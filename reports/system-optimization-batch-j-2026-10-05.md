# 第十批：付费封疗、阵型联动与自然收官

2026-10-05。基线 `d3a26ce`（第九批已独立复核、提交并推送）。当前合同[26号](../docs/26-counterplay-and-natural-end.md)，进化取舍[25号](../docs/25-evolution-direction-review.md)。本批不加入二世代、不改进化和训练。

## 工作包与验收边界

| 工作包 | 交付 | 验收证据 |
|---|---|---|
| 有效反制/联动 | v3/v4封疗针、统一实际治疗、旧配方隔离；同预算角色/站位梯度与代价分析 | 9项反制/保存合同、2项实际A/B/C流程；[100种子对照](evidence/counterplay-2026-10-05/README.md) |
| 自然终局 | v4 R20起败方至少掉21，保留R30野怪奖励，准备详情预告 | 10项pacing＋3项整局恢复合同；[100完整局双臂](natural-end-2026-10-05.md) |
| 动画反馈 | 实际命中徽记、减少恢复浮字、同步回血、死亡/到期隐藏、短日志及百分号字形 | 3项表现测试、[真实原生PNG/GIF](evidence/counter-visual-2026-10-05/visual.json)，主代理目视检查 |
| 进化权衡 | 保留/移除两种连贯玩法、推荐与启动条件 | [25号文档](../docs/25-evolution-direction-review.md)静态84形态/47进化边审计与已有合同；移除方向未实现 |

## 结果

同预算幽影护阵对原突进20%→83%，镜像突进只有23%；对花园0%、控场32%，存在明确破坏路径。选护卫相对同队未选没有改变赢家，不能归因成护卫独立收益。

控场对花园：聚焦镜8%、针无效果11%、完整针34%；完整针相对无效果净增23个百分点，26正向/3反向，实际减少7402HP治疗。对突进牺牲启动使16%→1%，封疗并未弥补；电流没有窗口内真实治疗可减少。原失败样本与更强75%/10秒探索均归档，不筛选成功队报告。

新压力100局自然冠军21→93，强制79→7，均零异常。93%的Wilson95%下界86.25%，只通过观察率初筛。R20 `end_prep` 后100对种子的显式席位投影（存活、HP、名次、等级、金币、上场/备战/合成/技能机计数）与待领奖励均一致；R25玩家存活45→25、全桌席位450→335、技能机均值38.05→35.24。完整真人操作时长未验收。

旧v2冻结档动作全状态及89条战斗事件哈希保持一致；新装备/压力显式版本化，不自动升级旧局。新三键验收使用隔离档，覆盖取消、确认、重复释放、装备返还、重启恢复和陈旧确认失效。

## 复现

```sh
python3 tools/acceptance/system_acceptance.py --demo --presentation --output .build/batch-j/acceptance.json
python3 tools/acceptance/counterplay_probe.py --help
python3 tools/acceptance/pacing_probe.py --games 100 --seed-base 2026103000 --arms baseline_v3 floor21_v4 --output .build/pacing/natural-end-n100.json
python3 tools/acceptance/counter_visual_probe.py --out .build/counter-visual
```

反制正式种子范围、无效果控制、换边方法与自镜像诊断修订以原始证据README为准。自然原始逐局大文件采用无损gzip归档，manifest记录压缩/原文双哈希。

## 发布复核

最终统一验收396项测试、九项检查全部通过（全池balance项未运行，以本批定向实验记录）。Python编译、JS语法、diff检查通过。QualityGate本地gate/raw_gate=pass、block_merge=false、execution_complete=true、quality_confidence=full、incomplete_engines空、actionable block=0；mutation_status=not_applicable，未执行mutation。工具agent_action为local_checks_passed、task_complete=false，要求补语义与测试；本批以独立代码/证据审计补复核，中央语义工具不可用，不虚报其完成。

探针阶段标签最后修正后只重跑同种子identity100次、编译/diff与局部本地gate，均通过；旧Phase II标签错误保留并在README消歧，不改旧原始矩阵。

独立复核已完成当前代码/证据审计，无阻断，结果为pass_with_risk：上述护卫因果、统计下界、真人/真机和全池边界仍保留。

统一验收、QualityGate本地结果、独立复核与最终源/证据哈希见 `evidence/batch-j-2026-10-05/`。没有调用不可用的中央MCP语义规则；本地工具报告不能代替独立代码与证据审计。已重启已知本项目预览服务加载当前源码，`/device`只读冒烟200，两个用户银行字节哈希未变；PC原生画面不代表ESP32真机验收。
