"""Equal-resource guard and weather arms; side swaps verify, not inflate, N.

Fixed existing 15-cost teams, three finished items and one teaching per team.
This measures combat value only, not recruitment or full-run completion rates.
"""
import argparse
from collections import Counter
from dataclasses import replace
import hashlib
import itertools
import json
import math
from pathlib import Path
import random
import statistics

from combat import Battle
from experiment_build_diversity import BUILDS, PIECES, rotate, side_fingerprint, team_metrics


def with_teaching(build, source, technique):
    return replace(build, learned=tuple(technique if i == source else None
                                       for i in range(len(build.species))))


def run_pair(a, b, seed, ta=None, tb=None, weather=None):
    comp = lambda x: [(PIECES[s], item) if item else PIECES[s]
                      for s, item in zip(x.species, x.items)]
    battle = Battle(comp(a), comp(b), random.Random(seed), ruleset='tactics_v1',
                    stat_mode='budget_v1', positions_a=list(a.positions),
                    positions_b=rotate(b.positions), weather_name=weather,
                    team_options=[{'partner': x.partner} for x in (a, b)],
                    learned_a=list(a.learned), learned_b=list(b.learned),
                    tactics_a=ta, tactics_b=tb)
    result = battle.run()
    return battle, result


def wilson(wins, n):
    z, p = 1.96, wins/n
    center = (p+z*z/(2*n))/(1+z*z/n)
    half = z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/(1+z*z/n)
    return [round(center-half, 4), round(center+half, 4)]


def measure(label, a, b, seeds, ta=None, tb=None, weather=None):
    outcomes, effects, durations, failures, casts = Counter(), Counter(), [], [], []
    trials, trigger_trials = [], Counter()
    for seed in seeds:
        first, result = run_pair(a, b, seed, ta, tb, weather)
        swap, mirrored = run_pair(b, a, seed, tb, ta, weather)
        winner = result['winner']
        outcomes['draw' if winner is None else 'a' if winner == 0 else 'b'] += 1
        if (side_fingerprint(first, 0, True) != side_fingerprint(swap, 1)
                or side_fingerprint(first, 1, True) != side_fingerprint(swap, 0)
                or result['duration'] != mirrored['duration']
                or mirrored['winner'] != (None if winner is None else 1-winner)):
            failures.append(seed)
        durations.append(result['duration'])
        casts.append(team_metrics(first, 0)['casts'])
        trial_effects = Counter()
        for e in first.events:
            if e[1] == 'tactical_effect':
                effects[e[4]] += 1
                trial_effects[e[4]] += 1
        trigger_trials.update(trial_effects.keys())
        trials.append({'seed': seed, 'winner': winner, 'a_casts': casts[-1],
                       'effects': dict(trial_effects)})
    return {'arm': label, 'a': a.key, 'b': b.key, 'independent_trials': len(seeds),
            'games_including_verification_swaps': 2*len(seeds), 'outcomes': dict(outcomes),
            'a_win_rate': outcomes['a']/len(seeds), 'a_win_wilson_95': wilson(outcomes['a'], len(seeds)),
            'a_casts_mean': round(statistics.mean(casts), 3),
            'duration_median': round(statistics.median(durations), 3),
            'tactical_events_per_trial': {k: v/len(seeds) for k, v in effects.items()},
            'tactical_trigger_trials': dict(trigger_trials), 'trials': trials,
            'side_swap_failures': failures,
            'fixture': {'a': a.__dict__, 'b': b.__dict__, 'tactics_a': ta, 'tactics_b': tb,
                        'base_weather': weather}}


def experiment(seed_count=100, start_seed=202610050):
    if seed_count <= 0:
        raise ValueError('positive seed count required')
    seeds = range(start_seed, start_seed+seed_count)
    garden, battery, dive, disrupt = BUILDS
    guard = with_teaching(battery, 0, 'guard')
    guard_config = {'guard': {'source': 0, 'target': 1}}
    sun = with_teaching(garden, 2, 'sunny_day')
    rain = with_teaching(battery, 0, 'rain_dance')
    sun_config = {'weather': {'source': 2}}
    rain_config = {'weather': {'source': 0}}
    arms = []
    for a, b in itertools.combinations(BUILDS, 2):
        arms.append(measure('unchanged_baseline', a, b, seeds))
    for opponent in (garden, dive, disrupt):
        arms.append(measure('guard_replaces_surf', guard, opponent, seeds, guard_config))
    # Compare the exact same new teaching with selection off/on to isolate
    # activation. These are ablations, not equal-usefulness alternatives.
    arms.append(measure('sun_and_rain_disabled', sun, rain, seeds))
    arms.append(measure('sun_only', sun, rain, seeds, sun_config))
    arms.append(measure('rain_only', sun, rain, seeds, None, rain_config))
    arms.append(measure('sun_vs_rain', sun, rain, seeds, sun_config, rain_config))
    # Preselected from exploratory seeds 310000..310019. Keep original failed
    # battery arms above and freeze this candidate before running held-out seeds.
    garden_line = replace(garden, key='garden_guard_line',
                          positions=((2, 2), (1, 2), (1, 3), (4, 3), (3, 2), (2, 3)))
    garden_guard = with_teaching(garden_line, 1, 'guard')
    garden_config = {'guard': {'source': 1, 'target': 2}}
    mirrored_dive = replace(dive, key='dive_horizontal_mirror',
                            positions=tuple((5-x, y) for x, y in dive.positions))
    comparisons = []
    for opponent in (dive, disrupt, mirrored_dive):
        original = measure('candidate_original_rest', garden_line, opponent, seeds)
        disabled = measure('candidate_guard_disabled', garden_guard, opponent, seeds)
        active = measure('candidate_guard_active', garden_guard, opponent, seeds, garden_config)
        arms.extend((original, disabled, active))
        pairs = list(zip(disabled['trials'], active['trials']))
        comparisons.append({
            'opponent': opponent.key,
            'original_rest_win_rate': original['a_win_rate'],
            'guard_disabled_win_rate': disabled['a_win_rate'],
            'guard_active_win_rate': active['a_win_rate'],
            'activation_win_rate_delta': active['a_win_rate']-disabled['a_win_rate'],
            'activation_win_gains': [on['seed'] for off, on in pairs
                                     if off['winner'] != 0 and on['winner'] == 0],
            'activation_win_losses': [on['seed'] for off, on in pairs
                                      if off['winner'] == 0 and on['winner'] != 0],
            'guard_trigger_trials': active['tactical_trigger_trials'].get('guard', 0),
        })
    for arm in arms:
        for build in (arm['fixture']['a'], arm['fixture']['b']):
            assert len(build['species']) == 6
            assert sum(PIECES[s].tier for s in build['species']) == 15
            assert sum(x is not None for x in build['items']) == 3
            assert sum(x is not None for x in build['learned']) == 1
    fingerprint = hashlib.sha256()
    root = Path(__file__).resolve().parents[1]
    for p in sorted((root/'sim').glob('*.py'))+sorted((root/'data').glob('*.json')):
        fingerprint.update(p.name.encode()); fingerprint.update(p.read_bytes())
    return {'schema': 'tactics-experiment-v1', 'rules_fingerprint': fingerprint.hexdigest(),
            'seed_range': [start_seed, start_seed+seed_count-1], 'arms': arms,
            'candidate_selection_seeds': [310000, 310019],
            'candidate_guard_comparisons': comparisons,
            'independent_of_candidate_selection': not (start_seed <= 310019
                                                       and start_seed+seed_count-1 >= 310000),
            'games': sum(a['games_including_verification_swaps'] for a in arms),
            'side_swap_failures': sum(len(a['side_swap_failures']) for a in arms),
            'limits': 'Fixed squads only; no all-roster balance, supply, recruitment, AI difficulty, or human duration claim. Weather window 8 seconds is a prototype parameter.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--seeds', type=int, default=100)
    parser.add_argument('--start-seed', type=int, default=202610050)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = experiment(args.seeds, args.start_seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'games': result['games'], 'side_swap_failures': result['side_swap_failures'],
                      'arms': [{k: a[k] for k in ('arm', 'a', 'b', 'a_win_rate', 'tactical_events_per_trial')}
                               for a in result['arms']]}, ensure_ascii=False, indent=2))
    raise SystemExit(bool(result['side_swap_failures']))
