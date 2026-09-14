#!/usr/bin/env python3
"""S5 装备双臂实验：items 关/开 × N 局（同种子同阵容序列）。

验收线（docs/07 §7 落地顺序第 1-2 步 + v1 健康线）：
1. 局长：开臂均值落在 27-31 带内（装备加战力应缩短对局但不提前崩盘；
   关臂对照同报）；
2. 人格方差不劣化超 50%：开臂人格平均名次方差 < 关臂 × 1.5
   （装备是全人格平等的第 4 资源轴，不应放大人格差距）；
3. 无死锁：两臂「非野怪轮无掉血」均为 0（S4 §6 死锁判据）。

附加读数：金币曲线（幸运蛋/野怪掉金的收入侧位移）、能力层名次、
进化石触发统计（触发人次/局、终点形态、通信 3合1 解锁数）、
掉落/合成/装备频率、冠军人格分布。

确定性（宪法 2.2）：装备随机全部走子流——掉落走 pve 子流掉落段
（counter ≥ 1024，与掉金 counter=i 互不位移），闪避/披带骰走 battle
子流；合成/装备决策零随机。脚本内建同种子重放自检（开臂），
跨进程/跨 PYTHONHASHSEED 复核见报告 §复现。

用法：
    python3 sim/experiment_items.py --games 50 --seed 100
"""

import argparse
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import items  # noqa: E402
from match import Match  # noqa: E402

LEN_BAND = (27, 31)      # v1 健康线：开臂平均局长
VARIANCE_WORSEN_LIMIT = 1.5   # 人格方差劣化上限（关臂 × 1.5）
GOLD_CHECKPOINTS = (4, 9, 14, 19, 24, 28)   # R5/R10/.../R29（曲线采样点）


def run_batch(games: int, seed: int, rounds: int = 31) -> dict:
    """跑 N 局（当前 items.ITEMS_ON 状态），收集双臂对照读数。"""
    rounds_full = []
    pers_ranks = defaultdict(list)
    ability_ranks = defaultdict(list)
    champion_count = defaultdict(int)
    gold_curves = []            # 每局 [人均金币/轮]
    decide_times = []
    damage_rounds_total = played_rounds_total = 0
    no_damage_games = finished_early = 0
    combines_total = 0
    # 装备侧
    drops = crafts = equips = stone_triggers = lucky_eggs = 0
    stone_forms = trade_merges = 0
    games_with_stone = 0
    crafted_kinds = defaultdict(int)
    equipped_kinds = defaultdict(int)
    lineups = []                # 同阵容序列断言用
    for i in range(games):
        m = Match(seed + i, 8, rounds)
        m.run()
        r = m.result()
        rounds_full.append(r["rounds"])
        finished_early += 1 if r["finished_early"] else 0
        decide_times.extend(r["decide_times"])
        damage_rounds_total += r["rounds_with_damage"]
        played_rounds_total += r["rounds"]
        pve_rounds = r["rounds"] // 5
        if r["rounds"] - r["rounds_with_damage"] > pve_rounds:
            no_damage_games += 1
        lineups.append(tuple((b.seat, b.pers_key, b.ability) for b in m.bots))
        curve = []
        for idx in range(r["rounds"]):
            col = [b.gold_curve[idx] for b in m.bots
                   if len(b.gold_curve) > idx]
            curve.append(statistics.mean(col) if col else 0)
        gold_curves.append(curve)
        for b in m.bots:
            pers_ranks[b.pers_key].append(b.rank)
            ability_ranks[b.ability].append(b.rank)
            combines_total += b.combines
            for o in b.all_pieces():
                if o.item is not None:
                    equipped_kinds[o.item] += 1
        champion_count[r["ranking"][0].pers_key] += 1
        st = r["item_stats"]
        drops += st["drops"]
        crafts += st["crafts"]
        equips += st["equips"]
        stone_triggers += st["stone_triggers"]
        stone_forms += st["stone_forms"]
        trade_merges += st["trade_merges"]
        lucky_eggs += st["lucky_eggs"]
        games_with_stone += 1 if st["stone_triggers"] else 0
    means = {k: statistics.mean(v) for k, v in pers_ranks.items()}
    times_sorted = sorted(decide_times)
    # 金币曲线：各局按采样点取均值（局有长短，短局后段不计入分母）
    gold_snap = {}
    for cp in GOLD_CHECKPOINTS:
        col = [c[cp] for c in gold_curves if len(c) > cp]
        gold_snap[cp + 1] = statistics.mean(col) if col else 0.0
    return {
        "games": games,
        "rounds_mean": statistics.mean(rounds_full),
        "rounds_median": statistics.median(rounds_full),
        "rounds_min": min(rounds_full),
        "rounds_max": max(rounds_full),
        "finished_early": finished_early,
        "pers_means": means,
        "var_across": statistics.pvariance(means.values()),
        "ability_means": {k: statistics.mean(v)
                          for k, v in sorted(ability_ranks.items())},
        "champions": dict(champion_count),
        "gold_snap": gold_snap,
        "combines_avg": combines_total / games,
        "decide_p99": times_sorted[min(int(len(times_sorted) * 0.99),
                                       len(times_sorted) - 1)] if times_sorted else 0.0,
        "damage_ratio": damage_rounds_total / max(1, played_rounds_total),
        "no_damage_games": no_damage_games,
        "drops_avg": drops / games,
        "crafts_avg": crafts / games,
        "equips_avg": equips / games,
        "stone_triggers_total": stone_triggers,
        "stone_games": games_with_stone,
        "stone_forms": stone_forms,
        "trade_merges": trade_merges,
        "lucky_eggs": lucky_eggs,
        "equipped_kinds": dict(equipped_kinds),
        "lineups": lineups,
    }


def replay_check(seed: int, rounds: int) -> bool:
    """同种子重放一局（装备开）：淘汰顺序 + 排名 + 装备统计逐位一致。"""
    def play() -> tuple:
        m = Match(seed, 8, rounds)
        m.run()
        r = m.result()
        return (tuple((rd, b.seat) for rd, b in r["elimination_order"]),
                tuple(b.seat for b in r["ranking"]),
                tuple(sorted(r["item_stats"].items())))
    return play() == play()


def report(name: str, res: dict, rounds: int) -> None:
    print(f"\n== [{name}] {res['games']} 局 × 8 bot（上限 {rounds} 轮）==")
    print(f"  局长: 均值 {res['rounds_mean']:.1f} / 中位 {res['rounds_median']:.0f}"
          f" / 区间 [{res['rounds_min']}, {res['rounds_max']}]"
          f"（提前决出 {res['finished_early']}/{res['games']}）")
    print("  人格平均名次: " + "  ".join(
        f"{k} {v:.2f}" for k, v in sorted(res['pers_means'].items()))
        + f"  → 方差 {res['var_across']:.3f}")
    print("  金币曲线(人均): " + "  ".join(
        f"R{r}={g:.1f}" for r, g in sorted(res['gold_snap'].items())))
    print(f"  能力层名次: " + "  ".join(
        f"L{k} {v:.2f}" for k, v in res['ability_means'].items()))
    print(f"  冠军人格: " + " ".join(
        f"{k}×{v}" for k, v in sorted(res['champions'].items())))
    print(f"  场均 3合1 {res['combines_avg']:.1f}；掉血轮占比 "
          f"{res['damage_ratio']:.0%}；非野怪无掉血局 {res['no_damage_games']}；"
          f"决策 p99 {res['decide_p99']:.2f}ms")


def report_items(res: dict) -> None:
    print(f"\n-- 装备侧读数（开臂）--")
    print(f"  场均组件掉落 {res['drops_avg']:.1f} 件/局（8 人合计）→ "
          f"合成 {res['crafts_avg']:.1f} → 装备 {res['equips_avg']:.1f}")
    print(f"  进化石: 触发 {res['stone_triggers_total']} 人次"
          f"（{res['stone_games']}/{res['games']} 局出现，"
          f"{res['stone_triggers_total'] / max(1, res['games']):.2f} 次/局）；"
          f"终局仍在场的进化石形态 {res['stone_forms']}，"
          f"通信 3合1（持装备门解锁）{res['trade_merges']}")
    print(f"  终局带装分布: " + "  ".join(
        f"{items.FINISHED[k]['name']}×{v}"
        for k, v in sorted(res['equipped_kinds'].items(),
                           key=lambda kv: -kv[1])))


def main() -> None:
    ap = argparse.ArgumentParser(description="S5 装备关/开双臂实验")
    ap.add_argument("--games", type=int, default=50)
    ap.add_argument("--seed", type=int, default=100)
    ap.add_argument("--rounds", type=int, default=31)
    args = ap.parse_args()

    # 1) 装备开臂的同种子重放自检（宪法 2.2）
    items.ITEMS_ON = True
    ok = replay_check(args.seed, args.rounds)
    print(f"同种子重放自检（装备开）: {'通过（淘汰+排名+装备统计一致）' if ok else '失败！'}")
    if not ok:
        raise SystemExit(1)

    # 2) 关臂（= 现网基线语义：无掉落/无合成/通信族维持暂缓）
    items.ITEMS_ON = False
    off = run_batch(args.games, args.seed, args.rounds)
    report("装备关", off, args.rounds)

    # 3) 开臂
    items.ITEMS_ON = True
    on = run_batch(args.games, args.seed, args.rounds)
    report("装备开", on, args.rounds)
    report_items(on)
    items.ITEMS_ON = False

    # 4) 同种子同阵容断言：pers 子流与装备无关，两臂发牌必须逐位一致
    assert off["lineups"] == on["lineups"], "两臂人格/能力发牌不一致！"
    print(f"\n== 双臂对照 ==")
    print(f"  同种子同阵容序列: 一致（{args.games} 局 × 8 席 pers 子流不受装备影响）")
    print(f"  局长: {off['rounds_mean']:.1f} → {on['rounds_mean']:.1f}"
          f"（中位 {off['rounds_median']:.0f} → {on['rounds_median']:.0f}，"
          f"提前决出 {off['finished_early']} → {on['finished_early']}）")
    print(f"  金币曲线位移: " + "  ".join(
        f"R{r} {off['gold_snap'][r]:.1f}→{on['gold_snap'][r]:.1f}"
        for r in sorted(off['gold_snap'])))
    print(f"  人格方差: {off['var_across']:.3f} → {on['var_across']:.3f}")
    print(f"  场均 3合1: {off['combines_avg']:.1f} → {on['combines_avg']:.1f}"
          f"（通信族解除 −800 暂缓罚 + 装备解锁）")

    # 5) 健康线三判
    ok_len = LEN_BAND[0] <= on["rounds_mean"] <= LEN_BAND[1]
    ok_var = on["var_across"] < off["var_across"] * VARIANCE_WORSEN_LIMIT
    ok_dd = on["no_damage_games"] == 0 and off["no_damage_games"] == 0
    print(f"\n== 健康线 ==")
    print(f"  1) 局长 {on['rounds_mean']:.1f} ∈ {LEN_BAND}"
          f"  → {'PASS' if ok_len else 'FAIL'}")
    print(f"  2) 人格方差 {on['var_across']:.3f} < 关臂 {off['var_across']:.3f}"
          f"×{VARIANCE_WORSEN_LIMIT:.1f}={off['var_across'] * VARIANCE_WORSEN_LIMIT:.3f}"
          f"  → {'PASS' if ok_var else 'FAIL'}")
    print(f"  3) 无死锁（两臂非野怪无掉血局 0）  → {'PASS' if ok_dd else 'FAIL'}")
    all_ok = ok_len and ok_var and ok_dd
    print(f"== 健康线：{'全部通过' if all_ok else '存在未通过项！'} ==")
    if not all_ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
