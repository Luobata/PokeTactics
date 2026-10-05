#!/usr/bin/env python3
"""Actual battle-renderer evidence for opening weather, coverage and conflict.

Directed high-HP fixtures verify readable native frames; they do not measure
full-run pacing, balance, human experience or physical ESP32 performance.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT/'tools/acceptance'), str(ROOT/'sim')]

from PIL import Image
from tactical_visual_probe import panel, label_font
from PIL import ImageFont
from session_save import rules_fingerprint



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location('opening_presentation_fixture', ROOT/'tests/test_tactical_presentation.py')
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    fixture.OpeningWeatherPresentation.setUpClass()
    check = fixture.OpeningWeatherPresentation()
    battles = {'sun': check.battle(), 'rain': check.battle(sid=131), 'conflict': check.battle(conflict=True)}
    animations = {key: fixture.renderer.BattleAnimation([], [], 42, *check.assets, battle=battle)
                  for key, battle in battles.items()}
    fonts = tuple(ImageFont.truetype(label_font(), size) for size in (24, 18, 14))
    override = next(e[0] for e in animations['sun'].timeline.events
                    if e[1] == 'tactical_effect' and e[4] == 'weather_start' and e[5]['new_weather'] == 'rain')
    shots = [('sun', 'sun', '01 / 九尾入场日照', '上场即制造八秒全场晴天，不占教学槽', 1.),
             ('rain', 'rain', '02 / 拉普拉斯入场降雨', '普通招募也可触发，双方共用雨天窗口', 1.),
             ('override', 'sun', '03 / 后续求雨覆盖', '水箭龟首次大招后，求雨覆盖入场日照', override+.3),
             ('conflict', 'conflict', '04 / 入场晴雨相抵', '九尾与拉普拉斯同时入场，恢复基础冰雹', 1.)]
    panels, frames = [], []
    for name, key, title, note, t in shots:
        frame = animations[key].frame(t)
        frame.convert('RGB').save(args.out/f'{name}.png')
        panels.append(panel(frame, title, note, t, fonts))
        frames.append({'name': name, 'fixture': key, 'presentation_time': t,
                       'native_frame': f'{name}.png', 'size': list(frame.size)})
    width, height = panels[0].size
    contact = Image.new('RGB', (width*2, height*2), '#f3f0e7')
    for index, image in enumerate(panels):
        contact.paste(image, ((index%2)*width, (index//2)*height))
    contact.save(args.out/'weather-abilities.png')
    for key in animations:
        animation = animations[key]
        stills = [animation.frame(n/10).convert('RGB') for n in range(106)]
        stills[0].save(args.out/f'{key}.gif', save_all=True, append_images=stills[1:],
                       duration=100, loop=0, disposal=2)
    payload = {'method': __doc__, 'ruleset': 'tactics_v2', 'rules_fingerprint': rules_fingerprint(),
               'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'frames': frames,
               'fixtures': {key: {'raw_events_sha256': hashlib.sha256(json.dumps(battle.events,ensure_ascii=False,
                            separators=(',', ':')).encode()).hexdigest(),
                                 'tactical_events': [e for e in battle.events if e[1] == 'tactical_effect']}
                            for key, battle in battles.items()}}
    (args.out/'visual.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'frames': len(frames), 'gifs': len(animations), 'contact_sheet': str(args.out/'weather-abilities.png')}))


if __name__ == '__main__':
    main()
