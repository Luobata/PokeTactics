"""R1 参数化签名、二帧姿态与确定性播放时钟（不修改模拟状态）。"""
from dataclasses import dataclass
import math

from PIL import Image, ImageDraw

from render_mockups import PAPER, FRAME, INK, TYPE_COLORS


@dataclass(frozen=True)
class Signature:
    basic: str
    ultimate: str
    trajectory: str
    windup: float
    floating: bool
    limb: str


SIGNATURES = {
    6: Signature("吐火弹", "大字爆炎", "arc", .5, True, "wings"),
    65: Signature("念力弹", "精神强念", "jitter", .4, True, "arms"),
    143: Signature("重拳", "泰山压顶", "melee", .4, False, "heavy"),
}


@dataclass(frozen=True)
class Gait:
    period: float
    amplitude: int
    floating: bool
    limb: str


def gait_profile(piece, source_size, speed):
    signature = SIGNATURES.get(piece.species_id)
    floating = signature.floating if signature else bool(
        set(piece.types) & {"FLYING", "GHOST"})
    heavy = source_size >= 56 and piece.distance <= 1
    # Period is inversely proportional to movement speed; two discrete poses.
    period = max(.24, min(.8, 24 / max(30, speed)))
    return Gait(period, 2 if heavy else 1, floating,
                signature.limb if signature else "body")


def pose_sprite(sprite, gait, phase, moving):
    """只做整数切片/平移；保持原色板、二值 alpha 和原尺寸。"""
    if not moving and not gait.floating:
        return sprite
    result = Image.new("RGBA", sprite.size)
    w, h = sprite.size
    sign = 1 if phase else -1
    if gait.limb in ("wings", "arms"):
        edge = w // 3
        result.paste(sprite.crop((edge, 0, w - edge, h)), (edge, 0))
        for left, right in ((0, edge), (w - edge, w)):
            result.paste(sprite.crop((left, 0, right, h)), (left, sign))
    elif not gait.floating:
        for y in range(h):
            dx = sign * gait.amplitude if y < h // 2 else -sign
            result.paste(sprite.crop((0, y, w, y + 1)), (dx, y))
    else:
        return sprite
    return result


class PlaybackClock:
    """0.35 playback seconds at 0.3×; overlapping kills merge, at most two windows.

    Input/output in seconds. Speed scales the entire replay, including slow motion.
    Mapping is stateless, so seeking and rendering in any order are identical.
    """
    duration = .35
    rate = .3

    def __init__(self, events):
        starts = []
        for ev in events:
            if ev[1] == "die" and len(starts) < 2:
                if not starts or ev[0] >= starts[-1] + self.duration * self.rate - 1e-9:
                    starts.append(ev[0])
        self.starts = tuple(starts)

    def simulation_time(self, playback, speed=1., skip=False):
        if speed <= 0:
            raise ValueError("speed must be positive")
        value = max(0., playback) * speed
        if skip:
            return value
        extra = 0.
        for start in self.starts:
            begin = start + extra
            if value < begin:
                break
            if value < begin + self.duration:
                return start + (value - begin) * self.rate
            extra += self.duration * (1 - self.rate)
        return value - extra

    def playback_time(self, simulation, speed=1., skip=False):
        if speed <= 0:
            raise ValueError("speed must be positive")
        extra = 0.
        if not skip:
            for start in self.starts:
                elapsed = min(self.duration * self.rate, max(0., simulation - start))
                extra += elapsed * (1 / self.rate - 1)
        return (simulation + extra) / speed


def signature_cast(img, sid, source, target, age, windup, budget, emblem=None, color=None):
    """共享蓄力/环/放射模板；实体只用 2px 笔画，外圈提供体积。"""
    draw = ImageDraw.Draw(img)
    sx, sy = source
    tx, ty = target
    color = color or TYPE_COLORS[{6: "FIRE", 65: "PSYCHIC", 143: "NORMAL"}[sid]]
    phase = math.floor((age + 1e-9) / .1)
    if age < windup:
        if sid == 6:
            radius = (4, 6, 8, 6, 4)[min(4, phase)]
            draw.ellipse((sx - radius, sy - radius, sx + radius, sy + radius),
                         outline=color, width=2)
            for i in budget.take(3):
                draw.point((sx + radius + 3 + i * 3, sy + (i % 2) * 2), fill=PAPER)
        elif sid == 65:
            draw.ellipse((sx - 22, sy - 22, sx + 22, sy + 22), outline=color, width=2)
        else:
            draw.arc((sx - 23, sy - 20, sx + 23, sy + 24), 20, 160, fill=color, width=2)
        return
    p = min(1., (age - windup) / .5)
    radius = 24 + round(p * 18)
    if sid == 6:
        # 大字 outline lands from above, with a four-way fire wave outside the body.
        ex, ey = emblem or (tx - 28, ty)
        y = ey - round((1 - min(1., p * 3)) * 10)
        for points in ([(ex - 10, y - 4), (ex + 10, y - 4)],
                       [(ex, y - 11), (ex - 2, y), (ex - 10, y + 10)],
                       [(ex - 2, y), (ex + 10, y + 10)]):
            draw.line(points, fill=INK, width=3)
            draw.line(points, fill=color, width=1)
        draw.ellipse((tx - radius, ty - radius, tx + radius, ty + radius), outline=color, width=2)
        for i in budget.take(4):
            a = i * math.pi / 2
            x, y = tx + round(radius * math.cos(a)), ty + round(radius * math.sin(a))
            draw.line((x - 5, y, x + 5, y), fill=color, width=2)
            draw.line((x, y - 5, x, y + 5), fill=PAPER, width=1)
    elif sid == 65:
        for offset in (0., .5):
            rr = 21 + round(18 * (1 - ((p + offset) % 1)))
            draw.ellipse((tx - rr, ty - rr, tx + rr, ty + rr), outline=color, width=2)
            draw.arc((tx - rr - 2, ty - rr - 2, tx + rr + 2, ty + rr + 2),
                     200, 330, fill=PAPER, width=1)
    else:
        draw.ellipse((tx - radius, ty + 8 - radius // 2,
                      tx + radius, ty + 8 + radius // 2), outline=FRAME, width=2)
        for i in budget.take(8):
            a = i * math.tau / 8
            x = tx + round(radius * math.cos(a))
            y = ty + 8 + round(radius * .5 * math.sin(a))
            draw.rectangle((x, y, x + 2, y + 1), fill=INK)
        for i in budget.take(3):
            x, y = tx - 26 + i * 25, ty + 40 - round(p * 17) - i * 3
            points = [(x, y), (x + 5, y), (x, y + 5), (x + 5, y + 5)]
            draw.line(points, fill=PAPER, width=3)
            draw.line(points, fill=INK, width=1)
