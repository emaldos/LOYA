# LOYA NG - Linux UI/UX audit and fix log

**Date:** 2026-11-23 | **Branch:** `s30b-linux-verification` | **Version:** 1.0.0 (unchanged - not released yet)
**Machine:** Kali rolling, XFCE/xfwm4 on X11, VMware VM (vmwgfx, 3D on), 1920×1080, scale 1, WebKitGTK 2.52.5, pywebview 6.2.1

The app was run on the real desktop under an audit harness (now the `linux-ui-audit` skill), driven with real mouse/keyboard input, screenshotted, and its live DOM queried. Static audits of the frontend, the Python backend, the JS↔Python bridge wiring, and a gap analysis against the original [LOYA-Note](https://github.com/emaldos/LOYA-Note) (HEAD `bbbad0f`) ran in parallel. Every fix below keeps Windows behaviour unchanged unless stated, and platform-specific changes are gated.

Tests at the end of the session: see the commit message for the final counts (Python `unittest`, `tests/js/run.js`, and the standalone `tests/js/*.js` suites).

---

## 1. Linux-only rendering and UX bugs

| # | Symptom on Linux | Root cause | Fix | Verified |
|---|---|---|---|---|
| L1 | Glass cards (Add Note, Add Command, modals) were see-through and unreadable - page content showed through sharp | Launcher set `WEBKIT_DISABLE_DMABUF_RENDERER=1`, which forces WebKit's acceleration policy to **NEVER**; `backdrop-filter` is only drawn on composited layers | `RunNote._linux_app_env` now sets `WEBKIT_DMABUF_RENDERER_FORCE_SHM=1` instead (keeps compositing, avoids the blank-white DMA-BUF bug on VM GL). An explicit user setting of either variable is honoured | Probe page under 6 configs; live screenshots; idle CPU ~0% |
| L2 | The whole UI was text-selectable (drag highlights buttons, Ctrl+A selects the app) | WebKitGTK ignores unprefixed `user-select` | `-webkit-user-select` twin added to all 32 declarations; terminal output explicitly selectable | Real drag + Ctrl+A select nothing |
| L3 | Checkboxes were tiny white GTK squares; number spinners light-themed | Native controls with no `color-scheme` / `appearance` | Themed checkbox in `base.css`; `color-scheme` per theme | Screenshot, checked + unchecked |
| L4 | Buttons used a different font from body text; code text mixed two monospace faces | "Segoe UI"/Consolas don't exist; form controls use the GTK system font | `--font-ui` / `--font-mono` stacks with Linux fallbacks; `button,input,select,textarea{font-family:inherit}`; canvas fonts updated | Computed styles |
| L5 | App's own scrollbars never appeared (faint GTK overlay bars instead) | In WebKitGTK, `scrollbar-width/color` disables `::-webkit-scrollbar` | Standard props gated to Chromium via `html:not(.engine-webkit)` (class set in `bridge.js`) - Windows look unchanged | Screenshot |
| L6 | Terminal prompt lost its space: `└─$nmap` | Partial-job-marker hiding stripped any trailing prefix of `" ;printf '"` - a lone space - even with no job running | Only hide marker prefixes while a job is in flight (`termPendingVisible`) | Live prompt + 3 regression tests |
| L7 | Terminal status bar showed `home/kali/` for `/home/kali` | `direction:rtl` ellipsis trick flips a leading `/` | Wrapped in U+200E marks | Test |
| L8 | Ctrl+Shift+C in the terminal sent ^C (could kill a running scan); Ctrl+Shift+V did nothing | Shift not distinguished | Ctrl+Shift+C copies only; Ctrl+Shift+V pastes through the multi-line guard | Tests |
| L9 | Save dialogs silently overwrote files and didn't add extensions | GTK3 has overwrite confirmation off; no auto-extension | GTK dialogs get `set_do_overwrite_confirmation(True)`; extension appended; collision prompt | 45 tests |
| L10 | File dialogs opened in the app's install folder | No `directory=` passed; GTK falls back to CWD | Last-used folder remembered, default Documents (Linux) | Live: dialog opened in Documents |
| L11 | Import filters missed `BACKUP.ZIP`, `X.JSON` | GTK patterns are case-sensitive | Upper-case variants added (Linux) | Tests |
| L12 | A window maximized by xfwm4 (Alt+F10) couldn't be restored from the app | GTK `restore()` doesn't unmaximize | Native `unmaximize()` on the GTK loop first | Tests |
| L13 | Possible crash/hang on maximize | GDK work-area calls made off the GTK main thread | Marshalled to the main loop with timeout; xprop fallback | Tests |
| L14 | Mini window could deadlock on close; closing main left an invisible process | Reading window props inside `closing`; hidden mini kept the process alive | Geometry seeded/cached; mini destroyed with main; Mini ✕ quits cleanly | Tests |
| L15 | White flash at startup / during resize | No `background_color` | Theme background passed to both windows (Linux) | - |
| L16 | "Open logs" reported success when nothing opened | `Popen(xdg-open)` never checked | Exit status/timeout checked; error shown | Tests |
| L17 | Commands page "rows per page" reset every launch | `localStorage` doesn't exist (pywebview private mode on GTK) | Stored in settings.json via the bridge | 4 tests |
| L18 | A file dropped anywhere outside a drop zone could replace the app with that file | WebKit navigates to dropped files by default | Window-level guard for unhandled file drops | Code review |
| L19 | Intermittent stale "ghost" line: the old edge of a glass card stays painted (Settings tab switches; Commands/Quick Run as rows load; the outgoing page's cards after a page switch; the note editor modal after it opens) | Not CSS: Skia's **GPU** painter in WebKitGTK 2.52 with shared-memory frames (`WEBKIT_DMABUF_RENDERER_FORCE_SHM=1`, needed on VM GL) leaves stale tiles behind composited `backdrop-filter` layers; the stale strips stop at fixed tile boundaries. Skia's CPU painter does not | **FIXED.** `RunNote._linux_app_env` (and the harness `launch.sh`) now also sets `WEBKIT_SKIA_ENABLE_CPU_RENDERING=1` whenever SHM frames are forced (explicit values are honoured). Blur and glass look unchanged; Windows untouched. Page-switch ghosts (`ghost3.sh`, Dashboard→Commands/Quick Run): GPU painter 4/30 (2/10, 2/20) → CPU painter 0/60 (+0/10 Quick Run). `WEBKIT_SKIA_GPU_PAINTING_THREADS=0` alone: 4/30 (not the fix). Note-editor modal (`ghostm.sh`): 1 ghost seen by eye on GPU, 0/20 by detector; 0 real ghosts in 22 cycles on CPU. CPU cost: idle WebKitWebProcess ~0.9% (same as before); 10 page switches 2.5-3.6 s CPU either way. Earlier no-ops: keeping damage tracking on, removing the glass rim, opacity nudge, toggling blur on resize, translateZ kick. The fixed table-card heights stay | Pixel-diff detectors `ghost3.sh` / `ghostm.sh`, 10-30 cycles per variant; blur verified with a stripe pattern under a `backdrop-filter` box |

## 2. Cross-platform UI fixes and user-requested changes

- **Table header corners** didn't follow the rounded tables (`border-collapse:collapse` ignores cell radius) → `separate` + rounded first/last header cells (Commands, Snippets, Targets, Settings).
- **Settings labels** ("Auto-lock after", "Retention", run-confirm options, AI approval) were 16px browser default → 12px like the rest.
- **Bottom dock** → floating glass capsule; open state hugs the buttons with a 6px rim, low 16px corner radius concentric with the 10px buttons; pages stop just above the closed capsule (a plain frameless strip) and the open dock floats over the content.
- **Terminal toggle** moved from the title bar into the dock, next to the AI button, same round design; shows an active ring while the terminal is open.
- **Import & Export** tab made compact (normal buttons, 3-column grid); import is now **drag-and-drop or click-to-browse** - the file is staged privately (100 MB cap, path-traversal-safe, only staged files may skip the dialog) and continues through the normal conflict-resolution import.
- **Notes editor drag** was cancelled on every platform (two dragstart listeners each cancelled the other's drags) → fixed.
- **Glass appearance style** (new default) with the previous look kept as "Classic" - see the commit for details.

## 3. Features and logic restored from the original LOYA-Note

The gap analysis found most original logic had been copied into `Cores/Services/*` but left unwired, plus several data-loss bugs. Ported in parallel work packages:

- **Data loss fixed:** note commands wiped by append / terminal "send to note" / MCP; editing an old-format note deleted its commands (legacy `<C [...]>` and command tables now convert); soft delete destroyed attachments; Targets cache wrote stale data back (reverting Mini/Recycle Bin/import changes); key canonicalisation renamed `{ip}`→`{IPv4}`; Tag actions ran before the confirm; commands import "Replace" could overwrite an unrelated command; **auto-lock could encrypt an empty database over the real one** (reproduced on a copy of the data, then fixed).
- **Notes:** Group Manager, Ctrl+F find, Pick Command, rich paste with images, unsaved-changes prompt, lists/tables, editor context menu, links open in the system browser instead of navigating the app away, note-link resolution by name, editor preferences.
- **Commands/Snippets:** pages refresh when shown (+ cheap change polling), `{` placeholder suggestions ranked by usage, Linked/Not-linked filter, pager, Description column, dirty prompt, double-click to edit, Terminal Jobs dashboard card.
- **Targets/Mini:** live reload, rename/merge refresh, value search, sorted list, collapse button, Quick Space find/wrap, context menu, geometry persistence.
- **Settings:** JSON import accepts the original's exports, Overwrite/Replace semantics with per-row error counts, "apply to all", Notes `.db`/all-tables/CSV-ZIP export, Recycle Bin restore errors shown, purge-all is truly all, tabs refresh, Tag Manager counts note tags.
- **Security:** PIN back-off persisted across restarts, encryption dialog verifies the PIN, lock screen stays up on errors, shared settings.json lock, update checks and 6-hourly backups actually scheduled, **audit-log expiry** (off by default; 1-999 days/months/years).

## 4. New features

- **Terminal:** command suggestions while typing (index of all saved commands, shell-aware ranking, placeholder filling from the live target, never auto-runs); rebindable shortcuts (Ctrl+Space, Ctrl+Shift+Space, Ctrl+Shift+P) in Settings → Extensions.
- **AI:** MCP local server now runs in-process (external clients' terminal requests reach the app's approval queue); MCP no longer offered as a chat provider; Claude chat fixes (token budget, thinking blocks, empty turns, real provider errors); `/` slash commands, `@` mentions that attach notes/commands/targets as context, prompt history, Copy / To terminal / To note on replies; AI Roles privileges enhanced.

## 5. Open items / not verified

- **Windows was not run in this session.** Check there: Glass/Classic styles, the dock (floating over content, terminal button), Import drag-and-drop and click-to-browse, Mini collapse to 60px and ✕ quitting, Commands page size persistence, save dialogs (WinForms behaviour should be unchanged).
- **No real AI provider call** was possible (no key or local model on this machine) - tested against a fake provider.
- Real drag-and-drop from a file manager was simulated with a genuine `drop` event carrying a `File`; click-to-browse was tested end to end with the native chooser.
- Multi-monitor and HiDPI still untested (single 1x output).
- Saving a *new* note under an existing name overwrites that note (original behaviour) - decision pending, see `NG-New-ideas.md`.
- Known limitations from the security work: a batch/chain job finishing while the app is locked can't record its result; Mini has no lock screen of its own (its data calls are refused while locked).
- 10 files in the working tree differ from `HEAD` only by CRLF line endings (pre-existing, from editing on Windows); they were deliberately not committed.
