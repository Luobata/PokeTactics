#!/usr/bin/env python3
"""Seed assets/motion and assets/vfx from the existing Python motion tables.

Run once (or after changing the Python tables) to regenerate the packs:
    python3 tools/acceptance/motion_seed.py [--check]

* roles.json    — hand-authored role archetype clips (melee / ranged / support /
                  tank) for idle, walk, attack_melee, attack_ranged, cast, hit,
                  ko and victory, exaggerated to read at the browser scale.
* families.json — family_motion._ACTIONS (25 whole-body templates) converted
                  to eased keyframe phases and exaggerated ×2.4.
* species.json  — per-species bindings: family archetype, authored idle loops
                  converted from motion.species_motion, and a body weight
                  derived from base stats (drives anticipation/recovery).
* assets/vfx/core.json — type palettes/materials, projectile families,
                  layered recipes and screen (camera) rules.

The workbench edits these files afterwards; ``--check`` only reports whether a
regenerated pack would differ from the checked-in file.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
for _p in (str(ROOT), str(ROOT / 'sim'), str(ROOT / 'tools' / 'mockups'), str(Path(__file__).resolve().parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import motion_schema  # noqa: E402

E = 'easeInOutQuad'
REST = [0, 0, 0, 100, 100, 1]


def key(at, dx=0, dy=0, angle=0, sx=100, sy=100, visible=1, ease=E):
    clamp = lambda v, lo, hi: max(lo, min(hi, int(round(v))))
    return [round(at, 3), clamp(dx, -48, 48), clamp(dy, -48, 48), clamp(angle, -180, 180),
            clamp(sx, 50, 150), clamp(sy, 50, 150), visible, ease]


def clip(slot, period=None, note=None, **phases):
    row = {'slot': slot, 'phases': phases}
    if period is not None:
        row['period'] = period
    if note:
        row['note'] = note
    return row


# ------------------------------------------------------------- role archetypes
def role_pack():
    clips = {
        'role.idle.breathe': clip('idle', 1.6, '通用呼吸：吸气拉高、呼气压扁',
            loop=[key(0, ease=E), key(.5, 0, -2, 0, 97, 104), key(1)]),
        'role.idle.heavy': clip('idle', 2.3, '重型：慢速下沉呼吸',
            loop=[key(0), key(.55, 0, 1, 0, 104, 96), key(1)]),
        'role.idle.float': clip('idle', 1.3, '漂浮：上下浮动带轻摆',
            loop=[key(0), key(.25, 0, -4, -2, 99, 102), key(.5, 0, -6, 0, 98, 103),
                  key(.75, 0, -3, 2, 99, 101), key(1)]),
        'role.idle.bounce': clip('idle', .9, '轻快：短促弹跳',
            loop=[key(0, ease='easeOutQuad'), key(.35, 0, -4, 0, 96, 105, ease='easeInQuad'),
                  key(.7, 0, 0, 0, 105, 95), key(1)]),
        'role.walk.hop': clip('walk', .36, '小跳步',
            loop=[key(0), key(.25, 0, -6, -4, 95, 107), key(.5, 0, 0, 0, 107, 93),
                  key(.75, 0, -6, 4, 95, 107), key(1)]),
        'role.walk.stomp': clip('walk', .5, '重步：左右摇摆',
            loop=[key(0), key(.25, 0, -2, -6, 102, 98), key(.5, 0, 1, 0, 106, 94),
                  key(.75, 0, -2, 6, 102, 98), key(1)]),
        'role.melee.attack': clip('attack_melee', None, '后撤蓄力→冲刺→命中挤压→回位',
            anticipation=[key(0, ease='easeOutCubic'), key(.7, -10, 4, -12, 112, 88),
                          key(1, -11, 4, -14, 114, 86, ease='easeInQuad')],
            dash=[key(0, -11, 4, -14, 114, 86, ease='easeInQuad'), key(1, 6, -2, 14, 86, 116)],
            contact=[key(0, 6, -2, 14, 86, 116, ease='easeOutBack'), key(.3, 10, 1, 18, 120, 84, ease='easeOutQuad'),
                     key(1, 4, 0, 6, 104, 97)],
            recover=[key(0, 4, 0, 6, 104, 97, ease='easeOutQuad'), key(.55, -2, -3, -3, 98, 103), key(1)]),
        'role.ranged.attack': clip('attack_ranged', None, '后坐蓄力→射出反冲→回稳',
            anticipation=[key(0, ease='easeOutCubic'), key(.75, -6, 2, -8, 108, 93), key(1, -7, 2, -9, 110, 92)],
            release=[key(0, -7, 2, -9, 110, 92, ease='easeOutExpo'), key(.25, 8, -1, 8, 90, 112, ease='easeOutQuad'),
                     key(1, -6, 0, -5, 104, 97)],
            recover=[key(0, -6, 0, -5, 104, 97, ease='easeOutBack'), key(1)]),
        'role.melee.cast': clip('cast', None, '下沉聚力→爆发前扑→回收',
            anticipation=[key(0, ease='easeOutQuad'), key(.5, -4, 4, -6, 110, 90),
                          key(.9, -6, 6, -9, 116, 85), key(1, -6, 6, -10, 117, 84)],
            release=[key(0, -6, 6, -10, 117, 84, ease='easeOutExpo'), key(.3, 12, -4, 14, 86, 118, ease='easeOutQuad'),
                     key(1, 4, 0, 4, 104, 97)],
            recover=[key(0, 4, 0, 4, 104, 97, ease='easeOutBack'), key(1)]),
        'role.ranged.cast': clip('cast', None, '升空蓄能→释放下压→回落',
            anticipation=[key(0, ease='easeOutQuad'), key(.5, 0, -6, 0, 94, 108),
                          key(.85, -2, -10, -3, 90, 114), key(1, -2, -11, -3, 89, 115)],
            release=[key(0, -2, -11, -3, 89, 115, ease='easeOutExpo'), key(.3, 4, 3, 4, 118, 86, ease='easeOutQuad'),
                     key(1, 0, 0, 0, 104, 97)],
            recover=[key(0, 0, 0, 0, 104, 97, ease='easeOutBack'), key(1)]),
        'role.support.cast': clip('cast', None, '漂浮引导→展开→柔和回落',
            anticipation=[key(0, ease='easeInOutQuad'), key(.4, 0, -8, -4, 98, 104),
                          key(.8, 0, -13, 4, 96, 106), key(1, 0, -14, 0, 95, 107)],
            release=[key(0, 0, -14, 0, 95, 107, ease='easeOutBack'), key(.35, 0, -8, 0, 114, 92),
                     key(1, 0, -3, 0, 102, 99)],
            recover=[key(0, 0, -3, 0, 102, 99, ease='easeOutQuad'), key(1)]),
        'role.support.attack': clip('attack_ranged', None, '轻点：小幅前送',
            anticipation=[key(0, ease='easeOutQuad'), key(1, -4, -4, -6, 104, 98)],
            release=[key(0, -4, -4, -6, 104, 98, ease='easeOutBack'), key(.3, 6, -1, 6, 96, 106),
                     key(1, 0, 0, 0, 102, 99)],
            recover=[key(0, 0, 0, 0, 102, 99), key(1)]),
        'role.tank.attack': clip('attack_melee', None, '抬身→重踏冲撞→震地',
            anticipation=[key(0, ease='easeOutQuad'), key(.6, -4, -10, -6, 94, 112),
                          key(1, -5, -12, -8, 92, 114, ease='easeInCubic')],
            dash=[key(0, -5, -12, -8, 92, 114, ease='easeInCubic'), key(1, 4, 2, 6, 110, 90)],
            contact=[key(0, 4, 2, 6, 110, 90, ease='easeOutBounce'), key(.25, 4, 6, 0, 124, 80),
                     key(1, 2, 1, 0, 104, 97)],
            recover=[key(0, 2, 1, 0, 104, 97, ease='easeInOutQuad'), key(1)]),
        'role.tank.cast': clip('cast', None, '蓄压下蹲→跃起→重踏冲击波',
            anticipation=[key(0, ease='easeOutQuad'), key(.6, 0, 6, 0, 118, 84), key(1, 0, 7, 0, 120, 82)],
            release=[key(0, 0, 7, 0, 120, 82, ease='easeOutExpo'), key(.3, 0, -14, 0, 88, 116, ease='easeInCubic'),
                     key(.55, 0, 6, 0, 126, 78, ease='easeOutBounce'), key(1, 0, 1, 0, 104, 97)],
            recover=[key(0, 0, 1, 0, 104, 97), key(1)]),
        'role.hit.react': clip('hit', None, '受击：后仰挤压→回弹',
            react=[key(0, ease='easeOutExpo'), key(.18, -8, 0, -10, 88, 112, ease='easeOutQuad'),
                   key(.55, -4, 0, -3, 106, 95, ease='easeOutBack'), key(1)]),
        'role.hit.heavy': clip('hit', None, '重型受击：小幅下沉',
            react=[key(0, ease='easeOutExpo'), key(.2, -4, 2, -4, 108, 92, ease='easeOutQuad'), key(1)]),
        'role.ko.topple': clip('ko', None, '倒下：后仰→侧倒→消散',
            fall=[key(0, ease='easeOutQuad'), key(.25, -4, -6, -10, 92, 110, ease='easeInQuad'),
                  key(.65, -8, 8, -50, 104, 84, ease='easeInQuad'), key(1, -10, 12, -80, 112, 60, 0)]),
        'role.ko.sink': clip('ko', None, '沉没：压扁下沉消散',
            fall=[key(0, ease='easeOutQuad'), key(.3, 0, -3, 0, 92, 110, ease='easeInCubic'),
                  key(1, 0, 10, 0, 130, 50, 0)]),
        'role.victory.hop': clip('victory', .6, '胜利小跳',
            loop=[key(0, ease='easeOutQuad'), key(.4, 0, -10, 0, 94, 108, ease='easeInQuad'),
                  key(.7, 0, 0, 0, 110, 90, ease='easeOutQuad'), key(1)]),
    }
    archetypes = {
        'melee': {'attack': 'melee', 'clips': {
            'idle': 'role.idle.bounce', 'walk': 'role.walk.hop', 'attack_melee': 'role.melee.attack',
            'attack_ranged': 'role.ranged.attack', 'cast': 'role.melee.cast', 'hit': 'role.hit.react',
            'ko': 'role.ko.topple', 'victory': 'role.victory.hop'},
            'timing': {'anticipation': .20, 'recover': .22, 'cast_anticipation': .40, 'cast_recover': .30,
                       'weight': .35, 'dash_speed': 950, 'offset_range': .06, 'idle_period': 1.2}},
        'ranged': {'attack': 'ranged', 'clips': {
            'idle': 'role.idle.breathe', 'walk': 'role.walk.hop', 'attack_melee': 'role.melee.attack',
            'attack_ranged': 'role.ranged.attack', 'cast': 'role.ranged.cast', 'hit': 'role.hit.react',
            'ko': 'role.ko.topple', 'victory': 'role.victory.hop'},
            'timing': {'anticipation': .16, 'recover': .16, 'cast_anticipation': .38, 'cast_recover': .26,
                       'weight': .25, 'dash_speed': 900, 'offset_range': .05, 'idle_period': 1.6}},
        'support': {'attack': 'support', 'clips': {
            'idle': 'role.idle.float', 'walk': 'role.walk.hop', 'attack_melee': 'role.melee.attack',
            'attack_ranged': 'role.support.attack', 'cast': 'role.support.cast', 'hit': 'role.hit.react',
            'ko': 'role.ko.sink', 'victory': 'role.victory.hop'},
            'timing': {'anticipation': .24, 'recover': .20, 'cast_anticipation': .46, 'cast_recover': .32,
                       'weight': .2, 'dash_speed': 800, 'offset_range': .07, 'idle_period': 1.4}},
        'tank': {'attack': 'tank', 'clips': {
            'idle': 'role.idle.heavy', 'walk': 'role.walk.stomp', 'attack_melee': 'role.tank.attack',
            'attack_ranged': 'role.ranged.attack', 'cast': 'role.tank.cast', 'hit': 'role.hit.heavy',
            'ko': 'role.ko.sink', 'victory': 'role.victory.hop'},
            'timing': {'anticipation': .30, 'recover': .30, 'cast_anticipation': .52, 'cast_recover': .36,
                       'weight': .8, 'dash_speed': 650, 'offset_range': .06, 'idle_period': 2.2}},
    }
    for clip_id, parts in ROLE_PARTS.items():
        clips[clip_id]['parts'] = parts
    return {'schema_version': 1, 'kind': 'motion_pack', 'name': 'roles',
            'description': '角色定位原型（近战/远程/辅助/坦克）动作片段、分件形变与节奏；单位：源精灵像素，前进方向为 +dx。',
            'clips': clips, 'archetypes': archetypes}


def pk(at, lean=0, head_x=0, head_y=0, belly=0, wobble=0, ease=E):
    """Part-deformation key: [at, lean, head_x, head_y, belly%, wobble, ease] (source px)."""
    r = lambda v: round(v, 1)
    return [round(at, 3), r(lean), r(head_x), r(head_y), r(belly), r(wobble), ease]


# Band-mesh deformation of the single cel: feet stay planted, the body leans
# (+ = toward the target), the head band bobs, the belly widens, wobble ripples.
ROLE_PARTS = {
    'role.idle.breathe': {'loop': [pk(0), pk(.5, 0, 0, 1.5, 5), pk(1)]},
    'role.idle.heavy': {'loop': [pk(0), pk(.55, 0, 0, 2, 9), pk(1)]},
    'role.idle.float': {'loop': [pk(0), pk(.25, 1.5, 1.5, -1), pk(.5, 0, 0, -2, 3), pk(.75, -1.5, -1.5, -1), pk(1)]},
    'role.idle.bounce': {'loop': [pk(0, ease='easeOutQuad'), pk(.35, 0, 0, -2, -4, 0, 'easeInQuad'), pk(.7, 0, 0, 2.5, 8), pk(1)]},
    'role.walk.hop': {'loop': [pk(0), pk(.25, 4, 2, -1), pk(.5, 2, 0, 2, 6), pk(.75, 4, 2, -1), pk(1)]},
    'role.walk.stomp': {'loop': [pk(0), pk(.25, 2, -2, 0, 4), pk(.5, 0, 0, 3, 10), pk(.75, 2, 2, 0, 4), pk(1)]},
    'role.melee.attack': {
        'anticipation': [pk(0, ease='easeOutCubic'), pk(.7, -9, -5, 2, 8), pk(1, -10, -6, 2, 10, 0, 'easeInQuad')],
        'dash': [pk(0, -10, -6, 2, 10, 0, 'easeInQuad'), pk(1, 12, 6, -2, -8)],
        'contact': [pk(0, 12, 6, -2, -8, 0, 'easeOutBack'), pk(.3, 14, 8, 2, 12, 4), pk(1, 5, 2, 0, 4, 2)],
        'recover': [pk(0, 5, 2, 0, 4, 2, 'easeOutQuad'), pk(.6, -2, -1, -1, -2), pk(1)]},
    'role.ranged.attack': {
        'anticipation': [pk(0, ease='easeOutCubic'), pk(1, -6, -4, 1, 6)],
        'release': [pk(0, -6, -4, 1, 6, 0, 'easeOutExpo'), pk(.25, 7, 5, -1, -6, 2), pk(1, -4, -2, 0, 2)],
        'recover': [pk(0, -4, -2, 0, 2, 0, 'easeOutBack'), pk(1)]},
    'role.melee.cast': {
        'anticipation': [pk(0), pk(.6, -6, -4, 3, 14), pk(1, -7, -5, 4, 18, 1)],
        'release': [pk(0, -7, -5, 4, 18, 1, 'easeOutExpo'), pk(.3, 14, 8, -3, -10, 3), pk(1, 3, 1, 0, 2)],
        'recover': [pk(0, 3, 1, 0, 2, 0, 'easeOutBack'), pk(1)]},
    'role.ranged.cast': {
        'anticipation': [pk(0), pk(.5, -2, -3, -3, 6), pk(1, -3, -4, -4, 12, 1.5)],
        'release': [pk(0, -3, -4, -4, 12, 1.5, 'easeOutExpo'), pk(.3, 6, 5, 2, -8, 2), pk(1)],
        'recover': [pk(0, ease='easeOutBack'), pk(1)]},
    'role.support.cast': {
        'anticipation': [pk(0), pk(.4, 0, 0, -3, 6, 1), pk(.8, 0, 0, -4, 10, 2), pk(1, 0, 0, -4, 10, 2)],
        'release': [pk(0, 0, 0, -4, 10, 2, 'easeOutBack'), pk(.35, 2, 2, 2, -4), pk(1)],
        'recover': [pk(0), pk(1)]},
    'role.support.attack': {
        'anticipation': [pk(0), pk(1, -3, -3, -1, 4)],
        'release': [pk(0, -3, -3, -1, 4, 0, 'easeOutBack'), pk(.3, 5, 4), pk(1)],
        'recover': [pk(0), pk(1)]},
    'role.tank.attack': {
        'anticipation': [pk(0), pk(.6, -4, -2, -4, -6), pk(1, -5, -3, -5, -8, 0, 'easeInCubic')],
        'dash': [pk(0, -5, -3, -5, -8, 0, 'easeInCubic'), pk(1, 8, 4, 2, 10)],
        'contact': [pk(0, 8, 4, 2, 10, 0, 'easeOutBounce'), pk(.25, 6, 2, 6, 24, 5), pk(1, 2, 0, 1, 4)],
        'recover': [pk(0, 2, 0, 1, 4), pk(1)]},
    'role.tank.cast': {
        'anticipation': [pk(0), pk(.6, 0, 0, 4, 18), pk(1, 0, 0, 5, 22)],
        'release': [pk(0, 0, 0, 5, 22, 0, 'easeOutExpo'), pk(.3, 0, 0, -5, -12), pk(.55, 0, 0, 6, 26, 6, 'easeOutBounce'), pk(1, 0, 0, 1, 4)],
        'recover': [pk(0, 0, 0, 1, 4), pk(1)]},
    'role.hit.react': {'react': [pk(0, ease='easeOutExpo'), pk(.18, -7, -6, 1, -8, 4), pk(.55, -2, 2, 0, 6, 2, 'easeOutBack'), pk(1)]},
    'role.hit.heavy': {'react': [pk(0, ease='easeOutExpo'), pk(.2, -3, -3, 2, 10, 2), pk(1)]},
    'role.ko.topple': {'fall': [pk(0), pk(.25, -4, -5, -2, -6, 3, 'easeInQuad'), pk(.65, -12, -8, 4, 6, 1), pk(1, -16, -10, 6, 12)]},
    'role.ko.sink': {'fall': [pk(0), pk(.3, 0, 0, -3, -6, 2, 'easeInCubic'), pk(1, 0, 0, 8, 30)]},
    'role.victory.hop': {'loop': [pk(0, ease='easeOutQuad'), pk(.4, 2, 0, -4, -6, 0, 'easeInQuad'), pk(.7, 0, 0, 3, 10), pk(1)]},
}


# ------------------------------------------------------------- family templates
def _convert(frames, start, *, end=None, gain=2.4, ease='easeInOutQuad', first_ease=None):
    """Python (dx, dy, sx, sy, deg, dissolve) frames → eased 0..1 keyframes."""
    def pose(frame):
        dx, dy, sx, sy, angle = frame[:5]
        return [dx * gain, dy * gain, angle * 1.8, 100 + (sx - 100) * gain, 100 + (sy - 100) * gain]
    keys = [key(0, *start, ease=first_ease or ease)]
    n = len(frames)
    for index, frame in enumerate(frames):
        at = (index + 1) / n
        values = end if (end is not None and index == n - 1) else pose(frame)
        keys.append(key(at, *values, ease=ease))
    last = keys[-1]
    return keys, [last[1], last[2], last[3], last[4], last[5]]


def family_pack():
    import family_motion
    clips = {}
    rest = [0, 0, 0, 100, 100]
    for arch, actions in sorted(family_motion._ACTIONS.items()):
        for kind, slot in (('attack', 'attack_ranged'), ('cast', 'cast')):
            row = actions[kind]
            windup, pose = _convert(row['windup'], rest, first_ease='easeOutCubic')
            strike, pose = _convert(row['strike'], pose, first_ease='easeOutExpo', ease='easeOutQuad')
            recover, _ = _convert(row['recover'], pose, end=rest, first_ease='easeOutBack')
            clips[f'fam.{arch}.{kind}'] = clip(
                slot, None, f'由 family_motion「{arch}」{kind} 模板转换（×2.4 夸张）',
                anticipation=windup, release=strike, recover=recover)
    return {'schema_version': 1, 'kind': 'motion_pack', 'name': 'families',
            'description': '25 种家族整身动作模板（family_motion.py）转换为缓动关键帧。',
            'clips': clips}


# ------------------------------------------------------------- species bindings
def _species_ids():
    import arena
    import arena_families
    return sorted(set(arena.build_templates()) | set(arena_families.SPECIES_FAMILY))


def _weight(record):
    base = record.get('base') or {}
    if isinstance(base, str):
        return .4
    hp, defense, speed = base.get('hp', 60), base.get('defense', 60), base.get('speed', 60)
    return round(max(0., min(1., (hp + defense - speed * .8 - 50) / 160)), 2)


def species_pack():
    import family_motion
    import motion
    from data import pokedex
    clips, species = {}, {}
    dex = pokedex()
    for sid in _species_ids():
        row = {}
        profile = family_motion.profile_of(sid)
        if profile is not None and sid not in family_motion.CLASSIC_MOTION_ONLY:
            arch = profile['archetype']
            row['family'] = arch
            row['clips'] = {'attack_ranged': f'fam.{arch}.attack', 'cast': f'fam.{arch}.cast'}
        authored = motion.species_motion.get(sid, {})
        idle = authored.get('idle')
        if idle and len(idle) >= 2 and any(tuple(frame[:5]) != (0, 0, 100, 100, 0) for frame in idle):
            n = len(idle)
            keys = []
            for index, frame in enumerate(idle[:15]):
                dx, dy, sx, sy, angle = frame[:5]
                keys.append(key(index / n, dx * 2, dy * 2.5, angle * 1.5,
                                100 + (sx - 100) * 2.2, 100 + (sy - 100) * 2.2, ease='easeInOutQuad'))
            keys.append(key(1, ease='linear'))
            clips[f'sp.{sid}.idle'] = clip('idle', round(max(.8, min(4., n * .1 * 1.5)), 2),
                                           '由 motion.py 手绘待机循环转换', loop=keys)
            row.setdefault('clips', {})['idle'] = f'sp.{sid}.idle'
        try:
            record = dex.species_record(sid)
        except (KeyError, ValueError):
            record = {}
        row['timing'] = {'weight': _weight(record)}
        species[str(sid)] = row
    return {'schema_version': 1, 'kind': 'motion_pack', 'name': 'species',
            'description': '逐物种绑定：家族动作模板、手绘待机循环与体重（影响蓄力/收招时长）。',
            'clips': clips, 'species': species}


# ------------------------------------------------------------- VFX
PALETTES = {
    'NORMAL': ['#fffbe8', '#f4ecd0', '#d8cfae', '#8c8468'],
    'FIRE': ['#fff6c4', '#ffc35a', '#ff7a2e', '#b8321a'],
    'WATER': ['#effcff', '#9fe3ff', '#3fa7f0', '#1d5fa8'],
    'ELECTRIC': ['#ffffff', '#fff27a', '#ffd21f', '#c08a00'],
    'GRASS': ['#f4ffd8', '#b6f07a', '#58c24a', '#2c7a32'],
    'ICE': ['#ffffff', '#d8f8ff', '#8fe0f5', '#4a9ec4'],
    'FIGHTING': ['#fff0e0', '#ffb08a', '#e0623e', '#8c2c1e'],
    'POISON': ['#f8e8ff', '#dba6ff', '#a85ae0', '#5e2a8c'],
    'GROUND': ['#fff4dc', '#e8c98a', '#bf9550', '#6e5028'],
    'FLYING': ['#ffffff', '#e2ecff', '#a8c2f5', '#5c78b8'],
    'PSYCHIC': ['#fff0fa', '#ffaee0', '#f05aa8', '#9a2a6a'],
    'BUG': ['#f8ffd8', '#d6ec7a', '#9ac23a', '#5a7a1c'],
    'ROCK': ['#f6f0e0', '#d8c8a0', '#a8906a', '#5e4e36'],
    'GHOST': ['#f4ecff', '#c4aef5', '#7e62c8', '#3e2c78'],
    'DRAGON': ['#f0ecff', '#b8a8ff', '#6e58f0', '#38259c'],
    'DARK': ['#f0e8e0', '#b0a090', '#6a5a50', '#2a2220'],
    'STEEL': ['#ffffff', '#e0e6ee', '#a8b4c4', '#5c6878'],
    'FAIRY': ['#fff4fc', '#ffd0f0', '#f59ad8', '#b0508e'],
    'HEAL': ['#f4fff0', '#c4ffb8', '#6ee07a', '#2c9a48'],
    'SHIELD': ['#ffffff', '#d8f6ff', '#8fd8f5', '#3c8cb8'],
    'KO': ['#ffffff', '#fff2d0', '#ffcf6a', '#a8601e'],
}
MATERIALS = {
    'NORMAL': {'particle': 'sparkle', 'gravity': 30, 'drag': .9, 'count': 8, 'size': [2, 4], 'life': [.25, .5], 'speed': [60, 160]},
    'FIRE': {'particle': 'ember', 'gravity': -120, 'drag': .86, 'count': 16, 'size': [2, 6], 'life': [.3, .7], 'speed': [60, 220]},
    'WATER': {'particle': 'droplet', 'gravity': 420, 'drag': .95, 'count': 14, 'size': [2, 5], 'life': [.3, .6], 'speed': [90, 260]},
    'ELECTRIC': {'particle': 'arc', 'gravity': 0, 'drag': .8, 'count': 10, 'size': [6, 16], 'life': [.12, .3], 'speed': [80, 240]},
    'GRASS': {'particle': 'leaf', 'gravity': 60, 'drag': .9, 'count': 12, 'size': [3, 7], 'life': [.4, .9], 'speed': [60, 200], 'spin': 6},
    'ICE': {'particle': 'shard', 'gravity': 200, 'drag': .92, 'count': 12, 'size': [3, 8], 'life': [.3, .6], 'speed': [100, 280], 'spin': 4},
    'FIGHTING': {'particle': 'impact_ring', 'gravity': 0, 'drag': .8, 'count': 3, 'size': [10, 26], 'life': [.15, .3], 'speed': [0, 30]},
    'POISON': {'particle': 'bubble', 'gravity': -70, 'drag': .9, 'count': 10, 'size': [3, 7], 'life': [.4, .9], 'speed': [30, 120]},
    'GROUND': {'particle': 'dust', 'gravity': 140, 'drag': .85, 'count': 14, 'size': [3, 8], 'life': [.35, .7], 'speed': [50, 180]},
    'FLYING': {'particle': 'gust', 'gravity': -10, 'drag': .9, 'count': 8, 'size': [8, 18], 'life': [.25, .5], 'speed': [80, 220]},
    'PSYCHIC': {'particle': 'ring', 'gravity': 0, 'drag': .9, 'count': 5, 'size': [8, 26], 'life': [.3, .6], 'speed': [0, 40]},
    'BUG': {'particle': 'mote', 'gravity': 20, 'drag': .9, 'count': 12, 'size': [2, 4], 'life': [.3, .6], 'speed': [80, 220]},
    'ROCK': {'particle': 'debris', 'gravity': 520, 'drag': .96, 'count': 12, 'size': [3, 8], 'life': [.4, .8], 'speed': [100, 300], 'spin': 5},
    'GHOST': {'particle': 'wisp', 'gravity': -60, 'drag': .9, 'count': 8, 'size': [4, 10], 'life': [.5, 1.], 'speed': [20, 100]},
    'DRAGON': {'particle': 'flame', 'gravity': -40, 'drag': .88, 'count': 14, 'size': [3, 8], 'life': [.3, .7], 'speed': [80, 240]},
    'DARK': {'particle': 'slash', 'gravity': 0, 'drag': .85, 'count': 6, 'size': [8, 20], 'life': [.15, .35], 'speed': [40, 160]},
    'STEEL': {'particle': 'spark', 'gravity': 380, 'drag': .94, 'count': 14, 'size': [1, 3], 'life': [.2, .45], 'speed': [140, 380]},
    'FAIRY': {'particle': 'sparkle', 'gravity': -20, 'drag': .9, 'count': 12, 'size': [2, 5], 'life': [.4, .8], 'speed': [40, 160]},
}
TYPE_PROJECTILE = {
    'NORMAL': 'straight', 'FIRE': 'straight', 'WATER': 'beam', 'ELECTRIC': 'homing', 'GRASS': 'volley',
    'ICE': 'volley', 'FIGHTING': 'straight', 'POISON': 'arc', 'GROUND': 'ground', 'FLYING': 'homing',
    'PSYCHIC': 'beam', 'BUG': 'volley', 'ROCK': 'arc', 'GHOST': 'homing', 'DRAGON': 'beam',
    'DARK': 'homing', 'STEEL': 'straight', 'FAIRY': 'homing',
}


def L(layer, shape, at='impact', **extra):
    return {'layer': layer, 'shape': shape, 'at': at, **extra}


def vfx_pack():
    recipes = {
        'melee_slash': {'layers': [
            L('trail', 'afterimage', 'release', duration=.18),
            L('impact', 'slash_arc', 'impact', palette='@type', size=56, duration=.22, curve='easeOutCubic'),
            L('impact', 'sparks', 'impact', palette='@type', count=10, duration=.35, particle='@type'),
            L('impact', 'flash', 'impact', palette='KO', size=34, duration=.1)]},
        'ranged_shot': {'layers': [
            L('charge', 'glow', 'anticipation', palette='@type', size=16, duration=.2),
            L('projectile', 'family', 'release', family='@type', palette='@type', size=9),
            L('impact', 'burst', 'impact', palette='@type', size=34, count=12, duration=.32, particle='@type'),
            L('impact', 'ring', 'impact', palette='@type', size=40, duration=.25, curve='easeOutQuad')]},
        'cast_burst': {'layers': [
            L('charge', 'converge', 'anticipation', palette='@type', count=14, size=46, particle='@type'),
            L('aura', 'glow', 'anticipation', palette='@type', size=46, intensity=1.2),
            L('projectile', 'family', 'release', family='@type', palette='@type', size=14),
            L('impact', 'burst', 'impact', palette='@type', size=64, count=22, duration=.45, particle='@type'),
            L('impact', 'ring', 'impact', palette='@type', size=86, duration=.4, curve='easeOutCubic'),
            L('ground', 'scorch', 'impact', palette='@type', size=60, duration=1.2, alpha=.5),
            L('screen', 'flash', 'impact', palette='@type', duration=.12, alpha=.35)]},
        'support_channel': {'layers': [
            L('aura', 'ring_rise', 'anticipation', palette='HEAL', size=40, duration=.5),
            L('charge', 'spiral', 'anticipation', palette='@type', count=10, size=36, particle='sparkle'),
            L('projectile', 'family', 'release', family='homing', palette='HEAL', size=8),
            L('aura', 'heal_plus', 'impact', palette='HEAL', count=6, size=34, duration=.7, target='target')]},
        'tank_stomp': {'layers': [
            L('impact', 'flash', 'impact', palette='KO', size=40, duration=.1),
            L('ground', 'shockwave', 'impact', palette='GROUND', size=90, duration=.45, curve='easeOutCubic'),
            L('impact', 'shards', 'impact', palette='ROCK', count=10, duration=.5, particle='debris'),
            L('ground', 'crack', 'impact', palette='GROUND', size=46, duration=1.4, alpha=.7)]},
        'heal_channel': {'layers': [
            L('aura', 'ring_rise', 'anticipation', palette='HEAL', size=42, duration=.6),
            L('projectile', 'family', 'release', family='homing', palette='HEAL', size=8),
            L('aura', 'heal_plus', 'impact', palette='HEAL', count=8, size=40, duration=.8, target='target'),
            L('aura', 'sparkle_up', 'impact', palette='HEAL', count=12, size=40, duration=.8, target='target')]},
        'shield_ring': {'layers': [
            L('charge', 'ring', 'anticipation', palette='SHIELD', size=40, duration=.35),
            L('aura', 'shield_dome', 'impact', palette='SHIELD', size=48, duration=.9, target='target'),
            L('impact', 'flash', 'impact', palette='SHIELD', size=30, duration=.12)]},
        'area_quake': {'layers': [
            L('charge', 'converge', 'anticipation', palette='@type', count=12, size=50, particle='@type'),
            L('ground', 'shockwave', 'impact', palette='@type', size=130, duration=.55, curve='easeOutCubic', target='target'),
            L('impact', 'burst', 'impact', palette='@type', size=60, count=20, duration=.5, particle='@type'),
            L('ground', 'crack', 'impact', palette='@type', size=70, duration=1.6, alpha=.6, target='target')]},
        'terrain_spikes': {'layers': [
            L('charge', 'glow', 'anticipation', palette='ROCK', size=30),
            L('projectile', 'family', 'release', family='ground', palette='ROCK', size=12),
            L('ground', 'spikes', 'impact', palette='ROCK', count=7, size=60, duration=2.4, target='target'),
            L('impact', 'shards', 'impact', palette='ROCK', count=14, duration=.6, particle='debris')]},
        'root_vines': {'layers': [
            L('projectile', 'family', 'release', family='ground', palette='GRASS', size=10),
            L('ground', 'vines', 'impact', palette='GRASS', count=6, size=46, duration=1.6, target='target'),
            L('impact', 'petals', 'impact', palette='GRASS', count=10, duration=.6, particle='leaf')]},
        'poison_cloud': {'layers': [
            L('projectile', 'family', 'release', family='arc', palette='POISON', size=11),
            L('ground', 'puddle', 'impact', palette='POISON', size=58, duration=1.6, alpha=.7, target='target'),
            L('impact', 'splash', 'impact', palette='POISON', count=14, duration=.5, particle='bubble')]},
        'chain_lightning': {'layers': [
            L('charge', 'sparks', 'anticipation', palette='ELECTRIC', count=10, size=36, particle='arc'),
            L('projectile', 'family', 'release', family='beam', palette='ELECTRIC', size=8),
            L('impact', 'cross', 'impact', palette='ELECTRIC', size=50, duration=.25),
            L('impact', 'sparks', 'impact', palette='ELECTRIC', count=14, duration=.35, particle='arc'),
            L('screen', 'flash', 'impact', palette='ELECTRIC', duration=.08, alpha=.3)]},
        'drain_siphon': {'layers': [
            L('projectile', 'family', 'release', family='beam', palette='@type', size=6),
            L('impact', 'burst', 'impact', palette='@type', size=40, count=10, duration=.35, particle='@type'),
            L('aura', 'heal_plus', 'impact', palette='HEAL', count=4, size=30, duration=.6, target='actor')]},
        'combo_flurry': {'layers': [
            L('trail', 'afterimage', 'release', duration=.25),
            L('impact', 'slash_arc', 'impact', palette='@type', size=60, duration=.25),
            L('impact', 'cross', 'impact', palette='@type', size=46, duration=.3),
            L('impact', 'sparks', 'impact', palette='@type', count=16, duration=.4, particle='@type')]},
        'displace_blast': {'layers': [
            L('projectile', 'family', 'release', family='straight', palette='@type', size=14),
            L('impact', 'ring', 'impact', palette='@type', size=70, duration=.35),
            L('trail', 'dust', 'impact', palette='GROUND', count=10, duration=.5)]},
        'generic_pop': {'layers': [
            L('impact', 'ring', 'impact', palette='@type', size=30, duration=.3),
            L('impact', 'sparks', 'impact', palette='@type', count=6, duration=.3, particle='sparkle')]},
    }
    recipes.update(CATEGORY_RECIPES)
    bindings = {
        'archetype': {'melee': 'melee_slash', 'ranged': 'ranged_shot', 'support': 'ranged_shot',
                      'tank': 'tank_stomp', 'cast': 'cast_burst', 'support_cast': 'support_channel'},
        'type_projectile': TYPE_PROJECTILE,
        'category': {name: 'cat.' + name for name in CATEGORY_NAMES},
    }
    screen = {
        'ult': {'zoom': 1.08, 'dim': .5, 'slowmo': .45, 'slowmo_s': .3, 'banner_s': .9, 'hitstop': .1},
        'ko': {'zoom': 1.06, 'dim': .38, 'hitstop': .1, 'zoom_s': .55},
        'crit': {'hitstop': .066, 'threshold': .22},
        'shake': {'base': 1.5, 'per_weight': 9, 'decay': .3, 'max': 12},
        'combo': {'window': .9, 'follow': .35},
    }
    return {'schema_version': 1, 'kind': 'vfx_pack', 'name': 'core',
            'description': '属性调色板与粒子材质、弹道家族、分层特效配方与镜头规则。',
            'palettes': PALETTES, 'materials': MATERIALS,
            'projectiles': {
                'straight': {'size': 9, 'trail': .8},
                'arc': {'size': 10, 'arc': .45, 'trail': .5},
                'homing': {'size': 8, 'wobble': 26, 'trail': .9},
                'beam': {'width': 9, 'trail': 0},
                'ground': {'size': 12, 'trail': .6},
                'volley': {'size': 7, 'count': 3, 'stagger': .06, 'trail': .6}},
            'recipes': recipes, 'bindings': bindings, 'screen': screen}


# Category recipes: one distinct silhouette per skill category. Layers with
# `on` fire once per cause-linked outcome of the cast (cast_index/action_index).
HEAL_ON = ['heal', 'heal_bell', 'regen']
GUARD_ON = ['guard', 'shield', 'protect', 'protect_charge', 'helping_hand']
CATEGORY_RECIPES = {
    'cat.burst': {'layers': [
        L('charge', 'converge', 'anticipation', palette='@type', count=14, size=46, particle='@type'),
        L('projectile', 'family', 'release', family='@type', palette='@type', size=13),
        L('impact', 'burst', 'impact', palette='@type', size=62, count=20, duration=.45, particle='@type'),
        L('impact', 'ring', 'impact', palette='@type', size=80, duration=.4, curve='easeOutCubic'),
        L('ground', 'scorch', 'impact', palette='@type', size=56, duration=1.2, alpha=.5),
        L('screen', 'flash', 'impact', palette='@type', duration=.1, alpha=.28),
        L('impact', 'burst', 'impact', palette='@type', size=34, count=8, on='side_hit', particle='@type')]},
    'cat.technique': {'extends': 'cat.burst', 'drop': ['converge'], 'add': [
        L('charge', 'rune_circle', 'anticipation', palette='@type', size=46)]},
    'cat.area': {'layers': [
        L('charge', 'rune_circle', 'anticipation', palette='@type', size=50),
        L('projectile', 'family', 'release', family='arc', palette='@type', size=14),
        L('ground', 'ring_expand', 'impact', palette='@type', size=130, duration=.6, target='target'),
        L('ground', 'debris', 'impact', palette='ROCK', size=60, count=12, duration=.7, target='target'),
        L('impact', 'burst', 'impact', palette='@type', size=58, count=16, duration=.4, particle='@type'),
        L('ground', 'crack', 'impact', palette='@type', size=70, duration=1.6, alpha=.6, target='target'),
        L('impact', 'shards', 'impact', palette='@type', count=8, duration=.45, on='side_hit')]},
    'cat.chain': {'layers': [
        L('charge', 'sparks', 'anticipation', palette='@type', count=10, size=36, particle='arc'),
        L('projectile', 'family', 'release', family='beam', palette='@type', size=8),
        L('impact', 'cross', 'impact', palette='@type', size=50, duration=.25),
        L('link', 'fork', 'impact', palette='@type', size=40, duration=.35, on=['side_hit', 'chain'], **{'from': 'origin'}),
        L('impact', 'sparks', 'impact', palette='@type', count=12, duration=.35, particle='arc', on=['side_hit', 'chain']),
        L('screen', 'flash', 'impact', palette='@type', duration=.08, alpha=.25)]},
    'cat.combo': {'layers': [
        L('trail', 'afterimage', 'release', duration=.25),
        L('impact', 'multi_hit', 'impact', palette='@type', size=60, count=4, duration=.5),
        L('impact', 'slash_arc', 'impact', palette='@type', size=62, duration=.25),
        L('impact', 'claw', 'impact', palette='@type', size=54, duration=.3, offset=.12),
        L('impact', 'shove', 'impact', palette='@type', size=50, duration=.4, on=['knockback', 'pull'])]},
    'cat.drain': {'layers': [
        L('projectile', 'family', 'release', family='homing', palette='@type', size=9),
        L('impact', 'burst', 'impact', palette='@type', size=42, count=10, duration=.35, particle='@type'),
        L('link', 'stream', 'impact', palette='@type', size=40, count=14, duration=.6, offset=.05, **{'from': 'target', 'to': 'actor'}),
        L('aura', 'motes_rise', 'impact', palette='HEAL', size=40, count=8, duration=.7, offset=.35, target='actor'),
        L('link', 'stream', 'impact', palette='@type', size=36, count=10, duration=.55, on=['energy_drain', 'drain'], **{'from': 'target', 'to': 'actor'})]},
    'cat.lifesteal': {'extends': 'cat.drain', 'add': [
        L('link', 'stream', 'impact', palette='HEAL', size=36, count=12, duration=.6, on=HEAL_ON, **{'from': 'origin'}),
        L('aura', 'cross_glyph', 'impact', palette='HEAL', size=46, duration=.7, on=HEAL_ON)]},
    'cat.energy': {'layers': [
        L('charge', 'spiral', 'anticipation', palette='ELECTRIC', count=10, size=38, particle='spark'),
        L('projectile', 'family', 'release', family='homing', palette='ELECTRIC', size=8),
        L('aura', 'energy_orbs', 'impact', palette='ELECTRIC', size=46, duration=.6, on=['energy']),
        L('link', 'stream', 'impact', palette='ELECTRIC', size=36, count=12, duration=.55, on=['energy_drain'], **{'from': 'target', 'to': 'actor'}),
        L('impact', 'burst', 'impact', palette='@type', size=36, count=8, duration=.3, particle='spark')]},
    'cat.heal': {'layers': [
        L('aura', 'ring_rise', 'anticipation', palette='HEAL', size=42, duration=.6),
        L('projectile', 'family', 'release', family='homing', palette='HEAL', size=8),
        L('aura', 'motes_rise', 'impact', palette='HEAL', size=44, count=12, duration=.8, on=HEAL_ON),
        L('aura', 'cross_glyph', 'impact', palette='HEAL', size=48, duration=.75, on=HEAL_ON),
        L('aura', 'cleanse_spiral', 'impact', palette='HEAL', size=44, duration=.7, on=['cleanse'])]},
    'cat.rescue': {'extends': 'cat.heal', 'add': [
        L('link', 'tether', 'impact', palette='HEAL', size=30, duration=.5, on=['pull', 'rescue'], **{'from': 'actor'}),
        L('impact', 'shove', 'impact', palette='HEAL', size=44, duration=.4, on=['pull'])]},
    'cat.shield': {'layers': [
        L('charge', 'ring', 'anticipation', palette='SHIELD', size=40, duration=.35),
        L('projectile', 'family', 'release', family='homing', palette='SHIELD', size=8),
        L('aura', 'hex_dome', 'impact', palette='SHIELD', size=70, duration=.95, on=GUARD_ON),
        L('impact', 'flash', 'impact', palette='SHIELD', size=30, duration=.12)]},
    'cat.guard': {'extends': 'cat.shield', 'add': [
        L('aura', 'buff_arrows', 'impact', palette='SHIELD', size=40, duration=.6, on=GUARD_ON)]},
    'cat.cleanse': {'layers': [
        L('aura', 'ring_rise', 'anticipation', palette='HEAL', size=42, duration=.6),
        L('projectile', 'family', 'release', family='homing', palette='@type', size=8),
        L('aura', 'cleanse_spiral', 'impact', palette='HEAL', size=48, duration=.8, on=['cleanse']),
        L('aura', 'motes_rise', 'impact', palette='HEAL', size=40, count=8, duration=.7, on=HEAL_ON),
        L('aura', 'energy_orbs', 'impact', palette='ELECTRIC', size=40, duration=.55, on=['energy'])]},
    'cat.clear': {'extends': 'cat.cleanse', 'add': [
        L('ground', 'ring_expand', 'impact', palette='HEAL', size=110, duration=.6, target='actor')]},
    'cat.displacement': {'layers': [
        L('projectile', 'family', 'release', family='straight', palette='@type', size=14),
        L('impact', 'ring', 'impact', palette='@type', size=64, duration=.32),
        L('impact', 'shove', 'impact', palette='@type', size=60, duration=.45, on=['knockback', 'pull']),
        L('trail', 'dust', 'impact', palette='GROUND', count=10, duration=.5, on=['knockback', 'pull'])]},
    'cat.root': {'layers': [
        L('projectile', 'family', 'release', family='ground', palette='GRASS', size=10),
        L('ground', 'vines_grow', 'impact', palette='GRASS', size=50, duration=1.4, target='target'),
        L('ground', 'vines_grow', 'impact', palette='GRASS', size=44, duration=1.3, on=['root', 'apply']),
        L('impact', 'petals', 'impact', palette='GRASS', count=10, duration=.55, particle='leaf')]},
    'cat.pursuit': {'layers': [
        L('trail', 'afterimage', 'release', duration=.22),
        L('impact', 'mark', 'release', palette='@type', size=50, duration=.3),
        L('impact', 'bite', 'impact', palette='@type', size=56, duration=.35),
        L('impact', 'claw', 'impact', palette='@type', size=50, duration=.3, offset=.08),
        L('impact', 'burst', 'impact', palette='@type', size=36, count=8, duration=.3, on='side_hit')]},
    'cat.assassin': {'extends': 'cat.pursuit', 'add': [
        L('charge', 'spiral', 'anticipation', palette='GHOST', count=10, size=36, particle='wisp'),
        L('impact', 'execute_slash', 'impact', palette='@type', size=64, duration=.45, on=['execute'])]},
    'cat.taunt': {'layers': [
        L('aura', 'shout_rings', 'release', palette='FIGHTING', size=70, duration=.6, target='actor'),
        L('aura', 'mark', 'impact', palette='FIGHTING', size=48, duration=.55, on=['taunt']),
        L('aura', 'hex_dome', 'impact', palette='SHIELD', size=66, duration=.8, on=GUARD_ON),
        L('impact', 'ring', 'impact', palette='@type', size=50, duration=.3)]},
    'cat.terrain': {'layers': [
        L('charge', 'rune_circle', 'anticipation', palette='@type', size=46),
        L('projectile', 'family', 'release', family='ground', palette='@type', size=12),
        L('ground', 'spikes', 'impact', palette='@type', count=7, size=60, duration=2.0, target='target'),
        L('ground', 'ring_expand', 'impact', palette='@type', size=96, duration=.5, target='target'),
        L('impact', 'shards', 'impact', palette='@type', count=12, duration=.55, particle='debris')]},
    'cat.poison': {'layers': [
        L('projectile', 'family', 'release', family='arc', palette='POISON', size=11),
        L('ground', 'puddle', 'impact', palette='POISON', size=58, duration=1.5, alpha=.7, target='target'),
        L('impact', 'splash', 'impact', palette='POISON', count=14, duration=.5, particle='bubble'),
        L('impact', 'splash', 'impact', palette='POISON', count=8, duration=.45, particle='bubble', on=['poison', 'status', 'side_hit'])]},
    'cat.vulnerability': {'layers': [
        L('projectile', 'family', 'release', family='straight', palette='@type', size=11),
        L('impact', 'mark', 'impact', palette='@type', size=54, duration=.6),
        L('impact', 'shards', 'impact', palette='STEEL', count=12, duration=.5),
        L('impact', 'burst', 'impact', palette='@type', size=40, count=8, duration=.3, particle='@type'),
        L('aura', 'mark', 'impact', palette='FIGHTING', size=44, duration=.5, on=['vulnerability'])]},
    'cat.execute': {'layers': [
        L('impact', 'mark', 'release', palette='@type', size=56, duration=.3),
        L('trail', 'afterimage', 'release', duration=.2),
        L('impact', 'execute_slash', 'impact', palette='@type', size=70, duration=.45),
        L('screen', 'flash', 'impact', palette='KO', duration=.1, alpha=.3),
        L('impact', 'execute_slash', 'impact', palette='KO', size=60, duration=.4, on=['execute'])]},
    'cat.pierce': {'layers': [
        L('charge', 'converge', 'anticipation', palette='@type', count=10, size=36, particle='@type'),
        L('projectile', 'family', 'release', family='beam', palette='@type', size=8),
        L('impact', 'pierce_line', 'impact', palette='@type', size=60, duration=.35),
        L('impact', 'sparks', 'impact', palette='@type', count=10, duration=.3, particle='spark'),
        L('impact', 'pierce_line', 'impact', palette='@type', size=50, duration=.3, on=['side_hit', 'knockback'])]},
    'cat.retaliation': {'layers': [
        L('aura', 'thorn_shell', 'release', palette='POISON', size=58, duration=.8, target='actor'),
        L('aura', 'hex_dome', 'impact', palette='POISON', size=60, duration=.7, on=['thorns']),
        L('impact', 'shards', 'impact', palette='POISON', count=10, duration=.45, on=['thorn_hit'])]},
    'cat.control': {'layers': [
        L('projectile', 'family', 'release', family='homing', palette='@type', size=9),
        L('impact', 'ring', 'impact', palette='@type', size=56, duration=.35),
        L('impact', 'stun_stars', 'impact', palette='ELECTRIC', size=50, duration=.8),
        L('aura', 'stun_stars', 'impact', palette='ELECTRIC', size=46, duration=.8, on=['flinch', 'status', 'apply'])]},
}
CATEGORY_NAMES = sorted(name[4:] for name in CATEGORY_RECIPES)

# Tag -> extra layers. A skill recipe = its category silhouette + its tags.
TAG_LAYERS = [
    (('击退', '震击'), L('impact', 'shove', 'impact', palette='@type', size=56, duration=.4, on=['knockback', 'pull'])),
    (('连击',), L('impact', 'multi_hit', 'impact', palette='@type', size=54, count=3, duration=.45)),
    (('护盾', '保护', '护卫', '群体护盾', '援护', '减伤'), L('aura', 'hex_dome', 'impact', palette='SHIELD', size=64, duration=.85, on=GUARD_ON)),
    (('回复', '群体治疗', '伤害转治疗', '救援'), L('aura', 'motes_rise', 'impact', palette='HEAL', size=42, count=10, duration=.75, on=HEAL_ON)),
    (('回能', '汲能', '攻击回能', '控能'), L('aura', 'energy_orbs', 'impact', palette='ELECTRIC', size=42, duration=.55, on=['energy'])),
    (('净化', '解毒', '群体净化', '解控', '解冻'), L('aura', 'cleanse_spiral', 'impact', palette='HEAL', size=46, duration=.75, on=['cleanse'])),
    (('定身', '控制铺垫'), L('ground', 'vines_grow', 'impact', palette='GRASS', size=44, duration=1.2, on=['root', 'apply'])),
    (('嘲讽',), L('aura', 'shout_rings', 'release', palette='FIGHTING', size=64, duration=.55, target='actor')),
    (('连锁',), L('link', 'fork', 'impact', palette='@type', size=40, duration=.35, on=['side_hit', 'chain'], **{'from': 'origin'})),
    (('范围', '轰炸', '溅射', '清场', '密集阵容'), L('ground', 'ring_expand', 'impact', palette='@type', size=110, duration=.55, target='target')),
    (('贯穿',), L('impact', 'pierce_line', 'impact', palette='@type', size=56, duration=.32)),
    (('易伤', '易伤追击', '集火'), L('impact', 'mark', 'impact', palette='FIGHTING', size=50, duration=.55)),
    (('收割', '残血收割'), L('impact', 'execute_slash', 'impact', palette='@type', size=60, duration=.4, on=['execute'])),
    (('中毒', '铺毒'), L('ground', 'puddle', 'impact', palette='POISON', size=52, duration=1.2, alpha=.6, target='target')),
    (('瞬移',), L('charge', 'spiral', 'anticipation', palette='PSYCHIC', count=12, size=40, particle='ring')),
    (('反击',), L('aura', 'thorn_shell', 'impact', palette='POISON', size=54, duration=.7, on=['thorns'])),
    (('麻痹联动', '控制追击', '干扰'), L('aura', 'stun_stars', 'impact', palette='ELECTRIC', size=42, duration=.7, on=['flinch', 'status'])),
    (('高威爆发', '高威俯冲'), L('screen', 'flash', 'impact', palette='KO', duration=.12, alpha=.32)),
]
BEHAVIOR_FAMILY = {'高威俯冲': 'straight', '范围轰炸': 'arc', '贯穿击退': 'beam', '连锁输出': 'beam', '毒伤追击': 'arc',
                   '冰棱溅射': 'volley', '毒潮压制': 'arc', '地形布置': 'ground', '定身阻截': 'ground'}
CHARGE_VARIANTS = ('converge', 'spiral', 'rune_circle', 'glow')


def _layer_key(layer):
    on = layer.get('on')
    return (layer['layer'], layer['shape'], tuple(on) if isinstance(on, list) else on)


def skills_pack():
    """Every native skill (gen1-3 family kits) gets its own recipe."""
    import arena_skills
    rows = {}
    for row in arena_skills.catalog(include_families=True):
        rows.setdefault(row['id'], row)
    recipes, bindings = {}, {}
    for skill_id, row in sorted(rows.items()):
        category = row.get('category') if row.get('category') in CATEGORY_NAMES else 'burst'
        base = CATEGORY_RECIPES['cat.' + category]
        resolved = list(base.get('layers', [])) + list(CATEGORY_RECIPES.get(base.get('extends', ''), {}).get('layers', [])) \
            + list(base.get('add', []))
        have = {_layer_key(layer) for layer in resolved}
        add = []
        for tags, layer in TAG_LAYERS:
            if any(tag in row.get('tags', ()) for tag in tags) and _layer_key(layer) not in have:
                add.append(dict(layer))
                have.add(_layer_key(layer))
        # A stable per-skill charge silhouette breaks same-category sameness.
        variant = CHARGE_VARIANTS[sum(map(ord, skill_id)) % len(CHARGE_VARIANTS)]
        if not any(layer['layer'] == 'charge' for layer in resolved + add) and row.get('targeting') == 'enemy':
            add.append(L('charge', variant, 'anticipation', palette='@type', size=40, count=10, particle='@type'))
        recipe = {'extends': 'cat.' + category}
        power = row.get('power') or 0
        if power:
            recipe['scale'] = round(max(.8, min(1.45, power / 60)), 2)
        family = BEHAVIOR_FAMILY.get(row.get('behavior'))
        if family:
            recipe['family'] = family
        if add:
            recipe['add'] = add
        recipe['note'] = f"{row['name']} · {row.get('behavior') or category}"
        recipes['skill.' + skill_id] = recipe
        bindings[skill_id] = 'skill.' + skill_id
    return {'schema_version': 1, 'kind': 'vfx_pack', 'name': 'skills',
            'description': '逐技能特效：每个原生技能 = 类别轮廓（cat.*）+ 标签附加层 + 威力缩放；由 motion_seed.py 生成，可在工作台逐条编辑。',
            'recipes': recipes, 'bindings': {'skill': bindings}}


def packs():
    return {('motion', 'roles'): role_pack(), ('motion', 'families'): family_pack(),
            ('motion', 'species'): species_pack(), ('vfx', 'core'): vfx_pack(),
            ('vfx', 'skills'): skills_pack()}


def main(argv):
    check = '--check' in argv
    changed = []
    for (group, name), data in packs().items():
        validator = motion_schema.validate_motion_pack if group == 'motion' else motion_schema.validate_vfx_pack
        validator(data, path=f'{group}/{name}')
        path = ROOT / 'assets' / group / f'{name}.json'
        text = motion_schema.dump_pack(data)
        if not path.is_file() or path.read_text() != text:
            changed.append(path.relative_to(ROOT).as_posix())
            if not check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
    print(('would change: ' if check else 'wrote: ') + (', '.join(changed) or 'nothing'))
    problems = motion_schema.validate_all() if not check else []
    for problem in problems:
        print('✗', problem)
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
