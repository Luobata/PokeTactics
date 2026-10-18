"""Shared skill glow: bright cores spill on the 3px grid, dark ink never glows."""
from pathlib import Path
import sys
import unittest

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'sim'), str(ROOT/'tools/mockups')]
import retro_primitives as rp
import retro_support


class BloomContracts(unittest.TestCase):
    def test_empty_and_dark_layers_add_no_glow(self):
        fx = Image.new('RGBA', (240, 180))
        self.assertIsNone(rp.bloom(fx))
        fx.paste((40, 30, 50, 255), (90, 60, 150, 120))
        self.assertIsNone(rp.bloom(fx), 'Dark outlines and envelopes must not glow')

    def test_bright_core_spills_banded_grid_glow_without_touching_fx(self):
        fx = Image.new('RGBA', (240, 180))
        fx.paste((255, 239, 128, 255), (99, 78, 141, 102))
        before = fx.tobytes()
        glow, (left, top) = rp.bloom(fx)
        self.assertEqual(fx.tobytes(), before)
        self.assertEqual((left % rp.PIXEL, top % rp.PIXEL), (0, 0))
        alpha = glow.getchannel('A')
        box = alpha.getbbox()
        self.assertLess(left + box[0], 99, 'Glow must spill past the core')
        self.assertGreater(left + box[2], 141)
        levels = set(alpha.tobytes()) - {0}
        self.assertTrue(levels)
        self.assertLessEqual(max(levels), rp.BLOOM_CEIL)
        self.assertLessEqual(len(levels), rp.BLOOM_STEPS)
        # Nearest stamping keeps whole 3px cells.
        for y in range(0, glow.height - glow.height % rp.PIXEL, rp.PIXEL):
            for x in range(0, glow.width - glow.width % rp.PIXEL, rp.PIXEL):
                cell = {alpha.getpixel((x + i, y + j)) for i in range(3) for j in range(3)}
                self.assertEqual(len(cell), 1)

    def test_ring_is_dithered_floor_patch_with_opaque_pixels(self):
        layer = Image.new('RGBA', (200, 200))
        colors = rp.palette('PSYCHIC', {})
        retro_support._ring(layer, (100, 100), colors, 18)
        alpha = layer.getchannel('A')
        self.assertLessEqual(set(alpha.tobytes()), {0, 255})
        fill = sum(1 for p in layer.getdata() if p[3] and p[:3] == colors[1])
        self.assertGreater(fill, 0, 'The ring needs a body, not only an outline')
        top = alpha.getbbox()[1]
        floor_top = min(y for y in range(200) for x in range(200)
                        if layer.getpixel((x, y))[3] and layer.getpixel((x, y))[:3] == colors[1])
        self.assertGreater(floor_top, top, 'The fill never rises to the far rim')


if __name__ == '__main__':
    unittest.main()
