"""arena_v2 stage weather (气候): a per-round forecast that shapes every battle.

Each round of an arena_v2 game has a forecast weather (rounds 1-2 are calm).
Some rounds turn into a second weather mid-battle. The prep screen shows this
round and the next two, so players can plan around them, and once per round a
seat may pay to swap its own battle to the forecast's alternative weather.

Weathers boost their element types and add one visible mechanic each (chip
damage, lightning, photosynthesis, freezing, gusts, ...). Rain dance / sunny day
teaching machines still temporarily override the current weather (arena_weather);
when they expire the stage weather returns.

Everything is deterministic: forecasts derive from the seed, battle effects use
no RNG draws. arena_v1 never sees any of this (golden fingerprints unchanged).
"""
from arena_effects import EPS
from data import ENERGY_MAX

SHIFT_AT = 15.
SWAP_COST = 2
CALM_ROUNDS = 2

# name, glyph, boosted types (+dmg), weakened types (-dmg), short rule lines
CLIMATES = {
    'calm': {'name': '平静', 'glyph': '◌', 'boost': (), 'weak': (),
             'lines': ('没有天气效果。',)},
    'sun': {'name': '烈日', 'glyph': '☀', 'boost': ('FIRE', 'GRASS'), 'weak': ('WATER',),
            'lines': ('火、草系造成伤害 +10%，水系 -8%；火系招式 +15%。',
                      '光合：每 5 秒，草系宝可梦获得 15 能量。',
                      '叶绿素特性加速生效。')},
    'rain': {'name': '暴雨', 'glyph': '☂', 'boost': ('WATER', 'ELECTRIC'), 'weak': ('FIRE',),
             'lines': ('水、电系造成伤害 +10%，火系 -8%；水系招式 +15%。',
                       '雨润：每 5 秒，水系宝可梦回复 3% 最大生命。',
                       '湿润持续更久；悠游自如、雨盘特性生效。')},
    'sand': {'name': '沙暴', 'glyph': '≋', 'boost': ('ROCK', 'GROUND', 'STEEL'), 'weak': (),
             'lines': ('岩、地、钢系造成伤害 +10%，受到伤害 -12%。',
                       '风沙：每 2 秒，其他宝可梦损失 1% 最大生命。')},
    'snow': {'name': '暴雪', 'glyph': '❄', 'boost': ('ICE',), 'weak': (),
             'lines': ('冰系造成伤害 +15%。',
                       '严寒：每 2 秒，非冰系宝可梦损失 0.8% 最大生命。',
                       '冰系每第 4 次有效普攻冻结目标（同一目标 5 秒一次）。')},
    'storm': {'name': '雷暴', 'glyph': 'ϟ', 'boost': ('ELECTRIC',), 'weak': (),
              'lines': ('电系造成伤害 +15%。',
                        '落雷：每 5 秒轮流劈向一方能量最高的宝可梦，造成 6% 最大生命伤害并麻痹；'
                        '电系被劈中则吸收为 25 能量。')},
    'fog': {'name': '浓雾', 'glyph': '☁', 'boost': ('GHOST', 'DARK'), 'weak': (),
            'lines': ('幽灵、恶系造成伤害 +15%。',
                      '视线受阻：射程 3 以上的宝可梦开战时射程 -1。')},
    'gale': {'name': '狂风', 'glyph': '➶', 'boost': ('FLYING', 'DRAGON'), 'weak': (),
             'lines': ('飞行、龙系造成伤害 +10%，飞行系攻速 +15%。',
                       '顺风：所有击退额外推开 1 格。')},
    'aurora': {'name': '极光', 'glyph': '✺', 'boost': ('PSYCHIC', 'FAIRY'), 'weak': (),
               'lines': ('超能力、妖精系造成伤害 +12%。',
                         '星辉：任何宝可梦施放本命后返还 10 能量。')},
}
ROTATION = ('sun', 'rain', 'sand', 'snow', 'storm', 'fog', 'gale', 'aurora')
BOOST = {'sun': 1.10, 'rain': 1.10, 'sand': 1.10, 'snow': 1.15, 'storm': 1.15, 'fog': 1.15,
         'gale': 1.10, 'aurora': 1.12}
WEAK = .92
TYPE_ZH = {'FIRE': '火', 'GRASS': '草', 'WATER': '水', 'ELECTRIC': '电', 'ROCK': '岩', 'GROUND': '地',
           'STEEL': '钢', 'ICE': '冰', 'GHOST': '幽灵', 'DARK': '恶', 'FLYING': '飞行', 'DRAGON': '龙',
           'PSYCHIC': '超能力', 'FAIRY': '妖精'}


# ------------------------------------------------------------------ forecast
def forecast(seed, round_no):
    """{'id', 'shift': None | {'id', 'at'}, 'alt'} for one round (pure function of the seed)."""
    if round_no <= CALM_ROUNDS:
        return {'id': 'calm', 'shift': None, 'alt': 'sun' if round_no == CALM_ROUNDS else 'calm'}
    import rng as rng_mod
    stage = (round_no - 1) // len(ROTATION)
    order = list(ROTATION)
    rng_mod.derive(seed, stage, 'climate').shuffle(order)
    key = order[round_no % len(order)]
    roll = rng_mod.derive(seed, round_no, 'climate', 1)
    others = [k for k in ROTATION if k != key]
    alt = others[roll.randrange(len(others))]
    shift = None
    if round_no >= 6 and roll.random() < .3:
        target = [k for k in others if k != alt]
        shift = {'id': target[roll.randrange(len(target))], 'at': SHIFT_AT}
    return {'id': key, 'shift': shift, 'alt': alt}


def schedule_for(seed, round_no, swapped=False):
    """Battle schedule ``((key, at), ...)``; a swapped seat fights in the alternative, no shift."""
    row = forecast(seed, round_no)
    if swapped and row['alt'] != 'calm':
        return ((row['alt'], 0.),)
    out = ((row['id'], 0.),)
    if row['shift']:
        out += ((row['shift']['id'], row['shift']['at']),)
    return out


def climate_view(key):
    spec = CLIMATES[key]
    return {'id': key, 'name': spec['name'], 'glyph': spec['glyph'], 'lines': list(spec['lines']),
            'boost': [TYPE_ZH.get(t, t) for t in spec['boost']], 'weak': [TYPE_ZH.get(t, t) for t in spec['weak']],
            'boost_types': list(spec['boost']), 'weak_types': list(spec['weak'])}


def forecast_view(seed, round_no, swapped=False, ahead=2):
    rows = []
    for n in range(round_no, round_no + ahead + 1):
        row = forecast(seed, n)
        mine = swapped and n == round_no and row['alt'] != 'calm'
        rows.append({'round': n, **climate_view(row['alt'] if mine else row['id']),
                     'shift': None if mine or not row['shift'] else
                     {**climate_view(row['shift']['id']), 'at': row['shift']['at']},
                     'alt': climate_view(row['alt']), 'swapped': mine})
    return rows


def validate_schedule(schedule):
    if (not isinstance(schedule, (list, tuple)) or not 1 <= len(schedule) <= 3
            or any(not isinstance(row, (list, tuple)) or len(row) != 2 or row[0] not in CLIMATES
                   or not isinstance(row[1], (int, float)) for row in schedule)
            or schedule[0][1] != 0 or list(schedule) != sorted(schedule, key=lambda r: r[1])):
        raise ValueError('invalid arena climate schedule')
    return tuple((key, float(at)) for key, at in schedule)


# ------------------------------------------------------------------ battle
def climate_at(battle, t):
    schedule = getattr(battle, 'arena_climate', None)
    if not schedule:
        return None
    key = schedule[0][0]
    for name, at in schedule:
        if at <= t + EPS:
            key = name
    return None if key == 'calm' else key


def current(battle, t):
    """Effective weather: a teaching-machine window if active, else the stage weather."""
    from arena_weather import active
    return active(battle, t)


def _goggles(unit):
    from arena_depth import has_item
    return has_item(unit, 'safety_goggles')


def _types(unit):
    return getattr(unit.piece, 'types', ()) or ()


def damage_factors(battle, attacker, target, t):
    """(team, source, key, factor) rows for arena_depth.damage_multiplier."""
    kind = current(battle, t)
    if kind is None or kind not in CLIMATES:
        return []
    spec = CLIMATES[kind]
    out = []
    if set(_types(attacker)) & set(spec['boost']):
        out.append((attacker.team, 'weather', kind, BOOST[kind]))
        if _goggles(attacker):
            out.append((attacker.team, 'item', 'safety_goggles', 1.10))
    elif set(_types(attacker)) & set(spec['weak']):
        out.append((attacker.team, 'weather', kind, WEAK))
    if kind == 'sand' and set(_types(target)) & set(spec['boost']):
        out.append((target.team, 'weather', kind, .88))
    return out


def setup(battle):
    """Battle-start adjustments (range, speed) and the per-tick weather driver."""
    battle.weather_track = []
    battle._climate_last = 'unset'
    battle._climate_next = {}
    battle._climate_counts = {}
    battle._climate_bolt = 0
    if not getattr(battle, 'arena_climate', None):
        return
    battle.fx.subscribe('tick', _tick)
    battle.fx.subscribe('basic_settled', _basic)
    battle.fx.subscribe('knockback', _knock)
    battle.fx.subscribe('native_cast', _cast)
    kinds = {key for key, _at in battle.arena_climate}
    if 'fog' in kinds or 'gale' in kinds:
        battle._climate_base = {u.idx: (u.range, u.attack_interval) for u in battle.units}


def _apply_start_mods(battle, kind, t):
    """Range/speed adjustments follow the current weather (applied and reverted on change)."""
    base = getattr(battle, '_climate_base', None)
    if not base:
        return
    for unit in battle.units:
        rng, interval = base[unit.idx]
        unit.range = rng - 1 if kind == 'fog' and rng >= 3 else rng
        unit.attack_interval = interval / 1.15 if kind == 'gale' and 'FLYING' in _types(unit) else interval


def _emit(battle, unit, target, key, t, label, kind='buff', value=0, team=None, **payload):
    team = unit.team if team is None else team
    battle.events.append((t, 'effect', unit.idx if unit is not None else -1, target.idx if target is not None else -1,
                          'climate_' + key, {'source': 'weather', 'team': team, 'kind': kind, 'label': label,
                                             'value': int(value), **payload}))
    battle.fx.ledger.add(team, 'weather', key, triggers=1,
                         **({kind: value} if kind in ('damage', 'heal', 'shield', 'energy') else {}))


def _every(battle, key, t, period):
    due = battle._climate_next.get(key)
    if due is None:
        battle._climate_next[key] = t + period
        return False
    if t + EPS < due:
        return False
    battle._climate_next[key] = due + period
    return True


def _tick(battle, t, **_):
    kind = current(battle, t)
    if kind != battle._climate_last:
        previous = battle._climate_last
        battle._climate_last = kind
        battle.weather_track.append([round(t, 4), kind])
        _apply_start_mods(battle, kind, t)
        battle._climate_next = {}
        if previous != 'unset':
            for unit in battle.units:
                if unit.alive:
                    battle._emit_state(unit, t)
            anchor = next((u for u in battle.units if u.alive), battle.units[0])
            label = '天气转为' + CLIMATES[kind or 'calm']['name']
            for team in (0, 1):
                _emit(battle, anchor, anchor, kind or 'calm', t, label, kind='buff', team=team,
                      camera='focus' if team == 0 else None, weather=kind)
    if kind is None:
        return
    alive = [u for u in battle.units if u.alive]
    if kind == 'sun' and _every(battle, 'sun', t, 5.):
        for unit in alive:
            if 'GRASS' in _types(unit):
                gained = max(0, min(15, ENERGY_MAX - unit.energy))
                unit.energy += gained
                if gained:
                    battle._emit_state(unit, t)
                    _emit(battle, unit, unit, 'sun', t, '光合', kind='energy', value=gained)
    elif kind == 'rain' and _every(battle, 'rain', t, 5.):
        for unit in alive:
            if 'WATER' in _types(unit) and unit.hp < unit.max_hp:
                healed = battle._heal(unit, max(1, int(unit.max_hp * .03)), t, source=unit)
                if healed:
                    _emit(battle, unit, unit, 'rain', t, '雨润', kind='heal', value=healed)
    elif kind in ('sand', 'snow') and _every(battle, kind, t, 2.):
        immune = set(CLIMATES[kind]['boost'])
        fraction = .01 if kind == 'sand' else .008
        for unit in alive:
            if set(_types(unit)) & immune or _goggles(unit):
                continue
            dealt = battle._land_hit(unit, unit, max(1, int(unit.max_hp * fraction)), t, direct=False)
            if dealt:
                battle.fx.ledger.add(1 - unit.team, 'weather', kind, triggers=1, damage=dealt)
    elif kind == 'storm' and _every(battle, 'storm', t, 5.):
        _lightning(battle, t)


def _lightning(battle, t):
    team = battle._climate_bolt % 2
    battle._climate_bolt += 1
    victims = [u for u in battle.units if u.alive and u.team == team and not _goggles(u)]
    if not victims:
        return
    victim = max(victims, key=lambda u: (u.energy, -u.local_idx))
    if 'ELECTRIC' in _types(victim):
        gained = max(0, min(25, ENERGY_MAX - victim.energy))
        victim.energy += gained
        battle._emit_state(victim, t)
        _emit(battle, victim, victim, 'storm', t, '避雷', kind='energy', value=gained, bolt=True, camera='focus')
        return
    dealt = battle._land_hit(victim, victim, max(1, int(victim.max_hp * .06)), t, direct=False)
    import status
    status.apply_debuff(battle, victim, 'para', t, source=victim)  # weather has no unit; never None
    _emit(battle, victim, victim, 'storm', t, '落雷', kind='damage', value=dealt, team=1 - victim.team,
          bolt=True, camera='focus')


def _basic(battle, unit, target, t, actual_hp, **_):
    if current(battle, t) != 'snow' or actual_hp <= 0 or not target.alive or 'ICE' not in _types(unit):
        return
    counts = battle._climate_counts
    counts[unit.idx] = counts.get(unit.idx, 0) + 1
    if counts[unit.idx] % 4:
        return
    ready = battle._climate_next.setdefault('freeze', {})
    if ready.get(target.idx, 0.) > t + EPS:
        return
    import status
    if status.apply_debuff(battle, target, 'freeze', t, source=unit):
        ready[target.idx] = t + 5.
        _emit(battle, unit, target, 'snow', t, '冻结', kind='debuff')


def _knock(battle, source, target, t, cast_index=None, **_):
    if current(battle, t) != 'gale' or source is None or not target.alive or battle._climate_next.get('gust_busy'):
        return
    destination = battle._knock_cell(target, source.pos)
    if destination is None:
        return
    from arena_fields import move_unit
    battle._climate_next['gust_busy'] = True
    try:
        if move_unit(battle, target, destination, t, cast_index, source=source, reason='knockback'):
            _emit(battle, source, target, 'gale', t, '顺风', kind='move')
    finally:
        battle._climate_next['gust_busy'] = False


def _cast(battle, unit, t, **_):
    if current(battle, t) != 'aurora' or not unit.alive:
        return
    gained = max(0, min(10, ENERGY_MAX - unit.energy))
    if gained:
        unit.energy += gained
        battle._emit_state(unit, t)
        _emit(battle, unit, unit, 'aurora', t, '星辉', kind='energy', value=gained)


# ------------------------------------------------------------------ bots / advisor
def favoured(key, types):
    spec = CLIMATES.get(key or 'calm', CLIMATES['calm'])
    return bool(set(types) & set(spec['boost'])), bool(set(types) & set(spec['weak']))


def swap_preview(seed, round_no):
    """What a swap buys this round: from (main [+ shift]) to the alternative."""
    row = forecast(seed, round_no)
    return {'from': climate_view(row['id']), 'to': climate_view(row['alt']), 'cost': SWAP_COST,
            'available': row['alt'] != 'calm' and row['alt'] != row['id']}
