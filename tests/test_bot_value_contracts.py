"""Bot purchase and retention values follow actual three-to-one evolution paths."""

import random
import sys
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sim"))
import profiles
from bots import Bot, power
from data import pokedex
from shop import OwnedPiece, SharedPool, build_templates


class BotValueContracts(unittest.TestCase):
    def setUp(self):
        self.templates = build_templates()
        self.pool = SharedPool(self.templates)
        self.initial_pool = dict(self.pool.remaining)
        self.bot = Bot(0, 2, "balanced", self.pool, self.templates)
        self.bot.gold = 30
        self.rng = random.Random(7412)
        # Isolate these policy contracts from the changing set of unit profiles.
        multiplier = patch.object(profiles, "bot_value_mult", return_value=1.0)
        multiplier.start()
        self.addCleanup(multiplier.stop)

    def own(self, sid):
        self.pool.take(sid)
        return OwnedPiece(self.templates[sid], self.templates[sid].tier)

    def stock(self, sid):
        self.pool.take(sid)
        self.bot.shop.slots[0] = sid

    def assert_pool_conserved(self):
        held = Counter(sid for owned in self.bot.all_pieces()
                       for sid in owned.sources)
        held.update(sid for sid in self.bot.shop.slots if sid is not None)
        self.assertEqual({sid: n + held[sid] for sid, n in self.pool.remaining.items()},
                         self.initial_pool)

    def scores_for_copies(self, sid):
        self.bot.target_types = self.templates[sid].types
        scores = []
        for copies in (0, 1, 2):
            # Only counts matter here; transaction tests below also verify pool use.
            self.bot.bench = [OwnedPiece(self.templates[sid], self.templates[sid].tier)
                              for _ in range(copies)]
            scores.append(self.bot._slot_score(sid))
        return scores

    def test_terminal_forms_and_eevee_leaves_have_no_chase_bonus(self):
        for sid in (3, 12, 26, 134, 135, 136):
            with self.subTest(species=sid):
                self.assertIsNone(pokedex().next_evolution(sid))
                scores = self.scores_for_copies(sid)
                self.assertEqual(scores, [scores[0]] * 3)

    def test_trade_forms_have_no_pair_bonus_and_keep_third_copy_penalty(self):
        for sid in (64, 67, 93):
            with self.subTest(species=sid):
                scores = self.scores_for_copies(sid)
                self.assertEqual(scores, [scores[0], scores[0], scores[0] - 800])

    def test_legal_evolutions_keep_pair_and_completion_bonus(self):
        for sid in (1, 25, 133):
            with self.subTest(species=sid):
                scores = self.scores_for_copies(sid)
                self.assertEqual(scores, [scores[0], scores[0] + 600, scores[0] + 900])

    def test_l1_does_not_buy_unrelated_terminal_or_trade_duplicate(self):
        self.bot.ability = 1
        self.bot.board = [self.own(9)]  # Water: no target-type or tier upgrade below.
        self.bot.bench = [self.own(sid) for sid in (12, 64, 135, 136)]
        for slot, sid in enumerate((12, 64, 135, 136)):
            self.pool.take(sid)
            self.bot.shop.slots[slot] = sid
        before_gold = self.bot.gold
        self.assertFalse(self.bot._buy_pass(10, self.rng, 0))
        self.assertEqual(self.bot.gold, before_gold)
        self.assertEqual(self.bot.shop.slots, [12, 64, 135, 136])
        self.assert_pool_conserved()

    def test_l1_buys_unrelated_legal_third_copy_and_combines(self):
        self.bot.ability = 1
        self.bot.board = [self.own(9)]
        self.bot.bench = [self.own(133), self.own(133)]
        self.stock(133)
        self.assertTrue(self.bot._buy_pass(10, self.rng, 0))
        self.assertEqual([o.piece.species_id for o in self.bot.bench], [134])
        self.assertEqual(self.bot.combines, 1)
        self.assertEqual(self.bot.gold, 29)
        self.assert_pool_conserved()

    def test_l1_can_still_buy_terminal_duplicate_for_board_types(self):
        self.bot.ability = 1
        self.bot.board = [self.own(9)]
        self.bot.bench = [self.own(134)]
        self.stock(134)
        self.assertTrue(self.bot._buy_pass(10, self.rng, 0))
        self.assertEqual(self.bot.count_species(134), 2)
        self.assertEqual(self.bot.combines, 0)
        self.assert_pool_conserved()

    def test_sell_pass_does_not_protect_weaker_terminal_duplicates(self):
        self.bot.ability = 1
        self.bot.bench = [self.own(sid) for sid in (12, 12, 3, 9, 59, 130, 131)]
        self.bot._sell_pass(10, self.rng)
        self.assertEqual(self.bot.count_species(12), 1)
        self.assertEqual(self.bot.count_species(3), 1)
        self.assert_pool_conserved()

    def test_sell_pass_protects_legal_pair_even_when_destination_is_out_of_stock(self):
        self.bot.ability = 1
        self.bot.bench = [self.own(sid) for sid in (1, 1, 12, 3, 9, 59, 130)]
        self.pool.remaining[2] = 0  # Other seats may temporarily hold all destinations.
        self.bot._sell_pass(10, self.rng)
        self.assertEqual(self.bot.count_species(1), 2)
        self.assertEqual(self.bot.count_species(12), 0)

    def test_full_bench_replaces_terminal_duplicate_before_stronger_single(self):
        self.bot.ability = 1
        self.bot.board = [self.own(16)]
        self.bot.bench = [self.own(sid) for sid in (12, 12, 3, 9, 59, 130)]
        self.stock(149)
        self.assertTrue(self.bot._buy_pass(10, self.rng, 0))
        self.assertEqual(self.bot.count_species(12), 1)
        self.assertEqual(self.bot.count_species(3), 1)
        self.assertEqual(self.bot.count_species(149), 1)
        self.assert_pool_conserved()

    def test_full_bench_still_protects_legal_pair(self):
        self.bot.ability = 1
        self.bot.board = [self.own(16)]
        self.bot.bench = [self.own(sid) for sid in (1, 1, 12, 3, 9, 59)]
        self.stock(149)
        self.assertTrue(self.bot._buy_pass(10, self.rng, 0))
        self.assertEqual(self.bot.count_species(1), 2)
        self.assertEqual(self.bot.count_species(12), 0)
        self.assertEqual(self.bot.count_species(149), 1)
        self.assert_pool_conserved()

    def test_shop_and_board_include_the_same_profile_value(self):
        owned = self.own(12)
        self.bot.target_types = owned.piece.types
        before = (self.bot._slot_score(12), self.bot._board_score(owned, {}), power(owned))
        with patch.object(profiles, "bot_value_mult", return_value=2.0):
            after = (self.bot._slot_score(12), self.bot._board_score(owned, {}), power(owned))
        self.assertEqual(tuple(new - old for old, new in zip(before, after)),
                         (pokedex().bst(12),) * 3)

    def test_l1_full_bench_buys_profile_upgrade_and_selects_it(self):
        self.bot.ability = 1
        self.bot.board = [self.own(10)]
        self.bot.bench = [self.own(sid) for sid in (3, 9, 59, 130, 131, 149)]
        self.stock(12)
        with patch.object(profiles, "bot_value_mult",
                          side_effect=lambda sid: 2.0 if sid == 12 else 1.0):
            self.assertTrue(self.bot._buy_pass(10, self.rng, 0))
            self.bot._select_board(10, self.rng)
        self.assertEqual(self.bot.count_species(3), 0)
        self.assertIn(12, [o.piece.species_id for o in self.bot.board])
        self.assert_pool_conserved()

    def test_profile_range_controls_actual_back_row_and_disabled_fallback(self):
        from combat import Battle
        for enabled, row in ((True, 3), (False, 2)):
            with self.subTest(enabled=enabled), patch.object(profiles, "PROFILES_ON", enabled):
                self.bot.board = [self.own(26)] + [self.own(19) for _ in range(6)]
                self.bot._arrange()
                battle = Battle(self.bot.battle_comp(), [self.templates[19]], random.Random(7), layout="back")
                hero = next(u for u in battle.units if u.team == 0 and u.piece.species_id == 26)
                self.assertEqual(hero.pos[1], row)
                self.assertEqual(hero.range, 3 if enabled else 1)

    def test_counter_and_equipment_use_the_combat_role(self):
        self.bot.ability = 3
        hero, tank = self.own(26), self.own(143)
        self.bot.board = [self.own(19) for _ in range(5)] + [hero]
        with patch.object(profiles, "PROFILES_ON", True):
            self.bot.counter_vs([tank])
            self.assertIs(self.bot.board[5], hero)
            self.bot.board = [tank, hero]
            self.assertIs(self.bot._item_target("choice_band"), hero)
            self.assertIs(self.bot._item_target("leftovers"), tank)
        with patch.object(profiles, "PROFILES_ON", False):
            self.assertIs(self.bot._item_target("choice_band"), tank)

    def test_ranged_penalty_follows_active_range_exactly_once(self):
        from combat import Unit
        for sid, enabled, expected in ((26, True, 1.5), (26, False, 1.), (9, True, 1.5)):
            with self.subTest(sid=sid, enabled=enabled), patch.object(profiles, "PROFILES_ON", enabled):
                with patch("combat.ranged_interval_mult", return_value=1.):
                    base = Unit(self.templates[sid], 0, (0, 3)).attack_interval
                with patch("combat.ranged_interval_mult", return_value=1.5):
                    adjusted = Unit(self.templates[sid], 0, (0, 3)).attack_interval
                self.assertAlmostEqual(adjusted / base, expected)


if __name__ == "__main__":
    unittest.main()
