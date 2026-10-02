# Architecture and Limits

## Modules

- `relay/core.py`: SQLite job queue, state transitions, shared platform waiting, checkpoints, process lock.
- `relay/codex.py`: runs the official `codex app-server` as a subprocess over JSON-RPC; never calls private HTTP endpoints directly.
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

`account/rateLimits/read` is read before each run. The dashboard shows a snapshot from the most recent job query, not continuous live monitoring. By default only the `codex` bucket is used; a 100% unrelated bucket does not block execution. Unknown mappings are not guessed; limited backoff is used only if the real request is still rate-limited. Unknown data is shown as unknown. Official usage windows and reset times take priority; when they are missing, limited backoff is used. One Relay process maps to one local Codex sign-in; there is no account pool.

## Permissions and integrations

Only read-only jobs are allowed, and additional permission approvals are refused. A read-only file system does not mean external tools have no side effects, so use a Codex configuration without private external MCP servers, plugins, hooks or notify. The provider checks settings through the official `config/read` and `configRequirements/read` methods, pauses if any of these integrations or a `hooks.json` file is enabled, and disables Apps in the subprocess. It never modifies the user's configuration files. Permission or interaction requests that cannot be handled automatically pause the job; Relay never answers them on the user's behalf.

The thread sandbox uses `read-only` from the official schema; the turn policy uses `readOnly` with `networkAccess: false`. These are two different enum spellings in the official protocol. Real CLI end-to-end testing is not complete; an incompatible CLI, or one whose settings cannot be checked, stops at manual review.

On Windows the subprocess and its cleanup (`taskkill`) start with `CREATE_NO_WINDOW`, so the installed app does not flash console windows.

The working-folder restriction is not complete confidentiality isolation; the read scope of the official sandbox is decided by Codex. Do not assign tasks that need higher privileges and expect Relay to bypass the limits.

## Current boundaries

Only the Codex and mock providers exist. There is no cross-host scheduling, job dependency graph, cost estimate, token budget, OS background-service install, or email/mobile push. Browser notifications must be enabled manually and need the page to stay open. Execution is serial, globally and per platform; this is not a distributed queue.

Limits: a 15-minute timeout per run, 6 automatic attempts per step, and a default 7-day waiting limit, extended to one hour after the reset when the platform explicitly reports a later reset. The database never deletes historical outputs automatically; back it up and manage its size for long-term use.

## Summary and detail API

`GET /api/state?page=0&page_size=50&since=revision` returns changed summaries, the page's `job_order`, totals and status counts. The first request and page changes omit `since`. If `job_order` contains an ID that the client has neither cached nor received a summary for (new data shifted page membership), the client fetches that page once more without `since`. Only `GET /api/jobs/{id}` returns full steps and results.

SQLite stores a summary/status/revision projection, so polling and scheduling scans never parse the outputs of all completed jobs. The front end keeps keyed DOM cards and output `pre` nodes, and only changes `textContent` when the text actually changed.

`POST /api/workspace` requires the same CSRF check; changing the default folder only affects new jobs. `POST /api/preferences` accepts `{"admin_tools_open": bool}`. POST routes match on the URL path, ignoring any query string. A full export still uses `/api/export` and runs only when the user requests it.
