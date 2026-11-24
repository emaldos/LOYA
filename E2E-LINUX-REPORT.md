# LOYA NG - final end-to-end test on Linux

Date: 2026-11-24. Kali, WebKitGTK 2.52. Branch `s30b-linux-verification`, version **1.0.0 (not bumped)**. Nothing committed.

## Summary

The whole app was toured on Linux, area by area, by seven parallel testers. Each had its own copy of the app, fresh demo data (targets, notes, commands, 3 demo reports, the offline CVE index) and its own virtual screen (`:141`-`:147`). Your real `Data/` and `Backups/` and your own app on `:0` were not touched. The main pass used dark Glass, with spot checks in light, royal and Classic. Real mouse and keyboard input (xdotool) was used wherever focus, typing, hover or drag matters.

**Result: every area works.** We found and fixed **40 small bugs** (each with a test), mostly in Notes, Commands/Chains, Settings and the title bar. **Nothing blocks the release**, but one issue is serious and should be looked at first: in Kali's default **zsh**, the built-in terminal shows garbled output and loses output. bash and PowerShell are fine. The other open issues are medium or low.

One test-tooling problem was found and fixed. The audit harness was meant to copy JavaScript console errors into `app.log`, but on this WebKitGTK it **captured nothing**. The harness now has its own in-page error collector (see "Harness fix"). With it, the tour of every page, every Settings tab and the main modals produced **zero JavaScript errors**.

## Per-area results

| # | Area | Result | Notes |
|---|------|--------|-------|
| 1 | Dashboard: cards, live-target picker, edit layout | **PASS** | 15 cards; the picker search and switching work. Edit Layout works by menu and keyboard. Mouse drag of cards could not be tested under the virtual screen (see open issue 11). |
| 2 | Notes: sidebar, search, drag to group/pin | **PASS** | Real drag to a group and to Pinned works. |
| 2 | Notes: pro editor, More, bubble, right-click, pentest tools, Markdown, auto-pairs | **PASS** (after 10 fixes) | Encode, hash (matches md5sum), JWT, CVSS 9.8, nmap→table, ATT&CK and evidence all work. |
| 2 | Notes: attachments, save and reopen | **PARTIAL** | Adding and saving attachments work, and content is byte-identical after a restart. **File attachments cannot be opened or downloaded** (open issue 2). |
| 3 | Reporting: template, sections, findings, rich editor | **PASS** (after fix) | The editor used to store the dark theme's text colour, which made text invisible in exports. Fixed. |
| 3 | Reporting: CVE picker (offline) and manual CVE | **PASS** | |
| 3 | Reporting: linked targets as scope, affected targets | **PASS** | |
| 3 | Reporting: evidence, timeline, reminders, undo/redo, Alt+A, Alt+1-6 | **PASS** | |
| 3 | Reporting: preview, export of all 8 formats, JSON/CSV import | **PASS** (after fix) | All 8 export files validated (PDF has 19 pages). The CSV import split linked targets in two; fixed. |
| 3 | Reporting: list with many cards (36) | **PASS** | |
| 4 | Commands: search, add/edit, run | **PASS** (after 4 fixes) | |
| 5 | Chains: list, linear, template diagram | **PASS** (after fixes) | |
| 5 | Chains: ping → alive/down → nmap / script | **PASS** | 127.0.0.1 took the alive branch (nmap); 192.0.2.1 took the down branch (script). |
| 5 | Chains: dry run, confirmation, live log and viewer, Mark as reviewed | **PASS** | |
| 5 | Chains: `/caller` from terminal and from the AI panel | **PASS** (after fix) | A diagram run from the terminal leaves no result in the terminal (open issue 6). |
| 6 | Terminal: docks right, drag-to-dock, splits, saved sessions | **PASS** (after fix) | |
| 6 | Terminal: suggestions, "⋯" overflow menu | **PASS** | |
| 6 | Terminal: PowerShell option, elevation text | **PASS** | pwsh **is** installed here (`/usr/bin/pwsh`), so only unit tests cover the missing-pwsh case. The prompt reads `[sudo] password for ...`; nothing was elevated. |
| 6 | Terminal: recording, save for report | **PASS** | Both appear under Reporting → Evidence. |
| 6 | Terminal output under zsh | **FAIL** | Garbled under Kali's default zsh plugins (open issue 1). |
| 7 | CVE Intel: offline search, detail card, News with lookups off, settings | **PASS** (after fix) | The index (430,863 CVEs) installed into the copy's Data. No network sockets during the tour. |
| 8 | Targets: toolbar, table, Set live, Add/Edit form, Set Elements | **PASS** (after 2 fixes) | |
| 9 | Quick Run, Mini window, Ctrl+K, Ctrl+/ | **PASS** (after 4 fixes) | Alt+F4 on the Mini window quits the whole app; no hidden window is left. |
| 10 | Settings: every tab, Appearance and persistence | **PASS** | |
| 10 | Settings: PIN, encryption at rest, lock/unlock, wrong PIN, turning the lock off | **PASS** (after 2 fixes) | The DB really becomes SQLCipher, and no plaintext is left in Data/. |
| 10 | Settings: backups, encrypted `.loyabak` restore | **PASS** (after 2 fixes) | Restoring an old backup silently reverts the PIN (open issue 3). |
| 10 | Settings: AI Roles, External Agents up to consent | **PASS** | No keys were entered. |
| 10 | Settings: Terminal Shells, Kali WSL card | **PASS** | The WSL card is hidden on Linux. |
| 10 | Settings: script policy, update settings, import/export | **PASS / PARTIAL** | There is no settings-only import/export; settings travel inside Export All / Import All, which works. |
| 11 | Title bar: badge card (2 columns, search), update bell | **PASS** (after 2 fixes) | |
| 12 | Navigation guard: external link | **PASS** | Nothing opens inside the window. The link opens the system browser (open issue 12). |
| 12 | Remote images blocked in notes | **PASS** | A "click to load" placeholder shows, and `naturalWidth` is 0. |
| 12 | No JS console errors | **PASS** | Checked with the in-page collector (0 errors). `app.log` itself was unusable; see Harness fix. |
| 12 | Resize, maximize, rounded corners | **PASS** | Corners are rounded only when the window manager's compositor is on, as designed. |
| 12 | Ghost repaint artifacts | **PASS** | Pixel diff was 0 after page switches, resizes and modals. |
| 12 | Bottom dock at 1400 and 800 px | **PASS** | All 11 items reachable at 800 px (icons only). |

## Bugs fixed (all minimal edits, each with a test, each verified live)

**Title bar, dashboard, cross-cutting**
- `UI/css/layout.css:11-13`: at narrow widths (≤1100 px) the centred search box covered the live-target badge and the bell. Test: `tests/js/titlebar_layout.js` (new).
- `UI/js/components/toast.js`: the bell popover ignored Escape, and a second click closed and reopened it. Test: `tests/js/toast_history.js` (new).
- `Cores/Bridge/api.py` (`_TooltipClickGate`, about lines 2111-2180): GTK showed a button's stale tooltip on top of the popover the click had just opened. Tooltips are now suppressed after a click until the mouse moves. Test: `tests/test_tooltip_click_gate.py` (new).
- `UI/js/components/live-target-badge.js`, `toast.js`, `pages/dashboard.js`: the badge, bell and picker drop their tooltip while their popover is open. Tests: `live_target_badge.js`, `toast_history.js`, `dashboard_cards.js`.

**Notes**
- `UI/js/pages/notes.js` (`notesLiftListFromP`/`notesFixListInP`) and `notes_pro.js:292`: WebKit produced `<p><ul>` lists, so a later code block swallowed the list.
- `notes.js` (`notesFontSpanFor`): each A+/A- click nested one more font-size span.
- `notes.js`: the note-link search box was not focused.
- `notes.js` (`notesExec`): the divider was saved as `<hr id="null">`.
- `notes_pro.js:226`: inserting a finding or table jumped the editor to the top.
- `notes_editor.js:1211`: an ATT&CK tag carried over to the next line and nested inside the previous tag.
- `UI/css/pages/notes.css`:
  - the Copy chip drew above popovers;
  - the draft banner pushed the page 61 px off screen;
  - long JWTs and hashes made the viewer scroll sideways;
  - the viewer header was crushed when the AI panel was docked.
- Tests: `tests/js/notes.js`, `notes_pro.js`, `notes_editor_actions.js`.

**Reporting**
- `UI/js/pages/reporting_widgets.js`: merging blocks stored the theme's text colour, which made text invisible in PDF/HTML. Test: `tests/js/reporting_widgets_style.js` (new).
- `Cores/Services/report_import.py:343,424`: the CSV import split a linked target at the comma inside its brackets. Test: `tests/test_reports_import.py`.

**Commands, Chains, AI**
- `Cores/Services/commands_service.py:467`: "Tittle" → "Title".
- `UI/js/pages/commands.js:516`: a new command defaulted OPSEC to "Stealthy"; it is now "Normal".
- `commands.js:374`: typing `{IPv4}` gave `{IPv4}}`.
- `UI/css/pages/notes.css:199`: the shell pill wrapped onto two lines.
- Test for the four items above: `tests/test_commands_page.py`.
- `UI/css/flow-panels.css:291`: the diagram name collapsed to zero width when the "Unsaved" badge appeared. Test: `tests/js/flow_panels.js`.
- `UI/css/components.css:115`: confirm-dialog body text was larger than the dialog title.
- `UI/css/pages/chains.css`: with panels docked, the toolbar pushed "New Action Chain" off screen.
- Test for the two items above: `tests/js/chains_page.js`.
- `UI/js/components/ai.js:908`: the AI panel said "Running chain" even when the run was cancelled. Test: `tests/js/ai_complete.js`.
- `UI/js/components/ui-select.js`:
  - Escape closed the dialog underneath instead of the dropdown;
  - dropdown lists were clipped to the trigger's width.
- Test for both: `tests/js/ui_select_width.js` (new).

**Terminal, Quick Run, palette, shortcuts**
- `UI/js/components/terminal.js` (`termOpenPopover`): the split picker spilled off the right edge of the window.
- `terminal.js` (`termEnsureActiveSession`): Quick Run "Run" sent the command to a hidden terminal.
- Test for both: `tests/js/terminal_shells.js`.
- `UI/js/components/palette.js:98`: the empty-state text was wrong.
- `UI/js/components/shortcuts.js`: Ctrl+Shift+Enter (maximize the terminal) was missing from the Ctrl+/ sheet.
- Test for both: `tests/js/shortcuts_sheet.js`.
- `UI/pages/settings.html:191,232`: the Terminal card said "CMD/PowerShell" on Linux, and the AI card said "Chat wiring is not yet available". Test: `tests/test_terminal_shells.py`.

**CVE Intel, Targets**
- `UI/js/pages/cve.js:251,296` and `cve_core.js:236`: "| General vulnerability guidance" and "added - | ransomware use: Unknown". Test: `tests/js/cve_core.js`.
- `UI/js/pages/targets.js:293`: Ctrl+S in the target form did nothing after clicking a label.
- `targets.js:496,583`: "used in 3 commands" counted note blocks as commands.
- Test for both: `tests/js/targets_page.js`.

**Settings, security, backups**
- `UI/js/pages/settings.js:94`: the PIN prompt ignored Enter and Escape. Test: `tests/js/settings_backup_pin.js`.
- `Cores/Services/dashboard_service.py:220`: with encryption on, the Dashboard showed "Targets 0". It now reads through the encrypted store. Test: `tests/test_dashboard_service.py`.
- `Cores/Update/backup_restore.py`:
  - restored files were 0664 on Linux; they are now 0600;
  - the `pre-encryption-*.loyabak` that the app itself points you to could not be restored.
- Tests for both: `tests/test_security_audit.py`.

**Harness fix (test tooling)**
- `.claude/skills/linux-ui-audit/scripts/harness.py`: WebKitGTK 2.52 ignores `set_enable_write_console_messages_to_stdout`. Even a deliberate `console.error`, a thrown error, or 200 `console.log` lines never reached `app.log`, so "no errors in app.log" proved nothing.
- The harness now installs an in-page collector (`window.onerror`, `unhandledrejection`, `console.error`/`warn`) about once a second. It survives reloads and writes `[js-error] [window] ...` lines to `app.log`. This was verified with a probe error, a probe rejection and a reload. Errors raised before the first drain after a load, and `console.log`, are not captured.
- `.claude/skills/linux-ui-audit/SKILL.md` now explains this.

## Fixed after E2E (2026-11-24, second round)

Each fix was made in four parallel areas, has tests, and was checked live in a sandbox copy on its own Xvfb display (`:161`-`:164`). The real `Data/` and `Backups/` and `:0` were not touched. Nothing committed; version still 1.0.0.

1. **Fixed (High): terminal output garbled under Kali's default zsh** (`UI/js/components/terminal.js`).
   - zsh echoes the typed line and then repaints it in colour using cursor moves; in narrow panes it wraps with ` \r ESC[K`.
   - New `termEmulateLine` replays an echoed line on a grid the width of the pane (backspace, cursor moves, erase, wide characters, wrap). It keeps the shell's colours. `termCleanPosixLine` cuts the hidden marker off by position, not by matching the echo.
   - Used for POSIX shells only; what cmd and PowerShell send is unchanged, byte for byte (tested).
   - The `ls` widget parses only the command's own output, without colour codes, and no longer swallows the next prompt.
   - `Cores/Services/terminal_service.py` `plain_terminal_text`/`peek_plain`: the AI's `terminal_read` (`Cores/Bridge/mcp_server.py`) now gets screen-like text with no escape codes or markers.
   - Tests: raw recordings in `tests/fixtures/terminal/` (skel zsh at 120 and 40 columns, bash, plus a recorder script; user and home are anonymised), `tests/js/terminal_shell_echo.js` (108 checks, fails on the old code) and `tests/test_terminal_shell_echo.py`.
   - Live with real typing: prompts, job blocks, exit codes, suggestions, Ctrl+C, multi-line, wrapping, `clear`. Regression checks in bash and pwsh. A read-only copy of the owner's `~/.zshrc` passed in replay; it was not checked live in the app.
2. **Fixed (Medium): Notes file attachments can be opened and saved.**
   - `Cores/Services/notes_service.py` `resolve_attachment_file`: the UI sends only an attachment id (8-32 hex). It resolves to a regular, non-symlinked file directly under `Data/Attachments/<note>/`; traversal and absolute paths are rejected.
   - "Open" decrypts the AES-GCM stream when encryption is on, into a private temp copy (folder 0700, file 0600), and opens it with `os.startfile` on Windows or xdg-open on Linux. Copies are deleted on lock, at exit and at the next start. File types the desktop would run (`.desktop`, `.exe`, `.sh`, `.ps1` ...) are save-only.
   - "Save as..." uses the native save dialog and decrypts straight into the chosen file (atomic write).
   - Both are refused while locked. Audit events `attachment_open` and `attachment_save` are written, including refusals.
   - Bridge: `NotesAPI.attachment_open` and `attachment_save_as` in `Cores/Bridge/api.py`.
   - UI (`UI/js/pages/notes.js`, `notes.css`): in the viewer, a click opens and a right-click, the Menu key or Shift+F10 shows Open / Save as.... In the editor, a double-click opens and a right-click shows the same menu.
   - Tests: `tests/test_notes_attachment_open.py` (16) and `tests/js/notes_attachment_chips.js` (14).
3. **Fixed (Medium): restoring an older backup no longer silently brings back its PIN** (`Cores/Update/backup_restore.py` `restore_data_backup(current_pin=...)`, `UI/js/pages/settings.js` `setBackupPin`).
   - Same data key (for example the PIN was changed after the backup): the live key file is kept, so the current PIN stays.
   - Different key: the app asks for the backup's PIN and then the current PIN, checks both before writing anything, and re-wraps the restored key under the current PIN.
   - "Skip" shows the warning "This backup uses the PIN that was set when it was made. After restore, unlock with that PIN."
   - A wrong PIN changes nothing, and the refusal is audited.
   - Tests: `tests/test_backup_restore_pin_audit.py` and `tests/js/settings_backup_pin.js`.
4. **Fixed (Medium): a job now finishes after a shell syntax error** (`terminal.js` `termCheckPromptReturn`, `termPosixLineState`).
   - When the prompt returns after a shell error line, the job closes with the shell's status (zsh 1, bash/sh 2). After Ctrl+C it closes with 130.
   - An unclosed quote, `$(` or trailing `\` continues the job on the next line.
   - Also fixed: a trailing `# comment` used to swallow the end marker, and a trailing `&` or `;` made the marker a syntax error.
5. **Fixed (Medium): the audit log is append-only across restores** (`Cores/Services/security_service.py` `merge_audit_file`, `merge_audit_rows`).
   - The live `security_audit.jsonl` is kept and merged with the backup's entries, without duplicates (0600, atomic).
   - The live encrypted `AuditEvents` rows are copied into the restored DB.
   - A `backup_restored` event is added after the merge.
6. **Fixed (Medium UX):**
   - A diagram chain run by `/caller` from the terminal now prints a display-only summary when it ends (`UI/js/pages/chains_flow.js` `chainsFlowReportToTerminal`, `terminal.js` `termPrintNotice`): the status line, `Path: Ping [ok] → Alive? [alive] → nmap`, and an "Open logs: Chains page > ... > History" hint.
   - Long status pills wrap to at most 520 px, carry the full text as a tooltip, and stay on screen longer (`UI/css/components.css`, `status-island.js`).
   - The Commands table fits at 1280 px (`UI/css/pages/commands.css`). The command column flexes, and container queries hide Sub Category, Description, Category and Tags as room shrinks. Run is always visible.
   - With the terminal docked, the diagram editor switches to compact mode below 960 px (`chains_flow.js` `chainsFlowWatchSpace`, `flow-panels.css`): an icon-only palette, and the inspector as an overlay while a node is selected. The canvas went from 296 to 752 px. The diagram re-fits when the terminal opens or closes.
   - Tests: `tests/js/ux_fit_and_feedback.js` (39).
7. **Partly fixed (Low): stale GTK tooltips** (`Cores/Bridge/api.py` `_TooltipClickGate.hold`). Scrolling or typing also holds tooltips until the pointer moves. Tests: `tests/test_tooltip_click_gate.py` (+3).
8. **Test tooling:** `gate.sh` now flags `DEFAULT_APP_VERSION` only for real assignments in `.py` files (for example `DEFAULT_APP_VERSION="..."` or `_DEFAULT_APP_VERSION=...`), not README text.

Tests after this round:
- Python: 1822 tests, OK (1 skipped).
- JavaScript: every `tests/js/*.js` passes, including the new files; `run.js` 418/0.
- `import Cores.Bridge.api` works.
- `gate.sh`: **PASS**. The only note is the known `LICENSE` CRLF-only churn; do not commit it.

### Open issues after the fix round, most important first

1. **Medium-low (terminal):**
   - Submitting a new command while a job is still "running" leaves the old job running in the Jobs list.
   - The jobs DB keeps only the first line of a continued (multi-line) command.
   - `clear` does not clear the panel in any shell (Ctrl+L does).
   - Ctrl+C inside a nested shell or ssh session with an identical prompt closes the outer job early (130).
2. **Low (terminal):**
   - The exit code after a rejected line is the shell's usual status, not one read back from the shell.
   - A trailing `#` comment is dropped from what is sent, which only matters if zsh has interactive comments turned off.
3. **Low (restore):**
   - A replace restore still brings back the backup's `settings.json`, including the security block (app-lock and auto-lock options). The PIN itself is not affected.
   - Restore is not atomic.
   - The merged audit log also takes in a foreign backup's own entries.
   - A merge restore of a different-key backup copies attachments encrypted under the other key (this was already the case before).
4. **Low (attachments):**
   - Windows `os.startfile` is covered by unit tests only.
   - A call refused by the bridge lock guard leaves no audit entry (refusals in the service are audited).
   - Saved copies are 0600.
5. **Low:** native GTK tooltips can still go stale when an element's title changes with no input at all (an async re-render).
6. **Low:** on Xvfb with no compositor, a tooltip hidden on scroll can leave a black rectangle until the next repaint. Check this once on a real desktop.
7. **Unchanged from the E2E list below:**
   - 11: mouse drag of dashboard cards is unverified; check it by hand.
   - 12: external links open the real browser.
   - 13: the cosmetic list, except that the minimap overlap is eased by compact mode and the minimap has a toggle.

## Open issues found during E2E (items 1-9 fixed above; see the updated list there)

1. **High - the terminal is garbled under Kali's default zsh.**
   - Kali's `.zshrc` loads zsh-syntax-highlighting and autosuggestions. These redraw the typed line, including the app's hidden job marker, with colour codes, so the marker pattern (`terminal.js` `TERM_JOB_ECHO_RE`, about line 282) never matches.
   - As a result, output goes missing, job blocks land in the middle of the prompt, and the `ls` widget shows escape-code garbage. bash and pwsh are fine.
   - Possible fixes: strip ANSI before matching, or start app-driven zsh sessions with these plugins off. This is a design choice.
2. **Medium - Notes file attachments cannot be opened or downloaded.** Click, double-click and right-click on the file chip do nothing, and there is no handler. This needs a bridge "open/save attachment" action that decrypts the file.
3. **Medium - restoring an older encrypted backup silently brings back the old PIN**, because the key file is restored with the database. You get no warning.
4. **Medium - a terminal job never finishes if the line has a shell syntax error.** The end marker never runs, so the job stays "running".
5. **Medium (design question) - a restore also rolls back `security_audit.jsonl`.** Audit entries written after the backup, including the restore itself, are lost.
6. **Medium (UX) - a diagram chain run by `/caller` from the terminal leaves nothing in the terminal.** You only get a 3-second pill and a bell entry. A linear chain shows a progress card.
7. **Medium (UX) - long status pill messages are cut off with no way to read them.** Example: "No AI provider is enabled - turn on ... External A...".
8. **Medium-low - at 1280×800 the Commands table is about 31 px too wide**, so the Run button is half hidden behind a sideways scroll.
9. **Medium-low - the diagram canvas is about 296 px wide when the terminal is docked.** It cannot fit a template diagram, and it does not re-fit when the terminal closes.
10. **Low - native GTK tooltips can still go stale** after an element's title changes or the element moves. Seen on the "Make this the live target" and "Edit target" buttons. The new click gate (fix above) cures the common case. Testers who ran before it landed still saw some, so this is worth a recheck with a real mouse.
11. **Low - mouse drag of dashboard cards in Edit Layout is unverified.** xdotool cannot drive GTK drag-and-drop under a virtual screen. Keyboard reordering works. **Check this by hand once.**
12. **Low - clicking an external link from a note starts your real browser with your profile.** This is by design, but be aware of it during tests.
13. **Low, cosmetic:**
    - empty date inputs on CVE News show a dimmed "today" date (WebKitGTK);
    - the "Renamed: Updated commands:1 notes:1 unlinked:1" toast is raw;
    - the offline-CVE "affected products" line lacks a separator;
    - the "Online lookups are off" banner is shown twice on CVE Lookup;
    - a white strip shows on the report preview cover;
    - the GTK date popover stays open after picking a day;
    - an imported report copy repeats its reminders;
    - after a reload with encryption on, the lock screen shows even though app lock is off;
    - backup filenames use UTC while the list uses local time, and the card says "ZIP" for `.loyabak` files;
    - Export All includes the 96 MB CVE index;
    - the PIN and restore popovers sit about 40 px right of centre;
    - the diagram minimap covers bottom-right nodes;
    - in narrow terminal panes, the job header shrinks the command to nothing;
    - the terminal's session tabs show a permanent scrollbar when narrow;
    - the selection bubble's colour tooltip mentions an arrow that does not exist;
    - attachment URLs use `file:////`;
    - notes saved before the list fix keep an empty `<p>`;
    - the palette's "Open Terminal" action toggles the panel;
    - pywebview logs a full traceback for expected validation errors.

## Tests and gate

- Python: `.venv_linux/bin/python3 -m unittest discover -s tests -p "test_*.py"` gives **1788 tests, OK** (1 skipped).
- JavaScript: all **45** `tests/js/*.js` files that require modules **pass** (`run.js`: 418 passed, 0 failed).
- `.venv_linux/bin/python3 -c "import Cores.Bridge.api"` works.
- `gate.sh` reported **FAIL**, but both reasons are pre-existing and neither is a version bump:
  - **`LICENSE` is CRLF-only churn.** Do not commit it.
  - **"DEFAULT_APP_VERSION changed" is a false positive.** The match is a line of release instructions in the uncommitted `README.md` edit that mentions `DEFAULT_APP_VERSION`. Both `CurrentVersion.info` files are unchanged (1.0.0), and `update_helpers.py` has no version change.
  - Nothing is staged, and no secrets were found.

## Screenshots and artefacts

Root folder: the session scratchpad `e2e/` folder (local only, not part of the repo)

- Screenshots, one folder per area:
  - `audit-A/shots`: dashboard, title bar, cross-cutting
  - `audit-B/shots`: notes
  - `audit-C/shots`: reporting
  - `audit-D/shots`: commands and chains
  - `audit-E/shots`: terminal, Quick Run, palette
  - `audit-F/shots`: CVE Intel and targets
  - `audit-G/shots`: settings
  - `audit-Z/shots`: the final collector sweep
- Exported report files: `audit-C/exports/`.
- One line per fix: `fixes.log`.
- These folders are temporary and may be cleared on reboot.

All sandbox apps, virtual screens (`:141`-`:147`, `:151`) and their window managers are stopped. Only your own app and window manager on `:0` are still running.
