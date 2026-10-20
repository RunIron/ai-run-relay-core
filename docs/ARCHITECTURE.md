# Architecture and Limits

## Modules

- `relay/core.py`: SQLite job queue, state transitions, shared platform waiting, checkpoints, process lock. Knows nothing about any specific provider; it only calls the `Provider` contract.
- `relay/providers.py`: the `Provider` contract (`available()`, `run()`) and the shared `Result` type every adapter returns. See "Providers" below.
- `relay/codex.py`: runs the official `codex app-server` as a subprocess over JSON-RPC; never calls private HTTP endpoints directly.
- `relay/claude_code.py`: runs the official `claude` CLI as a one-shot `-p --output-format json` subprocess per step (no persistent session protocol like Codex's app-server); never reads `~/.claude/.credentials.json` or calls any undocumented endpoint. See "Providers" below for its specific caveats.
- `relay/server.py`: local HTTP service with a random CSRF token generated on every start.
- `relay/desktop.py`: Tk launcher window for the installed app; hosts the same local service on a free port.
- `relay/static/index.html`: English dashboard with no CDN or front-end framework.

## States

`queued → running → queued / succeeded`

Quota unavailable: `running → waiting_quota → running`.

Unconfirmed interruption: `running → needs_review`. After checking, the user confirms and the job returns to `queued`. A failure also needs confirmation before it is retried. Cancellation is a final state.

## Checkpoints and resuming

Each successful step saves its result and the new `step_index` in a single SQLite transaction. The official thread ID is saved before the turn runs; resuming continues with that ID, so the existing thread keeps its context and earlier results are not re-sent each step. Only when the thread is explicitly missing or expired is a new thread created, once, with the saved results attached. Sign-in errors and general RPC errors never create a new thread automatically.

If the AI finished but Relay stopped before saving, exactly-once cannot be claimed. On restart, real jobs become `needs_review`; check the official session and any external results first. Intermediate model output is never treated as a successful checkpoint.

The worker loop catches unexpected errors from a scheduling pass and keeps running, so one bad pass cannot silently stop the queue.

## Quota

**Codex:** `account/rateLimits/read` is read before each run. By default only the `codex` bucket is used; a 100% unrelated bucket does not block execution. Unknown mappings are not guessed; limited backoff is used only if the real request is still rate-limited. Official usage windows and reset times take priority.

**Claude Code:** there is no equivalent structured query. A usage-limit cutoff is detected only by matching known phrases (`relay/claude_code.py`'s `_LIMIT_TEXTS`, reused from [claude-nightshift](https://github.com/dujunyi416/claude-nightshift)) in whatever text the `claude` subprocess itself prints — never by reading its OAuth credential file or calling its undocumented `/api/oauth/usage` endpoint the way that project does. This means the reset time is always unknown for this provider; it always falls into the "reset time unknown" backoff path below, never the platform-reported one.

For both: the dashboard shows a snapshot from the most recent job query, not continuous live monitoring. Unknown data is shown as unknown; when a reset time is missing, limited backoff is used (5, 10, 20, 40, 60 minutes, capped at 6 attempts). One Relay process maps to one local sign-in per provider; there is no account pool.

## Permissions and integrations

Only read-only jobs are allowed, and additional permission approvals are refused. A read-only file system does not mean external tools have no side effects, so both providers are configured to refuse external MCP servers, plugins, hooks and notify integrations.

**Codex:** checks settings through the official `config/read` and `configRequirements/read` methods, pauses if any of these integrations or a `hooks.json` file is enabled, and disables Apps in the subprocess. It never modifies the user's configuration files. The thread sandbox uses `read-only` from the official schema; the turn policy uses `readOnly` with `networkAccess: false` (two different enum spellings in the official protocol). Permission or interaction requests that cannot be handled automatically pause the job; Relay never answers them on the user's behalf.

**Claude Code:** every job runs with `--permission-mode dontAsk --permission-prompts none --restricted --strict-mcp-config --safe-mode --disallowedTools "Bash,Edit,Write,NotebookEdit,Task,WebFetch,ExitPlanMode"`. `--restricted` drops code-execution tools and WebFetch and ignores project/user settings; `--safe-mode` disables hooks, installed plugins, and CLAUDE.md auto-discovery; `--strict-mcp-config` drops MCP servers (none are passed, so this means zero); the explicit disallow list is a second, independent layer covering writes, subagents, and plan-exit. This combination was reached only after empirically finding that the more obvious `--permission-mode plan` writes a plan markdown file to `~/.claude/plans/` as a side effect even with every write tool disallowed — a real violation of "no file writes" that shows up outside the job's own workspace, so it is easy to miss if you only check the job's cwd. Disallowing `ExitPlanMode` on a non-plan permission mode is what actually stops it; see the module docstring in `relay/claude_code.py` and `tests/test_claude_code.py::test_permission_mode_is_not_plan` for the regression lock.

Real CLI end-to-end testing is not complete for either provider at installer-release level (Claude Code has been run by hand against the real CLI during development, including a read/resume/blocked-write pass with no stray files anywhere on disk — but that is a development-time spot check, not release-level verification). An incompatible CLI, or one whose settings cannot be checked, stops at manual review for Codex; Claude Code falls back to the generic "unexpected output" review path if its JSON doesn't parse as expected.

On Windows the subprocess and its cleanup (`taskkill`) start with `CREATE_NO_WINDOW`, so the installed app does not flash console windows. This applies to both providers.

The working-folder restriction is not complete confidentiality isolation; the read scope of the official sandbox is decided by each provider's own CLI. Do not assign tasks that need higher privileges and expect Relay to bypass the limits.

**Compliance note (Claude Code only):** reusing the local `claude` CLI's subscription sign-in for unattended, automated job processing is the pattern Anthropic's Agent SDK terms restrict for third-party products without prior approval (see the README's Claude Code section for the exact clause and link). This is a known, unresolved tension this project has chosen to ship anyway rather than hide; it is not a Relay-specific bug and there is nothing in the code that works around it — the restriction is about the usage pattern itself, not an implementation detail.

## Providers

`Engine(store, workspace, adapters={name: provider, ...})` accepts any mapping of provider name to an object satisfying `relay.providers.Provider`: a callable-shaped contract of `available() -> bool` and `run(job, prompt, on_session, stop) -> Result`. `core.py` never special-cases a provider name beyond the reserved `mock` (the built-in, side-effect-free simulation); whatever names appear as keys in `adapters` become valid values for a job's `provider` field, and `GET /api/state` reports each one's current `available()` under that same name. `CodexAdapter` and `ClaudeCodeAdapter` are both registered as default adapters — adding a further CLI means writing one adapter class against this contract, not touching the scheduler.

The two shipped adapters differ in shape, not just target service: Codex keeps one JSON-RPC subprocess open per job and exchanges structured messages over it (persistent session, mid-turn approval requests, a live quota-read call); Claude Code has no equivalent protocol, so each step is an independent one-shot `claude -p` call, cancellation is a plain process kill instead of an interrupt request, and quota is inferred from text rather than queried. A future adapter is not expected to look like either one specifically — only to satisfy `available()`/`run()` and return a `Result`.

## Current boundaries

Codex, Claude Code and the mock provider ship today; Gemini support is not implemented (the extension point above exists, but no adapter for it has been written). There is no cross-host scheduling, job dependency graph, cost estimate, token budget, OS background-service install, or email/mobile push. Browser notifications must be enabled manually and need the page to stay open. Execution is serial, globally and per platform; this is not a distributed queue.

The Claude Code provider carries an open compliance question (see "Permissions and integrations" above) and weaker quota detection than Codex (see "Quota" above); both are documented, not hidden, and neither has a code-level fix available today.

Limits: a 15-minute timeout per run, 6 automatic attempts per step, and a default 7-day waiting limit, extended to one hour after the reset when the platform explicitly reports a later reset. The database never deletes historical outputs automatically; back it up and manage its size for long-term use.

## Summary and detail API

`GET /api/state?page=0&page_size=50&since=revision` returns changed summaries, the page's `job_order`, totals and status counts. The first request and page changes omit `since`. If `job_order` contains an ID that the client has neither cached nor received a summary for (new data shifted page membership), the client fetches that page once more without `since`. Only `GET /api/jobs/{id}` returns full steps and results.

SQLite stores a summary/status/revision projection, so polling and scheduling scans never parse the outputs of all completed jobs. The front end keeps keyed DOM cards and output `pre` nodes, and only changes `textContent` when the text actually changed.

`POST /api/workspace` requires the same CSRF check; changing the default folder only affects new jobs. `POST /api/preferences` accepts `{"admin_tools_open": bool}`. POST routes match on the URL path, ignoring any query string. A full export still uses `/api/export` and runs only when the user requests it.
