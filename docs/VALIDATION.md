# Validation

This file records what has and has not been verified, and how to run the remaining checks. It replaces the per-version reports `VALIDATION_V014.md` and `VERIFY_V013.md`; their history is summarized below.

## v0.1.6 (2026-10-02)

Status: test candidate, not yet published.

- All user-facing text (dashboard, desktop launcher, server and job messages, Codex prompts, CLI help, documentation) is English. A unit test fails if Chinese characters reappear in shipped code or docs.
- Dashboard JavaScript was checked in Chromium against a mocked API: no script errors; jobs in waiting, needs-review and completed states render in English; countdowns, quota and activity log render; the connection banner clears after recovery.
- Windows review run: 50 unit tests, 48 passed, 2 environment errors (no symlink privilege; test Python without Tcl resources). Both tests now skip in those environments. The same review found that a shared late platform reset only extended the deadline of the job that received it; this is fixed and covered by a regression test.
- Browser smoke test (`node tests/browser_smoke.cjs`) not run yet: Chromium was not available.
- Installers: the existing setup file is v0.1.5 and does not represent this source. v0.1.6 installers must be rebuilt and smoke-tested (GitHub Actions workflow) before release.
- **Not verified with a real account:** Codex sign-in, two-step resume, cancel confirmation and quota reset. Release v0.1.6 as a pre-release until the manual checks below pass.

Data from earlier versions: job events and error text already stored in an existing database stay in the language they were written in. New messages are English.

## Earlier versions

- **v0.1.4:** 42 unit tests passed. Linux x86_64 build (Nuitka 4.2.2, Python 3.12, Ubuntu 24.04) produced `.deb` and `.tar.gz` packages requiring glibc >= 2.39. The compiled self-test passed, including after unpacking the `.deb` and running with no external Python. The Windows installer, desktop GUI, apt installation and real Codex were not tested.
- **v0.1.3:** 40 unit tests passed. 200 jobs with 16 KiB output each produced a 37,097-byte summary response (about 4 ms, informational only). Changes: summary projection with paging and revisions, keyed DOM cards, default workspace outside the program folder, graceful interrupt, one-time recovery for missing sessions, final-answer filtering, and codex-bucket quota selection.
- **v0.1.0:** 19 unit tests passed; a five-hour wait was verified with an injected clock.

## Automated tests

```bash
python3 -m unittest discover -s tests -v
```

On Windows PowerShell, use `py -3` instead of `python3`.

The browser test uses intercepted HTTP with fake data; it calls no AI and changes no account:

```bash
npm install --no-save --package-lock=false playwright
npx playwright install chromium
node tests/browser_smoke.cjs
```

It checks that outputs are not loaded until expanded, that DOM nodes, text selection and output scroll position survive three polls, that a new row on another page is filled in, and that a 390 px phone width has no horizontal overflow.

## Real Codex subscription checks (run on your own computer)

1. Record `codex --version`, the operating system and the Relay version. Use your own official ChatGPT sign-in and never give tokens to anyone.
2. Create a separate test folder with a `sample.txt` containing non-sensitive notes, and select that folder in the dashboard.
3. Add a two-step read-only job: "Read sample.txt and list three key points", then "Write a short summary based on the previous step". Confirm the content is not the Relay source code, both results are saved, and no intermediate commentary is included.
4. Start a longer read-only job and cancel it. Check the activity log for "Session stop confirmed". This is different from the interrupt RPC merely succeeding. If it times out, confirm that the log says the stop was not confirmed, and do not claim a clean stop.
5. To test timeouts, use `CodexAdapter(timeout=<short seconds>)` in a test script with a separate data folder; do not change your main jobs.
6. Session expiry is mainly covered by the fake CLI tests; do not delete important real sessions. If you naturally hit an expired session, confirm the new ID, the recovery event, and that the original results are still present. Other errors should still pause the job.
7. When real quota runs out, compare the official display with Relay's bucket and reset time, and watch it resume after the next reset. Do not burn quota on purpose. Without enough evidence, keep the status "not yet verified with a real account".
8. On Windows, run a Codex job from the installed app and confirm no console window appears.

## Upgrading

Stop the old version and back up `~/.ai-run-relay/` (or your `--data-dir`) before starting the new one. SQLite adds summary and revision columns automatically; the migration test confirms outputs and original ordering are preserved. To roll back, restore the backup; never run old and new versions against the same data folder at the same time.

The `ui_language` setting from v0.1.5 is no longer used and is ignored.

## Performance figures

Tests print the HTTP response size and time for information only; there is no flaky millisecond threshold. Summaries are limited to 100 per page (default 50), events to 100. A full export and single-job details can still be large; they are read only when the user asks.

## Official reference

- https://learn.chatgpt.com/docs/app-server (turn/interrupt, agentMessage phase, rateLimitsByLimitId)
