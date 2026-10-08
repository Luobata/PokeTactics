#!/usr/bin/env python3
"""Export real-event hero action GIFs, contact sheets and timing evidence.

python3 tools/mockups/animation_showcase.py --out .build/animation-b --seed 7
Uses real decoded sprites and padded-HP training Battles. No events or damage
are fabricated. CLI defaults to the 960x640 trial; --mode classic keeps device art.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import statistics
import time

from PIL import Image, ImageDraw
from profile_range import make_preview_scene
from render_battle_gif import quantize_frames
from character_catalog import character_catalog
from presentation_modes import make_renderer, mode_info, normalize_mode

HEROES = (6,9,3,26,65,94,76,143)
ARENA_HEROES = (68,212,26,9,6,3,65,95)
STEP = .05


def digest(frames):
    return hashlib.sha256(b''.join(f.tobytes() for f in frames)).hexdigest()


def export(out, seed=7, species=None, *, mode='classic', visual_overrides=None):
    mode = normalize_mode(mode)
    info = mode_info(mode)
    width, height = info['width'], info['height']
    out = Path(out)
    out.mkdir(parents=True,exist_ok=True)
    records=[]
    rows={'attack':[], 'cast':[]}
    all_ms=[]
    heroes = (ARENA_HEROES if mode=='arena' else HEROES) if species is None else tuple(species)
    roster_ids = set(map(int,character_catalog(mode=mode)))
    if not heroes or len(set(heroes)) != len(heroes) or set(heroes)-roster_ids:
        raise ValueError("species must be a nonempty unique subset of roster ids")
    for sid in heroes:
        for kind in ('attack','cast'):
            anim=make_preview_scene(sid,kind,seed,visual_overrides=visual_overrides,mode=mode)
            renderer=make_renderer(anim,mode)
            candidates=[a for a in anim.timeline.actions
                        if a.attacker==0 and a.kind==kind and not a.secondary]
            damage_index=6 if kind=='cast' else 4
            action=next((a for a in candidates if anim.events[a.source_index][damage_index]>0),candidates[0])
            start=max(0., action.start-.25)
            end=max(action.impact+.95,action.recover_end+.25)
            times=[round(start+i*STEP,6) for i in range(round((end-start)/STEP)+1)]
            frames=[]; measurements=[]; peaks={}
            for t in times:
                tick=time.perf_counter()
                frame=renderer.frame(t).convert('RGB')
                measurements.append((time.perf_counter()-tick)*1000)
                frames.append(frame)
                for key,value in renderer.metrics.items():
                    if isinstance(value,(int,float)):
                        peaks[key]=max(peaks.get(key,0),value)
            all_ms.extend(measurements)
            name=f'{sid}-{kind}'
            encoded=quantize_frames(frames)
            encoded[0].save(out/f'{name}.gif',save_all=True,append_images=encoded[1:],
                            duration=50,loop=0,optimize=False,disposal=2)
            phases=[('PREPARE',action.start+(action.release-action.start)*.65),
                    ('RELEASE',action.release),
                    ('FLIGHT',(action.release+action.impact)/2),
                    ('IMPACT',action.impact),('RECOVER',action.impact+.30)]
            if sid==65 and kind=='cast':
                blink=next((b for b in anim.timeline.blinks if b['unit']==0
                            and abs(b['start']-action.start)<1e-8),None)
                if blink:
                    phases=[('FOCUS',action.start+.05),('ECHO',blink['departure']+.06),
                            ('VANISH',blink['landing']-.025),('LAND',blink['landing']+.025),
                            ('IMPACT',action.impact)]
            elif sid==143 and kind=='cast':
                phases=[('CROUCH',action.start+.15),('LIFT',action.release-.075),
                        ('BEAM',action.impact-.05),('IMPACT',action.impact),
                        ('RECOVER',action.impact+.40)]
            row=Image.new('RGB',(5*width,height+24),(238,230,206))
            for index,(label,t) in enumerate(phases):
                row.paste(renderer.frame(t,show_cutins=False).convert('RGB'),(index*width,24))
                ImageDraw.Draw(row).text((index*width+6,7),f'{sid} {label} {t:.2f}s',fill=(35,40,35))
            row.save(out/f'{name}-contact.png')
            rows[kind].append(row.resize((1200,round((height+24)*240/width))) if mode=='arena' else row)
            before=anim.presentation_state(action.impact-.001)[action.target]
            after=anim.presentation_state(action.impact)[action.target]
            records.append({**info,'species':sid,'kind':kind,'gif':f'{name}.gif',
                            'contact':f'{name}-contact.png','action':asdict(action),
                            'landed_damage':anim.events[action.source_index][damage_index],
                            'clip_start':start,'clip_end':end,'frames':len(frames),'fps':20,
                            'frame_sha256':digest(frames),'target_before_impact':before,
                            'target_at_impact':after,'metrics':peaks,
                            **({'particle_peak':peaks.get('particles',0),
                                'signature_track_peak':peaks.get('signature_tracks',0)} if mode=='classic' else {}),
                            'frame_ms_p95':round(sorted(measurements)[int((len(measurements)-1)*.95)],3),
                            'frame_ms_max':round(max(measurements),3),
                            'simulation_duration':anim.events[-1][0],
                            'training_scene': 'precharged_skill' if kind=='cast' else 'stationary_posts',
                            'skill_effects': [list(ev) for ev in anim.timeline.events if ev[1]=='skill_effect'],
                            'presentation_duration':anim.presentation_duration})
    for kind,sheets in rows.items():
        combined=Image.new('RGB',(sheets[0].width,sum(sheet.height for sheet in sheets)),(238,230,206))
        offset=0
        for i,sheet in enumerate(sheets):
            combined.paste(sheet,(0,offset))
            offset+=sheet.height
        combined.save(out/f'contact-{kind}.png')
    manifest={**info,'seed':seed,'frame_size':[width,height],'clips':records,
              'clock':'presentation seconds, no additional PlaybackClock mapping',
              'limits':({'active_actions':6,'active_casts':6} if mode=='arena' else
                        {'particles_per_frame':192,'signature_tracks':3,
                         'portrait_windows_per_battle':2,'portrait_seconds_each':.20}),
              'host_frame_ms_p50':round(statistics.median(all_ms),3),
              'host_frame_ms_p95':round(sorted(all_ms)[int((len(all_ms)-1)*.95)],3),
              'device_claim':'Desktop Pillow evidence only; ESP32 performance is not measured.'}
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'out':str(out.resolve()),'clips':len(records),
                      'frame_ms_p95':manifest['host_frame_ms_p95']},ensure_ascii=False))
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=('arena','classic'),default='arena')
    parser.add_argument('--out',type=Path,default=Path('.build/animation-b'))
    parser.add_argument('--seed',type=int,default=7)
    parser.add_argument('--species',default=None,help='all or comma separated subset, e.g. 68,212,9')
    args=parser.parse_args()
    species=(None if args.species is None else tuple(sorted(map(int,character_catalog(mode=args.mode))))
             if args.species=='all' else tuple(int(s) for s in args.species.split(',')))
    export(args.out,args.seed,species,mode=args.mode)
