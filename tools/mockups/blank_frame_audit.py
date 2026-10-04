#!/usr/bin/env python3
"""Scan every archived PNG plus exact per-unit sprite alpha/rig attachments.

Pillow only. Every PNG is matched to its renderer: current/baseline authored
per-unit, and the archived 49a0d46 renderer for range-refined.
"""
import argparse
import copy
import csv
import io
import importlib.util
import json
import statistics
import subprocess
import tarfile
from pathlib import Path
from PIL import Image, ImageChops
import motion
import per_unit_evidence as evidence
import profile_range as training
import render_battle_gif as r

OUT = r.ROOT / 'reports/evidence/blank-frames-2026-10-04'
ROOTS = ('per-unit-2026-10-04', 'range-refined-2026-10-04')


def count(mask):
    return mask.width * mask.height - mask.histogram()[0]


def delta(a, b):
    rr, gg, bb = ImageChops.difference(a.convert('RGB'), b.convert('RGB')).split()
    return ImageChops.lighter(ImageChops.lighter(rr, gg), bb)


def old_rig(cel, sid, index):
    out = cel.copy()
    w, h = cel.size
    for l, t, rr, b, xs, ys in motion.RIGS[sid]:
        box = (l*w//100, t*h//100, rr*w//100, b*h//100)
        out.paste((0, 0, 0, 0), box)
        out.paste(cel.crop(box), (box[0]+xs[index % len(xs)], box[1]+ys[index % len(ys)]))
    return out


def scan(label):
    OUT.mkdir(parents=True, exist_ok=True)
    if label == 'before':
        spec = importlib.util.spec_from_file_location('baseline_motion', OUT/'baseline_motion.py')
        legacy = importlib.util.module_from_spec(spec)
        import sys
        sys.modules[spec.name] = legacy
        spec.loader.exec_module(legacy)
        r.transform = legacy.transform
    archive = None
    if label == 'before':
        archive = tarfile.open(fileobj=io.BytesIO(subprocess.check_output(
            ['git', 'archive', 'c94b225', *['reports/evidence/'+name for name in ROOTS]], cwd=r.ROOT)))
    historical, _ = evidence.baseline()
    rows = []
    for name in ROOTS:
        root = r.ROOT/'reports/evidence'/name
        for clip in json.loads((root/'manifest.json').read_text())['clips']:
            sid, state = clip['species'], clip['action']
            authored = name.startswith('per-unit')
            exact = True
            if authored:
                if state == 'skill':
                    anim = training.make_scene(sid, clip['scene'], 7)
                else:
                    anim, _, _ = evidence.fixture(sid, clip['scene'], state)
                times = clip['sim_times']
            else:
                anim = historical['profile_range'].make_scene(sid, clip['scene'], clip['seed'], state)
                times = clip['frame_times']
            floor = r.board_floor(None).copy()
            r.draw_divider(floor, 0, 3*r.BCELL, r.BCOLS*r.BCELL)
            metrics, previous = [], None
            palette = set(training._assets()[1].for_species(sid))
            for i in range(clip['frames']):
                frame_path = root/clip['path']/f'frame-{i:03d}.png'
                source = archive.extractfile(frame_path.relative_to(r.ROOT).as_posix()) if archive else frame_path
                with Image.open(source) as opened:
                    im = opened.convert('RGBA')
                board = im.crop((r.BX, r.BY, r.BX+floor.width, r.BY+floor.height))
                foreground = count(delta(board, floor))
                item = {'frame': i, 'foreground_px': foreground,
                        'opaque_px': im.getchannel('A').histogram()[255],
                        'palette_px': sum(n for n, color in board.convert('RGB').getcolors(board.width*board.height) if color in palette),
                        'changed_px': count(delta(im, previous)) if previous else 0}
                if exact:
                    t = times[i]
                    rendered = (anim.playback_frame(anim.playback_clock.playback_time(t), show_cutins=False)
                                if authored else anim.frame(t, show_cutins=False))
                    item['archive_matches_renderer'] = rendered.tobytes() == im.tobytes()
                    quiet = copy.copy(anim)
                    item['board_shake_px'] = anim._board_shake(t)
                    quiet._board_shake = lambda *_: 0
                    for method in ('_draw_board_fx', '_draw_board_flash', '_draw_floats', '_draw_ground_scars'):
                        setattr(quiet, method, lambda *_: None)
                    quiet_frame = quiet.frame(t, show_cutins=False)
                    item['effect_delta_px'] = count(delta(rendered, quiet_frame))
                    item['quiet_foreground_px'] = count(delta(quiet_frame.crop(
                        (r.BX, r.BY, r.BX+floor.width, r.BY+floor.height)), floor))
                    # All units, not just the hero: never let the floor/HUD mask a vanished actor.
                    units = []
                    for au in anim.units.values():
                        if not au.visible(t):
                            units.append({'unit': au.u.idx, 'visible': False, 'intent': 'death_removed'})
                            continue
                        pose = anim._unit_pose(au, t)
                        if pose is None:
                            units.append({'unit': au.u.idx, 'visible': False, 'intent': 'pose_hidden'})
                            continue
                        sprite, x, y = anim._sprite_placement(au, t, pose)
                        alpha = sprite.getchannel('A')
                        placed = Image.new('L', (r.W, r.H))
                        placed.paste(alpha, (x, y))
                        unit = {'unit': au.u.idx, 'visible': True, 'sprite_px': count(alpha),
                                'onscreen_px': count(placed), 'seam_px': 0, 'dissolve': 0}
                        usid = au.u.piece.species_id
                        if authored and usid in motion.species_motion:
                            mp = motion.MotionSystem.resolve(anim, au, t)
                            base = anim._board_sprite(usid, au.u.piece.tier)
                            cel = base.crop(base.getbbox())
                            fixed = motion.rig_cel(cel, usid, mp.index)
                            old = old_rig(cel, usid, mp.index)
                            # Pixels restored before scale/rotation/dissolve, not a claim
                            # that every restored pixel is visible through later overlays.
                            unit['baseline_seam_px'] = count(ImageChops.subtract(fixed.getchannel('A'), old.getchannel('A')))
                            reference = motion.transform(base, usid, mp)
                            actual = r.transform(base, usid, mp)
                            unit['seam_px'] = count(ImageChops.subtract(
                                reference.getchannel('A'), actual.getchannel('A')))
                            unit['state'] = mp.state
                            unit['dissolve'] = max(mp.frame[5], mp.hit[5])
                        units.append(unit)
                    item['units'] = units
                    hero = units[0]
                    item['sprite_px'] = hero.get('sprite_px', 0)
                    item['intent'] = ('death_removed' if not hero['visible'] else
                                      'authored_dissolve' if hero['dissolve'] else
                                      'death_pose' if hero.get('state') == 'death' else None)
                metrics.append(item)
                previous = im
            median = statistics.median(m['foreground_px'] for m in metrics)
            smedian = statistics.median(m['sprite_px'] for m in metrics) if exact else None
            anomalies = []
            for i, m in enumerate(metrics):
                reasons = []
                if m['opaque_px'] != r.W*r.H: reasons.append('transparent_canvas')
                if m['foreground_px'] == 0: reasons.append('empty_board')
                if m['foreground_px'] < median*.45: reasons.append('low_foreground')
                if i and abs(m['foreground_px']-metrics[i-1]['foreground_px']) > median*.35:
                    reasons.append('foreground_jump')
                if exact:
                    if not m['archive_matches_renderer']: reasons.append('archive_source_mismatch')
                    if m['sprite_px'] < smedian*.45: reasons.append('low_sprite')
                    if i and abs(m['sprite_px']-metrics[i-1]['sprite_px']) > smedian*.35:
                        reasons.append('sprite_jump')
                    if any(u.get('seam_px', 0) for u in m['units']): reasons.append('rig_cut_seam')
                    if any(u['visible'] and not u['onscreen_px'] for u in m['units']): reasons.append('visible_unit_empty')
                    if any(u['visible'] and u['onscreen_px'] < u['sprite_px'] for u in m['units']): reasons.append('clipped_unit')
                if reasons:
                    intent = m.get('intent')
                    if not intent and i and metrics[i-1].get('intent') == 'authored_dissolve':
                        intent = 'authored_dissolve_recovery'
                    if not intent and set(reasons) <= {'foreground_jump', 'low_foreground'}:
                        # Ablation removes only FX/flash/numbers/scars, preserving
                        # every actor. Require stable nonempty quiet content.
                        qmedian = statistics.median(x['quiet_foreground_px'] for x in metrics)
                        if (m['quiet_foreground_px'] >= qmedian*.45 and
                                any(x['effect_delta_px'] for x in metrics) and
                                (not i or abs(m['quiet_foreground_px']-metrics[i-1]['quiet_foreground_px']) <= qmedian*.35)):
                            intent = 'effect_phase_transition'
                    category = ('render_bug' if 'rig_cut_seam' in reasons or 'visible_unit_empty' in reasons else
                                'design_intent' if intent and not set(reasons).intersection(
                                    {'archive_source_mismatch', 'clipped_unit', 'transparent_canvas', 'empty_board'}) else 'review')
                    anomalies.append({'frame': i, 'category': category, 'reasons': reasons, 'intent': intent})
            rows.append({'page': name, 'path': clip['path'], 'frames': len(metrics),
                         'foreground_min': min(m['foreground_px'] for m in metrics), 'foreground_median': median,
                         'sprite_min': min(m['sprite_px'] for m in metrics) if exact else None,
                         'sprite_median': smedian, 'metrics': metrics, 'anomalies': anomalies})
        print(name, 'scanned', flush=True)
    summary = {'clips': len(rows), 'frames': sum(x['frames'] for x in rows),
               'transparent_frames': sum(m['opaque_px'] != r.W*r.H for x in rows for m in x['metrics']),
               'empty_board_frames': sum(m['foreground_px'] == 0 for x in rows for m in x['metrics']),
               'archive_source_mismatch': sum(not m.get('archive_matches_renderer', True) for x in rows for m in x['metrics']),
               'anomaly_frames': {cat: sum(a['category'] == cat for x in rows for a in x['anomalies']) for cat in ('render_bug', 'design_intent', 'review')}}
    result = {'label': label, 'summary': summary, 'thresholds': {'low_ratio': .45, 'jump_ratio': .35}, 'clips': rows}
    (OUT/f'{label}-scan.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    with (OUT/f'{label}-segments.csv').open('w') as f:
        writer = csv.writer(f)
        writer.writerow(['page','path','frames','foreground_min','foreground_median','sprite_min','sprite_median','anomalies'])
        for row in rows:
            writer.writerow([row[k] for k in ('page','path','frames','foreground_min','foreground_median','sprite_min','sprite_median')]+[json.dumps(row['anomalies'],ensure_ascii=False)])
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', choices=('before','after'), required=True)
    scan(parser.parse_args().label)
