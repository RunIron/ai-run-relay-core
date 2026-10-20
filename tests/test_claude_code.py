import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest

from relay.claude_code import ClaudeCodeAdapter

FAKE = r'''#!/usr/bin/env python3
import json, os, sys, time
from pathlib import Path
args = sys.argv[1:]
mode = MODE
Path('argv.log').write_text('\n'.join(args))
Path('env.log').write_text('ANTHROPIC_API_KEY=' + os.environ.get('ANTHROPIC_API_KEY', '<absent>'))
prompt = args[args.index('-p') + 1]
resumed = '--resume' in args
session_id = args[args.index('--resume') + 1] if resumed else 'new-session-id'

if mode == 'hang':
    time.sleep(30)
    sys.exit(0)
if mode == 'slow_then_ok':
    time.sleep(1.5)

if mode == 'missing_session' and resumed:
    sys.stdout.write('No conversation found with session ID: ' + session_id + '\n')
    sys.exit(1)

if mode == 'quota_garbage':
    sys.stdout.write("Error: you've hit your session limit, try again later\n")
    sys.exit(1)

if mode == 'garbage':
    sys.stdout.write('some unrelated CLI crash text\n')
    sys.exit(1)

if mode == 'empty':
    print(json.dumps({'type': 'result', 'subtype': 'success', 'is_error': False,
                      'result': '', 'session_id': session_id}))
    sys.exit(0)

if mode == 'error_is_error':
    print(json.dumps({'type': 'result', 'subtype': 'error_during_execution', 'is_error': True,
                      'result': 'Something went wrong', 'session_id': session_id}))
    sys.exit(0)

if mode == 'error_quota':
    print(json.dumps({'type': 'result', 'subtype': 'error_during_execution', 'is_error': True,
                      'result': "You've hit your weekly limit, resets soon", 'session_id': session_id}))
    sys.exit(0)

print(json.dumps({'type': 'result', 'subtype': 'success', 'is_error': False,
                  'result': 'Finished safely' + (' (resumed)' if resumed else ''),
                  'session_id': session_id}))
'''


class ClaudeCodeTest(unittest.TestCase):
    def run_fake(self, mode, session=None, stop=None, timeout=5, outputs=None, env=None):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / 'fake-claude.py'
            binary.write_text(FAKE.replace('MODE', repr(mode)))
            binary.chmod(0o700)
            sessions = []
            old_env = {}
            for k, v in (env or {}).items():
                old_env[k] = os.environ.get(k)
                os.environ[k] = v
            try:
                result = ClaudeCodeAdapter(str(binary), timeout=timeout).run(
                    {'id': 'job1', 'cwd': tmp, 'session_id': session, 'outputs': outputs or ['saved checkpoint']},
                    'Analyze text', sessions.append, stop or threading.Event())
            finally:
                for k, v in old_env.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
            argv_log = Path(tmp) / 'argv.log'
            env_log = Path(tmp) / 'env.log'
            self.argv = argv_log.read_text().splitlines() if argv_log.exists() else []
            self.env_seen = env_log.read_text() if env_log.exists() else ''
            return result, sessions

    def test_start_reports_session_and_output(self):
        result, sessions = self.run_fake('success')
        self.assertEqual((result.kind, result.output), ('success', 'Finished safely'))
        self.assertEqual(sessions, ['new-session-id'])

    def test_resume_passes_existing_session_id(self):
        result, sessions = self.run_fake('success', session='existing-session')
        self.assertEqual(result.kind, 'success')
        self.assertIn('--resume', self.argv)
        self.assertEqual(self.argv[self.argv.index('--resume') + 1], 'existing-session')
        self.assertEqual(result.output, 'Finished safely (resumed)')

    def test_prompt_immediately_follows_dash_p(self):
        # Regression: --disallowedTools (and any other "<tools...>" variadic
        # flag) swallows a trailing prompt with nothing after it, silently
        # turning it into a tool name instead of the prompt. The real CLI then
        # refuses with "Input must be provided either through stdin or as a
        # prompt argument" (verified by hand, not just against this fake).
        self.run_fake('success')
        self.assertEqual(self.argv[self.argv.index('-p') + 1], 'Analyze text')

    def test_read_only_flags_are_always_passed(self):
        self.run_fake('success')
        for flag in ('--permission-mode', 'dontAsk', '--permission-prompts', 'none',
                     '--restricted', '--strict-mcp-config', '--safe-mode',
                     '--output-format', 'json'):
            self.assertIn(flag, self.argv)
        disallowed = self.argv[self.argv.index('--disallowedTools') + 1]
        for tool in ('Bash', 'Edit', 'Write', 'NotebookEdit', 'Task', 'WebFetch', 'ExitPlanMode'):
            self.assertIn(tool, disallowed)

    def test_permission_mode_is_not_plan(self):
        # Regression: --permission-mode plan writes a plan markdown file to
        # ~/.claude/plans/ as a side effect, even with every write tool
        # disallowed — observed by hand against the real CLI, outside the
        # job's own cwd so it's easy to miss. Disallowing ExitPlanMode on a
        # non-plan permission mode is what actually stops it (see module
        # docstring). If this ever changes back to 'plan', it must come with
        # a new real-CLI check that no file appears under ~/.claude/plans/.
        self.run_fake('success')
        self.assertEqual(self.argv[self.argv.index('--permission-mode') + 1], 'dontAsk')

    def test_api_key_is_stripped_to_force_subscription_auth(self):
        self.run_fake('success', env={'ANTHROPIC_API_KEY': 'sk-should-not-be-seen'})
        self.assertEqual(self.env_seen, 'ANTHROPIC_API_KEY=<absent>')

    def test_missing_session_recovers_with_a_new_one(self):
        result, sessions = self.run_fake('missing_session', session='gone-session', outputs=['step one result'])
        self.assertEqual(result.kind, 'success')
        self.assertEqual(sessions, ['new-session-id'])
        self.assertTrue(any('no longer exists' in n for n in result.notices))

    def test_quota_detected_from_plain_text_non_json_failure(self):
        result, _ = self.run_fake('quota_garbage')
        self.assertEqual(result.kind, 'quota')
        self.assertIsNone(result.retry_at)

    def test_quota_detected_from_structured_is_error_result(self):
        result, _ = self.run_fake('error_quota')
        self.assertEqual(result.kind, 'quota')
        self.assertIsNone(result.retry_at)

    def test_unrelated_is_error_result_needs_review(self):
        result, _ = self.run_fake('error_is_error')
        self.assertEqual(result.kind, 'review')
        self.assertIn('Something went wrong', result.error)

    def test_unrelated_garbage_output_needs_review(self):
        result, _ = self.run_fake('garbage')
        self.assertEqual(result.kind, 'review')

    def test_empty_result_is_not_checkpointed_as_success(self):
        result, _ = self.run_fake('empty')
        self.assertEqual(result.kind, 'review')

    def test_timeout_is_reviewed_not_silently_retried(self):
        result, _ = self.run_fake('hang', timeout=0.3)
        self.assertEqual(result.kind, 'review')
        self.assertIn('timed out', result.error)

    def test_cancel_before_launch_never_spawns_a_process(self):
        stop = threading.Event()
        stop.set()
        result, _ = self.run_fake('success', stop=stop)
        self.assertEqual(result.kind, 'cancelled')
        self.assertEqual(self.argv, [])

    def test_cancel_mid_run_stops_the_process(self):
        stop = threading.Event()

        def trigger():
            time.sleep(0.2)
            stop.set()
        threading.Thread(target=trigger).start()
        result, _ = self.run_fake('slow_then_ok', stop=stop, timeout=5)
        self.assertEqual(result.kind, 'cancelled')

    def test_available_true_for_an_executable_file_false_otherwise(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / 'fake-claude.py'
            binary.write_text(FAKE.replace('MODE', repr('success')))
            binary.chmod(0o700)
            self.assertTrue(ClaudeCodeAdapter(str(binary)).available())
        self.assertFalse(ClaudeCodeAdapter('definitely-not-a-real-claude-binary-xyz').available())


if __name__ == '__main__':
    unittest.main()
