"""Presentation phase seams, timing compatibility, and articulated action intent."""
import copy
import random
from dataclasses import replace
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'sim'))
sys.path.insert(0, str(ROOT / 'tools' / 'mockups'))
import status
import render_battle_gif as renderer
from combat import Battle
from decoders import Front, Palettes
from motion import MotionSystem, duration
from profile_range import make_scene
from roster import build_roster
from web_motion import render_articulated

ROSTER = {p.species_id: p for ps in build_roster().values() for p in ps}
PROGRESSES = (0., .125, .25, .375, .5, .625, .75, .875, 1.)


class MotionPhaseContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assets = renderer.Front(), renderer.Palettes(), renderer.Font16()

    def melee_fixture(self):
        battle = Battle([ROSTER[68]], [ROSTER[143]], random.Random(19),
                        positions_a=[(2, 2)], positions_b=[(2, 1)])
        attacker, target = battle.units
        target.next_act = 1e6
        battle._emit_state(target, 0.)
        battle._emit_state(attacker, 0.)
        with patch.object(status, 'STATUS_ON', False):
            battle.run()
        return battle, renderer.BattleAnimation([], [], 19, *self.assets, battle=battle)

    def test_melee_strike_spans_four_presentation_samples(self):
        battle, anim = self.melee_fixture()
        raw_events = copy.deepcopy(battle.events)
        timing = next(action for action in anim.timeline.actions
                      if action.kind == 'attack' and not action.secondary)
        strike = timing.impact - timing.release
        self.assertGreaterEqual(strike, .15 - 1e-9)
        samples = tuple(timing.release + offset for offset in (0., .05, .10, strike))
        self.assertEqual(len(samples), 4)
        frames = [anim.playback_frame(moment, show_cutins=False).tobytes()
                  for moment in samples]
        self.assertEqual(len(set(frames)), 4)
        self.assertEqual(battle.events, raw_events)

    def test_authored_motion_switches_to_recovery_exactly_at_timeline_impact(self):
        anim = make_scene(6, 'melee', 7, 'attack')
        action = next(candidate for candidate in anim.timeline.actions
                      if candidate.kind == 'attack' and candidate.attacker == 0
                      and not candidate.secondary
                      and abs((candidate.impact - candidate.release)
                              - duration(6, 'strike')) > 1e-6)
        view = anim._presentation_view()
        unit = view.units[action.attacker]
        expected = {
            'release_minus': 'windup',
            'release_exact': 'strike',
            'impact_minus': 'strike',
            'impact_exact': 'recover',
            'impact_plus': 'recover',
            'recover_exact': 'idle',
        }
        for label, moment in (
                ('release_minus', action.release - .001),
                ('release_exact', action.release),
                ('impact_minus', action.impact - .001),
                ('impact_exact', action.impact),
                ('impact_plus', action.impact + .001),
                ('recover_exact', action.recover_end)):
            view._ensure(moment)
            pose = MotionSystem.resolve(view, unit, moment)
            with self.subTest(label=label):
                self.assertEqual(pose.state, expected[label])
                self.assertEqual(pose.action_kind,
                                 None if label == 'recover_exact' else 'attack')

    def test_next_authored_action_starts_at_prior_recover_end(self):
        anim = make_scene(6, 'melee', 7, 'attack')
        action = next(candidate for candidate in anim.timeline.actions
                      if candidate.kind == 'attack' and candidate.attacker == 0
                      and not candidate.secondary
                      and abs((candidate.impact - candidate.release)
                              - duration(6, 'strike')) > 1e-6)
        view = anim._presentation_view()
        unit = view.units[action.attacker]
        boundary = action.recover_end
        view._ensure(boundary)
        ended = MotionSystem.resolve(view, unit, boundary)
        next_timing = replace(action, source_index=-1, start=boundary,
                              release=boundary + .30, impact=boundary + .45,
                              recover_end=boundary + .65)
        key = (action.attacker, boundary)
        next_attack = (boundary, 1., 0.)
        view.timeline.action_by_onset[key] = next_timing
        unit.attacks.append(next_attack)
        try:
            next_pose = MotionSystem.resolve(view, unit, boundary)
        finally:
            unit.attacks.pop()
            del view.timeline.action_by_onset[key]

        self.assertEqual((ended.state, ended.action_kind), ('idle', None))
        self.assertEqual((next_pose.state, next_pose.action_kind), ('windup', 'attack'))

    def test_authored_motion_retains_raw_event_timing_fallback(self):
        anim = make_scene(6, 'melee', 7, 'attack')
        action = next(candidate for candidate in anim.timeline.actions
                      if candidate.kind == 'attack' and candidate.attacker == 0
                      and not candidate.secondary
                      and abs((candidate.impact - candidate.release)
                              - duration(6, 'strike')) > 1e-6)
        view = anim._presentation_view()
        unit = view.units[action.attacker]
        moment = action.impact
        view._ensure(moment)
        key = (action.attacker, action.start)
        timing = view.timeline.action_by_onset[key]
        del view.timeline.action_by_onset[key]
        try:
            fallback = MotionSystem.resolve(view, unit, moment)
        finally:
            view.timeline.action_by_onset[key] = timing
        self.assertEqual(fallback.state, 'strike')
        self.assertEqual(MotionSystem.resolve(view, unit, moment).state, 'recover')

    def test_authored_action_boundary_remains_seek_deterministic(self):
        anim = make_scene(6, 'melee', 7, 'attack')
        action = next(candidate for candidate in anim.timeline.actions
                      if candidate.kind == 'attack' and candidate.attacker == 0
                      and not candidate.secondary
                      and abs((candidate.impact - candidate.release)
                              - duration(6, 'strike')) > 1e-6)
        moment = action.impact - .05
        reference = anim.playback_frame(moment, show_cutins=False).tobytes()
        anim.playback_frame(anim.presentation_duration, show_cutins=False)
        self.assertEqual(reference,
                         anim.playback_frame(moment, show_cutins=False).tobytes())
        self.assertEqual(reference,
                         anim.playback_frame(moment / 2, speed=2, show_cutins=False).tobytes())


class ArticulatedActionKindTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        front, palettes = Front(), Palettes()
        cls.sources = {}
        for sid in (26, 68, 212):
            image = front.image(sid, palettes).convert('RGBA')
            image = image.crop(image.getchannel('A').getbbox())
            ratio = 64 / max(image.size)
            cls.sources[sid] = image.resize(
                (round(image.width * ratio), round(image.height * ratio)),
                Image.Resampling.NEAREST)

    def test_all_web_species_use_distinct_attack_and_cast_joint_tracks(self):
        for sid, source in self.sources.items():
            for state in ('windup', 'strike', 'recover'):
                attack = [render_articulated(source, sid, state, progress, -1, 'attack')
                          for progress in PROGRESSES]
                cast = [render_articulated(source, sid, state, progress, -1, 'cast')
                        for progress in PROGRESSES]
                different_pixels = sum(left.tobytes() != right.tobytes()
                                       for left, right in zip(attack, cast))
                different_anchors = sum(left.info['rig_anchors'] != right.info['rig_anchors']
                                        for left, right in zip(attack, cast))
                with self.subTest(species=sid, state=state):
                    # Recover legitimately settles to the same neutral final pose;
                    # every phase still needs a substantial distinct curve.
                    self.assertGreaterEqual(different_pixels, 7)
                    self.assertGreaterEqual(different_anchors, 7)
                    self.assertEqual(attack[-1].info['foot_anchor'],
                                     cast[-1].info['foot_anchor'])

    def test_articulated_action_kind_is_deterministic_and_foot_stable(self):
        for sid, source in self.sources.items():
            reference = render_articulated(source, sid, 'strike', .37, -1, 'attack')
            repeated = render_articulated(source, sid, 'strike', .37, -1, 'attack')
            cast = render_articulated(source, sid, 'strike', .37, -1, 'cast')
            self.assertEqual(reference.tobytes(), repeated.tobytes())
            self.assertNotEqual(reference.tobytes(), cast.tobytes())
            self.assertEqual(reference.info['foot_anchor'], cast.info['foot_anchor'])
            self.assertEqual(reference.size, cast.size)

    def test_articulated_recover_to_next_action_boundary_keeps_foot_pixels(self):
        for sid, source in self.sources.items():
            settled = render_articulated(source, sid, 'recover', 1., -1, 'attack')
            next_action = render_articulated(source, sid, 'windup', 0., -1, 'attack')
            with self.subTest(species=sid):
                self.assertEqual(settled.tobytes(), next_action.tobytes())
                self.assertEqual(settled.info['foot_anchor'],
                                 next_action.info['foot_anchor'])


if __name__ == '__main__':
    unittest.main()
