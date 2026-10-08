"""Web-only articulated pixel actors sampled from local source-sprite parts.

No animation changes the battle, uses randomness, or replaces the source art.
Polygon masks follow the inspected occupied 56px Machamp/Scizor and 54px Raichu
sprites. Limbs rotate around real shoulder/wrist attachment points rather than
moving a rectangular chunk of the torso. The fixed padded canvas has a stable
foot anchor; every named emission anchor follows its own limb.
"""
from dataclasses import dataclass
from functools import lru_cache
import math

from PIL import Image, ImageChops, ImageDraw, ImageOps


@dataclass(frozen=True)
class Limb:
    name: str
    outline: tuple
    distal: tuple
    root: tuple
    elbow: tuple
    tip: tuple
    layer: int=1


# Coordinates are in each inspected, occupied reference sprite, not canvas %.
# Rear arms are separate from both front arms and from the head/torso/feet.
MACHAMP = (
    Limb('fist_0', ((0,12),(4,9),(7,6),(12,2),(17,0),(22,0),(25,3),(25,8),
                    (22,11),(20,12),(19,15),(19,20),(18,25),(16,29),(10,28),
                    (10,22),(11,20),(8,21),(3,19),(0,15)),
         ((0,12),(4,9),(7,6),(12,2),(17,0),(22,0),(25,3),(25,8),(22,11),
          (19,14),(17,18),(11,20),(8,21),(3,19),(0,15)),
         (16,26),(11,18),(20,5),-1),
    Limb('fist_1', ((11,24),(15,23),(19,25),(23,27),(24,31),(22,34),(18,35),
                    (14,35),(12,37),(10,40),(5,39),(1,36),(0,32),(2,28),(6,26),(11,26)),
         ((0,30),(4,26),(8,26),(12,29),(15,31),(15,35),(12,38),(10,40),
          (5,39),(1,36),(0,32)),
         (22,29),(14,32),(5,33),1),
    Limb('fist_2', ((40,3),(44,0),(48,0),(52,3),(55,6),(56,14),(56,23),
                    (53,27),(49,27),(45,25),(42,24),(40,22),(40,16),(45,16),
                    (47,15),(45,12),(42,12),(40,9)),
         ((40,3),(44,0),(48,0),(52,3),(55,6),(56,14),(56,20),(53,23),
          (49,21),(48,17),(45,12),(42,12),(40,9)),
         (42,23),(52,21),(47,5),-1),
    Limb('fist_3', ((34,21),(38,20),(41,22),(45,25),(47,28),(50,27),(53,29),
                    (53,33),(51,36),(49,38),(47,40),(42,42),(35,42),(33,38),
                    (32,34),(35,31),(36,28),(34,26)),
         ((35,33),(39,30),(44,29),(48,27),(52,29),(53,32),(51,36),
          (49,38),(47,40),(42,42),(35,42),(33,38),(32,35)),
         (37,24),(44,32),(40,38),2),
)
SCIZOR = (
    Limb('claw_0', ((0,25),(14,25),(18,27),(21,29),(24,28),(28,30),(29,33),
                    (26,37),(21,38),(18,44),(12,46),(3,45),(0,40)),
         ((0,25),(14,25),(18,27),(22,30),(22,36),(18,44),(12,46),(3,45),(0,40)),
         (28,30),(21,33),(6,34),1),
    Limb('claw_1', ((35,29),(39,28),(42,28),(45,25),(50,25),(55,29),(55,42),
                    (53,46),(45,47),(42,42),(41,37),(37,37),(34,34)),
         ((41,29),(45,25),(50,25),(55,29),(55,42),(53,46),(45,47),(42,42),(41,37)),
         (35,30),(41,34),(51,35),1),
    Limb('wing_0', ((14,0),(19,0),(22,3),(22,8),(24,11),(24,15),(23,21),
                    (18,21),(16,17),(15,12),(14,8)),
         (), (20,18),(20,18),(17,3),-2),
    Limb('wing_1', ((38,4),(42,0),(51,0),(54,3),(55,6),(55,13),(53,17),
                    (49,21),(43,23),(40,21),(38,16),(38,9)),
         (), (40,21),(40,21),(49,3),-2),
)
RAICHU = (
    Limb('tail', ((35,15),(37,12),(39,10),(41,7),(45,4),(49,0),(54,0),
                  (54,24),(51,29),(54,35),(54,48),(49,52),(41,53),
                  (36,50),(35,47),(40,48),(42,47),(46,44),(46,36),
                  (44,29),(41,22),(37,22),(34,20)),
         (), (37,48),(37,48),(46,13),-1),
    Limb('ear_0', ((8,15),(8,8),(10,4),(14,1),(19,0),(19,4),(16,8),
                    (16,13),(15,16),(11,16)),
         (), (12,14),(12,14),(16,3),1),
    Limb('ear_1', ((23,16),(23,9),(25,7),(28,3),(33,1),(38,1),(38,4),
                    (35,7),(34,11),(33,15),(32,19),(28,19),(25,17)),
         (), (27,16),(27,16),(34,4),1),
)
RIGS = {68:((56,56),MACHAMP),212:((55,56),SCIZOR),26:((54,54),RAICHU)}


def supports(sid):
    return sid in RIGS


def _point(point,size,reference):
    return (point[0]*size[0]/reference[0],point[1]*size[1]/reference[1])


def _polygon_mask(size,outline,reference):
    mask=Image.new('L',size)
    ImageDraw.Draw(mask).polygon([_point(point,size,reference) for point in outline],fill=255)
    return mask


def _masked(source,mask):
    out=source.copy()
    out.putalpha(ImageChops.multiply(source.getchannel('A'),mask))
    return out


@lru_cache(maxsize=192)
def _split(size,rgba,sid):
    """Cache source-only masks/parts; callers receive no mutable cached image."""
    source=Image.frombytes('RGBA',size,rgba)
    reference,limbs=RIGS[sid]
    used=Image.new('L',size)
    parts=[]
    # Each source pixel belongs to one limb, preserving the original at rest.
    # Foreground limbs own overlaps, rear limbs yield to them.
    owned={}
    for limb in sorted(limbs,key=lambda part:part.layer,reverse=True):
        mask=_polygon_mask(size,limb.outline,reference)
        mask=ImageChops.subtract(mask,used)
        owned[limb.name]=mask
        used=ImageChops.lighter(used,mask)
    body=_masked(source,ImageChops.invert(used))
    for limb in limbs:
        mask=owned[limb.name]
        distal=ImageChops.multiply(mask,_polygon_mask(size,limb.distal,reference)) if limb.distal else mask
        upper=ImageChops.subtract(mask,distal)
        parts.append((limb,_masked(source,upper),_masked(source,distal),
                      _point(limb.root,size,reference),_point(limb.elbow,size,reference),
                      _point(limb.tip,size,reference)))
    return body,tuple(parts)


def _rotate_point(point,pivot,angle):
    rad=math.radians(angle)
    c,s=math.cos(rad),math.sin(rad)
    x,y=point[0]-pivot[0],point[1]-pivot[1]
    return pivot[0]+c*x-s*y,pivot[1]+s*x+c*y


def _affine(image,canvas_size,native_pivot,world_pivot,angle,pad):
    rad=math.radians(angle)
    c,s=math.cos(rad),math.sin(rad)
    px,py=world_pivot[0]+pad,world_pivot[1]+pad
    matrix=(c,s,native_pivot[0]-c*px-s*py,
            -s,c,native_pivot[1]+s*px-c*py)
    return image.transform(canvas_size,Image.Transform.AFFINE,matrix,Image.Resampling.NEAREST)


def _ease(p):
    return p*p*(3-2*p)


def _pulse(p,center,width=.23):
    q=max(0.,1-abs(p-center)/width)
    return q*q*(3-2*q)


def _angles(sid,index,state,p,cast):
    """Individual joint keys: no single whole-sprite rotation substitutes for them."""
    if sid==68:
        upper_charge=(17,13,-17,-11)
        elbow_charge=(23,-20,-23,20)
        strike_upper=(-48,-30,42,26)
        strike_elbow=(-14,36,16,-34)
        if state in ('idle','walk'):
            return (math.sin(p*math.tau+index*1.1)*2.5,
                    math.sin(p*math.tau+index*1.3)*3)
        if state=='windup':
            q=_ease(p)
            return upper_charge[index]*q,elbow_charge[index]*q
        if state=='strike':
            # Four different fists lead at p=0,.25,.5,.75 in a 20Hz cast.
            order=(0,2,1,3)
            center=order.index(index)*.25+.03
            hit=_pulse(p,center,.25 if cast else .46)
            hold=.40*(1-p)
            return upper_charge[index]*hold+strike_upper[index]*hit,elbow_charge[index]*hold+strike_elbow[index]*hit
        if state=='recover':
            q=(1-_ease(p))
            return (strike_upper[index]*.12+upper_charge[index]*.1)*q,elbow_charge[index]*.25*q
        if state=='hit':
            return (-1 if index<2 else 1)*8*(1-p),(-1 if index%2 else 1)*6*(1-p)
    elif sid==212:
        if index>=2:
            angle=math.sin(p*math.tau+index*.8)*7
            if state=='windup':
                angle=(-1 if index==2 else 1)*15*_ease(p)
            elif state=='strike':
                angle=(-1 if index==2 else 1)*(20+13*math.sin(p*math.pi))
            elif state=='recover':
                angle=(-1 if index==2 else 1)*20*(1-_ease(p))
            return angle,0
        sign=-1 if index==0 else 1
        if state in ('idle','walk'):
            return sign*math.sin(p*math.tau)*2,sign*math.sin(p*math.tau+.9)*3
        if state=='windup':
            return sign*22*_ease(p),-sign*31*_ease(p)
        if state=='strike':
            hit=_pulse(p,.10 if index==0 else .58,.42)
            return -sign*39*hit,sign*32*hit
        if state=='recover':
            return -sign*8*(1-_ease(p)),sign*9*(1-_ease(p))
        if state=='hit':
            return sign*12*(1-p),sign*9*(1-p)
    elif sid==26:
        if index==0:
            if state in ('idle','walk'):
                return math.sin(p*math.tau)*9,0
            if state=='windup':
                return -18*_ease(p),0
            if state=='strike':
                return -18+43*math.sin(p*math.pi*.72),0
            if state=='recover':
                return 15*(1-_ease(p)),0
            if state=='hit':
                return -10*(1-p),0
        sign=-1 if index==1 else 1
        if state in ('idle','walk'):
            return sign*math.sin(p*math.tau+index*.4)*5,0
        if state=='windup':
            return sign*20*_ease(p),0
        if state=='strike':
            return -sign*16*math.sin(p*math.pi),0
        if state=='recover':
            return -sign*5*(1-_ease(p)),0
        if state=='hit':
            return sign*10*(1-p),0
    return 0.,0.


def _joint_patch(source,point,radius):
    """Local original-colour shoulder/elbow overlap prevents a detached cut seam."""
    mask=Image.new('L',source.size)
    d=ImageDraw.Draw(mask)
    x,y=point
    d.ellipse((x-radius,y-radius,x+radius,y+radius),fill=255)
    return _masked(source,mask)


def render_articulated(source,sid,state,progress,facing=1,action_kind='attack',motion_scale=1.):
    """Return a local RGBA actor, or None for unsupported species/death.

    ``progress`` is normalized within windup/strike/recover. Idle is a periodic
    normalized phase. A caller must freeze that phase when the unit is frozen.
    The pipeline never infers targets, timing, health, or simulation decisions.
    """
    if not supports(sid) or state=='death':
        return None
    if not math.isfinite(progress):
        raise ValueError('articulated progress must be finite')
    if (type(motion_scale) not in (int, float) or not .5 <= motion_scale <= 1.5
            or not math.isfinite(motion_scale)):
        raise ValueError('articulated motion_scale must be in .5–1.5')
    if source.mode!='RGBA':
        source=source.convert('RGBA')
    if source.getchannel('A').getbbox() is None:
        raise ValueError('articulated source must contain visible artwork')
    p=progress%1. if state in ('idle','walk') else min(1.,max(0.,progress))
    pad=math.ceil(max(source.size)*.42)+4
    canvas_size=(source.width+pad*2,source.height+pad*2)
    out=Image.new('RGBA',canvas_size)
    body,parts=_split(source.size,source.tobytes(),sid)
    foot=((source.width-1)/2,source.height-1)
    # Only the torso breathes; feet and all action positions stay planted.
    breath=math.sin(p*math.tau)*.012*motion_scale if state in ('idle','walk') else 0.
    sy=1+breath
    def body_point(point):
        return point[0],foot[1]+(point[1]-foot[1])*sy
    body_y=(1/sy)
    body_canvas=body.transform(canvas_size,Image.Transform.AFFINE,
        (1,0,-pad,0,body_y,foot[1]-(pad+foot[1])*body_y),Image.Resampling.NEAREST)
    rendered=[]
    anchors={'foot':(pad+foot[0],pad+foot[1])}
    rig_parts={'body':{'layer':0,'joints':{'foot':anchors['foot']},'source':'original_pixels'}}
    cast=action_kind=='cast'
    for index,(limb,upper,distal,root,elbow,tip) in enumerate(parts):
        shoulder_angle,elbow_angle=_angles(sid,index,state,p,cast)
        shoulder_angle *= motion_scale
        elbow_angle *= motion_scale
        world_root=body_point(root)
        elbow_rot=_rotate_point(elbow,root,shoulder_angle)
        world_elbow=(elbow_rot[0]+world_root[0]-root[0],elbow_rot[1]+world_root[1]-root[1])
        lower_angle=shoulder_angle+elbow_angle
        tip_rot=_rotate_point(tip,elbow,lower_angle)
        world_tip=(tip_rot[0]+world_elbow[0]-elbow[0],tip_rot[1]+world_elbow[1]-elbow[1])
        upper_image=_affine(upper,canvas_size,root,world_root,shoulder_angle,pad)
        lower_image=_affine(distal,canvas_size,elbow,world_elbow,lower_angle,pad)
        # The two rotations share an exact elbow point. Tiny source-sampled
        # circular overlaps are the only repair, never a rectangle through torso.
        local=Image.new('RGBA',canvas_size)
        if limb.distal:
            radius=max(1.8,source.width/56*2.5)
            local.alpha_composite(_affine(_joint_patch(source,root,radius),canvas_size,root,world_root,0,pad))
            local.alpha_composite(upper_image)
            local.alpha_composite(_affine(_joint_patch(source,elbow,radius),canvas_size,elbow,world_elbow,lower_angle,pad))
        local.alpha_composite(lower_image)
        rendered.append((limb.layer,local))
        point=(round(pad+world_tip[0],2),round(pad+world_tip[1],2))
        anchors[limb.name]=point
        rig_parts[limb.name]={
            'layer':limb.layer,'source':'polygon_source_pixels',
            'joints':{'root':(round(pad+world_root[0],2),round(pad+world_root[1],2)),
                      'elbow':(round(pad+world_elbow[0],2),round(pad+world_elbow[1],2)),
                      'tip':point},
            'angles':(round(shoulder_angle,2),round(elbow_angle,2)),
        }
    for layer,image in sorted(rendered,key=lambda part:part[0]):
        if layer<0:
            out.alpha_composite(image)
    out.alpha_composite(body_canvas)
    for layer,image in sorted(rendered,key=lambda part:part[0]):
        if layer>=0:
            out.alpha_composite(image)
    if sid==26:
        cheek=body_point((source.width*13/54,source.height*22/54))
        anchors['cheek']=(round(pad+cheek[0],2),round(pad+cheek[1],2))
    # The inspected native sprites face left; positive facing matches the shared rig API.
    if facing>=0:
        out=ImageOps.mirror(out)
        anchors={name:(out.width-1-point[0],point[1]) for name,point in anchors.items()}
        for part in rig_parts.values():
            part['joints']={name:(out.width-1-point[0],point[1]) for name,point in part['joints'].items()}
    out.info['foot_anchor']=anchors['foot']
    out.info['rig_anchors']=anchors
    out.info['rig_parts']=rig_parts
    out.info['articulated_species']=sid
    return out
