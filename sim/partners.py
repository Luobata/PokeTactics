"""Optional expedition partners and compatible extra techniques.

Selection never changes a species' native skill. Battle selects the first deployed
member of the chosen evolution family; copies remain ordinary units. Unlocks are
owned by the expedition metagame, not this deterministic combat catalogue.
"""

from copy import deepcopy
from data import pokedex


_PARTNERS = {
    3: {"name": "妙蛙花", "trait_name": "共生花园", "starter": True,
        "trait_description": "首次释放原生大招后，治疗两格内生命比例最低的一名受伤队友，回复其最大生命的20%；每场一次。"},
    6: {"name": "喷火龙", "trait_name": "振翼鼓舞", "starter": True,
        "trait_description": "首次释放原生大招后，两格内最近的至多两名队友各获得18能量；每场一次。"},
    9: {"name": "水箭龟", "trait_name": "并肩坚壳", "starter": True,
        "trait_description": "开场为两格内最近的至多两名队友提供20%减伤，持续6秒；每场一次。"},
    26: {"name": "雷丘", "trait_name": "接力电流", "starter": False,
         "trait_description": "前两次普攻造成伤害后，两格内能量最低的一名队友获得16能量；每场至多两次。"},
    143: {"name": "卡比兽", "trait_name": "分享便当", "starter": False,
          "trait_description": "首次受击后仍存活且生命不高于一半时，治疗两格内生命比例最低的至多两名受伤队友，各回复最大生命的15%；每场一次。"},
}

_TECHNIQUES = {
    "cut": {"name": "居合斩", "description": "首次普攻造成伤害后，追加攻击主目标邻格内的一名其他敌人（普通属性、35威力、物理）；追加命中不回能，每场一次。",
            "partners": (3, 6)},
    "surf": {"name": "冲浪", "description": "首次原生大招造成伤害后，对主目标释放时位置邻格内的至多两名其他敌人追加35威力水属性伤害；追加命中不回能，每场一次。",
             "partners": (9,)},
    "rest": {"name": "睡觉", "description": "首次在生命不高于一半时行动，用该次行动回复自身最大生命的25%，随后休息一个攻击间隔；每场一次。",
             "partners": (3, 6, 9, 26, 143)},
}


def family_ids(partner):
    """Return a fresh ordered family list for a supported partner choice."""
    if type(partner) is not int or partner not in _PARTNERS:
        raise ValueError("unknown partner")
    return list(pokedex().family_of(partner))


def compatible(partner, technique):
    """A blank learning slot is compatible with every supported partner."""
    if type(partner) is not int or partner not in _PARTNERS:
        return False
    return technique is None or (isinstance(technique, str)
                                and technique in _TECHNIQUES
                                and partner in _TECHNIQUES[technique]["partners"])


def validate_loadout(partner, technique=None):
    """Return a fresh canonical loadout, or None; reject incompatible learning.

    Accept either (partner_id, technique) or the Battle team's loadout dictionary.
    This intentionally does not validate account-specific unlock ownership.
    """
    if isinstance(partner, dict):
        if (technique is not None or set(partner) - {"partner", "technique"}
                or "partner" not in partner or partner["partner"] is None):
            raise ValueError("invalid partner loadout fields")
        technique = partner.get("technique")
        partner = partner.get("partner")
    if partner is None and technique is None:
        return None
    if not compatible(partner, technique):
        raise ValueError("unknown partner or incompatible technique")
    return {"partner": partner, "technique": technique}


def techniques_catalog():
    return [{"id": key, **deepcopy(value), "partners": list(value["partners"])}
            for key, value in _TECHNIQUES.items()]


def catalog():
    return [{"id": sid, **deepcopy(value), "family_ids": family_ids(sid),
             "techniques": [key for key in _TECHNIQUES if compatible(sid, key)]}
            for sid, value in _PARTNERS.items()]
