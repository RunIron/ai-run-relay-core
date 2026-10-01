import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from relay.codex import CodexAdapter, quota_wait

SERVER = r'''#!/usr/bin/env python3
import json, sys, time
from pathlib import Path
mode = MODE
for line in sys.stdin:
    q = json.loads(line)
    m = q.get('method')
    if 'id' not in q or not m:
        continue
    with open('rpc.log', 'a') as log:
        log.write(json.dumps(q) + '\n')
    result = {}
    if m == 'turn/interrupt':
        print(json.dumps({'id': q['id'], 'result': {}}), flush=True)
        time.sleep(0.03)
        Path('interrupted').write_text('yes')
        print(json.dumps({'method': 'turn/completed', 'params': {'threadId': q['params']['threadId'], 'turn': {'id': q['params']['turnId'], 'status': 'interrupted'}}}), flush=True)
        continue
    if m == 'thread/resume' and mode in ('missing', 'authfail'):
        print(json.dumps({'id': q['id'], 'error': {'code': -32600, 'message': 'thread not found' if mode == 'missing' else 'Unauthorized'}}), flush=True)
        continue
    if m == 'config/read':
        result = {'config': {'mcp_servers': {'custom': {'command': 'do-not-run'}}}} if mode == 'mcp' else {'config': {}}
    if m == 'configRequirements/read':
        result = {'requirements': None}
    if m == 'account/read':
        result = {'account': {'type': 'apiKey' if mode == 'api' else 'chatgpt'}}
    if m == 'account/rateLimits/read':
        result = {'rateLimits': {'primary': {'usedPercent': 100 if mode == 'quota' else 1, 'resetsAt': 4102444800}, 'secondary': {'usedPercent': 100 if mode == 'quota' else 1, 'resetsAt': 4102444900}}}
    if m in ('thread/start', 'thread/resume'):
        assert q['params']['sandbox'] == 'read-only'
        assert q['params']['approvalPolicy'] == 'never'
        result = {'thread': {'id': q['params'].get('threadId', 'thread_1')}}
    if m == 'turn/start':
        assert q['params']['sandboxPolicy'] == {'type': 'readOnly', 'networkAccess': False}
        assert q['params']['approvalPolicy'] == 'never'
        result = {'turn': {'id': 'turn_1'}}
    if m == 'turn/start' and mode == 'race':
        time.sleep(0.3)
    print(json.dumps({'id': q['id'], 'result': result}), flush=True)
    if m == 'turn/start':
        if mode == 'eof':
            sys.exit(0)
        if mode == 'approval':
            print(json.dumps({'id': 999, 'method': 'item/permissions/requestApproval', 'params': {}}), flush=True)
        elif mode not in ('hang', 'race'):
            if mode in ('phases', 'commentary', 'partial'):
                for item in ([{'id': 'c', 'text': 'Working', 'phase': 'commentary'}] if mode != 'partial' else []):
                    print(json.dumps({'method': 'item/completed', 'params': {'turnId': 'turn_1', 'item': dict(item, type='agentMessage')}}), flush=True)
                print(json.dumps({'method': 'item/agentMessage/delta', 'params': {'turnId': 'turn_1', 'itemId': 'partial', 'delta': 'Incomplete'}}), flush=True)
            if mode in ('commentary', 'partial'):
                print(json.dumps({'method': 'turn/completed', 'params': {'turn': {'id': 'turn_1', 'status': 'completed'}}}), flush=True)
                continue
            print(json.dumps({'method': 'item/completed', 'params': {'threadId': q['params']['threadId'], 'turnId': 'turn_1', 'item': {'type': 'agentMessage', 'id': 'm1', 'text': 'Finished safely', 'phase': 'final_answer'}}}), flush=True)
            print(json.dumps({'method': 'turn/completed', 'params': {'turn': {'id': 'turn_1', 'status': 'completed'}}}), flush=True)
'''


class CodexTest(unittest.TestCase):
    def run_fake(self, mode, session=None, stop=None, timeout=5):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / 'fake-codex'
            binary.write_text(SERVER.replace('MODE', repr(mode)))
            binary.chmod(0o700)
            rpc_log = Path(tmp) / 'rpc.log'
            rpc_log.touch()
            sessions = []
            result = CodexAdapter(str(binary), timeout=timeout).run(
                {'id': 'job1', 'cwd': tmp, 'session_id': session, 'outputs': ['saved checkpoint']}, 'Analyze text', sessions.append, stop or threading.Event())
            self.rpc = [__import__('json').loads(line) for line in rpc_log.read_text().splitlines()]
            self.interrupted = (Path(tmp) / 'interrupted').exists()
            return result, sessions

    def test_start(self):
        result, sessions = self.run_fake('success')
        self.assertEqual((result.kind, result.output), ('success', 'Finished safely'))
        self.assertEqual(sessions, ['thread_1'])

    def test_resume(self):
        result, sessions = self.run_fake('success', 'existing-thread')
        self.assertEqual(result.kind, 'success')
        self.assertEqual(sessions, ['existing-thread'])

    def test_refuse_api(self):
        result, sessions = self.run_fake('api')
        self.assertEqual(result.kind, 'review')
        self.assertEqual(sessions, [])

    def test_quota_secondary(self):
        result, sessions = self.run_fake('quota')
        self.assertEqual((result.kind, result.retry_at), ('quota', 4102444900))
        self.assertEqual(sessions, [])

    def test_unknown_reset(self):
        self.assertEqual(quota_wait({'primary': {'usedPercent': 100}}), (True, None))
        self.assertEqual(quota_wait({'primary': {'usedPercent': 100, 'resetsAt': 4102444900}, 'secondary': {'usedPercent': 100}}), (True, None))

    def test_permission_pauses(self):
        result, _ = self.run_fake('approval')
        self.assertEqual(result.kind, 'review')

    def test_cancel_hung_server(self):
        stop = threading.Event()
        timer = threading.Timer(0.2, stop.set)
        timer.start()
        try:
            result, _ = self.run_fake('hang', stop=stop)
            self.assertEqual(result.kind, 'cancelled')
            self.assertTrue(self.interrupted)
            self.assertEqual(self.rpc[-1]['method'], 'turn/interrupt')
        finally:
            timer.cancel()

    def test_external_mcp_blocks(self):
        result, sessions = self.run_fake('mcp')
        self.assertEqual(result.kind, 'review')
        self.assertEqual(sessions, [])

    def test_eof_needs_review(self):
        result, _ = self.run_fake('eof')
        self.assertEqual(result.kind, 'review')

    def test_selective_resume_recovery(self):
        result, sessions = self.run_fake('missing', session='old')
        self.assertEqual(result.kind, 'success')
        self.assertEqual(sessions, ['thread_1'])
        self.assertTrue(result.notices)
        self.assertIn('saved checkpoint', next(q for q in self.rpc if q['method'] == 'turn/start')['params']['input'][0]['text'])
        result, sessions = self.run_fake('authfail', session='old')
        self.assertEqual(result.kind, 'review')
        self.assertNotIn('thread/start', [q['method'] for q in self.rpc])

    def test_final_not_commentary_or_delta(self):
        result, _ = self.run_fake('phases')
        self.assertEqual(result.output, 'Finished safely')
        self.assertEqual(result.partial_output, 'Incomplete')
        for mode in ('commentary', 'partial'):
            result, _ = self.run_fake(mode)
            self.assertEqual(result.kind, 'review')
            self.assertEqual(result.output, '')

    def test_unrelated_quota(self):
        self.assertEqual(quota_wait({'rateLimitsByLimitId': {'other': {'primary': {'usedPercent': 100}}}}), (False, None))
        self.assertEqual(quota_wait({'rateLimitsByLimitId': {'codex': {'primary': {'usedPercent': 1}}, 'other': {'primary': {'usedPercent': 100}}}}), (False, None))

    def test_interrupt_start_response_race(self):
        result, _ = self.run_fake('race', timeout=0.15)
        self.assertEqual(result.kind, 'review')
        self.assertTrue(self.interrupted)

    def test_timeout(self):
        result, _ = self.run_fake('hang', timeout=0.15)
        self.assertEqual(result.kind, 'review')
        self.assertTrue(self.interrupted)


if __name__ == '__main__':
    unittest.main()
