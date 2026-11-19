"""arena_v2 item synergy: resonance tags, awakened items and dual-wield combos.

Three layers make items build around each other instead of adding numbers:

* Resonance (共鸣): every obtainable item carries one or two mechanic tags. When a
  team's deployed units carry 2 / 4 items of the same tag, a team-wide rule turns
  on (statuses spread, knockbacks shake neighbours, casts feed allies, ...).
* Awakening (觉醒): from round ``AWAKEN_ROUND`` a mechanic item plus one of its own
  recipe components becomes ``<key>_plus``: the same item with one extra clause.
  At most ``AWAKEN_LIMIT`` per seat per game. Awakened items count as their base
  item everywhere (``arena_depth.has_item``) and keep its tags and base stats.
* Dual-wield (双持): a unit with two item slots (core unit / dual-wield augment)
  holding a listed pair gains a combo clause.

All effects are deterministic (no RNG draws) and report through the effect bus
ledger, sources ``resonance`` and ``item``.
"""
from arena_effects import EffectSpec, fire

AWAKEN_ROUND = 12
AWAKEN_LIMIT = 2

# ------------------------------------------------------------------ tags
TAG_NAMES = {'status': '异常', 'impact': '冲击', 'arcane': '奥术', 'guard': '守护', 'strike': '连击'}
TAG_ORDER = ('status', 'impact', 'arcane', 'guard', 'strike')
ITEM_TAGS = {
    # mechanic items and treasures
    'flame_orb': ('status',), 'toxic_orb': ('status',), 'static_glove': ('status', 'strike'),
    'impact_gauntlet': ('impact',), 'red_card': ('impact', 'guard'), 'boomerang': ('strike',),
    'echo_bell': ('arcane',), 'taunt_bell': ('guard',), 'weakness_policy': ('strike',),
    'reaper_scale': ('strike',), 'revival_seed': ('guard',), 'rally_whistle': ('arcane',),
    # depth items
    'mind_crystal': ('arcane',), 'quick_claw': ('arcane',), 'escape_pack': ('impact', 'guard'),
    'blast_core': ('guard',),
    # classic arena items still obtainable in v2
    'contagion_orb': ('status',), 'healing_needle': ('status',), 'storm_chime': ('impact', 'arcane'),
    'tide_shell': ('impact', 'guard'), 'trap_lens': ('impact',), 'heavy_boots': ('impact',),
    'torrent_orb': ('arcane',), 'pulse_band': ('arcane', 'strike'), 'relay_coil': ('arcane',),
    'sash': ('guard',), 'leftovers': ('guard',), 'ward_bracer': ('guard',), 'grounding_cloak': ('guard',),
    'heart_bell': ('guard',), 'clarity_charm': ('guard',), 'dew_charm': ('guard',),
    'metronome': ('strike',), 'drain_fang': ('strike',), 'life_orb': ('strike',),
    'damp_rock': ('arcane',), 'heat_rock': ('arcane',),
}
THRESHOLDS = (2, 4)
RESONANCES = {
    'status': ('异常共鸣', ('我方施加异常时，施加者获得 8 能量（每名单位 2 秒一次）。',
                         '带灼伤 / 中毒 / 麻痹的敌人倒下时，异常传染给 2 格内最近的无异常敌人。')),
    'impact': ('冲击共鸣', ('我方击退敌人时，被击退者受到击退者攻击 35% 的冲击伤害，落点相邻的其他敌人受到一半。',
                         '被我方击退的敌人眩晕 0.8 秒（同一目标 4 秒一次）。')),
    'arcane': ('奥术共鸣', ('我方施放本命后，2 格内能量最低的另一名队友获得 10 能量（全队 1.5 秒一次）。',
                         '奥术装备持有者每场第一次施放本命后返还 30 能量。')),
    'guard': ('守护共鸣', ('开战时，守护装备持有者为相邻最脆弱的队友提供自身最大生命 12% 的护盾。',
                        '守护装备持有者首次降到 50% 生命时，嘲讽 2 格内敌人 2 秒并获得 15% 护盾。')),
    'strike': ('连击共鸣', ('连击装备持有者每第 5 次有效普攻追打一次 40% 伤害。',
                         '我方击倒敌人后，击倒者 2 格内的队友 2 秒攻速 +20%。')),
}


def resonance_id(tag, tier):
    return f'res_{tag}_{THRESHOLDS[tier - 1]}'


def base_key(key):
    return key[:-5] if key and key.endswith('_plus') and key[:-5] in AWAKEN else key


def item_tags(key):
    return ITEM_TAGS.get(base_key(key), ())


def tag_counts(keys):
    counts = dict.fromkeys(TAG_ORDER, 0)
    for key in keys:
        for tag in item_tags(key):
            counts[tag] += 1
    return counts


def active_resonances(keys):
    """{tag: tier} for every tag that reaches a threshold (tier 1 = 2 items, 2 = 4 items)."""
    counts = tag_counts(keys)
    return {tag: sum(counts[tag] >= n for n in THRESHOLDS) for tag in TAG_ORDER
            if counts[tag] >= THRESHOLDS[0]}


def resonance_view(keys, candidates=()):
    """Progress rows for the UI; ``candidates`` are items the player could still add."""
    counts = tag_counts(keys)
    rows = []
    for tag in TAG_ORDER:
        name, texts = RESONANCES[tag]
        n = counts[tag]
        nxt = next((t for t in THRESHOLDS if t > n), None)
        rows.append({'tag': tag, 'tag_name': TAG_NAMES[tag], 'name': name, 'count': n,
                     'tier': sum(n >= t for t in THRESHOLDS), 'next': nxt,
                     'tiers': [{'n': t, 'text': text, 'active': n >= t} for t, text in zip(THRESHOLDS, texts)],
                     'helpers': sorted({k for k in candidates if tag in item_tags(k)})})
    return rows


# ------------------------------------------------------------------ awakening
AWAKEN = {
    'boomerang': '弹射后再弹一次：从第一名弹射目标跳到 2 格内另一名敌人，造成 35% 伤害。',
    'impact_gauntlet': '每第 2 次有效普攻就击退；目标无处可退时改为眩晕 0.8 秒（同一目标 4 秒一次）。',
    'echo_bell': '回响扩散：再对主目标 2 格内另一名敌人追加一次 45% 回响。',
    'flame_orb': '余烬：普攻命中已灼伤的目标时，对其相邻敌人造成本次伤害 30%，并点燃其中无异常者（1.5 秒一次）。',
    'toxic_orb': '毒性外溢：普攻命中已中毒的目标时，使其 1 格内一名无异常敌人中毒（2 秒一次）。',
    'static_glove': '每第 3 次有效普攻就麻痹；麻痹成功时电弧跳到 2 格内另一名敌人并使其麻痹。',
    'taunt_bell': '再挑衅：首次降到 50% 生命时，再次嘲讽 2 格内敌人 2.5 秒并获得 20% 最大生命护盾。',
    'red_card': '每场可推开 4 次；被推开的攻击者损失 25 能量。',
}


def awakened_key(key):
    return key + '_plus'


def _awakened_specs():
    from arena_mech_items import MECH_ITEMS
    out = {}
    for key, clause in AWAKEN.items():
        base = MECH_ITEMS[key]
        out[awakened_key(key)] = {
            'name': base['name'] + '·觉醒', 'pairs': (), 'awakened': True, 'base': key,
            'arena_only': True, 'depth_only': True,
            'description': base['description'] + ' 【觉醒】' + clause}
    return out


AWAKENED_ITEMS = _awakened_specs()


def awaken_components(key):
    """Components that can awaken ``key`` (any component of any of its recipes)."""
    from arena_mech_items import MECH_ITEMS
    if key not in AWAKEN:
        return ()
    return tuple(dict.fromkeys(c for pair in MECH_ITEMS[key]['pairs'] for c in pair))


# ------------------------------------------------------------------ dual wield
DUOS = {
    'duo_corrosion': (('flame_orb', 'toxic_orb'), '腐蚀爆燃',
                      '普攻命中带灼伤或中毒的目标时，额外造成其最大生命 3% 的伤害（1 秒一次）。'),
    'duo_conductor': (('boomerang', 'static_glove'), '导电回旋',
                      '普攻命中麻痹目标时，电弧跳到 2 格内最近的另一名敌人，造成 35% 伤害并使其麻痹（3 秒一次）。'),
    'duo_bulldozer': (('impact_gauntlet', 'red_card'), '推土机',
                      '携带者造成的击退再多推 1 格，并造成目标最大生命 5% 的伤害。'),
    'duo_circuit': (('echo_bell', 'mind_crystal'), '共振回路',
                    '本命主命中造成伤害后返还 10 能量（1 秒一次）。'),
    'duo_first_strike': (('rally_whistle', 'quick_claw'), '先声夺人',
                         '开战时 2 格内所有队友 4 秒攻速 +25%。'),
}


def duo_for(keys):
    bases = {base_key(k) for k in keys if k}
    return [duo for duo, (pair, _n, _t) in DUOS.items() if set(pair) <= bases]


def duo_partners(key):
    """[(partner_key, duo_id)] for the advisor."""
    base = base_key(key)
    return [(pair[1] if pair[0] == base else pair[0], duo) for duo, (pair, _n, _t) in DUOS.items()
            if base in pair]


# ------------------------------------------------------------------ battle helpers
def _d():
    import arena_depth
    return arena_depth


def is_awakened(unit, key):
    return awakened_key(key) in _d()._items(unit)


def unit_has_duo(unit, duo):
    return duo in duo_for(_d()._items(unit))


def stun(battle, unit, t, dur):
    """Short hard stun that respects and opens the control diminishing window."""
    import status
    st = getattr(unit, '_st', None)
    if not status.STATUS_ON or st is None or not unit.alive or t + 1e-9 < st.ctrl_until:
        return False
    until = t + dur
    if st.stun_until + 1e-9 >= until:
        return False
    st.stun_until = until
    st.flinch_until = max(st.flinch_until, until)
    st.ctrl_until = t + status.DR_WINDOW
    battle.events.append((t, 'status', unit.idx, status.FLINCH_KIND, 'apply', 0))
    return True


def _debuff_of(unit):
    return getattr(getattr(unit, '_st', None), 'debuff', None)


def _enemies_near(battle, unit, anchor, radius, exclude=()):
    d = _d()
    return sorted((v for v in battle.units if v.alive and v.team != unit.team and v not in exclude
                   and d._dist(v, anchor) <= radius), key=lambda v: (d._dist(v, anchor), v.local_idx))


def _per_target_ready(inst, target, t, cooldown):
    ready = inst.state.setdefault('ready', {})
    if ready.get(target.idx, 0.) > t + 1e-9:
        return False
    ready[target.idx] = t + cooldown
    return True


def _haste(unit, t, dur, fraction):
    unit.haste_until, unit.haste_fraction = t + dur, max(unit.haste_fraction, fraction)


def _taunt_around(battle, unit, t, dur, radius=2):
    taunted = 0
    for enemy in _enemies_near(battle, unit, unit, radius):
        enemy.taunt_source_idx, enemy.taunt_until = unit.idx, t + dur
        enemy.target_idx = unit.idx
        taunted += 1
    return taunted


# -------------------------------------------------- awakened clauses (own specs)
def _h_flame_plus(battle, inst, unit, target, t, actual_hp, **_):
    if unit is not inst.unit or actual_hp <= 0 or _debuff_of(target) != 'burn':
        return
    import status
    d = _d()
    hit = 0
    for victim in _enemies_near(battle, unit, target, 1, exclude=(target,)):
        if d._indirect_damage(battle, unit, victim, actual_hp * .3, t):
            hit += 1
        if victim.alive and _debuff_of(victim) is None:
            status.apply_debuff(battle, victim, 'burn', t, source=unit)
    if hit:
        fire(battle, inst, target, t, label='余烬', kind='damage', value=hit)


def _h_toxic_plus(battle, inst, unit, target, t, actual_hp, **_):
    if unit is not inst.unit or actual_hp <= 0 or _debuff_of(target) != 'poison':
        return
    import status
    for victim in _enemies_near(battle, unit, target, 1, exclude=(target,)):
        if _debuff_of(victim) is None and status.apply_debuff(battle, victim, 'poison', t, source=unit):
            fire(battle, inst, victim, t, label='毒性外溢', kind='debuff')
            return


def _h_taunt_plus(battle, inst, source, target, actual_hp, t, **_):
    unit = inst.unit
    if target is not unit or not unit.alive or actual_hp <= 0 or unit.hp > unit.max_hp * .5:
        return
    taunted = _taunt_around(battle, unit, t, 2.5)
    _d()._shield(battle, unit, unit, unit.max_hp * .2, t, 'taunt_bell_plus')
    battle._emit_state(unit, t)
    fire(battle, inst, unit, t, label='再挑衅', kind='buff', value=taunted, camera='focus')


# -------------------------------------------------------------- duo clauses
def _h_duo_corrosion(battle, inst, unit, target, t, actual_hp, **_):
    if unit is not inst.unit or actual_hp <= 0 or not target.alive or _debuff_of(target) not in ('burn', 'poison'):
        return
    dealt = _d()._indirect_damage(battle, unit, target, target.max_hp * .03, t)
    if dealt:
        fire(battle, inst, target, t, label='腐蚀爆燃', kind='damage', value=dealt)


def _h_duo_conductor(battle, inst, unit, target, t, actual_hp, **_):
    if unit is not inst.unit or actual_hp <= 0 or _debuff_of(target) != 'para':
        return
    others = _enemies_near(battle, unit, target, 2, exclude=(target,))
    if not others:
        return
    import status
    victim = others[0]
    dealt = _d()._indirect_damage(battle, unit, victim, actual_hp * .35, t)
    if victim.alive and _debuff_of(victim) is None:
        status.apply_debuff(battle, victim, 'para', t, source=unit)
    fire(battle, inst, victim, t, label='导电回旋', kind='damage', value=dealt)


def _h_duo_bulldozer(battle, inst, source, target, t, cast_index=None, action_index=None, **_):
    unit = inst.unit
    if source is not unit or not target.alive or target.team == unit.team or inst.state.get('busy'):
        return
    destination = battle._knock_cell(target, unit.pos)
    from arena_fields import move_unit
    inst.state['busy'] = True
    try:
        if destination is not None:
            move_unit(battle, target, destination, t, cast_index, source=unit, reason='knockback')
        dealt = _d()._indirect_damage(battle, unit, target, target.max_hp * .05, t)
    finally:
        inst.state['busy'] = False
    fire(battle, inst, target, t, label='推土机', kind='damage', value=dealt)


def _h_duo_circuit(battle, inst, unit, target, t, lost_hp, **_):
    if unit is not inst.unit or not unit.alive or lost_hp <= 0:
        return
    gained = _d()._energy(battle, unit, 10)
    if gained:
        fire(battle, inst, unit, t, label='共振回路', kind='energy', value=gained)


def _h_duo_first_strike(battle, inst, t, **_):
    unit = inst.unit
    if not unit.alive:
        return
    d = _d()
    hasted = 0
    for mate in battle.units:
        if mate.alive and mate.team == unit.team and d._dist(mate, unit) <= 2:
            _haste(mate, t, 4., .25)
            battle._emit_state(mate, t)
            hasted += 1
    fire(battle, inst, unit, t, label='先声夺人', kind='buff', value=hasted, camera='focus')


# ------------------------------------------------------------- resonance rules
def _team_holders(battle, team, tag):
    d = _d()
    return [u for u in battle.units if u.team == team and any(tag in item_tags(k) for k in d._items(u))]


def _h_res_status_2(battle, inst, source, target, kind, t, **_):
    if source is None or source.team != inst.team or not source.alive or target.team == inst.team:
        return
    if not _per_target_ready(inst, source, t, 2.):
        return
    gained = _d()._energy(battle, source, 8)
    if gained:
        fire(battle, inst, source, t, label='异常共鸣', kind='energy', value=gained, spend=False)


def _h_res_status_4(battle, inst, unit, killer, t, **_):
    if unit.team == inst.team:
        return
    kind = _debuff_of(unit)
    if kind not in ('burn', 'poison', 'para'):
        return
    import status
    for victim in sorted((v for v in battle.units if v.alive and v.team == unit.team and v is not unit
                          and _d()._dist(v, unit) <= 2 and _debuff_of(v) is None),
                         key=lambda v: (_d()._dist(v, unit), v.local_idx)):
        spreader = killer if killer is not None and killer.team == inst.team else None
        if status.apply_debuff(battle, victim, kind, t, source=spreader):
            fire(battle, inst, victim, t, label='异常传染', kind='debuff', spend=False)
            return


def _h_res_impact_2(battle, inst, source, target, t, **_):
    if source is None or source.team != inst.team or target.team == inst.team:
        return
    d = _d()
    amount = max(source.attack, source.sp_attack) * .35
    victims = [target] + _enemies_near(battle, source, target, 1, exclude=(target,))
    dealt = 0
    for i, victim in enumerate(victims):
        if victim.alive:
            dealt += d._indirect_damage(battle, source, victim, amount if i == 0 else amount * .5, t)
    if dealt:
        fire(battle, inst, target, t, label='冲击余波', kind='damage', value=dealt, spend=False)


def _h_res_impact_4(battle, inst, source, target, t, **_):
    if source is None or source.team != inst.team or target.team == inst.team or not target.alive:
        return
    if not _per_target_ready(inst, target, t, 4.):
        return
    if stun(battle, target, t, .8):
        fire(battle, inst, target, t, label='冲击眩晕', kind='debuff', spend=False)


def _h_res_arcane_2(battle, inst, unit, t, **_):
    if unit.team != inst.team or not unit.alive or inst.state.get('ready', 0.) > t + 1e-9:
        return
    d = _d()
    mates = [m for m in battle.units if m.alive and m.team == unit.team and m is not unit
             and d._dist(m, unit) <= 2]
    if not mates:
        return
    mate = min(mates, key=lambda m: (m.energy, m.local_idx))
    gained = d._energy(battle, mate, 10)
    if gained:
        inst.state['ready'] = t + 1.5
        fire(battle, inst, mate, t, label='奥术共鸣', kind='energy', value=gained, spend=False)


def _h_res_arcane_4(battle, inst, unit, t, **_):
    if unit.team != inst.team or not unit.alive or unit.idx not in inst.state.setdefault('holders', set()):
        return
    inst.state['holders'].discard(unit.idx)
    gained = _d()._energy(battle, unit, 30)
    if gained:
        fire(battle, inst, unit, t, label='奥术回流', kind='energy', value=gained, spend=False)


def _h_res_guard_2(battle, inst, t, **_):
    d = _d()
    shielded = 0
    for holder in _team_holders(battle, inst.team, 'guard'):
        if not holder.alive:
            continue
        mates = [m for m in battle.units if m.alive and m.team == holder.team and m is not holder
                 and d._dist(m, holder) == 1]
        if not mates:
            continue
        mate = min(mates, key=lambda m: (m.max_hp, m.local_idx))
        if d._shield(battle, holder, mate, holder.max_hp * .12, t, 'res_guard_2'):
            shielded += 1
            fire(battle, inst, mate, t, label='守护共鸣', kind='shield', value=int(holder.max_hp * .12),
                 spend=False)
    if shielded:
        inst.spend(t)


def _h_res_guard_4(battle, inst, source, target, actual_hp, t, **_):
    if target.team != inst.team or not target.alive or actual_hp <= 0 or target.hp > target.max_hp * .5:
        return
    holders = inst.state.setdefault('holders', set())
    if target.idx not in holders:
        return
    holders.discard(target.idx)
    taunted = _taunt_around(battle, target, t, 2.)
    _d()._shield(battle, target, target, target.max_hp * .15, t, 'res_guard_4')
    battle._emit_state(target, t)
    fire(battle, inst, target, t, label='守护挺身', kind='buff', value=taunted, spend=False, camera='focus')


def _h_res_strike_2(battle, inst, unit, target, t, actual_hp, **_):
    if unit.team != inst.team or actual_hp <= 0 or not target.alive:
        return
    if unit.idx not in inst.state.setdefault('holders', set()):
        return
    counts = inst.state.setdefault('n', {})
    counts[unit.idx] = counts.get(unit.idx, 0) + 1
    if counts[unit.idx] % 5:
        return
    dealt = _d()._indirect_damage(battle, unit, target, actual_hp * .4, t)
    if dealt:
        fire(battle, inst, target, t, label='连击追打', kind='damage', value=dealt, spend=False)


def _h_res_strike_4(battle, inst, unit, killer, t, **_):
    if unit.team == inst.team or killer is None or killer.team != inst.team or not killer.alive:
        return
    d = _d()
    hasted = 0
    for mate in battle.units:
        if mate.alive and mate.team == killer.team and mate is not killer and d._dist(mate, killer) <= 2:
            _haste(mate, t, 2., .20)
            battle._emit_state(mate, t)
            hasted += 1
    if hasted:
        fire(battle, inst, killer, t, label='连锁收割', kind='buff', value=hasted, spend=False)


# ------------------------------------------------------------------ specs
def _spec(id, source, trigger, name, handler, description, **kw):
    return EffectSpec(id=id, source=source, trigger=trigger, name=name, description=description,
                      handler=handler, **kw)


UNIT_SPECS = (
    _spec('flame_orb_plus', 'item', 'basic_settled', '火焰宝珠·觉醒', _h_flame_plus, AWAKEN['flame_orb'],
          cooldown=1.5),
    _spec('toxic_orb_plus', 'item', 'basic_settled', '剧毒宝珠·觉醒', _h_toxic_plus, AWAKEN['toxic_orb'],
          cooldown=2.),
    _spec('taunt_bell_plus', 'item', 'direct_hit', '挑衅铃·觉醒', _h_taunt_plus, AWAKEN['taunt_bell'], limit=1),
    _spec('duo_corrosion', 'item', 'basic_settled', '腐蚀爆燃', _h_duo_corrosion, DUOS['duo_corrosion'][2],
          cooldown=1.),
    _spec('duo_conductor', 'item', 'basic_settled', '导电回旋', _h_duo_conductor, DUOS['duo_conductor'][2],
          cooldown=3.),
    _spec('duo_bulldozer', 'item', 'knockback', '推土机', _h_duo_bulldozer, DUOS['duo_bulldozer'][2],
          cooldown=.5),
    _spec('duo_circuit', 'item', 'native_primary', '共振回路', _h_duo_circuit, DUOS['duo_circuit'][2], cooldown=1.),
    _spec('duo_first_strike', 'item', 'battle_start', '先声夺人', _h_duo_first_strike,
          DUOS['duo_first_strike'][2], limit=1),
)
_RES_HANDLERS = {
    ('status', 1): ('debuff', _h_res_status_2), ('status', 2): ('death', _h_res_status_4),
    ('impact', 1): ('knockback', _h_res_impact_2), ('impact', 2): ('knockback', _h_res_impact_4),
    ('arcane', 1): ('native_cast', _h_res_arcane_2), ('arcane', 2): ('native_cast', _h_res_arcane_4),
    ('guard', 1): ('battle_start', _h_res_guard_2), ('guard', 2): ('direct_hit', _h_res_guard_4),
    ('strike', 1): ('basic_settled', _h_res_strike_2), ('strike', 2): ('death', _h_res_strike_4),
}
TEAM_SPECS = tuple(
    _spec(resonance_id(tag, tier), 'resonance', trigger, f'{RESONANCES[tag][0]}·{THRESHOLDS[tier - 1]}',
          handler, RESONANCES[tag][1][tier - 1], owner='team', limit=1 if (tag, tier) == ('guard', 1) else None)
    for (tag, tier), (trigger, handler) in _RES_HANDLERS.items())
NAMES = {spec.id: spec.name for spec in UNIT_SPECS + TEAM_SPECS}


def is_duo(spec_id):
    return spec_id in DUOS


def team_instances(battle, team, members):
    """Resonance instances for ``team``; also stamps battle.item_resonance[team]."""
    from arena_effects import EffectInstance
    d = _d()
    keys = [k for u in members for k in d._items(u)]
    active = active_resonances(keys)
    battle.item_resonance[team] = {'counts': tag_counts(keys), 'active': active}
    instances = []
    for spec in TEAM_SPECS:
        tag, need = spec.id[4:].rsplit('_', 1)
        if active.get(tag, 0) >= THRESHOLDS.index(int(need)) + 1:
            inst = EffectInstance(spec, team, None)
            if spec.id in ('res_arcane_4', 'res_guard_4', 'res_strike_2'):
                inst.state['holders'] = {u.idx for u in _team_holders(battle, team, tag)}
            instances.append(inst)
    return instances
