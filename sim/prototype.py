#!/usr/bin/env python3
"""玩法原型：随机阵容批量对打，输出平衡性报告。

这是 PokeWalk「先仿真后落地」方法论在新项目的对应物——
设计文档里每一条数值改动，都应该能在这里几秒钟内看到几百局的影响。

用法：
    python3 sim/prototype.py --games 300 [--seed 20260913] [--size 6] [-v]
    -v 打印一场示例战斗的逐场明细
"""

import argparse
import random
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from combat import Battle  # noqa: E402
from roster import build_roster, random_comp  # noqa: E402
from data import pokedex  # noqa: E402


def run_games(games: int, size: int, seed: int, verbose: bool) -> list:
    rng = random.Random(seed)
    results = []
    for i in range(games):
        comp_a, comp_b = random_comp(rng, size), random_comp(rng, size)
        battle = Battle(comp_a, comp_b, rng)
        res = battle.run()
        res["comp"] = (comp_a, comp_b)
        results.append(res)
        if verbose and i == 0:
            print("== 示例战斗 ==")
            for side, comp in zip(("A", "B"), (comp_a, comp_b)):
                print(f"  {side}: {', '.join(map(repr, comp))}")
            print("  事件流（渲染回放契约）：")
            for ev in battle.events:
                print("   ", _fmt_event(battle, ev))
            print(f"  胜者: {res['winner']}  时长: {res['duration']:.1f}s  "
                  f"存活: {res['survivors']}")
    return results


def _fmt_event(battle: Battle, ev: tuple) -> str:
    t, kind = ev[0], ev[1]
    name = lambda i: battle.units[i].piece.name  # noqa: E731
    if kind == "deploy":
        return f"[{t:5.1f}] {name(ev[2])} 落位 {ev[3]}"
    if kind == "move":
        return f"[{t:5.1f}] {name(ev[2])} 移动到 {ev[3]}"
    if kind == "attack":
        return f"[{t:5.1f}] {name(ev[2])} 普攻 {name(ev[3])} -{ev[4]}"
    if kind == "cast":
        eff = {0.5: "效果不佳", 2.0: "效果拔群", 4.0: "效果绝群"}.get(
            ev[5], f"x{ev[5]}")
        outcome = "未命中" if ev[6] == 0 else f"-{ev[6]}{(' ' + eff) if ev[5] != 1 else ''}"
        return f"[{t:5.1f}] {name(ev[2])} 放出 {ev[4]} → {name(ev[3])} {outcome}"
    if kind == "die":
        return f"[{t:5.1f}] {name(ev[2])} 倒下"
    return f"[{t:5.1f}] end {ev[2]}"


def check_determinism(size: int, seed: int) -> None:
    """同种子从头重放一局，比对事件流——双端渲染同步契约的最小验证。"""
    def play() -> list:
        rng = random.Random(seed)
        battle = Battle(random_comp(rng, size), random_comp(rng, size), rng)
        battle.run()
        return battle.events
    ok = play() == play()
    print(f"确定性自检: {'通过（同种子同事件流）' if ok else '失败！'}")
    if not ok:
        raise SystemExit(1)


def report(results: list, size: int) -> None:
    games = len(results)
    wins = Counter(r["winner"] for r in results)
    draws = wins.get(None, 0)
    print(f"\n== 平衡报告（{games} 场，{size}v{size}）==")
    print(f"A 胜 {wins.get(0, 0)} | B 胜 {wins.get(1, 0)} | 平/超时 {draws} "
          f"({draws / games:.0%})")
    durations = [r["duration"] for r in results]
    print(f"战斗时长 中位 {statistics.median(durations):.1f}s / "
          f"均值 {statistics.mean(durations):.1f}s / 最长 {max(durations):.1f}s")

    # 属性维度：队伍里每出现一只该属性棋子记一次（胜负跟队）
    type_w = defaultdict(lambda: [0, 0])  # type -> [参与局, 胜局]
    for r in results:
        for side in (0, 1):
            types = {t for p in r["comp"][side] for t in p.types}
            for t in types:
                type_w[t][0] += 1
                type_w[t][1] += 1 if r["winner"] == side else 0
    rows = sorted(type_w.items(), key=lambda kv: kv[1][1] / kv[1][0],
                  reverse=True)
    print("属性胜率（按队伍出现计）:")
    for t, (n, w) in rows:
        print(f"  {t:<9} {w / n:6.1%}  (n={n})")

    # 棋子维度：平均伤害占比 + 胜率
    u_stat = defaultdict(lambda: [0, 0.0, 0, 0])  # 名 -> [局, 累计伤害, 胜, 大招]
    for r in results:
        team_dmg = {tm: sum(u.damage_dealt for u in r["units"] if u.team == tm)
                    for tm in (0, 1)}
        for u in r["units"]:
            s = u_stat[u.piece.name]
            s[0] += 1
            s[1] += (u.damage_dealt / max(1, team_dmg[u.team]))
            s[2] += 1 if r["winner"] == u.team else 0
            s[3] += u.casts
    print("棋子伤害占比 TOP10（占己队总伤害的比例，粗平衡信号）:")
    for name, (n, share, w, casts) in sorted(
            u_stat.items(), key=lambda kv: kv[1][1] / kv[1][0],
            reverse=True)[:10]:
        print(f"  {name:<6} 平均占比 {share / n:6.1%}  胜率 {w / n:5.1%}  "
              f"场均大招 {casts / n:.2f}")
    print("\n判读：单只占比 >25% 或属性胜率极化 >70% 就是危险信号；"
          "平局多说明输出不足或全远程龟缩。")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=300)
    ap.add_argument("--size", type=int, default=6, help="每队棋子数")
    ap.add_argument("--seed", type=int, default=20260913)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    roster = build_roster()
    total = sum(len(v) for v in roster.values())
    print(f"棋子池：{total} 只（" +
          ", ".join(f"{t}费 {len(v)}" for t, v in sorted(roster.items())) + "）")
    print(f"示例对局 seed={args.seed}")
    check_determinism(args.size, args.seed)
    results = run_games(args.games, args.size, args.seed, args.verbose)
    report(results, args.size)


if __name__ == "__main__":
    main()
