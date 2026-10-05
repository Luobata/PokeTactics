# 第九批：进化主线与入场天气特性

2026-10-05；基线 `6e33a02`。当前决策为**保留进化**，新开的战术远征增加九尾日照、拉普拉斯降雨。
功能自动验收通过；天气构筑的全池强度、自然终局、训练及天赋仍未完成。
本轮源码留在工作区，未新增提交或 push。

入口：[三键设备模拟页](http://127.0.0.1:8807/device) →「战术远征 · 护卫与天气」。
当前详细合同见 [24 · 进化、构筑与入场特性](../docs/24-evolution-builds-and-opening-abilities.md)。

## 1. 本轮确定与交付

- 保留 84 只各形态卡池、普通三合一和通信进化石。只抽最终形态再升星退出当前实施主线。
  持有实例训练是后续方向；没有声称训练、锁定形态、转训、石头释放装备槽已经实现。
- 九尾固定日照、拉普拉斯固定降雨，是本作自定义物种特性。普通招募副本也有；不要求主搭档，不占教学槽、不扣技能机。
- 所有实际上场单位在 `t=0` 一起申请天气，第一攻击/开场齐射之前裁定。持续八秒；同种不加时，同刻晴雨相抵恢复基础天气，
  己方混上两种天气也会相抵。已触发来源阵亡不撤销效果，每场一次。
- 晴天/求雨教学保留原生大招后、下一模拟步生效的合同；可以覆盖入场天气或延长相同天气，不追溯增强发起教学那次伤害。
  冲突/到期恢复基础天气，不建立天气栈。双方共享实际招式属性加成，雨天不自动强化冰、电招式。
- 商店、棋子、备战、冻结对手及结算按规则显示特性；三键页显示入场预告和来源角标，开战条目可长按看冲突说明。
  角标避开装备/教学点，战斗日志显示实际来源、覆盖、相抵、到期。
- 新开战术远征为 `tactics_v2`；旧 `tactics_v1` 和 `base_v1` 不升级。schema 4 不增加次数存档，特性由物种与版本派生。
  兼容已知旧指纹，旧指纹冒充新规则拒绝导入。

## 2. 自动验收与兼容

| 验证 | 结果与边界 |
|---|---|
| 完整合同测试 | 369 项通过，新增 19 项；含战斗、学习/进化、保存、三键和动画 |
| 统一执行器 | 九项通过、一项跳过：测试、编译、diff、重启恢复、动画样例、素材导出/核验、完整 Demo、真实三键帧；未运行通用 balance 项 |
| 最后界面微调 | 八项三键及十五项入场天气合同复跑通过；两份新 probe 编译及 JS 语法检查通过 |
| schema 3 旧档 | 旧固定样本操作状态及 102 条事件哈希一致 |
| schema 4 / `tactics_v1` | 从已提交 `6e33a02` 代码生成含九尾和拉普拉斯的固定样本，后续 move/lock/battle/next 的完整状态及 86 条事件哈希一致；没有入场特性 |
| 当前存档恢复 | 同一局保存/恢复的冻结对手特性、天气预告、后续完整战斗事件一致；教学和 UID 不丢失 |
| 实际用户旧槽 | 两个 schema 3 / `base_v1` 银行只读解码成功，文件 SHA256 前后不变；没有执行 resume、save 或档案同步 |
| 三键路径 | 新开→棋子详情分页→九尾学习晴天→拉普拉斯从备战上场→相抵预告→返回→恢复；仍只有 A/B/C |
| 实际展示 | 浏览器首页和隔离备战快照验证；实际 Battle 渲染四张原生关键帧、三段 GIF；定向高生命场景，不代表正常局长或 ESP32 性能 |

证据：[统一验收](evidence/abilities-2026-10-05/acceptance.json)、
[最终微调与浏览器](evidence/abilities-2026-10-05/supplementary-checks.json)、
[旧用户槽只读记录](evidence/abilities-2026-10-05/existing-save-readonly.json)、
[旧版固定样本](../tests/fixtures/tactics-v1-schema4-session.json)、
[实际动画事件](evidence/abilities-2026-10-05/visual.json)。

![隔离快照：入场晴雨相抵，角标、装备与教学共存](evidence/abilities-2026-10-05/device-formation.jpg)

[天气关键帧合集](evidence/abilities-2026-10-05/weather-abilities.png)、
[日照与后续求雨](evidence/abilities-2026-10-05/sun.gif)、
[降雨](evidence/abilities-2026-10-05/rain.gif)、
[入场相抵](evidence/abilities-2026-10-05/conflict.gif)。

## 3. 整局流程：32 局

使用四种 L2 代操作人格各八局，主种子 `2026100600–2026100631`。真实 Session、经济、卡池、奖励与动作，
仅跳过 PNG 和磁盘/档案写入；存档检查使用实际 codec。不能换算为真人游戏时长。

| 指标 | 结果 |
|---|---:|
| 完成 / 异常 / 操作阻塞 | 32 / 0 / 0 |
| 全桌战斗 / 玩家参与 | 4,034 / 771 |
| R6/R11 精确恢复 | 45 次，23 次保留待领奖状态 |
| 天气开始 / 晴雨冲突 | 3,068 / 117 次，含教学和入场特性 |
| 护卫实际触发 | 51 次 |
| 终局待领奖 | 0 |
| 自然终局 / R31 收官 | 7 / 25 |

[逐局原始数据](evidence/abilities-2026-10-05/full-run.json)。这是流程覆盖；主种子不同于第八批，
不能用 7/25 对上轮 4/28 宣称节奏得到因果改善。绝大多数对局仍需强制排名，局长问题没有关闭。

## 4. 天气确实联动，强度仍未放行

两个正式实验各十个臂，每臂同一组 100 个种子，额外换边一次验证。共 4,000 场解算，
每次换边不增加独立样本数。不同实验臂复用种子，也不计作额外主种子。
全部阵容六人口、15 金棋子、三件装备、一份教学；同一队伍只切换 `tactics_v1/v2`，站位、单位、装备、搭档与学习不变。
换边失败均为零，不代表全池平衡。

**首稿保留失败读数。** 日照接力对花园及突进都是 0%；降雨水阵只有 0–6%。八秒窗口平均有约 2–3 次技能加成，
说明机制可用，但首稿缺少有效承伤和输出组合，不能靠天气单位数量认领强度。
[首稿完整结果](evidence/abilities-2026-10-05/ability-ablation.json)及
[当时脚本快照](evidence/abilities-2026-10-05/weather_ability_probe_initial.py)均保留。

**第二阶段只换一个同费单位。** 探索种子 `310050–310069` 比较四个既有阵容替换；冻结日照控场、降雨续航后，
正式使用未参与探索的 `202610052000–202610052099`。首稿正式种子为 `202610051000–202610051099`。
[探索读数](evidence/abilities-2026-10-05/exploration.json)和[探索脚本](evidence/abilities-2026-10-05/explore.py)未删除。

| 同一阵容 / 对手 | 无入场特性 | 有入场特性 | 判断 |
|---|---:|---:|---|
| 日照控场 / 花园 | 13% | 16% | 仍弱 |
| 日照控场 / 突进 | 11% | 27% | 天气帮助早期火草启动，但仍非反突进答案 |
| 降雨续航 / 花园 | 66% | 65% | 队伍替换本身有效，降雨没有带来优势提升 |
| 降雨续航 / 突进 | 15% | 17% | 雨窗口收益小，仍明显劣势 |
| 日照控场 / 降雨续航 | 19% | 19% | 入场相抵，结果与旧规则一致 |

[全部替换对照](evidence/abilities-2026-10-05/replacement-ablation.json)。日照控场平均三次左右技能在入场窗口获得加成；
降雨续航对突进只有 0.21 次。这提示要结合实际招式属性、首次施法时点、前排承伤与启动资源，
不能仅看队伍的水属性人数。雨天来源拉普拉斯的冰招不会被水伤倍率强化。
本次没有根据这些读数临时提高全部天气倍率或加免费能量。

## 5. 复核与剩余工作

本轮三个子代理都因 `glm-5.3` 不支持当前 ChatGPT 账号而未启动，未产生评审。
按照独立评审协议记录 `reviewer_agent_status=unavailable`，本轮为**主代理普通复核**，
没有复用上轮独立通过结论认领新功能。[复核记录](evidence/abilities-2026-10-05/review.json)。

普通复核关闭两项实现问题：恢复冻结对手视图时遗漏规则版本，导致特性展示丢失；
新入场角标初始位置遮盖装备/教学点，已改位置并做合同与实际浏览器检查。

仍需逐项推进：有效反突进和治疗反制；机制型羁绊与小型天赋池；持有实例训练和安全付费账；
终形态重复卡用途；天气/应对件 AI 估值；自然终局与真人三键操作负担；ESP32 GPIO、NVS、刷新性能及满人口资源。
天气功能原型可试玩，不代表上述总体审计遗留已经完成。本轮未请求提交或发布，保留工作区供下一轮继续。

复现：

```sh
python3 tools/acceptance/system_acceptance.py --demo --presentation --output .build/entry-weather/acceptance.json
python3 tools/acceptance/tactical_run_probe.py --ruleset tactics_v2 --games 32 --seed-base 2026100600 --output .build/entry-weather/full-run.json
python3 tools/acceptance/weather_ability_probe.py --variant initial --seeds 100 --start-seed 202610051000 --output .build/entry-weather/ability-ablation.json
python3 tools/acceptance/weather_ability_probe.py --variant replacements --seeds 100 --start-seed 202610052000 --output .build/entry-weather/replacement-ablation.json
python3 tools/acceptance/weather_ability_visual_probe.py --out .build/entry-weather/visual
```

[本批源码与证据清单](evidence/abilities-2026-10-05/source-manifest.json)绑定当前文件哈希。
