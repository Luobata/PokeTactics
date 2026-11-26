# 73 · 安卓壳 App：防误触返回的原生外壳（2026-11-27）

> 起因：网页版（包括 docs/72 的「添加到主屏幕」网页 App）在手机上太容易误触回退——系统返回键、边缘侧滑一碰，
> 页面就后退或整个 App 退到后台。目标：做一个安卓客户端，里面仍然跑常驻预览的 `/play`，但返回由我们接管。
> 范围：`apps/android/`（Kotlin + Gradle 的 WebView 壳）、`tools/android/`（SDK 安装、构建、真机 E2E）、
> `play_mobile.js` 的壳钩子、`server.py` 的 `/app` 下载页、预览脚本的 APK 目录。不改玩法规则与数值。
> 依赖 docs/72（PWA、预览 HTTPS 与 CA）；本分支基于 `feat/mobile-pwa-preview`。

下文 `<开发机IP>` 指预览机的局域网地址（本机 `10.37.30.198`）；云真机只能访问 VPN 地址（本机 `10.4.63.169`）。

## 1. 为什么是原生 WebView 壳，而不是 TWA / 网页 App

| 方案 | 返回键 | 结论 |
|---|---|---|
| 网页 / PWA（docs/72） | 浏览器决定：后退历史或退出 App；网页无法可靠拦截（`popstate` 只能事后补救，侧滑返回还会先触发后台动画） | 误触问题的来源 |
| TWA（Trusted Web Activity） | 返回由 Chrome 处理，宿主 App 拿不到；还要求公网 Digital Asset Links | 管不住返回键，不采用 |
| **原生 WebView 壳（本方案）** | `OnBackPressedDispatcher` 收到所有返回（按键、手势、Android 13+ 预测性返回），由我们决定做什么 | 采用 |

## 2. 返回键 / 侧滑返回现在的行为

壳 App 在 Manifest 里开启 `android:enableOnBackInvokedCallback="true"`，并注册一个始终启用的 `OnBackPressedCallback`，
所以系统返回键、手势导航的边缘侧滑、Android 13+ 的预测性返回都只会走到这一个回调；系统不会再播放「退回桌面」动画，
WebView 也**从不**调用 `goBack()`（不做 history.back）。回调的处理顺序：

1. 调用网页里的 `window.PokeTacticsShell.onBack()`（`play_mobile.js`）：
   * 先复用网页已有的 Esc 关闭逻辑：派发一个 Esc 按键事件，并用 MutationObserver 同步记录 DOM 是否变化。
     这一步覆盖手机抽屉（商店 / 背包 / 详情等，`play_layout.js`）、确认弹层与目标选择（`play_interactions.js`）、
     长按菜单（`play_context.js`）、术语卡（`play_preview.js`）、选择器、合成树 / 分支弹层、首次引导、当前选中的棋子 / 卡牌。
   * 没有变化时，关闭最上层的普通 `<dialog>`（帮助、新开一局确认、图鉴目录、历史战报、对手侦察），走它自己的 `cancel` 处理。
   * **对战弹窗与结算弹窗不会被返回关闭**：关闭对战弹窗等于进入下一轮，误触不能替玩家跳过战斗；
     对战上方的术语卡、引导等仍会先被关掉。
   * 返回 `true` 表示关掉了东西，壳 App 什么也不再做。
2. 网页返回 `false`（没有可关的）、没有钩子（例如打开的是图鉴等其他页面、旧服务端）、1.2 秒内无应答、
   或页面还没加载好（加载中 / 错误页）时，弹出原生确认框「退出游戏？」：
   * 「继续游戏」或再按一次返回：关闭确认框，留在游戏里；
   * 「退出」：结束 App（对局进度在服务器上，下次打开继续）；
   * 当前不在 `/play`（例如从站内导航进了图鉴）时多一个「回到对局」。
3. 沉浸式全屏下的边缘侧滑天然是两段式：第一次侧滑只唤出系统栏（约 2 秒后自动隐藏），
   系统栏显示期间再滑一次才是返回——再按上面 1、2 处理。
4. 「边缘防误触」（设置页，默认开）：屏幕左右边缘竖直居中的一段（系统上限每侧 200dp，Pixel 9a 上约 y=949–1474 像素，
   棋盘与备战席所在高度）用 `setSystemGestureExclusionRects` 排除系统手势，从这里滑动既不会唤出系统栏也不会返回，
   拖动棋子贴边时不再误触。

## 3. 原生体验

| 能力 | 实现 | 真机验证（§7） |
|---|---|---|
| 沉浸式全屏 | `WindowInsetsControllerCompat.hide(systemBars())` + `BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE`；回到前台 / 获得焦点 / 关闭确认框后重新隐藏；摄像头挖孔区域留黑边（内容不进挖孔） | `dumpsys window`：statusBars / navigationBars `visible=false`；侧滑唤出后自动隐藏 |
| 竖屏锁定 | Manifest `screenOrientation="portrait"`；设置页可改为跟随系统（`FULL_USER`） | 强制系统横屏时 App 仍是竖屏布局（视口 183×411，系统以竖屏信箱显示） |
| 防熄屏 | `FLAG_KEEP_SCREEN_ON`（整个 App 期间；网页的 Wake Lock 仍在战斗时申请） | 窗口 flags 含 `KEEP_SCREEN_ON` |
| 震动 | 网页 `PlayMobile.buzz()` 在壳里经 `PokeTacticsNative.postMessage({type:"vibrate",pattern})` 交给原生 `Vibrator`（`VibrationEffect.createWaveform`）；浏览器里仍用 `navigator.vibrate`；HUD 震动开关照旧 | logcat `vibrate [28]`、战斗中大招 / 克制震动 |
| 音频免点击 | `mediaPlaybackRequiresUserGesture = false`；网页在壳里于 DOMContentLoaded 后直接解锁背景音乐与音效（浏览器里仍等第一次点击） | 未点击前 `PlayMusic.state() === "running"` |
| 存储与缓存 | DOM storage、HTTP 缓存（`LOAD_DEFAULT`）、Service Worker（https 来源） | 存档槽位保存在 localStorage，重开 App 续玩 |
| 网络错误页 | 主文档加载失败、5xx、证书错误或 15 秒连不上时显示「连不上游戏服务器」+「重试」+「设置地址」 | 云真机首启（默认局域网地址不可达）即走这条路径 |
| 其他 | 文本缩放固定 100%、禁止缩放、站外链接交给系统浏览器、文件选择（备份导入）、渲染进程崩溃自动重建 WebView | — |

JS 桥用 `WebViewCompat.addWebMessageListener`，只注入到当前配置地址的来源（scheme + host + port），
其他网站拿不到；没有使用 `addJavascriptInterface`。

## 4. 地址与证书：默认 https 8821 + App 内置预览 CA

默认地址 `https://<开发机IP>:8821/play`。两种做法的取舍：

| 做法 | 优点 | 缺点 |
|---|---|---|
| A. 明文 `http://<开发机IP>:8820/play` + network security config 只放行这台机器 | 不需要证书 | 非安全上下文：Service Worker、Wake Lock 不可用；流量明文 |
| **B. `https://<开发机IP>:8821/play`，把预览 CA 打包进 App 的信任配置（采用）** | 安全上下文（SW 缓存精灵图集、Wake Lock 都能用）；**用户不需要在系统里装证书**；CA 带名称约束，只能为这台机器的 IP 签证书 | 需要 docs/72 的 HTTPS 端口（本分支已带） |

`tools/android/build.sh` 在构建时生成 `res/xml/network_security_config.xml`（不进仓库）：

* 其他所有域名：只允许 https、只信任系统 CA（`base-config cleartextTrafficPermitted="false"`）。
* 只对预览机的地址（从预览服务器证书的 IP 名里读出：局域网 + VPN + 127.0.0.1，外加 localhost）：
  信任打包进去的预览 CA **公钥证书**（`~/.local/share/poketactics-preview/certs/ca.crt`，私钥 `ca.key` 不进 APK、不进仓库），
  同时允许明文 http——这样在设置页里填分支服务器（例如 `http://<开发机IP>:8899/play`，`server.py` 默认不开 TLS）也能连上。
* `onReceivedSslError` 只是兜底：仅当证书确实由这把预览 CA 签发、主机在上述地址列表里、且未过期时才放行，其余一律拒绝。

CA 不变（`install.sh` 只换服务器证书），所以 App 不需要因为证书续期重新构建；如果重新生成了 CA，重新执行 `build.sh` 即可。

### 隐藏设置页

* 打开方式：**两指同时按住屏幕 2 秒**；或在「连不上游戏服务器」页点「设置地址」。
* 可设置：服务器地址（`http://` / `https://`，例如分支服务）、允许横屏、边缘防误触；「恢复默认地址」「清除网页缓存」
  （只清 HTTP 缓存，不清 localStorage，存档槽位保留）。保存后回到游戏并加载新地址。

## 5. 构建、签名与分发

```sh
tools/android/setup_sdk.sh     # 一次：JDK 17 → ~/.local/share/jdk/，Android SDK → ~/.local/share/android-sdk/（cmdline-tools、platform-tools、build-tools 36.0.0、android-36；不需要 sudo）
tools/android/build.sh         # 构建并发布到预览：http://<开发机IP>:8820/app
tools/android/build.sh --no-publish
SHELL_URL=http://10.37.30.198:8899/play tools/android/build.sh   # 换默认地址
```

* 工具链：AGP 8.13.2、Gradle 8.14.3（wrapper，首次自动下载）、Kotlin 2.2.21、compileSdk / targetSdk 36、minSdk 26。
  本机网络里 Java 走 IPv4 连不上 services.gradle.org / Maven，`build.sh` 设置了 `-Djava.net.preferIPv6Addresses=true`。
* 构建的是 debug 变体（可调试：WebView 远程调试给真机 E2E 用），但用**固定的自签名 key** 签名，以后的 APK 可以直接覆盖安装：
  * keystore：`~/.config/poketactics-android/shell.jks`（PKCS12，RSA 3072，30 年），
    密码在 `~/.config/poketactics-android/keystore.properties`（权限 600）。首次运行 `build.sh` 自动生成。
  * **不进仓库**（`apps/android/.gitignore` 忽略 `*.jks`、`*.keystore`、`keystore.properties`），请自行备份：
    丢了 key，新 APK 就无法覆盖已安装的 App，只能先卸载（存档在服务器上，不受影响）。
* 版本号：`versionCode` = 仓库提交数，`versionName` = `1.0.<提交数>`（有未提交改动时带 `-dev`）。
* 发布：APK 与元数据写到 `~/.local/share/poketactics-preview/app/`（`PokeTactics.apk`、`PokeTactics.json`），
  常驻预览以 `--app-dir` 提供：
  * 下载页 `http://<开发机IP>:8820/app`：版本、构建时间、代码提交、默认地址、签名证书与 APK 的 SHA-256、安装步骤；
  * APK `http://<开发机IP>:8820/app/PokeTactics.apk`（`application/vnd.android.package-archive`）。
  * 用 http 8820 是为了手机浏览器不需要先信任 CA 就能下载；装好后 App 自己用 https 8821。

### 常驻预览现在跟随本分支

`/app` 路由与 `--app-dir` 在本分支里，`main` 上的服务端还没有。为了让手机现在就能下载、App 默认地址就有返回钩子，
常驻预览的配置改成了 `PREVIEW_BRANCH=feat/android-shell`（`~/.config/poketactics-preview/env`，已重新执行 `install.sh`），
它包含 `main` + PR #1（PWA、HTTPS 8821）+ 本分支。合并后改回：

```sh
PREVIEW_BRANCH=main tools/preview/install.sh     # 在合并后的 main 检出里执行
```

## 6. 手机上安装（一步一步）

1. 手机连公司 Wi-Fi 或 VPN，用浏览器（Chrome）打开 `http://<开发机IP>:8820/app`，点「⇩ 下载 PokeTactics.apk」。
   浏览器提示「此类文件可能有害」时点「仍然下载」。
2. 下载完成后点通知栏里的下载完成通知（或 Chrome「⋮」→「下载内容」里的 `PokeTactics.apk`）。
3. 第一次安装会提示「出于安全考虑，您的手机目前不允许安装来自此来源的未知应用」：点「设置」→
   打开「允许来自此来源的应用」→ 返回。（以后也可以在「设置 → 应用 → 特殊应用权限 → 安装未知应用 → Chrome」里关掉。）
4. 点「安装」。Play 保护机制提示「未知开发者 / 未经扫描的应用」时，点「更多详情」→「仍然安装」（或「无论如何都要安装」）。
5. 点「打开」，或之后从桌面图标「PokeTactics」打开。首次打开即为全屏竖屏的游戏；不需要装证书。
6. 连不上（不在内网 / VPN 断开）时会显示「连不上游戏服务器」：连好网络后点「重试」；要连分支服务，点「设置地址」。
7. 更新：重新下载并安装即可覆盖（签名固定）；存档在服务器上，不会丢。

## 7. 真机 E2E：`tools/android/shell_e2e.py`

只依赖 Python 标准库与 `adb`，复用 docs/72 `android_e2e.py` 的 adb / DevTools 客户端与一整回合流程。

```sh
BYTEDCLI_CLOUD_SITE=cn rax dora request --os android --manufacturer google --minutes 120 --no-provision --json
python3 tools/android/shell_e2e.py --serial <adb-serial> --url https://10.4.63.169:8821/play \
    --download-page http://10.4.63.169:8820/app
BYTEDCLI_CLOUD_SITE=cn rax dora release <serial> --json
```

流程：（`--download-page`）手机 Chrome 打开下载页并截图 → 从预览的 `/app` 下载 APK（校验 MIME）→ `adb install -r` → 清空 App 数据（新玩家）→ 打开；
云真机访问不到默认的局域网地址，App 15 秒后显示错误页 → 点「设置地址」→ 填 `--url` → 保存 → 加载游戏 →
通过 App 的 WebView DevTools 套接字（`localabstract:webview_devtools_remote_<pid>`）驱动页面：

1. 原生检查：未点击时音频已在播放；系统栏不可见（窗口 insets + `dumpsys window`）；`KEEP_SCREEN_ON`；
   边缘防误触区域；原生震动；强制横屏时仍为竖屏布局。
2. 首次引导：按返回关闭引导。
3. 一整回合（`Run.play_round`）：选海克斯 → 商店 → 招募 → 备战席 → 上场 → 开战；**战斗中按返回**：
   先关掉战斗上方的浮层（如有），然后弹「退出游戏？」，再按返回关闭确认框，战斗不被跳过 → 战果 → 第 2 轮。
4. 返回键：商店抽屉打开时按返回 → 抽屉关闭；再按 → 「退出游戏？」→「继续游戏」→ 仍在同一页面、`history.length` 不变。
5. 边缘侧滑（脚本临时切到手势导航，结束后恢复原来的三键导航）：单次侧滑只唤出系统栏、不返回，系统栏自动再隐藏；
   在防误触带内连续侧滑：既不唤出系统栏也不返回；带外两段式侧滑：先关商店抽屉，再次则弹「退出游戏？」，按返回关闭。
6. 最后：返回 →「退出」→ App 真正退出（确认框不是死循环）。

每一步断言并截图；同时收集页面 JS 异常、`console.error`、HTTP ≥ 400，有则判失败。证据（逐步截图、录屏、App 的 logcat、
`summary.json`）写到 `reports/evidence/android-shell-<时间>/`；本次提交的证据在 `reports/evidence/android-shell-2026-11-27/`。

云真机注意：Dora 杀掉 `uiautomator`，原生控件用 `dumpsys activity top` 的视图树（见 docs/72）；
「退出游戏？」对话框不在该视图树里，脚本用键盘焦点按按钮（TAB 一次是「退出」，两次是「继续游戏」）；
logcat 是环形缓冲，脚本按行内容而不是行号去重。

## 8. iOS（以后）

暂不做。以后的方案：在 Mac 上用 Xcode 建一个 SwiftUI / UIKit App，内嵌 `WKWebView` 加载同一个 `/play`：
`allowsBackForwardNavigationGestures = false` 关掉边缘侧滑后退（iOS 没有系统返回键，侧滑后退是唯一误触来源），
`mediaTypesRequiringUserActionForPlayback = []` 免点击播放音频，`isIdleTimerDisabled` 防熄屏，
`WKScriptMessageHandler` 接同一个 `PokeTacticsNative.postMessage` 协议（震动用 `UIImpactFeedbackGenerator`），
预览 CA 通过 `URLAuthenticationChallenge` 校验内置证书；分发走 TestFlight 或企业签名（需要 Apple 开发者账号）。

## 9. 已知限制

* 只在 Pixel 9a / Android 15 / WebView 157（Dora 云真机）上实测；其他厂商的手势实现可能不同（例如部分系统在沉浸模式下侧滑直接返回），
  但无论哪种都只会走到同一个回调，不会离开游戏。
* 两指按住 2 秒打开设置无法用 adb 注入多点触控验证，真机 E2E 走的是错误页「设置地址」入口；两指入口需要人工在真机上试一次。
* 「安装未知来源应用」与 Play 保护机制的系统对话框在云真机上无法自动化（无 uiautomator），E2E 用 `adb install`；
  下载页与 APK 的可下载性由脚本校验 HTTP 与 MIME，并在手机 Chrome 里打开下载页截图。
* 默认地址是本机局域网 IP；换机器或 IP 后需要重新 `build.sh`（或在设置页改地址）。VPN 用户需在设置页改成 VPN 地址。
* debug 构建（可远程调试 WebView）：只用于内网预览，不要上架或外发；PMD 精灵仅限非商业使用（见 README「来源与边界」）。
* 预览服务目前跟随 `feat/android-shell`（§5），合并后记得改回 `main`。
