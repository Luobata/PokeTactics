"""Johto art, authored attack silhouettes and real native replay dispatch."""
import copy
import hashlib
import random
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'sim'), str(ROOT / 'tools/mockups')]
import arena
import arena_skills
import arena_vfx
import decoders
from combat import Battle
from decoders import AssetError, Front, Palettes, Font16
from render_battle_gif import BattleAnimation

GEN2_IDS = frozenset((162, 211, 195, 237, 164, 171, 181, 196, 214,
                      197, 208, 242, 157, 212, 230, 160, 248, 154,
                      198, 200, 215, 227))
PHASES = ('windup', 'flight', 'impact', 'aftermath')


class Gen2VisualTracks(unittest.TestCase):
    def test_62_tracks_cover_roster_and_keep_new_silhouettes_distinct(self):
        self.assertEqual(set(arena_vfx.EFFECTS), set(arena.ROSTER))
        self.assertEqual(len(arena_vfx.EFFECTS), 62)
        self.assertEqual(set(arena_vfx.GEN2_EFFECTS), GEN2_IDS)
        for phase in PHASES:
            silhouettes = []
            for sid in GEN2_IDS:
                image = Image.new('RGBA', (320, 320))
                arena_vfx.draw_attack(image, sid, (64, 230), (256, 100), phase, .55)
                silhouettes.append(hashlib.sha256(image.getchannel('A').tobytes()).hexdigest())
            with self.subTest(phase=phase):
                self.assertEqual(len(set(silhouettes)), 22)

    def test_all_62_basic_and_native_tracks_are_nonempty_and_bounded_at_phase_edges(self):
        self.assertEqual(set(arena_skills.SKILLS), set(arena_vfx.EFFECTS))
        for sid in arena.ROSTER:
            for phase in PHASES:
                for progress in (-.2, 0., .55, 1., 1.2):
                    for native in (False, True):
                        with self.subTest(species=sid, phase=phase, progress=progress, native=native):
                            image = Image.new('RGBA', (480, 440))
                            if native:
                                arena_vfx.draw_native_skill(image, sid, arena_skills.SKILLS[sid]['id'],
                                                           (96, 300), (360, 100), phase, progress)
                            else:
                                arena_vfx.draw_attack(image, sid, (96, 300), (360, 100), phase, progress)
                            bounds = image.getchannel('A').getbbox()
                            self.assertIsNotNone(bounds)
                            self.assertGreaterEqual(bounds[0], 48)
                            self.assertGreaterEqual(bounds[1], 52)
                            self.assertLessEqual(bounds[2], 409)
                            self.assertLessEqual(bounds[3], 349)

    def test_dark_and_steel_native_contacts_use_their_canonical_material(self):
        for sid, element in ((197, 'DARK'), (208, 'STEEL'), (212, 'STEEL')):
            with self.subTest(species=sid):
                image = Image.new('RGBA', (240, 320))
                arena_vfx.draw_native_skill(image, sid, arena_skills.SKILLS[sid]['id'],
                                           (60, 230), (170, 130), 'impact', .55)
                colors = {rgba[:3] for _, rgba in image.getcolors(image.width * image.height) if rgba[3]}
                self.assertIn(arena_vfx.ELEMENT_COLORS[element], colors)

    def test_native_side_hit_uses_recorded_element_instead_of_main_cast_element(self):
        image = Image.new('RGBA', (240, 320))
        with patch.object(arena_vfx, 'draw_skill', wraps=arena_vfx.draw_skill) as draw:
            arena_vfx.draw_native_skill(image, 230, 'dragon_crosscurrent', (60, 230), (170, 130),
                                       'impact', .55, element='DRAGON')
            self.assertEqual(draw.call_args.args[2], 'DRAGON')
        self.assertIsNotNone(image.getchannel('A').getbbox())
        colors = {rgba[:3] for _, rgba in image.getcolors(image.width * image.height) if rgba[3]}
        self.assertIn(arena_vfx.ELEMENT_COLORS['DRAGON'], colors)

    def test_new_basic_tracks_preserve_both_faction_silhouettes(self):
        for sid in GEN2_IDS:
            frames = []
            for team in (0, 1):
                image = Image.new('RGBA', (240, 160))
                arena_vfx.draw_attack(image, sid, (30, 80), (200, 80), 'flight', .55, team)
                frames.append(image)
            with self.subTest(species=sid):
                self.assertNotEqual(frames[0].tobytes(), frames[1].tobytes())
                self.assertNotEqual(frames[0].crop((22, 71, 39, 89)).getchannel('A').tobytes(),
                                    frames[1].crop((22, 71, 39, 89)).getchannel('A').tobytes())


class Gen2AssetContracts(unittest.TestCase):
    def test_all_22_normal_and_shiny_pngs_are_real_independent_art(self):
        from arena_families import SPECIES_FAMILY
        self.assertEqual(decoders.GEN2_SPECIES, set(range(152, 252)))
        front = Front()
        palette = Mock()
        palette.for_species.side_effect = AssertionError('Gen 2 must not use the Gen 1 palette map')
        normal_hashes, shiny_hashes = set(), set()
        for sid in GEN2_IDS:
            images = []
            for shiny in (False, True):
                with self.subTest(species=sid, shiny=shiny):
                    image = front.image(sid, palette, shiny=shiny)
                    images.append(image)
                    path = ROOT / 'assets/gen2' / ('shiny' if shiny else 'normal') / f'{sid}.png'
                    before = hashlib.sha256(path.read_bytes()).hexdigest()
                    with Image.open(path) as original:
                        original.info['transparency'] = 0
                        raw = original.convert('RGBA')
                        white = tuple(original.getpalette()[:3]) + (255,)
                    # Index 0 doubles as background and the sprite's own white;
                    # the decoder restores only fully enclosed pixels to opaque
                    # white, leaving every other pixel byte-identical.
                    open_air = bytearray(image.width * image.height)
                    stack = [(x, 0) for x in range(image.width)] + \
                            [(x, image.height - 1) for x in range(image.width)] + \
                            [(0, y) for y in range(image.height)] + \
                            [(image.width - 1, y) for y in range(image.height)]
                    raw_alpha = raw.getchannel('A').load()
                    while stack:
                        x, y = stack.pop()
                        if not (0 <= x < image.width and 0 <= y < image.height) \
                                or raw_alpha[x, y] or open_air[y * image.width + x]:
                            continue
                        open_air[y * image.width + x] = 1
                        stack.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))
                    img_px, raw_px = image.load(), raw.load()
                    for y in range(image.height):
                        for x in range(image.width):
                            if raw_px[x, y][3] or open_air[y * image.width + x]:
                                self.assertEqual(img_px[x, y], raw_px[x, y])
                            else:
                                self.assertEqual(img_px[x, y], white)
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
                    self.assertEqual(image.mode, 'RGBA')
                    self.assertEqual(image.width, image.height)
                    self.assertIsNotNone(image.getchannel('A').getbbox())
                    self.assertEqual(image.getchannel('A').getextrema()[0], 0)
                    self.assertEqual(front.size_for_species(sid), image.width)
                    colors = front.palette_for_species(sid, palette, shiny=shiny)
                    self.assertTrue(colors)
                    self.assertTrue(all(len(rgb) == 3 for rgb in colors))
            self.assertNotEqual(images[0].tobytes(), images[1].tobytes())
            normal_hashes.add(hashlib.sha256(images[0].tobytes()).hexdigest())
            shiny_hashes.add(hashlib.sha256(images[1].tobytes()).hexdigest())
        self.assertEqual(len(normal_hashes), 22)
        self.assertEqual(len(shiny_hashes), 22)
        palette.for_species.assert_not_called()

    def _binary(self, path, sid=26):
        path.write_bytes(struct.pack('<4sHHHHIIH', b'FRNT', 1, 1, 8, 16, 1, 0, sid) + bytes(16))

    def _indexed_image(self, size=(8, 8), visible=True):
        image = Image.new('P', size)
        image.putpalette([255, 255, 255, 90, 110, 130, 160, 180, 200, 0, 0, 0])
        if visible:
            ImageDraw.Draw(image).rectangle((2, 2, 5, 5), fill=1)
        return image

    def test_png_failures_name_the_species_and_exact_resource(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            self._binary(directory / 'gen1_front.bin')
            (directory / 'normal').mkdir()
            (directory / 'shiny').mkdir()
            with patch.object(decoders, 'POKEWALK', directory), patch.object(decoders, 'GEN2_FRONT', directory):
                for bad_image, reason in ((None, 'cannot read PNG'),
                                          (self._indexed_image(visible=False), 'no visible pixels'),
                                          (self._indexed_image((8, 9)), 'must be square'),
                                          (Image.new('RGBA', (8, 8), 'red'), 'expected indexed P')):
                    path = directory / 'normal/162.png'
                    if bad_image is not None:
                        bad_image.save(path)
                    with self.subTest(reason=reason), self.assertRaisesRegex(AssetError, rf'species 162:.*{reason}.*normal/162.png'):
                        Front().image(162, Mock())
                (directory / 'normal/162.png').write_bytes(b'not a PNG')
                with self.assertRaisesRegex(AssetError, r'species 162:.*cannot read PNG.*normal/162.png'):
                    Front().image(162, Mock())
                self._indexed_image().save(directory / 'normal/162.png')
                with self.assertRaisesRegex(AssetError, r'species 162:.*cannot read PNG.*shiny/162.png'):
                    Front().image(162, Mock(), shiny=True)

    def test_explicit_binary_path_keeps_the_original_decoder_even_for_gen2_ids(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'custom.bin'
            self._binary(path, 162)
            front, palette = Front(path), Mock()
            palette.for_species.return_value = [(70, 90, 110)] * 4
            image = front.image(162, palette, shiny=True)
            self.assertEqual(image.size, (8, 8))
            self.assertEqual(image.getpixel((0, 0)), (70, 90, 110, 255))
            palette.for_species.assert_called_once_with(162, True)
            with self.assertRaisesRegex(AssetError, r'species 211: missing front sprite.*custom.bin'):
                front.image(211, palette)

    def test_png_cache_returns_independent_images(self):
        front, palette = Front(), Mock()
        original = front.image(162, palette).tobytes()
        returned = front.image(162, palette)
        ImageDraw.Draw(returned).rectangle((0, 0, returned.width, returned.height), fill=(0, 0, 0, 0))
        self.assertEqual(front.image(162, palette).tobytes(), original)

    def test_new_name_glyphs_are_visible_and_original_binary_glyphs_stay_exact(self):
        default = Font16()
        binary = Font16(decoders.POKEWALK / 'font16.bin')
        for ch, glyph in binary._glyph.items():
            self.assertEqual(default._glyph[ch], glyph)
        missing = set(decoders.GEN2_TEXT) - binary._glyph.keys()
        self.assertTrue(missing)
        self.assertIsNotNone(default.fallback_font_path)
        self.assertIsNone(binary.fallback_font_path)
        for ch in set(decoders.GEN2_TEXT):
            with self.subTest(character=ch):
                self.assertIsNotNone(default.text(ch).getchannel('A').getbbox())
        for ch in missing:
            self.assertIsNone(binary.text(ch).getchannel('A').getbbox())


class Gen2NativeReplay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assets = Front(), Palettes(), Font16()

    def test_all_22_real_casts_render_correct_species_and_rewind_without_event_mutation(self):
        templates = arena.build_templates()
        for sid in GEN2_IDS:
            with self.subTest(species=sid):
                battle = Battle([copy.copy(templates[sid]), copy.copy(templates[31])],
                                [copy.copy(templates[68]), copy.copy(templates[40])], random.Random(19),
                                positions_a=[(2, 3), (1, 3)], positions_b=[(2, 2), (1, 2)],
                                ruleset='arena_v1', stat_mode='budget_v1')
                for unit in battle.units:
                    unit.hp = unit.max_hp = 10000
                battle.units[1].hp = 2000
                battle.units[0].energy = arena_skills.ENERGY_MAX
                battle._strike(battle.units[0], battle.units[2], 2.)
                original = copy.deepcopy(battle.events)
                animation = BattleAnimation([], [], 19, *self.assets, battle=battle)
                cast = next(event for event in animation.timeline.events if event[1] == 'cast')
                self.assertEqual(cast[4], 'arena_' + arena_skills.SKILLS[sid]['id'])
                action = animation.timeline.action_by_event[id(cast)]
                with patch.object(arena_vfx, 'draw_native_skill', wraps=arena_vfx.draw_native_skill) as draw:
                    image = animation.playback_frame(action.release + .05, show_cutins=False)
                    self.assertTrue(any(call.args[1:3] == (sid, arena_skills.SKILLS[sid]['id'])
                                        for call in draw.call_args_list))
                self.assertEqual(image.size, (240, 400))
                normal = animation._board_sprite(sid, templates[sid].tier, shiny=False)
                shiny = animation._board_sprite(sid, templates[sid].tier, shiny=True)
                self.assertIsNotNone(normal.getchannel('A').getbbox())
                self.assertIsNotNone(shiny.getchannel('A').getbbox())
                self.assertNotEqual(normal.tobytes(), shiny.tobytes())
                first = animation.playback_frame(action.impact + .1, show_cutins=False).tobytes()
                animation.playback_frame(0., show_cutins=False)
                self.assertEqual(first, animation.playback_frame(action.impact + .1, show_cutins=False).tobytes())
                self.assertEqual(original, battle.events)


if __name__ == '__main__':
    unittest.main()
