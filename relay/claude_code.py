"""Official Claude Code CLI subprocess adapter. No credential parsing, no private
HTTP endpoints — same principle as relay/codex.py.

Protocol notes (verified by hand against `claude` 2.1.304, 2026-10-20; there is
no persistent app-server for Claude Code the way there is for Codex, so each
step is one blocking `claude -p` call, not a kept-open session):

- `claude -p "<prompt>" --output-format json [--resume <id>]` runs one turn and
  prints a single JSON object on success: {"type":"result","subtype":"success",
  "is_error":false,"result":"<text>","session_id":"<uuid>", ...}.
- `--resume <session_id>` continues that session id; an id Claude Code no
  longer has prints a plain-text "No conversation found with session ID: ..."
  to stdout (NOT JSON, even with --output-format json) and exits 1.
- Read-only enforcement verified empirically with `--permission-mode dontAsk
  --permission-prompts none --restricted --strict-mcp-config --safe-mode
  --disallowedTools "Bash,Edit,Write,NotebookEdit,Task,WebFetch,ExitPlanMode"`:
  blocks writes/exec/fetch/subagents and any project/user hooks or MCP
  servers, while Read/Grep/Glob still work for analysis. A write attempt
  under this flag set produces a normal is_error:false explanation, not a
  file — confirmed no file is created in the job's cwd.
  `--permission-mode plan` looked like the obvious choice first but is NOT
  used here: it writes a plan markdown file to ~/.claude/plans/ as a side
  effect even with every write tool disallowed — a real, observed violation
  of "no file writes" that only shows up outside the job's own workspace, so
  it's easy to miss if you only check the cwd. Disallowing `ExitPlanMode`
  specifically (on top of a non-plan permission mode) is what stops it.
- There is no official structured rate-limit query (unlike Codex's
  `account/rateLimits/read`), so a hit is detected the same way
  https://github.com/dujunyi416/claude-nightshift detects it: by matching
  known phrases in the failure text. Unlike that project we never read
  ~/.claude/.credentials.json or call any undocumented endpoint; detection
  is limited to the text this subprocess itself prints. The reset time is
  therefore always unknown (quota=None, retry_at=None), falling back to the
  engine's estimated backoff — see docs/ARCHITECTURE.md#providers.

Known limitation, documented rather than hidden: Anthropic's Agent SDK terms
restrict third-party products from offering claude.ai sign-in/rate-limit
reuse without prior approval (https://docs.claude.com/en/docs/agent-sdk/overview).
This adapter reuses the local `claude` CLI's own subscription session exactly
like relay/codex.py does for ChatGPT; that choice carries a real compliance
question this project has not resolved. See docs/ARCHITECTURE.md#providers.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time
from typing import Callable

from .providers import Provider, Result

__all__ = ['Result', 'ClaudeCodeAdapter']

# Lowercased substrings that mark a usage-limit cutoff, as opposed to other
# failures (auth, overloaded, network) we should not blindly retry. Reused
# from the field-tested list in dujunyi416/claude-nightshift (MIT), since no
# official error code or exit status distinguishes this case.
_LIMIT_TEXTS = ('hit your session limit', 'usage limit', 'rate limit',
                'limit reached', 'hit your limit', 'weekly limit',
                'usage_limit', 'rate_limit')

_NO_SESSION_TEXTS = ('no conversation found', 'session not found', 'no session found')

# See codex.py's _NO_WINDOW: avoids a flashing console for the packaged app.
_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

# Never let the job touch anything but reading: no file writes, no shell, no
# network fetch, no subagents, no project/user hooks or MCP servers. Verified
# empirically (see module docstring) rather than assumed from --help text.
_READ_ONLY_FLAGS = [
    '--permission-mode', 'dontAsk',
    '--permission-prompts', 'none',
    '--restricted',
    '--strict-mcp-config',
    '--safe-mode',
    '--disallowedTools', 'Bash,Edit,Write,NotebookEdit,Task,WebFetch,ExitPlanMode',
]


def _is_limit_text(text):
    low = (text or '').lower()
    return any(marker in low for marker in _LIMIT_TEXTS)


def _is_missing_session_text(text):
    low = (text or '').lower()
    return any(marker in low for marker in _NO_SESSION_TEXTS)


class ClaudeCodeAdapter(Provider):
    def __init__(self, executable='claude', timeout=900):
        self.executable = executable
        self.timeout = timeout

    def available(self) -> bool:
        candidate = os.fspath(self.executable)
        return (candidate.lower().endswith('.py') and Path(candidate).is_file()) or shutil.which(candidate) is not None

    def _command(self, executable, prompt, session_id):
        # The prompt MUST come immediately after -p: --disallowedTools (and any
        # other "<tools...>" style flag) takes a variadic list of following
        # tokens, so a trailing prompt with nothing after it gets silently
        # swallowed as another tool name instead of being read as the prompt
        # (verified against the real CLI: produces "Input must be provided
        # either through stdin or as a prompt argument").
        command = [executable, '-p', prompt, '--output-format', 'json'] + _READ_ONLY_FLAGS
        if session_id:
            command += ['--resume', session_id]
        if str(executable).lower().endswith('.py'):
            command = [sys.executable, executable, *command[1:]]
        return command

    def _invoke(self, executable, prompt, session_id, job, stop):
        env = dict(os.environ)
        env.pop('ANTHROPIC_API_KEY', None)  # force subscription auth; never separately-billed API usage
        proc = subprocess.Popen(self._command(executable, prompt, session_id),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
            text=True, encoding='utf-8', errors='replace', env=env, cwd=job['cwd'],
            start_new_session=(os.name == 'posix'), creationflags=_NO_WINDOW)
        deadline = time.monotonic() + self.timeout
        try:
            while True:
                if proc.poll() is not None:
                    break
                if stop.is_set():
                    return proc, None, None, 'cancelled'
                if time.monotonic() >= deadline:
                    return proc, None, None, 'timeout'
                stop.wait(0.2)
            stdout, stderr = proc.communicate()
            return proc, stdout, stderr, None
        finally:
            if proc.poll() is None:
                self._kill(proc)
            for stream in (proc.stdout, proc.stderr):
                if stream:
                    try:
                        stream.close()
                    except OSError:
                        pass

    @staticmethod
    def _kill(proc):
        try:
            if os.name == 'posix':
                os.killpg(proc.pid, signal.SIGTERM)
            else:
                subprocess.run(['taskkill', '/T', '/F', '/PID', str(proc.pid)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
                               creationflags=_NO_WINDOW)
            proc.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            try:
                if os.name == 'posix':
                    os.killpg(proc.pid, signal.SIGKILL)
                else:
                    proc.kill()
            except OSError:
                pass
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass

    def run(self, job: dict, prompt: str, on_session: Callable[[str], None], stop: threading.Event) -> Result:
        if stop.is_set():
            return Result('cancelled')
        candidate = os.fspath(self.executable)
        executable = candidate if candidate.lower().endswith('.py') and Path(candidate).is_file() else shutil.which(candidate)
        if executable is None:
            return Result('review', error='Claude Code CLI was not found. Install it, then run `claude` once '
                          'in a terminal and complete sign-in with your Claude subscription.')

        session_id = job.get('session_id')
        notices = []
        proc, stdout, stderr, interrupted = self._invoke(executable, prompt, session_id, job, stop)
        if interrupted == 'cancelled':
            return Result('cancelled')
        if interrupted == 'timeout':
            return Result('review', error='Claude Code timed out. Saved progress is kept; review the job before resuming.')

        payload = None
        try:
            payload = json.loads(stdout) if stdout else None
        except ValueError:
            payload = None

        if payload is None:
            combined = (stdout or '') + '\n' + (stderr or '')
            if session_id and _is_missing_session_text(combined):
                notices.append('The original session no longer exists. Starting a new one from the saved checkpoint.')
                resync_prompt = prompt + '\n\nSaved results from earlier steps (for session recovery):\n' + \
                    json.dumps(job.get('outputs', []), ensure_ascii=False)
                proc2, stdout2, stderr2, interrupted2 = self._invoke(executable, resync_prompt, None, job, stop)
                if interrupted2 == 'cancelled':
                    return Result('cancelled')
                if interrupted2 == 'timeout':
                    return Result('review', error='Claude Code timed out. Saved progress is kept; review the job before resuming.', notices=notices)
                try:
                    payload = json.loads(stdout2) if stdout2 else None
                except ValueError:
                    payload = None
                if payload is None:
                    return Result('review', error='Unexpected Claude Code response after session recovery. Check the CLI version.', notices=notices)
                stdout, stderr, proc = stdout2, stderr2, proc2
            elif _is_limit_text(combined):
                return Result('quota', retry_at=None, notices=notices)
            else:
                return Result('review', error='Unexpected Claude Code output (not valid JSON). Check the CLI version and sign-in status.', notices=notices)

        new_session_id = payload.get('session_id')
        if new_session_id and new_session_id != session_id:
            on_session(new_session_id)

        if payload.get('is_error'):
            text = json.dumps(payload)
            if _is_limit_text(text):
                return Result('quota', retry_at=None, notices=notices)
            return Result('review', error='Claude Code reported an error. Review it before resuming: '
                          + str(payload.get('result') or payload.get('subtype') or 'unknown error'), notices=notices)

        output = (payload.get('result') or '').strip()
        if not output:
            # Never checkpoint an empty result as a finished step.
            return Result('review', error='Claude Code reported completion but returned no text result. Check the session before resuming.', notices=notices)
        return Result('success', output=output, notices=notices)
