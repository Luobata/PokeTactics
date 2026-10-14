# 45 · 技能机与特性扩展指南（2026-10-11）

本文是扩展技能机/特性的工程合同：新增一个技能机要动哪里、哪些环节已自动、触发点怎么选、指纹与存档纪律。设计储备见[竞技联动设计](18-arena-combination-design.md)与[技能机与学习](30-skill-machines-and-learning.md)。

## 1. 新增技能机 checklist

以「守住 / 帮助 / 治愈铃声」（2026-10-11 落地）为参照实例。一个技能机最多动 6 处：

| 步骤 | 位置 | 内容 |
| --- | --- | --- |
| 1. 目录三表 | `sim/techniques.py` | `_TYPE_REQUIREMENTS`（属性相容）、`_ARENA`（name/description/category + `_ARENA_USES` 次数文案）、`_COMPATIBILITY`（相容名单）。`ids_for()` 自动从 `_ARENA` 导出目录 |
| 2. 触发处理器 | `sim/arena_teaching.py` | 普攻后触发：往 `_HANDLERS` 注册表加一个 `handler(battle, unit, target, t, key)`；伤害型直接进 `MOVES` 走默认 handler；需要战术等待的往 `_TACTICAL_CONDITIONS` 加谓词（6 秒上限是通用语义）。新触发点见 §2 |
| 3. 攻略文案 | `tools/acceptance/catalog_advice.py` | `TECHNIQUES` 加四字段条目（category/tags/advice/tradeoff），tradeoff 带星级次数口径。缺条目时 portal 会自动生成兜底卡（`portal.py::_technique_advice`，带 `generated` 标记），但 `tests/test_portal.py` 断言不允许出现 generated——文案是硬要求 |
| 4. 行为测试 | `tests/` | 参照 `test_teaching_support_machines.py` / `test_mechanic_techniques.py`：事件流断言 + 数值断言 + 次数=星级/再装填 + 不耗次数的失败路径 |
| 5. 目录计数断言 | `tests/test_arena_teaching.py`、`test_arena_expansion_skills.py`、`test_arena_synergy_choices.py` | 技能机总数断言 +N |
| 6. 存档兼容 | `tests/arena_save_expectations.py` | 把新 key 加入期望机器列表（照 `NEW_SUPPORT_MACHINES` 模式） |

**全自动、不用动**：奖励池与三选一候选（`arena_rewards.py` 从 `ids_for` 取全集）、学习动作与校验、前端学习面板与结算徽章、战斗回放中文名（`render_battle_gif.py`/`demo.py` 从 catalog 自动合并）、bot 学习与领奖评分（`arena.bot_teaching_choice` 按 category 通用打分，见 §3）。

**只在「删掉/改语义」时才需要**：sim/ 变更换规则指纹时的存档迁移，见 §4。

## 2. 触发点选型

现有触发点（钩子函数都在 `arena_teaching.py`，消费方在 combat.py / status.py / arena_skills.py）：

| 触发点 | 钩子 | 已在用 | 适合 |
| --- | --- | --- | --- |
| 成功普攻后 | `_HANDLERS`（after_basic 管线） | 伤害型全员、吼叫、隐形岩、挑衅、催眠粉、帮助 | 大多数进攻/功能机 |
| 低血行动时 | combat.py rest 分支 | 睡觉 | 自保/回复 |
| 本命技能完成后 | `arena_weather.after_native_cast` | 求雨、晴天 | 天气与大招联动（每战一次，不走星级次数） |
| 实际受击后 | `after_hit_taken`（挂 combat.py `_land_hit` 尾部） | 守住 | 承伤窗口、反击 |
| 友军被施加异常后 | `after_ally_debuff`（挂 status.py `_apply_debuff`） | 治愈铃声 | 净化、反制 |

新增触发点的纪律：钩子函数放 arena_teaching.py，挂接点跟在 `arena_traits` 同类钩子之后；无对应 technique 时不得消耗 RNG、不得发事件（golden 零漂移红线）；次数一律走 `technique_available/technique_spend`（次数=星级、3 次有效普攻再装填）。

可复用 helper（不要发明新的状态范式）：`battle._land_hit`（权威命中包）、`battle._skill_effect`（事件因果链上下文管理器）、`arena_fields.place_rocks/clear_near`、`status.apply_debuff/cleanse`、unit 上的窗口字段模式（`taunt_until`/`protect_window_until` 式）。

## 3. 新增特性 checklist

特性系统是现成的低成本范式（`sim/arena_traits.py`）：

1. `TRAITS` 加物种条目（id/name/category/cooldown/limit/trigger/description）；
2. 套模板：把特性 id 加进对应模板集合（`_CONTACT_STATUS`/`_TYPED_ABSORB`/`_LOW_HP_BOOST`/`_LETHAL_GUARD` 等 :205-229）——**零新逻辑**；
3. 只有新行为模板才需要在钩子函数（`opening`/`after_debuff`/`prepare_hit`/`settle_hit`/`after_native_cast` 等）里加分支；
4. bot 评分：`arena.py` 的 `_BOT_ROLE_MATCH` 按 category 通用打分，新 category 才需要加行。

## 4. 指纹与存档纪律

- `session_save.rules_fingerprint()` 对 sim/*.py + data/*.json 全量哈希：**任何 sim 改动都换指纹**，包括纯重构。
- 多个 sim 变更合并为一代指纹发布：开发期中间态不登记，定稿后一次性登记前任指纹（supported 集合、current_layout、migrating_expansion 排除、缺 battle_history 拒绝清单、`_decode_arena` 两参数元组、save_warning，共 7 处，照 `PRE_SUPPORT_TECHNIQUES_FINGERPRINT` 模式）+ 兼容测试（照 `tests/test_arena_support_techniques_compatibility.py` 模式）。
- 技能机仓库迁移按**已登记的历史目录常量**精确匹配补零（`session_save.py` 的 `PRE_SYNERGY/PRE_TECHNIQUE_GROWTH/PRE_SUPPORT_TECHNIQUES`）：新增技能机时把上一代目录登记为新常量即可，缺键的损坏存档（非登记子集）会被拒绝而非静默接受。
- golden 纪律：只增不改的扩展不应漂移任何既有战斗结果；漂移了必须能归因（如 bot 决策变化），并在报告里说明。

## 5. 平衡性数据基础

- `tools/acceptance/arena_probe.py`：arena_v1 整局 headless 批量 probe（Collector 架构，`PoolCollector` 卡池指标、`TechniqueCollector` 技能机指标），输出 `.build/arena-probe/*.json`。
- 参照报告：`reports/pool-scarcity-2026-10-11.md`（卡池）、`reports/technique-balance-2026-10-11.md`（技能机使用率/强度）。
- 扩展方向决策先看报表：使用率接近 0 的类别是空缺信号；触发次数/星级上限利用率长期低于 50% 说明再装填过严或过松。
