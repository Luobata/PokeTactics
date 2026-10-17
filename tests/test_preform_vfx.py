"""Contracts for the family pre-form/branch presentation pack."""
import hashlib
from pathlib import Path
import sys
import unittest

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'sim'), str(ROOT/'tools/mockups')]
import arena_vfx
from arena_families import FAMILIES, SPECIES_FAMILY
from arena_skills import skill_of
import preform_vfx

SOURCE = (180, 320)
TARGET = (620, 320)
PHASES = (('windup', .62), ('flight', .48), ('impact', .36), ('aftermath', .42))


class PreformVfxContracts(unittest.TestCase):
    def test_covers_exactly_the_58_non_hoenn_family_gap(self):
        all_forms = {sid for _, (_, paths) in FAMILIES.items()
                     for path in paths for sid in path}
        hoenn = {sid for fid, (_, paths) in FAMILIES.items() if fid >= 252
                 for path in paths for sid in path}
        expected = all_forms - set(arena_vfx.EFFECTS) - hoenn
        self.assertEqual(len(expected), 58)
        self.assertEqual(preform_vfx.SPECIES, expected)
        self.assertFalse(preform_vfx.SPECIES & set(arena_vfx.EFFECTS))
        self.assertFalse(preform_vfx.SPECIES & hoenn)

    def test_metadata_matches_real_native_kits_and_growth_stage(self):
        positions = {}
        for fid, (_, paths) in FAMILIES.items():
            for path in paths:
                for index, sid in enumerate(path):
                    positions[sid] = min(index + 1, positions.get(sid, 99))
        for sid in preform_vfx.SPECIES:
            data = preform_vfx.describe(sid)
            with self.subTest(sid=sid):
                self.assertEqual(set(data), {
                    'attack_name', 'cast_name', 'identity', 'emitter', 'stage',
                    'element', 'motif', 'cast_kind'})
                self.assertEqual(data['cast_name'], skill_of(sid)['name'])
                self.assertEqual(data['element'], skill_of(sid)['type'])
                self.assertEqual(data['stage'], positions[sid])
                self.assertTrue(data['attack_name'])
                self.assertTrue(data['identity'])
                self.assertTrue(data['emitter'])
        self.assertEqual(len({preform_vfx.attack_label(sid) for sid in preform_vfx.SPECIES}), 58)
        self.assertIsNone(preform_vfx.attack_label(6))
        self.assertIsNone(preform_vfx.describe(252))

    def test_all_attack_and_cast_tracks_are_complete_distinct_and_bounded(self):
        for kind in ('attack', 'cast'):
            tracks = []
            for sid in sorted(preform_vfx.SPECIES):
                digest = hashlib.sha256()
                for phase, progress in PHASES:
                    image = Image.new('RGBA', (960, 640))
                    handled = preform_vfx.draw(
                        image, sid, SOURCE, TARGET, phase, progress,
                        {'palette': 'classic', 'effect_scale': 1., 'particle_density': 1.},
                        kind=kind)
                    box = image.getbbox()
                    with self.subTest(kind=kind, sid=sid, phase=phase):
                        self.assertTrue(handled)
                        self.assertIsNotNone(box)
                        self.assertGreaterEqual(box[0], 0)
                        self.assertGreaterEqual(box[1], 0)
                        self.assertLessEqual(box[2], 960)
                        self.assertLessEqual(box[3], 640)
                        # Effects lead toward the target without flooding the arena.
                        self.assertLessEqual(box[2]-box[0], 560)
                        self.assertLessEqual(box[3]-box[1], 300)
                    digest.update(image.getchannel('A').tobytes())
                tracks.append(digest.hexdigest())
            self.assertEqual(len(set(tracks)), 58,
                             f'{kind} tracks must differ by choreography, not palette alone')

    def test_output_is_deterministic_and_quantized_to_three_pixel_cells(self):
        for sid in (1, 92, 130, 133, 135, 239):
            first = Image.new('RGBA', (960, 640))
            second = Image.new('RGBA', (960, 640))
            self.assertTrue(preform_vfx.draw(first, sid, SOURCE, TARGET, 'impact', .44, {}, kind='cast'))
            self.assertTrue(preform_vfx.draw(second, sid, SOURCE, TARGET, 'impact', .44, {}, kind='cast'))
            self.assertEqual(first.tobytes(), second.tobytes())
            alpha = first.getchannel('A')
            for y in range(0, first.height, 3):
                for x in range(0, first.width, 3):
                    if alpha.getpixel((x, y)):
                        for yy in range(y, min(y+3, first.height)):
                            for xx in range(x, min(x+3, first.width)):
                                self.assertTrue(alpha.getpixel((xx, yy)),
                                                f'{sid} broke a cell at {xx},{yy}')

    def test_shared_visual_settings_change_every_signature(self):
        options = (
            ('effect_scale', {'effect_scale': .7}, {'effect_scale': 1.}),
            ('palette', {'palette': 'classic'}, {'palette': 'vivid'}),
            ('particle_density', {'particle_density': .5}, {'particle_density': 1.}),
        )
        for name, sparse, dense in options:
            unchanged = []
            for sid in preform_vfx.SPECIES:
                rendered = []
                for config in (sparse, dense):
                    image = Image.new('RGBA', (960, 640))
                    preform_vfx.draw(image, sid, SOURCE, TARGET, 'impact', .4,
                                     {**config}, kind='cast')
                    rendered.append(image.tobytes())
                if rendered[0] == rendered[1]:
                    unchanged.append(sid)
            self.assertEqual(unchanged, [], f'{name} had no visual effect')

    def test_dispatch_contracts_do_not_import_the_legacy_renderer(self):
        source = (ROOT/'tools/mockups/preform_vfx.py').read_text()
        self.assertNotIn('import arena_vfx', source)
        unknown = Image.new('RGBA', (960, 640))
        self.assertFalse(preform_vfx.draw(unknown, 252, SOURCE, TARGET, 'impact', .4, {}))
        self.assertFalse(preform_vfx.draw(Image.new('RGBA', (960, 640)), 1, SOURCE, TARGET,
                                          'charging', .4, {}, kind='cast'))
        expired = Image.new('RGBA', (960, 640))
        self.assertTrue(preform_vfx.draw(expired, 1, SOURCE, TARGET, 'impact', 1., {}))
        self.assertIsNone(expired.getbbox())
        motif = Image.new('RGBA', (64, 64))
        from PIL import ImageDraw
        self.assertFalse(preform_vfx.draw_attack_motif(ImageDraw.Draw(motif), 252, 32, 32, .5, 0, True))
        self.assertTrue(preform_vfx.draw_attack_motif(ImageDraw.Draw(motif), 1, 32, 32, .5, 0, True))


if __name__ == '__main__':
    unittest.main()
