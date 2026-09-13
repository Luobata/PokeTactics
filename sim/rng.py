"""S7 RNG 分层派生：master_seed → 轮种子 → 用途子流（docs/09 §2.2）。

存档系统（docs/09）的前置依赖：把「一条 Random 流贯穿全局」改成
「按（轮 × 用途 × counter）现派生的独立子流」。轮边界快照因此完全
不需要保存 RNG 游标——恢复 = 用 (master_seed, round_no, refresh_count)
现派生当轮全部子流，历史轮已经结算进快照（docs/09 §2.2）。

派生实现（S7 定稿，取代 docs/09 §2.2 里 mix32 的示意写法）：

    seed_child = sha256( K_<purpose> ‖ master_seed ‖ round_no ‖ counter )
    子流 = random.Random(seed_child 的前 8 字节，u64 整数种子)

- 字段各占定长 4 字节小端拼接，无分隔符歧义；purpose 以编译期盐
  K_PERS / K_SHOP / K_BOTS / K_PAIR / K_BAT / K_PVE 参与（即 docs/09
  §2.2 的 K_* 常量落定）；
- 取前 8 字节（u64）做种子：一局约 1.6k 条子流，u64 下生日碰撞概率
  ~10^-10；只取 u32 则约 0.03%/局——不冒这个险。C 移植用任一 SHA-256
  实现（ESP-IDF mbedTLS 自带），取同样 8 字节初始化 64 位状态 PRNG；
  协议只锁「同字节流 → 同子流种子」这一步，PRNG 本体随端；
- 随机方法本体仍是标准库 random.Random（整数种子跨版本、跨平台、
  跨 PYTHONHASHSEED 稳定）。

counter 表（同一轮内多次消费的递增游标；消费点见 sim/match.py）：

    用途    counter                          说明
    pers    round_no=0，恒 0                 开局一次：人格/能力发牌
    shop    seat×256 + j                     j=0 免费滚；j≥1 = 第 j 次手动
                                            刷新——与存档 1B refresh_count
                                            游标对齐（docs/09 §1.1），M5
                                            人类席直读档现派生。bot 的手动
                                            刷新属 decide 阶段消费、不跨
                                            写点，走 bots 子流（docs/09
                                            §2.2），j≥1 由玩家席启用
    bots    seat                             各席决策独立子流（L0 买入/卖出/
                                            摆位随机 + bot 刷新的商店抽取）
    pair    恒 0                             每轮一条：≤20 次配对尝试 + 幽灵
                                            源选择顺序消费；配对完整发生在
                                            写点 A（开战提交）之后，无游标
                                            需求
    battle  i                                该轮第 i 场战斗（0 起：PVP 按对
                                            序、幽灵战殿后；PVE 轮 = 各家野
                                            怪战）——单场可独立回放
    pve     i                                野怪轮第 i 个存活者的掉金（2-3）

子流互相独立：任何一处消费次数变化不会移动其他用途的随机数序列
（对比旧单流：商店多抽一次，后面的战斗骰全部位移）——这正是存档、
恢复与单场回放需要的性质。棋盘/战斗层（combat.Battle）不改：仍然
只吃调用方传入的 rng，本模块在 match 层负责把对的手流递过去。
"""

import hashlib
import random

# 用途 → 编译期盐（docs/09 §2.2 的 K_* 常量；pers 为开局发牌流）
PURPOSE_SALTS = {
    "pers": b"K_PERS",
    "shop": b"K_SHOP",
    "bots": b"K_BOTS",
    "pair": b"K_PAIR",
    "battle": b"K_BAT",
    "pve": b"K_PVE",
}

# 商店子流 counter 打包步长：counter = seat × 256 + refresh_count。
# 256 = 存档 refresh_count 的 u8 游标宽度（docs/09 §1.1）：免费滚 j=0，
# 手动刷新 j=1..——恢复时直读档里的 (seat, refresh_count) 现派生。
SHOP_STRIDE = 256


def shop_counter(seat: int, refresh_count: int = 0) -> int:
    """打包商店子流 counter：高段席位 × 256 + 低段刷新序号。"""
    return seat * SHOP_STRIDE + refresh_count


def derive(master_seed: int, round_no: int, purpose: str,
           counter: int = 0) -> random.Random:
    """从 (master_seed, round_no, purpose, counter) 派生一条独立子流。

    纯函数：同参数必得同子流（跨进程、跨 PYTHONHASHSEED 稳定）；
    不同参数的碰撞概率可忽略（sha256 截 8 字节，见模块 docstring）。
    """
    if purpose not in PURPOSE_SALTS:
        raise ValueError(f"未知用途 {purpose!r}，可选 {sorted(PURPOSE_SALTS)}")
    h = hashlib.sha256(PURPOSE_SALTS[purpose])
    h.update((master_seed & 0xFFFFFFFF).to_bytes(4, "little"))
    h.update((round_no & 0xFFFFFFFF).to_bytes(4, "little"))
    h.update((counter & 0xFFFFFFFF).to_bytes(4, "little"))
    return random.Random(int.from_bytes(h.digest()[:8], "little"))


if __name__ == "__main__":   # 自检：同参同流、异参异流、盐不串味
    a, b = derive(7, 3, "battle", 2), derive(7, 3, "battle", 2)
    assert [a.random() for _ in range(5)] == [b.random() for _ in range(5)]
    assert derive(7, 3, "battle", 2).random() != derive(7, 3, "battle", 3).random()
    assert derive(7, 3, "battle").random() != derive(7, 3, "pve").random()
    assert shop_counter(2, 0) == 512 and shop_counter(2, 3) == 515
    print("rng.derive 自检通过：同参同流 / 异参异流 / 用途盐隔离")
