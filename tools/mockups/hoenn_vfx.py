"""Original Hoenn family attack and native-cast choreography.

This module is intentionally standalone: the renderer supplies real pixel
coordinates, recipients and emitters, while this file only draws finite visual
material.  It never reads battle state, chooses targets, or changes outcomes.
"""
import math

from PIL import Image, ImageDraw

import retro_primitives as rp


PHASES = frozenset(('windup', 'flight', 'impact', 'aftermath'))
CONTACT = .22
LIFETIME = .8

# Twelve Hoenn families, thirty-one selectable forms.  Stage is zero-based;
# the count/width/material choices below make each evolutionary step read.
_SPECIES = {}
for _ids, _family, _identity, _element in (
    ((252, 253, 254), 'leaf', '蜥蜴刀叶', 'GRASS'),
    ((255, 256, 257), 'fire', '火羽连踢', 'FIRE'),
    ((258, 259, 260), 'mud', '沼流重炮', 'WATER'),
    ((270, 271, 272), 'lotad', '莲池协奏', 'WATER'),
    ((280, 281, 282), 'psy', '心弦守护', 'PSYCHIC'),
    ((285, 286), 'spore', '孢子拳法', 'GRASS'),
    ((304, 305, 306), 'armor', '巨甲冲压', 'STEEL'),
    ((333, 334), 'cloud', '云羽歌谣', 'FLYING'),
    ((349, 350), 'serpent', '鳞光长河', 'WATER'),
    ((359,), 'dark', '灾厄月刃', 'DARK'),
    ((371, 372, 373), 'dragon', '流星龙击', 'DRAGON'),
    ((374, 375, 376), 'magnet', '磁力四臂', 'STEEL'),
):
    for _index, _sid in enumerate(_ids):
        _SPECIES[_sid] = {
            'family': _family, 'identity': _identity, 'element': _element,
            'stage': _index, 'line_ids': _ids,
        }

SPECIES = frozenset(_SPECIES)

_ATTACKS = {
    252: '新芽突刺', 253: '双叶刃', 254: '三连疾叶',
    255: '雏火啄击', 256: '火爪二连', 257: '烈焰踢弧',
    258: '细流弹', 259: '泥沼拍击', 260: '潮泥重拳',
    270: '雨露轻拍', 271: '莲叶回击', 272: '欢雨掌',
    280: '心绪涟漪', 281: '双弦轻击', 282: '守护月击',
    285: '孢子喷吐', 286: '孢子连拳',
    304: '铁额头槌', 305: '钢甲撞', 306: '巨甲交叉压',
    333: '云翼拂击', 334: '云龙翼卷',
    349: '搁浅飞溅', 350: '鳞光水带',
    359: '灾厄弧刃',
    371: '龙头突进', 372: '硬壳回旋撞', 373: '流星龙翼冲',
    374: '磁浮冲针', 375: '钳臂夹击', 376: '陨铁四臂拳',
}

_CASTS = {
    252: ('新芽连射', 'leaf'), 253: ('叶刃双斩', 'leaf'), 254: ('疾风叶刃', 'leaf'),
    255: ('雏火飞散', 'fire'), 256: ('双爪火舞', 'fire'), 257: ('烈焰爆连踢', 'fire'),
    258: ('细流贯穿', 'mud'), 259: ('泥沼锚定', 'mud'), 260: ('潮泥重炮', 'mud'),
    270: ('雨露接力', 'lotad'), 271: ('水草共鸣', 'lotad'), 272: ('欢雨庆典', 'lotad'),
    280: ('心铃安抚', 'psy'), 281: ('心弦屏障', 'psy'), 282: ('圣洁守护', 'psy'),
    285: ('孢子喷射', 'spore'), 286: ('孢子拳连打', 'spore'),
    304: ('铁头初撞', 'armor'), 305: ('钢甲冲撞', 'armor'), 306: ('巨金重压', 'armor'),
    333: ('云羽摇篮', 'cloud'), 334: ('云龙圣歌', 'cloud'),
    349: ('搁浅扑击', 'serpent'), 350: ('鳞光抚流', 'serpent'),
    359: ('灾厄预兆', 'dark'),
    371: ('龙头冲撞', 'dragon'), 372: ('硬壳突击', 'dragon'), 373: ('流星俯冲', 'dragon'),
    374: ('磁浮撞击', 'magnet'), 375: ('钳臂震退', 'magnet'), 376: ('陨铁重拳', 'magnet'),
}

_EMITTERS = {
    'leaf': ('leaf glands', 'leaf-blade wrists', 'back leaf fan'),
    'fire': ('beak', 'claw tips', 'ankle vents'),
    'mud': ('mouth', 'foreleg mud plate', 'mouth jet and forepaws'),
    'lotad': ('leaf basin', 'lily pads', 'crown water'),
    'psy': ('horn tips', 'gown hem', 'chest plate'),
    'spore': ('pore vents', 'fist spores'),
    'armor': ('helmet nose', 'armor rim', 'armored shoulders and twin forelimbs'),
    'cloud': ('wing tips', 'cloud wings'),
    'serpent': ('tail fin', 'scarf scales'),
    'dark': ('brow horn',),
    'dragon': ('hard helmet', 'shell rim', 'wing wrists'),
    'magnet': ('nose magnet', 'forearm magnets', 'four leg magnets'),
}


def attack_label(species_id):
    return _ATTACKS.get(species_id)


def describe(species_id):
    spec = _SPECIES.get(species_id)
    if not spec:
        return None
    cast_name, cast_kind = _CASTS[species_id]
    return {
        'attack_name': _ATTACKS[species_id],
        'cast_name': cast_name,
        'identity': spec['identity'],
        'emitter': _EMITTERS[spec['family']][spec['stage']],
        'stage': spec['stage'] + 1,
        'cast_kind': cast_kind,
        'element': spec['element'],
        'phase_order': ('windup', 'flight', 'impact', 'aftermath'),
        'contact_duration': CONTACT,
        'tail_duration': LIFETIME,
    }


def _p(value):
    return min(1., max(0., float(value)))


def _basis(a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy) or 1.
    ux, uy = dx / length, dy / length
    return ux, uy, -uy, ux


def _point(a, b, q, lane=0., arc=0.):
    ux, uy, nx, ny = _basis(a, b)
    base = (a[0] + (b[0] - a[0]) * q, a[1] + (b[1] - a[1]) * q)
    wave = math.sin(math.pi * q)
    return (base[0] + nx * lane * wave,
            base[1] + ny * lane * wave - arc * wave)


def _snap(value):
    return round(value / rp.PIXEL) * rp.PIXEL


def _poly(layer, points, color):
    pts = [(_snap(x), _snap(y)) for x, y in points]
    ImageDraw.Draw(layer).polygon(pts, fill=color)


def _ellipse(layer, center, radius, color, flatten=.8):
    x, y = center
    rx, ry = max(3, _snap(radius)), max(3, _snap(radius * flatten))
    ImageDraw.Draw(layer).ellipse((_snap(x - rx), _snap(y - ry), _snap(x + rx), _snap(y + ry)),
                                 fill=color)


def _outline(layer, points, color, width=3):
    rp.line(layer, points, color, max(3, round(width / 3) * 3))


def _path(layer, a, b, q, colors, *, lane=0., arc=0., width=6, step=.09):
    pts = [_point(a, b, max(0., min(1., q - i * step)), lane, arc)
           for i in range(math.ceil(min(1., q) / step) + 1)]
    _outline(layer, pts, colors[0], width + 3)
    _outline(layer, pts, colors[2], width)
    _outline(layer, pts[-3:] or pts, colors[4], 3)


def _blade(layer, at, angle, colors, scale=1.):
    x, y = at
    c, s = math.cos(angle), math.sin(angle)
    n_x, n_y = -s, c
    pts = []
    for q in (-1., -.35, .5, 1.):
        width = (0., 4., 5., 0.)
        for side in (-1, 1):
            pts.append((x + c * 24 * q * scale + n_x * side * (3 + abs(q) * 5) * scale,
                        y + s * 24 * q * scale + n_y * side * (3 + abs(q) * 5) * scale))
    left = [(x + c * -22 * scale + n_x * 3 * scale, y + s * -22 * scale + n_y * 3 * scale),
            (x + c * -3 * scale + n_x * 7 * scale, y + s * -3 * scale + n_y * 7 * scale),
            (x + c * 22 * scale + n_x * 0 * scale, y + s * 22 * scale + n_y * 0 * scale),
            (x + c * -3 * scale - n_x * 7 * scale, y + s * -3 * scale - n_y * 7 * scale)]
    _poly(layer, left, colors[2])
    _outline(layer, left, colors[0], 3)
    _outline(layer, left[:3], colors[4], 3)


def _claw(layer, at, angle, colors, scale=1., count=3):
    x, y = at
    c, s = math.cos(angle), math.sin(angle)
    n_x, n_y = -s, c
    for i in range(count):
        lane = (i - (count - 1) / 2) * 12 * scale
        pts = [(x + n_x * lane - c * 8 * scale, y + n_y * lane - s * 8 * scale),
               (x + n_x * (lane + 6 * scale) + c * 18 * scale,
                y + n_y * (lane + 6 * scale) + s * 18 * scale)]
        _outline(layer, pts, colors[0], 9 * scale)
        _outline(layer, pts, colors[3], 6 * scale)
        _outline(layer, pts, colors[4], 3)


def _kick_arc(layer, at, angle, colors, scale=1., count=2):
    x, y = at
    for i in range(count):
        start = angle - (.82 - i * .44) * 1.15
        end = start + .98
        pts = []
        for j in range(9):
            a = start + (end - start) * j / 8
            radius = (29 - i * 7) * scale
            pts.append((x + math.cos(a) * radius, y + math.sin(a) * radius * .82))
        _outline(layer, pts, colors[0], 10 * scale)
        _outline(layer, pts, colors[2], 6 * scale)
        _outline(layer, pts, colors[4], 3)


def _leaf(layer, at, angle, colors, scale=1.):
    x, y = at
    c, s = math.cos(angle), math.sin(angle)
    n_x, n_y = -s, c
    pts = [(x - c * 13 * scale, y - s * 13 * scale),
           (x + n_x * 8 * scale, y + n_y * 8 * scale),
           (x + c * 16 * scale, y + s * 16 * scale),
           (x - n_x * 8 * scale, y - n_y * 8 * scale)]
    _poly(layer, pts, colors[2])
    _outline(layer, pts, colors[0], 3)
    _outline(layer, pts[::2], colors[4], 3)


def _drop(layer, at, colors, scale=1.):
    x, y = at
    _poly(layer, ((x, y - 13 * scale), (x + 8 * scale, y + 2 * scale),
                  (x, y + 11 * scale), (x - 8 * scale, y + 2 * scale)), colors[2])
    _outline(layer, ((x - 4 * scale, y), (x, y - 8 * scale), (x + 4 * scale, y)), colors[4], 3)


def _cloud(layer, at, colors, scale=1., turn=0.):
    x, y = at
    for i, (dx, dy, radius) in enumerate(((-18, 2, 10), (0, -8, 15), (18, 1, 11), (3, 8, 9))):
        dx, dy = (dx * math.cos(turn) - dy * math.sin(turn),
                  dx * math.sin(turn) + dy * math.cos(turn))
        _ellipse(layer, (x + dx * scale, y + dy * scale), radius * scale,
                 colors[1 if i % 2 else 2], .78)
    _outline(layer, ((x - 25 * scale, y + 10 * scale), (x + 25 * scale, y + 10 * scale)), colors[0], 3)


def _moon(layer, at, colors, scale=1.):
    x, y = at
    pts = [(x + math.cos(a) * 26 * scale, y + math.sin(a) * 21 * scale)
           for a in [i * math.pi / 8 for i in range(17)]]
    _outline(layer, pts, colors[1], 9 * scale)
    _outline(layer, pts, colors[3], 6 * scale)
    inner = [(x + math.cos(a) * 14 * scale, y + math.sin(a) * 11 * scale)
             for a in [i * math.pi / 8 for i in range(17)]]
    _outline(layer, inner, colors[4], 3)


def _shield(layer, at, angle, colors, scale=1.):
    x, y = at
    c, s = math.cos(angle), math.sin(angle)
    n_x, n_y = -s, c
    pts = []
    for u, v in ((-18, -28), (12, -35), (28, 3), (8, 31), (-20, 26), (-31, 2)):
        pts.append((x + c * u * scale - n_x * v * scale,
                    y + s * u * scale - n_y * v * scale))
    _poly(layer, pts, (*colors[2], 112))
    _outline(layer, pts, colors[0], 6)
    _outline(layer, pts[1:4], colors[4], 3)


def _wing(layer, at, angle, colors, scale=1., span=1.):
    """Two shaded wing planes used for Salamence's diving track."""
    x, y = at
    c, s = math.cos(angle), math.sin(angle)
    n_x, n_y = -s, c
    for side in (-1, 1):
        pts = []
        for u, v in ((-14, 0), (-2, side * 31 * span), (18, side * 24 * span),
                     (25, side * 6), (8, 0)):
            pts.append((x + c * u * scale - n_x * v * scale,
                        y + s * u * scale - n_y * v * scale))
        _poly(layer, pts, (*colors[1], 182))
        _outline(layer, pts, colors[0], 6)
        _outline(layer, pts[1:4], colors[4], 3)


def _impact_ring(layer, at, colors, q, scale=1., count=6):
    radius = (11 + q * 43) * scale
    for i in range(count):
        angle = i * math.tau / count + q * 1.7
        x = at[0] + math.cos(angle) * radius
        y = at[1] + math.sin(angle) * radius * .72
        _ellipse(layer, (x, y), (4 if i % 2 else 6) * scale, colors[3], .65)
    if q < .32:
        _outline(layer, ((at[0] - radius, at[1]), (at[0], at[1] - radius * .72),
                         (at[0] + radius, at[1]), (at[0], at[1] + radius * .72),
                         (at[0] - radius, at[1])), colors[4], 3)


def _charge(layer, source, colors, p, count, scale, kind='orb', density=1.):
    radius = (8 + p * 18) * scale
    count = max(1, round(count * density))
    for i in range(count):
        angle = i * math.tau / count + p * 2.5
        at = (source[0] + math.cos(angle) * radius,
              source[1] + math.sin(angle) * radius * .68)
        if kind == 'leaf':
            _leaf(layer, at, angle + p * 3, colors, .48 * scale)
        elif kind == 'spark':
            _outline(layer, (at, (at[0] + math.cos(angle + 1.9) * 11 * scale,
                                  at[1] + math.sin(angle + 1.9) * 9 * scale)), colors[3], 3)
        else:
            _ellipse(layer, at, 5 * scale, colors[2], .72)
    if kind != 'spark':
        _ellipse(layer, source, (5 + p * 6) * scale, colors[3], .58)


def _age(phase, p):
    return p * CONTACT if phase == 'impact' else CONTACT + p * (LIFETIME - CONTACT)


def _fade(phase, p):
    if phase == 'impact':
        return 1.
    return max(0., 1. - p)


def _settings(config, secondary):
    scale, density = rp.settings(config or {})
    return scale * (.65 if secondary else 1.), density


def _phase_alpha(phase, p):
    """Fade in, peak through contact, then vanish by the phase boundary."""
    if phase == 'windup':
        return .38 + .62 * p
    if phase == 'flight':
        return .78 + .22 * p
    if phase == 'impact':
        return 1.
    return max(0., 1. - p)


def _draw_leaf(layer, source, target, phase, p, config, spec, *, cast=False):
    colors = rp.palette(spec['element'], config or {})
    scale, density = _settings(config, False)
    stage = spec['stage']
    count = stage + (3 if cast else 1)
    if phase == 'windup':
        _charge(layer, source, colors, p, stage + 2, .48 + stage * .07, 'leaf', density=density)
        return
    if phase == 'flight':
        for i in range(round(count * density)):
            lane = (i - (count - 1) / 2) * (14 if cast else 17)
            head = _point(source, target, p, lane, 13 if cast else 8)
            _blade(layer, head, math.atan2(target[1] - source[1], target[0] - source[0]) + i * .19,
                   colors, (.51 + stage * .055) * scale)
        return
    q = _age(phase, p) / LIFETIME
    fade = _fade(phase, p)
    for i in range(round((count + stage) * density)):
        angle = i * math.tau / (count + stage) + q * 2.4
        at = (target[0] + math.cos(angle) * (10 + q * 55) * scale,
              target[1] + math.sin(angle) * (8 + q * 43) * scale)
        _blade(layer, at, angle + .7, colors, (.42 + stage * .05) * scale * fade)
    _impact_ring(layer, target, colors, min(1., q * 1.1), .48 + stage * .06)


def _draw_fire(layer, source, target, phase, p, config, spec, *, cast=False):
    colors = rp.palette(spec['element'], config or {})
    scale, density = _settings(config, False)
    stage = spec['stage']
    if phase == 'windup':
        if cast and stage == 2:
            _kick_arc(layer, source, math.atan2(target[1] - source[1], target[0] - source[0]) - .65,
                      colors, (.28 + p * .15) * scale)
        else:
            _charge(layer, source, colors, p, 4 + stage, .40 + stage * .06, 'spark', density=density)
        return
    heading = math.atan2(target[1] - source[1], target[0] - source[0])
    if phase == 'flight':
        if stage == 0:
            if cast:
                for i in range(3):
                    q = max(0., p - i * .055)
                    head = _point(source, target, q, (i - 1) * 15, 12)
                    _ellipse(layer, head, (7 if i else 9) * scale, colors[2], .72)
                    _outline(layer, (source, head), colors[1], 3)
            else:
                head = _point(source, target, p, 0, 8)
                _ellipse(layer, head, (8 + stage * 3) * scale, colors[2], .72)
                _outline(layer, (source, head), colors[1], 3)
        elif stage == 1:
            for side in (-1, 1):
                head = _point(source, target, p - (.04 if cast and side < 0 else 0),
                              side * (18 if cast else 12), 10)
                _claw(layer, head, heading + side * .18, colors, (.48 + p * .07) * scale, 2)
            if cast:
                _kick_arc(layer, _point(source, target, p), heading, colors, .31 * scale, 2)
        else:
            _kick_arc(layer, _point(source, target, p, 18 if cast else 12, 15),
                      heading, colors, (.55 + p * .11) * scale, 3 if cast else 2)
            _path(layer, source, target, p, colors, lane=10, arc=17, width=6)
        return
    q = _age(phase, p) / LIFETIME
    fade = _fade(phase, p)
    at = target if cast else _point(source, target, 1.05, 4, 0)
    if stage == 2:
        _kick_arc(layer, at, heading, colors, (.70 if cast else .60) * scale * fade, 3)
    else:
        _claw(layer, at, heading, colors, (.50 + stage * .08) * scale * fade, 3 + stage)
    for i in range(round((5 + stage * 2) * density)):
        angle = i * 2.399 + q * 2.2
        pos = (at[0] + math.cos(angle) * (9 + q * 51) * scale,
               at[1] + math.sin(angle) * (7 + q * 39) * scale - q * 12 * scale)
        _poly(layer, ((pos[0], pos[1] - 9 * scale), (pos[0] + 6 * scale, pos[1] + 4 * scale),
                      (pos[0] - 6 * scale, pos[1] + 4 * scale)), colors[1 if i % 2 else 3])
    _impact_ring(layer, at, colors, q, .48 + stage * .05)


def _draw_mud(layer, source, target, phase, p, config, spec, *, cast=False):
    colors = rp.palette('GROUND' if spec['stage'] == 1 and cast else spec['element'], config or {})
    scale, density = _settings(config, False)
    stage = spec['stage']
    if phase == 'windup':
        _charge(layer, source, colors, p, 3 + stage, .43 + stage * .05,
                'spark' if stage == 2 and cast else 'orb', density=density)
        return
    heading = math.atan2(target[1] - source[1], target[0] - source[0])
    if phase == 'flight':
        streams = (2 if cast else 1) + (stage == 2 and cast)
        for i in range(streams):
            lane = 0 if streams == 1 else (i - (streams - 1) / 2) * (18 if stage < 2 else 26)
            head = _point(source, target, p, lane, 0 if stage < 2 else 9)
            _path(layer, source, head, p, colors, lane=lane, arc=0 if stage < 2 else 9,
                  width=8 + stage * 3)
            if stage == 1 and cast:
                _ellipse(layer, head, 12 * scale, colors[2], .48)
        return
    q = _age(phase, p) / LIFETIME
    fade = _fade(phase, p)
    at = target
    if cast and stage == 1:
        _ellipse(layer, at, (17 + q * 27) * scale * fade, colors[2], .34)
    elif stage == 2:
        _claw(layer, at, heading, colors, (.58 if cast else .46) * scale * fade, 3)
    else:
        _drop(layer, at, colors, (.55 + q * .1) * scale * fade)
    for i in range(round((5 + stage * 3) * density)):
        angle = i * 2.17 + q * 1.4
        pos = (at[0] + math.cos(angle) * (10 + q * 55) * scale,
               at[1] + math.sin(angle) * (7 + q * 38) * scale + q * 19 * scale)
        _ellipse(layer, pos, (5 if i % 2 else 7) * scale * fade, colors[1 if i % 3 else 2], .55)
    _impact_ring(layer, at, colors, q, .47 + stage * .05)


def _draw_lotad(layer, source, target, phase, p, config, spec, *, cast=False):
    colors = rp.palette(spec['element'], config or {})
    grass = rp.palette('GRASS', config or {})
    scale, density = _settings(config, False)
    stage = spec['stage']
    if phase == 'windup':
        _charge(layer, source, colors, p, 3 + stage, .38 + stage * .05, density=density)
        if stage:
            _leaf(layer, (source[0], source[1] + 10 * scale), -math.pi / 2, grass, .42 * scale)
        return
    if phase == 'flight':
        count = (3 if cast else 1) + stage
        for i in range(round(count * density)):
            q = max(0., p - i * .045)
            lane = (i - (count - 1) / 2) * (19 if cast else 12)
            at = _point(source, target, q, lane, 12 + stage * 6)
            if i % 3 == 0 and stage:
                _leaf(layer, at, math.atan2(target[1] - source[1], target[0] - source[0]) + p * 2,
                      grass, .40 * scale)
            else:
                _drop(layer, at, colors, (.36 + stage * .045) * scale)
        return
    q = _age(phase, p) / LIFETIME
    fade = _fade(phase, p)
    if cast and stage == 0:
        _moon(layer, target, colors, .36 * scale * fade)
    elif cast and stage == 1:
        gold = rp.palette('ELECTRIC', config or {})
        for i in range(5):
            angle = i * math.tau / 5 - q * 1.2
            pos = (target[0] + math.cos(angle) * (9 + q * 37) * scale,
                   target[1] + math.sin(angle) * (7 + q * 29) * scale - q * 15 * scale)
            _outline(layer, ((pos[0] - 5 * scale, pos[1]), (pos[0], pos[1] - 7 * scale),
                             (pos[0] + 5 * scale, pos[1]), (pos[0], pos[1] + 7 * scale),
                             (pos[0] - 5 * scale, pos[1])), gold[3], 3)
    else:
        _impact_ring(layer, target, colors, q, .52, 8)
        if stage:
            for i in range(6):
                angle = i * math.pi / 3 + q * .8
                at = (target[0] + math.cos(angle) * (13 + q * 38) * scale,
                      target[1] + math.sin(angle) * (10 + q * 30) * scale)
                _leaf(layer, at, angle, grass, .30 * scale * fade)
    if phase in ('impact', 'aftermath'):
        _ellipse(layer, target, (13 + q * 30) * scale * fade, colors[2], .34)


def _draw_psy(layer, source, target, phase, p, config, spec, *, cast=False):
    colors = rp.palette(spec['element'], config or {})
    scale, density = _settings(config, False)
    stage = spec['stage']
    if phase == 'windup':
        _charge(layer, source, colors, p, 4 + stage, .40 + stage * .05, density=density)
        if stage == 2:
            _outline(layer, ((source[0] - 24 * scale, source[1]),
                             (source[0], source[1] - 16 * scale),
                             (source[0] + 24 * scale, source[1])), colors[3], 3)
        return
    if phase == 'flight':
        heading = math.atan2(target[1] - source[1], target[0] - source[0])
        count = (4 if cast else 2) + stage
        for i in range(round(count * density)):
            q = max(0., p - i * .055)
            lane = (i - (count - 1) / 2) * (16 if cast else 11)
            _path(layer, source, target, q, colors, lane=lane, arc=10 + stage * 7,
                  width=5 + stage * 2)
        if cast and stage:
            _moon(layer, _point(source, target, p), colors, .22 * scale)
            if stage == 2:
                _shield(layer, target, heading, colors, .34 * scale)
        return
    q = _age(phase, p) / LIFETIME
    fade = _fade(phase, p)
    if cast:
        if stage == 0:
            for i in range(round(4 * density)):
                angle = i * math.pi / 2 + q * 1.2
                at = (target[0] + math.cos(angle) * (11 + q * 33) * scale,
                      target[1] + math.sin(angle) * (9 + q * 26) * scale - q * 22 * scale)
                _outline(layer, ((at[0] - 4, at[1] - 8), (at[0] + 4, at[1]),
                                 (at[0] - 4, at[1] + 7)), colors[3], 3)
        elif stage == 1:
            _shield(layer, target, math.atan2(target[1] - source[1], target[0] - source[0]),
                    colors, (.48 + q * .08) * scale * fade)
        else:
            _moon(layer, target, colors, (.48 + q * .07) * scale * fade)
            for i in range(round(5 * density)):
                angle = i * 2.399 - q
                at = (target[0] + math.cos(angle) * (18 + q * 36) * scale,
                      target[1] + math.sin(angle) * (14 + q * 28) * scale)
                _outline(layer, ((at[0], at[1] - 6), (at[0] + 5, at[1]),
                                 (at[0], at[1] + 6), (at[0] - 5, at[1])), colors[4], 3)
    else:
        for i in range(3 + stage):
            radius = (13 + q * (39 + stage * 9)) * scale
            ry = radius * (.54 + stage * .08)
            pts = [(target[0] + math.cos(a) * radius,
                    target[1] + math.sin(a) * ry) for a in
                   [j * math.pi / 10 for j in range(21)]]
            _outline(layer, pts, colors[(1 if i % 2 else 3)], max(3., 7 * scale * fade))
    _impact_ring(layer, target, colors, q, .40 + stage * .04, 5)


def _draw_spore(layer, source, target, phase, p, config, spec, *, cast=False):
    colors = rp.palette(spec['element'], config or {})
    scale, density = _settings(config, False)
    stage = spec['stage']
    if phase == 'windup':
        _charge(layer, source, colors, p, 6 + stage * 2, .38 + stage * .05, density=density)
        return
    heading = math.atan2(target[1] - source[1], target[0] - source[0])
    if phase == 'flight':
        for i in range(round((4 + stage * 2) * density)):
            q = max(0., p - i * (.05 if cast else .035))
            lane = (i - 3) * (20 if cast else 9)
            at = _point(source, target, q, lane, 9 + (5 if cast else 0))
            _ellipse(layer, at, (4 if i % 2 else 6) * scale, colors[2], .58)
        if stage:
            repeats = 2 if cast else 1
            for i in range(repeats):
                _claw(layer, _point(source, target, max(0., p - i * .10)), heading,
                      colors, .36 * scale, 2)
        return
    q = _age(phase, p) / LIFETIME
    fade = _fade(phase, p)
    if stage:
        _claw(layer, target, heading, colors, (.54 if cast else .44) * scale * fade, 2 if cast else 1)
    for i in range(round((10 + stage * 4) * density)):
        angle = i * 2.399 + q * 1.3
        at = (target[0] + math.cos(angle) * (9 + q * (48 + stage * 7)) * scale,
              target[1] + math.sin(angle) * (7 + q * (37 + stage * 5)) * scale - q * 13 * scale)
        _ellipse(layer, at, (3 if i % 3 else 5) * scale * fade, colors[1 if i % 2 else 3], .55)
    _impact_ring(layer, target, colors, q, .43 + stage * .04)


def _draw_armor(layer, source, target, phase, p, config, spec, *, cast=False):
    colors = rp.palette(spec['element'], config or {})
    scale, density = _settings(config, False)
    stage = spec['stage']
    if phase == 'windup':
        _charge(layer, source, colors, p, 3 + stage, .40 + stage * .06, 'spark', density=density)
        return
    heading = math.atan2(target[1] - source[1], target[0] - source[0])
    if phase == 'flight':
        plates = 3 if cast else 1
        for i in range(plates):
            q = max(0., p - i * .07)
            head = _point(source, target, q, (i - (plates - 1) / 2) * (18 if cast else 0),
                          (0 if stage < 2 else 7) + i * 3)
            _shield(layer, head, heading + i * .10, colors, (.34 + stage * .055) * scale)
        if stage == 2:
            for side in (-1, 1):
                _claw(layer, _point(source, target, p, side * 22, 8), heading,
                      colors, .34 * scale, 2)
        return
    q = _age(phase, p) / LIFETIME
    fade = _fade(phase, p)
    if stage == 2:
        _claw(layer, target, heading, colors, (.62 if cast else .54) * scale * fade, 4)
        _claw(layer, target, heading + math.pi / 2, colors, .36 * scale * fade, 2)
    else:
        _shield(layer, target, heading, colors, (.45 + stage * .08) * scale * fade)
    for i in range(round((6 + stage * 2) * density)):
        angle = i * 2.17 + q * .9
        at = (target[0] + math.cos(angle) * (11 + q * 52) * scale,
              target[1] + math.sin(angle) * (8 + q * 39) * scale)
        _poly(layer, ((at[0], at[1] - 9 * scale), (at[0] + 7 * scale, at[1] + 4 * scale),
                      (at[0] - 6 * scale, at[1] + 6 * scale)), colors[1 if i % 2 else 2])
    _impact_ring(layer, target, colors, q, .49 + stage * .05)


def _draw_cloud(layer, source, target, phase, p, config, spec, *, cast=False):
    colors = rp.palette(spec['element'], config or {})
    scale, density = _settings(config, False)
    stage = spec['stage']
    if phase == 'windup':
        _cloud(layer, source, colors, (.25 + stage * .06) * scale, p * .5)
        return
    if phase == 'flight':
        count = (4 if cast else 2) + stage * 2
        for i in range(round(count * density)):
            q = max(0., p - i * (.05 if cast else .07))
            lane = (i - (count - 1) / 2) * (25 if cast else 21)
            at = _point(source, target, q, lane, 16 + stage * 5)
            _cloud(layer, at, colors, (.19 + stage * .035) * scale, q * .6)
        return
    q = _age(phase, p) / LIFETIME
    fade = _fade(phase, p)
    if cast and stage == 0:
        _shield(layer, target, -math.pi / 2, colors, .46 * scale * fade)
    elif cast and stage == 1:
        for i in range(round(7 * density)):
            angle = i * 2.399 + q * .8
            at = (target[0] + math.cos(angle) * (13 + q * 43) * scale,
                  target[1] + math.sin(angle) * (10 + q * 33) * scale - q * 18 * scale)
            _outline(layer, ((at[0] - 7, at[1] - 6), (at[0] + 2, at[1]),
                             (at[0] - 3, at[1] + 8)), colors[3], 3)
    else:
        _cloud(layer, target, colors, (.45 + q * .13) * scale * fade, q * 1.2)
        _impact_ring(layer, target, colors, q, .43 + stage * .04, 8)


def _draw_serpent(layer, source, target, phase, p, config, spec, *, cast=False):
    colors = rp.palette(spec['element'], config or {})
    scale, density = _settings(config, False)
    stage = spec['stage']
    if phase == 'windup':
        _charge(layer, source, colors, p, 3 + stage, .38 + stage * .05, density=density)
        return
    if phase == 'flight':
        if stage == 0:
            drops = 3 if cast else 1
            for i in range(drops):
                q = max(0., p - i * .06)
                head = _point(source, target, q, math.sin(q * 3 + i) * (16 if cast else 8), 21)
                _drop(layer, head, colors, .47 * scale)
                _outline(layer, (source, head), colors[1], 3)
        else:
            for i in range(round((4 if cast else 3) * density)):
                q = max(0., p - i * .06)
                _path(layer, source, target, q, colors,
                      lane=math.sin(q * 5 + i) * 26, arc=14, width=7)
            for i in range(round((4 if cast else 3) * density)):
                q = max(0., p - i * .05)
                at = _point(source, target, q, math.sin(q * 5) * 25, 12)
                _ellipse(layer, at, 4 * scale, colors[4], .55)
        return
    q = _age(phase, p) / LIFETIME
    fade = _fade(phase, p)
    if stage:
        _path(layer, target, (target[0] + 1, target[1] + 1), q, colors,
              lane=math.sin(q * 5) * 27, arc=0, width=8)
    for i in range(round((7 + stage * 3) * density)):
        angle = i * 2.17 + q * 1.5
        at = (target[0] + math.cos(angle) * (9 + q * 49) * scale,
              target[1] + math.sin(angle) * (7 + q * 35) * scale - q * 15 * scale)
        _ellipse(layer, at, (3 if i % 2 else 5) * scale * fade, colors[3 if i % 3 == 0 else 2], .58)
    _impact_ring(layer, target, colors, q, .45 + stage * .04)


def _draw_dark(layer, source, target, phase, p, config, spec, *, cast=False):
    colors = rp.palette(spec['element'], config or {})
    scale, density = _settings(config, False)
    if phase == 'windup':
        _outline(layer, ((source[0] - 26 * scale, source[1] + 18 * scale),
                         (source[0], source[1] - 24 * scale),
                         (source[0] + 26 * scale, source[1] + 18 * scale)), colors[1], 9)
        _outline(layer, ((source[0] - 18 * scale, source[1] + 10 * scale),
                         (source[0], source[1] - 16 * scale),
                         (source[0] + 18 * scale, source[1] + 10 * scale)), colors[3], 3)
        return
    heading = math.atan2(target[1] - source[1], target[0] - source[0])
    if phase == 'flight':
        count = 3 if cast else 2
        for i in range(count):
            q = max(0., p - i * .05)
            at = _point(source, target, q, (i - 1) * 17, 11)
            c, s = math.cos(heading), math.sin(heading)
            nx, ny = -s, c
            pts = [(at[0] + c * -21 * scale + nx * 18 * scale,
                    at[1] + s * -21 * scale + ny * 18 * scale),
                   (at[0] + c * 22 * scale, at[1] + s * 22 * scale),
                   (at[0] + c * -21 * scale - nx * 18 * scale,
                    at[1] + s * -21 * scale - ny * 18 * scale)]
            _outline(layer, pts, colors[1], 9 * scale)
            _outline(layer, pts, colors[3], 5 * scale)
            _outline(layer, pts[:2], colors[4], 3)
        return
    q = _age(phase, p) / LIFETIME
    fade = _fade(phase, p)
    for i in range(3 if cast else 2):
        heading_i = heading + i * .32 - (0 if cast else .16)
        pts = [(target[0] + math.cos(heading_i - 1.2) * (18 + q * 50) * scale,
                target[1] + math.sin(heading_i - 1.2) * (15 + q * 39) * scale),
               (target[0] + math.cos(heading_i) * (28 + q * 51) * scale,
                target[1] + math.sin(heading_i) * (23 + q * 41) * scale),
               (target[0] + math.cos(heading_i + 1.2) * (18 + q * 50) * scale,
                target[1] + math.sin(heading_i + 1.2) * (15 + q * 39) * scale)]
        _outline(layer, pts, colors[1], max(3., 10 * scale * fade))
        _outline(layer, pts, colors[3], max(3., 5 * scale * fade))
    _impact_ring(layer, target, colors, q, .49)


def _draw_dragon(layer, source, target, phase, p, config, spec, *, cast=False):
    colors = rp.palette(spec['element'], config or {})
    scale, density = _settings(config, False)
    stage = spec['stage']
    if phase == 'windup':
        if stage == 0:
            _charge(layer, source, colors, p, 5 if cast else 3, .42, density=density)
        elif stage == 1:
            _shield(layer, source, p * 3, colors, (.45 if cast else .37) * scale)
        else:
            _wing(layer, source, math.atan2(target[1] - source[1], target[0] - source[0]),
                  colors, (.42 if cast else .34) * scale, 1.12 if cast else .88)
            _outline(layer, ((source[0] - 17, source[1] + 10), (source[0] + 17, source[1] + 10)),
                     colors[4], 3)
        return
    if phase == 'flight':
        heading = math.atan2(target[1] - source[1], target[0] - source[0])
        head = _point(source, target, p, 0, 0 if stage < 2 else 35)
        if stage == 2:
            _wing(layer, head, heading, colors, (.44 if cast else .35) * scale,
                  1.18 if cast else .88)
        else:
            _shield(layer, head, heading, colors, (.32 + stage * .055) * scale)
        if stage == 1:
            _path(layer, source, head, p, colors, lane=math.sin(p * 3) * 16, width=6)
        if stage == 2:
            _path(layer, source, head, p, colors, arc=35, width=8)
            for i in range(round(4 * density)):
                q = max(0., p - i * .055)
                at = _point(source, target, q, 0, 35)
                _ellipse(layer, at, 4 * scale, colors[4], .55)
        return
    q = _age(phase, p) / LIFETIME
    fade = _fade(phase, p)
    heading = math.atan2(target[1] - source[1], target[0] - source[0])
    _wing(layer, target, heading, colors, (.50 + stage * .055) * scale * fade,
          1.18 if cast else .86)
    if cast and stage == 2:
        _path(layer, source, target, 1, colors, arc=35, width=8)
    for i in range(round((5 + stage * 2) * density)):
        angle = i * 2.399 + q * 1.7
        at = (target[0] + math.cos(angle) * (11 + q * 55) * scale,
              target[1] + math.sin(angle) * (8 + q * 42) * scale)
        _poly(layer, ((at[0], at[1] - 10 * scale), (at[0] + 7 * scale, at[1] + 4 * scale),
                      (at[0] - 7 * scale, at[1] + 4 * scale)), colors[1 if i % 2 else 3])
    _impact_ring(layer, target, colors, q, .50 + stage * .04)


def _draw_magnet(layer, source, target, phase, p, config, spec, *, cast=False):
    colors = rp.palette(spec['element'], config or {})
    electric = rp.palette('ELECTRIC', config or {})
    scale, density = _settings(config, False)
    stage = spec['stage']
    if phase == 'windup':
        count = 3 + stage * 2
        for i in range(count):
            angle = i * math.tau / count + p * 2.7
            at = (source[0] + math.cos(angle) * (14 + p * 17) * scale,
                  source[1] + math.sin(angle) * (10 + p * 12) * scale)
            _outline(layer, (at, source), electric[2], 3)
        _ellipse(layer, source, 7 * scale, electric[3], .55)
        return
    heading = math.atan2(target[1] - source[1], target[0] - source[0])
    if phase == 'flight':
        head = _point(source, target, p)
        paths = (3 if cast else 1) + stage
        for i in range(paths):
            lane = (i - (paths - 1) / 2) * (22 if cast else 13)
            delayed = _point(source, target, max(0., p - i * (.035 if cast else .02)), lane, 4)
            _path(layer, source, delayed, max(0., p - i * .02), colors,
                  lane=lane, width=7 + stage * 2)
        if stage == 0:
            _shield(layer, head, heading, colors, (.44 if cast else .36) * scale)
        elif stage == 1:
            arms = 4 if cast else 2
            for i in range(arms):
                side = i - (arms - 1) / 2
                _path(layer, source, _point(source, target, p, side * 17, 4), p,
                      colors, lane=side * 17, width=5)
        else:
            for i in range(4):
                lane = (i - 1.5) * (23 if cast else 17)
                _claw(layer, _point(source, target, p, lane, 5), heading,
                      colors, .32 * scale, 1)
        return
    q = _age(phase, p) / LIFETIME
    fade = _fade(phase, p)
    if stage == 2:
        for i in range(4):
            angle = heading + i * math.pi / 2
            start = (target[0] + math.cos(angle + .65) * (36 + q * 9) * scale,
                     target[1] + math.sin(angle + .65) * (29 + q * 7) * scale)
            _claw(layer, start, angle, colors, (.38 if cast else .33) * scale * fade, 1)
        _impact_ring(layer, target, electric, q, .52, 4)
    else:
        _claw(layer, target, heading, colors, (.44 + stage * .09) * scale * fade,
              2 + stage)
    for i in range(round((5 + stage * 2) * density)):
        angle = i * 2.399 + q * 2.1
        at = (target[0] + math.cos(angle) * (10 + q * 47) * scale,
              target[1] + math.sin(angle) * (8 + q * 36) * scale)
        _outline(layer, ((at[0], at[1] - 7), (at[0] + 6, at[1] + 4), (at[0] - 5, at[1] + 5)),
                 electric[2], 3)
    _ellipse(layer, target, (7 + q * 18) * scale * fade, electric[3], .42)


_DRAWERS = {
    'leaf': _draw_leaf, 'fire': _draw_fire, 'mud': _draw_mud, 'lotad': _draw_lotad,
    'psy': _draw_psy, 'spore': _draw_spore, 'armor': _draw_armor,
    'cloud': _draw_cloud, 'serpent': _draw_serpent, 'dark': _draw_dark,
    'dragon': _draw_dragon, 'magnet': _draw_magnet,
}


def draw(layer, species_id, source, target, phase, progress, config, *,
         kind='cast', emitters=(), secondary=False):
    """Draw one real species action. Returns false for an unknown request."""
    if species_id not in SPECIES or phase not in PHASES or kind not in ('attack', 'cast'):
        return False
    p = _p(progress)
    if p >= 1:
        return True
    spec = _SPECIES[species_id]
    # Secondary packets are contact-sized only; no second windup/projectile.
    if secondary and phase in ('windup', 'flight'):
        return True

    raw_config = config or {}
    effective = dict(raw_config)
    density = min(1., max(.5, float(effective.get('particle_density', 1.))))
    effective['effect_scale'] = (
        float(effective.get('effect_scale', 1.)) *
        (1.08 if kind == 'cast' else .92) * (.65 if secondary else 1.) *
        (.95 + .10 * density))
    origins = ([tuple(emitter) for emitter in emitters if len(tuple(emitter)) >= 2]
               if emitters else [tuple(source)])
    if not origins:
        origins = [tuple(source)]

    # Draw on a packet-local cel so phase opacity never modifies actors or older
    # effects already composited into the supplied RGBA layer.
    overlay = Image.new('RGBA', layer.size, (0, 0, 0, 0))
    if phase == 'windup' and len(origins) > 1:
        for index, origin in enumerate(origins):
            # Real emitter positions drive staggered charge cels.
            _DRAWERS[spec['family']](
                overlay, origin, target, phase, max(0., p - index * .035),
                effective, spec, cast=(kind == 'cast'))
    else:
        _DRAWERS[spec['family']](overlay, origins[0], target, phase, p, effective,
                                 spec, cast=(kind == 'cast'))

    configured_scale = min(1.3, max(.7, float(raw_config.get('effect_scale', 1.))))
    alpha = _phase_alpha(phase, p) * (.80 + .14 * configured_scale + .06 * density)
    if alpha <= 0 or overlay.getbbox() is None:
        return True
    overlay.putalpha(overlay.getchannel('A').point(lambda value: int(value * alpha)))
    layer.alpha_composite(overlay)
    return True


def draw_attack_motif(d, sid, x, y, k, angle, hit):
    """Small 64-pixel preview motif used by the legacy attack registry."""
    spec = _SPECIES.get(sid)
    if not spec or not hasattr(d, 'polygon'):
        return False
    colors = rp.palette(spec['element'], {})
    stage = spec['stage']
    radius = 5 + k * (7 + stage * 2)
    if spec['family'] == 'leaf':
        for i in range(stage + 1):
            a = angle + i * .35
            d.polygon(((x + math.cos(a) * radius, y + math.sin(a) * radius * .8),
                       (x + math.cos(a + 1.3) * radius * .7,
                        y + math.sin(a + 1.3) * radius * .55),
                       (x + math.cos(a - .8) * radius * .6,
                        y + math.sin(a - .8) * radius * .45)), fill=colors[2])
            d.line(((x, y), (x + math.cos(a) * radius, y + math.sin(a) * radius * .8)),
                   fill=colors[4], width=1)
    elif spec['family'] in ('fire', 'dragon'):
        count = 2 + stage
        for i in range(count):
            a = angle + (i - (count - 1) / 2) * .38
            d.arc((x - radius * 1.2, y - radius, x + radius * 1.2, y + radius),
                  math.degrees(a - .7), math.degrees(a + .7), fill=colors[2], width=2)
    elif spec['family'] in ('mud', 'serpent'):
        for i in range(stage + 1):
            at = (x + (i - stage / 2) * 7, y + (i % 2) * 3 - 1)
            d.ellipse((at[0] - 5, at[1] - 4, at[0] + 5, at[1] + 4), fill=colors[2])
            d.line(((at[0] - 3, at[1]), (at[0] + 3, at[1] - 2)), fill=colors[4], width=1)
    elif spec['family'] in ('lotad', 'psy', 'cloud'):
        for i in range(3 + stage):
            a = angle + i * math.tau / (3 + stage) + k * 3
            at = (x + math.cos(a) * radius, y + math.sin(a) * radius * .7)
            d.ellipse((at[0] - 3, at[1] - 3, at[0] + 3, at[1] + 3), fill=colors[2])
    elif spec['family'] == 'dark':
        d.arc((x - radius, y - radius * .8, x + radius, y + radius * .8),
              math.degrees(angle - 1.1), math.degrees(angle + 1.1), fill=colors[3], width=3)
        d.line(((x - radius * .7, y), (x + radius * .7, y)), fill=colors[4], width=1)
    else:
        # Spore/armor/magnet share only this fallback compact stamp; full tracks differ.
        count = 3 + stage
        for i in range(count):
            a = angle + i * math.tau / count + k * 2
            d.line(((x, y), (x + math.cos(a) * radius, y + math.sin(a) * radius * .75)),
                   fill=colors[2], width=3)
            d.rectangle((x + math.cos(a) * radius - 2, y + math.sin(a) * radius * .75 - 2,
                         x + math.cos(a) * radius + 2, y + math.sin(a) * radius * .75 + 2),
                        fill=colors[4])
    if hit:
        d.ellipse((x - radius - 4, y - radius - 3, x + radius + 4, y + radius + 3),
                  outline=colors[4], width=1)
    return True
