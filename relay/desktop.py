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
        return self.engine.add({'title': 'Relay demo: resume after waiting', 'provider': 'mock',
                                       'steps': ['Organize materials', 'Wait for quota', 'Complete summary'], 'wait_seconds': 8})

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
        raise SystemExit('No desktop environment is available. Run ai-run-relay --server; use SSH port forwarding for remote access.')
    root.title(f'AI Run Relay {__version__}')
    root.geometry('640x480')
    root.minsize(590, 450)
    try:
        service = LocalService()
    except Exception as exc:
        messagebox.showerror('Could not start AI Run Relay', str(exc), parent=root)
        root.destroy()
        return 1
    frame = ttk.Frame(root, padding=24)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='AI Run Relay', font=('', 22, 'bold')).pack(anchor='w')
    ttk.Label(frame, text='Queue work and let Relay resume when quota is available.').pack(anchor='w', pady=(8, 16))
    status = tk.StringVar(value='Service is running. Choose a workspace, then open the dashboard.')
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
                messagebox.showerror('Workspace', str(exc), parent=root)

    def dashboard():
        if not webbrowser.open(service.url):
            messagebox.showinfo('Dashboard URL', f'Open this address in a browser:\n{service.url}', parent=root)

    def demo():
        service.demo()
        status.set('Demo job added. It resumes after about 8 seconds without using AI quota.')
        dashboard()

    def codex_help():
        found = bool(shutil.which('codex'))
        messagebox.showinfo('Connect your Codex account',
            ('Codex CLI was found; sign-in has not been verified.' if found else 'Codex CLI was not found.') +
            '\n\nFollow the official instructions to install it and sign in with ChatGPT.\nRestart Relay and select Codex in the dashboard.'
            '\n\nRelay never collects account passwords or installs third-party tools automatically.', parent=root)
        webbrowser.open('https://learn.chatgpt.com/docs/codex/cli')

    for label, command in [('Choose workspace folder', choose), ('Open dashboard', dashboard),
                           ('Try a demo job', demo), ('Connect Codex / setup help', codex_help)]:
        ttk.Button(frame, text=label, command=command).pack(fill='x', pady=4)
    ttk.Label(frame, text='Minimizing keeps Relay running. Closing it or putting the computer to sleep stops jobs.\n'
              'Commercial use requires prior written authorization: runiron.wu@gmail.com', wraplength=560).pack(anchor='w', pady=14)
    closing = False
    stopped = threading.Event()

    def close():
        nonlocal closing
        if closing or not messagebox.askokcancel('Quit AI Run Relay',
                'Stop scheduling and save progress? An interrupted job may need review before resuming.', parent=root):
            return
        closing = True
        for child in frame.winfo_children():
            if isinstance(child, ttk.Button):
                child.state(['disabled'])
        status.set('Stopping jobs and saving progress. Please wait…')
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
