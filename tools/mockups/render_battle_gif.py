#!/usr/bin/env python3
"""把 sim 的真实战斗事件流渲染成动画 GIF + 关键帧分镜图（v3 游标回放版）。

v3 修正（v2 遗留的真 bug）：
1. 游标式回放：事件按帧时间递进应用，帧渲染只见到「已发生」的事件——
   v2 把整场事件先应用完再渲染，导致未来阵亡的单位在早期帧被画成
   白色剪影（负 age 落进死亡闪白分支）、血条/位置显示终局值；
2. 棋盘按 sim 真实规格渲染（v3 曾为 7×6@34px）；2026-09-14 起 C-sym
   （docs/10 §1.5）：6 列 × 6 视觉行 = 敌备战 1 + 战场 2+2 + 我备战 1，
   sim 的战斗行 0-3 映射视觉行 1-4，备战行画观战格、不落战斗单位；
3. 死亡/击退/攻击动画全部加 `0 <=` 时间下界。

视觉层与静态稿共用三色地砖、米色窗框、底座与红 HP 条。棋盘精灵
用 BOX + 物种四原色量化缩入 32/34px，特写保留原尺寸，保留前后遮挡；精灵
命中以整只闪白、双色爆点和轨迹强调。事件游标、回放状态、时长与
固定调色板量化均不变。

    python3 tools/mockups/render_battle_gif.py [--seed 7]
"""

import argparse
import copy
import math
import random
import sys
from collections import Counter
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "sim"))
from decoders import Front, Font16, Palettes  # noqa: E402
from render_mockups import (  # noqa: E402
    H, W, CELL, BOARD_X, BOARD_Y, BOARD_FOOT, INK, PAPER, FRAME, NIGHT, ENERGY, HP_RED, HP_LOW,
    TYPE_COLORS, TIER_COLORS, GRASS_A, GRASS_B, SAND_A, SAND_B,
    GRASS_LINE, SAND_LINE, SPOT,
    arena_dot, draw_hud, draw_small_number, draw_text, draw_pixel_text,
    draw_floor_tile, draw_divider, draw_base, draw_meter, draw_spark,
    pixel_window, draw_message_window, draw_cutin_stage, draw_cutin_sprites,
    draw_nameplate, draw_effect_badge, text_width, wrap_text,
    board_sprite_size, scale_sprite, scale_compare_image,
)
from profile_vfx import SIGNATURES, PlaybackClock, gait_profile, pose_sprite
from skill_vfx import skill_profile, cast_windup, draw_skill
from pixel_vfx import (trajectory_point, projectile, impact_star, impact_rim,
                       light, debris, hit_sprite, feather_flash, number_rise, exposure_age)
from combat import Battle  # noqa: E402
from data import pokedex  # noqa: E402
from roster import build_roster  # noqa: E402

FPS_DT = 0.1
MOVE_SMOOTH = 0.22
FLOAT_LIFE = 0.8
CAST_WINDUP = 0.35
CUTIN_LEN = 1.0
ATTACK_ANIM = 0.30
DUST_LIFE = 0.35
HIT_DELAY = FPS_DT
HIT_LIFE = 3 * FPS_DT
PARTICLE_LIMIT = 192
OPENING_LIFE = 4 * FPS_DT
FULL_GOLD = (255, 208, 64)
SCAR_FRAMES = 8

# GIF 棋盘 = C-sym 布局（docs/10 §1.1/§1.5）：6 列 × 6 视觉行 × 40px（240px 满宽）。
# 视觉行分区：0 敌备战行（虚线观战格）/ 1-2 敌方战场（沙色）/ 3-4 己方战场
# （草绿）/ 5 我备战行（虚线观战格）。sim 战斗网格只有 4 行（combat.ROWS=4），
# 战斗行 r 经 VIS_ROW_OFF 映射到视觉行 r+1；备战行不落战斗单位（不参战）。
BCOLS, BROWS, BCELL = 6, 6, CELL
VIS_ROW_OFF = 1                    # 战斗行 0-3 → 视觉行 1-4
ENEMY_ROWS, ALLY_ROWS = (1, 2), (3, 4)   # 视觉行的战场分区
BENCH_ROWS = (0, 5)                # 视觉行的双备战行
BX, BY = BOARD_X, BOARD_Y

GRASS = (GRASS_A, GRASS_B)
SAND = (SAND_A, SAND_B)

# 每个天气只替换有限色板：草地 / 沙地各三色，观战格单独一色。
# 雨色板以原亮度约 0.85 蓝化，晴色板以约 1.1 暖黄化后手工定色。
FLOOR_COLORS = (GRASS_A, GRASS_B, GRASS_LINE, SAND_A, SAND_B, SAND_LINE, SPOT)
WEATHER_PALETTES = {
    "rain": ((130, 150, 165), (120, 140, 155), (96, 118, 136),
             (159, 165, 177), (149, 155, 167), (128, 135, 150), (49, 61, 77)),
    "sun": ((191, 197, 145), (181, 187, 133), (155, 161, 110),
            (224, 210, 153), (214, 198, 141), (193, 176, 121), (78, 73, 54)),
    "sand": ((181, 170, 120), (169, 158, 108), (146, 133, 89),
             (206, 177, 120), (194, 165, 108), (172, 143, 89), (79, 66, 46)),
    "hail": ((195, 210, 209), (182, 198, 198), (157, 179, 181),
             (216, 221, 222), (204, 210, 212), (179, 189, 195), (75, 89, 100)),
}
WEATHER_MESSAGES = {"rain": "下雨了！", "sun": "阳光强烈！",
                    "sand": "沙暴肆虐了！", "hail": "开始下冰雹了！"}
# 现有 FNT1 子集缺这四字；补充固定 16px 单色字模，无系统字体运行依赖。
WEATHER_GLYPHS = {
    "肆": (0x0000, 0x0000, 0x2260, 0x3f68, 0x31fc, 0x3e6e, 0x33ff, 0x366c,
           0x31fc, 0x336c, 0x7ffe, 0x3c66, 0x27ff, 0x7f60, 0x7260, 0x0060),
    "虐": (0x0000, 0x0000, 0x0380, 0x03fc, 0x2384, 0x3ffe, 0x33be, 0x33fc,
           0x3bcc, 0x31fc, 0x3018, 0x37fc, 0x3606, 0x3ffe, 0x6608, 0x47fc),
    "雨": (0x0000, 0x0000, 0x0006, 0x7fff, 0x0180, 0x0188, 0x3ffc, 0x35ec,
           0x37bc, 0x37bc, 0x318c, 0x37bc, 0x37bc, 0x318c, 0x31bc, 0x311c),
    "雹": (0x0000, 0x0000, 0x0018, 0x1ff8, 0x3ffe, 0x618e, 0x6180, 0x1df0,
           0x1d10, 0x1ffc, 0x3fd8, 0x38d8, 0x5fd8, 0x18ba, 0x1816, 0x1ffe),
}
WEATHER_ICONS = {
    "rain": (("0110", "1111", "0000", "1010"), (104, 139, 163)),
    "sun": (("1001", "0110", "0110", "1001"), (193, 139, 43)),
    "sand": (("0111", "1100", "0011", "1110"), (163, 139, 99)),
    "hail": (("0110", "1111", "0110", "1001"), (146, 174, 171)),
}
STATUS_ORANGE, STATUS_PURPLE = (240, 144, 56), (184, 112, 200)
STATUS_BLUE, STATUS_GREEN = (112, 176, 232), (120, 208, 136)
# 6px 图标槽内绘制离散点阵；睡眠字形为严格的 2×3px。
STATUS_ICONS = {
    "burn": (("0010", "0110", "1111", "0110"), STATUS_ORANGE),
    "poison": (("1111", "1001", "1111", "0110"), STATUS_PURPLE),
    "paralysis": (("0011", "0110", "1100", "0110"), FULL_GOLD),
    "freeze": (("1010", "0111", "1110", "0101"), (255, 255, 255)),
    "sleep": (("11", "01", "11"), STATUS_BLUE),
    "lightscreen": (("1111", "1001", "1001", "1111"), STATUS_BLUE),
    "reflect": (("1111", "1011", "1101", "1111"), (146, 174, 171)),
    "sworddance": (("0010", "0111", "1110", "1000"), FULL_GOLD),
    "flinch": (("0100", "1110", "0101", "0010"), PAPER),
}
BUFF_KINDS = ("lightscreen", "reflect", "sworddance")
DOT_COLORS = {"burn": STATUS_GREEN, "poison": STATUS_PURPLE}


def draw_pixel_icon(img, xy, rows, color):
    draw = ImageDraw.Draw(img)
    for y, row in enumerate(rows):
        for x, bit in enumerate(row):
            if bit == "1":
                draw.point((xy[0] + x, xy[1] + y), fill=color)


def draw_weather_text(img, xy, text, font):
    draw_text(img, xy, text, font, INK)
    draw = ImageDraw.Draw(img)
    offset = 0
    for ch in text:
        if ch in WEATHER_GLYPHS and not font.text(ch).getbbox():
            for y, row in enumerate(WEATHER_GLYPHS[ch]):
                for x in range(16):
                    if row & (1 << (15 - x)):
                        draw.point((xy[0] + offset + x, xy[1] + y), fill=INK)
        offset += text_width(ch)


@lru_cache(maxsize=5)
def board_floor(weather_name):
    """只缓存地砖；按色板查表替换，不乘整幅图，也不染精灵/UI。"""
    floor = Image.new("RGBA", (BCOLS * BCELL, BROWS * BCELL))
    for cy in range(BROWS):
        for cx in range(BCOLS):
            draw_floor_tile(floor, cx * BCELL, cy * BCELL, BCELL, cx, cy,
                            enemy=cy in ENEMY_ROWS, bench=cy in BENCH_ROWS)
    if weather_name in WEATHER_PALETTES:
        replacements = {src + (255,): dst + (255,) for src, dst in
                        zip(FLOOR_COLORS, WEATHER_PALETTES[weather_name])}
        floor.putdata([replacements.get(pixel, pixel) for pixel in floor.getdata()])
    return floor


def weather_particles(weather_name, T):
    """八粒上限；位置仅由帧号和序号决定，回卷、随机种子均不影响相位。"""
    frame = effect_frame(T)
    width, height = BCOLS * BCELL, BROWS * BCELL
    particles = []
    for i in range(8 if weather_name in WEATHER_PALETTES else 0):
        if weather_name == "rain":
            x, y = 27 + (i % 3) * 80, (i * 31 + frame * 9) % (height - 3)
            w, h, color = 1, 4, (184, 216, 232)
        elif weather_name == "sun":
            x, y = (i * 31 + frame // 3) % (width - 1), (i * 47 + frame // 5) % (height - 1)
            w, h, color = 2, 2, (248, 232, 168)
        elif weather_name == "sand":
            x, y = (i * 31 + frame * 7) % (width - 1), (i * 43 + frame // 4) % height
            w, h, color = 2, 1, (232, 192, 120)
        else:
            x, y = (i * 31 + frame // 2) % (width - 1), (i * 43 + frame * 17) % (height - 1)
            w, h, color = 2, 2, (248, 248, 255)
        particles.append((BX + x, BY + y, w, h, color))
    return particles

# 每种招式共享纸色高光 + 属性色，不产生逐帧渐变色或额外抖动色。
FX_STYLE = {
    kind: (style, [PAPER, TYPE_COLORS[kind]])
    for kind, style in {
        "ELECTRIC": "bolt", "FIRE": "travel", "WATER": "arc", "GRASS": "orbit",
        "BUG": "orbit", "PSYCHIC": "rings", "GHOST": "wisps", "POISON": "wisps",
        "DARK": "wisps", "ICE": "shards", "FIGHTING": "debris", "ROCK": "debris",
        "GROUND": "debris", "STEEL": "debris", "NORMAL": "debris",
        "DRAGON": "travel", "FLYING": "travel",
    }.items()
}
SRC_PT = (164, 180)
TGT_PT = (56, 114)

# 每系两个确定性图形，第二变体在切镜及棋盘共用同一轮廓语言。
FX_VARIANTS = {
    "ELECTRIC": ("锯齿闪电", "双叉闪电"), "FIRE": ("锥形火星", "爆燃环"),
    "WATER": ("抛物水珠", "环形水花"), "GRASS": ("旋转叶片", "四叶绽放"),
    "BUG": ("环绕虫群", "蝶翼交错"), "PSYCHIC": ("同心波纹", "菱形念场"),
    "GHOST": ("升腾幽火", "双螺幽魂"), "POISON": ("毒雾", "毒泡破裂"),
    "DARK": ("暗雾", "交错月牙"), "ICE": ("放射冰晶", "六角雪晶"),
    "FIGHTING": ("碎片冲击", "拳压方环"), "ROCK": ("飞散碎石", "棱角岩簇"),
    "GROUND": ("扬尘", "分叉地裂"), "STEEL": ("金属碎片", "旋转刀片"),
    "NORMAL": ("冲击碎片", "交叉斩线"), "DRAGON": ("能量飞弹", "龙焰彗尾"),
    "FLYING": ("疾风飞弹", "双卷风刃"),
}


def fx_variant(t, unit_idx):
    return (effect_frame(t) + unit_idx) % 2


def impact_tier(damage, max_hp):
    """轻 <6%，中 6–15%，重 ≥15%；整数比较避免临界浮点漂移。"""
    return 2 if damage * 100 >= max_hp * 15 else int(damage * 100 >= max_hp * 6)


def draw_cross(draw, cx, cy, radius, color):
    for line in ((cx - radius, cy, cx + radius, cy), (cx, cy - radius, cx, cy + radius)):
        draw.line(line, fill=color, width=7)
        draw.line(line, fill=PAPER, width=3)


def draw_type_variant(draw, mtype, cx, cy, p, direction):
    """第二轮廓；无新增粒子，沿用原有预算中的主体图形。

    2026-09-14 缩幅：radius 18+18p → 12+12p（用户反馈特效盖住精灵）。
    """
    color = TYPE_COLORS.get(mtype, FRAME)
    radius = 12 + round(12 * p)

    def point(x, y):
        return (round(cx + x * math.cos(direction) - y * math.sin(direction)),
                round(cy + x * math.sin(direction) + y * math.cos(direction)))

    def stroke(points, width=4):
        draw.line(points, fill=color, width=width)
        draw.line(points, fill=PAPER, width=1)

    if mtype == "ELECTRIC":
        for side in (-1, 1):
            stroke([point(-radius, 0), point(-3, side * 8), point(2, side * 3),
                    point(radius, side * 13)])
    elif mtype in ("FIRE", "WATER", "PSYCHIC", "FIGHTING"):
        count = 16 if mtype == "FIRE" else 4
        if mtype == "WATER":
            for offset in (0, 5):
                draw.ellipse((cx - radius, cy - radius // 2 - offset,
                              cx + radius, cy + radius // 2 - offset), outline=color, width=3)
        else:
            points = []
            for i in range(count + 1):
                angle = i * math.tau / count + (math.pi / 4 if mtype == "FIGHTING" else 0)
                length = radius * (0.7 if mtype == "FIRE" and i % 2 else 1)
                points.append(point(length * math.cos(angle), length * math.sin(angle)))
            stroke(points)
    elif mtype in ("GRASS", "BUG", "ROCK", "STEEL"):
        for i in range(4):
            angle = i * math.pi / 2 + p
            x, y = radius * math.cos(angle), radius * math.sin(angle)
            points = [point(x * 0.25, y * 0.25), point(x - y * 0.3, y + x * 0.3),
                      point(x * 1.3, y * 1.3), point(x + y * 0.3, y - x * 0.3)]
            if mtype == "BUG":
                points[0] = point(0, 0)
            if mtype == "STEEL":
                points[2] = point(x * 1.5 - y * 0.4, y * 1.5 + x * 0.4)
            draw.polygon(points, fill=color, outline=PAPER)
    elif mtype in ("GHOST", "DARK", "DRAGON", "FLYING"):
        for side in (-1, 1):
            points = []
            for i in range(13):
                k = i / 12
                if mtype == "GHOST":
                    x, y = math.sin(k * math.tau + p * 3) * 8 * side, (k - 0.5) * radius * 2
                elif mtype == "DRAGON":
                    x, y = (k - 1) * radius * 2, side * (3 + 8 * k) + math.sin(k * 5) * 3
                else:
                    angle = side * (k * math.pi * 1.5 + p)
                    x, y = radius * math.cos(angle), radius * math.sin(angle) * 0.65 + side * 4
                points.append(point(x, y))
            stroke(points)
    elif mtype == "POISON":
        for i in range(4):
            x, y = point((i - 1.5) * 9, -math.sin(i + p * 3) * radius)
            draw.ellipse((x - 5, y - 5, x + 5, y + 5), outline=color, width=3)
            draw.point((x - 2, y - 2), fill=PAPER)
    elif mtype in ("ICE", "GROUND"):
        for i in range(6 if mtype == "ICE" else 3):
            angle = i * math.tau / (6 if mtype == "ICE" else 3)
            x, y = radius * math.cos(angle), radius * math.sin(angle)
            stroke([point(0, 0), point(x * 0.5 - 3, y * 0.5), point(x, y)], 3)
            stroke([point(x * 0.5 - 3, y * 0.5), point(x * 0.7 - y * 0.3, y * 0.7 + x * 0.3)], 3)
    else:  # NORMAL
        for side in (-1, 1):
            stroke([point(-radius, side * radius), point(radius, -side * radius)], 5)


class ParticleBudget:
    """仅削减装饰粒子；命中、落点、消散和吸能始终保留整组。"""

    def __init__(self, limit=PARTICLE_LIMIT):
        self.used = 0
        self.limit = max(0, min(PARTICLE_LIMIT, limit))

    def take(self, count, minimum=1, required=False):
        if required and self.used + count > self.limit:
            return range(0)
        count = min(count, max(0, self.limit - self.used))
        if count < minimum:
            return range(0)
        self.used += count
        return range(count)


def effect_frame(age):
    """稳定的 100ms 相位，避免浮点累加让特效多活一帧。"""
    return math.floor((age + 1e-9) / FPS_DT)


def draw_fx(draw, mtype: str, T: float, cutin_key: tuple, img=None) -> None:
    """按属性画一帧技能特效（特效相位 0.3~0.9）。"""
    style, colors = FX_STYLE.get(mtype, FX_STYLE["NORMAL"])
    phase = (T - cutin_key[0]) / CUTIN_LEN
    p = min(1.0, max(0.0, (phase - 0.3) / 0.6))
    if p <= 0:
        return
    c1, c2 = colors
    sx, sy = SRC_PT
    tx, ty = TGT_PT
    if fx_variant(T, cutin_key[1]):
        draw_type_variant(draw, mtype, tx, ty, p, math.atan2(ty - sy, tx - sx))
        return
    if style == "bolt":
        pts = [(sx, sy)]
        for i in range(1, 6):
            k = i / 6
            pts.append((sx + (tx - sx) * k + ((i * 7 + effect_frame(T) * 3) % 19 - 9),
                        sy + (ty - sy) * k + ((i * 11 + effect_frame(T) * 7) % 15 - 7)))
        pts.append((tx, ty))
        draw.line(pts, fill=c2, width=3)
        draw.line(pts, fill=c1, width=1)
        for i in range(3):
            draw.point((tx + (i * 13 + effect_frame(T) * 3) % 21 - 10,
                        ty + (i * 7 + effect_frame(T) * 5) % 21 - 10),
                       fill=c1)
    elif style in ("travel", "arc") and img is not None:
        path = "arc" if style == "arc" else "line"
        projectile(img, lambda k: trajectory_point((sx,sy),(tx,ty),k,path),
                   exposure_age(p*.6,.6), .6, mtype, c1, ParticleBudget(9))
    elif style == "travel":
        for i in range(9):
            k = (p + i / 18) % 1.0
            x = sx + (tx - sx) * k + (i - 4) * 2.2 * k
            y = sy + (ty - sy) * k - (i % 3) * 2 * (1 - k)
            col = c1 if k < 0.6 else c2
            light(draw, x, y, col)
    elif style == "arc":
        for i in range(7):
            k = (p + i / 14) % 1.0
            if k > 0.97:
                continue
            x = sx + (tx - sx) * k
            y = sy + (ty - sy) * k - 34 * 4 * k * (1 - k)
            draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=c1 if i % 2 else c2)
        if p > 0.75:
            r = 4 + int(11 * (p - 0.75) / 0.25)
            draw.ellipse((tx - r, ty - r // 2, tx + r, ty + r // 2),
                         outline=c2)
    elif style == "orbit":
        for i in range(7):
            ang = p * 7 + i * 0.9
            r = 15 + 4 * ((p * 3 + i) % 2)
            x, y = tx + r * 0.8 * math.cos(ang), ty + r * 0.6 * math.sin(ang)
            col = c1 if i % 2 else c2
            light(draw, x, y, col)
    elif style == "rings":
        for i in range(3):
            pr = (p + i / 3) % 1.0
            r = 6 + int(26 * pr)
            if r < 34:
                draw.ellipse((tx - r, ty - r, tx + r, ty + r),
                             outline=c1 if i % 2 else c2)
    elif style == "wisps":
        for i in range(6):
            pr = (p + i / 6) % 1.0
            x = tx + (i - 3) * 6 + 5 * ((pr * 4 + i) % 2 - 0.5)
            y = ty + 18 - 44 * pr
            col = c1 if i % 2 else c2
            light(draw, x, y, col)
    elif style == "shards":
        for i in range(7):
            ang = i * math.tau / 7 + 0.3
            r0, r1 = 4 + 13 * p, 8 + 20 * p
            draw.line((tx + r0 * math.cos(ang), ty + r0 * math.sin(ang),
                       tx + r1 * math.cos(ang), ty + r1 * math.sin(ang)),
                      fill=c1 if i % 2 else c2, width=2)
    elif style == "debris":
        if p < 0.3:
            r = 3 + int(12 * p / 0.3)
            draw.ellipse((tx - r, ty - r, tx + r, ty + r), outline=c2)
        for i in range(8):
            ang = i * math.tau / 8 + 0.2
            d = 6 + 20 * p
            x, y = tx + d * math.cos(ang), ty + d * 0.7 * math.sin(ang)
            debris(draw, x, y, ang, c1 if i % 2 else c2)


class AnimUnit:
    """单位回放态。注意：所有字段只反映「已回放到的时间点」的值。"""

    def __init__(self, unit) -> None:
        self.u = unit
        self.init_px = None
        self.reset()

    def reset(self) -> None:
        self.from_px = self.init_px or (BX + self.u.pos[0] * BCELL,
                                        BY + (self.u.pos[1] + VIS_ROW_OFF) * BCELL)
        self.to_px = self.from_px
        self.move_t0 = -9.0
        self.hp = self.u.max_hp
        self.hp_history = [(-9.0, self.u.max_hp)]  # (t, hp) 血条滴落用
        self.energy = 0
        self.die_t = None
        self.attacks = []
        self.knockbacks = []
        self.jitter_t = None  # 受击抖动（GSC 左右颤）
        self.recoil_t = None
        self.statuses = {}  # kind -> apply 时间；不读取 sim 的终局 _st。
        self.frozen_pose = None
        self.frozen_squash = 0
        self.blink = None

    def set_hp(self, t: float, hp: int) -> None:
        self.hp = max(0, hp)
        self.hp_history.append((t, self.hp))

    def hp_display(self, t: float) -> float:
        """GSC 血条滴落：伤害分 8 格阶梯式落下，0.4s 内完成，有咔哒感。"""
        prev, cur, t0 = self.u.max_hp, self.u.max_hp, -9.0
        for ht, hh in self.hp_history:
            if ht <= t + 1e-9:
                prev, cur, t0 = cur, hh, ht
            else:
                break
        if cur >= prev:
            return float(cur)
        k = min(1.0, (t - t0) / 0.4)
        step = math.floor(k * 8) / 8
        return prev - (prev - cur) * step

    def cell_px(self, pos: tuple) -> tuple:
        return (BX + pos[0] * BCELL, BY + (pos[1] + VIS_ROW_OFF) * BCELL)

    def deploy(self, pos) -> None:
        self.init_px = self.cell_px(pos)
        self.from_px = self.to_px = self.init_px
        self.move_t0 = -9.0

    def move(self, pos, t) -> None:
        self.from_px = self.render_px(t)
        self.to_px = self.cell_px(pos)
        self.move_t0 = t

    def render_px(self, t: float) -> tuple:
        if "freeze" in self.statuses:
            t = min(t, self.statuses["freeze"])
        k = min(1.0, max(0.0, (t - self.move_t0) / MOVE_SMOOTH))
        k = 1 - (1 - k) * (1 - k)  # easeOutQuad：起步快、到位缓，去机器感
        fx = self.from_px[0] + (self.to_px[0] - self.from_px[0]) * k
        fy = self.from_px[1] + (self.to_px[1] - self.from_px[1]) * k
        return (fx, fy)

    def moving(self, t: float) -> float:
        if t < self.move_t0 or t > self.move_t0 + MOVE_SMOOTH:
            return 0.0
        return (t - self.move_t0) / MOVE_SMOOTH

    def visible(self, t: float) -> bool:
        """Four death frames followed by 0.2s sinking/fade, unless the cell is reused."""
        if self.die_t is None:
            return True
        return t <= self.die_t + 6 * FPS_DT

    def dying(self, t: float) -> bool:
        return self.die_t is not None and t >= self.die_t


class BattleAnimation:
    """游标式回放：_ensure(T) 把事件推进到 T，frame(T) 只读「过去」状态。"""

    def __init__(self, comp_a, comp_b, seed: int,
                 front: Front, pal: Palettes, font: Font16,
                 weather_name=None, battle=None) -> None:
        self.front, self.pal, self.font = front, pal, font
        self.weather_name = weather_name  # 场景动画：透传给 Battle（S11）
        self.move_type = {m["name"]: m["type"] for m in pokedex().moves.values()}
        # 显示层汉化：事件流契约不变（cast 事件仍存英文名），渲染/面板翻译
        self.move_zh = {m["name"]: (m.get("name_zh") or m["name"])
                        for m in pokedex().moves.values()}
        b = battle or Battle(comp_a, comp_b, random.Random(seed + 1),
                             weather_name=weather_name)
        if battle is None:
            b.run()
        self.units = {u.idx: AnimUnit(u) for u in b.units}
        self.by_idx = {u.idx: u for u in b.units}
        self.events = b.events
        self.playback_clock = PlaybackClock(self.events)
        self._cursor = 0
        self._cur_t = -1.0
        self._busy_until = 0.0
        self.dusts = []
        self.floats = []
        self.msg = (0.0, "")
        self.cutins = []
        self.result = None

    def _active_statuses(self, au, T):
        # sim 的 flinch 只发 apply；这个短促反馈按其 0.3s 视觉寿命自行隐去。
        return [kind for kind in STATUS_ICONS if kind in au.statuses
                and (kind != "flinch" or 0 <= effect_frame(T - au.statuses[kind]) < 3)]

    def _reset(self) -> None:
        for au in self.units.values():
            au.reset()
        self.dusts, self.floats, self.cutins = [], [], []
        self.msg = (0.0, "")
        self.result = None
        self._cursor, self._cur_t, self._busy_until = 0, -1.0, 0.0

    def _ensure(self, T: float) -> None:
        if T < self._cur_t:      # 请求过去的时间（分镜抽帧）：从头重放
            self._reset()
        while self._cursor < len(self.events) and self.events[self._cursor][0] <= T:
            self._apply(self.events[self._cursor])
            self._cursor += 1
        self._cur_t = T

    def _apply(self, ev: tuple) -> None:
        t, kind = ev[0], ev[1]
        if kind == "deploy":
            self.units[ev[2]].deploy(ev[3])
        elif kind == "move":
            au = self.units[ev[2]]
            blink = au.u.piece.species_id == 65 and any(
                e[1] == "cast" and e[2] == ev[2] and abs(e[0] - t) < 1e-9 for e in self.events)
            if blink:
                au.blink = (t, au.render_px(t))
                au.deploy(ev[3])
            else:
                au.move(ev[3], t)
            self.dusts.append((t + MOVE_SMOOTH, au.to_px[0] + BCELL // 2, au.to_px[1] + BCELL - 6))
        elif kind == "attack":
            atk, tgt = self.units[ev[2]], self.units[ev[3]]
            dmg = ev[4]
            atk.energy = ev[5] if len(ev) > 5 else min(80, atk.energy + 15)
            tgt.set_hp(t, tgt.hp - dmg)
            tgt.energy = min(80, tgt.energy + 10)
            ax, ay = atk.render_px(t)
            bx, by = tgt.render_px(t)
            dx, dy = bx - ax, by - ay
            norm = math.hypot(dx, dy) or 1.0
            atk.attacks.append((t, dx / norm, dy / norm))
            tgt.knockbacks.append((t, dx / norm, dy / norm))
            tgt.jitter_t = t  # GSC 受击左右颤
            self.floats.append((t + self._attack_delay(ev), bx, by, f"-{dmg}", (255, 255, 255)))
        elif kind == "cast":
            ci, ti, move, eff, dmg = ev[2], ev[3], ev[4], ev[5], ev[6]
            au = self.units[ci]
            au.energy = ev[7] if len(ev) > 7 else 0
            skill = skill_profile(au.u.piece.species_id)
            start = t
            length = cast_windup(au.u.piece.species_id)
            self.cutins.append((start, start + length, ci, ti,
                                move, eff, dmg, au.u.piece.types[0]))
            au.recoil_t = start + length
            tgt = self.units[ti]
            if dmg:
                self.floats.append((start + length, *tgt.render_px(t),
                                    f"-{dmg}",
                                    (255, 90, 70) if eff > 1 else (255, 220, 60)))
                tgt.set_hp(t, tgt.hp - dmg)
            extra = "效果拔群！" if eff >= 2 else ("效果不佳" if 0 < eff < 1 else "")
            label = skill["name"]
            self.msg = (start + length, f"{self.by_idx[ci].piece.name}的{label}！ {extra}")
        elif kind == "regen":
            au = self.units[ev[2]]
            au.set_hp(t, min(au.u.max_hp, au.hp + ev[3]))
            self.floats.append((t, *au.render_px(t), f"+{ev[3]}", STATUS_GREEN))
        elif kind == "sash":
            self.units[ev[2]].set_hp(t, 1)
        elif kind == "die":
            au = self.units[ev[2]]
            au.die_t = t
            au.statuses.clear()
            au.frozen_pose = None
        elif kind == "status":
            au = self.units[ev[2]]
            status, action = ("paralysis" if ev[3] == "para" else ev[3]), ev[4]
            if action == "apply" and status in STATUS_ICONS:
                if status == "freeze" and status not in au.statuses:
                    pose = self._unit_pose(au, t)
                    au.frozen_pose = (pose[0], pose[1], None) if pose else None
                    au.frozen_squash = self._sprite_squash(au, t)
                # 冰冻刷新延续同一姿态与位置；其余状态刷新显示起点。
                if status != "freeze" or status not in au.statuses:
                    au.statuses[status] = t
            elif action == "expire":
                if status == "freeze" and status in au.statuses:
                    au.from_px = au.render_px(t)
                    au.move_t0 = t
                    au.frozen_pose = None
                au.statuses.pop(status, None)
            elif action == "tick" and len(ev) > 5 and ev[5] > 0:
                au.set_hp(t, au.hp - ev[5])
                self.floats.append((t, *au.render_px(t), f"-{ev[5]}",
                                    DOT_COLORS.get(status, STATUS_PURPLE)))
        elif kind == "end":
            self.result = ev[2]

    # ---- 帧渲染（只读已发生状态）----
    def frame(self, T: float, show_cutins=True) -> Image.Image:
        self._ensure(T)
        img = Image.new("RGBA", (W, H), (18, 18, 20, 255))
        self._draw_board(img, T)
        release = next((c for c in self.cutins if c[1] <= T < c[1] + .2
                        and skill_profile(self.units[c[2]].u.piece.species_id)["tier"] == "generic"), None)
        signature_active = any(c[0] <= T < c[1] + .6 and
                               skill_profile(self.units[c[2]].u.piece.species_id)["tier"] == "signature"
                               for c in self.cutins)
        if show_cutins and release and not signature_active:
            content = self._cutin_frame(release, T)
            img.alpha_composite(content, (0, self._board_shake(T)))
        return img

    def playback_frame(self, seconds, speed=1., skip=False, show_cutins=True):
        """Public presentation clock; frame(T) remains the sim-time compatibility API."""
        return self.frame(self.playback_clock.simulation_time(seconds, speed, skip), show_cutins)

    def _gait(self, au):
        sid = au.u.piece.species_id
        return gait_profile(au.u.piece, self.front.size_of[sid],
                            pokedex().species[sid]["base"]["speed"])

    def _attack_delay(self, ev):
        au = self.units[ev[2]]
        if au.u.range <= 1:
            return HIT_DELAY
        a, b = self._event_position(ev[2], ev[0]), self._event_position(ev[3], ev[0])
        distance = math.hypot(a[0] - b[0], a[1] - b[1])
        # px/s = 800 / range. Quantize arrival to the 10fps effect grid.
        return max(.2, math.ceil(distance * au.u.range / 800 / FPS_DT) * FPS_DT)

    def _event_position(self, idx, t):
        """Historical event positions, unaffected by later movement or a rewind."""
        pos = next((e[3] for e in reversed(self.events)
                    if e[0] <= t + 1e-9 and e[1] in ("deploy", "move") and e[2] == idx), None)
        return self.units[idx].cell_px(pos) if pos is not None else self.units[idx].render_px(t)

    def _projectile_cancelled(self, ev):
        dead = self.units[ev[3]].die_t
        return dead is not None and dead < ev[0] + self._attack_delay(ev) - 1e-9

    def _draw_projectiles(self, img, T, budget):
        draw = ImageDraw.Draw(img)
        for ev in self.events[:self._cursor]:
            if ev[1] != "attack" or self.units[ev[2]].u.range <= 1:
                continue
            age, duration = T - ev[0] - FPS_DT, self._attack_delay(ev) - FPS_DT
            if not 0 <= age < duration or self._projectile_cancelled(ev):
                continue
            source = self.units[ev[2]]
            a, b, trajectory = self._projectile_path(ev)
            color = TYPE_COLORS[source.u.piece.types[0]]
            projectile(img, lambda p: trajectory_point(a, b, p, trajectory),
                       exposure_age(age,duration), duration, source.u.piece.types[0], color, budget)

    def _projectile_path(self, ev):
        a = self._event_position(ev[2], ev[0])
        b = self._event_position(ev[3], ev[0])
        signature = SIGNATURES.get(self.units[ev[2]].u.piece.species_id)
        return ((a[0] + BCELL // 2, a[1] + 14),
                (b[0] + BCELL // 2, b[1] + 14),
                signature.trajectory if signature else "line")

    def _impact_direction(self, au, T):
        """One hit frame; melee faces attacker, ranged follows arrival tangent."""
        if au.dying(T) or "freeze" in au.statuses:
            return None
        for ev in reversed(self._recent_hits(T)):
            if ev[3] == au.u.idx and effect_frame(T-ev[0]-self._attack_delay(ev)) == 0:
                a,b,path = self._projectile_path(ev)
                if self.units[ev[2]].u.range > 1:
                    a = trajectory_point(a,b,.9,path)
                return b[0]-a[0], b[1]-a[1]
        for c in reversed(self.cutins):
            if c[3] == au.u.idx and c[6] > 0 and effect_frame(T-c[1]) == 0:
                a,b = self._event_position(c[2],c[0]), self._event_position(c[3],c[0])
                return b[0]-a[0], b[1]-a[1]
        return None

    def _draw_impact_preview(self, img, T):
        draw = ImageDraw.Draw(img)
        impacts = [(e[0]+self._attack_delay(e), e[3], e[0])
                   for e in self.events[:self._cursor] if e[1] == "attack"
                   and e[4] > 0 and not self._projectile_cancelled(e)]
        impacts += [(c[1],c[3],c[0]) for c in self.cutins if c[6] > 0]
        for at, idx, onset in impacts:
            if effect_frame(T-at) == -1:
                x,y = self._event_position(idx,onset)
                for dx,dy in ((-1,-1),(1,-1),(-1,1),(1,1)):
                    draw.point((round(x+BCELL//2+dx*19),round(y+14+dy*19)), fill=PAPER)

    def _draw_signatures(self, img, T, budget):
        for c in self.cutins:
            sid = self.units[c[2]].u.piece.species_id
            if not c[0] <= T < c[1] + .6:
                continue
            a, b = self._event_position(c[2], c[0]), self._event_position(c[3], c[0])
            # Put the small fire emblem on the least crowded rim, keeping its
            # impact anchor on the target. No new full-screen or solid overlay.
            candidates = [(b[0] + 20 + dx, b[1] + 16 + dy)
                          for dx, dy in ((-28, 0), (28, 0), (0, 34), (0, -30))]
            def overlap(point):
                x, y = point
                score = 10000 if not 12 <= x < W - 12 or not BY + 12 <= y < BY + BROWS * BCELL - 12 else 0
                for unit in self.units.values():
                    if unit.visible(T):
                        ux, uy = unit.render_px(T)
                        score += max(0, min(x + 12, ux + 36) - max(x - 12, ux + 4)) * max(
                            0, min(y + 12, uy + BOARD_FOOT) - max(y - 12, uy))
                return score
            emblem = min(candidates, key=overlap)
            profile = {**skill_profile(sid), "type": c[7],
                       "target_size": board_sprite_size(self.units[c[3]].u.piece.tier)}
            draw_skill(img, profile, (a[0] + 20, a[1] + 16),
                       (b[0] + 20, b[1] + 16), T - c[0], c[1] - c[0],
                       budget, variant=c[2] % 2, emblem=emblem)

    def _draw_board(self, img: Image, T: float) -> None:
        # All sprite poses, flashes and FX share this frame's hit selection.
        # Scoped to this draw only: isolated probes and rewind cannot reuse it.
        self._frame_hit_context = (id(self), T, self._recent_hits(T))
        try:
            self._render_board(img, T)
        finally:
            self._frame_hit_context = None

    def _render_board(self, img: Image, T: float) -> None:
        # C-sym 分区（自上而下）：敌备战 1 行 / 敌战场 2 行 / 我战场 2 行 /
        # 我备战 1 行；备战行用观战格底色（bench=True），不落战斗单位。
        img.paste(board_floor(self.weather_name), (BX, BY))
        draw_divider(img, BX, BY + 3 * BCELL, BCOLS * BCELL)
        draw = ImageDraw.Draw(img)
        draw.line((BX, BY - 1, BX + BCOLS * BCELL - 1, BY - 1), fill=INK)
        draw.line((BX, BY + BROWS * BCELL, BX + BCOLS * BCELL - 1, BY + BROWS * BCELL), fill=INK)
        self._draw_ground_scars(img, T)
        shown = sorted((au for au in self.units.values() if au.visible(T)),
                       key=lambda a: a.render_px(T)[1])
        poses = {au.u.idx: self._unit_pose(au, T) for au in shown}
        # 切镜滑入/滑出时两层同时可见，为切镜的至多 9 粒子 + 4 星闪留额。
        in_cutin = any(c[0] <= T < c[1] + .2 for c in self.cutins)
        budget = ParticleBudget(PARTICLE_LIMIT - 13 if in_cutin else PARTICLE_LIMIT)
        # 天气预算独立固定为八粒，也从整盘预算扣除。
        weather = weather_particles(self.weather_name, T)
        budget.take(len(weather), minimum=len(weather))
        fx = Image.new("RGBA", (W, H))
        # 先分配命中/消散/蓄力，再把剩余预算给尘土与旧星闪。
        self._draw_board_fx(fx, T, budget, poses)
        for t, x, y in self.dusts:
            age = T - t
            if 0 <= effect_frame(age) < 4 and age < DUST_LIFE:
                k = age / DUST_LIFE
                for j in budget.take(2, minimum=2):
                    off = (-2, 2)[j]
                    draw.ellipse((x + off - 1 - j, y - int(4 * k),
                                  x + off + 1 + j, y + 2 - int(4 * k)), fill=FRAME)
        for au in shown:
            if poses[au.u.idx] is not None:
                self._draw_unit(img, au, T, poses[au.u.idx], budget)
        # All solid VFX are excluded from actual opaque sprite pixels. Outer
        # rings remain visible, even when several signatures overlap a unit.
        protected = Image.new("L", img.size)
        for au in shown:
            if poses[au.u.idx] is not None:
                sprite, x, y = self._sprite_placement(au, T, poses[au.u.idx])
                mask = Image.new("L", img.size)
                mask.paste(sprite.getchannel("A"), (x, y))
                protected = ImageChops.lighter(protected, mask)
        fx.putalpha(ImageChops.subtract(fx.getchannel("A"), protected))
        img.alpha_composite(fx)
        for x, y, width, height, color in weather:
            draw.rectangle((x, y, x + width - 1, y + height - 1), fill=color)
        self._draw_floats(img, T)
        self._draw_board_flash(img, T)
        self._draw_opening(img, T)
        # 图标属于持久状态，最后重绘，免于被落点、跳字、白闪淹没。
        for au in shown:
            if poses[au.u.idx] is not None:
                self._draw_status_band(img, au, T)
        # 全部状态条最后画：粒子、邻格残影、白闪、数字牌均不能盖住读数。
        for au in shown:
            pose = poses[au.u.idx]
            if pose is not None:
                self._draw_unit_meters(img, au, T, pose)
        shake = self._board_shake(T)
        if shake:
            board = img.crop((BX, BY, BX + BCOLS * BCELL, BY + BROWS * BCELL))
            # 裁切平移；边缘延用原地砖，不把另一端内容卷进来。
            img.paste(board.crop((0, max(0, -shake), board.width,
                                  board.height - max(0, shake))),
                      (BX, BY + max(0, shake)))
        self._draw_message(img, T)
        # HUD 最后绘制，原尺寸大精灵入场时不会遮住顶部读数。
        draw_hud(img, self.font, hp=34, gold=13, level=5, rnd=13, right="▶")
        if self.weather_name in WEATHER_ICONS:
            rows, color = WEATHER_ICONS[self.weather_name]
            draw_pixel_icon(img, (228, 11), rows, color)

    def _casting_phase(self, au, T):
        """只从已回放信息推导抬手；即时 cast 之前以满能量阈值为起点。"""
        if au.dying(T):
            return None
        active = next((c for c in self.cutins if c[2] == au.u.idx and c[0] <= T < c[1]), None)
        if active:
            return ((T - active[0]) / (active[1] - active[0]), active[7])
        return None

    def _board_shake(self, T):
        for c in reversed(self.cutins):
            phase = effect_frame(T - c[1])
            if 0 <= phase < 2:
                return (2, -2)[phase]
        return 0

    def _draw_board_flash(self, img, T):
        if 0 <= effect_frame(T) < 2:
            alpha = (208, 144)[effect_frame(T)]
        elif any(0 <= T - t < .03 for t in self.playback_clock.starts):
            alpha = 48
        elif any(c[6] > 0 and effect_frame(T - c[1]) == 0 for c in self.cutins):
            alpha = 20  # 20 / 255 = 7.84%，仅落点首帧。
        else:
            return
        flash = Image.new("RGBA", (BCOLS * BCELL, BROWS * BCELL), (255, 255, 255, alpha))
        img.alpha_composite(flash, (BX, BY))

    def _draw_opening(self, img, T):
        phase = effect_frame(T)
        if not 0 <= phase < effect_frame(OPENING_LIFE):
            return
        center = BY + BROWS * BCELL // 2
        draw = ImageDraw.Draw(img)
        # 双侧速度线扫向中场，横幅贯穿 240px；文字使用原生 16px 字库。
        for i in range(8):
            y = center - 48 + i * 13
            length = 32 + (i % 3) * 12 + phase * 8
            for start, end in ((0, length), (W - 1, W - 1 - length)):
                draw.line((start, y, end, y), fill=INK, width=4)
                draw.line((start, y, end, y), fill=PAPER, width=2)
        pixel_window(img, (0, center - 22, W - 1, center + 22), dark=True)
        draw.line((1, center - 18, W - 2, center - 18), fill=FULL_GOLD, width=2)
        draw.line((1, center + 18, W - 2, center + 18), fill=FULL_GOLD, width=2)
        draw_text(img, ((W - text_width("开战！")) // 2, center - 8),
                  "开战！", self.font, PAPER)

    def _recent_hits(self, T):
        context = getattr(self, '_frame_hit_context', None)
        if context is not None and context[:2] == (id(self), T):
            return context[2]
        return [ev for ev in self.events[:self._cursor]
                if ev[1] == "attack" and ev[4] > 0
                and not self._projectile_cancelled(ev)
                and 0 <= effect_frame(T - ev[0] - self._attack_delay(ev)) < 3]

    def _unit_pose(self, au, T):
        """绘制坐标供精灵、特效和最后一层状态条共用，不写回单位。"""
        if "freeze" in au.statuses and au.frozen_pose is not None and not au.dying(T):
            return au.frozen_pose
        u = au.u
        x, y = au.render_px(T)
        dying = au.dying(T)
        # A dead cell is immediately reusable by sim. Stop its presentation if
        # a living neighbour enters it; never cover that unit or its meters.
        if dying and any(other is not au and not other.dying(T)
                         and abs(other.render_px(T)[0] - x) < BCELL
                         and abs(other.render_px(T)[1] - y) < BCELL / 2
                         for other in self.units.values()):
            return None
        age = (T - au.die_t) if dying else 0
        casting = self._casting_phase(au, T)

        idle, _, sensitive, tempo, amplitude, walk_hz = self._motion_profile(u.piece.species_id)
        ox, oy, _ = self._attack_motion(au, T)
        for kt, kdx, kdy in au.knockbacks[-1:]:
            dt2 = T - kt
            recovery = (0.16 if sensitive else 0.26) * tempo
            if 0 <= dt2 < recovery:
                k = 1 - dt2 / recovery
                extra = 1 if effect_frame(dt2) == 0 else 0
                ox += kdx * (2 * k * amplitude + extra)
                oy += kdy * (2 * k * amplitude + extra)
        if sensitive and au.jitter_t is not None and 0 <= T - au.jitter_t < 0.16 * tempo:
            ox += (3 if effect_frame(T - au.jitter_t) % 2 == 0 else -3) * amplitude
        if casting:
            ox += 1 if au.u.team == 0 else -1
        if au.recoil_t and 0 <= T - au.recoil_t < 0.2:
            oy += 1
        if not dying and not casting:
            clock = T / tempo + u.piece.species_id * 0.17
            if idle == 0:  # 稳重：慢、大呼吸；纵向压缩也参与呼吸。
                oy += math.sin(clock * 1.8) * 1.5 * amplitude
            elif idle == 1:  # 灵活：小而快，周期歪头 1px。
                oy += math.sin(clock * 5.8) * 0.55 * amplitude
                ox += int(effect_frame(clock) % 24 in (0, 1))
            else:  # 慵懒：极慢的左右摇摆。
                ox += math.sin(clock * 0.85) * 1.2 * amplitude
        if not dying and not casting and T < 0.35:
            # 开场入场：从上方落下，缓动到位 + 末尾一像素顿挫
            k = T / 0.35
            oy -= 10 * (1 - k) * (1 - k)
            if k > 0.85:
                oy += 1
        gait = self._gait(au)
        phase = int((T + 1e-9) / (gait.period / 2)) % 2
        if not dying:
            if gait.floating:
                oy += 1 - phase  # Both poses survive the sprite/board rise clamp.
            elif au.moving(T) > 0:
                oy += phase
                ox += gait.amplitude * (1 if phase else -1)
        dying_frame = effect_frame(age) if dying else -1
        if dying:
            # GSC 濒死：脚下星闪 -> 逐帧下沉 -> 眨眼消失
            oy += min(8, dying_frame * 2) + max(0, dying_frame - 3)
            if dying_frame >= 6:
                return  # 最后一帧隐去（眨眼）

        # 只约束绘制偏移，不改模拟坐标/插值；横向极值仍可区分攻击风格。
        sprite = self._board_sprite(u.piece.species_id, u.piece.tier, self._sprite_squash(au, T))
        bounds = sprite.getbbox()
        rise_limit = BOARD_FOOT - (bounds[3] - bounds[1]) + 4
        return (round(x + max(-3, min(3, ox))),
                round(y + max(-rise_limit, oy if dying else min(3, oy))), casting)

    @lru_cache(maxsize=151)
    def _motion_profile(self, species_id):
        size = self.front.size_of[species_id]
        speed = pokedex().species[species_id]["base"]["speed"]
        weight = (size - 40) / 16
        return (species_id % 3, (species_id // 3) % 3, species_id % 2,
                1 + 0.2 * weight, 1 - 0.2 * weight,
                4.5 if speed >= 90 else 3.5 if speed >= 60 else 2.5)

    def _attack_motion(self, au, T):
        _, style, _, tempo, amplitude, _ = self._motion_profile(au.u.piece.species_id)
        attack = next((a for a in reversed(au.attacks)
                       if 0 <= T - a[0] < ATTACK_ANIM * tempo), None)
        if attack is None or au.dying(T):
            return 0.0, 0.0, 0
        if effect_frame(T - attack[0]) == 0:
            return -attack[1], -attack[2], 0
        age = (T - attack[0]) / tempo
        windup = (0.08, 0.055, 0.14)[style]
        if age < windup:
            k = age / windup
            thrust, jump, squash = -1.5 * k, 0, round((2, 5, 4)[style] * k)
        else:
            k = (age - windup) / (ATTACK_ANIM - windup)
            thrust = (3.5, 4, 5)[style] * (1 - k) ** (1 if style == 0 else 2)
            jump = 3 * math.sin(k * math.pi) if style == 0 else 0
            squash = round((2, 6, 1)[style] * (1 - k))
        return (attack[1] * thrust * amplitude,
                (attack[2] * thrust - jump) * amplitude, squash)

    def _sprite_squash(self, au, T):
        if "freeze" in au.statuses and not au.dying(T):
            return au.frozen_squash
        if au.u.piece.species_id == 143 and any(
                c[2] == au.u.idx and 0 <= effect_frame(T - c[1]) < 2 for c in self.cutins):
            return 6
        squash = self._attack_motion(au, T)[2]
        if not au.dying(T) and not self._gait(au).floating:
            squash += int((T + au.u.piece.species_id * .17) / .6) % 2
        return min(6, squash)

    @lru_cache(maxsize=1024)
    def _board_sprite(self, species_id, tier, squash=0):
        box = board_sprite_size(tier)
        source = self.front.image(species_id, self.pal)
        # 每个动作相位直接从源图 BOX + 量化，避免多次重采样损失细节。
        return scale_sprite(source, self.pal.for_species(species_id), (box, box - squash))

    def _sprite_placement(self, au, T, pose):
        sprite = self._board_sprite(au.u.piece.species_id, au.u.piece.tier,
                                    self._sprite_squash(au, T))
        if not au.dying(T):
            status = "freeze" if "freeze" in au.statuses else (
                "poison" if "poison" in au.statuses and effect_frame(T) % 2 == 0 else None)
            if status:
                sprite = self._status_sprite(au.u.piece.species_id, au.u.piece.tier,
                                             self._sprite_squash(au,T), status)
        if not au.dying(T) and "freeze" not in au.statuses:
            gait = self._gait(au)
            phase = int((T + 1e-9) / (gait.period / 2)) % 2
            sprite = pose_sprite(sprite, gait, phase, au.moving(T) > 0)
        direction = self._impact_direction(au, T)
        if direction is not None:
            sprite = hit_sprite(sprite, direction)
        x = max(BX, min(BX + BCOLS * BCELL - sprite.width,
                       round(pose[0] + (BCELL - sprite.width) / 2)))
        y = pose[1] + BOARD_FOOT - sprite.getbbox()[3]
        if direction is not None:
            y = max(y, math.ceil(au.render_px(T)[1]-4.5)-sprite.getbbox()[1])
        return sprite, x, y

    @lru_cache(maxsize=1024)
    def _status_sprite(self, species_id, tier, squash, status):
        sprite = self._board_sprite(species_id, tier, squash).copy()
        tint, amount = ((255, 255, 255), 60) if status == "freeze" else (STATUS_PURPLE, 15)
        colors = self.pal.for_species(species_id)
        replacements = {tuple(c): tuple((v * (100 - amount) + target * amount + 50) // 100
                                        for v, target in zip(c, tint)) for c in colors}
        sprite.putdata([replacements.get(pixel[:3], pixel[:3]) + (pixel[3],)
                        for pixel in sprite.getdata()])
        return sprite

    def _draw_status_band(self, img, au, T):
        if au.dying(T):
            return
        kinds = self._active_statuses(au, T)[:3]
        px, py = au.render_px(T)
        x = round(px + (BCELL - len(kinds) * 7 + 1) / 2)
        y = round(py + BOARD_FOOT - 7)
        draw = ImageDraw.Draw(img)
        for i, kind in enumerate(kinds):
            left = x + i * 7
            rows, color = STATUS_ICONS[kind]
            draw.rectangle((left, y, left + 5, y + 5), fill=INK)
            draw_pixel_icon(img, (left + (6 - len(rows[0])) // 2, y + 1), rows, color)

    def _draw_status_body(self, img, au, T, pose, budget):
        if au.dying(T):
            return
        px, py, _ = pose
        foot = py + BOARD_FOOT
        draw = ImageDraw.Draw(img)
        kinds = self._active_statuses(au, T)
        for kind in kinds:
            if kind in BUFF_KINDS:
                color = STATUS_ICONS[kind][1]
                draw.ellipse((px + 1, foot - 4, px + BCELL - 2, foot + 4), outline=color)
        if "freeze" in kinds:
            return
        if "burn" in kinds:
            for i in budget.take(2, minimum=2, required=True):
                rise = (effect_frame(T) + i * 3) % 6
                x, y = px + (7 if i == 0 else BCELL - 8), foot - 2 - rise
                draw.line((x, y+2, x+1, y), fill=STATUS_ORANGE if rise < 3 else HP_LOW)
                draw.point((x+1,y), fill=PAPER)
        if "paralysis" in kinds and effect_frame(T) % 6 == 0 and budget.take(1):
            draw_pixel_icon(img, (px + BCELL - 6, foot - 14), ("01", "10", "01"), FULL_GOLD)
        if "sleep" in kinds and budget.take(1):
            draw_pixel_icon(img, (px + BCELL - 6, foot - 15 - effect_frame(T) % 8),
                            STATUS_ICONS["sleep"][0], STATUS_BLUE)

    def _draw_unit(self, img, au, T, pose, budget):
        draw = ImageDraw.Draw(img)
        u = au.u
        px_, py_, casting = pose
        dying = au.dying(T)
        age = T - au.die_t if dying else 0
        foot = py_ + BOARD_FOOT
        if self._gait(au).floating and not dying:
            foot = round(au.render_px(T)[1]) + BOARD_FOOT + 1
            draw.ellipse((px_ + 10, foot - 2, px_ + 30, foot + 1), outline=FRAME)
        if not dying:
            draw_base(img, px_ + 1, foot, BCELL - 2, u.piece.types,
                      u.piece.tier, casting)

        sprite, anchor_x, anchor_y = self._sprite_placement(au, T, pose)
        frozen = "freeze" in au.statuses and not dying
        # 残影只复制量化后精灵的二值 alpha 蒙版，保留干净的像素边缘。
        if not dying and not frozen:
            if effect_frame(T - au.move_t0) in (0, 1):
                old_x, old_y = au.render_px(max(au.move_t0, T - FPS_DT))
                now_x, now_y = au.render_px(T)
                if budget.take(1):
                    self._draw_echo(img, sprite, anchor_x + round((old_x - now_x) * .45),
                                    anchor_y + round((old_y - now_y) * .45), FRAME, 48)
        if dying and age >= .4:
            sprite = sprite.copy()
            opacity = max(0, min(255, round(255 * (.6 - age) / .2)))
            sprite.putalpha(sprite.getchannel("A").point(lambda a: a * opacity // 255))
        teleport = next((c for c in self.cutins if c[2] == u.idx and u.piece.species_id == 65
                         and effect_frame(T - c[0]) in (0, 1)), None)
        if teleport and effect_frame(T - teleport[0]) == 0 and budget.take(1):
            origin = au.blink[1] if au.blink and abs(au.blink[0] - teleport[0]) < 1e-9 else au.render_px(T)
            self._draw_echo(img, sprite, round(origin[0] + (BCELL - sprite.width) / 2),
                            round(origin[1] + BOARD_FOOT - sprite.getbbox()[3]), STATUS_PURPLE, 128)
        hit_phases = [effect_frame(T-ev[0]-self._attack_delay(ev))
                      for ev in self._recent_hits(T) if ev[3] == u.idx]
        hit_phases += [effect_frame(T-c[1]) for c in self.cutins
                       if c[3] == u.idx and c[6] > 0 and 0 <= effect_frame(T-c[1]) <= 1]
        if teleport and effect_frame(T-teleport[0]) == 1:
            hit_phases.append(0)
        if not frozen and any(p in (0,1) for p in hit_phases):
            sprite = feather_flash(sprite, recovery=0 not in hit_phases)
        img.alpha_composite(sprite, (anchor_x, anchor_y))
        self._draw_status_body(img, au, T, pose, budget)
        if not dying and au.energy >= 80:
            # 底座外沿完整闭合的 2px 金描边；画在精灵之后，背侧也清晰可见。
            halo = Image.new("RGBA", (BCELL + 6, 18))
            hd = ImageDraw.Draw(halo)
            alpha = 208 if frozen else (160, 208, 255, 255, 208, 160)[effect_frame(T) % 6]
            hd.ellipse((1, 1, BCELL + 4, 16), outline=FULL_GOLD + (alpha,), width=2)
            img.alpha_composite(halo, (px_ - 3, foot - 8))
        if dying and 0 <= age < FPS_DT and budget.take(1):
            draw_spark(img, px_ + BCELL // 2, foot + 3)
        strike = [a for a in au.attacks if not frozen and u.range <= 1
                  and HIT_DELAY <= T - a[0] < ATTACK_ANIM
                  and (u.piece.species_id != 143 or effect_frame(T - a[0]) == 1)]
        if strike:
            _, adx, ady = strike[-1]
            cx0 = anchor_x + sprite.width // 2
            cy0 = anchor_y + sprite.height // 2
            direction = math.atan2(ady, adx)
            arc_col = TYPE_COLORS[u.piece.types[0]]
            radius = 15
            points = [(round(cx0 + radius * math.cos(direction - .8 + j * .2)),
                       round(cy0 + radius * math.sin(direction - .8 + j * .2))) for j in range(9)]
            draw.line(points, fill=arc_col, width=2)

    @staticmethod
    def _draw_echo(img, sprite, x, y, color, opacity):
        echo = Image.new("RGBA", sprite.size, color)
        echo.putalpha(sprite.getchannel("A").point(lambda a: a * opacity // 255))
        img.alpha_composite(echo, (int(x), int(y)))

    def _draw_unit_meters(self, img, au, T, pose):
        # 固定在逻辑脚点，不随身体颤动，防止前排头顶 HP 撞后排能量条。
        px_, py_ = (round(v) for v in au.render_px(T))
        u = au.u
        # 滴落读数和原低血/满能相位不变，仅收束到红 / 金两种语义。
        frac = au.hp_display(T) / u.max_hp
        c = HP_RED if frac > 0.25 or int(T * 10) % 4 < 2 else HP_LOW
        full = au.energy >= 80
        ec = (ENERGY if int(T * 10) % 4 < 2 else PAPER) if full else ENERGY
        # HP 在头顶（精灵 alpha 最多上溢 4px）；6px 图标带在脚点前 7px。
        draw_meter(img, px_ + 3, py_ - 10, BCELL - 6, frac, c, height=4)
        draw_meter(img, px_ + 3, py_ + BOARD_FOOT + 5, BCELL - 6, au.energy / 80, ec, height=4)

    def _ground_scars(self, T):
        """印记固定在落点格；从已发生的事件推导，不添加回放状态。"""
        impacts = [(ev[0] + self._attack_delay(ev), ev[3], self.units[ev[2]].u.piece.types[0])
                   for ev in self.events[:self._cursor] if ev[1] == "attack"
                   and self.units[ev[2]].u.piece.species_id != 6
                   and not self._projectile_cancelled(ev)
                   and impact_tier(ev[4], self.units[ev[3]].u.max_hp) == 2]
        impacts += [(c[1], c[3], c[7]) for c in self.cutins]
        end = next((ev[0] for ev in reversed(self.events[:self._cursor]) if ev[1] == "end"), None)
        fade = max(0, 1 - (T - end) / 0.6) if end is not None else 1
        for at, target, mtype in impacts:
            phase = effect_frame(T - at)
            if not 0 <= phase < SCAR_FRAMES or fade <= 0:
                continue
            pos = next((ev[3] for ev in reversed(self.events[:self._cursor])
                        if ev[0] <= at and ev[1] in ("deploy", "move") and ev[2] == target), None)
            if pos is not None:
                x, y = self.units[target].cell_px(pos)
                yield (x + BCELL // 2, y + BOARD_FOOT, mtype,
                       round(112 * (SCAR_FRAMES - phase) / SCAR_FRAMES * fade))

    def _draw_ground_scars(self, img, T):
        layer = Image.new("RGBA", img.size)
        draw = ImageDraw.Draw(layer)
        for cx, cy, mtype, alpha in self._ground_scars(T):
            color = TYPE_COLORS[mtype] + (alpha,)
            for i in range(14):
                angle = i * math.tau / 14
                radius = 16 + (i % 3) * 3  # 露出底座两侧，离开后仍可见。
                x = round(cx + math.cos(angle) * radius)
                y = round(cy + math.sin(angle) * radius * 0.4)
                draw.rectangle((x, y, x + 1, y + 1), fill=color)
            draw.line((cx - 5, cy, cx - 1, cy + 2, cx + 5, cy - 1), fill=INK + (alpha,))
        img.alpha_composite(layer)

    def _draw_board_fx(self, img, T, budget, poses):
        """统一棋盘粒子预算；线框原语与实体粒子分开计数。"""
        draw = ImageDraw.Draw(img)
        self._draw_impact_preview(img, T)
        self._draw_projectiles(img, T, budget)
        self._draw_signatures(img, T, budget)
        for ev in self._recent_hits(T):
            phase = effect_frame(T - ev[0] - self._attack_delay(ev))
            attacker, target = self.units[ev[2]], self.units[ev[3]]
            tx, ty = target.render_px(T)
            pose = poses.get(ev[3])
            if pose is not None:
                tx, ty = pose[:2]
            ax, ay = attacker.render_px(T)
            direction = math.atan2(ty - ay, tx - ax)
            cx = max(18, min(W - 19, round(tx) + BCELL // 2))
            cy = round(ty) + BCELL - 30
            color = TYPE_COLORS[attacker.u.piece.types[0]]
            strength = impact_tier(ev[4], target.u.max_hp)
            variant = fx_variant(T, ev[2])
            if phase < 1 and attacker.u.range <= 1:
                source = poses.get(ev[2])
                sx, sy = source[:2] if source is not None else (ax, ay)
                line = (round(sx) + BCELL // 2, round(sy) + BCELL - 30, cx, cy)
                if variant:
                    sx0, sy0, _, _ = line
                    line = [(round(sx0 + (cx - sx0) * k / 8),
                             round(sy0 + (cy - sy0) * k / 8 - 9 * 4 * k / 8 * (1 - k / 8)))
                            for k in range(9)]
                draw.line(line, fill=color, width=3)
                draw.line(line, fill=PAPER, width=1)
            # Inclusive diameter stays <=75%; reserve 1px radius per weight
            # tier so the cap cannot flatten light/medium/heavy into one size.
            cap = (math.floor(board_sprite_size(target.u.piece.tier) * .75) - 1) // 2
            radius = min(cap - (2 - strength),
                         (9, 11, 12)[strength] + phase * 2 + (2 if variant else 0))
            ring = 29 + phase * 3
            impact_rim(img, (cx,cy), ring, color, phase, budget, direction)
            contact = board_sprite_size(target.u.piece.tier) * .4
            impact_star(draw, round(cx-contact*math.cos(direction)),
                        round(cy-contact*math.sin(direction)), radius, direction, color,
                        effect_frame(ev[0]) * 31 + ev[2])
        # 消散不依赖精灵是否已眨眼隐藏：最后一帧只留上升粒子。
        for au in self.units.values():
            if au.die_t is None or not (0 <= effect_frame(T - au.die_t) < 4):
                continue
            x, y = au.render_px(T)
            phase = effect_frame(T - au.die_t) / 3
            color = TYPE_COLORS[au.u.piece.types[0]]
            for i in budget.take(6, required=True):
                drift = math.sin(phase * math.pi + i * 1.7) * 2
                xx = round(x + BCELL // 2 + (i - 2.5) * 5 + drift)
                yy = round(y + BCELL - 20 - phase * 20 - (i % 2) * 3)
                light(draw, xx, yy, color)
                draw.point((xx, yy), fill=PAPER)
    def _draw_telegraph(self, img: Image, cells: list, color) -> None:
        """④ 范围预警钩子：AoE 招式命中前 1 帧对格子集合画半透明高亮。

        cells 为受影响格坐标列表（棋盘列行）；S5 AoE 招式进池时由
        cast 事件携带范围并调用，当前无调用方（留档待接线）。
        """
        draw = ImageDraw.Draw(img)
        for col, row in cells:
            x, y = BX + col * BCELL, BY + row * BCELL
            draw.rectangle((x + 1, y + 1, x + BCELL - 2, y + BCELL - 2),
                           fill=color + (90,))

    def _draw_floats(self, img: Image, T: float) -> None:
        occupied = []
        silhouettes = []
        for au in self.units.values():
            if au.visible(T):
                ux, uy = au.render_px(T)
                sprite = self.front.image(au.u.piece.species_id, self.pal)
                bounds = sprite.getbbox()
                left = max(0, min(W - sprite.width, int(ux + (BCELL - sprite.width) / 2)))
                bottom = uy + BCELL - 16
                silhouettes.append((left + bounds[0], bottom - bounds[3] + bounds[1],
                                    left + bounds[2], uy + BCELL))
        for t, x, y, text, color in self.floats:
            age = T - t
            if not (0 <= age < FLOAT_LIFE):
                continue
            # Basic digits are 7px tall; skill digits are exactly 1px taller.
            scale = 1 if color in DOT_COLORS.values() or color == (255, 255, 255) else 8 / 7
            fx = max(6, min(W - len(text) * 6 * scale - 6, x + 6))
            rise = number_rise(age, FLOAT_LIFE)
            fy = max(32, y - 6 - rise)
            if age > FLOAT_LIFE - 0.2 and int(age * 10) % 2 == 1:
                continue  # 消失前眨两下
            if color == (255, 90, 70):
                fx += 2 if int(age * 10) % 2 == 0 else -2  # 克制红字颤动
            # 只调整同帧牌的位置，不合并事件、不改变显示时间或数值。
            width, height = (len(text) * 6 - 1) * scale + 8, 7 * scale + 9
            candidates = []
            for dx, dy in ((0, 0), (-width - 3, 0), (width + 3, 0),
                           (0, -height - 3), (0, height + 3), (-width - 3, -height - 3),
                           (-2 * width - 6, 0), (2 * width + 6, 0),
                           (-2 * width - 6, -height - 3), (2 * width + 6, -height - 3)):
                nx = int(max(6, min(W - width + 2, fx + dx)))
                ny = int(max(BY + 7, min(BY + BROWS * BCELL - height, fy + dy)))
                rect = (nx - 4, ny - 4, nx - 4 + width, ny - 4 + height)
                overlap = sum(max(0, min(rect[2], r[2]) - max(rect[0], r[0]))
                              * max(0, min(rect[3], r[3]) - max(rect[1], r[1]))
                              for r in occupied)
                sprite_overlap = sum(max(0, min(rect[2], r[2]) - max(rect[0], r[0]))
                                     * max(0, min(rect[3], r[3]) - max(rect[1], r[1]))
                                     for r in silhouettes)
                candidates.append((overlap * 8 + sprite_overlap, abs(dx) + abs(dy), nx, ny, rect))
            _, _, fx, fy, rect = min(candidates)
            occupied.append(rect)
            if abs(fx - (x + 6)) > width:
                origin = (int(x + BCELL // 2), int(y + 5))
                ImageDraw.Draw(img).line((origin, (fx, fy + 4)), fill=INK)
            heavy = any(e[1] == "attack" and abs(e[0]+self._attack_delay(e)-t) < 1e-8
                        and text == f"-{e[4]}" and impact_tier(e[4], self.units[e[3]].u.max_hp) == 2
                        for e in self.events[:self._cursor])
            heavy = heavy or any(abs(c[1]-t) < 1e-8 and text == f"-{c[6]}"
                                 for c in self.cutins)
            self._draw_damage_number(img, (fx, fy), text, color, scale, heavy=heavy)

    @staticmethod
    def _draw_damage_number(img, xy, text, color, scale, heavy=False):
        """透明数字；普通 1px 描边，重击再加 1px，字形高度不变。"""
        color = {(255, 255, 255): PAPER, (255, 220, 60): FULL_GOLD,
                 (255, 90, 70): HP_LOW}.get(color, color)
        glyph = Image.new("RGBA", (len(text) * 6 - 1, 7))
        draw_pixel_text(glyph, (0, 0), text, color, 1)
        glyph = glyph.resize((round(glyph.width * scale), round(7 * scale)), Image.Resampling.NEAREST)
        edge = 2 if heavy else 1
        size = (glyph.width + edge*2, glyph.height + edge*2)
        digits = Image.new("RGBA", size)
        digits.paste(glyph, (edge, edge))
        outline = Image.new("RGBA", size, (0, 0, 0, 255))
        outline.putalpha(digits.getchannel("A").filter(ImageFilter.MaxFilter(edge*2+1)))
        outline.alpha_composite(digits)
        img.alpha_composite(outline, (int(xy[0]) - edge, int(xy[1]) - edge))

    def _draw_message(self, img: Image, T: float) -> None:
        t0, text = self.msg
        if self.weather_name in WEATHER_MESSAGES and 0 <= T <= 1.8:
            t0, text = 0.0, WEATHER_MESSAGES[self.weather_name]
        y0 = BY + BROWS * BCELL + 4
        # 固定日志外框填满原有底部留白；消息出现/消退条件完全不变。
        pixel_window(img, (1, y0, 238, H - 2))
        draw_text(img, (10, y0 + 4), "战斗记录", self.font, INK)
        draw_pixel_text(img, (186, y0 + 8), f"{T:04.1f}", INK)
        draw = ImageDraw.Draw(img)
        draw.line((11, y0 + 20, W - 12, y0 + 20), fill=FRAME)
        if not text or T < t0 - 0.2 or T > t0 + 1.8:
            draw_text(img, (10, y0 + 24), "自动战斗中……", self.font, INK)
            return
        # 40px 棋盘后日志只有 48px：按原消息寿命分页，一次完整显示一行。
        lines = wrap_text(text, W - 36)
        line = lines[min(len(lines) - 1, max(0, int((T - t0) / 0.6)))]
        if self.weather_name in WEATHER_MESSAGES and 0 <= T <= 1.8:
            draw_weather_text(img, (10, y0 + 24), line, self.font)
        else:
            draw_text(img, (10, y0 + 24), line, self.font, HP_RED if "拔群" in line else INK)
        if int(T * 4) % 2 == 0:
            cx, cy = W - 18, H - 10
            draw.polygon(((cx - 3, cy - 3), (cx + 3, cy - 3), (cx, cy)), fill=INK)


    def _cutin_frame(self, c: tuple, T: float) -> Image.Image:
        _, _, ci, ti, move, eff, dmg, mtype = c
        caster, target = self.by_idx[ci], self.by_idx[ti]
        img = Image.new("RGBA", (W, H), NIGHT + (255,))
        draw_cutin_stage(img, self.font, mtype)
        draw_cutin_sprites(img, self.front, self.pal,
                           caster.piece.species_id, target.piece.species_id)
        if T - c[0] > CUTIN_LEN - FPS_DT * 2:
            # 判定相位保持，白闪改为目标周围的四个十字，不覆盖精灵调色板。
            for x, y in ((24, 100), (88, 106), (33, 140), (83, 138)):
                draw_spark(img, x, y)
        draw_fx(ImageDraw.Draw(img), mtype, T, (c[0], ci), img=img)
        frac = max(0.0, self.units[ti].hp / target.max_hp)
        draw_nameplate(img, self.font, (9, 35, 135, 75), target.piece.name, frac)
        draw_nameplate(img, self.font, (108, 86, 230, 126), caster.piece.name,
                       self.units[ci].hp / caster.max_hp)
        if eff >= 2 and T - c[0] > 0.3:
            draw_effect_badge(img, self.font, "效果拔群！")
        if T - c[0] > CUTIN_LEN - FPS_DT * 3 and dmg:
            draw_small_number(img, (24, 206), f"-{dmg}", HP_LOW, scale=2)
        draw_message_window(img, self.font, (1, 269, 238, 318),
                            [(f"{caster.piece.name}的{skill_profile(caster.piece.species_id)['name']}！", INK),
                             ("气势十足的一击……", INK)])
        return img



def quantize_frames(frames: list) -> list:
    """固定调色板 + 无抖动量化（修扩散抖动导致的褪色）。"""
    counter = Counter()
    for f in frames:
        counter.update(f.getdata())
    palette = []
    for (r, g, b), _ in counter.most_common(255):
        palette.extend((r, g, b))
    palette.extend([0, 0, 0] * (256 - len(palette) // 3))
    pal_img = Image.new("P", (1, 1))
    pal_img.putpalette(palette)
    return [f.quantize(palette=pal_img, dither=Image.Dither.NONE)
            for f in frames]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--speed", type=float, default=1.)
    ap.add_argument("--out", type=Path, default=ROOT / "reports/evidence/battle-r1-2026-10-04")
    args = ap.parse_args()
    front, pal, font = Front(), Palettes(), Font16()
    roster = build_roster()

    def find(name):
        return next(p for ps in roster.values() for p in ps if p.name == name)

    comp_a = [find(n) for n in ("雷丘", "妙蛙花", "隆隆岩", "怪力", "水伊布")]
    comp_b = [find(n) for n in ("暴鲤龙", "喷火龙", "胡地", "大比鸟", "霸王花")]
    anim = BattleAnimation(comp_a, comp_b, args.seed, front, pal, font)

    t_end = max(e[0] for e in anim.events)
    # 结果与切镜数从原始事件读（游标状态会被分镜抽帧回卷，不可靠）
    result = next((e[2] for e in reversed(anim.events) if e[1] == "end"), None)
    n_casts = sum(1 for e in anim.events if e[1] == "cast")
    duration = t_end + 1.2 + (1.5 if result is not None else 0)

    banner = None
    if result is not None:  # 结算横幅预渲染一次，避免循环内回卷游标
        backdrop = copy.deepcopy(anim)
        backdrop._draw_ground_scars = lambda *_: None
        banner = backdrop.frame(t_end - FPS_DT).copy()
        d = ImageDraw.Draw(banner)
        y0 = H // 2 - 30
        pixel_window(banner, (20, y0, W - 20, y0 + 60))
        draw_text(banner, (84, y0 + 2), "战果", font, INK)
        who = "训练家 A" if result == 0 else (
            "训练家 B" if result == 1 else "平局")
        label = f"{who} 获胜" if result in (0, 1) else who
        draw_text(banner, ((W - text_width(label)) // 2, y0 + 29), label, font, INK)

    frames = []
    board_keys = {}
    playback = 0.0
    while playback <= anim.playback_clock.playback_time(duration, args.speed):
        T = anim.playback_clock.simulation_time(playback, args.speed)
        img = banner.copy() if (banner is not None and T > t_end + 0.6) \
            else anim.frame(T)
        frames.append(img.convert("RGB"))
        # 直接取实际输出的棋盘帧作分镜；不额外推进或回卷事件游标。
        if len(board_keys) < 6 and T <= t_end + 0.6 and not any(
                c[0] <= T < c[1] and 0.02 < (T - c[0]) / CUTIN_LEN < 0.98
                for c in anim.cutins):
            cues = (
                ("开战白闪", T < FPS_DT),
                ("步行留影", T >= OPENING_LIFE and any(
                    effect_frame(T - au.move_t0) == 1 and not au.dying(T)
                    for au in anim.units.values())),
                ("突进与命中", T >= OPENING_LIFE + FPS_DT and bool(anim._recent_hits(T))),
                ("蓄力金环", any(anim._casting_phase(au, T)
                                 for au in anim.units.values())),
                ("消失星光", any(au.die_t is not None and effect_frame(T - au.die_t) == 2
                               for au in anim.units.values())),
                ("大招落点", any(0 <= effect_frame(T - c[1]) < 3 for c in anim.cutins)),
            )
            for label, active in cues:
                if active and label not in board_keys:
                    board_keys[label] = frames[-1]
        playback += FPS_DT

    qframes = quantize_frames(frames)
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    scale_compare_image(front, pal, font).save(out / "scale_compare.png")
    qframes[0].save(out / "battle_anim.gif", save_all=True,
                    append_images=qframes[1:], duration=int(FPS_DT * 1000),
                    loop=0)
    big = [f.resize((W * 2, H * 2), Image.NEAREST) for f in qframes]
    big[0].save(out / "battle_anim_2x.gif", save_all=True, append_images=big[1:],
                duration=int(FPS_DT * 1000), loop=0)

    labels = [label for label in ("开战白闪", "步行留影", "突进与命中", "蓄力金环",
                                  "消失星光", "大招落点") if label in board_keys]
    keys = [board_keys[label] for label in labels]
    k, gap = 3, 10
    sw, sh = W * k, H * k
    board_img = Image.new("RGB", (len(keys) * sw + (len(keys) + 1) * gap,
                                  sh + 2 * gap + 16 * k), NIGHT)
    for i, (f, lab) in enumerate(zip(keys, labels)):
        x = gap + i * (sw + gap)
        board_img.paste(f.resize((sw, sh), Image.NEAREST), (x, gap))
        lab_img = Image.new("RGBA", (W, 16), NIGHT + (255,))
        draw_pixel_text(lab_img, (1, 4), str(i + 1), PAPER)
        draw_text(lab_img, (14, 0), lab, font, PAPER)
        lab_img = lab_img.resize((W * k, 16 * k), Image.NEAREST)
        board_img.paste(lab_img.convert("RGB"), (x, sh + gap + 4), None)
    board_img.save(out / "battle_storyboard.png")
    print(f"{out}/battle_anim.gif（{len(qframes)} 帧 @10fps，"
          f"{len(qframes) * FPS_DT:.1f}s，游标回放+固定调色板）+ _2x + 分镜图")
    print(f"战况：{n_casts} 次大招切镜，胜者 = {result}")


if __name__ == "__main__":
    main()
