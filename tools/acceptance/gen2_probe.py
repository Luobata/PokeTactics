"""Seeded natural-action Gen2 samples; mechanics evidence, not a balance ranking."""
import argparse
import copy
import json
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'sim'), str(ROOT / 'tools/acceptance')]
import arena
import arena_skills
from combat import Battle
from combination_view import battle_summary, field_summary


def run():
    templates = arena.build_templates()

    def fight(roster, enemies, seed, placements=False):
        a = [(copy.copy(templates[sid]), item) for sid, item in roster]
        b = [(copy.copy(templates[sid]), item) for sid, item in enemies]
        for piece, _ in a + b:
            piece.star = 2
        if placements:
            rng = random.Random(seed)
            pa = rng.sample([(c, r) for c in range(6) for r in (3, 4, 5)], len(a))
            pb = rng.sample([(c, r) for c in range(6) for r in (0, 1, 2)], len(b))
        else:
            pa, pb = arena.positions_for(a, 0), arena.positions_for(b, 1)
        battle = Battle(a, b, random.Random(seed), stat_mode='budget_v1', ruleset=arena.RULESET,
                        positions_a=pa, positions_b=pb,
                        arena_teams=[['mana_flow', 'watch_echo', 'poison_catalyst'], ['mana_flow']])
        result = battle.run()
        assert result['duration'] <= 45
        assert all(0 <= unit.hp <= unit.max_hp for unit in battle.units)
        teams = {unit.idx: unit.team for unit in battle.units}
        casts = Counter(battle.units[e[2]].piece.species_id for e in battle.events
                        if e[1] == 'cast' and e[2] < len(a) and e[4].startswith('arena_'))
        followups = Counter(e[4] for e in battle.events
                            if e[1] == 'skill_effect' and e[2] < len(a) and e[5] == 'side_hit')
        return {'seed': seed, 'winner': result['winner'], 'duration': round(result['duration'], 2),
                'casts': dict(casts), 'followups': dict(followups),
                'fields': field_summary(battle.events, teams),
                'combinations': battle_summary(battle.events, teams)}

    witnesses = []
    for sid in arena.GEN2_ROSTER:
        allies = [sid] + [s for s in (195, 242, 214) if s != sid][:2]
        samples = [fight([(s, 'heart_bell' if templates[s].role_key == 'support' else 'leftovers') for s in allies],
                         [(128, 'leftovers'), (113, 'heart_bell'), (40, 'heart_bell')], 71000 + sid * 10 + n)
                   for n in range(3)]
        witnesses.append({'sid': sid, 'name': templates[sid].name,
                          'native_skill': arena_skills.skill_of(sid)['id'],
                          'casts': sum(row['casts'].get(sid, 0) for row in samples), 'samples': samples})
    builds = {
        '岩钉推阵': [(248, 'trap_lens'), (208, 'leftovers'), (160, 'leftovers'), (154, 'heart_bell')],
        '定身破甲追击': [(195, 'leftovers'), (214, 'choice_band'), (212, 'choice_band'), (242, 'heart_bell')],
        '易伤预见': [(127, 'leftovers'), (196, 'focus_lens'), (212, 'choice_band'), (154, 'heart_bell')],
        '铺毒警戒': [(211, 'focus_lens'), (162, 'choice_band'), (197, 'leftovers'), (164, 'heart_bell')],
        '麻痹信标': [(26, 'leftovers'), (181, 'scarf_electric'), (171, 'heart_bell'), (242, 'heart_bell')],
        '灼伤喷发': [(6, 'leftovers'), (157, 'focus_lens'), (197, 'leftovers'), (154, 'heart_bell')],
    }
    groups = []
    for i, (name, roster) in enumerate(builds.items()):
        for counter in ('mixed', 'boots') if i == 0 else ('mixed',):
            enemies = [(128, 'heavy_boots' if counter == 'boots' else 'leftovers'),
                       (131, 'heavy_boots' if counter == 'boots' else 'heart_bell'),
                       (113, 'heavy_boots' if counter == 'boots' else 'heart_bell'),
                       (40, 'heavy_boots' if counter == 'boots' else 'heart_bell')]
            samples = [fight(roster, enemies, 73000 + i * 100 + n, placements=True) for n in range(16)]
            groups.append({'name': name, 'counter': counter, 'samples': samples})
    return {'scope': 'Natural legal battles, no prefilled energy/status/terrain; mana_flow is a real selected augment. These samples verify finite execution and observed mechanics, not completed balance.',
            'roster_total': len(templates), 'gen2_total': len(witnesses),
            'games': sum(len(w['samples']) for w in witnesses) + sum(len(g['samples']) for g in groups),
            'witnesses': witnesses, 'builds': groups}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = run()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'games': result['games'], 'observed_native_species': sum(w['casts'] > 0 for w in result['witnesses'])}))
