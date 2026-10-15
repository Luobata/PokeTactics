"""水箭龟 cast 像素派生关键帧制作脚本。

方法：不从零画造型。每张帧以 gen1_front.bin 解码的 56x55 原图为本体，
把命名区域（头/臂/腿/双炮/身体）的原图像素按整数位移重排，部件移开后
露出的缝隙由 seam_fills 补画壳体（只补移动后身体剪影 2px 范围内，
黑色轮廓只画在最终剪影外缘）——全部严格使用原 3 色 + 二值 alpha。
静止区域与原图逐像素相同，风格一致由构造保证。

坐标系：REGION_POLYS / moves 在原图 56x55 坐标系；
逐帧 patches 与锚点在 64x64 画布坐标系（原图偏移 OX,OY = 4,5）。

用法：python3 tools/acceptance/author_blastoise_cels.py [输出目录]
"""
import json
import sys
from collections import deque
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.mockups.decoders import Front, Palettes  # noqa: E402

BLACK = (0, 0, 0, 255)
BLUE = (65, 89, 255, 255)
YELLOW = (197, 165, 24, 255)
PALETTE = (BLACK, BLUE, YELLOW)

CANVAS = 64          # 输出画布边长（正方形）
OX, OY = 4, 5        # 原图（56x55 裁切后）在画布中的偏移；脚底线 y=59

# ---------------------------------------------------------------- 区域定义
# 在原图 56x55 坐标系内用多边形圈出部件。粘贴顺序：body 在最底，
# 其余按 REGION_POLYS 顺序（后者在上层）。
REGION_POLYS = {
    # 顶炮：左上方斜指的长炮管（对角条形，含根部；黄色壳顶由颜色过滤排除）
    'cannon_top': [(8, 0), (17, 0), (21, 3), (26, 8), (26, 12), (17, 13), (8, 11), (6, 4)],
    # 侧炮：右侧大圆炮，含黄色炮口环
    'cannon_side': [(36, 7), (56, 7), (56, 31), (36, 31)],
    # 头（蓝色大头，含吻部与眼；右缘收在 x31 以内，不吞壳缘）
    'head': [(5, 8), (27, 7), (31, 12), (31, 24), (28, 29), (13, 30), (5, 25)],
    # 左臂（向画面左伸出的手臂与爪）
    'arm_left': [(0, 21), (12, 21), (12, 33), (0, 33)],
    # 左腿（画面左侧，含黄色脚爪；上缘收在壳底缘之下）
    'leg_left': [(8, 36), (22, 36), (22, 51), (8, 51)],
    # 右腿（画面右侧承重腿 + 黄色脚爪）
    'leg_right': [(42, 44), (56, 44), (56, 55), (42, 55)],
}
# body = 所有不透明像素中不属于上述区域的部分（壳体主体）。
# 某些部件只取特定颜色（如顶炮不含壳顶的黄色块）。
REGION_EXCLUDE = {'cannon_top': frozenset((YELLOW,))}

# ---------------------------------------------------------------- 帧编排
# 源图朝左 = 发射方向朝左。recoil（后坐）= 向右（+dx）。
# 下沉 = body/head/cannons/arm 一起 +dy，双腿不动（脚钉在地面）。
def sink(n, **extra):
    moves = {'body': (0, n), 'head': (0, n), 'cannon_top': (0, n),
             'cannon_side': (0, n), 'arm_left': (0, n)}
    moves.update(extra)
    return moves


CELS = {
    # ---- windup：下沉蓄力，炮管压向发射方向（左），头微收
    'windup_1': dict(moves=sink(1)),
    'windup_2': dict(moves=sink(2, cannon_top=(-1, 2), cannon_side=(-1, 2))),
    'windup_3': dict(moves=sink(3, cannon_top=(-2, 3), cannon_side=(-1, 3),
                                head=(1, 3), arm_left=(-1, 3))),
    'windup_4': dict(moves=sink(4, cannon_top=(-3, 3), cannon_side=(-2, 4),
                                head=(1, 4), arm_left=(-2, 4))),
    # ---- strike：击发后坐，炮向右弹、头向下收（相邻部件 dy 差 ≤1 避免拉开凹口）
    'strike_1': dict(moves=sink(2, head=(1, 3), cannon_top=(2, 1), cannon_side=(2, 1),
                                arm_left=(0, 2))),
    'strike_2': dict(moves=sink(3, head=(2, 4), cannon_top=(3, 2), cannon_side=(3, 2),
                                arm_left=(1, 3))),
    'strike_3': dict(moves=sink(3, head=(1, 3), cannon_top=(2, 2), cannon_side=(2, 2),
                                arm_left=(0, 3))),
    # ---- recover：回稳
    'recover_1': dict(moves=sink(2, cannon_top=(1, 1), cannon_side=(1, 1),
                                 head=(1, 1))),
    'recover_2': dict(moves=sink(1)),
}
CEL_ORDER = list(CELS)


def load_source():
    img = Front().image(9, Palettes()).convert('RGBA')
    return img.crop(img.getchannel('A').getbbox())  # 56x55


def region_masks(src):
    w, h = src.size
    alpha = src.getchannel('A')
    masks = {}
    claimed = Image.new('L', (w, h), 0)
    for name, poly in REGION_POLYS.items():
        mask = Image.new('L', (w, h), 0)
        ImageDraw.Draw(mask).polygon(poly, fill=255)
        mask = ImageChops.multiply(mask, alpha).point(lambda v: 255 if v else 0)
        excluded = REGION_EXCLUDE.get(name)
        if excluded:
            mask = mask.point(lambda v: v)  # copy
            px, mpx = src.load(), mask.load()
            for y in range(h):
                for x in range(w):
                    if mpx[x, y] and px[x, y] in excluded:
                        mpx[x, y] = 0
        masks[name] = mask
        claimed = ImageChops.lighter(claimed, mask)
    masks['body'] = ImageChops.subtract(alpha, claimed).point(lambda v: 255 if v else 0)
    return masks


def seam_fills(src, out, body_mask, body_move):
    """缝隙补齐：部件/body 移开后露出的像素，仅当「壳体就在附近」才补。

    候选 = 原图不透明而合成后透明的像素（vacated）。只保留距移动后身体
    剪影 ≤2px 的候选：炮管/头探出壳外的旧位置下面是背景而非壳体，
    保持透明——否则会把部件的旧轮廓补成重影。保留的候选先补壳面黄，
    再从画布边缘洪水填充确定最终外部背景（原图的抖动透明孔是封闭的，
    不会被误判为外部），与外部相邻的补像素描黑边——轮廓只出现在
    最终剪影外缘，不会出现在角色内部。
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
                    nx, ny = OX + x + bdx + dx, OY + y + bdy + dy
                    if 0 <= nx < CANVAS and 0 <= ny < CANVAS:
                        near_body.add((nx, ny))
    kept = set()
    for y in range(h):
        for x in range(w):
            cx, cy = OX + x, OY + y
            if spx[x, y][3] and not opx[cx, cy][3] and (cx, cy) in near_body:
                kept.add((cx, cy))
    for x, y in kept:
        out.putpixel((x, y), YELLOW)
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
            out.putpixel((x, y), BLACK)
    return kept


def compose(src, moves, patches=()):
    """moves: {region: (dx, dy)}；patches: [(x, y, color_or_None)] 画布坐标。"""
    w, h = src.size
    masks = region_masks(src)
    body = src.copy()
    for name, mask in masks.items():  # 身体底图：挖掉全部命名部件
        if name != 'body':
            body.paste((0, 0, 0, 0), (0, 0), mask)
    out = Image.new('RGBA', (CANVAS, CANVAS))
    order = ['body', 'leg_left', 'leg_right', 'arm_left', 'head',
             'cannon_side', 'cannon_top']
    for name in order:
        dx, dy = moves.get(name, (0, 0))
        tile_src = body if name == 'body' else src
        tile = Image.new('RGBA', (w, h))
        tile.paste(tile_src, (0, 0), masks[name])
        out.paste(tile, (OX + dx, OY + dy), tile)
    seam_fills(src, out, masks['body'], moves.get('body', (0, 0)))
    for x, y, color in patches:
        out.putpixel((x, y), color if color is not None else (0, 0, 0, 0))
    return out


def audit(name, img):
    colors = img.getcolors(1 << 24) or []
    for _n, px in colors:
        assert px[3] in (0, 255), f'{name}: alpha 非二值 {px}'
        if px[3]:
            assert px[:3] in [c[:3] for c in PALETTE], f'{name}: 调色板外颜色 {px}'
    assert img.getchannel('A').getbbox(), f'{name}: 无可见像素'


def sheet(frames, path, labels=None):
    """横向并排帧（8x），可选第二行画与第一帧的差异。"""
    S = 8
    n = len(frames)
    out = Image.new('RGBA', (CANVAS * S * n, CANVAS * S + 16), (24, 24, 24, 255))
    d = ImageDraw.Draw(out)
    for i, img in enumerate(frames):
        out.paste(img.resize((CANVAS * S, CANVAS * S), 0), (i * CANVAS * S, 12))
        if labels:
            d.text((i * CANVAS * S + 4, 2), labels[i], fill=(255, 255, 255))
    out.save(path)


# ---------------------------------------------------------------- 锚点
# 与 character_rigs._RIGS[9] 的炮口锚点等效（裁切后原图坐标 + 画布偏移）：
# left_muzzle = 顶炮炮口，right_muzzle = 侧炮炮口。逐帧锚点 = 基准 + 该炮位移。
FOOT_ANCHOR = (32., 59.)          # 脚底线：右腿脚底 src y=54
BASE_ANCHORS = {
    'left_muzzle': (OX + 10.5, OY + 0.5),    # src(10.5, 0.5)
    'right_muzzle': (OX + 51., OY + 9.5),    # src(51, 9.5)
}
ANCHOR_PART = {'left_muzzle': 'cannon_top', 'right_muzzle': 'cannon_side'}

SEQUENCES = {
    'windup': ['windup_1', 'windup_2', 'windup_3', 'windup_4'],
    'strike': ['strike_1', 'strike_2', 'strike_3'],
    'recover': ['recover_1', 'recover_2'],
}


def cel_anchors(name):
    moves = CELS.get(name, {}).get('moves', {})
    return {anchor: [BASE_ANCHORS[anchor][0] + moves.get(part, (0, 0))[0],
                     BASE_ANCHORS[anchor][1] + moves.get(part, (0, 0))[1]]
            for anchor, part in ANCHOR_PART.items()}


def pixels_txt(img):
    chars = {BLACK: 'K', BLUE: 'B', YELLOW: 'Y'}
    return '\n'.join(''.join(chars.get(img.getpixel((x, y)), '.')
                             for x in range(CANVAS)) for y in range(CANVAS))


def write_pack(cels, pack_dir):
    pack_dir.mkdir(parents=True, exist_ok=True)
    names = ['idle'] + CEL_ORDER
    for name in names:
        cels[name].save(pack_dir / f'{name}.png')
        (pack_dir / f'{name}.pixels.txt').write_text(pixels_txt(cels[name]) + '\n',
                                                     encoding='utf-8')
    manifest = {
        'schema_version': 1,
        'species': 9,
        'kind': 'cast',
        'version': 'cast-v2',
        'palette': 'RGBA',
        'canvas_size': [CANVAS, CANVAS],
        'intrinsic_facing': -1,
        'colors': [list(c[:3]) for c in PALETTE],
        'poses': [{'name': name, 'file': f'{name}.png',
                   'foot_anchor': list(FOOT_ANCHOR), 'anchors': cel_anchors(name)}
                  for name in names],
        'sequences': SEQUENCES,
    }
    (pack_dir / 'manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    out_dir = Path(args[0]) if args else ROOT / '.build/blastoise-inbetween-2026-10-15/draft'
    out_dir.mkdir(parents=True, exist_ok=True)
    src = load_source()
    base = Image.new('RGBA', (CANVAS, CANVAS))
    base.paste(src, (OX, OY), src)
    cels = {'idle': base}
    base.save(out_dir / 'idle.png')
    for name, spec in CELS.items():
        img = compose(src, spec['moves'], spec.get('patches', ()))
        audit(name, img)
        cels[name] = img
        img.save(out_dir / f'{name}.png')
    names = ['idle'] + CEL_ORDER
    sheet([cels[n] for n in names], out_dir / '_contact.png', labels=names)
    # 放大拼贴：每张帧 16x 纵向排列，便于逐像素检查接缝
    for name in names:
        cels[name].resize((CANVAS * 10, CANVAS * 10), 0).save(out_dir / f'_big_{name}.png')
    if '--pack' in sys.argv:
        write_pack(cels, ROOT / 'assets/animation/009/cast-v2')
        print('pack written to assets/animation/009/cast-v2')
    print(f'wrote {len(cels)} cels + contact sheet to {out_dir}')


if __name__ == '__main__':
    main()
