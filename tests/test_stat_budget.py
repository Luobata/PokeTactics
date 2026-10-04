"""The opt-in budget is conserved before named tactical and team effects."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sim"))
from combat import Unit
from data import pokedex
from roster import build_roster
import profiles
import stat_budget


class StatBudgetContracts(unittest.TestCase):
    def test_all_84_species_conserve_same_cost_budget_and_bounds(self):
        count = 0
        for tier, pieces in build_roster().items():
            for piece in pieces:
                count += 1
                panel = stat_budget.unit_stats(piece)
                points = panel["points"]
                self.assertEqual(sum(points.values()), stat_budget.BUDGET_BY_TIER[tier])
                self.assertEqual(panel["max_hp"] / 2 + panel["attack"] + panel["defense"]
                                 + panel["sp_attack"] + panel["sp_defense"] + panel["speed"],
                                 panel["budget"])
                average = panel["budget"] / 6
                self.assertTrue(all(average * .6 <= value <= average * 1.6 for value in points.values()))
        self.assertEqual(count, 84)

    def test_total_bst_scaling_has_no_effect_and_speed_consumes_real_budget(self):
        for sid in (3, 6, 9, 26, 65, 143):
            base = pokedex().species[sid]["base"]
            scaled = {key: value * 3 for key, value in base.items()}
            self.assertEqual(stat_budget.normalize(base, 2), stat_budget.normalize(scaled, 2))
        slow = dict.fromkeys(stat_budget.STAT_KEYS, 50)
        fast = {**slow, "speed": 150}
        slow_points, fast_points = (stat_budget.normalize(base, 2) for base in (slow, fast))
        self.assertGreater(fast_points["speed"], slow_points["speed"])
        self.assertLess(fast_points["attack"], slow_points["attack"])
        extreme = stat_budget.normalize({**slow, "hp": 100000}, 1)
        self.assertEqual(extreme["hp"], 80)
        self.assertEqual(sum(extreme.values()), 300)

    def test_profile_hp_and_attack_interval_cannot_bypass_budget(self):
        piece = next(p for p in build_roster()[3] if p.species_id == 6)
        expected = Unit(piece, 0, (2, 2), stat_mode="budget_v1")
        with patch.dict(profiles.PROFILE[6], hp_mult=5, atk_interval_mult=.01):
            actual = Unit(piece, 0, (2, 2), stat_mode="budget_v1")
            legacy = Unit(piece, 0, (2, 2))
        self.assertEqual(actual.max_hp, expected.max_hp)
        self.assertEqual(actual.attack_interval, expected.attack_interval)
        self.assertNotEqual(legacy.max_hp, expected.max_hp)
        self.assertEqual(actual.ult_arch, expected.ult_arch)
        self.assertEqual(actual.range, expected.range)

    def test_invalid_mode_and_budget_fail_explicitly(self):
        piece = build_roster()[1][0]
        with self.assertRaises(ValueError):
            Unit(piece, 0, (2, 2), stat_mode="future")
        with self.assertRaises(ValueError):
            stat_budget.normalize(dict.fromkeys(stat_budget.STAT_KEYS, 0), 1)
        with self.assertRaises(ValueError):
            stat_budget.normalize(dict.fromkeys(stat_budget.STAT_KEYS, 50), 4)


if __name__ == "__main__":
    unittest.main()
