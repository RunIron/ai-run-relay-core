"""Single-worker durable queue. SQLite transactions are the checkpoint boundary."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path

LOCKED = "This data folder is already in use by another AI Run Relay process."


class InstanceLock:
    """OS-held lock; released by the OS after a crash (not a stale PID file)."""
    def __init__(self, path):
        try:
            self.file = open(path, "a+b")
        except PermissionError:
            raise RuntimeError(LOCKED) from None
        try:
            self.file.seek(0)
            if self.file.read(1) == b"":
                self.file.write(b"0")
                self.file.flush()
            self.file.seek(0)
        except PermissionError:
            self.file.close()
            raise RuntimeError(LOCKED) from None
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError(LOCKED) from None

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
                raise ValueError("Job not found.")
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
                    if job["provider"] == "mock":
                        # Simulated steps have no external side effects; rerun them safely.
                        job.update(status="queued", last_error="")
                    else:
                        job.update(status="needs_review", last_error=(
                            "Relay stopped while this step was running. Check the actual result "
                            "of the last step before resuming."))
                    store.save(job, "Startup recovery: completed steps kept; the interrupted step needs a check.")

    def add(self, data):
        if not isinstance(data, dict):
            raise ValueError("Job data must be a JSON object.")
        title, steps = data.get("title", ""), data.get("steps", [])
        provider = data.get("provider", "mock")
        if provider not in ("mock", "codex"):
            raise ValueError("Only the simulation and Codex providers are supported.")
        if not isinstance(title, str) or not title.strip() or len(title) > 200:
            raise ValueError("Job name must be 1–200 characters.")
        if not isinstance(steps, list) or not 1 <= len(steps) <= 30 or any(
            not isinstance(s, str) or not s.strip() or len(s) > 10000 for s in steps
        ):
            raise ValueError("Provide 1–30 non-empty steps, each up to 10,000 characters.")
        priority = data.get("priority", 0)
        wait = data.get("wait_seconds", 8) if provider == "mock" else 8
        if type(priority) is not int or not 0 <= priority <= 10:
            raise ValueError("Priority must be an integer from 0 to 10.")
        if type(wait) is not int or not 1 <= wait <= 86400:
            raise ValueError("Simulation wait must be 1–86,400 seconds.")
        raw_cwd = data.get("cwd") or str(self.workspace)
        if not isinstance(raw_cwd, str):
            raise ValueError("Invalid working folder.")
        cwd = Path(raw_cwd).expanduser()
        cwd = (self.workspace / cwd).resolve() if not cwd.is_absolute() else cwd.resolve()
        if not cwd.is_dir() or not cwd.is_relative_to(self.workspace):
            raise ValueError("The working folder must exist inside the current workspace.")
        now = self.clock()
        job = dict(id=uuid.uuid4().hex, title=title.strip(), provider=provider, steps=[s.strip() for s in steps],
                   cwd=str(cwd), priority=priority, status="queued", created_at=now, updated_at=now,
                   next_run_at=0, step_index=0, attempts=0, step_attempts=0, max_attempts=6,
                   deadline=now + 7 * 86400, last_error="", session_id=None, outputs=[],
                   wait_seconds=wait, mock_waited=False, retry_source=None, partial_output="",
                   resync_context=False, workspace_root=str(self.workspace))
        self.store.save(job, "Job added to queue." + (" (Simulation; no AI is called.)" if provider == "mock" else ""))
        return job

    def action(self, job_id, action, confirmed=False):
        with self.store.lock:
            job = self.store.get(job_id)
            if action == "cancel":
                if job["status"] in ("succeeded", "cancelled"):
                    raise ValueError("This job has already finished.")
                job["status"] = "cancelled"
                if self.active_id == job_id:
                    self.active_stop.set()
            elif action in ("resume", "retry"):
                required = "needs_review" if action == "resume" else "failed"
                if job["status"] != required:
                    raise ValueError("This action is not available in the job's current state.")
                if not confirmed:
                    raise ValueError("Confirm that you reviewed the last result before the unfinished step is retried.")
                job.update(status="queued", step_attempts=0, next_run_at=0, last_error="",
                           deadline=self.clock() + 7 * 86400, resync_context=True)
            else:
                raise ValueError("Unknown action.")
            self.store.save(job, {"cancel": "Job cancelled. External actions already in progress may have happened.",
                                  "resume": "Resumed after user confirmation.",
                                  "retry": "Retried after user confirmation."}[action])
            return job

    def change_workspace(self, raw_path):
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError("Enter an existing absolute folder path.")
        path = Path(raw_path.strip()).expanduser()
        if not path.is_absolute() or not path.is_dir():
            raise ValueError("The workspace must be an existing folder given as an absolute path.")
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
                    job.update(status="failed", last_error="The 7-day waiting limit was reached. Review the job, then retry it manually.")
                    self.store.save(job, "Waiting limit reached.")
                    continue
                due = max(job["next_run_at"], cooldowns.get(job["provider"], 0))
                if due > now:
                    if job["status"] != "waiting_quota" or job["next_run_at"] != due or due >= job["deadline"]:
                        job = self.store.get(job["id"])
                        job.update(status="waiting_quota", next_run_at=due)
                        if due >= job["deadline"]:
                            # A shared platform wait (e.g. a weekly reset) must extend every
                            # waiting job, not only the one that received the quota reply.
                            job["deadline"] = due + 3600
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
            self.store.save(job, f"Running step {job['step_index'] + 1} of {len(job['steps'])}.")

        try:
            from .codex import Result
            if job["provider"] == "mock":
                if self.active_stop.wait(0.25):
                    result = Result("cancelled")
                elif not job["mock_waited"] and job["step_index"] == min(1, len(job["steps"]) - 1):
                    result = Result("quota", error="Simulated quota exhausted.", retry_at=self.clock() + job["wait_seconds"])
                else:
                    result = Result("success", output=(
                        "[Simulated output; not AI-generated]\n"
                        f"Step {job['step_index'] + 1}: {job['steps'][job['step_index']]}\n"
                        "Scheduling and checkpointing verified."))
            else:
                # A resumed thread already holds earlier turns; re-sending every prior output
                # each step makes token use grow quadratically. Send them only for a new
                # thread or the first run after a manual resume/retry.
                if job["outputs"] and (not job.get("session_id") or job.get("resync_context")):
                    prior = "\n\n".join(f"Completed step {i + 1}:\n{x}" for i, x in enumerate(job["outputs"]))
                elif job["outputs"]:
                    prior = "(Earlier step results are already in previous turns of this session.)"
                else:
                    prior = "(none)"
                prompt = ("You are running a read-only analysis job for AI Run Relay. Perform only the current step. "
                          "Do not modify files or send external messages.\n"
                          f"Job: {job['title']}\nSaved results from earlier steps:\n{prior}\n"
                          f"Current step {job['step_index'] + 1}: {job['steps'][job['step_index']]}\n"
                          "If this is a resumed run, check existing results first and do not redo completed steps. "
                          "Reply with the final result for this step.")
                result = self.adapters[job["provider"]].run(job, prompt, lambda sid: self._session(job["id"], sid), self.active_stop)
        except Exception:
            # An unknown failure after submission is not safe to blindly repeat.
            result = Result("review", error="The provider failed unexpectedly, so the last step's result is unknown. Review it before resuming.")

        with self.store.lock:
            current = self.store.get(job["id"])
            self.active_id = None
            notices = getattr(result, "notices", None) or []
            if notices:
                current["adapter_notices"] = notices
                self.store.save(current, " ".join(notices))
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
                message = "Job completed; results saved." if current["status"] == "succeeded" else "Step completed; checkpoint saved."
            elif result.kind == "quota":
                current["mock_waited"] = True
                current["last_error"] = result.error or "Platform quota is temporarily unavailable."
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
                    current.update(status="needs_review", last_error="Automatic retry limit reached. Check your quota, then resume manually.")
                    message = current["last_error"]
                else:
                    message = ("Quota unavailable; waiting for the reported reset." if known
                               else "Reset time unknown; retrying with limited backoff (estimated).")
            elif result.kind == "cancelled" and job["provider"] == "mock":
                current.update(status="queued", last_error="")
                message = "Simulated job interrupted by shutdown and re-queued."
            else:
                current.update(status={"cancelled": "needs_review", "failed": "failed"}.get(result.kind, "needs_review"),
                               last_error=result.error or "The run was interrupted. Check the result.")
                message = current["last_error"]
            self.store.save(current, message)
        return True

    def start(self):
        def loop():
            while not self.shutdown.is_set():
                try:
                    self.tick()
                except Exception:
                    # Never let one bad tick silently kill the only worker thread.
                    self.shutdown.wait(5)
                self.shutdown.wait(0.4)
        self.thread = threading.Thread(target=loop, name="relay-worker", daemon=True)
        self.thread.start()

    def stop(self):
        self.shutdown.set()
        self.active_stop.set()
        if self.thread:
            self.thread.join(timeout=15)
