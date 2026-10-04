"""通用/专属两级技能体系（用户裁定 2026-10-04：技能分通用与专属）。

设计：
- **专属技能（signature）**：主角团独有，行为原语组合（profiles.PROFILE
  的 ult 字段是唯一真源——本模块对其做 tier 包装，不重复定义）；
- **通用技能（generic）**：全池其余单位的技能原型，按定位启发式
  **确定性**分配（阈值 + species_id 判别，无随机）——每只可上场
  宝可梦都有技能（王者自走棋语义），但只有主角团有签名行为；
- 与 profiles.PROFILES_ON 同闸：历史实验钉关保基线（skill_of 在
  开关关闭时返回 None，combat 回落「无技能大招」的旧行为）；
- 渲染端（tools/mockups）只读消费 skill_of() 获取 arch/tier 做
  视觉语言分档（普攻 vs 技能 vs 签名技能），本模块不含视觉参数。

通用原语（combat._strike 消费；主线定稿，渲染端同名对齐）：
- double_strike 连击：主命中后 0s 同拍第二击 45%；
- charge 冲锋：出手前向目标突进 1-2 格（近战贴脸语义）；
- heavy_blow 重击：命中后目标被击退 1 格（有空格才退）；
- volley_shot 散射：主命中外再中距目标最近的 2 名敌人各 40%；
- bulwark 铁壁：施法后自身 3s 受伤减免 35%；
- mend 自愈：施法时自愈 20% 最大 HP。
"""

import profiles

GENERIC_ARCHS = ("double_strike", "charge", "heavy_blow",
                 "volley_shot", "bulwark", "mend")

GENERIC_NAMES = {
    "double_strike": "连击", "charge": "冲锋", "heavy_blow": "重击",
    "volley_shot": "散射", "bulwark": "铁壁", "mend": "自愈",
}

GENERIC_DESCRIPTIONS = {
    "double_strike": "主命中后追加一次 45% 伤害打击",
    "charge": "向最远敌人突进至多 2 格，能贴身时转为攻击该目标",
    "heavy_blow": "命中后将目标击退 1 格，目标身后有空位时生效",
    "volley_shot": "命中后再攻击距目标最近的至多 2 名敌人，各 40% 伤害",
    "bulwark": "施法后自身获得 3 秒 35% 减伤",
    "mend": "施法时恢复自身最大生命的 20%",
}

# 定位阈值（pokedex base 种族值口径；与 roster 的远近程判定同源）。
# 全 151 种族值 hp+2def 分布约 55-330、中位 200：260 取上四分位外
# 的「硬坦」带（读数校准：320 时全池仅 2 只入坦，bulwark 分配为 0）
_TANK_FLOOR = 260


def _role_of(base: dict, ranged: bool) -> str:
    bulk = base["hp"] + 2 * base["defense"]
    if bulk >= _TANK_FLOOR:
        return "tank"
    return "ranged_dps" if ranged else "melee_dps"


# 每定位 2~3 个原语，species_id 奇偶确定性分流（同定位不至于全员同技能）
_ROLE_POOL = {
    "tank": ("bulwark", "mend", "heavy_blow"),
    "melee_dps": ("heavy_blow", "charge", "double_strike"),
    "ranged_dps": ("volley_shot", "double_strike", "heavy_blow"),
}


def skill_of(species_id: int):
    """单位的技能档案：{"name","arch","tier"}；开关关闭/无档案 → None。

    专属 = profiles.PROFILE 的八个核心角色（arch 真源在 profile）；其余按
    定位 → 通用池奇偶分流。确定性：同 species_id 恒同结果。
    """
    prof = profiles.get(species_id)
    ult = prof["ult"] if prof else None
    if ult and ult.get("arch"):
        return {"name": ult.get("note", ult["arch"]).split("：")[0],
                "arch": ult["arch"], "tier": "signature"}
    if not profiles.profiles_on():
        return None
    from data import pokedex
    dex = pokedex()
    if species_id not in dex.species:
        return None
    base = dex.species[species_id]["base"]
    ranged = (prof["range"] > 1 if prof and prof["range"] is not None else
              base["special_attack"] > base["attack"])
    pool = _ROLE_POOL[_role_of(base, ranged)]
    arch = pool[species_id % len(pool)]
    return {"name": GENERIC_NAMES[arch], "arch": arch, "tier": "generic"}


def arch_of(species_id: int):
    s = skill_of(species_id)
    return s["arch"] if s else None


def resolve_cast(piece):
    """Executable cast payload, shared by combat and presentation consumers.

    Learned damaging moves retain their existing data and damage rules. A
    generic skill with no learned damaging move uses a neutral BASIC_POWER
    payload and the unit's stronger current attack stat. Its id remains None:
    this is a game skill, not a move inserted into the species' learnset.
    With profiles disabled, a no-move piece keeps its historical basic-only
    behavior. This function does not check energy or mutate the piece/dex.
    """
    from data import BASIC_POWER, pokedex
    if piece.move_id is not None:
        return pokedex().moves[piece.move_id]
    skill = skill_of(piece.species_id)
    if skill is None or skill["tier"] != "generic":
        return None
    return {"id": None, "name": "generic_" + skill["arch"],
            "name_zh": skill["name"], "type": "NONE", "power": BASIC_POWER,
            "accuracy": 100, "effect": None, "damage_stat": "best"}
