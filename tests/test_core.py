import tempfile
import threading
import unittest
from pathlib import Path

from relay.core import Engine, Store
from relay.codex import Result


class FakeAdapter:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def available(self):
        return True

    def run(self, job, prompt, session, stop):
        self.calls.append((job, prompt))
        session('saved-session')
        return self.results.pop(0)


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.workspace = self.root / 'work'
        self.now = 1000
        self.store = Store(self.root / 'queue.db')
        self.adapter = FakeAdapter()
        self.engine = Engine(self.store, self.workspace, {'codex': self.adapter}, lambda: self.now)

    def tearDown(self):
        self.engine.stop()
        self.store.close()
        self.tmp.cleanup()

    def add(self, **overrides):
        return self.engine.add(dict(title='test', provider='codex', steps=['one', 'two'], **overrides))

    def test_mock_wait_and_restart_preserve_checkpoint(self):
        job = self.engine.add({'title': 'mock', 'steps': ['one', 'two'], 'wait_seconds': 18000})
        self.engine.tick()
        self.engine.tick()
        saved = self.store.get(job['id'])
        self.assertEqual(saved['status'], 'waiting_quota')
        self.assertEqual(saved['step_index'], 1)
        self.assertEqual(saved['next_run_at'], 19000)
        self.store.close()
        self.store = Store(self.root / 'queue.db')
        self.engine = Engine(self.store, self.workspace, {}, lambda: self.now)
        self.assertFalse(self.engine.tick())
        self.now = 19000
        self.engine.tick()
        done = self.store.get(job['id'])
        self.assertEqual(done['status'], 'succeeded')
        self.assertEqual(len(done['outputs']), 2)
        self.assertEqual(done['outputs'][0], saved['outputs'][0])

    def test_restart_marks_uncertain_codex_for_review(self):
        job = self.add()
        job.update(status='running', step_index=1, outputs=['saved'], session_id='old')
        self.store.save(job)
        self.engine = Engine(self.store, self.workspace, {'codex': self.adapter}, lambda: self.now)
        recovered = self.store.get(job['id'])
        self.assertEqual(recovered['status'], 'needs_review')
        self.assertEqual(recovered['outputs'], ['saved'])
        with self.assertRaises(ValueError):
            self.engine.action(job['id'], 'resume')
        self.adapter.results = [Result('success', output='new')]
        self.engine.action(job['id'], 'resume', confirmed=True)
        self.engine.tick()
        self.assertIn('saved', self.adapter.calls[0][1])
        self.assertEqual(self.adapter.calls[0][0]['session_id'], 'old')
        self.assertEqual(self.store.get(job['id'])['outputs'], ['saved', 'new'])

    def test_shared_cooldown_and_priority(self):
        low = self.add(priority=0)
        high = self.add(priority=10)
        self.adapter.results = [Result('quota', retry_at=2000), Result('success', output='ok')]
        self.engine.tick()
        self.assertEqual(self.adapter.calls[0][0]['id'], high['id'])
        self.assertFalse(self.engine.tick())
        self.assertEqual(self.store.get(low['id'])['next_run_at'], 2002)
        self.now = 2002
        self.engine.tick()
        self.assertEqual(len(self.adapter.calls), 2)

    def test_failure_requires_confirmed_retry(self):
        job = self.add()
        self.adapter.results = [Result('failed', error='bad'), Result('success', output='ok')]
        self.engine.tick()
        self.assertFalse(self.engine.tick())
        with self.assertRaises(ValueError):
            self.engine.action(job['id'], 'retry')
        self.engine.action(job['id'], 'retry', confirmed=True)
        self.engine.tick()
        self.assertEqual(self.store.get(job['id'])['step_index'], 1)

    def test_cancel_race_does_not_commit_late_success(self):
        entered, release = threading.Event(), threading.Event()
        def run(job, prompt, session, stop):
            entered.set()
            release.wait(3)
            return Result('success', output='late')
        self.adapter.run = run
        job = self.add()
        worker = threading.Thread(target=self.engine.tick)
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            self.engine.action(job['id'], 'cancel')
        finally:
            release.set()
            worker.join(3)
        current = self.store.get(job['id'])
        self.assertEqual(current['status'], 'cancelled')
        self.assertEqual(current['outputs'], [])

    def test_pause_and_bounded_automatic_attempts(self):
        job = self.add()
        self.store.set('paused', True)
        self.assertFalse(self.engine.tick())
        self.assertEqual(self.adapter.calls, [])
        self.store.set('paused', False)
        self.adapter.results = [Result('quota') for _ in range(6)]
        for _ in range(6):
            self.assertTrue(self.engine.tick())
            self.now = self.store.get(job['id'])['next_run_at']
        self.assertEqual(self.store.get(job['id'])['status'], 'needs_review')
        self.assertFalse(self.engine.tick())
        self.assertEqual(len(self.adapter.calls), 6)

    def test_restart_requeues_mock_without_stale_error(self):
        job = self.engine.add({'title': 'mock', 'steps': ['one']})
        job.update(status='running')
        self.store.save(job)
        Engine(self.store, self.workspace, {}, lambda: self.now)
        recovered = self.store.get(job['id'])
        self.assertEqual((recovered['status'], recovered['last_error']), ('queued', ''))

    def test_worker_survives_a_failing_tick(self):
        class NoSleep(threading.Event):
            def wait(self, timeout=None):
                return self.is_set()
        calls = []
        def flaky():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError('transient')
            self.engine.shutdown.set()
            return False
        self.engine.shutdown = NoSleep()
        self.engine.tick = flaky
        self.engine.start()
        self.engine.thread.join(2)
        self.assertEqual(len(calls), 2)

    def test_invalid_inputs_and_workspace_escape(self):
        for values in ({'title': ''}, {'steps': []}, {'priority': True}, {'priority': 11},
                       {'wait_seconds': 0}, {'provider': 'unknown'}, {'cwd': str(self.root)},
                       {'cwd': '../'}, {'cwd': 'missing'}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.engine.add(dict({'title': 't', 'steps': ['s']}, **values))
        outside = self.workspace / 'escape'
        try:
            outside.symlink_to(self.root, target_is_directory=True)
        except OSError:
            self.skipTest('creating symbolic links needs Developer Mode or admin rights on Windows')
        with self.assertRaises(ValueError):
            self.engine.add({'title': 't', 'steps': ['s'], 'cwd': 'escape'})


if __name__ == '__main__':
    unittest.main()
