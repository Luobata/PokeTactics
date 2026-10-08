"""Single-slot water priming with competing electric/grass support payoffs.

Only typed native or TM primary hits enter this module. Side hits, DOT, terrain
and the reaction's own energy/healing never produce or consume another mark.
"""
from arena_combinations import EPS, _effect, _ready, _used
from data import ENERGY_MAX
from arena_weather import active

COOLDOWN = 4.
LIMIT = 3
REACTION_COUNTER = 'element_reaction'


def clear(patient):
    patient.wet_until = 0.
    patient.wet_source_idx = None
    patient.wet_cast_index = None


def _expire(battle, patient, t, reason='duration_elapsed'):
    if patient.wet_source_idx is None:
        return False
    source = battle.units[patient.wet_source_idx]
    until, cast_index = patient.wet_until, patient.wet_cast_index
    clear(patient)
    with _effect(battle, source, patient, 'element_wet', 'expire', t, cast_index,
                 amount=0, duration=0., expires_at=until, reason=reason):
        battle._emit_state(patient, t)
    return True


def expire(battle, t):
    if not battle._arena_on:
        return
    for patient in battle.units:
        if patient.wet_source_idx is not None and t + EPS >= patient.wet_until:
            _expire(battle, patient, t)


def after_primary(battle, unit, patient, move, actual_hp, t, action_index):
    if (not battle._arena_on or move is None or actual_hp <= 0
            or not unit.alive or not patient.alive or unit.team == patient.team
            or type(action_index) is not int or not 0 <= action_index < len(battle.events)
            or battle.events[action_index][1:4] != ('cast', unit.idx, patient.idx)
            or battle.events[action_index][4] != move['name']):
        return False
    kind = move['type']
    if kind == 'WATER':
        duration = 6. if active(battle, t) == 'rain' else 4.
        with _effect(battle, unit, patient, 'element_wet', 'wet', t, action_index,
                     amount=0, duration=duration, expires_at=t + duration,
                     wet_source_idx=unit.idx, action_index=action_index,
                     reason='actual_water_primary_hp'):
            patient.wet_source_idx, patient.wet_until = unit.idx, t + duration
            patient.wet_cast_index = action_index
            battle._emit_state(patient, t)
        return True
    if kind not in ('ELECTRIC', 'GRASS') or patient.wet_source_idx is None:
        return False
    if t + EPS >= patient.wet_until:
        _expire(battle, patient, t)
        return False
    source = battle.units[patient.wet_source_idx]
    if (source is unit or not source.alive or source.team != unit.team
            or not _ready(unit, REACTION_COUNTER, t, COOLDOWN, LIMIT)):
        return False
    if kind == 'ELECTRIC':
        gained = min(8, max(0, ENERGY_MAX - source.energy))
        if gained <= 0:
            return False
        key, recipient, amount, requested = 'element_conduct', source, gained, 8
    else:
        candidates = [friend for friend in battle.units if friend.alive
                      and friend.team == unit.team
                      and abs(friend.pos[0] - unit.pos[0]) + abs(friend.pos[1] - unit.pos[1]) <= 2
                      and battle._healing_amount(friend, int(friend.max_hp * .06), t)[0] > 0]
        recipient = min(candidates, key=lambda friend: (
            friend.hp / friend.max_hp, battle._target_key(unit, friend)), default=None)
        if recipient is None:
            return False
        key, requested = 'element_bloom', int(recipient.max_hp * .06)
        amount = battle._healing_amount(recipient, requested, t)[0]
    wet_until, wet_cast = patient.wet_until, patient.wet_cast_index
    with _effect(battle, unit, recipient, key, 'energy' if kind == 'ELECTRIC' else 'heal',
                 t, action_index, amount=amount, requested=requested,
                 origin_idx=patient.idx, origin_pos=patient.pos,
                 wet_source_idx=source.idx, wet_cast_index=wet_cast,
                 wet_expires_at=wet_until, action_index=action_index,
                 consumed_wet=True, cooldown=COOLDOWN, limit=LIMIT,
                 reason='other_electric_primary_on_wet' if kind == 'ELECTRIC'
                        else 'other_grass_primary_on_wet'):
        clear(patient)
        battle._emit_state(patient, t)
        if kind == 'ELECTRIC':
            recipient.energy += amount
            battle._emit_state(recipient, t)
        else:
            battle._heal(recipient, requested, t, source=unit)
        _used(unit, REACTION_COUNTER, t, COOLDOWN)
    return True
