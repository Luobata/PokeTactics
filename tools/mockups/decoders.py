"""PokeWalk 素材解码器（设计稿渲染用）。

解码 ../ESP32-PokemonGo/assets/ 下的三个二进制格式为 PIL 图像：
- gen1_front.bin (FRNT)：151 张正面精灵，2bpp，分 40/48/56 三段；
- palettes.bin (PALS)：146 套普通 + 146 套闪光 × 4 色 RGB565 + 每只索引；
- font16.bin (FNT1)：16×16 1bpp 中文点阵 + 码点表。

仅设计稿工具链使用（tools/），允许依赖 Pillow——sim/ 层的零依赖宪法不适用于此
（PokeWalk 先例：素材管线用 Pillow，运行时不用）。
"""

import struct
from pathlib import Path

from PIL import Image

# PokeTactics/tools/mockups/ -> 上三级到 luobata/，再进 ESP32-PokemonGo/assets
POKEWALK = Path(__file__).resolve().parent.parent.parent.parent / "ESP32-PokemonGo" / "assets"


def _rgb565(v: int) -> tuple:
    r, g, b = (v >> 11) & 31, (v >> 5) & 63, v & 31
    return (r * 255 // 31, g * 255 // 63, b * 255 // 31)


class Front:
    """FRNT：头 <4sHH，段目录 <HHII>×n（size, per, count, offset），记录 = u16 id + per 字节。"""

    def __init__(self, path: Path = None) -> None:
        d = (path or POKEWALK / "gen1_front.bin").read_bytes()
        magic, ver, nseg = struct.unpack("<4sHH", d[:8])
        assert magic == b"FRNT", magic
        segs, p = [], 8
        for _ in range(nseg):
            size, per, n, doff = struct.unpack("<HHII", d[p:p + 12])
            segs.append((size, per, n, doff))
            p += 12
        self.size_of = {}   # id -> 边长
        self.blob_of = {}   # id -> 2bpp 字节
        for size, per, n, doff in segs:
            q = p + doff
            for _ in range(n):
                (pid,) = struct.unpack("<H", d[q:q + 2])
                self.size_of[pid] = size
                self.blob_of[pid] = d[q + 2:q + 2 + per]
                q += 2 + per

    def image(self, pid: int, pal: "Palettes", shiny: bool = False) -> Image.Image:
        """解码为 RGBA。映射与固件 render.c 一致：色号 3 = 透明，0-2 -> 调色板前 3 色。"""
        size = self.size_of[pid]
        blob = self.blob_of[pid]
        colors = pal.for_species(pid, shiny)  # [c0, c1, c2, (c3 备用)]
        img = Image.new("RGBA", (size, size))
        px = img.load()
        for y in range(size):
            for x in range(size):
                bit = y * size + x
                byte = blob[bit // 4]
                idx = (byte >> (6 - 2 * (bit % 4))) & 3
                if idx != 3:
                    px[x, y] = colors[idx] + (255,)
        return img


class Palettes:
    """PALS：头 <4sHHHH>（nsets, ncolors, count）+ (2×nsets) 套 ×4 色 + count 字节索引。"""

    def __init__(self, path: Path = None) -> None:
        d = (path or POKEWALK / "palettes.bin").read_bytes()
        magic, ver, nsets, ncolors, count = struct.unpack("<4sHHHH", d[:12])
        assert magic == b"PALS", magic
        body = d[12:]
        set_bytes = ncolors * 2
        self.nsets, self.count = nsets, count
        self._sets = []
        for i in range(2 * nsets):
            off = i * set_bytes
            self._sets.append([_rgb565(struct.unpack("<H", body[off + 2 * c:off + 2 * c + 2])[0])
                               for c in range(ncolors)])
        self._map = body[2 * nsets * set_bytes:2 * nsets * set_bytes + count]

    def for_species(self, pid: int, shiny: bool = False) -> list:
        base = self._map[pid - 1] + (self.nsets if shiny else 0)
        return self._sets[base]


class Font16:
    """FNT1：头 <4sHHHI>（size, per, count）+ count×u16 码点 + count×per 字节 1bpp 行主序。"""

    def __init__(self, path: Path = None) -> None:
        d = (path or POKEWALK / "font16.bin").read_bytes()
        magic, ver, size, per, count = struct.unpack("<4sHHHI", d[:14])
        assert magic == b"FNT1", magic
        self.size, self.count = size, count
        self._glyph = {}
        for i in range(count):
            cp = struct.unpack("<H", d[14 + 2 * i:16 + 2 * i])[0]
            self._glyph[chr(cp)] = d[14 + 2 * count + i * per:(14 + 2 * count) + (i + 1) * per]

    def text(self, s: str, color=(24, 24, 24), bg=None) -> Image.Image:
        """渲染一行文本为 RGBA 图像；缺字渲染为空格。1bpp MSB-first。"""
        w = self.size * len(s)
        img = Image.new("RGBA", (w, self.size), bg and bg + (255,) or (0, 0, 0, 0))
        px = img.load()
        for i, ch in enumerate(s):
            blob = self._glyph.get(ch)
            if not blob:
                continue
            for y in range(self.size):
                row = blob[y * 2:y * 2 + 2]
                for x in range(self.size):
                    if (row[x // 8] >> (7 - x % 8)) & 1:
                        px[i * self.size + x, y] = color + (255,)
        return img
