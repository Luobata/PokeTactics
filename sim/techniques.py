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
    'ice_beam': frozenset({'WATER', 'ICE', 'PSYCHIC'}),
    'toxic': frozenset({'POISON', 'BUG', 'GRASS'}),
    'earthquake': frozenset({'GROUND', 'ROCK', 'FIGHTING'}),
}
_ARENA = {
    'thunderbolt': {'name': '十万伏特', 'description': '首次成功普攻后，追加一次 35 威力电属性单体攻击；可按电属性规则触发麻痹，地面免疫。每场一次。', 'partners': []},
    'ice_beam': {'name': '冰冻光束', 'description': '首次成功普攻后，追加一次 35 威力冰属性单体攻击；可按冰属性规则触发冰冻。每场一次。', 'partners': []},
    'toxic': {'name': '污泥弹', 'description': '首次成功普攻后，追加一次 25 威力毒属性单体攻击；35% 概率中毒，毒与钢属性免疫中毒。每场一次。', 'partners': []},
    'earthquake': {'name': '地震', 'description': '首次成功普攻后，以目标为中心震击目标和至多两只相邻敌人，分别结算 30 威力地面伤害；飞行免疫。每场一次。', 'partners': []},
}
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
                  'ice_beam': '水、冰或超能属性可学',
                  'toxic': '毒、虫或草属性可学',
                  'earthquake': '地面、岩或格斗属性可学'}


def ids_for(ruleset=BASE_RULESET):
    validate_ruleset(ruleset)
    if ruleset == 'arena_v1':
        return TECHNIQUE_IDS + tuple(_ARENA)
    return TECHNIQUE_IDS + tuple(_TACTICAL) if enabled(ruleset) else TECHNIQUE_IDS


def catalog(ruleset=BASE_RULESET):
    ids = ids_for(ruleset)
    rows = techniques_catalog() + [{'id': key, **deepcopy(value)} for key, value in {**_TACTICAL, **_ARENA}.items()]
    return [{**row, 'learn_types': sorted(_TYPE_REQUIREMENTS[row['id']] or []),
             'compatibility': _COMPATIBILITY[row['id']]}
            for row in rows if row['id'] in ids]


def compatible_species(species_id, technique):
    if type(species_id) is not int or species_id not in pokedex().species:
        return False
    if technique is None:
        return True
    if not isinstance(technique, str) or technique not in _TYPE_REQUIREMENTS:
        return False
    allowed = _TYPE_REQUIREMENTS[technique]
    return allowed is None or bool(allowed.intersection(pokedex().species[species_id]['types']))


def validate_learning(species_id, technique, ruleset=BASE_RULESET):
    allowed = ids_for(ruleset)
    if technique is not None and technique not in allowed:
        raise ValueError('当前规则不支持这个教学招式')
    if not compatible_species(species_id, technique):
        rule = _COMPATIBILITY.get(technique, '未知招式')
        raise ValueError('无法学习：' + rule)
    return technique


def view(technique):
    if technique is None:
        return None
    from tactics import TACTICS_RULESET
    ruleset = 'arena_v1' if technique in _ARENA else TACTICS_RULESET
    return next(dict(row) for row in catalog(ruleset) if row['id'] == technique)
