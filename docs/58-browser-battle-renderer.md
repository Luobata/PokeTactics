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
- Pillow 保留三种用途：`?renderer=png` 回退、设备 / ESP32 模式、测试参考帧。
- 「双端同源」重新定义为：同一权威事件流、同一时间轴、同一关键帧数据与采样规则。宪章修订由主线负责，本文不改动。

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
  - 联动链：0.9 秒内的连携 / 羁绊 / 特性 / 元素反应依次强调，单位之间画连线，镜头跟随。
- **未知事件**
  - `(t,'effect',src,tgt,effect_id,payload)`：按 `payload.label/value/kind` 显示标签和对应类别的符号；`camera:'focus'` 时短暂聚焦。
  - 其它未知 kind 降级为目标或来源身上的小提示。

## 3. 数据格式

### 3.1 战斗脚本（`/api/battle/script?sid=&round=`，schema `poketactics.battle_script` v1）

| 字段 | 内容 |
| --- | --- |
| `clock` | `duration`（时间轴总长）、`result_time`、`frame_dt`=0.05、`frames` |
| `arena` | `cols`/`rows`（6×6），`team_rows`（我方 3–5 行，敌方 0–2 行），开场天气 |
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

- 关键帧沿用 `esp32_runtime/animation.py` 的 7 字段，末尾加缓动：`[at, dx, dy, angle, scale_x, scale_y, visible, ease]`。
- 7 字段部分必须原样通过 `validate_track`：at 落在 0–1 且严格递增，dx/dy 不超过 ±48 的整数，缩放 50–150。
- 线性段的采样与 `sample_track` 完全一致（JS 的 `samplePortable`，有对照测试）。
- `ease` 表示从这一帧到下一帧所用的曲线。

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
- `recipes`：分层配方。每层有 `layer`（charge / projectile / trail / impact / ground / aura / screen）、`shape`、`at`（锚点：start、anticipation、release、impact、recover、end）、`palette`（`@type` 表示用招式属性）、`curve`、`duration`、`size`、`count`、`target`。
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
  - 通过 Node 运行的渲染器契约：确定性、节奏多样性（最高组合 < 35%）、命中不移位、扭曲后总长不变且单调、未知事件降级、采样器与 esp32 一致。
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
- 链式联动按时间窗口分组，不读取因果 id；等 sim 的新效果系统给出明确的因果字段后，应改为按字段串联。
- 新增的 `effect` 事件目前只有通用标签和符号，镜头只认 `camera:'focus'`；具体效果还需要专门的配方。
- 配方的形状库是程序化绘制，没有逐帧特效贴图；技能级配方（按 `bindings.skill`）只覆盖了少数几个。
- 设备端（ESP32）还没接入关键帧加缓动的格式：数据层已兼容，C 端采样器的缓动还没实现。
- 帧扭曲的补偿上限是 1.08 倍。顿帧和慢放很多的长战斗会按优先级丢弃后面的慢放：击倒 > 首次大招 > 暴击。
