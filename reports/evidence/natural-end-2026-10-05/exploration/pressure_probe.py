#!/usr/bin/env python3
"""Exploratory natural-ending arms. Runtime-only patches; no tracked files change."""
import json
import math
import statistics
import sys
from collections import Counter
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/acceptance'), str(ROOT / 'sim'), str(ROOT)]
import demo
from bots import PERSONALITIES
import tactical_run_probe as base


ARMS = {
    'baseline_v2': None,
    'r20_floor10': {'start': 20, 'floor': 10},
    'r20_floor15': {'start': 20, 'floor': 15},
    'r20_floor20': {'start': 20, 'floor': 20},
    'r20_factor4': {'start': 20, 'factor': 4},
    'r25_floor15': {'start': 25, 'floor': 15},
}
SEED_BASE = 2026101000
GAMES = 64


def patched_loss(config):
    original = demo.economy.loss_damage

    def loss(round_no, enemy_survivors):
        value = original(round_no, enemy_survivors)
        if config is None or round_no < config['start']:
            return value
        if 'floor' in config:
            return max(value, config['floor'])
        if 'factor' in config:
            return demo.economy.LOSS_BASE + max(0, enemy_survivors) * config['factor']
        raise AssertionError(config)
    return loss


def wilson(successes, n, z=1.96):
    if not n:
        return None
    p = successes / n
    denominator = 1 + z*z/n
    center = (p + z*z/(2*n)) / denominator
    half = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / denominator
    return [max(0, center-half), min(1, center+half)]


def summarize(rows):
    complete = [r for r in rows if r['status'] == 'complete']
    result = {
        'complete': len(complete), 'errors': len(rows)-len(complete),
        'natural_terminal': sum(r['natural_terminal'] for r in complete),
        'forced_ranking': sum(r['forced_ranking'] for r in complete),
        'natural_rate': (sum(r['natural_terminal'] for r in complete)/len(complete) if complete else None),
        'natural_rate_ci95': wilson(sum(r['natural_terminal'] for r in complete), len(complete)),
        'table_rounds_mean': statistics.mean(r['table_rounds'] for r in complete),
        'player_exit_round_mean': statistics.mean(r['player_rounds'] for r in complete),
        'player_eliminated_before_r20': sum(r.get('player_eliminated_round', 999) < 20 for r in complete),
        'player_alive_at_r20': sum(any(x['round'] == 20 and x['player_alive'] for x in r['rounds']) for r in complete),
        'player_alive_at_r25': sum(any(x['round'] == 25 and x['player_alive'] for x in r['rounds']) for r in complete),
        'player_champion': sum(r['player_rank'] == 1 for r in complete),
        'player_top4': sum(r['player_rank'] <= 4 for r in complete),
        'player_rank_counts': dict(sorted(Counter(r['player_rank'] for r in complete).items())),
        'rewarded_machines_mean': statistics.mean(r['rewarded_machines'] for r in complete),
        'final_player_gold_mean': statistics.mean(r['rounds'][-1]['gold'] for r in complete if r['rounds']),
        'final_player_level_counts': dict(sorted(Counter(r['rounds'][-1]['level'] for r in complete if r['rounds']).items())),
        'player_combines_mean': None,
    }
    # Rounds before/after each checkpoint. Alive snapshots are taken after battle resolution.
    for checkpoint in (15, 20, 25, 28, 30):
        values = []
        for row in complete:
            match = next((x for x in row['rounds'] if x['round'] == checkpoint), None)
            values.append(None if match is None else match['alive'])
        result[f'alive_after_r{checkpoint}_mean'] = statistics.mean([v for v in values if v is not None])
        result[f'alive_after_r{checkpoint}_counts'] = dict(sorted(Counter(v for v in values if v is not None).items()))
    return result


def main():
    output = {}
    personalities = sorted(PERSONALITIES)
    with patch.object(demo, 'SESSIONS', {}), \
         patch.object(demo, 'Battle', base.ObservedBattle), \
         patch.object(demo, '_render_battle_frames', side_effect=base.headless):
        for arm, config in ARMS.items():
            with patch.object(demo.economy, 'loss_damage', patched_loss(config)):
                rows = []
                for i in range(GAMES):
                    row = base.game(SEED_BASE+i, personalities[i % 4], 'tactics_v2')
                    row['arm'] = arm
                    rows.append(row)
            output[arm] = {'config': config, 'summary': summarize(rows), 'games': rows}
            print(arm, json.dumps(output[arm]['summary'], ensure_ascii=False), flush=True)
    payload = {
        'method': 'Runtime monkeypatch of economy.loss_damage after imports; same seeds/personalities/ruleset/AI in every arm.',
        'ruleset': 'tactics_v2', 'seed_base': SEED_BASE, 'games_per_arm': GAMES,
        'source_working_tree_dirty_batch_i': True,
        'limits': ['Exploratory only, not acceptance evidence.', 'No production pacing module exists yet.', 'L2 pilot, not human operation time.'],
        'arms': output,
    }
    path = Path(__file__).with_name('pressure-arms-n64.json')
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    print(f'written {path}', flush=True)


if __name__ == '__main__':
    main()
