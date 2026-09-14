"""S10 组合技 A：齐射（羁绊最高档的开场组合招）——数值臂 v1（2026-09-14）。

机制（docs/04-combo-moves.md §2.A，推荐首发）：某属性羁绊计数达到该系
**最高档**时，开战 t=0（deploy 后、主循环前）全队各向最近敌人放一发该
属性的迷你攻击——羁绊高阶的「仪式感回报」。

触发档统一规则 = 各系最高档：sim/synergy.py 现表 17 系最高档**全部落
(6)**（BUG 的自定义档 (1)(2)(4)(6) 最高档同样是 (6)，(1) 起步只改低档
补偿、不改仪式回报门槛——故虫系齐射按 (6) 适用，与「最高档」统一规则
一致）；docs/04 §2.A 写的电(6)/水(6)/火(6) 经 S3 平衡修订后档位未变。
现池凑满 (6) 需 6 单位全员供该属性（双属性算双份），只有深/中池属性
可达（水/毒/飞/普/草/火/斗/超/虫/岩/地/电，电 5 种需重复 1 只）；
钢/幽灵/龙/冰/恶当前不可达 = 齐射天然跟随扩池解锁，无需另设开关。

每队每场**至多一轮**齐射（docs/04 §2.A 单数语义「该属性的组合招」）：
双最高档（如 隆隆岩×6 = ROCK(6)+GROUND(6)）只触发计数最高的一系，
并列按属性名序取先。依据 = 实验读数（reports/s10-combo-a-2026-09-14.md）：
连发两轮对克制面弱的队（岩地 vs 火/草/电）读出齐射伤害占比中位 47.5%、
场均 2.4 个 t=0 击杀——远超 ≤12% 健康线；单轮后最重对位回落到中位
16.0%（仍是当前最重对位，v2 护栏候选见报告 §5），规定臂（电(6) vs
零羁绊）中位 6.0% / 最大 11.9% 达标，「仪式感 > 数值」成立。

v1 数值骨架（自定，依据）：
- 威力 = 各自招牌招威力 × COMBO_POWER_FRAC(40%)：一发齐射 ≈ 0.4×招牌，
  量级 ≤ 一次无属性普攻（BASIC_POWER=40），全队六发合计 ≈ 2-3 发普攻
  ——「仪式感 > 数值」的开场：双方都触发时互相抵消大半（docs/04 §2.A
  的设计意图，实验读数见 reports/s10-combo-a-2026-09-14.md）；
- 属性 = 齐射系（非使用者本系）：WATER(6) 的非水单位也放水弹——全员
  齐射是队伍仪式；STAB 只对本系单位生效；
- 必中：不掷命中骰/闪避骰（开场演出不吞 miss 反高潮）；免疫（0 倍）
  目标走 _damage 的 1 点保底、再过减伤链可归零（读数：电齐射对纯
  地面队落 0 伤，主题正确）；伤害随机骰（0.85~1.0）仍掷、走本场
  battle 子流（确定性条款不受影响）；
- 不回能不耗能：不走 ENERGY_PER_ATTACK / ENERGY_PER_HIT_TAKEN 两条
  通道——齐射是回报不是起手引擎，不加速大招循环；
- 结算复用 combat._final_damage 全链：克制 × 天气 × 羁绊乘区 × 大招
  承伤上限 × 减伤 × 装备乘区（「每发命中走既有 attack 事件、复用结算
  链」的接线要求）。

接线（combat.Battle）：run() 开头 deploy 事件之后、主循环之前解算；
事件流新增 (0.0, "combo", team, 属性, 名称) 一条 + 每发一条既有
(0.0, "attack", atk, def, dmg)——渲染端零特判（宪法 2.6），演出 =
§4.9 迷你特效串按属性直接复用（本期只做事件+数值，渲染端后续接）。

边界：本模块零随机、零 IO（威力/属性开战前定死）；bot 不感知齐射
（v1 纯战斗层，不碰 match/bots）。COMBOS_ON 默认 False（S3/S11/S12
同模式），主线裁定后翻转。
"""

from data import BASIC_POWER
import synergy

# ---- 模块级开关（模式照抄 synergy.SYNERGIES_ON / status.STATUS_ON）----
# 由 sim/experiment_combo.py 切换；combat.Battle.run() 开头读取。
COMBOS_ON = True  # 2026-09-14 成套翻开（用户批准；见 reports/flip-all-baseline-2026-09-14.md）


def combos_on() -> bool:
    return COMBOS_ON


# 组合技名（docs/04 §4.3：要占「招式名」，演出切镜横幅用）。
# 电/水/火/虫四系名定稿自 docs/04 §2.A 与任务书；其余 13 系为 v1 占位名，
# 按各自羁绊主题（sim/synergy.py SYNERGY_TABLE 的 theme）取义，定稿随渲染端横幅审。
COMBO_NAMES = {
    "ELECTRIC": "雷霆万钧",   # 电：docs/04 §2.A 定稿
    "WATER":    "潮汐",       # 水：docs/04 §2.A 定稿
    "FIRE":     "烈焰地带",   # 火：docs/04 §2.A 定稿
    "BUG":      "群虫踊击",   # 虫：任务书定稿（主题「虫群围猎」）
    "NORMAL":   "万众一心",   # 主题「齐心」
    "FLYING":   "疾风阵列",   # 主题「顺风滑翔」
    "GRASS":    "千藤缠绕",   # 主题「坚韧再生」
    "POISON":   "瘴气领域",   # 主题「瘴气侵蚀」
    "FIGHTING": "斗魂风暴",   # 主题「斗气全开」
    "PSYCHIC":  "精神海啸",   # 主题「精神洪流」
    "ROCK":     "岩壁崩落",   # 主题「岩壁」
    "GROUND":   "大地激震",   # 主题「大地缓冲」
    "STEEL":    "钢铁洪流",   # 主题「钢铁之躯」
    "GHOST":    "百鬼夜行",   # 主题「灵异夜袭」
    "DRAGON":   "龙鳞风暴",   # 主题「龙之威压」
    "ICE":      "极寒领域",   # 主题「凝冰之躯」
    "DARK":     "暗夜降临",   # 主题「暗影反噬」
}

# 齐射威力 = 招牌招威力 × 该比例（数值骨架依据见模块头）
COMBO_POWER_FRAC = 0.4


def volley_types(comp: list) -> list:
    """该 comp 达到齐射门槛的属性列表（计数 ≥ 该系最高档），按属性名排序。

    诊断/实验用（报告「哪些系够格」）；实际放哪一轮看 volley_pick。
    """
    counts = synergy.compute(comp)
    out = []
    for t in sorted(counts):
        spec = synergy.SYNERGY_TABLE.get(t)
        if not spec:
            continue
        if counts[t] >= max(spec["tiers"]):   # 各系最高档（现表全为 6）
            out.append(t)
    return out


def volley_pick(comp: list):
    """实际触发的一系：够格属性中计数最高者，并列按属性名序取先。

    每队每场至多一轮（连发两轮的读数依据见模块头）。返回 None = 不触发。
    """
    qualified = volley_types(comp)
    if not qualified:
        return None
    counts = synergy.compute(comp)
    return max(qualified, key=lambda t: counts[t])


def opening_volley(units: list, comp: list, dex) -> list:
    """一支队伍的齐射指令（cast-like），Battle 在 deploy 后 t=0 解算。

    返回 [{"type", "name", "shots": [(unit, power), ...]}]：至多一条
    （volley_pick 选出的系）；shots 的目标不由本函数定——只见己方，
    由 Battle 按各自最近敌人（曼哈顿距离，同 _target 的 (dist, idx) 键）
    解析。power = 该单位招牌招威力 × COMBO_POWER_FRAC；无招牌招（无威力
    招）按 BASIC_POWER 折算，保底 1。
    """
    t = volley_pick(comp)
    if t is None:
        return []
    shots = []
    for u in units:
        move = dex.moves.get(u.piece.move_id) if u.piece.move_id else None
        base = move.get("power") if move else None
        power = max(1, int((base if base else BASIC_POWER) * COMBO_POWER_FRAC))
        shots.append((u, power))
    return [{"type": t, "name": COMBO_NAMES.get(t, t), "shots": shots}]
