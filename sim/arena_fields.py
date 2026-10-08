"""Finite arena terrain and control. Movement, not elapsed time, triggers rocks."""
from contextlib import contextmanager

EPS = 1e-9


@contextmanager
def _effect(battle, source, target, key, effect, t, cast_index=None, **details):
    payload = {'cast_index': cast_index, 'event_count': 0,
               'source_pos': source.pos, 'target_pos': target.pos, 'cells': [], **details}
    index = len(battle.events)
    battle.events.append((t, 'field_effect', source.idx, target.idx, key, effect, payload))
    yield payload
    payload['event_count'] = len(battle.events) - index - 1


def _fields(battle):
    if not hasattr(battle, 'rock_fields'):
        battle.rock_fields = []
        battle._next_field_id = 0
    return battle.rock_fields


def _remove(battle, field, cells, t, effect='expire', unit=None, cast_index=None, reason='duration'):
    removed = [cell for cell in field['cells'] if cell in cells]
    if not removed:
        return 0
    source = unit or battle.units[field['source']]
    with _effect(battle, source, source, 'rock_spikes', effect, t, cast_index,
                 field_id=field['id'], cells=removed, removed=removed,
                 cleared_count=len(removed) if effect == 'clear' else 0, reason=reason):
        field['cells'] = [cell for cell in field['cells'] if cell not in removed]
        battle._emit_state(source, t)
    if not field['cells']:
        _fields(battle).remove(field)
    return len(removed)


def expire(battle, t):
    if not battle._arena_on:
        return
    for field in list(_fields(battle)):
        if t + EPS >= field['expires_at']:
            _remove(battle, field, list(field['cells']), t)
    for target in battle.units:
        for key, attr in (('root', 'root_until'), ('vulnerability', 'vulnerable_until')):
            until = getattr(target, attr, 0.)
            if until and t + EPS >= until:
                source = battle.units[getattr(target, key + '_source', target.idx)]
                with _effect(battle, source, target, key, 'expire', t,
                             expires_at=until):
                    setattr(target, attr, 0.)
                    battle._emit_state(target, t)


def place_rocks(battle, unit, target, t, cast_index=None):
    if not battle._arena_on or not unit.alive:
        return None
    expire(battle, t)
    dx, dy = target.pos[0] - unit.pos[0], target.pos[1] - unit.pos[1]
    # The rear tile matches the knockback direction; the side tile is stable
    # in local coordinates so rotating/swapping teams rotates the same setup.
    directions = ((0, 1 if dy > 0 else -1), (1 if unit.team == 0 else -1, 0)) if abs(dy) >= abs(dx) else (
        (1 if dx > 0 else -1, 0), (0, -1 if unit.team == 0 else 1))
    cells = [target.pos] + [(target.pos[0] + x, target.pos[1] + y) for x, y in directions]
    cells = list(dict.fromkeys(cell for cell in cells
                              if 0 <= cell[0] < battle.cols and 0 <= cell[1] < battle.rows))[:3]
    previous = [field for field in _fields(battle) if field['team'] == unit.team]
    refreshed = [cell for cell in cells if any(cell in field['cells'] for field in previous)]
    # Replacing the team's footprint preserves the three-cell cap. A refresh
    # creates no hit, and the global victim cap survives every replacement.
    for field in previous:
        _remove(battle, field, list(field['cells']), t, cast_index=cast_index, reason='refresh')
    battle._next_field_id += 1
    field = {'id': battle._next_field_id, 'team': unit.team, 'source': unit.idx,
             'cells': cells, 'expires_at': t + 6., 'hits': {},
             'damage_multiplier': 1.25 if getattr(unit, 'item_key', None) == 'trap_lens' else 1.}
    with _effect(battle, unit, target, 'rock_spikes', 'place', t, cast_index,
                 field_id=field['id'], cells=list(cells), expires_at=field['expires_at'],
                 damage_multiplier=field['damage_multiplier'], refreshed_cells=refreshed):
        _fields(battle).append(field)
        battle._emit_state(unit, t)
    return field


def move_unit(battle, target, destination, t, cast_index=None, source=None, reason='move'):
    if (not target.alive or destination == target.pos
            or not 0 <= destination[0] < battle.cols or not 0 <= destination[1] < battle.rows
            or any(other.alive and other is not target and other.pos == destination for other in battle.units)):
        return False
    if battle._arena_on:
        expire(battle, t)
        if reason == 'move' and getattr(target, 'root_until', 0) > t + EPS:
            return False
    origin, action_index = target.pos, len(battle.events)
    target.pos = destination
    battle.events.append((t, 'move', target.idx, destination))
    if not battle._arena_on:
        return True
    # At most one hostile field owns a tile: the team footprint never stacks.
    for field in list(_fields(battle)):
        if not target.alive or field['team'] == target.team or destination not in field['cells']:
            continue
        caster = battle.units[field['source']]
        avoided = ('heavy_boots' if getattr(target, 'item_key', None) == 'heavy_boots' else
                   'cooldown' if t + EPS < getattr(target, 'rock_ready_at', 0.) else
                   'field_limit' if field['hits'].get(target.idx, 0) >= 2 else
                   'battle_limit' if getattr(target, 'rock_hits', 0) >= 4 else None)
        if avoided:
            with _effect(battle, caster, target, 'rock_spikes', 'avoid', t, cast_index,
                         field_id=field['id'], cell=destination, cells=[destination], reason=avoided):
                battle._emit_state(target, t)
            continue
        target.rock_hits = getattr(target, 'rock_hits', 0) + 1
        target.rock_ready_at = t + 1.
        field['hits'][target.idx] = field['hits'].get(target.idx, 0) + 1
        multiplier = min(2., battle.dex.multiplier('ROCK', target.piece.types))
        requested = max(0, int(target.max_hp * min(.12, .06 * multiplier * field['damage_multiplier'])))
        absorbed_before = target.shield_absorbed
        with _effect(battle, caster, target, 'rock_spikes', 'enter', t, cast_index,
                     field_id=field['id'], cell=destination, cells=[destination],
                     requested=requested, absorbed=0, actual=0,
                     trigger_count=target.rock_hits) as payload:
            # No primary flag: terrain never grants energy, applies statuses,
            # triggers teaching/native combinations or recursively moves units.
            payload['actual'] = battle._land_hit(caster, target, requested, t, direct=False)
            payload['absorbed'] = target.shield_absorbed - absorbed_before
    if reason == 'knockback':
        from arena_combinations import after_knockback
        after_knockback(battle, source, target, origin, t, cast_index, action_index)
        from arena_equipment import after_knockback as equipment_after_knockback
        equipment_after_knockback(battle, source, target, t, cast_index, action_index)
    return True


def apply_root(battle, unit, target, t, cast_index=None):
    if not battle._arena_on or not unit.alive or not target.alive:
        return False
    uses = getattr(unit, 'root_uses', 0)
    if uses >= 3:
        return False
    unit.root_uses = uses + 1
    until = max(getattr(target, 'root_until', 0.), t + 1.5)
    with _effect(battle, unit, target, 'root', 'apply', t, cast_index,
                 duration=1.5, expires_at=until):
        target.root_until, target.root_source = until, unit.idx
        battle._emit_state(target, t)
    return True


def apply_vulnerability(battle, unit, target, t, cast_index=None):
    if not battle._arena_on or not unit.alive or not target.alive:
        return False
    with _effect(battle, unit, target, 'vulnerability', 'apply', t, cast_index,
                 fraction=.12, duration=4., expires_at=t + 4.):
        target.vulnerable_until, target.vulnerability_source = t + 4., unit.idx
        battle._emit_state(target, t)
    return True


def clear_near(battle, unit, t, cast_index=None, limit=3):
    if not battle._arena_on or not unit.alive or limit <= 0:
        return 0
    expire(battle, t)
    total = 0
    for field in list(_fields(battle)):
        if field['team'] == unit.team:
            continue
        cells = sorted((cell for cell in field['cells']
                        if abs(cell[0] - unit.pos[0]) + abs(cell[1] - unit.pos[1]) <= 1),
                       key=lambda cell: battle._local_pos(cell, unit.team))[:limit - total]
        total += _remove(battle, field, cells, t, 'clear', unit, cast_index, 'clearing_skill')
        if total >= limit:
            break
    return total
