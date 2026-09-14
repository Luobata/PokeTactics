"""S3 羁绊系统 v1：17 系机制主题表 + 战斗开始时的一次性结算。

设计定稿见 docs/systems/S3-synergies.md，实验读数见
reports/s3-synergy-2026-09-13.md。要点：

- 计数：双属性棋子同时供两个羁绊；按场上当前形态（comp 里的 Piece.types）计，
  战斗内无进化，因此 Battle 初始化时算一次即可；
- 阈值统一 (2)(4)(6)，档位取最高档，表内数值为该档**总值**（非增量叠加）；
- 生效范围：全队（羁绊是队伍层面的凑数决策，代价在阵容构成上）；
- 效果只复用现有结算维度：面板（HP/双防/特防/攻击）、攻速、伤害乘区、
  减伤、回能、每秒治疗、大招承伤上限——不发明新的结算类型；
- 跨系同名效果**加法叠**（攻速/伤害/减伤/回能/治疗/面板），
  大招承伤上限取各系**最小值**，减伤合计封顶 60%；
- 本模块零随机、零 IO：所有数值在开战前定死，确定性条款（宪法 2.2）不受影响。

平衡原则（依据 84 只池的人口与防守画像，见 S3 文档 §2）：
弱势/浅池属性（草/岩/地/冰/虫/电/钢）机制更强，深池属性（毒 23 只/水 18 只/
普通/飞）效果刻意平——毒系 (2) 只有 +4% 伤害，因为深池羁绊近乎「常驻白赚」。

2026-09-14 平衡修订（盯防收尾，读数与论证见 reports/balance-ice-bug-2026-09-14.md）：
1. 冰 (2) 减伤 4% → 2%：S3 §5 盯防条款触发动作（随机局 ICE 读数连续报告 62-70%），
   针对双拉普拉斯队（WATER(6)+ICE(2)）的套利路径；
2. 治疗衰减 HEAL_TIER3_MULT：heal 类效果对 3 费旗舰棋子减半——羁绊的补偿
   语义是抬弱单位，不是喂强势单位。随机局治疗量级 ~1HP/s 与胜负无关
   （对照臂：水治疗整体清零，ICE 62.1%→63.6% 在噪音带内、WATER 51.2%→50.8%），
   真正的喂食通道是全 T3 水队（冰偏置队 WATER(6) 1.5%/s × 六只高血量旗舰），
   故修机制不砍数值：1/2 费水系载体治疗全额保留；
3. 虫群围猎 (1)(2)(4)(6) 四档：虫是唯一「每只登场都是负资产」的属性
   （随机局每带一只虫胜率约 -10pp），补偿必须从第一只虫开始兑现——
   78% 的虫登场发生在单虫队，(2) 起步等于补偿落空。档位阶梯自此表内自定义
   （tier_of 带 key 走表内档位，默认仍全局 (2)(4)(6)，向后兼容）。
"""

from collections import defaultdict
from typing import Dict, List, Optional

# ---- 模块级开关（模式照抄 data.EFF_* / MELEE_*，默认关，主线裁定后翻默认）----
# 由 sim/experiment_synergy.py 切换；combat.Battle 初始化时读取。
# 2026-09-14 翻开默认（用户批准）：前置证据见 reports/m2-economy-2026-09-13.md
# 的 S3 联动臂（羁绊关时 L2 定向买棋名次 4.98 劣于 L1 2.87，开时 4.35 显形价值）
# 与 s3-synergy-2026-09-13.md 的翻开条件核对。历史实验已各自钉住关态保复现。
SYNERGIES_ON = True


def synergies_on() -> bool:
    return SYNERGIES_ON


# ---- 17 系羁绊表 ----
# tiers: {档位: {效果名: 该档总值}}。效果词表（全部复用现有结算维度）：
#   hp         全队最大 HP +%（同时回等量当前 HP）
#   defense    全队物防&特防 +%
#   sp_defense 全队特防 +%（岩壁光环：针对特攻手）
#   atk        全队攻击&特攻 +%
#   speed      全队攻速 +%（加法叠后一次性除进 attack_interval）
#   dmg        全队造成伤害 +%
#   ult_dmg    全队大招伤害 +%
#   dr         全队受伤减免 %（加法叠，封顶 60%）
#   heal       全队每秒回复 最大HP %（combat 每 1s 一跳）
#   energy     全队回能 +%（普攻命中与受击两条回能路都吃）
#   ult_cap    单次大招承伤上限（≤ 目标最大 HP 的该比例；跨系取最小）
SYNERGY_TABLE: Dict[str, dict] = {
    # 深池平效区（人口 >=8：效果刻意平）
    "POISON": {   # 23 只，全池最深：近乎常驻，数值必须最小
        "theme": "瘴气侵蚀", "tiers": {
            2: {"dmg": 0.04},
            4: {"dmg": 0.07, "ult_dmg": 0.04},
            6: {"dmg": 0.10, "ult_dmg": 0.08}}},
    "WATER": {    # 18 只；旗舰机制=治疗（S3 指定），深池所以量级压平：
        # 实验定稿 0.5/1.0/1.5%/s 纯治疗（无减伤 rider）——2.4%/s 会把
        # 拉普拉斯水系队喂到 96-98%（见 reports/s3-synergy-2026-09-13.md）。
        # 2026-09-14 修订：数值不动，改由治疗衰减机制管住「全 T3 水队」
        # 的喂食通道（HEAL_TIER3_MULT：3 费旗舰治疗减半，1/2 费全额）——
        # 随机局对照证明治疗对随机水队 ~无关胜负，砍数值只会误伤普通水队
        "theme": "治愈之泉", "tiers": {
            2: {"heal": 0.005},
            4: {"heal": 0.010},
            6: {"heal": 0.015}}},
    "FLYING": {   # 12 只
        "theme": "顺风滑翔", "tiers": {
            2: {"speed": 0.06},
            4: {"speed": 0.12, "dmg": 0.04},
            6: {"speed": 0.18, "dmg": 0.08}}},
    "NORMAL": {   # 9 只；万金油=无尖刺的全面板
        "theme": "齐心", "tiers": {
            2: {"hp": 0.06},
            4: {"hp": 0.12, "defense": 0.05},
            6: {"hp": 0.18, "defense": 0.10}}},
    # 中池区（6-9 只：主题鲜明，量级中等）
    "GRASS": {    # 9 只，防守画像 5 弱 4 抗 → 补偿型
        "theme": "坚韧再生", "tiers": {
            2: {"dr": 0.06},
            4: {"dr": 0.10, "heal": 0.005},
            6: {"dr": 0.15, "heal": 0.010}}},
    "FIRE": {     # 8 只；进攻端=大招乘区
        "theme": "烈焰过载", "tiers": {
            2: {"ult_dmg": 0.10},
            4: {"ult_dmg": 0.18, "dmg": 0.04},
            6: {"ult_dmg": 0.26, "dmg": 0.08}}},
    "FIGHTING": { # 6 只；面板爆发（物攻手主场）
        "theme": "斗气全开", "tiers": {
            2: {"atk": 0.08},
            4: {"atk": 0.14, "speed": 0.06},
            6: {"atk": 0.20, "speed": 0.12}}},
    "PSYCHIC": {  # 6 只；旗舰机制=回能（S3 指定）
        "theme": "精神洪流", "tiers": {
            2: {"energy": 0.15},
            4: {"energy": 0.28},
            6: {"energy": 0.45, "ult_dmg": 0.10}}},
    # 浅池补偿区（<=6 只，或防守画像吃亏：机制更强）
    "BUG": {      # 7 只且全是弱单位（早期虫）→ 补偿型。2026-09-14 修订：
        # (1) 起步 + (2) 转韧性（hp）。旧表 (2)s6+d3 与深池平效区几乎同档，
        # 「补偿」未兑现（随机局 BUG 43.7% 垫底；单虫队占虫登场的 78%，
        # (2) 起步对它们是零补偿）。新档位取最高档语义不变；
        # hp 档实测比纯攻速/伤害更抬虫队（虫是近战肉盾位，多挨一刀就是价值）。
        # 2026-09-14 平衡 pass 追加 (1) hp 0.06：C-sym 突进 0.60→0.62 的近战
        # 时序修订侵蚀虫队 ~1pp（46.9→46.0%，同种子同阵容归因），(1) 档加
        # 韧性补回 47.6%（单虫队占虫登场 78%，补偿就该落在 (1) 档）
        "theme": "虫群围猎", "tiers": {
            1: {"speed": 0.05, "dmg": 0.03, "hp": 0.06},
            2: {"speed": 0.10, "dmg": 0.05, "hp": 0.12},
            4: {"speed": 0.16, "dmg": 0.09, "hp": 0.18, "heal": 0.003},
            6: {"speed": 0.22, "dmg": 0.13, "hp": 0.24, "heal": 0.006}}},
    "ELECTRIC": { # 5 只 → 补偿型；旗舰机制=攻速（S3 指定）
        "theme": "雷光疾走", "tiers": {
            2: {"speed": 0.12},
            4: {"speed": 0.22, "energy": 0.10},
            6: {"speed": 0.35, "energy": 0.20}}},
    "ROCK": {     # 6 只（与地面完全同池）；特防纸欠账 → 特防光环
        "theme": "岩壁", "tiers": {
            2: {"sp_defense": 0.12},
            4: {"sp_defense": 0.24, "hp": 0.06},
            6: {"sp_defense": 0.36, "hp": 0.12}}},
    "GROUND": {   # 8 只（其中 6 只即岩池）；欠账② → 大招承伤上限
        "theme": "大地缓冲", "tiers": {
            2: {"dr": 0.04},
            4: {"dr": 0.04, "ult_cap": 0.60},
            6: {"dr": 0.08, "ult_cap": 0.40}}},
    "STEEL": {    # 2 只（小磁怪/三合一磁怪）：当前只能到 (2)
        "theme": "钢铁之躯", "tiers": {
            2: {"defense": 0.08},
            4: {"defense": 0.16},
            6: {"defense": 0.24, "dr": 0.06}}},
    "GHOST": {    # 3 只：当前只能到 (2)
        "theme": "灵异夜袭", "tiers": {
            2: {"ult_dmg": 0.10},
            4: {"ult_dmg": 0.20, "energy": 0.10},
            6: {"ult_dmg": 0.30, "energy": 0.20}}},
    "DRAGON": {   # 3 只：当前只能到 (2)
        "theme": "龙之威压", "tiers": {
            2: {"dmg": 0.08},
            4: {"dmg": 0.14, "defense": 0.06},
            6: {"dmg": 0.20, "defense": 0.12}}},
    "ICE": {      # 1 只（拉普拉斯）：防守画像 4 弱 1 抗该补偿，但现池唯一
        # 载体是强势单位 → 盯防条款（S3 §5）触发：2026-09-14 (2) 收紧
        # 4% → 2%。注：随机局合池 ICE 读数与 (2) dr 无关——池内仅拉普拉斯
        # 一只冰系，(2) 档在随机局不可达（需要 2 只冰载体）；其强度来自
        # 拉普拉斯本体 + WATER 协同，结构性修法 = 扩池加冰载体（S4 路线），
        # (4)(6) 为扩池预留，激活即重测
        "theme": "凝冰之躯", "tiers": {
            2: {"dr": 0.02},
            4: {"dr": 0.10, "hp": 0.08},
            6: {"dr": 0.16, "hp": 0.16}}},
    "DARK": {     # 0 只：表先立着（扩池即用），当前休眠
        "theme": "暗影反噬", "tiers": {
            2: {"ult_dmg": 0.10, "energy": 0.08},
            4: {"ult_dmg": 0.18, "dr": 0.06},
            6: {"ult_dmg": 0.26, "dr": 0.10}}},
}

THRESHOLDS = (2, 4, 6)
DR_CAP = 0.60  # 减伤合计封顶（防多系防御叠穿地板）

# 治疗衰减（2026-09-14 平衡修订）：heal 类羁绊效果对 3 费旗舰棋子的系数。
# 理由：治疗的受益方按「存活价值 × 血量」放大，天然偏向高血量强势单位——
# 随机局里 ~1HP/s 的治疗与胜负无关（清零对照读数见模块头），但全 T3 水队
# （六只高血量旗舰）会把 WATER(6) 1.5%/s 吃成显著续航。羁绊的补偿语义是
# 抬弱单位，故治疗对旗舰打折、对 1/2 费全额。1.0 = 关闭该机制（对照臂用）。
HEAL_TIER3_MULT = 0.5


def compute(comp: list) -> Dict[str, int]:
    """队伍羁绊计数：{属性: 棋子数}。双属性棋子供两个计数。"""
    counts: Dict[str, int] = defaultdict(int)
    for piece in comp:
        for t in piece.types:
            counts[t] += 1
    return dict(counts)


def tier_of(count: int, key: str = None) -> int:
    """计数 → 激活档位（0 = 未激活）。

    默认按全局阈值 (2)(4)(6)；带 key 时按该系表内自定义档位
    （2026-09-14 起 BUG 为 (1)(2)(4)(6)）。无 key 的旧行为完全不变。
    """
    rungs = THRESHOLDS
    if key is not None:
        spec = SYNERGY_TABLE.get(key)
        if spec:
            rungs = tuple(sorted(spec["tiers"]))
    tier = 0
    for th in rungs:
        if count >= th:
            tier = th
    return tier


def _aggregate(counts: Dict[str, int]) -> (dict, Optional[float]):
    """把各激活系的效果汇总成一张合并账（加法叠；ult_cap 取最小）。

    档位按各系表内自定义档位取（默认系仍是全局 (2)(4)(6)）。
    """
    agg: Dict[str, float] = defaultdict(float)
    caps = []
    for t, n in counts.items():
        spec = SYNERGY_TABLE.get(t)
        if not spec:
            continue
        tier = tier_of(n, t)
        if tier == 0:
            continue
        for eff, val in spec["tiers"][tier].items():
            if eff == "ult_cap":
                caps.append(val)
            else:
                agg[eff] += val
    return dict(agg), (min(caps) if caps else None)


def apply(units: List, comp: list) -> Dict[str, int]:
    """把激活羁绊施加到一队的 Unit 上（Battle 初始化时调用一次）。

    纯确定性：不抽 rng、不改事件流。返回实际生效的计数（调试用）。
    """
    counts = compute(comp)
    if not synergies_on() or not units:
        return counts
    agg, ult_cap = _aggregate(counts)
    heal = agg.get("heal", 0.0)
    for u in units:
        if agg.get("hp"):
            delta = int(u.max_hp * agg["hp"])
            u.max_hp += delta
            u.hp += delta
        if agg.get("defense"):
            u.defense += int(u.defense * agg["defense"])
            u.sp_defense += int(u.sp_defense * agg["defense"])
        if agg.get("sp_defense"):
            u.sp_defense += int(u.sp_defense * agg["sp_defense"])
        if agg.get("atk"):
            u.attack += int(u.attack * agg["atk"])
            u.sp_attack += int(u.sp_attack * agg["atk"])
        if agg.get("speed"):
            u.attack_interval /= 1.0 + agg["speed"]
        u.synergy_dmg = agg.get("dmg", 0.0)
        u.synergy_ult_dmg = agg.get("ult_dmg", 0.0)
        u.synergy_dr = min(agg.get("dr", 0.0), DR_CAP)
        # 治疗衰减（2026-09-14）：heal 对 3 费旗舰打折，1/2 费全额
        if heal:
            u.synergy_heal = heal * (HEAL_TIER3_MULT
                                     if u.piece.tier >= 3 else 1.0)
        else:
            u.synergy_heal = 0.0
        u.synergy_energy = agg.get("energy", 0.0)
        u.synergy_ult_cap = ult_cap
    return counts
