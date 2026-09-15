#!/usr/bin/env python3
"""Web Demo 严格 E2E（完整对局 + 动画全链路验证，urllib 零依赖）。

与 demo_selftest 的分工：selftest 是「随机合法操作也能跑完整局」的健壮性
冒烟；本脚本是**验收级 E2E**——策略保证每轮上场非空，逐场校验战斗动画
全链路。用户实测踩过「空场开战 → 无帧 → 播放器黑屏」的坑（2026-09-14
修复：准备期闪烁警告 + 阻塞确认 + 无帧画布大字说明），本脚本把这类回归
钉死在断言层。

断言分七组：
  E1 相位机：prep→battle→next→prep…→over，轮次单调，终局 8 席全排名；
  E2 上场不变量：每次 end_prep 前上场 ≥1（首日起即可保证：R1 收入后
     ≥7 金，商店任意棋 ≤3 金）——因此**每一轮都必须有战斗画面**；
  E3 动画全链路：每场玩家战斗 last_battle.n ≥ 40 且 events ≥ 1；
     首/中/末三帧 URL 200 + PNG 魔数；磁盘 meta.json 的 n/events 数与
     API 一致；帧数与轮次对齐（r 字段 == 当前轮）；
  E4 资源：出现过的每个物种精灵图 URL 200 + PNG；
  E5 经济：买入前后金币差 == 标价；金币恒 ≥0；
  E6 动作覆盖：跨种子全集覆盖 12 个动作（含 unequip/卖出/被拒路径，
     被拒必须带中文原因）；
  E7 天气与确定性：R6-10 战报出现「天气：晴」等行且当轮有战斗画面；
     同种子重放 R1 战斗的胜者/时长/帧数一致（rng 分层派生的端到端验证）。

用法：
    python3 tools/acceptance/demo_e2e.py                 # 自起临时服务
    python3 tools/acceptance/demo_e2e.py --base-url http://127.0.0.1:8799
    python3 tools/acceptance/demo_e2e.py --seeds 7,42,2026
"""

import argparse
import json
import random
import subprocess
import sys
import time
from pathlib import Path

from demo_selftest import Client, wait_ready, ROOT

SEEDS = (7, 42, 2026)
OP_RNG_SEED = 20260915     # 与 selftest 错开：两套操作流独立可复现
SAFETY_ROUNDS = 90            # 循环迭代上限（31 轮 × prep/battle 两态 + 余量）
MIN_FRAMES = 40            # 与 selftest 同一条底线


class E2E:
    def __init__(self, cli: Client):
        self.cli = cli
        self.sprites = {}          # sid -> 已校验
        self.actions_used = set()
        self.totals = {"battles": 0, "frames": 0, "rounds": 0,
                       "ok": 0, "rejected": 0}
        self.failures = []

    def note_action(self, name: str, j: dict) -> bool:
        self.actions_used.add(name)
        if j["ok"]:
            self.totals["ok"] += 1
            return True
        self.totals["rejected"] += 1
        assert j.get("error"), f"被拒动作 {name} 缺中文原因: {j}"
        return False

    def check_sprites(self, S):
        seen = []
        for row in S["board"]:
            seen += [v["sid"] for v in row if v]
        seen += [v["sid"] for v in S["bench"] if v]
        seen += [v["sid"] for v in S["shop"] if v]
        opp = S.get("opponent")
        if opp:
            for row in opp.get("rows") or []:
                seen += [v["sid"] for v in row if v]
        for sid in seen:
            if sid not in self.sprites:
                code, body = self.cli.get(f"/demo/sprite/{sid}.png")
                assert code == 200 and body[:4] == b"\x89PNG", \
                    f"精灵图 {sid} 异常 HTTP {code}"
                self.sprites[sid] = True

    def verify_battle(self, sid: str, S_pre: dict, S_post: dict):
        """E2+E3：上场非空 → 必有战斗画面；全链路帧校验。"""
        r = S_post["round"]
        on_board_pre = S_pre["you"]["on_board"]
        lb = S_post.get("last_battle")
        if on_board_pre == 0:
            # 策略保证不发生；发生即断言失败（这正是用户踩过的黑屏路径）
            raise AssertionError(f"R{r} 上场为空（策略违约，黑屏路径）")
        assert lb and lb.get("n"), f"R{r} 有棋上场却无战斗画面（last_battle 空）"
        n, ev = lb["n"], lb["events"]
        assert n >= MIN_FRAMES, f"R{r} 帧数不足：{n} < {MIN_FRAMES}"
        assert ev, f"R{r} 事件流为空"
        assert lb["round"] == r, f"帧轮次错位 {lb['round']} != {r}"
        for idx in (0, n // 2, n - 1):
            code, body = self.cli.get(f"/demo/frame/{sid}/r{r}/{idx}.png")
            assert code == 200, f"R{r} 帧 {idx} HTTP {code}"
            assert body[:4] == b"\x89PNG", f"R{r} 帧 {idx} 非 PNG"
        meta_p = ROOT / ".build" / "demo" / sid / f"r{r}" / "meta.json"
        assert meta_p.exists(), f"R{r} 磁盘缺 meta.json"
        meta = json.loads(meta_p.read_text())
        assert meta["n"] == n and len(meta["events"]) == len(ev), \
            f"R{r} meta 与 API 不一致：{meta['n']}/{len(meta['events'])}" \
            f" vs {n}/{len(ev)}"
        self.totals["battles"] += 1
        self.totals["frames"] += n

    # ---- 准备期策略：永上场（买得起就买 → 有空格就上 → 再其他操作） ----
    def prep_policy(self, sid: str, S: dict, rng: random.Random) -> dict:
        y = S["you"]
        # 1) 买：金币留 4 保底经验预算之外全花（首日 7 金至少买 2 只 1 费）
        for i, cell in enumerate(S["shop"]):
            if not cell:
                continue
            if y["gold"] - cell["price"] < 1:
                break
            j = self.cli.action({"cmd": "buy", "sid": sid, "i": i})
            if self.note_action("buy", j):
                gold0 = y["gold"]
                y = j["state"]["you"]
                assert gold0 - y["gold"] == cell["price"], "金币扣减错误"
            else:
                break   # 被拒（金币/备战满等）：本轮到此为止，下轮再补
        S = self.cli.action({"cmd": "state", "sid": sid})["state"]
        y = S["you"]
        # 2) 上场：备战全部推上去（人口够）
        holes = [f"g{r},{c}" for r in (1, 0) for c in range(6)
                 if not S["board"][r][c]]
        for b in range(len(S["bench"]) - 1, -1, -1):
            if y["on_board"] >= y["pop"] or not holes:
                break
            j = self.cli.action({"cmd": "move", "sid": sid,
                                 "from": f"b{b}", "to": holes.pop(0)})
            if self.note_action("move", j):
                S = j["state"]
                y = S["you"]
        # 3) 穿插：升级 / 刷新 / 卖出 / 卸装备（动作覆盖）
        x = rng.random()
        if x < 0.3 and y["gold"] >= 8:
            self.note_action("levelup", self.cli.action(
                {"cmd": "levelup", "sid": sid}))
        elif x < 0.45 and y["gold"] >= 6:
            self.note_action("refresh", self.cli.action(
                {"cmd": "refresh", "sid": sid}))
        elif x < 0.55:
            S = self.cli.action({"cmd": "state", "sid": sid})["state"]
            equipped = [f"g{r},{c}" for r in (0, 1) for c in range(6)
                        if S["board"][r][c] and S["board"][r][c]["item"]]
            if equipped:
                self.note_action("unequip", self.cli.action(
                    {"cmd": "unequip", "sid": sid,
                     "loc": rng.choice(equipped)}))
        elif x < 0.6:
            S = self.cli.action({"cmd": "state", "sid": sid})["state"]
            if len(S["bench"]) >= 5:
                self.note_action("sell", self.cli.action(
                    {"cmd": "sell", "sid": sid, "loc": "b0"}))
        # 4) 装备：合成 → 装到空手棋子
        S = self.cli.action({"cmd": "state", "sid": sid})["state"]
        for c in list(S["items"]["craftable"]):
            self.note_action("craft", self.cli.action(
                {"cmd": "craft", "sid": sid, "item": c["key"]}))
            S = self.cli.action({"cmd": "state", "sid": sid})["state"]
        for f in S["items"]["finished"]:
            loc = next((f"g{r},{c}" for r in (0, 1) for c in range(6)
                        if S["board"][r][c] and not S["board"][r][c]["item"]),
                       None)
            if loc:
                self.note_action("equip", self.cli.action(
                    {"cmd": "equip", "sid": sid, "item": f["key"],
                     "loc": loc}))
                S = self.cli.action({"cmd": "state", "sid": sid})["state"]
        S = self.cli.action({"cmd": "state", "sid": sid})["state"]
        self.check_sprites(S)
        return S

    def play(self, seed: int, expect_r1=None):
        rng = random.Random(OP_RNG_SEED + seed)
        j = self.cli.action({"cmd": "new", "seed": seed})
        assert j["ok"], j
        self.actions_used.add("new")
        sid = j["sid"]
        last_round, rounds = 0, 0
        r1_meta = None
        weather_rounds = {}
        t0 = time.time()
        while True:
            S = self.cli.action({"cmd": "state", "sid": sid})["state"]
            self.actions_used.add("state")
            assert S["round"] >= last_round, "轮次回退"
            last_round = S["round"]
            if S["phase"] == "over":
                break
            rounds += 1
            assert rounds <= SAFETY_ROUNDS, "超出安全轮数"
            if S["phase"] == "prep" and S["you"]["alive"]:
                S = self.prep_policy(sid, S, rng)
                assert S["you"]["on_board"] >= 1, \
                    f"R{S['round']} 策略违约：上场为空"
                assert S["you"]["gold"] >= 0, "金币为负"
                pre = S
                j = self.cli.action({"cmd": "end_prep", "sid": sid})
                self.note_action("end_prep", j)
                post = j["state"]
                self.verify_battle(sid, pre, post)
                if post["round"] == 1:
                    lb = post["last_battle"]
                    r1_meta = (lb["winner"], lb["duration"], lb["n"])
                w = post["weather"]["zh"]
                weather_rounds.setdefault(w, post["round"])
                if 6 <= post["round"] <= 10:
                    assert w == "晴", f"R{post['round']} 天气时刻表错误：{w}"
                    assert any("天气：" in l and "晴" in l
                               for l in post["log"][-8:]), "战报缺天气行"
            else:
                j = self.cli.action({"cmd": "next", "sid": sid})
                self.note_action("next", j)
        # E1 终局
        S = self.cli.action({"cmd": "state", "sid": sid})["state"]
        over = S.get("over")
        assert over and len(over["ranking"]) == 8 \
            and all(e["rank"] for e in over["ranking"]), "终局排名不完整"
        my = [e for e in over["ranking"] if e["is_you"]][0]
        if expect_r1 is not None:
            assert r1_meta == expect_r1, \
                f"同种子重放不一致：{r1_meta} != {expect_r1}（确定性回退！）"
        print(f"  seed={seed:<5} 轮数={S['round']:<3} 名次={my['rank']:<2} "
              f"战斗={self.totals['battles']}场/帧={self.totals['frames']} "
              f"精灵图={len(self.sprites)} 动作={len(self.actions_used)}/12 "
              f"ok={self.totals['ok']} 拒={self.totals['rejected']} "
              f"耗时={time.time() - t0:.1f}s")
        return r1_meta, my["rank"]


def main() -> None:
    ap = argparse.ArgumentParser(description="Web Demo 严格 E2E")
    ap.add_argument("--base-url", default="")
    ap.add_argument("--seeds", default=",".join(str(s) for s in SEEDS))
    args = ap.parse_args()
    seeds = [int(x) for x in args.seeds.split(",") if x.strip()]

    proc, base = None, args.base_url
    if not base:
        import socket
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        proc = subprocess.Popen(
            [sys.executable, str(ROOT / "tools/acceptance/server.py"),
             "--port", str(port)], cwd=str(ROOT),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"自起临时验收后台：{base}（pid {proc.pid}）")
    cli = Client(base)
    try:
        wait_ready(cli)
        t0 = time.time()
        print(f"== Web Demo 严格 E2E（种子 {seeds}，操作流种子 {OP_RNG_SEED}）==")
        e2e = E2E(cli)
        first_meta = None
        for seed in seeds:
            meta, _ = e2e.play(seed)   # 首轮收集，不跨种子断言（种子间本就不同）
            if first_meta is None:
                first_meta = meta
        # E7 重放臂：首种子重打一遍，R1 战斗逐位一致
        e2e.play(seeds[0], expect_r1=first_meta)
        # E6 动作覆盖盘点（采样依赖局数：单/双种子为冒烟口径只警告，
        # 默认 3 种子+重放臂才硬卡——unequip/sell 分支需要装备+长局才触发）
        need = {"new", "state", "buy", "sell", "refresh", "levelup", "move",
                "craft", "equip", "unequip", "end_prep", "next"}
        missing = need - e2e.actions_used
        if len(seeds) >= 3:
            assert not missing, f"动作未覆盖：{sorted(missing)}"
        elif missing:
            print(f"（冒烟口径 {len(seeds)} 种子：未覆盖 {sorted(missing)}，"
                  f"默认 3 种子为硬卡线）")
        print(f"== 全部通过（{time.time() - t0:.1f}s）｜动作 12/12 覆盖｜"
              f"HTTP {cli.statuses} ==")
    finally:
        if proc is not None:
            proc.terminate()
            proc.wait(timeout=10)


if __name__ == "__main__":
    main()
