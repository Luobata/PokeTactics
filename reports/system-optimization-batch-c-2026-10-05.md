# 第三批交付：八角色分层招式与动作编辑预览

八个核心角色已有各自的蓄力、传播、命中和余波。喷射火焰使用连续火舌，
水炮使用双股水流与独立水花，日光束与破坏光线通过宽度、聚能位置和后坐力区分。
动作编辑工作台可调整表现参数、同步对照默认效果、逐帧检查并导出预设。

前两批代码已提交为 `68eeb71`。本批基于该提交继续开发；
[源码摘要](evidence/animation-core-2026-10-05/source-fingerprint.json)记录本批验收源码。
下述交付是 PC 实现与证据，ESP32 绘制后端和设备性能仍待移植验收。

## 1. 角色动画

| 角色 | 当前真实招式 | 本批表现 | 样片 |
|---|---|---|---|
| 喷火龙 | 喷射火焰 | 张口聚能、锥形火舌、亮芯、命中火星与余烬 | [普攻](evidence/animation-core-2026-10-05/after/6-attack.gif) · [大招](evidence/animation-core-2026-10-05/after/6-cast.gif) |
| 水箭龟 | 水炮 | 炮口聚水、双股连续水流、泡沫和目标水花 | [普攻](evidence/animation-core-2026-10-05/after/9-attack.gif) · [大招](evidence/animation-core-2026-10-05/after/9-cast.gif) |
| 妙蛙花 | 日光束 | 花心收光、窄束亮芯与外缘、叶光消散 | [普攻](evidence/animation-core-2026-10-05/after/3-attack.gif) · [大招](evidence/animation-core-2026-10-05/after/3-cast.gif) |
| 雷丘 | 十万伏特 | 蓄电、折线电弧与分叉、局部命中电火花 | [普攻](evidence/animation-core-2026-10-05/after/26-attack.gif) · [大招](evidence/animation-core-2026-10-05/after/26-cast.gif) |
| 胡地 | 精神强念 | 聚焦、身体残影与晶片、消失落地、精神冲击 | [普攻](evidence/animation-core-2026-10-05/after/65-attack.gif) · [大招](evidence/animation-core-2026-10-05/after/65-cast.gif) |
| 耿鬼 | 舌舔 | 暗紫聚能、舌弧伸出与回收、短暂残影 | [普攻](evidence/animation-core-2026-10-05/after/94-attack.gif) · [大招](evidence/animation-core-2026-10-05/after/94-cast.gif) |
| 隆隆岩 | 地震 | 下压发力、地裂传播、低幅碎石与尘土 | [普攻](evidence/animation-core-2026-10-05/after/76-attack.gif) · [大招](evidence/animation-core-2026-10-05/after/76-cast.gif) |
| 卡比兽 | 破坏光线 | 稳定重心、口部聚能、宽束和后坐力；近身仍能看见光束 | [普攻](evidence/animation-core-2026-10-05/after/143-attack.gif) · [大招](evidence/animation-core-2026-10-05/after/143-cast.gif) |

参考 G1–G3 的招式脚本，将源端、传播和目标命中层分开，并使用错开发射、
色板与身体发力形成节奏。具体源码、提交和适配判断见
[招式动画参考](../docs/17-gen123-animation-reference.md)。本轮核对了源码，未运行原作或抽取 ROM 素材。
新增特效像素自行制作，沿用项目已有角色精灵资源。

16 个片段均以实际 Battle 事件采样；八个大招选取首个正伤害事件。
雷丘靶场改用普通属性卡比兽，避免原岩石靶导致电招式免疫；仅修改展示 fixture。
同刻附加伤害会一起反映在目标 HP 中，因此 HP 差额不一定等于该条主伤害。
原始模拟事件、胜负与状态计算未修改；传播最短时间调整只作用于演出时钟。

## 2. 动作编辑工作台

启动验收服务后打开 `/animation-editor`。选择角色、普攻或大招、种子，调整四项设置：

| 设置 | 范围 | 验收行为 |
|---|---|---|
| 色板 | classic / vivid | 真实绘制使用相应颜色 |
| 特效大小 | 0.7–1.3 | 主体与辅助效果尺寸变化 |
| 粒子密度 | 0.5–1.0 | 辅助粒子数量变化，仍受总预算约束 |
| 动作幅度 | 0.5–1.5 | 身体姿态表现变化 |

点击「生成预览」后，默认与修改后的画面在同一时刻并排播放；支持暂停、
0.5×/1×/2×、逐帧、时间拖动，以及开始/释放/命中/恢复阶段跳转。
两侧分别运行相同种子的真实战斗渲染，不在浏览器复制游戏规则。

预设仅保存版本、角色和四项表现参数，不保存 seed 或动作类型。
导入严格拒绝重复字段、未知字段、越界值、未来版本、非有限数字和超过 8KB 的文件。
参数未应用时禁止导出；渲染或导入失败保留上次成功画面。完整加载新帧后才切换预览。
服务端限制单片段 100 帧、缓存 24 项；失败生成不会累积缓存或挤掉上次成功结果。

这是参数编辑与动作检查器，尚不能拖拽关键帧、绘制 sprite、编辑骨骼或保存多轨工程。
预设用于当前编辑预览，尚无“发布为游戏默认配置”的入口。

## 3. 美术与可移植数据

`art-manifest.json` 新增八类、每类三帧、每帧 9×9 的索引像素 `effect_cels`，
含透明索引和两套四种不透明颜色的 RGB888 色板。
`vfx.core.*` 引用独立于物种数据，阶段统一为 `charge / flight / impact / aftermath`。
校验覆盖像素来源、角色引用、阶段可实际绘制和篡改拒绝。

当前仍有 16 套手工身体动作/技能演出、8 只本批分层特效、3 个玩法签名，分别统计。
像素 cel 已可导出，Python 的编排与绘制尚未全部变成 C 数据或字节码。
每帧 192 粒子、3 条技能轨是已实现的限制；PC 测量不能证明 ESP32 预算达标。

## 4. 验收结果与复现

```sh
python3 tools/acceptance/system_acceptance.py --demo --presentation \
  --output .build/animation-c/acceptance.json
python3 tools/acceptance/server.py --port 8807
# http://127.0.0.1:8807/animation-lab
# http://127.0.0.1:8807/animation-editor
```

依赖已有 Pillow 和兄弟项目 `../ESP32-PokemonGo/assets/`。
`animation_showcase.py` 默认导出八角色，也支持 `--species 6,9` 子集。

| 验收项 | 证据与结论 |
|---|---|
| 统一自动验收 | [JSON](evidence/animation-core-2026-10-05/acceptance.json)：8 项通过、0 失败、1 项 balance 未选；本批未重跑 40 局平衡实验 |
| 单元测试 | 128 项通过；含 8 项新特效、9 项编辑预览、12 项资源清单测试；[审查修正后完整重跑](evidence/animation-core-2026-10-05/post-review-tests.log)仍为 128 项通过 |
| 完整 Demo | seeds 7/42，均到 R31；25 场玩家战斗、6,293 帧、728 次 HTTP 200；真实存档进程重启检查也通过 |
| 动画样片 | 16 段 240×320、20fps；[manifest](evidence/animation-core-2026-10-05/after/manifest.json)记录时序、HP 和像素摘要 |
| PC 测量 | 本轮稀疏靶场 p50 3.720ms、p95 4.743ms；不是满人口、音频叠加或设备测试 |
| 美术清单 | [最终 manifest](evidence/animation-core-2026-10-05/after/art-manifest.json)导出及 verify 通过，revision `328174ece46dad498353a7239d0dbfc1b4c4dfe118c29733c89778c01a76cdb4` |
| 浏览器 | [操作记录](evidence/animation-core-2026-10-05/browser-acceptance.json)：真实调参生成、命中/单步、JSON 下载及重新导入、重复字段拒绝、角色切换及旧 GIF 加载；无 JS error |
| 独立审查 | [记录](evidence/animation-core-2026-10-05/review.json)：编辑器与核心特效均 pass；巨整数、失败缓存、重复字段和阶段名称四项问题已修复复核 |
| 静态与工具 | 编译、JS 语法、diff 空白检查通过。QualityGate MCP 不可用；CLI 有效规则快照为空，返回 pass 不计入有效覆盖，详见 [工具记录](evidence/animation-core-2026-10-05/qualitygate-summary.json) |

统一验收先执行，独立审查随后修正了 manifest 的阶段名称；最终已重新执行全部
单测及 manifest 导出/校验。这个修正不改变渲染像素和 Demo 规则，因此保留此前
同一渲染实现的 GIF、性能与整局证据，没有把旧 revision 伪装成最终 revision。

## 5. 旧版对照与后续门槛

验收页每张动作卡可展开 `68eeb71` 的旧版片段；
[旧版清单](evidence/animation-core-2026-10-05/before/manifest.json)与
[对照来源](evidence/animation-core-2026-10-05/baseline-source.json)随代码保存。
旧版在隔离的 `git archive` 源码上生成，保持旧 renderer/motion/VFX，只对采样脚本
统一中性雷丘靶和首个正伤害事件选择。两版 GIF 各自原速播放，不做事件同步；
编辑器内的默认/调整对照才使用相同时间轴。

下一步可验收交付应集中在：关键帧/多轨工程编辑、受击/死亡/控制/护盾专用素材、
同屏密集演出遮挡测试、音效触发与限流，以及 C/Python 整数采样和像素对账。
NVS、USB 恢复、设备断电与 RAM/帧率测试仍按前批运行时合同推进。
