#!/usr/bin/env python3
"""Standalone real-Battle training range; no acceptance server imports.

scene is 'dummy', 'melee', 'ranged' (all four clips), or '<scene>/<action>'.
action is attack/cast/move/hit. Returned frames are native 240x320 RGBA.
Training fixtures have padded HP and fixed deployment, never fabricated events.
"""
import argparse
import hashlib
import json
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
img{image-rendering:pixelated;width:480px;height:640px;border:4px solid #756e53}
main{display:flex;gap:24px;flex-wrap:wrap}p{max-width:560px}</style>
<h1>单体靶场 · 平A / 技能</h1><p>真实 Battle 事件 · 四色精灵 · 10 FPS · 训练用生命值加厚。
平A：清晰弹道、单环星形、标准跳字。技能：脚底蓄力、双外环、微震与大跳字。木桩受击段启用轻触反击。</p>
<select id="clip"></select><button id="play">暂停</button>
<button id="prev">上一帧</button><button id="next">下一帧</button>
<input id="seek" type="range" min="0" value="0"><span id="label"></span>
<main><img id="frame" alt="靶场逐帧动画"><pre id="info"></pre></main>
<script>
let clips=[],index=0,running=true;const $=id=>document.getElementById(id);
function show(){let c=clips[$('clip').value||0];if(!c)return;
index=(index+c.frames)%c.frames;$('frame').src=c.path+'/frame-'+String(index).padStart(3,'0')+'.png';
$('seek').max=c.frames-1;$('seek').value=index;$('label').textContent=(index+1)+' / '+c.frames;
$('info').textContent=JSON.stringify(c,null,2)}
fetch('manifest.json').then(r=>r.json()).then(m=>{clips=m.clips;clips.forEach((c,i)=>{
let o=document.createElement('option');o.value=i;o.textContent=c.species+' / '+c.scene+' / '+c.action;
$('clip').appendChild(o)});show()}).catch(e=>{$('info').textContent='请在此目录运行 python3 -m http.server 后打开本页。 '+e});
$('clip').onchange=()=>{index=0;show()};$('play').onclick=()=>{running=!running;$('play').textContent=running?'暂停':'播放'};
$('prev').onclick=()=>{running=false;index--;show()};$('next').onclick=()=>{running=false;index++;show()};
$('seek').oninput=e=>{running=false;index=Number(e.target.value);show()};
setInterval(()=>{if(running){index++;show()}},100);
</script></html>"""


@lru_cache(maxsize=1)
def _assets():
    return r.Front(), r.Palettes(), r.Font16()


def make_scene(species_id, scene, seed, action="attack"):
    if scene not in SCENES:
        raise ValueError(f"unknown scene {scene!r}; expected {tuple(SCENES)}")
    pieces = {p.species_id: p for ps in r.build_roster().values() for p in ps}
    if species_id not in pieces:
        raise ValueError(f"species {species_id} is not in the roster")
    battle = r.Battle([pieces[species_id]], [pieces[s] for s in SCENES[scene]],
                      random.Random(seed), layout="back")
    positions = [(0, 3), (4, 0), (5, 0), (4, 1), (5, 1)]
    for unit, pos in zip(battle.units, positions):
        unit.pos = pos
        unit.max_hp *= 8 if unit.team == 0 else 12
        unit.hp = unit.max_hp
        if unit.team:
            unit.range = 3 if scene == "ranged" else 1
            if scene == "dummy":
                # Stationary training posts; touch-back only in the hit clip.
                unit.range = 8
                unit.next_act = 1. if action == "hit" else 1e6
                unit.attack = unit.sp_attack = 1
            if action == "move":
                unit.next_act = max(unit.next_act, 2.5)
    # Initial deployment is fixture input; all subsequent events come from Battle.
    battle.events = [(0., "deploy", u.idx, u.pos) for u in battle.units]
    battle.run()
    return r.BattleAnimation([], [], seed, *_assets(), battle=battle)


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
    start = max(0., event[0] - .2)
    end = event[0] + (1.3 if action == "cast" else .9)
    if action in ("attack", "hit"):
        end = max(end, event[0] + anim._attack_delay(event) + .4)
    if action == "move":
        start = max(.4, start)
        # Keep a whole gait period, with at least two true movement events.
        end = event[0] + 1.3
    p0 = anim.playback_clock.playback_time(start)
    p1 = anim.playback_clock.playback_time(end)
    times = [p0 + i * r.FPS_DT for i in range(round((p1 - p0) / r.FPS_DT) + 1)]
    frames = [anim.playback_frame(t, show_cutins=False) for t in times]
    return frames, {"event": event, "sim_start": start, "sim_end": end,
                    "real_events": len(anim.events), "seed": seed,
                    "skill": r.skill_profile(species_id),
                    "cast_windup_seconds": r.cast_windup(species_id),
                    "frame_times": [anim.playback_clock.simulation_time(t) for t in times]}


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
