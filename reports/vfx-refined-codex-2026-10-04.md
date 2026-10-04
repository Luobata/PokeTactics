# 像素攻击特效精修验收

2026-10-04，基于 `d7139f9`。保留 GB/GSC 四色像素语汇，完成轨迹、形状细节与命中反馈三条主线。专项检查全部通过；只修改 `tools/mockups/**`、`reports/**`，未执行 git commit。

[靶场入口](evidence/range-refined-2026-10-04/index.html) · [48 片段清单与哈希](evidence/range-refined-2026-10-04/manifest.json) · [弹体细节放大图](evidence/range-refined-2026-10-04/projectile-details.png)。HTML 使用同目录静态 HTTP 服务打开；GIF、PNG 可直接查看。单位为喷火龙 6、胡地 65、卡比兽 143、generic 隆隆岩 76（mend）。

**前后对照**

以下三组均左为 `d7139f9`，右为最终实现，真实 Battle、seed=7、同一逻辑时刻，原生 240×320 后做 2× 最近邻拼图。基线由 `git show d7139f9` 加载原始渲染模块，不是手工模拟旧画面；模块指纹见 [baseline-source.json](evidence/range-refined-2026-10-04/baseline-source.json)。

| 组别 | 时刻 | 左右拼图 |
|---|---:|---|
| 普攻命中首帧 | 2.100s | [普攻命中](evidence/range-refined-2026-10-04/compare-basic-hit.png) |
| 弹道中段 | 1.900s | [弹道中段](evidence/range-refined-2026-10-04/compare-projectile-mid.png) |
| 技能命中首帧 | 6.900s | [技能命中](evidence/range-refined-2026-10-04/compare-skill-hit.png) |

对照帧保留并发事件；技能对照中另一木桩同时受普攻。下文的面积分离检查另行隔离行动、扣除精灵遮罩，避免并发事件影响读数。

**轨迹动画实现清单**

- 普攻、volley 技能及切镜的 travel/arc 弹道共用语义弹体与历史采样。每个弹体最多 4 段尾迹，宽度依次 `3 / 2 / 1 / 1px`，2×2 Bayer 覆盖依次 `100 / 75 / 50 / 25%`；不用新增 RGB 或半透明混色制造中间层。
- 历史位置按固定 25ms 子帧重采样，不按空间距离倒推。专项夹具中速度减半，尾迹长度从 30px 减至 15px。每个弹体连同尾迹最多记 5 个预算单位。
- 10 FPS 的每张展示帧使用帧内 75ms 采样点，并限制弹头至少早于到达 12.5ms。最短 100ms 飞行也能显示 3 段历史尾迹；正常飞行显示 4 段。准备帧、命中时刻、伤害结算和死亡取消逻辑不变。
- 弧线用 `1-(1-p)^1.45` 调整沿途速度，再计算抛物线高度，实现快出慢落。念力细摆动也由历史采样自己的进度决定，回卷不会把当前摆动错误复用到旧位置。
- 火弹为圆头、双帧火苗，火苗左右摆动 2px；念力弹空心/实心交替，空心区域不会被自身尾迹填满；水弹为圆头尖尾的泪滴。火、水弹和其他细长弹体沿速度方向绘制。
- 普攻和有伤害的技能在命中前恰好 1 帧显示落点四角 1px 标记，仍遵守最终精灵保护遮罩。

**特效细节实现清单**

- 普攻命中星形使用细外色环、确定性锯齿中层、2×2 纸白内核与十字亮边。交替半径和整数哈希产生不对称齿深；同一事件不依赖全局随机数。技能共用同一分层原语。
- 星形落在来袭侧的轮廓边缘，使细节能露出；精灵不透明像素继续从 FX 层扣除，未用覆盖身体的方式放大效果。
- 火花为短线与亮端点；碎屑为随运动角度四向选择的 1×2 / 2×1 像素；光点为 3×3 十字星。替换普通弹道、死亡、mend、压顶碎屑、燃烧和切镜装饰中的裸方块。
- 受击首帧保留亮内区、边缘 50% 棋盘羽化，第二帧仅保留边缘半亮，之后恢复。半亮由原色/纸白交错表达，不添加灰阶。闪光属于精灵自身受击表现，不计入外部 FX 遮挡。
- 蓄力环删除原有 RGB 插值，中间层次由离散原色与逐步延伸的纸白弧表达；尾迹和速度线渐隐使用 2×2 dithering。已有天气、状态、开场闪光等系统的历史配色机制没有在此轮整体重写。

**攻击效果实现清单**

- 命中首帧沿来袭主轴压缩 1px、垂直主轴增长 1px：水平来袭为横压竖涨，竖向来袭交换两轴。近战取攻守方向，远程取弹道到达切线；技能也接入。作用于不透明内容，保留固定 32/34px 画布宽度和原棋盘边界，冻结/死亡单位沿用原规则。
- 普攻外环为外 1px、内 2px 描边，半径相差 2px，间隔 1px；首帧半径为 29/27px。6 根放射速度线长 3–4px，逐相位外移并用棋盘覆盖渐隐，亮端点保留。
- 技能保留两组间隔 8px 的外环组，每组都有细/粗双描边；signature 叠加原有大字、念力环或压顶波。技能共 6 根新增速度线纳入预算，没有放宽 192 上限。
- 数字轨迹为上抛 3px、回落 1px后消散，八帧采样为 `0,2,3,3,3,3,2,2px`。普通数字 1px 描边，重击与技能再加 1px；字形仍为普攻 7px、技能 8px。
- 震屏仍只给技能，首两帧 `+2/-2px`。包括高伤害档在内的普攻均不新增震屏。
- 同一帧的姿态、闪光和 FX 共用一次受击事件筛选，绘制结束即清空，避免长事件流重复扫描。缓存不跨帧、不跨实例，也不影响回卷。

**硬约束读数**

[完整双 seed 可见度结果](evidence/range-refined-2026-10-04/visibility/visibility.json)。检查阈值仍为 attack=600、land=1500、opening=2500、weather=1200；身体同排重叠 ≤4px、状态条连续遮挡 ≤2 帧。`fx_visibility_check.py` 唯一改动为数字采集 lambda 接受新增关键字参数，判定及阈值未改。

| 项目，原生像素口径 | seed 7 | seed 11 |
|---|---:|---:|
| 失败数 | **0** | **0** |
| 普攻隔离最小差分，阈值 600 | 649px | 668px |
| 普攻逐帧最小差分 | 1931px | 1299px |
| 技能落点逐帧最小差分，阈值 1500 | 1716px | 2462px |
| 开场逐帧最小差分，阈值 2500 | 4338px | 6293px |
| 四种天气视觉隔离最小差分，阈值 1200 | 28623px | 28138px |
| 同排身体最大重叠 | 0px / 442 对 | 0px / 570 对 |
| 状态条最长连续遮挡 | 0 帧 | 0 帧 |

| 其他硬约束 | 最终读数 |
|---|---|
| 实心命中星形 ≤精灵宽度 75% | 32px 精灵：最大 23px，71.88%；34px 精灵：最大 25px，73.53% |
| 轻 / 中 / 重尺寸递增 | 32px：19/21/23px；34px：21/23/25px |
| 外部棋盘 FX 覆盖精灵不透明像素 | **0px**，四单位 × 普攻 3 相位、技能 6 相位，共 36 帧 |
| 实际压力回放粒子峰值 | **57/192** |
| 预算饱和夹具 | **192/192**，含弹体、尾迹、放射线 |
| 新弹体形状调色板/alpha | 只用既有属性色与纸白；alpha 只为 0/255 |
| 原精灵色板回归 | 84 物种、588 张压缩相位精灵，越界颜色 0px、部分 alpha 0px |
| 靶场确定性 | **48/48** 片段重新构造真实 Battle 后 SHA-256 相同；共 **701 帧** |
| 播放、直接帧和回卷一致性 | 四单位全部通过 |

尺寸取实际实心 polygon 的含端点跨度；外围空心环不作为实心直径。技能内星形最高 21px、弹体低于该尺寸。详细证据：[contracts.json](evidence/range-refined-2026-10-04/contracts.json)、[refinement.json](evidence/range-refined-2026-10-04/refinement.json)。

**两档语言分离**

真实木桩场景取同单位首个普攻与技能，分别在 0.3s / 0.6s 命中窗口中取最大可见 FX 面积。面积扣除身体并裁切棋盘，排除数字、白闪和镜头，按非透明像素计数，不用透明度加权。它与上表 RGB 差分不是同一口径，不能把 557px 的普攻 FX 面积与 600px 差分阈值直接比较。

| 单位 | 普攻 / 技能可见面积 | 技能/普攻 | ≥1.7× | 仪式感全真 |
|---|---:|---:|---|---|
| 6 喷火龙 | 629 / 2186px | 3.475× | 是 | 是 |
| 65 胡地 | 621 / 2409px | 3.879× | 是 | 是 |
| 143 卡比兽 | 559 / 1922px | 3.438× | 是 | 是 |
| 76 隆隆岩，generic mend | 557 / 1512px | 2.715× | 是 | 是 |

仪式感七项逐一成立：普攻无技能蓄力；技能蓄力 0.4–0.5s；底座接收连续相位；普攻紧邻双描边与技能分隔多环可区分；普攻不震/技能 2px 震屏；数字 7/8px 两档；80 能量呼吸预告。79 能量不出环，80 能量六帧 alpha 为 `255,255,208,160,160,208`。

旧“普攻单圈”判据与本次双圈需求冲突，已改为实际半径结构检查：普攻 `[27,29]`、技能至少四条外描边且半径跨度 ≥8px。没有降低面积阈值，也没有删掉蓄力、震屏、数字和能量判据。九原语 × 两 tier × 十相位、84 物种待机回归也全部通过。见 [separation.json](evidence/range-refined-2026-10-04/separation.json)。

**单帧性能**

最终代码固定后，在其他验收任务结束的情况下顺序执行基线与精修版。每版四单位各 25 帧，seed=7、melee 场景，逻辑时刻 0.5–7.7s、步长 0.3s，包含普攻、技能与移动。先预热同批帧和素材，然后重置游标，计时仅包括 `frame(show_cutins=False)`；Battle 构造、PNG 编码、文件写入和哈希不计入。

| 版本 | 帧数 | 均值 |
|---|---:|---:|
| d7139f9 | 100 | **4.024145ms** |
| 最终精修版 | 100 | **4.087809ms** |
| 增量 | — | **+0.063665ms，+1.58%** |

未观察到显著渲染回退，最终均值约占 10 FPS 的 100ms 帧预算 4.09%。逐帧样本见 [修改前](evidence/range-refined-2026-10-04/before-benchmark.json)、[修改后](evidence/range-refined-2026-10-04/after-benchmark.json)。这是本机单批均值，不是跨机器性能保证或统计显著性检验；开发中的首轮探测曾出现约 11.3% 增量，促成本帧受击事件复用优化，后续测量也有正常计时波动。

**修改清单**

| 文件 | 内容 |
|---|---|
| `tools/mockups/pixel_vfx.py`（新增） | 历史轨迹、帧内采样、2×2 dithering、语义弹体/粒子、分层星形、双描边环、受击变形/羽化、数字弹跳原语 |
| `tools/mockups/render_battle_gif.py` | 普攻及切镜接入、落点预示、方向受击、实际遮罩同步、重击数字、帧内事件复用 |
| `tools/mockups/skill_vfx.py` | 技能多环细节、volley 尾迹、mend 十字光点、去除蓄力 RGB 插值 |
| `tools/mockups/profile_vfx.py` | 压顶碎屑改为四向长方形 |
| `tools/mockups/profile_range.py` | 更新靶场说明 |
| `tools/mockups/r1_contract_check.py` | 语义弹体、双圈与星形外描边的新契约，保留尺寸/遮挡/预算约束 |
| `tools/mockups/vfx_separation_check.py` | 双描边与分隔多环判据、记录实际半径，兼容重击参数 |
| `tools/mockups/fx_visibility_check.py` | 仅采集钩子兼容 `heavy` 参数；所有阈值不变 |
| `tools/mockups/refinement_check.py`（新增） | 曲线节奏、短弹道、尾迹速度比例、形状色板、念力空心、羽化、方向挤压、预示窗口、跳字与预算检查 |
| `tools/mockups/refinement_evidence.py`（新增） | 从指定 commit 加载基线，三组对照及相同 100 帧性能测量 |
| `reports/evidence/range-refined-2026-10-04/**` | 新靶场、PNG/GIF、对照、指标、日志与源码指纹 |
| 本报告 | 实现、读数、复现与边界 |

**已知限制**

1. 10 FPS 输出仍是离散像素动画；25ms 历史子帧用于尾迹，帧内采样用于保证短飞行可见，不会增加 GIF 帧率，也不改变模拟状态。空间距离极短或预算耗尽时，尾迹会重合或按预算裁减。
2. 原保护遮罩优先。星形、白核和四角预示可能在密集场景被精灵遮掉一部分；不以穿透身体来保证每个细节完整露出。挤压的增长方向遇固定画布或棋盘边界时会被限制。
3. 受击羽化用既有纸白与原精灵颜色交错，50% 指棋盘覆盖率；不是新增的 50% 灰色。原有状态染色、天气和全屏闪光的历史实现仍保留，所以不宣称整幅合成帧只有四种 RGB。
4. 原 land 隔离差分包含原有棋盘闪光，可能整盘变化；本报告的两档面积比独立排除了该层。双 seed 零失败不等于覆盖所有阵容，generic 实战样本为 76/mend；其他技能原语由夹具覆盖。
5. 大面积数字避让仍沿用原规则；基本弹跳曲线是 3px 上抛、1px 回落，拥挤时避让可能额外改变其屏幕坐标。数字值、HP/能量结算时刻未变。
6. 确定性覆盖当前 Python/Pillow、同素材环境，未验证跨平台像素一致。Pillow 的 `getdata` 弃用提示不影响此次结果。
7. QualityGate 为辅助检查：最终 CLI 返回 `gate/raw_gate=pass`、`block_merge=false`、`execution_complete/blocking_execution_complete=true`、0 findings、`incomplete_engines=[]`，自报 `quality_confidence=full`；Mutation 按默认暂停，为 `not_applicable`。没有 actionable block，也没有语义修复。当前会话未注册中央 MCP，runner 依赖检查还缺部分 Mutation/Go 工具，其安装目录不在授权写入范围，因此未安装/升级，也不将本地结果称为完整中央语义验收。主验收依据为上面的专项结果。见 [qualitygate.json](evidence/range-refined-2026-10-04/qualitygate.json)。

**复现**

```sh
PYTHONDONTWRITEBYTECODE=1 python3 tools/mockups/refinement_check.py
PYTHONDONTWRITEBYTECODE=1 python3 tools/mockups/r1_contract_check.py --output reports/evidence/range-refined-2026-10-04/contracts.json
PYTHONDONTWRITEBYTECODE=1 python3 tools/mockups/vfx_separation_check.py --output reports/evidence/range-refined-2026-10-04
PYTHONDONTWRITEBYTECODE=1 python3 tools/mockups/fx_visibility_check.py --output reports/evidence/range-refined-2026-10-04/visibility
PYTHONDONTWRITEBYTECODE=1 python3 tools/mockups/profile_range.py --species 6,65,143,76 --out reports/evidence/range-refined-2026-10-04
# 性能命令应在其他验收结束后顺序执行：
PYTHONDONTWRITEBYTECODE=1 python3 tools/mockups/refinement_evidence.py --capture before --baseline-commit d7139f9
PYTHONDONTWRITEBYTECODE=1 python3 tools/mockups/refinement_evidence.py --capture after
```
