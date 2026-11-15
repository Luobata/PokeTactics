# 58 · 浏览器战斗渲染器与战斗动画工作台

日期：2026-11-15 · 范围：/play 竞技回合战斗演出、/animation-workbench、assets/motion、assets/vfx

## 1. 为什么换到浏览器

旧链路由 Pillow 在服务端逐帧画 960×640 PNG（20fps）：一场 583 帧的战斗要约 80 秒、68MB，播放端只能贴图。实测动作单调的原因有这几条：

- 76–83% 的动作共用 3 种节奏组合。
- 精灵最大 64px，4px 前冲和 5% 挤压根本看不出来。
- 顿帧预算摊到整场后每次不足 1 帧。
- 没有击退、镜头和大招插画。

现在的做法：

- /play 的竞技战斗默认在浏览器用 Canvas2D 以显示器刷新率渲染。
- Pillow 保留两种用途：`?renderer=png` 回退、测试参考帧。回退路由保持可用，但不再扩展。
- 2026-11-15 用户决定：设备 / ESP32 模式不再需要支持，只做浏览器端。竞技网页路径因此不再要求与 `esp32_runtime` 的采样一致、不要求可移植到 C，也不要求与 Pillow 像素对齐。
- 「同源」只指：同一权威事件流、同一时间轴、同一份动作与特效数据。

## 2. 架构

```
sim/combat.py Battle ──events──▶ AnimationTimeline（start/release/impact/end）
        │                                   │
        ├─▶ battle_script.py ──script.json──┤──▶ /api/battle/script ──▶ battle_renderer.js（Canvas2D 60fps）
        │   （同一次解算，写在帧目录旁）       │
        └─▶ web_battle.py（Pillow）──PNG──▶ /demo/frame/...（?renderer=png / 设备 / 测试）
```

- **脚本落盘**
  - `demo._prepare_battle_frames` 在权威解算后，把 `script.json` 写到 `.build/demo/<sid>/r<轮>/`，和 PNG 帧放在同一目录。
  - 帧任务清目录时会保留它。
  - 存档格式不变：`session_save.py` 只存结算摘要。
- **重建与恢复**
  - 脚本缺失、但本进程还持有该轮参数时，`/api/battle/script` 用同一种子重跑，写出的文件与原文件逐字节一致。
  - 服务重启并恢复存档后，`_restore_battle_replay` 优先接回完整 PNG 帧集；没有帧集时，用 `script.json` 里的 `playback_meta` 接回回放。
- **帧任务闸门**
  - play.js 在 `end_prep` / `next` 时带上 `renderer=script`，这类轮次不预先启动 Pillow 任务，参数登记在 `_RENDER_LAZY`。
  - 有人请求 PNG 帧（例如 `?renderer=png`）时，`ensure_render_job` 才第一次开渲。这一次不算崩溃重启，不占用唯一的重启额度。
  - 不带参数的旧调用（测试、设备）行为不变。
- **播放端（play.js 只改回放段）**
  - `last_battle.script` 为真且没有 `?renderer=png` 时，动态载入 `/play/assets/battle_renderer.js`，拉取脚本和动画数据包，用 requestAnimationFrame 播放。
  - 倍速、暂停 / 继续（含侦察时自动暂停）、拖动、跳到结尾、战果与统计、事件日志都沿用原控件。
  - 脚本 404 或载入失败时自动回退到 PNG 帧。

### 2.1 渲染器模块（`tools/acceptance/battle_renderer.js`）

| 接口 | 说明 |
| --- | --- |
| `compile(script, pack)` → plan | 纯函数，生成动作重排、命中 / 数字 / 标签、链式联动、地面贴花、全局时间扭曲、镜头事件 |
| `frame(plan, t)` → 绘制清单 | 纯函数，同一脚本和同一 t 一定得到同一清单，可任意拖动（有 Node 测试保证） |
| `paint(ctx, plan, list, images)` | 唯一有副作用的绘制 |
| `BattleRenderer` | 浏览器封装：按 devicePixelRatio 缩放画布、读取精灵不透明包围盒、悬停显示名字、`teamTotals(t)`、`log()`、`monotony()` |

**时间**

- 脚本里的时间是时间轴时间（sim）。
- 顿帧和大招慢放是一张全局扭曲表（playback→sim），其余时段以不超过 1.08 倍的速度快进来补偿，所以总时长等于时间轴时长。拖动条与队伍遥测保持对齐。

**节奏（打破节拍器）**

- 命中时刻（impact）固定不动，HP 快照始终对准造成它的那一下。
- 只重排蓄力和收招，取值依据：
  - 角色原型（近战 / 远程 / 辅助 / 坦克）
  - 体重（由种族值推出）
  - 每个单位固定的偏移
  - 每个动作的哈希抖动
  - 弹道飞行时长
- 同一单位的各个动作窗口不会重叠。
- 实测 arena_showcase：最高占比的节奏组合从时间轴原始的 42% 降到 10%。

**已实现的表现**

- **P0**
  - 近战真实冲刺到接触点再返回，带残影。
  - 受击后退 6–12px、回弹并闪白。
  - 只在击倒、暴击类大伤害、大招时顿帧，每次至少 2 帧（60fps 下 4–6 帧）。
  - 待机呼吸按单位错开相位。
  - 全部使用缓动。
  - 精灵约放大 1.6–1.9 倍，并按透视深度缩放；用不透明包围盒对齐脚底与影子。
  - 精简后的血条：护盾段、能量条、星级点、最多 3 个状态徽标；名字只在悬停时显示。
- **P1**
  - 四种出手原型：近战斩弧、远程后坐加弹道、辅助引导光环、坦克踏地冲击波。
  - 大招和击倒时镜头推近（1.04–1.08）并压暗其他单位。
  - 屏幕震动随伤害权重变化。
  - 伤害数字有弹出和缩放，按克制关系配色；治疗、护盾、吸收数字。
  - 状态色调与粒子：中毒、灼伤、麻痹、睡眠、冰冻、束缚、嘲讽、潮湿、畏缩、守护。
  - 天气覆盖层：雨、晴、沙、冰雹，切换时出现提示条。
  - 击倒时分条溶解，并弹出「击倒」卡片。
- **P2**
  - 六种弹道家族：直线、抛物线、追踪、光束、地面行进、齐射。
  - 18 种属性各有粒子调色板和材质。
  - 地面贴花：岩钉、藤蔓、毒池、焦痕、裂纹。
  - 大招横幅（立绘、技能名）加慢放。
  - 联动链按因果串联（见 2.2），单位之间画连线，镜头跟随。
- **未知事件**
  - `(t,'effect',src,tgt,effect_id,payload)`：按 `payload.label/value/kind` 显示标签和对应类别的符号；`camera:'focus'` 时短暂聚焦。
  - 其它未知 kind 降级为目标或来源身上的小提示。
- **arena_v2（深度版）**
  - 新开竞技局默认 `arena_v2`。
  - `effect` 事件的 source 和 target 都是 -1（例如冲锋号、先锋壁垒）时，按 `payload.team` 在全队头顶只弹一次大标签，并在每名队员脚下画环；`camera:'focus'` 推近整队。
  - `kind:'move'`（开场跃进、撤退）只显示标签，不显示数值 0；位移本身由权威的 `move` 事件驱动。
  - `meta.terrain` 的格子以 `(localRow, col)` 给出，脚本将其换算成全局 `[col, row, team]`：我方行号 = 3+localRow，敌方行号 = 2−localRow 且列号镜像为 5−col。棋盘按地形类型着色，并用虚线描边。

### 2.2 第二轮（2026-11-15）：逐技能特效、分件形变、因果编排

**因果结果（outcomes）**

- `skill_effect` / `combo_effect` / `field_effect` / `partner_effect` 的 payload 带 `cast_index` 或 `action_index`（也认 `source_cast_index`），它们指向原始事件序号，正好等于脚本里动作的 `i`。渲染器据此把每条效果挂到所属动作的 `outcomes` 上。
- 每条 outcome 记录 `sub`（heal、side_hit、knockback、guard、energy、root……）、目标、`origin_idx`（连锁的上一跳），以及演出用的错开延迟 `delay`。
- `effect` 事件（效果总线）若带这些字段就直接挂上；不带时，挂到在同一时刻命中、且与其来源或目标相关的动作上。
- 新的效果来源 `order`（战术令）、`quest`（羁绊任务）沿用通用效果路径：标签按来源加符号（令 / ★），颜色仍按 kind。

**因果编排（取代 0.9 秒窗口）**

- 同一动作的 outcome 按时间和顺序逐跳错开（每跳约 0.12 秒，上限 0.66 秒）。相关标签使用同样的延迟。
- 动作波及两个及以上单位时生成一条链：第一拍是主目标，后面依次是各个结果目标。
- 镜头只跟随施放技能的链，或至少 3 拍的链，避免普通攻击也频繁晃镜头。

**逐技能特效（每个原生技能都有配方）**

- `assets/vfx/core.json` 新增 25 个类别轮廓 `cat.<category>`，覆盖 `arena_skills`、gen3 与家族技能出现的全部类别，外加 `cat.technique`（技能机）。各类别形状不同，不是换色。

| 类别 | 主要轮廓 |
| --- | --- |
| chain | 叉状闪电逐跳（link fork，从 `origin_idx` 到下一个目标） |
| area | 地面扩散环 + 抛起的碎石 + 裂纹 |
| drain / lifesteal | 粒子流从目标倒流回施法者（link stream）；吸血另有一股流向受治疗的友军 |
| shield / guard | 六角蜂巢护罩（hex dome），按每个被守护对象各出现一次 |
| heal / rescue | 上升光点 + 十字符号；救援附带拉回的牵引线 |
| cleanse / clear | 螺旋光带 + 抖落的暗色碎屑 |
| root | 藤蔓从地面长出缠住目标 |
| taunt | 施法者身边向外扩散的喊声弧（`)))`）+ 目标锁定圈 |
| displacement | 推开方向的推力速度线 + 扬尘，方向取自 payload 的起止格 |
| combo / pursuit / assassin | 多段连打、咬合、爪痕、处决 X 斩 |
| pierce / vulnerability / execute / poison / terrain / retaliation / control | 贯穿光线、锁定准星、X 斩、毒池气泡、岩钉、尖刺外壳、眩晕星 |

- `assets/vfx/skills.json`（新数据包）由 `motion_seed.py` 生成，为 133 个原生技能 id 每个写一条 `skill.<id>` 配方并绑定到 `bindings.skill`：
  - 继承所属类别：`extends: cat.<category>`。
  - 按标签追加层，例如击退加推力线、护盾加蜂巢、连锁加闪电、定身加藤蔓、嘲讽加喊声弧、范围加扩散环。
  - 原本没有蓄力层的对敌技能，按技能 id 稳定地选一种蓄力轮廓。
  - 按威力缩放尺寸（0.8–1.45），按行为覆盖弹道。
- 配方新增字段：`extends` / `add` / `drop`（继承、追加、去掉）和 `palette` / `family` / `scale` / `particle`（整体覆盖）。
- 层新增字段：
  - `on`：按 outcome 实例化，例如 `on: heal` 时每个受治疗的友军各出现一次。
  - `from` / `to`：连线的起止，取值 actor / target / origin。
  - 新层类型 `link`，形状有 fork、stream、tether、hop_arc。

**分件形变（单张精灵的分带网格）**

- 精灵按高度切成 12 条横带逐带绘制：
  - 脚底一带固定不动。
  - `lean`：身体向前（正值）或向后剪切。
  - `head_x` / `head_y`：上部头带位移。
  - `belly`：中段加宽（%）。
  - `wobble`：沿各带传播的抖动。
- 数据在片段的 `parts` 里，形如 `parts: {phase: [[at, lean, head_x, head_y, belly, wobble, ease], ...]}`，阶段名与该 slot 的位移阶段相同。`roles.json` 的全部原型片段都已写入。
- 物种和家族片段自己没有 `parts` 时，借用同 slot 的原型片段。受击时会额外叠加随伤害大小衰减的 wobble。
- 工作台可以编辑这些轨道（见第 4 节）。

## 3. 数据格式

### 3.1 战斗脚本（`/api/battle/script?sid=&round=`，schema `poketactics.battle_script` v1）

| 字段 | 内容 |
| --- | --- |
| `clock` | `duration`（时间轴总长）、`result_time`、`frame_dt`=0.05、`frames` |
| `arena` | `cols`/`rows`（6×6），`team_rows`（我方 3–5 行，敌方 0–2 行），开场天气，`ruleset`（arena_v1 / arena_v2），`terrain`（深度版地形：id、name、description、全局格子 `[col,row,team]`） |
| `units[]` | idx、team、sid、name、star、shiny、role、types、range、melee、pos、max_hp、item、technique、skill（id/name/type/category/arch/tags/power/targeting）、trait、sprite |
| `actions[]` | 时间轴每个动作：i（原始事件序号）、kind、actor/target、start/release/impact/end、secondary/terrain、from/to、damage、cast 时的 move/eff/skill |
| `states{idx}` | `[t, hp, energy, shield]` 演出时刻的权威快照 |
| `positions{idx}` | `[t, col, row, deploy/walk/forced/blink, blink 时间]` |
| `statuses[]` | `{unit, kind, start, end}`（异常、潮湿、守护 / 鼓舞等带过期时间的效果） |
| `weather` / `deaths` / `cutins` | 天气切换、阵亡时刻、时间轴原有的插画窗口 |
| `events[]` | 全部演出事件 `[t_演出, t_模拟, kind, ...参数]`，已转成 JSON 安全格式 |
| `log[]` | 与战报一致的中文事件行 |
| `playback_meta` | 恢复存档时接回回放所需的 meta |

另有两个工作台端点，都不创建对局、不写存档：

- `/api/battle/script/preview?species=&kind=&scene=&seed=`：复用 `make_preview_scene`。
- `/api/battle/script/scenario?key=&seed=`：复用 `arena_scenarios.make_scene`。

### 3.2 动作数据（`assets/motion/*.json`，`kind: motion_pack`，schema_version 1）

- 位移关键帧：`[at, dx, dy, angle, scale_x, scale_y, visible, ease]`。
  - 数值界限沿用原 7 字段格式：at 落在 0–1 且严格递增，dx/dy 不超过 ±48 的整数，缩放 50–150。
  - 设备端已经不再支持，`samplePortable` 对照测试只作为历史兼容保留，不再是约束。
- `ease` 表示从这一帧到下一帧所用的曲线。
- 分件轨道：`parts.<phase>` = `[at, lean, head_x, head_y, belly, wobble, ease]`。
  - 界限：lean ±24，head ±16，belly −30..40，wobble 0..12。
  - 首尾帧必须在 0 和 1。

| 文件 | 内容 |
| --- | --- |
| `roles.json` | 片段 `clips`（slot：idle、walk、attack_melee、attack_ranged、cast、hit、ko、victory，各有阶段）和原型 `archetypes`（melee/ranged/support/tank 的片段绑定和节奏 timing） |
| `families.json` | 由 `family_motion._ACTIONS`（25 种家族模板）转换，放大 2.4 倍 |
| `species.json` | 逐物种绑定：家族模板、由 `motion.species_motion` 转换的手绘待机循环、体重 weight |

各 slot 的阶段：

- idle / walk / victory：`loop`
- attack_melee：`anticipation`、`dash`、`contact`、`recover`
- attack_ranged、cast：`anticipation`、`release`、`recover`
- hit：`react`
- ko：`fall`

坐标单位是源精灵像素，+dx 指向目标，渲染时乘以精灵缩放和深度。物种覆盖优先于原型。

### 3.3 特效配方（`assets/vfx/*.json`，`kind: vfx_pack`）

- `palettes`：每种属性 4 色 `[core, light, main, dark]`，另有 HEAL、SHIELD、KO。
- `materials`：属性粒子材质，包括 particle、gravity、count、size、life、speed、spin。
- `projectiles`：六种弹道家族的参数。
- `recipes`：分层配方，可以写 `layers`，也可以用 `extends` 加 `add` / `drop`。
  - 每层有 `layer`（charge / projectile / trail / impact / ground / aura / link / screen）、`shape`、`at`（锚点：start、anticipation、release、impact、recover、end）。
  - 还有 `palette`（`@type` 表示用招式属性）、`curve`、`duration`、`size`、`count`、`target`。
  - 以及 `on`、`from`、`to`（见 2.2）。
  - 校验器会检查 `extends` 能否解析、有无循环，以及 shape 是否属于该层的允许列表。
- `bindings`：配方选择顺序为技能 id → 类别 → 原型；`type_projectile` 是属性到默认弹道的映射。
- `screen`：镜头规则，分 ult、ko、crit、shake、combo。

**校验与重新生成**：

- `python3 tools/acceptance/motion_schema.py` 校验全部数据包，包括包之间的引用。
- `python3 tools/acceptance/motion_seed.py` 从 Python 动作表重新生成数据包。工作台改过的文件请勿再用它覆盖；它的 `--check` 只报告差异。

## 4. 战斗动画工作台（/animation-workbench）

入口在「调试工具 · 动画与演出」和 /acceptance 卡片。

1. **战斗来源**：三种。
   - 单个动作：精灵、动作、靶场。
   - 场景库。
   - 真实对局：sid + 轮次。
   - 也可以用 `?species=6&kind=cast`、`?scenario=…`、`?sid=…&round=…` 直接打开。
2. **A/B 对照**：A 用已保存的 assets，B 用编辑中的数据，共用同一时钟。
   - 播放 / 暂停 / ±1/60 秒逐帧（←/→ 键）、拖动、倍速、循环。
   - 可以只看 B 的大图。
3. **多轨时间线**：
   - 轨道：镜头、顿帧 / 横幅、事件，以及每个单位一条蓄力 / 出手 / 收招轨（标出命中线、大招、击倒）。
   - 点击某个动作段会跳转过去，并载入它绑定的片段。
4. **编辑 B**：
   - 关键帧表：插入 / 删除、缓动预设、缓动曲线图、位移曲线图，并按 esp32 的数值界限实时校验。
   - 原型节奏和物种体重。
   - 特效配方 JSON。
   - 「保存到 assets」只提交改过的文件。服务端只接受本机请求，要求带工作台标记头，校验 schema 和跨包引用后原子写入；还可以导出或还原。
5. **单调度仪表盘**（A、B 对照）：
   - 最高节奏组合占比，目标低于 35%，并与原始时间轴对比。
   - 同时进行的动作最多几个。
   - 有明确焦点的帧占比。
   - 顿帧列表，以及其中达到 2 帧以上的数量。
   - 弹道家族的种类和分布。
   - 击倒、大招、联动链的次数。

原有的 /animation-lab 和 /animation-editor（Pillow）不变。

## 5. 验证

- `tests/test_browser_battle_renderer.py`：
  - 脚本结构、确定性，以及与 AnimationTimeline 的逐动作一致。
  - HP 快照与 Pillow 演出视图一致。
  - 渲染闸门：脚本轮次不跑 Pillow，首次请求帧时才开渲；脚本缺失时重建，恢复存档时接回。
  - HTTP 路由和资源、保存接口（只限本机、校验、原子写入）。
  - schema 正反例；种子生成器与已提交的数据包同步。
  - 通过 Node 运行的渲染器契约：确定性、节奏多样性（最高组合 < 35%）、命中不移位、扭曲后总长不变且单调、未知事件降级、因果结果与链条只来自 cast_index / action_index、分件形变在出手和受击时生效、每个特效形状都确实绘制。
  - 数据：每个原生技能都有自己的配方，各类别轮廓互不相同且带签名形状，配方用到的形状在渲染器里都有绘制代码，分件轨道和配方继承都经过校验。
- `tests/frontend/battle_playback_presentation.js` 新增两个场景：
  - `scriptRenderer`：不请求 PNG；rAF 时钟、暂停、倍速、拖动、结尾战果、关闭时销毁。
  - `scriptFallback`：脚本 404 时回退到 PNG。
- 截图证据在 `reports/evidence/browser-renderer-2026-11-15/`：
  - 同一局 /play 的新旧对照：`play_js_round4_t8.5.png` 与 `play_png_round4_t8.5.png`。
  - 场景的大招横幅、顿帧、击倒。
  - 雨天导电的横幅和联动链。
  - 工作台。

## 6. 尚未完成

- 精灵只有正面单帧。没有背面图和分件骨骼，身体动作只能整身变换；`character_rigs` 的分件动画还没迁到浏览器。
- 分件形变只是对单张正面精灵做分带网格变形，没有真正的四肢；`character_rigs` 的分件动画仍未迁到浏览器。
- 新的效果总线 `effect`（order / quest / augment 等来源）仍是通用标签加符号；不带 `cast_index` 的总线效果，按同一时刻相关的动作推断因果。
- 特效形状都是程序化绘制，没有逐帧特效贴图。逐技能配方由类别轮廓加标签组合生成，签名技能还可以在工作台逐条精修。
- 技能机（TM）共用 `cat.technique`，没有逐招配方。
- 帧扭曲的补偿上限是 1.08 倍。顿帧和慢放很多的长战斗会按优先级丢弃后面的慢放：击倒 > 首次大招 > 暴击。
