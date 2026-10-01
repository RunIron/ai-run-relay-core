"""Single-worker durable queue. SQLite transactions are the checkpoint boundary."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path


class InstanceLock:
    """OS-held lock; released by the OS after a crash (not a stale PID file)."""
    def __init__(self, path):
        self.file = open(path, "a+b")
        self.file.seek(0)
        if self.file.read(1) == b"":
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError("這個資料目錄已由另一個 AI Run Relay 使用。") from None

    def close(self):
        self.file.close()


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        if os.name == "posix":
            try:
                os.chmod(self.path, 0o600)  # outputs may contain private analysis
            except OSError:
                pass
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, ts REAL, job_id TEXT, message TEXT);
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value INTEGER NOT NULL);
            INSERT OR IGNORE INTO meta VALUES ('revision', 0);
        """)
        # Add a small indexed projection once, so polling never reads/decodes outputs.
        with self.db:
            columns = {row[1] for row in self.db.execute("PRAGMA table_info(jobs)")}
            for name, kind in (("summary", "TEXT"), ("status", "TEXT"), ("revision", "INTEGER")):
                if name not in columns:
                    self.db.execute(f"ALTER TABLE jobs ADD COLUMN {name} {kind}")
            for job_id, raw in self.db.execute("SELECT id,data FROM jobs WHERE summary IS NULL").fetchall():
                job = json.loads(raw)
                job["revision"] = self._next_revision()
                self._put(job)
            self.db.execute("CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status)")

    def _next_revision(self):
        self.db.execute("UPDATE meta SET value=value+1 WHERE key='revision'")
        return self.db.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0]

    def revision(self):
        with self.lock:
            return self.db.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0]

    @staticmethod
    def summarize(job):
        keys = ("id", "title", "provider", "status", "priority", "created_at", "updated_at",
                "revision", "next_run_at", "step_index", "attempts", "last_error", "session_id",
                "retry_source", "deadline")
        summary = {key: job.get(key) for key in keys}
        steps = job.get("steps", [])
        index = job.get("step_index", 0)
        summary.update(steps_count=len(steps), next_step=steps[index][:240] if index < len(steps) else "",
                       output_count=len(job.get("outputs", [])), has_partial=bool(job.get("partial_output")))
        return summary

    def _put(self, job):
        # UPSERT keeps the original rowid; INSERT OR REPLACE would delete and re-insert,
        # reshuffling ORDER BY rowid every time a job is saved.
        self.db.execute("""INSERT INTO jobs(id,data,summary,status,revision) VALUES (?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET data=excluded.data,summary=excluded.summary,
            status=excluded.status,revision=excluded.revision""",
            (job["id"], json.dumps(job, ensure_ascii=False), json.dumps(self.summarize(job), ensure_ascii=False),
             job["status"], job.get("revision", 0)))

    def summaries(self, statuses):
        with self.lock:
            marks = ",".join("?" for _ in statuses)
            return [json.loads(row[0]) for row in self.db.execute(
                f"SELECT summary FROM jobs WHERE status IN ({marks}) ORDER BY rowid", tuple(statuses))]

    def page(self, page=0, page_size=50, since=None):
        with self.lock:
            counts = dict(self.db.execute("SELECT status,COUNT(*) FROM jobs GROUP BY status"))
            total = sum(counts.values())
            pages = max(1, (total + page_size - 1) // page_size)
            page = min(max(page, 0), pages - 1)
            revision = self.revision()
            # A stale cursor from another database must be treated as a full fetch.
            if since is not None and since > revision:
                since = None
            rows = self.db.execute("SELECT id,summary,revision FROM jobs ORDER BY rowid DESC LIMIT ? OFFSET ?",
                                   (page_size, page * page_size)).fetchall()
            return dict(jobs=[json.loads(raw) for _, raw, rev in rows if since is None or rev > since],
                        job_order=[i for i, _, _ in rows], revision=revision, total_jobs=total, counts=counts,
                        page=page, pages=pages, page_size=page_size)

    def get(self, job_id):
        with self.lock:
            row = self.db.execute("SELECT data FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise ValueError("找不到工作。")
            return json.loads(row[0])

    def jobs(self):
        with self.lock:
            return [json.loads(row[0]) for row in self.db.execute("SELECT data FROM jobs ORDER BY rowid DESC")]

    def save(self, job, message=None):
        with self.lock, self.db:
            job["updated_at"] = time.time()
            job["revision"] = self._next_revision()
            self._put(job)
            if message:
                self.db.execute("INSERT INTO events(ts,job_id,message) VALUES (?,?,?)", (time.time(), job["id"], message))

    def setting(self, key, default=None):
        with self.lock:
            row = self.db.execute("SELECT data FROM settings WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def set(self, key, value):
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value)))
            self._next_revision()

    def events(self):
        with self.lock:
            return [dict(zip(("ts", "job_id", "message"), row)) for row in self.db.execute(
                "SELECT ts,job_id,message FROM events ORDER BY id DESC LIMIT 100")]

    def close(self):
        self.db.close()


class Engine:
    def __init__(self, store, workspace, adapters=None, clock=time.time):
        self.store, self.workspace, self.clock = store, Path(workspace).resolve(), clock
        self.workspace.mkdir(parents=True, exist_ok=True)
        if adapters is None:
            from .codex import CodexAdapter
            adapters = {"codex": CodexAdapter()}
        self.adapters = adapters
        self.shutdown = threading.Event()
        self.active_stop = threading.Event()
        self.active_id = None
        self.thread = None
        self.tick_lock = threading.Lock()
        with store.lock:
            for summary in store.summaries(("running",)):
                job = store.get(summary["id"])
                if job["status"] == "running":
                    job["status"] = "queued" if job["provider"] == "mock" else "needs_review"
                    job["last_error"] = "執行期間程式中斷。請先確認最後一步的實際結果，再決定續跑。"
                    store.save(job, "啟動復原：保留已完成步驟，檢查未完成執行。")

    def add(self, data):
        if not isinstance(data, dict):
            raise ValueError("工作資料必須是物件。")
        title, steps = data.get("title", ""), data.get("steps", [])
        provider = data.get("provider", "mock")
        if provider not in ("mock", "codex"):
            raise ValueError("第一版僅支援模擬與 Codex。")
        if not isinstance(title, str) or not title.strip() or len(title) > 200:
            raise ValueError("工作名稱需為 1–200 字。")
        if not isinstance(steps, list) or not 1 <= len(steps) <= 30 or any(
            not isinstance(s, str) or not s.strip() or len(s) > 10000 for s in steps
        ):
            raise ValueError("請提供 1–30 個非空白步驟，每個最多 10000 字。")
        priority = data.get("priority", 0)
        wait = data.get("wait_seconds", 8) if provider == "mock" else 8
        if type(priority) is not int or not 0 <= priority <= 10:
            raise ValueError("優先權必須是 0–10 的整數。")
        if type(wait) is not int or not 1 <= wait <= 86400:
            raise ValueError("模擬等待需為 1–86400 秒。")
        raw_cwd = data.get("cwd") or str(self.workspace)
        if not isinstance(raw_cwd, str):
            raise ValueError("工作目錄格式錯誤。")
        cwd = Path(raw_cwd).expanduser()
        cwd = (self.workspace / cwd).resolve() if not cwd.is_absolute() else cwd.resolve()
        if not cwd.is_dir() or not cwd.is_relative_to(self.workspace):
            raise ValueError("工作目錄必須存在，且位於啟動時指定的 workspace 內。")
        now = self.clock()
        job = dict(id=uuid.uuid4().hex, title=title.strip(), provider=provider, steps=[s.strip() for s in steps],
                   cwd=str(cwd), priority=priority, status="queued", created_at=now, updated_at=now,
                   next_run_at=0, step_index=0, attempts=0, step_attempts=0, max_attempts=6,
                   deadline=now + 7 * 86400, last_error="", session_id=None, outputs=[],
                   wait_seconds=wait, mock_waited=False, retry_source=None, partial_output="",
                   resync_context=False, workspace_root=str(self.workspace))
        self.store.save(job, "工作已排入佇列。" + ("（模擬，不呼叫 AI）" if provider == "mock" else ""))
        return job

    def action(self, job_id, action, confirmed=False):
        with self.store.lock:
            job = self.store.get(job_id)
            if action == "cancel":
                if job["status"] in ("succeeded", "cancelled"):
                    raise ValueError("這項工作已結束。")
                job["status"] = "cancelled"
                if self.active_id == job_id:
                    self.active_stop.set()
            elif action in ("resume", "retry"):
                required = "needs_review" if action == "resume" else "failed"
                if job["status"] != required:
                    raise ValueError("目前狀態不能執行此操作。")
                if not confirmed:
                    raise ValueError("請確認已檢查上次執行結果，允許重試未完成步驟。")
                job.update(status="queued", step_attempts=0, next_run_at=0, last_error="",
                           deadline=self.clock() + 7 * 86400, resync_context=True)
            else:
                raise ValueError("未知操作。")
            self.store.save(job, {"cancel": "工作已取消；執行中的外部操作可能已發生。", "resume": "使用者確認後續跑。", "retry": "使用者確認後重試。"}[action])
            return job

    def change_workspace(self, raw_path):
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError("請輸入已存在的絕對路徑。")
        path = Path(raw_path).expanduser()
        if not path.is_absolute() or not path.is_dir():
            raise ValueError("工作資料夾必須存在，且使用絕對路徑。")
        with self.store.lock:
            self.workspace = path.resolve()
            self.store.set("workspace", str(self.workspace))
        return {"workspace": str(self.workspace)}

    def state(self, page=0, page_size=50, since=None):
        with self.store.lock:
            return dict(self.store.page(page, page_size, since), events=self.store.events(), now=self.clock(),
                    paused=self.store.setting("paused", False),
                    providers={"mock": True, "codex": bool(self.adapters.get("codex") and self.adapters["codex"].available())},
                    quota=self.store.setting("quota", {}), workspace=str(self.workspace))

    def _session(self, job_id, session_id):
        with self.store.lock:
            job = self.store.get(job_id)
            job["session_id"] = session_id
            self.store.save(job)

    def tick(self):
        if not self.tick_lock.acquire(blocking=False):
            return False
        try:
            return self._tick()
        finally:
            self.tick_lock.release()

    def _tick(self):
        with self.store.lock:
            if self.shutdown.is_set() or self.store.setting("paused", False):
                return False
            now = self.clock()
            cooldowns = self.store.setting("cooldowns", {})
            candidates = []
            for summary in self.store.summaries(("queued", "waiting_quota")):
                job = summary
                if now >= job["deadline"]:
                    job = self.store.get(job["id"])
                    job.update(status="failed", last_error="超過七天等待期限，請檢查後手動重試。")
                    self.store.save(job, "等待期限已到。")
                    continue
                due = max(job["next_run_at"], cooldowns.get(job["provider"], 0))
                if due > now:
                    if job["status"] != "waiting_quota" or job["next_run_at"] != due:
                        job = self.store.get(job["id"])
                        job.update(status="waiting_quota", next_run_at=due)
                        self.store.save(job)
                    continue
                candidates.append(job)
            if not candidates:
                return False
            selected = min(candidates, key=lambda j: (-j["priority"], j["created_at"], j["id"]))
            job = self.store.get(selected["id"])
            job.update(status="running", attempts=job["attempts"] + 1,
                       step_attempts=job["step_attempts"] + 1, next_run_at=0)
            self.active_id = job["id"]
            self.active_stop = threading.Event()
            self.store.save(job, f"執行步驟 {job['step_index'] + 1}/{len(job['steps'])}。")

        try:
            from .codex import Result
            if job["provider"] == "mock":
                if self.active_stop.wait(0.25):
                    result = Result("cancelled")
                elif not job["mock_waited"] and job["step_index"] == min(1, len(job["steps"]) - 1):
                    result = Result("quota", error="模擬額度耗盡", retry_at=self.clock() + job["wait_seconds"])
                else:
                    result = Result("success", output=f"[模擬輸出，非 AI 生成]\n步驟 {job['step_index'] + 1}：{job['steps'][job['step_index']]}\n排程與檢查點已驗證。")
            else:
                # A resumed thread already holds earlier turns; re-sending every prior output
                # each step makes token use grow quadratically. Send them only for a new
                # thread or the first run after a manual resume/retry.
                if job["outputs"] and (not job.get("session_id") or job.get("resync_context")):
                    prior = "\n\n".join(f"完成步驟 {i+1}：\n{x}" for i, x in enumerate(job["outputs"]))
                elif job["outputs"]:
                    prior = "（前步驟成果已在本工作階段的先前回合中。）"
                else:
                    prior = "（無）"
                prompt = ("你正在執行 AI Run Relay 的唯讀分析工作。請只執行本次步驟，勿修改檔案或發送外部訊息。\n"
                          f"工作：{job['title']}\n已保存的前步驟結果：\n{prior}\n"
                          f"本次步驟 {job['step_index'] + 1}：{job['steps'][job['step_index']]}\n"
                          "如為中斷續跑，先確認既有結果；不要重做已完成步驟。請回傳本步驟最終成果。")
                result = self.adapters[job["provider"]].run(job, prompt, lambda sid: self._session(job["id"], sid), self.active_stop)
        except Exception:
            # An unknown failure after submission is not safe to blindly repeat.
            result = Result("review", error="執行器異常，無法確認最後一步結果。請檢查後再續跑。")

        with self.store.lock:
            current = self.store.get(job["id"])
            self.active_id = None
            notices = getattr(result, "notices", None) or []
            if notices:
                current["adapter_notices"] = notices
                self.store.save(current, "；".join(notices))
            if current["status"] != "running":
                return True
            if result.quota is not None:
                quota = self.store.setting("quota", {})
                quota[job["provider"]] = result.quota
                self.store.set("quota", quota)
            current["partial_output"] = (getattr(result, "partial_output", "") or result.output) if result.kind != "success" else ""
            if result.kind == "success":
                current["outputs"].append(result.output)
                current["step_index"] += 1
                current.update(status="succeeded" if current["step_index"] == len(current["steps"]) else "queued",
                               step_attempts=0, last_error="", retry_source=None, resync_context=False)
                message = "工作完成，結果已保存。" if current["status"] == "succeeded" else "步驟完成，已保存檢查點。"
            elif result.kind == "quota":
                current["mock_waited"] = True
                current["last_error"] = result.error or "平台額度暫時不足。"
                known = result.retry_at is not None
                due = max(self.clock() + 5, result.retry_at + 2) if known else self.clock() + min(3600, 300 * 2 ** (current["step_attempts"] - 1))
                current.update(status="waiting_quota", next_run_at=due, retry_source="platform" if known else "estimated")
                if job["provider"] == "mock":
                    current["retry_source"] = "simulation"
                    due = result.retry_at
                    current["next_run_at"] = due
                cooldowns = self.store.setting("cooldowns", {})
                cooldowns[job["provider"]] = due
                self.store.set("cooldowns", cooldowns)
                if known and due >= current["deadline"]:
                    # e.g. a weekly window that resets after the 7-day deadline
                    current["deadline"] = due + 3600
                if current["step_attempts"] >= current["max_attempts"]:
                    current.update(status="needs_review", last_error="已達自動嘗試上限，請檢查配額後手動續跑。")
                    message = current["last_error"]
                else:
                    message = "額度不足，等待後再確認。" if known else "恢復時間未知，採有限次退避重試（預估）。"
            elif result.kind == "cancelled" and job["provider"] == "mock":
                current.update(status="queued", last_error="")
                message = "模擬工作因停止服務中斷，已重新排隊。"
            else:
                current.update(status={"cancelled": "needs_review", "failed": "failed"}.get(result.kind, "needs_review"),
                               last_error=result.error or "執行中斷，請確認結果。")
                message = current["last_error"]
            self.store.save(current, message)
        return True

    def start(self):
        def loop():
            while not self.shutdown.is_set():
                self.tick()
                self.shutdown.wait(0.4)
        self.thread = threading.Thread(target=loop, name="relay-worker", daemon=True)
        self.thread.start()

    def stop(self):
        self.shutdown.set()
        self.active_stop.set()
        if self.thread:
            self.thread.join(timeout=15)
