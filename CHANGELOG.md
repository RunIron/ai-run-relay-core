# Changelog

## 0.1.6 (2026-10-02)

### English only

- The dashboard is now English-only. The runtime translation layer and the language picker were removed.
- All backend messages are English: validation errors, job events, recovery notes, Codex provider errors and notices, server errors, CLI help and `--doctor` output.
- The prompt sent to Codex is English.
- All documentation is English. The per-version reports were merged into `docs/VALIDATION.md`, and `docs/BUILD_V014.md` became `docs/BUILD.md`.
- `POST /api/preferences` now accepts only `{"admin_tools_open": bool}`; the `ui_language` setting is ignored.

### Fixes

- Dashboard: the old translation regexes used `\\d` in regex literals, so dynamic text such as countdowns was never translated and stayed in Chinese. Countdowns now read "1 h 2 min 5 s".
- Dashboard: the connection status ("Connected locally" / "Queue paused"), the Codex provider note and server messages were shown in Chinese even in English mode.
- Dashboard: the "Connection lost" banner now clears after the connection recovers.
- Dashboard: "Settings & tools" no longer hides the New job form. Only the workspace and usage panels collapse, and saving a workspace no longer collapses the panel.
- Dashboard: the page no longer walks the whole DOM to translate text on every 2-second poll.
- Dashboard: failed jobs can be cancelled (dismissed) as well as retried.
- Dashboard: the workspace "Saved" confirmation is shown in green instead of the error color.
- Dashboard: notifications and `localStorage` failures (private windows, revoked permission) no longer throw.
- Windows: the Codex subprocess and `taskkill` start with `CREATE_NO_WINDOW`, so the installed app no longer flashes a console window for every step.
- Scheduler: when the platform reports a reset later than the 7-day limit (for example 8 days), every job sharing that wait now gets its deadline extended. Previously only the job that received the quota reply was extended, and the other waiting jobs failed on day 7.
- Tests: the symbolic-link check and the desktop self-test are skipped, instead of erroring, when Windows lacks symlink rights or the Python build has no Tcl/Tk. CI and the packaged build still run them.
- Worker: an unexpected error in one scheduling pass no longer kills the worker thread and silently stops the queue.
- Startup recovery: interrupted simulation jobs are re-queued without a stale "check the last step" error.
- Server: POST routes ignore query strings (`/api/jobs?x=1` used to return "Unknown endpoint").
- Docs: the Codex CLI link pointed to a 404 page; it now points to https://learn.chatgpt.com/docs/codex/cli. The desktop launcher's help link was updated to match.
- Docs: public install notes still described v0.1.4 and a private core. They now describe v0.1.6 and the public source release.

### Tests

- New test: no Chinese characters in shipped code or docs.
- New tests: preference validation, POST routes with a query string, mock startup recovery, worker survival after a failing pass.

## 0.1.5

- Public English source release with an optional Traditional Chinese dashboard and collapsible settings.

## 0.1.4

- Native installers (Nuitka): Windows x64 setup and Linux `.deb` / `.tar.gz`, plus the `--self-test` smoke check.

## 0.1.3

- Paged summary projection with revision deltas, on-demand job details, a default workspace outside the program folder, graceful Codex interrupt, one-time recovery for missing sessions, final-answer filtering, and codex-bucket quota selection.

## 0.1.1

- Switched from MIT to the AI Run Relay Non-Commercial License 1.0.

## 0.1.0

- First prototype: durable SQLite queue, simulation mode and the Codex app-server provider.
