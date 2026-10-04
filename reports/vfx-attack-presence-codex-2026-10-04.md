# 普攻存在感回调验收

2026-10-04，基于 `093db4e`。用户指定的六项自验收全部通过：恢复普攻体积与轻重量反馈，技能档保持不变。只修改 `tools/mockups/**` 和 `reports/**`，未执行 git commit。

[同一时刻的修改前后对照](evidence/vfx-attack-presence-2026-10-04/before-after.png) · [新靶场入口](evidence/range-attack-presence-2026-10-04/index.html) · [靶场清单及哈希](evidence/range-attack-presence-2026-10-04/manifest.json)。靶场 HTML 需经静态 HTTP 服务打开，也可直接查看各片段的 GIF、PNG 和 contact 图。前后对照使用 `093db4e` 渲染器和当前渲染器，在相同真实 Battle、相同时间绘制。

**标定前后：原生 240×320 像素口径**

| 普攻项 | 修改前 | 修改后 |
|---|---|---|
| 实心星形纪律 | 精灵宽度 ≤60% | 精灵宽度 ≤75%，包含端点取整 |
| 32px 精灵，轻/中/重峰值直径 | 19 / 19 / 19px | 19 / 21 / 23px |
| 34px 精灵，轻/中/重峰值直径 | 19 / 19 / 19px | 21 / 23 / 25px |
| 最大直径 / 精灵宽度 | 59.38% / 55.88% | 71.88% / 73.53% |
| 远程弹头 | 属性色 2px，纸色单点 | 属性色 3px，居中 1px 纸色内衬；长度仍为 5px |
| 近战命中连接线 | 属性色 2px + 纸色 1px | 属性色 3px + 纸色 1px |
| 外环 | 单属性色，alpha 176 | 单属性色，alpha 208 |
| 外环尺寸 | 半径 27 / 30 / 33px，线宽 4px | 不变，含端点直径 55 / 61 / 67px |
| 火花 | 4 粒 | 6 粒，增加 2 粒；仍为 3px 长度参数、2px 线宽 |
| 星形纸色内核 | 外半径的 0.58 倍 | 比例不变，随外星形回调 |
| 跳字 | 标准字高 7px | 标准字高 7px，不加大 |
| 命中窗口 / 震屏 | 0.3s / 0px | 不变 |

三档伤害分界仍为目标最大 HP 的 `<6%`、`6–15%`、`≥15%`。旧上限实际把三档峰值压平，本次为每档预留 1px 半径档差。32px 精灵的轻档保持 19px；中重档及 34px 精灵三档恢复体积。75% 是上限，不要求每档顶满。32px 目标的整数上限为 24px，对称整数半径取 23px；34px 目标上限为 25px，实测 25px。身侧原有 2px 动作弧保持不变。

原始尺寸证据：[修改前契约](evidence/vfx-attack-presence-2026-10-04/before-contracts.json)、[修改后契约](evidence/vfx-attack-presence-2026-10-04/contracts.json)。检查记录实际 polygon 坐标，覆盖轻中重、两种变体、三个命中相位、32/34px 精灵。

**分离度：面积 ≥1.7×，且仪式感判据全部为真**

沿用同一单位、seed=7 的真实木桩 Battle，各取首个普攻/技能；分别在 0.3s / 0.6s 命中窗口取最大可见 FX 帧。保留真实坐标，剔除其他行动，扣除精灵遮罩并裁切棋盘；不计跳字、白闪和镜头。面积为非透明像素数，不以 alpha 强度加权。契约脚本原硬阈值实际为 1.5×，本次更新为 1.7×；历史实测区间 2.381–3.324× 不是旧脚本阈值。

| 单位 | 修改前普攻 / 技能面积 | 修改后普攻 / 技能面积 | 新面积比 | ≥1.7× |
|---|---:|---:|---:|---|
| 喷火龙 6 | 695 / 2262px | 725 / 2262px | 3.120× | 真 |
| 胡地 65 | 695 / 2310px | 723 / 2310px | 3.195× | 真 |
| 卡比兽 143 | 597 / 1913px | 633 / 1913px | 3.022× | 真 |
| 隆隆岩 76，generic mend | 612 / 1457px | 642 / 1457px | 2.269× | 真 |

| 仪式感判据 | 6 | 65 | 143 | 76 |
|---|---|---|---|---|
| 普攻无技能蓄力 | 真 | 真 | 真 | 真 |
| 技能蓄力 0.4–0.5s | 真，0.5s | 真，0.4s | 真，0.4s | 真，0.4s |
| 蓄力底座接收连续推进的相位 | 真 | 真 | 真 | 真 |
| 普攻单圈 / 技能至少双圈 | 真，1 / 2 | 真，1 / 4 | 真，1 / 2 | 真，1 / 2 |
| 普攻不震 / 技能 2px 微震 | 真 | 真 | 真 | 真 |
| 普攻标准 7px / 技能大字 8px | 真 | 真 | 真 | 真 |
| 80 能量呼吸金环预告 | 真 | 真 | 真 | 真 |
| 全部判据成立 | 真 | 真 | 真 | 真 |

能量预告独立夹具覆盖 79→80 阈值及完整六帧周期；79 不出环，80 每帧出环，alpha 实测 `255,255,208,160,160,208`。不能因连续两帧处于同一亮度平台而误判不呼吸。详细表、事件时刻、帧哈希见 [separation.json](evidence/vfx-attack-presence-2026-10-04/separation.json)。

技能的三个 signature 与 generic 模板、0.4–0.5s 蓄力、双圈、微震、跳字及能量逻辑均未修改。四单位共 **41 帧蓄力/释放隔离 FX 哈希与修改前完全相同**；`profile_vfx.py`、`skill_vfx.py` 与 `093db4e` 逐字节一致。见 [skill-unchanged.json](evidence/vfx-attack-presence-2026-10-04/skill-unchanged.json)。

**原可见度、遮挡、预算与确定性**

`fx_visibility_check.py` 与基线逐字节一致；阈值仍为 attack=600、land=1500、opening=2500、weather=1200，同排身体重叠≤4px，状态条连续遮挡≤2帧。

| 项目 | seed 7 | seed 11 |
|---|---:|---:|
| 失败数 | 0 | 0 |
| 普攻隔离最小差分，前→后 | 644→712px | 692→788px |
| 普攻逐帧最小差分 | 2269px | 1594px |
| 技能落点逐帧最小差分 | 2277px | 3230px |
| 开场逐帧最小差分 | 4322px | 6263px |
| 同排身体最大重叠 | 0px / 442 对 | 0px / 570 对 |
| 状态条最长连续遮挡 | 0 帧 | 0 帧 |

- 四单位 × 普攻 3 相位与技能 6 相位，共 **36 帧**逐精灵不透明像素比对，棋盘 FX 遮挡 **0px**。
- 实际压力回放粒子峰值 **53/192**；预算压力测试封顶 **192/192**。普攻隔离命中实测消耗 6 粒。
- 靶场 `6,65,143,76` × 木桩/近战/远程 × attack/cast/move/hit，共 **48 片段、701 帧**。每片段重新构造两次真实 Battle，CLI 与公开 `render_species_scene` 入口 **48/48 SHA-256 一致**。
- 帧入口、播放时钟入口和前进后回卷像素一致；84 种待机、九原语 × 两种 tier × 10 相位的原有检查全部通过。
- 修改的四个 Python 文件及相关三个渲染/检查文件通过内存 compile；`git diff --check` 通过。

证据：[双 seed 完整可见度](evidence/fx-attack-presence-2026-10-04/visibility.json)、[48 个片段及哈希](evidence/range-attack-presence-2026-10-04/manifest.json)、[源码指纹](evidence/vfx-attack-presence-2026-10-04/source-fingerprints.json)。

复现项目验收：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 tools/mockups/r1_contract_check.py --output reports/evidence/vfx-attack-presence-2026-10-04/contracts.json
PYTHONDONTWRITEBYTECODE=1 python3 tools/mockups/vfx_separation_check.py --output reports/evidence/vfx-attack-presence-2026-10-04
PYTHONDONTWRITEBYTECODE=1 python3 tools/mockups/fx_visibility_check.py --output reports/evidence/fx-attack-presence-2026-10-04
PYTHONDONTWRITEBYTECODE=1 python3 tools/mockups/profile_range.py --species 6,65,143,76 --out reports/evidence/range-attack-presence-2026-10-04
```

**修改清单**

| 文件或目录 | 内容 |
|---|---|
| `tools/mockups/render_battle_gif.py` | 75% 星形上限及三档尺寸、3px 弹道/连接线、单环 alpha 208、六粒火花 |
| `tools/mockups/r1_contract_check.py` | 75% 含端点尺寸、三档严格递增、3/1px 线宽、单环/六粒火花、四单位普攻及技能遮挡检查；支持证据输出路径 |
| `tools/mockups/vfx_separation_check.py` | ≥1.7× 与全部仪式感判据联合验收，能量预告周期检查，JSON 判据表；支持证据输出路径 |
| `tools/mockups/profile_range.py` | 靶场说明更新为清晰弹道、单环星形、标准跳字 |
| `reports/evidence/{vfx,fx,range}-attack-presence-2026-10-04/` | 契约、双 seed、前后对照、靶场、哈希与辅助检查证据 |
| 本报告 | 前后标定、验收读数与限制 |

**已知限制**

1. 精灵不透明像素仍优先于 FX；星形被身体遮罩扣除后，实际露出面积小于原始几何尺寸。不能用几何直径代替最终画面可见面积。当前分离检查取四单位木桩样本，未声称全物种/全伤害组合的面积比都已验证。
2. 面积比与原可见度的隔离差分口径不同。技能原 land 隔离差分包含白闪；本报告分离面积已排除白闪。增强环 alpha 提升亮度，但不会直接增加非透明面积读数。
3. 模拟 HP/能量结算时刻与视觉蓄力、弹道、跳字延迟保持原行为。满能量可能在模拟同一 tick 被消费，呼吸金环的阈值/周期通过独立夹具验证，不保证每次真实施法前都有完整六帧预告。
4. GIF 为 10 FPS；双渲染确定性覆盖当前 Python/Pillow 环境，未验证跨系统像素一致性。generic 实战样本为 76 的 mend；九原语的更广覆盖属于模板夹具。
5. QualityGate 仅作辅助：最终本地 CLI 返回 `gate/raw_gate=pass`、`block_merge=false`、`execution_complete/blocking_execution_complete=true`、0 findings、`incomplete_engines=[]`，其自身报告 `quality_confidence=full`、修复轮次 0。但 MCP 中央规则/语义评审不可用，且本地 runner 依赖检查不完整；因此不将该结果称为完整语义验收。Mutation 按默认暂停未执行（CLI 字段为 `not_applicable`，本次未启用）。没有 actionable block，也未执行语义修复。本任务的完成依据是上述全部通过的项目专项验收。见 [QualityGate JSON](evidence/vfx-attack-presence-2026-10-04/qualitygate.json) 与 [诊断日志](evidence/vfx-attack-presence-2026-10-04/qualitygate.log)。
