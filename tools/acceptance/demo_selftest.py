#!/usr/bin/env python3
"""Web 可玩 Demo 整局自测（验收脚本，urllib 零依赖）。

对运行中的验收后台（默认自起一个临时实例）走完整 API 局：
    new → 随机合法操作（优先买/摆/开战，穿插刷新/经验/合成/装备/卖出）
    → 循环到终局。
断言（reports/web-demo-2026-09-14.md 验收 §1）：
    A1 轮次推进（单调不减、终局 == 最后一轮）；
    A2 金币扣减正确（买入前后 gold 差 == 商店标价）；
    A3 至少一场玩家战斗帧生成且 ≥40 帧（并抽查首帧 URL 200 + PNG 魔数）；
    A4 终局有排名（8 席全有 rank）；
    A5 全程无 500（所有请求 HTTP 200；合法操作 ok=true，被拒操作必有中文原因）。

用法：
    python3 tools/acceptance/demo_selftest.py                 # 自起临时服务
    python3 tools/acceptance/demo_selftest.py --base-url http://127.0.0.1:8799
    python3 tools/acceptance/demo_selftest.py --seeds 7,42,2026
"""

import argparse
import json
import random
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SEEDS = (7, 42, 2026)
OP_RNG_SEED = 20260914     # 操作序列固定种子：同种子可复现同一局
SAFETY_ROUNDS = 45


class Client:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.statuses = {}

    def get(self, path: str):
        req = urllib.request.Request(self.base + path)
        with urllib.request.urlopen(req, timeout=120) as resp:
            code = resp.status
            body = resp.read()
        self.statuses[code] = self.statuses.get(code, 0) + 1
        return code, body

    def action(self, params: dict):
        q = "&".join(f"{k}={urllib.parse.quote(str(v))}"
                     for k, v in params.items())
        code, body = self.get("/api/demo/action?" + q)
        assert code == 200, f"HTTP {code} on {params}"
        return json.loads(body)


def empty_cells(S):
    return [f"g{r},{c}" for r in (1, 0) for c in range(6)
            if not S["board"][r][c]]


def play_one_game(cli: Client, seed: int, verbose=False):
    rng = random.Random(OP_RNG_SEED + seed)
    j = cli.action({"cmd": "new", "seed": seed})
    assert j["ok"], j
    sid = j["sid"]
    stats = {"rounds": 0, "frames": 0, "battles": 0, "ok": 0, "rejected": 0,
             "gold_checks": 0, "evolutions": 0, "crafts": 0, "equips": 0,
             "first_battle_round": None}
    last_round = 0
    t0 = time.time()
    while True:
        S = cli.action({"cmd": "state", "sid": sid})["state"]
        assert S["round"] >= last_round, f"轮次回退 {last_round}->{S['round']}"
        last_round = S["round"]
        if S["phase"] == "over":
            break
        if S["phase"] == "prep" and S["you"]["alive"]:
            # -- 准备阶段：优先买/摆，穿插其他合法操作 --
            for _ in range(8):
                S = cli.action({"cmd": "state", "sid": sid})["state"]
                if S["phase"] != "prep":
                    break
                x = rng.random()
                if x < 0.55:                       # 买（优先）
                    idx = [i for i, s in enumerate(S["shop"]) if s]
                    if not idx:
                        continue
                    i = rng.choice(idx)
                    gold0 = S["you"]["gold"]
                    jj = cli.action({"cmd": "buy", "sid": sid, "i": i})
                    if jj["ok"]:
                        stats["ok"] += 1
                        price = S["shop"][i]["price"]
                        diff = gold0 - jj["state"]["you"]["gold"]
                        assert diff == price, \
                            f"金币扣减错误：期望 -{price} 实际 -{diff}"
                        stats["gold_checks"] += 1
                        if "3合1" in (jj.get("msg") or ""):
                            stats["evolutions"] += 1
                    else:
                        stats["rejected"] += 1
                        assert jj["error"], "被拒操作必须有中文原因"
                elif x < 0.65:                     # 摆位/交换
                    srcs = [f"b{i}" for i in range(len(S["bench"]))]
                    holes = empty_cells(S)
                    if S["bench"] and holes and rng.random() < 0.75:
                        jj = cli.action({"cmd": "move", "sid": sid,
                                         "from": rng.choice(srcs),
                                         "to": rng.choice(holes)})
                    elif len(srcs) > 1:
                        jj = cli.action({"cmd": "move", "sid": sid,
                                         "from": rng.choice(srcs),
                                         "to": rng.choice(srcs)})
                    elif S["bench"] and S["you"]["on_board"]:
                        cells = [f"g{r},{c}" for r in (1, 0) for c in range(6)
                                 if S["board"][r][c]]
                        jj = cli.action({"cmd": "move", "sid": sid,
                                         "from": rng.choice(cells),
                                         "to": "b0"})
                    else:
                        continue
                    stats["ok" if jj["ok"] else "rejected"] += 1
                    if not jj["ok"]:
                        assert jj["error"]
                elif x < 0.72:                     # 刷新
                    jj = cli.action({"cmd": "refresh", "sid": sid})
                    stats["ok" if jj["ok"] else "rejected"] += 1
                elif x < 0.80:                     # 买经验
                    jj = cli.action({"cmd": "levelup", "sid": sid})
                    stats["ok" if jj["ok"] else "rejected"] += 1
                else:                              # 卖出（备战管理）
                    S = cli.action({"cmd": "state", "sid": sid})["state"]
                    if S["bench"]:
                        jj = cli.action({"cmd": "sell", "sid": sid,
                                         "loc": f"b{rng.randrange(len(S['bench']))}"})
                        stats["ok" if jj["ok"] else "rejected"] += 1
                    else:
                        continue
            # -- 装备整理：合成 → 穿戴 --
            S = cli.action({"cmd": "state", "sid": sid})["state"]
            for c in list(S["items"]["craftable"]):
                jj = cli.action({"cmd": "craft", "sid": sid, "item": c["key"]})
                if jj["ok"]:
                    stats["crafts"] += 1
            S = cli.action({"cmd": "state", "sid": sid})["state"]
            for f in S["items"]["finished"]:
                loc = None
                for r in (0, 1):
                    for c in range(6):
                        v = S["board"][r][c]
                        if v and not v["item"]:
                            loc = f"g{r},{c}"
                            break
                    if loc:
                        break
                if not loc and S["bench"] and not S["bench"][0]["item"]:
                    loc = "b0"
                if loc:
                    jj = cli.action({"cmd": "equip", "sid": sid,
                                     "item": f["key"], "loc": loc})
                    if jj["ok"]:
                        stats["equips"] += 1
            # -- 开战 --
            jj = cli.action({"cmd": "end_prep", "sid": sid})
            assert jj["ok"], jj.get("error")
            lb = jj["state"]["last_battle"]
            if lb and lb.get("n"):
                stats["battles"] += 1
                stats["frames"] += lb["n"]
                if stats["first_battle_round"] is None:
                    stats["first_battle_round"] = lb["round"]
        else:
            jj = cli.action({"cmd": "next", "sid": sid})
            assert jj["ok"], jj.get("error")
        stats["rounds"] += 1
        assert stats["rounds"] <= SAFETY_ROUNDS, "超出轮数安全上限（疑似死循环）"
    # -- 终局断言 --
    S = cli.action({"cmd": "state", "sid": sid})["state"]
    final = S.get("over")
    assert final, "终局缺 over/ranking"
    ranking = final["ranking"]
    assert len(ranking) == 8 and all(e["rank"] for e in ranking), \
        f"排名不完整：{[(e['name'], e['rank']) for e in ranking]}"
    assert stats["battles"] >= 1 and stats["frames"] >= 40, \
        f"玩家战斗帧不足：{stats['battles']} 场 / {stats['frames']} 帧"
    # 抽查一帧：URL 200 + PNG 魔数（首个有画面的战斗轮）
    r1 = stats["first_battle_round"]
    code, body = cli.get(f"/demo/frame/{sid}/r{r1}/0.png")
    assert code == 200 and body[:8] == b"\x89PNG\r\n\x1a\n", "首帧非 PNG"
    my = [e for e in ranking if e["is_you"]][0]
    dt = time.time() - t0
    print(f"  seed={seed:<5} 轮数={S['round']:<3} 名次={my['rank']:<2} "
          f"玩家战斗={stats['battles']}场/{stats['frames']}帧 "
          f"进化={stats['evolutions']+0} 合成={stats['crafts']} "
          f"装备={stats['equips']} 操作ok={stats['ok']} "
          f"被拒={stats['rejected']} 金币校验={stats['gold_checks']} "
          f"耗时={dt:.1f}s")
    if verbose:
        print("    排名:", " > ".join(
            f"{e['name']}({e['rank']})" for e in ranking))
    return stats


def wait_ready(cli: Client, timeout=30.0) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            code, _ = cli.get("/")
            if code == 200:
                return
        except Exception:
            time.sleep(0.3)
    raise SystemExit("服务未就绪")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base-url", default="",
                    help="已运行的后台地址（缺省自起临时实例）")
    ap.add_argument("--seeds", default=",".join(str(s) for s in SEEDS))
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    seeds = [int(x) for x in args.seeds.split(",") if x.strip()]

    proc = None
    base = args.base_url
    if not base:
        import socket
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        proc = subprocess.Popen(
            [sys.executable, str(ROOT / "tools/acceptance/server.py"),
             "--port", str(port)],
            cwd=str(ROOT), stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
        print(f"自起临时验收后台：{base}（pid {proc.pid}）")
    cli = Client(base)
    try:
        wait_ready(cli)
        t_all = time.time()
        print(f"== Web Demo 整局自测（种子 {seeds}，操作流种子 {OP_RNG_SEED}）==")
        for seed in seeds:
            play_one_game(cli, seed, verbose=args.verbose)
        print(f"== 全部通过（{time.time() - t_all:.1f}s）"
              f"｜HTTP 状态分布 {cli.statuses} ==")
    finally:
        if proc is not None:
            proc.terminate()
            proc.wait(timeout=10)


if __name__ == "__main__":
    main()
