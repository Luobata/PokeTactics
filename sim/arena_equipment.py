"""Arena equipment reacts to settled actions, never recursively to its products.

All healing, energy and shields use the ordinary ledgers. Counters are battle
local; only successful gains consume a use. Classic rules remain neutral.
"""
from arena_combinations import EPS, _effect, _ready, _used, grant_shield
from data import ENERGY_MAX
from items import FINISHED
import status

CRAFT_ORDER = ('relay_coil', 'dew_charm', 'storm_chime', 'torrent_orb',
               'drain_fang', 'pulse_band', 'tide_shell', 'grounding_cloak',
               'damp_rock', 'heat_rock', 'life_orb')


def carrier_rank(owned, key):
    """Visible owned-piece suitability, with no opponent or future information."""
    if key not in CRAFT_ORDER:
        return None
    from arena_skills import skill_of
    piece = owned.piece
    sid, role = piece.species_id, getattr(piece, 'role_key', 'attack')
    if key in ('damp_rock', 'heat_rock'):
        return 3 if getattr(owned, 'technique', None) == (
            'rain_dance' if key == 'damp_rock' else 'sunny_day') else None
    if key == 'life_orb':
        return 4 if sid == 34 else 2 if role == 'attack' else None
    if key == 'relay_coil':
        return 3 if sid in (121, 171, 164) else None
    if key == 'dew_charm':
        return 3 if sid in (3, 12, 40, 45, 108, 113, 154, 242) else None
    if key == 'storm_chime':
        return (3 if sid in (9, 68, 106, 128, 142, 160, 208, 248) else
                1 if getattr(owned, 'technique', None) == 'roar' else None)
    if key == 'torrent_orb':
        skill = skill_of(sid)
        return 3 if skill['targeting'] == 'enemy' and skill['power'] > 0 else None
    if key == 'tide_shell':
        return 3 if role == 'defense' else None
    if key == 'drain_fang':
        return 3 if role == 'attack' else 2 if role == 'defense' else None
    if key == 'pulse_band':
        return 3 if role == 'attack' else None
    return 2 if role == 'support' else 1


def _equipped(battle, unit, key):
    return (battle._arena_on and unit is not None and unit.alive
            and getattr(unit, 'item_key', None) == key)


def _available(unit, key, t):
    spec = FINISHED[key]
    return _ready(unit, key, t, spec['cooldown'], spec['limit'])


def _native(battle, unit, cast_index):
    return (type(cast_index) is int and 0 <= cast_index < len(battle.events)
            and battle.events[cast_index][1:3] == ('cast', unit.idx)
            and battle.events[cast_index][4] == 'arena_' + unit.ult_arch)


def _energy(battle, source, recipient, key, t, cast_index=None, **details):
    requested = FINISHED[key]['energy_amount']
    gained = min(requested, max(0, ENERGY_MAX - recipient.energy))
    if not recipient.alive or gained <= 0:
        return False
    with _effect(battle, source, recipient, key, 'energy', t, cast_index,
                 amount=gained, requested=requested, **details):
        recipient.energy += gained
        _used(source, key, t, FINISHED[key]['cooldown'])
        battle._emit_state(recipient, t)
    return True


def _heal(battle, source, recipient, key, requested, t, cast_index=None, **details):
    actual = battle._healing_amount(recipient, requested, t)[0]
    if actual <= 0:
        return False
    with _effect(battle, source, recipient, key, 'heal', t, cast_index,
                 amount=actual, requested=requested, **details):
        battle._heal(recipient, requested, t, source=source)
        _used(source, key, t, FINISHED[key]['cooldown'])
    return True


def after_basic(battle, unit, target, t, action_index, actual_hp):
    if not battle._arena_on or not unit.alive or unit.team == target.team or actual_hp <= 0:
        return False
    key = getattr(unit, 'item_key', None)
    if key == 'drain_fang' and _available(unit, key, t):
        spec = FINISHED[key]
        amount = min(max(1, int(actual_hp * spec['fraction'])),
                     int(unit.max_hp * spec['heal_cap']))
        return _heal(battle, unit, unit, key, amount, t,
                     action_index=action_index, origin_idx=target.idx,
                     reason='actual_basic_lifesteal')
    if key == 'pulse_band':
        spec = FINISHED[key]
        if unit.combo_uses.get(key, 0) >= spec['limit']:
            return False
        unit.pulse_hits = min(spec['hits'], getattr(unit, 'pulse_hits', 0) + 1)
        if unit.pulse_hits >= spec['hits'] and _available(unit, key, t):
            if _energy(battle, unit, unit, key, t, action_index=action_index,
                       actual_hits=unit.pulse_hits, reason='three_actual_basics'):
                unit.pulse_hits = 0
                return True
    return False


def after_native_hit(battle, unit, target, t, cast_index, actual_hp):
    key = 'torrent_orb'
    if (not _equipped(battle, unit, key) or not _native(battle, unit, cast_index)
            or unit.team == target.team or actual_hp <= 0 or not _available(unit, key, t)):
        return False
    return _energy(battle, unit, unit, key, t, cast_index,
                   origin_idx=target.idx, reason='native_primary_actual_hp')


def after_native_heal(battle, unit, patient, actual, t, cast_index):
    key = 'dew_charm'
    spec = FINISHED[key]
    if (not _equipped(battle, unit, key) or not _native(battle, unit, cast_index)
            or not patient.alive or patient is unit or unit.team != patient.team
            or actual <= 0 or actual + EPS < patient.max_hp * spec['heal_threshold']
            or not _available(unit, key, t)):
        return False
    candidates = [friend for friend in battle.units
                  if friend is not unit and friend is not patient and friend.alive
                  and friend.team == unit.team and friend.hp < friend.max_hp
                  and abs(friend.pos[0] - patient.pos[0]) + abs(friend.pos[1] - patient.pos[1]) <= 2
                  and battle._healing_amount(friend, int(friend.max_hp * spec['heal_fraction']), t)[0] > 0]
    recipient = min(candidates, key=lambda friend: (
        friend.hp / friend.max_hp, battle._target_key(patient, friend)), default=None)
    if recipient is None:
        return False
    return _heal(battle, unit, recipient, key, int(recipient.max_hp * spec['heal_fraction']),
                 t, cast_index, origin_idx=patient.idx, reason='native_healing_relay')


def after_native_energy(battle, unit, patient, actual, t, cast_index):
    key = 'relay_coil'
    if (not _equipped(battle, unit, key) or not _native(battle, unit, cast_index)
            or patient is unit or unit.team != patient.team or not patient.alive
            or actual <= 0 or not _available(unit, key, t)):
        return False
    gained = grant_shield(battle, unit, patient,
                          int(patient.max_hp * FINISHED[key]['shield_fraction']), t, cast_index,
                          source_kind='item', source_key=key, reason='native_energy_protection')
    if gained:
        _used(unit, key, t, FINISHED[key]['cooldown'])
    return gained


def after_knockback(battle, source, target, t, cast_index, action_index):
    if (not battle._arena_on or source is None or not target.alive
            or source.team == target.team):
        return False
    triggered = False
    key = 'tide_shell'
    if _equipped(battle, target, key) and _available(target, key, t):
        triggered = grant_shield(battle, target, target,
                                int(target.max_hp * FINISHED[key]['shield_fraction']), t, None,
                                source_kind='item', source_key=key,
                                action_index=action_index, origin_idx=source.idx,
                                reason='survived_hostile_displacement')
        if triggered:
            _used(target, key, t, FINISHED[key]['cooldown'])
    key = 'storm_chime'
    if _equipped(battle, source, key) and _available(source, key, t):
        candidates = [friend for friend in battle.units
                      if friend.alive and friend.team == source.team and friend is not source
                      and friend.energy < ENERGY_MAX
                      and abs(friend.pos[0] - source.pos[0]) + abs(friend.pos[1] - source.pos[1]) <= 2]
        recipient = min(candidates, key=lambda friend: (
            friend.energy, battle._target_key(source, friend)), default=None)
        if recipient is not None:
            triggered = _energy(battle, source, recipient, key, t, cast_index,
                                action_index=action_index, origin_idx=target.idx,
                                reason='successful_hostile_knockback') or triggered
    return triggered


def after_debuff(battle, source, target, kind, t):
    key = 'grounding_cloak'
    if (not _equipped(battle, target, key) or kind not in ('sleep', 'para', 'freeze')
            or not _available(target, key, t)
            or getattr(getattr(target, '_st', None), 'debuff', None) != kind):
        return False
    with _effect(battle, target, target, key, 'cleanse', t, amount=0, status_kind=kind,
                 origin_idx=source.idx if source is not None else None,
                 reason='first_applied_major_control'):
        removed = status.cleanse(battle, target, t, kinds={kind})
        if removed:
            _used(target, key, t, FINISHED[key]['cooldown'])
    return removed
