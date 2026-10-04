#!/usr/bin/env python3
"""Standalone real-Battle training range; no acceptance server imports.

scene is 'dummy', 'melee', 'ranged' (all four clips), or '<scene>/<action>'.
action is attack/cast/move/hit. Returned frames are native 240x320 RGBA.
Training fixtures have padded HP and fixed deployment, never fabricated events.
"""
import argparse
import hashlib
import json
import math
import random
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw

try:
    from . import render_battle_gif as r
except ImportError:
    import render_battle_gif as r

SCENES = {"dummy": (76, 76, 76), "melee": (19, 19, 19, 19),
          "ranged": (22, 22, 22, 22)}
ACTIONS = ("attack", "cast", "move", "hit")
DEFAULT_OUT = r.ROOT / "reports/evidence/range-2026-10-04"

# Static artifact viewer. Host routes can call render_species_scene directly;
# the standalone CLI supplies the same relative PNG paths and manifest.
PROFILE_RANGE_HTML = """<!doctype html><html lang="zh"><meta charset="utf-8">
<title>单体靶场 · 平A / 技能</title><style>
body{background:#eee6ce;color:#292b24;font:16px monospace;margin:24px}
button,select{font:inherit;background:#faf1d4;color:#292b24;padding:8px;border:2px solid #756e53}
#frame{image-rendering:pixelated;width:480px;height:640px;border:4px solid #756e53}
main{display:flex;gap:24px;flex-wrap:wrap}p{max-width:560px}</style>
<h1>单体靶场 · 平A / 技能</h1><p>真实 Battle 事件 · 四色精灵 · 10 FPS · 训练用生命值加厚。
平A：渐细尾迹、属性弹体、紧邻双描边环与弹跳数字。技能：脚底蓄力、多重外环、微震与大跳字。木桩受击段启用轻触反击。</p>
<select id="clip"></select><button id="play">暂停</button>
<button id="prev">上一帧</button><button id="next">下一帧</button>
<button id="retry" hidden>重试载入</button>
<input id="seek" type="range" min="0" value="0"><span id="label"></span>
<main><canvas id="frame" width="240" height="320"></canvas><pre id="info"></pre></main>
<script>""" + Path(__file__).with_name("range_viewer.js").read_text() + "</script></html>"


@lru_cache(maxsize=1)
def _assets():
    return r.Front(), r.Palettes(), r.Font16()


def make_scene(species_id, scene, seed, action="attack", visual_overrides=None):
    if scene not in SCENES:
        raise ValueError(f"unknown scene {scene!r}; expected {tuple(SCENES)}")
    pieces = {p.species_id: p for ps in r.build_roster().values() for p in ps}
    if species_id not in pieces:
        raise ValueError(f"species {species_id} is not in the roster")
    # A ground-type post is immune to Raichu's actual electric move. Use neutral
    # normal-type posts for its visual fixture; immunity remains a combat rule.
    targets = (143, 143, 143) if scene == "dummy" and species_id == 26 else SCENES[scene]
    battle = r.Battle([pieces[species_id]], [pieces[s] for s in targets],
                      random.Random(seed), layout="back")
    positions = [(0, 3), (4, 0), (5, 0), (4, 1), (5, 1)]
    for unit, pos in zip(battle.units, positions):
        unit.pos = pos
        unit.max_hp *= 8 if unit.team == 0 else 12
        if action == "skill":
            unit.max_hp *= 4
        if action == "death" and unit.team == 0:
            unit.max_hp = 1
        unit.hp = unit.max_hp
        if unit.team:
            unit.range = 3 if scene == "ranged" else 1
            if scene == "dummy":
                # Stationary training posts; touch-back only in the hit clip.
                unit.range = 8
                unit.next_act = 1. if action in ("hit", "death") else 1e6
                unit.attack = unit.sp_attack = 1
            if action == "move":
                unit.next_act = max(unit.next_act, 2.5)
    # Initial deployment is fixture input; all subsequent events come from Battle.
    battle.events = [(0., "deploy", u.idx, u.pos) for u in battle.units]
    battle.run()
    return r.BattleAnimation([], [], seed, *_assets(), battle=battle,
                             visual_overrides=visual_overrides)


def make_signature_scene(species_id, seed=7, visual_overrides=None):
    """A precharged real skill in a layout that exposes its tactical effect.

    Initial HP/energy/positions are recorded inputs, including the injured ally
    for solar healing. Subsequent damage, links, healing and movement are produced
    by Battle, not by the showcase or renderer.
    """
    from experiment_signatures import make_signature_battle, run_fixture
    battle = run_fixture(make_signature_battle(species_id, seed))
    return r.BattleAnimation([], [], seed, *_assets(), battle=battle,
                             visual_overrides=visual_overrides)


def make_preview_scene(species_id, kind, seed=7, visual_overrides=None):
    """Create a real action fixture for any roster species, including generic casts.

    Cast fixtures begin injured and fully charged against three durable water
    targets. Water has no type immunity, and the cluster exposes generic spread,
    displacement and healing. Only Battle emits the action and its outcomes.
    """
    from action_preview import PREVIEW_ACTIONS
    if kind not in PREVIEW_ACTIONS:
        raise ValueError(f"unknown preview action {kind!r}")
    if kind == "idle":
        pieces = {p.species_id: p for ps in r.build_roster().values() for p in ps}
        if species_id not in pieces:
            raise ValueError(f"species {species_id} is not in the roster")
        battle = r.Battle([pieces[species_id]], [pieces[9]], random.Random(seed),
                          positions_a=[(0, 3)], positions_b=[(5, 0)])
        battle.events = [(0., "deploy", unit.idx, unit.pos) for unit in battle.units]
        for unit in battle.units:
            battle._emit_state(unit, 0.)
        # Delay the first real action to create a quiet inspection window.
        battle._act(battle.units[0], 2.)
        return r.BattleAnimation([], [], seed, *_assets(), battle=battle,
                                 visual_overrides=visual_overrides)
    if kind != "cast":
        return make_scene(species_id, "dummy", seed, kind, visual_overrides)
    if species_id in r.SUPPORTED_SPECIES:
        return make_signature_scene(species_id, seed, visual_overrides)
    from data import ENERGY_MAX
    from experiment_signatures import run_fixture
    pieces = {p.species_id: p for ps in r.build_roster().values() for p in ps}
    if species_id not in pieces:
        raise ValueError(f"species {species_id} is not in the roster")
    battle = r.Battle([pieces[species_id]], [pieces[9]] * 3, random.Random(seed))
    for unit, position in zip(battle.units, ((2, 3), (2, 2), (1, 2), (3, 2))):
        unit.pos = position
        unit.max_hp *= 6
        unit.hp = unit.max_hp
        unit.energy = 0
        unit.next_act = 1e6
    caster = battle.units[0]
    caster.hp = caster.max_hp // 2
    caster.energy, caster.next_act, caster.target_idx = ENERGY_MAX, .5, 1
    battle.fixture_target_idx = 1
    battle.events = [(0., "deploy", unit.idx, unit.pos) for unit in battle.units]
    for unit in battle.units:
        battle._emit_state(unit, 0.)
    run_fixture(battle)
    return r.BattleAnimation([], [], seed, *_assets(), battle=battle,
                             visual_overrides=visual_overrides)


def _clip(species_id, scene, seed, action):
    anim = make_scene(species_id, scene, seed, action)
    if action == "hit":
        candidates = [e for e in anim.events if e[1] == "attack" and e[3] == 0 and e[4] > 0]
    else:
        candidates = [e for e in anim.events if e[1] == action and e[2] == 0]
        if action == "move":
            candidates = [e for e in candidates if e[0] >= .35] or candidates
    if not candidates:
        raise RuntimeError(f"no real {action} event for {species_id}/{scene}, seed={seed}")
    event = candidates[0]
    source_index = next(i for i, value in enumerate(anim.events) if value is event)
    timing = next((a for a in anim.timeline.actions if a.source_index == source_index), None)
    if timing:
        start = max(0., timing.start - .2)
        end = max(timing.recover_end + .2, timing.impact + (.6 if action == "cast" else .4))
    else:
        # Movement has no ActionTiming, but shares the same causal presentation
        # stream. Match its payload and original time through the emitted map.
        scheduled = {at for raw, at in anim.timeline.source_times.values() if raw == event[0]}
        onset = next(e[0] for e in anim.timeline.events
                     if e[1:] == event[1:] and e[0] in scheduled)
        start, end = max(.4, onset - .2), onset + 1.3
    times = [round(start + i * r.FPS_DT, 6)
             for i in range(math.ceil((end - start) / r.FPS_DT - 1e-8) + 1)]
    frames = [anim.playback_frame(t, show_cutins=False) for t in times]
    source_end = event[0] + (1.3 if action in ("cast", "move") else .9)
    if action in ("attack", "hit"):
        source_end = max(source_end, event[0] + anim._attack_delay(event) + .4)
    return frames, {"event": event, "source_event_index": source_index,
                    "sim_start": max(0., event[0] - .2), "sim_end": source_end,
                    "presentation_start": times[0], "presentation_end": times[-1],
                    "action_timing": ({name: getattr(timing, name) for name in
                                       ("start", "release", "impact", "recover_end")} if timing else None),
                    "real_events": len(anim.events), "seed": seed,
                    "skill": r.skill_profile(species_id),
                    "cast_windup_seconds": r.cast_windup(species_id),
                    "frame_times": times, "time_domain": "presentation"}


def render_species_scene(species_id, scene, seed):
    """Return deterministic PIL frames; scene='dummy/cast' selects one clip."""
    parts = scene.split("/")
    target, actions = parts[0], (parts[1],) if len(parts) == 2 else ACTIONS
    if len(parts) > 2 or any(a not in ACTIONS for a in actions):
        raise ValueError("scene must be dummy|melee|ranged[/attack|cast|move|hit]")
    return [frame for action in actions for frame in _clip(species_id, target, seed, action)[0]]


def frame_hash(frames):
    digest = hashlib.sha256()
    for frame in frames:
        digest.update(frame.mode.encode())
        digest.update(str(frame.size).encode())
        digest.update(frame.tobytes())
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--species", default="6,65,143")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    ids = [int(s) for s in args.species.split(",")]
    args.out.mkdir(parents=True, exist_ok=True)
    clips, sheets = [], []
    for sid in ids:
        # Every frame of every clip appears on the per-species contact sheet.
        rows = []
        for scene in SCENES:
            for action in ACTIONS:
                frames, meta = _clip(sid, scene, args.seed, action)
                again = render_species_scene(sid, f"{scene}/{action}", args.seed)
                digest = frame_hash(frames)
                if digest != frame_hash(again):
                    raise AssertionError(f"non-deterministic: {sid}/{scene}/{action}")
                rel = Path(str(sid)) / scene / action
                dest = args.out / rel
                dest.mkdir(parents=True, exist_ok=True)
                for stale in dest.glob("frame-[0-9][0-9][0-9].png"):
                    stale.unlink()
                for i, frame in enumerate(frames):
                    frame.save(dest / f"frame-{i:03d}.png")
                contact = Image.new("RGB", (r.W * 4, (r.H + 24) * ((len(frames) + 3) // 4)), r.PAPER)
                for i, frame in enumerate(frames):
                    x, y = i % 4 * r.W, i // 4 * (r.H + 24)
                    contact.paste(frame.convert("RGB"), (x, y + 24))
                    ImageDraw.Draw(contact).text((x + 4, y + 4), f"{sid}/{scene}/{action} #{i}", fill=r.INK)
                contact.save(dest / "contact.png")
                frames[0].save(dest / "animation.gif", save_all=True,
                               append_images=frames[1:], duration=100, loop=0)
                row = Image.new("RGB", (r.W * len(frames), r.H + 24), r.PAPER)
                ImageDraw.Draw(row).text((4, 5), f"{sid} / {scene} / {action}", fill=r.INK)
                for i, frame in enumerate(frames):
                    row.paste(frame.convert("RGB"), (i * r.W, 24))
                rows.append(row)
                # Four useful phases per clip in the compact master sheet.
                strip = Image.new("RGB", (r.W * 4, r.H + 24), r.PAPER)
                ImageDraw.Draw(strip).text((4, 5), f"{sid} / {scene} / {action}", fill=r.INK)
                for x, i in enumerate([round((len(frames) - 1) * k / 3) for k in range(4)]):
                    strip.paste(frames[i].convert("RGB"), (x * r.W, 24))
                sheets.append(strip)
                clips.append({"species": sid, "scene": scene, "action": action,
                              "path": rel.as_posix(), "frames": len(frames),
                              "sha256": digest, "deterministic": True, **meta})
                print(f"PASS {sid}/{scene}/{action}: {len(frames)} frames {digest[:12]}", flush=True)
        sheet = Image.new("RGB", (max(row.width for row in rows), sum(row.height for row in rows)), r.PAPER)
        for i, row in enumerate(rows):
            sheet.paste(row, (0, i * (r.H + 24)))
        sheet.save(args.out / f"{sid}-all-frames.png")
    master = Image.new("RGB", (r.W * 4 * len(ids), (r.H + 24) * 12), r.PAPER)
    for i, strip in enumerate(sheets):
        master.paste(strip, ((i // 12) * r.W * 4, (i % 12) * (r.H + 24)))
    master.save(args.out / "contact-sheet.png")
    (args.out / "index.html").write_text(PROFILE_RANGE_HTML)
    (args.out / "manifest.json").write_text(json.dumps({"clips": clips, "fixture":
        "Hero HP x8; target HP x12. Dummy remains stationary; hit clip enables weak touch-back. "
        "Movement clips delay targets until 2.5s to show approach gait. "
        "All actions and damage are emitted by sim.Battle."}, ensure_ascii=False, indent=2) + "\n")
    print(f"PASS {len(clips)} clips, {sum(c['frames'] for c in clips)} PNG frames; {args.out}")


if __name__ == "__main__":
    main()
