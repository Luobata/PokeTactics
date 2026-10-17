"""Hoenn families participate in cultivation, conservation, live rounds and saves."""
import random
import sys
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'sim'), str(ROOT / 'tools/acceptance')]
import arena
import arena_families as families
import demo
import shop
from session_save import SessionCodec


HOENN = {
    252: (252, 253, 254),
    255: (255, 256, 257),
    258: (258, 259, 260),
    270: (270, 271, 272),
    280: (280, 281, 282),
    285: (285, 286, 286),
    304: (304, 305, 306),
    333: (333, 334, 334),
    349: (349, 350, 350),
    359: (359, 359, 359),
    371: (371, 372, 373),
    374: (374, 375, 376),
}


class HoennGameplay(unittest.TestCase):
    def setUp(self):
        self.session = demo.Session(1003, 'arena_v1', arena_pool=families.VERSION)
        self.session.begin_round(1)
        self.codec = SessionCodec()

    def give(self, session, fid, count=1):
        # This fixture never buys random cards; it directly reserves entrances.
        for _ in range(count):
            session.pool.take(fid)
            session.player.bench.append(
                shop.OwnedPiece(session.templates[fid], session.templates[fid].tier))
        session.ensure_unit_ids()

    def assert_conserved(self, session):
        held = Counter()
        for seat in session.seats:
            held.update(card for card in seat.shop.slots if card is not None)
            for owned in seat.all_pieces():
                held.update(owned.sources)
        self.assertEqual(
            {fid: session.pool.remaining[fid] + held[fid] for fid in families.FAMILIES},
            {fid: families.POOL_BY_COST[cost]
             for fid, (cost, _) in families.FAMILIES.items()})

    def assert_save_roundtrip(self, session):
        encoded = self.codec.encode(session)
        restored = self.codec.decode(encoded, 5)
        self.assertEqual(self.codec.encode(restored), encoded)

    def test_all_hoenn_families_reach_both_growth_steps_and_return_to_pool(self):
        for fid, (entrance, middle, final) in HOENN.items():
            with self.subTest(fid=fid):
                session = demo.Session(1003, 'arena_v1', arena_pool=families.VERSION)
                session.begin_round(1)
                self.give(session, fid, 3)
                self.assertEqual(len(session.combine_player()), 1)
                grown = session.player.bench[0]
                self.assertEqual((grown.piece.species_id, grown.piece.star, grown.sources),
                                 (middle, 2, [fid] * 3))
                self.assert_save_roundtrip(session)

                self.give(session, fid, 6)
                session.combine_player()
                finished = session.player.bench[0]
                self.assertEqual((finished.piece.species_id, finished.piece.star, finished.sources),
                                 (final, 3, [fid] * 9))
                self.assertEqual(finished.invested, families.FAMILIES[fid][0] * 9)
                self.assertEqual(finished.piece.tier, session.templates[fid].tier)
                self.assert_conserved(session)
                self.assert_save_roundtrip(session)

                session.player.bench.remove(finished)
                shop.sell_owned(finished, session.pool)
                self.assert_conserved(session)

    def test_incomplete_hoenn_growth_is_atomic(self):
        session = self.session
        self.give(session, 280, 2)
        before = self.codec.encode(session)
        self.assertEqual(session.combine_player(), [])
        self.assertEqual(self.codec.encode(session), before)
        self.assert_conserved(session)

    def test_hoenn_final_forms_survive_live_pvp_pve_rounds_and_saves(self):
        session = self.session
        self.give(session, 252, 9)
        self.give(session, 270, 9)
        session.combine_player()
        session.combine_player()
        self.assertEqual([owned.piece.species_id for owned in session.player.bench],
                         [254, 272])
        session.player.grid[(0, 1)] = session.player.bench.pop(0)
        session.player.grid[(0, 2)] = session.player.bench.pop(0)

        def prepare_only(*args, **kwargs):
            return demo._prepare_battle_frames(*args, **kwargs)[0]

        with patch.object(demo, 'DEFER_RENDER', False),                 patch.object(demo, '_render_battle_frames', side_effect=prepare_only):
            for _ in range(6):
                for reward in list(session.arena_augments_pending):
                    arena.claim_augment(session, reward['id'], reward['options'][0]['id'])
                self.assert_save_roundtrip(session)
                session.end_prep()
                self.assert_conserved(session)
                if session.phase == 'over':
                    break
                session.next_round()
                self.assert_conserved(session)


if __name__ == '__main__':
    unittest.main()
