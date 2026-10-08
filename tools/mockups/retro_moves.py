"""Authored handheld-style move cels for the shared arena renderer.

These are original pixel drawings, made from a small palette and enlarged with
nearest-neighbour sampling. They receive their causal phase from the battle
presentation timeline; they neither choose victims nor advance a battle clock.
"""
from functools import lru_cache
import math

from PIL import Image, ImageDraw

# A fixed 3px grid gives the 960px arena the deliberate, chunky edges of G3.
PIXEL_SIZE = 3
CONTACT_DURATION = .22
FIRE_BLAST_LIFETIME = .8
PALETTES = {
    'classic': ((117, 31, 31), (213, 53, 26), (250, 117, 32),
                (255, 202, 58), (255, 242, 178)),
    'vivid': ((139, 25, 39), (240, 49, 25), (255, 128, 24),
              (255, 222, 57), (255, 252, 214)),
}


def _bounded(value, low, high, default):
    value = float(value)
    return min(high, max(low, value)) if math.isfinite(value) else default


def _settings(config):
    palette = config.get('palette', 'classic')
    if palette not in PALETTES:
        palette = 'classic'
    return (palette,
            _bounded(config.get('effect_scale', 1.), .7, 1.3, 1.),
            _bounded(config.get('particle_density', 1.), .5, 1., 1.))


def _finish(cel, scale):
    """Resize on the logical grid first, then expose only whole screen pixels."""
    logical = (max(1, round(cel.width * scale)),
               max(1, round(cel.height * scale)))
    if logical != cel.size:
        cel = cel.resize(logical, Image.Resampling.NEAREST)
    return cel.resize((logical[0] * PIXEL_SIZE, logical[1] * PIXEL_SIZE),
                      Image.Resampling.NEAREST)


def _put(layer, cel, point):
    layer.alpha_composite(cel, (round(point[0] - cel.width / 2),
                               round(point[1] - cel.height / 2)))


def _stroke(draw, points, color, width):
    draw.line(points, fill=color, width=width, joint='curve')
    # Low-resolution square brush ends keep the cel crisp, without vector caps.
    radius = (width - 1) // 2
    for x, y in points:
        draw.rectangle((x - radius, y - radius, x + radius, y + radius),
                       fill=color)


def _flame_edge(draw, root, tip, bend, colors):
    """An uneven tapered tongue, hot at its root and red at its curling tip."""
    rx, ry = root
    tx, ty = tip
    dx, dy = tx-rx, ty-ry
    length = math.hypot(dx, dy) or 1.
    nx, ny = -dy/length, dx/length
    middle = ((rx+tx)*.5 + nx*bend, (ry+ty)*.5 + ny*bend)
    edge = ((rx-nx*1.6, ry-ny*1.6),
            (middle[0]-nx, middle[1]-ny), (tx, ty),
            (middle[0]+nx*1.6, middle[1]+ny*1.6),
            (rx+nx*2, ry+ny*2))
    draw.polygon(edge, fill=colors[1])
    draw.line((root, middle), fill=colors[2], width=2)
    draw.line((root, ((rx+middle[0])*.5, (ry+middle[1])*.5)),
              fill=colors[3], width=1)


@lru_cache(maxsize=96)
def _glyph(palette, frame, dissolve):
    """A burning five-armed silhouette with broken cores and live flame edges."""
    colors = PALETTES[palette]
    cel = Image.new('RGBA', (48, 48))
    draw = ImageDraw.Draw(cel)
    cx, cy = 24, 24
    paths = (
        ((-15, -8), (-7, -8), (7, -8), (15, -8)),
        ((0, -17), (0, -3), (-4, 4), (-10, 11), (-15, 16)),
        ((1, -2), (5, 5), (10, 11), (15, 16)),
    )
    # The orange fire body carries the shape. Cream is reserved for scattered
    # heat pockets, rather than a continuous typographic outline or neon tube.
    for width, color in ((7, colors[0]), (5, colors[1]), (3, colors[2])):
        for path in paths:
            _stroke(draw, [(cx+x, cy+y) for x, y in path], color, width)
    pixels = cel.load()
    for y in range(cel.height):
        for x in range(cel.width):
            ink = pixels[x, y]
            if not ink[3]:
                continue
            flow = (x*7 + y*13 + frame*5) % 17
            if ink[:3] == colors[0] and flow in (0, 1, 8):
                pixels[x, y] = (0, 0, 0, 0)
            elif ink[:3] == colors[2] and flow < 8:
                pixels[x, y] = (*colors[3 if flow < 6 else 4], 255)
    # Sample BOTH edges of every stroke, including the crossbar and diagonals.
    # Curled tongues vary in height from cel to cel; their roots always hug the
    # original silhouette so the attack remains legible in a crowded battle.
    seed = 0
    for path in paths:
        for a, b in zip(path, path[1:]):
            dx, dy = b[0]-a[0], b[1]-a[1]
            length = math.hypot(dx, dy) or 1.
            nx, ny = -dy/length, dx/length
            steps = max(1, round(length/3))
            for index in range(steps):
                t = (index+.35)/steps
                x, y = a[0]+dx*t, a[1]+dy*t
                for side in (-1, 1):
                    seed += 1
                    if seed % 5 == 0:
                        continue
                    flutter = (seed*11 + frame*7) % 5
                    root = (cx+x+nx*side*1.9, cy+y+ny*side*1.9)
                    tip = (cx+x+nx*side*(4+flutter*.45)+(flutter-2)*.4,
                           cy+y+ny*side*(4+flutter*.45)-2-flutter*.4)
                    # Keep the living outline inside the established local
                    # budget at the editor's maximum 1.3x effect scale.
                    tip = (min(45, max(3, tip[0])), min(45, max(2, tip[1])))
                    _flame_edge(draw, root, tip, (seed % 3-1)*1.2, colors)
    # A few broken white-hot knots burn through the denser orange envelope.
    for index, (x, y) in enumerate(((-11,-8),(-4,-8),(6,-8),(12,-8),
                                    (0,-13),(-3,4),(-9,10),(7,8),(13,14))):
        jitter = (frame+index) % 3-1
        draw.line(((cx+x, cy+y), (cx+x+jitter, cy+y-1)),
                  fill=colors[4 if (frame+index)%3 == 0 else 3], width=1)
    if dissolve:
        # Coherent little chunks break away; no translucent full-glyph overlay.
        for y in range(cel.height):
            for x in range(cel.width):
                rank = ((x//2)*17 + (y//2)*29 + 11) % 12
                if rank < dissolve:
                    pixels[x, y] = (0, 0, 0, 0)
    return cel


@lru_cache(maxsize=192)
def _fireball(palette, frame, direction):
    """A rounded fire seed with a forked, stepped tail pointing away from travel."""
    colors = PALETTES[palette]
    cel = Image.new('RGBA', (40, 40))
    draw = ImageDraw.Draw(cel)
    angle = direction * math.tau / 32
    ux, uy = math.cos(angle), math.sin(angle)
    nx, ny = -uy, ux

    def points(path):
        return [(round(20 + ux*x + nx*y), round(20 + uy*x + ny*y))
                for x, y in path]

    flutter = frame % 3
    outer = ((-17, 0), (-12, -2), (-14 + flutter, -4), (-9, -3),
             (-10, -7), (-5, -5), (-1, -7), (3, -6), (6, -3),
             (7, 0), (6, 3), (3, 6), (-1, 7), (-5, 5), (-10, 6),
             (-9, 3), (-15, 4), (-13, 1))
    body = ((-13, 0), (-8, -2), (-7, -4), (-2, -5), (3, -4),
            (5, -1), (5, 2), (2, 4), (-2, 5), (-6, 3), (-10, 3))
    hot = ((-8, 0), (-4, -2), (-1, -3), (2, -2), (3, 0),
           (2, 2), (-1, 3), (-4, 1))
    draw.polygon(points(outer), fill=colors[0])
    draw.polygon(points(body), fill=colors[1])
    # An off-centre warm edge makes the front read as a head, not a beam.
    draw.line(points(((3, -3), (4, -1), (4, 2), (2, 3))),
              fill=colors[2], width=2)
    draw.polygon(points(hot), fill=colors[3])
    draw.line(points(((-3, 0), (0, -1), (1, 0))),
              fill=colors[4], width=1)
    return cel


@lru_cache(maxsize=32)
def _ember(palette, frame, tiny=False):
    colors = PALETTES[palette]
    cel = Image.new('RGBA', (7, 9))
    draw = ImageDraw.Draw(cel)
    if tiny:
        draw.rectangle((3, 3, 4, 5), fill=colors[2])
        draw.point((3, 3), fill=colors[4])
    else:
        flutter = frame % 3
        draw.polygon(((2, 7), (1, 5), (2, 3), (2 + flutter, 1),
                      (4, 3), (5, 5), (4, 7)), fill=colors[1])
        draw.line(((3, 6), (3, 3), (4, 2 + flutter)),
                  fill=colors[3], width=1)
        draw.point((3, 4), fill=colors[4])
    # Crop decoration cels so low editor scales cannot sample only transparent
    # padding and accidentally erase every late ember.
    return cel.crop(cel.getchannel('A').getbbox())


@lru_cache(maxsize=384)
def _spark(palette, frame, direction, large=False):
    """A hot-headed cinder with a stepped red tail, oriented along its velocity."""
    colors = PALETTES[palette]
    cel = Image.new('RGBA', (24, 24))
    draw = ImageDraw.Draw(cel)
    angle = direction*math.tau/32
    ux, uy = math.cos(angle), math.sin(angle)
    nx, ny = -uy, ux

    def points(path):
        return [(round(12+ux*x+nx*y), round(12+uy*x+ny*y))
                for x, y in path]

    flicker = frame % 3
    tail = 9 if large else 6+flicker
    body = ((-tail,0),(-tail+3,-1),(-4,-1),(-2,-2),
            (2,-2),(3,0),(1,2),(-3,2),(-5,1))
    draw.polygon(points(body), fill=colors[1])
    draw.line(points(((-tail+3,0),(-3,0),(0,-1),(2,0))),
              fill=colors[2], width=2 if large else 1)
    draw.line(points(((-3,0),(0,-1),(2,0))), fill=colors[3], width=1)
    draw.line(points(((0,-1),(1,-1),(2,0))), fill=colors[4], width=1)
    if large:
        draw.polygon(points(((-3,-1),(-2,-4),(0,-3),(2,-1),
                             (1,2),(-1,4),(-2,1))), fill=colors[2])
        draw.line(points(((-1,1),(0,-2),(1,0))), fill=colors[3], width=2)
        draw.point(points(((0,-1),))[0], fill=colors[4])
        draw.point(points(((-tail+1,-2),))[0], fill=colors[0])
    # A hot head must survive the arena's normal ~0.65x browser display scale.
    # Keep an actual bright patch, not a single logical pixel lost in the tail.
    draw.polygon(points(((-1,-2),(2,-2),(4,0),(2,2),(-1,2))), fill=colors[3])
    draw.line(points(((0,-1),(2,-1),(3,0),(1,1))), fill=colors[4], width=2)
    return cel


def _spark_position(index, elapsed, secondary=False):
    """One continuous ballistic path through contact and aftermath (seconds)."""
    birth = .015 + (index % 4)*.018
    life = .61 + (index % 3)*.055
    age = elapsed-birth
    if not 0 <= age < life:
        return None
    p = age/life
    angle = -2.8 + index*2.399963
    origin, reach = (12., 48.) if secondary else (40., 87.)
    reach -= (index % 3)*4
    distance = origin + (reach-origin)*(1-(1-p)**1.6)
    return (math.cos(angle)*distance,
            math.sin(angle)*distance*.8 + 18*p*p - 10*p, p)


def _spark_shower(layer, point, elapsed, palette, scale, density, *, secondary=False):
    """Large bright heads, long streaks and several slower burning fragments."""
    colors = PALETTES[palette]
    draw = ImageDraw.Draw(layer)
    count = 12 if secondary else 18
    for index in range(round(count*density)):
        head = _spark_position(index, elapsed, secondary)
        if head is None:
            continue
        x, y, p = head
        # Trail is sampled from the very same trajectory, including across the
        # impact/aftermath boundary; no particles restart at that phase change.
        birth = .015 + (index % 4)*.018
        tail = _spark_position(index, max(birth, elapsed-.14), secondary)
        tx, ty = tail[:2]
        a = (point[0]+tx*scale, point[1]+ty*scale)
        b = (point[0]+x*scale, point[1]+y*scale)
        direction = round(math.atan2(y-ty, x-tx)*32/math.tau) % 32
        if p < .86:
            draw.line((a,b), fill=colors[1], width=max(2,round(4*scale)))
            midpoint = ((a[0]+b[0])*.5,(a[1]+b[1])*.5)
            draw.line((midpoint,b), fill=colors[3], width=max(2,round(2*scale)))
        large = index % 4 == 0
        # Independent sprite scale: shrinking the splash radius must not also
        # shrink its hot heads into invisible pinpoints, as the old code did.
        size = scale*(.88 if large else .65)*(.85 if secondary else 1.)
        size *= max(.38, min(1., (1-p)/.2))
        _put(layer, _finish(_spark(palette, index+round(elapsed*20), direction,
                                   large=large), size), b)


def _splash(layer, point, progress, palette, scale):
    """A compact licking contact flare, with three unequal bright flame heads."""
    for index, (ox, oy, size) in enumerate(((-5,3,.84),(4,1,1.0),(0,-4,1.15))):
        shift = math.sin(progress*4+index)*2
        center = (point[0] + (ox+shift)*scale,
                  point[1] + (oy-progress*5)*scale)
        _put(layer, _finish(_ember(palette, index+round(progress*8)),
                           scale*size*(1-progress*.28)), center)


def draw_fire_blast(layer, source, target, phase, progress, config, *, secondary=False):
    """Draw Charizard's Fire Blast using one authoritative action phase.

    ``layer`` is a Pillow RGBA image. ``source`` is the animated mouth emitter;
    ``target`` is the actual hit point. ``phase`` is windup, flight, impact or
    aftermath, and ``progress`` is normalized within that phase. Settings accept
    the shared palette, effect_scale and particle_density controls. A secondary
    hit draws a smaller contact flame and cinders, never another projectile.
    """
    if phase not in ('windup', 'flight', 'impact', 'aftermath'):
        return
    if secondary and phase in ('windup', 'flight'):
        return
    p = _bounded(progress, 0., 1., 0.)
    palette, scale, density = _settings(config)
    dx, dy = target[0] - source[0], target[1] - source[1]
    direction = round(math.atan2(dy, dx)*32/math.tau) % 32
    frame = min(8, round(p*8))
    elapsed = (p*CONTACT_DURATION if phase == 'impact' else
               CONTACT_DURATION + p*(FIRE_BLAST_LIFETIME-CONTACT_DURATION))
    if secondary:
        # Small irregular flame splash: the main 大 remains the visual owner.
        # A few rising cinders bridge contact to aftermath without another 大.
        if phase == 'impact':
            _splash(layer, target, p, palette, scale*1.4)
        elif p < 1.:
            if elapsed < .40:
                _put(layer, _finish(_ember(palette, frame, tiny=True),
                                   scale*.9),
                     (target[0], target[1] - p*12*scale))
        _spark_shower(layer,target,elapsed,palette,scale,density,secondary=True)
    elif phase == 'windup':
        # Embers draw inward to the mouth; no marks appear at the victim yet.
        radius = (29 - p*20)*scale
        for index in range(round(5*density)):
            angle = index*math.tau/5 + .35
            point = (source[0] + math.cos(angle)*radius,
                     source[1] + math.sin(angle)*radius*.55 - 4*scale)
            _put(layer, _finish(_ember(palette, frame + index, tiny=True),
                               scale*.45), point)
        _put(layer, _finish(_fireball(palette, frame, direction),
                           scale*(.24 + .32*p)), source)
    elif phase == 'flight':
        point = (source[0] + dx*p, source[1] + dy*p)
        distance = math.hypot(dx, dy) or 1.
        ux, uy = dx/distance, dy/distance
        # Only the last segment of travel burns. The route never resembles an
        # unbroken laser and the head cannot overshoot the authoritative target.
        for index in range(1, round(4*density) + 1):
            offset = min(distance*p, index*13*scale)
            flutter = ((index + frame) % 3 - 1)*3*scale
            tail = (point[0] - ux*offset - uy*flutter,
                    point[1] - uy*offset + ux*flutter)
            _put(layer, _finish(_ember(palette, frame + index),
                               scale*(.6 - index*.07)), tail)
        _put(layer, _finish(_fireball(palette, frame, direction), scale), point)
    elif phase == 'impact':
        # Expansion begins only when damage actually lands; a readable hold
        # starts after ~70ms of the existing 220ms contact stage.
        growth = min(1., p/.32)
        growth = .28 + .72*(1 - (1 - growth)**2)
        _spark_shower(layer,target,elapsed,palette,scale,density)
        # Fragments leave from behind the fire body so particle density cannot
        # replace its hot core or turn it back into scattered generic particles.
        _put(layer, _finish(_glyph(palette, frame, 0), scale*growth), target)
    elif p < 1.:
        # Briefly keep the three strokes, then let the pattern disintegrate into
        # rising cinders. The phase ends cleanly, including during replay seek.
        # Only the sparks linger longer. The large fire body still clears by
        # half a second, preserving the target's visibility during later hits.
        body_progress = (elapsed-CONTACT_DURATION)/.28
        dissolve = max(0, min(12, round((body_progress - .16)*18)))
        _spark_shower(layer,target,elapsed,palette,scale,density)
        if dissolve < 12:
            _put(layer, _finish(_glyph(palette, frame + 8, dissolve),
                               scale*(1 - body_progress*.12)),
                 (target[0], target[1] - body_progress*7*scale))
