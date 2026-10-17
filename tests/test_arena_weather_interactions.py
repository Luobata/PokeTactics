"""Real action tests for shared arena weather, finite water priming and Thunder."""
import copy
import random
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'sim'))
import arena
import arena_fields
import arena_interactions as interactions
import arena_skills
import arena_teaching
import arena_traits as traits
import arena_weather as weather
import status
from combat import Battle, TICK
from data import ENERGY_MAX


class ArenaLayeredWeather(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.templates = arena.build_templates()

    def battle(self, friends=(9, 26, 3), enemies=(128, 127), *, learning=None,
               enemy_learning=None, items=None, choices=None, weather_name=None,
               ruleset='arena_v1'):
        def comp(ids):
            entries = []
            for sid in ids:
                piece = copy.copy(self.templates[sid])
                piece.arena_trait_key = (choices or {}).get(sid)
                key = (items or {}).get(sid)
                entries.append((piece, key) if key else piece)
            return entries
        b = Battle(comp(friends), comp(enemies), random.Random(827),
                   ruleset=ruleset, stat_mode='budget_v1', weather_name=weather_name,
                   learned_a=learning, learned_b=enemy_learning,
                   positions_a=[(2, 3), (1, 3), (3, 3)][:len(friends)],
                   positions_b=[(2, 2), (3, 2), (1, 2)][:len(enemies)])
        for unit in b.units:
            unit.max_hp = unit.hp = 1000
            unit.energy = 0
        return b

    @staticmethod
    def unit(b, sid, team=0):
        return next(unit for unit in b.units if unit.piece.species_id == sid and unit.team == team)

    @staticmethod
    def effects(b, key, effect=None):
        return [e for e in b.events if e[1] == 'combo_effect' and e[4] == key
                and (effect is None or e[5] == effect)]

    def cast(self, b, source, target, t, base=100):
        b.duration, source.energy = t, ENERGY_MAX
        with patch.object(status, 'on_hit'), patch.object(b, '_move_damage',
                side_effect=lambda a, p, move, fraction=1.: int(base * fraction)):
            return arena_skills.cast(b, source, target, t)

    def primary(self, b, source, target, kind, t, damage=10, name='test_primary'):
        b.duration = t
        move = {'name': name, 'type': kind, 'power': 30}
        index = len(b.events)
        with patch.object(status, 'on_hit'):
            actual = b._land_hit(source, target, damage, t, move=move, primary=True, cast=True)
        result = interactions.after_primary(b, source, target, move, actual, t, index)
        return result, actual

    def request(self, b, source, t):
        # The native hook authenticates the cast packet, never a plain call to
        # the weather request API or a teaching cast masquerading as native.
        move = arena_skills.resolve_cast(source.piece)
        index = len(b.events)
        b._land_hit(source, source, 0, t, move=move, cast=True)
        return traits.after_native_cast(b, source, t, index)

    def test_choice_api_normalizes_defaults_and_rejects_cross_species(self):
        self.assertIsNone(traits.validate_choice(34, 'trait_poison_point'))
        self.assertIsNone(traits.validate_choice(127, None))
        self.assertIsNone(traits.validate_choice(150, None))
        self.assertEqual(traits.validate_choice(34, 'trait_sheer_force'), 'trait_sheer_force')
        self.assertEqual(traits.for_species(9, 'trait_rain_dish')['id'], 'trait_rain_dish')
        self.assertEqual(len(traits.options_for(34)), 2)
        self.assertEqual(len(traits.options_for(3)), 1)
        self.assertEqual(len(traits.options_for(127)), 1)
        self.assertEqual(len(traits.options_for(150)), 1)
        self.assertEqual(traits.options_for(16), [])
        for sid, key in ((34, 'trait_rain_dish'), (9, 'trait_sheer_force'),
                         (127, 'trait_static'), (150, 'trait_static'), (34, True), (True, None)):
            with self.subTest(sid=sid, key=key), self.assertRaises(ValueError):
                traits.validate_choice(sid, key)
        rows = traits.options_for(9)
        rows[0]['tags'].clear()
        self.assertTrue(traits.options_for(9)[0]['tags'])
        with self.assertRaises(ValueError):
            self.battle((34,), (128,), choices={34: 'trait_rain_dish'})

    def test_real_native_weather_is_once_next_tick_and_does_not_boost_itself(self):
        b = self.battle(learning=['rain_dance', None, None])
        source, target = self.unit(b, 9), self.unit(b, 128, 1)
        self.cast(b, source, target, 1.)
        self.assertTrue(source.technique_used)
        self.assertIsNone(weather.active(b, 1.))
        self.assertEqual(target.wet_until, 5.)  # This water cast still saw no rain.
        requests = self.effects(b, 'arena_weather', 'weather_request')
        self.assertEqual(len(requests), 1)
        b.flush_tactics(1.)
        self.assertIsNone(weather.active(b, 1.))
        b.flush_tactics(1. + TICK)
        self.assertEqual(weather.active(b, 1.1), 'rain')
        self.assertAlmostEqual(b.arena_weather_until, 13.1)
        self.cast(b, source, target, 2.)
        self.assertEqual(len(self.effects(b, 'arena_weather', 'weather_request')), 1)
        self.assertEqual(target.wet_until, 8.)
        b.flush_tactics(13.1)
        self.assertIsNone(weather.active(b, 13.1))
        self.assertIsNone(b.arena_weather_name)
        self.assertEqual(b.arena_weather_until, 0.)

    def test_same_tick_rain_and_sun_cancel_even_with_extension(self):
        b = self.battle(learning=['rain_dance', None, 'sunny_day'], items={9: 'damp_rock'})
        self.request(b, self.unit(b, 9), 1.)
        self.request(b, self.unit(b, 3), 1.)
        b.flush_tactics(1.1)
        self.assertIsNone(weather.active(b, 1.1))
        event = self.effects(b, 'arena_weather', 'weather')[-1]
        self.assertEqual(event[6]['reason'], 'simultaneous_rain_sun')
        self.assertEqual({row['duration'] for row in event[6]['requests']}, {12., 16.})
        self.assertTrue(self.unit(b, 9).technique_used)
        self.assertTrue(self.unit(b, 3).technique_used)
        b.flush_tactics(20.)
        self.assertIsNone(weather.active(b, 20.))

    def test_cross_team_weather_competes_and_both_teams_get_the_same_multipliers(self):
        b = self.battle((9,), (3,), learning=['rain_dance'], enemy_learning=['sunny_day'])
        own, enemy = self.unit(b, 9), self.unit(b, 3, 1)
        self.request(b, own, 1.)
        b.flush_tactics(1.1)
        for source in b.units:
            self.assertEqual(weather.damage_multiplier(b, {'type': 'WATER'}, 1.1), 1.15)
            self.assertEqual(weather.damage_multiplier(b, {'type': 'FIRE'}, 1.1), .9)
        self.request(b, enemy, 2.)
        b.flush_tactics(2.1)
        self.assertEqual(weather.active(b, 2.1), 'sun')
        self.assertEqual(weather.damage_multiplier(b, {'type': 'FIRE'}, 2.1), 1.15)
        self.assertEqual(weather.damage_multiplier(b, {'type': 'WATER'}, 2.1), .9)
        b.flush_tactics(14.1)
        self.assertIsNone(weather.active(b, 14.1))

    def test_same_weather_does_not_refresh_and_only_matching_carrier_extends(self):
        b = self.battle((9, 26, 3), learning=['rain_dance', 'rain_dance', 'sunny_day'],
                        items={9: 'damp_rock', 26: 'heat_rock', 3: 'heat_rock'})
        self.request(b, self.unit(b, 9), 1.)
        b.flush_tactics(1.1)
        self.assertAlmostEqual(b.arena_weather_until, 17.1)
        self.request(b, self.unit(b, 26), 2.)
        b.flush_tactics(2.1)
        self.assertAlmostEqual(b.arena_weather_until, 17.1)
        self.assertEqual(self.effects(b, 'arena_weather', 'weather')[-1][6]['reason'],
                         'same_weather_no_refresh')
        self.assertEqual(self.effects(b, 'arena_weather', 'weather_request')[-1][6]['duration'], 12.)
        self.request(b, self.unit(b, 3), 3.)
        b.flush_tactics(3.1)
        self.assertAlmostEqual(b.arena_weather_until, 19.1)
        self.assertEqual(b.arena_weather_name, 'sun')

    def test_only_completed_native_authenticates_weather_and_dead_source_cannot_request(self):
        b = self.battle(learning=['rain_dance', None, None])
        source, target = self.unit(b, 9), self.unit(b, 128, 1)
        index = len(b.events)
        b._land_hit(source, target, 0, 1., move=arena_teaching.MOVES['surf'], cast=True)
        self.assertFalse(traits.after_native_cast(b, source, 1., index))
        source.hp = 0
        self.assertFalse(self.request(b, source, 2.))
        self.assertFalse(source.technique_used)
        self.assertEqual(b._arena_weather_requests, [])

    def test_wet_primary_only_actual_hp_and_live_source_gate(self):
        for reason in ('absorbed', 'immune', 'lethal', 'dead_source'):
            with self.subTest(reason=reason):
                b = self.battle()
                source, target = self.unit(b, 9), self.unit(b, 128, 1)
                damage = 10
                if reason == 'absorbed':
                    target.shield, target.shield_until = 100, 10.
                elif reason == 'immune':
                    damage = 0
                elif reason == 'lethal':
                    target.hp = 1
                else:
                    source.hp = 0
                result, _ = self.primary(b, source, target, 'WATER', 1., damage)
                self.assertFalse(result)
                self.assertIsNone(target.wet_source_idx)
        b = self.battle()
        source, target = self.unit(b, 9), self.unit(b, 128, 1)
        self.cast(b, source, target, 1.)
        marks = self.effects(b, 'element_wet', 'wet')
        self.assertEqual(len(marks), 1)
        self.assertEqual(marks[0][3], target.idx)
        self.assertEqual(target.wet_source_idx, source.idx)
        self.assertIsNone(self.unit(b, 127, 1).wet_source_idx)  # cannon side hit

    def test_surf_aoe_wets_only_original_primary_target(self):
        b = self.battle(learning=['surf', None, None])
        source, target = self.unit(b, 9), self.unit(b, 128, 1)
        with patch.object(status, 'on_hit'), patch.object(b, '_move_damage', return_value=10):
            arena_teaching.after_basic(b, source, target, 1., actual_hp=10)
        self.assertEqual(len(self.effects(b, 'element_wet', 'wet')), 1)
        self.assertEqual(target.wet_source_idx, source.idx)
        self.assertIsNone(self.unit(b, 127, 1).wet_source_idx)

    def test_electric_returns_energy_to_water_source_without_recursion_and_shared_cap(self):
        b = self.battle()
        water, electric, target = self.unit(b, 9), self.unit(b, 26), self.unit(b, 128, 1)
        for t in (1., 2., 5., 9., 13.):
            self.primary(b, water, target, 'WATER', t)
            self.primary(b, electric, target, 'ELECTRIC', t + .1)
        events = self.effects(b, 'element_conduct', 'energy')
        self.assertEqual(len(events), 3)
        self.assertEqual(electric.combo_uses[interactions.REACTION_COUNTER], 3)
        self.assertEqual(water.energy, 24)
        self.assertEqual(electric.healing_done, 0)
        self.assertTrue(all(e[2:4] == (electric.idx, water.idx) and e[6]['amount'] == 8
                            and e[6]['consumed_wet'] for e in events))
        self.assertEqual(target.wet_source_idx, water.idx)  # cap failure preserves last mark

    def test_no_gain_dead_or_same_source_or_enemy_consumer_does_not_consume(self):
        for reason in ('full_energy', 'source_dead', 'same_source', 'enemy_source', 'shield'):
            with self.subTest(reason=reason):
                b = self.battle()
                water, electric, target = self.unit(b, 9), self.unit(b, 26), self.unit(b, 128, 1)
                self.primary(b, water, target, 'WATER', 1.)
                damage = 10
                if reason == 'full_energy':
                    water.energy = ENERGY_MAX
                elif reason == 'source_dead':
                    water.hp = 0
                elif reason == 'same_source':
                    electric = water
                elif reason == 'enemy_source':
                    water.team = 1
                else:
                    target.shield, target.shield_until = 100, 10.
                self.primary(b, electric, target, 'ELECTRIC', 1.1, damage)
                self.assertEqual(target.wet_source_idx, water.idx)
                self.assertEqual(self.effects(b, 'element_conduct'), [])
                self.assertEqual(electric.combo_uses.get(interactions.REACTION_COUNTER, 0), 0)

    def test_grass_heals_lowest_nearby_wounded_ally_and_excludes_native_callbacks(self):
        b = self.battle()
        water, grass, target = self.unit(b, 9), self.unit(b, 3), self.unit(b, 128, 1)
        water.hp, grass.hp, self.unit(b, 26).hp = 500, 800, 950
        self.primary(b, water, target, 'WATER', 1.)
        with patch('arena_combinations.after_native') as combos, \
                patch('arena_equipment.after_native_heal') as gear, \
                patch('arena_traits.after_native_heal') as native:
            result, _ = self.primary(b, grass, target, 'GRASS', 1.1)
            self.assertTrue(result)
            combos.assert_not_called(); gear.assert_not_called(); native.assert_not_called()
        self.assertEqual(water.hp, 560)
        self.assertEqual(grass.healing_done, 60)
        self.assertEqual(grass.self_healing, 0)
        self.assertIsNone(target.wet_source_idx)
        bloom = self.effects(b, 'element_bloom', 'heal')[0]
        self.assertEqual(bloom[3], water.idx)
        self.assertEqual(bloom[6]['amount'], 60)
        self.assertEqual(len(self.effects(b, 'element_wet', 'wet')), 1)

    def test_grass_no_injury_range_or_fully_blocked_healing_preserves_wet(self):
        for reason in ('full_health', 'out_of_range', 'sealed'):
            with self.subTest(reason=reason):
                b = self.battle()
                water, grass, target = self.unit(b, 9), self.unit(b, 3), self.unit(b, 128, 1)
                if reason != 'full_health':
                    water.hp = 400
                    if reason == 'out_of_range':
                        water.pos = (0, 5)
                    else:
                        water.healing_blocks.append({'source': target.idx, 'fraction': 1., 'expires_at': 10.})
                self.primary(b, water, target, 'WATER', 1.)
                self.primary(b, grass, target, 'GRASS', 1.1)
                self.assertEqual(target.wet_source_idx, water.idx)
                self.assertEqual(self.effects(b, 'element_bloom'), [])

    def test_wet_refresh_is_single_slot_rain_sun_do_not_erase_and_expiry_is_explicit(self):
        b = self.battle((9, 230, 3), learning=['rain_dance', None, 'sunny_day'])
        water, other, target = self.unit(b, 9), self.unit(b, 230), self.unit(b, 128, 1)
        self.primary(b, water, target, 'WATER', 1.)
        self.primary(b, other, target, 'WATER', 2.)
        self.assertEqual(target.wet_source_idx, other.idx)
        self.assertEqual(target.wet_until, 6.)
        self.request(b, water, 2.); b.flush_tactics(2.1)
        self.primary(b, water, target, 'WATER', 2.2)
        self.assertAlmostEqual(target.wet_until, 8.2)
        self.request(b, self.unit(b, 3), 3.); b.flush_tactics(3.1)
        self.assertAlmostEqual(target.wet_until, 8.2)
        self.primary(b, water, target, 'WATER', 3.2)
        self.assertAlmostEqual(target.wet_until, 7.2)
        interactions.expire(b, 7.2)
        self.assertIsNone(target.wet_source_idx)
        self.assertEqual(target.wet_until, 0.)
        event = self.effects(b, 'element_wet', 'expire')[-1]
        self.assertEqual(event[6]['reason'], 'duration_elapsed')
        state = next(e for e in reversed(b.events) if e[1] == 'unit_state' and e[2] == target.idx)
        self.assertIsNone(state[7]['wet_source_idx'])

    def test_rain_dish_has_two_second_pulses_six_real_heals_and_no_native_products(self):
        b = self.battle(learning=['rain_dance', None, None], choices={9: 'trait_rain_dish'})
        water = self.unit(b, 9)
        self.request(b, water, 1.); b.flush_tactics(1.1)
        with patch('arena_combinations.after_native') as native:
            traits.weather_tick(b, 3.1)  # Full health still advances the pulse grid.
            water.hp = 100
            traits.weather_tick(b, 3.2)
            self.assertEqual(water.hp, 100)
            for t in (5.1, 7.1, 9.1, 11.1, 13.1):
                traits.weather_tick(b, t)
            native.assert_not_called()
        self.assertEqual(water.hp, 220)
        self.assertEqual(water.healing_done, 120)
        self.assertEqual(water.self_healing, 120)
        self.assertEqual(water.combo_uses['trait_rain_dish'], 4)
        # A separate extended window gives enough time to exercise the battle cap.
        longer = self.battle(learning=['rain_dance', None, None], choices={9: 'trait_rain_dish'},
                            items={9: 'damp_rock'})
        wearer = self.unit(longer, 9)
        wearer.hp = 100
        self.request(longer, wearer, 1.); longer.flush_tactics(1.1)
        for t in (3.1, 5.1, 7.1, 9.1, 11.1, 13.1, 15.1):
            traits.weather_tick(longer, t)
        self.assertEqual(wearer.hp, 280)
        self.assertEqual(wearer.combo_uses['trait_rain_dish'], 6)

    def test_weather_speed_affects_actions_but_preserves_move_timing_and_other_weather(self):
        b = self.battle((3, 230, 9), learning=['sunny_day', None, 'rain_dance'])
        grass, dragon = self.unit(b, 3), self.unit(b, 230)
        baseline_grass, baseline_dragon = b._action_interval(grass, 0.), b._action_interval(dragon, 0.)
        self.request(b, grass, 1.); b.flush_tactics(1.1)
        self.assertAlmostEqual(b._action_interval(grass, 1.1), baseline_grass / 1.25)
        self.assertEqual(b._action_interval(dragon, 1.1), baseline_dragon)
        self.request(b, self.unit(b, 9), 2.); b.flush_tactics(2.1)
        self.assertEqual(b._action_interval(grass, 2.1), baseline_grass)
        self.assertAlmostEqual(b._action_interval(dragon, 2.1), baseline_dragon / 1.25)
        b.flush_tactics(14.1)
        self.assertEqual(b._action_interval(dragon, 14.1), baseline_dragon)
        # Moving is scheduled from MOVE_TICK and move_mult rather than action_interval.
        dragon.energy, dragon.next_act, dragon.pos = 0, 0, (0, 5)
        with patch.object(b, '_strike') as strike:
            b._act(dragon, 15.)
            strike.assert_not_called()
        self.assertGreater(dragon.next_act, 15.)

    def test_arena_ignores_legacy_base_weather_and_serializes_dedicated_state(self):
        b = self.battle(weather_name='rain')
        self.assertIsNone(b.weather_name)
        self.assertIsNone(b.base_weather_name)
        self.assertIsNone(b.arena_weather_name)
        self.assertIsNone(b._weather_control)
        source, target = self.unit(b, 9), self.unit(b, 128, 1)
        baseline = b._final_damage(source, target, arena_teaching.MOVES['surf'], 1000)
        b.weather_name = 'rain'  # Even an external legacy write cannot reach arena's multiplier.
        self.assertEqual(b._final_damage(source, target, arena_teaching.MOVES['surf'], 1000), baseline)
        state = next(e for e in b.events if e[1] == 'unit_state' and e[2] == source.idx)
        self.assertEqual(state[7]['arena_trait_key'], 'trait_torrent')
        self.assertIsNone(state[7]['arena_weather'])

    def test_thunder_waits_for_pending_rain_and_rain_bypasses_accuracy_and_dodge(self):
        b = self.battle(learning=['rain_dance', 'thunder', None])
        water, electric, target = self.unit(b, 9), self.unit(b, 26), self.unit(b, 128, 1)
        target.item_dodge = 1.
        arena_teaching.after_basic(b, electric, target, 1., actual_hp=10)
        self.assertFalse(electric.technique_used)
        self.request(b, water, 1.5)
        arena_teaching.after_basic(b, electric, target, 1.5, actual_hp=10)
        self.assertFalse(electric.technique_used)
        b.flush_tactics(1.6)
        with patch.object(b.rng, 'random', side_effect=AssertionError('rain accuracy must not roll')), \
                patch.object(b, '_move_damage', return_value=100), patch.object(status, 'on_hit'):
            arena_teaching.after_basic(b, electric, target, 1.6, actual_hp=10)
        self.assertTrue(electric.technique_used)
        self.assertEqual(target.hp, 900)
        event = self.effects(b, 'arena_weather', 'accuracy')[-1]
        self.assertTrue(event[6]['guaranteed'])
        self.assertEqual(event[6]['reason'], 'rain_thunder_guaranteed')

    def test_thunder_miss_is_zero_cast_finite_and_no_defender_energy_or_status(self):
        b = self.battle(learning=[None, 'thunder', None])
        electric, target = self.unit(b, 26), self.unit(b, 128, 1)
        target.energy = 0
        with patch.object(b.rng, 'random', return_value=.9):
            arena_teaching.after_basic(b, electric, target, 1., actual_hp=10)
        cast = next(e for e in b.events if e[1] == 'cast' and e[4] == 'thunder')
        self.assertEqual(cast[6], 0)
        self.assertEqual(target.hp, 1000)
        self.assertEqual(target.energy, 0)
        self.assertIsNone(target._st.debuff)
        self.assertTrue(electric.technique_used)
        before = list(b.events)
        arena_teaching.after_basic(b, electric, target, 2., actual_hp=10)
        self.assertEqual(b.events, before)
        self.assertTrue(any(e[1] == 'miss' for e in b.events))

    def test_thunder_wait_is_bounded_and_ground_immunity_survives_rain(self):
        b = self.battle(learning=['rain_dance', 'thunder', None])
        electric, target = self.unit(b, 26), self.unit(b, 128, 1)
        with patch.object(b.rng, 'random', return_value=.1), patch.object(status, 'on_hit'):
            arena_teaching.after_basic(b, electric, target, 6., actual_hp=10)
        self.assertTrue(electric.technique_used)
        grounded = self.battle(enemies=(76,), learning=['rain_dance', 'thunder', None])
        water, electric, target = self.unit(grounded, 9), self.unit(grounded, 26), self.unit(grounded, 76, 1)
        self.request(grounded, water, 1.); grounded.flush_tactics(1.1)
        arena_teaching.after_basic(grounded, electric, target, 1.2, actual_hp=10)
        self.assertEqual(target.hp, 1000)
        self.assertEqual(next(e[6] for e in grounded.events if e[1] == 'cast' and e[4] == 'thunder'), 0)
        self.assertTrue(electric.technique_used)

    def test_thunder_requires_effective_basic_when_called_by_engine(self):
        b = self.battle(learning=[None, 'thunder', None])
        electric, target = self.unit(b, 26), self.unit(b, 128, 1)
        target.shield, target.shield_until = 500, 10.
        with patch('combat._damage', return_value=10), patch.object(status, 'on_hit'):
            b._strike(electric, target, 1.)
        self.assertFalse(electric.technique_used)
        self.assertFalse(any(e[1] == 'cast' and e[4] == 'thunder' for e in b.events))


if __name__ == '__main__':
    unittest.main()
