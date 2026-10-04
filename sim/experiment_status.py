#!/usr/bin/env python3
"""S12 状态/Buff 系统对照实验（关 vs 开，docs/06-status-buffs.md）。

回答四件事：
1. 随机场：状态全开后带宽/时长怎么动？DOT 是拖场（打不死→拖到超时）还是
   收割（补伤害→提前结束）？状态覆盖率和人均挂状态数是什么量级？
2. 灼伤贡献：高火系队 vs 高草系队（火 2x 压制面）与 vs 无状态队（拉锯面），
   灼伤的 DOT+降攻占总伤害多少、对位胜率动多少；另设「灼伤必中压力臂」
   （chance=1.0，量级上界标定，非推荐值）读 DOT 满额时的伤害占比与拖场度；
3. 麻痹攻速影响：含电队 vs 无状态队，麻痹（攻速×0.70+周期停顿）压掉对面
   多少出手；
4. 控制递减是否压住连控：冰冻队（冰束远程拉普拉斯×6，实验内改携带招式与
   射程——现池拉普拉斯带水炮，冰冻来源不可达，见报告）vs 无控队，递减开/关
   × 常规 12% / 必中 100% 四读：施加量、被控时间占比、最长连控，以及
   递减不变量（同单位相邻两次控制命中间隔必须 ≥5s；递减关闭时该计数
   = 实际会形成的连控对数）。

方法与克制/近远程/羁绊实验同构：开关经 status.STATUS_ON 注入；
跨臂同一 comp_rng 序列 + 逐场派生战斗种子（状态施加会改变 rng 消耗，
逐场派生保证两臂阵容与种子完全一致）。压力臂通过临时改
status.DEBUFFS[kind]["chance"] 实现，跑完恢复原表。

用法：
    python3 sim/experiment_status.py [--games 1000] [--seed 12] [--pairs 200]
"""

import argparse
import random
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import status  # noqa: E402
from combat import Battle  # noqa: E402
from data import pokedex  # noqa: E402
from roster import Piece, build_roster, random_comp  # noqa: E402

MIN_SAMPLE = 40  # 属性出现次数低于此不进带宽统计（沿用克制实验口径）
FLINCH = "flinch"

# 定向对位阵容（名字须在 roster 中存在）
TEAM_FIRE = ["喷火龙", "九尾", "风速狗", "火伊布", "火恐龙", "六尾"]   # 全员火系招
TEAM_GRASS = ["妙蛙花", "霸王花", "大食花", "臭臭花", "妙蛙草", "走路草"]  # 全员草系招
TEAM_ELEC = ["雷伊布", "雷丘", "三合一磁怪", "皮卡丘", "小磁怪", "雷伊布"]  # 全员电系招
TEAM_PLAIN = [  # 无状态来源：龙/水/普/飞招式（火毒电冰超都没有）
    "快龙", "水箭龟", "水伊布", "卡比兽", "大比鸟", "暴鲤龙"]


def make_piece(name: str, move_name: str = None, distance: int = None):
    """按名取棋子；move_name/distance 非空时覆盖（实验构装：冰冻臂拉普拉斯
    改冰束+远程——本体近战，走位稀释大招频率，远程版吞吐读数更干净）。"""
    roster = build_roster()
    p = next(p for ps in roster.values() for p in ps if p.name == name)
    if move_name is None and distance is None:
        return p
    mv = p.move_id
    if move_name is not None:
        mv = next(m for m in pokedex().moves.values() if m["name"] == move_name)["id"]
    return Piece(p.species_id, p.tier, p.level, move_id=mv,
                 distance=p.distance if distance is None else distance)


def make_team(names, move_name=None, distance=None) -> list:
    return [make_piece(n, move_name, distance) for n in names]


# ---------------------------------------------------------------- 随机臂 --

def random_metrics(games: int, size: int, seed: int) -> dict:
    comp_rng = random.Random(seed)  # 阵容序列独立于战斗 rng → 跨臂完全一致
    pairs = [(random_comp(comp_rng, size), random_comp(comp_rng, size))
             for _ in range(games)]
    wins, durs, type_w = Counter(), [], defaultdict(lambda: [0, 0])
    st = dict(cov_any=0, cov_major=0, applies=Counter(), dot=0, direct=0,
              dot_kills=0, woke=0, blocked=Counter())
    for i, (a, b) in enumerate(pairs):
        battle = Battle(a, b, random.Random(seed * 1_000_003 + i))
        res = battle.run()
        wins[res["winner"]] += 1
        durs.append(res["duration"])
        for side, comp in ((0, a), (1, b)):
            for t in {t for p in comp for t in p.types}:
                type_w[t][0] += 1
                type_w[t][1] += 1 if res["winner"] == side else 0
        stats = getattr(battle, "status_stats", None)
        if stats:
            st["applies"].update(stats["applied"])
            st["blocked"].update(stats["blocked"])
            st["dot"] += stats["dot_damage"]
            st["dot_kills"] += stats["dot_kills"]
            st["woke"] += stats["woke"]
            st["direct"] += sum(e[4] for e in battle.events if e[1] == "attack") + \
                sum(e[6] for e in battle.events if e[1] == "cast")
            if sum(stats["applied"].values()):
                st["cov_any"] += 1
            if sum(v for k, v in stats["applied"].items() if k != FLINCH):
                st["cov_major"] += 1
    rates = {t: w / n for t, (n, w) in type_w.items() if n >= MIN_SAMPLE}
    q = statistics.quantiles(durs, n=10)
    return {
        "ab": (wins[0], wins[1], wins[None]),
        "dur_med": statistics.median(durs), "dur_p90": q[8], "dur_max": max(durs),
        "rates": rates, "bandwidth": max(rates.values()) - min(rates.values()),
        "cov_any": st["cov_any"] / games, "cov_major": st["cov_major"] / games,
        "per_unit": sum(st["applies"].values()) / (games * 2 * size),
        "applies": st["applies"], "blocked": st["blocked"],
        "dot_share": st["dot"] / max(1, st["dot"] + st["direct"]),
        "dot_kills": st["dot_kills"] / games, "woke": st["woke"] / games,
    }


# ---------------------------------------------------------------- 定向臂 --

def run_pair(team_a: list, team_b: list, games: int, seed_base: int,
             buff_a=None, sword_a=False) -> dict:
    """定向对位：A 胜率 + 状态读数 + 双方出手/直伤 + 控制窗口（事件流回读）。"""
    out = dict(win_a=0, dur=[], applies=Counter(), blocked=Counter(),
               dot=Counter(), direct={0: 0, 1: 0}, attacks={0: 0, 1: 0},
               ctrl={0: 0.0, 1: 0.0}, alive={0: 0.0, 1: 0.0},
               chain={0: 0.0, 1: 0.0}, dot_kills=0, dr_gap=Counter())
    for i in range(games):
        battle = Battle(team_a, team_b, random.Random(seed_base + i))
        if buff_a:
            status.apply_team_buff(battle, 0, buff_a, 0.0)
        if sword_a:
            for u in battle.units:
                if u.team == 0:
                    status.apply_sword_dance(battle, u, 0.0)
        res = battle.run()
        out["win_a"] += 1 if res["winner"] == 0 else 0
        out["dur"].append(res["duration"])
        stats = getattr(battle, "status_stats", None)
        if stats:
            out["applies"].update(stats["applied"])
            out["blocked"].update(stats["blocked"])
            out["dot_kills"] += stats["dot_kills"]
        death = {e[2]: e[0] for e in battle.events if e[1] == "die"}
        for u in battle.units:   # 存活秒数（被控占比的分母）
            out["alive"][u.team] += death.get(u.idx, res["duration"])
        prev_ctrl = {}   # idx -> 上次控制类命中时刻（递减不变量检查用）
        for e in battle.events:
            if e[1] == "attack":
                out["attacks"][battle.units[e[2]].team] += 1
                out["direct"][battle.units[e[2]].team] += e[4]
            elif e[1] == "cast":
                out["attacks"][battle.units[e[2]].team] += 1
                out["direct"][battle.units[e[2]].team] += e[6]
            elif e[1] == "status" and e[4] == "tick":
                out["dot"][e[3]] += e[5]
            elif (e[1] == "status" and e[4] == "apply"
                  and e[3] in ("freeze", "sleep", "para")):
                last = prev_ctrl.get(e[2])
                # 递减不变量：同一单位相邻两次控制命中间隔必须 >= DR_WINDOW(5s)。
                # 递减关闭时此计数 = 会形成的连控对数。
                out["dr_gap"]["lt5s" if last is not None
                              and e[0] - last < 5.0 - 1e-6 else "ge5s"] += 1
                prev_ctrl[e[2]] = e[0]
        secs, chain = _control_windows(battle, res)
        for tm in (0, 1):
            out["ctrl"][tm] += secs[tm]
            out["chain"][tm] = max(out["chain"][tm], chain[tm])
    g = games
    out["win_a"] /= g
    out["dur_med"] = statistics.median(out["dur"])
    out["attacks"] = {tm: v / g for tm, v in out["attacks"].items()}
    out["direct"] = {tm: v / g for tm, v in out["direct"].items()}
    out["ctrl"] = {tm: v / g for tm, v in out["ctrl"].items()}
    out["alive"] = {tm: v / g for tm, v in out["alive"].items()}
    out["dot_total"] = sum(out["dot"].values())
    out["dot_share"] = out["dot_total"] / max(1, out["dot_total"]
                                              + sum(out["direct"].values()))
    return out


def _control_windows(battle, res):
    """冰冻/睡眠 apply→expire 窗口：expire/死亡/战斗结束三处闭合（死亡不闭合
    会把窗口虚拉到战末，读数失真）。相邻窗口拼接 = 连控。
    返回（每队被控秒数, 每队最长连续被控秒数）。"""
    end_t = res["duration"]
    opens, wins = {}, {0: [], 1: []}
    for e in battle.events:
        if e[1] == "die":
            if e[2] in opens:
                wins[battle.units[e[2]].team].append((opens.pop(e[2]), e[0]))
        elif e[1] == "status" and e[3] in ("freeze", "sleep"):
            tm = battle.units[e[2]].team
            if e[4] == "apply":
                opens[e[2]] = e[0]
            elif e[4] == "expire" and e[2] in opens:
                wins[tm].append((opens.pop(e[2]), e[0]))
    for idx, s in opens.items():
        wins[battle.units[idx].team].append((s, end_t))
    secs, chain = {}, {}
    for tm, ws in wins.items():
        merged = []
        for s, e in sorted(ws):   # 相邻拼接 = 连控
            if merged and s <= merged[-1][1] + 1e-9:
                merged[-1][1] = max(merged[-1][1], e)
            else:
                merged.append([s, e])
        secs[tm] = sum(e - s for s, e in merged)
        chain[tm] = max((e - s for s, e in merged), default=0.0)
    return secs, chain


def _fmt_pair(o: dict) -> str:
    return (f"胜率A {o['win_a']:.0%}  时长中位 {o['dur_med']:.1f}s  "
            f"出手A/B {o['attacks'][0]:.0f}/{o['attacks'][1]:.0f} 每场")


def determinism_check(size: int, seed: int) -> None:
    """状态开启下同种子重放一局，比对事件流（宪法 2.2/2.6）。"""
    def play() -> list:
        rng = random.Random(seed)
        battle = Battle(random_comp(rng, size), random_comp(rng, size), rng)
        battle.run()
        return battle.events
    ok = play() == play()
    print(f"确定性自检（状态开）: {'通过' if ok else '失败！'}")
    if not ok:
        raise SystemExit(1)


# ---------------------------------------------------------------- 主流程 --

import synergy as _syn
_syn.SYNERGIES_ON = False  # 本报告基线建立于羁绊关（2026-09-14 起默认开）
import profiles as _pf
_pf.PROFILES_ON = False  # R1 单体档案（2026-09-15）：钉关保基线


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=1000)
    ap.add_argument("--size", type=int, default=6)
    ap.add_argument("--seed", type=int, default=12)
    ap.add_argument("--pairs", type=int, default=200)
    args = ap.parse_args()

    print(f"S12 状态实验：{args.games} 场随机 {args.size}v{args.size}"
          f"（seed={args.seed}）+ 定向检验各 {args.pairs} 场")
    status.STATUS_ON = True
    determinism_check(args.size, args.seed)
    status.STATUS_ON = False

    # ---- 随机臂：关 vs 开 ----
    rows = []
    for name, flag in (("T0 状态关", False), ("T1 状态开", True)):
        status.STATUS_ON = flag
        m = random_metrics(args.games, args.size, args.seed)
        top = max(m["rates"].items(), key=lambda kv: kv[1])
        bot = min(m["rates"].items(), key=lambda kv: kv[1])
        rows.append((name, m))
        print(f"\n[{name}]")
        print(f"  A/B/平 {m['ab'][0]}/{m['ab'][1]}/{m['ab'][2]}  "
              f"时长中位 {m['dur_med']:.1f}s / P90 {m['dur_p90']:.1f}s / "
              f"最长 {m['dur_max']:.1f}s")
        print(f"  属性胜率带宽 {m['bandwidth']:.1%}（最高 {top[0]} {top[1]:.0%} / "
              f"最低 {bot[0]} {bot[1]:.0%}，n≥{MIN_SAMPLE} 的 {len(m['rates'])} 系）")
        print(f"  属性胜率: " + "  ".join(
            f"{t} {r:.0%}" for t, r in sorted(
                m["rates"].items(), key=lambda kv: -kv[1])))
        if flag:
            print(f"  状态覆盖: 任一施加 {m['cov_any']:.0%} / 减益类(不含畏缩) "
                  f"{m['cov_major']:.0%} 的场次；人均施加 {m['per_unit']:.2f} 次")
            print(f"  施加/场: " + ("  ".join(
                f"{status.kind_label(k)} {v / args.games:.2f}"
                for k, v in m["applies"].most_common()) or "无"))
            blk = "  ".join(
                f"{status.kind_label(k)}.{r} {v / args.games:.1f}"
                for (k, r), v in m["blocked"].most_common(6))
            print(f"  被挡/场: {blk or '无'}")
            print(f"  DOT 占总伤害 {m['dot_share']:.2%}  DOT 击杀 "
                  f"{m['dot_kills']:.3f} 只/场  睡眠唤醒 {m['woke']:.3f} 次/场")

    # ---- 定向 1：灼伤贡献（火队 vs 草队压制面 / vs 无状态队拉锯面 / 必中压力）----
    fire, grass, plain = make_team(TEAM_FIRE), make_team(TEAM_GRASS), make_team(TEAM_PLAIN)
    print(f"\n== 定向 1：灼伤贡献（火队 vs 草队 / vs 无状态队 / 必中压力臂）==")
    status.STATUS_ON = True
    for label, tb, seed_base in (("草队(压制面)", grass, 9000),
                                 ("无状态队(拉锯面)", plain, 9050)):
        for name, flag in (("关", False), ("开", True)):
            status.STATUS_ON = flag
            o = run_pair(fire, tb, args.pairs, seed_base)
            extra = ""
            if flag:
                extra = (f"  灼伤施加 {o['applies']['burn'] / args.pairs:.2f} 次/场"
                         f"  DOT占总伤 {o['dot_share']:.1%}"
                         f"（{o['dot']['burn'] / args.pairs:.0f}/场）")
            print(f"  火队 vs {label} [{name}]: {_fmt_pair(o)}{extra}")
    status.STATUS_ON = True
    status.DEBUFFS["burn"]["chance"] = 1.0   # 压力臂：量级上界标定，跑完恢复
    o = run_pair(fire, plain, args.pairs, 9060)
    print(f"  [灼伤必中压力臂 chance=1.0]: {_fmt_pair(o)}"
          f"  DOT占总伤 {o['dot_share']:.1%}  DOT击杀 {o['dot_kills'] / args.pairs:.2f} 只/场")
    status.DEBUFFS["burn"]["chance"] = 0.30

    # ---- 定向 2：麻痹攻速影响（电队 vs 无状态队，常规 + 必中压力）----
    elec = make_team(TEAM_ELEC)
    print(f"\n== 定向 2：麻痹攻速（电队 vs 无状态队，看 B 队出手被压多少）==")
    for name, flag in (("关", False), ("开", True)):
        status.STATUS_ON = flag
        o = run_pair(elec, plain, args.pairs, 9100)
        extra = ""
        if flag:
            extra = (f"  麻痹施加 {o['applies']['para'] / args.pairs:.2f} 次/场"
                     f"  被DR挡 {o['blocked'].get(('para', 'dr'), 0) / args.pairs:.2f}")
        print(f"  [{name}]: {_fmt_pair(o)}{extra}")
    status.STATUS_ON = True
    status.DEBUFFS["para"]["chance"] = 1.0   # 压力臂：量级上界，跑完恢复
    o = run_pair(elec, plain, args.pairs, 9150)
    print(f"  [麻痹必中压力臂 chance=1.0]: {_fmt_pair(o)}"
          f"  麻痹施加 {o['applies']['para'] / args.pairs:.2f} 次/场"
          f"（对照 B 队出手关臂基数看压幅）")
    status.DEBUFFS["para"]["chance"] = 0.25

    # ---- 定向 3：控制递减 vs 连控（冰冻队 = 冰束远程拉普拉斯×6，常规+必中）----
    ice = make_team(["拉普拉斯"] * 6, move_name="ice_beam", distance=3)
    print(f"\n== 定向 3：连控防护（冰冻队 vs 无控队，DR 开/关 × 常规/必中）==")

    def freeze_arm(label, chance, dr, seed_base):
        status.STATUS_ON = True
        status.DEBUFFS["freeze"]["chance"] = chance
        status.DR_WINDOW = dr
        o = run_pair(ice, plain, args.pairs, seed_base)
        uptime = o["ctrl"][1] / max(1e-9, o["alive"][1])
        print(f"  [{label}]: {_fmt_pair(o)}")
        print(f"    冰冻施加 {o['applies']['freeze'] / args.pairs:.2f} 次/场  "
              f"被DR挡 {o['blocked'].get(('freeze', 'dr'), 0) / args.pairs:.2f} 次/场  "
              f"被免疫挡 {o['blocked'].get(('freeze', 'immune'), 0) / args.pairs:.2f} 次/场")
        print(f"    无控队被控 {o['ctrl'][1]:.1f}s/场（占存活时间 {uptime:.0%}）  "
              f"最长连续被控 {o['chain'][1]:.1f}s")
        print(f"    递减不变量（同单位相邻控制命中 <5s 的对数）: "
              f"{o['dr_gap']['lt5s']} 次（>=5s 的 {o['dr_gap']['ge5s']} 对）")
        return o

    freeze_arm("常规 12% 递减开5s", 0.12, 5.0, 9200)
    freeze_arm("常规 12% 递减关", 0.12, 0.0, 9200)
    freeze_arm("必中 100% 递减开5s", 1.0, 5.0, 9210)
    freeze_arm("必中 100% 递减关", 1.0, 0.0, 9210)
    status.DEBUFFS["freeze"]["chance"] = 0.12
    status.DR_WINDOW = 5.0

    # ---- 定向 4：增益 v1（光墙/反射壁/剑舞，实验参数直接施加）----
    print(f"\n== 定向 4：增益 v1（无状态队镜像局，A 侧 t=0 施加）==")
    status.STATUS_ON = True
    base = run_pair(plain, plain, args.pairs, 9300)
    print(f"  [无增益对照]: {_fmt_pair(base)}")
    for label, kw in (("光墙 特防+30% 8s", dict(buff_a="lightscreen")),
                      ("反射壁 物防+30% 8s", dict(buff_a="reflect")),
                      ("剑舞 全队物攻+25%", dict(sword_a=True))):
        o = run_pair(plain, plain, args.pairs, 9300, **kw)
        print(f"  [{label}]: {_fmt_pair(o)}")

    # ---- 收尾 ----
    status.STATUS_ON = False
    print("\n== 判读 ==")
    (n0, m0), (n1, m1) = rows
    print(f"  带宽 {m0['bandwidth']:.1%} → {m1['bandwidth']:.1%}；"
          f"时长中位 {m0['dur_med']:.1f}s → {m1['dur_med']:.1f}s "
          f"（P90 {m0['dur_p90']:.1f}s → {m1['dur_p90']:.1f}s，"
          f"最长 {m0['dur_max']:.1f}s → {m1['dur_max']:.1f}s）")
    print(f"  DOT 占总伤害 {m1['dot_share']:.2%}、DOT 击杀 {m1['dot_kills']:.3f} 只/场——"
          "中位/P90 下行=DOT 收割，上行=拖场（与 45s 超时线的距离看最长列）。")
    print("  关注：几率表的实际瓶颈是来源频率（状态只吃大招命中，普攻无属性，"
          "充能 ~5s vs 中位战斗 7.7s）——覆盖率读数低不是几率表偏高偏低一档能补的，"
          "结论与建议值见报告。")


if __name__ == "__main__":
    main()
