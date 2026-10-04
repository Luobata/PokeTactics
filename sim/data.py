"""数据层：加载 data/ 下的宝可梦数据并派生战斗用查询。

设计约束（见 docs/01-constitution.md）：
- 零第三方依赖，系统 python3 可跑；
- 所有随机性不许出现在这里——数据层是纯函数，随机只发生在解算器传入的 rng 里；
- 数值公式集中在常量区，方便批量调参。
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# 金银世代的物理/特殊划分按招式属性决定（Gen2 规则，非 Gen3+ 的按招判定）
SPECIAL_TYPES = frozenset(
    {"FIRE", "WATER", "GRASS", "ELECTRIC", "PSYCHIC", "ICE", "DRAGON", "DARK"})

# ---- 数值公式常量区（骨架占位值，等 sim 平衡报告后再调）----
BASIC_POWER = 40          # 普攻威力（无属性撞击类）
STAB_BONUS = 1.5          # 本系加成（Same-Type Attack Bonus）
ENERGY_PER_ATTACK = 15    # 普攻命中回能
ENERGY_PER_HIT_TAKEN = 10  # 受击回能
ENERGY_MAX = 80
# 速度(5~150) -> 攻击间隔秒：快龙/豪力蜂类约 0.65s，铁甲蛹类约 1.1s
SPEED_TO_ATTACK_INTERVAL = lambda speed: 1.0 / (0.6 + speed / 150.0)  # noqa: E731
# R2 节奏定参（2026-10-04 用户裁定「动画速度过快→都推进」的第 3 层）：
# 普攻间隔整体 ×1.5——消融实验（experiment_pacing）证明攻速是节奏主杠杆
# （战斗中位 7.5→10.1s、首招 5.5→7.9s）。历史实验钉回 1.0 保基线。
ATTACK_INTERVAL_MULT = 1.5
MOVE_TICK = 0.5           # 移动一格的耗时（秒）
MAX_BATTLE_SECONDS = 45.0  # 超时判平（防龟缩）

# ---- 克制作用范围实验开关（默认 = 现状：普攻无属性、大招吃原始金银倍率）----
# 由 sim/experiment_effectiveness.py 切换；结论见 reports/effectiveness-*-*.md
EFF_ON_BASIC = False   # True: 普攻带攻方主属性（吃本系加成与克制）
EFF_COMPRESS = None    # None: 原始倍率；dict: 最终乘区压缩映射（0.25~4 -> 压缩值）


def basic_takes_eff() -> bool:
    return EFF_ON_BASIC


def eff_mult(raw: float) -> float:
    """按 EFF_COMPRESS 压缩最终克制乘区（金银乘区只取 0/0.25/0.5/1/2/4）。"""
    if EFF_COMPRESS is None:
        return raw
    return EFF_COMPRESS.get(raw, raw)


# ---- 近战/远程均衡实验开关（sim/experiment_melee.py 驱动）----
# 射程归属：基础射程按宝可梦（特攻种族>物攻=远程，roster.py 判定）；
# 大招施法射程按技能修正是规划项（S1/S5，约 40 个招牌招手工标定），与本组开关正交。
RANGED_INTERVAL_MULT = 1.0  # 远程攻击间隔倍率（>1=远程出手更慢）
# S1 定稿（2026-09-13，近远程实验依据）：近战突进——近战移动耗时打折
# （0.5s/格 → ~0.31s/格），补偿远程在接近期的白嫖输出；详见
# reports/melee-ranged-experiment-2026-09-13.md。
# C-sym 修订（2026-09-14 平衡 pass）：棋盘 7 列→6 列后近战少走一行，
# 怪力vs胡地锚点 +14pp 漂出 40-60 带（48.6→62.6%，csym 报告 §4-2）。
# 0.60→0.62 拉回 42.6%（n=1000）；0.60 与 0.61 之间存在事件时序量化的
# 离散悬崖（61%↔43%，无中间态），0.62 取平台中段离两侧沿均有余量。
# 见 reports/matchbalance-2026-09-14.md
MELEE_MOVE_MULT = 0.62      # 近战移动耗时倍率（<1=近战突进更快）
MELEE_RESIST = 0.0          # 近战受伤减免比例


def ranged_interval_mult() -> float:
    return RANGED_INTERVAL_MULT


def melee_move_mult() -> float:
    return MELEE_MOVE_MULT


def melee_resist() -> float:
    return MELEE_RESIST


def _load(name: str) -> dict:
    return json.loads((DATA_DIR / f"{name}.json").read_text())


class Pokedex:
    """只读数据视图：图鉴、招式、克制表。"""

    def __init__(self) -> None:
        mons = _load("pokemon")["entries"]
        self.species: Dict[int, dict] = {m["id"]: m for m in mons}
        self.moves: Dict[int, dict] = {m["id"]: m for m in _load("moves")["entries"]}
        tc = _load("typechart")
        self.types: List[str] = tc["types"]
        self._mult = tc["multipliers"]

    def multiplier(self, atk_type: str, def_types: Tuple[str, ...]) -> float:
        """攻击属性对防守方属性组合的总倍率（乘法叠加，如电打水/飞行=4x）。

        NONE 表示无属性招（诅咒类），不吃克制。
        """
        if atk_type == "NONE":
            return 1.0
        a = self.types.index(atk_type)
        prod = 1.0
        for t in def_types:
            prod *= self._mult[a][self.types.index(t)] / 100.0
        return prod

    def move_is_special(self, move: dict) -> bool:
        return move["type"] in SPECIAL_TYPES

    def bst(self, species_id: int) -> int:
        b = self.species[species_id]["base"]
        return b["hp"] + b["attack"] + b["defense"] + b["speed"] + \
            b["special_attack"] + b["special_defense"]

    # ---- 进化族工具：lineage 从当前形态回溯到基础形态（可能含金银宝宝 ID）----
    def family_of(self, species_id: int) -> List[int]:
        """同一进化族内、属于关都 151 的成员，按从低阶到高阶排序。

        分支进化（伊布族）同阶成员并存，因此阶段不能按列表下标算，
        要用 stage_of 的血缘深度归一化。
        """
        head = self.species[species_id]["lineage"][-1]  # 族内最基础形态
        members = [sid for sid, m in self.species.items() if m["lineage"][-1] == head]
        return sorted(members, key=lambda sid: len(self.species[sid]["lineage"]))

    def stage_of(self, species_id: int) -> int:
        """在关都 151 可见范围内的进化阶段（1=基础形态）。

        以族内最浅血缘深度为基准归一化，容忍金银宝宝形态占一层
        （皮卡丘 [25,172] 与雷丘 [26,25,172] -> 阶段 1、2）。
        """
        family = self.family_of(species_id)
        depth = min(len(self.species[sid]["lineage"]) for sid in family)
        return len(self.species[species_id]["lineage"]) - depth + 1

    def next_evolution(self, species_id: int) -> Optional[int]:
        fam = self.family_of(species_id)
        i = fam.index(species_id)
        return fam[i + 1] if i + 1 < len(fam) else None

    def signature_move(self, species_id: int) -> Optional[dict]:
        """选招式：升级学会的本系招中威力最高且命>=80 的；否则任意威力招。"""
        learn = self.species[species_id].get("level_up", [])
        types = set(self.species[species_id]["types"])
        damaging = [self.moves[mid] for _, mid in learn
                    if mid in self.moves and self.moves[mid].get("power")]
        stab = [m for m in damaging if m["type"] in types and (m.get("accuracy") or 0) >= 80]
        pool = stab or damaging
        return max(pool, key=lambda m: m["power"]) if pool else None


_DATA: Optional[Pokedex] = None


def pokedex() -> Pokedex:
    global _DATA
    if _DATA is None:
        _DATA = Pokedex()
    return _DATA
