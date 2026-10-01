import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile

path = Path(__file__).resolve().parents[1] / "tools/package_release.py"
spec = importlib.util.spec_from_file_location("package_release", path)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class DistributionTest(unittest.TestCase):
    def test_public_allowlist_excludes_core_and_unexpected_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'public').mkdir()
            for name in release.PUBLIC_FILES:
                (root / 'public' / name).write_text('Public introduction')
            (root / 'public' / 'accidental_core.py').write_text('SECRET_IMPLEMENTATION')
            archive = root / 'public.zip'
            release.public_package(archive, root)
            with zipfile.ZipFile(archive) as z:
                self.assertEqual(set(z.namelist()), {'ai-run-relay/' + f for f in release.PUBLIC_FILES})
                self.assertFalse(any(b'SECRET_IMPLEMENTATION' in z.read(n) for n in z.namelist()))

    def test_owner_package_contains_source_but_not_private_state(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / 'owner.zip'
            release.owner_package(archive)
            with zipfile.ZipFile(archive) as z:
                names = z.namelist()
                self.assertIn('ai-run-relay/relay/core.py', names)
                self.assertIn('ai-run-relay/relay/codex.py', names)
                self.assertFalse(any('.git/' in n or n.endswith(('.sqlite3', '.whl', '.pyc')) for n in names))
