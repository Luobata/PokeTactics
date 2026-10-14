"""Persistent status motifs stay local, deterministic, and bounded."""
import sys
from pathlib import Path
import unittest

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools/mockups'))
import retro_status as status


class RetroStatusContracts(unittest.TestCase):
    bounds = (45, 30, 105, 112)
    foot = (75, 112)

    def image(self):
        return Image.new('RGBA', (180, 160), (0, 0, 0, 0))

    def draw(self, kinds, t=.37, idx=3, bounds=None, foot=None):
        image = self.image()
        drawn = status.draw_body(image, kinds, foot or self.foot,
                                 bounds or self.bounds, t, idx)
        return image, drawn

    def test_contract_and_normalization_are_explicit(self):
        self.assertEqual(status.info()['max_motifs'], 5)
        self.assertEqual(status.normalize_kinds(
            ('frozen', 'paralyzed', 'rooted', 'poisoned', 'unknown')),
            ('freeze', 'paralysis', 'root', 'poison'))
        self.assertEqual(status.normalize_kinds(()), ())
        self.assertEqual(status.foot_anchor(self.bounds), (75, 111))
        self.assertIn('head', status.rig_anchors(self.bounds, self.foot))

    def test_each_ailment_has_a_local_deterministic_motif(self):
        for kind in status.SUPPORTED_KINDS:
            with self.subTest(kind=kind):
                first, drawn = self.draw((kind,), t=.31)
                self.assertEqual(drawn, {kind})
                self.assertIsNotNone(first.getbbox())
                box = first.getbbox()
                self.assertGreaterEqual(box[0], 18)
                self.assertLessEqual(box[2], 162)
                self.assertGreaterEqual(box[1], 6)
                self.assertLessEqual(box[3], 150)
                self.draw(('freeze', 'sleep', 'paralysis'), t=.73)
                second, _ = self.draw((kind,), t=.31)
                self.assertEqual(first.tobytes(), second.tobytes())

    def test_paralysis_is_intermittent_not_a_constant_strobe(self):
        bright, _ = self.draw(('paralysis',), t=.30)
        dark, _ = self.draw(('paralysis',), t=.40)
        self.assertIsNotNone(bright.getbbox())
        self.assertIsNone(dark.getbbox())

    def test_control_takes_primary_role_and_dots_shrink(self):
        both, drawn = self.draw(('burn', 'poison', 'freeze', 'root', 'vulnerability'))
        self.assertEqual(drawn, {'freeze', 'root', 'vulnerability', 'burn', 'poison'})
        alone, _ = self.draw(('burn',))
        self.assertLessEqual(sum(value >= 200 for value in both.getchannel('A').histogram()[200:]), 700)

    def test_all_overlaps_stay_inside_a_bounded_local_region(self):
        image, _ = self.draw(tuple(status.SUPPORTED_KINDS), t=.83)
        box = image.getbbox()
        self.assertIsNotNone(box)
        self.assertLessEqual(box[2]-box[0], 102)
        self.assertLessEqual(box[3]-box[1], 114)
        self.assertLessEqual(sum(image.getchannel('A').histogram()[200:]), 700)
        self.assertIsNone(image.crop((0, 0, 12, 160)).getbbox())
        self.assertIsNone(image.crop((168, 0, 180, 160)).getbbox())

    def test_freeze_shell_and_poison_tint_preserve_the_body(self):
        body = Image.new('RGBA', (60, 82), (220, 40, 40, 255))
        before = body.tobytes()
        status.draw_body(body, ('freeze',), (30, 82), (0, 0, 60, 82), .42)
        core = body.crop((18, 30, 42, 52))
        self.assertEqual(core.getchannel('A').getextrema(), (255, 255))
        self.assertLess(max(abs(extremum-expected)
                           for channel, expected in zip(core.getextrema(), (220, 40, 40, 255))
                           for extremum in channel), 70)
        clean = Image.new('RGBA', body.size, (220, 40, 40, 255))
        tinted = status.tint_sprite(clean, ('poison',))
        self.assertEqual(tinted.getchannel('A').tobytes(), clean.getchannel('A').tobytes())
        self.assertNotEqual(tinted.tobytes(), before)
        self.assertEqual(status.tint_sprite(clean, ('burn',)).tobytes(), clean.tobytes())

    def test_invalid_inputs_do_not_paint(self):
        image = self.image()
        self.assertEqual(status.draw_body(image, None, self.foot, self.bounds, 1), frozenset())
        self.assertIsNone(image.getbbox())
        with self.assertRaises(ValueError):
            status.draw_body(image, ('freeze',), self.foot, (10, 10, 10, 20), 1)
        with self.assertRaises(ValueError):
            status.draw_body(Image.new('RGB', (10, 10)), ('freeze',), (5, 5), (1, 1, 8, 8), 1)


if __name__ == '__main__':
    unittest.main()
