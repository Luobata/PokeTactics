"""Android shell App (docs/73): the APK download page on the preview server, the
preview launcher wiring, and static guarantees of apps/android (back handling, native
settings, no signing secrets in the repository). The real-device run is
tools/android/shell_e2e.py; its evidence is under reports/evidence/."""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_play_mobile import Server  # noqa: E402  (real acceptance server in a subprocess)

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'apps/android'
MAIN = APP / 'app/src/main'
KOTLIN = MAIN / 'java/com/poketactics/shell'


class ApkDownload(unittest.TestCase):
    def test_download_page_and_apk_come_from_the_app_dir(self):
        with tempfile.TemporaryDirectory() as app_dir:
            apk = b'PK\x03\x04' + os.urandom(2048)
            Path(app_dir, 'PokeTactics.apk').write_bytes(apk)
            Path(app_dir, 'PokeTactics.json').write_text(json.dumps({
                'versionName': '1.0.7', 'versionCode': 7, 'commit': 'abc1234', 'defaultUrl': 'https://10.0.0.5:8821/play',
                'builtAt': '2026-11-27 10:00 CST', 'sha256': 'f' * 64, 'certSha256': 'e' * 64}))
            server = Server('--app-dir', app_dir)
            try:
                status, headers, body = server.get('/app')
                page = body.decode()
                self.assertEqual(status, 200)
                self.assertIn('href="/app/PokeTactics.apk"', page)
                for needle in ('1.0.7', 'abc1234', 'https://10.0.0.5:8821/play', '允许来自此来源的应用', '仍然安装'):
                    self.assertIn(needle, page)
                status, headers, body = server.get('/app/PokeTactics.apk')
                self.assertEqual(body, apk)
                self.assertEqual(headers['Content-Type'], 'application/vnd.android.package-archive')
                self.assertIn('attachment; filename="PokeTactics.apk"', headers['Content-Disposition'])
            finally:
                server.close()

    def test_without_an_apk_the_page_says_how_to_build_one(self):
        server = Server()
        try:
            status, _, body = server.get('/app/')
            self.assertEqual(status, 200)
            self.assertIn('tools/android/build.sh', body.decode())
            with self.assertRaises(urllib.error.HTTPError) as missing:
                server.get('/app/PokeTactics.apk')
            self.assertEqual(missing.exception.code, 404)
            missing.exception.close()
        finally:
            server.close()


class PreviewWiring(unittest.TestCase):
    def test_launcher_serves_the_app_dir_only_on_servers_that_know_it(self):
        run = (ROOT / 'tools/preview/run.sh').read_text()
        self.assertIn("grep -q -- '--app-dir' tools/acceptance/server.py", run)
        self.assertIn('--app-dir "$PREVIEW_APP_DIR"', run)
        install = (ROOT / 'tools/preview/install.sh').read_text()
        self.assertIn('PREVIEW_APP_DIR=$PREVIEW_APP_DIR', install, 'written to the env file run.sh reads')

    def test_android_scripts_parse_and_are_executable(self):
        for name in ('build.sh', 'setup_sdk.sh'):
            path = ROOT / 'tools/android' / name
            result = subprocess.run(['bash', '-n', str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, name + result.stderr)
            self.assertTrue(os.access(path, os.X_OK), f'{name} is executable')
        result = subprocess.run([sys.executable, '-m', 'py_compile', str(ROOT / 'tools/android/shell_e2e.py')],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_build_script_keeps_trust_narrow_and_keys_outside_the_repo(self):
        build = (ROOT / 'tools/android/build.sh').read_text()
        self.assertIn('<base-config cleartextTrafficPermitted="false">', build, 'no cleartext to the internet')
        self.assertIn('includeSubdomains=\\"false\\"', build, 'only the preview machine addresses')
        self.assertIn('openssl x509 -in "$ca" -outform PEM', build, 'only the public CA certificate is bundled')
        self.assertIn('$HOME/.config/poketactics-android', build)
        self.assertNotIn('ca.key', build)


class AndroidProject(unittest.TestCase):
    def test_manifest_back_orientation_and_permissions(self):
        manifest = (MAIN / 'AndroidManifest.xml').read_text()
        self.assertIn('android:enableOnBackInvokedCallback="true"', manifest, 'predictive back goes to the callback')
        self.assertIn('android:screenOrientation="portrait"', manifest)
        self.assertIn('android.permission.VIBRATE', manifest)
        self.assertIn('@xml/network_security_config', manifest)
        self.assertRegex(manifest, r'SettingsActivity"\s+android:exported="false"', 'settings not reachable from other apps')

    def test_back_never_walks_the_webview_history(self):
        main = (KOTLIN / 'MainActivity.kt').read_text()
        self.assertIn('OnBackPressedCallback(true)', main)
        self.assertIn('window.PokeTacticsShell', main)
        self.assertFalse(re.search(r'\.goBack\(|canGoBack', main), 'no history.back in the WebView')
        self.assertFalse('override fun onBackPressed' in main, 'back goes through the dispatcher only')
        self.assertIn('R.string.exit_title', main)

    def test_native_experience_settings(self):
        main = (KOTLIN / 'MainActivity.kt').read_text()
        for needle in ('FLAG_KEEP_SCREEN_ON', 'mediaPlaybackRequiresUserGesture = false', 'domStorageEnabled = true',
                       'WindowInsetsCompat.Type.systemBars()', 'BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE',
                       'setSystemGestureExclusionRects', 'R.string.error_retry', 'addWebMessageListener'):
            self.assertIn(needle, main)
        # The bridge is origin-scoped; addJavascriptInterface would expose it to every frame.
        self.assertFalse(re.search(r'\.addJavascriptInterface\(', main), 'no addJavascriptInterface bridge')
        vibes = (KOTLIN / 'Vibes.kt').read_text()
        self.assertIn('VibrationEffect.createWaveform', vibes)

    def test_no_signing_secrets_or_private_keys_in_the_project(self):
        ignore = (APP / '.gitignore').read_text()
        for pattern in ('*.jks', '*.keystore', 'keystore.properties', 'app/src/generated/'):
            self.assertIn(pattern, ignore)
        tracked = subprocess.run(['git', 'ls-files', 'apps/android', 'tools/android'], cwd=ROOT,
                                 capture_output=True, text=True, check=True).stdout.split()
        for name in tracked:
            self.assertFalse(re.search(r'\.(jks|keystore|p12|pem|key)$|keystore\.properties$', name), name)
            path = ROOT / name
            if path.suffix in ('.jar', '.png'):
                continue
            self.assertNotIn('PRIVATE KEY', path.read_text(errors='replace'), name)


if __name__ == '__main__':
    unittest.main()
