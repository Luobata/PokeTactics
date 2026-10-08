"""PokeWalk 素材解码器（设计稿渲染用）。

解码 ../ESP32-PokemonGo/assets/ 下的三个二进制格式为 PIL 图像：
- gen1_front.bin (FRNT)：151 张正面精灵，2bpp，分 40/48/56 三段；
- palettes.bin (PALS)：146 套普通 + 146 套闪光 × 4 色 RGB565 + 每只索引；
- font16.bin (FNT1)：16×16 1bpp 中文点阵 + 码点表；
- 本仓库 assets/gen2/{normal,shiny}/*.png：第二世代竞技池的独立 RGBA 素材。

仅设计稿工具链使用（tools/），允许依赖 Pillow——sim/ 层的零依赖宪法不适用于此
（PokeWalk 先例：素材管线用 Pillow，运行时不用）。
"""

import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# PokeTactics/tools/mockups/ -> 上三级到 luobata/，再进 ESP32-PokemonGo/assets
POKEWALK = Path(__file__).resolve().parent.parent.parent.parent / "ESP32-PokemonGo" / "assets"
GEN2_FRONT = Path(__file__).resolve().parents[2] / "assets" / "gen2"
GEN2_SPECIES = frozenset((162, 211, 195, 237, 164, 171, 181, 196, 214,
                          197, 208, 242, 157, 212, 230, 160, 248, 154))
GEN2_TEXT = (
    "大尾立千针鱼沼王战舞郎猫头夜鹰电灯怪电龙太阳伊布赫拉克罗斯月亮伊布"
    "大钢蛇幸福蛋火暴兽巨钳螳螂刺龙王大力鳄班基拉斯大竺葵"
    "警戒尾击毒针散布泥沼锚定旋转扫钉守夜安抚灯塔接力雷光信标弱点预见"
    "破角突击月影护幕钢尾震退幸福合唱烬火喷发交叉弹拳潮龙贯流潜流锁阵岩崩壁垒清露花幕"
    "守势护腕清明坠饰屏障回流乘隙追击反击蓄力易伤强化普攻额外生命损失"
    "扩散宝珠节拍器充能鼓舞传播灼伤中毒攻速直接攻击结束清层"
)
CJK_FONT_PATHS = (
    Path("/System/Library/Fonts/PingFang.ttc"),
    Path("/System/Library/Fonts/STHeiti Light.ttc"),
    Path("/System/Library/Fonts/STHeiti Medium.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
)


class AssetError(ValueError):
    """A required rendering resource is absent or cannot produce visible pixels."""


def _read_resource(path):
    try:
        return path.read_bytes()
    except OSError as exc:
        raise AssetError(f"cannot read art resource {path}: {exc}") from exc


def _rgb565(v: int) -> tuple:
    r, g, b = (v >> 11) & 31, (v >> 5) & 63, v & 31
    return (r * 255 // 31, g * 255 // 63, b * 255 // 31)


class Front:
    """FRNT：头 <4sHH，段目录 <HHII>×n（size, per, count, offset），记录 = u16 id + per 字节。"""

    def __init__(self, path: Path = None) -> None:
        self.path = Path(path) if path is not None else POKEWALK / "gen1_front.bin"
        # Explicit binary resources retain their complete, unrestricted ID table.
        self._allow_local_png = path is None
        self._png_root = GEN2_FRONT
        self._png_cache = {}
        d = _read_resource(self.path)
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

    def _uses_local_png(self, pid: int) -> bool:
        return self._allow_local_png and pid in GEN2_SPECIES and pid not in self.blob_of

    def _png_image(self, pid: int, shiny: bool = False) -> Image.Image:
        key = (pid, bool(shiny))
        if key not in self._png_cache:
            path = self._png_root / ("shiny" if shiny else "normal") / f"{pid}.png"
            try:
                with Image.open(path) as source:
                    if source.format != "PNG":
                        raise AssetError(f"species {pid}: invalid PNG front sprite in {path}")
                    if source.width != source.height or source.width < 1:
                        raise AssetError(f"species {pid}: front sprite must be square in {path}")
                    if source.mode != "P":
                        raise AssetError(f"species {pid}: expected indexed P PNG front sprite in {path}")
                    corners = ((0, 0), (source.width - 1, 0),
                               (0, source.height - 1), (source.width - 1, source.height - 1))
                    if any(source.getpixel(point) != 0 for point in corners):
                        raise AssetError(f"species {pid}: PNG background must use palette index 0 in {path}")
                    # The checked-in Johto pack reserves index 0 for background.
                    # Set alpha on this decoded copy; preserve every source byte.
                    source.info["transparency"] = 0
                    image = source.convert("RGBA")
            except (OSError, ValueError) as exc:
                if isinstance(exc, AssetError):
                    raise
                raise AssetError(f"species {pid}: cannot read PNG front sprite in {path}: {exc}") from exc
            if image.getchannel("A").getbbox() is None:
                raise AssetError(f"species {pid}: front sprite has no visible pixels in {path}")
            self._png_cache[key] = image
        return self._png_cache[key]

    def palette_for_species(self, pid: int, pal: "Palettes", shiny: bool = False) -> tuple:
        """Use local PNG colours directly while retaining binary palette mapping."""
        if not self._uses_local_png(pid):
            return tuple(pal.for_species(pid, shiny))
        image = self._png_image(pid, shiny)
        colors = image.getcolors(image.width * image.height)
        return tuple(dict.fromkeys(rgba[:3] for _, rgba in sorted(colors, reverse=True) if rgba[3]))

    def size_for_species(self, pid: int) -> int:
        if self._uses_local_png(pid):
            return self._png_image(pid).width
        if pid not in self.size_of or pid not in self.blob_of:
            raise AssetError(f"species {pid}: missing front sprite in {self.path}")
        return self.size_of[pid]

    def image(self, pid: int, pal: "Palettes", shiny: bool = False) -> Image.Image:
        """解码为 RGBA。映射与固件 render.c 一致：色号 3 = 透明，0-2 -> 调色板前 3 色。"""
        if self._uses_local_png(pid):
            return self._png_image(pid, shiny).copy()
        size = self.size_for_species(pid)
        blob = self.blob_of[pid]
        if len(blob) != size * size // 4:
            raise AssetError(f"species {pid}: truncated front sprite in {self.path}")
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
        if img.getbbox() is None:
            raise AssetError(f"species {pid}: front sprite has no visible pixels in {self.path}")
        return img


class Palettes:
    """PALS：头 <4sHHHH>（nsets, ncolors, count）+ (2×nsets) 套 ×4 色 + count 字节索引。"""

    def __init__(self, path: Path = None) -> None:
        self.path = Path(path) if path is not None else POKEWALK / "palettes.bin"
        d = _read_resource(self.path)
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
        if type(pid) is not int or not 1 <= pid <= len(self._map):
            raise AssetError(f"species {pid}: missing palette mapping in {self.path}")
        base = self._map[pid - 1] + (self.nsets if shiny else 0)
        if self._map[pid - 1] >= self.nsets or base >= len(self._sets):
            raise AssetError(f"species {pid}: invalid palette index in {self.path}")
        return self._sets[base]


class Font16:
    """FNT1：头 <4sHHHI>（size, per, count）+ count×u16 码点 + count×per 字节 1bpp 行主序。"""

    def __init__(self, path: Path = None) -> None:
        d = _read_resource(Path(path) if path is not None else POKEWALK / "font16.bin")
        magic, ver, size, per, count = struct.unpack("<4sHHHI", d[:14])
        assert magic == b"FNT1", magic
        self.size, self.count = size, count
        self._glyph = {}
        for i in range(count):
            cp = struct.unpack("<H", d[14 + 2 * i:16 + 2 * i])[0]
            self._glyph[chr(cp)] = d[14 + 2 * count + i * per:(14 + 2 * count) + (i + 1) * per]
        self.fallback_font_path = None
        if path is None:
            missing = set(GEN2_TEXT) - self._glyph.keys()
            if missing:
                self._add_gen2_glyphs(missing)

    def _add_gen2_glyphs(self, chars):
        """Rasterize only missing Johto names; existing firmware glyphs stay exact."""
        font_path = next((path for path in CJK_FONT_PATHS if path.is_file()), None)
        if font_path is None:
            raise AssetError("missing system CJK font for Gen 2 name glyphs")
        try:
            font = ImageFont.truetype(str(font_path), self.size - 1)
        except OSError as exc:
            raise AssetError(f"cannot read CJK font {font_path}: {exc}") from exc
        self.fallback_font_path = font_path
        for ch in chars:
            image = Image.new("L", (self.size, self.size))
            left, top, right, bottom = font.getbbox(ch)
            pos = ((self.size - (right - left)) // 2 - left,
                   (self.size - (bottom - top)) // 2 - top)
            ImageDraw.Draw(image).text(pos, ch, fill=255, font=font)
            pixels = image.load()
            rows = []
            for y in range(self.size):
                bits = sum((pixels[x, y] >= 128) << (self.size - 1 - x) for x in range(self.size))
                rows.extend(bits.to_bytes(2, "big"))
            if not any(rows):
                raise AssetError(f"CJK font {font_path} has no visible glyph for {ch}")
            self._glyph[ch] = bytes(rows)

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
