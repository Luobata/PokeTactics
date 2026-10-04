#!/usr/bin/env python3
"""节奏消融实验（docs/13 §6 v2：全局减速不是美术调速，先消融再组合）。

背景：评审指出「普攻×1.5、移动×1.3、能量−15%」同时改会重排整套
平衡（近战接敌挨打数、首招时间、治疗/DOT 相对收益、控制覆盖率、
平局率），且近战移动倍率 0.60→0.61 有 61%→43% 时序悬崖前科。

四臂消融（随机 6v6 + 两个定向锚点，档案关——量的是全局节奏不是角色）：
- A0 基线（现状）；
- A1 只改攻速：RANGED/普攻出手间隔 ×1.5（SPEED→interval 映射整体放慢；
  通过临时改 SPEED_TO_ATTACK_INTERVAL 的换算实现，臂内还原）；
- A2 只改移动：MOVE_TICK ×1.3；
- A3 只改能量：回能 ×0.85（攻/受击两口同缩）；
- A4 组合（A1+A2+A3）。

读数：时长中位/p90、首次 cast 中位、45s 超时率、怪力vs胡地锚点、
水vs火锚点、齐射后首杀时间。输出给 R2 定参（本文不拍数值）。

用法：python3 sim/experiment_pacing.py [--games 400]
"""

import argparse
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import combat  # noqa: E402
import data  # noqa: E402
import profiles  # noqa: E402
from roster import build_roster, random_comp  # noqa: E402

profiles.PROFILES_ON = False   # 量全局节奏，不量角色


def set_arm(arm):
    """臂内改 combat 命名空间的换算常量（Unit 初始化运行期读取）。
    2026-10-04 更新：攻速 ×1.5 已转正为默认（data.ATTACK_INTERVAL_MULT），
    本实验改为直接切该乘数——A0=旧节奏、A1=现默认、A2=远期 ×2.0；
    移动/能量消融臂固定攻速旧值以保持单一变量。"""
    combat.ATTACK_INTERVAL_MULT = {"A0": 1.0, "A1": 1.5, "A2": 2.0,
                                   "M0": 1.0, "E0": 1.0}[arm]
    combat.MOVE_TICK = _ORIG_MOVE * (1.3 if arm == "M0" else 1.0)
    combat.ENERGY_PER_ATTACK = int(_ORIG_EPA * (0.85 if arm == "E0" else 1.0))
    combat.ENERGY_PER_HIT_TAKEN = int(_ORIG_EPHT * (0.85 if arm == "E0" else 1.0))


_orig_interval = combat.SPEED_TO_ATTACK_INTERVAL
_ORIG_MOVE = combat.MOVE_TICK
_ORIG_EPA = combat.ENERGY_PER_ATTACK
_ORIG_EPHT = combat.ENERGY_PER_HIT_TAKEN


def _slow_interval(speed):
    return _orig_interval(speed) * 1.5


def metrics(games, seed, pair_games):
    rng = random.Random(seed)
    durs, first_casts, timeouts = [], [], 0
    for i in range(games):
        a, b = random_comp(rng, 6), random_comp(rng, 6)
        battle = combat.Battle(a, b, random.Random(seed * 7 + i))
        res = battle.run()
        durs.append(res["duration"])
        if res["winner"] is None:
            timeouts += 1
        fc = [e[0] for e in battle.events if e[1] == "cast"]
        if fc:
            first_casts.append(min(fc))
    roster = build_roster()

    def piece(n):
        return next(p for ps in roster.values() for p in ps if p.name == n)

    def anchor(na, nb):
        pa, pb = piece(na), piece(nb)
        win = sum(1 for i in range(pair_games)
                  if combat.Battle([pa] * 6, [pb] * 6,
                                   random.Random(9000 + i)).run()["winner"] == 0)
        return win / pair_games

    return {
        "med": statistics.median(durs), "p90": sorted(durs)[int(len(durs) * 0.9)],
        "timeout": timeouts / games,
        "fc_med": statistics.median(first_casts) if first_casts else None,
        "mk_anchor": anchor("怪力", "胡地"),
        "wf_anchor": anchor("水箭龟", "喷火龙"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=400)
    ap.add_argument("--pairs", type=int, default=300)
    ap.add_argument("--seed", type=int, default=13)
    args = ap.parse_args()
    print(f"节奏消融：随机 6v6 × {args.games}（种子 {args.seed}）+ 锚点 × {args.pairs}，档案关")
    print(f"{'臂':<6}{'时长中位':>8}{'p90':>7}{'超时率':>7}{'首招中位':>9}"
          f"{'怪力vs胡地':>10}{'水vs火':>8}")
    rows = {}
    for arm in ("A0", "A1", "A2", "M0", "E0"):
        set_arm(arm)
        m = metrics(args.games, args.seed, args.pairs)
        rows[arm] = m
        fc = f"{m['fc_med']:.1f}s" if m["fc_med"] is not None else "—"
        print(f"{arm:<6}{m['med']:>7.1f}s{m['p90']:>6.1f}s{m['timeout']:>7.0%}"
              f"{fc:>9}{m['mk_anchor']:>10.0%}{m['wf_anchor']:>8.0%}")
    set_arm("A0")
    b, a4 = rows["A0"], rows["A1"]
    print(f"\n判读：默认节奏（A1，攻速×1.5 已转正）vs 旧节奏 A0"
          f"（目标带 14-20s 的中后期候选，见 docs/13 §6）；"
          f"怪力vs胡地锚 {b['mk_anchor']:.0%} → {a4['mk_anchor']:.0%}；"
          f"超时率 {b['timeout']:.0%} → {a4['timeout']:.0%}。"
          f"数值组合留给 R2 配平（本文只出消融读数）。")


if __name__ == "__main__":
    main()
