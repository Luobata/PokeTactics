"""Save-free visual evidence for the battle VFX and action redesign."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'sim'), str(ROOT / 'tools/mockups')]
from arena_preview_scene import make_preview_scene
from arena_scenarios import make_scene
from presentation_modes import make_renderer


def capture(out):
    out.mkdir(parents=True, exist_ok=True)
    font = ImageFont.load_default()
    evidence = {'clips': [], 'battles': []}
    # Real isolated actions: different attack silhouettes, support and heavy cast.
    cases = ((6, 'attack'), (68, 'attack'), (94, 'attack'), (65, 'attack'),
             (26, 'cast'), (125, 'cast'), (181, 'cast'), (65, 'cast'),
             (196, 'cast'), (150, 'cast'), (40, 'cast'), (113, 'cast'), (242, 'cast'))
    for sid, kind in cases:
        anim = make_preview_scene(sid, kind, 7)
        renderer = make_renderer(anim, 'arena').renderer
        action = next(a for a in anim.timeline.actions if a.attacker == 0 and a.kind == kind and not a.secondary)
        times = ((action.start + action.release) / 2,
                 (action.release + action.impact) / 2, action.impact + .05,
                 action.impact + .24, action.impact + .48, action.impact + .75)
        sheet = Image.new('RGB', (960, 404), (17, 27, 30))
        d = ImageDraw.Draw(sheet)
        for i, at in enumerate(times):
            im = renderer.frame(at).crop((210, 165, 690, 465)).resize((320, 200), Image.Resampling.NEAREST)
            xy = ((i % 3) * 320, (i // 3) * 202)
            sheet.paste(im, xy)
            d.text((xy[0] + 4, xy[1] + 4), f'{sid} {kind} t={at:.3f}', font=font, fill='white')
        sheet.save(out / f'{sid}-{kind}.png')
        # Normal-speed GIF, 20fps; playback samples include the actual hitstop.
        start = renderer.presentation_time(action.start)
        end = renderer.presentation_time(action.impact + .9)
        frames = [renderer.frame_playback(start + i * .05).resize((720, 480), Image.Resampling.NEAREST)
                  for i in range(max(2, round((end - start) / .05) + 1))]
        frames[0].save(out / f'{sid}-{kind}.gif', save_all=True, append_images=frames[1:],
                       duration=50, loop=0)
        evidence['clips'].append({'species': sid, 'kind': kind, 'start': action.start,
            'release': action.release, 'impact': action.impact, 'recover_end': action.recover_end,
            'source_events_sha256': hashlib.sha256(repr(anim.events).encode()).hexdigest()})
    for scene in ('arena_elements', 'arena_trait_mending', 'arena_attack_growth'):
        anim = make_scene(7, scene)
        renderer = make_renderer(anim, 'arena').renderer
        samples, elapsed, peaks = [], [], []
        for at in (2., 5., 8., 11.):
            begin = time.perf_counter()
            frame = renderer.frame(at)
            elapsed.append(time.perf_counter() - begin)
            peaks.append(renderer._last_metrics.get('particles', 0))
            frame.save(out / f'{scene}-{at:g}.png')
            samples.append(frame.resize((480, 320), Image.Resampling.NEAREST))
        sheet = Image.new('RGB', (960, 640))
        for i, frame in enumerate(samples):
            sheet.paste(frame, ((i % 2) * 480, (i // 2) * 320))
        sheet.save(out / f'{scene}-sheet.png')
        casts = [e for e, a in renderer._actions if e[1] == 'cast' and not a.secondary]
        evidence['battles'].append({'scene': scene, 'casts': len(casts),
            'ults': len(renderer._ults), 'impact_accents': len(renderer._impacts),
            'ult_teaching': sum(not str(renderer._actions[row[6]][0][4]).startswith('arena_') for row in renderer._ults),
            'sample_frame_ms': [round(v * 1000, 2) for v in elapsed], 'peak_counted_particles': max(peaks),
            'source_events_sha256': hashlib.sha256(repr(anim.events).encode()).hexdigest()})
    (out / 'metrics.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    return evidence


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = capture(args.out)
    print(json.dumps({'out': str(args.out), 'clips': len(result['clips']), 'battles': result['battles']}, indent=2))
