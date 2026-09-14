#!/usr/bin/env python3
"""克制作用范围 × 倍率压缩 对照实验。

回答：克制上普攻/只上大招、原始/压缩倍率，对属性胜率极化和克制对位的影响。
规则经 data.EFF_ON_BASIC / data.EFF_COMPRESS 注入（combat.py 结算时读取），
同一种子在四种规则下生成完全相同的阵容序列，保证可比。

用法：
    python3 sim/experiment_effectiveness.py [--games 1000] [--seed 3]
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

COMPRESS = {0: 0, 0.25: 0.55, 0.5: 0.7, 1: 1, 2: 1.6, 4: 2.5}
TIERED_LV = {1: 30, 2: 40, 3: 50}  # 旧档位等级（本报告 R1-R4 的实验条件）
FLAT_LV = {1: 45, 2: 45, 3: 45}  # 等级拍平：强度只来自种族值差
RULES = [
    ("R1 全克制", dict(basic=True, compress=None, levels=TIERED_LV)),
    ("R2 现状", dict(basic=False, compress=None, levels=TIERED_LV)),
    ("R3 压缩", dict(basic=False, compress=COMPRESS, levels=TIERED_LV)),
    ("R4 全克制+压缩", dict(basic=True, compress=COMPRESS, levels=TIERED_LV)),
    ("R5 现状+等级拍平", dict(basic=False, compress=None, levels=FLAT_LV)),
    ("R6 拍平+压缩", dict(basic=False, compress=COMPRESS, levels=FLAT_LV)),
]
MIN_SAMPLE = 40  # 属性出现次数低于此不进带宽统计

_BASE_LV = None


def apply_rule(rule: dict) -> None:
    global _BASE_LV
    import roster
    data.EFF_ON_BASIC = rule["basic"]
    data.EFF_COMPRESS = rule["compress"]
    if _BASE_LV is None:
        _BASE_LV = dict(roster.LEVEL_BY_TIER)
    if "levels" in rule:
        roster.LEVEL_BY_TIER.update(rule["levels"])
    else:
        roster.LEVEL_BY_TIER.update(_BASE_LV)


def random_metrics(games: int, size: int, seed: int) -> dict:
    rng = random.Random(seed)
    wins, durs = Counter(), []
    type_w = defaultdict(lambda: [0, 0])
    for _ in range(games):
        comp_a, comp_b = random_comp(rng, size), random_comp(rng, size)
        res = Battle(comp_a, comp_b, rng).run()
        wins[res["winner"]] += 1
        durs.append(res["duration"])
        for side, comp in ((0, comp_a), (1, comp_b)):
            for t in {t for p in comp for t in p.types}:
                type_w[t][0] += 1
                type_w[t][1] += 1 if res["winner"] == side else 0
    rates = {t: w / n for t, (n, w) in type_w.items() if n >= MIN_SAMPLE}
    return {
        "ab": (wins[0], wins[1], wins[None]),
        "median_dur": statistics.median(durs),
        "rates": rates,
        "bandwidth": max(rates.values()) - min(rates.values()),
    }


def counter_pair(name_a: str, name_b: str, games: int) -> float:
    """定向克制对位：返回 A 方胜率。固定种子序列，跨规则可比。"""
    roster = build_roster()

    def find(name):
        return next(p for ps in roster.values() for p in ps if p.name == name)

    pa, pb = find(name_a), find(name_b)
    win_a = 0
    for i in range(games):
        rng = random.Random(9000 + i)
        if Battle([pa] * 6, [pb] * 6, rng).run()["winner"] == 0:
            win_a += 1
    return win_a / games


import synergy as _syn
_syn.SYNERGIES_ON = False  # 本报告基线建立于羁绊关（2026-09-14 起默认开）


import combo as _cb, items as _it, status as _st
_cb.COMBOS_ON = False; _it.ITEMS_ON = False; _st.STATUS_ON = False  # 2026-09-14 成套翻开后钉关保基线


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=1000)
    ap.add_argument("--size", type=int, default=6)
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--pairs", type=int, default=200)
    args = ap.parse_args()

    print(f"克制实验：{args.games} 场随机 {args.size}v{args.size}（seed={args.seed}）"
          f"+ 定向对位各 {args.pairs} 场")
    rows = []
    for name, rule in RULES:
        apply_rule(rule)
        m = random_metrics(args.games, args.size, args.seed)
        fire_vs_water = counter_pair("水箭龟", "喷火龙", args.pairs)
        water_vs_rock = counter_pair("水箭龟", "隆隆岩", args.pairs)
        top = max(m["rates"].items(), key=lambda kv: kv[1])
        bot = min(m["rates"].items(), key=lambda kv: kv[1])
        rows.append((name, m, fire_vs_water, water_vs_rock, top, bot))
        print(f"\n[{name}]")
        print(f"  A/B/平 {m['ab'][0]}/{m['ab'][1]}/{m['ab'][2]}  "
              f"时长中位 {m['median_dur']:.1f}s")
        print(f"  属性胜率带宽 {m['bandwidth']:.1%}（最高 {top[0]} {top[1]:.0%} / "
              f"最低 {bot[0]} {bot[1]:.0%}，n≥{MIN_SAMPLE} 的 {len(m['rates'])} 系）")
        print(f"  定向对位：水箭龟 vs 喷火龙(2x) 水方胜率 {fire_vs_water:.0%}；"
              f"vs 隆隆岩(4x+近战) {water_vs_rock:.0%}")

    print("\n== 判读 ==")
    for name, m, fvw, wvr, _, _ in rows:
        print(f"  {name}: 带宽 {m['bandwidth']:.1%} | 水vs火 {fvw:.0%} | "
              f"水vs岩 {wvr:.0%}")
    print("  健康线参考：带宽 ≤15%、克制对位 65~85%（留出摆位/经济翻盘空间）、"
          "对位接近 100% 说明摆幅失控。")


if __name__ == "__main__":
    main()
