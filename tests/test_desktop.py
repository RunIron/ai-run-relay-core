import tempfile
from pathlib import Path
import unittest

from relay.desktop import LocalService
from relay.entry import self_test


class DesktopTest(unittest.TestCase):
    def test_install_smoke_wait_output_restart(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / 'smoke.json'
            self_test(report)
            result = json.loads(report.read_text())
            self.assertTrue(result['ok'])
            self.assertTrue(result['saw_wait'])

    def test_instance_lock_and_workspace_survive_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder) / 'data'
            workspace = Path(folder) / 'my work'
            service = LocalService(data, workspace)
            try:
                with self.assertRaises(RuntimeError):
                    LocalService(data)
                job = service.engine.add({'title': 'Retain', 'provider': 'mock', 'steps': ['one']})
            finally:
                service.close()
            service = LocalService(data)
            try:
                self.assertEqual(service.store.setting('workspace'), str(workspace.resolve()))
                self.assertEqual(service.store.get(job['id'])['title'], 'Retain')
            finally:
                service.close()
                service.close()  # idempotent cleanup
