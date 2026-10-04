"""UnitProfile 单体档案（docs/13 §5，八个核心角色的有限技能原语）。

设计要点（v2 评审吸收后的形态）：
- **渐进叠加，不全面替代**：PROFILE 只存「有理由的覆盖项」，未覆盖
  字段回落到既有种族值推导链（宪法「数据派生优先」不推翻）。档案里
  每个覆盖项都带理由注释——这是数据合同，不是配置堆。
- **PROFILES_ON 模块开关**（与 SYNERGIES_ON/ITEMS_ON 同款）：历史
  实验钉关保基线（怪力vs胡地锚点含胡地——档案开启后该锚点属新基线，
  由 experiment_profiles 单独记录，不污染旧报告）。
- **四层结构**（docs/13 §5）：原始物种数据(data/) → 本档案(静态覆盖)
  → 持有实例(OwnedPiece，星级归 R2) → 战斗实例(Unit 消费覆盖)。
- **有限原语**：大招 arch 由本模块的八个 ARCH_* 常量限定，
  不开放自由脚本。渲染端签名
  视觉按 species_id 自建表（tools/mockups 侧，不 import 本模块的
  视觉键），本模块的 vfx 字段是设计文档性质的双端对齐说明。

保留 R1 三角色机制，招名与实际 move_id 的数据标签一致：
- 喷火龙「喷射火焰」= splash：目标全额 + 目标邻格敌人 50%
  （不回能/不吃状态施加/不吃命中骰——溅射必然命中）。
- 胡地「精神强念」= blink_strike：出手瞬间闪现到最弱敌人邻格再命中
  （目标选择 = 最低 HP；闪现落点找不到空格则退化为普通施法）。
- 卡比兽「破坏光线」= slam_heal：目标全额 + 自身邻格敌人 50% +
  自愈 15% 最大 HP（Z 粒子的机制来源）。
"""

PROFILES_ON = True   # 历史实验钉 False 保基线（同 SYNERGIES_ON 模式）

# 大招原语常量（combat._strike 消费；新增原语必须先扩实验）
ARCH_SPLASH = "splash"
ARCH_BLINK = "blink_strike"
ARCH_SLAM = "slam_heal"
ARCH_LINE = "line_push"
ARCH_SOLAR = "solar_siphon"
ARCH_CHAIN = "chain_lightning"
ARCH_DRAIN = "energy_drain"
ARCH_QUAKE = "quake_break"

SIDE_HIT_FRAC = 0.5      # 溅射/压顶侧命中伤害比例（对主命中）
SLAM_SELF_HEAL = 0.15    # 压顶自愈比例（最大 HP）
LINE_SIDE_FRAC = 0.45   # 总宽 1 格的前向射线，最多两个独立侧命中
SOLAR_HEAL_FRAC = 0.35  # 按主目标实际掉血治疗 2 格内 HP 比例最低的受伤友军
CHAIN_FRACS = (0.55, 0.35)  # 每跳曼哈顿距离 <= 2，免疫目标截断连锁
ENERGY_DRAIN_MAX = 20
QUAKE_SIDE_FRAC = 0.40

PROFILE = {
    # 喷火龙——远程轰炸位（3 费旗舰）
    6: {
        "name": "喷火龙", "role": "远程轰炸主C",
        "range": 3,               # 与推导一致（特攻手远程）；显式写出让档案自含
        "atk_interval_mult": 0.9, # 吐火弹节奏略快：轰炸位的输出脉动可读
        "hp_mult": 1.0,
        "move_mult": 1.0,         # 飞行语义留给渲染（悬浮步态），移速不加成
        "ult": {"arch": ARCH_SPLASH, "note": "喷射火焰：目标邻格 50% 溅射"},
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
        "ult": {"arch": ARCH_SLAM, "note": "破坏光线：邻格 AoE + 自愈 15%"},
        "ai": {"kite": False, "retreat_below_hp": None},
        "value_mult": 1.05,        # bot 估值：坦位溢价低于输出位
        "vfx": {"basic": "heavy_hook_arc", "ult": "slam_dust_z",
                "gait": "heavy_sway2"},
    },
    # 新五角色先保留种族值面板；新增机制强度是可测初值，尚未完成配平。
    9: {
        "name": "水箭龟", "role": "直线贯穿击退",
        "range": 3, "atk_interval_mult": 1.0, "hp_mult": 1.0, "move_mult": 1.0,
        "ult": {"arch": ARCH_LINE, "note": "水炮：前向直线最多贯穿两敌，各 45%，主目标击退一格"},
        "ai": {"kite": True, "retreat_below_hp": None}, "value_mult": 1.0,
        "vfx": {"basic": "water_round", "ult": "twin_cannon", "gait": "shell_step"},
    },
    3: {
        "name": "妙蛙花", "role": "伤害转化治疗",
        "range": 3, "atk_interval_mult": 1.0, "hp_mult": 1.0, "move_mult": 1.0,
        "ult": {"arch": ARCH_SOLAR, "note": "日光束：实际伤害的 35% 治疗两格内最虚弱友军"},
        "ai": {"kite": True, "retreat_below_hp": None}, "value_mult": 1.0,
        "vfx": {"basic": "seed_ray", "ult": "flower_lens", "gait": "heavy_leaf"},
    },
    26: {
        "name": "雷丘", "role": "远程连锁电击",
        # 双攻相等的推导会给近战；连锁施法者明确拥有三格射程。
        "range": 3, "atk_interval_mult": 1.0, "hp_mult": 1.0, "move_mult": 1.0,
        "ult": {"arch": ARCH_CHAIN, "note": "十万伏特：两格内最多跳跃两次，55% / 35%"},
        "ai": {"kite": True, "retreat_below_hp": None}, "value_mult": 1.0,
        "vfx": {"basic": "spark", "ult": "cheek_circuit", "gait": "tail_balance"},
    },
    94: {
        "name": "耿鬼", "role": "能量干扰",
        "range": 3, "atk_interval_mult": 1.0, "hp_mult": 1.0, "move_mult": 1.0,
        "ult": {"arch": ARCH_DRAIN, "note": "舌舔：命中偷取至多 20 能量，自身获得一半"},
        "ai": {"kite": True, "retreat_below_hp": None}, "value_mult": 1.0,
        "vfx": {"basic": "ghost_wisp", "ult": "spectral_tongue", "gait": "shadow_float"},
    },
    76: {
        "name": "隆隆岩", "role": "邻格震击控制",
        "range": 1, "atk_interval_mult": 1.0, "hp_mult": 1.0, "move_mult": 1.0,
        "ult": {"arch": ARCH_QUAKE, "note": "地震：自身邻格其他敌人 40% 伤害，命中短暂畏缩"},
        "ai": {"kite": False, "retreat_below_hp": None}, "value_mult": 1.0,
        "vfx": {"basic": "stone_hit", "ult": "fault_front", "gait": "rock_weight"},
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


def effective_range(piece) -> int:
    """Combat, positioning and equipment agree on an active range override."""
    profile = get(piece.species_id)
    return profile["range"] if profile else piece.distance
