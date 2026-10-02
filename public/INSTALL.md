# Installing AI Run Relay

This guide covers the compiled installer packages. PUBLIC-INTRO.zip contains documentation only and is not an installer.
v0.1.6 is a test release; rely on the files actually attached and on the validation record.

## Windows 10/11, x64

Download `AI-Run-Relay-0.1.6-windows-x64-setup.exe`, double-click it, read the license, and finish the setup.
Open AI Run Relay from the Start menu. You do not need to install Python.
Unsigned test builds may show "Unknown publisher". Verify the source and the SHA256 checksum first; do not turn off your antivirus.
It installs for the current user and does not need administrator rights. Uninstalling keeps your job history.

## Linux, x86_64

Ubuntu/Debian desktop: download the `.deb` and run this in the folder that contains it:

```sh
sudo apt install ./AI-Run-Relay-0.1.6-linux-amd64.deb
```

Open AI Run Relay from the application menu, or run `ai-run-relay`.
Installing needs administrator rights; run it day to day as a regular user, not with sudo.
You do not need to install Python. The package manager installs the required system libraries.
The minimum glibc version depends on the build host (Ubuntu 24.04 builds require glibc 2.39). Alpine/musl and ARM are not supported.

Other glibc-based Linux: extract the `.tar.gz`, enter the folder, and run `./ai-run-relay`.
The archive does not install system libraries; other distributions still need individual verification.

On a Linux server without a desktop, use:

```sh
ai-run-relay --server --port 8765
```

By default only a browser on the same machine can connect. To reach a remote server from your own computer, use:

```sh
ssh -L 8765:127.0.0.1:8765 your-user@server
```

Then open http://127.0.0.1:8765. The service does not register itself to start at boot.

## First use

1. Open the program, click **Choose workspace folder**, and pick the folder that holds the data you want analyzed.
2. Click **Try a demo job** and watch the dashboard wait and then resume automatically. The demo uses no AI quota.
3. Real AI jobs need the official Codex CLI, signed in with your own ChatGPT account.
   The launcher window has a link to the official instructions. Relay does not bundle Codex, collect passwords, or provide AI quota.
4. After signing in, restart Relay, choose **Codex CLI** in the dashboard, and start with a small read-only analysis job.

Closing the browser does not stop jobs. Keep the Relay launcher window open; you can minimize it.
Quitting the program stops scheduling, and nothing runs while the computer is off or asleep. An interrupted job may need review before it resumes.
Quit Relay before upgrading. Your history is kept in `.ai-run-relay` in your home folder; the workspace is not inside the install folder.

Only the simulation and Codex providers are supported. Codex runs in read-only analysis / text-result mode, and real CLI compatibility still needs hands-on verification.
Quota resets follow the platform's actual information. Relay does not guarantee a fixed five-hour window and does not bypass platform limits.

Non-commercial use is covered by the included LICENSE. Commercial use requires prior written authorization: runiron.wu@gmail.com.
