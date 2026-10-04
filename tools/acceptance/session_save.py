"""PokeTactics snapshot codec. Storage/backup policy lives in esp32_runtime.

Schema 1 records owned accounting explicitly: the same species can be bought,
merged or stone-evolved with different sources and investment. Loading never
calls begin_round, decide, roll or combat: income/rewards cannot be replayed.
"""
import copy
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMMON = ("gold", "hp", "level", "xp", "streak", "alive", "rank", "last_damage",
          "combines", "stone_used", "item_drops")
BOT_STATS = ("gold_curve", "pop_curve", "synergy_curve", "synergy_formed_round",
             "synergy_formed_type", "refreshes", "item_crafts", "item_equips",
             "stone_triggers", "craft_stats")


def rules_fingerprint():
    digest = hashlib.sha256()
    for path in sorted((ROOT / "sim").glob("*.py")) + sorted((ROOT / "data").glob("*.json")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"存档字段 {label} 超出范围")
    return value


def sequence(value, maximum, label):
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(f"存档字段 {label} 列表无效")
    return value


def owned_record(owned):
    return {"species": owned.piece.species_id, "item": owned.item,
            "sources": list(owned.sources), "invested": owned.invested}


def comp_record(comp):
    return [{"species": p[0].species_id, "item": p[1]} if isinstance(p, tuple)
            else {"species": p.species_id, "item": None} for p in comp]


class SessionCodec:
    game_id = "poketactics"
    schema_version = 1

    def encode(self, state):
        seats = []
        for seat in state.seats:
            data = {key: getattr(seat, key) for key in COMMON}
            data.update({"seat": seat.seat, "shop": list(seat.shop.slots),
                         "board": [owned_record(o) for o in seat.board],
                         "bench": [owned_record(o) for o in seat.bench],
                         "components": dict(seat.inventory.components),
                         "finished": list(seat.inventory.finished),
                         "last_opponent": getattr(getattr(seat, "_last_opp", None), "seat", None)})
            if seat.seat == 0:
                data.update({"grid": [[r, c, owned_record(seat.grid[(r, c)])]
                                      for r, c in sorted(seat.grid)],
                             "refresh_j": seat.refresh_j, "shop_locked": seat.shop_locked})
            else:
                data.update({"ability": seat.ability, "personality": seat.pers_key,
                             "target_types": list(seat.target_types),
                             "stats": {key: copy.deepcopy(getattr(seat, key)) for key in BOT_STATS}})
            seats.append(data)
        meta = state.last_battle
        summary = ({key: copy.deepcopy(meta[key]) for key in
                    ("winner", "survivors", "duration", "round", "pve", "ghost") if key in meta}
                   if meta else None)
        payload = {"rules": rules_fingerprint(), "seed": state.seed, "round": state.round_no,
                "phase": state.phase, "seats": seats,
                "pool": {str(k): v for k, v in state.pool.remaining.items()},
                "pairs": [[a.seat, b.seat] for a, b in state.pairs] if state.pairs is not None else None,
                "ghost_seat": getattr(state.ghost_seat, "seat", None),
                "ghost_source": getattr(state.ghost_src, "seat", None),
                "opponent_comp": comp_record(state.opponent_comp) if state.opponent_comp is not None else None,
                "log": list(state.log), "last_battle": summary,
                "player_battles": state.player_battles, "player_frames_total": state.player_frames_total,
                "eliminated_round": state.eliminated_round,
                "final_team": [{"species": o["sid"], "item": o.get("item")}
                               for o in state.final_team] if state.final_team is not None else None}
        # Normalize tuple-based metric curves and integer-keyed survivor maps;
        # the shared runtime deliberately accepts strict, portable JSON only.
        return json.loads(json.dumps(payload, ensure_ascii=False, allow_nan=False))

    def decode(self, payload, schema_version):
        if schema_version != 1:
            raise ValueError("不支持的 PokeTactics 存档版本")
        try:
            return self._decode(payload)
        except (KeyError, TypeError, AttributeError, IndexError) as exc:
            raise ValueError("存档结构不完整或字段类型错误") from exc

    def _decode(self, data):
        import demo
        from bots import PERSONALITIES
        state = demo.Session(integer(data["seed"], -(2 ** 63), 2 ** 63 - 1, "seed"))
        state.round_no = integer(data["round"], 1, demo.MAX_ROUNDS, "round")
        if data["phase"] not in ("prep", "battle", "over"):
            raise ValueError("无效的对局阶段")
        state.phase = data["phase"]
        held = Counter()

        def piece(record, owned=True):
            sid = integer(record["species"], 1, 151, "species")
            if sid not in state.templates:
                raise ValueError("存档包含当前版本不支持的棋子")
            item = record["item"]
            if item is not None and item not in demo.items_mod.FINISHED:
                raise ValueError("未知装备")
            template = state.templates[sid]
            if not owned:
                return (template, item) if item else template
            sources = sequence(record["sources"], 128, "sources")
            if not sources or sid not in sources:
                raise ValueError("棋子来源账本缺失")
            for source in sources:
                if type(source) is not int or source not in state.templates:
                    raise ValueError("棋子来源账本无效")
            investment = integer(record["invested"], 1, sum(state.templates[s].tier for s in sources), "invested")
            result = demo.shop_mod.OwnedPiece(template, investment)
            result.sources, result.item = list(sources), item
            held.update(sources)
            return result

        records = sequence(data["seats"], 8, "seats")
        if len(records) != 8 or [s["seat"] for s in records] != list(range(8)):
            raise ValueError("存档必须包含完整且唯一的八个席位")
        ranks = []
        for record, seat in zip(records, state.seats):
            for key in COMMON:
                value = record[key]
                if key in ("alive", "stone_used"):
                    if type(value) is not bool:
                        raise ValueError(f"{key} 必须为布尔值")
                elif key == "rank":
                    if value is not None:
                        integer(value, 1, 8, key)
                        ranks.append(value)
                else:
                    low, high = {"hp": (-1000, 100), "level": (1, 7), "streak": (-31, 31)}.get(key, (0, 1000000))
                    integer(value, low, high, key)
                setattr(seat, key, value)
            if seat.alive != (seat.hp > 0):
                raise ValueError("生命值与淘汰状态矛盾")
            if not seat.alive and seat.rank is None:
                raise ValueError("被淘汰的席位缺少名次")
            xp_limit = demo.economy.xp_to_next(seat.level)
            if xp_limit and seat.xp >= xp_limit:
                raise ValueError("等级与经验不一致")
            seat.bench = [piece(o) for o in sequence(record["bench"], demo.BENCH_CAP, "bench")]
            if seat.seat == 0:
                seat.grid = {}
                for row, col, owned in sequence(record["grid"], seat.pop(), "grid"):
                    pos = (integer(row, 0, 1, "row"), integer(col, 0, 5, "col"))
                    if pos in seat.grid:
                        raise ValueError("重复的棋盘格位")
                    seat.grid[pos] = piece(owned)
                if [owned_record(o) for o in seat.board] != record["board"]:
                    raise ValueError("棋盘格位与棋子顺序不一致")
                seat.refresh_j = integer(record["refresh_j"], 0, 1000000, "refresh_j")
                if type(record["shop_locked"]) is not bool:
                    raise ValueError("无效锁店状态")
                seat.shop_locked = record["shop_locked"]
            else:
                seat.board = [piece(o) for o in sequence(record["board"], seat.pop(), "board")]
                seat.ability = integer(record["ability"], 0, 3, "ability")
                if record["personality"] not in PERSONALITIES:
                    raise ValueError("无效机器人策略")
                seat.pers_key = record["personality"]
                seat.pers = PERSONALITIES[seat.pers_key]
                seat.name = f"{seat.seat}·{seat.pers['label'][:3]}L{seat.ability}"
                target_types = sequence(record["target_types"], 2, "target_types")
                if any(t not in demo.TYPE_ZH for t in target_types):
                    raise ValueError("未知目标属性")
                seat.target_types = tuple(target_types)
                stats = record["stats"]
                for key, upper in (("gold_curve", 1000000), ("pop_curve", 9)):
                    for value in sequence(stats[key], demo.MAX_ROUNDS, key):
                        integer(value, 0, upper, key)
                for name, count in sequence(stats["synergy_curve"], demo.MAX_ROUNDS, "synergy_curve"):
                    if name not in demo.TYPE_ZH and name != "-":
                        raise ValueError("统计包含未知属性")
                    integer(count, 0, 9, "synergy_count")
                for key in ("refreshes", "item_crafts", "item_equips", "stone_triggers"):
                    integer(stats[key], 0, 1000000, key)
                if stats["synergy_formed_round"] is not None:
                    integer(stats["synergy_formed_round"], 1, state.round_no, "synergy_formed_round")
                if stats["synergy_formed_type"] is not None and stats["synergy_formed_type"] not in demo.TYPE_ZH:
                    raise ValueError("统计包含未知成型属性")
                craft = stats["craft_stats"]
                if set(craft) != {"calls", "made", "no_pair", "gated", "shadow"}:
                    raise ValueError("合成统计字段不完整")
                integer(craft["calls"], 0, 1000000, "craft_calls")
                for key in ("made", "no_pair", "gated", "shadow"):
                    if not isinstance(craft[key], dict) or set(craft[key]) - set(demo.items_mod.FINISHED):
                        raise ValueError("合成统计含未知装备")
                    for value in craft[key].values():
                        integer(value, 0, 1000000, "craft_count")
                for key in BOT_STATS:
                    setattr(seat, key, copy.deepcopy(stats[key]))
            slots = sequence(record["shop"], demo.SHOP_SLOTS_UI, "shop")
            if len(slots) != demo.SHOP_SLOTS_UI:
                raise ValueError("商店格数不一致")
            for sid in slots:
                if sid is not None:
                    if type(sid) is not int or sid not in state.templates:
                        raise ValueError("商店未知棋子")
                    held[sid] += 1
            seat.shop.slots = list(slots)
            if not seat.alive and (seat.board or seat.bench or any(s is not None for s in slots)):
                raise ValueError("已淘汰席位仍占用卡池")
            components = record["components"]
            if set(components) != set(demo.items_mod.COMPONENT_ORDER):
                raise ValueError("组件字段不一致")
            seat.inventory.components = {k: integer(v, 0, 1000, k) for k, v in components.items()}
            finished = sequence(record["finished"], 1000, "finished")
            if any(key not in demo.items_mod.FINISHED for key in finished):
                raise ValueError("仓库含未知装备")
            seat.inventory.finished = list(finished)
        if len(ranks) != len(set(ranks)) or (state.phase == "over" and len(ranks) != 8):
            raise ValueError("名次重复或终局名次不完整")
        if set(data["pool"]) != {str(s) for s in state.templates}:
            raise ValueError("卡池种类与当前版本不一致")
        for sid, template in state.templates.items():
            count = integer(data["pool"][str(sid)], 0, demo.shop_mod.POOL_COPIES[template.tier], "pool")
            if count + held[sid] != demo.shop_mod.POOL_COPIES[template.tier]:
                raise ValueError("卡池守恒校验失败")
            state.pool.remaining[sid] = count

        def seat_ref(value):
            return None if value is None else state.seats[integer(value, 0, 7, "seat reference")]

        for record, seat in zip(records, state.seats):
            seat._last_opp = seat_ref(record["last_opponent"])
            if seat._last_opp is seat:
                raise ValueError("上轮对手不能是自己")
        pair_data = data["pairs"]
        state.pairs = ([(seat_ref(a), seat_ref(b)) for a, b in sequence(pair_data, 4, "pairs")]
                       if pair_data is not None else None)
        participants = [s.seat for pair in state.pairs or [] for s in pair]
        if len(set(participants)) != len(participants):
            raise ValueError("重复配对")
        state.ghost_seat, state.ghost_src = seat_ref(data["ghost_seat"]), seat_ref(data["ghost_source"])
        if bool(state.ghost_seat) != bool(state.ghost_src) or state.ghost_seat is not None and (
                state.ghost_seat is state.ghost_src or state.ghost_seat.seat in participants):
            raise ValueError("幽灵配对不一致")
        if state.phase == "prep" and state.round_no % 5:
            paired = set(participants + ([state.ghost_seat.seat] if state.ghost_seat else []))
            if paired != {seat.seat for seat in state._alive()}:
                raise ValueError("准备阶段配对缺少存活席位")
        state.opponent_comp = ([piece(o, owned=False) for o in sequence(data["opponent_comp"], 12, "opponent_comp")]
                               if data["opponent_comp"] is not None else None)
        if state.round_no % 5 == 0:
            state.opp_view = state._pve_view(state.round_no)
        else:
            src = state.ghost_src if state.ghost_seat is state.player else next(
                (b if a is state.player else a for a, b in state.pairs or [] if state.player in (a, b)), None)
            if src is not None and state.opponent_comp is not None:
                comp = state.opponent_comp
                views = [demo._piece_view(o[0], o[1]) if isinstance(o, tuple) else demo._piece_view(o) for o in comp]
                state.opp_view = {"name": (f"幽灵（{src.name} 镜像）" if state.ghost_seat is state.player else src.name),
                                  "hp": src.hp, "level": src.level, "rows": state._enemy_rows(views),
                                  "bench": [demo._piece_view(o.piece, o.item) for o in src.bench]}
        log = sequence(data["log"], 240, "log")
        if any(not isinstance(line, str) or len(line) > 1000 for line in log):
            raise ValueError("战报文本无效")
        state.log = list(log)
        for key in ("player_battles", "player_frames_total"):
            setattr(state, key, integer(data[key], 0, 1000000, key))
        state.eliminated_round = (integer(data["eliminated_round"], 1, state.round_no, "eliminated_round")
                                  if data["eliminated_round"] is not None else None)
        state.final_team = ([demo._piece_view(p[0], p[1]) if isinstance(p, tuple) else demo._piece_view(p)
                             for p in [piece(o, owned=False) for o in sequence(data["final_team"], 9, "final_team")]]
                            if data["final_team"] is not None else None)
        summary = data["last_battle"]
        if summary is not None:
            winner = summary["winner"]
            if winner is not None:
                integer(winner, 0, 1, "winner")
            state.last_battle = {"n": 0, "winner": winner, "round": state.round_no, "restored": True,
                                 "headline": "已恢复战后结算，结果不会重复发放",
                                 "opp_name": (state.opp_view or {}).get("name", "对手"), "events": []}
        state.save_warning = ("规则已更新，后续回合使用当前规则；历史回放不可重演"
                              if data["rules"] != rules_fingerprint() else None)
        return state
