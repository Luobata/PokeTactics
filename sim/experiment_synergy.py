#!/usr/bin/env python3
"""S3 羁绊系统对照实验（关 vs 开）。

回答三件事：
1. 羁绊全开后随机局的属性胜率带宽怎么动（弱势系是否被拉回）；
2. 岩地 (6) 满羁绊能否救回「水炮一击溢出」（水箭龟×6 vs 隆隆岩×6，
   附读大招落岩队的最大单发伤害）；
3. 含拉普拉斯的冰系偏置队（WATER(6)+ICE(2)）对均衡队的胜率变化。

方法与克制/近远程实验同构：开关经 synergy.SYNERGIES_ON 注入；
跨臂同一 comp_rng 序列 + 每场独立战斗种子（羁绊不抽 rng，但战斗演化
会改变 rng 消耗，故逐场派生种子，保证两臂阵容与种子完全一致）。

用法：
    python3 sim/experiment_synergy.py [--games 1000] [--seed 5] [--pairs 200]
"""

import argparse
import random
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import synergy  # noqa: E402
from combat import Battle  # noqa: E402
from roster import build_roster, random_comp  # noqa: E402

MIN_SAMPLE = 40  # 属性出现次数低于此不进带宽统计（沿用克制实验口径）

# 定向对位阵容（名字须在 roster 中存在）
TEAM_ICE = [  # 冰系偏置：WATER(6) + ICE(2)（PSYCHIC/FLYING 各 1 不触发）
    "拉普拉斯", "拉普拉斯", "水箭龟", "宝石海星", "水伊布", "暴鲤龙"]
TEAM_SPREAD = [  # 均衡·散羁绊：FIRE(2)+GRASS(2)+POISON(2)，其余各 1
    "喷火龙", "风速狗", "妙蛙花", "大食花", "雷丘", "隆隆岩"]
TEAM_PLAIN = [  # 均衡·零羁绊：全异系（对照：无羁绊纯质量队）
    "喷火龙", "妙蛙花", "雷丘", "胡地", "隆隆岩", "卡比兽"]


def find_piece(name: str):
    roster = build_roster()
    return next(p for ps in roster.values() for p in ps if p.name == name)


def make_team(names: list) -> list:
    return [find_piece(n) for n in names]


def describe(names: list) -> str:
    """打印一支定向队的羁绊激活账（计数 → 档位 → 合并效果）。"""
    team = make_team(names)
    counts = synergy.compute(team)
    agg, cap = synergy._aggregate(counts)
    parts = [f"{t} {n}→({synergy.tier_of(n)})" for t, n in
             sorted(counts.items(), key=lambda kv: -kv[1]) if synergy.tier_of(n)]
    effs = " ".join(f"{k}+{v:.0%}" if k != "heal" else f"heal {v:.1%}/s"
                    for k, v in sorted(agg.items()))
    if cap is not None:
        effs += f" ult_cap≤{cap:.0%}maxHP"
    return f"[{'/'.join(parts) or '无激活'}] 效果: {effs or '-'}"


def random_metrics(games: int, size: int, seed: int) -> dict:
    comp_rng = random.Random(seed)  # 阵容序列独立于战斗 rng → 跨臂完全一致
    pairs = [(random_comp(comp_rng, size), random_comp(comp_rng, size))
             for _ in range(games)]
    wins, durs, type_w = Counter(), [], defaultdict(lambda: [0, 0])
    for i, (a, b) in enumerate(pairs):
        res = Battle(a, b, random.Random(seed * 1_000_003 + i)).run()
        wins[res["winner"]] += 1
        durs.append(res["duration"])
        for side, comp in ((0, a), (1, b)):
            for t in {t for p in comp for t in p.types}:
                type_w[t][0] += 1
                type_w[t][1] += 1 if res["winner"] == side else 0
    rates = {t: w / n for t, (n, w) in type_w.items() if n >= MIN_SAMPLE}
    ice_n, ice_w = type_w.get("ICE", (0, 0))
    return {
        "ab": (wins[0], wins[1], wins[None]),
        "median_dur": statistics.median(durs),
        "rates": rates,
        "bandwidth": max(rates.values()) - min(rates.values()),
        "ice": (ice_w / max(1, ice_n), ice_n),  # ICE 单列（n 小于阈值也报）
    }


def pair_metrics(names_a: list, names_b: list, games: int, seed_base: int,
                 track_max_hit: bool = False) -> dict:
    """定向对位：A 队胜率；track_max_hit 时附读大招落 B 队的最大单发。"""
    team_a, team_b = make_team(names_a), make_team(names_b)
    win_a, max_hits = 0, []
    for i in range(games):
        rng = random.Random(seed_base + i)
        battle = Battle([p for p in team_a], [p for p in team_b], rng)
        res = battle.run()
        if res["winner"] == 0:
            win_a += 1
        if track_max_hit:  # cast 事件: (t, "cast", atk, def, name, eff, dmg)
            hits = [ev[6] for ev in battle.events if ev[1] == "cast"
                    and battle.units[ev[3]].team == 1 and ev[6] > 0]
            max_hits.append(max(hits) if hits else 0)
    out = {"win_a": win_a / games}
    if track_max_hit:
        out["hit_med"] = statistics.median(max_hits)
        out["hit_max"] = max(max_hits)
    return out


def determinism_check(size: int, seed: int) -> None:
    """羁绊开启下同种子重放一局，比对事件流（宪法 2.2/2.6）。"""
    def play() -> list:
        rng = random.Random(seed)
        battle = Battle(random_comp(rng, size), random_comp(rng, size), rng)
        battle.run()
        return battle.events
    ok = play() == play()
    print(f"确定性自检（羁绊开）: {'通过' if ok else '失败！'}")
    if not ok:
        raise SystemExit(1)


import combo as _cb, items as _it, status as _st
_cb.COMBOS_ON = False; _it.ITEMS_ON = False; _st.STATUS_ON = False
import profiles as _pf
_pf.PROFILES_ON = False  # R1 单体档案（2026-09-15）：钉关保基线（胡地建档影响近远锚点）  # 2026-09-14 成套翻开后钉关保基线


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=1000)
    ap.add_argument("--size", type=int, default=6)
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--pairs", type=int, default=200)
    args = ap.parse_args()

    print(f"S3 羁绊实验：{args.games} 场随机 {args.size}v{args.size}"
          f"（seed={args.seed}）+ 定向对位各 {args.pairs} 场")
    print(f"  冰偏置队 {describe(TEAM_ICE)}")
    print(f"  均衡·散羁绊 {describe(TEAM_SPREAD)}")
    print(f"  均衡·零羁绊 {describe(TEAM_PLAIN)}")
    print(f"  岩地队 {describe(['隆隆岩'] * 6)}   水队 {describe(['水箭龟'] * 6)}")

    arms = [("S0 羁绊关", False), ("S1 羁绊开", True)]
    rows = []
    for name, flag in arms:
        synergy.SYNERGIES_ON = flag
        if flag:
            determinism_check(args.size, args.seed)
        m = random_metrics(args.games, args.size, args.seed)
        wvr = pair_metrics(["水箭龟"] * 6, ["隆隆岩"] * 6, args.pairs, 9000,
                           track_max_hit=True)
        ice_plain = pair_metrics(TEAM_ICE, TEAM_PLAIN, args.pairs, 9100)
        ice_spread = pair_metrics(TEAM_ICE, TEAM_SPREAD, args.pairs, 9200)
        top = max(m["rates"].items(), key=lambda kv: kv[1])
        bot = min(m["rates"].items(), key=lambda kv: kv[1])
        rows.append(dict(name=name, m=m, wvr=wvr, ice_plain=ice_plain,
                         ice_spread=ice_spread, top=top, bot=bot))
        print(f"\n[{name}]")
        print(f"  A/B/平 {m['ab'][0]}/{m['ab'][1]}/{m['ab'][2]}  "
              f"时长中位 {m['median_dur']:.1f}s")
        print(f"  属性胜率带宽 {m['bandwidth']:.1%}（最高 {top[0]} {top[1]:.0%} / "
              f"最低 {bot[0]} {bot[1]:.0%}，n≥{MIN_SAMPLE} 的 {len(m['rates'])} 系）")
        print(f"  属性胜率: " + "  ".join(
            f"{t} {r:.0%}" for t, r in sorted(
                m["rates"].items(), key=lambda kv: -kv[1])))
        print(f"  ICE（拉普拉斯）随机局胜率 {m['ice'][0]:.0%} (n={m['ice'][1]})")
        print(f"  水箭龟×6 vs 隆隆岩×6：水方胜率 {wvr['win_a']:.0%}，"
              f"大招落岩队单发 中位 {wvr['hit_med']:.0f} / 最大 {wvr['hit_max']:.0f}")
        print(f"  冰偏置 vs 均衡·零羁绊：冰队胜率 {ice_plain['win_a']:.0%}；"
              f"vs 均衡·散羁绊：{ice_spread['win_a']:.0%}")

    synergy.SYNERGIES_ON = False  # 实验后恢复默认
    print("\n== 判读 ==")
    for r in rows:
        m, wvr = r["m"], r["wvr"]
        print(f"  {r['name']}: 带宽 {m['bandwidth']:.1%} | ICE {m['ice'][0]:.0%} | "
              f"水vs岩 {wvr['win_a']:.0%}（大招单发中位 {wvr['hit_med']:.0f}） | "
              f"冰偏置 vs 零羁绊/散羁绊 {r['ice_plain']['win_a']:.0%}/"
              f"{r['ice_spread']['win_a']:.0%}")
    print("  关注：带宽是否收窄（弱势系拉回）、水vs岩是否脱离 100%、"
          "冰偏置读数是否显著走高（走高=水/冰羁绊喂霸榜，需压水治疗或提冰阈值）。")


if __name__ == "__main__":
    main()
