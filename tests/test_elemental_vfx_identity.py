"""Horizontal identity contracts for same-colour native Electric/Psychic VFX."""
import itertools
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools/mockups'))
import retro_elemental as elemental
import retro_primitives as rp


ELECTRIC = {
    26: 'spark_chain', 125: 'storm_conductor', 181: 'charged_beacon',
}
PSYCHIC = {
    65: 'psychic_blink', 80: 'slow_field', 196: 'fracture_vision',
    150: 'mind_shatter', 151: 'ancient_mind',
}
SOURCE = (160, 370)
TARGET = (470, 180)
CONFIG = {'palette': 'classic', 'effect_scale': 1., 'particle_density': 1.}


class ElementalVfxIdentity(unittest.TestCase):
    def render(self, key, phase='impact', progress=.5, *, secondary=False, **options):
        image = Image.new('RGBA', (700, 530))
        handled = elemental.draw(image, key, SOURCE, TARGET, phase, progress,
                                  {**CONFIG, **options}, secondary=secondary)
        return handled, image

    def contact(self, key, age, *, secondary=False, **options):
        image = Image.new('RGBA', (700, 530))
        colors = rp.palette(elemental.TYPES[key], {**CONFIG, **options})
        scale, density = rp.settings({**CONFIG, **options})
        elemental._contact(image, key, SOURCE, TARGET, colors, scale, density,
                           age, (), secondary)
        return image

    @staticmethod
    def overlap(a, b):
        alpha_a, alpha_b = a.getchannel('A').convert('1'), b.getchannel('A').convert('1')
        intersection = ImageChops.multiply(alpha_a, alpha_b).histogram()[-1]
        union = ImageChops.add(alpha_a, alpha_b).histogram()[-1]
        return intersection/union if union else 0.

    @staticmethod
    def count(image):
        return sum(alpha > 0 for alpha in image.getchannel('A').tobytes())

    def test_review_uses_actual_native_skill_ids(self):
        self.assertEqual({key: elemental.TYPES[key] for key in ELECTRIC.values()},
                         {key: 'ELECTRIC' for key in ELECTRIC.values()})
        self.assertEqual({key: elemental.TYPES[key] for key in PSYCHIC.values()},
                         {key: 'PSYCHIC' for key in PSYCHIC.values()})

    def test_electric_flight_bodies_are_chain_route_vertical_leader_and_orb(self):
        _, chain = self.render('spark_chain', 'flight', .62)
        chain_box = chain.getbbox()
        self.assertIsNotNone(chain_box)
        with patch.object(elemental, '_lightning_route',
                          wraps=elemental._lightning_route) as route:
            self.render('spark_chain', 'flight', .62)
            self.assertEqual(route.call_args.args[1], SOURCE)
            self.assertEqual(route.call_args.args[2],
                             rp.point(SOURCE, TARGET, .62))

        _, thunder = self.render('storm_conductor', 'flight', .62)
        thunder_box = thunder.getbbox()
        self.assertIsNotNone(thunder_box)
        self.assertLessEqual(thunder_box[1], TARGET[1]-65)
        self.assertLess(thunder_box[3]-thunder_box[1],
                        chain_box[2]-chain_box[0])

        with patch.object(elemental, '_sprite', wraps=elemental._sprite) as sprite:
            self.render('charged_beacon', 'flight', .62)
            self.assertIn('electric_orb', [call.args[1] for call in sprite.call_args_list])
        _, orb = self.render('charged_beacon', 'flight', .62)
        self.assertGreaterEqual(orb.getbbox()[1], TARGET[1]-45)

    def test_electric_contacts_keep_three_local_family_silhouettes(self):
        boxes = {}
        for key in ELECTRIC.values():
            boxes[key] = [self.contact(key, age).getbbox()
                          for age in (.08, .18, .30)]
            self.assertTrue(all(box is not None for box in boxes[key]))

        for box in boxes['spark_chain']:
            width, height = box[2]-box[0], box[3]-box[1]
            self.assertGreaterEqual(width/max(1, height), 1.15)
            self.assertLessEqual(box[1], TARGET[1]+35)

        for box in boxes['storm_conductor'][1:2]:
            width, height = box[2]-box[0], box[3]-box[1]
            self.assertGreaterEqual(height/max(1, width), 1.25)
            self.assertLessEqual(box[1], TARGET[1]-70)

        for box in boxes['charged_beacon']:
            width, height = box[2]-box[0], box[3]-box[1]
            self.assertGreaterEqual(width/max(1, height), 1.05)
            self.assertGreaterEqual(box[1], TARGET[1]-45)

        for age in (.08, .18, .30):
            images = [self.contact(key, age) for key in ELECTRIC.values()]
            for a, b in itertools.combinations(images, 2):
                self.assertLess(self.overlap(a, b), .38,
                                f'Electric contacts overlap at age={age}')

    def test_psychic_contacts_use_five_local_semantic_silhouettes(self):
        keys = tuple(PSYCHIC.values())
        for age in (.12, .24, .36, .49):
            images = [self.contact(key, age) for key in keys]
            self.assertTrue(all(image.getbbox() is not None for image in images))
            for (key_a, a), (key_b, b) in zip(zip(keys, images),
                                               zip(keys[1:], images[1:])):
                self.assertLess(self.overlap(a, b), .46,
                                f'{key_a} and {key_b} overlap at age={age}')

        # Confusion remains a filled low disturbance lens, substantially denser
        # than Future Sight's two separated sheared slices.
        confusion = self.contact('slow_field', .12)
        future = self.contact('fracture_vision', .12)
        self.assertGreater(self.count(confusion), self.count(future)*1.5)

        # Psychic is a filled heavy volume, not a thin same-colour ring.
        psychic = self.contact('mind_shatter', .12)
        box = psychic.getbbox()
        self.assertGreater(self.count(psychic)/((box[2]-box[0])*(box[3]-box[1])), .30)

        # Ancient Power uses its angular glyph material and no generic wave call.
        with patch.object(elemental, '_pressure_wave') as wave, \
             patch.object(elemental, '_sprite', wraps=elemental._sprite) as sprite:
            self.contact('ancient_mind', .18)
            wave.assert_not_called()
            self.assertIn('glyph', [call.args[1] for call in sprite.call_args_list])

    def test_psychic_weight_and_ancient_glyph_sprites_have_volume(self):
        psychic = elemental._tile('psychic_weight', rp.palette('PSYCHIC', CONFIG), 3)
        glyph = elemental._tile('glyph', rp.palette('PSYCHIC', CONFIG), 4)
        for sprite in (psychic, glyph):
            box = sprite.getbbox()
            count = self.count(sprite)
            self.assertIsNotNone(box)
            self.assertGreater(count/((box[2]-box[0])*(box[3]-box[1])), .30)
            self.assertGreaterEqual(len({color[:3] for _, color
                                         in sprite.getcolors(16) if color[3]}), 4)
            self.assertTrue(all(alpha in (0, 255)
                                for alpha in sprite.getchannel('A').tobytes()))

    def test_density_and_scale_remain_visible_local_controls(self):
        for key in (*ELECTRIC.values(), 'mind_shatter', 'ancient_mind'):
            with self.subTest(skill=key):
                sparse = self.contact(key, .32, particle_density=.5)
                dense = self.contact(key, .32, particle_density=1.)
                self.assertLess(self.count(sparse), self.count(dense))

                small = self.contact(key, .18, effect_scale=.7)
                large = self.contact(key, .18, effect_scale=1.3)
                small_box, large_box = small.getbbox(), large.getbbox()
                self.assertIsNotNone(small_box)
                self.assertIsNotNone(large_box)
                self.assertLess(small_box[2]-small_box[0], large_box[2]-large_box[0])
                self.assertLess(small_box[3]-small_box[1], large_box[3]-large_box[1])
                self.assertGreaterEqual(large_box[0], TARGET[0]-122)
                self.assertLessEqual(large_box[2], TARGET[0]+122)
                self.assertGreaterEqual(large_box[1], TARGET[1]-122)
                self.assertLessEqual(large_box[3], TARGET[1]+122)

    def test_lifecycle_secondary_and_pixel_budget_are_preserved(self):
        all_keys = (*ELECTRIC.values(), *PSYCHIC.values())
        for key in all_keys:
            with self.subTest(skill=key):
                final = self.render(key, 'impact', 1.)[1]
                recovery = self.render(key, 'aftermath', 0.)[1]
                self.assertEqual(final.tobytes(), recovery.tobytes())
                self.assertIsNone(self.render(key, 'aftermath', 1.)[1].getbbox())
                for phase in ('windup', 'flight'):
                    self.assertIsNone(self.render(key, phase, .5, secondary=True)[1].getbbox())
                image = self.render(key, 'impact', .35)[1]
                self.assertTrue(all(alpha in (0, 255)
                                    for alpha in image.getchannel('A').tobytes()))

        previous, recipient, unrelated = (123.25, 321.75), (419.125, 170.875), (560.25, 96.5)
        with patch.object(elemental, '_lightning_route',
                          wraps=elemental._lightning_route) as route:
            elemental.draw(Image.new('RGBA', (700, 530)), 'spark_chain',
                           previous, recipient, 'impact', .35, CONFIG,
                           secondary=True)
            self.assertEqual(route.call_args.args[1], previous)
            self.assertEqual(route.call_args.args[2], recipient)
        side = Image.new('RGBA', (700, 530))
        elemental.draw(side, 'spark_chain', previous, recipient, 'impact', .35,
                       CONFIG, secondary=True)
        self.assertIsNotNone(side.crop((recipient[0]-35, recipient[1]-35,
                                        recipient[0]+35, recipient[1]+35)).getbbox())
        self.assertIsNone(side.crop((unrelated[0]-15, unrelated[1]-15,
                                     unrelated[0]+15, unrelated[1]+15)).getbbox())


if __name__ == '__main__':
    unittest.main()
