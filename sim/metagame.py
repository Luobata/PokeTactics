"""Offline challenge progress, independent of the shop and combat statistics.

Each run contributes a cumulative snapshot under one persistent run id. Keeping
the complete bounded ledger makes retries and restored older sessions safe: sets
are unioned, the round is maximized, and a completed result never becomes live
again. Unlocks are derived options for the next run, never permanent stat buffs.
"""

import re

MAX_RUNS = 2048
MAX_ROUNDS = 31
MAX_SPECIES_ID = 65535
MAX_OBSERVATIONS_PER_RUN = 151
# Compatibility name for the bounded list size, not a species-id ceiling.
MAX_SPECIES = MAX_OBSERVATIONS_PER_RUN
# Arena per-run cumulative counters stay bounded so merged snapshots remain safe.
MAX_ARENA_KILLS_PER_RUN = 4096
MAX_ARENA_COMBOS_PER_BATTLE = 1024
MAX_ARENA_BONDS_PER_RUN = 24
_ARENA_BOND_ID = re.compile(r"[A-Za-z_]{1,32}\Z")
_ARENA_PROGRESS_FIELDS = {"kills", "bonds", "combos", "streak"}
_RUN_ID = re.compile(r"[0-9a-f]{32}\Z")
_PROGRESS_FIELDS = {"seen", "fielded", "won", "round", "finished", "rank"}

PARTNERS = (
    {"id": 3, "name": "妙蛙花", "description": "草与毒属性的初始伙伴", "challenge": None},
    {"id": 6, "name": "喷火龙", "description": "火与飞行属性的初始伙伴", "challenge": None},
    {"id": 9, "name": "水箭龟", "description": "水属性的初始伙伴", "challenge": None},
    {"id": 26, "name": "雷丘", "description": "电属性的挑战伙伴", "challenge": "field_three"},
    {"id": 143, "name": "卡比兽", "description": "一般属性的挑战伙伴", "challenge": "field_six"},
)
TECHNIQUES = (
    {"id": "none", "name": "未携带", "description": "使用伙伴原有招式", "challenge": None},
    {"id": "cut", "name": "居合斩", "description": "伙伴可选择居合斩战术招式", "challenge": "first_field"},
    {"id": "surf", "name": "冲浪", "description": "伙伴可选择冲浪战术招式", "challenge": "field_three"},
    {"id": "rest", "name": "睡觉", "description": "伙伴可选择睡觉战术招式", "challenge": "finish_run"},
)
STARTER_ITEMS = (
    {"id": "none", "name": "未携带", "description": "不选择开局装备", "challenge": None},
    {"id": "leftovers", "name": "剩饭", "description": "战斗中持续恢复生命", "challenge": "finish_run"},
    # The existing items.FINISHED identifier is sash, not focus_sash.
    {"id": "sash", "name": "气势披带", "description": "每场首次致命伤时保留生命", "challenge": "field_six"},
)
ARENA_CHALLENGES = (
    {"id": "arena_first_finish", "name": "竞技首秀", "description": "完成 1 局竞技对战，无论名次",
     "metric": "runs", "target": 1,
     "rewards": [{"kind": "arena_augment", "id": "war_banner", "name": "海克斯候选·战旗高扬"}]},
    {"id": "arena_first_win", "name": "竞技场冠军", "description": "在竞技模式夺冠 1 次",
     "metric": "wins", "target": 1,
     "rewards": [{"kind": "arena_augment", "id": "deep_reserves", "name": "海克斯候选·深厚储备"}]},
    {"id": "arena_bonds_6", "name": "羁绊编织者", "description": "跨局累计点亮 6 组不同羁绊",
     "metric": "bonds", "target": 6,
     "rewards": [{"kind": "arena_trait", "id": "trait_verdant_rhythm", "name": "大竺葵互斥特性·翠绿节律"}]},
    {"id": "arena_combo_12", "name": "连锁反应", "description": "单场战斗触发 12 次联动效果",
     "metric": "combos", "target": 12, "rewards": []},
    {"id": "arena_kills_60", "name": "终结者", "description": "竞技战斗跨局累计击杀 60 次",
     "metric": "kills", "target": 60, "rewards": []},
    {"id": "arena_streak_6", "name": "连胜势头", "description": "单局竞技取得 6 连胜",
     "metric": "streak", "target": 6, "rewards": []},
    {"id": "arena_dex_24", "name": "竞技收藏家", "description": "竞技中跨局累计上场 24 种不同精灵",
     "metric": "species", "target": 24, "rewards": []},
)
CHALLENGES = (
    {"id": "first_field", "name": "首次出战", "description": "累计上场 1 种宝可梦",
     "metric": "fielded", "target": 1,
     "rewards": [{"kind": "technique", "id": "cut", "name": "居合斩"}]},
    {"id": "field_three", "name": "尝试新搭档", "description": "累计上场 3 种宝可梦",
     "metric": "fielded", "target": 3,
     "rewards": [{"kind": "partner", "id": 26, "name": "雷丘"},
                 {"kind": "technique", "id": "surf", "name": "冲浪"}]},
    {"id": "finish_run", "name": "完整旅程", "description": "完成 1 局对战，无论胜负",
     "metric": "finished", "target": 1,
     "rewards": [{"kind": "technique", "id": "rest", "name": "睡觉"},
                 {"kind": "item", "id": "leftovers", "name": "剩饭"}]},
    {"id": "field_six", "name": "多样阵容", "description": "累计上场 6 种宝可梦",
     "metric": "fielded", "target": 6,
     "rewards": [{"kind": "partner", "id": 143, "name": "卡比兽"},
                 {"kind": "item", "id": "sash", "name": "气势披带"}]},
)


class ProfileCapacityError(ValueError):
    """Capacity is exhausted; old run ids must not be evicted to make room."""


def initial_profile():
    """Return an independent, JSON-compatible profile with no recorded runs."""
    return {"runs": {}}


def validate_run_id(value):
    if type(value) is not str or not _RUN_ID.fullmatch(value):
        raise ValueError("局外档案 run_id 必须为 32 位小写十六进制标识")
    return value


def _species_list(value, label):
    if type(value) is not list or len(value) > MAX_OBSERVATIONS_PER_RUN:
        raise ValueError(f"局外档案 {label} 必须是最多 {MAX_OBSERVATIONS_PER_RUN} 项的物种列表")
    if any(type(sid) is not int or not 1 <= sid <= MAX_SPECIES_ID for sid in value):
        raise ValueError(f"局外档案 {label} 含无效物种编号")
    if len(value) != len(set(value)):
        raise ValueError(f"局外档案 {label} 含重复物种编号")
    return sorted(value)


def _arena_progress(value):
    """Validate one run's cumulative arena counters and return a canonical copy."""
    if type(value) is not dict or set(value) != _ARENA_PROGRESS_FIELDS:
        raise ValueError("局外档案竞技进度字段不完整或含未知字段")
    kills = value["kills"]
    if type(kills) is not int or not 0 <= kills <= MAX_ARENA_KILLS_PER_RUN:
        raise ValueError(f"局外档案竞技击杀必须在 0 至 {MAX_ARENA_KILLS_PER_RUN} 之间")
    combos = value["combos"]
    if type(combos) is not int or not 0 <= combos <= MAX_ARENA_COMBOS_PER_BATTLE:
        raise ValueError(f"局外档案单场联动必须在 0 至 {MAX_ARENA_COMBOS_PER_BATTLE} 之间")
    streak = value["streak"]
    if type(streak) is not int or not 0 <= streak <= MAX_ROUNDS:
        raise ValueError(f"局外档案最高连胜必须在 0 至 {MAX_ROUNDS} 之间")
    bonds = value["bonds"]
    if (type(bonds) is not list or len(bonds) > MAX_ARENA_BONDS_PER_RUN
            or any(type(b) is not str or not _ARENA_BOND_ID.fullmatch(b) for b in bonds)
            or len(bonds) != len(set(bonds))):
        raise ValueError(f"局外档案竞技羁绊必须是最多 {MAX_ARENA_BONDS_PER_RUN} 项的羁绊编号列表")
    return {"kills": kills, "bonds": sorted(bonds), "combos": combos, "streak": streak}


def _merge_arena(previous, incoming):
    """Idempotent merge: counters maximize, the bond set unions."""
    zero = {"kills": 0, "bonds": [], "combos": 0, "streak": 0}
    previous, incoming = previous or zero, incoming or zero
    return _arena_progress({
        "kills": max(previous["kills"], incoming["kills"]),
        "bonds": sorted(set(previous["bonds"]) | set(incoming["bonds"])),
        "combos": max(previous["combos"], incoming["combos"]),
        "streak": max(previous["streak"], incoming["streak"])})


def _progress(value):
    if type(value) is not dict or set(value) - {"arena"} != _PROGRESS_FIELDS:
        raise ValueError("局外档案对局进度字段不完整或含未知字段")
    optional = "arena" in value
    result = {key: _species_list(value[key], key) for key in ("seen", "fielded", "won")}
    if not set(result["won"]) <= set(result["fielded"]) <= set(result["seen"]):
        raise ValueError("胜利物种必须已上场，上场物种必须已见过")
    round_no = value["round"]
    if type(round_no) is not int or not 0 <= round_no <= MAX_ROUNDS:
        raise ValueError(f"局外档案回合必须在 0 至 {MAX_ROUNDS} 之间")
    finished, rank = value["finished"], value["rank"]
    if type(finished) is not bool:
        raise ValueError("局外档案 finished 必须为布尔值")
    if finished:
        if type(rank) is not int or not 1 <= rank <= 8 or round_no < 1:
            raise ValueError("已完成对局必须含 1 至 8 的名次及至少一个回合")
    elif rank is not None:
        raise ValueError("未完成对局不能记录最终名次")
    result.update(round=round_no, finished=finished, rank=rank)
    if optional:
        result["arena"] = _arena_progress(value["arena"])
    return result


def validate_snapshot(snapshot):
    """Validate a cumulative run snapshot and return a detached canonical copy."""
    if type(snapshot) is not dict or set(snapshot) - {"arena"} != _PROGRESS_FIELDS | {"run_id"}:
        raise ValueError("对局快照字段不完整或含未知字段")
    run_id = validate_run_id(snapshot["run_id"])
    return {"run_id": run_id, **_progress({k: snapshot[k] for k in _PROGRESS_FIELDS | {"arena"} if k in snapshot})}


def validate_profile(profile):
    """Strictly validate the persisted ledger, without accepting derived totals."""
    if type(profile) is not dict or set(profile) != {"runs"} or type(profile["runs"]) is not dict:
        raise ValueError("局外档案必须包含 runs 对局账本")
    if len(profile["runs"]) > MAX_RUNS:
        raise ProfileCapacityError(f"局外档案最多保存 {MAX_RUNS} 局，不能丢弃历史去重记录")
    return {"runs": {validate_run_id(run_id): _progress(progress)
                     for run_id, progress in profile["runs"].items()}}


def apply_progress(profile, snapshot):
    """Merge one cumulative snapshot, returning a new profile without mutation.

    A terminal rank is immutable. Conflicting terminal results for a shared id
    indicate a broken run identity and are rejected instead of rewriting wins.
    Older unfinished snapshots can still contribute previously unseen species.
    """
    result = validate_profile(profile)
    incoming = validate_snapshot(snapshot)
    run_id = incoming.pop("run_id")
    previous = result["runs"].get(run_id)
    if previous is None:
        if len(result["runs"]) >= MAX_RUNS:
            raise ProfileCapacityError(f"局外档案已达 {MAX_RUNS} 局容量，请保留备份；历史记录不会被删除")
        result["runs"][run_id] = incoming
        return result
    if previous["finished"] and incoming["finished"] and previous["rank"] != incoming["rank"]:
        raise ValueError("同一 run_id 的最终名次不能改变")
    for key in ("seen", "fielded", "won"):
        previous[key] = sorted(set(previous[key]) | set(incoming[key]))
    previous["round"] = max(previous["round"], incoming["round"])
    if incoming["finished"]:
        previous["finished"], previous["rank"] = True, incoming["rank"]
    if "arena" in previous or "arena" in incoming:
        previous["arena"] = _merge_arena(previous.get("arena"), incoming.get("arena"))
    # Individually bounded snapshots can have a union larger than one run can
    # store. Reject that merge before returning an invalid or truncated ledger.
    result["runs"][run_id] = _progress(previous)
    return result


update = apply_progress


def view(profile):
    """Return derived statistics, challenge progress, and selectable catalogs."""
    profile = validate_profile(profile)
    records = list(profile["runs"].values())
    dex = {key: sorted({sid for record in records for sid in record[key]})
           for key in ("seen", "fielded", "won")}
    completed = [record for record in records if record["finished"]]
    stats = {"runs": len(records), "finished": len(completed),
             "wins": sum(record["rank"] == 1 for record in completed),
             "top4": sum(record["rank"] <= 4 for record in completed),
             "rounds": sum(record["round"] for record in records),
             **{key: len(species) for key, species in dex.items()}}
    challenges = []
    for challenge in CHALLENGES:
        current = min(stats[challenge["metric"]], challenge["target"])
        challenges.append({"id": challenge["id"], "name": challenge["name"],
                           "description": challenge["description"], "current": current,
                           "target": challenge["target"], "unlocked": current >= challenge["target"],
                           "rewards": [dict(reward) for reward in challenge["rewards"]]})
    unlocked = {challenge["id"] for challenge in challenges if challenge["unlocked"]}

    def catalog(entries):
        return [{**entry, "unlocked": entry["challenge"] is None or entry["challenge"] in unlocked}
                for entry in entries]

    partners, techniques, items = catalog(PARTNERS), catalog(TECHNIQUES), catalog(STARTER_ITEMS)
    return {"stats": stats, "dex": dex, "challenges": challenges,
            "partners": partners, "techniques": techniques, "starter_items": items,
            "partner_ids": [entry["id"] for entry in partners if entry["unlocked"]],
            "technique_ids": [entry["id"] for entry in techniques if entry["unlocked"]],
            "item_ids": [entry["id"] for entry in items if entry["unlocked"]],
            "arena": _arena_view(records)}


def _arena_view(records):
    """Aggregate arena runs; rewards unlock candidate options, never stats."""
    arena_runs = [record for record in records if "arena" in record]
    bonds = sorted({bond for record in arena_runs for bond in record["arena"]["bonds"]})
    species = sorted({sid for record in arena_runs for sid in record["fielded"]})
    stats = {"runs": sum(record["finished"] for record in arena_runs),
             "wins": sum(record["finished"] and record["rank"] == 1 for record in arena_runs),
             "kills": sum(record["arena"]["kills"] for record in arena_runs),
             "combos": max((record["arena"]["combos"] for record in arena_runs), default=0),
             "streak": max((record["arena"]["streak"] for record in arena_runs), default=0),
             "bonds": len(bonds), "species": len(species)}
    challenges = []
    for challenge in ARENA_CHALLENGES:
        current = min(stats[challenge["metric"]], challenge["target"])
        challenges.append({"id": challenge["id"], "name": challenge["name"],
                           "description": challenge["description"], "current": current,
                           "target": challenge["target"], "unlocked": current >= challenge["target"],
                           "rewards": [dict(reward) for reward in challenge["rewards"]]})
    unlocked = {challenge["id"] for challenge in challenges if challenge["unlocked"]}
    rewards = [reward for challenge in ARENA_CHALLENGES if challenge["id"] in unlocked
               for reward in challenge["rewards"]]
    return {"stats": stats, "challenges": challenges, "bond_ids": bonds, "species_ids": species,
            "augment_ids": [reward["id"] for reward in rewards if reward["kind"] == "arena_augment"],
            "trait_ids": [reward["id"] for reward in rewards if reward["kind"] == "arena_trait"]}


def arena_completed(profile):
    """Ids of arena challenges already complete; used to announce new unlocks."""
    return {challenge["id"] for challenge in view(profile)["arena"]["challenges"]
            if challenge["unlocked"]}
