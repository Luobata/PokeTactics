"""Contracts for the isolated teaching-machine prototype.

These tests deliberately do not register the machines in the production catalog
or claim that acquisition, saving, and production animation are implemented.
They exercise real Battle scheduling and event packets through PrototypeBattle.
"""
from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "sim"), str(ROOT / "tools/acceptance"), str(ROOT)]

from combat import Battle
from teaching_skill_prototype import (
    BUILDS,
    COUNTER,
    PIECES,
    SEED_BASE,
    TEMPO,
    PrototypeBattle,
    effects,
    prototype_match,
    side_fingerprint,
)


RULESET = "tactics_v5"
STAT_MODE = "budget_v1"


def battle_fixture(attacker_id, defender_id, *, experimental_a=None,
                   experimental_b=None, **kwargs):
    attacker = PIECES[attacker_id]
    defender = PIECES[defender_id]
    options = {
        "positions_a": [(2, 2)],
        "positions_b": [(2, 1)],
        "ruleset": RULESET,
        "stat_mode": STAT_MODE,
    }
    options.update(kwargs)
    return PrototypeBattle([attacker], [defender], random.Random(741),
                           experimental_a=experimental_a,
                           experimental_b=experimental_b, **options)


def prepared_pair(battle, *, attacker_energy=0, target_energy=0,
                  target_energy_modifier=0.0):
    attacker, target = battle.units
    for unit in battle.units:
        unit.hp = unit.max_hp = 10_000
        unit.next_act = 0.1
        unit.target_idx = (target if unit is attacker else attacker).idx
    attacker.energy = attacker_energy
    target.energy = target_energy
    target.synergy_energy = target_energy_modifier
    battle.duration = 0.1
    return attacker, target


def teaching_event(battle, machine):
    matches = [event for event in effects(battle) if event[4] == machine]
    if len(matches) != 1:
        raise AssertionError(f"expected one {machine} event, got {len(matches)}")
    return matches[0]


def result_projection(result):
    return {
        "winner": result["winner"],
        "duration": result["duration"],
        "survivors": result["survivors"],
        "units": [(
            unit.piece.species_id, unit.local_idx, unit.team, tuple(unit.pos),
            unit.hp, unit.energy, unit.next_act, unit.technique_used,
        ) for unit in result["units"]],
    }


class AssignmentContracts(unittest.TestCase):
    def test_eligibility_and_one_native_slot_are_enforced(self):
        valid = dict(ruleset=RULESET, stat_mode=STAT_MODE,
                     positions_a=[(2, 2)], positions_b=[(2, 1)])
        bad_cases = [
            ("counter learner is not eligible",
             dict(experimental_b=[COUNTER]),
             dict(), PIECES[143], PIECES[26]),
            ("tempo learner is not eligible",
             dict(experimental_a=[TEMPO]),
             dict(), PIECES[143], PIECES[26]),
            ("native rest occupies the one slot",
             dict(experimental_b=[COUNTER]),
             dict(learned_b=["rest"]), PIECES[68], PIECES[143]),
            ("assignment list must match deployment",
             dict(experimental_b=[COUNTER, None]),
             dict(), PIECES[68], PIECES[143]),
        ]
        for message, experimental, native, attacker, defender in bad_cases:
            with self.subTest(message):
                with self.assertRaises(ValueError):
                    PrototypeBattle([attacker], [defender], random.Random(1),
                                    **experimental, **native, **valid)

        battle = PrototypeBattle([PIECES[68]], [PIECES[143]], random.Random(1),
                                 experimental_b=[COUNTER], **valid)
        self.assertEqual(battle.prototype_teaching[battle.units[1].idx], COUNTER)
        self.assertEqual(battle.units[1].technique, None)

    def test_off_arm_still_validates_and_switch_must_be_boolean(self):
        options = dict(ruleset=RULESET, stat_mode=STAT_MODE,
                       positions_a=[(2, 2)], positions_b=[(2, 1)])
        for enabled in (False, True, 1, None):
            with self.subTest(enabled=enabled):
                if type(enabled) is not bool:
                    with self.assertRaises(ValueError):
                        PrototypeBattle([PIECES[68]], [PIECES[143]], random.Random(1),
                                        experimental_b=[COUNTER],
                                        effects_enabled=enabled, **options)
                else:
                    battle = PrototypeBattle(
                        [PIECES[68]], [PIECES[143]], random.Random(1),
                        experimental_b=[COUNTER], effects_enabled=enabled, **options)
                    self.assertIs(battle.effects_enabled, enabled)
                    self.assertEqual(battle.units[1].technique, None)


class CounterContracts(unittest.TestCase):
    def counter_battle(self, *, geometry="valid", attacker_id=68, defender_id=143):
        positions = {
            # Team 0 owns rows 2-3 and team 1 owns rows 0-1.
            "valid": ((2, 2), (2, 1)),
            "distance3": ((2, 3), (2, 0)),
        }
        attacker_pos, defender_pos = positions[geometry]
        battle = battle_fixture(
            attacker_id, defender_id, experimental_b=[COUNTER],
            positions_a=[attacker_pos], positions_b=[defender_pos])
        attacker, defender = prepared_pair(battle)
        battle._act(attacker, 0.1)
        return battle, attacker, defender

    def test_adjacent_primary_hit_pushes_once_and_adds_exactly_delay(self):
        battle, attacker, defender = self.counter_battle()
        event = teaching_event(battle, COUNTER)
        native = battle.events[event[5]["cause_index"]]
        self.assertEqual((native[1], native[2], native[3]), ("attack", attacker.idx, defender.idx))
        self.assertEqual((event[2], event[3]), (defender.idx, attacker.idx))
        self.assertTrue(event[5]["pushed"])
        self.assertEqual(event[5]["from_pos"], (2, 2))
        self.assertEqual(event[5]["to_pos"], (2, 3))
        self.assertEqual(event[5]["delay_seconds"], 0.3)
        self.assertAlmostEqual(
            event[5]["next_act_after"] - event[5]["next_act_before"], 0.3)
        self.assertTrue(defender.technique_used)

        # A second real basic hit cannot obtain another use.
        attacker.pos, defender.pos = (2, 2), (2, 1)
        attacker.energy = 0
        battle._strike(attacker, defender, 0.2)
        self.assertEqual(len(effects(battle)), 1)
        self.assertTrue(defender.technique_used)

    def test_counter_has_no_direct_damage_or_energy_return(self):
        battle, attacker, defender = self.counter_battle()
        event = teaching_event(battle, COUNTER)
        native = battle.events[event[5]["cause_index"]]
        post_native_source = next(e for e in battle.events[event[5]["cause_index"] + 1:]
                                  if e[1] == "unit_state" and e[2] == attacker.idx)
        post_native_defender = next(e for e in battle.events[event[5]["cause_index"] + 1:]
                                    if e[1] == "unit_state" and e[2] == defender.idx)
        self.assertEqual((post_native_source[3], post_native_source[4]),
                         (attacker.hp, native[5]))
        self.assertEqual((post_native_defender[3], post_native_defender[4]),
                         (defender.hp, native[6]))
        self.assertEqual(attacker.hp, attacker.max_hp)
        self.assertLess(defender.hp, defender.max_hp)

        after_effect_source = [e for e in battle.events if
                               e[1] == "unit_state" and e[2] == attacker.idx][-1]
        after_effect_defender = [e for e in battle.events if
                                 e[1] == "unit_state" and e[2] == defender.idx][-1]
        self.assertEqual((after_effect_source[3], after_effect_source[4]),
                         (attacker.hp, native[5]))
        self.assertEqual((after_effect_defender[3], after_effect_defender[4]),
                         (defender.hp, native[6]))

    def test_remote_unit_adjacent_at_hit_still_triggers(self):
        # Raichu has effective range 3, but the hit snapshot is one cell away.
        battle, attacker, defender = self.counter_battle(attacker_id=26)
        event = teaching_event(battle, COUNTER)
        self.assertEqual(attacker.range, 3)
        # target_pos is the hit-time snapshot; the later push may increase distance.
        self.assertEqual(abs(event[5]["target_pos"][0] - event[5]["source_pos"][0]) +
                         abs(event[5]["target_pos"][1] - event[5]["source_pos"][1]), 1)
        self.assertEqual(event[2], defender.idx)
        self.assertTrue(defender.technique_used)

    def test_distance_over_one_blocked_edge_and_death_do_not_consume(self):
        battle, attacker, defender = self.counter_battle(geometry="distance3")
        self.assertGreater(abs(attacker.pos[0] - defender.pos[0]) +
                           abs(attacker.pos[1] - defender.pos[1]), 1)
        self.assertEqual(effects(battle), [])
        self.assertFalse(defender.technique_used)
        self.assertGreater(defender.hp, 0)

        blocker = PIECES[76]
        battle = PrototypeBattle(
            [PIECES[68], blocker], [PIECES[143]], random.Random(741),
            positions_a=[(2, 2), (2, 3)], positions_b=[(2, 1)],
            experimental_b=[COUNTER], ruleset=RULESET, stat_mode=STAT_MODE)
        attacker, blocker_unit, defender = battle.units
        for unit in battle.units:
            unit.hp = unit.max_hp = 10_000
            unit.next_act = 0.1
            unit.target_idx = (defender if unit.team == 0 else attacker).idx
        attacker.energy = 0
        battle.duration = 0.1
        battle._act(attacker, 0.1)
        event = teaching_event(battle, COUNTER)
        self.assertFalse(event[5]["pushed"])
        self.assertEqual(event[5]["from_pos"], event[5]["to_pos"])
        self.assertEqual(event[5]["delay_seconds"], 0.3)
        self.assertTrue(defender.technique_used)
        self.assertFalse(any(e[1] == "move" and e[2] == attacker.idx
                             for e in battle.events))

        battle = battle_fixture(68, 143, experimental_b=[COUNTER])
        attacker, defender = prepared_pair(battle)
        defender.hp = 1
        battle._strike(attacker, defender, 0.1)
        self.assertFalse(defender.alive)
        self.assertEqual(effects(battle), [])
        self.assertFalse(defender.technique_used)

    def test_guard_redirect_means_original_target_never_received_primary(self):
        defenders = (143, 76, 9)
        battle = PrototypeBattle(
            [PIECES[s] for s in defenders], [PIECES[130]], random.Random(741),
            positions_a=[(2, 2), (3, 2), (4, 2)], positions_b=[(3, 0)],
            learned_a=[None, "guard", None], learned_b=[None],
            experimental_a=[COUNTER, None, None],
            tactics_a={"guard": {"source": 1, "target": 0}},
            ruleset=RULESET, stat_mode=STAT_MODE)
        protected, guard, bait, attacker = battle.units
        bait.pos = (4, 0)
        for unit in battle.units:
            unit.hp = unit.max_hp = 10_000
            unit.next_act = 100.0
        attacker.target_idx = bait.idx
        attacker.energy = 100
        battle.duration = 0.1
        with patch.object(battle.rng, "randrange", return_value=0):
            battle._strike(attacker, bait, 0.1)

        guard_events = [e for e in battle.events
                        if e[1] == "tactical_effect" and e[4] == "guard"]
        self.assertEqual(len(guard_events), 1)
        final_cast = battle.events[guard_events[0][5]["result_event_index"]]
        self.assertEqual((final_cast[1], final_cast[3]), ("cast", guard.idx))
        self.assertEqual(effects(battle), [])
        self.assertFalse(protected.technique_used)
        self.assertEqual(protected.hp, protected.max_hp)
        self.assertLess(guard.hp, guard.max_hp)


class TempoContracts(unittest.TestCase):
    def tempo_battle(self, *, initial_energy, modifier=0.0,
                     defender_id=143, scenario="valid"):
        battle = battle_fixture(26, defender_id, experimental_a=[TEMPO])
        attacker, target = prepared_pair(
            battle, attacker_energy=100, target_energy=initial_energy,
            target_energy_modifier=modifier)
        if scenario == "dodge":
            target.item_dodge = 1.0
        if scenario == "lethal":
            target.hp = 1
        battle._act(attacker, 0.1)
        return battle, attacker, target

    def test_energy_loss_uses_post_native_hit_energy_and_clamps_to_zero(self):
        # The primary cast grants defender hit energy. These fixtures make that
        # post-native value exactly 0/1/19/20/100 before the teaching resolves.
        cases = (
            (0, 0, -1.0, 0, 0),
            (1, 0, -0.89, 1, 0),
            (19, 10, -0.1, 19, 0),
            (20, 10, 0.0, 20, 0),
            # The engine's ENERGY_MAX is 80: a manually seeded 100 is clamped
            # by the primary hit-gain path before tempo reads current energy.
            (80, 100, 0.0, 20, 60),
        )
        for before, initial, modifier, expected_loss, expected_after in cases:
            with self.subTest(post_native_energy=before):
                battle, attacker, target = self.tempo_battle(
                    initial_energy=initial, modifier=modifier)
                event = teaching_event(battle, TEMPO)
                native = battle.events[event[5]["cause_index"]]
                self.assertEqual((native[1], native[3]), ("cast", target.idx))
                self.assertEqual(native[8], before)
                payload = event[5]
                self.assertEqual(payload["energy_before"], before)
                self.assertEqual(payload["actual_loss"], expected_loss)
                self.assertEqual(payload["energy_after"], expected_after)
                self.assertEqual(target.energy, expected_after)
                self.assertEqual(payload["returned_energy"], 0)
                self.assertEqual(attacker.energy, 0)
                self.assertTrue(attacker.technique_used)

    def test_tempo_is_once_per_battle(self):
        battle, attacker, target = self.tempo_battle(initial_energy=10)
        self.assertEqual(len(effects(battle)), 1)
        attacker.energy = 100
        battle._strike(attacker, target, 0.2)
        self.assertEqual(len(effects(battle)), 1)
        self.assertTrue(attacker.technique_used)

    def test_miss_immunity_and_death_do_not_consume_tempo(self):
        battle, attacker, target = self.tempo_battle(
            initial_energy=10, scenario="dodge")
        self.assertTrue(any(e[1] == "miss" for e in battle.events))
        self.assertEqual(effects(battle), [])
        self.assertFalse(attacker.technique_used)
        self.assertEqual(attacker.energy, 100)

        # Raichu's electric cast is immune against a Ground/Rock defender.
        battle, attacker, target = self.tempo_battle(
            initial_energy=10, defender_id=74)
        cast = next(e for e in battle.events if e[1] == "cast")
        self.assertEqual(cast[6], 0)
        self.assertTrue(target.alive)
        self.assertEqual(effects(battle), [])
        self.assertFalse(attacker.technique_used)

        battle, attacker, target = self.tempo_battle(
            initial_energy=10, scenario="lethal")
        self.assertFalse(target.alive)
        self.assertEqual(effects(battle), [])
        self.assertFalse(attacker.technique_used)

    def test_tempo_waits_for_full_native_chain_packet(self):
        battle = PrototypeBattle(
            [PIECES[26]], [PIECES[143], PIECES[9]], random.Random(741),
            positions_a=[(2, 2)], positions_b=[(2, 1), (2, 0)],
            experimental_a=[TEMPO], ruleset=RULESET, stat_mode=STAT_MODE)
        attacker, target, side = battle.units
        for unit in battle.units:
            unit.hp = unit.max_hp = 10_000
            unit.next_act = 0.1
        attacker.energy = 100
        target.energy = 10  # Primary hit-gain makes current energy 20.
        side.energy = 0
        attacker.target_idx = target.idx
        battle.duration = 0.1
        battle._act(attacker, 0.1)

        event = teaching_event(battle, TEMPO)
        cause = battle.events[event[5]["cause_index"]]
        self.assertEqual((cause[1], cause[3]), ("cast", target.idx))
        marker_index = battle.events.index(event)
        native_between = battle.events[event[5]["cause_index"] + 1:marker_index]
        self.assertTrue(any(e[1] == "skill_effect" and e[5] == "side_hit"
                            for e in native_between))
        self.assertLess(native_between.index(
            next(e for e in native_between if e[1] == "skill_effect" and e[5] == "side_hit")),
            len(native_between) - 1)
        self.assertEqual(event[5]["energy_before"], 20)
        self.assertEqual(event[5]["actual_loss"], 20)
        self.assertEqual(event[5]["cause_event_count"], 1)
        self.assertEqual((battle.events[marker_index + 1][1],
                          battle.events[marker_index + 1][2]),
                         ("unit_state", target.idx))


class IsolationContracts(unittest.TestCase):
    def test_disabled_effects_match_formal_battle_events_and_projection(self):
        options = dict(positions_a=[(2, 2)], positions_b=[(2, 1)],
                       ruleset=RULESET, stat_mode=STAT_MODE)
        prototype = PrototypeBattle(
            [PIECES[68]], [PIECES[143]], random.Random(918),
            experimental_b=[COUNTER], effects_enabled=False, **options)
        formal = Battle([PIECES[68]], [PIECES[143]], random.Random(918), **options)
        proto_result = prototype.run()
        formal_result = formal.run()
        self.assertEqual(prototype.events, formal.events)
        self.assertEqual(result_projection(proto_result),
                         result_projection(formal_result))
        self.assertEqual(prototype.rng.getstate(), formal.rng.getstate())
        self.assertEqual(effects(prototype), [])

    def test_enabled_effect_adds_no_random_draw(self):
        off = battle_fixture(26, 143, experimental_a=[TEMPO], effects_enabled=False)
        on = battle_fixture(26, 143, experimental_a=[TEMPO])
        for battle in (off, on):
            attacker, target = prepared_pair(
                battle, attacker_energy=100, target_energy=10)
            battle._act(attacker, 0.1)
        self.assertEqual(effects(off), [])
        self.assertEqual(len(effects(on)), 1)
        self.assertEqual(on.rng.getstate(), off.rng.getstate())

    def test_natural_full_run_is_replayable_and_rotation_symmetric(self):
        for seed in range(SEED_BASE, SEED_BASE + 3):
            with self.subTest(seed=seed):
                battle, result = prototype_match(0, BUILDS[2], seed, "on")
                replay, replay_result = prototype_match(0, BUILDS[2], seed, "on")
                swapped, reverse = prototype_match(
                    0, BUILDS[2], seed, "on", swapped=True)
                self.assertEqual(battle.events, replay.events)
                self.assertEqual(result_projection(result),
                                 result_projection(replay_result))
                self.assertEqual(
                    side_fingerprint(battle, 0, True),
                    side_fingerprint(swapped, 1))
                self.assertEqual(
                    side_fingerprint(battle, 1, True),
                    side_fingerprint(swapped, 0))
                expected = (None if result["winner"] is None
                            else 1 - result["winner"])
                self.assertEqual(reverse["winner"], expected)
                self.assertEqual(reverse["duration"], result["duration"])


if __name__ == "__main__":
    unittest.main()
