"""Phone preview / installable app (docs/72): manifest, Service Worker, icons, HTTPS,
the phone layer in the page, the preview scripts and the real-device E2E helpers."""
import json
import os
import re
import shutil
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = ROOT / 'tools/acceptance'
PREVIEW = ROOT / 'tools/preview'
NODE = shutil.which('node')
OPENSSL = shutil.which('openssl')
sys.path.insert(0, str(ACCEPTANCE))


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def png_size(data):
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    return struct.unpack('>II', data[16:24])


class Server:
    """The real acceptance server in a subprocess (optionally with HTTPS)."""

    def __init__(self, *extra):
        self.port = free_port()
        self.saves = tempfile.TemporaryDirectory()
        self.proc = subprocess.Popen(
            [sys.executable, str(ACCEPTANCE / 'server.py'), '--port', str(self.port), *extra],
            env={**os.environ, 'POKETACTICS_SAVE_DIR': self.saves.name},
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        for _ in range(150):
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{self.port}/play/manifest.webmanifest', timeout=2):
                    return
            except OSError:
                time.sleep(0.2)
        self.close()
        raise AssertionError('acceptance server did not start')

    def get(self, path):
        with urllib.request.urlopen(f'http://127.0.0.1:{self.port}{path}', timeout=10) as response:
            return response.status, dict(response.headers), response.read()

    def close(self):
        self.proc.terminate()
        self.proc.wait(timeout=10)
        self.proc.stderr.close()
        self.saves.cleanup()


class InstallableAppRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = Server()

    @classmethod
    def tearDownClass(cls):
        cls.server.close()

    def test_manifest_opens_fullscreen_in_any_orientation_with_installable_icons(self):
        status, headers, body = self.server.get('/play/manifest.webmanifest')
        self.assertEqual(status, 200)
        self.assertTrue(headers['Content-Type'].startswith('application/manifest+json'))
        manifest = json.loads(body)
        self.assertEqual(manifest['display'], 'fullscreen')
        self.assertEqual(manifest['display_override'][:2], ['fullscreen', 'standalone'])
        self.assertEqual(manifest['orientation'], 'any', 'portrait and landscape both supported')
        self.assertEqual(manifest['start_url'], '/play?source=pwa')
        self.assertEqual(manifest['scope'], '/play')
        self.assertTrue(manifest['name'] and manifest['short_name'])
        sizes = {}
        for icon in manifest['icons']:
            status, headers, data = self.server.get(icon['src'])
            self.assertEqual((status, headers['Content-Type']), (200, 'image/png'), icon['src'])
            width, height = png_size(data)
            self.assertEqual(f'{width}x{height}', icon['sizes'], icon['src'])
            sizes.setdefault(icon['purpose'], set()).add(width)
        self.assertLessEqual({192, 512}, sizes['any'], 'Chrome needs 192 and 512 px icons')
        self.assertIn(512, sizes['maskable'], 'Android adaptive icon')

    def test_apple_touch_icon_and_favicon(self):
        for path in ('/play/icons/apple-touch-icon.png', '/apple-touch-icon.png',
                     '/apple-touch-icon-precomposed.png', '/favicon.ico'):
            status, headers, data = self.server.get(path)
            self.assertEqual((status, headers['Content-Type']), (200, 'image/png'), path)
        self.assertEqual(png_size(self.server.get('/apple-touch-icon.png')[2]), (180, 180))
        with self.assertRaises(urllib.error.HTTPError) as missing:
            self.server.get('/play/icons/../server.py')
        self.assertEqual(missing.exception.code, 404)
        missing.exception.close()

    def test_service_worker_is_versioned_and_precaches_only_static_files(self):
        import server
        status, headers, body = self.server.get('/play/sw.js')
        self.assertEqual(status, 200)
        self.assertEqual(headers['Service-Worker-Allowed'], '/play', 'a worker under /play/ controls /play')
        self.assertEqual(headers['Cache-Control'], 'no-cache', 'browsers must see new versions')
        text = body.decode()
        self.assertNotIn('"version": "dev"', text)
        self.assertNotIn('__PT_CONFIG__', text, 'the placeholder is replaced')
        config = json.loads(re.search(r'^const CONFIG = (\{.*\});$', text, re.M).group(1))
        self.assertRegex(config['version'], r'^[0-9a-f]{12}$')
        self.assertRegex(config['media'], r'^[0-9a-f]{12}$|^none$')
        self.assertEqual(set(config['precache']) - {'/play/manifest.webmanifest'} - {
            f'/play/icons/{name}' for name in server.PWA_ICONS}, set(server.PLAY_ASSETS))
        self.assertIn('/play/assets/play_mobile.js', config['precache'])
        self.assertFalse([url for url in config['precache'] if url.startswith('/api/')], 'API is never cached')
        for url in config['precache']:
            self.assertEqual(self.server.get(url)[0], 200, url)

    def test_play_page_links_the_app_shell_and_phone_controls(self):
        status, headers, body = self.server.get('/play')
        html = body.decode()
        sw = self.server.get('/play/sw.js')[2].decode()
        self.assertIn(f'"version": "{headers["X-PT-Shell-Version"]}"', sw, 'page and worker agree on the shell version')
        for needle in ('rel="manifest" href="/play/manifest.webmanifest"', 'rel="apple-touch-icon"',
                       'name="apple-mobile-web-app-capable"', 'viewport-fit=cover',
                       '/play/assets/play_mobile.js', '/play/assets/play_mobile.css',
                       'id="vibrate-button"', 'id="install-button"'):
            self.assertIn(needle, html)

    def test_preview_ca_is_only_served_when_configured(self):
        with self.assertRaises(urllib.error.HTTPError) as missing:
            self.server.get('/ca.crt')
        self.assertEqual(missing.exception.code, 404)
        missing.exception.close()


class ServiceWorkerVersion(unittest.TestCase):
    def test_any_shell_change_changes_the_version_and_media_follows_the_sprite_index(self):
        import server
        with tempfile.TemporaryDirectory() as tmp:
            files = [Path(tmp) / f'f{i}.js' for i in range(3)]
            for f in files:
                f.write_text('a')
            original = server._shell_files
            server._shell_files = lambda: files
            server._SW_VERSION.clear()
            try:
                first = server.service_worker_config()['version']
                self.assertEqual(server.service_worker_config()['version'], first, 'stable while unchanged')
                time.sleep(0.01)
                files[1].write_text('b')
                os.utime(files[1], ns=(time.time_ns() + 10**9,) * 2)
                self.assertNotEqual(server.service_worker_config()['version'], first, 'edit -> new version')
            finally:
                server._shell_files = original
                server._SW_VERSION.clear()
        source = server.service_worker_source()
        self.assertIn('"precache": ["/play/assets/', source)
        self.assertNotIn('__PT_CONFIG__', source, 'the placeholder is replaced')


@unittest.skipUnless(OPENSSL, 'openssl is needed to issue a test certificate')
class HttpsListener(unittest.TestCase):
    def test_https_port_serves_the_app_with_the_preview_ca_and_survives_bad_handshakes(self):
        with tempfile.TemporaryDirectory() as tmp:
            certs = Path(tmp) / 'certs'
            out = subprocess.run(['bash', str(PREVIEW / 'make_cert.sh'), str(certs), '127.0.0.1', 'localhost'],
                                 capture_output=True, text=True, timeout=60)
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
            constraints = subprocess.run(['openssl', 'x509', '-in', str(certs / 'ca.crt'), '-noout', '-ext',
                                          'nameConstraints,basicConstraints'], capture_output=True, text=True).stdout
            self.assertIn('critical', constraints)
            self.assertIn('IP:127.0.0.1/255.255.255.255', constraints, 'CA only vouches for the preview host')
            self.assertIn('DNS:localhost', constraints)
            self.assertIn('CA:TRUE', constraints)
            self.assertEqual(oct((certs / 'ca.key').stat().st_mode & 0o777), '0o600', 'CA key stays private')
            tls_port = free_port()
            server = Server('--tls-port', str(tls_port), '--tls-cert', str(certs / 'server-chain.crt'),
                            '--tls-key', str(certs / 'server.key'), '--ca-cert', str(certs / 'ca.crt'))
            try:
                context = ssl.create_default_context(cafile=str(certs / 'ca.crt'))
                # A client that does not trust the CA yet (a phone before setup) must not hurt the server.
                with socket.create_connection(('127.0.0.1', tls_port), timeout=5) as raw:
                    raw.sendall(b'GET / HTTP/1.0\r\n\r\n')
                with self.assertRaises((ssl.SSLError, urllib.error.URLError)):
                    urllib.request.urlopen(f'https://127.0.0.1:{tls_port}/play', timeout=10,
                                           context=ssl.create_default_context())
                for path in ('/play', '/play/sw.js', '/play/manifest.webmanifest', '/api/pmd/manifest?species=25'):
                    with urllib.request.urlopen(f'https://127.0.0.1:{tls_port}{path}', timeout=20,
                                                context=context) as response:
                        self.assertEqual(response.status, 200, path)
                status, headers, body = server.get('/ca.crt')
                self.assertEqual(headers['Content-Type'], 'application/x-x509-ca-cert')
                self.assertEqual(body, (certs / 'ca.crt').read_bytes())
                self.assertNotIn(b'PRIVATE KEY', body)
                # Re-running keeps the CA a phone already trusts and re-issues the leaf.
                before = (certs / 'ca.crt').read_bytes()
                subprocess.run(['bash', str(PREVIEW / 'make_cert.sh'), str(certs), '127.0.0.1'],
                               capture_output=True, timeout=60, check=True)
                self.assertEqual((certs / 'ca.crt').read_bytes(), before)
            finally:
                server.close()

    def test_tls_port_requires_a_certificate(self):
        result = subprocess.run([sys.executable, str(ACCEPTANCE / 'server.py'), '--tls-port', '9'],
                                capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('--tls-cert', result.stderr)


@unittest.skipUnless(NODE, 'Node.js is needed to run the phone layer')
class PhoneLayer(unittest.TestCase):
    def run_scenario(self, scenario):
        result = subprocess.run([NODE, str(ROOT / 'tests/frontend/play_mobile.js'), str(ACCEPTANCE), scenario],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_vibration_follows_battle_cues_and_the_hud_switch(self):
        self.run_scenario('vibration')

    def test_android_shell_back_hook_native_vibration_and_autoplay(self):
        self.run_scenario('shellBack')

    def test_wake_lock_is_held_only_while_the_battle_is_open(self):
        self.run_scenario('wakeLock')

    def test_worker_registration_install_button_and_display_mode(self):
        self.run_scenario('install')

    def test_service_worker_caches_static_files_and_never_the_api(self):
        self.run_scenario('serviceWorkerRoutes')

    def test_service_worker_versions_replace_old_caches_and_serve_offline_shell(self):
        self.run_scenario('serviceWorkerLifecycle')

    def test_an_outdated_worker_never_mixes_new_html_with_cached_old_scripts(self):
        self.run_scenario('serviceWorkerHandoff')

    def test_renderer_emits_cues_only_for_forward_playback(self):
        self.run_scenario('battleCues')


class PreviewScripts(unittest.TestCase):
    def test_shell_scripts_parse(self):
        for name in ('install.sh', 'run.sh', 'update.sh', 'make_cert.sh'):
            result = subprocess.run(['bash', '-n', str(PREVIEW / name)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, name + result.stderr)
            self.assertTrue(os.access(PREVIEW / name, os.X_OK), f'{name} is executable')

    def test_launcher_only_enables_https_on_servers_that_support_it(self):
        run = (PREVIEW / 'run.sh').read_text()
        self.assertIn("grep -q -- '--tls-port' tools/acceptance/server.py", run)
        self.assertIn('POKETACTICS_SAVE_DIR="$PREVIEW_SAVE_DIR"', run, 'saves live outside the worktree')
        install = (PREVIEW / 'install.sh').read_text()
        for needle in ('Restart=always', 'WantedBy=default.target', 'OnUnitActiveSec=2min', '--detach',
                       'port_owner'):
            self.assertIn(needle, install)
        update = (PREVIEW / 'update.sh').read_text()
        self.assertIn('git diff --quiet', update, 'never discards edits in the preview worktree')
        self.assertIn('merge-base --is-ancestor', update)

    def test_updater_follows_main_and_restarts_only_on_change(self):
        """update.sh against a throwaway repo: new commit -> checkout + restart; no change -> nothing."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            git = lambda *a, cwd=tmp / 'origin': subprocess.run(['git', *a], cwd=cwd, check=True,
                                                                 capture_output=True, text=True).stdout.strip()
            (tmp / 'origin').mkdir()
            git('init', '-q', '-b', 'main')
            git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'one')
            git('clone', '-q', str(tmp / 'origin'), str(tmp / 'clone'), cwd=tmp)
            git('worktree', 'add', '-q', '--detach', str(tmp / 'preview'), 'origin/main', cwd=tmp / 'clone')
            bin_dir = tmp / 'bin'
            bin_dir.mkdir()
            (bin_dir / 'systemctl').write_text(f'#!/bin/sh\necho "$@" >> {tmp / "restarts"}\n')
            (bin_dir / 'systemctl').chmod(0o755)
            env_file = tmp / 'env'
            env_file.write_text(f'PREVIEW_WORKTREE={tmp / "preview"}\nPREVIEW_BRANCH=main\n')
            env = {**os.environ, 'PATH': f'{bin_dir}:{os.environ["PATH"]}', 'POKETACTICS_PREVIEW_ENV': str(env_file)}
            run = lambda: subprocess.run(['bash', str(PREVIEW / 'update.sh')], env=env, capture_output=True, text=True)
            self.assertEqual(run().returncode, 0)
            self.assertFalse((tmp / 'restarts').exists(), 'no restart without a new commit')
            git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'two')
            result = run()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('preview updated', result.stdout)
            self.assertEqual(git('rev-parse', 'HEAD', cwd=tmp / 'preview'), git('rev-parse', 'HEAD'))
            self.assertIn('restart poketactics-preview.service', (tmp / 'restarts').read_text())
            (tmp / 'preview' / 'local.txt').write_text('x')
            git('add', 'local.txt', cwd=tmp / 'preview')
            git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'three')
            self.assertNotEqual(run().returncode, 0, 'refuses to update over local edits')


class AndroidE2EHelpers(unittest.TestCase):
    """Pure parts of tools/acceptance/android_e2e.py (the device run itself needs a phone)."""

    def test_view_dump_parser_turns_relative_bounds_into_screen_positions(self):
        import android_e2e
        dump = '''TASK 1
  ACTIVITY com.android.chrome/org.chromium.chrome.browser.ChromeTabbedActivity 1 pid=1
    View Hierarchy:
      com.android.internal.policy.DecorView{1 V.E...... R....... 0,0-1080,2424}
        android.widget.FrameLayout{2 V.E...... ........ 27,717-1053,1281 #7f01 app:id/modal_dialog_view}
          android.widget.LinearLayout{3 V.E...... ........ 0,1000-1026,1200}
            org.chromium.ui.widget.ButtonCompat{4 VFED..C.. ........ 753,42-984,168 #7f02 app:id/positive_button}
            org.chromium.ui.widget.ButtonCompat{5 GFED..C.. ........ 501,42-732,168 #7f03 app:id/negative_button}
  ACTIVITY com.example/.Other 2 pid=2
            org.chromium.ui.widget.ButtonCompat{6 VFED..C.. ........ 1,1-2,2 #7f02 app:id/positive_button}
'''
        adb = android_e2e.Adb.__new__(android_e2e.Adb)
        adb.shell = lambda *a, **k: dump
        self.assertEqual(adb.find_view('app:id/positive_button'), (27 + 753 + 115, 717 + 1000 + 42 + 63))
        self.assertIsNone(adb.find_view('app:id/negative_button'), 'gone views are skipped')
        self.assertEqual(adb.find_view('app:id/modal_dialog_view', child=-1), (27 + 513, 717 + 1100))


if __name__ == '__main__':
    unittest.main()
