# Release Checklist (v0.1.6)

- [ ] Run `python3 -m unittest discover -s tests -v` (Windows: `py -3 -m unittest discover -s tests -v`).
- [ ] Run `node tests/browser_smoke.cjs` on a machine with Playwright and Chromium.
- [ ] Test the Python and Codex CLI installation on the target Windows / Linux systems.
- [ ] Sign in with your own ChatGPT account and run a two-step read-only research job.
- [ ] Confirm both steps used the same thread and the first step's output was saved.
- [ ] Check quota data against a real platform limit; do not burn large amounts of quota on purpose.
- [ ] Confirm the job queries again and resumes after the platform reset.
- [ ] Interrupt a run and restart; confirm it needs manual review and completed steps are not redone.
- [ ] On Windows, confirm no console window flashes while a Codex job runs from the installed app.
- [ ] Confirm the release contains no private credentials, databases, results, or local absolute paths.
- [ ] Confirm the public README states which platforms and CLI versions each provider was tested with.
- [ ] Confirm the commercial licensing contact and rightsholder details, and check LICENSE.
- [ ] Complete the manual checks in [VALIDATION.md](VALIDATION.md).
- [ ] Confirm the public repository contains only intended source, documentation, tests, and release assets; never include personal data or credentials.

This release may only claim automated tests and simulated-flow verification. Do not claim that a real subscription account was verified or that every platform is supported.
