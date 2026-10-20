# AI Run Relay

[![Tests](https://github.com/RunIron/ai-run-relay-core/actions/workflows/test.yml/badge.svg)](https://github.com/RunIron/ai-run-relay-core/actions/workflows/test.yml)

**This repository contains the public v0.1.8 source release. Use it only within the rights and limitations stated in [LICENSE](LICENSE).**

**Queue your work, let the tool handle the waiting, and resume automatically when quota returns.**

**Commercial use requires prior written authorization from the project owner. See [LICENSE](LICENSE).**

AI Run Relay is a local AI job queue. It saves the result of every completed step, waits when it hits a usage limit, and then continues the original session. The dashboard lets you add jobs, watch countdowns, review results, cancel jobs and export logs.

**v0.1.8 / installer test candidate.** Scheduling, the Codex protocol flow, and the Claude Code CLI flow are covered by automated tests; neither has been verified end-to-end with a real subscription account **through the packaged installer** (the Claude Code provider has been run by hand against the real CLI during development — see [Architecture](docs/ARCHITECTURE.md#providers) — but that is not the same as installer-level release testing). This version connects to the **official Codex app-server**, the **official Claude Code CLI**, and a simulation mode that uses no quota. Providers are pluggable (see [Architecture](docs/ARCHITECTURE.md#providers)); Gemini is not implemented yet. Every provider is limited to read-only analysis with text results; autonomous file writes, email and publishing are not available.

**Claude Code provider — read before using.** Anthropic's Agent SDK terms state: *"Unless previously approved, Anthropic does not allow third party developers to offer claude.ai login or rate limits for their products... Use the API key authentication methods described in the Quickstart instead."* ([source](https://docs.claude.com/en/docs/agent-sdk/overview)). This provider reuses your local `claude` CLI's own subscription sign-in, the same pattern used for Codex — that is exactly the thing the clause above addresses, and this project has not sought or received approval for it. Using it is a compliance decision for the account owner to make, not something this README resolves on your behalf.

## Installers for regular users

Targets are a Windows x64 setup wizard and Linux x86_64 `.deb` / `.tar.gz` packages; users do not need Python.
See the [installation guide](public/INSTALL.md) and the [validation record](docs/VALIDATION.md) for the platform files that were actually produced.
Maintainers: see the [build guide](docs/BUILD.md). `PUBLIC-INTRO.zip` contains documentation only and is not an installer.
Commercial licensing contact: runiron.wu@gmail.com.

## Run from source (developers)

Requires Python 3.10 or later. No third-party Python packages are needed.

```bash
cd ai-run-relay
python3 -m relay --demo --open
```

On Windows:

```powershell
py -3 -m relay --demo --open
```

Open <http://127.0.0.1:8765>. The demo completes the first step, simulates quota exhaustion on the second step, waits 8 seconds, and then finishes the remaining steps. Simulated output is clearly labeled and does not represent real AI analysis.

The default workspace on first run is `~/AI-Run-Relay-workspace` (on Windows, a folder with the same name in your user profile), not the program folder. To change it, enter an existing absolute path under **Settings & tools → Default workspace** and save. Existing jobs keep their original folder.

To start an empty dashboard: `python3 -m relay --open`. Press Ctrl+C to stop. Starting again with the same data folder restores your earlier jobs.

## Use your own Codex subscription

1. Install the official CLI by following the [Codex CLI documentation](https://learn.chatgpt.com/docs/codex/cli) and make sure `codex` is on your PATH.
2. Run `codex login` on your own computer and choose **Sign in with ChatGPT**. Relay provides no sign-in form and never reads or copies credential files.
3. Choose the folder Relay may analyze:

   ```bash
   python3 -m relay --workspace /absolute/path/to/research --open
   ```

4. In the dashboard, choose **Codex CLI**, enter a job name and one step per line, for example "Summarize the documents in this folder", "Compare the options", "Write a conclusion". Results are stored in the Relay database and can be viewed or exported from the dashboard.

Check your environment with `python3 -m relay --doctor`. A detected CLI only means it is installed; sign-in, quota and protocol compatibility are checked when a job starts.

Relay only accepts ChatGPT sign-in managed by the official CLI. API-key sign-in pauses the job; **Relay never switches to separately billed API usage.** The models and quota available after sign-in are determined by your plan.

## Use your own Claude Code subscription

See the compliance note above before using this provider.

1. Install the [Claude Code CLI](https://code.claude.com) and make sure `claude` is on your PATH.
2. Run `claude` once in a terminal and complete sign-in with your Claude subscription. Relay provides no sign-in form and never reads `~/.claude/.credentials.json` or any other credential file.
3. Choose the folder Relay may analyze (same `--workspace` flag as Codex, shared across providers).
4. In the dashboard, choose **Claude Code**, enter a job name and one step per line. Results are stored in the Relay database and can be viewed or exported from the dashboard.

Relay strips `ANTHROPIC_API_KEY` from the subprocess environment so a job can never fall back to separately billed API usage. Every job runs read-only: `--permission-mode dontAsk --restricted --strict-mcp-config --safe-mode` plus an explicit `--disallowedTools` list blocking Bash, Edit, Write, NotebookEdit, Task (subagents), WebFetch, and `ExitPlanMode` — verified by hand to produce zero file writes anywhere on disk, including outside the job's own workspace (an earlier `--permission-mode plan` attempt looked safer but silently wrote a plan file to `~/.claude/plans/`; see [Architecture](docs/ARCHITECTURE.md#providers)).

Unlike Codex, there is no official rate-limit query for Claude Code. A usage-limit cutoff is detected by matching known phrases in the CLI's own failure text (the same technique [claude-nightshift](https://github.com/dujunyi416/claude-nightshift) uses, without reading its credential file or calling its undocumented usage endpoint), so the reset time is always reported as unknown and Relay falls back to its estimated backoff (5–60 minutes, capped at 6 attempts) rather than a platform-reported countdown.

## Behavior

| Situation | Behavior |
|---|---|
| Normal run | Ordered by priority (10 is highest), first-in first-out within the same priority; one step runs at a time |
| Quota exhausted with a known reset time | The time is saved durably and checked again after a small buffer; no hard-coded 5- or 12-hour waits |
| Several usage windows exhausted (Codex) | Only the codex bucket for this provider is checked; for its primary/secondary windows the latest reset wins; other buckets do not block |
| Reset time unknown (always true for Claude Code; Codex when the platform doesn't report one) | Marked "estimated"; backoff of about 5, 10, 20, 40, 60 minutes; at most 6 automatic attempts per step |
| Other jobs on the same platform | Share the waiting state to avoid simultaneous retries; simulation, Codex and Claude Code each have their own, unshared quota bucket |
| Program closed while waiting | Waiting time and completed results are saved; scheduling continues after restart |
| Power loss or shutdown during a real run | The unconfirmed step becomes "Needs review" so you can check it before resuming, instead of blindly redoing it |
| Computer asleep or off | Nothing runs during that time; jobs are checked again once the service is running |
| Queue paused | No new steps start; the current step continues (cancel it if needed) |
| Job cancelled | Codex: sends `turn/interrupt`, waits up to 2 seconds for stop confirmation. Claude Code: there is no interrupt protocol for a one-shot `claude -p` call, so the process is terminated directly. Either way, actions already taken are not rolled back |
| Sign-in lost, approval required, timeout | The job pauses for review; Relay never approves on your behalf |
| A job older than 7 days | Automatic scheduling stops by default; if the platform reports a later reset, the limit extends to one hour after that reset |

"Completed" means the official runner reported that the turn completed. **It is not a check that the content is correct.** Review important results yourself. Only completed steps are saved as checkpoints; tokens generated in an unfinished step cannot be guaranteed to resume.

## Data and permissions

- Default data folder: `~/.ai-run-relay/`. SQLite stores jobs, outputs, session IDs and events. Change it with `--data-dir /path`.
- Data stays on your computer. When a job runs, the prompt and the selected workspace data are processed by that provider's official service (Codex or Claude Code).
- The dashboard binds only to `127.0.0.1` and checks Host, Origin and a CSRF token. It is not a public website or a multi-user service; do not reverse-proxy it to the internet.
- Only one Relay process may use a data folder; an operating-system lock prevents double runs.
- A new job's working folder must be inside the current workspace. Switching workspaces does not change existing jobs. This is not a complete data-isolation sandbox.
- Relay stores no API keys, reads no browser cookies, and never rotates accounts to get around quota.
- Do not commit your private SQLite database, exported results, or either provider's configuration or sign-in files to GitHub.
- Codex and Claude Code each use your existing CLI configuration. For how external MCP servers, hooks and plugins are checked and limited per provider, see [Architecture and limits](docs/ARCHITECTURE.md).

## Development and tests

```bash
python3 -m unittest discover -s tests -v
```

The tests use a simulated clock and a fake app-server, so they consume no AI quota. Without a real CLI you can still try the full simulated scheduling flow.

Optional install: `python3 -m pip install .`, then run `ai-run-relay --open`.

## Source sharing and commercial licensing

**For non-commercial use you may use, modify and share this software free of charge under [LICENSE](LICENSE). Commercial use requires a separate written license from the project owner, obtained in advance.**

Commercial use includes enterprise operations, customer services, paid deployment, SaaS, and integration into commercial products. Contact: runiron.wu@gmail.com. This public source release is distributed under the accompanying non-commercial license; it is not MIT and is not represented as an OSI-approved open-source license.

The complete source tree is intentionally published in this repository for non-commercial use. Review [CORE_PROTECTION.md](docs/CORE_PROTECTION.md) and [RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md) before producing derivatives or releases. Complete your own end-to-end testing with your own subscription(s) before relying on the software — and, for Claude Code specifically, your own read of the compliance note above. This is an independent implementation and does not copy unsnooze code.

Possible next steps: an official Gemini CLI provider, job dependencies, acceptance rules, desktop packaging, a background service, resolving the Claude Code compliance question above (through prior Anthropic approval or an API-key-billed alternative). Cross-platform support is an architectural direction; not every AI subscription product is supported today.

## Changes in this release

See [CHANGELOG.md](CHANGELOG.md).

## Official protocol references

- [Codex app-server](https://learn.chatgpt.com/docs/app-server): initialization, sign-in mode, usage windows, thread/turn protocol.
- [Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode): background on automation and session resumption.
- [Claude Code headless mode](https://docs.claude.com/en/docs/agent-sdk/headless): `-p`/`--output-format`/`--resume` reference.
- [Claude Agent SDK overview](https://docs.claude.com/en/docs/agent-sdk/overview): the third-party claude.ai sign-in/rate-limit restriction quoted above.

Documentation last checked: 2026-10-20. The official tools may change; providers need ongoing compatibility testing.
