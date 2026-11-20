"""Interaction shortcuts (docs/70): context menu, re-click deselect, previews / glossary, first-run guide."""
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')
ACCEPTANCE = ROOT / 'tools/acceptance'


@unittest.skipUnless(NODE, 'Node.js is needed to execute the play-page handlers')
class PlayContextPresentation(unittest.TestCase):
    def run_scenario(self, scenario):
        result = subprocess.run(
            [NODE, str(ROOT / 'tests/frontend/play_context_presentation.js'), str(ACCEPTANCE),
             str(ACCEPTANCE / 'play.html'), scenario],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unit_menu_deploys_equips_with_the_advisor_pick_first_and_unequips(self):
        self.run_scenario('unitMenu')

    def test_menu_shows_population_and_phase_reasons_instead_of_calling_the_server(self):
        self.run_scenario('populationAndPhase')

    def test_shop_menu_buys_locks_and_explains_missing_gold(self):
        self.run_scenario('shopMenu')

    def test_item_and_machine_menus_equip_dismantle_target_and_learn(self):
        self.run_scenario('itemAndMachineMenus')

    def test_enemy_and_empty_cell_menus_scout_and_place(self):
        self.run_scenario('enemyAndCellMenus')

    def test_menu_is_keyboard_accessible(self):
        self.run_scenario('keyboardMenu')

    def test_touch_long_press_opens_the_menu_and_eats_the_release_click(self):
        self.run_scenario('longPress')

    def test_second_click_deselects_and_double_click_still_acts(self):
        self.run_scenario('reclickDeselect')

    def test_preview_card_glossary_and_selection_info_strip(self):
        self.run_scenario('previewAndGlossary')

    def test_guide_auto_starts_once_and_replays_from_the_help_button(self):
        self.run_scenario('guide')


class PlayContextAssets(unittest.TestCase):
    def test_page_and_server_ship_the_new_assets_before_the_motion_budget(self):
        html = (ACCEPTANCE / 'play.html').read_text(encoding='utf-8')
        server = (ACCEPTANCE / 'server.py').read_text(encoding='utf-8')
        for name in ('play_preview', 'play_context', 'play_guide'):
            for ext in ('js', 'css'):
                self.assertIn(f'/play/assets/{name}.{ext}', html)
                self.assertIn(f'"/play/assets/{name}.{ext}"', server)
            self.assertLess(html.index(f'{name}.css'), html.index('play_motion.css'))
            # Their capture listeners must run before play_interactions' targeting handler.
            self.assertLess(html.index(f'{name}.js'), html.index('play_interactions.js'))
        self.assertIn('id="guide-button"', html)
        self.assertIn('data-guide-start', html)


if __name__ == '__main__':
    unittest.main()
