"""Support heal identities must differ by pixel form and rhythm, not palette."""
from pathlib import Path
import sys
import unittest
from unittest import mock

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'sim'), str(ROOT/'tools/mockups')]
import retro_native
import retro_support

KEYS = ('healing_song', 'life_pulse', 'bliss_chorus')
PHASES = (('windup', .28), ('flight', .58), ('impact', .32), ('aftermath', .50))
SOURCE = (160, 350)
PATIENT = (690, 350)


class SupportVfxIdentity(unittest.TestCase):
    def layer(self):
        return Image.new('RGBA', (960, 640))

    def cast(self, key, phase, progress, config=None):
        image = self.layer()
        handled = retro_support.draw_assistance(
            image, key, SOURCE, PATIENT, phase, progress, config or {})
        return image, handled

    def outcome(self, key, progress=.38, details=None, config=None):
        image = self.layer()
        handled = retro_support.draw_outcome(
            image, key, 'heal', SOURCE, PATIENT, progress, config or {},
            details if details is not None else {'amount': 18})
        return image, handled

    def mask(self, image):
        return image.getchannel('A').tobytes()

    def test_cast_choreographies_are_distinct_without_color(self):
        sequences = {}
        for key in KEYS:
            sequence = bytearray()
            for phase, progress in PHASES:
                image, handled = self.cast(key, phase, progress)
                with self.subTest(key=key, phase=phase):
                    self.assertTrue(handled)
                    self.assertIsNotNone(image.getbbox())
                sequence.extend(self.mask(image))
            sequences[key] = bytes(sequence)
        self.assertEqual(len(set(sequences.values())), len(KEYS))
        # At the shared NORMAL palette, at least 8% of the combined silhouettes
        # must disagree. This rejects a route/palette-only identity change.
        for i, left in enumerate(KEYS):
            for right in KEYS[i+1:]:
                disagreement = sum(a != b for a, b in zip(sequences[left], sequences[right]))
                union = sum(bool(a or b) for a, b in zip(sequences[left], sequences[right]))
                self.assertGreater(disagreement / union, .08,
                                   f'{left} and {right} are too similar without color')

    def test_positive_heal_packets_use_three_principal_forms_on_the_patient(self):
        expected = {
            'healing_song': '_music_ribbon',
            'life_pulse': '_life_membrane',
            'bliss_chorus': '_choir_petals',
        }
        for key, helper in expected.items():
            image = self.layer()
            constructor = getattr(retro_support, helper)
            with mock.patch.object(retro_support, helper,
                                   wraps=constructor) as drawn:
                handled = retro_support.draw_outcome(
                    image, key, 'heal', SOURCE, PATIENT, .38, {}, {'amount': 18})
            self.assertTrue(handled)
            self.assertGreaterEqual(drawn.call_count, 1)
            self.assertIsNotNone(image.getbbox())
            # A real support outcome never turns the caster into a second recipient.
            self.assertIsNone(image.crop((0, 0, SOURCE[0]+90, 640)).getbbox())

    def test_heal_amounts_and_blocked_dispatch_cannot_manufacture_recovery(self):
        for details in ({}, {'amount': 0}, {'amount': -4},
                        {'amount': float('nan')}, {'amount': True}):
            with self.subTest(details=details):
                image, handled = self.outcome('life_pulse', details=details)
                self.assertFalse(handled)
                self.assertIsNone(image.getbbox())
        blocked = self.layer()
        self.assertFalse(retro_native.draw_outcome(
            blocked, 'life_pulse', 'heal', SOURCE, PATIENT, .2, {}, {'amount': 0}))
        self.assertIsNone(blocked.getbbox())

    def test_native_heal_identity_has_its_own_change_rhythm(self):
        rhythms = {}
        clocks = (.08, .20, .34, .50, .68, .84)
        for key in KEYS:
            masks = []
            for progress in clocks:
                image, handled = self.outcome(key, progress)
                self.assertTrue(handled)
                masks.append(self.mask(image))
            rhythm = tuple(sum(a != b for a, b in zip(before, after))
                           for before, after in zip(masks, masks[1:]))
            self.assertTrue(all(change > 0 for change in rhythm),
                            f'{key} has a static glyph segment')
            rhythms[key] = rhythm
        self.assertEqual(len(set(rhythms.values())), len(KEYS))

    def test_scale_density_and_replay_are_part_of_each_identity(self):
        for key in KEYS:
            with self.subTest(key=key):
                configurations = ({}, {'effect_scale': .7},
                                  {'effect_scale': 1.3}, {'particle_density': .5},
                                  {'palette': 'vivid'})
                pictures = []
                for config in configurations:
                    first, handled = self.outcome(key, .38, config=config)
                    second, replay = self.outcome(key, .38, config=config)
                    self.assertTrue(handled and replay)
                    self.assertEqual(first.tobytes(), second.tobytes())
                    pictures.append(first.tobytes())
                self.assertEqual(len(set(pictures)), len(configurations))

    def test_contact_tails_finish_and_remain_opaque_pixel_cels(self):
        for key in KEYS:
            for phase, progress in (('impact', .18), ('impact', .82),
                                    ('aftermath', .28), ('aftermath', .68)):
                with self.subTest(key=key, phase=phase, progress=progress):
                    image, handled = self.cast(key, phase, progress)
                    self.assertTrue(handled)
                    self.assertIsNotNone(image.getbbox())
                    self.assertLessEqual(set(image.getchannel('A').tobytes()), {0, 255})
            finished, handled = self.cast(key, 'aftermath', 1.)
            self.assertTrue(handled)
            self.assertIsNone(finished.getbbox())
            for progress in (1., 1.4):
                expired, outcome_handled = self.outcome(key, progress)
                self.assertTrue(outcome_handled)
                self.assertIsNone(expired.getbbox())


if __name__ == '__main__':
    unittest.main()
