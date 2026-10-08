"""Filled, pixel-authored water volumes for original-move-referenced effects.

Hydro Pump's paired sinusoidal sprites, Surf's advancing water front and
Whirlpool's phased target orbits inform the motion. No simulator/RNG access,
recipient discovery, borrowed tiles, or projectile-shaped skill emblem exists.
The public helpers consume only actual screen points and the caller's clock.
"""
import math

from PIL import Image, ImageDraw
import retro_primitives as rp

PIXEL = 3
LIFETIME = .8


class _WaterSurface:
    """Draw on a local one-third-size grid; nearest scale keeps 3px ink blocks."""
    def __init__(self, layer, bounds):
        self.layer = layer
        self.left = math.floor(bounds[0]/PIXEL)*PIXEL
        self.top = math.floor(bounds[1]/PIXEL)*PIXEL
        width = max(1, math.ceil((bounds[2]-self.left)/PIXEL))
        height = max(1, math.ceil((bounds[3]-self.top)/PIXEL))
        self.image = Image.new('RGBA', (width, height))
        self.draw = ImageDraw.Draw(self.image)

    def xy(self, at):
        return round((at[0]-self.left)/PIXEL), round((at[1]-self.top)/PIXEL)

    def polygon(self, path, color):
        if len(path) >= 3:
            self.draw.polygon([self.xy(at) for at in path], fill=color)

    def oval(self, at, rx, ry, color):
        a = self.xy((at[0]-rx, at[1]-ry))
        b = self.xy((at[0]+rx, at[1]+ry))
        self.draw.ellipse((min(a[0], b[0]), min(a[1], b[1]),
                           max(a[0], b[0]), max(a[1], b[1])), fill=color)

    def foam(self, at, color, radius=2):
        self.oval(at, radius, max(1., radius*.68), color)

    def commit(self):
        if self.image.getbbox() is None:
            return
        big = self.image.resize((self.image.width*PIXEL, self.image.height*PIXEL),
                                Image.Resampling.NEAREST)
        self.layer.alpha_composite(big, (self.left, self.top))


def _basis(source, target):
    dx, dy = target[0]-source[0], target[1]-source[1]
    distance = math.hypot(dx, dy)
    if distance < .001:
        return 0., -1., 1., 0., 0.
    return dx/distance, dy/distance, -dy/distance, dx/distance, distance


def _at(origin, ux, uy, nx, ny, along, across):
    return origin[0]+ux*along+nx*across, origin[1]+uy*along+ny*across


def _ribbon(surface, path, widths, color):
    """Fill an entire curved sheet, with independently varying cross sections."""
    if len(path) < 2:
        return
    left, right = [], []
    for index, center in enumerate(path):
        a = path[max(0, index-1)]
        b = path[min(len(path)-1, index+1)]
        ux, uy, nx, ny, _ = _basis(a, b)
        radius = widths[index] if isinstance(widths, (list, tuple)) else widths
        left.append((center[0]+nx*radius, center[1]+ny*radius))
        right.append((center[0]-nx*radius, center[1]-ny*radius))
    surface.polygon(left+list(reversed(right)), color)


def _curl(surface, at, ux, uy, nx, ny, radius, colors, *, turn=1., phase=0.):
    """A rolled liquid lip: filled spiral ribbon with a broken foamy crest."""
    path, widths = [], []
    for index in range(23):
        q = index/22
        angle = (-.22+q*1.50)*math.pi*turn+phase
        r = radius*(1.-.73*q)
        path.append(_at(at, ux, uy, nx, ny, math.cos(angle)*r, math.sin(angle)*r))
        widths.append(max(1.2, radius*(.28-.13*q)))
    _ribbon(surface, path, [width+2 for width in widths], colors[1])
    _ribbon(surface, path, widths, colors[2])
    _ribbon(surface, path[:15], [max(1., width*.35) for width in widths[:15]], colors[3])
    for index in (1, 4, 8, 12):
        surface.foam(path[index], colors[4], max(1.5, radius*.14))


def pressure_stream(layer, source, target, colors, *, scale=1., clock=0., lane=0, density=1.):
    """Continuous water column, sized around its exact incoming nozzle/flight head.

    Filled uneven cross sections, rolled side lips and crossing helical sheets
    replace nested straight strokes. No endpoint is inferred or advanced.
    """
    ux, uy, nx, ny, distance = _basis(source, target)
    margin = 43*scale
    surface = _WaterSurface(layer, (min(source[0], target[0])-margin,
                                   min(source[1], target[1])-margin,
                                   max(source[0], target[0])+margin,
                                   max(source[1], target[1])+margin))
    if distance < 2:
        surface.oval(source, 8*scale, 6*scale, colors[2])
        surface.oval(source, 4*scale, 3*scale, colors[3])
        surface.commit()
        return
    phase = clock*14+lane*math.pi

    def section(q):
        # Edge crests travel down the stream; the first/last center remain exact.
        bell = math.sin(q*math.pi)
        center = rp.point(source, target, q)
        sway = math.sin(q*math.tau*2.4-phase)*3.8*scale*bell
        center = (center[0]+nx*sway, center[1]+ny*sway)
        radius = (8.5+q*5.8+bell*(2.3+2.3*math.sin(q*math.tau*3-phase)))*scale
        return center, max(5*scale, radius)

    centers, widths = [], []
    for index in range(49):
        center, width = section(index/48)
        centers.append(center)
        widths.append(width)
    centers[0], centers[-1] = source, target
    _ribbon(surface, centers, [w+2*scale for w in widths], colors[0])
    _ribbon(surface, centers, widths, colors[1])
    # A broad lit water face moves side-to-side inside the body, not a white wire.
    face = []
    for index, center in enumerate(centers):
        q = index/48
        shift = math.sin(q*math.tau*2.0-phase+.7)*widths[index]*.23
        face.append((center[0]+nx*shift, center[1]+ny*shift))
    _ribbon(surface, face, [w*.69 for w in widths], colors[2])

    # Thick wrapping water sheets expose opposite sides of the pressure column.
    for band in range(max(3, round(5*density))):
        mid = (band/5+clock*.62+lane*.08) % 1
        lo, hi = max(.025, mid-.075), min(.975, mid+.075)
        if hi-lo < .045:
            continue
        path, foam_path, widths2 = [], [], []
        for index in range(15):
            t = index/14
            q = lo+(hi-lo)*t
            center, radius = section(q)
            side = math.cos(t*math.pi)*radius*.82
            path.append((center[0]+nx*side, center[1]+ny*side))
            foam_path.append((center[0]+nx*(side+2*scale), center[1]+ny*(side+2*scale)))
            widths2.append((1.5+math.sin(t*math.pi)*2.5)*scale)
        _ribbon(surface, path, widths2, colors[3])
        _ribbon(surface, foam_path[2:12], 1.15*scale, colors[4])
    # Small curls roll the outer water edge and advect, never a separate glyph.
    for index in range(max(2, round(3*density))):
        q = .17+((index*.27+clock*.35+lane*.08) % .64)
        center, radius = section(q)
        sign = -1 if (index+lane) % 2 else 1
        at = (center[0]+nx*(radius-3*scale)*sign,
              center[1]+ny*(radius-3*scale)*sign)
        curl_radius = min(7.5*scale, distance*.09)
        _curl(surface, at, ux, uy, nx*sign, ny*sign, curl_radius, colors,
              turn=sign, phase=clock*.6)
    surface.commit()


def _cup(surface, center, ux, uy, nx, ny, radius, thickness, colors, clock,
         *, spread=1., rise=.42, foam=True):
    """A thick, open crescent water face with curled shoulders, no radial rays."""
    outer, inner, rim = [], [], []
    for index in range(43):
        angle = -1.36+index/42*2.72
        ripple = (math.sin(angle*7-clock*17)*2.1+math.sin(angle*11+clock*5))*spread
        r = radius+ripple
        across = math.sin(angle)*r
        ahead = (math.cos(angle)*rise-.12)*r
        outer.append(_at(center, ux, uy, nx, ny, ahead, across))
        inner_r = max(1., r-thickness)
        inner.append(_at(center, ux, uy, nx, ny,
                         (math.cos(angle)*rise-.12)*inner_r-thickness*.22,
                         math.sin(angle)*inner_r))
        rim.append(_at(center, ux, uy, nx, ny, ahead, across))
    surface.polygon(outer+list(reversed(inner)), colors[1])
    # Broad sloping surface, deeper below its foamy rolled lip.
    lit = [rp.point(inner[index], outer[index], .78) for index in range(len(outer))]
    surface.polygon(lit+list(reversed(inner)), colors[2])
    _ribbon(surface, rim, max(1.5, thickness*.20), colors[3])
    if foam:
        for index in range(2, 41, 3):
            if (index+round(clock*18)) % 5 != 0:
                surface.foam(rim[index], colors[4], 2.0+(index % 3)*.45)
        for sign, index in ((-1, 2), (1, 40)):
            _curl(surface, rim[index], ux, uy, nx*sign, ny*sign,
                  max(5., thickness*.53), colors, turn=sign, phase=-.3)


def _ripple(surface, center, rx, ry, thickness, colors, clock, *, partial=False):
    # A spreading water sheet on the field plane, not an outline-circle icon.
    path, widths = [], []
    stop = math.pi*1.72 if partial else math.tau
    for index in range(55):
        angle = -.15+index/54*stop
        radius = 1.+.025*math.sin(angle*9-clock*12)
        path.append((center[0]+math.cos(angle)*rx*radius,
                     center[1]+math.sin(angle)*ry*radius))
        widths.append(max(1., thickness*(.62+.35*math.sin(angle*3+clock*7))))
    _ribbon(surface, path, widths, colors[1])
    _ribbon(surface, path, [max(1., width*.56) for width in widths], colors[2])
    # Foam stays on the wet ridge rather than radiating from an origin.
    for index in range(2, 54, 6):
        surface.foam(path[index], colors[3 if index % 4 else 4], 2.1)


def curling_splash(layer, source, target, colors, age, *, scale=1., density=1., narrow=False):
    """Authoritative hit: a dense cup opens into wave sheets, then falling drops.

    age is seconds since impact, shared across contact/recovery. Main geometry
    never leaves this recipient's area, and no incoming stream is invented here.
    """
    if not 0 <= age < LIFETIME:
        return
    ux, uy, nx, ny, _ = _basis(source, target)
    footprint = .86 if narrow else 1.
    local_scale = scale*footprint
    margin = 116*local_scale
    surface = _WaterSurface(layer, (target[0]-margin, target[1]-margin,
                                   target[0]+margin, target[1]+margin))
    build = min(1., age/.10)
    build = build*build*(3-2*build)
    # Full volume during .04-.20, opening outward during recovery. Radius remains
    # below a local footprint; growth stops before the last water fragments die.
    radius = (16+build*48+max(0., min(.32, age-.18))*66)*local_scale
    settle = max(0., (age-.20)/.42)
    thickness = max(3., (20-settle*14)*local_scale)
    if age < .53:
        center = _at(target, ux, uy, nx, ny, (age*13-3)*local_scale, 0)
        _cup(surface, center, ux, uy, nx, ny, radius, thickness, colors, age,
             spread=local_scale, rise=.52-age*.25)
        # A second low crest follows the first pressure cup, rather than eight
        # spoke-like hit lines; the bowl's center remains open around the actor.
        if .065 <= age < .40:
            trailing = _at(target, ux, uy, nx, ny, -10*local_scale, 0)
            _cup(surface, trailing, ux, uy, nx, ny, radius*.63,
                 max(4., thickness*.60), colors, age+.12,
                 spread=local_scale*.55, rise=.33, foam=age < .31)
    if .06 <= age < .66:
        progress = (age-.06)/.60
        ground = (target[0], target[1]+(21-progress*4)*local_scale)
        _ripple(surface, ground, (20+progress*66)*local_scale,
                (8+progress*22)*local_scale,
                max(1.4, (7-progress*5)*local_scale), colors, age, partial=age > .35)
    # Drops are born from the rolling cup after its dense impact, not immediately
    # as a sparse ray fan. All births use this one absolute elapsed clock.
    for index in range(max(6, round(12*density))):
        born = .17+(index % 4)*.025
        elapsed = age-born
        if not 0 <= elapsed < .40:
            continue
        sign = -1 if index % 2 else 1
        across = sign*(36+elapsed*(84+index % 3*11))*local_scale
        ahead = (9+elapsed*22)*local_scale
        at = _at(target, ux, uy, nx, ny, ahead, across)
        at = (at[0], at[1]+(-elapsed*35+elapsed*elapsed*136)*local_scale)
        radius_drop = max(1., (4.2-elapsed*5)*local_scale)
        surface.oval(at, radius_drop*.76, radius_drop*1.34, colors[2])
        surface.foam((at[0]-radius_drop*.20, at[1]-radius_drop*.48), colors[4],
                     max(1., radius_drop*.32))
    surface.commit()


def surf_front(layer, source, target, colors, progress, *, scale=1., density=1.):
    """A continuous low travelling Surf sheet, before actual target contact."""
    if not 0 <= progress <= 1:
        return
    ux, uy, nx, ny, _ = _basis(source, target)
    at = rp.point(source, target, progress)
    margin = 66*scale
    surface = _WaterSurface(layer, (at[0]-margin, at[1]-margin, at[0]+margin, at[1]+margin))
    radius = (30+progress*13)*scale
    _cup(surface, at, ux, uy, nx, ny, radius, 15*scale, colors,
         progress, spread=scale, rise=.36)
    _ripple(surface, (at[0], at[1]+9*scale), radius*.82, 9*scale,
            4*scale, colors, progress, partial=True)
    surface.commit()


def whirlpool(layer, target, colors, age, *, scale=1., density=1.):
    """Filled spiral water sheets curve upward around only the real recipient."""
    if not 0 <= age < .76:
        return
    margin = 104*scale
    surface = _WaterSurface(layer, (target[0]-margin, target[1]-margin,
                                   target[0]+margin, target[1]+margin))
    for band, born in enumerate((0., .065, .13)):
        local = age-born
        if not 0 <= local < .58:
            continue
        grow = min(1., local/.09)
        settle = max(0., (local-.28)/.30)
        radius = (14+grow*28+local*18)*scale
        path, widths = [], []
        for index in range(55):
            q = index/54
            angle = q*math.tau*1.22+local*10+band*1.7
            r = radius*(1.-q*.38)
            ripple = math.sin(q*18-local*15)*1.6*scale
            path.append((target[0]+math.cos(angle)*(r+ripple),
                         target[1]+(16-band*9)*scale+math.sin(angle)*r*.33-q*20*scale))
            widths.append(max(1.3, (6.5+math.sin(q*math.pi)*2)*(1-settle*.70)*scale))
        _ribbon(surface, path, [width+2*scale for width in widths], colors[1])
        _ribbon(surface, path, widths, colors[2])
        highlight = [(at[0], at[1]-2*scale) for at in path]
        _ribbon(surface, highlight, [max(1., width*.28) for width in widths], colors[3])
        for index in range(1, 54, max(3, round(5/density))):
            surface.foam(highlight[index], colors[4], max(1., (2.7-settle*1.8)*scale))
        # A side curl grows out of the sheet itself, making its edge turn inward.
        if local < .36:
            point_index = round((.3+(local*.6) % .35)*54)
            at = path[point_index]
            _curl(surface, at, 1., 0., 0., 1., 9*scale,
                  colors, turn=1 if band % 2 else -1, phase=age)
    if .04 <= age < .70:
        _ripple(surface, (target[0], target[1]+23*scale),
                (28+age*46)*scale, (9+age*8)*scale,
                max(1., (5-age*5)*scale), colors, age)
    surface.commit()


def draw_wake(layer, origin, destination, progress, config):
    """Low water trace along one factual knockback/pull path in its .6s window.

    The caller maps its recorded floor points and provides normalized progress.
    There is no endpoint explosion, victim search, extra stream or new clock.
    """
    p = float(progress)
    if not math.isfinite(p) or not 0 <= p < 1:
        return True
    ux, uy, nx, ny, distance = _basis(origin, destination)
    if distance < .001:
        return True
    scale, density = rp.settings(config)
    colors = rp.palette('WATER', config)
    head_q = min(1., p/.56)
    head = rp.point(origin, destination, head_q)
    fade = max(0., (p-.52)/.48)
    margin = 30*scale
    surface = _WaterSurface(layer, (min(origin[0], head[0])-margin,
                                   min(origin[1], head[1])-margin,
                                   max(origin[0], head[0])+margin,
                                   max(origin[1], head[1])+margin))
    # The faint-looking trace is a broken thin sheet; the low ridge is 3–9px,
    # preserving the character silhouette above the real field displacement.
    path, widths = [], []
    for index in range(25):
        q = index/24*head_q
        at = rp.point(origin, destination, q)
        path.append(at)
        width = (2.5+math.sin(q*8-p*11)*1.1)*(1-fade*.74)*scale
        widths.append(max(1., width))
    _ribbon(surface, path, [w+1*scale for w in widths], colors[1])
    _ribbon(surface, path, widths, colors[2])
    for index in range(max(2, round(4*density))):
        q = head_q-index*.14
        if q < 0:
            continue
        at = rp.point(origin, destination, q)
        radius = (17-index*2)*(1-fade*.66)*scale
        _ripple(surface, at, radius, max(1.6, radius*.16),
                max(1., 2.7*(1-fade)*scale), colors, p+index*.08, partial=True)
    surface.commit()
    return True
