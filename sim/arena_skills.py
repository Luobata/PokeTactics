"""Arena-only native skills: fixed identity, separate from the learned TM slot."""
import copy
import status
import arena_combinations
import arena_fields
from data import ENERGY_MAX


SKILLS = {
    26: dict(id='spark_chain', name='电流链', type='ELECTRIC', power=65, role='attack',
             tags=['连锁', '密集阵容'],
             description='电击主目标，再向两格内的敌人跳跃至多两次，分别造成55%和35%伤害；地面免疫会截断连锁。'),
    68: dict(id='four_arm_combo', name='四臂连击', type='FIGHTING', power=60, role='attack',
             tags=['连击', '击退'],
             description='攻击主目标，再追加至多两次30%伤害追击；目标存活且后方有空位时，击退一格。'),
    34: dict(id='venom_rush', name='毒角突袭', type='POISON', power=65, role='attack',
             tags=['中毒', '追击'],
             description='攻击主目标；目标施法前已中毒时追加40%伤害。命中后尝试使目标中毒，遵循属性免疫和单异常状态限制。'),
    94: dict(id='shadow_siphon', name='暗影汲能', type='GHOST', power=65, role='attack',
             tags=['汲能', '干扰'],
             description='选择射程内能量最高的敌人攻击，造成伤害后偷取至多20点能量，自身获得其中一半；普攻仍保留普通索敌，能量上限80。'),
    6: dict(id='flame_storm', name='大字爆炎', type='FIRE', power=70, role='attack',
            tags=['范围', '轰炸'],
            description='攻击主目标，并对目标相邻一格内的至多两名其他敌人造成50%火属性伤害。'),
    65: dict(id='psychic_blink', name='瞬移念力', type='PSYCHIC', power=70, role='attack',
             tags=['瞬移', '收割'],
             description='闪现到生命值最低敌人的邻格再攻击；没有可用落点时，攻击当前范围内的目标。'),
    31: dict(id='venom_armor', name='毒刺护甲', type='POISON', power=50, role='defense',
             tags=['减伤', '中毒'],
             description='进入3秒毒刺姿态并获得25%减伤；受到两格内敌人的有效主攻击伤害时，反击35威力毒属性伤害并尝试使其中毒。每次姿态至多反击3次，反击不会再触发反击或回能。'),
    76: dict(id='stone_pulse', name='岩甲震波', type='GROUND', power=50, role='defense',
             tags=['减伤', '震击'],
             description='自身获得3秒25%减伤，攻击主目标，并震击自身邻格的至多两名其他敌人，各40%伤害；有效震击造成0.3秒畏缩，受控制保护限制。'),
    59: dict(id='flame_guard', name='炽焰守护', type='FIRE', power=50, role='defense',
             tags=['护卫', '减伤'],
             description='自身获得3秒30%减伤，嘲讽两格内至多两名敌人，使其优先攻击自己2秒；每名敌人每4秒最多被嘲讽一次。技能本身不造成伤害。'),
    73: dict(id='venom_tide', name='毒潮屏障', type='POISON', power=45, role='defense',
             tags=['范围', '减伤'],
             description='攻击主目标，并对其邻格至多两名其他敌人造成40%毒属性伤害；自身获得3秒20%减伤。'),
    9: dict(id='twin_cannon', name='双炮冲击', type='WATER', power=55, role='defense',
            tags=['贯穿', '击退'],
            description='攻击主目标，沿前向直线贯穿至多两名其他敌人，各45%水属性伤害；主目标后方有空位时击退一格，自身获得3秒20%减伤。'),
    80: dict(id='slow_field', name='迟缓领域', type='PSYCHIC', power=45, role='defense',
             tags=['控能', '减伤'],
             description='攻击主目标；主目标与其邻格至多两名其他敌人各失去至多15点能量；自身获得3秒30%减伤。'),
    40: dict(id='healing_song', name='治愈歌声', type='NORMAL', power=30, role='support',
             tags=['群体治疗', '回复'],
             description='为两格内生命比例最低的至多两名受伤友军各回复12%最大生命，可治疗自身；没有可有效治疗的目标时保留能量，治疗受封疗影响。'),
    12: dict(id='cleansing_powder', name='净化蝶粉', type='BUG', power=30, role='support',
             tags=['净化', '回复'],
             description='优先为两格内带主要异常的一名友军净化，再回复15%最大生命；没有异常时治疗最虚弱友军。治疗受封疗影响。'),
    36: dict(id='moon_blessing', name='月光祝福', type='NORMAL', power=30, role='support',
             tags=['保护', '回复'],
             description='为两格内最虚弱的一名友军提供20%最大生命的月光护盾，持续3秒，可保护自身；护盾单槽，只覆盖更弱的护盾，不治疗生命。'),
    45: dict(id='aroma_garden', name='芳香花域', type='GRASS', power=35, role='support',
             tags=['解毒', '群体治疗'],
             description='优先净化两格内至多两名中毒友军，再为其回复10%最大生命；没有中毒时治疗最虚弱的受伤友军，治疗受封疗影响。'),
    3: dict(id='solar_relay', name='日光反哺', type='GRASS', power=65, role='support',
            tags=['伤害转治疗', '回复'],
            description='攻击主目标，将目标实际失去生命的35%用于治疗两格内生命比例最低的一名受伤友军；治疗受封疗影响。'),
    121: dict(id='star_resonance', name='星光共鸣', type='WATER', power=35, role='support',
              tags=['回能', '回复'],
              description='为两格内未满能量、能量最高的至多两名其他友军各补充18点能量；不治疗生命、不为自身回能，能量上限80，接收者在自己的行动时施法。'),
    95: dict(id='rock_spikes', name='岩钉场', type='ROCK', power=40, role='defense',
             tags=['地形', '入格伤害'],
             description='在射程内主目标所在格和后方、侧方铺设至多3格岩钉，持续6秒，施放时不攻击；敌人进入才受伤，伤害受岩属性克制影响。每队最多3格，站立不受伤，可衔接击退。'),
    106: dict(id='sweeping_kick', name='扫堂飞踢', type='FIGHTING', power=55, role='attack',
              tags=['近战', '击退'],
              description='攻击主目标，命中后若目标存活且后方有空位，将其击退一格；可把敌人推入岩钉。'),
    108: dict(id='rescue_tongue', name='救援舌', type='NORMAL', power=30, role='support',
              tags=['救援', '回复'],
              description='为两格内最虚弱的一名其他受伤友军回复12%最大生命；有空位时将其拉近一格。没有可治疗或可拉近的目标时保留能量，强制移动仍会触发敌方岩钉。'),
    114: dict(id='root_domain', name='缠根之域', type='GRASS', power=40, role='defense',
              tags=['定身', '控制铺垫'],
              description='主命中造成实际生命损失后，使存活目标定身1.5秒，限制自然移动但不限制攻击和强制位移；每个来源每战至多定身3次。'),
    113: dict(id='life_pulse', name='生命脉冲', type='NORMAL', power=25, role='support',
              tags=['净化', '回复'],
              description='为两格内最虚弱的一名其他友军回复25%最大生命，并净化其一个主要异常状态；无伤无异常时保留能量，不治疗自身，治疗受封疗影响。'),
    122: dict(id='barrier_relay', name='屏障接力', type='PSYCHIC', power=30, role='support',
              tags=['净化', '保护'],
              description='为两格内最虚弱的一名其他友军提供14%最大生命护盾及20%减伤，均持续3秒；不治疗生命。护盾单槽，只覆盖更弱的护盾。'),
    125: dict(id='storm_conductor', name='雷暴导体', type='ELECTRIC', power=55, role='attack',
              tags=['麻痹联动', '连锁'],
              description='攻击主目标；若其施法前已麻痹，对其邻格至多两名其他敌人各追加35%电属性伤害。主命中可按电属性规则尝试麻痹。'),
    127: dict(id='armor_pincer', name='破甲夹击', type='BUG', power=60, role='attack',
              tags=['易伤', '集火'],
              description='主命中造成实际生命损失后，使存活目标受到的攻击伤害提高12%，持续4秒；单槽刷新，不叠加。'),
    123: dict(id='gale_cross', name='疾风十字', type='BUG', power=60, role='attack',
              tags=['控制追击', '收割'],
              description='攻击主目标；若其施法前已定身、冰冻或麻痹，追加一次35%虫属性伤害追击。追击不再触发原生联动。'),
    128: dict(id='bull_rush', name='蛮力冲阵', type='NORMAL', power=55, role='defense',
              tags=['击退', '减伤'],
              description='攻击主目标，命中后且后方有空位时击退一格；自身获得3秒20%减伤。'),
    131: dict(id='frost_shelter', name='冰霜庇护', type='ICE', power=35, role='support',
              tags=['冰冻铺垫', '回复'],
              description='为两格内至多两名其他友军提供14%最大生命冰霜护盾，持续3秒，并解除冰冻；优先保护冰冻友军。护盾单槽，只覆盖更弱的护盾，不攻击、不治疗生命。'),
    142: dict(id='cliff_swoop', name='悬崖掠袭', type='ROCK', power=65, role='attack',
              tags=['击退', '清场'],
              description='攻击主目标，命中后且后方有空位时击退一格；清除自身一格内至多一格敌方岩钉。'),
    162: dict(id='alert_tail', name='警戒尾击', type='NORMAL', power=50, role='attack',
              tags=['异常追击', '连击'],
              description='攻击主目标；主命中实际扣除生命且目标施法前生命比例不高于35%时，追加一次60%一般属性伤害收割。收割不再触发异常或原生联动。'),
    211: dict(id='toxic_spines', name='毒针散布', type='POISON', power=50, role='attack',
              tags=['中毒', '铺毒'],
              description='主命中实际扣除生命后，尝试使存活主目标中毒，并对其邻格至多一名其他敌人造成30%毒属性伤害；侧击实际扣除生命后尝试中毒，遵循属性免疫和单异常状态限制。'),
    195: dict(id='mud_anchor', name='泥沼锚定', type='GROUND', power=40, role='defense',
              tags=['定身', '减伤'],
              description='攻击主目标；主命中实际扣除生命后，使存活目标定身1.5秒，每个来源每战至多3次；自身获得3秒25%减伤。定身不阻止攻击或强制位移。'),
    237: dict(id='spinning_cleanup', name='旋转扫钉', type='FIGHTING', power=40, role='defense',
              tags=['清场', '减伤'],
              description='攻击主目标；主命中实际扣除生命后，对自身邻格至多一名其他敌人造成35%格斗属性伤害；清除自身一格内至多3格敌方岩钉，并获得3秒20%减伤。'),
    164: dict(id='watchful_lullaby', name='守夜安抚', type='FLYING', power=25, role='support',
              tags=['净化', '回复'],
              description='优先为两格内一名其他友军解除睡眠或麻痹，并补充16点能量；没有对应异常时，支援能量最高的未满能量友军。不治疗生命、不清除其他主要异常，不为自身回能。'),
    171: dict(id='beacon_relay', name='灯塔接力', type='ELECTRIC', power=30, role='support',
              tags=['回能', '回复'],
              description='为两格内至多两名未满能量的其他友军各补充14点能量，优先攻击型，再按能量从高到低选择；不治疗生命、不为自身回能，能量上限80。'),
    181: dict(id='charged_beacon', name='雷光信标', type='ELECTRIC', power=65, role='attack',
              tags=['麻痹联动', '连锁'],
              description='攻击主目标，按电属性规则尝试麻痹；主命中实际扣除生命且目标施法前已麻痹时，对目标两格内最近的一名其他敌人追加60%电属性伤害。侧击不再施加麻痹。'),
    196: dict(id='fracture_vision', name='弱点预见', type='PSYCHIC', power=65, role='attack',
              tags=['易伤追击', '集火'],
              description='攻击主目标；主命中实际扣除生命且目标施法前已有未到期易伤时，追加一次50%超能属性伤害追击。不会自行施加易伤，追击不再触发原生联动。'),
    214: dict(id='horn_pressure', name='破角突击', type='FIGHTING', power=65, role='attack',
              tags=['易伤', '控制追击'],
              description='主命中实际扣除生命后，若目标施法前已定身、冰冻或麻痹，追加一次35%格斗属性伤害；并使存活目标受到的攻击伤害提高12%，持续4秒，单槽刷新不叠加。'),
    197: dict(id='moon_guard', name='月影护幕', type='DARK', power=45, role='defense',
              tags=['控能', '保护'],
              description='攻击主目标；主命中实际扣除生命后，使存活目标失去至多10能量；自身获得3秒25%减伤，并为两格内生命比例最低的一名其他友军提供3秒20%减伤。'),
    208: dict(id='iron_fault', name='钢尾震退', type='STEEL', power=50, role='defense',
              tags=['击退', '减伤'],
              description='攻击主目标；主命中实际扣除生命且目标存活、后方有空位时，击退一格，可触发岩钉入格；自身获得3秒30%减伤。'),
    242: dict(id='bliss_chorus', name='幸福合唱', type='NORMAL', power=25, role='support',
              tags=['群体治疗', '援护'],
              description='为两格内生命比例最低的至多两名其他受伤友军各回复18%最大生命；没有可有效治疗的目标时保留能量，不治疗自身，治疗受封疗影响，可接护盾与辅助回能联动。'),
    157: dict(id='cinder_eruption', name='烬火喷发', type='FIRE', power=75, role='attack',
              tags=['灼伤联动', '范围'],
              description='攻击主目标；主命中实际扣除生命后，对目标邻格至多两名其他敌人各造成45%火属性伤害；若主目标施法前已灼伤，侧击提高至65%。侧击不再施加灼伤。'),
    212: dict(id='cross_bullet', name='交叉弹拳', type='STEEL', power=70, role='attack',
              tags=['连击', '易伤追击'],
              description='攻击主目标；主命中实际扣除生命后，对存活目标追加至多两次20%钢属性伤害；若目标施法前已有未到期易伤，每次提高至35%。追击不再触发原生联动。'),
    230: dict(id='dragon_crosscurrent', name='潮龙贯流', type='WATER', power=75, role='attack',
              tags=['贯穿', '双属性'],
              description='以水属性攻击主目标；主命中实际扣除生命后，沿施法前的前向直线贯穿至多两名其他敌人，各造成50%龙属性伤害；侧击不再触发异常或原生联动。'),
    160: dict(id='undertow_lock', name='潜流锁阵', type='WATER', power=55, role='defense',
              tags=['定身', '击退'],
              description='主命中实际扣除生命后，若存活目标施法前已定身、冰冻或麻痹，后方有空位时击退一格；否则使其定身1.5秒，每个来源每战至多3次。自身获得3秒25%减伤。'),
    248: dict(id='crag_citadel', name='岩崩壁垒', type='ROCK', power=55, role='defense',
              tags=['地形', '击退'],
              description='主命中实际扣除生命后，若目标施法前站在本队未到期岩钉上且存活，后方有空位时击退一格；否则在目标及后方、侧方铺设至多3格岩钉6秒，每队最多3格。自身获得3秒25%减伤；当次新铺岩钉不会触发击退。'),
    154: dict(id='verdant_sanctuary', name='清露花幕', type='GRASS', power=40, role='support',
              tags=['群体净化', '回复'],
              description='优先净化两格内至多两名带主要异常的其他友军，再各回复12%最大生命；没有异常时治疗最虚弱的受伤友军。不治疗自身，治疗受封疗影响。'),

}


# Targeting is a gameplay contract, not a color/theme hint. Non-hostile casts
# never enter _land_hit; renderers and catalogs use the same identity metadata.
_IDENTITIES = {
    26: ('enemy', 'chain', '连锁输出'), 68: ('enemy', 'combo', '多段击退'),
    34: ('enemy', 'poison', '毒伤追击'), 94: ('enemy', 'drain', '锁定汲能'),
    6: ('enemy', 'area', '范围轰炸'), 65: ('enemy', 'assassin', '瞬移收割'),
    31: ('self', 'retaliation', '毒刺反击'), 76: ('enemy', 'control', '震击控场'),
    59: ('self', 'taunt', '嘲讽护卫'), 73: ('enemy', 'area', '毒潮压制'),
    9: ('enemy', 'displacement', '贯穿击退'), 80: ('enemy', 'drain', '范围控能'),
    40: ('ally', 'heal', '群体治疗'), 12: ('ally', 'cleanse', '净化治疗'),
    36: ('ally', 'shield', '单体护盾'), 45: ('ally', 'cleanse', '群体解毒'),
    3: ('enemy', 'lifesteal', '伤害反哺'), 121: ('ally', 'energy', '能量补给'),
    95: ('field', 'terrain', '地形布置'), 106: ('enemy', 'displacement', '击退联动'),
    108: ('ally', 'rescue', '拉回救援'), 114: ('enemy', 'root', '定身控场'),
    113: ('ally', 'heal', '单体急救'), 122: ('ally', 'guard', '屏障减伤'),
    125: ('enemy', 'chain', '麻痹连锁'), 127: ('enemy', 'vulnerability', '破甲集火'),
    123: ('enemy', 'pursuit', '控制追击'), 128: ('enemy', 'displacement', '前排冲阵'),
    131: ('ally', 'shield', '群体护盾'), 142: ('enemy', 'clear', '击退清场'),
    162: ('enemy', 'execute', '残血收割'), 211: ('enemy', 'poison', '范围铺毒'),
    195: ('enemy', 'root', '定身阻截'), 237: ('enemy', 'clear', '地形清除'),
    164: ('ally', 'cleanse', '解控回能'), 171: ('ally', 'energy', '攻击回能'),
    181: ('enemy', 'chain', '麻痹导电'), 196: ('enemy', 'pursuit', '易伤追击'),
    214: ('enemy', 'vulnerability', '破甲压制'), 197: ('enemy', 'drain', '控能援护'),
    208: ('enemy', 'displacement', '重甲击退'), 242: ('ally', 'heal', '群体急救'),
    157: ('enemy', 'area', '灼伤轰炸'), 212: ('enemy', 'combo', '破甲连击'),
    230: ('enemy', 'pierce', '双属性贯穿'), 160: ('enemy', 'root', '定身推移'),
    248: ('enemy', 'terrain', '岩钉壁垒'), 154: ('ally', 'cleanse', '群体净化'),
}
for _sid, (_targeting, _category, _behavior) in _IDENTITIES.items():
    SKILLS[_sid].update(targeting=_targeting, category=_category, behavior=_behavior)
    if _targeting != 'enemy':
        SKILLS[_sid]['power'] = 0
# Tags describe the current mechanics, including support skills that no longer
# heal. Attack range still describes basic attacks, not allied support range.
for _sid, _tags in {
    31: ['反击', '中毒', '减伤'], 59: ['嘲讽', '护卫', '减伤'],
    36: ['护盾', '保护'], 121: ['回能', '节奏'], 122: ['护盾', '减伤'],
    131: ['群体护盾', '解冻'], 162: ['残血收割', '追击'],
    164: ['解控', '回能'], 171: ['攻击回能', '节奏'],
}.items():
    SKILLS[_sid]['tags'] = _tags


def skill_of(species_id):
    if species_id not in SKILLS:
        raise ValueError('精灵没有竞技原生技能')
    return {'arch': SKILLS[species_id]['id'], **copy.deepcopy(SKILLS[species_id])}


def catalog():
    return [dict(sid=sid, **skill_of(sid)) for sid in sorted(SKILLS)]


def resolve_cast(piece):
    skill = skill_of(piece.species_id)
    return {'id': None, 'name': 'arena_' + skill['id'], 'name_zh': skill['name'],
            'type': skill['type'], 'power': skill['power'], 'accuracy': 100,
            'effect': None, 'targeting': skill['targeting'],
            'category': skill['category'], 'behavior': skill['behavior']}


def _distance(a, b):
    return abs(a.pos[0] - b.pos[0]) + abs(a.pos[1] - b.pos[1])


def _allies(battle, unit, *, wounded=False, others=False):
    return sorted((friend for friend in battle.units
                   if friend.alive and friend.team == unit.team and _distance(unit, friend) <= 2
                   and (not wounded or friend.hp < friend.max_hp)
                   and (not others or friend is not unit)),
                  key=lambda friend: (friend.hp / friend.max_hp, battle._target_key(unit, friend)))


def _near_enemies(battle, unit, anchor, primary):
    return sorted((enemy for enemy in battle.units
                   if enemy.alive and enemy.team != unit.team and enemy is not primary
                   and abs(enemy.pos[0] - anchor[0]) + abs(enemy.pos[1] - anchor[1]) <= 1),
                  key=lambda enemy: battle._target_key(unit, enemy))[:2]


def _side_hit(battle, unit, target, move, fraction, t, cast_index, origin=None, **details):
    if not unit.alive or not target.alive or unit.team == target.team:
        return 0
    damage = battle._move_damage(unit, target, move, fraction)
    with battle._skill_effect(unit, target, 'side_hit', t, cast_index,
                              damage=damage, move_type=move['type'],
                              origin_idx=(origin or unit).idx, **details):
        actual = battle._land_hit(unit, target, damage, t, move=move)
    return actual


def _heal(battle, unit, patient, amount, t, cast_index):
    amount = max(0, int(amount * unit.arena_heal_mult))
    actual = battle._healing_amount(patient, amount, t)[0]
    if not patient.alive or patient.hp >= patient.max_hp or amount <= 0:
        return 0
    # Fully prevented healing still belongs to this cast's presentation packet.
    with battle._skill_effect(unit, patient, 'heal', t, cast_index,
                              amount=actual, requested=amount):
        actual = battle._heal(patient, amount, t)
    from arena_equipment import after_native_heal
    after_native_heal(battle, unit, patient, actual, t, cast_index)
    from arena_traits import after_native_heal as trait_after_native_heal
    trait_after_native_heal(battle, unit, patient, actual, t, cast_index)
    return actual


def _guard(battle, unit, patient, fraction, t, cast_index):
    if not patient.alive:
        return
    # One temporary guard slot: a weaker shield cannot prolong a stronger one.
    if patient.temp_dr_until > t and patient.temp_dr > fraction:
        return
    with battle._skill_effect(unit, patient, 'guard', t, cast_index,
                              reduction=fraction, duration=3., expires_at=t + 3.):
        patient.temp_dr, patient.temp_dr_until = fraction, t + 3.
        battle._emit_state(patient, t)


def _poison(battle, unit, target, t, cast_index, **details):
    if not target.alive or getattr(getattr(target, '_st', None), 'debuff', None) == 'poison':
        return
    with battle._skill_effect(unit, target, 'status', t, cast_index, status='poison', **details):
        status.apply_debuff(battle, target, 'poison', t)


def _cleanse(battle, unit, patient, t, cast_index, kinds=None):
    kind = getattr(getattr(patient, '_st', None), 'debuff', None)
    if not patient.alive or kind is None or kinds is not None and kind not in kinds:
        return
    with battle._skill_effect(unit, patient, 'cleanse', t, cast_index, status=kind):
        removed = status.cleanse(battle, patient, t, kinds=kinds)
    return removed


def _knockback(battle, unit, target, t, cast_index):
    if not target.alive:
        return
    destination = battle._knock_cell(target, unit.pos)
    if destination is not None:
        with battle._skill_effect(unit, target, 'knockback', t, cast_index,
                                  origin=target.pos, destination=destination):
            arena_fields.move_unit(battle, target, destination, t, cast_index,
                                   source=unit, reason='knockback')


def _pull(battle, unit, patient, t, cast_index):
    destination = _pull_destination(battle, unit, patient)
    if destination is None:
        return
    with battle._skill_effect(unit, patient, 'pull', t, cast_index,
                              origin=patient.pos, destination=destination):
        arena_fields.move_unit(battle, patient, destination, t, cast_index,
                               source=unit, reason='pull')


def _pull_destination(battle, unit, patient):
    if not patient.alive:
        return None
    x, y = patient.pos
    occupied = {other.pos for other in battle.units if other.alive}
    candidates = [(x + dx, y + dy) for dx, dy in ((0, -1), (-1, 0), (1, 0), (0, 1))
                  if 0 <= x + dx < 6 and 0 <= y + dy < 6
                  and (x + dx, y + dy) not in occupied
                  and abs(x + dx - unit.pos[0]) + abs(y + dy - unit.pos[1]) < _distance(unit, patient)]
    if not candidates:
        return None
    return min(candidates, key=lambda pos: (
        abs(pos[0] - unit.pos[0]) + abs(pos[1] - unit.pos[1]),
        battle._local_pos(pos, unit.team)))


def _drain(battle, unit, target, maximum, t, cast_index, transfer=False):
    # The primary hit may be lethal. Its recorded residual energy can still be
    # siphoned by the caster; death does not cancel this action's transfer.
    stolen = min(maximum, target.energy) if target.alive or transfer else 0
    if not stolen:
        return
    gained = min(ENERGY_MAX - unit.energy, stolen // 2) if transfer else 0
    with battle._skill_effect(unit, target, 'energy_drain', t, cast_index,
                              stolen=stolen, gained=gained):
        target.energy -= stolen
        unit.energy += gained
        battle._emit_state(target, t)
        if gained:
            battle._emit_state(unit, t)


def _energy(battle, unit, recipient, requested, t, cast_index):
    gained = max(0, min(requested, ENERGY_MAX - recipient.energy))
    if not gained or not recipient.alive or recipient is unit:
        return 0
    with battle._skill_effect(unit, recipient, 'energy', t, cast_index,
                              amount=gained, requested=requested):
        recipient.energy += gained
        battle._emit_state(recipient, t)
    from arena_offense import after_native_energy
    after_native_energy(battle, unit, recipient, gained, t, cast_index)
    from arena_bonds import after_native_support
    after_native_support(battle, unit, recipient, gained, 'energy', t, cast_index)
    from arena_equipment import after_native_energy as equipment_after_native_energy
    equipment_after_native_energy(battle, unit, recipient, gained, t, cast_index)
    return gained


def _major(patient, kinds=None):
    kind = getattr(getattr(patient, '_st', None), 'debuff', None)
    return kind is not None and (kinds is None or kind in kinds)


def _can_heal(battle, unit, patient, fraction, t):
    requested = max(0, int(patient.max_hp * fraction * unit.arena_heal_mult))
    return battle._healing_amount(patient, requested, t)[0] > 0


def _can_guard(patient, reduction, t):
    return patient.alive and (patient.temp_dr_until <= t + arena_fields.EPS
                             or patient.temp_dr < reduction)


def _support_targets(battle, unit, key, t):
    """Snapshot actual recipients; a full energy bar need not produce a cast.

    Support range is two cells independently of basic attack range. Heal-only
    skills hold energy while nobody can recover HP. Cleansing, shields, rescue
    and energy transfer each have their own useful-target test.
    """
    self_allowed = key in ('healing_song', 'cleansing_powder', 'moon_blessing', 'aroma_garden')
    friends = _allies(battle, unit, others=not self_allowed)
    health_key = lambda friend: (friend.hp / friend.max_hp, battle._target_key(unit, friend))
    if key in ('star_resonance', 'beacon_relay'):
        candidates = [friend for friend in friends if friend.energy < ENERGY_MAX]
        return sorted(candidates, key=lambda friend: (
            (0 if friend.arena_role == 'attack' else 1) if key == 'beacon_relay' else 0,
            -friend.energy, battle._target_key(unit, friend)))[:2]
    if key == 'watchful_lullaby':
        candidates = [friend for friend in friends
                      if _major(friend, {'sleep', 'para'}) or friend.energy < ENERGY_MAX]
        return sorted(candidates, key=lambda friend: (
            not _major(friend, {'sleep', 'para'}), -friend.energy,
            battle._target_key(unit, friend)))[:1]
    if key in ('moon_blessing', 'barrier_relay', 'frost_shelter'):
        fraction = .20 if key == 'moon_blessing' else .14
        candidates = [friend for friend in friends if arena_combinations.can_shield(
            friend, int(friend.max_hp * fraction), t)
            or key == 'barrier_relay' and _can_guard(friend, .20, t)
            or key == 'frost_shelter' and _major(friend, {'freeze'})]
        return sorted(candidates, key=lambda friend: (
            not (key == 'frost_shelter' and _major(friend, {'freeze'})),
            health_key(friend)))[:2 if key == 'frost_shelter' else 1]
    fractions = {'healing_song': .12, 'cleansing_powder': .15, 'aroma_garden': .10,
                 'rescue_tongue': .12, 'life_pulse': .25, 'bliss_chorus': .18,
                 'verdant_sanctuary': .12}
    cleanse_kinds = {'poison'} if key == 'aroma_garden' else None
    cleanser = key in ('cleansing_powder', 'aroma_garden', 'life_pulse', 'verdant_sanctuary')
    candidates = [friend for friend in friends
                  if _can_heal(battle, unit, friend, fractions[key], t)
                  or cleanser and _major(friend, cleanse_kinds)
                  or key == 'rescue_tongue' and friend.hp < friend.max_hp
                  and _pull_destination(battle, unit, friend) is not None]
    candidates.sort(key=lambda friend: (
        not (cleanser and _major(friend, cleanse_kinds)), health_key(friend)))
    return candidates[:2 if key in ('healing_song', 'aroma_garden', 'bliss_chorus',
                                    'verdant_sanctuary') else 1]


def _announce_cast(battle, unit, target, move, t):
    """A native support/stance/field cast is an action, never a friendly hit."""
    unit.energy, unit.casts = 0, unit.casts + 1
    cast_index = len(battle.events)
    battle.events.append((t, 'cast', unit.idx, target.idx, move['name'],
                          1., 0, unit.energy, target.energy))
    battle._emit_state(unit, t)
    if target is not unit:
        battle._emit_state(target, t)
    return cast_index


def _support_cast(battle, unit, skill, t):
    key = skill['id']
    patients = _support_targets(battle, unit, key, t)
    if not patients:
        return False
    target = patients[0]
    anchor = target.pos
    cast_index = _announce_cast(battle, unit, target, resolve_cast(unit.piece), t)
    heals, cleanses = [], []

    def cleanse(patient, kinds=None):
        kind = getattr(getattr(patient, '_st', None), 'debuff', None)
        if _cleanse(battle, unit, patient, t, cast_index, kinds):
            cleanses.append((patient, kind))

    fractions = {'healing_song': .12, 'cleansing_powder': .15, 'aroma_garden': .10,
                 'rescue_tongue': .12, 'life_pulse': .25, 'bliss_chorus': .18,
                 'verdant_sanctuary': .12}
    for patient in patients:
        if key in ('cleansing_powder', 'aroma_garden', 'life_pulse', 'verdant_sanctuary'):
            cleanse(patient, {'poison'} if key == 'aroma_garden' else None)
        if key in fractions:
            heals.append((patient, _heal(battle, unit, patient,
                                        patient.max_hp * fractions[key], t, cast_index)))
        if key == 'rescue_tongue':
            _pull(battle, unit, patient, t, cast_index)
        if key in ('moon_blessing', 'barrier_relay', 'frost_shelter'):
            if key == 'frost_shelter':
                cleanse(patient, {'freeze'})
            fraction = .20 if key == 'moon_blessing' else .14
            arena_combinations.grant_shield(battle, unit, patient,
                                            int(patient.max_hp * fraction), t, cast_index)
            if key == 'barrier_relay':
                _guard(battle, unit, patient, .20, t, cast_index)
        if key in ('star_resonance', 'beacon_relay', 'watchful_lullaby'):
            if key == 'watchful_lullaby':
                cleanse(patient, {'sleep', 'para'})
            amount = {'star_resonance': 18, 'beacon_relay': 14, 'watchful_lullaby': 16}[key]
            _energy(battle, unit, patient, amount, t, cast_index)
    battle._partner_after_cast(unit, target, t, anchor, False)
    battle._request_weather(unit, t, cast_index)
    # Finish every native shield first: an item must not claim a shield that
    # this same action immediately replaces with stronger native protection.
    for patient, kind in cleanses:
        arena_combinations.after_cleanse(battle, unit, patient, kind, t, cast_index)
        from arena_bonds import after_native_support
        after_native_support(battle, unit, patient, 1, 'cleanse', t, cast_index)
    arena_combinations.after_native(battle, unit, target, t, cast_index, False, 0, heals)
    from arena_traits import after_native_cast
    after_native_cast(battle, unit, t, cast_index)
    return True


def _stance_cast(battle, unit, skill, t):
    nearby = sorted((enemy for enemy in battle.units if enemy.alive
                     and enemy.team != unit.team and _distance(unit, enemy) <= 2),
                    key=lambda enemy: battle._target_key(unit, enemy))
    if not nearby:
        return False
    key = skill['id']
    eligible = [enemy for enemy in nearby if enemy.taunt_ready_at <= t + arena_fields.EPS]
    if key == 'flame_guard' and not eligible and not _can_guard(unit, .30, t):
        return False
    if key == 'venom_armor' and unit.thorns_until > t + arena_fields.EPS and unit.thorns_left:
        return False
    cast_index = _announce_cast(battle, unit, unit, resolve_cast(unit.piece), t)
    _guard(battle, unit, unit, .30 if key == 'flame_guard' else .25, t, cast_index)
    if key == 'flame_guard':
        for enemy in eligible[:2]:
            with battle._skill_effect(unit, enemy, 'taunt', t, cast_index,
                                      duration=2., expires_at=t + 2.):
                enemy.taunt_source_idx = unit.idx
                enemy.taunt_cast_index = cast_index
                enemy.taunt_until = t + 2.
                enemy.taunt_ready_at = t + 4.
                enemy.target_idx = unit.idx
                battle._emit_state(enemy, t)
    else:
        with battle._skill_effect(unit, unit, 'thorns', t, cast_index,
                                  uses=3, duration=3., expires_at=t + 3.):
            unit.thorns_left, unit.thorns_until = 3, t + 3.
            unit.thorns_cast_index = cast_index
            battle._emit_state(unit, t)
    from arena_traits import after_native_cast
    after_native_cast(battle, unit, t, cast_index)
    return True


def on_primary_damage(battle, patient, attacker, actual, t, action_index):
    """Poison spikes react to effective primary damage only, never recursively."""
    if (not battle._arena_on or actual <= 0 or not patient.alive or not attacker.alive
            or attacker.team == patient.team or patient.thorns_left <= 0
            or patient.thorns_until <= t + arena_fields.EPS or _distance(patient, attacker) > 2):
        return
    patient.thorns_left -= 1  # Spend before settlement; neither reflection nor DOT recurses.
    move = {**resolve_cast(patient.piece), 'type': 'POISON', 'power': 35}
    damage = battle._move_damage(patient, attacker, move)
    with battle._skill_effect(patient, attacker, 'thorn_hit', t, patient.thorns_cast_index,
                              source_cast_index=patient.thorns_cast_index,
                              action_index=action_index, damage=damage, move_type='POISON',
                              remaining=patient.thorns_left):
        battle._land_hit(patient, attacker, damage, t, move=move)
        if damage > 0:
            _poison(battle, patient, attacker, t, patient.thorns_cast_index,
                    action_index=action_index, source_cast_index=patient.thorns_cast_index)


def expire(battle, t):
    """Restore normal targeting and end stances; no late damage or cast occurs."""
    if not battle._arena_on:
        return
    for unit in battle.units:
        if unit.taunt_source_idx is not None:
            source = battle.units[unit.taunt_source_idx]
            if unit.taunt_until <= t + arena_fields.EPS or not source.alive:
                unit.taunt_until, unit.taunt_source_idx = 0., None
                # Discard only the forced lock. Other attack locks stay sticky.
                if unit.target_idx == source.idx:
                    unit.target_idx = None
        if unit.thorns_until and unit.thorns_until <= t + arena_fields.EPS:
            unit.thorns_until, unit.thorns_left = 0., 0


def cast(battle, unit, target, t):
    if not battle._arena_on or not unit.alive:
        return False
    from arena_actions import action
    with action(battle, unit, t, resolve_cast(unit.piece)):
        return _cast(battle, unit, target, t)


def _cast(battle, unit, target, t):
    """Resolve one native action; learned techniques retain their separate slot."""
    if not battle._arena_on or not unit.alive or unit.energy < ENERGY_MAX or status.stunned(unit, t):
        return False
    skill = skill_of(unit.piece.species_id)
    if skill['targeting'] == 'ally':
        return _support_cast(battle, unit, skill, t)
    if skill['targeting'] == 'self':
        return _stance_cast(battle, unit, skill, t)
    forced = (battle.units[unit.taunt_source_idx] if unit.taunt_source_idx is not None
              and unit.taunt_until > t + arena_fields.EPS else None)
    taunted = forced is not None and forced.alive
    if taunted:
        target = forced
    if target is None or not target.alive or target.team == unit.team or _distance(unit, target) > unit.range:
        return False
    key, move = skill['id'], resolve_cast(unit.piece)
    if skill['targeting'] == 'field':
        cast_index = _announce_cast(battle, unit, target, move, t)
        arena_fields.place_rocks(battle, unit, target, t, cast_index)
        battle._partner_after_cast(unit, target, t, target.pos, False)
        arena_combinations.after_native(battle, unit, target, t, cast_index, False, 0, [])
        from arena_traits import after_native_cast
        after_native_cast(battle, unit, t, cast_index)
        return True
    if key == 'shadow_siphon' and not taunted:
        candidates = [enemy for enemy in battle.units if enemy.alive
                      and enemy.team != unit.team and _distance(unit, enemy) <= unit.range]
        target = min(candidates, key=lambda enemy: (-enemy.energy, battle._target_key(unit, enemy)))
    if key == 'psychic_blink' and not taunted:
        weakest = min((enemy for enemy in battle.units if enemy.alive and enemy.team != unit.team),
                      key=lambda enemy: (enemy.hp, battle._target_key(unit, enemy)), default=None)
        if weakest is not None:
            destination = battle._free_cell_near(weakest.pos, avoid=unit.pos, team=unit.team)
            if destination is not None:
                arena_fields.move_unit(battle, unit, destination, t, source=unit, reason='blink')
                if not unit.alive:
                    return True
                target, unit.target_idx = weakest, weakest.idx
    if target.item_dodge > 0:
        dodge_roll = battle.rng.random()
        if dodge_roll < target.item_dodge:
            from arena_traits import prevent_dodge
            if not prevent_dodge(battle, unit, target, dodge_roll, t):
                battle.events.append((t, 'miss', unit.idx, target.idx))
                return True
    anchor = target.pos
    from arena_traits import sheer_force_applies
    suppress_secondary = sheer_force_applies(battle, unit, move)
    already_poisoned = getattr(getattr(target, '_st', None), 'debuff', None) == 'poison'
    prior_status = getattr(getattr(target, '_st', None), 'debuff', None)
    already_controlled = prior_status in ('para', 'freeze') or getattr(target, 'root_until', 0) > t
    already_vulnerable = getattr(target, 'vulnerable_until', 0.) > t + arena_fields.EPS
    already_wounded = target.hp / target.max_hp <= .35
    already_spiked = key == 'crag_citadel' and any(
        field['team'] == unit.team and field['expires_at'] > t + arena_fields.EPS
        and anchor in field['cells'] for field in getattr(battle, 'rock_fields', []))
    # New support targets and every conditional bonus are snapshotted before
    # the primary hit; effects created by this action cannot activate themselves.
    gen2_allies = _allies(battle, unit, others=True) if key == 'moon_guard' else []
    line = battle._line_victims(unit, target) if key in ('twin_cannon', 'dragon_crosscurrent') else []
    unit.energy, unit.casts = 0, unit.casts + 1
    damage = battle._move_damage(unit, target, move)
    cast_index = len(battle.events)
    lost_hp = battle._land_hit(unit, target, damage, t, move=move, primary=True, cast=True)
    from arena_equipment import after_native_hit
    after_native_hit(battle, unit, target, t, cast_index, lost_hp)
    from arena_interactions import after_primary
    after_primary(battle, unit, target, move, lost_hp, t, cast_index)
    if not unit.alive:
        # A stance reaction may defeat the caster during its primary hit.
        # Only that already settled hit survives; no new follow-up is launched.
        return True
    heals = []

    def heal(patient, amount):
        heals.append((patient, _heal(battle, unit, patient, amount, t, cast_index)))

    if key == 'spark_chain' and damage > 0:
        previous, struck = target, {target.idx}
        for hop, fraction in enumerate((.55, .35), 1):
            candidates = [enemy for enemy in battle.units if enemy.alive and enemy.team != unit.team
                          and enemy.idx not in struck and _distance(previous, enemy) <= 2]
            victim = min(candidates, key=lambda enemy: (_distance(previous, enemy),
                         battle._target_key(unit, enemy)), default=None)
            if victim is None:
                break
            struck.add(victim.idx)
            actual = _side_hit(battle, unit, victim, move, fraction, t, cast_index, previous, hop=hop)
            if not actual:
                break
            previous = victim
    elif key == 'four_arm_combo' and damage > 0:
        for strike in range(2):
            _side_hit(battle, unit, target, move, .30, t, cast_index, strike=strike + 1)
        _knockback(battle, unit, target, t, cast_index)
    elif key == 'venom_rush' and damage > 0 and not suppress_secondary:
        if already_poisoned:
            _side_hit(battle, unit, target, move, .40, t, cast_index)
        _poison(battle, unit, target, t, cast_index)
    elif key == 'shadow_siphon' and damage > 0:
        _drain(battle, unit, target, 20, t, cast_index, transfer=True)
    elif key in ('flame_storm', 'venom_tide'):
        for victim in _near_enemies(battle, unit, anchor, target):
            _side_hit(battle, unit, victim, move, .50 if key == 'flame_storm' else .40, t, cast_index)
    elif key == 'stone_pulse':
        victims = [target] + _near_enemies(battle, unit, unit.pos, target)
        for victim in victims:
            actual = lost_hp if victim is target else _side_hit(battle, unit, victim, move, .40, t, cast_index)
            if actual > 0 and victim.alive:
                with battle._skill_effect(unit, victim, 'flinch', t, cast_index, duration=.3):
                    status.apply_flinch(battle, victim, t)
    elif key == 'twin_cannon':
        for victim in line:
            _side_hit(battle, unit, victim, move, .45, t, cast_index)
        if damage > 0:
            _knockback(battle, unit, target, t, cast_index)
    elif key == 'slow_field':
        for victim in [target] + _near_enemies(battle, unit, anchor, target):
            _drain(battle, unit, victim, 15, t, cast_index)
    elif key in ('sweeping_kick', 'bull_rush', 'cliff_swoop'):
        if damage > 0:
            _knockback(battle, unit, target, t, cast_index)
        if key == 'cliff_swoop':
            arena_fields.clear_near(battle, unit, t, cast_index, limit=1)
    elif key == 'root_domain' and lost_hp:
        arena_fields.apply_root(battle, unit, target, t, cast_index)
    elif key == 'armor_pincer' and lost_hp:
        arena_fields.apply_vulnerability(battle, unit, target, t, cast_index)
    elif key == 'storm_conductor' and prior_status == 'para' and damage > 0:
        for victim in _near_enemies(battle, unit, anchor, target):
            _side_hit(battle, unit, victim, move, .35, t, cast_index)
    elif key == 'gale_cross' and already_controlled and damage > 0:
        _side_hit(battle, unit, target, move, .35, t, cast_index)
    elif key == 'alert_tail' and lost_hp and already_wounded:
        _side_hit(battle, unit, target, move, .60, t, cast_index)
    elif key == 'toxic_spines' and lost_hp:
        _poison(battle, unit, target, t, cast_index)
        for victim in _near_enemies(battle, unit, anchor, target)[:1]:
            if _side_hit(battle, unit, victim, move, .30, t, cast_index) > 0:
                _poison(battle, unit, victim, t, cast_index)
    elif key == 'mud_anchor' and lost_hp:
        arena_fields.apply_root(battle, unit, target, t, cast_index)
    elif key == 'spinning_cleanup':
        if lost_hp:
            for victim in _near_enemies(battle, unit, unit.pos, target)[:1]:
                _side_hit(battle, unit, victim, move, .35, t, cast_index)
        arena_fields.clear_near(battle, unit, t, cast_index, limit=3)
    elif key == 'charged_beacon' and lost_hp and prior_status == 'para':
        candidates = [enemy for enemy in battle.units if enemy.alive
                      and enemy.team != unit.team and enemy is not target
                      and abs(enemy.pos[0] - anchor[0]) + abs(enemy.pos[1] - anchor[1]) <= 2]
        victim = min(candidates, key=lambda enemy: (
            abs(enemy.pos[0] - anchor[0]) + abs(enemy.pos[1] - anchor[1]),
            battle._target_key(unit, enemy)), default=None)
        if victim is not None:
            _side_hit(battle, unit, victim, move, .60, t, cast_index, target)
    elif key == 'fracture_vision' and lost_hp and already_vulnerable:
        _side_hit(battle, unit, target, move, .50, t, cast_index)
    elif key == 'horn_pressure' and lost_hp:
        if already_controlled:
            _side_hit(battle, unit, target, move, .35, t, cast_index)
        arena_fields.apply_vulnerability(battle, unit, target, t, cast_index)
    elif key == 'moon_guard' and lost_hp:
        _drain(battle, unit, target, 10, t, cast_index)
    elif key == 'iron_fault' and lost_hp:
        _knockback(battle, unit, target, t, cast_index)
    elif key == 'cinder_eruption' and lost_hp:
        for victim in _near_enemies(battle, unit, anchor, target):
            _side_hit(battle, unit, victim, move, .65 if prior_status == 'burn' else .45, t, cast_index)
    elif key == 'cross_bullet' and lost_hp:
        for strike in range(2):
            _side_hit(battle, unit, target, move, .35 if already_vulnerable else .20,
                      t, cast_index, strike=strike + 1)
    elif key == 'dragon_crosscurrent' and lost_hp:
        dragon_move = {**move, 'type': 'DRAGON'}
        for victim in line:
            _side_hit(battle, unit, victim, dragon_move, .50, t, cast_index)
    elif key == 'undertow_lock' and lost_hp:
        if already_controlled:
            _knockback(battle, unit, target, t, cast_index)
        else:
            arena_fields.apply_root(battle, unit, target, t, cast_index)
    elif key == 'crag_citadel' and lost_hp:
        if already_spiked:
            _knockback(battle, unit, target, t, cast_index)
        else:
            arena_fields.place_rocks(battle, unit, target, t, cast_index)

    guards = {'stone_pulse': .25, 'venom_tide': .20, 'twin_cannon': .20,
              'slow_field': .30, 'bull_rush': .20, 'mud_anchor': .25,
              'spinning_cleanup': .20, 'moon_guard': .25, 'iron_fault': .30,
              'undertow_lock': .25, 'crag_citadel': .25}
    if key in guards:
        _guard(battle, unit, unit, guards[key], t, cast_index)
    if key == 'solar_relay' and lost_hp:
        friends = _allies(battle, unit, wounded=True)
        if friends:
            heal(friends[0], lost_hp * .35)
    if key == 'moon_guard' and gen2_allies:
        _guard(battle, unit, gen2_allies[0], .20, t, cast_index)
    battle._partner_after_cast(unit, target, t, anchor, damage > 0)
    battle._request_weather(unit, t, cast_index)
    arena_combinations.after_native(battle, unit, target, t, cast_index,
                                    already_poisoned, lost_hp, heals)
    from arena_traits import after_native_cast
    after_native_cast(battle, unit, t, cast_index)
    return True
