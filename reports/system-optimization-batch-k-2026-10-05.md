# 第十一批：进化决策与公平性复核

2026-10-05；承接并已推送第十批 `914e89c`。本批保留84个关都形态，新增战术入口 `tactics_v5`，战斗与R20压力沿用v4；不加入二世代、训练或终点升星。

## 交付

| 工作包 | 实际改动 | 验收证据 |
|---|---|---|
| K1 进化公平性审计 | 按完整血统分区；比较直购/材料路线的本金、卡池、最低占位、退款、获取近似与职责；同预算九尾/拉普拉斯换槽对照 | [27号](../docs/27-evolution-fairness.md)、[专项报告](evolution-fairness-2026-10-05.md)；84=47+33+4、31条路线、37终点重复不合成；16臂×100种子、换边零失败；逐种子原始数据和失败模型归档 |
| K2 预览、暂缓与一步进化 | 真实合成函数复制预演；显示职责/费用/库存/人口/羁绊/继承；暂缓同名实例、按UID锁定/解除、明确只进化一步；schema4按规则保存锁 | [28号](../docs/28-evolution-choice-contract.md)；13专项测试：递归预测、零变更、第四张、容量/缺货、继承/战术、写失败、备份、旧规则/金样本；20种子v4/v5完整事件一致 |
| K3 三键与表现 | 两种购买选择、默认取消、完整分页详情、锁定菜单与恢复；修复摘要对象、教学回仓字典与菜单重叠 | 6设备专项；3条流程共356条记录（326个down/up/tick/state输入＋30条注记）；28控制器快照及240×320原生PNG；零浏览器错误；主代理目视预览、确认、实例菜单、一步进化及详情，非独立美术或真机验收 |

统一验收 `reports/evidence/batch-k-2026-10-05/acceptance.json`：415测试＋九项选定检查通过。包含编译、diff、真实进程存档恢复、动画样本/资源导出与验证、两局HTTP完整流程、真实帧三键播放至下一轮。最后一次画面布局修改后又跑6设备专项、Python编译、Node语法与实际原生渲染；对应结果见同目录，不能把先前重叠画面作为通过证据。

新v5流程探针32局全部完整、零异常，3804战斗、43次精确codec回读，终局无待领奖励；28自然终局、4强制排名，平均29.09轮。它使用已有L2自动策略，不测主动暂缓策略或真人时长，不替代第十批100局节奏估计，也不能说明v5改善了自然终局。

## 公平性判断

当前是47个可进化中段、33个已进化终点、4个天生无关都进化线；33中31个现行可达、雷伊布/火伊布2个只能直购。终点都按自身费档直购，三张重复终点都不继续合成，证明的是规则一致性；全池价格和战术强度仍未验证。

进化路线通常更贵：三张T1到T2为3金，直购2金；基础形态完整三段为9金，直购终点2或3金。优势是更早可见、过渡、继承和残值；代价是占用池、金币、备战与3→1人口/羁绊损失。终点间的同槽对照显示队伍契合有方向相反的结果，不支持“进化终点天然优于单阶段”的结论。

建议继续保留进化，用预览和暂缓让路径成为玩家选择。若以后加终点成长，让33个已进化终点与4个天然终点共用投资层；不加可进化专属第二层成长。伊布分支清晰性、少数边以外的职责变化、共同后期成长、侦察/转型AI及真人三键整局仍待后续包。

## 复核、失败记录与边界

- 独立复核使用本批新run，最终记录 `reports/evidence/batch-k-2026-10-05/independent-review.json`，源码/证据绑定见最终manifest；第十批结论不借用为本批结论。
- 本地QualityGate raw/gate通过、零actionable block、执行完成。`agent_action.task_complete=false`，中央MCP语义工具不可用，mutation未执行；不宣称中央语义通过。最终本地原始输出 `qualitygate.json`。
- 首轮415测试中一条旧测试把新v5当未知版本；改为仍未知的v6，10专项及最终全量通过。首轮失败完整保存为 `acceptance-initial-failed.json`。
- 公平性初稿错误把累计9材料当成必须同时持有9单位；修订为顺序合成最低峰值5，成本/占池不变。初稿证据保留在fairness目录archive，静态/战斗均按修订探针重跑。
- 第一轮PC截图的紧凑副标题重叠、继承文字出框以及捕获过程中源改变，分别归档于device目录archive；冻结后重跑控制器证据（source stable=true）和渲染，不能只替换失败图片而抹掉原因。
- 用户原schema3/base_v1双银行只读哈希不变，未把验收数据写进原档。PC预览8807已刷新当前源码，GET /device=200；旧存档仍按旧规则继续。
- 固定骨架、满池独立近似和自动流程不证明整池获取公平、真人决策或真机性能。旧v4全状态/89事件金样本及base/v1/v2既有金样本通过；旧fingerprint不能伪装为v5。

## 复现

```sh
python3 tools/acceptance/system_acceptance.py --demo --presentation --output .build/batch-k/acceptance.json
python3 tools/acceptance/evolution_fairness_probe.py --battle --battle-seeds 100 --battle-start-seed 2026100570000 --battle-ruleset tactics_v4 --output .build/evolution-fairness
python3 tools/acceptance/tactical_run_probe.py --games 32 --seed-base 2026100500 --ruleset tactics_v5 --output .build/batch-k/tactical-full-run.json
python3 tools/acceptance/evolution_device_probe.py --out .build/evolution-device
NODE_PATH=<已安装Playwright的node_modules> node tools/acceptance/evolution_device_capture.js .build/evolution-device/snapshots .build/evolution-device-png
```

捕获工具仅渲染快照，通过本地8807只读获取精灵；不执行用户对局动作。探针使用隔离存储；重新运行证据输出应使用新的 `.build` 目录，保留历史原始失败。
