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
    'support': '攻击与特攻降低 20%；每 4 秒回复受伤最重的己方精灵 8% 最大生命，可被封疗克制。',
}
# Two representatives of each role at every price; evolved forms only.
ROSTER = {
    26: (1, 'attack'), 68: (1, 'attack'), 31: (1, 'defense'), 76: (1, 'defense'),
    40: (1, 'support'), 12: (1, 'support'),
    34: (2, 'attack'), 94: (2, 'attack'), 59: (2, 'defense'), 73: (2, 'defense'),
    36: (2, 'support'), 45: (2, 'support'),
    6: (3, 'attack'), 65: (3, 'attack'), 9: (3, 'defense'), 80: (3, 'defense'),
    3: (3, 'support'), 121: (3, 'support'),
}
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
}


def augment_view(key):
    if key not in AUGMENTS:
        raise ValueError('未知海克斯强化')
    return {'id': key, **copy.deepcopy(AUGMENTS[key])}


def build_templates():
    dex = pokedex()
    result = {}
    for sid, (cost, role) in ROSTER.items():
        move = dex.signature_move(sid)
        base = dex.species[sid]['base']
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


def begin_round(session):
    r = session.round_no
    if r in (1, 7, 13):
        for seat in session.seats:
            if not seat.alive:
                continue
            available = sorted(set(AUGMENTS) - set(_keys(seat)))
            rng = rng_mod.derive(session.seed, r, 'bots', 8000 + seat.seat)
            options = [augment_view(k) for k in rng.sample(available, 3)]
            if seat is session.player:
                session.arena_augments_pending = [{'id': f'augment-r{r}', 'round': r, 'options': options}]
            else:
                seat.arena_augments_selected.append(options[rng.randrange(3)])
    # One paid teaching per AI per round, after purchasing and deployment.
    for seat in session.bots:
        if not seat.alive or seat.gold < 2:
            continue
        for owned in seat.board:
            if owned.technique is not None:
                continue
            key = 'rest' if owned.piece.role_key != 'attack' else (
                'surf' if 'WATER' in owned.piece.types else 'cut' if techniques.compatible_species(owned.piece.species_id, 'cut') else 'rest')
            owned.technique = key
            seat.gold -= 2
            break


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


def learn(session, loc, key):
    catalog = {t['id']: t for t in technique_catalog()}
    if key not in catalog:
        raise ValueError('未知教学技能')
    owned, _, _ = session.locate(loc)
    techniques.validate_learning(owned.piece.species_id, key, ruleset=RULESET)
    if owned.technique == key:
        raise ValueError('已经学会这个技能')
    cost = catalog[key]['cost']
    if session.player.gold < cost:
        raise ValueError(f'学习需要 {cost} 金币')
    session.player.gold -= cost
    owned.technique = key
    return f'{owned.piece.name}学会{catalog[key]["name"]}（-{cost} 金币，替换不返还旧技能）'


def battle_options(session, a, b):
    options = {'ruleset': RULESET, 'stat_mode': 'budget_v1',
               'arena_teams': [_keys(seat) if seat is not None else [] for seat in (a, b)]}
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
        ranged = p.get('ranged', False) if isinstance(p, dict) else p.distance > 1
        rows = (0, 1) if role == 'defense' or role == 'attack' and not ranged else (1, 0)
        pos = next((r, c) for r in rows for c in (2, 3, 1, 4, 0, 5) if (r, c) not in occupied)
        occupied.add(pos)
        r, c = pos
        positions.append((c, r + 2) if team == 0 else (5 - c, 1 - r))
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
