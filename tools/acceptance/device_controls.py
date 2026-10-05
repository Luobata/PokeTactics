"""240×320 three-key host navigation; game mutations use demo transactions only."""
import secrets
import threading
import time
import re
from dataclasses import dataclass, field

import demo
import expedition
from esp32_runtime.input import GestureInput

DEVICES = {}
MAX_DEVICES = 8
_LOCK = threading.RLock()


def row(label, action, *, detail="", subtitle="", disabled=False, portrait=None, icon="", **data):
    return {"label": label, "action": action, "detail": detail, "subtitle": subtitle,
            "disabled": disabled, "portrait": portrait, "icon": icon, "data": data}


def owned_rows(state):
    for r, cells in enumerate(state.get("board", [])):
        for c, piece in enumerate(cells):
            if piece:
                yield f"g{r},{c}", piece
    for i, piece in enumerate(state.get("bench", [])):
        if piece:
            yield f"b{i}", piece


def piece_detail(piece):
    learned = piece.get("technique") or {}
    ability = piece.get("ability") or {}
    evolution = piece.get("evolution") or {}
    return "\n".join(filter(None, [piece.get("name"), piece.get("role"),
        " / ".join(piece.get("types", [])), f"射程 {piece.get('range', 1)} · {piece.get('tier', 1)} 金",
        piece.get("skill_name"), piece.get("skill_description"),
        f"装备：{piece.get('item_name') or '无'}", piece.get("item_effect"), f"已学：{learned.get('name', '无')}",
        learned.get("description"),
        f"特性：{ability['name']}" if ability else None, ability.get("description"),
        f"进化：{evolution['detail']}" if evolution.get("detail") else None]))


@dataclass
class Device:
    device_id: str
    input: GestureInput
    sid: str = ""
    state: dict = field(default_factory=dict)
    sequence: object = None
    page: str = "home"
    selected: int = 0
    context: dict = field(default_factory=dict)
    stack: list = field(default_factory=list)
    message: str = "A / B 选择，C 确认"
    busy: bool = False
    touched: float = 0.0
    play_started: float = 0.0
    play_speed: int = 1
    sleep_started: object = None
    profile: dict = field(default_factory=dict)
    loadout: dict = field(default_factory=lambda: {"partner": None, "technique": "none", "item": "none"})

    def _base(self):
        if not self.state:
            return "home"
        if self.state.get("phase") == "over":
            return "over"
        if self.state.get("phase") == "battle":
            return "result"
        return "prep" if self.state.get("you", {}).get("alive", True) else "spectate"

    def _go(self, page, now, *, replace=False, **context):
        if not replace:
            self.stack.append((self.page, self.selected, self.context))
        else:
            self.stack.clear()
        self.page, self.selected, self.context = page, 0, context
        self.input.block(now)

    def _refresh(self, now):
        """Pure state read; never auto-resume or save during navigation."""
        if not self.sid:
            return False
        session = demo.SESSIONS.get(self.sid)
        if session is None:
            if self.state:
                self.state, self.sequence = {}, None
                self._go("home", now, replace=True)
                self.message = "对局已移出内存，请选择继续存档"
                return True
            return False
        current = demo.state_json(session)
        changed = bool(self.state) and current.get("save", {}).get("sequence") != self.sequence
        self.state = current
        self.sequence = current.get("save", {}).get("sequence")
        if changed:
            self._go(self._base(), now, replace=True)
            self.message = "存档已在另一页面更新，请重新选择目标"
            self.input.feed("cancel", now=now)
        return changed

    def _find_uid(self, uid):
        return next(((loc, p) for loc, p in owned_rows(self.state) if p.get("uid") == uid), None)

    def _pending_rewards(self):
        return [r for r in self.state.get("rewards", []) if r.get("status") == "pending"]

    def _is_tactical(self):
        from tactics import enabled
        return enabled(self.state.get("ruleset", "base_v1"))

    def _is_evolution_ui(self):
        return self.state.get("ruleset") == "tactics_v5"

    def _shop_evolution_preview(self, slot):
        try:
            piece = self.state.get("shop", [])[slot]
        except (IndexError, TypeError):
            return None
        return (piece or {}).get("evolution_preview") if isinstance(piece, dict) else None

    def _validate_learning(self, species, technique):
        from techniques import validate_learning
        return validate_learning(species, technique, ruleset=self.state.get("ruleset", "base_v1"))

    @staticmethod
    def _adjacent(first, second):
        if not first.startswith("g") or not second.startswith("g"):
            return False
        a, b = [tuple(map(int, loc[1:].split(","))) for loc in (first, second)]
        return sum(abs(x-y) for x, y in zip(a, b)) == 1

    def _catalog(self):
        result = expedition.api_profile()
        if result.get("ok"):
            self.profile = result
        else:
            self.message = result.get("error", "无法读取档案")
        return result.get("ok", False)

    def _commit(self, command, now, **params):
        # Called under demo._LOCK, including the read/UID resolution/commit boundary.
        if command not in ("new", "resume"):
            session = demo.SESSIONS.get(self.sid)
            fresh = demo.state_json(session) if session else None
            if fresh is None or fresh.get("save", {}).get("sequence") != self.sequence:
                self._refresh(now)
                self.message = "存档已更新，本次操作已取消，请重新选择"
                return
            self.state = fresh
            params["expected_sequence"] = self.sequence
            uid = params.pop("uid", None)
            if uid is not None:
                # Tactical configuration is identity based, including explicit
                # clearing. Never turn its stable UID into an equipment loc.
                if command in ("set_guard", "set_weather") and uid == "":
                    params["uid"] = ""
                else:
                    found = self._find_uid(uid)
                    if found is None:
                        self._go(self._base(), now, replace=True)
                        self.message = "目标棋子已变化，请重新选择"
                        return
                    if command in ("learn", "set_guard", "set_weather", "evolve", "set_evolution_lock"):
                        params["uid"] = uid
                    else:
                        params["from" if command == "move" else "loc"] = found[0]
        self.busy = True
        try:
            result = demo.api_action({"cmd": command, "sid": self.sid, **params})
        finally:
            self.busy = False
            # Reject inputs that arrived while the transaction/render was running.
            self.input.block(max(now, self.input.clock()))
        if not result.get("ok"):
            self.message = result.get("error", "操作未完成")
            if result.get("recovery_sid"):
                self.sid = result["recovery_sid"]
            if command in ("claim_reward", "set_guard", "set_weather", "learn", "evolve", "set_evolution_lock"):
                # A rejected command must not leave an apparently valid target
                # in a confirmation dialog. The next attempt starts from truth.
                self._refresh(now)
                self._go(self._base(), now, replace=True)
            return
        self.state = result.get("state", self.state)
        self.sid = result.get("sid", self.state.get("sid", self.sid))
        self.sequence = self.state.get("save", {}).get("sequence")
        self.message = result.get("msg", "已保存")
        self._go(self._base(), now, replace=True)
        if command == "end_prep" and (self.state.get("last_battle") or {}).get("n", 0):
            self.page, self.play_started, self.play_speed = "battle", max(now, self.input.clock()), 1

    def _confirm(self, label, command, now, **params):
        self._go("confirm", now, label=label, command=command, params=params,
                 expected_sequence=self.sequence)

    def _uid_row(self, loc, piece, action="piece", **data):
        uid = piece.get("uid")
        position = f"备战席 · 第 {int(loc[1:])+1} 格" if loc.startswith("b") else f"战场 · 第 {int(loc[1])+1} 行 {int(loc[3:])+1} 列"
        return row(piece["name"], action, subtitle=position, portrait=piece,
                   detail=piece_detail(piece), disabled=uid is None, uid=uid, **data)

    def rows(self):
        state, ctx, page = self.state, self.context, self.page
        you = state.get("you", {})
        if page == "home":
            return [row("启程 · 远征", "expedition", detail="选择主搭档、招式机器与开局装备。"),
                    row("战术远征 · 护卫与天气", "tactics", detail="九尾日照、拉普拉斯降雨；野怪轮教学三选一。两组件可合封疗针；第20轮起增加败方扣血，胜方不掉血。"),
                    row("继续存档", "resume", subtitle="继续已保存的这一局" if self.sid else "尚无存档编号", disabled=not self.sid),
                    row("经典对局", "classic", detail="从商店组建队伍，八位训练家同场竞技。"),
                    row("挑战与图鉴", "collection")]
        if page == "expedition":
            chosen = self.loadout
            def label(kind):
                return next((r["name"] for r in self.profile.get(kind + "s", [])
                             if r["id"] == chosen[kind]), "未选择" if kind == "partner" else "不携带")
            return [row("主搭档 · " + label("partner"), "loadout", kind="partner"),
                    row("招式机器 · " + label("technique"), "loadout", kind="technique"),
                    row("开局装备 · " + label("item"), "loadout", kind="item"),
                    row("出发", "depart", disabled=chosen["partner"] is None)]
        if page == "loadout":
            kind = ctx["kind"]
            choices = [] if kind == "partner" else [row("不携带", "choose_loadout", kind=kind, value="none")]
            for entry in self.profile.get(kind + "s", []):
                compatible = kind != "technique" or self.loadout["partner"] in entry.get("partners", [])
                locked = not entry.get("unlocked")
                choices.append(row(entry["name"], "choose_loadout", detail=entry.get("description", ""),
                                   portrait={"sid": entry["id"], "name": entry["name"]} if kind == "partner" else None,
                                   icon=kind,
                                   subtitle="尚未解锁" if locked else "搭档不兼容" if not compatible else "已解锁",
                                   disabled=locked or not compatible, kind=kind, value=entry["id"]))
            return choices
        if page == "collection":
            return [row("挑战进度", "open", page="challenges"), row("宝可梦图鉴", "open", page="dex")]
        if page == "challenges":
            return [row(c.get("name", c.get("id", "挑战")), "show_detail",
                        subtitle=f"{c.get('progress', c.get('current', 0))} / {c.get('target', '?')}",
                        detail="\n".join([c.get("description", ""), "奖励：" + "、".join(c.get("rewards", []))]))
                    for c in self.profile.get("challenges", [])]
        if page == "dex":
            return [row(p["name"] if p.get("seen") else "未发现", "show_detail",
                        portrait={"sid": p["id"], "name": p["name"]} if p.get("seen") else None, icon="dex",
                        subtitle=f"No.{p['id']:03d}", detail=(p["name"] + "\n" +
                        " / ".join(label for flag, label in (("seen", "已见"), ("fielded", "已上场"), ("won", "已获胜")) if p.get(flag)))
                        if p.get("seen") else "在商店或战斗中遇见后收录。") for p in self.profile.get("dex", [])]
        if page == "prep":
            return [row("商店", "open", page="shop"), row("棋盘与备战", "open", page="board_rows"),
                    row("仓库与教学" + (f" · {len(self._pending_rewards())} 待领" if self._pending_rewards() else ""), "open", page="inventory"), row("羁绊", "open", page="synergies"),
                    row("侦察与排名", "open", page="scout"),
                    row("开战", "battle_confirm", detail="\n".join(filter(None, [
                        (state.get("entry_weather") or {}).get("note"),
                        (state.get("pacing") or {}).get("note")]))),
                    row("保存 / 返回主页", "open", page="system")]
        if page == "shop":
            entries = []
            for i, p in enumerate(state.get("shop", [])):
                preview = (p or {}).get("evolution_preview") or {}
                detail = piece_detail(p) if p else ""
                if preview.get("detail"):
                    detail = "\n".join(filter(None, [detail, preview["detail"]]))
                entries.append(row(p["name"] if p else "空货架", "buy",
                                   subtitle=(f"{p.get('price', p['tier'])} 金 · 三合一预览" if p and preview.get("merges") else
                                      (f"{p.get('price', p['tier'])} 金" if p else "已售出")),
                                   detail=detail, portrait=p, disabled=not p, i=i))
            return entries + [row(f"刷新 · {you.get('refresh_cost', 2)} 金", "command", command="refresh"),
                              row("解除锁定" if you.get("shop_locked") else "锁定商店", "command", command="lock"),
                              row(f"购买经验 · {you.get('xp_cost', 4)} 金", "command", command="levelup")]
        if page in ("board_rows", "move_rows"):
            return [row(label, "choose_row", row=r) for r, label in enumerate(("战场第一行", "战场第二行", "备战席"))]
        if page in ("board_columns", "move_columns"):
            r = ctx["row"]
            cells = list(state.get("bench", [])) + [None] * 6 if r == 2 else state.get("board", [[None]*6]*2)[r]
            entries = []
            for c in range(6):
                p, loc = cells[c], f"b{c}" if r == 2 else f"g{r},{c}"
                entries.append(row(f"{c+1} · {p['name'] if p else '空位'}", "cell", detail=piece_detail(p) if p else "",
                                   portrait=p, loc=loc, uid=p.get("uid") if p else None))
            return entries
        if page == "piece":
            found = self._find_uid(ctx.get("uid"))
            if not found:
                return [row("棋子已变化，请返回", "back")]
            piece = found[1]
            entries = [row("移动 / 交换", "move_piece", uid=ctx["uid"]),
                    row("装备道具", "equip_piece", uid=ctx["uid"]),
                    row("卸下装备", "command", command="unequip", uid=ctx["uid"], disabled=not piece.get("item")),
                    row("学习招式", "learn_piece", uid=ctx["uid"]),
                    row(f"卖出 · +{piece.get('sell', 1)} 金", "sell_confirm", uid=ctx["uid"], name=piece["name"])]
            evolution = piece.get("evolution") or {}
            if self._is_evolution_ui() and evolution:
                can_evolve = bool(evolution.get("can_evolve"))
                entries.append(row("进化预览" if can_evolve else "形态状态",
                                   "piece_evolution" if can_evolve else "show_detail", uid=ctx["uid"],
                                   subtitle=evolution.get("detail", ""), detail=piece_detail(piece), icon="dex"))
                if evolution.get("can_lock"):
                    locked = bool(evolution.get("locked"))
                    entries.append(row("解除形态锁定" if locked else "锁定当前形态",
                                       "evolution_lock_confirm", uid=ctx["uid"],
                                       subtitle="仅改变锁，不触发合成" if locked else "锁定后不会自动三合一",
                                       detail=piece_detail(piece), icon="guard"))
            entries.append(row("战术配置" if self._is_tactical() else "查看详情",
                               "piece_tactics" if self._is_tactical() else "show_detail", uid=ctx["uid"], detail=piece_detail(piece)))
            return entries
        if page == "evolution_buy":
            preview = self._shop_evolution_preview(ctx.get("slot", -1)) or {}
            if not preview.get("merges"):
                return [row("预览已变化，请返回", "back", detail=preview.get("detail", ""))]
            detail = preview.get("detail", "")
            return [row("本次三合一预览", "show_detail", subtitle="长按 C 查看完整代价", detail=detail, icon="dex"),
                    row("购买并进化", "evolution_buy_confirm", evolution="auto", icon="battle",
                        disabled=not preview.get("auto_allowed", True),
                        subtitle="按当前预览自动完成连锁合成" if preview.get("auto_allowed", True) else "当前不能自动合成",
                        detail=detail),
                    row("购买并暂缓", "evolution_buy_confirm", evolution="defer", icon="guard",
                        disabled=not preview.get("defer_allowed", False),
                        subtitle="保留三只并锁定同名实例" if preview.get("defer_allowed", False) else "备战席不足，无法保留三只",
                        detail=detail),
                    row("取消购买", "back", icon="back")]
        if page == "evolution_piece":
            found = self._find_uid(ctx.get("uid"))
            if not found:
                return [row("棋子已变化，请返回", "back")]
            evolution = found[1].get("evolution") or {}
            preview = evolution.get("preview") or {}
            detail = "\n".join(filter(None, [preview.get("detail", ""), evolution.get("detail", "")]))
            if not evolution.get("can_evolve") or not preview.get("merges"):
                return [row("当前不能进化，请返回", "show_detail", detail=detail)]
            return [row("本次进化预览", "show_detail", subtitle="长按 C 查看完整代价", detail=detail, icon="dex"),
                    row("确认进化", "evolution_piece_confirm", uid=ctx["uid"], icon="battle",
                        detail=detail, subtitle="只执行这一步，不递归合成"),
                    row("暂缓 / 返回", "back", icon="back", detail=detail)]
        if page == "piece_tactics":
            found = self._find_uid(ctx.get("uid"))
            if not found:
                return [row("棋子已变化，请返回", "back")]
            loc, piece = found
            learned = (piece.get("technique") or {}).get("id")
            deployed = loc.startswith("g")
            tactical = state.get("tactical") or {}
            guard, weather = tactical.get("guard") or {}, tactical.get("weather") or {}
            return [
                row("选择护卫对象", "guard_choose", uid=piece["uid"], icon="guard",
                    disabled=not deployed or learned != "guard",
                    subtitle="仅相邻上场队友 · 每场一次" if deployed and learned == "guard" else "需上场并学习护卫",
                    detail="选择相邻队友，拦截一次真实突进后的主命中；启用后原护卫停用，不会自动接力。"),
                row("设为本队天气手", "weather_confirm", uid=piece["uid"], icon="weather",
                    disabled=not deployed or learned not in ("sunny_day", "rain_dance"),
                    subtitle="首次大招后改变全场天气" if deployed and learned in ("sunny_day", "rain_dance") else "需上场并学习晴天或求雨",
                    detail="天气全场共享，双方都受影响。后触发覆盖先触发，同刻不同天气抵消，同天气不叠加时长。窗口结束恢复基础天气。每队一次；原天气手停用，不会自动接力。"),
                row("关闭本队护卫", "guard_clear", disabled=not guard, icon="guard", subtitle="不会返还教学，也不改变站位"),
                row("关闭本队天气手", "weather_clear", disabled=not weather, icon="weather", subtitle="本队本场仅使用基础或对方天气"),
                row("查看伙伴详情", "show_detail", detail=piece_detail(piece), icon="dex")]
        if page == "guard_targets":
            source = self._find_uid(ctx.get("uid"))
            if not source:
                return [row("护卫已变化，请返回", "back")]
            entries = []
            for loc, piece in owned_rows(state):
                if piece.get("uid") == ctx["uid"] or not loc.startswith("g"):
                    continue
                entry = self._uid_row(loc, piece, "guard_target", source_uid=ctx["uid"])
                entry["disabled"] = not self._adjacent(source[0], loc)
                entry["subtitle"] = "相邻队友 · C 预览确认" if not entry["disabled"] else "必须与护卫四向相邻"
                entries.append(entry)
            return entries or [row("先部署一名相邻队友", "back", detail="护卫只能保护四向相邻的上场队友。")]
        if page == "inventory":
            pending = self._pending_rewards()
            rewards = [row(f"待领补给 · {len(pending)}", "open", page="rewards", icon="flag",
                           subtitle="选择后入仓 · 开战前处理", detail="候选已固定；返回不会放弃，也不会重新抽取。")] if pending else []
            return rewards + [row("成品装备 · 使用", "open", page="finished", icon="item"), row("组件 · 合成", "open", page="craft", icon="craft"),
                    row("招式机器 · 教学", "open", page="techniques"), row("已收取物资", "open", page="drops")]
        if page == "rewards":
            return [row(f"第 {r['round']} 轮 · 教学补给", "reward_open", reward_id=r["id"], icon="technique",
                        subtitle=f"{len(r.get('options', []))} 选 1 · 领取后选择学习对象",
                        detail="本轮候选已保存。返回仍待领；开战前选择领取，或明确放弃本次。")
                    for r in self._pending_rewards()]
        if page == "reward_options":
            reward = next((r for r in self._pending_rewards() if r["id"] == ctx.get("reward_id")), None)
            if not reward:
                return [row("补给已处理，请返回", "back")]
            choices = []
            for option in reward.get("options", []):
                compatible = []
                for _, piece in owned_rows(state):
                    try:
                        self._validate_learning(piece["sid"], option["id"])
                        compatible.append(piece["name"])
                    except ValueError:
                        pass
                choices.append(row(option["name"], "reward_claim", reward_id=reward["id"], choice=option["id"],
                                   icon="guard" if option["id"] == "guard" else "weather" if option["id"] in ("sunny_day", "rain_dance") else "technique",
                                   subtitle="可学：" + "、".join(compatible) if compatible else "暂时无兼容伙伴 · 可留待转型",
                                   detail=option.get("description", "") + "\n" + option.get("compatibility", "")))
            return choices + [row("放弃本次补给", "reward_claim", reward_id=reward["id"], choice="skip",
                                  subtitle="确认后本轮不可再领取", icon="back")]
        if page in ("finished", "equip_items"):
            return [row(i["name"], "equip_choose", detail=i.get("effect", ""), icon="item", item=i["key"], uid=ctx.get("uid"))
                    for i in state.get("items", {}).get("finished", [])]
        if page == "craft":
            return [row(i["name"], "craft_confirm", subtitle=i.get("recipe", ""), detail=i.get("effect", ""), icon="craft", item=i["key"])
                    for i in state.get("items", {}).get("craftable", [])] + [
                    row(f"{i['name']} ×{i['n']}", "show_detail", detail="组件已在仓库，集齐配方即可合成。", icon="craft")
                    for i in state.get("items", {}).get("components", [])]
        if page == "drops":
            return [row("物资已自动入仓", "show_detail", detail="野怪掉落已在战斗结算时保存；此页只查看，不会重复领取。"),
                    *[row(i["name"], "show_detail", detail=i.get("effect", "")) for i in state.get("items", {}).get("finished", [])],
                    *[row(f"{i['name']} ×{i['n']}", "show_detail", detail="仓库组件") for i in state.get("items", {}).get("components", [])]]
        if page in ("techniques", "learn_items"):
            return [row(f"{i['name']} ×{i.get('count', 1)}", "technique_choose", detail=i.get("description", ""),
                        icon="technique", technique=i["id"], name=i["name"], uid=ctx.get("uid"))
                    for i in state.get("techniques", {}).get("inventory", []) if i.get("count", 1) > 0]
        if page == "targets":
            entries = []
            for loc, piece in owned_rows(state):
                entry = self._uid_row(loc, piece, "target", **ctx)
                if ctx.get("kind") == "learn":
                    try:
                        self._validate_learning(piece["sid"], ctx["technique"])
                    except ValueError as exc:
                        entry.update(disabled=True, subtitle=str(exc), detail=piece_detail(piece) + "\n" + str(exc))
                entries.append(entry)
            return entries
        if page == "synergies":
            return [row(f"{s['zh']} · {s['n']} 位", "show_detail", subtitle=s.get("effect") or f"再需 {s.get('need', 0)} 位",
                        detail=s.get("effect") or f"按实际上场数量计数，同种副本也计入，还需 {s.get('need', 0)} 位。")
                    for s in state.get("synergies", [])]
        if page == "scout":
            opp = state.get("opponent") or {}
            pieces = [p for cells in opp.get("rows", []) for p in cells if p] + opp.get("bench", [])
            return [row("训练家排名", "open", page="standings"),
                    row(opp.get("name", "对手尚未揭晓"), "show_detail", detail="准备期显示已知对手快照，配对后更新。"),
                    *[row(p.get("name", "对手棋子"), "show_detail", detail=piece_detail(p), portrait=p) for p in pieces if isinstance(p, dict)]]
        if page in ("standings", "over"):
            standings = (state.get("over") or {}).get("ranking", state.get("standings", []))
            return [row(f"{p.get('rank') or '—'} · {'你' if p.get('is_you') else p['name']}", "show_detail",
                        subtitle=f"HP {p.get('hp', 0)}", detail=f"生命 {p.get('hp', 0)}\n名次 {p.get('rank') or '待定'}")
                    for p in standings] + ([row("返回主页", "home")] if page == "over" else [])
        if page == "battle":
            return [row("查看结算", "result"), row(f"播放速度 · {self.play_speed}×", "speed"), row("战报", "report")]
        if page in ("result", "spectate"):
            entries = [row("下一轮" if you.get("alive", True) else "观战下一轮", "command", command="next")]
            if state.get("phase") == "over":
                entries = [row("查看最终排名", "open", page="over")]
            if not you.get("alive", True) and state.get("phase") != "over":
                entries.append(row("观战至终局", "finish_confirm"))
            return entries + [row("查看战报", "report"), row("已收取物资", "open", page="drops"),
                              row("训练家排名", "open", page="standings"), row("返回主页", "home")]
        if page == "system":
            return [row("保存进度", "command", command="save"), row("继续当前对局", "return_base"), row("返回主页", "home")]
        if page == "confirm":
            return [row("取消", "back"), row("确认执行", "confirm")]
        return []

    def _learn_confirm(self, uid, technique, name, now):
        found = self._find_uid(uid)
        if not found:
            self.message = "目标棋子已变化，请重新选择"
            return
        try:
            self._validate_learning(found[1]["sid"], technique)
        except ValueError as exc:
            self.message = str(exc)
            return
        old = found[1].get("technique")
        label = f"{found[1]['name']} 学习 {name}"
        if old:
            label += f"（覆盖 {old['name']}，旧机器返还仓库）"
        self._confirm(label, "learn", now, uid=uid, technique=technique, replace="1" if old else "0")

    def back(self, now):
        self.message = ""
        if self.stack:
            self.page, self.selected, self.context = self.stack.pop()
            self.input.block(now)
        elif self.page != "home":
            self._go("home", now, replace=True)

    def activate(self, item, now):
        self.message = ""
        if item.get("disabled"):
            self.message = item.get("subtitle") or "当前不可操作"
            return
        action, data = item["action"], dict(item["data"])
        if action == "open":
            self._go(data["page"], now)
        elif action == "home":
            self._go("home", now, replace=True)
        elif action == "return_base":
            self._go(self._base(), now, replace=True)
        elif action == "back":
            self.back(now)
        elif action == "resume":
            self._commit("resume", now)
        elif action == "classic":
            self._confirm("开始新的经典对局", "new", now, mode="classic")
        elif action in ("expedition", "tactics", "collection"):
            if self._catalog():
                self._go("expedition" if action == "tactics" else action, now,
                         **({"mode": action} if action != "collection" else {}))
        elif action == "loadout":
            self._go("loadout", now, **data)
        elif action == "choose_loadout":
            self.loadout[data["kind"]] = data["value"]
            if data["kind"] == "partner":
                self.loadout["technique"] = "none"
            self.back(now)
        elif action == "depart":
            mode = self.context.get("mode", "expedition")
            self._confirm("战术远征出发" if mode == "tactics" else "远征出发", "new", now, mode=mode, **self.loadout)
        elif action == "buy":
            preview = self._shop_evolution_preview(data.get("i", -1)) or {}
            if self._is_evolution_ui() and preview.get("merges"):
                self._go("evolution_buy", now, slot=data["i"])
                return
            self._commit("buy", now, **data)
        elif action == "command":
            command = data.pop("command")
            self._commit(command, now, **data)
        elif action == "choose_row":
            moving = self.page == "move_rows"
            self._go("move_columns" if moving else "board_columns", now,
                     row=data["row"], **({"uid": self.context["uid"]} if moving else {}))
        elif action == "cell":
            if self.page == "move_columns":
                self._commit("move", now, uid=self.context["uid"], to=data["loc"])
            elif data.get("uid") is not None:
                self._go("piece", now, uid=data["uid"])
            else:
                self.message = "这是空位"
        elif action == "piece":
            self._go("piece", now, **data)
        elif action == "piece_tactics":
            self._go("piece_tactics", now, uid=data["uid"])
        elif action == "piece_evolution":
            self._go("evolution_piece", now, uid=data["uid"])
        elif action == "evolution_buy_confirm":
            preview = self._shop_evolution_preview(self.context.get("slot", -1)) or {}
            if not preview.get("merges"):
                self.message = "商店或预览已变化，请重新选择"
                self._go(self._base(), now, replace=True)
                return
            piece = self.state.get("shop", [])[self.context["slot"]]
            if data["evolution"] == "defer":
                if not preview.get("defer_allowed", False):
                    self.message = "备战席不足，无法暂缓"
                    return
                self._confirm(f"购买 {piece['name']} 并暂缓进化；同名实例全部锁定", "buy", now,
                              i=self.context["slot"], evolution="defer")
            else:
                if not preview.get("auto_allowed", True):
                    self.message = "当前不能自动进化"
                    return
                self._confirm(f"购买 {piece['name']} 并按预览进化", "buy", now,
                              i=self.context["slot"], evolution="auto")
        elif action == "evolution_piece_confirm":
            found = self._find_uid(data.get("uid"))
            if not found or not ((found[1].get("evolution") or {}).get("can_evolve")):
                self.message = "目标棋子已变化，请重新选择"
                return
            self._confirm(f"{found[1]['name']} 进化；只执行这一步", "evolve", now, uid=data["uid"])
        elif action == "evolution_lock_confirm":
            found = self._find_uid(data.get("uid"))
            if not found or not ((found[1].get("evolution") or {}).get("can_lock")):
                self.message = "目标棋子不支持形态锁定"
                return
            evolution = found[1]["evolution"]
            locked = bool(evolution.get("locked"))
            label = "解除形态锁定；不会触发进化" if locked else "锁定当前形态；不会自动三合一"
            self._confirm(label, "set_evolution_lock", now, uid=data["uid"],
                          locked="0" if locked else "1")
        elif action == "guard_choose":
            self._go("guard_targets", now, uid=data["uid"])
        elif action == "guard_target":
            source = self._find_uid(data["source_uid"])
            if source:
                self._confirm(f"{source[1]['name']} 护卫 {item['label']}；每场一次，原护卫停用", "set_guard", now,
                              uid=data["source_uid"], target_uid=data["uid"])
        elif action == "weather_confirm":
            source = self._find_uid(data["uid"])
            if source:
                self._confirm(f"{source[1]['name']} 首次大招后发动 {source[1]['technique']['name']}；全场共享，原天气手停用", "set_weather", now, uid=data["uid"])
        elif action == "guard_clear":
            self._confirm("关闭本队护卫；保留已学教学", "set_guard", now, uid="", target_uid="")
        elif action == "weather_clear":
            self._confirm("关闭本队天气手；保留已学教学", "set_weather", now, uid="")
        elif action == "reward_open":
            self._go("reward_options", now, reward_id=data["reward_id"])
        elif action == "reward_claim":
            self._confirm("放弃本次补给；本轮不可再领取" if data["choice"] == "skip" else "领取 " + item["label"] + " 招式机器；进入仓库后选择学习对象",
                          "claim_reward", now, **data)
        elif action in ("move_piece", "equip_piece", "learn_piece"):
            self._go({"move_piece": "move_rows", "equip_piece": "equip_items", "learn_piece": "learn_items"}[action], now, uid=data["uid"])
        elif action == "sell_confirm":
            self._confirm("卖出 " + data["name"], "sell", now, uid=data["uid"])
        elif action == "equip_choose":
            if data.get("uid") is not None:
                self._confirm("装备 " + item["label"], "equip", now, uid=data["uid"], item=data["item"])
            else:
                self._go("targets", now, kind="equip", item=data["item"], name=item["label"])
        elif action == "craft_confirm":
            self._confirm("合成 " + item["label"], "craft", now, item=data["item"])
        elif action == "technique_choose":
            if data.get("uid") is not None:
                self._learn_confirm(data["uid"], data["technique"], data["name"], now)
            else:
                self._go("targets", now, kind="learn", technique=data["technique"], name=data["name"])
        elif action == "target":
            if data["kind"] == "learn":
                self._learn_confirm(data["uid"], data["technique"], data["name"], now)
            else:
                self._confirm("为 " + item["label"] + " 装备 " + data["name"], "equip", now, uid=data["uid"], item=data["item"])
        elif action == "battle_confirm":
            if self._pending_rewards():
                self._go("rewards", now)
                self.message = "还有待领补给，请领取或明确放弃后开战"
                return
            empty = not any(True for _ in owned_rows({"board": self.state.get("board", [])}))
            self._confirm("空场出战将直接判负" if empty else "准备完成，开始战斗", "end_prep", now)
        elif action == "finish_confirm":
            self._confirm("观战至终局", "finish", now)
        elif action == "confirm":
            if self.context.get("expected_sequence") != self.sequence:
                self.message = "存档已更新，请重新确认"
                self._go(self._base(), now, replace=True)
            else:
                self._commit(self.context["command"], now, **self.context["params"])
        elif action == "show_detail":
            if item.get("detail"):
                self._go("detail", now, title=item["label"], text=item["detail"])
        elif action == "result":
            self._go("result", now, replace=True)
        elif action == "speed":
            elapsed = max(0., now - self.play_started) * self.play_speed
            self.play_speed = {1: 2, 2: 4, 4: 1}[self.play_speed]
            self.play_started = now - elapsed / self.play_speed
        elif action == "report":
            lines = self.state.get("log", [])[-12:]
            headline = (self.state.get("last_battle") or {}).get("headline", "本轮暂无战报")
            self._go("detail", now, title="战斗记录", text="\n".join([headline, *lines]))

    def handle(self, event, now):
        kind, key = event
        if kind == "sleep":
            self.sleep_started = now
            return
        if kind == "wake":
            if self.sleep_started is not None:
                self.play_started += max(0., now - self.sleep_started)
            self.sleep_started = None
            self.message = "屏幕已唤醒，请松开后再按一次"
            return
        if kind == "back":
            self.back(now)
            return
        entries = self.rows()
        self.selected = min(self.selected, max(0, len(entries) - 1)) if self.page != "detail" else self.selected
        if kind == "detail":
            if entries and entries[self.selected].get("detail"):
                self.message = ""
                self._go("detail", now, title=entries[self.selected]["label"], text=entries[self.selected]["detail"])
            return
        if kind != "click":
            return
        if self.page == "detail":
            if key == "C":
                self.back(now)
            else:
                self.selected = max(0, min(self.selected + (-1 if key == "A" else 1), len(self._detail_pages()) - 1))
        elif key in ("A", "B"):
            self.message = ""
            self.selected = max(0, min(self.selected + (-1 if key == "A" else 1), len(entries) - 1))
        elif entries:
            self.activate(entries[self.selected], now)

    def _detail_pages(self):
        text = self.context.get("text", "")
        lines = [line[i:i+16] for line in text.splitlines() for i in range(0, max(1, len(line)), 16)]
        return [lines[i:i+8] for i in range(0, len(lines), 8)] or [["暂无详情"]]

    def view(self, now):
        titles = {"home": "POKÉ TACTICS", "expedition": "远征行囊", "collection": "训练家档案",
                  "prep": "准备出发", "shop": "林间商店", "board_rows": "棋盘 · 选行", "board_columns": "棋盘 · 选列",
                  "move_rows": "移动 · 选行", "move_columns": "移动 · 选列", "piece": "棋子操作",
                  "inventory": "随身仓库", "finished": "使用装备", "craft": "组件与合成", "techniques": "招式教学",
                  "learn_items": "选择机器", "targets": "选择棋子", "equip_items": "选择装备", "synergies": "队伍羁绊",
                  "scout": "对手情报", "standings": "训练家排名", "over": "旅程完结", "result": "战后结算",
                  "spectate": "观战席", "battle": "战斗回放", "system": "旅途菜单", "drops": "已收取物资",
                  "challenges": "挑战记录", "dex": "宝可梦图鉴", "loadout": "选择行囊", "confirm": "请确认"}
        titles.update(piece_tactics="棋盘 · 战术分工", guard_targets="护卫 · 选择队友", rewards="待领补给",
                      reward_options="教学补给 · 三选一", evolution_buy="三合一 · 购买预览",
                      evolution_piece="三合一 · 进化预览")
        if self.page == "expedition" and self.context.get("mode") == "tactics":
            titles["expedition"] = "战术远征行囊"
        entries = self.rows()
        if self.page != "detail":
            self.selected = min(self.selected, max(0, len(entries)-1))
        offset = max(0, self.selected-4)
        public = [{k: v for k, v in entry.items() if k not in ("action", "data")} | {"index": i}
                  for i, entry in enumerate(entries) if offset <= i < offset+5]
        footer = ["A 上一项  B 下一项  C 确认", "B 按住返回 · C 按住详情 / 关屏"]
        screen = {"page": self.page, "title": titles.get(self.page, self.context.get("title", self.page)),
                  "rows": public, "selected": self.selected, "offset": offset, "total": len(entries),
                  "footer": footer, "message": self.message, "hud": self.state.get("you"),
                  "round": self.state.get("round"), "board": self.state.get("board", []),
                  "bench": self.state.get("bench", []), "row": self.context.get("row"),
                  "ruleset": self.state.get("ruleset", "base_v1")}
        # Presentation data only. The client draws the saved formation, but every
        # action, target UID and confirmation remains owned by this controller.
        if self.page in ("prep", "shop", "board_rows", "board_columns", "move_rows", "move_columns", "piece", "piece_tactics", "guard_targets", "reward_options", "evolution_buy", "evolution_piece"):
            screen["choices"] = [{k: v for k, v in entry.items() if k not in ("action", "data")} | {"index": i}
                                 for i, entry in enumerate(entries)]
        opponent = self.state.get("opponent") or {}
        screen["scene"] = {
            "opponent": {"name": opponent.get("name", "等待配对"), "rows": opponent.get("rows", [])},
            "weather": self.state.get("weather", {}),
            "entry_weather": self.state.get("entry_weather"),
            "synergies": self.state.get("synergies", []),
            "loadout_partner": self.loadout.get("partner"),
            "loadout_mode": self.context.get("mode", "expedition"),
            "tactical": self.state.get("tactical") or {},
            "pending_rewards": len(self._pending_rewards()),
            "inventory": {
                "items": len(self.state.get("items", {}).get("finished", [])),
                "components": sum(i["n"] for i in self.state.get("items", {}).get("components", [])),
                "techniques": sum(i.get("count", 1) for i in self.state.get("techniques", {}).get("inventory", []))},
            "result": {k: v for k, v in (self.state.get("last_battle") or {}).items()
                       if k in ("headline", "winner", "survivors", "duration", "opp_name")},
        }
        focus_uid = self.context.get("uid") or self.context.get("params", {}).get("uid")
        focused = self._find_uid(focus_uid) if focus_uid else None
        if focused:
            screen["focus"] = {"loc": focused[0], "piece": focused[1]}
        if self.page == "shop" and entries:
            active = entries[self.selected]
            preview = self._shop_evolution_preview(active.get("data", {}).get("i", -1))
            if preview:
                screen["evolution_preview"] = preview
        if self.page == "evolution_buy":
            preview = self._shop_evolution_preview(self.context.get("slot", -1))
            if preview:
                screen["evolution_preview"] = preview
        if self.page == "evolution_piece" and focused:
            preview = ((focused[1].get("evolution") or {}).get("preview"))
            if preview:
                screen["evolution_preview"] = preview
        if self.page == "guard_targets" and entries:
            candidate = entries[self.selected]
            if candidate.get("portrait"):
                screen["tactical_preview"] = {"guard": {"uid": focus_uid, "target_uid": candidate["portrait"]["uid"]},
                                              "valid": not candidate.get("disabled", False), "draft": True}
        if self.page == "confirm":
            params = self.context["params"]
            if self.context["command"] == "set_guard" and params.get("uid"):
                screen["tactical_preview"] = {"guard": {"uid": params["uid"], "target_uid": params["target_uid"]}, "valid": True, "draft": True}
            elif self.context["command"] == "set_weather" and params.get("uid"):
                screen["tactical_preview"] = {"weather": {"uid": params["uid"]}, "valid": True, "draft": True}
        if entries and self.page != "detail":
            screen["active"] = {k: v for k, v in entries[self.selected].items() if k not in ("action", "data")}
        screen["can_back"] = bool(self.stack) or self.page != "home"
        if self.page == "confirm":
            screen["prompt"] = self.context["label"]
        if self.page == "detail":
            pages = self._detail_pages()
            self.selected = min(self.selected, len(pages)-1)
            screen.update(title=self.context.get("title", "详情"), detail=pages[self.selected],
                          detail_page=self.selected+1, detail_total=len(pages), footer=["A 上一页  B 下一页  C 返回", "B 按住返回 · C 1.5 秒关屏"])
        if self.page == "battle":
            meta = self.state.get("last_battle") or {}
            end = self.sleep_started if self.sleep_started is not None else now
            frame = min(max(0, meta.get("n", 0)-1), int(max(0., end-self.play_started)*self.play_speed/max(.01, meta.get("dt", .05))))
            screen["battle"] = {"frame": frame, "n": meta.get("n", 0), "speed": self.play_speed,
                                "url": f"/demo/frame/{self.sid}/r{meta.get('round', self.state.get('round'))}/{frame}.png"}
        return {"ok": True, "device_id": self.device_id, "sid": self.sid, "screen": screen,
                "sleeping": self.input.sleeping, "busy": self.busy, "sequence": self.sequence}


def api_input(params, *, now=None):
    """HTTP-safe API. now is a Python-only clock injection for deterministic tests."""
    received = time.monotonic() if now is None else now
    with _LOCK, demo._LOCK:
        try:
            device_id = params.get("device_id", "")
            device = DEVICES.get(device_id)
            if device is None:
                if device_id:
                    return {"ok": False, "error": "设备会话已过期，请重新打开设备页"}
                if params.get("phase", "state") != "state":
                    return {"ok": False, "error": "请先读取设备状态"}
                if len(DEVICES) >= MAX_DEVICES:
                    DEVICES.pop(min(DEVICES, key=lambda key: DEVICES[key].touched))
                device_id = secrets.token_hex(8)
                clock = time.monotonic if now is None else lambda: received
                device = Device(device_id, GestureInput(clock=clock), touched=received)
                DEVICES[device_id] = device
                sid = params.get("sid", "")
                if sid:
                    device.sid = sid
                    device._commit("resume", received)
                else:
                    # A remembered browser slot enables Continue without loading it.
                    remembered = params.get("remembered_sid", "")
                    if isinstance(remembered, str) and re.fullmatch(r"[a-f0-9]{12}", remembered):
                        device.sid = remembered
            elif now is not None:
                device.input.clock = lambda: received
            device.touched = received
            stale = device._refresh(received)
            events = device.input.feed(params.get("phase", "state"), params.get("key"), now=received, busy=device.busy)
            if not stale:
                for event in events:
                    device.handle(event, received)
            if device.page == "battle" and not device.input.sleeping:
                meta = device.state.get("last_battle") or {}
                if received - device.play_started >= meta.get("n", 0) * meta.get("dt", .05) / device.play_speed:
                    device._go("result", received, replace=True)
                    device.input.feed("cancel", now=received)
            return device.view(received)
        except (ValueError, TypeError, KeyError) as exc:
            return {"ok": False, "device_id": params.get("device_id", ""), "error": str(exc)}
