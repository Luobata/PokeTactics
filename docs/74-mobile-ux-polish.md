# 74 · 手机交互打磨与手机端前端重构（2026-11-27）

> 起因：用户反馈手机上的交互和 UI 细节不好。先在安卓云真机上用壳 App 实际玩了 4 轮、看了小屏 / 大屏，
> 问题清单见 [reports/mobile-ux-audit-2026-11-27.md](../reports/mobile-ux-audit-2026-11-27.md)（22 条，高 5 / 中 11 / 低 6）。
> 本篇记录：重构前后的结构、统一弹层栈、手机交互层的实现、壳 App 的配合、分支预览与验证。
> 不改玩法规则与平衡数值；桌面布局不变（同局面截图逐像素对比，见 §8）。

## 1. 为什么要重构

审计时发现，手机上的问题有一半出在结构上，不是单点样式：

| 现象 | 结构原因 |
|---|---|
| 返回键关弹层时好时坏 | 壳 App 的 `onBack()` 派发一个假的 Esc 键盘事件，再用 MutationObserver 看 DOM 有没有变化来猜「是否关掉了东西」；Esc 处理分散在 10 个脚本里（有的捕获阶段 `stopPropagation`，有的冒泡阶段），关闭顺序取决于脚本加载顺序 |
| 手机样式难改、互相覆盖 | `play_layout.css` 2249 行里 560 行是手机规则，和桌面规则交错；另有手机规则散在 `play_interactions.css`、`play.css` 的媒体查询里 |
| 层级冲突（吐司盖 HUD、菜单盖弹层） | 70 多处 `z-index` 魔法数字分布在 13 个样式表，没有统一的层级表 |
| 手机交互（拖拽、长按、拇指区按钮）无处安放 | 手机只是桌面布局的一组覆盖样式，没有「手机交互」这一层 |

## 2. 设计变量：`play_tokens.css`

第一个加载的样式表，只定义变量：

* **层级表**：`--z-context-bar 8 · --z-sheet 40 · --z-scout-docked 42 · --z-dock 45 · --z-ix-sheet 65 · --z-augment 70 ·
  --z-undo 75 · --z-tree 80 · --z-branch 82 · --z-menu 84 · --z-guide 86/87 · --z-glossary 88 · --z-ctx 89/90 · --z-toast 100 ·
  --z-select 119/120 · --z-app-update 120 · --z-drag 130`。数值就是改造前各文件里的数字，只是起了名字；
  原来写死数字的 18 处改成 `var(--z-…, 原值)`（带回退值，单独加载某个样式表的单测不受影响）。
* **触控**：`--touch-min 44px`、`--touch-row 48px`。
* **字号**：`--fs-2xs 10 / xs 11 / sm 12 / md 14 / lg 16 / xl 20`；手机上玩家要读的字不小于 `--fs-xs`。
* 间距、圆角、动效时长，手机 HUD 高度 `--phone-hud-h 46px`、壳 App 挖孔区颜色 `--app-letterbox #14231b`。

## 3. 重构前后的结构

### 改造前

```
play.html
 ├─ play.css            旧组件样式 + 24 个媒体查询（含部分手机规则）
 ├─ play_layout.css     桌面布局 + 手机布局（第 1442–2000 行）+ 深度字段 + 吐司/选秀的手机规则
 ├─ play_interactions.css  海克斯/技能/道具时刻 + 31 条 layout-phone 规则
 ├─ play_mobile.{js,css}   PWA/SW/防熄屏/震动 + 壳 App 返回钩子（假 Esc + DOM 观察）
 └─ 10 个脚本各自监听 Esc
```

### 改造后

```
play.html（加载顺序即层叠顺序）
 ├─ play_tokens.css        设计变量（层级 / 触控 / 字号 / 间距）           ← 新
 ├─ play.css · battle.css
 ├─ play_layout.css        桌面与通用布局（手机块已移出，1691 行）
 ├─ play_layout_phone.css  手机布局几何：原样搬出的 559 行（紧跟 play_layout.css）← 新
 ├─ play_interactions.css … play_mobile.css
 ├─ play_phone.css         手机交互层样式（HUD 菜单、拖拽、吐司、字号下限……） ← 新，最后加载
 │
 ├─ play_layout.js         只管「显示哪个面板」：手机/桌面判定、弹层尺寸（新导出 measure()）
 ├─ play_overlay.js        统一弹层栈：返回键与 Esc 都只关最上层            ← 新
 ├─ play_mobile.js         平台胶水：PWA、SW、防熄屏、震动、壳 App 桥；onBack() → PlayOverlay
 ├─ play_phone.js          手机交互层（PlayPhone.render(ctx)）              ← 新
 └─ play.js                规则与数据不变；新增 actions.move()、toast 时长询问 PlayPhone
```

分层约定：

| 层 | 文件 | 负责 | 不做 |
|---|---|---|---|
| 规则 / 数据 | `play.js`、`play_depth.js` | 调服务端、维护 state、渲染面板内容 | 不判断手机/桌面 |
| 布局 | `play_layout.js` + `play_layout*.css` | 面板开关、弹层几何、徽标、棋盘提示 | 不调服务端 |
| 弹层栈 | `play_overlay.js` | 哪个弹层在最上面、返回/Esc 关哪个 | 不渲染 |
| 手机交互 | `play_phone.js` + `play_phone.css` | 拇指区操作、触屏拖拽、反馈时机、菜单 | 不改规则，所有变更走 `ctx.actions` / `ctx.api` / `data-*` |
| 平台 | `play_mobile.js` | PWA / 壳 App / 震动 / 防熄屏 | 不碰游戏 DOM |

手机布局块的搬家用 Playwright 验证：同一局面、原文件 vs 拆分后，在 411×865、360×731、844×390、820×1180、1280×760、1600×900
六个视口逐元素比较 30 个计算样式属性，除吐司的显示时机和横屏下一个随测量漂移的 0.5px（原文件对原文件也会漂）外完全一致。

## 4. 统一弹层栈：`play_overlay.js`

一张有序表列出所有玩家能关掉的层，每项登记层级、`isOpen()`、`close()`：

| 层级 | id | 关闭方式 | 备注 |
|---|---|---|---|
| 95 | `context-menu` 长按菜单 | `PlayContext.close()` | above |
| 92 | `term-card` 术语卡 | `PlayPreview.hide()` | above |
| 90 | `select` 自定义下拉 | `PlaySelect.close(true)` | above |
| 88 | `guide` 首次引导 | `PlayGuide.finish()` | above |
| 84 | `menu` 手机菜单（`play_phone.js` 注册） | 关闭菜单 | above |
| 80 | `dialog` 普通模态框（帮助、新开一局、图鉴、历史战报） | 派发 `cancel`，没人拦就 `close()` | blocking |
| 78 | `phase-dialog` 战斗 / 结算 | **不可关** | blocking |
| 60 | `ix-sheet` 确认面板 | `PlayInteractions.dismiss()` | 升星强化等同「稍后再选」 |
| 58/57 | `tree` / `branch` 合成树、进化分支 | 各自 `close()` | |
| 55 | `weather` 天气说明 | `PlayWeather.close()` | |
| 50 | `augment` 海克斯时刻 | 按「先看看棋盘」 | 改造前返回键对它无效 |
| 48 | `draft` 共享选秀 | 按「稍后再选」 | |
| 45 | `target-mode` 装备/技能机目标模式 | `PlayInteractions.dismiss()` | |
| 40 | `scout` 停靠的对手侦察 | 派发 `cancel` | |
| 20 | `sheet` 手机底部弹层 | `PlayLayout.close()` | 桌面侧边抽屉不算弹层 |
| 10 | `selection` 当前选中 | `ctx.actions.clear()` | 输入框里按 Esc 不清选中 |

规则：层级高的先关；有 `blocking` 的模态框打开时，只有它本身和标了 `above` 的层（菜单、卡片、引导会画在模态框上面）可关，
被它挡住的弹层不会被「隔空关掉」；战斗 / 结算对话框不可关——返回键返回 `false`，壳 App 弹「退出游戏？」，
Esc 则放行给对话框自己的 `cancel` 处理（桌面上 Esc 仍是「下一轮」）。

* 返回键：`PokeTacticsShell.onBack()` → `PlayOverlay.closeTop("back")`，返回关掉的 id（`status.last.changed`），壳 App 日志里能看到。
  旧页面没有 `play_overlay.js` 时才走原来的「假 Esc」路径。
* Esc：`window` 捕获阶段统一处理，关掉了才 `preventDefault + stopImmediatePropagation`；各模块原有的 Esc 监听保留（单独加载时仍可用），
  但在完整页面里不会再被触发。
* 新增弹层：`PlayOverlay.register({id, layer, isOpen, close, above?, blocking?})`，不用再去每个文件接 Esc。

## 5. 手机交互层：`play_phone.js` / `play_phone.css`

对应审计编号：

| 编号 | 实现 |
|---|---|
| H2 页头 | 手机布局隐藏站点导航（`--nav-h: 0`）；HUD 一行：回合 · 生命 · 金币 · 人口 · 等级+经验条+`4/10` · 「≡ 菜单」（≤380px 只留图标）；连胜/连败挂在回合牌下角。HUD 工具按钮在手机上隐藏，菜单面板的行**代理**原按钮（点击转发、开关状态镜像），所以音乐 / 音效 / 震动 / 引导 / 指南 / 存档 / 新开一局 / 安装的逻辑仍只在 `play.js`、`play_mobile.js` 里；站点链接（营地首页 / 战术图鉴 / 玩法指南）从站点导航里取，不含「调试工具」 |
| H1 / M9 棋盘高度 | 竖屏手机由 `fitTiles()` 量出「备战席底边以上除 6 行格子外的高度」，格子高度 = (标签栏顶 − 200px 商店 − 其余) / 6，夹在 34px 与格子宽度之间；格子宽度上限 62→74px。改变后调用 `PlayLayout.measure()` 重新量弹层高度（否则半屏弹层会从旧高度动画过来，被场景几何测试抓到过）。测量放进 `requestAnimationFrame`，每帧最多一次 |
| H3 触屏拖拽 | Pointer 事件：在己方棋子上按下、移动超过 10px 拿起（长按菜单 450ms 内不动才出，互不冲突）；手指上方跟一个精灵「幽灵」，可放空格虚线、手指下格子实线高亮；松手调用 `actions.move(from, to)`（与鼠标拖放同一个 `move` 命令）。棋盘格 `touch-action: none`；备战席 `touch-action: pan-x`，横向起手是滚动、纵向起手才拿起（与浏览器的判定一致——斜着起手会被浏览器抢去滚动，真机上踩过） |
| H4 长按 | `play_context.js`：`pointercancel` 和菜单关闭时清掉 `eatClick`；手机上游戏界面 `user-select: none`、`-webkit-touch-callout: none`（输入框除外） |
| H5 吐司 | `play.js` 的 `toast()` 先问 `PlayPhone.toastHold()`：手机上普通 1.8s、错误 3s，「X 移动」和「升级！…」（有横幅）不弹；位置在 HUD 下方（`--toast-top` 量出），单行省略 |
| M1 招募 | 选中商店卡时，卡片下沿浮出「招募 · N 金」/「还差 N 金」（`data-shop-buy`，沿用 `play.js` 的处理器），在弹层里、拇指可及 |
| M2 操作条 | 竖屏两行：名字行 + 自动换行的按钮行（≥44px 高），× 固定在右上 |
| M3 | 选中己方棋子时 `body.unit-picked`，空格与空备战席显示与拖拽相同的虚线 |
| M4 字号 | 标签栏文字、操作条说明、面板正文、商店升星进度提到 11–12px；备战席名字移到格子下沿 |
| M5 战斗弹窗 | 手机上 × 改为「跳过 ›」，底栏去掉「重开一局」和图例，隐藏「画风」选择，「ROUND JOURNAL」显示为「本轮战报」 |
| M6 结算 | 记下准备阶段的生命值，战果卡出现时加一行「生命 100 → 94（−6）」/「生命无损」（所有布局都有） |
| M7 海克斯 | 手机卡片只显示名称、简述、适配度、第一条理由和选择按钮；「完整说明 · 理由与选择后变化」展开其余；三张同屏 |
| M8 加载 | 精灵图加载完成前显示柔和的精灵球剪影占位，加载后淡入（捕获阶段监听 `load` / `error`） |
| M11 等待 | 手机上请求挂起超过 0.7s，HUD 下方显示「同步中…」（纯 CSS，挂在 `body.is-busy`）；`play.js` 原有 12s 超时与「继续存档」不变 |
| L1 文案 | 触屏（`pointer: coarse`）的提示只写「长按 / 双击」，不写右键 / Esc / 空格 |
| L5 | 已买走的商店卡位缩成 30px 窄条 |

## 6. 壳 App 的配合

* 网页侧返回钩子的协议不变（`PokeTacticsShell.onBack()` 返回布尔值），壳 App 不需要改逻辑。
* L4：沉浸模式下挖孔区留出的那条边（`root` 的 padding）从近黑色 `#10141C` 改为 HUD 同色 `#14231B`（`pt_letterbox`）。
* 重新构建：`tools/android/build.sh`，versionCode = 提交数（1.0.139），**同一把签名**（`~/.config/poketactics-android/shell.jks`），可以覆盖安装。

## 7. 预览：分支服务与壳 App 切换

合并前，分支跑在一个独立的常驻服务上（与 main 的预览互不影响，存档分开）：

| 项 | 值 |
|---|---|
| 地址 | `http://<开发机IP>:8830/play`、`https://<开发机IP>:8831/play`（同一张预览证书，壳 App 内置信任） |
| APK | `http://<开发机IP>:8830/app`（1.0.139，默认地址就是 8831 分支服务） |
| 代码 | worktree `../PokeTactics-branch-preview`，每 2 分钟跟随 `origin/feat/mobile-ux-polish` |
| 配置 | `~/.config/poketactics-preview/branch.env`；单元 `poketactics-branch-preview.service` + `poketactics-branch-preview-update.timer`（systemd --user） |
| 存档 / APK 目录 | `~/.local/share/poketactics-preview/saves-branch`、`app-branch` |

已装壳 App（1.0.132）的手机切到分支服务：**两指同时按住屏幕 2 秒** → 隐藏设置页 → 服务器地址填
`https://<开发机IP>:8831/play`（VPN 用户填 VPN 地址）→「保存并重新加载」。切回 main：同一页点「恢复默认地址」。
想连壳 App 的挖孔区颜色一起看，就从 `:8830/app` 下载 1.0.139 覆盖安装（它的默认地址就是分支服务；合并后再从 `:8820/app` 装 main 的新包）。

合并后：常驻预览（8820/8821，跟随 main）2 分钟内自动更新网页；在 main 检出里执行 `tools/android/build.sh` 把新 APK 发布到 `:8820/app`；
然后可以停掉分支服务：`systemctl --user disable --now poketactics-branch-preview poketactics-branch-preview-update.timer`。

本次也把常驻预览改回了跟随 `main`（PR #1 / #2 已合并，`~/.config/poketactics-preview/env` 的 `PREVIEW_BRANCH=main`，docs/73 §5 的待办）。

## 8. 验证

* **真机 E2E**（Pixel 9a / Android 15 / WebView 158，Dora 云真机，壳 App 1.0.139）：`tools/android/shell_e2e.py` 全部 28 项通过——
  一整回合（选海克斯 → 招募 → 上场 → 开战 → 战斗中按返回只弹确认不跳过 → 战果 → 第 2 轮），新增的手机交互阶段
  （一行 HUD / 菜单按钮；商店不盖备战席、卡片上「招募」；**真实手指**拖拽上场；长按不选字、返回关菜单后下一次点击生效；
  菜单开关驱动真实按钮、返回关闭），以及返回键 / 边缘侧滑 / 「退出」。
  证据：`reports/evidence/mobile-ux-2026-11-27/e2e/`（截图已缩小、去掉地址页；`summary.json`、`logcat.txt`）。
* 云真机到开发机 VPN 地址这次丢包严重（`ping` 80% 丢包，页面脚本和 API 请求反复卡住），所以 E2E 新增
  `--tether-port`：在壳 App 的 WebView 上做 DevTools 端口转发（`Tethering.bind`），手机 `http://localhost:8851` 经 adb 到本机服务，
  不经过 VPN；`localhost` 是安全上下文，Service Worker / Wake Lock 照常。经 VPN 的直连路径在 docs/73 已验证过，这次网络条件下没能跑完。
  另外加了一次「页面加载卡住就重启 App」的重试（WebView 重载会复用卡住的连接，重启不会）。
* **改前 / 改后对比**：`reports/evidence/mobile-ux-2026-11-27/compare/`（同一台云真机、同一视口 411×865 / 360×731 / 480×1010）。
* **桌面**：同一种子同一局面，main 与分支在 1280×760、1440×900 截图逐像素对比，差异像素 0.00%（阈值 24/255）；HUD、站点导航、工具栏、
  棋盘与备战席尺寸完全一致：`reports/evidence/mobile-ux-2026-11-27/desktop/`。
* **单测与前端场景**：全量 `python -m unittest discover -s tests` 1167 项，只有 main 上已知的两项失败
  （`continuous_forward_playback`、`bond_depth_migration real_terminal_predecessor`），与 main（1156 项，同样两项）一致。新增：
  `tests/test_play_phone.py`（静态：层叠顺序、手机规则归属、层级变量、菜单代理目标存在；Node VM：弹层栈 6 个场景；
  Chromium：390×844、360×740 触屏流程 + 1280×760 桌面不变）。`test_play_layout` 的场景几何测试照常通过。

## 9. 没做的 / 已知限制

* L6「一键上场」按职业挑行，5 只常常全在前排——属于布阵规则，不在本次范围。
* 小屏（360×731）格子仍只有 34px 高（为商店弹层留出空间），低于 44px 建议；宽度 46px，实际可点面积够用，但更矮的屏幕可以考虑商店打开时压缩敌方半场。
* 触屏拖拽只覆盖棋盘 / 备战席之间移动；从商店拖到备战席购买、拖到商店出售没有做（避免误卖）。
* 两指按住打开设置页仍无法用 adb 注入多点触控验证（docs/73 已知）。
* 横屏手机（docs/68 的场景内 HUD）只做了菜单按钮替换工具栏，没有重新审计。
* iOS 仍未覆盖（docs/73 §8）。
