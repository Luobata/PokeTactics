#!/usr/bin/env python3
"""Focused behavioral evidence for refinement, separate from visibility thresholds."""
import copy
import hashlib
import json
import math
from unittest.mock import patch
from PIL import Image, ImageDraw, ImageChops
import pixel_vfx as v
import render_battle_gif as r
from profile_range import make_scene
from refinement_evidence import OUT


def checks():
    failures, readings = [], {}
    def require(ok, message):
        if not ok:
            failures.append(message)
    def layer():
        return Image.new('RGBA',(240,320))
    color = r.TYPE_COLORS['FIRE']
    a,b = (20,100),(200,100)
    arc = [v.trajectory_point(a,b,i/10,'arc') for i in range(11)]
    require(arc[0] == a and arc[-1] == b, 'arc endpoints')
    require(arc[2][0]-arc[0][0] > arc[-1][0]-arc[-3][0], 'fast launch / slow arrival')
    require(min(y for x,y in arc)<100, 'parabolic lift')
    readings['arc_positions'] = arc
    point = lambda p:v.trajectory_point(a,b,p)
    trail = v.trail_samples(point,.3,.6)
    require(trail == [point((.3-i*.025)/.6) for i in range(5)], 'historical positions')
    slow = v.trail_samples(point,.3,1.2)
    length = lambda ps:math.dist(ps[0],ps[-1])
    require(length(trail) == 2*length(slow), 'tail length proportional to velocity')
    short_tail = v.trail_samples(point,v.exposure_age(0,.1),.1)
    short_segments = sum(a!=b for a,b in zip(short_tail,short_tail[1:]))
    require(short_segments >= 3 and v.exposure_age(0,.1) < .1,
            'one-frame short shot has historical tail before arrival')
    readings['short_shot_visible_segments'] = short_segments
    readings['trail'] = {'segments':4,'history_interval_ms':25,'positions':trail,
                         'length_fast_px':length(trail),'length_half_speed_px':length(slow)}
    silhouettes = {}
    atlas = Image.new('RGBA',(240*3,140*3),r.NIGHT)
    for row,kind in enumerate(('FIRE','PSYCHIC','WATER')):
        digests=[]
        for col,age in enumerate((.2,.3,.4)):
            img=layer(); budget=r.ParticleBudget()
            color = r.TYPE_COLORS[kind]
            v.projectile(img,point,age,.6,kind,color,budget)
            if kind == 'PSYCHIC':
                center = point(age/.6)
                require(bool(img.getpixel(center)[3]) == (round(age*10)%2==1),
                        'traveling psychic center alternates even over tail')
            require(budget.used == 5, 'head + four tail segments budget')
            require(all(p[3] in (0,255) and (not p[3] or p[:3] in (color,r.PAPER))
                        for p in img.getdata()), f'opaque palette {kind}')
            digests.append(hashlib.sha256(img.tobytes()).hexdigest())
            x,y = point(age/.6)
            detail = Image.new('RGBA',(60,30),r.NIGHT)
            detail.alpha_composite(img.crop((x-45,y-15,x+15,y+15)))
            atlas.paste(detail.resize((240,120),Image.Resampling.NEAREST),(col*240,row*140+20))
            ImageDraw.Draw(atlas).text((col*240+4,row*140+3),f'{kind} {age:.1f}s / 4x',fill=r.PAPER)
        silhouettes[kind]=digests
    # Fixed location but changing time proves semantic animation independent of travel.
    fixed=lambda p:(100+round(p*4),100)
    imgs=[]
    for age in (.2,.3):
        im=layer();v.projectile(im,fixed,age,10,'PSYCHIC',color,r.ParticleBudget());imgs.append(im)
    require(imgs[0].getpixel((100,100))[3] == 0 and imgs[1].getpixel((100,100))[3] == 255,
            'psychic hollow/solid alternation')
    readings['projectile_sha256']=silhouettes
    atlas.save(OUT/'projectile-details.png')
    calls=[]
    original=ImageDraw.ImageDraw.ellipse
    def ellipse(draw,box,*args,**kwargs):
        calls.append((box,kwargs.get('width',1)))
        return original(draw,box,*args,**kwargs)
    im=layer();budget=r.ParticleBudget()
    with patch.object(ImageDraw.ImageDraw,'ellipse',ellipse):
        v.impact_rim(im,(100,100),29,color,0,budget)
    require([w for box,w in calls]==[1,2] and budget.used==6,'double rim 1/2px, six rays')
    readings['impact_rim']={'widths_px':[w for box,w in calls], 'rays':budget.used,
                            'radius_px':[(box[2]-box[0])/2 for box,w in calls]}
    star=layer();v.impact_star(ImageDraw.Draw(star),100,100,11,0,color,7)
    require(star.getpixel((100,100))[:3]==r.PAPER and star.getpixel((101,101))[:3]==r.PAPER,
            '2x2 white core')
    sprite=Image.new('RGBA',(12,12),color)
    im=v.feather_flash(sprite)
    edge=[im.getpixel((x,0))[:3] for x in range(12)]
    # Nonopaque padding defines a true silhouette edge for min-filter erosion.
    sprite=Image.new('RGBA',(12,12));ImageDraw.Draw(sprite).rectangle((2,2,9,9),fill=color)
    flash=v.feather_flash(sprite);recovery=v.feather_flash(sprite,True)
    require(sum(flash.getpixel((x,2))[:3]==r.PAPER for x in range(2,10))==4,'50 percent edge checker')
    require(flash.getpixel((5,5))[:3]==r.PAPER and recovery.getpixel((5,5))[:3]==color,'one-frame edge recovery')
    bounds = []
    for direction in ((1,0),(0,1)):
        hit = v.hit_sprite(sprite,direction)
        x0,y0,x1,y1 = hit.getbbox();bounds.append([x1-x0,y1-y0])
        require(hit.width==sprite.width,'fixed-width sprite ABI')
    require(bounds==[[7,9],[9,7]],'directional one-pixel squeeze')
    readings['hit_pose']={'opaque_sizes':bounds, 'source_opaque_size':[8,8], 'edge_coverage':.5}
    rises=[v.number_rise(i*.1) for i in range(8)]
    require(max(rises)==3 and rises[-1]==2 and rises[0]==0,'3px throw, 1px fall')
    readings['damage_number_rise_px']=rises
    digit_boxes=[]
    for heavy in (False, True):
        im=layer();r.BattleAnimation._draw_damage_number(im,(100,100),'-42',r.PAPER,1,heavy)
        digit_boxes.append(im.getbbox())
    require(digit_boxes[1] == tuple(v+d for v,d in zip(digit_boxes[0],(-1,-1,1,1))),
            'heavy digit adds exactly one outline pixel on every side')
    readings['digit_bounds_normal_heavy']=digit_boxes
    # Assert actual production integration at impact/pre-impact/recovery times.
    previews=[]; hits=[]
    for sid in (6,65,143,76):
        anim=make_scene(sid,'dummy',7)
        ev=next(e for e in anim.events if e[1]=='attack' and e[2]==0)
        at=ev[0]+anim._attack_delay(ev)
        for offset in (-.2,-.1,0,.1):
            t=at+offset;anim._ensure(t)
            probe=copy.copy(anim);probe.events=[e for e in anim.events[:anim._cursor] if e[1] in ('move','deploy') or e is ev]
            probe._cursor=len(probe.events);probe.cutins=[]
            im=layer();probe._draw_impact_preview(im,t)
            pixels=im.width*im.height-im.getchannel('A').histogram()[0]
            require(pixels==(4 if offset==-.1 else 0),f'one-frame four-corner preview {sid}/{offset}')
            target=probe.units[ev[3]]
            direction=probe._impact_direction(target,t)
            require((direction is not None)==(offset==0),f'one-frame impact deformation {sid}/{offset}')
            previews.append({'species':sid,'offset':offset,'marker_pixels':pixels})
            hits.append({'species':sid,'offset':offset,'direction':direction})
    readings['production_previews']=previews;readings['production_hit_directions']=hits
    # Saturation includes semantic heads, tails and rings without exceeding 192.
    budget=r.ParticleBudget(1000);im=layer()
    for _ in range(100):
        v.projectile(im,point,.3,.6,'WATER',color,budget)
        v.impact_rim(im,(100,100),29,color,0,budget)
    require(budget.used==192,'semantic particle saturation')
    readings['saturated_particles']=budget.used
    return {'readings':readings,'failures':failures,'passed':not failures}

if __name__=='__main__':
    result=checks();OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'refinement.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    raise SystemExit(0 if result['passed'] else 1)
