"""Arena member bonds counted by unique deployed species.

Element panels and the four fixed tactical groups are separate from the classic
team-wide synergy table. Tactical hooks consume settled facts and never launch
another attack, heal or cast. All counters belong to this battle's units.
"""
import copy

import arena
import arena_families as families
from data import ENERGY_MAX

EPS = 1e-9
TYPE_NAMES = {
    'NORMAL': '一般', 'FIRE': '火', 'WATER': '水', 'GRASS': '草',
    'ELECTRIC': '电', 'ICE': '冰', 'FIGHTING': '格斗', 'POISON': '毒',
    'GROUND': '地面', 'FLYING': '飞行', 'PSYCHIC': '超能力', 'BUG': '虫',
    'ROCK': '岩石', 'GHOST': '幽灵', 'DRAGON': '龙', 'DARK': '恶', 'STEEL': '钢',
}
ELEMENT_MEMBERS = {
    'ELECTRIC': (26, 125, 171, 181, 145), 'FIGHTING': (68, 106, 237, 214),
    'POISON': (31, 34, 94, 73, 45, 3, 211, 93), 'GROUND': (31, 76, 34, 95, 195, 208),
    'ROCK': (76, 95, 142, 248), 'NORMAL': (40, 36, 108, 113, 128, 162, 164, 242),
    'BUG': (12, 127, 123, 214, 212),
    'FLYING': (12, 6, 123, 142, 164, 144, 145, 146, 198, 227, 149),
    'GHOST': (94, 93, 200), 'FIRE': (59, 6, 157, 146),
    'WATER': (73, 9, 80, 121, 131, 211, 195, 171, 230, 160, 91),
    'GRASS': (45, 3, 114, 154), 'PSYCHIC': (65, 80, 121, 122, 196, 150, 151, 124),
    'ICE': (131, 144, 91, 124, 215), 'DARK': (197, 248, 198, 215),
    'STEEL': (208, 212, 227), 'DRAGON': (230, 148, 149),
}
# Each tier is its total value, not an increment. Only matching members benefit.
ELEMENT_TIERS = {
    'POISON': {2: {'dmg': .04}, 4: {'dmg': .07}, 6: {'dmg': .10}},
    'WATER': {2: {'heal': .003}, 4: {'heal': .006}, 6: {'heal': .009}},
    'NORMAL': {2: {'hp': .06}, 4: {'hp': .10}, 6: {'hp': .14}},
    'GROUND': {2: {'dr': .03}, 4: {'dr': .05}, 6: {'dr': .07}},
    'FIRE': {2: {'atk': .06}, 3: {'atk': .10}},
    'GRASS': {2: {'heal': .003}, 4: {'heal': .006}},
    'ROCK': {2: {'sp_defense': .10}, 4: {'sp_defense': .18}},
    'FIGHTING': {2: {'atk': .05}, 4: {'atk': .09}},
    'FLYING': {2: {'speed': .04}, 4: {'speed': .08}},
    'ELECTRIC': {2: {'speed': .06}, 4: {'speed': .10}},
    'PSYCHIC': {2: {'energy': .05}, 4: {'energy': .10}},
    'BUG': {2: {'speed': .04}, 4: {'speed': .08}},
    'STEEL': {2: {'defense': .10}}, 'DARK': {2: {'dmg': .05}},
    'ICE': {1: {'hp': .06}}, 'GHOST': {1: {'ult_dmg': .05}},
    'DRAGON': {1: {'dmg': .05}},
}
TACTICS = {
    'bond_erosion': {
        'name': '侵蚀', 'members': (6, 31, 34, 73, 157, 211),
        'description': '成员对同一存活敌人归属的灼伤或中毒累计造成三次实际生命损失后，自身获得能量。每个原目标一次；来源冷却4秒、每战最多3次；传播产物不触发，满能量不消耗次数。',
        'playstyle': '持续异常压制，用稳定跳伤换回能。',
        'synergy': ['保护/延长灼毒来源', '扩散灼毒但不继承触发', '为高费技能提前充能'],
        'counterplay': '净化、免疫属性与击杀来源。',
        'tiers': {2: {'energy': 4}, 4: {'energy': 8}},
    },
    'bond_combo': {
        'name': '连击', 'members': (6, 26, 34, 68, 123, 162, 212, 214),
        'description': '成员对同一目标的普攻造成实际生命损失后积累攻速，最多三层。切换普攻目标或4秒无有效普攻清层；技能、教学、侧击、反击和毒伤不叠层。节拍器共用这些层数，每层额外15%攻速。',
        'playstyle': '锁定同一目标，用真实普攻节奏滚起攻速。',
        'synergy': ['前排与援护保护连续输出', '节拍器放大同一层数', '控制限制转火'],
        'counterplay': '频繁换位、护盾完全吸收、闪避或迫使目标死亡切换。',
        'tiers': {2: {'speed_per_stack': .05}, 4: {'speed_per_stack': .08}},
    },
    'bond_guard': {
        'name': '守护', 'members': (31, 36, 59, 76, 122, 131, 197, 208),
        'description': '成员因直接命中的实际生命损失，从半血以上降至半血或以下且仍存活时，获得3秒自盾。每名成员每战成功一次；毒伤不触发，较强护盾不被覆盖，也不消耗次数。',
        'playstyle': '让前排承伤换治疗、反击或大招窗口。',
        'synergy': ['治疗跨过半血后的危机期', '反伤与守护类技能共用时间窗', '鼓舞队友接管输出'],
        'counterplay': '持续伤害绕过触发，集中爆发破盾，或先处理后排支援。',
        'tiers': {2: {'shield_fraction': .08}, 4: {'shield_fraction': .12}},
    },
    'bond_inspiration': {
        'name': '鼓舞', 'members': (3, 12, 40, 121, 154, 164, 171, 242),
        'description': '成员的本命技能为其他队友有效治疗、成功净化或实际充能后，该队友获得3秒直接伤害加成。受益者冷却5秒、每战最多3次。自益、空效果和教学不触发；与充能鼓舞海克斯取强不叠，各自独立到期。',
        'playstyle': '把有效援护转化为短爆发窗口。',
        'synergy': ['治疗、净化与充能辅助同队', '把主力站位放进支援范围', '装备或技能机补启动'],
        'counterplay': '压低血线让治疗必须救急，或击杀辅助切断窗口。',
        'tiers': {2: {'damage_bonus': .10}, 4: {'damage_bonus': .15}},
    },
    'bond_frostline': {
        'name': '寒脉', 'members': (), 'types': ('ICE',),
        'description': '冰成员对同一目标5秒内累计三次有效直接生命损失后，延长目标行动间隔，持续3秒。寒滞不占异常位、不可净化、不阻止移动，也不叠加；更强寒滞可覆盖较弱寒滞。每名成员每战最多四次，空窗口或已有更强效果不消耗次数。',
        'playstyle': '用连续命中拖慢关键敌人，为近战和爆发争取节拍。',
        'synergy': ['连击成员共享同一目标', '束缚让目标更难脱离冰成员', '爆发技能接在第三次命中后'],
        'counterplay': '转火拆累计、击杀冰成员，或利用3秒短窗恢复行动。',
        'tiers': {2: {'slow': .15}, 3: {'slow': .20}},
    },
    'bond_spirit': {
        'name': '魂缚', 'members': (), 'types': ('GHOST',),
        'description': '幽灵成员第一次因直接伤害从55%以上降到55%或以下且存活时，束缚攻击者。1档束缚1格内攻击者1.2秒，2档束缚2格内攻击者1.5秒；更强束缚可延长，已有更强束缚不消耗次数。每名成员每战一次。',
        'playstyle': '用幽灵承伤惩罚贴身输出，保护后排并打乱推进。',
        'synergy': ['远程幽灵安全提供输出', '前排卡位迫使近战触发束缚', '岩钉与位移放大停顿'],
        'counterplay': '远程消耗幽灵、先手爆发击杀，或等待束缚结束再贴近。',
        'tiers': {1: {'range': 1, 'duration': 1.2}, 2: {'range': 2, 'duration': 1.5}},
    },
    'bond_mindsong': {
        'name': '脑波', 'members': (), 'types': ('PSYCHIC',),
        'description': '超能成员完成本命后，使2格内能量未满的最近另一名超能队友回能。受益者冷却3秒、每战最多3次，只结算实际增量；没有合适队友或满能量不触发。',
        'playstyle': '把超能成员站位排成接力网络，轮流完成本命加速循环。',
        'synergy': ['多个超能分支提供不同本命类型', '回能装备放大轮转', '前排保护2格接力链'],
        'counterplay': '用范围伤害惩罚超能紧密布阵，或击杀一名超能断链。',
        'tiers': {2: {'energy': 3}, 4: {'energy': 5}},
    },
    'bond_dragon_pressure': {
        'name': '龙威', 'members': (), 'types': ('DRAGON',),
        'description': '龙成员的本命主命中造成实际生命损失后，标记目标易伤：1档10%持续3秒，2档12%持续4秒并影响目标周围1格敌人。已有易伤不叠加；每名成员每战最多两次。',
        'playstyle': '用高费龙本命开启集火窗口，2档惩罚敌方聚集。',
        'synergy': ['连击和爆发主力跟进易伤目标', '束缚或减速帮助龙完成主命中', '多龙轮流标记'],
        'counterplay': '分散站位、护盾/减伤覆盖窗口，或打断龙能量积累。',
        'tiers': {1: {'fraction': .10, 'duration': 3.}, 2: {'fraction': .12, 'duration': 4.}},
    },
}


def _species_id(entry):
    if isinstance(entry, tuple):
        entry = entry[0]
    entry = getattr(entry, 'piece', entry)
    return getattr(entry, 'species_id', entry if type(entry) is int else None)


def _tactic_members(spec):
    """Type-derived tactics follow the species actually deployed on board."""
    if not spec.get('types'):
        return sorted(spec['members'])
    from data import pokedex
    return sorted(sid for sid in arena.ROSTER
                  if set(spec['types']).intersection(pokedex().species_record(sid)['types']))


def memberships(species_id):
    """Stable bond identifiers for one legal arena species."""
    sid = _species_id(species_id)
    if sid not in arena.ROSTER and sid not in families.SPECIES_FAMILY:
        return []
    from data import pokedex
    origin = sid if sid in arena.ROSTER else families.mentor(sid)
    extra = ()
    if sid >= 252:
        from arena_gen3 import BONDS
        extra = BONDS.get(sid, ())
    types = set(pokedex().species_record(sid)['types'])
    return ([key for key in ELEMENT_TIERS if key in types]
            + [key for key, spec in TACTICS.items()
               if origin in spec['members'] or key in extra or set(spec.get('types', ())) & types])


def count(comp):
    """Count each family once per bond; legacy pieces retain species identity."""
    result, seen = {}, set()
    for entry in comp:
        piece = entry[0] if isinstance(entry, tuple) else entry
        piece = getattr(piece, 'piece', piece)
        sid = _species_id(piece)
        identity = getattr(piece, 'family_id', sid)
        for key in memberships(sid):
            if (key, identity) not in seen:
                seen.add((key, identity))
                result[key] = result.get(key, 0) + 1
    return result


def tier_of(n, key):
    tiers = ELEMENT_TIERS.get(key, TACTICS.get(key, {}).get('tiers', {}))
    return max((tier for tier in tiers if n >= tier), default=0)


def _effect_text(key, effects):
    if key == 'bond_erosion':
        return f"成员三次有效灼毒跳伤后获得{effects['energy']}能量"
    if key == 'bond_combo':
        return f"成员同目标有效普攻每层攻速+{effects['speed_per_stack'] * 100:g}%，最多三层"
    if key == 'bond_guard':
        return f"成员直接伤害跨半血时，自盾{effects['shield_fraction'] * 100:g}%最大生命，持续3秒"
    if key == 'bond_inspiration':
        return f"成员有效本命援护后，其他受益队友直接伤害+{effects['damage_bonus'] * 100:g}%，持续3秒"
    if key == 'bond_frostline':
        return f"成员同目标三次有效直接命中后，目标行动间隔+{effects['slow'] * 100:g}%，持续3秒"
    if key == 'bond_spirit':
        return f"成员首次直接承伤跨55%生命时，束缚{effects['range']}格内攻击者{effects['duration']:g}秒"
    if key == 'bond_mindsong':
        return f"成员完成本命后，2格内另一名超能队友回{effects['energy']}能量"
    if key == 'bond_dragon_pressure':
        return (f"成员有效本命主命中使目标易伤+{effects['fraction'] * 100:g}%，"
                f"持续{effects['duration']:g}秒" + ('，并波及邻格' if effects['duration'] >= 4 else ''))
    labels = {'hp': '最大生命', 'defense': '物防与特防', 'sp_defense': '特防',
              'atk': '攻击与特攻', 'speed': '攻速', 'dmg': '直接伤害',
              'ult_dmg': '攻击技能伤害', 'dr': '减伤', 'energy': '普攻与受击回能'}
    return '；'.join((f'成员每秒回复{value * 100:g}%最大生命' if effect == 'heal'
                     else f'成员{labels[effect]}+{value * 100:g}%')
                    for effect, value in effects.items())


def catalog():
    """Full 17-element/eight-tactic catalogue, including only reachable tiers."""
    result = []
    for key, tiers in ELEMENT_TIERS.items():
        result.append({'id': key, 'type': key, 'name': TYPE_NAMES[key] + '系',
                       'category': 'element', 'element': key,
                       'description': '按上场不同种族计数，只强化本属性成员；重复棋子与星级不增加计数。',
                       'members': sorted(ELEMENT_MEMBERS[key]),
                       'beneficiaries': 'members', 'pool_size': len(ELEMENT_MEMBERS[key]),
                       'thresholds': [{'count': tier, 'effect': _effect_text(key, effects),
                                       'effects': copy.deepcopy(effects)}
                                      for tier, effects in tiers.items()]})
    for key, spec in TACTICS.items():
        members = _tactic_members(spec)
        result.append({'id': key, 'type': key, 'name': spec['name'],
                       'category': 'tactic', 'element': None,
                       'description': spec['description'], 'members': members,
                       'playstyle': spec['playstyle'], 'synergy': list(spec['synergy']),
                       'counterplay': spec['counterplay'],
                       'scenario': f'arena_{key}',
                       'beneficiaries': 'team' if key == 'bond_inspiration' else 'members',
                       'pool_size': len(members),
                       'thresholds': [{'count': tier, 'effect': _effect_text(key, effects),
                                       'effects': copy.deepcopy(effects)}
                                      for tier, effects in spec['tiers'].items()]})
    return result


def preparation(comp, available=None):
    """Only represented bonds; candidates are undeployed compatible species."""
    pieces = [getattr(e[0] if isinstance(e, tuple) else e, 'piece', e[0] if isinstance(e, tuple) else e)
              for e in comp]
    is_family = any(hasattr(p, 'family_id') for p in pieces)
    legal = families.SPECIES_FAMILY.keys() if is_family else arena.ROSTER.keys()
    deployed = {_species_id(entry) for entry in comp} & legal
    counts = count(comp)
    allowed = (legal if available is None else
               {_species_id(entry) for entry in available} & legal)
    entries = []
    for row in catalog():
        if is_family:
            row = {**row, 'members': [sid for sid in legal if row['id'] in memberships(sid)]}
        key, n = row['id'], counts.get(row['id'], 0)
        if not n:
            continue
        tier = tier_of(n, key)
        next_tier = next((step['count'] for step in row['thresholds'] if step['count'] > n), None)
        effect = next((step['effect'] for step in row['thresholds'] if step['count'] == tier), '')
        candidates = set(row['members']) & allowed - deployed
        if is_family:
            represented = {getattr(p, 'family_id', _species_id(p)) for p in pieces
                           if key in memberships(p)}
            candidates = {sid for sid in candidates if families.SPECIES_FAMILY[sid] not in represented}
        entries.append({**row, 'n': n, 'tier': tier, 'next': next_tier,
                        'need': max(0, next_tier - n) if next_tier is not None else 0,
                        'effect': effect, 'members': sorted(deployed & set(row['members'])),
                        'candidates': sorted(candidates)})
    return {'entries': entries,
            'note': ('同一家族对每项羁绊最多计一次；不同分支可贡献各自属性，每只均占人口。' if is_family else
                     '只计算上场的不同种族。重复棋子与星级不增加羁绊；属性只强化对应成员，战术按目录中的成员与触发条件生效。')}


def apply(units, comp, *, enabled=True):
    """Apply member-only panels once after arena role, star and augment panels."""
    counts = count(comp)
    for unit in units:
        keys = memberships(unit.piece.species_id)
        unit.bond_tiers = {key: tier_of(counts.get(key, 0), key) if enabled else 0
                           for key in TACTICS if key in keys}
        if not enabled:
            continue
        effects = {}
        for key in keys:
            if key not in ELEMENT_TIERS:
                continue
            for effect, value in ELEMENT_TIERS[key].get(tier_of(counts.get(key, 0), key), {}).items():
                effects[effect] = effects.get(effect, 0.) + value
        if effects.get('hp'):
            delta = int(unit.max_hp * effects['hp'])
            unit.max_hp += delta
            unit.hp += delta
        for stat, effect in (('attack', 'atk'), ('sp_attack', 'atk'),
                             ('defense', 'defense'), ('sp_defense', 'defense')):
            setattr(unit, stat, getattr(unit, stat) + int(getattr(unit, stat) * effects.get(effect, 0.)))
        unit.sp_defense += int(unit.sp_defense * effects.get('sp_defense', 0.))
        unit.attack_interval /= 1. + effects.get('speed', 0.)
        unit.synergy_dmg = effects.get('dmg', 0.)
        unit.synergy_ult_dmg = effects.get('ult_dmg', 0.)
        unit.synergy_dr = min(.60, effects.get('dr', 0.))
        unit.synergy_heal = effects.get('heal', 0.)
        unit.synergy_energy = effects.get('energy', 0.)
        unit.synergy_ult_cap = None
    return counts


def _tier(unit, key):
    return getattr(unit, 'bond_tiers', {}).get(key, 0)


def after_dot(battle, source, patient, kind, t, actual_hp, action_index):
    """Earn erosion energy from three original-source real HP-loss DOT ticks."""
    from arena_combinations import _effect, _ready, _used
    key = 'bond_erosion'
    tier = _tier(source, key)
    st = getattr(patient, '_st', None)
    if (not battle._arena_on or not tier or source is None or not source.alive
            or not patient.alive or source.team == patient.team or actual_hp <= 0
            or kind not in ('burn', 'poison') or st is None or st.debuff != kind
            or st.debuff_source_idx != source.idx or not st.debuff_spreadable):
        return False
    ledger_key = (patient.idx, kind)
    ledger = source.erosion_counts.get(ledger_key)
    if ledger is None or ledger['epoch'] != st.debuff_source_epoch:
        ledger = {'epoch': st.debuff_source_epoch, 'ticks': 0}
        source.erosion_counts[ledger_key] = ledger
    ledger['ticks'] = min(3, ledger['ticks'] + 1)
    gained = max(0, min(TACTICS[key]['tiers'][tier]['energy'], ENERGY_MAX - source.energy))
    if (ledger['ticks'] < 3 or patient.idx in source.erosion_used_targets or not gained
            or not _ready(source, key, t, 4., 3)):
        return False
    with _effect(battle, source, source, key, 'energy', t,
                 amount=gained, gained=gained, requested=TACTICS[key]['tiers'][tier]['energy'],
                 action_index=action_index, origin_idx=patient.idx, origin_pos=patient.pos,
                 status_kind=kind, dot_ticks=3, bond_tier=tier,
                 reason='owned_actual_dot_three_ticks'):
        source.energy += gained
        source.erosion_used_targets.add(patient.idx)
        _used(source, key, t, 4.)
        battle._emit_state(source, t)
    return True


def after_direct_damage(battle, patient, hp_before, t, action_index):
    """Guard a crossing member, then let a wounded Ghost bind its attacker."""
    from arena_combinations import _effect, grant_shield
    key = 'bond_guard'
    tier = _tier(patient, key)
    guarded = False
    if (not battle._arena_on or not tier or not patient.alive
            or patient.combo_uses.get(key, 0) or hp_before <= patient.max_hp * .5
            or not 0 < patient.hp <= patient.max_hp * .5 or patient.hp >= hp_before):
        guarded = False
    else:
        fraction = TACTICS[key]['tiers'][tier]['shield_fraction']
        if grant_shield(battle, patient, patient, int(patient.max_hp * fraction), t, None,
                        source_kind='combo', source_key=key, reason='direct_damage_cross_half',
                        action_index=action_index, hp_before=hp_before, hp_after=patient.hp,
                        fraction=fraction, bond_tier=tier):
            patient.combo_uses[key] = 1
            guarded = True

    bound = False
    key = 'bond_spirit'
    tier = _tier(patient, key)
    attacker = getattr(patient, '_last_damage_source', None)
    if (not battle._arena_on or not tier or bound or patient.combo_uses.get(key, 0)
            or not patient.alive or attacker is None or not attacker.alive
            or attacker.team == patient.team
            or hp_before <= patient.max_hp * .55
            or not 0 < patient.hp <= patient.max_hp * .55 or patient.hp >= hp_before):
        bound = False
    else:
        effects = TACTICS[key]['tiers'][tier]
        distance = abs(attacker.pos[0] - patient.pos[0]) + abs(attacker.pos[1] - patient.pos[1])
        until = t + effects['duration']
        if distance > effects['range'] or attacker.root_until >= until + EPS:
            bound = False
        else:
            with _effect(battle, patient, attacker, key, 'root', t,
                         amount=0, applied=True, range=effects['range'],
                         duration=effects['duration'], expires_at=until,
                         attacker_idx=attacker.idx, distance=distance,
                         action_index=action_index, hp_before=hp_before,
                         hp_after=patient.hp, bond_tier=tier,
                         reason='direct_damage_cross_55'):
                attacker.root_until = until
                attacker.root_source = patient.idx
                patient.combo_uses[key] = 1
                battle._emit_state(attacker, t)
            bound = True
    return guarded or bound


def after_direct_hit(battle, source, patient, actual_hp, t, action_index, move=None, basic=False):
    """Build a short action-interval debuff from three real direct hits."""
    from arena_combinations import _effect, _ready, _used
    key = 'bond_frostline'
    tier = _tier(source, key)
    if (not battle._arena_on or not tier or source is None or not source.alive
            or not patient.alive or source.team == patient.team or actual_hp <= 0):
        return False
    ledger_key = patient.idx
    ledger = source.bond_frost_counts.get(ledger_key, {'times': []})
    times = ledger['times']
    while times and t - times[0] > 5.:
        times.pop(0)
    times.append(t)
    source.bond_frost_counts[ledger_key] = ledger
    if len(times) < 3:
        return False
    del source.bond_frost_counts[ledger_key]
    fraction = TACTICS[key]['tiers'][tier]['slow']
    active = (patient.bond_chill_fraction if patient.bond_chill_until > t + EPS else 0.)
    if active >= fraction or not _ready(source, key, t, 0., 4):
        return False
    until = t + 3.
    with _effect(battle, source, patient, key, 'chill', t,
                 amount=0, applied=True, hits=3, fraction=fraction,
                 previous_fraction=active, duration=3., expires_at=until,
                 action_index=action_index, origin_idx=patient.idx,
                 origin_pos=patient.pos, bond_tier=tier,
                 reason='same_target_three_actual_direct_hits'):
        patient.bond_chill_fraction = fraction
        patient.bond_chill_until = until
        patient.bond_chill_source_idx = source.idx
        _used(source, key, t, 0.)
        battle._emit_state(patient, t)
    return True


def _native_cast(battle, source, cast_index):
    return (battle._arena_on and isinstance(cast_index, int)
            and 0 <= cast_index < len(battle.events)
            and battle.events[cast_index][1:3] == ('cast', source.idx)
            and battle.events[cast_index][4] == 'arena_' + source.ult_arch)


def after_native_cast(battle, source, t, cast_index):
    """Relay actual energy between two nearby Psychic members after a cast."""
    from arena_combinations import _effect, _ready, _used
    key = 'bond_mindsong'
    tier = _tier(source, key)
    if (not _native_cast(battle, source, cast_index) or not tier or not source.alive):
        return False
    requested = TACTICS[key]['tiers'][tier]['energy']
    candidates = []
    for mate in battle.units:
        if (mate is source or not mate.alive or mate.team != source.team
                or key not in memberships(mate.piece.species_id)
                or mate.energy >= ENERGY_MAX):
            continue
        distance = abs(mate.pos[0] - source.pos[0]) + abs(mate.pos[1] - source.pos[1])
        if distance <= 2 and _ready(mate, key, t, 3., 3):
            candidates.append((distance, -(ENERGY_MAX - mate.energy),
                               battle._target_key(source, mate), mate))
    _, _, _, patient = min(candidates, default=(None, None, None, None))
    if patient is None:
        return False
    gained = min(requested, ENERGY_MAX - patient.energy)
    if gained <= 0:
        return False
    distance = abs(patient.pos[0] - source.pos[0]) + abs(patient.pos[1] - source.pos[1])
    with _effect(battle, source, patient, key, 'energy', t, cast_index,
                 amount=gained, gained=gained, requested=requested,
                 distance=distance, recipient_idx=patient.idx,
                 source_idx=source.idx, bond_tier=tier,
                 reason='completed_native_cast_near_psychic'):
        patient.energy += gained
        _used(patient, key, t, 3.)
        battle._emit_state(patient, t)
    return True


def after_native_hit(battle, source, target, t, cast_index, actual_hp):
    """A Dragon's settled native primary opens a bounded focus window."""
    from arena_combinations import _effect, _ready, _used
    key = 'bond_dragon_pressure'
    tier = _tier(source, key)
    if (not _native_cast(battle, source, cast_index) or not tier or not source.alive
            or actual_hp <= 0 or target.team == source.team
            or not _ready(source, key, t, 0., 2)):
        return False
    effects = TACTICS[key]['tiers'][tier]
    victims = []
    active = (target.vulnerable_fraction if target.vulnerable_until > t + EPS else 0.)
    if target.alive and active < effects['fraction']:
        victims.append(target)
    if tier >= 2:
        victims.extend(enemy for enemy in battle.units
                        if enemy is not target and enemy.alive and enemy.team != source.team
                        and abs(enemy.pos[0] - target.pos[0]) + abs(enemy.pos[1] - target.pos[1]) <= 1
                        and (enemy.vulnerable_fraction if enemy.vulnerable_until > t + EPS else 0.)
                        < effects['fraction'])
    if not victims:
        return False
    until = t + effects['duration']
    for patient in victims:
        with _effect(battle, source, patient, key, 'vulnerability', t, cast_index,
                     amount=0, applied=True, fraction=effects['fraction'],
                     duration=effects['duration'], expires_at=until,
                     origin_idx=target.idx, origin_pos=target.pos,
                     splash_count=len(victims), bond_tier=tier,
                     reason='effective_native_primary'):
            patient.vulnerable_until = until
            patient.vulnerable_fraction = effects['fraction']
            patient.vulnerability_source = source.idx
            battle._emit_state(patient, t)
    _used(source, key, t, 0.)
    return True


def after_native_support(battle, source, patient, actual, kind, t, cast_index):
    """Native effective help from a member empowers another ally, without RNG."""
    from arena_combinations import _effect, _ready, _used
    key = 'bond_inspiration'
    tier = _tier(source, key)
    native = (isinstance(cast_index, int) and 0 <= cast_index < len(battle.events)
              and battle.events[cast_index][1:3] == ('cast', source.idx)
              and battle.events[cast_index][4] == 'arena_' + source.ult_arch)
    if (not battle._arena_on or not tier or not native or actual <= 0
            or kind not in ('heal', 'cleanse', 'energy') or not source.alive
            or not patient.alive or patient is source or patient.team != source.team
            or not _ready(patient, key, t, 5., 3)):
        return False
    fraction = TACTICS[key]['tiers'][tier]['damage_bonus']
    with _effect(battle, source, patient, key, 'offense_buff', t, cast_index,
                 amount=0, fraction=fraction, duration=3., expires_at=t + 3.,
                 source_idx=source.idx, recipient_idx=patient.idx,
                 native_kind=kind, native_actual=actual, bond_tier=tier,
                 reason='other_native_effective_' + kind):
        patient.bond_inspiration_fraction = fraction
        patient.bond_inspiration_until = t + 3.
        patient.bond_inspiration_source_idx = source.idx
        patient.bond_inspiration_cast_index = cast_index
        _used(patient, key, t, 5.)
        battle._emit_state(patient, t)
    return True
