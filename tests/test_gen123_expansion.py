"""Hoenn expansion boundaries: historical reference, versioned pool and real saves."""
import copy
import io
import json
import sys
import tempfile
import threading
import unittest
from collections import Counter
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'sim'), str(ROOT / 'tools/acceptance'), str(ROOT / 'tools/mockups')]
import arena
import arena_families as families
import demo
import server
import shop
from data import pokedex
from decoders import Front, Palettes
from family_catalog import catalog_view, reference_view
from session_save import SessionCodec, PRE_HOENN_FINGERPRINT
from PIL import Image


class Gen123Coverage(unittest.TestCase):
    def test_historical_reference_does_not_expand_classic_or_frozen_arena(self):
        dex = pokedex()
        self.assertEqual(set(dex.reference_species), set(range(1, 387)))
        self.assertEqual(Counter(r['generation'] for r in dex.reference_species.values()),
                         {1: 151, 2: 100, 3: 135})
        self.assertEqual(len(dex.species), 151)
        self.assertEqual(len(dex.arena_species), 42)
        self.assertEqual(len(shop.build_templates()), 84)
        self.assertEqual(len(arena.build_templates()), 62)
        # Runtime records prefer legacy files; validate them too, not just the new reference.
        for sid in families.SPECIES_FAMILY:
            self.assertTrue(set(dex.species_record(sid)['types']) <= set(dex.types), sid)
        self.assertEqual(dex.species_record(238)['types'], ['ICE', 'PSYCHIC'])
        for sid, record in dex.reference_species.items():
            self.assertEqual(record['generation'], dex.generation_of(sid))
            self.assertEqual(record['lineage'][0], sid)
            self.assertTrue(set(record['lineage']) <= dex.reference_species.keys())
            self.assertTrue(set(record['evolves_to']) <= dex.reference_species.keys())
            self.assertEqual(set(record['base']), {'hp', 'attack', 'defense', 'speed', 'special_attack', 'special_defense'})
            self.assertTrue(all(type(v) is int and 0 < v <= 255 for v in record['base'].values()))
            self.assertNotIn('FAIRY', record['types'])
            self.assertTrue(set(record['types']) <= set(dex.types))

    def test_reference_uses_gen3_stats_and_only_historical_evolutions(self):
        rows = pokedex().reference_species
        self.assertEqual(rows[25]['base']['defense'], 30)
        self.assertEqual(rows[164]['base']['special_attack'], 76)
        self.assertEqual(rows[282]['types'], ['PSYCHIC'])
        self.assertEqual(rows[35]['types'], ['NORMAL'])
        self.assertEqual(rows[133]['evolves_to'], [134, 135, 136, 196, 197])
        self.assertEqual(rows[281]['evolves_to'], [282])
        self.assertEqual(rows[183]['lineage'], [183, 298])
        self.assertEqual(rows[242]['lineage'], [242, 113])
        self.assertEqual(rows[143]['lineage'], [143])

    def test_two_pool_versions_have_explicit_inventory_and_form_boundaries(self):
        old, new = catalog_view(families.FIRST_VERSION), catalog_view()
        self.assertEqual((len(old['families']), old['forms'], old['total_stock']), (56, 120, 1136))
        self.assertEqual((len(new['families']), new['forms'], new['total_stock']), (68, 151, 1390))
        self.assertEqual(new['distribution'], {1: 17, 2: 27, 3: 19, 4: 3, 5: 2})
        self.assertEqual(set(families.build_templates()) - set(families.build_templates(families.FIRST_VERSION)),
                         {sid for sid in families.SPECIES_FAMILY if sid >= 252})
        self.assertEqual(new['families'][:56], old['families'])
        self.assertTrue(all(cap == 0 for sid, cap in families.pool_caps().items() if sid not in families.FAMILIES))

    def test_reference_playability_matches_selected_pool(self):
        for version in families.VERSIONS:
            result = reference_view(version)
            self.assertEqual(len(result['species']), 386)
            self.assertEqual({r['id'] for r in result['species'] if r['playable']}, set(families.pool_caps(version)))
            for row in result['species']:
                if row['playable']:
                    self.assertIn(row['family'], families.families_for(version))
                    self.assertEqual(row['cost'], families.families_for(version)[row['family']][0])
                else:
                    self.assertIsNone(row['family'])
                    self.assertIsNone(row['cost'])

    def test_old_pool_bond_hints_do_not_offer_hoenn_recruits(self):
        for version in families.VERSIONS:
            session = demo.Session(181, 'arena_v1', arena_pool=version)
            session.begin_round(1)
            session.pool.take(4)
            session.player.grid[(0, 0)] = shop.OwnedPiece(session.templates[4], 2)
            state = demo.state_json(session)
            fire = next(row for row in state['bonds']['entries'] if row['id'] == 'FIRE')
            self.assertTrue(set(fire['candidates']) <= session.templates.keys())
            self.assertEqual(255 in fire['candidates'], version == families.VERSION)

    def test_all_386_sprites_and_shiny_variants_decode_with_visible_pixels(self):
        front, palettes = Front(), Palettes()
        for sid in range(1, 387):
            for shiny in (False, True):
                with self.subTest(sid=sid, shiny=shiny):
                    image = front.image(sid, palettes, shiny=shiny)
                    self.assertEqual(image.mode, 'RGBA')
                    self.assertIsNotNone(image.getchannel('A').getbbox())
                    with Image.open(io.BytesIO(demo.sprite_png(sid, shiny))) as served:
                        self.assertEqual(served.size, image.size)
                        self.assertEqual(served.tobytes(), image.tobytes())
                    if sid >= 252:
                        path = ROOT / 'assets/gen3' / ('shiny' if shiny else 'normal') / f'{sid}.png'
                        with Image.open(path) as source:
                            self.assertEqual(source.mode, 'RGBA')
                            self.assertEqual(source.tobytes(), image.tobytes(), 'Do not erase internal white pixels')
                        self.assertEqual(image.getpixel((0, 0))[3], 0)


class HoennSaveCompatibility(unittest.TestCase):
    def fixture(self):
        return json.loads((ROOT / 'tests/fixtures/family-v1-pre-gen3.json').read_text())

    def test_real_predecessor_restores_without_expanding_or_repricing_pool(self):
        old = self.fixture()
        original = copy.deepcopy(old)
        self.assertEqual(old['rules'], PRE_HOENN_FINGERPRINT)
        codec = SessionCodec()
        restored = codec.decode(old, 5)
        current = codec.encode(restored)
        expected = copy.deepcopy(old)
        expected['rules'] = current['rules']
        self.assertEqual(current, expected)
        self.assertEqual(old, original)
        self.assertEqual(restored.arena_pool, families.FIRST_VERSION)
        self.assertEqual(set(restored.templates), set(families.pool_caps(families.FIRST_VERSION)))
        self.assertEqual(codec.encode(codec.decode(current, 5)), current)

    def test_predecessor_cannot_claim_new_version_or_hoenn_units(self):
        codec = SessionCodec()
        bad = self.fixture()
        bad['arena_pool'] = families.VERSION
        with self.assertRaises(ValueError):
            codec.decode(bad, 5)
        bad = self.fixture()
        bad['seats'][0]['bench'][0]['species'] = 252
        with self.assertRaises(ValueError):
            codec.decode(bad, 5)
        bad = self.fixture()
        bad['seats'][0]['shop'][0] = 252
        with self.assertRaises(ValueError):
            codec.decode(bad, 5)

    def test_new_game_uses_v2_and_original_pool_can_still_start(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(demo, 'SAVE_ROOT', Path(directory)), patch.object(demo, 'SESSIONS', {}):
            result = demo.api_action({'cmd': 'new', 'seed': '812', 'mode': 'arena'})
            self.assertTrue(result['ok'], result)
            self.assertEqual(demo.SESSIONS[result['sid']].arena_pool, families.VERSION)
        for version in families.VERSIONS:
            session = demo.Session(812, 'arena_v1', arena_pool=version)
            session.begin_round(1)
            for seat in session.seats:
                self.assertTrue((set(seat.shop.slots) - {None}) <= families.families_for(version).keys())


class ExpandedPortalRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.httpd.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)

    def read(self, path):
        with urlopen(self.base + path, timeout=10) as response:
            self.assertEqual(response.status, 200)
            return response.read()

    def test_versioned_catalogs_are_read_only_and_invalid_versions_fail(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(demo, 'SAVE_ROOT', Path(directory)), patch.object(demo, 'Session', side_effect=AssertionError('Reference browsing created a session')):
            for version, count in ((families.FIRST_VERSION, 56), (families.VERSION, 68)):
                data = json.loads(self.read('/api/portal/families?pool=' + version))
                self.assertEqual(len(data['families']), count)
                self.assertEqual(data['version'], version)
                data = json.loads(self.read('/api/portal/species?pool=' + version))
                self.assertEqual(len(data['species']), 386)
                data = json.loads(self.read('/api/portal/catalog?pool=' + version))
                self.assertEqual({p['sid'] for p in data['pokemon']}, set(families.pool_caps(version)))
                self.assertEqual(any(row['sid'] == 252 for row in data['traits']), version == families.VERSION)
                self.read('/pokedex?view=all&pool=' + version)
            self.read('/hub/assets/reference_dex.js')
            self.assertEqual(list(Path(directory).iterdir()), [])
        for route in ('families', 'species', 'catalog'):
            with self.assertRaises(HTTPError) as error:
                self.read('/api/portal/' + route + '?pool=unreleased')
            self.assertEqual(error.exception.code, 400)


if __name__ == '__main__':
    unittest.main()
