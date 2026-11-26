# Architecture
LOYA NG is a Python desktop app. The UI is plain HTML, CSS and JS rendered in a native window by pywebview (WebView2 on Windows, WebKitGTK on Linux). Python owns all data and logic; the page talks to it only through a bridge object. There is no web server for the UI, no bundler and no JS framework. Subsystem internals (storage, security, updater, terminal, chains, AI, reporting, CVE) are in [SUBSYSTEMS.md](SUBSYSTEMS.md).
## The big picture
```text
RunNote.py (system Python)            launcher: venv, deps, health check, recovery, pid file
   |
   +--> LOYA_Note.py (venv Python)    app process: crash logging, health check, lock state, windows
          |
          +--> Cores/Bridge/api.py    Api object bound to the window: one namespace per feature
          |       |
          |       +--> Cores/Services/*      feature logic
          |       +--> Cores/*.py            storage core: common_db, db_driver, crypto_store, doc_store
          |
          +--> UI/windows/main.html   shell page: titlebar, nav, panels, page sections
                  |
                  +--> UI/js/bridge.js       bridgeCall("namespace.method",[args]) returns a Promise
          +--> MCP server (127.0.0.1:8765)   same services, exposed to AI clients behind AI Roles
```
## Startup
### `RunNote.py`, the launcher
It runs with whatever Python the user starts it with, and its job is to get a healthy environment and then step aside. `main()` does, in order:
1. Parses `--skip-update`, `--verbose`, `--recovery`, `--version` and `--help`.
2. Makes sure the update runtime files exist and syncs the installed version.
3. Opens `Logs/RunNote_YYYY-MM-DD.log` and prunes old logs (`log_retention_days`, default 30), then prints the banner.
4. Reads `Requirements.json` (pinned packages, plus `linux_extra` on Linux) and checks the Python version.
5. Runs `Cores/Update/health_check.run_health_check()`. If it reports errors, the recovery console opens (restore a backup, downgrade, logs, diagnostics, retry). This is the screen you see when a data file cannot be read.
6. Checks `Data/loya.pid` so a second launch does not start a second app, and removes stale pid files.
7. Installs an update that was downloaded in the background, if one is staged.
8. Creates or repairs `.venv_windows` or `.venv_linux` (Linux uses `--system-site-packages` for PyGObject, Windows hides the folder).
9. Upgrades pip and installs packages only when the fingerprint of the requirements differs from `Data/deps_state.json`. Optional package groups are never installed here.
10. Checks the web engine: the WebView2 registry key on Windows, `gi.require_version("WebKit2", ...)` on Linux.
11. Starts `LOYA_Note.py` with the venv Python (`pythonw.exe` detached on Windows; on Linux with the WebKit rendering variables set), sends its output to `Logs/app_output.log`, writes the pid file and exits.
### `LOYA_Note.py`, the app
1. Installs crash logging: uncaught exceptions to `Logs/Note_log.log`, faulthandler to `Logs/crash.log`.
2. Runs the health check again; a fatal report reopens `RunNote.py --recovery`.
3. `security_service.sync_lock_state()`: hardens the permissions of `Data/`, `Logs/` and `Backups/`, finishes or rolls back an interrupted storage migration, and locks the bridge if a PIN or encryption is set.
4. Starts the MCP server if a CLI is connected (`ext_connections_service.autostart()`).
5. `Cores/Bridge/api.create_main_window()` regenerates the theme files, restores the window geometry and binds the `Api` object, then `webview.start()`.
6. After the window shows: the GTK overwrite confirmation patch, auto backup, audit log pruning and the `loya-scheduler` thread, which ticks every 600 seconds for backups, report reminders, update checks and background update downloads.
7. A launch only counts as good when the UI calls `update.launch_ready`. The updater relies on this to roll back a broken release.
8. On close: window geometry is saved, terminal sessions are closed, the MCP server stops, the encrypted database is checkpointed and the session key is wiped.
## Windows
- `create_main_window()` and `create_mini_window()` in `Cores/Bridge/api.py` are the only two `webview.create_window` calls. Both windows are frameless; the titlebar, dragging and resizing are done in JS through `WindowAPI`.
- The Mini Window is created on demand by `window.shrink()` and gets a smaller API (`MiniApi`).
- Navigation is locked to the app's own files twice: `UI/js/components/nav-guard.js` blocks link clicks, form submits and drops in the page, and `_install_nav_guard` cancels any navigation outside `UI/` at the engine level.
- Platform specific code is gated with `_IS_LINUX` and friends: rounded corners (DWM on Windows, a transparent window only when a Linux compositor runs), GTK main thread dispatch, the Linux work area, and file dialog behaviour.
## The bridge
- `class Api` in `Cores/Bridge/api.py` has one attribute per namespace: `window`, `theme`, `dashboard`, `notes`, `commands`, `playbooks`, `targets`, `search`, `security`, `backup`, `recycleBin`, `notifications`, `onboarding`, `focusMode`, `tags`, `importExport`, `templates`, `update`, `terminal`, `ai`, `reports`, `evidence`, `reportsIO`, `reportAI`, `extAgents`, `cve`, `wsl`, `flows`, `chainHistory`. Bigger namespaces live in their own `Cores/Bridge/*_api.py` file.
- Namespaces are camelCase, methods snake_case. JS calls `bridgeCall("terminal.get_settings")` or `bridgeCall("notes.save",[payload])`.
- Bridge methods are thin. They validate input and call a service function.
- Errors are raised as `ValueError("text for the user")`. The JS promise rejects and the caller shows `err.message` in a toast.
- **Lock guard.** Every public method is wrapped so it raises while the app is locked, except the ones listed in `_LOCK_OPEN` and `_LOCK_OPEN_TOP` (window, theme, unlock, a few terminal and update calls). A new method is locked by default.
- **Threads.** pywebview runs every bridge call on its own thread, so shared state needs locks. All `settings.json` writes go through `Cores/settings_lock.py` under one process wide `SETTINGS_LOCK`. Long work (AI streams, terminal sessions, chain runs, model downloads) runs on daemon threads and the UI polls it by id.
- **Python to JS** is mostly polling (`terminal.poll` adapts between 60 and 500 ms, AI streams, update progress, the Mini window's data signature). Direct pushes through `evaluate_js` exist in a few places only, for example `mcp_app_tools.notify_ui`, which tells the page that an AI changed data.
- Never touch GTK windows from window event handlers. Use `_run_on_gtk_main` or a short timer; reading geometry or destroying a window inside those callbacks deadlocks.
## The UI
- `UI/windows/main.html` is the whole shell: titlebar, AI panel, `#workArea` with one empty `<section class="page" data-page="...">` per page, the terminal panel, the bottom nav, lock screen and command palette.
- Pages load lazily. `goToPage(key)` in `UI/js/app.js` calls the page's loader from `PAGE_LOADERS` once (`initNotes`, `initChains`, ...), which fetches `UI/pages/<page>.html` into its section, then fires `loya:page-shown` with `{page, first}` every time the page is shown.
- `UI/js/components/` holds shared pieces: `toast.js` (`showToast`), `context-menu.js` (`openContextMenu`), `modal.js`, `confirm-dialog.js`, `ui-select.js`, `panel-dock.js` (docking the Terminal and AI panels left, right or bottom), `palette.js`, `lock-screen.js`, `titlebar.js`, `resize.js`, plus the terminal and AI panels.
- `UI/js/pages/` holds page logic. Big pages split their helpers into `*_core.js` files that load first.
- **One global scope.** Every script is a classic script tag, so load order in `main.html` matters (`bridge.js`, `nav-guard.js`, components, vendor, pages, `app.js` last) and globals carry an area prefix: `term*`, `ai*`, `notes*`, `rpg*` (reporting), `set*` (settings), `dash*`, `cve*`, `chh*`, `panelDock*`, `mini*`. Python reads `notesState` and `rpgS` by name, so do not rename them.
- Custom events tie pages together: `loya:page-shown`, `loya:live-target-changed`, `loya:target-keys-changed`, `loya:chains-changed`, `loya:chain-rendered`, `loya:ai-data-changed`.
- **Themes.** `Cores/Theme/tokens.py` and `palettes.py` generate `UI/css/theme.css`, `UI/js/theme-tokens.json` and `UI/js/appearance-boot.js` at every start. Themes are `data-theme` (dark, light, royal, system) and `data-style` (glass or classic) on the root element. Page CSS lives in `UI/css/pages/`.
- The page never gets real file paths. Dropped or picked files are staged through `importExport.stage_upload` (100 MB cap).
## Services
- Services in `Cores/Services/` are mostly module level functions with a few helper classes (`targets_service.Store` and the export classes). Each one owns one feature.
- Database access is always `with common_db.connection() as con:`, which commits, rolls back on error and closes. Connections go through `Cores/db_driver.py` so the same code works with plain SQLite and SQLCipher.
- Small JSON stores (targets, profiles, notes metadata, drafts, terminal sessions, AI sessions, search indexes) go through `Cores/doc_store.py`: plain files normally, rows in the encrypted database when encryption at rest is on. `settings.json` always stays a plain file.
- Each area logs to its own logger and file in `Logs/`.
| Area | Main files |
|---|---|
| Notes, commands, targets | `notes_service.py`, `commands_service.py`, `targets_service.py`, `search_service.py`, `semantic_search_service.py`, `quick_space_service.py`, `templates_service.py` |
| Settings, backups, notifications | `settings_service.py`, `dashboard_service.py` |
| Security | `security_service.py` |
| Terminal | `terminal_service.py`, `conpty.py`, `wsl_kali_service.py` |
| Chains | `playbooks_service.py`, `flow_service.py`, `flow_engine.py`, `flow_nodes.py`, `flow_rules.py`, `flow_schema.py`, `flow_scripts.py`, `flow_store.py`, `flow_demos.py`, `chain_history.py` |
| AI | `ai_service.py`, `ai_chat_service.py`, `ai_sessions_service.py`, `ai_index_service.py`, `ai_element_rules.py`, `mcp_local_service.py` |
| External agents | `ext_agents_service.py`, `ext_agent_claude_runner.py`, `ext_connections_service.py`, `ext_cli_launch.py` |
| Reporting | `reports_service.py`, `report_export*.py`, `report_pdf_*.py`, `report_xlsx.py`, `report_design.py`, `report_templates.py`, `report_sections.py`, `report_import.py`, `report_autogen.py`, `report_schedule.py`, `report_ai.py`, `evidence_service.py`, `report_service.py` |
| CVE Intel | `cve_service.py`, `cve_index.py`, `cve_index_updater.py`, `cve_guidance.py`, `cvss.py` |
## Settings and feature switches
- Everything lives in `Data/settings.json`, created with defaults by the health check. Sections include `window`, `security`, `backup`, `update`, `dashboard`, `targets` and `extensions`.
- Extensions are switched on in `extensions`: `terminal_enabled` (off by default, so the Terminal button stays hidden until it is enabled in Settings > Extensions) and `ai_enabled` (on by default), plus their panel size, dock side and behaviour keys.
- Every setter does read, modify and write under `SETTINGS_LOCK` and returns the fresh settings. The Settings page calls the setter, then a refresh function such as `termRefreshEnabled()` so the rest of the UI updates without a restart.
## Files you should never edit by hand
- `UI/css/theme.css`, `UI/js/theme-tokens.json`, `UI/js/appearance-boot.js`: rewritten from `Cores/Theme/` at every start.
- `UI/js/components/flow-catalog.js`: generated from `Cores/Services/flow_nodes.py` by `tools/gen_flow_catalog.py`.
- `UI/vendor/`: vendored third party code with its own `VENDOR.md`.
## Runtime folders
- `Data/`: database, key file, settings, JSON stores, attachments, external agent workspaces, CVE index. Hardened to the current user at every start.
- `Logs/`: launcher, app, crash, update and per feature logs.
- `Backups/`: data backups, always encrypted `.loyabak` (PIN-wrapped data key with encryption at rest on, else a backup password kept only in the OS keyring when remembered). Older plain zips still restore.
- `Cores/Update/OldVersions/` and `Cores/Update/state.json`: code snapshots and updater state.
None of these are in git. The root [README](../README.md#reference) lists every runtime path.
