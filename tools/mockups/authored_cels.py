"""手绘完整姿态帧（cel）素材包的严格加载与采样。

与切片 rig 的区别：素材包里的每一帧都是完整角色，运行时不再裁片挖空，
因此不存在切片位移露出的背景缝。素材缺失或非法时返回 None，调用方
回退到现有切片 rig，行为与加载前一致。

素材包按物种存放在 assets/animation/{species:03d}/cast-v2/，每个包覆盖
cast 的 windup/strike/recover 三阶段；没有包的物种或
idle/walk/hit/death/attack 一律返回 None。

坐标约定与 character_rigs.render_rig 相同：素材为源图朝向（朝左），
facing 与包内 intrinsic_facing 符号相反时镜像输出并换算锚点。
"""
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[2]
PACKS_ROOT = ROOT / "assets/animation"

KIND = "cast"
VERSION = "cast-v2"
SEQUENCE_STATES = ("windup", "strike", "recover")


@dataclass(frozen=True)
class _Cel:
    name: str
    image: Image.Image
    foot_anchor: tuple[float, float]
    anchors: dict[str, tuple[float, float]]


@dataclass(frozen=True)
class _Pack:
    cels: dict[str, _Cel]
    sequences: dict[str, tuple[str, ...]]
    intrinsic_facing: int


_cache = {}


def pack_dir(sid):
    return PACKS_ROOT / f"{sid:03d}" / VERSION


def pack_files():
    return tuple(sorted(PACKS_ROOT.rglob("*"))) if PACKS_ROOT.is_dir() else ()


def pack_digest():
    digest = hashlib.sha256()
    for path in pack_files():
        if path.is_file():
            digest.update(str(path.relative_to(PACKS_ROOT)).encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _point(value, width, height, name):
    if (not isinstance(value, list) or len(value) != 2 or
            any(type(c) not in (int, float) or not math.isfinite(c) for c in value)):
        raise ValueError(f"{name} must be a finite [x, y] coordinate")
    if not (0 <= value[0] <= width and 0 <= value[1] <= height):
        raise ValueError(f"{name} must lie within the canvas")
    return float(value[0]), float(value[1])


def load_pack(sid, root=None):
    """完整校验物种 sid 的素材包；任何不符都抛 ValueError，由可用性入口吞掉。"""
    root = pack_dir(sid) if root is None else Path(root)
    key = (sid, str(root))
    if key in _cache:
        return _cache[key]
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"authored cels unavailable: {exc}") from exc
    if manifest.get("schema_version") != 1 or manifest.get("species") != sid \
            or manifest.get("kind") != KIND or manifest.get("version") != VERSION \
            or manifest.get("palette") != "RGBA":
        raise ValueError("authored cels manifest header mismatch")
    intrinsic = manifest.get("intrinsic_facing")
    if intrinsic not in (-1, 1):
        raise ValueError("intrinsic_facing must be -1 or 1")
    size = manifest.get("canvas_size")
    if (not isinstance(size, list) or len(size) != 2
            or any(type(v) is not int or v <= 0 for v in size)):
        raise ValueError("canvas_size must contain positive integer dimensions")
    width, height = size
    colors = manifest.get("colors")
    if (not isinstance(colors, list) or not colors
            or any(not isinstance(c, list) or len(c) != 3
                   or any(type(v) is not int or not 0 <= v <= 255 for v in c)
                   for c in colors)):
        raise ValueError("colors must declare the pack palette as RGB triples")
    palette = frozenset(tuple(c) for c in colors)

    poses = manifest.get("poses")
    if not isinstance(poses, list) or not poses:
        raise ValueError("poses must be a nonempty array")
    cels = {}
    for row in poses:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str) \
                or row.get("file") != f"{row['name']}.png":
            raise ValueError("each pose needs name and matching file")
        name = row["name"]
        try:
            image = Image.open(root / row["file"])
            image.load()
        except (OSError, ValueError) as exc:
            raise ValueError(f"cannot read cel {row['file']}: {exc}") from exc
        if image.mode != "RGBA" or image.size != (width, height):
            raise ValueError(f"{row['file']} must be RGBA with canvas_size dimensions")
        if image.getchannel("A").getbbox() is None:
            raise ValueError(f"{row['file']} must contain visible artwork")
        for _count, pixel in image.getcolors(1 << 24) or []:
            if pixel[3] not in (0, 255):
                raise ValueError(f"{row['file']} alpha must be strictly transparent or opaque")
            if pixel[3] and pixel[:3] not in palette:
                raise ValueError(f"{row['file']} contains a color outside the declared palette")
        anchors = row.get("anchors")
        if not isinstance(anchors, dict) \
                or any(not isinstance(key_, str) for key_ in anchors):
            raise ValueError(f"{name} anchors must be a name-to-point mapping")
        cels[name] = _Cel(name, image,
                          _point(row.get("foot_anchor"), width, height, f"{name} foot_anchor"),
                          {key_: _point(value, width, height, f"{name} {key_}")
                           for key_, value in anchors.items()})
    sequences = manifest.get("sequences")
    if not isinstance(sequences, dict) or set(sequences) != set(SEQUENCE_STATES):
        raise ValueError(f"sequences must cover exactly {sorted(SEQUENCE_STATES)}")
    seq = {}
    for state, names in sequences.items():
        if (not isinstance(names, list) or not names
                or any(name not in cels for name in names)):
            raise ValueError(f"sequence {state} must reference existing poses")
        seq[state] = tuple(names)
    pack = _Pack(cels, seq, intrinsic)
    _cache[key] = pack
    return pack


def pack_status(sid):
    """('available'|'unavailable'|'invalid', reason)，供预览元数据与测试。"""
    if not pack_dir(sid).is_dir():
        return "unavailable", "no authored cel pack files"
    try:
        load_pack(sid)
    except ValueError as exc:
        return "invalid", str(exc)
    return "available", "authored cel pack loaded"


def render(sid, kind, state, progress, facing=1):
    """采样完整姿态帧；不在实装范围内时返回 None 由调用方回退。

    返回的画布与 render_rig 同一约定：info['foot_anchor'] 与
    info['rig_anchors']（含 foot 及包内声明的命名锚点）。
    """
    if kind != KIND or state not in SEQUENCE_STATES:
        return None
    if not math.isfinite(progress):
        raise ValueError("cel progress must be finite")
    try:
        pack = load_pack(sid)
    except ValueError:
        return None
    names = pack.sequences[state]
    cel = pack.cels[names[min(len(names) - 1, int(max(0., min(1., progress)) * len(names)))]]
    image = cel.image.copy()
    foot = cel.foot_anchor
    anchors = dict(cel.anchors)
    if (facing >= 0) != (pack.intrinsic_facing >= 0):  # 与素材朝向相反时镜像
        image = ImageOps.mirror(image)
        foot = (image.width - foot[0], foot[1])
        anchors = {name: (image.width - point[0], point[1])
                   for name, point in anchors.items()}
    image.info["foot_anchor"] = foot
    image.info["rig_anchors"] = {**anchors, "foot": list(foot)}
    return image
