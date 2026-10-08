"""Physical native choreography adapted from inspected G3 move scripts.

See reports/evidence/original-move-reference-2026-10-07/physical-reference.md.
Short hit stamps, shaded rotating horns, staggered trajectories and recovery
replace long-lived pictograms. Drawing consumes the replay's actual emitters
and recipients; it never adds damage, moves an actor or creates terrain.
"""
from functools import lru_cache
import math

from PIL import Image, ImageDraw
import retro_primitives as R

SKILL_IDS = (
    'four_arm_combo', 'venom_rush', 'stone_pulse', 'rock_spikes',
    'sweeping_kick', 'root_domain', 'armor_pincer', 'gale_cross', 'bull_rush',
    'cliff_swoop', 'alert_tail', 'mud_anchor', 'spinning_cleanup',
    'horn_pressure', 'iron_fault', 'cross_bullet', 'crag_citadel',
)
_ELEMENTS = dict(zip(SKILL_IDS, (
    'FIGHTING', 'POISON', 'GROUND', 'ROCK', 'FIGHTING', 'GRASS', 'BUG', 'BUG',
    'NORMAL', 'ROCK', 'NORMAL', 'GROUND', 'FIGHTING', 'FIGHTING', 'STEEL',
    'STEEL', 'ROCK',
)))
# Fur, hard chitin and blade surfaces choose material inks without changing move type.
_PALETTE_MATERIAL = {'bull_rush':'GROUND','alert_tail':'GROUND',
                     'armor_pincer':'ROCK','gale_cross':'STEEL'}
CONTACT = .22
LIFETIME = .8


@lru_cache(maxsize=160)
def _sprite(kind, colors, variant=0):
    """Tiny original stamps/material cels, never a full-size semantic icon."""
    image, draw, center = R.cel(16)
    x, y = center

    def polygon(path, color, outline=True):
        points = [(round(x+dx), round(y+dy)) for dx, dy in path]
        draw.polygon(points, fill=colors[color])
        if outline:
            draw.line(points+[points[0]], fill=colors[0], width=1)

    if kind == 'rock':
        polygon(((-5,-3),(-2,-6),(4,-4),(6,0),(3,5),(-3,5),(-6,1)),1)
        polygon(((-4,-3),(-1,-5),(3,-3),(1,0),(-3,1)),3,False)
        draw.line(((x+1,y),(x,y+4),(x-3,y+3)),fill=colors[0],width=1)
        if variant % 2:
            draw.line(((x+2,y-2),(x+4,y+1)),fill=colors[4],width=1)
    elif kind == 'mud':
        polygon(((-4,-4),(1,-5),(5,-1),(4,3),(0,5),(-5,2)),1)
        draw.ellipse((x-3,y-2,x+3,y+3),fill=colors[2])
        draw.line(((x-2,y-2),(x+1,y-2)),fill=colors[4],width=1)
    elif kind == 'fist':
        polygon(((-4,-3),(3,-3),(5,-1),(4,4),(-3,4),(-5,1)),2)
        draw.line(((x-3,y-2),(x+2,y-2)),fill=colors[4],width=1)
        for offset in (-2,0,2):
            draw.line(((x+offset,y-2),(x+offset,y+1)),fill=colors[0],width=1)
    elif kind == 'foot':
        polygon(((-3,-6),(0,-6),(1,1),(5,2),(6,5),(-3,5),(-4,2)),2)
        draw.line(((x-1,y-4),(x-1,y+2),(x+4,y+3)),fill=colors[4],width=1)
    elif kind == 'claw':
        for offset in (-3,0,3):
            draw.line(((x-5,y+offset+2),(x+4,y+offset-2)),fill=colors[0],width=3)
            draw.line(((x-5,y+offset+2),(x+4,y+offset-2)),fill=colors[4],width=1)
    else:  # shared G3-like hitsplat, briefly keyed to real contact
        polygon(((-6,0),(-3,-2),(-4,-5),(-1,-3),(1,-7),(2,-3),
                 (6,-4),(4,-1),(7,1),(3,2),(4,6),(0,4),
                 (-3,7),(-3,3),(-7,4),(-4,1)),3)
        draw.rectangle((x-1,y-1,x+1,y+1),fill=colors[4])
    return image


def _turned(image, a, b, extra=0.):
    angle=-math.degrees(math.atan2(b[1]-a[1],b[0]-a[0]))+extra
    return image.rotate(round(angle/15)*15,Image.Resampling.NEAREST,expand=True)


def _stroke(layer, points, colors, width=3.):
    R.line(layer,points,colors[0],width+3)
    R.line(layer,points,colors[2],width)
    R.line(layer,points,colors[4],3)


def _arc(layer, center, rx, ry, turn, sweep, colors, scale, width=3.):
    points=[]
    for i in range(9):
        a=turn+sweep*i/8
        points.append((center[0]+math.cos(a)*rx*scale,
                       center[1]+math.sin(a)*ry*scale))
    _stroke(layer,points,colors,width*scale)


def _basis(a,b):
    distance=math.dist(a,b) or 1.
    ux,uy=(b[0]-a[0])/distance,(b[1]-a[1])/distance
    return ux,uy,-uy,ux


def _head(a,b,p,bend=0.,lane=0.):
    ux,uy,nx,ny=_basis(a,b)
    q=R.point(a,b,p)
    wave=math.sin(math.pi*p)
    return q[0]+nx*lane*wave, q[1]+ny*lane*wave+bend*wave


def _trail(layer,a,b,p,colors,scale,width=3.,bend=0.,lane=0.,span=.20):
    """Every route begins at its supplied emitter, never a synthetic joint."""
    back=max(0.,p-span)
    points=[_head(a,b,back+(p-back)*i/4,bend,lane) for i in range(5)]
    _stroke(layer,points,colors,width*scale)
    return points[-1]


def _flash(layer,position,colors,elapsed,scale,delay=0.,duration=.09,size=.70,kind='hit'):
    age=elapsed-delay
    if not 0<=age<duration:
        return
    q=age/duration
    R.put(layer,_sprite(kind,colors),position,scale*size*(1-q*.72))


def _cut(layer,position,colors,elapsed,scale,angle,delay=0.,duration=.14,length=26.,width=3.):
    age=elapsed-delay
    if not 0<=age<duration:
        return
    p=age/duration
    ux,uy=math.cos(angle),math.sin(angle)
    # The slash draws through the target then contracts behind its moving tip.
    start=-length*.5+length*max(0.,p-.28)
    end=-length*.5+length*min(1.,p*1.9+.18)
    _stroke(layer,((position[0]+ux*start*scale,position[1]+uy*start*scale),
                   (position[0]+ux*end*scale,position[1]+uy*end*scale)),colors,width*scale)



@lru_cache(maxsize=384)
def _drill_cel(colors, turn, heavy=False, compression=0):
    """Original shaded cone, with its tip at the cel's rotation anchor.

    G3 supplies bow/lunge, rolling drill texture and repeated contact timing.
    Rounded cone geometry and its wrapping bands are our material adaptation.
    """
    image, painter, tip = R.cel(64)
    tx, ty = tip
    squash = min(1., max(0., compression / 8.))
    length = (27 if heavy else 24) * (1 - .38 * squash)
    radius = (10 if heavy else 8.5) * (1 + .18 * squash)
    base = tx - length

    def cross(x):
        return radius * max(0., (tx - x) / length) ** .82

    def region(upper, lower, ink):
        xs = [base + length * i / 16 for i in range(17)]
        points = [(round(x), round(ty + cross(x) * upper)) for x in xs]
        points += [(round(x), round(ty + cross(x) * lower)) for x in reversed(xs)]
        painter.polygon(points, fill=colors[ink])
        return points

    contour = region(-1., 1., 1)
    region(-.91, .46, 2)
    region(-.78, -.08, 3)
    # The base is a rounded end cap, with a shaded lower rim.
    painter.ellipse((round(base - 2), round(ty - radius),
                     round(base + 4), round(ty + radius)), fill=colors[0])
    painter.ellipse((round(base - 1), round(ty - radius + 1),
                     round(base + 3), round(ty + radius - 1)), fill=colors[1])
    painter.arc((round(base - 1), round(ty - radius + 1),
                 round(base + 3), round(ty + radius - 1)), 210, 300,
                fill=colors[3], width=1)
    painter.line(contour + [contour[0]], fill=colors[0], width=1)
    spin = turn * math.tau / 24
    segment = []
    # A helix's near-facing halves cross the cone surface. Their spacing
    # narrows toward the tip, rather than moving as flat parallel strokes.
    for index in range(97):
        q = index / 96
        x = base + length * q
        phi = q * math.tau * 2.4 + spin
        visible = math.cos(phi) >= -.12
        y = ty + cross(x) * math.sin(phi) * .9
        if visible:
            segment.append((round(x), round(y)))
        if not visible or index == 96:
            if len(segment) > 1:
                painter.line(segment, fill=colors[0], width=3)
                painter.line(segment, fill=colors[3], width=2)
                painter.line([(x, y - 1) for x, y in segment],
                             fill=colors[4], width=1)
            segment = []
    # The lit shoulder remains visible while the bands rotate through it.
    shoulder = [(round(base + length * q),
                 round(ty - cross(base + length * q) * .63))
                for q in (.19, .27, .36, .44)]
    painter.line(shoulder, fill=colors[4], width=1)
    return image


def _drill_stamp(layer, a, b, tip, colors, scale, turn, heavy, compression=0.):
    cel = _drill_cel(colors, round(turn * 24) % 24, heavy,
                     round(min(1., max(0., compression)) * 8))
    # Keeping the tip at the image center preserves the supplied route end
    # under rotation/scaling; no cone protrudes ahead of contact.
    angle = -math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
    cel = cel.rotate(round(angle / 15) * 15, Image.Resampling.NEAREST,
                     center=(32, 32), expand=False)
    R.put(layer, cel, tip, scale * .72)


def _oriented(a, ux, uy, nx, ny, x, y, scale):
    return (a[0] + (ux * x + nx * y) * scale,
            a[1] + (uy * x + ny * y) * scale)


def _compression(layer, a, b, colors, elapsed, scale, *,
                 duration=.14, radius=40., delay=0.):
    """A thick bowed pressure ribbon expands and buckles at real contact."""
    age = elapsed - delay
    if not 0 <= age < duration:
        return
    q = age / duration
    ux, uy, nx, ny = _basis(a, b)
    reach = radius * (.72 + .28 * math.sin(math.pi * q))
    depth = 9 + 7 * math.sin(math.pi * q)
    thickness = 8 * (1 - q * .68)
    front, back = [], []
    for index in range(21):
        angle = -math.pi / 2 + index * math.pi / 20
        x = -5 + depth * math.cos(angle) + q * 7
        y = reach * math.sin(angle)
        front.append(_oriented(b, ux, uy, nx, ny, x, y, scale))
        back.append(_oriented(b, ux, uy, nx, ny, x - thickness, y, scale))
    snap = lambda points: [(round(x / 3) * 3, round(y / 3) * 3)
                           for x, y in points]
    painter = ImageDraw.Draw(layer)
    boundary = snap(front + list(reversed(back)))
    painter.polygon(boundary, fill=colors[1])
    R.line(layer, front + list(reversed(back)) + [front[0]], colors[0], 3)
    middle = [R.point(x, y, .38) for x, y in zip(front, back)]
    R.line(layer, middle, colors[2], max(3., thickness * .54 * scale))
    R.line(layer, front[2:18], colors[4], 3)
    # One compressed shadow crescent is visibly offset from the lit rim.
    R.line(layer, back[6:20], colors[0], 3)


def _drill_travel(layer, key, a, b, p, colors, scale):
    heavy = key == 'horn_pressure'
    bend = (-18 if heavy else -5) * scale
    tip = _head(a, b, p, bend)
    ux, uy, nx, ny = _basis(a, b)
    # Brief wrapping afterimages hug the broad end; they are curved,
    # shaded rings rather than a long linear tracer or another projectile.
    for index in range(2):
        center = _head(a, b, max(0., p - .055 - index * .04), bend)
        turn = p * math.tau * 3 + index * 1.9
        points = []
        for step in range(9):
            angle = turn + step * math.pi * .85 / 8
            points.append(_oriented(center, ux, uy, nx, ny,
                                    -35 - index * 8 + math.cos(angle) * 4,
                                    math.sin(angle) * (12 - index * 2), scale))
        R.line(layer, points, colors[0], 6)
        R.line(layer, points, colors[3 if index == 0 else 1], 3)
    _drill_stamp(layer, a, b, tip, colors, scale, p * 3.25, heavy)


def _drill_chips(layer, key, a, b, elapsed, colors, scale, density):
    """Finite curved knock-off trajectories, on the continuous contact clock."""
    ux, uy, nx, ny = _basis(a, b)
    count = max(3, round((8 if key == 'horn_pressure' else 7) * density))
    painter = ImageDraw.Draw(layer)
    for index in range(count):
        age = elapsed - index * .007
        duration = .56 + index % 3 * .045
        if not 0 <= age < duration:
            continue
        q = age / duration
        side = -1 if index % 2 else 1

        def point(t):
            axial = 4 + (14 + index % 3 * 6) * t - 13 * t * t
            lateral = side * (8 + index % 3 * 4 +
                              (28 + index % 4 * 7) * math.sin(t * math.pi * .62))
            x, y = _oriented(b, ux, uy, nx, ny, axial, lateral, scale)
            return x, y + 21 * t * t * scale

        tip = point(q)
        path = [point(max(0., q - .075 + .075 * i / 4)) for i in range(5)]
        R.line(layer, path, colors[1], 6 if index % 3 == 0 else 3)
        # Short opaque material fragments carry a dark underside and lit lip.
        x, y = (round(v / 3) * 3 for v in tip)
        r = 3 if index % 3 else 4
        if key == 'venom_rush':
            painter.ellipse((x - r, y - r - 2, x + r, y + r), fill=colors[1])
            painter.ellipse((x - r + 1, y - r - 2, x + r - 1, y), fill=colors[3])
        else:
            painter.polygon(((x - r, y), (x, y - r - 2),
                             (x + r + 2, y - r), (x + r, y + r)), fill=colors[1])
            R.line(layer, ((x - r, y), (x + r, y - r)), colors[3], 3)
        painter.rectangle((x, y - r, x + 2, y - r + 2), fill=colors[4])


def _drill_contact(layer, key, a, b, elapsed, colors, scale):
    heavy = key == 'horn_pressure'
    duration = .18 if heavy else .14
    if elapsed < duration:
        q = elapsed / duration
        _drill_stamp(layer, a, b, b, colors, scale * (1 - .22 * q),
                     .31 + elapsed * 10, heavy, q)
    _compression(layer, a, b, colors, elapsed, scale, duration=duration,
                 radius=48 if heavy else 39)
    # G3 Drill's repeated small target-local hits become brief glints on
    # the pressure rim, never a second visual travel or another damage hit.
    ux, uy, nx, ny = _basis(a, b)
    for index in range(3 if heavy else 2):
        pos = _oriented(b, ux, uy, nx, ny, 2, (-1 if index % 2 else 1) *
                        (10 + index * 4), scale)
        _flash(layer, pos, colors, elapsed, scale, index * .045, .05, .32)


@lru_cache(maxsize=192)
def _body(kind, colors, variant=0):
    """Shaded, readable material stamps; their short motion supplies identity."""
    image, painter, (x,y) = R.cel(32)
    def poly(points, ink, rim=False):
        path=[(round(x+dx),round(y+dy)) for dx,dy in points]
        painter.polygon(path,fill=colors[ink])
        if rim:
            painter.line(path+[path[0]],fill=colors[0],width=1)
    if kind=='fist':
        poly(((-12,1),(-8,-3),(-7,-6),(-4,-7),(-2,-6),(0,-8),
              (3,-7),(5,-6),(8,-4),(10,-1),(9,5),(6,8),(-4,7),(-9,4)),1,True)
        poly(((-8,-2),(-6,-5),(-3,-5),(0,-6),(3,-5),(7,-3),
              (8,0),(6,5),(-3,5),(-6,2)),2)
        poly(((-6,-4),(-3,-4),(0,-5),(3,-4),(6,-2),(4,0),(-5,0)),3)
        painter.line(((x-7,y+2),(x-3,y+4),(x+4,y+4)),fill=colors[0],width=1)
        for dx,dy in ((-4,-5),(0,-6),(4,-4)):
            painter.line(((x+dx,y+dy),(x+dx+1,y+dy+3)),fill=colors[0],width=1)
        painter.line(((x-4,y-4),(x-1,y-5),(x+2,y-4)),fill=colors[4],width=1)
    elif kind=='foot':
        poly(((-5,-13),(-1,-13),(3,-4),(3,1),(11,5),(13,8),
              (11,11),(3,11),(-5,7),(-7,2),(-7,-5)),1,True)
        poly(((-4,-11),(-1,-10),(1,-3),(0,3),(9,6),(10,8),
              (3,8),(-3,5),(-4,0)),2)
        painter.line(((x-3,y-10),(x-2,y-3),(x-3,y+2),(x+6,y+6)),fill=colors[3],width=2)
        painter.line(((x+5,y+6),(x+10,y+8)),fill=colors[4],width=1)
        painter.line(((x-4,y+6),(x+4,y+10),(x+11,y+10)),fill=colors[0],width=2)
    elif kind in ('pincer','blade'):
        # Closed, hard hooked claw: broad steel face and a sharp bright bevel.
        poly(((-13,4),(-9,-2),(-5,-7),(0,-10),(7,-10),(12,-5),
              (13,1),(7,7),(0,9),(-6,7),(-9,4)),1,True)
        poly(((-10,2),(-5,-5),(1,-8),(7,-8),(10,-4),(8,-1),
              (3,-3),(-1,1),(5,3),(10,1),(7,5),(0,6),(-5,4)),2)
        poly(((-7,0),(-3,-4),(2,-7),(7,-7),(9,-4),(3,-5),(-2,-1)),3)
        painter.line(((x-5,y-3),(x+1,y-7),(x+7,y-7)),fill=colors[4],width=1)
        painter.line(((x-1,y+1),(x+4,y+3),(x+9,y)),fill=colors[0],width=2)
    elif kind=='rock':
        wobble=variant%3
        poly(((-10,-5),(-6,-11),(1,-12),(8,-8),(12,-2),
              (10,7),(3,11),(-5,10),(-11,4),(-12,-1)),1,True)
        poly(((-8,-4),(-4,-9),(1,-10),(5,-6),(2,0),(-3,3),(-8,1)),3)
        poly(((5,-6),(9,-2),(7,5),(2,8),(2,0)),2)
        poly(((-8,2),(-3,3),(2,0),(2,8),(-4,7)),1)
        painter.line(((x-8,y-4),(x-3,y-8),(x+1,y-9)),fill=colors[4],width=1)
        painter.line(((x-3,y+3),(x+2,y),(x+6,y-5)),fill=colors[0],width=1)
        if wobble:
            painter.line(((x+4,y+4),(x+7,y+1)),fill=colors[3],width=1)
    elif kind=='mud':
        poly(((-11,1),(-10,-5),(-6,-8),(-2,-6),(3,-9),(8,-5),
              (12,-1),(10,6),(4,9),(-3,8),(-8,5)),1,True)
        poly(((-8,-3),(-5,-6),(-1,-4),(3,-6),(8,-2),(7,3),
              (1,5),(-5,2)),2)
        painter.arc((x-7,y-5,x+6,y+4),195,290,fill=colors[3],width=2)
        painter.line(((x-5,y-4),(x-2,y-5)),fill=colors[4],width=1)
        painter.arc((x-6,y-2,x+9,y+7),15,115,fill=colors[0],width=2)
    elif kind in ('tail','metal_tail'):
        poly(((-14,4),(-10,-3),(-5,-7),(2,-8),(8,-5),(13,-1),
              (14,4),(9,7),(2,7),(-5,4),(-10,6)),1,True)
        poly(((-11,2),(-6,-4),(1,-5),(7,-3),(10,1),(7,4),
              (1,4),(-4,1),(-8,3)),2)
        painter.line(((x-9,y),(x-4,y-4),(x+2,y-5),(x+8,y-2)),fill=colors[3],width=2)
        for offset in (-5,1,7):
            painter.line(((x+offset,y-4),(x+offset+2,y+4)),
                         fill=colors[0 if kind=='metal_tail' else 3],width=1)
        painter.line(((x+4,y-3),(x+9,y)),fill=colors[4],width=1)
    return image


def _material_put(layer,kind,position,colors,scale,variant=0,turn=0.):
    image=_body(kind,colors,variant)
    if turn:
        image=image.rotate(round(turn/15)*15,Image.Resampling.NEAREST,expand=True)
    R.put(layer,image,position,scale)


def _sheet(layer,points,widths,colors,*,bright=True):
    """Filled tapered material surface, not nested equal-width bright lines."""
    if len(points)<2:
        return
    left,right=[],[]
    for i,center in enumerate(points):
        ux,uy,nx,ny=_basis(points[max(0,i-1)],points[min(len(points)-1,i+1)])
        width=widths[i] if isinstance(widths,(tuple,list)) else widths
        left.append((center[0]+nx*width,center[1]+ny*width))
        right.append((center[0]-nx*width,center[1]-ny*width))
    snap=lambda path:[(round(x/3)*3,round(y/3)*3) for x,y in path]
    painter=ImageDraw.Draw(layer)
    outline=left+list(reversed(right))
    painter.polygon(snap(outline),fill=colors[0])
    inner_left=[R.point(c,a,.70) for c,a in zip(points,left)]
    inner_right=[R.point(c,b,.72) for c,b in zip(points,right)]
    painter.polygon(snap(inner_left+list(reversed(inner_right))),fill=colors[1])
    lit_right=[R.point(c,b,.24) for c,b in zip(points,right)]
    painter.polygon(snap(inner_left+list(reversed(lit_right))),fill=colors[2])
    painter.polygon(snap([R.point(c,a,.62) for c,a in zip(points,left)]+
                        list(reversed([R.point(c,a,.14) for c,a in zip(points,left)]))),fill=colors[3])
    if bright:
        R.line(layer,left[2:max(3,len(left)-2)],colors[4],3)


def _crescent(layer,position,colors,scale,turn=0.,rx=27,ry=12,sweep=2.7,width=8,*,bright=True):
    path,widths=[],[]
    for i in range(19):
        q=i/18
        angle=turn+(q-.5)*sweep
        path.append((position[0]+math.cos(angle)*rx*scale,
                     position[1]+math.sin(angle)*ry*scale))
        widths.append(max(1.2,width*math.sin(q*math.pi)**.75)*scale)
    _sheet(layer,path,widths,colors,bright=bright)


def _blade_cut(layer,position,colors,elapsed,scale,angle,delay=0.,duration=.16,length=60,width=12):
    age=elapsed-delay
    if not 0<=age<duration:
        return
    q=age/duration
    ux,uy=math.cos(angle),math.sin(angle)
    nx,ny=-uy,ux
    middle=(q-.5)*length*.48
    path,widths=[],[]
    for i in range(17):
        t=i/16
        along=(t-.5)*length+middle
        across=math.sin(t*math.pi)*length*.11
        path.append((position[0]+(ux*along+nx*across)*scale,
                     position[1]+(uy*along+ny*across)*scale))
        widths.append(max(1.,width*math.sin(t*math.pi)**.8*(1-q*.62))*scale)
    _sheet(layer,path,widths,colors)


def _ground_fault(layer,center,colors,elapsed,scale):
    if not 0<=elapsed<.28:
        return
    reach=(13+min(.17,elapsed)*174)*scale
    ground=(center[0],center[1]+23*scale)
    for side in (-1,1):
        points=[]
        for i in range(7):
            q=i/6
            points.append((ground[0]+side*q*reach,
                           ground[1]+math.sin(i*2.1+elapsed*23)*4*scale))
        _sheet(layer,points,[max(1.,(7-i*.9)*(1-elapsed*.9))*scale for i in range(7)],colors,bright=False)
    if elapsed<.16:
        for index in range(3):
            age=max(0.,elapsed-index*.018)
            x=ground[0]+(index-1)*16*scale
            y=ground[1]-math.sin(min(1.,age/.16)*math.pi)*(10+index*3)*scale
            _material_put(layer,'rock',(x,y),colors,scale*(.25+index%2*.12),index)


def _mud_cup(layer,center,colors,elapsed,scale):
    """Thick irregular soil-water fold settles into clinging wet lobes."""
    if not 0<=elapsed<.34:
        return
    q=elapsed/.34
    ground=(center[0],center[1]+17*scale)
    radius=(22+math.sin(min(1.,q*1.5)*math.pi)*18)*scale
    painter=ImageDraw.Draw(layer)
    outer,inner=[],[]
    for i in range(25):
        t=i/24
        x=(t-.5)*2*radius
        y=-(math.sin(t*math.pi)*(15+7*math.sin(t*math.tau*3+elapsed*17))*(1-q*.75))*scale
        outer.append((ground[0]+x,ground[1]+y))
        inner.append((ground[0]+x*.94,ground[1]+8*scale+math.sin(t*math.tau)*3*scale))
    snap=lambda path:[(round(x/3)*3,round(y/3)*3) for x,y in path]
    painter.polygon(snap(outer+list(reversed(inner))),fill=colors[0])
    painter.polygon(snap([R.point(a,b,.14) for a,b in zip(outer,inner)]+
                        list(reversed([R.point(a,b,.78) for a,b in zip(outer,inner)]))),fill=colors[1])
    painter.polygon(snap([R.point(a,b,.18) for a,b in zip(outer,inner)]+
                        list(reversed([R.point(a,b,.51) for a,b in zip(outer,inner)]))),fill=colors[2])
    R.line(layer,outer[3:12],colors[3],3)
    for index in range(3):
        at=(ground[0]+(index-1)*radius*.52,ground[1]-8*scale*(1-q))
        _material_put(layer,'mud',at,colors,scale*(.26-q*.10),index)


def _vines(layer,points,colors,scale,width=7.):
    _sheet(layer,points,[max(1.,width*(1-i/(len(points)+1)))*scale for i in range(len(points))],colors)
    # A few buds hug the solid vine, rather than replacing it with a leaf fan.
    painter=ImageDraw.Draw(layer)
    for i in range(3,len(points)-1,4):
        x,y=points[i]
        r=5*scale
        painter.polygon(((round(x),round(y)),(round(x-r),round(y-r)),
                         (round(x-r*1.4),round(y+1)),(round(x),round(y+r*.5))),fill=colors[1])
        R.line(layer,((x-r,y-r),(x,y)),colors[3],3)


def _material_debris(layer,key,a,b,elapsed,colors,scale,density):
    """Low hard chips, curling metal glints, sticky drops or floating leaves."""
    if not 0<=elapsed<LIFETIME:
        return
    count=max(3,round((7 if key in ('rock_spikes','crag_citadel') else 5)*density))
    painter=ImageDraw.Draw(layer)
    for i in range(count):
        age=elapsed-i*.011
        duration=.58+(i%3)*.045
        if not 0<=age<duration:
            continue
        p=age/duration
        side=-1 if i%2 else 1
        if key=='root_domain':
            angle=i*1.9+p*2.8
            at=(b[0]+math.cos(angle)*(15+p*25)*scale,
                b[1]+(15-p*30+math.sin(angle)*11)*scale)
            x,y=(round(v/3)*3 for v in at)
            w=(4-i%2)*scale*(1-p*.45)
            painter.polygon(((x-w,y+3),(x-w*.4,y-w),(x+w,y-w*.4),(x+w*.5,y+3)),fill=colors[2])
            R.line(layer,((x-w,y+3),(x+w,y-w*.4)),colors[3],3)
        elif key in ('iron_fault','cross_bullet','gale_cross'):
            at=(b[0]+side*(11+math.sin(p*math.pi*.7)*(20+i%3*6))*scale,
                b[1]+(6-p*21+p*p*34+(i%3-1)*8)*scale)
            x,y=(round(v/3)*3 for v in at)
            size=max(2.,(5-i%2)*(1-p*.55)*scale)
            painter.polygon(((x-size,y),(x,y-size),(x+size*1.3,y),(x,y+size*.6)),fill=colors[1])
            R.line(layer,((x-size*.4,y),(x+size,y-size*.5)),colors[3],3)
        elif key=='mud_anchor':
            at=(b[0]+side*(12+p*(24+i%3*8))*scale,
                b[1]+(17-age*30+age*age*93)*scale)
            x,y=(round(v/3)*3 for v in at)
            radius=max(2.,(5-i%2)*(1-p*.5)*scale)
            painter.ellipse((x-radius,y-radius*.6,x+radius,y+radius*.9),fill=colors[1])
            painter.ellipse((x-radius*.65,y-radius*.55,x+radius*.4,y),fill=colors[2])
        elif key=='spinning_cleanup':
            angle=i*2.4+p*3.6
            radius=(17+p*35)*scale
            at=(b[0]+math.cos(angle)*radius,b[1]+17*scale+math.sin(angle)*radius*.25)
            x,y=(round(v/3)*3 for v in at)
            painter.rectangle((x-3,y-2,x+2,y+2),fill=colors[1 if i%2 else 3])
        else:
            # Hard fragments follow a brief ballistic hop then slide low. Small
            # fist/wing impacts shed grit, not giant identical sparkling rays.
            at=(b[0]+side*(9+p*(23+i%3*7))*scale,
                b[1]+(18-math.sin(p*math.pi)*(15+i%3*5)+p*p*10)*scale)
            x,y=(round(v/3)*3 for v in at)
            size=max(2.,(5 if key in ('stone_pulse','rock_spikes','crag_citadel') and i%3==0 else 3)*(1-p*.5)*scale)
            painter.polygon(((x-size,y-size*.7),(x+size*.3,y-size),
                             (x+size,y+size*.4),(x-size*.4,y+size)),fill=colors[1])
            painter.polygon(((x-size,y-size*.7),(x+size*.3,y-size),(x,y)),fill=colors[3])

def _windup(layer,key,a,b,p,colors,scale,density,emitters):
    if key in ('venom_rush','horn_pressure'):
        _drill_stamp(layer,a,b,a,colors,scale*(.40+.50*p),p*1.4,key=='horn_pressure')
        return
    if key in ('four_arm_combo','cross_bullet'):
        count=4 if key=='four_arm_combo' else 2
        kind='fist' if count==4 else 'pincer'
        for i,origin in enumerate(tuple(emitters)[:count] or (a,)):
            _material_put(layer,kind,origin,colors,scale*(.23+p*.13),i)
        return
    if key in ('stone_pulse','rock_spikes','crag_citadel'):
        for i in range(3):
            pos=(a[0]+(i-1)*16*scale,a[1]+(20-p*(8+i*3))*scale)
            _material_put(layer,'rock',pos,colors,scale*(.22+p*.13+i%2*.05),i)
    elif key=='root_domain':
        for side in (-1,1):
            points=[(a[0]+side*(22-14*p*q)*scale,
                     a[1]+(25-14*p*q+math.sin(q*4)*3)*scale) for q in (0,.2,.4,.6,.8,1)]
            _vines(layer,points,colors,scale,5+p*2)
    elif key=='armor_pincer':
        for side in (-1,1):
            at=(a[0]+side*(20-p*5)*scale,a[1]-3*scale)
            _material_put(layer,'pincer',at,colors,scale*(.30+p*.12),turn=side*(35-p*20))
    elif key=='mud_anchor':
        for i in range(max(3,round(4*density))):
            pos=(a[0]+(i-1.5)*12*scale,a[1]+(15-p*9-i%2*4)*scale)
            _material_put(layer,'mud',pos,colors,scale*(.21+p*.13),i)
    elif key=='sweeping_kick':
        _crescent(layer,(a[0],a[1]+12*scale),colors,scale,p*2.0,rx=21,ry=7,width=5)
        _material_put(layer,'foot',(a[0]+8*p*scale,a[1]+14*scale),colors,
                      scale*(.20+p*.14),turn=35-p*45)
    elif key in ('gale_cross','cliff_swoop'):
        for side in (-1,1):
            _crescent(layer,(a[0]+side*(12-p*4)*scale,a[1]),colors,scale,
                      side*(1.0+p*.5),rx=19,ry=9,width=5)
    elif key in ('alert_tail','iron_fault'):
        kind='metal_tail' if key=='iron_fault' else 'tail'
        _material_put(layer,kind,(a[0]-10*p*scale,a[1]+10*scale),colors,
                      scale*(.27+p*.10),turn=-35+p*70)
    elif key=='spinning_cleanup':
        for i in range(2):
            _crescent(layer,a,colors,scale,p*math.tau*2+i*math.pi,
                      rx=25,ry=9,sweep=2.3,width=6)
    else:
        ux,uy,nx,ny=_basis(a,b)
        for side in (-1,1):
            begin=(a[0]-ux*(22+12*p)*scale+nx*side*8*scale,
                   a[1]-uy*(22+12*p)*scale+ny*side*8*scale)
            end=(a[0]+nx*side*6*scale,a[1]+ny*side*6*scale)
            _sheet(layer,(begin,R.point(begin,end,.5),end),(2*scale,6*scale,2*scale),colors)


def _flight(layer,key,a,b,p,colors,scale,density,emitters):
    if key in ('venom_rush','horn_pressure'):
        _drill_travel(layer,key,a,b,p,colors,scale)
        return
    if key in ('four_arm_combo','cross_bullet'):
        count=4 if key=='four_arm_combo' else 2
        kind='fist' if count==4 else 'pincer'
        origins=tuple(emitters)[:count] or (a,)
        for i,origin in enumerate(origins):
            delay=i*.055
            local=min(1.,max(0.,(p-delay)/(1-delay)))
            q=_trail(layer,origin,b,local,colors,scale,3,
                     bend=(i-(len(origins)-1)/2)*5*scale)
            angle=-math.degrees(math.atan2(b[1]-origin[1],b[0]-origin[0]))
            _material_put(layer,kind,q,colors,scale*(.52 if count==4 else .60),i,turn=angle)
        return
    if key in ('rock_spikes','crag_citadel'):
        count=3 if key=='rock_spikes' else 4
        for i in range(count):
            delay=i*.055
            local=min(1.,max(0.,(p-delay)/(1-delay)))
            q=_head(a,b,local,-(24+i*8)*scale,(i-(count-1)/2)*12*scale)
            _material_put(layer,'rock',q,colors,scale*(.39+(i%3)*.12),i,turn=p*(35+i*12))
        return
    if key=='mud_anchor':
        for i in range(max(3,round(5*density))):
            delay=i*.035
            local=min(1.,max(0.,(p-delay)/(1-delay)))
            q=_head(a,b,local,10*scale,(i-2)*12*scale)
            _material_put(layer,'mud',q,colors,scale*(.31+i%3*.09),i,turn=local*(20+i*7))
        return
    if key=='root_domain':
        ux,uy,nx,ny=_basis(a,b)
        for side in (-1,1):
            points=[]
            for i in range(17):
                local=p*i/16
                q=R.point(a,b,local)
                sway=math.sin(local*math.tau*1.25+side*.7)*6*scale*math.sin(math.pi*local)
                points.append((q[0]+nx*sway,q[1]+ny*sway))
            _vines(layer,points,colors,scale,8.)
        return
    if key=='stone_pulse':
        # A filled fault travels along the floor; it does not become a levitating
        # rock laser. The head reaches the recorded victim exactly at p=1.
        points=[]
        for i in range(11):
            local=max(0.,p-.32)+min(p,.32)*i/10
            at=R.point(a,b,local)
            points.append((at[0]+math.sin(i*2.1)*3*scale,at[1]+20*scale))
        _sheet(layer,points,[max(2.,7*math.sin((i+1)*math.pi/12))*scale for i in range(11)],colors,bright=False)
        return
    bends={'sweeping_kick':13,'cliff_swoop':-30,'alert_tail':17,'iron_fault':-11}
    q=_head(a,b,p,bends.get(key,0)*scale)
    if key=='sweeping_kick':
        low=(q[0],q[1]+11*scale)
        _crescent(layer,low,colors,scale,math.pi*.65+p*2.0,rx=27,ry=9,width=9)
        _material_put(layer,'foot',q,colors,scale*.53,turn=65-p*95)
    elif key=='armor_pincer':
        for side in (-1,1):
            spread=(21*math.sin(math.pi*p)+4)*scale
            center=(q[0]+side*spread,q[1])
            _material_put(layer,'pincer',center,colors,scale*.55,turn=side*(35-30*p))
    elif key=='gale_cross':
        for i in range(3):
            local=max(0.,(p-i*.055)/(1-i*.055))
            at=_head(a,b,local,0,(i-1)*12*scale)
            _crescent(layer,at,colors,scale,math.pi*.75+(i-1)*.22,
                      rx=24+i%2*4,ry=14,width=8)
    elif key=='bull_rush':
        ux,uy,nx,ny=_basis(a,b)
        back=_head(a,b,max(0.,p-.19),7*scale)
        path=[_oriented(back,ux,uy,nx,ny,0,0,1),R.point(back,q,.45),q]
        _sheet(layer,path,[4*scale,13*scale,3*scale],colors)
        for side in (-1,1):
            _crescent(layer,(q[0]+side*9*scale,q[1]+14*scale),colors,scale,
                      p*2+side,rx=11,ry=5,width=4,bright=False)
    elif key=='cliff_swoop':
        for side in (-1,1):
            _crescent(layer,(q[0]+side*14*scale,q[1]),colors,scale,
                      side*math.pi*.65,rx=26,ry=11,width=10)
    elif key in ('alert_tail','iron_fault'):
        kind='metal_tail' if key=='iron_fault' else 'tail'
        _crescent(layer,q,colors,scale,-1.3+p*.8,rx=29,ry=13,width=10)
        _material_put(layer,kind,q,colors,scale*.45,turn=30-p*70)
    elif key=='spinning_cleanup':
        for i in range(3):
            _crescent(layer,q,colors,scale,p*math.tau*2+i*math.tau/3,
                      rx=29,ry=11,sweep=1.65,width=7)


def _falling_rocks(layer,key,b,elapsed,colors,scale):
    count=3 if key=='stone_pulse' else 4 if key=='rock_spikes' else 6
    for i in range(count):
        fall=.07+(i%3)*.015
        age=elapsed-i*.024
        if i==0:
            age+=fall
        if age<0:
            continue
        landing=(b[0]+((i*17)%47-23)*scale,b[1]+(15+i%2*4)*scale)
        if age<fall:
            p=age/fall
            at=(landing[0]+math.sin(p*math.pi)*4*scale,
                landing[1]-(1-p*p)*(36+i%3*7)*scale)
        elif age<fall+.09:
            p=(age-fall)/.09
            at=(landing[0]+(p-.4)*i*3*scale,
                landing[1]-math.sin(p*math.pi)*(9+i%2*3)*scale)
        else:
            continue
        _material_put(layer,'rock',at,colors,scale*(.40+i%3*.10)*(1-max(0.,age-fall)*3),i,turn=i*20+age*150)
    if key in ('stone_pulse','rock_spikes'):
        _ground_fault(layer,b,colors,elapsed,scale)
    if key=='crag_citadel' and elapsed<.26:
        for i in range(2):
            _crescent(layer,(b[0]+(i-.5)*18*scale,b[1]+23*scale),colors,scale,
                      math.pi+elapsed*7+i,rx=29+elapsed*30,ry=6,sweep=2.4,width=5,bright=False)


def _contact(layer,key,a,b,elapsed,colors,scale):
    angle=math.atan2(b[1]-a[1],b[0]-a[0])
    if key in ('venom_rush','horn_pressure'):
        _drill_contact(layer,key,a,b,elapsed,colors,scale)
    elif key=='four_arm_combo':
        for i,(dx,dy) in enumerate(((-12,-9),(12,-6),(-11,10),(11,12))):
            age=elapsed-i*.036
            if 0<=age<.088:
                pos=(b[0]+dx*scale,b[1]+dy*scale)
                _material_put(layer,'fist',pos,colors,scale*(.52-age*2.4),i,turn=-math.degrees(angle))
                _compression(layer,a,pos,colors,elapsed,scale,delay=i*.036,duration=.077,radius=17)
                _flash(layer,pos,colors,elapsed,scale,i*.036,.042,.41)
    elif key=='cross_bullet':
        for i in range(2):
            pos=(b[0]+(-8 if i==0 else 8)*scale,b[1])
            _blade_cut(layer,pos,colors,elapsed,scale,-.72 if i==0 else .72,
                       i*.075,.14,48,10)
            age=elapsed-i*.075
            if 0<=age<.07:
                _material_put(layer,'pincer',pos,colors,scale*(.48-age*3),i,turn=(-35 if i==0 else 35))
            _compression(layer,a,pos,colors,elapsed,scale,delay=i*.075,duration=.072,radius=20)
    elif key in ('stone_pulse','rock_spikes','crag_citadel'):
        _falling_rocks(layer,key,b,elapsed,colors,scale)
        _flash(layer,(b[0],b[1]+15*scale),colors,elapsed,scale,duration=.06,size=.45)
    elif key=='sweeping_kick':
        low=(b[0],b[1]+14*scale)
        if elapsed<.14:
            _crescent(layer,low,colors,scale,math.pi+elapsed*9,rx=32,ry=10,width=11)
            _material_put(layer,'foot',low,colors,scale*(.47-elapsed*1.6),turn=-20+elapsed*300)
        _compression(layer,a,low,colors,elapsed,scale,duration=.115,radius=31)
    elif key=='root_domain':
        if elapsed<.31:
            q=elapsed/.31
            for side in (-1,1):
                points=[]
                for i in range(17):
                    t=i/16
                    swing=-1.35+side*t*2.2
                    radius=(28-12*q)*(1-t*.38)*scale
                    points.append((b[0]+math.cos(swing)*radius*side,
                                   b[1]+16*scale+math.sin(swing)*radius))
                _vines(layer,points,colors,scale,9*(1-q*.5))
    elif key=='armor_pincer':
        if elapsed<.16:
            spread=21*max(0.,1-elapsed/.07)
            for side in (-1,1):
                pos=(b[0]+side*spread*scale,b[1])
                _material_put(layer,'pincer',pos,colors,scale*(.54-elapsed*1.2),turn=side*(28-elapsed*180))
        _compression(layer,a,b,colors,elapsed,scale,delay=.045,duration=.095,radius=27)
        _flash(layer,b,colors,elapsed,scale,.045,.055,.54)
    elif key=='gale_cross':
        _blade_cut(layer,b,colors,elapsed,scale,-.76,duration=.145,length=62,width=11)
        _blade_cut(layer,b,colors,elapsed,scale,.76,.045,.145,58,10)
    elif key=='bull_rush':
        _compression(layer,a,b,colors,elapsed,scale,duration=.145,radius=43)
        _flash(layer,b,colors,elapsed,scale,duration=.065,size=.67)
        if elapsed<.19:
            _crescent(layer,(b[0],b[1]+20*scale),colors,scale,math.pi+elapsed*5,
                      rx=25+elapsed*45,ry=7,width=6,bright=False)
    elif key=='cliff_swoop':
        for side in (-1,1):
            pos=(b[0]+side*15*scale,b[1])
            age=elapsed-(.018 if side>0 else 0)
            if 0<=age<.16:
                _crescent(layer,pos,colors,scale,side*(1.0+age*4),rx=26,ry=14,width=10*(1-age*3))
            _flash(layer,pos,colors,elapsed,scale,0 if side<0 else .018,.055,.5)
        if .07<=elapsed<.22:
            _material_put(layer,'rock',(b[0]-10*scale,b[1]+18*scale),colors,scale*(.33-elapsed*.7),turn=elapsed*140)
    elif key in ('alert_tail','iron_fault'):
        kind='metal_tail' if key=='iron_fault' else 'tail'
        if elapsed<.17:
            _crescent(layer,(b[0],b[1]+9*scale),colors,scale,
                      -.7+elapsed*8,rx=34,ry=14,width=12*(1-elapsed*2.7))
            _material_put(layer,kind,b,colors,scale*(.48-elapsed*1.5),turn=-35+elapsed*400)
        _compression(layer,a,b,colors,elapsed,scale,duration=.10,
                     radius=28 if key=='alert_tail' else 34)
        if key=='iron_fault':
            _ground_fault(layer,b,colors,elapsed*.95,scale*.71)
    elif key=='mud_anchor':
        _mud_cup(layer,b,colors,elapsed,scale)
    elif key=='spinning_cleanup':
        if elapsed<.205:
            for i in range(3):
                _crescent(layer,b,colors,scale,i*math.tau/3+elapsed*21,
                          rx=31,ry=13,sweep=1.55,width=7*(1-elapsed*2))
        _flash(layer,b,colors,elapsed,scale,duration=.052,size=.47)

def draw(layer,skill_id,source,target,phase,progress,config,*,emitters=(),secondary=False):
    """Return ownership; draw bounded, seekable art without changing replay facts."""
    if skill_id not in _ELEMENTS:
        return False
    if phase not in ('windup','flight','impact','aftermath'):
        return True
    p=float(progress)
    p=min(1.,max(0.,p)) if math.isfinite(p) else 0.
    if (secondary and phase in ('windup','flight')) or (phase=='aftermath' and p>=1.):
        return True
    scale,density=R.settings(config)
    colors=R.palette(_PALETTE_MATERIAL.get(skill_id,_ELEMENTS[skill_id]),config)
    if phase=='windup':
        _windup(layer,skill_id,source,target,p,colors,scale,density,emitters)
    elif phase=='flight':
        _flight(layer,skill_id,source,target,p,colors,scale,density,emitters)
    else:
        # One physical clock across impact and aftermath: no restarted pose,
        # falling trajectory, stamp sequence or particle burst at +.22 seconds.
        elapsed=p*CONTACT if phase=='impact' else CONTACT+p*(LIFETIME-CONTACT)
        local=scale*(.61 if secondary else 1.)
        _contact(layer,skill_id,source,target,elapsed,colors,local)
        if skill_id in ('venom_rush','horn_pressure'):
            _drill_chips(layer,skill_id,source,target,elapsed,colors,local,density)
        else:
            _material_debris(layer,skill_id,source,target,elapsed,colors,local,density)
    return True
