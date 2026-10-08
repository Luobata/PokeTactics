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
}
_ARENA = {
    'rain_dance': {'name': '求雨', 'description': '首次成功完成本命技能后，请求12秒全场雨天，下一战斗刻生效，每位学习者每战一次。雨天水属性直接伤害提高15%、火属性降低10%，打雷必中；双方共享，同刻雨晴抵消，同天气不续时。', 'partners': []},
    'sunny_day': {'name': '晴天', 'description': '首次成功完成本命技能后，请求12秒全场晴天，下一战斗刻生效，每位学习者每战一次。晴天火属性直接伤害提高15%、水属性降低10%；双方共享，同刻雨晴抵消，同天气不续时。', 'partners': []},
    'thunder': {'name': '打雷', 'description': '有效普攻后择机追加一次65威力电属性单体攻击，通常70%命中；雨天必中且无视道具闪避，仍不能命中地面属性。己方有求雨学习者时最多等到开战6秒；未命中也消耗本场一次机会。', 'partners': []},
    'thunderbolt': {'name': '十万伏特', 'description': '首次成功普攻后，追加一次 35 威力电属性单体攻击；可按电属性规则触发麻痹，地面免疫。每场一次。', 'partners': []},
    'ice_beam': {'name': '冰冻光束', 'description': '首次成功普攻后，追加一次 35 威力冰属性单体攻击；可按冰属性规则触发冰冻。每场一次。', 'partners': []},
    'toxic': {'name': '污泥弹', 'description': '首次成功普攻后，追加一次 25 威力毒属性单体攻击；35% 概率中毒，毒与钢属性免疫中毒。每场一次。', 'partners': []},
    'earthquake': {'name': '地震', 'description': '首次成功普攻后，以目标为中心震击目标和至多两只相邻敌人，分别结算 30 威力地面伤害；飞行免疫。每场一次。', 'partners': []},
    'roar': {'name': '吼叫', 'description': '成功普攻后择机将存活目标击退一格。有存活铺钉队友或本队有效岩钉时，优先等能把目标推入岩钉的落点；开战6秒后不再等待铺场。后方无空位时保留次数，每场一次。', 'partners': []},
    'rapid_spin': {'name': '高速旋转', 'description': '成功普攻后择机追加20威力一般属性攻击，并清除自身一格内至多3格敌钉。有存活敌方铺钉手或有效敌钉时，优先等待附近出现敌钉；开战6秒后不再等待。无铺钉威胁时首次成功普攻触发，每场一次。', 'partners': []},
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
                  'thunder': '电、超能或一般属性可学；竞技尼多王也可学',
                  'ice_beam': '水、冰或超能属性可学',
                  'toxic': '毒、虫或草属性可学',
                  'earthquake': '地面、岩或格斗属性可学',
                  'roar': '一般、火、格斗或岩属性可学',
                  'rapid_spin': '一般、水、虫或岩属性可学'}

# Explicit original-move coverage for the arena's mixed attacker. Keep this
# separate from the classic species/type policy and apply it only with a ruleset.
_ARENA_EXTRA = {34: frozenset({'thunderbolt', 'ice_beam', 'thunder'})}


def ids_for(ruleset=BASE_RULESET):
    validate_ruleset(ruleset)
    if ruleset == 'arena_v1':
        return TECHNIQUE_IDS + tuple(_ARENA)
    return TECHNIQUE_IDS + tuple(_TACTICAL) if enabled(ruleset) else TECHNIQUE_IDS


def catalog(ruleset=BASE_RULESET):
    ids = ids_for(ruleset)
    definitions = {**_TACTICAL, **_ARENA} if ruleset == 'arena_v1' else _TACTICAL
    rows = techniques_catalog() + [{'id': key, **deepcopy(value)} for key, value in definitions.items()]
    if ruleset == 'arena_v1':
        rows = [{**row, 'description': '首次成功普攻后，以主目标为中心发动水浪，对主目标和至多两名相邻敌人分别造成35威力水属性伤害。每场一次；不依赖本命技能造成伤害。'}
                if row['id'] == 'surf' else row for row in rows]
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
