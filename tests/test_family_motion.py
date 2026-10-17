"""Contracts for family whole-body action tracks and their motion integration."""
from pathlib import Path
import sys
import unittest

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'sim'), str(ROOT/'tools/mockups')]

import family_motion
import motion
from arena import ROSTER
from arena_families import SPECIES_FAMILY


class FamilyMotionContracts(unittest.TestCase):
    def test_exactly_the_89_forms_outside_the_legacy_roster_are_authored(self):
        expected = set(SPECIES_FAMILY) - set(ROSTER)
        self.assertEqual(len(expected), 89)
        self.assertEqual(family_motion.SPECIES, frozenset(expected))

    def test_profiles_expose_notes_stage_and_normalized_emitter(self):
        for sid in family_motion.SPECIES:
            profile = family_motion.profile_of(sid)
            with self.subTest(species=sid):
                self.assertEqual(profile['species'], sid)
                self.assertIn(profile['archetype'], family_motion._ACTIONS)
                self.assertIn(profile['stage'], (0, 1, 2))
                self.assertTrue(profile['attack_note'])
                self.assertTrue(profile['cast_note'])
                x, y = profile['emitter']
                self.assertIsInstance(x, float)
                self.assertIsInstance(y, float)
                self.assertGreaterEqual(x, 0.)
                self.assertLessEqual(x, 1.)
                self.assertGreaterEqual(y, 0.)
                self.assertLessEqual(y, 1.)

    def test_attack_and_cast_have_distinct_deterministic_integer_tracks(self):
        progresses = (0., .25, .5, .75, 1.)
        for sid in family_motion.INTEGRATED_SPECIES:
            attack = tuple(family_motion.sample_action(sid, 'attack', state, p)
                           for state in family_motion.ACTION_STATES for p in progresses)
            cast = tuple(family_motion.sample_action(sid, 'cast', state, p)
                         for state in family_motion.ACTION_STATES for p in progresses)
            repeated = tuple(family_motion.sample_action(sid, 'attack', state, p)
                             for state in family_motion.ACTION_STATES for p in progresses)
            with self.subTest(species=sid):
                self.assertTrue(all(type(frame) is tuple and len(frame) == 6
                                    and all(type(value) is int for value in frame)
                                    for frame in attack))
                self.assertEqual(attack, repeated)
                self.assertNotEqual(attack, cast)

    def test_action_bounds_and_release_recovery_seams(self):
        for sid in family_motion.INTEGRATED_SPECIES:
            for kind in family_motion.KINDS:
                with self.subTest(species=sid, kind=kind):
                    for state in family_motion.ACTION_STATES:
                        for p in (0., .17, .5, .83, 1.):
                            dx, dy, sx, sy, angle, dissolve = family_motion.sample_action(
                                sid, kind, state, p)
                            self.assertGreaterEqual(abs(dx), 0)
                            self.assertLessEqual(abs(dy), 8)
                            self.assertGreaterEqual(sx, 80)
                            self.assertLessEqual(sx, 120)
                            self.assertGreaterEqual(sy, 80)
                            self.assertLessEqual(sy, 120)
                            self.assertLessEqual(abs(angle), 15)
                            self.assertIn(dissolve, (0, 1, 2, 3))
                    self.assertEqual(family_motion.sample_action(
                        sid, kind, 'recover', 1.), motion.REST)

    def test_invalid_action_sampling_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'unsupported species'):
            family_motion.sample_action(999, 'attack', 'strike', .5)
        for kind, state, progress in ((999, 'strike', .5), ('other', 'strike', .5),
                                      ('attack', 'idle', .5), ('attack', 'strike', -.1),
                                      ('attack', 'strike', 1.1),
                                      ('attack', 'strike', float('nan'))):
            with self.subTest(kind=kind, state=state, progress=progress):
                self.assertRaises(ValueError, family_motion.sample_action,
                                  1, kind, state, progress)

    def test_motion_registers_new_family_species_but_preserves_classic_130(self):
        self.assertEqual(family_motion.INTEGRATED_SPECIES,
                         frozenset(set(motion.species_motion) & family_motion.INTEGRATED_SPECIES))
        self.assertEqual(len(family_motion.INTEGRATED_SPECIES), 88)
        for sid in family_motion.INTEGRATED_SPECIES:
            with self.subTest(species=sid):
                self.assertTrue(motion.validate_motion(sid))
        # This key is from the pre-existing Gyarados track, not the new family row.
        self.assertEqual(motion.KEYFRAMES[130]['windup'][0], (-1,1,103,97,-5,0))
        classic = motion.sample(130, 'windup', 0, 'attack')
        self.assertEqual(motion.sample(130, 'windup', 0, 'cast'), classic)

    def test_motion_sampling_selects_action_kind_without_mutating_track(self):
        for sid in (1, 257, 350):
            states = motion.species_motion[sid]
            original = tuple(states.values())
            with self.subTest(species=sid):
                index, attack = motion.sample(sid, 'strike', .1, 'attack')
                self.assertEqual(attack, family_motion.sample_action(
                    sid, 'attack', 'strike', index/(len(states['strike'])-1)))
                _, cast = motion.sample(sid, 'strike', .1, 'cast')
                self.assertEqual(cast, family_motion.sample_action(
                    sid, 'cast', 'strike', index/(len(states['strike'])-1)))
                self.assertNotEqual(attack, cast)
                self.assertEqual(tuple(states.values()), original)


class FamilyEmitterTransformTests(unittest.TestCase):
    def source(self):
        image = Image.new('RGBA', (20, 30), (0, 0, 0, 0))
        for y in range(5, 25):
            for x in range(4, 16):
                image.putpixel((x, y), (40, 90, 160, 255))
        return image

    def test_emitter_follows_flip_scale_rotation_and_world_offset_ownership(self):
        source = self.source()
        before = source.tobytes()
        frame = (4, 1, 108, 94, 9, 0)
        left = motion.transform(source, 1, motion.Pose(
            'strike', 5, frame, direction=(-1, 0), action_kind='attack'))
        right = motion.transform(source, 1, motion.Pose(
            'strike', 5, frame, direction=(1, 0), action_kind='attack'))
        self.assertEqual(source.tobytes(), before)
        self.assertIn('emitter', left.info.get('rig_anchors', {}))
        self.assertIn('emitter', right.info.get('rig_anchors', {}))
        left_point = left.info['rig_anchors']['emitter']
        right_point = right.info['rig_anchors']['emitter']
        # The authored coordinate is in intrinsic left-facing space.  A right
        #-facing render mirrors that point before scaling and rotation.
        self.assertLess(right_point[0], left_point[0])
        # transform must not bake dx into the local canvas: foot placement would
        # subtract the same value.  World travel is owned by offsets() instead.
        self.assertEqual(left.size, right.size)
        self.assertEqual(left.info['foot_anchor'], right.info['foot_anchor'])
        left_offset = motion.offsets(motion.Pose(
            'strike', 5, frame, direction=(-1, 0), action_kind='attack'))
        right_offset = motion.offsets(motion.Pose(
            'strike', 5, frame, direction=(1, 0), action_kind='attack'))
        self.assertEqual((right_offset[0]-left_offset[0], right_offset[1]-left_offset[1]),
                         (2*frame[0], 0))
        self.assertEqual(left.tobytes(), motion.transform(source, 1, motion.Pose(
            'strike', 5, frame, direction=(-1, 0), action_kind='attack')).tobytes())

        source_colors = {pixel for pixel in source.getdata() if pixel[3]}
        for rendered in (left, right):
            self.assertLessEqual({pixel for pixel in rendered.getdata() if pixel[3]},
                                 source_colors)


if __name__ == '__main__':
    unittest.main()
