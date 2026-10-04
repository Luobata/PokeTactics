#!/usr/bin/env python3
"""节奏消融与当前参数对照（docs/13 §6）。

A0/A1/A2 的普攻间隔分别为 1.0/1.5/2.0，均固定历史回能 15/10；
M0 只改移动，E0 只改两口回能，历史臂关闭档案/通用技能以隔离全局节奏。
CURRENT_NO_PROFILES 使用当前节奏（2.2、21/10）但同样关档案，供受控对照；
CURRENT 使用当前节奏和源码的档案开关，量实际玩法。两者不能混作同一消融臂。

逐臂输出完整控制参数；切臂无顺序依赖，CLI 结束/异常时恢复进入前状态。
用法：python3 sim/experiment_pacing.py [--games 400] [--pairs 300]
"""

import argparse
import json
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import combat  # noqa: E402
import data  # noqa: E402
import profiles  # noqa: E402
from roster import build_roster, random_comp  # noqa: E402


_HISTORICAL = {"atk_mult": 1.0, "move_tick": data.MOVE_TICK,
               "energy_attack": 15, "energy_hit": 10, "profiles_on": False}
_CURRENT = {"atk_mult": data.ATTACK_INTERVAL_MULT, "move_tick": data.MOVE_TICK,
            "energy_attack": data.ENERGY_PER_ATTACK,
            "energy_hit": data.ENERGY_PER_HIT_TAKEN,
            "profiles_on": profiles.PROFILES_ON}
ARM_CONFIGS = {
    "A0": dict(_HISTORICAL),
    "A1": dict(_HISTORICAL, atk_mult=1.5),
    "A2": dict(_HISTORICAL, atk_mult=2.0),
    "M0": dict(_HISTORICAL, move_tick=data.MOVE_TICK * 1.3),
    "E0": dict(_HISTORICAL, energy_attack=int(15 * 0.85),
               energy_hit=int(10 * 0.85)),
    "CURRENT_NO_PROFILES": dict(_CURRENT, profiles_on=False),
    "CURRENT": dict(_CURRENT),
}


def runtime_snapshot():
    return {"atk_mult": combat.ATTACK_INTERVAL_MULT, "move_tick": combat.MOVE_TICK,
            "energy_attack": combat.ENERGY_PER_ATTACK,
            "energy_hit": combat.ENERGY_PER_HIT_TAKEN,
            "profiles_on": profiles.PROFILES_ON}


def restore_runtime(cfg):
    combat.ATTACK_INTERVAL_MULT = cfg["atk_mult"]
    combat.MOVE_TICK = cfg["move_tick"]
    combat.ENERGY_PER_ATTACK = cfg["energy_attack"]
    combat.ENERGY_PER_HIT_TAKEN = cfg["energy_hit"]
    profiles.PROFILES_ON = cfg["profiles_on"]


def set_arm(arm):
    """显式写入整套臂参数，历史回能不从当前默认或上一臂推导。"""
    restore_runtime(ARM_CONFIGS[arm])


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
    if args.games < 1 or args.pairs < 1:
        ap.error("--games 与 --pairs 必须大于 0")
    print(f"节奏消融：随机 6v6 × {args.games}（种子 {args.seed}）+ 锚点 × {args.pairs}")
    before = runtime_snapshot()
    rows = {}
    try:
        for arm in ARM_CONFIGS:
            set_arm(arm)
            print(f"\n[{arm}] 配置 " + json.dumps(runtime_snapshot(), sort_keys=True))
            m = metrics(args.games, args.seed, args.pairs)
            rows[arm] = m
            fc = f"{m['fc_med']:.1f}s" if m["fc_med"] is not None else "—"
            print(f"  时长中位 {m['med']:.1f}s / p90 {m['p90']:.1f}s / "
                  f"超时率 {m['timeout']:.0%} / 首招 {fc} / "
                  f"怪力vs胡地 {m['mk_anchor']:.0%} / 水vs火 {m['wf_anchor']:.0%}")
    finally:
        restore_runtime(before)
    old, controlled, current = rows["A0"], rows["CURRENT_NO_PROFILES"], rows["CURRENT"]
    print(f"\n判读：相同档案关闭条件下，旧节奏→当前节奏的时长中位 "
          f"{old['med']:.1f}s → {controlled['med']:.1f}s；"
          f"CURRENT（源码档案开关）的实际玩法中位 {current['med']:.1f}s。"
          "14-20s 是中后期候选带，随机 6v6 读数不能代替整局与分阶段验收。")


if __name__ == "__main__":
    main()
