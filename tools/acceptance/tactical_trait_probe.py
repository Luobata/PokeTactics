"""Paired, deterministic smoke probe for the six tactical trait redesigns.

Only the focal unit's passive is disabled in the control arm. This measures
activation and team outcome in fixed lineups, not ladder balance or shop odds.
Run: python3 tools/acceptance/tactical_trait_probe.py --seeds 20 --output PATH
"""
import argparse
import json
from pathlib import Path
import random
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'sim'), str(ROOT / 'tools/acceptance'), str(ROOT)]
import arena_families as families
import arena_traits as traits
from combat import Battle
from combination_view import battle_summary
from session_save import rules_fingerprint

FOCAL = (134, 135, 136, 196, 197, 198)
PARTNERS = {134: (9, 6, 36), 135: (9, 65, 196), 136: (59, 6, 157),
            196: (208, 127, 242), 197: (9, 135, 65), 198: (31, 196, 45)}
OPPONENTS = ((9, 65, 36, 125), (59, 6, 45, 31), (197, 198, 121, 68))


def run(seeds):
    templates = families.build_templates()
    original = traits._spec
    rows = []
    for sid in FOCAL:
        spec = traits.for_species(sid)
        counters = dict(battles=0, active_battles=0, wins=0, control_wins=0,
                        triggers=0, healing=0, energy=0, shield=0,
                        absorbed=0, damage=0, vulnerable=0)
        for opponent in OPPONENTS:
            for seed in range(seeds):
                for enabled in (False, True):
                    own = [families.make_piece(families.SPECIES_FAMILY[i], 3, i) for i in (sid, *PARTNERS[sid])]
                    enemy = [families.make_piece(families.SPECIES_FAMILY[i], 3, i) for i in opponent]
                    def selected(battle, unit, key=None):
                        if not enabled and unit is not None and unit.team == 0 and unit.piece.species_id == sid:
                            return None
                        return original(battle, unit, key)
                    # Tanks face the frontline; ranged focal units fire from
                    # one row behind it. Every fixture uses real family panels.
                    positions = ([(2, 3), (3, 3), (2, 4), (3, 4)]
                                 if own[0].role_key == 'defense' else
                                 [(2, 4), (2, 3), (3, 4), (3, 3)])
                    with patch.object(traits, '_spec', selected):
                        battle = Battle(own, enemy, random.Random(171000 + seed),
                                        ruleset='arena_v1', stat_mode='budget_v1',
                                        arena_teams=[[], []], positions_a=positions,
                                        positions_b=[(2, 2), (2, 1), (3, 1), (3, 2)])
                        result = battle.run()
                    if not enabled:
                        counters['control_wins'] += result['winner'] == 0
                        continue
                    counters['battles'] += 1
                    counters['wins'] += result['winner'] == 0
                    # Keep only focal-produced facts; a mirrored opponent or
                    # another ally with the same id cannot inflate its score.
                    focal_idx = next(u.idx for u in battle.units
                                     if u.team == 0 and u.piece.species_id == sid)
                    events = [e for e in battle.events
                              if e[1] == 'combo_effect' and e[2] == focal_idx]
                    summary = battle_summary(events, {u.idx: u.team for u in battle.units}, 0)
                    row = next((r for r in summary['by_key'] if r['id'] == spec['id']), {})
                    counters['active_battles'] += bool(row.get('triggers'))
                    for field in ('triggers', 'healing', 'energy', 'shield', 'absorbed', 'damage', 'vulnerable'):
                        counters[field] += row.get(field, 0)
        rows.append(dict(sid=sid, name=templates[sid].name, trait=spec['name'], partners=PARTNERS[sid], **counters))
    return dict(rules=rules_fingerprint(), training_step=3, seeds_per_matchup=seeds, opponent_lineups=OPPONENTS,
                rows=rows,
                limitation='固定阵容的特性开关对照；非排位胜率，不含经济、选牌与本局研习。')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--seeds', type=int, default=20)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.seeds < 1:
        parser.error('--seeds must be positive')
    result = run(args.seeds)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
