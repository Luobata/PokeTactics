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
}
_TACTICAL = {
    'guard': {'name': '护卫', 'description': '准备期指定相邻队友；替其承受一次实际突进后的主命中，每队一名护卫，每场一次。', 'partners': []},
    'sunny_day': {'name': '晴天', 'description': f'指定为天气手后，首次原生大招申请{WEATHER_WINDOW_SECONDS:g}秒全场晴天；双方都会受益或受损，每队每场一次。', 'partners': []},
    'rain_dance': {'name': '求雨', 'description': f'指定为天气手后，首次原生大招申请{WEATHER_WINDOW_SECONDS:g}秒全场雨天；双方都会受益或受损，每队每场一次。', 'partners': []},
}
_COMPATIBILITY = {'cut': '草、火、虫、一般、格斗或钢属性可学',
                  'surf': '水属性可学', 'rest': '所有宝可梦可学',
                  'guard': '所有宝可梦可学', 'sunny_day': '火或草属性可学',
                  'rain_dance': '水或电属性可学'}


def ids_for(ruleset=BASE_RULESET):
    validate_ruleset(ruleset)
    return TECHNIQUE_IDS + tuple(_TACTICAL) if enabled(ruleset) else TECHNIQUE_IDS


def catalog(ruleset=BASE_RULESET):
    ids = ids_for(ruleset)
    rows = techniques_catalog() + [{'id': key, **deepcopy(value)} for key, value in _TACTICAL.items()]
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
    return next(dict(row) for row in catalog(TACTICS_RULESET) if row['id'] == technique)
