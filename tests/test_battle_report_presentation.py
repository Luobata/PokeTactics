"""Real play-page handlers present saved statistics without touching a session."""
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')


@unittest.skipUnless(NODE, 'Node.js is needed to execute the play-page handlers')
class BattleReportPresentation(unittest.TestCase):
    def run_scenario(self, scenario):
        result = subprocess.run(
            [NODE, str(ROOT / 'tests/frontend/battle_report_presentation.js'),
             str(ROOT / 'tools/acceptance/play.js'),
             str(ROOT / 'tools/acceptance/play.html'), scenario],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_component_choices_bond_candidates_and_formation_stages(self):
        result = subprocess.run(
            [NODE, str(ROOT / 'tests/frontend/arena_formation_presentation.js'),
             str(ROOT / 'tools/acceptance/play.js'), str(ROOT / 'tools/acceptance/play.html')],
            capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_shop_cards_preview_before_recruiting_and_keep_selection_exclusive(self):
        result = subprocess.run(
            [NODE, str(ROOT / 'tests/frontend/shop_preview_presentation.js'),
             str(ROOT / 'tools/acceptance/play.js'), str(ROOT / 'tools/acceptance/play.html')],
            capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_attack_route_counts_show_actual_events_without_estimated_damage(self):
        self.run_scenario('attackBranches')

    def test_new_combo_metrics_distinguish_extra_damage_from_shields_and_preserve_legacy(self):
        self.run_scenario('comboBranches')

    def test_traits_and_gear_keep_real_healing_mitigation_and_physical_scope_separate(self):
        self.run_scenario('traitsGear')

    def test_contributions_switch_teams_sort_metrics_and_include_dead_units(self):
        self.run_scenario('metrics')

    def test_all_history_rounds_are_read_only_and_survive_resume_and_refresh(self):
        self.run_scenario('history')

    def test_history_controls_do_not_change_current_playback_or_current_statistics(self):
        self.run_scenario('playback')

    def test_empty_history_distinguishes_new_games_from_completed_legacy_rounds(self):
        self.run_scenario('emptyHistory')

    def test_old_reports_never_fabricate_zeros_but_new_empty_battles_show_zero_totals(self):
        self.run_scenario('missing')

    def test_verdict_and_history_panels_list_lit_bonds_and_nearest_misses(self):
        self.run_scenario('bondSpark')

    def test_family_reports_deduplicate_forms_and_count_evolved_branch_types(self):
        self.run_scenario('familyBondSpark')

    def test_empty_combination_state_gives_actionable_bond_guidance(self):
        self.run_scenario('comboGuidance')

    def test_last_result_entry_reopens_latest_settled_round_only_when_present(self):
        self.run_scenario('lastResult')

    def run_advice_scenario(self, scenario):
        result = subprocess.run(
            [NODE, str(ROOT / 'tests/frontend/next_advice.js'),
             str(ROOT / 'tools/acceptance/play.js'),
             str(ROOT / 'tools/acceptance/play.html'), scenario],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_loadout_highlights_and_gear_badges_mark_item_and_technique_sources(self):
        self.run_scenario('loadoutHighlights')

    def test_defeat_advice_cites_elimination_numbers_threat_share_and_loss_streak(self):
        self.run_advice_scenario('defeatAdvice')

    def test_lost_round_advice_cites_mvp_share_zero_healing_and_bond_gap(self):
        self.run_advice_scenario('verdictLossAdvice')

    def test_won_round_advice_consolidates_core_bond_and_win_streak(self):
        self.run_advice_scenario('verdictWinAdvice')

    def test_champion_result_shows_consolidation_without_defeat_lines(self):
        self.run_advice_scenario('championAdvice')

    def test_advice_block_stays_hidden_when_no_data_supports_a_tip(self):
        self.run_advice_scenario('noEmptyAdvice')


if __name__ == '__main__':
    unittest.main()
