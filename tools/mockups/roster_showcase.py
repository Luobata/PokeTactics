#!/usr/bin/env python3
"""Export a natural six-versus-six battle from the active presentation mode.

CLI defaults to the trial arena; --mode classic preserves the signature/generic
fixture and the 240x320 device presentation.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import random

from profile_range import _assets
from render_battle_gif import Battle, BattleAnimation, build_roster, quantize_frames
from skills import skill_of
from presentation_modes import make_renderer, mode_info, normalize_mode


def _scene(seed, mode):
    mode = normalize_mode(mode)
    if mode == 'arena':
        from arena_scenarios import SCENARIOS, make_scene
        anim = make_scene(seed, 'arena_showcase')
        teams = (SCENARIOS['arena_showcase']['a'], SCENARIOS['arena_showcase']['b'])
        end = next(event for event in reversed(anim.events) if event[1] == 'end')
        result = {'winner': end[2], 'duration': end[0],
                  'survivors': {team: sum(unit.alive for unit in anim.by_idx.values()
                                          if unit.team == team) for team in (0, 1)}}
        return anim, result, teams
    pieces = {p.species_id: p for group in build_roster().values() for p in group}
    teams = ((6, 19, 63, 31, 75, 12), (9, 1, 2, 10, 18, 130))
    battle = Battle(*[[pieces[sid] for sid in team] for team in teams], random.Random(seed))
    result = {key: value for key, value in battle.run().items() if key != 'units'}
    return BattleAnimation([], [], seed, *_assets(), battle=battle), result, teams


def export(out, seed=7, *, mode='classic'):
    mode = normalize_mode(mode)
    info = mode_info(mode)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    anim, result, teams = _scene(seed, mode)
    source = copy.deepcopy(anim.events)
    renderer = make_renderer(anim, mode)
    casts = [a for a in anim.timeline.actions if a.kind == "cast" and not a.secondary]
    if mode == 'classic':
        tiers = {skill_of(anim.by_idx[a.attacker].piece.species_id)["tier"] for a in casts}
        if tiers != {"signature", "generic"}:
            raise AssertionError("fixture must actually exercise both skill tiers")
    else:
        import arena_skills
        expected = {unit.idx: 'arena_' + arena_skills.skill_of(unit.piece.species_id)['id']
                    for unit in anim.by_idx.values()}
        if (not casts or anim.battle_rows != 6 or len(anim.by_idx) != 12
                or any(anim.events[action.source_index][4] != expected[action.attacker] for action in casts)):
            raise AssertionError('arena fixture must exercise native skills in the actual 6v6 rules')
        tiers = {'native'}
    frames, hashes, peaks = [], [], {}
    step = .05 if mode == 'arena' else .1
    start = max(0., min(a.start for a in casts) - .5)
    end = min(anim.presentation_duration, start + 8.)
    for i in range(round(anim.presentation_duration / step) + 1):
        t = round(i * step, 6)
        frame = renderer.frame(t, show_cutins=True).convert("RGB")
        hashes.append(hashlib.sha256(frame.tobytes()).hexdigest())
        for key, value in renderer.metrics.items():
            if isinstance(value, (int, float)):
                peaks[key] = max(peaks.get(key, 0), value)
        if start <= t <= end:
            frames.append(frame)
    if anim.events != source:
        raise AssertionError('mixed battle changed the authoritative events')
    if mode == 'classic':
        if peaks.get('particles', 0) > 192 or peaks.get('signature_tracks', 0) > 3:
            raise AssertionError('mixed battle exceeded presentation budgets')
    elif peaks.get('active_actions', 0) > 6 or peaks.get('active_casts', 0) > 6:
        raise AssertionError('arena battle exceeded presentation budgets')
    encoded = quantize_frames(frames)
    encoded[0].save(out / "mixed-battle.gif", save_all=True, append_images=encoded[1:],
                    duration=round(step*1000), loop=0, optimize=False, disposal=2)
    report = {**info, "seed": seed, "teams": teams, "initial_conditions": "normal HP and energy; unmodified Battle",
              "result": result, "rendered_frames": len(hashes), "gif_frames": len(frames),
              "clip_start": start, "clip_end": end, "gif": "mixed-battle.gif", 'skill_tiers': sorted(tiers),
              'frame_size': [renderer.width, renderer.height], 'frame_duration_ms': round(step*1000),
              "casts_by_species": {str(u.piece.species_id): u.casts for u in anim.by_idx.values()},
              "frame_sha256": hashlib.sha256("".join(hashes).encode()).hexdigest(),
              "event_sha256": hashlib.sha256(json.dumps(source, ensure_ascii=False).encode()).hexdigest(),
              "events_preserved": True, 'metrics': peaks,
              **({'particle_peak': peaks.get('particles', 0), 'track_peak': peaks.get('signature_tracks', 0)}
                 if mode == 'classic' else {}),
              "scope": "PC 6v6 real Battle; not balance or ESP32 performance validation"}
    (out / "mixed-battle.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=('arena', 'classic'), default='arena')
    parser.add_argument("--out", type=Path, default=Path(".build/animation-e"))
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    export(args.out, args.seed, mode=args.mode)
