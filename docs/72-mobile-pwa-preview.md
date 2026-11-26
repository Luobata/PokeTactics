# 72 · 手机预览：常驻服务、可安装网页 App 与真机 E2E（2026-11-27）

> 目标：以后都在手机上体验 /play，并尽量接近原生 App——从主屏幕图标全屏打开、开战不熄屏、大招有震感、横竖屏都能玩。
> 范围：预览部署（`tools/preview/`）、PWA 外壳（`tools/acceptance/pwa/`、`play_sw.js`、`play_mobile.{js,css}`、`server.py` 路由与 HTTPS）、
> 战斗渲染器的震动提示事件（`battle_renderer.js` 只加事件，不改画面）、真机脚本 `tools/acceptance/android_e2e.py`。
> 不改玩法规则与数值。PMD 精灵仅限非商业使用：预览只在公司内网 / VPN 内提供，**不要**把端口映射到公网。

下文 `<开发机IP>` 指运行预览的机器的内网地址（`hostname -I` 第一项）；安装脚本结束时会打印实际地址。

## 1. 常驻预览服务（systemd --user）

| 项 | 值 |
|---|---|
| 地址 | `http://<开发机IP>:8820/play`（HTTP，内网 / VPN 直接打开即可玩） |
| HTTPS | `https://<开发机IP>:8821/play`（安装网页 App 用，需先信任预览 CA，见第 3 节） |
| 监听 | `0.0.0.0`，端口可用 `PREVIEW_PORT` / `PREVIEW_TLS_PORT` 改 |
| 代码 | 独立 worktree `../PokeTactics-preview`（detached，跟随 `main`），不影响日常开发目录 |
| 存档 | `~/.local/share/poketactics-preview/saves`（在 worktree 之外，更新代码不丢档） |
| 运行环境 | `~/.local/share/poketactics-preview/venv`（Python + Pillow） |

安装 / 更新配置（幂等，可重复执行）：

```sh
tools/preview/install.sh              # 默认 http 8820 / https 8821
loginctl enable-linger "$USER"        # 只需一次：不登录也能开机自启
```

它会：检查端口是否被占用 → 创建 worktree 与 venv → 生成证书 → 把 `run.sh`、`update.sh` 复制到
`~/.local/share/poketactics-preview/bin/`（运行脚本不随 checkout 变化）→ 写入并启用三个单元：

* `poketactics-preview.service`：`Restart=always`、`WantedBy=default.target`，崩溃 3 秒后重启，开机自启（需 linger）。
* `poketactics-preview-update.timer` → `poketactics-preview-update.service`：每 2 分钟 `git fetch origin main`，
  有新提交就把 worktree 切到新提交并重启服务；本机 `main` 已包含 `origin/main`（本地已提交、尚未推送）时跟随本机 `main`；
  worktree 有人改过文件时拒绝更新，不会覆盖。

常用命令：

```sh
systemctl --user status poketactics-preview           # 运行状态与当前提交
journalctl --user -u poketactics-preview -f           # 日志
journalctl --user -u poketactics-preview-update       # 自动更新记录
systemctl --user start poketactics-preview-update     # 立刻检查一次 main
systemctl --user disable --now poketactics-preview poketactics-preview-update.timer   # 停用
```

HTTPS 依赖本次新增的 `--tls-port`：`run.sh` 只在 worktree 里的 `server.py` 支持该参数时才开 8821，
所以本分支合入 `main` 之前服务只有 HTTP，合入后最多 2 分钟自动带上 HTTPS 与网页 App。

## 2. 可安装的网页 App（PWA）与手机体验

| 能力 | 实现 |
|---|---|
| 清单 | `/play/manifest.webmanifest`：名称、`display: fullscreen`（`display_override` 回退 `standalone`）、`orientation: any`、`start_url: /play?source=pwa`、`scope: /play`、主题色 |
| 图标 | `tools/acceptance/pwa/`：192 / 512、512 maskable（安卓自适应图标）、180 `apple-touch-icon`；原创图案，由 `make_pwa_icons.py` 生成 |
| Service Worker | `/play/sw.js`（服务端注入版本号，响应头 `Service-Worker-Allowed: /play`）。只缓存静态资源：`/play/assets/*`、图标、清单、`/demo/sprite/*`、`/pmd/thumb/*` 进 `pt-shell-<代码版本>`，PMD 帧动画图集进 `pt-media-<精灵索引版本>`；`/api/*`、存档、备份、战斗脚本和所有非 GET 请求**一律走网络** |
| 版本失效 | 代码版本 = 外壳文件（play 页 JS/CSS、HTML、图标、清单、SW 本身）的哈希。任一文件变化 → 浏览器装新 SW → `activate` 删除旧 `pt-*` 缓存；页面提示「新版本已就绪 · 刷新」。精灵图集只在重新导入 PMD 时失效 |
| 离线 | 导航请求网络优先；开发机不可达时打开缓存的外壳，由页面自己报告连不上服务器（游戏仍以服务端为准） |
| 安装按钮 | HUD 工具栏的「⇩」：Chrome 触发 `beforeinstallprompt` 后出现，点开即系统安装对话框；已安装 / 全屏运行时隐藏 |
| 防熄屏 | 战斗弹窗打开时申请 `navigator.wakeLock('screen')`，切到后台被系统收回后回到前台自动重新申请，关闭弹窗即释放 |
| 震动 | 渲染器在正向播放越过「大招命中」和「克制命中」时派发 `battle:cue`；我方大招 `[40,30,70]`、敌方大招 `[25,40,25]`、克制 `[28]`，160ms 内连击合并为一次，后台不震。HUD「震动」开关（`localStorage poketactics.vibrate`）同时关闭操作失败的震动反馈。iOS 无 `navigator.vibrate`，开关自动隐藏 |
| 音频解锁 | 第一次点击 / 触摸结束时，在同一手势内恢复背景音乐与音效的 `AudioContext`（iOS 只允许手势内启动），并播放 1 个采样的静音缓冲唤醒输出 |
| 安全区 | 已有：`viewport-fit=cover`、标签栏 / 弹层 / 战斗弹窗的 `env(safe-area-inset-*)`。新增：全屏 App 中站点导航让出状态栏与刘海，横屏左右让出圆角与挖孔 |
| 横竖屏 | 清单 `orientation: any`；竖屏 / 横屏布局沿用 docs/61、docs/68；旋转后复位滚动；`<html>` 带 `orient-portrait/landscape`、`app-installed` 与 `data-display-mode` 供样式使用 |
| 原生手感 | `touch-action: manipulation`（去掉双击缩放延迟）、去掉点击灰色高亮、全屏 App 中禁止下拉刷新与回弹（避免误刷新正在进行的对局）、棋盘区域禁止长按选字 |

## 3. HTTPS：为什么需要，怎么选

Service Worker、安装网页 App、Wake Lock 都只在**安全上下文**里可用：`https://…` 或 `http://localhost`。
手机用 `http://<开发机IP>:8820` 打开时页面照常可玩，但这些能力全部不可用（Chrome 菜单里的「添加到主屏幕」只会建一个普通书签式快捷方式，打开仍带地址栏）。

可选方案与取舍：

| 方案 | 适用 | 代价 |
|---|---|---|
| **A. 预览 CA + HTTPS 8821（默认提供）** | 安卓 Chrome、iOS Safari | 手机要装一次 CA 证书 |
| B. Chrome 标志 `unsafely-treat-insecure-origin-as-secure` | 只限安卓 Chrome，不想装证书时 | 每台手机手动设置；标志页提示不安全 |
| C. USB / 无线调试 + `chrome://inspect` 端口转发，打开 `http://localhost:8820` | 开发者自己的手机 | 依赖电脑连接，断开即不可用 |
| mkcert | — | 本机未安装；它的本质同 A（本地 CA），A 用 openssl 实现且额外加了名称约束 |
| 公网证书（Let's Encrypt 等） | — | 需要公网域名 / DNS，且会把 PMD 精灵暴露到公网，**不采用** |

方案 A 的证书由 `tools/preview/make_cert.sh` 生成（`install.sh` 自动调用），在 `~/.local/share/poketactics-preview/certs/`：

* `ca.crt`：预览 CA。带 **critical 名称约束**，只能为开发机的 IP（局域网 + VPN）和 `localhost` 签发证书——
  即使私钥泄露，也无法冒充任何其他网站，手机信任它的风险被限定在这台开发机。`ca.key` 权限 600，不进仓库、不对外提供。
* `server.crt`：397 天有效（Chrome / iOS 对服务器证书的上限内）；重新执行 `install.sh` 只换服务器证书、保留 CA，已信任的手机无需重装。
* 服务端在 `http://<开发机IP>:8820/ca.crt` 提供 CA 公钥证书下载（只有公钥）。
* 开发机 IP 变了（例如 VPN 重新分配）：重新执行 `tools/preview/install.sh` 即可，CA 不变。

### 安卓（Chrome）信任预览 CA

1. 手机连公司 Wi-Fi 或 VPN，用 Chrome 打开 `http://<开发机IP>:8820/ca.crt`，下载 `PokeTactics-preview-CA.crt`。
2. 打开「设置」→「安全与隐私」→「更多安全设置」→「加密与凭据」→「安装证书」→「CA 证书」
   （不同品牌路径略有差异，可在设置里搜索「CA 证书」或「安装证书」）。
3. 系统提示「您的数据将不再是私密数据」，点「仍然安装」，选择刚下载的 `PokeTactics-preview-CA.crt`。
   部分机型要求先设置锁屏密码。
4. 回到 Chrome 打开 `https://<开发机IP>:8821/play`，地址栏不再报证书错误即成功。
   之后可在「加密与凭据 → 受信任的凭据 → 用户」里随时删除该 CA。

### iOS（Safari）信任预览 CA

1. 用 Safari 打开 `http://<开发机IP>:8820/ca.crt`，允许下载描述文件。
2. 「设置」→「已下载描述文件」→ 安装。
3. 「设置」→「通用」→「关于本机」→「证书信任设置」→ 打开「PokeTactics Preview CA」的完全信任。

### 方案 B（安卓，不装证书）

Chrome 打开 `chrome://flags/#unsafely-treat-insecure-origin-as-secure`，启用并在文本框填 `http://<开发机IP>:8820`，
点「重新启动」。之后 `http://<开发机IP>:8820/play` 被当作安全来源，可安装、可用 Service Worker 与防熄屏。

## 4. 手机上安装体验（一步一步）

**安卓 Chrome**

1. 手机连公司内网或 VPN。只想试玩：直接打开 `http://<开发机IP>:8820/play`。
2. 要全屏 App：先按第 3 节信任预览 CA（或用方案 B），然后打开 `https://<开发机IP>:8821/play`。
3. 点 HUD 工具栏的「⇩ 安装到主屏幕」按钮（或 Chrome 右上角「⋮」→「添加到主屏幕」/「安装应用」）→「安装」。
4. 若桌面弹出「添加到主屏幕」确认卡片，点「添加到主屏幕」。
5. 回到桌面，点「PokeTactics」图标：全屏打开，无地址栏。代码更新后打开 App 会提示「新版本已就绪」，点「刷新」。

**iPhone Safari**

1. 按第 3 节信任 CA，Safari 打开 `https://<开发机IP>:8821/play`。
2. 点分享按钮 →「添加到主屏幕」→「添加」。从桌面图标打开即为全屏（iOS 不支持震动，开关自动隐藏）。

## 5. 真机 E2E：`tools/acceptance/android_e2e.py`

只依赖 Python 标准库和 `adb`。流程：

1. 选设备（`--serial`，或唯一的 `adb devices`）、点亮解锁、`svc power stayon`、开始 `screenrecord`。
2. 通过 adb 直连手机 Chrome 的 DevTools 套接字（`localabstract:chrome_devtools_remote`，无需 `adb forward` 监听端口）。
3. 打开方式：
   * `--via tether`（默认）：Chrome DevTools 端口转发（`Tethering.bind`），手机访问 `http://localhost:<端口>`，
     每条连接经 adb 送到本机服务。`localhost` 是安全上下文，SW / Wake Lock / 安装都能测。
     也适用于 `adb reverse` 不可用的环境（Dora 云真机的 adb 中继就不支持 reverse）。
   * `--via direct --url http://<IP>:8820/play`：手机自己经网络访问，用来证明内网 / VPN 可达。
4. `am start` 用 Chrome 打开页面，清空该来源的数据（新玩家），然后完成一整回合：选海克斯 → 打开商店 → 点卡片 →
   从操作条「招募」→ 点备战席 → 点棋盘空格 → 开始战斗 → 等待战果 → 下一轮，进入第 2 轮。
   每步断言状态（金币减少、备战席 / 人口变化、战斗弹窗与渲染器就绪、Wake Lock 持有与释放、回合号）并截图。
5. 检查 PWA：清单、SW 激活并接管页面、缓存名、`beforeinstallprompt`。
6. `--install`：点页面「安装」按钮 → 点 Chrome 的「安装」→ 点桌面的「添加到主屏幕」→ 回桌面点新图标 →
   断言新窗口 `display-mode` 为 `fullscreen`/`standalone` 且为 `WebappActivity`，截图。
7. 收集 JS 异常、`console.error`、HTTP ≥ 400 与失败请求，有则判失败；输出 `summary.json`、逐步截图和录屏。

```sh
# 1) 准备设备：USB 插手机并打开 USB 调试；或无线调试 adb pair/connect；
#    或申请 Dora 云真机（rax-cli）：
BYTEDCLI_CLOUD_SITE=cn rax dora request --os android --manufacturer google --minutes 120 --no-provision --json
adb devices

# 2) 一整回合 + 安装 + 全屏（默认转发到本机 8820 的预览服务；分支自测可指向任意本地端口）
python3 tools/acceptance/android_e2e.py --port 8820 --install
# 同一部手机重复安装测试：换一个手机侧端口 = 新来源 = 尚未安装
python3 tools/acceptance/android_e2e.py --port 8820 --phone-port 8841 --install
# 3) 手机经网络直连（证明内网 / VPN 可达）
python3 tools/acceptance/android_e2e.py --via direct --url http://<开发机IP>:8820/play
# 用完释放云真机
BYTEDCLI_CLOUD_SITE=cn rax dora release <serial> --json
```

证据默认写到 `reports/evidence/android-e2e-<时间>/`（`--out` 可改）。

实现要点与限制：

* Dora 云真机会杀掉 `uiautomator dump`（其自动化代理占用了无障碍连接），脚本因此不依赖它：
  系统对话框按钮由 `dumpsys activity top` 的视图树按资源 id 定位（相对坐标逐级累加）；桌面新图标用安装前后的图标位置对比找出，并按所在页滑动后点击。
* Chrome 对新弹出的安装对话框有防点击劫持保护，刚出现时的点击会被忽略，脚本会间隔重试直到对话框关闭。
* `localhost` 与内网 IP 来源拿不到 WebAPK（需要 Google 服务器能访问到清单），Chrome 退回为带 Chrome 角标的主屏快捷方式；
  打开后同样是 `WebappActivity` 全屏，体验一致。
* 云真机到开发机 VPN 地址的网络偶发卡住单条 TCP 连接；页面加载超时会自动重载一次再判失败。

## 6. 验证与已知限制

* 测试：`tests/test_play_mobile.py`（清单 / 图标尺寸、SW 版本与预缓存清单、HTTPS 与名称约束、坏握手不影响服务、
  `/ca.crt`、安装脚本与自动更新（临时仓库实跑 `update.sh`）、视图树解析）+ `tests/frontend/play_mobile.js`
  （震动开关与节流、Wake Lock 获取 / 重获 / 释放、SW 注册与安装按钮、SW 路由只缓存静态资源、版本替换与离线外壳、渲染器提示只在正向播放时派发）。
* 真机：Pixel 9a / Android 15 / Chrome 157（Dora 云真机）跑通一整回合、安装与全屏打开；证据见 PR 与 `reports/evidence/mobile-pwa-2026-11-27/`。
* 已知限制：
  * Chrome 标签页模式下（地址栏占高度，视口高度约 ≤ 780px），商店「peek」弹层会盖住备战席，需要先收起商店再点备战席（main 上同样如此，与本次改动无关）；
    安装后的全屏 App 视口更高（Pixel 9a 为 923px），不受影响。
  * 内网 IP 的 HTTP 地址不能安装 / 不能用 SW 与防熄屏，需 HTTPS + 信任 CA 或方案 B。
  * 证书信任步骤在真机上需要人工操作；云真机不能自动化系统设置（uiautomator 被禁用），这一步未在云真机上实测，已用 openssl / Python TLS 客户端验证证书链与名称约束。
  * HTTPS 端口要等本分支合入 main 后，常驻服务才会自动开启。
