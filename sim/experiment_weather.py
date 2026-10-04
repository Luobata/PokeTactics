#!/usr/bin/env python3
"""天气/场地数值臂 对照实验（S11，docs/05-weather.md）。

回答：docs/05 §5 开放问题 1——±20% 的天气乘区是「TFT 海克斯级转型动力」
还是「数值噪音」？四天气 × 随机阵容带宽 + 定向对位位移来量化。

方法论（复用克制/近战实验模板，一处关键加强）：
- 阵容与战斗随机源分离：comp 用独立 Random(seed) 生成（与模板不同——模板
  里战斗与阵容共用 rng，若某臂伤害结算改变 rng 消耗量，后续阵容序列会跨臂
  漂移；本实验每场战斗用 seed 派生的独立 rng，跨臂阵容序列严格逐场一致，
  main() 里有显式断言自检）；
- 每臂 Battle(weather_name=...) 独立设置天气（combat.py 预埋接线）；
- 定向对位用固定种子序列（9000+i），跨天气臂可比。

边界：沙暴/冰雹的全局掉血本阶段未实现（weather.py 文件头），故本实验测的是
纯乘区效应；「冰雹 +25% 冰」在当前池内零载体（唯一冰系拉普拉斯的招牌是
水炮，冰雹臂读数应与无天气逐场一致——这本身是数值臂的发现之一）。

用法：
    python3 sim/experiment_weather.py [--games 1000] [--seed 11] [--pairs 200]
"""

import argparse
import random
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from combat import Battle  # noqa: E402
import weather  # noqa: E402
from roster import build_roster, random_comp  # noqa: E402

ARMS = [
    (None, "无天气"),
    ("sun", "晴"),
    ("rain", "雨"),
    ("sand", "沙暴"),
    ("hail", "冰雹"),
]
MIN_SAMPLE = 40        # 属性出现次数低于此不进带宽统计
KEY_TYPES = ("FIRE", "WATER", "GRASS", "GROUND", "ROCK")  # 位移重点观察系
# 健康线（判读用）：
#   1) 全局不失控：任一天气臂属性胜率 ≤65%，随机臂胜者翻转率 ≤2%
#      （天气不得把随机环境的任何系推出克制实验的极化警戒线）；
#   2) 有效：干净 2x 对位（水vs火）的晴/雨摆幅 8~20pp——低于 8pp 是噪音、
#      高于 20pp 过强；
#   3) 不越权：纯属性队对撞（4x 相对克制差）不因天气翻转——天气是倾斜不是
#      免死金牌，转型方向仍需尊重克制表。
TYPE_CAP = 0.65
FLIP_CAP = 0.02
SWING_OK = (0.08, 0.20)
# 定向队伍（满编最强 6 只 = 已成型 committed 阵容；招式全吃天气乘区）
FIRE_TEAM = ("喷火龙", "风速狗", "九尾", "火伊布", "火恐龙", "六尾")
WATER_TEAM = ("水箭龟", "哥达鸭", "宝石海星", "水伊布", "暴鲤龙", "拉普拉斯")


def battle_rng(seed: int, game: int) -> random.Random:
    """每场战斗的独立 rng：种子 = 主种子派生 + 场次，跨臂同场次同种子。"""
    return random.Random(seed * 1_000_003 + game)


def random_metrics(games: int, size: int, seed: int, weather_name) -> dict:
    """随机 6v6 批量指标。comp_rng 与战斗 rng 分离 → 跨臂阵容序列逐场一致。"""
    comp_rng = random.Random(seed)  # 只喂 random_comp，绝不被战斗消耗
    ab, durs, winners = Counter(), [], []
    type_w = defaultdict(lambda: [0, 0])
    head_comps = []  # 前 5 场阵容快照，供跨臂一致性断言
    for i in range(games):
        comp_a, comp_b = random_comp(comp_rng, size), random_comp(comp_rng, size)
        if i < 5:
            head_comps.append(([p.name for p in comp_a], [p.name for p in comp_b]))
        res = Battle(comp_a, comp_b, battle_rng(seed, i),
                     weather_name=weather_name).run()
        ab[res["winner"]] += 1
        durs.append(res["duration"])
        winners.append(res["winner"])
        for side, comp in ((0, comp_a), (1, comp_b)):
            for t in {t for p in comp for t in p.types}:
                type_w[t][0] += 1
                type_w[t][1] += 1 if res["winner"] == side else 0
    rates = {t: w / n for t, (n, w) in type_w.items() if n >= MIN_SAMPLE}
    return {
        "ab": (ab[0], ab[1], ab[None]),
        "median_dur": statistics.median(durs),
        "max_dur": max(durs),
        "rates": rates,
        "bandwidth": max(rates.values()) - min(rates.values()),
        "winners": winners,
        "head_comps": head_comps,
    }


def _piece_by_name(name: str):
    roster = build_roster()
    return next(p for ps in roster.values() for p in ps if p.name == name)


def pair_winrate(name_a: str, name_b: str, games: int, weather_name,
                 base_seed: int = 9000) -> float:
    """同种 6 连对位：返回 A 方胜率。固定种子序列，跨天气臂可比。"""
    pa, pb = _piece_by_name(name_a), _piece_by_name(name_b)
    win_a = sum(
        1 for i in range(games)
        if Battle([pa] * 6, [pb] * 6, random.Random(base_seed + i),
                  weather_name=weather_name).run()["winner"] == 0)
    return win_a / games


def team_winrate(names_a: tuple, names_b: tuple, games: int, weather_name,
                 base_seed: int = 9500) -> float:
    """混编队对位（火系队 vs 水系队翻转检验）：返回 A 队胜率。"""
    ta = [_piece_by_name(n) for n in names_a]
    tb = [_piece_by_name(n) for n in names_b]
    win_a = sum(
        1 for i in range(games)
        if Battle(ta, tb, random.Random(base_seed + i),
                  weather_name=weather_name).run()["winner"] == 0)
    return win_a / games


import synergy as _syn
_syn.SYNERGIES_ON = False  # 本报告基线建立于羁绊关（2026-09-14 起默认开）
# 2026-09-14 成套翻开后钉关保基线（与 tiering/effectiveness 同款）：齐射
# 对 6 连单色队有克制不对称放大（水箭龟×6 的 WATER 齐射 2x 打火队 →
# 水vs火锚 62%→100%），本表口径为纯天气乘区，钉住三系统
import combo as _cb, items as _it, status as _st
_cb.COMBOS_ON = False; _it.ITEMS_ON = False; _st.STATUS_ON = False
import profiles as _pf
_pf.PROFILES_ON = False  # R1 单体档案（2026-09-15）：钉关保基线（胡地建档影响近远锚点）


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=1000)
    ap.add_argument("--size", type=int, default=6)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--pairs", type=int, default=200)
    args = ap.parse_args()

    # 确定性自检 1：同臂同参数重跑读数一致（宪法 2.2）
    m1 = random_metrics(80, args.size, args.seed, "sun")
    m2 = random_metrics(80, args.size, args.seed, "sun")
    det_ok = (m1["ab"], m1["median_dur"], m1["rates"], m1["winners"]) == \
             (m2["ab"], m2["median_dur"], m2["rates"], m2["winners"])
    print(f"确定性自检（晴臂 80 场重跑）: {'通过' if det_ok else '失败！'}")
    if not det_ok:
        raise SystemExit(1)

    print(f"天气实验：{args.games} 场随机 {args.size}v{args.size} × {len(ARMS)} 臂"
          f" + 定向对位各 {args.pairs} 场（seed={args.seed}，"
          f"沙暴/冰雹掉血未实现=纯乘区臂）")

    rows = {}
    for name, label in ARMS:
        m = random_metrics(args.games, args.size, args.seed, name)
        rows[name] = m
        top = max(m["rates"].items(), key=lambda kv: kv[1])
        bot = min(m["rates"].items(), key=lambda kv: kv[1])
        print(f"\n[{label}]  A/B/平 {m['ab'][0]}/{m['ab'][1]}/{m['ab'][2]}  "
              f"时长中位 {m['median_dur']:.1f}s / 最长 {m['max_dur']:.1f}s")
        print(f"  属性胜率带宽 {m['bandwidth']:.1%}（最高 {top[0]} {top[1]:.0%} / "
              f"最低 {bot[0]} {bot[1]:.0%}，n≥{MIN_SAMPLE} 的 {len(m['rates'])} 系）")
        focus = "  ".join(f"{t} {m['rates'][t]:.0%}" for t in KEY_TYPES
                          if t in m["rates"])
        print(f"  重点系：{focus}")

    # 确定性自检 2：跨臂阵容序列逐场一致（前 5 场快照比对）
    ref = rows[None]["head_comps"]
    seq_ok = all(rows[w]["head_comps"] == ref for w, _ in ARMS)
    print(f"\n跨臂阵容序列一致性自检（前 5 场快照）: {'通过' if seq_ok else '失败！'}")
    if not seq_ok:
        raise SystemExit(1)

    # 随机臂胜者翻转场数（vs 无天气臂同场次）——「全局不失控」的直接读数
    print(f"\n== 随机臂胜者翻转场数（vs 无天气臂，共 {args.games} 场）==")
    flips = {}
    for name, label in ARMS[1:]:
        n_flip = sum(1 for a, b in zip(rows[None]["winners"], rows[name]["winners"])
                     if a != b)
        flips[name] = n_flip / args.games
        print(f"  {label}: {n_flip} 场（{flips[name]:.1%}）")

    # 位移表：各天气臂重点系胜率相对无天气臂的位移（百分点）
    print("\n== 位移表（随机臂 vs 无天气臂，正=该系更爱赢，单位 pp）==")
    print("  臂   " + "".join(f"{t:>8}" for t in KEY_TYPES) + "   带宽Δ   时长Δ")
    for name, label in ARMS[1:]:
        cells = []
        for t in KEY_TYPES:
            if t in rows[name]["rates"] and t in rows[None]["rates"]:
                cells.append(
                    f"{(rows[name]['rates'][t] - rows[None]['rates'][t]) * 100:+8.1f}")
            else:
                cells.append(f"{'—':>8}")
        bw_d = (rows[name]["bandwidth"] - rows[None]["bandwidth"]) * 100
        dur_d = rows[name]["median_dur"] - rows[None]["median_dur"]
        print(f"  {label}  " + "".join(cells) + f"   {bw_d:+5.1f}  {dur_d:+5.1f}s")

    # 定向对位
    print(f"\n== 定向对位（各 {args.pairs} 场，固定种子序列跨臂可比）==")
    pair_rows = []
    for label, kind, arms in [
        ("水箭龟×6 vs 喷火龙×6", "pair", [(None, "无"), ("sun", "晴"), ("rain", "雨")]),
        ("火系队 vs 水系队", "team", [(None, "无"), ("sun", "晴"), ("rain", "雨")]),
        ("水箭龟×6 vs 隆隆岩×6", "pair", [(None, "无"), ("sand", "沙暴")]),
        ("隆隆石×6 vs 卡比兽×6", "pair", [(None, "无"), ("sand", "沙暴")]),
    ]:
        cells = []
        for wname, wlabel in arms:
            if kind == "pair":
                a, b = label.split(" vs ")
                a, b = a.replace("×6", ""), b.replace("×6", "")
                wr = pair_winrate(a, b, args.pairs, wname)
            else:  # 火系队 vs 水系队翻转检验
                wr = team_winrate(FIRE_TEAM, WATER_TEAM, args.pairs, wname)
            cells.append(f"{wlabel} {wr:.0%}")
            pair_rows.append((label, wlabel, wr))
        print(f"  {label}: " + " → ".join(cells))

    weather.set_active(None)  # 恢复进程级默认（无天气）

    # 判读
    print("\n== 判读 ==")
    base = rows[None]
    over = {f"{label}/{t} {r:.0%}": None for name, label in ARMS
            for t, r in rows[name]["rates"].items() if r > TYPE_CAP}
    print(f"  健康线 1a（任一天气臂属性胜率 ≤{TYPE_CAP:.0%}）：",
          "通过" if not over else f"越线 {list(over)}")
    bad_flips = [f"{l} {flips[w]:.1%}" for w, l in ARMS[1:] if flips[w] > FLIP_CAP]
    print(f"  健康线 1b（随机臂胜者翻转率 ≤{FLIP_CAP:.0%}）：",
          "通过" if not bad_flips else f"越线 {bad_flips}")

    def pair_wr(label_prefix, wlabel):
        return next(w for lb, wl, w in pair_rows
                    if lb == label_prefix and wl == wlabel)

    fw = [pair_wr("水箭龟×6 vs 喷火龙×6", wl) for wl in ("无", "晴", "雨")]
    swing = (fw[2] - fw[1]) / 2 * 100  # 晴/雨摆幅半宽（±pp）
    lo, hi = SWING_OK[0] * 100, SWING_OK[1] * 100
    verdict = "有效区间" if lo <= abs(swing) <= hi else \
              ("偏弱(噪音风险)" if abs(swing) < lo else "过强")
    print(f"  健康线 2（干净 2x 对位摆幅 {lo:.0f}~{hi:.0f}pp）："
          f"水vs火 无 {fw[0]:.1%} → 晴 {fw[1]:.1%} / 雨 {fw[2]:.1%}，"
          f"±{abs(swing):.1f}pp → {verdict}")
    t_sun = pair_wr("火系队 vs 水系队", "晴")
    t_rain = pair_wr("火系队 vs 水系队", "雨")
    flip = (t_sun > 0.5) != (t_rain > 0.5)
    print(f"  健康线 3（纯属性队 4x 相对差不因天气翻转）：火系队 晴 {t_sun:.0%} / "
          f"雨 {t_rain:.0%} → {'翻转(越权!)' if flip else '未翻转，通过'}")
    fire_shift = (rows["rain"]["rates"]["FIRE"] - base["rates"]["FIRE"]) * 100
    water_shift = (rows["sun"]["rates"]["WATER"] - base["rates"]["WATER"]) * 100
    print(f"  随机臂位移（应为噪音级）：雨臂 FIRE {fire_shift:+.1f}pp / "
          f"晴臂 WATER {water_shift:+.1f}pp——位移动力集中在 committed 对位，"
          f"不扰动随机环境")


if __name__ == "__main__":
    main()
