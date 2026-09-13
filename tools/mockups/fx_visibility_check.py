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
"""

import argparse
import copy
import json
import time
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageChops

import render_battle_gif as r


LIMITS = {"attack": 600, "land": 1500, "opening": 2500}


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
    rect = (r.BX, r.BY, r.BX + r.BCOLS * r.BCELL, r.BY + r.BROWS * r.BCELL)
    t = 0.0
    # 与生产入口使用完全相同的浮点累加顺序，不调整事件时间或切镜调度。
    while t <= t_end + 1.2:  # 与生产渲染窗一致（csym 报告遗留注记的一行修复）
        display = anim.frame(t).convert("RGB")
        board = board_frame(anim, t)
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
    banner_from = t_end + 0.6  # 结算横幅帧会替换棋盘渲染，窗口内大招不计入期望
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
    report = {"seed": seed, "summary": summary, "frames": rows, "isolated": isolated,
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
