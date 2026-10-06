"""S5 装备系统 v1：8 组件 / 12 成品 / 仓库模型 / 合成 / 装备效果施加。

设计定稿见 docs/07-items.md（概念稿）、S2 §1.5（2026-09-14 修订：
通信进化唯一通道 = 进化石）、S4 §5.2（野怪轮掉落留 S5）。落地语义
（v1 裁定，读数见 reports/s5-items-2026-09-14.md；平衡修订见
reports/items-balance-2026-09-14.md）：

- 两层结构：野怪轮掉组件 → 两两合成成品（允许同组件×2，如疾风羽）；
- 每单位 1 格（OwnedPiece.item，None = 空手）；卖棋自动卸回仓库；
  3 合 1 进化继承装备（shop.try_combine）；
- 掉落（docs/07 §1「每 5 轮野怪轮保底 1 组件，掉落表按玩家血量加权
  （落后方双倍权重）」的 v1 读法）：每位存活玩家每野怪轮保底 1 组件
  （组件种类随机），另加发 2 件按血量加权分发（hp 不高于存活均值者
  权重×2）——「按人头保底 + 加发追赶」双轨。全部随机走 pve 子流的
  掉落 counter 段（PVE_DROP_COUNTER 起，与掉金的 counter=i 互不位移）；
- 装备效果只复用现有结算维度（照 S3 synergy_* 的中性默认模式加 item_*
  字段，combat.Unit 默认 0/None）：攻击/特攻、攻速、回能、减伤、
  系别伤害、回血、闪避、披带。本模块零随机、零 IO；
- 进化石（任意两组件的兜底配方）：装备在通信进化族中段形态
  （勇基拉/豪力/鬼斯通，S2 §1.5 名单）上即触发通信进化（入场即进化，
  装备不消耗）；**通信进化的唯一通道**（2026-09-14 用户裁定：原
  「3 合 1 持装备」门删除——50 局仅触发 1 次、与进化石实质互斥）；
  8s 冷却是渲染语义，sim 按「每 bot 每局一次」限；
- 幸运蛋：持有者每轮 +1 金，全场（8 bot 合计）限 2 件；
- 天气石：S11 天气未实装，v1 折算为减伤 8%（S11 落地后改为主动改一次
  天气，docs/05 联动条款）；专爱头巾的「锁定当前目标」在自动战斗里
  已由目标滞回近似（combat._target），v1 不加独立结算（docs/07 §6-2
  开放问题）。

配方冲突裁定：docs/07 成品表里「剩饭 = 防+铃」与「幸运蛋 = 铃+防」
同一对组件（表格自纠错留下的撞车）——按纠错后的剩饭配方执行，幸运蛋
改拿被划掉的「头带+贝壳铃」组合（均为经济向组件，语义自洽）。

2026-09-14 平衡修订（读数见 reports/items-balance-2026-09-14.md，
同种子前后对照）：
- 天气石配方 伤组件+硬石（3 对）→ **硬石头×2 / 磁铁+硬石头**：v1 的
  三对宽配方让它吸走所有「缺磁铁的伤组件」成为第一霸主（快照口径
  17-19%，围巾+天气家族 44.7%）。v2 只留硬石头×2 又过窄（4.6% 低于
  5% 底线）——终版改成「守卫最严的两种防御料的余料折算」：剩饭/
  披带/亮粉先吃硬石头，天气石只从真余料（硬石头×2 或落单磁铁×
  硬石头）里出，伤组件全部让给围巾；
- 黄围巾加 **雷之石碎片×2** 配方：电系棋子稀缺（池内 5 只），单靠
  「碎片+磁铁」+同系门时黄围巾终局 3.7-3.8% 低于 5% 底线；双碎片
  给电系承诺型阵容一个碎片出口（同组件合成先例同上）。
"""

from typing import Dict, List, Optional, Tuple
import tactics

# ---- 模块级开关（模式照抄 synergy.SYNERGIES_ON，默认关，主线裁定后翻开）----
# 由 sim/experiment_items.py 切换臂；match 层（掉落/幸运蛋/通信进化门）与
# bots 层（合成/装备策略）读它。战斗层不读开关：comp 里出现 (Piece, item)
# 二元组就施加——prototype 传裸 Piece，天然无装备。
ITEMS_ON = True  # 2026-09-14 成套翻开（用户批准；见 reports/flip-all-baseline-2026-09-14.md）


def items_on() -> bool:
    return ITEMS_ON


# ---- 组件（8 种，野怪轮掉落；docs/07 §1）----
# 顺序即合成兜底时的消费序（确定性，宪法 2.2）
COMPONENT_ORDER: Tuple[str, ...] = (
    "band",        # 力量头带（物攻倾向）
    "hardstone",   # 硬石头（物防倾向）
    "magnet",      # 磁铁线圈（特攻倾向）
    "shoes",       # 加速鞋（攻速倾向）
    "bell",        # 贝壳铃（回能倾向）
    "charcoal",    # 木炭（火伤+）
    "mysticwater", # 神秘水滴（水伤+）
    "spark",       # 雷之石碎片（电伤+）
)
COMPONENT_NAMES: Dict[str, str] = {
    "band": "力量头带", "hardstone": "硬石头", "magnet": "磁铁线圈",
    "shoes": "加速鞋", "bell": "贝壳铃", "charcoal": "木炭",
    "mysticwater": "神秘水滴", "spark": "雷之石碎片",
}

# ---- 成品（12 种；docs/07 §2）----
# pairs：该成品的具体配方（组件对，同组件允许 ×2）；None = 任意两组件
# （进化石兜底）。效果字段 = items.apply_to_unit 写进 Unit 的维度。
FINISHED: Dict[str, dict] = {
    "healing_needle": {"name": "封疗针", "pairs": (("band", "charcoal"),),
                       "healing_reduction": 0.60, "duration": 8.0},
    "leftovers":     {"name": "剩饭", "pairs": (("hardstone", "bell"),),
                      "heal": 0.015},                    # 每秒回 1.5% maxHP
    "sash":          {"name": "气势披带", "pairs": (("band", "hardstone"),),
                      "sash": True},                     # 致命伤保留 1 HP（一次/场）
    "choice_band":   {"name": "专爱头巾", "pairs": (("band", "magnet"),),
                      "atk": 0.35},                      # 攻/特攻 +35%（锁目标 v1 不建模）
    "bright_powder": {"name": "亮粉", "pairs": (("hardstone", "shoes"),),
                      "dodge": 0.15},                    # 被击 15% 闪避
    "focus_lens":    {"name": "聚光镜", "pairs": (("magnet", "bell"),),
                      "ult_dmg": 0.25},                  # 大招 +25%
    "swift_feather": {"name": "疾风羽", "pairs": (("shoes", "shoes"),),
                      "speed": 0.25},                    # 攻速 +25%（同组件合成）
    "scarf_fire":    {"name": "红围巾", "pairs": (("charcoal", "magnet"),),
                      "type_dmg": {"FIRE": 0.30}},       # 火系伤 +30%
    "scarf_water":   {"name": "蓝围巾", "pairs": (("mysticwater", "magnet"),),
                      "type_dmg": {"WATER": 0.30}},
    "scarf_electric": {"name": "黄围巾",
                       "pairs": (("spark", "magnet"),
                                 ("spark", "spark")),
                       "type_dmg": {"ELECTRIC": 0.30}},
    "weather_stone": {"name": "天气石",
                      "pairs": (("hardstone", "hardstone"),
                                ("magnet", "hardstone")),
                      "dr": 0.08},                       # v1 折算减伤（S11 后改主动天气）
    "lucky_egg":     {"name": "幸运蛋", "pairs": (("band", "bell"),),
                      "gold_per_round": 1},              # 每轮 +1 金，全场限 2
    "evo_stone":     {"name": "进化石", "pairs": None,
                      "stone": True},                    # 通信进化 catalyst（不消耗）
}

# 进化石的通信进化名单（S2 §1.5：勇基拉→胡地、豪力→怪力、鬼斯通→耿鬼）
STONE_TARGETS: Dict[int, int] = {64: 65, 67: 68, 93: 94}

# 幸运蛋：每轮 +1 金；全场（全桌）同时存在上限
LUCKY_EGG_INCOME = 1
LUCKY_EGG_GLOBAL_CAP = 2

# 掉落：pve 子流的掉落 counter 段起点（与掉金 counter=i 隔离，互不位移）
PVE_DROP_COUNTER = 1024
# 每野怪轮的加发件数（按血量加权分发；人头保底之外）
PVE_BONUS_DROPS = 2


# ---- 配方查询 ----
def catalog(ruleset=tactics.BASE_RULESET):
    active = tactics.counters_enabled(ruleset)
    return {key: spec for key, spec in FINISHED.items()
            if (key != "healing_needle" or active or ruleset == 'arena_v1')
            and (key != "evo_stone" or ruleset != 'arena_v1')}


def _pair_lookup(ruleset=tactics.BASE_RULESET) -> Dict[Tuple[str, str], str]:
    """排序后的组件对 → 成品 key（进化石不在表内 = 兜底）。"""
    table: Dict[Tuple[str, str], str] = {}
    for key, spec in catalog(ruleset).items():
        for a, b in spec["pairs"] or ():
            table[tuple(sorted((a, b)))] = key
    return table


_PAIR_TABLE = _pair_lookup()


def craft_result(a: str, b: str, ruleset=tactics.BASE_RULESET) -> str:
    """两组件 → 成品 key：无特定配方的对子兜底为进化石。"""
    table = _pair_lookup(ruleset) if tactics.counters_enabled(ruleset) else _PAIR_TABLE
    return table.get(tuple(sorted((a, b))), "evo_stone")


# ---- 仓库模型 ----
class Inventory:
    """一名玩家的装备仓库：组件池 + 待装备成品。"""

    def __init__(self, ruleset=tactics.BASE_RULESET) -> None:
        self.ruleset = tactics.validate_ruleset(ruleset)
        self.components: Dict[str, int] = {c: 0 for c in COMPONENT_ORDER}
        self.finished: List[str] = []   # 待装备的成品 key（合成即完成）
        from techniques import ids_for
        self.techniques = dict.fromkeys(ids_for(self.ruleset), 0)

    def add_component(self, comp: str) -> None:
        assert comp in self.components, f"未知组件 {comp!r}"
        self.components[comp] += 1

    def total_components(self) -> int:
        return sum(self.components.values())

    def _consume(self, a: str, b: str) -> None:
        """按配方扣组件（同组件×2 需要库存 2）。"""
        self.components[a] -= 1
        self.components[b] -= 1
        assert min(self.components.values()) >= 0, "组件扣穿"

    def craftable(self, key: str) -> Optional[Tuple[str, str]]:
        """某成品当前是否可合成；可则返回一组配方（确定性取序最先者）。"""
        if key not in catalog(self.ruleset):
            return None
        if key == "evo_stone":
            return self._stone_pair()
        for pair in sorted(FINISHED[key]["pairs"]):
            a, b = pair
            need_b = 2 if a == b else 1
            if self.components[a] >= 1 and self.components[b] >= need_b:
                return pair
        return None

    def _stone_pair(self) -> Optional[Tuple[str, str]]:
        """进化石的对子选择：优先「无特定配方」的组件对（不拆特定成品），
        全都是特定对时按固定序取第一组可用对（组件不烂在仓库里）。"""
        avail = list(COMPONENT_ORDER)
        fallback = None
        for i in range(len(avail)):
            for j in range(i, len(avail)):
                a, b = avail[i], avail[j]
                if self.components[a] >= 1 and self.components[b] >= (2 if a == b else 1):
                    if fallback is None:
                        fallback = (a, b)
                    if craft_result(a, b, self.ruleset) == "evo_stone":
                        return (a, b)
        return fallback

    def craft(self, key: str, pair: Tuple[str, str]) -> None:
        self._consume(*pair)
        self.finished.append(key)


def craft_priority(pers_key: str, wants_stone: bool,
                   behind: bool = False) -> Tuple[str, ...]:
    """合成优先级表（人格差异 + 场景门，2026-09-14 平衡修订）。

    - 梭哈型先合攻击件，其余走默认序；
    - 气势披带补入两表（v1 漏排 = 终局 0 件的直接原因，见
      reports/items-balance-2026-09-14.md）；
    - behind（落后方，hp ≤ 存活均值）：幸运蛋提到最前——经济追赶件
      对落后方的价值最高（docs/03 §5 / docs/07 §1 追赶渠道），全场限 2
      仍由 lucky_ok 把关；
    - 亮粉/披带/剩饭排在围巾与天气石之前：防御件与围巾家族争硬石头，
      靠前吃料压缩「围巾+天气」家族占比（v1 快照口径 44.7% > 30% 线）。
    """
    base = (("choice_band", "swift_feather", "focus_lens",
             "sash", "scarf_fire", "scarf_water", "scarf_electric",
             "leftovers", "bright_powder", "weather_stone", "lucky_egg")
            if pers_key == "roller" else
            ("choice_band", "focus_lens", "sash", "leftovers",
             "bright_powder", "swift_feather",
             "scarf_fire", "scarf_water", "scarf_electric",
             "weather_stone", "lucky_egg"))
    if behind:
        base = ("lucky_egg",) + tuple(k for k in base if k != "lucky_egg")
    return ("evo_stone",) + base if wants_stone else base


def craft_best(inv: Inventory, priority: Tuple[str, ...], lucky_ok: bool = True,
               stone_ok: bool = True, stats: dict = None,
               gate=None) -> Optional[str]:
    """按优先级合成一件成品；组件够但无想要的特定配方时兜底进化石。

    lucky_ok：幸运蛋达全场上限时让位；stone_ok：没有通信进化目标或
    每局一次已用时不造进化石（组件留给后续特定配方，不烧成废石）。
    仓库里已有进化石时不重复造。返回合成的成品 key，无料可合返回 None。
    确定性（无随机）。

    附加参数（2026-09-14 平衡修订引入，默认关 = 行为与 v1 逐位一致）：
    - stats：逐成品合成统计（bots 传入常驻 dict）——calls 总调用数、
      made 合成数、no_pair「在优先序内但缺料」次数、gated「可合但被
      场景门拦下」次数、shadow「本次合成后仍可合 = 被优先序压住」次数；
    - gate：场景门 key->bool（如围巾「同系才合」）；None = 全放行。
    stats/gate 只读不改决策路径外的任何状态。
    """
    def bump(kind: str, key: str) -> None:
        if stats is not None:
            stats[kind][key] = stats[kind].get(key, 0) + 1

    if stats is not None:
        stats["calls"] = stats.get("calls", 0) + 1
    has_stone = "evo_stone" in inv.finished
    made = None
    for key in priority:
        if key == "lucky_egg" and not lucky_ok:
            continue
        if key == "evo_stone":
            if not stone_ok or has_stone:
                continue
            pair = inv._stone_pair()
            if pair is not None:
                inv.craft("evo_stone", pair)
                made = "evo_stone"
                break
            continue
        pair = inv.craftable(key)
        if pair is None:
            bump("no_pair", key)
            continue
        if gate is not None and not gate(key):
            bump("gated", key)
            continue
        inv.craft(key, pair)
        made = key
        break
    if made is None and (stone_ok and not has_stone
                         and "evo_stone" not in priority
                         and inv.total_components() >= 2):
        pair = inv._stone_pair()   # 优先序里没排进化石 → 兜底（有目标才烧）
        if pair is not None:
            inv.craft("evo_stone", pair)
            made = "evo_stone"
    if made is not None:
        bump("made", made)
        if stats is not None:   # 优先序阴影：合成后仍可合且过门的 = 被压住
            for key in priority:
                if key == made or key == "evo_stone":
                    continue
                if key == "lucky_egg" and not lucky_ok:
                    continue
                if inv.craftable(key) and (gate is None or gate(key)):
                    bump("shadow", key)
    return made


# ---- 装备效果施加（combat.Unit 的 item_* 维度，S3 synergy_* 同模式）----
def apply_to_unit(u, key: str) -> None:
    """把成品效果写进一个战斗 Unit（Battle._deploy 的施加点调用）。

    面板/攻速类直接改数值（与 synergy.apply 同法），乘区/机制类写
    item_* 字段由 combat 结算点消费。零随机。
    u.item_key = 载体归属标记（combat 不消费；bots 装备策略与
    experiment_items 逐成品测量用，空手单位无此属性）。
    """
    spec = FINISHED[key]
    u.item_key = key
    atk = spec.get("atk", 0.0)
    if atk:
        u.attack += int(u.attack * atk)
        u.sp_attack += int(u.sp_attack * atk)
    if spec.get("speed"):
        u.attack_interval /= 1.0 + spec["speed"]
    u.item_ult_dmg = spec.get("ult_dmg", 0.0)
    u.item_dr = spec.get("dr", 0.0)
    u.item_heal = spec.get("heal", 0.0)
    u.item_energy = spec.get("energy", 0.0)
    u.item_dodge = spec.get("dodge", 0.0)
    u.item_sash = bool(spec.get("sash", False))
    if spec.get("type_dmg"):
        u.item_type_dmg = dict(spec["type_dmg"])


# ---- 幸运蛋 / 掉落（match 层调用）----
def lucky_egg_income(bot) -> int:
    """持有幸运蛋的棋子数 × 每轮金币（match 收入步骤调用）。"""
    return LUCKY_EGG_INCOME * sum(
        1 for o in bot.all_pieces() if o.item == "lucky_egg")


def lucky_egg_count(bots) -> int:
    """全桌现存幸运蛋数（已装备 + 待装备），合成上限 LUCKY_EGG_GLOBAL_CAP 用。"""
    n = 0
    for b in bots:
        n += sum(1 for o in b.all_pieces() if o.item == "lucky_egg")
        n += b.inventory.finished.count("lucky_egg")
    return n


def drop_weights(alive) -> List[float]:
    """掉落权重：hp 不高于存活均值（落后方）×2（docs/07 §1 追赶条款）。"""
    mean_hp = sum(b.hp for b in alive) / len(alive)
    return [2.0 if b.hp <= mean_hp else 1.0 for b in alive]


if __name__ == "__main__":   # 自检：配方覆盖 / 兜底 / 合成确定性
    inv = Inventory()
    for c in COMPONENT_ORDER:
        inv.add_component(c)
    assert craft_result("hardstone", "bell") == "leftovers"
    assert craft_result("band", "bell") == "lucky_egg"      # 撞车裁定后的幸运蛋
    assert craft_result("shoes", "shoes") == "swift_feather"
    assert craft_result("band", "charcoal") == "evo_stone"  # 无特定对 → 兜底
    # 全组件各 1：合成 3 件（专爱头巾 + 剩饭 + 进化石兜底），余 2 个单组件等配对
    made = []
    while True:
        key = craft_best(inv, craft_priority("balanced", False))
        if key is None:
            break
        made.append(key)
    assert made == ["choice_band", "leftovers", "evo_stone"], made
    assert inv.total_components() == 2 and "evo_stone" in inv.finished
    # 梭哈型优先攻击件：band+magnet 在场先出专爱头巾
    inv2 = Inventory()
    for c in ("band", "magnet", "hardstone", "bell"):
        inv2.add_component(c)
    assert craft_best(inv2, craft_priority("roller", False)) == "choice_band"
    # 披带补入优先序（v1 漏排修复）：band+hardstone 且无 magnet → 气势披带
    inv3 = Inventory()
    for c in ("band", "hardstone"):
        inv3.add_component(c)
    assert craft_best(inv3, craft_priority("balanced", False)) == "sash"
    # 场景门：无同系棋子时围巾被拦下（组件不烧，落到下一优先项）
    inv4 = Inventory()
    for c in ("charcoal", "magnet", "bell"):
        inv4.add_component(c)
    no_fire = lambda k: k != "scarf_fire"   # noqa: E731  模拟「板上无火系」
    assert craft_best(inv4, craft_priority("balanced", False),
                      gate=no_fire) == "focus_lens"
    # 落后方：幸运蛋提前（band+bell 在手时优先出蛋）
    inv5 = Inventory()
    for c in ("band", "bell"):
        inv5.add_component(c)
    assert craft_best(inv5, craft_priority("balanced", False, behind=True)) \
        == "lucky_egg"
    print(f"items 自检通过：{len(FINISHED)} 成品 / {len(COMPONENT_ORDER)} 组件，"
          f"合成序 {made}（含披带/场景门/落后方蛋检查）")
