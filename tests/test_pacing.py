#!/usr/bin/env python3
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sim"))

import economy
import pacing


class PressurePolicyTests(unittest.TestCase):
    def test_exactly_one_pressure_field_is_required(self):
        with self.assertRaisesRegex(ValueError, "exactly one"):
            pacing.PressurePolicy(start_round=20)
        with self.assertRaisesRegex(ValueError, "exactly one"):
            pacing.PressurePolicy(start_round=20, minimum_loss=21, survivor_factor=4)

    def test_fields_reject_bool_and_nonpositive_values(self):
        for bad in ((True, 1), (1, 1), (20, 0), (20, True)):
            with self.assertRaises(ValueError):
                pacing.PressurePolicy(start_round=bad[0], minimum_loss=bad[1])
        with self.assertRaises(ValueError):
            pacing.PressurePolicy(start_round=20, survivor_factor=0)

    def test_floor_preserves_legacy_before_start_and_never_lowers_it(self):
        policy = pacing.PressurePolicy(start_round=20, minimum_loss=21)
        for round_no in range(1, 20):
            for survivors in range(10):
                self.assertEqual(policy.loss_damage(round_no, survivors),
                                 economy.loss_damage(round_no, survivors))
        for survivors in range(10):
            self.assertEqual(policy.loss_damage(20, survivors),
                             max(economy.loss_damage(20, survivors), 21))

    def test_coefficient_uses_loss_base_and_nonnegative_survivors(self):
        policy = pacing.PressurePolicy(start_round=20, survivor_factor=4)
        self.assertEqual(policy.loss_damage(20, 0), economy.LOSS_BASE)
        self.assertEqual(policy.loss_damage(31, 5), 22)
        self.assertEqual(policy.loss_damage(19, 5), economy.loss_damage(19, 5))


class RoutingTests(unittest.TestCase):
    def test_all_legacy_rulesets_keep_exact_legacy_damage(self):
        for ruleset in pacing.LEGACY_RULESETS:
            for round_no in range(1, 32):
                for survivors in range(10):
                    self.assertEqual(pacing.loss_damage(ruleset, round_no, survivors),
                                     economy.loss_damage(round_no, survivors))

    def test_natural_end_ruleset_uses_default_floor_and_not_economy_mutation(self):
        original = economy.loss_damage
        self.assertEqual(pacing.loss_damage("tactics_v4", 20, 0), 21)
        self.assertEqual(pacing.loss_damage("tactics_v4", 20, 6), 21)
        self.assertEqual(pacing.loss_damage("tactics_v4", 20, 7), 23)
        self.assertEqual(pacing.loss_damage("tactics_v4", 19, 0), original(19, 0))
        self.assertIs(economy.loss_damage, original)

    def test_production_policy_is_immutable_and_unknown_rules_rejected(self):
        self.assertIsInstance(pacing.DEFAULT_NATURAL_END_POLICY, pacing.PressurePolicy)
        with self.assertRaises(Exception):
            pacing.DEFAULT_NATURAL_END_POLICY.start_round = 21
        with self.assertRaises(ValueError):
            pacing.loss_damage("tactics_v6", 20, 0)
        with self.assertRaises(ValueError):
            pacing.loss_damage("tactics_v3", 20, 0,
                               policy=pacing.DEFAULT_NATURAL_END_POLICY)

    def test_override_can_disable_pressure_only_on_candidate(self):
        self.assertEqual(pacing.loss_damage("tactics_v4", 20, 0,
                                            policy=pacing.LEGACY_POLICY),
                         economy.loss_damage(20, 0))


class EndingKindTests(unittest.TestCase):
    def test_exactly_one_alive_is_natural_even_at_round_cap(self):
        self.assertEqual(pacing.ending_kind(1, 30, 31), pacing.NATURAL_CHAMPION)
        self.assertEqual(pacing.ending_kind(1, 31, 31), pacing.NATURAL_CHAMPION)

    def test_multiple_alive_at_cap_is_forced_and_zero_alive_is_invalid(self):
        self.assertEqual(pacing.ending_kind(2, 31, 31), pacing.FORCED_RANKING)
        self.assertEqual(pacing.ending_kind(0, 31, 31), pacing.INVALID_ENDING)
        self.assertEqual(pacing.ending_kind(8, 20, 31), pacing.INVALID_ENDING)


if __name__ == "__main__":
    unittest.main()
