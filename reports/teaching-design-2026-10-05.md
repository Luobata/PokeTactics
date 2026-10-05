# 技能机器与学习资格设计审计（首包设计稿）

日期：2026-10-05（Asia/Shanghai）。基线：`93de08e`。状态：只读设计，不是正式玩法，未修改 `sim/`、`data/`、现有 6 个教学、规则指纹或用户存档。

## 交付

- [docs/30-skill-machines-and-learning.md](../docs/30-skill-machines-and-learning.md)：8 台新增候选、独立学习资格、进化返还策略、准备期挂点与验收。
- [docs/design/teaching-skills-v1.json](../docs/design/teaching-skills-v1.json)：8 机器、84 形态逐形态资格/理由、35 族能力标签与完整参数。
- [tools/acceptance/teaching_design_probe.py](../tools/acceptance/teaching_design_probe.py)：只读正式池，导出学习矩阵、逐对理由、进化继承与失配证据。

首包冻结为 `guardian_riposte`（守备反击）与 `tempo_break`（心律截断）。二者分别复用既有击退/迟滞与确定能量削减语义；`breach_lunge` 与 `arc_lock` 保留在目录中但降为后续，因为前者与当前突进方向重合，后者需要新增逐来源回能钩子。

## 探针结果

命令：

```sh
python3 tools/acceptance/teaching_design_probe.py --output .build/teaching-design-new
```

结果 `ok: true`：

- 正式形态 84、进化族 35、进化边 47、终点形态 37、天然终点族 4。
- 主资格覆盖：breakthrough 30、counter 19、suppression 20、rally 15，合计 84。
- 机器覆盖：breach_lunge 30、guardian_riposte 19、arc_lock 20、rally_signal 15、expose_weakness 26、standburst 12、field_triage 11、tempo_break 10。
- 全部 37 个终点均有主资格；天然终点与进化终点同规则。
- 47 条进化边中存在 24 个“当前可学但目标不可继承”的机器-边组合：breach_lunge 10、rally_signal 8、field_triage 4、guardian_riposte 1、arc_lock 1。设计要求确认前预览，确认成功后返还机器。
- 现有 6 教学目录与兼容计数保持 `cut=41、surf=18、rest=84、guard=84、sunny_day=17、rain_dance=23`，未回改。
- 体格公式明确为 `base.hp + 2*base.defense`（不使用特防，也不读取原作学习表）。
- 八台的目标、时序、消耗、叠加和系统联动已补确定性合同；后六台仍未实现，候选参数未平衡。
- 首包结构化参数已冻结：`guardian_riposte` 为 `delay_seconds=0.3`、`push_cells=1`、`uses_per_battle=1`；`tempo_break` 为 `energy_loss=20`、`uses_per_battle=1`，0 能量时 `actual_loss=0` 仍算消耗。
- 设计 JSON SHA-256：`a01c737d53e5f5e9e5f0bb85496778f51be98517d1be6c571a341800185c2cf2`。
- 源哈希：30 号文档 `8ebe59ad35f772e08bc2ca7f8a58220d99bf109c8392d9a70d56a357c7ff46c1`；设计探针 `2fbf193b9931cb5b93d97375aba9e40c188b73b1db115300050d43be4051f4a8`。

导出物：

- `reports/evidence/teaching-design-2026-10-05/design/summary.json`
- `reports/evidence/teaching-design-2026-10-05/design/learning-matrix.csv`（84 行 × 14 台＝1176 个判定，含现行 6 台）
- `reports/evidence/teaching-design-2026-10-05/design/pairwise-eligibility.json`（84 形态 × 8 新机器＝672 对，含不可学理由）
- `reports/evidence/teaching-design-2026-10-05/design/evolution-inheritance.json`（47 条边）
- `reports/evidence/teaching-design-2026-10-05/design/evolution-incompatibilities.csv`（24 对失配）

## 复核

- `python3 -m py_compile tools/acceptance/teaching_design_probe.py` 通过。
- `python3 -m json.tool docs/design/teaching-skills-v1.json` 通过。
- `git diff --check` 通过。
- 额外核对：学习矩阵 84 行、14 个判定列、1176 个判定；`pairwise-eligibility.json` 672 条且只覆盖新增机器。
- 探针多轮运行通过；最终轮覆盖 teaching_effect 六元组合同、结构化参数、冻结阈值、体格公式与 84×14 全学习矩阵。
- 本报告不声称强度平衡、真人三键体验、真机表现或完整局获取成立；本轮随后完成的隔离 prototype 见 [teaching-prototype-2026-10-05.md](teaching-prototype-2026-10-05.md)，正式版本验收仍未完成。最终文字明确反击按命中距离判定，固有远程贴身可触发；ENERGY_MAX=80，空收益仍是同一 teaching_effect，不另发 tempo_zero。
