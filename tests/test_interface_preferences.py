from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
# CJK ideographs, CJK punctuation and full-width forms (U+FF0B, the plus button glyph, is allowed).
CJK = re.compile('[\u3000-\u303f\u4e00-\u9fff\uff00-\uff0a\uff0c-\uffef]')


class InterfacePreferenceTests(unittest.TestCase):
    def test_dashboard_is_english_only(self):
        html = (ROOT / 'relay/static/index.html').read_text(encoding='utf-8')
        self.assertIn('<html lang="en">', html)
        self.assertIn('Work queue', html)
        self.assertIn('Codex usage', html)
        self.assertNotIn('id="language"', html)
        self.assertNotIn('translations', html)

    def test_management_tools_are_collapsible_and_remembered(self):
        html = (ROOT / 'relay/static/index.html').read_text(encoding='utf-8')
        self.assertIn('id="adminTools"', html)
        self.assertIn('relay-admin-tools-open', html)
        self.assertIn('Settings &amp; tools', html)
        self.assertIn('workspaceForm', html)
        # The new-job form must stay visible; only settings collapse.
        self.assertLess(html.index('id="jobForm"'), html.index('id="adminTools"'))

    def test_desktop_launcher_uses_english_labels(self):
        source = (ROOT / 'relay/desktop.py').read_text(encoding='utf-8')
        self.assertIn('Choose workspace folder', source)
        self.assertIn('Open dashboard', source)
        self.assertIn('Stop scheduling and save progress?', source)

    def test_shipped_text_has_no_chinese(self):
        files = [*(ROOT / 'relay').rglob('*.py'), ROOT / 'relay/static/index.html',
                 *ROOT.glob('*.md'), *(ROOT / 'docs').glob('*.md'), *(ROOT / 'public').glob('*.md')]
        for path in files:
            with self.subTest(path=path.relative_to(ROOT).as_posix()):
                for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                    self.assertIsNone(CJK.search(line), f'line {number}: {line.strip()[:80]}')


if __name__ == '__main__':
    unittest.main()
