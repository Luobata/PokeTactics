"""Player-visible combat rules and symmetric seeded resolution contracts."""
import collections
import random
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sim"))
import combat
import combo
import status
from combat import Battle
from data import ENERGY_MAX, ENERGY_PER_ATTACK, ENERGY_PER_HIT_TAKEN
from roster import build_roster

ROSTER = {p.species_id: p for ps in build_roster().values() for p in ps}


def battle(a=(6,), b=(143,), **kwargs):
    return Battle([ROSTER[s] for s in a], [ROSTER[s] for s in b],
                  random.Random(7), **kwargs)


class CombatContracts(unittest.TestCase):
    def test_explicit_positions_and_validation(self):
        b = battle((6, 65), (143,), positions_a=[(5, 3), (0, 2)], positions_b=[(2, 1)])
        self.assertEqual([u.pos for u in b.units], [(5, 3), (0, 2), (2, 1)])
        for positions in ([], [(0, 1)], [(6, 2)], [(0.5, 2)], [(True, 2)]):
            with self.subTest(positions=positions), self.assertRaises(ValueError):
                battle(positions_a=positions)
        with self.assertRaises(ValueError):
            battle((6, 65), positions_a=[(0, 2), (0, 2)])
        with self.assertRaises(ValueError):
            battle(positions_b=[(0, 2)])

    def test_back_formation_is_a_180_degree_mirror(self):
        b = battle((6, 65, 143), (6, 65, 143), layout="back")
        self.assertEqual([u.pos for u in b.units[3:]],
                         [(5-u.pos[0], 3-u.pos[1]) for u in b.units[:3]])

    def test_cast_really_applies_each_type_status_at_100_percent(self):
        for kind, mtype in (("burn", "FIRE"), ("poison", "POISON"),
                            ("para", "ELECTRIC"), ("freeze", "ICE"), ("sleep", "PSYCHIC")):
            with self.subTest(kind=kind):
                b = battle(positions_a=[(2, 2)], positions_b=[(2, 1)])
                u, target = b.units
                target.hp = target.max_hp = 10000
                u.energy, u.ult_arch = ENERGY_MAX, None
                move = b.dex.moves[u.piece.move_id]
                with patch.dict(move, type=mtype, power=10, accuracy=100), \
                     patch.dict(status.DEBUFFS[kind], chance=1.0):
                    b._strike(u, target, 0.1)
                self.assertEqual(target._st.debuff, kind)
                self.assertEqual(b.status_stats["applied"][kind], 1)
                self.assertEqual(u.energy, 0)

    def test_missed_cast_does_not_apply_status_or_grant_hit_energy(self):
        b = battle(positions_a=[(2, 2)], positions_b=[(2, 1)])
        u, target = b.units
        u.energy = ENERGY_MAX
        move = b.dex.moves[u.piece.move_id]
        with patch.dict(move, accuracy=1), patch.object(b.rng, "randrange", return_value=99):
            b._strike(u, target, 0.1)
        self.assertEqual(target.energy, 0)
        self.assertEqual(target.hp, target.max_hp)
        self.assertIsNone(target._st.debuff)
        self.assertEqual(u.energy, 0)

    def _modified_cast(self, arch):
        b = battle((6,), (143, 143, 143), weather_name="sun",
                   positions_a=[(2, 2)], positions_b=[(2, 1), (3, 1), (1, 1)])
        u, *targets = b.units
        u.energy, u.ult_arch, u.sp_attack = ENERGY_MAX, arch, 100
        u.synergy_dmg, u.synergy_ult_dmg = 0.2, 0.3
        u.item_ult_dmg, u.item_type_dmg = 0.4, {"FIRE": 0.5}
        for n, v in enumerate(targets):
            v.hp = v.max_hp = 10000
            v.sp_defense = 100 if n == 0 else 200
            v.synergy_dr, v.item_dr = 0.1, 0.2
        move = b.dex.moves[u.piece.move_id]
        with patch.dict(move, type="FIRE", power=100, accuracy=100), \
             patch.object(b.rng, "uniform", return_value=1.0), \
             patch.object(status, "STATUS_ON", False):
            b._strike(u, targets[0], 0.1)
        return b

    def test_splash_uses_secondary_defense_and_each_modifier_once(self):
        b = self._modified_cast("splash")
        # Primary: raw 63 -> weather75 -> damage90 -> ult117 -> lens163
        # -> scarf244 -> DR175. Secondary: raw33 * .5=16 ->19->22->28->39->58->41.
        self.assertEqual(next(e[6] for e in b.events if e[1] == "cast"), 175)
        self.assertEqual([e[4] for e in b.events if e[1] == "attack"], [41, 41])
        self.assertEqual([u.energy for u in b.units], [0, ENERGY_PER_HIT_TAKEN, 0, 0])

    def test_volley_and_double_strike_do_not_repeat_primary_modifiers(self):
        for arch, expected in (("volley_shot", [34, 34]), ("double_strike", [75])):
            with self.subTest(arch=arch):
                b = self._modified_cast(arch)
                self.assertEqual([e[4] for e in b.events if e[1] == "attack"], expected)

    def test_lethal_primary_skips_second_strike_and_never_duplicates_death(self):
        b = battle(positions_a=[(2, 2)], positions_b=[(2, 1)])
        u, target = b.units
        u.energy, u.ult_arch, target.hp = ENERGY_MAX, "double_strike", 1
        with patch.dict(b.dex.moves[u.piece.move_id], accuracy=100):
            b._strike(u, target, 0.1)
        b._death_check(target, 0.1)
        self.assertEqual([e for e in b.events if e[1] == "die"], [(0.1, "die", target.idx)])
        self.assertFalse(any(e[1] == "attack" for e in b.events))
        self.assertEqual(target.hp, 0)

    def test_basic_attack_grants_authoritative_energy_with_bonuses(self):
        b = battle(positions_a=[(2, 2)], positions_b=[(2, 1)])
        u, target = b.units
        u.synergy_energy = .5
        target.item_energy = .5
        with patch.object(status, "STATUS_ON", False):
            b._strike(u, target, .1)
        self.assertEqual(u.energy, int(ENERGY_PER_ATTACK * 1.5))
        self.assertEqual(target.energy, int(ENERGY_PER_HIT_TAKEN * 1.5))
        attack = next(e for e in b.events if e[1] == "attack")
        self.assertEqual(attack[5:], (u.energy, target.energy))

    def test_unreachable_charge_falls_back_without_wasted_movement(self):
        b = battle((6,), (143, 143), positions_a=[(0, 2)], positions_b=[(0, 1), (5, 0)])
        u, original, distant = b.units
        u.range, u.energy, u.ult_arch = 1, ENERGY_MAX, "charge"
        with patch.dict(b.dex.moves[u.piece.move_id], accuracy=100):
            b._strike(u, original, .1)
        cast = next(e for e in b.events if e[1] == "cast")
        self.assertEqual(cast[3], original.idx)
        self.assertEqual(u.pos, (0, 2))
        self.assertEqual(distant.hp, distant.max_hp)
        self.assertFalse(any(e[1] == "move" for e in b.events))

    def test_blink_with_no_landing_cell_retains_original_target(self):
        b = battle((65,), (143, 143, 143, 143, 143),
                   positions_a=[(0, 2)], positions_b=[(0, 1), (5, 0), (4, 0), (5, 1), (1, 1)])
        u, original, weakest, *_ = b.units
        weakest.hp = 1
        u.energy = ENERGY_MAX
        with patch.dict(b.dex.moves[u.piece.move_id], accuracy=100):
            b._strike(u, original, .1)
        self.assertEqual(next(e[3] for e in b.events if e[1] == "cast"), original.idx)
        self.assertEqual(weakest.hp, 1)
        self.assertEqual(u.pos, (0, 2))

    def test_both_teams_launch_opening_volley_before_casualties(self):
        b = battle((6,) * 6, (6,) * 6, layout="back")
        for u in b.units:
            u.hp = 1
        b._opening_volley()
        attacks = [e for e in b.events if e[1] == "attack"]
        self.assertEqual(len(attacks), 12)
        self.assertEqual(collections.Counter(b.units[e[2]].team for e in attacks), {0: 6, 1: 6})
        self.assertTrue(all(u.energy == 0 for u in b.units))
        self.assertFalse(any(u.alive for u in b.units))
        deaths = [e[2] for e in b.events if e[1] == "die"]
        self.assertEqual(len(deaths), len(set(deaths)))

    def test_same_seed_and_rotated_side_swap_preserve_each_unit_result(self):
        a = [ROSTER[s] for s in (6, 65, 143, 9, 26, 68)]
        b = [ROSTER[s] for s in (3, 94, 130, 59, 76, 123)]
        for seed in range(12):
            with self.subTest(seed=seed):
                original = Battle(a, b, random.Random(seed)); original.run()
                repeat = Battle(a, b, random.Random(seed)); repeat.run()
                swapped = Battle(b, a, random.Random(seed)); swapped.run()
                self.assertEqual(original.events, repeat.events)
                self.assertEqual(original.duration, swapped.duration)
                self.assertEqual([(u.hp, u.energy, (5-u.pos[0], 3-u.pos[1])) for u in original.units],
                                 [(u.hp, u.energy, u.pos) for u in swapped.units[6:] + swapped.units[:6]])
                winner, other = original.events[-1][2], swapped.events[-1][2]
                self.assertEqual(None if winner is None else 1-winner, other)

    def test_identical_team_sample_has_no_large_side_bias(self):
        for sid in (6, 9):
            wins = collections.Counter(Battle([ROSTER[sid]] * 6, [ROSTER[sid]] * 6,
                                             random.Random(seed)).run()["winner"]
                                       for seed in range(120))
            # Deliberately broad smoke bound; exact side-swap invariance above
            # carries the structural contract. This is not a balance target.
            with self.subTest(species=sid, wins=wins):
                self.assertLessEqual(abs(wins[0] - wins[1]), 36)


if __name__ == "__main__":
    unittest.main()
