# 60 · PMD SpriteCollab 帧动画精灵

日期：2026-11-15 · 范围：浏览器战斗渲染器（/play 竞技回放、/animation-workbench）、`assets/pmd/`、`tools/pmd_import.py`

浏览器战斗默认改用《宝可梦不可思议的迷宫》（PMD）风格的逐帧动画精灵。原来的经典正面立绘仍然可以切换回去。商店、图鉴等界面的头像不在本次范围内，仍然使用经典立绘。

## 1. 来源、许可与署名义务

- **来源**：PMD SpriteCollab（https://github.com/PMDCollab/SpriteCollab），固定提交为 `424d5ff2e79785f9535f25f647455d3d723b8573`（2026-11-15 通过 `git ls-remote HEAD` 取得）。
- **版权**：
  - 宝可梦形象 © The Pokémon Company / Nintendo / Creatures / GAME FREAK。
  - 署名为 `CHUNSOFT` 的精灵（绝大多数）取自 PMD 系列游戏，© Spike Chunsoft。
  - 其余为社区作者绘制，按 **CC BY-NC 4.0**（署名—非商业）授权。
- **我们的义务**：
  1. **只能用于非商业用途**。本项目是同人原型，不得出售，也不得用于有收益的发行。任何商业化都必须替换全部宝可梦美术素材（包括经典立绘）。
  2. **署名**。`assets/pmd/CREDITS.md` 由导入器根据 SpriteCollab 的 `tracker.json` 和 `credit_names.txt` 自动生成，逐物种列出精灵、异色和头像的作者。随项目分发时必须一并保留。
  3. **可追溯**。`assets/pmd/SOURCES.json` 记录提交 SHA、每个源文件的 URL 和 sha256，以及每个输出文件的 sha256。
- 试玩页和工作台只引用本地 `assets/pmd`，运行时不访问外网。

## 2. 导入器 `tools/pmd_import.py`

```sh
python3 tools/pmd_import.py                  # 全部竞技物种（家族 + 旧模板 + 丰缘 + 野怪波次，共 152 种）
python3 tools/pmd_import.py --species 6,25   # 只更新子集（合并进 index.json）
python3 tools/pmd_import.py --verify         # 按 SOURCES.json 重算哈希并校验清单与 actions.json
python3 tools/pmd_import.py --offline        # 只用 .build/pmd-cache 里的缓存
python3 tools/pmd_import.py --sha <commit>   # 换固定提交（必须全量重导）
```

**处理流程**：

1. 只下载需要的 13 个动画：Idle、Walk、Attack、Strike、Swing、Double、Shoot、Charge、Rotate、Hop、Hurt、Faint、Sleep。遇到 `CopyOf` 就跟随到它引用的表。
2. 读取 `AnimData.xml` 中的帧尺寸、每帧时长（60fps 的 tick）、RushFrame、HitFrame、ReturnFrame。
3. 从 `-Offsets.png` 读取每帧的标记点：黑 = 头，绿 = 身体中心，红 / 蓝 = 双手。
4. 从 `-Shadow.png` 读取白色像素作为落脚锚点。
5. 每个动画取所有已存方向和帧（含异色）的不透明区域并集来裁剪。
6. 每个物种用货架法打包成一张图集，宽度不超过 1024 像素。颜色不超过 256 种时写成**无损调色板 PNG**（带 tRNS），否则写 RGBA PNG。
7. 异色读取 `sprite/<dex>/0000/0001/`，与普通版共用同一份裁剪框和坐标，单独存一张 `-shiny.png`。
8. 头像取 `portrait/<dex>/Normal.png`（40×40，约 1.4KB），只在大招横幅上使用。
9. 下载缓存在 `.build/pmd-cache/<sha>/`。输出是确定性的，重复运行逐字节一致（已验证），所以导入是幂等的。

**方向取舍**：图表的行序是 0 下、1 右下、2 右、3 右上、4 上、5 左上、6 左、7 左下（已用喷火龙的表核对）。只存 0–4 五个方向，5、6、7 在绘制时用 3、2、1 水平镜像得到。

- 棋盘上我方朝上、敌方朝下，横向移动时朝左或朝右，八个方向都会用到。
- PMD 原作本来就把左右视为镜像（个别不对称花纹除外）。
- 这样少存 37.5% 的图块，左右对称造成的误差几乎看不出来。
- 要补存某个方向，见第 6 节。

**体积**：152 种全部导入，152 种有异色，共 **21.6 MB**（包括图集、清单、头像、SOURCES 和 CREDITS），低于约 40 MB 的预算。没有回退物种（index 的 `fallback` 为空）。

## 3. 文件布局与清单格式

```
assets/pmd/
  index.json          物种索引 {schema, version, commit, anims, dirs_stored, license, species:{sid:{dex,file,anims,shiny,portrait}}, fallback:{sid:{style:'classic',reason}}}
  actions.json        时间轴阶段 → 动画的映射（手写，见第 4 节；导入器不覆盖）
  <dex>.json          物种清单（schema poketactics.pmd_species v1）
  <dex>.png           图集
  <dex>-shiny.png     异色图集（与普通版同坐标）
  portrait/<dex>.png  40×40 头像
  SOURCES.json        提交、源文件 URL+sha256、输出 sha256
  CREDITS.md          署名（自动生成）
```

物种清单 `<dex>.json`：

| 字段 | 含义 |
| --- | --- |
| `species` / `dex` | 全国图鉴号（数字 / 4 位字符串） |
| `shadow_size` | AnimData 的 ShadowSize（0–2） |
| `atlas` / `shiny_atlas` / `atlas_size` | 图集文件和尺寸；没有异色时 `shiny_atlas` 为 null |
| `dirs_stored` / `mirror` | 已存的方向 `[0..4]`；镜像表 `{5:3, 6:2, 7:1}` |
| `anims.<Name>.tile` | 裁剪后的图块宽高 |
| `anims.<Name>.cell` / `crop` | 原始帧格尺寸，以及裁剪框在帧格里的左上角 |
| `anims.<Name>.durations` | 每帧 tick（60fps） |
| `anims.<Name>.rush` / `hit` / `return` | RushFrame / HitFrame / ReturnFrame（可缺省） |
| `anims.<Name>.single_dir` | 只有一行的表（例如 Sleep），所有朝向共用 |
| `anims.<Name>.dirs.<d>.xy[i]` | 第 i 帧在图集里的左上角 |
| `anims.<Name>.dirs.<d>.anchor[i]` | 落脚点（Shadow 白点），相对图块左上角 |
| `anims.<Name>.dirs.<d>.head/center/hand_r/hand_l[i]` | Offsets 标记点，相对图块左上角；缺失为 null |
| `portrait` | 头像相对路径或 null |

校验器：`pmd_import.validate_manifest()` 和 `validate_actions()`。`--verify` 与 `tests/test_pmd_sprites.py` 都会调用它们。

## 4. 动作映射（`assets/pmd/actions.json`）

| 时间轴阶段 | 默认动画（按候选顺序；在该物种已有的动画里按物种哈希稳定挑选） |
| --- | --- |
| 近战普攻 | Attack / Strike / Swing（坦克：Attack / Swing / Strike） |
| 远程普攻 | Shoot，没有时用 Attack（辅助相同） |
| 原生技能 | 蓄力段放 `Charge`，出手段按类别选动画，见下一行 |
| 技能类别 | 例如：combo 用 Double / Attack，heal、cleanse 用 Rotate / Hop，shield、guard 用 Rotate / Charge，displacement、pursuit、execute 用 Strike，chain、pierce、poison 用 Shoot，taunt 用 Hop。辅助型施放默认 Rotate / Hop / Charge |
| 受击、击退滑动 | Hurt |
| 眩晕 / 睡眠 | Sleep（`stun_statuses` 列出触发的状态） |
| 击倒 | Faint（47/152 种有）；没有时用 Hurt 停在末帧，再淡出、分条溶解 |
| 待机 / 移动 | Idle / Walk（Walk 朝移动方向） |
| 胜利 | Hop |

**帧与时间轴对齐**（权威命中时刻不动）：

- 普攻：
  - 帧 `[0, Rush)` 均摊在 start→release。
  - 帧 `[Rush, Hit)` 均摊在 release→impact。
  - **第 Hit 帧恰好在 impact**；命中前不会提前显示 Hit 帧。
  - 帧 `[Hit, 结尾)` 均摊在 impact→end。
  - 每段内部按原 tick 比例拉伸。
- 施放：start→release 拉伸播放 Charge；release→impact 播放主动画 `[0, Hit)`；其余与普攻相同。
- 没有 Rush / Hit 时，Hit 取 55% 处，Rush 取 Hit 的一半。
- 顿帧期间模拟时间冻结，帧自然停住；慢放时帧随之变慢。

**朝向**：

- 每个单位朝向当前目标：取正在进行的动作的目标；没有时取下一个或上一个动作的目标；再没有就取最近的敌人。
- 由屏幕向量量化成 8 个方向，移动时朝移动方向。

**锚点**：Offsets 的 head 是弹道起点，center 是命中点与特效落点。蓝 / 红手部标记已经存进清单，留给以后的武器类特效。

**PMD 模式下的身体动作**：

- 帧本身已经在动，因此片段的位移、旋转、缩放和分件形变都关闭。
- 只保留物理运动：近战冲刺、击退推开、开场落地，以及很轻的受击抖动（原来的 35%）。
- 残影、白闪、状态色调、阴影、血条、特效层、镜头和顿帧都照常。

**缩放**：`actions.json` 的 `scale`（默认 2.5）乘以透视深度，再量化到 0.25 的整数倍，以保持像素清晰。

**异色**：3★（或单位本身标记为异色）时使用 shiny 图集；没有异色图集时叠加淡金色。

**扩展方式**：

- **改映射**：直接编辑 `actions.json`。动画名必须属于导入器的 `ANIMS`，`validate_actions()` 会检查。
- **逐物种覆盖**：在 `species.<图鉴号>` 下写 `basic_melee` / `basic_ranged` / `basic` / `cast` / `windup`。现有示例：怪力（68）近战用 Double 连打。
- **新增动画种类**：把名字加进 `pmd_import.ANIMS` 并重导；在 `actions.json` 里引用它；如需新的阶段，在 `battle_renderer.js` 的 `pmdFrame()` 里加分支。

## 5. 画风切换

- `/play` 战斗对话框速度控件旁有「画风」下拉（PMD 动画 / 经典）。选择写入 `localStorage['poketactics.sprite.style']`，切换时就地重编译，不重新拉取脚本，也不回退到 PNG。
- URL 参数 `?sprites=classic|pmd` 优先于 localStorage；默认 `pmd`。
- 工作台（含技能库）读同一设置，播放条上也有「画风」下拉。
- 某物种没有 PMD 精灵时，只有该单位用经典立绘；`/api/pmd/manifest` 的 `fallback` 会说明原因。
- 服务端：
  - `/pmd/<文件>` 提供图集、清单和头像，带 `Cache-Control: max-age=86400` 和 ETag，只允许白名单文件名。
  - `/api/pmd/manifest?species=6,25` 一次返回所需清单、动作映射和许可说明。

## 6. 扩展指南

- **新物种（含新世代）**：把物种加进 sim 的竞技池后运行 `tools/pmd_import.py`（或 `--species <图鉴号>`）。SpriteCollab 没有它时，导入器把它写入 `fallback`，渲染器自动用经典立绘。新世代的图鉴号格式相同（4 位）。
- **补存方向**：修改 `DIRS_STORED` 和 `MIRROR`（例如存全部 8 个方向时 `MIRROR = {}`），全量重导。渲染器按清单的 `mirror` 决定是否镜像，不用改代码。
- **换固定提交**：先 `git ls-remote https://github.com/PMDCollab/SpriteCollab.git HEAD`，把 `PINNED_SHA` 改成新值后全量重导，再 `--verify`，并在提交里附上 CREDITS 的差异。
- **体积预算**：目前 21.6 MB。补存全部 8 个方向约增加 60%；也加上 SpAttack 等更多动画还会更大。若超出约 40 MB，可以改为按需加载图集，或另找存放位置。

## 7. 验证

- `tests/test_pmd_sprites.py`：
  - 固定提交与输出哈希、每个竞技物种恰好属于 PMD 或回退之一、清单校验、核心动画齐全。
  - 动作映射校验与反例、署名和体积预算、无损 PNG。
  - 服务端点、缓存头与路径限制。
- `tests/frontend/battle_renderer.js` 的 `pmd` 场景：
  - 每个单位都解析到 PMD 或回退。
  - 94 个动作的 Hit 帧恰好落在 impact，命中前帧号都小于 Hit。
  - PMD 模式下拖动顺序不影响绘制清单；只使用已存方向。
  - 切换画风后时间轴完全相同；URL 参数生效。
- `tests/frontend/battle_playback_presentation.js` 的 `spriteStyle`：画风切换会持久化，并就地重绘。
- 截图在 `reports/evidence/pmd-sprites-2026-11-15/`：同一局 /play 在同一时刻的 PMD 与经典对照、场景对照、带画风下拉的对话框、工作台。

## 8. 尚未完成

- 152 种里只有 47 种有 Faint 动画，其余用 Hurt 末帧加淡出代替。Strike 有 114 种、Shoot 有 149 种，缺失时按映射回退。
- 方向只存了 5 个，镜像对不对称的花纹（例如喷火龙尾焰在身体哪一侧）会左右颠倒。
- PMD 原作比例下，小体型宝可梦在棋盘上明显比经典立绘小。这是有意保持原作比例；可以调 `scale`，或做逐物种缩放。
- 商店、图鉴、侦察面板的头像仍是经典立绘；只有大招横幅使用 PMD 头像。
- 手部标记还没有用在特效上；SpAttack、Pose 等动画没有导入。

## 准备界面头像（2026-11-15 追加）
- 棋盘、备战席、商店、训练家列表、选秀卡在“迷宫风格”下改用 `/pmd/thumb/<dex>.png[?shiny=1]`：取 Idle 动作朝下第一帧，3 倍最近邻放大，进程内缓存；没有 PMD 素材的物种 302 回经典立绘。
- 前端 `window.pokeSpriteUrl(sid, shiny)` 统一按画风选图（`?sprites=` > 本地保存 > 默认 pmd），战斗窗口切换画风后准备界面同步刷新。图鉴页仍用经典立绘。
