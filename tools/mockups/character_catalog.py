"""Player-facing character identity, grounded in the active combat and rig data."""
from character_rigs import catalog as rig_catalog
from profiles import get as profile_of
from data import pokedex

# Tactical intent is presentation data. Damage, targets, ranges and action tracks
# continue to come from the simulator/rig definitions, never from these strings.
TACTICS = {
    6: ("打击抱团后排", "分散站位，避免多人紧贴主目标。", "抬爪助力火弹", "展翼蓄火，从口部喷射火焰"),
    9: ("打穿纵向阵线，打乱前排", "错开前后排，边界或占用格会阻止击退。", "双炮短促后坐", "炮筒蓄压、贯穿水柱、主目标后退"),
    3: ("靠近前排提供续航", "拉开治疗距离；满血队伍无法储存溢出治疗。", "左右藤鞭伸展回收", "花盘聚光，日光束命中后回流治疗"),
    26: ("惩罚相距较近的多个敌人", "分散超过跳跃距离；地面免疫可截断电链。", "电火花", "十万伏特在相邻目标间跳跃"),
    65: ("切入生命最低的敌人", "保护残血角色周围的落点；胡地切入后较脆。", "念力弹", "消失、瞬移落位、精神强念"),
    94: ("干扰敌人大招节奏", "低能量目标可供偷取的能量较少；一般系免疫舌舔。", "幽灵波动", "舌舔命中后，将偷取的能量拉回自身"),
    76: ("在接敌处震击多人", "避免围住隆隆岩；飞行系免疫地震。", "岩石重击", "地面裂纹扩散，邻格受击与短暂畏缩"),
    143: ("前排承伤与自我续航", "保持距离减少邻格波及；集中伤害压过自愈。", "重拳", "蓄力光束、近身震荡、自愈"),
}


# Content can be promoted independently: mechanics, body, parts and effects are
# separate capabilities. A species never needs to appear in TACTICS to play.
GENERIC_TACTICS = {
    "double_strike": ("主命中后追加一次 45% 伤害", "压低单体血量", "用高防单位承接连续攻击。"),
    "charge": ("施法前向目标突进，最多两格", "缩短接敌距离", "用前排限制突进落点。"),
    "heavy_blow": ("命中后将目标击退一格，有空格才生效", "打乱敌人阵形", "利用边界或占用格阻止击退。"),
    "volley_shot": ("主命中外，追加攻击最近两名敌人，各 40% 伤害", "同时压低多个敌人的血量", "多名承伤单位分担散射。"),
    "bulwark": ("施法后自身获得 3 秒 35% 减伤", "前排持续承伤", "减伤结束后集中输出。"),
    "mend": ("施法时回复自身最大生命的 20%", "前排自我续航", "集中伤害压过回复。"),
}


def character_catalog(*, pieces=None, asset_root=None):
    """JSON-safe capability catalog for the active roster, with no ID allowlist.

    Optional inputs let exporters validate the exact asset pack being shipped.
    Missing art is reported separately from simulation/skill readiness.
    """
    from pathlib import Path
    from roster import build_roster
    from skills import skill_of, resolve_cast, GENERIC_DESCRIPTIONS
    from profiles import effective_range
    from motion import species_motion
    from skill_vfx import AUTHORED_SKILLS
    from move_effects import SUPPORTED_SPECIES
    from decoders import Front, Palettes, POKEWALK
    root = Path(asset_root) if asset_root is not None else POKEWALK
    front, palettes = Front(root / "gen1_front.bin"), Palettes(root / "palettes.bin")
    if pieces is None:
        pieces = [p for group in build_roster().values() for p in group]
    rigs, result = rig_catalog(), {}
    for piece in sorted(pieces, key=lambda p: p.species_id):
        sid = piece.species_id
        profile, skill, move = profile_of(sid), skill_of(sid), resolve_cast(piece)
        signature = bool(skill and skill["tier"] == "signature")
        rig = rigs.get(str(sid), {"implemented": False, "parts": [], "anchors": {}})
        errors = []
        blob = front.blob_of.get(sid)
        if blob is None:
            errors.append(f"缺少精灵资源 front/{sid}")
        elif len(blob) != front.size_of.get(sid, 0) ** 2 // 4:
            errors.append(f"精灵资源 front/{sid} 数据长度错误")
        elif not blob or all(b == 255 for b in blob):
            errors.append(f"精灵资源 front/{sid} 全透明")
        try:
            palettes.for_species(sid)
        except (ValueError, IndexError, KeyError) as exc:
            errors.append(f"缺少有效色板 species/{sid}: {exc}")
        arch = skill["arch"] if skill else None
        description, tactic, counterplay = GENERIC_TACTICS.get(arch, ("使用学习表中的伤害招式", "依照属性与射程安排站位", "用属性克制与站位应对。"))
        description = GENERIC_DESCRIPTIONS.get(arch, description)
        attack, cast = "程序化蓄力、出手、回收", "通用技能模板，按真实命中播放"
        if signature:
            description = profile["ult"].get("note", GENERIC_DESCRIPTIONS.get(arch, skill["name"]))
            if sid in TACTICS:
                tactic, counterplay, attack, cast = TACTICS[sid]
        elif sid in species_motion:
            attack = "手编整身动作与真实命中时序"
        if not move:
            description, cast = "当前规则下无可施放技能", "不支持施法"
        authored = AUTHORED_SKILLS.get(sid)
        authored_vfx = bool(move and authored and authored[0] == move["id"])
        body = "part_rig" if rig["implemented"] else "authored_pose" if sid in species_motion else "procedural"
        effect = ("none" if not move else "layered" if sid in SUPPORTED_SPECIES
                  else "authored" if authored_vfx else "archetype")
        controls = ["palette", "effect_scale", "particle_density", "motion_scale"] if sid in SUPPORTED_SPECIES else []
        result[str(sid)] = {
            "species": sid, "name": piece.name,
            "role": profile.get("role", "通用技能") if profile else "通用技能",
            "cost": piece.tier, "range": effective_range(piece),
            "skill": {"move_id": piece.move_id, "name": (move.get("name_zh") or move["name"]) if move else "无",
                      "tier": skill["tier"] if skill and move else "legacy" if move else "none",
                      "arch": arch, "can_cast": bool(move), "fallback_payload": bool(move and piece.move_id is None),
                      "description": description, "tactic": tactic, "counterplay": counterplay},
            "rig": rig, "motion_notes": {"attack": attack, "cast": cast},
            "capabilities": {"body": body, "effect": effect, "resource_ready": not errors,
                             "resource_errors": errors, "actions": ["attack"] + (["cast"] if move else []),
                             "editable_controls": controls},
        }
    return result
