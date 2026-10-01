"""Loopback-only dashboard with Host, Origin and per-process CSRF checks."""
from __future__ import annotations

import argparse
import json
import secrets
import shutil
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from . import __version__
from .core import Engine, InstanceLock, Store


def make_server(engine, port=8765):
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # Do not log user prompts or auth material.

        def send_data(self, status, data, mime="application/json; charset=utf-8"):
            raw = json.dumps(data, ensure_ascii=False).encode() if not isinstance(data, bytes) else data
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; form-action 'self'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(raw)

        def valid_host(self):
            hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if self.headers.get("Host") not in hosts:
                self.send_data(403, {"error": "僅接受本機網址。"})
                return False
            return True

        def do_GET(self):
            if not self.valid_host():
                return
            path = urlparse(self.path).path
            if path == "/":
                self.send_data(200, Path(__file__).with_name("static").joinpath("index.html").read_bytes(), "text/html; charset=utf-8")
            elif path == "/api/state":
                try:
                    query = parse_qs(urlparse(self.path).query)
                    page = int(query.get("page", ["0"])[0])
                    size = int(query.get("page_size", ["50"])[0])
                    since = int(query["since"][0]) if "since" in query else None
                    if page < 0 or not 1 <= size <= 100 or (since is not None and since < 0):
                        raise ValueError()
                    self.send_data(200, dict(engine.state(page, size, since), csrf_token=token, version=__version__))
                except ValueError:
                    self.send_data(400, {"error": "page、page_size 或 since 格式錯誤。"})
            elif path.startswith("/api/jobs/"):
                parts = path.strip("/").split("/")
                try:
                    if len(parts) != 3:
                        raise ValueError()
                    self.send_data(200, engine.store.get(parts[2]))
                except ValueError:
                    self.send_data(404, {"error": "找不到工作。"})
            elif path == "/api/export":
                self.send_data(200, {"version": __version__, "jobs": engine.store.jobs(), "events": engine.store.events()})
            else:
                self.send_data(404, {"error": "找不到頁面。"})

        def do_POST(self):
            if not self.valid_host():
                return
            origin = self.headers.get("Origin")
            expected = f"http://{self.headers.get('Host')}"
            # Compare bytes: compare_digest raises TypeError on non-ASCII str headers.
            supplied = self.headers.get("X-Relay-Token", "").encode("utf-8", "surrogateescape")
            if (origin is not None and origin != expected) or not secrets.compare_digest(supplied, token.encode()):
                self.send_data(403, {"error": "操作驗證失敗，請重新整理頁面。"})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 350000 or self.headers.get_content_type() != "application/json":
                    raise ValueError("請使用 JSON，大小需小於 350 KB。")
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise ValueError("資料必須是物件。")
                if self.path == "/api/jobs":
                    self.send_data(201, engine.add(data))
                elif self.path == "/api/control":
                    if data.get("action") not in ("pause", "resume"):
                        raise ValueError("未知操作。")
                    engine.store.set("paused", data["action"] == "pause")
                    self.send_data(200, {"ok": True})
                elif self.path == "/api/workspace":
                    self.send_data(200, engine.change_workspace(data.get("path")))
                else:
                    parts = urlparse(self.path).path.strip("/").split("/")
                    if len(parts) != 4 or parts[:2] != ["api", "jobs"]:
                        self.send_data(404, {"error": "找不到操作。"})
                        return
                    self.send_data(200, engine.action(parts[2], parts[3], data.get("confirmed") is True))
            except (ValueError, TypeError) as exc:
                self.send_data(400, {"error": str(exc)})
            except Exception:
                self.send_data(500, {"error": "服務異常；請保留資料目錄後重新啟動。"})

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


def resolve_workspace(store, explicit=None):
    path = Path(explicit or store.setting("workspace") or (Path.home() / "AI-Run-Relay-workspace")).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    store.set("workspace", str(path))
    return path


def main():
    parser = argparse.ArgumentParser(description="AI Run Relay — 額度等待與工作接續")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--data-dir", type=Path, default=Path.home() / ".ai-run-relay")
    parser.add_argument("--workspace", type=Path, default=None,
                        help="預設沿用已保存路徑，首次使用 ~/AI-Run-Relay-workspace")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="自動開啟瀏覽器")
    parser.add_argument("--demo", action="store_true", help="加入一個不耗 AI 額度的示範工作")
    parser.add_argument("--doctor", action="store_true", help="檢查執行環境，不讀取登入憑證")
    args = parser.parse_args()
    if args.doctor:
        print(f"AI Run Relay {__version__}\nPython: OK\nCodex CLI: {'已找到' if shutil.which('codex') else '未安裝（模擬模式仍可用）'}\n工作目錄: {args.workspace.resolve() if args.workspace else '沿用設定；首次使用 ~/AI-Run-Relay-workspace'}")
        return
    if not 0 <= args.port <= 65535:
        parser.error("port 必須介於 0–65535。")
    args.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        args.data_dir.chmod(0o700)  # mkdir(mode=) is ignored when the folder already exists
    except OSError:
        pass
    try:
        lock = InstanceLock(args.data_dir / "instance.lock")
    except RuntimeError as exc:
        parser.exit(1, f"{exc}\n")
    store = Store(args.data_dir / "relay.sqlite3")
    engine = Engine(store, resolve_workspace(store, args.workspace))
    server = None
    try:
        try:
            server = make_server(engine, args.port)
        except OSError as exc:
            print(f"無法使用連接埠 {args.port}（{exc.strerror or exc}）。請改用 --port 指定其他埠號。", flush=True)
            return
        if args.demo:
            engine.add({"title": "第一趟接力：等待後自動完成", "provider": "mock", "steps": ["整理任務資料", "分析並保存結果", "完成摘要"], "wait_seconds": 8})
        url = f"http://127.0.0.1:{server.server_port}"
        print(f"AI Run Relay {__version__}\n控制台：{url}\n資料目錄：{args.data_dir.resolve()}\n按 Ctrl+C 停止。", flush=True)
        engine.start()
        if args.open:
            webbrowser.open(url)
        server.serve_forever(poll_interval=0.4)
    except KeyboardInterrupt:
        pass
    finally:
        engine.stop()
        if server:
            server.server_close()
        store.close()
        lock.close()
