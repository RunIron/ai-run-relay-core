"""Projection, migration, HTTP pagination and workspace regressions."""
import http.client
import json
import sqlite3
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from relay.core import Engine, Store
from relay.server import make_server, resolve_workspace


class V013Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / 'queue.db')
        self.engine = Engine(self.store, self.root / 'work', {})
        self.server = make_server(self.engine, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.store.close()
        self.tmp.cleanup()

    def add(self, title='test', **extra):
        return self.engine.add(dict(title=title, steps=['analyze'], **extra))

    def request(self, path, data=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        try:
            conn.request('GET' if data is None else 'POST', path,
                         None if data is None else json.dumps(data),
                         {'Content-Type': 'application/json', **(headers or {})})
            response = conn.getresponse()
            raw = response.read()
            return response.status, json.loads(raw), len(raw)
        finally:
            conn.close()

    def test_projection_and_large_output_http_payload(self):
        payload = 'x' * 16384
        for index in range(200):
            job = self.add(str(index))
            job.update(outputs=[payload], partial_output='partial secret', status='succeeded', step_index=1)
            self.store.save(job)
        started = time.perf_counter()
        with patch.object(self.store, 'jobs', side_effect=AssertionError('poll must not load full jobs')):
            status, state, size = self.request('/api/state')
        elapsed = time.perf_counter() - started
        self.assertEqual(status, 200)
        self.assertEqual(state['total_jobs'], 200)
        self.assertEqual(state['counts'], {'succeeded': 200})
        self.assertEqual(len(state['jobs']), 50)
        self.assertEqual(state['pages'], 4)
        self.assertLess(size, 100000)
        for summary in state['jobs']:
            self.assertTrue({'outputs', 'steps', 'partial_output'}.isdisjoint(summary))
            self.assertEqual(summary['output_count'], 1)
            self.assertTrue(summary['has_partial'])
        status, detail, _ = self.request('/api/jobs/' + job['id'])
        self.assertEqual(status, 200)
        self.assertEqual(detail['outputs'], [payload])
        self.assertEqual(detail['partial_output'], 'partial secret')
        print(f'\nv0.1.3 measurement: 200 jobs × 16 KiB output; state={size} bytes, request={elapsed * 1000:.2f} ms (informational)')

    def test_delta_revision_order_counts_and_stale_cursor(self):
        first, second = self.add('first'), self.add('second')
        initial = self.engine.state()
        revision = initial['revision']
        unchanged = self.engine.state(since=revision)
        self.assertEqual(unchanged['jobs'], [])
        self.assertEqual(unchanged['job_order'], [second['id'], first['id']])
        first['status'] = 'failed'
        self.store.save(first)
        delta = self.engine.state(since=revision)
        self.assertEqual([j['id'] for j in delta['jobs']], [first['id']])
        self.assertEqual(delta['counts'], {'queued': 1, 'failed': 1})
        self.assertEqual(delta['job_order'], initial['job_order'])
        self.assertGreater(delta['revision'], revision)
        self.assertEqual(self.engine.state(since=delta['revision'])['jobs'], [])
        self.assertEqual(len(self.engine.state(since=delta['revision'] + 1)['jobs']), 2)
        self.store.set('paused', True)
        settings_delta = self.engine.state(since=delta['revision'])
        self.assertTrue(settings_delta['paused'])
        self.assertGreater(settings_delta['revision'], delta['revision'])
        self.assertEqual(settings_delta['jobs'], [])

    def test_page_changes_and_insert_boundary_full_fetch_recovers_membership(self):
        for index in range(7):
            self.add(str(index))
        page0 = self.engine.state(page_size=3)
        page1 = self.engine.state(page=1, page_size=3)
        self.assertFalse(set(page0['job_order']) & set(page1['job_order']))
        self.assertEqual(len(page1['jobs']), 3)
        self.add('new first row')
        delta = self.engine.state(page=1, page_size=3, since=page1['revision'])
        cached = {j['id']: j for j in page1['jobs']}
        cached.update({j['id']: j for j in delta['jobs']})
        missing = set(delta['job_order']) - cached.keys()
        # Membership shifts need a full refresh, even when the incoming row itself
        # has not changed since the client's revision. Explicit full fetch recovers it.
        self.assertEqual(len(missing), 1)
        full = self.engine.state(page=1, page_size=3)
        self.assertEqual({j['id'] for j in full['jobs']}, set(delta['job_order']))
        clamped = self.engine.state(page=999, page_size=3)
        self.assertEqual(clamped['page'], 2)
        self.assertEqual(len(clamped['jobs']), 2)

    def test_query_validation_bounds_and_detail_missing(self):
        for query in ('page=-1', 'page=no', 'page_size=0', 'page_size=101',
                      'page_size=1.5', 'since=-1', 'since=no'):
            with self.subTest(query=query):
                self.assertEqual(self.request('/api/state?' + query)[0], 400)
        for size in (1, 100):
            status, state, _ = self.request(f'/api/state?page_size={size}')
            self.assertEqual(status, 200)
            self.assertEqual(state['page_size'], size)
        self.assertEqual(self.request('/api/jobs/missing')[0], 404)

    def test_old_schema_migration_preserves_data_row_order_and_is_idempotent(self):
        path = self.root / 'legacy.db'
        originals = [self.add(str(i)) for i in range(3)]
        old = sqlite3.connect(path)
        old.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,data TEXT NOT NULL)')
        for index, job in enumerate(originals):
            job.pop('revision', None)
            job['outputs'] = ['legacy output ' + str(index)]
            old.execute('INSERT INTO jobs VALUES (?,?)', (job['id'], json.dumps(job)))
        old.commit()
        old.close()
        migrated = Store(path)
        try:
            expected = [j['id'] for j in reversed(originals)]
            self.assertEqual(migrated.page()['job_order'], expected)
            for original in originals:
                restored = migrated.get(original['id'])
                self.assertEqual(restored['outputs'], original['outputs'])
                self.assertGreater(restored['revision'], 0)
            first = migrated.get(originals[0]['id'])
            first['title'] = 'updated oldest'
            migrated.save(first)
            self.assertEqual(migrated.page()['job_order'], expected)
            revision = migrated.revision()
        finally:
            migrated.close()
        reopened = Store(path)
        try:
            self.assertEqual(reopened.revision(), revision)
            self.assertEqual(reopened.page()['job_order'], expected)
        finally:
            reopened.close()

    def test_workspace_default_persistence_explicit_override(self):
        fake_home = self.root / 'home'
        fake_home.mkdir()
        with patch('relay.server.Path.home', return_value=fake_home), patch('os.getcwd', side_effect=AssertionError('must not use cwd')):
            default = resolve_workspace(self.store)
        self.assertEqual(default, (fake_home / 'AI-Run-Relay-workspace').resolve())
        self.assertTrue(default.is_dir())
        chosen = self.root / 'chosen'
        with patch('relay.server.Path.home', return_value=self.root / 'other-home'):
            self.assertEqual(resolve_workspace(self.store), default)
            self.assertEqual(resolve_workspace(self.store, chosen), chosen.resolve())
            self.assertEqual(resolve_workspace(self.store), chosen.resolve())

    def test_workspace_http_auth_validation_and_pinned_jobs(self):
        old = self.add('existing')
        _, state, _ = self.request('/api/state')
        token = {'X-Relay-Token': state['csrf_token']}
        target = self.root / 'new-workspace'
        target.mkdir()
        nested = target / 'nested'
        nested.mkdir()
        for headers in ({}, {**token, 'Origin': 'https://foreign.example'}):
            status, _, _ = self.request('/api/workspace', {'path': str(target)}, headers)
            self.assertEqual(status, 403)
        self.assertEqual(self.engine.workspace, (self.root / 'work').resolve())
        for value in ('relative', str(target / 'missing'), '', 42):
            self.assertEqual(self.request('/api/workspace', {'path': value}, token)[0], 400)
        status, result, _ = self.request('/api/workspace', {'path': str(target)}, token)
        self.assertEqual(status, 200)
        normalized_target = target.resolve()
        self.assertEqual(result['workspace'], str(normalized_target))
        self.assertEqual(self.store.setting('workspace'), str(normalized_target))
        self.assertEqual(self.store.get(old['id'])['cwd'], old['cwd'])
        self.assertEqual(self.store.get(old['id'])['workspace_root'], old['workspace_root'])
        self.assertEqual(self.add('new')['cwd'], str(target.resolve()))
        self.assertEqual(self.add('nested', cwd='nested')['cwd'], str(nested.resolve()))
        with self.assertRaises(ValueError):
            self.add('escape', cwd='../work')


if __name__ == '__main__':
    unittest.main()
