"""arena_v2 session rules: economy, items, skill modifiers, core unit, draft rounds.

The demo session (tools/acceptance/demo.py) calls these helpers only when its
ruleset is arena_v2. Every function is deterministic given the session seed
and round; nothing here touches arena_v1 sessions.
"""
import copy

import arena_depth
import economy
import items
import rng as rng_mod
import techniques

RULESET = 'arena_v2'
SIMULATIONS_PER_ROUND = 2
FAST_TRACK_LIMIT = 3
SIMULATION_BATTLES = 6
TARGETED_REFRESH_COST = 3
UNEQUIP_COST = 1
DISMANTLE_COST = 1
ITEM_SELL_VALUE = 2
DRAFT_ROUNDS = (4, 9, 14, 19, 24)
LOSS_RELIEF_STREAK = 3


def is_depth(session):
    return getattr(session, 'ruleset', None) == RULESET


def augment_keys(seat):
    return [a['id'] if isinstance(a, dict) else a for a in seat.arena_augments_selected]


def has(seat, key):
    return key in augment_keys(seat)


def seat_state(seat):
    """Per-seat v2 counters (persisted by session_save)."""
    state = getattr(seat, 'depth', None)
    if state is None:
        state = {}
        seat.depth = state
    for key, value in (('free_refreshes', 0), ('relief', 0), ('sims', 0), ('targeted', 0),
                       ('fast_track', 0), ('draft_uid', None)):
        state.setdefault(key, value)
    return state


# ------------------------------------------------------------------ economy
def population(seat):
    base = economy.pop_of(seat.level)
    return max(1, base - arena_depth.population_penalty(augment_keys(seat)))


def extra_interest(seat, gold_after_base):
    """interest_master raises the interest cap from 5 to 8."""
    if not has(seat, 'interest_master'):
        return 0
    return max(0, min(gold_after_base // 10, 8) - min(gold_after_base // 10, economy.INTEREST_CAP))


def refresh_cost(seat):
    return 0 if seat_state(seat)['free_refreshes'] > 0 else economy.REFRESH_COST


def spend_refresh(seat):
    state = seat_state(seat)
    if state['free_refreshes'] > 0:
        state['free_refreshes'] -= 1
        return 0
    seat.gold -= economy.REFRESH_COST
    return economy.REFRESH_COST


def targeted_cost(seat):
    """Base 3 (1 with free_roll); each extra targeted roll in the same round costs +1."""
    base = 1 if has(seat, 'free_roll') else TARGETED_REFRESH_COST
    return base + seat_state(seat)['targeted']


def type_options(session):
    import arena_bonds
    return [{'id': key, 'name': arena_bonds.TYPE_NAMES[key]} for key in arena_bonds.ELEMENT_TIERS]


def family_has_type(fid, element):
    from arena_families import FAMILIES
    from data import pokedex
    dex = pokedex()
    if fid not in FAMILIES:
        return dex.has_species(fid) and element in dex.species_record(fid)['types']
    return any(element in dex.species_record(sid)['types']
               for path in FAMILIES[fid][1] for sid in path)


def targeted_roll(session, seat, element, rng):
    """Reroll every slot from families that carry ``element`` (same level odds)."""
    shop = seat.shop
    for sid in shop.slots:
        if sid is not None:
            shop.pool.put(sid)
    import shop as shop_mod
    odds = shop_mod.ARENA_LEVEL_ODDS[min(max(seat.level, 1), max(shop_mod.ARENA_LEVEL_ODDS))]
    tiers = tuple(range(1, len(odds) + 1))
    slots = []
    for _ in range(shop.slot_count):
        tier = rng.choices(tiers, weights=odds)[0]
        chosen = None
        for t in (tier, tier - 1, tier + 1, *tiers):
            if t not in tiers:
                continue
            avail = [sid for sid, piece in shop.templates.items()
                     if piece.tier == t and shop.pool.remaining.get(sid, 0) > 0
                     and family_has_type(sid, element)]
            if avail:
                chosen = rng.choice(sorted(avail))
                shop.pool.take(chosen)
                break
        if chosen is None:
            chosen = shop_mod.draw_slot(rng, seat.level, shop.pool, shop.templates)
        slots.append(chosen)
    shop.slots = slots


# ------------------------------------------------------------------ items
def item_slots(owned, seat):
    return 2 if (getattr(owned, 'is_core', False) or has(seat, 'dual_wield')) else 1


def dismantle(seat, key):
    if key not in seat.inventory.finished:
        raise ValueError('仓库里没有这件成品装备')
    components = arena_depth.recipe_components(key)
    if not components:
        raise ValueError('这件装备无法拆解')
    cost = 0 if has(seat, 'salvage') else DISMANTLE_COST
    if seat.gold < cost:
        raise ValueError(f'拆解需要 {cost} 金币')
    seat.gold -= cost
    seat.inventory.finished.remove(key)
    for component in components:
        seat.inventory.add_component(component)
    names = '、'.join(items.COMPONENT_NAMES[c] for c in components)
    return f'拆解{items.FINISHED[key]["name"]}，取回{names}' + (f'（-{cost} 金）' if cost else '')


def draft_sell_value(seat, owned, value):
    """A unit drafted this round sells for 0 (no free item laundering)."""
    uid = seat_state(seat).get('draft_uid')
    return 0 if uid is not None and owned.uid == uid else value


def sell_item(seat, key):
    if key not in seat.inventory.finished:
        raise ValueError('仓库里没有这件成品装备')
    seat.inventory.finished.remove(key)
    seat.gold += ITEM_SELL_VALUE
    return f'出售{items.FINISHED[key]["name"]}（+{ITEM_SELL_VALUE} 金）'


def salvage_bonus(session, seat, owned):
    """Selling a 2/3-star unit with salvage yields one deterministic component."""
    if not has(seat, 'salvage') or getattr(owned.piece, 'star', 1) < 2:
        return None
    order = items.COMPONENT_ORDER
    seed_key = sum(ord(ch) for ch in (owned.uid or owned.piece.name))
    component = order[(seed_key + session.round_no) % len(order)]
    seat.inventory.add_component(component)
    return component


# ------------------------------------------------------------------ rewards
def roll_rewards(rng, result, seat):
    """One reward per battle; techniques only if someone on the seat can learn it."""
    pools = {
        'component': list(items.COMPONENT_ORDER),
        'item': sorted(set(items.catalog(RULESET)) - {'lucky_egg', 'evo_stone'}),
    }
    pieces = seat.all_pieces()
    learnable = [key for key in techniques.ids_for(RULESET)
                 if any(techniques.compatible_species(o.piece.species_id, key, RULESET)
                        for o in pieces)]
    if learnable:
        pools['technique'] = learnable
    weights = {'component': 5, 'item': 2, 'technique': 2}
    kinds = list(pools)
    kind = rng.choices(kinds, weights=[weights[k] for k in kinds])[0]
    grants = [{'kind': kind, 'key': rng.choice(pools[kind])}]
    if result == 'loss' and seat.streak <= -LOSS_RELIEF_STREAK:
        grants.append({'kind': 'component', 'key': rng.choice(pools['component'])})
    return grants


# ------------------------------------------------------------------ skill mods
def pending_mod_options(owned):
    star = getattr(owned.piece, 'star', 1)
    taken = list(getattr(owned, 'skill_mods', None) or [])
    if star < 2 or len(taken) >= star - 1:
        return []
    role = getattr(owned.piece, 'role_key', 'attack')
    next_star = len(taken) + 2
    return [arena_depth.mod_view(key) for key in arena_depth.mod_options(role, next_star)]


def choose_mod(owned, key):
    options = [row['id'] for row in pending_mod_options(owned)]
    if key not in options:
        raise ValueError('这只宝可梦当前不能选择该技能强化')
    owned.skill_mods = list(getattr(owned, 'skill_mods', None) or []) + [key]
    return f'{owned.piece.name}的本命技能获得「{arena_depth.MODS[key]["name"]}」'


def auto_mods(seat, prefer_first=True):
    """Bots (and unattended players) take a role-appropriate default."""
    for owned in seat.all_pieces():
        while True:
            options = pending_mod_options(owned)
            if not options:
                break
            choice = _bot_mod(owned, options) if not prefer_first else options[0]['id']
            choose_mod(owned, choice)


def _bot_mod(owned, options):
    preference = ('spread', 'execute', 'fortify', 'retaliate', 'quicken', 'sanctify',
                  'amplify', 'quake', 'overflow', 'sustain')
    ids = [row['id'] for row in options]
    return min(ids, key=preference.index)


# ------------------------------------------------------------------ core unit
def set_core(seat, owned):
    for other in seat.all_pieces():
        if other is not owned and getattr(other, 'is_core', False):
            other.is_core = False
            _return_extra_item(seat, other)
    owned.is_core = not getattr(owned, 'is_core', False)
    if not owned.is_core:
        _return_extra_item(seat, owned)
        return f'取消{owned.piece.name}的核心标记'
    return f'{owned.piece.name}成为核心：第二装备位、羁绊计数 +1、生命攻击 +15%（敌方刺客优先针对）'


def _return_extra_item(seat, owned):
    if getattr(owned, 'extra_item', None) and not has(seat, 'dual_wield'):
        seat.inventory.finished.append(owned.extra_item)
        owned.extra_item = None


def bot_core(seat):
    board = list(seat.board)
    if not board:
        return
    if any(getattr(o, 'is_core', False) for o in board):
        return
    best = max(board, key=lambda o: (getattr(o.piece, 'role_key', '') == 'attack',
                                     o.piece.star, o.piece.tier, -o.piece.species_id))
    for owned in seat.all_pieces():
        owned.is_core = owned is best


# ------------------------------------------------------------------ fast track
def fast_track(session, seat):
    """Complete pairs of 1-2 cost families from the pool (deterministic order)."""
    if not has(seat, 'fast_track') or seat_state(seat)['fast_track'] >= FAST_TRACK_LIMIT:
        return []
    from arena_families import FAMILIES, RARE
    logs = []
    groups = {}
    for owned in seat.all_pieces():
        p = owned.piece
        fid = getattr(p, 'family_id', None)
        if fid is None or fid in RARE or p.star >= 3 or FAMILIES[fid][0] > 2 or p.branch_id is None:
            continue
        groups.setdefault((fid, p.star, p.branch_id), []).append(owned)
    for (fid, star, branch), group in sorted(groups.items()):
        need = 3 ** (star - 1)
        if len(group) != 2 or session.pool.remaining.get(fid, 0) < need:
            continue
        if len(seat.bench) >= getattr(seat, 'bench_capacity', 8):
            break
        from arena_families import make_piece
        from shop import OwnedPiece
        for _ in range(need):
            session.pool.take(fid)
        piece = make_piece(fid, star, branch)
        # Ledger parity with bought copies (sell value follows the usual rule).
        gift = OwnedPiece(piece, piece.tier * need)
        gift.sources = [fid] * need
        seat.bench.append(gift)
        seat_state(seat)['fast_track'] += 1
        logs.append(f'速成培育补入{piece.name}（本局 {seat_state(seat)["fast_track"]}/{FAST_TRACK_LIMIT}）')
        if seat_state(seat)['fast_track'] >= FAST_TRACK_LIMIT:
            break
    return logs


# ------------------------------------------------------------------ draft
def draft_options(session, round_no):
    """Eight unit+item bundles drawn from the shared pool."""
    from arena_families import FAMILIES, RARE, make_piece
    rng = rng_mod.derive(session.seed, round_no, 'draft')
    if round_no < 9:
        tiers = (1, 2)
    elif round_no < 14:
        tiers = (2, 3)
    else:
        tiers = (3, 4)
    candidates = sorted(fid for fid, (cost, _) in FAMILIES.items()
                        if cost in tiers and session.pool.remaining.get(fid, 0) > 0
                        and (fid not in RARE or round_no >= 14))
    finished = sorted(set(items.catalog(RULESET)) - {'lucky_egg', 'evo_stone'})
    options = []
    picks = rng.sample(candidates, min(8, len(candidates)))
    for index, fid in enumerate(picks):
        if round_no < 9:
            reward = {'kind': 'component', 'key': rng.choice(items.COMPONENT_ORDER)}
        else:
            reward = {'kind': 'item', 'key': rng.choice(finished)}
        piece = make_piece(fid)
        options.append({'index': index, 'family': fid, 'species': piece.species_id,
                        'name': piece.name, 'cost': FAMILIES[fid][0], 'reward': reward,
                        'taken_by': None})
    return options


def open_draft(session):
    round_no = session.round_no
    if round_no not in DRAFT_ROUNDS:
        session.arena_draft = None
        return
    alive = [seat for seat in session.seats if seat.alive]
    order = [seat.seat for seat in sorted(alive, key=lambda s: (s.hp, s.seat))]
    options = draft_options(session, round_no)
    for option in options:
        session.pool.take(option['family'])
    session.arena_draft = {'round': round_no, 'options': options, 'order': order,
                           'status': 'pending'}
    _bots_pick(session, until_player=True)


def _bots_pick(session, until_player):
    draft = session.arena_draft
    for seat_no in draft['order']:
        if any(o['taken_by'] == seat_no for o in draft['options']):
            continue
        if seat_no == session.player.seat:
            if until_player:
                return
            continue
        seat = session.seats[seat_no]
        option = _bot_draft_choice(seat, [o for o in draft['options'] if o['taken_by'] is None])
        if option is not None:
            _grant_draft(session, seat, option)


def _bot_draft_choice(seat, options):
    if not options:
        return None
    from data import pokedex
    types = {t for owned in seat.board for t in owned.piece.types}

    def score(option):
        species_types = set(pokedex().species_record(option['species'])['types'])
        return (len(species_types & types), option['cost'], -option['index'])
    return max(options, key=score)


def _grant_draft(session, seat, option):
    from arena_families import make_piece
    from shop import OwnedPiece
    option['taken_by'] = seat.seat
    piece = make_piece(option['family'])
    owned = OwnedPiece(piece, option['cost'])
    capacity = getattr(seat, 'bench_capacity', 8)
    if len(seat.bench) < capacity:
        seat.bench.append(owned)
        if session.player is seat:
            session.ensure_unit_ids()
            seat_state(seat)['draft_uid'] = owned.uid
        unit_note = piece.name
    else:
        session.pool.put(option['family'])
        seat.gold += option['cost']
        unit_note = f'{piece.name}（备战席已满，折算 {option["cost"]} 金）'
    reward = option['reward']
    if reward['kind'] == 'component':
        seat.inventory.add_component(reward['key'])
        reward_name = items.COMPONENT_NAMES[reward['key']]
    else:
        seat.inventory.finished.append(reward['key'])
        reward_name = items.FINISHED[reward['key']]['name']
    return f'选秀获得 {unit_note} + {reward_name}'


def claim_draft(session, index):
    draft = getattr(session, 'arena_draft', None)
    if not draft or draft['status'] != 'pending' or draft['round'] != session.round_no:
        raise ValueError('当前没有进行中的选秀')
    option = next((o for o in draft['options'] if o['index'] == index), None)
    if option is None or option['taken_by'] is not None:
        raise ValueError('这个选秀选项已经被选走')
    message = _grant_draft(session, session.player, option)
    finish_draft(session)
    return message


def finish_draft(session):
    draft = getattr(session, 'arena_draft', None)
    if not draft or draft['status'] != 'pending':
        return None
    message = None
    if session.player.alive and not any(o['taken_by'] == session.player.seat
                                        for o in draft['options']):
        remaining = [o for o in draft['options'] if o['taken_by'] is None]
        if remaining:
            message = _grant_draft(session, session.player, remaining[0])
    _bots_pick(session, until_player=False)
    for option in draft['options']:
        if option['taken_by'] is None:
            session.pool.put(option['family'])
            option['taken_by'] = -1
    draft['status'] = 'done'
    _trim_bot_benches(session)
    return message


def player_draft_pending(session):
    draft = getattr(session, 'arena_draft', None)
    return bool(draft and draft['status'] == 'pending' and draft['round'] == session.round_no
                and session.player.alive)


# ------------------------------------------------------------------ round hooks
def on_augment_claimed(session, seat, key):
    if key == 'treasure_hunter':
        order = items.COMPONENT_ORDER
        base = (session.seed + seat.seat * 7 + session.round_no) % len(order)
        for offset in (0, 3):
            seat.inventory.add_component(order[(base + offset) % len(order)])


def begin_round(session):
    """Called after the generic arena begin_round for arena_v2 sessions."""
    for seat in session.seats:
        if not seat.alive:
            continue
        state = seat_state(seat)
        state['sims'] = 0
        state['targeted'] = 0
        state['draft_uid'] = None
        state['free_refreshes'] = 2 if has(seat, 'free_roll') else 0
        if seat.streak <= -LOSS_RELIEF_STREAK:
            state['free_refreshes'] += 1
        if seat is not session.player:
            fast_track(session, seat)
            session_combine_bot(session, seat)
            auto_mods(seat, prefer_first=False)
            bot_core(seat)
            _bot_items(seat)
    if session.player.alive:
        for line in fast_track(session, session.player):
            session._say(line)
        if any(True for _ in session.player.bench):
            logs = session.combine_player()
            for line in logs:
                session._say(line)
    open_draft(session)
    _trim_bot_benches(session)


def _trim_bot_benches(session):
    """Population-reducing augments and gifts must never leave a bot over capacity."""
    for seat in session.bots:
        if seat.alive and len(seat.bench) > getattr(seat, 'bench_capacity', 8):
            seat._sell_pass(session.round_no, rng_mod.derive(session.seed, session.round_no,
                                                             'bots', 9000 + seat.seat))


def session_combine_bot(session, seat):
    from shop import try_combine
    try_combine(seat.board, seat.bench, session.pool, session.templates, seat.inventory)


def _bot_items(seat):
    """Bots fill second slots (core / dual wield) from spare finished items."""
    for owned in seat.board:
        if (item_slots(owned, seat) < 2 or owned.item is None
                or getattr(owned, 'extra_item', None)):
            continue
        spare = [key for key in seat.inventory.finished if key not in ('lucky_egg', 'evo_stone')]
        if spare:
            owned.extra_item = spare[0]
            seat.inventory.finished.remove(spare[0])


def pve_bonus(session, seat):
    if has(seat, 'treasure_hunter'):
        order = items.COMPONENT_ORDER
        seat.inventory.add_component(order[(session.seed + session.round_no + seat.seat) % len(order)])
        return True
    return False


def owned_view_extras(owned, seat):
    return {'skill_mods': [arena_depth.mod_view(k) for k in (getattr(owned, 'skill_mods', None) or [])],
            'mod_options': pending_mod_options(owned),
            'is_core': bool(getattr(owned, 'is_core', False)),
            'extra_item': getattr(owned, 'extra_item', None),
            'extra_item_name': (items.FINISHED[owned.extra_item]['name']
                                if getattr(owned, 'extra_item', None) else None),
            'item_slots': item_slots(owned, seat)}


def copy_state(seat):
    return copy.deepcopy(seat_state(seat))
