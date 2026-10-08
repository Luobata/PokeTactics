"""状态与 Buff 系统（S12，docs/06-status-buffs.md）——数值臂实现。

接线（combat.py 已预埋，本模块只被调用、不反向修改战斗核）：
- init_battle(battle)：开战初始化（每单位状态容器 + 全队增益槽 + 统计账）；
- tick(battle, t)：主循环每 tick 调用（DOT 跳伤 / 到期解除 / 增益到期，零随机）；
- stunned(unit, t)：_act 顶部的眩晕闸（冰冻/睡眠/畏缩/麻痹停顿共用一个 stun_until）；
- speed_mult(unit)：攻击间隔乘区（麻痹：攻速×0.70 → 间隔×1.43）；
- on_hit(battle, attacker, target, move, t)：_strike 落伤后调用（几率施加）。

机制骨架取自 docs/06 §1-§2；数值臂微调处均在行内注明（实验依据见
reports/status-experiment-2026-09-13.md）：

- 六减益：灼伤/中毒/麻痹/冰冻/睡眠/畏缩。施加来源 = 招式属性命中后按几率表掷
  battle.rng（普攻无属性不施加；未命中不施加）。同种命中刷新时长（中毒斜坡
  保留继续爬），异种被「每单位同时 1 减益」纪律挡下——经典宝可梦的单 Major
  状态位，灼伤的单位不再中毒，属性知识直接可学；
- 免疫 = 属性常识：火免灼伤、毒/钢免中毒、电免麻痹、冰免冰冻（判 target.piece.types）；
- 控制递减：被冰冻/睡眠/麻痹命中后 DR_WINDOW 秒内对控制类免疫（含畏缩；
  畏缩过轻，只受窗口保护、不触发窗口），杜绝无限连控；
- DOT 走 tick（每 1s 一跳），事件 (t, "status", unit_idx, kind, apply|tick|expire, dmg)，
  渲染端对未知事件类型有兜底；DOT 击杀补发既有语义的 (t, "die", idx)；
- 增益 v1 只实现光墙/反射壁/剑舞（蓄气/降雨留占位，等招式系统接线）；
  光墙/反射壁为全队增益（实验参数直接施加：apply_team_buff），剑舞为自身
  物攻增益（apply_sword_dance），面板修正走「施加时记账增量、到期回退」；
- 死亡单位清状态：面板修正静默回退、容器复位（击杀者已发 die，不补 expire）。

约束：STATUS_ON=False 时五个入口全部无操作/中性值（原型读数逐点不变）；
随机只走 battle.rng（宪法 2.2）；除新增 status 事件与 DOT 致死的 die 事件外，
不改既有事件语义。
"""

from collections import Counter

# ---- 模块级开关（模式照抄 synergy.SYNERGIES_ON / data.EFF_*，默认关，主线裁定后翻默认）----
STATUS_ON = True  # 2026-09-14 成套翻开（用户批准；见 reports/flip-all-baseline-2026-09-14.md）


# ---- 减益表（docs/06 §1 骨架数值；数值臂微调见行内注）----
# chance=来源属性招式命中后的施加几率；dur=时长秒；dot/ramp=最大HP比例/秒；
# atk_mod=物攻比例修正（灼伤）；speed=攻速乘区；pause/pause_every=麻痹周期停顿。
DEBUFFS = {
    "burn":   dict(src="FIRE",     chance=0.30, dur=6.0,
                   dot=0.008, atk_mod=-0.10),          # 灼伤：4.8% maxHP 总量
    "poison": dict(src="POISON",   chance=0.35, dur=8.0,
                   dot=0.005, ramp=0.002),             # 中毒：0.5%起步每秒+0.2%，总量 9.6%
    "para":   dict(src="ELECTRIC", chance=0.25, dur=8.0, speed=0.70,
                   pause=0.4, pause_every=3.0),        # 麻痹：攻速-30% + 3s一停
    "freeze": dict(src="ICE",      chance=0.12, dur=1.2),  # 冰冻：短而强眩晕
    "sleep":  dict(src="PSYCHIC",  chance=0.20, dur=2.0),  # 睡眠：受击即醒
    "flinch": dict(chance=0.08, dur=0.3),              # 畏缩：任意命中受击 8%，打击感调味
}
# 招式属性 → 减益（普攻无属性、不在表内的属性招式都不施加）
DEBUFF_BY_SRC = {spec["src"]: k for k, spec in DEBUFFS.items() if "src" in spec}

# 免疫 = 属性常识（docs/06 §1）：知道属性表就懂谁怕什么
IMMUNE_TYPES = {
    "burn":   ("FIRE",),
    "poison": ("POISON", "STEEL"),
    "para":   ("ELECTRIC",),
    "freeze": ("ICE",),
}

# 控制递减：被控制类命中后 DR_WINDOW 秒内免疫控制类（docs/06 §1 防连锁控制）。
# 实验可临时置 0 做无递减对照（experiment_status.py 冰冻臂）。
DR_WINDOW = 5.0
CONTROL_KINDS = ("freeze", "sleep", "para")   # 触发递减窗口的控制类
FLINCH_KIND = "flinch"                        # 只受窗口保护、不触发窗口

DOT_TICK = 1.0   # DOT 结算周期（秒）
_EPS = 1e-9      # 与 combat.py 相同的浮点步长容差

# ---- 增益 v1（docs/06 §2 三种；来源先做成实验参数直接施加，等招式系统接线）----
# stat=结算维度（直接改 Unit 面板，施加记账增量、到期回退）；frac=面板比例；
# dur=None 表示持续到战斗结束（剑舞）；stacks=可叠层数。
BUFFS = {
    "lightscreen": dict(stat="sp_defense", frac=0.30, dur=8.0),   # 光墙：全队特防+30%
    "reflect":     dict(stat="defense",    frac=0.30, dur=8.0),   # 反射壁：全队物防+30%
    "sworddance":  dict(stat="attack",     frac=0.25, dur=None, stacks=2),  # 剑舞：物攻+25%
    # "focus" 蓄气（下次大招必定最高浮动）：等 S5 招式浮动系统接线后实现；
    # "raindance" 降雨（水系伤害+15% 微型天气）：等天气乘区联动（docs/05/S11）后实现。
}
TEAM_BUFF_CAP = 2   # 全队增益槽上限，后进先出（docs/06 §2 的 2 增益纪律）

_KIND_ZH = {"burn": "灼伤", "poison": "中毒", "para": "麻痹", "freeze": "冰冻",
            "sleep": "睡眠", "flinch": "畏缩", "lightscreen": "光墙",
            "reflect": "反射壁", "sworddance": "剑舞"}


class _UnitState:
    """每单位状态容器（init_battle 挂到 unit._st；STATUS_ON=False 时不创建）。"""

    __slots__ = ("debuff", "debuff_source_idx", "expire", "next_dot", "dot_ticks", "para_next",
                 "stun_until", "flinch_until", "ctrl_until", "atk_delta", "buffs",
                 "sd_stacks", "sd_deltas", "debuff_source_epoch", "debuff_spreadable")

    def __init__(self) -> None:
        self.debuff = None      # 当前减益 kind（每单位同时 1 个；flinch 不占槽）
        self.debuff_source_idx = None  # Latest successful applier owns future DOT.
        self.debuff_source_epoch = 0  # A different owner/status never inherits DOT progress.
        self.debuff_spreadable = True
        self.expire = 0.0       # 减益到期时刻
        self.next_dot = 0.0     # 下一跳 DOT 时刻
        self.dot_ticks = 0      # 已跳数（中毒斜坡用）
        self.para_next = 0.0    # 麻痹下一次周期停顿时刻
        self.stun_until = -1.0  # 眩晕闸：冰冻/睡眠/畏缩/麻痹停顿共用
        self.flinch_until = -1.0  # 独立短畏缩截止；净化主要异常时保留
        self.ctrl_until = -1.0  # 控制递减窗口截止（窗口内控制类全免）
        self.atk_delta = 0      # 灼伤物攻减量（到期回退用）
        self.buffs = {}         # 全队增益 name -> {"stat","delta"}（到期时刻在队槽）
        self.sd_stacks = 0      # 剑舞层数
        self.sd_deltas = []     # 每层物攻增量（持续型，战斗内不回退）


# ---------------------------------------------------------------- 战斗入口 --

def init_battle(battle) -> None:
    if not STATUS_ON:
        return
    for u in battle.units:
        u._st = _UnitState()
    # 全队增益槽（光墙/反射壁）：team -> [{"name","expire"}]，LIFO 容量 TEAM_BUFF_CAP
    battle._st_team = {0: [], 1: []}
    # 统计账（实验读数用；单线程 sim 下安全，与 weather.ACTIVE 同口径）
    battle.status_stats = {"applied": Counter(), "blocked": Counter(),
                           "dot_damage": 0, "dot_kills": 0, "woke": 0}


def tick(battle, t: float) -> None:
    """每 tick：DOT 跳伤 → 减益到期 → 麻痹周期停顿 → 全队增益到期。零随机。"""
    if not STATUS_ON:
        return
    stats = battle.status_stats
    for u in battle.units:
        st = getattr(u, "_st", None)
        if st is None:
            continue
        if u.hp <= 0:            # 死亡单位清状态（面板修正静默回退）
            _reset_unit(u, st)
            continue
        # 1) DOT（灼伤恒率 / 中毒递增），先跳伤后判到期：满时长恰好吃满跳数
        if st.debuff in ("burn", "poison") and t + _EPS >= st.next_dot:
            st.next_dot += DOT_TICK
            st.dot_ticks += 1
            rate = DEBUFFS[st.debuff]["dot"]
            if st.debuff == "poison":
                rate += DEBUFFS["poison"]["ramp"] * (st.dot_ticks - 1)
            dmg = max(1, int(u.max_hp * rate))
            hp_damage, packets, protection = dmg, [], None
            source = (battle.units[st.debuff_source_idx]
                      if st.debuff_source_idx is not None else None)
            if battle._arena_on:
                from arena_combinations import consume, emit_packets, clear
                from arena_traits import protect_indirect, emit_protection
                dmg, protection = protect_indirect(battle, u, dmg, t, source)
                hp_damage, packets = consume(battle, u, dmg, t, len(battle.events))
            hp_before = max(0, u.hp)
            u.hp -= hp_damage
            battle._record_hp_loss(source, u, min(hp_before, hp_damage))
            stats["dot_damage"] += hp_damage
            dot_action_index = len(battle.events)
            battle.events.append((t, "status", u.idx, st.debuff, "tick", dmg))
            if u.hp <= 0:        # DOT 致死：补发既有语义的 die 事件
                u.hp = 0
                if battle._arena_on:
                    clear(u)
                stats["dot_kills"] += 1
                _reset_unit(u, st)
                # DOT intentionally bypasses the direct-hit sash; still share
                # the death ledger so later prelaunched hits cannot duplicate die.
                if u.idx not in battle._dead:
                    battle._dead.add(u.idx)
                    battle.events.append((t, "die", u.idx))
                if battle._arena_on:
                    emit_packets(battle, u, t, packets)
                battle._emit_state(u, t)
                continue
            if battle._arena_on:
                emit_packets(battle, u, t, packets)
                emit_protection(battle, u, protection, t, dot_action_index)
            battle._emit_state(u, t)
            if battle._arena_on:
                from arena_offense import after_dot
                after_dot(battle, source, u, st.debuff, t,
                          max(0, hp_before - u.hp), dot_action_index)
                from arena_bonds import after_dot as after_bond_dot
                after_bond_dot(battle, source, u, st.debuff, t,
                               max(0, hp_before - u.hp), dot_action_index)
        # 2) 减益到期（回退面板修正）
        if st.debuff is not None and t + _EPS >= st.expire:
            kind = st.debuff
            _revert_debuff(u, st)
            battle.events.append((t, "status", u.idx, kind, "expire", 0))
            if battle._arena_on:
                from arena_traits import expire
                expire(battle, u, t)
        # 3) 麻痹周期停顿（docs §1：每 3s 停 0.4s；受眩晕闸 0.2s 重试粒度影响，
        #    实际停顿约 0.4~0.6s，见报告注）
        if st.debuff == "para" and t + _EPS >= st.para_next:
            st.stun_until = max(st.stun_until, t + DEBUFFS["para"]["pause"])
            st.para_next += DEBUFFS["para"]["pause_every"]
    _tick_team_buffs(battle, t)   # 4) 全队增益到期（剑舞 dur=None 持续型，不在此列）


def stunned(unit, t: float) -> bool:
    """眩晕闸：冰冻/睡眠/畏缩/麻痹停顿期间不可行动（_act 顶部调用）。"""
    st = getattr(unit, "_st", None)
    return st is not None and t + _EPS < st.stun_until


def speed_mult(unit) -> float:
    """攻击间隔乘区：麻痹攻速×0.70 → 间隔×1.43（其余 1.0）。"""
    st = getattr(unit, "_st", None)
    if st is None or st.debuff != "para":
        return 1.0
    return 1.0 / DEBUFFS["para"]["speed"]


def apply_flinch(battle, unit, t: float) -> bool:
    """确定施加既有短畏缩；不占减益槽，受控制保护，不另开递减窗口。

    技能侧命中使用此有限入口，不调用随机 on_hit，也不绕过 STATUS_ON。
    同拍已有等长/更长停顿时不重复发 apply。
    """
    st = getattr(unit, "_st", None)
    if not STATUS_ON or st is None or not unit.alive:
        return False
    if t + _EPS < st.ctrl_until:
        battle.status_stats["blocked"][(FLINCH_KIND, "dr")] += 1
        return False
    until = t + DEBUFFS[FLINCH_KIND]["dur"]
    if st.stun_until + _EPS >= until:
        return False
    st.stun_until = until
    st.flinch_until = max(st.flinch_until, until)
    battle.status_stats["applied"][FLINCH_KIND] += 1
    battle.events.append((t, "status", unit.idx, FLINCH_KIND, "apply", 0))
    return True


def apply_debuff(battle, unit, kind, t, source=None, *, non_spreading=False):
    """Deterministic native effect with the same immunity/slot/control guards."""
    st = getattr(unit, '_st', None)
    if not STATUS_ON or st is None or not unit.alive or kind not in DEBUFF_BY_SRC.values():
        return False
    reason = ('immune' if set(IMMUNE_TYPES.get(kind, ())) & set(unit.piece.types) else
              'dr' if kind in CONTROL_KINDS and t + _EPS < st.ctrl_until else
              'slot' if st.debuff is not None and st.debuff != kind else None)
    if reason:
        battle.status_stats['blocked'][(kind, reason)] += 1
        return False
    _apply_debuff(battle, unit, kind, t, source=source, non_spreading=non_spreading)
    battle._emit_state(unit, t)
    return True


def cleanse(battle, unit, t, kinds=None):
    """Remove one major status, preserving buffs, short flinch and DR window."""
    st = getattr(unit, '_st', None)
    if not STATUS_ON or st is None or not unit.alive or st.debuff is None:
        return False
    kind = st.debuff
    if kinds is not None and kind not in kinds:
        return False
    _revert_debuff(unit, st)
    if kind in CONTROL_KINDS:
        st.stun_until = max(t, st.flinch_until)
    st.expire, st.next_dot, st.dot_ticks, st.para_next = t, 0., 0, 0.
    battle.events.append((t, 'status', unit.idx, kind, 'expire', 0))
    battle._emit_state(unit, t)
    if battle._arena_on:
        from arena_traits import expire
        expire(battle, unit, t)
    return True


def on_hit(battle, attacker, target, move, t: float, damage=None) -> None:
    """_strike 落伤后：几率施加减益（随机只走 battle.rng，固定顺序保证确定性）。"""
    if not STATUS_ON:
        return
    st = getattr(target, "_st", None)
    if st is None or target.hp <= 0:
        return  # 已被本击打死：不给死人挂状态
    # v2 passes damage explicitly; legacy callers retain the fixed event indices.
    # Appended energy/state fields must never be mistaken for damage.
    ev = battle.events[-1] if battle.events else None
    dmg = damage if damage is not None else (
        ev[4] if ev is not None and ev[1] == "attack" else
        ev[6] if ev is not None and ev[1] == "cast" else 0)
    if dmg <= 0:
        return
    stats = battle.status_stats
    # 睡眠「受击即醒」（docs §1）：先醒（清减益位 + 立即解除眩晕闸），再结算本击
    # 自身的施加（唤醒与再催眠同击可并发，连控由递减窗口兜底）
    if st.debuff == "sleep":
        st.debuff = None
        st.debuff_source_idx = None
        st.stun_until = t
        stats["woke"] += 1
        battle.events.append((t, "status", target.idx, "sleep", "expire", 0))
        if battle._arena_on:
            from arena_traits import expire
            expire(battle, target, t)
    if battle._arena_on:
        from arena_traits import sheer_force_applies
        if sheer_force_applies(battle, attacker, move):
            return
    # 招式属性减益掷骰（免疫/递减/占槽检查在掷骰前，不消耗 rng）
    kind = DEBUFF_BY_SRC.get(move["type"]) if move is not None else None
    if kind is not None:
        _maybe_apply(battle, target, kind, t, source=attacker)
    # 畏缩：任意命中的受击调味。不占减益槽、不触发递减，但窗口期内免（防与冰冻叠加连控）
    if t + _EPS >= st.ctrl_until and \
            battle.rng.random() < DEBUFFS[FLINCH_KIND]["chance"]:
        st.stun_until = max(st.stun_until, t + DEBUFFS[FLINCH_KIND]["dur"])
        st.flinch_until = max(st.flinch_until, t + DEBUFFS[FLINCH_KIND]["dur"])
        stats["applied"][FLINCH_KIND] += 1
        battle.events.append((t, "status", target.idx, FLINCH_KIND, "apply", 0))


# ---------------------------------------------------------------- 内部结算 --

def _maybe_apply(battle, unit, kind: str, t: float, source=None) -> None:
    """按几率表施加减益：免疫 → 递减 → 占槽 三道闸后才掷骰。"""
    st = unit._st
    stats = battle.status_stats
    immune = IMMUNE_TYPES.get(kind, ())
    if immune and set(immune) & set(unit.piece.types):
        stats["blocked"][(kind, "immune")] += 1
        return
    if kind in CONTROL_KINDS and t + _EPS < st.ctrl_until:
        stats["blocked"][(kind, "dr")] += 1
        return
    if st.debuff is not None and st.debuff != kind:
        stats["blocked"][(kind, "slot")] += 1   # 每单位 1 减益：异种顶不掉
        return
    if battle.rng.random() < DEBUFFS[kind]["chance"]:
        _apply_debuff(battle, unit, kind, t, source=source)


def _apply_debuff(battle, unit, kind: str, t: float, source=None, *, non_spreading=False) -> None:
    """挂上/刷新减益：面板修正只在 None→kind 转换时结算一次（刷新不重复叠）。"""
    st = unit._st
    previous_kind = st.debuff
    spec = DEBUFFS[kind]
    if source is None:
        source = battle._stat_effect_source
    source_idx = source.idx if source is not None else None
    if battle._arena_on:
        if st.debuff != kind or st.debuff_source_idx != source_idx:
            st.debuff_source_epoch += 1
        st.debuff_spreadable = not non_spreading
    st.debuff_source_idx = source_idx
    battle.status_stats["applied"][kind] += 1
    if st.debuff != kind:
        st.debuff = kind
        st.dot_ticks = 0
        if kind == "burn":       # 物攻 -10%（经典灼伤；只砍物理端）
            st.atk_delta = int(unit.attack * -DEBUFFS["burn"]["atk_mod"])
            unit.attack -= st.atk_delta
        if kind == "para":
            st.para_next = t + spec["pause_every"]
        if "dot" in spec:
            st.next_dot = t + DOT_TICK
    st.expire = t + spec["dur"]
    if kind in ("freeze", "sleep"):
        # 眩晕时长按 stun_until 取 max（不叠加，只延长）；递减窗口同步起表
        st.stun_until = max(st.stun_until, st.expire)
    if kind in CONTROL_KINDS:
        st.ctrl_until = t + DR_WINDOW
    battle.events.append((t, "status", unit.idx, kind, "apply", 0))
    if battle._arena_on and previous_kind is None:
        from arena_equipment import after_debuff
        after_debuff(battle, source, unit, kind, t)
        from arena_traits import after_debuff as trait_after_debuff
        trait_after_debuff(battle, source, unit, kind, t)


def _revert_debuff(unit, st: _UnitState) -> None:
    """到期解除：回退面板修正并清位（事件由调用方发）。"""
    if st.debuff == "burn" and st.atk_delta:
        unit.attack += st.atk_delta
        st.atk_delta = 0
    st.debuff = None
    st.debuff_source_idx = None


def _reset_unit(unit, st: _UnitState) -> None:
    """死亡清状态：面板修正回退、容器复位（不发事件）。"""
    _revert_debuff(unit, st)
    st.stun_until = -1.0
    st.flinch_until = -1.0
    st.ctrl_until = -1.0
    st.buffs.clear()


def _tick_team_buffs(battle, t: float) -> None:
    """全队增益（光墙/反射壁）到期：按队槽统一回退。"""
    for team, slots in battle._st_team.items():
        for entry in list(slots):
            if t + _EPS < entry["expire"]:
                continue
            slots.remove(entry)
            name = entry["name"]
            for u in battle.units:
                if u.team != team:
                    continue
                st = getattr(u, "_st", None)
                b = st.buffs.pop(name, None) if st is not None else None
                if u.hp > 0:
                    if b is not None:
                        setattr(u, b["stat"], getattr(u, b["stat"]) - b["delta"])
                    battle.events.append((t, "status", u.idx, name, "expire", 0))


# ---------------------------------------------------------------- 增益入口 --
# v1 来源 = 实验参数直接施加（无随机、事件走 status 流）；招式系统接线后
# 改由格斗/超能系招式触发（docs/06 §2 的来源列）。

def apply_team_buff(battle, team: int, name: str, t: float) -> None:
    """给一队施加全队增益（光墙/反射壁）。重复施加=刷新时长；队槽 LIFO 容量 2。"""
    if not STATUS_ON or name not in BUFFS:
        return
    spec = BUFFS[name]
    slots = battle._st_team[team]
    if name not in [e["name"] for e in slots]:
        if len(slots) >= TEAM_BUFF_CAP:      # 后进先出：挤掉最早的队增益
            victim = slots.pop(0)["name"]
            _remove_team_buff(battle, team, victim, t)
        slots.append({"name": name, "expire": t + spec["dur"]})
    else:
        for e in slots:
            if e["name"] == name:
                e["expire"] = t + spec["dur"]
    for u in battle.units:
        if u.team != team or u.hp <= 0:
            continue
        _grant_unit_buff(battle, u, name, spec, t)


def _remove_team_buff(battle, team: int, name: str, t: float) -> None:
    slots = battle._st_team[team]
    slots[:] = [e for e in slots if e["name"] != name]
    for u in battle.units:
        if u.team != team or u.hp <= 0:
            continue
        st = getattr(u, "_st", None)
        b = st.buffs.pop(name, None) if st is not None else None
        if b is not None:
            setattr(u, b["stat"], getattr(u, b["stat"]) - b["delta"])
        battle.events.append((t, "status", u.idx, name, "expire", 0))


def _grant_unit_buff(battle, u, name: str, spec: dict, t: float) -> None:
    """把队增益落到单个单位（面板增量记账 + apply 事件）。刷新先回退旧增量。"""
    st = u._st
    old = st.buffs.pop(name, None)
    if old is not None:   # 刷新：先按旧增量回退、补一条 expire，再按当前面板记新
        setattr(u, old["stat"], getattr(u, old["stat"]) - old["delta"])
        battle.events.append((t, "status", u.idx, name, "expire", 0))
    delta = int(getattr(u, spec["stat"]) * spec["frac"])
    setattr(u, spec["stat"], getattr(u, spec["stat"]) + delta)
    st.buffs[name] = {"stat": spec["stat"], "delta": delta}
    battle.events.append((t, "status", u.idx, name, "apply", 0))


def apply_sword_dance(battle, unit, t: float) -> bool:
    """剑舞：自身物攻 +25%，最多叠 2 层，持续到战斗结束。"""
    if not STATUS_ON:
        return False
    spec = BUFFS["sworddance"]
    st = unit._st
    if st.sd_stacks >= spec["stacks"]:
        return False
    delta = int(unit.attack * spec["frac"])
    unit.attack += delta
    st.sd_stacks += 1
    st.sd_deltas.append(delta)
    battle.status_stats["applied"]["sworddance"] += 1
    battle.events.append((t, "status", unit.idx, "sworddance", "apply",
                          st.sd_stacks))   # dmg 位携带层数（渲染端自由解读）
    return True


def kind_label(kind: str) -> str:
    return _KIND_ZH.get(kind, kind)
