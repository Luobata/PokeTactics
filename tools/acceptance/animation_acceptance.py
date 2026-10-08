#!/usr/bin/env python3
"""Roster-wide real-event action checks; host evidence, not an art-quality score."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/mockups'), str(ROOT / 'sim')]
from action_preview import PREVIEW_ACTIONS, describe_clip
from character_catalog import character_catalog
from profile_range import make_preview_scene
from presentation_modes import make_renderer, mode_info, normalize_mode


def check_action(species, kind, seed=7, *, mode='classic', visual_overrides=None):
    mode = normalize_mode(mode)
    anim = make_preview_scene(species, kind, seed, mode=mode, visual_overrides=visual_overrides)
    renderer = make_renderer(anim, mode)
    events = copy.deepcopy(anim.events)
    clip = describe_clip(anim, kind)
    times = sorted({round(clip['clip_start'], 6), round(clip['clip_end'], 6),
                    *(phase['at'] for phase in clip['phases'])})
    frames = []
    peaks = {}
    for at in times:
        frame = renderer.frame(at,show_cutins=False)
        assert frame.size == (renderer.width, renderer.height), (species, kind, 'frame size')
        frames.append(frame.tobytes())
        for key, value in renderer.metrics.items():
            if isinstance(value, (int, float)):
                peaks[key] = max(peaks.get(key, 0), value)
    for at, expected in reversed(list(zip(times, frames))):
        assert renderer.frame(at,show_cutins=False).tobytes() == expected, (species, kind, 'seek mismatch')
    assert events == anim.events, (species, kind, 'authority mutated')
    if mode == 'classic':
        assert peaks.get('particles', 0) <= 192 and peaks.get('signature_tracks', 0) <= 3, (species, kind, 'budget exceeded')
    else:
        assert peaks.get('active_actions', 0) <= 6 and peaks.get('active_casts', 0) <= 6, (species, kind, 'budget exceeded')
    unit = clip['subject']['unit']
    before = anim.presentation_state(clip['snapshot_before'])[unit]
    after = anim.presentation_state(clip['snapshot_at'])[unit]
    if kind == 'hit':
        assert after['hp'] < before['hp'], (species, kind, 'missing real damage')
    if kind == 'death':
        assert before['die_t'] is None and after['die_t'] is not None, (species, kind, 'missing death transition')
        anim.presentation_state(clip['clip_end'])
        assert not anim._presentation_view().units[0].visible(clip['clip_end']), (species, kind, 'actor stays visible')
    if kind == 'idle':
        assert before == after, (species, kind, 'idle changes battle state')
    return {**mode_info(mode), 'species': species, 'kind': kind, 'seed': seed, 'sample_times': times,
            'phases': clip['phases'], 'subject': clip['subject'],
            'frame_sha256': hashlib.sha256(b''.join(frames)).hexdigest(),
            'metrics': peaks,
            **({'particle_peak': peaks.get('particles',0), 'signature_track_peak': peaks.get('signature_tracks',0)}
               if mode == 'classic' else {}),
            'before': before, 'after': after, 'rewind_equal': True, 'events_unchanged': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('arena','classic'), default='arena')
    parser.add_argument('--species', default='all', help='all or comma-separated species ids')
    parser.add_argument('--seed', type=int, default=7)
    parser.add_argument('--output', type=Path, default=ROOT / '.build/animation-contract.json')
    args = parser.parse_args()
    catalog = character_catalog(mode=args.mode)
    ids = sorted(map(int, catalog)) if args.species == 'all' else list(dict.fromkeys(map(int, args.species.split(','))))
    if not ids or any(str(sid) not in catalog for sid in ids):
        parser.error('species must be in the active roster')
    records, failures = [], []
    for sid in ids:
        for kind in catalog[str(sid)]['capabilities']['actions']:
            try:
                records.append(check_action(sid, kind, args.seed, mode=args.mode))
            except (AssertionError, ValueError) as exc:
                failures.append({'species': sid, 'kind': kind, 'error': str(exc)})
    result = {**mode_info(args.mode), 'ok': not failures, 'species_count': len(ids), 'checks': len(records),
              'actions': PREVIEW_ACTIONS, 'failures': failures, 'records': records,
              'scope': 'Native host frames and real Battle events; no artistic-quality or ESP32 performance claim.'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({key: value for key, value in result.items() if key != 'records'}, ensure_ascii=False))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
