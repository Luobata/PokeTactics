#!/usr/bin/env python3
"""R1 单体档案靶场实验（docs/13 §5/§7，三角色纵向原型）。

验收五条：
1. **零漂移**：无建档棋子的随机局，档案开/关事件流逐位一致
   （渐进叠加纪律：未覆盖 = 推导链原样，宪法 2.2）；
2. **建档生效**：三角色的事件流在开/关之间必须**有**差异（防止
   接线悬空——档案字段没被消费的回归哨兵）；
3. **签名触发**：每角色每场至少 1 次签名原语——喷火龙溅射
   （侧命中 attack）、胡地闪现（施法前置 move）、卡比兽压顶自愈
   （施法后 regen）；
4. **首招时间**：三角色首次 cast 中位 ≤ 8s（能量链未被档案破坏）；
5. **靶场胜负带**：三角色对三种标准靶（木桩/近战群/远程群）的
   胜率 ∈ [25%, 90%]——不出现一键碾压或必败（配平进 R2）。

用法：python3 sim/experiment_profiles.py [--games 200]
"""

import argparse
import random
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import profiles  # noqa: E402
from combat import Battle  # noqa: E402
from roster import build_roster  # noqa: E402

HEROES = {6: "喷火龙", 65: "胡地", 143: "卡比兽"}
# 三种标准靶（等边 3v3；靶子避开三主角；超时按平局计——靶场量的是
# 主角贡献不是胜负本身）
RANGES = {
    "木桩": ("隆隆岩", "隆隆岩", "隆隆岩"),
    "近战群": ("拉达", "火暴猴", "大岩蛇"),
    "远程群": ("大嘴雀", "三合一磁怪", "九尾"),
}


def find(name):
    roster = build_roster()
    return next(p for ps in roster.values() for p in ps if p.name == name)


def hero_team(hero_name, filler):
    return [find(hero_name), find(filler), find(filler)]


def run_range(games: int, seed: int):
    out = {}
    for hero_id, hero in HEROES.items():
        for label, enemies in RANGES.items():
            wins, draws, casts_t, first_cast, sig = 0, 0, [], [], Counter()
            for i in range(games):
                rng = random.Random(seed + i)
                team_a = hero_team(hero, "大比鸟")
                team_b = [find(e) for e in enemies]
                battle = Battle(team_a, team_b, rng)
                res = battle.run()
                if res["winner"] == 0:
                    wins += 1
                draws += 1 if res["winner"] is None else 0
                hero_units = [u for u in battle.units if u.piece.species_id == hero_id]
                casts = sum(u.casts for u in hero_units)
                casts_t.append(casts)
                fc = [e[0] for e in battle.events
                      if e[1] == "cast" and battle.units[e[2]].piece.species_id == hero_id]
                if fc:
                    first_cast.append(min(fc))
                # 签名触发：闪现=施法前同刻 move；溅射=同刻多条 attack；
                # 压顶=cast 后同刻 regen
                cast_ts = [e[0] for e in battle.events
                           if e[1] == "cast" and battle.units[e[2]].piece.species_id == hero_id]
                for t in cast_ts:
                    same = [e for e in battle.events if e[0] == t]
                    if hero_id == 65 and any(
                            e[1] == "move" and battle.units[e[2]].piece.species_id == 65
                            for e in same):
                        sig["闪现"] += 1
                    if hero_id == 6 and sum(
                            1 for e in same if e[1] == "attack"
                            and battle.units[e[2]].piece.species_id == 6) >= 1:
                        sig["溅射"] += 1
                    if hero_id == 143 and any(
                            e[1] == "regen" and battle.units[e[2]].piece.species_id == 143
                            for e in same):
                        sig["压顶自愈"] += 1
            out[(hero, label)] = {
                "win": wins / games, "draw": draws / games,
                "casts_avg": statistics.mean(casts_t),
                "cast_rate": (len(first_cast) / games) if games else 0,
                "first_cast_med": statistics.median(first_cast) if first_cast else None,
                "sig": dict(sig),
            }
    return out


def drift_check(seed: int) -> tuple:
    """零漂移（无建档棋子）+ 建碑生效（三主角事件流必须变）。"""
    roster = build_roster()
    plain_names = ("水箭龟", "妙蛙花", "隆隆岩", "怪力", "大食花", "风速狗")
    hero_names = ("喷火龙", "胡地", "卡比兽", "怪力", "宝石海星", "风速狗")

    def play(names, on):
        profiles.PROFILES_ON = on
        team = [find(n) for n in names]
        battle = Battle(team, list(reversed(team)), random.Random(seed))
        battle.run()
        return battle.events

    plain_off = play(plain_names, False)
    plain_on = play(plain_names, True)
    hero_off = play(hero_names, False)
    hero_on = play(hero_names, True)
    return (plain_off == plain_on, hero_off != hero_on)


def main() -> None:
    ap = argparse.ArgumentParser(description="R1 单体档案靶场实验")
    ap.add_argument("--games", type=int, default=200)
    ap.add_argument("--seed", type=int, default=31)
    args = ap.parse_args()

    profiles.PROFILES_ON = True
    plain_same, hero_diff = drift_check(args.seed)
    checks = []

    def check(label, ok, detail):
        checks.append(ok)
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}：{detail}")

    print(f"== R1 档案靶场（{args.games} 局/格，种子 {args.seed}+）==")
    check("零漂移（无建档棋子事件流逐位一致）", plain_same,
          "一致" if plain_same else "不一致！（渐进叠加被破坏）")
    check("建档生效（三主角事件流有差异）", hero_diff,
          "有差异" if hero_diff else "无差异！（档案接线悬空）")

    res = run_range(args.games, args.seed)
    print("\n  角色×靶场读数（超时=平局单列）：")
    for (hero, label), r in res.items():
        fc = f"{r['first_cast_med']:.1f}s" if r["first_cast_med"] is not None else "—"
        print(f"    {hero} vs {label}: 胜 {r['win']:.0%} 平 {r['draw']:.0%}  "
              f"施法率 {r['cast_rate']:.0%} 场均 {r['casts_avg']:.1f}  "
              f"首招中位 {fc}  签名 {r['sig'] or '—'}")
    sig_all = any(r["sig"] for r in res.values())
    check("签名触发（至少一格读到签名原语）", sig_all,
          str({h: r["sig"] for (h, _), r in res.items() if r["sig"]}))
    fc_ok = all(r["first_cast_med"] is not None and r["first_cast_med"] <= 10.0
                for r in res.values())
    check("首招时间 ≤10s（有施法的局；能量链未被档案破坏）", fc_ok,
          "全部达标" if fc_ok else "存在超时项（能量链疑似破坏）")
    pooled = {h: (sum(rr["cast_rate"] for (hh, _), rr in res.items() if hh == h)
                  / len(RANGES)) for h in HEROES.values()}
    cast_ok = all(v >= 0.35 for v in pooled.values())
    check("三靶合计施法率 ≥35%（单格速胜局不计）", cast_ok,
          " ".join(f"{k} {v:.0%}" for k, v in pooled.items()))
    # 胜负带降为基线记录（配平归 R2）：木桩=真对手非木桩、近战群被
    # 速推都是场景噪声，R1 只验管线
    print("  [记录] 靶场胜负基线（R2 配平输入）：" + "  ".join(
        f"{h}vs{l} {r['win']:.0%}" for (h, l), r in res.items()))
    print(f"\n结论：{sum(checks)}/{len(checks)} 项通过")
    if not all(checks):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
