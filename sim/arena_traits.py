"""Arena species passives and strictly scoped optional ability choices.

Chosen abilities live on the battle Piece, while counters and weather windows
remain battle local. Effects annotate settled facts; health/shield statistics
stay owned by the ordinary battle ledger, never by bonus annotations.
"""
from copy import deepcopy

from arena_combinations import EPS, _effect, _ready, _used
from data import ENERGY_MAX
import status

TRAITS_ON = True
TRAITS = {
    26: {'id': 'trait_static', 'name': '静电', 'category': 'attack', 'cooldown': 5., 'limit': 2,
         'trigger': '邻格敌人普攻造成实际生命损失', 'tags': ['受击', '麻痹'],
         'description': '受到邻格敌人的有效生命普攻后，使该敌人麻痹。冷却5秒，每战最多2次；免疫、主要异常占槽或控制保护挡住时不消耗次数。'},
    68: {'id': 'trait_guts', 'name': '毅力', 'category': 'attack', 'cooldown': 5., 'limit': 2,
         'trigger': '自己被成功施加新的主要异常', 'tags': ['异常', '物理进攻'], 'fraction': .20,
         'description': '真实新主要异常施加后，获得3秒物理直接伤害加成20%。冷却5秒，每战最多2次；异常结束或被净化立即失效，刷新异常不重开窗口。保留灼伤本身的攻击降低。'},
    34: {'id': 'trait_poison_point', 'name': '毒刺', 'category': 'attack', 'cooldown': 5., 'limit': 2,
         'trigger': '邻格敌人普攻造成实际生命损失', 'tags': ['受击', '中毒'],
         'description': '受到邻格敌人的有效生命普攻后，使该敌人中毒。冷却5秒，每战最多2次；只施加异常，不追加反击。免疫或主要异常占槽挡住时不消耗次数。'},
    6: {'id': 'trait_blaze', 'name': '猛火', 'category': 'attack', 'cooldown': 3., 'limit': 3,
        'trigger': '生命不高于三分之一时的火属性直接命中', 'tags': ['低血量', '火'], 'fraction': .25,
        'description': '生命不高于最大生命的三分之一时，火属性直接命中伤害提高25%。冷却3秒，每战最多3次；只有实际多扣生命或额外消耗护盾才消耗次数，不增强灼伤。'},
    76: {'id': 'trait_sturdy', 'name': '结实', 'category': 'defense', 'cooldown': 0., 'limit': 1,
         'trigger': '满生命遭受直接命中的致命生命伤害', 'tags': ['保命'],
         'description': '满生命时遭受直接命中的致命伤害，先结算护盾，再保留1生命，每战一次。毒伤与岩钉不触发；本次由结实保命时，气势披带仍可保留。'},
    59: {'id': 'trait_intimidate', 'name': '威吓', 'category': 'defense', 'cooldown': 0., 'limit': 1,
         'trigger': '开战时两格内最近两名敌人', 'tags': ['开局', '物理压制'], 'fraction': .10,
         'description': '开战时，使两格内最近的最多两名敌人物理直接伤害降低10%，持续5秒。每战一次，同类取强，不永久改变攻击面板，不影响毒伤或岩钉。'},
    9: {'id': 'trait_torrent', 'name': '激流', 'category': 'defense', 'cooldown': 3., 'limit': 3,
        'trigger': '生命不高于一半时的水属性直接命中', 'tags': ['低血量', '水'], 'fraction': .15,
        'description': '生命不高于最大生命的一半时，水属性直接命中伤害提高15%。冷却3秒，每战最多3次；只有实际多扣生命或额外消耗护盾才消耗次数。'},
    12: {'id': 'trait_compound_eyes', 'name': '复眼', 'category': 'support', 'cooldown': 3., 'limit': 3,
         'trigger': '原本被道具闪避的进攻判定', 'tags': ['命中', '反闪避'],
         'description': '进攻原本会被道具闪避且原判定落在闪避率后半区时，改为命中。冷却3秒，每战最多3次，沿用该次随机判定，不额外掷骰。'},
    171: {'id': 'trait_volt_absorb', 'name': '蓄电', 'category': 'support', 'cooldown': 4., 'limit': 3,
          'trigger': '电属性直接命中造成实际生命损失后存活', 'tags': ['电', '自疗', '回能'],
          'description': '受到电属性直接命中的实际生命伤害且仍存活时，自疗4%最大生命，并获得最多4实际能量。冷却4秒，每战最多3次，实际恢复或回能成功才消耗次数。本作改编为受伤后的有限吸收。'},
    36: {'id': 'trait_magic_guard', 'name': '魔法防守', 'category': 'support', 'cooldown': 1., 'limit': 3,
         'trigger': '正数毒伤、灼伤或岩钉伤害包', 'tags': ['间接伤害', '防护'],
         'description': '免疫每战前三次正数灼伤、毒伤或岩钉伤害包，冷却1秒；免疫时不消耗护盾。零伤与属性免疫不计次数，不免疫普通进攻或技能。'},
    121: {'id': 'trait_natural_cure', 'name': '自然回复', 'category': 'support', 'cooldown': 4., 'limit': 2,
          'trigger': '成功完成本命施法且自己仍有主要异常', 'tags': ['施法', '自净化'],
          'description': '成功完成本命施法后，清除自己的一个主要异常。冷却4秒，每战最多2次；空净化、教学、被阻止的施法不触发，保留短畏缩与控制保护。'},
    242: {'id': 'trait_healer', 'name': '治愈之心', 'category': 'support', 'cooldown': 4., 'limit': 3,
          'trigger': '本命对其他队友实际治疗至少患者最大生命的5%', 'tags': ['治疗', '净化'],
          'description': '本命对其他队友实际治疗达到患者最大生命的5%后，清除该队友的一个主要异常。冷却4秒，每战最多3次；只有实际净化成功才消耗次数，特性产物不再触发本命联动。'},
}


TRAITS.update({
    3: {'id': 'trait_chlorophyll', 'name': '叶绿素', 'category': 'support',
        'cooldown': 0., 'limit': None, 'weather': 'sun', 'fraction': .25,
        'trigger': '竞技晴天持续期间', 'tags': ['晴天', '行动加速'],
        'description': '竞技晴天中普攻与本命技能行动速度提高25%，移动速度不变；天气结束立即停止。'},
    230: {'id': 'trait_swift_swim', 'name': '悠游自如', 'category': 'attack',
          'cooldown': 0., 'limit': None, 'weather': 'rain', 'fraction': .25,
          'trigger': '竞技雨天持续期间', 'tags': ['雨天', '行动加速'],
          'description': '竞技雨天中普攻与本命技能行动速度提高25%，移动速度不变；天气结束立即停止。'},
})
ALTERNATIVES = {
    34: {'id': 'trait_sheer_force', 'name': '强行', 'category': 'attack',
         'cooldown': 0., 'limit': None, 'fraction': .30,
         'trigger': '毒角突袭或十万伏特、冰冻光束、污泥弹、打雷直接命中',
         'tags': ['追加效果取舍', '生命之玉'],
         'description': '毒角突袭和十万伏特、冰冻光束、污泥弹、打雷直接伤害提高30%，移除这些动作的追加异常与畏缩；毒角突袭也不再对预先中毒目标追加40%追击。仅这些动作免除生命之玉反噬；普攻仍反噬。受击唤醒仍保留。'},
    9: {'id': 'trait_rain_dish', 'name': '雨盘', 'category': 'defense',
        'cooldown': 2., 'limit': 6, 'fraction': .03, 'weather': 'rain',
        'trigger': '竞技雨天中每两秒', 'tags': ['雨天', '自疗'],
        'description': '竞技雨天中每两秒回复3%最大生命，每战最多6次，受封疗影响；实际回复成功才消耗次数。特性治疗不触发本命技能联动。'},
}


def validate_choice(sid, key):
    """Normalize a legal explicit default to None; reject cross-species choices."""
    if type(sid) is not int:
        raise ValueError('竞技特性需要有效宝可梦编号')
    if key is None:
        return None
    default, alternative = TRAITS.get(sid), ALTERNATIVES.get(sid)
    if isinstance(key, str) and default and key == default['id']:
        return None
    if isinstance(key, str) and alternative and key == alternative['id']:
        return key
    raise ValueError('这个宝可梦不能选择该竞技特性')


def _view(sid, spec):
    fixed = sid not in ALTERNATIVES
    default = spec['id'] == TRAITS[sid]['id']
    return {**deepcopy(spec), 'sid': sid, 'species': sid,
            'source_label': '原作特性改编', 'fixed': fixed,
            'selectable': not fixed, 'default': default,
            'choice': None if default else spec['id'], 'arena_only': True}


def for_species(sid, trait_key=None):
    if type(sid) is not int:
        return None if trait_key is None else validate_choice(sid, trait_key)
    chosen = validate_choice(sid, trait_key)
    spec = ALTERNATIVES.get(sid) if chosen is not None else TRAITS.get(sid)
    return _view(sid, spec) if spec else None


def options_for(sid):
    if type(sid) is not int or sid not in TRAITS:
        return []
    specs = [TRAITS[sid]] + ([ALTERNATIVES[sid]] if sid in ALTERNATIVES else [])
    return [_view(sid, spec) for spec in specs]


def catalog():
    return [row for sid in sorted(TRAITS) for row in options_for(sid)]


def _spec(battle, unit, key=None):
    if not battle._arena_on or not TRAITS_ON or unit is None or not unit.alive:
        return None
    sid = unit.piece.species_id
    chosen = validate_choice(sid, getattr(unit.piece, 'arena_trait_key', None))
    spec = ALTERNATIVES.get(sid) if chosen else TRAITS.get(sid)
    return spec if spec and (key is None or spec['id'] == key) else None


def sheer_force_applies(battle, unit, move):
    return bool(_spec(battle, unit, 'trait_sheer_force') and move
                and move['name'] in ('arena_venom_rush', 'thunderbolt',
                                     'ice_beam', 'sludge_bomb', 'thunder'))


def action_multiplier(battle, unit, t):
    spec = _spec(battle, unit)
    if spec and spec['id'] in ('trait_chlorophyll', 'trait_swift_swim'):
        from arena_weather import active
        if active(battle, t) == spec['weather']:
            return 1. + spec['fraction']
    return 1.


def weather_tick(battle, t):
    from arena_weather import active
    if not battle._arena_on or active(battle, t) != 'rain':
        return
    for patient in sorted(battle.units, key=lambda unit: unit.initiative):
        spec = _spec(battle, patient, 'trait_rain_dish')
        if not spec or not _available(patient, spec, t):
            continue
        # Empty/full-health pulses do not count as healing, but the cadence
        # still advances; a new injury cannot create an off-grid pulse.
        window = battle.arena_weather_started_at
        if getattr(patient, '_rain_dish_window', None) != window:
            patient._rain_dish_window = window
            patient._rain_dish_next_at = window + spec['cooldown']
        if t + EPS < patient._rain_dish_next_at:
            continue
        while patient._rain_dish_next_at <= t + EPS:
            patient._rain_dish_next_at += spec['cooldown']
        requested = int(patient.max_hp * spec['fraction'])
        actual = battle._healing_amount(patient, requested, t)[0]
        if actual <= 0:
            continue
        with _effect(battle, patient, patient, spec['id'], 'heal', t,
                     amount=actual, requested=requested, weather='rain',
                     reason='rain_dish_actual_self_heal'):
            battle._heal(patient, requested, t, source=patient)
            _used_trait(patient, spec, t)


def _available(unit, spec, t):
    return _ready(unit, spec['id'], t, spec['cooldown'], spec['limit'])


def _used_trait(unit, spec, t):
    _used(unit, spec['id'], t, spec['cooldown'])


def _physical(battle, unit, move):
    return (unit.attack >= unit.sp_attack if move is None
            else not battle.dex.move_is_special(move))


def opening(battle):
    if not battle._arena_on or not TRAITS_ON:
        return
    for source in sorted(battle.units, key=lambda unit: unit.initiative):
        spec = _spec(battle, source, 'trait_intimidate')
        if spec is None:
            continue
        enemies = sorted((enemy for enemy in battle.units if enemy.alive
                          and enemy.team != source.team
                          and abs(enemy.pos[0] - source.pos[0]) + abs(enemy.pos[1] - source.pos[1]) <= 2),
                         key=lambda enemy: battle._target_key(source, enemy))[:2]
        changed = False
        for patient in enemies:
            if patient.trait_weaken_until > EPS and patient.trait_weaken_fraction >= spec['fraction']:
                continue
            with _effect(battle, source, patient, spec['id'], 'weaken', 0.,
                         amount=0, fraction=spec['fraction'], duration=5., expires_at=5.,
                         damage_scope='physical', reason='opening_nearby_enemies'):
                patient.trait_weaken_fraction, patient.trait_weaken_until = spec['fraction'], 5.
                patient.trait_weaken_source_idx = source.idx
                battle._emit_state(patient, 0.)
            changed = True
        if changed:
            _used_trait(source, spec, 0.)


def expire(battle, unit, t):
    if not battle._arena_on or not TRAITS_ON:
        return
    st = getattr(unit, '_st', None)
    for key, prefix, reason in (
            ('trait_guts', 'trait_guts', 'duration' if st and st.debuff else 'cleansed_or_ended'),
            ('trait_intimidate', 'trait_weaken', 'duration')):
        fraction, until = getattr(unit, prefix + '_fraction'), getattr(unit, prefix + '_until')
        if not fraction or (t + EPS < until and (key != 'trait_guts' or st and st.debuff)):
            continue
        source_idx = unit.idx if key == 'trait_guts' else unit.trait_weaken_source_idx
        source = battle.units[source_idx]
        with _effect(battle, source, unit, key, 'expire', t, amount=0, fraction=fraction,
                     duration=0., expires_at=until, damage_scope='physical', reason=reason):
            setattr(unit, prefix + '_fraction', 0.)
            setattr(unit, prefix + '_until', 0.)
            if key == 'trait_intimidate':
                unit.trait_weaken_source_idx = None
            battle._emit_state(unit, t)


def after_debuff(battle, source, patient, kind, t):
    spec = _spec(battle, patient, 'trait_guts')
    st = getattr(patient, '_st', None)
    if not spec or not st or st.debuff != kind or not _available(patient, spec, t):
        return False
    with _effect(battle, patient, patient, spec['id'], 'offense_buff', t,
                 amount=0, fraction=spec['fraction'], duration=3., expires_at=t + 3.,
                 damage_scope='physical', status_kind=kind,
                 origin_idx=source.idx if source is not None else None,
                 reason='new_major_status'):
        patient.trait_guts_fraction, patient.trait_guts_until = spec['fraction'], t + 3.
        _used_trait(patient, spec, t)
        battle._emit_state(patient, t)
    return True


def prevent_dodge(battle, source, target, roll, t):
    spec = _spec(battle, source, 'trait_compound_eyes')
    if (not spec or roll < target.item_dodge * .5 or roll >= target.item_dodge
            or not _available(source, spec, t)):
        return False
    with _effect(battle, source, target, spec['id'], 'accuracy', t, amount=0,
                 roll=roll, original_dodge=target.item_dodge, saved_dodge=True,
                 reason='existing_dodge_roll_second_half'):
        _used_trait(source, spec, t)
    return True


def prepare_hit(battle, source, patient, damage, t, move, direct):
    """Plan direct modifiers without adding an event before the real hit index."""
    if not battle._arena_on or not TRAITS_ON or not direct or damage <= 0:
        return damage, None
    spec = _spec(battle, source)
    boost = None
    if spec and _available(source, spec, t):
        key = spec['id']
        eligible = (key == 'trait_blaze' and move and move['type'] == 'FIRE'
                    and source.hp * 3 <= source.max_hp or
                    key == 'trait_torrent' and move and move['type'] == 'WATER'
                    and source.hp * 2 <= source.max_hp)
        if eligible or key == 'trait_sheer_force' and sheer_force_applies(battle, source, move):
            boost = spec
    if (spec and spec['id'] == 'trait_guts' and _physical(battle, source, move)
            and source.trait_guts_fraction and t + EPS < source.trait_guts_until
            and getattr(getattr(source, '_st', None), 'debuff', None)):
        boost = spec
    boosted = damage if boost is None else int(damage * (1. + boost['fraction']))
    weakened = (patient is not source and source.trait_weaken_fraction
                and t + EPS < source.trait_weaken_until and _physical(battle, source, move))
    final = int(boosted * (1. - source.trait_weaken_fraction)) if weakened else boosted
    baseline = int(damage * (1. - source.trait_weaken_fraction)) if weakened else damage
    return final, {'boost': boost, 'baseline_damage': baseline, 'boosted_damage': boosted,
                   'final_damage': final, 'weakened': bool(weakened),
                   'weaken_source_idx': source.trait_weaken_source_idx,
                   'weaken_fraction': source.trait_weaken_fraction}


def protect_indirect(battle, patient, damage, t, source=None):
    spec = _spec(battle, patient, 'trait_magic_guard')
    if not spec or damage <= 0 or not _available(patient, spec, t):
        return damage, None
    shield = patient.shield if patient.shield_until > t + EPS else 0
    packet = {'spec': spec, 'prevented': damage,
              'prevented_hp': min(patient.hp, max(0, damage - shield)),
              'avoided_shield_absorption': min(damage, shield),
              'origin_idx': source.idx if source is not None else None}
    _used_trait(patient, spec, t)
    return 0, packet


def emit_protection(battle, patient, packet, t, action_index):
    if packet is None:
        return
    with _effect(battle, patient, patient, packet['spec']['id'], 'guard', t,
                 amount=packet['prevented_hp'], prevented=packet['prevented'],
                 avoided_shield_absorption=packet.get('avoided_shield_absorption', 0),
                 action_index=action_index, origin_idx=packet.get('origin_idx'),
                 reason=packet.get('reason', 'bounded_indirect_immunity')):
        battle._emit_state(patient, t)


def sturdy_ready(battle, patient, t):
    spec = _spec(battle, patient, 'trait_sturdy')
    return bool(spec and patient.hp == patient.max_hp and _available(patient, spec, t))


def protect_lethal(battle, patient, hp_damage, t, direct):
    spec = _spec(battle, patient, 'trait_sturdy')
    if (not direct or not spec or patient.hp != patient.max_hp or hp_damage < patient.hp
            or not _available(patient, spec, t)):
        return hp_damage, None
    capped = max(0, patient.hp - 1)
    _used_trait(patient, spec, t)
    return capped, {'spec': spec, 'prevented': hp_damage - capped,
                    'prevented_hp': min(patient.hp, hp_damage) - capped,
                    'reason': 'full_health_direct_lethal'}


def settled_hp(damage, hp_before, shield_before, survival_ready):
    """Counterfactual settled HP for the same pre-hit shield/survival snapshot."""
    possible = min(hp_before, max(0, damage - shield_before))
    return max(0, hp_before - 1) if possible >= hp_before and survival_ready else possible


def settle_hit(battle, source, patient, context, t, action_index, actual_hp, absorbed,
               hp_before, shield_before, sturdy_before, sash_before):
    if not context or not battle._arena_on or not TRAITS_ON:
        return
    def expected(damage):
        return settled_hp(damage, hp_before, shield_before, sturdy_before or sash_before)
    spec = context['boost']
    if spec:
        baseline = context['baseline_damage']
        baseline_actual = expected(baseline)
        extra = max(0, actual_hp - baseline_actual)
        extra_absorbed = max(0, absorbed - min(baseline, shield_before))
        if extra > 0 or extra_absorbed > 0:
            with _effect(battle, source, patient, spec['id'], 'empowered_hit', t,
                         amount=extra, extra_damage=extra, absorbed=extra_absorbed,
                         baseline_damage=baseline, baseline_actual=baseline_actual,
                         actual_total=actual_hp, action_index=action_index,
                         fraction=spec['fraction'], reason='settled_direct_extra'):
                if spec['id'] != 'trait_guts' and spec['limit'] is not None:
                    _used_trait(source, spec, t)
                battle._emit_state(source, t)
    if context['weakened']:
        prevented = max(0, expected(context['boosted_damage']) - actual_hp)
        source_owner = battle.units[context['weaken_source_idx']]
        if prevented > 0:
            with _effect(battle, source_owner, source, 'trait_intimidate', 'guard', t,
                         amount=prevented, prevented=prevented, action_index=action_index,
                         origin_idx=patient.idx, damage_scope='physical',
                         reason='physical_damage_prevented'):
                battle._emit_state(source, t)


def after_direct_hit(battle, source, patient, actual_hp, t, action_index, move, basic):
    spec = _spec(battle, patient)
    if not spec or actual_hp <= 0 or source.team == patient.team:
        return
    key = spec['id']
    if key in ('trait_static', 'trait_poison_point'):
        kind = 'para' if key == 'trait_static' else 'poison'
        st = getattr(source, '_st', None)
        if (not basic or not source.alive or st is None or st.debuff is not None
                or not _available(patient, spec, t)
                or abs(source.pos[0] - patient.pos[0]) + abs(source.pos[1] - patient.pos[1]) != 1
                or set(source.piece.types).intersection(status.IMMUNE_TYPES[kind])
                or kind in status.CONTROL_KINDS and t + EPS < st.ctrl_until or not status.STATUS_ON):
            return
        with _effect(battle, patient, source, key, 'status', t, amount=0,
                     status_kind=kind, applied=True, action_index=action_index,
                     reason='adjacent_actual_basic_received'):
            if status.apply_debuff(battle, source, kind, t, source=patient):
                _used_trait(patient, spec, t)
        return
    if (key != 'trait_volt_absorb' or move is None or move['type'] != 'ELECTRIC'
            or not _available(patient, spec, t)):
        return
    requested = int(patient.max_hp * .04)
    actual = battle._healing_amount(patient, requested, t)[0]
    energy = min(4, max(0, ENERGY_MAX - patient.energy))
    if actual <= 0 and energy <= 0:
        return
    if actual > 0:
        with _effect(battle, patient, patient, key, 'heal', t, amount=actual,
                     requested=requested, action_index=action_index, origin_idx=source.idx,
                     reason='survived_actual_electric_hp'):
            battle._heal(patient, requested, t, source=patient)
    if energy > 0:
        with _effect(battle, patient, patient, key, 'energy', t, amount=energy,
                     requested=4, action_index=action_index, origin_idx=source.idx,
                     reason='survived_actual_electric_hp'):
            patient.energy += energy
            battle._emit_state(patient, t)
    _used_trait(patient, spec, t)


def _cleanse(battle, source, patient, spec, t, cast_index, reason):
    kind = getattr(getattr(patient, '_st', None), 'debuff', None)
    if not kind or not status.STATUS_ON or not patient.alive:
        return False
    with _effect(battle, source, patient, spec['id'], 'cleanse', t, cast_index,
                 amount=0, status_kind=kind, cleansed_status=kind, reason=reason):
        removed = status.cleanse(battle, patient, t)
        if removed:
            _used_trait(source, spec, t)
    return removed


def after_native_cast(battle, source, t, cast_index):
    from arena_weather import after_native_cast as request_weather
    requested = request_weather(battle, source, t, cast_index)
    spec = _spec(battle, source, 'trait_natural_cure')
    if (not spec or not _available(source, spec, t) or type(cast_index) is not int
            or not 0 <= cast_index < len(battle.events)
            or battle.events[cast_index][1:3] != ('cast', source.idx)
            or battle.events[cast_index][4] != 'arena_' + source.ult_arch):
        return requested
    return _cleanse(battle, source, source, spec, t, cast_index, 'completed_native_self_cure') or requested


def after_native_heal(battle, source, patient, actual, t, cast_index):
    spec = _spec(battle, source, 'trait_healer')
    if (not spec or patient is source or source.team != patient.team or actual <= 0
            or actual + EPS < patient.max_hp * .05 or not _available(source, spec, t)
            or type(cast_index) is not int or not 0 <= cast_index < len(battle.events)
            or battle.events[cast_index][1:3] != ('cast', source.idx)
            or battle.events[cast_index][4] != 'arena_' + source.ult_arch):
        return False
    return _cleanse(battle, source, patient, spec, t, cast_index, 'effective_native_other_heal')
