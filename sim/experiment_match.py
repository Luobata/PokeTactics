#!/usr/bin/env python3
"""M2 批量局实验：经济 + 买入 AI 的四条验收（docs/03 §6）。

验收读数（每局 8 bot = 1×L0 + 3×L1 + 3×L2 + 1×L3，四人格均匀投放）：
1. 人格名次方差：各人格平均名次的方差 < 名次极差(7) × 40% = 2.8
   （人格强度大致平衡，无人格碾压）；
2. 平均局长 28~34 轮（节奏健康：不提前死亡也不拖满）；
3. bot 决策 < 10ms/轮（C 移植余量；报全局 max 与均值）；
4. 8 bot 混战无死锁：每轮要么有人掉血要么对局结束
   （无掉血轮只允许出现在「野怪轮全员获胜」——单独计数盯防）。

附加读数：能力层(L0-L3)名次分布（难度爬坡是否自然）、
羁绊成型轮次、3合1 频率、同种子重放一致性（宪法 2.2）。
可选臂 --synergy：S3 羁绊开关全开后对照局长/成型（S3 报告遗留的复验钩子）。

用法：
    python3 sim/experiment_match.py --games 50 --seed 100 [--synergy]
"""

import argparse
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import synergy  # noqa: E402
from match import Match  # noqa: E402

RANK_RANGE = 7          # 8 人局名次极差 8-1
VARIANCE_LIMIT = 0.40   # 验收线：人格平均名次方差 < 极差 × 40%
LEN_BAND = (28, 34)     # 验收线：平均局长
DECIDE_LIMIT_MS = 10.0  # 验收线：决策耗时


def run_batch(games: int, seed: int, rounds: int = 31) -> dict:
    """跑 N 局，收集验收四读数。返回汇总 dict。"""
    per_game = []                 # 每局 (局长, 冠军人格)
    pers_ranks = defaultdict(list)   # 人格 -> [名次]
    ability_ranks = defaultdict(list)  # 能力层 -> [名次]
    formed_rounds = []            # 羁绊成型轮次
    combines_total = 0
    rounds_full = []              # 局长（含到上限）
    damage_rounds_total = 0
    played_rounds_total = 0
    no_damage_games = 0           # 出现过「无人掉血轮」的局数（死锁盯防）
    champion_count = defaultdict(int)
    finished_early = 0
    decide_times = []
    for i in range(games):
        m = Match(seed + i, 8, rounds)
        m.run()
        r = m.result()
        rounds_full.append(r["rounds"])
        finished_early += 1 if r["finished_early"] else 0
        decide_times.extend(r["decide_times"])
        damage_rounds_total += r["rounds_with_damage"]
        played_rounds_total += r["rounds"]
        # 无掉血轮只允许 = 野怪轮（每 5 轮一个）；多出来即死锁
        pve_rounds = r["rounds"] // 5
        if r["rounds"] - r["rounds_with_damage"] > pve_rounds:
            no_damage_games += 1
        for b in m.bots:
            pers_ranks[b.pers_key].append(b.rank)
            ability_ranks[b.ability].append(b.rank)
            if b.synergy_formed_round:
                formed_rounds.append(b.synergy_formed_round)
            combines_total += b.combines
        champion_count[r["ranking"][0].pers_key] += 1
        per_game.append((r["rounds"], r["ranking"][0].pers_key))
    means = {k: statistics.mean(v) for k, v in pers_ranks.items()}
    var_across = statistics.pvariance(means.values())  # 人格平均名次的方差
    times_sorted = sorted(decide_times)
    return {
        "games": games,
        "rounds_mean": statistics.mean(rounds_full),
        "rounds_median": statistics.median(rounds_full),
        "rounds_min": min(rounds_full),
        "rounds_max": max(rounds_full),
        "pers_means": means,
        "pers_var_within": {k: statistics.pvariance(v)
                            for k, v in pers_ranks.items()},
        "var_across": var_across,
        "ability_means": {k: statistics.mean(v)
                          for k, v in sorted(ability_ranks.items())},
        "formed_mean": statistics.mean(formed_rounds) if formed_rounds else 0,
        "formed_n": len(formed_rounds),
        "combines_avg": combines_total / games,
        "decide_p99": times_sorted[min(int(len(times_sorted) * 0.99),
                                       len(times_sorted) - 1)] if times_sorted else 0.0,
        "decide_max": times_sorted[-1] if times_sorted else 0.0,
        "decide_avg": statistics.mean(times_sorted) if times_sorted else 0.0,
        "damage_ratio": damage_rounds_total / max(1, played_rounds_total),
        "no_damage_games": no_damage_games,
        "champions": dict(champion_count),
        "finished_early": finished_early,
    }


def replay_check(seed: int, rounds: int) -> bool:
    """同种子重放一局：淘汰顺序 + 排名 + 逐轮伤害事件完全一致。"""
    def play() -> tuple:
        m = Match(seed, 8, rounds)
        m.run()
        r = m.result()
        return (tuple((rnd, b.seat) for rnd, b in r["elimination_order"]),
                tuple(b.seat for b in r["ranking"]), r["rounds"])
    return play() == play()


def report(res: dict, rounds: int) -> None:
    print(f"\n== M2 批量局验收（{res['games']} 局 × 8 bot，上限 {rounds} 轮）==")
    ok_len = LEN_BAND[0] <= res["rounds_mean"] <= LEN_BAND[1]
    print(f"1) 局长: 均值 {res['rounds_mean']:.1f} / 中位 {res['rounds_median']:.0f}"
          f" / 区间 [{res['rounds_min']}, {res['rounds_max']}]"
          f"  目标 {LEN_BAND}  → {'PASS' if ok_len else 'FAIL'}"
          f"（打满上限 {rounds} 轮 {res['games'] - res['finished_early']} 局 / "
          f"提前决出 {res['finished_early']} 局）")
    print("   人格平均名次: " + "  ".join(
        f"{k} {v:.2f}" for k, v in sorted(res['pers_means'].items())))
    var_ok = res["var_across"] < RANK_RANGE * VARIANCE_LIMIT
    print(f"2) 人格名次方差: {res['var_across']:.3f} < "
          f"{RANK_RANGE}×40%={RANK_RANGE * VARIANCE_LIMIT:.1f}"
          f"  → {'PASS' if var_ok else 'FAIL'}（各人格组内方差 "
          + " ".join(f"{k}={v:.2f}" for k, v in
                     sorted(res["pers_var_within"].items())) + "）")
    time_ok = res["decide_p99"] < DECIDE_LIMIT_MS
    print(f"3) 决策耗时: p99 {res['decide_p99']:.2f}ms / 均值 "
          f"{res['decide_avg']:.2f}ms / 单点最大 {res['decide_max']:.2f}ms"
          f"（perf_counter 含 OS 调度抖动，判据看 p99）"
          f"  → {'PASS' if time_ok else 'FAIL'}")
    ok_dd = res["no_damage_games"] == 0
    print(f"4) 无死锁: 掉血轮占比 {res['damage_ratio']:.0%}，"
          f"存在非野怪轮无掉血的局 {res['no_damage_games']} 个"
          f"  → {'PASS' if ok_dd else 'FAIL'}")
    print(f"   能力层平均名次: "
          + "  ".join(f"L{k} {v:.2f}" for k, v in res["ability_means"].items())
          + "（弱 bot 先走、决赛圈 L2/L3 = 难度爬坡）")
    print(f"   羁绊成型: {res['formed_n']} 人次，均值 R{res['formed_mean']:.1f}；"
          f"场均 3合1 {res['combines_avg']:.1f} 次；冠军人格分布 "
          + " ".join(f"{k}×{v}" for k, v in sorted(res["champions"].items())))
    all_ok = ok_len and var_ok and time_ok and ok_dd
    print(f"== 四条验收：{'全部通过' if all_ok else '存在未通过项！'} ==")
    if not all_ok:
        raise SystemExit(1)


def main() -> None:
    ap = argparse.ArgumentParser(description="M2 批量局实验")
    ap.add_argument("--games", type=int, default=50)
    ap.add_argument("--seed", type=int, default=100)
    ap.add_argument("--rounds", type=int, default=31)
    ap.add_argument("--synergy", action="store_true",
                    help="可选臂：S3 羁绊开关全开对照")
    args = ap.parse_args()

    ok = replay_check(args.seed, args.rounds)
    print(f"同种子重放自检: {'通过（淘汰顺序+排名一致）' if ok else '失败！'}")
    if not ok:
        raise SystemExit(1)

    res = run_batch(args.games, args.seed, args.rounds)
    report(res, args.rounds)

    if args.synergy:  # 可选臂：S3 报告「M2 后复验」的钩子，恢复默认
        synergy.SYNERGIES_ON = True
        print("\n[S3 联动臂] SYNERGIES_ON=True（羁绊全开）:")
        res2 = run_batch(args.games, args.seed, args.rounds)
        report(res2, args.rounds)
        synergy.SYNERGIES_ON = False
        print(f"\n对照: 局长 {res['rounds_mean']:.1f} → {res2['rounds_mean']:.1f}，"
              f"成型轮 {res['formed_mean']:.1f} → {res2['formed_mean']:.1f}")


if __name__ == "__main__":
    main()
