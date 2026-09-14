"""天气/场地系统（S11，docs/05-weather.md）——数值臂模块。

接线（combat.py 已预埋，本模块只被调用、不反向修改战斗核）：
- Battle(weather_name=...) 设置本场天气；None = 无天气（默认）。
- _final_damage 开头调 weather.damage_mult(move)：带属性招式（大招）吃天气乘区，
  普攻无属性不受影响（与「克制只上大招」同一条裁定线）。

数值表定稿（2026-09-13 数值臂，reports/weather-experiment-2026-09-13.md）：
- 晴/雨 ±20%（晴还含草 +20%）、沙暴岩/地/钢 +15%、冰雹冰 +25%——维持
  docs/05 §2 骨架未调。依据：1000 场随机臂中任一属性胜率未越 65% 健康线
  （带宽 14.8%→15.3%，胜者翻转率 ≤0.8%，属性位移 ≤0.7pp=噪音级）；干净
  2x 对位（水箭龟×6 vs 喷火龙×6）62.0% → 晴 41.5% / 雨 68.5%，±13.5pp
  摆幅落在 8~20pp 有效区间。即 ±20% 是「倾斜」而非「翻转」：能驱动已成型
  阵容的对位位移，但不翻越纯属性队间的克制差（火系队 vs 水系队晴天下仍
  0%），与「天气是规划信号不是抽卡」的设计意图一致。
- 本阶段边界：沙暴/冰雹的**全局掉血**（非对应属性单位 -0.8%/2s maxHP，
  docs/05 §2 表第 4 列）未实现——它需要战斗主循环的 tick 钩子（与 S12
  状态系统的 DOT 同一通道），且涉及事件流新增，留待状态系统联动时一并做。
  当前模块只覆盖伤害乘区，故沙暴/冰雹臂读数 = 纯增益臂（无掉血压力项）。

约束：零随机、零事件流新增（v1 数值臂阶段）；乘区独立于克制/本系链，便于分臂归因。
"""

# 天气定义表（数值骨架来自 docs/05 §2；倍率逐天气独立，便于单独标定）
WEATHERS = {
    None:   {"label": "无"},
    "sun":  {"label": "晴", "boost": ("FIRE", "GRASS"), "boost_mult": 1.20,
             "cut": ("WATER",), "cut_mult": 0.80},
    "rain": {"label": "雨", "boost": ("WATER",), "boost_mult": 1.20,
             "cut": ("FIRE",), "cut_mult": 0.80},
    "sand": {"label": "沙暴", "boost": ("ROCK", "GROUND", "STEEL"),
             "boost_mult": 1.15},
    "hail": {"label": "冰雹", "boost": ("ICE",), "boost_mult": 1.25},
}

BOOST_MULT = 1.20   # 兜底增益幅度（表内未显式指定 boost_mult 时使用）
CUT_MULT = 0.80     # 兜底减益幅度（表内未显式指定 cut_mult 时使用）
ACTIVE = None       # 当前天气（进程级；实验按臂设置，验收后台在锁内渲染）


def set_active(name) -> None:
    global ACTIVE
    assert name in WEATHERS, f"未知天气: {name}"
    ACTIVE = name


def active():
    return ACTIVE


_UNSET = object()      # 「未传参」哨兵：与合法值 None（无天气）区分


def damage_mult(move, active=_UNSET) -> float:
    """天气对单次伤害的乘区。move=None（无属性普攻）恒为 1.0。

    active 显式传本场天气（combat.Battle 的调用方式）。2026-09-14 修订：
    进程级 ACTIVE 在验收后台多线程下会交叉污染（/anim 渲染与 /demo
    战斗并行时两把锁互不知情），战斗解算一律按 Battle 实例传参；
    不传 active 则回落进程级 ACTIVE（experiment_* 单线程臂的兼容路径）。

    只看招式属性、不看攻方属性（与克制判定同源）——草系放阳光烈焰在晴天
    加成、水系放水炮在雨天加成，判定线唯一。
    """
    name = ACTIVE if active is _UNSET else active
    if move is None or name is None:
        return 1.0
    w = WEATHERS[name]
    mtype = move.get("type")
    if mtype in w.get("boost", ()):
        return w.get("boost_mult", BOOST_MULT)
    if mtype in w.get("cut", ()):
        return w.get("cut_mult", CUT_MULT)
    return 1.0
