#!/usr/bin/env python3
"""S10 组合技 A（齐射）对照实验：关 vs 开。

回答三件事：
1. 随机局不劣化：齐射开/关的属性胜率带宽、时长、平局率（健康线：
   带宽劣化 ≤3pp、时长中位 6-10s）——随机 6 人队凑满 (6) 是小概率事件，
   本臂本质是「不误伤」回归 + 触发率/人口占比读数；
2. 齐射伤害占比：t=0 的 attack 事件伤害 / 全场总伤（健康线 ≤12%），
   主口径 = 定向局（必触发、单局占比中位/最大），辅口径 = 随机局全员
   汇总占比与触发局单局占比；
3. 定向对位：凑 (6) 电队 vs 零羁绊队（齐射是羁绊的仪式感回报，不该把
   对位推过健康线）；附读双最高档（隆隆岩×6 = ROCK(6)+GROUND(6)，按
   「每队至多一轮」规则只放计数并列先序的 GROUND 单轮）与双方都触发
   （电 vs 电，互相抵消读数），以及 docs/04 开放问题 1（时机）的数据：
   齐射 t=0 击杀数 / 首次出手时点 / 0.5s 前减员率。

方法与 S3/S5 同构：开关经 combo.COMBOS_ON 注入（S3 羁绊两臂恒开，读数
差纯归因齐射）；跨臂同一 comp_rng 序列 + 每场独立战斗种子（齐射吃伤害
随机骰，战斗演化会改变 rng 消耗，故逐场派生种子，保证两臂阵容与种子
完全一致——comp_digest 两臂相同即证）。

齐射伤害口径：t=0.0 的 attack 事件（正常战斗首个行动在起手抖动 0~0.3s
之后的一跳才发生，t=0 的 attack 只能来自齐射；关臂断言恒 0 自证口径）。

用法：
    python3 sim/experiment_combo.py [--games 1000] [--seed 5] [--pairs 200]
"""

import argparse
import hashlib
import random
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import combo  # noqa: E402
import synergy  # noqa: E402
from combat import Battle  # noqa: E402
from roster import build_roster, random_comp  # noqa: E402

MIN_SAMPLE = 40  # 属性出现次数低于此不进带宽统计（沿用克制/S3 实验口径）

# 定向阵容（名字须在 roster 中存在）
TEAM_ELEC6 = [  # 凑 (6) 电：池内电系 5 种，重复 1 只皮卡丘到 6 计
    "皮卡丘", "皮卡丘", "雷丘", "小磁怪", "三合一磁怪", "雷伊布"]
TEAM_PLAIN = [  # 零羁绊：全异系（对照，S3 实验同款）
    "喷火龙", "妙蛙花", "雷丘", "胡地", "隆隆岩", "卡比兽"]
TEAM_DUAL = ["隆隆岩"] * 6   # ROCK(6)+GROUND(6)：双最高档连发读数


def find_piece(name: str):
    roster = build_roster()
    return next(p for ps in roster.values() for p in ps if p.name == name)


def make_team(names: list) -> list:
    return [find_piece(n) for n in names]


def describe(names: list) -> str:
    """一支定向队的羁绊账 + 齐射触发（计数 → 档位 → 组合技名）。"""
    team = make_team(names)
    counts = synergy.compute(team)
    parts = [f"{t} {n}→({synergy.tier_of(n, t)})" for t, n in
             sorted(counts.items(), key=lambda kv: -kv[1])
             if synergy.tier_of(n, t)]
    qualified = combo.volley_types(team)
    pick = combo.volley_pick(team)
    volley = (f"{pick}「{combo.COMBO_NAMES[pick]}」" if pick else "无")
    if len(qualified) > 1:   # 双最高档：够格多系、只放一轮
        volley += f"（够格 {'/'.join(qualified)}，放计数最高的一轮）"
    return f"[{'/'.join(parts) or '无激活'}] 齐射: {volley}"


def volley_stats(battle: Battle) -> (int, int, int):
    """(齐射总伤, 发数, t=0 击杀数)：t=0.0 的 attack/die 事件口径。"""
    shots = [ev for ev in battle.events if ev[1] == "attack" and ev[0] == 0.0]
    kills = sum(1 for ev in battle.events if ev[1] == "die" and ev[0] == 0.0)
    return sum(ev[4] for ev in shots), len(shots), kills


def random_metrics(games: int, size: int, seed: int) -> dict:
    comp_rng = random.Random(seed)  # 阵容序列独立于战斗 rng → 跨臂完全一致
    pairs = [(random_comp(comp_rng, size), random_comp(comp_rng, size))
             for _ in range(games)]
    comp_digest = hashlib.sha256(repr(pairs).encode()).hexdigest()
    wins, durs, type_w = Counter(), [], defaultdict(lambda: [0, 0])
    v_dmg_all = v_shots_tot = v_trig = 0
    would = 0   # 阵容侧够格局数（combo.volley_types，与开关无关 → 两臂必同）
    dmg_all = 0
    v_shares_cond = []
    stream = hashlib.sha256()
    for i, (a, b) in enumerate(pairs):
        battle = Battle(a, b, random.Random(seed * 1_000_003 + i))
        res = battle.run()
        wins[res["winner"]] += 1
        durs.append(res["duration"])
        if combo.volley_types(a) or combo.volley_types(b):
            would += 1
        total = max(1, sum(u.damage_dealt for u in battle.units))
        dmg_all += total
        v_dmg, v_n, _ = volley_stats(battle)
        if i < 20 or v_n:   # 前 20 场 + 全部触发场：摘要覆盖齐射路径
            stream.update(repr(battle.events).encode())
        if v_n:      # 实触发局（齐射开着才有；关臂恒 0 → 口径自证）
            v_trig += 1
            v_shares_cond.append(v_dmg / total)
        v_dmg_all += v_dmg
        v_shots_tot += v_n
        for side, comp in ((0, a), (1, b)):
            for t in {t for p in comp for t in p.types}:
                type_w[t][0] += 1
                type_w[t][1] += 1 if res["winner"] == side else 0
    rates = {t: w / n for t, (n, w) in type_w.items() if n >= MIN_SAMPLE}
    return {
        "ab": (wins[0], wins[1], wins[None]),
        "median_dur": statistics.median(durs),
        "rates": rates,
        "bandwidth": max(rates.values()) - min(rates.values()),
        "v_trig": v_trig, "v_shots": v_shots_tot, "would": would,
        "dmg_all": dmg_all,
        "v_share_all": v_dmg_all / dmg_all,
        "v_share_cond_med": (statistics.median(v_shares_cond)
                             if v_shares_cond else None),
        "comp_digest": comp_digest,
        "stream_digest": stream.hexdigest(),
    }


def pair_metrics(names_a: list, names_b: list, games: int,
                 seed_base: int) -> dict:
    """定向对位：A 队胜率 + 齐射读数（占比中位/最大、场均发数、t=0 击杀）
    + 时机读数（首次出手时点中位、0.5s 前减员局率，docs/04 开放问题 1）。"""
    team_a, team_b = make_team(names_a), make_team(names_b)
    win_a, durs = 0, []
    v_dmgs, v_shots_tot, v_kills = [], 0, 0
    first_hits, early_death = [], 0
    stream = hashlib.sha256()
    for i in range(games):
        rng = random.Random(seed_base + i)
        battle = Battle(list(team_a), list(team_b), rng)
        res = battle.run()
        if i < 20:   # 前 20 场全量事件（开臂必含齐射路径，跨进程比对用）
            stream.update(repr(battle.events).encode())
        if res["winner"] == 0:
            win_a += 1
        durs.append(res["duration"])
        v_dmg, v_shots, v_k = volley_stats(battle)
        v_kills += v_k
        v_shots_tot += v_shots
        v_dmgs.append(v_dmg / max(1, sum(u.damage_dealt
                                         for u in battle.units)))
        hits = [ev[0] for ev in battle.events
                if ev[1] in ("attack", "cast")]
        if hits:
            first_hits.append(min(hits))
        if any(ev[1] == "die" and ev[0] < 0.5 for ev in battle.events):
            early_death += 1
    return {
        "win_a": win_a / games,
        "dur_med": statistics.median(durs),
        "v_share_med": statistics.median(v_dmgs),
        "v_share_max": max(v_dmgs),
        "v_shots_avg": v_shots_tot / games,
        "v_kills": v_kills,
        "first_hit_med": statistics.median(first_hits) if first_hits else None,
        "early_death": early_death / games,
        "stream_digest": stream.hexdigest(),
    }


def determinism_check(seed: int) -> None:
    """齐射开启下同种子重放一局（定向局，保证真触发齐射路径），比对事件流。"""
    def play() -> list:
        battle = Battle(make_team(TEAM_ELEC6), make_team(TEAM_PLAIN),
                        random.Random(seed))
        battle.run()
        return battle.events
    ok = play() == play()
    print(f"确定性自检（齐射开，定向局）: {'通过' if ok else '失败！'}")
    if not ok:
        raise SystemExit(1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=1000)
    ap.add_argument("--size", type=int, default=6)
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--pairs", type=int, default=200)
    args = ap.parse_args()

    print(f"S10 组合技 A（齐射）实验：{args.games} 场随机 {args.size}v{args.size}"
          f"（seed={args.seed}）+ 定向对位各 {args.pairs} 场（S3 羁绊两臂恒开）")
    print(f"  电(6)队 {describe(TEAM_ELEC6)}")
    print(f"  零羁绊 {describe(TEAM_PLAIN)}")
    print(f"  双最高档 {describe(TEAM_DUAL)}")

    arms = [("C0 齐射关", False), ("C1 齐射开", True)]
    rows = []
    for name, flag in arms:
        combo.COMBOS_ON = flag
        if flag:
            determinism_check(42)
        m = random_metrics(args.games, args.size, args.seed)
        if not flag and (m["v_trig"] or m["v_shots"]):
            raise SystemExit("口径被污染：关臂出现 t=0 attack 事件！")
        elec = pair_metrics(TEAM_ELEC6, TEAM_PLAIN, args.pairs, 9000)
        rows.append(dict(name=name, m=m, elec=elec, extra=None))
        print(f"\n[{name}]")
        print(f"  随机: A/B/平 {m['ab'][0]}/{m['ab'][1]}/{m['ab'][2]}  "
              f"时长中位 {m['median_dur']:.1f}s  够格局 {m['would']}/{args.games}"
              f"（实触发 {m['v_trig']}）")
        top = max(m["rates"].items(), key=lambda kv: kv[1])
        bot = min(m["rates"].items(), key=lambda kv: kv[1])
        print(f"  属性胜率带宽 {m['bandwidth']:.1%}（最高 {top[0]} {top[1]:.0%} / "
              f"最低 {bot[0]} {bot[1]:.0%}，n≥{MIN_SAMPLE} 的 {len(m['rates'])} 系）")
        print(f"  齐射伤害: 随机局汇总占比 {m['v_share_all']:.2%}（{m['v_shots']} 发）"
              + (f"  触发局单局占比中位 {m['v_share_cond_med']:.1%}"
                 if m["v_share_cond_med"] is not None else ""))
        e = rows[-1]["elec"]
        print(f"  电(6) vs 零羁绊: 电队胜率 {e['win_a']:.0%}  "
              f"时长中位 {e['dur_med']:.1f}s  齐射占比中位 {e['v_share_med']:.1%}"
              f"（最大 {e['v_share_max']:.1%}，场均 {e['v_shots_avg']:.0f} 发，"
              f"t=0 击杀 {e['v_kills']}）")
        print(f"  时机读数: 首次出手中位 {e['first_hit_med']:.1f}s  "
              f"0.5s 前有减员的局 {e['early_death']:.0%}")
        print(f"  阵容摘要 {m['comp_digest'][:16]}  事件流摘要 "
              f"{m['stream_digest'][:16]} / 定向 {e['stream_digest'][:16]}")
        if flag:
            dual = pair_metrics(TEAM_DUAL, TEAM_PLAIN, args.pairs, 9300)
            mirror = pair_metrics(TEAM_ELEC6, TEAM_ELEC6, args.pairs, 9400)
            rows[-1]["extra"] = (dual, mirror)
            print(f"  附读(仅开臂): 双最高档岩地队(单轮: {describe(TEAM_DUAL)})"
                  f" vs 零羁绊 {dual['win_a']:.0%}，齐射占比中位 "
                  f"{dual['v_share_med']:.1%}（最大 {dual['v_share_max']:.1%}，"
                  f"t=0 击杀 {dual['v_kills']}）")
            print(f"             电 vs 电（双触发互相抵消）: 电A胜率 "
                  f"{mirror['win_a']:.0%}，齐射占比中位 "
                  f"{mirror['v_share_med']:.1%}，时长中位 {mirror['dur_med']:.1f}s")

    combo.COMBOS_ON = False  # 实验后恢复默认
    print("\n== 判读 ==")
    off, on = rows
    bd = on["m"]["bandwidth"] - off["m"]["bandwidth"]
    dur_d = on["m"]["median_dur"] - off["m"]["median_dur"]
    print(f"  随机局: 带宽 {off['m']['bandwidth']:.1%} → {on['m']['bandwidth']:.1%}"
          f"（动 {bd * 100:+.1f}pp，健康线 ≤3pp）  时长中位 "
          f"{off['m']['median_dur']:.1f}s → {on['m']['median_dur']:.1f}s"
          f"（{dur_d:+.1f}s）  平局 {off['m']['ab'][2]} → {on['m']['ab'][2]}")
    print(f"  定向(电(6) vs 零羁绊): 胜率 {off['elec']['win_a']:.0%} → "
          f"{on['elec']['win_a']:.0%}，齐射伤害占比中位 "
          f"{on['elec']['v_share_med']:.1%} / 最大 {on['elec']['v_share_max']:.1%}"
          f"（健康线 ≤12%）")
    print(f"  时机（docs/04 开放问题 1）: 齐射 t=0 击杀 {on['elec']['v_kills']} 只 / "
          f"{args.pairs} 局；正常局首次出手中位 {off['elec']['first_hit_med']:.1f}s、"
          f"0.5s 前有减员的局 {off['elec']['early_death']:.0%}"
          f"（开臂 {on['elec']['early_death']:.0%}）")
    print("  关注：触发局伤害占比是否越 12% 线、带宽是否劣化 >3pp、"
          "单轮最重对位（岩地 vs 克制面）是否贴近线（贴近则 v2 考虑"
          "「每发 ≤ 目标最大 HP 的 x%」结构性护栏或按系调威力）。")


if __name__ == "__main__":
    main()
