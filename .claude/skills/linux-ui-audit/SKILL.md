---
name: linux-ui-audit
description: Launch LOYA NG on the Linux desktop under an audit harness, drive it with real input, screenshot it, query the live DOM, and audit it for Linux/WebKitGTK-only UI bugs. Use when asked to run, play, test, screenshot, or audit the app's UI/UX on Linux, or to verify a UI fix live.
---

# Linux UI audit for LOYA NG

The app is pywebview: Chromium (WebView2) on Windows, **WebKitGTK** on Linux. Most "Linux only" UI bugs are WebKitGTK/GTK behaving differently from Chromium/WinForms. Always verify in the live app - screenshots plus DOM queries - not just by reading CSS.

## 1. Launch and drive

Scripts are in `scripts/` (paths below are relative to this skill directory). Workspace: `$LOYA_AUDIT_DIR`, default `${TMPDIR:-/tmp}/loya-audit` (log, screenshots, RPC files).

| Script | Does |
|---|---|
| `scripts/launch.sh` | Starts the real app (run it **in the background**). WebKit console → `app.log`; JS RPC enabled. Same WebKit env as the launcher. |
| `scripts/js.sh 'expr'` | Evaluates JS in the main window, prints JSON. `LOYA_WIN="LOYA NG Mini" js.sh ...` (also `jsa.sh`) targets the Mini window. |
| `scripts/jsa.sh 'async body'` | Same, but awaits promises (`evaluate_js` does not). Use for `bridgeCall(...)`. |
| `scripts/shot.sh name` | Pins the window above others and screenshots it → `shots/name.png`; then Read the PNG. |
| `scripts/stop.sh` | Stops the app. Never `pkill -f harness.py` unanchored - it matches your own shell and kills it. |

Wait for `console->stdout` in `app.log` before driving. **WebKit's console→stdout writes nothing on WebKitGTK 2.52**, so the harness installs an in-page collector (`window.onerror`, `unhandledrejection`, `console.error`/`warn`) about once a second and drains it to `app.log` as `[js-error] [window] ...` lines: `grep '\[js-error\]' app.log`. Errors thrown before the first drain after a load are missed; `console.log` is not captured. Python changes need stop + launch; CSS/JS changes only need `js.sh 'location.reload();1'`.

Driving tips:
- Navigate: `js.sh "document.querySelector('#bottomNav [data-page=settings]').click();1"` (pages: dashboard, notes, commands, targets, snippets, settings). Settings tabs: click the button whose text matches.
- Real input for anything focus/keyboard/hover related: `xdotool mousemove/click/type/key` using `xdotool getwindowgeometry --shell <win>` offsets. The user may be using the same display - say so before moving their pointer.
- ImageMagick 7: crops of `import` output keep a page offset - use `+repage` before `-crop`. Use `magick a b -compose difference -composite -colorspace gray -threshold 12% -format "%[fx:round(mean*w*h)]" info:` to count changed pixels (the `compare -metric AE` output is not a usable count here).
- zsh does not word-split `$VAR`; loop over files explicitly.

## 2. Audit procedure

1. Tour every page and every Settings tab; open every modal/popover (Add Note/Command/Target, selects, menus, terminal panel, AI panel, mini window). Screenshot each.
2. For anything that looks off, measure with `js.sh` (computed style, `getBoundingClientRect`, `elementsFromPoint`) before deciding the cause. If nothing in the DOM is at a spot that shows pixels, it is a stale repaint, not CSS.
3. Grep the code for the pitfalls below.
4. Log every finding (symptom, measured evidence, root cause file:line, Linux-only or not, fix, how verified) in the audit log the user asked for.
5. After each fix, re-verify live with a screenshot, and run both suites:
   `.venv_linux/bin/python3 -m unittest discover -s tests -p "test_*.py"` and `node tests/js/run.js`.

## 3. WebKitGTK / GTK pitfalls found in this app (check these first)

- **Glass/blur not drawn** → `backdrop-filter` needs accelerated compositing. `WEBKIT_DISABLE_DMABUF_RENDERER=1` forces policy NEVER (no blur). The launcher uses `WEBKIT_DMABUF_RENDERER_FORCE_SHM=1` instead (no blank window on VM GL, blur works). Check `settings.get_hardware_acceleration_policy()` (0 on-demand, 1 always, 2 never).
- **Stale "ghost" card edges** (old outline of a glass card left on screen after a resize, page switch or modal open) → Skia GPU painting with SHM frames leaves stale tiles behind `backdrop-filter` layers. The launcher sets `WEBKIT_SKIA_ENABLE_CPU_RENDERING=1` with `WEBKIT_DMABUF_RENDERER_FORCE_SHM=1` (0/60 vs 4/30 ghosts, same CPU). If ghosts come back, check the WebKitWebProcess env first; CSS tricks (rim removal, opacity/translateZ nudges, blur toggles) did not help. Detect with a pixel diff against an in-place re-render (`display:none` → rAF → `display:''`).
- **`user-select` ignored** → WebKitGTK needs `-webkit-user-select`. Every `user-select:` must have its `-webkit-` twin, or the whole UI is text-selectable.
- **Native controls look like light GTK** (checkboxes, number spinners) → `color-scheme` per theme, and `appearance:none` + themed checkbox in `base.css`.
- **Fonts**: "Segoe UI"/Consolas don't exist; use `var(--font-ui)` / `var(--font-mono)`; form controls need `font-family:inherit` or they get the GTK system font.
- **Scrollbars**: setting `scrollbar-width/color` disables `::-webkit-scrollbar` styling in WebKitGTK → standard props are gated to Chromium via `html:not(.engine-webkit)` (class set in `bridge.js`).
- **Border-radius on table header cells** is ignored with `border-collapse:collapse` → use `separate` + `border-spacing:0`, round `th:first-child/last-child`.
- **RTL tricks** (`direction:rtl` for start-ellipsis) flip POSIX paths (`/home/x` → `home/x/`) → wrap in U+200E.
- **GTK dialogs**: no overwrite confirmation, no auto extension, case-sensitive filters, open in CWD (handled in `api.py` `_save_dialog`/`_file_types`/`_dialog_dir`).
- **Never read `window.x/width/...` inside `closing` or any GTK-main-loop callback** - pywebview marshals it onto the same loop and deadlocks.
- `window.restore()` on GTK does not unmaximize a WM-maximized window.
- Edge `::-ms-reveal` password eye does not exist on Linux.
- **`::highlight()` (CSS Custom Highlight API) is not painted on text whose parent is the contenteditable root**, and removing or moving a highlight leaves the old marks on screen until something else repaints. Wrap root text nodes in a `<span>` before collecting ranges, then flip a property such as an invisible outline once per frame (see mini.js `miniQuickWrapRootText` / `miniQuickRepaint`).
- **Mini window**: open it with `js.sh 'document.getElementById("btnShrink").click();1'`. Test Alt+F4 too: a WM close must quit the app, never leave the hidden main window running (`pgrep -af harness`).
- **`localStorage` does not exist** (pywebview runs WebKitGTK in private mode - `localStorage` is an undefined variable, not empty). A `try{localStorage...}catch{}` silently loses the setting on Linux only. Persist UI preferences through the bridge into `Data/settings.json` (use `Cores/settings_lock.update_json`).
