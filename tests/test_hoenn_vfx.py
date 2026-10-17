import hashlib
import sys
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'sim'), str(ROOT / 'tools/acceptance'), str(ROOT / 'tools/mockups')]
import hoenn_vfx


EXPECTED = {
    252, 253, 254, 255, 256, 257, 258, 259, 260, 270, 271, 272,
    280, 281, 282, 285, 286, 304, 305, 306, 333, 334, 349, 350,
    359, 371, 372, 373, 374, 375, 376,
}
PHASES = ('windup', 'flight', 'impact', 'aftermath')
CONFIG = {'effect_scale': 1., 'particle_density': 1., 'palette': 'standard'}


class HoennVfxTests(unittest.TestCase):
    def test_catalog_covers_all_31_forms_with_attack_and_cast_metadata(self):
        self.assertEqual(hoenn_vfx.SPECIES, EXPECTED)
        self.assertEqual(len(EXPECTED), 31)
        for sid in EXPECTED:
            with self.subTest(species=sid):
                self.assertRegex(hoenn_vfx.attack_label(sid), r'\S+')
                row = hoenn_vfx.describe(sid)
                self.assertTrue(row['attack_name'])
                self.assertTrue(row['cast_name'])
                self.assertIn(row['stage'], (1, 2, 3))
                self.assertTrue(row['identity'])
                self.assertTrue(row['emitter'])

    def test_draw_rejects_unknown_and_renders_every_phase(self):
        image = Image.new('RGBA', (960, 640))
        self.assertFalse(hoenn_vfx.draw(image, 999, (100, 100), (200, 100),
                                       'flight', .5, CONFIG))
        self.assertFalse(hoenn_vfx.draw(image, 254, (100, 100), (200, 100),
                                       'bad-phase', .5, CONFIG))
        self.assertFalse(hoenn_vfx.draw(image, 254, (100, 100), (200, 100),
                                       'flight', .5, CONFIG, kind='unknown'))
        for sid in EXPECTED:
            for kind in ('attack', 'cast'):
                track = []
                for phase in PHASES:
                    with self.subTest(species=sid, kind=kind, phase=phase):
                        canvas = Image.new('RGBA', (960, 640))
                        self.assertTrue(hoenn_vfx.draw(
                            canvas, sid, (220, 320), (740, 320), phase, .55, CONFIG,
                            kind=kind))
                        box = canvas.getchannel('A').getbbox()
                        self.assertIsNotNone(box)
                        self.assertGreaterEqual(box[0], 60)
                        self.assertLessEqual(box[2], 900)
                        self.assertGreaterEqual(box[1], 150)
                        self.assertLessEqual(box[3], 490)
                        track.append(hashlib.sha256(canvas.tobytes()).hexdigest())
                self.assertEqual(len(set(track)), 4)

    def test_species_tracks_are_distinct_and_deterministic(self):
        for kind in ('attack', 'cast'):
            tracks = {}
            for sid in EXPECTED:
                canvas = Image.new('RGBA', (960, 640))
                for phase in PHASES:
                    hoenn_vfx.draw(canvas, sid, (220, 320), (740, 320), phase, .55,
                                   CONFIG, kind=kind)
                repeat = Image.new('RGBA', (960, 640))
                for phase in PHASES:
                    hoenn_vfx.draw(repeat, sid, (220, 320), (740, 320), phase, .55,
                                   CONFIG, kind=kind)
                digest = hashlib.sha256(canvas.tobytes()).hexdigest()
                self.assertEqual(canvas.tobytes(), repeat.tobytes())
                tracks[sid] = digest
            self.assertEqual(len(set(tracks.values())), len(EXPECTED))

    def test_full_actions_use_actual_target_and_support_does_not_paint_a_decoy(self):
        right = Image.new('RGBA', (960, 640))
        left = Image.new('RGBA', (960, 640))
        self.assertTrue(hoenn_vfx.draw(right, 257, (200, 320), (700, 320),
                                      'flight', .65, CONFIG, kind='attack'))
        self.assertTrue(hoenn_vfx.draw(left, 257, (200, 320), (300, 320),
                                      'flight', .65, CONFIG, kind='attack'))
        self.assertNotEqual(right.tobytes(), left.tobytes())
        support = Image.new('RGBA', (960, 640))
        hoenn_vfx.draw(support, 282, (180, 330), (720, 320), 'flight', .55,
                       CONFIG, kind='cast', emitters=((180, 318),))
        decoy = support.crop((420, 110, 540, 230)).getchannel('A').getbbox()
        self.assertIsNone(decoy)

    def test_attack_and_cast_have_distinct_choreography(self):
        for sid in EXPECTED:
            attack = Image.new('RGBA', (960, 640))
            cast = Image.new('RGBA', (960, 640))
            for phase in PHASES:
                hoenn_vfx.draw(attack, sid, (220, 320), (740, 320), phase, .55,
                               CONFIG, kind='attack')
                hoenn_vfx.draw(cast, sid, (220, 320), (740, 320), phase, .55,
                               CONFIG, kind='cast')
            self.assertNotEqual(attack.tobytes(), cast.tobytes(), sid)

    def test_all_phase_settings_apply_and_secondary_is_smaller(self):
        variants = (
            CONFIG,
            {**CONFIG, 'palette': 'vivid'},
            {**CONFIG, 'effect_scale': .7},
            {**CONFIG, 'particle_density': .55},
        )
        for sid in EXPECTED:
            for phase in PHASES:
                tracks = []
                for config in variants:
                    canvas = Image.new('RGBA', (960, 640))
                    self.assertTrue(hoenn_vfx.draw(
                        canvas, sid, (220, 320), (740, 320), phase, .55, config))
                    tracks.append(hashlib.sha256(canvas.tobytes()).hexdigest())
                self.assertEqual(len(set(tracks)), 4, (sid, phase))

        primary = Image.new('RGBA', (960, 640))
        secondary = Image.new('RGBA', (960, 640))
        hoenn_vfx.draw(primary, 376, (240, 320), (700, 320), 'impact', .5, CONFIG,
                       kind='cast')
        hoenn_vfx.draw(secondary, 376, (240, 320), (700, 320), 'impact', .5, CONFIG,
                       kind='cast', secondary=True)
        pbox, sbox = primary.getchannel('A').getbbox(), secondary.getchannel('A').getbbox()
        self.assertIsNotNone(pbox)
        self.assertIsNotNone(sbox)
        self.assertLess((sbox[2] - sbox[0]) * (sbox[3] - sbox[1]),
                        (pbox[2] - pbox[0]) * (pbox[3] - pbox[1]))

    def test_aftermath_fades_and_completed_progress_disappears(self):
        early = Image.new('RGBA', (960, 640))
        late = Image.new('RGBA', (960, 640))
        hoenn_vfx.draw(early, 254, (220, 320), (740, 320), 'aftermath', .2, CONFIG)
        hoenn_vfx.draw(late, 254, (220, 320), (740, 320), 'aftermath', .8, CONFIG)
        early_alpha = early.getchannel('A')
        late_alpha = late.getchannel('A')
        self.assertGreater(max(early_alpha.getdata()), max(late_alpha.getdata()))
        self.assertGreater(max(late_alpha.getdata()), 0)
        finished = Image.new('RGBA', (960, 640))
        self.assertTrue(hoenn_vfx.draw(finished, 254, (220, 320), (740, 320),
                                       'aftermath', 1., CONFIG))
        self.assertIsNone(finished.getchannel('A').getbbox())

    def test_multiple_emitters_anchor_windup_to_real_positions_only(self):
        source = (480, 320)
        one = Image.new('RGBA', (960, 640))
        two = Image.new('RGBA', (960, 640))
        hoenn_vfx.draw(one, 254, source, (740, 320), 'windup', .8, CONFIG,
                       emitters=((260, 320),))
        hoenn_vfx.draw(two, 254, source, (740, 320), 'windup', .8, CONFIG,
                       emitters=((260, 320), (370, 320)))
        self.assertIsNotNone(two.getchannel('A').getbbox())
        self.assertIsNone(two.crop((440, 200, 520, 440)).getchannel('A').getbbox())
        self.assertNotEqual(one.tobytes(), two.tobytes())


    def test_secondary_cast_is_bounded_and_small_motifs_render(self):
        for sid in EXPECTED:
            motif = Image.new('RGBA', (64, 64))
            self.assertTrue(hoenn_vfx.draw_attack_motif(
                ImageDraw.Draw(motif), sid, 32, 32, .6, .3, True))
            self.assertIsNotNone(motif.getchannel('A').getbbox())
        secondary = Image.new('RGBA', (960, 640))
        self.assertTrue(hoenn_vfx.draw(secondary, 376, (240, 320), (700, 320),
                                      'impact', .5, CONFIG, kind='cast', secondary=True))
        box = secondary.getchannel('A').getbbox()
        self.assertIsNotNone(box)
        self.assertLess(box[2] - box[0], 310)
        self.assertLess(box[3] - box[1], 230)


if __name__ == '__main__':
    unittest.main()
