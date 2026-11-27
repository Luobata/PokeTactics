"""Draw the installable-app icons for /play (docs/72).

Original artwork (no franchise imagery): a forest-green tile with a 4x4 tactics
board and a gold star piece. Re-run after changing the design:

    python3 tools/acceptance/make_pwa_icons.py

Writes tools/acceptance/pwa/{icon-192,icon-512,icon-maskable-512,apple-touch-icon}.png.
Needs Pillow (the same dependency as the battle renderer fallback).
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent / "pwa"
SIZE = 1024
BG_TOP, BG_BOTTOM = (36, 66, 54), (18, 34, 29)
TILE_LIGHT, TILE_DARK = (122, 196, 170), (70, 142, 122)
ENEMY_LIGHT, ENEMY_DARK = (226, 184, 132), (186, 136, 88)
GOLD, GOLD_DARK = (255, 206, 84), (196, 132, 28)


def _gradient(size: int) -> Image.Image:
    img = Image.new("RGB", (size, size))
    px = img.load()
    for y in range(size):
        k = y / (size - 1)
        row = tuple(round(a + (b - a) * k) for a, b in zip(BG_TOP, BG_BOTTOM))
        for x in range(size):
            px[x, y] = row
    return img


def _star(cx: float, cy: float, r_out: float, r_in: float) -> list[tuple[float, float]]:
    points = []
    for i in range(10):
        r = r_out if i % 2 == 0 else r_in
        a = -math.pi / 2 + i * math.pi / 5
        points.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return points


def artwork(safe: float) -> Image.Image:
    """Full-bleed square; the board and star stay inside `safe` (fraction of the side)."""
    img = _gradient(SIZE).convert("RGBA")
    draw = ImageDraw.Draw(img)
    span = SIZE * safe
    board = span * 0.78
    x0 = (SIZE - board) / 2
    y0 = (SIZE - board) / 2 + span * 0.05
    cell = board / 4
    # soft drop shadow under the board
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (x0 - cell * 0.12, y0 + cell * 0.1, x0 + board + cell * 0.12, y0 + board + cell * 0.32),
        radius=cell * 0.35, fill=(0, 0, 0, 110))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(SIZE * 0.02)))
    draw.rounded_rectangle((x0 - cell * 0.12, y0 - cell * 0.12, x0 + board + cell * 0.12, y0 + board + cell * 0.12),
                           radius=cell * 0.3, fill=(92, 64, 40))
    for row in range(4):
        for col in range(4):
            enemy = row < 2
            light = (row + col) % 2 == 0
            color = (ENEMY_LIGHT if light else ENEMY_DARK) if enemy else (TILE_LIGHT if light else TILE_DARK)
            pad = cell * 0.045
            draw.rounded_rectangle((x0 + col * cell + pad, y0 + row * cell + pad,
                                    x0 + (col + 1) * cell - pad, y0 + (row + 1) * cell - pad),
                                   radius=cell * 0.14, fill=color)
    # glowing centre line between the two halves
    draw.rectangle((x0, y0 + 2 * cell - cell * 0.035, x0 + board, y0 + 2 * cell + cell * 0.035), fill=GOLD)
    # the gold piece: a star standing on the player's front row
    cx, cy = x0 + board * 0.5, y0 + board * 0.5 + cell * 0.05
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((cx - cell * 1.25, cy - cell * 1.25, cx + cell * 1.25, cy + cell * 1.25),
                                 fill=(255, 220, 120, 120))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(SIZE * 0.035)))
    draw = ImageDraw.Draw(img)
    draw.polygon(_star(cx + cell * 0.04, cy + cell * 0.07, cell * 1.08, cell * 0.46), fill=GOLD_DARK)
    draw.polygon(_star(cx, cy, cell * 1.08, cell * 0.46), fill=GOLD)
    draw.polygon(_star(cx - cell * 0.12, cy - cell * 0.12, cell * 0.42, cell * 0.18), fill=(255, 244, 200))
    return img


def rounded(img: Image.Image, radius: float) -> Image.Image:
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, img.width - 1, img.height - 1), radius=radius, fill=255)
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def main() -> None:
    OUT.mkdir(exist_ok=True)
    regular = rounded(artwork(0.92), SIZE * 0.2)
    maskable = artwork(0.72)          # Android masks keep the inner 80% circle
    apple = artwork(0.86).convert("RGB")  # iOS rounds corners itself and dislikes alpha
    for name, img, size in (("icon-192.png", regular, 192), ("icon-512.png", regular, 512),
                            ("icon-maskable-512.png", maskable, 512), ("apple-touch-icon.png", apple, 180)):
        img.resize((size, size), Image.LANCZOS).save(OUT / name, optimize=True)
        print("wrote", OUT / name)


if __name__ == "__main__":
    main()
