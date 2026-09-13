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
"""

import argparse
import copy
import json
import time
from collections import defaultdict
from itertools import combinations
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

import render_battle_gif as r


LIMITS = {"attack": 600, "land": 1500, "opening": 2500}
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
    t = event[0] + r.HIT_DELAY if kind == "attack" else event[1]
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
        phase = r.effect_frame(t - ev[0] - r.HIT_DELAY)
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
    """直接量测实际 NEAREST/动作压缩后的 alpha 包围盒和最终血条像素。"""
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
        if box[1] < py - 4.5 or sprite.width != (30 if au.u.piece.tier == 3 else 28):
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
        expected = 30 if piece.tier == 3 else 28
        scales.add((source.width, expected, round(expected / source.width, 6)))
        # 最近邻不能混出新颜色；等比缩放的静态画布宽高必须相等。
        colors = {c for _, c in source.getcolors(source.width * source.height) if c[3]}
        if (sprite.size != (expected, expected)
                or any(c[3] and c not in colors
                       for _, c in sprite.getcolors(sprite.width * sprite.height))):
            failures.append({"kind": "nearest_sprite_fit", "species": sid})
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
                      if r.effect_frame(t - ev[0] - r.HIT_DELAY) == 0]
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
    reports = [check_seed(seed, args.output) for seed in (args.seed or [7, 11])]
    if args.output:
        (args.output / "visibility.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2) + "\n")
    raise SystemExit(1 if any(report["failures"] for report in reports) else 0)


if __name__ == "__main__":
    main()
