"""Original-authored elemental motion adapted from Emerald's move scripts.

The source reference is choreography, not extracted game artwork. Streams,
individual needles, orbiting sparks and falling rocks have their own motion;
there are no move-name emblems. Real replay positions and impact own all hits.
"""
from functools import lru_cache
import math

from PIL import Image
import retro_primitives as rp
import retro_water

TYPES = {
    'spark_chain': 'ELECTRIC', 'shadow_siphon': 'GHOST',
    'psychic_blink': 'PSYCHIC', 'venom_armor': 'POISON',
    'flame_guard': 'FIRE', 'venom_tide': 'POISON', 'twin_cannon': 'WATER',
    'slow_field': 'PSYCHIC', 'storm_conductor': 'ELECTRIC',
    'toxic_spines': 'POISON', 'charged_beacon': 'ELECTRIC',
    'fracture_vision': 'PSYCHIC', 'cinder_eruption': 'FIRE',
    'dragon_crosscurrent': 'WATER', 'undertow_lock': 'WATER',
    'glacier_beam': 'ICE', 'storm_peck': 'ELECTRIC', 'sky_blaze': 'FIRE',
    'mind_shatter': 'PSYCHIC', 'ancient_mind': 'PSYCHIC',
    'phantom_hex': 'GHOST', 'spiteful_wail': 'GHOST',
    'frost_kiss': 'ICE', 'icicle_aegis': 'ICE',
}
SKILL_IDS = tuple(TYPES)
BODY_ONLY_FLIGHTS = frozenset(('psychic_blink', 'slow_field', 'fracture_vision'))
STREAM_CONTACT_END = .24


class _Brush:
    def __init__(self, draw, center):
        self.draw, self.cx, self.cy = draw, center[0], center[1]

    def points(self, path):
        return [(round(self.cx+x), round(self.cy+y)) for x, y in path]

    def line(self, path, color, width=1):
        self.draw.line(self.points(path), fill=color, width=width, joint='curve')

    def poly(self, path, color):
        self.draw.polygon(self.points(path), fill=color)

    def box(self, bounds, color):
        x1, y1, x2, y2 = bounds
        self.draw.rectangle((round(self.cx+x1), round(self.cy+y1),
                             round(self.cx+x2), round(self.cy+y2)), fill=color)

    def oval(self, bounds, color, *, outline=None, width=1):
        x1, y1, x2, y2 = bounds
        self.draw.ellipse((round(self.cx+x1), round(self.cy+y1),
                          round(self.cx+x2), round(self.cy+y2)),
                         fill=color, outline=outline, width=width)

    def arc(self, bounds, angles, color, width=1):
        x1, y1, x2, y2 = bounds
        self.draw.arc((round(self.cx+x1), round(self.cy+y1),
                       round(self.cx+x2), round(self.cy+y2)),
                      angles[0], angles[1], fill=color, width=width)


@lru_cache(maxsize=640)
def _tile(material, colors, frame=0):
    """Small independent sprite frames, all freshly authored on a five-ink grid."""
    image, draw, center = rp.cel(32)
    b = _Brush(draw, center)
    if material in ('water', 'drop'):
        if material == 'water':
            b.oval((-8, -5, 8, 5), colors[1])
            b.oval((-6, -4, 6, 3), colors[2])
            b.line(((-5, -2), (0, -3), (5, -1)), colors[3], 2)
            b.box((-3, -3, 0, -2), colors[4])
        else:
            b.poly(((0, -7), (-4, -1), (-4, 3), (-2, 5),
                    (2, 5), (4, 2), (3, -1)), colors[2])
            b.line(((-1, -2), (-2, 1), (-1, 3)), colors[4], 1)
    elif material == 'water_charge':
        radius = 4+frame % 3
        b.oval((-radius, -radius, radius, radius), colors[1], outline=colors[3])
        b.oval((-radius+2, -radius+1, radius-1, radius-2), colors[2])
        b.box((-2, -3, 0, -1), colors[4])
        for index in range(4):
            angle = index*math.pi/2+frame*.23
            x, y = math.cos(angle)*10, math.sin(angle)*9
            b.line(((x, y), (x*.8, y*.8)), colors[3], 1)
    elif material == 'bubble':
        radius = 5+frame % 2
        b.oval((-radius, -radius, radius, radius), colors[0], outline=colors[2])
        b.arc((-radius+1, -radius+1, radius-1, radius-1), (190, 290), colors[3], 2)
        b.box((-radius+2, -radius+1, -radius+3, -radius+2), colors[4])
    elif material == 'sludge':
        b.poly(((-10, 1), (-9, -4), (-5, -7), (0, -6), (4, -8),
                (8, -4), (10, 2), (6, 7), (0, 8), (-7, 5)), colors[0])
        b.oval((-8, -5, 7, 5), colors[1])
        b.oval((-5, -5, 4, 1), colors[2])
        b.arc((-6, -5, 3, 3), (195, 285), colors[3], 2)
        b.box((-3, -4, -2, -3), colors[4])
    elif material == 'needle':
        # Hard barb: broad faceted root, lit ridge, dark underside and one tip.
        # This is projectile material, not the move's name or an extra emitter.
        b.poly(((-13, -4), (-5, -4), (13, 0), (-5, 4), (-13, 3)), colors[0])
        b.poly(((-11, -3), (-4, -3), (12, 0), (-7, 1), (-11, 1)), colors[2])
        b.poly(((-10, 1), (-4, 0), (11, 0), (-5, 3), (-10, 2)), colors[1])
        b.line(((-10, -2), (-4, -2), (9, 0)), colors[3], 1)
        b.box((9, 0, 10, 0), colors[4])
    elif material in ('flame', 'breath'):
        bend = (frame % 3)-1
        b.poly(((-12, 2), (-7, -2), (-9, -7), (-1, -4), (4, -9),
                (5+bend, -4), (11, -2), (13, 2), (8, 7), (0, 8), (-6, 5)), colors[1])
        b.poly(((-6, 2), (-2, -3), (3, -5), (4, -1), (9, 1),
                (6, 5), (0, 5)), colors[2])
        b.line(((-1, 2), (3, -1), (7, 2)), colors[3], 3)
        b.box((3, 1, 5, 2), colors[4])
        if material == 'breath':
            b.line(((-14, 0), (-9, 0)), colors[2], 1)
    elif material == 'rock':
        # Warm rock has a physical irregular rim and molten cracks, no fire pillar.
        b.poly(((-9, -4), (-4, -9), (4, -8), (9, -3), (8, 5),
                (1, 9), (-6, 6), (-10, 1)), colors[0])
        b.poly(((-6, -4), (-3, -7), (3, -5), (4, 1), (0, 5), (-5, 3)), colors[1])
        b.line(((-6, -1), (-1, -3), (2, 1), (6, 2)), colors[2], 2)
        b.line(((-2, -6), (-1, -3), (-3, 1), (-2, 4)), colors[3], 1)
        b.box((-1, -2, 0, -1), colors[4])
    elif material == 'shadow':
        b.oval((-12, -11, 12, 11), colors[0])
        b.oval((-10, -10, 7, 7), colors[1])
        b.oval((-8, -9, 5, 3), colors[2])
        # The bright shoulder wraps round a dark sphere; its core stays shadow.
        b.arc((-10, -10, 9, 7), (195, 282), colors[3], 2)
        b.arc((-9, -8, 10, 9), (frame*30+15, frame*30+123), colors[2], 2)
        b.arc((-6, -6, 6, 6), (frame*30+200, frame*30+292), colors[0], 3)
        b.box((-5, -7, -3, -6), colors[4])
        b.line(((-14, 3), (-11, 5), (-7, 4)), colors[1], 2)
        b.line(((8, -7), (11, -9), (14, -7)), colors[2], 1)
    elif material == 'smoke':
        # Broken, rolling crescent wisps replace copies of the flying ball.
        bend = frame % 3 - 1
        b.poly(((-13, 3), (-11, -3), (-6, -6), (-3+bend, -10),
                (5, -8), (10, -4), (12, 3), (7, 7), (1, 6),
                (6, 3), (7, -1), (3, -4), (-2, -3), (-5, 1)), colors[0])
        b.poly(((-11, 1), (-8, -3), (-4, -4), (-2+bend, -8),
                (4, -6), (8, -3), (9, 2), (5, 5), (7, 1),
                (4, -3), (-2, -1), (-5, 3)), colors[1])
        b.line(((-7, -2), (-3, -3), (0, -6), (4, -5)), colors[2], 2)
        b.line(((-2, -5), (1, -6), (4, -4)), colors[3], 1)
    elif material == 'electric_orb':
        b.oval((-11, -11, 11, 11), colors[0])
        b.arc((-10, -10, 10, 10), (175, 325), colors[2], 2)
        b.arc((-8, -8, 8, 8), (frame*30, frame*30+128), colors[3], 2)
        b.arc((-6, -6, 7, 7), (frame*30+180, frame*30+255), colors[1], 2)
        b.oval((-4, -4, 4, 5), colors[0])
        b.box((-6, -6, -4, -4), colors[4])
    elif material == 'spark':
        shift = frame % 3-1
        b.line(((-7, -6), (-2, -3), (-4+shift, 1), (2, 0), (6, 5)), colors[1], 3)
        b.line(((-6, -6), (-2, -3), (-3+shift, 1), (2, 0), (6, 5)), colors[3], 1)
        b.box((-2, -3, -1, -2), colors[4])
        b.line(((2, 0), (5, -3), (6, -2)), colors[2], 1)
    elif material == 'chip':
        b.poly(((-4, -3), (1, -5), (5, -1), (2, 4), (-3, 2)), colors[1])
        b.line(((-2, -2), (1, -3), (3, -1)), colors[3], 1)
    elif material == 'psychic_weight':
        # A broad filled pressure front with a narrowing wake.  Unlike rings,
        # its volume reads as weight while it remains one moving surface.
        path = [(4-math.sin(j/24*math.pi)*10, -24+j*2) for j in range(25)]
        widths = [2.5+math.sin(j/24*math.pi)*10 for j in range(25)]
        _ribbon(b, path, [w+2.4 for w in widths], colors[0])
        _ribbon(b, path, widths, colors[1])
        _ribbon(b, path[3:21], [w*.58 for w in widths[3:21]], colors[2])
        _ribbon(b, path[8:17], [max(.9,w*.25) for w in widths[8:17]], colors[4])
        b.line((path[6],path[7],path[8]), colors[3], 1)
    elif material == 'glyph':
        # Ancient-power fragment: an angular tablet, not a move-name emblem.
        b.poly(((-5, -9), (3, -10), (8, -3), (6, 7), (-2, 10),
                (-8, 4), (-7, -5)), colors[0])
        b.poly(((-3, -7), (3, -7), (6, -2), (3, 5), (-4, 5),
                (-6, -1)), colors[1])
        b.poly(((0, -5), (4, -1), (0, 3), (-4, -1)), colors[2])
        b.line(((-3, -3), (1, -1), (-2, 3)), colors[3], 1)
        b.box((-1, -1, 1, 1), colors[4])
    return image


def _sprite(layer, material, at, colors, scale, frame=0, angle=None):
    if scale <= 0:
        return
    image = _tile(material, colors, int(frame) % 12)
    if angle is not None:
        image = image.rotate(angle, resample=Image.Resampling.NEAREST, expand=True)
    rp.put(layer, image, at, scale)


def _basis(source, target):
    dx, dy = target[0]-source[0], target[1]-source[1]
    length = math.hypot(dx, dy) or 1.
    return dx/length, dy/length, -dy/length, dx/length


def _offset(at, x, y, scale=1.):
    return at[0]+x*scale, at[1]+y*scale


def _heading(source, target):
    return -math.degrees(math.atan2(target[1]-source[1], target[0]-source[0]))


def _contact_time(phase, progress):
    # Both phases sample the same elapsed clock. Snapped cels stay identical on
    # either side of impact's final frame and on backwards seeks.
    seconds = .22*progress if phase == 'impact' else .22+.58*progress
    return round(seconds*50)/50


def _beam(layer, source, end, colors, scale, progress, lane, density=1.):
    """Filled pressure volume; keep the supplied nozzle and head as exact inputs."""
    retro_water.pressure_stream(layer, source, end, colors, scale=scale,
                                clock=progress, lane=lane, density=density)


def _lightning_route(layer, source, end, colors, scale, progress):
    """One actual chain connection. Never chooses or draws another recipient."""
    dx, dy = end[0]-source[0], end[1]-source[1]
    length = math.hypot(dx, dy) or 1.
    nx, ny = -dy/length, dx/length
    tick = round(progress*12)
    ux, uy = dx/length, dy/length
    points = []
    for index in range(13):
        jitter = (1 if (index+tick) % 2 else -1)*(5+(index*5+tick) % 4)*scale
        if index in (0, 12):
            jitter = 0
        points.append((source[0]+dx*index/12+nx*jitter,
                       source[1]+dy*index/12+ny*jitter))
    points[0], points[-1] = source, end
    # Side links used to shrink to a 3px thread. A width floor keeps every
    # real link a solid bolt; main chains still read heavier.
    body = max(scale, .7)
    # A dark outer envelope carries the hot white-yellow core.
    rp.line(layer, points, colors[0], 15*body)
    rp.line(layer, points, colors[1], 10*body)
    # A thinner counter-phase strand braids around the trunk.
    braid = [points[0]]+[(x-nx*(1 if (i+tick) % 2 else -1)*6*body,
                          y-ny*(1 if (i+tick) % 2 else -1)*6*body)
                         for i, (x, y) in enumerate(points[1:-1], 1)]+[points[-1]]
    rp.line(layer, braid, colors[2], 4*body)
    rp.line(layer, points, colors[3], 6*body)
    rp.line(layer, points, colors[4], 3*body)
    for joint, side in ((4, 1), (8, -1)):
        a = points[joint]
        branch = (a, _offset(a, nx*side*13*scale+ux*7*scale,
                             ny*side*13*scale+uy*7*scale),
                  _offset(a, nx*side*8*scale+ux*16*scale,
                          ny*side*8*scale+uy*16*scale))
        rp.line(layer, branch, colors[1], 5*scale)
        rp.line(layer, branch, colors[3], 2*scale)
    for index in (3, 8):
        _sprite(layer, 'spark', points[index], colors, scale*.19, tick+index)
    _sprite(layer, 'spark', end, colors, scale*.24, tick+5)


def _ribbon(brush, path, widths, color):
    if len(path) < 2:
        return
    left, right = [], []
    for i, point in enumerate(path):
        a, b = path[max(0, i-1)], path[min(len(path)-1, i+1)]
        ux, uy, nx, ny = _basis(a, b)
        radius = widths[i] if isinstance(widths, (tuple, list)) else widths
        left.append((point[0]+nx*radius, point[1]+ny*radius))
        right.append((point[0]-nx*radius, point[1]-ny*radius))
    brush.poly(left+list(reversed(right)), color)


def _pressure_wave(layer, at, colors, age, scale, variant):
    """Finite recipient-local psychic distortion, with no travelling object.

    Confusion is a flattened lens, Psychic pinches from opposite sides, and
    Future Sight shears two offset bands. Actual body/palette tasks remain in
    the shared renderer; the authored air surfaces are a board-local adaptation.
    """
    if not 0 <= age < .70:
        return
    q = age/.70
    image, draw, center = rp.cel(80)
    b = _Brush(draw, center)
    if variant == 'slow_field':
        for index in range(2):
            radius = 24+index*8+q*5
            path = []
            for j in range(31):
                angle = (-.85+j/30*1.7)*math.pi+(index*.72+q*.60)
                path.append((math.cos(angle)*radius,
                             math.sin(angle)*radius*.39+(index-.5)*8))
            widths = [4.1+math.sin(j/30*math.pi)*1.9 for j in range(31)]
            _ribbon(b, path, [w+1.5 for w in widths], colors[0])
            _ribbon(b, path, widths, colors[1])
            _ribbon(b, path[:25], 2.5, colors[2])
            _ribbon(b, path[3:16], 1.1, colors[3])
    elif variant == 'psychic_blink':
        # Psychic crush: three nested diamond fields close in on the actor
        # and spin a little as they tighten; a hot four-point flash marks
        # the instant the pressure lands.
        squeeze = min(1., age/.30)
        for index in range(3):
            radius = (24-index*7)*(1-.30*squeeze)+math.sin(age*18+index)*1.2
            turn = (index-1)*.10+q*.35*(1 if index % 2 else -1)
            path = []
            for j in range(33):
                corner = j/32*4
                side, f = int(corner) % 4, corner-int(corner)
                a = side*math.pi/2+turn
                a2 = a+math.pi/2
                x = math.cos(a)*(1-f)+math.cos(a2)*f
                y = math.sin(a)*(1-f)+math.sin(a2)*f
                path.append((x*radius, y*radius*.82))
            # Thin fields with open gaps keep the crushed actor readable.
            width = 1.4-index*.2
            _ribbon(b, path, width+.8, colors[0])
            _ribbon(b, path, width, colors[2 if index == 0 else 1])
            _ribbon(b, path[2:13], max(.9, width*.45), colors[4 if index == 0 else 3])
        if age < .16:
            flash = (1-age/.16)
            r = 15*flash+4
            star = [((r if j % 2 == 0 else r*.24)*math.cos(j*math.pi/4),
                     (r if j % 2 == 0 else r*.24)*math.sin(j*math.pi/4)) for j in range(8)]
            b.poly(star, colors[3])
            b.poly([(x*.5, y*.5) for x, y in star], colors[4])
    elif variant == 'fracture_vision':
        # Future Sight is two offset slices. Their straight sheared bodies
        # deliberately differ from Confusion's lens and Psychic's weight.
        for index in range(2):
            sign = -1 if index else 1
            path = []
            for j in range(25):
                qj = j/24
                path.append((-27+qj*54+sign*(7-q*4),
                             -17+qj*34+sign*(9-q*5)*math.sin(qj*math.pi)))
            widths = [7.4*math.sin(j/24*math.pi)+1 for j in range(25)]
            _ribbon(b, path, [w+1.8 for w in widths], colors[0])
            _ribbon(b, path, widths, colors[1])
            _ribbon(b, path[3:21], [w*.60 for w in widths[3:21]], colors[2])
            _ribbon(b, path[7:17], [max(.9,w*.24) for w in widths[7:17]], colors[4])
    else:
        return
    # The old bands stayed large up to .70s and blinked out. Break their
    # contours and steadily shrink the hard-edged residue on this same clock.
    if age > .52:
        seam = 1+round((age-.52)/.18*3)
        for y in (center[1]-10,center[1]+9):
            draw.rectangle((0,y-seam,image.width,y+seam),fill=(0,0,0,0))
    collapse = max(0.,1-max(0.,age-.40)/.30)**1.25
    rp.put(layer,image,at,scale*(.66-.24*q)*collapse)

def _electric_contact(layer, at, colors, age, scale, density, thunder=False):
    """Spark Chain's short bent lash arcs vs. Thunder's heavy delayed column."""
    delays = (0., .055, .125) if not thunder else (0., .11, .25, .36)
    for index, delay in enumerate(delays):
        local = age-delay
        life = .15 if not thunder else .17
        if not 0 <= local < life:
            continue
        tick = round(local*45)
        if thunder:
            lateral = (-14, 13, 0, -7)[index]*scale
            height = 82*scale
            start = _offset(at, lateral, -height)
            end = _offset(at, lateral*.15, 3*scale)
            path = []
            for j in range(8):
                q = j/7
                zig = (11 if (j+index+tick) % 2 else -9)*scale if j not in (0, 7) else 0
                path.append((start[0]+(end[0]-start[0])*q+zig,
                             start[1]+(end[1]-start[1])*q))
            # A short heavy dark envelope carries a narrow hot edge; the main
            # discharge has physical width without a huge white target silhouette.
            rp.line(layer, path, colors[0], 19*scale)
            rp.line(layer, path, colors[1], 14*scale)
            rp.line(layer, path, colors[3], 8*scale)
            rp.line(layer, path, colors[4], 3*scale)
            for joint, side in ((2, -1), (5, 1)):
                a = path[joint]
                branch = (a, _offset(a, side*15*scale, 6*scale),
                          _offset(a, side*11*scale, 16*scale))
                rp.line(layer, branch, colors[1], 6*scale)
                rp.line(layer, branch, colors[3], 3*scale)
        else:
            # The chain lands as a short solid arc that whips around the body:
            # a bowed dark envelope with a lit mid band and a hot core, kept low
            # and quick so it never reads as Thunder's tall sky column.
            side = (-1, 1, -1)[index]
            start = _offset(at, side*23*scale, -24*scale)
            bend = _offset(at, side*31*scale, -1*scale)
            end = _offset(at, -side*5*scale, 15*scale)
            path = []
            for j in range(7):
                q = j/6
                bx = (1-q)*(1-q)*start[0]+2*(1-q)*q*bend[0]+q*q*end[0]
                by = (1-q)*(1-q)*start[1]+2*(1-q)*q*bend[1]+q*q*end[1]
                snap = ((1 if (j+index+tick) % 2 else -1)*(4 if j % 2 else 3)*scale
                        if j not in (0, 6) else 0)
                path.append((bx-snap*side, by+snap*.4))
            rp.line(layer, path, colors[0], 13*scale)
            rp.line(layer, path, colors[1], 8*scale)
            rp.line(layer, path, colors[2], 5*scale)
            rp.line(layer, path, colors[4], 3*scale)
            if index == 0 and local < .10:
                # The first touch flashes as an eight-point starburst that
                # collapses in place; the bright core makes the hit land.
                image, draw, center = rp.cel(32)
                b = _Brush(draw, center)
                q = local/.10
                radius = 13-q*6
                # Flattened sideways: Spark Chain stays a low, wide family.
                star = [((radius if j % 2 == 0 else radius*.38)*math.cos(j*math.pi/8)*1.15,
                         (radius if j % 2 == 0 else radius*.38)*math.sin(j*math.pi/8)*.6)
                        for j in range(16)]
                b.poly(star, colors[1])
                b.poly([(x*.68, y*.68) for x, y in star], colors[3])
                b.poly([(x*.34, y*.34) for x, y in star], colors[4])
                rp.put(layer, image, _offset(at, 0, 2*scale), scale*(1.-q*.35))
    # Each family owns a different terminal face.  The low chain stamp and
    # Thunder's ground plate never share the old generic crescent template.
    if thunder:
        _thunder_ground_face(layer, at, colors, age, scale)
    else:
        _chain_contact_face(layer, at, colors, age, scale*.82)
    # Residue moves around the actor's contour and rises; not a spoke fan.
    for index in range(max(4, round(6*density))):
        born = .10+(index % 3)*.05
        local = age-born
        if not 0 <= local < .42:
            continue
        angle = index*2.4+local*2.5
        radius = (28+local*22)*scale
        pos = _offset(at, math.cos(angle)*radius,
                      math.sin(angle)*radius*.66-local*24*scale)
        _sprite(layer, 'spark', pos, colors, scale*(.22-local*.23),
                index+round(age*45), index*43)


def _chain_contact_face(layer, at, colors, age, scale):
    """Spark Chain's low triangular stamp, independent from Thunder's plate."""
    if not 0 <= age < .12:
        return
    image, draw, center = rp.cel(56)
    b = _Brush(draw, center)
    q = age/.12
    spread = 17+q*10
    path = [(-spread+abs(j-9)*1.2, -6+q*4+j*.65) for j in range(19)]
    widths = [5.2*(1-q*.62)*math.sin(j/18*math.pi)+.7 for j in range(19)]
    _ribbon(b, path, [w+1.5 for w in widths], colors[0])
    _ribbon(b, path, widths, colors[1])
    _ribbon(b, path[4:15], [w*.55 for w in widths[4:15]], colors[3])
    b.line((path[6],path[9],path[12]), colors[4], 1)
    rp.put(layer, image, _offset(at,0,7*scale), scale*.78)


def _thunder_ground_face(layer, at, colors, age, scale):
    """Thunder terminates in a wide grounded plate and crown, not a circle."""
    if not 0 <= age < .16:
        return
    image, draw, center = rp.cel(72)
    b = _Brush(draw, center)
    q = age/.16
    width = 30+q*13
    path = [(-width+j*2.7, 8+math.sin(j/20*math.pi)*5-q*4)
            for j in range(23)]
    widths = [7.5*(1-q*.58)*math.sin(j/22*math.pi)+1 for j in range(23)]
    _ribbon(b, path, [w+2 for w in widths], colors[0])
    _ribbon(b, path, widths, colors[1])
    _ribbon(b, path[3:19], [w*.62 for w in widths[3:19]], colors[2])
    for index in range(5):
        x = (-24+index*12)*(.72+q*.28)
        b.line(((x,5-q*3),(x+(index-2)*2,15+q*7)),colors[3],2)
    rp.put(layer, image, _offset(at,0,13*scale), scale*.80)


def _charged_contact(layer, source, at, colors, age, scale, density):
    """Zap Cannon keeps its dark sphere and tears it into orbital discharges.

    It never borrows Thunder's vertical arrival or invents a second projectile.
    """
    if age < .17:
        image, draw, center = rp.cel(64)
        b = _Brush(draw,center)
        q = age/.17
        rx, ry = 13+q*13, 17-q*7
        b.oval((-rx,-ry,rx,ry),colors[0])
        b.arc((-rx+1,-ry+1,rx-1,ry-1),(172,317),colors[2],3)
        b.arc((-rx+2,-ry+2,rx-2,ry-2),(22,131),colors[1],3)
        b.arc((-rx+5,-ry+3,rx-5,ry-3),(age*650,age*650+112),colors[3],2)
        b.box((-rx*.40,-ry*.60,-rx*.22,-ry*.43),colors[4])
        rp.put(layer,image,at,scale*.65)
    for index in range(max(4,round(6*density))):
        local=age-(index % 3)*.04
        if not 0 <= local < .52:
            continue
        angle=index*math.tau/6+local*4.6
        radius=(24+local*42)*scale
        center=_offset(at,math.cos(angle)*radius,math.sin(angle)*radius*.78)
        tangent=(-math.sin(angle),math.cos(angle))
        path=[]
        for j in range(5):
            offset=(j-2)*(4.5-local*4)*scale
            cross=(4 if j%2 else -3)*scale
            path.append(_offset(center,tangent[0]*offset+math.cos(angle)*cross,
                                 tangent[1]*offset+math.sin(angle)*cross))
        rp.line(layer,path,colors[0],8*scale*(1-local))
        rp.line(layer,path,colors[2],5*scale*(1-local))
        rp.line(layer,path,colors[4],3*scale)

def _poison_contact(layer, at, colors, age, scale, density, *, sludge=False):
    """A sticky sheet opens into heavy droplets, then separate rising bubbles."""
    duration = .30 if sludge else .18
    if age < duration:
        image, draw, center = rp.cel(64)
        b = _Brush(draw, center)
        q = age/duration
        radius=(12+q*(18 if sludge else 11))
        # Irregular lobes surround a clear center; a low lit wet face has depth.
        path=[]
        for j in range(37):
            angle=j/36*math.tau
            r=radius*(1+.13*math.sin(angle*5+age*13))
            path.append((math.cos(angle)*r,math.sin(angle)*r*.53))
        _ribbon(b,path,[(5.4 if sludge else 4.6)*(1-q*.40) for _ in path],colors[0])
        _ribbon(b,path[1:35],(3.8 if sludge else 3.0)*(1-q*.35),colors[1])
        _ribbon(b,path[3:22],2.2,colors[2])
        _ribbon(b,path[5:13],1.0,colors[3])
        for sign in (-1,1):
            x=sign*(radius-4)
            b.poly(((x-3,1),(x-4,7+q*6),(x,12+q*6),(x+3,8),(x+2,1)),colors[1])
            b.line(((x-1,2),(x,7+q*4)),colors[3],1)
        rp.put(layer,image,_offset(at,0,9*scale),scale*.70)
    for index in range(max(4,round((7 if sludge else 4)*density))):
        if sludge:
            local=age-.05-(index%3)*.025
            if 0<=local<.40:
                sign=-1 if index%2 else 1
                x=sign*(15+local*(53+index%3*12))*scale
                y=(-10-local*43+local*local*147)*scale
                _sprite(layer,'sludge',_offset(at,x,y),colors,
                        scale*(.34-local*.40),index,sign*local*70)
        born=.10+(index%4)*.055
        local=age-born
        if 0<=local<.36:
            x=((index*17)%43-21+math.sin(local*11+index)*4)*scale
            y=(8-local*95+(index%2)*7)*scale
            _sprite(layer,'bubble',_offset(at,x,y),colors,
                    scale*(.26+.07*math.sin(local*8)),index+round(age*35))

def _water_contact(layer, source, at, colors, age, scale, density, *, narrow=False):
    retro_water.curling_splash(layer, source, at, colors, age,
                              scale=scale, density=density, narrow=narrow)


def _fire_spread(layer, at, colors, age, scale, density):
    # Flame Wheel's pressure opens into a broad asymmetric curled hot rim.
    if age < .24:
        _flame_roll(layer,at,colors,age*6,scale*(.87-age*.65),.6+age*2)
    for index in range(max(4,round(6*density))):
        born=.08+(index%3)*.035
        local=age-born
        if not 0<=local<.47:
            continue
        sign=-1 if index%2 else 1
        x=sign*(10+local*(35+index%3*15))*scale
        y=(-2-local*(42+index%3*13)+local*local*50)*scale
        size=scale*(.28-local*.34)
        _sprite(layer,'flame',_offset(at,x,y),colors,size,
                round(age*42)+index,sign*(15+local*55))
        # A lit falling head detaches from each tongue during the final tail.
        if local > .25:
            _sprite(layer,'chip',_offset(at,x,y+7*scale),colors,
                    scale*(.13-local*.16),index)


def _flame_roll(layer, at, colors, clock, scale, openness=1.):
    """Rotating filled fire tongues with a dark outer curl and bright root.

    An incomplete sheet leaves the actor visible. Its curled outline breaks
    differently on every sampled clock; it cannot become a ring icon.
    """
    image,draw,center=rp.cel(80)
    b=_Brush(draw,center)
    for index in range(3):
        base=clock*1.6+index*math.tau/3
        path=[];widths=[]
        for j in range(27):
            q=j/26
            angle=base+q*1.45
            r=19+math.sin(q*math.pi)*(4+openness*4)-q*6
            path.append((math.cos(angle)*r,math.sin(angle)*r*.88-q*4))
            widths.append((1-q)**.6*(5.8+openness*1.8)+.5)
        _ribbon(b,path,[w+1.1 for w in widths],colors[0])
        _ribbon(b,path,widths,colors[1])
        _ribbon(b,path[:23],[w*.61 for w in widths[:23]],colors[2])
        _ribbon(b,path[1:17],[max(.7,w*.27) for w in widths[1:17]],colors[3])
        b.line((path[3],path[5],path[7]),colors[4],1)
    rp.put(layer,image,at,scale*.67)

def _eruption_contact(layer, at, colors, age, scale, density):
    # The first rock lands at the authoritative impact. The other delayed
    # falling fragments are cosmetic within this same recipient's local area.
    for index in range(max(3, round(6*density))):
        born = index*.043
        local = age-born
        if not -.14 <= local < .42:
            continue
        x = (0 if index == 0 else ((index*19) % 61-30))*scale
        landing = _offset(at, x, (index % 3-1)*7*scale)
        if local < 0:
            _sprite(layer, 'rock', _offset(landing, 0, local*360*scale), colors,
                    scale*(.36+index % 2*.07), index)
        else:
            if local < .16:
                bounce = -math.sin(local*math.pi/.16)*8*scale
                _sprite(layer, 'rock', _offset(landing, 0, bounce), colors,
                        scale*((.60 if index==0 else .38)-local*.85),index)
            for chip in range(3):
                angle = chip*math.tau/3+index*.9
                distance = (4+local*83)*scale
                pos = _offset(landing, math.cos(angle)*distance,
                              math.sin(angle)*distance*.5+local*local*48*scale)
                _sprite(layer, 'chip', pos, colors, scale*(.27-local*.36), chip)
            if local < .24:
                _sprite(layer,'flame',_offset(landing,0,-local*30*scale),
                        colors,scale*(.46-local*.72),round(local*40))


def _whirlpool_contact(layer, at, colors, age, scale, density):
    retro_water.whirlpool(layer, at, colors, age, scale=scale, density=density)


def _zap_orb(layer, at, colors, scale, progress):
    _sprite(layer,'electric_orb',at,colors,scale*.59,round(progress*24))
    # Paired tangential arcs follow the sphere's surface instead of a star icon.
    for index in range(4):
        angle=index*math.pi/2+progress*6
        points=[]
        for j in range(6):
            a=angle+j*.11
            radius=(22+(3 if j%2 else -2))*scale
            points.append(_offset(at,math.cos(a)*radius,math.sin(a)*radius*.89))
        rp.line(layer,points,colors[1],6*scale)
        rp.line(layer,points,colors[3],3*scale)

def _windup(layer, key, source, target, colors, scale, density, p, emitters):
    step = round(p*16)
    if key == 'twin_cannon':
        # Only these two puts are the pressure charge; no invented shoulder sites.
        for emitter in tuple(emitters)[:2] or (source,):
            _sprite(layer, 'water_charge', emitter, colors, scale*(.30+.13*p), step)
    elif key in BODY_ONLY_FLIGHTS:
        _pressure_wave(layer, source, colors, p*.52, scale*.58, key)
    elif key == 'flame_guard':
        _flame_roll(layer,source,colors,p*3.1,
                    scale*(.52+.24*p),.35+.50*p)
    elif key == 'cinder_eruption':
        for index in range(max(3, round(6*density))):
            local = p-(index//3)*.23
            if not 0 <= local <= .76:
                continue
            angle = (index % 3-1)*.55
            x = math.sin(angle)*local*58*scale
            y = (-math.sin(min(1., local/.76)*math.pi)*44-7)*scale
            _sprite(layer, 'rock', _offset(source, x, y), colors,
                    scale*(.42 if index==1 else .27+index%2*.05),index)
    elif key == 'venom_armor':
        image, draw, center = rp.cel(48)
        b = _Brush(draw, center)
        for index in range(3):
            y=-10+index*8+p*3
            width=14+math.sin(p*8+index)*3
            path=[(math.cos(j/18*math.pi)*width,
                   y+math.sin(j/18*math.pi)*(4+index)) for j in range(19)]
            _ribbon(b,path,4.6,colors[0])
            _ribbon(b,path,3.4,colors[1])
            _ribbon(b,path[2:14],2.0,colors[2])
            _ribbon(b,path[4:10],.9,colors[3])
        rp.put(layer,image,source,scale*.65)
    elif key == 'venom_tide':
        _sprite(layer,'sludge',_offset(source,0,-6*scale),colors,
                scale*(.30+.18*p),step)
        for index in (-1,1):
            _sprite(layer,'bubble',_offset(source,index*(20-p*6)*scale,
                                           (-2-p*8)*scale),colors,
                    scale*(.20+.06*p),step+index)
    elif key == 'toxic_spines':
        for index in range(3):
            _sprite(layer, 'needle', _offset(source, 0, (index-1)*7*scale),
                    colors, scale*(.23+.08*p), index, _heading(source, target))
    elif key == 'charged_beacon':
        _zap_orb(layer, source, colors, scale*(.45+.40*p), p)
    elif key == 'shadow_siphon':
        _sprite(layer, 'shadow', source, colors, scale*(.22+.25*p), step)
        for index in range(3):
            a = index*math.tau/3+p*5
            radius = (25-p*13)*scale
            _sprite(layer, 'shadow', _offset(source, math.cos(a)*radius,
                                           math.sin(a)*radius*.7), colors,
                    scale*.08, step+index)
    elif key == 'spark_chain':
        # Four short arcs orbit and tighten into a growing hot core on the
        # caster: the charge reads as one gathering cage, not loose scribbles.
        tick = round(p*16)
        radius = (30-p*12)*scale
        for index in range(4):
            angle = index*math.pi/2+p*2.6+(tick % 2)*.12
            a = _offset(source, math.cos(angle)*radius, math.sin(angle)*radius*.8-6*scale)
            mid = _offset(source, math.cos(angle+.42)*(radius+7*scale),
                          math.sin(angle+.42)*(radius+7*scale)*.8-6*scale)
            b = _offset(source, math.cos(angle+.84)*radius, math.sin(angle+.84)*radius*.8-6*scale)
            rp.line(layer, (a, mid, b), colors[0], 9*scale)
            rp.line(layer, (a, mid, b), colors[2], 5*scale)
            rp.line(layer, (a, mid, b), colors[4], 2*scale)
        image, draw, center = rp.cel(24)
        core = _Brush(draw, center)
        r = 3+p*6
        spikes = [((r if j % 2 == 0 else r*.45)*math.cos(j*math.pi/4+p*3),
                   (r if j % 2 == 0 else r*.45)*math.sin(j*math.pi/4+p*3)) for j in range(8)]
        core.poly(spikes, colors[3])
        core.poly([(x*.5, y*.5) for x, y in spikes], colors[4])
        rp.put(layer, image, _offset(source, 0, -6*scale), scale*.9)
    elif key == 'storm_conductor':
        # Thunder's charge is a vertical conductor: five leaders descend into
        # one low coil, separate from Spark Chain's horizontal chain links.
        for index in range(5):
            x = (index-2)*(9-p*4)*scale
            top = _offset(source, x+math.sin(index+p*4)*4*scale,
                          (-38+p*15)*scale)
            bottom = _offset(source, x*.35, (-8+p*5)*scale)
            path = (top, _offset(source, x*.65+((index%2)*2-1)*5*scale,
                                 (-24+p*10)*scale), bottom)
            rp.line(layer, path, colors[0], 6*scale)
            rp.line(layer, path, colors[1], 3*scale)
        image, draw, center = rp.cel(40)
        b = _Brush(draw, center)
        radius = 8+p*5
        b.oval((-radius, -radius*.42, radius, radius*.42), colors[1],
               outline=colors[3], width=2)
        rp.put(layer, image, _offset(source,0,-4*scale), scale*.75)
    elif key == 'dragon_crosscurrent':
        for index in (-1, 1):
            _sprite(layer, 'water', _offset(source, index*11*scale,
                                          math.sin(p*8+index)*7*scale),
                    colors, scale*(.16+.10*p), step)
    elif key == 'undertow_lock':
        _whirlpool_contact(layer, source, colors, p*.43, scale*.48, density)
    elif key == 'glacier_beam':
        # Aurora gathering: frost shards converge on the caster's focus point.
        for index in range(6):
            a = index*math.tau/6+p*2.4
            radius = (26-15*p)*scale
            _sprite(layer, 'chip', _offset(source, math.cos(a)*radius,
                                           math.sin(a)*radius*.72), colors,
                    scale*(.30+.10*p), step+index, math.degrees(a))
        image, draw, center = rp.cel(32)
        b = _Brush(draw, center)
        core = 3+p*6
        b.oval((-core, -core, core, core), colors[2], outline=colors[3])
        rp.put(layer, image, source, scale*.8)
    elif key == 'storm_peck':
        # The drill beak forms first; gathered sparks orbit it asymmetrically.
        _sprite(layer, 'needle', _offset(source, 0, -4*scale), colors,
                scale*(.24+.22*p), step, _heading(source, target))
        for index in range(3):
            a = index*math.tau/3+p*3.2
            _sprite(layer, 'spark', _offset(source, math.cos(a)*(19-8*p)*scale,
                                            math.sin(a)*(15-6*p)*scale-4*scale),
                    colors, scale*(.16+.07*p), step+index)
    elif key == 'sky_blaze':
        # Sky Attack's rising charge: a slow flame helix climbs off the caster.
        for index in range(3):
            local = p-index*.18
            if not 0 <= local <= 1.:
                continue
            a = local*math.tau*.8+index*2.1
            _sprite(layer, 'flame', _offset(source, math.cos(a)*9*scale,
                                            (-local*34-4)*scale), colors,
                    scale*(.22+.16*local), step+index)
    elif key == 'mind_shatter':
        # Four pressure arcs contract toward the caster's core.
        image, draw, center = rp.cel(64)
        b = _Brush(draw, center)
        radius = (26-14*p)
        for index in range(4):
            start = index*90+round(p*40)
            b.arc((-radius, -radius*.8, radius, radius*.8),
                  (start, start+52), colors[1+index % 3], max(1, round(4-p*2)))
        b.oval((-4-p*3, -4-p*3, 4+p*3, 4+p*3), colors[2], outline=colors[3])
        rp.put(layer, image, source, scale)
    elif key == 'ancient_mind':
        # Ancient glyph tablets lift off the ground in a slow spiral.
        for index in range(5):
            local = p-index*.13
            if not 0 <= local <= 1.:
                continue
            a = local*math.tau*.6+index*1.26
            _sprite(layer, 'glyph', _offset(source, math.cos(a)*14*scale,
                                            6*scale-local*30*scale), colors,
                    scale*(.28-.06*local), step+index, math.degrees(a))
    elif key == 'phantom_hex':
        # Shadow wisps spiral inward against the flight's drift; the orb gathers.
        for index in range(4):
            a = -index*math.tau/4-p*4.6
            radius = (27-16*p)*scale
            _sprite(layer, 'smoke', _offset(source, math.cos(a)*radius,
                                            math.sin(a)*radius*.62), colors,
                    scale*(.24+.10*p), step+index, math.degrees(a))
        _sprite(layer, 'shadow', source, colors, scale*(.20+.22*p), step)
    elif key == 'spiteful_wail':
        # A smoke ring tightens around the caster before the wail is released.
        image, draw, center = rp.cel(64)
        b = _Brush(draw, center)
        radius = 24-11*p
        for index in range(3):
            start = index*120+round(p*50)
            b.arc((-radius, -radius*.62, radius, radius*.62),
                  (start, start+74), colors[1+index % 3], max(1, round(3-p)))
        rp.put(layer, image, _offset(source, 0, -4*scale), scale)
        _sprite(layer, 'smoke', _offset(source, 0, -6*scale), colors,
                scale*(.22+.12*p), step)
    elif key == 'frost_kiss':
        # Two frost chips orbit a small bright core: a kiss of ice, not a beam.
        for index in range(2):
            a = index*math.pi+p*5.2
            _sprite(layer, 'chip', _offset(source, math.cos(a)*14*scale,
                                           math.sin(a)*9*scale-4*scale),
                    colors, scale*(.30+.10*p), step+index, math.degrees(a))
        image, draw, center = rp.cel(24)
        b = _Brush(draw, center)
        core = 2+p*4
        b.oval((-core, -core, core, core), colors[2], outline=colors[3])
        rp.put(layer, image, _offset(source, 0, -4*scale), scale*.8)
    elif key == 'icicle_aegis':
        # Six shards close into a defensive shell around the caster.
        for index in range(6):
            a = index*math.tau/6+.4
            radius = (30-19*p)*scale
            _sprite(layer, 'chip', _offset(source, math.cos(a)*radius,
                                           math.sin(a)*radius*.78), colors,
                    scale*(.30+.08*p), step+index, math.degrees(a))
        if p > .45:
            image, draw, center = rp.cel(48)
            b = _Brush(draw, center)
            q = (p-.45)/.55
            b.arc((-16, -20, 16, 14), (200, 340), colors[1], max(1, round(2+q*2)))
            b.arc((-13, -16, 13, 11), (210, 330), colors[3], 1)
            rp.put(layer, image, source, scale*(.5+.3*q))


def _flight(layer, key, source, target, colors, scale, density, p, emitters):
    if key in BODY_ONLY_FLIGHTS:
        return  # Original Teleport/Confusion/Future Sight have no projectile sprite.
    if key == 'twin_cannon':
        for lane, emitter in enumerate(tuple(emitters)[:2] or (source,)):
            _beam(layer, emitter, rp.point(emitter, target, p), colors, scale, p, lane, density)
        return
    at = rp.point(source, target, p)
    heading = _heading(source, target)
    if key == 'spark_chain':
        _lightning_route(layer, source, at, colors, scale*.92, p)
    elif key == 'shadow_siphon':
        # AnimShadowBall advances, pauses briefly, then accelerates to target.
        travel = (p/.38*.46 if p < .38 else .46 if p < .62
                  else .46+(p-.62)/.38*.54)
        for index in (3, 2, 1):
            q = max(0., travel-index*.035)
            _sprite(layer, 'shadow', rp.point(source, target, q), colors,
                    scale*(.09+index*.015), round(p*20)+index)
        _sprite(layer, 'shadow', rp.point(source, target, travel), colors,
                scale*.61, round(p*20))
    elif key == 'venom_armor':
        _sprite(layer, 'needle', at, colors, scale*.43, 0, heading)
    elif key == 'flame_guard':
        _flame_roll(layer,at,colors,p*5.6,scale,.70)
        for index in range(2):
            q=max(0.,p-.09-index*.055)
            center=rp.point(source,target,q)
            _sprite(layer,'flame',center,colors,scale*(.19-index*.035),
                    round(p*30)+index,heading)
    elif key == 'venom_tide':
        for index in range(max(3, round(6*density))):
            q = max(0., p-index*.060)
            center = rp.point(source, target, q)
            arc = -math.sin(q*math.pi)*(24+index % 3*6)*scale
            _sprite(layer, 'sludge', _offset(center, 0, arc), colors,
                    scale*(.42-index*.024), index)
    elif key == 'storm_conductor':
        # Thunder originates above the actual target. The descending leader is
        # still above the victim until the authoritative impact phase starts.
        top = _offset(target, 0, -91*scale)
        end = _offset(target, 0, -(15+(1-p)*72)*scale)
        path = [top]
        for index in range(1, 6):
            q = index/6
            path.append((top[0]+(6 if index % 2 else -7)*scale,
                         top[1]+(end[1]-top[1])*q))
        path.append(end)
        rp.line(layer, path, colors[1], 9*scale)
        rp.line(layer, path, colors[3], 3*scale)
    elif key == 'toxic_spines':
        for index in range(3):
            q = max(0., p-index*.07)
            center = rp.point(source, target, q)
            center = _offset(center, 0, -math.sin(q*math.pi)*(26+index*7)*scale)
            _sprite(layer,'needle',center,colors,scale*(.44-index*.04),index,
                    heading+math.cos(q*math.pi)*18)
    elif key == 'charged_beacon':
        _zap_orb(layer, at, colors, scale, p)
    elif key == 'cinder_eruption':
        for index in range(max(3, round(6*density))):
            q = max(0., p-index*.045)
            center = rp.point(source, target, q)
            center = _offset(center, (index % 3-1)*math.sin(q*math.pi)*20*scale,
                             -math.sin(q*math.pi)*(64+index % 3*9)*scale)
            _sprite(layer,'rock',center,colors,
                    scale*(.58 if index==0 else .34+index%2*.06),index)
    elif key == 'dragon_crosscurrent':
        _beam(layer, source, at, colors, scale*.82, p, 0, density)
    elif key == 'undertow_lock':
        retro_water.surf_front(layer, source, target, colors, p, scale=scale,
                               density=density)
    elif key == 'glacier_beam':
        # A narrow ice lance leads; staggered shards trail the exact route.
        _sprite(layer, 'needle', at, colors, scale*.50, round(p*18),
                heading)
        rp.line(layer, (source, at), colors[2], 4*scale)
        rp.line(layer, (source, at), colors[3], 2*scale)
        for index in range(4):
            q = max(0., p-(index+1)*.075)
            center = rp.point(source, target, q)
            _sprite(layer, 'chip', _offset(center, (index % 2*2-1)*5*scale,
                                           -math.sin(q*math.pi)*9*scale),
                    colors, scale*(.30-index*.03), round(p*20)+index)
    elif key == 'storm_peck':
        # Drill Peck wrapped in Thunder's arcs: two flanking sparks, one beak.
        _sprite(layer, 'needle', at, colors, scale*.55, round(p*24), heading)
        for index in (-1, 1):
            q = max(0., p-.10)
            center = rp.point(source, target, q)
            ux, uy, nx, ny = _basis(source, target)
            _sprite(layer, 'spark', (center[0]+nx*index*9*scale,
                                     center[1]+ny*index*9*scale),
                    colors, scale*.24, round(p*22)+index)
    elif key == 'sky_blaze':
        # A blazing head with two wing flames swept off the flight axis.
        _sprite(layer, 'flame', at, colors, scale*(.58+.10*p), round(p*26),
                heading)
        ux, uy, nx, ny = _basis(source, target)
        for index in (-1, 1):
            q = max(0., p-.08)
            center = rp.point(source, target, q)
            wing = (center[0]+nx*index*13*scale, center[1]+ny*index*13*scale)
            _sprite(layer, 'flame', wing, colors, scale*.26,
                    round(p*26)+index, heading+index*18)
    elif key == 'mind_shatter':
        # Psychic's heavy pressure advances as one filled crescent volume;
        # there are no same-colour concentric rings borrowed from a field.
        _sprite(layer, 'psychic_weight', at, colors, scale*(.62+.22*p),
                round(p*18), heading)
    elif key == 'ancient_mind':
        # A large faceted glyph leads two smaller tumbling glyphs along the
        # exact route; no generic psychic halo or thin ring is added.
        _sprite(layer, 'glyph', at, colors, scale*.54, round(p*16), heading)
        for index in range(2):
            q = max(0., p-(index+1)*.10)
            center = rp.point(source, target, q)
            side = -1 if index else 1
            _sprite(layer, 'glyph', _offset(center, side*8*scale,
                                            -math.sin(q*math.pi)*8*scale),
                    colors, scale*(.31-index*.04), round(p*18)+index,
                    heading+side*22)
    elif key == 'phantom_hex':
        # The hex orb flies straight; smoke wisps trail on a reverse spiral.
        _sprite(layer, 'shadow', at, colors, scale*(.52+.06*p), round(p*22))
        for index in range(3):
            q = max(0., p-(index+1)*.07)
            center = rp.point(source, target, q)
            a = -q*7+index*2.1
            _sprite(layer, 'smoke', _offset(center, math.cos(a)*9*scale,
                                            math.sin(a)*6*scale), colors,
                    scale*(.20-index*.03), round(p*20)+index)
    elif key == 'spiteful_wail':
        # A rolling smoke burst leads; two staggered wail arcs chase behind it.
        _sprite(layer, 'smoke', at, colors, scale*(.44+.08*p), round(p*24),
                heading)
        for index in range(2):
            q = max(0., p-(index+1)*.09)
            center = rp.point(source, target, q)
            image, draw, cel_center = rp.cel(40)
            b = _Brush(draw, cel_center)
            spread = 6+index*4
            start = round(p*140)+index*70
            b.arc((-spread, -spread*.7, spread, spread*.7),
                  (start, start+96), colors[2+index], 2)
            rp.put(layer, image, center, scale*.8)
    elif key == 'frost_kiss':
        # A compact ice kiss travels low; the two escort chips keep orbiting it.
        _sprite(layer, 'chip', at, colors, scale*(.40+.06*p), round(p*20),
                heading)
        for index in range(2):
            q = max(0., p-.06)
            center = rp.point(source, target, q)
            a = index*math.pi+p*6
            _sprite(layer, 'chip', _offset(center, math.cos(a)*7*scale,
                                           math.sin(a)*5*scale), colors,
                    scale*.22, round(p*22)+index, math.degrees(a))
    elif key == 'icicle_aegis':
        # The shell travels as one needle-led aegis, shards hugging its flanks.
        _sprite(layer, 'needle', at, colors, scale*.52, round(p*18), heading)
        ux, uy, nx, ny = _basis(source, target)
        for index in (-1, 1):
            q = max(0., p-.05)
            center = rp.point(source, target, q)
            _sprite(layer, 'chip', (center[0]+nx*index*8*scale,
                                    center[1]+ny*index*8*scale),
                    colors, scale*.26, round(p*20)+index)


def _contact(layer, key, source, target, colors, scale, density, age, emitters, secondary):
    if age >= .8:
        return
    local = scale*(.57 if secondary else 1.)
    if key in ('twin_cannon', 'dragon_crosscurrent') and not secondary and age < STREAM_CONTACT_END:
        origins = ((tuple(emitters)[:2] or (source,))
                   if key == 'twin_cannon' else (source,))
        for lane, emitter in enumerate(origins):
            _beam(layer, emitter, target, colors,
                  scale*(1. if key == 'twin_cannon' else .82), 1.+age*2, lane, density)
    if key == 'spark_chain':
        if secondary and age < .32:
            _lightning_route(layer, source, target, colors, local*.8, age/.8)
        _electric_contact(layer, target, colors, age, local*.81, density)
    elif key == 'storm_conductor':
        _electric_contact(layer, target, colors, age, local, density, thunder=True)
    elif key == 'charged_beacon':
        _charged_contact(layer,source,target,colors,age,local,density)
    elif key == 'shadow_siphon':
        if age < .17:
            image=_tile('shadow',colors,round(age*40))
            image=image.resize((image.width+round(age*60),
                                max(18,image.height-round(age*70))),Image.Resampling.NEAREST)
            rp.put(layer,image,target,local*(.72-age*1.35))
        for index in range(max(3,round(5*density))):
            born=.025+(index%3)*.045
            elapsed=age-born
            if not 0<=elapsed<.51:
                continue
            sign=-1 if index%2 else 1
            x=sign*(15+elapsed*50+math.sin(elapsed*9+index)*6)*local
            y=(-8-elapsed*(38+index%3*15))*local
            _sprite(layer,'smoke',_offset(target,x,y),colors,
                    local*(.55-elapsed*1.05),round(age*24)+index,sign*elapsed*48)
    elif key in BODY_ONLY_FLIGHTS:
        _pressure_wave(layer, target, colors, age, local, key)
    elif key == 'venom_armor':
        _poison_contact(layer, target, colors, age, local, density)
    elif key == 'venom_tide':
        _poison_contact(layer, target, colors, age, local, density, sludge=True)
    elif key == 'toxic_spines':
        for index in range(3):
            local_age = age-index*.055
            if 0 <= local_age < .14:
                recipient = _offset(target, (index-1)*9*local, (index-1)*7*local)
                _sprite(layer, 'needle', recipient, colors,
                        local*(.40-local_age*1.2), index, _heading(source, target))
        _poison_contact(layer, target, colors, age, local*.80, density)
    elif key == 'flame_guard':
        _fire_spread(layer, target, colors, age, local, density)
    elif key == 'twin_cannon':
        _water_contact(layer, source, target, colors, age, local, density)
    elif key == 'dragon_crosscurrent':
        if secondary:
            # Side-hit is Dragon Breath material at only the actual replay
            # recipient. No new source stream or fictional dragon head appears.
            for index in range(max(4, round(7*density))):
                born = index*.034
                local_age = age-born
                if not 0 <= local_age < .35:
                    continue
                ux, uy, nx, ny = _basis(source, target)
                pos = _offset(target, (ux*local_age*47+nx*math.sin(index)*12)*local,
                              (uy*local_age*47+ny*math.sin(index)*12)*local)
                _sprite(layer, 'breath', pos, colors, local*(.26-local_age*.32),
                        round(age*30)+index, _heading(source, target))
        else:
            _water_contact(layer, source, target, colors, age, local, density, narrow=True)
    elif key == 'cinder_eruption':
        _eruption_contact(layer, target, colors, age, local, density)
    elif key == 'undertow_lock':
        _whirlpool_contact(layer, target, colors, age, local, density)
    elif key == 'glacier_beam':
        if secondary:
            # Side hits are a small shard spray at the actual neighbour only.
            if age < .30:
                for index in range(3):
                    a = age*8+index*math.tau/3
                    _sprite(layer, 'chip', _offset(target, math.cos(a)*8*local,
                                                   math.sin(a)*6*local-4*local),
                            colors, local*(.30-age*.6), round(age*30)+index)
            return
        # A six-point crystal star opens on the main recipient, then frosts out.
        if age < .34:
            q = age/.34
            for index in range(6):
                a = index*math.tau/6+.3
                ux, uy = math.cos(a), math.sin(a)
                length = (8+q*17)*local
                rp.line(layer, (_offset(target, ux*4*local, uy*4*local),
                                _offset(target, ux*length, uy*length*.8)),
                        colors[1], 4*local*(1-q*.4))
                rp.line(layer, (_offset(target, ux*4*local, uy*4*local),
                                _offset(target, ux*length, uy*length*.8)),
                        colors[3], 2*local*(1-q*.4))
        for index in range(max(3, round(5*density))):
            born = .03+index*.05
            elapsed = age-born
            if not 0 <= elapsed < .40:
                continue
            a = index*2.4+elapsed*5
            _sprite(layer, 'chip', _offset(target, math.cos(a)*14*local,
                                           (-6-elapsed*26)*local), colors,
                    local*(.30-elapsed*.5), round(age*26)+index)
    elif key == 'storm_peck':
        # The beak stamp pierces first; discharge arcs follow on the same clock.
        if age < .17:
            _sprite(layer, 'needle', _offset(target, 0, -3*local), colors,
                    local*(.62-age*1.6), round(age*40), _heading(source, target))
        _electric_contact(layer, target, colors, age, local*.66, density)
    elif key == 'sky_blaze':
        _fire_spread(layer, target, colors, age, local, density)
        if age < .30:
            q = age/.30
            for index in range(5):
                a = -math.pi/2+(index-2)*.5
                ux, uy = math.cos(a), math.sin(a)
                length = (12+q*16)*local
                rp.line(layer, (_offset(target, ux*6*local, uy*6*local),
                                _offset(target, ux*length, uy*length)),
                        colors[2+index % 2], 3*local*(1-q))
    elif key == 'mind_shatter':
        # Psychic lands as a heavy recipient-local dome: a filled pressing
        # volume first, then only short fracture seams remain.
        if age < .42:
            q = age/.42
            image, draw, center = rp.cel(80)
            b = _Brush(draw, center)
            radius = 34-q*9
            path = [(-radius+j*2.6, -10+q*15+
                     (1-(j/24)**2)*-(20-q*8)) for j in range(25)]
            widths = [10.5*(1-q*.62)*math.sin(j/24*math.pi)+1
                      for j in range(25)]
            _ribbon(b, path, [w+2 for w in widths], colors[0])
            _ribbon(b, path, widths, colors[1])
            _ribbon(b, path[4:20], [w*.62 for w in widths[4:20]], colors[2])
            _ribbon(b, path[9:16], [max(.9,w*.22) for w in widths[9:16]], colors[4])
            rp.put(layer, image, target, local*(.72-q*.28))
        if age < .50:
            q = age/.50
            for index in range(max(3, round(5*density))):
                a = index*math.tau/max(3, round(5*density))+.55
                ux, uy = math.cos(a), math.sin(a)
                inner = (7+q*9)*local
                outer = (15+q*13-index % 2*4)*local
                rp.line(layer, (_offset(target, ux*inner, uy*inner*.8),
                                _offset(target, ux*outer, uy*outer*.8)),
                        colors[1+index % 3], max(1.,(3-q*1.6)*local))
    elif key == 'ancient_mind':
        # Ancient Power impresses a small faceted slab, then glyphs lift away.
        if age < .30:
            q = age/.30
            image, draw, center = rp.cel(64)
            b = _Brush(draw, center)
            radius = 10+q*8
            b.poly(((-radius,-radius*.48),(radius*.72,-radius*.62),
                    (radius,radius*.38),(-radius*.58,radius*.72)),colors[0])
            b.poly(((-radius*.62,-radius*.28),(radius*.42,-radius*.38),
                    (radius*.62,radius*.22),(-radius*.34,radius*.46)),colors[1])
            b.poly(((-radius*.24,-radius*.14),(radius*.24,-radius*.20),
                    (radius*.30,radius*.16),(-radius*.12,radius*.30)),colors[2])
            b.line(((-radius*.45,-radius*.34),(radius*.35,radius*.28)),colors[3],2)
            rp.put(layer,image,target,local*(.72-q*.28))
        for index in range(max(3,round(5*density))):
            born = .02+index*.055
            elapsed = age-born
            if not 0 <= elapsed < .45:
                continue
            a = index*1.7+elapsed*3
            _sprite(layer, 'glyph', _offset(target, math.cos(a)*13*local,
                                           (-4-elapsed*30)*local), colors,
                    local*(.24-elapsed*.34), round(age*22)+index,
                    math.degrees(a)*2)
    elif key == 'phantom_hex':
        # Three claw rakes land in sequence; the hex smoke sinks, never rising.
        for index in range(3):
            local_age = age-index*.06
            if not 0 <= local_age < .16:
                continue
            q = local_age/.16
            slash = math.radians(_heading(source, target)+index*38-30)
            ux, uy = math.cos(slash), math.sin(slash)
            cx, cy = (index-1)*10*local, (index-1)*6*local-4*local
            rp.line(layer, (_offset(target, cx-ux*(4+q*9)*local,
                                    cy-uy*(4+q*9)*local),
                            _offset(target, cx+ux*(4+q*9)*local,
                                    cy+uy*(4+q*9)*local)),
                    colors[1+index % 2], max(1., (4-q*2)*local))
        for index in range(max(3, round(4*density))):
            born = .04+(index % 3)*.05
            elapsed = age-born
            if not 0 <= elapsed < .46:
                continue
            sign = -1 if index % 2 else 1
            x = sign*(11+elapsed*34)*local
            y = (-16+elapsed*44)*local
            _sprite(layer, 'smoke', _offset(target, x, y), colors,
                    local*(.42-elapsed*.7), round(age*22)+index, sign*elapsed*30)
    elif key == 'spiteful_wail':
        # Concentric wail arcs burst out of the recipient, then break apart.
        if age < .40:
            q = age/.40
            image, draw, center = rp.cel(72)
            b = _Brush(draw, center)
            for index in range(3):
                radius = 6+q*(9+index*7)
                start = round(age*260)+index*125
                b.arc((-radius, -radius*.72, radius, radius*.72),
                      (start, start+58+index*16), colors[1+index % 3],
                      max(1, round((4-index)-q*2)))
            rp.put(layer, image, target, local*.62)
        for index in range(max(3, round(5*density))):
            born = .05+(index % 3)*.06
            elapsed = age-born
            if not 0 <= elapsed < .42:
                continue
            a = index*2.1+elapsed*3
            _sprite(layer, 'smoke',
                    _offset(target, math.cos(a)*(10+elapsed*22)*local,
                            math.sin(a)*(7+elapsed*15)*local-6*local),
                    colors, local*(.34-elapsed*.6), round(age*24)+index)
    elif key == 'frost_kiss':
        if secondary:
            # Psychic side hits are a small bright burst at the neighbour only.
            if age < .26:
                for index in range(3):
                    a = age*9+index*math.tau/3
                    _sprite(layer, 'spark',
                            _offset(target, math.cos(a)*7*local,
                                    math.sin(a)*5*local-3*local),
                            colors, local*(.26-age*.5), round(age*30)+index)
            return
        # A four-petal crystal opens on the diagonal axes, unlike Glacier's
        # six-point star, then melts into drifting chips.
        if age < .30:
            q = age/.30
            for index in range(4):
                a = index*math.pi/2+math.pi/4
                ux, uy = math.cos(a), math.sin(a)
                length = (6+q*15)*local
                rp.line(layer, (_offset(target, ux*3*local, uy*3*local),
                                _offset(target, ux*length, uy*length*.9)),
                        colors[1], max(1., 3*local*(1-q*.4)))
                rp.line(layer, (_offset(target, ux*3*local, uy*3*local),
                                _offset(target, ux*length, uy*length*.9)),
                        colors[3], max(1., 2*local*(1-q*.3)))
        for index in range(max(3, round(4*density))):
            born = .03+index*.05
            elapsed = age-born
            if not 0 <= elapsed < .38:
                continue
            a = index*2.6+elapsed*4
            _sprite(layer, 'chip', _offset(target, math.cos(a)*11*local,
                                           (-4-elapsed*22)*local), colors,
                    local*(.26-elapsed*.45), round(age*26)+index)
    elif key == 'icicle_aegis':
        if secondary:
            # Side hits spray chips sideways at the actual neighbour only.
            if age < .28:
                for index in range(3):
                    sign = -1 if index % 2 else 1
                    _sprite(layer, 'chip', _offset(target,
                                                   sign*(5+age*30)*local,
                                                   (index-1)*5*local-age*8*local),
                            colors, local*(.28-age*.55), round(age*30)+index,
                            sign*30)
            return
        # The aegis lands as a low shell arc that holds, then frosts apart.
        if age < .34:
            q = age/.34
            image, draw, center = rp.cel(72)
            b = _Brush(draw, center)
            radius = 15+q*9
            b.arc((-radius, -radius*.9, radius, radius*.55),
                  (185, 355), colors[0], max(1, round(5*(1-q*.5))))
            b.arc((-radius+3, -radius*.9+3, radius-3, radius*.55-2),
                  (195, 345), colors[2], max(1, round(3*(1-q*.5))))
            b.arc((-radius+6, -radius*.9+6, radius-6, radius*.55-4),
                  (210, 330), colors[3], 1)
            rp.put(layer, image, _offset(target, 0, 4*local), local*(.80-q*.2))
        for index in range(max(3, round(5*density))):
            born = .04+index*.05
            elapsed = age-born
            if not 0 <= elapsed < .40:
                continue
            a = index*1.9+elapsed*2
            _sprite(layer, 'chip', _offset(target, math.cos(a)*13*local,
                                           (-2-elapsed*24)*local), colors,
                    local*(.28-elapsed*.5), round(age*24)+index)


def draw(layer, skill_id, source, target, phase, progress, config, *, emitters=(), secondary=False):
    """Paint a move from factual origin/recipient and return whether it is owned.

    Repeated visual sprites are one action. Contact's .22s and aftermath's .58s
    share one clock. A side-hit has no windup/flight or newly opened cannon.
    Defensive/healing effects are painted separately from actual outcome packets.
    """
    if skill_id not in TYPES:
        return False
    if phase not in ('windup', 'flight', 'impact', 'aftermath'):
        return True
    if secondary and phase in ('windup', 'flight'):
        return True
    p = max(0., min(1., float(progress)))
    if phase == 'aftermath' and p >= 1.:
        return True
    scale, density = rp.settings(config)
    if secondary and skill_id == 'dragon_crosscurrent':
        element = 'DRAGON'
    elif secondary and skill_id == 'frost_kiss':
        element = 'PSYCHIC'
    else:
        element = TYPES[skill_id]
    colors = rp.palette(element, config)
    if phase == 'windup':
        _windup(layer, skill_id, source, target, colors, scale, density, p, emitters)
    elif phase == 'flight':
        _flight(layer, skill_id, source, target, colors, scale, density, p, emitters)
    else:
        _contact(layer, skill_id, source, target, colors, scale, density,
                 _contact_time(phase, p), emitters, secondary)
    return True
