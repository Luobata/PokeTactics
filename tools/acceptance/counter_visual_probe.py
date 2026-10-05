#!/usr/bin/env python3
"""Native frames from one natural-energy battle plus a directed expiry boundary.

PC presentation evidence, not balance, human readability or hardware acceptance.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT/'tools/acceptance'), str(ROOT/'sim')]
from PIL import Image, ImageDraw, ImageFont
from session_save import rules_fingerprint
from tactical_visual_probe import label_font


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(); args.out.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location('counter_visual_fixture', ROOT/'tests/test_counter_presentation.py')
    fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
    fixture.CounterPresentation.setUpClass(); check = fixture.CounterPresentation()
    battles = {'natural': fixture.natural_battle(), 'expiry': fixture.directed_battle()}
    originals = {key: copy.deepcopy(b.events) for key, b in battles.items()}
    animations = {key: check.animation(b) for key, b in battles.items()}
    natural = animations['natural']
    block = next(e for e in natural.timeline.events if e[1] == 'tactical_effect' and e[4] == 'healing_block')
    heal = next(e for e in natural.timeline.events if e[1] == 'tactical_effect' and e[4] == 'healing_prevented')
    expiry = next(e for e in animations['expiry'].timeline.events
                  if e[1] == 'tactical_effect' and e[4] == 'healing_block')
    directed_heal = next(e for e in animations['expiry'].timeline.events
                         if e[1] == 'tactical_effect' and e[4] == 'healing_prevented')
    expiry_time = expiry[0]+expiry[5]['expires_at']-expiry[5]['simulation_time']
    font = ImageFont.truetype(label_font(), 18)
    shots = [('before-hit', 'natural', block[0]-.05, '自然启动 / 命中前无封疗标记'),
             ('hit', 'natural', block[0]+.05, '原生大招命中 / 目标获得八秒封疗'),
             ('healing', 'expiry', directed_heal[0]+.05, '定向实际恢复与被封锁量 / 同时反馈'),
             ('expired', 'expiry', expiry_time+.05, '定向边界 / 到期标记消失、恢复正常')]
    cards, outputs = [], []
    for key, scene, t, title in shots:
        frame = animations[scene].playback_frame(t).convert('RGB')
        frame.save(args.out/f'{key}.png')
        card = Image.new('RGB', (516, 720), '#f3f0e7')
        draw = ImageDraw.Draw(card); draw.text((18, 14), title, font=font, fill='#24332f')
        card.paste(frame.resize((480, 640), Image.Resampling.NEAREST), (18, 45))
        draw.text((18, 692), f'演出 {t:.2f}s · PC 240×320 原生画面', font=font, fill='#66746f')
        cards.append(card); outputs.append({'file': f'{key}.png', 'scene': scene, 'time': t,
                                           'native_pixels_sha256': sha(frame.tobytes())})
    contact = Image.new('RGB', (1032, 1440))
    for i, card in enumerate(cards): contact.paste(card, ((i%2)*516, (i//2)*720))
    contact.save(args.out/'counter-overview.png'); outputs.append({'file': 'counter-overview.png'})
    for key, anim in animations.items():
        frames = [anim.playback_frame(i/10).convert('RGB')
                  for i in range(math.ceil(anim.presentation_duration*10)+1)]
        montage = Image.new('RGB', (240, 320*len(frames)))
        for i, frame in enumerate(frames): montage.paste(frame, (0, i*320))
        palette = montage.quantize(colors=256)
        indexed = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f in frames]
        indexed[0].save(args.out/f'{key}.gif', save_all=True, append_images=indexed[1:],
                        duration=100, loop=0, disposal=2, optimize=False)
        outputs.append({'file': f'{key}.gif', 'frames': len(frames), 'fps': 10})
    for key in battles:
        assert battles[key].events == originals[key], 'Presentation mutated simulation'
    for row in outputs:
        path = args.out/row['file']; row.update(bytes=path.stat().st_size, sha256=sha(path.read_bytes()))
    sources = ['tools/acceptance/counter_visual_probe.py', 'tests/test_counter_presentation.py',
               'tools/mockups/render_battle_gif.py', 'tools/mockups/animation_timeline.py',
               'sim/combat.py', 'sim/items.py', 'sim/tactics.py']
    payload = {'ruleset': 'tactics_v4', 'rules_fingerprint': rules_fingerprint(),
               'sources_sha256': {p: sha((ROOT/p).read_bytes()) for p in sources},
               'scenes': {key: {'events': b.events, 'events_sha256': sha(json.dumps(b.events,
                            ensure_ascii=False, separators=(',', ':')).encode()),
                            'presentation_events': animations[key].timeline.events}
                          for key, b in battles.items()}, 'outputs': outputs,
               'limits': ['natural: production six-v-six disrupt/needle versus garden, seed 202610055000; no HP or energy override.',
                          'expiry: high-HP, manually charged single cast with directed heals; boundary contract only.',
                          'Countdown uses the announced duration in presentation seconds; combat uses simulator expiry.',
                          'HUD is default renderer sample data, not an expedition economy snapshot.',
                          'No balance, physical device, human readability or new species asset claim.']}
    (args.out/'visual.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'output': str(args.out), 'files': len(outputs), 'simulation_unchanged': True}))


if __name__ == '__main__':
    main()
