import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from relay.core import Engine, Store
from relay.server import make_server


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.store = Store(root / 'queue.db')
        cls.engine = Engine(cls.store, root / 'work', {})
        cls.server = make_server(cls.engine, 0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.host = f'127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.store.close()
        cls.tmp.cleanup()

    def request(self, method, path, data=None, **headers):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        try:
            body = json.dumps(data) if data is not None else None
            conn.request(method, path, body, {'Host': self.host, 'Content-Type': 'application/json', **headers})
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        finally:
            conn.close()

    def test_host_origin_and_csrf_protect_writes(self):
        status, state = self.request('GET', '/api/state')
        self.assertEqual(status, 200)
        token = state['csrf_token']
        status, _ = self.request('GET', '/api/state', Host='attacker.example')
        self.assertEqual(status, 403)
        payload = {'title': 'from HTTP', 'steps': ['analyze']}
        initial = len(self.store.jobs())
        for headers in ({}, {'X-Relay-Token': 'wrong'},
                        {'X-Relay-Token': token, 'Origin': 'https://attacker.example'},
                        {'X-Relay-Token': token, 'Host': 'attacker.example'}):
            with self.subTest(headers=headers):
                status, _ = self.request('POST', '/api/jobs', payload, **headers)
                self.assertEqual(status, 403)
        self.assertEqual(len(self.store.jobs()), initial)
        status, job = self.request('POST', '/api/jobs', payload,
                                   **{'X-Relay-Token': token, 'Origin': f'http://{self.host}'})
        self.assertEqual(status, 201)
        self.assertEqual(self.store.get(job['id'])['title'], 'from HTTP')

    def test_invalid_body_rejected_and_pause_controls_queue(self):
        _, state = self.request('GET', '/api/state')
        auth = {'X-Relay-Token': state['csrf_token']}
        status, _ = self.request('POST', '/api/jobs', [], **auth)
        self.assertEqual(status, 400)
        status, _ = self.request('POST', '/api/control', {'action': 'pause'}, **auth)
        self.assertEqual(status, 200)
        self.assertTrue(self.engine.state()['paused'])
        self.assertFalse(self.engine.tick())
        self.request('POST', '/api/control', {'action': 'resume'}, **auth)
        self.assertFalse(self.engine.state()['paused'])


if __name__ == '__main__':
    unittest.main()
