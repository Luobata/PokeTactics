"""Real replay UI handlers keep downloaded, current, and final states separate."""
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')


@unittest.skipUnless(NODE, 'Node.js is needed to execute the play-page handlers')
class BattlePlaybackPresentation(unittest.TestCase):
    def run_scenario(self, scenario):
        result = subprocess.run(
            [NODE, str(ROOT / 'tests/frontend/battle_playback_presentation.js'),
             str(ROOT / 'tools/acceptance/play.js'),
             str(ROOT / 'tools/acceptance/play.html'), scenario],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f'OK playback {scenario}', result.stdout,
                      'The replay scenario did not reach its final assertion.')

    def test_pause_speed_and_cached_scrubbing_use_the_real_controls(self):
        self.run_scenario('controls')

    def test_out_of_order_preloads_and_pending_seeks_never_advance_the_scoreboard(self):
        self.run_scenario('progressive')

    def test_continuous_forward_playback_keeps_desktop_and_mobile_caches_bounded_without_refetch_loops(self):
        self.run_scenario('rollingCache')

    def test_end_statistics_hide_again_on_scrub_and_replay_without_mutation(self):
        self.run_scenario('ending')

    def test_missing_frame_auto_retries_twice_before_offering_explicit_retry(self):
        self.run_scenario('failure')

    def test_transient_frame_failure_recovers_without_manual_retry(self):
        self.run_scenario('autoRetryRecovery')

    def test_failed_prefetch_auto_retries_and_playback_crosses_the_recovered_frame(self):
        self.run_scenario('midstreamFailure')

    def test_explicit_view_result_survives_a_missing_final_image_without_advancing_the_current_frame(self):
        self.run_scenario('explicitFailureResult')

    def test_close_and_reopen_ignore_stale_image_and_timeout_callbacks(self):
        self.run_scenario('staleLoads')

    def test_rendering_rounds_poll_progress_and_recover_when_ready(self):
        self.run_scenario('renderStatus')

    def test_dead_render_falls_back_to_saved_result_without_recalculating(self):
        self.run_scenario('renderDead')

    def test_manual_render_retry_extends_the_no_progress_deadline(self):
        self.run_scenario('renderRetryDeadline')

    def test_render_status_polling_has_a_bounded_failure_state(self):
        self.run_scenario('statusTimeout')

    def test_mutation_timeout_releases_busy_and_requires_resume_without_resending(self):
        self.run_scenario('mutationTimeout')

    def test_restored_reports_without_frames_still_show_saved_statistics(self):
        self.run_scenario('restored')


if __name__ == '__main__':
    unittest.main()
