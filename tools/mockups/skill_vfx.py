"""Read-only skill adapter and nine deterministic, attribute-coloured templates."""
import math

from PIL import ImageDraw
from render_mockups import TYPE_COLORS, PAPER
from profile_vfx import SIGNATURES, signature_cast
from pixel_vfx import light, impact_rim, projectile, trajectory_point, impact_star, exposure_age

try:
    from skills import skill_of as _skill_of
except ImportError:
    _skill_of = None

ARCHS = ('double_strike', 'charge', 'bulwark', 'mend', 'volley_shot',
         'heavy_blow', 'splash', 'blink_strike', 'slam_heal')
FALLBACK = {6: ('splash', '大字爆炎'), 65: ('blink_strike', '精神强念'),
            143: ('slam_heal', '泰山压顶')}


def skill_profile(sid):
    profile = _skill_of(sid) if _skill_of else None
    if profile and profile.get('arch') in ARCHS:
        return profile
    if sid in FALLBACK:
        arch, name = FALLBACK[sid]
        return {'arch': arch, 'name': name, 'tier': 'signature'}
    return {'arch': 'heavy_blow', 'name': '重击', 'tier': 'generic'}


def cast_windup(sid):
    return SIGNATURES[sid].windup if sid in SIGNATURES else .4


def draw_charge(img, source, progress, color):
    """Foot ring brightens in four integer stages; no solid body overlay."""
    x, y = source
    bright = color
    d = ImageDraw.Draw(img)
    d.ellipse((x - 20, y - 5, x + 20, y + 5), outline=bright, width=2)
    d.arc((x - 23, y - 7, x + 23, y + 7), 0, round(360 * progress), fill=PAPER, width=1)


def draw_skill(img, profile, source, target, age, windup, budget, variant=0, emblem=None):
    color = TYPE_COLORS[profile['type']]
    if age < windup:
        draw_charge(img, (source[0], source[1] + 16), max(0, age / windup), color)
        return
    elapsed = age - windup
    if not 0 <= elapsed < .6:
        return
    arch = profile['arch']
    if arch in ('splash', 'blink_strike', 'slam_heal'):
        sid = {'splash': 6, 'blink_strike': 65, 'slam_heal': 143}[arch]
        signature_cast(img, sid, source, target, age, windup, budget, emblem, color=color)
    d = ImageDraw.Draw(img)
    sx, sy = source
    tx, ty = target
    phase = int((elapsed + 1e-9) / .1)
    flip = -1 if variant else 1
    if arch == 'double_strike':
        for delay, off in ((0., -5), (.15, 5)):
            if delay <= elapsed < delay + .3:
                d.line((tx - 10, ty + off + 8 * flip, tx + 10, ty + off - 8 * flip), fill=color, width=3)
                d.line((tx - 9, ty + off + 7 * flip, tx + 9, ty + off - 7 * flip), fill=PAPER, width=1)
    elif arch == 'charge':
        if phase < 3:
            # Three open chevrons, fading each frame; never a solid sprite copy.
            for i in budget.take(3):
                k = max(0, 1 - (i + 1) * .12)
                x, y = sx + (tx - sx) * k, sy + (ty - sy) * k
                d.line((x - 7, y - 9, x, y, x - 7, y + 9), fill=color + (max(32, 160 - phase * 48 - i * 24),), width=2)
        d.polygon(((tx, ty - 11), (tx + 11, ty), (tx, ty + 11), (tx - 11, ty)), outline=color, width=3)
    elif arch == 'bulwark':
        points = [(sx + round(23 * math.cos(i * math.tau / 6)), sy + round(23 * math.sin(i * math.tau / 6))) for i in range(6)]
        d.line(points + points[:1], fill=color, width=2)
        for i in budget.take(8):
            a = i * math.tau / 8
            d.line((sx + 27 * math.cos(a), sy + 27 * math.sin(a), sx + 31 * math.cos(a), sy + 31 * math.sin(a)), fill=PAPER, width=1)
    elif arch == 'mend':
        y = sy - 23
        d.line((sx - 4, y, sx + 4, y), fill=PAPER, width=2)
        d.line((sx, y - 4, sx, y + 4), fill=color, width=2)
        for i in budget.take(3):
            x, y = sx - 12 + i * 12, sy + 5 - phase * 3 - i * 4
            light(d, x, y, color)
    elif arch == 'volley_shot':
        if elapsed < .3:
            for ox,oy in ((0,-8),(-7,5),(7,5)):
                a,b = (sx+ox,sy+oy),(tx+ox,ty+oy)
                projectile(img, lambda p: trajectory_point(a,b,p), exposure_age(elapsed,.3), .3,
                           profile['type'], color, budget)
    elif arch == 'heavy_blow':
        d.line((tx - 9, ty + 9 * flip, tx + 9, ty - 9 * flip), fill=color, width=5)
        d.line((tx - 8, ty + 7 * flip, tx + 8, ty - 7 * flip), fill=PAPER, width=1)
    # Universal skill impact: two OUTER rings, visibly larger than basic impact.
    radius = 30 + phase * 3
    for rr in (radius, radius + 8):
        impact_rim(img, (tx,ty), rr, color, phase, budget, rays=3)
    direction = math.atan2(ty-sy, tx-sx)
    contact = profile.get('target_size', 32) * .4
    impact_star(d, round(tx-contact*math.cos(direction)), round(ty-contact*math.sin(direction)),
                min(10, 8+phase), direction, color, variant*31+phase//2)
    d.arc((tx - radius - 3, ty - radius - 3, tx + radius + 3, ty + radius + 3),
          30 + variant * 90 + phase * 20, 110 + variant * 90 + phase * 20, fill=PAPER, width=2)
