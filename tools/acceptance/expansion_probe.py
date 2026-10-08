"""Reproducible natural-action samples, intended for mechanics rather than ranking."""
import argparse
import copy
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'sim'), str(ROOT / 'tools/acceptance')]
import arena
import arena_skills
import techniques
from combat import Battle
from combination_view import battle_summary, field_summary


def run(seeds=12):
    templates = arena.build_templates()
    condition_keys = {arena_skills.skill_of(sid)['id'] for sid in (123, 125)}
    groups = []
    configurations = {
        'rock_full': [(95, 'focus_lens'), (106, 'choice_band'), (128, 'leftovers'), (131, 'heart_bell')],
        'rock_without_layer': [(76, 'focus_lens'), (106, 'choice_band'), (128, 'leftovers'), (131, 'heart_bell')],
        'rock_without_push': [(95, 'focus_lens'), (34, 'choice_band'), (73, 'leftovers'), (131, 'heart_bell')],
        'rock_trap_lens': [(95, 'trap_lens'), (106, 'choice_band'), (128, 'leftovers'), (131, 'heart_bell')],
        'root_pursuit': [(114, 'focus_lens'), (123, 'choice_band'), (127, 'swift_feather'), (113, 'heart_bell')],
        'paralysis_relay': [(26, 'focus_lens'), (125, 'scarf_electric'), (122, 'leftovers'), (108, 'heart_bell')],
    }
    for name, roster in configurations.items():
        for counter in ('mixed', 'boots'):
            samples = []
            for offset in range(seeds):
                a = [(copy.copy(templates[sid]), item) for sid, item in roster]
                b = [(copy.copy(templates[sid]), 'heavy_boots' if counter == 'boots' else item)
                     for sid, item in [(6, 'focus_lens'), (59, 'leftovers'), (127, 'choice_band'), (113, 'heart_bell')]]
                for piece, _ in a + b:
                    piece.star = 2
                battle = Battle(a, b, random.Random(41000 + offset), ruleset='arena_v1', stat_mode='budget_v1',
                                positions_a=arena.positions_for(a, 0), positions_b=arena.positions_for(b, 1),
                                arena_teams=[['mana_flow', 'watch_echo'], ['mana_flow']],
                                learned_a=[None, None, None, 'ice_beam' if techniques.compatible_species(roster[-1][0], 'ice_beam') else 'thunderbolt'],
                                learned_b=[None, None, None, 'thunderbolt'])
                result = battle.run()
                teams = {unit.idx: unit.team for unit in battle.units}
                fields = field_summary(battle.events, teams)
                # Count opposition boots against our terrain separately from our avoidance.
                fields['enemy_boots_avoided'] = sum(e[1] == 'field_effect' and e[4] == 'rock_spikes'
                    and e[5] == 'avoid' and teams[e[2]] == 0 and e[6].get('reason') == 'heavy_boots'
                    for e in battle.events)
                native = sum(e[1] == 'cast' and e[2] < 4 and e[4].startswith('arena_') for e in battle.events)
                condition_hits = sum(e[1] == 'skill_effect' and e[2] < 4
                    and e[4] in condition_keys and e[5] == 'side_hit' for e in battle.events)
                samples.append({'seed': 41000 + offset, 'winner': result['winner'],
                                'duration': round(result['duration'], 2), 'native_casts': native,
                                'condition_hits': condition_hits, **fields,
                                'combinations': battle_summary(battle.events, teams)})
            totals = {key: sum(row[key] for row in samples) for key in
                      ('native_casts', 'condition_hits', 'triggers', 'damage', 'absorbed', 'avoided', 'cleared', 'enemy_boots_avoided')}
            groups.append({'configuration': name, 'counter': counter, 'games': seeds,
                           'wins': sum(row['winner'] == 0 for row in samples), 'totals': totals, 'samples': samples})
    # Default formations produced no conditional follow-ups against the burst
    # opponent. Expand the sample to legal seeded placements and durable foes;
    # retain the zero groups above instead of presenting only successful cases.
    explorations = []
    for name, roster in {
        'rock_early_push': [(95, 'focus_lens'), (9, 'focus_lens'), (128, 'leftovers'), (131, 'heart_bell')],
        'root_positions': configurations['root_pursuit'],
        'paralysis_positions': configurations['paralysis_relay'],
    }.items():
        samples = []
        for offset in range(100):
            a = [(copy.copy(templates[sid]), item) for sid, item in roster]
            opponents = ((128, 'leftovers'), (106, 'choice_band'), (40, 'heart_bell'), (114, 'leftovers')) if name == 'rock_early_push' else (
                (113, 'leftovers'), (131, 'leftovers'), (40, 'leftovers'), (9, 'leftovers'))
            b = [(copy.copy(templates[sid]), item) for sid, item in opponents]
            for piece, _ in a + b:
                piece.star = 2
            placement = random.Random(offset)
            pa = placement.sample([(c, r) for c in range(6) for r in (3, 4, 5)], 4)
            pb = placement.sample([(c, r) for c in range(6) for r in (0, 1, 2)], 4)
            battle = Battle(a, b, random.Random(43000 + offset), ruleset='arena_v1', stat_mode='budget_v1',
                            positions_a=pa, positions_b=pb,
                            arena_teams=[['mana_flow', 'watch_echo'], ['mana_flow']])
            result = battle.run()
            teams = {unit.idx: unit.team for unit in battle.units}
            conditional = sum(e[1] == 'skill_effect' and e[2] < 4
                              and e[4] in condition_keys and e[5] == 'side_hit' for e in battle.events)
            samples.append({'seed': 43000 + offset, 'positions_a': pa, 'positions_b': pb,
                            'winner': result['winner'], 'duration': result['duration'],
                            'condition_hits': conditional, **field_summary(battle.events, teams)})
        explorations.append({'configuration': name, 'games': 100, 'samples': samples,
                             'totals': {key: sum(row[key] for row in samples) for key in
                                        ('condition_hits', 'triggers', 'damage', 'absorbed', 'avoided', 'cleared')}})
    return {'description': '自然行动的小样本机制验证，未预设满能量或状态；替换精灵、装备与对手会改变基础强度，随机合法站位也不是玩家优化站位，不能据此宣称胜率定标。',
            'seeds_per_group': seeds, 'games': seeds * len(groups) + 300,
            'groups': groups, 'placement_explorations': explorations}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--seeds', type=int, default=12)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.seeds <= 100:
        parser.error('seeds must be between 1 and 100')
    output = run(args.seeds)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'games': output['games'], 'groups': len(output['groups'])}))
