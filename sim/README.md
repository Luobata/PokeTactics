# sim — PC 端玩法仿真

PokeTactics 的核心迭代杠杆：**调一次数值在表现层要重做一局，在这里几秒钟跑几百局**。
零第三方依赖，系统 python3 即可。方法论与目录结构继承自
[PokeWalk 的 sim/](../../ESP32-PokemonGo/sim/README.md)。

## 模块

| 文件 | 内容 |
|---|---|
| `data.py` | 数据层：加载 `data/` 三表，克制倍率、进化族/阶段、招牌招式推导、数值公式常量区 |
| `roster.py` | 棋子池：从 35 个进化族自动生成 84 只棋子（档位=形态自身 BST，S2 定稿；射程=特攻远程） |
| `combat.py` | 战斗解算器：7×6 棋盘 tick 制自动战斗（BFS 寻路+目标滞回），金银伤害公式，能量大招；**输出事件流**（双端渲染回放契约） |
| `prototype.py` | 端到端原型：确定性自检 + 随机阵容批量对打 + 平衡报告 |
| `experiment_effectiveness.py` | 克制作用范围 × 倍率压缩 × 等级拍平六臂对照实验（报告见 reports/） |
| `experiment_melee.py` | 近战/远程补偿六臂对照实验（远程惩罚/突进/坚韧） |
| `experiment_tiering.py` | 档位重排对照实验：旧档位（按进化阶段）vs 新档位（按形态 BST），档内 BST 方差/极差 + 同档内战胜率带宽 + 确定性回归 |

## 用法

```sh
# 平衡报告（默认 300 场 6v6 随机阵容；开跑前先做同种子事件流一致性自检）
python3 sim/prototype.py --games 300

# 带示例战斗的事件流时间线 / 换 seed / 换队伍规模
python3 sim/prototype.py --games 50 --size 8 --seed 7 -v
```

## 双端渲染同步契约（宪法 2.6）

`Battle.events` 输出 `(t, kind, ...)` 离散事件（deploy/move/attack/cast/die/end）。
Web 预览与 ESP32 固件都是这条事件流的回放器：同种子 → 同事件流 → 同画面。
C 内核移植的验收方式就是与 Python 参考实现比对事件流。

## 当前骨架的占位设计（全部待 S 系文档定稿替换）

- 档位 = 形态自身 BST（1费<365 / 3费≥500，S2 定稿），等级全档拍平 45 级（S1 定稿）；
- 普攻无属性不吃克制（S1 定稿：克制只上大招）；大招吃本系加成 × 属性克制 × 命中骰；
- 特攻种族 > 物攻 → 远程 3 格，否则近战；
- 速度 → 攻击间隔：`1/(0.6 + speed/150)`。

## 调参入口

| 参数 | 位置 | 作用 |
|---|---|---|
| `LEVEL_BY_TIER` | `roster.py` | 档位等级；S1 定稿=全档拍平 45 级（进化强度只来自种族值跳变），勿改 |
| `TIER_BY_BST` | `roster.py` | BST 档位阈值（S2 定稿 365/500，取自池分布自然断点）；扩池时需重标定 |
| `ENERGY_*` | `data.py` | 回能速度 → 大招频率 → 战斗节奏 |
| `BASIC_POWER` | `data.py` | 普攻占比：调高则战斗更「平A」，克制爆点更稀有 |
| `MAX_BATTLE_SECONDS` | `data.py` | 超时线，防龟缩 |
| `SPEED_TO_ATTACK_INTERVAL` | `data.py` | 速度族的强度 |
| `EFF_ON_BASIC / EFF_COMPRESS` | `data.py` | 克制作用范围与倍率压缩（实验开关，默认=克制只上大招原始倍率） |
| `RANGED_INTERVAL_MULT / MELEE_MOVE_MULT / MELEE_RESIST` | `data.py` | 近远程均衡开关（默认=近战突进 ×0.6，S1 定稿；其余无补偿） |

## 判读（见 prototype 输出尾部）

- 单棋伤害占比 >25%、属性胜率跑出 45-55% 带宽、平局率 <10% 为健康；
- 随机阵容的结论只能看方向——真正的平衡要等买入 AI（M2）。
