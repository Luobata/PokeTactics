"""Rendering contracts for family forms and the Hoenn art pack."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'sim'), str(ROOT / 'tools/acceptance'), str(ROOT / 'tools/mockups')]
import animation_preview as preview
import arena
import arena_families as families
import arena_skills
import arena_traits
import arena_vfx
import decoders
from action_preview import describe_clip
from animation_timeline import native_targeting
from arena_preview_scene import make_preview_scene
from character_catalog import character_catalog
from types import SimpleNamespace
from web_battle import WebBattleRenderer


HOENN_TERMINALS = (254, 257, 260, 272, 282, 286, 306, 334, 350, 359, 373, 376)
PHASES = ('windup', 'flight', 'impact', 'aftermath')


class FamilyRenderCatalogTests(unittest.TestCase):
    def test_default_arena_catalog_covers_every_playable_family_form(self):
        templates = families.build_templates()
        entries = character_catalog(mode='arena')
        self.assertEqual(set(entries), {str(sid) for sid in templates})
        self.assertEqual(len(entries), 151)
        self.assertIn('254', entries)
        self.assertEqual(entries['254']['skill']['native_id'], 'hoenn_cross_bullet_254')

    def test_explicit_legacy_templates_remain_previewable(self):
        entries = character_catalog(mode='arena', pieces=list(arena.build_templates().values()))
        self.assertEqual(set(entries), set(map(str, arena.ROSTER)))
        self.assertEqual(len(entries), 62)
        self.assertTrue(all(entry['capabilities']['resource_ready'] for entry in entries.values()))


class ExternalGen3AssetTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        for name in ('gen1_front.bin', 'palettes.bin'):
            shutil.copy(decoders.POKEWALK / name, self.root / name)
        for variant in ('normal', 'shiny'):
            (self.root / 'gen3' / variant).mkdir(parents=True)

    def _front_png(self, variant):
        path = self.root / 'gen3' / variant / '254.png'
        image = Image.new('RGBA', (4, 4), (0, 0, 0, 0))
        ImageDraw.Draw(image).rectangle((1, 1, 2, 2), fill=(120, 190, 100, 255))
        image.save(path)

    def test_external_asset_root_uses_both_local_png_generations(self):
        self._front_png('normal')
        self._front_png('shiny')
        piece = families.make_piece(252, 3)
        entry = character_catalog(mode='arena', pieces=[piece], asset_root=self.root)['254']
        self.assertTrue(entry['capabilities']['resource_ready'])
        self.assertEqual(entry['capabilities']['resource_errors'], [])
        self.assertEqual(entry['resources']['source'], 'gen3_png')
        self.assertEqual(Path(entry['resources']['normal']), self.root / 'gen3/normal/254.png')
        self.assertEqual(Path(entry['resources']['shiny']), self.root / 'gen3/shiny/254.png')

    def test_gen3_png_changes_invalidate_the_source_revision(self):
        png = self.root / 'gen3' / 'normal' / '254.png'
        png.write_bytes(b'asset-version-one')
        with patch.object(preview, 'ROOT', self.root), patch.object(decoders, 'GEN3_FRONT', self.root / 'gen3'):
            before = preview.source_revision()
            png.write_bytes(b'asset-version-two')
            self.assertNotEqual(before, preview.source_revision())


class FamilyActionRenderTests(unittest.TestCase):
    def test_hoenn_terminal_forms_have_real_cast_fixtures(self):
        for sid in HOENN_TERMINALS:
            with self.subTest(species=sid):
                anim = make_preview_scene(sid, 'cast')
                clip = describe_clip(anim, 'cast')
                skill = arena_skills.skill_of(sid)
                self.assertEqual(anim.preview_fixture['native_skill'], True)
                self.assertEqual(clip['targeting'], skill['targeting'])
                source = anim.events[clip['source_index']]
                self.assertEqual(source[4], 'arena_' + skill['id'])

    def test_legacy_template_pack_remains_selectable(self):
        anim = make_preview_scene(212, 'cast', templates=arena.build_templates())
        self.assertEqual(anim.by_idx[0].piece.species_id, 212)
        self.assertEqual(anim.preview_fixture['ruleset'], 'arena_v1')

    def test_family_basic_attack_is_authored_without_changing_legacy_registry(self):
        self.assertEqual(set(arena_vfx.EFFECTS), set(arena.ROSTER))
        self.assertEqual(arena_vfx.attack_label(254), '三连疾叶')
        for species in (5, 130, 254, 350):
            for phase in PHASES:
                with self.subTest(species=species, phase=phase):
                    image = Image.new('RGBA', (240, 160))
                    arena_vfx.draw_attack(image, species, (30, 80), (200, 80), phase, .55)
                    self.assertIsNotNone(image.getchannel('A').getbbox())
        self.assertEqual(set(arena_vfx.EFFECTS), set(arena.ROSTER))
        with self.assertRaisesRegex(ValueError, "no arena attack effect"):
            arena_vfx.attack_effect(999)

    def test_gen3_targeting_and_web_motif_use_resolved_native_skills(self):
        allies = (SimpleNamespace(team=0), SimpleNamespace(team=0))
        event = (0., 'cast', 0, 1, 'arena_hoenn_dragon_vein_270', 0, 0)
        self.assertEqual(native_targeting(event, allies), 'ally')
        self.assertEqual(native_targeting(event[:6] + (1,), allies), 'enemy')
        renderer = WebBattleRenderer(make_preview_scene(254, 'idle'))
        native = renderer._motif(254, 'arena_hoenn_cross_bullet_254', 'GRASS',
                                 'impact', 4, 0)
        basic = renderer._motif(254, '', 'GRASS', 'impact', 4, 0)
        self.assertIsNotNone(native.getchannel('A').getbbox())
        self.assertIsNotNone(basic.getchannel('A').getbbox())

    def test_family_generic_native_cast_targets_enemy(self):
        anim = make_preview_scene(5, 'cast')
        clip = describe_clip(anim, 'cast')
        source = anim.events[clip['source_index']]
        self.assertEqual(source[4], 'arena_family_strike_5')
        self.assertEqual(clip['targeting'], 'enemy')

    def test_family_trait_names_use_expanded_catalog_with_legacy_precedence(self):
        family_names = {row['id']: row['name']
                        for row in arena_traits.catalog(include_families=True)}
        self.assertEqual(family_names['trait_sturdy'], '坚硬脑袋')
        self.assertEqual(arena_vfx.COMBINATION_NAMES['trait_sturdy'], '结实')

    def test_hoenn_native_skill_uses_resolved_skill_and_element_material(self):
        image = Image.new('RGBA', (240, 320))
        arena_vfx.draw_native_skill(image, 254, 'cross_bullet',
                                    (60, 230), (170, 130), 'impact', .55)
        colors = {rgba[:3] for _, rgba in image.getcolors(image.width * image.height) if rgba[3]}
        self.assertTrue(any(g > r and g > b for r, g, b in colors))
        self.assertIsNotNone(image.getchannel('A').getbbox())

    def test_family_device_native_renders_both_packs_in_rgb_and_rgba(self):
        for species in (5, 130, 254, 350):
            for phase in PHASES:
                for mode in ('RGB', 'RGBA'):
                    with self.subTest(species=species, phase=phase, mode=mode):
                        image = Image.new(mode, (240, 320))
                        before = image.tobytes()
                        arena_vfx.draw_native_skill(image, species, arena_skills.skill_of(species)['id'],
                                                   (60, 230), (170, 130), phase, .55)
                        self.assertNotEqual(image.tobytes(), before)


if __name__ == '__main__':
    unittest.main()
