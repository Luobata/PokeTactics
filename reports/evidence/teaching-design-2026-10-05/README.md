# 技能机器设计与首批实验的证据

2026-10-05，基线 `93de08e`。本目录只发布设计与隔离实验，正式目录仍为旧6教学。总报告见 [teaching-prototype-2026-10-05.md](../../teaching-prototype-2026-10-05.md)。

| 文件 | 内容 |
|---|---|
| `design/summary.json` | 84形态/35族、1176学习判定、672新增对、47进化边/24失配及最终设计哈希 |
| `design/learning-matrix.csv` | 原6＋新8的逐形态可学/不可学与理由，不读取原作学习表 |
| `design/pairwise-eligibility.json` | 新8台的672判定及不可学理由 |
| `design/evolution-inheritance.json` / `evolution-incompatibilities.csv` | 47边及24失配；正式预览/返仓未实现 |
| `preparation-checks.json` / `preparation-tests.log` | 现行4目标42专项、54输入源/依赖前后哈希、两银行保护 |
| `tests-final.log` | 新原型14专项真实命令输出 |
| `league.json.gz` / `league-final.log` | 2候选×4对手×3臂×100主seed加控制4800场、逐seed结果/指标/完整事件SHA、配置与源码哈希 |
| `build-checks.json` | 最终编译/JSON/空白、运行源绑定、正式源/指纹与用户银行保护 |
| `qualitygate-final.json` / `.log` | 本地原始扫描；无适用脚本规则、无中央语义覆盖，task_complete=false |
| `decision-delta.json` / `decision-replay-record.json` | 中央语义不可用时本地记录的公开实现取舍，不是语义裁决 |
| `design-review-final.json` / `archive/design-review-initial.json` | 后六候选设计缺口的独立blocked与窄复核pass，不是最终代码放行 |
| `main-agent-self-review.json` / `archive/review-service-errors.json` | 最终独立审阅三次429未得verdict；主代理普通复核的24事件重放/8统计/8边界与哈希检查，非独立审阅 |
| `manifest.json` | 交付/依赖/证据/压缩和解压双哈希，不含自身和最终review记录 |

联赛换边2300次只作对称控制，自镜像100次作identity，另24首seed逐字重放。不同对手复用同100种子，不能把4800场说成4800独立主种子；此批无平局，配对p未校正多重比较。每场完整事件本身可由冻结配置/源/seed重算，本目录保存其SHA和真实指标，不把摘要称为完整事件原始数组。

`archive/` 保留初次smoke错误自镜像翻转断言、修正smoke、计数解析修正前的准备检查与文档，以及设计文字修订前联赛。`distance-wording-comparison.json` 对账两轮最终battle段一致。`design-before-prototype/` 只保存开始原型前的探针输出和当时设计hash，未另存原设计草稿，不当作最终源可重放快照。

动画独立位于 [teaching-visual-2026-10-05](../teaching-visual-2026-10-05/visual.json)，含真实10场景、PNG/GIF与未改原事件对账。`visual.failure-scheduling.json` 保留修正前owned move/state晚于overlay的问题及原始事件数组；修复只在验收adapter，未修生产时间轴。`visual.v1-input.json` 为旧metadata备份，旧版探针源码未另存，不能用它宣称旧输出能从最终源重放。

主代理目视、普通代码复核与设计专项独立审阅分开记录；没有独立美术或ESP32真机验收，最终独立代码审阅服务三次失败。review状态与主代理最终复核单独发布，排除manifest以避免循环。教学层预算只检查常量绘制成本估计，未验证原生/天气/教学共享总预算。Mutation暂停未执行，中央语义工具不可用不能用普通review冒充。

```sh
python3 tools/acceptance/teaching_design_probe.py --output .build/teaching-design-new
python3 -m unittest tests.test_teaching_prototype -v
python3 tools/acceptance/teaching_skill_prototype.py --seeds 100 --output .build/teaching-prototype-new.json
python3 tools/acceptance/teaching_visual_probe.py --out .build/teaching-visual-new
```
