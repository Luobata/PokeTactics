"""Portal catalog views follow explicit arena pool versions."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "sim"), str(ROOT / "tools/acceptance")]

import arena
import arena_families as families
import demo
import portal
import family_catalog
import arena_research

class PortalPoolCatalogTests(unittest.TestCase):
    def test_default_remains_the_frozen_legacy_contract(self):
        view = portal.catalog_view(demo)
        self.assertEqual(view['version'], 'species_v1')
        self.assertEqual(len(view['pokemon']), len(arena.ROSTER))
        self.assertEqual({row['sid'] for row in view['pokemon']}, set(arena.ROSTER))
        self.assertEqual(len(view['traits']), 65)
        self.assertLessEqual({sid for row in view['bonds'] for sid in row['members']},
                             set(arena.ROSTER))

    def test_family_versions_expose_only_pool_forms_and_traits(self):
        for version, expected_forms in ((families.FIRST_VERSION, 120),
                                        (families.VERSION, 151)):
            with self.subTest(version=version):
                view = portal.catalog_view(demo, version=version)
                expected = set(families.build_templates(version))
                self.assertEqual(view['version'], version)
                self.assertEqual(len(view['pokemon']), expected_forms)
                self.assertEqual({row['sid'] for row in view['pokemon']}, expected)
                self.assertEqual(len(view['traits']),
                                 122 if version == families.FIRST_VERSION else 153)
                self.assertLessEqual({row['sid'] for row in view['traits']}, expected)
                self.assertEqual({row['id'] for row in view['bonds']},
                                 {row['id'] for row in portal.catalog_view(demo)['bonds']})

    def test_family_catalog_uses_pool_stock_generation_and_bond_members(self):
        view = portal.catalog_view(demo, version=families.VERSION)
        rows = {row['sid']: row for row in view['pokemon']}
        self.assertEqual(rows[252]['pool_total'], families.POOL_BY_COST[2])
        self.assertEqual(rows[253]['pool_total'], 0)
        self.assertEqual(rows[252]['generation'], 3)
        self.assertEqual(rows[252]['generation_name'], '第3世代')

        legal = set(rows)
        for bond in view['bonds']:
            self.assertTrue(bond['members'])
            self.assertLessEqual(set(bond['members']), legal)
            self.assertEqual(bond['pool_size'], len(bond['members']))
        self.assertIn(252, next(row['members'] for row in view['bonds'] if row['id'] == 'GRASS'))

    def test_build_bond_candidates_stay_in_selected_family_pool(self):
        view = portal.catalog_view(demo, version=families.FIRST_VERSION)
        legal = set(families.build_templates(families.FIRST_VERSION))
        stages = [stage for build in view['builds']
                  for stage in (build['base_stage'], build.get('transition')) if stage]
        self.assertTrue(stages)
        for stage in stages:
            for entry in stage['bonds']['entries']:
                self.assertLessEqual(set(entry['candidates']), legal)

    def test_eevee_preview_and_live_evolution_choices_share_tactical_traits(self):
        view = family_catalog.catalog_view(families.VERSION)
        family = next(row for row in view['families'] if row['id'] == 133)
        starter = demo._piece_view(families.make_piece(133), ruleset='arena_v1')
        live_routes = {row['branch']: row for row in starter['family']['routes']}
        trait_ids = set()
        for branch in family['branches']:
            evolved = branch['stages'][1]
            trait = evolved['trait']
            self.assertEqual(evolved['total_cost'], 6)
            self.assertEqual(trait, live_routes[branch['id']]['trait'])
            self.assertTrue(trait['playstyle'])
            self.assertTrue(trait['synergy'])
            self.assertTrue(trait['counterplay'])
            trait_ids.add(trait['id'])
        self.assertEqual(len(trait_ids), 5)
        self.assertEqual(view['research_catalog'], arena_research.catalog())


if __name__ == "__main__":
    unittest.main()
