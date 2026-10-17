"""Finite species attack silhouettes on the native skills' three-pixel grid."""
from functools import lru_cache
import math

from PIL import Image, ImageDraw

import arena_vfx
import family_vfx
import retro_primitives as rp


@lru_cache(maxsize=512)
def _motif(sid, phase, step, direction, palette, size):
    cel = Image.new('RGBA', (64, 64))
    p = step / 16
    k = p * .3 if phase == 'windup' else .25 if phase == 'flight' else p if phase == 'impact' else 1.
    angle = direction * math.tau / 32 + p * 2
    arena_vfx.EFFECTS[sid][1](ImageDraw.Draw(cel), 32, 32, k, angle,
                            phase in ('impact', 'aftermath'))
    if palette == 'vivid':
        r, g, b, alpha = cel.split()
        lut = [min(255, round(v * 1.08 + 5)) for v in range(256)]
        cel = Image.merge('RGBA', (r.point(lut), g.point(lut), b.point(lut), alpha))
    # Resize before the exact 3x upscale: colored pixels retain integer cells.
    return cel.resize((size, size), Image.Resampling.NEAREST).resize(
        (size * rp.PIXEL, size * rp.PIXEL), Image.Resampling.NEAREST)


def draw(layer, sid, source, target, phase, p, config, *, ranged=False, trails=0):
    if family_vfx.draw(layer, sid, source, target, phase, p, config, kind='attack'):
        return True
    if sid not in arena_vfx.EFFECTS or phase not in ('windup', 'flight', 'impact', 'aftermath'):
        return False
    if not 0 <= p < 1:
        return True
    scale, density = rp.settings(config)
    dx, dy = target[0] - source[0], target[1] - source[1]
    direction = round(math.atan2(dy, dx) / math.tau * 32) % 32
    size = max(1, round(64 * .6 * scale))
    if phase == 'windup':
        size = max(1, round(size * (.38 + .32 * p)))
    elif phase == 'aftermath':
        size = max(1, round(size * (1 - p) ** .7))

    def position(q):
        x, y = rp.point(source, target, q)
        if ranged and sid in (40, 12, 36, 45, 80):
            y -= math.sin(q * math.pi) * 24
        elif ranged and sid in (94, 65, 121):
            length = math.hypot(dx, dy) or 1
            x += math.sin(q * math.tau) * dy / length * 9
            y -= math.sin(q * math.tau) * dx / length * 9
        return x, y

    q = 0. if phase == 'windup' else p if phase == 'flight' else 1.
    # Caller reserves the short trailing silhouettes from the particle budget.
    if phase == 'flight':
        for i in range(min(2, trails, round(2 * density)), 0, -1):
            previous = q - i * .12
            if previous <= 0:
                continue
            art = _motif(sid, phase, round(p * 16), direction, config['palette'], size).copy()
            art.putalpha(art.getchannel('A').point(lambda a: round(a * .18 / i)))
            at = position(previous)
            layer.alpha_composite(art, (round(at[0] - art.width / 2), round(at[1] - art.height / 2)))
    art = _motif(sid, phase, min(16, round(p * 16)), direction, config['palette'], size)
    if phase == 'aftermath':
        art = art.copy()
        art.putalpha(art.getchannel('A').point(lambda a: round(a * (1 - p))))
    at = position(q)
    layer.alpha_composite(art, (round(at[0] - art.width / 2), round(at[1] - art.height / 2)))
    return True
