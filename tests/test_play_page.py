"""The new trial routes serve fixed assets without changing game state."""

import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "acceptance"))
import server


class QuietHandler(server.Handler):
    def log_message(self, *_args):
        pass


class PlayPageRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)

    def get(self, path):
        return urlopen(self.base + path, timeout=5)

    def test_opening_trial_does_not_create_a_session(self):
        sessions = set(server.demo_mod.SESSIONS)
        for path in ("/play", "/play/", "/play?new=1"):
            with self.subTest(path=path), self.get(path) as response:
                html = response.read().decode()
                self.assertEqual(response.status, 200)
                self.assertIn('id="ally-board"', html)
                self.assertIn('id="fight-button"', html)
                self.assertIn('/play/assets/play.js', html)
                self.assertIn('text/html', response.headers['Content-Type'])
        self.assertEqual(set(server.demo_mod.SESSIONS), sessions)

    def test_source_assets_are_served_with_their_exact_mime_types(self):
        for filename, mime in (("play.css", "text/css"),
                               ("play.js", "text/javascript")):
            with self.subTest(filename=filename), self.get("/play/assets/" + filename) as response:
                expected = (ROOT / "tools" / "acceptance" / filename).read_bytes()
                self.assertEqual(response.read(), expected)
                self.assertIn(mime, response.headers["Content-Type"])
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")

    def test_unknown_and_traversal_assets_are_rejected(self):
        for path in ("/play/assets/server.py", "/play/assets/missing.js",
                     "/play/assets/../server.py", "/play/assets/%2e%2e/server.py"):
            with self.subTest(path=path), self.assertRaises(HTTPError) as error:
                self.get(path)
            self.assertEqual(error.exception.code, 404)

    def test_acceptance_home_and_legacy_demo_stay_available(self):
        with self.get("/") as response:
            self.assertIn('href="/play"', response.read().decode())
        with self.get("/demo") as response:
            self.assertEqual(response.status, 200)
            self.assertIn('text/html', response.headers["Content-Type"])


if __name__ == "__main__":
    unittest.main()
