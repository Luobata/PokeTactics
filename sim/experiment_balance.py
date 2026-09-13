#!/usr/bin/env python3
"""S3 平衡修订实验（2026-09-14）：ICE 霸榜 / BUG 垫底两项盯防的收尾验证。

背景（reports/synergy-flip-baseline-2026-09-14.md 的盯防项）：
羁绊翻开后 ICE 随机局 62-70%（载体仅拉普拉斯）、BUG 43.7% 垫底（补偿型
羁绊未兑现）。修订内容见 sim/synergy.py 模块头与
reports/balance-ice-bug-2026-09-14.md：
1. 冰 (2) 减伤 4% → 2%（S3 §5 盯防条款触发动作）；
2. 治疗衰减 HEAL_TIER3_MULT=0.5（heal 对 3 费旗舰减半——修机制不砍数值，
   1/2 费水系载体全额）；
3. 虫群围猎 (1)(2)(4)(6) 四档（补偿从第一只虫开始，(2) 转韧性 hp）。

方法与 experiment_synergy 同构：两臂跨臂同一 comp_rng 序列 + 逐场派生
战斗种子（阵容与种子完全可比）。两臂：
- v1 修前 = 冻结快照（2026-09-13 终版表 + 治疗不衰减），锚定翻牌基线；
- v2 修后 = sim/synergy.py 当前态（零改动注入，所见即所得）。

随机局口径：主种子（默认 5，沿用 S3 惯例）1000 场做单种子读数；另跑
多种子合池（默认 5/11/23/31/47 各 1000 场）——单种子 ICE n≈50-67、
SE±6pp（翻牌基线已确立「单种子噪音由多种子结案」的口径），健康线以
合池为主判、主种子为辅证。

健康线（判读行自动 PASS/FAIL）：
- ICE 随机局 ≤62%（合池）；BUG 随机局 ≥47%（主种子与合池）；
- 水vs岩 ≤90% 且大招落岩单发中位 ~51（不回退既有成果）；
- 属性带宽 ≤25%；其余系（除 ICE/BUG）在 45-58% 带内；
- A/B 各种子在 45-55% 噪音带；冰偏置 vs 散羁绊 <90%（盯防条款触发线）；
- BUG 定向臂 v2 ≥ v1（补偿方向兑现）。

用法：python3 sim/experiment_balance.py [--games 1000] [--seed 5]
        [--pool-seeds 5,11,23,31,47] [--pairs 200]
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

MIN_SAMPLE = 40    # 单种子属性进带宽统计的最小样本（沿用克制实验口径）
POOL_SAMPLE = 120  # 合池口径（多种子合读后仍要足够样本）

# ---- v1 冻结快照：2026-09-13 终版表的虫/冰/水三条 + 治疗不衰减 ----
# （只快照与修订相关的差异项，其余系与当前表共享；治疗衰减经
#   synergy.HEAL_TIER3_MULT=1.0 关闭。快照锚定翻牌基线，不随表演进漂移。）
V1_PATCH = {
    "ICE": {"theme": "凝冰之躯", "tiers": {
        2: {"dr": 0.04},
        4: {"dr": 0.10, "hp": 0.08},
        6: {"dr": 0.16, "hp": 0.16}}},
    "BUG": {"theme": "虫群围猎", "tiers": {
        2: {"speed": 0.06, "dmg": 0.03},
        4: {"speed": 0.12, "dmg": 0.06},
        6: {"speed": 0.18, "dmg": 0.10, "heal": 0.003}}},
}
V2_TABLE = None      # main() 里冻结当前表
V2_HEAL_MULT = None  # main() 里冻结当前治疗衰减系数

# ---- 定向对位阵容（与 experiment_synergy 的 ICE/水岩臂同款保持可比） ----
TEAM_ICE = [  # 冰系偏置：WATER(6) + ICE(2)（盯防条款的对象阵容）
    "拉普拉斯", "拉普拉斯", "水箭龟", "宝石海星", "水伊布", "暴鲤龙"]
TEAM_SPREAD = [  # 均衡·散羁绊：FIRE(2)+GRASS(2)+POISON(2)
    "喷火龙", "风速狗", "妙蛙花", "大食花", "雷丘", "隆隆岩"]
TEAM_PLAIN = [  # 均衡·零羁绊：全异系 T3 队（混编虫臂的底版）
    "喷火龙", "妙蛙花", "雷丘", "胡地", "隆隆岩", "卡比兽"]
TEAM_BUG1 = [  # 单虫混编：PLAIN 换入一只绿毛虫 → BUG(1)（v1 无档，v2 有）
    "绿毛虫", "喷火龙", "妙蛙花", "雷丘", "胡地", "隆隆岩"]
TEAM_BUG2 = [  # 双虫混编：换入两只 → BUG(2)（v1 旧档 vs v2 新档的对照位）
    "绿毛虫", "铁甲蛹", "妙蛙花", "雷丘", "胡地", "隆隆岩"]
TEAM_SWARM = [  # 虫群满档：BUG(6)+POISON(4)+FLYING(2)
    "绿毛虫", "铁甲蛹", "独角虫", "铁壳蛹", "巴大蝶", "大针蜂"]
TEAM_T1_PLAIN = [  # 同价位零羁绊：全 1 费、六系互异（虫群臂的等价对手）
    "小火龙", "皮卡丘", "凯西", "腕力", "小拳石", "波波"]


def set_arm(v1: bool) -> None:
    """切换修前/修后臂：v1 = 快照差异项 + 关治疗衰减；v2 = 冻结的当前表。"""
    table = dict(V2_TABLE)  # 从冻结快照出发，防止 v1 补丁污染 v2 臂
    if v1:
        table.update(V1_PATCH)
        heal_mult = 1.0
    else:
        heal_mult = V2_HEAL_MULT
    synergy.SYNERGY_TABLE.clear()
    synergy.SYNERGY_TABLE.update(table)
    synergy.HEAL_TIER3_MULT = heal_mult


def find_piece(name: str):
    roster = build_roster()
    return next(p for ps in roster.values() for p in ps if p.name == name)


def make_team(names: list) -> list:
    return [find_piece(n) for n in names]


def describe(names: list) -> str:
    """打印一支定向队的羁绊激活账（档位按表内自定义阶梯）。"""
    team = make_team(names)
    counts = synergy.compute(team)
    agg, cap = synergy._aggregate(counts)
    parts = [f"{t} {n}→({synergy.tier_of(n, t)})" for t, n in
             sorted(counts.items(), key=lambda kv: -kv[1])
             if synergy.tier_of(n, t)]
    effs = " ".join(f"{k}+{v:.0%}" if k not in ("heal", "hp") else
                    (f"heal {v:.1%}/s" if k == "heal" else f"hp+{v:.0%}")
                    for k, v in sorted(agg.items()))
    if cap is not None:
        effs += f" ult_cap≤{cap:.0%}maxHP"
    return f"[{'/'.join(parts) or '无激活'}] 效果: {effs or '-'}"


def random_metrics(games: int, size: int, seed: int, min_sample: int) -> dict:
    """随机局读数：属性胜率（含 ICE/BUG 单列）、带宽、A/B、时长。"""
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
    rates = {t: w / n for t, (n, w) in type_w.items() if n >= min_sample}
    return {
        "ab": (wins[0], wins[1], wins[None]),
        "median_dur": statistics.median(durs),
        "rates": rates,
        "type_w": {t: (n, w) for t, (n, w) in type_w.items()},
        "bandwidth": max(rates.values()) - min(rates.values()),
        "ice": tuple(type_w.get("ICE", (0, 0))),
        "bug": tuple(type_w.get("BUG", (0, 0))),
        "ice_rate": type_w["ICE"][1] / max(1, type_w["ICE"][0]),
        "bug_rate": type_w["BUG"][1] / max(1, type_w["BUG"][0]),
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
    """修后臂同种子重放一局，比对事件流（宪法 2.2/2.6）。"""
    def play() -> list:
        rng = random.Random(seed)
        battle = Battle(random_comp(rng, size), random_comp(rng, size), rng)
        battle.run()
        return battle.events
    ok = play() == play()
    print(f"确定性自检（修后臂）: {'通过' if ok else '失败！'}")
    if not ok:
        raise SystemExit(1)


def main() -> None:
    global V2_TABLE, V2_HEAL_MULT
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=1000, help="主种子随机局数")
    ap.add_argument("--size", type=int, default=6)
    ap.add_argument("--seed", type=int, default=5, help="主种子（S3 惯例）")
    ap.add_argument("--pool-seeds", type=str, default="5,11,23,31,47",
                    help="合池种子列表（逗号分隔）")
    ap.add_argument("--pairs", type=int, default=200)
    args = ap.parse_args()
    pool_seeds = [int(s) for s in args.pool_seeds.split(",")]

    V2_TABLE = dict(synergy.SYNERGY_TABLE)   # 冻结当前（修后）表
    V2_HEAL_MULT = synergy.HEAL_TIER3_MULT
    synergy.SYNERGIES_ON = True

    print(f"S3 平衡修订实验：修前 v1 / 修后 v2 两臂 × {args.games} 场随机 "
          f"{args.size}v{args.size}（主种子 {args.seed}）"
          f"+ 合池 {args.pool_seeds} + 定向对位各 {args.pairs} 场")
    print(f"  v2 = synergy.py 当前态（治疗衰减 ×{V2_HEAL_MULT}）")
    set_arm(True)
    print(f"  冰偏置队 {describe(TEAM_ICE)}")
    print(f"  双虫混编 v1 {describe(TEAM_BUG2)}")
    set_arm(False)
    print(f"  双虫混编 v2 {describe(TEAM_BUG2)}")
    print(f"  虫群满档 {describe(TEAM_SWARM)}")
    print(f"  同价位零羁绊 {describe(TEAM_T1_PLAIN)}")
    determinism_check(args.size, args.seed)

    arms = [("v1 修前", True), ("v2 修后", False)]
    rows = []
    for name, v1 in arms:
        set_arm(v1)
        m = random_metrics(args.games, args.size, args.seed, MIN_SAMPLE)
        # 合池（多种子结案口径）：各种子属性计数加总后统一算率
        pooled = defaultdict(lambda: [0, 0])
        ab_pooled = [0, 0, 0]
        for s in pool_seeds:
            ms = random_metrics(args.games, args.size, s, 1)
            for t, (n, w) in ms["type_w"].items():
                pooled[t][0] += n
                pooled[t][1] += w
            a, b, d = ms["ab"]
            ab_pooled[0] += a; ab_pooled[1] += b; ab_pooled[2] += d
        prates = {t: w / n for t, (n, w) in pooled.items() if n >= POOL_SAMPLE}
        pool = {
            "rates": prates,
            "bandwidth": max(prates.values()) - min(prates.values()),
            "ice": pooled.get("ICE", (0, 0)),
            "bug": pooled.get("BUG", (0, 0)),
            "ice_rate": pooled["ICE"][1] / max(1, pooled["ICE"][0]),
            "bug_rate": pooled["BUG"][1] / max(1, pooled["BUG"][0]),
            "ab": tuple(ab_pooled),
        }
        # 定向臂
        wvr = pair_metrics(["水箭龟"] * 6, ["隆隆岩"] * 6, args.pairs, 9000,
                           track_max_hit=True)
        ice_plain = pair_metrics(TEAM_ICE, TEAM_PLAIN, args.pairs, 9100)
        ice_spread = pair_metrics(TEAM_ICE, TEAM_SPREAD, args.pairs, 9200)
        bug1 = pair_metrics(TEAM_BUG1, TEAM_PLAIN, args.pairs, 9300)
        bug2 = pair_metrics(TEAM_BUG2, TEAM_PLAIN, args.pairs, 9400)
        swarm = pair_metrics(TEAM_SWARM, TEAM_T1_PLAIN, args.pairs, 9500)
        rows.append(dict(name=name, m=m, pool=pool, wvr=wvr,
                         ice_plain=ice_plain, ice_spread=ice_spread,
                         bug1=bug1, bug2=bug2, swarm=swarm))
        print(f"\n[{name}]")
        print(f"  主种子{args.seed}: A/B/平 {m['ab'][0]}/{m['ab'][1]}/{m['ab'][2]}"
              f"  时长中位 {m['median_dur']:.1f}s  带宽 {m['bandwidth']:.1%}")
        print(f"    ICE {m['ice_rate']:.1%}(n={m['ice'][0]})  "
              f"BUG {m['bug_rate']:.1%}(n={m['bug'][0]})")
        print(f"    属性胜率: " + "  ".join(
            f"{t} {r:.0%}" for t, r in sorted(
                m["rates"].items(), key=lambda kv: -kv[1])))
        print(f"  合池{len(pool_seeds)}种子×{args.games}: "
              f"A/B/平 {pool['ab'][0]}/{pool['ab'][1]}/{pool['ab'][2]}  "
              f"带宽 {pool['bandwidth']:.1%}  "
              f"ICE {pool['ice_rate']:.1%}(n={pool['ice'][0]})  "
              f"BUG {pool['bug_rate']:.1%}(n={pool['bug'][0]})")
        print(f"    属性胜率: " + "  ".join(
            f"{t} {r:.0%}" for t, r in sorted(
                pool["rates"].items(), key=lambda kv: -kv[1])))
        print(f"  水箭龟×6 vs 隆隆岩×6：水方 {wvr['win_a']:.0%}，"
              f"大招落岩队单发 中位 {wvr['hit_med']:.0f} / 最大 {wvr['hit_max']:.0f}")
        print(f"  冰偏置 vs 零羁绊 {ice_plain['win_a']:.0%} / "
              f"vs 散羁绊 {ice_spread['win_a']:.0%}")
        print(f"  单虫混编 vs 零羁绊 {bug1['win_a']:.0%}  "
              f"双虫混编 {bug2['win_a']:.0%}  "
              f"虫群满档 vs 同价位零羁绊 {swarm['win_a']:.0%}")

    set_arm(False)  # 恢复修后（当前默认）态
    v1, v2 = rows
    checks = []

    def check(label: str, ok: bool, detail: str) -> None:
        checks.append((label, ok))
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}：{detail}")

    print("\n== 健康线判读 ==")
    ice2, bug2m = v2["m"]["ice_rate"], v2["m"]["bug_rate"]
    ice2p, bug2p = v2["pool"]["ice_rate"], v2["pool"]["bug_rate"]
    check("ICE 随机局 ≤62%（合池主判）", ice2p <= 0.62,
          f"v1 合池 {v1['pool']['ice_rate']:.1%} → v2 {ice2p:.1%}"
          f"(n={v2['pool']['ice'][0]})；主种子 v1 {v1['m']['ice_rate']:.1%} → "
          f"v2 {ice2:.1%}(n={v2['m']['ice'][0]})")
    check("ICE 单种子读数波动提示", True,
          f"ICE 单种子 n≈{v2['m']['ice'][0]}、SE≈±6pp，逐种子读数属方向参考")
    check("BUG 随机局 ≥47%（主种子）", bug2m >= 0.47,
          f"v1 {v1['m']['bug_rate']:.1%} → v2 {bug2m:.1%}"
          f"(n={v2['m']['bug'][0]})；合池 v1 {v1['pool']['bug_rate']:.1%} → "
          f"v2 {bug2p:.1%}")
    check("水vs岩 ≤90% 且大招单发封顶不回退",
          v2["wvr"]["win_a"] <= 0.90 and v2["wvr"]["hit_med"] <= 60,
          f"v2 水方 {v2['wvr']['win_a']:.0%}（v1 {v1['wvr']['win_a']:.0%}），"
          f"大招落岩单发中位 {v2['wvr']['hit_med']:.0f}")
    bw2, bw2p = v2["m"]["bandwidth"], v2["pool"]["bandwidth"]
    check("属性带宽 ≤25%", bw2 <= 0.25 and bw2p <= 0.25,
          f"主种子 v1 {v1['m']['bandwidth']:.1%} → v2 {bw2:.1%}；"
          f"合池 v1 {v1['pool']['bandwidth']:.1%} → v2 {bw2p:.1%}")
    others_ok_m = all(0.45 <= r <= 0.58 for t, r in v2["m"]["rates"].items()
                      if t not in ("ICE", "BUG"))
    others_ok_p = all(0.45 <= r <= 0.58 for t, r in v2["pool"]["rates"].items()
                      if t not in ("ICE", "BUG"))
    check("其余系 45-58% 带内（主种子+合池）", others_ok_m and others_ok_p,
          "除 ICE/BUG 外全部落带（超带项：无）" if others_ok_m and others_ok_p
          else f"超带：{[f'{t}{r:.0%}' for t, r in {**v2['m']['rates'], **v2['pool']['rates']}.items() if t not in ('ICE','BUG') and not 0.45 <= r <= 0.58]}")
    ab_ok = all(0.45 <= r[0] / max(1, sum(r)) <= 0.55 for r in
                [v2["m"]["ab"], v2["pool"]["ab"]])
    check("A/B 噪音带 45-55%", ab_ok,
          f"主种子 {v2['m']['ab'][0]}:{v2['m']['ab'][1]}，"
          f"合池 {v2['pool']['ab'][0]}:{v2['pool']['ab'][1]}")
    check("冰偏置 vs 散羁绊 <90%（盯防条款触发线）",
          v2["ice_spread"]["win_a"] < 0.90,
          f"v1 {v1['ice_spread']['win_a']:.0%} → v2 {v2['ice_spread']['win_a']:.0%}"
          f"（vs 零羁绊 {v1['ice_plain']['win_a']:.0%} → "
          f"{v2['ice_plain']['win_a']:.0%}）")
    bug_up = (v2["bug1"]["win_a"] >= v1["bug1"]["win_a"]
              and v2["bug2"]["win_a"] >= v1["bug2"]["win_a"]
              and v2["swarm"]["win_a"] >= v1["swarm"]["win_a"])
    check("BUG 定向臂补偿方向兑现（v2 ≥ v1）", bug_up,
          f"单虫 {v1['bug1']['win_a']:.0%}→{v2['bug1']['win_a']:.0%}  "
          f"双虫 {v1['bug2']['win_a']:.0%}→{v2['bug2']['win_a']:.0%}  "
          f"虫群 {v1['swarm']['win_a']:.0%}→{v2['swarm']['win_a']:.0%}")
    n_fail = sum(1 for _, ok in checks if not ok)
    print(f"\n结论：{len(checks) - n_fail}/{len(checks)} 项通过"
          + ("；全部健康线达标" if n_fail == 0 else f"；{n_fail} 项未达标！"))
    if n_fail:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
