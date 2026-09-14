"""M2 商店层：共享卡池 + 按等级概率滚动 + 买/卖/刷新 + 3 合 1 自动进化。

设计依据（docs/00-brainstorm §5、docs/systems/S2）：
- 商店 5 格；每格独立按「等级 → 档位概率表」定档，再从共享池该档
  仍有存量的物种中均匀抽一只；
- 共享卡池按档位限量：1费 22 / 2费 18 / 3费 12（84 只池 → 全局 1540 只），
  8 人共享，定向买棋会真实卡别人牌（docs/03 §5 滚雪球抑制）；
- 每轮开始免费重滚一次；主动刷新 2 金（economy.REFRESH_COST）；
- 卖出价 = 累计投入 - 1（1 费保底全价，TFT 同款）；
- 3 合 1 自动进化（S2 §1）：备战/场上凑齐 3 只同图鉴号 → 下一进化形态，
  sources 记账（基础 3 只 + 进化形态各占 1 张池），卖出时全部归还；
- 通信进化（勇基拉/豪力/鬼斯通）需装备（S2 §1.5），M2 无装备 → 暂缓合成；
  分支进化（伊布）本版走 next_evolution 确定性取水伊布（真三选一归 S9 UI）。

随机只走调用方传入的 rng（宪法 2.2）。零 IO。
"""

import random
from typing import Dict, List, Optional

from data import pokedex
import items as items_mod   # S5 装备：通信进化持装备门（items_on 时生效）
from roster import (LEVEL_BY_TIER, RANGED, MELEE, Piece, build_roster,
                    tier_for_bst)

SHOP_SLOTS = 5

# 共享卡池：每只（按物种）在池中的张数（任务书骨架值，1费22/2费18/3费12）
POOL_COPIES: Dict[int, int] = {1: 22, 2: 18, 3: 12}

# 等级 → (1费%, 2费%, 3费%) 概率表（TFT 式三档表，等级 1-7）
# 口径：L1-2 纯 1 贲；3 费（500+ BST 终形态）从 L4 起可见、L7 到 25%
LEVEL_ODDS: Dict[int, tuple] = {
    1: (100, 0, 0),
    2: (100, 0, 0),
    3: (75, 25, 0),
    4: (60, 35, 5),
    5: (50, 40, 10),
    6: (40, 45, 15),
    7: (30, 45, 25),
}

# 通信进化族（勇基拉→胡地、豪力→怪力、鬼斯通→耿鬼）：需持有装备（S2 §1.5，
# 装备 S5 接线前暂缓合成——M2 边界，见报告）
TRADE_EVOLUTIONS = frozenset({64, 67, 93})


def build_templates() -> Dict[int, Piece]:
    """species_id → Piece 模板（84 只池全量，含各进化形态）。"""
    templates: Dict[int, Piece] = {}
    for pieces in build_roster().values():
        for p in pieces:
            templates[p.species_id] = p
    return templates


def make_piece(species_id: int, templates: Dict[int, Piece]) -> Piece:
    """按图鉴号取模板；不在池中的物种（PVE 野怪等）现场按 BST 定档构造。"""
    if species_id in templates:
        return templates[species_id]
    dex = pokedex()
    base = dex.species[species_id]["base"]
    tier = tier_for_bst(dex.bst(species_id))
    move = dex.signature_move(species_id)
    return Piece(species_id, tier, LEVEL_BY_TIER[tier],
                 move_id=move and move["id"],
                 distance=RANGED if base["special_attack"] > base["attack"] else MELEE)


class SharedPool:
    """全桌共享卡池：species_id → 剩余张数。"""

    def __init__(self, templates: Dict[int, Piece]) -> None:
        self.templates = templates
        self.remaining: Dict[int, int] = {}
        for sid, piece in templates.items():
            self.remaining[sid] = POOL_COPIES[piece.tier]

    def take(self, species_id: int) -> None:
        assert self.remaining.get(species_id, 0) > 0, f"池空: {species_id}"
        self.remaining[species_id] -= 1

    def put(self, species_id: int) -> None:
        if species_id in self.remaining:
            self.remaining[species_id] += 1


class OwnedPiece:
    """一名玩家拥有的一只棋子：模板 + 经济记账（买入投入、池占用溯源）。

    invested：买入这只棋子累计花的金币（3 合 1 后 = 三只之和）；
    sources：这只棋子在共享池里占用的物种张数（买入=自身；合成=3 基础+新形态），
    卖出/淘汰时全部归还池子。
    """

    def __init__(self, piece: Piece, invested: int) -> None:
        self.piece = piece
        self.invested = invested
        self.sources = [piece.species_id]
        self.item = None   # S5 装备栏：每单位 1 格（None = 空手，docs/07 §3）

    def __repr__(self) -> str:
        return f"{self.piece.name}(T{self.piece.tier},投{self.invested})"


def sell_value(owned: OwnedPiece) -> int:
    """卖出价 = 累计投入 - 1，1 费保底全价（TFT 同款，防卖棋套利）。"""
    return max(owned.invested - 1, 1)


def draw_slot(rng: random.Random, level: int, pool: SharedPool,
              templates: Dict[int, Piece]) -> Optional[int]:
    """抽一格商店：先按等级定档，再在该档有存量的物种中均匀抽。

    抽中即从共享池**预留**一张（同一批 5 格可能抽到同种——各自占一张），
    买家买入时不再扣池；该档全空时逐档下潜（极端情况：终局 3 费被买光）。
    """
    odds = LEVEL_ODDS[min(max(level, 1), max(LEVEL_ODDS))]
    tier = rng.choices((1, 2, 3), weights=odds)[0]
    for t in (tier, tier - 1, tier + 1, 1, 2, 3):  # 优先原档，缺货时补位
        if t not in POOL_COPIES:
            continue
        avail = [sid for sid, piece in templates.items()
                 if piece.tier == t and pool.remaining.get(sid, 0) > 0]
        if avail:
            sid = rng.choice(sorted(avail))
            pool.take(sid)
            return sid
    return None  # 全池枯竭（8 人局理论不可达，保底返回 None）


class Shop:
    """一名玩家的商店：5 格，roll 从共享池抽，买走即出池，刷新归还重抽。"""

    def __init__(self, pool: SharedPool, templates: Dict[int, Piece]) -> None:
        self.pool = pool
        self.templates = templates
        self.slots: List[Optional[int]] = [None] * SHOP_SLOTS

    def roll(self, rng: random.Random, level: int) -> None:
        """重滚全部格子（未买的先归还池子）。"""
        for sid in self.slots:
            if sid is not None:
                self.pool.put(sid)
        self.slots = [draw_slot(rng, level, self.pool, self.templates)
                      for _ in range(SHOP_SLOTS)]

    def buy(self, slot: int) -> OwnedPiece:
        """买走一格（池张数在抽取时已预留，此处只清格；扣钱由 bot 负责）。"""
        sid = self.slots[slot]
        assert sid is not None
        self.slots[slot] = None
        piece = make_piece(sid, self.templates)
        return OwnedPiece(piece, invested=piece.tier)

    def price(self, slot: int) -> int:
        sid = self.slots[slot]
        return self.templates[sid].tier if sid is not None else 0

    def return_all(self) -> None:
        """淘汰/局终：未买的格子归还池子。"""
        for sid in self.slots:
            if sid is not None:
                self.pool.put(sid)
        self.slots = [None] * SHOP_SLOTS


def sell_owned(owned: OwnedPiece, pool: SharedPool) -> int:
    """卖出：归还 sources 张数进池，返回卖价。"""
    for sid in owned.sources:
        pool.put(sid)
    return sell_value(owned)


def try_combine(board: List[OwnedPiece], bench: List[OwnedPiece],
                pool: SharedPool, templates: Dict[int, Piece],
                inventory=None) -> List[str]:
    """3 合 1 自动进化（S2 §1）：凑齐 3 只同图鉴号立即合成下一形态。

    在 board+bench 上反复扫描直到无可合成；合成品优先落 bench（备战），
    池中无进化形态存量时保持原状等待（S2 §1.4）。S5 装备条款（S2 §1.5）：
    通信进化族（勇基拉/豪力/鬼斯通）的 3 合 1 要求选中三只中至少一只
    **持有任意装备**——装备随棋子进入新形态（不消耗）；选中三只里多余
    的持装备者卸回 inventory（每单位 1 格）。items 关闭时维持旧门（暂缓）。
    返回日志（无进化则空表）。
    """
    dex = pokedex()
    logs: List[str] = []
    merged = True
    while merged:
        merged = False
        all_pieces = list(board) + list(bench)
        groups: Dict[int, List[OwnedPiece]] = {}
        for owned in all_pieces:
            groups.setdefault(owned.piece.species_id, []).append(owned)
        for sid in sorted(groups):  # 排序保证确定性（宪法 2.2）
            group = groups[sid]
            if len(group) < 3:
                continue
            nxt = dex.next_evolution(sid)
            if nxt is None:
                continue                       # 终形态不再合成（S2 §1.7）
            three = group[:3]                  # board 在前、bench 在后，确定性
            if sid in TRADE_EVOLUTIONS:
                holders = [o for o in group if o.item is not None]
                if not (items_mod.items_on() and holders):
                    continue                   # 通信进化需持装备（S5 前暂缓）
                # 优先让持装备者入选（否则被前两只无装备者占坑卡死合成）
                three = [holders[0]] + [o for o in group
                                       if o is not holders[0]][:2]
            if pool.remaining.get(nxt, 0) <= 0:
                continue                       # 池中无该形态，等待
            pool.take(nxt)
            new_piece = make_piece(nxt, templates)
            merged_owned = OwnedPiece(new_piece,
                                      invested=sum(o.invested for o in three))
            merged_owned.sources = sum((o.sources for o in three), []) + [nxt]
            # 装备继承（S2 §1.2）：首个持装备者的装备随棋子进入新形态；
            # 其余持装备者卸回仓库（每单位 1 格，不吞装备）
            for o in three:
                if o.item is not None and merged_owned.item is None:
                    merged_owned.item = o.item
                elif o.item is not None and inventory is not None:
                    inventory.finished.append(o.item)
                o.item = None
            for o in three:  # 三只的池占用已并入 merged_owned.sources 记账
                (board if o in board else bench).remove(o)
            bench.append(merged_owned)
            logs.append(f"3合1:{new_piece.name}(T{new_piece.tier})")
            merged = True
            break
    return logs
