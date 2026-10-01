"""Official Codex app-server stdio adapter. No credential parsing or API fallback."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time
from typing import Callable

from . import __version__


@dataclass
class Result:
    kind: str
    output: str = ''
    error: str = ''
    retry_at: float | None = None
    quota: dict | None = None
    notices: list[str] = field(default_factory=list)
    partial_output: str = ''


def _seconds(value):
    """Accept Unix seconds or milliseconds; return seconds or None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value) / 1000 if value > 1e11 else float(value)


def _used(node):
    value = node.get('usedPercent') if isinstance(node, dict) else None
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def quota_wait(quota: dict, limit_id: str = 'codex') -> tuple[bool, float | None]:
    """Select the metered bucket; unrelated/unknown buckets never block this job."""
    if not isinstance(quota, dict):
        return False, None
    mapping = quota.get('rateLimitsByLimitId')
    bucket = mapping.get(limit_id) if isinstance(mapping, dict) else None
    if not isinstance(bucket, dict):
        candidate = quota.get('rateLimits', quota)
        # Legacy single-bucket responses omitted limitId. With a mapping present,
        # require an explicit match instead of guessing its identity.
        if not isinstance(candidate, dict) or candidate.get('limitId') not in (
                (limit_id,) if isinstance(mapping, dict) else (None, limit_id)):
            return False, None
        bucket = candidate
    exhausted, unknown, resets = False, False, []
    for key in ('primary', 'secondary'):
        window = bucket.get(key)
        if _used(window) >= 100:
            exhausted = True
            reset = _seconds(window.get('resetsAt'))
            if reset is not None and reset > time.time():
                resets.append(reset)
            else:
                unknown = True
    if bucket.get('rateLimitReachedType') and not exhausted:
        exhausted, unknown = True, True
    return exhausted, max(resets) if resets and not unknown else None


def _missing_thread(error):
    """Fail over only for explicit thread absence, never general 404/auth errors."""
    if not isinstance(error, dict):
        return False
    code = str(error.get('code', '')).lower()
    if code in ('thread_not_found', 'thread_expired'):
        return True
    message = str(error.get('message', '')).lower()
    return any(marker in message for marker in (
        'thread not found', 'thread has expired', 'thread expired',
        'no rollout found for thread id', 'no rollout found for thread'))


class _Abort(Exception):
    def __init__(self, kind, message):
        self.kind, self.message = kind, message


class _RPCError(Exception):
    def __init__(self, payload):
        self.payload = payload


def _is_quota(error):
    # Classification only; never store untrusted server error text.
    text = json.dumps(error).lower()
    return any(x in text for x in ('usagelimitexceeded', 'usage_limit_exceeded', 'ratelimitexceeded', 'rate_limit_exceeded', 'usage limit', 'rate limit'))


class CodexAdapter:
    def __init__(self, executable='codex', timeout=900, interrupt_timeout=2):
        self.executable = executable
        self.timeout = timeout
        self.interrupt_timeout = interrupt_timeout

    def available(self) -> bool:
        candidate = os.fspath(self.executable)
        return (candidate.lower().endswith('.py') and Path(candidate).is_file()) or shutil.which(candidate) is not None

    def run(self, job: dict, prompt: str, on_session: Callable[[str], None], stop: threading.Event) -> Result:
        if stop.is_set():
            return Result('cancelled')
        candidate = os.fspath(self.executable)
        executable = candidate if candidate.lower().endswith('.py') and Path(candidate).is_file() else shutil.which(candidate)
        if executable is None:
            return Result('review', error='找不到 Codex CLI；請先安裝並以 ChatGPT 帳號執行 codex login。')
        proc = None
        inbox = queue.Queue()
        messages, quota, pending = {}, {}, []
        completed_messages, notices = [], []
        turn_start_request = None
        turn_finished = False
        limit_id = job.get('limit_id') or 'codex'
        deadline = time.monotonic() + self.timeout
        seq = 0
        turn_id = None
        session_id = None
        def send(payload):
            proc.stdin.write(json.dumps(payload) + '\n')
            proc.stdin.flush()
        def reader():
            try:
                for line in proc.stdout:
                    try:
                        payload = json.loads(line)
                        if isinstance(payload, dict):
                            inbox.put(payload)
                    except ValueError:
                        continue
            finally:
                inbox.put(None)
        def receive(request_deadline=None):
            while True:
                if stop.is_set():
                    raise _Abort('cancelled', '')
                if time.monotonic() >= min(deadline, request_deadline or deadline):
                    raise _Abort('review', 'Codex 執行逾時；進度已保留，請檢查後再續做。')
                try:
                    payload = inbox.get(timeout=0.1)
                    if payload is None:
                        raise _Abort('review', 'Codex app-server 已結束；請檢查 CLI 與登入狀態。')
                    return payload
                except queue.Empty:
                    continue
        def event(payload):
            nonlocal quota
            method = payload.get('method', '')
            params = payload.get('params') or {}
            if 'id' in payload and method:
                if method in ('item/commandExecution/requestApproval', 'item/fileChange/requestApproval'):
                    result = {'decision': 'decline'}
                elif method == 'item/permissions/requestApproval':
                    result = {'permissions': {}, 'scope': 'turn'}
                elif method == 'mcpServer/elicitation/request':
                    result = {'action': 'decline', 'content': None}
                else:
                    send({'id': payload['id'], 'error': {'code': -32601, 'message': 'Interactive requests require manual review'}})
                    raise _Abort('review', '此工作需要人工輸入或核准，已暫停。')
                send({'id': payload['id'], 'result': result})
                raise _Abort('review', '此工作需要額外權限，已拒絕並暫停。')
            if method == 'account/updated' and params.get('authMode') != 'chatgpt':
                raise _Abort('review', '登入模式已改變；僅支援由官方 CLI 管理的 ChatGPT 登入。')
            if method == 'account/rateLimits/updated':
                quota = params
            if turn_id is None and params.get('turnId') is not None:
                # Notifications for the new turn can arrive before the turn/start
                # response; keep them for replay instead of dropping the output.
                pending.append(payload)
                return
            if params.get('threadId') not in (None, session_id):
                return
            if params.get('turnId') not in (None, turn_id):
                return
            if method == 'item/agentMessage/delta':
                key = params.get('itemId', 'reply')
                messages[key] = messages.get(key, '') + params.get('delta', '')
            if method == 'item/completed' and params.get('item', {}).get('type') == 'agentMessage':
                item = params['item']
                messages.pop(item['id'], None)
                completed_messages.append(item)
        def request(method, params=None, timeout=None):
            nonlocal seq, turn_start_request
            seq += 1
            rid = seq
            if method == 'turn/start':
                turn_start_request = rid
            send({'id': rid, 'method': method, 'params': params or {}})
            request_deadline = time.monotonic() + timeout if timeout is not None else None
            while True:
                payload = receive(request_deadline)
                if payload.get('id') == rid and not payload.get('method'):
                    if 'error' in payload:
                        raise _RPCError(payload['error'])
                    return payload.get('result') or {}
                if payload.get('method') == 'turn/completed':
                    pending.append(payload)
                else:
                    event(payload)
        def output():
            finals = [item for item in completed_messages if item.get('phase') == 'final_answer']
            legacy = [item for item in completed_messages if item.get('phase') is None]
            candidates = finals or legacy
            return candidates[-1].get('text', '') if candidates else ''
        def interrupt_active():
            # An independent bounded drain handles cancellation before turn/start's
            # reply. Never call receive(), which intentionally honors stop/deadline.
            nonlocal turn_id, turn_finished, seq
            if not session_id or turn_finished or turn_start_request is None:
                return
            until = time.monotonic() + self.interrupt_timeout
            sent = False
            while time.monotonic() < until:
                if turn_id and not sent:
                    seq += 1
                    send({'id': seq, 'method': 'turn/interrupt',
                          'params': {'threadId': session_id, 'turnId': turn_id}})
                    sent = True
                try:
                    payload = pending.pop(0) if pending else inbox.get(timeout=min(0.1, max(0.001, until - time.monotonic())))
                except queue.Empty:
                    continue
                if payload is None:
                    return
                params = payload.get('params') or {}
                if params.get('threadId') not in (None, session_id):
                    continue
                if payload.get('id') == turn_start_request and not payload.get('method'):
                    turn_id = (payload.get('result') or {}).get('turn', {}).get('id', turn_id)
                if payload.get('method') == 'turn/started':
                    turn_id = params.get('turn', {}).get('id', turn_id)
                if turn_id is None and params.get('turnId'):
                    turn_id = params['turnId']
                if payload.get('method') == 'turn/completed':
                    turn = params.get('turn') or {}
                    if turn_id is None:
                        turn_id = turn.get('id')
                    if turn.get('id') == turn_id and turn.get('status') in ('interrupted', 'completed', 'failed'):
                        turn_finished = True
                        if sent:
                            notices.append('已收到工作階段停止確認：' + turn.get('status', 'unknown'))
                        return
            notices.append('停止確認逾時，已關閉本機程序；請檢查原工作階段。')
        try:
            # Force subscription authentication/provider; never use inherited API keys.
            env = dict(os.environ)
            for key in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'OPENAI_BASE_URL'):
                env.pop(key, None)
            command = [executable, '-c', 'forced_login_method="chatgpt"', '-c', 'model_provider="openai"', '-c', 'features.apps=false', 'app-server']
            if str(executable).lower().endswith('.py'):
                command = [sys.executable, executable, *command[1:]]
            proc = subprocess.Popen(command,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding='utf-8', errors='replace', env=env, cwd=job['cwd'],
                start_new_session=(os.name == 'posix'))
            threading.Thread(target=reader, daemon=True).start()
            request('initialize', {'clientInfo': {'name': 'ai_run_relay', 'version': __version__}})
            send({'method': 'initialized', 'params': {}})
            account = request('account/read', {'refreshToken': False}).get('account') or {}
            if account.get('type') != 'chatgpt':
                return Result('review', error='請先使用官方 codex login 登入 ChatGPT；API key 登入不會執行。')
            # Inspect effective settings through the public protocol, never auth files.
            config = request('config/read', {'includeLayers': False, 'cwd': job['cwd']}).get('config')
            if not isinstance(config, dict):
                return Result('review', error='無法驗證 Codex 設定；請更新 CLI 後重試。')
            def enabled_entries(entries):
                return bool(entries) and (not isinstance(entries, dict) or any(
                    not isinstance(value, dict) or value.get('enabled') is not False
                    for value in entries.values()))
            unsafe = enabled_entries(config.get('mcp_servers')) or enabled_entries(config.get('plugins'))
            unsafe = unsafe or bool(config.get('hooks')) or bool(config.get('notify'))
            requirements = request('configRequirements/read').get('requirements') or {}
            unsafe = unsafe or bool(requirements.get('hooks'))
            # Standalone hook files are not necessarily included in config/read.
            codex_dir = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
            hook_paths = [codex_dir / 'hooks.json']
            cwd_path = Path(job['cwd']).resolve()
            hook_paths.extend(parent / '.codex' / 'hooks.json' for parent in (cwd_path, *cwd_path.parents))
            unsafe = unsafe or any(path.exists() for path in hook_paths)
            if unsafe:
                return Result('review', error='此 MVP 僅支援未啟用 MCP、plugins、hooks 或 notify 的乾淨 Codex 設定；請先人工檢查。')
            quota = request('account/rateLimits/read')
            exhausted, retry_at = quota_wait(quota, limit_id)
            if exhausted:
                return Result('quota', retry_at=retry_at, quota=quota, notices=notices, partial_output='\n\n'.join(messages.values()))
            params = {'cwd': job['cwd'], 'approvalPolicy': 'never', 'sandbox': 'read-only', 'modelProvider': 'openai'}
            if job.get('session_id'):
                params['threadId'] = job['session_id']
            try:
                result = request('thread/resume' if job.get('session_id') else 'thread/start', params)
            except _RPCError as exc:
                if not job.get('session_id') or not _missing_thread(exc.payload):
                    raise
                params.pop('threadId', None)
                result = request('thread/start', params)
                prompt += '\n\n已保存的先前成果（工作階段復原用）：\n' + json.dumps(job.get('outputs', []), ensure_ascii=False)
                notices.append('原工作階段已不存在；已建立新工作階段，依保存的檢查點繼續。')
            session_id = result['thread']['id']
            on_session(session_id)
            result = request('turn/start', {'threadId': session_id,
                'input': [{'type': 'text', 'text': prompt}], 'cwd': job['cwd'],
                'approvalPolicy': 'never', 'sandboxPolicy': {'type': 'readOnly', 'networkAccess': False}})
            turn_id = result['turn']['id']
            while True:
                payload = pending.pop(0) if pending else receive()
                event(payload)
                if payload.get('method') == 'turn/completed':
                    turn = payload.get('params', {}).get('turn', {})
                    if turn.get('id') != turn_id:
                        continue
                    turn_finished = True
                    if turn.get('status') == 'completed':
                        if not output().strip():
                            # Never checkpoint an empty result as a finished step.
                            return Result('review', error='Codex 回報完成，但沒有收到文字成果；請檢查工作階段後再續跑。', quota=quota, notices=notices, partial_output='\n\n'.join(messages.values()))
                        return Result('success', output=output(), quota=quota, notices=notices, partial_output='\n\n'.join(messages.values()))
                    if _is_quota(turn.get('error')):
                        try:
                            quota = request('account/rateLimits/read', timeout=3)
                        except _Abort as exc:
                            if exc.kind == 'cancelled':
                                raise
                            notices.append('額度更新未能確認，保留最後已知用量。')
                        except _RPCError:
                            notices.append('額度更新未能確認，保留最後已知用量。')
                        return Result('quota', output=output(), retry_at=quota_wait(quota, limit_id)[1], quota=quota, notices=notices, partial_output='\n\n'.join(messages.values()))
                    return Result('review' if turn.get('status') == 'interrupted' else 'failed', output=output(), error='Codex 工作未完成；請檢查後續做。', quota=quota, notices=notices, partial_output='\n\n'.join(messages.values()))
        except _Abort as exc:
            return Result(exc.kind, output=output(), error=exc.message, quota=quota, notices=notices, partial_output='\n\n'.join(messages.values()))
        except _RPCError as exc:
            if _is_quota(exc.payload):
                return Result('quota', output=output(), retry_at=quota_wait(quota, limit_id)[1], quota=quota, notices=notices, partial_output='\n\n'.join(messages.values()))
            return Result('review', output=output(), error='Codex 拒絕請求；請檢查 CLI 版本、登入與設定。', quota=quota, notices=notices, partial_output='\n\n'.join(messages.values()))
        except Exception:
            return Result('review', output=output(), error='Codex 連線或回應格式異常；請檢查 CLI 版本。', quota=quota, notices=notices, partial_output='\n\n'.join(messages.values()))
        finally:
            if proc is not None:
                if proc.poll() is None:
                    try:
                        interrupt_active()
                    except (OSError, ValueError):
                        pass
                if proc.poll() is None:
                    try:
                        if os.name == 'posix':
                            os.killpg(proc.pid, signal.SIGTERM)
                        else:
                            # npm installs codex as a .cmd shim; terminate() would only stop
                            # cmd.exe and leave node/codex running. Kill the whole tree.
                            subprocess.run(['taskkill', '/T', '/F', '/PID', str(proc.pid)],
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                        proc.wait(timeout=2)
                    except (OSError, subprocess.TimeoutExpired):
                        if os.name == 'posix':
                            try:
                                os.killpg(proc.pid, signal.SIGKILL)
                            except OSError:
                                pass
                        else:
                            proc.kill()
                        proc.wait()
                for stream in (proc.stdin, proc.stdout):
                    if stream:
                        try:
                            stream.close()
                        except OSError:
                            pass
