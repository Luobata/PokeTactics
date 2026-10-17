"""Contract checks for the unobstructed arena-body preview."""

import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools/acceptance'), str(ROOT / 'tools/mockups'), str(ROOT / 'sim')]
import animation_preview as preview
from arena_preview_scene import make_preview_scene
from action_preview import describe_clip
from presentation_modes import make_renderer


class BodyPreviewContracts(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        change = patch.object(preview, 'CACHE_ROOT', self.root)
        change.start()
        self.addCleanup(change.stop)

    def test_view_normalization_preserves_composite_and_restricts_body_to_arena(self):
        request = {'species': 212, 'kind': 'cast'}
        default = preview.normalize_preview(request)
        explicit = preview.normalize_preview({**request, 'view': 'composite'})
        self.assertEqual(default['view'], 'composite')
        self.assertEqual(explicit, default)
        self.assertEqual(preview._key(default, 'revision'), preview._key(explicit, 'revision'))
        self.assertEqual(preview.normalize_preview({**request, 'view': 'body'})['view'], 'body')
        for value in ({'view': 'classic', 'mode': 'classic', 'species': 19},
                      {'view': 'body', 'mode': 'classic', 'species': 19},
                      {'view': 'unknown', 'species': 212},
                      {'view': None, 'species': 212}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                preview.normalize_preview(value)

    def test_body_preview_keeps_real_clip_and_hp_while_separating_cache(self):
        composite = preview.preview({'species': 6, 'kind': 'cast'})
        body = preview.preview({'species': 6, 'kind': 'cast', 'view': 'body'})
        self.assertEqual(composite['view'], 'composite')
        self.assertEqual(body['view'], 'body')
        self.assertEqual(body['body_preview'], {
            'unit': 0, 'scale': 4, 'camera': 'follow_cell', 'external_effects': False})
        self.assertEqual(body['dimensions'], {'width': 960, 'height': 640})
        self.assertNotEqual(composite['key'], body['key'])
        self.assertNotEqual(composite['base_key'], body['base_key'])
        for key in ('kind', 'action', 'source_index', 'clip_start', 'clip_end', 'n', 'dt',
                    'phases', 'target_before_impact', 'target_at_impact'):
            self.assertEqual(composite[key], body[key], key)
        with Image.open(self.root / body['key'] / '0.png') as frame:
            self.assertEqual(frame.size, (960, 640))
        with patch('arena_preview_scene.make_preview_scene',
                   side_effect=AssertionError('cached preview must reuse the same fixture')):
            self.assertEqual(preview.preview({'species': 6, 'kind': 'cast'})['key'], composite['key'])
            self.assertEqual(preview.preview({'species': 6, 'kind': 'cast', 'view': 'body'})['key'], body['key'])

    def test_body_renderer_renders_move_and_exit_samples_from_real_events(self):
        for kind in ('move', 'death'):
            with self.subTest(kind=kind):
                anim = make_preview_scene(68 if kind == 'move' else 6, kind)
                clip = describe_clip(anim, kind)
                renderer = make_renderer(anim)
                original_events = copy.deepcopy(anim.events)
                before = renderer.body_frame(clip['clip_start'], unit_idx=0)
                changed = renderer.body_frame(clip['phases'][-1]['at'], unit_idx=0)
                self.assertEqual(before.size, (960, 640))
                self.assertEqual(changed.size, (960, 640))
                self.assertIsNotNone(before.convert('RGB').getbbox())
                self.assertIsNotNone(changed.convert('RGB').getbbox())
                self.assertNotEqual(before.tobytes(), changed.tobytes())
                self.assertEqual(anim.events, original_events)

    def test_body_renderer_reuses_selected_art_without_external_layers_and_seeks_cleanly(self):
        anim = make_preview_scene(6, 'cast')
        action = describe_clip(anim, 'cast')['action']
        moment = action['release'] + .05
        full = make_renderer(make_preview_scene(6, 'cast'))
        body = make_renderer(anim)
        original_events = copy.deepcopy(anim.events)

        def spy(renderer):
            calls, original = [], renderer._unit_art
            def sample(au, x, y, seconds):
                value = original(au, x, y, seconds)
                calls.append((au, x, y, seconds, value))
                return value
            return patch.object(renderer, '_unit_art', side_effect=sample), calls

        full_patch, full_calls = spy(full.renderer)
        body_patch, body_calls = spy(body.renderer)
        with full_patch, body_patch:
            full.frame(moment)
            frame = body.body_frame(moment, unit_idx=0)

        self.assertEqual(frame.size, (960, 640))
        self.assertIsNotNone(frame.convert('RGB').getbbox())
        corners = ((0, 0), (959, 0), (0, 639), (959, 639))
        colors = {tuple(frame.getpixel(point)[:3]) for point in corners}
        self.assertEqual(len(colors), 1)
        self.assertTrue(all(180 <= channel <= 255 for channel in next(iter(colors))))
        selected_full = next(call for call in full_calls if call[0].u.idx == 0)
        self.assertEqual(len(body_calls), 1)
        body_au, body_x, body_y, body_t, body_art = body_calls[0]
        _, full_x, full_y, full_t, full_art = selected_full
        self.assertEqual((body_au.u.idx, body_t), (0, full_t))
        self.assertEqual(body_art[0].tobytes(), full_art[0].tobytes())
        self.assertAlmostEqual(body_art[1]-body_x, full_art[1]-full_x, delta=1)
        self.assertAlmostEqual(body_art[2]-body_y, full_art[2]-full_y, delta=1)
        self.assertEqual(set(body_art[3]), set(full_art[3]))
        for key in body_art[3]:
            body_point = body_art[3][key]
            full_point = full_art[3][key]
            self.assertAlmostEqual(body_point[0]-body_x, full_point[0]-full_x, delta=1, msg=key)
            self.assertAlmostEqual(body_point[1]-body_y, full_point[1]-full_y, delta=1, msg=key)

        forbidden = {name: patch.object(body.renderer, name,
                                         side_effect=AssertionError(name + ' must not run'))
                     for name in ('_draw_actions', '_draw_outcomes', '_draw_terrain',
                                  '_draw_weather', '_draw_ambient', '_draw_hud',
                                  '_draw_ult_overlay', '_draw_energy_halo',
                                  '_draw_persistent_accent')}
        for active in forbidden.values():
            active.start()
        try:
            body.body_frame(moment, unit_idx=0)
        finally:
            for active in forbidden.values():
                active.stop()

        first = body.body_frame(moment, unit_idx=0).tobytes()
        body.body_frame(anim.timeline.duration, unit_idx=0)
        self.assertEqual(body.body_frame(moment, unit_idx=0).tobytes(), first)
        self.assertEqual(anim.events, original_events)


if __name__ == '__main__':
    unittest.main()
