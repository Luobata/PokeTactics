"""Real HTTP playback endpoints distinguish delayed frames from failed renders."""
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/acceptance'))
import server


class BattleRenderHTTP(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='poke-render-http-')
        self.root_patch = patch.object(server, 'ROOT', Path(self.temp.name))
        self.root_patch.start()
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        self.worker = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.worker.start()
        self.base = f'http://127.0.0.1:{self.httpd.server_port}'

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.worker.join(timeout=5)
        self.root_patch.stop()
        self.temp.cleanup()

    def get(self, path):
        try:
            response = urlopen(self.base + path, timeout=4)
        except HTTPError as error:
            response = error
        with response:
            return response.status, response.headers, response.read()

    def test_pending_frame_returns_retryable_response_without_blocking_health(self):
        entered = threading.Event()
        def rendering(*_args):
            entered.set()
            return 'rendering'
        progress = {'ok': True, 'status': 'rendering', 'frames': 16,
                    'total': 100, 'updated_at': 123.0, 'queued': False, 'error': None}
        with patch.object(server.demo_mod, 'ensure_render_job', side_effect=rendering), \
                patch.object(server.demo_mod, 'render_job_status', return_value=progress), \
                ThreadPoolExecutor(max_workers=1) as requests:
            started = time.monotonic()
            pending = requests.submit(self.get, '/demo/frame/123456abcdef/r1/18.png')
            self.assertTrue(entered.wait(timeout=2))
            status, _, body = self.get('/demo/render-status/123456abcdef/r1')
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body), progress)
            status, headers, body = pending.result(timeout=3)
            self.assertEqual(status, 425)
            self.assertEqual(headers['Retry-After'], '1')
            self.assertEqual(json.loads(body)['status'], 'rendering')
            self.assertLess(time.monotonic() - started, 3)

    def test_dead_render_is_machine_readable_and_never_a_hanging_image(self):
        with patch.object(server.demo_mod, 'ensure_render_job', return_value='dead'):
            status, headers, body = self.get('/demo/frame/123456abcdef/r1/18.png')
        self.assertEqual(status, 425)
        self.assertEqual(headers['Retry-After'], '1')
        self.assertEqual(json.loads(body)['status'], 'dead')

    def test_published_render_missing_a_frame_is_a_real_404(self):
        with patch.object(server.demo_mod, 'ensure_render_job', return_value='ready'):
            status, _, _ = self.get('/demo/frame/123456abcdef/r1/18.png')
        self.assertEqual(status, 404)


if __name__ == '__main__':
    unittest.main()
