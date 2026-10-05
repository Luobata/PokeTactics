# 第十三批补充审计证据

2026-10-05（Asia/Shanghai）。总报告：[teaching-audit-2026-10-05.md](../../teaching-audit-2026-10-05.md)。

| 记录 | 内容与范围 |
|---|---|
| `code-initial.json` / `evidence-initial.json` | 两路审阅者原始初判，逐字保留，绑定已推送cf087de；均pass_with_risk、零阻塞 |
| `code-final.json` / `evidence-final.json` / `review-state.json` | 同具体问题的窄复验与最终汇总；汇总由主代理写，不冒充第三份独立审阅 |
| `preflight.json` / `frozen-hashes.json` | 审计前工作区/编译/银行保护，逐文件历史冻结hash与7份压缩双hash |
| `review-generate.json` / `recheck-generate.json` / `review-input.json` | 原不可变提交run、新窄修正run，以及源/证据hash和复验指纹 |
| `prior-local-review-state.json` | 启动时的旧本地状态，含三次429无verdict历史；不是当前独立结论 |
| `tests-final.log` / `affected-validation.json` | 当前源20项通过、编译/空白、48个联赛输入未变、银行与37媒体字节对账 |
| `packet-cases.json.gz` / `packet-artifact.json` | 三个真实案例完整事件/cause/owned/HP对账；压缩与解压双hash |
| `visual.json` / `visual.log` | 当前探针的10场景重跑metadata及命令输出；37份媒体与原目录文件逐字节一致 |
| `negative-success-before.log` | 主代理追加“负场景带真实成功包”测试的四处真实失败，修正后纳入20项 |
| `raw-log-formatting.json` / `.gitattributes` | 暂存检查发现原始unittest日志一处尾空格；不改原字节，只对该单文件豁免空白诊断，代码仍正常检查 |
| `test-teaching-visual-probe-before.txt` | 实现者在旧源上运行新增测试的真实红结果（4项：3失败/1错误） |
| `test-teaching-visual-probe-intermediate-*.txt` | 中间payload变量覆盖失败记录及strict-refactor诊断摘要，后者不是完整raw traceback |
| `commands-final.json` / `test-teaching-prototype-visual-final.txt` 等 | 实现阶段命令与19项快照，早于主代理第20项负路径门；保留历史，不作为最终源绑定 |
| `qualitygate-readiness.json` / `qualitygate-final.json` / `.log` | 本轮真实诊断/扫描；中央工具缺失、readiness不完整、无匹配规则覆盖，task_complete=false |
| `manifest.json` | 当前补充源/证据/原始审阅hash，另指向cf087de旧manifest；排除自身 |

原37媒体位于 [teaching-visual-2026-10-05](../teaching-visual-2026-10-05/visual.json)。原学习/4800联赛/设计审阅/429记录保留在 [teaching-design-2026-10-05](../teaching-design-2026-10-05/README.md)。不改旧失败或旧manifest：原11源包含已更新的交接/视觉探针，其历史hash需通过 `git show cf087de:<path>` 验证；新源由本目录manifest另绑。

```sh
python3 -m unittest tests.test_teaching_prototype tests.test_teaching_visual_probe -v
python3 tools/acceptance/teaching_visual_probe.py --out .build/teaching-audit-replay
gzip -dc reports/evidence/teaching-audit-2026-10-05/packet-cases.json.gz > .build/teaching-audit-packets.json
```

新视觉metadata记录当前源hash，媒体比较见 `affected-validation.json`。当前两个教学只在隔离PrototypeBattle中生效；本次独立文字审阅不包括美术观感、真机或正式规则接入。
