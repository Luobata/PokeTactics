# 进化公平性审计报告 · 2026-10-05

基线提交 `914e89c`；探针在 v5 进化选择实现后的冻结工作区指纹上运行，sim/data 依赖哈希记录于 `static.json` 与 `battle.json`。设计与完整结论见 [27 号文档](../docs/27-evolution-fairness.md)。

## 验收结果

- 84 模板完整分区：47 可进化中段 + 33 已进化终点 + 4 天然无进化线；33 = 31 现行可达 + 2 伊布分支不可达。费档 34/32/18，33 个已进化终点前驱全在池内。
- 37 个终点各构造三张直接复制并调用 `try_combine`，全部无日志、无合并、无来源账变化；终点重复规则一致且均无升星。
- 31 条可达路线完成直购/材料路线账：10 条 `直购2/路线3`（1条通信族）、8 条 `直购2/路线9`、8 条 `直购3/路线3`（2条通信族）、5 条 `直购3/路线9`。普通三合一最终人口 -2；一步路线累计占 4 张池，三段路线累计占 13 张。三段线累计 9 张基础购买，顺序合成最低同时持有 5 单位；旧“峰值9”证据已归档。
- 47 条进化边中 14 条有非费档职责变化、27 条仅费档变化、6 条无跟踪维度变化。
- 100 独立种子 × 16 臂有界战斗：换边失败 0。证据实际规则为 `tactics_v4`；v5 战斗/压力数值一致性需独立路由/事件测试。九尾/拉普拉斯同槽互换在两个骨架中方向相反，显著差异只出现在部分对手，不能证明进化类别本身强弱。
- 运行中静态与战斗源依赖均稳定；换边和静态断言零失败。0% 战斗臂是边界结果而非测试失败，固定骨架边界保留，不声明全池平衡。

## 证据

目录：`reports/evidence/evolution-fairness-2026-10-05/`

- `battle.json` 与 `static.json` 均已用顺序峰值修订后的探针重跑并记录脚本 SHA；初版峰值证据保留在 archive。
- `archive/superseded-20261005-peak-model/`：保留初版“等齐9张”峰值模型的原始证据与失败原因。

- `static.json`：分区断言、逐形态表、路线账、获取概率、源指纹。
- `battle.json`：预声明、16 臂逐种子结果、paired 对比、换边失败和源指纹。
- `templates.csv`、`evolution_edges.csv`、`endpoint_routes.csv`、`acquisition_full_pool.csv`：可复现原始表。

## 验证

- `python3 -m py_compile tools/acceptance/evolution_fairness_probe.py` 通过。
- 静态探针修复后重跑通过；16 臂 ×100 种子战斗用修订版探针重跑，换边失败 0，静态与战斗源依赖及脚本哈希记录完整。
- `QG_LOCAL_MUTATION_ENABLED=0 quality-gate gate --workspace . --mode local tools/acceptance/evolution_fairness_probe.py` 通过；mutation intentionally not executed。中央 MCP 语义复核本轮不可用，本地 PASS 不扩大为中央语义 PASS。

复现命令见 27 号文档。公平性审计工作包只新增审计工具/文档/证据；同批进化选择工作包另有正式 sim、demo、保存和 UI 改动。
