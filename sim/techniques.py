"""Species-compatible teaching, independent of ownership and unlock storage."""
from copy import deepcopy
from data import pokedex
from partners import techniques_catalog
from tactics import BASE_RULESET, enabled, validate_ruleset
from weather_control import WEATHER_WINDOW_SECONDS

TECHNIQUE_IDS = ('cut', 'surf', 'rest')
_TYPE_REQUIREMENTS = {
    'cut': frozenset({'GRASS', 'FIRE', 'BUG', 'NORMAL', 'FIGHTING', 'STEEL'}),
    'surf': frozenset({'WATER'}),
    'rest': None,
    'guard': None,
    'sunny_day': frozenset({'FIRE', 'GRASS'}),
    'rain_dance': frozenset({'WATER', 'ELECTRIC'}),
    'thunderbolt': frozenset({'ELECTRIC', 'PSYCHIC', 'NORMAL'}),
    'thunder': frozenset({'ELECTRIC', 'PSYCHIC', 'NORMAL'}),
    'ice_beam': frozenset({'WATER', 'ICE', 'PSYCHIC'}),
    'toxic': frozenset({'POISON', 'BUG', 'GRASS'}),
    'earthquake': frozenset({'GROUND', 'ROCK', 'FIGHTING'}),
    'roar': frozenset({'NORMAL', 'FIRE', 'FIGHTING', 'ROCK'}),
    'rapid_spin': frozenset({'NORMAL', 'WATER', 'BUG', 'ROCK'}),
    'stealth_rock': frozenset({'ROCK', 'GROUND', 'STEEL'}),
    'taunt': frozenset({'NORMAL', 'FIGHTING', 'ROCK'}),
    'sleep_powder': frozenset({'GRASS', 'BUG', 'POISON'}),
    'protect': frozenset({'NORMAL', 'FIGHTING', 'GROUND'}),
    'helping_hand': frozenset({'NORMAL', 'PSYCHIC'}),
    'heal_bell': frozenset({'NORMAL', 'PSYCHIC', 'GRASS'}),
}
_ARENA_USES = '次数等于携带者星级，每次触发后再装填需 3 次有效普攻。'
_ARENA = {
    'rain_dance': {'name': '求雨', 'category': 'startup', 'description': '首次成功完成本命技能后，请求12秒全场雨天，下一战斗刻生效，每位学习者每战一次。雨天水属性直接伤害提高15%、火属性降低10%，打雷必中；双方共享，同刻雨晴抵消，同天气不续时。', 'partners': []},
    'sunny_day': {'name': '晴天', 'category': 'startup', 'description': '首次成功完成本命技能后，请求12秒全场晴天，下一战斗刻生效，每位学习者每战一次。晴天火属性直接伤害提高15%、水属性降低10%；双方共享，同刻雨晴抵消，同天气不续时。', 'partners': []},
    'thunder': {'name': '打雷', 'category': 'damage', 'description': '有效普攻后择机追加一次65威力电属性单体攻击，通常70%命中；雨天必中且无视道具闪避，仍不能命中地面属性。己方有求雨学习者时最多等到开战6秒；未命中也消耗一次机会。' + _ARENA_USES, 'partners': []},
    'thunderbolt': {'name': '十万伏特', 'category': 'control', 'description': '首次成功普攻后，追加一次 35 威力电属性单体攻击；可按电属性规则触发麻痹，地面免疫。' + _ARENA_USES, 'partners': []},
    'ice_beam': {'name': '冰冻光束', 'category': 'control', 'description': '首次成功普攻后，追加一次 35 威力冰属性单体攻击；可按冰属性规则触发冰冻。' + _ARENA_USES, 'partners': []},
    'toxic': {'name': '污泥弹', 'category': 'control', 'description': '首次成功普攻后，追加一次 25 威力毒属性单体攻击；35% 概率中毒，毒与钢属性免疫中毒。' + _ARENA_USES, 'partners': []},
    'earthquake': {'name': '地震', 'category': 'damage', 'description': '首次成功普攻后，以目标为中心震击目标和至多两只相邻敌人，分别结算 30 威力地面伤害；飞行免疫。' + _ARENA_USES, 'partners': []},
    'roar': {'name': '吼叫', 'category': 'control', 'description': '成功普攻后择机将存活目标击退一格。有存活铺钉队友或本队有效岩钉时，优先等能把目标推入岩钉的落点；开战6秒后不再等待铺场。后方无空位时不消耗次数。' + _ARENA_USES, 'partners': []},
    'rapid_spin': {'name': '高速旋转', 'category': 'counter', 'description': '成功普攻后择机追加20威力一般属性攻击，并清除自身一格内至多3格敌钉。有存活敌方铺钉手或有效敌钉时，优先等待附近出现敌钉；开战6秒后不再等待。无铺钉威胁时首次成功普攻触发。' + _ARENA_USES, 'partners': []},
    'stealth_rock': {'name': '隐形岩', 'category': 'control', 'description': '成功普攻后，以当前目标为中心铺设至多3格岩钉、持续6秒；敌人进入钉格受到岩属性伤害（不超过其最大生命12%）。吼叫与击退可把目标推入岩钉，高速旋转可清除。' + _ARENA_USES, 'partners': []},
    'taunt': {'name': '挑衅', 'category': 'control', 'description': '成功普攻后嘲讽当前目标2秒，期间它强制攻击你；同一敌人之后4秒内不会再被嘲讽。' + _ARENA_USES, 'partners': []},
    'sleep_powder': {'name': '催眠粉', 'category': 'control', 'description': '成功普攻后尝试使当前目标陷入睡眠，期间无法行动；免疫、已有主要异常或控制保护期内会失败，失败同样消耗次数。' + _ARENA_USES, 'partners': []},
    'protect': {'name': '守住', 'category': 'survival', 'description': '携带者首次实际受击后获得2秒20%减伤窗口；窗口期间实际承伤累计达到其最大生命15%时获得蓄势：下一次原生主命中伤害提高12%，命中后消耗。减伤窗口与蓄势每次次数各触发一次。' + _ARENA_USES, 'partners': []},
    'helping_hand': {'name': '帮助', 'category': 'support', 'description': '成功普攻后，为两格内攻击最高的其他存活友军施加标记：其下一次原生主命中伤害提高15%，命中后消耗；没有合法友军时不消耗次数。' + _ARENA_USES, 'partners': []},
    'heal_bell': {'name': '治愈铃声', 'category': 'recovery', 'description': '首次有友军被施加主要异常后，净化两格内一名其他存活队友的该异常，优先刚被施加异常的队友；没有合适目标时不消耗次数。' + _ARENA_USES, 'partners': []},
}
# 经典三机在竞技场共用触发管线，但次数随星级成长，文案需按规则覆盖。
_ARENA_CLASSIC_DESCRIPTIONS = {
    'cut': '首次普攻造成伤害后，追加攻击主目标邻格内的一名其他敌人（普通属性、35威力、物理）；追加命中不回能。' + _ARENA_USES,
    'surf': '首次成功普攻后，以主目标为中心发动水浪，对主目标和至多两名相邻敌人分别造成35威力水属性伤害；不依赖本命技能造成伤害。' + _ARENA_USES,
    'rest': '生命不高于一半时行动，用该次行动回复自身最大生命的25%，随后休息一个攻击间隔。' + _ARENA_USES,
}
# 经典三机的类别只在竞技评分中使用；经典目录行保持原样。
_CLASSIC_CATEGORY = {'cut': 'damage', 'surf': 'damage', 'rest': 'recovery'}
_TACTICAL = {
    'guard': {'name': '护卫', 'description': '准备期指定相邻队友；替其承受一次实际突进后的主命中，每队一名护卫，每场一次。', 'partners': []},
    'sunny_day': {'name': '晴天', 'description': f'指定为天气手后，首次原生大招申请{WEATHER_WINDOW_SECONDS:g}秒全场晴天；双方都会受益或受损，每队每场一次。', 'partners': []},
    'rain_dance': {'name': '求雨', 'description': f'指定为天气手后，首次原生大招申请{WEATHER_WINDOW_SECONDS:g}秒全场雨天；双方都会受益或受损，每队每场一次。', 'partners': []},
}
_COMPATIBILITY = {'cut': '草、火、虫、一般、格斗或钢属性可学',
                  'surf': '水属性可学', 'rest': '所有宝可梦可学',
                  'guard': '所有宝可梦可学', 'sunny_day': '火或草属性可学',
                  'rain_dance': '水或电属性可学',
                  'thunderbolt': '电、超能或一般属性可学',
                  'thunder': '电、超能或一般属性可学；竞技尼多王也可学',
                  'ice_beam': '水、冰或超能属性可学',
                  'toxic': '毒、虫或草属性可学',
                  'earthquake': '地面、岩或格斗属性可学',
                  'roar': '一般、火、格斗或岩属性可学',
                  'rapid_spin': '一般、水、虫或岩属性可学',
                  'stealth_rock': '岩、地面或钢属性可学',
                  'taunt': '一般、格斗或岩属性可学',
                  'sleep_powder': '草、虫或毒属性可学',
                  'protect': '一般、格斗或地面属性可学',
                  'helping_hand': '一般或超能属性可学',
                  'heal_bell': '一般、超能或草属性可学'}

# Explicit original-move coverage for the arena's mixed attacker. Keep this
# separate from the classic species/type policy and apply it only with a ruleset.
_ARENA_EXTRA = {34: frozenset({'thunderbolt', 'ice_beam', 'thunder'})}


def ids_for(ruleset=BASE_RULESET):
    validate_ruleset(ruleset)
    if ruleset == 'arena_v1':
        return TECHNIQUE_IDS + tuple(_ARENA)
    return TECHNIQUE_IDS + tuple(_TACTICAL) if enabled(ruleset) else TECHNIQUE_IDS


def category_of(key):
    """Bot 学习评分用的技能类别；未登记的 key 返回 None。"""
    if key in _ARENA:
        return _ARENA[key]['category']
    return _CLASSIC_CATEGORY.get(key)


def catalog(ruleset=BASE_RULESET):
    ids = ids_for(ruleset)
    definitions = {**_TACTICAL, **_ARENA} if ruleset == 'arena_v1' else _TACTICAL
    rows = techniques_catalog() + [{'id': key, **deepcopy(value)} for key, value in definitions.items()]
    if ruleset == 'arena_v1':
        rows = [{**row, 'description': _ARENA_CLASSIC_DESCRIPTIONS[row['id']]}
                if row['id'] in _ARENA_CLASSIC_DESCRIPTIONS else row for row in rows]
    return [{**row, 'learn_types': sorted(_TYPE_REQUIREMENTS[row['id']] or []),
             **({'extra_species': sorted(sid for sid, keys in _ARENA_EXTRA.items() if row['id'] in keys)}
                if ruleset == 'arena_v1' else {}),
             'compatibility': _COMPATIBILITY[row['id']] +
                              ('；竞技尼多王也可学' if ruleset == 'arena_v1' and row['id'] in ('thunderbolt', 'ice_beam') else '')}
            for row in rows if row['id'] in ids]


def compatible_species(species_id, technique, ruleset=BASE_RULESET):
    if type(species_id) is not int or not pokedex().has_species(species_id):
        return False
    if technique is None:
        return True
    if not isinstance(technique, str) or technique not in _TYPE_REQUIREMENTS:
        return False
    if ruleset == 'arena_v1' and technique in _ARENA_EXTRA.get(species_id, ()):
        return True
    allowed = _TYPE_REQUIREMENTS[technique]
    return allowed is None or bool(allowed.intersection(pokedex().species_record(species_id)['types']))


def validate_learning(species_id, technique, ruleset=BASE_RULESET):
    allowed = ids_for(ruleset)
    if technique is not None and technique not in allowed:
        raise ValueError('当前规则不支持这个教学招式')
    if not compatible_species(species_id, technique, ruleset):
        rule = _COMPATIBILITY.get(technique, '未知招式')
        raise ValueError('无法学习：' + rule)
    return technique


def view(technique, ruleset=None):
    if technique is None:
        return None
    from tactics import TACTICS_RULESET
    ruleset = ruleset or ('arena_v1' if technique in _ARENA and technique not in _TACTICAL else TACTICS_RULESET)
    return next(dict(row) for row in catalog(ruleset) if row['id'] == technique)
