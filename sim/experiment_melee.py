#!/usr/bin/env python3
"""近战/远程均衡对照实验。

背景：远程在近战接近期白嫖输出，叠加水系攻击载体最多、岩地全族被水 4x 针对，
导致 水 vs 隆隆岩 对位在克制实验六臂中全部 100%（与倍率无关）。
本实验比较三种补偿：远程出手惩罚 / 近战突进 / 近战坚韧。

基线统一为等级拍平（S1 定稿，现为 roster 默认）。同种子同阵容序列，跨臂可比。

用法：
    python3 sim/experiment_melee.py [--games 1000] [--seed 9]
"""

import argparse
import random
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import data  # noqa: E402
from combat import Battle  # noqa: E402
from roster import build_roster, random_comp  # noqa: E402

_DEFAULTS = dict(ranged=data.RANGED_INTERVAL_MULT, move=data.MELEE_MOVE_MULT,
                 resist=data.MELEE_RESIST)  # 导入时快照，结束时恢复
ARMS = [
    ("M0 无补偿对照", dict(ranged=1.0, move=1.0, resist=0.0)),
    ("M1 远程出手×1.25", dict(ranged=1.25, move=1.0, resist=0.0)),
    ("M2 近战突进×0.6", dict(ranged=1.0, move=0.6, resist=0.0)),
    # M2c：C-sym 棋盘（6 列）修订值 = 当前 data.MELEE_MOVE_MULT 默认
    # （2026-09-14 平衡 pass：旧板 0.6 在 C-sym 下怪力vs胡地 61% 出带，
    #   0.62 拉回 42.6%；旧臂保留保 2026-09-13 报告可复现）
    ("M2c 突进×0.62(C-sym修订)", dict(ranged=1.0, move=0.62, resist=0.0)),
    ("M3 近战坚韧15%", dict(ranged=1.0, move=1.0, resist=0.15)),
    ("M4 出手+突进", dict(ranged=1.25, move=0.6, resist=0.0)),
    ("M5 全组合", dict(ranged=1.25, move=0.6, resist=0.10)),
]
MIN_SAMPLE = 40
# 对位健康线：物特对照组（怪力vs胡地）40~60%；2x 回归（水vs火）不劣化出
# 55~85%。水vs岩为附读（band=None）：melee 报告 §3 裁定「同种纯克制压力
# 对位允许 ~100%」（物理墙特防纸的结构行为，修法归 S3 摆位解），
# 2026-09-14 平衡 pass 将代码带与已发布裁定同步。
PAIRS = [
    ("水箭龟", "隆隆岩", None, "4x+远程打近战（附读：结构项，允许~100%）"),
    ("怪力", "胡地", (0.40, 0.60), "近战vs远程对照（无克制）"),
    ("水箭龟", "喷火龙", (0.55, 0.85), "2x 回归检查"),
]


def apply_arm(arm: dict) -> None:
    data.RANGED_INTERVAL_MULT = arm["ranged"]
    data.MELEE_MOVE_MULT = arm["move"]
    data.MELEE_RESIST = arm["resist"]


def random_bandwidth(games: int, size: int, seed: int) -> tuple:
    rng = random.Random(seed)
    durs, type_w = [], defaultdict(lambda: [0, 0])
    for _ in range(games):
        comp_a, comp_b = random_comp(rng, size), random_comp(rng, size)
        res = Battle(comp_a, comp_b, rng).run()
        durs.append(res["duration"])
        for side, comp in ((0, comp_a), (1, comp_b)):
            for t in {t for p in comp for t in p.types}:
                type_w[t][0] += 1
                type_w[t][1] += 1 if res["winner"] == side else 0
    rates = {t: w / n for t, (n, w) in type_w.items() if n >= MIN_SAMPLE}
    return max(rates.values()) - min(rates.values()), statistics.median(durs), rates


def pair_winrate(name_a: str, name_b: str, games: int) -> float:
    roster = build_roster()

    def find(name):
        return next(p for ps in roster.values() for p in ps if p.name == name)

    pa, pb = find(name_a), find(name_b)
    win_a = sum(
        1 for i in range(games)
        if Battle([pa] * 6, [pb] * 6, random.Random(9000 + i)).run()["winner"] == 0)
    return win_a / games


import synergy as _syn
_syn.SYNERGIES_ON = False  # 本报告基线建立于羁绊关（2026-09-14 起默认开）
# 2026-09-14 成套翻开后钉关保基线（与 tiering/effectiveness 同款）：齐射
# 对 6 连单色队有克制不对称放大（水箭龟×6 的 WATER 齐射 2x 打火队 →
# 水vs火锚 51%→100%），本实验口径为近远程时序，钉住三系统
import combo as _cb, items as _it, status as _st
_cb.COMBOS_ON = False; _it.ITEMS_ON = False; _st.STATUS_ON = False
import profiles as _pf
_pf.PROFILES_ON = False  # R1 单体档案（2026-09-15）：钉关保基线（胡地建档影响近远锚点）
import combat as _cb
_cb.ATTACK_INTERVAL_MULT = 1.0  # R2 节奏定参（2026-10-04）：钉回旧攻速保基线
_cb.ENERGY_PER_ATTACK = 15  # R2 能量补偿钉回旧值


import combo as _cb, items as _it, status as _st
_cb.COMBOS_ON = False; _it.ITEMS_ON = False; _st.STATUS_ON = False  # 2026-09-14 成套翻开后钉关保基线


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=1000)
    ap.add_argument("--size", type=int, default=6)
    ap.add_argument("--seed", type=int, default=9)
    ap.add_argument("--pairs", type=int, default=200)
    args = ap.parse_args()

    print(f"近战/远程实验：{args.games} 场随机 + 三组对位各 {args.pairs} 场"
          f"（等级拍平基线，seed={args.seed}）")
    for name, arm in ARMS:
        apply_arm(arm)
        bw, med, rates = random_bandwidth(args.games, args.size, args.seed)
        top = max(rates.items(), key=lambda kv: kv[1])
        pairs = [(a, b, pair_winrate(a, b, args.pairs), band)
                 for a, b, band, _ in PAIRS]
        print(f"\n[{name}]  带宽 {bw:.1%}（最高 {top[0]} {top[1]:.0%}）  "
              f"时长中位 {med:.1f}s")
        for (a, b, wr, band), (_, _, _, label) in zip(pairs, PAIRS):
            if band is None:   # 附读锚点：只报读数不判带（结构项裁定）
                print(f"  · {a} vs {b} [{label}]: {wr:.0%}")
                continue
            lo, hi = band
            ok = "✓" if lo <= wr <= hi else "✗"
            print(f"  {ok} {a} vs {b} [{label}]: {wr:.0%}（目标 {lo:.0%}~{hi:.0%}）")

    apply_arm(_DEFAULTS)  # 恢复模块默认（近战突进已是 S1 定稿默认值）
    print("\n判读：M0 的 ✗ 就是待修项；补偿强度以「全部对位进目标区间、带宽最小」为准。"
          "注：水vs岩的 100% 是「特防纸×4x 一击溢出」的结构问题，归 S3 羁绊解决，"
          "见报告。")


if __name__ == "__main__":
    main()


if __name__ == "__main__":
    main()
