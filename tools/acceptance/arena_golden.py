#!/usr/bin/env python3
"""Fingerprint every arena battle of whole bot sessions (refactor equivalence guard).

Each seed plays a complete arena session where the human seat stays empty, so
only bot/ghost/PvE battles resolve (no frame rendering). Every Battle.run()
result is reduced to a SHA-256 over its full event stream and statistics. Any
behaviour change in combat or session flow changes at least one digest.

    python3 tools/acceptance/arena_golden.py --seeds 11,23,37 --output digests.json
    python3 tools/acceptance/arena_golden.py --check tests/fixtures/arena_golden.json
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
for _path in (ROOT / 'sim', ROOT / 'tools' / 'acceptance', ROOT / 'tools' / 'mockups'):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

DEFAULT_SEEDS = (11, 23, 37)


def _jsonable(value):
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, set):
        return sorted(_jsonable(v) for v in value)
    if isinstance(value, float):
        return round(value, 9)
    if isinstance(value, (int, str, bool)) or value is None:
        return value
    return repr(value)


def run_seed(seed, params=None):
    import combat
    import demo
    digests = []
    original = combat.Battle.run

    def recording_run(battle):
        result = original(battle)
        payload = json.dumps({'events': _jsonable(battle.events),
                              'statistics': _jsonable(battle.statistics())},
                             sort_keys=True, ensure_ascii=False)
        digests.append(hashlib.sha256(payload.encode()).hexdigest()[:16])
        return result

    combat.Battle.run = recording_run
    try:
        session = demo._new_session(seed, {'mode': 'arena', 'edition': 'v1', **(params or {})})
        while session.player.alive and session.phase != 'over':
            if session.phase == 'battle':
                session.next_round()
            session.arena_augments_pending = []
            for row in session.arena_component_choices:
                if row['status'] == 'pending' and row['seat'] == 0:
                    row.update(status='closed', closed_reason='golden_skip')
            session.end_prep()
        session.finish_spectating()
        ranks = [seat.rank for seat in session.seats]
    finally:
        combat.Battle.run = original
    return {'battles': len(digests), 'digests': digests, 'ranks': ranks,
            'rounds': session.round_no}


def run_fuzz(seed, battles=60):
    """Random family comps with random equipment, techniques and positions."""
    import random
    import combat
    import arena
    import arena_families as families
    import items
    import techniques
    from arena_traits import ALTERNATIVES
    rng = random.Random(seed)
    finished = sorted(items.catalog(arena.RULESET))
    machines = list(techniques.ids_for(arena.RULESET))
    fids = sorted(families.FAMILIES)
    augments = sorted(arena.AUGMENTS)
    digests = []
    for index in range(battles):
        comps, learned, positions = [], [], []
        for team in (0, 1):
            size = rng.randint(3, 9)
            comp, row, cells = [], [], rng.sample(range(18), size)
            for _ in range(size):
                fid = rng.choice(fids)
                cost, paths = families.FAMILIES[fid]
                step = 1 if fid in families.RARE else rng.randint(1, 3)
                piece = families.make_piece(fid, step, rng.choice(paths)[-1])
                alternative = ALTERNATIVES.get(piece.species_id)
                if alternative and rng.random() < .5:
                    piece.arena_trait_key = alternative['id']
                item = rng.choice(finished) if rng.random() < .6 else None
                comp.append((piece, item) if item else piece)
                usable = [m for m in machines
                          if techniques.compatible_species(piece.species_id, m, arena.RULESET)]
                row.append(rng.choice(usable) if usable and rng.random() < .5 else None)
            for cell in cells:
                r, c = divmod(cell, 6)
                positions.append(None)
                positions[-1] = (c, r + 3) if team == 0 else (5 - c, 2 - r)
            comps.append(comp)
            learned.append(row)
        pos_a, pos_b = positions[:len(comps[0])], positions[len(comps[0]):]
        teams = [sorted(rng.sample(augments, rng.randint(0, 3))) for _ in (0, 1)]
        battle = combat.Battle(comps[0], comps[1], random.Random(seed * 1000 + index),
                               layout='back', ruleset=arena.RULESET, stat_mode='budget_v1',
                               positions_a=pos_a, positions_b=pos_b,
                               learned_a=learned[0] if any(learned[0]) else None,
                               learned_b=learned[1] if any(learned[1]) else None,
                               arena_teams=teams)
        battle.run()
        payload = json.dumps({'events': _jsonable(battle.events),
                              'statistics': _jsonable(battle.statistics())},
                             sort_keys=True, ensure_ascii=False)
        digests.append(hashlib.sha256(payload.encode()).hexdigest()[:16])
    return {'battles': len(digests), 'digests': digests}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seeds', default=','.join(map(str, DEFAULT_SEEDS)))
    parser.add_argument('--output')
    parser.add_argument('--check')
    parser.add_argument('--fuzz', type=int, default=80, help='random battles per seed (0 disables)')
    args = parser.parse_args(argv)
    seeds = [int(s) for s in args.seeds.split(',') if s]
    report = {str(seed): run_seed(seed) for seed in seeds}
    report.update({f'fuzz{seed}': run_fuzz(seed, args.fuzz) for seed in seeds if args.fuzz})
    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=1) + '\n')
    if args.check:
        expected = json.loads(Path(args.check).read_text())
        bad = [seed for seed in expected if expected[seed] != report.get(seed)]
        for seed in bad:
            want, got = expected[seed], report.get(seed) or {}
            first = next((i for i, (a, b) in enumerate(zip(want['digests'], got.get('digests', [])))
                          if a != b), None)
            print(f'seed {seed}: battles {want["battles"]} -> {got.get("battles")}, first diff at {first}')
        print('OK' if not bad else f'{len(bad)} seed(s) differ')
        return 1 if bad else 0
    print(json.dumps({seed: {k: v for k, v in row.items() if k != 'digests'}
                      for seed, row in report.items()}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
