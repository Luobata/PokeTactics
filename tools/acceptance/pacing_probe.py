#!/usr/bin/env python3
"""Fixed-AI natural-ending probe for tactical v3/v4 Sessions.

Every arm reuses the same independent seed block and the four L2 personalities.
The v3 arm is the fixed AI/battle counter baseline; v4 arms isolate a pure table
pacing policy. The probe never writes game saves or profiles and skips PNG I/O.

Formal initial screening requires at least 100 games per requested arm. It is
still an automated L2-pilot readout, not a human operation-time measurement.
"""
import argparse
from collections import Counter
from contextlib import contextmanager, nullcontext
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/acceptance'), str(ROOT / 'sim'), str(ROOT)]
import demo
import pacing
from bots import PERSONALITIES
import rng
import tactical_run_probe as legacy_probe
from session_save import rules_fingerprint


BASELINE_RULESET = 'tactics_v3'
CANDIDATE_RULESET = 'tactics_v4'
R30_PVE_ROUND = 30


def ensure_row_metrics(row):
    defaults = {
        'prep_ms': [], 'battle_compute_ms': [], 'player_battle_compute_ms': [],
        'simulated_battle_seconds': [], 'stage_rounds': [], 'terminal_state': None,
    }
    for key, value in defaults.items():
        row.setdefault(key, value)
    return row


class TimedBattle(legacy_probe.ObservedBattle):
    def run(self):
        started = time.perf_counter()
        result = super().run()
        row = legacy_probe.CONTEXT['row']
        if row is not None:
            ensure_row_metrics(row)
            elapsed = time.perf_counter() - started
            row['battle_compute_ms'].append(elapsed * 1000)
            row['simulated_battle_seconds'].append(result['duration'])
        return result


def timed_headless(*args, **kwargs):
    row = legacy_probe.CONTEXT['row']
    started = time.perf_counter()
    try:
        return legacy_probe.headless(*args, **kwargs)
    finally:
        if row is not None:
            ensure_row_metrics(row)
            row['player_battle_compute_ms'].append(
                (time.perf_counter() - started) * 1000)


def seat_growth(seat):
    return {
        'seat': seat.seat,
        'alive': seat.alive,
        'hp': seat.hp,
        'level': seat.level,
        'gold': seat.gold,
        'board': len(seat.board),
        'bench': len(seat.bench),
        'combines': getattr(seat, 'combines', 0),
        'machines': sum(seat.inventory.techniques.values())
        + sum(o.technique is not None for o in seat.all_pieces()),
    }


def arm_definition(name):
    if name == 'baseline_v3':
        return {'ruleset': BASELINE_RULESET, 'policy': pacing.LEGACY_POLICY,
                'terminal_pve': 'keep'}
    if name == 'floor20_v4':
        return {'ruleset': CANDIDATE_RULESET,
                'policy': pacing.PressurePolicy(20, minimum_loss=20),
                'terminal_pve': 'keep'}
    if name == 'floor21_v4':
        return {'ruleset': CANDIDATE_RULESET,
                'policy': pacing.DEFAULT_NATURAL_END_POLICY,
                'terminal_pve': 'keep'}
    if name == 'floor22_v4':
        return {'ruleset': CANDIDATE_RULESET,
                'policy': pacing.PressurePolicy(20, minimum_loss=22),
                'terminal_pve': 'keep'}
    if name == 'factor4_v4':
        return {'ruleset': CANDIDATE_RULESET,
                'policy': pacing.PressurePolicy(20, survivor_factor=4),
                'terminal_pve': 'keep'}
    if name == 'floor21_v4_r30_pvp':
        return {'ruleset': CANDIDATE_RULESET,
                'policy': pacing.DEFAULT_NATURAL_END_POLICY,
                'terminal_pve': 'replace_r30_pvp'}
    raise ValueError(f'unknown arm {name!r}')


@contextmanager
def observed_session_lifecycle():
    """Capture per-round growth, eliminations and the authoritative final table."""
    end_prep = demo.Session.end_prep
    finalize = demo.Session._finalize

    def observed_end_prep(self):
        row = legacy_probe.CONTEXT['row']
        before_seats = [seat_growth(seat) for seat in self.seats]
        result = end_prep(self)
        if row is not None:
            ensure_row_metrics(row)
            after = [seat_growth(seat) for seat in self.seats]
            eliminated = [{
                'seat': old['seat'], 'rank': seat.rank
            } for old, seat in zip(before_seats, self.seats)
                if old['alive'] and not seat.alive]
            row['stage_rounds'].append({
                'round': self.round_no,
                'alive_before': sum(s['alive'] for s in before_seats),
                'alive_after': sum(s['alive'] for s in after),
                'eliminated': eliminated,
                'seat_alive_after': [s['alive'] for s in after],
                'seat_levels_after': [s['level'] for s in after],
                'seat_gold_after': [s['gold'] for s in after],
                'seat_board_after': [s['board'] for s in after],
                'seat_machines_after': [s['machines'] for s in after],
                'player_before': before_seats[0],
                'player_after': after[0],
                'pending_rewards': sum(r['status'] == 'pending' for r in self.rewards),
            })
        return result

    def observed_finalize(self):
        result = finalize(self)
        row = legacy_probe.CONTEXT['row']
        if row is not None:
            ensure_row_metrics(row)
            row['terminal_state'] = {
                'round': self.round_no,
                'alive_count': len(self._alive()),
                'seats': [{'seat': seat.seat, 'alive': seat.alive,
                           'rank': seat.rank, 'hp': max(0, seat.hp)}
                          for seat in self.seats],
            }
        return result

    with patch.object(demo.Session, 'end_prep', observed_end_prep), \
            patch.object(demo.Session, '_finalize', observed_finalize):
        yield


@contextmanager
def terminal_pve_mode(mode):
    if mode == 'keep':
        yield
        return
    if mode != 'replace_r30_pvp':
        raise ValueError(f'unknown terminal PVE mode {mode!r}')
    begin_round = demo.Session.begin_round
    resolve_pve = demo.Session._resolve_pve

    def begin_with_r30_pairs(self, round_no):
        begin_round(self, round_no)
        if round_no != R30_PVE_ROUND:
            return
        pair_rng = rng.derive(self.seed, round_no, 'pair')
        alive = self._alive()
        pairs, odd = demo._Match._pair_up(None, alive, pair_rng)
        ghost_src = None
        if odd is not None and len(alive) > 1:
            ghost_src = pair_rng.choice([seat for seat in alive if seat is not odd])
        self.pairs, self.ghost_seat, self.ghost_src = pairs, odd, ghost_src
        if self.player.alive:
            self.opp_view = self._opponent_view()

    def pvp_instead_of_r30_pve(self, round_no, weather):
        if round_no == R30_PVE_ROUND:
            return self._resolve_pvp(round_no, weather)
        return resolve_pve(self, round_no, weather)

    with patch.object(demo.Session, 'begin_round', begin_with_r30_pairs), \
            patch.object(demo.Session, '_resolve_pve', pvp_instead_of_r30_pve):
        yield


@contextmanager
def policy_damage(policy):
    """Patch only the production per-session routing point for isolated arms."""
    if not hasattr(demo.Session, '_loss_damage'):
        raise RuntimeError('production Session._loss_damage routing is not integrated')

    def loss(self, round_no, enemy_survivors):
        return pacing.loss_damage(self.ruleset, round_no, enemy_survivors,
                                   policy=policy)

    with patch.object(demo.Session, '_loss_damage', loss):
        yield


@contextmanager
def timed_pilot():
    pilot = legacy_probe.pilot_prep

    def timed(session, bot):
        row = legacy_probe.CONTEXT['row']
        started = time.perf_counter()
        try:
            return pilot(session, bot)
        finally:
            if row is not None:
                ensure_row_metrics(row)
                row['prep_ms'].append((time.perf_counter() - started) * 1000)

    with patch.object(legacy_probe, 'pilot_prep', timed):
        yield


def validate_terminal(row):
    state = row.get('terminal_state')
    if state is None:
        raise AssertionError('missing authoritative terminal state')
    ranks = sorted(seat['rank'] for seat in state['seats'])
    if ranks != list(range(1, 9)):
        raise AssertionError(f'incomplete final ranks: {ranks}')
    champions = [seat for seat in state['seats'] if seat['alive'] and seat['rank'] == 1]
    kind = pacing.ending_kind(state['alive_count'], state['round'], demo.MAX_ROUNDS)
    if kind == pacing.NATURAL_CHAMPION and len(champions) != 1:
        raise AssertionError(f'natural ending has {len(champions)} champions')
    if kind == pacing.INVALID_ENDING:
        raise AssertionError(
            f'invalid terminal alive_count={state["alive_count"]} round={state["round"]}')
    row['ending_kind'] = kind
    row['natural_terminal'] = kind == pacing.NATURAL_CHAMPION
    row['forced_ranking'] = kind == pacing.FORCED_RANKING
    row['champion_seat'] = champions[0]['seat'] if len(champions) == 1 else None


def run_arm(name, definition, seed_base, games):
    personalities = sorted(PERSONALITIES)
    rows = []
    with observed_session_lifecycle(), \
            patch.object(demo, 'SESSIONS', {}), \
            patch.object(demo, 'Battle', TimedBattle), \
            patch.object(demo, '_render_battle_frames', side_effect=timed_headless), \
            timed_pilot():
        with terminal_pve_mode(definition['terminal_pve']):
            # floor21_v4 intentionally exercises production routing. Other v4
            # arms patch only Session._loss_damage and keep ruleset/AI/battle fixed.
            policy = definition['policy']
            explicit_policy = policy is not pacing.DEFAULT_NATURAL_END_POLICY
            with policy_damage(policy) if explicit_policy else nullcontext():
                for index in range(games):
                    row = legacy_probe.game(seed_base + index,
                                            personalities[index % len(personalities)],
                                            definition['ruleset'])
                    row['arm'] = name
                    if row['status'] == 'complete':
                        validate_terminal(row)
                    rows.append(row)
                    if (index + 1) % 10 == 0:
                        print(f'{name}: completed {index + 1}/{games}', flush=True)
    return rows


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * fraction))]


def wilson(successes, count, z=1.96):
    if not count:
        return None
    p_value = successes / count
    denominator = 1 + z * z / count
    center = (p_value + z * z / (2 * count)) / denominator
    half = z * math.sqrt(p_value * (1 - p_value) / count
                         + z * z / (4 * count * count)) / denominator
    return [max(0.0, center - half), min(1.0, center + half)]


def summarize(rows):
    complete = [row for row in rows if row['status'] == 'complete']
    natural = [row for row in complete if row['ending_kind'] == pacing.NATURAL_CHAMPION]
    forced = [row for row in complete if row['ending_kind'] == pacing.FORCED_RANKING]

    def alive_after(row, round_no):
        record = next((item for item in row['stage_rounds']
                       if item['round'] == round_no), None)
        return None if record is None else record['alive_after']

    def player_alive(row, round_no):
        record = next((item for item in row['stage_rounds']
                       if item['round'] == round_no), None)
        return None if record is None else record['player_after']['alive']

    def values(function, checkpoint):
        return [function(row, checkpoint) for row in complete]

    stage_rounds = [row['table_rounds'] for row in complete]
    all_eliminations = [elimination for row in complete
                        for elimination in sum((item['eliminated']
                                                for item in row['stage_rounds']), [])]
    table_eliminations = Counter(item['round'] for row in complete
                                 for item in row['stage_rounds'] if item['eliminated'])

    def growth_checkpoint(round_no):
        records = [next((item for item in row['stage_rounds']
                         if item['round'] == round_no), None) for row in complete]
        records = [record for record in records if record is not None]
        def seat_values(key):
            return [value for record in records
                    for alive, value in zip(record['seat_alive_after'], record[key])
                    if alive]
        return {
            'alive_seats': len(seat_values('seat_levels_after')),
            'level_mean': statistics.mean(seat_values('seat_levels_after'))
            if records else None,
            'level7_seats': sum(value >= 7 for value in seat_values('seat_levels_after')),
            'gold_mean': statistics.mean(seat_values('seat_gold_after'))
            if records else None,
            'board_mean': statistics.mean(seat_values('seat_board_after'))
            if records else None,
            'machines_mean': statistics.mean(seat_values('seat_machines_after'))
            if records else None,
        }

    return {
        'games': len(rows), 'independent_seeds': len({row['seed'] for row in rows}),
        'complete': len(complete), 'errors': len(rows) - len(complete),
        'formal_seed_count': len({row['seed'] for row in rows}) >= 100,
        'personalities': dict(Counter(row['personality'] for row in rows)),
        'natural_champion': len(natural), 'forced_ranking': len(forced),
        'natural_champion_rate': len(natural) / len(complete) if complete else None,
        'natural_champion_ci95': wilson(len(natural), len(complete)),
        'forced_ranking_rate': len(forced) / len(complete) if complete else None,
        'ending_kinds_exactly_partition_complete': (
            len(natural) + len(forced) == len(complete)),
        'table_rounds_mean': statistics.mean(stage_rounds) if complete else None,
        'table_rounds_p90': percentile(stage_rounds, .9),
        'player_exit_round_mean': statistics.mean(row['player_rounds'] for row in complete)
        if complete else None,
        'player_eliminated_before_r15': sum(
            row.get('player_eliminated_round', 10**9) < 15 for row in complete),
        'player_eliminated_before_r20': sum(
            row.get('player_eliminated_round', 10**9) < 20 for row in complete),
        'player_alive_after_r15': sum(value is True for value in values(player_alive, 15)),
        'player_alive_after_r20': sum(value is True for value in values(player_alive, 20)),
        'player_alive_after_r25': sum(value is True for value in values(player_alive, 25)),
        'alive_after_r15_mean': statistics.mean(
            [v for v in values(alive_after, 15) if v is not None]) if complete else None,
        'alive_after_r20_mean': statistics.mean(
            [v for v in values(alive_after, 20) if v is not None]) if complete else None,
        'alive_after_r25_mean': statistics.mean(
            [v for v in values(alive_after, 25) if v is not None]) if complete else None,
        'player_eliminations_by_round': dict(sorted(Counter(
            row.get('player_eliminated_round') for row in complete
            if row.get('player_eliminated_round') is not None).items())),
        'table_eliminations_by_round': dict(sorted(table_eliminations.items())),
        'table_elimination_events': len(all_eliminations),
        'growth_r15': growth_checkpoint(15),
        'growth_r20': growth_checkpoint(20),
        'growth_r25': growth_checkpoint(25),
        'player_top4': sum(row['player_rank'] <= 4 for row in complete),
        'player_champion': sum(row['player_rank'] == 1 for row in complete),
        'player_rank_counts': dict(sorted(Counter(row['player_rank'] for row in complete).items())),
        'rewarded_machines_mean': statistics.mean(row['rewarded_machines'] for row in complete)
        if complete else None,
        'player_level7_at_exit': sum(
            (row['rounds'][-1]['level'] == 7 if row['rounds'] else False)
            for row in complete),
        'player_final_gold_mean': statistics.mean(
            row['rounds'][-1]['gold'] for row in complete if row['rounds'])
        if any(row['rounds'] for row in complete) else None,
        'final_pending': sum(row['final_pending'] for row in complete),
        'prep_ms_mean': statistics.mean(
            [v for row in complete for v in row['prep_ms']]) if complete else None,
        'battle_compute_ms_mean': statistics.mean(
            [v for row in complete for v in row['battle_compute_ms']]) if complete else None,
        'player_battle_compute_ms_mean': statistics.mean(
            [v for row in complete for v in row['player_battle_compute_ms']]) if complete else None,
        'simulated_battle_seconds_mean': statistics.mean(
            [v for row in complete for v in row['simulated_battle_seconds']]) if complete else None,
        'human_playback_seconds': None,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--games', type=int, default=100,
                        help='Games per arm; formal initial screening requires >=100.')
    parser.add_argument('--seed-base', type=int, default=2026103000)
    parser.add_argument('--arms', nargs='+', default=['baseline_v3', 'floor21_v4'],
                        choices=['baseline_v3', 'floor20_v4', 'floor21_v4', 'floor22_v4',
                                 'factor4_v4', 'floor21_v4_r30_pvp'])
    parser.add_argument('--output', type=Path,
                        default=ROOT / '.build/pacing/natural-end-n100.json')
    args = parser.parse_args(argv)
    if args.games < 1:
        parser.error('--games must be positive')
    if args.games > 4096:
        parser.error('--games must be <=4096')
    if not 0 <= args.seed_base <= 2**63 - args.games:
        parser.error('seed block must fit nonnegative signed-64-bit integers')
    args.output = args.output.resolve()
    if args.output.is_relative_to(demo.SAVE_ROOT.resolve()):
        parser.error('--output must not point into the game save directory')
    if args.output.is_dir():
        parser.error('--output must name a JSON file')

    arms = {}
    for name in args.arms:
        definition = arm_definition(name)
        rows = run_arm(name, definition, args.seed_base, args.games)
        arms[name] = {'definition': {**definition, 'policy': asdict(definition['policy'])},
                      'summary': summarize(rows), 'games': rows}
        print(name, json.dumps(arms[name]['summary'], ensure_ascii=False), flush=True)

    payload = {
        'method': __doc__,
        'source_sha256': {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (ROOT/'sim/pacing.py', ROOT/'tools/acceptance/pacing_probe.py')
        },
        'rules_fingerprint': rules_fingerprint(),
        'seed_base': args.seed_base,
        'games_requested_per_arm': args.games,
        'formal_initial_screen': args.games >= 100,
        'arms': arms,
        'limits': [
            'L2 bot pilot; no human preparation or playback duration is inferred.',
            'The R30-PVP arm deliberately removes that round’s promised PVE rewards; it is diagnostic only.',
            'Experimental overrides patch only Session._loss_damage; floor21_v4 exercises production ruleset routing.',
            'A natural champion is accepted only with exactly one alive rank-1 seat and complete ranks 1..8.',
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    print(f'Written: {args.output}', flush=True)
    return 0 if all(summary['errors'] == 0 for summary in
                    (arm['summary'] for arm in arms.values())) else 1


if __name__ == '__main__':
    raise SystemExit(main())
