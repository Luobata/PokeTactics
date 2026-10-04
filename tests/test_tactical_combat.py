"""Opt-in guard/contested-weather contracts, including unchanged base replays."""
import hashlib
import json
import random
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sim"))
import combat
import status
import tactics
from combat import Battle
from data import ENERGY_MAX, ENERGY_PER_HIT_TAKEN
from roster import build_roster
from weather_control import WEATHER_WINDOW_SECONDS

ROSTER = {piece.species_id: piece for rows in build_roster().values() for piece in rows}


def fixture(a=(6,), b=(9,), **kwargs):
    result = Battle([ROSTER[s] for s in a], [ROSTER[s] for s in b],
                    random.Random(741), ruleset=tactics.TACTICS_RULESET, **kwargs)
    for unit in result.units:
        unit.hp = unit.max_hp = 10000
    return result


def effects(battle, kind):
    return [event for event in battle.events
            if event[1] == "tactical_effect" and event[4] == kind]


def strike(battle, attacker, target, t=.1, accuracy=100, statuses=False):
    attacker.energy = ENERGY_MAX
    battle.duration = t
    with ExitStack() as stack:
        stack.enter_context(patch.dict(battle.dex.moves[attacker.piece.move_id],
                                       accuracy=accuracy))
        stack.enter_context(patch.object(battle.rng, "uniform", return_value=1.0))
        stack.enter_context(patch.object(battle.rng, "randrange", return_value=0))
        if not statuses:
            stack.enter_context(patch.object(status, "on_hit"))
        battle._strike(attacker, target, t)


def guarded_battle(attacker_id=130, guard_id=9, attacker_teaching=None, rotated=False):
    # The legal charge geometry from D03. The bait has moved to (4,0) during
    # combat; all constructor positions remain within their deployment rows.
    defenders = (143, guard_id, 76)
    defender_positions = [(2, 2), (3, 2), (4, 2)]
    attacker_positions = [(3, 0)]
    chosen = {"guard": {"source": 1, "target": 0}}
    learning = [None, "guard", None]
    if not rotated:
        battle = fixture(defenders, (attacker_id,), positions_a=defender_positions,
                         positions_b=attacker_positions, learned_a=learning,
                         learned_b=[attacker_teaching], tactics_a=chosen)
        protected, guard, bait, attacker = battle.units
        bait.pos = (4, 0)
    else:
        rotate = lambda cells: [(5-x, 3-y) for x, y in cells]
        battle = fixture((attacker_id,), defenders, positions_a=rotate(attacker_positions),
                         positions_b=rotate(defender_positions), learned_b=learning,
                         learned_a=[attacker_teaching], tactics_b=chosen)
        attacker, protected, guard, bait = battle.units
        bait.pos = (1, 3)
    attacker.target_idx = bait.idx
    return battle, attacker, protected, guard, bait


def weather_battle(same=False, base=None):
    battle = fixture((6,), (6 if same else 9,),
                     positions_a=[(2, 2)], positions_b=[(2, 1)],
                     learned_a=["sunny_day"],
                     learned_b=["sunny_day" if same else "rain_dance"],
                     tactics_a={"weather": {"source": 0}},
                     tactics_b={"weather": {"source": 0}}, weather_name=base)
    # Isolate scheduling from the existing splash/knockback native effects.
    for unit in battle.units:
        unit.ult_arch = None
    return battle


class TacticalValidation(unittest.TestCase):
    def test_ruleset_is_explicit_and_invalid_selections_are_rejected(self):
        for value in (None, True, 1, "", "future_v2"):
            with self.subTest(ruleset=value), self.assertRaises(ValueError):
                tactics.validate_ruleset(value)
        self.assertFalse(tactics.enabled(tactics.BASE_RULESET))
        self.assertTrue(tactics.enabled(tactics.TACTICS_RULESET))
        for selection in ([], {"unknown": None}, {"guard": []},
                          {"guard": {"source": 0}},
                          {"guard": {"source": 0, "target": 0}},
                          {"weather": {"source": True}},
                          {"weather": {"source": -1}},
                          {"weather": {"source": 2}},
                          {"weather": {"source": 0, "target": 1}}):
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                tactics.validate_team(selection, 2, tactics.TACTICS_RULESET)
        for teaching in ("guard", "sunny_day", "rain_dance"):
            with self.subTest(teaching=teaching), self.assertRaises(ValueError):
                Battle([ROSTER[6]], [ROSTER[9]], random.Random(1), learned_a=[teaching])
        with self.assertRaises(ValueError):
            Battle([ROSTER[6]], [ROSTER[9]], random.Random(1),
                   tactics_a={"weather": {"source": 0}})

    def test_selection_requires_learning_compatibility_and_deployment_adjacency(self):
        bad = [dict(tactics_a={"weather": {"source": 0}}),
               dict(learned_a=["rain_dance"]),
               dict(learned_a=["guard"], tactics_a={"weather": {"source": 0}})]
        for args in bad:
            with self.subTest(args=args), self.assertRaises(ValueError):
                fixture(**args)
        for learn, positions in (([None, None], [(0, 2), (1, 2)]),
                                 (["guard", None], [(0, 2), (2, 2)])):
            with self.assertRaises(ValueError):
                fixture((143, 6), learned_a=learn, positions_a=positions,
                         tactics_a={"guard": {"source": 0, "target": 1}})

    def test_base_events_and_rng_match_pre_tactics_golden_runs(self):
        cases = [
            ({}, "b6e181d694f89ba108b5aab503e0a9e16ece9831f351490bbc359e392dea76e6",
             "626cd8c7a315202ee449136db81d271b6df2e12e433771d6edf900ee2d4d69cc"),
            ({"learned_a": ["cut", "surf", "rest"], "weather_name": "rain",
              "stat_mode": "budget_v1"},
             "ba39e37bba82c54819f5bf5ad53e7676d6e9919cfe2cebb62b6874a67d86b635",
             "fea1a2c67716dba6416222d58967ea1337c7e3e88a02337fcba85b59d9e988d1"),
        ]
        # Captured from the unmodified combat core before this change. The
        # entire replay and final RNG state protect unrelated legacy systems.
        for kwargs, event_hash, rng_hash in cases:
            for explicit in (False, True):
                with self.subTest(kwargs=kwargs, explicit=explicit):
                    rng = random.Random(741)
                    rules = {"ruleset": tactics.BASE_RULESET} if explicit else {}
                    battle = Battle([ROSTER[s] for s in (6, 9, 65)],
                                    [ROSTER[s] for s in (143, 94, 76)], rng,
                                    layout="back", **kwargs, **rules)
                    battle.run()
                    encoded = json.dumps(battle.events, sort_keys=True,
                                         separators=(",", ":")).encode()
                    self.assertEqual(hashlib.sha256(encoded).hexdigest(), event_hash)
                    self.assertEqual(hashlib.sha256(repr(rng.getstate()).encode()).hexdigest(),
                                     rng_hash)


class GuardContracts(unittest.TestCase):
    def test_real_charge_redirects_once_and_keeps_target_lock_and_normal_range(self):
        for attacker_id in (130, 67):
            battle, attacker, protected, guard, bait = guarded_battle(attacker_id)
            strike(battle, attacker, bait)
            event = effects(battle, "guard")[0]
            cast = battle.events[event[5]["result_event_index"]]
            self.assertEqual((attacker.pos, attacker.target_idx), ((2, 1), protected.idx))
            self.assertEqual((cast[1], cast[3]), ("cast", guard.idx))
            self.assertEqual((event[2], event[3]), (guard.idx, protected.idx))
            self.assertEqual(guard.energy, ENERGY_PER_HIT_TAKEN)
            self.assertEqual(protected.energy, 0)
            self.assertEqual(protected.hp, protected.max_hp)
            self.assertEqual(guard.hp, guard.max_hp - cast[6])
            self.assertEqual(attacker.range, 1)
            self.assertEqual(guard.pos, (3, 2))
            # A later basic cannot inherit the exceptional two-cell reach.
            before = len(battle.events)
            battle._strike(attacker, guard, .2)
            self.assertEqual(len(battle.events), before)
            self.assertIs(battle._target(attacker), protected)
            attacker.pos = (3, 0)
            strike(battle, attacker, bait, .3)
            self.assertEqual(len(effects(battle, "guard")), 1)
            self.assertEqual(protected.energy, ENERGY_PER_HIT_TAKEN)

    def test_blink_and_rotated_charge_keep_the_same_guard_semantics(self):
        for rotated in (False, True):
            battle, attacker, protected, guard, bait = guarded_battle(rotated=rotated)
            strike(battle, attacker, bait)
            event = effects(battle, "guard")[0]
            self.assertEqual(battle.events[event[5]["result_event_index"]][3], guard.idx)
            self.assertEqual(attacker.pos, (3, 2) if rotated else (2, 1))
        battle, attacker, protected, guard, bait = guarded_battle(attacker_id=65)
        protected.hp = 5000  # The blink's existing weakest-target rule.
        strike(battle, attacker, bait)
        self.assertEqual(attacker.pos, (2, 3))
        self.assertEqual(effects(battle, "guard")[0][2], guard.idx)
        self.assertEqual(attacker.target_idx, protected.idx)

    def test_no_interception_on_failed_or_zero_displacement_or_ordinary_basic(self):
        battle, attacker, protected, guard, bait = guarded_battle()
        # Out of the charge's two-step budget; retain the ordinary legal bait.
        protected.pos, guard.pos = (0, 3), (1, 3)
        strike(battle, attacker, bait)
        self.assertEqual(attacker.pos, (3, 0))
        self.assertFalse(effects(battle, "guard"))
        # Blink has no new landing cell around the protected lowest-HP target.
        battle = fixture((143, 9, 76, 143), (65,),
                         learned_a=[None, "guard", None, None],
                         positions_a=[(2, 2), (3, 2), (1, 2), (2, 3)],
                         positions_b=[(2, 1)],
                         tactics_a={"guard": {"source": 1, "target": 0}})
        protected, guard, _, _, attacker = battle.units
        protected.hp = 5000
        strike(battle, attacker, protected)
        self.assertEqual(attacker.pos, (2, 1))
        self.assertEqual(next(e[3] for e in battle.events if e[1] == "cast"), protected.idx)
        self.assertFalse(effects(battle, "guard"))
        attacker.energy = 0
        battle._strike(attacker, protected, .2)
        self.assertEqual([e[3] for e in battle.events if e[1] == "attack"], [protected.idx])
        self.assertFalse(effects(battle, "guard"))
        self.assertFalse(guard.technique_used)

    def test_dead_or_nonadjacent_guard_never_consumes_the_marker(self):
        for mutate in (lambda guard: setattr(guard, "hp", 0),
                       lambda guard: setattr(guard, "pos", (5, 3))):
            battle, attacker, protected, guard, bait = guarded_battle()
            mutate(guard)
            strike(battle, attacker, bait)
            self.assertFalse(effects(battle, "guard"))
            self.assertFalse(guard.technique_used)
            self.assertFalse(battle._guard_used)

    def test_guard_distance_cap_is_separate_from_ranged_attack_range(self):
        battle, attacker, protected, guard, _ = guarded_battle(attacker_id=65)
        attacker.pos = (2, 0)
        self.assertLessEqual(combat._manhattan(attacker.pos, protected.pos), attacker.range)
        final, payload = battle._intercept(attacker, protected, .1, (3, 0))
        self.assertIs(final, protected)
        self.assertIsNone(payload)
        self.assertFalse(battle._guard_used)

    def test_accuracy_miss_or_guard_dodge_consumes_the_one_protection(self):
        for dodge in (False, True):
            battle, attacker, protected, guard, bait = guarded_battle()
            guard.item_dodge = 1.0 if dodge else 0.0
            attacker.energy = ENERGY_MAX
            with patch.dict(battle.dex.moves[attacker.piece.move_id], accuracy=1), \
                    patch.object(battle.rng, "randrange", return_value=99), \
                    patch.object(battle.rng, "random", return_value=0.0):
                battle._strike(attacker, bait, .1)
            event = effects(battle, "guard")[0]
            result = battle.events[event[5]["result_event_index"]]
            self.assertEqual(result[1], "miss" if dodge else "cast")
            self.assertEqual(result[3], guard.idx)
            if dodge:
                self.assertEqual(event[5]["result_event_count"], 0)
            self.assertTrue(guard.technique_used)
            self.assertEqual((guard.hp, protected.hp), (10000, 10000))
            self.assertEqual((guard.energy, protected.energy), (0, 0))

    def test_primary_status_immunity_and_death_belong_to_the_guard(self):
        battle, attacker, protected, guard, bait = guarded_battle()
        with patch.dict(battle.dex.moves[attacker.piece.move_id], type="FIRE"), \
                patch.dict(status.DEBUFFS["burn"], chance=1.0):
            strike(battle, attacker, bait, statuses=True)
        self.assertEqual(guard._st.debuff, "burn")
        self.assertIsNone(protected._st.debuff)
        immune, attacker, protected, guard, bait = guarded_battle(guard_id=94)
        with patch.dict(immune.dex.moves[attacker.piece.move_id], type="NORMAL"):
            strike(immune, attacker, bait)
        self.assertEqual((guard.hp, guard.energy), (10000, 0))
        self.assertTrue(guard.technique_used)
        lethal, attacker, protected, guard, bait = guarded_battle()
        guard.hp = 1
        strike(lethal, attacker, bait)
        self.assertEqual(guard.hp, 0)
        self.assertEqual([e[2] for e in lethal.events if e[1] == "die"], [guard.idx])
        self.assertTrue(protected.alive)

    def test_surf_side_targets_anchor_to_final_guard_without_second_primary_energy(self):
        battle, attacker, protected, guard, bait = guarded_battle(attacker_teaching="surf")
        strike(battle, attacker, bait)
        cast = next(e for e in battle.events if e[1] == "cast")
        side = [e for e in battle.events if e[1] == "attack"]
        self.assertEqual(cast[3], guard.idx)
        self.assertEqual([e[3] for e in side], [protected.idx])
        self.assertEqual(guard.hp, 10000-cast[6])
        self.assertEqual(protected.hp, 10000-side[0][4])
        self.assertEqual((guard.energy, protected.energy), (ENERGY_PER_HIT_TAKEN, 0))
        payload = effects(battle, "guard")[0][5]
        start = payload["result_event_index"] + 1
        end = start + payload["result_event_count"]
        self.assertEqual(end, len(battle.events))
        self.assertIn(side[0], battle.events[start:end])
        self.assertTrue(any(e[1] == "partner_effect" and e[5] == "surf"
                            for e in battle.events[start:end]))
        # A later real basic may share the exact tick, but is outside the cast's
        # closed event packet and must retain its own animation/action slot.
        attacker.energy = 0
        battle._strike(attacker, protected, .1)
        self.assertEqual(payload["result_event_index"] + 1 + payload["result_event_count"], end)
        self.assertTrue(any(e[1] == "attack" for e in battle.events[end:]))

    def test_unselected_guard_does_not_take_over_when_chosen_guard_dies(self):
        battle = fixture((143, 9, 76), (130,),
                         learned_a=[None, "guard", "guard"],
                         positions_a=[(2, 2), (3, 2), (1, 2)], positions_b=[(3, 0)],
                         tactics_a={"guard": {"source": 1, "target": 0}})
        protected, chosen, reserve, attacker = battle.units
        chosen.hp = 0
        target, _ = battle._intercept(attacker, protected, .1, (4, 0))
        self.assertIs(target, protected)
        self.assertFalse(reserve.technique_used)
        self.assertFalse(effects(battle, "guard"))


class WeatherContracts(unittest.TestCase):
    def test_request_is_after_native_cast_and_starts_next_tick(self):
        battle = weather_battle()
        caster, target = battle.units
        with patch.object(battle.rng, "uniform", return_value=1.0):
            expected = battle._move_damage(caster, target,
                                          battle.dex.moves[caster.piece.move_id])
        strike(battle, caster, target)
        request = effects(battle, "weather_request")[0]
        cast = battle.events[request[5]["cast_index"]]
        self.assertEqual((cast[1], cast[6]), ("cast", expected))
        self.assertIsNone(battle.weather_name)
        self.assertEqual(battle.flush_tactics(.1), [])
        battle.flush_tactics(.2)
        event = effects(battle, "weather_start")[0]
        self.assertEqual(battle.weather_name, "sun")
        self.assertEqual((event[0], event[5]["expires_at"]), (.2, .2+WEATHER_WINDOW_SECONDS))
        self.assertEqual(event[5]["requests"][0]["cast_index"], request[5]["cast_index"])
        strike(battle, caster, target, .3)
        self.assertEqual(len(effects(battle, "weather_request")), 1)

    def test_later_opposing_weather_overwrites_then_restores_base_without_stack(self):
        battle = weather_battle(base="sand")
        sun, rain = battle.units
        strike(battle, sun, rain)
        battle.flush_tactics(.2)
        self.assertEqual(battle.weather_name, "sun")
        strike(battle, rain, sun, 2.1)
        self.assertEqual(battle.weather_name, "sun")
        battle.flush_tactics(2.2)
        self.assertEqual(battle.weather_name, "rain")
        last = effects(battle, "weather_start")[-1][5]
        self.assertEqual((last["old_weather"], last["new_weather"], last["reason"]),
                         ("sun", "rain", "overridden"))
        battle.flush_tactics(8.2)
        self.assertEqual(battle.weather_name, "rain")
        battle.flush_tactics(10.2)
        self.assertEqual(battle.weather_name, "sand")
        self.assertEqual(battle.base_weather_name, "sand")
        self.assertEqual(len(effects(battle, "weather_end")), 1)
        self.assertEqual(effects(battle, "weather_end")[0][0], 10.2)

    def test_same_tick_conflict_consumes_both_and_does_not_use_call_order(self):
        for order in ((0, 1), (1, 0)):
            battle = weather_battle(base="hail")
            for index in order:
                strike(battle, battle.units[index], battle.units[1-index])
            battle.flush_tactics(.1)
            self.assertEqual(battle.weather_name, "hail")
            battle.flush_tactics(.2)
            self.assertEqual(battle.weather_name, "hail")
            event = effects(battle, "weather_conflict")[0]
            self.assertEqual({r["weather"] for r in event[5]["requests"]}, {"sun", "rain"})
            self.assertEqual(battle._weather_used, {0, 1})
            self.assertFalse(effects(battle, "weather_start"))
            self.assertIsNone(event[5]["expires_at"])
            for index in order:
                strike(battle, battle.units[index], battle.units[1-index], .3)
            self.assertEqual(len(effects(battle, "weather_request")), 2)

    def test_identical_requests_share_a_window_and_later_one_takes_later_expiry(self):
        for second_at, expiry in ((.1, 8.2), (2.1, 10.2)):
            battle = weather_battle(same=True)
            first, second = battle.units
            strike(battle, first, second)
            strike(battle, second, first, second_at)
            battle.flush_tactics(second_at+.1)
            event = effects(battle, "weather_start")[-1]
            self.assertEqual(battle.weather_name, "sun")
            self.assertEqual(event[5]["expires_at"], expiry)
            self.assertFalse(effects(battle, "weather_conflict"))
            battle.flush_tactics(expiry)
            self.assertIsNone(battle.weather_name)

    def test_dead_source_does_not_cast_or_relay_but_committed_request_survives_death(self):
        battle = fixture((6, 3), (9,), learned_a=["sunny_day", "sunny_day"],
                         tactics_a={"weather": {"source": 0}}, layout="back")
        source, reserve, target = battle.units
        source.hp = 0
        reserve.pos, target.pos = (2, 2), (2, 1)
        strike(battle, source, target)
        strike(battle, reserve, target)
        battle.flush_tactics(.2)
        self.assertFalse(effects(battle, "weather_request"))
        self.assertIsNone(battle.weather_name)
        committed = weather_battle()
        source, target = committed.units
        strike(committed, source, target)
        source.hp = 0
        committed.flush_tactics(.2)
        self.assertEqual(committed.weather_name, "sun")

    def test_missed_native_cast_requests_weather_but_dodge_is_not_a_settled_cast(self):
        battle = weather_battle()
        source, target = battle.units
        source.energy = ENERGY_MAX
        with patch.dict(battle.dex.moves[source.piece.move_id], accuracy=1), \
                patch.object(battle.rng, "randrange", return_value=99):
            battle._strike(source, target, .1)
        self.assertEqual(source.casts, 1)
        self.assertEqual(len(effects(battle, "weather_request")), 1)
        dodged = weather_battle()
        source, target = dodged.units
        target.item_dodge = 1.0
        strike(dodged, source, target)
        self.assertEqual(source.casts, 0)
        self.assertFalse(effects(dodged, "weather_request"))

    def test_weather_multiplier_is_shared_and_never_changes_neutral_basics(self):
        battle = weather_battle(same=True)
        a, b = battle.units
        strike(battle, a, b)
        battle.flush_tactics(.2)
        for attacker, target in ((a, b), (b, a)):
            self.assertEqual(battle._final_damage(attacker, target, {"type": "FIRE"}, 100), 120)
            self.assertEqual(battle._final_damage(attacker, target, {"type": "WATER"}, 100), 80)
            self.assertEqual(battle._final_damage(attacker, target, None, 100), 100)

    def test_run_collects_simultaneous_requests_before_the_next_tick(self):
        battle = weather_battle()
        for unit in battle.units:
            unit.energy, unit.next_act = ENERGY_MAX, .1
        with patch.object(status, "STATUS_ON", False):
            battle.run()
        self.assertEqual(len(effects(battle, "weather_request")), 2)
        conflicts = effects(battle, "weather_conflict")
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0][0], .2)
        self.assertFalse(effects(battle, "weather_start"))

    def test_rotated_side_swap_retains_complete_battle_outcome(self):
        a, b = (143, 6, 26), (130, 9, 65)
        apos, bpos = [(1, 2), (2, 2), (4, 3)], [(4, 1), (3, 1), (1, 0)]
        learning = (["guard", "sunny_day", None], [None, "rain_dance", None])
        chosen = ({"guard": {"source": 0, "target": 1}, "weather": {"source": 1}},
                  {"weather": {"source": 1}})
        for seed in range(12):
            kwargs = dict(ruleset=tactics.TACTICS_RULESET)
            original = Battle([ROSTER[s] for s in a], [ROSTER[s] for s in b], random.Random(seed),
                              positions_a=apos, positions_b=bpos,
                              learned_a=learning[0], learned_b=learning[1],
                              tactics_a=chosen[0], tactics_b=chosen[1], **kwargs)
            swapped = Battle([ROSTER[s] for s in b], [ROSTER[s] for s in a], random.Random(seed),
                             positions_a=[(5-x, 3-y) for x, y in bpos],
                             positions_b=[(5-x, 3-y) for x, y in apos],
                             learned_a=learning[1], learned_b=learning[0],
                             tactics_a=chosen[1], tactics_b=chosen[0], **kwargs)
            original.run()
            swapped.run()
            with self.subTest(seed=seed):
                self.assertEqual(original.duration, swapped.duration)
                self.assertEqual([(u.hp, u.energy, (5-u.pos[0], 3-u.pos[1])) for u in original.units],
                                 [(u.hp, u.energy, u.pos) for u in swapped.units[3:]+swapped.units[:3]])
                self.assertEqual(original.weather_name, swapped.weather_name)


if __name__ == "__main__":
    unittest.main()
