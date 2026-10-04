#!/usr/bin/env python3
"""R2 rendered-pixel contracts; real Battle pairs plus exhaustive template fixtures."""
import copy
import hashlib
import json
import math
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageChops, ImageDraw

import render_battle_gif as r
from profile_range import make_scene
from skill_vfx import ARCHS, draw_skill, skill_profile

OUT = r.ROOT / 'reports/evidence/vfx-separation-2026-10-04'
AREA_RATIO_MIN = 1.7


def pixels(layer):
    return layer.width * layer.height - layer.getchannel('A').histogram()[0]


def isolated_fx(anim, event, t):
    """Retain real geometry, exclude unrelated actions, then apply production body mask."""
    anim._ensure(t)
    probe = copy.copy(anim)
    if event[1] == 'cast':
        probe.cutins = [c for c in anim.cutins if c[0] == event[0] and c[2] == event[2]]
    else:
        probe.cutins = []
    probe.events = [e for e in anim.events[:anim._cursor] if e[1] in ('deploy', 'move') or e is event]
    probe._cursor = len(probe.events)
    poses = {i: probe._unit_pose(u, t) for i, u in probe.units.items() if u.visible(t)}
    layer = Image.new('RGBA', (r.W, r.H))
    budget = r.ParticleBudget()
    probe._draw_board_fx(layer, t, budget, poses)
    mask = Image.new('L', layer.size)
    for i, pose in poses.items():
        if pose is not None:
            sprite, x, y = probe._sprite_placement(probe.units[i], t, pose)
            body = Image.new('L', layer.size)
            body.paste(sprite.getchannel('A'), (x, y))
            mask = ImageChops.lighter(mask, body)
    layer.putalpha(ImageChops.subtract(layer.getchannel('A'), mask))
    return layer.crop((r.BX, r.BY, r.BX + r.BCOLS * r.BCELL, r.BY + r.BROWS * r.BCELL)), budget.used, probe


def motion_checks(require):
    anim = make_scene(6, 'dummy', 7)
    anim.units = {0: copy.deepcopy(anim.units[0])}
    anim.events = []
    anim._reset()
    unit = anim.units[0]
    idle = []
    for piece in [p for group in r.build_roster().values() for p in group]:
        unit.u.piece = piece
        unit.init_px = (80, 120)
        unit.reset()
        frames = []
        for i in range(12):
            t = 2 + i * .1
            layer = Image.new('RGBA', (r.W, r.H))
            anim._draw_unit(layer, unit, t, anim._unit_pose(unit, t), r.ParticleBudget())
            frames.append(hashlib.sha256(layer.tobytes()).hexdigest())
        require(len(set(frames)) >= 2, f'idle breath {piece.species_id}')
        idle.append(piece.species_id)
    unit.reset()
    unit.attacks = [(2., 1., 0.)]
    require(anim._attack_motion(unit, 2.) == (-1., 0., 0), 'one-frame reverse preparation')
    # No dying neighbour: the added 0.2s phase visibly sinks and loses alpha.
    unit.reset()
    unit.die_t = 1.
    death = []
    for t in (1.4, 1.5):
        layer = Image.new('RGBA', (r.W, r.H))
        pose = anim._unit_pose(unit, t)
        anim._draw_unit(layer, unit, t, pose, r.ParticleBudget())
        death.append({'t': t, 'pose_y': pose[1], 'alpha_sum': sum(i * n for i, n in enumerate(layer.getchannel('A').histogram()))})
    require(death[1]['pose_y'] > death[0]['pose_y'] and 0 < death[1]['alpha_sum'] < death[0]['alpha_sum'], 'death sink/fade')
    require(anim._unit_pose(unit, 1.6) is None, 'death ends at .6s')
    unit.reset()
    anim._apply((2., 'move', 0, (3, 2)))
    require(len(anim.dusts) == 1 and math.isclose(anim.dusts[0][0], 2 + r.MOVE_SMOOTH), 'dust starts at step landing')
    dust_start = anim.dusts[0][0]
    def budget_at(t):
        calls = []
        original = r.ParticleBudget.take
        def tracked(b, count, *args, **kwargs):
            calls.append(count)
            return original(b, count, *args, **kwargs)
        with patch.object(r.ParticleBudget, 'take', tracked):
            anim._draw_board(Image.new('RGBA', (r.W, r.H)), t)
        return calls
    require(budget_at(dust_start).count(2) == 1 and budget_at(dust_start - .01).count(2) == 0, 'two landing dust particles')
    return {'idle_species': len(set(idle)), 'attack_preparation_seconds': .1,
            'reverse_offset_px': 1, 'death_extension_samples': death, 'step_dust_particles': 2}


def checks(output=None):
    failures, pairs = [], []
    def require(value, name):
        if not value:
            failures.append(name)
    if output:
        output.mkdir(parents=True, exist_ok=True)
    for sid in (6, 65, 143, 76):
        anim = make_scene(sid, 'dummy', 7)
        attack = next(e for e in anim.events if e[1] == 'attack' and e[2] == 0)
        cast = next(e for e in anim.events if e[1] == 'cast' and e[2] == 0)
        anim._ensure(attack[0])
        attack_has_no_charge = anim._casting_phase(anim.units[0], attack[0]) is None
        anim._ensure(cast[0])
        c = next(c for c in anim.cutins if c[0] == cast[0] and c[2] == 0)
        times = (attack[0] + anim._attack_delay(attack), c[1])
        layers, feedback, peaks, moments = [], [], [], []
        for event, at in zip((attack, cast), times):
            samples = []
            for step in range(3 if event[1] == 'attack' else 6):
                t = at + step * r.FPS_DT
                layer, used, probe = isolated_fx(anim, event, t)
                samples.append((pixels(layer), t, layer, used))
            count, t, layer, used = max(samples, key=lambda v: v[0])
            layers.append(layer)
            peaks.append(count)
            moments.append(t)
            _, _, probe = isolated_fx(anim, event, at)
            calls = []
            probe._draw_damage_number = lambda img, xy, text, color, scale: calls.append((color, scale))
            probe._draw_floats(Image.new('RGBA', (r.W, r.H)), at + .01)
            expected_color = (255,255,255) if event[1] == 'attack' else ((255,90,70) if cast[5] > 1 else (255,220,60))
            scales = [scale for color, scale in calls if color == expected_color]
            require(bool(scales), f'number present {sid}/{event[1]}')
            # Instrument actual ellipse calls, count full outer impact rings.
            rings = []
            original = ImageDraw.ImageDraw.ellipse
            def record(draw, box, *args, **kwargs):
                if kwargs.get('outline') and box[2] - box[0] >= 52 and box[3] - box[1] >= 52:
                    rings.append(box)
                return original(draw, box, *args, **kwargs)
            with patch.object(ImageDraw.ImageDraw, 'ellipse', record):
                probe._draw_board_fx(Image.new('RGBA', (r.W, r.H)), at, r.ParticleBudget(), {})
            feedback.append({'outer_rings': len(rings), 'shake_px': abs(probe._board_shake(at)),
                             'digit_height_px': round(7 * max(scales)) if scales else 0})
        phases, base_phases = [], []
        for step in range(round((c[1] - c[0]) / r.FPS_DT)):
            t = c[0] + step * r.FPS_DT
            anim._ensure(t)
            phases.append(anim._casting_phase(anim.units[0], t))
            with patch.object(r, 'draw_base', wraps=r.draw_base) as base:
                anim._draw_unit(Image.new('RGBA', (r.W, r.H)), anim.units[0], t,
                                anim._unit_pose(anim.units[0], t), r.ParticleBudget())
                base_phases.append(base.call_args.args[-1])
        windup = round(len([p for p in phases if p is not None]) * r.FPS_DT, 2)
        ratio = round(peaks[1] / peaks[0], 3)
        # Energy-ready preview is an independent fixture: sim may consume 80
        # energy in the same tick, so a real pre-cast frame need not retain it.
        unit = copy.deepcopy(anim.units[0])
        unit.reset()
        energy_rings = []
        original = ImageDraw.ImageDraw.ellipse
        def energy_ring(draw, box, *args, **kwargs):
            color = kwargs.get('outline', ())
            if tuple(color[:3]) == r.FULL_GOLD and len(color) == 4 and kwargs.get('width') == 2:
                energy_rings.append(color[3])
            return original(draw, box, *args, **kwargs)
        energy_counts = []
        with patch.object(ImageDraw.ImageDraw, 'ellipse', energy_ring):
            for energy, t in [(79, 2.)] + [(80, 2. + i * r.FPS_DT) for i in range(6)]:
                unit.energy = energy
                before = len(energy_rings)
                anim._draw_unit(Image.new('RGBA', (r.W, r.H)), unit, t,
                                (80, 120, None), r.ParticleBudget())
                energy_counts.append(len(energy_rings) - before)
        rituals = {
            'attack_has_no_charge': attack_has_no_charge,
            'charge_0_4_to_0_5s': .4 <= windup <= .5,
            'charge_base_progresses': all(p is not None for p in base_phases) and len(set(base_phases)) > 1,
            'single_vs_double_outer_rings': feedback[0]['outer_rings'] == 1 and feedback[1]['outer_rings'] >= 2,
            'skill_only_2px_shake': feedback[0]['shake_px'] == 0 and feedback[1]['shake_px'] == 2,
            'standard_vs_large_digits': feedback[0]['digit_height_px'] == 7 and feedback[1]['digit_height_px'] == 8,
            'energy_ready_breathing_ring': energy_counts == [0] + [1] * 6 and len(set(energy_rings)) == 3,
        }
        require(peaks[1] / peaks[0] >= AREA_RATIO_MIN, f'FX area >={AREA_RATIO_MIN}x {sid}: {ratio}')
        for name, passed in rituals.items():
            require(passed, f'ritual {name} {sid}')
        # Frame API and presentation API produce identical same-time pixels,
        # and rewind restores them byte-for-byte.
        hashes = []
        for t in moments:
            a = anim.frame(t, show_cutins=False)
            anim.frame(t + 1, show_cutins=False)
            b = anim.playback_frame(anim.playback_clock.playback_time(t), show_cutins=False)
            require(a.tobytes() == b.tobytes(), f'frame/playback/rewind {sid}/{t}')
            hashes.append(hashlib.sha256(a.tobytes()).hexdigest())
        if output:
            sheet = Image.new('RGB', (r.W * 4, r.H + 20), r.PAPER)
            for i, (event, t, layer) in enumerate(zip((attack, cast), moments, layers)):
                frame = anim.frame(t, show_cutins=False)
                sheet.paste(frame.convert('RGB'), (i * r.W * 2, 20))
                sheet.paste(layer.convert('RGB'), (i * r.W * 2 + r.W, r.BY + 20))
                ImageDraw.Draw(sheet).text((i * r.W * 2 + 4, 4), f'{sid} {event[1]} t={t:.2f} / isolated FX', fill=r.INK)
            sheet.save(output / f'pair-{sid}.png')
        pairs.append({'species': sid, 'skill': skill_profile(sid), 'events': [attack, cast],
                      'frame_times': moments, 'visible_fx_pixels': peaks, 'cast_attack_area_ratio': ratio,
                      'charge_seconds': [0, windup], 'feedback': feedback, 'frame_sha256': hashes})
        pairs[-1].update({'rituals': rituals, 'rituals_all_true': all(rituals.values()),
                         'area_ratio_passed': peaks[1] / peaks[0] >= AREA_RATIO_MIN,
                         'charge_base_phases': base_phases, 'energy_preview_alpha': energy_rings})
    motion = motion_checks(require)
    # All nine primitives under both tiers, all release phases, zero/full budgets.
    templates, peak_budget = [], 0
    atlas = Image.new('RGBA', (r.W * 6, 180 * len(ARCHS)), r.NIGHT)
    for tier in ('generic', 'signature'):
        for arch in ARCHS:
            digests, counts = [], []
            for step in range(10):
                layer = Image.new('RGBA', (r.W, r.H))
                budget = r.ParticleBudget()
                draw_skill(layer, {'arch': arch, 'tier': tier, 'type': 'FIRE'},
                           (60, 130), (160, 130), step * .1, .4, budget)
                peak_budget = max(peak_budget, budget.used)
                digests.append(hashlib.sha256(layer.tobytes()).hexdigest())
                counts.append(pixels(layer))
                if tier == 'generic' and step >= 4:
                    col, row = step - 4, ARCHS.index(arch)
                    atlas.paste(layer.crop((0, 50, r.W, 210)), (col * r.W, row * 180 + 20))
                    ImageDraw.Draw(atlas).text((col * r.W + 4, row * 180 + 3), f'{arch} +{(step - 4) * .1:.1f}s', fill=r.PAPER)
            require(min(counts) > 0 and len(set(digests)) >= 6, f'template phases {tier}/{arch}')
            templates.append({'tier': tier, 'arch': arch, 'unique_frames': len(set(digests)), 'max_pixels': max(counts)})
    if output:
        atlas.convert('RGB').save(output / 'nine-primitives.png')
    # The second parallel slash starts at 150ms, even though GIF samples at 100ms.
    slash_frames = []
    for age in (.549, .55):
        layer = Image.new('RGBA', (r.W, r.H))
        draw_skill(layer, {'arch': 'double_strike', 'tier': 'generic', 'type': 'FIRE'},
                   (60,130), (160,130), age, .4, r.ParticleBudget())
        slash_frames.append(pixels(layer))
    require(slash_frames[1] > slash_frames[0], 'second slash starts at .15s')
    b = r.ParticleBudget(999)
    for _ in range(100):
        b.take(8, required=True)
    require(b.used <= 192 and b.limit == 192, 'hard budget clamp')
    # Real render stress includes weather, dust, status, overlapping templates.
    from fx_visibility_check import make_animation
    original_take = r.ParticleBudget.take
    observed = []
    def tracked(budget, *args, **kwargs):
        result = original_take(budget, *args, **kwargs)
        observed.append(budget.used)
        require(budget.used <= budget.limit <= 192, 'real render budget')
        return result
    with patch.object(r.ParticleBudget, 'take', tracked):
        stress = make_animation(7)
        for i in range(math.ceil(stress.events[-1][0] / .1) + 12):
            stress.frame(i * .1)
    peak_budget = max(peak_budget, max(observed))
    # Module absence must retain the three signature profiles and a generic fallback.
    with patch('skill_vfx._skill_of', None):
        require(all(skill_profile(s)['tier'] == 'signature' for s in (6,65,143)), 'signature fallback')
        require(skill_profile(76)['tier'] == 'generic', 'generic fallback')
    return {'thresholds': {'area_ratio_min': AREA_RATIO_MIN, 'charge_seconds_min': .4, 'attack_charge_seconds': 0,
                           'rule': 'area ratio >=1.7 AND every ritual predicate true',
                           'outer_rings': [1,2], 'shake_px': [0,2], 'digit_height_px': [7,8]},
            'pairs': pairs, 'motion': motion, 'templates': templates, 'peak_render_particles': peak_budget,
            'hard_cap_stress': b.used, 'failures': failures, 'passed': not failures}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUT)
    args = parser.parse_args()
    result = checks(args.output)
    (args.output / 'separation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['passed'] else 1)
