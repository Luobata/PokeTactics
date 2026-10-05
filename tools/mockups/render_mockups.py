#!/usr/bin/env python3
"""240×320 GSC 风格视觉稿：准备 / 战斗 / 特写，保留原输出接口。

方案 C 已按 C-sym 重排棋盘分区（docs/10 §1.1，2026-09-14 sim 联动）：
敌备战 1 行 + 战场 2+2（对称）+ 我备战 1 行；敌/我备战行画观战格。
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
from decoders import Front, Font16, Palettes

W, H = 240, 320
CELL = 40
BOARD_FOOT = 30  # 34px 目标盒允许向上溢出 4px。
BOARD_X, BOARD_Y = 0, 28
HUD_H, SHOP_H = 28, 48

# 三色窗框 / 三色领地。属性色只占细环与小图标，原作精灵不改色。
INK = (41, 44, 53)          # #292C35
PAPER = (242, 232, 201)     # #F2E8C9
FRAME = (185, 173, 144)     # #B9AD90
NIGHT = (23, 29, 39)        # #171D27
SPOT = (61, 67, 70)        # #3D4346
HP_RED = (184, 72, 64)      # #B84840
HP_LOW = (216, 112, 88)     # #D87058
ENERGY = (181, 151, 79)     # #B5974F
GRASS_A, GRASS_B = (167, 179, 153), (157, 171, 142)
SAND_A, SAND_B = (204, 191, 154), (194, 180, 143)
GRASS_LINE, SAND_LINE = (132, 147, 121), (173, 158, 123)

TYPE_COLORS = {
    "NORMAL": FRAME, "FIRE": HP_RED, "WATER": (104, 139, 163),
    "GRASS": (116, 145, 100), "ELECTRIC": ENERGY, "ICE": (146, 174, 171),
    "FIGHTING": (165, 105, 84), "POISON": (151, 114, 145),
    "GROUND": (163, 139, 99), "FLYING": (146, 174, 171),
    "PSYCHIC": (151, 114, 145), "BUG": (116, 145, 100),
    "ROCK": (163, 139, 99), "GHOST": (120, 116, 149),
    "DRAGON": (120, 116, 149), "DARK": (124, 117, 108),
    "STEEL": (146, 174, 171),
}
TIER_COLORS = {1: FRAME, 2: TYPE_COLORS["GRASS"], 3: TYPE_COLORS["WATER"],
               4: TYPE_COLORS["GHOST"], 5: ENERGY}


def arena_dot(cx: int, cy: int, x: int, y: int, base: tuple) -> tuple:
    """每 16px 一个浅刻点；与砖缝共用第三色，不再铺满高对比斜纹。"""
    seam = SAND_LINE if base in (SAND_A, SAND_B) else GRASS_LINE
    return seam if ((x + cx * 8) % 16, (y + cy * 8) % 16) == (3, 3) else base

DIGITS = {
    "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    "3": ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
    "6": ["00110", "01000", "10000", "11110", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00010", "01100"],
    "-": ["00000", "00000", "00000", "01110", "00000", "00000", "00000"],
}
HEART = ["01010", "11111", "11111", "01110", "00100"]

# 原 16px 字库缺少部分 UI 字形；固定单色补字不依赖主机字体。
UI_GLYPHS = {
    "…": ["0000000000000000"] * 7 + ["0011001100110000"] * 2
         + ["0000000000000000"] * 7,
    "拔": ["0010000001000000", "0010000001010000", "0010000001001000",
           "1111101111111100", "0010000001000000", "0010000001000000",
           "0010100111111000", "0011000100001000", "0110000100010000",
           "1010000010010000", "0010000010100000", "0010000001000000",
           "0010000010100000", "0010000100010000", "0110001000001100",
           "0000000000000000"],
    "群": ["0000000001001000", "1111110000100000", "0001010000010000",
           "0001010011111100", "1111111000010000", "0001010000010000",
           "0001010000010000", "0111110011111100", "0100000000010000",
           "0111110000010000", "1100010000010000", "0100010111111110",
           "0100010000010000", "0111110000010000", "0100010000010000",
           "0000000000000000"],
}
# 战术日志补字来自固定 16px Songti SC Regular 栅格，与原字库保持单像素笔画。
# 放在通用绘字路径，避免仅天气开场提示能绘制、战斗日志却出现空格。
UI_GLYPHS.update({char: [f"{row:016b}" for row in rows] for char, rows in {
    "承": (0x0000, 0x1ff0, 0x0030, 0x0180, 0x0100, 0x796c, 0x0ff8, 0x1920,
           0x17d0, 0x1110, 0x3ff8, 0x210c, 0x4106, 0x0104, 0x0700, 0x0200),
    "晴": (0x0040, 0x0040, 0x7bfc, 0x4840, 0x4bfc, 0x4840, 0x7ffe, 0x4800,
           0x49f8, 0x4908, 0x49f8, 0x7908, 0x49f8, 0x4108, 0x0138, 0x0118),
    "雨": (0x0002, 0x7ffe, 0x0100, 0x2100, 0x3ffc, 0x2104, 0x2944, 0x2524,
           0x2104, 0x2d64, 0x2524, 0x2104, 0x211c, 0x2118, 0x0000, 0x0000),
    "雹": (0x0000, 0x0ffc, 0x0080, 0x1fff, 0x2086, 0x2080, 0x0eb8, 0x0c08,
           0x0808, 0x1fc8, 0x0848, 0x0fd8, 0x0812, 0x0807, 0x07fe, 0x0000),
}.items()})
PIXEL_LETTERS = {
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    "B": ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    "C": ["01111", "10000", "10000", "10000", "10000", "10000", "01111"],
    "D": ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    "F": ["11111", "10000", "10000", "11110", "10000", "10000", "10000"],
    "G": ["01111", "10000", "10000", "10111", "10001", "10001", "01111"],
    "H": ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
    "I": ["11111", "00100", "00100", "00100", "00100", "00100", "11111"],
    "J": ["00111", "00010", "00010", "00010", "10010", "10010", "01100"],
    "K": ["10001", "10010", "10100", "11000", "10100", "10010", "10001"],
    "L": ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    "M": ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
    "N": ["10001", "11001", "11001", "10101", "10011", "10011", "10001"],
    "O": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "P": ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    "Q": ["01110", "10001", "10001", "10001", "10101", "10010", "01101"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    "S": ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    "T": ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    "U": ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
    "V": ["10001", "10001", "10001", "10001", "10001", "01010", "00100"],
    "W": ["10001", "10001", "10001", "10101", "10101", "11011", "10001"],
    "X": ["10001", "10001", "01010", "00100", "01010", "10001", "10001"],
    "Y": ["10001", "10001", "01010", "00100", "00100", "00100", "00100"],
    "Z": ["11111", "00001", "00010", "00100", "01000", "10000", "11111"],
    "/": ["00001", "00001", "00010", "00100", "01000", "10000", "10000"],
    ".": ["00000", "00000", "00000", "00000", "00000", "00110", "00110"],
    ":": ["00000", "00100", "00100", "00000", "00100", "00100", "00000"],
    "+": ["00000", "00100", "00100", "11111", "00100", "00100", "00000"],
    "%": ["11001", "11001", "00010", "00100", "01000", "10011", "10011"],
}


def text_width(text):
    return sum(4 if ch == " " else 8 if ch.isascii() else 16 for ch in text)


def wrap_text(text, width):
    lines, line = [], ""
    for ch in text:
        if line and text_width(line + ch) > width:
            lines.append(line)
            line = ""
        line += ch
    if line:
        lines.append(line)
    return lines


def draw_text(img: Image, xy, s: str, font: Font16, color=INK) -> None:
    layer = Image.new("RGBA", (max(1, text_width(s)), 16))
    draw = ImageDraw.Draw(layer)
    offset = 0
    for ch in s:
        if ch in UI_GLYPHS:
            for y, row in enumerate(UI_GLYPHS[ch]):
                for x, bit in enumerate(row):
                    if bit == "1":
                        draw.point((offset + x, y), fill=color)
        elif ch.isascii():
            draw_pixel_text(layer, (offset + 1, 5), ch, color)
        else:
            layer.alpha_composite(font.text(ch, color), (offset, 0))
        offset += text_width(ch)
    img.alpha_composite(layer, tuple(map(int, xy)))


def draw_pixel_text(img, xy, text, color=INK, scale=1):
    draw = ImageDraw.Draw(img)
    x0, y0 = map(int, xy)
    for i, ch in enumerate(text.upper()):
        glyph = DIGITS.get(ch, PIXEL_LETTERS.get(ch, []))
        for y, row in enumerate(glyph):
            for x, bit in enumerate(row):
                if bit == "1":
                    xx, yy = x0 + (i * 6 + x) * scale, y0 + y * scale
                    draw.rectangle((xx, yy, xx + scale - 1, yy + scale - 1), fill=color)


def pixel_window(img, box, dark=False):
    """切角 1px，外线 / 米色隔缝 / 内线，全部在整数像素上落笔。"""
    x0, y0, x1, y1 = map(int, box)
    draw = ImageDraw.Draw(img)
    bg, border = (INK, PAPER) if dark else (PAPER, INK)
    draw.rounded_rectangle((x0, y0, x1, y1), radius=3, fill=bg, outline=border)
    draw.rounded_rectangle((x0 + 2, y0 + 2, x1 - 2, y1 - 2), radius=1,
                           outline=FRAME if dark else INK)


def draw_small_number(img: Image, xy, s: str, color, scale: int = 2,
                      shadow: bool = True) -> None:
    """5×7 数字；战斗数字使用带底影的切角牌，HUD 数字交给外层容器。"""
    color = {(255, 255, 255): PAPER, (255, 220, 60): ENERGY,
             (255, 90, 70): HP_LOW}.get(color, color)
    width, height = max(1, (len(s) * 6 - 1) * scale), 7 * scale
    x, y = map(int, xy)
    if shadow:
        x = max(5, min(img.width - width - 6, x))
        y = max(5, min(img.height - height - 7, y))
        draw = ImageDraw.Draw(img)
        draw.rectangle((x - 3, y - 2, x + width + 4, y + height + 5), fill=INK)
        draw.rounded_rectangle((x - 4, y - 4, x + width + 3, y + height + 2),
                               radius=2, fill=INK, outline=FRAME)
    draw_pixel_text(img, (x, y), s, color, scale)


def draw_heart(img: Image, xy, color=HP_RED, scale: int = 2) -> None:
    draw = ImageDraw.Draw(img)
    x0, y0 = xy
    for y, row in enumerate(HEART):
        for x, bit in enumerate(row):
            if bit == "1":
                xx, yy = x0 + x * scale, y0 + y * scale
                draw.rectangle((xx, yy, xx + scale - 1, yy + scale - 1), fill=color)


def draw_coin(img, x, y, color=ENERGY):
    draw = ImageDraw.Draw(img)
    draw.ellipse((x, y, x + 7, y + 7), fill=color, outline=INK)
    draw.line((x + 3, y + 2, x + 3, y + 5), fill=PAPER)


def draw_meter(img, x, y, width, frac, color=HP_RED, height=5):
    """深槽、浅端帽；空条不留下伪造的 1px 血量。"""
    x, y, width = int(x), int(y), int(width)
    draw = ImageDraw.Draw(img)
    draw.rectangle((x, y, x + width - 1, y + height - 1), fill=INK)
    draw.line((x, y + 1, x, y + height - 2), fill=PAPER)
    draw.line((x + width - 1, y + 1, x + width - 1, y + height - 2), fill=PAPER)
    fill = int((width - 4) * min(1.0, max(0.0, frac)))
    if fill:
        draw.rectangle((x + 2, y + 1, x + 1 + fill, y + height - 2), fill=color)


def draw_meters(img, x, y, width, hp, energy, hp_color=HP_RED, energy_color=ENERGY):
    draw_meter(img, x, y, width, hp, hp_color, height=4)
    draw_meter(img, x, y + 5, width, energy or 0, energy_color, height=4)


def board_sprite_size(tier):
    return 34 if tier == 3 else 32


def scale_sprite(source, palette, size):
    """面积平均后按 RGB 平方距离吸附到物种四原色；覆盖率半数取整。

    RGBA BOX 使用预乘 alpha，透明背景不污染边缘 RGB。量化不抖动，
    alpha 收为 0/255，防止半透明边缘与地砖再次混色。
    """
    averaged = source.resize(size, Image.Resampling.BOX)
    colors = tuple(tuple(c) for c in palette)
    mapped = {}
    for _, rgba in averaged.getcolors(averaged.width * averaged.height):
        rgb, alpha = rgba[:3], rgba[3]
        nearest = min(colors, key=lambda c: sum((a - b) ** 2 for a, b in zip(rgb, c)))
        mapped[rgba] = nearest + (255 if alpha >= 128 else 0,)
    sprite = Image.new("RGBA", size)
    pixels = averaged.load()
    sprite.putdata([mapped[pixels[x, y]] for y in range(size[1]) for x in range(size[0])])
    return sprite


def scale_compare_image(front, pal, font):
    """同一 56px 喷火龙：原生尺寸与统一 4× 像素放大，供人眼比对。"""
    source = front.image(6, pal)
    if source.size != (56, 56):
        raise ValueError("scale_compare requires a 56px source")
    samples = (source.resize((28, 28), Image.Resampling.NEAREST),
               scale_sprite(source, pal.for_species(6), (34, 34)), source)
    img = Image.new("RGBA", (744, 452), NIGHT + (255,))
    draw_text(img, (12, 12), "喷火龙 · 精灵缩放对比", font, PAPER)
    for i, (sprite, title, label) in enumerate(zip(
            samples, ("第4期", "第5期", "原尺寸"),
            ("28 PX / NEAREST", "34 PX / BOX+PAL", "56 PX / SOURCE"))):
        x = 12 + i * 244
        pixel_window(img, (x, 44, x + 231, 439))
        draw_text(img, (x + 8, 52), title, font, INK)
        draw_pixel_text(img, (x + 8, 76), label, INK)
        draw_pixel_text(img, (x + 8, 146), "1X", INK)
        draw_pixel_text(img, (x + 8, 174), "4X", INK)
        img.alpha_composite(sprite, (x + (232 - sprite.width) // 2, 140 - sprite.height))
        enlarged = sprite.resize((sprite.width * 4, sprite.height * 4), Image.Resampling.NEAREST)
        img.alpha_composite(enlarged, (x + (232 - enlarged.width) // 2, 424 - enlarged.height))
    return img.convert("RGB")


def draw_floor_tile(img, x, y, size, cx, cy, enemy, bench=False):
    draw = ImageDraw.Draw(img)
    if bench:
        draw.rectangle((x, y, x + size - 1, y + size - 1), fill=INK)
        draw.rounded_rectangle((x + 3, y + 4, x + size - 4, y + size - 3),
                               radius=2, fill=SPOT, outline=FRAME)
        return
    a, b = (SAND_A, SAND_B) if enemy else (GRASS_A, GRASS_B)
    seam = SAND_LINE if enemy else GRASS_LINE
    base = a if (cx + cy) % 2 == 0 else b
    draw.rectangle((x, y, x + size - 1, y + size - 1), fill=base)
    draw.line((x, y + size - 1, x, y, x + size - 1, y), fill=seam)
    # 小刻痕只在砖角，中央留给原作精灵。
    for yy in range(3, size - 3, 16):
        for xx in range(3, size - 3, 16):
            draw.point((x + xx, y + yy), fill=arena_dot(cx, cy, xx, yy, base))
    draw.line((x + size - 5, y + size - 3, x + size - 3, y + size - 3), fill=seam)


def cell_bg(img: Image, cx: int, cy: int, enemy: bool, bench: bool) -> None:
    draw_floor_tile(img, BOARD_X + cx * CELL, BOARD_Y + cy * CELL,
                    CELL, cx, cy, enemy, bench)


def draw_divider(img, x, y, width):
    draw = ImageDraw.Draw(img)
    draw.rectangle((x, y - 2, x + width - 1, y + 1), fill=INK)
    draw.line((x + 1, y - 1, x + width - 2, y - 1), fill=FRAME)
    for xx in (x + 8, x + width // 2, x + width - 9):
        draw.polygon(((xx, y - 3), (xx + 3, y), (xx, y + 3), (xx - 3, y)),
                     fill=PAPER, outline=INK)


def draw_base(img, x, foot, width, types, tier, casting=False):
    draw = ImageDraw.Draw(img)
    x, foot = int(x), int(foot)
    draw.ellipse((x + 1, foot - 2, x + width - 2, foot + 7), fill=INK)
    draw.ellipse((x + 2, foot - 4, x + width - 3, foot + 4), fill=FRAME, outline=INK)
    draw.ellipse((x + 4, foot - 3, x + width - 5, foot + 2),
                 fill=INK, outline=PAPER if casting else TYPE_COLORS[types[0]])
    if len(types) > 1:
        draw.arc((x + 7, foot - 2, x + width - 8, foot + 1), 0, 180,
                 fill=TYPE_COLORS[types[1]])
    # 费用从四角彩点改为底座前沿的 1–5 颗铆钉，可数也可辨色。
    start = x + (width - (tier * 3 - 1)) // 2
    for i in range(tier):
        draw.line((start + i * 3, foot + 4, start + i * 3 + 1, foot + 4),
                  fill=TIER_COLORS[tier])


def draw_cursor(img, x, y, size):
    draw = ImageDraw.Draw(img)
    for dx, dy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
        xx = x + 2 if dx == 1 else x + size - 3
        yy = y + 2 if dy == 1 else y + size - 3
        pts = ((xx + 6 * dx, yy), (xx, yy), (xx, yy + 6 * dy))
        draw.line(pts, fill=INK, width=3)
        draw.line(pts, fill=PAPER, width=1)


def draw_piece(img: Image, front: Front, pal: Palettes, font: Font16,
               pid: int, types: tuple, tier: int, cx: int, cy: int,
               hp_frac: float = None, energy_frac: float = None,
               selected: bool = False, casting: bool = False) -> None:
    x, y = BOARD_X + cx * CELL, BOARD_Y + cy * CELL
    foot = y + BOARD_FOOT
    draw_base(img, x + 1, foot, CELL - 2, types, tier, casting)
    box = board_sprite_size(tier)
    sprite = scale_sprite(front.image(pid, pal), pal.for_species(pid), (box, box))
    bounds = sprite.getbbox()
    lift = min(2, BOARD_FOOT - (bounds[3] - bounds[1]) + 4) if casting else 0
    img.alpha_composite(sprite, (x + (CELL - sprite.width) // 2,
                                 foot - bounds[3] - lift))
    if hp_frac is not None:
        draw_meters(img, x + 3, y + BOARD_FOOT, CELL - 6, hp_frac, energy_frac)
    if selected:
        draw_cursor(img, x, y, CELL)
    if casting:
        draw_spark(img, x + CELL // 2, foot - bounds[3] - 5, PAPER)


def draw_spark(img, x, y, color=PAPER):
    draw = ImageDraw.Draw(img)
    x, y = int(x), int(y)
    draw.line((x - 3, y, x + 3, y), fill=INK, width=3)
    draw.line((x, y - 3, x, y + 3), fill=INK, width=3)
    draw.line((x - 3, y, x + 3, y), fill=color)
    draw.line((x, y - 3, x, y + 3), fill=color)


def draw_hud(img: Image, font: Font16, hp: int, gold: int, level: int,
             rnd: int, right: str = "") -> None:
    ImageDraw.Draw(img).rectangle((0, 0, W - 1, HUD_H - 1), fill=INK)
    for box in ((1, 2, 48, 25), (50, 2, 99, 25), (101, 2, 141, 25),
                (143, 2, 195, 25), (197, 2, 238, 25)):
        pixel_window(img, box)
    draw_heart(img, (7, 10), scale=1)
    draw_small_number(img, (20, 10), str(hp), INK, scale=1, shadow=False)
    draw_coin(img, 56, 9)
    draw_small_number(img, (74, 10), str(gold), INK, scale=1, shadow=False)
    draw_pixel_text(img, (108, 10), f"L{level}")
    draw_pixel_text(img, (151, 10), f"R {rnd}")
    if right == "▶":
        ImageDraw.Draw(img).polygon(((213, 9), (220, 13), (213, 18)), fill=INK)
    elif right == "2x":
        draw_pixel_text(img, (211, 10), "2X")
    elif right:
        draw_text(img, (209, 6), "备", font)


def draw_shop(img: Image, front: Front, pal: Palettes, font: Font16,
              offers: list) -> None:
    """40px 固定槽：原尺寸精灵的头像窗口 + 价格底栏，窗口外不溢出。"""
    y0 = H - SHOP_H
    ImageDraw.Draw(img).rectangle((0, y0, W - 1, H - 1), fill=INK)
    for i, (pid, tier, price) in enumerate(offers):
        x = i * 40
        pixel_window(img, (x + 1, y0 + 1, x + 38, H - 2))
        portrait = Image.new("RGBA", (32, 28), PAPER + (255,))
        sprite = front.image(pid, pal)
        box = sprite.getbbox()
        # 原图不缩小、不改色：如图鉴头像，仅视窗裁去下身与边缘。
        portrait.alpha_composite(sprite, ((32 - sprite.width) // 2, 1 - box[1]))
        img.alpha_composite(portrait, (x + 4, y0 + 4))
        draw = ImageDraw.Draw(img)
        draw.line((x + 4, y0 + 33, x + 35, y0 + 33), fill=FRAME)
        draw_coin(img, x + 9, y0 + 36)
        draw_small_number(img, (x + 22, y0 + 36), str(price), INK, scale=1, shadow=False)
        draw.point((x + 34, y0 + 37), fill=TIER_COLORS[tier])
    for j in range(2):
        y = y0 + 1 + j * 23
        pixel_window(img, (201, y, 238, y + 21))
        draw = ImageDraw.Draw(img)
        if j == 0:
            draw.arc((207, y + 6, 216, y + 15), 45, 310, fill=INK)
            draw.polygon(((215, y + 4), (215, y + 9), (211, y + 7)), fill=INK)
        else:
            draw.line((211, y + 7, 211, y + 15), fill=INK, width=2)
            draw.line((207, y + 11, 211, y + 7, 215, y + 11), fill=INK)
        draw_small_number(img, (224, y + 7), str(2 if j == 0 else 4), INK,
                          scale=1, shadow=False)


def board_frame(img: Image) -> None:
    draw_divider(img, BOARD_X, BOARD_Y + 3 * CELL, 6 * CELL)
    draw = ImageDraw.Draw(img)
    draw.line((0, BOARD_Y - 1, W - 1, BOARD_Y - 1), fill=INK)
    draw.line((0, BOARD_Y + 6 * CELL, W - 1, BOARD_Y + 6 * CELL), fill=INK)


def draw_message_window(img, font, box, lines, cursor=True):
    pixel_window(img, box)
    x0, y0, x1, y1 = box
    row = y0 + 7
    for text, color in lines:
        for line in wrap_text(text, x1 - x0 - 22):
            if row + 15 > y1 - 5:
                return
            draw_text(img, (x0 + 10, row), line, font, color)
            row += 18
    if cursor:
        d = ImageDraw.Draw(img)
        d.polygon(((x1 - 14, y1 - 10), (x1 - 8, y1 - 10),
                   (x1 - 11, y1 - 7)), fill=INK)


def screen_prep(front: Front, pal: Palettes, font: Font16) -> Image.Image:
    """C-sym 准备页：敌备战 1 + 战场 2+2 + 我备战 1，底部商店 48px。

    棋盘分区已按 C-sym 重排（2026-09-14 sim 联动）；敌备战行的「上轮
    快照」内容与 4 格动作条（商店 4 + 刷新/经验/开战）随 SHOP_SLOTS 联动
    与第四期美术上稿（M4 验收清单 #13），本稿暂维持 5 格动作条与棋子摆样。
    """
    img = Image.new("RGBA", (W, H), INK + (255,))
    for cy in range(6):
        for cx in range(6):
            cell_bg(img, cx, cy, enemy=cy in (1, 2), bench=cy in (0, 5))
    board_frame(img)
    for cx, pid, types, tier in (
            (1, 19, ("NORMAL",), 1), (2, 10, ("BUG",), 1),
            (3, 63, ("PSYCHIC",), 1), (4, 92, ("GHOST", "POISON"), 2)):
        draw_piece(img, front, pal, font, pid, types, tier, cx, 2)
    draw_piece(img, front, pal, font, 16, ("NORMAL", "FLYING"), 1, 0, 1)
    draw_piece(img, front, pal, font, 4, ("FIRE",), 1, 2, 3)
    for cx, pid, types, tier, selected in (
            (1, 25, ("ELECTRIC",), 1, False), (2, 1, ("GRASS", "POISON"), 1, False),
            (3, 74, ("ROCK", "GROUND"), 2, True), (4, 66, ("FIGHTING",), 2, False)):
        draw_piece(img, front, pal, font, pid, types, tier, cx, 4, selected=selected)
    draw_piece(img, front, pal, font, 63, ("PSYCHIC",), 2, 1, 5)
    draw_piece(img, front, pal, font, 129, ("WATER",), 1, 4, 5)
    # 空白敌方后场容纳选中信息，4px 棋盘/商店缝只做结构分隔。
    pixel_window(img, (108, 36, 229, 73))
    draw_text(img, (116, 41), "小拳石", font)
    draw_pixel_text(img, (181, 46), "02 G")
    draw_pixel_text(img, (117, 61), "ROCK / GROUND", INK)
    draw_shop(img, front, pal, font, [(1, 1, 1), (25, 1, 1), (41, 1, 1),
                                     (74, 2, 2), (95, 1, 1)])
    draw_hud(img, font, hp=34, gold=13, level=5, rnd=12, right="羁")
    return img


def screen_battle(front: Front, pal: Palettes, font: Font16) -> Image.Image:
    """C-sym 战斗页：备战行画观战格（敌行战斗期揭示真实备战、我行显示
    替补——静态稿留空），战场 2+2 与 sim 战斗网格同构。"""
    img = Image.new("RGBA", (W, H), INK + (255,))
    for cy in range(6):
        for cx in range(6):
            cell_bg(img, cx, cy, enemy=cy in (1, 2), bench=cy in (0, 5))
    board_frame(img)
    for cx, pid, types, tier, hp, en in (
            (1, 20, ("NORMAL",), 1, 0.35, 0.6),
            (3, 64, ("PSYCHIC",), 2, 0.8, 1.0),
            (4, 93, ("GHOST", "POISON"), 2, 0.55, 0.3)):
        draw_piece(img, front, pal, font, pid, types, tier, cx, 2, hp, en)
    draw_piece(img, front, pal, font, 5, ("FIRE",), 2, 2, 3, 0.5, 0.1)
    for cx, pid, types, tier, hp, en in (
            (1, 26, ("ELECTRIC",), 2, 0.9, 1.0), (2, 2, ("GRASS", "POISON"), 2, 0.7, 0.4),
            (3, 75, ("ROCK", "GROUND"), 2, 0.45, 0.2), (4, 67, ("FIGHTING",), 2, 0.62, 0.8)):
        draw_piece(img, front, pal, font, pid, types, tier, cx, 4, hp, en,
                   casting=cx == 1)
    draw_small_number(img, (119, 71), "-23", PAPER, scale=1)
    draw_small_number(img, (192, 145), "-78", ENERGY, scale=1)
    draw_small_number(img, (80, 234), "-156", HP_LOW, scale=2)
    draw_message_window(img, font, (1, 273, 238, 318),
                        [("雷丘的十万伏特！", INK), ("效果拔群！", HP_RED)])
    draw_hud(img, font, hp=34, gold=13, level=5, rnd=12, right="2x")
    return img


def draw_cutin_stage(img, font, mtype="ELECTRIC"):
    """三阶像素渐晕与两块舞台光斑；没有平滑渐变或精灵滤镜。"""
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, W - 1, H - 1), fill=NIGHT)
    draw.ellipse((-30, 27, 276, 274), fill=INK)
    draw.polygon(((38, 81), (94, 81), (220, 230), (107, 245)), fill=SPOT)
    for x, y, width in ((16, 143, 80), (100, 243, 126)):
        draw.ellipse((x - 1, y - 6, x + width + 1, y + 7), fill=NIGHT)
        draw.ellipse((x, y - 8, x + width, y + 4), fill=FRAME, outline=INK)
        draw.arc((x + 5, y - 6, x + width - 5, y + 1), 0, 180, fill=PAPER)
    pixel_window(img, (8, 5, 231, 26), dark=True)
    type_zh = {"NORMAL": "一般", "FIRE": "火", "WATER": "水", "GRASS": "草",
               "ELECTRIC": "电", "ICE": "冰", "FIGHTING": "格斗", "POISON": "毒",
               "GROUND": "地面", "FLYING": "飞行", "PSYCHIC": "超能", "BUG": "虫",
               "ROCK": "岩石", "GHOST": "幽灵", "DRAGON": "龙", "DARK": "恶",
               "STEEL": "钢"}
    draw_text(img, (17, 5), "招式特写", font, PAPER)
    label = type_zh.get(mtype, mtype) + "属性"
    draw_text(img, (223 - 16 * len(label), 5), label, font, FRAME)


def draw_nameplate(img, font, box, name, hp, level=None):
    pixel_window(img, box)
    x, y, x1, _ = box
    draw_text(img, (x + 8, y + 5), name, font)
    if level is not None:
        draw_pixel_text(img, (x1 - 29, y + 10), f"L{level}")
    draw_pixel_text(img, (x + 8, y + 27), "HP", INK)
    draw_meter(img, x + 25, y + 27, x1 - x - 33, hp, height=6)


def draw_cutin_sprites(img, front, pal, caster_pid, target_pid, target_lift=0):
    target = front.image(target_pid, pal)
    tb = target.getbbox()
    img.alpha_composite(target, (56 - target.width // 2, 144 - tb[3] - target_lift))
    caster = front.image(caster_pid, pal)
    # 只作整数像素复制的 2× 展示，不插值、不重采样形状、不改调色板。
    caster = caster.resize((caster.width * 2, caster.height * 2), Image.Resampling.NEAREST)
    cb = caster.getbbox()
    img.alpha_composite(caster, (166 - caster.width // 2, 242 - cb[3]))


def draw_effect_badge(img, font, text):
    pixel_window(img, (9, 170, 100, 194))
    draw_text(img, (15, 174), text, font, HP_RED)


def screen_cutin(front: Front, pal: Palettes, font: Font16) -> Image.Image:
    img = Image.new("RGBA", (W, H), NIGHT + (255,))
    draw_cutin_stage(img, font)
    draw_cutin_sprites(img, front, pal, 25, 130)
    draw = ImageDraw.Draw(img)
    bolt = ((154, 180), (122, 154), (131, 150), (86, 126), (97, 121), (55, 110))
    draw.line(bolt, fill=INK, width=5)
    draw.line(bolt, fill=ENERGY, width=3)
    draw.line(bolt, fill=PAPER)
    draw_spark(img, 48, 97)
    draw_nameplate(img, font, (9, 35, 135, 75), "暴鲤龙", 0.22, 5)
    draw_nameplate(img, font, (108, 86, 230, 126), "皮卡丘", 0.88, 5)
    draw_effect_badge(img, font, "效果拔群！")
    draw_small_number(img, (24, 206), "-204", HP_LOW, scale=2)
    draw_message_window(img, font, (1, 269, 238, 318),
                        [("皮卡丘的十万伏特！", INK), ("雷光击穿了水面……", INK)])
    return img


def main() -> None:
    front, pal, font = Front(), Palettes(), Font16()
    out = Path(__file__).resolve().parent.parent.parent / "docs" / "design" / "mockups"
    out.mkdir(parents=True, exist_ok=True)
    screens = []
    for name, fn in (("prep", screen_prep), ("battle", screen_battle),
                     ("cutin", screen_cutin)):
        img = fn(front, pal, font)
        screens.append((name, img))
        img.save(out / f"{name}_240x320.png")
        img.resize((W * 2, H * 2), Image.NEAREST).save(out / f"{name}_2x.png")
        img.resize((W * 6, H * 6), Image.NEAREST).save(out / f"{name}_hd6x.png")
        print(f"docs/design/mockups/{name}_240x320.png (+2x, +hd6x {W*6}x{H*6})")

    # 三屏总览（4x 并排 + 标签），用于一次性评审/分享
    k, gap, label_h = 4, 12, 0
    labels = {"prep": "准备画面", "battle": "战斗画面", "cutin": "招式特写"}
    ov_w = len(screens) * W * k + (len(screens) + 1) * gap
    ov_h = H * k + gap * 2 + 16 * k  # 标签区 = 16px 字 × k
    overview = Image.new("RGBA", (ov_w, ov_h), NIGHT + (255,))
    for i, (name, img) in enumerate(screens):
        x = gap + i * (W * k + gap)
        big = img.resize((W * k, H * k), Image.NEAREST)
        overview.alpha_composite(big, (x, gap))
        label = font.text(labels[name], PAPER)
        label = label.resize((label.width * k, label.height * k), Image.NEAREST)
        overview.alpha_composite(label, (x, gap + H * k + 6 * k // 2))
    overview.save(out / "overview_4x.png")
    print(f"docs/design/mockups/overview_4x.png ({ov_w}x{ov_h})")
    print("8px 数字小字库原型：5×7 双倍渲染 = 10×14，三种语义色已上稿")


if __name__ == "__main__":
    main()
