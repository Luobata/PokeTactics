"""Save-free arena encounters for the same presentation used by the trial."""
import copy
import random

SCENARIOS = {
    'arena_bond_erosion': {
        'label': '基础羁绊 · 侵蚀消耗', 'exp': 'combinations',
        'description': '尼多后、千针鱼、尼多王与毒刺水母组成4侵蚀；无装备、教学和海克斯，观察真实毒伤回能。',
        'a': (31, 73, 34, 211, 40, 12), 'b': (76, 195, 68, 26, 40, 108)},
    'arena_bond_combo': {
        'label': '基础羁绊 · 连击成长', 'exp': 'combinations',
        'description': '雷丘、怪力、尼多王与大尾立组成4连击；低费搭档持续普攻积累速度，不依赖节拍器或指定海克斯。',
        'a': (76, 68, 34, 162, 26, 40), 'b': (31, 195, 76, 211, 40, 108)},
    'arena_bond_guard': {
        'label': '基础羁绊 · 守护续战', 'exp': 'combinations',
        'description': '尼多后、隆隆岩、风速狗与皮可西组成4守护；低血量自盾争取反击和援护时间，无装备与海克斯。',
        'a': (31, 76, 59, 26, 36, 40), 'b': (68, 195, 76, 211, 26, 40)},
    'arena_bond_inspiration': {
        'label': '基础羁绊 · 鼓舞援护', 'exp': 'combinations',
        'description': '胖可丁、巴大蝶、猫头夜鹰与电灯怪组成4鼓舞；全部1费，治疗、净化或本命回能可带来增伤窗口。',
        'a': (76, 68, 40, 12, 164, 171), 'b': (31, 76, 68, 211, 26, 108)},
    'arena_trait_sustain': {
        'label': '特性与装备 · 四臂续战', 'exp': 'combinations',
        'description': '怪力携汲取之牙，以真实普攻自疗；皮可西加盾、胖可丁治疗，观察固定特性与续航装备的独立归因。',
        'a': (76, 68, 31, 6, 36, 40), 'b': (128, 195, 208, 242, 26, 113),
        'items_a': ('tide_shell', 'drain_fang', 'leftovers', 'torrent_orb', 'focus_lens', 'heart_bell'),
        'items_b': ('leftovers', 'leftovers', 'leftovers', 'focus_lens', 'grounding_cloak', 'leftovers')},
    'arena_trait_cadence': {
        'label': '特性与装备 · 四臂脉冲', 'exp': 'combinations',
        'description': '同一怪力改用脉冲腕带；飞腿郎逐风鸣铃把真实击退变成队友回能，电灯怪本命援护另有独立触发。',
        'a': (76, 31, 68, 106, 171, 40), 'b': (76, 195, 31, 40, 113, 242),
        'items_a': ('leftovers', 'leftovers', 'pulse_band', 'storm_chime', 'relay_coil', 'focus_lens'),
        'items_b': ('leftovers', 'leftovers', 'leftovers', 'leftovers', 'leftovers', 'leftovers')},
    'arena_trait_relay': {
        'label': '特性与装备 · 星光护电', 'exp': 'combinations',
        'description': '宝石海星接力线圈把本命真实他人回能接成护盾；风速狗承伤，胡地收割，装备回能不冒充本命链。',
        'a': (59, 208, 68, 65, 121, 171), 'b': (128, 195, 76, 242, 211, 113),
        'items_a': ('ward_bracer', 'leftovers', 'drain_fang', 'grounding_cloak', 'relay_coil', 'focus_lens'),
        'items_b': ('leftovers', 'leftovers', 'leftovers', 'focus_lens', 'contagion_orb', 'leftovers')},
    'arena_trait_mending': {
        'label': '特性与装备 · 歌声甘露', 'exp': 'combinations',
        'description': '胖可丁和幸福蛋携甘露坠饰，以真实本命治疗接到第三位受伤队友；被击退前排用潮汐甲壳争取续战时间。',
        'a': (76, 68, 31, 6, 40, 242), 'b': (128, 9, 208, 26, 34, 113),
        'items_a': ('tide_shell', 'drain_fang', 'leftovers', 'torrent_orb', 'dew_charm', 'dew_charm'),
        'items_b': ('leftovers', 'focus_lens', 'leftovers', 'grounding_cloak', 'pulse_band', 'leftovers')},
    'arena_nidoking_poison': {
        'label': '尼多王分支 · 毒刺扩散', 'exp': 'combinations',
        'description': '同一尼多王选择毒刺、扩散宝珠与污泥弹，靠自己施加的毒伤归属做消耗；与强行生命之玉场景比较取舍。',
        'a': (195, 34, 131, 6, 12, 36), 'b': (128, 195, 76, 242, 40, 197),
        'traits_a': (None, 'trait_poison_point', None, None, None, None),
        'items_a': ('leftovers', 'contagion_orb', 'leftovers', 'torrent_orb', 'focus_lens', 'focus_lens'),
        'items_b': ('leftovers', 'leftovers', 'leftovers', 'leftovers', 'leftovers', 'leftovers'),
        'learned_a': ('rest', 'toxic', 'rest', 'rest', 'rest', 'rest')},
    'arena_nidoking_force': {
        'label': '尼多王分支 · 强行生命之玉', 'exp': 'combinations',
        'description': '相同阵容的尼多王改选强行、生命之玉与冰冻光束，舍弃自己铺毒与毒角条件追击；适用强行动作免反噬，普攻仍有生命代价。',
        'a': (195, 34, 131, 6, 12, 36), 'b': (128, 195, 76, 242, 40, 197),
        'traits_a': (None, 'trait_sheer_force', None, None, None, None),
        'items_a': ('leftovers', 'life_orb', 'leftovers', 'torrent_orb', 'focus_lens', 'focus_lens'),
        'items_b': ('leftovers', 'leftovers', 'leftovers', 'leftovers', 'leftovers', 'leftovers'),
        'learned_a': ('rest', 'ice_beam', 'rest', 'rest', 'rest', 'rest')},
    'arena_rain_conduct': {
        'label': '雨电体系 · 湿润导流', 'exp': 'combinations',
        'description': '水箭龟铺湿润并求雨，雷丘学习打雷，刺龙王雨中加速；另一队员电主命中同一湿润目标后返能给水来源。',
        'a': (9, 59, 76, 230, 26, 171), 'b': (128, 197, 59, 242, 40, 113),
        'traits_a': ('trait_rain_dish', None, None, None, None, None),
        'items_a': ('focus_lens', 'leftovers', 'leftovers', 'torrent_orb', 'scarf_electric', 'relay_coil'),
        'items_b': ('leftovers', 'leftovers', 'leftovers', 'leftovers', 'leftovers', 'leftovers'),
        'learned_a': ('rain_dance', None, None, 'surf', 'thunder', None)},
    'arena_water_bloom': {
        'label': '水草体系 · 湿润滋养', 'exp': 'combinations',
        'description': '水箭龟先以水主命中挂湿润，妙蛙花或蔓藤怪随后草主命中同一目标，额外治疗草手附近伤员；反应治疗不继续触发本命治疗链。',
        'a': (9, 76, 31, 3, 114, 242), 'b': (128, 197, 59, 211, 40, 113),
        'items_a': ('focus_lens', 'leftovers', 'leftovers', 'dew_charm', 'torrent_orb', 'heart_bell'),
        'items_b': ('leftovers', 'leftovers', 'leftovers', 'contagion_orb', 'leftovers', 'leftovers'),
        'learned_a': ('rain_dance', None, None, 'rest', None, 'rest')},
    'arena_weather_contest': {
        'label': '阴晴争夺 · 全场天气覆盖', 'exp': 'combinations',
        'description': '双方分别学习求雨与晴天，共享全场天气；观察合法施法后的申请、生效、覆盖和到期，无额外天气手指定。',
        'a': (9, 76, 34, 26, 230, 171), 'b': (59, 208, 68, 6, 3, 242),
        'items_a': ('damp_rock', 'leftovers', 'drain_fang', 'focus_lens', 'torrent_orb', 'focus_lens'),
        'items_b': ('leftovers', 'leftovers', 'drain_fang', 'heat_rock', 'dew_charm', 'focus_lens'),
        'learned_a': ('rain_dance', None, None, None, 'surf', None),
        'learned_b': (None, None, None, 'sunny_day', 'rest', None)},
    'arena_solar_growth': {
        'label': '晴草体系 · 叶绿素反哺', 'exp': 'combinations',
        'description': '喷火龙学习晴天并携炽热岩石，妙蛙花晴中行动加速；原生草伤反哺队友，甘露只跟随达标本命治疗。',
        'a': (59, 76, 68, 6, 3, 113), 'b': (128, 197, 59, 211, 40, 113),
        'items_a': ('leftovers', 'leftovers', 'drain_fang', 'heat_rock', 'dew_charm', 'heart_bell'),
        'items_b': ('leftovers', 'leftovers', 'leftovers', 'contagion_orb', 'leftovers', 'leftovers'),
        'learned_a': (None, None, 'rest', 'sunny_day', 'rest', 'rest')},
    'arena_showcase': {
        'label': '分件动作 · 四臂 / 双炮 / 双钳', 'exp': 'motion',
        'description': '怪力、巨钳螳螂、雷丘与御三家同场，观察关节、弹道与命中。',
        'a': (68, 9, 212, 26, 3, 65), 'b': (248, 208, 160, 181, 154, 242)},
    'arena_rocks': {
        'label': '岩钉与击退 · 区域联动', 'exp': 'terrain',
        'description': '大岩蛇铺岩钉，怪力和水箭龟击退；对手有清场与治疗。',
        'a': (95, 68, 9, 106, 40, 26), 'b': (208, 237, 128, 131, 171, 142)},
    'arena_status': {
        'label': '异常与追击 · 毒 / 电 / 控制', 'exp': 'status',
        'description': '毒针铺毒、毒角追击与电流连锁，对抗净化与保护。',
        'a': (31, 114, 34, 211, 125, 162), 'b': (197, 195, 212, 12, 113, 122)},
    'arena_elements': {
        'label': '属性特效 · 火 / 水 / 草 / 冰', 'exp': 'effects',
        'description': '一二世代交叉对战，观察不同属性的蓄力、飞行与落点。',
        'a': (59, 9, 160, 6, 157, 3), 'b': (248, 76, 73, 230, 154, 131)},
    'arena_support': {
        'label': '治疗与防守 · 保护链', 'exp': 'support',
        'description': '前排消耗与后排治疗；生命、护盾和能量变化来自真实战斗。',
        'a': (31, 59, 80, 40, 121, 242), 'b': (208, 197, 68, 196, 164, 171)},
    'arena_shield_branches': {
        'label': '护盾分支 · 反击 / 回流', 'exp': 'combinations',
        'description': '皮可西单盾、拉普拉斯群盾保护持腕前排；观察实际吸收、强化普攻和施盾者回能。',
        'a': (59, 68, 208, 36, 131, 121), 'b': (9, 76, 214, 26, 6, 113),
        'items_a': ('ward_bracer', 'ward_bracer', 'leftovers', 'focus_lens', 'focus_lens', 'leftovers'),
        'augments_a': ('mana_flow', 'barrier_feedback'), 'augments_b': ('mana_flow', 'sharp_focus')},
    'arena_cleanse_branches': {
        'label': '净化分支 · 解控 / 保护', 'exp': 'combinations',
        'description': '巴大蝶、大竺葵与猫头夜鹰的不同净化能力对抗异常；清明坠饰只在真正解除队友异常后给盾。',
        'a': (59, 208, 68, 12, 164, 154), 'b': (31, 211, 34, 125, 94, 181),
        'items_a': ('leftovers', 'leftovers', 'ward_bracer', 'clarity_charm', 'clarity_charm', 'clarity_charm'),
        'augments_a': ('mana_flow', 'barrier_feedback'), 'augments_b': ('mana_flow', 'poison_catalyst')},
    'arena_breach_branches': {
        'label': '击退分支 · 岩钉 / 易伤集火', 'exp': 'combinations',
        'description': '水箭龟、大钢蛇和吼叫推阵；乘隙追击制造易伤，巨钳螳螂与太阳伊布利用施法顺序追击。',
        'a': (9, 208, 95, 212, 196, 121), 'b': (128, 76, 195, 40, 6, 242),
        'items_a': ('leftovers', 'leftovers', 'focus_lens', 'choice_band', 'focus_lens', 'leftovers'),
        'learned_a': ('rapid_spin', None, 'roar', None, None, None),
        'augments_a': ('mana_flow', 'breach_momentum'), 'augments_b': ('mana_flow', 'iron_wall')},
    'arena_attack_attrition': {
        'label': '进攻分支 · 异常扩散', 'exp': 'combinations',
        'description': '喷火龙与尼多王携带扩散宝珠；先由自身铺异常，再等待真实跳伤与邻格传播，辅助保护来源。',
        'a': (195, 34, 131, 6, 12, 36), 'b': (128, 195, 76, 242, 40, 197),
        'items_a': ('leftovers', 'contagion_orb', 'leftovers', 'contagion_orb', 'focus_lens', 'focus_lens'),
        'items_b': ('leftovers', 'leftovers', 'leftovers', 'leftovers', 'leftovers', 'leftovers'),
        'learned_a': ('rest', 'toxic', 'rest', 'rest', 'rest', 'rest'),
        'augments_a': ('mana_flow', 'vitality'), 'augments_b': ('vitality', 'iron_wall')},
    'arena_attack_growth': {
        'label': '进攻分支 · 连击成长', 'exp': 'combinations',
        'description': '喷火龙、尼多王和巨钳螳螂使用节拍器；观察同目标普攻积层，以及换目标或断档后的清层。',
        'a': (59, 34, 212, 6, 36, 121), 'b': (128, 195, 76, 242, 40, 197),
        'items_a': ('leftovers', 'metronome', 'metronome', 'metronome', 'focus_lens', 'focus_lens'),
        'items_b': ('leftovers', 'leftovers', 'leftovers', 'leftovers', 'leftovers', 'leftovers'),
        'learned_a': ('rest', 'rest', 'rest', 'rest', 'rest', 'rest'),
        'augments_a': ('mana_flow', 'vitality'), 'augments_b': ('vitality', 'iron_wall')},
    'arena_attack_inspiration': {
        'label': '进攻分支 · 充能爆发', 'exp': 'combinations',
        'description': '相同攻击核心换用爆发装备；宝石海星和电灯怪提供真实本命回能，充能鼓舞创造3秒增伤窗口。',
        'a': (59, 34, 212, 6, 121, 171), 'b': (128, 195, 76, 242, 40, 197),
        'items_a': ('leftovers', 'focus_lens', 'choice_band', 'focus_lens', 'focus_lens', 'focus_lens'),
        'items_b': ('leftovers', 'leftovers', 'leftovers', 'leftovers', 'leftovers', 'leftovers'),
        'learned_a': ('rest', 'earthquake', 'cut', 'cut', 'rest', 'rest'),
        'augments_a': ('mana_flow', 'native_inspiration'), 'augments_b': ('vitality', 'iron_wall')},
}


def make_scene(seed=7, scenario=None):
    from arena import build_templates
    from combat import Battle
    from decoders import Front, Palettes, Font16
    from render_battle_gif import BattleAnimation
    key = scenario or 'arena_showcase'
    if key not in SCENARIOS:
        raise ValueError('未知竞技场景')
    scene, templates = SCENARIOS[key], build_templates()
    def side(key):
        equipment = scene.get('items_' + key, (None,) * len(scene[key]))
        if len(equipment) != len(scene[key]):
            raise ValueError('场景装备与阵容数量不匹配')
        choices = scene.get('traits_' + key, (None,) * len(scene[key]))
        if len(choices) != len(scene[key]):
            raise ValueError('场景特性与阵容数量不匹配')
        from arena_traits import validate_choice
        result = []
        for sid, item, choice in zip(scene[key], equipment, choices):
            piece = copy.copy(templates[sid])
            piece.arena_trait_key = validate_choice(sid, choice)
            result.append((piece, item) if item else piece)
        return result
    a, b = side('a'), side('b')
    # Three front-line spaces, one middle and two back-line spaces on each side.
    cells = ((1, 3), (3, 3), (5, 3), (1, 4), (3, 5), (5, 5))
    battle = Battle(a, b, random.Random(seed), ruleset='arena_v1', stat_mode='budget_v1',
                    positions_a=list(cells), positions_b=[(5-x, 5-y) for x, y in cells],
                    learned_a=list(scene['learned_a']) if 'learned_a' in scene else None,
                    learned_b=list(scene['learned_b']) if 'learned_b' in scene else None,
                    arena_teams=[list(scene.get('augments_a', ())), list(scene.get('augments_b', ()))])
    battle.run()
    return BattleAnimation(a, b, seed, Front(), Palettes(), Font16(), battle=battle)
