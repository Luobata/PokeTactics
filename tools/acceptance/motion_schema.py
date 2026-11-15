"""Schemas for data-driven battle motion and VFX (assets/motion, assets/vfx).

Motion keyframes reuse the portable 7-field contract from
esp32_runtime/animation.py — (at, dx, dy, angle, scale_x, scale_y, visible) —
and append one easing name: ``[at, dx, dy, angle, sx, sy, visible, ease]``.
The 7-field projection of every phase must pass ``validate_track`` unchanged,
so the device sampler and the browser sampler read the same data. The ease
names the curve from that key to the next (the last key's ease is unused).

Usage:
    python3 tools/acceptance/motion_schema.py            # validate all packs
    python3 tools/acceptance/motion_schema.py FILE.json  # validate one file
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from esp32_runtime.animation import TRACK_FIELDS, validate_track  # noqa: E402

SCHEMA_VERSION = 1
MOTION_DIR = ROOT / 'assets' / 'motion'
VFX_DIR = ROOT / 'assets' / 'vfx'
MAX_PACK_BYTES = 512 * 1024
NAME_PATTERN = re.compile(r'^[a-z][a-z0-9_]{0,39}$')
ID_PATTERN = re.compile(r'^[A-Za-z0-9_.:-]{1,64}$')
HEX = re.compile(r'^#[0-9a-fA-F]{6}$')

EASES = ('linear', 'step', 'easeInQuad', 'easeOutQuad', 'easeInOutQuad', 'easeInCubic',
         'easeOutCubic', 'easeInOutCubic', 'easeOutBack', 'easeInBack', 'easeOutElastic',
         'easeOutBounce', 'easeOutExpo', 'easeInExpo')
CLIP_SLOTS = ('idle', 'walk', 'attack_melee', 'attack_ranged', 'cast', 'hit', 'ko', 'victory')
PHASES = ('loop', 'anticipation', 'dash', 'contact', 'release', 'recover', 'react', 'fall')
SLOT_PHASES = {
    'idle': ('loop',), 'walk': ('loop',), 'victory': ('loop',),
    'attack_melee': ('anticipation', 'dash', 'contact', 'recover'),
    'attack_ranged': ('anticipation', 'release', 'recover'),
    'cast': ('anticipation', 'release', 'recover'),
    'hit': ('react',), 'ko': ('fall',),
}
TIMING_KEYS = {'anticipation': (0.04, 1.2), 'recover': (0.04, 1.2), 'cast_anticipation': (0.08, 1.6),
               'cast_recover': (0.06, 1.6), 'weight': (0.0, 1.0), 'dash_speed': (100, 4000),
               'offset_range': (0.0, 0.2), 'idle_period': (0.4, 6.0)}
ARCHETYPE_ATTACKS = ('melee', 'ranged', 'support', 'tank')

TYPES = ('NORMAL', 'FIRE', 'WATER', 'ELECTRIC', 'GRASS', 'ICE', 'FIGHTING', 'POISON', 'GROUND',
         'FLYING', 'PSYCHIC', 'BUG', 'ROCK', 'GHOST', 'DRAGON', 'DARK', 'STEEL', 'FAIRY')
LAYERS = ('charge', 'projectile', 'trail', 'impact', 'ground', 'aura', 'link', 'screen')
ANCHORS = ('start', 'anticipation', 'release', 'impact', 'recover', 'end')
SHAPES = {
    'charge': ('converge', 'glow', 'ring', 'spiral', 'sparks', 'rune_circle'),
    'projectile': ('family',),
    'trail': ('streak', 'afterimage', 'dust', 'ribbon'),
    'impact': ('burst', 'slash_arc', 'ring', 'shards', 'splash', 'sparks', 'flash', 'cross', 'petals',
               'shove', 'pierce_line', 'execute_slash', 'multi_hit', 'bite', 'claw', 'mark', 'stun_stars'),
    'ground': ('crack', 'ring_decal', 'spikes', 'puddle', 'shockwave', 'scorch', 'vines', 'vines_grow',
               'ring_expand', 'debris', 'rune_circle'),
    'aura': ('glow', 'sparkle_up', 'ring_rise', 'shield_dome', 'heal_plus', 'hex_dome', 'thorn_shell',
             'cross_glyph', 'motes_rise', 'cleanse_spiral', 'energy_orbs', 'shout_rings', 'mark',
             'buff_arrows', 'stun_stars'),
    'link': ('fork', 'stream', 'tether', 'hop_arc'),
    'screen': ('flash', 'shake', 'tint'),
}
OUTCOME_PATTERN = re.compile(r'^(\*|[a-z][a-z0-9_]{0,31})$')
RECIPE_FIELDS = {'layers', 'extends', 'add', 'drop', 'palette', 'family', 'scale', 'particle', 'note'}
LAYER_FIELDS = {'layer', 'shape', 'at', 'palette', 'curve', 'family', 'duration', 'offset', 'size', 'count',
                'alpha', 'intensity', 'particle', 'target', 'on', 'from', 'to'}
PART_FIELDS = ('at', 'lean', 'head_x', 'head_y', 'belly', 'wobble', 'ease')
PART_LIMITS = {'lean': (-24, 24), 'head_x': (-16, 16), 'head_y': (-16, 16), 'belly': (-30, 40), 'wobble': (0, 12)}
PROJECTILE_FAMILIES = ('straight', 'arc', 'homing', 'beam', 'ground', 'volley')
PARTICLES = ('ember', 'droplet', 'arc', 'leaf', 'shard', 'debris', 'wisp', 'ring', 'bubble',
             'flame', 'spark', 'sparkle', 'impact_ring', 'gust', 'mote', 'dust', 'slash')
SCREEN_KEYS = ('ult', 'ko', 'crit', 'shake', 'combo')


class SchemaError(ValueError):
    pass


def _number(value, lo, hi, path):
    if type(value) not in (int, float) or value != value or not lo <= value <= hi:
        raise SchemaError(f'{path}: expected number in [{lo}, {hi}]')
    return value


def _keys(keys, path):
    if not isinstance(keys, list):
        raise SchemaError(f'{path}: expected key list')
    track = []
    for index, key in enumerate(keys):
        if not isinstance(key, list) or len(key) != len(TRACK_FIELDS) + 1:
            raise SchemaError(f'{path}[{index}]: key must be [at, dx, dy, angle, sx, sy, visible, ease]')
        if key[-1] not in EASES:
            raise SchemaError(f'{path}[{index}]: unknown ease {key[-1]!r}')
        track.append(key[:-1])
    try:
        validate_track(track, path=path)
    except ValueError as exc:
        raise SchemaError(str(exc)) from None


def _part_keys(keys, path):
    """Part-deformation keys: [at, lean, head_x, head_y, belly%, wobble, ease]."""
    if not isinstance(keys, list) or not 2 <= len(keys) <= 16:
        raise SchemaError(f'{path}: expected 2–16 part keys')
    previous = -1
    for index, key in enumerate(keys):
        if not isinstance(key, list) or len(key) != len(PART_FIELDS):
            raise SchemaError(f'{path}[{index}]: key must be {list(PART_FIELDS)}')
        at = key[0]
        if type(at) not in (int, float) or not 0 <= at <= 1 or at <= previous:
            raise SchemaError(f'{path}: part key times must increase strictly within 0–1')
        previous = at
        for name, value in zip(PART_FIELDS[1:-1], key[1:-1]):
            _number(value, *PART_LIMITS[name], f'{path}[{index}].{name}')
        if key[-1] not in EASES:
            raise SchemaError(f'{path}[{index}]: unknown ease {key[-1]!r}')
    if keys[0][0] != 0 or keys[-1][0] != 1:
        raise SchemaError(f'{path}: part track must include endpoints 0 and 1')


def validate_motion_pack(pack, *, path='motion'):
    """Validate one motion pack; raises SchemaError with a readable path."""
    if not isinstance(pack, dict):
        raise SchemaError(f'{path}: pack must be an object')
    if pack.get('schema_version') != SCHEMA_VERSION or pack.get('kind') != 'motion_pack':
        raise SchemaError(f'{path}: expected schema_version {SCHEMA_VERSION} and kind motion_pack')
    unknown = set(pack) - {'schema_version', 'kind', 'name', 'description', 'clips',
                           'archetypes', 'species', 'notes'}
    if unknown:
        raise SchemaError(f'{path}: unknown fields {sorted(unknown)}')
    if not isinstance(pack.get('name'), str) or not NAME_PATTERN.match(pack['name']):
        raise SchemaError(f'{path}: name must match {NAME_PATTERN.pattern}')
    clips = pack.get('clips', {})
    if not isinstance(clips, dict):
        raise SchemaError(f'{path}.clips: expected object')
    for clip_id, clip in clips.items():
        here = f'{path}.clips.{clip_id}'
        if not ID_PATTERN.match(clip_id) or not isinstance(clip, dict):
            raise SchemaError(f'{here}: invalid clip')
        slot = clip.get('slot')
        if slot not in CLIP_SLOTS:
            raise SchemaError(f'{here}.slot: expected one of {CLIP_SLOTS}')
        if set(clip) - {'slot', 'phases', 'period', 'note', 'parts'}:
            raise SchemaError(f'{here}: unknown fields {sorted(set(clip) - {"slot", "phases", "period", "note", "parts"})}')
        parts = clip.get('parts', {})
        if not isinstance(parts, dict):
            raise SchemaError(f'{here}.parts: expected object')
        for name, keys in parts.items():
            if name not in SLOT_PHASES[slot]:
                raise SchemaError(f'{here}.parts.{name}: slot {slot} allows {SLOT_PHASES[slot]}')
            _part_keys(keys, f'{here}.parts.{name}')
        phases = clip.get('phases')
        if not isinstance(phases, dict) or not phases:
            raise SchemaError(f'{here}.phases: expected object')
        for name, keys in phases.items():
            if name not in SLOT_PHASES[slot]:
                raise SchemaError(f'{here}.phases.{name}: slot {slot} allows {SLOT_PHASES[slot]}')
            _keys(keys, f'{here}.phases.{name}')
        if 'period' in clip:
            _number(clip['period'], 0.2, 8.0, f'{here}.period')
    for group in ('archetypes', 'species'):
        rows = pack.get(group, {})
        if not isinstance(rows, dict):
            raise SchemaError(f'{path}.{group}: expected object')
        for key, row in rows.items():
            here = f'{path}.{group}.{key}'
            if group == 'species' and not re.fullmatch(r'[1-9][0-9]{0,3}', key):
                raise SchemaError(f'{here}: species keys are national dex numbers')
            if group == 'archetypes' and not NAME_PATTERN.match(key):
                raise SchemaError(f'{here}: invalid archetype name')
            if not isinstance(row, dict) or set(row) - {'clips', 'timing', 'archetype', 'family',
                                                        'attack', 'note'}:
                raise SchemaError(f'{here}: invalid fields')
            if 'attack' in row and row['attack'] not in ARCHETYPE_ATTACKS:
                raise SchemaError(f'{here}.attack: expected one of {ARCHETYPE_ATTACKS}')
            for slot, clip_id in (row.get('clips') or {}).items():
                if slot not in CLIP_SLOTS or not isinstance(clip_id, str) or not ID_PATTERN.match(clip_id):
                    raise SchemaError(f'{here}.clips.{slot}: invalid clip binding')
            for name, value in (row.get('timing') or {}).items():
                if name not in TIMING_KEYS:
                    raise SchemaError(f'{here}.timing.{name}: unknown timing key')
                _number(value, *TIMING_KEYS[name], f'{here}.timing.{name}')
            for name in ('archetype', 'family'):
                if name in row and (not isinstance(row[name], str) or not NAME_PATTERN.match(row[name])):
                    raise SchemaError(f'{here}.{name}: invalid name')
    return True


def _palette_ref(value, palettes, path):
    if value == '@type' or value in palettes or value in TYPES or value in ('HEAL', 'SHIELD', 'KO') \
            or (isinstance(value, str) and HEX.match(value)):
        return
    raise SchemaError(f'{path}: palette must be @type, a palette name or #rrggbb')


def _validate_layer(layer, where, palettes):
    if not isinstance(layer, dict) or layer.get('layer') not in LAYERS:
        raise SchemaError(f'{where}.layer: expected one of {LAYERS}')
    if layer.get('shape') not in SHAPES[layer['layer']]:
        raise SchemaError(f'{where}.shape: {layer["layer"]} allows {SHAPES[layer["layer"]]}')
    if layer.get('at', 'impact') not in ANCHORS:
        raise SchemaError(f'{where}.at: expected one of {ANCHORS}')
    if set(layer) - LAYER_FIELDS:
        raise SchemaError(f'{where}: unknown layer fields {sorted(set(layer) - LAYER_FIELDS)}')
    if 'palette' in layer:
        _palette_ref(layer['palette'], palettes, f'{where}.palette')
    if 'curve' in layer and layer['curve'] not in EASES:
        raise SchemaError(f'{where}.curve: unknown ease')
    if 'family' in layer and layer['family'] not in PROJECTILE_FAMILIES + ('@type',):
        raise SchemaError(f'{where}.family: unknown projectile family')
    for key, (lo, hi) in {'duration': (0.02, 3), 'offset': (-1, 1), 'size': (1, 240),
                          'count': (0, 48), 'alpha': (0, 1), 'intensity': (0, 3)}.items():
        if key in layer:
            _number(layer[key], lo, hi, f'{where}.{key}')
    if 'particle' in layer and layer['particle'] not in PARTICLES + ('@type',):
        raise SchemaError(f'{where}.particle: unknown particle')
    if 'target' in layer and layer['target'] not in ('actor', 'target', 'between', 'targets'):
        raise SchemaError(f'{where}.target: expected actor/target/between/targets')
    if 'on' in layer:
        subs = layer['on'] if isinstance(layer['on'], list) else [layer['on']]
        if not subs or not all(isinstance(v, str) and OUTCOME_PATTERN.match(v) for v in subs):
            raise SchemaError(f'{where}.on: expected outcome name(s) such as heal / side_hit / knockback')
    if layer.get('from', 'actor') not in ('actor', 'target', 'origin'):
        raise SchemaError(f'{where}.from: expected actor/target/origin')
    if layer.get('to', 'target') not in ('actor', 'target'):
        raise SchemaError(f'{where}.to: expected actor/target')


def validate_vfx_pack(pack, *, path='vfx'):
    if not isinstance(pack, dict):
        raise SchemaError(f'{path}: pack must be an object')
    if pack.get('schema_version') != SCHEMA_VERSION or pack.get('kind') != 'vfx_pack':
        raise SchemaError(f'{path}: expected schema_version {SCHEMA_VERSION} and kind vfx_pack')
    unknown = set(pack) - {'schema_version', 'kind', 'name', 'description', 'palettes', 'materials',
                           'projectiles', 'recipes', 'bindings', 'screen', 'notes'}
    if unknown:
        raise SchemaError(f'{path}: unknown fields {sorted(unknown)}')
    if not isinstance(pack.get('name'), str) or not NAME_PATTERN.match(pack['name']):
        raise SchemaError(f'{path}: name must match {NAME_PATTERN.pattern}')
    palettes = pack.get('palettes', {})
    for name, colors in palettes.items():
        if not ID_PATTERN.match(name) or not isinstance(colors, list) or len(colors) != 4 \
                or not all(isinstance(c, str) and HEX.match(c) for c in colors):
            raise SchemaError(f'{path}.palettes.{name}: expected [core, light, main, dark] hex colours')
    for name, row in pack.get('materials', {}).items():
        here = f'{path}.materials.{name}'
        if not isinstance(row, dict) or row.get('particle') not in PARTICLES:
            raise SchemaError(f'{here}.particle: expected one of {PARTICLES}')
        for key, (lo, hi) in {'gravity': (-600, 600), 'drag': (0, 1), 'count': (0, 48),
                              'spin': (-20, 20)}.items():
            if key in row:
                _number(row[key], lo, hi, f'{here}.{key}')
        for key, (lo, hi) in {'size': (0.5, 40), 'life': (0.05, 3), 'speed': (0, 900)}.items():
            if key in row:
                value = row[key]
                if not isinstance(value, list) or len(value) != 2:
                    raise SchemaError(f'{here}.{key}: expected [min, max]')
                for item in value:
                    _number(item, lo, hi, f'{here}.{key}')
    for name, row in pack.get('projectiles', {}).items():
        here = f'{path}.projectiles.{name}'
        if name not in PROJECTILE_FAMILIES or not isinstance(row, dict):
            raise SchemaError(f'{here}: family must be one of {PROJECTILE_FAMILIES}')
        for key, (lo, hi) in {'size': (1, 60), 'arc': (0, 2), 'count': (1, 8), 'stagger': (0, .3),
                              'wobble': (0, 60), 'width': (1, 60), 'trail': (0, 1)}.items():
            if key in row:
                _number(row[key], lo, hi, f'{here}.{key}')
    recipes = pack.get('recipes', {})
    for name, recipe in recipes.items():
        here = f'{path}.recipes.{name}'
        if not ID_PATTERN.match(name) or not isinstance(recipe, dict):
            raise SchemaError(f'{here}: expected a recipe object')
        if set(recipe) - RECIPE_FIELDS:
            raise SchemaError(f'{here}: unknown fields {sorted(set(recipe) - RECIPE_FIELDS)}')
        if 'extends' in recipe:
            if not isinstance(recipe['extends'], str) or not ID_PATTERN.match(recipe['extends']):
                raise SchemaError(f'{here}.extends: expected a recipe id')
        elif not isinstance(recipe.get('layers'), list) or not recipe['layers']:
            raise SchemaError(f'{here}: expected {{"layers": [...]}} or {{"extends": ...}}')
        for group in ('layers', 'add'):
            if group in recipe and not isinstance(recipe[group], list):
                raise SchemaError(f'{here}.{group}: expected list')
        if 'drop' in recipe and (not isinstance(recipe['drop'], list)
                                 or not all(isinstance(v, str) for v in recipe['drop'])):
            raise SchemaError(f'{here}.drop: expected list of shape or layer names')
        if 'palette' in recipe:
            _palette_ref(recipe['palette'], palettes, f'{here}.palette')
        if 'family' in recipe and recipe['family'] not in PROJECTILE_FAMILIES:
            raise SchemaError(f'{here}.family: unknown projectile family')
        if 'scale' in recipe:
            _number(recipe['scale'], .3, 3, f'{here}.scale')
        if 'particle' in recipe and recipe['particle'] not in PARTICLES:
            raise SchemaError(f'{here}.particle: unknown particle')
        layers = [(f'{here}.layers[{i}]', layer) for i, layer in enumerate(recipe.get('layers', []))] \
            + [(f'{here}.add[{i}]', layer) for i, layer in enumerate(recipe.get('add', []))]
        for where, layer in layers:
            _validate_layer(layer, where, palettes)
    bindings = pack.get('bindings', {})
    if not isinstance(bindings, dict) or set(bindings) - {'archetype', 'type_projectile', 'category',
                                                           'skill', 'type_recipe'}:
        raise SchemaError(f'{path}.bindings: unknown binding groups')
    for group, rows in bindings.items():
        for key, value in rows.items():
            if group == 'type_projectile':
                if key not in TYPES or value not in PROJECTILE_FAMILIES:
                    raise SchemaError(f'{path}.bindings.type_projectile.{key}: invalid')
            elif not isinstance(value, str) or not ID_PATTERN.match(value):
                raise SchemaError(f'{path}.bindings.{group}.{key}: expected recipe id')
    for key, row in pack.get('screen', {}).items():
        if key not in SCREEN_KEYS or not isinstance(row, dict):
            raise SchemaError(f'{path}.screen.{key}: expected one of {SCREEN_KEYS}')
        for name, value in row.items():
            _number(value, 0, 40, f'{path}.screen.{key}.{name}')
    return True


def check_references(motion_packs, vfx_packs):
    """Cross-pack references: clip bindings and recipe bindings must resolve."""
    clips, recipes = {}, {}
    for pack in motion_packs:
        clips.update(pack.get('clips', {}))
    for pack in vfx_packs:
        recipes.update(pack.get('recipes', {}))
    problems = []
    for pack in motion_packs:
        for group in ('archetypes', 'species'):
            for key, row in pack.get(group, {}).items():
                for slot, clip_id in (row.get('clips') or {}).items():
                    clip = clips.get(clip_id)
                    if clip is None:
                        problems.append(f'{pack["name"]}.{group}.{key}.{slot}: missing clip {clip_id}')
                    elif clip['slot'] != slot:
                        problems.append(f'{pack["name"]}.{group}.{key}.{slot}: clip {clip_id} is a {clip["slot"]} clip')
    for pack in vfx_packs:
        for name, recipe in pack.get('recipes', {}).items():
            seen, current = {name}, recipe
            while isinstance(current, dict) and current.get('extends'):
                parent = current['extends']
                if parent not in recipes:
                    problems.append(f'{pack["name"]}.recipes.{name}: extends missing recipe {parent}')
                    break
                if parent in seen:
                    problems.append(f'{pack["name"]}.recipes.{name}: extends cycle')
                    break
                seen.add(parent)
                current = recipes[parent]
        for group, rows in pack.get('bindings', {}).items():
            if group == 'type_projectile':
                continue
            for key, value in rows.items():
                if value not in recipes:
                    problems.append(f'{pack["name"]}.bindings.{group}.{key}: missing recipe {value}')
    return problems


def _read_dir(directory):
    packs = {}
    try:
        files = sorted(Path(directory).glob('*.json'))
    except OSError:
        return packs
    for path in files:
        try:
            packs[path.stem] = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
    return packs


def load_packs():
    """All motion and VFX packs, keyed by file stem (alphabetical merge order)."""
    return {'schema_version': SCHEMA_VERSION, 'motion': _read_dir(MOTION_DIR), 'vfx': _read_dir(VFX_DIR)}


def validate_all():
    data = load_packs()
    problems = []
    for group, validate in (('motion', validate_motion_pack), ('vfx', validate_vfx_pack)):
        for stem, pack in data[group].items():
            try:
                validate(pack, path=f'{group}/{stem}.json')
            except SchemaError as exc:
                problems.append(str(exc))
            if isinstance(pack, dict) and pack.get('name') != stem:
                problems.append(f'{group}/{stem}.json: name must equal the file stem')
    if not problems:
        problems += check_references(list(data['motion'].values()), list(data['vfx'].values()))
    return problems


def dump_pack(data):
    """Readable JSON: one line per innermost list (keyframes, colours)."""
    text = json.dumps(data, ensure_ascii=False, indent=1)
    flat = re.compile(r'\[\s*([^\[\]{}]*?)\s*\]', re.S)
    return flat.sub(lambda m: '[' + ', '.join(part.strip() for part in m.group(1).split(',\n')) + ']'
                    if m.group(1).strip() else '[]', text) + '\n'


def save_pack(group, name, data, *, root=None):
    """Validate and atomically write a pack; returns the repo-relative path."""
    if group not in ('motion', 'vfx'):
        raise SchemaError('group must be motion or vfx')
    if not isinstance(name, str) or not NAME_PATTERN.match(name):
        raise SchemaError('pack name must be lowercase letters, digits or _')
    if not isinstance(data, dict) or data.get('name') != name:
        raise SchemaError('pack data must be an object whose name equals the file name')
    (validate_motion_pack if group == 'motion' else validate_vfx_pack)(data, path=f'{group}/{name}.json')
    base = Path(root) if root is not None else ROOT
    directory = base / 'assets' / group
    others = _read_dir(directory)
    others[name] = data
    if group == 'motion':
        problems = check_references(list(others.values()), list(_read_dir(base / 'assets' / 'vfx').values()))
    else:
        problems = check_references(list(_read_dir(base / 'assets' / 'motion').values()), list(others.values()))
    if problems:
        raise SchemaError('; '.join(problems[:4]))
    text = dump_pack(data)
    if len(text.encode()) > MAX_PACK_BYTES:
        raise SchemaError('pack exceeds 512KB')
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f'{name}.json'
    temporary = target.with_name(target.name + '.tmp')
    temporary.write_text(text)
    os.replace(temporary, target)
    return target.relative_to(base).as_posix()


def main(argv):
    if argv:
        problems = []
        for raw in argv:
            path = Path(raw)
            pack = json.loads(path.read_text())
            validate = validate_vfx_pack if pack.get('kind') == 'vfx_pack' else validate_motion_pack
            try:
                validate(pack, path=str(path))
            except SchemaError as exc:
                problems.append(str(exc))
    else:
        problems = validate_all()
    for problem in problems:
        print('✗', problem)
    print('OK' if not problems else f'{len(problems)} problem(s)')
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
