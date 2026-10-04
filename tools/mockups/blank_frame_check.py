#!/usr/bin/env python3
"""Independent attachment regression and before/after visual evidence."""
import hashlib
import importlib.util
import json
import sys
from PIL import Image, ImageDraw, ImageChops
import motion
import profile_range as training
from blank_frame_audit import OUT, old_rig, count


def main():
    # A continuous source body cannot acquire internal transparent cut lines.
    # Keep a three-pixel outside margin: authored silhouette motion is <=2px.
    solid = Image.new('RGBA', (34, 34), (10, 30, 50, 255))
    cases, before_gaps, after_gaps = 0, 0, 0
    failures = []
    for sid, states in motion.species_motion.items():
        for state, sequence in states.items():
            for index in range(len(sequence)):
                cases += 1
                box = (3, 3, 31, 31)
                old = old_rig(solid, sid, index).getchannel('A').crop(box)
                new = motion.rig_cel(solid, sid, index).getchannel('A').crop(box)
                before_gaps += old.histogram()[0]
                after_gaps += new.histogram()[0]
                if new.histogram()[0]: failures.append(f'{sid}/{state}/{index}')
    # Real source palettes and exact ordered dissolution must survive repair.
    dissolved, empty, off_palette = 0, 0, 0
    for sid, states in motion.species_motion.items():
        anim = training.make_scene(sid, 'melee', 7)
        source = anim._board_sprite(sid, anim.units[0].u.piece.tier)
        colors = set(source.getdata())
        for state, sequence in states.items():
            for index, frame in enumerate(sequence):
                out = motion.transform(source, sid, motion.Pose(state, index, frame))
                empty += not bool(out.getbbox())
                off_palette += sum(1 for c in out.getdata() if c[3] and c not in colors)
                if frame[5]:
                    dissolved += 1
                    clean = motion.transform(source, sid, motion.Pose(state, index, (*frame[:5], 0)))
                    expected = clean.getchannel('A')
                    expected.putdata([a if x%2+2*(y%2) >= frame[5] else 0
                                      for y in range(out.height) for x in range(out.width)
                                      for a in (expected.getpixel((x,y)),)])
                    if expected.tobytes() != out.getchannel('A').tobytes():
                        failures.append(f'dissolve/{sid}/{state}/{index}')
    spec = importlib.util.spec_from_file_location('baseline_motion', OUT/'baseline_motion.py')
    old = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = old
    spec.loader.exec_module(old)
    sheet = Image.new('RGB', (720, 16*190), (238,230,206))
    draw = ImageDraw.Draw(sheet)
    for row, sid in enumerate(motion.species_motion):
        anim = training.make_scene(sid, 'melee', 7)
        source = anim._board_sprite(sid, anim.units[0].u.piece.tier)
        # Select the largest restored attachment in an idle cycle, not death.
        candidates = []
        for i, frame in enumerate(motion.species_motion[sid]['idle']):
            p = motion.Pose('idle', i, frame)
            before, after = old.transform(source, sid, p), motion.transform(source, sid, p)
            restored = ImageChops.subtract(after.getchannel('A'), before.getchannel('A'))
            candidates.append((count(restored), i, before, after, restored))
        pixels, index, before, after, restored = max(candidates, key=lambda x:x[0])
        draw.text((8,row*190+5), f'{sid} idle #{index}: c94b225 | fixed | restored alpha ({pixels}px)', fill=(25,25,25))
        for col, im in enumerate((before, after, restored.convert('RGBA'))):
            tile = Image.new('RGBA', (40,40), (238,230,206,255))
            tile.alpha_composite(im, (3,3))
            sheet.paste(tile.convert('RGB').resize((160,160),Image.Resampling.NEAREST), (col*240+30,row*190+24))
    sheet.save(OUT/'rig-before-after.png')
    result = {'passed': not failures and not after_gaps and not empty and not off_palette,
              'cases': cases, 'baseline_internal_gap_pixels': before_gaps,
              'fixed_internal_gap_pixels': after_gaps, 'dissolve_masks_preserved': dissolved,
              'empty_authored_cels': empty, 'off_palette_pixels': off_palette, 'failures': failures}
    (OUT/'rig-regression.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))
    if not result['passed']: raise SystemExit(1)


if __name__ == '__main__': main()
