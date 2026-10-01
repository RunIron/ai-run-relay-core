"""Native executable entry point, including an isolated installation smoke test."""
import json
from pathlib import Path
import sys
import tempfile
import time
import urllib.request


def self_test(report):
    import tkinter
    # No display required, but verifies the packaged Tcl binary and scripts load.
    assert tkinter.Tcl().eval('info patchlevel')
    from . import __version__
    from .desktop import LocalService
    with tempfile.TemporaryDirectory(prefix='relay-smoke-') as folder:
        service = LocalService(Path(folder) / 'data', Path(folder) / 'workspace')
        try:
            # Ensure bundled HTML, HTTP, SQLite and the worker work without Python installed.
            client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with client.open(service.url, timeout=5) as response:
                assert b'AI Run Relay' in response.read()
            job = service.engine.add({'title': 'Install smoke', 'provider': 'mock',
                'steps': ['one', 'two'], 'wait_seconds': 1})
            deadline = time.monotonic() + 30
            saw_wait = False
            while time.monotonic() < deadline:
                current = service.store.get(job['id'])
                saw_wait |= current['status'] == 'waiting_quota'
                if current['status'] == 'succeeded':
                    break
                time.sleep(.1)
            assert current['status'] == 'succeeded', current['status']
            assert saw_wait, 'quota wait was not observed'
            assert len(current['outputs']) == 2
            with client.open(service.url + '/api/state', timeout=5) as response:
                state = json.load(response)
            assert all('outputs' not in item for item in state['jobs'])
        finally:
            service.close()
        # A restart must release the lock and preserve the completed job.
        restarted = LocalService(Path(folder) / 'data')
        try:
            assert restarted.store.get(job['id'])['status'] == 'succeeded'
        finally:
            restarted.close()
    Path(report).write_text(json.dumps({'ok': True, 'version': __version__,
        'mock_only': True, 'saw_wait': saw_wait}), encoding='utf-8')


def main():
    if len(sys.argv) == 3 and sys.argv[1] == '--self-test':
        self_test(sys.argv[2])
        return 0
    if '--server' in sys.argv:
        sys.argv.remove('--server')
        from .server import main as serve
        serve()
        return 0
    if len(sys.argv) > 1:
        from .server import main as cli
        cli()
        return 0
    from .desktop import main as desktop
    return desktop()
