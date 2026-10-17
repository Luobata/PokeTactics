"""Authored family-form presentation, independent of battle rules.

The two packs name every supported form explicitly. Native identities are
resolved from the real species kit; a shared mechanic never substitutes a
different species' choreography.
"""
from functools import lru_cache

import hoenn_vfx
import preform_vfx

SPECIES = hoenn_vfx.SPECIES | preform_vfx.SPECIES


def _pack(sid):
    return hoenn_vfx if sid in hoenn_vfx.SPECIES else preform_vfx if sid in preform_vfx.SPECIES else None


@lru_cache(maxsize=151)
def native_spec(sid):
    if sid not in SPECIES:
        return None
    from arena_skills import skill_of
    return skill_of(sid)


@lru_cache(maxsize=1)
def _unique_moves():
    # Some older preforms intentionally share a native ID with their final
    # form. Those need the actual caster ID, not a reverse-ID guess.
    return {native_spec(sid)['id']: sid for sid in sorted(SPECIES)
            if native_spec(sid)['id'].startswith(('hoenn_', 'family_strike_'))}


def species_for_key(key):
    return _unique_moves().get(key)


def matches_native(sid, key):
    spec = native_spec(sid)
    return bool(spec and spec['id'] == key)


def matches_packet(key, packet_key):
    sid = species_for_key(key)
    spec = native_spec(sid)
    return bool(spec and packet_key in (spec['id'], spec['arch']))


def attack_label(sid):
    pack = _pack(sid)
    return pack.attack_label(sid) if pack else None


def attack_motif(sid):
    pack = _pack(sid)
    if not pack:
        return None
    return (pack.attack_label(sid),
            lambda d, x, y, k, angle, hit: pack.draw_attack_motif(d, sid, x, y, k, angle, hit))


def draw(layer, sid, source, target, phase, progress, config, *, kind='cast', emitters=(), secondary=False):
    pack = _pack(sid)
    if not pack:
        return False
    return pack.draw(layer, sid, source, target, phase, progress, config,
                     kind=kind, emitters=emitters, secondary=secondary)


def describe(sid):
    pack = _pack(sid)
    if not pack:
        return None
    return {**pack.describe(sid), 'authored': True, 'style': '家族像素演出',
            'group': '丰缘家族' if pack is hoenn_vfx else '前置形态与分支',
            'targeting': native_spec(sid)['targeting'],
            'category': native_spec(sid)['category'],
            'outcome_source': 'authoritative_cast_packets',
            'body_scope': '原贴图整身发力；部件覆盖另列'}
