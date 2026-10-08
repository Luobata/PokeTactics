"""Read-only build checks and actual arena combination telemetry."""

import arena_skills
import arena_traits
from items import FINISHED
import status

NAMES = {'poison_catalyst': '毒性催化', 'heart_bell': '护心铃', 'watch_echo': '守望回响',
         'ward_bracer': '守势护腕', 'clarity_charm': '清明坠饰',
         'barrier_feedback': '屏障回流', 'breach_momentum': '乘隙追击',
         'contagion_orb': '扩散宝珠', 'metronome': '节拍器',
         'native_inspiration': '充能鼓舞', 'bond_erosion': '侵蚀羁绊',
         'bond_combo': '连击羁绊', 'bond_guard': '守护羁绊',
         'bond_inspiration': '鼓舞羁绊', 'element_wet': '湿润铺垫',
         'element_conduct': '水电导流', 'element_bloom': '水草滋养',
         'arena_weather': '天气争夺', 'life_orb': FINISHED['life_orb']['name']}
GEAR_KEYS = ('drain_fang', 'tide_shell', 'dew_charm', 'torrent_orb', 'pulse_band',
             'relay_coil', 'grounding_cloak', 'storm_chime')
NAMES.update({key: FINISHED[key]['name'] for key in GEAR_KEYS})
NAMES.update({row['id']: row['name'] for row in arena_traits.catalog()})
NATIVE_CLEANSERS = {12, 45, 113, 154, 164}
NATIVE_SHIELDERS = {36, 122, 131}
NATIVE_HEALERS = {40, 12, 45, 3, 108, 113, 242, 154}
CHECK_NAMES = {**NAMES, 'rock_displacement': '岩钉推阵', 'root_pursuit': '束缚收割',
               'paralysis_conductor': '麻痹导流',
               'native_guard': '本命护盾掩护', 'native_healing': '本命治疗续航',
               'native_energy': '本命充能接力', 'native_poison': '本命铺毒消耗',
               'arena_rain': '雨天阵容', 'arena_sun': '晴天阵容',
               'nidoking_force': '强行生命之玉'}
BASE_CHECKS = {'rock_displacement', 'root_pursuit', 'paralysis_conductor',
               'native_guard', 'native_healing', 'native_energy', 'native_poison',
               'element_conduct', 'element_bloom'}
AUGMENT_CHECKS = {'poison_catalyst', 'watch_echo', 'barrier_feedback',
                  'breach_momentum', 'native_inspiration'}


def preparation(session):
    player = session.player
    deployed = list(player.grid.items())
    selected = {value['id'] if isinstance(value, dict) else value
                for value in player.arena_augments_selected}

    def distance(a, b):
        return abs(a[0] - b[0]) + abs(a[1] - b[1])

    def stocked(key):
        inventory = getattr(player, 'inventory', None)
        return key in getattr(inventory, 'finished', ())

    def can_cleanse_pair(giver, recipient):
        if giver is recipient or giver.piece.species_id not in NATIVE_CLEANSERS:
            return False
        skill = arena_skills.SKILLS[giver.piece.species_id]
        kinds = {'aroma_garden': ('poison',),
                 'watchful_lullaby': ('sleep', 'para')}.get(
                     skill['id'], status.DEBUFF_BY_SRC.values())
        return any(not set(recipient.piece.types).intersection(status.IMMUNE_TYPES.get(kind, ()))
                   for kind in kinds)

    def can_shield_pair(giver, recipient):
        if giver is recipient:
            return giver.piece.species_id == 36
        return (giver.piece.species_id in NATIVE_SHIELDERS
                or giver.item == 'heart_bell' and giver.piece.species_id in NATIVE_HEALERS
                or giver.item == 'clarity_charm' and can_cleanse_pair(giver, recipient))

    def nearby(pos, owned, role=None):
        return [(other_pos, friend) for other_pos, friend in deployed
                if friend is not owned and distance(pos, other_pos) <= 2
                and (role is None or getattr(friend.piece, 'role_key', None) == role)]

    def trait_of(owned):
        return arena_traits.for_species(owned.piece.species_id, getattr(owned, 'arena_trait', None))

    def force_selected(owned):
        trait = trait_of(owned)
        return bool(trait and trait['id'] == 'trait_sheer_force')

    def entry(key, detail, missing, units):
        seen = set()
        refs = []
        for owned in units:
            if owned.uid not in seen:
                seen.add(owned.uid)
                refs.append({'uid': owned.uid, 'name': owned.piece.name})
        return {'id': key, 'name': CHECK_NAMES[key],
                'stage': 'base' if key in BASE_CHECKS or key.startswith('trait_') else 'upgrade',
                'requires_augment': key in AUGMENT_CHECKS,
                'status': 'missing' if missing else 'ready',
                'detail': detail, 'missing': missing, 'units': refs,
                'present': ['已上场：' + row['name'] for row in refs],
                'battle_conditions': [], 'conflicts': []}

    poisoners = [owned for _, owned in deployed
                 if (owned.piece.species_id in (31, 34, 211) or owned.technique == 'toxic')
                 and not force_selected(owned)]
    native_damage_dealers = [owned for _, owned in deployed
                             if arena_skills.SKILLS.get(owned.piece.species_id, {}).get('targeting') == 'enemy'
                             and arena_skills.SKILLS[owned.piece.species_id]['power'] > 0]
    missing = []
    if 'poison_catalyst' not in selected:
        missing.append('尚未选择毒性催化海克斯')
    if not poisoners:
        missing.append('上场尼多王、尼多后、千针鱼，或给上场队员学习污泥弹来铺毒')
    if not native_damage_dealers:
        missing.append('上场至少一位原生技能直接攻击敌人的伤害手，反击、治疗和护盾不能触发催化')
    entries = [entry('poison_catalyst',
        '先让目标中毒，再由原生技能主命中造成实际生命损失，施法者获得 8 能量；每只最多 3 次。',
        missing, poisoners + native_damage_dealers)]

    equipped = [(pos, owned) for pos, owned in deployed if owned.item == 'heart_bell']
    healers = [(pos, owned) for pos, owned in equipped if owned.piece.species_id in NATIVE_HEALERS]
    pairs = [(owned, friend) for pos, owned in healers for _, friend in nearby(pos, owned)]
    missing = []
    if not equipped:
        hint = ('已有护心铃，将它装备给上场辅助' if stocked('heart_bell')
                else '用两个贝壳铃合成护心铃，或从回合战利品获得，再装备给上场辅助')
        missing.append(hint)
    elif not healers:
        missing.append('将护心铃换给拥有原生治疗的上场辅助')
    if healers and not pairs:
        missing.append('在携带者两格内部署另一位队友')
    entries.append(entry('heart_bell',
        '原生技能对其他队友的实际回复达到其最大生命的 5%，为一位队友提供 8% 护盾、持续 3 秒；携带者冷却 4 秒。',
        missing, [unit for pair in pairs for unit in pair] or [owned for _, owned in healers]))

    healers = [(pos, owned) for pos, owned in deployed if owned.piece.species_id in NATIVE_HEALERS]
    pairs = [(owned, carry) for pos, owned in healers
             for _, carry in nearby(pos, owned, 'attack')]
    missing = []
    if 'watch_echo' not in selected:
        missing.append('尚未选择守望回响海克斯')
    if not healers:
        missing.append('上场一位有原生治疗的辅助')
    elif not pairs:
        missing.append('在辅助两格内部署攻击型队友')
    entries.append(entry('watch_echo',
        '辅助原生技能有效治疗其他队友后，为附近未满能量、能量最高的攻击型队友补 8 能量；每名辅助最多 3 次。',
        missing, [unit for pair in pairs for unit in pair]))
    layers = [owned for _, owned in deployed if owned.piece.species_id in (95, 248)]
    pushers = [owned for _, owned in deployed
               if owned.piece.species_id in (68, 9, 106, 128, 142, 208, 160, 248) or owned.technique == 'roar']
    missing = ([] if layers else ['上场大岩蛇或班基拉斯铺设岩钉']) + ([] if pushers else ['上场击退伙伴，或给相容队员学习吼叫'])
    entries.append(entry('rock_displacement',
        '先铺岩钉，再把敌人推入区域；入格岩伤随属性克制变化，厚底靴和高速旋转可反制。铺场与击退的朝向、顺序仍决定是否触发。',
        missing, layers + pushers))
    blades = [owned for _, owned in deployed if owned.piece.species_id in (123, 214)]
    controllers = [owned for _, owned in deployed if owned.piece.species_id in (114, 26, 125, 195, 160)
                   or owned.technique in ('ice_beam', 'thunderbolt', 'thunder') and not force_selected(owned)]
    missing = ([] if blades else ['上场飞天螳螂或赫拉克罗斯利用控制追击']) + ([] if controllers else ['上场蔓藤怪或沼王，或用相容技能机铺控制'])
    entries.append(entry('root_pursuit',
        '施法前目标已定身、冰冻或麻痹，飞天螳螂或赫拉克罗斯追加35%追击；技能机可铺垫条件，净化冰冻与麻痹、分散目标可应对。',
        missing, blades + controllers))
    conductors = [owned for _, owned in deployed if owned.piece.species_id in (125, 181)]
    primers = [owned for _, owned in deployed if owned.piece.species_id in (26, 125)
               or owned.technique in ('thunderbolt', 'thunder') and not force_selected(owned)]
    missing = ([] if conductors else ['上场电击兽或电龙']) + ([] if primers else ['上场雷丘，或给相容队员学习十万伏特来尝试麻痹'])
    entries.append(entry('paralysis_conductor',
        '先麻痹主目标，再由电击兽向至多两名邻格敌人导流，或由电龙向两格内一名敌人追加电击；麻痹概率、属性免疫、净化和站位都影响结果。',
        missing, conductors + primers))
    ward_holders = [(pos, owned) for pos, owned in deployed if owned.item == 'ward_bracer']
    ward_pairs = [(holder, giver) for pos, holder in ward_holders for other_pos, giver in deployed
                  if distance(pos, other_pos) <= 2 and can_shield_pair(giver, holder)]
    missing = []
    if not ward_holders:
        missing.append('将守势护腕装备给上场前排' if stocked('ward_bracer') else
                       '用力量头带与加速鞋合成守势护腕，或从回合战利品获得，再装备给上场前排')
    if ward_holders and not ward_pairs:
        missing.append('在护腕携带者两格内安排皮可西、拉普拉斯、魔墙人偶，或能生成护盾的道具辅助')
    entries.append(entry('ward_bracer',
        '一个连续护盾周期实吸达到携带者最大生命8%后，蓄力4秒，下次有效普攻伤害翻倍；冷却4秒、每战最多3次。防守型持腕保命反击，攻击型持腕提高普攻压力。',
        missing, [unit for pair in ward_pairs for unit in pair] or [owned for _, owned in ward_holders]))

    charm_holders = [(pos, owned) for pos, owned in deployed if owned.item == 'clarity_charm']
    cleansers = [(pos, owned) for pos, owned in charm_holders
                if owned.piece.species_id in NATIVE_CLEANSERS]
    cleanse_pairs = [(cleanser, friend) for pos, cleanser in cleansers
                     for _, friend in nearby(pos, cleanser) if can_cleanse_pair(cleanser, friend)]
    missing = []
    if not charm_holders:
        missing.append('将清明坠饰装备给上场净化手' if stocked('clarity_charm') else
                       '用贝壳铃与木炭合成清明坠饰，或从回合战利品获得，再装备给上场净化手')
    elif not cleansers:
        missing.append('清明坠饰需要真正能净化队友的原生技能；改给巴大蝶、大竺葵或猫头夜鹰等净化手')
    if cleansers and not cleanse_pairs:
        missing.append('在净化手两格内部署能承受其可移除异常的另一名队友；霸王花只解毒，毒/钢系队友不会中毒')
    entries.append(entry('clarity_charm',
        '原生技能成功净化其他友军后，给患者8%最大生命护盾3秒；每次施法最多一人，冷却4秒、每战最多3次。巴大蝶单净化、大竺葵群净化、猫头夜鹰只解睡眠/麻痹并回能。',
        missing, [unit for pair in cleanse_pairs for unit in pair] or [owned for _, owned in cleansers]))

    shield_pairs = [(giver, friend) for pos, giver in deployed for _, friend in nearby(pos, giver)
                    if can_shield_pair(giver, friend)]
    missing = [] if 'barrier_feedback' in selected else ['尚未选择屏障回流海克斯']
    if not shield_pairs:
        missing.append('让两格内的其他队友能获得护盾：上场皮可西、拉普拉斯、魔墙人偶，或带护心铃/清明坠饰的相应辅助；净化护盾需队友能承受可移除的异常，自己给自己的盾不回流')
    entries.append(entry('barrier_feedback',
        '给其他队友的盾实吸达到患者最大生命5%，原施盾者实际获得至多8能量；每盾一次，施盾者冷却4秒、每战最多3次。减伤盾、单盾和双人盾的覆盖与回流节奏不同。',
        missing, [unit for pair in shield_pairs for unit in pair]))

    breach_pushers = [owned for _, owned in deployed
                      if owned.piece.species_id in (68, 9, 106, 128, 142, 208, 160, 248)
                      or owned.technique == 'roar']
    breach_finishers = [owned for _, owned in deployed if owned.piece.species_id in (212, 196)]
    missing = [] if 'breach_momentum' in selected else ['尚未选择乘隙追击海克斯']
    if not breach_pushers:
        missing.append('上场水箭龟、大钢蛇、飞腿郎等击退手，或给相容队员学习吼叫')
    if not breach_finishers:
        missing.append('上场巨钳螳螂或太阳伊布，衔接施法前已有易伤的追击')
    entries.append(entry('breach_momentum',
        '成功把存活敌人推开后，使其受到的攻击伤害提高12%共4秒；推动者冷却4秒、每战最多3次。追击核心需要随后攻击同一目标，边界/被占落点不产生易伤。',
        missing, breach_pushers + breach_finishers))
    contagion_holders = [owned for _, owned in deployed if owned.item == 'contagion_orb']
    dot_holders = [owned for owned in contagion_holders if not force_selected(owned) and (owned.technique == 'toxic'
                   or owned.piece.species_id == 31
                   or (arena_skills.SKILLS.get(owned.piece.species_id, {}).get('targeting') == 'enemy'
                       and arena_skills.SKILLS[owned.piece.species_id]['type'] in ('FIRE', 'POISON')))]
    missing = []
    if not contagion_holders:
        missing.append('将扩散宝珠装备给上场火/毒伤害手' if stocked('contagion_orb') else
                       '用加速鞋与木炭合成扩散宝珠，或从回合战利品获得，再交给上场火/毒伤害手')
    elif not dot_holders:
        missing.append('携带者需能亲自施加灼伤或中毒；改给喷火龙/尼多王等，或为相容携带者学习污泥弹')
    entries.append(entry('contagion_orb',
        '同一存活敌人受到携带者归属的3次真实灼伤/毒跳伤后，向其邻格一名空主要异常槽且非免疫的敌人传播。携带者冷却4秒、每战最多2次，每个原目标仅一次；传播产生的异常不再传播。',
        missing, dot_holders or contagion_holders))

    tempo_holders = [owned for _, owned in deployed if owned.item == 'metronome']
    missing = [] if tempo_holders else [
        '将节拍器装备给上场持续普攻核心' if stocked('metronome') else
        '用两个力量头带合成节拍器，或从回合战利品获得，再装备给上场持续普攻核心']
    entries.append(entry('metronome',
        '对同一敌人的每次有效生命普攻增加15%攻速，最多3层45%，影响攻击和施法行动间隔。普攻转火或4秒没有有效生命普攻就清层；纯吸盾、闪避、技能机、原生技能和DOT不增层。',
        missing, tempo_holders))

    donors = [(pos, owned) for pos, owned in deployed if owned.piece.species_id in (121, 171, 164)]
    inspiration_pairs = [(donor, friend) for pos, donor in donors for _, friend in nearby(pos, donor)]
    missing = [] if 'native_inspiration' in selected else ['尚未选择充能鼓舞海克斯']
    if not donors:
        missing.append('上场宝石海星、电灯怪或猫头夜鹰，提供本命技能回能')
    elif not inspiration_pairs:
        missing.append('在充能辅助两格内安排另一位队友，留出实际回能与直接攻击窗口')
    entries.append(entry('native_inspiration',
        '收到其他队友本命技能实际回能后，受益队员3秒直接攻击伤害+25%；受益队员冷却5秒、每战最多3次，不叠加。普攻、原生/学习技能及直接反击可受益，DOT和岩钉不强化，联动回能与自回能不触发。',
        missing, [unit for pair in inspiration_pairs for unit in pair]))
    native_shield_pairs = [(giver, friend) for pos, giver in deployed
                           if giver.piece.species_id in NATIVE_SHIELDERS
                           for _, friend in nearby(pos, giver)]
    entries.append(entry('native_guard',
        '皮可西、拉普拉斯或魔墙人偶用本命护盾保护两格内队友；不要求装备和海克斯。护盾覆盖与承伤时机由站位决定。',
        [] if native_shield_pairs else ['上场本命施盾伙伴，并在其两格内部署另一位队友'],
        [unit for pair in native_shield_pairs for unit in pair]))
    native_heal_pairs = [(giver, friend) for pos, giver in deployed
                        if giver.piece.species_id in NATIVE_HEALERS
                        for _, friend in nearby(pos, giver)]
    entries.append(entry('native_healing',
        '本命治疗给附近受伤队友续航；不要求护心铃、守望回响或急救花园。队友满血时不产生有效治疗。',
        [] if native_heal_pairs else ['上场本命治疗伙伴，并在其两格内部署可救援队友'],
        [unit for pair in native_heal_pairs for unit in pair]))
    entries.append(entry('native_energy',
        '宝石海星、电灯怪或猫头夜鹰以本命技能给两格内未满能量队友充能；猫头夜鹰还需有可净化或可充能目标。不要求充能鼓舞。',
        [] if inspiration_pairs else ['上场本命充能伙伴，并在其两格内部署另一位队友'],
        [unit for pair in inspiration_pairs for unit in pair]))
    native_poisoners = [owned for _, owned in deployed
                       if owned.piece.species_id in (31, 34, 211) and not force_selected(owned)]
    entries.append(entry('native_poison',
        '尼多后受击反毒、尼多王或千针鱼本命施毒，先建立中毒消耗；尼多王还能追击施法前已中毒目标。不要求毒性催化或扩散宝珠。毒/钢免疫、异常槽和真实命中仍限制施毒。',
        [] if native_poisoners else ['上场尼多王、尼多后或千针鱼建立本命铺毒'], native_poisoners))
    for pos, owned in deployed:
        trait = trait_of(owned)
        if trait:
            row = entry(trait['id'], trait['description'], [], [owned])
            row.update(stage='trait', source_kind='trait',
                       fixed=len(arena_traits.options_for(owned.piece.species_id)) == 1,
                       present=['已选择：' + owned.piece.name + ' · ' + trait['name']],
                       battle_conditions=[trait['trigger']], configuration_only=True)
            if trait['id'] == 'trait_guts' and owned.item == 'grounding_cloak':
                row['conflicts'].append('接地斗篷立即净化睡眠、麻痹或冰冻，会关闭这次毅力窗口；它不解除中毒或灼伤。')
            if trait['id'] == 'trait_sheer_force' and owned.item == 'contagion_orb':
                row['conflicts'].append('强行删除本命和适用技能机施毒，自己无法为扩散宝珠建立毒伤归属；切换毒刺或换输出装备。')
            entries.append(row)
    gear_details = {
        'drain_fang': '真实生命普攻后自疗，必须自己受伤；技能追击和纯吸盾不会触发。',
        'tide_shell': '被敌方真实击退且存活才给自己护盾，普移、友军拉回与堵路都不触发。',
        'dew_charm': '本命他疗达患者最大生命5%后，治疗患者两格内另一位受伤队友；装备产物不继续接本命链。',
        'torrent_orb': '本命攻击主命中真正扣除生命后自回能，反击、侧击、技能机和DOT不触发。',
        'pulse_band': '三次有效生命普攻转成自回能，技能多段、追击与纯吸盾不凑次数。',
        'relay_coil': '本命实际给其他队友回能后为其加盾，满能量、更强盾和装备回能不触发。',
        'grounding_cloak': '实际睡眠、麻痹或冰冻后立即自净化一次，不能清中毒/灼伤或代替团队净化。',
        'storm_chime': '自己真正击退存活敌人后给附近另一未满能量队友回能，边界与堵路不触发。',
    }
    for key in GEAR_KEYS:
        equipped = [(pos, owned) for pos, owned in deployed if owned.item == key]
        if not equipped:
            continue
        missing = []
        if key == 'dew_charm':
            healers = [(pos, owned) for pos, owned in equipped if owned.piece.species_id in NATIVE_HEALERS]
            triples = [(giver, patient, other) for pos, giver in healers
                       for patient_pos, patient in nearby(pos, giver)
                       for _, other in nearby(patient_pos, patient) if other is not giver]
            if not healers:
                missing.append('换给能本命治疗其他队友的上场精灵')
            elif not triples:
                missing.append('施疗者两格内安排患者，患者两格内再安排另一位队友')
        elif key == 'torrent_orb' and not any(owned in native_damage_dealers for _, owned in equipped):
            missing.append('换给本命直接攻击敌人的精灵；纯援护、姿态和铺场不触发')
        elif key == 'relay_coil':
            chargers = [(pos, owned) for pos, owned in equipped if owned.piece.species_id in (121, 171, 164)]
            if not chargers:
                missing.append('换给宝石海星、电灯怪或猫头夜鹰的本命充能')
            elif not any(nearby(pos, owned) for pos, owned in chargers):
                missing.append('在本命充能者两格内安排另一位队友')
        elif key == 'storm_chime':
            movers = [(pos, owned) for pos, owned in equipped if owned.piece.species_id in (68, 9, 106, 128, 142, 208, 160, 248) or owned.technique == 'roar']
            if not movers:
                missing.append('携带者需要本命击退或学习吼叫')
            elif not any(nearby(pos, owned) for pos, owned in movers):
                missing.append('在击退手两格内安排另一位队友')
        row = entry(key, gear_details[key], missing, [owned for _, owned in equipped])
        row.update(stage='upgrade', source_kind='item')
        entries.append(row)
    wet_sources = [owned for _, owned in deployed
                   if (arena_skills.SKILLS.get(owned.piece.species_id, {}).get('type') == 'WATER'
                       and owned in native_damage_dealers) or owned.technique == 'surf']
    electric = [owned for _, owned in deployed
                if (arena_skills.SKILLS.get(owned.piece.species_id, {}).get('type') == 'ELECTRIC'
                    and owned in native_damage_dealers) or owned.technique in ('thunder', 'thunderbolt')]
    grass = [owned for _, owned in deployed
             if arena_skills.SKILLS.get(owned.piece.species_id, {}).get('type') == 'GRASS'
             and owned in native_damage_dealers]
    for key, consumers, detail in (
            ('element_conduct', electric, '另一名同队电系主命中消耗同一敌人的湿润，为原水手补至多8能量；不是普通麻痹导流。'),
            ('element_bloom', grass, '另一名同队草系主命中消耗同一敌人的湿润，为草手两格内生命比例最低的伤员回复6%最大生命。')):
        pairs = [(source, consumer) for source in wet_sources for consumer in consumers if source is not consumer]
        missing = ([] if wet_sources else ['上场本命水攻击手，或给相容队员学习冲浪'])
        if not consumers:
            missing.append('上场电攻击手或学习打雷 / 十万伏特' if key == 'element_conduct' else '上场妙蛙花或蔓藤怪等本命草攻击手')
        elif not pairs:
            missing.append('湿润来源和反应触发者须是两位不同队员')
        row = entry(key, detail, missing, [unit for pair in pairs for unit in pair] or wet_sources + consumers)
        row.update(source_kind='reaction', battle_conditions=[
            '水主命中先造成实际生命损失；同一存活敌人的湿润平时4秒、雨天6秒。',
            '水来源、触发者与敌人须存活；后续电 / 草主命中也须造成实际生命损失。',
            '水来源未满能量才导流；草手附近有伤员且实际治疗成功才滋养。',
            '每名反应触发者冷却4秒，每战最多3次；一次湿润只能被一条反应消耗，产物不递归。'],
            conflicts=['电与草竞争同一湿润；更早命中的伙伴会决定本次导流或滋养。'])
        entries.append(row)
    rain = [owned for _, owned in deployed if owned.technique == 'rain_dance']
    sun = [owned for _, owned in deployed if owned.technique == 'sunny_day']
    for key, holders, label, item, effect in (
            ('arena_rain', rain, '求雨', 'damp_rock', '水直接伤害×1.15、火×0.9；打雷必中，雨盘回复与悠游自如加速。'),
            ('arena_sun', sun, '晴天', 'heat_rock', '火直接伤害×1.15、水×0.9；叶绿素加速，强化火攻并压低对方水伤。')):
        if not holders and not any(trait_of(owned) and trait_of(owned)['id'] in (
                ('trait_rain_dish', 'trait_swift_swim') if key == 'arena_rain' else ('trait_chlorophyll',))
                for _, owned in deployed):
            continue
        row = entry(key, effect, [] if holders else ['给上场相容队员学习' + label], holders)
        row.update(source_kind='weather', battle_conditions=[
            '天气学习者成功完成第一次本命后申请，下一战斗步生效；天气占用每场一次的学习位。',
            '基础12秒，申请者携对应岩石为16秒；同天气申请不续时，后来的异天气覆盖，结束不恢复旧天气。'],
            conflicts=['双方共享天气；队内晴雨同一战斗步申请会抵消为无天气，敌方相同属性也会受益。'],
            present=['已上场：' + owned.piece.name + ' · ' + label + (' · 天气岩石' if owned.item == item else '') for owned in holders])
        entries.append(row)
    nidokings = [owned for _, owned in deployed if owned.piece.species_id == 34]
    if nidokings:
        ready = [owned for owned in nidokings if force_selected(owned) and owned.item == 'life_orb']
        missing = ([] if any(force_selected(owned) for owned in nidokings) else ['在尼多王详情中免费切换为强行'])
        if not ready:
            missing.append('给同一强行尼多王装备生命之玉（木炭×2）')
        row = entry('nidoking_force', '强行放弃自己施毒和已中毒40%追击，强化适用本命或技能机；生命之玉再提高直接输出，适用强行动作免反噬。', missing, nidokings)
        row.update(source_kind='build', battle_conditions=[
            '强行仅适用毒角突袭、十万伏特、冰冻光束、污泥弹、打雷；不强化普攻、DOT、岩钉和援护。',
            '生命之玉普攻及其他不适用强行的直接进攻仍每完整动作反噬5%最大生命，绕过护盾且可能自倒。'],
            conflicts=['强行与毒刺互斥；单装备位不能同时携生命之玉与扩散宝珠，放弃自身施毒传播。'])
        entries.append(row)
    return {'entries': entries,
            'note': '配置已具备不等于本轮必触发。特性按个体选择检查，天气双方共享；基础配合、装备、学习位和海克斯分别列出缺少组件。实际收益仍取决于同目标命中、实际生命损失、有效治疗、站位、天气与对手免疫。吼叫 / 高速旋转 / 打雷的等待上限为6秒，非法击退落点仍不会消耗次数。'}


def battle_summary(events, teams, team=0):
    """Count one team's actual values; annotations are never a second hit."""
    rows = {}
    counters = ('triggers', 'energy', 'shield', 'absorbed', 'charges', 'damage',
                'damage_absorbed', 'vulnerable', 'spreads', 'tempo_stacks', 'offense_buffs',
                'healing', 'cleanses', 'statuses', 'mitigated', 'accuracy_saves', 'weakens')
    for event in events:
        if event[1] != 'combo_effect' or len(event) != 7 or event[4] not in NAMES:
            continue
        _, _, caster, _, key, effect, payload = event
        # Self-cost is not opposing damage or a positive combination benefit.
        # Guard annotations too, so future recoil packet shapes cannot leak in.
        if payload.get('recoil') or payload.get('damage_scope') == 'self_cost':
            continue
        # Feedback originates at the struck patient; energy belongs to the
        # original shield provider. Both are allies in a valid current replay.
        owner = (payload.get('source_idx', caster) if key == 'barrier_feedback' else
                 payload.get('recipient_idx', event[3]) if key in ('native_inspiration', 'bond_inspiration') else caster)
        if teams.get(owner) != team:
            continue
        if effect not in ('energy', 'shield', 'absorb', 'charge', 'empowered_basic', 'vulnerability',
                          'spread', 'tempo', 'offense_buff', 'heal', 'cleanse', 'status',
                          'guard', 'absorb_damage', 'accuracy', 'weaken', 'empowered_hit'):
            continue
        if effect == 'spread' and payload.get('applied') is not True:
            continue
        if effect == 'tempo' and payload.get('gained', 0) <= 0:
            continue
        if effect == 'status' and payload.get('applied') is not True:
            continue
        if effect == 'accuracy' and payload.get('saved_dodge') is not True:
            continue
        if effect == 'heal' and payload.get('amount', 0) <= 0:
            continue
        if effect in ('guard', 'absorb_damage') and max(payload.get('amount', 0), payload.get('prevented', 0), payload.get('avoided_shield_absorption', 0)) <= 0:
            continue
        row = rows.setdefault(key, {'id': key, 'name': NAMES[key],
                                    **dict.fromkeys(counters, 0)})
        amount = max(0, int(payload.get('amount', 0)))
        if effect in ('energy', 'shield'):
            row['triggers'] += 1
            row[effect] += amount
        elif effect == 'absorb':
            row['absorbed'] += amount
        elif effect == 'charge':
            row['charges'] += 1
        elif effect in ('empowered_basic', 'empowered_hit'):
            row['triggers'] += 1
            row['damage'] += max(0, int(payload.get('extra_damage', amount)))
            row['damage_absorbed'] += max(0, int(payload.get('absorbed', 0)))
        elif effect == 'vulnerability':
            row['triggers'] += 1
            row['vulnerable'] += 1
        elif effect == 'spread':
            row['triggers'] += 1
            row['spreads'] += 1
        elif effect == 'tempo':
            row['triggers'] += 1
            row['tempo_stacks'] += max(0, int(payload.get('gained', 0)))
        elif effect == 'offense_buff':
            row['triggers'] += 1
            row['offense_buffs'] += 1
        elif effect in ('heal', 'cleanse', 'status', 'guard', 'absorb_damage', 'accuracy', 'weaken'):
            row['triggers'] += 1
            field = {'heal': 'healing', 'cleanse': 'cleanses', 'status': 'statuses',
                     'guard': 'mitigated', 'absorb_damage': 'mitigated',
                     'accuracy': 'accuracy_saves', 'weaken': 'weakens'}[effect]
            row[field] += amount if field in ('healing', 'mitigated') else 1
    by_key = [rows[key] for key in NAMES if key in rows]
    fields = {'triggers': 'triggers', 'total_energy': 'energy', 'total_shield': 'shield',
              'absorbed': 'absorbed', 'total_charges': 'charges', 'total_damage': 'damage',
              'damage_absorbed': 'damage_absorbed', 'total_vulnerable': 'vulnerable',
              'total_spreads': 'spreads', 'total_tempo_stacks': 'tempo_stacks',
              'total_offense_buffs': 'offense_buffs',
              'total_healing': 'healing', 'total_cleanses': 'cleanses',
              'total_statuses': 'statuses', 'total_mitigated': 'mitigated',
              'total_accuracy_saves': 'accuracy_saves', 'total_weakens': 'weakens'}
    return {**{key: sum(row[field] for row in by_key) for key, field in fields.items()},
            'by_key': by_key}


def field_summary(events, teams, team=0):
    """Separate one team's offensive terrain from its avoidance and clearing."""
    result = dict.fromkeys(('triggers', 'damage', 'absorbed', 'avoided', 'cleared'), 0)
    for event in events:
        if event[1] != 'field_effect' or event[4] != 'rock_spikes':
            continue
        _, _, source, target, _, effect, payload = event
        if effect == 'enter' and teams.get(source) == team:
            result['triggers'] += 1
            result['damage'] += max(0, int(payload.get('actual', 0)))
            result['absorbed'] += max(0, int(payload.get('absorbed', 0)))
        elif effect == 'avoid' and teams.get(target) == team and payload.get('reason') == 'heavy_boots':
            result['avoided'] += 1
        elif effect == 'clear' and teams.get(source) == team:
            result['cleared'] += max(0, int(payload.get('cleared_count', 0)))
    return result
