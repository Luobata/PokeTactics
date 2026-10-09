"""Wide, web-only battle presentation built from the authoritative replay view.

The classic device renderer and simulation are deliberately independent of this
canvas. All positions, HP, energy, effects and deaths come from BattleAnimation's
retimed presentation stream, including when the user seeks backwards.
"""
from bisect import bisect_left, bisect_right
from functools import lru_cache
import copy
import math
from pathlib import Path
import random

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

import arena_vfx
import retro_native
import retro_feedback
import retro_support
import retro_water
import web_motion
from animation_timeline import native_targeting
from motion import Pose, species_motion, transform
from move_effects import DEFAULT_VISUAL, RANGES
from render_battle_gif import BCELL, BX, BY, VIS_ROW_OFF, FULL_GOLD

WIDTH, HEIGHT = 960, 640
PARTICLE_LIMIT = 192
MAX_ACTIVE_ACTIONS = 6
EDITABLE_CONTROLS = tuple(DEFAULT_VISUAL)
# Impact-feel layer (web-arena v14). Presentation-only and deterministic in t:
# no state mutation, no extra hits, no timeline retiming outside the renderer.
IMPACT_SHAKE = True
IMPACT_HITSTOP = True
IMPACT_ACCENTS = True
AMBIENT_PARTICLES = True
_HITSTOP_DWELL = .08
_HITSTOP_BUDGET = .6
_SHAKE_WINDOW = .25
_SHAKE_CAP = 5
# Event staging (v14): entrance landing feedback and KO topple. All of it is a
# pure function of (t, event index, particle index) on the battlefield layer.
_ENTRANCE_DROP = .35   # mirrors the shared opening drop in _unit_pose
_ENTRANCE_SQUASH = .12
_KO_CARD_LIFE = .5
_TOPPLE_TIME = .28
# Generic procedural pose: species with neither an articulated rig nor authored
# cels still squat/lunge/breathe. Foot-anchored NEAREST scale plus an integer
# lunge, all a pure function of (t, unit, action phase) sampled from _part_state.
_GENERIC_BREATH = .015
_GENERIC_SQUAT = .05
_GENERIC_STRETCH = .05
_GENERIC_LEAN = 3
_GENERIC_LUNGE = 4
# Ultimate staging (v14 P0-P2): a full-field palette performance, metronomic
# burst salvos, a darker hitstop and a wider horizontal shake for high-power
# native casts. "大招" caliber: a cast event whose move power >= _ULT_POWER in
# the arena skill catalog (or pokedex data outside arena mode). Basic attacks
# and zero-power support/terrain casts never qualify; banned-list skills only
# receive this generic overlay, their retro_*.py files stay untouched.
IMPACT_ULT = True
_ULT_POWER = 65
_ULT_DIM_PEAK = 84
_ULT_FLASH_ALPHAS = (((255,255,255),175),((8,10,12),110),((255,255,255),80))
_ULT_DARKEN_WINDOW = .2   # the GBA 13-frame blacken-and-restore beat
_ULT_DARKEN_DEPTH = .12
_ULT_BURST_BEAT = .15     # three 20fps frames between salvos
_ULT_BURST_BATCHES = 5
_ULT_BURST_LIFE = .5
_ULT_HITSTOP_DWELL = .13
_SHAKE_CAP_ULT = 9


def _positive_heal_amount(value):
    return type(value) in (int,float) and math.isfinite(value) and value>0


def normalize_visual_overrides(overrides=None):
    """Detached, bounded web-only settings for the complete arena roster."""
    if overrides is None:
        return {}
    if not isinstance(overrides, dict):
        raise ValueError('visual_overrides must be a species-to-settings object')
    from arena import ROSTER
    result = {}
    for key, values in overrides.items():
        if (isinstance(key, bool) or not (type(key) is int or
                isinstance(key, str) and key.isdecimal())):
            raise ValueError('visual species keys must be integer ids')
        sid = int(key)
        if sid not in ROSTER or sid in result:
            raise ValueError('unknown or duplicate arena visual species')
        if not isinstance(values, dict) or set(values) - set(DEFAULT_VISUAL):
            raise ValueError('invalid arena visual fields')
        config = dict(DEFAULT_VISUAL)
        for name, value in values.items():
            if name == 'palette':
                if value not in ('classic', 'vivid'):
                    raise ValueError('palette must be classic or vivid')
            elif (type(value) not in (int, float) or
                  not RANGES[name][0] <= value <= RANGES[name][1] or not math.isfinite(value)):
                raise ValueError(f'{name} must be in {RANGES[name]}')
            config[name] = value
        result[sid] = config
    return result


def _effect_color(rgb, palette):
    if palette == 'classic':
        return rgb
    light = sum(rgb) / 3
    return tuple(round(min(255, max(0, light + (value-light)*1.45 + 10))) for value in rgb)


@lru_cache(maxsize=1)
def _ult_move_powers():
    """Move power per castable move name, from the authoritative catalogs."""
    powers = {}
    import arena_skills
    for skill in arena_skills.catalog():
        powers['arena_'+skill['id']] = skill.get('power', 0)
    from render_battle_gif import pokedex
    for move in pokedex().moves.values():
        powers[move['name']] = move.get('power', 0)
    return powers


def _dim_sprite(sprite, factor):
    """Multiply sprite brightness by factor; the alpha channel is preserved."""
    lut = [round(value*factor) for value in range(256)]
    r, g, b, a = sprite.split()
    return Image.merge('RGBA', (r.point(lut), g.point(lut), b.point(lut), a))


class _ScaledDraw:
    """Scale local VFX geometry while inverse-mapped route endpoints stay fixed."""
    def __init__(self, draw, origin, scale):
        self.draw, self.origin, self.scale = draw, origin, scale

    def _coordinates(self, points):
        if isinstance(points[0], (tuple, list)):
            return [self._coordinates(point) for point in points]
        return tuple(self.origin[i % 2] + (value-self.origin[i % 2])*self.scale
                     for i, value in enumerate(points))

    def __getattr__(self, name):
        draw = getattr(self.draw, name)
        def call(points, *args, **kwargs):
            if 'width' in kwargs:
                kwargs['width'] = max(1, round(kwargs['width']*self.scale))
            return draw(self._coordinates(points), *args, **kwargs)
        return call

ALLY = (87, 193, 247)
ENEMY = (249, 111, 111)
PAPER = (243, 244, 218)
INK = (17, 33, 36)
TYPE_NAMES = {
    'NORMAL': '一般', 'FIRE': '火', 'WATER': '水', 'ELECTRIC': '电',
    'GRASS': '草', 'ICE': '冰', 'FIGHTING': '格斗', 'POISON': '毒',
    'GROUND': '地面', 'FLYING': '飞行', 'PSYCHIC': '超能', 'BUG': '虫',
    'ROCK': '岩石', 'GHOST': '幽灵', 'DRAGON': '龙', 'DARK': '恶', 'STEEL': '钢',
}
STATUS_LABELS = {
    'burn': ('灼', (255, 150, 76)), 'poison': ('毒', (205, 153, 244)),
    'paralysis': ('麻', (254, 225, 102)), 'freeze': ('冻', (171, 238, 250)),
    'sleep': ('眠', (173, 184, 249)), 'lightscreen': ('光', (139, 225, 241)),
    'reflect': ('壁', (159, 217, 242)), 'sworddance': ('攻', (255, 192, 91)),
    'flinch': ('晕', (253, 221, 129)), 'root': ('缚', (152, 216, 102)),
    'vulnerability': ('破', (255, 173, 126)),
    'healing_block': ('封', (255, 140, 121)),
    'taunt': ('嘲', (255, 172, 109)), 'thorns': ('刺', (223, 170, 249)),
    'ward_charge': ('蓄', (255, 205, 111)),
    'tempo': ('拍', (255, 205, 116)), 'bond_combo': ('连', (223, 208, 140)), 'offense_buff': ('鼓', (249, 185, 112)),
    'physical_buff': ('力', (255, 208, 119)), 'physical_weaken': ('慑', (205, 164, 236)),
    'guard': ('护', (170, 226, 249)), 'shield': ('盾', (147, 231, 249)),
}
WEATHER_NAMES = {'rain': '雨天', 'sun': '晴天', 'sand': '沙暴', 'hail': '冰雹'}
# Weather staging: a 0.5s tint pulse and a small pixel icon announce each
# recorded weather change; both are pure functions of (t, change index).
_WEATHER_TRANSITION = .5
_WEATHER_ICON_LIFE = 1.
_WEATHER_TINT_PEAK = 32
_HUD_BAND_TOP = 592
_WEATHER_TINTS = {'rain': (78, 104, 124), 'sun': (255, 224, 130),
                  'sand': (210, 181, 124), 'hail': (190, 224, 235),
                  None: (168, 178, 172)}
_WEATHER_ICON_ART = {
    'rain': (("...cccccc...",
              "..cccccccc..",
              ".cccccccccc.",
              "..cccccccc..",
              "...d..d..d..",
              "..d..d..d...",
              "...d..d..d.."),
             {'c': (196, 208, 220), 'd': (134, 193, 215)}),
    'sun': ((".r........r.",
             "...ssssss...",
             "..ssssssss..",
             "..ssssssss..",
             "..ssssssss..",
             "...ssssss...",
             ".r........r."),
            {'s': (255, 224, 130), 'r': (255, 196, 90)}),
    'hail': (("...cccccc...",
              "..cccccccc..",
              ".cccccccccc.",
              "..cccccccc..",
              "....h..h....",
              "..h......h.."),
             {'c': (206, 220, 228), 'h': (171, 225, 240)}),
    'sand': (("..sssss.....",
              "......ssss..",
              ".ssssssss...",
              "...sssss....",
              "......sssss."),
             {'s': (222, 192, 134)}),
}


@lru_cache(maxsize=8)
def _weather_icon(name):
    """Small cached pixel glyph announcing one weather beside the title."""
    rows, palette = _WEATHER_ICON_ART[name]
    cell = 2
    icon = Image.new('RGBA', (len(rows[0])*cell, len(rows)*cell))
    d = ImageDraw.Draw(icon)
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch in palette:
                d.rectangle((x*cell, y*cell, x*cell+cell-1, y*cell+cell-1),
                            fill=palette[ch])
    return icon


@lru_cache(maxsize=24)
def _font(size, bold=False):
    """Use an installed CJK font; the web renderer does not depend on Font16."""
    paths = (
        '/System/Library/Fonts/PingFang.ttc',
        '/System/Library/Fonts/Hiragino Sans GB.ttc',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    )
    for path in paths:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size=size, index=1 if bold else 0)
            except OSError:
                try:
                    return ImageFont.truetype(path, size=size)
                except OSError:
                    pass
    return ImageFont.load_default()


def _text(d, xy, text, size=14, fill=PAPER, anchor='la', bold=False, stroke=0):
    d.text(xy, str(text), font=_font(size, bold), fill=fill, anchor=anchor,
           stroke_width=stroke, stroke_fill=INK)


def _star(d, x, y, radius, color, points=4, angle=-math.pi/2):
    d.polygon([(x + math.cos(angle+i*math.pi/points)*radius*(1 if i%2 == 0 else .38),
                y + math.sin(angle+i*math.pi/points)*radius*(1 if i%2 == 0 else .38))
               for i in range(points*2)], fill=color)


def _line(d, a, b, color, width=2):
    d.line((*a, *b), fill=color, width=width)


def _ring(d, xy, radius, color, width=2, flatten=1.):
    x, y = xy
    d.ellipse((x-radius, y-radius*flatten, x+radius, y+radius*flatten),
              outline=color, width=width)


def _arrow(d, a, b, color, width=2, size=9):
    _line(d, a, b, color, width)
    dx, dy = b[0]-a[0], b[1]-a[1]
    length = math.hypot(dx, dy) or 1.
    ux, uy, nx, ny = dx/length, dy/length, -dy/length, dx/length
    d.line(((b[0]-ux*size+nx*size*.55, b[1]-uy*size+ny*size*.55), b,
            (b[0]-ux*size-nx*size*.55, b[1]-uy*size-ny*size*.55)), fill=color, width=width)


def _field_point(col, row, rows=6):
    """Cell foot point in a shallow perspective field, independent of old pixels."""
    row = row * 6 / max(1, rows)
    y = 144 + row*80
    half_width = 345 + (row+.5)*12
    x = WIDTH/2 + ((col+.5)/6-.5)*half_width*2
    return x, y


def _field_corner(col, row):
    y = 74 + row*80
    half_width = 338 + row*12
    return (WIDTH/2 + (col/6-.5)*half_width*2, y)


@lru_cache(maxsize=5)
def _background(weather):
    """Only this cached scenery uses broad lighting; no frame-wide blur is used."""
    img = Image.new('RGB', (WIDTH, HEIGHT))
    d = ImageDraw.Draw(img)
    top = (19, 43, 38) if weather != 'sun' else (39, 56, 38)
    bottom = (11, 29, 28)
    for y in range(HEIGHT):
        k = y/HEIGHT
        color = tuple(round(a*(1-k)+b*k) for a,b in zip(top,bottom))
        d.line((0,y,WIDTH,y), fill=color)
    rng = random.Random(812)
    # Distant canopy and trunks frame the field without competing with actors.
    for i in range(44):
        x, y = rng.randrange(-70,1030), rng.randrange(23,120)
        r = rng.randrange(23,74)
        d.ellipse((x-r,y-r*.5,x+r,y+r*.5), fill=(25+i%3*4,60+i%4*3,45+i%3*3))
    for side in (0,1):
        for i in range(7):
            x = (15+i*14 if side == 0 else 945-i*14)
            d.polygon(((x-5,45),(x+6,45),(x+11,580),(x-15,580)), fill=(26,44,36))
            _line(d,(x+2,88),(x+5,544),(53,70,46),2)
    # Warm stone rim, then the six-by-six playable surface.
    rim = [_field_corner(0,0),_field_corner(6,0),_field_corner(6,6),_field_corner(0,6)]
    d.polygon([(x,y+12) for x,y in rim], fill=(13,24,25))
    d.line((*rim, rim[0]), fill=(150,161,121), width=10, joint='curve')
    d.line((*rim, rim[0]), fill=(78,104,80), width=6, joint='curve')
    for row in range(6):
        for col in range(6):
            cell = [_field_corner(col,row),_field_corner(col+1,row),
                    _field_corner(col+1,row+1),_field_corner(col,row+1)]
            color = ((77,89,73) if (col+row)%2 == 0 else (73,85,71))
            if row < 3:
                color = tuple(v+7 for v in color)
            if weather == 'rain':
                color = (color[0]-9,color[1]-2,color[2]+8)
            elif weather == 'hail':
                color = (color[0]+10,color[1]+14,color[2]+19)
            elif weather == 'sand':
                color = (color[0]+21,color[1]+7,color[2]-5)
            elif weather == 'sun':
                color = (color[0]+13,color[1]+9,color[2]-2)
            d.polygon(cell, fill=color)
            d.line((*cell,cell[0]), fill=(99,111,87), width=1)
            cx,cy = _field_point(col,row)
            # Small carved cell corners make spaces legible without a wireframe.
            for xx in (cx-42,cx+42):
                _line(d,(xx-4,cy+8),(xx+4,cy+8),(136,151,106))
            for _ in range(25):
                xx,yy = cx+rng.randint(-48,48),cy+rng.randint(-58,8)
                r = rng.randint(1,3)
                c = tuple(v+rng.randrange(-4,5) for v in color)
                d.ellipse((xx-r,yy-1,xx+r,yy+1),fill=c)
            # Worn joints and small masonry fractures are confined to each tile.
            if (col+row)%3 == 0:
                xx,yy=cx-38,cy-30
                d.line(((xx,yy),(xx+11,yy-5),(xx+15,yy),(xx+23,yy-3)),fill=(65,78,66),width=1)
    a,b = _field_corner(0,3),_field_corner(6,3)
    _line(d,a,b,(140,149,106),2)
    _line(d,(a[0],a[1]+2),(b[0],b[1]+2),(34,61,51),2)
    # Restrained centre insignia is visible beneath moving actors.
    cx,cy = 480,314
    _ring(d,(cx,cy),37,(120,141,93),2, .58)
    _ring(d,(cx,cy),13,(120,141,93),2, .58)
    _line(d,(cx-37,cy),(cx+37,cy),(120,141,93),2)
    for side,x in ((0,41),(1,919)):
        # Weathered forest posts with faction lights.
        d.rounded_rectangle((x-13,258,x+13,385),radius=5,fill=(58,77,59),outline=(98,117,83),width=2)
        color = ENEMY if side == 0 else ALLY
        d.ellipse((x-8,265,x+8,282),fill=color,outline=PAPER,width=2)
        d.line((x,290,x,376),fill=(140,156,110),width=1)
    for i in range(80):
        side = i%2
        x = rng.randrange(0,85) if side == 0 else rng.randrange(875,960)
        y = rng.randrange(405,HEIGHT)
        h = rng.randrange(4,15)
        _line(d,(x,y),(x+rng.randrange(-5,6),y-h),(59+i%3*6,95+i%5*5,61),2)
    # A compact title gives the web UI room to own the live team counts.
    d.rectangle((0,592,WIDTH,HEIGHT),fill=(15,31,32))
    d.line((0,592,WIDTH,592),fill=(96,123,89),width=1)
    _text(d,(480,12),'森林竞技场',17,anchor='ma',bold=True)
    _text(d,(480,36),'POKÉTACTICS',9,(149,173,147),anchor='ma')
    _text(d,(28,155),'敌',12,ENEMY,anchor='ma')
    _text(d,(28,171),'方',12,ENEMY,anchor='ma')
    _text(d,(931,473),'我',12,ALLY,anchor='ma')
    _text(d,(931,489),'方',12,ALLY,anchor='ma')
    return img


class WebBattleRenderer:
    """High-resolution, deterministic and seekable frame renderer for /play."""
    width, height = WIDTH, HEIGHT

    def __init__(self, anim):
        self.anim = anim
        self.view = anim._presentation_view()
        self.rows = anim.battle_rows
        self._event_times = anim.timeline.event_times
        self._actions = []
        for event in anim.timeline.events:
            if event[1] not in ('attack','cast'):
                continue
            timing = anim.timeline.action_by_event.get(id(event))
            if timing is None or self.view._terrain_attack(event):
                continue
            self._actions.append((event,timing))
        # Resolve side-hit ownership to the actual child damage record. Packet
        # damage is requested damage and can be completely absorbed by a shield.
        side_owners = {}
        for index, event in enumerate(anim.events):
            key = retro_native.effect_key(event, anim.events)
            if key and event[5] in ('side_hit', 'thorn_hit'):
                stop = min(len(anim.events), index+1+event[6].get('event_count', 0))
                for child in range(index+1, stop):
                    landed = anim.events[child]
                    if landed[1] == 'attack' and landed[2:4] == event[2:4]:
                        side_owners[child] = key
        self._field_footprints = {}
        for event in anim.events:
            if event[1] == 'field_effect' and event[5] == 'place':
                self._field_footprints[event[6].get('cast_index')] = tuple(event[6].get('cells', ()))
        self._native_hits = []
        for event, timing in self._actions:
            key = (event[4][6:] if event[1] == 'cast' and retro_native.has_move(event[4])
                   else side_owners.get(timing.source_index))
            requested = event[6] if event[1] == 'cast' else event[4]
            if key and native_targeting(event, anim.by_idx) == 'enemy' and self.view._display_damage(event, requested) > 0:
                self._native_hits.append((timing.impact, timing.target, key))
        self._native_hits.sort()
        self._native_hit_times = [hit[0] for hit in self._native_hits]
        self._action_times = [event[0] for event,timing in self._actions]
        self._unit_actions = {}
        for event, timing in self._actions:
            if not timing.secondary:
                self._unit_actions.setdefault(timing.attacker, []).append((event, timing))
        self._unit_action_times = {idx: [timing.start for _, timing in rows]
                                   for idx, rows in self._unit_actions.items()}
        self._healing_by_regen = self._index_healing_packets()
        self._last_metrics = {}
        self._frame_art = {}
        self._visual_overrides = normalize_visual_overrides(getattr(anim, 'web_visual_overrides', None))
        self._particle_used = 0
        self._impacts, self._impact_lookup = self._index_impacts()
        self._impact_times = [hit[0] for hit in self._impacts]
        self._ults = self._index_ults()
        self._ult_impact_keys = frozenset(round(row[2], 3) for row in self._ults)
        self._warp_segments = self._build_warp()
        self._warp_starts = [segment[0] for segment in self._warp_segments]
        self._cast_float_tiers = self._index_cast_floats()
        self._misses = self._index_misses()
        self._entrances = self._index_entrances()
        self._entrance_land = {row[1]: row[0] for row in self._entrances}
        self._ko_shows = self._index_ko_shows()
        self._ko_by_idx = {row[1]: row for row in self._ko_shows}
        self._result_t = next((ev[0] for ev in anim.timeline.events
                               if ev[1] == 'end'), None)
        self._weather_changes = self._index_weather_changes()

    def _index_weather_changes(self):
        """Announced weather transitions in presentation time, from the timeline.

        Only the events the presentation view itself applies are indexed, so a
        transition cel never reveals weather before the view shows it.
        """
        changes = []
        initial = self.view._initial_weather_name
        if initial in WEATHER_NAMES:
            changes.append((0., initial))
        for event in self.anim.timeline.events:
            if (event[1] == 'combo_effect' and len(event) == 7
                    and event[4] == 'arena_weather' and event[5] in ('weather', 'expire')):
                changes.append((event[0], event[6].get('new_weather')))
            elif (event[1] == 'tactical_effect' and len(event) == 6
                    and event[4] in ('weather_start', 'weather_end', 'weather_conflict')):
                changes.append((event[0], event[5].get('new_weather')))
        changes.sort()
        # A recorded change at the opening already announces the base weather.
        if len(changes) > 1 and changes[0][0] == 0. and changes[1][0] < .05:
            changes.pop(0)
        return tuple(changes)

    def _index_entrances(self):
        """The first deploy of each unit lands when the opening drop ends."""
        seen, rows = set(), []
        for event in self.anim.timeline.events:
            if event[1] != 'deploy' or event[2] in seen:
                continue
            seen.add(event[2])
            unit = self.anim.by_idx[event[2]]
            rows.append((max(_ENTRANCE_DROP, event[0]), event[2], tuple(event[3]),
                         unit.team, getattr(unit.piece, 'star', 1)))
        return tuple(rows)

    def _index_ko_shows(self):
        """Each die event owns a card, a ground crack ring and a topple direction.

        The direction comes from the actual killing action's recorded cells;
        melee-less finishes (poison ticks, fields) fall back to a faction side.
        """
        events = self.anim.timeline.events
        shows = []
        for index, event in enumerate(events):
            if event[1] != 'die':
                continue
            die_t, idx = event[0], event[2]
            pos = next((ev[3] for ev in reversed(events[:index+1])
                        if ev[0] <= die_t and ev[1] in ('deploy', 'move')
                        and ev[2] == idx), None)
            if pos is None:
                continue
            dx = dy = 0.
            for action, timing in self._actions:
                if timing.target == idx and abs(timing.impact-die_t) < .2:
                    dx = timing.target_pos[0]-timing.source_pos[0]
                    dy = timing.target_pos[1]-timing.source_pos[1]
            unit = self.anim.by_idx[idx]
            if not dx and not dy:
                dx = 1. if unit.team == 0 else -1.
            norm = math.hypot(dx, dy) or 1.
            shows.append((die_t, idx, tuple(pos), unit.team, dx/norm, dy/norm))
        return tuple(shows)

    def _index_cast_floats(self):
        """Map each visible cast damage float to (element, effectiveness).

        Floats are bare (t, x, y, text, color) tuples; the tier is inferred
        from the authoritative cast event that produced the text, keyed by
        (impact time, display text) so replay state is never sampled at draw.
        """
        tiers = {}
        for event in self.anim.timeline.events:
            if event[1] != 'cast' or len(event) < 7 or not event[6]:
                continue
            timing = self.anim.timeline.action_by_event.get(id(event))
            if timing is None:
                continue
            display = self.view._display_damage(event, event[6])
            if not display:
                continue
            piece = self.view.units[event[2]].u.piece
            element = (self.view.move_type.get(event[4], piece.types[0])
                       if self.view.is_arena else piece.types[0])
            tiers[(round(timing.impact, 3), f'-{display}')] = (element, event[5])
        return tiers

    def _index_misses(self):
        """Missed casts show MISS over the target's historical cell."""
        misses = []
        events = self.anim.timeline.events
        for index, event in enumerate(events):
            if event[1] != 'miss' or len(event) < 4:
                continue
            pos = next((ev[3] for ev in reversed(events[:index+1])
                        if ev[0] <= event[0] and ev[1] in ('deploy', 'move')
                        and ev[2] == event[3]), None)
            if pos is not None:
                misses.append((event[0], self.cell_point(pos)))
        return misses

    def _index_impacts(self):
        """Weight every real attack/cast impact for the impact-feel layer.

        The view is replayed to the end once so KO weighting can read die_t;
        _ensure rewinds itself on the next frame call.
        """
        self.view._ensure(self.anim.timeline.duration)
        impacts = []
        lookup = {}
        for event, timing in self._actions:
            attacker = self.view.units.get(timing.attacker)
            if attacker is None:
                continue
            move = event[4] if event[1] == 'cast' else ''
            element = (self.anim.move_type.get(move, attacker.u.piece.types[0]) if move
                       else attacker.u.piece.types[0])
            weight = 1.6 if event[1] == 'cast' else 1.
            target = self.view.units.get(timing.target)
            die_t = getattr(target, 'die_t', None)
            if die_t is not None and abs(die_t-timing.impact) < .15:
                weight = 2.4
            impacts.append((timing.impact, weight, timing.target_pos, element))
            lookup[(round(timing.impact, 3), timing.target)] = weight
        impacts.sort()
        return tuple(impacts), lookup

    def _index_ults(self):
        """High-power casts ("大招") that own the full-field staging layer.

        Caliber: cast events (never basic attacks) whose move power is at
        least _ULT_POWER in the arena skill catalog / pokedex data. Each row
        carries the action's own timing and cells plus a stable sequence
        number, so every downstream pixel is a pure function of (t, seq, i).
        """
        powers = _ult_move_powers()
        ults = []
        for seq, (event, timing) in enumerate(self._actions):
            if event[1] != 'cast' or powers.get(event[4], 0) < _ULT_POWER:
                continue
            attacker = self.view.units.get(timing.attacker)
            fallback = attacker.u.piece.types[0] if attacker is not None else 'NORMAL'
            element = self.anim.move_type.get(event[4], fallback)
            ults.append((timing.start, timing.release, timing.impact, timing.target,
                         tuple(timing.target_pos), element, seq))
        ults.sort(key=lambda row: row[2])
        return tuple(ults)

    def _build_warp(self):
        """Piecewise presentation→sim clock: brief dwells at heavy impacts.

        Total presentation length stays equal to the timeline duration; normal
        segments run at a bounded slope (≤1.05) to absorb the dwell time. Ult
        impacts dwell longer (_ULT_HITSTOP_DWELL) than regular heavy hits; all
        dwells share the same _HITSTOP_BUDGET and shrink proportionally when
        it saturates.
        """
        duration = self.anim.timeline.duration
        flat = ((0., 0., 1.),)
        if not IMPACT_HITSTOP or duration <= 0:
            return flat
        stops = []
        for at in sorted({hit[0] for hit in self._impacts if hit[1] >= 1.6}):
            if at < .5 or at > duration-.5:
                continue
            if stops and at-stops[-1] < .3:
                continue
            stops.append(at)
        if not stops:
            return flat
        dwells = [_ULT_HITSTOP_DWELL if IMPACT_ULT and round(at, 3) in self._ult_impact_keys
                  else _HITSTOP_DWELL for at in stops]
        total = sum(dwells)
        if total > _HITSTOP_BUDGET:
            dwells = [dwell*_HITSTOP_BUDGET/total for dwell in dwells]
            total = _HITSTOP_BUDGET
        slope = duration/max(1e-6, duration-total)
        if slope > 1.05:
            slope = 1.05
            total = duration*(1-1/slope)
            dwells = [dwell*total/sum(dwells) for dwell in dwells]
        segments = []
        pres = sim = 0.
        for at, dwell in zip(stops, dwells):
            if at > sim:
                segments.append((pres, sim, slope))
                pres += (at-sim)/slope
                sim = at
            segments.append((pres, sim, 0.))
            pres += dwell
        segments.append((pres, sim, slope))
        return tuple(segments)

    def _warp(self, seconds):
        if len(self._warp_segments) == 1:
            return seconds
        index = max(0, bisect_right(self._warp_starts, seconds)-1)
        pres, sim, slope = self._warp_segments[index]
        return sim + (seconds-pres)*slope

    def _shake_offset(self, t):
        """Deterministic damped shake from recent impacts; capped in magnitude.

        Ult impacts switch the battlefield into a wider horizontal sway (cap
        _SHAKE_CAP_ULT, slow 9 Hz carrier, small vertical bleed); everything
        else keeps the original _SHAKE_CAP=5 envelope.
        """
        if not IMPACT_SHAKE:
            return (0, 0)
        x = y = 0.
        ult = False
        start = bisect_right(self._impact_times, t-_SHAKE_WINDOW)
        end = bisect_right(self._impact_times, t+1e-9)
        for i in range(start, end):
            at, weight = self._impacts[i][0], self._impacts[i][1]
            age = t-at
            if age < 0:
                continue
            phase = i*2.399
            if IMPACT_ULT and round(at, 3) in self._ult_impact_keys:
                ult = True
                decay = math.exp(-age/.16)
                x += 9.5*decay*math.cos(math.tau*9*age)
                y += 2.2*decay*math.cos(math.tau*7*age+phase*1.7)
            else:
                amp = 4. if weight >= 2.4 else 2.5 if weight >= 1.6 else 1.2
                decay = math.exp(-age/.09)
                x += amp*decay*math.sin(math.tau*13*age+phase)
                y += amp*decay*.6*math.cos(math.tau*11*age+phase*1.7)
        cap = _SHAKE_CAP_ULT if ult else _SHAKE_CAP
        mag = math.hypot(x, y)
        if mag > cap:
            x, y = x*cap/mag, y*cap/mag
        return (round(x), round(y))

    def _index_healing_packets(self):
        """Bind actual regen source indexes to optional native/role annotations.

        Heal packet event_count is exact ownership. Role/partner annotations
        have an explicit adjacent regen+state grammar. No timestamp matching:
        several unrelated heals can share a tick, recipient and even amount.
        """
        raw=self.anim.events
        owners={}
        def context(source, key=None, payload=None, reaction=None):
            position=(payload.get('target_pos') if key or reaction else None)
            origin=(payload.get('origin_pos',payload.get('source_pos',
                    payload.get('caster_pos'))) if key or reaction else None)
            return {'source':source,'key':key,'source_pos':origin,
                    'target_pos':position,'payload':payload,'reaction':reaction}
        def regen_at(index, patient, amount=None):
            if not 0<=index<len(raw):return False
            row=raw[index]
            return (len(row)==4 and row[1]=='regen' and row[2]==patient
                    and _positive_heal_amount(row[3])
                    and (amount is None or row[3]==amount))
        for index,event in enumerate(raw):
            kind=event[1]
            if (kind in ('skill_effect','combo_effect','field_effect')
                    and len(event)==7 and isinstance(event[6],dict) and event[5]=='heal'):
                source,patient=event[2:4];payload=event[6]
                count=payload.get('event_count')
                if (source not in self.view.units or patient not in self.view.units
                        or not _positive_heal_amount(payload.get('amount'))
                        or type(count) is not int or not 0<count<len(raw)-index):
                    continue
                key=retro_native.effect_key(event,raw)
                for child in range(index+1,index+count+1):
                    if regen_at(child,patient):
                        owners[child]=context(source,key,payload,
                            event[4] if kind == 'combo_effect' and event[4] == 'element_bloom' else None)
            elif kind=='arena_heal' and len(event)==6:
                source,patient,amount=event[2:5]
                if (source in self.view.units and patient in self.view.units
                        and _positive_heal_amount(amount) and index>=2
                        and raw[index-1][1]=='unit_state' and raw[index-1][2]==patient
                        and regen_at(index-2,patient,amount)):
                    owners[index-2]=context(source)
            elif (kind=='partner_effect' and len(event)==7
                    and event[5] in ('rest','share_lunch','bloom') and isinstance(event[6],dict)):
                source,patient=event[2:4];amount=event[6].get('amount')
                if (source not in self.view.units or patient not in self.view.units
                        or not _positive_heal_amount(amount)):
                    continue
                child=index+1
                # Partial suppression is emitted before the successful regen.
                if (child<len(raw) and len(raw[child])==6 and raw[child][1]=='tactical_effect'
                        and raw[child][3]==patient and raw[child][4]=='healing_prevented'):
                    child+=1
                if (regen_at(child,patient,amount) and child+1<len(raw)
                        and raw[child+1][1]=='unit_state' and raw[child+1][2]==patient):
                    owners[child]=context(source)
        return owners

    def visual_config(self, sid):
        return {**DEFAULT_VISUAL, **self._visual_overrides.get(sid, {})}

    def _particles(self, count, density):
        count = min(math.ceil(count*density), max(0, PARTICLE_LIMIT-self._particle_used))
        self._particle_used += count
        return range(count)

    def _foot_pose(self, au, t, pose):
        x, y = au.render_px(t)
        scale = self.visual_config(au.u.piece.species_id)['motion_scale']
        return self._old_point((x+(pose[0]-x)*scale, y+(pose[1]-y)*scale))

    def cell_point(self, position):
        """Expose the real grid-to-field mapping for overlays and contract tests."""
        return _field_point(position[0],position[1],self.rows)

    def _old_point(self, point):
        return self.cell_point(((point[0]-BX)/BCELL,(point[1]-BY)/BCELL-VIS_ROW_OFF))

    @lru_cache(maxsize=160)
    def _source_sprite(self, sid, tier, shiny):
        image = self.anim.front.image(sid,self.anim.pal,shiny=shiny).convert('RGBA')
        bounds = image.getchannel('A').getbbox()
        if bounds is None:
            raise ValueError(f'species {sid}: sprite contains no artwork')
        image = image.crop(bounds)
        box = min(64,58+max(0,tier-1)*3)
        ratio = box/max(image.size)
        return image.resize((max(1,round(image.width*ratio)),max(1,round(image.height*ratio))),
                            Image.Resampling.NEAREST)

    @lru_cache(maxsize=768)
    def _pose_sprite(self,sid,tier,shiny,state,index,frame,hit,right,action_kind):
        source = self._source_sprite(sid,tier,shiny)
        return transform(source,sid,Pose(state,index,frame,(1 if right else -1,0),hit,
                                        action_kind=action_kind))

    def _part_state(self, au, t):
        """Sample joints on the existing action clock, with death before freeze."""
        right = au.u.team == 0
        if au.dying(t):
            return 'death', 0., right, 'attack'
        if 'freeze' in au.statuses:
            t = min(t, au.statuses['freeze'])
        rows = self._unit_actions.get(au.u.idx, ())
        end = bisect_right(self._unit_action_times.get(au.u.idx, ()), t + 1e-9)
        for event, timing in reversed(rows[max(0, end-3):end]):
            if not timing.start <= t < timing.recover_end:
                continue
            delta = timing.target_pos[0] - timing.source_pos[0]
            right = delta > 0 if delta else right
            if t < timing.release:
                state, start, stop = 'windup', timing.start, timing.release
            elif t < timing.impact:
                state, start, stop = 'strike', timing.release, timing.impact
            else:
                state, start, stop = 'recover', timing.impact, timing.recover_end
            return state, min(1., max(0., (t-start)/max(.001, stop-start))), right, event[1]
        if self._result_t is not None and t >= self._result_t:
            # Survivors celebrate on the existing windup pose loop; no new art.
            return 'windup', (t/.9+au.u.idx*.29) % 1., right, 'attack'
        return 'idle', (t/1.6 + au.u.idx*.13) % 1., right, 'attack'

    def _generic_pose(self, au, t):
        """Whole-body squat/lunge/breath for species with no rig and no cels.

        Returns (scale_x, scale_y, lunge_px) or None for species with their own
        motion, dying units, and the entrance-squash window (the landing squash
        owns the body there; never stack both). The phase rides the shared
        action clock, so frozen units hold and seeks replay identical pixels.
        """
        sid = au.u.piece.species_id
        if au.dying(t) or web_motion.supports(sid) or sid in species_motion:
            return None
        if self._entrance_squash(au.u.idx, t) < 1.:
            return None
        state, progress, right, _ = self._part_state(au, t)
        if state == 'death':
            return None
        facing = 1 if right else -1
        if state == 'windup':
            q = progress*progress*(3-2*progress)
            return 1.+.02*q, 1.-_GENERIC_SQUAT*q, facing*round(_GENERIC_LEAN*q)
        if state == 'strike':
            # Lunge toward the target and rebound inside the strike window.
            q = math.sin(math.pi*min(1., progress))
            return 1.-.02*q, 1.+_GENERIC_STRETCH*q, facing*round(_GENERIC_LUNGE*q)
        if state == 'recover':
            q = (1-progress)*(1-progress)
            return 1., 1.+.02*q, facing*round(2*q)
        # Idle breath: a 1.5% vertical scale whose phase _part_state already
        # staggers by unit index, so the field never breathes in sync.
        return 1., 1.+_GENERIC_BREATH*math.sin(math.tau*progress), 0

    @lru_cache(maxsize=1024)
    def _part_sprite(self, sid, tier, shiny, state, step, right, kind, scale=1.):
        return web_motion.render_articulated(self._source_sprite(sid, tier, shiny),
            sid, state, step/32, facing=1 if right else -1, action_kind=kind, motion_scale=scale)

    def _body_cue(self, au, t):
        if au.dying(t) or 'freeze' in au.statuses:
            return 1., 1., None, 0.
        scale = self.visual_config(au.u.piece.species_id)['motion_scale']
        end = bisect_right(self._native_hit_times, t)
        start = bisect_right(self._native_hit_times, t-.24)
        for at, target, key in reversed(self._native_hits[start:end]):
            if target == au.u.idx and key != 'flame_storm':
                weight = self._impact_lookup.get((round(at, 3), target), 1.)
                return retro_feedback.body_cue(key, (t-at)/.24, receiving=True,
                                               motion_scale=scale, weight=min(2., weight))
        rows = self._unit_actions.get(au.u.idx, ())
        end = bisect_right(self._unit_action_times.get(au.u.idx, ()), t)
        for event, timing in reversed(rows[max(0,end-3):end]):
            if event[1] == 'cast' and timing.start <= t < timing.release:
                return retro_feedback.body_cue(event[4][6:],
                    (t-timing.start)/max(.001,timing.release-timing.start), motion_scale=scale)
        return 1., 1., None, 0.

    def _unit_art(self, au, x, y, t):
        piece = au.u.piece
        sid, shiny = piece.species_id, getattr(piece, 'shiny', False)
        sprite = self._source_sprite(sid, piece.tier, shiny)
        lunge = 0
        if web_motion.supports(sid) and not au.dying(t):
            state, progress, right, kind = self._part_state(au, t)
            sprite = self._part_sprite(sid, piece.tier, shiny, state,
                                      round(progress*32), right, kind,
                                      self.visual_config(sid)['motion_scale'])
        elif sid in species_motion:
            motion = self.view._authored_motion(au, t)
            scale = self.visual_config(sid)['motion_scale']
            def scaled(frame):
                return (round(frame[0]*scale), round(frame[1]*scale),
                        round(100+(frame[2]-100)*scale), round(100+(frame[3]-100)*scale),
                        round(frame[4]*scale), frame[5])
            motion = Pose(motion.state, motion.index, scaled(motion.frame), motion.direction,
                          scaled(motion.hit), motion.hit_direction, motion.action_kind)
            sprite = self._pose_sprite(sid, piece.tier, shiny, motion.state,
                motion.index, motion.frame, motion.hit, motion.direction[0]>=0, motion.action_kind)
        else:
            if au.u.team == 0:
                sprite = ImageOps.mirror(sprite)
            generic = self._generic_pose(au, t)
            if generic is not None:
                sx, sy, lunge = generic
                size = (max(1, round(sprite.width*sx)), max(1, round(sprite.height*sy)))
                if size != sprite.size:
                    sprite = sprite.resize(size, Image.Resampling.NEAREST)
        sprite = retro_feedback.transform_body(sprite, self._body_cue(au, t))
        anchor = sprite.info.get('foot_anchor')
        if anchor is None:
            bounds = sprite.getchannel('A').getbbox() or (0, 0, *sprite.size)
            anchor = sprite.width/2, bounds[3]
        left, top = round(x-anchor[0])+lunge, round(y-anchor[1])
        anchors = {key: (left+point[0], top+point[1])
                   for key, point in sprite.info.get('rig_anchors', {}).items()}
        return sprite, left, top, anchors

    def _action_emitters(self, source, timing, phase, t):
        """Freeze launch positions at release; windup follows the actual joint."""
        sid = source.u.piece.species_id
        foot = self.cell_point(timing.source_pos)
        if phase == 'windup' and source.u.idx in self._frame_art:
            anchors = self._frame_art[source.u.idx][3]
        else:
            # Flight is tied to the recorded origin rather than a caster who may
            # have moved or died after firing. Pure sampling permits backwards seek.
            sampled = copy.copy(source)
            sampled.statuses = {key: onset for key, onset in source.statuses.items()
                                if onset <= timing.release}
            if 'freeze' not in sampled.statuses:
                sampled.frozen_pose = None
            pose = self.view._unit_pose(sampled, timing.release)
            if pose is not None:
                native = sampled.render_px(timing.release)
                base = (BX+timing.source_pos[0]*BCELL,
                        BY+(timing.source_pos[1]+VIS_ROW_OFF)*BCELL)
                scale = self.visual_config(sid)['motion_scale']
                foot = self._old_point((base[0]+(pose[0]-native[0])*scale,
                                        base[1]+(pose[1]-native[1])*scale))
            _, _, _, anchors = self._unit_art(sampled, *foot, timing.release)
        names = {68: ('fist_0', 'fist_1', 'fist_2', 'fist_3'),
                 9: ('left_muzzle', 'right_muzzle'),
                 6: ('mouth',), 3: ('flower_focus',),
                 65: ('spoon_0', 'spoon_1'),
                 26: ('cheek',), 212: ('claw_0', 'claw_1')}.get(sid, ('emitter',))
        points = [anchors[name] for name in names if name in anchors]
        return points or [(foot[0], foot[1]-36)]

    @lru_cache(maxsize=160)
    def _nameplate(self, sid, name, star, team, role, ranged, shiny):
        img = Image.new('RGBA',(116,18))
        d = ImageDraw.Draw(img)
        color = ALLY if team == 0 else ENEMY
        # Transparent, outlined text avoids hiding actors in the preceding row.
        _text(d,(2,0),name,12,PAPER,bold=True,stroke=1)
        for i in range(min(3,star)):
            _star(d,88+i*8,7,3.2,(255,221,113),points=5)
        d.line((0,16,9,16),fill=color,width=2)
        if shiny:
            _star(d,112,7,3,(175,225,255))
        return img

    @staticmethod
    @lru_cache(maxsize=1)
    def _contact_shadow():
        img=Image.new('RGBA',(100,36))
        d=ImageDraw.Draw(img)
        for i in range(8):
            d.ellipse((i*3, i*.8, 99-i*3, 35-i*.8), fill=(5,18,19,9+i*5))
        return img

    def _shown(self,t):
        view = self.view
        shown = []
        view._frame_hit_context = (id(view),t,view._recent_hits(t))
        view._motion_context = {}
        for au in view.units.values():
            if not au.visible(t):
                continue
            pose = view._unit_pose(au,t)
            if pose is None:
                continue
            x,y = self._foot_pose(au,t,pose)
            shown.append((y,au,x,y,pose))
        return sorted(shown,key=lambda entry:(entry[0],entry[1].u.idx))

    @staticmethod
    @lru_cache(maxsize=2)
    def _rock_field_art(team):
        """Low faceted hazards rooted in the cell, without a solid oval plate."""
        tile = Image.new('RGBA',(36,20))
        d = ImageDraw.Draw(tile)
        team_color = ALLY if team == 0 else ENEMY
        # Broken soil and cracks sit beneath unequal three-faced stones. The
        # transparent gaps keep the board and its real cell boundary readable.
        d.polygon(((3,10),(9,7),(17,8),(23,7),(32,10),(30,14),
                   (23,15),(17,14),(8,15),(3,13)),fill=(31,37,30,115))
        for path in (((4,11),(10,10),(15,12),(18,10),(27,11),(32,9)),
                     ((10,10),(8,7),(5,6)),((18,10),(21,6),(26,5)),
                     ((24,11),(27,14),(32,15)),((15,12),(12,15),(7,16))):
            d.line(path,fill=(39,38,29,210),width=1)
        for x,y,height,width in ((9,12,7,4),(18,10,10,4),(27,13,6,5)):
            tip=(x-1,y-height)
            d.polygon(((x-width-1,y),(x+width+1,y),(x+width,y+2),
                       (x-width+1,y+2)),fill=(21,29,23,180))
            shape=((x-width,y-1),(x-2,y-height+2),tip,
                   (x+width-1,y-3),(x+width,y),(x,y+1))
            d.polygon(shape,fill=(145,125,96,255))
            d.polygon((tip,(x,y-1),(x+width,y),(x+width-1,y-3)),
                      fill=(89,87,73,255))
            d.polygon((tip,(x-2,y-height+2),(x-width,y-1),(x,y-1)),
                      fill=(180,158,116,255))
            d.line(((x-width,y-1),tip,(x,y-1)),fill=(221,197,146,255),width=1)
        for x,y in ((4,13),(13,8),(14,15),(23,14),(31,11)):
            d.polygon(((x-1,y),(x,y-2),(x+2,y),(x+1,y+1)),
                      fill=(124,112,88,235))
            d.point((x,y-1),fill=(198,175,129,255))
        # Short ground markers convey ownership without outlining a dome.
        d.line(((3,14),(4,15),(6,15)),fill=(*team_color,235),width=1)
        d.line(((30,15),(32,15),(33,14)),fill=(*team_color,235),width=1)
        return tile.resize((108,60),Image.Resampling.NEAREST)

    def _draw_terrain(self,img,t):
        for field in self.view.active_rock_fields.values():
            tile = self._rock_field_art(field['team'])
            for col,row in field['cells']:
                x,y = self.cell_point((col,row))
                img.alpha_composite(tile,(round(x-54),round(y-30)))
                _text(ImageDraw.Draw(img),(x,y+17),'岩钉',10,
                      (248,221,173),anchor='ma',stroke=1)

    def _active_identity_effects(self, t, idx):
        """Only applied native packets can expose a temporary stance/status."""
        active = {}
        for event in self.anim.timeline.recent_events(t, 4.):
            if not retro_native.effect_key(event, self.anim.events):
                continue
            effect, payload = event[5:7]
            if (effect in ('guard', 'taunt', 'thorns') and event[3] == idx
                    and 0 <= t-event[0] < payload.get('duration', 0)):
                if effect != 'taunt' or self.view.units[event[2]].hp > 0:
                    active[effect] = event
            elif (effect == 'thorn_hit' and event[2] == idx
                    and payload.get('remaining', 0) <= 0):
                active.pop('thorns', None)
        for event in self.anim.timeline.recent_events(t, 4.):
            if event[1] != 'combo_effect':
                continue
            if event[4] == 'breach_momentum' and event[5] == 'vulnerability' and event[3] == idx:
                if 0 <= t-event[0] < event[6].get('duration', 0):
                    active['vulnerability'] = event
                continue
            if event[4] != 'ward_bracer' or event[2] != idx:
                continue
            if event[5] == 'charge' and 0 <= t-event[0] < event[6].get('duration', 0):
                active['ward_charge'] = event
            elif event[5] == 'empowered_basic':
                active.pop('ward_charge', None)
        active.update(arena_vfx.active_offense(self.anim.timeline.recent_events(t, 4.), t, idx))
        active.update(arena_vfx.active_traits(self.anim.timeline.recent_events(t, 5.1), t, idx))
        return active

    def _draw_unit(self,img,au,x,y,t):
        piece = au.u.piece
        sid,team = piece.species_id,au.u.team
        color = ALLY if team == 0 else ENEMY
        d = ImageDraw.Draw(img)
        dying = au.dying(t)
        fade = max(0.,1-(t-au.die_t)/.7) if dying else 1.
        img.alpha_composite(self._contact_shadow(),(round(x-50),round(y-10)))
        d=ImageDraw.Draw(img)
        _ring(d,(x,y+1),31,(*color,255),2,.26)
        d.ellipse((x-25,y-4,x+25,y+7),fill=(30,49,43))
        if team == 0:
            d.ellipse((x-36,y-3,x-29,y+4),fill=color,outline=PAPER)
        else:
            d.polygon(((x+33,y-4),(x+38,y+4),(x+29,y+4)),fill=color,outline=PAPER)
        sprite, left, top, anchors = self._unit_art(au, x, y, t)
        self._frame_art[au.u.idx] = sprite, left, top, anchors
        if dying:
            sprite, left, top = self._topple(sprite, left, top, x, y, au, t)
            sprite = sprite.copy()
            sprite.putalpha(sprite.getchannel('A').point(lambda value:round(value*fade)))
        else:
            squash = self._entrance_squash(au.u.idx, t)
            if squash < 1.:
                height = max(1, round(sprite.height*squash))
                top += sprite.height-height
                sprite = sprite.resize((sprite.width, height), Image.Resampling.NEAREST)
            darken = self._ult_darken_factor(au.u.idx, t)
            if darken < 1.:
                sprite = _dim_sprite(sprite, darken)
        img.alpha_composite(sprite,(left,top))
        if not dying and au.energy>=80:
            self._draw_energy_halo(img,x,y,t,'freeze' in au.statuses)
        # Persistent protection comes from the replay state, never future outcomes.
        # Shield HP is a cyan bubble; guard stance is a steel-tinted one.
        identities = self._active_identity_effects(t, au.u.idx)
        guards = 'guard' in identities
        if not dying and au.shield > 0:
            retro_support.draw_dome(img, (x,y-34), (t*.8)%1,
                self.visual_config(sid), quiet=True)
        elif not dying and guards:
            retro_support.draw_dome(img, (x,y-34), (t*.8)%1,
                self.visual_config(sid), quiet=True, element='STEEL')
        if not dying and 'thorns' in identities:
            stance = identities['thorns']
            retro_support._stance_material(img,'venom_armor',(x,y-34),
                (t-stance[0])/max(.001,stance[6]['duration']),self.visual_config(sid),quiet=True)
        if not dying and 'ward_charge' in identities:
            layer = Image.new('RGBA', (80, 80))
            arena_vfx.draw_combination(layer, 'ward_bracer', 'active', (40,40), (40,40),
                (t*.8)%1, identities['ward_charge'][6])
            img.alpha_composite(layer.resize((160,160), Image.Resampling.NEAREST),
                                (round(x-80),round(y-114)))
        if not dying:
            for effect in ('tempo', 'bond_combo', 'offense_buff', 'physical_buff', 'physical_weaken'):
                if effect not in identities:
                    continue
                layer = Image.new('RGBA', (64, 64))
                arena_vfx.draw_combination(layer, identities[effect][4], 'active', (32,32), (32,32),
                    (t*.8)%1, identities[effect][6])
                img.alpha_composite(layer.resize((128,128), Image.Resampling.NEAREST),
                                    (round(x-64),round(y-98)))
        if not dying and getattr(au, 'wet_source_idx', None) is not None:
            layer = Image.new('RGBA', (64, 64))
            arena_vfx.draw_combination(layer, 'element_wet', 'active', (32,32), (32,32), (t*.8)%1, {})
            img.alpha_composite(layer.resize((128,128), Image.Resampling.NEAREST), (round(x-64),round(y-80)))
            _text(ImageDraw.Draw(img), (x,y+22), '湿润', 10, (142,231,240), anchor='ma', stroke=1)
        speed_weather = {'trait_chlorophyll': 'sun', 'trait_swift_swim': 'rain'}
        trait_key = getattr(au, 'arena_trait_key', None)
        if not dying and trait_key in speed_weather and speed_weather[trait_key] == self.view.weather_name:
            layer = Image.new('RGBA', (64, 64))
            arena_vfx.draw_combination(layer, trait_key, 'active', (32,32), (32,32), (t*.8)%1, {})
            img.alpha_composite(layer.resize((128,128), Image.Resampling.NEAREST), (round(x-64),round(y-98)))
        if not dying and 'freeze' in au.statuses:
            d = ImageDraw.Draw(img)
            d.polygon(((x-33,y-6),(x-35,y-54),(x-20,y-78),(x+24,y-78),(x+36,y-48),(x+30,y-4)),
                      outline=(177,246,255))
        if not dying and getattr(piece,'shiny',False):
            d = ImageDraw.Draw(img)
            phase = math.floor(t*10)%8
            _star(d,x-34+(phase%3)*7,y-45-phase*3,4,(198,235,254))

    @staticmethod
    def _energy_halo_alpha(t,frozen=False):
        """Breath is quantized to 8 Hz steps; a pure function of the clock."""
        if frozen:
            return 200
        return (130,175,220,255)[int(t*8)%4]

    def _draw_energy_halo(self,img,x,y,t,frozen=False):
        """Full-energy telegraph: pixel-thin purple/gold rings at the feet.

        Drawn on the battlefield layer so the rings ride the same shake warp
        as their unit; alpha breathes without any randomness or state.
        """
        alpha=self._energy_halo_alpha(t,frozen)
        d=ImageDraw.Draw(img,'RGBA')
        _ring(d,(x,y+1),36,(210,182,247,alpha),2,.26)
        _ring(d,(x,y+1),30,(*FULL_GOLD,round(alpha*.72)),1,.26)

    def _draw_meter(self,img,au,x,y,t):
        if au.dying(t):
            return
        d=ImageDraw.Draw(img)
        color=ALLY if au.u.team==0 else ENEMY
        top,left,width=round(y-68),round(x-39),78
        d.rounded_rectangle((left-1,top-1,left+width+1,top+11),radius=3,
                            fill=(15,31,33,230))
        displayed=min(1.,max(0.,au.hp_display(t)/max(1,au.u.max_hp)))
        current=min(1.,max(0.,au.hp/max(1,au.u.max_hp)))
        d.rectangle((left,top,left+width,top+5),fill=(45,59,50))
        if displayed>current:
            d.rectangle((left,top,left+round(width*displayed),top+5),fill=(221,186,103))
        hpcolor=color if current>.25 else (254,167,83)
        if current>0:
            d.rectangle((left,top,left+round(width*current),top+5),fill=hpcolor)
            d.line((left,top,left+round(width*current),top),fill=(208,240,221))
        d.rectangle((left,top+8,left+width,top+10),fill=(37,53,59))
        energy=min(1.,max(0.,au.energy/80))
        if energy:
            d.rectangle((left,top+8,left+round(width*energy),top+10),fill=(210,182,247))
        # Exact numbers are available when an actor is active; resting bars stay thin.
        active=(au.jitter_t is not None and 0<=t-au.jitter_t<.65) or any(
            c[2]==au.u.idx and c[0]<=t<c[1]+.4 for c in self.view.cutins[-12:])
        if active:
            _text(d,(x,top-1),f'{au.hp}',9,PAPER,anchor='ma',bold=True,stroke=1)
        piece=au.u.piece
        badge=self._nameplate(piece.species_id,piece.name,getattr(piece,'star',1),au.u.team,
                              getattr(piece,'role_key','attack'),au.u.range>1,getattr(piece,'shiny',False))
        img.alpha_composite(badge,(round(x-53),round(y-87)))
        label={'attack':'攻','defense':'守','support':'辅'}.get(getattr(piece,'role_key','attack'),'攻')
        _text(d,(x+34,y-19),label+('远' if au.u.range>1 else '近'),9,(195,214,179),stroke=1)
        kinds=self.view._active_statuses(au,t)
        kinds += [key for (idx,key) in self.view.field_statuses if idx==au.u.idx]
        kinds += list(self._active_identity_effects(t,au.u.idx))
        if au.shield > 0:
            kinds.append('shield')
        blocks=[row for row in self.view._active_healing_blocks(t) if row['target']==au.u.idx]
        if blocks:
            kinds.insert(0,'healing_block')
        for i,kind in enumerate(list(dict.fromkeys(kinds))[:3]):
            label,c=STATUS_LABELS.get(kind,('·',PAPER))
            if kind in ('tempo', 'bond_combo'):
                label = str(self._active_identity_effects(t, au.u.idx)[kind][6]['stacks'])
            xx,yy=round(x+41),top+i*18
            d=ImageDraw.Draw(img)
            d.rounded_rectangle((xx,yy,xx+16,yy+16),radius=4,fill=(23,37,37),outline=c)
            _text(d,(xx+8,yy),label,11,c,anchor='ma')
            if kind=='healing_block':
                remaining=math.ceil(max(row['expires_at']-t for row in blocks))
                _text(d,(xx+19,yy+1),f'{remaining}s',10,c,stroke=1)

    def _phase(self,timing,t,lifetime=.50):
        if t < timing.start or t >= timing.impact+lifetime:
            return None
        if t < timing.release:
            return 'windup',(t-timing.start)/max(.001,timing.release-timing.start)
        if t < timing.impact:
            return 'flight',(t-timing.release)/max(.001,timing.impact-timing.release)
        age = t-timing.impact
        return ('impact',age/.22) if age < .22 else ('aftermath',(age-.22)/(lifetime-.22))

    @lru_cache(maxsize=768)
    def _motif(self,sid,move,element,phase,step,team,palette='classic',scale=1.):
        """Preserve each species' authored silhouette at twice its device size."""
        img = Image.new('RGBA',(112,112))
        center = (56,56)
        progress = step/8
        if move.startswith('arena_') and sid in arena_vfx.EFFECTS:
            arena_vfx.draw_native_skill(img,sid,move[6:],center,center,phase,progress,team,element)
        elif move:
            arena_vfx.draw_skill(img,sid,element,center,center,phase,progress,team,move)
        elif sid in arena_vfx.EFFECTS:
            # The authored motif itself is available without drawing a fake route.
            arena_vfx.EFFECTS[sid][1](ImageDraw.Draw(img),56,56,progress*.5,
                                    progress*2,phase in ('impact','aftermath'))
        else:
            arena_vfx.draw_skill(img,sid,element,center,center,phase,progress,team)
        if palette == 'vivid':
            vivid = ImageEnhance.Color(img.convert('RGB')).enhance(1.45)
            vivid = ImageEnhance.Brightness(vivid).enhance(1.12).convert('RGBA')
            vivid.putalpha(img.getchannel('A'))
            img = vivid
        side = max(1, round(168*scale))
        return img.resize((side,side),Image.Resampling.NEAREST)

    def _material(self,d,element,a,b,phase,p,cast,seed,config=None):
        config = config or DEFAULT_VISUAL
        rgb = _effect_color(arena_vfx.ELEMENT_COLORS.get(element,arena_vfx.ELEMENT_COLORS['NORMAL']),
                            config['palette'])
        density = config['particle_density']
        fade = 1-p if phase == 'aftermath' else 1.
        color = (*rgb,round(240*fade))
        white = (*PAPER,round(250*fade))
        dx,dy = b[0]-a[0],b[1]-a[1]
        length = math.hypot(dx,dy) or 1.
        ux,uy,nx,ny = dx/length,dy/length,-dy/length,dx/length
        k = 0. if phase == 'windup' else p if phase == 'flight' else 1.
        x,y = a[0]+dx*k,a[1]+dy*k
        r = (18+18*p if phase == 'impact' else 16) if cast else 10+10*p
        hit = phase in ('impact','aftermath')
        if phase == 'windup':
            # Shared charge: motes spiral into the caster as the windup
            # tightens. Deterministic index-driven motion, density-scaled.
            for i in self._particles(6, density):
                angle = seed*.53 + i*2.399 - p*5.4
                radius = (27-20*p) * (1-i*.07)
                xx,yy = a[0]+math.cos(angle)*radius, a[1]+math.sin(angle)*radius*.78
                shade = white if i%3 == 0 else color
                s = 2 if i%3 == 0 else 1
                d.rectangle((xx-s,yy-s,xx+s,yy+s),fill=shade)
            # The preparation has the same material as its release. Keep the
            # centre open so the weapon or animated limb stays visible.
            if element == 'ELECTRIC':
                for i in self._particles(4, density):
                    angle = i*math.tau/4 + math.floor(p*8)*.23
                    v = math.cos(angle), math.sin(angle)
                    radius = 14+12*p
                    d.line(((a[0]+v[0]*9,a[1]+v[1]*9),
                            (a[0]+v[0]*radius-v[1]*5,a[1]+v[1]*radius+v[0]*5),
                            (a[0]+v[0]*(radius+9),a[1]+v[1]*(radius+9))),fill=color,width=3)
                    _star(d,a[0]+v[0]*(radius+9),a[1]+v[1]*(radius+9),3,white)
            elif element == 'FIRE':
                for i in self._particles(5, density):
                    q = (p+i*.19)%1
                    xx, yy = a[0]+(i-2)*8, a[1]+12-q*35
                    d.polygon(((xx-4,yy+5),(xx,yy-7-q*8),(xx+5,yy+5)),fill=color)
                    d.line((xx,yy+2,xx,yy-4),fill=(255,228,131,220),width=2)
            elif element == 'WATER':
                for i in self._particles(6, density):
                    angle = i*math.tau/6+p*4
                    radius = 27-15*p
                    xx,yy = a[0]+math.cos(angle)*radius,a[1]+math.sin(angle)*radius
                    d.arc((xx-6,yy-6,xx+6,yy+6),angle*180/math.pi,angle*180/math.pi+200,
                          fill=color,width=3)
                    d.ellipse((xx-2,yy-2,xx+2,yy+2),fill=white)
            elif element in ('FIGHTING','STEEL'):
                for side in (-1,1):
                    xx = a[0]+side*(13+7*p)
                    d.arc((xx-8,a[1]-13,xx+8,a[1]+12),
                          70 if side<0 else 240,220 if side<0 else 390,fill=color,width=3)
                    d.line((xx,a[1]+16,xx+side*5,a[1]+24),fill=white,width=2)
            elif element in ('PSYCHIC','GHOST','DARK','POISON'):
                for i in self._particles(2, density):
                    radius = 18+i*10-5*p
                    d.arc((a[0]-radius,a[1]-radius*.6,a[0]+radius,a[1]+radius*.6),
                          p*210+i*180,p*210+i*180+145,fill=color,width=3)
                if element == 'PSYCHIC':
                    for i in self._particles(3, density):
                        angle = i*math.tau/3-p*2
                        _star(d,a[0]+math.cos(angle)*25,a[1]+math.sin(angle)*25,4,white,4)
            elif element in ('GRASS','BUG'):
                for i in self._particles(4, density):
                    angle = i*math.tau/4+p*2
                    xx,yy = a[0]+math.cos(angle)*21,a[1]+math.sin(angle)*16
                    d.polygon(((xx-5,yy+3),(xx-2,yy-6),(xx+7,yy-2),(xx+2,yy+4)),
                              fill=color,outline=white)
            elif element in ('ICE','ROCK','GROUND'):
                for i in self._particles(4, density):
                    xx,yy = a[0]+(i-1.5)*12,a[1]+17-(i%2)*6
                    lift = (5+13*p) if element=='ICE' else 4+7*p
                    d.polygon(((xx-4,yy),(xx,yy-lift),(xx+5,yy),(xx,yy+3)),
                              fill=color,outline=white)
            else:
                for i in self._particles(3, density):
                    radius = 17+i*7-8*p
                    d.arc((a[0]-radius,a[1]-radius*.65,a[0]+radius,a[1]+radius*.65),
                          110+p*100,250+p*100,fill=color,width=2)
            return
        if phase == 'flight':
            # Shared projectile volume: a fading wake behind a three-tier head
            # (dark rim / main shell / bright core). Each element still draws
            # its own material features on top; route and hit point unchanged.
            head = 8 if cast else 5
            dark = (*tuple(round(c*.42) for c in rgb),round(235*fade))
            for j in self._particles(3, density):
                kk = max(0.,k-(j+1)*.05)
                wx,wy = a[0]+dx*kk, a[1]+dy*kk
                wr = head-2-j*2
                if wr > 0:
                    d.ellipse((wx-wr,wy-wr,wx+wr,wy+wr),fill=(*rgb,round((150-40*j)*fade)))
            d.ellipse((x-head-2,y-head-2,x+head+2,y+head+2),fill=dark)
            d.ellipse((x-head,y-head,x+head,y+head),fill=color)
            cx,cy = x+ux*head*.3, y+uy*head*.3
            core = head*.42
            d.ellipse((cx-core,cy-core,cx+core,cy+core),fill=white)
        if element == 'ELECTRIC':
            if phase == 'flight':
                points = [(a[0]+dx*k*j/8+nx*(7 if j%2 else -5),
                           a[1]+dy*k*j/8+ny*(7 if j%2 else -5)) for j in range(9)]
                d.line(points,fill=(*rgb,100),width=12 if cast else 7)
                d.line(points,fill=color,width=5 if cast else 3)
                d.line(points,fill=white,width=2)
            if hit:
                for i in self._particles(6, density):
                    ang = i*math.tau/6+seed*.2
                    tip = (x+math.cos(ang)*(r+15),y+math.sin(ang)*(r+15))
                    d.line(((x+math.cos(ang)*8,y+math.sin(ang)*8),
                            (x+math.cos(ang+.3)*r,y+math.sin(ang+.3)*r),tip),fill=color,width=3)
        elif element == 'FIRE':
            for i in self._particles(5 if cast else 3, density):
                kk = max(0.,k-i*.038) if phase == 'flight' else 1.
                xx,yy = (a[0]+dx*kk,a[1]+dy*kk) if phase == 'flight' else (
                    x+math.cos(i*1.9+p*5)*r*.65,y+math.sin(i*1.9+p*5)*r*.6)
                rr = 12-i*.9
                d.polygon(((xx-ux*rr+nx*6,yy-uy*rr+ny*6),
                           (xx+ux*rr,yy+uy*rr),(xx-ux*rr-nx*6,yy-uy*rr-ny*6),
                           (xx-ux*rr*2,yy-uy*rr*2)),fill=color)
                d.ellipse((xx-4,yy-4,xx+4,yy+4),fill=(255,229,122,round(250*fade)))
            if hit:
                for i in self._particles(7, density):
                    ang=i*math.tau/7+seed
                    xx,yy=x+math.cos(ang)*r,y+math.sin(ang)*r-p*20
                    d.ellipse((xx-3,yy-3,xx+3,yy+3),fill=color)
        elif element == 'WATER':
            if phase == 'flight':
                for off in (-5,0,5):
                    route=[(a[0]+dx*k*j/10+nx*(off+math.sin(j*.9+p*7)*3),
                            a[1]+dy*k*j/10+ny*(off+math.sin(j*.9+p*7)*3)) for j in range(11)]
                    d.line(route,fill=(*tuple(round(c*.42) for c in rgb),round(210*fade)),width=5 if cast else 4)
                for off in (-5,0,5):
                    route=[(a[0]+dx*k*j/10+nx*(off+math.sin(j*.9+p*7)*3),
                            a[1]+dy*k*j/10+ny*(off+math.sin(j*.9+p*7)*3)) for j in range(11)]
                    d.line(route,fill=color,width=3)
                d.ellipse((x-10,y-10,x+10,y+10),fill=color,outline=white,width=2)
            if hit:
                _ring(d,(x,y+8),r+8,color,3,.48)
                for i in self._particles(7, density):
                    ang=i*math.tau/7
                    xx,yy=x+math.cos(ang)*r,y+math.sin(ang)*r-p*9
                    d.ellipse((xx-3,yy-5,xx+3,yy+4),fill=color,outline=white)
        elif element in ('ROCK','GROUND'):
            if phase == 'flight':
                pts=[(x+math.cos(i*math.pi/3+p*3)*15,y+math.sin(i*math.pi/3+p*3)*13) for i in range(6)]
                d.polygon(pts,fill=color,outline=white)
                d.line((pts[0],(x,y),pts[2]),fill=(91,77,57,240),width=3)
            if hit:
                for i in self._particles(7, density):
                    ang=i*math.tau/7
                    xx,yy=x+math.cos(ang)*(r+5),y+math.sin(ang)*(r+5)*.6
                    d.polygon(((xx-5,yy+4),(xx-2,yy-9),(xx+6,yy+3)),fill=color,outline=white)
                for sign in (-1,1):
                    d.line(((x,y+12),(x+sign*15,y+20),(x+sign*25,y+15),
                            (x+sign*(r+18),y+24)),fill=(65,66,46,round(245*fade)),width=3)
        elif element in ('GRASS','BUG'):
            if phase == 'flight':
                curve=[(a[0]+dx*k*j/10+nx*math.sin(j*.7)*6,a[1]+dy*k*j/10+ny*math.sin(j*.7)*6) for j in range(11)]
                d.line(curve,fill=(56,102,44,round(210*fade)),width=6 if cast else 4)
                d.line(curve,fill=(99,173,76,round(200*fade)),width=3)
                d.line(curve,fill=(*PAPER,round(180*fade)),width=1)
            for i in self._particles(5 if hit else 3, density):
                ang=i*math.tau/5+p*4
                xx,yy=x+math.cos(ang)*r*.7,y+math.sin(ang)*r*.7
                d.polygon(((xx-8,yy+4),(xx-4,yy-7),(xx+9,yy-3),(xx+4,yy+6)),fill=color,outline=white)
                _line(d,(xx-5,yy+3),(xx+6,yy-3),(70,125,52,round(240*fade)),2)
        elif element in ('GHOST','POISON','DARK'):
            d.ellipse((x-r,y-r,x+r,y+r),fill=(47,25,64,round(210*fade)),outline=color,width=3)
            if element == 'GHOST':
                d.polygon(((x-7,y-4),(x-2,y-1),(x-7,y+2)),fill=white)
                d.polygon(((x+7,y-4),(x+2,y-1),(x+7,y+2)),fill=white)
            for i in self._particles(3, density):
                ang=i*math.tau/3+p*4
                xx,yy=x+math.cos(ang)*(r+5),y+math.sin(ang)*r
                d.arc((xx-10,yy-10,xx+10,yy+10),30+p*100,275+p*100,fill=color,width=3)
        elif element == 'PSYCHIC':
            for i in self._particles(2 if cast else 1, density):
                rr=r+i*10
                d.line(((x,y-rr),(x+rr,y),(x,y+rr),(x-rr,y),(x,y-rr)),fill=white if i else color,width=3)
                d.arc((x-rr-6,y-rr-6,x+rr+6,y+rr+6),p*180,p*180+250,fill=color,width=2)
        elif element == 'ICE':
            for i in self._particles(5 if hit else 2, density):
                ang=i*math.tau/5+p
                xx,yy=x+math.cos(ang)*r*.7,y+math.sin(ang)*r*.7
                d.polygon(((xx,yy-12),(xx+5,yy),(xx,yy+9),(xx-5,yy)),fill=color,outline=white)
            if hit:
                for i in self._particles(6, density):
                    ang=i*math.tau/6
                    _line(d,(x,y),(x+math.cos(ang)*r,y+math.sin(ang)*r),white,2)
        elif element in ('FIGHTING','STEEL'):
            for i in self._particles(3, density):
                off=(i-1)*9
                d.arc((x-r+off,y-r,x+r+off,y+r),210,345,fill=color,width=5)
            _line(d,(x-11,y+13),(x+12,y-13),white,3)
            if element == 'STEEL':
                _line(d,(x-13,y-11),(x+13,y+11),color,4)
        elif element in ('FLYING','DRAGON'):
            for i in self._particles(3, density):
                off=(i-1)*10
                if element == 'FLYING':
                    d.arc((x-r,y+off-8,x+r,y+off+9),160,345,fill=color,width=3)
                else:
                    _star(d,x+off,y+math.sin(p*5+i)*9,9+i%2*3,color,4,p+i)
        else:
            if phase == 'flight':
                _line(d,(x-ux*20,y-uy*20),(x,y),(*tuple(round(c*.42) for c in rgb),round(230*fade)),7 if cast else 5)
                _line(d,(x-ux*20,y-uy*20),(x,y),color,4)
                _line(d,(x-ux*20,y-uy*20),(x,y),white,1)
            _ring(d,(x,y),r,color,3)
            _star(d,x,y,10,white,5,p)
        if hit and phase == 'impact':
            _ring(d,b,10+p*30,(*rgb,round(165*(1-p))),2,.6)
            # Local contact flash and dispersing particles make a landed hit
            # readable without flashing the whole battlefield.
            if p < .35:
                _star(d,b[0],b[1],(19 if cast else 11)*(1-p),
                      (*PAPER,round(230*(1-p/.35))),6,seed*.11)
            for i in self._particles(8 if cast else 4, density):
                angle = i*math.tau/(8 if cast else 4)+seed*.37
                radius = 15+p*(38 if cast else 23)
                xx,yy = b[0]+math.cos(angle)*radius,b[1]+math.sin(angle)*radius*.7
                _line(d,(xx-math.cos(angle)*5,yy-math.sin(angle)*3),
                      (xx,yy),(*rgb,round(210*(1-p))),2)

    def _arm_trails(self, d, points, b, phase, p, cast):
        """Four joint-owned strokes share one authoritative contact instant."""
        if phase == 'windup':
            return
        for i, a in enumerate(points):
            dx,dy = b[0]-a[0],b[1]-a[1]
            length=math.hypot(dx,dy) or 1.
            ux,uy,nx,ny=dx/length,dy/length,-dy/length,dx/length
            if phase == 'flight':
                q=max(0.,min(1.,p*1.6-i*.18))
                if q<=0:
                    continue
                reach=min(length*.6,35+q*36)
                tip=(a[0]+ux*reach+nx*(i-1.5)*4,a[1]+uy*reach+ny*(i-1.5)*4)
                d.line((a,(tip[0]-ux*10,tip[1]-uy*10),tip),fill=(240,168,112,130),width=5)
                _line(d,(tip[0]-ux*18,tip[1]-uy*18),tip,(255,232,183,220),2)
            elif phase == 'impact' and cast:
                angle=i*math.tau/4+.35
                xx,yy=b[0]+math.cos(angle)*(12+p*15),b[1]+math.sin(angle)*(12+p*12)
                _star(d,xx,yy,8*(1-p)+3,(255,202,133,round(235*(1-p))),5,angle)

    def _active_actions(self,t):
        right=bisect_right(self._action_times,t+1e-9)
        left=bisect_right(self._action_times,t-2.1)
        active=[]
        for event,timing in self._actions[left:right]:
            lifetime = retro_native.lifetime(event[4]) if event[1]=='cast' else .5
            phase=self._phase(timing,t,lifetime)
            if phase is None or timing.secondary:
                continue
            if event[1] == 'attack' and self.view._projectile_cancelled(event):
                continue
            active.append((event,timing,*phase))
        # Main casts are emphasised; every landed state and damage number remains.
        active.sort(key=lambda row:(row[0][1]!='cast',abs(t-row[1].impact),row[0][2]))
        return active[:MAX_ACTIVE_ACTIONS]

    def _configured_material(self,d,element,a,b,phase,p,cast,seed,config):
        scale = config['effect_scale']
        end = (a[0]+(b[0]-a[0])/scale, a[1]+(b[1]-a[1])/scale)
        draw = _ScaledDraw(d,a,scale) if scale != 1. else d
        self._material(draw,element,a,end,phase,p,cast,seed,config)

    def _draw_actions(self,img,t):
        layer=Image.new('RGBA',img.size)
        d=ImageDraw.Draw(layer)
        active=self._active_actions(t)
        for event,timing,phase,p in reversed(active):
            source=self.view.units[event[2]]
            target=self.view.units[event[3]]
            a=self.cell_point(timing.source_pos); b=self.cell_point(timing.target_pos)
            a=(a[0],a[1]-36);b=(b[0],b[1]-35)
            emitters=self._action_emitters(source,timing,phase,t)
            a=emitters[0]
            config=self.visual_config(source.u.piece.species_id)
            cast=event[1]=='cast'
            move=event[4] if cast else ''
            element=self.anim.move_type.get(move,source.u.piece.types[0]) if cast else source.u.piece.types[0]
            team=source.u.team
            if cast and retro_native.draw(layer,move,a,b,phase,min(1.,max(0.,p)),config,
                                          emitters=tuple(emitters),
                                          targeting=native_targeting(event,self.anim.by_idx),
                                          field_cells=tuple((self.cell_point(cell)[0],self.cell_point(cell)[1]-3)
                                              for cell in self._field_footprints.get(timing.source_index, ()))):
                # Authored native choreography replaces the generic overlay.
                continue
            rgb=arena_vfx.ELEMENT_COLORS.get(element,PAPER)
            if phase in ('windup','flight'):
                color=(*ALLY,100) if team == 0 else (*ENEMY,100)
                if cast:
                    for j in range(0,16,2):
                        aa=(a[0]+(b[0]-a[0])*j/16,a[1]+(b[1]-a[1])*j/16)
                        bb=(a[0]+(b[0]-a[0])*(j+1)/16,a[1]+(b[1]-a[1])*(j+1)/16)
                        _line(d,aa,bb,color,2)
                _ring(d,(b[0],b[1]+34),29,(*rgb,190),2,.35)
                _ring(d,self.cell_point(timing.source_pos),40,(*rgb,190),2,.31)
            if not cast and source.u.range <= 1 and phase == 'flight':
                _arrow(d,a,b,(*rgb,160),3,12)
            pp=min(1.,max(0.,p))
            dual_cannon = cast and move=='arena_twin_cannon' and phase=='flight'
            if (phase=='windup' or dual_cannon) and len(emitters)>1:
                for emitter in emitters:
                    self._configured_material(d,element,emitter,b,phase,pp,cast,source.u.piece.species_id,config)
            else:
                self._configured_material(d,element,a,b,phase,pp,cast,source.u.piece.species_id,config)
            if source.u.piece.species_id==68 and (not cast or move=='arena_four_arm_combo'):
                self._arm_trails(d,emitters,b,phase,pp,cast)
            k=0. if phase == 'windup' else p if phase == 'flight' else 1.
            point=(a[0]+(b[0]-a[0])*k,a[1]+(b[1]-a[1])*k)
            if phase == 'impact' or (cast and phase != 'windup'):
                motif=self._motif(source.u.piece.species_id,move,element,phase,
                                  min(8,max(0,round(p*8))),team,config['palette'],config['effect_scale'])
                layer.alpha_composite(motif,(round(point[0]-motif.width/2),round(point[1]-motif.height/2)))
        img.alpha_composite(layer)
        self._last_metrics={'active_actions':len(active),'active_casts':sum(e[0][1]=='cast' for e in active)}

    def _draw_displacement_wake(self, img, origin, destination, progress, element, config):
        """Low ground material follows the recorded displacement, without arrows."""
        if not 0 <= progress < 1 or origin == destination:
            return
        if element == 'WATER':
            retro_water.draw_wake(img, origin, destination, progress, config)
            return
        # Short overlapping dust lobes, drawn on a pixel grid. The travelling
        # center stays on the actual ground segment and never chooses a victim.
        layer = Image.new('RGBA', (WIDTH//3, HEIGHT//3))
        draw = ImageDraw.Draw(layer)
        scale = config['effect_scale']
        dx, dy = destination[0]-origin[0], destination[1]-origin[1]
        length = math.hypot(dx,dy) or 1.
        nx,ny = -dy/length,dx/length
        colors = ((87,86,70),(163,149,107),(218,202,149))
        q = min(1.,progress*1.25)
        for i in range(5):
            along = q-i*.09
            if along < 0:
                continue
            side = math.sin(progress*5+i*1.8)*(5+i*2)*scale
            x = (origin[0]+dx*along+nx*side)/3
            y = (origin[1]+dy*along+ny*side)/3
            radius = (6+i*1.8)*(1-progress)*scale/3
            if radius < .4:
                continue
            alpha = round((130-i*12)*(1-progress))
            draw.ellipse((round(x-radius),round(y-radius*.46),
                          round(x+radius),round(y+radius*.46)),fill=(*colors[1],alpha))
            draw.arc((round(x-radius),round(y-radius*.46),
                      round(x+radius),round(y+radius*.46)),195,330,
                     fill=(*colors[2],min(180,alpha+20)),width=1)
        img.alpha_composite(layer.resize(img.size,Image.Resampling.NEAREST))

    def _draw_outcomes(self,img,t):
        d=ImageDraw.Draw(img)
        for event in self.anim.timeline.recent_events(t,retro_native.LIFETIME):
            kind=event[1]
            native_key=retro_native.effect_key(event,self.anim.events)
            if kind=='regen':
                if (len(event)!=4 or type(event[2]) is not int or event[2] not in self.view.units
                        or not _positive_heal_amount(event[3])):
                    continue
                target=event[2]
                index=self.anim.timeline.source_index_by_event.get(id(event))
                owner=self._healing_by_regen.get(index,{})
                key=owner.get('key')
                source=owner.get('source',target)
                lifetime=retro_native.LIFETIME if key else .6
                age=t-event[0]
                if not 0<=age<lifetime:
                    continue
                position=owner.get('target_pos')
                b=(self.cell_point(position) if position is not None
                   else self._old_point(self.view.units[target].render_px(t)))
                b=(b[0],b[1]-34)
                config=self.visual_config(self.view.units[source].u.piece.species_id)
                if owner.get('reaction') == 'element_bloom':
                    origin=owner.get('source_pos')
                    a=self.cell_point(origin) if origin is not None else b
                    if origin is not None:
                        a=(a[0],a[1]-34)
                    layer=Image.new('RGBA',(img.width//3,img.height//3))
                    arena_vfx.draw_combination(layer,'element_bloom','heal',
                        (a[0]/3,a[1]/3),(b[0]/3,b[1]/3),age/lifetime,owner['payload'])
                    img.alpha_composite(layer.resize(img.size,Image.Resampling.NEAREST))
                    continue
                if key:
                    origin=owner.get('source_pos')
                    a=(self.cell_point(origin) if origin is not None else
                       self._old_point(self.view._event_position(source,event[0])))
                    details=owner['payload']
                    if details.get('amount')!=event[3]:
                        details={**details,'amount':event[3]}
                    retro_native.draw_outcome(img,key,'heal',(a[0],a[1]-34),b,
                        age,config,details)
                else:
                    retro_support.draw_healing(img,b,age/lifetime,config)
                continue
            if kind=='arena_heal':
                # The companion regen owns both actual material and HP float.
                continue
            if not native_key and t-event[0]>=.6:
                continue
            if kind not in ('skill_effect','combo_effect','field_effect','arena_heal','tactical_effect'):
                continue
            if kind=='tactical_effect' and len(event)==6:
                source,target,effect,payload=event[2:]
                if (effect not in ('guard','healing_block') or not isinstance(payload,dict)
                        or source not in self.view.units or target not in self.view.units):
                    continue
                a=self.cell_point(payload['source_pos'])
                b=self.cell_point(payload['target_pos'])
            elif len(event) == 7 and isinstance(event[6],dict):
                source,target,key,effect,payload=event[2:]
                if source not in self.view.units or target not in self.view.units:
                    continue
                apos=payload.get('origin_pos',payload.get('source_pos',payload.get('caster_pos')))
                bpos=payload.get('target_pos')
                a=self.cell_point(apos) if apos is not None else self._old_point(self.view._event_position(source,event[0]))
                b=self.cell_point(bpos) if bpos is not None else self._old_point(self.view._event_position(target,event[0]))
                if kind=='field_effect' and effect not in ('enter','clear','apply'):
                    continue
            else:
                continue
            age=t-event[0]; p=min(1.,age/.6)
            a=(a[0],a[1]-34);b=(b[0],b[1]-34)
            if kind=='combo_effect':
                if effect == 'heal':
                    # Its real child regen owns the single healing material and HP float.
                    continue
                # Applied interaction tracks use exact endpoints and the same
                # pixel grid as native materials, without speculative hits.
                layer = Image.new('RGBA', (img.width//3,img.height//3))
                if key in ('metronome', 'bond_combo'):
                    a = b
                arena_vfx.draw_combination(layer,key,effect,(a[0]/3,a[1]/3),
                    (b[0]/3,b[1]/3),p,payload)
                img.alpha_composite(layer.resize(img.size,Image.Resampling.NEAREST))
                continue
            if effect=='heal':
                amount=payload.get('amount')
                if (type(amount) in (int,float) and math.isfinite(amount) and amount<=0):
                    c=(248,146,124)
                    _line(d,(b[0]-9,b[1]-9),(b[0]+9,b[1]+9),c,3)
                    _line(d,(b[0]-9,b[1]+9),(b[0]+9,b[1]-9),c,3)
                # Positive heals are presented once by their actual child regen.
                continue
            if native_key and retro_native.draw_outcome(img,native_key,effect,a,b,age,
                    self.visual_config(self.view.units[source].u.piece.species_id),payload):
                # Actual regen records already supply the single HP amount in
                # _draw_numbers; native cels should not print it a second time.
                continue
            if effect=='cleanse':
                c=(117,242,175)
                if source != target:
                    _line(d,a,b,(98,175,134),2)
                    q=(a[0]+(b[0]-a[0])*p,a[1]+(b[1]-a[1])*p)
                    _star(d,*q,7,c)
                _ring(d,(b[0],b[1]+31),24+p*15,c,2,.4)
                yy=b[1]-5-p*22
                d.line((b[0]-8,yy,b[0]+8,yy),fill=c,width=4)
                d.line((b[0],yy-8,b[0],yy+8),fill=c,width=4)
            elif effect=='healing_block':
                c=(253,168,110)
                tip=(a[0]+(b[0]-a[0])*min(1.,p*2),a[1]+(b[1]-a[1])*min(1.,p*2))
                _line(d,a,tip,c,3)
                _line(d,(tip[0]-5,tip[1]-5),(tip[0]+5,tip[1]+5),PAPER,2)
            elif effect in ('guard','shield','absorb'):
                retro_support.draw_dome(img,b,p,
                    self.visual_config(self.view.units[source].u.piece.species_id),
                    element='STEEL' if effect=='guard' else 'ICE')
            elif effect in ('energy','energy_drain'):
                c=(196,162,248)
                _line(d,a,b,c,2)
                xx,yy=a[0]+(b[0]-a[0])*p,a[1]+(b[1]-a[1])*p
                _star(d,xx,yy,9,c)
            elif effect in ('knockback','pull'):
                destination=payload.get('destination',payload.get('to'))
                if destination is not None and len(destination)==2:
                    point=self.cell_point(destination)
                    element = self.anim.move_type.get('arena_'+native_key,
                        self.view.units[source].u.piece.types[0]) if native_key else self.view.units[source].u.piece.types[0]
                    self._draw_displacement_wake(img,(b[0],b[1]+31),(point[0],point[1]-3),p,
                        element,self.visual_config(self.view.units[source].u.piece.species_id))
            elif effect in ('side_hit','chain','splash','pierce','echo','follow_up','adjacent','shock'):
                if payload.get('damage',payload.get('amount',0)) <= 0:
                    continue
                element=payload.get('move_type',payload.get('type',payload.get('element',self.view.units[source].u.piece.types[0])))
                c=arena_vfx.ELEMENT_COLORS.get(element,PAPER)
                _arrow(d,a,b,c,2,8)
                self._configured_material(d,element,a,b,'impact',min(1.,p),True,source,
                                          self.visual_config(self.view.units[source].u.piece.species_id))

    def _draw_numbers(self,img,t):
        d=ImageDraw.Draw(img)
        for at,x,y,text,color in self.view.floats[-60:]:
            age=t-at
            if not 0 <= age < .8:
                continue
            xx,yy=self._old_point((x,y))
            size,stroke,fill=18,2,color
            if text.startswith('-'):
                tier=self._cast_float_tiers.get((round(at,3),text))
                if tier is None:
                    # Basic attacks and chip damage stay quiet next to casts.
                    size,stroke=15,1
                else:
                    element,eff=tier
                    fill=arena_vfx.ELEMENT_COLORS.get(element,FULL_GOLD)
                    size,stroke=(28,3) if eff>=2 else (24,3)
            _text(d,(xx+29,yy-52-24*age/.8),text,size,fill,anchor='ma',bold=True,stroke=stroke)
        for at,point in self._misses:
            age=t-at
            if 0 <= age < .8:
                _text(d,(point[0]+29,point[1]-52-24*age/.8),'MISS',15,(198,208,198),
                      anchor='ma',bold=True,stroke=1)

    def _draw_impact_accents(self,img,t):
        """Flash, ground shockwave and debris at each recent real impact."""
        if not IMPACT_ACCENTS:
            return
        start=bisect_right(self._impact_times,t-.5)
        end=bisect_right(self._impact_times,t+1e-9)
        if start>=end:
            return
        layer=Image.new('RGBA',(WIDTH//3,HEIGHT//3))
        d=ImageDraw.Draw(layer)
        for i in range(start,end):
            at,weight,pos,element=self._impacts[i]
            age=t-at
            p=age/.3
            x0,y0=self.cell_point(pos)
            y0-=30
            x,y=x0/3,y0/3
            rgb=_effect_color(arena_vfx.ELEMENT_COLORS.get(element,PAPER),'classic')
            heavy=weight>=1.6
            ko=weight>=2.4
            if age<.12:
                q=age/.12
                r=(9 if heavy else 6)*(1+q*.6)
                alpha=round(190*(1-q))
                color=(255,255,255) if ko else rgb
                d.ellipse((x-r,y-r*.9,x+r,y+r*.9),fill=(*color,alpha))
                core=r*.45
                d.ellipse((x-core,y-core*.9,x+core,y+core*.9),
                          fill=(*PAPER,min(255,alpha+50)))
            for j in range(2):
                q=min(1.,p*1.6-j*.25)
                if q<=0:
                    continue
                rr=(4+15*q)*(1.25 if heavy else 1.)
                alpha=round(140*(1-q)*(.7 if j else 1.))
                if alpha>0:
                    d.ellipse((x-rr,y+7-rr*.32,x+rr,y+7+rr*.32),
                              outline=(*rgb,alpha),width=1)
            for j in (self._particles(6 if heavy else 4,1.) if p<1. else ()):
                angle=(j*2.399+i*1.7)%math.tau
                speed=70+(j*37%55)
                vx=math.cos(angle)*speed
                vy=-abs(math.sin(angle))*speed*.75-25
                xx=(x0+vx*age)/3
                yy=(y0+vy*age+450*age*age)/3
                alpha=round(210*(1-p))
                if alpha>0:
                    d.rectangle((xx-1,yy-1,xx+1,yy+1),fill=(*rgb,alpha))
            # A KO keeps a slower crack ring alive past the standard window.
            if ko and age<.5:
                q=age/.5
                rr=8+30*q
                alpha=round(170*(1-q))
                if alpha>0:
                    d.ellipse((x-rr,y+7-rr*.34,x+rr,y+7+rr*.34),
                              outline=(*PAPER,alpha),width=2)
                    for j in range(4):
                        angle=(j*math.tau/4+i*.9)%math.tau
                        d.line((x+math.cos(angle)*rr*.45,y+7+math.sin(angle)*rr*.15,
                                x+math.cos(angle)*rr,y+7+math.sin(angle)*rr*.34),
                               fill=(*rgb,alpha),width=2)
        img.alpha_composite(layer.resize(img.size,Image.Resampling.NEAREST))

    def _ult_overlay_state(self, t):
        """(dim alpha, flash) of the ult palette performance; pure in t.

        The field dims as a high-power cast winds up (Hyper Beam style), and
        the impact frame runs a three-step white/black/white palette flicker.
        Both cover only the field area; the HUD band is composited later.
        """
        dim = 0
        flash = None
        for start, release, impact, target, pos, element, seq in self._ults:
            if start <= t < impact:
                q = (t-start)/max(.001, impact-start)
                dim = max(dim, round(_ULT_DIM_PEAK*q*q))
            age = t-impact
            if 0 <= age < len(_ULT_FLASH_ALPHAS)*.05:
                flash = _ULT_FLASH_ALPHAS[int(age*20)]
        return dim, flash

    def _draw_ult_overlay(self, img, t):
        """Full-field dim/flash for ults, drawn after the shake paste.

        The overlay is translation-invariant, so it is safe to apply over the
        shaken field; it stops at _HUD_BAND_TOP, and meters/HUD draw after it.
        """
        if not IMPACT_ULT:
            return
        dim, flash = self._ult_overlay_state(t)
        if dim <= 0 and flash is None:
            return
        overlay = Image.new('RGBA', (WIDTH, _HUD_BAND_TOP))
        d = ImageDraw.Draw(overlay)
        if dim > 0:
            d.rectangle((0, 0, WIDTH, _HUD_BAND_TOP), fill=(4, 8, 9, dim))
        if flash is not None:
            color, alpha = flash
            d.rectangle((0, 0, WIDTH, _HUD_BAND_TOP), fill=(*color, alpha))
        img.alpha_composite(overlay, (0, 0))

    # Metronomic burst salvos: ring and cross templates alternate every
    # _ULT_BURST_BEAT seconds, positions from a preset offset table plus
    # jitter seeded by (action sequence, batch, particle).
    _ULT_BURST_OFFSETS = (
        ((0,-1),(1,0),(0,1),(-1,0),(.7,-.7),(.7,.7),(-.7,.7),(-.7,-.7)),
        ((0,-1),(1,0),(0,1),(-1,0)),
    )

    def _draw_ult_bursts(self, img, t):
        """Batched particle salvos after an ult hit; counts into the budget."""
        if not IMPACT_ULT:
            return
        span = _ULT_BURST_BEAT*(_ULT_BURST_BATCHES-1)+_ULT_BURST_LIFE
        rows = [row for row in self._ults if 0 <= t-row[2] < span]
        if not rows:
            return
        layer = Image.new('RGBA', (WIDTH//3, HEIGHT//3))
        d = ImageDraw.Draw(layer)
        for start, release, impact, target, pos, element, seq in rows:
            age = t-impact
            x0, y0 = self.cell_point(pos)
            y0 -= 30
            rgb = _effect_color(arena_vfx.ELEMENT_COLORS.get(element, PAPER), 'classic')
            for batch in range(_ULT_BURST_BATCHES):
                bage = age-batch*_ULT_BURST_BEAT
                if not 0 <= bage < _ULT_BURST_LIFE:
                    continue
                q = bage/_ULT_BURST_LIFE
                offsets = self._ULT_BURST_OFFSETS[batch % 2]
                reach = (26+batch*9)*(.35+.75*q)
                # Each salvo opens with its own expanding ring (大字爆炎 beat).
                if q < .55:
                    rr = 10+40*q/.55+batch*5
                    alpha = round(150*(1-q/.55))
                    if alpha > 0:
                        d.ellipse(((x0-rr)/3, (y0-rr*.5)/3, (x0+rr)/3, (y0+rr*.5)/3),
                                  outline=(*rgb, alpha), width=1)
                for i in self._particles(len(offsets), 1.):
                    ox, oy = offsets[i % len(offsets)]
                    jitter = random.Random(seq*131+batch*17+i*7)
                    jx, jy = jitter.uniform(-2, 2), jitter.uniform(-1.5, 1.5)
                    xx = x0/3+ox*reach/3+jx
                    yy = y0/3+oy*reach*.55/3+jy-q*3
                    alpha = round(230*(1-q))
                    if alpha <= 0:
                        continue
                    s = 1 if i % 3 else 2
                    d.rectangle((xx-s, yy-s, xx+s, yy+s), fill=(*rgb, alpha))
                    if i % 3 == 0:
                        d.rectangle((xx-.5, yy-.5, xx+.5, yy+.5),
                                    fill=(*PAPER, min(255, alpha+25)))
        img.alpha_composite(layer.resize(img.size, Image.Resampling.NEAREST))

    def _ult_darken_factor(self, idx, t):
        """Brightness multiplier for an ult target: dip near-black, pop back."""
        if not IMPACT_ULT:
            return 1.
        factor = 1.
        for start, release, impact, target, pos, element, seq in self._ults:
            if target != idx:
                continue
            age = t-impact
            if not 0 <= age < _ULT_DARKEN_WINDOW:
                continue
            q = age/_ULT_DARKEN_WINDOW
            k = q/.3 if q < .3 else 1. if q < .65 else 1-(q-.65)/.35
            factor = min(factor, 1-(1-_ULT_DARKEN_DEPTH)*max(0., min(1., k)))
        return factor

    def _entrance_squash(self, idx, t):
        """A brief local settle as the landing drop ends; pure function of t."""
        land = self._entrance_land.get(idx)
        if land is None:
            return 1.
        age = t-land
        if not 0 <= age < _ENTRANCE_SQUASH:
            return 1.
        return 1.-.06*(1-age/_ENTRANCE_SQUASH)

    def _draw_entrances(self, img, t):
        """Landing dust ring, faction flash and star motes at each opening deploy."""
        rows = [row for row in self._entrances if 0 <= t-row[0] < .3]
        if not rows:
            return
        layer = Image.new('RGBA', (WIDTH//3, HEIGHT//3))
        d = ImageDraw.Draw(layer)
        for land, idx, pos, team, star in rows:
            age = t-land
            p = age/.3
            x0, y0 = self.cell_point(pos)
            x, y = x0/3, (y0+2)/3
            # Expanding dust ring dissolves within 0.3s.
            rr = 5+24*p
            alpha = round(150*(1-p))
            if alpha > 0:
                d.ellipse((x-rr, y-rr*.34, x+rr, y+rr*.34),
                          outline=(218, 202, 149, alpha), width=2)
            # Pixel grit kicked outward; every mote is a function of (idx, i, t).
            for i in self._particles(5, .8):
                angle = (i*2.399+idx*1.317) % math.tau
                radius = 4+19*p
                xx = x+math.cos(angle)*radius
                yy = y+math.sin(angle)*radius*.4-p*2
                shade = (163, 149, 107) if i % 2 else (218, 202, 149)
                alpha = round(200*(1-p))
                if alpha > 0:
                    d.rectangle((xx-1, yy-1, xx+1, yy), fill=(*shade, alpha))
            # Faction flash: a short team-coloured ring hugging the base.
            if age < .2:
                q = age/.2
                color = ALLY if team == 0 else ENEMY
                rr = 9+8*q
                d.ellipse((x-rr, y-rr*.36, x+rr, y+rr*.36),
                          outline=(*color, round(210*(1-q))), width=2)
            # Three-star arrivals scatter a few gold motes.
            if star >= 3:
                for i in range(3):
                    angle = i*math.tau/3+idx*.71
                    xx = x+math.cos(angle)*(6+9*p)
                    yy = y-2-p*7-math.sin(angle)*2
                    alpha = round(220*(1-p))
                    if alpha > 0:
                        _star(d, xx, yy, 2.2, (*FULL_GOLD, alpha))
        img.alpha_composite(layer.resize(img.size, Image.Resampling.NEAREST))

    def _topple(self, sprite, left, top, x, y, au, t):
        """The body tips around its foot anchor toward the killing blow."""
        ko = self._ko_by_idx.get(au.u.idx)
        if ko is None:
            return sprite, left, top
        k = min(1., max(0., t-au.die_t)/_TOPPLE_TIME)
        k = 1-(1-k)*(1-k)
        theta = -21*k if ko[4] >= 0 else 21*k
        rotated = sprite.rotate(theta, resample=Image.Resampling.NEAREST, expand=True)
        rad = math.radians(theta)
        ax, ay = x-left, y-top
        cx, cy = sprite.width/2, sprite.height/2
        nx = rotated.width/2+(ax-cx)*math.cos(rad)+(ay-cy)*math.sin(rad)
        ny = rotated.height/2-(ax-cx)*math.sin(rad)+(ay-cy)*math.cos(rad)
        slide = 6*k
        fx = x+ko[4]*slide
        fy = y+abs(ko[5])*slide*.5+2*k
        return rotated, round(fx-nx), round(fy-ny)

    @staticmethod
    @lru_cache(maxsize=1)
    def _ko_card_art():
        """Chunky pixel plaque, authored small and upscaled with NEAREST."""
        card = Image.new('RGBA', (86, 32))
        d = ImageDraw.Draw(card)
        d.rounded_rectangle((1, 5, 84, 30), radius=4, fill=(16, 33, 35, 235),
                            outline=(255, 214, 111), width=1)
        _text(d, (43, 7), '击倒', 15, (255, 226, 130), anchor='ma', bold=True, stroke=1)
        return card.resize((172, 64), Image.Resampling.NEAREST)

    def _draw_ko_cards(self, img, t):
        """A popping '击倒' card over each fresh KO; never reaches the HUD band."""
        rows = [row for row in self._ko_shows if 0 <= t-row[0] < _KO_CARD_LIFE]
        if not rows:
            return
        card = self._ko_card_art()
        for die_t, idx, pos, team, dx, dy in rows:
            age = t-die_t
            x0, y0 = self.cell_point(pos)
            pop = 1.+.25*max(0., 1-age/.1)
            w, h = round(card.width*pop), round(card.height*pop)
            frame = card.resize((w, h), Image.Resampling.NEAREST)
            alpha = round(255*min(1., (_KO_CARD_LIFE-age)/.15))
            if alpha < 255:
                frame = frame.copy()
                frame.putalpha(frame.getchannel('A').point(lambda value: value*alpha//255))
            px = min(max(round(x0-w/2), 8), WIDTH-8-w)
            py = max(64, round(y0-96-h))
            img.alpha_composite(frame, (px, py))

    def _draw_ambient(self,img,t):
        """Low-density ambient motes behind the units, seeded and looped."""
        if not AMBIENT_PARTICLES:
            return
        name=self.view.weather_name
        layer=Image.new('RGBA',(WIDTH//3,HEIGHT//3))
        d=ImageDraw.Draw(layer)
        frame=math.floor(t*20)
        if name=='rain':
            # Distant drizzle sheet sits behind the units: drawn straight onto
            # the field here, before any actor is pasted. Palette grey-blue,
            # one step above the rain tiles; integer pixels per 20fps frame.
            back=ImageDraw.Draw(img)
            for i in self._particles(8,1.):
                x=(140+i*97+frame*7)%720
                y=(100+i*67+frame*11)%470
                _line(back,(x,y),(x-2,y+8),(108,130,138),1)
            # Low mist rings step through three discrete sizes, never a
            # continuous fade, so they read as pixel animation.
            for i in self._particles(6,.8):
                x=(53+i*97)%320
                y=118+(i*53)%72
                stage=((frame+i*5)%12)//4
                r=2+stage*2
                alpha=(66,46,28)[stage]
                d.ellipse((x-r,y-r*.4,x+r,y+r*.4),
                          outline=(120,150,160,alpha),width=1)
            # Raindrop landing ripples: seeded ground spots expanding through
            # three fixed pixel sizes instead of a smooth alpha gradient.
            for i in self._particles(7,.8):
                spot=random.Random(911+i)
                x=spot.randrange(38,282)
                y=spot.randrange(84,178)
                stage=((frame+i*11)%24)//3
                if stage<3:
                    r=1+stage*2
                    alpha=(120,84,52)[stage]
                    d.ellipse((x-r,y-r*.35,x+r,y+r*.35),
                              outline=(146,174,182,alpha),width=1)
        elif name=='sun':
            for i in self._particles(10,.8):
                x=(37+i*61+frame)%320
                y=(60+(i*41)%120+frame//4)%213
                twinkle=.5+.5*math.sin(t*2+i*1.7)
                d.point((x,y),fill=(245,230,160,round(70+60*twinkle)))
            # Drifting light patches on the ground, barely above the tiles.
            for i in self._particles(4,.8):
                spot=random.Random(311+i)
                y=spot.randrange(96,172)
                x=(spot.randrange(0,320)+frame//7+i*47)%320
                rx=16+spot.randrange(0,14)
                pulse=.5+.5*math.sin(t*.4+i*1.3)
                d.ellipse((x-rx,y-rx*.3,x+rx,y+rx*.3),
                          fill=(246,233,174,round(8+8*pulse)))
        elif name=='sand':
            for i in self._particles(8,.8):
                x=(29+i*83+frame*3)%320
                y=150+(i*37)%50
                d.line((x,y,x+4,y-1),fill=(210,181,124,90),width=1)
            # Long horizontal drifts of blown sand along the ground.
            for i in self._particles(5,.8):
                spot=random.Random(511+i)
                y=spot.randrange(140,186)
                x=(spot.randrange(0,320)+frame*2+i*61)%340-20
                d.line((x,y,x+13,y),fill=(214,186,130,64),width=1)
                d.line((x+4,y+1,x+9,y+1),fill=(196,166,108,44),width=1)
        elif name!='hail':
            for i in self._particles(8,.7):
                x=(47+i*89)%320
                y=150+(i*43)%45+math.sin(t*.8+i*2.1)*3
                twinkle=.5+.5*math.sin(t*1.3+i*2.7)
                d.point((x,y),fill=(218,202,149,round(50+50*twinkle)))
        img.alpha_composite(layer.resize(img.size,Image.Resampling.NEAREST))

    def _draw_weather_transition(self,img,t):
        """Each recorded weather change pulses a 0.5s tint and pops a pixel icon.

        The tint stops above the HUD band; the icon lives beside the title and
        dissolves within a second. Pure function of (t, change index).
        """
        for change_t,name in self._weather_changes:
            age=t-change_t
            if not 0<=age<_WEATHER_ICON_LIFE:
                continue
            if age<_WEATHER_TRANSITION:
                tint=_WEATHER_TINTS.get(name,_WEATHER_TINTS[None])
                alpha=round(_WEATHER_TINT_PEAK*math.sin(math.pi*age/_WEATHER_TRANSITION))
                if alpha>0:
                    img.alpha_composite(
                        Image.new('RGBA',(WIDTH,_HUD_BAND_TOP),(*tint,alpha)),(0,0))
            if name in WEATHER_NAMES:
                icon=_weather_icon(name)
                fade=min(1.,(_WEATHER_ICON_LIFE-age)/.25)
                if fade<1.:
                    icon=icon.copy()
                    icon.putalpha(icon.getchannel('A').point(lambda a:round(a*fade)))
                img.alpha_composite(icon,(528,10))

    def _draw_weather(self,img,t):
        name=self.view.weather_name
        self._draw_weather_transition(img,t)
        if name not in WEATHER_NAMES:
            return
        d=ImageDraw.Draw(img)
        _text(d,(560,16),WEATHER_NAMES[name] + (' · 双方共享' if self.anim.is_arena else ''),10,(219,219,168),anchor='la')
        frame=math.floor(t*20)
        if name=='rain':
            # Foreground pass only: a sparse fast sheet in front of the units
            # (the distant drizzle is drawn behind them in _draw_ambient).
            # Palette grey-blue, 1px streaks, integer pixels per 20fps frame.
            for i in self._particles(6,1.):
                x=(120+i*131+frame*12)%718
                y=(110+i*89+frame*19)%460
                _line(d,(x,y),(x-4,y+14),(146,172,180),1)
        elif name=='hail':
            for i in self._particles(10,1.):
                drop=random.Random(733+i)
                top=70+drop.randrange(0,110)
                ground=300+drop.randrange(0,220)
                x=130+(i*67+drop.randrange(0,40))%700
                # Frame-quantised fall: whole pixels per frame, no subpixel
                # drift; chips kick for five frames after landing.
                pf=(frame+i*17)%40
                if pf<34:
                    _star(d,x,top+pf*(ground-top)//34,3,(210,239,242))
                elif pf<39:
                    spread=2+(pf-34)*2
                    _line(d,(x-spread,ground),(x-spread+2,ground-1),(210,239,242),1)
                    _line(d,(x+spread-2,ground-1),(x+spread,ground),(190,220,228),1)
        else:
            for i in self._particles(12,1.):
                x=120+(i*61+frame*(5 if name=='sand' else 1))%718
                y=115+(i*47+frame*5)%460
                if name=='sand':
                    _line(d,(x,y),(x+7,y-2),(210,181,124),2)
                else:
                    _star(d,x,y,2,(245,220,153))

    def _draw_hud(self,img,t):
        d=ImageDraw.Draw(img)
        _text(d,(480,561),f'{t:04.1f}s',12,(202,211,174),anchor='ma',stroke=1)
        # A direct actor → move → recipient line ties a flashy cast to its target.
        latest=[c for c in self.view.cutins[-12:] if c[0]<=t<c[1]+1.]
        latest.sort(key=lambda c:c[0],reverse=True)
        if latest:
            c=latest[0]
            source,target=self.view.units[c[2]].u,self.view.units[c[3]].u
            rgb=arena_vfx.ELEMENT_COLORS.get(c[7],PAPER)
            color=ALLY if source.team==0 else ENEMY
            d.rounded_rectangle((22,603,48,630),radius=6,fill=rgb)
            _text(d,(35,606),TYPE_NAMES.get(c[7],'招')[0],12,INK,anchor='ma',bold=True)
            label=self.anim.move_zh.get(c[4],c[4])
            raw = (0., 'cast', c[2], c[3], c[4], c[5], c[6])
            targeting = native_targeting(raw, self.anim.by_idx)
            recipient = ('岩钉区域' if targeting == 'field' else '自身架势' if targeting == 'self' else
                         target.piece.name + ('（友军）' if targeting == 'ally' else ''))
            _text(d,(60,608),f'{source.piece.name}  ›  {label}  ›  {recipient}',14,PAPER,bold=True)
            _text(d,(935,609),'我方施放' if source.team==0 else '对手施放',11,color,anchor='ra')
        else:
            msg=self.view.msg[1] if 0<=t-self.view.msg[0]<2. else '双方自动战斗 · 能量满时施放原生技能'
            _text(d,(26,609),msg,13,(192,212,187))
        if self.view.result is not None:
            won=self.view.result==0
            title='回合胜利' if won else '回合落败' if self.view.result==1 else '势均力敌'
            color=ALLY if won else ENEMY if self.view.result==1 else (226,208,141)
            # The result is only announced when the end event is actually applied.
            panel=Image.new('RGBA',(330,106))
            pd=ImageDraw.Draw(panel)
            pd.rounded_rectangle((0,0,329,105),radius=16,fill=(16,33,35,245),outline=color,width=2)
            _star(pd,37,52,15,color,5)
            _text(pd,(171,20),title,30,PAPER,anchor='ma',bold=True)
            _text(pd,(171,66),'战斗已结束 · 查看本轮战报',12,(181,203,176),anchor='ma')
            img.alpha_composite(panel,(315,268))
        elif t<.55:
            # Short, unobtrusive opening; no global cinematic interrupts play.
            _text(d,(480,311),'开战',34,PAPER,anchor='ma',bold=True,stroke=3)
            _line(d,(374,335),(424,335),(212,207,148),2)
            _line(d,(536,335),(586,335),(212,207,148),2)

    def frame(self,seconds):
        """Sim-clock frame: second s shows simulation time s (authoring contract)."""
        return self._render_frame(self.anim.timeline.time(seconds))

    def frame_playback(self,seconds):
        """Presentation-clock frame: heavy impacts hold for a short dwell."""
        return self._render_frame(self.anim.timeline.time(self._warp(seconds)))

    def presentation_time(self,t):
        """Inverse of _warp: first playback second showing simulation time t."""
        if len(self._warp_segments) == 1:
            return t
        index = max(0, bisect_left([s[1] for s in self._warp_segments], t)-1)
        pres, sim, slope = self._warp_segments[index]
        if slope == 0.:
            return pres
        return pres + (t-sim)/slope

    def _render_frame(self,t):
        self.view._ensure(t)
        self._frame_art={}
        self._particle_used=0
        base=_background(self.view.weather_name).convert('RGBA')
        field=base.copy()
        self._draw_terrain(field,t)
        self._draw_ambient(field,t)
        self._draw_entrances(field,t)
        shown=self._shown(t)
        try:
            for _,au,x,y,pose in shown:
                self._draw_unit(field,au,x,y,t)
            self._draw_actions(field,t)
            self._draw_impact_accents(field,t)
            self._draw_ult_bursts(field,t)
            self._draw_outcomes(field,t)
            self._draw_numbers(field,t)
            self._draw_ko_cards(field,t)
            self._draw_weather(field,t)
            # Only the battlefield shakes; readouts stay registered to the grid.
            offset=self._shake_offset(t)
            if offset!=(0,0):
                img=base
                img.paste(field,offset,field)
                # The HUD band is never shaken: restore it byte-identically so
                # even the wider ult sway cannot leak field pixels into it.
                img.paste(base.crop((0,_HUD_BAND_TOP,WIDTH,HEIGHT)),(0,_HUD_BAND_TOP))
            else:
                img=field
            # Full-field ult dim/flash sits above the (shaken) field but below
            # the readouts; it is translation-invariant and stops at the band.
            self._draw_ult_overlay(img,t)
            # Readouts are always the final field layer, protected from effects.
            for _,au,x,y,pose in shown:
                self._draw_meter(img,au,x,y,t)
            self._draw_hud(img,t)
        finally:
            self.view._frame_hit_context=None
            self.view._motion_context=None
            self._frame_art={}
        self._last_metrics.update(visible_units=len(shown), particles=self._particle_used,
                                  signature_tracks=self._last_metrics.get('active_casts',0),
                                  particle_limit=PARTICLE_LIMIT,
                                  signature_track_limit=MAX_ACTIVE_ACTIONS)
        return img.convert('RGB')
