"""Expedition tactical payloads and independently learned combat techniques."""
import random
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sim"))
import build_rules
from combat import Battle
from data import ENERGY_MAX
from experiment_build_diversity import BUILDS, combat_pair, side_fingerprint, variants
import profiles
from roster import build_roster
import skills
import status

PIECES = {p.species_id: p for group in build_roster().values() for p in group}


def battle_of(a, b=(143,), **kwargs):
    return Battle([PIECES[s] for s in a], [PIECES[s] for s in b], random.Random(17), **kwargs)


class LearnedCombat(unittest.TestCase):
    def test_learning_shape_and_species_validated_before_rng_consumption(self):
        for learned in (("rest",), [], ["unknown"], ["surf"], [True]):
            rng = random.Random(4)
            before = rng.getstate()
            with self.subTest(learned=learned), self.assertRaises(ValueError):
                Battle([PIECES[68]], [PIECES[143]], rng, learned_a=learned)
            self.assertEqual(rng.getstate(), before)

    def test_none_learning_is_legacy_identical_and_does_not_require_partner(self):
        a = battle_of((68, 117), learned_a=[None, None], learned_b=[None])
        b = battle_of((68, 117))
        a.run(); b.run()
        self.assertEqual(a.events, b.events)
        own = battle_of((68, 68), learned_a=["cut", "rest"])
        self.assertEqual([u.technique for u in own.units], ["cut", "rest", None])
        self.assertTrue(all(u.partner_id is None for u in own.units))

    def test_explicit_learning_wins_over_old_partner_without_stacking(self):
        battle = battle_of((3, 3), learned_a=["rest", "cut"],
                           team_options=({"partner": 3, "technique": "cut"}, None))
        self.assertEqual([(u.partner_id, u.technique) for u in battle.units[:2]],
                         [(3, "rest"), (None, "cut")])
        fallback = battle_of((3,), learned_a=[None],
                             team_options=({"partner": 3, "technique": "cut"}, None))
        self.assertEqual(fallback.units[0].technique, "cut")
        clean = battle_of((3, 3), learned_a=["rest", "cut"],
                          team_options=({"partner": 3}, None))
        battle.run(); clean.run()
        self.assertEqual(battle.events, clean.events)

    def test_ordinary_cut_is_single_use_with_no_extra_hit_energy(self):
        battle = battle_of((68,), (143, 143), learned_a=["cut"])
        caster, main, side = battle.units
        caster.pos, main.pos, side.pos = (2, 2), (2, 1), (3, 1)
        for unit in battle.units:
            unit.max_hp = unit.hp = 10000
        battle._strike(caster, main, .1)
        self.assertTrue(caster.technique_used)
        self.assertLess(side.hp, side.max_hp)
        self.assertEqual(side.energy, 0)
        first_hp = side.hp
        battle._strike(caster, main, .2)
        self.assertEqual(side.hp, first_hp)
        effects = [e for e in battle.events if e[1] == "partner_effect" and e[5] == "cut"]
        self.assertEqual(len(effects), 1)
        self.assertIsNone(effects[0][4])

    def test_ordinary_surf_preserves_native_cast_and_caps_secondary_hits(self):
        battle = battle_of((117,), (143, 143, 143, 143), learned_a=["surf"])
        caster, *targets = battle.units
        caster.pos = (2, 3)
        for unit, pos in zip(targets, ((2, 2), (1, 2), (3, 2), (2, 1))):
            unit.pos, unit.max_hp, unit.hp = pos, 10000, 10000
        caster.energy = ENERGY_MAX
        with patch.object(battle.rng, "randrange", return_value=0), patch.object(status, "on_hit"):
            battle._strike(caster, targets[0], .1)
        cast = next(e for e in battle.events if e[1] == "cast")
        self.assertEqual(cast[4], skills.resolve_cast(caster.piece)["name"])
        self.assertEqual(len([e for e in battle.events if e[1] == "partner_effect" and e[5] == "surf"]), 2)
        self.assertTrue(all(u.energy == 0 for u in targets[1:]))
        self.assertEqual(len(cast), 9)
        self.assertTrue(all(len(e) == 7 for e in battle.events if e[1] == "attack"))

    def test_ordinary_rest_costs_action_and_emits_authoritative_state(self):
        battle = battle_of((75,), learned_a=["rest"])
        caster = battle.units[0]
        caster.hp, caster.energy = 10, 40
        before = len(battle.events)
        battle._act(caster, .5)
        self.assertEqual(caster.hp, 10 + int(caster.max_hp*.25))
        self.assertEqual(caster.energy, 40)
        self.assertAlmostEqual(caster.next_act, .5 + caster.attack_interval)
        self.assertTrue(caster.technique_used)
        self.assertFalse(any(e[1] in ("attack", "cast") for e in battle.events[before:]))
        self.assertIn((.5, "unit_state", caster.idx, caster.hp, caster.energy), battle.events)


class BudgetTactics(unittest.TestCase):
    def test_lens_trades_damage_for_startup_only_in_budget_mode(self):
        for mode, energy, bonus in (("legacy", 0, .25), ("budget_v1", 40, 0)):
            battle = Battle([(PIECES[6], "focus_lens")], [PIECES[143]],
                            random.Random(0), stat_mode=mode)
            caster = battle.units[0]
            self.assertEqual(caster.energy, energy)
            self.assertEqual(caster.item_ult_dmg, bonus)
            self.assertIn((0., "unit_state", caster.idx, caster.hp, energy), battle.events)
        self.assertIsNone(build_rules.item_description("focus_lens", "legacy"))
        self.assertIn("40", build_rules.item_description("focus_lens", "budget_v1"))
        self.assertIsNone(build_rules.item_description("choice_band", "budget_v1"))

    def test_lens_first_cast_is_two_basic_actions_earlier_at_damage_cost(self):
        counts = []
        damages = []
        for item in (None, "focus_lens"):
            entry = (PIECES[6], item) if item else PIECES[6]
            battle = Battle([entry], [PIECES[143]], random.Random(3), stat_mode="budget_v1")
            caster, target = battle.units
            caster.pos, target.pos = (2, 2), (2, 1)
            target.hp = target.max_hp = 10000
            for turn in range(5):
                battle._strike(caster, target, float(turn))
                if caster.casts:
                    counts.append(turn)
                    damages.append(next(e[6] for e in battle.events if e[1] == "cast"))
                    break
        self.assertEqual(counts, [4, 2])
        # The new lens has no hidden damage bonus or additional base stat budget.
        self.assertLess(abs(damages[0]-damages[1]), 20)

    def test_gengar_override_is_opt_in_and_does_not_mutate_native_data(self):
        piece = PIECES[94]
        native = dict(skills.resolve_cast(piece))
        payload = build_rules.resolve_cast(piece, "budget_v1")
        self.assertEqual(payload["power"], 65)
        self.assertEqual(payload["damage_stat"], "best")
        for key in ("id", "name", "type", "accuracy", "effect"):
            self.assertEqual(payload.get(key), native.get(key))
        self.assertEqual(skills.resolve_cast(piece), native)
        self.assertEqual(build_rules.resolve_cast(piece), native)
        with patch.object(profiles, "PROFILES_ON", False):
            self.assertEqual(build_rules.resolve_cast(piece, "budget_v1"), native)
            self.assertFalse(build_rules.energy_targeting(piece, "budget_v1"))
        self.assertEqual(build_rules.resolve_cast(PIECES[143], "budget_v1"), skills.resolve_cast(PIECES[143]))

    def test_budget_gengar_disrupts_most_charged_in_range_but_normal_is_immune(self):
        for target_sid in (65, 143):
            battle = battle_of((94,), (76, target_sid, 65), stat_mode="budget_v1")
            caster, near, charged, outside = battle.units
            for unit, pos in zip(battle.units, ((2, 3), (2, 2), (3, 2), (5, 0))):
                unit.pos, unit.hp, unit.max_hp = pos, 10000, 10000
            caster.energy, charged.energy, outside.energy = ENERGY_MAX, 60, ENERGY_MAX
            with patch.object(battle.rng, "randrange", return_value=0), patch.object(status, "on_hit"):
                battle._strike(caster, near, .1)
            cast = next(e for e in battle.events if e[1] == "cast")
            self.assertEqual(cast[3], charged.idx)
            self.assertEqual(outside.energy, ENERGY_MAX)
            self.assertEqual(charged.energy, 60 if target_sid == 143 else 51)
            self.assertEqual(caster.energy, 0 if target_sid == 143 else 10)
            self.assertEqual(charged.hp == 10000, target_sid == 143)
            states = {e[2]: e[3:] for e in battle.events if e[1] == "unit_state"}
            self.assertEqual(states[charged.idx], (charged.hp, charged.energy))

    def test_legacy_gengar_retains_original_target(self):
        battle = battle_of((94,), (76, 65))
        caster, near, charged = battle.units
        caster.pos, near.pos, charged.pos = (2, 3), (2, 2), (3, 2)
        caster.energy, charged.energy = ENERGY_MAX, 60
        battle._strike(caster, near, .1)
        self.assertEqual(next(e for e in battle.events if e[1] == "cast")[3], near.idx)

    def test_team_fixtures_have_equal_cost_resources_and_rotate_exactly(self):
        self.assertEqual({b.cost for b in BUILDS}, {15})
        for build in BUILDS:
            self.assertEqual(len(build.species), 6)
            self.assertEqual(sum(item is not None for item in build.items), 3)
            self.assertEqual(sum(t is not None for t in build.learned), 1)
            if "focus_lens" in build.items:
                variant = variants(build)["frontline_lens"]
                front = next(i for i, (_, y) in enumerate(build.positions) if y == 2)
                self.assertEqual(variant.items[front], "focus_lens")
        for a, b in zip(BUILDS, BUILDS[1:]):
            first, result = combat_pair(a, b, 23)
            same, _ = combat_pair(a, b, 23)
            swap, other = combat_pair(a, b, 23, swapped=True)
            self.assertEqual(first.events, same.events)
            self.assertEqual(side_fingerprint(first, 0, True), side_fingerprint(swap, 1))
            self.assertEqual(side_fingerprint(first, 1, True), side_fingerprint(swap, 0))
            self.assertEqual(other["winner"], None if result["winner"] is None else 1-result["winner"])


if __name__ == "__main__":
    unittest.main()
