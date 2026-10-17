"""Supplemental Gen2 data, shared-pool stock and verified save upgrades."""
import copy
from arena_save_expectations import with_synergy_defaults
import json
import sys
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'sim'), str(ROOT / 'tools/acceptance')]
import arena
import demo
import shop
from data import pokedex
from session_save import SessionCodec, PRE_GEN2_FINGERPRINT, UnknownRulesError


class Gen2Roster(unittest.TestCase):
    def test_supplemental_historical_data_preserves_classic_scope(self):
        dex = pokedex()
        self.assertEqual(set(dex.species), set(range(1, 152)))
        self.assertEqual(len(shop.build_templates()), 84)
        from arena_families import SPECIES_FAMILY
        self.assertEqual(set(dex.arena_species), {sid for sid in SPECIES_FAMILY if sid > 151})
        self.assertEqual(dex.species_record(164)['base']['special_attack'], 76)
        self.assertEqual(dex.species_record(181)['base']['defense'], 75)
        self.assertEqual(dex.species_record(208)['types'], ['STEEL', 'GROUND'])
        self.assertEqual(dex.species_record(248)['types'], ['ROCK', 'DARK'])
        for sid in dex.arena_species:
            record = dex.species_record(sid)
            self.assertGreater(dex.bst(sid), 0)
            self.assertTrue(record['level_up'])
            self.assertTrue(all(move in dex.moves for _, move in record['level_up']))
            self.assertIsNotNone(dex.signature_move(sid))

    def test_family_preform_moves_match_crystal_ids_and_level_one_spacing(self):
        # ASM pads single-digit levels; NO_MOVE is index zero, not move one.
        self.assertEqual(pokedex().species_record(155)['level_up'],
                         [[1, 33], [1, 43], [6, 108], [12, 52],
                          [19, 98], [27, 172], [36, 129], [46, 53]])

    def test_all_three_tiers_have_six_additions_and_fixed_per_species_stock(self):
        self.assertEqual(Counter(c for c, _ in arena.GEN2_ROSTER.values()), {1: 6, 2: 6, 3: 6})
        self.assertEqual(Counter(c for c, _ in arena.ROSTER.values()),
                         {1: 16, 2: 22, 3: 18, 4: 3, 5: 3})
        self.assertEqual(Counter(r for _, r in arena.ROSTER.values()), {'attack': 30, 'defense': 17, 'support': 15})
        self.assertEqual(len(arena.ROSTER), 62)
        self.assertEqual(sum(arena.pool_caps().values()), 906)

    def test_gen2_nine_copy_star_merge_save_and_sale_preserve_stock(self):
        codec = SessionCodec()
        for sid in arena.GEN2_ROSTER:
            with self.subTest(species=sid):
                session = demo.Session(71007, 'arena_v1')
                session.begin_round(1)
                before = session.pool.remaining[sid]
                for _ in range(9):
                    session.pool.take(sid)
                    session.player.bench.append(shop.OwnedPiece(copy.copy(session.templates[sid]), arena.ROSTER[sid][0]))
                    session.combine_player()
                own, = session.player.bench
                self.assertEqual((own.piece.species_id, own.piece.star, own.piece.shiny), (sid, 3, True))
                self.assertEqual(own.sources, [sid] * 9)
                payload = codec.encode(session)
                restored = codec.decode(payload, 5)
                self.assertEqual(codec.encode(restored), payload)
                demo.act_sell(restored, 'b0')
                self.assertEqual(restored.pool.remaining[sid], before)


class Gen2SaveCompatibility(unittest.TestCase):
    def fixture(self):
        return json.loads((ROOT / 'tests/fixtures/arena-v5-pre-gen2-prep.json').read_text())

    def test_real_thirty_species_save_preserves_every_committed_field(self):
        codec = SessionCodec()
        old = self.fixture()
        untouched = copy.deepcopy(old)
        self.assertEqual(old['rules'], PRE_GEN2_FINGERPRINT)
        restored = codec.decode(old, 5)
        current = codec.encode(restored)
        expected = with_synergy_defaults(old)
        expected['rules'] = current['rules']
        expected['battle_history'] = []
        expected['arena'].update(component_choices=[],
                                 component_choice_start=old['round'] + (old['phase'] != 'prep'))
        expected['pool'].update({str(sid): arena.pool_cap(sid) for sid in arena.GEN2_ROSTER})
        self.assertEqual(current, expected)
        self.assertEqual(old, untouched)
        self.assertIn('第二世代', restored.save_warning)
        self.assertEqual(codec.encode(codec.decode(current, 5)), current)

    def test_partial_old_pool_current_pool_and_unknown_versions_are_rejected(self):
        codec = SessionCodec()
        old = self.fixture()
        del old['pool']['95']
        with self.assertRaises(ValueError):
            codec.decode(old, 5)
        current = codec.encode(codec.decode(self.fixture(), 5))
        del current['pool']['248']
        with self.assertRaises(ValueError):
            codec.decode(current, 5)
        old = self.fixture()
        old['rules'] = 'unverified-gen2'
        with self.assertRaises(UnknownRulesError):
            codec.decode(old, 5)


if __name__ == '__main__':
    unittest.main()
