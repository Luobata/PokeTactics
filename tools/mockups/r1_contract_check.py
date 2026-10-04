#!/usr/bin/env python3
"""Focused R1 contracts: energy ABI, clock, projectiles, gait, budget, signatures."""
import copy
import json
import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

import render_battle_gif as r
from profile_vfx import PlaybackClock, pose_sprite


def checks():
    from profile_range import make_scene
    anim = make_scene(6, "dummy", 7)
    failures, samples = [], {}

    def require(condition, name):
        if not condition:
            failures.append(name)

    # Old/new tuple lengths, including nonzero cast energy and rewind.
    probe = copy.copy(anim)
    probe.units = copy.deepcopy(anim.units)
    probe.events = [(0., "deploy", 0, (0, 3)), (0., "deploy", 1, (3, 0)),
                    (1., "attack", 0, 1, 1, 77), (2., "attack", 0, 1, 1),
                    (3., "cast", 0, 1, "fixture", 1, 1, 23),
                    (4., "cast", 0, 1, "fixture", 1, 1)]
    probe._reset()
    for t, energy in ((1., 77), (2., 80), (3., 23), (4., 0), (1., 77)):
        probe._ensure(t)
        require(probe.units[0].energy == energy, f"energy at {t}")
    samples["energy"] = "new attack/cast + legacy fallback + rewind"

    clock = PlaybackClock([(1., "die", 0), (1., "die", 1),
                           (1.03, "die", 2), (2., "die", 3), (3., "die", 4)])
    require(clock.starts == (1., 2.), "kill merge/cap")
    for speed in (1., 2., 4.):
        for sim in (0., 1., 1.03, 1.105, 1.5, 2., 2.105, 3., 4.):
            play = clock.playback_time(sim, speed)
            require(math.isclose(clock.simulation_time(play, speed), sim, abs_tol=1e-8), "clock inverse")
            require(clock.simulation_time(sim / speed, speed, skip=True) == sim, "skip")
    require(math.isclose(clock.simulation_time(1.35), 1.105), "0.35s at 0.3x")
    samples["clock"] = {"windows": clock.starts, "speeds": [1, 2, 4], "duration": .35, "rate": .3}

    probe.events = [(0., "deploy", 0, (0, 3)), (0., "deploy", 1, (3, 0)),
                    (1., "attack", 0, 1, 1), (1.1, "die", 1)]
    probe._reset()
    probe._ensure(1.)
    layer = Image.new("RGBA", (r.W, r.H))
    probe._draw_projectiles(layer, 1., r.ParticleBudget())
    require(layer.getbbox() is not None, "projectile launch")
    first_delay = probe._attack_delay(probe.events[2])
    probe.units[0].u.range *= 2
    require(probe._attack_delay(probe.events[2]) > first_delay, "inverse range speed")
    probe._ensure(1.1)
    layer = Image.new("RGBA", (r.W, r.H))
    probe._draw_projectiles(layer, 1.1, r.ParticleBudget())
    require(layer.getbbox() is None, "dead target dissipates")
    require(not probe._recent_hits(1.8), "cancelled projectile has no later hit")
    samples["projectile"] = "launch / inverse speed / death cancellation"

    # Measure actual filled polygon coordinates, including inclusive pixels;
    # rounding a half-pixel radius must never turn 24px into 25px on a 32px sprite.
    star = copy.copy(anim)
    star.units = copy.deepcopy(anim.units)
    star._reset()
    star.units[0].u.range = 1
    star.units[1].u.max_hp = 100
    star.units[0].from_px = star.units[0].to_px = (20, 100)
    star.units[1].from_px = star.units[1].to_px = (100, 100)
    polygons = []
    original_polygon = ImageDraw.ImageDraw.polygon
    def record_polygon(draw, xy, *args, **kwargs):
        if kwargs.get("fill") is not None:
            polygons.append(max(max(p[0] for p in xy) - min(p[0] for p in xy) + 1,
                                max(p[1] for p in xy) - min(p[1] for p in xy) + 1))
        return original_polygon(draw, xy, *args, **kwargs)
    solid_sizes = []
    try:
        ImageDraw.ImageDraw.polygon = record_polygon
        for tier in (1, 3):
            star.units[1].u.piece.tier = tier
            polygons.clear()
            for damage in (5, 10, 20):
                for onset in (1., 1.1):
                    star.events = [(onset, "attack", 0, 1, damage)]
                    star._cursor = 1
                    for phase in range(3):
                        star._draw_board_fx(Image.new("RGBA", (r.W, r.H)),
                                            onset + .1 + phase * .1, r.ParticleBudget(), {})
            diameter = max(polygons)
            limit = math.floor(r.board_sprite_size(tier) * .75)
            require(diameter <= limit, f"solid star 75% tier {tier}")
            solid_sizes.append({"sprite_px": r.board_sprite_size(tier), "solid_px": diameter, "limit_px": limit})
    finally:
        ImageDraw.ImageDraw.polygon = original_polygon
    samples["solid_star_bounds"] = solid_sizes

    budgets = []
    for limit in (0, 1, 8, 192):
        b = r.ParticleBudget(limit)
        for _ in range(50):
            b.take(8, required=True)
            b.take(3)
        require(b.used <= limit, "particle cap")
        budgets.append([limit, b.used])
    samples["particle_budgets"] = budgets

    motions = []
    max_body_overlap = 0
    peak_budget = 0
    for sid in (6, 65, 143):
        a = make_scene(sid, "dummy", 7)
        au = a.units[0]
        gait = a._gait(au)
        sprite = a._board_sprite(sid, au.u.piece.tier)
        phases = [pose_sprite(sprite, gait, phase, True) for phase in (0, 1)]
        pixels = ImageChops.difference(phases[0], phases[1]).convert("RGB")
        changed = sum(any(pixel) for pixel in pixels.getdata())
        require(changed > 0, f"two-frame gait {sid}")
        allowed = set(a.pal.for_species(sid))
        require(all(c[:3] in allowed and c[3] == 255 for im in phases for c in im.getdata() if c[3]),
                f"gait palette {sid}")
        event = next(e for e in a.events if e[1] == "cast" and e[2] == 0)
        a._ensure(event[0] + .7)
        # Scrubbing across a signature must restore exactly the same pixels.
        first = a.frame(event[0] + .1, show_cutins=False)
        a.frame(event[0] + 1, show_cutins=False)
        require(a.frame(event[0] + .1, show_cutins=False).tobytes() == first.tobytes(), f"signature rewind {sid}")
        quiet = copy.copy(a)
        quiet._draw_board_fx = lambda *_: None
        t = event[0] + r.SIGNATURES[sid].windup + .1
        a._ensure(t)
        with_fx, without_fx = [Image.new("RGBA", (r.W, r.H)) for _ in range(2)]
        a._draw_board(with_fx, t)
        quiet._draw_board(without_fx, t)
        delta = ImageChops.difference(with_fx.convert("RGB"), without_fx.convert("RGB"))
        for unit in a.units.values():
            pose = a._unit_pose(unit, t)
            if not unit.visible(t) or pose is None:
                continue
            body, x, y = a._sprite_placement(unit, t, pose)
            y += a._board_shake(t)
            for yy in range(body.height):
                for xx in range(body.width):
                    if body.getpixel((xx, yy))[3] and 0 <= x + xx < r.W and 0 <= y + yy < r.H:
                        max_body_overlap += int(any(delta.getpixel((x + xx, y + yy))))
        for phase in range(12):
            budget = r.ParticleBudget()
            a._draw_board_fx(Image.new("RGBA", (r.W, r.H)), event[0] + phase * .1, budget, {})
            peak_budget = max(peak_budget, budget.used)
        motions.append({"species": sid, "two_pose_diff_pixels": changed,
                        "floating": gait.floating, "period": gait.period})
    require(max_body_overlap == 0, "VFX covers opaque sprite pixels")
    require(peak_budget <= r.PARTICLE_LIMIT, "real scene particle budget")
    samples["opaque_body_fx_overlap_pixels"] = max_body_overlap
    samples["peak_sampled_fx_particles"] = peak_budget
    samples["gait"] = motions
    return {"samples": samples, "failures": failures, "passed": not failures}


if __name__ == "__main__":
    result = checks()
    out = r.ROOT / "reports/evidence/r1-contracts-2026-10-04.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
