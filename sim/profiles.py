"""UnitProfile 单体档案（docs/13 §5，R1 三角色纵向原型）。

设计要点（v2 评审吸收后的形态）：
- **渐进叠加，不全面替代**：PROFILE 只存「有理由的覆盖项」，未覆盖
  字段回落到既有种族值推导链（宪法「数据派生优先」不推翻）。档案里
  每个覆盖项都带理由注释——这是数据合同，不是配置堆。
- **PROFILES_ON 模块开关**（与 SYNERGIES_ON/ITEMS_ON 同款）：历史
  实验钉关保基线（怪力vs胡地锚点含胡地——档案开启后该锚点属新基线，
  由 experiment_profiles 单独记录，不污染旧报告）。
- **四层结构**（docs/13 §5）：原始物种数据(data/) → 本档案(静态覆盖)
  → 持有实例(OwnedPiece，星级归 R2) → 战斗实例(Unit 消费覆盖)。
- **有限原语**：大招 arch ∈ {splash, blink_strike, slam_heal}——
  溅射/瞬移/压顶自愈三个可组合的原语，不开放自由脚本。渲染端签名
  视觉按 species_id 自建表（tools/mockups 侧，不 import 本模块的
  视觉键），本模块的 vfx 字段是设计文档性质的双端对齐说明。

R1 三角色（species_id：喷火龙=6，胡地=65，卡比兽=143）：
- 喷火龙「大字爆炎」= splash：目标全额 + 目标邻格敌人 50%
  （不回能/不吃状态施加/不吃命中骰——溅射必然命中）。
- 胡地「精神强念」= blink_strike：出手瞬间闪现到最弱敌人邻格再命中
  （目标选择 = 最低 HP；闪现落点找不到空格则退化为普通施法）。
- 卡比兽「泰山压顶」= slam_heal：目标全额 + 自身邻格敌人 50% +
  自愈 15% 最大 HP（Z 粒子的机制来源）。
"""

PROFILES_ON = True   # 历史实验钉 False 保基线（同 SYNERGIES_ON 模式）

# 大招原语常量（combat._strike 消费；新增原语必须先扩实验）
ARCH_SPLASH = "splash"
ARCH_BLINK = "blink_strike"
ARCH_SLAM = "slam_heal"

SIDE_HIT_FRAC = 0.5      # 溅射/压顶侧命中伤害比例（对主命中）
SLAM_SELF_HEAL = 0.15    # 压顶自愈比例（最大 HP）

PROFILE = {
    # 喷火龙——远程轰炸位（3 费旗舰）
    6: {
        "name": "喷火龙", "role": "远程轰炸主C",
        "range": 3,               # 与推导一致（特攻手远程）；显式写出让档案自含
        "atk_interval_mult": 0.9, # 吐火弹节奏略快：轰炸位的输出脉动可读
        "hp_mult": 1.0,
        "move_mult": 1.0,         # 飞行语义留给渲染（悬浮步态），移速不加成
        "ult": {"arch": ARCH_SPLASH, "note": "大字爆炎：目标邻格 50% 溅射"},
        "ai": {"kite": True, "retreat_below_hp": None},   # R1 预留，未接线
        "value_mult": 1.10,       # bot 估值：溅射 = 群伤溢价
        "vfx": {"basic": "arc_fire_fast", "ult": "fire_blast_cross",
                "gait": "hover_wing2"},
    },
    # 胡地——瞬移刺客位（2 费中坚，脆皮高爆发）
    65: {
        "name": "胡地", "role": "瞬移刺客",
        "range": 3,
        "atk_interval_mult": 0.85,  # 念力弹快节奏：刺客的攻击脉动
        "hp_mult": 0.85,            # 更脆：闪现换爆发后的生存代价（BST 490 → 面板 -15%）
        "move_mult": 1.0,
        "ult": {"arch": ARCH_BLINK, "note": "精神强念：闪现至最弱敌人邻格"},
        "ai": {"kite": True, "retreat_below_hp": None},
        "value_mult": 1.15,         # bot 估值：斩杀溢出 = 收头溢价
        "vfx": {"basic": "line_psychic_fast", "ult": "blink_ring_in",
                "gait": "glide_spoon2"},
    },
    # 卡比兽——前排巨坦位（3 费旗舰）
    143: {
        "name": "卡比兽", "role": "前排巨坦",
        "range": 1,                # 近战（物攻手推导一致）；显式自含
        "atk_interval_mult": 1.1,  # 重拳慢节奏：每一下都可读（靶场读数校准：1.25 会饿死能量链，场均 0.1 次大招）
        "hp_mult": 1.15,           # 巨坦体格（BST 540 → 面板 +15%）
        "move_mult": 0.85,         # 沉重步态的机制面：走得慢
        "ult": {"arch": ARCH_SLAM, "note": "泰山压顶：邻格 AoE + 自愈 15%"},
        "ai": {"kite": False, "retreat_below_hp": None},
        "value_mult": 1.05,        # bot 估值：坦位溢价低于输出位
        "vfx": {"basic": "heavy_hook_arc", "ult": "slam_dust_z",
                "gait": "heavy_sway2"},
    },
}


def profiles_on() -> bool:
    return PROFILES_ON


def get(species_id: int):
    """取档案；未建档或开关关闭返回 None（调用方回落推导链）。"""
    if not PROFILES_ON:
        return None
    return PROFILE.get(species_id)


def bot_value_mult(species_id: int) -> float:
    """bot 估值乘数（bots.power 消费）；未建档 = 1.0。"""
    p = get(species_id)
    return p["value_mult"] if p else 1.0
