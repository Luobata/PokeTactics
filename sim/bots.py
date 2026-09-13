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
import shop as shop_mod
from combat import COLS  # C-sym 棋盘列数（docs/10 §1.5）：列对位随棋盘常量走
from shop import OwnedPiece, SharedPool, try_combine

BENCH_SIZE = 9       # 备战席 9 格（TFT 同款）
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
                 "late_cap": 20, "refresh_max": 1,
                 "level_mode": "slow", "pivot_tol": 0},
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


def power(owned: OwnedPiece, target_types=()) -> int:
    """棋子战力估值：纯 BST（上场选择/卖出/对位共用的底价）。

    目标羁绊不直接加价：首版读数 L2 给目标棋 +150~+250 上场偏置，
    会用 380 BST 的羁绊棋挤掉 500+ 的散件，名次反而倒挂——
    羁绊的价值由 L2 的买入定向 + 上场时的成堆奖励（_board_score）兑现。
    """
    return pokedex().bst(owned.piece.species_id)


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

    # ---- 通用视图 ----
    def all_pieces(self) -> list:
        return self.board + self.bench

    def count_species(self, species_id: int) -> int:
        return sum(1 for o in self.all_pieces()
                   if o.piece.species_id == species_id)

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
        self._select_board(round_no, rng)
        self._record(round_no)

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
        if mode == "follow":    # 跟牌：等级咬住最强对手
            return max(strongest_lv, min(4, 2 + round_no // 5))
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
            self.gold += shop_mod.sell_owned(owned, self.pool)
            if owned in self.bench:
                self.bench.remove(owned)
            elif owned in self.board:
                self.board.remove(owned)

        if self.ability == 0:  # L0：满了随机卖
            while len(self.bench) > BENCH_SIZE:
                do_sell(self.bench[rng.randrange(len(self.bench))])
            return

        # L1+：优先卖「单只、不供目标羁绊、非复制件」的低战力棋
        def sell_rank(owned: OwnedPiece) -> tuple:
            off_target = 1 if self.ability >= 2 and not (
                set(owned.piece.types) & set(self.target_types)) else 0
            single = 1 if self.count_species(owned.piece.species_id) == 1 else 0
            return (off_target, single, -power(owned, self.target_types))

        limit = 6 if self.ability >= 2 else 8
        while len(self.bench) > limit:
            do_sell(max(self.bench, key=sell_rank))
        while len(self.bench) > BENCH_SIZE:  # 硬上限兜底
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
        score = pokedex().bst(sid)
        copies = self.count_species(sid)
        in_target = bool(set(piece.types) & set(self.target_types))
        valuable = in_target or pokedex().bst(sid) >= 400
        if copies == 1:
            score += 600 if valuable else 250    # 第 2 只：3 合 1 进度
        elif copies >= 2:
            score += (900 if valuable else 300) \
                if sid not in shop_mod.TRADE_EVOLUTIONS else -800
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
        复制件 / 主属性族（板上前 2 属性）/ 明确的高档升级 才买。"""
        if self.count_species(piece.species_id) >= 1:
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
        for slot in range(shop_mod.SHOP_SLOTS):
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
            if len(self.bench) >= BENCH_SIZE:
                # 备战满：新货价值（含羁绊/复制加成）高于最弱存货才换仓；
                # 换仓优先牺牲单只（保住 3 合 1 的复制件）
                def victim_rank(o: OwnedPiece) -> tuple:
                    single = 0 if self.count_species(
                        o.piece.species_id) == 1 else 1
                    return (single, power(o, self.target_types))
                victim = min(self.bench, key=victim_rank)
                new_val = self._slot_score(sid) if self.ability >= 2 \
                    else pokedex().bst(sid)
                if self.ability == 0 or power(victim, self.target_types) < new_val:
                    self.gold += shop_mod.sell_owned(victim, self.pool)
                    self.bench.remove(victim)
                else:
                    continue
            owned = self.shop.buy(slot)
            self.gold -= price
            self.bench.append(owned)
            self.combines += len(try_combine(
                self.board, self.bench, self.pool, self.templates))
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

        melee = [o for o in self.board if o.piece.distance == 1]
        ranged = [o for o in self.board if o.piece.distance > 1]
        melee.sort(key=tank_rank)   # 坦克值高的在列表尾 = 前排
        ranged.sort(key=lambda o: -dex.species[o.piece.species_id]
                    ["base"]["special_attack"])  # 主 C 在列表头 = 最后排
        self.board = ranged + melee

    def counter_vs(self, opp_board: list) -> None:
        """L3 专用：配对后按对手阵容做列对位（弱化版）。

        对手同样 back 布阵，其主 C（战力最高）大概率落在其列表前段（列 0-6）；
        我方主 C 落到镜像列（6 - 对手列）拉开距离，主坦对齐对手主 C 列。
        只做一次置换，非 L3 直接返回。"""
        if self.ability < 3 or not self.board:
            return
        comp = self.board
        opp_carry_col = 3
        if opp_board:
            carry = max(opp_board, key=power)
            try:
                opp_carry_col = min(opp_board.index(carry), 6)
            except ValueError:
                pass

        def swap_to(piece: OwnedPiece, want_col: int) -> None:
            if want_col >= min(7, len(comp)):
                return
            cur = comp.index(piece)
            if cur < 7 and cur != want_col:
                comp[cur], comp[want_col] = comp[want_col], comp[cur]

        ranged = [o for o in comp if o.piece.distance > 1]
        melee = [o for o in comp if o.piece.distance == 1]
        if ranged:
            swap_to(max(ranged, key=power), 6 - opp_carry_col)
        if melee:
            swap_to(max(melee, key=lambda o: pokedex().bst(o.piece.species_id)),
                    opp_carry_col)

    # ---- 供 battle 用的 comp ----
    def battle_comp(self) -> list:
        return [o.piece for o in self.board]

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
