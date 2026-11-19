"""arena_v2 depth edition: rules that change *how* a team plays, not just numbers.

Everything here is opt-in through the ``arena_v2`` ruleset; arena_v1 battles
never import this module's battle hooks (frozen by tests/test_arena_effect_bus).

Content
-------
* Stat curve: compressed tier budget and steeper star multipliers, so a 2-star
  low-cost unit beats a 1-star higher-cost one and 3 stars are a real plan.
* Stage terrain: every five rounds the arena gains a terrain that rewards or
  punishes specific cells (highland, mana spring, brambles, sanctum, swamp, embers).
* Skill modifiers: reaching 2 and 3 stars offers a choice between two native
  skill modifiers chosen by role (spread vs amplify, fortify vs quake, ...).
* Rule augments: augments that rewrite a rule (two item slots, -1 population
  for elite stats, bond counts +1, revive the first ally, executions, ...).
* Bond breakpoints: higher element tiers add behaviour (flyers dive the back
  line, rock walls shelter neighbours, ghosts phase out, electric arcs chain).
* Core unit: one marked carry gets a second item slot and doubled bond weight,
  but assassins hunt it.
* Items: every finished item also carries its two components' base stats;
  four previously dead component pairs now craft active items.

All battle effects are deterministic (no RNG draws) and emit ('effect', ...)
events plus ledger rows so the report can show exactly what each source did.
"""
from data import ENERGY_MAX
from arena_effects import EffectSpec, EffectInstance, fire, install

RULESET = 'arena_v2'
EPS = 1e-9

# ----------------------------------------------------------------- stat curve
TIER_SCALE = {1: 1.20, 2: 1.04, 3: .94, 4: .92, 5: .90}
STAR_MULT = (1., 1.8, 3.2)

# --------------------------------------------------------------- stage terrain
# Cells are local to each team: row 0 = front row, row 2 = back row, col 0..5.
TERRAINS = {
    'plain': {'name': '平原', 'cells': (),
              'description': '没有特殊地形。', 'tags': ()},
    'highland': {'name': '高地', 'cells': ((2, 1), (2, 2), (2, 3), (2, 4)),
                 'description': '己方后排中间四格是高地：开战时站在高地的远程单位射程 +1、攻击 +8%。',
                 'tags': ('ranged',)},
    'mana_spring': {'name': '能量泉', 'cells': ((0, 2), (0, 3), (1, 2), (1, 3)),
                    'description': '己方中央四格涌出能量：站在泉眼上的单位每秒获得 6 能量。',
                    'tags': ('energy',)},
    'brambles': {'name': '荆棘丛', 'cells': tuple((r, c) for r in range(3) for c in (0, 5)),
                 'description': '两侧边列长满荆棘：站在边列的单位每秒损失 2% 最大生命，但普攻伤害 +15%。',
                 'tags': ('edge',)},
    'sanctum': {'name': '圣域', 'cells': tuple((2, c) for c in range(6)),
                'description': '己方后排是圣域：站在后排的单位每秒回复 1.5% 最大生命。',
                'tags': ('sustain',)},
    'swamp': {'name': '泥沼', 'cells': tuple((0, c) for c in range(6)),
              'description': '双方前排陷入泥沼：在泥沼中移动耗时 +60%，站在泥沼里的单位受到伤害 -10%。',
              'tags': ('frontline',)},
    'embers': {'name': '余烬', 'cells': tuple((0, c) for c in range(6)),
               'description': '双方前排余烬未熄：站在前排的单位造成伤害 +12%，受到伤害 +8%。',
               'tags': ('aggression',)},
}
TERRAIN_ROTATION = ('highland', 'mana_spring', 'brambles', 'sanctum', 'swamp', 'embers')


def terrain_for_round(seed, round_no):
    """Stage 1 (rounds 1-5) is plain; later stages draw a stable rotation."""
    stage = (max(1, round_no) - 1) // 5
    if stage == 0:
        return 'plain'
    import rng as rng_mod
    order = list(TERRAIN_ROTATION)
    rng_mod.derive(seed, 0, 'terrain').shuffle(order)
    return order[(stage - 1) % len(order)]


def terrain_cells(key, team, rows=6):
    """Global (col, row) cells for one team's half."""
    cells = TERRAINS[key]['cells']
    half = rows // 2
    if team == 0:
        return {(c, half + r) for r, c in cells}
    return {(5 - c, half - 1 - r) for r, c in cells}


def terrain_view(key):
    spec = TERRAINS[key]
    return {'id': key, 'name': spec['name'], 'description': spec['description'],
            'cells': [list(cell) for cell in spec['cells']]}


def formation(comp, team, terrain):
    """Terrain-aware bot formation (local rows: 0 front, 2 back). Deterministic."""
    from profiles import effective_range
    cols_default = (2, 3, 1, 4, 0, 5)
    cols = (2, 3, 1, 4, 0, 5) if terrain != 'brambles' else (2, 3, 1, 4, 5, 0)
    occupied, positions = set(), []
    for entry in comp:
        if isinstance(entry, tuple):
            entry = entry[0]
        p = getattr(entry, 'piece', entry)
        role = getattr(p, 'role_key', 'attack')
        ranged = effective_range(p) > 1
        if role == 'defense':
            rows = (0, 1, 2)
        elif role == 'support':
            rows = (1, 2, 0) if terrain == 'mana_spring' else (2, 1, 0)
        elif ranged:
            rows = (2, 1, 0) if terrain in ('highland', 'sanctum') else (1, 2, 0)
        else:
            rows = ((0, 1, 2) if terrain == 'embers' else (1, 0, 2) if terrain == 'swamp'
                    else (0, 1, 2) if terrain == 'plain' else (1, 0, 2))
        order = cols
        if terrain == 'highland' and ranged and role != 'defense':
            order = (2, 3, 1, 4) + tuple(c for c in cols_default if c not in (1, 2, 3, 4))
        pos = next((r, c) for r in rows for c in order if (r, c) not in occupied)
        occupied.add(pos)
        r, c = pos
        positions.append((c, r + 3) if team == 0 else (5 - c, 2 - r))
    return positions


def scale_pve(wave, round_no):
    """arena_v2 wild rounds keep pace with the table: stars rise with the stage."""
    import copy
    # (leader star, others) — one 3-star leader first, whole 3-star waves only late.
    stars = {5: (2, 1), 10: (2, 2), 15: (2, 2), 20: (3, 2), 25: (3, 2), 30: (3, 3)}
    high, low = stars.get(round_no, (3, 3) if round_no > 30 else (1, 1))
    scaled = []
    for index, piece in enumerate(wave):
        clone = copy.copy(piece)
        clone.star = high if index == 0 else low
        clone.shiny = clone.star == 3
        scaled.append(clone)
    return scaled


def mentor_piece(piece):
    """Give a generic-strike early form its final form's native kit (v2 only)."""
    import copy
    from arena_skills import skill_of
    from arena_families import SPECIES_FAMILY, mentor
    sid = piece.species_id
    if sid not in SPECIES_FAMILY or not skill_of(sid)['id'].startswith('family_strike_'):
        return piece
    final = mentor(sid)
    if final == sid or skill_of(final)['id'].startswith('family_strike_'):
        return piece
    clone = copy.copy(piece)
    clone.native_mentor = final
    return clone


STREAK_PVE_THRESHOLD = 5


def streak_wave(wave, streak):
    """Win streak >= 5: every wild unit gains one star (max 3)."""
    if streak < STREAK_PVE_THRESHOLD:
        return wave
    import copy
    stronger = []
    for piece in wave:
        clone = copy.copy(piece)
        clone.star = min(3, getattr(piece, 'star', 1) + 1)
        clone.shiny = clone.star == 3
        stronger.append(clone)
    return stronger


# --------------------------------------------------------------- tactical orders
# One per team per battle, chosen in prep. Each has an upside and a cost.
ORDERS = {
    'none': {'name': '自由作战', 'brief': '不下达指令', 'description': '按默认索敌与站位作战。'},
    'protect_core': {'name': '护驾', 'brief': '核心开场获得 20% 护盾，相邻防守型嘲讽 2 格内敌人 2 秒',
                     'description': '需要指定核心。开战时核心获得 20% 最大生命护盾；与核心相邻的防守型宝可梦嘲讽 2 格内的敌人 2 秒。代价：核心之外的单位开场能量 -10。'},
    'focus_fire': {'name': '集火', 'brief': '全队开场锁定敌方核心（无核心则最低生命者）',
                   'description': '开战时全队把目标锁定为敌方核心；敌方没有核心时锁定最大生命最低的敌人。射程内已有敌人时近战仍会先打眼前的目标。代价：远程不再自动挑残血。'},
    'cut_supply': {'name': '断补给', 'brief': '全队开场锁定敌方辅助型，对辅助伤害 +15%',
                   'description': '开战时全队锁定最近的敌方辅助型，并对辅助型造成的伤害提高 15%。敌方没有辅助时无效果。'},
    'hold': {'name': '稳守', 'brief': '前排开场 5 秒减伤 25%，后排首次行动延后 0.6 秒',
             'description': '开战后 5 秒内己方前排受到伤害降低 25%；后排单位的首次行动延后 0.6 秒。'},
    'blitz': {'name': '突袭', 'brief': '全队开场 +25 能量，但前 5 秒受到伤害 +12%',
              'description': '开战时全队获得 25 能量，更早释放本命；代价是前 5 秒受到的伤害提高 12%。'},
}
ORDER_WINDOW = 5.


def order_view(key):
    return {'id': key, **ORDERS[key]}


def bot_order(board, enemy_board=None):
    """Deterministic bot order from its board and (when known) the opponent's."""
    roles = [getattr(o.piece, 'role_key', 'attack') for o in board]
    if not roles:
        return 'none'
    enemy_roles = [getattr(o.piece, 'role_key', 'attack') for o in enemy_board or ()]
    if enemy_roles.count('support') >= 2:
        return 'cut_supply'
    if (enemy_roles.count('attack') >= max(4, len(enemy_roles) // 2 + 1)
            and roles.count('defense') >= 2):
        return 'hold'
    if any(getattr(o, 'is_core', False) for o in board) and roles.count('defense') >= 2:
        return 'protect_core'
    if roles.count('attack') >= max(3, len(roles) // 2 + 1):
        return 'blitz'
    if roles.count('defense') >= 3:
        return 'hold'
    return 'focus_fire'


def _apply_orders(battle, t, **_):
    from arena_combinations import grant_shield
    for team in (0, 1):
        order = battle.arena_orders[team]
        mates = [u for u in battle.units if u.team == team and u.alive]
        enemies = [u for u in battle.units if u.team != team and u.alive]
        if order == 'none' or not mates:
            continue
        if order == 'protect_core':
            core = next((u for u in mates if u.depth_core), None)
            if core is None:
                continue
            amount = int(core.max_hp * .20)
            grant_shield(battle, core, core, amount, t, None, source_kind='combo',
                         source_key='protect_core', reason='order_protect_core')
            taunted = 0
            for guard in mates:
                if guard is core or guard.arena_role != 'defense' or _dist(guard, core) != 1:
                    continue
                for enemy in enemies:
                    if _dist(enemy, guard) <= 2:
                        enemy.taunt_source_idx, enemy.taunt_until = guard.idx, t + 2.
                        enemy.target_idx = guard.idx
                        taunted += 1
            for unit in mates:
                if unit is not core:
                    unit.energy = max(0, unit.energy - 10)
            _event(battle, core, core, 'protect_core', t, 'order', '护驾', 'shield', amount, team=team,
                   taunted=taunted)
        elif order in ('focus_fire', 'cut_supply'):
            if order == 'focus_fire':
                target = next((e for e in enemies if e.depth_core), None) or min(
                    enemies, key=lambda e: (e.max_hp, e.local_idx), default=None)
            else:
                supports = [e for e in enemies if e.arena_role == 'support']
                target = min(supports, key=lambda e: (min(_dist(e, m) for m in mates), e.local_idx),
                             default=None)
            if target is None:
                continue
            for unit in mates:
                unit.target_idx = target.idx
                unit.order_locked = True
            _event(battle, mates[0], target, order, t, 'order', ORDERS[order]['name'], 'debuff', 0,
                   team=team, camera='focus')
        elif order == 'hold':
            for unit in mates:
                if _local_row(battle, unit) == 2:
                    unit.next_act += .6
            _event(battle, mates[0], mates[0], 'hold', t, 'order', '稳守', 'buff', 0, team=team)
        elif order == 'blitz':
            for unit in mates:
                unit.energy = min(ENERGY_MAX, unit.energy + 25)
            _event(battle, mates[0], mates[0], 'blitz', t, 'order', '突袭', 'energy', 25 * len(mates),
                   team=team)
        for unit in mates:
            battle._emit_state(unit, t)


# --------------------------------------------------------------- skill mods
MODS = {
    'amplify': {'name': '强化', 'description': '本命与技能机伤害、治疗 +30%。'},
    'spread': {'name': '扩散', 'description': '本命主命中造成实际伤害后，对目标邻格最多 2 名敌人造成 35% 溅射。'},
    'execute': {'name': '处决', 'description': '本命主命中后目标生命低于 15% 时直接击倒。'},
    'sustain': {'name': '汲取', 'description': '本命主命中回复实际伤害的 30%；援护技能改为自身回复 8% 最大生命。'},
    'fortify': {'name': '坚壁', 'description': '施放本命后获得 15% 最大生命护盾（3 秒）。'},
    'quake': {'name': '震地', 'description': '施放本命后使自身邻格所有敌人畏缩 0.6 秒。'},
    'retaliate': {'name': '反震', 'description': '施放本命后 4 秒内，受到直接伤害时反弹 30%。'},
    'overflow': {'name': '溢流', 'description': '施放本命后，为自身 2 格内生命最低的两名队友提供 8% 最大生命护盾。'},
    'quicken': {'name': '迅捷', 'description': '施放本命后立即返还 25 能量。'},
    'sanctify': {'name': '圣洁', 'description': '施放本命后净化 2 格内一名队友的主要异常，并使其 3 秒内减伤 25%。'},
}
MOD_CHOICES = {
    'attack': {2: ('amplify', 'spread'), 3: ('execute', 'sustain')},
    'defense': {2: ('fortify', 'quake'), 3: ('retaliate', 'sustain')},
    'support': {2: ('overflow', 'quicken'), 3: ('sanctify', 'amplify')},
}


def mod_options(role, star):
    return MOD_CHOICES.get(role, MOD_CHOICES['attack']).get(star, ())


def mod_view(key):
    return {'id': key, **MODS[key]}


# --------------------------------------------------------------- rule augments
# 'battle' rows are resolved by handlers below; 'session' rows by demo/session code.
AUGMENTS = {
    'dual_wield': {'name': '双持专精', 'scope': 'session', 'tags': ('items',),
                   'brief': '每只宝可梦有 2 个装备位并立即获得 2 个组件，但战斗中技能机失效',
                   'description': '所有棋子获得第二个装备位，选取时立即获得 2 个组件；作为代价，已学习的技能机在战斗中不会触发。适合以本命技能为核心的阵容。'},
    'elite_squad': {'name': '精兵简政', 'scope': 'session', 'tags': ('stats', 'small_team'),
                    'brief': '人口上限 -1，全队生命与攻击 +22%',
                    'description': '人口上限永久 -1；作为补偿，全队最大生命与攻击、特攻提高 22%。'},
    'bond_resonance': {'name': '羁绊共鸣', 'scope': 'session', 'tags': ('bonds',),
                       'brief': '已激活的属性羁绊计数 +1，但人口上限 -1',
                       'description': '每个至少有 1 名成员的属性羁绊计数 +1（包括深度断点）；人口上限永久 -1。'},
    'fast_track': {'name': '速成培育', 'scope': 'session', 'tags': ('economy', 'stars'),
                   'brief': '每轮开始，1–2 费家族的同星对子自动补齐第三张（每局 3 次）',
                   'description': '每轮开始时，若你持有某个 1 或 2 费家族的两张同星棋子，且卡池仍有余量，自动从卡池补入第三张并升星；每局最多补齐 3 次。'},
    'free_roll': {'name': '自由刷新', 'scope': 'session', 'tags': ('economy',),
                  'brief': '每轮前两次刷新免费；定向刷新基础价 1 金',
                  'description': '每轮的前两次普通刷新免费，定向刷新的基础价从 3 金降为 1 金（同轮每多定向一次 +1 金）。'},
    'salvage': {'name': '回收专家', 'scope': 'session', 'tags': ('items', 'economy'),
                'brief': '出售 2 星及以上棋子额外得到 1 个组件；拆解装备免费',
                'description': '出售 2 星或 3 星棋子时，按棋子编号确定性地额外获得 1 个组件；拆解成品装备不再花费金币。'},
    'treasure_hunter': {'name': '寻宝者', 'scope': 'session', 'tags': ('items',),
                        'brief': '立即获得 2 个组件，之后每次野怪轮获胜再得 1 个组件',
                        'description': '选取时立即获得 2 个组件；之后每个野怪轮获胜额外获得 1 个组件。'},
    'interest_master': {'name': '理财专家', 'scope': 'session', 'tags': ('economy',),
                        'brief': '利息上限 5 → 8',
                        'description': '每 10 金 1 利息的上限从 5 提高到 8（80 金吃满）。'},
    'charge_horn': {'name': '冲锋号', 'scope': 'battle', 'tags': ('melee', 'opening'),
                    'brief': '开战时近战单位冲到最近敌人身边，获得 20% 护盾与 15 能量',
                    'description': '开战瞬间，所有近战单位跃到最近敌人旁边的空格，获得 20% 最大生命护盾（3 秒）与 15 能量。'},
    'vanguard': {'name': '先锋壁垒', 'scope': 'battle', 'tags': ('frontline',),
                 'brief': '开战时前排单位获得 20% 最大生命护盾',
                 'description': '开战时站在己方前排的单位获得 20% 最大生命护盾（3 秒）。'},
    'sniper_nest': {'name': '狙击巢', 'scope': 'battle', 'tags': ('ranged',),
                    'brief': '后排远程单位射程 +1、攻击 +10%',
                    'description': '开战时站在己方后排的远程单位射程 +1，攻击与特攻提高 10%。'},
    'undying': {'name': '不屈军团', 'scope': 'battle', 'tags': ('sustain',),
                'brief': '每场第一个将要阵亡的友军保留 1 生命并获得 2 秒 60% 减伤',
                'description': '每场战斗，第一个受到致命伤害的友军改为保留 1 点生命，并在 2 秒内减伤 60%。'},
    'chain_reaction': {'name': '连锁爆破', 'scope': 'battle', 'tags': ('aoe',),
                       'brief': '敌人阵亡时，对其邻格敌人造成其最大生命 12% 的伤害',
                       'description': '每当敌方单位阵亡，对它四向相邻的敌方单位造成相当于阵亡者最大生命 12% 的伤害（不触发连锁）。'},
    'giant_slayer': {'name': '巨人杀手', 'scope': 'battle', 'tags': ('damage',),
                     'brief': '对最大生命高于自身的目标伤害 +22%',
                     'description': '全队对最大生命高于攻击者的目标造成的伤害提高 22%。'},
    'executioner': {'name': '斩首令', 'scope': 'battle', 'tags': ('damage',),
                    'brief': '直接命中后敌人生命低于 12% 时立即击倒',
                    'description': '全队的直接命中使敌人生命降到 12% 以下时将其击倒；每名攻击者冷却 3 秒。'},
    'mana_siphon': {'name': '能量虹吸', 'scope': 'battle', 'tags': ('energy',),
                    'brief': '施放本命后，邻格队友获得 12 能量',
                    'description': '任一友军施放本命技能后，与它四向相邻的其他友军各获得 12 能量。'},
    'hold_the_line': {'name': '坚守阵地', 'scope': 'battle', 'tags': ('positioning',),
                      'brief': '本场从未移动过的单位受到伤害 -18%',
                      'description': '本场战斗中没有主动移动过的友军受到的伤害降低 18%；被击退不算主动移动。'},
}
# Flat numeric augments leave the v2 candidate pool: rules replace raw panels.
V2_EXCLUDED = frozenset({'sharp_focus', 'iron_wall', 'first_aid', 'vitality', 'quick_step',
                         'mana_flow', 'war_banner', 'deep_reserves'})
AUGMENT_TAGS = {
    'poison_catalyst': ('poison', 'energy'), 'watch_echo': ('support', 'energy'),
    'barrier_feedback': ('support', 'shield'), 'native_inspiration': ('support', 'damage'),
    'breach_momentum': ('knockback',), 'growth_mark': ('stats',), 'growth_bulwark': ('stats',),
    'war_drum': ('stats',), 'xp_doctrine': ('economy',),
}


def augment_tags(key):
    return AUGMENTS[key]['tags'] if key in AUGMENTS else AUGMENT_TAGS.get(key, ())


def population_penalty(augment_keys):
    return sum(1 for key in augment_keys if key in ('elite_squad', 'bond_resonance'))


# --------------------------------------------------------------- bond rules
BOND_RULES = {
    'ROCK': (4, 'rock_bulwark', '岩壁', '成员使四向相邻的其他队友受到伤害 -12%。'),
    'FLYING': (4, 'sky_dive', '俯冲', '开战时成员跃至最远敌人（优先敌方核心）身旁，并获得 10% 护盾。'),
    'GHOST': (2, 'phase_out', '虚化', '成员第一次受到致命伤时保留 1 生命并在 1.5 秒内无法被选为目标。'),
    'WATER': (4, 'tidal_overflow', '潮涌', '成员受到的溢出治疗转化为护盾（最多 15% 最大生命）。'),
    'FIRE': (3, 'wildfire', '燎原', '成员每第 3 次有效普攻使无异常的目标灼伤。'),
    'ELECTRIC': (4, 'arc_chain', '电弧', '成员每第 4 次有效普攻向目标 2 格内另外 3 名敌人传导 45% 伤害。'),
    'GRASS': (4, 'thorn_snare', '荆棘缠绕', '成员首次降到 40% 生命以下时，定身所有相邻敌人 1.5 秒。'),
    'POISON': (4, 'venom_mark', '毒蚀', '中毒的敌人受到成员所在队伍的伤害 +12%（6 档 +20%）。'),
    'GROUND': (4, 'aftershock', '余震', '成员施放本命后使自身邻格敌人畏缩 0.6 秒。'),
    'NORMAL': (4, 'solidarity', '团结', '成员每有一名存活队友，造成伤害 +2.5%。'),
    'FIGHTING': (4, 'flurry', '连环拳', '成员每第 3 次有效普攻追加一次 50% 伤害的连击。'),
    'PSYCHIC': (4, 'telekinesis', '念动', '成员本命主命中后将目标推开 1 格。'),
    'BUG': (4, 'molt', '蜕壳', '成员首次降到 35% 生命以下时净化异常并获得 20% 护盾。'),
    'ICE': (3, 'deep_freeze', '冰封', '成员对同一目标每第 5 次直接命中使其冰冻 1 秒。'),
    'STEEL': (2, 'iron_reflect', '反甲', '成员把受到的直接伤害的 10% 反弹给攻击者。'),
    'DARK': (2, 'ambush', '伏击', '成员对每个目标的第一次直接命中伤害 +40%。'),
    'DRAGON': (2, 'dragon_scale', '龙鳞', '成员受到技能伤害 -15%。'),
}


def bond_rule_for(element, count):
    rule = BOND_RULES.get(element)
    if rule is None or count < rule[0]:
        return None
    return rule[1]


def bond_rule_view(element):
    rule = BOND_RULES.get(element)
    if rule is None:
        return None
    return {'count': rule[0], 'id': rule[1], 'name': rule[2], 'effect': rule[3]}


# --------------------------------------------------------------- item stats
COMPONENT_STATS = {
    'band': {'atk': .08}, 'hardstone': {'hp': .08}, 'magnet': {'ult': .10},
    'shoes': {'speed': .08}, 'bell': {'energy': 10}, 'charcoal': {'dmg': .05},
    'mysticwater': {'heal': .006}, 'spark': {'gain': .10},
}
COMPONENT_STAT_TEXT = {'atk': '攻击', 'hp': '最大生命', 'ult': '技能伤害', 'speed': '攻速',
                       'energy': '开战能量', 'dmg': '伤害', 'heal': '每秒回复', 'gain': '回能效率'}
DEPTH_ITEMS = {
    'mind_crystal': {'name': '心灵水晶', 'pairs': (('magnet', 'magnet'),), 'arena_only': True,
                     'depth_only': True, 'energy_amount': 20, 'cooldown': 2., 'limit': 4,
                     'description': '施放本命后立即返还 20 能量。每战最多 4 次。'},
    'quick_claw': {'name': '先制之爪', 'pairs': (('magnet', 'shoes'),), 'arena_only': True,
                   'depth_only': True,
                   'description': '开战时获得 40 能量；每次施放本命后 3 秒内攻速 +25%。'},
    'escape_pack': {'name': '逃脱背包', 'pairs': (('mysticwater', 'shoes'),), 'arena_only': True,
                    'depth_only': True,
                    'description': '首次降到 40% 生命以下时，撤退到己方后排空格并获得 20% 最大生命护盾。'},
    'blast_core': {'name': '爆裂核心', 'pairs': (('charcoal', 'spark'),), 'arena_only': True,
                   'depth_only': True,
                   'description': '携带者阵亡时爆炸，对四向相邻敌人造成其最大生命 25% 的伤害。'},
}

import arena_mech_items as _mech  # noqa: E402
DEPTH_ITEMS.update(_mech.MECH_ITEMS)


def recipe_components(key):
    import items
    spec = {**items.FINISHED, **DEPTH_ITEMS}.get(key)
    if not spec or not spec.get('pairs'):
        return ()
    return tuple(spec['pairs'][0])


def item_stats(key):
    stats = {}
    for component in recipe_components(key):
        for stat, value in COMPONENT_STATS.get(component, {}).items():
            stats[stat] = stats.get(stat, 0) + value
    return stats


def item_stats_text(key):
    parts = []
    for stat, value in item_stats(key).items():
        if stat == 'energy':
            parts.append(f'{COMPONENT_STAT_TEXT[stat]} +{value:g}')
        else:
            parts.append(f'{COMPONENT_STAT_TEXT[stat]} +{value * 100:g}%')
    return '、'.join(parts)


# ===================================================================== battle
def _dist(a, b):
    return abs(a.pos[0] - b.pos[0]) + abs(a.pos[1] - b.pos[1])


def _local_row(battle, unit):
    """0 = own front row, 2 = own back row."""
    half = battle.rows // 2
    return unit.pos[1] - half if unit.team == 0 else half - 1 - unit.pos[1]


def _items(unit):
    return tuple(key for key in (getattr(unit, 'item_key', None),
                                 getattr(unit, 'extra_item_key', None)) if key)


def has_item(unit, key):
    return key in _items(unit)


def apply_stat_curve(unit, star, tier):
    scale = TIER_SCALE.get(tier, 1.)
    return STAR_MULT[star - 1] * scale


def _apply_component_stats(unit):
    for key in _items(unit):
        stats = item_stats(key)
        if stats.get('atk'):
            unit.attack += int(unit.attack * stats['atk'])
            unit.sp_attack += int(unit.sp_attack * stats['atk'])
        if stats.get('hp'):
            delta = int(unit.max_hp * stats['hp'])
            unit.max_hp += delta
            unit.hp += delta
        if stats.get('speed'):
            unit.attack_interval /= 1. + stats['speed']
        if stats.get('ult'):
            unit.item_ult_dmg += stats['ult']
        if stats.get('energy'):
            unit.energy = min(ENERGY_MAX, unit.energy + int(stats['energy']))
        if stats.get('dmg'):
            unit.depth_dmg += stats['dmg']
        if stats.get('heal'):
            unit.item_heal += stats['heal']
        if stats.get('gain'):
            unit.item_energy += stats['gain']


def apply_secondary_item(unit, key):
    """Merge a second finished item additively, keeping the primary's identity."""
    import items
    spec = {**items.FINISHED, **DEPTH_ITEMS}[key]
    unit.extra_item_key = key
    if spec.get('atk'):
        unit.attack += int(unit.attack * spec['atk'])
        unit.sp_attack += int(unit.sp_attack * spec['atk'])
    if spec.get('speed'):
        unit.attack_interval /= 1. + spec['speed']
    unit.item_ult_dmg += spec.get('ult_dmg', 0.)
    unit.item_dr = 1 - (1 - unit.item_dr) * (1 - spec.get('dr', 0.))
    unit.item_heal += spec.get('heal', 0.)
    unit.item_energy += spec.get('energy', 0.)
    unit.item_dodge = max(unit.item_dodge, spec.get('dodge', 0.))
    unit.item_sash = unit.item_sash or bool(spec.get('sash'))
    if spec.get('type_dmg'):
        merged = dict(unit.item_type_dmg or {})
        for kind, value in spec['type_dmg'].items():
            merged[kind] = merged.get(kind, 0.) + value
        unit.item_type_dmg = merged


def unit_init(unit):
    """Neutral defaults for every depth field (set on all arena_v2 units)."""
    unit.depth_dmg = 0.
    unit.depth_dr = 0.
    unit.depth_rules = set()
    unit.depth_mods = ()
    unit.order_locked = False
    unit.depth_core = False
    unit.extra_item_key = getattr(unit, 'extra_item_key', None)
    unit.untargetable_until = 0.
    unit.moved = False
    unit.hit_counts = {}
    unit.first_hits = set()
    unit.retaliate_until = 0.
    unit.haste_until = 0.
    unit.haste_fraction = 0.
    unit.threshold_used = set()


def _bond_counts(battle, team):
    import arena_bonds
    comp = battle._plain_comps[team]
    counts = arena_bonds.count(comp)
    augments = battle.arena_teams[team]
    core = next((u for u in battle.units if u.team == team and u.depth_core), None)
    if core is not None:
        for element in core.piece.types:
            if element in counts:
                counts[element] += 1
    if 'bond_resonance' in augments:
        for element in list(counts):
            if element in arena_bonds.ELEMENT_TIERS and counts[element] >= 1:
                counts[element] += 1
    return counts


def team_bond_rules(battle, team):
    counts = _bond_counts(battle, team)
    return {element: rule[1] for element, rule in BOND_RULES.items()
            if counts.get(element, 0) >= rule[0]}, counts


def setup(battle):
    """Called once after arena panels and bonds; installs every v2 effect."""
    terrain = battle.arena_terrain or 'plain'
    battle.terrain_cells = ({team: terrain_cells(terrain, team, battle.rows) for team in (0, 1)}
                            if terrain != 'plain' else {0: set(), 1: set()})
    instances = []
    for team in (0, 1):
        augments = set(battle.arena_teams[team])
        members = [u for u in battle.units if u.team == team]
        rules, counts = team_bond_rules(battle, team)
        battle.depth_bond_counts[team] = counts
        for unit in members:
            unit.depth_rules = {rule for element, rule in rules.items()
                                if element in unit.piece.types}
            if 'elite_squad' in augments:
                _scale_unit(unit, 1.22)
            if unit.depth_core:
                _scale_unit(unit, 1.15)
            _apply_component_stats(unit)
            if 'dual_wield' in augments:
                unit.technique = None
            row = _local_row(battle, unit)
            if unit.range > 1 and row == 2 and 'sniper_nest' in augments:
                unit.range += 1
                unit.attack += int(unit.attack * .10)
                unit.sp_attack += int(unit.sp_attack * .10)
                battle.fx.ledger.add(team, 'augment', 'sniper_nest', triggers=1)
            if (terrain == 'highland' and unit.range > 1
                    and unit.pos in battle.terrain_cells[team]):
                unit.range += 1
                unit.attack += int(unit.attack * .08)
                unit.sp_attack += int(unit.sp_attack * .08)
                battle.fx.ledger.add(team, 'terrain', 'highland', triggers=1)
            if 'amplify' in unit.depth_mods:
                unit.synergy_ult_dmg += .30
                unit.arena_heal_mult *= 1.3
            if has_item(unit, 'quick_claw'):
                unit.energy = min(ENERGY_MAX, unit.energy + 40)
            for spec in UNIT_SPECS:
                if _unit_has(unit, spec, augments):
                    instances.append(EffectInstance(spec, team, unit))
        for spec in TEAM_SPECS:
            if spec.id in augments or spec.id == 'terrain_' + terrain:
                instances.append(EffectInstance(spec, team, None))
        for key in augments:
            if key in PASSIVE_AUGMENTS:
                battle.fx.ledger.add(team, 'augment', key, passive=1)
        if 'elite_squad' in augments:
            battle.fx.ledger.add(team, 'augment', 'elite_squad', passive=1)
    install(battle, instances)
    battle.fx.subscribe('battle_start', _apply_orders)


PASSIVE_AUGMENTS = frozenset({'growth_mark', 'growth_bulwark', 'war_drum', 'sharp_focus', 'vitality',
                              'iron_wall', 'quick_step', 'mana_flow', 'first_aid', 'war_banner',
                              'deep_reserves', 'dual_wield', 'bond_resonance'})


def ledger_key(spec):
    return spec.id[len('terrain_'):] if spec.id.startswith('terrain_') else spec.id


def contributed_rules(battle, team):
    """Bond breakpoints that actually produced value for ``team`` in this battle."""
    if not getattr(battle, 'depth', False):
        return []
    rules = {rule[1] for rule in BOND_RULES.values()}
    return sorted(row['id'] for row in battle.fx.ledger.view(team)
                  if row['source'] == 'bond' and row['id'] in rules
                  and any(row[k] for k in ('triggers', 'damage', 'heal', 'shield', 'energy',
                                            'prevented', 'estimated')))


def mark_idle(battle):
    """After the battle: every installed effect without a ledger row shows as not triggered."""
    for instance in getattr(battle, 'fx_instances', ()):
        key = ledger_key(instance.spec)
        if not battle.fx.ledger.has(instance.team, instance.spec.source, key):
            battle.fx.ledger.add(instance.team, instance.spec.source, key, idle=1)


def _scale_unit(unit, factor):
    unit.max_hp = max(1, int(unit.max_hp * factor))
    unit.hp = unit.max_hp
    unit.attack = max(1, int(unit.attack * factor))
    unit.sp_attack = max(1, int(unit.sp_attack * factor))


def _unit_has(unit, spec, augments):
    if spec.source == 'bond':
        return spec.id in unit.depth_rules
    if spec.source == 'skill_mod':
        return spec.id in unit.depth_mods
    if spec.source == 'item':
        return has_item(unit, spec.id)
    if spec.source == 'augment':
        return spec.id in augments
    return False


# ------------------------------------------------------------ queries used by combat
def untargetable(unit, t):
    return getattr(unit, 'untargetable_until', 0.) > t + EPS


def damage_multiplier(battle, attacker, target, move, t, base=0):
    """Depth multiplier applied in Battle._final_damage (attacker side x target side).

    Each named factor is booked to its owner's ledger as an estimate of the
    extra damage dealt (factor > 1) or damage prevented (factor < 1).
    """
    factors = []  # (team, source, key, factor)
    if getattr(attacker, 'depth_dmg', 0.):
        factors.append((attacker.team, 'item', 'component_damage', 1. + attacker.depth_dmg))
    team_aug = battle.arena_teams[attacker.team]
    their_aug = battle.arena_teams[target.team]
    rules = getattr(attacker, 'depth_rules', ())
    if 'giant_slayer' in team_aug and target.max_hp > attacker.max_hp:
        factors.append((attacker.team, 'augment', 'giant_slayer', 1.22))
    if has_item(attacker, 'static_glove') and getattr(getattr(target, '_st', None), 'debuff', None) == 'para':
        factors.append((attacker.team, 'item', 'static_glove', 1.15))
    if 'solidarity' in rules:
        allies = sum(1 for u in battle.units if u.alive and u.team == attacker.team and u is not attacker)
        factors.append((attacker.team, 'bond', 'solidarity', 1. + .025 * allies))
    if 'ambush' in rules and target.idx not in attacker.first_hits:
        attacker.first_hits.add(target.idx)
        factors.append((attacker.team, 'bond', 'ambush', 1.40))
    if (getattr(getattr(target, '_st', None), 'debuff', None) == 'poison'
            and any(u.team == attacker.team and 'venom_mark' in u.depth_rules for u in battle.units)):
        count = battle.depth_bond_counts[attacker.team].get('POISON', 0)
        factors.append((attacker.team, 'bond', 'venom_mark', 1.20 if count >= 6 else 1.12))
    terrain = battle.arena_terrain
    if terrain == 'embers':
        if attacker.pos in battle.terrain_cells[attacker.team]:
            factors.append((attacker.team, 'terrain', 'embers', 1.12))
        if target.pos in battle.terrain_cells[target.team]:
            factors.append((attacker.team, 'terrain', 'embers', 1.08))
    if terrain == 'brambles' and move is None and attacker.pos in battle.terrain_cells[attacker.team]:
        factors.append((attacker.team, 'terrain', 'brambles', 1.15))
    order = battle.arena_orders[attacker.team]
    if order == 'cut_supply' and getattr(target, 'arena_role', None) == 'support':
        factors.append((attacker.team, 'order', 'cut_supply', 1.15))
    their_order = battle.arena_orders[target.team]
    if t < ORDER_WINDOW:
        if their_order == 'blitz':
            factors.append((attacker.team, 'order', 'blitz_exposed', 1.12))
        if their_order == 'hold' and _local_row(battle, target) == 0:
            factors.append((target.team, 'order', 'hold', .75))
    # ---- target-side reductions
    if terrain == 'swamp' and target.pos in battle.terrain_cells[target.team]:
        factors.append((target.team, 'terrain', 'swamp', .90))
    if 'hold_the_line' in their_aug and not getattr(target, 'moved', True):
        factors.append((target.team, 'augment', 'hold_the_line', .82))
    if move is not None and 'dragon_scale' in getattr(target, 'depth_rules', ()):
        factors.append((target.team, 'bond', 'dragon_scale', .85))
    if any(u.alive and u is not target and u.team == target.team and 'rock_bulwark' in u.depth_rules
           and _dist(u, target) == 1 for u in battle.units):
        factors.append((target.team, 'bond', 'rock_bulwark', .88))
    if any(u.alive and u is not target and u.team == target.team
           and getattr(u, 'arena_role', None) == 'support' and _dist(u, target) == 1
           for u in battle.units):
        factors.append((target.team, 'edition', 'support_aura', .94))
    if attacker.range > 1 and target.range > 1:
        ahead = (target.pos[0], target.pos[1] + (-1 if target.team == 0 else 1))
        if any(u.alive and u.team == target.team and u.pos == ahead for u in battle.units):
            factors.append((target.team, 'edition', 'cover', .88))
    if getattr(target, 'depth_dr', 0.):
        factors.append((target.team, 'edition', 'depth_dr', 1. - target.depth_dr))
    mult = 1.
    for team, source, key, factor in factors:
        if base > 0 and key != 'depth_dr':
            delta = base * mult * (factor - 1.)
            if delta >= 0:
                battle.fx.ledger.add(team, source, key, estimated=delta)
            else:
                battle.fx.ledger.add(team, source, key, prevented=-delta)
        mult *= factor
    return mult


def prefer_target(battle, unit, enemies, t):
    """Ranged units pick the weakest enemy already in range; assassins hunt cores."""
    if unit.range > 1 and not getattr(unit, 'order_locked', False):
        in_range = [e for e in enemies if _dist(unit, e) <= unit.range]
        if in_range:
            return min(in_range, key=lambda e: (e.hp / e.max_hp, battle._target_key(unit, e)))
    return None


def prevent_death(battle, unit, t):
    """Run before a unit is marked dead. Returns True if it stays alive at 1 HP."""
    if 'phase_out' in unit.depth_rules and 'phase_out' not in unit.threshold_used:
        unit.threshold_used.add('phase_out')
        unit.hp = 1
        unit.untargetable_until = t + 1.5
        if unit.target_idx is not None:
            unit.target_idx = None
        for enemy in battle.units:
            if enemy.target_idx == unit.idx:
                enemy.target_idx = None
        _event(battle, unit, unit, 'phase_out', t, 'bond', '虚化', 'buff', 0, team=unit.team)
        battle._emit_state(unit, t)
        return True
    if _mech.revival_save(battle, unit, t):
        return True
    if 'undying' in battle.arena_teams[unit.team] and not battle.depth_undying_used[unit.team]:
        battle.depth_undying_used[unit.team] = True
        unit.hp = 1
        unit.temp_dr, unit.temp_dr_until = .60, t + 2.
        _event(battle, unit, unit, 'undying', t, 'augment', '不屈', 'buff', 0, team=unit.team,
               camera='focus')
        battle._emit_state(unit, t)
        return True
    return False


def on_heal(battle, unit, requested, healed, t):
    """Water breakpoint: overflow healing becomes a shield."""
    if 'tidal_overflow' not in getattr(unit, 'depth_rules', ()) or not unit.alive:
        return
    overflow = max(0, requested - healed)
    amount = min(int(unit.max_hp * .15), overflow)
    if amount <= 0:
        return
    from arena_combinations import grant_shield, can_shield
    current = unit.shield if unit.shield_until > t + EPS else 0
    total = min(int(unit.max_hp * .15), current + amount)
    if can_shield(unit, total, t) and grant_shield(battle, unit, unit, total, t, None,
                                                   source_kind='combo', source_key='tidal_overflow',
                                                   reason='overflow_heal'):
        battle.fx.ledger.add(unit.team, 'bond', 'tidal_overflow', triggers=1, shield=total - current)


def move_cost(battle, unit, destination):
    if battle.arena_terrain == 'swamp' and destination in battle.terrain_cells[unit.team]:
        return 1.6
    return 1.


# ------------------------------------------------------------------ helpers
def _event(battle, source, target, key, t, origin, label, kind, value, *, team, camera=None,
           **payload):
    battle.events.append((t, 'effect', source.idx, target.idx, key,
                          {'source': origin, 'team': team, 'kind': kind, 'label': label,
                           'value': int(value), **({'camera': camera} if camera else {}),
                           **payload}))
    battle.fx.ledger.add(team, origin, key, triggers=1,
                         **({kind: value} if kind in ('damage', 'heal', 'shield', 'energy') else {}))


def _indirect_damage(battle, source, target, amount, t):
    """Non-primary damage packet: no energy, no statuses, no on-hit recursion."""
    if not target.alive or amount <= 0:
        return 0
    return battle._land_hit(source, target, int(amount), t, direct=False)


def _shield(battle, source, patient, amount, t, key):
    from arena_combinations import grant_shield
    return grant_shield(battle, source, patient, int(amount), t, None, source_kind='combo',
                        source_key=key, reason='depth_' + key)


def _energy(battle, unit, amount):
    gained = max(0, min(amount, ENERGY_MAX - unit.energy))
    unit.energy += gained
    return gained


def _free_cell_adjacent(battle, anchor, team):
    occupied = {u.pos for u in battle.units if u.alive}
    for dc, dr in battle._directions(team):
        cell = (anchor[0] + dc, anchor[1] + dr)
        if 0 <= cell[0] < battle.cols and 0 <= cell[1] < battle.rows and cell not in occupied:
            return cell
    return None


def _leap(battle, unit, destination, t, key):
    from arena_fields import move_unit
    origin = unit.pos
    if destination is None or destination == origin:
        return False
    move_unit(battle, unit, destination, t, source=unit, reason='leap')
    unit.moved = True
    battle.events.append((t, 'effect', unit.idx, unit.idx, key,
                          {'source': 'depth', 'team': unit.team, 'kind': 'move', 'label': '跃进',
                           'value': 0,
                           'origin': list(origin), 'destination': list(destination)}))
    return True


# ------------------------------------------------------------------ handlers
def _h_charge_horn(battle, inst, t, **_):
    total = 0
    for unit in sorted((u for u in battle.units if u.team == inst.team and u.alive and u.range == 1),
                       key=lambda u: u.local_idx):
        enemies = [e for e in battle.units if e.alive and e.team != unit.team]
        if not enemies:
            break
        nearest = min(enemies, key=lambda e: (_dist(unit, e), battle._target_key(unit, e)))
        if _dist(unit, nearest) > 1:
            _leap(battle, unit, _free_cell_adjacent(battle, nearest.pos, unit.team), t, 'charge_horn')
        unit.target_idx = nearest.idx
        shield = int(unit.max_hp * .20)
        if _shield(battle, unit, unit, shield, t, 'charge_horn'):
            total += shield
        unit.energy = min(ENERGY_MAX, unit.energy + 15)
    fire(battle, inst, None, t, label='冲锋号', kind='shield', value=total, camera='focus')


def _h_vanguard(battle, inst, t, **_):
    total = 0
    for unit in battle.units:
        if unit.team == inst.team and unit.alive and _local_row(battle, unit) == 0:
            shield = int(unit.max_hp * .20)
            if _shield(battle, unit, unit, shield, t, 'vanguard'):
                total += shield
    fire(battle, inst, None, t, label='先锋壁垒', kind='shield', value=total)


def _h_sky_dive(battle, inst, t, **_):
    unit = inst.unit
    enemies = [e for e in battle.units if e.alive and e.team != unit.team]
    if not enemies:
        return
    core = next((e for e in enemies if e.depth_core), None)
    target = core or max(enemies, key=lambda e: (_dist(unit, e), -e.local_idx))
    destination = _free_cell_adjacent(battle, target.pos, target.team)
    if _leap(battle, unit, destination, t, 'sky_dive'):
        unit.target_idx = target.idx
        shield = int(unit.max_hp * .10)
        _shield(battle, unit, unit, shield, t, 'sky_dive')
        fire(battle, inst, target, t, label='俯冲', kind='shield', value=shield, camera='focus')


def _h_mana_siphon(battle, inst, unit, t, cast_index, **_):
    if unit.team != inst.team or not unit.alive:
        return
    total = 0
    for mate in battle.units:
        if mate is not unit and mate.alive and mate.team == unit.team and _dist(mate, unit) == 1:
            gained = _energy(battle, mate, 12)
            if gained:
                total += gained
                battle._emit_state(mate, t)
    if total:
        fire(battle, inst, unit, t, kind='energy', value=total, spend=False)


def _h_chain_reaction(battle, inst, unit, killer, t, **_):
    if unit.team == inst.team:
        return
    source = killer if killer is not None and killer.team == inst.team else next(
        (u for u in battle.units if u.team == inst.team and u.alive), None)
    if source is None:
        return
    total = 0
    for victim in sorted((v for v in battle.units if v.alive and v.team == unit.team
                          and _dist(v, unit) == 1), key=lambda v: v.local_idx):
        total += _indirect_damage(battle, source, victim, unit.max_hp * .12, t)
    if total:
        fire(battle, inst, unit, t, kind='damage', value=total, spend=False)


def _h_executioner(battle, inst, source, target, actual_hp, t, **_):
    if source is None or source.team != inst.team or not target.alive or actual_hp <= 0:
        return
    if target.hp > target.max_hp * .12:
        return
    ready = inst.state.setdefault('ready', {})
    if ready.get(source.idx, 0.) > t + EPS:
        return
    ready[source.idx] = t + 3.
    remaining = target.hp
    _indirect_damage(battle, source, target, remaining + max(target.shield, 0) + 1, t)
    fire(battle, inst, target, t, label='斩首', kind='damage', value=remaining, spend=False,
         camera='focus')


def _bond_basic_counter(battle, inst, unit, target, actual_hp, every):
    if unit is not inst.unit or actual_hp <= 0 or not target.alive:
        return False
    count = inst.state.get('count', 0) + 1
    inst.state['count'] = count
    return count % every == 0


def _h_wildfire(battle, inst, unit, target, t, actual_hp, **_):
    if not _bond_basic_counter(battle, inst, unit, target, actual_hp, 3):
        return
    if getattr(getattr(target, '_st', None), 'debuff', None) is None:
        import status
        if status.apply_debuff(battle, target, 'burn', t, source=unit):
            fire(battle, inst, target, t, label='燎原', kind='debuff', spend=False)


def _h_arc_chain(battle, inst, unit, target, t, actual_hp, **_):
    if not _bond_basic_counter(battle, inst, unit, target, actual_hp, 4):
        return
    victims = sorted((v for v in battle.units if v.alive and v.team != unit.team and v is not target
                      and _dist(v, target) <= 2), key=lambda v: (_dist(v, target), v.local_idx))[:3]
    total = sum(_indirect_damage(battle, unit, v, actual_hp * .45, t) for v in victims)
    if total:
        fire(battle, inst, target, t, label='电弧', kind='damage', value=total, spend=False)


def _h_flurry(battle, inst, unit, target, t, actual_hp, **_):
    if not _bond_basic_counter(battle, inst, unit, target, actual_hp, 3):
        return
    dealt = _indirect_damage(battle, unit, target, actual_hp * .5, t)
    if dealt:
        fire(battle, inst, target, t, label='连环拳', kind='damage', value=dealt, spend=False)


def _h_deep_freeze(battle, inst, source, target, actual_hp, t, **_):
    if source is not inst.unit or actual_hp <= 0 or not target.alive:
        return
    counts = inst.state.setdefault('hits', {})
    counts[target.idx] = counts.get(target.idx, 0) + 1
    if counts[target.idx] % 5:
        return
    import status
    if status.apply_debuff(battle, target, 'freeze', t, source=source):
        st = getattr(target, '_st', None)
        if st is not None:
            st.expire = min(st.expire, t + 1.)
            st.stun_until = min(st.stun_until, t + 1.)
        fire(battle, inst, target, t, label='冰封', kind='debuff', spend=False)


def _h_iron_reflect(battle, inst, source, target, actual_hp, t, **_):
    if target is not inst.unit or source is None or source.team == target.team or actual_hp <= 0:
        return
    dealt = _indirect_damage(battle, target, source, actual_hp * .10, t)
    if dealt:
        fire(battle, inst, source, t, label='反甲', kind='damage', value=dealt, spend=False)


def _threshold(inst, unit, fraction):
    return (unit is inst.unit and unit.alive and unit.hp <= unit.max_hp * fraction
            and inst.uses == 0)


def _h_thorn_snare(battle, inst, source, target, t, **_):
    unit = inst.unit
    if not _threshold(inst, target, .40):
        return
    rooted = 0
    for enemy in battle.units:
        if enemy.alive and enemy.team != unit.team and _dist(enemy, unit) == 1:
            enemy.root_until = max(enemy.root_until, t + 1.5)
            enemy.root_source = unit.idx
            battle._emit_state(enemy, t)
            rooted += 1
    if rooted:
        fire(battle, inst, unit, t, label='荆棘缠绕', kind='debuff', value=rooted)
    else:
        inst.spend(t)


def _h_molt(battle, inst, source, target, t, **_):
    unit = inst.unit
    if not _threshold(inst, target, .35):
        return
    import status
    status.cleanse(battle, unit, t)
    shield = int(unit.max_hp * .20)
    _shield(battle, unit, unit, shield, t, 'molt')
    fire(battle, inst, unit, t, label='蜕壳', kind='shield', value=shield)


def _h_escape_pack(battle, inst, source, target, t, **_):
    unit = inst.unit
    if not _threshold(inst, target, .40):
        return
    back_row = battle.rows - 1 if unit.team == 0 else 0
    occupied = {u.pos for u in battle.units if u.alive}
    cells = sorted(((c, back_row) for c in range(battle.cols) if (c, back_row) not in occupied),
                   key=lambda cell: abs(cell[0] - unit.pos[0]))
    if cells and _local_row(battle, unit) != 2:
        _leap(battle, unit, cells[0], t, 'escape_pack')
        for enemy in battle.units:
            if enemy.target_idx == unit.idx and enemy.range == 1:
                enemy.target_idx = None
    shield = int(unit.max_hp * .20)
    _shield(battle, unit, unit, shield, t, 'escape_pack')
    fire(battle, inst, unit, t, label='撤退', kind='shield', value=shield)


def _h_blast_core(battle, inst, unit, killer, t, **_):
    if unit is not inst.unit or inst.uses:
        return
    total = 0
    for victim in sorted((v for v in battle.units if v.alive and v.team != unit.team
                          and _dist(v, unit) == 1), key=lambda v: v.local_idx):
        total += _indirect_damage(battle, unit, victim, unit.max_hp * .25, t)
    fire(battle, inst, unit, t, label='爆裂', kind='damage', value=total, camera='focus')


def _native_owner(inst, unit):
    return unit is inst.unit and unit.alive


def _h_aftershock(battle, inst, unit, t, cast_index, **_):
    if not _native_owner(inst, unit):
        return
    _flinch_adjacent(battle, inst, unit, t, '余震')


def _flinch_adjacent(battle, inst, unit, t, label):
    import status
    hit = 0
    for enemy in battle.units:
        if enemy.alive and enemy.team != unit.team and _dist(enemy, unit) == 1:
            if status.apply_flinch(battle, enemy, t):
                hit += 1
    if hit:
        fire(battle, inst, unit, t, label=label, kind='debuff', value=hit, spend=False)


def _h_telekinesis(battle, inst, unit, target, t, cast_index, lost_hp, **_):
    if not _native_owner(inst, unit) or lost_hp <= 0 or not target.alive:
        return
    from arena_fields import move_unit
    destination = battle._knock_cell(target, unit.pos)
    if destination is not None:
        move_unit(battle, target, destination, t, cast_index, source=unit, reason='knockback')
        fire(battle, inst, target, t, label='念动', kind='move', spend=False)


# ---- skill mods
def _h_mod_spread(battle, inst, unit, target, t, cast_index, lost_hp, move, **_):
    if not _native_owner(inst, unit) or lost_hp <= 0:
        return
    victims = sorted((v for v in battle.units if v.alive and v.team != unit.team and v is not target
                      and _dist(v, target) == 1), key=lambda v: battle._target_key(unit, v))[:2]
    total = sum(_indirect_damage(battle, unit, v, lost_hp * .35, t) for v in victims)
    if total:
        fire(battle, inst, target, t, label='扩散', kind='damage', value=total, spend=False)


def _h_mod_execute(battle, inst, unit, target, t, cast_index, lost_hp, **_):
    if not _native_owner(inst, unit) or not target.alive or target.hp > target.max_hp * .15:
        return
    remaining = target.hp
    _indirect_damage(battle, unit, target, remaining + max(target.shield, 0) + 1, t)
    fire(battle, inst, target, t, label='处决', kind='damage', value=remaining, spend=False,
         camera='focus')


def _h_mod_sustain_primary(battle, inst, unit, target, t, cast_index, lost_hp, **_):
    if not _native_owner(inst, unit) or lost_hp <= 0:
        return
    healed = battle._heal(unit, int(lost_hp * .30), t, source=unit)
    if healed:
        fire(battle, inst, unit, t, label='汲取', kind='heal', value=healed, spend=False)


def _h_mod_sustain_support(battle, inst, unit, t, cast_index, **_):
    if not _native_owner(inst, unit) or unit.arena_role != 'support':
        return
    healed = battle._heal(unit, int(unit.max_hp * .08), t, source=unit)
    if healed:
        fire(battle, inst, unit, t, label='汲取', kind='heal', value=healed, spend=False)


def _h_mod_fortify(battle, inst, unit, t, cast_index, **_):
    if not _native_owner(inst, unit):
        return
    shield = int(unit.max_hp * .15)
    if _shield(battle, unit, unit, shield, t, 'fortify'):
        fire(battle, inst, unit, t, label='坚壁', kind='shield', value=shield, spend=False)


def _h_mod_quake(battle, inst, unit, t, cast_index, **_):
    if _native_owner(inst, unit):
        _flinch_adjacent(battle, inst, unit, t, '震地')


def _h_mod_retaliate_cast(battle, inst, unit, t, cast_index, **_):
    if _native_owner(inst, unit):
        unit.retaliate_until = t + 4.


def _h_mod_retaliate_hit(battle, inst, source, target, actual_hp, t, **_):
    if (target is not inst.unit or source is None or source.team == target.team
            or actual_hp <= 0 or target.retaliate_until <= t + EPS):
        return
    dealt = _indirect_damage(battle, target, source, actual_hp * .30, t)
    if dealt:
        fire(battle, inst, source, t, label='反震', kind='damage', value=dealt, spend=False)


def _h_mod_overflow(battle, inst, unit, t, cast_index, **_):
    if not _native_owner(inst, unit):
        return
    mates = sorted((m for m in battle.units if m.alive and m.team == unit.team and m is not unit
                    and _dist(m, unit) <= 2), key=lambda m: (m.hp / m.max_hp, m.local_idx))[:2]
    total = 0
    for mate in mates:
        amount = int(mate.max_hp * .08)
        if _shield(battle, unit, mate, amount, t, 'overflow'):
            total += amount
    if total:
        fire(battle, inst, unit, t, label='溢流', kind='shield', value=total, spend=False)


def _h_mod_quicken(battle, inst, unit, t, cast_index, **_):
    if not _native_owner(inst, unit):
        return
    gained = _energy(battle, unit, 25)
    if gained:
        battle._emit_state(unit, t)
        fire(battle, inst, unit, t, label='迅捷', kind='energy', value=gained, spend=False)


def _h_mod_sanctify(battle, inst, unit, t, cast_index, **_):
    if not _native_owner(inst, unit):
        return
    import status
    mates = [m for m in battle.units if m.alive and m.team == unit.team and _dist(m, unit) <= 2]
    if not mates:
        return
    patient = min(mates, key=lambda m: (getattr(getattr(m, '_st', None), 'debuff', None) is None,
                                        m.hp / m.max_hp, m.local_idx))
    status.cleanse(battle, patient, t)
    patient.temp_dr, patient.temp_dr_until = max(patient.temp_dr, .25), t + 3.
    battle._emit_state(patient, t)
    fire(battle, inst, patient, t, label='圣洁', kind='buff', spend=False)


# ---- items
def _h_mind_crystal(battle, inst, unit, t, cast_index, **_):
    if not _native_owner(inst, unit):
        return
    gained = _energy(battle, unit, 20)
    if gained:
        battle._emit_state(unit, t)
        fire(battle, inst, unit, t, label='心灵水晶', kind='energy', value=gained)


def _h_quick_claw(battle, inst, unit, t, cast_index, **_):
    if _native_owner(inst, unit):
        unit.haste_until, unit.haste_fraction = t + 3., .25
        fire(battle, inst, unit, t, label='先制', kind='buff', spend=False)


# ---- terrain (team-owned, per-second cadence)
def _every_second(inst, t):
    if t + EPS < inst.state.get('next', 1.):
        return False
    inst.state['next'] = inst.state.get('next', 1.) + 1.
    return True


def _h_terrain_spring(battle, inst, t, **_):
    if not _every_second(inst, t):
        return
    for unit in battle.units:
        if unit.alive and unit.team == inst.team and unit.pos in battle.terrain_cells[inst.team]:
            gained = _energy(battle, unit, 6)
            if gained:
                battle._emit_state(unit, t)
                battle.fx.ledger.add(inst.team, 'terrain', ledger_key(inst.spec), triggers=1, energy=gained)


def _h_terrain_brambles(battle, inst, t, **_):
    if not _every_second(inst, t):
        return
    for unit in battle.units:
        if unit.alive and unit.team == inst.team and unit.pos in battle.terrain_cells[inst.team]:
            dealt = battle._land_hit(unit, unit, max(1, int(unit.max_hp * .02)), t, direct=False)
            battle.fx.ledger.add(inst.team, 'terrain', 'brambles', triggers=1, damage=dealt)


def _h_terrain_sanctum(battle, inst, t, **_):
    if not _every_second(inst, t):
        return
    for unit in battle.units:
        if (unit.alive and unit.team == inst.team and unit.hp < unit.max_hp
                and unit.pos in battle.terrain_cells[inst.team]):
            healed = battle._heal(unit, max(1, int(unit.max_hp * .015)), t, source=unit)
            battle.fx.ledger.add(inst.team, 'terrain', 'sanctum', triggers=1, heal=healed)


def _spec(id, source, trigger, name, handler, description='', **kw):
    return EffectSpec(id=id, source=source, trigger=trigger, name=name, description=description,
                      handler=handler, **kw)


UNIT_SPECS = (
    # bond breakpoints
    _spec('sky_dive', 'bond', 'battle_start', '俯冲', _h_sky_dive, limit=1),
    _spec('wildfire', 'bond', 'basic_settled', '燎原', _h_wildfire),
    _spec('arc_chain', 'bond', 'basic_settled', '电弧', _h_arc_chain),
    _spec('flurry', 'bond', 'basic_settled', '连环拳', _h_flurry),
    _spec('deep_freeze', 'bond', 'direct_hit', '冰封', _h_deep_freeze),
    _spec('iron_reflect', 'bond', 'direct_hit', '反甲', _h_iron_reflect),
    _spec('thorn_snare', 'bond', 'direct_hit', '荆棘缠绕', _h_thorn_snare, limit=1),
    _spec('molt', 'bond', 'direct_hit', '蜕壳', _h_molt, limit=1),
    _spec('aftershock', 'bond', 'native_cast', '余震', _h_aftershock),
    _spec('telekinesis', 'bond', 'native_primary', '念动', _h_telekinesis),
    # skill modifiers
    _spec('spread', 'skill_mod', 'native_primary', '扩散', _h_mod_spread),
    _spec('execute', 'skill_mod', 'native_primary', '处决', _h_mod_execute),
    _spec('sustain', 'skill_mod', 'native_primary', '汲取', _h_mod_sustain_primary),
    _spec('fortify', 'skill_mod', 'native_cast', '坚壁', _h_mod_fortify),
    _spec('quake', 'skill_mod', 'native_cast', '震地', _h_mod_quake),
    _spec('retaliate', 'skill_mod', 'native_cast', '反震', _h_mod_retaliate_cast),
    _spec('overflow', 'skill_mod', 'native_cast', '溢流', _h_mod_overflow),
    _spec('quicken', 'skill_mod', 'native_cast', '迅捷', _h_mod_quicken),
    _spec('sanctify', 'skill_mod', 'native_cast', '圣洁', _h_mod_sanctify),
    # items
    _spec('mind_crystal', 'item', 'native_cast', '心灵水晶', _h_mind_crystal, cooldown=2., limit=4),
    _spec('quick_claw', 'item', 'native_cast', '先制之爪', _h_quick_claw),
    _spec('escape_pack', 'item', 'direct_hit', '逃脱背包', _h_escape_pack, limit=1),
    _spec('blast_core', 'item', 'death', '爆裂核心', _h_blast_core, limit=1),
)
# Second subscriptions for two-trigger effects (same id, separate instance state).
UNIT_SPECS += (
    _spec('sustain', 'skill_mod', 'native_cast', '汲取', _h_mod_sustain_support),
    _spec('retaliate', 'skill_mod', 'direct_hit', '反震', _h_mod_retaliate_hit),
)
UNIT_SPECS += _mech.UNIT_SPECS
TEAM_SPECS = (
    _spec('charge_horn', 'augment', 'battle_start', '冲锋号', _h_charge_horn, owner='team', limit=1),
    _spec('vanguard', 'augment', 'battle_start', '先锋壁垒', _h_vanguard, owner='team', limit=1),
    _spec('mana_siphon', 'augment', 'native_cast', '能量虹吸', _h_mana_siphon, owner='team'),
    _spec('chain_reaction', 'augment', 'death', '连锁爆破', _h_chain_reaction, owner='team'),
    _spec('executioner', 'augment', 'direct_hit', '斩首令', _h_executioner, owner='team'),
    _spec('terrain_mana_spring', 'terrain', 'tick', '能量泉', _h_terrain_spring, owner='team'),
    _spec('terrain_brambles', 'terrain', 'tick', '荆棘丛', _h_terrain_brambles, owner='team'),
    _spec('terrain_sanctum', 'terrain', 'tick', '圣域', _h_terrain_sanctum, owner='team'),
)


def haste_multiplier(unit, t):
    return 1. + unit.haste_fraction if getattr(unit, 'haste_until', 0.) > t + EPS else 1.
