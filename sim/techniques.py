"""Species-compatible teaching, independent of ownership and unlock storage."""
from data import pokedex
from partners import techniques_catalog

TECHNIQUE_IDS = ('cut', 'surf', 'rest')
_TYPE_REQUIREMENTS = {
    'cut': frozenset({'GRASS', 'FIRE', 'BUG', 'NORMAL', 'FIGHTING', 'STEEL'}),
    'surf': frozenset({'WATER'}),
    'rest': None,
}


def catalog():
    return [{**row, 'learn_types': sorted(_TYPE_REQUIREMENTS[row['id']] or []),
             'compatibility': {'cut': '草、火、虫、一般、格斗或钢属性可学',
                               'surf': '水属性可学', 'rest': '所有宝可梦可学'}[row['id']]}
            for row in techniques_catalog()]


def compatible_species(species_id, technique):
    if type(species_id) is not int or species_id not in pokedex().species:
        return False
    if technique is None:
        return True
    if not isinstance(technique, str) or technique not in _TYPE_REQUIREMENTS:
        return False
    allowed = _TYPE_REQUIREMENTS[technique]
    return allowed is None or bool(allowed.intersection(pokedex().species[species_id]['types']))


def validate_learning(species_id, technique):
    if not compatible_species(species_id, technique):
        rule = next((t['compatibility'] for t in catalog() if t['id'] == technique), '未知招式')
        raise ValueError('无法学习：' + rule)
    return technique


def view(technique):
    if technique is None:
        return None
    return next(dict(row) for row in catalog() if row['id'] == technique)
