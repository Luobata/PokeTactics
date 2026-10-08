"""Arena member bonds counted by unique deployed species.

Element panels and the four fixed tactical groups are separate from the classic
team-wide synergy table. Tactical hooks consume settled facts and never launch
another attack, heal or cast. All counters belong to this battle's units.
"""
import copy

import arena
from data import ENERGY_MAX

EPS = 1e-9
TYPE_NAMES = {
    'NORMAL': '一般', 'FIRE': '火', 'WATER': '水', 'GRASS': '草',
    'ELECTRIC': '电', 'ICE': '冰', 'FIGHTING': '格斗', 'POISON': '毒',
    'GROUND': '地面', 'FLYING': '飞行', 'PSYCHIC': '超能力', 'BUG': '虫',
    'ROCK': '岩石', 'GHOST': '幽灵', 'DRAGON': '龙', 'DARK': '恶', 'STEEL': '钢',
}
ELEMENT_MEMBERS = {
    'ELECTRIC': (26, 125, 171, 181), 'FIGHTING': (68, 106, 237, 214),
    'POISON': (31, 34, 94, 73, 45, 3, 211), 'GROUND': (31, 76, 34, 95, 195, 208),
    'ROCK': (76, 95, 142, 248), 'NORMAL': (40, 36, 108, 113, 128, 162, 164, 242),
    'BUG': (12, 127, 123, 214, 212), 'FLYING': (12, 6, 123, 142, 164),
    'GHOST': (94,), 'FIRE': (59, 6, 157),
    'WATER': (73, 9, 80, 121, 131, 211, 195, 171, 230, 160),
    'GRASS': (45, 3, 114, 154), 'PSYCHIC': (65, 80, 121, 122, 196),
    'ICE': (131,), 'DARK': (197, 248), 'STEEL': (208, 212), 'DRAGON': (230,),
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
    'PSYCHIC': {2: {'energy': .10}, 4: {'energy': .20}},
    'BUG': {2: {'speed': .04}, 4: {'speed': .08}},
    'STEEL': {2: {'defense': .10}}, 'DARK': {2: {'dmg': .05}},
    'ICE': {1: {'hp': .06}}, 'GHOST': {1: {'ult_dmg': .05}},
    'DRAGON': {1: {'dmg': .05}},
}
TACTICS = {
    'bond_erosion': {
        'name': '侵蚀', 'members': (6, 31, 34, 73, 157, 211),
        'description': '成员对同一存活敌人归属的灼伤或中毒累计造成三次实际生命损失后，自身获得能量。每个原目标一次；来源冷却4秒、每战最多3次；传播产物不触发，满能量不消耗次数。',
        'tiers': {2: {'energy': 4}, 4: {'energy': 8}},
    },
    'bond_combo': {
        'name': '连击', 'members': (6, 26, 34, 68, 123, 162, 212, 214),
        'description': '成员对同一目标的普攻造成实际生命损失后积累攻速，最多三层。切换普攻目标或4秒无有效普攻清层；技能、教学、侧击、反击和毒伤不叠层。节拍器共用这些层数，每层额外15%攻速。',
        'tiers': {2: {'speed_per_stack': .05}, 4: {'speed_per_stack': .08}},
    },
    'bond_guard': {
        'name': '守护', 'members': (31, 36, 59, 76, 122, 131, 197, 208),
        'description': '成员因直接命中的实际生命损失，从半血以上降至半血或以下且仍存活时，获得3秒自盾。每名成员每战成功一次；毒伤不触发，较强护盾不被覆盖，也不消耗次数。',
        'tiers': {2: {'shield_fraction': .08}, 4: {'shield_fraction': .12}},
    },
    'bond_inspiration': {
        'name': '鼓舞', 'members': (3, 12, 40, 121, 154, 164, 171, 242),
        'description': '成员的本命技能为其他队友有效治疗、成功净化或实际充能后，该队友获得3秒直接伤害加成。受益者冷却5秒、每战最多3次。自益、空效果和教学不触发；与充能鼓舞海克斯取强不叠，各自独立到期。',
        'tiers': {2: {'damage_bonus': .10}, 4: {'damage_bonus': .15}},
    },
}


def _species_id(entry):
    if isinstance(entry, tuple):
        entry = entry[0]
    entry = getattr(entry, 'piece', entry)
    return getattr(entry, 'species_id', entry if type(entry) is int else None)


def memberships(species_id):
    """Stable bond identifiers for one legal arena species."""
    sid = _species_id(species_id)
    if sid not in arena.ROSTER:
        return []
    return ([key for key in ELEMENT_TIERS if sid in ELEMENT_MEMBERS[key]]
            + [key for key, spec in TACTICS.items() if sid in spec['members']])


def count(comp):
    """Deployed species count once, regardless of duplicates, stars or equipment."""
    result = {}
    for sid in sorted({_species_id(entry) for entry in comp} & arena.ROSTER.keys()):
        for key in memberships(sid):
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
    labels = {'hp': '最大生命', 'defense': '物防与特防', 'sp_defense': '特防',
              'atk': '攻击与特攻', 'speed': '攻速', 'dmg': '直接伤害',
              'ult_dmg': '攻击技能伤害', 'dr': '减伤', 'energy': '普攻与受击回能'}
    return '；'.join((f'成员每秒回复{value * 100:g}%最大生命' if effect == 'heal'
                     else f'成员{labels[effect]}+{value * 100:g}%')
                    for effect, value in effects.items())


def catalog():
    """Full 17-element/four-tactic catalogue, including only reachable tiers."""
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
        result.append({'id': key, 'type': key, 'name': spec['name'],
                       'category': 'tactic', 'element': None,
                       'description': spec['description'], 'members': sorted(spec['members']),
                       'beneficiaries': 'team' if key == 'bond_inspiration' else 'members',
                       'pool_size': len(spec['members']),
                       'thresholds': [{'count': tier, 'effect': _effect_text(key, effects),
                                       'effects': copy.deepcopy(effects)}
                                      for tier, effects in spec['tiers'].items()]})
    return result


def preparation(comp, available=None):
    """Only represented bonds; candidates are undeployed compatible species."""
    deployed = {_species_id(entry) for entry in comp} & arena.ROSTER.keys()
    counts = count(comp)
    allowed = (arena.ROSTER.keys() if available is None else
               {_species_id(entry) for entry in available} & arena.ROSTER.keys())
    entries = []
    for row in catalog():
        key, n = row['id'], counts.get(row['id'], 0)
        if not n:
            continue
        tier = tier_of(n, key)
        next_tier = next((step['count'] for step in row['thresholds'] if step['count'] > n), None)
        effect = next((step['effect'] for step in row['thresholds'] if step['count'] == tier), '')
        entries.append({**row, 'n': n, 'tier': tier, 'next': next_tier,
                        'need': max(0, next_tier - n) if next_tier is not None else 0,
                        'effect': effect, 'members': sorted(deployed & set(row['members'])),
                        'candidates': sorted(set(row['members']) & allowed - deployed)})
    return {'entries': entries,
            'note': '只计算上场的不同种族。重复棋子与星级不增加羁绊；属性只强化对应成员，战术按目录中的成员与触发条件生效。'}


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
    """One successful guard shield after a living member crosses half health."""
    from arena_combinations import grant_shield
    key = 'bond_guard'
    tier = _tier(patient, key)
    if (not battle._arena_on or not tier or not patient.alive
            or patient.combo_uses.get(key, 0) or hp_before <= patient.max_hp * .5
            or not 0 < patient.hp <= patient.max_hp * .5 or patient.hp >= hp_before):
        return False
    fraction = TACTICS[key]['tiers'][tier]['shield_fraction']
    if grant_shield(battle, patient, patient, int(patient.max_hp * fraction), t, None,
                    source_kind='combo', source_key=key, reason='direct_damage_cross_half',
                    action_index=action_index, hp_before=hp_before, hp_after=patient.hp,
                    fraction=fraction, bond_tier=tier):
        patient.combo_uses[key] = 1
        return True
    return False


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
