#!/usr/bin/env python3
"""Reproducible before/after captures and 100-frame render-only benchmark."""
import argparse
import hashlib
import json
import time
import subprocess
import sys
import types
from pathlib import Path
from PIL import Image, ImageDraw
from profile_range import make_scene
import render_battle_gif as r

OUT = r.ROOT / 'reports/evidence/range-refined-2026-10-04'


def capture(label, output=OUT):
    output.mkdir(parents=True, exist_ok=True)
    anim = make_scene(6, 'dummy', 7)
    attack = next(e for e in anim.events if e[1] == 'attack' and e[2] == 0)
    cast = next(e for e in anim.events if e[1] == 'cast' and e[2] == 0)
    impact = attack[0] + anim._attack_delay(attack)
    times = {'basic-hit': impact, 'projectile-mid': attack[0] + r.FPS_DT +
             (anim._attack_delay(attack) - r.FPS_DT) / 2,
             'skill-hit': cast[0] + r.cast_windup(6)}
    hashes = {}
    for name, t in times.items():
        frame = anim.frame(t, show_cutins=False)
        frame.save(output / f'{label}-{name}.png')
        hashes[name] = hashlib.sha256(frame.tobytes()).hexdigest()
        if label == 'after':
            before = Image.open(output / f'before-{name}.png').convert('RGB')
            sheet = Image.new('RGB', (r.W * 2, r.H + 20), r.PAPER)
            sheet.paste(before, (0, 20))
            sheet.paste(frame.convert('RGB'), (r.W, 20))
            draw = ImageDraw.Draw(sheet)
            draw.text((4, 4), f'd7139f9 | {name}', fill=r.INK)
            draw.text((r.W + 4, 4), f'refined | t={t:.3f}', fill=r.INK)
            sheet.resize((r.W * 4, (r.H + 20) * 2), Image.Resampling.NEAREST).save(output / f'compare-{name}.png')
    # Four species x 25 identical chronological times. Warm all samples first;
    # Battle construction, asset loading, PNG and hashing are outside timing.
    scenes = [make_scene(s, 'melee', 7) for s in (6, 65, 143, 76)]
    schedule = [round(.5 + i * .3, 5) for i in range(25)]
    for a in scenes:
        for t in schedule:
            a.frame(t, show_cutins=False)
        a._reset()
    durations = []
    for a in scenes:
        for t in schedule:
            start = time.perf_counter_ns()
            a.frame(t, show_cutins=False)
            durations.append((time.perf_counter_ns() - start) / 1e6)
    result = {'label': label, 'seed': 7, 'species': [6,65,143,76],
              'scene': 'melee', 'times': schedule, 'frames': len(durations),
              'mean_ms': sum(durations) / len(durations), 'samples_ms': durations,
              'capture_times': times, 'sha256': hashes}
    (output / f'{label}-benchmark.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k:v for k,v in result.items() if k != 'samples_ms'}, indent=2))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', choices=['before','after'], required=True)
    parser.add_argument('--baseline-commit', help='Load renderer modules directly from this git revision')
    args = parser.parse_args()
    if args.baseline_commit:
        if args.capture != 'before':
            parser.error('--baseline-commit requires --capture before')
        source_hashes = {}
        root = r.ROOT
        for name in ('profile_vfx','skill_vfx','render_battle_gif','profile_range'):
            path = root / 'tools/mockups' / f'{name}.py'
            source = subprocess.check_output(['git','show',f'{args.baseline_commit}:tools/mockups/{name}.py'],cwd=root)
            source_hashes[name] = hashlib.sha256(source).hexdigest()
            module = types.ModuleType(name)
            module.__file__ = str(path)
            sys.modules[name] = module
            exec(compile(source,str(path),'exec'),module.__dict__)
        r = sys.modules['render_battle_gif']
        make_scene = sys.modules['profile_range'].make_scene
        (OUT/'baseline-source.json').write_text(json.dumps({'commit':args.baseline_commit,'sha256':source_hashes},indent=2)+'\n')
    capture(args.capture)
