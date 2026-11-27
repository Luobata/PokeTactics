"""Phone UX layer and overlay stack (docs/74, reports/mobile-ux-audit-2026-11-27.md)."""
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = ROOT / 'tools/acceptance'
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_play_layout import NODE, PLAYWRIGHT_NODE_PATH  # noqa: E402


class PlayPhoneStatic(unittest.TestCase):
    def test_stylesheets_keep_the_cascade_order_of_the_split(self):
        html = (ACCEPTANCE / 'play.html').read_text()
        order = [html.index(f'/play/assets/{name}') for name in (
            'play_tokens.css', 'play.css', 'play_layout.css', 'play_layout_phone.css', 'play_interactions.css',
            'play_mobile.css', 'play_phone.css')]
        self.assertEqual(order, sorted(order), 'tokens first, phone layout right after the layout, phone UX last')
        self.assertLess(html.index('play_overlay.js'), html.index('play_mobile.js'))
        self.assertLess(html.index('play_phone.js'), html.index('play.js"'))

    def test_phone_layout_rules_all_live_in_the_phone_files(self):
        layout = (ACCEPTANCE / 'play_layout.css').read_text()
        phone = (ACCEPTANCE / 'play_layout_phone.css').read_text()
        self.assertIn('.stage-ui.layout-phone .stage-drawer', phone)
        self.assertNotIn('/* ------------------------------------------------------------- phone */', layout)
        self.assertNotIn('battle dialog on phones', layout)

    def test_stacking_order_is_named_in_the_tokens(self):
        tokens = (ACCEPTANCE / 'play_tokens.css').read_text()
        for name in ('--z-sheet', '--z-dock', '--z-menu', '--z-ctx', '--z-toast', '--z-drag', '--touch-min', '--fs-xs'):
            self.assertIn(name + ':', tokens)
        for name, token in (('play_context.css', '--z-ctx'), ('play_select.css', '--z-select'),
                            ('play_layout_phone.css', '--z-sheet'), ('play_phone.css', '--z-menu')):
            self.assertIn(f'var({token}', (ACCEPTANCE / name).read_text(), name)

    def test_menu_rows_proxy_real_buttons(self):
        html = (ACCEPTANCE / 'play.html').read_text()
        import re
        for target in re.findall(r'data-menu-proxy="([^"]+)"', html):
            self.assertIn(f'id="{target}"', html, target)


@unittest.skipUnless(NODE, 'Node.js is needed to run the overlay stack')
class PlayOverlayStack(unittest.TestCase):
    def run_scenario(self, scenario):
        result = subprocess.run([NODE, str(ROOT / 'tests/frontend/play_overlay.js'), str(ACCEPTANCE), scenario],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_back_closes_the_topmost_layer_first(self):
        self.run_scenario('orderTopFirst')

    def test_a_modal_dialog_hides_the_layers_below_it(self):
        self.run_scenario('modalHidesWhatIsBelow')

    def test_back_never_closes_the_battle(self):
        self.run_scenario('battleIsNeverClosedByBack')

    def test_escape_uses_the_same_stack(self):
        self.run_scenario('escapeUsesTheSameStack')

    def test_later_buttons_and_registered_layers(self):
        self.run_scenario('laterButtonsAndRegister')

    def test_desktop_drawer_is_not_an_overlay(self):
        self.run_scenario('desktopDrawerIsNotAnOverlay')


@unittest.skipUnless(PLAYWRIGHT_NODE_PATH is not None,
                     'needs Node.js + playwright (set POKETACTICS_PLAYWRIGHT_NODE_PATH to its node_modules)')
class PlayPhoneFlow(unittest.TestCase):
    """390x844 and 360x740 with touch, plus 1280x760 desktop, in Chromium."""

    def test_phone_flow_and_desktop_untouched(self):
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
                    [NODE, str(ROOT / 'tests/frontend/play_phone_flow.js'), base],
                    env={**os.environ, 'NODE_PATH': PLAYWRIGHT_NODE_PATH},
                    capture_output=True, text=True, timeout=240)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            finally:
                server.terminate()
                server.wait(timeout=10)


if __name__ == '__main__':
    unittest.main()
