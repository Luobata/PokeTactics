"""Fixed-seed loadout ablation; descriptive evidence, not a balance ranking."""
import argparse
import copy
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'sim'), str(ROOT / 'tools/acceptance')]
import arena
from combat import Battle
from combination_view import battle_summary

SCENARIOS = {
    'poison_engine': {'units': [34, 31, 45, 6], 'items': ['swift_feather', None, None, None],
                      'learned': ['toxic', None, None, None], 'augment': 'poison_catalyst'},
    'healing_guard': {'units': [36, 40, 76, 94], 'items': ['heart_bell', None, None, None],
                      'learned': ['thunderbolt', None, None, None], 'augment': 'first_aid'},
    'healing_relay': {'units': [40, 6, 76, 121], 'items': ['focus_lens', None, None, None],
                      'learned': ['thunderbolt', None, None, None], 'augment': 'watch_echo'},
}
POSITIONS = [(2, 4), (3, 4), (2, 3), (3, 3)]


def probe(seeds):
    templates = arena.build_templates()
    groups = []
    for key, scenario in SCENARIOS.items():
        for opponent, enemy_sids in (('mixed', [76, 68, 40, 6]),
                                     ('poison_immune', [31, 73, 34, 94])):
            for mode in ('full', 'without_item', 'without_teaching', 'without_augment'):
                samples = []
                for seed in range(seeds):
                    equipment = scenario['items'] if mode != 'without_item' else [None] * 4
                    a = [(copy.copy(templates[sid]), item) if item else copy.copy(templates[sid])
                         for sid, item in zip(scenario['units'], equipment)]
                    battle = Battle(a, [copy.copy(templates[sid]) for sid in enemy_sids], random.Random(90100 + seed),
                                    ruleset='arena_v1', stat_mode='budget_v1', positions_a=POSITIONS,
                                    positions_b=[(3, 1), (2, 1), (3, 2), (2, 2)],
                                    learned_a=scenario['learned'] if mode != 'without_teaching' else [None] * 4,
                                    arena_teams=[[scenario['augment']] if mode != 'without_augment' else [], []])
                    result = battle.run()
                    summary = battle_summary(battle.events, {unit.idx: unit.team for unit in battle.units})
                    samples.append({'seed': 90100 + seed, 'winner': result['winner'],
                                    'duration': result['duration'], 'casts': sum(unit.casts for unit in battle.units if unit.team == 0),
                                    **{field: summary[field] for field in ('triggers', 'total_energy', 'total_shield', 'absorbed')}})
                totals = {field: sum(row[field] for row in samples)
                          for field in ('casts', 'triggers', 'total_energy', 'total_shield', 'absorbed')}
                groups.append({'scenario': key, 'opponent': opponent, 'mode': mode, 'games': seeds,
                               'wins': sum(row['winner'] == 0 for row in samples),
                               'draws': sum(row['winner'] is None for row in samples), 'totals': totals,
                               'samples': samples})
    return {'description': '固定种子、等星级和人口的构筑消融；用于观察触发和收益，不作全环境胜率排行。',
            'seeds_per_group': seeds, 'games': seeds * len(groups), 'groups': groups}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seeds', type=int, default=12)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.seeds <= 100:
        parser.error('--seeds must be between 1 and 100')
    result = probe(args.seeds)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'games': result['games'], 'out': str(args.out)}, ensure_ascii=False))
