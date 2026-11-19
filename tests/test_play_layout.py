"""Board-centric prep layout (docs/61): dock, drawer/sheet, badges and board cues."""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')
ACCEPTANCE = ROOT / 'tools/acceptance'


@unittest.skipUnless(NODE, 'Node.js is needed to execute the play-page handlers')
class PlayLayoutPresentation(unittest.TestCase):
    def run_scenario(self, scenario):
        result = subprocess.run(
            [NODE, str(ROOT / 'tests/frontend/play_layout_presentation.js'),
             str(ACCEPTANCE / 'play_layout.js'), str(ACCEPTANCE / 'play.js'),
             str(ACCEPTANCE / 'play.html'), scenario, str(ACCEPTANCE / 'play_depth.js')],
            capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_every_scripted_id_and_legacy_hook_stays_in_the_page(self):
        self.run_scenario('ids')

    def test_desktop_drawer_opens_switches_and_closes_without_server_calls(self):
        self.run_scenario('desktopDrawer')

    def test_dock_badges_count_pending_choices_and_fight_reveals_augments(self):
        self.run_scenario('badges')

    def test_phone_layout_uses_a_peeking_shop_sheet_with_resizable_panels(self):
        self.run_scenario('phoneSheet')

    def test_landscape_phone_uses_side_sheets_and_a_bottom_shop_tray(self):
        self.run_scenario('landscapeSheet')

    def test_contextual_bar_recruits_sells_and_opens_detail_on_the_board(self):
        self.run_scenario('contextBar')

    def test_depth_hud_chips_draft_sheet_and_threat_summary(self):
        self.run_scenario('depthHud')

    def test_selection_highlights_attack_range_and_opening_target_lines(self):
        self.run_scenario('rangeThreat')

    def test_selection_toggles_classes_without_rebuilding_keyed_sections(self):
        self.run_scenario('keyedSelection')

    def test_purchase_renders_optimistically_before_the_server_answers(self):
        self.run_scenario('optimisticBuy')

    def test_rejected_optimistic_actions_roll_back(self):
        self.run_scenario('optimisticRollback')

    def test_legacy_saves_without_depth_render_without_chips_or_threat(self):
        self.run_scenario('legacy')


@unittest.skipUnless(NODE, 'Node.js is needed to execute the play-page handlers')
class PlaySelectPresentation(unittest.TestCase):
    def run_scenario(self, scenario):
        result = subprocess.run(
            [NODE, str(ROOT / 'tests/frontend/play_select_presentation.js'),
             str(ACCEPTANCE / 'play_select.js'), str(ACCEPTANCE / 'play.js'),
             str(ACCEPTANCE / 'play.html'), scenario],
            capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_dropdown_keyboard_typeahead_and_change_event_keep_the_native_select(self):
        self.run_scenario('keyboard')

    def test_dropdown_is_a_bottom_sheet_on_phones(self):
        self.run_scenario('phoneSheet')

    def test_dropdown_follows_options_rebuilt_by_code(self):
        self.run_scenario('dynamicOptions')


def playwright_node_path():
    """A NODE_PATH under which `require('playwright')` resolves, or None (test skips)."""
    if not NODE:
        return None
    candidates = [os.environ.get('POKETACTICS_PLAYWRIGHT_NODE_PATH'), os.environ.get('NODE_PATH'),
                  str(ROOT / 'node_modules'), '']
    for candidate in candidates:
        if candidate is None:
            continue
        env = {**os.environ, 'NODE_PATH': candidate}
        probe = subprocess.run([NODE, '-e', "require.resolve('playwright')"], env=env, capture_output=True)
        if probe.returncode == 0:
            return candidate
    return None


PLAYWRIGHT_NODE_PATH = playwright_node_path()


@unittest.skipUnless(PLAYWRIGHT_NODE_PATH is not None,
                     'needs Node.js + playwright (set POKETACTICS_PLAYWRIGHT_NODE_PATH to its node_modules)')
class PlaySceneGeometry(unittest.TestCase):
    """docs/68: each panel opens next to its dock button and leaves the board usable,
    measured in Chromium at 1440x900, 1280x720, 844x390 (landscape) and 390x844."""

    def test_panels_open_next_to_their_dock_button_and_keep_the_board_usable(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        with tempfile.TemporaryDirectory() as saves:
            server = subprocess.Popen(
                [sys.executable, str(ACCEPTANCE / 'server.py'), '--port', str(port)],
                env={**os.environ, 'POKETACTICS_SAVE_DIR': saves},
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                base = f'http://127.0.0.1:{port}'
                for _ in range(100):
                    try:
                        with urllib.request.urlopen(f'{base}/play', timeout=2) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(0.2)
                else:
                    self.fail('acceptance server did not start')
                result = subprocess.run(
                    [NODE, str(ROOT / 'tests/frontend/play_scene_geometry.js'), base],
                    env={**os.environ, 'NODE_PATH': PLAYWRIGHT_NODE_PATH},
                    capture_output=True, text=True, timeout=180)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            finally:
                server.terminate()
                server.wait(timeout=10)


class PlayLayoutStatic(unittest.TestCase):
    def test_page_and_styles_load_nothing_from_the_network(self):
        for name in ('play.html', 'play.css', 'play_layout.css', 'play_interactions.css', 'play_motion.css', 'play_select.css', 'battle.css'):
            text = (ACCEPTANCE / name).read_text()
            with self.subTest(asset=name):
                self.assertNotIn('fonts.googleapis', text)
                self.assertNotRegex(text, r'(?:src|href)="https?://')
                self.assertNotRegex(text, r'url\(["\']?https?://')

    def test_long_running_loops_only_animate_compositor_properties(self):
        css = (ACCEPTANCE / 'play_motion.css').read_text()
        frames = css.split('@keyframes')[1:]
        self.assertTrue(frames)
        for block in frames:
            body = block[block.index('{'):]
            self.assertNotIn('box-shadow', body)
            self.assertNotIn('background', body)
        html = (ACCEPTANCE / 'play.html').read_text()
        self.assertLess(html.index('play_feedback.css'), html.index('play_motion.css'), 'motion budget loads last')

    def test_mobile_viewport_respects_safe_areas_and_reduced_motion(self):
        html = (ACCEPTANCE / 'play.html').read_text()
        css = (ACCEPTANCE / 'play_layout.css').read_text()
        self.assertIn('viewport-fit=cover', html)
        self.assertIn('env(safe-area-inset-bottom)', css)
        self.assertIn('prefers-reduced-motion', css)
        for terrain in ('highland', 'mana_spring', 'brambles', 'sanctum', 'swamp', 'embers'):
            self.assertIn(f'.tile.terrain-{terrain}', css)


if __name__ == '__main__':
    unittest.main()
