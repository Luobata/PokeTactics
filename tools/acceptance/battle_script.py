"""Browser battle script: one authoritative battle compiled for client rendering.

The script carries exactly what the Pillow renderer reads — the simulator's
event tuples, the shared ``AnimationTimeline`` schedule and the state snapshots
at their presentation times — as compact JSON. ``battle_renderer.js`` draws
from it at 60 fps; nothing here invents damage, movement or outcome.

Same-source contract (docs/58): both ends consume the same event stream, the
same timeline (start / release / impact / end per action) and the same
keyframe data. Presentation-only retiming happens downstream and never moves
an impact, so HP snapshots stay registered to the hits that cause them.
"""
from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path

SCRIPT_SCHEMA = 'poketactics.battle_script'
SCRIPT_VERSION = 1
SCRIPT_FILE = 'script.json'
SID_PATTERN = re.compile(r'^[\w-]{1,64}$')
_STATUS_ALIASES = {'para': 'paralysis', 'psn': 'poison', 'brn': 'burn', 'frz': 'freeze', 'slp': 'sleep'}
_FORCED_MOVES = ('knockback', 'pull', 'breach', 'swap', 'displace', 'push')


def json_safe(value, digits=3):
    """Tuples become lists, floats are rounded, unknown objects become text."""
    if isinstance(value, bool) or value is None or isinstance(value, (int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        rounded = round(value, digits)
        return int(rounded) if rounded == int(rounded) and abs(rounded) < 1e15 else rounded
    if isinstance(value, dict):
        return {str(k): json_safe(v, digits) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        items = sorted(value, key=repr) if isinstance(value, (set, frozenset)) else value
        return [json_safe(v, digits) for v in items]
    return str(value)


def _r(value):
    return round(float(value), 3)


def _skill_rows():
    import arena_skills
    return {'arena_' + row['id']: row for row in arena_skills.catalog(include_families=True)}


def _skill_meta(anim, move, rows):
    """Skill metadata for a cast move name (native arena kit, TM or classic move)."""
    if not isinstance(move, str):
        return None
    row = rows.get(move)
    if row is not None:
        return {'id': row['id'], 'move': move, 'name': row['name'], 'type': row['type'],
                'category': row.get('category'), 'arch': row.get('arch'),
                'tags': list(row.get('tags') or ()), 'power': row.get('power'),
                'targeting': row.get('targeting', 'enemy'), 'native': True,
                'behavior': row.get('behavior')}
    return {'id': move, 'move': move, 'name': anim.move_zh.get(move, move),
            'type': anim.move_type.get(move, 'NORMAL'), 'category': 'technique', 'arch': None,
            'tags': [], 'power': None, 'targeting': 'enemy', 'native': False, 'behavior': None}


def _unit_rows(anim, rows):
    import arena_skills
    try:
        from arena_traits import for_species
    except ImportError:  # pragma: no cover - classic checkouts
        for_species = None
    units = []
    deploy = {ev[2]: ev[3] for ev in anim.events if ev[1] == 'deploy'}
    for unit in sorted(anim.by_idx.values(), key=lambda u: u.idx):
        piece = unit.piece
        sid = piece.species_id
        shiny = bool(getattr(piece, 'shiny', False))
        try:
            native = arena_skills.skill_of(sid)
            skill = _skill_meta(anim, 'arena_' + native['id'], rows)
        except (ValueError, KeyError):
            skill = None
        trait = None
        if for_species is not None:
            try:
                row = for_species(sid, getattr(piece, 'arena_trait_key', None))
                trait = {'id': row['id'], 'name': row.get('name')} if row else None
            except (ValueError, KeyError, TypeError):
                trait = None
        item = getattr(unit, 'item_key', None)
        technique = getattr(unit, 'technique', None) or None
        pos = deploy.get(unit.idx, unit.pos)
        units.append({
            'idx': unit.idx, 'team': unit.team, 'sid': sid, 'name': piece.name,
            'star': int(getattr(piece, 'star', 1) or 1), 'tier': int(getattr(piece, 'tier', 1) or 1),
            'shiny': shiny, 'role': getattr(piece, 'role_key', 'attack') or 'attack',
            'types': list(getattr(piece, 'types', ()) or ()),
            'range': int(getattr(unit, 'range', getattr(piece, 'distance', 1)) or 1),
            'melee': int(getattr(unit, 'range', getattr(piece, 'distance', 1)) or 1) <= 1,
            'pos': list(pos), 'max_hp': int(unit.max_hp),
            'item': item, 'technique': technique,
            'technique_skill': _skill_meta(anim, technique, rows) if technique else None,
            'skill': skill, 'trait': trait,
            'sprite': f'/demo/sprite/{sid}.png' + ('?shiny=1' if shiny else ''),
        })
    return units


def _event_row(timeline, ev):
    """[t_presentation, t_simulation, kind, ...args] with JSON-safe arguments."""
    index = timeline.source_index_by_event.get(id(ev))
    sim_t = timeline.source_events[index][0] if index is not None else ev[0]
    return [_r(ev[0]), _r(sim_t), ev[1], *json_safe(list(ev[2:]))]


def build_script(anim, *, source=None, log_formatter=None, playback_meta=None):
    """Compile a BattleAnimation (arena) into the browser battle script dict."""
    timeline = anim.timeline
    rows = _skill_rows() if getattr(anim, 'is_arena', False) else {}
    units = _unit_rows(anim, rows)
    by_idx = {row['idx']: row for row in units}
    events = timeline.events
    source_index = timeline.source_index_by_event
    absorbed = getattr(anim, '_absorbed_by_source', {}) or {}
    terrain = getattr(anim, '_terrain_attack_sources', set()) or set()

    actions = []
    for ev in events:
        if ev[1] not in ('attack', 'cast'):
            continue
        timing = timeline.action_by_event.get(id(ev))
        if timing is None:
            continue
        index = timing.source_index
        requested = ev[6] if ev[1] == 'cast' else ev[4]
        requested = requested if isinstance(requested, (int, float)) else 0
        row = {
            'i': index, 'kind': ev[1], 'actor': timing.attacker, 'target': timing.target,
            'start': _r(timing.start), 'release': _r(timing.release),
            'impact': _r(timing.impact), 'end': _r(timing.recover_end),
            'secondary': bool(timing.secondary), 'terrain': index in terrain,
            'from': list(timing.source_pos), 'to': list(timing.target_pos),
            'requested': requested, 'damage': max(0, requested - absorbed.get(index, 0)),
            'sim_t': _r(ev[0] if index is None else timeline.source_events[index][0]),
        }
        if ev[1] == 'cast':
            row['move'] = ev[4]
            row['eff'] = json_safe(ev[5])
            row['skill'] = _skill_meta(anim, ev[4], rows)
            row['technique'] = ev[4] == by_idx.get(timing.attacker, {}).get('technique')
        actions.append(row)

    states = {row['idx']: [] for row in units}
    positions = {row['idx']: [[0.0, *row['pos'], 'deploy']] for row in units}
    statuses, open_status = [], {}
    weather, weather_now = [], getattr(anim, '_initial_weather_name', None)
    weather.append([0.0, weather_now])
    blink_by_event = getattr(timeline, 'blink_by_event', {})
    forced = {}
    for ev in events:
        if ev[1] in ('skill_effect', 'combo_effect', 'field_effect') and len(ev) >= 6 \
                and isinstance(ev[5], str) and any(word in ev[5] for word in _FORCED_MOVES):
            forced.setdefault(ev[3], set()).add(_r(ev[0]))
    for ev in events:
        t, kind = _r(ev[0]), ev[1]
        if kind == 'unit_state' and ev[2] in states:
            shield = ev[5] if len(ev) > 5 and isinstance(ev[5], (int, float)) else 0
            row = [t, int(ev[3]), int(ev[4]), int(shield)]
            if not states[ev[2]] or states[ev[2]][-1][1:] != row[1:]:
                states[ev[2]].append(row)
            payload = ev[7] if len(ev) > 7 and isinstance(ev[7], dict) else {}
            index = source_index.get(id(ev))
            sim_t = timeline.source_events[index][0] if index is not None else ev[0]
            wet_until = payload.get('wet_until') or 0
            if isinstance(wet_until, (int, float)) and wet_until > sim_t + 1e-6:
                statuses.append({'unit': ev[2], 'kind': 'wet', 'start': t,
                                 'end': _r(t + wet_until - sim_t), 'source': 'state'})
            if 'arena_weather' in payload and payload.get('arena_weather') != weather_now:
                weather_now = payload.get('arena_weather')
                weather.append([t, weather_now])
        elif kind in ('deploy', 'move') and ev[2] in positions:
            how = ('deploy' if kind == 'deploy' else
                   'blink' if id(ev) in blink_by_event else
                   'forced' if t in forced.get(ev[2], ()) else 'walk')
            entry = [t, *json_safe(ev[3]), how]
            if how == 'blink':
                blink = blink_by_event[id(ev)]
                entry.append({'start': _r(blink['start']), 'departure': _r(blink['departure']),
                              'landing': _r(blink['landing'])})
            if kind == 'deploy':
                positions[ev[2]] = [entry]
            else:
                positions[ev[2]].append(entry)
        elif kind == 'status' and len(ev) >= 5:
            name = _STATUS_ALIASES.get(ev[3], ev[3])
            key = (ev[2], name)
            if ev[4] == 'apply':
                if key not in open_status:
                    open_status[key] = {'unit': ev[2], 'kind': name, 'start': t, 'end': None,
                                        'source': 'status'}
                    statuses.append(open_status[key])
            elif ev[4] == 'expire' and key in open_status:
                open_status.pop(key)['end'] = t
        elif kind in ('skill_effect', 'combo_effect', 'field_effect') and len(ev) == 7 \
                and isinstance(ev[6], dict):
            payload = ev[6]
            expires = payload.get('expires_at')
            index = source_index.get(id(ev))
            sim_t = timeline.source_events[index][0] if index is not None else ev[0]
            sub = ev[5] if isinstance(ev[5], str) else 'effect'
            if sub == 'expire':
                for row in statuses:
                    if row['unit'] == ev[3] and row.get('effect') == ev[4] and (
                            row['end'] is None or row['end'] > t):
                        row['end'] = t
            elif isinstance(expires, (int, float)) and expires > sim_t + 1e-6 and sub not in (
                    'damage', 'side_hit', 'heal', 'regen', 'energy', 'absorb', 'status'):
                # 'status' packets announce a debuff whose own status events
                # already open/close the interval; never double count them.
                name = ev[4] if sub in ('apply', 'effect', 'place') and isinstance(ev[4], str) else sub
                statuses.append({'unit': ev[3], 'kind': name, 'start': t,
                                 'end': _r(t + expires - sim_t), 'source': ev[1], 'effect': ev[4]})
        elif kind == 'tactical_effect' and len(ev) == 6 and isinstance(ev[5], dict):
            if ev[4] in ('weather_start', 'weather_end'):
                name = ev[5].get('weather') if ev[4] == 'weather_start' else None
                if name != weather_now:
                    weather_now = name
                    weather.append([t, name])
    duration = _r(timeline.duration)
    for row in statuses:
        if row['end'] is None:
            row['end'] = duration
    # Repeated snapshots of one ongoing state (wet, refreshed buffs) merge into
    # a single interval so the client draws one continuous badge.
    merged = []
    for row in sorted(statuses, key=lambda r: (r['unit'], r['kind'], r['start'])):
        last = merged[-1] if merged else None
        if last and last['unit'] == row['unit'] and last['kind'] == row['kind'] \
                and row['start'] <= last['end'] + 1e-6:
            last['end'] = max(last['end'], row['end'])
        else:
            merged.append(dict(row))
    statuses = sorted(merged, key=lambda r: (r['start'], r['unit'], r['kind']))
    deaths = [[_r(ev[0]), ev[2]] for ev in events if ev[1] == 'die']
    log = []
    if log_formatter is not None:
        for ev in anim.presentation_events:
            if ev[1] in ('unit_state',):
                continue
            try:
                text = log_formatter(anim, ev)
            except Exception:  # noqa: BLE001 — a log line must never break the script
                continue
            if text:
                log.append({'t': _r(ev[0]), 'text': re.sub(r'<[^>]+>', '', str(text))})
    end = next((ev for ev in events if ev[1] == 'end'), None)
    script = {
        'schema': SCRIPT_SCHEMA, 'version': SCRIPT_VERSION,
        'source': json_safe(source or {}),
        'clock': {'grid': 0.05, 'duration': duration,
                  'result_time': _r(timeline.result_time) if timeline.result_time is not None else None,
                  'frame_dt': 0.05, 'frames': int(round(duration / 0.05)) + 1},
        'arena': {'cols': 6, 'rows': int(getattr(anim, 'battle_rows', 6)),
                  'team_rows': {'0': [3, 4, 5], '1': [0, 1, 2]},
                  'ruleset': 'arena_v1' if getattr(anim, 'is_arena', False) else 'classic',
                  'weather': getattr(anim, '_initial_weather_name', None)},
        'units': units,
        'actions': actions,
        'cutins': [[_r(a), _r(b), i] for a, b, i in getattr(timeline, 'cutin_windows', ())],
        'states': {str(k): v for k, v in states.items()},
        'positions': {str(k): v for k, v in positions.items()},
        'statuses': statuses,
        'weather': weather,
        'deaths': deaths,
        'events': [_event_row(timeline, ev) for ev in events],
        'log': log,
        'result': {'winner': json_safe(end[2]) if end else None,
                   't': _r(end[0]) if end else duration},
    }
    if playback_meta is not None:
        script['playback_meta'] = json_safe(playback_meta)
    return script


def write_script(path: Path, script: dict) -> None:
    """Atomic publish; a reader never sees a half-written script."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(script, ensure_ascii=False, separators=(',', ':')))
    os.replace(temporary, path)


def read_script(path: Path):
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get('schema') != SCRIPT_SCHEMA \
            or data.get('version') != SCRIPT_VERSION:
        return None
    return data


def validate_script(script) -> list:
    """Structural checks used by tests and the endpoint (returns problems)."""
    problems = []
    if not isinstance(script, dict):
        return ['script must be an object']
    if script.get('schema') != SCRIPT_SCHEMA or script.get('version') != SCRIPT_VERSION:
        problems.append('schema/version mismatch')
    units = script.get('units')
    if not isinstance(units, list) or not units:
        problems.append('units missing')
        return problems
    known = {row.get('idx') for row in units}
    for row in units:
        for key in ('idx', 'team', 'sid', 'name', 'max_hp', 'pos', 'sprite', 'role', 'range'):
            if key not in row:
                problems.append(f'unit {row.get("idx")} missing {key}')
    duration = script.get('clock', {}).get('duration', 0)
    for action in script.get('actions', []):
        if action.get('actor') not in known or action.get('target') not in known:
            problems.append(f'action {action.get("i")} references unknown unit')
        if not (action['start'] <= action['release'] <= action['impact'] <= action['end'] <= duration + 1e-6):
            problems.append(f'action {action.get("i")} timing out of order')
    previous = -1
    for row in script.get('events', []):
        if not isinstance(row, list) or len(row) < 3 or row[0] < previous - 1e-9:
            problems.append('events must be ordered [t, sim_t, kind, ...] rows')
            break
        previous = row[0]
    return problems


# ---------------------------------------------------------------- 端点辅助
def session_script(demo, sid, round_no):
    """Load (or deterministically regenerate) the script of a committed round.

    Returns (status, payload). The side file lives with the round's frames:
    .build/demo/<sid>/r<round>/script.json. When it is missing but this
    server still holds the round's battle parameters, the same seeded battle is
    re-run (no frames drawn) and the file is rewritten identically.
    """
    if not isinstance(sid, str) or not SID_PATTERN.match(sid) or type(round_no) is not int \
            or not 1 <= round_no <= 999:
        return 400, {'ok': False, 'error': '无效的对局或轮次'}
    directory = demo.ROOT / '.build' / 'demo' / sid / f'r{round_no}'
    path = directory / SCRIPT_FILE
    script = read_script(path)
    if script is None:
        key = (sid, round_no)
        with demo._RENDER_LOCK:
            params = demo._RENDER_PARAMS.get(key)
            params = dict(params) if params else None
        if params is None:
            return 404, {'ok': False, 'error': '这一轮的战斗脚本不在本机（可改用 ?renderer=png 或查看战果）'}
        with demo._LOCK:
            demo._prepare_battle_frames(
                params['comp_a'], params['comp_b'],
                demo.rng_mod.derive(params['seed'], round_no, 'battle', params['battle_i']),
                params['weather_name'], params['out_dir'],
                positions_a=params['positions_a'], hud_snapshot=params['hud_snapshot'],
                **params['battle_options'])
        script = read_script(path)
        if script is None:
            return 500, {'ok': False, 'error': '战斗脚本生成失败'}
    script['source'] = {**(script.get('source') or {}), 'kind': 'session', 'sid': sid,
                        'round': round_no}
    return 200, script


def preview_script(species, kind='attack', scene='dummy', seed=7):
    """Isolated action fixture (same generator as the editor/lab)."""
    from arena_preview_scene import make_preview_scene
    import demo
    anim = make_preview_scene(species, kind, seed, scene=scene)
    return build_script(anim, source={'kind': 'preview', 'species': species, 'action': kind,
                                      'scene': scene, 'seed': seed},
                        log_formatter=demo._fmt_event)


def scenario_script(key, seed=7):
    """Full arena scenario from the shared scenario library."""
    from arena_scenarios import make_scene
    import demo
    anim = make_scene(seed, key)
    return build_script(anim, source={'kind': 'scenario', 'scenario': key, 'seed': seed},
                        log_formatter=demo._fmt_event)
