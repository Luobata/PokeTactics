#!/usr/bin/env python3
"""Web 可玩完整 Demo：1 玩家 + 7 bot 的整局宝可梦自走棋（会话引擎 + /demo 页面）。

架构（防漂移，与验收后台同源）：
- **只读复用 sim**：economy / shop / items / bots / combo / synergy / status /
  weather / rng / combat.Battle / roster / match 的常量与规则
  （PVE_WAVES、weather_for_round、Match._pair_up 无重复对手配对）。
  sim/ 与 tools/mockups/ 不做任何修改；渲染需参数扩展的地方
  （BattleAnimation 固定 layout="random"、自带 rng）用 DemoBattleAnimation
  子类包装：layout="back" + 外部 battle 子流 —— 玩家摆位因此真实生效。
- 会话 = 内存 dict（uuid 键）+ 全局锁；玩家席位（seat 0）+ 7 bot
  （人格混合 L1×3 + L2×3 + L3×1，LINEUP[7]，开局一次 pers 子流发牌）。
- 回合循环：准备阶段（玩家操作，不限时）→ end_prep 服务端结算 →
  玩家战斗用 BattleAnimation 渲染成帧（存 .build/demo/<sid>/r<n>/，
  羁绊/状态/天气/齐射全开）→ bot 对 bot 秒算只留结果行 → 掉血/淘汰/
  下一轮（天气按 weather_for_round）→ 终局排名页。
- 与 sim/match.py 的差异（适配层裁定，均为简化/单机可用性让路）：
  · 商店 4 格 / 备战 6 格：2026-09-14 平衡 pass 起 sim 常量已对齐
    （docs/10 设备裁定），bot 与玩家同规则（此前 bot 5 格/9 格的不对等
    已消除，见 reports/matchbalance-2026-09-14.md）；
  · 玩家战斗的解算与渲染同源（DemoBattleAnimation 内部那次 Battle 就是
    权威结果），帧 = 战报；bot 战斗与 match 完全同轨；
  · 幽灵战/野怪战也吃当轮天气（match 只给 PVP 主对战上天气）；
  · 渲染器 HUD（帧内左上读数）是渲染层固定占位值，真实读数在 Web HUD。

动作 API（GET /api/demo/action?cmd=...&sid=...）：new(seed) / state / buy(i) /
sell(loc) / refresh / levelup / move(from,to)（棋盘↔备战互移，含交换）/
craft(item) / equip(item,loc) / unequip(loc) / end_prep / next。
金币/人口/容量校验全部服务端，错误返回中文原因（ok=false，HTTP 恒 200）。

自动试玩（2026-09-15）：「▶ 自动试玩」按钮——客户端按决策优先级
（合成→装备→上场→买棋→升级→刷新→卖冗余→开战）驱动完整一局到终局
排名，战斗动画照常逐场播放（倍速随播放器档位）。近战前排/远程后排
的摆位与角标语义一致；后台标签自动暂停；全部走公开动作 API，
对局可事后复盘（与 E2E 同轨）。
"""

import io
import json
import shutil
import sys
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
for _p in (str(ROOT / "sim"), str(ROOT / "tools" / "mockups")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import economy  # noqa: E402
import items as items_mod  # noqa: E402
import rng as rng_mod  # noqa: E402
import shop as shop_mod  # noqa: E402
import synergy as syn_mod  # noqa: E402
import weather as weather_mod  # noqa: E402
from bots import LINEUP, Bot, assign_personalities  # noqa: E402
from combat import Battle  # noqa: E402
from match import (PVE_GOLD, PVE_WAVES, Match as _Match,  # noqa: E402
                   weather_for_round)
from shop import (build_templates, make_piece, sell_value,  # noqa: E402
                  try_combine)

MAX_ROUNDS = 31          # 与 sim/match 相同的轮数上限（超限按 HP 排名收官）
BENCH_CAP = 6            # 我方备战行 6 格（docs/10 §1.1 C-sym）
SHOP_SLOTS_UI = 4        # 商店 4 格（docs/10 §1.2 裁定）
GRID_COLS = 6            # C-sym 6 列
FPS_DT = 0.1             # 战斗帧步长（10fps，与验收台一致）

# 我方战场 2 行的填充序（combat layout="back" 对 team0 自 combat 行 3 起密排）：
# 列表头 = 后排（grid 行 1）→ 列表尾 = 前排（grid 行 0，贴中线）
_GRID_ORDER = [(1, c) for c in range(GRID_COLS)] + [(0, c) for c in range(GRID_COLS)]

TYPE_ZH = {"NORMAL": "一般", "FIRE": "火", "WATER": "水", "GRASS": "草",
           "ELECTRIC": "电", "ICE": "冰", "FIGHTING": "格斗", "POISON": "毒",
           "GROUND": "地面", "FLYING": "飞行", "PSYCHIC": "超能", "BUG": "虫",
           "ROCK": "岩", "GHOST": "幽灵", "DRAGON": "龙", "STEEL": "钢",
           "DARK": "恶"}

WEATHER_NOTE = {None: "天气平静", "sun": "火/草系招式 +20%，水系 -20%",
                "rain": "水系招式 +20%，火系 -20%",
                "sand": "岩/地/钢系招式 +15%", "hail": "冰系招式 +25%"}

PVE_LABELS = ["大葱鸭群", "暴走肯泰罗", "肯泰罗+化石翼龙", "双化石翼龙",
              "化石翼龙军团", "化石翼龙大军"]

ITEM_KEY_ZH = {"heal": "每秒回血", "sash": "致命伤保留1HP", "atk": "攻/特攻",
               "speed": "攻速", "dodge": "闪避", "ult_dmg": "大招伤害",
               "type_dmg": "系别增伤", "dr": "减伤", "gold_per_round": "每轮金币",
               "stone": "通信进化"}

SESSIONS: dict = {}
_LOCK = threading.RLock()
MAX_SESSIONS = 8         # 每会话落帧 ~20MB，超限淘汰最旧会话并清目录


class DemoError(Exception):
    """玩家操作被拒（前端 toast 中文原因）。"""


# ---------------------------------------------------------------- 素材（懒加载）
_ASSETS = None


def _assets():
    """Front/Palettes/Font16 全局单例（读 PokeWalk 二进制，进程内复用）。"""
    global _ASSETS
    if _ASSETS is None:
        with _LOCK:
            if _ASSETS is None:
                from decoders import Font16, Front, Palettes
                _ASSETS = (Front(), Palettes(), Font16())
    return _ASSETS


_SPRITES: dict = {}


def sprite_png(species_id: int):
    """/demo/sprite/<id>.png：40/48/56px 源图直接出 PNG（Web 端 CSS 缩放）。"""
    if species_id in _SPRITES:
        return _SPRITES[species_id]
    if not (1 <= species_id <= 151):
        return None
    front, pal, _ = _assets()
    buf = io.BytesIO()
    front.image(species_id, pal).save(buf, "PNG")
    _SPRITES[species_id] = buf.getvalue()
    return _SPRITES[species_id]


# ---------------------------------------------------------------- 渲染包装
def _render_battle_frames(comp_a, comp_b, rng, weather_name, out_dir: Path):
    """玩家战斗：DemoBattleAnimation（layout=back + 外部子流）解算并出全帧。

    解算与渲染同源：内部那次 Battle 就是本场的权威结果（胜者/存活数），
    帧目录 .build/demo/<sid>/r<轮>/，返回 meta（帧数/事件流/结果）。
    """
    from render_battle_gif import AnimUnit, BattleAnimation
    from data import pokedex

    class _Anim(BattleAnimation):
        """适配包装：layout=back + 外部 battle 子流；渲染器 R1 新接口
        （battle= 注入 + playback_clock 等回放态）由父类构造统一初始化。"""

        def __init__(self, a, b, battle_rng, front, pal, font):
            battle = Battle(a, b, battle_rng, layout="back",
                            weather_name=weather_name)
            self.sim_result = battle.run()
            super().__init__(a, b, 0, front, pal, font,
                             weather_name=weather_name, battle=battle)

    front, pal, font = _assets()
    anim = _Anim(comp_a, comp_b, rng, front, pal, font)
    res = anim.sim_result
    t_end = max(e[0] for e in anim.events)
    winner = res["winner"]
    duration = t_end + 1.2 + (1.5 if winner is not None else 0)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    n, T = 0, 0.0
    while T <= duration + 1e-9:
        anim.frame(T).convert("RGB").save(out_dir / f"{n}.png")
        n += 1
        T += FPS_DT
    meta = {"n": n, "winner": winner,
            "survivors": res["survivors"], "duration": round(t_end, 1),
            "events": [{"t": round(e[0], 2), "text": _fmt_event(anim, e)}
                       for e in anim.events]}
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False))
    return meta


_MOVES_ZH = None


def _move_zh(name: str) -> str:
    """事件流 cast 存英文名（契约不变），显示层翻译（与验收台同法）。"""
    global _MOVES_ZH
    if _MOVES_ZH is None:
        from data import pokedex
        _MOVES_ZH = {m["name"]: (m.get("name_zh") or m["name"])
                     for m in pokedex().moves.values()}
    return _MOVES_ZH.get(name, name)


def _fmt_event(anim, e: tuple) -> str:
    t, kind = e[0], e[1]
    name = lambda i: anim.by_idx[i].piece.name  # noqa: E731
    if kind == "deploy":
        return f"<b>{name(e[2])}</b> 落位 {e[3]}"
    if kind == "move":
        return f"{name(e[2])} 移动到 {e[3]}"
    if kind == "attack":
        return f"{name(e[2])} 普攻 {name(e[3])} <b>-{e[4]}</b>"
    if kind == "miss":
        return f"{name(e[2])} 攻击 {name(e[3])} 未命中（亮粉闪避）"
    if kind == "sash":
        return f"<b>{name(e[2])} 气势披带发动</b>（保留 1 HP）"
    if kind == "cast":
        eff = {0.5: "效果不佳", 2.0: "效果拔群", 4.0: "效果绝群"}.get(e[5], f"x{e[5]}")
        tail = " 未命中" if e[6] == 0 else \
            f" <b>-{e[6]}</b>{(' ' + eff) if e[5] != 1 else ''}"
        return f"<b>{name(e[2])} 的 {_move_zh(e[4])}</b> → {name(e[3])}{tail}"
    if kind == "die":
        return f"<b>{name(e[2])} 倒下</b>"
    if kind == "combo":
        return f"<b>⚡ {e[4]}（{TYPE_ZH.get(e[3], e[3])}系齐射）</b>"
    if kind == "regen":
        return f"{name(e[2])} 回复 +{e[3]}"
    if kind == "status":
        zh = {"burn": "灼伤", "poison": "中毒", "para": "麻痹", "paralysis": "麻痹",
              "freeze": "冰冻", "sleep": "睡眠", "flinch": "畏缩",
              "reflect": "反射壁", "lightscreen": "光墙",
              "swords": "剑舞"}.get(e[3], e[3])
        act = {"apply": "发作", "tick": "跳伤", "expire": "解除"}.get(e[4], e[4])
        tail = f" -{e[5]}" if len(e) > 5 and e[5] else ""
        return f"<b>{name(e[2])}</b> {zh}·{act}{tail}"
    if kind == "end":
        return f"— 战斗结束 {'（你胜）' if e[2] == 0 else '（对方胜）' if e[2] == 1 else '（平局）'}"
    return f"— {kind}"


# ---------------------------------------------------------------- 玩家席位
class PlayerSeat:
    """人类席位：与 Bot 鸭子类型兼容（hp/gold/level/board/bench/shop/inventory），
    供 sim 的幸运蛋计数、掉落权重、copycat 侦察与配对复用。"""

    seat = 0

    def __init__(self, pool, templates) -> None:
        self.name = "你"
        self.gold = economy.START_GOLD
        self.hp = economy.START_HP
        self.level, self.xp = 1, 0
        self.streak = 0
        self.grid = {}                      # (row, col) -> OwnedPiece
        self.bench = []
        self.shop = shop_mod.Shop(pool, templates)
        self.pool = pool
        self.templates = templates
        self.inventory = items_mod.Inventory()
        self.stone_used = False
        self.item_drops = 0
        self.alive = True
        self.rank = None
        self.last_damage = 0
        self.combines = 0
        self.refresh_j = 0                  # 当轮手动刷新序（shop 子流 j≥1）

    @property
    def board(self) -> list:
        """上场列表（次序即 Battle 阵型：头=后排）。"""
        return [self.grid[pos] for pos in _GRID_ORDER if pos in self.grid]

    def all_pieces(self) -> list:
        return self.board + self.bench

    def count_species(self, species_id: int) -> int:
        return sum(1 for o in self.all_pieces()
                   if o.piece.species_id == species_id)

    def pop(self) -> int:
        return economy.pop_of(self.level)

    def battle_comp(self) -> list:
        return [o.piece if o.item is None else (o.piece, o.item)
                for o in self.board]

    def counter_vs(self, opp_board) -> None:  # 人类无自动对位（占位，配对代码统一调用）
        return None


# ---------------------------------------------------------------- 会话
class Session:
    def __init__(self, seed: int) -> None:
        self.sid = uuid.uuid4().hex[:12]
        self.seed = seed
        self.templates = build_templates()
        self.pool = shop_mod.SharedPool(self.templates)
        self.player = PlayerSeat(self.pool, self.templates)
        pers = assign_personalities(7, rng_mod.derive(self.seed, 0, "pers"))
        self.bots = [Bot(i + 1, LINEUP[7][i], pers[i], self.pool, self.templates)
                     for i in range(7)]
        self.round_no = 0
        self.phase = "prep"
        self.log: list = []
        self.last_battle = None
        self.pairs = None
        self.ghost_seat = None
        self.ghost_src = None
        self.opp_view = None
        self.player_frames_total = 0
        self.player_battles = 0

    # ---- 工具 ----
    @property
    def seats(self) -> list:
        return [self.player] + self.bots

    def _alive(self) -> list:
        return [e for e in self.seats if e.alive]

    def _say(self, line: str) -> None:
        self.log.append(f"R{self.round_no}｜{line}")
        if len(self.log) > 240:
            del self.log[:120]

    def combine_player(self) -> list:
        """玩家 3 合 1（复用 shop.try_combine；格位按对象身份回填）。"""
        p = self.player
        pos_map = {id(o): pos for pos, o in p.grid.items()}
        board_list = list(p.board)
        logs = try_combine(board_list, p.bench, self.pool, self.templates,
                           p.inventory)
        if logs:
            p.combines += len(logs)
            p.grid = {pos_map[id(o)]: o for o in board_list if id(o) in pos_map}
        return logs

    def locate(self, loc: str):
        """'b<i>' 备战格 / 'g<r>,<c>' 战场格 -> (OwnedPiece, 容器, 键)。"""
        p = self.player
        try:
            if loc.startswith("b"):
                i = int(loc[1:])
                if not (0 <= i < len(p.bench)):
                    raise DemoError("备战格里没有棋子")
                return p.bench[i], "bench", i
            m = loc[1:].split(",")
            r, c = int(m[0]), int(m[1])
            if not (0 <= r <= 1 and 0 <= c < GRID_COLS):
                raise DemoError("格子坐标越界")
            if (r, c) not in p.grid:
                raise DemoError("这个格子是空的")
            return p.grid[(r, c)], "grid", (r, c)
        except (IndexError, ValueError):
            raise DemoError(f"无法识别的位置 {loc!r}")

    # ---- 回合推进 ----
    def begin_round(self, r: int) -> None:
        self.round_no = r
        self.phase = "prep"
        self.last_battle = None
        for e in self._alive():
            e.gold += economy.round_income(e.gold, e.streak)
            e.gold += items_mod.lucky_egg_income(e)
            e.level, e.xp = economy.gain_round_xp(e.level, e.xp)
        p = self.player
        p.refresh_j = 0
        if p.alive:
            self._roll_player_shop(rng_mod.derive(
                self.seed, r, "shop", rng_mod.shop_counter(p.seat, 0)))
        for b in self.bots:
            if b.alive:
                b.shop.roll(rng_mod.derive(
                    self.seed, r, "shop", rng_mod.shop_counter(b.seat, 0)),
                    b.level)
        for b in self.bots:
            if b.alive:
                b.decide(r, self.seats,
                         rng_mod.derive(self.seed, r, "bots", b.seat))
        # 配对：复用 match 规则（无重复对手优先 + 奇数打幽灵），
        # pair 子流每轮现派生，prep 期算好供 UI 展示对手快照（battle 时原样使用）
        self.pairs = None
        self.ghost_seat = self.ghost_src = None
        if r % 5 == 0:
            self.opp_view = self._pve_view(r)
        else:
            pair_rng = rng_mod.derive(self.seed, r, "pair")
            alive = self._alive()
            pairs, odd = _Match._pair_up(None, alive, pair_rng)
            ghost_src = None
            if odd is not None and len(alive) > 1:
                ghost_src = pair_rng.choice([e for e in alive if e is not odd])
            self.pairs, self.ghost_seat, self.ghost_src = pairs, odd, ghost_src
            if p.alive:
                self.opp_view = self._opponent_view()

    def _roll_player_shop(self, rng) -> None:
        # 2026-09-14 平衡 pass：sim SHOP_SLOTS 已对齐 4 格（docs/10 裁定），
        # bot 与玩家同规则，适配层不再裁第 5 格
        self.player.shop.roll(rng, self.player.level)

    def _enemy_rows(self, board: list):
        """bot 上场列表 -> 战场 2 行（combat 行 1=贴中线行在前、行 0 在后）。"""
        front = board[:GRID_COLS]
        back = board[GRID_COLS:2 * GRID_COLS]
        return [list(back), list(front)]

    def _opponent_view(self):
        p = self.player
        src = None
        if self.ghost_seat is p and self.ghost_src is not None:
            src, name = self.ghost_src, f"幽灵（{self.ghost_src.name} 镜像）"
        else:
            for a, b in self.pairs or []:
                if a is p:
                    src, name = b, b.name
                elif b is p:
                    src, name = a, a.name
        if src is None:
            return None
        return {"name": name, "hp": src.hp, "level": src.level,
                "rows": [[_piece_view(o.piece, o.item) for o in row]
                         for row in self._enemy_rows(src.board)],
                "bench": [_piece_view(o.piece, o.item)
                          for o in src.bench[:GRID_COLS]]}

    def _pve_view(self, r: int):
        wave_ids = PVE_WAVES[min(r // 5 - 1, len(PVE_WAVES) - 1)]
        label = PVE_LABELS[min(r // 5 - 1, len(PVE_LABELS) - 1)]
        row = [_piece_view(make_piece(sid, self.templates))
               for sid in wave_ids]
        rows = [row, [None] * len(row)]
        return {"name": f"野怪轮 · {label}", "hp": None, "level": None,
                "rows": rows, "bench": [], "pve": True}

    # ---- 战斗结算 ----
    def end_prep(self) -> None:
        if self.phase != "prep":
            raise DemoError("当前不是准备阶段（先看完战斗再进下一轮）")
        r = self.round_no
        weather = weather_for_round(r)
        if weather is not None:
            self._say(f"天气：{weather_mod.WEATHERS[weather]['label']}"
                      f"（{WEATHER_NOTE[weather]}）")
        if r % 5 == 0:
            events = self._resolve_pve(r, weather)
        else:
            events = self._resolve_pvp(r, weather)
        for seat, dmg, _note in events:
            if dmg > 0:
                seat.hp -= dmg
                seat.last_damage = dmg
        for e in [x for x in self.seats if x.alive and x.hp <= 0]:
            self._eliminate(e)
        self.phase = "battle"
        if len(self._alive()) <= 1 or r >= MAX_ROUNDS:
            self._finalize()

    def _fight(self, r, battle_i, a, b, weather):
        """bot 对 bot：秒算，只留结果（与 match._pvp_round 同轨）。"""
        return Battle(a.battle_comp(), b.battle_comp(),
                      rng_mod.derive(self.seed, r, "battle", battle_i),
                      layout="back", weather_name=weather).run()

    def _resolve_pvp(self, r, weather):
        events = []
        battle_i = 0
        p = self.player
        for a, b in self.pairs:
            dmg = {id(a): 0, id(b): 0}
            note = ""
            if a.battle_comp() and b.battle_comp():
                if isinstance(a, Bot):
                    a.counter_vs(b.board)
                if isinstance(b, Bot):
                    b.counter_vs(a.board)
                if p in (a, b):
                    # 玩家战斗：_fight_rendered 恒以玩家为 team0 —— 胜者
                    # 索引要换算回配对席位，再记 dmg/连胜
                    me, opp = (a, b) if a is p else (b, a)
                    meta = self._fight_rendered(r, battle_i, me, opp, weather)
                    w, surv = meta["winner"], meta["survivors"]
                    if w == 0:
                        dmg[id(opp)] = economy.loss_damage(r, surv[0])
                        note = f"你 胜（己方存活 {surv[0]}）"
                    elif w == 1:
                        dmg[id(me)] = economy.loss_damage(r, surv[1])
                        note = f"{opp.name} 胜（存活 {surv[1]}）"
                    else:
                        dmg[id(me)] = economy.loss_damage(r, surv[1])
                        dmg[id(opp)] = economy.loss_damage(r, surv[0])
                        note = "平局双伤"
                    self._streak(me, w == 0)
                    self._streak(opp, w == 1)
                    my = dmg[id(p)]
                    self._say(f"vs {opp.name}：{note}"
                              + (f"｜你 -{my}" if my else "｜你不掉血"))
                else:
                    res = self._fight(r, battle_i, a, b, weather)
                    if res["winner"] == 0:
                        dmg[id(b)] = economy.loss_damage(r, res["survivors"][0])
                        note = f"{a.name} 胜（存活 {res['survivors'][0]}）"
                    elif res["winner"] == 1:
                        dmg[id(a)] = economy.loss_damage(r, res["survivors"][1])
                        note = f"{b.name} 胜（存活 {res['survivors'][1]}）"
                    else:
                        dmg[id(a)] = economy.loss_damage(r, res["survivors"][1])
                        dmg[id(b)] = economy.loss_damage(r, res["survivors"][0])
                        note = "平局双伤"
                    self._streak(a, res["winner"] == 0)
                    self._streak(b, res["winner"] == 1)
                    if note:
                        self._say(note)
                battle_i += 1
            else:
                if a.battle_comp():
                    dmg[id(b)] = economy.loss_damage(r, len(a.battle_comp()))
                    self._streak(a, True), self._streak(b, False)
                    note = f"{a.name} 不战而胜"
                elif b.battle_comp():
                    dmg[id(a)] = economy.loss_damage(r, len(b.battle_comp()))
                    self._streak(b, True), self._streak(a, False)
                    note = f"{b.name} 不战而胜"
                else:
                    note = "双方空场，无事发生"
                if p in (a, b):
                    opp = b if a is p else a
                    my = dmg[id(p)]
                    self._say(f"vs {opp.name}：{note}"
                              + (f"｜你 -{my}" if my else "｜你不掉血"))
            events.append((a, dmg[id(a)], note))
            events.append((b, dmg[id(b)], ""))
        if self.ghost_seat is not None:   # 奇数席打幽灵（败方照常掉血）
            odd = self.ghost_seat
            if odd is p and p.battle_comp():
                meta = self._fight_rendered(r, battle_i, p, self.ghost_src,
                                            weather, ghost=True)
                res = {"winner": meta["winner"], "survivors": meta["survivors"]}
            elif odd.battle_comp():
                res = Battle(odd.battle_comp(), self.ghost_src.battle_comp(),
                             rng_mod.derive(self.seed, r, "battle", battle_i),
                             layout="back", weather_name=weather).run()
            else:   # 空场打幽灵：不战而败（保底掉血，Battle 空队会崩所以不走解算）
                res = {"winner": 1,
                       "survivors": {0: 0, 1: len(self.ghost_src.battle_comp())}}
            dmg = 0
            if res["winner"] == 1:
                dmg = economy.loss_damage(r, res["survivors"][1])
                self._streak(odd, False)
            else:
                self._streak(odd, True)
            if odd is p:
                self._say(f"幽灵战（{self.ghost_src.name} 镜像）："
                          + (f"败 -{dmg}" if dmg else "胜"))
            events.append((odd, dmg, "幽灵战"))
        return events

    def _resolve_pve(self, r, weather):
        wave_ids = PVE_WAVES[min(r // 5 - 1, len(PVE_WAVES) - 1)]
        wave = [make_piece(sid, self.templates) for sid in wave_ids]
        events = []
        battle_i = 0
        p = self.player
        alive = self._alive()
        for i, e in enumerate(alive):
            if e.battle_comp():
                if e is p:
                    meta = self._fight_rendered(r, battle_i, e, None, weather,
                                                wave=wave, pve=True)
                    res = {"winner": meta["winner"],
                           "survivors": meta["survivors"]}
                else:
                    res = Battle(e.battle_comp(), list(wave),
                                 rng_mod.derive(self.seed, r, "battle", battle_i),
                                 layout="back", weather_name=weather).run()
                battle_i += 1
                if res["winner"] == 0:
                    gold = rng_mod.derive(self.seed, r, "pve", i).randint(*PVE_GOLD)
                    e.gold += gold
                    if e is p:
                        self._say(f"野怪轮胜（+{gold} 金）")
                else:
                    dmg = economy.loss_damage(r, res["survivors"][1])
                    if e is p:
                        self._say(f"野怪轮败 -{dmg}（存活敌棋 "
                                  f"{res['survivors'][1]}）")
                    events.append((e, dmg, "野怪败"))
            else:
                dmg = economy.loss_damage(r, len(wave))
                if e is p:
                    self._say(f"野怪轮不战而败 -{dmg}（场上没有棋子！）")
                events.append((e, dmg, "野怪空场"))
        # S5 组件掉落：人头保底 + 血量加权加发（pve 子流掉落段，同 match）
        comps = sorted(items_mod.COMPONENT_ORDER)
        for i, e in enumerate(alive):
            rng_d = rng_mod.derive(self.seed, r, "pve",
                                   items_mod.PVE_DROP_COUNTER + i)
            e.inventory.add_component(rng_d.choice(comps))
            e.item_drops += 1
        weights = items_mod.drop_weights(alive)
        for j in range(items_mod.PVE_BONUS_DROPS):
            rng_d = rng_mod.derive(self.seed, r, "pve",
                                   items_mod.PVE_DROP_COUNTER + 256 + j)
            rec = rng_d.choices(alive, weights=weights)[0]
            rec.inventory.add_component(rng_d.choice(comps))
            rec.item_drops += 1
        got = {}
        for key, n in self.player.inventory.components.items():
            if n > 0:
                got[items_mod.COMPONENT_NAMES[key]] = got.get(
                    items_mod.COMPONENT_NAMES[key], 0) + n
        self._say("装备组件入仓：" + "、".join(
            f"{k}×{v}" for k, v in sorted(got.items()))
            if got else "野怪轮结束，等待下次掉落")
        return events

    def _fight_rendered(self, r, battle_i, me, opp, weather, ghost=False,
                        wave=None, pve=False):
        """玩家参与的战斗：渲染帧（=权威解算）。opp=None 时用野怪波次。"""
        comp_a = me.battle_comp()
        comp_b = ([o.piece if o.item is None else (o.piece, o.item)
                   for o in opp.board] if opp is not None else list(wave))
        if isinstance(opp, Bot):
            opp.counter_vs(self.player.board)
        rng = rng_mod.derive(self.seed, r, "battle", battle_i)
        out_dir = ROOT / ".build" / "demo" / self.sid / f"r{r}"
        t0 = time.time()
        meta = _render_battle_frames(comp_a, comp_b, rng, weather, out_dir)
        meta["round"] = r
        meta["render_s"] = round(time.time() - t0, 1)
        meta["pve"] = pve
        meta["ghost"] = ghost
        meta["opp_name"] = (opp.name if opp is not None else
                            (self.opp_view or {}).get("name", "野怪"))
        winner = meta["winner"]
        meta["headline"] = ("你 获胜！" if winner == 0 else
                            "你 失败……" if winner == 1 else "平局")
        self.last_battle = meta
        self.player_battles += 1
        self.player_frames_total += meta["n"]
        return meta

    @staticmethod
    def _streak(seat, won: bool) -> None:
        if won:
            seat.streak = seat.streak + 1 if seat.streak > 0 else 1
        else:
            seat.streak = seat.streak - 1 if seat.streak < 0 else -1

    def _eliminate(self, seat) -> None:
        seat.alive = False
        seat.rank = len(self._alive()) + 1
        for owned in seat.all_pieces():
            for sid in owned.sources:
                self.pool.put(sid)
        if isinstance(seat, PlayerSeat):
            seat.grid, seat.bench = {}, []
        else:
            seat.board, seat.bench = [], []
        seat.shop.return_all()
        self._say(f"{seat.name} 被淘汰（第 {seat.rank} 名）")

    def _finalize(self) -> None:
        self.phase = "over"
        alive = self._alive()
        if len(alive) == 1:
            alive[0].rank = 1
        else:
            for rank, e in enumerate(sorted(
                    alive, key=lambda x: (-x.hp, -x.level, x.seat)), 1):
                e.rank = rank
        order = sorted(self.seats, key=lambda e: (e.rank is None, e.rank))
        self._say("终局：" + " > ".join(
            f"{e.name}({e.rank})" for e in order[:3]))

    def next_round(self) -> None:
        if self.phase != "battle":
            raise DemoError("当前不在结算阶段")
        self.begin_round(self.round_no + 1)


# ---------------------------------------------------------------- 状态 JSON
def _hex(rgb) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _piece_view(piece, item=None):
    from data import pokedex
    from render_mockups import TYPE_COLORS
    dex = pokedex()
    mv = dex.moves.get(piece.move_id) if piece.move_id else None
    return {
        "sid": piece.species_id, "name": piece.name, "tier": piece.tier,
        "types": [TYPE_ZH.get(t, t) for t in piece.types],
        "colors": [_hex(TYPE_COLORS.get(t, (120, 120, 120)))
                   for t in piece.types],
        "ranged": piece.distance > 1,
        "move": (mv.get("name_zh") or mv["name"]) if mv else "—",
        "item": item,
        "item_name": items_mod.FINISHED[item]["name"] if item else None,
    }


def _item_effect(key: str) -> str:
    spec = items_mod.FINISHED[key]
    parts = []
    for k, v in spec.items():
        if k in ("name", "pairs"):
            continue
        if k == "type_dmg":
            parts.append("、".join(
                f"{TYPE_ZH.get(t, t)}系大招+{round(p * 100)}%"
                for t, p in v.items()))
        elif isinstance(v, bool):
            parts.append(ITEM_KEY_ZH.get(k, k))
        else:
            parts.append(f"{ITEM_KEY_ZH.get(k, k)}+{round(v * 100)}%")
    return "，".join(parts) or "—"


def _synergy_view(sess) -> list:
    from render_mockups import TYPE_COLORS
    comp = [o.piece for o in sess.player.board]
    counts = syn_mod.compute(comp)
    out = []
    for t, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        spec = syn_mod.SYNERGY_TABLE.get(t)
        if not spec:
            continue
        rungs = sorted(spec["tiers"])
        tier = syn_mod.tier_of(n, t)
        nxt = next((x for x in rungs if x > n), None)
        eff = ""
        if tier:
            key_zh = {"speed": "攻速", "dmg": "伤害", "hp": "HP", "heal": "回复",
                      "dr": "减伤", "cap": "大招上限", "energy": "回能",
                      "sp_defense": "特防", "defense": "防御", "atk": "攻击"}
            eff = " ".join(
                f"{key_zh.get(k, k)}+{round(v * 100, 1) if isinstance(v, float) else v}%"
                if not isinstance(v, str) else f"{key_zh.get(k, k)}{v}"
                for k, v in spec["tiers"][tier].items())
        out.append({"type": t, "zh": TYPE_ZH.get(t, t), "n": n, "tier": tier,
                    "next": nxt, "need": (nxt - n) if nxt else 0,
                    "color": _hex(TYPE_COLORS.get(t, (120, 120, 120))),
                    "effect": eff})
    return out


def state_json(sess) -> dict:
    p = sess.player
    from render_mockups import TYPE_COLORS
    weather = weather_for_round(sess.round_no)
    wkey = weather or ""
    board_rows = [[None] * GRID_COLS for _ in range(2)]
    copies = {}
    for o in p.all_pieces():
        copies[o.piece.species_id] = copies.get(o.piece.species_id, 0) + 1
    for (r, c), o in p.grid.items():
        v = _piece_view(o.piece, o.item)
        v["copies"] = copies.get(o.piece.species_id, 1)
        v["sell"] = sell_value(o)
        board_rows[r][c] = v
    bench = []
    for o in p.bench:
        v = _piece_view(o.piece, o.item)
        v["copies"] = copies.get(o.piece.species_id, 1)
        v["sell"] = sell_value(o)
        bench.append(v)
    shop = []
    for i in range(SHOP_SLOTS_UI):
        sid = p.shop.slots[i]
        if sid is None:
            shop.append(None)
        else:
            v = _piece_view(p.templates[sid])
            v["price"] = p.templates[sid].tier
            shop.append(v)
    comps = [{"key": k, "name": items_mod.COMPONENT_NAMES[k], "n": n}
             for k, n in p.inventory.components.items() if n > 0]
    finished = [{"key": k, "name": items_mod.FINISHED[k]["name"],
                 "effect": _item_effect(k)}
                for k in p.inventory.finished]
    craftable = []
    lucky_capped = items_mod.lucky_egg_count(sess.seats) >= \
        items_mod.LUCKY_EGG_GLOBAL_CAP
    for key, spec in items_mod.FINISHED.items():
        if key in p.inventory.finished:
            continue
        pair = p.inventory.craftable(key)
        if pair is None:
            continue
        if key == "lucky_egg" and lucky_capped:
            continue
        recipe = " + ".join(items_mod.COMPONENT_NAMES[c] for c in pair)
        craftable.append({"key": key, "name": spec["name"],
                          "effect": _item_effect(key), "recipe": recipe})
    xp_next = economy.xp_to_next(p.level)
    st = {
        "sid": sess.sid, "seed": sess.seed, "round": sess.round_no,
        "phase": sess.phase, "max_rounds": MAX_ROUNDS,
        "you": {"hp": max(0, p.hp), "gold": p.gold, "level": p.level,
                "xp": p.xp, "xp_next": xp_next, "pop": p.pop(),
                "on_board": len(p.grid), "streak": p.streak,
                "alive": p.alive, "rank": p.rank, "combines": p.combines,
                "stone_used": p.stone_used, "bench_cap": BENCH_CAP,
                "refresh_cost": economy.REFRESH_COST,
                "xp_cost": economy.XP_BUY_COST},
        "weather": {"key": wkey,
                    "zh": weather_mod.WEATHERS[weather]["label"] if weather else "无",
                    "note": WEATHER_NOTE[weather]},
        "shop": shop,
        "board": board_rows,
        "bench": bench,
        "synergies": _synergy_view(sess),
        "items": {"components": comps, "finished": finished,
                  "craftable": craftable},
        "opponent": sess.opp_view,
        "standings": [{"name": e.name, "is_you": e is p,
                       "hp": max(0, e.hp), "level": e.level,
                       "alive": e.alive, "rank": e.rank, "streak": e.streak}
                      for e in sess.seats],
        "log": sess.log[-24:],
        "last_battle": sess.last_battle,
        "stats": {"battles": sess.player_battles,
                  "frames": sess.player_frames_total},
        "type_colors": {t: _hex(c) for t, c in TYPE_COLORS.items()},
    }
    if sess.phase == "over":
        st["over"] = {"ranking": [
            {"name": e.name, "rank": e.rank, "is_you": e is p,
             "hp": max(0, e.hp), "rounds": sess.round_no}
            for e in sorted(sess.seats,
                            key=lambda e: (e.rank is None, e.rank))]}
    return st


# ---------------------------------------------------------------- 动作
def _guard_prep(sess) -> None:
    if not sess.player.alive:
        raise DemoError("你已被淘汰，点「下一轮」观战到终局")
    if sess.phase != "prep":
        raise DemoError("当前不是准备阶段")


def act_buy(sess, i: int):
    _guard_prep(sess)
    p = sess.player
    if not (0 <= i < SHOP_SLOTS_UI) or p.shop.slots[i] is None:
        raise DemoError("这个商店格是空的")
    price = p.shop.price(i)
    if p.gold < price:
        raise DemoError(f"金币不足（需要 {price} 金，你有 {p.gold} 金）")
    if len(p.bench) >= BENCH_CAP:
        raise DemoError(f"备战席已满（{BENCH_CAP} 格）：先把棋子上场或卖出")
    owned = p.shop.buy(i)
    p.gold -= price
    p.bench.append(owned)
    logs = sess.combine_player()
    msg = f"买入 {owned.piece.name}（-{price} 金）"
    for line in logs:
        msg += f"；{line}"
    return msg


def act_sell(sess, loc: str):
    _guard_prep(sess)
    p = sess.player
    owned, where, key = sess.locate(loc)
    if owned.item is not None and owned.item != "evo_stone":
        p.inventory.finished.append(owned.item)   # 卖棋自动卸回仓库（无惩罚）
    gold = shop_mod.sell_owned(owned, sess.pool)
    p.gold += gold
    if where == "bench":
        p.bench.remove(owned)
    else:
        del p.grid[key]
    return f"卖出 {owned.piece.name}（+{gold} 金）"


def act_refresh(sess):
    _guard_prep(sess)
    p = sess.player
    if p.gold < economy.REFRESH_COST:
        raise DemoError(f"金币不足（刷新需 {economy.REFRESH_COST} 金）")
    p.gold -= economy.REFRESH_COST
    p.refresh_j += 1
    sess._roll_player_shop(rng_mod.derive(
        sess.seed, sess.round_no, "shop",
        rng_mod.shop_counter(p.seat, p.refresh_j)))
    return "商店已刷新"


def act_levelup(sess):
    _guard_prep(sess)
    p = sess.player
    if economy.xp_to_next(p.level) is None:
        raise DemoError("已是满级（Lv7 · 9 人口）")
    if p.gold < economy.XP_BUY_COST:
        raise DemoError(f"金币不足（买经验需 {economy.XP_BUY_COST} 金）")
    lv0 = p.level
    p.level, p.xp, p.gold, _ = economy.buy_xp(p.level, p.xp, p.gold)
    return (f"升级！Lv{lv0} → Lv{p.level}（人口 {p.pop()}）"
            if p.level > lv0 else f"+{economy.XP_BUY_AMOUNT} 经验")


def act_move(sess, frm: str, to: str):
    _guard_prep(sess)
    p = sess.player
    src, src_where, src_key = sess.locate(frm)
    # 解析目标（允许交换：目标有棋子则互换位置）
    try:
        if to.startswith("b"):
            ti = int(to[1:])
            if not (0 <= ti < BENCH_CAP):
                raise DemoError(f"备战只有 {BENCH_CAP} 格")
            dst_where, dst_key = "bench", ti
        else:
            m = to[1:].split(",")
            rr, cc = int(m[0]), int(m[1])
            if not (0 <= rr <= 1 and 0 <= cc < GRID_COLS):
                raise DemoError("目标格越界（棋盘 6 列 × 2 行）")
            dst_where, dst_key = "grid", (rr, cc)
    except (IndexError, ValueError):
        raise DemoError(f"无法识别的位置 {to!r}")
    dst = (p.bench[dst_key] if dst_where == "bench"
           and dst_key < len(p.bench) else
           p.grid.get(dst_key) if dst_where == "grid" else None)
    if dst is src:
        raise DemoError("原地不动")
    # 人口约束：备战→空战场格 会让上场数 +1
    if src_where == "bench" and dst_where == "grid" and dst is None:
        if len(p.grid) >= p.pop():
            raise DemoError(f"上场人口已满（{p.pop()}）：先升级或撤下棋子")
    # 执行移动/交换
    if src_where == "bench":
        p.bench.remove(src)
    else:
        del p.grid[src_key]
    if dst is not None:
        if dst_where == "bench":
            p.bench.remove(dst)
        else:
            del p.grid[dst_key]
    if dst_where == "bench":
        if dst_key >= len(p.bench):
            p.bench.append(src)
        else:
            p.bench.insert(dst_key, src)
    else:
        p.grid[dst_key] = src
    if dst is not None:
        if src_where == "bench":
            if src_key >= len(p.bench):
                p.bench.append(dst)
            else:
                p.bench.insert(src_key, dst)
        else:
            p.grid[src_key] = dst
    return (f"{src.piece.name} 移动"
            + (f"（与 {dst.piece.name} 交换）" if dst is not None else ""))


def act_craft(sess, key: str):
    _guard_prep(sess)
    p = sess.player
    if key not in items_mod.FINISHED:
        raise DemoError("未知装备")
    pair = p.inventory.craftable(key)
    if pair is None:
        raise DemoError("组件不足，无法合成这件装备")
    if key == "lucky_egg" and items_mod.lucky_egg_count(sess.seats) >= \
            items_mod.LUCKY_EGG_GLOBAL_CAP:
        raise DemoError("幸运蛋已达全场上限（2 件）")
    p.inventory.craft(key, pair)
    recipe = " + ".join(items_mod.COMPONENT_NAMES[c] for c in pair)
    return f"合成 {items_mod.FINISHED[key]['name']}（{recipe}）"


def act_equip(sess, key: str, loc: str):
    _guard_prep(sess)
    p = sess.player
    if key not in p.inventory.finished:
        raise DemoError("仓库里没有这件装备（先合成）")
    owned, _where, _key = sess.locate(loc)
    if key == "evo_stone":
        if p.stone_used:
            raise DemoError("进化石每局只能触发一次通信进化")
        nxt = items_mod.STONE_TARGETS.get(owned.piece.species_id)
        if nxt is None:
            raise DemoError("进化石只能给勇基拉 / 豪力 / 鬼斯通"
                            "（触发通信进化）")
        if sess.pool.remaining.get(nxt, 0) <= 0:
            raise DemoError("共享池里该进化形态已售罄")
        p.inventory.finished.remove("evo_stone")
        owned.item = "evo_stone"
        sess.pool.take(nxt)
        old = owned.piece.name
        owned.piece = make_piece(nxt, sess.templates)
        owned.sources.append(nxt)
        p.stone_used = True
        return f"通信进化！{old} → {owned.piece.name}（进化石不消耗）"
    if owned.item is not None:
        raise DemoError("该棋子已有装备（每单位 1 格），先卸下再换")
    p.inventory.finished.remove(key)
    owned.item = key
    return f"{owned.piece.name} 装备了 {items_mod.FINISHED[key]['name']}"


def act_unequip(sess, loc: str):
    _guard_prep(sess)
    p = sess.player
    owned, _where, _key = sess.locate(loc)
    if owned.item is None:
        raise DemoError("这个棋子没有装备")
    if owned.item == "evo_stone":
        raise DemoError("进化石已触发通信进化，不能卸下")
    p.inventory.finished.append(owned.item)
    key = owned.item
    owned.item = None
    return f"卸下 {items_mod.FINISHED[key]['name']}（回仓库）"


def _new_session(seed: int) -> Session:
    if len(SESSIONS) >= MAX_SESSIONS:
        oldest = next(iter(SESSIONS))
        _drop_session(oldest)
    sess = Session(seed)
    sess.begin_round(1)   # R1 准备阶段：首轮收入 + 免费商店（与 match 同轨）
    SESSIONS[sess.sid] = sess
    return sess


def _drop_session(sid: str) -> None:
    sess = SESSIONS.pop(sid, None)
    if sess is not None:
        shutil.rmtree(ROOT / ".build" / "demo" / sess.sid, ignore_errors=True)


def api_action(params: dict):
    """/api/demo/action 的总入口。返回 (dict, status)；异常全部转 ok=false。"""
    cmd = params.get("cmd", "")
    try:
        with _LOCK:
            if cmd == "new":
                try:
                    seed = int(params.get("seed") or 7)
                except ValueError:
                    raise DemoError("种子必须是整数")
                sess = _new_session(seed)
                return {"ok": True, "sid": sess.sid,
                        "state": state_json(sess)}
            sid = params.get("sid", "")
            sess = SESSIONS.get(sid)
            if sess is None:
                return {"ok": False, "dead": True,
                        "error": "会话不存在（服务可能已重启），请开新对局"}
            msg = None
            if cmd == "state":
                pass
            elif cmd == "buy":
                msg = act_buy(sess, int(params.get("i", -1)))
            elif cmd == "sell":
                msg = act_sell(sess, params.get("loc", ""))
            elif cmd == "refresh":
                msg = act_refresh(sess)
            elif cmd == "levelup":
                msg = act_levelup(sess)
            elif cmd == "move":
                msg = act_move(sess, params.get("from", ""),
                               params.get("to", ""))
            elif cmd == "bench_to_board":       # move 的语义别名（自测/脚本友好）
                bench_i = params.get("bench", "")
                col = params.get("col", "")
                row = params.get("row", "1")
                msg = act_move(sess, f"b{bench_i}", f"g{row},{col}")
            elif cmd == "craft":
                msg = act_craft(sess, params.get("item", ""))
            elif cmd == "equip":
                msg = act_equip(sess, params.get("item", ""),
                                params.get("loc", ""))
            elif cmd == "unequip":
                msg = act_unequip(sess, params.get("loc", ""))
            elif cmd == "end_prep":
                sess.end_prep()
                msg = "战斗结算完成"
            elif cmd == "next":
                if sess.phase == "prep" and not sess.player.alive:
                    sess.end_prep()   # 淘汰后观战快进：跳过准备直接结算本轮
                if sess.phase == "battle":
                    sess.next_round()
                    msg = f"进入第 {sess.round_no} 轮准备阶段"
                else:
                    msg = "对局已结束"
            else:
                return {"ok": False, "error": f"未知动作 {cmd!r}"}
            out = {"ok": True, "state": state_json(sess)}
            if msg:
                out["msg"] = msg
            return out
    except DemoError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 —— Demo 的 500 屏蔽层
        return {"ok": False, "error": f"内部错误：{exc!r}"}


# ---------------------------------------------------------------- /demo 页面
DEMO_HTML = r"""<!doctype html><html lang="zh-CN">
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>宝可梦自走棋 · Web Demo</title>
<style>
*{box-sizing:border-box}
body{margin:0;background:#f2efe5;color:#29302b;font:14px/1.6 ui-monospace,"PingFang SC",monospace}
main{max-width:1180px;margin:auto;padding:16px}
header{display:flex;align-items:center;gap:12px;border-bottom:2px solid #29302b;padding-bottom:10px;margin-bottom:12px;flex-wrap:wrap}
h1{font-size:19px;margin:0}a{color:#355c3d}
button{font:inherit;color:inherit;background:#fffdf5;border:1px solid #899081;border-radius:4px;padding:7px 12px;cursor:pointer;min-height:36px}
button:hover{background:#e2e8d8}button.primary{background:#355c3d;color:#fff;border-color:#355c3d}
button.primary:hover{background:#28452f}button:disabled{opacity:.45;cursor:default}
input,select{font:inherit;color:inherit;background:#fffdf5;border:1px solid #899081;border-radius:4px;padding:6px 8px}
.muted{color:#8b938a;font-size:12px}
/* HUD */
#hud{display:flex;gap:10px;flex-wrap:wrap;align-items:center;background:#fffdf5;border:1px solid #899081;border-radius:6px;padding:8px 12px;margin-bottom:10px}
#hud b{font-size:16px}
.hudchip{display:flex;gap:6px;align-items:center;padding:2px 10px;border-right:1px dashed #b9b3a0}
.hudchip:last-child{border-right:none}
/* 布局 */
.cols{display:grid;grid-template-columns:minmax(430px,1fr) 330px;gap:14px;align-items:start}
@media(max-width:900px){.cols{grid-template-columns:1fr}}
.panel{background:#fffdf5;border:1px solid #899081;border-radius:6px;padding:10px;margin-bottom:10px}
.panel h3{margin:0 0 8px;font-size:14px;border-bottom:1px solid #d8d2bf;padding-bottom:6px}
/* 棋盘 */
.rowtag{font-size:12px;color:#555e54;margin:4px 2px}
.grid{display:grid;grid-template-columns:repeat(6,64px);gap:4px;justify-content:center}
.cell{position:relative;width:64px;height:58px;border-radius:5px;background:#e9e4d3;border:1px solid #b9b3a0;display:flex;align-items:flex-end;justify-content:center;cursor:default}
.cell.ally{background:#c3cdb9;border-color:#93a186}
.cell.enemy{background:#d9cba6;border-color:#b3a67e}
.cell.bench{background:#e6e0cf;border-style:dashed}
.cell.ebench{background:#e6e0cf;border-style:dashed;opacity:.55}
.cell.empty-ally{cursor:pointer}
.cell img{width:50px;height:50px;image-rendering:pixelated;object-fit:contain;position:relative;z-index:2;pointer-events:none}
.cell .ring{position:absolute;left:8px;right:8px;bottom:2px;height:7px;border:2px solid #29302b;border-radius:4px;z-index:1;pointer-events:none}
.cell .cnt{position:absolute;top:1px;right:3px;font-size:11px;color:#fff;background:#355c3d;border-radius:3px;padding:0 3px;z-index:3}
.cell .eq{position:absolute;top:1px;left:3px;font-size:10px;text-decoration:none;color:#5a4a00;background:radial-gradient(circle,#ffd040,#c99b4a);border-radius:50%;width:16px;height:16px;line-height:16px;text-align:center;z-index:3;font-style:normal}
.cell .rng{position:absolute;bottom:2px;right:2px;font-size:10px;font-style:normal;color:#fff;border-radius:3px;padding:0 3px;line-height:14px;z-index:3}
.cell .rng.near{background:#8a4a2f}.cell .rng.far{background:#2f5a8a}
#warnfight{display:none;color:#fff;background:#8a2f27;border-radius:4px;padding:6px 10px;font-size:12px;animation:blink 1.2s infinite}
@keyframes blink{50%{opacity:.55}}
.cell.has-item{box-shadow:0 0 0 2px #e0a010 inset}
.cell.sel{outline:3px solid #355c3d;outline-offset:1px;z-index:5}
.cell.pickme{outline:3px dashed #c99b4a;outline-offset:1px}
.midline{display:flex;align-items:center;gap:8px;color:#555e54;font-size:12px;margin:6px 0}
.midline:before,.midline:after{content:"";flex:1;border-top:2px dashed #899081}
#info{min-height:56px;background:#fffdf5;border:1px solid #899081;border-radius:6px;padding:8px 10px;margin-top:10px;font-size:13px}
#info .btns{margin-top:6px;display:flex;gap:8px;flex-wrap:wrap}
#info button{min-height:30px;padding:4px 10px}
/* 商店 */
#shop{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:10px}
.shopcell{background:#fffdf5;border:1px solid #899081;border-radius:6px;padding:6px;cursor:pointer;text-align:center}
.shopcell:hover{background:#e2e8d8}
.shopcell img{width:56px;height:56px;image-rendering:pixelated;object-fit:contain}
.shopcell .nm{font-size:12px}
.shopcell .pr{font-size:12px;color:#8a5a17}
.shopcell.off{opacity:.4;cursor:default}
#actions{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}
#actions button{flex:1;min-width:96px}
/* 侧栏 */
.syrow{display:flex;align-items:center;gap:6px;padding:3px 4px;border-radius:3px;font-size:12px}
.syrow.on{background:#e5efe0}
.syrow .dot{width:10px;height:10px;border-radius:3px;flex:none}
.syrow .cnt2{margin-left:auto;color:#555e54}
.itrow{display:flex;align-items:center;gap:6px;font-size:12px;padding:3px 2px;flex-wrap:wrap}
.itrow button{min-height:26px;padding:2px 8px;font-size:12px}
.itchip{border:1px solid #c99b4a;background:#f7ecd2;border-radius:4px;padding:2px 8px;cursor:pointer;font-size:12px}
.itchip.on{outline:2px solid #c99b4a}
.strow{display:flex;gap:8px;align-items:center;font-size:12px;padding:2px 4px}
.strow .hpbar{flex:1;height:8px;background:#e6e0cf;border-radius:3px;overflow:hidden}
.strow .hpbar i{display:block;height:100%;background:#7fa383}
.strow.dead{opacity:.5;text-decoration:line-through}
#log{font-size:12px;max-height:180px;overflow-y:auto;line-height:1.5}
/* 战斗浮层 */
#overlay{position:fixed;inset:0;background:rgba(23,29,39,.82);display:none;align-items:center;justify-content:center;z-index:50;padding:12px}
#overlay.show{display:flex}
.bwrap{display:flex;gap:14px;align-items:flex-start;flex-wrap:wrap;justify-content:center;max-height:96vh}
.bstage{background:#171d27;border:2px solid #899081;border-radius:10px;padding:12px}
canvas{display:block;width:480px;max-width:92vw;image-rendering:pixelated;background:#171d27;border-radius:4px}
.bctl{display:flex;gap:6px;margin-top:8px;flex-wrap:wrap;justify-content:center}
.bctl button{min-height:32px;padding:4px 10px;background:#fffdf5}
.bside{width:min(360px,92vw);max-height:92vh;overflow-y:auto}
.bside .panel{margin-bottom:10px}
#evlist{font-size:12px;max-height:300px;overflow-y:auto}
#evlist div{padding:1px 6px;border-radius:3px;color:#8b938a}
#evlist div.past{color:#3d453f}
#evlist div.now{background:#e5efe0;color:#28432c;font-weight:600}
#battle-report{font-size:13px;line-height:1.7}
.rank1{color:#8a5a17;font-weight:700}
/* toast */
#toast{position:fixed;left:50%;bottom:26px;transform:translateX(-50%);background:#292c35;color:#f2e8c9;padding:10px 18px;border-radius:6px;opacity:0;transition:opacity .25s;pointer-events:none;z-index:99;max-width:80vw;font-size:13px}
#toast.show{opacity:.96}
#toast.err{background:#8a2f27;color:#fff}
</style></head><body><main>
<header>
<h1>宝可梦自走棋 · Web 可玩 Demo</h1>
<span class="muted">1 玩家 + 7 bot · 全系统开启（羁绊/装备/齐射/天气/状态）</span>
<span style="flex:1"></span>
<input id="seedin" type="number" value="7" min="1" max="99999" style="width:90px" title="种子">
<button class="primary" onclick="newGame()">开新对局</button>
<a href="/" class="muted">← 验收后台</a>
</header>
<div id="hud" class="muted">加载中…</div>
<div class="cols">
<section>
  <div id="arena"></div>
  <div id="info" class="muted">点击商店买入 → 点击棋子 → 点击目标格摆位。3 只同种自动进化！</div>
  <div id="shop"></div>
  <div id="actions">
    <button id="btn-refresh" onclick="api('refresh')">刷新（2 金）</button>
    <button id="btn-xp" onclick="api('levelup')">买经验（4 金 +4XP）</button>
    <button id="btn-fill" onclick="fillBoard()">一键上场</button>
    <button id="btn-auto" onclick="toggleAuto()">▶ 自动试玩</button>
    <button id="btn-fight" class="primary" onclick="endPrep()">开战 ▶</button>
    <span id="warnfight">⚠ 上场为空</span>
  </div>
  <p class="muted" id="tips">准备阶段不限时；开战后自动战斗。败方掉血 = 2 + 对方存活棋子 × 阶段系数；每 5 轮野怪轮掉装备组件。HP 归零淘汰，活到最后就是冠军。</p>
</section>
<aside>
  <div class="panel"><h3>羁绊（按上场阵容）</h3><div id="syn" class="muted">—</div></div>
  <div class="panel"><h3>装备仓库</h3><div id="items" class="muted">—</div></div>
  <div class="panel"><h3>场上局势</h3><div id="standings"></div></div>
  <div class="panel"><h3>战报</h3><div id="log" class="muted">—</div></div>
</aside>
</div>
</main>
<div id="overlay"><div class="bwrap">
  <div class="bstage">
    <canvas id="cv" width="240" height="320"></canvas>
    <div class="bctl">
      <button onclick="btoggle()" id="bplay">▶ 播放</button>
      <select id="bspeed" onchange="bspeed()"><option value="1" selected>1x</option><option value="2">2x</option><option value="4">4x</option></select>
      <button onclick="breplay()">↻ 重播</button>
      <button onclick="bskip()">跳过 ⏭</button>
    </div>
    <p class="muted" id="bstatus" style="text-align:center;color:#b9b3a0;margin:6px 0 0"></p>
  </div>
  <div class="bside">
    <div class="panel"><h3 id="bhead">战斗</h3><div id="battle-report"></div>
      <div style="margin-top:10px"><button class="primary" style="width:100%" onclick="nextRound()" id="btn-next">下一轮 ▶</button></div>
    </div>
    <div class="panel"><h3>事件流（与画面逐条对照）</h3><div id="evlist"></div></div>
  </div>
</div></div>
<div id="toast"></div>
<script>
let S=null, sid="", selLoc=null, equipKey=null;
const $=id=>document.getElementById(id);
function toast(t,err){const el=$('toast');el.textContent=t;el.className='show'+(err?' err':'');clearTimeout(el._t);el._t=setTimeout(()=>el.className='',2600);}
async function api(cmd,params={}){
  const q=new URLSearchParams({cmd,sid,...params});
  const r=await fetch('/api/demo/action?'+q.toString());
  const j=await r.json();
  if(!j.ok&&j.error){toast(j.error,true);if(j.dead){sid='';}}
  if(j.state){S=j.state;render();}
  if(j.msg)toast(j.msg);
  return j;
}
function newGame(){api('new',{seed:$('seedin').value||'7'}).then(j=>{if(j.ok){sid=j.sid;selLoc=equipKey=null;toast('对局开始：先买几只棋子上场吧');}});}
/* ---------- 渲染 ---------- */
function pieceCell(v,loc,cls){
  /* 空格子也带 data-loc（仅我方格）——2026-09-14 E2E 发现的 UI 级根因：
     空格无 data-loc 则点击委托命中不了，玩家没有任何途径把棋子放上场
     （只能空场开战 → 无帧 → 播放器黑屏）。敌方格保持不可点。 */
  if(!v)return `<div class="cell ${cls}"${(cls.includes('ally')||cls.includes('bench'))&&loc?` data-loc="${loc}"`:''}></div>`;
  const sel=(selLoc===loc)?' sel':'';
  const pick=(equipKey&&(cls.includes('ally')||cls.includes('bench')))?' pickme':'';
  return `<div class="cell ${cls}${sel}${pick}${v.item?' has-item':''}" data-loc="${loc}" title="${v.name} ${v.tier}费 ${v.types.join('/')} ${v.ranged?'远程':'近战'} 招式:${v.move}${v.item?' 装备:'+v.item_name:''}">
    <img loading="lazy" src="/demo/sprite/${v.sid}.png" draggable="false">
    <i class="ring" style="border-color:${v.colors[0]}"></i>
    <i class="rng ${v.ranged?'far':'near'}" title="${v.ranged?'远程（射程3）':'近战（射程1·突进）'}">${v.ranged?'远':'近'}</i>
    ${v.copies>=2?`<b class="cnt">×${Math.min(v.copies,3)}</b>`:''}
    ${v.item?'<i class="eq">装</i>':''}</div>`;
}
function render(){
  if(!S)return;
  const y=S.you;
  /* HUD */
  const w=S.weather;
  $('hud').innerHTML=[
    `<span class="hudchip">❤ HP <b>${y.hp}</b></span>`,
    `<span class="hudchip">🪙 <b>${y.gold}</b> 金</span>`,
    `<span class="hudchip">Lv${y.level} <span class="muted">(${y.xp}/${y.xp_next??'满'})</span> 人口 <b>${y.on_board}/${y.pop}</b></span>`,
    `<span class="hudchip">第 <b>${S.round}</b>/${S.max_rounds} 轮</span>`,
    `<span class="hudchip">${w.zh==='无'?'🌤':w.key==='sun'?'☀️':w.key==='rain'?'🌧️':w.key==='sand'?'🌪️':w.key==='hail'?'❄️':'🌤'} ${w.zh}<span class="muted">（${w.note}）</span></span>`,
    y.streak?`<span class="hudchip">${y.streak>0?'🔥 连胜':'💤 连败'} <b>${Math.abs(y.streak)}</b></span>`:'',
    `<span class="hudchip muted">${S.phase==='prep'?'准备阶段（不限时）':S.phase==='battle'?'结算阶段':'终局'}</span>`,
    y.alive?'':`<span class="hudchip" style="color:#8a2f27">已淘汰（第 ${y.rank} 名）</span>`
  ].join('');
  /* 棋盘 */
  const ov=S.opponent;
  let ar=`<div class="rowtag">敌方备战（${ov?ov.name:'—'} 的快照）</div>`;
  ar+=`<div class="grid">${(ov?ov.bench:[]).concat(Array(6).fill(null)).slice(0,6).map(v=>pieceCell(v,'','ebench')).join('')}</div>`;
  const erows=ov?ov.rows:[[],[]];
  ar+=`<div class="grid">${(erows[0]||[]).concat(Array(6).fill(null)).slice(0,6).map(v=>pieceCell(v,'','enemy')).join('')}</div>`;
  ar+=`<div class="grid">${(erows[1]||[]).concat(Array(6).fill(null)).slice(0,6).map(v=>pieceCell(v,'','enemy')).join('')}</div>`;
  ar+=`<div class="midline">战 场 中 线</div>`;
  ar+=`<div class="grid">${S.board[0].map((v,c)=>pieceCell(v,`g0,${c}`,'ally empty-ally')).join('')}</div>`;
  ar+=`<div class="grid">${S.board[1].map((v,c)=>pieceCell(v,`g1,${c}`,'ally empty-ally')).join('')}</div>`;
  ar+=`<div class="rowtag">我方备战（${S.bench.length}/${y.bench_cap}）</div>`;
  ar+=`<div class="grid">${Array(6).fill(null).map((_,i)=>pieceCell(S.bench[i]||null,`b${i}`,'bench empty-ally')).join('')}</div>`;
  $('arena').innerHTML=ar;
  /* 选中信息 */
  renderInfo();
  /* 商店 */
  const canBuy=S.phase==='prep'&&y.alive;
  $('shop').innerHTML=S.shop.map((v,i)=>v?`<div class="shopcell ${canBuy?'':'off'}" data-shop="${i}" title="${v.types.join('/')} ${v.ranged?'远程':'近战'} · ${v.move}">
    <img loading="lazy" src="/demo/sprite/${v.sid}.png"><div class="nm">${v.name}</div><div class="pr">🪙${v.price} · ${v.tier}费 · <b style="color:${v.ranged?'#2f5a8a':'#8a4a2f'}">${v.ranged?'远程':'近战'}</b></div></div>`:
    `<div class="shopcell off"><div class="nm muted">空</div></div>`).join('');
  $('btn-refresh').disabled=$('btn-xp').disabled=$('btn-fight').disabled=!canBuy;
  $('btn-fight').style.display=(S.phase==='prep')?'':'none';
  /* 空场防呆：按当前状态给下一步指引（2026-09-14 用户反馈——棋子买了/
     选中了但还在备战时，「上场为空」读起来像矛盾，改为指引文案） */
  const wf=$('warnfight');
  const benchN=S.bench.filter(Boolean).length;
  if(S.phase==='prep'&&y.alive&&y.on_board===0){
    wf.style.display='inline-block';
    wf.textContent=selLoc?'→ 已选中棋子：点击棋盘任意格完成上场':
      (benchN?'⚠ 棋子还在备战席（'+benchN+' 只）：点棋子 → 点棋盘格上场，或点「一键上场」':
              '⚠ 上场为空：先从下方商店买几只棋子');
  }else wf.style.display='none';
  $('btn-fill').style.display=(S.phase==='prep'&&y.alive&&benchN&&y.on_board<y.pop)?'':'none';
  /* 羁绊 */
  $('syn').innerHTML=S.synergies.length?S.synergies.map(s=>`<div class="syrow ${s.tier?'on':''}">
    <span class="dot" style="background:${s.color}"></span><b>${s.zh}</b> ×${s.n}
    ${s.tier?`<span class="badge on">(${s.tier}) ${s.effect}</span>`:'<span class="muted">未激活</span>'}
    <span class="cnt2">${s.next?`还差 ${s.need} 只到 (${s.next})`:'已满档'}</span></div>`).join(''):'<span class="muted">上场棋子后显示羁绊计数</span>';
  /* 装备 */
  let it='';
  it+='<div class="itrow"><b>组件</b>：'+(S.items.components.length?S.items.components.map(c=>`<span class="itchip" style="cursor:default;border-color:#899081;background:#e9e4d3">${c.name}×${c.n}</span>`).join(' '):'<span class="muted">暂无（野怪轮掉落）</span>')+'</div>';
  it+='<div class="itrow"><b>可合成</b>：'+(S.items.craftable.length?S.items.craftable.map(c=>`<button onclick="api(\'craft\',{item:\'${c.key}\'})" title="${c.recipe} → ${c.effect}">${c.name}</button>`).join(' '):'<span class="muted">组件凑齐配方后出现</span>')+'</div>';
  it+='<div class="itrow"><b>成品</b>：'+(S.items.finished.length?S.items.finished.map(f=>`<span class="itchip ${equipKey===f.key?'on':''}" data-item="${f.key}" title="${f.effect}（点击后选择棋子装备）">${f.name}</span>`).join(' '):'<span class="muted">无</span>')+'</div>';
  $('items').innerHTML=it;
  /* 排名 */
  $('standings').innerHTML=S.standings.map(e=>`<div class="strow ${e.alive?'':'dead'}">
    <b style="width:8em;overflow:hidden;text-overflow:ellipsis">${e.is_you?'★ ':''}${e.name}</b>
    <span class="hpbar"><i style="width:${Math.max(0,e.hp)}%"></i></span>
    <span class="muted">${e.hp}HP L${e.level}${e.rank?' 第'+e.rank+'名':''}</span></div>`).join('');
  /* 战报 */
  $('log').innerHTML=S.log.length?S.log.map(l=>`<div>${l}</div>`).join(''):'<span class="muted">尚无战报</span>';
}
function findPiece(loc){
  if(loc.startsWith('b'))return S.bench[+loc.slice(1)];
  const m=loc.slice(1).split(',');
  return S.board[+m[0]][+m[1]];
}
function renderInfo(){
  const el=$('info');
  if(!selLoc){el.className='muted';el.innerHTML='点击商店买入 → 点击棋子 → 点击目标格摆位。3 只同种自动进化！金环 = 持有装备。';return;}
  const v=findPiece(selLoc);
  if(!v){selLoc=null;return renderInfo();}
  el.className='';
  el.innerHTML=`<b>${v.name}</b> · ${v.tier} 费 · ${v.types.join('/')} · ${v.ranged?'远程':'近战'} · 招式「${v.move}」${v.copies>=2?` · 同种已有 ${v.copies} 只（3 只自动进化）`:''}${v.item?` · 装备「${v.item_name}」`:''}
  <div class="btns"><button onclick="api('sell',{loc:selLoc}).then(()=>{selLoc=null})">卖出（+${v.sell} 金）</button>
  ${v.item?`<button onclick="api('unequip',{loc:selLoc})">卸下装备</button>`:''}</div>`;
}
/* ---------- 点击流 ---------- */
document.addEventListener('click',e=>{
  const shop=e.target.closest('[data-shop]');
  if(shop){if(!shop.classList.contains('off'))api('buy',{i:shop.dataset.shop});return;}
  const item=e.target.closest('[data-item]');
  if(item){equipKey=(equipKey===item.dataset.item)?null:item.dataset.item;toast(equipKey?'已选中装备，点击要装备的棋子（金框提示中）':'已取消选择');render();return;}
  const cell=e.target.closest('[data-loc]');
  if(!cell||!cell.dataset.loc)return;
  onCell(cell.dataset.loc);
});
function onCell(loc){
  if(!S||S.phase!=='prep'||!S.you.alive)return;
  const isMine=!loc.startsWith('x');
  if(!isMine)return;
  if(equipKey){api('equip',{item:equipKey,loc}).then(j=>{if(j.ok)equipKey=null;});return;}
  const v=findPiece(loc);
  if(selLoc===null){if(v)selLoc=loc;render();return;}
  if(selLoc===loc){selLoc=null;render();return;}
  const from=selLoc;selLoc=null;
  api('move',{from,to:loc});
}
async function fillBoard(){
  /* 一键上场：把备战棋子依次搬到棋盘空格（前排 g0 先填），人口满/备战空即停 */
  if(!S||S.phase!=='prep'||!S.you.alive)return;
  for(let k=0;k<12;k++){
    if(S.you.on_board>=S.you.pop){toast('人口已满（买经验升级可上场更多）');break;}
    const bi=S.bench.findIndex(Boolean);
    if(bi<0)break;
    let hole=null;
    for(const r of [0,1]){for(let c=0;c<6;c++){if(!S.board[r][c]){hole=`g${r},${c}`;break;}}if(hole)break;}
    if(!hole)break;
    const j=await api('move',{from:'b'+bi,to:hole});
    if(!j.ok)break;
  }
}
/* ---------- 自动试玩：客户端驱动完整一局（买棋→摆位→开战→播动画→下一轮→终局） ---------- */
let autoOn=false,autoGen=0;
const autoSleep=ms=>new Promise(r=>setTimeout(r,ms));
function toggleAuto(){
  autoOn=!autoOn;autoGen++;
  const b=$('btn-auto');
  b.textContent=autoOn?'⏸ 停止自动试玩':'▶ 自动试玩';
  b.classList.toggle('primary',autoOn);
  if(autoOn){const g=autoGen;autoLoop(g);toast('自动试玩开始：全程自动决策与播放，可随时接手');}
}
function autoStop(msg){if(!autoOn)return;autoOn=false;autoGen++;$('btn-auto').classList.remove('primary');$('btn-auto').textContent='▶ 自动试玩';if(msg)toast(msg);}
function autoBoardPieces(){return [...S.board[0],...S.board[1]].filter(Boolean);}
function autoTypeCounts(){const c={};autoBoardPieces().forEach(v=>v.types.forEach(t=>c[t]=(c[t]||0)+1));return c;}
function autoTargetCell(v){
  /* 近战前排（g0 贴中线）、远程后排（g1）——与角标语义一致 */
  const rows=v&&v.ranged?[1,0]:[0,1];
  for(const r of rows)for(let c=0;c<6;c++)if(!S.board[r][c])return `g${r},${c}`;
  return null;
}
function autoWantBuy(){
  const y=S.you,mine=[...autoBoardPieces(),...S.bench.filter(Boolean)];
  if(S.bench.filter(Boolean).length>=y.bench_cap-1&&y.on_board>=y.pop)return -1;
  const tc=autoTypeCounts();
  let best=-1,score=-1;
  S.shop.forEach((c,i)=>{
    if(!c||y.gold-c.price<2)return;
    let s=c.tier*10;
    s+=mine.filter(v=>v.sid===c.sid).length*55;          /* 复制件：3合1 进度 */
    s+=c.types.reduce((a,t)=>a+(tc[t]||0)*9,0);          /* 供主羁绊 */
    if(s>score){score=s;best=i;}
  });
  return best;
}
function autoFirstFreeHand(){
  for(const r of [0,1])for(let c=0;c<6;c++){const v=S.board[r][c];if(v&&!v.item)return `g${r},${c}`;}
  for(let i=0;i<S.bench.length;i++){if(S.bench[i]&&!S.bench[i].item)return 'b'+i;}
  return null;
}
function autoAllFreeHands(){
  const spots=[];
  for(const r of [0,1])for(let c=0;c<6;c++){if(S.board[r][c]&&!S.board[r][c].item)spots.push(`g${r},${c}`);}
  for(let i=0;i<S.bench.length;i++){if(S.bench[i]&&!S.bench[i].item)spots.push('b'+i);}
  return spots;
}
let autoSkipRound=-1,autoSkipItems=new Set();
function autoTickSkip(){
  if(S&&S.round!==autoSkipRound){autoSkipRound=S.round;autoSkipItems.clear();}
}
async function autoStep(){
  if(!S)return;
  if(S.phase==='over'){
    const my=(S.over&&S.over.ranking||[]).find(e=>e.is_you);
    autoStop('自动试玩结束：'+(my?`第 ${my.rank} 名（${S.round} 轮）`:'终局'));return;
  }
  if(S.phase==='prep'){
    if(!S.you.alive){await api('next');return;}          /* 淘汰后观战快进 */
    const y=S.you;
    autoTickSkip();
    /* 决策优先级：合成 → 装备 → 上场 → 买棋 → 升级 → 刷新 → 卖冗余 → 开战。
       合成/装备失败（如进化石只走通信进化、围巾无载体）不 return——
       穿透到下一优先级继续行动，该成品本轮记跳防反复空打（R11 卡死
       根因：进化石装备被拒 + 状态不变 → 空闲超时）。 */
    for(const c of S.items.craftable||[]){
      if(autoSkipItems.has('craft:'+c.key))continue;
      const j=await api('craft',{item:c.key});
      if(j.ok)return;
      autoSkipItems.add('craft:'+c.key);
    }
    for(const f of S.items.finished||[]){
      if(autoSkipItems.has('equip:'+f.key))continue;
      let done=false;
      for(const loc of autoAllFreeHands()){
        const j=await api('equip',{item:f.key,loc});
        if(j.ok){done=true;break;}
      }
      if(done)return;
      autoSkipItems.add('equip:'+f.key);
    }
    if(y.on_board<y.pop){
      const bi=S.bench.findIndex(Boolean);
      if(bi>=0){const cell=autoTargetCell(S.bench[bi]);if(cell){await api('move',{from:'b'+bi,to:cell});return;}}
    }
    const want=autoWantBuy();
    if(want>=0){await api('buy',{i:want});return;}
    if(y.gold>=8&&y.level<7&&S.round>=4){await api('levelup');return;}
    if(y.gold>=8&&S.round>=6&&autoWantBuy()<0&&S.bench.filter(Boolean).length<y.bench_cap-2){await api('refresh');return;}
    if(S.bench.filter(Boolean).length>=y.bench_cap){await api('sell',{loc:'b'+(S.bench.filter(Boolean).length-1)});return;}
    await api('end_prep');openBattle();return;
  }
  /* battle：等动画播完再进下一轮（无帧场面短等即走） */
  if(!$('overlay').classList.contains('show'))openBattle();
  if(bn>0&&(playing||bcur<bn-1))return;
  await api('next');
}
async function autoLoop(gen){
  /* 卡死盯防的签名含全部会动的量（轮次/相位/金币/人口/等级/XP/备战/成品/
     播放游标）：准备期升级连买经验不涨轮次、战斗期逐帧播放不涨轮次，
     都是正常推进——只有签名完全不变才计空闲 */
  const sig=()=>S?[S.round,S.phase,S.you.gold,S.you.on_board,S.you.level,
    S.you.xp,S.bench.filter(Boolean).length,(S.items.finished||[]).length,
    (S.items.craftable||[]).length,bcur].join('|'):'';
  let last=sig(),idle=0;
  while(autoOn&&gen===autoGen){
    if(document.hidden){await autoSleep(600);continue;}   /* 后台标签不推进 */
    try{await autoStep();}catch(e){/* 单步失败退避重试 */}
    const now=sig();
    idle=now!==last?0:idle+1;
    last=now;
    if(idle>60){autoStop('自动试玩空闲超时停止（疑似异常）');return;}
    await autoSleep(S&&S.phase==='prep'?560:650);
  }
}
async function endPrep(){
  if(!autoOn&&S.board[0].every(c=>!c)&&S.board[1].every(c=>!c)&&S.you.alive){
    if(!confirm('上场为空：开战将不战而败（掉血且没有战斗画面）。\n\n建议先从商店买几只棋子并点击上场（或点「一键上场」）。\n确定仍然开战？'))return;
  }
  const j=await api('end_prep');
  if(j.ok)openBattle();
}
async function nextRound(){
  if(S.phase==='over'){closeBattle();return;}
  const j=await api('next');
  closeBattle();
  if(j.ok&&S.phase==='over')toast('对局结束');
}
/* ---------- 战斗回放 ---------- */
let frames=[],bcur=0,bn=0,btimer=null,bspeedv=1,playing=false,bevs=[],bmeta=null;
function openBattle(){
  bmeta=S.last_battle;frames=[];bcur=0;playing=false;btimer&&clearInterval(btimer);btimer=null;
  $('overlay').classList.add('show');
  const rep=[];
  rep.push(`<b>${bmeta?bmeta.headline:''}</b>`);
  rep.push(...S.log.slice(-6).map(l=>`<div>${l}</div>`));
  if(S.phase==='over'&&S.over){rep.push('<hr><b>最终排名</b><ol style="margin:6px 0;padding-left:22px">'+S.over.ranking.map(r=>`<li class="${r.rank===1?'rank1':''}">${r.is_you?'★ ':''}${r.name}</li>`).join('')+'</ol>');}
  $('battle-report').innerHTML=rep.join('');
  $('btn-next').textContent=S.phase==='over'?'查看终局 ▶':'下一轮 ▶';
  if(!bmeta||!bmeta.n){
    $('bhead').textContent='战斗结算';
    const ctx=$('cv').getContext('2d');
    ctx.clearRect(0,0,240,320);
    /* 空场等原因没有帧：画布上直接给出大字说明，不再留黑屏 */
    ctx.fillStyle='#e8e2cf';ctx.textAlign='center';
    ctx.font='bold 18px monospace';ctx.fillText('本场无战斗画面',120,132);
    ctx.font='13px monospace';ctx.fillStyle='#b9b3a0';
    const why=S.you&&!S.you.alive?'你已被淘汰（观战快进）':
      (S.you&&S.you.on_board===0?'我方空场 · 不战而败掉血':'空场判负 / 野怪轮空');
    ctx.fillText(why,120,158);
    ctx.fillText('下一轮记得买棋上场',120,178);
    $('bstatus').textContent='本场无战斗画面（'+(S.you&&S.you.on_board===0?'我方空场':'空场判负/轮空')+'）';
    $('evlist').innerHTML='<div class="muted">本场景没有战斗事件流</div>';return;}
  $('bhead').textContent=`第 ${bmeta.round} 轮战斗 vs ${bmeta.opp_name}`;
  bevs=bmeta.events||[];
  $('evlist').innerHTML=bevs.map((e,i)=>`<div id="ev${i}">[${e.t.toFixed(1)}] ${e.text}</div>`).join('');
  bn=bmeta.n;
  loadAndPlay();
}
async function loadAndPlay(){
  $('bstatus').textContent='战斗帧载入中…（'+bn+' 帧）';
  const jobs=[];
  for(let i=0;i<bn;i++)jobs.push(new Promise(res=>{const im=new Image();im.onload=im.onerror=()=>res();im.src=`/demo/frame/${sid}/r${bmeta.round}/${i}.png`;frames[i]=im;}));
  await Promise.all(jobs);
  $('bstatus').textContent=bn+' 帧就绪 @10fps';
  play();
}
function bshow(i){
  bcur=Math.max(0,Math.min(bn-1,i));
  const im=frames[bcur];
  if(im&&im.width){const ctx=$('cv').getContext('2d');ctx.clearRect(0,0,240,320);ctx.drawImage(im,0,0);}
  $('bstatus').textContent=`第 ${bcur+1} / ${bn} 帧 · ${(bcur*0.1).toFixed(1)}s`;
  let last=-1;
  for(let j=0;j<bevs.length;j++){const el=$('ev'+j);if(!el)continue;const past=bevs[j].t<=bcur*0.1+1e-9;el.className=past?'past':'';if(past)last=j;}
  if(last>=0){const el=$('ev'+last);el.className='now';el.scrollIntoView({block:'nearest'});}
}
function btick(){bshow(bcur+1);if(bcur>=bn-1)stopPlay();}
function play(){if(playing)return;playing=true;$('bplay').textContent='⏸ 暂停';btimer=setInterval(btick,100/bspeedv);}
function stopPlay(){playing=false;clearInterval(btimer);btimer=null;$('bplay').textContent='▶ 播放';}
function btoggle(){playing?stopPlay():(bcur>=bn-1&&bshow(0),play());}
function breplay(){stopPlay();bshow(0);play();}
function bskip(){stopPlay();bshow(bn-1);}
function bspeed(){bspeedv=+$('bspeed').value;if(playing){stopPlay();play();}}
function closeBattle(){stopPlay();$('overlay').classList.remove('show');}
document.addEventListener('visibilitychange',()=>{if(document.hidden)stopPlay();});
/* ---------- 启动 ---------- */
(async()=>{newGame();})();
</script></body></html>"""
