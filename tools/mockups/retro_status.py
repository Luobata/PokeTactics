"""Bounded pixel-art motifs for persistent unit ailments.

This module is presentation-only.  Callers pass replay-derived active kinds,
the actor's actual sprite bounds, and the presentation clock; nothing here
reads or writes simulation state.  Drawing is a pure function of those inputs,
so backwards seeks and direct jumps reproduce the same frame.
"""
from __future__ import annotations

from collections.abc import Iterable
import math

from PIL import Image, ImageDraw

import retro_primitives as pixels


PIXEL = pixels.PIXEL
SUPPORTED_KINDS = frozenset({
    'burn', 'poison', 'paralysis', 'sleep', 'freeze', 'root', 'vulnerability'
})
BODY_KINDS = ('freeze', 'sleep', 'paralysis', 'burn', 'poison')
CONTROL_KINDS = ('freeze', 'sleep', 'paralysis')
FOOT_KINDS = ('root', 'vulnerability')
MAX_MOTIFS = 5
_ALIASES = {
    'burned': 'burn', 'poisoned': 'poison', 'para': 'paralysis',
    'paralyzed': 'paralysis', 'frozen': 'freeze', 'ice': 'freeze',
    'rooted': 'root', 'bound': 'root', 'vulnerable': 'vulnerability',
}


def normalize_kinds(kinds: Iterable[str] | None) -> tuple[str, ...]:
    """Return supported kinds in the presentation order, ignoring unknowns."""
    found = set()
    for kind in kinds or ():
        normalized = _ALIASES.get(str(kind), str(kind))
        if normalized in SUPPORTED_KINDS:
            found.add(normalized)
    ranked = [kind for kind in (*CONTROL_KINDS, 'root', 'vulnerability',
                                'burn', 'poison') if kind in found]
    return tuple(ranked)


def info() -> dict[str, object]:
    """Describe the stable integration contract for callers and tests."""
    return {
        'version': 1,
        'supported_kinds': tuple(sorted(SUPPORTED_KINDS)),
        'control_priority': CONTROL_KINDS,
        'body_kinds': BODY_KINDS,
        'foot_kinds': FOOT_KINDS,
        'max_motifs': MAX_MOTIFS,
        'clock': 'deterministic 10 Hz samples of presentation t + actor idx',
        'grid': PIXEL,
    }


def foot_anchor(bounds: tuple[float, float, float, float]) -> tuple[int, int]:
    """Return the centered bottom anchor on the module's pixel grid."""
    left, top, right, bottom = _clean_bounds(bounds)
    return _snap((left + right) / 2), _snap(bottom)


def rig_anchors(bounds: tuple[float, float, float, float], foot=None,
                facing: int = 1) -> dict[str, tuple[int, int]]:
    """Derive a few local attachment points from actual visible bounds.

    These anchors are deliberately sparse. Persistent ailments should remain
    material around the body, not become independent emitters all over a unit.
    """
    left, top, right, bottom = _clean_bounds(bounds)
    center = (left + right) / 2
    anchor = foot or (center, bottom)
    side = 1 if facing >= 0 else -1
    return {
        'head': (_snap(center + side * 6), _snap(top + max(3., (bottom-top)*.08))),
        'left_shoulder': (_snap(left + max(3., (right-left)*.12)),
                          _snap(top + (bottom-top)*.30)),
        'right_shoulder': (_snap(right - max(3., (right-left)*.12)),
                           _snap(top + (bottom-top)*.30)),
        'left_flank': (_snap(left - 3), _snap(top + (bottom-top)*.55)),
        'right_flank': (_snap(right + 3), _snap(top + (bottom-top)*.55)),
        'left_foot': (_snap(float(anchor[0]) - 6), _snap(float(anchor[1]))),
        'right_foot': (_snap(float(anchor[0]) + 6), _snap(float(anchor[1]))),
    }


def tint_sprite(sprite: Image.Image, kinds: Iterable[str] | None) -> Image.Image:
    """Apply the classic light poison tint while preserving alpha and sprite info."""
    if 'poison' not in normalize_kinds(kinds):
        return sprite
    if sprite.mode != 'RGBA':
        raise ValueError('persistent status sprites must be RGBA')
    bands = list(sprite.split())
    # A channel-wise blend keeps partial source alpha untouched. Carrying .info
    # preserves the caller's rig/foot metadata for later drawing passes.
    for channel, target in enumerate((184, 112, 200)):
        bands[channel] = bands[channel].point(
            lambda value, target=target: round(value * .85 + target * .15))
    tinted = Image.merge('RGBA', bands)
    tinted.info = dict(sprite.info)
    return tinted


def draw_body(image: Image.Image, kinds: Iterable[str] | None, foot,
              bounds: tuple[float, float, float, float], t: float,
              idx: int = 0) -> frozenset[str]:
    """Draw compact local ailments around an actor and return the kinds drawn.

    ``bounds`` is the actual visible sprite rectangle in ``image`` coordinates;
    ``foot`` is its replay foot point. At most five motif groups are shown. A
    control ailment is primary when present; burn/poison then shrink to tiny
    foot-side markers instead of stacking several full-body cues. All motion is
    quantized to 10 Hz and derived only from ``t + idx``.
    """
    if image.mode != 'RGBA':
        raise ValueError('persistent status layers must be RGBA')
    shown = normalize_kinds(kinds)
    if not shown:
        return frozenset()

    left, top, right, bottom = _clean_bounds(bounds)
    base_foot = _point(foot) if foot is not None else foot_anchor(bounds)
    frame = int((float(t) * 10 + int(idx)) % 100000)
    local = Image.new('RGBA', (max(1, right-left + 48), max(1, bottom-top + 48)),
                      (0, 0, 0, 0))
    draw = ImageDraw.Draw(local)
    origin = (_snap(left - 24), _snap(top - 24))
    anchors = rig_anchors(bounds, base_foot)

    control = next((kind for kind in CONTROL_KINDS if kind in shown), None)
    groups: list[tuple[str, bool]] = []
    if control:
        groups.append((control, True))
    # Root/vulnerability stay readable because they occupy separate foot bands.
    groups.extend((kind, True) for kind in FOOT_KINDS if kind in shown)
    # With a control present, DOTs become one-pixel foot notes rather than two
    # additional body layers. Without a control, they can use their local forms.
    groups.extend((kind, control is None) for kind in ('burn', 'poison') if kind in shown)
    groups = groups[:MAX_MOTIFS]

    for kind, full in groups:
        if kind == 'freeze':
            _freeze(draw, bounds, origin)
        elif kind == 'sleep':
            _sleep(draw, anchors['head'], origin, frame)
        elif kind == 'paralysis':
            _paralysis(draw, bounds, origin, frame, full)
        elif kind == 'burn':
            _burn(draw, bounds, base_foot, origin, frame, full)
        elif kind == 'poison':
            _poison(draw, bounds, base_foot, origin, frame, full)
        elif kind == 'root':
            _root(draw, base_foot, origin, frame)
        elif kind == 'vulnerability':
            _vulnerable(draw, base_foot, origin)

    # Keep the local layer inside the supplied image. This also prevents a bad
    # anchor from painting a distant field-level flash.
    x0, y0 = origin
    x1, y1 = x0 + local.width, y0 + local.height
    if x1 <= 0 or y1 <= 0 or x0 >= image.width or y0 >= image.height:
        return frozenset()
    crop = local.crop((max(0, -x0), max(0, -y0),
                       min(local.width, image.width-x0),
                       min(local.height, image.height-y0)))
    image.alpha_composite(crop, (max(0, x0), max(0, y0)))
    return frozenset(kind for kind, _ in groups)


def _freeze(draw, bounds, origin):
    left, top, right, bottom = bounds
    x0, y0 = origin
    x1, y1 = left-x0, top-y0
    x2, y2 = right-x0, bottom-y0
    shell = ((x1-6, y1+9), (x1-2, y1-5), (x1+9, y1-8), (x2+7, y1-3),
             (x2+9, y2-8), (x2+3, y2+6), (x1+7, y2+10), (x1-3, y2+4))
    snapped = [_point(point) for point in shell]
    draw.polygon(snapped, fill=(132, 213, 246, 30))
    draw.line(snapped + [snapped[0]], fill=(197, 243, 255, 122), width=3, joint='curve')
    draw.line(((_point((x1+9, y1-8)), _point(((x1+x2)/2, (y1+y2)/2)),
                _point((x1-3, y2+4)))), fill=(232, 250, 255, 62), width=3)
    draw.line(((_point((x2+7, y1-3)), _point(((x1+x2)/2, (y1+y2)/2)),
                _point((x2+3, y2+6)))), fill=(120, 194, 232, 58), width=3)
    # Two tiny highlights distinguish ice without filling the whole shell.
    draw.rectangle((_point((x1+3, y1+3)), _point((x1+8, y1+6))), fill=(242, 255, 255, 108))
    draw.rectangle((_point((x2-8, y2-6)), _point((x2-3, y2-3))), fill=(242, 255, 255, 86))


def _sleep(draw, head, origin, frame):
    x, y = head[0]-origin[0]+6, head[1]-origin[1]-12-(frame % 4)
    x, y = _snap_local(x), _snap_local(y)
    alpha = 190 if frame % 2 == 0 else 150
    color = (172, 184, 249, alpha)
    for dy in (0, 3):
        draw.line(((x, y+dy, x+6, y+dy)), fill=color, width=3)
    draw.line(((x+6, y), (x, y+3)), fill=color, width=3)
    draw.line(((x, y+3), (x+6, y+3)), fill=color, width=3)
    draw.rectangle((_point((x+6, y-3)), _point((x+8, y-1))), fill=(214, 224, 253, alpha))


def _paralysis(draw, bounds, origin, frame, full):
    # An intermittent local arc avoids turning paralysis into a constant strobe.
    if frame % 3 != 0:
        return
    left, top, right, bottom = bounds
    x0, y0 = origin
    if full:
        x = right-x0+3
        y1, y2 = top-y0+(bottom-top)*.20, top-y0+(bottom-top)*.65
    else:
        x = right-x0
        y1, y2 = bottom-y0-4, bottom-y0+1
    path = (_snap_local((x, y1)), _snap_local((x-5, y1+(y2-y1)*.38)),
            _snap_local((x+4, y1+(y2-y1)*.62)), _snap_local((x-2, y2)))
    draw.line(path, fill=(254, 225, 102, 230), width=3, joint='curve')
    draw.line(path, fill=(255, 248, 190, 175), width=3)
    draw.rectangle((_point((path[-1][0], path[-1][1]-3)), path[-1]), fill=(255, 248, 190, 175))


def _burn(draw, bounds, foot, origin, frame, full):
    left, top, right, bottom = bounds
    x0, y0 = origin
    if full:
        positions = ((left-x0-4, bottom-y0-5), (right-x0+4, bottom-y0-10))
    else:
        positions = ((foot[0]-x0+9, foot[1]-y0-3),)
    for index, (x, y) in enumerate(positions):
        rise = (frame + index*4) % 6
        point = _snap_local((x, y-rise))
        draw.line((point, _snap_local((x+3, y+3-rise))), fill=(253, 123, 32, 210), width=3)
        draw.rectangle((_point((point[0]+3, point[1]-3)), _point((point[0]+5, point[1]-1))), fill=(255, 208, 68, 235))
        if rise < 3:
            draw.rectangle((_point((point[0]-3, point[1])), _point((point[0]-1, point[1]+2))), fill=(254, 167, 83, 150))


def _poison(draw, bounds, foot, origin, frame, full):
    left, top, right, bottom = bounds
    x0, y0 = origin
    if full:
        positions = ((left-x0+(right-left)*.20, top-y0+(bottom-top)*.28),
                     (right-x0-(right-left)*.17, top-y0+(bottom-top)*.50))
    else:
        positions = ((foot[0]-x0-9, foot[1]-y0-3),)
    for index, (x, y) in enumerate(positions):
        drip = (frame + index*3) % 4
        point = _snap_local((x, y+drip))
        draw.polygon((point, (point[0]-3, point[1]+6), (point[0]+3, point[1]+6)),
                     fill=(193, 103, 223, 205))
        draw.rectangle((point, _point((point[0], point[1]+2))), fill=(235, 171, 244, 240))


def _root(draw, foot, origin, frame):
    x, y = foot[0]-origin[0], foot[1]-origin[1]
    phase = frame % 2
    for offset in (-9, 0, 9):
        x1 = _snap_local((x+offset-4))
        x2 = _snap_local((x+offset+4))
        yy = _snap_local((y + (1 if offset and phase == (0 if offset < 0 else 1) else 0)))
        draw.line(((x1, yy), (x2, yy)), fill=(152, 216, 102, 195), width=3)
        draw.rectangle(((_point((x2, yy-3))), _point((x2+2, yy-1))), fill=(207, 238, 112, 150))


def _vulnerable(draw, foot, origin):
    x, y = foot[0]-origin[0], foot[1]-origin[1]
    center = _snap_local((x, y+3))
    draw.line(((_snap_local((x-9, y+1))), center, _snap_local((x+9, y+1))),
              fill=(255, 173, 126, 195), width=3, joint='curve')
    draw.line((center, _snap_local((x-3, y+7))), fill=(255, 173, 126, 150), width=3)
    draw.line((center, _snap_local((x+4, y+7))), fill=(223, 139, 101, 125), width=3)


def _clean_bounds(bounds):
    values = tuple(float(value) for value in bounds)
    if len(values) != 4 or not all(math_is_finite(value) for value in values):
        raise ValueError('bounds must be four finite values')
    left, top, right, bottom = values
    if right <= left or bottom <= top:
        raise ValueError('bounds must enclose the visible sprite')
    return round(left), round(top), round(right), round(bottom)


def _point(point):
    return _snap(point[0]), _snap(point[1])


def _snap(value):
    return round(float(value) / PIXEL) * PIXEL


def _snap_local(value):
    if isinstance(value, tuple):
        return _point(value)
    return round(float(value) / PIXEL) * PIXEL


def math_is_finite(value):
    return math.isfinite(value)
