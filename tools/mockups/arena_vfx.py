"""Forty-eight authored basic-attack tracks for the arena roster.

The simulator remains authoritative. These bounded Pillow drawings consume only
an event's source, target and presentation phase, and never alter combat state.
"""
import math
from PIL import ImageDraw
from items import FINISHED
import arena_traits

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


def _expansion_motif(sid, d, x, y, k, angle, hit):
    """Species-specific geometry shared by its basic and stronger native track."""
    r = 8 + k * 8
    if sid == 95:
        for i in (-1, 0, 1):
            xx = x + i * 10
            d.polygon(((xx-5,y+7),(xx-2,y-r-abs(i)*3),(xx+6,y+7)), fill=(187,155,116,245), outline=WHITE)
            d.line((xx-2,y-r,xx+1,y+5), fill=(103,84,69,255), width=2)
    elif sid == 106:
        d.line(((x-r,y+8),(x,y-3),(x+r,y-3),(x+r+3,y+4),(x+1,y+4)), fill=(227,141,86,255), width=6)
        d.arc((x-21,y-20,x+20,y+15), 200, 330, fill=WHITE, width=2)
    elif sid == 108:
        route = [(x-20+i*5,y+math.sin(i*.8+angle)*7) for i in range(9)]
        d.line(route, fill=(244,138,174,255), width=6)
        d.line(route, fill=(255,210,219,255), width=2)
        _ring(d,x+20,y+math.sin(6.4+angle)*7,4,WHITE,1)
    elif sid == 113:
        d.ellipse((x-8,y-12,x+8,y+11), fill=(255,239,202,255), outline=(244,135,192,255), width=3)
        for off in (-16,16):
            d.line((x+off-3,y,x+off+3,y),fill=(131,235,175,255),width=2)
            d.line((x+off,y-3,x+off,y+3),fill=(131,235,175,255),width=2)
    elif sid == 114:
        for i in range(3):
            route=[(x-20+j*5,y+(i-1)*6+math.sin(j+angle+i)*5) for j in range(9)]
            d.line(route,fill=(86,197,131,255),width=3)
        for off in (-14,14):
            d.polygon(((x+off,y-14),(x+off+5,y-5),(x+off-4,y-7)),fill=(187,243,122,255))
    elif sid == 122:
        for i in range(3):
            off=i*4
            d.rectangle((x-11-off,y-13+off,x+11+off,y+13-off),outline=(118,218,242,245),width=2)
        _star(d,x,y,5,(244,157,203,255),4,angle)
    elif sid == 123:
        d.line((x-16,y-18,x+16,y+18),fill=(164,239,129,255),width=5)
        d.line((x+16,y-18,x-16,y+18),fill=WHITE,width=3)
        for off in (-14,14):
            d.arc((x-20+off,y-13,x+9+off,y+13),205,345,fill=(89,183,105,255),width=2)
    elif sid == 125:
        for off in (-10,10):
            d.line(((x+off,y-18),(x+off-6,y-4),(x+off+5,y-6),(x+off-2,y+17)),fill=(255,213,72,255),width=4)
        d.line((x-10,y,x+10,y),fill=WHITE,width=2)
        _ring(d,x,y,6+k*7,(244,175,55,255),2)
    elif sid == 127:
        d.arc((x-21,y-17,x+2,y+17),255,95,fill=(215,165,112,255),width=5)
        d.arc((x-2,y-17,x+21,y+17),85,285,fill=WHITE,width=3)
        for off in (-9,9):
            d.line((x+off,y-8,x,y),fill=(143,103,71,255),width=2)
    elif sid == 128:
        d.line(((x-18,y-12),(x-12,y+4),(x,y+10),(x+12,y+4),(x+18,y-12)),fill=(215,161,99,255),width=5)
        for off in (-22,22):
            d.line((x+off,y+10,x+off*.5,y+13),fill=WHITE,width=2)
    elif sid == 131:
        d.arc((x-23,y-9,x+23,y+15),180,355,fill=(100,215,243,255),width=3)
        for i in (-1,0,1):
            xx=x+i*12
            d.polygon(((xx,y-17-abs(i)*4),(xx+4,y-2),(xx,y+4),(xx-4,y-2)),fill=(178,238,251,255),outline=WHITE)
    elif sid == 142:
        d.polygon(((x-24,y-10),(x-6,y+7),(x,y-8),(x+6,y+7),(x+24,y-10),(x+11,y+14),(x-11,y+14)),fill=(172,154,189,255),outline=WHITE)
        for off in (-19,19):
            d.polygon(((x+off,y+17),(x+off+4,y+21),(x+off-3,y+22)),fill=(197,172,131,255))
    if hit:
        _ring(d,x,y,r+12,(255,237,190,190),1)


def _gen2_motif(sid, d, x, y, k, angle, hit):
    """Johto silhouettes: tails, quills, horns, jaws and steel plates."""
    r = 9 + k * 7
    if sid == 162:
        # A striped tail coils into a broad, cream-coloured dash ribbon.
        route = [(x - 19 + i * 4, y + math.sin(i * .62 + angle) * 7) for i in range(11)]
        d.line(route, fill=(193, 131, 82, 255), width=8)
        d.line(route, fill=(255, 226, 165, 255), width=4)
        for i in (2, 5, 8):
            xx, yy = route[i]
            d.line((xx - 1, yy - 3, xx + 2, yy + 3), fill=(124, 79, 57, 255), width=2)
        if hit:
            d.arc((x - 25, y - 16, x + 25, y + 16), 185, 340, fill=WHITE, width=2)
    elif sid == 211:
        # A quill wheel carries a toxic bead, with alternating long spikes.
        for i in range(8):
            a = angle * .25 + i * math.pi / 4
            tip = r + (7 if i % 2 else 11)
            d.polygon(((x + math.cos(a - .2) * 7, y + math.sin(a - .2) * 7),
                       (x + math.cos(a) * tip, y + math.sin(a) * tip),
                       (x + math.cos(a + .2) * 7, y + math.sin(a + .2) * 7)),
                      fill=(112, 187, 202, 255), outline=WHITE)
        d.ellipse((x - 8, y - 8, x + 8, y + 8), fill=(163, 104, 197, 255), outline=WHITE, width=2)
        d.ellipse((x - 3, y - 4, x + 1, y), fill=(235, 200, 248, 255))
    elif sid == 195:
        # Mud forms a blunt crest under three blue water lobes.
        mud = [(x - 23, y + 7), (x - 17, y), (x - 8, y + 4),
               (x - 2, y - 5), (x + 7, y + 1), (x + 18, y - 2), (x + 24, y + 10)]
        d.polygon(mud, fill=(161, 129, 91, 255), outline=(230, 202, 156, 255))
        for off in (-13, 0, 13):
            d.arc((x + off - 8, y - 12, x + off + 8, y + 7), 180, 345,
                  fill=(103, 207, 230, 255), width=4)
        if hit:
            d.ellipse((x - 27, y + 9, x + 27, y + 19), outline=(97, 174, 193, 255), width=2)
    elif sid == 237:
        # Three boot tips revolve around the inverted fighter's pivot.
        for i in range(3):
            a = angle + i * math.tau / 3
            ux, uy, nx, ny = math.cos(a), math.sin(a), -math.sin(a), math.cos(a)
            tip = (x + ux * (r + 10), y + uy * (r + 10))
            ankle = (x + ux * r, y + uy * r)
            d.line(((x, y), ankle, (tip[0] + nx * 4, tip[1] + ny * 4)),
                   fill=(206, 138, 91, 255), width=5)
            d.line((tip[0] - nx * 4, tip[1] - ny * 4, tip[0] + nx * 5, tip[1] + ny * 5),
                   fill=WHITE, width=3)
        _ring(d, x, y, 5, (134, 183, 208, 255), 2)
        if hit:
            d.arc((x - 28, y - 28, x + 28, y + 28), 20, 310, fill=WHITE, width=2)
    elif sid == 164:
        # Two watchful eyes and broad feather fans read as an owl wing beat.
        for sign in (-1, 1):
            for i in range(3):
                xx, yy = x + sign * (10 + i * 6), y + i * 3
                d.polygon(((x + sign * 5, y + 5), (xx, yy - 15), (xx + sign * 3, yy - 2)),
                          fill=(180, 143, 100, 255), outline=(250, 224, 176, 255))
            _ring(d, x + sign * 5, y - 3, 4, (247, 219, 99, 255), 2)
        d.polygon(((x - 2, y + 2), (x + 2, y + 2), (x, y + 7)), fill=WHITE)
        if hit:
            d.arc((x - 25, y - 23, x + 25, y + 23), 210, 330, fill=(202, 163, 235, 255), width=2)
    elif sid == 171:
        # An arched lure sends an electric pulse through a bubble current.
        d.line(((x - 15, y + 6), (x - 11, y - 8), (x + 3, y - 17), (x + 12, y - 12)),
               fill=(91, 194, 231, 255), width=3)
        d.ellipse((x + 7, y - 17, x + 17, y - 7), fill=(255, 225, 91, 255), outline=WHITE, width=2)
        for off in (-12, 0, 12):
            _ring(d, x + off, y + 7, 4 + k * 2, (124, 222, 246, 255), 2)
        d.line(((x - 12, y + 1), (x - 2, y - 2), (x - 5, y + 5), (x + 15, y + 1)),
               fill=(255, 220, 80, 255), width=2)
    elif sid == 181:
        # A red beacon discharges asymmetric branches inside a gold halo.
        _ring(d, x, y, r + 6, (255, 211, 72, 255), 2)
        d.ellipse((x - 5, y - 5, x + 5, y + 5), fill=(242, 110, 109, 255), outline=WHITE, width=2)
        for i in range(3):
            a = angle * .3 + i * math.tau / 3
            ux, uy, nx, ny = math.cos(a), math.sin(a), -math.sin(a), math.cos(a)
            d.line(((x + ux * 8, y + uy * 8),
                    (x + ux * 16 + nx * 5, y + uy * 16 + ny * 5),
                    (x + ux * 15 - nx * 2, y + uy * 15 - ny * 2),
                    (x + ux * 26, y + uy * 26)), fill=(255, 215, 92, 255), width=3)
        if hit:
            _ring(d, x, y, r + 12, WHITE, 1)
    elif sid == 196:
        # A forehead ruby focuses two narrow psychic crescents.
        d.polygon(((x, y - 8), (x + 5, y), (x, y + 8), (x - 5, y)),
                  fill=(238, 97, 156, 255), outline=WHITE)
        for sign in (-1, 1):
            d.arc((x - 22, y - 15 + sign * 5, x + 22, y + 15 + sign * 5),
                  200 if sign < 0 else 20, 340 if sign < 0 else 160,
                  fill=(207, 147, 237, 255), width=3)
        d.line(((x - 18, y + 14), (x - 4, y + 7), (x, y + 11), (x + 4, y + 7), (x + 18, y + 14)),
               fill=(251, 184, 227, 255), width=2)
        if hit:
            _star(d, x, y - 22, 4, WHITE, 4, angle)
    elif sid == 214:
        # A forked beetle horn and short wing shells make a heavy cleave.
        d.polygon(((x - 6, y + 16), (x - 5, y - 6), (x - 15, y - 16),
                   (x - 10, y - 23), (x, y - 13), (x + 10, y - 23),
                   (x + 15, y - 16), (x + 5, y - 6), (x + 6, y + 16)),
                  fill=(89, 152, 197, 255), outline=WHITE)
        for sign in (-1, 1):
            d.arc((x + sign * 13 - 7, y - 3, x + sign * 13 + 7, y + 17),
                  20, 310, fill=(177, 219, 123, 255), width=3)
        if hit:
            d.line((x - 22, y + 21, x, y + 13, x + 22, y + 21), fill=WHITE, width=2)
    elif sid == 197:
        # Golden oval rings cut into a solid ink crescent.
        d.polygon(((x - 19, y - 7), (x - 8, y - 19), (x + 13, y - 14),
                   (x + 3, y - 7), (x - 1, y + 8), (x + 17, y + 17),
                   (x - 9, y + 19), (x - 21, y + 6)),
                  fill=(62, 59, 88, 255), outline=(148, 133, 184, 255))
        for off in (-10, 10):
            d.ellipse((x + off - 4, y - 9, x + off + 4, y + 3),
                      outline=(252, 216, 99, 255), width=2)
        d.line((x - 4, y + 9, x + 4, y + 9), fill=(245, 104, 123, 255), width=2)
        if hit:
            d.arc((x - 27, y - 24, x + 27, y + 24), 35, 265, fill=(234, 203, 117, 255), width=2)
    elif sid == 208:
        # Riveted hexagonal links end in a pointed steel maw.
        for i in range(4):
            xx, yy = x - 19 + i * 10, y + math.sin(angle + i * .8) * 4
            plate = ((xx - 5, yy), (xx - 3, yy - 7), (xx + 4, yy - 5),
                     (xx + 6, yy + 1), (xx + 3, yy + 6), (xx - 4, yy + 5))
            d.polygon(plate, fill=(140 + i * 15, 169 + i * 12, 190 + i * 8, 255), outline=WHITE)
            d.line((xx - 2, yy - 3, xx + 2, yy + 2), fill=(78, 98, 120, 255), width=2)
        d.polygon(((x + 10, y - 11), (x + 27, y - 2), (x + 17, y + 10), (x + 12, y + 3)),
                  fill=(212, 233, 240, 255), outline=WHITE)
        if hit:
            d.line((x - 24, y + 16, x - 9, y + 11, x - 1, y + 19, x + 15, y + 14),
                   fill=(124, 158, 187, 255), width=3)
    elif sid == 242:
        # A heart cradles the healing egg; paired wings carry green pulses.
        pink = (255, 161, 199, 255)
        d.ellipse((x - 11, y - 12, x + 1, y), fill=pink, outline=WHITE)
        d.ellipse((x - 1, y - 12, x + 11, y), fill=pink, outline=WHITE)
        d.polygon(((x - 11, y - 4), (x + 11, y - 4), (x, y + 13)), fill=pink)
        d.ellipse((x - 5, y - 4, x + 5, y + 9), fill=(255, 241, 208, 255), outline=WHITE)
        for sign in (-1, 1):
            d.line(((x + sign * 12, y + 1), (x + sign * 24, y - 6),
                    (x + sign * 20, y + 8)), fill=(125, 233, 174, 255), width=3)
        if hit:
            d.line((x - 5, y - 20, x + 5, y - 20), fill=WHITE, width=3)
            d.line((x, y - 25, x, y - 15), fill=WHITE, width=3)
    elif sid == 157:
        # A five-toothed fire collar rises from a dark volcanic base.
        flame = []
        for i in range(5):
            xx = x - 20 + i * 10
            flame.extend(((xx - 5, y + 6), (xx - 2, y - 10 - (12 if i == 2 else 4)), (xx + 5, y + 6)))
        d.polygon(flame, fill=(249, 118, 52, 255), outline=(255, 225, 105, 255))
        d.arc((x - 25, y - 3, x + 25, y + 16), 0, 180, fill=(87, 85, 106, 255), width=5)
        d.line(((x - 10, y + 3), (x, y - 14), (x + 10, y + 3)), fill=WHITE, width=2)
        if hit:
            for off in (-23, 23):
                d.rectangle((x + off - 1, y - 20, x + off + 1, y - 16), fill=(255, 217, 85, 255))
    elif sid == 212:
        # Red pincer blades close over a bright steel seam.
        for sign in (-1, 1):
            d.polygon(((x + sign * 24, y - 11), (x + sign * 13, y - 16),
                       (x + sign * 4, y - 5), (x + sign * 13, y - 4),
                       (x + sign * 7, y + 7), (x + sign * 19, y + 15), (x + sign * 26, y + 5)),
                      fill=(224, 100, 103, 255), outline=(225, 238, 239, 255))
            _ring(d, x + sign * 17, y, 3, (70, 77, 96, 255), 2)
        d.line((x - 5, y + 17, x + 6, y - 18), fill=WHITE, width=3)
        if hit:
            d.line((x - 12, y - 20, x + 13, y + 20), fill=(179, 220, 232, 255), width=2)
    elif sid == 230:
        # Water coils about a dragon lance, with a curled crest at its tip.
        for sign in (-1, 1):
            route = [(x - 23 + i * 4, y + sign * math.sin(i * .65 + angle) * 8) for i in range(13)]
            d.line(route, fill=(110, 201, 244, 255) if sign < 0 else (162, 157, 245, 255), width=3)
        d.polygon(((x - 11, y - 3), (x + 17, y - 3), (x + 24, y),
                   (x + 17, y + 4), (x - 11, y + 4)), fill=(169, 222, 255, 255), outline=WHITE)
        d.arc((x + 13, y - 19, x + 26, y - 4), 120, 355, fill=(203, 190, 255, 255), width=2)
        if hit:
            _star(d, x - 18, y - 17, 5, WHITE, 4, angle)
    elif sid == 160:
        # A tidal jaw has two curved blue rails and staggered teeth.
        for sign in (-1, 1):
            d.arc((x - 23, y - 17 + sign * 5, x + 23, y + 17 + sign * 5),
                  190 if sign < 0 else 10, 350 if sign < 0 else 170,
                  fill=(88, 170, 224, 255), width=5)
            for i in (-1, 0, 1):
                xx, yy = x + i * 12, y + sign * (9 + abs(i) * 3)
                d.polygon(((xx - 4, yy), (xx + 4, yy), (xx, yy - sign * 7)), fill=WHITE)
        d.line((x - 7, y - 22, x, y - 16, x + 7, y - 22), fill=(238, 110, 106, 255), width=3)
        if hit:
            d.ellipse((x - 27, y + 16, x + 27, y + 25), outline=(139, 219, 247, 255), width=2)
    elif sid == 248:
        # A green, serrated monolith splits a black fissure and sand chips.
        d.polygon(((x - 17, y + 13), (x - 13, y - 2), (x - 19, y - 12),
                   (x - 5, y - 9), (x, y - 24), (x + 6, y - 10),
                   (x + 19, y - 15), (x + 14, y + 2), (x + 19, y + 14)),
                  fill=(151, 178, 104, 255), outline=(240, 224, 160, 255))
        d.line((x - 4, y - 9, x + 4, y - 1, x - 3, y + 5, x + 5, y + 13),
               fill=(66, 61, 84, 255), width=3)
        for i in (-1, 1):
            d.polygon(((x + i * 24, y + 7), (x + i * 19, y + 16), (x + i * 28, y + 17)),
                      fill=(216, 182, 115, 255), outline=WHITE)
        if hit:
            d.ellipse((x - 29, y + 15, x + 29, y + 24), outline=(188, 149, 101, 255), width=2)
    elif sid == 154:
        # Four broad petals surround a seed, framed by upward leaf shields.
        for ox, oy in ((-8, -4), (8, -4), (-8, 7), (8, 7)):
            d.ellipse((x + ox - 8, y + oy - 6, x + ox + 8, y + oy + 6),
                      fill=(247, 151, 189, 255), outline=(255, 231, 202, 255))
        d.ellipse((x - 5, y - 5, x + 5, y + 7), fill=(254, 229, 114, 255), outline=WHITE)
        for sign in (-1, 1):
            d.polygon(((x + sign * 14, y + 14), (x + sign * 26, y - 13),
                       (x + sign * 27, y + 8)), fill=(121, 206, 126, 255), outline=WHITE)
            d.line((x + sign * 17, y + 9, x + sign * 25, y - 8), fill=(64, 132, 89, 255), width=1)
        if hit:
            d.arc((x - 28, y - 24, x + 28, y + 24), 195, 345, fill=(186, 236, 137, 255), width=2)


def _authored(sid):
    return lambda d, x, y, k, angle, hit: _expansion_motif(sid,d,x,y,k,angle,hit)


EXPANSION_EFFECTS = {
    95: ('岩柱碎刺', _authored(95)), 106: ('飞踢弧光', _authored(106)),
    108: ('舌鞭旋卷', _authored(108)), 113: ('幸运蛋星', _authored(113)),
    114: ('藤根缠绕', _authored(114)), 122: ('镜面方阵', _authored(122)),
    123: ('交叉镰刃', _authored(123)), 125: ('双叉雷击', _authored(125)),
    127: ('双钳夹击', _authored(127)), 128: ('角阵冲撞', _authored(128)),
    131: ('冰晶浪纹', _authored(131)), 142: ('翼刃碎岩', _authored(142)),
}


def _gen2_authored(sid):
    return lambda d, x, y, k, angle, hit: _gen2_motif(sid, d, x, y, k, angle, hit)


GEN2_EFFECTS = {
    162: ('条纹尾旋', _gen2_authored(162)), 211: ('毒珠针轮', _gen2_authored(211)),
    195: ('泥浪水冠', _gen2_authored(195)), 237: ('倒立三旋踢', _gen2_authored(237)),
    164: ('夜枭羽扇', _gen2_authored(164)), 171: ('灯珠电泡', _gen2_authored(171)),
    181: ('红珠雷环', _gen2_authored(181)), 196: ('额晶念弧', _gen2_authored(196)),
    214: ('叉角重劈', _gen2_authored(214)), 197: ('月环暗影', _gen2_authored(197)),
    208: ('钢节裂颚', _gen2_authored(208)), 242: ('爱心蛋翼', _gen2_authored(242)),
    157: ('火领喷焰', _gen2_authored(157)), 212: ('赤钳钢刃', _gen2_authored(212)),
    230: ('龙旋水枪', _gen2_authored(230)), 160: ('潮牙咬合', _gen2_authored(160)),
    248: ('砂甲暗裂', _gen2_authored(248)), 154: ('花环叶盾', _gen2_authored(154)),
}


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
    **EXPANSION_EFFECTS,
    **GEN2_EFFECTS,
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
    rgb = ELEMENT_COLORS.get(move_type, ELEMENT_COLORS['NORMAL'])
    color = (*rgb, round(240 * fade))
    dark = (*tuple(round(c * .42) for c in rgb), round(235 * fade))
    white = (255, 252, 231, round(245 * fade))
    d = ImageDraw.Draw(image)
    k = p if phase == 'flight' else 0. if phase == 'windup' else 1.
    x, y = ax + dx * k, ay + dy * k
    radius = 7 + (p * 6 if phase == 'windup' else p * 14 if phase == 'impact' else 3)
    variant = species_id % 4
    travel = phase == 'flight'
    hit = phase in ('impact', 'aftermath')
    if phase == 'windup':
        _ring(d, ax, ay, radius + 3, dark, 3)
        _ring(d, ax, ay, radius + 3, color, 1)
        for i in range(3):
            angle = i * math.tau / 3 + p * 3
            d.rectangle((ax + math.cos(angle) * radius - 1, ay + math.sin(angle) * radius - 1,
                         ax + math.cos(angle) * radius + 1, ay + math.sin(angle) * radius + 1), fill=white)
        # Charge motes spiral into the source as the windup tightens.
        for i in range(4):
            angle = i * math.tau / 4 + variant * .8 - p * 4.5
            dist = (radius + 13) * (1 - p * .55)
            xx, yy = ax + math.cos(angle) * dist, ay + math.sin(angle) * dist * .8
            d.rectangle((xx - 1, yy - 1, xx + 1, yy + 1), fill=color if i % 2 else white)
    points = [(ax + dx * j / 12 * k + nx * math.sin(j * 1.7 + p * 7) * 3,
               ay + dy * j / 12 * k + ny * math.sin(j * 1.7 + p * 7) * 3) for j in range(13)]
    if travel:
        # Shared projectile volume under each element's own material: a fading
        # wake and a dark rim / main shell / bright core head.
        head = 5
        for j in range(3):
            kk = max(0., k - (j + 1) * .06)
            wx, wy = ax + dx * kk, ay + dy * kk
            wr = head - 1 - j
            if wr > 0:
                d.ellipse((wx - wr, wy - wr, wx + wr, wy + wr), fill=(*rgb, round(150 - 40 * j)))
        d.ellipse((x - head - 2, y - head - 2, x + head + 2, y + head + 2), fill=dark)
        d.ellipse((x - head, y - head, x + head, y + head), fill=color)
        ux, uy = dx / length, dy / length
        cx, cy = x + ux * 2, y + uy * 2
        d.ellipse((cx - 2, cy - 2, cx + 2, cy + 2), fill=white)
    if move_type == 'FIRE':
        if travel:
            d.line(points, fill=dark, width=8)
            d.line(points, fill=color, width=5)
            d.line(points, fill=white, width=2)
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
                d.line([(xx + nx * off, yy + ny * off) for xx, yy in points], fill=dark, width=4)
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
        d.line(route, fill=dark, width=7)
        d.line(route, fill=color, width=4)
        d.line(route, fill=white, width=1)
        for i in range(4):
            angle = i * math.pi / 2 + variant * .3
            tip = (x + math.cos(angle) * (radius + 8), y + math.sin(angle) * (radius + 8))
            d.line(((x, y), (x + math.cos(angle + .4) * 8, y + math.sin(angle + .4) * 8), tip), fill=color, width=2)
    elif move_type == 'GRASS':
        if travel:
            d.line(points, fill=(51, 92, 42, 240), width=5)
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
            route = points if travel else [(x - radius, y + 7), (x - 7, y), (x - 2, y + 4),
                                           (x + 5, y - 2), (x + radius, y + 6)]
            d.line(route, fill=dark, width=6)
            d.line(route, fill=(94, 73, 57, round(245 * fade)), width=3)
        else:
            poly = [(x + math.cos(i * math.pi / 3 + p) * 9, y + math.sin(i * math.pi / 3 + p) * 9) for i in range(6)]
            under = [(x + math.cos(i * math.pi / 3 + p) * 12, y + math.sin(i * math.pi / 3 + p) * 12) for i in range(6)]
            d.polygon(under, fill=dark)
            d.polygon(poly, fill=color, outline=white)
            d.line((poly[0], (x, y), poly[2]), fill=(94, 73, 57, round(240 * fade)), width=2)
        for i in range(6):
            xx = x + (i - 2.5) * 6
            yy = y - math.sin((i + 1) * .8) * (radius + 3)
            d.polygon(((xx, yy - 3), (xx + 3, yy + 2), (xx - 3, yy + 3)), fill=color)
    elif move_type == 'ICE':
        if travel:
            d.line((ax, ay, x, y), fill=dark, width=5)
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
            d.arc((x - radius + off, y - radius, x + radius + off, y + radius), 215, 340, fill=dark, width=6)
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
                d.arc((x - radius, y + off - 5, x + radius, y + off + 8), 170, 345, fill=dark, width=4)
                d.arc((x - radius, y + off - 5, x + radius, y + off + 8), 170, 345, fill=color, width=2)
            elif move_type == 'BUG':
                d.polygon(((x, y + off), (x - 10, y + off - 7), (x - 5, y + off + 5)), fill=color, outline=white)
                d.polygon(((x, y + off), (x + 10, y + off - 7), (x + 5, y + off + 5)), fill=color, outline=white)
            else:
                _star(d, x + off, y + math.sin(p * 5 + i) * 6, 6 + i % 2 * 3, color, 4, p + i)
    else:
        for i in range(3):
            _ring(d, x, y, radius + i * 4, color, 2)
        _star(d, x, y, radius * .45, white, 5, p)
    if hit:
        # Contact debris: dark chips with bright tips scatter from the hit
        # point and settle during the aftermath.
        for i in range(5):
            angle = i * math.tau / 5 + variant * .7
            dist = radius + 4 + p * 10
            xx, yy = x + math.cos(angle) * dist, y + math.sin(angle) * dist * .7
            d.polygon(((xx - 2, yy + 2), (xx, yy - 4), (xx + 3, yy + 1)), fill=dark)
            d.line((xx, yy - 3, xx + 2, yy), fill=color, width=1)


def draw_native_skill(img, species_id, kind, source, target, phase, progress, team=0, element=None):
    """A species' authored silhouette overlays its canonical element material.

    Source and target are one real action (or one applied side hit). Decorative
    sparks/runes never choose additional victims or create extra combat links.
    """
    from arena_skills import SKILLS
    move_type = element or SKILLS[species_id]['type']
    p = max(0., min(1., progress))
    draw_skill(img, species_id, move_type, source, target, phase, p, team, 'arena_' + kind)
    d = ImageDraw.Draw(img)
    ax, ay = source
    bx, by = target
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy) or 1.
    nx, ny = -dy / length, dx / length
    x, y = source if phase == 'windup' else ((ax + dx * p, ay + dy * p) if phase == 'flight' else target)
    hit = phase in ('impact', 'aftermath')
    fade = 1 - p * .6 if phase == 'aftermath' else 1.
    rgb = ELEMENT_COLORS[move_type]
    color, white = (*rgb[:3], round(245 * fade)), (*WHITE[:3], round(245 * fade))
    r = 9 + (p * 9 if hit else p * 4)
    angle = p * math.tau
    if species_id in GEN2_EFFECTS:
        _gen2_motif(species_id, d, x, y, p if hit else p * .4, angle, hit)
        if hit:
            _ring(d, x, y, r + 16, color, 2)
        return
    if species_id in EXPANSION_EFFECTS:
        _expansion_motif(species_id,d,x,y,p if hit else p*.4,angle,hit)
        if hit:
            _ring(d,x,y,r+16,color,2)
        return
    if kind == 'spark_chain':
        if phase != 'windup':
            route = [(ax + dx * i / 8 + nx * (3 if i % 2 else -3),
                      ay + dy * i / 8 + ny * (3 if i % 2 else -3)) for i in range(9)]
            d.line(route, fill=color, width=3)
            d.line(route, fill=white, width=1)
        for off in (-7, 7):
            d.line(((x + off, y - 10), (x + off - 3, y), (x + off + 3, y - 1), (x + off, y + 10)), fill=color, width=3)
    elif kind == 'four_arm_combo':
        for i, (ox, oy) in enumerate(((-11, -9), (8, -7), (-9, 8), (11, 10))):
            xx, yy = x + ox * (1 - .35 * p), y + oy
            d.rounded_rectangle((xx - 5, yy - 4, xx + 5, yy + 4), radius=2, fill=color, outline=white)
            d.line((xx - 3, yy - 4, xx - 3, yy - 1, xx, yy - 4, xx, yy - 1), fill=white, width=1)
    elif kind == 'venom_rush':
        ux, uy = dx / length, dy / length
        d.polygon(((x + ux * 19, y + uy * 19), (x - ux * 12 + nx * 8, y - uy * 12 + ny * 8),
                   (x - ux * 5, y - uy * 5), (x - ux * 12 - nx * 8, y - uy * 12 - ny * 8)), fill=color, outline=white)
        if hit:
            for i in (-1, 1):
                d.line((x - 12, y + i * 9, x + 12, y + i * 9 - 5), fill=(176, 248, 82, 230), width=2)
    elif kind == 'shadow_siphon':
        d.ellipse((x - r, y - r, x + r, y + r), fill=(35, 15, 61, 220), outline=color, width=3)
        d.arc((x - r - 5, y - r - 5, x + r + 5, y + r + 5), 45 + p * 90, 290 + p * 90, fill=white, width=2)
        d.polygon(((x - 6, y - 4), (x - 1, y - 1), (x - 6, y + 2)), fill=(255, 99, 172, 255))
        d.polygon(((x + 6, y - 4), (x + 1, y - 1), (x + 6, y + 2)), fill=(255, 99, 172, 255))
    elif kind == 'flame_storm':
        for i in range(5):
            a = angle + i * math.tau / 5
            xx, yy = x + math.cos(a) * r, y + math.sin(a) * r * .7
            d.polygon(((xx - 5, yy + 6), (xx - 3, yy - 2), (xx + 3, yy - 12), (xx + 6, yy + 3)), fill=color, outline=white)
        d.arc((x - r - 6, y - r - 6, x + r + 6, y + r + 6), 30, 315, fill=(255, 196, 56, 240), width=3)
    elif kind == 'psychic_blink':
        for i in range(2):
            rr = r + i * 7
            d.line(((x, y - rr), (x + rr, y), (x, y + rr), (x - rr, y), (x, y - rr)), fill=white if i else color, width=2)
        d.line((x - 7, y, x + 7, y, x, y - 7, x, y + 7), fill=color, width=2)
    elif kind == 'venom_armor':
        poly = [(x + math.cos(i * math.pi / 3) * r, y + math.sin(i * math.pi / 3) * r) for i in range(6)]
        d.polygon(poly, outline=white)
        for xx, yy in poly:
            d.line((xx, yy, x + (xx - x) * 1.35, y + (yy - y) * 1.35), fill=color, width=3)
        _ring(d, x, y, r * .65, color, 3)
    elif kind == 'stone_pulse':
        for i in range(3):
            rr = r + i * 5
            d.ellipse((x - rr, y - rr * .4 + 5, x + rr, y + rr * .4 + 5), outline=(216, 179, 125, 230), width=2)
        for i in (-1, 0, 1):
            d.line(((x + i * 10, y + 4), (x + i * 12 - 3, y - 5), (x + i * 14, y - 15)), fill=white, width=2)
    elif kind == 'flame_guard':
        d.line(((x - 13, y - 10), (x + 13, y - 10), (x + 10, y + 7), (x, y + 16), (x - 10, y + 7), (x - 13, y - 10)), fill=white, width=2)
        for i in (-1, 1):
            d.line(((x + i * 15, y + 7), (x + i * 22, y), (x + i * 17, y - 11)), fill=color, width=4)
    elif kind == 'venom_tide':
        for row in range(3):
            route = [(x - 22 + j * 5, y + row * 6 - 6 + math.sin(j * .9 + angle) * 4) for j in range(10)]
            d.line(route, fill=color if row != 1 else white, width=3)
        for off in (-15, 15):
            d.ellipse((x + off - 3, y - 13, x + off + 3, y - 7), outline=color, width=2)
    elif kind == 'twin_cannon':
        for off in (-6, 6):
            start = (ax + nx * off, ay + ny * off)
            end = (x + nx * off, y + ny * off)
            if phase == 'windup':
                _ring(d, *start, 5 + p * 3, white, 2)
            else:
                d.line((start, end), fill=color, width=4)
                d.line((start, end), fill=white, width=1)
                _ring(d, *end, 5 + p * 6, color, 2)
    elif kind == 'slow_field':
        _ring(d, x, y, r + 5, color, 2)
        for i in range(8):
            a = i * math.pi / 4
            d.line((x + math.cos(a) * r, y + math.sin(a) * r,
                    x + math.cos(a) * (r + 4), y + math.sin(a) * (r + 4)), fill=white, width=2)
        d.line(((x - 6, y), (x, y), (x + math.cos(angle) * 9, y + math.sin(angle) * 9)), fill=white, width=2)
    elif kind == 'healing_song':
        for i in range(3):
            xx, yy = x + (i - 1) * 11, y + math.sin(angle + i) * 5
            d.ellipse((xx - 4, yy + 2, xx + 3, yy + 6), fill=(255, 149, 203, 255))
            d.line((xx + 3, yy + 3, xx + 3, yy - 9, xx + 8, yy - 6), fill=white, width=2)
    elif kind == 'cleansing_powder':
        for i in range(3):
            xx, yy = x + (i - 1) * 13, y - (i % 2) * 7
            for off in (-1, 1):
                d.ellipse((xx + off * 4 - 4, yy - 6, xx + off * 4 + 4, yy + 3), outline=white, fill=color)
            d.line((xx, yy - 5, xx, yy + 7), fill=(115, 221, 186, 250), width=2)
    elif kind == 'moon_blessing':
        d.arc((x - r, y - r, x + r, y + r), 35, 315, fill=(255, 218, 126, 255), width=5)
        _star(d, x + 10, y - 9, 5, white, 4)
        _star(d, x - 13, y + 9, 3, white, 4)
    elif kind == 'aroma_garden':
        for i in range(5):
            a = i * math.tau / 5 + angle * .2
            xx, yy = x + math.cos(a) * 10, y + math.sin(a) * 10
            d.ellipse((xx - 6, yy - 5, xx + 6, yy + 5), fill=(255, 162, 190, 230), outline=white)
        _ring(d, x, y, 5, (253, 229, 111, 255), 3)
        d.arc((x - 22, y + 3, x + 22, y + 19), 0, 180, fill=color, width=3)
    elif kind == 'solar_relay':
        _ring(d, x, y, 8, (255, 225, 82, 255), 3)
        for i in range(8):
            a = i * math.pi / 4 + angle * .2
            d.line((x + math.cos(a) * 12, y + math.sin(a) * 12,
                    x + math.cos(a) * 22, y + math.sin(a) * 22), fill=(255, 220, 65, 240), width=2)
        d.line(((x - 12, y + 10), (x, y + 16), (x + 12, y + 10)), fill=color, width=3)
    elif kind == 'star_resonance':
        _star(d, x, y, r + 5, (255, 199, 92, 245), 5, angle * .1)
        _star(d, x, y, r * .5, (116, 218, 255, 255), 5, angle * .1)
        for off in (-18, 18):
            _star(d, x + off, y - 8, 4, white, 4, angle)


def draw_native_outcome(img, kind, source, target, progress, details):
    """Bounded feedback for an applied effect packet, with exact endpoints."""
    p = max(0., min(1., progress))
    d = ImageDraw.Draw(img)
    ax, ay = source
    bx, by = target
    alpha = round(240 * (1 - p * .65))
    green, cyan, violet = (111, 236, 171, alpha), (107, 223, 255, alpha), (199, 128, 252, alpha)
    if kind == 'heal':
        if details.get('amount', 0) <= 0:
            d.line((bx - 7, by - 7, bx + 7, by + 7), fill=(246, 128, 97, alpha), width=2)
            _ring(d, bx, by, 13, (246, 128, 97, alpha), 2)
            return
        draw_heal(img, source, target, p)
        d.line((bx - 5, by - 9 - p * 9, bx + 5, by - 9 - p * 9), fill=green, width=3)
        d.line((bx, by - 14 - p * 9, bx, by - 4 - p * 9), fill=green, width=3)
    elif kind == 'guard':
        if source != target:
            d.line((source, target), fill=cyan, width=1)
        pts = ((bx - 15, by - 17), (bx + 15, by - 17), (bx + 12, by + 7),
               (bx, by + 17), (bx - 12, by + 7), (bx - 15, by - 17))
        d.line(pts, fill=cyan, width=2)
        d.arc((bx - 20, by - 22, bx + 20, by + 22), 200, 340, fill=(*WHITE[:3], alpha), width=2)
    elif kind == 'cleanse':
        d.line((source, target), fill=green, width=1)
        _ring(d, bx, by, 9 + p * 15, green, 2)
        for i in range(4):
            a = i * math.pi / 2 + p
            _star(d, bx + math.cos(a) * 18, by + math.sin(a) * 14, 4, (*WHITE[:3], alpha), 4)
    elif kind in ('energy', 'energy_drain'):
        color = cyan if kind == 'energy' else violet
        d.line((source, target), fill=color, width=1)
        for i in range(3):
            k = min(1., max(0., p * 1.3 - i * .12))
            x, y = ax + (bx - ax) * k, ay + (by - ay) * k
            d.polygon(((x, y - 5), (x + 4, y), (x, y + 5), (x - 4, y)), fill=color, outline=WHITE)
        _ring(d, bx, by, 8 + p * 8, color, 2)
    elif kind in ('knockback', 'pull'):
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy) or 1.
        nx, ny = -dy / length, dx / length
        x, y = ax + dx * p, ay + dy * p
        d.line((source, target), fill=(255, 201, 127, alpha), width=2)
        d.line(((x - dx / length * 7 + nx * 5, y - dy / length * 7 + ny * 5), (x, y),
                (x - dx / length * 7 - nx * 5, y - dy / length * 7 - ny * 5)), fill=WHITE, width=2)
    elif kind == 'status':
        for off in (-6, 6):
            yy = by - 10 - p * 10
            d.ellipse((bx + off - 4, yy - 4, bx + off + 4, yy + 4), fill=violet, outline=WHITE)
    elif kind == 'flinch':
        for i in range(3):
            a = i * math.tau / 3 + p * 4
            _star(d, bx + math.cos(a) * 14, by - 14 + math.sin(a) * 4, 4, (255, 220, 93, alpha), 4)


COMBINATION_NAMES = {'heart_bell': '护心铃', 'poison_catalyst': '毒性催化',
                     'watch_echo': '守望回响', 'ward_bracer': '守势护腕',
                     'clarity_charm': '清明坠饰', 'barrier_feedback': '屏障回流',
                     'breach_momentum': '乘隙追击', 'contagion_orb': '扩散宝珠',
                     'metronome': '节拍器', 'native_inspiration': '充能鼓舞',
                     'bond_erosion': '侵蚀羁绊', 'bond_combo': '连击羁绊',
                     'bond_guard': '守护羁绊', 'bond_inspiration': '鼓舞羁绊'}

COMBINATION_NAMES.update({key: FINISHED[key]['name'] for key in (
    'drain_fang', 'tide_shell', 'dew_charm', 'torrent_orb', 'pulse_band',
    'relay_coil', 'grounding_cloak', 'storm_chime')})
COMBINATION_NAMES.update({row['id']: row['name'] for row in arena_traits.catalog()})
# These display IDs follow combination_view.NAMES; no new reward/stat source.
COMBINATION_NAMES.update({'element_wet': '湿润铺垫', 'element_conduct': '水电导流',
                          'element_bloom': '水草滋养', 'arena_weather': '天气争夺',
                          'life_orb': FINISHED['life_orb']['name']})


def combination_label(key, effect, details):
    name = COMBINATION_NAMES.get(key, key)
    amount = max(0, int(details.get('amount', 0)))
    label = {'heal': f'实际回复 +{amount}', 'cleanse': '实际净化',
             'status': '施加麻痹' if details.get('status_kind') == 'para' else '施加中毒',
             'accuracy': '修正闪避命中', 'weaken': f"物理攻击 -{details.get('fraction', 0):.0%}",
             'guard': f'实际避免生命损失 {amount}', 'absorb_damage': f'实际避免生命损失 {amount}',
             'empowered_hit': f"强化命中 · 已结算额外生命损失 {details.get('extra_damage', amount)}",
             'shield': f'护盾 +{amount}', 'absorb': f'护盾吸收 {amount}',
             'energy': f'回能 +{amount}', 'expire': '护盾到期',
             'charge': '反击蓄力',
             'empowered_basic': f'强化普攻 · 额外生命损失 {details.get("extra_damage", amount)}',
             'vulnerability': f'易伤 {details.get("fraction", 0):.0%}',
             'spread': ('传播灼伤' if details.get('status_kind') == 'burn' else '传播中毒'),
             'tempo': f'节拍 {details.get("stacks", 0)} 层 · 攻速 +{details.get("fraction", 0):.0%}',
             'offense_buff': f'直接攻击 +{details.get("fraction", 0):.0%} · 3秒'}
    if effect in ('guard', 'absorb_damage') and details.get('avoided_shield_absorption', 0) > 0:
        label[effect] += f" / 保留护盾 {details['avoided_shield_absorption']}"
    if effect == 'empowered_hit' and details.get('absorbed', 0) > 0:
        label[effect] += f" / 额外护盾吸收 {details['absorbed']}"
    if key == 'element_wet':
        label.update(wet=f"湿润 {details.get('duration', 4):g}秒 · 同目标可接电/草",
                     expire='湿润结束')
    if key == 'arena_weather':
        weather = {'rain': '雨天', 'sun': '晴天', None: '平静'}
        label['weather_request'] = f"申请{weather.get(details.get('new_weather'), '天气')} {details.get('duration', 12):g}秒 · 随后一拍生效"
        label['weather'] = ('晴雨相抵 · 转为平静' if details.get('reason') == 'simultaneous_rain_sun' else
                            f"{weather.get(details.get('new_weather'), '平静')} · 不续时" if details.get('reason') == 'same_weather_no_refresh' else
                            f"全场{weather.get(details.get('new_weather'), '平静')} {details.get('duration', 0):g}秒 · 双方共享")
        label['expire'] = '天气到期 · 恢复平静'
        label['accuracy'] = ('雨中打雷 · 跳过命中/闪避，地面仍免疫' if details.get('guaranteed') else
                             '打雷未命中' if not details.get('hit') else '打雷命中判定通过')
    if key == 'life_orb' and (details.get('recoil') or details.get('damage_scope') == 'self_cost'):
        label['damage'] = f'反噬自损 {amount} · 不计对抗伤害'
    if key in ('trait_chlorophyll', 'trait_swift_swim'):
        label['tempo'] = f"天气行动速度 +{details.get('fraction', .25):.0%}"
        label['expire'] = '天气加速结束'
    if key.startswith('trait_'):
        name = '特性 · ' + name
        if effect == 'offense_buff' and details.get('damage_scope') == 'physical':
            label['offense_buff'] = f"物理直接伤害 +{details.get('fraction', 0):.0%}"
        if effect == 'expire' and key not in ('trait_chlorophyll', 'trait_swift_swim'):
            label['expire'] = '物理强化结束' if key == 'trait_guts' else '物理压制结束'
    if effect == 'tempo' and key == 'bond_combo':
        label['tempo'] = label['tempo'].replace('节拍', '连击', 1)
    if effect == 'tempo' and details.get('base_fraction', 0) > 0 and details.get('item_fraction', 0) > 0:
        label['tempo'] += (f"（连击+{details['base_fraction']:.0%} / 装备+{details['item_fraction']:.0%}）")
    if effect == 'expire' and key in ('metronome', 'native_inspiration', 'bond_combo', 'bond_inspiration'):
        label['expire'] = '连击清层' if key == 'bond_combo' else '节拍清层' if key == 'metronome' else '鼓舞结束'
    return f'{name} · {label.get(effect, effect)}'


def active_offense(events, t, idx):
    """Rebuild independent tempo tracks and the strongest recorded buff."""
    tracks = {}
    effects = {'metronome': 'tempo', 'bond_combo': 'bond_combo',
               'native_inspiration': 'offense_buff', 'bond_inspiration': 'offense_buff'}
    for event in events:
        if event[0] > t + 1e-9 or event[1] != 'combo_effect' or len(event) != 7 or event[3] != idx:
            continue
        key, effect, payload = event[4:7]
        if key not in effects:
            continue
        expected = 'tempo' if key == 'bond_combo' else effects[key]
        if effect == expected:
            tracks[key] = event
        elif effect == 'expire':
            tracks.pop(key, None)
    active = {}
    for key, event in tracks.items():
        if not 0 <= t-event[0] < event[6].get('duration', 0):
            continue
        label = effects[key]
        if label != 'offense_buff' or label not in active or event[6].get('fraction', 0) >= active[label][6].get('fraction', 0):
            active[label] = event
    return active


def active_traits(events, t, idx):
    """Separate physical-only trait tracks from all-direct inspiration buffs."""
    tracks = {}
    expected = {'trait_guts': ('offense_buff', 'physical_buff'),
                'trait_intimidate': ('weaken', 'physical_weaken')}
    for event in events:
        if (len(event) != 7 or event[1] != 'combo_effect' or event[0] > t + 1e-9
                or event[3] != idx or event[4] not in expected):
            continue
        key, effect, details = event[4:]
        if effect == expected[key][0] and details.get('damage_scope') == 'physical':
            tracks[key] = event
        elif effect == 'expire':
            tracks.pop(key, None)
    return {expected[key][1]: event for key, event in tracks.items()
            if 0 <= t-event[0] < event[6].get('duration', 0)}


def draw_combination(img, key, effect, source, target, progress, details):
    """Finite interaction feedback with recorded, exact source/recipient points."""
    p = min(1., max(0., progress))
    draw = ImageDraw.Draw(img)
    ax, ay = source
    bx, by = target
    alpha = 220 if effect == 'active' else round(245 * (1 - p * .6))
    if key == 'element_wet':
        cyan, pale = (87, 208, 239, alpha), (221, 255, 245, alpha)
        radius = 10 + (math.sin(p*math.tau)*2 if effect == 'active' else p*12)
        draw.arc((bx-radius, by+2-radius*.35, bx+radius, by+2+radius*.35), 5, 345, fill=cyan, width=2)
        # Curved droplet bodies give the mark a water surface, not a line icon.
        for i in range(3):
            xx = bx-10+i*10
            yy = by-15 + math.sin(p*math.tau+i)*2
            draw.polygon(((xx,yy-5),(xx-3,yy),(xx-2,yy+3),(xx+2,yy+3),(xx+3,yy)), fill=cyan)
            draw.arc((xx-3,yy-1,xx+3,yy+4), 5, 170, fill=pale, width=1)
        return
    if key == 'element_conduct':
        cyan, gold = (104, 219, 239, alpha), (255, 227, 109, alpha)
        for offset in (-3, 3):
            points = [(ax+(bx-ax)*i/14, ay+(by-ay)*i/14+math.sin(i*.9+p*math.tau)*offset)
                      for i in range(15)]
            draw.line(points, fill=cyan, width=2)
        flight = min(1., p*1.5)
        xx, yy = ax+(bx-ax)*flight, ay+(by-ay)*flight
        draw.line(((xx-5,yy-6),(xx+1,yy-2),(xx-2,yy+2),(xx+5,yy+6)),fill=gold,width=3)
        draw.ellipse((bx-8-p*7,by-6,bx+8+p*7,by+6),outline=gold,width=2)
        return
    if key == 'element_bloom':
        leaf, pale = (119, 236, 139, alpha), (229, 255, 207, alpha)
        radius = 12+p*20
        for i in range(3):
            rr=radius-i*4
            draw.arc((bx-rr,by+7-rr*.35,bx+rr,by+7+rr*.35), 5, 355, fill=leaf,width=2)
        for i in range(6):
            angle=i*math.tau/6+p*.8
            xx,yy=bx+math.cos(angle)*radius,by-8+math.sin(angle)*radius*.5
            draw.ellipse((xx-4,yy-2,xx+4,yy+2),fill=leaf)
            draw.line((xx-3,yy+1,xx+3,yy-1),fill=pale,width=1)
        draw.line((bx-5,by-13,bx+5,by-13),fill=pale,width=3)
        draw.line((bx,by-18,bx,by-8),fill=pale,width=3)
        return
    if key == 'arena_weather':
        kind = details.get('new_weather')
        if effect == 'accuracy':
            if details.get('hit'):
                draw.line(((bx-8,by-12),(bx+2,by-3),(bx-2,by+2),(bx+9,by+13)),fill=(255,232,106,alpha),width=3)
            return
        if kind == 'rain':
            color=(132,207,237,alpha)
            for i in range(5):
                xx=bx-15+i*7;yy=by-14+math.sin(i)*3
                draw.ellipse((xx-5,yy-5,xx+5,yy+4),fill=(172,226,239,alpha))
                draw.line((xx,yy+7+p*12,xx-2,yy+12+p*12),fill=color,width=2)
        elif kind == 'sun':
            radius=8+p*3;color=(255,211,112,alpha)
            draw.ellipse((bx-radius,by-14-radius,bx+radius,by-14+radius),fill=color,outline=WHITE,width=1)
            for i in range(8):
                angle=i*math.tau/8+p*.6
                draw.line((bx+math.cos(angle)*(radius+3),by-14+math.sin(angle)*(radius+3),
                           bx+math.cos(angle)*(radius+7),by-14+math.sin(angle)*(radius+7)),fill=color,width=2)
        else:
            draw.arc((bx-18-p*12,by-12,bx+18+p*12,by+12),5,355,fill=(204,230,210,alpha),width=1)
        return
    if key == 'life_orb':
        cost = details.get('recoil') or details.get('damage_scope') == 'self_cost'
        color = (251, 122, 147, alpha) if cost else (236, 184, 245, alpha)
        radius = (18-p*9) if cost else (9+p*14)
        for i in range(6):
            angle=i*math.tau/6+p*.6
            xx,yy=bx+math.cos(angle)*radius,by+math.sin(angle)*radius*.7
            draw.polygon(((xx-3,yy),(xx,yy-5),(xx+3,yy),(xx,yy+5)),fill=color,outline=WHITE)
        return
    if key in ('trait_chlorophyll', 'trait_swift_swim'):
        leaf = key == 'trait_chlorophyll'
        color = (155, 237, 124, alpha) if leaf else (111, 218, 245, alpha)
        for i in range(3):
            xx=bx-13+i*13;yy=by+11+math.sin(p*math.tau+i)*2
            draw.arc((xx-6,yy-3,xx+6,yy+3),10,185,fill=color,width=2)
            if leaf:
                draw.ellipse((xx-2,yy-13,xx+4,yy-9),fill=color)
            else:
                draw.line((xx-4,yy-10,xx,yy-13,xx+4,yy-10),fill=WHITE,width=1)
        return
    if key.startswith('trait_'):
        cyan = (130, 238, 237, alpha)
        gold = (255, 214, 107, alpha)
        violet = (204, 166, 242, alpha)
        if effect == 'empowered_hit':
            fire = key in ('trait_blaze', 'trait_guts')
            color = (255, 155, 67, alpha) if fire else cyan
            radius = 8 + p * 16
            for i in range(6):
                angle = i * math.tau / 6 + p * .9
                xx, yy = bx + math.cos(angle) * radius, by + math.sin(angle) * radius * .65
                if fire:
                    draw.polygon(((xx-3,yy+4),(xx-2,yy-3),(xx+1,yy-7),(xx+3,yy+4)), fill=color)
                    draw.line((xx, yy+1, xx+1, yy-4), fill=WHITE, width=1)
                else:
                    draw.arc((xx-5, yy-3, xx+5, yy+3), 10, 180, fill=color, width=2)
            return
        if key == 'trait_guts':
            if effect in ('offense_buff', 'active'):
                for side in (-1, 1):
                    xx = bx + side * (14 + math.sin(p*math.tau)*2)
                    draw.rounded_rectangle((xx-4, by-6, xx+4, by+2), radius=2, fill=(135,87,64,alpha), outline=gold, width=1)
                    draw.line((xx-side*2,by-11,xx-side*4,by-17), fill=gold, width=2)
            else:
                draw.arc((bx-15-p*8,by-13,bx+15+p*8,by+13), 190, 345, fill=gold, width=1)
            return
        if key == 'trait_intimidate':
            # Two lowering eyes signal physical pressure, with no damage float.
            for side in (-1, 1):
                xx = bx + side * 8
                yy = by - 16 - p * 5
                draw.polygon(((xx-6,yy-3),(xx+6,yy),(xx+3,yy+4),(xx-3,yy+3)), outline=violet)
                draw.line((xx,yy,xx,yy+3), fill=WHITE, width=1)
                draw.line(((xx,by+2),(xx,by+9),(xx-3,by+6)), fill=violet, width=2)
            return
        if effect in ('guard', 'absorb_damage'):
            radius = 12 + p * 7
            if key == 'trait_magic_guard':
                points = [(bx+math.cos(-math.pi/2+i*math.pi/2)*radius,
                           by+math.sin(-math.pi/2+i*math.pi/2)*radius*1.15) for i in range(5)]
                draw.line(points, fill=cyan, width=2)
                _star(draw,bx-radius*.9,by,3,WHITE,4)
                _star(draw,bx+radius*.9,by,3,WHITE,4)
            else:
                for side in (-1,1):
                    draw.line(((bx+side*radius,by+8),(bx+side*radius,by-10),
                               (bx+side*5,by-17),(bx,by-13)), fill=gold, width=2)
                draw.line((bx-6,by+13,bx+6,by+13), fill=WHITE, width=2)
            return
        if effect == 'accuracy':
            radius = 9 + (1-p)*7
            draw.ellipse((bx-radius,by-radius*.5,bx+radius,by+radius*.5), outline=gold,width=2)
            draw.ellipse((bx-3,by-3,bx+3,by+3), fill=WHITE)
            for side in (-1,1):
                draw.line((bx+side*(radius+3),by-3,bx+side*(radius+3),by+3), fill=gold,width=1)
            return
        if effect == 'status':
            electric = details.get('status_kind') == 'para'
            color = gold if electric else violet
            for i in range(5):
                angle = i*math.tau/5+p*.7
                xx,yy = bx+math.cos(angle)*(8+p*12),by+math.sin(angle)*(7+p*9)
                if electric:
                    draw.line(((xx-3,yy-4),(xx+1,yy-1),(xx-1,yy+1),(xx+3,yy+4)),fill=color,width=2)
                else:
                    draw.ellipse((xx-3,yy-4,xx+3,yy+2),fill=color,outline=WHITE)
            return
        # Trait recovery uses the same actual-outcome material as equipment.
        key = 'grounding_cloak' if effect == 'cleanse' else 'relay_coil' if effect == 'energy' else 'dew_charm'
    if key in ('drain_fang', 'dew_charm', 'tide_shell', 'torrent_orb', 'pulse_band',
               'relay_coil', 'grounding_cloak', 'storm_chime'):
        electric = key in ('pulse_band', 'relay_coil', 'grounding_cloak', 'storm_chime')
        color = (252, 221, 115, alpha) if electric else (129, 227, 235, alpha)
        pale = (255, 248, 202, alpha) if electric else (218, 252, 241, alpha)
        if effect == 'cleanse':
            for i in range(4):
                angle=i*math.pi/2+p*.8
                _star(draw,bx+math.cos(angle)*(8+p*12),by+math.sin(angle)*(8+p*12),3,pale,4)
            draw.arc((bx-16-p*6,by-11,bx+16+p*6,by+11),15,165,fill=color,width=2)
        elif effect in ('shield', 'absorb', 'active', 'expire'):
            radius=14 if effect=='active' else 10+p*10
            for side in (-1,1):
                draw.arc((bx-radius,by-radius*1.2,bx+radius,by+radius*1.2),
                         95 if side<0 else -85,265 if side<0 else 85,fill=color,width=2)
            for yy in (-8,0,8):
                draw.arc((bx-radius+3,by+yy-3,bx+radius-3,by+yy+3),5,170,fill=pale,width=1)
            if effect == 'absorb':
                _star(draw,bx-2,by-8,5,WHITE,4)
        elif effect in ('energy', 'heal'):
            if source != target:
                for i in range(5):
                    k=min(1.,max(0.,p*1.5-i*.1))
                    xx,yy=ax+(bx-ax)*k,ay+(by-ay)*k-math.sin(k*math.pi)*9
                    if electric:
                        draw.line(((xx-3,yy-2),(xx,yy-5),(xx-1,yy),(xx+3,yy+2)),fill=color,width=2)
                    else:
                        draw.ellipse((xx-2,yy-3,xx+2,yy+2),fill=color,outline=pale)
            for i in range(5):
                angle=i*math.tau/5+p*.7
                xx,yy=bx+math.cos(angle)*(8+p*9),by+math.sin(angle)*(5+p*6)-p*8
                if electric:
                    _star(draw,xx,yy,3,pale,4)
                else:
                    draw.polygon(((xx,yy-4),(xx-2,yy),(xx,yy+3),(xx+2,yy)),fill=color,outline=pale)
            draw.arc((bx-15,by+8,bx+15,by+16),5,175,fill=color,width=1)
        return
    if key == 'contagion_orb' and effect == 'spread':
        # Follow the original DOT patient's recorded endpoint, not the holder.
        fire = details.get('status_kind') == 'burn'
        mid = (255, 153, 62, alpha) if fire else (174, 106, 217, alpha)
        dark = (173, 61, 54, alpha) if fire else (83, 55, 119, alpha)
        light = (255, 231, 139, alpha) if fire else (234, 190, 249, alpha)
        for i in range(7):
            k = min(1., max(0., p * 1.5 - i * .075))
            if not 0 < k < 1:
                continue
            xx = ax + (bx-ax)*k
            yy = ay + (by-ay)*k - math.sin(k*math.pi)*(7+i%3*2)
            radius = 2 + (i % 2)
            if fire:
                draw.polygon(((xx-radius, yy+radius), (xx-1,yy-radius-3),
                              (xx+1,yy-radius), (xx+radius,yy+radius)), fill=dark)
                draw.polygon(((xx-radius+1,yy+radius-1), (xx,yy-radius-1),
                              (xx+radius-1,yy+radius-1)), fill=mid)
                draw.point((round(xx),round(yy)), fill=light)
            else:
                draw.ellipse((xx-radius,yy-radius,xx+radius,yy+radius), fill=dark, outline=mid)
                draw.point((round(xx-1),round(yy-1)), fill=light)
        if p > .35:
            radius = 5 + (p-.35)*16
            draw.arc((bx-radius,by-radius*.55,bx+radius,by+radius*.55),20,165,fill=mid,width=2)
            draw.arc((bx-radius,by-radius*.55,bx+radius,by+radius*.55),195,345,fill=light,width=1)
            for i in range(4):
                angle = i*math.tau/4 + p*.8
                xx,yy = bx+math.cos(angle)*radius*.8,by+math.sin(angle)*radius*.6
                if fire:
                    _star(draw,xx,yy,2.5,light,4)
                else:
                    draw.ellipse((xx-2,yy-3,xx+2,yy+1),fill=mid,outline=light)
    elif key in ('metronome', 'bond_combo'):
        stacks = max(0, min(3, int(details.get('stacks', 0))))
        if key == 'bond_combo':
            by -= 31
        gold, shadow = (255, 205, 116, alpha), (150, 102, 54, alpha)
        if effect == 'expire':
            for i in range(min(3, int(details.get('previous_stacks', 3)))):
                xx = bx + (i-1)*(8+p*7)
                yy = by+15+p*8
                draw.line((xx-2,yy,xx+2,yy),fill=(198,179,140,round(alpha*(1-p))),width=2)
        elif effect in ('tempo', 'active'):
            # Three distinct beat lights show the current stack, even when idle.
            for i in range(3):
                xx,yy = bx+(i-1)*8,by+16
                draw.rounded_rectangle((xx-3,yy-2,xx+3,yy+2),radius=1,
                    fill=gold if i<stacks else (74,65,54,alpha),outline=shadow)
            for side in (-1,1):
                xx=bx+side*(13+math.sin(p*math.tau)*2)
                draw.line(((xx,by+7),(xx-side*3,by),(xx,by-7)),fill=gold,width=1)
            if effect == 'tempo' and details.get('gained', 0):
                _star(draw,bx+(stacks-2)*8,by+11-p*9,3,WHITE,4)
    elif key in ('native_inspiration', 'bond_inspiration'):
        gold, orange = (255, 227, 149, alpha), (249, 155, 93, alpha)
        if effect == 'offense_buff' and source != target:
            for i in range(4):
                k=min(1.,max(0.,p*1.5-i*.14))
                xx,yy=ax+(bx-ax)*k,ay+(by-ay)*k-math.sin(k*math.pi)*12
                _star(draw,xx,yy,3,gold,4)
        if effect in ('active','offense_buff'):
            for side in (-1,1):
                xx=bx+side*14
                yy=by+3-math.sin(p*math.pi)*3
                draw.line(((xx-3,yy+1),(xx,yy-3),(xx+3,yy+1)),fill=orange,width=2)
                draw.line(((xx-3,yy-5),(xx,yy-9),(xx+3,yy-5)),fill=gold,width=1)
            for i in range(3):
                xx=bx+(i-1)*6
                yy=by+16-((p+i/3)%1)*6
                draw.point((round(xx),round(yy)),fill=gold)
        elif effect == 'expire':
            for side in (-1,1):
                xx=bx+side*(14+p*7)
                draw.line((xx-2,by+9+p*6,xx+2,by+9+p*6),fill=(183,163,134,round(alpha*(1-p))),width=1)
    elif key in ('heart_bell', 'clarity_charm', 'bond_guard'):
        color = ((147, 245, 189, alpha) if key == 'clarity_charm' else
                 (186, 228, 144, alpha) if key == 'bond_guard' else (99, 217, 242, alpha))
        radius = 16 if effect == 'active' else 11 + p * 10
        if effect == 'shield' and source != target:
            draw.line((source, target), fill=color, width=1)
            x, y = ax + (bx-ax)*p, ay + (by-ay)*p
            _ring(draw, x, y, 3, WHITE, 1)
        points = [(bx + math.cos(-math.pi/2 + i*math.tau/6)*radius,
                   by + math.sin(-math.pi/2 + i*math.tau/6)*radius*1.25) for i in range(7)]
        draw.line(points, fill=color, width=1 if effect == 'active' else 2)
        if effect == 'absorb':
            draw.line((bx-5, by-12, bx+2, by-2, bx-2, by+3, bx+6, by+12),
                      fill=WHITE, width=2)
        if key == 'clarity_charm' and effect != 'active':
            for i in range(4):
                angle = i * math.pi / 2 + p * .8
                _star(draw, bx + math.cos(angle) * (14+p*6),
                      by + math.sin(angle) * (12+p*6), 3, WHITE, 4)
    elif key == 'ward_bracer':
        gold = (255, 192, 90, alpha)
        if effect in ('charge', 'active'):
            radius = 15 if effect == 'active' else 10 + p * 12
            for side in (-1, 1):
                xx = bx + side * radius
                draw.line(((xx, by-10), (xx-side*5, by-16),
                           (xx-side*8, by), (xx-side*5, by+16), (xx, by+10)),
                          fill=gold, width=2)
            _star(draw, bx, by, 6, WHITE, 4, p*.8)
        elif effect == 'empowered_basic':
            # Accent the single recorded hit, never another damage float.
            draw.rounded_rectangle((ax-7, ay-6, ax+7, ay+6), radius=3,
                                   fill=(147,93,58,alpha), outline=gold, width=2)
            radius = 6 + p * 14
            for i in range(6):
                angle = i * math.tau / 6
                draw.line((bx+math.cos(angle)*radius, by+math.sin(angle)*radius,
                           bx+math.cos(angle)*(radius+5), by+math.sin(angle)*(radius+5)),
                          fill=gold, width=2)
            _star(draw, bx, by, 7*(1-p*.5), WHITE, 4)
    elif key == 'barrier_feedback':
        cyan = (131, 224, 255, alpha)
        path = [(ax+(bx-ax)*i/12, ay+(by-ay)*i/12-math.sin(i/12*math.pi)*12)
                for i in range(13)]
        draw.line(path, fill=(83,147,177,alpha//2), width=1)
        for i in range(3):
            k = min(1., max(0., p*1.25-i*.16))
            xx, yy = ax+(bx-ax)*k, ay+(by-ay)*k-math.sin(k*math.pi)*12
            _ring(draw, xx, yy, 3+i*.4, cyan, 2)
            draw.point((round(xx),round(yy)), fill=WHITE)
        _ring(draw, bx, by, 7+p*9, cyan, 1)
    elif key == 'breach_momentum' and effect == 'vulnerability':
        red = (255, 133, 115, alpha)
        radius = 12+p*5
        for sx, sy in ((-1,-1), (1,-1), (-1,1), (1,1)):
            xx, yy = bx+sx*radius, by+sy*radius
            draw.line(((xx-sx*5,yy), (xx,yy), (xx,yy-sy*5)), fill=red, width=2)
        draw.line(((bx-5,by-8), (bx+2,by-3), (bx-2,by+1), (bx+5,by+8)),
                  fill=WHITE, width=2)
        for side in (-1,1):
            xx = bx+side*(8+p*8)
            draw.polygon(((xx,by-4), (xx+side*4,by-8), (xx+side*3,by+2)), fill=red)
    elif key in ('poison_catalyst', 'bond_erosion'):
        color = (203, 126, 245, alpha)
        _ring(draw, bx, by, 8+p*11, color, 2)
        for i in range(3):
            angle = p*math.tau + i*math.tau/3
            x, y = bx+math.cos(angle)*13, by+math.sin(angle)*10
            draw.ellipse((x-2, y-2, x+2, y+2), fill=color, outline=WHITE)
    elif key == 'watch_echo':
        color = (255, 220, 109, alpha)
        draw.line((source, target), fill=color, width=1)
        for i in range(3):
            k = min(1., max(0., p*1.4-i*.16))
            x, y = ax+(bx-ax)*k, ay+(by-ay)*k
            _star(draw, x, y, 4, color, 4)
        _ring(draw, bx, by, 7+p*10, color, 2)
