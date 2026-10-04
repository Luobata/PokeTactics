"""New roster entries share executable skills and optional profile overrides."""

import copy
import random
import sys
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sim"))
import combat
import experiment_profiles
import profiles
import roster
import skills
import status
from data import ENERGY_MAX, ENERGY_PER_HIT_TAKEN, pokedex
from shop import build_templates, make_piece


class RosterExtensionContracts(unittest.TestCase):
    def setUp(self):
        self.dex = pokedex()
        self.templates = build_templates()
        gate = patch.object(profiles, "PROFILES_ON", True)
        gate.start()
        self.addCleanup(gate.stop)

    def fixture(self, sid, enemies=(143,)):
        return combat.Battle([make_piece(sid, self.templates)],
                             [self.templates[s] for s in enemies], random.Random(7),
                             positions_a=[(1, 2)],
                             positions_b=[(1, 1), (2, 1), (3, 1)][:len(enemies)])

    def test_all_loaded_species_have_a_cast_without_changing_learnsets(self):
        original_species, original_moves = copy.deepcopy(self.dex.species), copy.deepcopy(self.dex.moves)
        for sid in sorted(self.dex.species):
            piece = make_piece(sid, self.templates)
            payload = skills.resolve_cast(piece)
            with self.subTest(species=sid):
                self.assertIsNotNone(payload)
                self.assertGreater(payload["power"], 0)
                if piece.move_id is not None:
                    self.assertIs(payload, self.dex.moves[piece.move_id])
                else:
                    self.assertIsNone(payload["id"])
                    self.assertEqual(payload["type"], "NONE")
        self.assertEqual(self.dex.species, original_species)
        self.assertEqual(self.dex.moves, original_moves)

    def test_no_move_generic_casts_consume_energy_and_execute_their_arch(self):
        for sid in (63, 132):
            with self.subTest(species=sid):
                battle = self.fixture(sid, (143, 143, 143))
                unit, target, *others = battle.units
                self.assertIsNone(unit.piece.move_id)
                self.assertIsNone(self.dex.signature_move(sid))
                unit.energy = ENERGY_MAX
                with patch.object(status, "on_hit"), patch.object(battle.rng, "uniform", return_value=1.0):
                    battle._act(unit, 0.0)
                cast = next(e for e in battle.events if e[1] == "cast")
                self.assertEqual(len(cast), 9)  # Event tuple ABI is unchanged.
                self.assertEqual((unit.casts, unit.energy), (1, 0))
                self.assertEqual(cast[4], skills.resolve_cast(unit.piece)["name"])
                self.assertEqual(target.energy, ENERGY_PER_HIT_TAKEN)
                self.assertEqual([v.energy for v in others], [0, 0])
                if sid == 63:
                    self.assertTrue(all(v.hp < v.max_hp for v in others))
                else:
                    self.assertEqual(target.pos, (1, 0))
                states = {e[2]: (e[3], e[4]) for e in battle.events if e[1] == "unit_state"}
                self.assertEqual(states[unit.idx], (unit.hp, 0))

    def test_generic_neutral_payload_uses_stronger_current_stat_and_matching_defense(self):
        battle = self.fixture(63)
        unit, target = battle.units
        payload = skills.resolve_cast(unit.piece)
        target.defense = target.sp_defense = 50
        with patch.object(battle.rng, "uniform", return_value=1.0):
            unit.attack, unit.sp_attack = 10, 100
            self.assertEqual(battle._move_damage(unit, target, payload), 34)
            target.sp_defense = 100
            self.assertEqual(battle._move_damage(unit, target, payload), 18)
            unit.attack, unit.sp_attack = 100, 10
            self.assertEqual(battle._move_damage(unit, target, payload), 34)

    def test_profiles_off_preserves_no_move_basic_only_and_existing_moves(self):
        with patch.object(profiles, "PROFILES_ON", False):
            for sid in (63, 132):
                battle = self.fixture(sid)
                unit = battle.units[0]
                unit.energy = ENERGY_MAX
                self.assertIsNone(skills.resolve_cast(unit.piece))
                self.assertIsNone(unit.ult_arch)
                battle._act(unit, 0.0)
                self.assertEqual((unit.casts, unit.energy), (0, ENERGY_MAX))
                self.assertFalse(any(e[1] == "cast" for e in battle.events))
            for piece in self.templates.values():
                if piece.move_id is not None:
                    self.assertIs(skills.resolve_cast(piece), self.dex.moves[piece.move_id])

    def test_partial_profiles_keep_neutral_defaults_and_generic_identity(self):
        piece = self.templates[1]
        baseline = combat.Unit(piece, 0, (1, 2))
        with patch.dict(profiles.PROFILE, {1: {"range": 1}, 63: {"hp_mult": 1.2}}):
            adjusted = combat.Unit(piece, 0, (1, 2))
            self.assertEqual(adjusted.range, 1)
            self.assertEqual((adjusted.max_hp, adjusted.attack_interval, adjusted.move_mult),
                             (baseline.max_hp, baseline.attack_interval, baseline.move_mult))
            self.assertEqual(profiles.bot_value_mult(1), 1.0)
            self.assertEqual(skills.skill_of(1)["tier"], "generic")
            self.assertEqual(skills.skill_of(1)["arch"], "charge")
            self.assertEqual(self.fixture(63).units[0].range, self.templates[63].distance)
            profile = profiles.get(1)
            profile["ai"]["kite"] = True
            self.assertFalse(profiles.get(1)["ai"]["kite"])
        with patch.dict(profiles.PROFILE, {1: {"ult": {"arch": "splash", "note": "测试招：说明"}}}):
            unit = combat.Unit(piece, 0, (1, 2))
            self.assertEqual(unit.range, piece.distance)
            self.assertEqual(unit.ult_arch, "splash")
            self.assertEqual(skills.skill_of(1), {"name": "测试招", "arch": "splash", "tier": "signature"})

    def test_overlapping_family_anchors_do_not_change_roster_or_shop_weights(self):
        original = {tier: [p.species_id for p in pieces]
                    for tier, pieces in roster.build_roster().items()}
        self.assertEqual({tier: len(ids) for tier, ids in original.items()}, {1: 34, 2: 32, 3: 18})
        with patch.object(roster, "CURATED_FAMILIES", roster.CURATED_FAMILIES + [2, 26, 134, 1]):
            changed = {tier: [p.species_id for p in pieces]
                       for tier, pieces in roster.build_roster().items()}
            self.assertEqual(changed, original)
            self.assertEqual(sum(len(pieces) for pieces in changed.values()), len(build_templates()))

    def test_new_id_in_selected_family_inherits_generic_combat_contract(self):
        new_species = {**copy.deepcopy(self.dex.species[123]),
                       "id": 212, "name_zh": "测试新物种", "lineage": [212, 123], "level_up": []}
        with patch.dict(self.dex.species, {212: new_species}):
            templates = build_templates()
            self.assertEqual(len(templates), 85)
            piece = templates[212]
            self.assertEqual(skills.skill_of(212)["tier"], "generic")
            battle = combat.Battle([piece], [templates[143]], random.Random(3),
                                   positions_a=[(1, 2)], positions_b=[(1, 1)])
            battle.units[0].energy = ENERGY_MAX
            battle._act(battle.units[0], 0.0)
            self.assertEqual(battle.units[0].casts, 1)

    def test_experiment_coverage_uses_dynamic_pool_and_detects_nonexecuting_species(self):
        summary = experiment_profiles.skill_coverage_check(0, 7)
        self.assertEqual(summary["expected"], len(self.templates))
        self.assertEqual(summary["coverage"], summary["expected"])
        self.assertEqual(summary["cast_coverage"], summary["expected"])
        self.assertEqual(summary["missing_casts"], [])
        tiers = Counter()
        for (tier, _), count in summary["assign"].items():
            tiers[tier] += count
        self.assertEqual(tiers, {"signature": 8, "generic": 76})
        self.assertEqual({arch for (tier, arch) in summary["assign"] if tier == "generic"},
                         set(skills.GENERIC_ARCHS))
        full_dex = [make_piece(sid, self.templates) for sid in sorted(self.dex.species)]
        with patch.object(experiment_profiles, "build_roster", return_value={1: full_dex}):
            extended = experiment_profiles.skill_coverage_check(0, 7)
            self.assertEqual(extended["expected"], len(self.dex.species))
            self.assertEqual(extended["cast_coverage"], len(self.dex.species))
            self.assertEqual(extended["missing_casts"], [])
        with patch.object(experiment_profiles, "build_roster", return_value={1: [self.templates[63]]}):
            summary = experiment_profiles.skill_coverage_check(0, 7)
            self.assertEqual((summary["expected"], summary["coverage"], summary["cast_coverage"]), (1, 1, 1))
            with patch.object(skills, "resolve_cast", return_value=None):
                broken = experiment_profiles.skill_coverage_check(0, 7)
                self.assertEqual(broken["coverage"], 1)
                self.assertEqual(broken["missing_casts"], [63])


if __name__ == "__main__":
    unittest.main()
