"""通用 cast 像素派生关键帧制作脚本（把水箭龟 cast-v2 方案推广到其余物种）。

方法与水箭龟手工包一致：每张帧以 gen1_front.bin 解码的原图为本体，
只把区域像素按整数位移重排——区域只分两段：脚底带（bbox 底部约 18%
行，钉在地面不动）与身体（其余全部，整体位移）。身体移开后露出的缝隙
由 seam_fills 补画（只补移动后身体剪影 2px 范围内；轮廓色只描在最终
剪影与外部背景相邻处）——全部严格使用原图自有色板 + 二值 alpha。
静止区域与原图逐像素相同，风格一致由构造保证。

帧编排复用水箭龟形状：windup 下沉蓄力并向发射方向（左）倾，
strike 后坐（+dx）下沉，recover 回稳。

颜色泛化：轮廓色 = 原图中最暗的不透明色；补缝填充色局部自适应
（最近的非轮廓邻像素），回退值 = 身体区域中出现次数最多的非轮廓色。

锚点：foot 为脚底线中点；若 character_rigs 对该物种有无部件锚点
（position_percent，相对 bbox），按同一语义换算到画布坐标并逐帧随
身体位移（foot/ground 类接地锚点保持静止）。

用法：python3 tools/acceptance/author_generic_cels.py [--pack] [sid ...]
"""
import json
import sys
from collections import deque
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools/mockups"))
from tools.mockups.decoders import Front, Palettes  # noqa: E402
import character_rigs  # noqa: E402

# motion.species_motion 中有本体 cast 动画的物种，除水箭龟（9，手工包）外。
GENERIC_SPECIES = (3, 6, 18, 26, 31, 34, 59, 65, 76, 94, 95, 130, 131, 143, 149)

CANVAS = 64      # 输出画布边长（正方形）
FOOT_LINE = 59   # 脚底线（bbox 底缘对齐此 y）

# ---------------------------------------------------------------- 帧编排
# 源图朝左 = 发射方向朝左。下沉 = 身体 +dy，脚底带不动；后坐 = +dx。
CELS = {
    'windup_1': (0, 1),
    'windup_2': (0, 2),
    'windup_3': (-1, 3),
    'windup_4': (-2, 4),
    'strike_1': (1, 2),
    'strike_2': (2, 3),
    'strike_3': (1, 3),
    'recover_1': (1, 2),
    'recover_2': (0, 1),
}
CEL_ORDER = list(CELS)
SEQUENCES = {
    'windup': ['windup_1', 'windup_2', 'windup_3', 'windup_4'],
    'strike': ['strike_1', 'strike_2', 'strike_3'],
    'recover': ['recover_1', 'recover_2'],
}
GROUND_ANCHORS = ('foot', 'ground')  # 接地锚点：不随身体位移


def load_source(sid):
    img = Front().image(sid, Palettes()).convert('RGBA')
    return img.crop(img.getchannel('A').getbbox())


def palette_of(src):
    """(轮廓色, 身体填充色, 全部颜色)：按亮度与出现频次推断。"""
    counts = {}
    for pixel in src.getdata():
        if pixel[3]:
            counts[pixel] = counts.get(pixel, 0) + 1
    outline = min(counts, key=lambda rgb: sum(rgb[:3]))
    body_fill = max((c for c in counts if c != outline), key=lambda c: counts[c])
    return outline, body_fill, tuple(counts)


def feet_mask(src):
    """脚底带：bbox 底部约 18% 行内的不透明像素（钉在地面不动）。"""
    w, h = src.size
    rows = max(3, round(h * 0.18))
    mask = Image.new('L', (w, h), 0)
    mpx, spx = mask.load(), src.load()
    for y in range(h - rows, h):
        for x in range(w):
            if spx[x, y][3]:
                mpx[x, y] = 255
    return mask


def seam_fills(src, out, body_mask, body_move, ox, oy, outline, fill):
    """缝隙补齐：body 移开后露出的像素，仅当「身体就在附近」才补。

    与水箭龟手工包同一算法：候选 = 原图不透明而合成后透明的像素，只保留
    距移动后身体剪影 ≤2px 的候选（旧位置下面是背景而非身体时保持透明，
    避免把旧轮廓补成重影）；保留的候选补「最近的非轮廓邻像素」颜色
    （取不到时回退身体填充色），再从画布边缘洪水填充确定最终外部背景
    （原图的抖动透明孔是封闭的，不会误判为外部），与外部相邻的补像素
    描轮廓色——轮廓只出现在最终剪影外缘。
    """
    w, h = src.size
    spx, opx = src.load(), out.load()
    bdx, bdy = body_move
    bpx = body_mask.load()
    near_body = set()
    for y in range(h):
        for x in range(w):
            if not bpx[x, y]:
                continue
            for dx in range(-2, 3):
                for dy in range(-2, 3):
                    nx, ny = ox + x + bdx + dx, oy + y + bdy + dy
                    if 0 <= nx < CANVAS and 0 <= ny < CANVAS:
                        near_body.add((nx, ny))
    kept = set()
    for y in range(h):
        for x in range(w):
            cx, cy = ox + x, oy + y
            if spx[x, y][3] and not opx[cx, cy][3] and (cx, cy) in near_body:
                kept.add((cx, cy))
    # 填充色局部自适应：取输出中最近的非轮廓不透明邻像素颜色
    # （全局单一填充色会把粉色头冠的颜色补进棕色腿部接缝）。
    for x, y in kept:
        color = None
        best = None
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                nx, ny = x + dx, y + dy
                if 0 <= nx < CANVAS and 0 <= ny < CANVAS:
                    pixel = opx[nx, ny]
                    if pixel[3] and pixel != outline:
                        dist = abs(dx) + abs(dy)
                        if best is None or dist < best:
                            best, color = dist, pixel
        out.putpixel((x, y), color if color is not None else fill)
    exterior = set()
    queue = deque()
    for x in range(CANVAS):
        for y in (0, CANVAS - 1):
            if not opx[x, y][3] and (x, y) not in exterior:
                exterior.add((x, y))
                queue.append((x, y))
    for y in range(CANVAS):
        for x in (0, CANVAS - 1):
            if not opx[x, y][3] and (x, y) not in exterior:
                exterior.add((x, y))
                queue.append((x, y))
    while queue:
        x, y = queue.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if (0 <= nx < CANVAS and 0 <= ny < CANVAS
                    and not opx[nx, ny][3] and (nx, ny) not in exterior):
                exterior.add((nx, ny))
                queue.append((nx, ny))
    for x, y in kept:
        if any((x + dx, y + dy) in exterior
               for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx, dy) != (0, 0)):
            out.putpixel((x, y), outline)
    return kept


def compose(src, body_move, ox, oy, outline, fill):
    """身体整体位移 body_move，脚底带静止；先铺身体再盖脚底带。"""
    w, h = src.size
    feet = feet_mask(src)
    fpx = feet.load()
    body_mask = Image.new('L', (w, h), 0)
    bpx, spx = body_mask.load(), src.load()
    for y in range(h):
        for x in range(w):
            if spx[x, y][3] and not fpx[x, y]:
                bpx[x, y] = 255
    out = Image.new('RGBA', (CANVAS, CANVAS))
    body = Image.new('RGBA', (w, h))
    body.paste(src, (0, 0), body_mask)
    out.paste(body, (ox + body_move[0], oy + body_move[1]), body)
    tile = Image.new('RGBA', (w, h))
    tile.paste(src, (0, 0), feet)
    out.paste(tile, (ox, oy), tile)
    seam_fills(src, out, body_mask, body_move, ox, oy, outline, fill)
    return out


def audit(name, img, palette):
    colors = img.getcolors(1 << 24) or []
    allowed = {c[:3] for c in palette}
    for _n, px in colors:
        assert px[3] in (0, 255), f'{name}: alpha 非二值 {px}'
        if px[3]:
            assert px[:3] in allowed, f'{name}: 调色板外颜色 {px}'
    assert img.getchannel('A').getbbox(), f'{name}: 无可见像素'


def sheet(frames, path, labels=None):
    """横向并排帧（8x）。"""
    scale = 8
    n = len(frames)
    out = Image.new('RGBA', (CANVAS * scale * n, CANVAS * scale + 16), (24, 24, 24, 255))
    draw = ImageDraw.Draw(out)
    for i, img in enumerate(frames):
        out.paste(img.resize((CANVAS * scale, CANVAS * scale), 0), (i * CANVAS * scale, 12))
        if labels:
            draw.text((i * CANVAS * scale + 4, 2), labels[i], fill=(255, 255, 255))
    out.save(path)


def rig_anchors(sid, ox, oy, w, h):
    """character_rigs 中的无部件锚点（bbox 百分比）→ 画布基准坐标。"""
    rigs = character_rigs.catalog()
    rig = rigs.get(str(sid))
    if not rig:
        return {}
    anchors = {}
    for name, anchor in rig['anchors'].items():
        if name == 'foot' or 'part' in anchor:
            continue
        percent = anchor['position_percent']
        anchors[name] = (ox + percent[0] * w / 100, oy + percent[1] * h / 100)
    return anchors


def cel_anchors(base, move):
    return {name: [round(x + (0 if name in GROUND_ANCHORS else move[0]), 1),
                   round(y + (0 if name in GROUND_ANCHORS else move[1]), 1)]
            for name, (x, y) in base.items()}


def pixels_txt(img, palette):
    ordered = sorted(palette, key=lambda rgb: sum(rgb[:3]))
    letters = 'KABCDEFGH'
    chars = {color: letters[i] for i, color in enumerate(ordered)}
    return '\n'.join(''.join(chars.get(img.getpixel((x, y)), '.')
                             for x in range(CANVAS)) for y in range(CANVAS))


def write_pack(sid, cels, base_anchors, foot, palette, pack_dir):
    pack_dir.mkdir(parents=True, exist_ok=True)
    names = ['idle'] + CEL_ORDER
    for name in names:
        cels[name].save(pack_dir / f'{name}.png')
        (pack_dir / f'{name}.pixels.txt').write_text(pixels_txt(cels[name], palette) + '\n',
                                                     encoding='utf-8')
    moves = {'idle': (0, 0), **CELS}
    manifest = {
        'schema_version': 1,
        'species': sid,
        'kind': 'cast',
        'version': 'cast-v2',
        'palette': 'RGBA',
        'canvas_size': [CANVAS, CANVAS],
        'intrinsic_facing': -1,
        'colors': [list(c[:3]) for c in sorted(palette, key=lambda rgb: sum(rgb[:3]))],
        'poses': [{'name': name, 'file': f'{name}.png',
                   'foot_anchor': [round(foot[0], 1), round(foot[1], 1)],
                   'anchors': cel_anchors(base_anchors, moves[name])}
                  for name in names],
        'sequences': SEQUENCES,
    }
    (pack_dir / 'manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def build(sid, out_dir, pack=False):
    src = load_source(sid)
    w, h = src.size
    ox, oy = (CANVAS - w) // 2, FOOT_LINE - (h - 1)
    outline, fill, palette = palette_of(src)
    foot = (ox + w / 2, float(FOOT_LINE))
    base_anchors = rig_anchors(sid, ox, oy, w, h)
    base = Image.new('RGBA', (CANVAS, CANVAS))
    base.paste(src, (ox, oy), src)
    cels = {'idle': base}
    out_dir.mkdir(parents=True, exist_ok=True)
    base.save(out_dir / 'idle.png')
    for name, move in CELS.items():
        img = compose(src, move, ox, oy, outline, fill)
        audit(f'{sid}/{name}', img, palette)
        cels[name] = img
        img.save(out_dir / f'{name}.png')
    names = ['idle'] + CEL_ORDER
    sheet([cels[n] for n in names], out_dir / '_contact.png', labels=names)
    if pack:
        target = ROOT / 'assets/animation' / f'{sid:03d}' / 'cast-v2'
        write_pack(sid, cels, base_anchors, foot, palette, target)
    return {'species': sid, 'bbox': [w, h], 'offset': [ox, oy],
            'outline': outline[:3], 'fill': fill[:3], 'colors': len(palette),
            'anchors': sorted(base_anchors)}


def main():
    pack = '--pack' in sys.argv
    args = [int(a) for a in sys.argv[1:] if not a.startswith('--')]
    species = args or list(GENERIC_SPECIES)
    root_out = ROOT / '.build/generic-cels-2026-10-15/draft'
    summary = []
    for sid in species:
        if sid == 9:
            print('skip 9: 水箭龟保留手工包')
            continue
        summary.append(build(sid, root_out / f'{sid:03d}', pack=pack))
        print(f'{sid}: done')
    (root_out / '_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'wrote {len(summary)} species to {root_out}'
          + (' + assets/animation/*/cast-v2' if pack else ''))


if __name__ == '__main__':
    main()
