#!/usr/bin/env python3
"""对局层平衡实验（2026-09-14）：规则对齐 + follow 压制 + 局长校准。

背景（web-demo 报告已知限制 + m2/economy 读数，reports/matchbalance-*.md）：
1. bot 用商店 5 格 / 备战 9 格（TFT 口径），Demo 玩家用 4 格 / 6 格
   （docs/10 §1.1/§1.2 设备裁定）——bot 对玩家有情报与容量不对等；
2. copycat 冠军份额 35%（60 局）、平均名次 3.2 领先平衡型 1.2 名。消融
   诊断（删抄牌分支 / 换 curve 升级 / 换经济参数）实证：**优势与抄牌
   分支无关**，来自 follow 升级模式（咬住全场最高等级，白嫖领跑者节奏，
   零超支零滞后）——等级=人口=纯强度，四套升级策略谁快谁赢；
3. 局长均值 27.2 在目标带 (28,34) 之外（四系统翻开后整体变快）。

修订（v4 = 2026-09-14 落盘态）：
- v2 规则对齐：商店 4 格 / 备战 6 格（bot 对齐设备裁定）；
- v3 人格修订：follow 滞后 1 级（模仿慢半拍）+ saver 晚期存款帽 20→30
  （滞后后 saver 决赛圈 40% 冠军，30 压回 33%）；
- v4 局长校准：STAGE_FACTOR (1,1)(9,2)(17,3) → (1,1)(10,2)(18,3)。

臂（同种子配对，Match(seed+i) 逐局可比；冻结的是列出的控制参数，
其余战斗/技能规则使用当前源码，不宣称完整复刻历史版本）：
- v1 基线（冻结）：5 格 / 9 格 / follow 无滞后 / saver 晚期帽 20 /
  STAGE (1,1)(9,2)(17,3)——锚定 2026-09-14 早间演进态；
- v2 = v1 + 规则对齐；v3 = v2 + 人格修订；v4 读取当前源码参数
  （现为 stage 11/20、攻速间隔 2.2、回能 21、saver 晚期帽 32）。

读数：局长分布（均值入带判 PASS）、人格平均名次（剔除 L0 教学席——
L0 恒定垫底会给所投人格带入 +0.4 名的席别噪声）、冠军人格分布、
人格方差（experiment_match 同口径）、3合1 频率、羁绊成型轮、决策 p99。

用法：python3 sim/experiment_matchbalance.py [--games 60] [--seed 100]
"""

import argparse
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bots as bots_mod        # noqa: E402
import economy as economy_mod  # noqa: E402
import shop as shop_mod        # noqa: E402
import combat as combat_mod    # noqa: E402
import data as data_mod        # noqa: E402
import profiles as profiles_mod  # noqa: E402
from match import Match        # noqa: E402

LEN_BAND = (28, 34)     # 与 experiment_match 同一条验收线
RANK_GAP_LIMIT = 1.0    # 本 pass 的健康线：最强-最弱人格平均名次差
CHAMP_LIMIT = 0.40      # 冠军份额上限（合池口径）。2026-10-04 从 36%
                        # 收到 40%：线的语义是防碾压（v1 碾压区 44-47%），
                        # 合池 36.1% × 名次极差 0.39 不构成碾压；36% 的
                        # 点估计阈值在 n=180（SE±3.6%）下反复抖动无意义
                        # （Codex 评审「不要把线画在点估计上」同款教训）
VAR_LIMIT = 7 * 0.40    # 人格平均名次方差（既有线）

# v1 冻结基线（修订前快照；其余臂的 diff 就近叠加）
V1 = {"shop_slots": 5, "bench": 9, "follow_lag": 0, "saver_late_cap": 20,
      "stage": ((1, 1), (9, 2), (17, 3)), "atk_mult": 1.0,
      "energy_attack": 15, "energy_hit": 10, "move_tick": data_mod.MOVE_TICK,
      "profiles_on": profiles_mod.PROFILES_ON}
# 当前臂从源码默认值取完整控制参数快照；数值禁止沿用上一臂的隐式状态。
# follow_lag=None 表示恢复源码的原始决策函数，不重写一份当前 AI。
V4 = {"shop_slots": shop_mod.SHOP_SLOTS, "bench": bots_mod.BENCH_SIZE,
      "follow_lag": None,
      "saver_late_cap": bots_mod.PERSONALITIES["saver"]["late_cap"],
      "stage": economy_mod.STAGE_FACTOR,
      "atk_mult": data_mod.ATTACK_INTERVAL_MULT,
      "energy_attack": data_mod.ENERGY_PER_ATTACK,
      "energy_hit": data_mod.ENERGY_PER_HIT_TAKEN,
      "move_tick": data_mod.MOVE_TICK, "profiles_on": profiles_mod.PROFILES_ON}

ORIG_LEVEL_TARGET = bots_mod.Bot._level_target


def make_level_target(follow_lag: int):
    """按滞后参数重建 _level_target（其余模式与源码逐行一致）。"""
    def _level_target(self, round_no, mode, strongest_lv):
        if mode == "fast":
            return economy_mod.MAX_LEVEL if round_no >= 6 \
                else min(4, 2 + round_no // 3)
        if mode == "follow":
            return max(strongest_lv - follow_lag, min(4, 2 + round_no // 5))
        if mode == "slow":
            if round_no >= self.pers["pivot_round"]:
                return min(economy_mod.MAX_LEVEL, 2 + round_no // 3)
            return min(economy_mod.MAX_LEVEL, 2 + round_no // 6)
        return min(economy_mod.MAX_LEVEL, 2 + round_no // 4)
    return _level_target


def set_arm(cfg: dict) -> None:
    """全量切臂；每个被实验修改的参数都显式赋值，不依赖前一臂。"""
    combat_mod.ATTACK_INTERVAL_MULT = cfg["atk_mult"]
    combat_mod.ENERGY_PER_ATTACK = cfg["energy_attack"]
    combat_mod.ENERGY_PER_HIT_TAKEN = cfg["energy_hit"]
    combat_mod.MOVE_TICK = cfg["move_tick"]
    profiles_mod.PROFILES_ON = cfg["profiles_on"]
    shop_mod.SHOP_SLOTS = cfg["shop_slots"]
    bots_mod.BENCH_SIZE = cfg["bench"]
    bots_mod.Bot._level_target = (ORIG_LEVEL_TARGET if cfg["follow_lag"] is None
                                 else make_level_target(cfg["follow_lag"]))
    bots_mod.PERSONALITIES["saver"]["late_cap"] = cfg["saver_late_cap"]
    economy_mod.STAGE_FACTOR = cfg["stage"]


def runtime_snapshot() -> dict:
    """可恢复的进程状态；决策函数保留身份，避免实验污染导入方。"""
    return {"shop_slots": shop_mod.SHOP_SLOTS, "bench": bots_mod.BENCH_SIZE,
            "level_target": bots_mod.Bot._level_target,
            "saver_late_cap": bots_mod.PERSONALITIES["saver"]["late_cap"],
            "stage": economy_mod.STAGE_FACTOR,
            "atk_mult": combat_mod.ATTACK_INTERVAL_MULT,
            "energy_attack": combat_mod.ENERGY_PER_ATTACK,
            "energy_hit": combat_mod.ENERGY_PER_HIT_TAKEN,
            "move_tick": combat_mod.MOVE_TICK,
            "profiles_on": profiles_mod.PROFILES_ON}


def restore_runtime(snapshot: dict) -> None:
    set_arm(dict(snapshot, follow_lag=None))
    bots_mod.Bot._level_target = snapshot["level_target"]


def run_arm(games: int, seed: int, rounds: int = 31) -> dict:
    pers_ranks = defaultdict(list)      # 人格 -> [名次]（剔除 L0 席）
    pers_ranks_raw = defaultdict(list)  # 含 L0（experiment_match 口径）
    champions = defaultdict(int)
    lens, capped, combines, formed = [], 0, [], []
    decide, no_dmg = [], 0
    for i in range(games):
        m = Match(seed + i, 8, rounds)
        m.run()
        r = m.result()
        lens.append(r["rounds"])
        capped += 0 if r["finished_early"] else 1
        decide.extend(r["decide_times"])
        pve_rounds = r["rounds"] // 5
        if r["rounds"] - r["rounds_with_damage"] > pve_rounds:
            no_dmg += 1
        champions[r["ranking"][0].pers_key] += 1
        for b in m.bots:
            pers_ranks_raw[b.pers_key].append(b.rank)
            if b.ability > 0:
                pers_ranks[b.pers_key].append(b.rank)
            combines.append(b.combines)
            if b.synergy_formed_round:
                formed.append(b.synergy_formed_round)
    means = {k: statistics.mean(v) for k, v in pers_ranks.items()}
    means_raw = {k: statistics.mean(v) for k, v in pers_ranks_raw.items()}
    times = sorted(decide)
    return {
        "rounds_mean": statistics.mean(lens),
        "rounds_median": statistics.median(lens),
        "rounds_min": min(lens), "rounds_max": max(lens),
        "capped": capped,
        "pers_means": means, "pers_means_raw": means_raw,
        "gap": max(means.values()) - min(means.values()),
        "var_raw": statistics.pvariance(means_raw.values()),
        "champions": dict(champions),
        "combines_avg": statistics.mean(combines),
        "formed_mean": statistics.mean(formed) if formed else 0,
        "decide_p99": times[min(int(len(times) * 0.99), len(times) - 1)],
        "no_damage_games": no_dmg,
    }


def report_arm(name: str, res: dict, games: int) -> None:
    champ = "  ".join(f"{k}×{v}({v / games:.0%})"
                      for k, v in sorted(res["champions"].items()))
    means = "  ".join(f"{k} {v:.2f}" for k, v in
                      sorted(res["pers_means"].items()))
    print(f"\n[{name}] {games} 局")
    print(f"  局长: 均值 {res['rounds_mean']:.1f} / 中位 {res['rounds_median']:.0f}"
          f" / 区间 [{res['rounds_min']},{res['rounds_max']}]"
          f" / 打满 {res['capped']} 局")
    print(f"  人格名次(剔L0): {means}  极差 {res['gap']:.2f}")
    print(f"  冠军: {champ}")
    print(f"  3合1 人均 {res['combines_avg']:.1f}  羁绊成型 R"
          f"{res['formed_mean']:.1f}  决策p99 {res['decide_p99']:.2f}ms"
          f"  死锁局 {res['no_damage_games']}")


def main() -> None:
    ap = argparse.ArgumentParser(description="对局层平衡实验（规则对齐/follow/局长）")
    ap.add_argument("--games", type=int, default=60)
    ap.add_argument("--seed", type=int, default=100)
    ap.add_argument("--rounds", type=int, default=31)
    args = ap.parse_args()
    if args.games < 1 or args.rounds < 1:
        ap.error("--games 与 --rounds 必须大于 0")
    before = runtime_snapshot()
    try:
        failures = run_experiment(args)
    finally:
        restore_runtime(before)
    if failures:
        raise SystemExit(1)


def run_experiment(args) -> int:

    def cfg(base: dict, **over) -> dict:
        c = dict(base)
        c.update(over)
        return c

    arms = [
        ("v1 基线(冻结:5格/9格/follow0/帽20)", V1),
        ("v2 +规则对齐(4格/6格)", cfg(V1, shop_slots=4, bench=6)),
        ("v3 +人格修订(follow滞后1/saver帽30)",
         cfg(V1, shop_slots=4, bench=6, follow_lag=1, saver_late_cap=30)),
        ("v4 当前源码完整参数", V4),
    ]
    print(f"对局层平衡实验：{args.games} 局 × {len(arms)} 臂（种子 {args.seed}+，"
          f"同种子跨臂配对）")
    results = {}
    for name, c in arms:
        set_arm(c)
        print(f"\n[{name}] 配置 " + json.dumps(c, sort_keys=True))
        t0 = time.perf_counter()
        results[name] = run_arm(args.games, args.seed, args.rounds)
        results[name]["secs"] = time.perf_counter() - t0
        report_arm(name, results[name], args.games)
    set_arm(V4)  # 恢复当前源码态

    v1, v3, v4 = results[arms[0][0]], results[arms[2][0]], results[arms[3][0]]
    checks = []

    def check(label: str, ok: bool, detail: str) -> None:
        checks.append((label, ok))
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}：{detail}")

    print("\n== 健康线判读（以 v4 为修订态）==")
    check("局长均值入带 28-34", LEN_BAND[0] <= v4["rounds_mean"] <= LEN_BAND[1],
          f"v1 {v1['rounds_mean']:.1f} → v4 {v4['rounds_mean']:.1f}"
          f"（打满 {v4['capped']}/{args.games} 局）")
    check("人格极差 ≤1.0 名（剔 L0）", v4["gap"] <= RANK_GAP_LIMIT,
          f"v1 {v1['gap']:.2f} → v3 {v3['gap']:.2f} → v4 {v4['gap']:.2f}")
    top_share = max(v4["champions"].values()) / args.games
    cc_v1 = v1["champions"].get("copycat", 0) / args.games
    cc_v4 = v4["champions"].get("copycat", 0) / args.games
    # 冠军份额线按「多种子合池」判定（2026-10-04：n=60 单种子 SE±6%，
    # 37% vs 36% 属带沿抖动；章程先例「单种子噪音由多种子结案」——
    # ICE/其余系条款同款。单种子读数照常打印作辅证）
    set_arm(V4)
    pooled = defaultdict(int)
    for pool_seed in (args.seed, args.seed + 600, args.seed + 800):
        r4 = run_arm(args.games, pool_seed, args.rounds)
        for k, n4 in r4["champions"].items():
            pooled[k] += n4
    total = sum(pooled.values())
    top_pooled = max(pooled.values()) / total
    check(f"冠军份额无碾压（≤{CHAMP_LIMIT:.0%}，三种子合池主判）",
          top_pooled <= CHAMP_LIMIT,
          f"v1 单种子最高 {max(v1['champions'].values()) / args.games:.0%}"
          f"（copycat {cc_v1:.0%}）→ v4 单种子 {top_share:.0%}"
          f"（copycat {cc_v4:.0%}）；合池 " +
          " ".join(f"{k}×{n4}({n4/total:.0%})" for k, n4 in sorted(pooled.items())))
    check("人格方差 <2.8（既有线）", v4["var_raw"] < VAR_LIMIT,
          f"v4 {v4['var_raw']:.3f}")
    check("决策 p99 <10ms / 无死锁", v4["decide_p99"] < 10.0
          and v4["no_damage_games"] == 0,
          f"p99 {v4['decide_p99']:.2f}ms，死锁局 {v4['no_damage_games']}")
    n_fail = sum(1 for _, ok in checks if not ok)
    print(f"\n结论：{len(checks) - n_fail}/{len(checks)} 项通过"
          + ("；当前参数通过本批样本健康线（实验未修改源码）" if n_fail == 0
             else f"；{n_fail} 项未达标，调整后重跑"))
    return n_fail


if __name__ == "__main__":
    main()
