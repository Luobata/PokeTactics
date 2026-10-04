# Authored 动画放慢验收

2026-10-04，基于 `968f42f`。本轮只修改 `tools/mockups/**` 与 `reports/**`，未执行 git commit。工作区同时存在主线的模拟与 Demo 改动，本轮没有写入这些路径。

动画层已按确认目标放慢，保留原动作设计、关键姿势、幅度、物种差异和接缝修复。主线的默认倍速、攻击间隔调整独立生效；动画帧表不补偿事件稀疏化。

[新靶场：16 只 × 3 靶 × 6 状态 + 48 技能片段](evidence/range-slowed-2026-10-04/index.html) · [manifest 与逐段哈希](evidence/range-slowed-2026-10-04/manifest.json) · [逐段时长 CSV](evidence/range-slowed-2026-10-04/timing-segments.csv) · [时长汇总 JSON](evidence/range-slowed-2026-10-04/timing-summary.json)。HTML 需通过静态 HTTP 服务打开；PNG/GIF 可直接查看。

**前后时长**

每个状态统计 **48 段**（16 只 × dummy/melee/ranged）。strike 行包含 recover。时长为完整帧数 × 帧时长，包含最后一帧的显示时间；不是首末时间戳相减。

| 状态 | 原均值（s） | 新均值（s） | 实际倍率 | 确认目标 | 总帧数：旧 → 新 |
|---|---:|---:|---:|---|---:|
| walk | 0.425000 | **0.637500** | 1.5000× | ×1.5，约 0.63 s | 204 → 612 |
| windup | 0.312500 | **0.403125** | 1.2900× | ×1.3，约 0.40 s | 150 → 387 |
| strike + recover | 0.506250 | **0.656250** | 1.2963× | ×1.3，约 0.66 s | 243 → 630 |
| hit | 0.300000 | **0.400000** | 1.3333× | 0.40 s | 144 → 384 |
| death | 0.600000 | **0.750000** | 1.2500× | 0.75 s | 288 → 720 |
| idle | 0.850000 | **0.850000** | 1.0000× | 保持 | 408 → 408 |

idle 的 0.85 s 是既有靶场片段口径：每段至少展示 8 帧。原始 idle 循环帧表的物种均值是 0.65 s，本轮仍为 0.65 s，没有将原循环改成统一 0.85 s。技能蓄力从原来的 **0.2–0.4 s** 调整到 **0.4–0.5 s**，施法姿势按该蓄力区间映射到完整 windup；平 A 仍保留物种间时长差异。

**实现与取舍**

- 原 10 Hz 动作关键帧原样保留。除 idle 外，帧表插入整数中间姿势，按 **20 Hz / 50 ms** 采样；位移、缩放和倾角在相邻原关键姿势之间插值。非循环动作末帧保持，walk 尾帧向首帧衔接。四阶消散不插值透明度，仍使用原离散蒙版与二值 alpha。
- 全身帧表加帧时，翼、尾、腹部、岩体分节的局部轨道同步映射回原关键帧相位，避免局部动作因索引增加而加速。原关键姿势像素检查全部一致。
- windup、strike、recover 各自取最近的 50 ms 帧数。windup 均值相对精确 ×1.3 低 **3.125 ms**；strike/recover 合计均值低 **1.875 ms**。单物种仍保留节奏区别，例如平 A windup 为 0.25–0.50 s。选加帧而非单纯延长原 100 ms 帧停留，以维持过渡流畅；整数像素和末帧保持仍可能产生相同邻帧。
- 受击事件采样窗口同步延到 0.4 s；死亡单位可见窗口同步延到 0.75 s，完整显示下沉消散。补齐 0.4 s 抬手出手边界的浮点容差，防止弹体晚一帧出现；受击首帧也有专项断言。未建档单位继续使用原时序。
- 新靶场将每段 `frame_duration_ms` 写入 manifest，GIF 与查看器读取相同节奏。旧 manifest 未提供该字段时仍默认 100 ms。图集预载、解码后播放、失败保留画面及重试逻辑保留。
- 技能证据采用原管线已有的加厚 HP `skill` 训练夹具：主线攻击间隔变长后，普通夹具中部分弱体型会在首次施法前倒下。仍由真实 Battle 产生事件，不伪造施法或伤害。

**新旧同钟对照**

以下四组均左为 `968f42f`、右为本轮，同一源精灵、相同 50 ms 时间步；每组包含 walk、完整攻击链、idle 上的 hit 叠加、death 四行，2 s 循环。攻击完成后回待机，死亡完成后移除；walk 连续循环，因此能看到新旧周期差异。

| 物种 | 动态对照 | 0.35 s 同钟拼图 |
|---|---|---|
| 喷火龙 6 | [GIF](evidence/range-slowed-2026-10-04/6-timing-comparison.gif) | [PNG](evidence/range-slowed-2026-10-04/6-timing-comparison.png) |
| 卡比兽 143 | [GIF](evidence/range-slowed-2026-10-04/143-timing-comparison.gif) | [PNG](evidence/range-slowed-2026-10-04/143-timing-comparison.png) |
| 大岩蛇 95 | [GIF](evidence/range-slowed-2026-10-04/95-timing-comparison.gif) | [PNG](evidence/range-slowed-2026-10-04/95-timing-comparison.png) |
| 大比鸟 18 | [GIF](evidence/range-slowed-2026-10-04/18-timing-comparison.gif) | [PNG](evidence/range-slowed-2026-10-04/18-timing-comparison.png) |

另保留 16 组整盘六状态左右对照、逐物种全部帧拼图、动作与技能图集。对照基线源码及 SHA-256 存在新证据目录；归档模块的延迟导入也绑定归档 motion，避免旧技能意外引用新时长。

**验收读数**

| 检查 | 结果与证据 |
|---|---|
| 双次独立构造渲染 | **336/336 段、3,636 帧 SHA-256 一致**；[manifest](evidence/range-slowed-2026-10-04/manifest.json) |
| 落盘复查 | **336 GIF 时长正确，3,636 PNG 哈希一致、全帧不透明**；[artifact-audit](evidence/range-slowed-2026-10-04/artifact-audit.json) |
| FX 双 seed | **seed 7：0 failures；seed 11：0 failures**，包含原 R1 合同；未降低可见度/遮挡阈值；[visibility](evidence/range-slowed-2026-10-04/visibility/visibility.json) |
| 接缝与动作保真 | **1,015 动作帧，内部缺口 0、空 cel 0、越色 0**；原关键姿势含保持帧共 **601 次逐像素检查**通过，**198 个消散蒙版**保持；[retiming-contracts](evidence/range-slowed-2026-10-04/retiming-contracts.json) |
| 动作/技能合同 | 16 只各自唯一，120 对；倒放、冻结、死亡优先级通过；实心原语最大 8 px；[contracts](evidence/range-slowed-2026-10-04/contracts.json) |
| 硬约束 | **990 技能采样帧**，FX 覆盖精灵像素 **0**；动作越色及非二值 alpha 均 **0**；粒子峰值 **50/192**，饱和预算 **192**；[hard-contracts](evidence/range-slowed-2026-10-04/hard-contracts.json) |
| 未建档回落 | **28 组全部逐位一致**；[fallback](evidence/range-slowed-2026-10-04/fallback.json) |
| 查看器 | **336 段、7,272 播放 tick、3,636 次逆序 seek**；空白 **0**、PNG 像素不匹配 **0**、播放/seek 新网络请求 **0**；逐段计时器与 manifest 一致，慢加载/换段与 404/损坏/错误尺寸/超时重试通过；[viewer-equivalent](evidence/range-slowed-2026-10-04/viewer-equivalent.json) |
| 静态检查 | 修改的 Python AST、两个 JS 语法检查及 `git diff --check` 通过 |

**修改清单**

| 路径 | 内容 |
|---|---|
| `tools/mockups/motion.py` | 原关键帧留存、20 Hz 动作帧表、时长接口、局部相位同步、蓄力姿势映射、受击窗口 |
| `tools/mockups/render_battle_gif.py` | 死亡可见时长、受击事件窗口、authored 弹体出手浮点边界 |
| `tools/mockups/skill_vfx.py` | authored 技能蓄力维持 0.4–0.5 s |
| `tools/mockups/per_unit_evidence.py` | 50 ms 状态采样、manifest/GIF 时长、可选基线、归档导入隔离、加厚 HP 技能证据 |
| `tools/mockups/range_viewer.js` | 按片段帧时长设置播放计时器 |
| `tools/mockups/range_viewer_check.cjs` | 支持新证据目录、逐段计时器验收 |
| `tools/mockups/slowed_animation_check.py` | 逐段时长、关键姿势像素保真、所有中间帧接缝/消散、四组同钟 GIF、落盘时长/哈希验收 |
| `reports/evidence/range-slowed-2026-10-04/**` | 全新靶场、对照图、原始读数、日志、基线源码与验证证据 |
| `reports/vfx-slowed-codex-2026-10-04.md` | 本报告 |

**已知限制**

表内为动作采样时钟下的 1× 时长，不额外计入已有击杀慢镜窗口；整场回放的全局倍速和慢镜会改变实际墙钟显示时长。主线事件间隔变化只改变事件分布，不参与本轮帧表倍率。完整战斗仍可能由更新的攻击/技能事件抢占当前动作，孤立靶场展示完整单段。

调用方若仍只以 10 FPS 取帧，会跳过部分 20 Hz 中间帧，但放慢后的状态时长仍生效。新靶场支持 20 FPS，技能 FX 和既有整体 GIF 默认采样率保持原设置；本轮未修改 Demo。模拟 HP 仍按事件时刻结算，视觉延后不改变伤害机制。

查看器验证执行生成页的真实 JS、原生 Canvas 光栅化及真实 PNG 解码，但使用虚拟计时器和本地 IO；**不是浏览器 compositor、真实弱网或后台标签页调度的实测**。本轮目视检查了四组放大对照，未新增浏览器实测。

QualityGate 中央 MCP 未注册，runner 预检缺部分依赖，仓库 capsule 未就绪；受本轮路径所有权约束，未安装或修改外部环境。CLI 辅助检查的结构化结果另存 [qualitygate.json](evidence/range-slowed-2026-10-04/qualitygate.json)：`gate/raw_gate=pass`、`block_merge=false`、`execution_complete=true`、`incomplete_engines=[]`、0 findings，CLI 自报 `quality_confidence=full`，但没有适用规则和中央语义覆盖，不能视作完整质量证明。Mutation 未执行（默认暂停，CLI 返回 `not_applicable`）。交付依据为上述专项验证。

**复跑**

```sh
PYTHONDONTWRITEBYTECODE=1 python3 tools/mockups/per_unit_evidence.py --mode contracts --baseline 968f42f --out reports/evidence/range-slowed-2026-10-04
PYTHONDONTWRITEBYTECODE=1 python3 tools/mockups/per_unit_evidence.py --mode range --baseline 968f42f --out reports/evidence/range-slowed-2026-10-04
PYTHONDONTWRITEBYTECODE=1 python3 tools/mockups/per_unit_evidence.py --mode hard --baseline 968f42f --out reports/evidence/range-slowed-2026-10-04
PYTHONDONTWRITEBYTECODE=1 python3 tools/mockups/slowed_animation_check.py
PYTHONDONTWRITEBYTECODE=1 python3 tools/mockups/fx_visibility_check.py --output reports/evidence/range-slowed-2026-10-04/visibility
NODE_PATH=/Users/bytedance/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules node tools/mockups/range_viewer_check.cjs range-slowed-2026-10-04
```
