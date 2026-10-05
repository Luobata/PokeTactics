#!/usr/bin/env python3
"""Paired tactical-v1/v2 ablation of opening weather with unchanged fixed squads.

Every squad costs 15 gold, has six units, three ordinary equipped items, one
learning slot and one partner. Side-swaps verify symmetry and are not additional
independent trials. No acquisition, all-roster balance or human-play claim.
"""
import argparse
from collections import Counter
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import random
import statistics
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'sim'), str(ROOT/'tools/acceptance'), str(ROOT)]
from combat import Battle
from experiment_build_diversity import Build, BUILDS, PIECES, rotate, side_fingerprint, team_metrics
from session_save import rules_fingerprint
import build_rules
import weather

SUN = Build('sun', '日照接力', (38, 6, 3, 26, 76, 2),
            ((1, 3), (2, 3), (4, 3), (3, 3), (2, 2), (5, 2)),
            (None, 'focus_lens', None, 'swift_feather', 'sash', None), 26,
            (None, None, 'cut', None, None, None),
            '九尾先开晴天，雷丘接力与能量装备让火草技能赶上八秒窗口。')
RAIN = Build('rain', '降雨水阵', (131, 9, 80, 26, 76, 143),
             ((3, 2), (2, 2), (4, 3), (3, 3), (1, 2), (4, 2)),
             ('focus_lens', None, None, 'swift_feather', None, 'sash'), 26,
             (None, 'surf', None, None, None, None),
             '拉普拉斯入场降雨，雷丘接力、起手能量与三水羁绊支持前排技能。')
SUN_CONTROL = replace(BUILDS[3], key='sun_control', name='日照控场', species=(38, 3, 6, 26, 76, 65),
                      plan='用九尾替换耿鬼，保留喷火龙能量装备与首次技能接力；失去偷能，换开场火草窗口。')
RAIN_GARDEN = replace(BUILDS[0], key='rain_garden', name='降雨续航', species=(143, 131, 3, 80, 76, 2),
                     plan='用拉普拉斯替换水箭龟，保留睡觉、剩饭和妙蛙花治疗；降雨强化呆壳兽水招，原生冰招不获雨增幅。')


def battle_for(a, b, seed, ruleset, swapped=False):
    if swapped:
        a, b = b, a
    comp = lambda build: [(PIECES[s], item) if item else PIECES[s]
                          for s, item in zip(build.species, build.items)]
    battle = Battle(comp(a), comp(b), random.Random(seed), ruleset=ruleset, stat_mode='budget_v1',
                    positions_a=list(a.positions), positions_b=rotate(b.positions),
                    team_options=[{'partner': x.partner} for x in (a, b)],
                    learned_a=list(a.learned), learned_b=list(b.learned))
    result = battle.run()
    return battle, result


def window_metrics(battle, team):
    indices = {u.idx for u in battle.units if u.team == team}
    current, expiry = battle.base_weather_name, None
    windows, buffed, nerfed, casts, first = 0, 0, 0, 0, None
    for event in battle.events:
        if event[1] == 'tactical_effect' and event[4] in ('weather_start', 'weather_end', 'weather_conflict'):
            current, expiry = event[5]['new_weather'], event[5]['expires_at']
            windows += int(event[4] == 'weather_start')
        elif event[1] == 'cast' and event[2] in indices:
            casts += 1
            move = build_rules.resolve_cast(battle.units[event[2]].piece, battle.stat_mode)
            multiplier = weather.damage_mult(move, current)
            in_window = expiry is not None and event[0] < expiry
            buffed += int(in_window and multiplier > 1.)
            nerfed += int(in_window and multiplier < 1.)
            first = event[0] if first is None else first
    return {'casts': casts, 'window_buffed_casts': buffed, 'window_nerfed_casts': nerfed,
            'weather_windows': windows, 'first_cast': first}


def arm(a, b, seeds, ruleset):
    outcomes = Counter()
    failures, durations, metrics, casts = [], [], [], []
    for seed in seeds:
        battle, result = battle_for(a, b, seed, ruleset)
        reverse, swapped = battle_for(a, b, seed, ruleset, True)
        if (side_fingerprint(battle, 0, True) != side_fingerprint(reverse, 1)
                or side_fingerprint(battle, 1, True) != side_fingerprint(reverse, 0)
                or result['duration'] != swapped['duration']
                or swapped['winner'] != (None if result['winner'] is None else 1-result['winner'])):
            failures.append(seed)
        outcomes['draw' if result['winner'] is None else 'a' if result['winner'] == 0 else 'b'] += 1
        durations.append(result['duration'])
        metrics.append(team_metrics(battle, 0))
        casts.append(window_metrics(battle, 0))
    average = lambda rows: {k: round(statistics.mean(r[k] for r in rows if r[k] is not None), 3)
                           if any(r[k] is not None for r in rows) else None for k in rows[0]}
    return {'a': a.key, 'b': b.key, 'ruleset': ruleset, 'trials': len(seeds),
            'games_including_swaps': len(seeds)*2, 'wins': outcomes['a'], 'losses': outcomes['b'],
            'draws': outcomes['draw'], 'score': (outcomes['a']+.5*outcomes['draw'])/len(seeds),
            'duration_median': round(statistics.median(durations), 2),
            'side_swap_failures': failures, 'a_metrics': average(metrics), 'a_windows': average(casts)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seeds', type=int, default=100)
    parser.add_argument('--start-seed', type=int, default=202610051000)
    parser.add_argument('--variant', choices=('initial', 'replacements'), default='initial')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.seeds < 1:
        parser.error('--seeds must be positive')
    sun, rain = (SUN, RAIN) if args.variant == 'initial' else (SUN_CONTROL, RAIN_GARDEN)
    squads = [sun, rain, BUILDS[0], BUILDS[2]]
    assert all(b.cost == 15 and len(b.species) == 6 and sum(i is not None for i in b.items) == 3
               and sum(t is not None for t in b.learned) == 1 for b in squads)
    seeds = range(args.start_seed, args.start_seed+args.seeds)
    pairings = [(sun, BUILDS[0]), (sun, BUILDS[2]), (rain, BUILDS[0]), (rain, BUILDS[2]), (sun, rain)]
    arms = [arm(a, b, seeds, version) for a, b in pairings for version in ('tactics_v1', 'tactics_v2')]
    comparisons = [{'a': arms[i]['a'], 'b': arms[i]['b'],
                    'v1_score': arms[i]['score'], 'v2_score': arms[i+1]['score'],
                    'v2_minus_v1_pp': round((arms[i+1]['score']-arms[i]['score'])*100, 1),
                    'v2_window_buffed_casts': arms[i+1]['a_windows']['window_buffed_casts']}
                   for i in range(0, len(arms), 2)]
    payload = {'schema': 1, 'method': __doc__, 'rules_fingerprint': rules_fingerprint(),
               'variant': args.variant,
               'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'seed_range': [args.start_seed, args.start_seed+args.seeds-1],
               'builds': [dict(asdict(b), cost=b.cost) for b in squads], 'arms': arms,
               'comparisons': comparisons, 'games': sum(a['games_including_swaps'] for a in arms),
               'side_swap_failures': sum(len(a['side_swap_failures']) for a in arms),
               'limits': ['Fixed authored squads, not the live recruitment economy.',
                          'Same seeds and every resource held fixed across v1/v2.',
                          'Swaps validate symmetry; they do not double sample size.',
                          'No inferential claim from a 100-seed prototype sample.']}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({k: payload[k] for k in ('games', 'side_swap_failures', 'comparisons')}, ensure_ascii=False, indent=2))
    return bool(payload['side_swap_failures'])


if __name__ == '__main__':
    raise SystemExit(main())
