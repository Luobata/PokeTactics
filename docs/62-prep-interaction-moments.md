# 62 · 准备阶段的三个「游戏时刻」：海克斯、技能、道具（2026-11-15）

> 承接 [docs/61](61-play-ui-redesign.md) 的棋盘中心布局。本篇把海克斯选择、技能机/本命强化、
> 组件合成与装备三类交互从「表单」改成有仪式感、讲道理的游戏时刻。
> 截图：`reports/evidence/interaction-redesign-2026-11-15/`（desktop_* / phone_*，按编号即操作顺序）。

## 1. 设计原则

1. **服务端讲道理，前端只负责表现**：每个推荐、适配度、可合成判断都由 `tools/acceptance/interaction_view.py`
   根据当前棋盘、备战席、仓库算出，并附 1–3 条中文理由。前端不复刻规则。
2. **只读**：`interaction_view.build(sess)` 不用随机数、不改会话，战斗与金样本指纹不变
   （`arena_golden.py --check` 通过；另用 arena_v2 机器人整局指纹对比了重构前后，完全一致）。
3. **与机器人同一把尺子**：海克斯适配度复用 `arena.augment_fit`（由 `bot_augment_choice` 拆出，
   机器人仍取其分值最大者）；技能机推荐复用 `arena.teaching_fit`（由 `bot_teaching_choice` 拆出）；
   装备推荐复用 `arena_equipment.carrier_rank`，经典装备补充了一张可见的定位表。
4. **所有变更仍走原命令**：`claim_augment / reroll_augment / learn / equip / craft / choose_mod`，
   确认面板里的按钮只是换了入口。
5. **触屏优先**：点选即可完成全部流程；桌面额外支持拖拽。触控目标 ≥ 44px，信息不依赖悬停。

## 2. 海克斯选择（第 1 / 7 / 13 轮）

* **全屏时刻**：有待选海克斯时自动弹出 3 张大卡，翻牌 + 依次揭示动画（`prefers-reduced-motion` 时关闭）。
  稀有度只做表现：第 1 轮银框、第 7 轮金框、第 13 轮彩框（没有改变卡池）。
* 每张卡：类别图标（◎ 经济 / § 规则 / ⚔ 战斗 / ⚡ 条件 / ↗ 成长）、名称、简述、标签（中文）、
  **适配度条**（很适配 / 一般 / 勉强，最高分者标「推荐」）、理由（✓ / ✗）、「选择后」的具体变化、
  v1 条件型海克斯的「触发条件：已满足 / 未满足」、完整说明。
* **换一批**是显眼的按钮并显示剩余次数；「先看看棋盘」暂时收起，棋盘顶条出现橙色「海克斯待选」芯片随时打开。
  有待选海克斯时点开战，会重新打开这个时刻。
* **已选海克斯徽章条**：桌面在入口坞下方，手机在备战席标题行。点徽章看说明、当前成长值，以及上一战
  这条海克斯在收益账本里的触发次数与数值。

## 3. 技能交互（技能机 + 本命技能 + 升星强化）

* **技能机货架**（强化 → 技能学习）：每台机器显示类别、库存（×N）或 2 金学习、可学数量、
  **推荐携带者 + 理由**。原「下拉框 + 按钮」列表保留在「列表方式学习」折叠里。
* **点选目标**：点一台技能机 → 棋盘与备战席上能学的伙伴发紫光，推荐者带金色「1」角标，不能学的变灰；
  点不能学的伙伴会在顶部提示原因。桌面可以直接把技能机拖到伙伴身上。
* **确认面板**：学习位「现在 → 学习后」对比、消耗（1 台技能机 / 2 金）、替换不返还警告、
  双持专精下技能机失效提示。
* **精灵情报**：原生技能卡底部加一条技能牌（类别符号、类别、威力、目标）；学习位变成插槽样式，
  带「插入技能机 / 更换技能机」，打开只列出这只伙伴能学的机器。
* **升星强化（arena_v2，2★/3★）**：伙伴有待选强化时（通常刚合成升星），自动弹出二选一卡片，
  每张写明变化（如「本命/技能机 伤害·治疗 +30%」「主命中后 邻格 2 敌 35% 溅射」）；
  可以「稍后再选」，棋子上的「?」标记保留到选择为止。

## 4. 道具交互与组合

* **成品卡**（背包）：名称、配方、数值行（如「攻击 / 特攻 +35%」）、v2 组件属性行、效果、
  「适合：…」与前三推荐携带者；按钮「选择携带者」，v2 另有拆解 / 出售。
* **装备**：点「选择携带者」或拖到伙伴身上 → 有空位的伙伴发光，推荐 1/2/3 带角标，装备位已满的变灰；
  选中伙伴后弹出确认面板：推荐名次与理由、装备位「0/1 → 1/1」前后对比（含已装备物品的数值）、
  第二装备位（核心 / 双持）提示、满位时提示先卸下（v2 每件 1 金）。棋盘操作条的「卸装」也标出 1 金。
* **组件合成图**：8 × 8 组件矩阵（行列都是 8 种组件，表头显示库存与组件属性）：
  绿色发光 = 现在能合成；米色 = 差 1 个；灰色 = 差更多；斜纹 = 无配方（经典规则下的 4 个空对子）；
  金框 = 深度版新增配方（心灵水晶、先制之爪、逃脱背包、爆裂核心）。点格子看配方、属性与缺什么，再点「合成」；
  桌面可以把一个组件拖到另一个组件上直接合成。
* **合成预告**：商店卡选中时，棋盘操作条显示「⇪ 买入即升星；某装备将回到仓库」或「买下即升 2★」。

## 5. 数据字段：`state.interactions`（所有竞技局，只读）

| 字段 | 内容 |
|------|------|
| `augments.pending[]` | `id, round, rarity(silver/gold/prismatic), rarity_name, rerolls_left, options[]`；option：`id, category, category_name, tags(中文), score, fit(high/mid/low), best, reasons[{text, good}], changes[], condition{met, text} | null` |
| `augments.selected[]` | `id, category, category_name, last{round, rows[{triggers, damage, heal, shield, energy, prevented, estimated, idle, passive}]} | null` |
| `techniques{id}` | `category, category_name, compatible[uid], known_by[uid], cost, count, best{uid, name, score, reasons[], replaces} | null` |
| `skills{uid}` | `category, category_name, glyph, power, targeting, targeting_name, behavior, tags, technique, mods[{id, name, delta, description}]`（`mods` 仅 v2） |
| `recipes` | `components[{key, name, n, stats}]`，`cells[36]{a, b, item, name, depth, dead, craftable, blocked, missing[], stats[], effect}` |
| `equip` | `items{key}{name, lines[], stats[], effect, recipe, carriers[≤3]{uid, name, score, reason, free}, suits}`，`slots{uid}{total, used, items[]}`，`unequip_cost` |

后端改动：`sim/arena.py` 拆出 `augment_signals / augment_fit / teaching_context / teaching_fit / teaching_learner`
（机器人行为不变）；`tools/acceptance/demo.py` 在竞技状态里加入 `interactions`（构建失败时只返回 `error`，不影响试玩），
并在 arena_v2 结算后把我方规则收益账本暂存在内存 `sess.last_rule_ledger`（准备阶段 `last_battle` 已清空；**不写入存档**，重新载入后要等下一场结算才有）。

## 6. 前端结构

| 文件 | 职责 |
|------|------|
| `play_interactions.js` | `PlayInteractions.render(ctx)`：海克斯时刻、徽章条、技能机货架、成品卡、合成图、情报卡装饰、目标模式（点选 / 拖拽）与通用确认面板 `#ix-sheet`。 |
| `play_interactions.css` | 以上所有表现（稀有度框、翻牌、发光目标、矩阵、手机底部面板）。 |
| `play.html` | 新增 `#hud-augment`、`#ix-augment`、`#ix-sheet`、`#ix-target-bar`、`#ix-augment-strip`、`#ix-tm-rack`、`#ix-items`、`#ix-recipes`；原 `#techniques`、`#inventory` 列表保留在折叠里。 |
| `play_layout.js` | 有交互层时不再自动打开强化面板；商店操作条显示合成预告；卸装标价；切换面板回到顶部。 |

目标模式会接管棋盘点击（捕获阶段拦截，避免 play.js 把点选当成移动）；Esc 或「取消」退出。

## 7. 测试

* `tests/test_play_interactions.py`：只读性、两个版本都有 `interactions`、海克斯理由引用真实阵容、
  机器人选择 = 最高 `augment_fit`、v1 条件判定、技能机推荐 = 最高 `teaching_fit`、天气理由、技能牌与升星强化、
  合成矩阵（36 格、死对子、深度配方、与仓库一致、合成后刷新）、装备推荐排序与槽位、v2 账本跨轮保留；
  以及 7 个前端场景（`tests/frontend/play_interactions_presentation.js`：海克斯时刻、技能机目标与确认、合成图、
  装备推荐与预览、升星强化选择 / 延后、情报技能卡与插槽）。
* 回归：`test_play_layout`、`test_play_page`、`test_portal`、`test_battle_report_presentation`、`test_arena_depth`、
  `test_arena_effect_bus`、`arena_golden.py --check` 通过；`continuous_forward_playback` 为 main 上已知超时。

## 8. 已知限制

* 稀有度只影响外观，没有改变各轮的海克斯候选池。
* 「上一战」账本只保存在服务器内存里，重新载入存档后要等下一场结算才显示。
* 合成同一成品有多种配方时（如黄围巾、天气石），服务端按仓库确定的那组组件合成，可能不是你点的那一格。
* 升星强化截图使用了在浏览器侧注入的 2★ 待选状态（真实字段由 Python 测试覆盖）。
