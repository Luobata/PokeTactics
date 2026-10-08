"""Battle-local arena rain/sun, independent of classic weather and tactics.

A weather teaching machine requests once after a completed native action. All
requests from one tick contend together on the next tick; an opposing request
cancels both. Equal weather never refreshes a window, and old weather never
returns after replacement or expiry.
"""
import math

from arena_combinations import EPS, _effect
from items import FINISHED

WINDOW_SECONDS = 12.
WEATHER_TECHNIQUES = {'rain_dance': 'rain', 'sunny_day': 'sun'}


def init(battle):
    battle.arena_weather_name = None
    battle.arena_weather_until = 0.
    battle.arena_weather_started_at = 0.
    battle.arena_weather_source_idx = None
    battle._arena_weather_requests = []


def active(battle, t):
    if (not battle._arena_on or t + EPS >= getattr(battle, 'arena_weather_until', 0.)
            or t + EPS < getattr(battle, 'arena_weather_started_at', 0.)):
        return None
    return getattr(battle, 'arena_weather_name', None)


def damage_multiplier(battle, move, t):
    kind = active(battle, t)
    if move is None or kind is None or move['type'] not in ('WATER', 'FIRE'):
        return 1.
    stronger = 'WATER' if kind == 'rain' else 'FIRE'
    return 1.15 if move['type'] == stronger else .90


def has_rain_setter(battle, team):
    return any(unit.alive and unit.team == team and unit.technique == 'rain_dance'
               and not unit.technique_used for unit in battle.units) or any(
                   row['team'] == team and row['weather'] == 'rain'
                   for row in getattr(battle, '_arena_weather_requests', ()))


def after_native_cast(battle, unit, t, cast_index):
    if (not battle._arena_on or not unit.alive or unit.technique_used
            or unit.technique not in WEATHER_TECHNIQUES
            or type(cast_index) is not int or not 0 <= cast_index < len(battle.events)
            or battle.events[cast_index][1:3] != ('cast', unit.idx)
            or battle.events[cast_index][4] != 'arena_' + unit.ult_arch):
        return False
    from combat import TICK
    kind = WEATHER_TECHNIQUES[unit.technique]
    item = FINISHED.get(getattr(unit, 'item_key', None), {})
    extension = item.get('weather_extension', 0.) if item.get('weather_kind') == kind else 0.
    duration = WINDOW_SECONDS + extension
    effective_at = round((math.floor((t + EPS) / TICK) + 1) * TICK, 10)
    request = {'source_idx': unit.idx, 'team': unit.team, 'weather': kind,
               'duration': duration, 'effective_at': effective_at,
               'source_pos': unit.pos, 'cast_index': cast_index,
               'technique': unit.technique, 'item': getattr(unit, 'item_key', None)}
    unit.technique_used = True
    battle._arena_weather_requests.append(request)
    with _effect(battle, unit, unit, 'arena_weather', 'weather_request', t, cast_index,
                 amount=0, new_weather=kind, duration=duration, effective_at=effective_at,
                 weather_extension=extension, technique=unit.technique,
                 reason='first_completed_native_weather_tm'):
        battle._emit_state(unit, t)
    return True


def _source(battle, requests=None):
    if requests:
        chosen = min(requests, key=lambda row: (
            -row['duration'], battle._team_order.index(row['team']),
            battle.units[row['source_idx']].local_idx))
        return battle.units[chosen['source_idx']]
    idx = battle.arena_weather_source_idx
    return battle.units[idx] if idx is not None else battle.units[0]


def _change(battle, source, kind, at, duration, requests, reason):
    old_kind, old_until = battle.arena_weather_name, battle.arena_weather_until
    battle.arena_weather_name = kind
    battle.arena_weather_started_at = at
    battle.arena_weather_until = at + duration if kind else 0.
    battle.arena_weather_source_idx = source.idx if kind else None
    effect = 'expire' if reason == 'duration_elapsed' else 'weather'
    with _effect(battle, source, source, 'arena_weather', effect, at, amount=0,
                 old_weather=old_kind, new_weather=kind, duration=duration,
                 expires_at=battle.arena_weather_until, previous_expires_at=old_until,
                 requests=requests, reason=reason):
        for unit in battle.units:
            battle._emit_state(unit, at)
    # Keep weather-dependent action speed legible in the ordinary combo stream.
    from arena_traits import _spec
    for unit in battle.units:
        spec = _spec(battle, unit)
        if not spec or spec['id'] not in ('trait_swift_swim', 'trait_chlorophyll'):
            continue
        was, now = old_kind == spec['weather'], kind == spec['weather']
        if was == now:
            continue
        with _effect(battle, unit, unit, spec['id'], 'tempo' if now else 'expire', at,
                     amount=0, fraction=spec['fraction'] if now else 0.,
                     weather=kind, duration=duration if now else 0.,
                     expires_at=battle.arena_weather_until,
                     reason='matching_arena_weather' if now else 'arena_weather_ended'):
            battle._emit_state(unit, at)


def advance(battle, t):
    if not battle._arena_on:
        return []
    marker = len(battle.events)
    pending = battle._arena_weather_requests
    due = sorted({row['effective_at'] for row in pending if row['effective_at'] <= t + EPS})
    for at in due:
        if battle.arena_weather_name and battle.arena_weather_until <= at + EPS:
            _change(battle, _source(battle), None, battle.arena_weather_until, 0., [],
                    'duration_elapsed')
        requests = [row for row in pending if abs(row['effective_at'] - at) <= EPS]
        pending[:] = [row for row in pending if row not in requests]
        kinds = {row['weather'] for row in requests}
        source = _source(battle, requests)
        if len(kinds) > 1:
            _change(battle, source, None, at, 0., requests, 'simultaneous_rain_sun')
        else:
            kind = next(iter(kinds))
            if battle.arena_weather_name == kind:
                with _effect(battle, source, source, 'arena_weather', 'weather', at,
                             amount=0, old_weather=kind, new_weather=kind,
                             duration=max(0., battle.arena_weather_until - at),
                             expires_at=battle.arena_weather_until, requests=requests,
                             reason='same_weather_no_refresh'):
                    battle._emit_state(source, at)
            else:
                _change(battle, source, kind, at, max(row['duration'] for row in requests),
                        requests, 'weather_tm_resolved')
    if battle.arena_weather_name and battle.arena_weather_until <= t + EPS:
        _change(battle, _source(battle), None, battle.arena_weather_until, 0., [],
                'duration_elapsed')
    return battle.events[marker:]
