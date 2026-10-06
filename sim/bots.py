"""M2 机器人训练家：L0-L3 能力分层 × 四组人格参数（docs/03 §4）。

设计要点（同一引擎、参数化人格，不是七套代码）：
- 能力分层叠加：L0 随机买 → L1 规则经济（利息优先、按曲线升人口、买当前
  阵容族）→ L2 羁绊感知（朝主羁绊定向买、3 合 1 优先、卖偏离羁绊的棋）
  → L3 对位摆位（坦克前排远程后排 + 弱化版列对位）；
- 人格参数（docs/03 §4.2）：攒钱型/梭哈型/平衡型/跟牌型 = 攒钱上限、
  刷新预算、升级节奏、换阵容容忍 四轴；
- 摆位（L1 起）经 comp 列表次序表达：combat.Battle layout="back" 按列表
  顺序从己方后排向前排填充 → 列表头 = 远程后排、列表尾 = 坦克前排；
  L3 追加列对位（己方主 C 避开对手主 C 列、主坦对齐对手主 C 列），
  由 match 在配对后注入对手阵容再调一次（对手也走 back 布阵）；
- 濒死（HP<=30）与决赛圈（R25+）自动放松存款上限（保命优先）。

决策零 IO；随机只走传入 rng（宪法 2.2）。单轮决策为纯列表/字典操作，
实测 << 10ms（C 移植余量，读数见 experiment_match）。
"""

import random
from data import pokedex
import economy
import items as items_mod   # S5 装备：仓库 + 合成/装备策略（L1+）
import skills
import synergy
import shop as shop_mod
from profiles import effective_range
import profiles
import tactics
from combat import COLS  # C-sym 棋盘列数（docs/10 §1.5）：列对位随棋盘常量走
from shop import OwnedPiece, SharedPool, try_combine

BENCH_SIZE = 6       # 备战席 6 格（docs/10 §1.1 C-sym 设备裁定；2026-09-14
                     # 平衡 pass：从 TFT 口径 9 格对齐——bot 与 Demo 玩家同规则）
BUY_THRESHOLD = 500  # L2 买入分界：复制件/目标羁绊/高 BST 任一过线才买
LATE_GAME_ROUND = 18  # 后期：全体追加刷新预算

# ---- 人格参数表（docs/03 §4.2，四轴）----
# reserve_*：存款爬坡（start + (轮-1)*gain，封顶 cap）= 花钱地板（保利息）；
# pivot_round/late_cap：到轮后存款上限降为 late_cap（攒钱型中期把财富变现，
# 否则「死时一屁股钱」——首版读数实证，见 reports/m2-economy-*.md）；
# refresh_max：每轮主动刷新预算上限；level_mode：升级节奏；
# pivot_tol：换主羁绊需要的领先幅度（换阵容容忍）。
PERSONALITIES = {
    "saver":    {"label": "攒钱型·火箭队干部", "reserve_start": 10,
                 "reserve_gain": 5, "reserve_cap": 50, "pivot_round": 12,
                 "late_cap": 32, "refresh_max": 1,
                 "level_mode": "slow", "pivot_tol": 0},
                 # late_cap 30→32（2026-10-04 R2 节奏二调）：×2.2 攻速 +
                 # 回能补偿下 saver 两种子 32%/39% 冠军又起——再收一档
                 # 变现期（20→30→32 的同手法第三步）
                 # late_cap 20→30（2026-09-14 平衡 pass）：变现期更晚兑现——
                 # 读数里 20 的 saver 决赛圈 40% 冠军碾压全场，30 压回 33% 且
                 # 人格极差 1.29→0.80（experiment_matchbalance v4 臂）
    "roller":   {"label": "梭哈型·格斗道馆主", "reserve_start": 4,
                 "reserve_gain": 2, "reserve_cap": 10, "pivot_round": 99,
                 "late_cap": 10, "refresh_max": 6,
                 "level_mode": "fast", "pivot_tol": 2},
    "balanced": {"label": "平衡型·博士系", "reserve_start": 8,
                 "reserve_gain": 3, "reserve_cap": 30, "pivot_round": 16,
                 "late_cap": 16, "refresh_max": 2,
                 "level_mode": "curve", "pivot_tol": 1},
    "copycat":  {"label": "跟牌型·模仿少女", "reserve_start": 8,
                 "reserve_gain": 2, "reserve_cap": 20, "pivot_round": 14,
                 "late_cap": 12, "refresh_max": 2,
                 "level_mode": "follow", "pivot_tol": 1},
}

# 开局投放（docs/03 §4.4 难度投放：3×L1+3×L2+1×L3；
# 8 人局第 8 席 = L0 教学期沙包，顶替单机模式中玩家的席位）
LINEUP = {7: [1, 1, 1, 2, 2, 2, 3], 8: [1, 1, 1, 2, 2, 2, 3, 0]}


def assign_personalities(n_bots: int, rng: random.Random) -> list:
    """人格发牌：尽量均匀（8 人=每种 2 个；7 人=2/2/2/1），顺序由 rng 洗。"""
    keys = sorted(PERSONALITIES)
    deck = [keys[i % len(keys)] for i in range(n_bots)]
    rng.shuffle(deck)
    return deck


def main_types(comp: list) -> list:
    """一套阵容的羁绊计数降序表 [(属性, 数), ...]（确定性排序）。"""
    counts = {}
    for owned in comp:
        for t in owned.piece.types:
            counts[t] = counts.get(t, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def _species_power(species_id: int) -> int:
    """买入、卖出和上场共用的单体底价，含启用中的档案倍率。"""
    import profiles as profiles_mod
    return int(pokedex().bst(species_id)
               * profiles_mod.bot_value_mult(species_id))


def _can_combine(species_id: int) -> bool:
    """物种是否有 3 合 1 路径；池暂时缺货仍可保留进化进度。"""
    return (species_id not in shop_mod.TRADE_EVOLUTIONS
            and pokedex().next_evolution(species_id) is not None)


def power(owned: OwnedPiece, target_types=()) -> int:
    """棋子战力估值：BST × 档案倍率（买入/上场/卖出/对位共用底价）。

    目标羁绊不直接加价：首版读数 L2 给目标棋 +150~+250 上场偏置，
    会用 380 BST 的羁绊棋挤掉 500+ 的散件，名次反而倒挂——
    羁绊的价值由 L2 的买入定向 + 上场时的成堆奖励（_board_score）兑现。
    R1 单体档案（docs/13 §5）：建档棋子按档案价值乘数加价——
    溅射/斩杀/坦度原语是 BST 表达不了的强度，不加价 bot 会贱卖主角。
    """
    value = _species_power(owned.piece.species_id)
    return int(value * (1, 1.6, 2.5)[getattr(owned.piece, 'star', 1) - 1])


class Bot:
    """一名机器人训练家：全部状态 + 一轮决策（买/卖/刷新/升级/摆位）。"""

    def __init__(self, seat: int, ability: int, pers_key: str,
                 pool: SharedPool, templates: dict) -> None:
        self.seat = seat
        self.ability = ability
        self.pers = PERSONALITIES[pers_key]
        self.pers_key = pers_key
        self.name = f"{seat}·{self.pers['label'][:3]}L{ability}"
        self.gold = economy.START_GOLD
        self.hp = economy.START_HP
        self.level, self.xp = 1, 0
        self.streak = 0            # + 连胜 / - 连败 / 0
        self.board: list = []      # 上场（已按摆位次序排序）
        self.bench: list = []      # 备战
        self.shop = shop_mod.Shop(pool, templates)
        self.pool = pool
        self.templates = templates
        self.target_types: tuple = ()   # L2/copycat 的主羁绊目标（确定性元组）
        self.alive = True
        self.rank = None
        self.last_damage = 0
        # ---- 统计（experiment/match 汇总用）----
        self.gold_curve: list = []
        self.pop_curve: list = []
        self.synergy_curve: list = []     # 每轮 (主羁绊属性, 数)
        self.synergy_formed_round = None  # 首次任一属性数 >= 4 的轮次
        self.synergy_formed_type = None
        self.combines = 0
        self.refreshes = 0
        # ---- S5 装备（items_on 时启用；L0 教学沙包不参与合成/装备）----
        self.inventory = items_mod.Inventory()  # 组件池 + 待装备成品
        self.stone_used = False                 # 进化石：每 bot 每局一次（8s 冷却的 sim 语义）
        self.item_drops = 0                     # 收到的组件数
        self.item_crafts = 0                    # 合成次数
        self.item_equips = 0                    # 装备次数
        self.stone_triggers = 0                 # 进化石触发的通信进化数
        # 逐成品合成统计（items.craft_best 写入，experiment_items 汇总）
        self.craft_stats = {"calls": 0, "made": {}, "no_pair": {},
                            "gated": {}, "shadow": {}}

    # ---- 通用视图 ----
    def all_pieces(self) -> list:
        return self.board + self.bench

    def count_species(self, species_id: int) -> int:
        return sum(1 for o in self.all_pieces()
                   if o.piece.species_id == species_id)

    def _has_combine_progress(self, species_id: int) -> bool:
        if getattr(self.pool, 'arena', False):
            stars = [o.piece.star for o in self.all_pieces() if o.piece.species_id == species_id]
            return any(stars.count(star) >= 2 for star in (1, 2))
        return _can_combine(species_id) and self.count_species(species_id) >= 2

    def pop(self) -> int:
        return economy.pop_of(self.level)

    def reserve(self, round_no: int) -> int:
        """花钱地板：人格存款曲线 → 中期变现 → 濒死/决赛圈全押。"""
        if self.ability == 0:
            return 3              # L0 不懂利息，见钱就花
        p = self.pers
        cap = p["late_cap"] if round_no >= p["pivot_round"] \
            else p["reserve_cap"]
        r = min(cap, p["reserve_start"] + (round_no - 1) * p["reserve_gain"])
        if round_no <= 2:
            r = min(r, 3)          # 开局必买：前 2 轮不守存款
        if self.hp <= 40:
            r = min(r, 8)         # 濒死全押（保命比利息值钱）
        if round_no >= 25:
            r = min(r, max(cap // 2, 4))  # 决赛圈花掉一半存款
        return r

    # ---- 一轮决策主入口（match 每轮准备阶段调用）----
    def decide(self, round_no: int, others: list, rng: random.Random) -> None:
        if self.ability >= 1:
            self._maybe_buy_xp(round_no, others)
        if self.ability >= 2:
            self._update_target(round_no, others)
        self._sell_pass(round_no, rng)
        self._shopping(round_no, rng)
        self._items_pass(round_no, others)
        self._select_board(round_no, rng)
        self._record(round_no)

    # ---- S5 装备整理（L1+；items_on 时启用）----
    def _items_pass(self, round_no: int, others: list) -> None:
        """合成（优先级表，人格差异 + 场景门）→ 进化石通信进化 → 装备。

        2026-09-14 裁定/平衡修订：通信进化唯一通道 = 进化石（原「3 合 1
        持装备门」删除，见 S2 §1.5）；合成/装备加场景门（围巾同系才合、
        落后方先合幸运蛋、防御件给坦克——细则见各分步注释）。
        全程确定性（无 rng）：合成/装备次序由固定序与棋子列表序决定。
        顺序在 _select_board 之前——进化/合成改变棋子池，上场选择要看
        新形态；装备本身不影响上场评分（power 是纯 BST）。
        """
        if not items_mod.items_on() or self.ability == 0:
            return
        dex = pokedex()
        # 1) 合成：组件 ≥2 即按优先级出成品。场景门（gate）：
        #    围巾只在持有同系棋子时才合（切系损耗，docs/07 §2）——无同系
        #    载体的围巾是死装备；幸运蛋达全场上限让位；无通信进化目标/
        #    石头已用则不烧进化石（组件留作后续特定配方）
        stone_ok = not self.stone_used and any(
            o.piece.species_id in items_mod.STONE_TARGETS
            for o in self.all_pieces())
        behind = self._is_behind(others)   # 落后方：幸运蛋提前（追赶条款）
        priority = items_mod.craft_priority(self.pers_key, stone_ok, behind)
        # Only public, previously encountered opponent pieces inform this choice.
        # No future shop, seed or hidden inventory is inspected.
        opponent = getattr(self, '_last_opp', None)
        if (tactics.counters_enabled(self.inventory.ruleset)
                and opponent is not None and self._healing_threat(opponent.board)):
            priority = ('healing_needle',) + priority
        craft_gate = self._craft_gate(round_no)
        while True:
            lucky_ok = items_mod.lucky_egg_count(others) < \
                items_mod.LUCKY_EGG_GLOBAL_CAP
            if items_mod.craft_best(self.inventory, priority, lucky_ok,
                                    stone_ok, stats=self.craft_stats,
                                    gate=craft_gate) is None:
                break
            self.item_crafts += 1
        # 2) 进化石：装备到通信族中段形态上即触发通信进化（不消耗、每局一次；
        #    2026-09-14 裁定后的唯一通道——3 合 1 通道已删除）
        if "evo_stone" in self.inventory.finished and not self.stone_used:
            for o in sorted(self.all_pieces(),
                            key=lambda x: -dex.bst(x.piece.species_id)):
                nxt = items_mod.STONE_TARGETS.get(o.piece.species_id)
                if o.item is None and nxt and self.pool.remaining.get(nxt, 0) > 0:
                    self.inventory.finished.remove("evo_stone")
                    o.item = "evo_stone"
                    self.item_equips += 1
                    self.pool.take(nxt)
                    o.piece = shop_mod.make_piece(nxt, self.templates)
                    o.sources.append(nxt)      # 池记账：进化形态占 1 张
                    self.stone_used = True
                    self.stone_triggers += 1
                    break
        # 3) 装备：按成品类别定向（针对性使用条件，2026-09-14 平衡修订）；
        #    幸运蛋给最弱棋（不占主 C 的 1 格）；进化石只走上面的通信进化
        #    通道（不占无目标的棋子格）
        for key in [k for k in self.inventory.finished
                    if k not in ("lucky_egg", "evo_stone")]:
            target = self._item_target(key)
            if target is not None:
                self.inventory.finished.remove(key)
                target.item = key
                self.item_equips += 1
        if "lucky_egg" in self.inventory.finished:
            by_bst = sorted(self.all_pieces(),
                            key=lambda o: -dex.bst(o.piece.species_id))
            for o in reversed(by_bst):        # 最弱棋背蛋（不占主 C 的 1 格）
                if o.item is None:
                    self.inventory.finished.remove("lucky_egg")
                    o.item = "lucky_egg"
                    self.item_equips += 1
                    break

    def _is_behind(self, others: list) -> bool:
        """落后方判定（与 items.drop_weights 同口径）：hp 不高于存活均值——
        幸运蛋等追赶件对落后方提前（docs/03 §5 / docs/07 §1 追赶渠道）。"""
        alive = [b.hp for b in others if b.alive]
        return self.hp <= sum(alive) / max(1, len(alive))

    def _craft_gate(self, round_no: int):
        """合成场景门（针对性使用条件，2026-09-14 平衡修订）：

        - 三色围巾按系别棋子池深设门（池越深门槛越高——单只同系载体
          说不上「围绕该系组阵」，切系损耗 docs/07 §2）：水（池内
          ~20 只）**≥3 只**、火（~8 只）**≥2 只**、电（仅 5 只）
          **≥1 只**，或该系在主羁绊目标里（L2 定向中）。逐系读数
          校准：统一 ≥2 时黄围巾 3.2% 低于 5% 底线、家族又略超线，
          按池深分档后各系均落带内；
        - 其余成品全放行（天气石靠配方改窄压制，见 items.py 修订注）。
        确定性（纯查表）。
        """
        counts = {}
        for o in self.all_pieces():
            for t in o.piece.types:
                counts[t] = counts.get(t, 0) + 1
        targets = set(self.target_types)
        # 门限随池深：WATER ~20 只 → 3；FIRE ~8 只 → 2；ELECTRIC 5 只 → 1
        need_of = {"WATER": 3, "FIRE": 2, "ELECTRIC": 1}

        def gate(key: str) -> bool:
            if key.startswith("scarf_"):
                t = key.rsplit("_", 1)[1].upper()
                return counts.get(t, 0) >= need_of.get(t, 2) or t in targets
            return True
        return gate

    @staticmethod
    def _healing_threat(board):
        if synergy.compute([o.piece for o in board]).get('WATER', 0) >= 2:
            return True
        return any(o.item == 'leftovers' or o.technique == 'rest'
                   or skills.arch_of(o.piece.species_id) in ('mend', profiles.ARCH_SOLAR, profiles.ARCH_SLAM)
                   for o in board)

    def _item_target(self, key: str):
        """装备去向（针对性使用条件，2026-09-14 平衡修订）：

        - 三色围巾 → 最强**同系**空手单位（无同系时落到通用主 C 兜底）；
        - 聚光镜 → 空手中特攻最高者（大招流载体：大招走特攻/威力乘区）；
        - 专爱头巾/疾风羽 → BST 最高空手者、远程优先（主 C 输出位）；
        - 防御件（剩饭/气势披带/亮粉/天气石）→ 最坦空手单位（近战优先：
          闪避/减伤/反斩杀/前排续航都在承伤位兑现，v1 全堆 BST 主 C
          让防御件的场景天然错位）。
        确定性：并列取棋子列表序（max 首个最大值）。
        """
        dex = pokedex()
        free = [o for o in self.all_pieces() if o.item is None]
        if not free:
            return None
        if key == 'healing_needle':
            casters = [o for o in free if skills.resolve_cast(o.piece) is not None]
            return max(casters, key=lambda o: (
                effective_range(o.piece) > 1, dex.bst(o.piece.species_id)), default=None)
        if key.startswith("scarf_"):
            t = key.rsplit("_", 1)[1].upper()
            on_type = [o for o in free if t in o.piece.types]
            pool = on_type or free
            return max(pool, key=lambda o: dex.bst(o.piece.species_id))
        if key == "focus_lens":
            return max(free, key=lambda o: (
                dex.species[o.piece.species_id]["base"]["special_attack"],
                dex.bst(o.piece.species_id)))
        if key in ("choice_band", "swift_feather"):

            def carry_rank(o: OwnedPiece) -> tuple:
                ranged = effective_range(o.piece) > 1
                return (ranged, dex.bst(o.piece.species_id),
                        dex.species[o.piece.species_id]["base"]["special_attack"])
            return max(free, key=carry_rank)

        def tank_rank(o: OwnedPiece) -> tuple:
            b = dex.species[o.piece.species_id]["base"]
            return (effective_range(o.piece) == 1, b["hp"] + 2 * b["defense"])
        return max(free, key=tank_rank)

    def _unequip(self, owned: OwnedPiece) -> None:
        """卸下装备回仓库（卖棋自动卸下，无惩罚——docs/07 §3）。"""
        if owned.item is not None:
            self.inventory.finished.append(owned.item)
            owned.item = None
        if owned.technique is not None:
            self.inventory.techniques[owned.technique] += 1
            owned.technique = None

    # ---- 升级人口 ----
    def _maybe_buy_xp(self, round_no: int, others: list) -> None:
        mode = self.pers["level_mode"]
        strongest_lv = max((b.level for b in others
                            if b is not self and b.alive), default=1)
        # slow 人格变现前只花「存款溢出」（cap+12 之上）；其余守当轮地板
        pre_pivot = round_no < self.pers["pivot_round"]
        floor = (self.pers["reserve_cap"] + 12) if (mode == "slow" and
                                                   pre_pivot) \
            else self.reserve(round_no)
        for _ in range(5):  # 每轮最多买 5 次（20 金）防失控
            need = economy.xp_to_next(self.level)
            if need is None:
                break
            # 先有人再升人口：现有棋子连当前人口都填不满时不买经验
            if len(self.all_pieces()) < self.pop() - 1:
                break
            if self.level >= self._level_target(round_no, mode, strongest_lv):
                break
            if self.gold - economy.XP_BUY_COST < floor:
                break
            self.level, self.xp, self.gold, _ = economy.buy_xp(
                self.level, self.xp, self.gold)

    def _level_target(self, round_no: int, mode: str, strongest_lv: int) -> int:
        if mode == "fast":      # 梭哈：R6 起全力冲满级
            return economy.MAX_LEVEL if round_no >= 6 else min(4, 2 + round_no // 3)
        if mode == "follow":    # 跟牌：等级咬住最强对手（滞后 1 级——模仿总比
            # 原创慢半拍；2026-09-14 平衡 pass：无滞后时 copycat 白嫖领跑者
            # 节奏（平均名次 3.2 领先 1.2 名，消融实证与抄牌分支无关），滞后 1
            # 级回到 4.2 与其余人格挤进一格）
            return max(strongest_lv - 1, min(4, 2 + round_no // 5))
        if mode == "slow":      # 攒钱：吃满利息慢升；变现期（pivot 后）追赶
            if round_no >= self.pers["pivot_round"]:
                return min(economy.MAX_LEVEL, 2 + round_no // 3)
            return min(economy.MAX_LEVEL, 2 + round_no // 6)
        return min(economy.MAX_LEVEL, 2 + round_no // 4)  # balanced：标准曲线

    # ---- 主羁绊目标（L2 羁绊感知 / copycat 抄最强对手）----
    def _stack_values(self) -> list:
        """各属性的堆叠价值表 [(属性, 数量, 持有该属性棋子 BST 合计)]。

        纯按数量锁定会把 L2 锁进「深而弱」的属性（毒系 23 只大半是 1 费，
        首版读数 L2 从水系漂移到毒系后名次倒挂的实证）——
        价值 = 该属性持有棋子的 BST 合计，数量只做并列 tie-break。
        """
        dex = pokedex()
        agg = {}
        for owned in self.all_pieces():
            bst = dex.bst(owned.piece.species_id)
            for t in owned.piece.types:
                n, s = agg.get(t, (0, 0))
                agg[t] = (n + 1, s + bst)
        return sorted(((t, n, s) for t, (n, s) in agg.items()),
                      key=lambda kv: (-kv[2], -kv[1], kv[0]))

    def _update_target(self, round_no: int, others: list) -> None:
        if self.pers_key == "copycat":
            opp = max((b for b in others if b is not self and b.alive),
                      key=lambda b: (b.hp, b.level, -b.seat), default=None)
            if opp is not None:
                opp_types = main_types(opp.board)
                if opp_types and opp_types[0][1] >= 3:
                    self.target_types = (opp_types[0][0],)
                    return
        stacks = self._stack_values()
        if not stacks:
            return
        best_t, best_n, best_s = stacks[0]
        if not self.target_types:
            if best_n >= 2:   # 2 只同属性即锁方向（开局引导）
                self.target_types = (best_t,)
            return
        cur = next((s for t, _n, s in stacks if t in self.target_types), 0)
        # 换阵容容忍：新目标的价值（BST 合计）须超当前 × (1.2 + 0.1×tol)
        if best_t not in self.target_types and \
                best_s >= cur * (1.2 + 0.1 * self.pers["pivot_tol"]):
            self.target_types = (best_t,)

    # ---- 卖棋整理（备战席容量管理 + L2 卖偏离羁绊）----
    def _sell_pass(self, round_no: int, rng: random.Random) -> None:
        def do_sell(owned: OwnedPiece) -> None:
            self._unequip(owned)   # S5：卖棋自动卸下回仓库（无惩罚）
            self.gold += shop_mod.sell_owned(owned, self.pool)
            if owned in self.bench:
                self.bench.remove(owned)
            elif owned in self.board:
                self.board.remove(owned)

        if self.ability == 0:  # L0：满了随机卖
            while len(self.bench) > getattr(self, 'bench_capacity', BENCH_SIZE):
                do_sell(self.bench[rng.randrange(len(self.bench))])
            return

        # L1+：优先卖不供目标羁绊、没有 3 合 1 进度的低战力棋
        def sell_rank(owned: OwnedPiece) -> tuple:
            off_target = 1 if self.ability >= 2 and not (
                set(owned.piece.types) & set(self.target_types)) else 0
            unprotected = not self._has_combine_progress(owned.piece.species_id)
            return (off_target, unprotected, -power(owned, self.target_types))

        limit = getattr(self, 'bench_capacity', BENCH_SIZE)   # L1/L2 都守 6 格硬上限（设备裁定）；差别在卖谁：
        while len(self.bench) > limit:   # L2 按偏离羁绊优先卖，L1 只看战力
            do_sell(max(self.bench, key=sell_rank))
        while len(self.bench) > getattr(self, 'bench_capacity', BENCH_SIZE):  # 硬上限兜底
            do_sell(max(self.bench, key=lambda o: -power(o, self.target_types)))

    # ---- 买棋 + 刷新 ----
    def _slot_score(self, sid: int) -> int:
        """L2 买入评分；L1 返回 ±哨兵（只看 fits 布尔）。"""
        piece = self.templates[sid]
        if self.ability <= 1:
            return 10 ** 9 if self._fits(piece) else -1
        # 铺场期（还没凑出主羁绊方向、阵容未满编）：什么都能买
        if not self.target_types and len(self.all_pieces()) < self.pop() + 4:
            return 10 ** 9
        score = _species_power(sid)
        copies = self.count_species(sid)
        in_target = bool(set(piece.types) & set(self.target_types))
        valuable = in_target or score >= 400
        if getattr(self.pool, 'arena', False) or _can_combine(sid):
            if copies == 1:
                score += 600 if valuable else 250    # 第 2 只：3 合 1 进度
            elif copies >= 2:
                score += 900 if valuable else 300
        elif copies >= 2 and sid in shop_mod.TRADE_EVOLUTIONS:
            # 通信族第 3 只：3 合 1 通道已裁撤（2026-09-14 裁定：唯一通道=
            # 进化石单人进化，只需 1 只中段形态），第 3 只无合并价值，
            # 维持 −800 暂缓罚（装备开关两臂一致——原「装备开解除」随门删除）
            score -= 800
        score += {1: 0, 2: 100, 3: 220}[piece.tier]   # 高档位通用升级价值
        if in_target:
            score += 400            # 供主羁绊
        else:   # 次级羁绊：双属性世界里单点锁定太窄，跟随场上自然成堆的属性
            owned_counts = main_types(self.all_pieces())
            stack = {t: n for t, n in owned_counts}
            score += 60 * sum(min(stack.get(t, 0), 6) for t in piece.types)
        return score

    def _fits(self, piece) -> bool:
        """L1 规则经济（docs/03 §4.1「只买当前阵容族」）：
        可合成复制件 / 主属性族（板上前 2 属性）/ 明确的高档升级 才买。"""
        if (_can_combine(piece.species_id)
                and self.count_species(piece.species_id) >= 1):
            return True
        if not self.board:          # 空场先铺
            return True
        top_types = {t for t, _n in main_types(self.board)[:2]}
        if set(piece.types) & top_types:
            return True
        if piece.tier > min(o.piece.tier for o in self.board):
            return True
        return False

    def _shopping(self, round_no: int, rng: random.Random) -> None:
        reserve = self.reserve(round_no)
        refresh_budget = self.pers["refresh_max"]
        if round_no >= LATE_GAME_ROUND:
            refresh_budget += 2
        if self.ability == 0:
            refresh_budget = 2     # L0 偶尔瞎刷
        refreshes = 0
        aggressive = self.pers_key == "roller" or (
            self.ability >= 2 and self.hp <= 30)
        while True:
            bought = self._buy_pass(round_no, rng, reserve)
            # 刷新地板比买棋高 4 金：给下轮留买棋钱，防梭哈型滚到破产
            may_refresh = refreshes < refresh_budget and \
                self.gold - economy.REFRESH_COST >= reserve + 4
            if self.ability == 0:
                may_refresh = may_refresh and rng.random() < 0.2
            if not may_refresh:
                break
            if not bought and not aggressive and refreshes >= 1:
                break              # 没买到东西且不激进：省下这次刷新
            self.gold -= economy.REFRESH_COST
            self.refreshes += 1
            refreshes += 1
            self.shop.roll(rng, self.level)

    def _buy_pass(self, round_no: int, rng: random.Random, reserve: int) -> bool:
        bought = False
        for slot in range(len(self.shop.slots)):
            sid = self.shop.slots[slot]
            if sid is None:
                continue
            price = self.shop.price(slot)
            if self.gold - price < reserve:
                continue
            if self.ability == 0:
                want = rng.random() < 0.85
            else:
                want = self._slot_score(sid) >= (
                    BUY_THRESHOLD if self.ability >= 2 else 0)
            if not want:
                continue
            if len(self.bench) >= getattr(self, 'bench_capacity', BENCH_SIZE):
                # 备战满：新货价值（含羁绊/复制加成）高于最弱存货才换仓；
                # 换仓保护有 3 合 1 进度的复制件
                def victim_rank(o: OwnedPiece) -> tuple:
                    protected = self._has_combine_progress(o.piece.species_id)
                    return (protected, power(o, self.target_types))
                victim = min(self.bench, key=victim_rank)
                new_val = self._slot_score(sid) if self.ability >= 2 \
                    else _species_power(sid)
                if self.ability == 0 or power(victim, self.target_types) < new_val:
                    self._unequip(victim)   # S5：卖棋自动卸下回仓库
                    self.gold += shop_mod.sell_owned(victim, self.pool)
                    self.bench.remove(victim)
                else:
                    continue
            owned = self.shop.buy(slot)
            self.gold -= price
            self.bench.append(owned)
            self.combines += len(try_combine(
                self.board, self.bench, self.pool, self.templates,
                self.inventory, respect_locks=tactics.evolution_choices_enabled(self.inventory.ruleset)))
            bought = True
        return bought

    # ---- 上场阵容 + 摆位 ----
    def _board_score(self, owned: OwnedPiece, stack: dict) -> int:
        """L2 上场评分：BST + 成堆属性奖励（每供一个已 ≥2 只的属性 +80）。

        读的是场上实际堆叠数（阈值语义对齐 synergy.THRESHOLDS[0]），
        羁绊关时它只是「跟自然成堆走」的弱偏置，羁绊开时它就是羁绊意识。
        """
        s = power(owned)
        if self.ability >= 2:
            s += 80 * sum(1 for t in owned.piece.types if stack.get(t, 0) >= 2)
        return s

    def _select_board(self, round_no: int, rng: random.Random) -> None:
        all_owned = self.all_pieces()
        pop = self.pop()
        if self.ability == 0:
            picked = rng.sample(all_owned, min(pop, len(all_owned))) \
                if all_owned else []
            rng.shuffle(picked)
            self.board = picked
            self.bench = [o for o in all_owned if o not in picked]
            return
        stack = {t: n for t, n in main_types(all_owned)}
        ranked = sorted(all_owned,
                        key=lambda o: -self._board_score(o, stack))
        self.board = ranked[:pop]
        self.bench = ranked[pop:]
        self._arrange()

    def _arrange(self) -> None:
        """摆位（L1 起）：远程后排（列表头）/ 坦克前排（列表尾）。

        layout="back" 下 Battle 按列表顺序从己方后排（C-sym 战场行 3，
        贴己方边缘）向前排（行 2，贴中线）填 → 次序即阵型。
        L3 的列对位由 counter_vs 在配对后追加。
        """
        dex = pokedex()

        def tank_rank(o: OwnedPiece) -> int:
            b = dex.species[o.piece.species_id]["base"]
            return b["hp"] + 2 * b["defense"]

        melee = [o for o in self.board if effective_range(o.piece) == 1]
        ranged = [o for o in self.board if effective_range(o.piece) > 1]
        melee.sort(key=tank_rank)   # 坦克值高的在列表尾 = 前排
        ranged.sort(key=lambda o: -dex.species[o.piece.species_id]
                    ["base"]["special_attack"])  # 主 C 在列表头 = 最后排
        self.board = ranged + melee

    def counter_vs(self, opp_board: list) -> None:
        """L3 专用：配对后按对手阵容做列对位（弱化版）。

        对手同样 back 布阵，其主 C（战力最高）大概率落在其列表前段
        （列 0~COLS-1）；我方主 C 落到镜像列（COLS-1 - 对手列）拉开
        距离，主坦对齐对手主 C 列。列宽随 combat.COLS（C-sym 为 6），
        置换只发生在首行（列表索引 < COLS 即锚定行），非 L3 直接返回。"""
        if self.ability < 3 or not self.board:
            return
        comp = self.board
        opp_carry_col = COLS // 2
        if opp_board:
            carry = max(opp_board, key=power)
            try:
                opp_carry_col = min(opp_board.index(carry), COLS - 1)
            except ValueError:
                pass

        def swap_to(piece: OwnedPiece, want_col: int) -> None:
            if want_col >= min(COLS, len(comp)):
                return
            cur = comp.index(piece)
            if cur < COLS and cur != want_col:
                comp[cur], comp[want_col] = comp[want_col], comp[cur]

        ranged = [o for o in comp if effective_range(o.piece) > 1]
        melee = [o for o in comp if effective_range(o.piece) == 1]
        if ranged:
            swap_to(max(ranged, key=power), COLS - 1 - opp_carry_col)
        if melee:
            swap_to(max(melee, key=lambda o: pokedex().bst(o.piece.species_id)),
                    opp_carry_col)

    # ---- 供 battle 用的 comp ----
    def battle_comp(self) -> list:
        """上场名单：带装备者传 (Piece, item_key) 二元组（S5 协议），空手传裸 Piece。"""
        return [o.piece if o.item is None else (o.piece, o.item)
                for o in self.board]

    # ---- 统计 ----
    def _record(self, round_no: int) -> None:
        self.gold_curve.append(self.gold)
        self.pop_curve.append(len(self.board))
        counts = main_types(self.board)
        top = counts[0] if counts else ("-", 0)
        self.synergy_curve.append(top)
        if self.synergy_formed_round is None and top[1] >= 4:
            self.synergy_formed_round = round_no
            self.synergy_formed_type = top[0]
