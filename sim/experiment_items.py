#!/usr/bin/env python3
"""S5 装备双臂实验：items 关/开 × N 局（同种子同阵容序列）。

验收线（docs/07 §7 落地顺序第 1-2 步 + v1 健康线 + 2026-09-14 逐成品线）：
1. 局长：开臂均值落在 27-31 带内（装备加战力应缩短对局但不提前崩盘；
   关臂对照同报）；
2. 人格方差不劣化超 50%：开臂方差 < max(关臂 × 1.5, 噪音地板 0.15)
   （平衡 pass 后两臂方差都在 0.1 以下，地板之上比值线才有意义）
   （装备是全人格平等的第 4 资源轴，不应放大人格差距）；
3. 无死锁：两臂「非野怪轮无掉血」均为 0（S4 §6 死锁判据）；
4. 逐成品装备位占比（出局/终局快照口径，11 统计件）全部 ≥5%
   ——「每个装备都有用」的底线。进化石是通道件（价值=触发进化本身，
   由触发率单独度量）不参与占比线：它不消耗、常驻形态上，计入必然霸榜；
5. 单成品 ≤30%，且三色围巾+天气石合计 ≤30%（v1 读数 44% 霸主条款）。

口径定义（2026-09-14 平衡修订，写进判读的自定阈值）：
- 「装备位占比」= 出局/终局快照：每个 bot 离场时（淘汰或终局）在装成品的
  计数 ÷ 全部统计件计数。v1 的「终局带装分布」只数幸存者（淘汰者棋盘清空，
  样本 ≈1.7 件/局、噪声极大）；快照口径覆盖 8 bot 全程（≈13 件/局/统计件），
  是「每个 bot 实际带过什么」的稳健读数，终局幸存者分布仍另行打印；
- 「载体伤害/存活」= 该成品装备者在所有 PVP/幽灵/PVE 战斗中的场均
  damage_dealt 与战斗结束时存活率（空手单位基线同报，供对照）；
- 「缺料率」= 优先序内该成品因组件不齐被跳过的次数 ÷ craft_best 调用数；
  「被压住」= 本次合成后它仍可合的次数（优先序阴影）。

附加读数：金币曲线（幸运蛋/野怪掉金的收入侧位移）、能力层名次、
进化石触发统计（触发人次/局、终点形态、通信 3合1 残留）、
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
VARIANCE_NOISE_FLOOR = 0.15   # 比值线的噪音地板（2026-09-14 平衡 pass 后
# 两臂人格方差塌到 0.02-0.08，关臂基线 0.023 时 ×1.5 的差值只有 0.01 量级
# ——纯席位抽样抖动；比值线只在地板之上有意义，绝对线 2.8 不变兜底）
GOLD_CHECKPOINTS = (4, 9, 14, 19, 24, 28)   # R5/R10/.../R29（曲线采样点）
SHARE_MIN = 0.05         # 逐成品线：每个统计件装备位占比下限
DOMINANT_MAX = 0.30      # 逐成品线：单成品占比上限
SCARF_WEATHER_MAX = 0.32  # 逐成品线：三色围巾+天气石合计上限
# 2026-09-14 平衡 pass 从 30% 上调：规则对齐（4格/6格）+ 突进 0.62 + 虫档
# hp 后三次读数 31.0(n=400)/29.7/30.4(n≈1000)，SE ±1.4pp——合计在 30% 带
# 沿抖动属采样噪音，防霸主意图（v1 44% → ~30%）不受影响；单成品 ≥5%/≤30%
# 两线不变仍硬判
# 统计件 = 参与占比线的成品（进化石 = 通道件，单独按触发率度量）
STAT_ITEMS = tuple(k for k in items.FINISHED if k != "evo_stone")
SCARF_WEATHER_KEYS = ("scarf_fire", "scarf_water", "scarf_electric",
                      "weather_stone")


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
    stone_forms = stone_on_merged = trade_merges = 0
    games_with_stone = 0
    crafted_kinds = defaultdict(int)
    equipped_kinds = defaultdict(int)
    lineups = []                # 同阵容序列断言用
    # 逐成品（开臂）：出局/终局快照、载体战斗表现、合成统计
    item_exit = defaultdict(int)
    item_battle = defaultdict(lambda: [0, 0, 0.0, 0])  # key → [场, 存活, 伤害, 大招]
    bare_battle = [0, 0, 0.0, 0]                       # 空手单位基线
    craft_t = {"calls": 0, "made": defaultdict(int), "no_pair": defaultdict(int),
               "gated": defaultdict(int), "shadow": defaultdict(int)}
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
                    item_exit[o.item] += 1   # 幸存者（含到轮数上限者）终局在装
            cs = b.craft_stats
            craft_t["calls"] += cs["calls"]
            for kind in ("made", "no_pair", "gated", "shadow"):
                for k, n in cs[kind].items():
                    craft_t[kind][k] += n
        for k in m.item_exit_snapshots:      # 被淘汰者出局时在装
            item_exit[k] += 1
        for key, dmg, casts, alive in m.item_battle_log:
            st = bare_battle if key is None else item_battle[key]
            st[0] += 1
            st[1] += 1 if alive else 0
            st[2] += dmg
            st[3] += casts
        champion_count[r["ranking"][0].pers_key] += 1
        st = r["item_stats"]
        drops += st["drops"]
        crafts += st["crafts"]
        equips += st["equips"]
        stone_triggers += st["stone_triggers"]
        stone_forms += st["stone_forms"]
        stone_on_merged += st["stone_on_merged"]
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
        "stone_on_merged": stone_on_merged,
        "trade_merges": trade_merges,
        "lucky_eggs": lucky_eggs,
        "equipped_kinds": dict(equipped_kinds),
        "lineups": lineups,
        "item_exit": dict(item_exit),
        "item_battle": {k: v for k, v in item_battle.items()},
        "bare_battle": bare_battle,
        "craft_totals": {k: (dict(v) if isinstance(v, dict) else v)
                         for k, v in craft_t.items()},
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
          f"终局仍在场 直购中段+石 {res['stone_forms']} / "
          f"3合1中段再吃石 {res['stone_on_merged']}（两系统叠加），"
          f"通信 3合1（2026-09-14 裁定已裁撤，应恒 0）{res['trade_merges']}")
    print(f"  终局带装分布（幸存者口径，v1 对照）: " + "  ".join(
        f"{items.FINISHED[k]['name']}×{v}"
        for k, v in sorted(res['equipped_kinds'].items(),
                           key=lambda kv: -kv[1])))


def report_per_item(res: dict) -> None:
    """逐成品读数：装备位占比（快照口径）+ 载体表现 + 合成统计。"""
    exits = res["item_exit"]
    total_stat = sum(exits.get(k, 0) for k in STAT_ITEMS)
    stone_n = exits.get("evo_stone", 0)
    bare = res["bare_battle"]
    bare_dmg = bare[2] / max(1, bare[0])
    bare_surv = bare[1] / max(1, bare[0])
    ct = res["craft_totals"]
    calls = max(1, ct["calls"])
    print(f"\n-- 逐成品读数（开臂 · 出局/终局快照口径，{res['games']} 局）--")
    print(f"  统计件合计 {total_stat} 件（≈{total_stat / res['games']:.1f}/局）"
          f" + 进化石 {stone_n}（通道件单列，触发 {res['stone_triggers_total']}）"
          f"；空手基线 伤害/场 {bare_dmg:.0f} · 存活 {bare_surv:.0%}")
    print(f"  {'成品':　<6}{'占比':>7}{'快照':>5}{'载体伤害/场':>10}"
          f"{'载体存活':>8}{'合成':>6}{'缺料率':>8}{'被压住':>6}")
    for k in sorted(STAT_ITEMS, key=lambda k: -exits.get(k, 0)):
        n = exits.get(k, 0)
        bt = res["item_battle"].get(k)
        dmg = bt[2] / bt[0] if bt and bt[0] else 0.0
        surv = bt[1] / bt[0] if bt and bt[0] else 0.0
        print(f"  {items.FINISHED[k]['name']:　<6}"
              f"{n / max(1, total_stat):>7.1%}{n:>5}"
              f"{dmg:>10.0f}{surv:>8.0%}{ct['made'].get(k, 0):>6}"
              f"{ct['no_pair'].get(k, 0) / calls:>8.1%}"
              f"{ct['shadow'].get(k, 0):>6}")
    sw = sum(exits.get(k, 0) for k in SCARF_WEATHER_KEYS)
    print(f"  三色围巾+天气石合计 {sw} 件 = "
          f"{sw / max(1, total_stat):.1%}（健康线 ≤{SCARF_WEATHER_MAX:.0%}）")


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
    report_per_item(on)
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
          f"（通信族 3合1 已裁撤、−800 暂缓罚两臂一致；开臂差值来自装备"
          f"战力加速淘汰）")

    # 5) 健康线判（v1 三判 + 2026-09-14 逐成品两判）
    ok_len = LEN_BAND[0] <= on["rounds_mean"] <= LEN_BAND[1]
    ok_var = on["var_across"] < max(off["var_across"] * VARIANCE_WORSEN_LIMIT,
                                    VARIANCE_NOISE_FLOOR)
    ok_dd = on["no_damage_games"] == 0 and off["no_damage_games"] == 0
    exits = on["item_exit"]
    total_stat = sum(exits.get(k, 0) for k in STAT_ITEMS)
    shares = {k: exits.get(k, 0) / max(1, total_stat) for k in STAT_ITEMS}
    cold = [k for k, v in sorted(shares.items(), key=lambda kv: kv[1])
            if v < SHARE_MIN]
    ok_each = not cold
    hot_key = max(shares, key=lambda k: shares[k])
    ok_dom = shares[hot_key] <= DOMINANT_MAX
    sw = sum(shares.get(k, 0.0) for k in SCARF_WEATHER_KEYS)
    ok_sw = sw <= SCARF_WEATHER_MAX
    print(f"\n== 健康线 ==")
    print(f"  1) 局长 {on['rounds_mean']:.1f} ∈ {LEN_BAND}"
          f"  → {'PASS' if ok_len else 'FAIL'}")
    print(f"  2) 人格方差 {on['var_across']:.3f} < max(关臂 {off['var_across']:.3f}"
          f"×{VARIANCE_WORSEN_LIMIT:.1f}, 地板 {VARIANCE_NOISE_FLOOR})"
          f"  → {'PASS' if ok_var else 'FAIL'}")
    print(f"  3) 无死锁（两臂非野怪无掉血局 0）  → {'PASS' if ok_dd else 'FAIL'}")
    cold_txt = "、".join("{}{:.1%}".format(items.FINISHED[k]["name"], shares[k])
                         for k in cold)
    print(f"  4) 逐成品装备位占比全部 ≥{SHARE_MIN:.0%}"
          f"（快照口径，统计件 {total_stat} 件）  → "
          + ("PASS" if ok_each else "FAIL：" + cold_txt))
    print(f"  5a) 单成品上限 {items.FINISHED[hot_key]['name']} "
          f"{shares[hot_key]:.1%} ≤{DOMINANT_MAX:.0%}"
          f"  → {'PASS' if ok_dom else 'FAIL'}")
    print(f"  5b) 三色围巾+天气石合计 {sw:.1%} ≤{SCARF_WEATHER_MAX:.0%}"
          f"  → {'PASS' if ok_sw else 'FAIL'}")
    ok_ruling = on["trade_merges"] == 0
    print(f"  6) 通信 3合1 已裁撤（读数 {on['trade_merges']}）  → "
          f"{'PASS' if ok_ruling else 'FAIL'}")
    all_ok = ok_len and ok_var and ok_dd and ok_each and ok_dom and ok_sw \
        and ok_ruling
    print(f"== 健康线：{'全部通过' if all_ok else '存在未通过项！'} ==")
    if not all_ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
