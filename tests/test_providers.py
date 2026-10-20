"""Providers are pluggable: Engine must not hardcode the 'codex' name anywhere."""
import tempfile
import unittest
from pathlib import Path

from relay.codex import CodexAdapter
from relay.core import Engine, Store
from relay.providers import Provider, Result


class FakeAdapter:
    def __init__(self, available=True):
        self._available = available

    def available(self):
        return self._available

    def run(self, job, prompt, session, stop):
        session('saved-session')
        return Result('success', output='done')


class ProviderProtocolTests(unittest.TestCase):
    def test_codex_adapter_satisfies_the_protocol(self):
        self.assertIsInstance(CodexAdapter(), Provider)

    def test_arbitrary_duck_typed_object_satisfies_the_protocol(self):
        self.assertIsInstance(FakeAdapter(), Provider)

    def test_object_missing_run_does_not_satisfy_the_protocol(self):
        class Incomplete:
            def available(self):
                return True
        self.assertNotIsInstance(Incomplete(), Provider)


class PluggableEngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / 'queue.db')

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def engine(self, adapters):
        return Engine(self.store, self.root / 'work', adapters, lambda: 1000)

    def test_a_non_codex_provider_name_is_accepted_when_registered(self):
        engine = self.engine({'demo': FakeAdapter()})
        job = engine.add({'title': 'test', 'provider': 'demo', 'steps': ['one']})
        self.assertEqual(job['provider'], 'demo')

    def test_an_unregistered_provider_name_is_still_rejected(self):
        engine = self.engine({'demo': FakeAdapter()})
        with self.assertRaises(ValueError):
            engine.add({'title': 'test', 'provider': 'codex', 'steps': ['one']})

    def test_mock_is_always_accepted_even_with_no_adapters(self):
        engine = self.engine({})
        job = engine.add({'title': 'test', 'provider': 'mock', 'steps': ['one']})
        self.assertEqual(job['provider'], 'mock')

    def test_state_reports_availability_for_every_registered_adapter_by_name(self):
        engine = self.engine({'demo': FakeAdapter(available=True), 'other': FakeAdapter(available=False)})
        providers = engine.state()['providers']
        self.assertEqual(providers, {'mock': True, 'demo': True, 'other': False})


if __name__ == '__main__':
    unittest.main()
