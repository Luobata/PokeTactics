"""棋子池：从进化族自动生成自走棋棋子。

S2 定稿（2026-09-13）：**档位按「形态自身种族值总和（BST）」定价**，
不再按进化阶段，也不再给无进化者开单独阈值（详见
docs/systems/S2-evolution-starup.md）。理由：
- 等级已全档拍平（S1），强度只来自种族值差——「档位=进化阶段」会造成
  阶段≠强度的双向错位：三段线终点大针蜂(385)被定 3 费，两段线终点
  风速狗(555)却只定 2 费；两段线终点中位 485 与三段线终点中位 495
  大量重叠甚至倒挂；
- 定价跟着强度走后，「同费=同强度」成为可验收命题（档内 BST 极差
  从 190/350/215 收敛到 155/130/100）。

保持不变：
- 等级 `LEVEL_BY_TIER` 维持 S1 拍平值（全档 45 级），档位只管价格/出现率；
- 招式 = 升级表中本系最高威力招（data.signature_move）；
- 攻击距离：特攻高=远程（3 格），物攻高=近战（1 格）。

接口保持：`build_roster() -> dict[tier, list[Piece]]` 与 `random_comp(rng, size)`。
"""

import random
from data import Pokedex, pokedex

# 手选的初始棋子族（基础形态图鉴号）。目标：覆盖多数属性、含著名三段线。
CURATED_FAMILIES = [
    1, 4, 7,            # 御三家
    10, 13, 16, 21, 19,  # 虫/鸟/鼠早期线
    25, 29, 32, 37, 41, 43,
    54, 56, 58, 60, 63, 66, 69, 74,
    79, 81, 92, 95, 111, 116, 120, 123,
    129, 131, 133, 143, 147,
]

# S1 定稿（2026-09-13，克制实验依据）：等级拍平——进化强度只来自种族值跳变，
# 档位只管价格/出现率。原 30/40/50 会造成「档位双重计费」（详见
# reports/effectiveness-experiment-2026-09-13.md）。
LEVEL_BY_TIER = {1: 45, 2: 45, 3: 45}

# S2 定稿（2026-09-13）：档位 = 形态自身 BST 分档。阈值取自 84 只池 BST 分布的
# 自然断点（推导与读数见 docs/systems/S2-evolution-starup.md §2、
# reports/s2-tiering-2026-09-13.md）：
# - T1 上界 365（不含）：350→365 是池中部最大断点之一（卡蒂狗 350 → 尼多娜 365，
#   gap=15），365 以下恰好全是基础形态/虫茧/准基础盘（比比鸟 349），共 34 只；
# - T2 上界 500（不含）：465~505 是终形态密集带（480/485/490/495/500/505 共
#   14 只），没有可用的空档，取「500 俱乐部」文化锚点划精英线——BST≥500 才有
#   明显种族值压制；之上 18 只，与旧 3 费池 19 只规模接近，商店结构冲击最小；
# - 4/5 费档位留给扩池（化石翼龙/快龙/三神鸟/超梦等传说位，见头脑风暴 §5）；
#   届时快龙(600)等将上移，阈值随新池分布重标定。
TIER_BY_BST = ((365, 1), (500, 2))   # (BST 上界[不含], 档位)；都不满足 = 3 费

# 新档位分布（84 只）：1费 34（BST 195~350）/ 2费 32（365~495）/ 3费 18（500~600）。
# 旧档位（按进化阶段）：32/33/19，各档 BST 极差 190/350/215；新档位 155/130/100，
# 三档均单调改善（sim/experiment_tiering.py 可复现）。

RANGED = 3                               # 特攻手射程
MELEE = 1


class Piece:
    def __init__(self, species_id: int, tier: int, level: int,
                 move_id=None, distance: int = MELEE) -> None:
        dex: Pokedex = pokedex()
        self.species_id = species_id
        self.name = dex.species_record(species_id)["name_zh"]
        self.types = tuple(dex.species_record(species_id)["types"])
        self.tier = tier
        self.level = level
        self.move_id = move_id
        self.distance = distance

    def __repr__(self) -> str:
        return f"{self.name}(T{self.tier})"


def tier_for_bst(bst: int) -> int:
    """形态自身 BST → 商店档位。S2 统一规则：进化族成员与成品棋同一条公式。"""
    for upper, tier in TIER_BY_BST:
        if bst < upper:
            return tier
    return 3


def build_roster() -> dict:
    """返回 {tier: [Piece, ...]}：84 只（1费 34 / 2费 32 / 3费 18）。"""
    dex = pokedex()
    roster: dict = {1: [], 2: [], 3: []}
    seen = set()
    for head in CURATED_FAMILIES:
        for sid in sorted(dex.family_of(head),
                          key=lambda sid: (len(dex.species[sid]["lineage"]), sid)):
            if sid in seen:
                continue
            seen.add(sid)
            tier = tier_for_bst(dex.bst(sid))   # S2：按形态自身 BST 定档
            level = LEVEL_BY_TIER[tier]
            base = dex.species[sid]["base"]
            distance = RANGED if base["special_attack"] > base["attack"] else MELEE
            move = dex.signature_move(sid)
            roster[tier].append(Piece(sid, tier, level,
                                      move_id=move and move["id"],
                                      distance=distance))
    return roster


def random_comp(rng: random.Random, size: int,
                tier_weights=(0.62, 0.28, 0.10)) -> list:
    """按档位权重抽一套阵容（骨架用；真实商店池见 docs/systems 的商店文档）。"""
    roster = build_roster()
    tiers = list(roster)
    weights = [tier_weights[min(t - 1, len(tier_weights) - 1)] for t in tiers]
    comp = []
    for _ in range(size):
        tier = rng.choices(tiers, weights=weights)[0]
        comp.append(rng.choice(roster[tier]))
    return comp
