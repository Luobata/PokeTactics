"""Authored per-species move visuals with the original nine-template fallback."""
import math
from functools import lru_cache

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


@lru_cache(maxsize=151)
def _actual_move(sid):
    from data import pokedex
    return pokedex().signature_move(sid)


def skill_profile(sid):
    profile = _skill_of(sid) if _skill_of else None
    if sid in AUTHORED_SKILLS:
        move_id, label, design = AUTHORED_SKILLS[sid]
        move = _actual_move(sid)
        if move and move['id'] == move_id:
            return {**(profile or {}), 'arch': (profile or {}).get('arch', 'heavy_blow'),
                    'tier': (profile or {}).get('tier', 'signature' if sid in FALLBACK else 'generic'), 'name': label,
                    'species_id': sid, 'move_id': move_id, 'type': move['type'],
                    'design': design}
    if profile and profile.get('arch') in ARCHS:
        return profile
    if sid in FALLBACK:
        arch, name = FALLBACK[sid]
        return {'arch': arch, 'name': name, 'tier': 'signature'}
    return {'arch': 'heavy_blow', 'name': '重击', 'tier': 'generic'}


def cast_windup(sid):
    if sid in AUTHORED_SKILLS:
        from motion import windup
        return windup(sid)
    return SIGNATURES[sid].windup if sid in SIGNATURES else .4


def draw_charge(img, source, progress, color):
    """Foot ring brightens in four integer stages; no solid body overlay."""
    x, y = source
    bright = color
    d = ImageDraw.Draw(img)
    d.ellipse((x - 20, y - 5, x + 20, y + 5), outline=bright, width=2)
    d.arc((x - 23, y - 7, x + 23, y + 7), 0, round(360 * progress), fill=PAPER, width=1)


def draw_skill(img, profile, source, target, age, windup, budget, variant=0, emblem=None):
    if profile.get('species_id') in AUTHORED_SKILLS:
        return draw_authored(img, profile, source, target, age, windup, budget, emblem)
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

# Visual contracts are keyed by species AND the actual roster move, not by type
# or combat archetype. Repeated moves receive separately authored performances.
AUTHORED_SKILLS = {
    6: (53, '喷射火焰', 'wing_furnace'),
    65: (94, '精神强念', 'spoon_focus'),
    143: (63, '破坏光线', 'belly_capacitor'),
    149: (200, '逆鳞', 'dragon_rampage'),
    9: (56, '水炮', 'twin_cannon'),
    3: (76, '日光束', 'flower_lens'),
    94: (122, '舌舔', 'spectral_tongue'),
    131: (56, '水炮', 'neck_fan'),
    59: (53, '喷射火焰', 'running_furnace'),
    130: (56, '水炮', 'serpent_pulse'),
    31: (40, '毒针', 'guard_spines'),
    34: (40, '毒针', 'horn_drill'),
    76: (89, '地震', 'fault_front'),
    95: (88, '落石', 'segment_catapult'),
    18: (17, '翅膀攻击', 'crosswing'),
    26: (85, '十万伏特', 'cheek_circuit'),
}


def _stroke(d, points, color, width=3):
    d.line(points, fill=color, width=width)
    if width >= 3:
        d.line(points, fill=PAPER, width=1)


def draw_authored_phase(img, sid, phase_name, source, target, phase, color, budget, emblem=None):
    """Draw one semantic layer independently (also used by geometry contracts).

    Geometry uses a source-to-target local basis, integer frame index and no RNG.
    All broad shapes are outlines; filled fragments are <= 13px. Every emitted
    independent fragment is debited from the shared board ParticleBudget.
    """
    d = ImageDraw.Draw(img)
    sx,sy = source
    tx,ty = target
    dx,dy = tx-sx,ty-sy
    length = math.hypot(dx,dy) or 1
    ux,uy = dx/length,dy/length
    vx,vy = -uy,ux
    def point(p,off=0):
        return round(sx+dx*p+vx*off),round(sy+dy*p+vy*off)
    def local(x,y,center=target):
        return round(center[0]+ux*x+vx*y),round(center[1]+uy*x+vy*y)
    def line(points,width=3):
        _stroke(d,points,color,width)
    def ellipse(center,rx,ry,width=2):
        x,y=center
        d.ellipse((x-rx,y-ry,x+rx,y+ry),outline=color,width=width)
    if phase_name == 'charge':
        k=phase+1
        # All 16 concentration gestures are drawn around different body weapons.
        if sid == 6:  # inhalation at mouth, wings enclosing heat
            for i in budget.take(3):
                line([local(-18+i*6,-14-k,source),local(-10+i*6,-9,source)],2)
            d.arc((sx-23,sy-19,sx+23,sy+19),210,330,fill=color,width=2)
        elif sid == 65:  # two spoon stars feeding an eye focus
            for off in (-22,22):
                if budget.take(1):
                    light(d,sx+off,sy-4-k,color)
                    line([(sx+off,sy-4-k),(sx+off//2,sy-15-k)],1)
            ellipse((sx,sy-12),max(2,10-k*2),4)
        elif sid == 143:  # abdominal capacitor, stacked horizontal bars
            for i in budget.take(k):
                y=sy+20-i*4
                line([(sx-17,y),(sx+17,y)],2)
        elif sid == 149:  # opposed claw crescents twist inwards
            d.arc((sx-25,sy-22,sx+17,sy+20),70+k*10,210+k*10,fill=color,width=3)
            d.arc((sx-17,sy-20,sx+25,sy+22),250-k*10,390-k*10,fill=PAPER,width=2)
        elif sid == 9:  # each barrel has a separate pressure ring
            for off in (-15,15):
                ellipse(local(-8,off,source),4+k,3)
                line([local(-17,off,source),local(-10,off,source)],2)
        elif sid == 3:  # petals converge on flower, not body centre
            for i in budget.take(6):
                a=i*math.tau/6
                p=(sx+round((25-k)*math.cos(a)),sy-10+round((18-k)*math.sin(a)))
                line([p,(sx+round(10*math.cos(a)),sy-10+round(7*math.sin(a)))],2)
        elif sid == 94:  # lopsided grin opens outside the body
            d.arc((sx-21,sy-3,sx+23,sy+22+k),5,160,fill=color,width=2)
            for i in budget.take(3):
                d.line((sx-12+i*12,sy+16,sx-12+i*12,sy+20),fill=PAPER,width=1)
        elif sid == 131:  # rising throat bubbles
            for i in budget.take(3):
                ellipse((sx-19+i*7,sy+9-i*9-k),2+i,3+i)
        elif sid == 59:  # hot breath skims ground ahead of muzzle
            for i in budget.take(3):
                line([local(13+i*5,-4-k,source),local(17+i*5,2-k,source),local(21+i*5,-2-k,source)],2)
        elif sid == 130:  # coils funnel pressure up to jaws
            for i in budget.take(3):
                d.arc((sx-22+i*3,sy-18+i*7,sx+22-i*3,sy+8+i*7),15+k*10,165+k*10,fill=color,width=2)
        elif sid == 31:  # shoulder spines open defensively
            for i in budget.take(5):
                line([(sx-23+i*11,sy+8),(sx-25+i*12,sy-6-k)],2)
        elif sid == 34:  # horn sight aligns with attack axis
            line([local(8,-7,source),local(20+k,-2,source),local(8,7,source)],2)
            line([local(14,0,source),local(24+k,0,source)],1)
        elif sid == 76:  # weight loads into two feet
            for off in (-19,19):
                line([(sx+off-6,sy+21),(sx+off,sy+17+k),(sx+off+6,sy+21)],2)
        elif sid == 95:  # three stones lifted by sequential body segments
            for i in budget.take(3):
                x,y=sx-22+i*20,sy+18-i*5-k
                d.polygon([(x-3,y),(x,y-4),(x+4,y+1),(x,y+4)],outline=color,width=1)
        elif sid == 18:  # folded wings unfold as two feather fans
            for side in (-1,1):
                for i in budget.take(3):
                    line([(sx+side*15,sy+10),(sx+side*(21+i*3),sy-4-k-i*4)],1)
        elif sid == 26:  # cheek sparks and tail ground connection
            for side in (-1,1):
                line([(sx+side*18,sy-8),(sx+side*23,sy-12-k),(sx+side*20,sy-3)],2)
            line([(sx-20,sy+10),(sx-25,sy+18),(sx-17,sy+23)],1)
        return
    if phase_name == 'body':
        p=(phase+1)/6
        if sid == 6:  # sustained cone, serrated flame tongues advance continuously
            for i in budget.take(5):
                off=(i-2)*5
                pts=[point(.08,0),point(.35,off*.5),point(.6,off+(phase%2)*2),point(.9,off*1.4),point(1.05,off)]
                line(pts,3 if i%2==0 else 2)
        elif sid == 65:  # keep the established contracting psychic ripples
            signature_cast(img,65,source,target,.4+phase*.1,.4,budget,color=color)
        elif sid == 143:  # recoil-heavy segmented beam with rectangular collars
            for i in budget.take(5):
                start=.06+i*.18
                line([point(start,-4),point(start+.13,-4),point(start+.13,4),point(start,4)],2)
            line([point(.02),point(1.05)],5)
            for off in (-9,9):
                line([point(.1,off),point(.92,off)],1)
        elif sid == 149:  # rampaging three claw-orbits, no projectile beam
            for i in budget.take(3):
                a=phase*.8+i*2.1
                pts=[(tx+round((21+j)*math.cos(a+j*.09)),ty+round((16+j)*math.sin(a+j*.09))) for j in range(12)]
                line(pts,3)
            line([point(.1,-8),point(.4,14),point(.65,-12),point(.9,6)],2)
        elif sid == 9:  # twin cannons cross then fan apart
            for side in (-1,1):
                for i in budget.take(3):
                    line([point(.05,side*(12+i)),point(.45,side*4),point(.78,-side*5),point(1.,-side*(11+phase*2+i*2))],2)
        elif sid == 3:  # flower-focused straight light shaft plus orbiting petal diamonds
            line([point(.05,-3),point(1.,-3)],2)
            line([point(.05,3),point(1.,3)],2)
            for i in budget.take(5):
                x,y=point((i*.18+p*.2)%1,9 if i%2 else -9)
                d.polygon([(x-4,y),(x,y-6),(x+4,y),(x,y+6)],outline=color,width=1)
        elif sid == 94:  # long looping tongue, rounded return curl
            pts=[point(j/16,math.sin(j/16*math.pi)*12+math.sin(j*.8+phase)*2) for j in range(17)]
            line(pts,5)
            x,y=point(1.,0)
            d.arc((x-8,y-7,x+8,y+7),15+phase*20,300+phase*20,fill=color,width=3)
        elif sid == 131:  # single neck fan sweeps across target, rippling pressure ribs
            sweep=(-14,-8,0,9,15,4)[phase]
            for i in budget.take(5):
                line([point(.06),point(.6,(sweep+i-2)*.5),point(1.,sweep+(i-2)*4)],2)
            x,y=point(.65,sweep*.5)
            d.arc((x-12,y-15,x+12,y+15),-70,70,fill=PAPER,width=2)
        elif sid == 59:  # low, galloping flame packets: three independent maws
            for i in budget.take(3):
                q=(p*.6+i*.26)%1
                pts=[point(q,-5),point(q+.06,-10-i),point(q+.1,-3),point(q+.18,0),point(q+.08,6),point(q+.03,3)]
                d.polygon(pts,outline=color,width=2)
                line([point(q+.03),point(q+.12)],2)
        elif sid == 130:  # alternating coiled pressure pulses
            for i in budget.take(4):
                q=(i*.23+p*.3)%1
                pts=[point(q+j*.015,math.sin(j*.5+phase)*8) for j in range(9)]
                line(pts,3)
                x,y=point(q+.1)
                ellipse((x,y),3,8)
        elif sid == 31:  # five shoulder needles spread in a protective fan
            for i in budget.take(5):
                off=(i-2)*9
                q=min(1.,.25+phase*.15)
                line([point(q-.16,off*.7),point(q,off)],2)
                a=point(q,off);b=point(q-.055,off-3);c=point(q-.055,off+3)
                d.polygon([a,b,c],outline=color,width=1)
        elif sid == 34:  # one horn drill corkscrews into the target
            q=min(1.,.4+phase*.12)
            line([point(.05),point(q)],2)
            for i in budget.take(4):
                a=.25+i*.17
                line([point(a-.05,-6),point(a,5),point(a+.05,-5)],2)
            line([point(q-.13,-7),point(q,0),point(q-.13,7)],3)
        elif sid == 76:  # board-wide fault fronts and branching floor fissures
            for i in budget.take(3):
                radius=20+phase*8+i*20
                ellipse(target,radius,max(4,radius//3),2)
            for i in budget.take(5):
                x=12+i*(img.width-24)//4
                y=ty+14+(i%2)*12
                line([(x,y),(x+8,y+7),(x+3,y+15+phase*2),(x+12,y+20+phase*2)],2)
        elif sid == 95:  # three stones lobbed at staggered parabolic heights
            for i in budget.take(3):
                q=min(1.,max(0.,(phase-i+1)/4))
                x,y=point(q,(i-1)*14)
                y-=round(32*4*q*(1-q))
                d.polygon([(x-5,y-2),(x-2,y-6),(x+4,y-4),(x+6,y+2),(x,y+6),(x-5,y+3)],outline=color,width=2)
                line([(x-2,y-3),(x+2,y)],1)
        elif sid == 18:  # crossing paired wing crescents and shed feathers
            for side in (-1,1):
                pts=[local(-26+j*4,side*(4+round(12*math.sin(j*math.pi/12)))) for j in range(13)]
                line(pts,3)
            for i in budget.take(4):
                x,y=local(-20+i*13,(-1 if i%2 else 1)*(20+phase))
                line([(x-3,y+4),(x+3,y-4)],2)
        elif sid == 26:  # branched multi-axis lightning net
            for i in budget.take(6):
                a=i*math.tau/6
                pts=[(tx,ty)]
                for j in range(1,5):
                    rr=j*9
                    off=4 if (j+phase)%2 else -4
                    pts.append((round(tx+rr*math.cos(a)-off*math.sin(a)),round(ty+rr*math.sin(a)+off*math.cos(a))))
                line(pts,2)
                x,y=pts[2]
                line([(x,y),(x+round(11*math.cos(a+.7)),y+round(11*math.sin(a+.7)))],1)
        return
    if phase_name != 'impact':
        raise ValueError(phase_name)
    # Per-skill contact shapes; no large filled disc or uniform recoloured star.
    if sid == 6:
        for i in budget.take(5):
            x,y=local(-4+i*4,(i%2*2-1)*(19+phase))
            line([(x-3,y+4),(x,y-5),(x+3,y+2)],2)
    elif sid == 65:
        for radius in (22-phase*2,32-phase*2):
            ellipse(target,radius,radius,1)
        line([local(-5,-22),local(0,-27),local(5,-22)],2)
    elif sid == 143:
        for side in (-1,1):
            line([local(-9,side*20),local(0,side*(28+phase)),local(9,side*20)],3)
    elif sid == 149:
        for i in budget.take(3):
            line([local(-16+i*9,-23),local(-9+i*9,23)],2)
    elif sid == 9:
        for side in (-1,1):
            x,y=local(0,side*22)
            d.arc((x-12,y-8,x+12,y+8),20,300,fill=color,width=2)
    elif sid == 3:
        for i in budget.take(6):
            a=i*math.tau/6
            x,y=tx+round(26*math.cos(a)),ty+round(26*math.sin(a))
            d.polygon([(x-3,y),(x,y-5),(x+3,y),(x,y+5)],outline=color,width=2)
    elif sid == 94:
        for i in budget.take(3):
            x,y=tx-17+i*16,ty+20+phase
            line([(x,y),(x-2,y+6+i*2)],3)
    elif sid == 131:
        for i in budget.take(4):
            ellipse((tx-24+i*16,ty+20+(i%2)*5),4,2)
    elif sid == 59:
        for i in budget.take(4):
            line([local(-22+i*12,18),local(-18+i*12,25+phase),local(-15+i*12,19)],2)
    elif sid == 130:
        for side in (-1,1):
            line([local(-15,side*18),local(-6,side*27),local(4,side*20),local(15,side*30)],2)
    elif sid == 31:
        for i in budget.take(5):
            x,y=local(8,(i-2)*11)
            light(d,x,y,color)
    elif sid == 34:
        x,y=local(16,0)
        line([(x-6,y-18),(x+7,y-9),(x-4,y),(x+7,y+9),(x-6,y+18)],2)
    elif sid == 76:
        for i in budget.take(6):
            x,y=tx-32+i*13,ty+19+(i%2)*8
            d.polygon([(x-3,y),(x,y-4),(x+3,y+1),(x,y+3)],fill=color)
    elif sid == 95:
        for i in budget.take(5):
            x,y=tx-26+i*13,ty+20-(i%2)*6+phase
            d.rectangle((x,y,x+2,y+3),fill=color)
    elif sid == 18:
        for side in (-1,1):
            line([local(-18,side*25),local(0,side*19),local(18,side*25)],1)
    elif sid == 26:
        for side in (-1,1):
            line([(tx+side*24,ty-16),(tx+side*19,ty-4),(tx+side*27,ty+5),(tx+side*22,ty+18)],2)


def draw_authored(img, profile, source, target, age, windup, budget, emblem):
    sid=profile['species_id']
    color=TYPE_COLORS[profile['type']]
    if age < windup:
        draw_charge(img,(source[0],source[1]+16),max(0,age/windup),color)
        draw_authored_phase(img,sid,'charge',source,target,int((age+1e-8)*10),color,budget,emblem)
        return
    phase=int((age-windup+1e-8)*10)
    if not 0 <= phase < 6:
        return
    draw_authored_phase(img,sid,'body',source,target,phase,color,budget,emblem)
    draw_authored_phase(img,sid,'impact',source,target,phase,color,budget,emblem)
    draw_contact_field(img,sid,target,phase,color,budget)


def draw_contact_field(img, sid, target, phase, color, budget):
    """Large OPEN semantic silhouettes survive short-range body-mask clipping.

    Each field is separately drawn; there is no common circular impact stamp.
    Their strokes expand beyond the 32/34px sprite, never fill its silhouette.
    """
    d=ImageDraw.Draw(img)
    x,y=target
    k=phase*2
    def stroke(points,width=3):
        _stroke(d,[(round(x+a),round(y+b)) for a,b in points],color,width)
    if sid==6:  # a rising five-tongue flame crown, two offset sheets
        for offset in (0,8):
            pts=[(-39-offset,21),(-31-offset,0),(-28-offset,8),(-26-offset,-22),(-18-offset,-8),
                 (-12-offset,-36-k),(-4-offset,-16),(4+offset,-43-k),(12+offset,-18),
                 (24+offset,-32),(21+offset,-2),(33+offset,-12),(31+offset,13),(40+offset,23)]
            # Alternate individual flame tips, including the final release frame;
            # a slowly expanding static outline alone loses attack presence.
            pts=[(a + (2 if (i+phase)%2 else -2), b + (2 if phase%2 else -2))
                 for i,(a,b) in enumerate(pts)]
            stroke(pts,3)
    elif sid==65:
        for rr in (26+phase,42-phase):
            d.ellipse((x-rr,y-rr,x+rr,y+rr),outline=color,width=2)
        for i in budget.take(4):
            a=i*math.pi/2+phase*.2
            light(d,x+round(43*math.cos(a)),y+round(43*math.sin(a)),PAPER)
    elif sid==143:  # rectilinear shock gates from an overcharged beam
        for rr in (26+k,37+k):
            stroke([(-rr,-rr//2),(-rr,-rr),(rr,-rr),(rr,-rr//2)],3)
            stroke([(-rr,rr//2),(-rr,rr),(rr,rr),(rr,rr//2)],3)
            stroke([(-rr-5,-rr//2),(-rr-5,rr//2)],2)
            stroke([(rr+5,-rr//2),(rr+5,rr//2)],2)
    elif sid==149:  # rotating opposed claw sweeps around a broken triangular orbit
        for side in (-1,1):
            for off in (0,9,18):
                pts=[(side*(20+j*2),-36+off+round(j*j*.22)+k) for j in range(13)]
                stroke(pts,3)
        stroke([(-35,20),(0,43+k),(35,20)],2)
    elif sid==9:  # twin water lobes with a hard centre collision seam
        for side in (-1,1):
            for off in (0,8):
                pts=[(side*(16+off+round(23*math.sin(j*math.pi/16))),-39-k+j*5) for j in range(17)]
                stroke(pts,3)
        stroke([(-15,-31),(0,-39-k),(15,-31)],2)
        stroke([(-15,31),(0,39+k),(15,31)],2)
    elif sid==3:  # six huge hollow petals, continuous light at their roots
        for i in budget.take(6):
            a=i*math.tau/6
            pts=[]
            for rr,off in ((21,0),(35+k,-.25),(47+k,0),(35+k,.25),(21,0)):
                pts.append((rr*math.cos(a+off),rr*math.sin(a+off)))
            stroke(pts,3)
    elif sid==94:  # asymmetric drooping tongue loop; no regular halo
        for off in (0,8):
            stroke([(-36-off,-19),(-27-off,-31),(-6,-35),(23+off,-28),(35+off,-10),
                    (34+off,18+k),(21,33+k),(-4,38+k),(-29-off,28),(-39-off,8),(-30,-6)],3)
        stroke([(-20,22),(-13,43+k),(0,46+k),(12,38+k),(17,19)],2)
    elif sid==131:  # cresting broad water fan, horizontal ribs with recurved ends
        for j in range(4):
            yy=-36+j*22
            pts=[(-49-k,yy+8),(-42-k,yy),(-26,yy-8),(0,yy-12),(26,yy-8),(42+k,yy),(49+k,yy+8)]
            stroke(pts,3 if j%2==0 else 2)
    elif sid==59:  # racing ground fire banks with serrated, wind-blown tips
        for side in (-1,1):
            stroke([(side*18,-36),(side*30,-43-k),(side*27,-23),(side*44,-33),
                    (side*36,-11),(side*51,-18),(side*42,5),(side*53,12),(side*35,30),(side*21,36)],3)
        stroke([(-42,40+k),(-20,31),(0,40),(20,31),(42,40+k)],3)
    elif sid==130:  # alternating serpentine pressure fronts with white spine
        for side in (-1,1):
            for off in (0,10):
                pts=[(side*(27+off+round(8*math.sin(j*.55+phase))),-46+j*6) for j in range(17)]
                stroke(pts,3)
    elif sid==31:  # five long needles, separate broad V-shaped pressure traces
        for i in budget.take(5):
            a=math.pi*(.12+i*.19)
            ux,uy=math.cos(a),math.sin(a)
            for side in (-1,1):
                stroke([(side*21*ux,side*21*uy),(side*(43+k)*ux-uy*5,side*(43+k)*uy+ux*5),
                        (side*(52+k)*ux,side*(52+k)*uy)],2)
    elif sid==34:  # squared helical puncture funnel, three increasingly large teeth
        for side in (-1,1):
            stroke([(side*21,-40),(side*41,-30),(side*26,-17),(side*(47+k),-5),
                    (side*29,9),(side*(45+k),23),(side*23,40)],3)
        stroke([(-20,-43),(0,-53-k),(20,-43)],3)
        stroke([(-20,43),(0,53+k),(20,43)],3)
    elif sid==76:  # terraced earthquake faults follow ground perspective
        for j in range(3):
            yy=24+j*10+k
            stroke([(-65,yy),(-49,yy-6),(-33,yy-2),(-17,yy-9),(0,yy-4),
                    (17,yy-10),(33,yy-3),(49,yy-7),(65,yy)],2)
        for side in (-1,1):
            stroke([(side*25,-29),(side*38,-15),(side*30,-4),(side*45,12)],3)
    elif sid==95:  # five faceted boulders, each hollow and structurally separate
        for i in budget.take(5):
            a=i*math.tau/5-.5
            xx,yy=round((35+k)*math.cos(a)),round((33+k)*math.sin(a))
            stroke([(xx-10,yy-4),(xx-5,yy-12),(xx+7,yy-10),(xx+13,yy+2),
                    (xx+4,yy+12),(xx-9,yy+8),(xx-10,yy-4)],3)
            stroke([(xx-5,yy-6),(xx+3,yy),(xx-4,yy+6)],1)
    elif sid==18:  # two feathered wing crescents crossing above/below target
        for side in (-1,1):
            for off in (0,8,16):
                pts=[(-48+j*6,side*(19+off+round(15*math.sin(j*math.pi/16)))+side*k) for j in range(17)]
                stroke(pts,3 if off==0 else 2)
    elif sid==26:  # lightning branches link into an irregular six-sided cage
        pts=[]
        for i in range(6):
            a=i*math.tau/6
            rr=47+k+(4 if (i+phase)%2 else -4)
            pts.extend([(rr*math.cos(a),rr*math.sin(a)),((rr-9)*math.cos(a+.25),(rr-9)*math.sin(a+.25)),
                        ((rr+3)*math.cos(a+.42),(rr+3)*math.sin(a+.42))])
        stroke(pts+pts[:1],2)
        for i in budget.take(6):
            a=i*math.tau/6
            stroke([(28*math.cos(a),28*math.sin(a)),(39*math.cos(a+.2),39*math.sin(a+.2)),
                    ((53+k)*math.cos(a),(53+k)*math.sin(a))],2)
