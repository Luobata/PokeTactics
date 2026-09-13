#!/usr/bin/env python3
"""档位重排实验：旧档位（按进化阶段）vs 新档位（按形态 BST）。

背景（S2，2026-09-13）：等级拍平（S1）后强度只来自种族值差，旧规则
「档位=进化阶段 + 无进化者单独阈值」造成阶段≠强度的双向错位——
三段线终点大针蜂(385)定 3 费、两段线终点风速狗(555)只定 2 费。
roster.py 已改为按形态自身 BST 分档（阈值 365/500），本脚本对照两种分法。

方法：84 只全池按 BST 升序两两配对，3v3 同种镜像对打 N 局/对
（双方轮流占据 A/B 位，抵消部署先手差），得到一份共享对打矩阵；
旧/新两种分档只是对同一份矩阵的两种分组，差异全部来自分组而非战斗运气。

指标：
1. 档位同质化：各档内 BST 极差/方差/均值（同费棋子的面板离散度）；
2. 「同费=同强度」：档内每只棋子对同档同伴的平均胜率（平局记 0.5），
   带宽 = max−min，越窄 = 花同样的钱买到的强度越等价；
3. 跨档单调性：低档 vs 高档的平均胜率应单调下降（档位=强度排序未被破坏）；
4. 回归：结尾做同种子重放比对（确定性条款，宪法 2.2）。

用法：
    python3 sim/experiment_tiering.py [--duels 12] [--seed 20260913]
"""

import argparse
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from combat import Battle  # noqa: E402
from data import pokedex  # noqa: E402
from roster import build_roster  # noqa: E402

# ---- 旧档位规则复刻（roster.py 2026-09-13 BST 重写前的逻辑，仅供对照）----
# 多段族按进化阶段（血缘深度封顶 3 费）；无进化者走单独 BST 阈值。
OLD_SINGLE_STAGE_BST = (430, 500)


def old_tier(sid: int, dex) -> int:
    if len(dex.family_of(sid)) > 1:
        return min(dex.stage_of(sid), 3)
    bst = dex.bst(sid)
    return 1 if bst < OLD_SINGLE_STAGE_BST[0] else (
        3 if bst >= OLD_SINGLE_STAGE_BST[1] else 2)


def _pair_seed(base: int, i: int, j: int, g: int) -> int:
    """(i, j, g) → 不冲突的整数种子（i、j < 128，g < 128）。"""
    return (base << 21) + (i << 14) + (j << 7) + g


def duel_matrix(pieces: list, duels: int, seed: int) -> dict:
    """全池两两对打一次：{(i, j): i 方得分率}。i<j，得分率∈[0,1]，平局 0.5。"""
    matrix = {}
    for i in range(len(pieces)):
        for j in range(i + 1, len(pieces)):
            score = 0.0  # i 方累计得分（胜 1 / 平 0.5）
            for g in range(duels):
                rng = random.Random(_pair_seed(seed, i, j, g))
                a, b = (i, j) if g % 2 == 0 else (j, i)  # 轮流占 A/B 位
                res = Battle([pieces[a]] * 3, [pieces[b]] * 3, rng).run()
                if res["winner"] is None:
                    score += 0.5
                else:  # i 得分当且仅当 i 所在的一队获胜
                    i_team = 0 if a == i else 1
                    score += 1.0 if res["winner"] == i_team else 0.0
            matrix[(i, j)] = score / duels
    return matrix


def _pair_score(matrix: dict, i: int, j: int) -> float:
    return matrix[(i, j)] if i < j else 1.0 - matrix[(j, i)]


def tier_report(label: str, tier_of: dict, bsts: dict,
                pieces: list, matrix: dict) -> dict:
    """按一种分档打印指标：BST 同质化 + 档内战胜率带宽 + 跨档单调性。"""
    print(f"\n[{label}]")
    avg_by_tier = {}
    for t in (1, 2, 3):
        idx = [i for i in range(len(pieces)) if tier_of[i] == t]
        vals = [bsts[i] for i in idx]
        # 档内每只棋子对同档同伴的平均胜率
        avg = {i: statistics.mean(_pair_score(matrix, i, j)
                                  for j in idx if j != i) for i in idx}
        avg_by_tier[t] = avg
        if not idx:
            continue
        lo, hi = min(avg, key=avg.get), max(avg, key=avg.get)
        # 档内最悬殊的单个对位
        worst = min(((i, j) for x, i in enumerate(idx) for j in idx[x + 1:]),
                    key=lambda p: _pair_score(matrix, *p))
        print(f"  {t}费: {len(idx):2d} 只  BST {min(vals)}~{max(vals)}"
              f"（极差 {max(vals) - min(vals):3d}，方差 {statistics.pvariance(vals):5.0f}，"
              f"均值 {statistics.mean(vals):.0f}）")
        print(f"        内战带宽 {avg[hi] - avg[lo]:5.1%}（{pieces[lo].name} "
              f"{avg[lo]:.0%} ~ {pieces[hi].name} {avg[hi]:.0%}）；"
              f"最悬殊对位 {pieces[worst[0]].name} vs {pieces[worst[1]].name} "
              f"{_pair_score(matrix, *worst):.0%}")
    print("  跨档平均胜率（低费方视角，应单调下降）:", end="")
    for lo_t, hi_t in ((1, 2), (1, 3), (2, 3)):
        games = [(_pair_score(matrix, i, j), i)
                 for i in avg_by_tier[lo_t] for j in avg_by_tier[hi_t]]
        rate = statistics.mean(s for s, _ in games)
        print(f"  {lo_t}费vs{hi_t}费 {rate:.0%}", end=";")
    print()
    return avg_by_tier


def check_determinism(pieces: list, seed: int) -> None:
    """同种子重放比对：固定序列抽队打 4 场，跑两遍比对战果指纹（宪法 2.2）。"""
    def play() -> list:
        rng = random.Random(seed)
        out = []
        for _ in range(4):
            comp_a = [rng.choice(pieces) for _ in range(6)]
            comp_b = [rng.choice(pieces) for _ in range(6)]
            res = Battle(comp_a, comp_b, rng).run()
            out.append((res["winner"], round(res["duration"], 1),
                        len(res["units"]), sum(len(u.piece.types) for u in res["units"])))
        return out
    ok = play() == play()
    print(f"\n确定性自检: {'通过（同种子同战果指纹）' if ok else '失败！'}")
    if not ok:
        raise SystemExit(1)


import synergy as _syn
_syn.SYNERGIES_ON = False  # 本报告基线建立于羁绊关（2026-09-14 起默认开）


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--duels", type=int, default=12, help="每对棋子的对打局数")
    ap.add_argument("--seed", type=int, default=20260913)
    args = ap.parse_args()

    dex = pokedex()
    roster = build_roster()
    pieces = sorted((p for ps in roster.values() for p in ps),
                    key=lambda p: (dex.bst(p.species_id), p.name))
    bsts = {i: dex.bst(p.species_id) for i, p in enumerate(pieces)}
    n_pairs = len(pieces) * (len(pieces) - 1) // 2
    print(f"档位重排实验：84 只全池两两对打，{n_pairs} 对 × {args.duels} 局"
          f"（3v3 同种镜像，seed={args.seed}）")

    matrix = duel_matrix(pieces, args.duels, args.seed)

    old = {i: old_tier(p.species_id, dex) for i, p in enumerate(pieces)}
    new = {i: p.tier for i, p in enumerate(pieces)}  # roster 新规则（按 BST）
    report_old = tier_report("旧档位 · 按进化阶段（复刻）", old, bsts, pieces, matrix)
    report_new = tier_report("新档位 · 按形态自身 BST（roster 现行）", new, bsts, pieces, matrix)

    # 汇总：三档带宽的均值变化（同费=同强度的改善量）
    def mean_bw(report: dict) -> float:
        return statistics.mean(max(a.values()) - min(a.values())
                               for a in report.values() if a)
    print(f"\n档内胜率带宽均值（三档平均）：旧 {mean_bw(report_old):.1%} → "
          f"新 {mean_bw(report_new):.1%}")
    print("判读：新档位应同时满足——各档 BST 极差全面收窄、带宽收窄、"
          "跨档胜率仍单调（档位=强度的排序不变）。")
    check_determinism(pieces, args.seed)


if __name__ == "__main__":
    main()
