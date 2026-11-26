# Working on LOYA NG
How to set up, change, test and ship the code. Read [ARCHITECTURE.md](ARCHITECTURE.md) first so the folder names below mean something.
## Setup
1. Install Python 3.10 or newer. On Windows you also need the Edge WebView2 Runtime. On Linux install the WebKitGTK bindings listed in the root [README](../README.md#requirements).
2. Clone `https://github.com/emaldos/LOYA.git` and run `python RunNote.py` (`python3` on Linux). The first run builds `.venv_windows` or `.venv_linux` and installs the pinned packages from `Requirements.json`.
3. Optional: build the offline CVE index with `python tools/build_cve_index.py --install-seed`. It is not in git; releases carry it.
4. Install Node.js if you want to run the browser side tests.
Your data goes to `Data/`, `Logs/` and `Backups/` next to the code. They are git ignored and must never be committed. Use `python RunNote.py --recovery` to restore a backup or open logs when startup fails, and `python resetPIN.py` for a forgotten PIN.
## Running the tests
```bash
python -m unittest discover -s tests -p "test_*.py"
node tests/js/run.js
```
- Always run Python tests through discovery, even for one file: `python -m unittest discover -s tests -p "test_flow_nodes.py"`. `python -m unittest tests.test_x` breaks the `_isolate` import that keeps tests away from your real `Data/`.
- On Windows use `.venv_windows\Scripts\python.exe`, on Linux `.venv_linux/bin/python3`.
- Each file in `tests/js/` is its own runner; `run.js` is the main one and the gate runs all of them.
- POSIX only terminal tests live in `tests/test_posix_pty.py` and skip on Windows. Run them on Linux or in WSL, from a copy inside the WSL filesystem, never from `/mnt/...` (both installs would share one `Data/`).
- The full Python suite takes about 8 minutes.
### Tests that already fail on Windows
On the Windows machine used for 1.0.1, about 55 tests failed before any 1.0.1 change and still fail after it. They are environment problems, not regressions, but nobody has gone through them yet, so check this list before you assume you broke something. Areas: backup and restore with PIN (`test_backup_restore_pin_audit`, `test_chain_backup`, `test_storage_encryption`, `test_crypto_store`), flows and chain scripts (`test_flow_engine`, `test_flow_scripts`, `test_flow_service`, one in `test_flow_nodes`), external agents and connections (`test_ext_agents`, `test_ext_connections`, `test_ext_cli_launch`), Unicode PDF export (`test_reports_export`), the CVE build tool (`test_cve_index`), `test_mini_window`, one updater staging test and the native nav guard test (`test_security_audit` `NavGuardNativeTests.test_allowed`, which rejects the Windows `file://D%3A/...` URL form). In `tests/js`, one `notes_pro.js` check (image `file:` URLs) fails too.
## Before every commit
Run `.claude/skills/ng-quality-gate/scripts/gate.sh`. It runs both suites, lists line ending churn, checks the version files and refuses to stage `Data/`, `Logs/`, `Backups/`, `.env` or key shaped secrets.
- Stage files by name. Never `git add -A`.
- The repository is LF. Git for Windows usually has `core.autocrlf=true`, so files edited on Windows can show whole file diffs with no real change. Never commit a file whose only change is CRLF churn; `LICENSE` is a known offender.
- Keep `CurrentVersion.info`, `CurentVersion.info` and `DEFAULT_APP_VERSION` at the version in development (1.0.1). Change them only for a release.
- Add a regression test for every fix: Python in `tests/`, browser side logic in `tests/js/`.
## House rules
- **Both platforms.** Every change must work on Windows and Linux. Gate platform code (`os.name`, `_IS_WINDOWS`, `_IS_LINUX`) and leave the other platform's behaviour unchanged.
- **Compressed code style.** The existing code has no blank lines, few comments and one line CSS rules. Match it in the lines you touch, keep names full and readable.
- **Local assets only.** No CDN scripts, fonts or icons. Vendored libraries live in `UI/vendor/` (see `UI/vendor/xterm/VENDOR.md`), icons under `Assets/`.
- **Separate files.** HTML in `UI/pages/` and `UI/windows/`, CSS in `UI/css/`, JS in `UI/js/`, Python in `Cores/`. No inline `<script>`, `<style>` or `style=`.
- **All JS to Python calls go through `bridgeCall`.** Never touch `window.pywebview.api` directly.
- **Errors are `ValueError("message the user can read")`.** The UI shows `err.message` in a toast.
- **Settings writes hold `Cores/settings_lock.SETTINGS_LOCK`** and go through `settings_lock.update_json` or `write_json`. Some older services still use their own lock or a fixed temp name; do not copy that.
- **Generated files are never hand edited:** `UI/css/theme.css`, `UI/js/theme-tokens.json`, `UI/js/appearance-boot.js` (written at every start from `Cores/Theme/`) and `UI/js/components/flow-catalog.js` (from `tools/gen_flow_catalog.py`).
## Recipes
### Add a bridge method
1. Put the logic in a function in the right `Cores/Services/*_service.py`.
2. Add a thin method to the matching class in `Cores/Bridge/api.py` or `Cores/Bridge/*_api.py`. JS calls it as `bridgeCall("namespace.method",[args])`.
3. Every bridge method is refused while the app is locked. If it must work on the lock screen, add it to `_LOCK_OPEN` in `api.py`, and expect the security audit tests to ask why.
4. Test the service function in `tests/`.
### Add a page
1. Create `UI/pages/x.html`, `UI/js/pages/x.js` with an `initX()` that fetches the fragment, sets `innerHTML` and wires events, and `UI/css/pages/x.css`.
2. In `UI/windows/main.html` add the stylesheet link, a `<section class="page" data-page="x">`, a `.nav-btn` with `data-page="x"` and the script tag before `app.js`. Script order matters because every file shares one global scope.
3. Add `x:initX` to `PAGE_LOADERS` in `UI/js/app.js`. Refresh data on the `loya:page-shown` event when `first` is false.
4. Prefix your globals (`x*`) so they cannot collide with `term*`, `notes*`, `rpg*`, `set*` and the rest.
### Add an MCP tool
1. Register it in `Cores/Bridge/mcp_server.py` or one of the `mcp_*_tools.py` files, guarded by the same `_check` permission call the neighbouring tools use.
2. Map it to a permission key in `Cores/Services/ai_service.py`.
3. Add it to [MCP-COVERAGE.md](MCP-COVERAGE.md) and update the tool total there and in the root README.
4. If AI agents should use it, mention it in the bundled skills under `AI Template/skills/`. A test checks that every tool a skill names exists.
### Change what AI agents are told
The rule for writing commands with `{Element}` placeholders lives once, in `Cores/Services/ai_element_rules.py`. The in app AI, the Claude Agent prompt, the MCP server instructions, the tool descriptions, the AI templates and the bundled skills all read it from there (skills through the `<!-- loya-element-rule -->` marker). Edit it there, not in the copies.
## Testing on a real desktop
- Use the `linux-ui-audit` skill on Linux: it launches the app under a harness, drives it with real input, screenshots it and queries the live DOM. `seed_demo.py` fills a throwaway data folder with fake demo data.
- Before a release, run the app on a real Windows machine and on a real Linux desktop (Kali XFCE on X11 is the tested one). WSL is not enough for window, notification or elevation behaviour.
## Releasing
The full checklist is in the root [README](../README.md#reference) under "Release publishing". In short: set the version, commit and push, tag `vX.Y.Z`, build `LOYA-NG-vX.Y.Z.zip` with `git archive`, add the CVE index with `tools/build_cve_index.py --add-to-package`, then publish a GitHub release (not a draft, not a pre-release) with the zip and the `cve-index-YYYYMMDD.sqlite.xz` asset. The updater only installs a package whose SHA-256 matches the release and whose `CurrentVersion.info` equals the tag.
## Tools in this repository
| Path | What it is |
|---|---|
| `.claude/skills/ng-quality-gate/` | Pre commit gate script and rules |
| `.claude/skills/linux-ui-audit/` | Linux UI harness, demo data seeder and WebKitGTK pitfall list |
| `.claude/skills/port-from-original/` | Procedure for comparing a feature with the original LOYA Note |
| `AI Template/skills/` | Skills LOYA installs into the user's Claude Code or Codex when they connect it |
| `tools/build_cve_index.py` | Builds the offline CVE index for releases |
| `tools/gen_flow_catalog.py` | Regenerates `flow-catalog.js` from `flow_nodes.py` |
