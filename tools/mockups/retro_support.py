"""Original-move-referenced choreography for support casts and real outcomes.

Pinned G3 script observations precede this artwork; see support-reference.md.
Particles, waves and light walls are original drawings, never copied game assets.
Enemy-target casts retain their original choreography. Ally/self casts have a
deliberate assistance or stance track; recovery stars, status removal and full
protective planes exist only for actual authoritative outcome packets.
"""
from functools import lru_cache
import math

from PIL import Image, ImageDraw

from arena_skills import SKILLS
from retro_primitives import palette, settings, cel, put, line, point, burst

SKILL_IDS = (
    'healing_song', 'cleansing_powder', 'moon_blessing', 'aroma_garden',
    'solar_relay', 'star_resonance', 'rescue_tongue', 'life_pulse',
    'barrier_relay', 'frost_shelter', 'watchful_lullaby', 'beacon_relay',
    'moon_guard', 'bliss_chorus', 'verdant_sanctuary',
)
# Chosen from the pinned original scripts BEFORE implementing these tracks.
REFERENCES = {
    'healing_song': ('SING', 'HEAL_BELL'),
    'cleansing_powder': ('SLEEP_POWDER', 'STUN_SPORE', 'HEAL_BELL'),
    'moon_blessing': ('MOONLIGHT', 'WISH'),
    'aroma_garden': ('AROMATHERAPY', 'PETAL_DANCE'),
    'solar_relay': ('SOLAR_BEAM', 'GIGA_DRAIN'),
    'star_resonance': ('BUBBLE_BEAM', 'SWIFT', 'RECOVER'),
    'rescue_tongue': ('LICK', 'RECOVER'),
    'life_pulse': ('EGG_BOMB', 'SOFT_BOILED'),
    'barrier_relay': ('PSYBEAM', 'LIGHT_SCREEN', 'REFLECT', 'BARRIER'),
    'frost_shelter': ('ICY_WIND', 'ICE_BEAM', 'RECOVER'),
    'watchful_lullaby': ('GUST', 'SING', 'HEAL_BELL'),
    'beacon_relay': ('TAIL_GLOW', 'THUNDER_WAVE', 'RECOVER'),
    'moon_guard': ('CONFUSE_RAY', 'REFLECT', 'BARRIER'),
    'bliss_chorus': ('HEAL_BELL', 'MILK_DRINK'),
    'verdant_sanctuary': ('PETAL_DANCE', 'AROMATHERAPY', 'SYNTHESIS'),
}
_TYPES = {entry['id']: entry['type'] for entry in SKILLS.values()}
OUTCOME_EFFECTS = frozenset(('heal', 'cleanse', 'guard', 'shield', 'absorb',
                           'energy', 'energy_drain', 'status', 'flinch',
                           'taunt', 'thorns', 'thorn_hit'))
CONTACT = .22
LIFETIME = .8
_STATUS = {'poison': 'POISON', 'burn': 'FIRE', 'freeze': 'ICE', 'para': 'ELECTRIC',
           'sleep': 'PSYCHIC', 'bound': 'GRASS', 'vulnerable': 'FIGHTING', 'silence': 'NORMAL'}
_STATUS_ALIAS = {'paralysis': 'para', 'paralyzed': 'para', 'frozen': 'freeze',
                 'ice': 'freeze', 'root': 'bound', 'rooted': 'bound', 'vulnerability': 'vulnerable'}


def _p(value):
    value = float(value)
    return min(1., max(0., value)) if math.isfinite(value) else 0.


def _positive(details, *keys):
    for key in keys:
        value = details.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return math.isfinite(value) and value > 0
    return False


def _vec(a, b):
    distance = math.dist(a, b) or 1.
    ux, uy = (b[0]-a[0])/distance, (b[1]-a[1])/distance
    return ux, uy, -uy, ux


def _poly(draw, path, colors):
    draw.polygon(path, fill=colors[2])
    draw.line(path+[path[0]], fill=colors[0], width=1)
    if len(path)>2:
        draw.line(path[:2], fill=colors[4], width=1)


@lru_cache(maxsize=480)
def _particle(kind, colors, variant=0):
    """Small original-like emitted objects, never a species/totem emblem."""
    image, d, (x, y) = cel(20)
    if kind=='note':
        # SING / HEAL_BELL: several independent wavy music-note sprites.
        d.ellipse((x-5, y+2, x+1, y+6), fill=colors[2], outline=colors[0])
        d.line(((x, y+3), (x, y-6), (x+5, y-3)), fill=colors[3], width=2)
        if variant%3==1:
            d.line(((x+5,y-3),(x+5,y+3)),fill=colors[2],width=2)
            d.ellipse((x+1,y+2,x+6,y+5),fill=colors[3])
        d.arc((x-5,y+2,x+1,y+6),0,150,fill=colors[1],width=1)
        d.line(((x-3,y+3),(x-1,y+3)),fill=colors[4],width=1)
        d.line(((x+1,y-6),(x+4,y-4)),fill=colors[4],width=1)
    elif kind=='bubble':
        r=3+variant%3
        d.ellipse((x-r,y-r,x+r,y+r),outline=colors[2],width=2)
        d.line(((x-r+1,y-1),(x-r+2,y-r+1),(x+1,y-r+1)),fill=colors[4],width=1)
    elif kind=='petal':
        # PETAL_DANCE / AROMATHERAPY use moving tiny petals, not a big flower.
        paths=[[(x-6,y+3),(x-3,y-3),(x+6,y-4),(x+3,y+2)],
               [(x-4,y-6),(x+2,y-3),(x+4,y+5),(x-2,y+3)],
               [(x-5,y-3),(x+2,y-4),(x+6,y+3),(x-2,y+3)]]
        _poly(d,paths[variant%3],colors)
        path=paths[variant%3]
        d.polygon((path[0],path[1],(x,y)),fill=colors[1])
        d.polygon((path[1],path[2],(x,y)),fill=colors[3])
        d.line(((x-3,y+1),(x+3,y-2)),fill=colors[4],width=1)
    elif kind=='leaf':
        shape=[(x-8,y+3),(x-5,y-4),(x+2,y-6),(x+8,y-3),(x+4,y+3),(x-2,y+6)]
        _poly(d,shape,colors)
        d.polygon((shape[0],shape[1],shape[2],(x,y)),fill=colors[1])
        d.polygon(((x,y),shape[2],shape[3],shape[4]),fill=colors[3])
        d.line(((x-6,y+3),(x+5,y-3)),fill=colors[4],width=1)
        d.line(((x-1,y),(x-3,y-3)),fill=colors[2],width=1)
    elif kind=='swift_star':
        shape=[]
        for i in range(10):
            angle=-math.pi/2+i*math.pi/5;r=7 if i%2==0 else 3
            shape.append((x+round(math.cos(angle)*r),y+round(math.sin(angle)*r)))
        _poly(d,shape,colors)
        d.polygon((shape[0],shape[1],shape[2],(x,y)),fill=colors[3])
        d.polygon((shape[5],shape[6],shape[7],(x,y)),fill=colors[1])
        d.line(((x,y-4),(x+2,y-1)),fill=colors[4],width=1)
    elif kind=='bell':
        # HEAL_BELL: a compact swinging bell, separate from the note packet.
        d.arc((x-4,y-7,x+4,y+1),180,360,fill=colors[0],width=2)
        d.polygon(((x-4,y-3),(x-4,y+2),(x-6,y+5),(x+6,y+5),(x+4,y+2),(x+4,y-3)),fill=colors[2])
        d.polygon(((x-4,y-3),(x-4,y+2),(x-6,y+5),(x-2,y+3),(x-1,y-4)),fill=colors[1])
        d.line(((x+1,y-4),(x+3,y-2),(x+3,y+2)),fill=colors[4],width=1)
        d.line(((x-6,y+5),(x+6,y+5)),fill=colors[0],width=1)
        d.ellipse((x-1,y+5,x+2,y+8),fill=colors[3])
    elif kind=='ice':
        _poly(d,[(x-3,y+5),(x-4,y),(x+1,y-6),(x+4,y),(x+3,y+4)],colors)
        d.line(((x,y-4),(x+1,y+3)),fill=colors[4],width=1)
    elif kind=='egg':
        # EGG_BOMB: a small physical projectile whose flight precedes rupture.
        d.ellipse((x-6,y-9,x+6,y+8),fill=colors[3],outline=colors[0],width=1)
        d.line(((x-2,y-4),(x-3,y),(x-2,y+2)),fill=colors[4],width=1)
        d.rectangle((x+1,y+2,x+2,y+3),fill=colors[1])
    elif kind=='tongue':
        d.rounded_rectangle((x-7,y-4,x+7,y+4),radius=4,fill=colors[2],outline=colors[0],width=1)
        d.line(((x-5,y-2),(x+5,y-2)),fill=colors[3],width=1)
    elif kind=='orb':
        r=3+variant%2
        d.ellipse((x-r,y-r,x+r,y+r),fill=colors[2])
        d.ellipse((x-r+1,y-r+1,x+r-1,y+r-1),fill=colors[3])
        d.rectangle((x-1,y-2,x+1,y),fill=colors[4])
    elif kind=='heal_star':
        # HealingBlueStar: a faceted, bounded four-ray star, not a HP cross.
        r=4+variant%2
        shape=[(x,y-r),(x+1,y-1),(x+r,y),(x+1,y+1),
               (x,y+r),(x-1,y+1),(x-r,y),(x-1,y-1)]
        d.polygon(shape,fill=colors[2])
        d.line(shape+[shape[0]],fill=colors[1],width=1)
        d.polygon(((x,y-r+1),(x,y),(x+r-1,y),(x+1,y-1)),fill=colors[3])
        d.rectangle((x,y-1,x+1,y),fill=colors[4])
    elif kind=='sparkle':
        # HealingEffect uses small blue stars, not a health cross or large stamp.
        r=3+variant%2
        d.line(((x-r,y),(x+r,y)),fill=colors[3],width=1)
        d.line(((x,y-r),(x,y+r)),fill=colors[3],width=1)
        d.rectangle((x-1,y-1,x+1,y+1),fill=colors[4])
    elif kind=='powder':
        # Powder has a few readable grains, each uneven and dry rather than a
        # flat square. Three levels survive the 620px battlefield downsample.
        d.polygon(((x-4,y),(x-2,y-4),(x+1,y-3),(x+4,y-1),(x+3,y+3),(x-1,y+4)),fill=colors[1])
        d.polygon(((x-2,y),(x-2,y-3),(x+1,y-2),(x+3,y),(x+1,y+2)),fill=colors[2])
        d.rectangle((x-1,y-2,x+1,y),fill=colors[3])
        d.point((x-1,y-2),fill=colors[4])
        if variant%3==1:d.rectangle((x+5,y+3,x+6,y+4),fill=colors[2])
    else:  # Illuminated dust stays subordinate to the principal material.
        d.rectangle((x-1,y-1,x+1,y+1),fill=colors[2 if variant%2 else 3])
        d.point((x-1,y-1),fill=colors[4])
        if variant%3==1:d.point((x+3,y+2),fill=colors[1])
    return image


def _dissolve(image, fraction):
    if fraction<=0:return image
    image=image.copy(); pixels=image.load(); threshold=min(16,round(fraction*16))
    for y in range(image.height):
        for x in range(image.width):
            if ((x//2)*7+(y//2)*11)%16<threshold:pixels[x,y]=(0,0,0,0)
    return image


def _speck(layer, kind, position, colors, scale, variant=0, fade=0, *, turn=0):
    image=_dissolve(_particle(kind,colors,variant),fade)
    if turn:
        image=image.rotate(round(turn),resample=Image.Resampling.NEAREST)
    put(layer,image,position,scale)


def _ring(layer, position, colors, radius, scale=1., flatten=.55, turn=0):
    image,d,(x,y)=cel(48)
    r=max(2,min(21,round(radius)))
    d.ellipse((x-r,y-round(r*flatten),x+r,y+round(r*flatten)),outline=colors[2],width=2)
    d.arc((x-r,y-round(r*flatten),x+r,y+round(r*flatten)),205,295,fill=colors[4],width=1)
    if turn:
        image=image.rotate(turn,resample=Image.Resampling.NEAREST)
    put(layer,image,position,scale)


def _stream(layer, source, target, progress, colors, kind, *, count=6,
            spread=13, wave=1.5, scale=1., density=1., arc=0):
    """Original staggered sprite emission, bounded by the current flight head."""
    ux,uy,nx,ny=_vec(source,target)
    for i in range(max(1,round(count*density))):
        q=progress-i*.072
        if q<0:continue
        center=point(source,target,q)
        wobble=math.sin(q*math.tau*wave+i*.91)*spread*scale
        pos=(center[0]+nx*wobble,center[1]+ny*wobble-math.sin(q*math.pi)*arc*scale)
        material_scale=(.66+(i%3)*.06) if kind in ('note','petal','leaf') else (.48+(i%3)*.08)
        turn=math.sin(q*math.tau*1.7+i)*25 if kind in ('petal','leaf') else math.sin(q*8+i)*12 if kind=='note' else 0
        if kind in ('petal','leaf'):
            pos=(pos[0],pos[1]-math.sin(q*math.pi)*10*scale)
        _speck(layer,kind,pos,colors,scale*material_scale,i,turn=turn)


def _absorb_charge(layer, source, progress, colors, scale, density):
    # SolarBeamAbsorbEffect emits from opposing axes before the continuous beam.
    offsets=((40,40),(-40,-40),(0,40),(0,-40),(40,-20),(40,20),(-40,-20),(-40,20),
             (-20,30),(20,-30),(-20,-30),(20,30),(-40,0),(40,0))
    for i in range(max(3,round(len(offsets)*density))):
        dx,dy=offsets[i]
        q=min(1.,max(0.,progress*1.35-(i%4)*.07))
        shrink=1.-q
        _speck(layer,'orb',(source[0]+dx*shrink*scale*1.7,
                            source[1]+dy*shrink*scale*1.7),colors,scale*.42,i)
    _speck(layer,'orb',source,colors,scale*(.40+.42*progress))


def _beam(layer, source, target, colors, scale, *, power=1., clock=0):
    """SOLAR_BEAM: breathing soft rim, travelling pulses, uninterrupted core."""
    if power<=0:return
    pulse=.5+.5*math.sin(clock*math.tau*3)
    width=(26+5*pulse)*scale*power
    # Local translucent outer strokes add light volume without a screen flash.
    line(layer,(source,target),(*colors[2],28),width+15*scale)
    line(layer,(source,target),(*colors[3],58),width+8*scale)
    for c,w in ((colors[1],width),(colors[2],width*.84),
                (colors[3],width*.64),(colors[4],width*.34)):
        line(layer,(source,target),c,w)
    ux,uy,nx,ny=_vec(source,target)
    for i in range(3):
        q=(clock*3.2+i/3)%1.
        center=point(source,target,q)
        span=(6+3*pulse)*scale
        # Short luminous packets broaden and narrow inside the stable beam.
        line(layer,((center[0]-ux*span,center[1]-uy*span),
                    (center[0]+ux*span,center[1]+uy*span)),colors[4],width*.48)
        _speck(layer,'orb',(center[0]+nx*width*.28,
                           center[1]+ny*width*.28),colors,scale*.34,i)
    _speck(layer,'orb',source,colors,scale*(.65+.10*pulse))


def _tongue(layer, source, head, colors, scale, *, contact=0):
    """A rounded fleshy ribbon tapers from the mouth to its compressing tip."""
    ux,uy,nx,ny=_vec(source,head);distance=math.dist(source,head)
    if distance<1:return
    centers=[];widths=[]
    for i in range(10):
        q=i/9;center=point(source,head,q)
        bend=math.sin(q*math.pi)*(11+contact*5)*scale
        centers.append((center[0]+nx*bend,center[1]+ny*bend))
        widths.append((4+q*5+math.sin(q*math.pi)*2+contact*q*2)*scale)
    def edge(fraction):
        return [(round((x+nx*w*fraction)/3)*3,round((y+ny*w*fraction)/3)*3)
                for (x,y),w in zip(centers,widths)]
    d=ImageDraw.Draw(layer)
    outer=edge(1)+list(reversed(edge(-1)))
    d.polygon(outer,fill=colors[0])
    d.polygon(edge(.82)+list(reversed(edge(-.82))),fill=colors[2])
    d.polygon(edge(.77)+list(reversed(edge(.2))),fill=colors[1])
    line(layer,edge(-.38),colors[3],4*scale)
    line(layer,edge(-.56)[2:8],colors[4],3*scale)
    _speck(layer,'tongue',head,colors,scale*(.80+.14*contact),turn=math.degrees(math.atan2(uy,ux)))


def _psy_wave(layer, center, colors, scale, radius, direction, *, squeeze=.48, fade=0):
    """Gold-ring PSYBEAM reference: hollow volume with a shaded back rim."""
    image,d,(x,y)=cel(48);r=min(20,max(4,round(radius)))
    box=(x-round(r*squeeze),y-r,x+round(r*squeeze),y+r)
    d.ellipse(box,outline=colors[0],width=4)
    d.ellipse(box,outline=colors[2],width=2)
    d.arc(box,275,445,fill=colors[3],width=3)
    d.arc(box,295,343,fill=colors[4],width=1)
    image=_dissolve(image,fade)
    image=image.rotate(-round(direction),resample=Image.Resampling.NEAREST)
    put(layer,image,center,scale*.72)


def _ice_ray(layer, source, head, clock, colors, scale, density, *, power=1):
    """Three connected crystal tracks, with colder rims and angular glints."""
    if power<=0:return
    ux,uy,nx,ny=_vec(source,head)
    for side in (-1,0,1):
        shift=side*11*scale
        a=(source[0]+nx*shift,source[1]+ny*shift)
        b=(head[0]+nx*shift,head[1]+ny*shift)
        if side==0:
            for color,width in ((colors[1],13),(colors[2],9),(colors[3],5)):
                line(layer,(a,b),color,width*scale*power)
        else:line(layer,(a,b),colors[1],3*scale*power)
        for i in range(max(2,round(4*density))):
            q=(clock*1.8+i/4)%1.
            at=point(a,b,q)
            _speck(layer,'ice',at,colors,scale*(.65 if side else .80)*power,
                   i,turn=-math.degrees(math.atan2(uy,ux))-25+side*12)


def _gust(layer, center, clock, colors, scale, *, power=1):
    """Three swept crescent ribbons build a tapered, open-centered spiral."""
    if power<=0:return
    image,d,(x,y)=cel(52)
    for i in range(3):
        r=(9+i*3)*power;yy=y-12+i*11
        box=(x-r,yy-r*.34,x+r,yy+r*.34)
        angle=(clock*230+i*42)%360
        d.arc(box,angle,angle+245,fill=colors[1],width=4)
        d.arc(box,angle+45,angle+205,fill=colors[3],width=2)
        d.arc(box,angle+70,angle+124,fill=colors[4],width=1)
    put(layer,_dissolve(image,max(0.,1-power)*.8),center,scale*.88)


def _moon_rays(layer, center, clock, colors, scale, *, strength=1):
    if strength<=0:return
    for i in range(3):
        q=max(0.,min(1.,clock*1.15-i*.11))
        x=center[0]+(i-1)*22*scale;y=center[1]+(-43+q*65)*scale
        path=[(x-4*scale,y-17*scale),(x+2*scale,y-8*scale),(x,y)]
        line(layer,path,colors[1],7*scale*strength)
        line(layer,path,colors[3],4*scale*strength)
        _speck(layer,'sparkle',(x,y),colors,scale*.55*strength,i)


def _egg_shells(layer, target, life, colors, scale, density):
    if life>=.87:return
    for i in range(max(3,round(5*density))):
        angle=i*math.tau/5+.2
        radius=(8+life*45)*scale
        at=(target[0]+math.cos(angle)*radius,
            target[1]+math.sin(angle)*radius*.65+(life*life*34-life*20)*scale)
        image,d,(x,y)=cel(26)
        shell=[(x-6,y+1),(x-4,y-4),(x-1,y-1),(x+1,y-5),(x+6,y),(x+3,y+6),(x-3,y+5)]
        d.polygon(shell,fill=colors[3],outline=colors[0])
        d.polygon(((x-6,y+1),(x-3,y+5),(x+3,y+6),(x+1,y+2)),fill=colors[1])
        d.line(((x-3,y-1),(x-1,y+2),(x+3,y+1)),fill=colors[4],width=1)
        image=_dissolve(image,max(0.,(life-.50)/.37))
        put(layer,image.rotate(round(i*51+life*(100 if i%2 else -130)),resample=Image.Resampling.NEAREST),at,scale*.62)


def _local_material(layer, key, target, life, colors, scale, density, *, source=None, config=None):
    """One continuous material clock from real contact through its finite tail."""
    source=source or target
    direction=math.degrees(math.atan2(target[1]-source[1],target[0]-source[0]))
    fade=max(0.,(life-.52)/.40)
    if key in ('healing_song','bliss_chorus'):
        count=3 if key=='healing_song' else 5
        for i in range(round(count*density)):
            angle=i*math.tau/count+.5;radius=(13+life*31)*scale
            pos=(target[0]+math.cos(angle)*radius,
                 target[1]+math.sin(angle)*radius*.6-life*24*scale)
            _speck(layer,'note',pos,colors,scale*(.77 if key=='healing_song' else .69),i,fade,
                   turn=math.sin(life*8+i)*15)
        if life<.64:
            _ring(layer,target,colors,7+life*18,scale*.77,flatten=.48)
            if key=='bliss_chorus':
                _ring(layer,(target[0],target[1]+10*scale),colors,6+life*18,scale*.76,flatten=.45)
        if key=='bliss_chorus' and life<.22:
            _speck(layer,'bell',(target[0]-23*scale,target[1]-8*scale),colors,scale*.55,
                   turn=math.sin(life*16)*16)
    elif key=='cleansing_powder':
        for i in range(round(11*density)):
            born=(i%4)*.07;q=(life-born)/(.9-born)
            if not 0<=q<1:continue
            pos=(target[0]+(((i%5)-2)*12+math.sin(q*5+i)*8)*scale,
                 target[1]+(-34+q*65)*scale)
            _speck(layer,'powder',pos,colors,scale*(.68 if i%4==0 else .48),i,
                   max(0.,(q-.58)/.40))
    elif key=='moon_blessing':
        if life<.76:_moon_rays(layer,target,life,colors,scale,strength=1-max(0.,(life-.34)/.42))
        for i in range(3):
            q=max(0.,min(1.,life*1.3-i*.12))
            _speck(layer,'sparkle',(target[0]+(i-1)*25*scale,target[1]+(-35+q*70)*scale),
                   colors,scale*.48,i,fade)
    elif key in ('aroma_garden','verdant_sanctuary'):
        count=7 if key=='aroma_garden' else 8
        for i in range(round(count*density)):
            angle=i*2.17+life*(4 if key=='aroma_garden' else -6)
            radius=(18+life*39+i%3*5)*scale
            pos=(target[0]+math.cos(angle)*radius,
                 target[1]+math.sin(angle)*radius*.5+(life*25 if key=='aroma_garden' else -life*32)*scale)
            kind='leaf' if key=='verdant_sanctuary' and i%2==0 else 'petal'
            _speck(layer,kind,pos,colors,scale*(.79 if i%3==0 else .60),i,
                   max(0.,(life-.56)/.38),turn=math.sin(life*9+i)*34+i*28)
    elif key=='star_resonance':
        gold=palette('ELECTRIC',config or {})
        for i in range(round(6*density)):
            angle=i*2.399+life*2;radius=(10+life*42)*scale
            pos=(target[0]+math.cos(angle)*radius,target[1]+math.sin(angle)*radius*.65-life*16*scale)
            kind='swift_star' if i%3==0 else 'bubble'
            _speck(layer,kind,pos,gold if kind=='swift_star' else colors,
                   scale*(.71 if kind=='swift_star' else .60),i,fade,turn=life*160)
    elif key=='barrier_relay':
        if life<.76:
            for i in range(2):
                _psy_wave(layer,(target[0]+(i*2-1)*life*17*scale,target[1]-life*12*scale),
                          colors,scale,9+life*17+i*2,direction,squeeze=.42+life*.22,fade=fade)
        burst(layer,target,colors,life,scale=scale*.44,density=density,kind='spark',count=4,seed=13)
    elif key=='frost_shelter':
        for i in range(round(7*density)):
            angle=i*2.1+.3;radius=(7+life*52)*scale
            _speck(layer,'ice',(target[0]+math.cos(angle)*radius,
                              target[1]+math.sin(angle)*radius*.45+(life*life*24-life*12)*scale),
                   colors,scale*(.85 if i%3==0 else .56),i,fade,turn=i*21+life*110)
    elif key=='watchful_lullaby':
        _gust(layer,(target[0],target[1]-life*12*scale),life,colors,scale,
              power=max(0.,1-max(0.,(life-.25)/.52)))
        for i in range(2):
            _speck(layer,'note',(target[0]+(i*2-1)*27*scale,target[1]-life*34*scale),
                   colors,scale*.70,i,fade,turn=life*12)
    elif key=='beacon_relay':
        for row in range(3):
            y=target[1]+(row-1)*21*scale;span=(16+life*22)*scale
            vertices=[(target[0]-span,y),(target[0]-span*.65,y-8*scale),
                      (target[0]-span*.24,y+4*scale),(target[0]+span*.1,y-4*scale),
                      (target[0]+span*.58,y+8*scale),(target[0]+span,y)]
            if life<.6:
                line(layer,vertices,colors[1],6*scale);line(layer,vertices,colors[4],3*scale)
        burst(layer,target,colors,life,scale=scale*.66,density=density,count=7,seed=17)
    elif key=='moon_guard':
        if life<.85:
            radius=math.sin(min(1.,life/.23)*math.pi/2)*(17+life*13)*scale
            angle=life*9
            at=(target[0]+math.cos(angle)*radius,target[1]+math.sin(angle)*radius*.7-life*11*scale)
            _speck(layer,'orb',at,colors,scale*(.87-.28*life),0,fade)
            for i in range(2):
                a=angle-(i+1)*.45
                _speck(layer,'orb',(target[0]+math.cos(a)*radius,target[1]+math.sin(a)*radius*.7-life*11*scale),
                       colors,scale*.33,i+1,fade)
    elif key=='life_pulse':
        _egg_shells(layer,target,life,colors,scale,density)
    elif key=='rescue_tongue':
        # Wet contact becomes a few falling drops, not a second ray or hitsplat.
        for i in range(round(4*density)):
            q=min(1.,life/.85);angle=i*2.1+.6
            at=(target[0]+math.cos(angle)*(8+q*27)*scale,
                target[1]+(math.sin(angle)*(7+q*16)+q*q*30)*scale)
            _speck(layer,'orb',at,colors,scale*(.38 if i%2 else .50),i,fade)
    elif key=='solar_relay':
        # Existing beam size stays accepted; only its local release arcs peel off.
        for i in range(round(7*density)):
            angle=i*2.399+life*.8;radius=(9+life*45)*scale
            at=(target[0]+math.cos(angle)*radius,target[1]+math.sin(angle)*radius*.68-life*12*scale)
            _speck(layer,'sparkle',at,colors,scale*(.57 if i%3==0 else .36),i,fade)


def draw(layer, skill_id, source, target, phase, progress, config, *, emitters=(), secondary=False):
    if skill_id not in SKILL_IDS or phase not in ('windup','flight','impact','aftermath'):
        return False
    p=_p(progress);scale,density=settings(config);colors=palette(_TYPES[skill_id],config)
    scale*=.62 if secondary else 1.
    if secondary and phase in ('windup','flight'):return True
    if phase=='aftermath' and p>=1:return True
    # The renderer freezes the actual flower joint at release, not the mouth.
    if skill_id=='solar_relay' and emitters:source=emitters[0]
    if phase=='windup':
        if skill_id=='solar_relay':
            _absorb_charge(layer,source,p,colors,scale,density)
        elif skill_id=='beacon_relay':
            _speck(layer,'orb',source,colors,scale*(.6+.25*math.sin(p*8)))
            for side in (-1,1):
                line(layer,((source[0]+side*22*scale,source[1]-13*scale),
                            (source[0]+side*14*scale,source[1]-6*scale),source),colors[3],3)
        elif skill_id=='life_pulse':
            _speck(layer,'egg',(source[0],source[1]-p*7*scale),colors,scale*.62)
        elif skill_id=='rescue_tongue':
            head=point(source,target,min(1.,p*19*scale/(math.dist(source,target) or 1.)))
            _tongue(layer,source,head,colors,scale*.65)
        elif skill_id=='barrier_relay':
            direction=math.degrees(math.atan2(target[1]-source[1],target[0]-source[0]))
            _psy_wave(layer,source,colors,scale,6+p*8,direction)
        elif skill_id=='bliss_chorus':
            _speck(layer,'bell',(source[0],source[1]-10*scale),colors,scale*.62,
                   turn=math.sin(p*12)*15)
            for i in range(2):
                _speck(layer,'note',(source[0]+(i*2-1)*(11+p*9)*scale,source[1]+4*scale),
                       colors,scale*.57,i)
        else:
            kind={'healing_song':'note','bliss_chorus':'note','watchful_lullaby':'note',
                  'cleansing_powder':'powder','moon_blessing':'sparkle','aroma_garden':'petal',
                  'verdant_sanctuary':'leaf','star_resonance':'bubble','frost_shelter':'ice',
                  'moon_guard':'orb'}[skill_id]
            count=4 if skill_id!='cleansing_powder' else 9
            for i in range(round(count*density)):
                angle=i*2.399+p*(3 if skill_id!='verdant_sanctuary' else -4)
                radius=(7+11*(1-p)+i%3*4)*scale
                at=(source[0]+math.cos(angle)*radius,source[1]+math.sin(angle)*radius*.8)
                _speck(layer,kind,at,colors,scale*(.66 if kind in ('note','petal','leaf') else .5 if kind!='powder' else .4),i,
                       turn=math.sin(p*6+i)*24 if kind in ('petal','leaf') else 0)
        return True
    if phase=='flight':
        head=point(source,target,p)
        if skill_id=='solar_relay':
            _beam(layer,source,head,colors,scale,power=.70+.3*p,clock=p*.16)
        elif skill_id=='rescue_tongue':
            _tongue(layer,source,head,colors,scale)
        elif skill_id=='life_pulse':
            arc=(head[0],head[1]-math.sin(p*math.pi)*49*scale)
            _speck(layer,'egg',arc,colors,scale*.68)
        elif skill_id=='barrier_relay':
            direction=math.degrees(math.atan2(target[1]-source[1],target[0]-source[0]))
            for i in range(4):
                q=p-i*.095
                if q>=0:_psy_wave(layer,point(source,target,q),colors,scale,11+i%2*2,direction)
        elif skill_id=='frost_shelter':
            _ice_ray(layer,source,head,p*.2,colors,scale,density)
        elif skill_id=='star_resonance':
            ux,uy,nx,ny=_vec(source,target)
            _stream(layer,source,target,p,colors,'bubble',count=5,spread=13,scale=scale,density=density)
            for i in range(2):
                q=p-i*.18
                if q>=0:
                    at=point(source,target,q)
                    wobble=math.sin(q*math.pi)*math.sin(q*5+i)*14*scale
                    _speck(layer,'swift_star',(at[0]+nx*wobble,at[1]+ny*wobble),
                           palette('ELECTRIC',config),scale*.70,i,turn=q*150)
        elif skill_id=='verdant_sanctuary':
            _stream(layer,source,target,p,colors,'leaf',count=5,spread=19,wave=1.2,arc=12,scale=scale,density=density)
            _stream(layer,source,target,p,colors,'petal',count=3,spread=9,wave=1.8,scale=scale*.65,density=density)
        elif skill_id=='moon_guard':
            ux,uy,nx,ny=_vec(source,target)
            bend=math.sin(p*math.pi)*22*scale
            _speck(layer,'orb',(head[0]+nx*bend,head[1]+ny*bend),colors,scale*.85,0)
            _stream(layer,source,target,p,colors,'orb',count=3,spread=9,scale=scale*.65,density=density)
        elif skill_id=='moon_blessing':
            _moon_rays(layer,head,p,colors,scale*.78)
        elif skill_id=='watchful_lullaby':
            for i in range(3):
                q=p-i*.11
                if q>=0:
                    at=point(source,target,q)
                    _gust(layer,(at[0],at[1]+(i-1)*9*scale),p+i*.1,colors,scale*(.68-i*.1))
            _stream(layer,source,target,p,colors,'note',count=2,spread=17,scale=scale*.72,density=density)
        else:
            kind={'healing_song':'note','bliss_chorus':'note','cleansing_powder':'powder',
                  'moon_blessing':'sparkle','aroma_garden':'petal','verdant_sanctuary':'petal',
                  'star_resonance':'bubble','frost_shelter':'ice','beacon_relay':'orb','moon_guard':'orb'}[skill_id]
            count={'healing_song':5,'bliss_chorus':8,'cleansing_powder':15,'frost_shelter':11,
                   'beacon_relay':4,'moon_guard':3}.get(skill_id,7)
            spread={'cleansing_powder':27,'bliss_chorus':23,'moon_guard':19,
                    'verdant_sanctuary':19,'frost_shelter':22}.get(skill_id,13)
            _stream(layer,source,target,p,colors,kind,count=count,spread=spread,
                    wave=2. if skill_id=='moon_guard' else 1.5,scale=scale,density=density)
            if skill_id=='beacon_relay':
                ux,uy,nx,ny=_vec(source,target);tail=point(head,source,min(1.,45/(math.dist(source,head) or 1.)))
                bend=point(tail,head,.5);bend=(bend[0]+nx*8,bend[1]+ny*8)
                line(layer,(tail,bend,head),colors[1],9*scale);line(layer,(tail,bend,head),colors[4],3*scale)
        return True
    elapsed=p*CONTACT if phase=='impact' else CONTACT+p*(LIFETIME-CONTACT)
    life=elapsed/LIFETIME
    if skill_id=='solar_relay' and not secondary and elapsed<.34:
        _beam(layer,source,target,colors,scale,power=min(1.,max(0.,(.34-elapsed)/.12)),clock=elapsed+.18)
    elif skill_id=='rescue_tongue' and not secondary and elapsed<.30:
        # LICK contact holds briefly then physically retracts, never a tongue stamp.
        reach=1. if elapsed<.12 else max(0.,(.30-elapsed)/.18)
        _tongue(layer,source,point(source,target,reach),colors,scale,contact=max(0.,1-elapsed/.16))
    elif skill_id=='frost_shelter' and not secondary and elapsed<.24:
        _ice_ray(layer,source,target,elapsed+.2,colors,scale,density,
                 power=max(0.,1-max(0.,(elapsed-.10)/.14)))
    _local_material(layer,skill_id,target,life,colors,scale,density,source=source,config=config)
    return True



def _screen_fragment(layer, position, colors, scale, turn=0):
    """A traveling facet is a casting cue, not an already applied full shield."""
    image,d,(x,y)=cel(22)
    poly=[(x-5,y-8),(x+5,y-10),(x+7,y+7),(x-3,y+10)]
    d.polygon(poly,fill=colors[1])
    d.line(poly+[poly[0]],fill=colors[3],width=1)
    d.line((poly[0],poly[1],poly[2]),fill=colors[4],width=1)
    put(layer,image.rotate(round(turn),resample=Image.Resampling.NEAREST),position,scale*.58)


def draw_assistance(layer, skill_id, source, target, phase, progress, config, *, emitters=()):
    """An ally-directed preparation, flight and arrival with no enemy hitsplat.

    Contact only unfolds the move's casting material. Real heal/cleanse/shield/
    energy packets independently own their outcome; a suppressed or zero benefit
    can never acquire a positive HP cue from this track.
    """
    if skill_id not in SKILL_IDS or skill_id in ('solar_relay','moon_guard'):
        return False
    p=_p(progress);scale,density=settings(config);colors=palette(_TYPES[skill_id],config)
    if phase=='windup':
        # The pinned original cues (bells, moonlight, eggs, pollen) are already
        # nonhostile at the caster and retain their accepted G3 pixel shapes.
        return draw(layer,skill_id,source,target,phase,p,config,emitters=emitters)
    if phase=='flight':
        head=point(source,target,p)
        if skill_id=='rescue_tongue':
            _tongue(layer,source,head,colors,scale)
        elif skill_id=='life_pulse':
            _speck(layer,'egg',(head[0],head[1]-math.sin(p*math.pi)*49*scale),colors,scale*.68)
        elif skill_id in ('moon_blessing','barrier_relay','frost_shelter'):
            # Parallel light facets / snowmist deliver protection. Neither an
            # Ice Beam nor a Psybeam is fired into a friendly recipient.
            ux,uy,nx,ny=_vec(source,target)
            for i in range(round(3*density)):
                q=p-i*.10
                if q<0:continue
                at=point(source,target,q)
                sway=math.sin(q*math.pi)*((i-1)*18+math.sin(q*5+i)*7)*scale
                at=(at[0]+nx*sway,at[1]+ny*sway-8*math.sin(q*math.pi)*scale)
                if skill_id=='frost_shelter':
                    _speck(layer,'ice',at,colors,scale*(.35+i%2*.1),i,turn=q*120)
                    _speck(layer,'powder',(at[0]-nx*9*scale,at[1]-ny*9*scale),colors,scale*.31,i)
                elif skill_id=='moon_blessing':
                    _speck(layer,'sparkle',at,colors,scale*.65,i,turn=q*30)
                else:
                    _screen_fragment(layer,at,colors,scale,turn=math.sin(q*5)*10)
        elif skill_id in ('star_resonance','beacon_relay'):
            # Tail Glow / Recover-style gathered energy follows a curved chain
            # of orbs, distinct from the old offensive water ray and zigzag hit.
            energy=palette('ELECTRIC' if skill_id=='beacon_relay' else 'PSYCHIC',config)
            _stream(layer,source,target,p,energy,'orb',count=5,spread=16,wave=1.8,
                    arc=18,scale=scale*.85,density=density)
            if skill_id=='star_resonance':
                _speck(layer,'swift_star',(head[0],head[1]-math.sin(p*math.pi)*18*scale),
                       palette('ELECTRIC',config),scale*.58,0,turn=p*100)
        elif skill_id=='watchful_lullaby':
            _stream(layer,source,target,p,colors,'note',count=4,spread=21,wave=1.5,
                    arc=12,scale=scale*.93,density=density)
        else:
            kind={'healing_song':'note','bliss_chorus':'note','cleansing_powder':'powder',
                  'aroma_garden':'petal','verdant_sanctuary':'leaf'}[skill_id]
            _stream(layer,source,target,p,colors,kind,count=9 if kind=='powder' else 5,
                    spread=23 if kind=='powder' else 17,wave=1.5,arc=9,
                    scale=scale,density=density)
        return True
    if phase not in ('impact','aftermath'):return False
    elapsed=p*CONTACT if phase=='impact' else CONTACT+p*(LIFETIME-CONTACT)
    life=elapsed/LIFETIME
    if life>=1:return True
    if skill_id in ('moon_blessing','barrier_relay','frost_shelter'):
        # Arrival shards peel around the body. Actual shields alone draw walls.
        for i in range(round(4*density)):
            angle=i*math.tau/4+life*.9;radius=(14+life*28)*scale
            at=(target[0]+math.cos(angle)*radius,target[1]+math.sin(angle)*radius*.65-life*14*scale)
            kind='ice' if skill_id=='frost_shelter' else 'sparkle'
            _speck(layer,kind,at,colors,scale*.43,i,max(0.,(life-.35)/.55),turn=life*70)
    elif skill_id in ('star_resonance','beacon_relay'):
        energy=palette('ELECTRIC' if skill_id=='beacon_relay' else 'PSYCHIC',config)
        for i in range(round(5*density)):
            angle=i*math.tau/5-life*2;radius=(14+life*17)*scale
            at=(target[0]+math.cos(angle)*radius,target[1]+math.sin(angle)*radius*.72-life*20*scale)
            _speck(layer,'swift_star' if skill_id=='star_resonance' else 'orb',at,energy,
                   scale*.48,i,max(0.,(life-.35)/.55),turn=life*50)
    elif skill_id=='watchful_lullaby':
        for i in range(round(3*density)):
            angle=i*math.tau/3+life*1.3;radius=(18+life*18)*scale
            _speck(layer,'note',(target[0]+math.cos(angle)*radius,
                                 target[1]+math.sin(angle)*radius*.60-life*27*scale),
                   colors,scale*.67,i,max(0.,(life-.45)/.45),turn=math.sin(life*6+i)*15)
    elif skill_id=='rescue_tongue':
        if elapsed<.30:
            reach=1. if elapsed<.12 else max(0.,(.30-elapsed)/.18)
            _tongue(layer,source,point(source,target,reach),colors,scale)
        _local_material(layer,skill_id,target,life,colors,scale,density,source=source,config=config)
    else:
        _local_material(layer,skill_id,target,life,colors,scale,density,source=source,config=config)
    return True


def _stance_material(layer, key, target, life, config, *, quiet=False):
    scale,density=settings(config);colors=palette('POISON' if key=='venom_armor' else 'FIRE',config)
    strength=.72 if quiet else 1.-max(0.,(life-.60)/.40)
    if strength<=0:return
    for i in range(round((6 if key=='venom_armor' else 4)*density)):
        if key=='venom_armor':
            angle=i*math.tau/6+life*.55;radius=(23+math.sin(life*7)*2)*scale
            pos=(target[0]+math.cos(angle)*radius,target[1]+math.sin(angle)*radius*.76)
            image,d,(x,y)=cel(22)
            d.polygon(((x-4,y+7),(x-3,y),(x,y-9),(x+3,y),(x+5,y+7)),fill=colors[1])
            d.polygon(((x,y-9),(x+3,y),(x+2,y+5),(x,y+4)),fill=colors[3])
            d.line(((x,y-9),(x+1,y-3)),fill=colors[4],width=1)
            image=_dissolve(image,1-strength)
            put(layer,image.rotate(round(-angle*180/math.pi+90),resample=Image.Resampling.NEAREST),pos,scale*.57)
        else:
            side=-1 if i%2 else 1
            pos=(target[0]+side*(20+i//2*13)*scale,target[1]+(13-i//2*9)*scale)
            image,d,(x,y)=cel(26)
            body=[(x-5,y+7),(x-7,y+2),(x-4,y-3),(x-3,y+1),
                  (x+1,y-11),(x+3,y-4),(x+6,y+2),(x+5,y+7)]
            d.polygon(body,fill=colors[1]);d.polygon(((x-3,y+6),(x-3,y),(x+1,y-6),(x+3,y+2),(x+2,y+7)),fill=colors[3])
            d.polygon(((x-1,y+6),(x,y+1),(x+2,y+5),(x+1,y+7)),fill=colors[4])
            put(layer,_dissolve(image,1-strength),pos,scale*(.52+.05*math.sin(life*8+i)))


def draw_stance(layer, key, source, phase, progress, config):
    """Local Iron Defense/Protect-style stance, with no imagined enemy contact."""
    if key not in ('venom_armor','flame_guard'):return False
    p=_p(progress);scale,density=settings(config);colors=palette('POISON' if key=='venom_armor' else 'FIRE',config)
    if phase in ('windup','flight'):
        q=p*.7 if phase=='windup' else .7+p*.3
        _stance_material(layer,key,source,q*.4,config)
        _ring(layer,(source[0],source[1]+28*scale),colors,12+q*22,scale,flatten=.26)
    elif phase in ('impact','aftermath'):
        q=p*.22 if phase=='impact' else .22+p*.78
        if q<1:
            for i in range(round(4*density)):
                a=i*math.tau/4+q*.8;r=(19+q*32)*scale
                _speck(layer,'powder' if key=='venom_armor' else 'sparkle',
                       (source[0]+math.cos(a)*r,source[1]+math.sin(a)*r*.52),
                       colors,scale*.43,i,max(0.,(q-.35)/.6))
    else:return False
    return True


def draw_field_cast(layer, source, cells, phase, progress, config):
    """Only the authoritative future footprint receives laid rock fragments."""
    from retro_physical import _material_put
    p=_p(progress);scale,density=settings(config);colors=palette('ROCK',config)
    cells=tuple(cells)[:3]
    if phase=='windup':
        for i in range(3):
            _material_put(layer,'rock',(source[0]+(i-1)*18*scale,source[1]+(18-p*20)*scale),
                          colors,scale*(.27+p*.12),i)
    elif phase=='flight':
        for i,cell in enumerate(cells):
            q=min(1.,max(0.,(p-i*.05)/(1-i*.05)))
            pos=point(source,cell,q);pos=(pos[0],pos[1]-math.sin(q*math.pi)*(35+i*13)*scale)
            _material_put(layer,'rock',pos,colors,scale*(.42+i*.07),i,turn=q*95)
    elif phase in ('impact','aftermath'):
        q=p*.25 if phase=='impact' else .25+p*.75
        if q<1:
            for i,cell in enumerate(cells):
                _ring(layer,cell,colors,11+q*22,scale*.7,flatten=.28)
                burst(layer,cell,colors,q,scale=scale*.50,density=density,kind='dust',count=5,seed=i+3)
    else:return False
    return True


def draw_screen(layer, target, progress, config, *, kind='reflect', quiet=False):
    """Light Screen / Reflect / Barrier planar light, shared with persistent state.

    target is actor center, normally foot_y - 34. Nonquiet progress is normalized
    over its actual finite outcome; p>=1 draws nothing. quiet=True has no lifecycle
    and uses progress modulo 1 as a mild sheen phase; caller owns expiry/death.
    """
    if kind not in ('reflect','light_screen','barrier'):return False
    p=_p(progress) if not quiet else float(progress)%1.
    if not quiet and p>=1:return True
    scale,density=settings(config)
    colors=palette({'light_screen':'GRASS','reflect':'ICE','barrier':'STEEL'}[kind],config)
    image,d,(x,y)=cel(52)
    strength=(.46 if quiet else (1.-max(0.,(p-.65)/.35)))
    # Slanted, parallel-edge quadrilateral: explicitly a thin translucent plane.
    plane=[(x-13,y-20),(x+12,y-24),(x+15,y+21),(x-10,y+25)]
    d.polygon(plane,fill=(*colors[2],round(48*strength)))
    d.line(plane+[plane[0]],fill=(*colors[3],round(132*strength)),width=1)
    d.line(((x-11,y-18),(x+10,y-22),(x+13,y+19)),fill=(*colors[4],round(110*strength)),width=1)
    sheen=-19+round(p*37)
    d.line(((x-11,y+sheen+3),(x+12,y+sheen-2)),fill=(*colors[4],round(86*strength)),width=2)
    if not quiet:
        for i in range(round(3*density)):
            q=(p+i*.27)%1.
            xx=x-8+(i%3)*9;yy=y-19+round(q*38)
            d.line(((xx-2,yy),(xx+2,yy)),fill=(*colors[4],round(160*strength)),width=1)
            d.line(((xx,yy-2),(xx,yy+2)),fill=(*colors[3],round(160*strength)),width=1)
    put(layer,image,(target[0]+8*scale,target[1]-4*scale),scale*(.88 if quiet else .91))
    return True


def _screen_kind(key):
    if key=='barrier_relay':return 'barrier'
    if key in ('aroma_garden','verdant_sanctuary','solar_relay'):
        return 'light_screen'
    return 'reflect'


def _healing_plane(draw, center, radius, flatten, colors, opacity, turn):
    """Hollow restorative ring with soft sides and a moving front highlight."""
    x,y=center;h=max(3,round(radius*flatten))
    box=(x-radius,y-h,x+radius,y+h)
    for width,alpha,color in ((5,18,colors[1]),(3,44,colors[2]),(1,102,colors[3])):
        draw.ellipse(box,outline=(*color,round(alpha*opacity)),width=width)
    # Back side remains thin; the brighter curved lip establishes a plane.
    draw.arc(box,18,162,fill=(*colors[3],round(158*opacity)),width=2)
    draw.arc(box,turn,turn+52,fill=(*colors[4],round(188*opacity)),width=1)


def _healing_stars(layer, key, target, p, config, scale, density):
    """Recover gathers light; Soft-Boiled rings open; real blue stars rise.

    At the 620px view this has two separated 45–60px hollow planes and
    three 6–10px main stars. Compact low-alpha cel preserves the recipient's
    face and has no numeric overlay. Actual positive healing owns its lifetime.
    """
    if not 0<=p<1:return
    blue=palette('WATER',config);green=palette('GRASS',config)
    colors=tuple(tuple(round((a+b)/2) for a,b in zip(w,g)) for w,g in zip(blue,green))
    # One bounded local cel; no blur, screen-sized surfaces or render-time RNG.
    image,d,(x,y)=cel(80)
    gather=min(1.,p/.18)
    release=min(1.,max(0.,(p-.14)/.66))
    fade=1.-max(0.,(p-.56)/.44)
    strength=(.55+.45*gather)*fade
    # Stepped transparent light volume. No filled opaque plate over the actor.
    for rx,ry,alpha in ((32,28,6),(28,24,10),(24,21,15),(19,17,19),(12,12,22)):
        lift=round(release*7)
        d.ellipse((x-rx,y-ry-lift,x+rx,y+ry-lift),fill=(*colors[2],round(alpha*strength)))
    lower=(x,y+17-round(release*10))
    upper=(x,y+1-round(release*15))
    _healing_plane(d,lower,round(20+7*gather+4*release),.23,colors,strength,20+p*290)
    _healing_plane(d,upper,round(16+6*gather+4*release),.34,blue,strength*.84,210-p*250)
    if p<.30:
        pulse=max(0.,math.sin(min(1.,p/.30)*math.pi))
        r=max(2,round(4+3*pulse))
        d.ellipse((x-r,y-r,x+r,y+r),fill=(*colors[3],round(52*pulse)))
        d.ellipse((x-2,y-3,x+2,y+2),fill=(*blue[4],round(62*pulse)))
    put(layer,image,target,scale*.5)
    # Three main stars carry silhouette and ascent; density only thins accents.
    for i in range(3):
        born=i*.055
        q=(p-born)/(.86-born)
        if not 0<=q<1:continue
        angle=i*math.tau/3+q*2.7
        side=-1 if i%2 else 1
        radius=(24+6*math.sin(q*math.pi+i))*scale
        at=(target[0]+side*radius,
            target[1]+(23-q*56+math.sin(angle)*7)*scale)
        _speck(layer,'heal_star',at,blue,scale*(.53 if i%2 else .60),i,
               max(0.,(q-.68)/.32))
    for i in range(max(1,round(3*density))):
        born=.14+i*.075
        q=(p-born)/(.97-born)
        if not 0<=q<1:continue
        angle=i*2.4-q*2.1
        at=(target[0]+math.cos(angle)*(34-7*q)*scale,
            target[1]+(18-53*q+math.sin(angle)*8)*scale)
        _speck(layer,'sparkle',at,green,scale*.25,i,max(0.,(q-.68)/.32))
    if p<.24:
        q=p/.24
        for i in range(3):
            angle=i*math.tau/3+.4
            radius=(34*(1-q)+5)*scale
            _speck(layer,'orb',(target[0]+math.cos(angle)*radius,
                               target[1]+math.sin(angle)*radius*.65),colors,scale*.3,i)
    # Keep native healing identity secondary to the common blue-green recovery.
    if key in ('healing_song','watchful_lullaby','bliss_chorus') and p<.80:
        for i in range(2):
            q=min(1.,max(0.,(p-i*.09)/.72))
            at=(target[0]+(i*2-1)*(31+math.sin(q*4)*6)*scale,
                target[1]+(10-q*39)*scale)
            _speck(layer,'note',at,palette(_TYPES[key],config),scale*.40,i,
                   max(0.,(q-.65)/.35),turn=math.sin(q*6+i)*10)
    elif key in ('aroma_garden','verdant_sanctuary') and p<.82:
        for i in range(2):
            q=min(1.,max(0.,(p-i*.08)/.75))
            angle=i*math.pi+q*3
            at=(target[0]+math.cos(angle)*35*scale,
                target[1]+(18-q*45+math.sin(angle)*8)*scale)
            _speck(layer,'petal',at,green,scale*.41,i,max(0.,(q-.65)/.35),
                   turn=math.sin(q*7+i)*28)


def draw_healing(layer, target, progress, config, *, key='recovery'):
    """Finite recovery material for an already validated real healing event.

    The caller owns positive-amount and recipient checks. This helper chooses
    neither recipient nor amount and draws no number. Native keys add their
    original note/petal accents; generic recovery keeps the blue-green material.
    """
    if type(progress) not in (int,float) or not math.isfinite(progress) or progress<0:
        return False
    if progress>=1:return True
    scale,density=settings(config)
    _healing_stars(layer,key,target,progress,config,scale,density)
    return True


def _status_material(layer, target, kind, p, config, scale, density, *, cleansing=False):
    colors=palette(_STATUS[kind],config)
    fade=max(0.,(p-.60)/.38) if not cleansing else min(1.,p*2)
    particle={'poison':'bubble','burn':'powder','freeze':'ice','bound':'petal',
              'sleep':'note','vulnerable':'sparkle','silence':'powder','para':'powder'}[kind]
    for i in range(round(5*density)):
        angle=i*2.4+p*2;radius=(13+i%3*7)*scale
        pos=(target[0]+math.cos(angle)*radius,target[1]+math.sin(angle)*radius*.7-p*25*scale)
        _speck(layer,particle,pos,colors,scale*.5,i,fade)
    if kind=='para' and p<.6:
        for sign in (-1,1):
            x=target[0]+sign*20*scale
            line(layer,((x-4,target[1]-17),(x+4,target[1]-6),(x-3,target[1]),
                        (x+4,target[1]+12)),colors[3],3*scale)


def draw_outcome(layer, skill_id, effect, source, target, progress, config, details):
    """Consume the exact recorded outcome without selecting or manufacturing it."""
    if effect not in OUTCOME_EFFECTS or not isinstance(details,dict):return False
    p=_p(progress)
    if effect=='heal' and not _positive(details,'amount'):return False
    if effect=='guard' and not _positive(details,'reduction'):return False
    if effect in ('shield','absorb','energy') and not _positive(details,'amount'):return False
    if effect=='energy_drain' and not _positive(details,'stolen','amount'):return False
    if effect=='taunt' and not _positive(details,'duration'):return False
    if effect=='thorns' and not _positive(details,'uses'):return False
    if effect=='thorn_hit' and not _positive(details,'damage'):return False
    if effect in ('status','cleanse'):
        kind=details.get('status')
        if not isinstance(kind,str):return False
        kind=_STATUS_ALIAS.get(kind,kind)
        if kind not in _STATUS:return False
    if p>=1:return True
    scale,density=settings(config);colors=palette(_TYPES.get(skill_id,'NORMAL'),config)
    if effect=='heal':
        draw_healing(layer,target,p,config,key=skill_id)
    elif effect in ('guard','shield'):
        draw_screen(layer,target,p,config,kind=_screen_kind(skill_id))
        if skill_id=='frost_shelter':
            _ring(layer,(target[0],target[1]+23*scale),colors,20+9*p,scale,flatten=.27)
        elif skill_id=='moon_blessing':
            _moon_rays(layer,(target[0],target[1]-5*scale),p,colors,scale*.70,strength=1-max(0.,(p-.55)/.45))
    elif effect=='absorb':
        draw_screen(layer,target,min(1.,p*1.4),config,kind='barrier')
        burst(layer,target,palette('ICE',config),p,scale=scale*.62,density=density,kind='shard',count=8,seed=37)
    elif effect in ('energy','energy_drain'):
        energy=palette('ELECTRIC' if skill_id=='beacon_relay' else 'PSYCHIC',config)
        gained=effect=='energy_drain' and _positive(details,'gained')
        recipient=source if gained else target
        if effect=='energy' or gained:
            start,end=(target,source) if gained else (source,target)
            if start!=end and p<.52:
                _stream(layer,start,end,min(1.,p/.52),energy,'orb',count=5,spread=15,
                        wave=1.2,scale=scale*.85,density=density)
            if p>=.14:
                _ring(layer,(recipient[0],recipient[1]+16*scale),energy,
                      21+10*math.sin(min(1.,p/.6)*math.pi),scale,flatten=.32)
                for i in range(round(5*density)):
                    angle=i*math.tau/5+p*4;radius=(25-13*p)*scale
                    _speck(layer,'sparkle',(recipient[0]+math.cos(angle)*radius,
                                           recipient[1]+math.sin(angle)*radius*.6-p*18*scale),
                           energy,scale*.56,i,max(0.,(p-.60)/.38))
        if effect=='energy_drain':
            # No gained resource means no caster cue, returning path or fake gain.
            for i in range(round(5*density)):
                q=(p+i*.08)%1.
                _speck(layer,'powder',(target[0]+((i%3)-1)*12*scale,
                                      target[1]+(q*35-5)*scale),energy,scale*.42,i,
                       max(0.,(p-.60)/.38))
    elif effect=='taunt':
        # An actual taunted enemy receives a red attention bracket, not damage.
        fire=palette('FIRE',config)
        _ring(layer,(target[0],target[1]-20*scale),fire,13+8*p,scale*.72,flatten=.5)
        for side in (-1,1):
            line(layer,((target[0]+side*20*scale,target[1]-24*scale),
                        (target[0]+side*13*scale,target[1]-16*scale)),fire[3],3)
        _speck(layer,'sparkle',(target[0],target[1]-26*scale-p*9*scale),fire,scale*.52,0,
               max(0.,(p-.60)/.40))
    elif effect=='thorns':
        _stance_material(layer,'venom_armor',target,p,config)
    elif effect=='thorn_hit':
        poison=palette('POISON',config)
        burst(layer,target,poison,p,scale=scale*.83,density=density,kind='shard',count=9,seed=31)
    elif effect=='status':
        _status_material(layer,target,kind,p,config,scale,density)
    elif effect=='cleanse':
        _status_material(layer,target,kind,p,config,scale,density,cleansing=True)
        water=palette('WATER',config)
        for i in range(round(4*density)):
            q=min(1.,max(0.,p*1.6-i*.06))
            _speck(layer,'sparkle',(target[0]+(-22+q*44)*scale,
                                   target[1]+(14-i*8-q*22)*scale),water,scale*.45,i,
                   max(0.,(p-.62)/.36))
    else:  # Actual flinch uses a small offset original hitsplat-style flash.
        burst(layer,(target[0],target[1]-14*scale),colors,p,scale=scale*.48,
              density=density,count=5,seed=41)
    return True
