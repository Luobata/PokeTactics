# 32 · 教学技能学习与动画合同

状态：2026-10-05 设计合同；生产实现尚未开始。本文承接 [20 · 远征搭档与预算](20-expedition-partners-and-budgets.md)、
[21 · 动画制作与验收](21-animation-authoring-and-acceptance.md)、[23 · 战术远征](23-tactical-expedition.md)
与 [29 · 系统深度审计](29-system-depth-and-augments.md)。当前用户裁定先完整设计与学习表，
再做首批隔离原型；`guardian_riposte` / `tempo_break` 已有只读隔离 adapter、真实事件视觉探针与
HP/能量/位置对账证据。正式 sim 接入、生产渲染器、新教学身体部件与 ESP32 实现均未完成；
旧 `cut/surf/rest` 因果与演出缺陷本包只审计，不声明修复。本文件不改变 `tactics_v5`
规则、存档 schema、正式技能目录或生产渲染器。

## 1. 结论与当前覆盖

当前 6 个教学是居合斩、冲浪、睡觉、护卫、晴天、求雨。事件与表现成熟度并不相同：

| 教学 | 权威结算 | 因果绑定 | 画面现状 | 缺口 |
|---|---|---|---|---|
| 居合斩 | `partner_effect("cut")` 后接真实 `attack`/`unit_state` | 无 `cause_index`/`event_count` | 副攻击可走通用攻击/伤害浮字 | 无教学专属弧刃；标注比主普攻命中早进入演出流 |
| 冲浪 | 每个目标各一条 `partner_effect("surf")`，后续 `attack`/`unit_state` 权威化 | 无 `cause_index`/`event_count` | 副攻击与伤害浮字可显示 | 无教学专属浪围；标注比原生大招冲击更早进入演出流 |
| 睡觉 | `partner_effect("rest")` 后接 `regen`/`unit_state`，行动间隔由模拟器扣 | 无独立动作 timing | 只有通用回复浮字 | 无休息姿态、Z 字、能量不变等教学语义；不能把行动间隔画成新的模拟状态 |
| 护卫 | `tactical_effect("guard")`，payload 有 `result_event_index`/`result_event_count` | 已按最终命中或闪避归属 | 连线、消息与承伤同步 | 仍无独立身体关键帧；不影响当前因果正确性 |
| 晴天/求雨 | 请求、开始、覆盖、冲突、结束均为 `tactical_effect`；请求有 `cast_index` | 已按原生大招冲击/下一 tick 归属 | 地板色、天气粒子、图标、倒计时与消息 | 天气手身体只有通用施法，无教学专属请求姿态 |
| 封疗针（对照） | `healing_block`/`healing_prevented`，payload 有模拟与到期时钟 | 已按实际命中/治疗归属 | 徽记、封锁浮字、倒计时 | 可作为有限效果动画的参照，不是教学槽技能 |

只读探针确认了旧教学标注的时间缺口：在定向场景中，居合斩标注保持在原始模拟时刻，
而其主动作与副命中被时间轴延后到动作冲击；冲浪标注也早于原生大招冲击；睡觉没有独立
前摇/命中阶段。`tools/acceptance/demo.py` 只把 `partner_effect` 转成文字战报；
`tools/mockups/render_battle_gif.py` 不消费该标注。因此不能把“副攻击有通用特效”或
“战报有文字”说成教学技能动画已交付。

现有可复用资产是：16 套整身动作、16 套手编技能视觉、8 族三帧素材、
`skill_effect` 的 `cast_index/event_count` 因果包、护卫的 `result_event_index`、
天气与封疗的模拟/演出时钟换算。它们不能自动生成新强教学；新技能至少需要一条
可辨认的独立教学轨道，不能只换类型颜色或粒子数量。

## 2. 权威事件合同

### 2.1 统一标注

新增强教学不得由渲染端按物种、属性、时刻或名字猜测。模拟器必须在结算前后输出标注，
实际结果仍由既有权威事件表达：

- 伤害：`attack` 或 `cast`，随后 `unit_state`/`die`；
- 治疗：`regen`，随后 `unit_state`；
- 能量：`unit_state`；
- 位移：`move`；
- 状态/有限效果：`status` 或 `tactical_effect` 的 apply/expire；
- 未命中、免疫、零伤害、无有效目标：保留真实结果事件；无成功效果不得绘制成功反馈。

新增强教学使用 6 元组 `teaching_effect` 作为唯一权威标注通道：

```text
(t, "teaching_effect", source_idx, target_idx, machine_id, payload)
```

旧 `partner_effect` 回放保持兼容但不用于新机器；`source_idx` 与 `target_idx` 是顶层
因果身份，payload 必须重复并携带完整结果元数据：

```text
{
  "cause_index": <owning primary attack/cast index>,
  "cause_event_count": <owned records after this marker>,
  "source_idx": <skill source, repeated for standalone causality>,
  "target_idx": <skill target, repeated for standalone causality>,
  "source_pos": ..., "target_pos": ...,
  "actual": {damage/heal/energy/delay/pushed/... using real results},
  "effective_at": <simulation seconds, optional>,
  "expires_at": <simulation seconds, optional>
}
```

首批冻结机器的实际结果字段允许两种等价 ABI：上例的 `actual` 嵌套对象，或与
`cause_index` 平级的结果字段。守备反击必须可取得 `pushed`、`from_pos`、`to_pos`、
`delay_seconds`、`next_act_before`、`next_act_after`；心律截断必须可取得
`actual_loss`、`energy_before`、`energy_after`、`returned_energy`。适配与验收层不得
强制要求只描述实验室分类的 `scenario` 字段，也不得要求独立的 `tempo_zero` 事件；
零收益由 `actual_loss == 0` 识别。`target_idx` 必须与顶层目标重复；位置快照只描述
标注时刻，守备反击的真实位移另由 `from_pos/to_pos` 与紧随 `move` 表达。

`cause_index` 必须指向权威原生主 `attack/cast`，不得指向未来或其它动作；该限定只适用于
首批 `guardian_riposte` / `tempo_break`。后续被动候选（如 `standburst` / `triage`）若由
`unit_state`、`move` 或 DOT 原始事件致因触发，必须新增显式 `cause_kind` 与对应归属规则，
不得沿用或扩写现 adapter 的 attack/cast 假设；后六台尚未由本 adapter 支持或验证。守备反击的
资格按主命中快照判定，但推离方向按原生技能链结算后的当前真实位置取值；这两个时刻
可以不同，动画不得用主命中位置回写当前位移。`source_idx`
允许与父事件攻击者不同：守备反击的技能来源是受击防守者，父事件攻击者仍由 `cause_index`
定位；心律截断的来源是施法者。`cause_event_count` 只圈定紧随的属于该教学的事件，遇到同
tick 无关动作必须停止。独立教学
动作（如睡觉）`cause_index=null`，由 `AnimationTimeline` 生成教学动作的前摇、释放、
命中与恢复。若结算需要回填 `result_event_index`，沿用护卫模式；序列化后仍可重建。

实验 adapter 可以把新实验 Battle 的事件转换成同一标注，但不得修改原始事件数组、
消耗新游戏 RNG、补伤害或提前读取未来结果。首批实验动画工具读取权威事件渲染；
`tools/mockups` 生产渲染器保持不变。

### 2.2 有限效果

持续减伤、封疗、嘲讽、反伤、蓄能等必须由模拟器输出开始与结束：

- payload 记录 `effective_at`、`expires_at`、强度和对象；
- 到期、死亡清除或覆盖时输出显式事件；死亡可以立即隐藏表现，但不得给活体发伪造到期；
- 最强取一、覆盖与叠层规则属于模拟器；渲染端只显示当前有效行；
- 来源退场是否移除效果由规则决定。若不移除，来源位置只作快照，不表示持续依赖；
- 满血、零收益、免疫或未命中不能显示“已削弱/已治疗/已命中”。

## 3. 演出阶段与关键帧

每个强教学轨道必须定义四阶段，并绑定 `ActionTiming.start/release/impact/recover_end`：

1. **前摇**：只允许蓄势、读数、挂点预亮；不得提前改 HP/能量/位置。
2. **释放**：从记录的 source 快照发出；可使用既有口部、炮口、花盘、爪尖挂点。
3. **命中/生效**：数字、HP、能量、位移、状态与死亡只在此后按权威事件出现。
4. **恢复/余波**：短促收束；不得延长模拟效果时长，也不得吞掉后续独立动作。

教学轨道需要至少两层区分：一层身体/挂点动作，一层弹道、光环或命中材质；范围或持续
效果再加第三层目标边界。关键帧遵守 `esp32_runtime/animation.py`：2–16 个归一化时间点、
六维整数姿态、可见性离散切换、严格递增且覆盖 0/1。未建正式部件的普通角色使用整身
动作或程序化轨道，不得声称已完成逐部件动画。

## 4. 八条教学视觉轨道

前六条对应现状；后两条是新强教学的首选视觉族，具体技能名和学习表由学习设计定稿后映射。
候选若不能映射，应新增轨道而不是挤占相近视觉。

| 轨道 | 语义 | 主要事件 | 视觉方案 | 无效/边界 |
|---|---|---|---|---|
| `follow_slash` | 普攻成功后的追加斩击 | 原生 `attack` → 教学标注 → 副 `attack` | 主目标到邻目标的一道短弧；副命中同拍，不额外回能 | 无邻目标、免疫、零伤害只消耗或保留次数须按规则，不画斩击 |
| `splash_ring` | 原生大招成功后的波及 | 原生 `cast` → 多个教学标注与副 `attack` | 以释放时主目标位置为圆心的两圈水沫；至多两道目标水线 | 释放位置必须快照；后续位移不能追溯改变中心 |
| `recuperation` | 用一次行动换取休息/恢复 | 独立教学标注 → `regen`/`unit_state` | 0.35–0.55 秒前摇，命中时回复数字；短 Z/呼吸环只是表现，不创建睡眠状态 | 满血或死亡不触发；不得把攻击间隔伪装成持续睡眠状态 |
| `intercept_guard` | 一次承伤转移 | `tactical_effect("guard")` + `result_event_index` | 被保护者到护卫的短连线、盾弧与冲击同步 | 闪避显示次数已耗但无伤害；无效距离/死亡不触发 |
| `weather_request` | 天气手申请 | `tactical_effect("weather_request")`，`cast_index` | 施法冲击处一圈请求纹；身体用通用施法姿态 | 未施法、阵亡、次数耗尽无请求纹 |
| `weather_state` | 全场天气窗口 | `weather_start/conflict/end` | 地板替换、八粒天气、图标与剩余秒数 | 冲突不短暂显示任一新天气；倒计时不读取未来事件 |
| `guardian_riposte` / `shell_riposte_push` | 高体格近战首次受相邻主伤害并存活后反击 | 父 `attack/cast` → `teaching_effect` → 攻击者 `move` 或 blocked/stalled 状态 | 受击冲击同拍：防守者外圈壳形折线，攻击者被推或原地迟滞标记；`source_idx=防守者`，`cause_index=敌方主事件` | 距离大于 1、零伤害、闪避或结算时死亡不触发；固有远程单位贴身命中仍可触发；堵位无位移仍显示迟滞；不得伪造防守者伤害或回能 |
| `tempo_break` / `broken_pulse_drain` | 高速度首次原生大招主命中后削减目标当前能量 | 原生 `cast` → `teaching_effect` → 主目标 `unit_state` | 施法命中同拍：断续脉冲线连向主目标，目标能量条短促断口；平级 `actual_loss` 或嵌套 `actual.loss/removed` 为 0 时显示空断线 | 未命中、闪避、免疫、零伤害或目标死亡不触发；0 能量可消耗，不要求独立 `tempo_zero` 事件，仍不得伪造数值或能量回流 |

前六条是既有教学补齐方案；后两条对应已冻结的首批机器。其余候选仍是第二批设计。强教学若只是提高伤害，仍不得通过：它必须带来不同
启动时机、站位价值、反制窗口或资源转换，并在学习设计中给出兼容资格与机会成本。

## 5. 首批隔离原型

首批候选已冻结，但未完成设计验收前仍不改 `sim/`、`data/`、正式规则、存档或
`tools/mockups/`。已实现的隔离 adapter 位于
`tools/acceptance/teaching_visual_probe.py`：它只读解析 `teaching_effect` 的平级或嵌套
结果 ABI、绑定原生 `ActionTiming`，并在验收侧对 HP/能量/位置与 owned events 做因果
对账；生产 `AnimationTimeline`/渲染器尚未消费该教学轨道。首个动画原型在
`tools/acceptance/` 下构造隔离实验 Battle 与 adapter：

1. **因果修复基线**：给实验版居合斩/冲浪/睡觉标注补 `cause_index` 或独立动作元数据，
   证明副结果与原生主动作同拍、无未来泄漏、原始事件不变。此步只修实验 adapter。
2. **首批两个冻结机器**：`guardian_riposte`（counter 资格，`shell_riposte_push`）与
   `tempo_break`（tempo 资格，`broken_pulse_drain`）。资格与学习表以 30 号和
   `docs/design/teaching-skills-v1.json` 为准：前者近战且体格 `HP+2*DEF` 不低于 220，后者速度不低于 100；阈值与机器归属只读 30 号/JSON，视觉探针不得自行推导资格。
3. **候选视觉探针**：`tools/acceptance/teaching_visual_probe.py` 输出
   真实场景关键帧与 GIF、事件哈希、源哈希、播放时刻、像素哈希和模拟不变断言。
   事件所有者必须借已有原生 cast/attack `cause_index` 对齐；`guardian_riposte` 的技能来源
   与父事件攻击者不同，不能通过既有 `skill_effect` 的同 caster 过滤冒用。不假造伤害。

实验探针可以复生产渲染器的只读函数，但不能 monkey patch 或修改生产默认行为；正式接入
必须另开规则版本与回归包。探针事件只允许 `guardian_riposte` 与 `tempo_break` 两个冻结 machine id；第二批候选不得混入首个证据包。

## 6. 最小实现点与验收

正式实现时的最小修改面：

- `sim/techniques.py` / 学习规则：技能目录、兼容资格与学习表；
- `sim/combat.py`：结算、目标选择、资源、次数与标注事件；
- `tools/mockups/animation_timeline.py`：教学标注的因果包与独立动作四阶段；
- `tools/mockups/render_battle_gif.py`：只读消费、状态重置与绘制；
- `tools/mockups/move_effects.py`：有限、带预算的新轨道素材；
- 对应测试：学习资格、战斗边界、时间轴、回放、动画像素与设备页文本。

隔离原型阶段只需 `tools/acceptance/teaching_visual_probe.py` 及其自包含 adapter；
生产路径不引用实验技能，避免旧 v5 录像或存档被隐式升级。

验收最低集：

1. **权威不变**：渲染前后原始事件深比较相同；无新 RNG；无模拟对象写入。
2. **因果**：前摇早于结果，HP/能量/位移/死亡只在 impact 后出现；同 tick 无关动作不被圈入。
3. **无效路径**：未命中、免疫、零收益、无目标、边界阻断、死亡取消均无成功反馈。
4. **退场/到期**：目标死亡隐藏；apply/expire 边界前一帧在、边界帧不在；来源退场按规则测试。
5. **回放**：0.5×、1×、2×、skip、向前再回卷同一时刻像素相同；倍速只换算一次。
6. **预算（正式接入条件）**：192 粒子、3 条活跃技能轨、天气八粒与教学轨道共享预算；重复触发不超限。本包只检查教学叠加层的常量绘制成本估计（反击42/截断36），未计量原生/天气/教学总量，未实现或验收共享总预算；`teaching_overlay_estimated_budget` 不能当作本项通过。
7. **画面证据**：关键帧覆盖前摇、释放、命中、恢复、无效与到期；GIF 连续无跳帧。
8. **测试入口**：先跑/扩展 `test_build_diversity.py`、`test_animation_timeline.py`、
   `test_replay_contracts.py`、`test_move_effects.py`、`test_tactical_presentation.py`，
   再跑 `system_acceptance.py --presentation`。隔离原型至少有探针自校验 JSON 与非零退出。

## 7. 仍未实现

- 首批 `guardian_riposte` / `tempo_break` 已冻结，第二批机器学习资格、次数与数值尚未验收；
- `partner_effect` 因果元数据与教学轨道尚未接入生产；居合斩/冲浪/睡觉的旧因果与
  演出缺陷在本包只审计，不由隔离原型修复；
- 居合斩/冲浪/睡觉专属动画尚未实现；
- 护卫与天气手的教学专属身体关键帧尚未实现；
- `guardian_riposte`、`tempo_break` 的隔离实验 adapter 与 PC 视觉探针已实现，但正式
  sim 接入、生产渲染、教学专属身体部件与 ESP32 实现均未完成；
- ESP32 C 采样、绘制、缓存、峰值内存与真机帧耗时仍未开始；PC PNG/GIF 不能替代。
