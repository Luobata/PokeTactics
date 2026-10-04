# 三键棋盘界面与页面视觉统一

本次把 `/device` 的准备与布阵操作放进真实队伍的棋盘画面，保留 A/B/C 三键完成游戏操作的约束。范围覆盖掌机页面，以及远征手册、完整棋盘、动画图鉴和动作编辑器的视觉规范。规则、商店价格与战斗数值未调整。

## 玩家能看到的变化

| 页面 | 新表现与操作 |
| --- | --- |
| 准备 | 敌方快照、己方两排、备战席、生命/金币/等级/轮次/人口同时可见；底部七个图标切换商店、布阵、仓库、羁绊、侦察、开战和系统菜单。空场显示上场提示。 |
| 布阵 | A/B 选行，C 进入选格；格子显示光标，移动起点带“起”标记，空格放置、有棋子则交换。 |
| 商店 | 四张精灵卡、类型、费用与技能摘要；顶部显示备战席，长按 C 看完整资料。 |
| 伙伴 | 肖像、定位、属性、原生技能、装备与已学招式；移动、装备、教学、卖出和详情按网格对齐。 |
| 仓库与教学 | 物资数量与图标，目标列表显示精灵和实际位置；不相容项说明原因。装备/教学确认层带目标精灵，默认取消。 |
| 战斗与结算 | 继续播放后端生成的真实帧，结束后自动进入结算，C 进入下一轮。 |
| 主页、远征与图鉴 | 主页精灵场景、搭档肖像、图鉴图片；详情分页与三键提示保持一致。 |

屏幕保持逻辑 240×320；桌面条件允许时用 2×，手机用 1×，关闭平滑。用户手选 2× 后缩窄至 320px，自动退回可容纳的比例。三个物理按钮在 390×844 和 320×760 的首屏均可见。

统一页面字体、文字基线、间距、表单高度、选中/不可用状态和提示颜色。完整棋盘的存档工具收进可展开区；远征与动画工具页共用 `ui_theme.css`。羁绊效果改为玩家能读懂的文案，包括“大招伤害+10%”“每秒回复0.5%最大生命”“单次大招承伤≤60%最大生命”。

## 实现边界

- `device_controls.py` 提供只读的棋盘、肖像、选项、焦点目标和场景信息；`action/data` 仍只留在控制器。移动、装备、学习和确认继续通过原有 UID/存档序号校验与事务。
- `device_renderer.js` 负责绘制；`device_input.js` 负责物理按键传输。HTML/CSS 独立成文件，便于后续将绘制后端换成设备实现。
- 准备页坐标：HUD 0–26，对手信息 27–44，敌方 45–124，中线 125–129，我方 130–209，备战 214–245，动作区 247–296，按键提示 297–319。
- 屏幕没有可点击的游戏控件。浏览器尺寸选项不触发游戏快捷键；按着 C 时焦点转入表单，松键仍正确释放。
- 操作错误显示在屏幕内；导航离开后清除，重复失败仍会再次显示。长按 C 有按住进度与松开动作提示。

## 验收记录

[系统验收 JSON](evidence/ui-battle-2026-10-05/final-acceptance.json) 中选定的 6 项全部 passed：294 项单测、编译、diff 检查、进程重启持久化、两局完整 Demo、真实帧三键 HTTP 流程。未选择的 4 项仍为 skipped，不认领强度/真机/额外美术专项验收。

收尾修复提示清理、主页副标题、表单焦点后，再跑 [全部 294 项单测](evidence/ui-battle-2026-10-05/final-unit-tests.log)，全部通过。

浏览器使用隔离 Chrome 和端口 8808，测试档案在 `.build/ui-review/saves`；道具与技能机库存仅写入该测试夹具。生产预览端口 8807 仍使用 `.build/saves`，用户原对局未用于交易测试。

- [页面与布局检查](evidence/ui-battle-2026-10-05/browser-report.json)：1280×1000 桌面、390×844 手机；五个页面没有横向溢出，设备按键均可见。实际键盘输入经过 down/up 传输，验收商店、详情、选行选格、移动、角色、仓库、空技能机列表和取消开战。
- [实际游戏流程](evidence/ui-battle-2026-10-05/browser-flows-report.json)：装备目标和确认、不兼容教学不扣库存、兼容教学生效、关屏/唤醒不提交、真实战斗帧、自动结算、只进入一次第二轮、主页/远征/挑战/图鉴。浏览器控制台错误为 0。
- [视觉收尾复查](evidence/ui-battle-2026-10-05/browser-final-report.json)：旧错误不遮挡新的教学目标，确认显示目标肖像，主页副标题不越界，手选 2× 后缩到 320px 自动恢复 1×，完整棋盘顶部对齐。控制台错误为 0。

初始页面截图使用 browser-automation / Midscene。其视觉动作模型因 thinking 配置返回 400，随后改用独立 Chrome/Puppeteer 执行真实按键、读取结果并截图人工复核；未把该失败记为视觉模型验收成功。没有改动用户的全局模型配置。

## 截图

| 对照与场景 | 证据 |
| --- | --- |
| 修改前 | [纯文字操作页](evidence/ui-battle-2026-10-05/device-before.jpeg) |
| 准备画面 | [桌面](evidence/ui-battle-2026-10-05/device-prep-desktop-final.png) · [手机](evidence/ui-battle-2026-10-05/device-prep-mobile.png) |
| 商店与伙伴 | [精灵商店](evidence/ui-battle-2026-10-05/device-shop.png) · [伙伴资料](evidence/ui-battle-2026-10-05/device-piece.png) |
| 布阵 | [起点与目标格](evidence/ui-battle-2026-10-05/device-move-target.png) |
| 教学 | [目标列表](evidence/ui-battle-2026-10-05/device-tm-targets-final.png) · [不兼容](evidence/ui-battle-2026-10-05/device-tm-incompatible.png) · [确认](evidence/ui-battle-2026-10-05/device-teaching-confirm-final.png) |
| 战斗 | [后端真实帧](evidence/ui-battle-2026-10-05/device-battle.png) · [结算](evidence/ui-battle-2026-10-05/device-result.png) |
| 主页 | [桌面](evidence/ui-battle-2026-10-05/device-home-final.png) · [320px 手机](evidence/ui-battle-2026-10-05/device-home-small-phone.png) |
| 其他页面 | [远征手册](evidence/ui-battle-2026-10-05/expedition-desktop-final.png) · [完整棋盘](evidence/ui-battle-2026-10-05/demo-desktop-final.png) · [动作编辑](evidence/ui-battle-2026-10-05/animation-editor-desktop.png) |

这些证据覆盖 host 图形界面。ESP32 绘制后端、实际屏幕阅读性、GPIO 按键手感与帧时预算仍待真机验收；完整首次体验引导、音效反馈与系统 review 的其他未完成项目继续按原清单推进。
