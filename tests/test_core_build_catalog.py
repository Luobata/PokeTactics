"""Core routes compare legal current builds without teammate-filter ambiguity."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'sim'), str(ROOT / 'tools/acceptance')]
import demo
import portal
import arena_bonds


class CoreBuildCatalog(unittest.TestCase):
    def catalog(self):
        with patch.object(demo, 'Session', side_effect=AssertionError('Browsing allocated a game')):
            return portal.catalog_view(demo)

    def test_multiple_core_routes_use_different_triggers_and_legal_single_slots(self):
        data = self.catalog()
        pokemon = {row['sid']: row for row in data['pokemon']}
        for sid, expected in ((6, 3), (34, 4), (212, 2)):
            routes = [row for row in data['builds'] if row['core'] == sid]
            self.assertEqual(len(routes), expected)
            self.assertEqual(len({row['item'] for row in routes}), expected)
            for row in routes:
                self.assertIn(row['technique'], pokemon[sid]['learnable'])
                self.assertIsInstance(row['item'], str)
                self.assertIsInstance(row['augment'], str)
                self.assertTrue(row.get('trigger') or row['steps'])
        self.assertEqual({row['core'] for row in data['builds'] if row['item'] == 'contagion_orb'}, {6, 34})
        self.assertEqual({row['core'] for row in data['builds'] if row['item'] == 'metronome'}, {6, 34, 212})
        self.assertEqual({row['core'] for row in data['builds'] if row['augment'] == 'native_inspiration'}, {6})

    def test_formation_stages_preserve_special_conversion_requirements(self):
        data = self.catalog()
        pokemon = {row['sid']: row for row in data['pokemon']}
        self.assertEqual(data['bonds'], arena_bonds.catalog())
        for row in data['builds']:
            with self.subTest(build=row['id']):
                base = row['base_stage']
                self.assertFalse(base['requires_augment'])
                self.assertIn(row['core'], base['members'])
                self.assertTrue(set(base['members']) <= pokemon.keys())
                self.assertTrue(base['summary'])
                self.assertTrue(base['substitutes'])
                self.assertEqual(set(row['upgrades']), {'item', 'technique', 'augment'})
                self.assertTrue(all(row['upgrades'].values()))
                if row.get('transition'):
                    transition = row['transition']
                    self.assertTrue(all(pokemon[sid]['cost'] == 1 for sid in transition['members']))
                    self.assertTrue(transition['summary'])
                    self.assertTrue(any(entry['tier'] for entry in transition['bonds']['entries']))
                    self.assertEqual(transition['bonds'], arena_bonds.preparation(transition['members']))
                self.assertEqual(base['bonds'], arena_bonds.preparation(base['members']))
                if row['augment'] in {'barrier_feedback', 'breach_momentum', 'poison_catalyst',
                                       'watch_echo', 'native_inspiration'}:
                    self.assertTrue(row['augment_conversion'])
                    self.assertIn('才', row['upgrades']['augment'])
                else:
                    self.assertFalse(row['augment_conversion'])
        for sid, row in pokemon.items():
            self.assertEqual(row['bonds'], arena_bonds.memberships(sid))

    def test_native_poison_is_distinct_from_the_tm_probability_in_route_copy(self):
        builds = {row['id']: row for row in self.catalog()['builds']}
        attrition = builds['nidoking_attrition']
        self.assertIn('本命命中后，对存活、非免疫且无主要异常的目标直接施毒', attrition['steps'][0])
        self.assertIn('污泥弹技能机有35%中毒概率', attrition['steps'][0])
        self.assertIn('无主要异常的目标直接施毒', builds['poison_pursuit']['steps'][1])
        self.assertIn('侧击实际扣血后', attrition['gen2_advice'])
        self.assertIn('按相同条件直接施毒', builds['poison_engine']['gen2_advice'])
        for key in ('nidoking_attrition', 'poison_pursuit', 'poison_engine'):
            self.assertNotIn('分别尝试施毒', ' '.join(builds[key]['steps']) + builds[key]['gen2_advice'])

    @unittest.skipUnless(shutil.which('node'), 'Node.js is needed for the actual frontend handlers')
    def test_exact_core_selector_comparison_stable_links_and_legacy_search(self):
        result = subprocess.run([shutil.which('node'), str(ROOT / 'tests/frontend/core_builds_catalog.js'),
                                 str(ROOT / 'tools/acceptance/hub.js')],
                                input=json.dumps(self.catalog()), capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'Node.js is needed for the actual frontend handlers')
    def test_family_catalog_handlers_counts_and_uncovered_species(self):
        with patch.object(demo, 'Session', side_effect=AssertionError('Browsing allocated a game')):
            data = portal.catalog_view(demo, 'families_v2')
        result = subprocess.run([shutil.which('node'), str(ROOT / 'tests/frontend/core_builds_catalog.js'),
                                 str(ROOT / 'tools/acceptance/hub.js')],
                                input=json.dumps(data), capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
