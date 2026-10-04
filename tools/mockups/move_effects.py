"""Original, bounded pixel cels for eight core moves (desktop reference renderer).

The choreography borrows the charge / stream / contact separation of handheld
battles; all cels below are original. No simulation, random generator or clock is
owned here. ``draw_move_effect`` receives a phase and normalized progress from
the authoritative presentation timeline. Every sprite or path consumes budget.
"""
from functools import lru_cache
import math
from numbers import Real

from PIL import Image, ImageDraw

SUPPORTED_SPECIES = (6, 9, 3, 26, 65, 94, 76, 143)
DEFAULT_VISUAL = {'palette': 'classic', 'effect_scale': 1.,
                  'particle_density': 1., 'motion_scale': 1.}
RANGES = {'effect_scale': (.7, 1.3), 'particle_density': (.5, 1.),
          'motion_scale': (.5, 1.5)}
FAMILIES = {6: 'flame', 9: 'water', 3: 'solar', 26: 'electric',
            65: 'psychic', 94: 'tongue', 76: 'earth', 143: 'beam'}
# Existing primitives can be reused by new species without joining the eight
# bespoke choreography entries. These are effect motifs, never gameplay rules.
OUTCOME_MOTIFS = {'line_push': 9, 'solar_siphon': 3, 'chain_lightning': 26,
                  'energy_drain': 94, 'quake_break': 76,
                  'splash': 6, 'blink_strike': 65, 'slam_heal': 143}
MOVE_NAMES = {6: '喷射火焰', 9: '水炮', 3: '日光束', 26: '十万伏特',
              65: '精神强念', 94: '舌舔', 76: '地震', 143: '破坏光线'}
# Four opaque inks per move; zero is transparent. No intermediate alpha/blur.
PALETTES = {
    'flame': (((103,43,43),(213,73,35),(247,161,49),(255,237,166)),
              ((119,26,62),(246,70,30),(255,192,28),(255,252,211))),
    'water': (((34,64,106),(48,112,176),(99,188,214),(220,249,241)),
              ((29,47,140),(22,126,231),(46,223,245),(226,255,255))),
    'solar': (((55,83,44),(102,145,55),(191,207,76),(254,248,179)),
              ((37,85,70),(68,183,65),(210,239,55),(255,255,224))),
    'electric': (((117,69,45),(201,126,30),(248,206,57),(255,253,194)),
                 ((117,56,85),(239,133,22),(255,231,28),(255,255,238))),
    'psychic': (((67,48,99),(132,78,163),(202,142,213),(254,230,244)),
                ((64,28,115),(163,66,220),(236,130,250),(255,243,255))),
    'tongue': (((65,41,89),(120,63,134),(213,105,151),(252,198,207)),
               ((55,24,100),(117,40,172),(239,80,162),(255,212,239))),
    'earth': (((77,60,48),(130,94,65),(187,150,94),(237,210,147)),
              ((91,49,42),(165,95,47),(222,164,78),(255,231,151))),
    'beam': (((99,63,62),(175,110,56),(240,185,71),(255,250,206)),
             ((97,42,82),(221,104,30),(255,209,48),(255,255,243))),
}

# Three distinct cels per material. Small silhouettes survive native 240x320.
# Values are palette indices, not grayscale: dark contour -> material -> core.
CELS = {
 'flame': (
  ('000001000','000012100','000123100','001233210','001234321','012344321','123443210','012332100','001110000'),
  ('000100000','001210010','012321121','012343221','123444321','123443210','012332100','001210000','000100000'),
  ('000010000','001121000','012332100','123443210','123444321','012343210','001232100','000110000','000000000')),
 'water': (
  ('000010000','000121000','001232100','012334210','123344321','123443321','012333210','001222100','000111000'),
  ('000111000','001232100','012344210','123443321','123333321','012333210','001222100','000110000','000000000'),
  ('000000000','000111000','001234100','012344210','123443321','012333210','001222100','000111000','000000000')),
 'solar': (
  ('000000010','000001121','000012321','000123421','001234210','012342100','123321000','122110000','011000000'),
  ('000011000','000123100','001234210','012344321','123443210','123332100','012221000','001110000','000000000'),
  ('000000000','000001110','000123321','012344321','123443210','123321000','011100000','000000000','000000000')),
 'electric': (
  ('000012100','000123100','001234100','012343210','123444321','012343210','001234100','000123100','000012100'),
  ('001210000','001321000','000342100','012343210','123444321','012343210','001243000','000123100','000012100'),
  ('000010000','010121010','001232100','012343210','123444321','012343210','001232100','010121010','000010000')),
 'psychic': (
  ('000010000','000121000','001232100','012040210','123404321','012040210','001232100','000121000','000010000'),
  ('000111000','001202100','012030210','120040021','123404321','120040021','012030210','001202100','000111000'),
  ('000010000','000141000','001202100','012030210','140404041','012030210','001202100','000141000','000010000')),
 'tongue': (
  ('000000000','000111000','001233100','012334210','123344321','123333321','012333210','001111100','000000000'),
  ('000000000','000011100','001123310','012333421','123344321','123333210','011111100','000000000','000000000'),
  ('000000000','000000000','001111000','012333100','123344210','123333321','012333210','001111100','000000000')),
 'earth': (
  ('000110000','001231000','012343100','123433210','123332210','012322100','001111000','000000000','000000000'),
  ('000011000','001123100','012334210','123432210','123332210','012222100','001111000','000000000','000000000'),
  ('000000000','000111000','001232100','012343210','123332221','123222210','011111100','000000000','000000000')),
 'beam': (
  ('000111000','001232100','012343210','123444321','123444321','123444321','012343210','001232100','000111000'),
  ('000010000','001121100','012333210','123444321','123444321','123444321','012333210','001121100','000010000'),
  ('000000000','000111000','001232100','012343210','123444321','012343210','001232100','000111000','000000000')),
}


def normalize_overrides(overrides=None):
    """Validate and copy an instance config. Unknown fields never silently pass."""
    if overrides is None:
        return {}
    if not isinstance(overrides, dict):
        raise ValueError('visual_overrides must be a species-to-settings object')
    result = {}
    for key, values in overrides.items():
        if isinstance(key, bool) or not (isinstance(key, int) or
                isinstance(key, str) and key.isdecimal()):
            raise ValueError('visual species keys must be integer ids')
        sid = int(key)
        if sid not in SUPPORTED_SPECIES:
            raise ValueError(f'unsupported visual species: {sid}')
        if sid in result:
            raise ValueError(f'duplicate visual species: {sid}')
        if not isinstance(values, dict) or set(values)-set(DEFAULT_VISUAL):
            raise ValueError(f'invalid visual fields for species {sid}')
        config = dict(DEFAULT_VISUAL)
        for name, value in values.items():
            if name == 'palette':
                if value not in ('classic', 'vivid'):
                    raise ValueError('palette must be classic or vivid')
            elif (isinstance(value, bool) or not isinstance(value, Real) or
                  not math.isfinite(value) or not RANGES[name][0] <= value <= RANGES[name][1]):
                raise ValueError(f'{name} must be in {RANGES[name]}')
            config[name] = value
        result[sid] = config
    return result


def effect_profile(sid, overrides=None):
    """Return a detached settings value; a preview cannot mutate another one."""
    return {**DEFAULT_VISUAL, **(overrides or {}).get(sid, {})}


@lru_cache(maxsize=768)
def pixel_cel(family, frame=0, palette='classic', size=9, angle=0):
    """Cached original atlas cel. Callers only paste it, never mutate it."""
    rows = CELS[family][frame % 3]
    colors = PALETTES[family][palette == 'vivid']
    image = Image.new('RGBA', (9, 9))
    data = [(0,0,0,0) if value=='0' else (*colors[int(value)-1],255)
            for row in rows for value in row]
    image.putdata(data)
    if size != 9:
        image = image.resize((size,size),Image.Resampling.NEAREST)
    if angle:
        image = image.rotate(angle,Image.Resampling.NEAREST,expand=True)
    return image


class _Painter:
    def __init__(self, image, sid, config, budget, frame):
        self.image, self.family, self.config = image, FAMILIES[sid], config
        self.budget, self.frame = budget, frame
        self.colors = PALETTES[self.family][config['palette']=='vivid']
        self.scale = config['effect_scale']

    def count(self, count):
        return max(1,math.ceil(count*self.config['particle_density']))

    def stamp(self, xy, size=9, frame=None, angle=0, family=None):
        if not self.budget.take(1):
            return
        tile = pixel_cel(family or self.family,self.frame if frame is None else frame,
                         self.config['palette'],max(3,round(size*self.scale)),angle)
        self.image.alpha_composite(tile,(round(xy[0]-tile.width/2),round(xy[1]-tile.height/2)))

    def path(self, points, width=3, inner=True):
        if not self.budget.take(1):
            return
        points=[(round(x),round(y)) for x,y in points]
        draw=ImageDraw.Draw(self.image)
        draw.line(points,fill=self.colors[0],width=max(1,round((width+2)*self.scale)))
        draw.line(points,fill=self.colors[2],width=max(1,round(width*self.scale)))
        if inner:
            draw.line(points,fill=self.colors[3],width=max(1,round((width-2)*self.scale)))

    def tongue(self, source, target, width):
        """Jagged widening flame silhouette with an inset hot core, one entity."""
        if not self.budget.take(1):
            return
        dx,dy=target[0]-source[0],target[1]-source[1]
        length=math.hypot(dx,dy) or 1
        nx,ny=-dy/length,dx/length
        draw=ImageDraw.Draw(self.image)
        for index,mult in enumerate((1.,.78,.43)):
            points=[]
            for side in (-1,1):
                for i in (range(7) if side<0 else reversed(range(7))):
                    q=i/6
                    radius=(2+q*width)*mult*self.scale
                    radius*=.76 if (i+self.frame)%2 else 1.
                    cx,cy=_mix(source,target,q)
                    points.append((round(cx+nx*radius*side),round(cy+ny*radius*side)))
            draw.polygon(points,fill=self.colors[index+1],outline=self.colors[index])


def _mix(a,b,t):
    return a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t


def draw_blink_fragments(image, center, progress, budget, config, *, arriving=False):
    """Four converging/dispersing psychic plates frame the real body echo."""
    paint=_Painter(image,65,config,budget,int(progress*6))
    radius=(10+progress*12 if arriving else 21-progress*10)*paint.scale
    count=paint.count(4)
    for i in range(count):
        theta=math.pi/4+i*math.tau/count
        point=(center[0]+math.cos(theta)*radius,center[1]+math.sin(theta)*radius)
        paint.stamp(point,8 if arriving else 7,frame=i+paint.frame)


def draw_skill_effect(image, sid, effect, source, target, age, budget, config=None,
                      payload=None, *, arch=None):
    """Material feedback for an actual, causally scheduled skill_effect record.

    Links start at the authoritative impact, not at an invented second hit time.
    The caller supplies the logged pre-effect positions. No target selection or
    resource change is reconstructed by this drawing function.
    """
    if not math.isfinite(age) or not 0 <= age < .45:
        return
    motif = OUTCOME_MOTIFS.get(arch, sid if sid in SUPPORTED_SPECIES else None)
    if motif is None:
        return
    payload = payload or {}
    p = age / .45
    paint = _Painter(image, motif, config or effect_profile(sid), budget, int(age/.05))
    if effect == 'side_hit' and payload.get('damage', 0) > 0:
        if motif == 26:
            dx, dy = target[0]-source[0], target[1]-source[1]
            length = math.hypot(dx, dy) or 1
            points = [_mix(source, target, i/8) for i in range(9)]
            points = [(x + (0 if i in (0,8) else (-1)**(i+paint.frame)*4)*-dy/length,
                       y + (0 if i in (0,8) else (-1)**(i+paint.frame)*4)*dx/length)
                      for i, (x,y) in enumerate(points)]
            paint.path(points, 2 if age < .2 else 1)
            paint.stamp(target, 11 if age < .2 else 5)
        elif motif == 9:
            paint.path([source,target], 4 if age < .2 else 2)
            for i in range(paint.count(3)):
                paint.stamp((target[0]+(i-1)*8, target[1]+p*8), 7-i)
        elif motif == 76:
            floor_a, floor_b = (source[0],source[1]+17), (target[0],target[1]+17)
            mid = _mix(floor_a,floor_b,.5)
            paint.path([floor_a,(mid[0]-3,mid[1]+3),floor_b],2,False)
            for i in range(paint.count(3)):
                paint.stamp((floor_b[0]+(i-1)*9, floor_b[1]-math.sin(p*math.pi)*8),7+i)
    elif effect == 'heal' and payload.get('amount', 0) > 0:
        # A leaf/solar return identifies the supported ally; the plus is outside
        # its silhouette so it survives the sprite exclusion mask.
        for i in range(paint.count(4)):
            q = min(1., max(0., p*1.6-i*.12))
            x,y = _mix(source,target,q)
            paint.stamp((x,y-math.sin(q*math.pi)*12),6,frame=i+paint.frame)
        x,y = target[0]+18,target[1]-16
        paint.path([(x-3,y),(x+3,y)],1,False)
        paint.path([(x,y-3),(x,y+3)],1,False)
    elif effect == 'energy_drain' and payload.get('stolen', 0) > 0:
        for i in range(paint.count(4)):
            q=min(1.,max(0.,p*1.6-i*.1))
            x,y=_mix(source,target,q)
            paint.stamp((x,y+math.sin(q*math.pi)*(-9 if i%2 else 9)),5,frame=i+paint.frame)
    elif effect == 'flinch':
        # Existing status icon carries the state; these three short shock marks
        # identify the moment of application without extending its duration.
        if age < .2:
            for i in range(3):
                x,y=target[0]+(i-1)*9,target[1]-22
                paint.path([(x,y-4),(x,y)],1,False)


def draw_move_effect(image, sid, source, target, phase, progress, budget, config=None,
                     *, basic=False, anchors=None):
    """Draw one phase without advancing state; return nothing.

    ``phase`` is charge / flight / impact / aftermath, progress is [0,1].
    All coordinates are native board pixels. Core primary attacks use ``basic``
    for a smaller projectile/contact; secondary hit timings stay authoritative.
    """
    if sid not in SUPPORTED_SPECIES or phase not in ('charge','flight','impact','aftermath'):
        return
    if not math.isfinite(progress) or not 0 <= progress <= 1:
        return
    config=effect_profile(sid) if config is None else config
    anchors = anchors or {}
    source_name = ('left_vine_tip' if basic else 'flower_focus') if sid == 3 else 'mouth'
    source = anchors.get(source_name, source)
    p=progress; frame=int(p*6)
    paint=_Painter(image,sid,config,budget,frame)
    dx,dy=target[0]-source[0],target[1]-source[1]
    length=math.hypot(dx,dy) or 1
    normal=(-dy/length,dx/length)
    direction=(dx/length,dy/length)
    def local(center,along=0,across=0):
        return (center[0]+direction[0]*along+normal[0]*across,
                center[1]+direction[1]*along+normal[1]*across)
    angle=round(-math.degrees(math.atan2(dy,dx))+90)
    if basic:
        if phase=='flight':
            sources = ([anchors['left_muzzle'], anchors['right_muzzle']]
                       if sid == 9 and all(k in anchors for k in ('left_muzzle','right_muzzle')) else [source])
            for origin in sources:
                for j in reversed(range(paint.count(3))):
                    q=max(0,p-j*.075)
                    paint.stamp(_mix(origin,target,q),7-j*2,frame=frame+j,angle=angle)
        elif phase in ('impact','aftermath'):
            for i in range(paint.count(5 if phase=='impact' else 3)):
                theta=i*2.399+sid*.1
                radius=(14+p*12)*paint.scale
                paint.stamp((target[0]+math.cos(theta)*radius,
                             target[1]+math.sin(theta)*radius),5 if phase=='impact' else 3,frame=i+frame)
        return
    if phase=='charge':
        # A breathing core plus material gathering, never a universal ring.
        count=paint.count(6 if sid in (3,65,26) else 4)
        if sid==9:
            for side in (-1,1):
                muzzle=anchors.get('left_muzzle' if side == -1 else 'right_muzzle',
                                   (source[0]+side*13,source[1]-7))
                paint.stamp(muzzle,7+round(p*3),frame=frame+side)
                paint.stamp((muzzle[0],muzzle[1]-8*(1-p)),4,frame=frame)
        elif sid==76:
            for i in range(count):
                x=source[0]+(i-(count-1)/2)*11
                paint.stamp((x,source[1]+16-round(p*3)),6+(i%2)*2,frame=i+frame)
        elif sid==94:
            for side in (-1,1):
                paint.stamp((source[0]+side*(18-p*5),source[1]-4-p*4),8,frame=frame+side)
            paint.stamp(local(source,14),7+round(p*3),frame=frame)
        else:
            center=(source if 'flower_focus' in anchors else (source[0],source[1]-12)) if sid==3 else local(source,13)
            for i in range(count):
                theta=(i/count*math.tau)+(p*.6 if sid==65 else 0)
                r=(22*(1-p)+7)*paint.scale
                paint.stamp((center[0]+math.cos(theta)*r,center[1]+math.sin(theta)*r),
                            6 if sid!=3 else 8,frame=i+frame,angle=(i*45 if sid==3 else 0))
            if sid in (6,26,143):
                paint.stamp(center,7+round(p*5),frame=frame)
        return
    if phase=='flight':
        if sid==6:
            head=_mix(source,target,p)
            paint.tongue(local(source,8),head,9)
            for i in range(paint.count(6)):
                q=p*(i+1)/paint.count(6)
                center=local(_mix(source,target,q),0,
                             (-1 if i%2 else 1)*(3+q*7))
                paint.stamp(center,8+round(q*8),frame=i+frame,angle=angle)
        elif sid==9:
            # Continuous twin jets, faceted foam edges and independent droplets.
            count=paint.count(5)
            for side in (-1,1):
                muzzle=anchors.get('left_muzzle' if side == -1 else 'right_muzzle',
                                   local(source,0,side*8))
                points=[local(_mix(muzzle,target,p*i/8),0,
                              side*4*p*i/8+(1 if (i+frame)%2 else -1))
                        for i in range(9)]
                paint.path(points,width=6)
                for i in range(count):
                    q=max(0,p-i*.11)
                    spread=side*6*q
                    paint.stamp(local(_mix(muzzle,target,q),0,spread),7 if i else 13,
                                frame=i+frame,angle=angle)
        elif sid==3:
            head=_mix(source,target,p)
            paint.path([source,head],width=8)
            for i in range(paint.count(6)):
                q=p*i/max(1,paint.count(6)-1)
                paint.stamp(local(_mix(source,target,q),0,(-1 if i%2 else 1)*5),6,frame=i+frame,angle=angle)
            paint.stamp(head,16,frame=frame)
        elif sid==26:
            count=8
            points=[local(_mix(source,target,p*i/count),0,
                          (0 if i in (0,count) else (-1 if (i+frame)%2 else 1)*(4+i%3)))
                    for i in range(count+1)]
            paint.path(points,3)
            for i in range(paint.count(4)):
                q=p*(i+1)/4
                center=_mix(source,target,q)
                side=(-1 if i%2 else 1)
                end=local(center,-3,side*(20+i%2*7)*paint.scale)
                paint.path([center,local(center,-2,side*5),end],1,False)
                paint.stamp(end,8,frame=i+frame)
        elif sid==65:
            for i in range(paint.count(5)):
                q=max(0,p-i*.08)
                center=local(_mix(source,target,q),0,math.sin(q*9+frame)*10)
                paint.stamp(center,16-i,frame=i+frame)
        elif sid==94:
            # The articulated pink tongue is connected, curls, then retracts.
            points=[]
            for i in range(9):
                q=p*i/8
                points.append(local(_mix(source,target,q),0,math.sin(q*math.pi)*9))
            paint.path(points,5,False)
            for i in range(paint.count(4)):
                q=p*(i+1)/4
                paint.stamp(local(_mix(source,target,q),0,math.sin(q*math.pi)*9),8,frame=i+frame,angle=angle)
            paint.stamp(points[-1],12,frame=frame,angle=angle)
        elif sid==76:
            floor_a=(source[0],source[1]+18);floor_b=(target[0],target[1]+18)
            points=[local(_mix(floor_a,floor_b,p*i/6),0,(-1 if i%2 else 1)*3) for i in range(7)]
            paint.path(points,2,False)
            for i in range(paint.count(6)):
                q=p*(i+1)/6
                paint.stamp(_mix(floor_a,floor_b,q),9+i%3*3,frame=frame+i)
        else:
            # Mouth focus stays ahead of the body; a raised short, broad beam
            # is still legible when the two silhouettes are only one cell apart.
            raised=(source[0],source[1]-9)
            landing=(target[0],target[1]-9)
            head=_mix(raised,landing,p)
            paint.path([raised,head],width=13)
            paint.stamp(local(raised,14),20,frame=frame,angle=angle)
            for i in range(paint.count(7)):
                q=p*i/max(1,paint.count(7)-1)
                center=_mix(raised,landing,q)
                paint.stamp(center,13+(i%2)*3,frame=i+frame,angle=angle)
                if i%2==0:
                    side=-1 if i%4==0 else 1
                    paint.path([local(center,-4,side*13),local(center,4,side*13)],1,False)
            paint.stamp(head,21,frame=frame,angle=angle)
        return
    # Target material breakup. Radial directions use discrete stamps, never an
    # expanding ellipse. Keep the middle free so a unit and HP bar remain clear.
    aftermath=phase=='aftermath'
    count=paint.count((5 if aftermath else 9) if sid!=76 else (5 if aftermath else 7))
    radius=(23+p*(10 if not aftermath else 7))*paint.scale
    for i in range(count):
        theta=(i/count*math.tau)+sid*.13
        size=(5 if aftermath else 11)-(i%2)
        if sid==9:
            # Low transverse water fan; gravity takes over in the last phase.
            side=-1 if i%2 else 1
            point=(target[0]+side*(18+(i//2)*5+p*7)*paint.scale,
                   target[1]+9-(0 if aftermath else math.sin(p*math.pi)*8)+i%3*3+p*6)
        elif sid==76:
            point=(target[0]+(i-(count-1)/2)*8*paint.scale,
                   target[1]+18-(0 if aftermath else (1-p)*(6+i%3*3)))
            size=6 if aftermath else 12+i%3*2
        elif sid==94:
            point=(target[0]+math.cos(theta)*radius,target[1]+math.sin(theta)*radius*.55-p*5)
        else:
            point=(target[0]+math.cos(theta)*radius,
                   target[1]+math.sin(theta)*radius+(p*7 if aftermath and sid in (6,3) else 0))
        paint.stamp(point,size,frame=i+frame,angle=round(theta*180/math.pi) if sid==3 else 0)
        if sid in (26,143) and not aftermath and i%2==0:
            paint.path([local(point,-5),point,local(point,4)],1,False)
    if sid==76 and not aftermath:
        for side in (-1,1):
            y=target[1]+19
            paint.path([(target[0]+side*7,y),(target[0]+side*15,y-2),
                        (target[0]+side*21,y+2),(target[0]+side*(27+p*6),y)],1,False)
