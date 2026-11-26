# How LOYA NG was developed
This page is for anyone picking the project up later: where the code came from, how it was built and tested, which decisions shaped it, and what is still open. For how the code works today, read [ARCHITECTURE.md](ARCHITECTURE.md).
## Timeline
| Version | What changed | Why |
|---|---|---|
| LOYA Note 5.1.1 | PyQt6 desktop app. Sortable tables, Linux fixes, `{PLACEHOLDER}` detection that ignores shell `{}` and JSON braces, themed update screen, launcher log rotation, deps fingerprint cache, `--skip-update`, already running detection | Quality and compatibility release |
| LOYA Note 5.1.2 | Already running check no longer kills the open app on Windows, stale pid files cleaned, `datetime.utcnow()` removed, `cryptography` 42.0.5 to 48.0.1 | Bug fix patch |
| LOYA Note 6.0.0 | PyQt6 UI replaced by a local HTML, CSS and JS UI in a native pywebview window (WebView2 on Windows, WebKitGTK on Linux), plus a customizable Dashboard. Qt only HTML, PDF and structured Markdown note import and export were retired | One UI stack for both platforms, easier to style and test |
| LOYA NG 1.0.0 (2026-11-24) | Version numbering reset. Superset of 6.0.0 plus encryption at rest (SQLCipher and Argon2id), tags and a backlinks graph, the Terminal extension, the AI extension with an MCP server and AI Roles, Reporting, Chain Diagrams and CVE Intel | First public release under the NG name. Moving from 5.x or 6.0.0 is a one time fresh install, because the updater only accepts a strictly greater version |
| LOYA NG 1.0.1 (2026-11-26) | Fixes and features listed below | First update on top of the public release |
| LOYA NG 1.0.2 (2026-11-26) | Full terminal tabs work when the app runs without a console, and the AI panel lists every provider with the connected ones first | Bugs found right after 1.0.1 shipped |
| LOYA NG 1.0.3 (2026-11-26) | The launcher rebuilds the virtual environment when the system Python changes or its Python no longer starts, ties the dependency cache to the Python version, and reports an app that dies right after starting with its real error | A Kali upgrade from Python 3.13 to 3.14 left the venv unable to import pywebview while the launcher still said "running" |
## Since the 1.0.0 public release
- Settings > AI reorganized: Agents first, Connections on top, AI Assistant moved in.
- Crash diagnostics: `Logs/crash.log` through faulthandler, uncaught errors to the Note log, app output to `Logs/app_output.log`.
- Connections setup: CLI calls run as background jobs in their own process group, Cancel always works, the MCP server picks a free port when 8765 is busy.
- Launcher startup screen, and the sign in status no longer flips to "not signed in".
- Terminal right click menu, and Claude Code and Codex CLI entries in the AI panel.
- Chains: 7 demo diagrams and one New chain button with a chooser.
- The CLI working folder moved outside the repository, because Codex extends trust to the whole enclosing git repository.
- The setup guide answers installer questions, and Verify no longer waits for the installer.
- Full terminal mode with vendored xterm.js 6.0.0: Claude Code, Codex, vim and htop work inside LOYA terminal tabs.
- Windows data hardening fix: the recursive `icacls` call left every file in `Data/` and `Logs/` with an empty ACL, so the app fell into recovery mode with "Permission denied". Installs hurt by it heal on the next start.
- AI written notes and commands write changeable values as `{Element}` placeholders, reusing existing elements by meaning, through the shared rule in `Cores/Services/ai_element_rules.py` and the new `parameter_match` MCP tool.
- Planning and report files were removed from the root and this `Docs/` folder was added.
- Launcher: a system Python upgrade (3.13 to 3.14 on Kali) no longer breaks an existing install. The venv is rebuilt when its Python changed or does not start, the dependency cache records the venv Python, `import webview` is checked, and an app that exits within 2.5 s of launch is reported with its output.
## How the work was organized
- **The original is the behaviour spec.** [LOYA Note](https://github.com/emaldos/LOYA-Note) defines how a feature should behave. The `port-from-original` skill compares each feature as `original file:line` against `NG file:line` and classifies it as present, different or missing. The usual gap was missing wiring, not missing code: logic copied into a service but never called.
- **Phased plans sized for one AI session.** Big areas got a plan file with numbered sessions (the terminal plan had 31, S01 to S30b). Each session listed its files, dependencies and size, and a tracking table marked it implemented, flagged off, partial or not implemented. The suggested order was quick wins, then foundations, then the headline features, then the risky platform work.
- **Parallel work packages.** Work was split between agents by disjoint file sets, with ownership rules for shared files such as the API classes in `Cores/Bridge/api.py`.
- **Storage rebuild in two phases.** `Cores/storage_migration_plan.md` describes it: phase 1 added `crypto_store.py` and `db_driver.py`, phase 2 wired them in.
- **Security audit.** [SECURITY-AUDIT.md](SECURITY-AUDIT.md) ran in three stages (core and updater, then reporting, terminal, CVE, chains and the MCP tools, then a re-check after the storage rebuild). It enumerated every bridge method against the lock allow list, checked with an AST pass that every MCP tool authorizes, tried XSS payloads, checked dependencies against OSV and grepped git history for secrets. 39 findings: 37 fixed, SA-16 (unsigned updates) accepted, SA-37 (CSV formula escaping) open by decision. Each fix has a regression test named after its finding ID.
- **Linux UI audit.** Run on Kali in VMware under a harness that became the `linux-ui-audit` skill. It found 19 Linux only bugs (L1 to L19).
- **Linux end to end round.** Seven parallel testers, each with its own copy, demo data and Xvfb display, drove the app with real xdotool input. 40 bugs were fixed with a test each, then 9 more in a second round.
- **Quality gate.** `.claude/skills/ng-quality-gate/scripts/gate.sh` runs before every commit. See [DEVELOPMENT.md](DEVELOPMENT.md).
- **WSL is not Linux.** WSL is the quick loop for kernel behaviour (pty, `TIOCSWINSZ`, `setsid`), but it silently passes things a real desktop breaks: work area maximize, multi monitor, pkexec, notify-send and window manager drag. A real Kali VM is the check before a release.
## Decisions and lessons worth keeping
- **Check control characters before calling a key broken.** "Ctrl+C does nothing" turned out to be a raw 0x03 byte in the source.
- **Incremental terminal rendering commits only complete lines.** Appending raw chunks mangled ANSI codes split across reads. This is tested against hundreds of random chunk splits.
- **`tests/` was once git ignored by accident.** Check `.gitignore` when a new folder will not commit.
- **ConPTY shipped flagged off with a pipe fallback**, because it could not be reproduced in the sandbox. Full terminal mode now uses it. Do not re-derive the struct definitions in `conpty.py`.
- **The Linux venv uses `--system-site-packages`** and skips the `pywebview[gtk]` extra, which pins a PyGObject that has to be built from source.
- **Linux elevation prefers sudo inside the terminal**; the pkexec path is unverified.
- **Never read window geometry inside `closing` or GTK callbacks**, and defer window destroy so the bridge call can return. Both deadlock otherwise.
- **WebKitGTK rendering** needs `WEBKIT_DMABUF_RENDERER_FORCE_SHM=1` and `WEBKIT_SKIA_ENABLE_CPU_RENDERING=1`. Disabling DMABUF instead killed the blur effects, and CSS tricks did not fix the ghost tiles.
- **WebKitGTK has no `localStorage`** in this setup, so UI state persists through the bridge into `settings.json`. It also needs `-webkit-user-select`, and its file dialogs are case sensitive with no overwrite confirmation (the app patches that).
- **The WebKitGTK 2.52 console does not reach stdout**, so the audit harness collects page errors itself.
- **No keyring held key when encryption is off.** The PIN derives a key with Argon2id. A keyring key would add lock out risk for little protection and would bind backups to one machine.
- **A restore never rolls back the audit log and never silently brings back an old PIN.**
- **On Windows, `icacls` with `(OI)(CI)` grants and `/T` empties file ACLs.** Harden the folder only and let the files inherit.
- **ConPTY children inherit a redirected parent's stdio.** LOYA runs under `pythonw` with stdout sent to a log, so `CreateProcessW` must pass `STARTF_USESTDHANDLES` with null handles, or the shell writes to the log, reads EOF and exits. Test ConPTY from a process with redirected stdio, not from a console.
- **Git for Windows converts line endings on checkout and on `git archive`** when `core.autocrlf=true`. This repository sets `core.autocrlf=false` locally, and release zips are built with `git -c core.autocrlf=false archive`, so Linux installs never get CRLF shell scripts. Files the app writes itself use `newline="\n"`.
- **AI tooling never gets literal target values in saved commands.** Values that change per target are elements, so one command works on every target.
## Ideas that were planned but not built
### Decisions waiting for the owner
- Ed25519 signed releases (closes SA-16).
- A passphrase instead of a 6 digit PIN.
- Saving a note under an existing name overwrites it silently.
- Bring back single note export.
- Default chain script policy "Sandboxed only".
- Excel safe CSV export (SA-37).
### Notes and editor
- Multi select with bulk move, tag and pin, and saved filter presets.
- An explicit note to target link, and `[[` note linking while typing.
- Hash type identification with a hashcat mode hint, a CVSS 4.0 calculator, and "Add hosts to Targets" from an nmap table.
### Reporting and workflow
- Compare report versions, findings with ATT&CK, EPSS and bulk status, clickable links in Linux PDFs.
- Engagement workspaces, a scope guard in the terminal, a loot and credentials view, an operator activity log.
- Scanner imports, and a migration wizard from the original LOYA Note.
### Engineering
- GitHub Actions on Windows and Linux, a release check in CI, a headless Xvfb smoke test.
- A hash chain for the audit log, target credentials in their own table, a PIN prompt on the remaining plaintext exports, a Windows sandbox for chain scripts.
- Reduce motion, UI zoom, SQLite FTS5 search.
## Known gaps
- HiDPI and multi monitor setups were never tested on real hardware.
- The Windows checklists in `Cores/storage_migration_plan.md` (section 9) and for the updater were not run end to end, and SA-23 and SA-39 still need a Windows confirmation.
- No real AI provider call is covered by tests; they use a fake provider.
- The floating terminal window (S16b) is not done, and the AI terminal tools over MCP (S24) are off by default.
- Open terminal issues: `clear` does not clear the panel, a superseded job can stay "running", only the first line of a multi line command is stored, and Ctrl+C with a nested identical prompt ends the outer job.
- A replace restore brings back `settings.json` including its security block, and restore is not atomic.
- There is no CI yet, and releases are not signed.
