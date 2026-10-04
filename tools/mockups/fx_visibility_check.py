#!/usr/bin/env python3
"""逐时刻 RGB diff 验收；默认同时检查 seed 7 / 11，失败退出 1。

    PYTHONDONTWRITEBYTECODE=1 python3 tools/mockups/fx_visibility_check.py
    python3 tools/mockups/fx_visibility_check.py --seed 7 --output /tmp/fx-check

统计 RGB 任一通道变化的像素，原尺寸与 2× 最近邻分别计算。不用差值
强度求和，也不把切镜变化当作棋盘特效通过的证据。逐帧检查底层棋盘，
同时报告最终合成画面的 diff 和切镜遮挡状态。t=0 没有真实前帧，使用
相同部署/姿态、关闭开战演出的静帧作为参考。

另对每次普攻/大招的首帧做隔离自验：冻结单位坐标，仅保留这一事件，
在同一地砖背景上画前一帧与特效帧，排除震屏、伤害数字及其他事件。
阈值直接应用于 240×320 原尺寸，比任务要求的 2× 可见度更严格。
第 4 期增加实际精灵 alpha 包围盒的 board_crowding（≤4px）、状态条
遮挡（≤2 帧），以及全属性变体、力度边界、地痕寿命和物种动作覆盖。
第 5 期新增 palette_purity（含全部压缩相位）与 scale_compare 三联图核对，
在 40px 格和 32/34px 目标盒下继续执行原可见度红线。
第 6 期直调 BattleAnimation(weather_name)，逐帧检查同阵容无天气对照
与同事件流视觉隔离对照（均 ≥1200px），并核对真实 status_shock 图标。
"""

import argparse
import copy
import json
import sys
import time
from collections import defaultdict
from itertools import combinations
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

import render_battle_gif as r

sys.path.insert(0, str(r.ROOT))
from tools.acceptance.server import SCENARIOS  # noqa: E402
import status as status_mod  # noqa: E402
import synergy as synergy_mod  # noqa: E402


LIMITS = {"attack": 600, "land": 1500, "opening": 2500}
WEATHER_LIMIT = 1200
MAX_BOARD_OVERLAP = 4


def diff_pixels(before, after):
    """简单 RGB diff：每个变化像素只计一次。"""
    delta = ImageChops.difference(before.convert("RGB"), after.convert("RGB"))
    red, green, blue = delta.split()
    maximum = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    return maximum.width * maximum.height - maximum.histogram()[0]


def make_animation(seed):
    roster = r.build_roster()
    pieces = {p.name: p for group in roster.values() for p in group}
    return r.BattleAnimation(
        [pieces[n] for n in ("雷丘", "妙蛙花", "隆隆岩", "怪力", "水伊布")],
        [pieces[n] for n in ("暴鲤龙", "喷火龙", "胡地", "大比鸟", "霸王花")],
        seed, r.Front(), r.Palettes(), r.Font16())


def board_frame(anim, t):
    img = Image.new("RGBA", (r.W, r.H), (18, 18, 20, 255))
    anim._draw_board(img, t)
    return img.convert("RGB")


def opening_reference(anim):
    reference = copy.copy(anim)
    reference._draw_board_flash = lambda *_: None
    reference._draw_opening = lambda *_: None
    return board_frame(reference, 0.0)


def isolated_pair(anim, kind, event):
    """独立绘制夹具，只改浅拷贝；真实回放状态与事件列表保持原样。"""
    probe = copy.copy(anim)
    # Freeze geometry without changing the original flight duration.
    probe._attack_delay = anim._attack_delay
    t = event[0] + anim._attack_delay(event) if kind == "attack" else event[1]
    probe.units = {idx: copy.copy(au) for idx, au in anim.units.items()}
    for au in probe.units.values():
        au.from_px = au.to_px = au.render_px(t)
        au.move_t0 = -9.0
        au.die_t = None
    probe.events = [event] if kind == "attack" else []
    probe._cursor = len(probe.events)
    probe.cutins = [event] if kind == "land" else []
    background = Image.new("RGBA", (r.W, r.H), r.NIGHT)
    for row in range(r.BROWS):
        for col in range(r.BCOLS):
            r.draw_floor_tile(background, r.BX + col * r.BCELL, r.BY + row * r.BCELL,
                              r.BCELL, col, row, enemy=row < 3)
    frames = []
    for moment in (t - r.FPS_DT, t):
        img = background.copy()
        fx = Image.new("RGBA", img.size)
        probe._draw_board_fx(fx, moment, r.ParticleBudget(), {})
        img.alpha_composite(fx)
        if kind == "land":
            probe._draw_board_flash(img, moment)
        frames.append(img.convert("RGB"))
    return frames


def frame_cues(anim, t):
    cues, required = [], set()
    if 0 <= r.effect_frame(t) < 4:
        cues.append(f"opening:{r.effect_frame(t)}")
        required.add("opening")
    for ev in anim._recent_hits(t):
        phase = r.effect_frame(t - ev[0] - anim._attack_delay(ev))
        cues.append(f"attack:{ev[2]}>{ev[3]}:{phase}")
        required.add("attack")
    for c in anim.cutins:
        phase = r.effect_frame(t - c[1])
        if 0 <= phase < 6:
            cues.append(f"land:{c[2]}>{c[3]}:{phase}")
            required.add("land")
    for idx, au in anim.units.items():
        if au.die_t is not None and 0 <= r.effect_frame(t - au.die_t) < 4:
            cues.append(f"death:{idx}:{r.effect_frame(t - au.die_t)}")
        if anim._casting_phase(au, t):
            cues.append(f"charge:{idx}")
        if au.visible(t) and not au.dying(t) and au.energy >= 80:
            cues.append(f"full:{idx}")
    if anim._board_shake(t):
        cues.append(f"shake:{anim._board_shake(t):+}")
    if any(0 <= t - item[0] < r.FLOAT_LIFE for item in anim.floats):
        cues.append("damage-number")
    return cues, required


def save_pair(output, name, before, after):
    if output is None:
        return
    output.mkdir(parents=True, exist_ok=True)
    before.save(output / f"{name}-before.png")
    after.save(output / f"{name}-fx.png")
    delta = ImageChops.difference(before, after)
    delta.save(output / f"{name}-diff.png")


def unit_layer_checks(anim, t, board):
    """直接量测实际 BOX+量化/动作压缩后的 alpha 包围盒和最终血条像素。"""
    shown, failures = [], []
    checked_meters, obscured_meters = 0, 0
    for idx, au in anim.units.items():
        pose = anim._unit_pose(au, t) if au.visible(t) else None
        if pose is None:
            continue
        sprite, x, y = anim._sprite_placement(au, t, pose)
        left, top, right, bottom = sprite.getbbox()
        box = (x + left, y + top, x + right, y + bottom)
        px, py = au.render_px(t)
        shown.append((idx, round((py - r.BY) / r.BCELL), px, box))
        # 插值原点可含小数，最终图像取整容差为 0.5px。
        if box[1] < py - 4.5 or sprite.width != (34 if au.u.piece.tier == 3 else 32):
            failures.append({"kind": "board_fit", "t": round(t, 4), "unit": idx,
                             "bbox": box, "cell_y": py})
        expected = Image.new("RGBA", (r.W, r.H))
        anim._draw_unit_meters(expected, au, t, pose)
        shake = anim._board_shake(t)
        mask_box = expected.getbbox()
        clipped = False
        for yy in range(mask_box[1], mask_box[3]):
            for xx in range(mask_box[0], mask_box[2]):
                if expected.getpixel((xx, yy))[3] and r.BY <= yy + shake < r.BY + r.BROWS * r.BCELL:
                    if board.getpixel((xx, yy + shake)) != expected.getpixel((xx, yy))[:3]:
                        clipped = True
        checked_meters += 1
        obscured_meters += int(clipped)
    maximum, pairs = 0, 0
    for a, b in combinations(shown, 2):
        # 同视觉排的横向邻居；同列前后排的深度遮挡仍按原排序保留。
        if a[1] != b[1] or abs(a[2] - b[2]) < 1:
            continue
        pairs += 1
        overlap = max(0, min(a[3][2], b[3][2]) - max(a[3][0], b[3][0]))
        maximum = max(maximum, overlap)
        if overlap > MAX_BOARD_OVERLAP:
            failures.append({"kind": "board_crowding", "t": round(t, 4),
                             "units": [a[0], b[0]], "overlap_px": overlap,
                             "limit_px": MAX_BOARD_OVERLAP})
    return maximum, pairs, checked_meters, obscured_meters, failures


def style_contract_checks(anim, output):
    """补齐真实阵容未覆盖的属性/轻击，逐相位比对两种轮廓。"""
    probe = copy.copy(anim)
    probe.units = {i: copy.deepcopy(anim.units[i]) for i in (0, 1)}
    for i, au in probe.units.items():
        au.reset()
        au.from_px = au.to_px = (r.BX + (1 + i * 2) * r.BCELL, r.BY + 2 * r.BCELL)
        au.u.max_hp = 100
        au.u.range = 1
    probe.units[3] = probe.units[0]  # 奇数 idx，同一施法者位置/材质，隔离变体差异。
    failures, coverage = [], []
    atlas = Image.new("RGB", (r.W * 2, r.H * len(r.FX_VARIANTS)), r.NIGHT)
    for row, mtype in enumerate(r.FX_VARIANTS):
        probe.units[0].u.piece.types = (mtype,)
        samples = []
        for variant in (0, 1):
            source = 0 if variant == 0 else 3
            probe.events, probe._cursor = [], 0
            probe.cutins = [(1., 2., source, 1, "fixture", 2, 15, mtype)]
            phases = []
            for phase in range(6):
                layer = Image.new("RGBA", (r.W, r.H))
                probe._draw_board_fx(layer, 2 + phase * r.FPS_DT, r.ParticleBudget(0), {})
                phases.append(layer)
            samples.append(phases)
            cell = Image.new("RGBA", (r.W, r.H), r.NIGHT)
            cell.alpha_composite(phases[0])
            ImageDraw.Draw(cell).text((8, 12), f"{mtype} / {variant + 1}", fill=r.PAPER)
            atlas.paste(cell.convert("RGB"), (variant * r.W, row * r.H))
        diffs = [diff_pixels(a, b) for a, b in zip(*samples)]
        coverage.append({"type": mtype, "variant_phase_diffs": diffs})
        if min(diffs) == 0:
            failures.append({"kind": "type_variants", "type": mtype, "diffs": diffs})
    # 三档两变体均须满足原普攻可见度；包括最容易被压小的轻击。
    attacks = []
    probe.cutins = []
    probe.units[0].u.piece.types = ("NORMAL",)
    for damage, expected_tier in ((5, 0), (6, 1), (14, 1), (15, 2)):
        if r.impact_tier(damage, 100) != expected_tier:
            failures.append({"kind": "damage_boundary", "damage": damage})
        for variant in (0, 1):
            source = 0 if variant == 0 else 3
            probe.events, probe._cursor = [(1.9, "attack", source, 1, damage)], 1
            before, after = isolated_pair(probe, "attack", probe.events[0])
            count = diff_pixels(before, after)
            attacks.append({"damage_percent": damage, "variant": variant, "diff_1x": count})
            if count < LIMITS["attack"]:
                failures.append({"kind": "damage_style_visibility", **attacks[-1]})
    # 八帧地痕驻留同一落点，目标后续移动也不能拖着印记走。
    probe.units = {0: probe.units[0], 1: probe.units[1]}
    probe.events = [(0., "deploy", 1, (2, 1)), (1.9, "attack", 0, 1, 15),
                    (2.2, "move", 1, (3, 1))]
    probe._cursor = len(probe.events)
    scars = [list(probe._ground_scars(2 + i * r.FPS_DT)) for i in range(9)]
    if (any(len(s) != 1 for s in scars[:8]) or scars[8]
            or len({s[0][:2] for s in scars[:8] if s}) != 1
            or not all(a[0][3] > b[0][3] for a, b in zip(scars[:7], scars[1:8]) if a and b)):
        failures.append({"kind": "ground_scars", "frames": scars})
    probe.events.insert(2, (2.1, "end", 0))
    probe._cursor += 1
    if list(probe._ground_scars(2.7)):
        failures.append({"kind": "scar_settlement_fade"})
    if output:
        output.mkdir(parents=True, exist_ok=True)
        atlas.save(output / "type-variants.png")
    return {"type_count": len(coverage), "variants_per_type": 2,
            "coverage": coverage, "damage_styles": attacks, "scar_frames": 8,
            "failures": failures}


def motion_contract_checks(anim):
    failures, scales, buckets = [], set(), [set() for _ in range(4)]
    representatives = {}
    roster = [p for group in r.build_roster().values() for p in group]
    for piece in roster:
        sid = piece.species_id
        profile = anim._motion_profile(sid)
        for dest, value in zip(buckets, (*profile[:3], profile[5])):
            dest.add(value)
        representatives.setdefault(profile[1], piece)
        source = anim.front.image(sid, anim.pal)
        sprite = anim._board_sprite(sid, piece.tier)
        expected = 34 if piece.tier == 3 else 32
        scales.add((source.width, expected, round(expected / source.width, 6)))
        # 颜色归入独立 palette_purity；静态目标盒保持等比。
        if sprite.size != (expected, expected):
            failures.append({"kind": "sprite_fit", "species": sid})
    attack_signatures, idle_signatures, hit_responses = {}, {}, {}
    for piece in roster:
        profile = anim._motion_profile(piece.species_id)
        au = copy.deepcopy(anim.units[0])
        au.u.piece = piece
        au.init_px = (r.BX + 2 * r.BCELL, r.BY + 2 * r.BCELL)
        au.reset()
        idle_signatures.setdefault(profile[0], tuple(
            (*anim._unit_pose(au, 2 + i * 0.1)[:2], anim._sprite_squash(au, 2 + i * 0.1))
            for i in range(40)))
        # 只有 jitter 的对照夹具：硬汉不得颤动，敏感型必须出现可见偏移。
        still = anim._unit_pose(au, 2.)
        au.jitter_t = 2.
        reacted = anim._unit_pose(au, 2.)
        hit_responses.setdefault(profile[2], reacted != still)
    for style, piece in representatives.items():
        au = copy.deepcopy(anim.units[0])
        au.reset()
        au.u.piece = piece
        au.attacks = [(2., 1., 0.)]
        attack_signatures[style] = tuple(anim._attack_motion(au, 2 + i * 0.04) for i in range(10))
    if ([len(b) for b in buckets] != [3, 3, 2, 3]
            or len(set(attack_signatures.values())) != 3
            or len(set(idle_signatures.values())) != 3
            or hit_responses != {0: False, 1: True}):
        failures.append({"kind": "motion_buckets", "bucket_counts": [len(b) for b in buckets],
                         "hit_responses": hit_responses})
    return {"species_checked": len({p.species_id for p in roster}),
            "idle_types": len(buckets[0]), "attack_types": len(buckets[1]),
            "hit_types": len(buckets[2]), "walk_rates": sorted(buckets[3]),
            "scales": sorted(scales), "failures": failures}


def palette_purity_checks(anim):
    """按 pal.for_species 的四原色验收真实缓存缩图，含 0–6px 动作压缩。"""
    failures, checked, visible, off_palette, partial_alpha = [], 0, 0, 0, 0
    roster = [p for group in r.build_roster().values() for p in group]
    for piece in roster:
        allowed = {tuple(c) for c in anim.pal.for_species(piece.species_id)}
        for squash in range(7):
            sprite = anim._board_sprite(piece.species_id, piece.tier, squash)
            pixels = sprite.getcolors(sprite.width * sprite.height)
            invalid = sum(n for n, c in pixels if c[3] and c[:3] not in allowed)
            partial = sum(n for n, c in pixels if c[3] not in (0, 255))
            nonempty = sum(n for n, c in pixels if c[3])
            checked += 1
            visible += nonempty
            off_palette += invalid
            partial_alpha += partial
            expected = 34 if piece.tier == 3 else 32
            if (invalid or partial or not nonempty
                    or sprite.size != (expected, expected - squash)):
                failures.append({"kind": "palette_purity", "species": piece.species_id,
                                 "squash": squash, "off_palette_pixels": invalid,
                                 "partial_alpha_pixels": partial, "visible_pixels": nonempty,
                                 "size": sprite.size})
    # 防止验收样本失去敏感性：该 56→34 BOX 原图确实会产生调色板外颜色。
    mixed = anim.front.image(6, anim.pal).resize((34, 34), Image.Resampling.BOX)
    allowed = set(anim.pal.for_species(6))
    unquantized = sum(n for n, c in mixed.getcolors(34 * 34) if c[3] and c[:3] not in allowed)
    if not unquantized:
        failures.append({"kind": "palette_purity_fixture", "reason": "BOX has no mixed colors"})
    return {"species_checked": len({p.species_id for p in roster}), "sprites_checked": checked,
            "squash_phases": 7, "visible_pixels": visible, "off_palette_pixels": off_palette,
            "partial_alpha_pixels": partial_alpha, "unquantized_box_off_palette_pixels": unquantized,
            "failures": failures}


def scale_compare_checks(anim):
    """核对已交付 PNG 的三种 1×/4× 呈现，不把展示图误做等宽拉伸。"""
    path = r.ROOT / "docs/design/mockups/scale_compare.png"
    failures, samples = [], []
    if not path.is_file():
        return {"failures": [{"kind": "scale_compare", "reason": "missing PNG"}]}
    with Image.open(path) as opened:
        image = opened.convert("RGB")
    expected = r.scale_compare_image(anim.front, anim.pal, anim.font)
    if image.size != expected.size or diff_pixels(image, expected):
        failures.append({"kind": "scale_compare", "reason": "stale or incorrect PNG"})
    source = anim.front.image(6, anim.pal)
    for i, sprite in enumerate((source.resize((28, 28), Image.Resampling.NEAREST),
                                anim._board_sprite(6, 3), source)):
        for zoom, baseline in ((1, 140), (4, 424)):
            enlarged = sprite.resize((sprite.width * zoom, sprite.height * zoom), Image.Resampling.NEAREST)
            tile = Image.new("RGBA", enlarged.size, r.PAPER + (255,))
            tile.alpha_composite(enlarged)
            x = 12 + i * 244 + (232 - enlarged.width) // 2
            region = image.crop((x, baseline - enlarged.height, x + enlarged.width, baseline))
            count = diff_pixels(region, tile)
            samples.append({"size_px": sprite.width, "zoom": zoom, "diff_pixels": count})
            if count:
                failures.append({"kind": "scale_compare", **samples[-1]})
    return {"species": 6, "source_px": source.width, "samples": samples, "failures": failures}


def scenario_animation(seed, name, assets, weather_name=None):
    """共享线上场景阵容，开关只在构造期间启用，绝不修改 sim 文件。"""
    sc = SCENARIOS[name]
    pieces = {p.name: p for group in r.build_roster().values() for p in group}
    previous, previous_synergy = status_mod.STATUS_ON, synergy_mod.SYNERGIES_ON
    try:
        status_mod.STATUS_ON = bool(sc.get("status"))
        synergy_mod.SYNERGIES_ON = False  # /anim 的默认 synergy=False。
        return r.BattleAnimation([pieces[n] for n in sc["a"]], [pieces[n] for n in sc["b"]],
                                 seed, assets.front, assets.pal, assets.font,
                                 weather_name=weather_name)
    finally:
        status_mod.STATUS_ON = previous
        synergy_mod.SYNERGIES_ON = previous_synergy


def weather_checks(seed, assets, output):
    failures, rows = [], []
    rect = (r.BX, r.BY, r.BX + r.BCOLS * r.BCELL, r.BY + r.BROWS * r.BCELL)
    for weather in r.WEATHER_PALETTES:
        scenario = f"weather_{weather}" if weather != "hail" else "weather_rain"
        anim = scenario_animation(seed, scenario, assets, weather)
        clear = scenario_animation(seed, scenario, assets)
        samples, visual_samples = [], []
        maximum_overlap, meter_streak, max_streak, meter_checks = 0, 0, 0, 0
        t, end = 0.0, max(e[0] for e in anim.events) + 1.2
        while t <= end:
            anim._ensure(t)
            clear._ensure(t)
            board = board_frame(anim, t)
            # 同 seed 同阵容无天气；另外只关闭渲染天气，排除数值臂造成的 diff。
            reference = board_frame(clear, t)
            visual_clear = copy.copy(anim)
            visual_clear.weather_name = None
            isolated = board_frame(visual_clear, t)
            count = diff_pixels(reference.crop(rect), board.crop(rect))
            visual_count = diff_pixels(isolated.crop(rect), board.crop(rect))
            samples.append(count)
            visual_samples.append(visual_count)
            if min(count, visual_count) < WEATHER_LIMIT:
                failures.append({"kind": "weather", "weather": weather, "t": round(t, 4),
                                 "diff_1x": count, "visual_only_diff_1x": visual_count})
            overlap, _, meters, obscured, layer_failures = unit_layer_checks(anim, t, board)
            maximum_overlap = max(maximum_overlap, overlap)
            meter_checks += meters
            meter_streak = meter_streak + 1 if obscured else 0
            max_streak = max(max_streak, meter_streak)
            failures.extend(layer_failures)
            particles = r.weather_particles(weather, t)
            if len(particles) != 8 or any(not (r.BX <= x <= rect[2] - w and
                                            r.BY <= y <= rect[3] - h)
                                         for x, y, w, h, _ in particles):
                failures.append({"kind": "weather_particles", "weather": weather, "t": t})
            if r.effect_frame(t) == 10:
                save_pair(output, f"seed-{seed}-weather-{weather}", isolated, board)
            t += r.FPS_DT
        # 每格只能出现其原有颜色的天气替代色，不接受整图滤镜或软边。
        before, after = r.board_floor(None), r.board_floor(weather)
        replacements = dict(zip(r.FLOOR_COLORS, r.WEATHER_PALETTES[weather]))
        off_palette = 0
        for cy in range(r.BROWS):
            for cx in range(r.BCOLS):
                tile = (cx * r.BCELL, cy * r.BCELL, (cx + 1) * r.BCELL, (cy + 1) * r.BCELL)
                allowed = {replacements.get(c[:3], c[:3]) + (255,)
                           for _, c in before.crop(tile).getcolors(r.BCELL ** 2)}
                off_palette += sum(n for n, c in after.crop(tile).getcolors(r.BCELL ** 2)
                                   if c not in allowed)
        if off_palette or max_streak > 2:
            failures.append({"kind": "weather_layers", "weather": weather,
                             "off_palette_pixels": off_palette, "meter_occlusion": max_streak})
        for char in r.WEATHER_MESSAGES[weather]:
            glyph = Image.new("RGBA", (16, 16))
            r.draw_weather_text(glyph, (0, 0), char, anim.font)
            if not glyph.getbbox():
                failures.append({"kind": "weather_message_missing_glyph", "char": char})
        rows.append({"weather": weather, "frames": len(samples), "min_1x": min(samples),
                     "visual_only_min_1x": min(visual_samples), "threshold_1x": WEATHER_LIMIT,
                     "off_palette_pixels": off_palette, "particles_per_frame": 8,
                     "max_overlap_px": maximum_overlap, "meter_checks": meter_checks,
                     "max_meter_occlusion_frames": max_streak})
    return {"samples": rows, "failures": failures}


def status_checks(seed, assets, output):
    anim = scenario_animation(seed, "status_shock", assets)
    failures, samples = [], []
    applies = [ev for ev in anim.events if ev[1] == "status" and ev[4] == "apply"]
    if not applies:
        failures.append({"kind": "status_fixture", "reason": "no status apply events"})
    t, end, checked = 0.0, max(e[0] for e in anim.events) + 1.2, 0
    meter_streak, max_streak, max_overlap = 0, 0, 0
    while t <= end:
        display = anim.frame(t).convert("RGB")
        board = board_frame(anim, t)
        overlap, _, _, obscured, layer_failures = unit_layer_checks(anim, t, board)
        max_overlap = max(max_overlap, overlap)
        meter_streak = meter_streak + 1 if obscured else 0
        max_streak = max(max_streak, meter_streak)
        failures.extend(layer_failures)
        for idx, au in anim.units.items():
            kinds = anim._active_statuses(au, t)[:3]
            if not kinds or au.dying(t):
                continue
            layer = Image.new("RGBA", (r.W, r.H))
            anim._draw_status_band(layer, au, t)
            bounds = layer.getbbox()
            if bounds is None or bounds[3] - bounds[1] != 6 or bounds[2] - bounds[0] > 20:
                failures.append({"kind": "status_band", "t": t, "unit": idx, "bounds": bounds})
                continue
            checked += 1
            meters = Image.new("RGBA", (r.W, r.H))
            anim._draw_unit_meters(meters, au, t, anim._unit_pose(au, t))
            shake, visible, colored = anim._board_shake(t), 0, 0
            for y in range(bounds[1], bounds[3]):
                for x in range(bounds[0], bounds[2]):
                    pixel = layer.getpixel((x, y))
                    if pixel[3] and meters.getpixel((x, y))[3]:
                        failures.append({"kind": "status_meter_overlap", "t": t, "unit": idx})
                    if pixel[3] and pixel[:3] != r.INK:
                        colored += 1
                        visible += int(board.getpixel((x, y + shake)) == pixel[:3])
            if not colored or visible != colored:
                failures.append({"kind": "status_visibility", "t": t, "unit": idx,
                                 "expected": colored, "visible": visible})
            covered = any(c[0] <= t < c[1] for c in anim.cutins)
            if not covered and (not samples or t - samples[-1]["t"] >= 0.5):
                row = {"t": round(t, 4), "unit": idx, "kinds": kinds,
                       "icon_pixels": visible, "bounds": bounds}
                samples.append(row)
                if output:
                    display.save(output / f"seed-{seed}-status-{t:.1f}-unit-{idx}.png")
        t += r.FPS_DT
    if not checked or max_streak > 2:
        failures.append({"kind": "status_coverage", "checked": checked, "meter_occlusion": max_streak})
    return {"apply_events": len(applies), "checked_unit_frames": checked, "samples": samples,
            "max_overlap_px": max_overlap, "max_meter_occlusion_frames": max_streak,
            "failures": failures}


def status_contract_checks(assets):
    """补齐真实电队不覆盖的状态：只向独立回放夹具注入公开事件。"""
    anim = copy.copy(assets)
    anim.units = {i: copy.deepcopy(assets.units[i]) for i in range(6)}
    kinds = ("burn", "poison", "para", "freeze", "sleep", "flinch")
    anim.events = [(0., "deploy", i, (i % 3 * 2, i // 3 * 2)) for i in range(6)]
    anim.events += [(1., "status", i, kind, "apply", 0) for i, kind in enumerate(kinds)]
    anim.events += [(1.2, "status", 0, "burn", "tick", 3),
                    (1.2, "status", 1, "poison", "tick", 4),
                    (1.4, "status", 3, "freeze", "apply", 0)]
    anim.events += [(2., "status", i, kind, "expire", 0) for i, kind in enumerate(kinds)]
    anim._reset()
    failures, checked = [], []
    before = anim.frame(0.9)
    applied = anim.frame(1.)
    for i, kind in enumerate(kinds):
        canonical = "paralysis" if kind == "para" else kind
        if anim._active_statuses(anim.units[i], 1.) != [canonical]:
            failures.append({"kind": "status_apply", "status": kind})
        checked.append(canonical)
    # 冻结后的位置、压缩、四颜色与完整身体像素均保持不变（含刷新）。
    frozen_frames = []
    for t in (1., 1.1, 1.5, 1.9):
        anim._ensure(t)
        au = anim.units[3]
        layer = Image.new("RGBA", (r.W, r.H))
        anim._draw_unit(layer, au, t, anim._unit_pose(au, t), r.ParticleBudget())
        frozen_frames.append(layer)
    if any(diff_pixels(frozen_frames[0], frame) for frame in frozen_frames[1:]):
        failures.append({"kind": "freeze_motion"})
    for i, damage in ((0, 3), (1, 4)):
        if anim.units[i].hp != anim.units[i].u.max_hp - damage:
            failures.append({"kind": "status_dot_hp", "unit": i})
    if anim._active_statuses(anim.units[5], 1.9):
        failures.append({"kind": "flinch_lifetime"})
    # DOT 与普攻使用同一个避让器，同时发生也保持 scale=1 和独立位置。
    calls = []
    anim._draw_damage_number = lambda img, xy, text, color, scale, **kwargs: calls.append((xy, color, scale))
    anim._ensure(1.2)
    anim.floats.append((1.2, *anim.units[0].render_px(1.2), "-12", (255, 255, 255)))
    anim._draw_floats(Image.new("RGBA", (r.W, r.H)), 1.2)
    dot_calls = [call for call in calls if call[1] in r.DOT_COLORS.values()]
    if len(dot_calls) != 2 or any(call[2] != 1 for call in dot_calls) or len({c[0] for c in calls}) != 3:
        failures.append({"kind": "status_dot_numbers", "calls": calls})
    del anim._draw_damage_number
    # 各身体状态仍只有四种替代色，alpha 保留二值；天气不改精灵色板。
    for status in ("poison", "freeze"):
        for squash in range(7):
            sprite = anim._status_sprite(6, 3, squash, status)
            pixels = sprite.getcolors(sprite.width * sprite.height)
            if len({c[:3] for _, c in pixels if c[3]}) > 4 or any(c[3] not in (0, 255) for _, c in pixels):
                failures.append({"kind": "status_palette", "status": status, "squash": squash})
    anim._ensure(2.)
    if any(au.statuses for au in anim.units.values()):
        failures.append({"kind": "status_expire"})
    if diff_pixels(before, anim.frame(0.9)) or diff_pixels(applied, anim.frame(1.)):
        failures.append({"kind": "status_rewind"})
    # 1 减益 + 2 增益只占 20×6px；死亡无须 expire 即清除图标。
    for kind in r.BUFF_KINDS:
        anim._apply((1., "status", 0, kind, "apply", 0))
    layer = Image.new("RGBA", (r.W, r.H))
    anim._draw_status_band(layer, anim.units[0], 1.)
    left, top, right, bottom = layer.getbbox()
    if (right - left, bottom - top) != (20, 6):
        failures.append({"kind": "status_band_cap"})
    anim._apply((1.1, "die", 0))
    if anim.units[0].statuses:
        failures.append({"kind": "status_death_cleanup"})
    return {"kinds": checked, "frozen_frames": len(frozen_frames),
            "dot_numbers": len(dot_calls), "palette_variants": 14, "failures": failures}


def check_seed(seed, output=None):
    start = time.perf_counter()
    anim = make_animation(seed)
    t_end = max(e[0] for e in anim.events)
    anim._ensure(0.0)
    previous = opening_reference(anim)
    previous_display = previous
    rows, isolated, failures = [], [], []
    measured = defaultdict(list)
    checked = set()
    crowding_max, crowding_pairs, meter_checks = 0, 0, 0
    meter_streak, max_meter_streak = 0, 0
    obscured_frames = 0
    rect = (r.BX, r.BY, r.BX + r.BCOLS * r.BCELL, r.BY + r.BROWS * r.BCELL)
    t = 0.0
    # 与生产入口使用完全相同的浮点累加顺序，不调整事件时间或切镜调度。
    while t <= t_end + 1.2:  # 与生产渲染窗一致（csym 报告遗留注记的一行修复）
        display = anim.frame(t).convert("RGB")
        board = board_frame(anim, t)
        overlap, pairs, meters, obscured, layer_failures = unit_layer_checks(anim, t, board)
        crowding_max, crowding_pairs = max(crowding_max, overlap), crowding_pairs + pairs
        meter_checks += meters
        meter_streak = meter_streak + 1 if obscured else 0
        max_meter_streak = max(max_meter_streak, meter_streak)
        obscured_frames += int(bool(obscured))
        failures.extend(layer_failures)
        cues, required = frame_cues(anim, t)
        if cues:
            count = diff_pixels(previous.crop(rect), board.crop(rect))
            board_size_2x = (r.BCOLS * r.BCELL * 2, r.BROWS * r.BCELL * 2)
            big_count = diff_pixels(previous.crop(rect).resize(board_size_2x, Image.Resampling.NEAREST),
                                    board.crop(rect).resize(board_size_2x, Image.Resampling.NEAREST))
            covered = any(c[0] <= t < c[1] and 0.02 < (t - c[0]) / r.CUTIN_LEN < 0.98
                          for c in anim.cutins)
            limit = max((LIMITS[k] for k in required), default=0)
            passed = count >= limit
            row = {"t": round(t, 4), "cues": cues, "board_diff_1x": count,
                   "board_diff_2x": big_count, "display_diff_1x": diff_pixels(previous_display, display),
                   "cutin_covered": covered, "threshold_1x": limit, "passed": passed}
            rows.append(row)
            for kind in required:
                measured[kind].append(count)
            if not passed:
                failures.append(row)
            print(f"seed={seed} t={t:4.1f} board1x={count:5d} board2x={big_count:6d} "
                  f"display1x={row['display_diff_1x']:5d} {'PASS' if passed else 'FAIL'} "
                  f"{'[cutin-covered] ' if covered else ''}{','.join(cues)}")

        candidates = [("attack", ev) for ev in anim._recent_hits(t)
                      if r.effect_frame(t - ev[0] - anim._attack_delay(ev)) == 0]
        candidates += [("land", c) for c in anim.cutins
                       if 0 <= t - c[1] < r.FPS_DT + 1e-9]
        if t == 0:
            before, after = previous, board
            isolated.append({"kind": "opening", "t": 0, "diff_1x": diff_pixels(before, after)})
            save_pair(output, f"seed-{seed}-opening", before, after)
        for kind, event in candidates:
            key = kind, event
            if key in checked:
                continue
            checked.add(key)
            before, after = isolated_pair(anim, kind, event)
            count = diff_pixels(before, after)
            entry = {"kind": kind, "t": round(t, 4), "diff_1x": count,
                     "diff_2x": diff_pixels(before.resize((r.W * 2, r.H * 2), Image.Resampling.NEAREST),
                                            after.resize((r.W * 2, r.H * 2), Image.Resampling.NEAREST)),
                     "source": event[2], "target": event[3]}
            isolated.append(entry)
            print(f"  isolated {kind} {event[2]}>{event[3]}: {count}px / {entry['diff_2x']}px (1x / 2x)")
            save_pair(output, f"seed-{seed}-{kind}-{t:.1f}-{event[2]}-{event[3]}", before, after)
        previous, previous_display = board, display
        t += r.FPS_DT

    for event in anim.events:
        if event[1] != "attack" or event[4] <= 0 or ("attack", event) in checked:
            continue
        before, after = isolated_pair(anim, "attack", event)
        count = diff_pixels(before, after)
        isolated.append({"kind": "attack", "t": event[0], "diff_1x": count,
                         "source": event[2], "target": event[3],
                         "death_cancelled": anim._projectile_cancelled(event)})
        save_pair(output, f"seed-{seed}-isolated-attack-{event[0]:.1f}-{event[2]}-{event[3]}", before, after)
    for row in isolated:
        if row["diff_1x"] < LIMITS[row["kind"]]:
            failures.append(row)
    t_end = max(e[0] for e in anim.events)
    expected_hits = sum(e[1] == "attack" and e[4] > 0 for e in anim.events)
    expected_lands = sum(c[1] <= t_end + 1.2 for c in anim.cutins)
    # 期望边界=采样窗本身（检查器直调 anim.frame，无横幅替换）
    for kind, expected in (("attack", expected_hits), ("land", expected_lands), ("opening", 1)):
        actual = sum(row["kind"] == kind for row in isolated)
        if not actual or actual != expected:
            failures.append({"kind": kind, "expected": expected, "checked": actual})
    summary = {kind: {"frames": len(values), "min_1x": min(values), "max_1x": max(values),
                      "isolated_min_1x": min(row["diff_1x"] for row in isolated if row["kind"] == kind)}
               for kind, values in measured.items()}
    if not crowding_pairs:
        failures.append({"kind": "board_crowding", "reason": "no pairs checked"})
    if max_meter_streak > 2:
        failures.append({"kind": "meter_occlusion", "max_consecutive_frames": max_meter_streak})
    summary["board_crowding"] = {"max_overlap_px": crowding_max, "limit_px": MAX_BOARD_OVERLAP,
                                 "checked_pairs": crowding_pairs}
    summary["meter_occlusion"] = {"checked_units": meter_checks, "obscured_frames": obscured_frames,
                                  "max_consecutive_frames": max_meter_streak, "limit_frames": 2}
    styles = style_contract_checks(anim, output)
    failures.extend(styles["failures"])
    motions = motion_contract_checks(anim)
    failures.extend(motions["failures"])
    purity = palette_purity_checks(anim)
    failures.extend(purity["failures"])
    comparison = scale_compare_checks(anim)
    failures.extend(comparison["failures"])
    summary["palette_purity"] = {k: v for k, v in purity.items() if k != "failures"}
    summary["scale_compare"] = {k: v for k, v in comparison.items() if k != "failures"}
    weather = weather_checks(seed, anim, output)
    statuses = status_checks(seed, anim, output)
    status_contracts = status_contract_checks(anim)
    failures.extend(weather["failures"])
    failures.extend(statuses["failures"])
    failures.extend(status_contracts["failures"])
    summary["weather"] = {k: v for k, v in weather.items() if k != "failures"}
    summary["status"] = {k: v for k, v in statuses.items() if k != "failures"}
    summary["status_contracts"] = {k: v for k, v in status_contracts.items() if k != "failures"}
    report = {"seed": seed, "summary": summary, "frames": rows, "isolated": isolated,
              "styles": styles, "motions": motions,
              "failures": failures, "elapsed_seconds": round(time.perf_counter() - start, 3)}
    print(f"SUMMARY seed={seed}: {json.dumps(summary, ensure_ascii=False)}")
    print(f"{'FAIL' if failures else 'PASS'} seed={seed}: {len(failures)} failures, "
          f"{report['elapsed_seconds']:.3f}s")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, action="append", help="可重复；默认 7 和 11")
    parser.add_argument("--output", type=Path, help="可选：保存 PNG 前后帧、diff 和 JSON 报告")
    args = parser.parse_args()
    from r1_contract_check import checks as r1_checks
    contracts = r1_checks()
    print("R1 CONTRACTS " + json.dumps(contracts, ensure_ascii=False))
    reports = [check_seed(seed, args.output) for seed in (args.seed or [7, 11])]
    for report in reports:
        report["r1_contracts"] = contracts
        report["failures"].extend(contracts["failures"])
    if args.output:
        (args.output / "visibility.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2) + "\n")
    raise SystemExit(1 if any(report["failures"] for report in reports) else 0)


if __name__ == "__main__":
    main()
