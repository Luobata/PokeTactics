"""Hoenn-first family combat identities.

The species dictionaries are deliberately separate from the frozen species_v1
registries.  ``effect`` names the already-settled arena mechanic, while each
species keeps a distinct native move identity and power budget.
"""

ROLES = {
    252: 'attack', 253: 'attack', 254: 'attack',
    255: 'attack', 256: 'attack', 257: 'attack',
    258: 'defense', 259: 'defense', 260: 'defense',
    270: 'support', 271: 'support', 272: 'support',
    280: 'support', 281: 'support', 282: 'support',
    285: 'attack', 286: 'attack',
    304: 'defense', 305: 'defense', 306: 'defense',
    333: 'support', 334: 'support',
    349: 'attack', 350: 'support',
    359: 'attack',
    371: 'attack', 372: 'attack', 373: 'attack',
    374: 'defense', 375: 'defense', 376: 'defense',
}

# Existing targeting/category contracts used by the renderer and native caster.
_EFFECT_IDENTITIES = {
    'cross_bullet': ('enemy', 'combo', '连击破甲'),
    'flame_storm': ('enemy', 'area', '范围轰炸'),
    'four_arm_combo': ('enemy', 'combo', '多段击退'),
    'twin_cannon': ('enemy', 'displacement', '贯穿击退'),
    'mud_anchor': ('enemy', 'root', '定身阻截'),
    'dragon_vein': ('ally', 'energy', '治疗回能'),
    'star_resonance': ('ally', 'energy', '能量补给'),
    'bliss_chorus': ('ally', 'heal', '群体急救'),
    'watchful_lullaby': ('ally', 'cleanse', '解控回能'),
    'barrier_relay': ('ally', 'guard', '屏障减伤'),
    'moon_blessing': ('ally', 'shield', '单体护盾'),
    'venom_rush': ('enemy', 'poison', '毒伤追击'),
    'iron_fault': ('enemy', 'displacement', '重甲击退'),
    'gale_cross': ('enemy', 'pursuit', '控制追击'),
    'fracture_vision': ('enemy', 'pursuit', '易伤追击'),
    'cliff_swoop': ('enemy', 'clear', '击退清场'),
    'dragon_dive': ('enemy', 'burst', '高威俯冲'),
}


def _skill(sid, effect, name, move_type, power, role, tags, description):
    targeting, category, behavior = _EFFECT_IDENTITIES[effect]
    return dict(id=f'hoenn_{effect}_{sid}', effect=effect, name=name, type=move_type,
                power=power, role=role, targeting=targeting, category=category,
                behavior=behavior, tags=tags, description=description)


GEN3_SKILLS = {
    252: _skill(252, 'cross_bullet', '新芽连射', 'GRASS', 45, 'attack', ['连击', '成长'],
                '连续射出两轮新芽攻击主目标；目标已有易伤时连击更具威胁。'),
    253: _skill(253, 'cross_bullet', '叶刃双斩', 'GRASS', 55, 'attack', ['连击', '叶刃'],
                '以两段叶刃斩击主目标；对已有易伤的目标造成更高追击。'),
    254: _skill(254, 'cross_bullet', '疾风叶刃', 'GRASS', 70, 'attack', ['连击', '收割'],
                '高速叶刃连续斩击主目标，能利用易伤状态打出成段伤害。'),
    255: _skill(255, 'flame_storm', '雏火飞散', 'FIRE', 40, 'attack', ['范围', '火苗'],
                '攻击主目标，火星波及目标旁一名敌人。'),
    256: _skill(256, 'cross_bullet', '双爪火舞', 'FIGHTING', 55, 'attack', ['连击', '双属性'],
                '利爪与火焰节奏交错，连续两段攻击主目标。'),
    257: _skill(257, 'four_arm_combo', '烈焰爆连踢', 'FIRE', 75, 'attack', ['连击', '击退'],
                '以火焰连踢攻击主目标并追加两段打击，命中后尝试击退。'),
    258: _skill(258, 'twin_cannon', '细流贯穿', 'WATER', 40, 'defense', ['贯穿', '防守'],
                '水流贯穿前方敌人并尝试击退目标，自身获得短时减伤。'),
    259: _skill(259, 'mud_anchor', '泥沼锚定', 'GROUND', 50, 'defense', ['定身', '减伤'],
                '泥流攻击主目标并使其定身，自身获得短时减伤。'),
    260: _skill(260, 'twin_cannon', '潮泥重炮', 'WATER', 65, 'defense', ['贯穿', '击退'],
                '重水流沿直线贯穿多名敌人，击退主目标并获得短时减伤。'),
    270: _skill(270, 'dragon_vein', '雨露接力', 'WATER', 0, 'support', ['治疗', '回能'],
                '为附近最需要的友军回复生命并补充能量。'),
    271: _skill(271, 'star_resonance', '水草共鸣', 'GRASS', 0, 'support', ['回能', '节奏'],
                '为附近能量最高的两名友军补充施法能量。'),
    272: _skill(272, 'bliss_chorus', '欢雨庆典', 'WATER', 0, 'support', ['群体治疗', '雨天'],
                '为附近最虚弱的受伤友军连续回复生命。'),
    280: _skill(280, 'watchful_lullaby', '心铃安抚', 'PSYCHIC', 0, 'support', ['解控', '回能'],
                '优先解除附近友军的睡眠或麻痹，并为其补充能量。'),
    281: _skill(281, 'barrier_relay', '心弦屏障', 'PSYCHIC', 0, 'support', ['护盾', '减伤'],
                '为最虚弱的友军提供护盾和短时减伤。'),
    282: _skill(282, 'moon_blessing', '圣洁守护', 'PSYCHIC', 0, 'support', ['保护', '守护'],
                '为附近最虚弱的友军提供一层较厚的守护护盾。'),
    285: _skill(285, 'venom_rush', '孢子喷射', 'GRASS', 40, 'attack', ['中毒', '追击'],
                '喷射孢子攻击主目标并尝试使其中毒；对已中毒目标追加伤害。'),
    286: _skill(286, 'cross_bullet', '孢子拳连打', 'FIGHTING', 60, 'attack', ['连击', '控制'],
                '蘑菇孢子与拳法交错，连续攻击主目标。'),
    304: _skill(304, 'iron_fault', '铁头初撞', 'STEEL', 40, 'defense', ['击退', '减伤'],
                '用铁头攻击并尝试击退目标，自身获得短时减伤。'),
    305: _skill(305, 'iron_fault', '钢甲冲撞', 'STEEL', 50, 'defense', ['击退', '减伤'],
                '钢甲冲撞主目标并击退，自身获得较强减伤。'),
    306: _skill(306, 'iron_fault', '巨金重压', 'STEEL', 65, 'defense', ['击退', '阵地'],
                '巨甲重压主目标并击退，自身获得短时高减伤。'),
    333: _skill(333, 'moon_blessing', '云羽摇篮', 'FLYING', 0, 'support', ['护盾', '轻羽'],
                '用云羽为最虚弱友军提供守护护盾。'),
    334: _skill(334, 'bliss_chorus', '云龙圣歌', 'DRAGON', 0, 'support', ['群体治疗', '云海'],
                '以圣歌为附近至多两名受伤友军回复生命。'),
    349: _skill(349, 'gale_cross', '搁浅扑击', 'WATER', 25, 'attack', ['低费', '扑击'],
                '笨拙地扑击主目标；目标受控时能勉强追击一次。'),
    350: _skill(350, 'bliss_chorus', '鳞光抚流', 'WATER', 0, 'support', ['群体治疗', '优雅'],
                '鳞光流水为附近至多两名受伤友军回复生命。'),
    359: _skill(359, 'fracture_vision', '灾厄预兆', 'DARK', 70, 'attack', ['易伤追击', '爆发'],
                '攻击主目标；目标已有易伤时追加一次预兆斩击。'),
    371: _skill(371, 'cliff_swoop', '龙头冲撞', 'DRAGON', 45, 'attack', ['击退', '清场'],
                '以坚硬头部冲撞目标并尝试击退，同时清理附近岩钉。'),
    372: _skill(372, 'cliff_swoop', '硬壳突击', 'ROCK', 55, 'attack', ['击退', '清场'],
                '硬壳突击目标并尝试击退，可扫除自身附近岩钉。'),
    373: _skill(373, 'dragon_dive', '流星俯冲', 'DRAGON', 85, 'attack', ['高威爆发', '击退'],
                '以流星般的俯冲击打主目标，命中后尝试击退。'),
    374: _skill(374, 'iron_fault', '磁浮撞击', 'STEEL', 35, 'defense', ['击退', '减伤'],
                '磁力推进撞击目标并尝试击退，自身获得短时减伤。'),
    375: _skill(375, 'iron_fault', '钳臂震退', 'STEEL', 50, 'defense', ['击退', '减伤'],
                '钳臂重击目标并击退，自身获得短时减伤。'),
    376: _skill(376, 'iron_fault', '陨铁重拳', 'STEEL', 70, 'defense', ['击退', '阵地'],
                '四臂合击目标并击退，自身获得短时高减伤。'),
}

# Public name used by presentation and data importers.
SKILLS = GEN3_SKILLS


def _trait(effect, name, category, trigger, tags, description, **fields):
    return {'id': effect, 'name': name, 'category': category,
            'cooldown': fields.pop('cooldown', 0.), 'limit': fields.pop('limit', None),
            'trigger': trigger, 'tags': tags, 'description': description, **fields}


# Each entry names the Hoenn ability adaptation and reuses its settled hook.
GEN3_TRAITS = {
    252: _trait('trait_overgrow', '茂盛', 'attack', '生命不高于三分之一时的草属性直接命中',
                ['低血量', '草'], '生命不高于三分之一时，草属性直接命中伤害提高25%。', cooldown=3., limit=3, fraction=.25),
    253: _trait('trait_overgrow', '茂盛', 'attack', '生命不高于三分之一时的草属性直接命中',
                ['低血量', '草'], '生命不高于三分之一时，草属性直接命中伤害提高25%。', cooldown=3., limit=3, fraction=.25),
    254: _trait('trait_overgrow', '茂盛', 'attack', '生命不高于三分之一时的草属性直接命中',
                ['低血量', '草'], '生命不高于三分之一时，草属性直接命中伤害提高25%。', cooldown=3., limit=3, fraction=.25),
    255: _trait('trait_blaze', '猛火', 'attack', '生命不高于三分之一时的火属性直接命中',
                ['低血量', '火'], '生命不高于三分之一时，火属性直接命中伤害提高25%。', cooldown=3., limit=3, fraction=.25),
    256: _trait('trait_blaze', '猛火', 'attack', '生命不高于三分之一时的火属性直接命中',
                ['低血量', '火'], '生命不高于三分之一时，火属性直接命中伤害提高25%。', cooldown=3., limit=3, fraction=.25),
    257: _trait('trait_blaze', '猛火', 'attack', '生命不高于三分之一时的火属性直接命中',
                ['低血量', '火'], '生命不高于三分之一时，火属性直接命中伤害提高25%。', cooldown=3., limit=3, fraction=.25),
    258: _trait('trait_torrent', '激流', 'defense', '生命不高于一半时的水属性直接命中',
                ['低血量', '水'], '生命不高于一半时，水属性直接命中伤害提高15%。', cooldown=3., limit=3, fraction=.15),
    259: _trait('trait_torrent', '激流', 'defense', '生命不高于一半时的水属性直接命中',
                ['低血量', '水'], '生命不高于一半时，水属性直接命中伤害提高15%。', cooldown=3., limit=3, fraction=.15),
    260: _trait('trait_torrent', '激流', 'defense', '生命不高于一半时的水属性直接命中',
                ['低血量', '水'], '生命不高于一半时，水属性直接命中伤害提高15%。', cooldown=3., limit=3, fraction=.15),
    270: _trait('trait_rain_dish', '雨盘', 'support', '竞技雨天中每两秒', ['雨天', '自疗'],
                '竞技雨天中每两秒回复3%最大生命，实际回复才消耗次数。', cooldown=2., limit=6, fraction=.03),
    271: _trait('trait_rain_dish', '雨盘', 'support', '竞技雨天中每两秒', ['雨天', '自疗'],
                '竞技雨天中每两秒回复3%最大生命，实际回复才消耗次数。', cooldown=2., limit=6, fraction=.03),
    272: _trait('trait_swift_swim', '悠游自如', 'support', '竞技雨天持续期间', ['雨天', '行动加速'],
                '竞技雨天中行动速度提高25%，天气结束立即停止。', fraction=.25, weather='rain'),
    280: _trait('trait_synchronize', '同步', 'support', '自己被敌人成功施加新的主要异常',
                ['异常', '反弹'], '被敌人施加新的主要异常时，若条件允许则反弹同种异常。', cooldown=5., limit=2),
    281: _trait('trait_synchronize', '同步', 'support', '自己被敌人成功施加新的主要异常',
                ['异常', '反弹'], '被敌人施加新的主要异常时，若条件允许则反弹同种异常。', cooldown=5., limit=2),
    282: _trait('trait_synchronize', '同步', 'support', '自己被敌人成功施加新的主要异常',
                ['异常', '反弹'], '被敌人施加新的主要异常时，若条件允许则反弹同种异常。', cooldown=5., limit=2),
    285: _trait('trait_effect_spore', '孢子', 'attack', '邻格敌人普攻造成实际生命损失',
                ['受击', '睡眠'], '受到邻格敌人有效普攻后，尝试使其睡眠。', cooldown=6., limit=2),
    286: _trait('trait_effect_spore', '孢子', 'attack', '邻格敌人普攻造成实际生命损失',
                ['受击', '睡眠'], '受到邻格敌人有效普攻后，尝试使其睡眠。', cooldown=6., limit=2),
    304: _trait('trait_sturdy', '结实', 'defense', '满生命遭受直接命中的致命生命伤害',
                ['保命'], '满生命时遭受直接致命伤害保留1生命，每战一次。', limit=1),
    305: _trait('trait_sturdy', '结实', 'defense', '满生命遭受直接命中的致命生命伤害',
                ['保命'], '满生命时遭受直接致命伤害保留1生命，每战一次。', limit=1),
    306: _trait('trait_sturdy', '结实', 'defense', '满生命遭受直接命中的致命生命伤害',
                ['保命'], '满生命时遭受直接致命伤害保留1生命，每战一次。', limit=1),
    333: _trait('trait_natural_cure', '自然回复', 'support', '成功完成本命施法且自己仍有主要异常',
                ['施法', '自净化'], '完成本命施法后清除自身一个主要异常。', cooldown=4., limit=2),
    334: _trait('trait_natural_cure', '自然回复', 'support', '成功完成本命施法且自己仍有主要异常',
                ['施法', '自净化'], '完成本命施法后清除自身一个主要异常。', cooldown=4., limit=2),
    349: _trait('trait_swift_swim', '悠游自如', 'attack', '竞技雨天持续期间', ['雨天', '行动加速'],
                '竞技雨天中行动速度提高25%，天气结束立即停止。', fraction=.25, weather='rain'),
    350: _trait('trait_spin_guard', '神秘鳞片', 'defense', '邻格敌人普攻造成实际生命损失',
                ['受击', '护盾'], '受到邻格有效普攻后获得6%最大生命护盾。', cooldown=4., limit=3, fraction=.06),
    359: _trait('trait_pressure', '压迫感', 'attack', '开战时两格内最近两名敌人',
                ['开局', '控能'], '开战时使附近至多两名敌人各失去至多6能量。', limit=1),
    371: _trait('trait_sturdy', '坚硬脑袋', 'defense', '满生命遭受直接命中的致命生命伤害',
                ['保命', '撞击'], '满生命时用坚硬头部扛下直接致命伤害并保留1生命。', limit=1),
    372: _trait('trait_sturdy', '坚硬脑袋', 'defense', '满生命遭受直接命中的致命生命伤害',
                ['保命', '撞击'], '满生命时用坚硬头部扛下直接致命伤害并保留1生命。', limit=1),
    373: _trait('trait_intimidate', '威吓', 'attack', '开战时两格内最近两名敌人',
                ['开局', '物理压制'], '开战时降低附近至多两名敌人的物理直接伤害。', limit=1, fraction=.10),
    374: _trait('trait_clear_body', '净体', 'defense', '开战时被敌方威吓类特性选中',
                ['开局', '抗压制'], '被开战威吓类效果选中时，抵挡该次削弱。', limit=1),
    375: _trait('trait_clear_body', '净体', 'defense', '开战时被敌方威吓类特性选中',
                ['开局', '抗压制'], '被开战威吓类效果选中时，抵挡该次削弱。', limit=1),
    376: _trait('trait_clear_body', '净体', 'defense', '开战时被敌方威吓类特性选中',
                ['开局', '抗压制'], '被开战威吓类效果选中时，抵挡该次削弱。', limit=1),
}

# Only tactical bonds whose trigger the corresponding native kit can actually
# participate in.  Elemental bonds are derived from types elsewhere.
BONDS = {
    **{sid: ('bond_combo',) for sid in (252, 253, 254, 255, 256, 257, 285, 286)},
    **{sid: ('bond_guard',) for sid in (258, 259, 260, 304, 305, 306, 374, 375, 376)},
    **{sid: ('bond_inspiration',) for sid in (270, 271, 272, 280, 281, 282, 333, 334, 350)},
}
