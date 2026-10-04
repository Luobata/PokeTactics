"""M2 经济层：收入 / 利息 / 连胜连败 / 经验人口（纯函数 + 常量表）。

设计依据（docs/00-brainstorm §5、docs/03 §5-§6，骨架沿任务书微调）：
- 每轮基础收入 5 金；
- 利息：结算后余额（基础收入已入账）每 10 金 +1，上限 +5（50 金封顶）；
- 连胜/连败：同一梯度表，连胜连败同权（连败可玩是 docs/03 §3 红线），
  梯度取 docs/03 §5 的 2/4/6 轮 +1/+2/+3；
- 刷新 2 金；买经验 4 金 +4 XP；每轮白送 2 XP；
- 等级 1-7，人口 = 等级 + 2（1 级 3 人口起步，7 级 9 人口封顶，
  头脑风暴 §1「1 级 3 只起步，上限 9 只」）；
- 经验曲线见 LEVEL_XP_COST（升到下一级所需 XP），总量 102 XP：
  白送 62（31 轮 ×2）+ 约 40 金买经验 = 满级，留给人格分化空间。

本模块零随机、零 IO；所有数值在常量区，sim-first 调参只改这里。
"""

# ---- 常量表（M2 首版读数见 reports/m2-economy-2026-09-13.md）----
BASE_INCOME = 5            # 每轮基础收入
INTEREST_PER_10 = 1        # 每 10 金利息
INTEREST_CAP = 5           # 利息上限（50 金吃满）
REFRESH_COST = 2           # 刷新一次商店
XP_BUY_COST = 4            # 买一次经验的金币
XP_BUY_AMOUNT = 4          # 买一次经验获得 XP
XP_PER_ROUND = 2           # 每轮白送 XP
START_GOLD = 2             # 开局金币（TFT 同款：2 轮「迷你经济」的感觉由首轮商店承担）
START_HP = 100             # 玩家/机器人 HP

# 连胜/连败梯度：>=6 轮 +3 / >=4 轮 +2 / >=2 轮 +1（docs/03 §5 连败补偿表，
# 连胜同表——自走棋共识：连胜是强度收益，连败是经济补偿，两头都真）
STREAK_TABLE = ((6, 3), (4, 2), (2, 1))

# 等级 → 人口（头脑风暴 §1：1 级 3 人口起步、上限 9；等级 1-7）
LEVEL_POP = {1: 3, 2: 4, 3: 5, 4: 6, 5: 7, 6: 8, 7: 9}
MAX_LEVEL = max(LEVEL_POP)

# 等级 → 升到下一级所需 XP（1 级起步已拥有；累计到 7 级 = 2+6+10+16+28+40 = 102）
LEVEL_XP_COST = {1: 2, 2: 6, 3: 10, 4: 16, 5: 28, 6: 40}

# 败方掉血阶段系数：掉血 = 2 + 存活敌棋数 × 系数（头脑风暴 §7）
# 三段：前期轻（1-9 轮）→ 中期 ×2 → 决赛圈 ×3；满员败北最高 2+9×3=29。
# （首版 10/20 分界会把局长顶到 31 上限拖满，9/17 是 50 局批量读数校准值；
#  2026-09-14 平衡 pass：四系统翻开 + 规则对齐后局长 27.8 贴带下缘，两段
#  分界各推后 1 轮 → 28.1-28.4 入带 (28,34)，打满上限 ≤10%——见
#  reports/matchbalance-2026-09-14.md）
# R2 节奏定参二次校准（2026-10-04）：攻速 ×1.5 + 全员技能下局长 27.7
# 贴带下缘，两段分界各再推后 1 轮 → 28.5+ 入带
STAGE_FACTOR = ((1, 1), (11, 2), (20, 3))
LOSS_BASE = 2              # 掉血公式的固定底数


# ---- 纯函数 ----
def interest(gold_after_income: int) -> int:
    """结算后余额 → 利息（每 10 金 +1，封顶 5）。"""
    return min(gold_after_income // 10, INTEREST_CAP)


def streak_bonus(streak: int) -> int:
    """当前连胜(+)或连败(-)的绝对长度 → 额外金币。"""
    n = abs(streak)
    for threshold, gold in STREAK_TABLE:
        if n >= threshold:
            return gold
    return 0


def round_income(gold: int, streak: int) -> int:
    """一轮总收入 = 基础 5 + 利息 + 连胜/连败。

    口径：利息按「基础收入入账后」的余额计（同一轮攒到的钱下一轮才吃息，
    与 TFT 的实际到账顺序一致，玩家读数直观）。
    """
    return BASE_INCOME + interest(gold + BASE_INCOME) + streak_bonus(streak)


def stage_factor(round_no: int) -> int:
    """轮次 → 败方掉血的阶段系数。"""
    factor = STAGE_FACTOR[0][1]
    for start, f in STAGE_FACTOR:
        if round_no >= start:
            factor = f
    return factor


def loss_damage(round_no: int, enemy_survivors: int) -> int:
    """败方掉血 = 2 + 存活敌棋数 × 阶段系数（头脑风暴 §7）。"""
    return LOSS_BASE + max(0, enemy_survivors) * stage_factor(round_no)


def pop_of(level: int) -> int:
    """训练家等级 → 上场人口。"""
    return LEVEL_POP[min(max(level, 1), MAX_LEVEL)]


def xp_to_next(level: int) -> int:
    """升到下一级所需 XP；满级返回 None。"""
    if level >= MAX_LEVEL:
        return None
    return LEVEL_XP_COST[level]


def buy_xp(level: int, xp: int, gold: int) -> tuple:
    """尝试买一次经验。返回 (level, xp, gold, bought)——纯函数式更新。"""
    if level >= MAX_LEVEL or gold < XP_BUY_COST:
        return level, xp, gold, False
    xp += XP_BUY_AMOUNT
    gold -= XP_BUY_COST
    while xp_to_next(level) is not None and xp >= xp_to_next(level):
        xp -= xp_to_next(level)
        level += 1
    return level, xp, gold, True


def gain_round_xp(level: int, xp: int) -> tuple:
    """轮次白送 XP（+2，可能跨级）。返回 (level, xp)。"""
    xp += XP_PER_ROUND
    while xp_to_next(level) is not None and xp >= xp_to_next(level):
        xp -= xp_to_next(level)
        level += 1
    return level, xp


# ---- 自检表（导入即打印的对照表，供文档引用）----
def describe() -> str:
    """人读参数表（报告与 README 引用）。"""
    lines = [
        f"收入：基础 {BASE_INCOME} + 利息(每10金+1,上限{INTEREST_CAP}) "
        f"+ 连胜连败 {[f'>={t}:+{g}' for t, g in STREAK_TABLE]}",
        f"刷新 {REFRESH_COST} 金；买经验 {XP_BUY_COST} 金 +{XP_BUY_AMOUNT}XP；"
        f"每轮白送 {XP_PER_ROUND}XP",
        "等级/人口/升级XP: " + "  ".join(
            f"L{l}→{LEVEL_POP[l]}人"
            + (f"(升下一级{LEVEL_XP_COST[l]}XP)" if l in LEVEL_XP_COST else "(满级)")
            for l in sorted(LEVEL_POP)),
        "阶段系数: " + "  ".join(
            f"R{STAGE_FACTOR[i][0]}-{(STAGE_FACTOR[i + 1][0] - 1) if i + 1 < len(STAGE_FACTOR) else '∞'}"
            f" ×{f}" for i, (_, f) in enumerate(STAGE_FACTOR)),
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    print(describe())
