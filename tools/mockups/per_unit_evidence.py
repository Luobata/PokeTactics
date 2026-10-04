#!/usr/bin/env python3
"""16 x six states x three targets, archived baseline, geometry and replay gates.

Read-only sim/data access. Artifacts are written only below reports/. The range
isolates recorded events so idle/death/long windups cannot be hidden by another
action. Cast supplements retain the entire real battle. No acceptance code edits.
"""
import argparse
import copy
import hashlib
import json
import math
import statistics
import subprocess
import sys
import time
import types
from pathlib import Path
from unittest.mock import patch
from PIL import Image, ImageChops, ImageDraw
import render_battle_gif as r
import profile_range as training
from motion import species_motion, RIGS, MotionSystem, Pose, REST, transform, sample, windup
from skill_vfx import AUTHORED_SKILLS, draw_authored_phase, draw_contact_field

OUT = r.ROOT / 'reports/evidence/per-unit-2026-10-04'
STATES = ('idle','walk','windup','strike','hit','death')
FALLBACK_IDS = (19,22,45,134)


def digest(frames):
    return training.frame_hash(frames)


def baseline():
    names = ('profile_vfx','skill_vfx','render_battle_gif','profile_range')
    saved = {name:sys.modules.get(name) for name in names}
    loaded, hashes = {}, {}
    try:
        for name in names:
            path = r.ROOT/'tools/mockups'/f'{name}.py'
            source = subprocess.check_output(['git','show',f'49a0d46:tools/mockups/{name}.py'],cwd=r.ROOT)
            hashes[name] = hashlib.sha256(source).hexdigest()
            module = types.ModuleType(name)
            module.__file__ = str(path)
            sys.modules[name] = module
            exec(compile(source,str(path),'exec'),module.__dict__)
            loaded[name] = module
    finally:
        for name,value in saved.items():
            if value is None:
                sys.modules.pop(name,None)
            else:
                sys.modules[name]=value
    return loaded,hashes


def fixture(sid,scene,state,seed=7):
    """Isolate a real event, preserving its onset/indices/positions and tuple ABI."""
    action = 'death' if state=='death' else 'hit' if state=='hit' else 'move' if state=='walk' else 'attack'
    anim=training.make_scene(sid,scene,seed,action)
    events=anim.events
    if state=='idle':
        event=None
        at=.5
    else:
        kind={'walk':'move','windup':'attack','strike':'attack','hit':'attack','death':'die'}[state]
        candidates=[e for e in events if e[1]==kind and
                    ((e[3]==0 and e[4]>0) if state=='hit' else e[2]==0)]
        if not candidates:
            raise AssertionError((sid,scene,state,'no real event'))
        if state=='walk':
            candidates=[e for e in candidates if e[0]>=.4] or candidates
        event=candidates[0]
        at=event[0]
    deployments=[]
    for idx in anim.units:
        pos=next((e[3] for e in reversed(events) if e[1] in ('deploy','move')
                  and e[2]==idx and e[0] < at+1e-9), anim.units[idx].u.pos)
        if state=='walk' and idx==0:
            pos=next(e[3] for e in reversed(events) if e[1] in ('deploy','move') and e[2]==idx and e[0]<at)
        deployments.append((0.,'deploy',idx,pos))
    anim.events=deployments+([event] if event else [])
    anim.playback_clock=r.PlaybackClock(anim.events)
    anim._reset()
    if state=='idle':
        times=[at+i*.1 for i in range(max(8,len(species_motion.get(sid,{}).get('idle',[]))))]
    elif state=='walk':
        times=[at+i*.1 for i in range(len(species_motion.get(sid,{}).get('walk',[0]*4)))]
    elif state=='windup':
        times=[at+i*.1 for i in range(len(species_motion.get(sid,{}).get('windup',[0,0,0])))]
    elif state=='strike':
        prep=windup(sid) if sid in species_motion else r.HIT_DELAY
        count=len(species_motion[sid]['strike'])+len(species_motion[sid]['recover']) if sid in species_motion else 5
        times=[at+prep+i*.1 for i in range(count)]
    elif state=='hit':
        times=[at+anim._attack_delay(event)+i*.1 for i in range(3)]
    else:
        times=[at+i*.1 for i in range(6)]
    return anim,times,{'event':event,'isolation':'recorded event + deployment at event positions', 'sim_times':times}


def frames_at(anim,times):
    return [anim.playback_frame(anim.playback_clock.playback_time(t),show_cutins=False) for t in times]


def old_fixture(current, old_r):
    old = old_r.BattleAnimation.__new__(old_r.BattleAnimation)
    old.__dict__ = copy.copy(current.__dict__)
    old.units={idx:old_r.AnimUnit(au.u) for idx,au in current.units.items()}
    old._reset()
    return old


def contracts(output):
    failures=[]
    def require(ok,label):
        if not ok: failures.append(label)
    source=Image.new('RGBA',(34,34))
    d=ImageDraw.Draw(source)
    for y in range(3,31):
        for x in range(3,31):
            if (x+y)%5 != 0:
                d.point((x,y),fill=(20+(x%3)*30,20+(y%3)*30,20,255))
    motion_hashes, deformation_hashes, geometry_hashes = {}, {}, {}
    per_state={}
    peak=0
    solids=[]
    polygon=ImageDraw.ImageDraw.polygon
    rectangle=ImageDraw.ImageDraw.rectangle
    ellipse=ImageDraw.ImageDraw.ellipse
    def polygon_probe(draw,xy,*args,**kw):
        if kw.get('fill') is not None:
            solids.append(max(max(p[0] for p in xy)-min(p[0] for p in xy)+1,max(p[1] for p in xy)-min(p[1] for p in xy)+1))
        return polygon(draw,xy,*args,**kw)
    def shape_probe(original):
        def probe(draw,xy,*args,**kw):
            if kw.get('fill') is not None:
                if len(xy)==4: x0,y0,x1,y1=xy
                else: (x0,y0),(x1,y1)=xy
                solids.append(max(abs(x1-x0)+1,abs(y1-y0)+1))
            return original(draw,xy,*args,**kw)
        return probe
    for sid,states in species_motion.items():
        require(set(states)==set(STATES)|{'recover'},f'{sid}: states')
        require(.2<=windup(sid)<=.4,f'{sid}: windup')
        motion_hashes[sid]=hashlib.sha256(json.dumps(states,sort_keys=True).encode()).hexdigest()
        deformed=[]
        for state,frames in states.items():
            for i,f in enumerate(frames):
                im=transform(source,sid,Pose(state,i,f))
                # Keep geometry only, including per-frame translations; common test cel.
                canvas=Image.new('L',(48,48))
                canvas.paste(im.getchannel('A'),(7+f[0],7+f[1]))
                deformed.append(canvas)
        deformation_hashes[sid]=digest(deformed)
        layers={}
        for name in ('charge','body','impact','contact'):
            images=[]
            for phase in range(4 if name=='charge' else 6):
                im=Image.new('RGBA',(240,240))
                budget=r.ParticleBudget()
                with patch.object(ImageDraw.ImageDraw,'polygon',polygon_probe), \
                     patch.object(ImageDraw.ImageDraw,'rectangle',shape_probe(rectangle)), \
                     patch.object(ImageDraw.ImageDraw,'ellipse',shape_probe(ellipse)):
                    if name == 'contact':
                        draw_contact_field(im,sid,(120,120),phase,(255,255,255),budget)
                    else:
                        draw_authored_phase(im,sid,name,(45,120),(160,120),phase,(255,255,255),budget)
                peak=max(peak,budget.used)
                images.append(im.getchannel('A'))
            require(all(im.getbbox() for im in images),f'{sid}/{name}: nonempty')
            layers[name]={'sha256':digest(images),'unique_frames':len({im.tobytes() for im in images})}
        geometry_hashes[sid]=layers['body']['sha256']
        per_state[sid]=layers
        actual=r.pokedex().signature_move(sid)
        require(actual['id']==AUTHORED_SKILLS[sid][0],f'{sid}: actual move_id')
    for name,values in [('motion',motion_hashes),('deformed geometry',deformation_hashes),('skill body',geometry_hashes)]:
        require(len(set(values.values()))==16,f'{name}: pairwise uniqueness')
    require(len({v['contact']['sha256'] for v in per_state.values()})==16,'contact field uniqueness')
    require(max(solids,default=0)<=math.floor(32*.75),'authored solid <=75%')
    # Animation selection, replay/rewind, hit overlay, freeze and death priority.
    runtime={}
    for sid in species_motion:
        states_seen=[]
        for state in STATES:
            anim,times,_=fixture(sid,'melee',state)
            a=frames_at(anim,times)
            b=frames_at(anim,list(reversed(times)))[::-1]
            require(digest(a)==digest(b),f'{sid}/{state}: rewind')
            poses=[]
            for t in times:
                anim._ensure(t)
                pose=MotionSystem.resolve(anim,anim.units[0],t)
                poses.append(pose)
            if state=='hit':
                require(any(p.hit!=REST for p in poses),f'{sid}: hit overlay')
            elif state=='strike':
                require(poses[0].state=='strike' and poses[-1].state=='recover',f'{sid}: strike/recover')
            else:
                require(poses[0].state==state,f'{sid}: {state} event wire')
            states_seen.append(state)
        anim,times,_=fixture(sid,'melee','strike')
        au=anim.units[0]
        t=times[0]
        anim._ensure(t)
        au.statuses['freeze']=t
        require(MotionSystem.resolve(anim,au,t)==MotionSystem.resolve(anim,au,t+.2),f'{sid}: freeze')
        au.die_t=t+.1
        require(MotionSystem.resolve(anim,au,t+.2).state=='death',f'{sid}: death precedence')
        runtime[sid]=states_seen+['recover','freeze','death_priority']
    result={'passed':not failures,'failures':failures,'motion_sha256':motion_hashes,
            'common_cel_geometry_sha256':deformation_hashes,'skill_body_alpha_sha256':geometry_hashes,
            'phase_layers':per_state,'runtime_states':runtime,'authored_solid_max_px':max(solids,default=0),
            'authored_layer_particle_peak':peak,'pairwise_pairs_checked':120}
    (output/'contracts.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print('contracts',result['passed'],failures,flush=True)
    return result


def fallback(output,old_r):
    results=[]
    for sid in FALLBACK_IDS:
        for state in STATES:
            # Enemies 19/22 are also unregistered; dummy (76) is intentionally
            # excluded here because its authored appearance must change.
            current,times,meta=fixture(sid,'ranged',state)
            old=old_fixture(current,old_r)
            # Hit arrival is unaffected: all actors in this fixture use fallback.
            before,after=frames_at(old,times),frames_at(current,times)
            equal=all(a.tobytes()==b.tobytes() for a,b in zip(before,after))
            results.append({'species':sid,'state':state,'frames':len(times),'equal':equal,
                            'before':digest(before),'after':digest(after)})
        current=training.make_scene(sid,'ranged',7,'skill')
        event=next(e for e in current.events if e[1]=='cast' and e[2]==0)
        times=[event[0]+i*.1 for i in range(10)]
        old=old_fixture(current,old_r)
        before,after=frames_at(old,times),frames_at(current,times)
        results.append({'species':sid,'state':'skill','frames':10,
                        'equal':all(a.tobytes()==b.tobytes() for a,b in zip(before,after)),
                        'before':digest(before),'after':digest(after)})
    result={'passed':all(x['equal'] for x in results),'samples':results}
    (output/'fallback.json').write_text(json.dumps(result,indent=2)+'\n')
    print('fallback',result['passed'],[x for x in results if not x['equal']],flush=True)
    return result


def save_clip(output,sid,scene,state,frames,meta):
    rel=Path(str(sid))/scene/state
    dest=output/rel
    dest.mkdir(parents=True,exist_ok=True)
    for i,im in enumerate(frames): im.save(dest/f'frame-{i:03d}.png')
    frames[0].save(dest/'animation.gif',save_all=True,append_images=frames[1:],duration=100,loop=0,disposal=2)
    sheet=Image.new('RGB',(r.W*len(frames),r.H+24),r.PAPER)
    ImageDraw.Draw(sheet).text((4,5),f'{sid} / {scene} / {state}',fill=r.INK)
    for i,im in enumerate(frames): sheet.paste(im.convert('RGB'),(i*r.W,24))
    sheet.save(dest/'contact.png')
    return {'species':sid,'scene':scene,'action':state,'path':rel.as_posix(),'frames':len(frames),
            'sha256':digest(frames),'deterministic':True,**meta}


def range_artifacts(output,old_r):
    clips=[]
    masters=[]
    for sid in species_motion:
        rows=[]
        columns=max(8,len(species_motion[sid]['idle']))
        compare=Image.new('RGB',(r.W*2*len(STATES),r.H+24),r.PAPER)
        for si,scene in enumerate(training.SCENES):
            for j,state in enumerate(STATES):
                anim,times,meta=fixture(sid,scene,state)
                frames=frames_at(anim,times)
                again,tt,_=fixture(sid,scene,state)
                assert digest(frames)==digest(frames_at(again,tt)),(sid,scene,state)
                clips.append(save_clip(output,sid,scene,state,frames,meta))
                row=Image.new('RGB',(r.W*columns,r.H+24),r.PAPER)
                ImageDraw.Draw(row).text((4,5),f'{sid} / {scene} / {state}',fill=r.INK)
                for k,im in enumerate(frames): row.paste(im.convert('RGB'),(k*r.W,24))
                rows.append(row)
                if si==1:
                    ix=min(1,len(times)-1)
                    legacy=old_fixture(anim,old_r).frame(times[ix],show_cutins=False)
                    compare.paste(legacy.convert('RGB'),(j*2*r.W,24))
                    compare.paste(frames[ix].convert('RGB'),((j*2+1)*r.W,24))
                    ImageDraw.Draw(compare).text((j*2*r.W+4,5),f'{sid}/{state}   49a0d46 | AUTHORED',fill=r.INK)
            # Full Battle skill sample: checks the actual move and event adapter.
            anim=training.make_scene(sid,scene,7)
            event=next(e for e in anim.events if e[1]=='cast' and e[2]==0)
            times=[event[0]+i*.1 for i in range(round(r.cast_windup(sid)*10)+6)]
            frames=frames_at(anim,times)
            again=training.make_scene(sid,scene,7)
            assert digest(frames)==digest(frames_at(again,times))
            clips.append(save_clip(output,sid,scene,'skill',frames,{'event':event,'sim_times':times,'move':r.skill_profile(sid)}))
        sheet=Image.new('RGB',(r.W*columns,(r.H+24)*len(rows)),r.PAPER)
        for i,row in enumerate(rows): sheet.paste(row,(0,i*(r.H+24)))
        sheet.save(output/f'{sid}-all-frames.png')
        compare.save(output/f'{sid}-comparison.png')
        # Compact per-species summary: all six states + the actual skill.
        summary=Image.new('RGB',(r.W*7,r.H+24),r.PAPER)
        for j,state in enumerate(STATES+('skill',)):
            index=round(r.cast_windup(sid)*10)+2 if state=='skill' else 1
            path=output/str(sid)/'melee'/state/f'frame-{index:03d}.png'
            summary.paste(Image.open(path).convert('RGB'),(j*r.W,24))
            ImageDraw.Draw(summary).text((j*r.W+4,5),f'{sid} / {state}',fill=r.INK)
        summary.save(output/f'{sid}-summary.png')
        masters.append(summary)
        print('range',sid,'21 clips',flush=True)
    master=Image.new('RGB',(r.W*7,(r.H+24)*16),r.PAPER)
    for i,im in enumerate(masters): master.paste(im,(0,i*(r.H+24)))
    master.save(output/'contact-sheet.png')
    (output/'manifest.json').write_text(json.dumps({'clips':clips,'six_state_clips':288,
        'skill_clips':48,'frames':sum(c['frames'] for c in clips),
        'fixture':'Six-state clips isolate recorded Battle events. Skill clips use complete real battles. Death uses HP=1 training fixture.'},ensure_ascii=False,indent=2)+'\n')
    html=training.PROFILE_RANGE_HTML.replace('单体靶场 · 平A / 技能','16 只独立动作与技能靶场').replace('真实 Battle 事件 · 四色精灵','真实事件隔离六状态 + 完整 Battle 技能 · 左右对比见下方 · 四色精灵')
    html += '<p>状态说明：strike 片段含 recover；hit 是叠加轨。六状态隔离真实事件，死亡训练 HP=1。技能片段保留完整战斗。</p>'
    html += ''.join(f'<p><a href="{sid}-summary.png">{sid} 六状态+技能</a> · <a href="{sid}-comparison.png">49a0d46 / authored 左右对照</a> · <a href="{sid}-all-frames.png">全部状态帧</a></p>' for sid in species_motion)
    (output/'index.html').write_text(html)


def detail_atlases(output):
    """Readable 4x motion and 2x uncoloured FX, separate from full-board evidence."""
    fx_sheet=Image.new('RGB',(6*240,16*264),r.NIGHT)
    columns=max(len(seq) for states in species_motion.values() for seq in states.values())
    motion_sheet=Image.new('RGB',(columns*160,16*7*180),r.PAPER)
    for row,sid in enumerate(species_motion):
        anim=training.make_scene(sid,'melee',7)
        base=anim._board_sprite(sid,anim.units[0].u.piece.tier)
        for j,state in enumerate((*STATES,'recover')):
            frames=species_motion[sid][state]
            for i,f in enumerate(frames):
                cel=transform(base,sid,Pose(state,i,f))
                tile=Image.new('RGBA',(40,40),r.PAPER)
                tile.alpha_composite(cel,(3+f[0],3+max(-3,min(3,f[1]))))
                x,y=i*160,(row*7+j)*180
                motion_sheet.paste(tile.convert('RGB').resize((160,160),Image.Resampling.NEAREST),(x,y+20))
                ImageDraw.Draw(motion_sheet).text((x+2,y+3),f'{sid}/{state} #{i}',fill=r.INK)
        for phase in range(6):
            cell=Image.new('RGBA',(240,240),r.NIGHT)
            budget=r.ParticleBudget()
            for layer in ('body','impact'):
                draw_authored_phase(cell,sid,layer,(40,120),(150,120),phase,r.PAPER,budget)
            draw_contact_field(cell,sid,(150,120),phase,r.PAPER,budget)
            fx_sheet.paste(cell.convert('RGB'),(phase*240,row*264+24))
            ImageDraw.Draw(fx_sheet).text((phase*240+4,row*264+5),f'{sid} move={AUTHORED_SKILLS[sid][0]} #{phase}',fill=r.PAPER)
    fx_sheet.save(output/'skill-geometry-atlas.png')
    motion_sheet.save(output/'motion-4x-atlas.png')


def hard_checks(output):
    failures=[]
    overlap=0
    frames=0
    peak=0
    palette_bad=0
    alpha_bad=0
    motion_frames=0
    for sid,states in species_motion.items():
        a=training.make_scene(sid,'melee',7)
        base=a._board_sprite(sid,a.units[0].u.piece.tier)
        allowed=set(a.pal.for_species(sid))
        for state,sequence in states.items():
            for index,f in enumerate(sequence):
                sprite=transform(base,sid,Pose(state,index,f))
                motion_frames+=1
                for c in sprite.getdata():
                    palette_bad+=int(c[3]>0 and c[:3] not in allowed)
                    alpha_bad+=int(c[3] not in (0,255))
        for seed in (7,11):
            for scene in training.SCENES:
                a=training.make_scene(sid,scene,seed,'skill')
                cast=next(e for e in a.events if e[1]=='cast' and e[2]==0)
                for phase in range(round(r.cast_windup(sid)*10)+6):
                    t=cast[0]+phase*.1
                    a._ensure(t)
                    quiet=copy.copy(a)
                    quiet._draw_board_fx=lambda *_:None
                    on,off=[Image.new('RGBA',(r.W,r.H)) for _ in range(2)]
                    a._draw_board(on,t)
                    quiet._draw_board(off,t)
                    channels=ImageChops.difference(on.convert('RGB'),off.convert('RGB')).split()
                    delta=ImageChops.lighter(ImageChops.lighter(channels[0],channels[1]),channels[2])
                    mask=Image.new('L',(r.W,r.H))
                    for u in a.units.values():
                        pose=a._unit_pose(u,t)
                        if not u.visible(t) or pose is None:continue
                        sprite,x,y=a._sprite_placement(u,t,pose)
                        body=Image.new('L',mask.size)
                        body.paste(sprite.getchannel('A'),(x,y+a._board_shake(t)))
                        mask=ImageChops.lighter(mask,body)
                    painted=ImageChops.multiply(delta,mask)
                    overlap+=painted.width*painted.height-painted.histogram()[0]
                    budget=r.ParticleBudget()
                    a._draw_board_fx(Image.new('RGBA',(r.W,r.H)),t,budget,{})
                    peak=max(peak,budget.used)
                    frames+=1
    if overlap:failures.append('opaque sprite occlusion')
    if palette_bad or alpha_bad:failures.append('authored sprite palette/alpha')
    saturated=r.ParticleBudget()
    for _ in range(20):
        for sid in species_motion:
            draw_authored_phase(Image.new('RGBA',(240,240)),sid,'body',(40,120),(150,120),2,r.PAPER,saturated)
            draw_contact_field(Image.new('RGBA',(240,240)),sid,(150,120),2,r.PAPER,saturated)
    if saturated.used>192 or peak>192:failures.append('particle budget')
    result={'passed':not failures,'failures':failures,'checked_cast_frames':frames,
            'opaque_body_fx_overlap_pixels':overlap,'authored_motion_frames':motion_frames,
            'off_palette_pixels':palette_bad,'partial_alpha_pixels':alpha_bad,
            'sampled_board_fx_particle_peak':peak,'saturated_budget':saturated.used}
    (output/'hard-contracts.json').write_text(json.dumps(result,indent=2)+'\n')
    print('hard',result,flush=True)
    if failures:raise SystemExit(1)


def benchmark(output,old_r):
    # Same immutable event streams and schedule, warmed independently. Paired
    # rounds alternate order, avoid PNG/hash/I/O during the timing interval.
    new=[training.make_scene(sid,'melee',7) for sid in species_motion]
    old=[old_fixture(a,old_r) for a in new]
    schedule=[.5+i*.3 for i in range(25)]
    for group in (old,new):
        for a in group:
            for t in schedule:a.frame(t,show_cutins=False)
            a._reset()
    def run(group):
        samples=[]
        for a in group:
            a._reset()
            for t in schedule:
                start=time.perf_counter_ns()
                a.frame(t,show_cutins=False)
                samples.append((time.perf_counter_ns()-start)/1e6)
        return samples
    results=[]
    for i in range(5):
        if i%2: after,before=run(new),run(old)
        else: before,after=run(old),run(new)
        results.append({'before_ms':statistics.mean(before),'after_ms':statistics.mean(after),
                        'before_samples_ms':before,'after_samples_ms':after})
    before=statistics.median(x['before_ms'] for x in results)
    after=statistics.median(x['after_ms'] for x in results)
    delta=(after/before-1)*100
    data={'passed':delta<=15,'baseline':'49a0d46','species':list(species_motion),
          'frames_per_round':400,'rounds':results,'baseline_median_ms':before,'authored_median_ms':after,'increase_percent':delta}
    (output/'benchmark.json').write_text(json.dumps(data,indent=2)+'\n')
    print('benchmark',before,after,delta,data['passed'],flush=True)
    if not data['passed']:raise SystemExit(1)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=('contracts','range','hard','benchmark','all'),default='all')
    parser.add_argument('--out',type=Path,default=OUT)
    args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    loaded,hashes=baseline()
    (args.out/'baseline-source.json').write_text(json.dumps({'commit':'49a0d46','sha256':hashes},indent=2)+'\n')
    if args.mode in ('contracts','all'):
        a=contracts(args.out)
        b=fallback(args.out,loaded['render_battle_gif'])
        if not a['passed'] or not b['passed']:raise SystemExit(1)
    if args.mode in ('range','all'):
        range_artifacts(args.out,loaded['render_battle_gif'])
        detail_atlases(args.out)
    if args.mode in ('hard','all'):hard_checks(args.out)
    if args.mode in ('benchmark','all'):benchmark(args.out,loaded['render_battle_gif'])

if __name__=='__main__':main()
