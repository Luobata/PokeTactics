#!/usr/bin/env python3
"""Import PMD SpriteCollab frame-animated sprites for the browser renderer.

Downloads only the animations the battle renderer plays, from one pinned
SpriteCollab commit, crops every frame to its animation's union opaque box,
packs one atlas PNG per species (plus a shiny atlas when the shiny sheet
exists) and writes a manifest with frames, durations, Rush/Hit/Return frames
and per-frame anchor points from the Offsets / Shadow sheets.

    python3 tools/pmd_import.py                 # all arena species
    python3 tools/pmd_import.py --species 6,25  # a subset (merged into index)
    python3 tools/pmd_import.py --verify        # re-hash outputs vs SOURCES.json
    python3 tools/pmd_import.py --sha <commit>  # re-pin (then re-run all)

Outputs (assets/pmd/): index.json, <dex>.json, <dex>.png, <dex>-shiny.png,
portrait/<dex>.png, SOURCES.json (commit, every source URL + sha256, every
output sha256) and CREDITS.md. Downloads are cached under .build/pmd-cache.
Outputs are deterministic, so re-running is idempotent.

Art: (c) The Pokémon Company / Nintendo / Spike Chunsoft (CHUNSOFT rips) and
SpriteCollab contributors under CC BY-NC 4.0 — non-commercial fan use only.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'assets' / 'pmd'
CACHE = ROOT / '.build' / 'pmd-cache'
REPO = 'PMDCollab/SpriteCollab'
PINNED_SHA = '424d5ff2e79785f9535f25f647455d3d723b8573'   # git ls-remote HEAD, 2026-11-15
ANIMS = ('Idle', 'Walk', 'Attack', 'Strike', 'Swing', 'Double', 'Shoot', 'Charge', 'Rotate',
         'Hop', 'Hurt', 'Faint', 'Sleep')
# Sheet rows: 0 Down, 1 DownRight, 2 Right, 3 UpRight, 4 Up, 5 UpLeft, 6 Left, 7 DownLeft.
# Rows 5-7 are drawn as mirrors of 3, 2, 1, so only the first five are stored.
DIRS_STORED = (0, 1, 2, 3, 4)
MIRROR = {5: 3, 6: 2, 7: 1}
MARKERS = {(0, 0, 0): 'head', (0, 255, 0): 'center', (255, 0, 0): 'hand_r', (0, 0, 255): 'hand_l'}
ATLAS_WIDTH = 1024
SCHEMA = 'poketactics.pmd_species'
INDEX_SCHEMA = 'poketactics.pmd_index'
VERSION = 1
LICENSE_NOTE = ('Pokémon sprites © The Pokémon Company / Nintendo / Creatures / GAME FREAK; '
                'PMD sprites © Spike Chunsoft; community sprites from PMD SpriteCollab '
                '(https://github.com/PMDCollab/SpriteCollab) under CC BY-NC 4.0. '
                'Non-commercial fan project only.')


def raw_url(sha, path):
    return f'https://raw.githubusercontent.com/{REPO}/{sha}/{path}'


class Fetcher:
    """Cached, hashed downloads from one pinned commit."""

    def __init__(self, sha, offline=False):
        self.sha, self.offline = sha, offline
        self.root = CACHE / sha
        self.sources = {}

    def get(self, path):
        cached = self.root / path
        missing = cached.with_name(cached.name + '.404')
        if missing.exists():
            return None
        if not cached.exists():
            if self.offline:
                return None
            data = None
            for attempt in range(4):
                try:
                    with urllib.request.urlopen(raw_url(self.sha, path), timeout=60) as response:
                        data = response.read()
                    break
                except urllib.error.HTTPError as exc:
                    if exc.code == 404:
                        missing.parent.mkdir(parents=True, exist_ok=True)
                        missing.write_text('')
                        return None
                    if attempt == 3:
                        raise
                except (urllib.error.URLError, TimeoutError, ConnectionError):
                    if attempt == 3:
                        raise
                time.sleep(1.5 * (attempt + 1))
            cached.parent.mkdir(parents=True, exist_ok=True)
            tmp = cached.with_name(cached.name + '.tmp')
            tmp.write_bytes(data)
            os.replace(tmp, cached)
        data = cached.read_bytes()
        self.sources[path] = {'url': raw_url(self.sha, path), 'sha256': hashlib.sha256(data).hexdigest(),
                              'bytes': len(data)}
        return data

    def image(self, path):
        data = self.get(path)
        return Image.open(io.BytesIO(data)).convert('RGBA') if data is not None else None


# ------------------------------------------------------------------ species list
def arena_species():
    """Every species the arena can field: families, frozen templates, gen3, PvE waves."""
    sys.path[:0] = [str(ROOT / 'sim'), str(ROOT / 'tools' / 'mockups')]
    import arena
    import arena_families
    import arena_gen3
    import match
    ids = set(arena_families.SPECIES_FAMILY) | set(arena.build_templates()) | set(arena_gen3.GEN3_SKILLS)
    for wave in match.PVE_WAVES:
        ids.update(x for x in wave if isinstance(x, int))
    return sorted(ids)


# ------------------------------------------------------------------ AnimData
def parse_anim_data(xml_bytes):
    root = ET.fromstring(xml_bytes)
    shadow = int(root.findtext('ShadowSize') or 1)
    anims = {}
    for node in root.iter('Anim'):
        name = node.findtext('Name')
        row = {'copy_of': node.findtext('CopyOf')}
        if not row['copy_of']:
            row.update(w=int(node.findtext('FrameWidth')), h=int(node.findtext('FrameHeight')),
                       durations=[int(d.text) for d in node.iter('Duration')])
            for key, tag in (('rush', 'RushFrame'), ('hit', 'HitFrame'), ('return', 'ReturnFrame')):
                value = node.findtext(tag)
                if value is not None and value.strip() not in ('', '-1'):
                    row[key] = int(value)
        anims[name] = row
    return shadow, anims


def resolve(anims, name, depth=0):
    """Follow CopyOf; returns (sheet name, spec) or (None, None)."""
    row = anims.get(name)
    if row is None or depth > 8:
        return None, None
    if row.get('copy_of'):
        return resolve(anims, row['copy_of'], depth + 1)
    return name, row


# ------------------------------------------------------------------ packing
def markers(cell):
    found = {}
    w, h = cell.size
    px = cell.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a and (r, g, b) in MARKERS and MARKERS[(r, g, b)] not in found:
                found[MARKERS[(r, g, b)]] = (x, y)
    return found


def shadow_anchor(cell):
    px = cell.load()
    w, h = cell.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a and (r, g, b) == (255, 255, 255):
                return (x, y)
    return None


def encode_png(image):
    """Lossless: exact palette PNG when ≤256 RGBA colours, else RGBA PNG."""
    colors = image.getcolors(257)
    buf = io.BytesIO()
    if colors is not None:
        palette = sorted({c for _, c in colors}, key=lambda c: (c[3] != 0, c))
        index = {c: i for i, c in enumerate(palette)}
        out = Image.new('P', image.size)
        out.putpalette([v for c in palette for v in c[:3]] + [0] * (768 - 3 * len(palette)))
        out.putdata([index[c] for c in (image.get_flattened_data() if hasattr(image, "get_flattened_data") else image.getdata())])
        out.save(buf, 'PNG', optimize=True, transparency=bytes(c[3] for c in palette))
    else:
        image.save(buf, 'PNG', optimize=True)
    return buf.getvalue()


class Shelf:
    def __init__(self, width):
        self.width, self.x, self.y, self.row_h, self.used_w = width, 0, 0, 0, 0

    def place(self, w, h):
        if self.x + w > self.width:
            self.x, self.y, self.row_h = 0, self.y + self.row_h + 1, 0
        pos = (self.x, self.y)
        self.used_w = max(self.used_w, self.x + w)
        self.x += w + 1
        self.row_h = max(self.row_h, h)
        return pos

    @property
    def height(self):
        return self.y + self.row_h


def import_species(fetcher, sid):
    dex = f'{sid:04d}'
    xml = fetcher.get(f'sprite/{dex}/AnimData.xml')
    if xml is None:
        return None, 'SpriteCollab 无该物种的 AnimData.xml'
    shadow_size, anims = parse_anim_data(xml)
    shiny_xml = fetcher.get(f'sprite/{dex}/0000/0001/AnimData.xml')
    tiles, manifest_anims = [], {}
    for name in ANIMS:
        sheet, spec = resolve(anims, name)
        if spec is None:
            continue
        sheet_img = fetcher.image(f'sprite/{dex}/{sheet}-Anim.png')
        if sheet_img is None:
            continue
        shiny_img = fetcher.image(f'sprite/{dex}/0000/0001/{sheet}-Anim.png') if shiny_xml else None
        if shiny_img is not None and shiny_img.size != sheet_img.size:
            shiny_img = None
        offsets_img = fetcher.image(f'sprite/{dex}/{sheet}-Offsets.png')
        shadow_img = fetcher.image(f'sprite/{dex}/{sheet}-Shadow.png')
        cw, ch, n = spec['w'], spec['h'], len(spec['durations'])
        rows = sheet_img.height // ch
        dirs = [d for d in DIRS_STORED if d < rows] if rows >= 8 else [0]
        # union opaque box over every stored frame (normal and shiny)
        box = None
        for d in dirs:
            for f in range(n):
                for img in (sheet_img, shiny_img):
                    if img is None:
                        continue
                    bb = img.crop((f * cw, d * ch, f * cw + cw, d * ch + ch)).getbbox()
                    if bb:
                        box = bb if box is None else (min(box[0], bb[0]), min(box[1], bb[1]),
                                                      max(box[2], bb[2]), max(box[3], bb[3]))
        if box is None:
            continue
        tw, th = box[2] - box[0], box[3] - box[1]
        entry = {'sheet': sheet, 'tile': [tw, th], 'cell': [cw, ch], 'crop': [box[0], box[1]],
                 'durations': spec['durations'], 'single_dir': rows < 8, 'dirs': {}}
        for key in ('rush', 'hit', 'return'):
            if key in spec:
                entry[key] = spec[key]
        if sheet != name:
            entry['copy_of'] = sheet
        for d in dirs:
            frames = {'anchor': [], 'head': [], 'center': [], 'hand_r': [], 'hand_l': []}
            for f in range(n):
                rect = (f * cw, d * ch, f * cw + cw, d * ch + ch)
                tile = (sheet_img.crop(rect).crop(box), shiny_img.crop(rect).crop(box) if shiny_img else None)
                tiles.append((name, d, f, tile))
                rel = lambda p: [p[0] - box[0], p[1] - box[1]] if p else None
                anchor = shadow_anchor(shadow_img.crop(rect)) if shadow_img else None
                frames['anchor'].append(rel(anchor) if anchor else [cw // 2 - box[0], ch // 2 - box[1]])
                found = markers(offsets_img.crop(rect)) if offsets_img else {}
                for key in ('head', 'center', 'hand_r', 'hand_l'):
                    frames[key].append(rel(found.get(key)))
            entry['dirs'][str(d)] = frames
        manifest_anims[name] = entry
    if not manifest_anims:
        return None, 'SpriteCollab 没有可用的战斗动画'
    # pack: tallest tiles first for tighter shelves; deterministic order
    order = sorted(range(len(tiles)), key=lambda i: (-manifest_anims[tiles[i][0]]['tile'][1], ANIMS.index(tiles[i][0]),
                                                    tiles[i][1], tiles[i][2]))
    shelf = Shelf(ATLAS_WIDTH)
    positions = {}
    for i in order:
        name, d, f, _ = tiles[i]
        tw, th = manifest_anims[name]['tile']
        positions[i] = shelf.place(tw, th)
    size = (max(1, shelf.used_w), max(1, shelf.height))
    atlas = Image.new('RGBA', size, (0, 0, 0, 0))
    shiny = Image.new('RGBA', size, (0, 0, 0, 0)) if shiny_xml else None
    has_shiny = False
    for i, (name, d, f, (normal, shiny_tile)) in enumerate(tiles):
        atlas.paste(normal, positions[i])
        if shiny is not None and shiny_tile is not None:
            shiny.paste(shiny_tile, positions[i])
            has_shiny = True
        manifest_anims[name]['dirs'][str(d)].setdefault('xy', []).append(list(positions[i]))
    manifest = {'schema': SCHEMA, 'version': VERSION, 'species': sid, 'dex': dex, 'shadow_size': shadow_size,
                'atlas': f'{dex}.png', 'shiny_atlas': f'{dex}-shiny.png' if has_shiny else None,
                'atlas_size': list(size), 'dirs_stored': list(DIRS_STORED),
                'mirror': {str(k): v for k, v in MIRROR.items()}, 'anims': manifest_anims}
    portrait = fetcher.get(f'portrait/{dex}/Normal.png')
    manifest['portrait'] = f'portrait/{dex}.png' if portrait else None
    return (manifest, encode_png(atlas), encode_png(shiny) if has_shiny else None, portrait), None


# ------------------------------------------------------------------ credits
def credit_names(fetcher):
    data = fetcher.get('credit_names.txt')
    names = {}
    for line in (data or b'').decode('utf-8', 'replace').splitlines()[1:]:
        parts = line.split('\t')
        if len(parts) >= 2:
            names[parts[1].strip()] = (parts[0].strip(), parts[2].strip() if len(parts) > 2 else '')
    return names


def tracker_credits(fetcher, ids):
    data = fetcher.get('tracker.json')
    tracker = json.loads(data) if data else {}
    rows = {}
    for sid in ids:
        entry = tracker.get(f'{sid:04d}', {})
        shiny = entry.get('subgroups', {}).get('0000', {}).get('subgroups', {}).get('0001', {})
        rows[sid] = {'name': entry.get('name') or f'#{sid}', 'sprite': entry.get('sprite_credit') or {},
                     'shiny': shiny.get('sprite_credit') or {}, 'portrait': entry.get('portrait_credit') or {}}
    return rows


def write_credits(path, credits, names, imported, sha):
    def who(credit):
        out = []
        for key in [credit.get('primary')] + list(credit.get('secondary') or []):
            if not key:
                continue
            name, contact = names.get(key, (key.strip('<@!>'), ''))
            out.append(name + (f'（{contact}）' if contact and contact.startswith('http') else ''))
        return '、'.join(dict.fromkeys(out)) or '—'
    lines = ['# PMD 精灵素材署名（自动生成）', '',
             f'来源：PMD SpriteCollab（https://github.com/{REPO}），固定提交 `{sha}`。', '',
             '版权与许可：', '',
             '- 宝可梦形象 © The Pokémon Company / Nintendo / Creatures / GAME FREAK。',
             '- 署名为 CHUNSOFT 的精灵取自《宝可梦不可思议的迷宫》系列，© Spike Chunsoft。',
             '- 其余由 SpriteCollab 社区作者绘制，按 CC BY-NC 4.0（署名—非商业）授权：'
             'https://creativecommons.org/licenses/by-nc/4.0/ 。',
             '- 本项目为非商业同人作品；任何商业用途都必须替换全部美术素材。', '',
             '| 图鉴号 | 名称 | 精灵作者 | 异色作者 | 头像作者 |', '| --- | --- | --- | --- | --- |']
    for sid in sorted(imported):
        row = credits.get(sid, {})
        lines.append(f"| {sid:04d} | {row.get('name', '')} | {who(row.get('sprite', {}))} | "
                     f"{who(row.get('shiny', {})) if imported[sid].get('shiny_atlas') else '—（未收录异色）'} | "
                     f"{who(row.get('portrait', {})) if imported[sid].get('portrait') else '—'} |")
    path.write_text('\n'.join(lines) + '\n')


# ------------------------------------------------------------------ validation
def validate_manifest(m):
    """Return problems in one species manifest (empty list = valid)."""
    problems = []
    if m.get('schema') != SCHEMA or m.get('version') != VERSION:
        return ['schema/version mismatch']
    aw, ah = m.get('atlas_size', [0, 0])
    for name, anim in m.get('anims', {}).items():
        where = f"{m.get('dex')}.{name}"
        if name not in ANIMS:
            problems.append(f'{where}: unexpected animation')
        n = len(anim.get('durations', []))
        if not n or any(type(d) is not int or d <= 0 for d in anim['durations']):
            problems.append(f'{where}: durations must be positive ticks')
        for key in ('rush', 'hit', 'return'):
            if key in anim and not 0 <= anim[key] < n:
                problems.append(f'{where}: {key} frame out of range')
        if 'rush' in anim and 'hit' in anim and anim['rush'] > anim['hit']:
            problems.append(f'{where}: rush after hit')
        tw, th = anim.get('tile', [0, 0])
        if not anim.get('dirs'):
            problems.append(f'{where}: no directions')
        for d, row in anim.get('dirs', {}).items():
            if int(d) not in DIRS_STORED:
                problems.append(f'{where}: direction {d} not stored')
            for key in ('xy', 'anchor', 'head', 'center', 'hand_r', 'hand_l'):
                if len(row.get(key, [])) != n:
                    problems.append(f'{where}.{d}: {key} must have one entry per frame')
            for x, y in row.get('xy', []):
                if x < 0 or y < 0 or x + tw > aw or y + th > ah:
                    problems.append(f'{where}.{d}: frame outside the atlas')
                    break
    return problems


def validate_actions(data):
    """Action mapping (assets/pmd/actions.json): every anim name must be importable."""
    problems = []
    known = set(ANIMS)
    def names(value):
        return value if isinstance(value, list) else [value]
    if data.get('schema_version') != 1 or data.get('kind') != 'pmd_actions':
        return ['actions.json: schema_version 1 / kind pmd_actions required']
    groups = [data['basic'][k] for k in data.get('basic', {})] + [data['cast'].get('default', []),
              data['cast'].get('support', []), data['cast'].get('windup')]
    groups += list(data['cast'].get('by_category', {}).values())
    groups += [data.get(k) for k in ('hit', 'knockback', 'stun', 'ko', 'idle', 'walk', 'victory')]
    for row in data.get('species', {}).values():
        groups += [v for k, v in row.items() if k != 'note']
    for group in groups:
        for name in names(group):
            if name not in known:
                problems.append(f'actions.json: unknown animation {name!r}')
    for key in data.get('species', {}):
        if not key.isdigit():
            problems.append(f'actions.json: species key {key!r} must be a dex number')
    return problems


# ------------------------------------------------------------------ main
def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_bytes(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() == data:
        return
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_bytes(data)
    os.replace(tmp, path)


def dump(data):
    return (json.dumps(data, ensure_ascii=False, separators=(',', ':'), sort_keys=True) + '\n').encode()


def verify():
    sources = json.loads((OUT / 'SOURCES.json').read_text())
    bad = [rel for rel, digest in sources['outputs'].items()
           if not (OUT / rel).is_file() or sha256(OUT / rel) != digest]
    cache = CACHE / sources['commit']
    stale = [rel for rel, row in sources['files'].items()
             if (cache / rel).is_file() and sha256(cache / rel) != row['sha256']]
    for rel in bad:
        print('✗ output changed or missing:', rel)
    for rel in stale:
        print('✗ cached source differs from SOURCES.json:', rel)
    index = json.loads((OUT / 'index.json').read_text())
    for row in index['species'].values():
        for problem in validate_manifest(json.loads((OUT / row['file']).read_text())):
            bad.append(problem)
            print('✗', problem)
    actions = OUT / 'actions.json'
    if actions.exists():
        for problem in validate_actions(json.loads(actions.read_text())):
            bad.append(problem)
            print('✗', problem)
    print('OK' if not bad and not stale else f'{len(bad) + len(stale)} problem(s)')
    return 1 if bad or stale else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--species', help='comma separated national dex numbers (default: all arena species)')
    ap.add_argument('--sha', default=PINNED_SHA, help='SpriteCollab commit to pin')
    ap.add_argument('--verify', action='store_true', help='re-hash outputs against SOURCES.json')
    ap.add_argument('--offline', action='store_true', help='use only the download cache')
    ap.add_argument('--jobs', type=int, default=12)
    args = ap.parse_args(argv)
    if args.verify:
        return verify()
    fetcher = Fetcher(args.sha, offline=args.offline)
    every = arena_species()
    ids = sorted(int(x) for x in args.species.split(',')) if args.species else every
    index_path = OUT / 'index.json'
    index = json.loads(index_path.read_text()) if index_path.exists() and args.species else {}
    if index.get('commit') not in (None, args.sha):
        print('commit changed: re-import every species (run without --species)', file=sys.stderr)
        return 2
    species = dict(index.get('species', {}))
    fallback = dict(index.get('fallback', {}))
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        results = list(pool.map(lambda sid: (sid, import_species(fetcher, sid)), ids))
    for sid, (result, reason) in results:
        key = str(sid)
        if result is None:
            fallback[key] = {'style': 'classic', 'reason': reason}
            species.pop(key, None)
            print(f'#{sid}: fallback to classic — {reason}')
            continue
        manifest, atlas, shiny, portrait = result
        dex = manifest['dex']
        write_bytes(OUT / f'{dex}.png', atlas)
        if shiny is not None:
            write_bytes(OUT / f'{dex}-shiny.png', shiny)
        else:
            (OUT / f'{dex}-shiny.png').unlink(missing_ok=True)
        if portrait is not None:
            write_bytes(OUT / 'portrait' / f'{dex}.png', portrait)
        write_bytes(OUT / f'{dex}.json', dump(manifest))
        fallback.pop(key, None)
        species[key] = {'dex': dex, 'file': f'{dex}.json', 'anims': sorted(manifest['anims']),
                        'shiny': manifest['shiny_atlas'] is not None, 'portrait': manifest['portrait']}
    index = {'schema': INDEX_SCHEMA, 'version': VERSION, 'repo': REPO, 'commit': args.sha,
             'anims': list(ANIMS), 'dirs_stored': list(DIRS_STORED), 'license': LICENSE_NOTE,
             'species': dict(sorted(species.items(), key=lambda kv: int(kv[0]))),
             'fallback': dict(sorted(fallback.items(), key=lambda kv: int(kv[0])))}
    write_bytes(index_path, dump(index))
    # sources: union with previous run for subset imports
    sources_path = OUT / 'SOURCES.json'
    previous = json.loads(sources_path.read_text()) if sources_path.exists() and args.species else {}
    fetcher.get('credit_names.txt')
    files = {**previous.get('files', {}), **fetcher.sources}
    credits = tracker_credits(fetcher, [int(k) for k in species])
    files.update({k: v for k, v in fetcher.sources.items()})
    imported = {int(k): {'shiny_atlas': v['shiny'], 'portrait': v['portrait']} for k, v in species.items()}
    write_credits(OUT / 'CREDITS.md', credits, credit_names(fetcher), imported, args.sha)
    outputs = {}
    for path in sorted(OUT.rglob('*')):
        if path.is_file() and path.name not in ('SOURCES.json', 'actions.json') and not path.name.endswith('.tmp'):
            outputs[path.relative_to(OUT).as_posix()] = sha256(path)
    sources = {'repo': REPO, 'commit': args.sha,
               'note': 'Raw files fetched from raw.githubusercontent.com at the pinned commit; '
                       'tracker.json and credit_names.txt only feed CREDITS.md.',
               'files': dict(sorted(files.items())), 'outputs': outputs}
    write_bytes(sources_path, (json.dumps(sources, ensure_ascii=False, indent=1, sort_keys=True) + '\n').encode())
    total = sum((OUT / rel).stat().st_size for rel in outputs) + sources_path.stat().st_size
    print(f'species {len(species)} · fallback {len(fallback)} · shiny {sum(v["shiny"] for v in species.values())} '
          f'· {total / 1e6:.1f} MB in assets/pmd')
    return 0


if __name__ == '__main__':
    sys.exit(main())
