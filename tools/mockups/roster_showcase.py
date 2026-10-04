#!/usr/bin/env python3
"""Verify and show a natural mixed battle with core and generic characters."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import random

from profile_range import _assets
from render_battle_gif import Battle, BattleAnimation, build_roster, quantize_frames
from skills import skill_of


def export(out, seed=7):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    pieces = {p.species_id: p for group in build_roster().values() for p in group}
    teams = ((6, 19, 63, 31, 75, 12), (9, 1, 2, 10, 18, 130))
    battle = Battle(*[[pieces[sid] for sid in team] for team in teams], random.Random(seed))
    result = battle.run()
    source = copy.deepcopy(battle.events)
    anim = BattleAnimation([], [], seed, *_assets(), battle=battle)
    casts = [a for a in anim.timeline.actions if a.kind == "cast" and not a.secondary]
    tiers = {skill_of(anim.by_idx[a.attacker].piece.species_id)["tier"] for a in casts}
    if tiers != {"signature", "generic"}:
        raise AssertionError("fixture must actually exercise both skill tiers")
    frames, hashes, particle_peak, track_peak = [], [], 0, 0
    start = max(0., min(a.start for a in casts) - .5)
    end = min(anim.presentation_duration, start + 8.)
    for i in range(round(anim.presentation_duration / .1) + 1):
        t = round(i * .1, 6)
        frame = anim.playback_frame(t, show_cutins=True).convert("RGB")
        hashes.append(hashlib.sha256(frame.tobytes()).hexdigest())
        metrics = anim._presentation_view().last_frame_metrics
        particle_peak = max(particle_peak, metrics["particles"])
        track_peak = max(track_peak, metrics["signature_tracks"])
        if start <= t <= end:
            frames.append(frame)
    if battle.events != source or particle_peak > 192 or track_peak > 3:
        raise AssertionError("mixed battle changed events or exceeded presentation budgets")
    encoded = quantize_frames(frames)
    encoded[0].save(out / "mixed-battle.gif", save_all=True, append_images=encoded[1:],
                    duration=100, loop=0, optimize=False, disposal=2)
    report = {"seed": seed, "teams": teams, "initial_conditions": "normal HP and energy; unmodified Battle",
              "result": {k: v for k, v in result.items() if k != "units"}, "rendered_frames": len(hashes), "gif_frames": len(frames),
              "clip_start": start, "clip_end": end, "gif": "mixed-battle.gif",
              "casts_by_species": {str(u.piece.species_id): u.casts for u in battle.units},
              "frame_sha256": hashlib.sha256("".join(hashes).encode()).hexdigest(),
              "event_sha256": hashlib.sha256(json.dumps(source, ensure_ascii=False).encode()).hexdigest(),
              "events_preserved": True, "particle_peak": particle_peak, "track_peak": track_peak,
              "scope": "PC 6v6 mixed battle; not balance or ESP32 performance validation"}
    (out / "mixed-battle.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path(".build/animation-e"))
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    export(args.out, args.seed)
