"""Family counts, useful tactical guidance and preview links stay honest."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'sim'), str(ROOT / 'tools/acceptance'), str(ROOT / 'tools/mockups')]
import arena_families as families
import arena_bonds
import arena_scenarios
import demo
import portal


class BondDepthCatalog(unittest.TestCase):
    def test_family_counts_are_not_form_counts_and_every_threshold_is_reachable(self):
        data = portal.catalog_view(demo, families.VERSION)
        self.assertEqual(len(data['bonds']), 25)
        for row in data['bonds']:
            with self.subTest(bond=row['id']):
                identities = {families.SPECIES_FAMILY[sid] for sid in row['members']}
                self.assertEqual(row['identity_count'], len(identities))
                self.assertEqual(row['count_unit'], '家族')
                self.assertEqual(row['identity_by_species'],
                                 {str(sid): families.SPECIES_FAMILY[sid] for sid in row['members']})
                self.assertLessEqual(max(t['count'] for t in row['thresholds']), len(identities))
                if row['category'] == 'tactic':
                    self.assertTrue(row['playstyle'])
                    self.assertTrue(row['synergy'])
                    self.assertTrue(row['counterplay'])
                    self.assertIn(row['scenario'], arena_scenarios.SCENARIOS)

    def test_battle_reports_use_the_same_legal_family_catalog_as_the_dex(self):
        for version in families.VERSIONS:
            with self.subTest(version=version):
                session = demo.Session(20261017, 'arena_v1', arena_pool=version)
                state = demo.state_json(session)
                self.assertEqual(state['arena']['bond_catalog'],
                                 portal.catalog_view(demo, version)['bonds'])

    def test_evolved_types_determine_new_tactics_and_siblings_count_once(self):
        self.assertIn('bond_mindsong', arena_bonds.memberships(196))
        self.assertNotIn('bond_mindsong', arena_bonds.memberships(197))
        self.assertNotIn('bond_mindsong', arena_bonds.memberships(133))
        self.assertNotIn('bond_dragon_pressure', arena_bonds.memberships(333))
        self.assertIn('bond_dragon_pressure', arena_bonds.memberships(334))
        members = [families.make_piece(280, step) for step in (1, 2, 3)]
        self.assertEqual(arena_bonds.count(members)['bond_mindsong'], 1)

    def test_new_previews_really_trigger_without_equipment(self):
        for suffix in ('frostline', 'spirit', 'mindsong', 'dragon_pressure'):
            with self.subTest(bond=suffix):
                key = 'arena_bond_' + suffix
                spec = arena_scenarios.SCENARIOS[key]
                for side in ('a', 'b'):
                    for prefix in ('items_', 'learned_', 'augments_'):
                        self.assertFalse(spec.get(prefix + side))
                anim = arena_scenarios.make_scene(7, key)
                effects = [event for event in anim.events if event[1] == 'combo_effect'
                           and event[4] == 'bond_' + suffix
                           and event[5] != 'expire' and anim.by_idx[event[2]].team == 0]
                self.assertTrue(effects, key)


if __name__ == '__main__':
    unittest.main()
