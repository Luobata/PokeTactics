"""后台流式渲染（DEFER_RENDER）：开战只等权威解算，帧异步落盘且结果不变。"""
import json
import os
import random
import select
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'sim'), str(ROOT / 'tools' / 'acceptance'),
                str(ROOT / 'tools' / 'mockups')]
import demo
import arena


def new_session(seed=20261010):
    session = demo.Session(seed, 'arena_v1')
    session.begin_round(1)
    state = demo.state_json(session)
    for i, slot in enumerate(state.get('shop', [])):
        if slot:
            try:
                demo.act_buy(session, i)
            except demo.DemoError:
                pass
    state = demo.state_json(session)
    for j, _ in enumerate(state['bench'][:3]):
        try:
            demo.act_move(session, f'b{j}', f'g{j},0')
        except demo.DemoError:
            pass
    arena.claim_augment(session, 'augment-r1',
                        state.get('augments', {}).get('pending', [{}])[0]
                        .get('options', [{}])[0].get('id', ''))
    return session


def join_renders():
    for worker in list(demo._RENDER_THREADS):
        worker.join()


class DeferredRenderTest(unittest.TestCase):
    def setUp(self):
        demo.DEFER_RENDER = True
        demo._RENDER_THREADS.clear()
        demo._RENDER_ACTIVE.clear()

    def tearDown(self):
        join_renders()
        demo._RENDER_ACTIVE.clear()
        demo._RENDER_THREADS.clear()
        demo.DEFER_RENDER = False

    def test_end_prep_returns_before_frames_then_publishes_complete_set(self):
        session = new_session()
        out_dir = demo.ROOT / '.build' / 'demo' / session.sid / 'r1'
        started = time.time()
        session.end_prep()
        elapsed = time.time() - started
        meta = session.last_battle
        # 权威结果与 meta 立即可用，不等逐帧落盘。
        self.assertLess(elapsed, 5)
        self.assertGreater(meta['n'], 0)
        self.assertIsNone(meta['render_s'])
        self.assertEqual(len(meta['team_frames']), meta['n'])
        self.assertIn('winner', meta)
        self.assertTrue(meta['statistics'])
        join_renders()
        # 后台任务补齐完整帧集，meta.json 最后写入作为发布标记。
        for i in range(meta['n']):
            self.assertTrue((out_dir / f'{i}.png').is_file(), f'缺帧 {i}')
        published = json.loads((out_dir / 'meta.json').read_text())
        self.assertEqual(published['n'], meta['n'])
        self.assertIsInstance(published['render_s'], float)
        self.assertEqual(published['team_frames'], meta['team_frames'])

    def test_step_view_matches_frame_playback_telemetry(self):
        # 不画帧的视图步进必须与真实渲染读到的队伍遥测逐帧一致（竞技渲染含
        # 时间 warp 映射，是最容易被解耦破坏的分支）。
        import copy
        from combat import Battle
        from presentation_modes import make_renderer
        from render_battle_gif import BattleAnimation

        session = new_session(seed=317)
        assert session.player.battle_comp(), '需要上场阵容构造竞技战斗'
        opponent = next(seat for seat in session.seats[1:] if seat.alive)
        options = session.battle_options(session.player, opponent)

        def comps():
            return (copy.deepcopy(session.player.battle_comp()),
                    copy.deepcopy(opponent.battle_comp()))

        def telemetry(view):
            return [[sum(u.die_t is None for u in view.units.values() if u.u.team == team)
                     for team in (0, 1)],
                    [sum(u.hp for u in view.units.values() if u.u.team == team)
                     for team in (0, 1)]]

        comp_a, comp_b = comps()
        meta, _job = demo._prepare_battle_frames(
            comp_a, comp_b, random.Random(20261010), None,
            demo.ROOT / '.build' / 'demo' / 'step-view-probe',
            positions_a=session.player.battle_positions(), **options)
        self.assertTrue(meta['presentation'].startswith('web-arena-'))

        class _Anim(BattleAnimation):
            def __init__(self, a, b, battle_rng):
                battle = Battle(a, b, battle_rng, layout='back',
                                positions_a=session.player.battle_positions(),
                                **options)
                self.sim_result = battle.run()
                self.statistics = battle.statistics()
                super().__init__(a, b, 0, *demo._assets(), battle=battle)

        anim = _Anim(*comps(), random.Random(20261010))
        renderer = make_renderer(anim, 'arena')
        n = meta['n']
        for i in {0, n // 3, n // 2, n - 1}:
            T = i * meta['dt']
            renderer.frame_playback(T)
            drawn = telemetry(anim._presentation_view())
            self.assertEqual(drawn, [meta['team_frames'][i]['alive'],
                                     meta['team_frames'][i]['hp']],
                             f'第 {i} 帧遥测不一致')


class RenderRecoveryTest(unittest.TestCase):
    """渲染中断兜底：心跳判活、崩溃留痕、参数快照重启渲染、无法恢复判 dead。"""

    def setUp(self):
        demo.DEFER_RENDER = True
        demo._RENDER_THREADS.clear()
        demo._RENDER_ACTIVE.clear()
        demo._RENDER_PARAMS.clear()
        demo._RENDER_RESTARTS.clear()

    def tearDown(self):
        join_renders()
        demo._RENDER_THREADS.clear()
        demo._RENDER_ACTIVE.clear()
        demo._RENDER_PARAMS.clear()
        demo._RENDER_RESTARTS.clear()
        demo.DEFER_RENDER = False

    def test_render_status_publishes_ready_progress(self):
        session = new_session(seed=913)
        session.end_prep()
        join_renders()
        row = demo.render_job_status(session.sid, 1)
        self.assertTrue(row['ok'])
        self.assertEqual(row['status'], 'ready')
        self.assertEqual(row['frames'], session.last_battle['n'])
        self.assertEqual(row['total'], session.last_battle['n'])
        self.assertFalse(row['queued'])
        self.assertIsNone(row['error'])

    def test_restarted_worker_with_stale_heartbeat_is_dead(self):
        directory = demo.ROOT / '.build' / 'demo' / 'stale-retry-probe' / 'r1'
        directory.mkdir(parents=True, exist_ok=True)
        worker = threading.Thread(target=time.sleep, args=(0.05,), daemon=True)
        worker.start()
        key = ('stale-retry-probe', 1)
        demo._RENDER_ACTIVE[key] = worker
        # A registered worker with a stale heartbeat must expose a terminal state.
        (directory / 'rendering.json').write_text(json.dumps(
            {'pid': os.getpid(), 'updated': time.time() - 3600,
             'frames': 3, 'total': 10, 'queued': False}))
        try:
            self.assertEqual(demo.ensure_render_job('stale-retry-probe', 1), 'dead')
            row = demo.render_job_status('stale-retry-probe', 1)
            self.assertEqual(row['status'], 'dead')
            self.assertEqual(row['frames'], 3)
            self.assertEqual(row['total'], 10)
        finally:
            worker.join()
            shutil.rmtree(directory.parent, ignore_errors=True)

    def test_queue_timeout_is_terminal_error(self):
        directory = demo.ROOT / '.build' / 'demo' / 'queue-timeout-probe' / 'r1'
        stale = demo._RENDER_HEARTBEAT_STALE_S
        demo._RENDER_HEARTBEAT_STALE_S = 0.01
        for _ in range(demo._RENDER_CONCURRENCY):
            self.assertTrue(demo._RENDER_SEMAPHORE.acquire(timeout=0.1))
        try:
            demo._run_render_job(lambda: None, directory, ('queue-timeout-probe', 1))
        finally:
            for _ in range(demo._RENDER_CONCURRENCY):
                demo._RENDER_SEMAPHORE.release()
            demo._RENDER_HEARTBEAT_STALE_S = stale
        row = json.loads((directory / 'render_error.json').read_text())
        self.assertIn('render queue timeout', row['error'])
        self.assertEqual(demo.ensure_render_job('queue-timeout-probe', 1), 'dead')
        shutil.rmtree(directory.parent, ignore_errors=True)

    def test_base_exception_worker_leaves_error_marker(self):
        out_dir = demo.ROOT / '.build' / 'demo' / 'base-exit-probe' / 'r1'

        def stop():
            raise SystemExit(7)
        with self.assertRaises(SystemExit):
            demo._run_render_job(stop, out_dir, ('base-exit-probe', 1))
        row = json.loads((out_dir / 'render_error.json').read_text())
        self.assertIn('SystemExit', row['error'])
        shutil.rmtree(out_dir.parent, ignore_errors=True)

    def test_registered_render_job_publishes_ownership_before_start(self):
        release = threading.Event()

        def job():
            release.wait(2)

        probe_root = Path(tempfile.mkdtemp(prefix='poke-foreign-start-'))
        out_dir = probe_root / '.build' / 'demo' / 'startup-heartbeat-probe' / 'r1'
        key = ('startup-heartbeat-probe', 1)
        real_start = threading.Thread.start
        def start_after_foreign_prune(worker):
            self.assertTrue((out_dir / 'rendering.json').is_file())
            probe = subprocess.run([sys.executable, '-c',
                'import sys; from pathlib import Path; '
                'sys.path.insert(0, sys.argv[1]); import demo; '
                'demo.ROOT=Path(sys.argv[2]); demo._prune_render_store(max_sessions=0)',
                str(ROOT / 'tools/acceptance'), str(probe_root)],
                capture_output=True, text=True, timeout=10)
            self.assertEqual(probe.returncode, 0, probe.stderr)
            self.assertTrue(out_dir.is_dir(), 'another process must see ownership before Thread.start')
            real_start(worker)
        with patch.object(threading.Thread, 'start', start_after_foreign_prune):
            demo._start_render_job(job, out_dir, key, 'render-start-heartbeat')
        try:
            heartbeat = json.loads((out_dir / 'rendering.json').read_text())
            self.assertEqual(heartbeat['pid'], os.getpid())
            self.assertTrue(heartbeat['queued'])
            self.assertGreaterEqual(heartbeat['frames'], 0)
        finally:
            release.set()
            for worker in list(demo._RENDER_THREADS):
                if worker.name == 'render-start-heartbeat':
                    worker.join(.5)
            demo._RENDER_ACTIVE.pop(key, None)
            shutil.rmtree(probe_root, ignore_errors=True)

    def test_registered_render_job_starts_before_another_worker_can_replace_it(self):
        started = threading.Event()
        release = threading.Event()
        entered = []

        def job():
            entered.append(threading.get_ident())
            started.set()
            release.wait(2)

        out_dir = demo.ROOT / '.build' / 'demo' / 'startup-race-probe' / 'r1'
        key = ('startup-race-probe', 1)
        demo._start_render_job(job, out_dir, key, 'render-start-race')
        try:
            self.assertTrue(started.wait(.5))
            demo._start_render_job(job, out_dir, key, 'render-start-race-duplicate')
            self.assertEqual(len(entered), 1, 'a registered worker must not be replaced before it starts')
        finally:
            release.set()
            for worker in list(demo._RENDER_THREADS):
                if worker.name.startswith('render-start-race'):
                    worker.join(.5)
            demo._RENDER_ACTIVE.pop(key, None)
            shutil.rmtree(out_dir.parent, ignore_errors=True)

    def test_old_round_frames_are_pruned_but_active_round_is_kept(self):
        with patch.object(demo, 'ROOT', Path(tempfile.mkdtemp(prefix='poke-render-prune-'))):
            session = demo.ROOT / '.build/demo/123456abcdef'
            worker = threading.Thread(target=time.sleep, args=(0.05,), daemon=True)
            worker.start()
            demo._RENDER_ACTIVE[('123456abcdef', 1)] = worker
            try:
                for round_no in (1, 2, 3, 4):
                    (session / f'r{round_no}').mkdir(parents=True, exist_ok=True)
                demo._prune_round_frames('123456abcdef', 4, keep_rounds=2)
                self.assertEqual(
                    sorted(p.name for p in session.iterdir() if p.is_dir()),
                    ['r1', 'r3', 'r4'])
                demo._RENDER_ACTIVE.pop(('123456abcdef', 1), None)
                demo._prune_round_frames('123456abcdef', 4, keep_rounds=2)
                self.assertEqual(
                    sorted(p.name for p in session.iterdir() if p.is_dir()), ['r3', 'r4'])
            finally:
                worker.join()
                demo._RENDER_ACTIVE.pop(('123456abcdef', 1), None)
                shutil.rmtree(demo.ROOT, ignore_errors=True)

    def test_round_pruning_respects_foreign_heartbeat(self):
        with patch.object(demo, 'ROOT', Path(tempfile.mkdtemp(prefix='poke-round-foreign-'))):
            session = demo.ROOT / '.build/demo/123456abcdef/r1'
            session.mkdir(parents=True, exist_ok=True)
            demo._write_heartbeat(session, frames=1, total=2)
            try:
                demo._prune_round_frames('123456abcdef', 4, keep_rounds=2)
                self.assertTrue(session.is_dir())
            finally:
                shutil.rmtree(demo.ROOT, ignore_errors=True)

    def test_render_store_pruning_respects_foreign_heartbeat(self):
        with patch.object(demo, 'ROOT', Path(tempfile.mkdtemp(prefix='poke-render-store-'))):
            session = demo.ROOT / '.build/demo/123456abcdef/r1'
            session.mkdir(parents=True, exist_ok=True)
            demo._write_heartbeat(session, frames=1, total=2)
            try:
                demo._prune_render_store(max_sessions=0)
                self.assertTrue(session.is_dir())
            finally:
                shutil.rmtree(demo.ROOT, ignore_errors=True)

    def test_heartbeat_marks_live_and_stale(self):
        directory = demo.ROOT / '.build' / 'demo' / 'heartbeat-probe' / 'r1'
        directory.mkdir(parents=True, exist_ok=True)
        heartbeat = directory / 'rendering.json'
        try:
            self.assertFalse(demo._render_alive(directory))
            heartbeat.write_text(json.dumps({'pid': os.getpid(), 'updated': time.time()}))
            self.assertTrue(demo._render_alive(directory))
            heartbeat.write_text(json.dumps(
                {'pid': os.getpid(), 'updated': time.time() - 3600}))
            self.assertFalse(demo._render_alive(directory))
            heartbeat.write_text(json.dumps({'pid': 2 ** 22, 'updated': time.time()}))
            self.assertFalse(demo._render_alive(directory))
        finally:
            shutil.rmtree(directory.parent, ignore_errors=True)

    def test_render_job_failure_leaves_error_marker(self):
        out_dir = demo.ROOT / '.build' / 'demo' / 'crash-probe' / 'r1'
        shutil.rmtree(out_dir, ignore_errors=True)

        def boom():
            raise RuntimeError('simulated render crash')

        demo._run_render_job(boom, out_dir)
        error = json.loads((out_dir / 'render_error.json').read_text())
        self.assertIn('simulated render crash', error['error'])
        self.assertFalse((out_dir / 'rendering.json').exists())
        shutil.rmtree(out_dir.parent, ignore_errors=True)

    def _render_recovery_case(self, seed, probe):
        session = new_session(seed)
        opponent = next(seat for seat in session.seats[1:] if seat.alive)
        options = session.battle_options(session.player, opponent)
        options['positions_b'] = arena.positions_for(opponent.battle_comp(), 1)
        out_dir = demo.ROOT / '.build' / 'demo' / probe / 'r1'
        rng = demo.rng_mod.derive(session.seed, 1, 'battle', 0)
        meta, job = demo._prepare_battle_frames(
            session.player.battle_comp(), opponent.battle_comp(), rng, None,
            out_dir, positions_a=session.player.battle_positions(),
            hud_snapshot={'hp': session.player.hp, 'gold': session.player.gold,
                          'level': session.player.level, 'round': 1}, **options)
        params = {'comp_a': session.player.battle_comp(),
                  'comp_b': opponent.battle_comp(), 'seed': session.seed,
                  'battle_i': 0, 'weather_name': None, 'out_dir': out_dir,
                  'positions_a': session.player.battle_positions(),
                  'hud_snapshot': {'hp': session.player.hp, 'gold': session.player.gold,
                                   'level': session.player.level, 'round': 1},
                  'battle_options': options, 'total': meta['n']}
        return out_dir, meta, job, params

    def test_first_explicit_worker_crash_gets_one_real_retry(self):
        out_dir, _meta, _job, params = self._render_recovery_case(917, 'first-crash-retry')
        key = ('first-crash-retry', 1)
        demo._RENDER_PARAMS[key] = params

        def crash():
            raise RuntimeError('first simulated worker crash')
        demo._start_render_job(crash, out_dir, key, 'first-crash-worker')
        join_renders()
        self.assertIn('first simulated worker crash',
                      json.loads((out_dir / 'render_error.json').read_text())['error'])
        self.assertEqual(demo.ensure_render_job('first-crash-retry', 1), 'rendering')
        join_renders()
        self.assertTrue((out_dir / 'meta.json').is_file())
        self.assertFalse((out_dir / 'render_error.json').exists())
        shutil.rmtree(out_dir.parent, ignore_errors=True)

    def test_second_explicit_worker_crash_is_terminal(self):
        out_dir, meta, _job, params = self._render_recovery_case(919, 'second-crash-terminal')
        key = ('second-crash-terminal', 1)
        demo._RENDER_PARAMS[key] = params

        def first_crash():
            raise RuntimeError('first terminal probe crash')
        demo._start_render_job(first_crash, out_dir, key, 'second-crash-first')
        join_renders()

        def retry_crash():
            raise RuntimeError('retry must stop here')
        with patch.object(demo, '_prepare_battle_frames',
                          return_value=(meta, retry_crash)) as prepare:
            self.assertEqual(demo.ensure_render_job('second-crash-terminal', 1), 'rendering')
            prepare.assert_called_once()
        join_renders()
        self.assertIn('retry must stop here',
                      json.loads((out_dir / 'render_error.json').read_text())['error'])
        threads = len(demo._RENDER_THREADS)
        self.assertEqual(demo.ensure_render_job('second-crash-terminal', 1), 'dead')
        self.assertEqual(len(demo._RENDER_THREADS), threads)
        shutil.rmtree(out_dir.parent, ignore_errors=True)

    def test_session_eviction_keeps_active_render_directory(self):
        with patch.object(demo, 'ROOT', Path(tempfile.mkdtemp(prefix='poke-render-evict-'))):
            sid = '123456abcdef'
            demo.SESSIONS[sid] = type('SessionStub', (), {'sid': sid})()
            release = threading.Event()
            worker = threading.Thread(target=release.wait, args=(2,), daemon=True)
            worker.start()
            demo._RENDER_ACTIVE[(sid, 1)] = worker
            directory = demo.ROOT / '.build/demo' / sid / 'r1'
            directory.mkdir(parents=True, exist_ok=True)
            try:
                demo._drop_session(sid)
                self.assertNotIn(sid, demo.SESSIONS)
                self.assertTrue(directory.is_dir())
            finally:
                release.set()
                worker.join(.5)
                demo._RENDER_ACTIVE.pop((sid, 1), None)
                shutil.rmtree(demo.ROOT, ignore_errors=True)

    def test_session_eviction_does_not_delete_queued_worker_files(self):
        with tempfile.TemporaryDirectory(prefix='poke-queued-evict-') as temp, \
                patch.object(demo, 'ROOT', Path(temp)):
            sid = 'abcdef123456'
            key = (sid, 1)
            demo.SESSIONS[sid] = type('SessionStub', (), {'sid': sid})()
            directory = demo.ROOT / '.build/demo' / sid / 'r1'
            directory.mkdir(parents=True)
            marker = directory / 'keep.txt'
            marker.write_text('original directory')
            semaphore = threading.BoundedSemaphore(1)
            semaphore.acquire()
            def job():
                (directory / 'meta.json').write_text('{"n": 1}')
                (directory / 'rendering.json').unlink(missing_ok=True)
            with patch.object(demo, '_RENDER_SEMAPHORE', semaphore):
                demo._start_render_job(job, directory, key, 'queued-eviction')
                try:
                    demo._drop_session(sid)
                    self.assertTrue(marker.is_file())
                finally:
                    semaphore.release()
                    join_renders()
                self.assertEqual(marker.read_text(), 'original directory')
                self.assertTrue((directory / 'meta.json').is_file())

    def test_cleanup_serializes_a_local_claim_after_its_ownership_scan(self):
        with tempfile.TemporaryDirectory(prefix='poke-local-claim-') as temp, \
                patch.object(demo, 'ROOT', Path(temp)):
            sid = 'abcdef123456'
            directory = demo.ROOT / '.build/demo' / sid / 'r1'
            directory.mkdir(parents=True)
            scanned, allow_delete, started, release = [threading.Event() for _ in range(4)]
            def scan(_path):
                scanned.set()
                self.assertTrue(allow_delete.wait(5))
                return False
            def job():
                started.set()
                release.wait(5)
            with patch.object(demo, '_session_has_live_renderer', side_effect=scan):
                cleanup = threading.Thread(target=demo._remove_inactive_render_path,
                                           args=(directory.parent, sid))
                cleanup.start()
                self.assertTrue(scanned.wait(2))
                starter = threading.Thread(target=demo._start_render_job,
                                           args=(job, directory, (sid, 1), 'late-local-claim'))
                starter.start()
                try:
                    self.assertFalse(started.wait(.1), 'claim must wait for cleanup to release ownership lock')
                    allow_delete.set()
                    cleanup.join(2)
                    starter.join(2)
                    self.assertTrue(started.wait(2))
                    self.assertTrue(directory.is_dir())
                    self.assertTrue((directory / 'rendering.json').is_file())
                finally:
                    allow_delete.set()
                    release.set()
                    cleanup.join(2)
                    starter.join(2)
                    join_renders()

    def test_cleanup_serializes_a_foreign_claim_after_its_ownership_scan(self):
        with tempfile.TemporaryDirectory(prefix='poke-foreign-claim-') as temp, \
                patch.object(demo, 'ROOT', Path(temp)):
            sid = 'abcdef654321'
            directory = demo.ROOT / '.build/demo' / sid / 'r1'
            directory.mkdir(parents=True)
            scanned, allow_delete = threading.Event(), threading.Event()
            def scan(_path):
                scanned.set()
                self.assertTrue(allow_delete.wait(8))
                return False
            script = '''import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import demo
demo.ROOT = Path(sys.argv[2])
directory = demo.ROOT / '.build/demo/abcdef654321/r1'
def job():
    (directory / 'meta.json').write_text('{"n":1}')
    (directory / 'rendering.json').unlink(missing_ok=True)
print('claiming', flush=True)
demo._start_render_job(job, directory, ('abcdef654321', 1), 'foreign-claim')
for worker in demo._RENDER_THREADS: worker.join(3)
print('finished', flush=True)
'''
            with patch.object(demo, '_session_has_live_renderer', side_effect=scan):
                cleanup = threading.Thread(target=demo._remove_inactive_render_path,
                                           args=(directory.parent, sid))
                cleanup.start()
                self.assertTrue(scanned.wait(2))
                child = subprocess.Popen([sys.executable, '-c', script,
                                          str(ROOT / 'tools/acceptance'), temp],
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    self.assertTrue(select.select([child.stdout], [], [], 5)[0])
                    self.assertEqual(child.stdout.readline().strip(), 'claiming')
                    self.assertIsNone(child.poll())
                    allow_delete.set()
                    cleanup.join(2)
                    output, error = child.communicate(timeout=5)
                    self.assertEqual(child.returncode, 0, error)
                    self.assertIn('finished', output)
                    self.assertTrue((directory / 'meta.json').is_file(), 'cleanup must not remove a newly claimed output')
                finally:
                    allow_delete.set()
                    cleanup.join(2)
                    if child.poll() is None:
                        child.kill()
                        child.communicate()

    def test_ensure_render_job_recovers_interrupted_round(self):
        session = new_session()
        out_dir = demo.ROOT / '.build' / 'demo' / session.sid / 'r1'
        session.end_prep()
        join_renders()
        published = json.loads((out_dir / 'meta.json').read_text())
        self.assertEqual(demo.ensure_render_job(session.sid, 1), 'ready')
        # 模拟服务器重启/渲染线程被杀：帧残缺、无 meta、无心跳。
        meta = session.last_battle
        (out_dir / 'meta.json').unlink()
        for i in range(meta['n'] // 2, meta['n']):
            (out_dir / f'{i}.png').unlink()
        self.assertEqual(demo.ensure_render_job(session.sid, 1), 'rendering')
        join_renders()
        restored = json.loads((out_dir / 'meta.json').read_text())
        self.assertEqual(restored['winner'], published['winner'])
        for i in range(meta['n']):
            self.assertTrue((out_dir / f'{i}.png').is_file(), f'重渲染后仍缺帧 {i}')
        # 再次中断不重复重启：判 dead，交给战果兜底。
        (out_dir / 'meta.json').unlink()
        (out_dir / 'render_error.json').write_text('{}')
        self.assertEqual(demo.ensure_render_job(session.sid, 1), 'dead')

    def test_ensure_render_job_dead_without_params(self):
        self.assertEqual(demo.ensure_render_job('no-such-session', 7), 'dead')


if __name__ == '__main__':
    unittest.main()
