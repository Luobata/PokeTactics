# PokeTactics · 宝可梦自走棋

宝可梦 × 自走棋（TFT/云顶之弈式自动战斗）：从商店购买宝可梦排兵布阵，
三只同种**进化**成高阶形态，用 17 系属性克制与羁绊在棋盘上自动对战。
单机模式：训练家（你）vs 7 名机器人对手打满整轮。

**双端同源**：同一份 C 内核编译为 ESP32 设备固件与 Web 同源预览，
渲染一致性以像素对账验收（继承 [../ESP32-PokemonGo（PokeWalk）](../ESP32-PokemonGo)
的固件同源预览架构与 ABC 三键操作体系）。
数据同样继承 PokeWalk：种族值、招式表、属性克制表、进化链均从其固定提交数据提取；
「先在 PC 仿真上调平衡，再谈 C 内核与表现」的 sim-first 流程亦然——
**调一次数值在表现层要重做一局，在 sim 里是几秒钟跑几百局**。

## 当前状态

- [x] 项目骨架：`sim/` 玩法仿真 · `data/` 结构化数据 · `docs/` 设计文档 · `reports/` 验证报告
- [x] 数据提取管线：151 只种族值/属性/进化链 + 17 系克制表 + 251 招式
- [x] 最小战斗原型：tick 制自动战斗解算器，**事件流输出**（双端渲染回放契约），
      含同种子确定性自检
- [x] 系统定稿（实验驱动）：S1 战斗解算核心（克制只上大招/等级拍平/近战突进）、
      S2 进化升星 BST 定档、S3 羁绊 v1（默认关，待 M2 复验）——见 docs/systems/
- [x] 设计稿 v1：240×320 像素真稿（准备/战斗/大招特写）+ 高清版 + 动画节拍表，
      真实素材渲染（docs/02 §4、docs/design/mockups/）
- [ ] 经济/商店/机器人对手模拟（M2，羁绊翻开的闸门）
- [ ] C 内核 + ESP-IDF 固件 + Web 同源预览（M4，见宪法 §1/§2）

## 目录

| 目录 | 内容 |
|---|---|
| `sim/` | 零依赖 Python 玩法仿真，核心迭代杠杆；同时是 C 内核的参考实现 |
| `data/` | 从 PokeWalk 提取的结构化数据（生成物，可由 tools 重建） |
| `tools/` | 数据提取与后续管线（双端构建、预览服务） |
| `docs/` | 头脑风暴、设计宪法（双端/三键/内存约束）、编号系统文档 |
| `reports/` | 按日期命名的验证报告 |

## 快速开始

```sh
# 验收后台（推荐入口：设计稿/动画验收台/事件流对照）
python3 tools/acceptance/server.py --port 8799
# 浏览器打开 http://127.0.0.1:8799/
# Web 可玩 Demo（1 玩家 + 7 bot 整局：买棋/摆位/装备/羁绊/天气/战斗动画）
#   http://127.0.0.1:8799/demo ｜ 整局自测 python3 tools/acceptance/demo_selftest.py

# 从 ../ESP32-PokemonGo 提取数据（data/ 已随仓库提供，可跳过）
python3 tools/extract_from_pokewalk.py

# 跑战斗原型：随机阵容 × 300 场，输出平衡性报告
python3 sim/prototype.py --games 300
```

系统 python3 即可（已在 3.9+ 验证），无第三方依赖。

## 来源与边界

宝可梦数据源自 PokeWalk 项目固定提交的 [pret/pokecrystal](https://github.com/pret/pokecrystal)
提取链（详见 `data/*.json` 内的 `source` 字段）；每只宝可梦的属性组合为
`tools/species_types_gen2.py` 中手工整理的金银世代属性表。
本项目为同人玩法原型，不将原作素材声称为本项目原创。
