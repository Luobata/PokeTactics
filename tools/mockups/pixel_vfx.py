"""Small opaque pixel primitives: temporal sampling, semantic shapes, 2x2 dithering.

No RNG state, fractional alpha, interpolated RGB or extra decorative particles.
"""
import math
from functools import lru_cache
from PIL import Image, ImageDraw, ImageChops, ImageFilter
from render_mockups import PAPER


def trajectory_point(source, target, progress, trajectory='line'):
    p = max(0., min(1., progress))
    if trajectory == 'arc':
        p = 1 - (1 - p) ** 1.45  # fast launch, gentle landing, unchanged arrival
    x = source[0] + (target[0] - source[0]) * p
    y = source[1] + (target[1] - source[1]) * p
    if trajectory == 'arc':
        y -= 64 * p * (1 - p)
    elif trajectory == 'jitter':
        y += math.sin(p * math.tau * 3)  # old samples retain their own phase
    return round(x), round(y)


def exposure_age(age, duration):
    """Sample inside the displayed 100ms frame, keeping the head before arrival.

    A minimum-duration (100ms) shot still shows three historical segments rather
    than spending its only visible sample hidden inside the launch sprite.
    """
    return min(duration - .0125, age + .075)


def trail_samples(point, age, duration, step=.025):
    # Four 25ms history subframes per 100ms output frame, never distance offsets.
    return [point(max(0., age - step * i) / duration) for i in range(5)]


@lru_cache(maxsize=128)
def checker(size, density):
    mask = Image.new('L', size)
    # 2x2 Bayer: 50% is a checkerboard, 25% leaves one corner.
    ranks = ((0, 2), (3, 1))
    mask.putdata([255 if ranks[y % 2][x % 2] < density else 0
                  for y in range(size[1]) for x in range(size[0])])
    return mask


def dither_line(img, points, color, width=1, density=2):
    if density >= 4:
        ImageDraw.Draw(img).line(points, fill=color, width=width)
        return
    xs, ys = zip(*points)
    x, y = math.floor(min(xs)) - width, math.floor(min(ys)) - width
    size = (math.ceil(max(xs)) - x + width + 1, math.ceil(max(ys)) - y + width + 1)
    tile = Image.new('RGBA', size)
    ImageDraw.Draw(tile).line([(px-x, py-y) for px,py in points], fill=color, width=width)
    tile.putalpha(ImageChops.multiply(tile.getchannel('A'), checker(size, density)))
    img.alpha_composite(tile, (x, y))


def light(draw, x, y, color):
    x, y = round(x), round(y)
    draw.line((x-1, y, x+1, y), fill=color)
    draw.line((x, y-1, x, y+1), fill=color)


def debris(draw, x, y, angle, color):
    x, y = round(x), round(y)
    dx, dy = ((1,0), (0,1), (-1,0), (0,-1))[round(angle / (math.pi / 2)) % 4]
    draw.line((x, y, x+dx, y+dy), fill=color, width=1)


def spark(img, x, y, angle, color, phase=0, length=3):
    end = (round(x + length * math.cos(angle)), round(y + length * math.sin(angle)))
    dither_line(img, [(x,y), end], color, width=2, density=max(1, 4-phase))
    ImageDraw.Draw(img).point(end, fill=PAPER)


def projectile(img, point, age, duration, kind, color, budget):
    if not budget.take(1):
        return
    positions = trail_samples(point, age, duration)
    # Four joined, successively finer/fainter segments; each charged to budget.
    for i in reversed(list(budget.take(4))):
        if positions[i] != positions[i+1]:
            dither_line(img, [positions[i], positions[i+1]], color,
                        width=(3,2,1,1)[i], density=(4,3,2,1)[i])
    x, y = positions[0]
    ahead = point(min(1., age / duration + .02))
    behind = point(max(0., age / duration - .02))
    angle = math.atan2(ahead[1]-behind[1], ahead[0]-behind[0])
    ux, uy = math.cos(angle), math.sin(angle)
    def p(longitudinal, lateral=0):
        return round(x+ux*longitudinal-uy*lateral), round(y+uy*longitudinal+ux*lateral)
    draw = ImageDraw.Draw(img)
    phase = math.floor((age+1e-9)/.1) % 2
    if kind == 'PSYCHIC':
        draw.ellipse((x-2,y-2,x+2,y+2), outline=color,
                     fill=color if phase else (0,0,0,0), width=1)
        draw.point(p(1), fill=PAPER)
    elif kind == 'FIRE':
        sway = 2 if phase else -2
        draw.polygon([p(0,1),p(-5,sway),p(-3,0),p(-4,-sway),p(0,-1)], fill=color)
        draw.ellipse((x-2,y-2,x+2,y+2), fill=color)
        draw.point(p(1), fill=PAPER)
    elif kind == 'WATER':
        draw.polygon([p(0,2),p(-5),p(0,-2)], fill=color)
        draw.ellipse((x-2,y-2,x+2,y+2), fill=color)
        draw.point(p(1,-1), fill=PAPER)
    else:
        draw.line([p(-3),p(2)], fill=color, width=3)
        draw.line([p(-1),p(1)], fill=PAPER, width=1)


def impact_star(draw, cx, cy, radius, direction, color, seed):
    draw.ellipse((cx-radius-1,cy-radius-1,cx+radius+1,cy+radius+1), outline=color, width=1)
    points = []
    for i in range(16):
        # Stateless integer hash: shape stable throughout this event.
        jitter = ((seed * 1664525 + i * 1013904223) & 0xffffffff) % 5
        rr = radius if i % 2 == 0 else radius * (.36 + jitter * .055)
        a = direction + i * math.tau / 16
        points.append((round(cx+rr*math.cos(a)), round(cy+rr*math.sin(a))))
    draw.polygon(points, fill=color)
    draw.rectangle((cx,cy,cx+1,cy+1), fill=PAPER)
    draw.line((cx-1,cy,cx+2,cy), fill=PAPER)
    draw.line((cx,cy-1,cx,cy+2), fill=PAPER)


def impact_rim(img, center, radius, color, phase, budget, direction=0, rays=6):
    draw = ImageDraw.Draw(img)
    x,y = center
    # One-pixel gap between the thin outside and thick inside strokes.
    draw.ellipse((x-radius,y-radius,x+radius,y+radius), outline=color, width=1)
    rr = radius-2
    draw.ellipse((x-rr,y-rr,x+rr,y+rr), outline=color, width=2)
    for i in budget.take(rays):
        a = direction + i * math.tau / rays
        rr = radius + 3 + phase
        spark(img, round(x+rr*math.cos(a)), round(y+rr*math.sin(a)), a,
              color, phase, length=3+int(i%2==0))


def hit_sprite(sprite, direction):
    # Deform the opaque content, preserving the board's fixed-width sprite ABI.
    horizontal = abs(direction[0]) >= abs(direction[1])
    left,top,right,bottom = sprite.getbbox()
    body = sprite.crop((left,top,right,bottom))
    w,h = body.size
    body = body.resize((max(1,w-1) if horizontal else w+1,
                        h+1 if horizontal else max(1,h-1)), Image.Resampling.NEAREST)
    result = Image.new('RGBA',(sprite.width,sprite.height+int(horizontal)))
    # Anchor the far edge: the front side gives way by one native pixel.
    dx = int(horizontal and direction[0] > 0)
    result.paste(body,(left+dx,top+int(not horizontal and direction[1]>0)))
    return result


def feather_flash(sprite, recovery=False):
    alpha = sprite.getchannel('A')
    inner = alpha.filter(ImageFilter.MinFilter(3))
    edge = ImageChops.subtract(alpha, inner)
    white = Image.new('RGBA', sprite.size, PAPER)
    half_edge = ImageChops.multiply(edge, checker(sprite.size, 2))
    white.putalpha(half_edge if recovery else ImageChops.lighter(inner, half_edge))
    result = sprite.copy()
    result.alpha_composite(white)
    return result


def number_rise(age, life=.8):
    p = max(0., min(1., age/life))
    if p <= .375:
        return round(3 * (1-(1-p/.375)**2))
    return round(3 - min(1., ((p-.375)/.375)**2))
