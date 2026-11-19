# 66 · 试玩页流畅度与主题下拉框（2026-11-19）

> 用户反馈：「交互卡顿感还是有」「select 下拉框的 ui 还是最原始的」。
> 本篇记录测量方法、改动和前后数据，以及下拉框组件的用法。

## 1. 怎么测

* 工具：Playwright + CDP（headless Chromium，1440×900，种子 515，第 1 轮已招募 1 只）。
  * `Performance.getMetrics` 的 ScriptDuration / RecalcStyleDuration / LayoutDuration 差值（每次交互）。
  * rAF 最大帧间隔（掉帧 = 卡顿）、Long Task、Event Timing（输入 → 下一帧呈现）。
  * 页面内「点击 → 棋盘/备战席 DOM 变化」耗时（MutationObserver）。
  * 对单次交互抓 `devtools.timeline` 追踪，统计 Paint / UpdateLayoutTree 次数。
* 「改前」用 Playwright 把 play.js / play_layout.js / play_depth.js / play_interactions.js 路由回 7c61d2a 版本，同一服务、同一存档对比，各跑 2 次取均值/最大值。

## 2. 发现

1. **空闲也在重绘**：选中一只精灵后什么都不做，400 ms 内仍有约 100 次 Paint（主线程 28 ms 绘制 + 12 ms 样式）。原因是选中光圈、强调徽标/芯片、装备目标等用 `box-shadow` 做无限循环动画，无法交给合成器，每帧都要重绘和光栅化，点击时只能排在这些帧后面。
2. **每次点选都全量重建**：`render()` 对棋盘、备战席、商店、羁绊、背包、技能等全部重写 innerHTML；选中状态写在格子标记里，所以单纯点一下也要重建所有格子。
3. **变更要等服务器**：买、移动、出售在服务器回包（约 100–160 ms，lite 响应 67–76 KB）后才出现结果。
4. 首次手势时创建 `AudioContext` 约 60 ms（play_music，已放在 idle 回调里，一次性）。

## 3. 改动

* **按区块缓存渲染**（play.js / play_layout.js / play_depth.js / play_interactions.js）：
  `$h(id).innerHTML = …` / `setHTML(el, …)` 只在 HTML 字符串变化（且子节点没被别人替换）时才写 DOM；`setText` 只写变化的文本。
  格子和商店卡的标记不再包含选中、装备目标、busy 状态。
* **纯 UI 状态只切 class**：`syncSelection()` 切换 `.selected` / `aria-pressed` / `.equip-target`；
  `renderSelection()` 只更新提示语、详情、背包按钮，并以 `reason: "selection"` 调用各模块的轻量路径
  （PlayDepth：地形格、核心/威胁角标、详情；PlayLayout：操作条与射程/威胁连线；PlayInteractions：详情装饰与目标模式）。
  深度版角标改为「同签名不重建」（`decoration()`）。
* **乐观更新**：`buy / move / sell / equip`（首个装备位）先在本地状态副本上应用并立即渲染（`renderCore()` + `renderSelection()`），
  服务器回包后整体替换；失败、超时或回包无状态时回滚并抖动原控件。会合成升星、备战席满、人口满、第二装备位等不确定情况不做乐观预测。
* **动效预算**（`play_motion.css`，最后加载）：长循环只动 opacity / transform；发光改由伪元素承载并做透明度呼吸；威胁箭头改为静态虚线；沼泽/余烬地形改为透明度呼吸。
* 威胁连线、射程高亮只切换差异 class，SVG 覆盖层同样按内容缓存。

## 4. 结果（改前 → 改后）

| 交互 | 点击→DOM 变化 | 最大帧间隔 | JS | 样式重算 | 布局 |
|------|--------------|-----------|----|---------|------|
| 选中商店卡 | — | 33 → 17 ms | 18 → 7 ms | 18 → 9 ms | 7 → 3 ms |
| 选中棋盘单位 | — | 33 → 17 | 16 → 8 | 24 → 16 | 6 → 3 |
| Esc 取消选择 | — | 33 → 17（事件 72 → <16 ms） | 14 → 2 | 15 → 6 | 5 → 0 |
| 双击购买 | **166 → 18 ms** | 33 → 17 | 18 → 12 | 40 → 36 | 21 → 19 |
| 备战席 → 棋盘 | **172 → 16 ms** | 50 → 33 | 20 → 10 | 58 → 44 | 14 → 8 |
| 出售 | **158 → 10 ms** | 33 → 17 | 21 → 10 | 44 → 28 | 22 → 14 |
| 空闲（已选中） | 每 400 ms 约 100 次 Paint → **0 次** | | | | |
| 悬停敌方 | Paint 89 → 11 次 | | | | |

所有交互均无 ≥50 ms 的 Long Task。打开抽屉面板（首次显示背包的合成矩阵）仍有一次约 10 ms 的布局，属于内容首次显示的成本。

**给服务端的建议**（不在本次前端范围）：即使只是切换商店锁定（`lock`），lite 响应也要 90–113 ms、76 KB。
体积前几位：`interactions`（12.5 KB，其中合成矩阵 9 KB，组件不变时不会变）、`shop`（10 KB）、`opponent`（10 KB，整轮不变）、
`depth`、`combinations`、`techniques`（5 KB，基本静态）。可考虑按区块带版本号/哈希，只回传变化的区块，并检查 `state_json` 的计算耗时。

## 5. 主题下拉框（`play_select.js` / `play_select.css`）

* 页面上所有单选 `<select>`（定向刷新属性、战斗速度、画风、历史回合、技能机学习目标、本局特性……）自动增强，
  包括之后重新渲染出来的（MutationObserver）。
* **原生 select 仍是唯一数据源**：保留 id / value，隐藏但在 DOM 中；选择后写回 `value` 并派发冒泡的 `change` 事件，
  所以 `onchange`、委托监听、测试里的 `p.change(id, value)` 都不用改。代码里 `select.value = …`、重建 option 时按钮自动同步。
* 外观：按钮显示当前值 + 箭头；弹出列表带 ✓、悬停/键盘高亮；`<option data-chip="#hex">` 显示色块（属性颜色），`data-icon` 显示图标。
* 键盘：↑↓ / Home / End 移动，Enter / 空格选择，Esc 关闭并回到按钮，Tab 关闭，输入字符跳转（type-ahead）。
* 无障碍：按钮 `aria-haspopup="listbox"` + `aria-expanded` + `aria-controls`；列表 `role="listbox"` + `aria-activedescendant`；选项 `role="option"` + `aria-selected`。
* 手机（与布局相同的媒体查询）：底部弹层 + 遮罩 + 标题，行高 48 px；点击外部关闭。
* 在模态 `<dialog>` 里时，弹层挂到该 dialog 内（顶层渲染），否则挂到 body；空间不足时向上弹出。
* 不需要增强的 select 加 `data-native`；`multiple` 和 `size>1` 的列表自动跳过。
* 未接入：动画工作台（`animation_workbench.html`）有自己的 select，组件可直接复用（引入两个文件即可），但该页面由其他成员维护，本次未改。

## 6. 测试

* `tests/test_play_layout.py`：新增 `keyedSelection`（选中/预览/装备目标不重建任何格子和卡片节点，只切 class）、
  `optimisticBuy`（请求未返回时备战席已出现单位、金币已扣、商店格为已售）、`optimisticRollback`（失败回滚购买与移动）、
  三个下拉框场景（键盘与 type-ahead、手机底部弹层、代码重建选项后同步）、动效预算静态检查。
* 前端测试 DOM 增加 `remove / firstChild / nextElementSibling / options / insertAdjacentElement / dispatchEvent`，点击会遵守 `stopPropagation`。
* `rangeThreat`、`skillCard` 两个场景原先就因「再点一次同一单位 = 快速上场」失败，改为通过操作条取消选择。

## 7. 配装顾问界面（数据见 docs/65 `state.interactions.item_advice`）

* **背包顶部「配装建议」**：最多 6 张卡（手机横向滑动），每张一步可执行：
  * 装备 → 打开常规确认面板（装备位前后对比）后装给建议的伙伴；
  * 合成 → 立即合成，成功后直接弹出「装给 X」的确认面板（带「刚合成」标记）；
  * 凑齐 → 打开合成图，高亮该配方格与缺的组件，并显示「正在凑：X · 还差 Y」。
  卡片列出 `why` 理由（✓）。上方是**队伍道具类型**统计（输出 / 坦克 / 控制 / 联动 / 辅助 / 经济），装了 2 件以上且没有坦克/输出/控制时提示「缺少…道具」。
* **成品卡**：类型徽章与左侧色条、机制 / 宝物 / 数值徽章、一句话玩法、✓ 已成立联动（绿）与 ○ 还差的联动（灰，「还差：…」）。有 2 种以上类型时出现带数量的筛选芯片。
* **装备目标模式**：顶部条显示第一推荐携带者与理由、其余名次，以及该道具已成立的联动。
* **合成图**：格子顶部为类型色条，机制道具带 ⚙、宝物带 ★；点格子在面板里看到类型、玩法与联动。
* **选中伙伴的操作条**：如果仓库里有建议给它的道具，出现「◆ 推荐 X」一键装备。
* 测试：`itemAdvice`（建议卡、缺类型提示、成品卡联动、筛选、装备与凑齐高亮、目标条联动）、`itemAdviceCraft`（合成后装给建议伙伴）。
