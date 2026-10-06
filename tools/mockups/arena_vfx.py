"""Eighteen authored basic-attack tracks for the small arena roster.

The simulator remains authoritative. These bounded Pillow drawings consume only
an event's source, target and presentation phase, and never alter combat state.
"""
import math
from PIL import ImageDraw

WHITE = (255, 251, 225, 255)


def _ring(d, x, y, r, color, width=2):
    d.ellipse((x-r, y-r, x+r, y+r), outline=color, width=width)


def _star(d, x, y, r, color, points=5, angle=-math.pi/2):
    pts = [(x + math.cos(angle+i*math.pi/points)*r*(1 if i%2 == 0 else .42),
            y + math.sin(angle+i*math.pi/points)*r*(1 if i%2 == 0 else .42))
           for i in range(points*2)]
    d.polygon(pts, fill=color)


def _raichu(d, x, y, k, a, hit):
    # A forked bolt rather than the generic electric particle.
    r = 8 + k*5
    pts = [(x-r, y-3), (x-2,y-3), (x-5,y+2), (x+r,y+1), (x+2,y+6)]
    d.line(pts, fill=(255,211,53,255), width=4)
    d.line(pts, fill=WHITE, width=1)
    if hit:
        d.line((x,y,x-7,y-12), fill=(255,211,53,255), width=2)
        d.line((x,y,x+10,y+9), fill=(255,211,53,255), width=2)


def _machamp(d, x, y, k, a, hit):
    # Four fists, paired above and below the contact.
    for ox, oy in ((-7,-6),(5,-6),(-7,5),(5,5)):
        d.rounded_rectangle((x+ox-3,y+oy-3,x+ox+3,y+oy+3), radius=2,
                            fill=(239,157,89,255), outline=WHITE)
    if hit:
        d.arc((x-17,y-15,x+17,y+15), 205, 340, fill=(232,114,66,255), width=3)


def _nidoqueen(d, x, y, k, a, hit):
    # An armoured ground shock, three upward blue plates.
    r = 8+k*5
    for i in (-1,0,1):
        xx = x+i*7
        d.polygon(((xx-4,y+5),(xx,y-r),(xx+4,y+5)), fill=(91,172,215,255), outline=WHITE)
    if hit:
        d.arc((x-18,y-9,x+18,y+13), 0, 180, fill=(130,213,240,255), width=2)


def _golem(d, x, y, k, a, hit):
    # A tumbling faceted boulder, then stone chips.
    r = 8+k*3
    pts = [(x+math.cos(i*math.pi/3+a)*r,y+math.sin(i*math.pi/3+a)*r) for i in range(6)]
    d.polygon(pts, fill=(142,116,84,255), outline=(242,213,167,255))
    d.line((pts[0],(x,y),pts[2]), fill=(70,65,65,255), width=2)
    if hit:
        for i in range(4):
            xx,yy=x+(i-1.5)*8,y-10-abs(i-1.5)*3
            d.rectangle((xx,yy,xx+3,yy+3),fill=(207,183,136,255))


def _wigglytuff(d, x, y, k, a, hit):
    # Two musical notes; the hit spreads as a sound wave.
    for ox,oy in ((-5,3),(5,-4)):
        d.ellipse((x+ox-4,y+oy-2,x+ox+2,y+oy+2),fill=(255,146,201,255))
        d.line((x+ox+2,y+oy,x+ox+2,y+oy-10,x+ox+7,y+oy-8),fill=WHITE,width=2)
    if hit:
        d.arc((x-18,y-18,x+18,y+18), 240, 60, fill=(255,166,213,255), width=2)


def _butterfree(d, x, y, k, a, hit):
    # Crossed translucent-looking wing motes and a powder cloud.
    for ox,oy in ((-6,-4),(6,-4),(-4,4),(4,4)):
        d.ellipse((x+ox-3,y+oy-4,x+ox+3,y+oy+4),fill=(204,175,241,220),outline=WHITE)
    d.line((x,y-6,x,y+6),fill=(96,89,172,255),width=2)
    if hit:
        for i in range(6):
            ang=i*math.tau/6
            xx,yy=x+math.cos(ang)*16,y+math.sin(ang)*12
            d.ellipse((xx-2,yy-2,xx+2,yy+2),fill=(234,203,253,255))


def _nidoking(d, x, y, k, a, hit):
    # Purple horn lance; a serrated puncture on contact.
    r=12+k*4
    d.polygon(((x-r,y+5),(x+r,y),(x-r,y-5),(x-r/2,y)),fill=(164,94,211,255),outline=WHITE)
    if hit:
        for i in (-1,0,1):
            d.line((x-12,y+i*6,x+12,y+i*6-4),fill=(210,149,248,255),width=2)


def _gengar(d, x, y, k, a, hit):
    # A dark orb with two eyes, broken by crescent wisps.
    r=9+k*4
    d.ellipse((x-r,y-r,x+r,y+r),fill=(59,30,100,240),outline=(189,116,253,255),width=2)
    d.polygon(((x-5,y-3),(x-1,y-1),(x-5,y+1)),fill=(255,98,159,255))
    d.polygon(((x+5,y-3),(x+1,y-1),(x+5,y+1)),fill=(255,98,159,255))
    if hit:
        d.arc((x-17,y-17,x+17,y+17),45,230,fill=(178,94,249,255),width=3)


def _arcanine(d, x, y, k, a, hit):
    # Three warm claw trails, not Charizard's fire.
    for i in (-1,0,1):
        d.line((x-13,y+i*6+5,x+12,y+i*6-4),fill=(255,177,82,255),width=3)
        d.line((x-8,y+i*6+3,x+12,y+i*6-4),fill=WHITE,width=1)
    if hit:
        d.arc((x-18,y-14,x+18,y+14),190,335,fill=(251,93,40,255),width=2)


def _tentacruel(d, x, y, k, a, hit):
    # Twin curling tentacles with a red poison bead.
    for sign in (-1,1):
        pts=[(x-12+i*3,y+sign*(4+math.sin(i*.65+k*3)*5)) for i in range(9)]
        d.line(pts,fill=(92,192,218,255),width=2)
    d.ellipse((x+7,y-4,x+14,y+3),fill=(234,66,112,255),outline=WHITE)
    if hit:
        _ring(d,x,y,16,(177,116,224,255))


def _clefable(d, x, y, k, a, hit):
    # Orbiting fairy stars, five points and pink tails.
    _star(d,x,y,9+k*3,(255,197,219,255))
    for i in range(3):
        ang=a+i*math.tau/3
        _star(d,x+math.cos(ang)*17,y+math.sin(ang)*11,3,(255,224,126,255))


def _vileplume(d, x, y, k, a, hit):
    # Five red petals around a pollen centre.
    for i in range(5):
        ang=i*math.tau/5+a
        xx,yy=x+math.cos(ang)*7,y+math.sin(ang)*7
        d.ellipse((xx-5,yy-5,xx+5,yy+5),fill=(232,93,116,255),outline=(255,180,179,255))
    d.ellipse((x-3,y-3,x+3,y+3),fill=(255,227,94,255))
    if hit:
        _ring(d,x,y,18,(248,176,132,255),1)


def _charizard(d, x, y, k, a, hit):
    # A tapered flame with a white core and detached embers.
    d.polygon(((x-14,y+5),(x-8,y-7),(x-3,y-3),(x+8,y-12),(x+14,y+1),(x+6,y+8)),
              fill=(254,104,38,255),outline=(255,197,65,255))
    d.polygon(((x-6,y+4),(x+7,y-5),(x+6,y+5)),fill=WHITE)
    if hit:
        for i in range(3):
            d.rectangle((x-12+i*10,y-18-i%2*5,x-10+i*10,y-15-i%2*5),fill=(255,196,69,255))


def _alakazam(d, x, y, k, a, hit):
    # Nested psychic diamonds, plus the twin spoon arcs.
    for r,c in ((12+k*4,(244,132,239,255)),(6,(255,227,139,255))):
        d.line(((x,y-r),(x+r,y),(x,y+r),(x-r,y),(x,y-r)),fill=c,width=2)
    for sign in (-1,1):
        d.arc((x+sign*16-4,y-8,x+sign*16+4,y+8),60,300,fill=WHITE,width=2)


def _blastoise(d, x, y, k, a, hit):
    # Two parallel cannon bolts and a radial splash.
    for sign in (-1,1):
        d.line((x-13,y+sign*5,x+12,y+sign*5),fill=(74,189,249,255),width=4)
        d.line((x-9,y+sign*5,x+12,y+sign*5),fill=WHITE,width=1)
    if hit:
        for i in range(6):
            ang=i*math.tau/6
            d.line((x+math.cos(ang)*10,y+math.sin(ang)*10,
                    x+math.cos(ang)*19,y+math.sin(ang)*19),fill=(102,212,255,255),width=2)


def _slowbro(d, x, y, k, a, hit):
    # Three staggered bubbles with persistent circular ripples.
    for ox,oy,r in ((-9,3,4),(0,-3,6),(10,2,4)):
        d.ellipse((x+ox-r,y+oy-r,x+ox+r,y+oy+r),fill=(130,201,252,150),outline=(205,239,255,255),width=2)
    if hit:
        d.ellipse((x-18,y+6,x+18,y+16),outline=(141,220,255,255),width=2)


def _venusaur(d, x, y, k, a, hit):
    # Two interlaced vines, sharp paired leaves on the leading end.
    for sign in (-1,1):
        pts=[(x-15+i*3,y+math.sin(i*.6+k)*sign*5) for i in range(11)]
        d.line(pts,fill=(83,188,104,255),width=2)
    d.polygon(((x+2,y),(x+8,y-10),(x+13,y-7)),fill=(151,237,120,255),outline=WHITE)
    d.polygon(((x+2,y),(x+8,y+10),(x+13,y+7)),fill=(151,237,120,255),outline=WHITE)
    if hit:
        d.arc((x-18,y-18,x+18,y+18),25,285,fill=(111,216,140,255),width=2)


def _starmie(d, x, y, k, a, hit):
    # An eight-point rotating star blade, ruby core.
    _star(d,x,y,12+k*3,(168,135,237,255),points=8,angle=a)
    _star(d,x,y,8,(247,216,122,255),points=4,angle=-a)
    d.ellipse((x-3,y-3,x+3,y+3),fill=(236,74,119,255),outline=WHITE)


EFFECTS = {
    26: ('交叉电弧', _raichu), 68: ('四臂连拳', _machamp),
    31: ('甲壳震波', _nidoqueen), 76: ('滚石碎击', _golem),
    40: ('音符脉冲', _wigglytuff), 12: ('蝶翼鳞粉', _butterfree),
    34: ('毒角穿刺', _nidoking), 94: ('幽影鬼火', _gengar),
    59: ('焰爪三连', _arcanine), 73: ('毒触缠绕', _tentacruel),
    36: ('星屑环绕', _clefable), 45: ('花瓣孢击', _vileplume),
    6: ('灼热火舌', _charizard), 65: ('念力棱镜', _alakazam),
    9: ('双管水炮', _blastoise), 80: ('泡沫涟漪', _slowbro),
    3: ('双藤飞叶', _venusaur), 121: ('旋转星刃', _starmie),
}


def draw_attack(image, species_id, source, target, phase, progress, team=0):
    """Draw an individual attack plus a legible source-to-target guide."""
    if species_id not in EFFECTS:
        raise ValueError('no arena attack effect for species')
    if phase not in ('windup', 'flight', 'impact', 'aftermath'):
        raise ValueError('unknown attack phase')
    p = min(1., max(0., progress))
    d = ImageDraw.Draw(image)
    ax,ay=source
    bx,by=target
    color=(77,180,255,220) if team == 0 else (255,104,114,220)
    dx,dy=bx-ax,by-ay
    norm=math.hypot(dx,dy) or 1.
    # Thin, dotted guide persists through contact. Faction markers use shape.
    if phase != 'aftermath':
        for i in range(0,12,2):
            d.line((ax+dx*i/12,ay+dy*i/12,ax+dx*(i+1)/12,ay+dy*(i+1)/12),fill=color,width=1)
        tip=(bx-dx/norm*7,by-dy/norm*7)
        d.line(((tip[0]+dy/norm*3,tip[1]-dx/norm*3),(bx,by),
                (tip[0]-dy/norm*3,tip[1]+dx/norm*3)),fill=color,width=2)
    if team == 0:
        _ring(d,ax,ay,6,color,1)
    else:
        d.line(((ax,ay-6),(ax+6,ay+5),(ax-6,ay+5),(ax,ay-6)),fill=color,width=1)
    angle=math.atan2(dy,dx)+p*2
    if phase == 'windup':
        x,y=ax,ay
        k=p*.3
    elif phase == 'flight':
        x,y=ax+dx*p,ay+dy*p
        if species_id in (40,12,36,45,80):
            y-=math.sin(p*math.pi)*12
        elif species_id in (94,65,121):
            x+=math.sin(p*math.tau)*dy/norm*5
            y-=math.sin(p*math.tau)*dx/norm*5
        k=.25
    else:
        x,y=bx,by
        k=p if phase == 'impact' else 1-p
        _ring(d,bx,by,13+p*5,color,1)
    EFFECTS[species_id][1](d,x,y,k,angle,phase in ('impact','aftermath'))


def draw_heal(image, source, target, progress):
    d=ImageDraw.Draw(image)
    p=min(1.,max(0.,progress))
    ax,ay=source
    bx,by=target
    color=(103,235,161,240)
    d.line((ax,ay,bx,by),fill=color,width=1)
    for k in (max(0.,p-.2),p,min(1.,p+.2)):
        x,y=ax+(bx-ax)*k,ay+(by-ay)*k
        d.line((x-3,y,x+3,y),fill=WHITE,width=2)
        d.line((x,y-3,x,y+3),fill=WHITE,width=2)
    _ring(d,bx,by,12+p*8,color,2)


ELEMENT_COLORS = {
    'FIRE': (255, 110, 41), 'WATER': (82, 195, 251), 'ELECTRIC': (255, 222, 66),
    'GRASS': (130, 219, 80), 'POISON': (195, 112, 216), 'PSYCHIC': (255, 139, 213),
    'ICE': (161, 243, 255), 'GROUND': (210, 168, 103), 'ROCK': (174, 150, 119),
    'FIGHTING': (244, 166, 105), 'NORMAL': (247, 226, 167), 'BUG': (186, 211, 81),
    'FLYING': (184, 221, 251), 'GHOST': (150, 126, 235), 'DRAGON': (132, 166, 255),
    'STEEL': (205, 229, 239), 'DARK': (126, 121, 169),
}


def draw_skill(image, species_id, move_type, source, target, phase, progress, team=0, move_name=''):
    """Actual move material with a readable charge, route, contact and residue."""
    if phase not in ('windup', 'flight', 'impact', 'aftermath'):
        raise ValueError('unknown skill phase')
    p = min(1., max(0., progress))
    ax, ay = source
    bx, by = target
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy) or 1.
    nx, ny = -dy / length, dx / length
    fade = 1 - p if phase == 'aftermath' else 1.
    color = (*ELEMENT_COLORS.get(move_type, ELEMENT_COLORS['NORMAL']), round(240 * fade))
    white = (255, 252, 231, round(245 * fade))
    d = ImageDraw.Draw(image)
    k = p if phase == 'flight' else 0. if phase == 'windup' else 1.
    x, y = ax + dx * k, ay + dy * k
    radius = 7 + (p * 6 if phase == 'windup' else p * 14 if phase == 'impact' else 3)
    variant = species_id % 4
    travel = phase == 'flight'
    hit = phase in ('impact', 'aftermath')
    if phase == 'windup':
        _ring(d, ax, ay, radius + 3, color, 1)
        for i in range(3):
            angle = i * math.tau / 3 + p * 3
            d.rectangle((ax + math.cos(angle) * radius - 1, ay + math.sin(angle) * radius - 1,
                         ax + math.cos(angle) * radius + 1, ay + math.sin(angle) * radius + 1), fill=white)
    points = [(ax + dx * j / 12 * k + nx * math.sin(j * 1.7 + p * 7) * 3,
               ay + dy * j / 12 * k + ny * math.sin(j * 1.7 + p * 7) * 3) for j in range(13)]
    if move_type == 'FIRE':
        if travel:
            d.line(points, fill=color, width=5)
        for i in range(5 if hit else 3):
            angle = i * 1.9 + p * 5 + variant
            xx, yy = x + math.cos(angle) * radius * .6, y + math.sin(angle) * radius * .6
            d.polygon(((xx - 5, yy + 5), (xx - 2, yy - 3), (xx + 3, yy - 11),
                       (xx + 6, yy + 4), (xx, yy + 8)), fill=color)
            d.polygon(((xx - 2, yy + 4), (xx + 2, yy - 4), (xx + 3, yy + 5)), fill=white)
        if hit:
            for i in range(7):
                angle = i * math.tau / 7
                xx, yy = bx + math.cos(angle) * radius, by + math.sin(angle) * radius - p * 9
                d.rectangle((xx, yy, xx + 2, yy + 2), fill=color)
    elif move_type == 'WATER':
        if travel:
            for off in (-3, 0, 3):
                d.line([(xx + nx * off, yy + ny * off) for xx, yy in points], fill=color, width=2)
        for i in range(3):
            r = radius + i * 4
            d.ellipse((x - r, y - r * .45, x + r, y + r * .45), outline=color, width=2)
        for i in range(6):
            angle = i * math.tau / 6 + p
            xx, yy = x + math.cos(angle) * radius, y + math.sin(angle) * radius * .8
            d.ellipse((xx - 2, yy - 3, xx + 2, yy + 2), fill=color, outline=white)
    elif move_type == 'ELECTRIC':
        route = points if travel else [(x - radius, y), (x - 3, y - 8), (x + 1, y + 5), (x + radius, y - 3)]
        d.line(route, fill=color, width=4)
        d.line(route, fill=white, width=1)
        for i in range(4):
            angle = i * math.pi / 2 + variant * .3
            tip = (x + math.cos(angle) * (radius + 8), y + math.sin(angle) * (radius + 8))
            d.line(((x, y), (x + math.cos(angle + .4) * 8, y + math.sin(angle + .4) * 8), tip), fill=color, width=2)
    elif move_type == 'GRASS':
        if travel:
            d.line(points, fill=(81, 142, 66, 240), width=2)
        for i in range(5):
            angle = i * math.tau / 5 + p * 3
            xx, yy = x + math.cos(angle) * radius * .7, y + math.sin(angle) * radius * .7
            d.polygon(((xx - 6, yy + 2), (xx - 2, yy - 5), (xx + 6, yy - 3), (xx + 2, yy + 4)), fill=color, outline=white)
            d.line((xx - 4, yy + 1, xx + 4, yy - 2), fill=(62, 128, 50, round(240 * fade)), width=1)
    elif move_type in ('POISON', 'GHOST', 'DARK'):
        for i in range(5):
            angle = i * 1.7 + p * 2
            xx, yy = x + math.cos(angle) * radius * .7, y + math.sin(angle) * radius * .6
            r = 3 + i % 3
            d.ellipse((xx - r, yy - r, xx + r, yy + r), fill=(*color[:3], round(120 * fade)), outline=color)
        if move_type == 'POISON':
            for i in range(4):
                xx, yy = x + (i - 1.5) * 7, y + p * 9 + i % 2 * 3
                d.polygon(((xx, yy - 4), (xx - 2, yy + 2), (xx + 2, yy + 2)), fill=color)
        else:
            d.arc((x - radius, y - radius, x + radius, y + radius), 20, 280, fill=color, width=3)
            d.line((x - 5, y - 3, x - 2, y - 1), fill=white, width=2)
            d.line((x + 5, y - 3, x + 2, y - 1), fill=white, width=2)
    elif move_type == 'PSYCHIC':
        for i in range(3):
            r = radius + i * 4
            d.ellipse((x - r, y - r * .5, x + r, y + r * .5), outline=color, width=1 + i % 2)
        _star(d, x, y, radius * .7, white, 4, p * 3)
    elif move_type in ('GROUND', 'ROCK'):
        if move_type == 'GROUND':
            d.line(points if travel else [(x - radius, y + 7), (x - 7, y), (x - 2, y + 4),
                                          (x + 5, y - 2), (x + radius, y + 6)], fill=(94, 73, 57, round(245 * fade)), width=3)
        else:
            poly = [(x + math.cos(i * math.pi / 3 + p) * 9, y + math.sin(i * math.pi / 3 + p) * 9) for i in range(6)]
            d.polygon(poly, fill=color, outline=white)
            d.line((poly[0], (x, y), poly[2]), fill=(94, 73, 57, round(240 * fade)), width=2)
        for i in range(6):
            xx = x + (i - 2.5) * 6
            yy = y - math.sin((i + 1) * .8) * (radius + 3)
            d.polygon(((xx, yy - 3), (xx + 3, yy + 2), (xx - 3, yy + 3)), fill=color)
    elif move_type == 'ICE':
        if travel:
            d.line((ax, ay, x, y), fill=color, width=2)
        for i in range(4 if hit else 2):
            angle = i * math.pi / 2 + p * .7
            xx, yy = x + math.cos(angle) * radius * .7, y + math.sin(angle) * radius * .7
            d.polygon(((xx, yy - 10), (xx + 4, yy), (xx, yy + 7), (xx - 4, yy)), fill=color, outline=white)
        if hit:
            for i in range(6):
                angle = i * math.pi / 3
                d.line((x, y, x + math.cos(angle) * radius, y + math.sin(angle) * radius), fill=white, width=1)
    elif move_type in ('FIGHTING', 'STEEL'):
        for i in range(3):
            off = (i - 1) * 6
            d.arc((x - radius + off, y - radius, x + radius + off, y + radius), 215, 340, fill=color, width=3)
        d.line((x - 9, y + 9, x + 10, y - 10), fill=white, width=2)
        if move_type == 'STEEL':
            d.line((x - 9, y - 9, x + 10, y + 10), fill=color, width=2)
        else:
            _star(d, x, y, radius * .6, color, 6, p)
    elif move_type in ('FLYING', 'BUG', 'DRAGON'):
        for i in range(4):
            off = (i - 1.5) * 6
            if move_type == 'FLYING':
                d.arc((x - radius, y + off - 5, x + radius, y + off + 8), 170, 345, fill=color, width=2)
            elif move_type == 'BUG':
                d.polygon(((x, y + off), (x - 10, y + off - 7), (x - 5, y + off + 5)), fill=color, outline=white)
                d.polygon(((x, y + off), (x + 10, y + off - 7), (x + 5, y + off + 5)), fill=color, outline=white)
            else:
                _star(d, x + off, y + math.sin(p * 5 + i) * 6, 6 + i % 2 * 3, color, 4, p + i)
    else:
        for i in range(3):
            _ring(d, x, y, radius + i * 4, color, 1)
        _star(d, x, y, radius * .45, white, 5, p)
