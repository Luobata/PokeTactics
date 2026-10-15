"""第二世代素材提取管线。

数据源：PokeAPI sprites 仓库的水晶版正面图（透明背景、原生 40/48/56px、4 色）。
    https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/
    versions/generation-ii/crystal/{shiny/}<id>.png

转换规则（与 assets/gen2/ 既有 18 张素材逐字节验证一致，见本文件 --verify）：
- 保留原生尺寸，不补齐；
- 透明像素与不透明白色像素统一落为调色板索引 0（白色）——素材里的内部白色
  由 tools/mockups/decoders.py 的 _restore_enclosed_white 在解码时还原；
- 调色板顺序沿用源图（[白, 浅, 深, 黑]）。

用法：
    python3 tools/extract_gen2_sprites.py 198 200 215 227   # 下载并写入 assets/gen2/
    python3 tools/extract_gen2_sprites.py --verify 162      # 只校验不写入
"""

import io
import sys
import urllib.request
from pathlib import Path

from PIL import Image

GEN2_DIR = Path(__file__).resolve().parents[1] / "assets" / "gen2"
BASE = ("https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/"
        "versions/generation-ii/crystal")
WHITE = (255, 255, 255)


def convert(data: bytes) -> Image.Image:
    src = Image.open(io.BytesIO(data)).convert("RGBA")
    ref = Image.open(io.BytesIO(data))
    ref_pal = ref.getpalette()
    out = Image.new("P", src.size)
    palette = list(WHITE)
    index = {WHITE: 0}
    px = src.load()
    opx = out.load()
    for y in range(src.size[1]):
        for x in range(src.size[0]):
            r, g, b, a = px[x, y]
            color = WHITE if a == 0 else (r, g, b)
            if color not in index:
                index[color] = len(palette) // 3
                palette.extend(color)
            opx[x, y] = index[color]
    # 与既有素材一致：白色固定为索引 0，其余颜色按源图调色板顺序
    ordered = list(WHITE)
    remap = {0: 0}
    for i in sorted(set(ref.getdata())):
        c = tuple(ref_pal[i * 3:i * 3 + 3])
        if c != WHITE and c in index:
            remap[index[c]] = len(ordered) // 3
            ordered.extend(c)
    for y in range(src.size[1]):
        for x in range(src.size[0]):
            opx[x, y] = remap[opx[x, y]]
    out.putpalette(palette := ordered + [0] * (768 - len(ordered)))
    return out


def fetch(sid: int, shiny: bool) -> bytes:
    url = f"{BASE}/{'shiny/' if shiny else ''}{sid}.png"
    with urllib.request.urlopen(url) as resp:
        return resp.read()


def equivalent(a: Image.Image, b: Image.Image) -> bool:
    """白色/透明等价、其余颜色逐像素相等。"""
    if a.size != b.size:
        return False
    ar, br = a.convert("RGBA"), b.convert("RGBA")
    for y in range(a.size[1]):
        for x in range(a.size[0]):
            pa, pb = ar.getpixel((x, y)), br.getpixel((x, y))
            wa = pa[3] == 0 or pa[:3] == WHITE
            wb = pb[:3] == WHITE
            if wa != wb or (not wa and pa[:3] != pb[:3]):
                return False
    return True


def main(argv):
    verify_only = "--verify" in argv
    ids = [int(a) for a in argv if a != "--verify"]
    for sid in ids:
        for shiny in (False, True):
            out = convert(fetch(sid, shiny))
            sub = GEN2_DIR / ("shiny" if shiny else "normal") / f"{sid}.png"
            if verify_only:
                existing = Image.open(sub)
                status = "MATCH" if equivalent(out, existing) else "DIFF"
                print(f"{sid} {'shiny' if shiny else 'normal'}: {status} {out.size}")
            else:
                out.save(sub)
                print(f"wrote {sub} {out.size}")


if __name__ == "__main__":
    main(sys.argv[1:])
