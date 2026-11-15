"""Action feedback layer: node scenarios + served assets."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class PlayFeedbackTest(unittest.TestCase):
    def test_every_action_leaves_a_visible_trace(self):
        result = subprocess.run(['node', str(ROOT / 'tests' / 'frontend' / 'play_feedback.js')],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('play_feedback: ok', result.stdout)

    def test_page_loads_feedback_assets_and_hooks(self):
        html = (ROOT / 'tools' / 'acceptance' / 'play.html').read_text()
        self.assertIn('/play/assets/play_feedback.js', html)
        self.assertIn('/play/assets/play_feedback.css', html)
        server = (ROOT / 'tools' / 'acceptance' / 'server.py').read_text()
        self.assertIn('"/play/assets/play_feedback.js"', server)
        play = (ROOT / 'tools' / 'acceptance' / 'play.js').read_text()
        self.assertIn('PlayFeedback?.before(cmd, params, state)', play)
        self.assertIn('PlayFeedback.after(feedback', play)
        self.assertIn('PlayFeedback?.selection(', play)


if __name__ == '__main__':
    unittest.main()
