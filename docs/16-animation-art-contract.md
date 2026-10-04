# 16 · 动画、美术资源与可移植清单

状态：2026-10-05，**核心 8 角色演出、16 段样片和动作编辑器已交付；ESP32 绘制后端未移植**。
本文承接 [15 · 通用运行时边界](15-esp32-runtime-design.md)：共用资源格式、
时钟和绘制接口，游戏自己提供角色、招式、事件与资源映射。不能把 Python
预览通过等同于设备 RAM、帧率、Flash 占用或断电行为已验收。

## 1. 可直接执行的资源交付

```sh
python3 tools/mockups/art_manifest.py --output .build/animation-b/art-manifest.json
python3 tools/mockups/art_manifest.py --verify .build/animation-b/art-manifest.json
python3 -m unittest discover -s tests -p test_art_manifest.py -v
```

默认只读取 `../ESP32-PokemonGo/assets/`，不会复制、重写兄弟项目资源。
另一个环境可用 `--asset-root /path/to/assets` 指定同一逻辑资源根。
生成 JSON 不包含机器绝对路径、生成时间或随机 ID，相同输入在新 Python
进程中仍输出逐字节相同的内容。`revision` 是清单内容 SHA-256；代码或资源
改变后应重新导出。它用于定位视觉输入，不是存档的兼容性拦截条件。

若已生成本轮动画证据，可明确附带该次 **PC** 测量：

```sh
python3 tools/mockups/art_manifest.py \
  --pc-metrics .build/animation-b/manifest.json \
  --output .build/animation-b/art-manifest-with-pc-evidence.json
```

这只引用并校验证据 JSON 的摘要，不重新跑性能测试。清单标为
`supplied_evidence_not_remeasured`；证据更换会改变 revision。默认导出中
PC 帧耗时、峰值 RSS 均为未测，ESP32 状态始终为待移植、待真机测量。

## 2. 实际素材、来源与解码

首次导出从实际文件读取以下结果；以后以重新生成的清单为准：

| 资源 | 实际字节数 | 当前格式与覆盖 | 使用规则 |
|---|---:|---|---|
| `gen1_front.bin` | 90,730 | FRNT v1；151 张 40/48/56 方形精灵 | 行主序 2bpp，每字节高位先读；记录含物种 ID；色号 3 在本项目渲染为透明 |
| `palettes.bin` | 2,499 | PALS v1；146 套普通、146 套闪光，各 4 色，151 个映射 | little-endian RGB565；精灵索引不得越过调色板集合 |
| `font16.bin` | 42,344 | FNT1 v1；1,245 个 16×16 字形 | u16 码点表，1bpp 行主序、高位先读；单字 32 字节 |
| **运行时引用文件总计** | **135,573** | 三份二进制原文件 | 不包含 Python、Pillow、纹理缓存、生成帧与来源说明 JSON |

资源格式与 PC 实现位于 [decoders.py](../tools/mockups/decoders.py)。导出器
独立检查头部、版本、段范围、重复 ID、记录长度、调色板索引、字形数量，
并记录整文件与每个精灵像素记录的 SHA-256。`atlas` 表示这些**打包记录的
索引**，当前没有新生成的 GPU 纹理图集。

来源依据是兄弟项目的 `assets/pokemon_art_sources.json`，其中记录
`pret/pokecrystal`、提交 `7a7881d0d62e0ddbd82dcf10e7116807487ac651`、
Crystal 正面首个方形帧及原始调色板规则。清单保留这些声明及说明文件摘要。
这些宝可梦精灵与调色板是引用的原作素材，**不是 PokeTactics 原创美术**。
本项目编写的是围绕原素材的动作表、局部部件变形与程序化演出；本批新增的
8 族小像素特效帧为原创。G1–G3 的编排参考与适配边界见
[17 · 招式动画参考](17-gen123-animation-reference.md)。

`font16.bin` 自身没有记录字体名称和源字体摘要；PokeWalk 转换器允许选择
不同字体，不能凭默认参数断言这份二进制的精确字体来源。清单将其标记为
需补齐来源证据。本文不新增素材授权或再分发承诺。

## 3. 四层边界

| 层 | 输入 → 输出 | 当前 PC 实装 | 待迁移部分 |
|---|---|---|---|
| 资源解码 | resource handle、atlas record、palette → 像素/字形 | `decoders.py` 解码成 Pillow RGBA | 设备侧只读 packed 数据、透明色与 RGB565 blitter；错误资源拒绝 |
| 动作 clip | animation key、局部年龄、朝向、受击轨 → Pose | `motion.py` 的整数关键帧、重采样帧、rig、姿态合成 | C 表、整数采样器、局部切片与旋转的像素对账 |
| 事件编排 | 权威事件 → start/release/impact/recover/end | `animation_timeline.py` 的独立演出轴与因果顺序 | C 整数时钟与事件 ABI；倒放重建、倍速/跳过一致性 |
| 绘制后端 | Pose、特效、层级、预算 → framebuffer | Pillow、NEAREST、程序化粒子、HUD | ESP32 绘制、缓存、局部刷新、实际内存与耗时验证 |

`sim` 负责命中、伤害、死亡和资源变化，动画只编排其展示时间。角色与技能
映射保留在游戏适配层；未来通用框架应接收 `AssetId`、`ClipId`、`Pose` 与
时间戳，不能 import 宝可梦物种表或根据物种号决定伤害。

资源更新与存档迁移也分开：动画资源 revision 不同可以使旧录像外观变化，
并不意味着同 schema 的游戏进度不可继续；需要精确重现录像时，另记录
规则版本、资源 revision 和事件流，而非以固件构建哈希拒绝所有旧存档。

## 4. 清单 v1 的具体结构

| 字段 | 含义 |
|---|---|
| `schema_version / game_id / revision` | 清单格式、游戏命名空间、内容身份 |
| `logical_roots` | `project` 与 `pokewalk_assets`；加载器使用允许的根目录解析路径 |
| `inputs` | 生成清单依赖的源文件/游戏数据文件的路径、字节数和 SHA |
| `assets` | 资源字节身份及 FRNT/PALS/FNT1 解码元数据 |
| `atlas` | `front/6` 等资源记录；asset key、offset、bytes、尺寸、palette index、记录 SHA |
| `animation_data.clips / rigs` | 动作与部件轨道数据；不嵌精灵图、不绑资源文件路径 |
| `animation_data.effect_cels` | 8 族 × 3 帧 × 9×9 索引像素，以及 classic/vivid 色板；每套四种不透明色加透明 |
| `actors` | `species.6` 的 role key、atlas key、动作 key、技能 key；在这一层组合动作与素材 |
| `coverage` | 可购池、素材池、手工动作、技能演出与无招式角色覆盖 |
| `clock / coordinates` | 时间单位、采样、画布、棋盘及局部坐标合同 |
| `budget` | 配置上限、算术尺寸估计和实际测量三者分别记录 |
| `port_status` | 每层 PC 与设备实现状态 |

当前工具是 PokeTactics 的 schema v1 **适配导出器和校验器**，不是已经能
加载任意游戏的 ESP32 资源管理器。其它游戏可以沿用字段结构，提供自己的
角色/动画目录；不能直接沿用本工具的宝可梦覆盖检查。

动作例子：`motion.6.windup` 包含整数 `frames`、整数毫秒 `sample_ms`、
`loop` 和每帧 `rig_phase`。帧的六个字段依次是：前向像素、向下像素、
横向百分比、纵向百分比、顺时针角度、消散四分位。`presentation_frames`
已烘焙当前 `presentation_pose` 的身体放大；`hit` clip 则烘焙独立受击轨。
rig 区域以原精灵占用包围盒的百分比表达，位移轨保持原像素单位；相位用
`[numerator, denominator]` 表达，避免把 Python 浮点小数直接当设备协议。

技能编排、默认步态等程序化条目标为 `procedural_python` 且
`frames_exported=false`。核心特效的 8×3×9×9 像素数据单独导出到 `effect_cels`，
透明索引为 0、四种不透明色索引为 1–4，保留二值 alpha；它不是 2bpp 打包格式。
四阶段名为 `charge / flight / impact / aftermath`。小像素帧可移植，
完整编排与光栅变换仍为 Python，不能将它们声称为完整纹理序列或 C 字节码。
手工新增一条不存在的 animation key 不会通过校验；引用缺失资源、错误 SHA、错误 atlas 范围也会使命令非零退出。

## 5. 覆盖范围与下一批美术工作

当前清单实际得到：151 个精灵记录、84 个可购角色、16 个具备完整七状态
动作表的角色、16 个与实际招式 ID 绑定的独立技能演出。游戏技能分类为
3 个专属、80 个通用；凯西没有可释放的属性招式，故不能将其散射模板计入
真实技能覆盖。素材覆盖、技能机制覆盖和手工演出覆盖是三个不同数字。
本批的 **8 种核心视觉效果没有把玩法签名从 3 种扩成 8 种**。

| 核心角色 | 当前招式 | 本批可辨识主体 |
|---|---|---|
| 6 喷火龙 | 喷射火焰 | 有锥度的连续火舌与断裂余烬 |
| 9 水箭龟 | 水炮 | 双股水束、泡沫边与独立横向水花 |
| 3 妙蛙花 | 日光束 | 叶光聚能、硬边亮芯和双层外缘 |
| 26 雷丘 | 十万伏特 | 折线电弧、短分叉和命中电花 |
| 65 胡地 | 精神强念 | 瞬移残影与念力晶片 |
| 94 耿鬼 | 舌舔 | 弯曲舌弧、暗紫残影与接触碎片 |
| 76 隆隆岩 | 地震 | 脚下裂纹、低矮土浪与碎岩 |
| 143 卡比兽 | 破坏光线 | 口前聚能、近身可见短粗束与后坐力 |

未手工建档的角色使用默认程序化步态/普攻/受击/死亡路径。这一批先让
核心角色的蓄力、发射、飞行、命中与恢复更清楚；继续扩充时按以下验收：

1. 新角色必须有独立身体发力部位和七状态 clip，而不只是改变类型颜色。
2. 专属/通用技能均绑定实际 `move_id`；更换招式时清单覆盖也应改变。
3. 复用现有原作精灵，不改变解码后的色板；新增部件、纹理或图集必须新增
   资源记录与来源，不塞进运动逻辑。
4. 无动作引用或无技能的角色须明确 fallback / `can_cast=false`，不能靠
   一个通用标签声称已有手工表现。

## 6. 坐标、时钟与未来 C 对账

PC 画布为 240×320，左上角原点、x 向右、y 向下。单格 40px，战斗模拟
为 6×4 格；绘制为含双方备战行的 6×6 格，模拟行加 1 后落到绘制行。
原点与脚点偏移取实际 renderer/layout 常量；脚点不会随精灵晃动导致
血条和能量条上下飘移。缩放和旋转使用 NEAREST。

当前动作采样为 idle 100ms、其它动作 50ms，既有粒子相位为 100ms。
Python 事件仍以秒浮点输入，演出编排用 50ms 网格。设备移植应使用整数
毫秒或 50ms tick，并在边界转换一次。clip 采样是
`floor(age_ms / sample_ms)`；idle/walk 取模循环，其余钳制到末帧。
Python `round` 是 ties-to-even；不要假定 C `roundf` 的半值处理相同。
优先消费清单中的已烘焙整数帧，并单独定义变换坐标的舍入规则。

`AnimationTimeline.events` 是内部绘制流：attack/cast 在动作开始时出现，
其状态变化在 impact 时出现；`public_events` 的伤害日志时间也为 impact。
`ActionTiming` 显式保留 start、release、impact、recover_end 与起终点。
倍速只在 `AnimationTimeline.time()` 应用一次，skip 跳到含死亡收束的
duration；不要再叠一次旧播放时钟。胡地闪现等额外编排以该版本源码为准，
不能用本文的文字摘要替代实际动作轨。

C 验收应复用固定输入事件，逐项比较：

- 同一毫秒的动作 index、六维 Pose、rig 相位、状态/死亡先后；覆盖边界前
  1ms、边界时刻和边界后 1ms。
- 0.5×、1×、2×、跳过、倒放重建在对应演出时间得到相同最终状态。
- 致命投射物先出现、命中时数字/HP/能量变化一致，再播放死亡；不能先判
  目标消失而取消致命弹道。
- 胡地闪现、重击位移、齐射及同刻侧命中沿原事件顺序对账；不能为了
  演出改变模拟事件或消耗新的游戏 RNG。
- 再比较像素：先验证解码和 alpha，后验证裁切、rig、NEAREST、旋转与
  图层顺序。仅比较 HP 或最终 PNG 不足以证明中间动作正确。

## 7. 预算合同与实测边界

配置值直接从当前代码读取：每帧粒子预算 192、同时展示的技能轨 3、
每战 portrait 窗最多 2 次、每次 200ms、投射物最长飞行 450ms。这些是
PC 展示规则，不是 ESP32 可以持续承受这些负载的性能结论。

240×320 的单层 RGBA 字节数按算术为 307,200；RGB565 为 153,600。
这不是峰值 RAM：Pillow 对象、缓存、源像素、临时透明层、旋转结果和显示
双缓冲会另外占空间；也不等于必须在设备上分配完整 RGBA 帧缓冲。

本轮动画证据 `.build/animation-b/manifest.json` 来自核心 8 角色各一段普攻
和技能，共 16 个稀疏四单位片段的真实 Pillow 逐帧渲染，PC 帧耗时 p95 为
4.743ms。统一验收为 128 项测试、8 项检查通过，1 项平衡检查跳过。
样片记录每段粒子峰值、技能轨峰值、帧耗时与测试输入；**不能外推到满人口
同屏或 ESP32**。清单附带的是
指定证据文件当时的副本与摘要，不证明它比当前代码更新，也不自动重跑。

设备验收另需记录：资源常驻/按需解码策略、最大临时 buffer、缓存容量与
淘汰、帧耗时 p50/p95/max、峰值可用堆/栈、屏幕传输耗时、低电/后台降级、
最密集战斗下 HUD 可读性。未测项保留 pending；不能将限流上限或 PC
靶场耗时填入设备测量栏。

## 8. 动作编辑器与样片复验

启动验收服务后，`/animation-lab` 查看 16 段样片，`/animation-editor` 编辑
核心 8 角色的普通攻击或大招。编辑器以相同真实 Battle 输入和种子生成原样
与调整后两侧画面，共用演出时钟；“原样”指当前版本默认参数。支持播放、
0.5×/1×/2×、逐帧、拖动和 start/release/impact/recover_end 阶段跳转。

| 参数 | 允许值 | 作用 |
|---|---|---|
| `palette` | `classic` / `vivid` | 特效色板 |
| `effect_scale` | 0.7–1.3 | 特效实体尺寸与扩散尺度 |
| `particle_density` | 0.5–1.0 | 有预算约束的粒子数量 |
| `motion_scale` | 0.5–1.5 | 身体预备、后坐与受击幅度 |

参数存于各 renderer 实例，不修改全局配置、伤害、游戏 RNG 或事件时间。
JSON 预设使用 `schema_version=1`，仅保存 `species` 与四项 `settings`，
不包含种子或动作类型。导入严格校验格式、版本、角色、字段与数值范围，
拒绝重复键、未知字段及非有限数；成功生成预览后才能导出已应用参数。

```sh
# 默认导出全部 16 段；可指定角色子集和独立目录
python3 tools/mockups/animation_showcase.py --out .build/animation-b --seed 7
python3 tools/mockups/animation_showcase.py --species 6,9 --out .build/animation-subset
```

样片优先选真实正伤害动作，保留免疫或未命中的真实事件；雷丘木桩采用
卡比兽以展示电击命中。表现参数变化前后仍须对账权威状态、命中/死亡顺序、
倒放一致性与粒子上限，不能只检查最终画面是否不同。
