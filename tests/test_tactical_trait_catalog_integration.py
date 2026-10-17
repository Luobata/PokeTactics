"""Settled tactical benefits survive the report and save boundaries."""
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'sim'), str(ROOT / 'tools/acceptance')]
import arena
import arena_families as families
from combat import Battle
from combination_view import battle_summary, field_summary
import demo
from session_save import SessionCodec


class TacticalTraitCatalogIntegration(unittest.TestCase):
    def test_murkrow_actual_energy_is_reported_and_portable(self):
        battle = Battle([families.make_piece(198)], [families.make_piece(128)],
                        random.Random(1717), ruleset='arena_v1', stat_mode='budget_v1',
                        arena_teams=[[], []], positions_a=[(2, 3)], positions_b=[(2, 2)])
        source, target = battle.units
        source.energy, target.energy = 0, 40
        source.hp = source.max_hp = target.hp = target.max_hp = 2000
        target.vulnerable_until = 5
        battle._land_hit(source, target, 100, 1., primary=True, direct=True)
        evidence = next(e[6] for e in battle.events
                        if e[1] == 'combo_effect' and e[4:6] == ('trait_night_feed', 'energy_drain'))
        teams = {u.idx: u.team for u in battle.units}
        summary = battle_summary(battle.events, teams, 0)
        row = next(r for r in summary['by_key'] if r['id'] == 'trait_night_feed')
        self.assertEqual(row['energy'], evidence['gained'])
        self.assertGreater(row['energy'], 0)
        self.assertLess(row['energy'], evidence['stolen'])
        self.assertEqual(row['triggers'], 1)
        SessionCodec._validate_combination_summary(summary)

        session = demo.Session(1717, 'arena_v1', arena_pool=families.VERSION)
        session.begin_round(1)
        session.phase = 'battle'
        for reward in list(session.arena_augments_pending):
            arena.claim_augment(session, reward['id'], reward['options'][0]['id'])
        session.last_battle = {
            'round': 1, 'winner': 0, 'survivors': {0: 1, 1: 1}, 'duration': 1.,
            'pve': False, 'ghost': False, 'opp_name': '研习验收',
            'statistics': battle.statistics(), 'effect_version': 1,
            'combinations': summary, 'enemy_combinations': battle_summary(battle.events, teams, 1),
            'fields': field_summary(battle.events, teams, 0),
            'enemy_fields': field_summary(battle.events, teams, 1),
        }
        codec = SessionCodec()
        restored = codec.decode(codec.encode(session), 5)
        saved_row = next(r for r in restored.last_battle['combinations']['by_key']
                         if r['id'] == 'trait_night_feed')
        self.assertEqual(saved_row, row)


if __name__ == '__main__':
    unittest.main()
