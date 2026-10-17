"""Render every new family action through the real arena playback path.

Run from the repository root; outputs are inspection evidence, never save data.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'sim'), str(ROOT/'tools/mockups'), str(ROOT/'tools/acceptance')]
from PIL import Image, ImageDraw
from action_preview import describe_clip
from animation_preview import source_revision
from arena_preview_scene import make_preview_scene
import family_vfx
from presentation_modes import make_renderer


def probe(output):
    output.mkdir(parents=True, exist_ok=True)
    rows, times = [], []
    samples = (257, 376, 282, 350, 130, 135)
    sheet = Image.new('RGB', (1440, len(samples)*340), '#f4f5e9')
    pen = ImageDraw.Draw(sheet)
    for sid in sorted(family_vfx.SPECIES):
        for kind in ('attack', 'cast'):
            anim = make_preview_scene(sid, kind)
            original = copy.deepcopy(anim.events)
            action = describe_clip(anim, kind)['action']
            moments = ((action['start']+action['release'])/2,
                       (action['release']+action['impact'])/2,
                       action['impact']+.06)
            renderer = make_renderer(anim)
            frames = []
            for moment in moments:
                started = time.perf_counter()
                frames.append(renderer.frame(moment))
                times.append((time.perf_counter()-started)*1000)
            renderer.frame(action['recover_end']+.1)
            assert renderer.frame(moments[1]).tobytes() == frames[1].tobytes(), (sid, kind, 'seek')
            assert anim.events == original, (sid, kind, 'events')
            assert len({frame.tobytes() for frame in frames}) > 1, (sid, kind, 'static')
            rows.append({'species': sid, 'kind': kind, 'samples': 3,
                         'seek_identical': True, 'events_unchanged': True,
                         'flight_sha256': hashlib.sha256(frames[1].tobytes()).hexdigest()})
            if sid in samples and kind == 'cast':
                y = samples.index(sid)*340
                for column, (label, frame) in enumerate(zip(('Windup', 'Release', 'Impact'), frames)):
                    pen.text((column*480+12, y+4), f'#{sid} native / {label}', fill='#294133')
                    sheet.paste(frame.resize((480, 320), Image.Resampling.NEAREST), (column*480, y+20))
    report = {'source_revision': source_revision(), 'forms': len(family_vfx.SPECIES),
              'actions': len(rows), 'sampled_frames': len(times),
              'render_ms': {'median': round(statistics.median(times), 2),
                            'p95': round(sorted(times)[int(len(times)*.95)], 2),
                            'max': round(max(times), 2)}, 'results': rows}
    (output/'family-vfx-probe.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    sheet.save(output/'family-vfx-contact.png')
    print(json.dumps({key: value for key, value in report.items() if key != 'results'}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'.build/family-vfx-probe')
    probe(parser.parse_args().output)
