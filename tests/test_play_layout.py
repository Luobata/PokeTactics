"""Board-centric prep layout (docs/61): dock, drawer/sheet, badges and board cues."""
import shutil
import subprocess
import unittest
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

    def test_contextual_bar_recruits_sells_and_opens_detail_on_the_board(self):
        self.run_scenario('contextBar')

    def test_depth_hud_chips_draft_sheet_and_threat_summary(self):
        self.run_scenario('depthHud')

    def test_selection_highlights_attack_range_and_opening_target_lines(self):
        self.run_scenario('rangeThreat')

    def test_legacy_saves_without_depth_render_without_chips_or_threat(self):
        self.run_scenario('legacy')


class PlayLayoutStatic(unittest.TestCase):
    def test_page_and_styles_load_nothing_from_the_network(self):
        for name in ('play.html', 'play.css', 'play_layout.css', 'battle.css'):
            text = (ACCEPTANCE / name).read_text()
            with self.subTest(asset=name):
                self.assertNotIn('fonts.googleapis', text)
                self.assertNotRegex(text, r'(?:src|href)="https?://')
                self.assertNotRegex(text, r'url\(["\']?https?://')

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
