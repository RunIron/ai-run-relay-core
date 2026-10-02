"""Regression tests for issues found in the v0.1.1 review."""
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from relay.codex import CodexAdapter, Result, quota_wait
from relay.core import Engine, Store
from relay.server import make_server

EARLY = r'''#!/usr/bin/env python3
import json, sys
for line in sys.stdin:
    q = json.loads(line); m = q.get('method')
    if 'id' not in q or not m:
        continue
    r = {}
    if m == 'config/read': r = {'config': {}}
    if m == 'account/read': r = {'account': {'type': 'chatgpt'}}
    if m == 'account/rateLimits/read': r = {'rateLimits': {'primary': {'usedPercent': 1}}}
    if m in ('thread/start', 'thread/resume'): r = {'thread': {'id': 't1'}}
    if m == 'turn/start':
        p = {'threadId': 't1', 'turnId': 'turn_1'}
        if MODE == 'early':
            print(json.dumps({'method': 'item/agentMessage/delta', 'params': dict(p, itemId='m1', delta='HELLO')}), flush=True)
            print(json.dumps({'method': 'item/completed', 'params': dict(p, item={'type': 'agentMessage', 'id': 'm1', 'text': 'HELLO'})}), flush=True)
        r = {'turn': {'id': 'turn_1'}}
    print(json.dumps({'id': q['id'], 'result': r}), flush=True)
    if m == 'turn/start':
        print(json.dumps({'method': 'turn/completed', 'params': {'turn': {'id': 'turn_1', 'status': 'completed'}}}), flush=True)
'''


class FakeAdapter:
    def __init__(self, *results):
        self.results, self.prompts = list(results), []

    def available(self):
        return True

    def run(self, job, prompt, session, stop):
        self.prompts.append(prompt)
        session('thread-x')
        return self.results.pop(0)


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.now = 1000
        self.store = Store(self.root / 'q.db')

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def engine(self, adapter=None):
        return Engine(self.store, self.root / 'w', {'codex': adapter or FakeAdapter()}, lambda: self.now)

    def fake(self, mode):
        path = self.root / f'fake-{mode}.py'
        path.write_text(EARLY.replace('MODE', repr(mode)))
        path.chmod(0o700)
        return CodexAdapter(str(path), timeout=5).run(
            {'id': 'j', 'cwd': str(self.root), 'session_id': None}, 'p', lambda s: None, threading.Event())

    def test_notifications_before_turn_response_are_kept(self):
        result = self.fake('early')
        self.assertEqual((result.kind, result.output), ('success', 'HELLO'))

    def test_empty_completed_turn_is_not_checkpointed(self):
        self.assertEqual(self.fake('empty').kind, 'review')

    def test_job_order_stable_after_save(self):
        e = self.engine()
        a = e.add({'title': 'A', 'steps': ['x']})
        e.add({'title': 'B', 'steps': ['x']})
        self.store.save(self.store.get(a['id']))
        self.assertEqual([j['title'] for j in self.store.jobs()], ['B', 'A'])

    def test_millisecond_reset_normalised(self):
        self.assertEqual(quota_wait({'primary': {'usedPercent': 100, 'resetsAt': 4102444800000}}), (True, 4102444800.0))
        self.assertEqual(quota_wait({'rateLimitReachedType': 'x', 'primary': {'usedPercent': None}}), (True, None))

    def test_codex_job_ignores_mock_wait_field(self):
        e = self.engine()
        e.add({'title': 't', 'provider': 'codex', 'steps': ['s'], 'wait_seconds': 0})

    def test_prior_outputs_not_resent_into_resumed_thread(self):
        adapter = FakeAdapter(Result('success', output='FIRST-OUTPUT'), Result('success', output='second'))
        e = self.engine(adapter)
        e.add({'title': 't', 'provider': 'codex', 'steps': ['one', 'two']})
        e.tick(); e.tick()
        self.assertNotIn('FIRST-OUTPUT', adapter.prompts[1])

    def test_deadline_extended_for_known_late_reset(self):
        adapter = FakeAdapter(Result('quota', retry_at=1000 + 8 * 86400))
        e = self.engine(adapter)
        job = e.add({'title': 't', 'provider': 'codex', 'steps': ['one']})
        e.tick()
        saved = self.store.get(job['id'])
        self.assertGreater(saved['deadline'], saved['next_run_at'])

    def test_shared_late_reset_extends_other_waiting_jobs(self):
        reset = 1000 + 8 * 86400
        adapter = FakeAdapter(Result('quota', retry_at=reset), Result('success', output='a'), Result('success', output='b'))
        e = self.engine(adapter)
        first = e.add({'title': 'first', 'provider': 'codex', 'steps': ['one'], 'priority': 10})
        other = e.add({'title': 'other', 'provider': 'codex', 'steps': ['one']})
        e.tick()  # first job receives the 8-day reset
        self.assertFalse(e.tick())  # other job joins the shared wait
        self.assertGreater(self.store.get(other['id'])['deadline'], reset)
        self.now = 1000 + 7 * 86400 + 1  # past the original 7-day deadline
        self.assertFalse(e.tick())
        for job in (first, other):
            self.assertEqual(self.store.get(job['id'])['status'], 'waiting_quota')
        self.now = reset + 2
        e.tick(); e.tick()
        for job in (first, other):
            self.assertEqual(self.store.get(job['id'])['status'], 'succeeded')

    def test_non_ascii_token_rejected_cleanly(self):
        server = make_server(self.engine(), 0)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            c = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
            c.putrequest('POST', '/api/jobs', skip_host=True)
            c.putheader('Host', f'127.0.0.1:{server.server_port}')
            c.putheader('X-Relay-Token', 'é'.encode('latin-1'))
            c.putheader('Content-Type', 'application/json')
            c.putheader('Content-Length', '2')
            c.endheaders(); c.send(b'{}')
            self.assertEqual(c.getresponse().status, 403)
        finally:
            server.shutdown(); server.server_close()


if __name__ == '__main__':
    unittest.main()
