"""战斗解算器：tick 制自动战斗（TFT 式），金银伤害公式。

一局战斗 = 两队棋子落位后无人操作，解算到一队全灭或超时。

单位行为（骨架版，规则全部可换）：
- 索敌：最近的敌人（曼哈顿距离）；
- 射程外每 MOVE_TICK 秒走一步（贪心靠近，绕不开就原地）；
- 射程内按攻击间隔普攻；能量满（ENERGY_MAX）时改放本系招牌招式；
- 普攻无属性（不吃克制与本系加成），走攻高的一端（物攻/特攻）；
- 招式带属性：吃本系加成、属性克制、命中骰。

伤害 = 金银世代公式（无个体值/努力值）：
    base = ((2*Lv/5+2) * Power * A/D) / 50 + 2
    final = base * STAB * 克制 * 随机(0.85~1.0)
"""

import random
from data import (BASIC_POWER, ENERGY_MAX, ENERGY_PER_ATTACK,
                  ENERGY_PER_HIT_TAKEN, MAX_BATTLE_SECONDS, MOVE_TICK,
                  SPEED_TO_ATTACK_INTERVAL, STAB_BONUS, basic_takes_eff,
                  eff_mult, melee_move_mult, melee_resist, pokedex,
                  ranged_interval_mult)
from roster import Piece
import synergy  # S3 羁绊：默认 SYNERGIES_ON=False，零随机、零事件流变更
import status as status_mod   # S12 状态/Buff：默认 STATUS_ON=False（docs/06）
import weather as weather_mod  # S11 天气：默认无天气（docs/05）
import items as items_mod     # S5 装备：comp 元素可带 (Piece, item) 二元组（docs/07）

TICK = 0.1  # 解算步长（秒）
# ---- C-sym 棋盘（docs/10 §1.3/§1.5，2026-09-14 sim 联动落地）----
# 6 列 × 4 行对称战场：行 0-1 敌方战场、行 2-3 己方战场（旧版 7×6 的
# 3+3 纵深收成 2+2）。双方各 1 条备战行是准备页/渲染层概念，不进战斗
# 网格：备战棋子本就不传入 Battle（bots.battle_comp 只含上场名单），
# 无需部署过滤；若把备战行画进网格，要么整行不可通行切断两军通路、
# 要么可通行变成行军走廊，都与「不参战」矛盾。
COLS, ROWS = 6, 4
ROWS_ENEMY = (0, 1)   # 敌方战场行；"back" 布阵自 rows[-1]（贴中线的前排）起填
ROWS_ALLY = (2, 3)    # 己方战场行；"back" 布阵自 rows[-1]（贴己方边缘的后排）起填


class Unit:
    """场上的一名棋子（战斗态）。"""

    def __init__(self, piece: Piece, team: int, pos: tuple) -> None:
        dex = pokedex()
        base = dex.species[piece.species_id]["base"]
        lv = piece.level
        self.piece = piece
        self.team = team
        self.pos = pos
        # 金银种族值 -> 等级属性（DV15/经验0 的整数化简化）
        self.max_hp = int(2 * base["hp"] * lv / 100) + lv + 10
        self.hp = self.max_hp
        self.attack = int(2 * base["attack"] * lv / 100) + 5
        self.defense = int(2 * base["defense"] * lv / 100) + 5
        self.sp_attack = int(2 * base["special_attack"] * lv / 100) + 5
        self.sp_defense = int(2 * base["special_defense"] * lv / 100) + 5
        interval = SPEED_TO_ATTACK_INTERVAL(base["speed"])
        if piece.distance > 1:  # 远程：均衡实验的出手惩罚
            interval *= ranged_interval_mult()
        self.attack_interval = interval
        self.range = piece.distance
        self.energy = 0
        self.next_act = 0.0  # 起手抖动由 Battle._deploy 注入，抵消部署先手差
        self.target_idx = None  # 目标滞回：锁定到死亡为止，防最近目标切换震荡
        # 战报统计
        self.damage_dealt = 0
        self.casts = 0
        # ---- S3 羁绊结算维度（sim/synergy.apply 开战时写入，默认中性值）----
        self.synergy_dmg = 0.0       # 造成伤害加成（比例）
        self.synergy_ult_dmg = 0.0   # 大招伤害加成（比例）
        self.synergy_dr = 0.0        # 受伤减免（比例）
        self.synergy_heal = 0.0      # 每秒回复（最大 HP 比例）
        self.synergy_energy = 0.0    # 回能加成（比例）
        self.synergy_ult_cap = None  # 单次大招承伤上限（最大 HP 比例）
        # ---- S5 装备结算维度（items.apply_to_unit 写入，默认中性值）----
        self.item_ult_dmg = 0.0     # 大招伤害加成（比例，聚光镜）
        self.item_dr = 0.0          # 受伤减免（比例，天气石 v1 折算）
        self.item_heal = 0.0        # 每秒回复（最大 HP 比例，剩饭）
        self.item_energy = 0.0      # 回能加成（比例）
        self.item_dodge = 0.0       # 被击闪避（比例，亮粉）
        self.item_type_dmg = None   # 系别伤害加成 {属性: 比例}（三色围巾）
        self.item_sash = False      # 气势披带：致命伤保留 1 HP
        self.item_sash_used = False # 披带一次/场

    @property
    def alive(self) -> bool:
        return self.hp > 0

    def attack_stat(self, special: bool) -> int:
        return self.sp_attack if special else self.attack

    def defense_stat(self, special: bool) -> int:
        return self.sp_defense if special else self.defense


def _manhattan(a: tuple, b: tuple) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _damage(rng: random.Random, level: int, power: int, atk: int, dfn: int,
            stab: float, eff: float) -> int:
    base = int(int(int(2 * level / 5 + 2) * power * atk / dfn) / 50) + 2
    return max(1, int(base * stab * eff * rng.uniform(0.85, 1.0)))


class Battle:
    """一场 1v1 自动战斗。rng 由调用方传入，保证可复现（设计宪法第 3 条）。

    events 是双端渲染同步的契约（宪法 2.6）：解算器输出离散事件流，
    Web 预览与设备固件只是同一种子下同一事件流的两种回放端。
    每条事件为 (t, kind, ...)，kind ∈ deploy/move/attack/cast/die/end。
    """

    def __init__(self, comp_a: list, comp_b: list, rng: random.Random,
                 layout: str = "random", weather_name=None) -> None:
        weather_mod.set_active(weather_name)  # 全局天气（实验按臂；后台在锁内渲染）
        self.rng = rng
        self.dex = pokedex()
        self.units: list = []
        self.events: list = []
        self._deploy(comp_a, team=0, rows=ROWS_ALLY, layout=layout)
        self._deploy(comp_b, team=1, rows=ROWS_ENEMY, layout=layout)
        if synergy.synergies_on():  # S3：按场上当前形态一次性结算（无随机）
            # S5 协议：comp 元素可能带 (Piece, item) 二元组——羁绊只看裸 Piece
            plain_a = [e[0] if isinstance(e, tuple) else e for e in comp_a]
            plain_b = [e[0] if isinstance(e, tuple) else e for e in comp_b]
            synergy.apply([u for u in self.units if u.team == 0], plain_a)
            synergy.apply([u for u in self.units if u.team == 1], plain_b)
        status_mod.init_battle(self)  # S12：状态容器（默认无操作）
        self.duration = 0.0

    def _deploy(self, comp: list, team: int, rows: tuple, layout: str) -> None:
        cells = [(c, r) for r in rows for c in range(COLS)]
        if layout == "random":
            spots = self.rng.sample(cells, len(comp))
        else:  # "back": 自 rows[-1] 行起密排（我方=后排起填、敌方=前排起填，
               # 与旧 3+3 布阵的填充方向逐行对应，列表头=远程）
            order = sorted(cells, key=lambda p: abs(p[1] - rows[-1]))
            spots = order[:len(comp)]
        for entry, pos in zip(comp, spots):
            # S5 装备协议：comp 元素可为 (Piece, item_key) 二元组（带装备）或
            # 裸 Piece（无装备——prototype/野怪波次走此路径，行为不变）
            piece, item_key = entry if isinstance(entry, tuple) else (entry, None)
            unit = Unit(piece, team, pos)
            if item_key is not None:   # S5 施加点（S3 synergy.apply 同模式）
                items_mod.apply_to_unit(unit, item_key)
            unit.next_act = self.rng.uniform(0, 0.3)  # 起手抖动，消除先手偏差
            unit.idx = len(self.units)
            self.units.append(unit)
            self.events.append((0.0, "deploy", unit.idx, pos))

    # ---- 主循环 ----
    def run(self) -> dict:
        t = 0.0
        # S3 持续羁绊（水之治疗等）+ S5 剩饭：每 1s 一跳；v1 不入事件流
        regen_units = [u for u in self.units
                       if u.synergy_heal > 0 or u.item_heal > 0]
        next_regen = 1.0
        while t <= MAX_BATTLE_SECONDS:
            self.duration = t
            alive_teams = {u.team for u in self.units if u.alive}
            if len(alive_teams) <= 1:
                break
            for u in sorted(self.units, key=lambda x: x.next_act):
                if u.alive and t + 1e-9 >= u.next_act:
                    self._act(u, t)
            if regen_units and t + 1e-9 >= next_regen:
                for u in regen_units:
                    if u.alive and u.hp < u.max_hp:
                        healed = min(u.max_hp, u.hp + max(
                            1, int(u.max_hp * (u.synergy_heal + u.item_heal)))) - u.hp
                        u.hp += healed
                        if healed:
                            self.events.append((t, "regen", u.idx, healed))
                next_regen += 1.0
            status_mod.tick(self, t)  # S12：DOT/到期（默认无操作）
            t += TICK
        return self._result()

    def _act(self, u: Unit, t: float) -> None:
        if status_mod.stunned(u, t):  # S12：冰冻/睡眠期间不行动（默认 False）
            u.next_act = t + 0.2
            return
        target = self._target(u)
        if target is None:
            return
        dist = _manhattan(u.pos, target.pos)
        if dist <= u.range:
            self._strike(u, target, t)
            u.next_act = t + u.attack_interval * status_mod.speed_mult(u)
        else:
            self._step_toward(u, target.pos)
            self.events.append((t, "move", u.idx, u.pos))
            step = MOVE_TICK * (melee_move_mult() if u.range == 1 else 1.0)
            u.next_act = t + step

    def _target(self, u: Unit):
        """目标滞回：命中或锁定中的敌人死了才换目标。

        无滞回时「最近敌人」在两个等距目标间来回翻转，近战会原地震荡
        （实验证据见 reports/effectiveness-experiment-2026-09-13.md）。
        """
        cur = self.units[u.target_idx] if u.target_idx is not None else None
        if cur is not None and cur.alive and cur.team != u.team:
            return cur
        enemies = [e for e in self.units if e.alive and e.team != u.team]
        if not enemies:
            u.target_idx = None
            return None
        near = min(enemies, key=lambda e: (_manhattan(u.pos, e.pos), e.idx))
        u.target_idx = near.idx
        return near

    def _step_toward(self, u: Unit, goal: tuple) -> None:
        """BFS 最短路走第一步（绕开占用格；终点视为可通行）。

        旧版贪心一步会被己方单位和地形卡成来回抖动；BFS 保证单调接近。
        """
        from collections import deque
        occupied = {o.pos for o in self.units if o.alive and o is not u}
        queue = deque([(u.pos, None)])
        seen = {u.pos}
        while queue:
            pos, first = queue.popleft()
            if pos == goal:
                if first:
                    u.pos = first
                return
            c, r = pos
            for dc, dr in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                nxt = (c + dc, r + dr)
                if not (0 <= nxt[0] < COLS and 0 <= nxt[1] < ROWS):
                    continue
                if nxt in seen or (nxt in occupied and nxt != goal):
                    continue
                seen.add(nxt)
                queue.append((nxt, first or nxt))

    def _strike(self, u: Unit, target: Unit, t: float) -> None:
        # S5 亮粉闪避（施加点）：出手即判定，命中失败 = 整次挥空——伤害/回能/
        # 耗能都不发生，事件流只补一条 miss（渲染契约：attack/cast 数字与
        # 掉血一致）。骰走本场 battle 子流，确定性不受影响
        if target.item_dodge > 0 and self.rng.random() < target.item_dodge:
            self.events.append((t, "miss", u.idx, target.idx))
            return
        move = None
        if u.energy >= ENERGY_MAX and u.piece.move_id:
            move = self.dex.moves[u.piece.move_id]
        if move:  # 放大招
            special = self.dex.move_is_special(move)
            stab = STAB_BONUS if move["type"] in u.piece.types else 1.0
            eff = eff_mult(self.dex.multiplier(move["type"], target.piece.types))
            if self.rng.randrange(100) >= (move.get("accuracy") or 100):
                dmg = 0  # 未命中
            else:
                dmg = _damage(self.rng, u.piece.level, move["power"],
                              u.attack_stat(special), target.defense_stat(special),
                              stab, eff)
                target.energy = min(ENERGY_MAX, target.energy + int(
                    ENERGY_PER_HIT_TAKEN * (1.0 + target.synergy_energy
                                            + target.item_energy)))
            u.energy = 0
            u.casts += 1
            dmg = self._final_damage(u, target, move, dmg)
            self.events.append((t, "cast", u.idx, target.idx,
                                move["name"], round(eff, 2), dmg))
        else:  # 普攻：默认无属性；实验开关下带攻方主属性（本系+克制）
            special = u.sp_attack > u.attack
            if basic_takes_eff():
                stab, eff = STAB_BONUS, eff_mult(
                    self.dex.multiplier(u.piece.types[0], target.piece.types))
            else:
                stab, eff = 1.0, 1.0
            dmg = _damage(self.rng, u.piece.level, BASIC_POWER,
                          u.attack_stat(special), target.defense_stat(special),
                          stab, eff)
            u.energy = min(ENERGY_MAX, u.energy + int(
                ENERGY_PER_ATTACK * (1.0 + u.synergy_energy + u.item_energy)))
            dmg = self._final_damage(u, target, None, dmg)
            self.events.append((t, "attack", u.idx, target.idx, dmg))
        target.hp -= dmg
        u.damage_dealt += dmg
        status_mod.on_hit(self, u, target, move, t)  # S12：几率施加（默认无操作）
        # S5 气势披带（施加点）：致命伤保留 1 HP，一次/场
        if target.hp <= 0 and target.item_sash and not target.item_sash_used:
            target.item_sash_used = True
            target.hp = 1
            self.events.append((t, "sash", target.idx))
        if target.hp <= 0:
            target.hp = 0
            self.events.append((t, "die", target.idx))

    def _final_damage(self, u: Unit, target: Unit, move, dmg: int) -> int:
        """结算尾段：近战减免（均衡实验）→ 羁绊乘区 → 大招承伤上限 → 减伤。

        事件流里的 attack/cast 伤害即此处的最终落地值（渲染契约：
        数字与掉血一致）。羁绊全中性时与旧实现逐点等价。
        """
        dmg = int(dmg * weather_mod.damage_mult(move))  # S11 天气乘区（默认 1.0）
        if target.range == 1:  # 近战受伤减免（均衡实验）
            dmg = int(dmg * (1.0 - melee_resist()))
        # ---- S3 羁绊结算钩子 ----
        dmg = int(dmg * (1.0 + u.synergy_dmg))
        if move is not None:
            dmg = int(dmg * (1.0 + u.synergy_ult_dmg))
            # ---- S5 装备结算钩子（聚光镜大招乘区 / 三色围巾系别乘区）----
            dmg = int(dmg * (1.0 + u.item_ult_dmg))
            if u.item_type_dmg and move["type"] in u.item_type_dmg:
                dmg = int(dmg * (1.0 + u.item_type_dmg[move["type"]]))
            if target.synergy_ult_cap is not None:
                dmg = min(dmg, int(target.max_hp * target.synergy_ult_cap))
        return int(dmg * (1.0 - target.synergy_dr) * (1.0 - target.item_dr))

    def _result(self) -> dict:
        alive = [u for u in self.units if u.alive]
        teams = {u.team for u in alive}
        if len(teams) == 1:
            winner = teams.pop()
        else:  # 超时：按存活 HP 比例判
            frac = {tm: sum(u.hp / u.max_hp for u in alive if u.team == tm)
                    for tm in teams}
            winner = max(frac, key=frac.get) if len(set(frac.values())) > 1 else None
        self.events.append((self.duration, "end", winner))
        return {
            "winner": winner,
            "duration": self.duration,
            "survivors": {tm: sum(1 for u in alive if u.team == tm)
                          for tm in (0, 1)},
            "units": self.units,
        }

