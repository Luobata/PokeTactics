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

事件契约 version=2：attack/cast 的既有字段索引不变；attack 追加攻方、
受方能量，cast 在攻方能量后追加受方能量。每次命中、治疗、DOT、开战后
输出 (t, "unit_state", idx, hp, energy)，这是回放的权威状态。伤害事件仅
描述伤害与演出，不能由其种类推断回能。齐射和侧命中都不回能。
专属附属效果另发 (t, "skill_effect", caster, target, arch, effect, payload)，
payload.cast_index/event_count 指向主 cast 与紧随标记的原事件包；几何快照
和伤害/治疗/能量数值仅供演出，不改变解算，旧事件字段保持原样。
可选搭档事件为 (t, "partner_effect", caster, target, partner_id, effect, payload)；
其治疗、回能仍同时输出 unit_state，attack/cast 索引不变。
显式 tactics_v1 另发 (t, "tactical_effect", source, target, kind, payload)：
护卫 result_event_index 指向最终命中/闪避事件，天气请求 cast_index 指向原生
施法。天气在下一 tick 统一裁决，开始/冲突/结束事件是全场天气的唯一来源。
base_v1 不生成此类事件，也不接受新教学或有效战术配置。

随机契约 v2：仍只消费传入的 rng，但按队伍内容/本地部署顺序绑定抽样，
同刻按开战抽取的 initiative 排序；完全相同的两队先公平掷币绑定随机序列。
交换阵营并旋转棋盘 180° 保持非同构阵容的相同随机试验，旧种子数值会改变。
"""

import random
from contextlib import contextmanager
from data import (ATTACK_INTERVAL_MULT, BASIC_POWER, ENERGY_MAX,
                  ENERGY_PER_ATTACK, ENERGY_PER_HIT_TAKEN, MAX_BATTLE_SECONDS,
                  MOVE_TICK, SPEED_TO_ATTACK_INTERVAL, STAB_BONUS,
                  basic_takes_eff,
                  eff_mult, melee_move_mult, melee_resist, pokedex,
                  ranged_interval_mult)
from roster import Piece
import combo as combo_mod    # S10 组合技 A：默认 COMBOS_ON=False（docs/04）
import synergy  # S3 羁绊：默认 SYNERGIES_ON=False，零随机、零事件流变更
import status as status_mod   # S12 状态/Buff：默认 STATUS_ON=False（docs/06）
import weather as weather_mod  # S11 天气：默认无天气（docs/05）
import abilities as abilities_mod
import items as items_mod     # S5 装备：comp 元素可带 (Piece, item) 二元组（docs/07）
import profiles as profiles_mod  # R1 单体档案（docs/13 §5）：有理由的覆盖项
import skills as skills_mod      # 通用/专属两级技能（2026-10-04 用户裁定）
import partners as partners_mod
import stat_budget
import build_rules
import techniques as techniques_mod
import tactics as tactics_mod
import arena as arena_mod
from weather_control import WeatherController, WEATHER_WINDOW_SECONDS

TICK = 0.1  # 解算步长（秒）
# ---- C-sym 棋盘（docs/10 §1.3/§1.5，2026-09-14 sim 联动落地）----
# 6 列 × 4 行对称战场：行 0-1 敌方战场、行 2-3 己方战场（旧版 7×6 的
# 3+3 纵深收成 2+2）。双方各 1 条备战行是准备页/渲染层概念，不进战斗
# 网格：备战棋子本就不传入 Battle（bots.battle_comp 只含上场名单），
# 无需部署过滤；若把备战行画进网格，要么整行不可通行切断两军通路、
# 要么可通行变成行军走廊，都与「不参战」矛盾。
COLS, ROWS = 6, 4
ROWS_ENEMY = (0, 1)   # 敌方战场行；"back" 从 r=0 后排起填，与己方旋转对称
ROWS_ALLY = (2, 3)    # 己方战场行；"back" 从 r=3 后排起填


class Unit:
    """场上的一名棋子（战斗态）。"""

    def __init__(self, piece: Piece, team: int, pos: tuple,
                 stat_mode: str = "legacy") -> None:
        dex = pokedex()
        base = dex.species[piece.species_id]["base"]
        lv = piece.level
        self.piece = piece
        self.team = team
        self.pos = pos
        # 金银种族值 -> 等级属性（DV15/经验0 的整数化简化）
        self.max_hp = int(2 * base["hp"] * lv / 100) + lv + 10
        self.attack = int(2 * base["attack"] * lv / 100) + 5
        self.defense = int(2 * base["defense"] * lv / 100) + 5
        self.sp_attack = int(2 * base["special_attack"] * lv / 100) + 5
        self.sp_defense = int(2 * base["special_defense"] * lv / 100) + 5
        interval = SPEED_TO_ATTACK_INTERVAL(base["speed"]) \
            * ATTACK_INTERVAL_MULT     # R2 节奏定参：攻速 ×1.5（历史实验钉 1.0）
        self.stat_mode = stat_mode
        self.base_budget = None
        self.budget_points = None
        if stat_mode == "budget_v1":
            panel = stat_budget.unit_stats(piece)
            for name in ("max_hp", "attack", "defense", "sp_attack", "sp_defense"):
                setattr(self, name, panel[name])
            interval = panel["attack_interval"]
            self.base_budget, self.budget_points = panel["budget"], panel["points"]
        elif stat_mode != "legacy":
            raise ValueError("unknown stat mode")
        if profiles_mod.effective_range(piece) > 1:  # 档案覆盖后的远程惩罚
            interval *= ranged_interval_mult()
        self.range = profiles_mod.effective_range(piece)
        self.move_mult = 1.0
        self.ult_arch = None
        self.temp_dr = 0.0          # 通用技能「铁壁」：临时受伤减免
        self.temp_dr_until = -1.0
        self.partner_id = None
        self.partner_trait_uses = 0
        self.technique = None
        self.technique_used = False
        self.partner_dr = 0.0
        self.partner_dr_until = -1.0
        # ---- UnitProfile（docs/13 R1）：有理由的覆盖项，其余回落推导 ----
        prof = profiles_mod.get(piece.species_id)
        if prof is not None:
            if stat_mode == "legacy":
                self.max_hp = int(self.max_hp * prof["hp_mult"])
                interval *= prof["atk_interval_mult"]
            self.move_mult = prof["move_mult"]
        # ---- 两级技能（skills.skill_of）：专属主角团沿用档案原语，
        #      其余单位按定位分配通用原语；开关关闭时 None（旧行为）----
        if self.ult_arch is None:
            self.ult_arch = skills_mod.arch_of(piece.species_id)
        self.hp = self.max_hp
        self.attack_interval = interval
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
        self.needle_used = False
        self.healing_blocks = []  # Bounded: at most one entry per enemy needle.
        self.arena_dr = 0.0
        self.arena_heal_mult = 1.0

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
    rolled = int(base * stab * eff * rng.uniform(0.85, 1.0))
    # Immunity is zero; retain the minimum one only for nonzero effectiveness.
    # Keep consuming the same damage roll even for immune targets.
    return 0 if eff == 0 else max(1, rolled)


class Battle:
    """一场 1v1 自动战斗。rng 由调用方传入，保证可复现（设计宪法第 3 条）。

    events 是双端渲染同步的契约（宪法 2.6）：解算器输出离散事件流，
    Web 预览与设备固件只是同一种子下同一事件流的两种回放端。
    每条事件为 (t, kind, ...)，具体字段与 v2 unit_state 见模块文档。
    """

    def __init__(self, comp_a: list, comp_b: list, rng: random.Random,
                 layout: str = "random", weather_name=None,
                 positions_a=None, positions_b=None, team_options=None,
                 stat_mode: str = "legacy", learned_a=None, learned_b=None,
                 ruleset=tactics_mod.BASE_RULESET, tactics_a=None, tactics_b=None,
                 arena_teams=None) -> None:
        # S11 天气按 Battle 实例持有（2026-09-14 修订：原 set_active 全局写
        # 在验收后台多线程下会交叉污染——/anim 与 /demo 并行时互改对方天气；
        # damage_mult 由 _final_damage 显式传 self.weather_name）
        self.weather_name = weather_name
        self.base_weather_name = weather_name
        self.ruleset = tactics_mod.validate_ruleset(ruleset)
        self._arena_on = self.ruleset == arena_mod.RULESET
        self.cols = COLS
        self.rows = 6 if self._arena_on else ROWS
        self.rows_ally = tuple(range(self.rows // 2, self.rows))
        self.rows_enemy = tuple(range(self.rows // 2))
        if arena_teams is not None and not self._arena_on:
            raise ValueError('arena augments require arena_v1')
        if arena_teams is None:
            arena_teams = ([], [])
        if (not isinstance(arena_teams, (list, tuple)) or len(arena_teams) != 2
                or any(not isinstance(row, (list, tuple)) for row in arena_teams)):
            raise ValueError('arena_teams must contain two augment lists')
        for row in arena_teams:
            if (any(not isinstance(key, str) or key not in arena_mod.AUGMENTS for key in row)
                    or len(set(row)) != len(row) or len(row) > 3):
                raise ValueError('unknown, repeated, or excessive arena augments')
        self.arena_teams = tuple(tuple(sorted(row)) for row in arena_teams)
        self._tactics_on = tactics_mod.enabled(self.ruleset)
        if self._tactics_on and weather_name not in weather_mod.WEATHERS:
            raise ValueError("unknown base weather")
        self._weather_control = (WeatherController(weather_name, TICK)
                                 if self._tactics_on else None)
        self._guard_links = {}
        self._guard_used = set()
        self._weather_sources = {}
        self._weather_used = set()
        if stat_mode not in ("legacy", "budget_v1"):
            raise ValueError("unknown stat mode")
        self.stat_mode = stat_mode
        if team_options is None:
            team_options = (None, None)
        if not isinstance(team_options, (tuple, list)) or len(team_options) != 2:
            raise ValueError("team_options must contain two team loadouts")
        if any(option is not None and not isinstance(option, dict) for option in team_options):
            raise ValueError("each team loadout must be a dictionary or None")
        self.team_options = tuple(partners_mod.validate_loadout(option)
                                  for option in team_options)
        self.rng = rng
        self.dex = pokedex()
        self.units: list = []
        self.events: list = []
        self.event_version = 2
        self._dead = set()
        comps = (comp_a, comp_b)
        self.learned = tuple(self._validate_learning(comp, learned)
                             for comp, learned in zip(comps, (learned_a, learned_b)))
        self.tactics = tuple(tactics_mod.validate_team(selection, len(comp), self.ruleset)
                             for comp, selection in zip(comps, (tactics_a, tactics_b)))
        positions = (positions_a, positions_b)
        for team in (0, 1):
            self._validate_positions(comps[team], positions[team], team)
        keys = [self._deployment_key(comps[team], positions[team], team)
                for team in (0, 1)]
        if keys[0] == keys[1]:
            first = self.rng.randrange(2)
            team_order = (first, 1 - first)
        else:
            team_order = tuple(sorted((0, 1), key=lambda team: keys[team]))
        self._team_order = team_order
        plans = {}
        for team in team_order:
            cells = [(c, r) for r in self.rows_ally for c in range(self.cols)]
            if positions[team] is not None:
                spots = [self._local_pos(p, team) for p in positions[team]]
            elif layout == "random":
                spots = self.rng.sample(cells, len(comps[team]))
            else:
                spots = sorted(cells, key=lambda p: (-p[1], p[0]))[:len(comps[team])]
            plans[team] = [(self._local_pos(p, team), self.rng.uniform(0, 0.3),
                            self.rng.random()) for p in spots]
        self._deploy(comp_a, team=0, plan=plans[0])
        self._deploy(comp_b, team=1, plan=plans[1])
        for team, option in enumerate(self.team_options):
            if option is not None:
                family = partners_mod.family_ids(option["partner"])
                partner = next((u for u in self.units if u.team == team
                                and u.piece.species_id in family), None)
                if partner is not None:
                    partner.partner_id = option["partner"]
                    if partner.technique is None:
                        partner.technique = option["technique"]
        self._bind_tactics()
        # S5 协议：comp 元素可能带 (Piece, item) 二元组——羁绊/齐射只看裸 Piece
        plain_a = [e[0] if isinstance(e, tuple) else e for e in comp_a]
        plain_b = [e[0] if isinstance(e, tuple) else e for e in comp_b]
        self._plain_comps = (plain_a, plain_b)  # S10 齐射计数用（deploy 后不变）
        if synergy.synergies_on():  # S3：按场上当前形态一次性结算（无随机）
            synergy.apply([u for u in self.units if u.team == 0], plain_a)
            synergy.apply([u for u in self.units if u.team == 1], plain_b)
        status_mod.init_battle(self)  # S12：状态容器（默认无操作）
        if self._arena_on:
            self._apply_arena_stats()
        self.duration = 0.0
        for unit in self.units:
            self._emit_state(unit, 0.0)
        self._opening_partner_traits()
        self._opening_abilities()

    def _apply_arena_stats(self):
        for unit in self.units:
            piece = unit.piece
            if piece.species_id not in arena_mod.ROSTER:
                raise ValueError('species is outside the arena pool')
            star = getattr(piece, 'star', 1)
            role = arena_mod.ROSTER[piece.species_id][1]
            if type(star) is not int or not 1 <= star <= 3:
                raise ValueError('arena star must be 1, 2, or 3')
            if getattr(piece, 'role_key', role) != role:
                raise ValueError('arena role must match the species')
            unit.arena_role = role
            augments = self.arena_teams[unit.team]
            hp_mult = (1., 1.6, 2.5)[star - 1]
            atk_mult = hp_mult * {'attack': 1.12, 'defense': .85, 'support': .8}[role]
            if role == 'defense':
                hp_mult *= 1.25
                unit.arena_dr = .18
            if 'sharp_focus' in augments:
                atk_mult *= 1.12
            if 'vitality' in augments:
                hp_mult *= 1.15
            if 'iron_wall' in augments:
                unit.arena_dr = 1 - (1 - unit.arena_dr) * .92
            if 'quick_step' in augments:
                unit.attack_interval /= 1.12
            if 'mana_flow' in augments:
                unit.energy = min(ENERGY_MAX, unit.energy + 20)
            if 'first_aid' in augments:
                unit.arena_heal_mult = 1.3
            unit.max_hp = max(1, int(unit.max_hp * hp_mult))
            unit.hp = unit.max_hp
            unit.attack = max(1, int(unit.attack * atk_mult))
            unit.sp_attack = max(1, int(unit.sp_attack * atk_mult))

    def _arena_support(self, t):
        for healer in sorted(self.units, key=lambda u: u.initiative):
            if (not healer.alive or healer.arena_role != 'support'
                    or status_mod.stunned(healer, t)):
                continue
            candidates = [u for u in self.units if u.alive and u.team == healer.team
                          and u.hp < u.max_hp]
            if not candidates:
                continue
            target = min(candidates, key=lambda u: (
                u.hp / u.max_hp, self._local_pos(u.pos, healer.team), u.local_idx))
            amount = max(1, int(target.max_hp * .08 * healer.arena_heal_mult))
            healed = self._heal(target, amount, t)
            if healed:
                self.events.append((t, 'arena_heal', healer.idx, target.idx,
                                    healed, healer.piece.species_id))

    def _validate_learning(self, comp, learned):
        if learned is None:
            return (None,) * len(comp)
        if not isinstance(learned, list) or len(learned) != len(comp):
            raise ValueError("learned techniques must be a list matching the team's unit count")
        return tuple(techniques_mod.validate_learning(
            (entry[0] if isinstance(entry, tuple) else entry).species_id, technique,
            ruleset=self.ruleset)
            for entry, technique in zip(comp, learned))

    def _bind_tactics(self):
        """Bind explicit local indices once; dead/invalid sources never relay."""
        for team, selection in enumerate(self.tactics):
            units = [unit for unit in self.units if unit.team == team]
            guard = selection["guard"]
            if guard is not None:
                source, target = units[guard["source"]], units[guard["target"]]
                if source.technique != "guard":
                    raise ValueError("selected guard must have learned guard")
                if _manhattan(source.pos, target.pos) != 1:
                    raise ValueError("guard and protected ally must deploy adjacent")
                self._guard_links[team] = (source, target)
            weather = selection["weather"]
            if weather is not None:
                source = units[weather["source"]]
                if source.technique not in ("sunny_day", "rain_dance"):
                    raise ValueError("selected weather source must know weather teaching")
                self._weather_sources[team] = source

    def _local_pos(self, pos, team):
        return tuple(pos) if team == 0 else (self.cols - 1 - pos[0], self.rows - 1 - pos[1])

    def _validate_positions(self, comp, positions, team):
        if len(comp) > self.cols * (self.rows // 2):
            raise ValueError(f'a team cannot deploy more than {self.cols * (self.rows // 2)} units')
        if positions is None:
            return
        if len(positions) != len(comp):
            raise ValueError("positions must match the team's unit count")
        rows = self.rows_ally if team == 0 else self.rows_enemy
        cells = []
        for pos in positions:
            if (not isinstance(pos, (tuple, list)) or len(pos) != 2
                    or any(type(n) is not int for n in pos)
                    or not 0 <= pos[0] < self.cols or pos[1] not in rows):
                raise ValueError("positions must be integer cells in the team's own rows")
            cells.append(tuple(pos))
        if len(set(cells)) != len(cells):
            raise ValueError("positions must be unique within a team")

    def _deployment_key(self, comp, positions, team):
        entries = []
        for entry in comp:
            piece, item = entry if isinstance(entry, tuple) else (entry, None)
            entries.append((piece.species_id, piece.tier, piece.level,
                            piece.move_id or 0, piece.distance, str(item)))
        local = tuple(self._local_pos(p, team) for p in positions) if positions is not None else ()
        option = self.team_options[team]
        # An absent partner has no combat or random-sequence effect. For present
        # partners, bind rolls to the loadout too, preserving rotated side swaps.
        partner_index = next((index for index, entry in enumerate(entries)
                              if option is not None and entry[0] in
                              partners_mod.family_ids(option["partner"])), None)
        active = partner_index is not None
        effective_technique = (option["technique"] if active and
                               self.learned[team][partner_index] is None else None)
        loadout = (option["partner"], effective_technique or "") if active else (0, "")
        # Keep the original random ordering for every unlearned legacy team.
        # A learned skill becomes part of identity only when actually present.
        learning = tuple(technique or "" for technique in self.learned[team])
        if self._tactics_on:
            selection = self.tactics[team]
            guard, weather = selection["guard"], selection["weather"]
            chosen = ((guard["source"], guard["target"]) if guard else (),
                      (weather["source"],) if weather else ())
            return tuple(entries), local, loadout, learning, chosen
        if self._arena_on:
            stars = tuple(getattr((e[0] if isinstance(e, tuple) else e), 'star', 1) for e in comp)
            return tuple(entries), local, loadout, learning, stars, self.arena_teams[team]
        if any(learning):
            return tuple(entries), local, loadout, learning
        return tuple(entries), local, loadout

    def _deploy(self, comp: list, team: int, plan: list) -> None:
        for local_idx, (entry, (pos, next_act, initiative)) in enumerate(zip(comp, plan)):
            # S5 装备协议：comp 元素可为 (Piece, item_key) 二元组（带装备）或
            # 裸 Piece（无装备——prototype/野怪波次走此路径，行为不变）
            piece, item_key = entry if isinstance(entry, tuple) else (entry, None)
            if item_key is not None and item_key not in items_mod.catalog(self.ruleset):
                raise ValueError('equipment unavailable in this ruleset')
            unit = Unit(piece, team, pos, stat_mode=self.stat_mode)
            unit.technique = self.learned[team][local_idx]
            if item_key is not None:   # S5 施加点（S3 synergy.apply 同模式）
                items_mod.apply_to_unit(unit, item_key)
                build_rules.apply_item_rules(unit, item_key)
            unit.next_act = next_act
            unit.initiative = initiative
            unit.local_idx = local_idx
            unit.idx = len(self.units)
            self.units.append(unit)
            self.events.append((0.0, "deploy", unit.idx, pos))

    # ---- 主循环 ----
    def run(self) -> dict:
        t = 0.0
        if combo_mod.combos_on():   # S10 齐射：deploy 后 t=0 的开场组合招
            self._opening_volley()
        # S3 持续羁绊（水之治疗等）+ S5 剩饭：每 1s 一跳；v1 不入事件流
        regen_units = [u for u in self.units
                       if u.synergy_heal > 0 or u.item_heal > 0]
        next_regen = 1.0
        next_support = 4.0
        while t <= MAX_BATTLE_SECONDS:
            self.duration = t
            alive_teams = {u.team for u in self.units if u.alive}
            if len(alive_teams) <= 1:
                break
            self.flush_tactics(t)
            for u in sorted(self.units, key=lambda x: (x.next_act, x.initiative)):
                if u.alive and t + 1e-9 >= u.next_act:
                    self._act(u, t)
            if regen_units and t + 1e-9 >= next_regen:
                for u in regen_units:
                    if u.alive and u.hp < u.max_hp:
                        self._heal(u, max(1, int(u.max_hp * (
                            u.synergy_heal + u.item_heal))), t)
                next_regen += 1.0
            if self._arena_on and t + 1e-9 >= next_support:
                self._arena_support(t)
                next_support += 4.0
            status_mod.tick(self, t)  # S12：DOT/到期（默认无操作）
            t += TICK
        return self._result()

    def _act(self, u: Unit, t: float) -> None:
        if status_mod.stunned(u, t):  # S12：冰冻/睡眠期间不行动（默认 False）
            u.next_act = t + 0.2
            return
        if (u.technique == "rest" and not u.technique_used
                and u.hp <= u.max_hp / 2):
            u.technique_used = True
            self._partner_heal(u, u, .25, t, "rest")
            u.next_act = t + u.attack_interval * status_mod.speed_mult(u)
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
            step = MOVE_TICK * (melee_move_mult() if u.range == 1 else 1.0) \
                * u.move_mult                      # R1 档案移速（卡比兽 0.85）
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
        near = min(enemies, key=lambda e: self._target_key(u, e))
        u.target_idx = near.idx
        return near

    def _target_key(self, u, target):
        return (_manhattan(u.pos, target.pos), self._local_pos(target.pos, u.team),
                target.local_idx)

    def _opening_volley(self) -> None:
        """Both teams launch from the same pre-volley state; casualties cannot cancel shots.

        Resolve the precomputed shots in canonical team order. Each target is selected
        before damage, so a first team's kills cannot steal the other team's opening.
        Combo attacks deliberately grant neither attacker nor defender energy.
        """
        pending = []
        for team in self._team_order:
            mates = [u for u in self.units if u.team == team]
            for volley in combo_mod.opening_volley(mates, self._plain_comps[team], self.dex):
                self.events.append((0.0, "combo", team, volley["type"], volley["name"]))
                move = {"type": volley["type"], "name": volley["name"]}
                for unit, power in volley["shots"]:
                    enemies = [e for e in self.units if e.alive and e.team != team]
                    if not unit.alive or not enemies:
                        continue
                    target = min(enemies, key=lambda e: self._target_key(unit, e))
                    unit.target_idx = target.idx
                    damage = self._move_damage(unit, target, {**move, "power": power})
                    pending.append((unit, target, damage))
        for unit, target, damage in pending:
            self._land_hit(unit, target, damage, 0.0)

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
            for dc, dr in self._directions(u.team):
                nxt = (c + dc, r + dr)
                if not (0 <= nxt[0] < self.cols and 0 <= nxt[1] < self.rows):
                    continue
                if nxt in seen or (nxt in occupied and nxt != goal):
                    continue
                seen.add(nxt)
                queue.append((nxt, first or nxt))

    @staticmethod
    def _directions(team):
        directions = ((0, -1), (0, 1), (-1, 0), (1, 0))
        return directions if team == 0 else tuple((-dc, -dr) for dc, dr in directions)

    def _move_damage(self, unit, target, move, fraction=1.0):
        """Each hit owns its target's defense/type calculation and one modifier chain."""
        special = (unit.sp_attack > unit.attack if move.get("damage_stat") == "best"
                   else self.dex.move_is_special(move))
        stab = STAB_BONUS if move["type"] in unit.piece.types else 1.0
        eff = eff_mult(self.dex.multiplier(move["type"], target.piece.types))
        raw = _damage(self.rng, unit.piece.level, move["power"],
                      unit.attack_stat(special), target.defense_stat(special), stab, eff)
        return self._final_damage(unit, target, move, int(raw * fraction))

    def _strike(self, u: Unit, target: Unit, t: float) -> None:
        if self._tactics_on:
            self.flush_tactics(t)
            if not u.alive:
                return
        start_pos = u.pos
        move = build_rules.resolve_cast(u.piece, self.stat_mode) if u.energy >= ENERGY_MAX else None
        if move and build_rules.energy_targeting(u.piece, self.stat_mode):
            # Retarget only the cast. Basic attacks retain their normal lock;
            # a nearby Normal shield can still absorb the Ghost cast for zero.
            candidates = [e for e in self.units if e.alive and e.team != u.team
                          and _manhattan(u.pos, e.pos) <= u.range]
            target = min(candidates, key=lambda e: (-e.energy, self._target_key(u, e)),
                         default=target)
        if move and u.ult_arch == profiles_mod.ARCH_BLINK:
            weakest = min((e for e in self.units if e.alive and e.team != u.team),
                          key=lambda e: (e.hp, self._target_key(u, e)), default=None)
            if weakest is not None:
                cell = self._free_cell_near(weakest.pos, avoid=u.pos, team=u.team)
                if cell is not None:
                    u.pos = cell
                    self.events.append((t, "move", u.idx, u.pos))
                    target = weakest
                    u.target_idx = weakest.idx
                # No landing cell: retain the original in-range target.
        if move and u.ult_arch == "charge":
            enemies = [e for e in self.units if e.alive and e.team != u.team]
            farthest = min(enemies, key=lambda e: (-_manhattan(u.pos, e.pos),
                           self._target_key(u, e)[1:]), default=None)
            if farthest is not None and farthest is not target:
                start, path = u.pos, []
                for _ in range(2):
                    if _manhattan(u.pos, farthest.pos) <= 1:
                        break
                    old = u.pos
                    self._step_toward(u, farthest.pos)
                    if u.pos == old:
                        break
                    path.append(u.pos)
                if _manhattan(u.pos, farthest.pos) <= 1:
                    for pos in path:
                        self.events.append((t, "move", u.idx, pos))
                    target = farthest
                    u.target_idx = farthest.idx
                else:
                    u.pos = start  # Unreachable within budget: ordinary in-range cast.
        if not target.alive or _manhattan(u.pos, target.pos) > u.range:
            return
        guard_payload = None
        if (self._tactics_on and move and u.pos != start_pos
                and u.ult_arch in ("charge", profiles_mod.ARCH_BLINK)):
            target, guard_payload = self._intercept(u, target, t, start_pos)
        if target.item_dodge > 0 and self.rng.random() < target.item_dodge:
            if guard_payload is not None:
                guard_payload["result_event_index"] = len(self.events)
            self.events.append((t, "miss", u.idx, target.idx))
            return
        if move:
            # Geometry is fixed before damage/death/displacement changes occupancy.
            cast_target_pos = target.pos
            line_victims = self._line_victims(u, target) if u.ult_arch == profiles_mod.ARCH_LINE else []
            hit = self.rng.randrange(100) < (move.get("accuracy") or 100)
            dmg = self._move_damage(u, target, move) if hit else 0
            u.energy = 0
            u.casts += 1
            hp_before = target.hp
            cast_index = len(self.events)
            if guard_payload is not None:
                guard_payload["result_event_index"] = cast_index
            self._land_hit(u, target, dmg, t, move=move, primary=True, cast=True)
            lost_hp = max(0, hp_before - target.hp)
            # Side hits are independent damage calculations. The primary hit is
            # already resolved, so a lethal first hit never emits a second death.
            if dmg > 0 and u.ult_arch in (profiles_mod.ARCH_SPLASH, profiles_mod.ARCH_SLAM):
                anchor = target.pos if u.ult_arch == profiles_mod.ARCH_SPLASH else u.pos
                victims = sorted((v for v in self.units if v.alive and v.team != u.team
                                  and v is not target and _manhattan(v.pos, anchor) <= 1),
                                 key=lambda v: self._target_key(u, v))
                for victim in victims:
                    self._land_hit(u, victim, self._move_damage(
                        u, victim, move, profiles_mod.SIDE_HIT_FRAC), t)
            if dmg > 0 and u.ult_arch == profiles_mod.ARCH_SLAM and u.alive:
                self._heal(u, int(u.max_hp * profiles_mod.SLAM_SELF_HEAL), t)
            if dmg > 0 and u.ult_arch == profiles_mod.ARCH_LINE:
                for victim in line_victims:
                    side_damage = self._move_damage(u, victim, move, profiles_mod.LINE_SIDE_FRAC)
                    with self._skill_effect(u, victim, "side_hit", t, cast_index,
                                            damage=side_damage, origin_idx=u.idx):
                        self._land_hit(u, victim, side_damage, t)
                if target.alive:
                    away = self._knock_cell(target, u.pos)
                    if away is not None:
                        with self._skill_effect(u, target, "knockback", t, cast_index,
                                                origin=target.pos, destination=away):
                            target.pos = away
                            self.events.append((t, "move", target.idx, target.pos))
            if lost_hp > 0 and u.ult_arch == profiles_mod.ARCH_SOLAR:
                wounded = [v for v in self.units if v.alive and v.team == u.team
                           and v.hp < v.max_hp and _manhattan(u.pos, v.pos) <= 2]
                patient = min(wounded, key=lambda v: (
                    v.hp / v.max_hp, self._target_key(u, v)), default=None)
                if patient is not None:
                    healed = min(patient.max_hp - patient.hp,
                                 int(lost_hp * profiles_mod.SOLAR_HEAL_FRAC))
                    with self._skill_effect(u, patient, "heal", t, cast_index,
                                            amount=self._healing_amount(patient, healed, t)[0],
                                            origin_idx=target.idx):
                        self._heal(patient, healed, t)
            if dmg > 0 and u.ult_arch == profiles_mod.ARCH_CHAIN:
                previous, struck = target, {target.idx}
                for hop, fraction in enumerate(profiles_mod.CHAIN_FRACS, 1):
                    nearby = [v for v in self.units if v.alive and v.team != u.team
                              and v.idx not in struck and _manhattan(previous.pos, v.pos) <= 2]
                    victim = min(nearby, key=lambda v: (
                        _manhattan(previous.pos, v.pos), self._target_key(u, v)), default=None)
                    if victim is None:
                        break
                    struck.add(victim.idx)
                    side_damage = self._move_damage(u, victim, move, fraction)
                    with self._skill_effect(u, victim, "side_hit", t, cast_index,
                                            damage=side_damage, origin_idx=previous.idx, hop=hop):
                        self._land_hit(u, victim, side_damage, t)
                    if side_damage <= 0:  # Ground immunity interrupts conduction.
                        break
                    previous = victim
            if dmg > 0 and u.ult_arch == profiles_mod.ARCH_DRAIN:
                # Transfer after primary hit energy; odd stolen values round down.
                stolen = min(profiles_mod.ENERGY_DRAIN_MAX, target.energy)
                if stolen:
                    gained = min(ENERGY_MAX - u.energy, stolen // 2)
                    with self._skill_effect(u, target, "energy_drain", t, cast_index,
                                            stolen=stolen, gained=gained, origin_idx=target.idx):
                        target.energy -= stolen
                        u.energy += gained
                        self._emit_state(u, t)
                        self._emit_state(target, t)
            if hit and u.ult_arch == profiles_mod.ARCH_QUAKE:
                if lost_hp > 0:
                    with self._skill_effect(u, target, "flinch", t, cast_index,
                                            duration=status_mod.DEBUFFS["flinch"]["dur"]):
                        status_mod.apply_flinch(self, target, t)
                victims = sorted((v for v in self.units if v.alive and v.team != u.team
                                  and v is not target and _manhattan(v.pos, u.pos) <= 1),
                                 key=lambda v: self._target_key(u, v))
                for victim in victims:
                    hp_before = victim.hp
                    side_damage = self._move_damage(u, victim, move, profiles_mod.QUAKE_SIDE_FRAC)
                    with self._skill_effect(u, victim, "side_hit", t, cast_index,
                                            damage=side_damage, origin_idx=u.idx):
                        self._land_hit(u, victim, side_damage, t)
                    if victim.hp < hp_before:
                        with self._skill_effect(u, victim, "flinch", t, cast_index,
                                                duration=status_mod.DEBUFFS["flinch"]["dur"]):
                            status_mod.apply_flinch(self, victim, t)
            if dmg > 0 and u.ult_arch == "heavy_blow" and target.alive:
                away = self._knock_cell(target, u.pos)
                if away is not None:
                    target.pos = away
                    self.events.append((t, "move", target.idx, target.pos))
            if dmg > 0 and u.ult_arch == "double_strike" and target.alive:
                self._land_hit(u, target, self._move_damage(u, target, move, 0.45), t)
            if dmg > 0 and u.ult_arch == "volley_shot":
                others = sorted((v for v in self.units if v.alive and v.team != u.team
                                 and v is not target), key=lambda v: (
                                     _manhattan(v.pos, target.pos), self._target_key(u, v)))
                for victim in others[:2]:
                    self._land_hit(u, victim, self._move_damage(u, victim, move, 0.40), t)
            if u.ult_arch == "bulwark" and u.alive:
                u.temp_dr = 0.35
                u.temp_dr_until = t + 3.0
            if u.ult_arch == "mend" and u.alive:
                self._heal(u, int(u.max_hp * 0.20), t)
            self._partner_after_cast(u, target, t, cast_target_pos, dmg > 0)
            self._request_weather(u, t, cast_index)
            if guard_payload is not None:
                guard_payload["result_event_count"] = len(self.events) - cast_index - 1
        else:
            special = u.sp_attack > u.attack
            if basic_takes_eff():
                stab, eff = STAB_BONUS, eff_mult(
                    self.dex.multiplier(u.piece.types[0], target.piece.types))
            else:
                stab, eff = 1.0, 1.0
            raw = _damage(self.rng, u.piece.level, BASIC_POWER,
                          u.attack_stat(special), target.defense_stat(special), stab, eff)
            dmg = self._final_damage(u, target, None, raw)
            if dmg > 0:
                u.energy = min(ENERGY_MAX, u.energy + int(
                    ENERGY_PER_ATTACK * (1.0 + u.synergy_energy + u.item_energy)))
            self._land_hit(u, target, dmg, t, primary=True)
            if dmg > 0:
                self._partner_after_basic(u, target, t)

    def _intercept(self, attacker, target, t, start_pos):
        """Redirect one legal displaced cast, before any accuracy/dodge roll.

        This sole hit may reach a guard two cells away. The attacker's target
        lock, normal range, position, and future attacks are not changed.
        """
        link = self._guard_links.get(target.team)
        if (link is None or target.team in self._guard_used
                or attacker.team == target.team):
            return target, None
        source, protected = link
        if (target is not protected or not source.alive
                or _manhattan(source.pos, protected.pos) != 1
                or _manhattan(attacker.pos, source.pos) > 2):
            return target, None
        self._guard_used.add(source.team)
        source.technique_used = True
        payload = {"reason": "intercept", "remaining": 0,
                   "attacker_idx": attacker.idx, "recipient_idx": source.idx,
                   "source_pos": source.pos, "target_pos": protected.pos,
                   "attacker_pos": attacker.pos, "attacker_origin": start_pos,
                   "result_event_index": None, "result_event_count": 0}
        self.events.append((t, "tactical_effect", source.idx, protected.idx, "guard", payload))
        return source, payload

    def _request_weather(self, unit, t, cast_index):
        if (not self._tactics_on or self._weather_sources.get(unit.team) is not unit
                or unit.team in self._weather_used or unit.casts != 1):
            return
        self._weather_used.add(unit.team)
        unit.technique_used = True
        weather = {"sunny_day": "sun", "rain_dance": "rain"}[unit.technique]
        request = self._weather_control.request(t, unit.team, unit.idx, unit.pos,
                                                weather, cast_index)
        payload = {"reason": "queued", "requests": [request], "remaining": 0,
                   "source_pos": unit.pos, "target_pos": unit.pos,
                   "cast_index": cast_index, "weather": weather,
                   "old_weather": self.weather_name, "new_weather": weather,
                   "base_weather": self.base_weather_name,
                   "effective_at": request["effective_at"],
                   "expires_at": round(request["effective_at"] + WEATHER_WINDOW_SECONDS, 9)}
        self.events.append((t, "tactical_effect", unit.idx, unit.idx,
                            "weather_request", payload))

    def _opening_abilities(self):
        if not tactics_mod.entry_abilities_enabled(self.ruleset):
            return
        for unit in self.units:
            ability = abilities_mod.for_species(unit.piece.species_id, self.ruleset)
            if not unit.alive or ability is None:
                continue
            request = self._weather_control.request_entry(
                unit.team, unit.idx, unit.pos, ability["weather"], ability["id"])
            payload = {"reason": "entry", "requests": [request], "remaining": 0,
                       "source_kind": "ability", "ability_id": ability["id"],
                       "source_pos": unit.pos, "target_pos": unit.pos,
                       "cast_index": None, "weather": ability["weather"],
                       "old_weather": self.weather_name, "new_weather": ability["weather"],
                       "base_weather": self.base_weather_name,
                       "effective_at": 0.0, "expires_at": WEATHER_WINDOW_SECONDS}
            self.events.append((0.0, "tactical_effect", unit.idx, unit.idx,
                                "weather_request", payload))
        # All opening abilities contend together, including same-team conflicts.
        # Neither traversal order nor later calls to run() can repeat them.
        self.flush_tactics(0.0)

    def flush_tactics(self, t):
        """Advance weather before tick actions; direct-strike callers may use it.

        Requests made during the current tick remain pending, so this is safe
        to call more than once or between strikes at the same timestamp. New
        weather never changes damage from the cast that requested it.
        """
        if self._weather_control is None:
            return []
        emitted = []
        for transition in self._weather_control.advance(t):
            requests = sorted(transition["requests"], key=lambda row: (
                self._team_order.index(row["team"]), self.units[row["source"]].local_idx))
            source = requests[0]
            payload = {key: value for key, value in transition.items()
                       if key not in ("kind", "time", "requests")}
            payload.update(requests=requests, source_pos=source["source_pos"],
                           target_pos=source["source_pos"])
            event = (transition["time"], "tactical_effect", source["source"],
                     source["source"], transition["kind"], payload)
            self.events.append(event)
            emitted.append(event)
        self.weather_name = self._weather_control.weather_name
        return emitted

    def _land_hit(self, attacker, target, damage, t, move=None, primary=False, cast=False):
        """Resolve a damage packet and emit its authoritative post-hit state.

        Only primary attacks/casts grant defender energy and apply statuses. A
        prelaunched combo may arrive after its sender/target died; no resurrection
        or repeat death is possible, and the attack still records that launched shot.
        """
        if primary and damage > 0 and target.alive:
            target.energy = min(ENERGY_MAX, target.energy + int(
                ENERGY_PER_HIT_TAKEN * (1.0 + target.synergy_energy + target.item_energy)))
        if cast:
            eff = eff_mult(self.dex.multiplier(move["type"], target.piece.types))
            self.events.append((t, "cast", attacker.idx, target.idx, move["name"],
                                round(eff, 2), damage, attacker.energy, target.energy))
        else:
            self.events.append((t, "attack", attacker.idx, target.idx, damage,
                                attacker.energy, target.energy))
        hp_before = max(0, target.hp)
        target.hp -= damage
        self._death_check(target, t)
        attacker.damage_dealt += max(0, hp_before - target.hp)
        self._emit_state(attacker, t)
        self._emit_state(target, t)
        if cast and primary and hp_before > target.hp:
            self._apply_healing_needle(attacker, target, t)
        if primary:
            status_mod.on_hit(self, attacker, target, move, t, damage=damage)
        if (damage > 0 and target.alive and target.partner_id == 143
                and target.partner_trait_uses == 0 and target.hp <= target.max_hp / 2):
            target.partner_trait_uses += 1
            for mate in self._partner_mates(target, wounded=True)[:2]:
                self._partner_heal(target, mate, .15, t, "share_lunch")

    def _partner_mates(self, unit, wounded=False):
        mates = [mate for mate in self.units if mate is not unit and mate.alive
                 and mate.team == unit.team and _manhattan(unit.pos, mate.pos) <= 2
                 and (not wounded or mate.hp < mate.max_hp)]
        return sorted(mates, key=lambda mate: (
            (mate.hp / mate.max_hp if wounded else 0), self._target_key(unit, mate)))

    def _partner_event(self, unit, target, effect, t, **payload):
        """Optional annotation; HP and energy remain authoritative unit_state data."""
        self.events.append((t, "partner_effect", unit.idx, target.idx,
                            unit.partner_id, effect, payload))

    def _partner_heal(self, unit, target, fraction, t, effect):
        amount = min(target.max_hp - target.hp, int(target.max_hp * fraction))
        if amount > 0 and target.alive:
            self._partner_event(unit, target, effect, t,
                                amount=self._healing_amount(target, amount, t)[0])
            self._heal(target, amount, t)

    def _partner_energy(self, unit, target, amount, t, effect):
        gained = min(ENERGY_MAX - target.energy, amount)
        if gained > 0:
            self._partner_event(unit, target, effect, t, energy=gained)
            target.energy += gained
            self._emit_state(target, t)

    def _opening_partner_traits(self):
        for team in self._team_order:
            for unit in self.units:
                if unit.team != team or unit.partner_id != 9:
                    continue
                unit.partner_trait_uses = 1
                for mate in self._partner_mates(unit)[:2]:
                    mate.partner_dr, mate.partner_dr_until = .20, 6.0
                    self._partner_event(unit, mate, "shell_guard", 0.0,
                                        reduction=.20, duration=6.0)

    def _partner_after_cast(self, unit, target, t, target_pos, caused_damage):
        if unit.partner_trait_uses == 0 and unit.partner_id in (3, 6):
            unit.partner_trait_uses = 1
            if unit.partner_id == 3:
                for mate in self._partner_mates(unit, wounded=True)[:1]:
                    self._partner_heal(unit, mate, .20, t, "bloom")
            elif unit.partner_id == 6:
                for mate in self._partner_mates(unit)[:2]:
                    self._partner_energy(unit, mate, 18, t, "wing_rally")
        if unit.technique == "surf" and not unit.technique_used and caused_damage:
            unit.technique_used = True
            victims = sorted((enemy for enemy in self.units if enemy.alive
                              and enemy.team != unit.team and enemy is not target
                              and _manhattan(target_pos, enemy.pos) <= 1),
                             key=lambda enemy: self._target_key(unit, enemy))
            for victim in victims[:2]:
                move = {"name": "surf" if self._arena_on else "冲浪", "type": "WATER", "power": 35}
                damage = self._move_damage(unit, victim, move)
                self._partner_event(unit, victim, "surf", t, damage=damage)
                self._land_hit(unit, victim, damage, t, move=move, cast=self._arena_on)

    def _partner_after_basic(self, unit, target, t):
        if unit.partner_id == 26 and unit.partner_trait_uses < 2:
            unit.partner_trait_uses += 1
            mate = min(self._partner_mates(unit), key=lambda candidate: (
                candidate.energy, self._target_key(unit, candidate)), default=None)
            if mate is not None:
                self._partner_energy(unit, mate, 16, t, "relay")
        if unit.technique == "cut" and not unit.technique_used:
            unit.technique_used = True
            victim = min((enemy for enemy in self.units if enemy.alive
                          and enemy.team != unit.team and enemy is not target
                          and _manhattan(target.pos, enemy.pos) <= 1),
                         key=lambda enemy: self._target_key(unit, enemy), default=None)
            if victim is not None:
                move = {"name": "cut" if self._arena_on else "居合斩", "type": "NORMAL", "power": 35}
                damage = self._move_damage(unit, victim, move)
                self._partner_event(unit, victim, "cut", t, damage=damage)
                self._land_hit(unit, victim, damage, t, move=move, cast=self._arena_on)
        if self._arena_on:
            from arena_teaching import after_basic
            after_basic(self, unit, target, t)

    @contextmanager
    def _skill_effect(self, caster, target, effect, t, cast_index, **details):
        """Annotate a finite effect packet without changing any legacy event ABI.

        cast_index is an absolute index into the original Battle.events stream;
        event_count identifies exactly the following events owned by this effect.
        Playback can bind third-party heals/movement to their real cast, even if
        a second unrelated action shares this timestamp. Empty effects disappear.
        """
        origin_idx = details.get("origin_idx", caster.idx)
        payload = {"cast_index": cast_index, "event_count": 0,
                   "origin_idx": origin_idx, "origin_pos": self.units[origin_idx].pos,
                   "target_pos": target.pos, "caster_pos": caster.pos, **details}
        marker_index = len(self.events)
        self.events.append((t, "skill_effect", caster.idx, target.idx,
                            caster.ult_arch, effect, payload))
        yield
        payload["event_count"] = len(self.events) - marker_index - 1
        if not payload["event_count"]:
            self.events.pop()

    def _line_victims(self, attacker, target):
        """Snapshot a one-cell-wide forward ray, continuing to the board edge.

        The lane has perpendicular half-width 0.5 cells and excludes positions
        behind/on the caster's perpendicular plane. At most two other enemies,
        ordered by forward projection, are selected before any hit or knockback.
        Integer squared cross products keep diagonal boundaries deterministic.
        """
        dx, dy = target.pos[0] - attacker.pos[0], target.pos[1] - attacker.pos[1]
        length_sq = dx * dx + dy * dy
        if not length_sq:
            return []
        candidates = []
        for victim in self.units:
            if not victim.alive or victim.team == attacker.team or victim is target:
                continue
            vx, vy = victim.pos[0] - attacker.pos[0], victim.pos[1] - attacker.pos[1]
            projection, cross = vx * dx + vy * dy, vx * dy - vy * dx
            if projection > 0 and 4 * cross * cross <= length_sq:
                candidates.append((projection, self._target_key(attacker, victim), victim))
        return [entry[2] for entry in sorted(candidates, key=lambda entry: entry[:2])[:2]]

    def _emit_state(self, unit, t):
        self.events.append((t, "unit_state", unit.idx, unit.hp, unit.energy))

    def _apply_healing_needle(self, unit, target, t):
        if (not tactics_mod.counters_enabled(self.ruleset)
                or getattr(unit, 'item_key', None) != 'healing_needle'
                or unit.needle_used or not target.alive):
            return
        unit.needle_used = True
        spec = items_mod.FINISHED['healing_needle']
        row = {'source': unit.idx, 'fraction': spec['healing_reduction'],
               'expires_at': t + spec['duration']}
        target.healing_blocks.append(row)
        self.events.append((t, 'tactical_effect', unit.idx, target.idx, 'healing_block',
                            {**row, 'source_pos': unit.pos, 'target_pos': target.pos,
                             'remaining': 0, 'reason': 'native_primary_hit'}))

    def _healing_amount(self, unit, amount, t):
        possible = max(0, min(unit.max_hp - unit.hp, amount)) if unit.alive else 0
        blocks = [row for row in unit.healing_blocks if t < row['expires_at']]
        strongest = max(blocks, key=lambda row: row['fraction'], default=None)
        healed = int(possible * (1.0 - strongest['fraction'])) if strongest else possible
        return healed, possible - healed, strongest

    def _heal(self, unit, amount, t):
        healed, blocked, source = self._healing_amount(unit, amount, t)
        if blocked:
            self.events.append((t, 'tactical_effect', source['source'], unit.idx,
                                'healing_prevented',
                                {'amount': blocked, 'healed': healed,
                                 'fraction': source['fraction'], 'expires_at': source['expires_at'],
                                 'target_pos': unit.pos, 'reason': 'actual_missing_hp'}))
        if healed > 0:
            unit.hp += healed
            self.events.append((t, "regen", unit.idx, healed))
            self._emit_state(unit, t)
        return healed

    def _death_check(self, target: Unit, t: float) -> None:
        if target.idx in self._dead:
            target.hp = 0
            return
        if target.hp <= 0 and target.item_sash and not target.item_sash_used:
            target.item_sash_used = True
            target.hp = 1
            self.events.append((t, "sash", target.idx))
        if target.hp <= 0:
            target.hp = 0
            self._dead.add(target.idx)
            self.events.append((t, "die", target.idx))

    def _free_cell_near(self, pos: tuple, avoid: tuple, team=0):
        occupied = {o.pos for o in self.units if o.alive}
        for dc, dr in self._directions(team):
            nxt = (pos[0] + dc, pos[1] + dr)
            if (0 <= nxt[0] < self.cols and 0 <= nxt[1] < self.rows
                    and nxt not in occupied and nxt != avoid):
                return nxt
        return None

    def _knock_cell(self, target: Unit, from_pos: tuple):
        """重击击退：目标沿远离 from_pos 方向退 1 格的空格（无则 None）。
        方向取主轴（行差优先），贴边/被挡不退——不产生连锁位移。"""
        dc = target.pos[0] - from_pos[0]
        dr = target.pos[1] - from_pos[1]
        step = (0, (1 if dr > 0 else -1)) if abs(dr) >= abs(dc) \
            else ((1 if dc > 0 else -1), 0)
        if step == (0, 0):
            return None
        nxt = (target.pos[0] + step[0], target.pos[1] + step[1])
        occupied = {o.pos for o in self.units if o.alive and o is not target}
        if (0 <= nxt[0] < self.cols and 0 <= nxt[1] < self.rows and nxt not in occupied):
            return nxt
        return None

    def _final_damage(self, u: Unit, target: Unit, move, dmg: int) -> int:
        """结算尾段：近战减免（均衡实验）→ 羁绊乘区 → 大招承伤上限 → 减伤。

        事件流里的 attack/cast 伤害即此处的最终落地值（渲染契约：
        数字与掉血一致）。羁绊全中性时与旧实现逐点等价。
        """
        dmg = int(dmg * weather_mod.damage_mult(
            move, self.weather_name))  # S11 天气乘区（实例级，默认 1.0）
        # 通用技能「铁壁」：临时受伤减免（bulwark 施法后 3s；
        # 到期判定用本 tick 的 self.duration，_strike 同拍一致）
        temporary_dr = target.temp_dr if target.temp_dr_until >= self.duration else 0.0
        partner_dr = target.partner_dr if target.partner_dr_until >= self.duration else 0.0
        if max(temporary_dr, partner_dr) > 0:
            dmg = int(dmg * (1.0 - max(temporary_dr, partner_dr)))
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
        return int(dmg * (1.0 - target.synergy_dr) * (1.0 - target.item_dr)
                   * (1.0 - target.arena_dr))

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
