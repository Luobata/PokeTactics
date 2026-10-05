"""Shared weather and intercepted damage keep their causal presentation order."""
import copy
import json
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT / 'sim', ROOT / 'tools/mockups'):
    sys.path.insert(0, str(directory))
from combat import Battle
from animation_timeline import AnimationTimeline
import render_battle_gif as renderer
from roster import build_roster

PIECES = {p.species_id: p for group in build_roster().values() for p in group}


class TacticalPresentation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assets = renderer.Front(), renderer.Palettes(), renderer.Font16()

    def guard(self, dodge=False, surf=False, extra_attack=False):
        battle = Battle([PIECES[130]], [PIECES[143], PIECES[76], PIECES[143]],
                        random.Random(42), ruleset='tactics_v1',
                        positions_a=[(3, 2)], positions_b=[(2, 1), (3, 1), (4, 0)],
                        learned_a=['surf' if surf else None],
                        learned_b=[None, 'guard', None],
                        tactics_b={'guard': {'source': 1, 'target': 0}})
        for unit, position in zip(battle.units, ((3, 0), (2, 2), (3, 2), (4, 0))):
            unit.pos, unit.hp, unit.max_hp = position, 10000, 10000
        attacker, protected, guardian, locked = battle.units
        attacker.energy, attacker.target_idx = 80, locked.idx
        guardian.item_dodge = 1. if dodge else 0.
        battle.events = [(0., 'deploy', u.idx, u.pos) for u in battle.units]
        for u in battle.units:
            battle._emit_state(u, 0.)
        with patch.object(battle.rng, 'randrange', return_value=0):
            battle._strike(attacker, locked, .1)
            if extra_attack:
                battle._strike(attacker, protected, .1)
        battle.events.append((2., 'end', None))
        return battle

    def weather(self, simultaneous=False):
        battle = Battle([PIECES[6]], [PIECES[9]], random.Random(42),
                        ruleset='tactics_v1', positions_a=[(2, 2)], positions_b=[(2, 1)],
                        learned_a=['sunny_day'], learned_b=['rain_dance'],
                        tactics_a={'weather': {'source': 0}}, tactics_b={'weather': {'source': 0}})
        for u in battle.units:
            u.max_hp = u.hp = 10000
            u.energy = 80
            battle._emit_state(u, 0.)
        a, b = battle.units
        with patch.object(battle.rng, 'randrange', return_value=0):
            battle._strike(a, b, .1)
            if not simultaneous:
                battle.flush_tactics(.2)
            battle._strike(b, a, .1 if simultaneous else 2.1)
        battle.flush_tactics(.2 if simultaneous else 2.2)
        battle.flush_tactics(10.2)
        battle.events.append((10.3, 'end', None))
        return battle

    def animation(self, battle):
        return renderer.BattleAnimation([], [], 42, *self.assets, battle=battle)

    def test_guard_link_and_hp_arrive_with_the_actual_intercepted_cast(self):
        battle = self.guard()
        before = copy.deepcopy(battle.events)
        anim = self.animation(battle)
        event = next(e for e in anim.timeline.events if e[1] == 'tactical_effect' and e[4] == 'guard')
        action = next(a for a in anim.timeline.actions if a.source_index == event[5]['result_event_index'])
        self.assertEqual(event[0], action.impact)
        self.assertEqual(action.target, event[2])
        early = anim.presentation_state(action.impact-.001)
        landed = anim.presentation_state(action.impact)
        self.assertEqual(early[event[2]]['hp'], 10000)
        self.assertLess(landed[event[2]]['hp'], 10000)
        self.assertEqual(landed[event[3]]['hp'], 10000)
        view = anim._presentation_view()
        image = renderer.Image.new('RGBA', (240, 320))
        view._draw_tactical_outcomes(image, action.impact+.1, renderer.ParticleBudget())
        self.assertIsNotNone(image.getbbox())
        self.assertEqual(before, battle.events)
        # Serialized event arrays retain the explicit owner, too.
        serialized = AnimationTimeline(json.loads(json.dumps(before)), battle.units)
        again = next(e for e in serialized.events if e[1] == 'tactical_effect')
        self.assertEqual(again[0], action.impact)

    def test_dodge_still_shows_consumed_guard_without_inventing_damage(self):
        battle = self.guard(dodge=True)
        anim = self.animation(battle)
        event = next(e for e in anim.timeline.events if e[1] == 'tactical_effect')
        miss = next(e for e in anim.timeline.events if e[1] == 'miss')
        self.assertEqual(event[0], miss[0])
        self.assertTrue(all(u.hp == 10000 for u in battle.units))
        self.assertFalse(any(e[1] == 'cast' for e in battle.events))

    def test_guard_surf_is_one_impact_but_later_same_tick_basic_is_independent(self):
        battle = self.guard(surf=True, extra_attack=True)
        anim = self.animation(battle)
        marker = next(e for e in battle.events if e[1] == 'tactical_effect')
        owner = marker[5]['result_event_index']
        end = owner+marker[5]['result_event_count']
        cast = next(a for a in anim.timeline.actions if a.source_index == owner)
        derived = [a for a in anim.timeline.actions if owner < a.source_index <= end]
        independent = [a for a in anim.timeline.actions if a.source_index > end]
        self.assertTrue(derived)
        self.assertTrue(all(a.secondary and a.impact == cast.impact for a in derived))
        self.assertEqual(len(independent), 1)
        self.assertFalse(independent[0].secondary)
        self.assertGreater(independent[0].impact, cast.impact)

    def test_weather_cannot_appear_before_its_cast_or_after_next_weather_damage(self):
        battle = self.weather()
        anim = self.animation(battle)
        transitions = [e for e in anim.timeline.events if e[1] == 'tactical_effect'
                       and e[4] in ('weather_start', 'weather_end')]
        self.assertEqual([e[5]['new_weather'] for e in transitions], ['sun', 'rain', None])
        for request in (e for e in anim.timeline.events if e[1] == 'tactical_effect'
                        and e[4] == 'weather_request'):
            action = next(a for a in anim.timeline.actions if a.source_index == request[5]['cast_index'])
            self.assertEqual(request[0], action.impact)
        self.assertLessEqual(anim.timeline.actions[0].impact, transitions[0][0])
        self.assertGreaterEqual(anim.timeline.actions[1].start, transitions[0][0])
        self.assertLessEqual(anim.timeline.actions[1].impact, transitions[1][0])
        view = anim._presentation_view()
        for event in transitions:
            view._ensure(event[0])
            self.assertEqual(view.weather_name, event[5]['new_weather'])
        for unit in battle.units:
            raw = [e[2:] for e in battle.events if e[1] == 'unit_state' and e[2] == unit.idx]
            presented = [e[2:] for e in anim.timeline.events if e[1] == 'unit_state' and e[2] == unit.idx]
            self.assertEqual(raw, presented)

    def test_weather_rewind_speed_and_skip_preserve_pixels_and_simulation(self):
        battle = self.weather()
        original = copy.deepcopy(battle.events)
        anim = self.animation(battle)
        start = next(e[0] for e in anim.timeline.events if e[1] == 'tactical_effect' and e[4] == 'weather_start')
        moment = start+.2
        reference = anim.playback_frame(moment).tobytes()
        anim.playback_frame(0, skip=True)
        self.assertEqual(anim._presentation_view().weather_name, None)
        self.assertEqual(reference, anim.playback_frame(moment).tobytes())
        self.assertEqual(reference, anim.playback_frame(moment/2, speed=2).tobytes())
        self.assertEqual(anim._presentation_view().weather_name, 'sun')
        self.assertEqual(original, battle.events)

    def test_weather_window_does_not_reveal_future_coverage_or_battle_end(self):
        battle = self.weather()
        full = self.animation(battle)
        index = next(i for i, e in enumerate(battle.events)
                     if e[1] == 'tactical_effect' and e[4] == 'weather_start')
        battle.events = battle.events[:index+1]+[(1., 'end', None)]
        early_end = self.animation(battle)
        for anim in (full, early_end):
            start = next(e for e in anim.timeline.events
                         if e[1] == 'tactical_effect' and e[4] == 'weather_start')
            view = anim._presentation_view(); view._ensure(start[0])
            self.assertAlmostEqual(view.weather_until-start[0], 8.)
            self.assertEqual(view.weather_name, 'sun')
        rain = next(e for e in full.timeline.events if e[1] == 'tactical_effect'
                    and e[4] == 'weather_start' and e[5]['new_weather'] == 'rain')
        view = full._presentation_view(); view._ensure(rain[0]-.001)
        self.assertEqual(view.weather_name, 'sun')
        view._ensure(rain[0]); self.assertEqual(view.weather_name, 'rain')
        self.assertAlmostEqual(view.weather_until-rain[0], 8.)

    def test_same_tick_conflict_is_visible_after_both_requesting_impacts(self):
        anim = self.animation(self.weather(simultaneous=True))
        conflict = next(e for e in anim.timeline.events if e[1] == 'tactical_effect' and e[4] == 'weather_conflict')
        self.assertGreaterEqual(conflict[0], max(a.impact for a in anim.timeline.actions))
        self.assertFalse(any(e[4] == 'weather_start' for e in anim.timeline.events if e[1] == 'tactical_effect'))
        view = anim._presentation_view(); view._ensure(conflict[0])
        self.assertIn('晴雨冲突', view.msg[1])
        self.assertIsNone(view.weather_name)


class OpeningWeatherPresentation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assets = renderer.Front(), renderer.Palettes(), renderer.Font16()

    def battle(self, conflict=False, sid=38):
        battle = Battle([PIECES[sid]], [PIECES[131 if conflict else 9]], random.Random(42),
                        ruleset='tactics_v2', weather_name='hail',
                        positions_a=[(2, 2)], positions_b=[(2, 1)],
                        learned_b=[None if conflict else 'rain_dance'],
                        tactics_b=None if conflict else {'weather': {'source': 0}})
        for u in battle.units:
            u.hp = u.max_hp = 10000
            u.energy = 80
            battle._emit_state(u, 0.)
        if not conflict:
            with patch.object(battle.rng, 'randrange', return_value=0):
                battle._strike(battle.units[1], battle.units[0], 2.1)
            battle.flush_tactics(2.2)
        battle.flush_tactics(10.2)
        battle.events.append((10.3, 'end', None))
        return battle

    def test_opening_weather_precedes_cast_and_later_override_is_causal(self):
        for sid, weather in ((38, 'sun'), (131, 'rain')):
            battle = self.battle(sid=sid)
            before = copy.deepcopy(battle.events)
            anim = renderer.BattleAnimation([], [], 42, *self.assets, battle=battle)
            start = next(e for e in anim.timeline.events if e[1] == 'tactical_effect' and e[4] == 'weather_start')
            self.assertEqual(start[0], 0.)
            view = anim._presentation_view()
            view._ensure(0.)
            self.assertEqual(view.weather_name, weather)
            self.assertIn(PIECES[sid].name+'带来', view.msg[1])
            override = [e for e in anim.timeline.events if e[1] == 'tactical_effect' and e[4] == 'weather_start'][1]
            view._ensure(override[0]-.001)
            self.assertEqual(view.weather_name, weather)
            view._ensure(override[0])
            self.assertEqual(view.weather_name, 'rain')
            frame = anim.frame(override[0]+.1)
            self.assertEqual(frame.size, (240, 320))
            view._ensure(anim.timeline.duration)
            self.assertEqual(view.weather_name, 'hail')
            view._ensure(0.)  # Backward seek reconstructs opening state.
            self.assertEqual(view.weather_name, weather)
            self.assertEqual(battle.events, before)

    def test_opening_conflict_never_briefly_displays_either_override(self):
        battle = self.battle(conflict=True)
        anim = renderer.BattleAnimation([], [], 42, *self.assets, battle=battle)
        self.assertFalse(any(e[1] == 'tactical_effect' and e[4] == 'weather_start' for e in anim.timeline.events))
        for t in (0., .1, 5.):
            view = anim._presentation_view()
            view._ensure(t)
            self.assertEqual(view.weather_name, 'hail')
        view._ensure(0.)
        self.assertIn('晴雨冲突', view.msg[1])

    def test_opening_message_glyphs_have_real_pixels(self):
        from render_mockups import UI_GLYPHS
        font = self.assets[2]
        for ch in set('九尾带来晴天拉普拉斯带来雨天'):
            if ch not in UI_GLYPHS:
                self.assertIsNotNone(font.text(ch).getbbox(), f'missing device glyph {ch}')


if __name__ == '__main__':
    unittest.main()
