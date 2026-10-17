"""Run full family-v2 games and verify tactical research end-to-end.

This probe intentionally uses the real session/router/battle code and the
arena_probe headless renderer.  It neither renders PNGs nor writes a game save;
SAVE_ROOT is additionally redirected to a temporary directory as a guard.
Example:
  python3 tools/acceptance/tactical_research_probe.py --games 10 \
    --seed-base 2026101710 --output .build/arena-probe/tactical-research-family-n10.json
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/acceptance'), str(ROOT / 'sim'), str(ROOT)]
import arena_families as families
import arena_probe
import arena_research
import demo
import shop as shop_mod
from bots import PERSONALITIES
from session_save import SessionCodec, rules_fingerprint


class ResearchCollector:
    """Track per-seat stacks and one final save/load/re-encode oracle."""

    def __init__(self):
        self.timeline = []
        self.final_stacks = {}
        self.save_roundtrip = None
        self.save_error = None
        self.save_mismatch = None

    def on_round_end(self, session):
        row = {'round': session.round_no, 'phase': session.phase,
               'stacks': {}}
        for seat in session.seats:
            row['stacks'][str(seat.seat)] = {
                track['id']: track['stacks'] for track in arena_research.view(
                    session.arena_research, seat.seat)['tracks']}
        self.timeline.append(row)

    def on_game_over(self, session):
        self.final_stacks = {
            str(seat.seat): {track['id']: track['stacks']
                             for track in arena_research.view(
                                 session.arena_research, seat.seat)['tracks']}
            for seat in session.seats
        }
        try:
            codec = SessionCodec()
            payload = codec.encode(session)
            restored = codec.decode(payload, codec.schema_version)
            reencoded = codec.encode(restored)
            self.save_roundtrip = reencoded == payload
            if not self.save_roundtrip:
                self.save_mismatch = json.dumps(self._difference(payload, reencoded),
                                                ensure_ascii=False)[:20000]
        except Exception as exc:  # noqa: BLE001 - report probe oracle failures.
            self.save_roundtrip = False
            self.save_error = repr(exc)

    @staticmethod
    def _difference(left, right):
        if type(left) is not type(right):
            return {'left': left, 'right': right}
        if isinstance(left, dict):
            rows = []
            for key in sorted(set(left) | set(right), key=str):
                if key not in left or key not in right or left[key] != right[key]:
                    rows.append([key, ResearchCollector._difference(
                        left.get(key, '<missing>'), right.get(key, '<missing>'))])
            return rows
        if isinstance(left, list):
            if len(left) != len(right):
                return {'left_length': len(left), 'right_length': len(right)}
            return [ResearchCollector._difference(a, b)
                    for a, b in zip(left, right) if a != b]
        return {'left': left, 'right': right}

    def result(self):
        return {'timeline': self.timeline, 'final_stacks': self.final_stacks,
                'save_roundtrip': self.save_roundtrip,
                'save_error': self.save_error,
                'save_mismatch': self.save_mismatch}


def compact_game(row, collector):
    result = {key: row[key] for key in (
        'seed', 'personality', 'status', 'current_round', 'battle_count',
        'player_battle_count', 'player_rank', 'player_rounds', 'table_rounds',
        'final_alive', 'natural_terminal') if key in row}
    if row['status'] == 'error':
        result.update(error=row['error'], failed_round=row['failed_round'],
                      failed_phase=row['failed_phase'])
    result['research'] = collector.result()
    return result


def summarize(games):
    complete = [row for row in games if row['status'] == 'complete']
    route_totals = Counter()
    seat_totals = Counter()
    exceed_limit = 0
    roundtrips = 0
    for row in complete:
        research = row['research']
        roundtrips += bool(research['save_roundtrip'])
        for stacks in research['final_stacks'].values():
            for track, count in stacks.items():
                route_totals[track] += count
                seat_totals[track] = max(seat_totals[track], count)
                exceed_limit += count > arena_research.STACK_LIMIT
    return {'games': len(games), 'complete': len(complete),
            'errors': len(games) - len(complete),
            'save_roundtrips': roundtrips,
            'all_save_roundtrips': len(complete) == roundtrips,
            'route_stack_totals': dict(route_totals),
            'max_stacks_by_route': dict(seat_totals),
            'stack_limit_violations': exceed_limit,
            'total_battles': sum(row['battle_count'] for row in games)}


def run_games(count, seed_base):
    rows = []
    original_session = demo.Session
    observed_battle = arena_probe.ObservedBattle

    def family_session(seed, ruleset, arena_pool=None):
        return original_session(seed, ruleset, arena_pool=families.VERSION)

    with tempfile.TemporaryDirectory(prefix='poketactics-research-probe-') as save_dir, \
            patch.object(demo, 'SAVE_ROOT', Path(save_dir)), \
            patch.object(demo, 'SESSIONS', {}), \
            patch.object(demo, 'Session', side_effect=family_session), \
            patch.object(demo, 'Battle', observed_battle), \
            patch.object(demo, '_render_battle_frames', side_effect=arena_probe.headless), \
            patch.object(shop_mod, 'draw_slot', arena_probe.counting_draw_slot):
        for index in range(count):
            collector = ResearchCollector()
            raw = arena_probe.run_game(seed_base + index,
                                       sorted(PERSONALITIES)[index % len(PERSONALITIES)],
                                       [collector])
            rows.append(compact_game(raw, collector))
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--games', type=int, default=10,
                        help='Independent games (1-256, default: 10).')
    parser.add_argument('--seed-base', type=int, default=2026101710)
    parser.add_argument('--output', type=Path,
                        default=ROOT / '.build/arena-probe/tactical-research-family-n10.json')
    args = parser.parse_args(argv)
    if not 1 <= args.games <= 256:
        parser.error('--games must be between 1 and 256')
    if not 0 <= args.seed_base <= 2 ** 63 - args.games:
        parser.error('seed range must fit nonnegative signed-64-bit integers')
    args.output = args.output.resolve()
    if args.output.is_relative_to(demo.SAVE_ROOT.resolve()):
        parser.error('--output must not point into the isolated game save directory')
    if args.output.is_dir():
        parser.error('--output must name a JSON file')

    games = run_games(args.games, args.seed_base)
    summary = summarize(games)
    payload = {
        'method': __doc__,
        'arena_pool': families.VERSION,
        'ruleset': demo.arena_mod.RULESET,
        'rules_fingerprint': rules_fingerprint(),
        'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'seed_base': args.seed_base,
        'summary': summary,
        'games': games,
        'limits': [
            'Seat 0 uses the same L2 bot policy as AI seats; this is a mechanics smoke, not a human win-rate study.',
            'PNG rendering and persistent game saves are disabled; SAVE_ROOT is redirected to a temporary directory.',
            'Save verification is encode/decode/re-encode equality at terminal state, not reload-and-continue.',
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f'Written: {args.output}')
    return 0 if summary['errors'] == 0 and summary['all_save_roundtrips'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
