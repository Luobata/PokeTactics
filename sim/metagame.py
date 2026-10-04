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


def _progress(value):
    if type(value) is not dict or set(value) != _PROGRESS_FIELDS:
        raise ValueError("局外档案对局进度字段不完整或含未知字段")
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
    return result


def validate_snapshot(snapshot):
    """Validate a cumulative run snapshot and return a detached canonical copy."""
    if type(snapshot) is not dict or set(snapshot) != _PROGRESS_FIELDS | {"run_id"}:
        raise ValueError("对局快照字段不完整或含未知字段")
    run_id = validate_run_id(snapshot["run_id"])
    return {"run_id": run_id, **_progress({k: snapshot[k] for k in _PROGRESS_FIELDS})}


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
            "item_ids": [entry["id"] for entry in items if entry["unlocked"]]}
