# 远征应用层独立审查

日期：2026-10-05。最终结论：**pass_with_risk**。本次发现的应用层缺陷均已修复并复验，无未关闭 blocker。保留风险是旧版备份身份识别和明确的档案容量边界，详见下文。

## 范围与独立性

- Reviewer：`/root/meta_profile_impl`，由主代理委派的应用层 reviewer。
- 仓库：`/Users/bytedance/luobata/PokeTactics`；分支 `main`；基准 HEAD：`e2246f3dc924eaf30cbba95a203ca2c11c47da0b`。
- 审查对象：工作区中的 `tools/acceptance/expedition.py`、`demo.py`、`session_save.py`、`server.py`，覆盖 session/profile 事务顺序、恢复与备份幂等、schema 1/2 兼容、不可信导入和各战斗路径的伙伴配置。
- Reviewer 未修改上述应用层文件；修复由主代理完成。Reviewer 曾实现 `sim/metagame.py`、`meta_profile.py` 及对应测试，因此本报告不把这些文件的自测称为独立代码审查；其容量合并缺陷由另一位 `/root/expedition_independent_review` 独立发现。
- 最终应用层输入指纹：`b3a4cef0c37ab82b89afde4d651e9626ee0f1692d9b8d3e45fe6e9c46925b64f`。算法为 SHA-256，依次拼接上述四个文件的仓库相对路径 UTF-8 字节和文件原始字节，顺序为 expedition、demo、session_save、server。最终窄复验另包含经典模式入口所在的 `expedition_page.py`，其文件 SHA-256 为 `6f1e170529480a8cbcb0db6c753801c1e1b109fc0fd2e4afe5c8bb897d93fc65`。

## 最终判断

`demo.api_action` 在 session 保存成功后才调用 `sync_profile`；档案同步失败记录可见 warning，不回滚已提交战斗。读取状态或恢复存档会重放同一持久 `run_id` 的累计快照。终局结果、round 最大值与物种集合均能抵抗重复或旧快照，不重复累计完成局数、胜数或挑战奖励。

远征的玩家战、bot 对战、PVE 与幽灵战均传入 `budget_v1`。伙伴选项只赋给玩家所属一侧；玩家作为幽灵来源时保留正确的侧别。经典模式保持原规则。开局伙伴按正常价格扣金并从原卡池取出，不扩充或锁定现有 84 种商店棋池。

备份预览和正式导入共用 runtime 与 codec 校验。校验和正确但语义不合法的远征配置在写入前被拒绝；坏档和未来版本不会被视为空档重建。导入保留之前的检查点，档案 HTTP 导入上限与存储上限均为 8 MiB。

## 问题关闭记录

| 发现 | 原复现与影响 | 修复与复验 | 状态 |
| --- | --- | --- | --- |
| P1：空伙伴 loadout 通过校验 | 将合法备份的 loadout 改成 `{"partner": null, "technique": null, "item": null}` 并重算校验和。原 inspect 返回成功；import 已替换磁盘并发布内存，随后 `status()` 抛 `StopIteration`，却回复“当前进度保持不变”。嵌套 dict partner 也有相同校验入口风险。 | `decode_extension` 要求 partner 为严格整数，并核对 `validate_loadout` 非空结果。再次对空伙伴、嵌套 dict 伙伴分别执行 inspect/import，均拒绝；原 session bytes、内存 loadout 和 profile bytes 均保持不变。 | 已关闭 |
| P2：schema 2 空扩展误走旧档迁移 | `expedition_state: null` 满足“字段存在”，却被当作 schema 1 无扩展，远征变经典且重新派生 run_id。 | `session_save.py:99` 拒绝 schema 2 缺扩展；`decode_extension` 仅缺字段时迁移，存在但非 dict 则拒绝。checksummed null 扩展备份预览和导入均失败且无副作用。 | 已关闭 |
| P2：PVE 已见物种漏记 | R5 画面显示 `83, 83, 83`，但 `opponent_comp=None`，原 `observe()` 的 seen 集合不含 83。 | `demo.py:343` 从当前 PVE 波次收录物种；独立复现与 `test_visible_pve_wave_is_recorded_in_seen_dex` 均通过。 | 已关闭 |
| P2：不战而胜未记随队获胜 | 玩家有阵容、对手空场时，战报胜利且 streak=1，但 `fielded=[1]`、`won=[]`。 | `demo.py:570` 与 `demo.py:576` 分别覆盖玩家在配对两侧，调用 `observe(won=...)`；新增空对手胜利测试通过。 | 已关闭 |
| 挑战奖励文案接线 | profile rewards 为对象数组，页面直接 join 会显示 `[object Object]`。 | `api_profile` 输出奖励 name 文本数组；主代理完成页面接线修复。页面视觉证据另见本目录 `browser-review.md`。 | 已关闭 |
| 外部独立审查：累计集合容量溢出 | 两个分别合法的同 run 快照 `seen=1..151` 与 `seen=[252]`，合并后会产生 152 条非法档案。 | `sim/metagame.py:147` 合并后再次 `_progress` 校验；超限拒绝且不截断历史、不修改输入。新增 overflow 测试同时验证满容量重叠重试仍有效。独立 reviewer 重跑 19 条档案测试通过并关闭问题，记录见本目录 `independent-combat-review.md`。 | 已关闭 |

## 独立故障注入实测

所有手工复现使用 `TemporaryDirectory` 替换 `demo.SAVE_ROOT`，并隔离 `demo.SESSIONS`，未访问用户真实存档。战斗渲染替身仍调用真实 `demo.Battle` 并转交 `battle_options`，只省略生成图片。

1. **档案写失败**：新建远征后，仅令 `ProfileStore.save` 抛 `StorageIOError("disk full")`，执行一次 `end_prep`。API 返回成功并带 profile warning；重新从 session Store 读取的 discoveries 与内存相等。档案 fielded 仍为 0。恢复正常后请求 `state`，warning 清空，fielded 变为 1。随后 `resume` 与导入同一对局备份到新 slot，统计完全不变。
2. **session 写失败**：`test_session_write_failure_never_publishes_profile_achievement` 验证提交失败不发布上场成就；既有保存测试同时覆盖写入失败回滚、commit uncertain 暂停操作及重新载入确认。
3. **恶意但校验和正确的备份**：分别注入空扩展、空伙伴、嵌套 dict 伙伴。修复后的三组结果均为 `preview rejected=True`、`import rejected=True`、`disk/memory/profile preserved=True`。
4. **重复恢复**：真实一次战斗后执行状态重试、恢复及重复导入，run 数量与完成、胜利、round 和图鉴计数均不重复增加。失败终局解锁装备与睡觉、重复终局导入不重复完成数也由应用层契约测试覆盖。
5. **路径覆盖**：契约测试拦截 Battle 与渲染入口，检查玩家、bot、PVE、幽灵来源的预算和 team options；全部通过。

## 测试证据

本 reviewer 在最终应用层文件上重新运行：

```text
python3 -m unittest discover -s tests -p test_expedition_contracts.py -q
Ran 12 tests in 2.275s — OK

python3 -m unittest discover -s tests -p test_session_save.py -q
Ran 12 tests in 1.166s — OK
```

容量修复后本 reviewer 运行 `test_meta_profile.py`：19 项全部通过；其中覆盖错误备份保护、未来版本保护、去重账本上限、union 溢出拒绝、物种 252/65535 往返以及最大合法备份容量。相关 `py_compile` 通过。早期复验的 `test_runtime_storage.py` 27 项全部通过，本轮未修改 runtime。

Reviewer 已读取本目录 `acceptance.json`：`system_acceptance --demo` 总状态为 `passed`，所选五项 `unit_tests`、`compile`、`diff_check`、`persistence_restart`、`demo` 全部 `passed`，returncode 均为 0。该主代理执行的验收记录含 246 项测试、两个种子共 25 场玩家战斗与 6283 帧，HTTP 状态分布为 `{200: 728}`。这是对已落盘验收证据的核对，不冒充 reviewer 重新执行了全量验收。最后一处结算摘要校验收紧发生在这次全量验收之后，补丁后 reviewer 重新运行的受影响测试为上述 24 项，并完成下述 6 组坏备份导入复验；未声称再次运行全量 246 项。浏览器交互和完整效果平衡分别以浏览器审查及平衡实验报告为准。

## 最终补充变更窄复验

以下复验在生产代码冻结后进行，本轮只更新本报告。

1. **物种编号与可用内容分别校验**：`SessionCodec` 接受的数值范围调整为 1..65535 后仍要求 `state.templates` 成员身份。独立构造单局 payload，将场上棋子改为 252、65535，均报“当前版本不支持的棋子”；改为 65536 则报 species 超范围。`sprite_png(252/65535/65536)` 在当前数据中均返回 `None`，未因扩展 ID 范围而索引缺失素材。
2. **PVE 和前向兼容物种进入图鉴列表**：在临时档案写入 seen `[83, 252, 65535]` 后调用 `api_profile`，实测 `build_templates` 仅调用一次，返回 87 条图鉴，即现有 84 种加三条额外已见。83 显示“大葱鸭”，252/65535 分别显示 `#252`、`#65535`，三者均 `seen=True`，未上场和未获胜标记仍为 False。商店 templates 未扩大。
3. **经典模式入口只消费一次**：审阅 `/demo?new=classic` 链接及初始化分支；把实际页面初始化 JavaScript 放入隔离 Node VM，以 history/location/newGame/resumeGame 替身执行入口和一次刷新，调用序列为 `["replace:/demo", "new", "resume"]`，确认先移除查询参数，再新开一局，刷新恢复而非再开局。真实浏览器“HP100、金币7、人口0、无主搭档”的记录已核对本目录 `browser-review.md`；本 reviewer 另调新建经典对局 API，`expedition` 为 None。
4. **恢复结算摘要保持严格结构**：`SessionCodec` 的 summary 仅允许 `winner/survivors/duration/round/pve/ghost`，两侧 survivors 必须为 0..12 的严格整数，duration 必须为非布尔有限数值且在 0..10000 内，round 受对局回合约束，pve/ghost 必须为布尔值。独立构造有效校验和的六种错误摘要：字符串 duration、布尔 duration、负 survivors、survivors=13、未知注入字段、数值 pve。每种 inspect/import 均拒绝，原 session 和 profile bytes 保持不变。现有合法战斗恢复及重复导入契约测试继续通过。

补充变更未产生新 blocker，结论仍为 `pass_with_risk`。

## 保留边界

- **schema 1 缺少持久局号**：迁移以原 payload 的规范 JSON 哈希派生 run_id，因此同一旧备份反复导入可去重。来自同一历史对局、但处于不同进度的两份 schema 1 备份会有不同哈希，不能可靠识别为同一局；旧格式没有足够身份信息。schema 2 后持续保存 run_id，后续恢复不受此限制。
- **容量明确有限**：最多 2048 个 run；每个 run 的 seen、fielded、won 各最多 151 项，ID 范围为 1..65535。超限返回错误并保留原记录，不丢弃去重账本。完整高编号最大样本为 5,775,541 bytes，低于 8 MiB。未来若单局可能观察超过 151 种，需要显式迁移容量方案；当前 84 种商店池不受影响。
- **审查范围**：本报告确认应用层事务与接线行为，不声称同费用预算已证明所有阵容胜率相等，也不代替 ESP32 设备存储验收。

结论可用于进入后续验收；若四个应用层文件中涉及上述行为的代码再次变化，应重跑相关契约测试并重新核对指纹。
