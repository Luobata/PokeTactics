"""Small deterministic 2D part rigs, not skeletons or replacement hand-drawn art.

The three implemented rigs cut the existing single cel and add two original
pixel vines. Coordinates are percentages of the occupied source; track offsets
are native pixels. A bounded padded canvas and an explicit foot anchor allow a
part to extend outside the source rectangle. No battle state or RNG is read.
"""
from copy import deepcopy
import math
from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from esp32_runtime.animation import TRACK_FIELDS, sample_track, validate_track

SCHEMA_VERSION = 1
PADDING = 24
MAX_PARTS = 8
MAX_VINE_SEGMENTS = 12
REST = (0, 0, 0, 100, 100, 1)
PART_LABELS = {'body':'身体', 'far_wing':'远侧翅膀', 'near_arm':'近侧手臂与爪',
               'left_cannon':'左炮筒', 'right_cannon':'右炮筒', 'flower':'花盘',
               'left_vine':'左藤鞭', 'right_vine':'右藤鞭', 'ears':'耳朵', 'tail':'尾巴',
               'left_spoon':'左手汤匙', 'right_spoon':'右手汤匙', 'jaw':'下颌',
               'shadow':'下身阴影', 'left_arm':'左臂', 'right_arm':'右臂',
               'belly':'腹部', 'head':'头部'}


def _keys(*poses):
    return [[round(i / max(1, len(poses)-1), 6), *pose] for i, pose in enumerate(poses)]


def _clip(windup, strike, recover):
    return {'windup': _keys(*windup), 'strike': _keys(*strike), 'recover': _keys(*recover)}


def _part(name, bounds, pivot, layer, attachment=None):
    return {'name': name, 'label': PART_LABELS[name], 'source': {'kind': 'source_slice', 'bounds_percent': bounds},
            'pivot_percent': pivot, 'layer': layer, 'attachment': attachment}


def _vine(name, origin, layer):
    return {'name': name, 'label': PART_LABELS[name], 'source': {'kind': 'procedural_pixel_vine', 'origin_percent': origin},
            'pivot_percent': [0, 0], 'layer': layer, 'attachment': None}


def _entry(name, parts, anchors, attack=None, cast=None):
    return {'name': name, 'implemented': attack is not None,
            'art_method': 'source_cel_slices_and_original_pixel_vines' if name == 'Venusaur' else 'source_cel_slices',
            'parts': [_part('body', [0, 0, 100, 100], [50, 100], 0), *parts],
            'anchors': anchors, 'actions': {'attack': attack or {}, 'cast': cast or {}},
            'sample_ms': 50, 'track_fields': list(TRACK_FIELDS),
            'limits': {'parts': MAX_PARTS, 'padding_px': PADDING, 'vine_segments': MAX_VINE_SEGMENTS}}


_RIGS = {
    6: _entry('Charizard', [
        _part('far_wing', [63, 10, 100, 59], [5, 85], -1, 'left'),
        _part('near_arm', [9, 50, 37, 70], [95, 15], 2, 'right'),
    ], {'foot': {'position_percent': [50, 100]},
        'mouth': {'position_percent': [8, 20]},
        'claw': {'part': 'near_arm', 'position_percent': [10, 85]}}, {
        'near_arm': _clip([REST, (2, -3, -55, 100, 100, 1)],
                          [(2, -3, -55, 100, 100, 1), (-6, 1, 45, 115, 100, 1), (-3, 2, 22, 100, 100, 1)],
                          [(-3, 2, 22, 100, 100, 1), REST]),
        'far_wing': _clip([REST, (1, -1, 9, 100, 100, 1)],
                          [(1, -1, 9, 100, 100, 1), (-1, 1, -8, 100, 100, 1)],
                          [(-1, 1, -8, 100, 100, 1), REST]),
    }, {
        'near_arm': _clip([REST, (0, 1, 8, 100, 100, 1)],
                          [(0, 1, 8, 100, 100, 1), (1, 1, 12, 100, 100, 1)],
                          [(1, 1, 12, 100, 100, 1), REST]),
        'far_wing': _clip([REST, (0, -2, 18, 105, 100, 1)],
                          [(0, -2, 18, 105, 100, 1), (2, 1, -10, 100, 100, 1)],
                          [(2, 1, -10, 100, 100, 1), REST]),
    }),
    9: _entry('Blastoise', [
        _part('left_cannon', [14, 0, 33, 22], [78, 94], 1, 'bottom'),
        _part('right_cannon', [70, 16, 100, 53], [30, 94], 2, 'bottom'),
    ], {'foot': {'position_percent': [50, 100]},
        'left_muzzle': {'part': 'left_cannon', 'position_percent': [25, 12]},
        'right_muzzle': {'part': 'right_cannon', 'position_percent': [70, 12]},
        'mouth': {'position_percent': [13, 35]}}, {
        name: _clip([REST, (0, -1, -3, 100, 100, 1)],
                    [(3, 2, 5, 100, 92, 1), (1, 1, 2, 100, 98, 1)],
                    [(1, 1, 2, 100, 98, 1), REST])
        for name in ('left_cannon', 'right_cannon')
    }, {
        name: _clip([REST, (-1, -2, -8, 100, 105, 1)],
                    [(5, 3, 9, 100, 85, 1), (3, 2, 4, 100, 93, 1)],
                    [(3, 2, 4, 100, 93, 1), REST])
        for name in ('left_cannon', 'right_cannon')
    }),
    3: _entry('Venusaur', [
        _part('flower', [5, 0, 92, 43], [50, 92], 1, 'bottom'),
        _vine('left_vine', [20, 63], 2), _vine('right_vine', [74, 62], -1),
    ], {'foot': {'position_percent': [50, 100]},
        'flower_focus': {'part': 'flower', 'position_percent': [50, 25]},
        'left_vine_tip': {'part': 'left_vine', 'position_percent': [100, 100]},
        'right_vine_tip': {'part': 'right_vine', 'position_percent': [100, 100]}}, {
        'flower': _clip([REST, (0, 1, -3, 100, 96, 1)],
                       [(0, 1, -3, 100, 96, 1), (0, 0, 3, 100, 100, 1)],
                       [(0, 0, 3, 100, 100, 1), REST]),
        'left_vine': _clip([(0, 0, 0, 100, 100, 0), (2, -5, 0, 100, 100, 1)],
                          [(-8, -8, 0, 100, 100, 1), (-26, -3, 0, 100, 100, 1), (-18, 4, 0, 100, 100, 1)],
                          [(-18, 4, 0, 100, 100, 1), (0, 0, 0, 100, 100, 0)]),
        'right_vine': _clip([(0, 0, 0, 100, 100, 0), (6, -4, 0, 100, 100, 1)],
                           [(-12, -12, 0, 100, 100, 1), (-36, -8, 0, 100, 100, 1), (-25, 1, 0, 100, 100, 1)],
                           [(-25, 1, 0, 100, 100, 1), (0, 0, 0, 100, 100, 0)]),
    }, {
        'flower': _clip([REST, (0, -3, -5, 108, 108, 1)],
                       [(0, -3, -5, 108, 108, 1), (1, -1, 5, 103, 103, 1)],
                       [(1, -1, 5, 103, 103, 1), REST]),
    }),
    26: _entry('Raichu', [_part('ears', [4, 0, 81, 35], [50, 90], 1),
                          _part('tail', [70, 42, 100, 100], [0, 20], -1)],
                {'foot': {'position_percent': [50, 100]}, 'cheek': {'position_percent': [32, 30]}}),
    65: _entry('Alakazam', [_part('left_spoon', [0, 28, 26, 73], [90, 75], 1),
                           _part('right_spoon', [74, 28, 100, 73], [10, 75], 1)],
                {'foot': {'position_percent': [50, 100]}, 'focus': {'position_percent': [50, 28]}}),
    94: _entry('Gengar', [_part('jaw', [25, 44, 78, 78], [50, 10], 1),
                         _part('shadow', [0, 60, 100, 100], [50, 50], -1)],
                {'foot': {'position_percent': [50, 100]}, 'mouth': {'position_percent': [50, 56]}}),
    76: _entry('Golem', [_part('left_arm', [0, 31, 24, 73], [90, 10], 1),
                        _part('right_arm', [76, 31, 100, 73], [10, 10], 1)],
                {'foot': {'position_percent': [50, 100]}, 'ground': {'position_percent': [50, 100]}}),
    143: _entry('Snorlax', [_part('belly', [24, 40, 77, 88], [50, 100], 1),
                           _part('head', [25, 0, 78, 38], [50, 95], 2)],
                {'foot': {'position_percent': [50, 100]}, 'mouth': {'position_percent': [50, 24]}}),
}


def validate_rig(rig, *, species='unknown'):
    """Reject unrenderable content with a species/part/phase location.

    Named local parts are optional game content, not a shared humanoid skeleton.
    The body is controlled by motion.py; this format authors attack/cast parts.
    """
    prefix = f'rig/{species}'
    def fail(message):
        raise ValueError(f'{prefix}: {message}')
    if not isinstance(rig, dict) or type(rig.get('implemented')) is not bool:
        fail('expected a rig with explicit implemented flag')
    parts = rig.get('parts')
    if not isinstance(parts, list) or not 1 <= len(parts) <= MAX_PARTS:
        fail(f'expected 1–{MAX_PARTS} parts')
    names = []
    def coordinates(value, size=2):
        return (isinstance(value, (list, tuple)) and len(value) == size
                and all(type(v) in (int, float) and 0 <= v <= 100 for v in value))
    for part in parts:
        if not isinstance(part, dict) or not isinstance(part.get('name'), str) or not part['name']:
            fail('part must have a name')
        name = part['name']
        if name in names:
            fail(f'duplicate part {name}')
        names.append(name)
        if not coordinates(part.get('pivot_percent')):
            fail(f'{name}: invalid pivot')
        if type(part.get('layer')) is not int or not -MAX_PARTS <= part['layer'] <= MAX_PARTS:
            fail(f'{name}: invalid layer')
        source = part.get('source', {})
        if not isinstance(source, dict):
            fail(f'{name}: invalid source')
        if source.get('kind') == 'source_slice':
            box = source.get('bounds_percent')
            if not coordinates(box, 4) or box[0] >= box[2] or box[1] >= box[3]:
                fail(f'{name}: invalid source bounds')
        elif source.get('kind') == 'procedural_pixel_vine':
            if not coordinates(source.get('origin_percent')):
                fail(f'{name}: invalid vine origin')
        else:
            fail(f'{name}: unsupported source kind')
    if names[0] != 'body' or parts[0]['source'] != {'kind': 'source_slice', 'bounds_percent': [0, 0, 100, 100]}:
        fail('first part must be the full source body')
    anchors = rig.get('anchors')
    if not isinstance(anchors, dict) or 'foot' not in anchors:
        fail('missing foot anchor')
    if anchors['foot'] != {'position_percent': [50, 100]}:
        fail('foot anchor must use the fixed bottom-center convention')
    for name, anchor in anchors.items():
        if (not isinstance(anchor, dict) or not coordinates(anchor.get('position_percent'))
                or ('part' in anchor and anchor['part'] not in names[1:])):
            fail(f'anchor {name}: invalid position or unknown part')
    actions = rig.get('actions')
    if not isinstance(actions, dict) or set(actions) != {'attack', 'cast'}:
        fail('expected attack and cast action definitions')
    for action, tracks in actions.items():
        if not isinstance(tracks, dict) or bool(tracks) != rig['implemented']:
            fail(f'{action}: implemented rigs require tracks; planned rigs must have none')
        for part, phases in tracks.items():
            if part not in names[1:]:
                fail(f'{action}/{part}: unknown or whole-body part')
            if not isinstance(phases, dict) or set(phases) != {'windup', 'strike', 'recover'}:
                fail(f'{action}/{part}: missing or unknown phases')
            for phase, keys in phases.items():
                validate_track(keys, path=f'{prefix}/{action}/{part}/{phase}')
    if rig.get('track_fields') != list(TRACK_FIELDS) or rig.get('sample_ms') != 50:
        fail('unsupported track format or sample clock')
    if rig.get('limits') != {'parts': MAX_PARTS, 'padding_px': PADDING, 'vine_segments': MAX_VINE_SEGMENTS}:
        fail('unsupported rendering limits')
    return True


def catalog():
    """Detached JSON-safe species definitions; planned rigs are explicitly false."""
    for sid, rig in _RIGS.items():
        validate_rig(rig, species=sid)
    return {str(sid): deepcopy(rig) for sid, rig in _RIGS.items()}


def manifest_data():
    return {'schema_version': SCHEMA_VERSION, 'species': catalog()}


def implemented(sid):
    return sid in _RIGS and _RIGS[sid]['implemented']


def sample_rig(sid, kind, state, progress, facing=1):
    """Pure local track sampling. Facing mirrors coordinates and angle, not time."""
    if not math.isfinite(progress):
        raise ValueError('rig progress must be finite')
    rig = _RIGS.get(sid)
    if not rig or not rig['implemented'] or kind not in ('attack', 'cast'):
        return {}
    p = min(1., max(0., progress))
    result = {}
    for part in rig['parts']:
        keys = rig['actions'][kind].get(part['name'], {}).get(state)
        default = (*REST[:-1], 0) if part['source']['kind'] == 'procedural_pixel_vine' else REST
        values = default
        if keys:
            values = sample_track(keys, p)
        dx, dy, angle, sx, sy, visible = values
        # Source art faces left; canonical authoring is in source-art space.
        flip = -1 if facing >= 0 else 1
        result[part['name']] = {'dx': dx*flip, 'dy': dy, 'angle': angle*flip,
                                'scale_x': sx, 'scale_y': sy, 'visible': bool(visible),
                                'layer': part['layer']}
    return result


def _point_after_rotation(point, size, new_size, angle):
    theta = math.radians(angle)
    x, y = point[0]-size[0]/2, point[1]-size[1]/2
    return (math.cos(theta)*x + math.sin(theta)*y + new_size[0]/2,
            -math.sin(theta)*x + math.cos(theta)*y + new_size[1]/2)


def render_rig(sprite, sid, kind, state, progress, facing=1):
    """Synthesize a bounded local canvas and foot/attachment metadata, or None.

    The source cel is never mutated. Cut regions leave their free silhouette
    transparent; a small joint bridge joins their pivots. Vines are original
    12-segment pixel paths using the source palette, not hand-drawn new cels.
    """
    if not implemented(sid) or state == 'death':
        return None
    kind = kind if kind in ('attack', 'cast') else 'attack'
    rig = _RIGS[sid]
    poses = sample_rig(sid, kind, state, progress, facing=-1)
    bounds = sprite.getbbox()
    if not bounds:
        return None
    cel = sprite.crop(bounds)
    w, h = cel.size
    base = cel.copy()
    extracted = []
    anchors = {}
    for part in rig['parts'][1:]:
        if part['source']['kind'] != 'source_slice':
            continue
        box = tuple(round(v*(w if i % 2 == 0 else h)/100)
                    for i,v in enumerate(part['source']['bounds_percent']))
        if box[0] >= box[2] or box[1] >= box[3]:
            raise ValueError(f"rig/{sid}/{part['name']}: source slice is empty at {w}x{h}")
        tile = cel.crop(box)
        base.paste((0,0,0,0), box)
        extracted.append((part,box,tile))
    out = Image.new('RGBA',(sprite.width+2*PADDING,sprite.height+2*PADDING))
    origin = (PADDING+bounds[0],PADDING+bounds[1])
    layers = [(0, base, origin)]
    for part, box, tile in extracted:
        pose = poses[part['name']]
        pivot = (part['pivot_percent'][0]*tile.width/100,part['pivot_percent'][1]*tile.height/100)
        scaled = tile.resize((max(1,round(tile.width*pose['scale_x']/100)),
                              max(1,round(tile.height*pose['scale_y']/100))),Image.Resampling.NEAREST)
        scaled_pivot = (pivot[0]*scaled.width/tile.width,pivot[1]*scaled.height/tile.height)
        angle = -pose['angle']
        rotated = scaled.rotate(angle,Image.Resampling.NEAREST,expand=True)
        rotated_pivot = _point_after_rotation(scaled_pivot,scaled.size,rotated.size,angle)
        location = (round(origin[0]+box[0]+pivot[0]+pose['dx']-rotated_pivot[0]),
                    round(origin[1]+box[1]+pivot[1]+pose['dy']-rotated_pivot[1]))
        # A bounded two-pixel joint connects the moved attachment. Extending a
        # whole boundary row/column would produce rectangular stripes in wings.
        candidates = [(x,y) for y in range(tile.height) for x in range(tile.width)
                      if tile.getpixel((x,y))[3]]
        if candidates and pose['visible']:
            nearest = min(candidates,key=lambda xy:(xy[0]-pivot[0])**2+(xy[1]-pivot[1])**2)
            color = tile.getpixel(nearest)
            joint = Image.new('RGBA',out.size)
            start = (round(origin[0]+box[0]+pivot[0]),round(origin[1]+box[1]+pivot[1]))
            end = (start[0]+pose['dx'],start[1]+pose['dy'])
            if part['name'] == 'flower':
                color = max((pixel for pixel in cel.getdata() if pixel[3]),
                            key=lambda rgb:rgb[1]-rgb[0]-rgb[2]/2)
                start = (start[0],origin[1]+box[3]+1)
            ImageDraw.Draw(joint).line((start,end),fill=color,width=3 if part['name']=='flower' else 2)
            layers.append((part['layer']-.5,joint,(0,0)))
        if pose['visible']:
            layers.append((part['layer'],rotated,location))
        for name, anchor in rig['anchors'].items():
            if anchor.get('part') == part['name']:
                point = (anchor['position_percent'][0]*scaled.width/100,
                         anchor['position_percent'][1]*scaled.height/100)
                transformed = _point_after_rotation(point,scaled.size,rotated.size,angle)
                anchors[name] = [round(location[i]+transformed[i]) for i in (0,1)]
    opaque = [pixel[:3] for pixel in cel.getdata() if pixel[3]]
    colors = sorted(set(opaque),key=lambda rgb: sum(rgb))
    dark = colors[0]; green = max(colors,key=lambda rgb: rgb[1]-rgb[0]-rgb[2]/2)
    for part in rig['parts']:
        if part['source']['kind'] != 'procedural_pixel_vine':
            continue
        pose = poses[part['name']]
        xy = part['source']['origin_percent']
        start = (origin[0]+round(xy[0]*w/100),origin[1]+round(xy[1]*h/100))
        tip = (start[0]+pose['dx'],start[1]+pose['dy'])
        anchors[part['name']+'_tip'] = list(tip)
        if not pose['visible']:
            continue
        layer = Image.new('RGBA',out.size)
        draw = ImageDraw.Draw(layer)
        bend = -7 if part['name']=='right_vine' else 6
        control = ((start[0]+tip[0])/2,start[1]+bend)
        points = []
        for i in range(MAX_VINE_SEGMENTS+1):
            t=i/MAX_VINE_SEGMENTS
            points.append(tuple(round((1-t)**2*start[j]+2*(1-t)*t*control[j]+t*t*tip[j]) for j in (0,1)))
        draw.line(points,fill=(*dark,255),width=3)
        draw.line(points,fill=(*green,255),width=1)
        layers.append((part['layer'],layer,(0,0)))
    for _, image, position in sorted(layers,key=lambda item:item[0]):
        out.alpha_composite(image,position)
    foot = (PADDING+sprite.width/2,PADDING+bounds[3])
    for name, anchor in rig['anchors'].items():
        if 'part' not in anchor:
            xy = anchor['position_percent']
            anchors[name] = [origin[0]+round(xy[0]*w/100),origin[1]+round(xy[1]*h/100)]
    anchors['foot'] = list(foot)
    if facing >= 0:
        out = ImageOps.mirror(out)
        foot = (out.width-foot[0],foot[1])
        anchors = {name:[out.width-xy[0],xy[1]] for name,xy in anchors.items()}
    out.info['foot_anchor'] = foot
    out.info['rig_anchors'] = anchors
    out.info['rig_parts'] = len(rig['parts'])
    return out
