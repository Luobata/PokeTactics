"""Arena species passives and strictly scoped optional ability choices.

Chosen abilities live on the battle Piece, while counters and weather windows
remain battle local. Effects annotate settled facts; health/shield statistics
stay owned by the ordinary battle ledger, never by bonus annotations.
"""
from copy import deepcopy

from arena_combinations import EPS, _effect, _ready, _used, can_shield, grant_shield
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
TRAITS.update({
    # 受击反制：邻格敌人普攻造成实际生命损失后施加异常，沿用静电/毒刺模板。
    31: {'id': 'trait_venom_scales', 'name': '毒鳞', 'category': 'attack', 'cooldown': 5., 'limit': 2,
         'trigger': '邻格敌人普攻造成实际生命损失', 'tags': ['受击', '中毒'],
         'description': '受到邻格敌人的有效生命普攻后，使该敌人中毒。冷却5秒，每战最多2次；免疫、主要异常占槽或护盾挡住时不消耗次数。'},
    45: {'id': 'trait_effect_spore', 'name': '孢子', 'category': 'attack', 'cooldown': 6., 'limit': 2,
         'trigger': '邻格敌人普攻造成实际生命损失', 'tags': ['受击', '睡眠'],
         'description': '受到邻格敌人的有效生命普攻后，使该敌人睡眠。冷却6秒，每战最多2次；主要异常占槽或控制保护挡住时不消耗次数。'},
    181: {'id': 'trait_static_fleece', 'name': '毛绒静电', 'category': 'attack', 'cooldown': 5., 'limit': 2,
          'trigger': '邻格敌人普攻造成实际生命损失', 'tags': ['受击', '麻痹'],
          'description': '受到邻格敌人的有效生命普攻后，使该敌人麻痹。冷却5秒，每战最多2次；免疫、主要异常占槽或控制保护挡住时不消耗次数。'},
    211: {'id': 'trait_poison_needles', 'name': '毒针', 'category': 'attack', 'cooldown': 5., 'limit': 2,
          'trigger': '邻格敌人普攻造成实际生命损失', 'tags': ['受击', '中毒'],
          'description': '受到邻格敌人的有效生命普攻后，使该敌人中毒。冷却5秒，每战最多2次；免疫、主要异常占槽或护盾挡住时不消耗次数。'},
    # 受击定身：邻格敌人普攻造成实际生命损失后定身攻击者，不占异常槽。
    94: {'id': 'trait_cursed_body', 'name': '咒术之躯', 'category': 'defense', 'cooldown': 5., 'limit': 2,
         'trigger': '邻格敌人普攻造成实际生命损失', 'tags': ['受击', '定身'],
         'description': '受到邻格敌人的有效生命普攻后，使该敌人定身1.2秒，限制自然移动但不限制攻击和强制位移。冷却5秒，每战最多2次；定身不占主要异常槽。'},
    114: {'id': 'trait_tangling_vines', 'name': '蔓藤缠身', 'category': 'defense', 'cooldown': 5., 'limit': 2,
          'trigger': '邻格敌人普攻造成实际生命损失', 'tags': ['受击', '定身'],
          'description': '受到邻格敌人的有效生命普攻后，使该敌人定身1.2秒，限制自然移动但不限制攻击和强制位移。冷却5秒，每战最多2次；定身不占主要异常槽。'},
    195: {'id': 'trait_mud_wrap', 'name': '泥泞缠身', 'category': 'defense', 'cooldown': 5., 'limit': 2,
          'trigger': '邻格敌人普攻造成实际生命损失', 'tags': ['受击', '定身'],
          'description': '受到邻格敌人的有效生命普攻后，使该敌人定身1.2秒，限制自然移动但不限制攻击和强制位移。冷却5秒，每战最多2次；定身不占主要异常槽。'},
    237: {'id': 'trait_spin_guard', 'name': '回旋格挡', 'category': 'defense', 'cooldown': 4., 'limit': 3,
          'trigger': '邻格敌人普攻造成实际生命损失', 'tags': ['受击', '护盾'], 'fraction': .06,
          'description': '受到邻格敌人的有效生命普攻后，获得6%最大生命的护盾，持续3秒。冷却4秒，每战最多3次；已有更强护盾时不消耗次数。'},
    # 属性吸收：受到对应属性直接命中的实际生命伤害且存活后自疗或回能，沿用蓄电模板。
    125: {'id': 'trait_galvanize', 'name': '导电', 'category': 'support', 'cooldown': 4., 'limit': 3,
          'trigger': '电属性直接命中造成实际生命损失后存活', 'tags': ['电', '回能'],
          'description': '受到电属性直接命中的实际生命伤害且仍存活时，获得最多8实际能量。冷却4秒，每战最多3次，实际回能成功才消耗次数。'},
    131: {'id': 'trait_water_absorb', 'name': '蓄水', 'category': 'support', 'cooldown': 4., 'limit': 3,
          'trigger': '水属性直接命中造成实际生命损失后存活', 'tags': ['水', '自疗', '回能'],
          'description': '受到水属性直接命中的实际生命伤害且仍存活时，自疗4%最大生命，并获得最多4实际能量。冷却4秒，每战最多3次，实际恢复或回能成功才消耗次数。本作改编为受伤后的有限吸收。'},
    157: {'id': 'trait_flash_fire', 'name': '引火', 'category': 'support', 'cooldown': 4., 'limit': 3,
          'trigger': '火属性直接命中造成实际生命损失后存活', 'tags': ['火', '自疗', '回能'],
          'description': '受到火属性直接命中的实际生命伤害且仍存活时，自疗4%最大生命，并获得最多4实际能量。冷却4秒，每战最多3次，实际恢复或回能成功才消耗次数。本作改编为受伤后的有限吸收。'},
    # 异常开窗：真实新主要异常施加后开启短时增伤窗口，沿用毅力模板。
    40: {'id': 'trait_competitive', 'name': '好胜', 'category': 'attack', 'cooldown': 5., 'limit': 2,
         'trigger': '自己被成功施加新的主要异常', 'tags': ['异常', '特殊进攻'], 'fraction': .20,
         'description': '真实新主要异常施加后，获得3秒特殊直接伤害加成20%。冷却5秒，每战最多2次；异常结束或被净化立即失效，刷新异常不重开窗口。'},
    128: {'id': 'trait_anger_point', 'name': '愤怒穴位', 'category': 'attack', 'cooldown': 5., 'limit': 2,
          'trigger': '自己被成功施加新的主要异常', 'tags': ['异常', '物理进攻'], 'fraction': .25,
          'description': '真实新主要异常施加后，获得3秒物理直接伤害加成25%。冷却5秒，每战最多2次；异常结束或被净化立即失效，刷新异常不重开窗口。保留灼伤本身的攻击降低。'},
    65: {'id': 'trait_synchronize', 'name': '同步', 'category': 'attack', 'cooldown': 5., 'limit': 2,
         'trigger': '自己被敌人成功施加新的主要异常', 'tags': ['异常', '反弹'],
         'description': '被敌人成功施加新的主要异常后，若来源敌人存活且能承受该异常，则将同种异常施加给它。冷却5秒，每战最多2次；免疫、占槽或控制保护挡住时不消耗次数。'},
    164: {'id': 'trait_insomnia', 'name': '不眠', 'category': 'support', 'cooldown': 5., 'limit': 2,
          'trigger': '自己被成功施加睡眠', 'tags': ['异常', '自净化'],
          'description': '自己被成功施加睡眠后立即净化它。冷却5秒，每战最多2次；接地斗篷等先行净化时不消耗次数，不解除其他主要异常。'},
    # 开局：沿用威吓模板的开战一次性效果。
    73: {'id': 'trait_clear_body', 'name': '净体', 'category': 'defense', 'cooldown': 0., 'limit': 1,
         'trigger': '开战时被敌方威吓类特性选中', 'tags': ['开局', '抗压制'],
         'description': '开战时若被敌方威吓类开局削弱选中，抵挡该次削弱。每战一次；没被选中时不消耗。'},
    122: {'id': 'trait_opening_barrier', 'name': '开场护幕', 'category': 'support', 'cooldown': 0., 'limit': 1,
          'trigger': '开战时两格内最虚弱的一名友军', 'tags': ['开局', '护盾'], 'fraction': .08,
          'description': '开战时，为两格内生命比例最低的一名友军提供8%最大生命的护盾，持续3秒，可保护自身。每战一次；已有更强护盾时不消耗。'},
    142: {'id': 'trait_pressure', 'name': '压迫感', 'category': 'attack', 'cooldown': 0., 'limit': 1,
          'trigger': '开战时两格内最近两名敌人', 'tags': ['开局', '控能'],
          'description': '开战时，使两格内最近的最多两名敌人各失去至多6能量。每战一次；两名敌人都没有能量可失去时不消耗。'},
    248: {'id': 'trait_unnerve', 'name': '紧张感', 'category': 'defense', 'cooldown': 0., 'limit': 1,
          'trigger': '开战时两格内最近两名敌人', 'tags': ['开局', '物理压制'], 'fraction': .10,
          'description': '开战时，使两格内最近的最多两名敌人物理直接伤害降低10%，持续5秒。每战一次，与威吓同类取强，不永久改变攻击面板，不影响毒伤或岩钉。'},
    # 保命：沿用结实模板，放宽到半血以上。
    95: {'id': 'trait_stone_core', 'name': '岩核', 'category': 'defense', 'cooldown': 0., 'limit': 1,
         'trigger': '生命不低于一半时遭受直接命中的致命生命伤害', 'tags': ['保命'],
         'description': '生命不低于最大生命的一半时遭受直接命中的致命伤害，先结算护盾，再保留1生命，每战一次。毒伤与岩钉不触发。'},
    208: {'id': 'trait_steel_core', 'name': '钢芯', 'category': 'defense', 'cooldown': 0., 'limit': 1,
          'trigger': '生命不低于一半时遭受直接命中的致命生命伤害', 'tags': ['保命'],
          'description': '生命不低于最大生命的一半时遭受直接命中的致命伤害，先结算护盾，再保留1生命，每战一次。毒伤与岩钉不触发。'},
    # 低血增伤：沿用猛火/激流模板。
    123: {'id': 'trait_swarm', 'name': '虫之预感', 'category': 'attack', 'cooldown': 3., 'limit': 3,
          'trigger': '生命不高于三分之一时的虫属性直接命中', 'tags': ['低血量', '虫'], 'fraction': .25,
          'description': '生命不高于最大生命的三分之一时，虫属性直接命中伤害提高25%。冷却3秒，每战最多3次；只有实际多扣生命或额外消耗护盾才消耗次数。'},
    214: {'id': 'trait_cornered', 'name': '困兽斗', 'category': 'attack', 'cooldown': 3., 'limit': 3,
          'trigger': '生命不高于三分之一时的格斗属性直接命中', 'tags': ['低血量', '格斗'], 'fraction': .25,
          'description': '生命不高于最大生命的三分之一时，格斗属性直接命中伤害提高25%。冷却3秒，每战最多3次；只有实际多扣生命或额外消耗护盾才消耗次数。'},
    160: {'id': 'trait_raging_tide', 'name': '怒涛', 'category': 'defense', 'cooldown': 3., 'limit': 3,
          'trigger': '生命不高于三分之一时的水属性直接命中', 'tags': ['低血量', '水'], 'fraction': .25,
          'description': '生命不高于最大生命的三分之一时，水属性直接命中伤害提高25%。冷却3秒，每战最多3次；只有实际多扣生命或额外消耗护盾才消耗次数。'},
    # 易伤追击：目标带未到期易伤时强化直接命中。
    127: {'id': 'trait_crushing_grip', 'name': '碎甲重钳', 'category': 'attack', 'cooldown': 3., 'limit': 3,
          'trigger': '目标带有未到期易伤时的直接命中', 'tags': ['易伤', '集火'], 'fraction': .12,
          'description': '目标带有未到期易伤时，自己的直接命中伤害提高12%。冷却3秒，每战最多3次；只有实际多扣生命或额外消耗护盾才消耗次数。'},
    196: {'id': 'trait_weakness_read', 'name': '破绽洞悉', 'category': 'attack', 'cooldown': 3., 'limit': 3,
          'trigger': '目标带有未到期易伤时的直接命中', 'tags': ['易伤', '集火'], 'fraction': .15,
          'description': '目标带有未到期易伤时，自己的直接命中伤害提高15%。冷却3秒，每战最多3次；只有实际多扣生命或额外消耗护盾才消耗次数。'},
    # 本命开窗：成功完成本命施法后开启短时增伤窗口。
    106: {'id': 'trait_rising_kick', 'name': '踢势', 'category': 'attack', 'cooldown': 5., 'limit': 2,
          'trigger': '成功完成本命施法', 'tags': ['施法', '增伤'], 'fraction': .15,
          'description': '成功完成本命施法后，获得3秒直接伤害加成15%。冷却5秒，每战最多2次；被阻止的施法不触发，不强化毒伤、岩钉或治疗。'},
    212: {'id': 'trait_sharpened_blades', 'name': '刀锋磨砺', 'category': 'attack', 'cooldown': 5., 'limit': 2,
          'trigger': '成功完成本命施法', 'tags': ['施法', '增伤'], 'fraction': .15,
          'description': '成功完成本命施法后，获得3秒直接伤害加成15%。冷却5秒，每战最多2次；被阻止的施法不触发，不强化毒伤、岩钉或治疗。'},
    # 节拍自疗：沿用雨盘模板的常驻节律回复。
    80: {'id': 'trait_regenerator', 'name': '再生力', 'category': 'defense', 'cooldown': 4., 'limit': 4,
         'trigger': '战斗中每四秒', 'tags': ['自疗'], 'fraction': .03,
         'description': '战斗中每四秒回复3%最大生命，每战最多4次，受封疗影响；实际回复成功才消耗次数。特性治疗不触发本命技能联动。'},
    197: {'id': 'trait_moonlight', 'name': '月光滋养', 'category': 'defense', 'cooldown': 4., 'limit': 4,
          'trigger': '战斗中每四秒', 'tags': ['自疗'], 'fraction': .03,
          'description': '战斗中每四秒回复3%最大生命，每战最多4次，受封疗影响；实际回复成功才消耗次数。特性治疗不触发本命技能联动。'},
    # 本命治疗接力：沿用治愈之心模板，改为护盾、自疗或减伤。
    108: {'id': 'trait_soothing_lick', 'name': '润泽之舌', 'category': 'support', 'cooldown': 4., 'limit': 3,
          'trigger': '本命对其他队友实际治疗至少患者最大生命的5%', 'tags': ['治疗', '护盾'], 'fraction': .08,
          'description': '本命对其他队友实际治疗达到患者最大生命的5%后，为该队友提供8%最大生命的护盾，持续3秒。冷却4秒，每战最多3次；已有更强护盾时不消耗次数，特性产物不再触发本命联动。'},
    113: {'id': 'trait_benevolence', 'name': '仁心', 'category': 'support', 'cooldown': 4., 'limit': 3,
          'trigger': '本命对其他队友实际治疗至少患者最大生命的5%', 'tags': ['治疗', '自疗'], 'fraction': .04,
          'description': '本命对其他队友实际治疗达到患者最大生命的5%后，自疗4%最大生命。冷却4秒，每战最多3次；实际回复成功才消耗次数，特性产物不再触发本命联动。'},
    154: {'id': 'trait_lingering_aroma', 'name': '花幕余香', 'category': 'support', 'cooldown': 4., 'limit': 3,
          'trigger': '本命对其他队友实际治疗至少患者最大生命的5%', 'tags': ['治疗', '减伤'], 'fraction': .15,
          'description': '本命对其他队友实际治疗达到患者最大生命的5%后，使该队友受到的伤害降低15%，持续3秒。冷却4秒，每战最多3次；已有更强减伤时不消耗次数，特性产物不再触发本命联动。'},
    # 反闪避：沿用复眼模板。
    162: {'id': 'trait_keen_eye', 'name': '锐利目光', 'category': 'support', 'cooldown': 3., 'limit': 3,
          'trigger': '原本被道具闪避的进攻判定', 'tags': ['命中', '反闪避'],
          'description': '进攻原本会被道具闪避且原判定落在闪避率后半区时，改为命中。冷却3秒，每战最多3次，沿用该次随机判定，不额外掷骰。'},
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
    154: {'id': 'trait_verdant_rhythm', 'name': '翠绿节律', 'category': 'support',
          'cooldown': 5., 'limit': 3, 'fraction': .05,
          'trigger': '战斗中每五秒', 'tags': ['自疗', '挑战解锁'],
          'description': '战斗中每五秒回复5%最大生命，每战最多3次，受封疗影响；实际回复成功才消耗次数。特性治疗不触发本命技能联动。完成竞技挑战「羁绊编织者」后可在准备期选择。'},
}

# Challenge-locked alternatives: only the player can pick them, and only after
# the linked arena challenge is complete (session.arena_unlocks snapshot).
TRAIT_LOCKS = {'trait_verdant_rhythm': 'arena_bonds_6'}


# Dispatch tables for the expanded roster. Every entry reuses an existing
# combat hook; settlement semantics stay identical to the original template.
_CONTACT_STATUS = {'trait_static': 'para', 'trait_poison_point': 'poison',
                   'trait_venom_scales': 'poison', 'trait_poison_needles': 'poison',
                   'trait_effect_spore': 'sleep', 'trait_static_fleece': 'para'}
_CONTACT_ROOT = {'trait_cursed_body': 1.2, 'trait_tangling_vines': 1.2,
                 'trait_mud_wrap': 1.2}
# key -> (move type, self-heal fraction, energy cap)
_TYPED_ABSORB = {'trait_volt_absorb': ('ELECTRIC', .04, 4),
                 'trait_water_absorb': ('WATER', .04, 4),
                 'trait_flash_fire': ('FIRE', .04, 4),
                 'trait_galvanize': ('ELECTRIC', 0., 8)}
# key -> (move type, hp divisor): boost while source.hp * divisor <= max_hp.
_LOW_HP_BOOST = {'trait_blaze': ('FIRE', 3), 'trait_torrent': ('WATER', 2),
                 'trait_swarm': ('BUG', 3), 'trait_cornered': ('FIGHTING', 3),
                 'trait_raging_tide': ('WATER', 3)}
_VULNERABLE_BOOST = {'trait_crushing_grip', 'trait_weakness_read'}
# Offense windows open once (consuming a use) and boost until expiry; settle
# never charges them per hit. Debuff-tied windows also end with the status.
_DEBUFF_WINDOWS = {'trait_guts': 'physical', 'trait_competitive': 'special',
                   'trait_anger_point': 'physical'}
_CAST_WINDOWS = {'trait_rising_kick', 'trait_sharpened_blades'}
_WINDOWS = {**_DEBUFF_WINDOWS, **{key: 'all' for key in _CAST_WINDOWS}}
_OPENING_WEAKEN = {'trait_intimidate', 'trait_unnerve'}
_CADENCE_HEAL = {'trait_regenerator', 'trait_moonlight', 'trait_verdant_rhythm'}
_LETHAL_GUARD = {'trait_sturdy', 'trait_stone_core', 'trait_steel_core'}
_ANTI_DODGE = {'trait_compound_eyes', 'trait_keen_eye'}


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
            'choice': None if default else spec['id'],
            'unlock_challenge': TRAIT_LOCKS.get(spec['id']), 'arena_only': True}


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
    if not battle._arena_on:
        return
    rain = active(battle, t) == 'rain'
    for patient in sorted(battle.units, key=lambda unit: unit.initiative):
        spec = _spec(battle, patient)
        if not spec or not _available(patient, spec, t):
            continue
        if spec['id'] == 'trait_rain_dish':
            if not rain:
                continue
            # Empty/full-health pulses do not count as healing, but the cadence
            # still advances; a new injury cannot create an off-grid pulse.
            window = battle.arena_weather_started_at
            if getattr(patient, '_rain_dish_window', None) != window:
                patient._rain_dish_window = window
                patient._rain_dish_next_at = window + spec['cooldown']
                next_at = patient._rain_dish_next_at
            else:
                next_at = patient._rain_dish_next_at
        elif spec['id'] in _CADENCE_HEAL:
            # Battle-start anchored cadence; same pulse semantics as rain dish.
            if getattr(patient, '_trait_cadence_next_at', None) is None:
                patient._trait_cadence_next_at = spec['cooldown']
            next_at = patient._trait_cadence_next_at
        else:
            continue
        if t + EPS < next_at:
            continue
        attr = '_rain_dish_next_at' if spec['id'] == 'trait_rain_dish' else '_trait_cadence_next_at'
        while getattr(patient, attr) <= t + EPS:
            setattr(patient, attr, getattr(patient, attr) + spec['cooldown'])
        requested = int(patient.max_hp * spec['fraction'])
        actual = battle._healing_amount(patient, requested, t)[0]
        if actual <= 0:
            continue
        with _effect(battle, patient, patient, spec['id'], 'heal', t,
                     amount=actual, requested=requested,
                     weather='rain' if spec['id'] == 'trait_rain_dish' else None,
                     reason='rain_dish_actual_self_heal' if spec['id'] == 'trait_rain_dish'
                     else 'cadence_actual_self_heal'):
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
        spec = _spec(battle, source)
        if spec is None:
            continue
        key = spec['id']
        if key in _OPENING_WEAKEN:
            enemies = sorted((enemy for enemy in battle.units if enemy.alive
                              and enemy.team != source.team
                              and abs(enemy.pos[0] - source.pos[0]) + abs(enemy.pos[1] - source.pos[1]) <= 2),
                             key=lambda enemy: battle._target_key(source, enemy))[:2]
            changed = False
            for patient in enemies:
                guard = _spec(battle, patient, 'trait_clear_body')
                if guard and _available(patient, guard, 0.):
                    with _effect(battle, patient, patient, guard['id'], 'guard', 0.,
                                 amount=0, fraction=spec['fraction'], origin_idx=source.idx,
                                 damage_scope='physical', reason='opening_weaken_blocked'):
                        _used_trait(patient, guard, 0.)
                        battle._emit_state(patient, 0.)
                    continue
                if patient.trait_weaken_until > EPS and patient.trait_weaken_fraction >= spec['fraction']:
                    continue
                with _effect(battle, source, patient, key, 'weaken', 0.,
                             amount=0, fraction=spec['fraction'], duration=5., expires_at=5.,
                             damage_scope='physical', reason='opening_nearby_enemies'):
                    patient.trait_weaken_fraction, patient.trait_weaken_until = spec['fraction'], 5.
                    patient.trait_weaken_source_idx = source.idx
                    patient.trait_weaken_key = key
                    battle._emit_state(patient, 0.)
                changed = True
            if changed:
                _used_trait(source, spec, 0.)
        elif key == 'trait_opening_barrier':
            friends = sorted((friend for friend in battle.units if friend.alive
                              and friend.team == source.team
                              and abs(friend.pos[0] - source.pos[0]) + abs(friend.pos[1] - source.pos[1]) <= 2),
                             key=lambda friend: (friend.hp / friend.max_hp,
                                                 battle._target_key(source, friend)))
            for patient in friends:
                amount = int(patient.max_hp * spec['fraction'])
                if not can_shield(patient, amount, 0.):
                    continue
                if grant_shield(battle, source, patient, amount, 0., None,
                                source_kind='trait', source_key=key,
                                reason='opening_weakest_ally'):
                    _used_trait(source, spec, 0.)
                break
        elif key == 'trait_pressure':
            enemies = sorted((enemy for enemy in battle.units if enemy.alive
                              and enemy.team != source.team and enemy.energy > 0
                              and abs(enemy.pos[0] - source.pos[0]) + abs(enemy.pos[1] - source.pos[1]) <= 2),
                             key=lambda enemy: battle._target_key(source, enemy))[:2]
            drained_any = False
            for patient in enemies:
                drained = min(6, patient.energy)
                if drained <= 0:
                    continue
                with _effect(battle, source, patient, key, 'energy_drain', 0.,
                             amount=drained, requested=6,
                             reason='opening_nearby_enemies'):
                    patient.energy -= drained
                    battle._emit_state(patient, 0.)
                drained_any = True
            if drained_any:
                _used_trait(source, spec, 0.)


def expire(battle, unit, t):
    if not battle._arena_on or not TRAITS_ON:
        return
    st = getattr(unit, '_st', None)
    for key, debuff_tied in (('trait_guts', True), ('trait_competitive', True),
                             ('trait_anger_point', True), ('trait_rising_kick', False),
                             ('trait_sharpened_blades', False)):
        fraction = getattr(unit, key + '_fraction', 0.)
        until = getattr(unit, key + '_until', 0.)
        if not fraction or (t + EPS < until and (not debuff_tied or st and st.debuff)):
            continue
        reason = 'duration' if not debuff_tied or st and st.debuff else 'cleansed_or_ended'
        with _effect(battle, unit, unit, key, 'expire', t, amount=0, fraction=fraction,
                     duration=0., expires_at=until, damage_scope=_WINDOWS[key], reason=reason):
            setattr(unit, key + '_fraction', 0.)
            setattr(unit, key + '_until', 0.)
            battle._emit_state(unit, t)
    fraction, until = unit.trait_weaken_fraction, unit.trait_weaken_until
    if fraction and t + EPS >= until:
        key = getattr(unit, 'trait_weaken_key', None) or 'trait_intimidate'
        source = battle.units[unit.trait_weaken_source_idx]
        with _effect(battle, source, unit, key, 'expire', t, amount=0, fraction=fraction,
                     duration=0., expires_at=until, damage_scope='physical', reason='duration'):
            unit.trait_weaken_fraction = 0.
            unit.trait_weaken_until = 0.
            unit.trait_weaken_source_idx = None
            unit.trait_weaken_key = None
            battle._emit_state(unit, t)


def after_debuff(battle, source, patient, kind, t):
    spec = _spec(battle, patient)
    if not spec:
        return False
    st = getattr(patient, '_st', None)
    key = spec['id']
    if key in _DEBUFF_WINDOWS:
        if not st or st.debuff != kind or not _available(patient, spec, t):
            return False
        with _effect(battle, patient, patient, key, 'offense_buff', t,
                     amount=0, fraction=spec['fraction'], duration=3., expires_at=t + 3.,
                     damage_scope=_DEBUFF_WINDOWS[key], status_kind=kind,
                     origin_idx=source.idx if source is not None else None,
                     reason='new_major_status'):
            setattr(patient, key + '_fraction', spec['fraction'])
            setattr(patient, key + '_until', t + 3.)
            _used_trait(patient, spec, t)
            battle._emit_state(patient, t)
        return True
    if key == 'trait_synchronize':
        st_source = getattr(source, '_st', None) if source is not None else None
        if (not st or st.debuff != kind or not status.STATUS_ON
                or source is None or not source.alive or source.team == patient.team
                or st_source is None or st_source.debuff is not None
                or not _available(patient, spec, t)
                or set(source.piece.types).intersection(status.IMMUNE_TYPES.get(kind, ()))
                or kind in status.CONTROL_KINDS and t + EPS < st_source.ctrl_until):
            return False
        with _effect(battle, patient, source, key, 'status', t, amount=0,
                     status_kind=kind, applied=True,
                     reason='mirrored_new_major_status'):
            if status.apply_debuff(battle, source, kind, t, source=patient):
                _used_trait(patient, spec, t)
        return True
    if key == 'trait_insomnia':
        if kind != 'sleep' or not _available(patient, spec, t):
            return False
        return _cleanse(battle, patient, patient, spec, t, None,
                        'immediate_sleep_cleanse')
    return False


def prevent_dodge(battle, source, target, roll, t):
    spec = _spec(battle, source)
    if (not spec or spec['id'] not in _ANTI_DODGE
            or roll < target.item_dodge * .5 or roll >= target.item_dodge
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
        low_hp = _LOW_HP_BOOST.get(key)
        eligible = bool(low_hp and move and move['type'] == low_hp[0]
                        and source.hp * low_hp[1] <= source.max_hp)
        if key in _VULNERABLE_BOOST:
            eligible = bool(patient is not None and patient is not source
                            and getattr(patient, 'vulnerable_until', 0.) > t + EPS)
        if eligible or key == 'trait_sheer_force' and sheer_force_applies(battle, source, move):
            boost = spec
    window_scope = _WINDOWS.get(spec['id']) if spec else None
    if (window_scope and getattr(source, spec['id'] + '_fraction', 0.)
            and t + EPS < getattr(source, spec['id'] + '_until', 0.)
            and (window_scope == 'all'
                 or (window_scope == 'physical') == _physical(battle, source, move))
            and (spec['id'] not in _DEBUFF_WINDOWS
                 or getattr(getattr(source, '_st', None), 'debuff', None))):
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


def _lethal_guard_spec(battle, patient, t):
    spec = _spec(battle, patient)
    if not spec or spec['id'] not in _LETHAL_GUARD or not _available(patient, spec, t):
        return None
    if spec['id'] == 'trait_sturdy':
        return spec if patient.hp == patient.max_hp else None
    return spec if patient.hp * 2 >= patient.max_hp else None


def sturdy_ready(battle, patient, t):
    return _lethal_guard_spec(battle, patient, t) is not None


def protect_lethal(battle, patient, hp_damage, t, direct):
    spec = _lethal_guard_spec(battle, patient, t) if direct else None
    if spec is None or hp_damage < patient.hp:
        return hp_damage, None
    capped = max(0, patient.hp - 1)
    _used_trait(patient, spec, t)
    return capped, {'spec': spec, 'prevented': hp_damage - capped,
                    'prevented_hp': min(patient.hp, hp_damage) - capped,
                    'reason': ('full_health_direct_lethal' if spec['id'] == 'trait_sturdy'
                               else 'half_health_direct_lethal')}


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
                if spec['id'] not in _WINDOWS and spec['limit'] is not None:
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
    adjacent = abs(source.pos[0] - patient.pos[0]) + abs(source.pos[1] - patient.pos[1]) == 1
    if key in _CONTACT_STATUS:
        kind = _CONTACT_STATUS[key]
        st = getattr(source, '_st', None)
        if (not basic or not source.alive or st is None or st.debuff is not None
                or not adjacent or not _available(patient, spec, t)
                or set(source.piece.types).intersection(status.IMMUNE_TYPES.get(kind, ()))
                or kind in status.CONTROL_KINDS and t + EPS < st.ctrl_until or not status.STATUS_ON):
            return
        with _effect(battle, patient, source, key, 'status', t, amount=0,
                     status_kind=kind, applied=True, action_index=action_index,
                     reason='adjacent_actual_basic_received'):
            if status.apply_debuff(battle, source, kind, t, source=patient):
                _used_trait(patient, spec, t)
        return
    if key in _CONTACT_ROOT:
        if (not basic or not source.alive or not adjacent
                or not _available(patient, spec, t)):
            return
        duration = _CONTACT_ROOT[key]
        until = max(getattr(source, 'root_until', 0.), t + duration)
        with _effect(battle, patient, source, key, 'root', t, amount=0,
                     duration=duration, expires_at=until, action_index=action_index,
                     reason='adjacent_actual_basic_received'):
            source.root_until, source.root_source = until, patient.idx
            battle._emit_state(source, t)
            _used_trait(patient, spec, t)
        return
    if key == 'trait_spin_guard':
        if not basic or not adjacent or not _available(patient, spec, t):
            return
        amount = int(patient.max_hp * spec['fraction'])
        if not can_shield(patient, amount, t):
            return
        if grant_shield(battle, patient, patient, amount, t, None,
                        source_kind='trait', source_key=key,
                        reason='adjacent_actual_basic_received'):
            _used_trait(patient, spec, t)
        return
    absorb = _TYPED_ABSORB.get(key)
    if (not absorb or move is None or move['type'] != absorb[0]
            or not _available(patient, spec, t)):
        return
    heal_fraction, energy_cap = absorb[1:]
    requested = int(patient.max_hp * heal_fraction)
    actual = battle._healing_amount(patient, requested, t)[0] if requested > 0 else 0
    energy = min(energy_cap, max(0, ENERGY_MAX - patient.energy))
    if actual <= 0 and energy <= 0:
        return
    reason = 'survived_actual_' + absorb[0].lower() + '_hp'
    if actual > 0:
        with _effect(battle, patient, patient, key, 'heal', t, amount=actual,
                     requested=requested, action_index=action_index, origin_idx=source.idx,
                     reason=reason):
            battle._heal(patient, requested, t, source=patient)
    if energy > 0:
        with _effect(battle, patient, patient, key, 'energy', t, amount=energy,
                     requested=energy_cap, action_index=action_index, origin_idx=source.idx,
                     reason=reason):
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
    spec = _spec(battle, source)
    if (not spec or not _available(source, spec, t) or type(cast_index) is not int
            or not 0 <= cast_index < len(battle.events)
            or battle.events[cast_index][1:3] != ('cast', source.idx)
            or battle.events[cast_index][4] != 'arena_' + source.ult_arch):
        return requested
    key = spec['id']
    if key == 'trait_natural_cure':
        return _cleanse(battle, source, source, spec, t, cast_index,
                        'completed_native_self_cure') or requested
    if key in _CAST_WINDOWS:
        with _effect(battle, source, source, key, 'offense_buff', t,
                     amount=0, fraction=spec['fraction'], duration=3., expires_at=t + 3.,
                     damage_scope='all', reason='completed_native_cast'):
            setattr(source, key + '_fraction', spec['fraction'])
            setattr(source, key + '_until', t + 3.)
            _used_trait(source, spec, t)
            battle._emit_state(source, t)
        return True
    return requested


def after_native_heal(battle, source, patient, actual, t, cast_index):
    spec = _spec(battle, source)
    if (not spec or patient is source or source.team != patient.team or actual <= 0
            or actual + EPS < patient.max_hp * .05 or not _available(source, spec, t)
            or type(cast_index) is not int or not 0 <= cast_index < len(battle.events)
            or battle.events[cast_index][1:3] != ('cast', source.idx)
            or battle.events[cast_index][4] != 'arena_' + source.ult_arch):
        return False
    key = spec['id']
    if key == 'trait_healer':
        return _cleanse(battle, source, patient, spec, t, cast_index,
                        'effective_native_other_heal')
    if key == 'trait_soothing_lick':
        amount = int(patient.max_hp * spec['fraction'])
        if not can_shield(patient, amount, t):
            return False
        if grant_shield(battle, source, patient, amount, t, cast_index,
                        source_kind='trait', source_key=key,
                        reason='effective_native_other_heal'):
            _used_trait(source, spec, t)
            return True
        return False
    if key == 'trait_benevolence':
        requested_amount = int(source.max_hp * spec['fraction'])
        recovered = battle._healing_amount(source, requested_amount, t)[0]
        if recovered <= 0:
            return False
        with _effect(battle, source, source, key, 'heal', t, cast_index,
                     amount=recovered, requested=requested_amount, origin_idx=patient.idx,
                     reason='effective_native_other_heal'):
            battle._heal(source, requested_amount, t, source=source)
            _used_trait(source, spec, t)
        return True
    if key == 'trait_lingering_aroma':
        if patient.temp_dr_until > t + EPS and patient.temp_dr > spec['fraction']:
            return False
        with _effect(battle, source, patient, key, 'guard', t, cast_index, amount=0,
                     reduction=spec['fraction'], duration=3., expires_at=t + 3.,
                     reason='effective_native_other_heal'):
            patient.temp_dr, patient.temp_dr_until = spec['fraction'], t + 3.
            _used_trait(source, spec, t)
            battle._emit_state(patient, t)
        return True
    return False
