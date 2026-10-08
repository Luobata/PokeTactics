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
    points = []
    for index in range(13):
        jitter = (1 if (index+tick) % 2 else -1)*(4+index % 3)*scale
        if index in (0, 12):
            jitter = 0
        points.append((source[0]+dx*index/12+nx*jitter,
                       source[1]+dy*index/12+ny*jitter))
    points[0], points[-1] = source, end
    rp.line(layer, points, colors[1], 9*scale)
    rp.line(layer, points, colors[3], 6*scale)
    rp.line(layer, points, colors[4], 3*scale)
    for index in (3, 8):
        _sprite(layer, 'spark', points[index], colors, scale*.19, tick+index)


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
            _ribbon(b, path, [2.7+math.sin(j/30*math.pi)*1.3 for j in range(31)], colors[1])
            _ribbon(b, path[:25], 1.7, colors[2])
            _ribbon(b, path[3:16], .8, colors[3])
    elif variant == 'psychic_blink':
        # Two bowed pressure shoulders squeeze, then peel back from the actor.
        pinch = math.sin(min(1., age/.26)*math.pi)*6
        for sign in (-1, 1):
            path = [(sign*(22-pinch+math.sin(j/22*math.pi)*6+q*5),
                     -27+j/22*54) for j in range(23)]
            _ribbon(b, path, [3.8-math.sin(j/22*math.pi)*1.4 for j in range(23)], colors[1])
            _ribbon(b, path[2:21], 2.1, colors[2])
            _ribbon(b, path[4:13], .9, colors[3])
        for sign in (-1, 1):
            b.line(((sign*10, -17-q*9), (sign*17, -21-q*7)), colors[3], 1)
    else:
        # Offset compression is a distortion surface, never an eye/clock glyph.
        for index in range(2):
            sign = -1 if index else 1
            path = []
            for j in range(28):
                angle = -.22*math.pi+j/27*1.30*math.pi+index*math.pi
                radius = 22+index*6+q*8
                x, y = math.cos(angle)*radius, math.sin(angle)*radius*.66
                path.append((x+sign*(5-q*3), y+x*.20))
            _ribbon(b, path, 3.5, colors[1])
            _ribbon(b, path[2:23], 2.1, colors[2])
            _ribbon(b, path[5:16], .8, colors[4])
    # The old bands stayed large up to .70s and blinked out. Break their
    # contours and steadily shrink the hard-edged residue on this same clock.
    if age > .52:
        seam = 1+round((age-.52)/.18*3)
        for y in (center[1]-10,center[1]+9):
            draw.rectangle((0,y-seam,image.width,y+seam),fill=(0,0,0,0))
    collapse = max(0.,1-max(0.,age-.40)/.30)**1.25
    rp.put(layer,image,at,scale*(.66-.24*q)*collapse)

def _electric_contact(layer, at, colors, age, scale, density, thunder=False):
    """Thunderbolt's quick narrow snaps vs. Thunder's heavy delayed column."""
    delays = (0., .055, .125) if not thunder else (0., .11, .25, .36)
    for index, delay in enumerate(delays):
        local = age-delay
        life = .15 if not thunder else .17
        if not 0 <= local < life:
            continue
        lateral = (-14, 13, 0, -7)[index]*scale
        height = (82 if thunder else 55)*scale
        start = _offset(at, lateral, -height)
        end = _offset(at, lateral*.15, 3*scale)
        path = []
        tick = round(local*45)
        for j in range(8):
            q = j/7
            zig = (11 if (j+index+tick) % 2 else -9)*scale if j not in (0, 7) else 0
            path.append((start[0]+(end[0]-start[0])*q+zig,
                         start[1]+(end[1]-start[1])*q))
        # A short heavy dark envelope carries a narrow hot edge; the main
        # discharge has physical width without a huge white target silhouette.
        rp.line(layer, path, colors[0], (19 if thunder else 12)*scale)
        rp.line(layer, path, colors[1], (14 if thunder else 9)*scale)
        rp.line(layer, path, colors[3], (8 if thunder else 5)*scale)
        rp.line(layer, path, colors[4], 3*scale)
        if thunder:
            for joint, side in ((2, -1), (5, 1)):
                a = path[joint]
                branch = (a, _offset(a, side*15*scale, 6*scale),
                          _offset(a, side*11*scale, 16*scale))
                rp.line(layer, branch, colors[1], 6*scale)
                rp.line(layer, branch, colors[3], 3*scale)
        _discharge_rim(layer, at, colors, local, scale*(1. if thunder else .69), thunder)
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


def _discharge_rim(layer, at, colors, age, scale, heavy=False):
    if not 0 <= age < .13:
        return
    image, draw, center = rp.cel(64)
    b = _Brush(draw, center)
    q = age/.13
    # Buckled crescent pressure face, briefly compressed at one hit point.
    path = [(math.cos(-.15+j/24*math.pi*1.60)*(17+q*12),
             math.sin(-.15+j/24*math.pi*1.60)*(8+q*7)) for j in range(25)]
    widths = [(3.2 if heavy else 2.5)*(1-q*.55) for _ in path]
    _ribbon(b, path, [w+1.2 for w in widths], colors[0])
    _ribbon(b, path, widths, colors[2])
    _ribbon(b, path[2:19], [max(.8,w*.48) for w in widths[2:19]], colors[3])
    rp.put(layer, image, _offset(at,0,11*scale), scale*.78)


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
    _discharge_rim(layer,at,colors,age,scale*.85)

def _poison_contact(layer, at, colors, age, scale, density, *, sludge=False):
    """A sticky sheet opens into heavy droplets, then separate rising bubbles."""
    duration = .30 if sludge else .18
    if age < duration:
        image, draw, center = rp.cel(64)
        b = _Brush(draw, center)
        q = age/duration
        radius=(12+q*(17 if sludge else 8))
        # Irregular lobes surround a clear center; a low lit wet face has depth.
        path=[]
        for j in range(37):
            angle=j/36*math.tau
            r=radius*(1+.13*math.sin(angle*5+age*13))
            path.append((math.cos(angle)*r,math.sin(angle)*r*.53))
        _ribbon(b,path,[(4.8 if sludge else 3.5)*(1-q*.40) for _ in path],colors[0])
        _ribbon(b,path[1:35],(3.3 if sludge else 2.2)*(1-q*.35),colors[1])
        _ribbon(b,path[3:22],1.8,colors[2])
        _ribbon(b,path[5:13],.8,colors[3])
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
                        scale*(.27-local*.33),index,sign*local*70)
        born=.10+(index%4)*.055
        local=age-born
        if 0<=local<.36:
            x=((index*17)%43-21+math.sin(local*11+index)*4)*scale
            y=(8-local*95+(index%2)*7)*scale
            _sprite(layer,'bubble',_offset(at,x,y),colors,
                    scale*(.22+.06*math.sin(local*8)),index+round(age*35))

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
                    scale*(.29+index % 2*.06), index)
        else:
            if local < .16:
                bounce = -math.sin(local*math.pi/.16)*8*scale
                _sprite(layer, 'rock', _offset(landing, 0, bounce), colors,
                        scale*((.48 if index==0 else .30)-local*.78),index)
            for chip in range(3):
                angle = chip*math.tau/3+index*.9
                distance = (4+local*83)*scale
                pos = _offset(landing, math.cos(angle)*distance,
                              math.sin(angle)*distance*.5+local*local*48*scale)
                _sprite(layer, 'chip', pos, colors, scale*(.23-local*.33), chip)
            if local < .24:
                _sprite(layer,'flame',_offset(landing,0,-local*30*scale),
                        colors,scale*(.37-local*.66),round(local*40))


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
                    scale*(.32 if index==1 else .20+index%2*.04),index)
    elif key == 'venom_armor':
        image, draw, center = rp.cel(48)
        b = _Brush(draw, center)
        for index in range(3):
            y=-10+index*8+p*3
            width=14+math.sin(p*8+index)*3
            path=[(math.cos(j/18*math.pi)*width,
                   y+math.sin(j/18*math.pi)*(4+index)) for j in range(19)]
            _ribbon(b,path,3.7,colors[0])
            _ribbon(b,path,2.7,colors[1])
            _ribbon(b,path[2:14],1.5,colors[2])
            _ribbon(b,path[4:10],.7,colors[3])
        rp.put(layer,image,source,scale*.65)
    elif key == 'venom_tide':
        _sprite(layer,'sludge',_offset(source,0,-6*scale),colors,
                scale*(.24+.16*p),step)
        for index in (-1,1):
            _sprite(layer,'bubble',_offset(source,index*(20-p*6)*scale,
                                           (-2-p*8)*scale),colors,
                    scale*(.16+.05*p),step+index)
    elif key == 'toxic_spines':
        for index in range(3):
            _sprite(layer, 'needle', _offset(source, 0, (index-1)*7*scale),
                    colors, scale*(.17+.07*p), index, _heading(source, target))
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
    elif key in ('spark_chain', 'storm_conductor'):
        for index in range(3 if key == 'spark_chain' else 5):
            a = index*math.tau/5+p*2
            _sprite(layer, 'spark', _offset(source, math.cos(a)*18*scale,
                                          math.sin(a)*22*scale), colors,
                    scale*.17, step+index)
    elif key == 'dragon_crosscurrent':
        for index in (-1, 1):
            _sprite(layer, 'water', _offset(source, index*11*scale,
                                          math.sin(p*8+index)*7*scale),
                    colors, scale*(.16+.10*p), step)
    elif key == 'undertow_lock':
        _whirlpool_contact(layer, source, colors, p*.43, scale*.48, density)


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
        _lightning_route(layer, source, at, colors, scale*.68, p)
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
                    scale*(.30-index*.018), index)
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
            _sprite(layer,'needle',center,colors,scale*(.35-index*.035),index,
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
                    scale*(.47 if index==0 else .27+index%2*.055),index)
    elif key == 'dragon_crosscurrent':
        _beam(layer, source, at, colors, scale*.82, p, 0, density)
    elif key == 'undertow_lock':
        retro_water.surf_front(layer, source, target, colors, p, scale=scale,
                               density=density)


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
            image=image.resize((image.width+round(age*45),
                                max(18,image.height-round(age*60))),Image.Resampling.NEAREST)
            rp.put(layer,image,target,local*(.61-age*1.25))
        for index in range(max(3,round(4*density))):
            born=.025+(index%3)*.045
            elapsed=age-born
            if not 0<=elapsed<.51:
                continue
            sign=-1 if index%2 else 1
            x=sign*(13+elapsed*42+math.sin(elapsed*9+index)*5)*local
            y=(-7-elapsed*(32+index%3*13))*local
            _sprite(layer,'smoke',_offset(target,x,y),colors,
                    local*(.38-elapsed*.38),round(age*24)+index,sign*elapsed*48)
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
                        local*(.27-local_age), index, _heading(source, target))
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
    element = 'DRAGON' if secondary and skill_id == 'dragon_crosscurrent' else TYPES[skill_id]
    colors = rp.palette(element, config)
    if phase == 'windup':
        _windup(layer, skill_id, source, target, colors, scale, density, p, emitters)
    elif phase == 'flight':
        _flight(layer, skill_id, source, target, colors, scale, density, p, emitters)
    else:
        _contact(layer, skill_id, source, target, colors, scale, density,
                 _contact_time(phase, p), emitters, secondary)
    return True
