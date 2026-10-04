"""Bounded signature mechanics, immunity and authoritative resource contracts."""
import random
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sim"))
import combat
import profiles
import skills
import status
from combat import Battle
from data import ENERGY_MAX, ENERGY_PER_HIT_TAKEN
from roster import build_roster

ROSTER = {p.species_id: p for ps in build_roster().values() for p in ps}


def fixture(sid, enemies=(143,), friends=(), positions=None):
    battle = Battle([ROSTER[s] for s in (sid, *friends)],
                    [ROSTER[s] for s in enemies], random.Random(7))
    if positions:
        for unit, pos in zip(battle.units, positions):
            unit.pos = pos
    for unit in battle.units:
        unit.max_hp = unit.hp = 10000
    battle.events = [(0., "deploy", u.idx, u.pos) for u in battle.units]
    for unit in battle.units:
        battle._emit_state(unit, 0.)
    return battle


def cast(battle, target=None, accuracy=100, random_status=False):
    unit = battle.units[0]
    unit.energy = ENERGY_MAX
    target = target or next(v for v in battle.units if v.team != unit.team)
    # Fixture isolation: deterministic damage while explicit quake flinch remains on.
    with ExitStack() as stack:
        stack.enter_context(patch.dict(battle.dex.moves[unit.piece.move_id], accuracy=accuracy))
        stack.enter_context(patch.object(battle.rng, "uniform", return_value=1.0))
        if not random_status:
            stack.enter_context(patch.object(status, "on_hit"))
        battle._strike(unit, target, .1)
    return next(e for e in battle.events if e[1] == "cast")


class SignatureSkills(unittest.TestCase):
    def test_all_eight_bind_real_moves_and_profile_gate(self):
        expected = {6: (53, "喷射火焰"), 9: (56, "水炮"), 3: (76, "日光束"),
                    26: (85, "十万伏特"), 65: (94, "精神强念"), 94: (122, "舌舔"),
                    76: (89, "地震"), 143: (63, "破坏光线")}
        self.assertEqual(set(profiles.PROFILE), set(expected))
        for sid, (move_id, name) in expected.items():
            self.assertEqual(ROSTER[sid].move_id, move_id)
            self.assertEqual(skills.skill_of(sid)["name"], name)
            self.assertEqual(skills.skill_of(sid)["tier"], "signature")
        self.assertEqual(fixture(26).units[0].range, 3)
        with patch.object(profiles, "PROFILES_ON", False):
            for sid in expected:
                self.assertIsNone(skills.skill_of(sid))
                self.assertIsNone(fixture(sid).units[0].ult_arch)

    def test_immunity_is_zero_for_electric_ground_ghost_and_nonzero_resists_keep_floor(self):
        for sid, target in ((26, 76), (76, 6), (94, 143)):
            with self.subTest(sid=sid, target=target):
                battle = fixture(sid, (target,), positions=[(2, 2), (2, 1)])
                event = cast(battle, random_status=True)
                self.assertEqual(event[5:7], (0.0, 0))
                self.assertEqual(battle.units[1].hp, 10000)
                self.assertEqual(battle.units[1].energy, 0)
                self.assertEqual(battle.units[0].damage_dealt, 0)
                self.assertEqual(battle.units[0].energy, 0)
                self.assertFalse(any(e[1] == "status" for e in battle.events))
        with patch.object(random.Random, "uniform", return_value=1.0):
            self.assertEqual(combat._damage(random.Random(1), 1, 1, 1, 9999, 1., .25), 1)
            self.assertEqual(combat._damage(random.Random(1), 1, 1, 1, 9999, 1., 0.), 0)

    def test_water_ray_has_one_cell_width_forward_boundary_and_two_side_limit(self):
        battle = fixture(9, (143,) * 6, positions=[
            (0, 2), (2, 2), (1, 2), (3, 2), (4, 2), (2, 1), (0, 1)])
        unit, main, first, second, *_ = battle.units
        self.assertEqual(battle._line_victims(unit, main), [first, second])
        with patch.object(battle.rng, "uniform", return_value=1.0):
            expected = [battle._move_damage(unit, v, battle.dex.moves[unit.piece.move_id], .45)
                        for v in (first, second)]
        cast(battle)
        sides = [e for e in battle.events if e[1] == "attack"]
        self.assertEqual([(e[3], e[4]) for e in sides], list(zip((2, 3), expected)))
        self.assertEqual([v.energy for v in battle.units], [0, 10, 0, 0, 0, 0, 0])
        self.assertFalse(any(e[1] == "move" for e in battle.events))  # Next cell occupied.
        diagonal = fixture(9, (143,) * 4, positions=[
            (1, 3), (2, 2), (3, 1), (3, 2), (0, 3)])
        self.assertEqual([v.idx for v in diagonal._line_victims(*diagonal.units[:2])], [2])

    def test_water_resolves_sides_before_knockback_and_miss_has_no_effect(self):
        battle = fixture(9, (143, 143), positions=[(2, 3), (2, 2), (2, 0)])
        cast(battle)
        kinds = [e[1] for e in battle.events]
        self.assertEqual(battle.units[1].pos, (2, 1))
        self.assertGreater(kinds.index("move"), kinds.index("attack"))
        missed = fixture(9, (143, 143), positions=[(2, 3), (2, 2), (2, 0)])
        with patch.object(missed.rng, "randrange", return_value=99):
            event = cast(missed, accuracy=1)
        self.assertEqual(event[6], 0)
        self.assertFalse(any(e[1] in ("attack", "move") for e in missed.events))

    def test_solar_heals_lowest_fraction_nearby_including_self_and_clamps_overkill(self):
        battle = fixture(3, (76,), friends=(143, 143), positions=[
            (2, 2), (3, 2), (5, 3), (2, 1)])
        unit, nearby, distant, target = battle.units
        unit.hp, nearby.hp, distant.hp, target.hp = 5000, 1000, 1, 20
        cast(battle)
        self.assertEqual(nearby.hp, 1007)
        self.assertEqual(unit.hp, 5000)
        self.assertEqual(distant.hp, 1)
        self.assertIn((.1, "regen", nearby.idx, 7), battle.events)
        self.assertEqual(unit.damage_dealt, 20)
        own = fixture(3, (76,), positions=[(2, 2), (2, 1)])
        own.units[0].hp, own.units[1].hp = 100, 20
        cast(own)
        self.assertEqual(own.units[0].hp, 107)

    def test_solar_full_allies_or_tiny_actual_damage_create_no_heal(self):
        full = fixture(3, (76,), positions=[(2, 2), (2, 1)])
        cast(full)
        self.assertFalse(any(e[1] == "regen" for e in full.events))
        tiny = fixture(3, (76,), positions=[(2, 2), (2, 1)])
        tiny.units[0].hp, tiny.units[1].hp = 20, 1
        tiny.units[1].item_sash = True
        cast(tiny)
        self.assertEqual(tiny.units[1].hp, 1)
        self.assertFalse(any(e[1] == "regen" for e in tiny.events))

    def test_lightning_hops_from_previous_target_with_fractions_and_no_repeat(self):
        battle = fixture(26, (143,) * 4, positions=[
            (0, 3), (0, 2), (2, 2), (4, 2), (5, 0)])
        unit, primary, first, second, far = battle.units
        with patch.object(battle.rng, "uniform", return_value=1.0):
            expected = [battle._move_damage(unit, v, battle.dex.moves[unit.piece.move_id], frac)
                        for v, frac in ((first, .55), (second, .35))]
        cast(battle)
        sides = [e for e in battle.events if e[1] == "attack"]
        self.assertEqual([(e[2], e[3], e[4]) for e in sides],
                         [(unit.idx, v.idx, amount) for v, amount in zip((first, second), expected)])
        self.assertEqual(far.hp, far.max_hp)
        self.assertEqual([v.energy for v in battle.units], [0, 10, 0, 0, 0])
        self.assertFalse(any(e[1] == "status" for e in battle.events))

    def test_ground_target_interrupts_chain_and_dead_primary_can_still_anchor_it(self):
        blocked = fixture(26, (143, 76, 143), positions=[
            (0, 3), (0, 2), (2, 2), (4, 2)])
        cast(blocked)
        sides = [e for e in blocked.events if e[1] == "attack"]
        self.assertEqual([(e[3], e[4]) for e in sides], [(2, 0)])
        self.assertEqual(blocked.units[3].hp, 10000)
        lethal = fixture(26, (143, 143), positions=[(0, 3), (0, 2), (2, 2)])
        lethal.units[1].hp = 1
        cast(lethal)
        self.assertTrue(any(e[1] == "attack" and e[3] == 2 for e in lethal.events))
        self.assertEqual(sum(e[1] == "die" for e in lethal.events), 1)

    def test_energy_drain_uses_actual_post_hit_energy_and_authoritative_states(self):
        for before, stolen in ((0, 10), (5, 15), (70, 20)):
            with self.subTest(before=before):
                battle = fixture(94, (76,), positions=[(2, 2), (2, 1)])
                unit, target = battle.units
                target.energy = before
                cast(battle)
                self.assertEqual(target.energy, min(80, before + ENERGY_PER_HIT_TAKEN) - stolen)
                self.assertEqual(unit.energy, stolen // 2)
                states = {e[2]: e[3:] for e in battle.events if e[1] == "unit_state"}
                self.assertEqual(states[unit.idx], (unit.hp, unit.energy))
                self.assertEqual(states[target.idx], (target.hp, target.energy))
        missed = fixture(94, (76,), positions=[(2, 2), (2, 1)])
        missed.units[1].energy = 50
        with patch.object(missed.rng, "randrange", return_value=99):
            cast(missed, accuracy=1)
        self.assertEqual(missed.units[1].energy, 50)
        self.assertEqual(missed.units[0].energy, 0)

    def test_quake_each_neighbor_has_own_damage_immunity_and_control_gate(self):
        battle = fixture(76, (143, 143, 6, 143), positions=[
            (2, 2), (2, 1), (1, 2), (3, 2), (4, 2)])
        unit, main, neighbor, flying, distant = battle.units
        main._st.ctrl_until = 5.0
        cast(battle)
        self.assertEqual([(e[3], e[4]) for e in battle.events if e[1] == "attack"][-1], (flying.idx, 0))
        self.assertGreater(neighbor.max_hp - neighbor.hp, 0)
        self.assertEqual(flying.hp, 10000)
        self.assertEqual(distant.hp, 10000)
        applies = [e[2] for e in battle.events if e[1:2] == ("status",) and e[4] == "apply"]
        self.assertEqual(applies, [neighbor.idx])
        self.assertTrue(status.stunned(neighbor, .2))
        self.assertFalse(status.stunned(neighbor, .4))
        self.assertEqual([v.energy for v in battle.units], [0, 10, 0, 0, 0])
        self.assertEqual(battle.status_stats["blocked"][("flinch", "dr")], 1)

    def test_quake_immune_primary_does_not_cancel_other_neighbors_and_status_switch_works(self):
        battle = fixture(76, (6, 143), positions=[(2, 2), (2, 1), (1, 2)])
        event = cast(battle)
        self.assertEqual(event[6], 0)
        self.assertLess(battle.units[2].hp, 10000)
        self.assertTrue(status.stunned(battle.units[2], .2))
        disabled = fixture(76, (143,), positions=[(2, 2), (2, 1)])
        with patch.object(status, "STATUS_ON", False):
            cast(disabled)
        self.assertFalse(any(e[1] == "status" for e in disabled.events))

    def test_flinch_helper_is_bounded_dead_safe_and_does_not_consume_rng(self):
        battle = fixture(76)
        target = battle.units[1]
        rng_state = battle.rng.getstate()
        self.assertTrue(status.apply_flinch(battle, target, .1))
        self.assertFalse(status.apply_flinch(battle, target, .1))
        self.assertTrue(status.apply_flinch(battle, target, .2))
        self.assertAlmostEqual(target._st.stun_until, .5)
        self.assertEqual(battle.rng.getstate(), rng_state)
        target.hp = 0
        self.assertFalse(status.apply_flinch(battle, target, .3))

    def test_effective_damage_counts_sash_overkill_and_dead_packets_once(self):
        battle = fixture(6)
        unit, target = battle.units
        target.hp, target.item_sash = 5, True
        battle._land_hit(unit, target, 100, .1)
        self.assertEqual((target.hp, unit.damage_dealt), (1, 4))
        battle._land_hit(unit, target, 100, .2)
        self.assertEqual((target.hp, unit.damage_dealt), (0, 5))
        battle._land_hit(unit, target, 100, .3)
        self.assertEqual(unit.damage_dealt, 5)
        self.assertEqual(sum(e[1] == "die" for e in battle.events), 1)
        self.assertEqual([e[4] for e in battle.events if e[1] == "attack"], [100] * 3)

    def test_new_signature_same_seed_and_rotated_side_swap_are_symmetric(self):
        a = [ROSTER[s] for s in (9, 3, 26, 94, 76, 143)]
        b = [ROSTER[s] for s in (6, 65, 59, 130, 68, 123)]
        for seed in (3, 11, 29):
            with self.subTest(seed=seed):
                first = Battle(a, b, random.Random(seed)); first.run()
                same = Battle(a, b, random.Random(seed)); same.run()
                swap = Battle(b, a, random.Random(seed)); swap.run()
                self.assertEqual(first.events, same.events)
                self.assertEqual(first.duration, swap.duration)
                self.assertEqual([(u.hp, u.energy, (5-u.pos[0], 3-u.pos[1]), u.damage_dealt)
                                  for u in first.units],
                                 [(u.hp, u.energy, u.pos, u.damage_dealt)
                                  for u in swap.units[6:] + swap.units[:6]])

    def test_directed_evidence_has_bounded_causal_packets_and_real_geometry(self):
        from experiment_signatures import make_signature_battle, run_fixture, run_experiment
        for sid in (9, 3, 26, 94, 76):
            battle = run_fixture(make_signature_battle(sid))
            markers = [(i, e) for i, e in enumerate(battle.events) if e[1] == "skill_effect"]
            self.assertTrue(markers, sid)
            for index, marker in markers:
                payload = marker[6]
                parent = battle.events[payload["cast_index"]]
                self.assertEqual(parent[1:3], ("cast", marker[2]))
                self.assertLess(payload["cast_index"], index)
                self.assertGreater(payload["event_count"], 0)
                packet = battle.events[index + 1:index + 1 + payload["event_count"]]
                self.assertEqual(len(packet), payload["event_count"])
                self.assertFalse(any(e[1] in ("skill_effect", "cast") for e in packet))
                self.assertEqual(len(payload["origin_pos"]), 2)
                self.assertEqual(len(payload["target_pos"]), 2)
                if marker[5] == "heal":
                    self.assertEqual(packet[0][1:], ("regen", marker[3], payload["amount"]))
                if marker[5] == "knockback":
                    self.assertEqual(packet[0][1:], ("move", marker[3], payload["destination"]))
        evidence = run_experiment()
        self.assertTrue(all(evidence["checks"].values()))
        self.assertEqual(len(evidence["rows"]), 8 * 3 * 2)
        self.assertFalse(evidence["balance_validated"])


if __name__ == "__main__":
    unittest.main()
