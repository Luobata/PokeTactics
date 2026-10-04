# 平A / 技能视觉分离与动画丰富化

2026-10-04，基于 R1 合流 commit `13aaaab`。任务 A–D 的项目验收全部通过。代码修改限定 `tools/mockups/**`，报告及证据位于 `reports/**`；未修改模拟、验收服务、文档或数据文件，未执行 git commit。工作区主线的模拟改动仅只读消费；版本指纹见 [source-fingerprints.json](evidence/vfx-separation-2026-10-04/source-fingerprints.json)。

**六项视觉语言规范**

| 项目 | 普攻 attack | 技能 cast |
|---|---|---|
| 蓄力与节奏 | 无技能蓄力；出手动作首帧 0.1s 反向准备，随后弹道发射 | 喷火龙 0.5s，其余 0.4s；随后释放，命中效果持续 0.6s |
| 姿态与底座 | 反向微移 1px，无蓄力环 | 前倾 1px，脚底属性环分阶段变亮；满能量待机保留呼吸金环 |
| 轨迹与形状 | 弹道 / 近战轨迹 ≤2px，移除普攻整身攻击残影与粗双斩弧 | 九原语按属性着色；三个 signature 保留大字、念力波、压顶恢复图形 |
| 命中体积 | 单个半透明外环；实心星形最大 19px（32/34px 精灵的 59.4% / 55.9%）；四粒短火花 | 双外环；签名可叠加原有轮廓；所有棋盘 FX 扣除实际精灵不透明像素 |
| 镜头 | 普攻不震屏、不切镜 | 命中 ±2px 两帧微震；generic 可沿用 0.2s 释放切镜，切镜同步微震；signature 保持棋盘演出 |
| 跳字 | 7px 点阵字高 | 8px 点阵字高，准确增加 1px；保留克制色和避让 |

单环采用 alpha=176 的描边，在保持原 600px 隔离可见度门槛的同时减轻视觉强度。面积通过轮廓表达，未扩大实心星形。原死亡慢镜属于击杀演出，保留 R1 播放时钟。

**模板和全单位动画**

- `double_strike`：两道平行斩线，第二道延迟 0.15s；边界检查覆盖 0.149s / 0.150s。
- `charge`：三道空心冲刺拖尾，连续三帧递减透明度，落点菱形。
- `bulwark`：六边形护盾，周身八条短亮线。
- `mend`：头顶十字微光，三粒上升光点。
- `volley_shot`：三发小弹按品字形展开。
- `heavy_blow`：粗单斩及重外环。
- `splash / blink_strike / slam_heal`：复用 R1 三套签名形状，颜色由单位属性传入。

只读调用主线 `skill_of` 获取中文名、arch、tier；缺失模块或缺失有效档案时，6/65/143 回退内置签名，其余回退 generic heavy_blow。主线仍是实际档案的真源。generic 使用统一原语，signature 三只保留原有专属演出。见 [九原语逐帧图](evidence/vfx-separation-2026-10-04/nine-primitives.png)。

全池 84 种单位逐一检查待机，均至少两种可见姿态；陆行系补齐 1px 压伸，悬浮系上下浮动修正为能通过棋盘边界约束的相位。普攻首帧反向微移 1px；每步尘点延后至插值落点，恰好两粒；受击原左右颤保留，首帧追加沿击退方向 1px。死亡尾段增加 0.2s 下沉淡出：样本 y=129→130，alpha 总和 160395→79883；0.6s 结束。

**平A / 技能可分性读数**

同一单位、同一 seed=7 的真实木桩 Battle，各取首个 attack/cast。统计各自命中窗口中可见特效面积最大的帧，保留真实位置、剔除其他行动，并使用生产渲染的精灵遮罩和棋盘裁切；不计全屏白闪、跳字、背景和镜头变化。证据同时保存真实完整帧及隔离 FX 图。面积阈值为 cast / attack ≥1.5。

| 单位 | 普攻 / 技能可见 FX 像素 | 面积倍数 | 普攻 / 技能蓄力 | 普攻 / 技能外环数 | 微震 | 字高 |
|---|---:|---:|---|---|---|---|
| 喷火龙 6 | 695 / 2262 | 3.255× | 0 / 0.5s | 1 / ≥2 | 0 / 2px | 7 / 8px |
| 胡地 65 | 695 / 2310 | 3.324× | 0 / 0.4s | 1 / 4 | 0 / 2px | 7 / 8px |
| 卡比兽 143 | 597 / 1913 | 3.204× | 0 / 0.4s | 1 / ≥2 | 0 / 2px | 7 / 8px |
| 隆隆岩 76，generic mend | 612 / 1457 | 2.381× | 0 / 0.4s | 1 / 2 | 0 / 2px | 7 / 8px |

这里的面积扣除了精灵遮罩，与原可见度脚本的“空背景隔离差分 ≥600px”是不同口径；卡比兽 597px 不代表原门槛失败。隆隆岩图鉴 ID 为 76，采用此 ID 生成通用技能实战样例。

详细事件、帧时刻、反馈读数和哈希：[separation.json](evidence/vfx-separation-2026-10-04/separation.json)。对照帧：[喷火龙](evidence/vfx-separation-2026-10-04/pair-6.png)、[胡地](evidence/vfx-separation-2026-10-04/pair-65.png)、[卡比兽](evidence/vfx-separation-2026-10-04/pair-143.png)、[隆隆岩](evidence/vfx-separation-2026-10-04/pair-76.png)。

**原可见度与确定性验收**

`fx_visibility_check.py` 未修改。原阈值保持 attack=600、land=1500、opening=2500、weather=1200、同排重叠≤4px、状态条连续遮挡≤2帧。

| 项目 | seed 7 | seed 11 |
|---|---:|---:|
| 失败数 | 0 | 0 |
| 普攻隔离最小差分 | 644px | 692px |
| 普攻逐帧最小差分 | 2216px | 1559px |
| 技能落点逐帧最小差分 | 2277px | 3230px |
| 开场逐帧最小差分 | 4314px | 6263px |
| 同排身体最大重叠 | 0px / 442 对 | 0px / 570 对 |
| 血条最长连续遮挡 | 0 帧 | 0 帧 |

原 land 隔离检查包含命中全盘轻白闪，读数为 57600px；因此额外用上面的无白闪 FX 面积检查证明技能形状确实更大。天气、状态、四原色、冻结静止、伤害分层、回卷与 R1 能量/时钟契约全部通过。实心星形契约从 75% 收紧至 60%。

- 靶场重出 6/65/143/76 × 3 场景 × 4 行动，共 **48 片段、701 帧**；逐片段两次独立构造真实 Battle 并渲染，48/48 SHA-256 完全一致。
- CLI `_clip` 与公开 `render_species_scene` 入口帧哈希一致；另验证 `frame(T)`、`playback_frame(clock.playback_time(T))` 及前进后回卷像素一致。
- 九原语 × 两种 tier 输入 × 10 相位，180 个模板帧检查通过；并不意味着新增九只 signature，实际仍只有三只。
- 实际整场渲染粒子计数峰值 **39/192**；超额预算请求压力检查 **192/192**，构造器也封顶 192。
- 六个改动 Python 文件 compile 通过；`git diff --check` 通过。

[靶场入口](evidence/range-separation-2026-10-04/index.html)（需通过静态 HTTP 服务打开）、[靶场清单与全部哈希](evidence/range-separation-2026-10-04/manifest.json)、[原可见度完整报告](evidence/fx-separation-2026-10-04/visibility.json)、[R1 契约](evidence/r1-contracts-2026-10-04.json)。

复现命令：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 tools/mockups/r1_contract_check.py
PYTHONDONTWRITEBYTECODE=1 python3 tools/mockups/vfx_separation_check.py
PYTHONDONTWRITEBYTECODE=1 python3 tools/mockups/fx_visibility_check.py --output reports/evidence/fx-separation-2026-10-04
PYTHONDONTWRITEBYTECODE=1 python3 tools/mockups/profile_range.py --species 6,65,143,76 --out reports/evidence/range-separation-2026-10-04
```

**修改清单**

| 文件 | 变更 |
|---|---|
| `tools/mockups/render_battle_gif.py` | 技能元数据接入、分层反馈、小跳字、动作丰富化、预算封顶、死亡格复用处理 |
| `tools/mockups/profile_vfx.py` | 胡地蓄力 0.4s；签名模板接受外部属性色 |
| `tools/mockups/skill_vfx.py` | 新增防御性技能适配及九原语模板 |
| `tools/mockups/profile_range.py` | 靶场说明与 skill / windup 元数据 |
| `tools/mockups/r1_contract_check.py` | 60% 实心约束及普攻先准备再发射检查 |
| `tools/mockups/vfx_separation_check.py` | 新增可分性、84 种待机、死亡淡出、落尘、模板覆盖及确定性检查 |

**已知限制**

1. 动画不改变模拟结算时刻。模拟 HP、能量、即时突进/传送仍在原事件时间更新；视觉蓄力、弹道到达和跳字有独立展示延迟。胡地的原瞬移姿态仍随模拟事件出现，后续念力释放遵循 0.4s 蓄力。
2. GIF 为 10 FPS，0.15s 双斩间隔在逐帧展示中落在下一个 0.1s 采样点；连续时间绘制函数边界已检查。
3. 死亡格被存活单位提前复用时，终止遗体演出，避免遮挡；未复用时完整展示新增淡出。
4. 九原语全部有模板夹具证据；真实靶场的通用角色仅展示当前主线给隆隆岩分配的 mend，未声称所有原语都已有真实战斗样本。
5. 确定性证明覆盖当前 Python/Pillow 环境的双入口、双构造与回卷；未执行跨操作系统/硬件像素一致性验证。
6. 辅助 QualityGate MCP 未注册，中央规则与语义审查不可用。一次本地 CLI 对当时快照返回 gate/raw_gate=pass、block_merge=false、execution_complete=true、0 findings，但 Python 语义覆盖不足且之后有修复，**不作为最终版本的完整门禁通过证明**；Mutation 未执行（CLI 报 not_applicable，未启用）。本次任务完成判据采用以上最终版本项目专用验收。诊断输出保存在 [qualitygate.log](evidence/vfx-separation-2026-10-04/qualitygate.log)，该次诊断归档已迁入 reports。
