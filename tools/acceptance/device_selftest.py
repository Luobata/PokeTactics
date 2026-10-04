#!/usr/bin/env python3
"""Real-frame three-key regression: auto playback -> settlement -> next round.

Disposable HTTP server and saves. The deterministic fixture starts via the game
API; all subsequent navigation and commits use physical down/up/tick events.
No resume is allowed between the battle and advancing to the next round.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[2]


def main():
    with tempfile.TemporaryDirectory(prefix='poketactics-device-e2e-') as directory:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        process = subprocess.Popen(
            [sys.executable, 'tools/acceptance/server.py', '--port', str(port)],
            cwd=ROOT, env={**os.environ, 'POKETACTICS_SAVE_DIR': directory},
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        def get(path, **params):
            url = base + path + ('?' + urllib.parse.urlencode(params) if params else '')
            with urllib.request.urlopen(url, timeout=120) as response:
                return response.read()
        def data(path, **params):
            result = json.loads(get(path, **params))
            assert result['ok'], result
            return result
        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise AssertionError(process.stderr.read().decode())
                try:
                    get('/device')
                    break
                except OSError:
                    time.sleep(.05)
            else:
                raise AssertionError('device server did not start')
            created = data('/api/demo/action', cmd='new', seed=7, mode='expedition', partner=6)
            sid = created['sid']
            view = data('/api/device/input', phase='state', sid=sid)
            device = view['device_id']
            def send(phase, key=None):
                nonlocal view
                params = {'phase': phase, 'device_id': device}
                if key:
                    params['key'] = key
                view = data('/api/device/input', **params)
                return view
            def click(key):
                # Respect the specified 100ms page-transition blanking interval.
                time.sleep(.12)
                send('down', key)
                return send('up', key)
            for _ in range(5):
                click('B')
            assert next(r for r in view['screen']['rows'] if r['index'] == view['screen']['selected'])['label'] == '开战'
            click('C')
            assert view['screen']['page'] == 'confirm'
            click('B')
            click('C')
            assert view['screen']['page'] == 'battle', view
            battle = view['screen']['battle']
            assert battle['n'] > 0, battle
            assert get(battle['url']).startswith(b'\x89PNG\r\n\x1a\n')
            sequence = view['sequence']
            deadline = time.monotonic() + 120
            while view['screen']['page'] == 'battle' and time.monotonic() < deadline:
                time.sleep(.1)
                send('tick')
            assert view['screen']['page'] == 'result', view
            assert view['sequence'] == sequence
            assert view['screen']['selected'] == 0
            click('C')
            assert view['screen']['page'] == 'prep' and view['screen']['round'] == 2, view
            assert view['sequence'] == sequence + 1
            send('up', 'C')  # duplicate release must never advance a second time
            send('tick')
            assert view['sequence'] == sequence + 1 and view['screen']['round'] == 2
            final = data('/api/demo/action', cmd='state', sid=sid)['state']
            assert final['stats']['battles'] == 1
            print(json.dumps({'status': 'passed', 'seed': 7, 'frames': battle['n'],
                'checks': ['real_frame_png', 'automatic_playback_completion',
                           'next_without_resume', 'single_sequence_increment',
                           'duplicate_release_no_commit'],
                'round': final['round'], 'player_battles': final['stats']['battles'],
                'storage': 'temporary_directory'}, ensure_ascii=False, indent=2))
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            process.stderr.close()


if __name__ == '__main__':
    main()
