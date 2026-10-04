# 靶场帧间空白定位与修复

2026-10-04，基于 `c94b225`，未执行 git commit。最终改动限定 `tools/mockups/**` 与 `reports/**`。

**根因是局部切片拼接空缝。** 原 `motion.transform` 逐块清除源矩形，再平移粘贴；平移留下的内部条带没有补齐，且后续切片的清除/透明像素会擦掉邻接内容。卡比兽腹部、喷火龙翼根、大岩蛇分节等可直接复现。这种缺陷不需要出现整张空白帧，因此上一轮“单段 30 tick 非空”不能排除它。

[16 只修复前后放大对照](evidence/blank-frames-2026-10-04/rig-before-after.png)（左：`c94b225`；中：修复；右：恢复的 alpha 像素） · [更新后的 336 段靶场](evidence/per-unit-2026-10-04/index.html) · [历史 range-refined 靶场](evidence/range-refined-2026-10-04/index.html)。页面通过已有静态 HTTP 服务访问并刷新。

**全量扫描与根因分层**

两个目标页共 384 段、2,576 帧，逐帧检查：

- 棋盘相对纯地砖/分界线的非背景像素、帧间变化像素、整帧不透明像素。
- 每个可见单位的精灵 alpha 像素、进入画布后的像素数、主角内容量、死亡/消散状态。
- 全部源图与对应渲染器逐位一致。per-unit 使用当前/`c94b225` 动作代码；range-refined 使用归档 `49a0d46` 渲染器，避免用新动作解释旧帧。
- 小于本段中位数 45% 或相邻内容量变化超过中位数 35% 标为候选；不直接把候选判为空白。另做关闭 FX、闪屏、跳字、地痕和震屏的对照，辨别技能相位/棋盘平移带来的大面积变化。

| 分层 | 修复前 | 修复后 / 处置 |
|---|---:|---:|
| 整张透明 / 棋盘全空 | 0 / 0 | 0 / 0 |
| 成帧精灵接缝缺失候选 | 1,106 帧，326 段 | 0；修复内部连接条带与合成顺序 |
| 独立连续实体图回归的内部空洞 | 6,211 像素 / 447 动作样本 | 0 像素 / 447 样本 |
| 可见单位完全消失 / 出画裁切 | 0 / 0 | 0 / 0 |
| 设计意图异常采样（互斥分类） | 243 | 477，全部保留 |
| 未解释的异常候选 | 0 | 0 |
| 查看器风险 | 加载失败被当成成功；未显式等待解码；加载中反复 seek 可重复发起整段加载；无限缓存；无超时/重试 | 已修；正常网络下未把这些风险宣称为已复现的整张闪白根因 |

初扫的 **1,126** 是缩放/旋转/消散前的局部 rig 缺失候选；最终 **1,106** 是经过这些步骤后仍存在缺失 alpha 的成帧样本数。不能把两种口径混用，也不能把每个恢复像素都视为最终屏幕上可见的独立故障。

修复后 477 个设计意图采样为：技能/震屏相位变化 **238**、有序消散 **192**、死亡姿态 **34**、死亡后移除 **9**、从有意消散恢复 **4**。此前同时含接缝和正常特效变化的帧优先归入渲染 bug，修复后正常变化仍被阈值捕获，所以设计意图分类数量增加。所有 79 个 authored 消散蒙版与原有四阶规则逐位一致；未删除死亡或耿鬼的透明呼吸。

**逐段读数**

| 页面 | 段 / 帧 | 棋盘内容最小值 | 可见主角精灵最小值 | 可见单位采样 | 全空 / 出画 |
|---|---:|---:|---:|---:|---:|
| per-unit | 336 / 1,875（288 状态 + 48 技能） | 3,499 px | 55 px（死亡消散） | 8,747 | 0 / 0 |
| range-refined | 48 / 701 | 3,660 px | 521 px | 3,242 | 0 / 0 |

死亡完成后主角为 0 像素属于事件指定移除，不纳入“可见主角最小值”。历史渲染器的精灵计数采自 placement 的 alpha；其额外闪光/淡出后外观由归档 PNG、非背景量与逐位重渲染校验补充验证。

每一段的 **min / 中位数 / 异常帧索引及理由** 均已落盘，帧索引从 0 开始：

- [修复前逐段 CSV](evidence/blank-frames-2026-10-04/before-segments.csv)、[修复后逐段 CSV](evidence/blank-frames-2026-10-04/after-segments.csv)。
- [修复前逐帧 JSON](evidence/blank-frames-2026-10-04/before-scan.json)、[修复后逐帧 JSON](evidence/blank-frames-2026-10-04/after-scan.json)：包含全部单位、消散状态、入画像素与去除特效后的对照读数。
- [447 动作接缝回归](evidence/blank-frames-2026-10-04/rig-regression.json)。连续实体图是独立测试输入，旧算法确实失败，新算法通过；不是只把新算法输出与自身比较。

**修复清单**

| 路径 | 修改 |
|---|---|
| `tools/mockups/motion.py` | 抽出 `rig_cel`；先统一清除源切片，再 alpha 合成全部切片；仅向暴露的内部连接处延展原边缘行/列，轮廓外缘仍可移动。保留原色、整数像素、二值 alpha、帧表、位移与消散规则。 |
| `tools/mockups/range_viewer.js` | 新共享查看器：每段解码后写入离屏 Canvas 图集，播放/seek 仅从已驻留图集裁切；切段完成前保留已显示画面；选择代次与 AbortController 排除旧任务回写；加载期间 seek 记住目标帧。 |
| `tools/mockups/profile_range.py` | 模板内嵌共享 JS，新增重试按钮；后续生成自动携带相同逻辑。 |
| `tools/mockups/per_unit_evidence.py` | 生成时同步紧凑 motion-preview，避免继续展示旧接缝图。 |
| `tools/mockups/blank_frame_audit.py`、`blank_frame_check.py` | 全帧内容/单位 alpha 扫描、历史重放、特效对照、独立接缝测试与可视对照。 |
| `tools/mockups/range_viewer_check.cjs` | 直接执行生成页脚本，使用真实 PNG 解码与原生 Canvas 的可复跑自动化。 |
| `reports/evidence/per-unit-2026-10-04/**` | 重新生成全部 336 段 PNG/GIF、contact sheets、动作图集、预览、manifest 哈希及合同结果。 |
| 五个证据页 `index.html` | per-unit、range-refined、range、range-attack-presence、range-separation 的脚本与重试控件同步。历史 range-refined PNG 保留原版本，其扫描未发现 authored 切片问题。 |

没有生成新的磁盘雪碧图：内存图集同样使播放期间只裁切一张已解码的图，不再依赖每 tick 的 PNG 解码。有效加载并发上限 **4**，每帧网络+解码 deadline **12 秒**、最多 **2 次尝试**；失败不进入可播放缓存，保留画面并显示重试。可复用图集缓存按 LRU 限为 **32 MiB**（不等同于整个浏览器进程内存上限）。manifest 不使用缓存，PNG 请求附带片段内容哈希，避免更新后继续使用旧版图片。

**查看器自动化读数与边界**

[逐段播放/seek 与故障注入结果](evidence/blank-frames-2026-10-04/viewer-equivalent.json) · [执行日志](evidence/blank-frames-2026-10-04/viewer-equivalent.log) · [五页模板同步](evidence/blank-frames-2026-10-04/template-sync.json)。

| 检查 | 结果 |
|---|---:|
| 两个目标页逐段切换 | 384 段全部通过 |
| 每段两次完整循环（含尾→首） | **5,152 tick，空白 0，PNG 像素不匹配 0** |
| 每段逆序 seek 到每一帧 | **2,576 次，通过** |
| 上一帧/下一帧越界回绕 | 384 段通过 |
| 播放/seek 中新增网络请求 | 0 |
| 慢加载→拖动→快速换段→旧任务完成 | 两页通过，各保留画面 30 tick |
| 最长技能片段加载时 seek 到末帧 | per-unit 10 帧、range-refined 18 帧，均通过 |
| 404 / 损坏 PNG / 错误尺寸 / deadline→重试 | 两页各四类通过；每类保留画面 30 tick |
| 有效并发 / 缓存上限 | ≤4 / ≤32 MiB |

这是**等价状态机与原生光栅化验证，不是浏览器实测**。运行环境为 Node v25.8.1、`@napi-rs/canvas` 0.1.100、`pngjs` 7.0.0。输入是生成页实际脚本，输出 Canvas 的完整 RGBA 与独立 PNG 解码逐位比较；计时器由测试推进，12 秒 deadline 也由测试触发，因此不证明浏览器调度、GPU 合成或实际弱网时长。

本轮 headless 浏览器启动被沙箱限制，绑定本地端口也被拒绝；随后浏览器自动审批明确拒绝访问 `http://127.0.0.1:8799`，理由是用户拒绝该地址访问。未通过替代浏览器、CDP 或间接方式绕过。浏览器 compositor、真实网络缓存以及后台标签页节流仍为未执行项。

**硬约束与其余验证**

- [逐只合同](evidence/per-unit-2026-10-04/contracts.json)：16 只动作/技能几何仍各自唯一，120 对检查；倒放、冻结、死亡优先级通过；authored 实心原语最大 **8 px**，低于既有 75% 约束。
- [硬合同](evidence/per-unit-2026-10-04/hard-contracts.json)：876 个技能帧的 FX 覆盖精灵像素 **0**；447 动作帧越色 **0**、非二值 alpha **0**；粒子采样峰值 **60/192**，饱和预算 **192**。
- [未建档回落](evidence/per-unit-2026-10-04/fallback.json)：全部逐位一致。336 段生成均执行双次确定性哈希校验。
- [原可见度检查](evidence/blank-frames-2026-10-04/visibility/visibility.json)：seed 7、11 均 **0 failures**；原 attack / land / opening / weather 阈值和遮挡阈值未修改。
- Python/JS 语法检查、五页模板同步、`git diff --check` 通过。最终未修改 sim、data 或验收服务。
- [QualityGate 辅助结果](evidence/blank-frames-2026-10-04/qualitygate.txt)：中间检查返回 `gate/raw_gate=pass`、`block_merge=false`、`execution_complete=true`、0 findings、`incomplete_engines=[]`；没有命中适用规则，中央 MCP/语义检查不可用，不能视为完整质量证明，也不覆盖其后的辅助脚本修改。Mutation 未执行（默认暂停，CLI 此范围返回 `not_applicable`）。CLI 自动生成的本轮本地记录已迁入报告范围，原有记录未删除；主要交付依据为上述专项测试。

**复跑**

在仓库根目录执行（前两条 before/after 扫描可独立复跑；before 从 `c94b225` 的 Git 归档读取原 PNG）：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 tools/mockups/blank_frame_audit.py --label before
PYTHONDONTWRITEBYTECODE=1 python3 tools/mockups/per_unit_evidence.py --mode all
PYTHONDONTWRITEBYTECODE=1 python3 tools/mockups/blank_frame_audit.py --label after
PYTHONDONTWRITEBYTECODE=1 python3 tools/mockups/blank_frame_check.py
NODE_PATH=/Users/bytedance/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules node tools/mockups/range_viewer_check.cjs
PYTHONDONTWRITEBYTECODE=1 python3 tools/mockups/fx_visibility_check.py --output reports/evidence/blank-frames-2026-10-04/visibility
```

原图/帧表仍可产生有意的点阵透明、死亡消失与片段循环时的动作跳转。这些均保留；本次修掉的是切片导致的额外空缝，并加强查看器在加载失败和切换时保留完整画面的能力。
