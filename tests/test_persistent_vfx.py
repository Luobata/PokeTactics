"""Lifecycle contracts for persistent arena VFX, backed by simulator events."""
import copy
import random
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'sim'), str(ROOT / 'tools/mockups')]

import arena
import arena_fields
import arena_interactions
import arena_skills
import arena_traits
import status
from combat import Battle, TICK
from decoders import Front, Palettes, Font16
from render_battle_gif import BattleAnimation
from web_battle import WebBattleRenderer


class PersistentVfxContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assets = Front(), Palettes(), Font16()
        cls.templates = arena.build_templates()

    def battle(self, friends=(40, 36, 122), enemies=(9, 68), items=None,
               learning_a=None, learning_b=None):
        def comp(ids):
            result = []
            for sid in ids:
                item = (items or {}).get(sid)
                result.append((copy.copy(self.templates[sid]), item) if item
                              else copy.copy(self.templates[sid]))
            return result
        b = Battle(comp(friends), comp(enemies), random.Random(919),
                   ruleset='arena_v1', stat_mode='budget_v1',
                   positions_a=[(2, 3), (1, 3), (3, 3)][:len(friends)],
                   positions_b=[(2, 2), (1, 2), (3, 2)][:len(enemies)],
                   learned_a=learning_a, learned_b=learning_b)
        for unit in b.units:
            unit.max_hp = unit.hp = 1000
            unit.energy = 0
            unit._st.ctrl_until = 1000.
        b.duration = 0.
        return b

    def animation(self, b):
        return BattleAnimation([], [], 919, *self.assets, battle=b)

    def native_cast(self, b, unit, target, t):
        b.duration, unit.energy = t, 80
        self.assertTrue(arena_skills.cast(b, unit, target, t))

    def water_primary(self, b, source, target, t, damage=10):
        move = {'name': 'persistent-test-surf', 'type': 'WATER', 'power': 30,
                'accuracy': 100}
        index = len(b.events)
        with patch.object(status, 'on_hit'), patch.object(
                b, '_move_damage', return_value=damage):
            actual = b._land_hit(source, target, damage, t, move=move,
                                 primary=True, cast=True)
        self.assertTrue(arena_interactions.after_primary(
            b, source, target, move, actual, t, index))

    def test_badges_rank_real_control_states_and_report_overflow(self):
        b = self.battle(friends=(68, 40), enemies=(128, 31))
        target, source = b.units[1], b.units[2]
        status.apply_team_buff(b, target.team, 'lightscreen', 1.)
        status.apply_team_buff(b, target.team, 'reflect', 1.1)
        status.apply_sword_dance(b, target, 1.2)
        target._st.ctrl_until = 0.
        self.assertTrue(status.apply_flinch(b, target, 1.3))
        self.assertTrue(status.apply_debuff(b, target, 'poison', 1.4, source=source))
        self.assertTrue(arena_fields.apply_root(b, source, target, 1.5))
        anim = self.animation(b)
        renderer = WebBattleRenderer(anim)
        au = renderer.view.units[target.idx]
        flinch = next(e for e in anim.timeline.events if e[1] == 'status'
                      and e[3] == 'flinch' and e[4] == 'apply')
        root = next(e for e in anim.timeline.events if e[1] == 'field_effect'
                    and e[4] == 'root' and e[5] == 'apply')
        during = root[0] + .04
        renderer.view._ensure(during)
        self.assertEqual(renderer._status_badges(au, during),
                         (['flinch', 'root', 'poison', 'lightscreen'], 2))
        renderer.view._ensure(flinch[0] + .05)
        self.assertEqual(renderer._status_badges(au, flinch[0] + .05),
                         (['flinch', 'lightscreen', 'reflect', 'sworddance'], 0))
        # Backward seek restores the short flinch without changing simulation events.
        original = copy.deepcopy(b.events)
        renderer.view._ensure(during)
        self.assertEqual(renderer._status_badges(au, during),
                         (['flinch', 'root', 'poison', 'lightscreen'], 2))
        self.assertEqual(b.events, original)

    def test_persistent_layers_choose_one_protection_one_accent_and_wet(self):
        b = self.battle(items={40: 'ward_bracer'})
        target, shielder, guarder = b.units[:3]
        water, attacker = b.units[3:]
        self.water_primary(b, water, target, 1.)
        self.native_cast(b, shielder, target, 2.)
        b._land_hit(attacker, target, 100, 2.1)
        b._land_hit(attacker, target, 100, 2.2)
        self.native_cast(b, guarder, target, 2.3)
        self.assertTrue(status.apply_debuff(b, target, 'burn', 2.4, source=attacker))
        self.native_cast(b, shielder, target, 2.5)
        target.energy = 80
        b._emit_state(target, 2.6)
        anim = self.animation(b)
        renderer = WebBattleRenderer(anim)
        au = renderer.view.units[target.idx]
        guard = next(e for e in anim.timeline.events if e[1] == 'skill_effect'
                     and e[3] == target.idx and e[5] == 'guard')
        charge = next(e for e in anim.timeline.events if e[1] == 'combo_effect'
                      and e[3] == target.idx and e[5] == 'charge')
        second_shield = next(e for e in reversed(anim.timeline.events)
                             if e[1] == 'skill_effect' and e[2:4] == (shielder.idx, target.idx)
                             and e[5] == 'shield')
        sample = max(guard[0], charge[0], second_shield[0]) + .05
        renderer.view._ensure(sample)
        active = renderer._active_identity_effects(sample, target.idx)
        self.assertLessEqual({'guard', 'ward_charge'}, set(active))
        self.assertGreater(au.shield, 0)
        self.assertIsNotNone(au.wet_source_idx)
        self.assertEqual(renderer._persistent_layers(au, sample),
                         ('shield', 'ward_charge', 'wet'))
        original = copy.deepcopy(b.events)
        renderer.view._ensure(sample)
        self.assertEqual(renderer._persistent_layers(au, sample),
                         ('shield', 'ward_charge', 'wet'))
        self.assertEqual(b.events, original)

    def test_guard_protection_suppresses_thorns_without_hiding_badge(self):
        b = self.battle(friends=(31,), enemies=(68,))
        target, enemy = b.units
        self.native_cast(b, target, enemy, 1.)
        anim = self.animation(b)
        renderer = WebBattleRenderer(anim)
        au = renderer.view.units[target.idx]
        guard = next(e for e in anim.timeline.events if e[1] == 'skill_effect'
                     and e[3] == target.idx and e[5] == 'guard')
        sample = guard[0] + .05
        renderer.view._ensure(sample)
        active = renderer._active_identity_effects(sample, target.idx)
        self.assertIn('thorns', active)
        self.assertIn('guard', active)
        self.assertEqual(renderer._persistent_layers(au, sample), ('guard',))
        badges, overflow = renderer._status_badges(au, sample)
        self.assertIn('thorns', badges)
        self.assertIn('guard', badges)
        self.assertEqual(overflow, 0)

    def test_freeze_body_ends_at_its_real_expire_event(self):
        b = self.battle(friends=(68,), enemies=(128,))
        source, target = b.units
        target._st.ctrl_until = 0.
        self.assertTrue(status.apply_debuff(b, target, 'freeze', 1., source=source))
        status.tick(b, 2.3)
        original = copy.deepcopy(b.events)
        anim = self.animation(b)
        renderer = WebBattleRenderer(anim)
        au = renderer.view.units[target.idx]
        apply_event = next(e for e in anim.timeline.events if e[1] == 'status'
                           and e[3] == 'freeze' and e[4] == 'apply')
        expire = next(e for e in anim.timeline.events if e[1] == 'status'
                      and e[3] == 'freeze' and e[4] == 'expire')
        during = apply_event[0] + .05
        after = expire[0] + .05
        renderer.view._ensure(during)
        self.assertIn('freeze', renderer._status_badges(au, during)[0])
        frozen = renderer._unit_art(au, *renderer.cell_point(target.pos), during)[0]
        refrozen = renderer._unit_art(au, *renderer.cell_point(target.pos), during + .05)[0]
        self.assertEqual(frozen.tobytes(), refrozen.tobytes())
        renderer.view._ensure(after)
        self.assertNotIn('freeze', renderer._status_badges(au, after)[0])
        renderer.view._ensure(during)
        self.assertIn('freeze', renderer._status_badges(au, during)[0])
        self.assertEqual(b.events, original)

    def test_rock_lifecycle_keeps_expiry_on_presentation_clock_and_rewinds(self):
        b = self.battle(friends=(95, 106), enemies=(128, 208),
                        items={208: 'heavy_boots'})
        source, target, avoider = b.units[0], b.units[2], b.units[3]
        first = arena_fields.place_rocks(b, source, target, .5)
        arena_fields.move_unit(b, target, (0, 2), 1.)
        # Leave without triggering, then return to the placed tile for a real entry hit.
        arena_fields.move_unit(b, target, (2, 2), 1.2)
        self.assertEqual(arena_fields.clear_near(b, target, 1.4, limit=3), 3)
        second = arena_fields.place_rocks(b, source, target, 1.6)
        arena_fields.move_unit(b, target, (0, 2), 1.8)
        arena_fields.move_unit(b, avoider, (2, 1), 2.)
        arena_fields.expire(b, 7.7)
        original = copy.deepcopy(b.events)
        anim = self.animation(b)
        renderer = WebBattleRenderer(anim)
        events = [e for e in anim.timeline.events if e[1] == 'field_effect'
                  and e[4] == 'rock_spikes']
        actions = [e[5] for e in events]
        self.assertEqual(actions, ['place', 'enter', 'clear', 'place', 'avoid', 'expire'])
        places = [e for e in events if e[5] == 'place']
        for raw, presented, field in zip(
                [e for e in b.events if e[1] == 'field_effect' and e[5] == 'place'],
                places, (first, second)):
            with self.subTest(field=field['id']):
                renderer.view._ensure(presented[0])
                visible = renderer.view.active_rock_fields[field['id']]
                self.assertEqual(visible['expires_at'],
                                 presented[0] + (raw[6]['expires_at'] - raw[0]))
                self.assertAlmostEqual(visible['expires_at'] - presented[0], 6.)
        clear = next(e for e in events if e[5] == 'clear')
        image = renderer.frame(clear[0] - .01).tobytes()
        renderer.frame(anim.timeline.duration)
        self.assertEqual(renderer.frame(clear[0] - .01).tobytes(), image)
        renderer.view._ensure(-1.)
        self.assertFalse(renderer.view.active_rock_fields)
        self.assertEqual(b.events, original)

    def test_partial_rock_clear_preserves_other_cells_and_deadline(self):
        b = self.battle(friends=(95,), enemies=(128,))
        source, cleaner = b.units
        field = arena_fields.place_rocks(b, source, cleaner, 1.)
        initial_cells = set(field['cells'])
        self.assertEqual(arena_fields.clear_near(b, cleaner, 2., limit=1), 1)
        remaining = set(field['cells'])
        self.assertEqual(len(remaining), 2)
        self.assertEqual(len(initial_cells-remaining), 1)
        arena_fields.expire(b, 7.)
        renderer = WebBattleRenderer(self.animation(b))
        events = [e for e in renderer.anim.timeline.events if e[1] == 'field_effect']
        place = next(e for e in events if e[5] == 'place')
        clear = next(e for e in events if e[5] == 'clear')
        expire = next(e for e in events if e[5] == 'expire')
        renderer.view._ensure(place[0])
        deadline = renderer.view.active_rock_fields[field['id']]['expires_at']
        renderer.view._ensure(clear[0])
        visible = renderer.view.active_rock_fields[field['id']]
        self.assertEqual(set(map(tuple, visible['cells'])), remaining)
        self.assertEqual(visible['expires_at'], deadline)
        renderer.view._ensure(expire[0])
        self.assertNotIn(field['id'], renderer.view.active_rock_fields)
        renderer.view._ensure(clear[0])
        self.assertEqual(set(map(tuple, renderer.view.active_rock_fields[field['id']]['cells'])), remaining)

    def weather_battle(self):
        return self.battle(friends=(9, 26, 3), enemies=(128, 127),
                           items={9: 'damp_rock'},
                           learning_a=['rain_dance', 'rain_dance', None])

    @staticmethod
    def request_weather(b, source, t):
        move = arena_skills.resolve_cast(source.piece)
        index = len(b.events)
        b._land_hit(source, source, 0, t, move=move, cast=True)
        return arena_traits.after_native_cast(b, source, t, index)

    def test_same_weather_request_keeps_original_deadline_and_seek(self):
        b = self.weather_battle()
        first_source = next(u for u in b.units if u.piece.species_id == 9)
        repeat_source = next(u for u in b.units if u.piece.species_id == 26)
        self.assertTrue(self.request_weather(b, first_source, 1.))
        b.flush_tactics(1. + TICK)
        first_deadline = b.arena_weather_until
        self.assertEqual(b.arena_weather_name, 'rain')
        before_repeat = b.arena_weather_until
        self.assertTrue(self.request_weather(b, repeat_source, 2.))
        b.flush_tactics(2. + TICK)
        self.assertEqual(b.arena_weather_until, before_repeat)
        b.flush_tactics(first_deadline + TICK)
        self.assertIsNone(b.arena_weather_name)
        repeat = next(e for e in b.events if e[1] == 'combo_effect'
                      and e[4:5] == ('arena_weather',) and e[5] == 'weather'
                      and e[6].get('reason') == 'same_weather_no_refresh')
        self.assertEqual(repeat[6]['expires_at'], first_deadline)
        original = copy.deepcopy(b.events)
        anim = self.animation(b)
        renderer = WebBattleRenderer(anim)
        presented_repeat = next(e for e in anim.timeline.events
                                if e[1] == 'combo_effect' and e[4:6]
                                == ('arena_weather', 'weather')
                                and e[6].get('reason') == 'same_weather_no_refresh')
        renderer.view._ensure(presented_repeat[0] - .01)
        deadline = renderer.view.weather_until
        renderer.view._ensure(presented_repeat[0])
        self.assertEqual(renderer.view.weather_until, deadline)
        self.assertAlmostEqual(renderer._weather_remaining(presented_repeat[0]),
                               deadline - presented_repeat[0])
        transitions = renderer._weather_changes
        self.assertEqual([name for _, name in transitions], ['rain', None])
        self.assertNotIn(presented_repeat[0], [t for t, _ in transitions])
        moment = presented_repeat[0] + .2
        image = renderer.frame(moment).tobytes()
        renderer.frame(anim.timeline.duration)
        self.assertEqual(renderer.frame(moment).tobytes(), image)
        expire = next(e for e in anim.timeline.events if e[1] == 'combo_effect'
                      and e[4:6] == ('arena_weather', 'expire'))
        renderer.view._ensure(expire[0])
        self.assertIsNone(renderer._weather_remaining(expire[0]))
        self.assertEqual(b.events, original)


if __name__ == '__main__':
    unittest.main()
