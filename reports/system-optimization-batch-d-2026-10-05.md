# 第四批交付：专属机制、物种部件与 AI 遗留

本批把核心角色的差异落实到战斗结果：从 3 种专属机制扩到 8 种；完成喷火龙、
水箭龟、妙蛙花的不同部件轨道，并修复 AI 追卡/估值/射程、免疫、伤害统计和
附属效果时序。完整系统 review 尚未全部结束，剩余范围保留在
[分系统路线](../docs/14-system-optimization-acceptance.md)。

## 已交付及可验收行为

| 模块 | 改动与验收 |
|---|---|
| AI 复制件 | 只有存在真实 3 合 1 路径才获得追卡奖励及对子保护。终形与伊布叶节点不再虚增价值；通信族保留既定第三张惩罚。回归能复现旧版卖掉妙蛙花、保两只弱巴大蝶的问题。 |
| AI 单体价值 | 买入、出售、上场共用含档案倍率的底价；满仓能接受真实战力更高的新棋。尚未实现完整阵容边际价值模型。 |
| AI / 战斗角色 | 站位、对位、装备和远程攻速惩罚共用有效射程。雷丘启用三格档案后不再被当作近战，关闭档案仍回退原值。 |
| 伤害 | 属性免疫保持零伤害；非零克制保留最低伤害。damage_dealt 按实际 HP 减少量计数，不计入过量伤害或披带阻挡量。 |
| 物种动作 | 喷火龙手臂与翼、水箭龟双炮、妙蛙花花盘与双藤鞭已接入，普攻/大招使用不同轨道；命名挂点供真实特效发射。 |
| 演出因果 | skill_effect 以主施法索引和事件包长度精确归属；第三方治疗、能量、畏缩与击退随主技能命中落地。同刻独立行动保持独立。 |
| 页面 | 编辑器显示当前角色的部件、技能用途、反制与实际效果记录；比较栏改为“默认参数 / 调参结果”。研究室显示 8 专属机制与 3 套实际部件动作，5 套规划定义明确标注未接入。 |

技能数值、对象上限、反制和框架接口见[设计合同](../docs/18-character-skills-and-rigs.md)。

| 角色 | 真实招式与战术结果 | 最新样片 |
|---|---|---|
| 喷火龙 | 喷射火焰，目标邻格溅射 | [普攻](evidence/character-signatures-2026-10-05/samples/6-attack.gif) · [大招](evidence/character-signatures-2026-10-05/samples/6-cast.gif) |
| 水箭龟 | 水炮，最多两名额外目标贯穿，再击退主目标 | [普攻](evidence/character-signatures-2026-10-05/samples/9-attack.gif) · [大招](evidence/character-signatures-2026-10-05/samples/9-cast.gif) |
| 妙蛙花 | 日光束，按实际伤害治疗附近受伤友军 | [普攻](evidence/character-signatures-2026-10-05/samples/3-attack.gif) · [大招](evidence/character-signatures-2026-10-05/samples/3-cast.gif) |
| 雷丘 | 十万伏特，最多两跳，地面免疫可截断 | [普攻](evidence/character-signatures-2026-10-05/samples/26-attack.gif) · [大招](evidence/character-signatures-2026-10-05/samples/26-cast.gif) |
| 胡地 | 精神强念，瞬移切入最弱目标 | [普攻](evidence/character-signatures-2026-10-05/samples/65-attack.gif) · [大招](evidence/character-signatures-2026-10-05/samples/65-cast.gif) |
| 耿鬼 | 舌舔，偷取能量并回流自身 | [普攻](evidence/character-signatures-2026-10-05/samples/94-attack.gif) · [大招](evidence/character-signatures-2026-10-05/samples/94-cast.gif) |
| 隆隆岩 | 地震，邻格伤害与短暂畏缩 | [普攻](evidence/character-signatures-2026-10-05/samples/76-attack.gif) · [大招](evidence/character-signatures-2026-10-05/samples/76-cast.gif) |
| 卡比兽 | 破坏光线，近身波及与自愈 | [普攻](evidence/character-signatures-2026-10-05/samples/143-attack.gif) · [大招](evidence/character-signatures-2026-10-05/samples/143-cast.gif) |

大招使用预充能、固定站位的真实 Battle 首次施法夹具；妙蛙花带受伤友军，
雷丘对三只可导电目标，水箭龟对一列目标。初始条件公开记录，所有后续命中、
治疗、位移均由解算生成。此夹具证明机制与演出，不证明正常对局的施法频率。

## 验收证据

统一命令：

```sh
python3 tools/acceptance/system_acceptance.py --demo --balance --presentation --output .build/acceptance/batch-d-final.json
python3 sim/experiment_signatures.py --seeds 7 11 29
```

| 检查 | 最终结果 |
|---|---|
| 完整自动验收 | [JSON](evidence/character-signatures-2026-10-05/acceptance.json)、[日志](evidence/character-signatures-2026-10-05/acceptance.log)：9 通过、0 失败、0 跳过 |
| 单测 | 179 项通过；相对上一批新增 51 项，覆盖 AI、技能、部件、因果时间轴、挂点与页面资料 |
| 存档 | 真实进程重启、备份、损坏导入不覆盖当前进度等检查通过；本批未改存档格式 |
| Demo | seeds 7/42，25 场玩家战斗、6,333 帧、728 次 HTTP 200，均能完成整局 |
| 定向技能 | [48 场记录](evidence/character-signatures-2026-10-05/signature-mechanics.json)：8 角色 × 3 种子 × 档案开关；四项触发/开关/事件差异检查通过，balance_validated=false |
| 样片 | [清单](evidence/character-signatures-2026-10-05/samples/manifest.json)：16 段 240×320 GIF；PC p50 4.091ms、p95 6.050ms，样本粒子峰值 36/192，技能轨峰值 1/3 |
| 资源 | [美术清单](evidence/character-signatures-2026-10-05/samples/art-manifest.json)：84 棋子、151 资源记录、8 专属/75 通用/1 无招式、3 已实现部件/5 计划部件；导出和校验通过 |
| 浏览器 | [记录](evidence/character-signatures-2026-10-05/browser-acceptance.json)：现有 lab 刷新后显示新覆盖；编辑器实测日光束治疗 117、雷丘两次追加伤害 50/32，阶段跳转和状态可见 |
| 独立审查 | [记录](evidence/character-signatures-2026-10-05/review.json)：sim 与动画两名独立 reviewer 最终均 pass，4 项遗漏已修复并窄复验 |

独立审查关闭：AI 忽略档案射程、远程实验惩罚漏乘、普攻未接挂点、
耿鬼吸能回流被同刻击退改写终点。最后一项增加结算前 caster_pos 快照，并用真实
双施法事件复现、验证原坐标和像素回放。

QualityGate 本地 CLI 返回 pass，但有效规则快照为空；MCP 规则/语义服务不可用，
不作为有效质量覆盖。Mutation 按既定暂停未执行。见[限制记录](evidence/character-signatures-2026-10-05/qualitygate-summary.json)。
以上独立审查与项目测试是另外执行的证据，并非中央语义检查。源码绑定见
[指纹](evidence/character-signatures-2026-10-05/source-fingerprint.json)。

## 仍未完成

40 局、seed 20261004 的旧四条判据通过，平均 30.8 轮，中位 31，区间 27–31；
27/40 局到达 R31。L0/L1/L2/L3 平均名次为 7.97/3.36/4.47/4.55，
copycat 人格平均 5.71，未达到难度单调或人格平衡。下一步需要围绕候选阵容价值、
羁绊边际收益、追卡与升人口机会成本做配对实验，不能靠这批 bug 修复宣布策略完成。

其余五只的部件轨、完整角色素材、逐部件关键帧编辑器仍待制作。当前切片与程序化
藤鞭不能替代完整手绘素材；大角度转身、遮挡面及跳跃需专门资源。
小核心池、独立星级、天赋、教学、完整三键、音频、图鉴、完整历史回放及 ESP32
设备后端仍未交付。当前数据接口可用于后续通用运行时，C 采样/绘制/设备预算尚未实测。
