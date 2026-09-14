# 四系统成套翻开 · 新基线 · 2026-09-14

**决策**（用户批准）：S5 装备（ITEMS_ON）/ S10 组合技 A（COMBOS_ON）/ S12 状态
（STATUS_ON）三开关默认 True + match 主对战场接入 S11 天气时刻表
（docs/05 §1 固定序列 R6-10 晴 / 11-15 雨 / 16-20 沙 / 21-25 雹 / 26+ 轮换）。
同时用户裁定：**暂缓 M4 双端 C 内核**，下一阶段核心 = 玩法平衡可玩性 +
Web 完整可玩 Demo。

## 翻开面

| 系统 | 翻开方式 | 备注 |
|---|---|---|
| S5 装备 | `items.ITEMS_ON = True` | 进化石唯一通道（同日裁定） |
| S10 齐射 | `combo.COMBOS_ON = True` | 最高档触发、单轮、占比 ≤12% |
| S12 状态 | `status.STATUS_ON = True` | 免疫=属性常识、控制递减 |
| S11 天气 | `match.weather_for_round()` 固定时刻表 | 幽灵轮/野怪轮无天气（快照与 PvE 语义） |

## 可复现性

五个先于这些系统的历史实验（effectiveness/melee/tiering/synergy/balance）
入口已钉三系统关；四系统各自的实验臂本来就显式管理自家开关。

## 新基线（全开，20 局 seed=5）

- 局长均值 27.6 / 中位 28（区间 24-31；目标带 28-34 的下缘——全开后节奏略快，
  首个调参候选：决赛圈掉血档）；
- 人格方差 0.502（PASS）、决策 p99 1.72ms（PASS）、无死锁（PASS）；
- 冠军分布 copycat×10/20 仍偏强（跟牌型连续第三个报告领先——bot 对位
  强化的优先级提升）；
- prototype 战斗层不受翻开影响（items/combo 挂在 match 层，status 开启后
  随机局影响在噪音带内）。

## 盯防清单（进平衡 pass）

1. copycat 人格 50% 冠军率；
2. 局长 27.6 贴目标带下缘；
3. MELEE_MOVE_MULT 遗留（C-sym 后怪力vs胡地 +14pp，docs/10 预言项）；
4. 三色围巾+天气石在天气常开后的占比复查（平衡修订在天气关态做的）。

## 复现

```sh
python3 sim/match.py --bots 8 --seed 100        # 单局全开
python3 sim/experiment_match.py --games 20 --seed 5
```
