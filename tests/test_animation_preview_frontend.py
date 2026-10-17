"""Execute current and classic preview players and the actual authoring controls."""
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')


@unittest.skipUnless(NODE, 'Node.js is required to execute frontend handlers')
class AnimationPreviewFrontend(unittest.TestCase):
    def run_scenario(self, name):
        result = subprocess.run(
            [NODE, str(ROOT / 'tests/frontend/animation_preview_frontend.js'), name],
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f'OK animation {name}', result.stdout)

    def test_paired_frames_are_painted_together_and_shared_urls_decode_once(self):
        self.run_scenario('paired')

    def test_desktop_and_mobile_forward_playback_have_bounded_caches(self):
        self.run_scenario('rollingCache')

    def test_missing_distant_seek_does_not_create_prefetch_loops(self):
        self.run_scenario('failedSeek')

    def test_first_frame_and_seek_failures_recover_on_explicit_retry(self):
        self.run_scenario('failure')

    def test_pause_during_buffering_prevents_automatic_frame_advancement(self):
        self.run_scenario('bufferPause')

    def test_cancelled_image_and_timeout_callbacks_cannot_modify_the_new_result(self):
        self.run_scenario('stale')

    def test_mode_validation_classic_smoothing_and_old_preset_compatibility(self):
        self.run_scenario('modes')

    def test_lab_respects_query_and_modes_and_only_renders_one_selected_action(self):
        self.run_scenario('lab')

    def test_assistance_preview_has_effect_phase_and_actual_shield_energy_snapshots(self):
        self.run_scenario('assistIdentity')

    def test_lab_body_view_requests_samples_and_falls_back_for_classic(self):
        self.run_scenario('bodyView')

    def test_editor_view_switch_cannot_pair_old_frames_with_new_selection(self):
        self.run_scenario('editorBodyView')

    def test_lab_cancel_ignores_late_response_and_recovers(self):
        self.run_scenario('labCancellation')

    def test_editor_applied_values_and_old_preset_mode_use_the_actual_controls(self):
        self.run_scenario('editorPresets')

    def test_editor_first_frame_failure_cancel_and_retry_keep_the_last_success_playable(self):
        self.run_scenario('editorRecovery')

    def test_editor_cross_mode_import_catalog_failure_retries_the_current_mode(self):
        self.run_scenario('editorCatalogFailure')

    def test_editor_successful_replacement_preserves_the_selected_playback_speed(self):
        self.run_scenario('editorSpeed')

    def test_editor_does_not_overwrite_edits_made_during_import(self):
        self.run_scenario('editorImportRace')

    def test_lab_legacy_actor_art_url_loads_baseline_from_real_html(self):
        self.run_scenario('labLegacyActorArtURL')

    def test_editor_legacy_actor_art_url_loads_baseline_from_real_html(self):
        self.run_scenario('editorLegacyActorArtURL')


if __name__ == '__main__':
    unittest.main()
