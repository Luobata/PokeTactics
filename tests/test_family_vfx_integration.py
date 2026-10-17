"""Family choreography reaches actual playback without changing battle events."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools/mockups'), str(ROOT/'tools/acceptance'), str(ROOT/'sim')]
import arena_families
import arena_skills
import arena_vfx
import family_vfx
import retro_attacks
import retro_native
from arena_preview_scene import make_preview_scene
from action_preview import describe_clip
from character_catalog import character_catalog
from presentation_modes import make_renderer

CONFIG = {'palette': 'classic', 'effect_scale': 1., 'particle_density': 1.}


class FamilyVfxIntegration(unittest.TestCase):
    def test_every_deployable_form_resolves_explicit_basic_art(self):
        templates = arena_families.build_templates()
        missing = set(templates) - set(arena_vfx.EFFECTS)
        self.assertEqual(len(missing), 89)
        self.assertEqual(missing, family_vfx.SPECIES)
        for sid in templates:
            self.assertNotEqual(arena_vfx.attack_label(sid), '家族冲击', sid)
            canvas = Image.new('RGBA', (960, 640))
            self.assertTrue(retro_attacks.draw(canvas, sid, (240, 360), (600, 300),
                                              'flight', .5, CONFIG), sid)
            self.assertIsNotNone(canvas.getbbox(), sid)

    def test_every_new_native_resolves_through_its_real_identity(self):
        for sid in sorted(family_vfx.SPECIES):
            key = arena_skills.skill_of(sid)['id']
            self.assertTrue(retro_native.has_move('arena_' + key), (sid, key))
            canvas = Image.new('RGBA', (960, 640))
            self.assertTrue(retro_native.draw(canvas, 'arena_' + key, (240, 360), (600, 300),
                                             'flight', .5, CONFIG, species_id=sid), sid)
            self.assertIsNotNone(canvas.getbbox(), sid)
        # Copied mechanics cannot select the old owner's material.
        key = arena_skills.skill_of(134)['id']
        with patch.object(family_vfx, 'draw', wraps=family_vfx.draw) as draw:
            retro_native.draw(Image.new('RGBA', (960, 640)), 'arena_' + key,
                              (240, 360), (240, 360), 'windup', .5, CONFIG, species_id=134)
            self.assertEqual(draw.call_args.args[1], 134)

    def test_hoenn_outcomes_use_verified_parent_cast_identity(self):
        for sid in (257, 260, 272, 282, 350, 376):
            anim = make_preview_scene(sid, 'cast')
            packets = [e for e in anim.events if e[1] == 'skill_effect' and e[2] == 0]
            self.assertTrue(packets, sid)
            for event in packets:
                owner = anim.events[event[6]['cast_index']]
                self.assertEqual(retro_native.effect_key(event, anim.events), owner[4][6:])
                wrong_source = (*event[:2], 999, *event[3:])
                self.assertIsNone(retro_native.effect_key(wrong_source, anim.events))
                wrong_key = (*event[:4], 'unrelated-mechanic', *event[5:])
                self.assertIsNone(retro_native.effect_key(wrong_key, anim.events))

    def test_real_web_playback_uses_both_tracks_and_seeks_deterministically(self):
        for sid in (1, 67, 130, 134, 135, 254, 257, 260, 282, 350, 373, 376):
            for kind in ('attack', 'cast'):
                with self.subTest(sid=sid, kind=kind):
                    anim = make_preview_scene(sid, kind)
                    events = copy.deepcopy(anim.events)
                    clip = describe_clip(anim, kind)
                    action = clip['action']
                    moment = (action['release'] + action['impact']) / 2
                    renderer = make_renderer(anim)
                    with patch.object(family_vfx, 'draw', wraps=family_vfx.draw) as draw:
                        first = renderer.frame(moment).tobytes()
                        self.assertTrue(any(c.args[1] == sid and c.kwargs.get('kind', 'cast') == kind
                                            for c in draw.call_args_list))
                    renderer.frame(action['impact'] + .35)
                    self.assertEqual(renderer.frame(moment).tobytes(), first)
                    self.assertEqual(anim.events, events)

    def test_catalog_keeps_body_and_visual_completion_separate(self):
        rows = character_catalog(mode='arena')
        for sid in family_vfx.SPECIES:
            entry = rows[str(sid)]
            self.assertTrue(entry['attack_presentation']['authored'])
            self.assertTrue(entry['skill']['presentation']['authored'])
            self.assertFalse(entry['rig']['implemented'])
            self.assertEqual(entry['capabilities']['parts'], 'none')

    def test_enemy_native_contact_requires_actual_hp_damage(self):
        anim = make_preview_scene(257, 'cast')
        action = describe_clip(anim, 'cast')['action']
        renderer = make_renderer(anim).renderer
        moment = action['impact'] + .06
        renderer.frame(moment)
        with patch.object(renderer, '_damaging_impact', return_value=False), \
                patch.object(family_vfx, 'draw', wraps=family_vfx.draw) as draw:
            renderer._draw_actions(Image.new('RGBA', (960, 640)), moment)
            self.assertFalse(any(call.args[1] == 257 and call.args[4] in ('impact', 'aftermath')
                                 for call in draw.call_args_list))


if __name__ == '__main__':
    unittest.main()
