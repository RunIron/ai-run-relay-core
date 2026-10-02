# AI Run Relay

**This repository contains the public v0.1.6 source release. Use it only within the rights and limitations stated in [LICENSE](LICENSE).**

**Queue your work, let the tool handle the waiting, and resume automatically when quota returns.**

**Commercial use requires prior written authorization from the project owner. See [LICENSE](LICENSE).**

AI Run Relay is a local AI job queue. It saves the result of every completed step, waits when it hits a usage limit, and then continues the original session. The dashboard lets you add jobs, watch countdowns, review results, cancel jobs and export logs.

**v0.1.6 / installer test candidate.** Scheduling and the Codex protocol flow are covered by automated tests; the release has not yet been verified with a real subscription account. This version connects to the **official Codex app-server** and to a simulation mode that uses no quota. Claude and Gemini providers are not implemented yet. Codex jobs are limited to read-only analysis with text results; autonomous file writes, email and publishing are not available.

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

## Behavior

| Situation | Behavior |
|---|---|
| Normal run | Ordered by priority (10 is highest), first-in first-out within the same priority; one step runs at a time |
| Quota exhausted with a known reset time | The time is saved durably and checked again after a small buffer; no hard-coded 5- or 12-hour waits |
| Several usage windows exhausted | Only the codex bucket for this provider is checked; for its primary/secondary windows the latest reset wins; other buckets do not block |
| Reset time unknown | Marked "estimated"; backoff of about 5, 10, 20, 40, 60 minutes; at most 6 automatic attempts per step |
| Other jobs on the same platform | Share the waiting state to avoid simultaneous retries; simulation and Codex do not share quota |
| Program closed while waiting | Waiting time and completed results are saved; scheduling continues after restart |
| Power loss or shutdown during a real run | The unconfirmed step becomes "Needs review" so you can check it before resuming, instead of blindly redoing it |
| Computer asleep or off | Nothing runs during that time; jobs are checked again once the service is running |
| Queue paused | No new steps start; the current step continues (cancel it if needed) |
| Job cancelled | Sends `turn/interrupt`, waits up to 2 seconds for stop confirmation, then cleans up the process; actions already taken are not rolled back |
| Sign-in lost, approval required, timeout | The job pauses for review; Relay never approves on your behalf |
| A job older than 7 days | Automatic scheduling stops by default; if the platform reports a later reset, the limit extends to one hour after that reset |

"Completed" means the official runner reported that the turn completed. **It is not a check that the content is correct.** Review important results yourself. Only completed steps are saved as checkpoints; tokens generated in an unfinished step cannot be guaranteed to resume.

## Data and permissions

- Default data folder: `~/.ai-run-relay/`. SQLite stores jobs, outputs, session IDs and events. Change it with `--data-dir /path`.
- Data stays on your computer. When Codex runs, the prompt and the selected workspace data are processed by the official Codex service.
- The dashboard binds only to `127.0.0.1` and checks Host, Origin and a CSRF token. It is not a public website or a multi-user service; do not reverse-proxy it to the internet.
- Only one Relay process may use a data folder; an operating-system lock prevents double runs.
- A new job's working folder must be inside the current workspace. Switching workspaces does not change existing jobs. This is not a complete data-isolation sandbox.
- Relay stores no API keys, reads no browser cookies, and never rotates accounts to get around quota.
- Do not commit your private SQLite database, exported results, Codex configuration or sign-in files to GitHub.
- Codex uses your existing CLI configuration. For how external MCP servers and hooks are checked and limited, see [Architecture and limits](docs/ARCHITECTURE.md).

## Development and tests

```bash
python3 -m unittest discover -s tests -v
```

The tests use a simulated clock and a fake app-server, so they consume no AI quota. Without a real CLI you can still try the full simulated scheduling flow.

Optional install: `python3 -m pip install .`, then run `ai-run-relay --open`.

## Source sharing and commercial licensing

**For non-commercial use you may use, modify and share this software free of charge under [LICENSE](LICENSE). Commercial use requires a separate written license from the project owner, obtained in advance.**

Commercial use includes enterprise operations, customer services, paid deployment, SaaS, and integration into commercial products. Contact: runiron.wu@gmail.com. This public source release is distributed under the accompanying non-commercial license; it is not MIT and is not represented as an OSI-approved open-source license.

The complete source tree is intentionally published in this repository for non-commercial use. Review [CORE_PROTECTION.md](docs/CORE_PROTECTION.md) and [RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md) before producing derivatives or releases. Complete your own end-to-end testing with your Codex subscription before relying on the software. This is an independent implementation and does not copy unsnooze code.

Possible next steps: official Gemini / Claude CLI providers, job dependencies, acceptance rules, desktop packaging, a background service. Cross-platform support is an architectural direction; not every AI subscription product is supported today.

## Changes in this release

See [CHANGELOG.md](CHANGELOG.md).

## Official protocol references

- [Codex app-server](https://learn.chatgpt.com/docs/app-server): initialization, sign-in mode, usage windows, thread/turn protocol.
- [Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode): background on automation and session resumption.

Documentation last checked: 2026-10-02. The official tools may change; providers need ongoing compatibility testing.
