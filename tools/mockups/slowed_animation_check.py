#!/usr/bin/env python3
"""Timing, key-pose preservation, attachment regression and same-clock GIFs."""
import argparse
import csv
import json
import math
import statistics
from pathlib import Path

from PIL import Image, ImageDraw, ImageSequence
import motion as m
import per_unit_evidence as evidence
import profile_range as training

STATES = ('idle', 'walk', 'windup', 'strike', 'hit', 'death')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=evidence.r.ROOT/'reports/evidence/range-slowed-2026-10-04')
    args = parser.parse_args()
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    loaded, _ = evidence.baseline('968f42f')
    old = loaded['motion']
    failures, rows, sources = [], [], {}
    keys_checked = frames_checked = gaps = empty = palette_bad = dissolve_checked = 0
    solid = Image.new('RGBA', (34, 34), (10, 30, 50, 255))
    for sid, states in m.species_motion.items():
        anim = training.make_scene(sid, 'melee', 7)
        source = anim._board_sprite(sid, anim.units[0].u.piece.tier)
        sources[sid] = source
        colors = set(source.getdata())
        for state, sequence in states.items():
            for key, frame in enumerate(old.species_motion[sid][state]):
                indices = [i for i, phase in enumerate(m.RIG_PHASES[sid][state]) if phase == key]
                if not indices:
                    failures.append(f'missing-key/{sid}/{state}/{key}')
                for i in indices:
                    before = old.transform(source, sid, old.Pose(state, key, frame))
                    after = m.transform(source, sid, m.Pose(state, i, sequence[i]))
                    keys_checked += 1
                    if before.tobytes() != after.tobytes():
                        failures.append(f'key-changed/{sid}/{state}/{key}')
            for i, frame in enumerate(sequence):
                frames_checked += 1
                phase = m.rig_phase(sid, state, i)
                nxt = 0 if state == 'walk' and math.floor(phase) == len(m.KEYFRAMES[sid][state])-1 else None
                gaps += m.rig_cel(solid, sid, phase, nxt).getchannel('A').crop((3, 3, 31, 31)).histogram()[0]
                sprite = m.transform(source, sid, m.Pose(state, i, frame))
                empty += not bool(sprite.getbbox())
                palette_bad += sum(1 for c in sprite.getdata() if c[3] and c not in colors)
                if frame[5]:
                    clean = m.transform(source, sid, m.Pose(state, i, (*frame[:5], 0)))
                    expected = clean.getchannel('A')
                    expected.putdata([a if x%2+2*(y%2) >= frame[5] else 0
                                      for y in range(clean.height) for x in range(clean.width)
                                      for a in (expected.getpixel((x,y)),)])
                    dissolve_checked += 1
                    if expected.tobytes() != sprite.getchannel('A').tobytes():
                        failures.append(f'dissolve/{sid}/{state}/{i}')
        for scene in training.SCENES:
            for state in STATES:
                segments = ('strike', 'recover') if state == 'strike' else (state,)
                before = sum(len(old.species_motion[sid][s])*.1 for s in segments)
                after = sum(m.duration(sid,s) for s in segments)
                # Idle training clips have always shown at least eight frames.
                if state == 'idle':
                    before, after = max(.8,before), max(.8,after)
                rows.append({'species':sid, 'scene':scene, 'state':state,
                             'before_seconds':round(before,6), 'after_seconds':round(after,6),
                             'before_frames':round(before/.1),
                             'after_frames':round(after/m.frame_dt(state))})
        # Runtime boundaries: a complete walk cycle, attack release/recovery,
        # additive hit expiration, death visibility and frozen/rewound samples.
        for state in ('walk', 'windup', 'strike', 'hit', 'death'):
            anim, times, _ = evidence.fixture(sid, 'melee', state)
            anim._ensure(times[0])
            au = anim.units[0]
            end = times[-1] + m.frame_dt(state)
            if state == 'death':
                if not au.visible(end-1e-5) or au.visible(end+1e-5):
                    failures.append(f'death-boundary/{sid}')
            if state == 'hit':
                if m.MotionSystem.resolve(anim, au, times[0]).hit != m.species_motion[sid]['hit'][0]:
                    failures.append(f'hit-onset/{sid}')
                anim._ensure(end+1e-5)
                if m.MotionSystem.resolve(anim, au, end+1e-5).hit != m.REST:
                    failures.append(f'hit-boundary/{sid}')
        if not .4 <= evidence.r.cast_windup(sid) <= .5:
            failures.append(f'charge-boundary/{sid}')
    with (out/'timing-segments.csv').open('w') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = {}
    for state in STATES:
        samples = [row for row in rows if row['state']==state]
        before = statistics.mean(row['before_seconds'] for row in samples)
        after = statistics.mean(row['after_seconds'] for row in samples)
        summary[state] = {'clips':len(samples), 'before_mean_seconds':before,
                          'after_mean_seconds':after, 'ratio':after/before,
                          'before_frames':sum(r['before_frames'] for r in samples),
                          'after_frames':sum(r['after_frames'] for r in samples)}
    summary['charge'] = {'before_min':min(loaded['skill_vfx'].cast_windup(s) for s in sources),
                         'before_max':max(loaded['skill_vfx'].cast_windup(s) for s in sources),
                         'after_min':min(evidence.r.cast_windup(s) for s in sources),
                         'after_max':max(evidence.r.cast_windup(s) for s in sources)}
    (out/'timing-summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    if gaps or empty or palette_bad:
        failures.append('attachment/palette/nonempty')
    result = {'passed':not failures, 'failures':failures, 'authored_frames_checked':frames_checked,
              'key_pose_pixel_checks':keys_checked, 'internal_gap_pixels':gaps,
              'empty_cels':empty, 'off_palette_pixels':palette_bad, 'dissolve_masks_preserved':dissolve_checked,
              'idle_key_cycle_mean_seconds':statistics.mean(m.duration(s,'idle') for s in sources),
              'baseline':'968f42f'}
    (out/'retiming-contracts.json').write_text(json.dumps(result,indent=2)+'\n')
    comparisons(out, old, sources)
    if (out/'manifest.json').exists():
        verify_range(out, rows)
    print(json.dumps({'timing':summary, 'regression':result}, indent=2))
    if failures:
        raise SystemExit(1)


def verify_range(out, timing):
    manifest = json.loads((out/'manifest.json').read_text())
    lookup = {(r['species'],r['scene'],r['state']):r for r in timing}
    records, failures = [], []
    for clip in manifest['clips']:
        path = out/clip['path']
        with Image.open(path/'animation.gif') as gif:
            milliseconds = sum(frame.info['duration'] for frame in ImageSequence.Iterator(gif))
        expected = clip['frames']*clip.get('frame_duration_ms',100)
        if milliseconds != expected:
            failures.append(f"GIF duration/{clip['path']}")
        frames = []
        for i in range(clip['frames']):
            with Image.open(path/f'frame-{i:03d}.png') as im:
                frames.append(im.convert('RGBA'))
        if evidence.digest(frames) != clip['sha256']:
            failures.append(f"PNG hash/{clip['path']}")
        if any(im.getchannel('A').getextrema() != (255,255) for im in frames):
            failures.append(f"transparent frame/{clip['path']}")
        key = clip['species'],clip['scene'],clip['action']
        if key in lookup and abs(milliseconds/1000-lookup[key]['after_seconds']) > 1e-8:
            failures.append(f"timing table/{clip['path']}")
        records.append({'path':clip['path'], 'frames':len(frames), 'gif_duration_ms':milliseconds,
                        'sha256':evidence.digest(frames)})
    result = {'passed':not failures, 'failures':failures, 'clips':len(records),
              'frames':sum(r['frames'] for r in records), 'records':records}
    (out/'artifact-audit.json').write_text(json.dumps(result,indent=2)+'\n')
    if failures:
        raise AssertionError(failures)


def comparisons(out, old, sources):
    rows = ('walk', 'attack chain', 'hit', 'death')
    def cel(module, sid, state, age):
        dt = (lambda s: .1) if module is old else m.frame_dt
        length = lambda s: len(module.species_motion[sid][s])*dt(s)
        if state == 'hit':
            index, frame = module.sample(sid, 'idle', age)
            hit = module.sample(sid, 'hit', age)[1] if age < length('hit')-1e-8 else module.REST
            pose = module.Pose('idle', index, frame, hit=hit)
        elif state == 'attack chain':
            for part in ('windup', 'strike', 'recover'):
                if age < length(part)-1e-8:
                    state = part
                    break
                age -= length(part)
            else:
                state, age = 'idle', 0
        elif state in ('hit','death') and age >= length(state)-1e-8:
            if state == 'death':
                return Image.new('RGBA',(40,40))
            state, age = 'idle', 0
        if state != 'hit':
            index, frame = module.sample(sid,state,age)
            pose = module.Pose(state,index,frame)
        sprite = module.transform(sources[sid],sid,pose)
        tile = Image.new('RGBA',(48,48))
        ox,oy = module.offsets(pose)
        tile.alpha_composite(sprite,(7+round(ox),4+round(oy)))
        return tile
    records = []
    for sid in (6,143,95,18):
        frames=[]
        for tick in range(40):
            age=tick*.05
            board=Image.new('RGB',(416,4*208+32),evidence.r.PAPER)
            draw=ImageDraw.Draw(board)
            draw.text((8,8),f'{sid} | 968f42f BEFORE     SLOWED | t={age:.2f}s',fill=evidence.r.INK)
            for row,state in enumerate(rows):
                y=32+row*208
                draw.text((8,y+2),state,fill=evidence.r.INK)
                for col,module in enumerate((old,m)):
                    tile=cel(module,sid,state,age)
                    tile=tile.resize((192,192),Image.Resampling.NEAREST)
                    board.paste(tile,(8+col*208,y+16),tile)
            frames.append(board)
        frames[0].save(out/f'{sid}-timing-comparison.gif',save_all=True,append_images=frames[1:],
                       duration=50,loop=0,disposal=2)
        # Same-clock still at 0.35 s: before/after and labels retained.
        frames[7].save(out/f'{sid}-timing-comparison.png')
        records.append({'species':sid,'rows':rows,'frames':len(frames),'frame_duration_ms':50,
                        'duration_seconds':2,'sha256':evidence.digest(frames)})
    (out/'timing-comparisons.json').write_text(json.dumps(records,indent=2)+'\n')


if __name__ == '__main__':
    main()
