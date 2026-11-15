"""PMD SpriteCollab frame sprites (docs/60): import outputs, coverage, serving."""
import json
import re
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/acceptance'), str(ROOT / 'tools/mockups'), str(ROOT / 'sim')]
import pmd_import  # noqa: E402

PMD = ROOT / 'assets' / 'pmd'


class PmdImportOutputs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = json.loads((PMD / 'index.json').read_text())
        cls.sources = json.loads((PMD / 'SOURCES.json').read_text())

    def test_index_is_pinned_and_outputs_match_their_hashes(self):
        self.assertEqual(self.index['schema'], pmd_import.INDEX_SCHEMA)
        self.assertEqual(self.index['commit'], pmd_import.PINNED_SHA)
        self.assertEqual(self.sources['commit'], pmd_import.PINNED_SHA)
        self.assertRegex(self.sources['commit'], r'^[0-9a-f]{40}$')
        for rel, digest in self.sources['outputs'].items():
            self.assertEqual(pmd_import.sha256(PMD / rel), digest, rel)
        for rel, row in self.sources['files'].items():
            self.assertIn(pmd_import.PINNED_SHA, row['url'])
            self.assertRegex(row['sha256'], r'^[0-9a-f]{64}$')

    def test_every_arena_species_resolves_to_pmd_or_an_explicit_fallback(self):
        species = pmd_import.arena_species()
        self.assertGreaterEqual(len(species), 150)
        for sid in species:
            key = str(sid)
            in_pmd, in_fallback = key in self.index['species'], key in self.index['fallback']
            self.assertTrue(in_pmd != in_fallback, f'#{sid} must be exactly one of pmd / fallback')
            if in_fallback:
                self.assertEqual(self.index['fallback'][key]['style'], 'classic')
                self.assertTrue(self.index['fallback'][key]['reason'])
        self.assertGreaterEqual(len(self.index['species']) / len(species), 0.95)

    def test_manifests_validate_and_cover_the_core_animations(self):
        for key, row in self.index['species'].items():
            manifest = json.loads((PMD / row['file']).read_text())
            self.assertEqual(pmd_import.validate_manifest(manifest), [], key)
            self.assertTrue((PMD / manifest['atlas']).is_file())
            if manifest['shiny_atlas']:
                self.assertTrue((PMD / manifest['shiny_atlas']).is_file())
            for name in ('Idle', 'Walk', 'Attack', 'Hurt'):
                self.assertIn(name, manifest['anims'], f'#{key} lacks {name}')
            attack = manifest['anims']['Attack']
            self.assertIn('hit', attack, f'#{key} Attack has no HitFrame')
            self.assertEqual(sorted(attack['dirs']), ['0', '1', '2', '3', '4'])

    def test_action_mapping_validates_and_rejects_unknown_animations(self):
        actions = json.loads((PMD / 'actions.json').read_text())
        self.assertEqual(pmd_import.validate_actions(actions), [])
        actions['basic']['melee'] = ['Moonwalk']
        self.assertTrue(pmd_import.validate_actions(actions))
        bad = json.loads((PMD / 'index.json').read_text())
        manifest = json.loads((PMD / bad['species']['6']['file']).read_text())
        manifest['anims']['Attack']['hit'] = 99
        self.assertTrue(pmd_import.validate_manifest(manifest))

    def test_credits_and_size_budget(self):
        credits = (PMD / 'CREDITS.md').read_text()
        self.assertIn('CC BY-NC 4.0', credits)
        self.assertIn('CHUNSOFT', credits)
        self.assertIn(pmd_import.PINNED_SHA, credits)
        for key in self.index['species']:
            self.assertIn(f'| {int(key):04d} |', credits)
        total = sum(path.stat().st_size for path in PMD.rglob('*') if path.is_file())
        self.assertLess(total, 40 * 1024 * 1024)

    def test_atlases_are_lossless_palette_or_rgba_pngs(self):
        from PIL import Image
        for name in ('0006.png', '0025.png'):
            with Image.open(PMD / name) as image:
                self.assertIn(image.mode, ('P', 'RGBA'))
                self.assertLessEqual(image.width, pmd_import.ATLAS_WIDTH)


class PmdServing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import server
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.worker = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.worker.start()
        cls.base = f'http://127.0.0.1:{cls.httpd.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def get(self, path):
        try:
            response = urlopen(self.base + path, timeout=30)
        except HTTPError as error:
            response = error
        with response:
            return response.status, response.headers, response.read()

    def test_manifest_endpoint_and_classic_fallback(self):
        status, _, body = self.get('/api/pmd/manifest?species=6,25,9999')
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data['base'], '/pmd/')
        self.assertEqual(set(data['species']), {'6', '25'})
        self.assertEqual(data['fallback']['9999']['style'], 'classic')
        self.assertEqual(data['actions']['kind'], 'pmd_actions')
        self.assertIn('CC BY-NC', data['license'])

    def test_assets_are_cacheable_and_confined(self):
        status, headers, body = self.get('/pmd/0006.png')
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Type'], 'image/png')
        self.assertIn('max-age', headers['Cache-Control'])
        self.assertTrue(headers['ETag'])
        self.assertTrue(body.startswith(b'\x89PNG'))
        self.assertEqual(self.get('/pmd/portrait/0006.png')[0], 200)
        for path in ('/pmd/../server.py', '/pmd/%2e%2e/server.py', '/pmd/SOURCES.json', '/pmd/9999.png'):
            self.assertEqual(self.get(path)[0], 404, path)


if __name__ == '__main__':
    unittest.main()
