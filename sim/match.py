#!/usr/bin/env python3
"""M2 完整单局模拟：8 bot 混战（经济 + 商店 + 买入 AI + 战斗 + 掉血淘汰）。

一局 = 玩家 vs 7 机器人的单机锦标赛骨架（本版全 bot，无人类玩家）。
回合循环（头脑风暴 §1/§7，docs/03 §1）：
  收入结算（基础+利息+连胜连败 + 白送 XP）
  → 免费重滚商店 → bot 决策（买/卖/刷新/升级，L0-L3，耗时统计）
  → 上场选择与摆位 → 配对（无重复对手优先，奇数人打幽灵）
  → bot-vs-bot 直接解算（无渲染，docs/03 §1）
  → 败方掉血 = 2 + 存活敌棋 × 阶段系数 → 淘汰（棋子归还共享池）
每 5 轮 PVE 野怪轮（大葱鸭群→暴走肯泰罗→化石翼龙，胜 2-3 金；
装备掉落留 S5）。HP 100 归零淘汰，按淘汰顺序排名。

确定性：整局只用一个显式 rng（宪法 2.2），同 seed 重放逐轮一致
（淘汰顺序与排名完全一致，验收见 experiment_match）。

用法：
    python3 sim/match.py --bots 8 --seed 7 --rounds 31 [-v]
"""

import argparse
import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import economy  # noqa: E402
import shop as shop_mod  # noqa: E402
from bots import Bot, LINEUP, assign_personalities, main_types  # noqa: E402
from combat import Battle  # noqa: E402
from shop import SharedPool, build_templates, make_piece  # noqa: E402

# PVE 野怪轮波次表（头脑风暴 §7：大葱鸭群 → 暴走肯泰罗 → 化石翼龙 BOSS）
# 键 = 第几个野怪轮（R5/R10/.../R30 → 0..5）；野怪不入商店池
PVE_WAVES = [
    [83, 83, 83],                    # R5:  大葱鸭群
    [128, 128, 128, 128],            # R10: 暴走肯泰罗
    [128, 128, 128, 142],            # R15: 肯泰罗 + 化石翼龙
    [142, 142, 128, 128],            # R20: 双化石翼龙
    [142, 142, 142, 128, 128],       # R25
    [142, 142, 142, 128, 128, 128],  # R30: 6 单位满编
]
PVE_GOLD = (2, 3)   # 野怪轮胜利掉落 2-3 金（装备组件留 S5）


class Match:
    """一局完整模拟。run() 返回结果摘要 dict（experiment 复用）。"""

    def __init__(self, seed: int, n_bots: int = 8, max_rounds: int = 31) -> None:
        assert n_bots in LINEUP, f"bots 只支持 {sorted(LINEUP)}"
        self.seed = seed
        self.rng = random.Random(seed)
        self.max_rounds = max_rounds
        self.templates = build_templates()
        self.pool = SharedPool(self.templates)
        pers = assign_personalities(n_bots, random.Random(seed ^ 0x5EED))
        self.bots = [Bot(i, LINEUP[n_bots][i], pers[i],
                         self.pool, self.templates) for i in range(n_bots)]
        self.round = 0
        self.elimination_order: list = []   # [(轮, bot)]
        self.round_log: list = []           # -v 逐轮简报
        self.rounds_with_damage = 0         # 死锁自查：有人掉血的轮数
        self.decide_times: list = []        # 每次 bot 决策耗时(ms)
        self.battles = 0

    # ---- 工具 ----
    def alive(self) -> list:
        return [b for b in self.bots if b.alive]

    def _eliminate(self, bot: Bot, round_no: int) -> None:
        """淘汰：定名次，棋子/商店全部归还共享池（卡池恢复，可被别人买走）。"""
        bot.alive = False
        bot.rank = len(self.alive()) + 1
        for owned in bot.all_pieces():
            for sid in owned.sources:
                self.pool.put(sid)
        bot.board, bot.bench = [], []
        bot.shop.return_all()
        self.elimination_order.append((round_no, bot))

    # ---- 主循环 ----
    def run(self) -> dict:
        # 首轮免费铺一次商店
        for b in self.bots:
            b.shop.roll(self.rng, b.level)
        while self.round < self.max_rounds and len(self.alive()) > 1:
            self.round += 1
            self._play_round(self.round)
            if len(self.alive()) <= 1:
                break
        # 收尾：决出冠军；到轮数上限仍多人存活按 HP 排名（并列按等级/席位）
        alive = self.alive()
        if len(alive) == 1:
            alive[0].rank = 1
        else:
            for rank, b in enumerate(sorted(
                    alive, key=lambda x: (-x.hp, -x.level, x.seat)), 1):
                b.rank = rank
        return self.result()

    def _play_round(self, round_no: int) -> None:
        rng = self.rng
        pve = round_no % 5 == 0
        # 1) 收入结算 + 白送 XP + 免费重滚（席位顺序，确定性）
        for b in self.alive():
            b.gold += economy.round_income(b.gold, b.streak)
            b.level, b.xp = economy.gain_round_xp(b.level, b.xp)
            b.shop.roll(rng, b.level)
        # 2) bot 决策（耗时统计：perf_counter 含 OS 调度抖动，实验读 p99）
        for b in self.alive():
            t0 = time.perf_counter()
            b.decide(round_no, self.bots, rng)
            self.decide_times.append((time.perf_counter() - t0) * 1000)
        # 3) 配对 / PVE
        events = []
        if pve:
            events = self._pve_round(round_no)
        else:
            events = self._pvp_round(round_no)
        # 4) 掉血（先全部结算，再按席位序淘汰——同轮双亡时名次确定）
        damaged = False
        for bot, dmg, _note in events:
            if dmg > 0:
                bot.hp -= dmg
                bot.last_damage = dmg
                damaged = True
        self.rounds_with_damage += 1 if damaged else 0
        for b in [x for x in self.alive() if x.hp <= 0]:
            self._eliminate(b, round_no)
        if events:
            self.round_log.append((round_no, events))

    # ---- PVP 轮 ----
    def _pvp_round(self, round_no: int) -> list:
        rng = self.rng
        alive = self.alive()
        pairs, odd = self._pair_up(alive)
        events = []   # [(bot, damage, 描述)]
        for a, b in pairs:
            dmg_a = dmg_b = 0
            note = ""
            if a.battle_comp() and b.battle_comp():
                a.counter_vs(b.board)   # L3 对位（非 L3 无操作）
                b.counter_vs(a.board)
                res = Battle(a.battle_comp(), b.battle_comp(),
                             rng, layout="back").run()
                self.battles += 1
                factor = economy.stage_factor(round_no)
                surv = res["survivors"]
                if res["winner"] == 0:
                    dmg_b = economy.loss_damage(round_no, surv[0])
                    note = f"{a.name} 胜(存活{surv[0]})"
                elif res["winner"] == 1:
                    dmg_a = economy.loss_damage(round_no, surv[1])
                    note = f"{b.name} 胜(存活{surv[1]})"
                else:   # 平局（超时同 HP 比例，罕见）：双双按对方存活掉血
                    dmg_a = economy.loss_damage(round_no, surv[1])
                    dmg_b = economy.loss_damage(round_no, surv[0])
                    note = "平局双伤"
                self._streak(a, res["winner"] == 0)
                self._streak(b, res["winner"] == 1)
            else:   # 空场判负（理论上仅开局极端情况）
                if a.battle_comp():
                    dmg_b = economy.loss_damage(round_no, len(a.battle_comp()))
                    self._streak(a, True)
                    self._streak(b, False)
                    note = f"{a.name} 不战而胜"
                elif b.battle_comp():
                    dmg_a = economy.loss_damage(round_no, len(b.battle_comp()))
                    self._streak(b, True)
                    self._streak(a, False)
                    note = f"{b.name} 不战而胜"
            events.append((a, dmg_a, f"vs {b.name}: {note}"))
            events.append((b, dmg_b, ""))
        if odd is not None:   # 奇数人：打幽灵（随机对手的镜像，败方照常掉血）
            ghost_src = rng.choice([b for b in alive if b is not odd])
            res = Battle(odd.battle_comp(), ghost_src.battle_comp(),
                         rng, layout="back").run()
            self.battles += 1
            dmg = 0
            if res["winner"] == 1:
                dmg = economy.loss_damage(round_no, res["survivors"][1])
                self._streak(odd, False)
            else:
                self._streak(odd, True)
            events.append((odd, dmg, f"幽灵战({ghost_src.name}镜像)"))
        return events

    def _pair_up(self, alive: list):
        """随机配对，尽量避开上一轮同对手（无重复对手优先，头脑风暴 §7）。"""
        rng = self.rng
        best = None
        for _ in range(20):
            order = sorted(alive, key=lambda _: rng.random())
            pairs = [(order[i], order[i + 1])
                     for i in range(0, len(order) - 1, 2)]
            odd = order[-1] if len(order) % 2 else None
            fresh = all(getattr(a, "_last_opp", None) is not b for a, b in pairs)
            best = (pairs, odd)
            if fresh:
                break
        for a, b in best[0]:
            a._last_opp, b._last_opp = b, a
        if best[1] is not None and best[0]:
            # 幽灵战的对手记录：记镜像源，同样避免连续
            best[1]._last_opp = None
        return best

    @staticmethod
    def _streak(bot: Bot, won: bool) -> None:
        if won:
            bot.streak = bot.streak + 1 if bot.streak > 0 else 1
        else:
            bot.streak = bot.streak - 1 if bot.streak < 0 else -1

    # ---- PVE 野怪轮 ----
    def _pve_round(self, round_no: int) -> list:
        rng = self.rng
        wave_ids = PVE_WAVES[min(round_no // 5 - 1, len(PVE_WAVES) - 1)]
        wave = [make_piece(sid, self.templates) for sid in wave_ids]
        events = []
        for b in self.alive():
            res = Battle(b.battle_comp(), list(wave), rng,
                         layout="back").run()
            self.battles += 1
            if res["winner"] == 0:   # 野怪轮不改连胜连败（docs/03 §5 惯例）
                b.gold += rng.randint(*PVE_GOLD)
                events.append((b, 0, "野怪胜"))
            else:
                dmg = economy.loss_damage(round_no, res["survivors"][1])
                events.append((b, dmg, f"野怪败 -{dmg}"))
        return events

    # ---- 结果摘要 ----
    def result(self) -> dict:
        rounds = self.round
        return {
            "seed": self.seed,
            "rounds": rounds,
            "finished_early": len(self.elimination_order) == len(self.bots) - 1,
            "ranking": sorted(self.bots, key=lambda b: b.rank),
            "elimination_order": list(self.elimination_order),
            "rounds_with_damage": self.rounds_with_damage,
            "decide_times": list(self.decide_times),
            "battles": self.battles,
        }


# ---- CLI ----
def _fmt_events(events: list) -> str:
    parts = []
    for bot, dmg, note in events:
        if note:
            parts.append(f"{note} [{bot.name} -{dmg}]" if dmg else note)
    return " | ".join(parts)


def print_report(m: Match, verbose: bool) -> None:
    r = m.result()
    print(f"== 单局结果（seed={m.seed}，{len(m.bots)} bot，"
          f"进行 {r['rounds']} 轮，解算 {r['battles']} 场战斗）==")
    if verbose:
        print("-- 逐轮简报 --")
        for round_no, events in m.round_log:
            print(f"  R{round_no:>2}: {_fmt_events(events)}")
    print("-- 淘汰顺序 --")
    for round_no, bot in r["elimination_order"]:
        formed = (f"羁绊成型 R{bot.synergy_formed_round}({bot.synergy_formed_type})"
                  if bot.synergy_formed_round else "羁绊未成型(4)")
        print(f"  第{round_no:>2}轮淘汰 → 第{bot.rank}名 {bot.name:<12} "
              f"Lv{bot.level} 人口{bot.pop_curve[-1] if bot.pop_curve else 0} "
              f"3合1×{bot.combines} {formed}")
    print("-- 最终排名 --")
    print(f"  {'名':<3}{'bot':<14}{'人格':<10}{'能力':<4}{'轮数':<5}"
          f"{'等级':<5}{'HP':<6}{'金币均/末':<10}{'人口末':<6}羁绊成型")
    for b in r["ranking"]:
        avg_g = statistics.mean(b.gold_curve) if b.gold_curve else 0
        formed = f"R{b.synergy_formed_round} {b.synergy_formed_type}" \
            if b.synergy_formed_round else "-"
        print(f"  {b.rank:<4}{b.name:<15}{b.pers_key:<10}L{b.ability:<4}"
              f"{len(b.gold_curve):<5}{b.level:<5}{max(b.hp, 0):<6}"
              f"{avg_g:.0f}/{b.gold_curve[-1] if b.gold_curve else 0:<4}"
              f"{b.pop_curve[-1] if b.pop_curve else 0:<6}{formed}")
    # 关键统计摘要
    print("-- 关键统计 --")
    gold_curve_avg = []
    for i in range(m.round):
        col = [b.gold_curve[i] for b in m.bots if len(b.gold_curve) > i]
        gold_curve_avg.append(statistics.mean(col) if col else 0)
    checkpoints = sorted(set([0, m.round // 4, m.round // 2,
                              3 * m.round // 4, m.round - 1]))
    print("  人均金币曲线: " + "  ".join(
        f"R{i + 1}={gold_curve_avg[i]:.0f}" for i in checkpoints if i < m.round))
    pop_avg = []
    for i in range(m.round):
        col = [b.pop_curve[i] for b in m.bots if len(b.pop_curve) > i]
        pop_avg.append(statistics.mean(col) if col else 0)
    print("  人口爬升:     " + "  ".join(
        f"R{i + 1}={pop_avg[i]:.1f}" for i in checkpoints if i < m.round))
    formed = [b.synergy_formed_round for b in m.bots
              if b.synergy_formed_round]
    print(f"  羁绊成型轮次（任一属性≥4）: 均值 "
          f"{statistics.mean(formed):.1f} / 中位 {statistics.median(formed):.0f}"
          f"（{len(formed)}/{len(m.bots)} 人成型）" if formed else
          "  羁绊成型: 无人成型")
    times = sorted(r["decide_times"])
    p99 = times[int(len(times) * 0.99)] if times else 0.0
    print(f"  3合1 进化总数 {sum(b.combines for b in m.bots)}，"
          f"刷新总次数 {sum(b.refreshes for b in m.bots)}，"
          f"决策耗时 p99 {p99:.2f}ms / max {times[-1] if times else 0:.2f}ms / "
          f"均值 {statistics.mean(times) if times else 0:.2f}ms")
    print(f"  有掉血的轮数 {r['rounds_with_damage']}/{m.round}"
          f"（其余为野怪轮全胜）")


def main() -> None:
    ap = argparse.ArgumentParser(description="M2 完整单局模拟")
    ap.add_argument("--bots", type=int, default=8, choices=sorted(LINEUP))
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--rounds", type=int, default=31)
    ap.add_argument("-v", "--verbose", action="store_true", help="逐轮简报")
    args = ap.parse_args()
    m = Match(args.seed, args.bots, args.rounds)
    m.run()
    print_report(m, args.verbose)


if __name__ == "__main__":
    main()
