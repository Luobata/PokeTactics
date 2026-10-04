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


def character_catalog():
    dex, rigs = pokedex(), rig_catalog()
    result = {}
    for sid, (tactic, counterplay, attack, cast) in TACTICS.items():
        profile, move = profile_of(sid), dex.signature_move(sid)
        result[str(sid)] = {
            "species": sid, "name": dex.species[sid]["name_zh"],
            "role": profile["role"] if profile else "通用技能",
            "skill": {"move_id": move["id"], "name": move.get("name_zh") or move["name"],
                      "description": profile["ult"]["note"] if profile else "档案已关闭，使用通用技能规则。",
                      "tactic": tactic if profile else "通用技能规则",
                      "counterplay": counterplay if profile else "当前未启用该专属机制。"},
            "rig": rigs[str(sid)],
            "motion_notes": {"attack": attack, "cast": cast},
        }
    return result
