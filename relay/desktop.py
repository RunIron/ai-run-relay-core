"""Desktop host for the loopback service; never installs or stores AI credentials."""
from pathlib import Path
import os
import shutil
import threading
import webbrowser

from . import __version__
from .core import Engine, InstanceLock, Store
from .server import make_server, resolve_workspace


class LocalService:
    def __init__(self, data_dir=None, workspace=None):
        self.data_dir = Path(data_dir or Path.home() / '.ai-run-relay')
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = InstanceLock(self.data_dir / 'instance.lock')
        self.store = self.engine = self.server = self.thread = None
        try:
            self.store = Store(self.data_dir / 'relay.sqlite3')
            self.engine = Engine(self.store, resolve_workspace(self.store, workspace))
            # OS chooses a free loopback port; never open another service by mistake.
            self.server = make_server(self.engine, 0)
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()
            self.engine.start()
        except Exception:
            self.close()
            raise

    @property
    def url(self):
        return f'http://127.0.0.1:{self.server.server_port}'

    def demo(self):
        return self.engine.add({'title': '第一次使用：等待後自動接續', 'provider': 'mock',
                               'steps': ['整理資料', '等待額度恢復', '完成摘要'], 'wait_seconds': 8})

    def close(self):
        if self.server:
            if self.thread and self.thread.is_alive():
                self.server.shutdown()
                self.thread.join()
            self.server.server_close()
            self.server = None
        if self.engine:
            self.engine.stop()
            # Do not close SQLite while an interrupted worker is still using it.
            if self.engine.thread and self.engine.thread.is_alive():
                self.engine.thread.join()
            self.engine = None
        if self.store:
            self.store.close()
            self.store = None
        if self.lock:
            self.lock.close()
            self.lock = None


def main():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    try:
        root = tk.Tk()
    except tk.TclError:
        raise SystemExit('沒有可用的桌面環境。請使用 ai-run-relay --server；遠端存取請用 SSH 本機轉送。')
    root.title(f'AI Run Relay {__version__}')
    root.geometry('640x480')
    root.minsize(590, 450)
    try:
        service = LocalService()
    except Exception as exc:
        messagebox.showerror('無法啟動 AI Run Relay', str(exc), parent=root)
        root.destroy()
        return 1
    frame = ttk.Frame(root, padding=24)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='AI Run Relay', font=('', 22, 'bold')).pack(anchor='w')
    ttk.Label(frame, text='工作先排好，額度恢復後自動接續。').pack(anchor='w', pady=(8, 16))
    status = tk.StringVar(value='服務已啟動。先選擇工作資料夾，再開啟控制台。')
    workspace = tk.StringVar(value=service.store.setting('workspace'))
    ttk.Label(frame, textvariable=status, wraplength=560).pack(anchor='w', pady=6)
    ttk.Label(frame, textvariable=workspace, wraplength=560).pack(anchor='w', pady=6)

    def choose():
        path = filedialog.askdirectory(parent=root, initialdir=workspace.get(), mustexist=True)
        if path:
            try:
                service.engine.change_workspace(path)
                workspace.set(path)
            except ValueError as exc:
                messagebox.showerror('工作資料夾', str(exc), parent=root)

    def dashboard():
        if not webbrowser.open(service.url):
            messagebox.showinfo('控制台網址', f'請用瀏覽器開啟：\n{service.url}', parent=root)

    def demo():
        service.demo()
        status.set('已加入模擬工作：等待約 8 秒後接續，不消耗 AI 額度。')
        dashboard()

    def codex_help():
        found = bool(shutil.which('codex'))
        messagebox.showinfo('連接自己的 Codex 帳號',
            ('已找到 Codex CLI（尚未確認登入狀態）。' if found else '尚未找到 Codex CLI。') +
            '\n\n請依官方說明安裝並以 ChatGPT 帳號登入。\n完成後重新啟動 Relay，在控制台選擇 Codex。'
            '\n\nRelay 不代收帳號密碼，也不會自動安裝第三方程式。', parent=root)
        webbrowser.open('https://developers.openai.com/codex/cli')

    for label, command in [('選擇工作資料夾', choose), ('開啟工作控制台', dashboard),
                           ('先試用：加入模擬工作', demo), ('連接 Codex／安裝說明', codex_help)]:
        ttk.Button(frame, text=label, command=command).pack(fill='x', pady=4)
    ttk.Label(frame, text='最小化視窗可以繼續執行；關閉程式或電腦休眠會停止工作。\n'
              '商業使用須事先書面授權：runiron.wu@gmail.com', wraplength=560).pack(anchor='w', pady=14)
    closing = False
    stopped = threading.Event()

    def close():
        nonlocal closing
        if closing or not messagebox.askokcancel('結束 AI Run Relay',
                '停止排程並保存進度？進行中的工作下次可能需要確認後續跑。', parent=root):
            return
        closing = True
        for child in frame.winfo_children():
            if isinstance(child, ttk.Button):
                child.state(['disabled'])
        status.set('正在停止工作並保存進度，請稍候…')
        def stop():
            try:
                service.close()
            finally:
                stopped.set()
        threading.Thread(target=stop, daemon=False).start()
        def check():
            if stopped.is_set():
                root.destroy()
            else:
                root.after(100, check)
        check()

    root.protocol('WM_DELETE_WINDOW', close)
    try:
        root.mainloop()
    finally:
        if not closing:
            service.close()
    return 0
