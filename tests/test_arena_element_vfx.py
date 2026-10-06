"""Each skill type has a distinct material in every causal phase."""
import hashlib
import sys
import unittest
from pathlib import Path
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools/mockups'))
import arena_vfx


class ElementMaterials(unittest.TestCase):
    def test_primary_element_shapes_differ_in_every_phase_and_are_bounded(self):
        for phase in ('windup', 'flight', 'impact', 'aftermath'):
            hashes = []
            for element in arena_vfx.ELEMENT_COLORS:
                img = Image.new('RGBA', (240, 400))
                arena_vfx.draw_skill(img, 6, element, (60, 230), (170, 130), phase, .55)
                self.assertIsNotNone(img.getbbox())
                hashes.append(hashlib.sha256(img.tobytes()).hexdigest())
                self.assertLess(img.getchannel('A').getbbox()[3], 300)
            with self.subTest(phase=phase):
                self.assertEqual(len(hashes), len(set(hashes)))


if __name__ == '__main__': unittest.main()
