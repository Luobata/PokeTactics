"""Versioned family shop. Species remain presentation/combat identities.

Only entrance species own stock; 1/3/9 sources pay for growth exactly once.
This module is deliberately separate from the frozen species_v1 shop.
"""
import copy
from data import pokedex
from roster import Piece, LEVEL_BY_TIER, RANGED, MELEE

VERSION = 'families_v2'
FIRST_VERSION = 'families_v1'
VERSIONS = (FIRST_VERSION, VERSION)
LEGACY_VERSION = 'species_v1'
# cost, supported routes. A route names real species, never invented forms.
FIRST_FAMILIES = {
    1: (2, ((1, 2, 3),)), 4: (2, ((4, 5, 6),)), 7: (2, ((7, 8, 9),)),
    10: (1, ((10, 11, 12),)), 29: (1, ((29, 30, 31),)),
    32: (2, ((32, 33, 34),)), 43: (2, ((43, 44, 45),)),
    58: (2, ((58, 59),)), 63: (3, ((63, 64, 65),)),
    66: (1, ((66, 67, 68),)), 72: (2, ((72, 73),)),
    74: (1, ((74, 75, 76),)), 79: (3, ((79, 80),)),
    90: (3, ((90, 91),)), 92: (2, ((92, 93, 94),)),
    95: (2, ((95, 208),)), 108: (1, ((108,),)),
    113: (2, ((113, 242),)), 114: (1, ((114,),)),
    116: (3, ((116, 117, 230),)), 120: (3, ((120, 121),)),
    122: (2, ((122,),)), 123: (3, ((123, 212),)),
    127: (2, ((127,),)), 128: (3, ((128,),)),
    129: (2, ((129, 130),)), 131: (3, ((131,),)),
    133: (2, ((133, 134), (133, 135), (133, 136), (133, 196), (133, 197))), 142: (3, ((142,),)),
    144: (4, ((144,),)), 145: (4, ((145,),)), 146: (4, ((146,),)),
    147: (3, ((147, 148, 149),)), 150: (5, ((150,),)), 151: (5, ((151,),)),
    152: (3, ((152, 153, 154),)), 155: (3, ((155, 156, 157),)),
    158: (3, ((158, 159, 160),)), 161: (1, ((161, 162),)),
    163: (1, ((163, 164),)), 170: (1, ((170, 171),)),
    172: (1, ((172, 25, 26),)), 173: (2, ((173, 35, 36),)),
    174: (1, ((174, 39, 40),)), 179: (2, ((179, 180, 181),)),
    194: (1, ((194, 195),)), 198: (2, ((198,),)),
    200: (2, ((200,),)), 211: (1, ((211,),)), 214: (2, ((214,),)),
    215: (2, ((215,),)), 227: (3, ((227,),)),
    236: (1, ((236, 106), (236, 237))), 238: (2, ((238, 124),)),
    239: (2, ((239, 125),)), 246: (3, ((246, 247, 248),)),
}
HOENN_FAMILIES = {
    252: (2, ((252, 253, 254),)), 255: (2, ((255, 256, 257),)),
    258: (2, ((258, 259, 260),)), 270: (1, ((270, 271, 272),)),
    280: (3, ((280, 281, 282),)), 285: (1, ((285, 286),)),
    304: (1, ((304, 305, 306),)), 333: (2, ((333, 334),)),
    349: (2, ((349, 350),)), 359: (3, ((359,),)),
    371: (3, ((371, 372, 373),)), 374: (3, ((374, 375, 376),)),
}
FAMILIES = {**FIRST_FAMILIES, **HOENN_FAMILIES}
SPECIES_FAMILY = {sid: fid for fid, (_, paths) in FAMILIES.items() for path in paths for sid in path}
RARE = frozenset(fid for fid, (cost, _) in FAMILIES.items() if cost >= 4)
# 3-cost stock grows from 10 to 18: two full cultivations can exist per family.
POOL_BY_COST = {1: 24, 2: 22, 3: 18, 4: 10, 5: 8}


def families_for(version=VERSION):
    if version not in VERSIONS:
        raise ValueError('未知家族卡池版本')
    return FIRST_FAMILIES if version == FIRST_VERSION else FAMILIES


def role_of(sid):
    import arena
    if sid >= 252:
        from arena_gen3 import ROLES
        return ROLES[sid]
    if sid in arena.ROSTER:
        return arena.ROSTER[sid][1]
    if sid in (129, 130):
        return 'attack'
    if sid in (133, 134, 135, 136):
        return 'defense' if sid == 134 else 'attack'
    fid = SPECIES_FAMILY[sid]
    route = next(p for p in FAMILIES[fid][1] if sid in p)
    return arena.ROSTER[route[-1]][1]


def mentor(sid):
    """Existing native kit to reuse for an earlier support stage."""
    fid = SPECIES_FAMILY[sid]
    return next(p[-1] for p in FAMILIES[fid][1] if sid in p)


def make_piece(fid, step=1, branch=None):
    if fid not in FAMILIES or type(step) is not int or step not in (1, 2, 3):
        raise ValueError('无效家族或培养档')
    cost, paths = FAMILIES[fid]
    if fid in RARE and step != 1:
        raise ValueError('稀有单位限一，不参与培养')
    path = paths[0] if branch is None else next((p for p in paths if p[-1] == branch), None)
    if path is None:
        raise ValueError('该家族不支持这条进化路线')
    sid = path[min(step - 1, len(path) - 1)]
    dex = pokedex(); base = dex.species_record(sid)['base']; role = role_of(sid)
    move = dex.signature_move(sid)
    piece = Piece(sid, cost, LEVEL_BY_TIER[cost], move_id=move and move['id'],
                  distance=RANGED if role == 'support' or base['special_attack'] > base['attack'] else MELEE)
    piece.family_id = fid
    piece.branch_id = None if step == 1 and len(paths) > 1 and branch is None else path[-1]
    piece.star, piece.growth_step, piece.shiny, piece.role_key = step, step, step == 3, role
    return piece


def build_templates(version=VERSION):
    result = {}
    for fid, (_, paths) in families_for(version).items():
        for path in paths:
            for step in range(1, 2 if fid in RARE else 4):
                piece = make_piece(fid, step, path[-1])
                result.setdefault(piece.species_id, piece)
        result[fid] = make_piece(fid)
    return result


def pool_caps(version=VERSION):
    entries = families_for(version)
    species = {sid for _, paths in entries.values() for path in paths for sid in path}
    return {sid: POOL_BY_COST[entries[sid][0]] if sid in entries else 0 for sid in species}


def source_id(piece):
    return getattr(piece, 'family_id', piece.species_id)


def rare_piece(piece):
    import arena
    return piece.family_id in RARE if hasattr(piece, 'family_id') else piece.species_id in arena.LEGENDARY


def route_view(piece):
    from arena_skills import skill_of
    fid = getattr(piece, 'family_id', None)
    if fid is None:
        return None
    cost, paths = FAMILIES[fid]
    return dict(id=fid, cost=cost, step=piece.star, copies=3 ** (piece.star - 1),
                rare=fid in RARE, branch=piece.branch_id,
                entrance=pokedex().species_record(fid)['name_zh'],
                routes=[dict(branch=p[-1], names=[pokedex().species_record(s)['name_zh'] for s in p],
                             species=list(p), role=role_of(p[-1]),
                             skill=skill_of(p[-1])['name'],
                             description=skill_of(p[-1])['description']) for p in paths])


def combine(board, bench, inventory=None, *, single=False, only_species=None):
    from shop import OwnedPiece
    import arena_traits, techniques
    logs = []
    while True:
        groups = {}
        for owned in board + bench:
            p = owned.piece
            if not hasattr(p, 'family_id') or p.family_id in RARE or p.star >= 3:
                continue
            if p.branch_id is None:
                continue  # Branches are a player decision; cancel keeps all materials.
            if only_species is not None and p.species_id != only_species:
                continue
            groups.setdefault((p.family_id, p.star, p.branch_id), []).append(owned)
        group = next((v[:3] for _, v in sorted(groups.items()) if len(v) >= 3), None)
        if group is None:
            return logs
        old = group[0].piece
        p = make_piece(old.family_id, old.star + 1, old.branch_id)
        merged = OwnedPiece(p, sum(o.invested for o in group))
        merged.uid = group[0].uid
        merged.sources = [s for o in group for s in o.sources]
        try:
            merged.arena_trait = arena_traits.validate_choice(p.species_id, group[0].arena_trait)
        except ValueError:
            merged.arena_trait = None
        for o in group:
            if o.item:
                if merged.item is None:
                    merged.item = o.item
                elif inventory is not None:
                    inventory.finished.append(o.item)
            if o.technique:
                if merged.technique is None and techniques.compatible_species(p.species_id, o.technique, 'arena_v1'):
                    merged.technique = o.technique
                elif inventory is not None:
                    inventory.techniques[o.technique] += 1
            (board if o in board else bench).remove(o)
        bench.append(merged)
        logs.append(f'{old.name}进化为{p.name}（培养 {p.star}/3）' if old.species_id != p.species_id
                    else f'{p.name}完成' + ('满培养' if p.star == 3 else '进阶培养'))
        if single:
            return logs


def choose_bot_branches(seat):
    """Prefer an existing branch, then a type matching the bot's current plan."""
    for fid, (_, paths) in FAMILIES.items():
        if len(paths) < 2:
            continue
        waiting = [o for o in seat.all_pieces() if getattr(o.piece, 'family_id', None) == fid
                   and o.piece.star == 1 and o.piece.branch_id is None]
        if len(waiting) < 3:
            continue
        invested = [o.piece.branch_id for o in seat.all_pieces()
                    if getattr(o.piece, 'family_id', None) == fid and o.piece.star == 2]
        branch = max(paths, key=lambda p: (invested.count(p[-1]),
                     len(set(pokedex().species_record(p[-1])['types']) & set(seat.target_types)), -p[-1]))[-1]
        for owned in waiting[:len(waiting) // 3 * 3]:
            owned.piece = copy.copy(owned.piece)
            owned.piece.branch_id = branch
