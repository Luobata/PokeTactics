# 第十二批审计证据

2026-10-05（Asia/Shanghai），基线 `24090f5`，现行 `tactics_v5` / `budget_v1`。没有改正式游戏值。

- `inventory.json`：84形态的技能/射程/教学、配方和羁绊目录，齐射14系实际构造与岩/钢遮蔽证明。审计角色标签重叠，不是新职业。
- `summary.json`：同11配置/7人工方向/55对阵摘要及全部筛查结果，不删除失败配置。
- `matrix.csv`：行配置对列配置的得分，平局半分；本次无平局。空对角线未测，不填写50%。
- `tournament.json.gz`：包含完整目录、配置和每对阵100种子的winner、时长、双方战斗指标、事件SHA；每个种子另跑换边。完整事件本身可用冻结源码/配置/seed重算，不把摘要称为完整事件原始数据。
- `replay-checks.json`：55组首种子的重放结果，与保存的完整事件SHA核对；含最初用Unit对象身份误判结果字典的验证失败原因及修正。
- `acceptance.json`：资源一致性、源稳定、用户银行未变、换边和重放验收。
- `expansion-comparison.json` 与 `archive/tournament-before-volley-expansion.json.gz`：扩展齐射静态审计前后的实际battle段及双哈希绑定；规范JSON字节一致。旧审计探针源码未另存，旧artifact仅作历史证据；最终探针可重放相同battle段，其他sim/data/helper依赖哈希未变。
- `qualitygate.json`：最终审计脚本的本地原始结果；无匹配脚本规则、无AST/中央语义覆盖，task_complete=false。
- `qg-runner.json` / `qg-repo-readiness.json`：完整runner缺依赖、当前指定仓库key外置capsule未就绪的诊断；不将外置onboarding或中央语义视为完成，不安装/升级依赖或启动mutation。
- `manifest.json`：4个交付源、运行依赖、证据、压缩与解压双哈希；排除自身及最终独立复核记录以避免循环。

方法先声明11套候选和100种子，再运行。扩展齐射静态审计后全部55组重跑，与原来战斗部分逐字相同。55组同种子换边是对称校验，不扩大N；各对阵共用同一组100种子，不能称为5,500个全局独立主种子。

首次独立复核因交接顶部过时的提交指代阻断；原始复核、当时manifest与交接副本保留在archive。修订只更新交接事实与证据绑定，不改游戏、探针、候选、种子或最终战斗数据；最终复核另存，归档不代表当前通过。

“有取舍”仅是跨人工方向至少一个优势/劣势的探索筛查，逐对阵Wilson区间未校正多重比较。没有真实招募/组件取得/进化本金/AI/真人/真机证据；整套阵容胜率不能归因于单一护卫、天气或道具。

```sh
python3 tools/acceptance/system_depth_probe.py --battle --seeds 100 --output .build/system-depth-new/tournament.json
python3 -c "import gzip,json; p=json.loads(gzip.decompress(open('reports/evidence/system-depth-2026-10-05/tournament.json.gz','rb').read())); print(p['battle']['summaries'])"
```
