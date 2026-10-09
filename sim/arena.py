"""Opt-in, small-pool arena rules. Classic species evolution is unchanged."""
import copy

from data import pokedex
from roster import Piece, LEVEL_BY_TIER, MELEE, RANGED
import techniques
import rng as rng_mod

RULESET = 'arena_v1'
ROLE_NAMES = {'attack': '攻击型', 'defense': '防守型', 'support': '辅助型'}
ROLE_DESCRIPTIONS = {
    'attack': '攻击与特攻提高 12%，专注输出；需要队友保护。',
    'defense': '生命提高 25%，受到伤害降低 18%，攻击与特攻降低 15%；在前排持续消耗。',
    'support': '攻击与特攻降低 20%；可行动时每秒获得 4 能量。本命技能分为治疗、护盾、净化、充能与救援，援护技能无需先攻击敌人。',
}
# Keep the original pool explicit so verified old saves can add new stock once.
ORIGINAL_ROSTER = {
    26: (1, 'attack'), 68: (1, 'attack'), 31: (1, 'defense'), 76: (1, 'defense'),
    40: (1, 'support'), 12: (1, 'support'),
    34: (2, 'attack'), 94: (2, 'attack'), 59: (2, 'defense'), 73: (2, 'defense'),
    36: (2, 'support'), 45: (2, 'support'),
    6: (3, 'attack'), 65: (3, 'attack'), 9: (3, 'defense'), 80: (3, 'defense'),
    3: (3, 'support'), 121: (3, 'support'),
}
EXPANSION_ROSTER = {
    95: (1, 'defense'), 106: (1, 'attack'), 108: (1, 'support'), 114: (1, 'defense'),
    113: (2, 'support'), 122: (2, 'support'), 125: (2, 'attack'), 127: (2, 'attack'),
    123: (3, 'attack'), 128: (3, 'defense'), 131: (3, 'support'), 142: (3, 'attack'),
}
GEN2_ROSTER = {
    162: (1, 'attack'), 211: (1, 'attack'), 195: (1, 'defense'), 237: (1, 'defense'),
    164: (1, 'support'), 171: (1, 'support'),
    181: (2, 'attack'), 196: (2, 'attack'), 214: (2, 'attack'), 197: (2, 'defense'),
    208: (2, 'defense'), 242: (2, 'support'),
    157: (3, 'attack'), 212: (3, 'attack'), 230: (3, 'attack'), 160: (3, 'defense'),
    248: (3, 'defense'), 154: (3, 'support'),
}
ROSTER = {**ORIGINAL_ROSTER, **EXPANSION_ROSTER, **GEN2_ROSTER}
POOL_BY_COST = {1: 22, 2: 18, 3: 12}
PVE_WAVES = ((76, 76), (68, 68, 12), (31, 34, 73, 40),
             (9, 9, 65, 36), (59, 59, 6, 6, 3), (9, 9, 6, 6, 65, 121))
PVE_LABELS = ('滚石试炼', '四臂试炼', '毒刺试炼', '水炮试炼', '火焰试炼', '进化精英试炼')
AUGMENTS = {
    'sharp_focus': {'name': '精准火力', 'description': '全队攻击与特攻提高 12%。'},
    'iron_wall': {'name': '坚不可摧', 'description': '全队额外减伤 8%，与其他减伤相乘。'},
    'first_aid': {'name': '急救花园', 'description': '辅助型的每次团队回复量提高 30%。'},
    'vitality': {'name': '生命之泉', 'description': '全队最大生命提高 15%。'},
    'quick_step': {'name': '迅捷步伐', 'description': '全队攻击速度提高 12%。'},
    'mana_flow': {'name': '能量涌动', 'description': '全队开战时获得 20 点能量，更早施放招式。'},
    'poison_catalyst': {'name': '毒性催化', 'description': '原生技能主命中对施法前已中毒的目标造成实际生命损失后，施法者获得 8 能量；每只冷却 2 秒、每战最多 3 次。教学、毒伤和侧击不触发。'},
    'watch_echo': {'name': '守望回响', 'description': '辅助原生技能有效治疗其他队友后，为两格内未满能量、能量最高的攻击型队友补 8 能量；每名辅助冷却 4 秒、每战最多 3 次。被动回复和睡觉不触发。'},
    'barrier_feedback': {'name': '屏障回流', 'shield_threshold': .05, 'energy': 8,
                         'cooldown': 4., 'limit': 3,
                         'description': '自己提供给其他队友的护盾实际吸收累计达到受盾者最大生命的 5%，为施盾者补 8 能量。同一连续护盾周期最多触发一次，更强覆盾不重置资格；每名施盾者冷却 4 秒、每战最多 3 次。自盾、已阵亡或满能量的施盾者无收益。'},
    'native_inspiration': {'name': '充能鼓舞', 'damage_bonus': .25, 'duration': 3.,
                           'cooldown': 5., 'limit': 3,
                           'description': '实际收到其他友军本命技能回能后，直接攻击伤害提高 25%，持续 3 秒；每只受益宝可梦冷却 5 秒、每战最多 3 次。强化普攻、攻击技能及按正常直接命中结算的反击，不强化毒伤、岩钉或治疗。不叠加；自回能、普攻回能、教学及其他海克斯回能不触发。'},
    'breach_momentum': {'name': '乘隙追击', 'vulnerability': .12, 'duration': 4.,
                        'cooldown': 4., 'limit': 3,
                        'description': '原生技能或吼叫成功把存活敌人击退后，使其受到的伤害提高 12%、持续 4 秒。每名推动者冷却 4 秒、每战最多 3 次。移动、救援、闪现及被边界或堵路阻止的击退不触发，当前技能不能吃到自己新施加的易伤。'},
    'growth_mark': {'name': '成长印记',
                    'description': '成长型：选取后每经过一轮，全队攻击与特攻提高 2%，最多叠加 5 层（+10%）。'},
    'growth_bulwark': {'name': '积蓄力量',
                       'description': '成长型：选取后每经过一轮，全队最大生命提高 2%，最多叠加 5 层（+10%）。'},
    'war_drum': {'name': '战鼓催征',
                 'description': '成长型：全队攻击速度提高 1%×当前轮数，第 12 轮起封顶（+12%）。'},
    'xp_doctrine': {'name': '经验学说',
                    'description': '成长型：选取后的每轮开始自动获得 1 点经验；持有满 6 轮后改为每轮 2 点。'},
    'war_banner': {'name': '战旗高扬',
                   'description': '全队攻击与特攻提高 6%，攻击速度提高 6%。完成竞技挑战「竞技首秀」后进入候选池。'},
    'deep_reserves': {'name': '深厚储备',
                      'description': '全队最大生命提高 8%，开战时获得 10 点能量。完成竞技挑战「竞技场冠军」后进入候选池。'},
}
# Challenge-locked candidates: an option unlock for future runs, never a
# permanent buff. Bots always draw from the base pool; the player's pool gains
# unlocked entries from the run-start profile snapshot (session.arena_unlocks).
AUGMENT_LOCKS = {'war_banner': 'arena_first_finish', 'deep_reserves': 'arena_first_win'}
AUGMENT_MILESTONES = (1, 7, 13)
# Growth augments derive every bonus from the pick milestone index and the
# current round, so no per-round hook or extra ledger ever reaches the save.
GROWTH_STAT_KEYS = frozenset({'growth_mark', 'growth_bulwark'})
GROWTH_STAT_STEP = .02
GROWTH_STAT_CAP = 5
WAR_DRUM_STEP = .01
WAR_DRUM_CAP_ROUND = 12
XP_DOCTRINE_STEP_ROUNDS = 6
GROWTH_KEYS = frozenset({'growth_mark', 'growth_bulwark', 'war_drum', 'xp_doctrine'})
GROWTH_STACK_LIMIT = WAR_DRUM_CAP_ROUND


def augment_view(key):
    if key not in AUGMENTS:
        raise ValueError('未知海克斯强化')
    return {'id': key, **copy.deepcopy(AUGMENTS[key])}


def build_templates():
    dex = pokedex()
    result = {}
    for sid, (cost, role) in ROSTER.items():
        move = dex.signature_move(sid)
        base = dex.species_record(sid)['base']
        distance = RANGED if role == 'support' or base['special_attack'] > base['attack'] else MELEE
        p = Piece(sid, cost, LEVEL_BY_TIER[cost], move_id=move and move['id'], distance=distance)
        p.star, p.shiny, p.role_key = 1, False, role
        result[sid] = p
    return result


def pool_cap(species_id):
    return POOL_BY_COST[ROSTER[species_id][0]]


def pool_caps():
    return {sid: pool_cap(sid) for sid in ROSTER}


def technique_catalog():
    return [{**t, 'cost': 2} for t in techniques.catalog(RULESET)]


def init_seat(seat):
    seat.arena_augments_selected = []
    seat.inventory.finished.append('sash')
    seat.inventory.add_component('band')
    seat.inventory.add_component('magnet')


def _keys(seat):
    return [a['id'] if isinstance(a, dict) else a for a in seat.arena_augments_selected]


def augment_pool(session, seat):
    """Unclaimed candidates for one seat; locked entries need the player's unlocks."""
    locked = set(AUGMENT_LOCKS)
    if seat is session.player:
        locked -= set(getattr(session, 'arena_unlocks', {}).get('augments', ()))
    return sorted(set(AUGMENTS) - set(_keys(seat)) - locked)


def growth_stacks(seat, round_no):
    """Live growth values; the pick milestone index fixes the elapsed rounds."""
    stacks = {}
    for index, key in enumerate(_keys(seat)):
        elapsed = max(0, round_no - AUGMENT_MILESTONES[index])
        if key in GROWTH_STAT_KEYS:
            stacks[key] = min(GROWTH_STAT_CAP, elapsed)
        elif key == 'war_drum':
            stacks[key] = min(WAR_DRUM_CAP_ROUND, max(0, round_no))
        elif key == 'xp_doctrine':
            stacks[key] = 2 if elapsed >= XP_DOCTRINE_STEP_ROUNDS else 1
    return stacks


def augment_status(session, seat, key):
    """Panel view: static augments stay verbatim; growth augments show live strength."""
    view = augment_view(key)
    stacks = growth_stacks(seat, session.round_no)
    cap = int(round(GROWTH_STAT_CAP * GROWTH_STAT_STEP * 100))
    if key in GROWTH_STAT_KEYS:
        current = int(round(stacks[key] * GROWTH_STAT_STEP * 100))
        view['current'] = f'当前 +{current}%（{stacks[key]}/{GROWTH_STAT_CAP} 层，上限 +{cap}%）'
    elif key == 'war_drum':
        view['current'] = (f'当前 +{stacks[key]}% 攻速'
                           f'（第 {WAR_DRUM_CAP_ROUND} 轮起封顶 +{WAR_DRUM_CAP_ROUND}%）')
    elif key == 'xp_doctrine':
        view['current'] = f'当前每轮开始 +{stacks[key]} 经验'
    return view


def _grant_bonus_xp(level, xp, amount):
    import economy
    xp += amount
    while True:
        need = economy.xp_to_next(level)
        if need is None or xp < need:
            return level, xp
        xp -= need
        level += 1


def begin_round(session):
    r = session.round_no
    # 经验学说在本轮三选一发放之前结算，本轮刚选取的从下一轮开始收益。
    for seat in session.seats:
        if seat.alive and 'xp_doctrine' in _keys(seat):
            seat.level, seat.xp = _grant_bonus_xp(seat.level, seat.xp,
                                                  growth_stacks(seat, r)['xp_doctrine'])
    if r in AUGMENT_MILESTONES:
        for seat in session.seats:
            if not seat.alive:
                continue
            available = augment_pool(session, seat)
            rng = rng_mod.derive(session.seed, r, 'bots', 8000 + seat.seat)
            options = [augment_view(k) for k in rng.sample(available, 3)]
            if seat is session.player:
                session.arena_augments_pending = [{'id': f'augment-r{r}', 'round': r, 'options': options,
                                                   'rerolled': False}]
            else:
                seat.arena_augments_selected.append(options[rng.randrange(3)])
    # One paid teaching per AI per round, after purchasing and deployment.
    for seat in session.bots:
        if not seat.alive:
            continue
        if seat.gold >= 2:
            owned, key = bot_teaching_choice(seat.board)
            if owned is not None:
                owned.technique = key
                seat.gold -= 2
        rain = any(owned.technique == 'rain_dance' for owned in seat.board)
        for owned in seat.all_pieces():
            sid = owned.piece.species_id
            if sid == 34:
                owned.arena_trait = 'trait_sheer_force' if owned.item == 'life_orb' else None
            elif sid == 9:
                owned.arena_trait = 'trait_rain_dish' if rain else None


def bot_teaching_choice(board):
    """Build a legal weather pair from owned teammates, never future rolls."""
    unused = [owned for owned in board if owned.technique is None]
    if not unused:
        return None, None
    known = {owned.technique for owned in board}
    types = [set(owned.piece.types) for owned in board]
    def learner(key):
        eligible = [owned for owned in unused if techniques.compatible_species(
            owned.piece.species_id, key, RULESET)]
        return min(eligible, key=lambda owned: (
            owned.piece.role_key != 'support', owned.piece.role_key == 'attack',
            owned.piece.species_id), default=None)
    if not known.intersection({'rain_dance', 'sunny_day'}):
        wants_rain = (any('WATER' in row for row in types)
                      and (any('ELECTRIC' in row for row in types)
                           or any(owned.piece.species_id == 230 for owned in board)))
        wants_sun = (sum(bool(row.intersection({'GRASS', 'FIRE'})) for row in types) >= 2
                     and any(owned.piece.species_id == 3 for owned in board))
        for key, wanted in (('rain_dance', wants_rain), ('sunny_day', wants_sun)):
            owned = learner(key) if wanted else None
            if owned is not None:
                return owned, key
    if 'rain_dance' in known and 'thunder' not in known:
        owned = learner('thunder')
        if owned is not None:
            return owned, 'thunder'
    for owned in unused:
        if owned.piece.species_id == 34 and owned.item == 'life_orb':
            return owned, 'ice_beam'
    owned = unused[0]
    key = 'rest' if owned.piece.role_key != 'attack' else (
        'surf' if 'WATER' in owned.piece.types else 'cut' if techniques.compatible_species(
            owned.piece.species_id, 'cut', RULESET) else 'rest')
    return owned, key


def claim_augment(session, reward_id, choice):
    pending = session.arena_augments_pending
    row = next((r for r in pending if r['id'] == reward_id), None)
    if row is None or row['round'] != session.round_no:
        raise ValueError('这次海克斯选择已经结束')
    if choice not in [a['id'] for a in row['options']] or choice in _keys(session.player):
        raise ValueError('请选择本轮提供的海克斯强化')
    session.player.arena_augments_selected.append(augment_view(choice))
    pending.remove(row)
    return '获得海克斯：' + AUGMENTS[choice]['name']


def reroll_augment(session, reward_id):
    pending = session.arena_augments_pending
    row = next((r for r in pending if r['id'] == reward_id), None)
    if row is None or row['round'] != session.round_no:
        raise ValueError('这次海克斯选择已经结束')
    if row.get('rerolled'):
        raise ValueError('本轮海克斯候选已经刷新过一次')
    replaced = {a['id'] for a in row['options']}
    available = sorted(set(augment_pool(session, session.player)) - replaced)
    if len(available) < 3:
        raise ValueError('没有足够的海克斯强化可供刷新')
    rng = rng_mod.derive(session.seed, row['round'], 'bots', 8100 + session.player.seat)
    row['options'] = [augment_view(k) for k in rng.sample(available, 3)]
    row['rerolled'] = True
    return '海克斯候选已刷新：原来的三个强化不可再选'


def learn(session, loc, key):
    catalog = {t['id']: t for t in technique_catalog()}
    if key not in catalog:
        raise ValueError('未知教学技能')
    owned, _, _ = session.locate(loc)
    techniques.validate_learning(owned.piece.species_id, key, ruleset=RULESET)
    if owned.technique == key:
        raise ValueError('已经学会这个技能')
    cost = catalog[key]['cost']
    if session.player.inventory.techniques[key] > 0:
        session.player.inventory.techniques[key] -= 1
        owned.technique = key
        return f'{owned.piece.name}学会{catalog[key]["name"]}（消耗1台技能机，替换不返还旧技能）'
    if session.player.gold < cost:
        raise ValueError(f'学习需要 {cost} 金币')
    session.player.gold -= cost
    owned.technique = key
    return f'{owned.piece.name}学会{catalog[key]["name"]}（-{cost} 金币，替换不返还旧技能）'


def set_trait(session, loc, key):
    """One mutually exclusive species ability, chosen freely before combat."""
    import arena_traits
    if session.ruleset != RULESET or session.phase != 'prep' or not session.player.alive:
        raise ValueError('只能在竞技准备期选择特性')
    owned, _, _ = session.locate(loc)
    if isinstance(key, str) and key in arena_traits.TRAIT_LOCKS and key not in getattr(
            session, 'arena_unlocks', {}).get('traits', ()):
        raise ValueError('该特性需要先完成对应的竞技挑战解锁')
    choice = arena_traits.validate_choice(owned.piece.species_id, key)
    selected = arena_traits.for_species(owned.piece.species_id, choice)
    if selected is None:
        raise ValueError('该宝可梦尚未配置特性')
    owned.arena_trait = choice
    return f'{owned.piece.name}选择特性：{selected["name"]}'


def battle_piece(owned):
    """Snapshot an owned choice without changing a shared species template."""
    import arena_traits
    piece = copy.copy(owned.piece)
    piece.arena_trait_key = arena_traits.validate_choice(
        piece.species_id, getattr(owned, 'arena_trait', None))
    return piece


def battle_comp(owned_pieces):
    result = []
    for owned in owned_pieces:
        piece = battle_piece(owned)
        result.append((piece, owned.item) if owned.item else piece)
    return result


def battle_options(session, a, b):
    options = {'ruleset': RULESET, 'stat_mode': 'budget_v1',
               'arena_teams': [_keys(seat) if seat is not None else [] for seat in (a, b)],
               'arena_growth': [growth_stacks(seat, session.round_no) if seat is not None else {}
                                for seat in (a, b)]}
    if a is not None and a is not session.player:
        options['positions_a'] = positions_for(a.board, 0)
    if b is not None:
        options['positions_b'] = positions_for(b.board, 1)
    return options


def positions_for(comp, team):
    """Place defenders toward the centre, support behind, with stable columns."""
    occupied, positions = set(), []
    for entry in comp:
        if isinstance(entry, tuple):
            entry = entry[0]
        p = entry if isinstance(entry, dict) else getattr(entry, 'piece', entry)
        role = p.get('role_key', 'attack') if isinstance(p, dict) else getattr(p, 'role_key', 'attack')
        from profiles import effective_range
        ranged = p.get('ranged', False) if isinstance(p, dict) else effective_range(p) > 1
        rows = (2, 1, 0) if role == 'support' else (1, 2, 0) if role == 'attack' and ranged else (0, 1, 2)
        pos = next((r, c) for r in rows for c in (2, 3, 1, 4, 0, 5) if (r, c) not in occupied)
        occupied.add(pos)
        r, c = pos
        positions.append((c, r + 3) if team == 0 else (5 - c, 2 - r))
    return positions


def combine(board, bench, inventory=None, *, single=False, only_species=None):
    """Merge owned card accounting without taking an extra pool copy."""
    from shop import OwnedPiece
    logs = []
    while True:
        grouped = {}
        for owned in board + bench:
            sid, star = owned.piece.species_id, owned.piece.star
            if star < 3 and (only_species is None or sid == only_species):
                grouped.setdefault((sid, star), []).append(owned)
        group = next((v[:3] for k, v in sorted(grouped.items()) if len(v) >= 3), None)
        if group is None:
            break
        p = copy.copy(group[0].piece)
        p.star += 1
        p.shiny = p.star == 3
        merged = OwnedPiece(p, sum(o.invested for o in group))
        merged.uid = group[0].uid
        # The survivor keeps both its UID and mutually exclusive ability.
        merged.arena_trait = getattr(group[0], 'arena_trait', None)
        merged.sources = [s for o in group for s in o.sources]
        for owned in group:
            if owned.item:
                if merged.item is None:
                    merged.item = owned.item
                elif inventory is not None:
                    inventory.finished.append(owned.item)
            if owned.technique and merged.technique is None:
                merged.technique = owned.technique
            (board if owned in board else bench).remove(owned)
        bench.append(merged)
        logs.append(f'{p.name}升为{p.star}星' + ('闪光' if p.shiny else ''))
        if single:
            break
    return logs
