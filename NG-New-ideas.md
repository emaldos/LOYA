# LOYA NG - new ideas to approve or skip

Date: 2026-11-23 | Branch: `s30b-linux-verification` | Version stays 1.0.0

## How to use this file

- Tick the box (`[x]`) for anything you want built.
- Write `skip` after an item you don't want, or write a short note (for example "later", "only on Windows", "smaller version").
- For **Decisions needed**, write your answer under the item (A or B, or your own words).
- Leave the rest alone. Nothing here gets built until you tick it.

Each item has: what it is and why it helps, effort (**S** = a few hours, **M** = a day or two, **L** = several days), risk or notes, and where the idea came from.

---

## Decisions needed

These are choices, not features. Pick one answer each.

- [ ] **D1. AI Roles "Assistant" preset: let adds/edits run without asking?**
  Today the Assistant preset allows reads and asks before every add or edit. A: keep asking (safer, more clicks). B: allow adds/edits, still ask for deletes and shell.
  Effort: S. Notes: if B, the Reporting AI test that expects "ask" must be updated too. Deletes and shell stay Deny/Ask either way.
  Source: AI Roles agent report.

- [ ] **D2. Ship the full MITRE ATT&CK Enterprise list?**
  Today the ATT&CK picker has a curated 161 techniques. A: keep 161. B: ship all 706 (v20.1), about +50 KB.
  Effort: S. Notes: the tool-name hints (nmap -> T1046 etc.) only exist for the curated ones; the extra ones would be search-by-name/ID only. Needs a plan for updating the list later.
  Source: Note editor agent report.

- [ ] **D3. Signed releases (Ed25519)?**
  Sign `SHA256SUMS` with an offline Ed25519 key; the app has the public key built in and refuses an unsigned or wrongly signed package. Today a stolen GitHub account/token could publish a matching zip and hash.
  Effort: M. Notes: you must keep the private key offline and never lose it (losing it means a manual re-install for everyone). Adds one step to Release Publishing. Fixed source repo check stays.
  Source: Updater agent report.

- [ ] **D4. Push users to a passphrase instead of a short PIN?**
  A 6-digit PIN can be brute-forced offline from a copied `Data/` folder in about 75 CPU-hours, even with Argon2id. A: keep PIN as is. B: allow PIN but show a strength warning and suggest a passphrase. C: require a passphrase when encryption is on.
  Effort: S (B) / M (C). Notes: C changes the lock screen and `resetPIN.py` flow. Fits with the SQLCipher + Argon2id rebuild.
  Source: Storage / security agent report.

- [ ] **D5. Saving a new note under an existing name**
  Today a *new* note with the same name as an existing one overwrites it (same as the original app). A: keep that. B: ask "Replace / Keep both (rename to `name (2)`) / Cancel".
  Effort: S. Notes: B is safer (no silent data loss); MCP/AI note-create would need the same rule.
  Source: Linux UI audit (`LINUX-UI-AUDIT.md`, section 5).

- [ ] **D6. Bring back single-note Markdown / HTML / PDF export (and Commands Markdown)?**
  The original had these; they were dropped with PyQt6. Build Report already does Markdown/HTML/PDF/DOCX of selected notes. A: keep them dropped. B: add "Export this note" (Markdown/HTML/PDF) on top of the report exporters.
  Effort: M. Notes: the report export code can be reused, so no Qt needed. The README says "not available, by design" and would change.
  Source: gap analysis vs original LOYA-Note (README "Import & Export").

- [ ] **D7. Should imported chains also carry the AI-made badge?**
  An imported chain shows **Imported - review**, not **AI-made - review**. Both already need the "I reviewed this chain" tick on the first run. A: keep them separate (today). B: also show the AI-made badge on imported chains.
  Effort: S. Notes: with B, imported chains would also pick up the AI-made rules (scripts always confirmed, "Allow unsandboxed" ignored). It also makes it harder to tell where a chain came from.
  Source: Chain Diagrams (README "Chain Diagrams").

- [ ] **D8. Default script policy for chain diagrams**
  Today the default is **Allow unsandboxed scripts**, because Windows has no sandbox. Each diagram can override it. A: keep "Allow unsandboxed" as the default. B: default to **Sandboxed only**, so on Windows a diagram with scripts will not run until you allow it.
  Effort: S. Notes: B is safer, but on Windows every script chain stops until you change the setting. AI-made and unreviewed diagrams ignore "Allow" either way. See also the Windows sandbox item under Storage and security.
  Source: Chain Diagrams (README "Script isolation"); `SECURITY-AUDIT.md` (remaining risks).

- [ ] **D9. Run the one-time NVD severity fill for the CVE index?**
  About 58% of CVEs in the offline index have a score today: high for 2024-2026, low before 2021, because older CVEs were mostly scored only by NVD. A: leave it (look old CVEs up online to get the score). B: run the build with `--nvd-severity` once (about 25 minutes without an NVD API key) so older CVEs get scores too.
  Effort: S. Notes: build-time only; the package size grows a little. Must be run again for every new index build, or the scores kept between builds.
  Source: README ("The offline CVE index").

- [ ] **D10. SA-37: formula-safe CSV for notes / commands / targets?**
  These CSV exports don't escape cells that start with `=`, `+`, `-` or `@`, so opening one in Excel can run a formula. Report CSV/XLSX are already safe. It is open on purpose, because escaping changes LOYA's own re-import format. A: keep it open (today). B: add an "Excel-safe" export option (off by default), with a matching unescape on import.
  Effort: S (B). Notes: B keeps the normal round-trip as it is. The audit also suggests a "this file may hold formulas" warning instead.
  Source: `SECURITY-AUDIT.md` (SA-37).

---

## Notes sidebar

- [ ] **Type-ahead jump**
  Start typing while the list has focus and the selection jumps to the first note whose name starts with those letters (like a file manager).
  Effort: S. Notes: must not clash with `/` (search) and the arrow-key navigation.
  Source: Notes sidebar agent report.

- [ ] **Multi-select with bulk move / tag / pin**
  Ctrl/Shift+click to pick several notes, then move to a group, add/remove a tag, or pin them all at once.
  Effort: M. Notes: the virtual list only draws visible rows, so selection must be kept by note id, not by DOM row.
  Source: Notes sidebar agent report.

- [ ] **Drag a group onto a group to re-parent it**
  Drop `Web` on `ACME` and it becomes `ACME/Web` (sub-groups renamed with it).
  Effort: M. Notes: reuse the existing parent-rename logic; block dropping a group into its own child.
  Source: Notes sidebar agent report.

- [ ] **Severity filter and click-a-tag-chip filter**
  Filter chips for "has Critical/High findings", and clicking a tag chip on a row filters the list to that tag.
  Effort: S.
  Source: Notes sidebar agent report.

- [ ] **Saved filter presets**
  Save the current view + sort + filters + search as a named preset ("ACME criticals") and switch with one click.
  Effort: M. Notes: stored in `settings.json` with the other sidebar settings.
  Source: Notes sidebar agent report.

- [ ] **Explicit note-to-target link**
  Today the Targets view matches notes by name/address text. Add a "Link to target" so a note shows under a target even when it doesn't mention it.
  Effort: M. Notes: needs a small schema change; do it after the storage rebuild.
  Source: Notes sidebar agent report.

- [ ] **Show the matched tag in compact rows**
  When a tag search matches, compact rows show that tag even if it's not one of the first two.
  Effort: S.
  Source: Notes sidebar agent report.

- [ ] **Remember collapse state for the Tags and Targets sections**
  Groups already remember their fold state; the tag/target sections reset.
  Effort: S.
  Source: Notes sidebar agent report.

- [ ] **Relevance-ordered search**
  Sort search hits by match quality (name match > tag > content, more hits higher) instead of the list sort.
  Effort: S/M.
  Source: Notes sidebar agent report.

- [ ] **Alt+Up / Alt+Down to reorder pinned notes**
  Keyboard twin of drag-to-reorder and Move Up / Move Down.
  Effort: S.
  Source: Notes sidebar agent report.

- [ ] **Remove the unused `notesTagTextStyle`**
  Dead code cleanup.
  Effort: S. Notes: no user-visible change.
  Source: Notes sidebar agent report.

## Note editor

- [ ] **ATT&CK: open the technique page, add it as a note tag, per-note ATT&CK summary**
  From an ATT&CK tag: open the MITRE page in the system browser, or add `T1046` as a note tag. A small summary lists the techniques used in the note (by tactic).
  Effort: M. Notes: links open externally only. Ties to D2.
  Source: Note editor agent report.

- [ ] **"Add hosts to Targets" from an nmap table**
  One button on a Nmap-to-table block to add every host (and open ports) to Targets.
  Effort: S/M. Notes: IOC tools already add one host; this does a batch with a preview.
  Source: Note editor agent report.

- [ ] **Reuse the terminal parsers for gobuster / ffuf / nxc output**
  Same idea as Nmap to table: paste/select tool output and get a clean table.
  Effort: M.
  Source: Note editor agent report.

- [ ] **Insert last terminal job output + exit code into a Command output block**
  One click fills the Command output block from the last finished job, instead of copy-paste.
  Effort: S/M. Notes: apply the existing secret redaction.
  Source: Note editor agent report.

- [ ] **Hash type identification (with hashcat mode hint)**
  Select a hash, get "NTLM, hashcat -m 1000" style guesses.
  Effort: S.
  Source: Note editor agent report.

- [ ] **More encoders**
  ROT13, Unicode escapes (`A`), gzip+base64, PowerShell `-enc` (UTF-16LE base64).
  Effort: S. Notes: gzip needs a small JS inflate or a bridge call.
  Source: Note editor agent report.

- [ ] **Epoch <-> date conversion**
  Select `1732400000` and see the UTC/local date, or the other way.
  Effort: S.
  Source: Note editor agent report.

- [ ] **CVSS 4.0 calculator, plus 3.1 environmental/temporal metrics**
  The calculator is 3.1 base only today; reports already have a CVSS 4.0 default setting.
  Effort: M. Notes: 4.0 scoring uses a lookup table; `Cores/Services/cvss.py` is 3.1 only today, so both the JS calculator and the Python side need it.
  Source: Note editor agent report.

- [ ] **Reverse-shell / payload snippets filled from Targets placeholders**
  Pick "bash reverse shell" and it fills `{LHOST}` / `{LPORT}` from the live target.
  Effort: M. Notes: snippets are only inserted as text, never run.
  Source: Note editor agent report.

- [ ] **Screenshot to evidence with an auto caption**
  Pasting a screenshot wraps it as Evidence with a time and the live target as caption.
  Effort: S/M.
  Source: Note editor agent report.

- [ ] **Table size picker**
  Grid picker (like Word) for rows x columns when inserting a table.
  Effort: S.
  Source: Note editor agent report.

- [ ] **Drag-reorder of pinned toolbar tools**
  In Customise, drag tools to change their order, not only pin/unpin.
  Effort: S/M.
  Source: Note editor agent report.

- [ ] **Per-host toolbar layout**
  Keep a different toolbar layout per machine (e.g. small laptop vs desktop).
  Effort: S. Notes: `settings.json` is per install, so mainly matters if Data/ is synced.
  Source: Note editor agent report.

- [ ] **Redacted copy for sharing**
  "Copy redacted" gives the note text with secrets, credentials and masked spans replaced by `[REDACTED]`.
  Effort: S.
  Source: Note editor agent report.

## Reporting and evidence

- [ ] **Flatten-permanently redaction for report evidence images**
  Option to burn redactions into the stored original too, so the unredacted image is gone, not just hidden in exports.
  Effort: M. Notes: can't be undone; ask to confirm.
  Source: earlier session.

- [ ] **Opt-in silent auto-naming**
  Name untitled notes/evidence automatically from the suggested title, without the chip click. Off by default.
  Effort: S.
  Source: earlier session.

- [ ] **Clickable links and repeated table headers in Linux PDFs**
  In PDFs made on Linux, external links are not clickable and long tables don't repeat their header row on each page.
  Effort: M. Notes: Linux-only fix in the WebKit print path; check that Windows (WebView2) output does not change.
  Source: Reporting team list.

- [ ] **Native Word layouts for callouts, the dashboard and the risk matrix**
  In DOCX export, build these as real Word tables/shapes instead of simple fallbacks, so they look like the PDF.
  Effort: L. Notes: Word layout is fiddly; test in Word and LibreOffice.
  Source: Reporting team list.

- [ ] **Compare report versions, and a cap on kept versions**
  Show what changed between two saved versions of a report. Also keep only the last N versions so the DB doesn't grow forever.
  Effort: M. Notes: the cap deletes old versions, so make the number a setting and never drop the newest one.
  Source: Reporting team list.

- [ ] **A "mark" button during recording, and evidence thumbnails**
  While recording, press Mark to flag the current moment (with a short label). Show small thumbnails in the evidence list.
  Effort: M.
  Source: Reporting team list.

- [ ] **Recording keeps half-finished lines**
  Today a recording captures only completed lines, so a prompt or a line without a newline at the end is lost.
  Effort: S/M. Notes: flush the partial line when the recording stops; keep the secret redaction.
  Source: Reporting team list.

- [ ] **Terminal record button: show it when docked, and give it its own icon**
  The record button is hidden when the terminal is docked, and it uses the report icon, which is confusing.
  Effort: S. Notes: UX only.
  Source: Reporting team list.

- [ ] **AI in Reporting: streaming replies, one-batch remediation, cost estimate**
  Show AI text as it arrives instead of all at the end. Add "Generate all remediation" for every finding in one go. Show a token/cost estimate in the consent dialog.
  Effort: M. Notes: the estimate is a guess per provider; label it as an estimate. Batch must still go through one consent.
  Source: Reporting team list.

- [ ] **Timeline: drag markers, snooze, .ics export, calendar across reports**
  Drag a marker to change its date, snooze a reminder, export the schedule as `.ics`, and see one calendar for all reports. Clicking a reminder opens its report.
  Effort: M/L. Notes: `.ics` is a plain file, no calendar account needed.
  Source: Reporting team list.

- [ ] **Findings: ATT&CK field, bulk status, re-sync, CVE refresh, EPSS, CVE detect**
  Add a MITRE ATT&CK field to findings. Change the status of several findings at once. Re-sync a finding from the Findings Library. Refresh a CVE chip with fresh data. Put EPSS in exports. Spot CVE IDs in pasted text and offer to add them.
  Effort: M (each part is S). Notes: re-sync must ask before it overwrites edited fields. Ties to D2 for the ATT&CK list.
  Source: Reporting team list.

- [ ] **Targets in reports: show a diff before "Update from target", and a "changed" badge**
  Before "Update from target", show what will change. Mark a report target with a "changed" badge when the target was edited after it was added.
  Effort: M.
  Source: Reporting team list.

- [ ] **Report editor: auto-chip `{{token}}`, syntax tint, Markdown preview, .md import with images**
  A typed `{{token}}` turns into a chip by itself. Light syntax colouring in the editor. A side-by-side Markdown preview. Import a `.md` file with its images.
  Effort: M. Notes: imported Markdown and images go through the same sanitiser.
  Source: Reporting team list.

- [ ] **Report list: table view and bulk export**
  A table view of reports (client, status, dates, findings), and select several reports to export at once.
  Effort: M.
  Source: Reporting team list.

- [ ] **"Mask credentials" default in Settings > Report Export Defaults**
  A default for the "mask credentials" export option, so you don't have to tick it every time.
  Effort: S. Notes: suggest on by default.
  Source: Reporting team list.

## Appearance and layout

- [ ] **"Reduce transparency" option for the Glass style**
  Accessibility option that makes glass panels solid. Noted as not needed now (Classic style already exists).
  Effort: S.
  Source: earlier session.

- [ ] **Drag-to-dock: pointer label covers the zone label**
  Move the pointer label so it doesn't hide the dock zone label.
  Effort: S.
  Source: drag-to-dock agent report.

- [ ] **Drag-to-dock: wider resize grab area**
  The 4 px resize edge is hard to hit; widen the hit area (keep the visible line thin).
  Effort: S.
  Source: drag-to-dock agent report.

## Updater

- [ ] **Run the Windows updater checklist**
  A Windows test checklist exists; it still needs a real pass on Windows.
  Effort: S. Notes: testing only.
  Source: Updater agent report.

- [ ] **Delta updates (later)**
  Download only changed files instead of the full zip.
  Effort: L. Notes: more moving parts in a sensitive area; not worth it while the zip is small.
  Source: Updater agent report.

---

## Fresh review - engagement and workflow

- [ ] **Engagement workspaces for notes**
  Targets and reports already have profiles ("engagement profile"), but notes don't. Let notes belong to a profile so switching client hides the other client's notes.
  Effort: L. Notes: schema change; do it after the storage rebuild. Default "no profile" keeps today's behaviour.
  Source: fresh review.

- [ ] **Scope guard in the terminal**
  Warn before running a command whose IP/host is outside the report's "In scope" list or inside "Out of scope" (`scope_in` / `scope_out` already exist on reports).
  Effort: M. Notes: warning only, never blocks; CIDR matching; hook into the existing destructive-command risk check.
  Source: fresh review.

- [ ] **Time tracking per engagement / target**
  Start/stop timer on a target or report, total hours shown on the report schedule and dashboard. Useful for billing and "how long did the web part take".
  Effort: M.
  Source: fresh review.

- [ ] **Operator activity log (like Ghostwriter's oplog)**
  A view of every command run: time, source (terminal/chain/AI), cwd, live target, exit code. Export CSV or add as a report appendix. Clients ask for this for deconfliction ("was that you at 14:02?").
  Effort: M. Notes: the data is already written as `terminal_command` audit events; this is a filtered view + export.
  Source: fresh review.

- [ ] **Methodology checklists per target**
  Checklist templates (web, AD, external, OWASP WSTG style) attached to a target, with progress shown on Targets and the dashboard.
  Effort: M. Notes: note templates and checklists exist; the new part is tying a checklist to a target and showing progress.
  Source: fresh review.

- [ ] **Loot / credentials view**
  One table of every Credential callout across notes (host, user, which note), with copy and "add to target values".
  Effort: M. Notes: show masked by default; respects app lock.
  Source: fresh review.

- [ ] **Engagement journal note**
  One click opens today's journal note for the active profile; Ctrl+Shift+; already adds timestamps, so entries are quick.
  Effort: S.
  Source: fresh review.

- [ ] **`[[` to link a note while typing (Obsidian style)**
  Typing `[[` opens a note picker and inserts a note link; backlinks already work.
  Effort: S/M.
  Source: fresh review.

## Fresh review - imports, exports, sync

- [ ] **Scanner imports into findings / targets (Dradis style)**
  Import Nessus `.nessus` XML, Burp XML, Nuclei JSONL and Nmap XML directly. Today findings import is CSV only ("Nessus-style CSV").
  Effort: L. Notes: parse with `defusedxml` or a safe parser (XXE); dedupe by plugin/template id + host.
  Source: fresh review; Nmap XML import is also on the Reporting team list.

- [ ] **Cheatsheet import into Commands**
  Import navi `.cheat` and arsenal cheats, mapping `<var>` to `{VAR}` placeholders.
  Effort: M.
  Source: fresh review.

- [ ] **Migration wizard from the original LOYA-Note**
  Point at an old LOYA-Note folder: dry-run summary, then import the DB, `Targets.json`, target values, Quick Space and tag colours in one go (with a backup first). Today you have to export/import each type.
  Effort: M. Notes: the import side already accepts the original's JSON and `.db`; this is a wrapper.
  Source: fresh review.

- [ ] **Password-protected engagement bundle**
  Export one engagement (notes, targets, report, evidence) as an encrypted file to hand to a teammate; import merges by uid.
  Effort: M. Notes: separate from the backup encryption in the storage rebuild; this is for sharing.
  Source: fresh review.

- [ ] **One-way folder sync for team use**
  Write notes as Markdown to a folder that git/Syncthing can sync, so a team can read each other's notes.
  Effort: L. Notes: one-way only to avoid merge conflicts; plaintext leaves the encrypted DB, so off by default with a clear warning.
  Source: fresh review.

- [ ] **Reviewer comments on findings (Pwndoc style)**
  When a report is in "review", a reviewer can leave comments on a finding; the writer resolves them.
  Effort: M. Notes: single-user app today, so this is mainly "notes to self" until there is sharing.
  Source: fresh review.

## Fresh review - terminal and security

- [ ] **OS notification when a long job or chain finishes**
  If the app isn't focused, show an OS notification when a scan/chain ends (with exit code). `os_toast.py` exists but is only used by CVE Intel.
  Effort: S.
  Source: fresh review.

- [ ] **Session recording to file**
  Optional per-session log (plain text with timestamps, or asciinema `.cast`) for evidence.
  Effort: M. Notes: apply the existing secret redaction; store inside Data/ so the storage rebuild encrypts it.
  Source: fresh review.

- [ ] **Clear the clipboard after copying a secret**
  After "Copy unmasked" or copying a target password, clear the clipboard after 30 s (if it still holds that value).
  Effort: S. Notes: needs a bridge call on Linux (X11/Wayland clipboard owners differ); test both OSes.
  Source: fresh review.

- [ ] **Include `search_index/`, `ai_sessions/` and the audit log in the storage rebuild**
  `Data/search_index/index.json` holds note titles, snippets and tokens in plain JSON. Make sure the rebuild covers it (and AI chat sessions and `security_audit.jsonl`), or move it into the encrypted DB.
  Effort: S/M. Notes: the planned rebuild lists targets/profiles/notes_meta/terminal sessions/Quick Space, but not these.
  Source: fresh review.

## Fresh review - accessibility and performance

- [ ] **Honour "reduce motion"**
  No CSS uses `prefers-reduced-motion`; add it (and an in-app switch) to turn off panel/dock animations.
  Effort: S.
  Source: fresh review.

- [ ] **UI zoom / text size**
  Ctrl+= / Ctrl+- and a text size setting. Helps on HiDPI (still untested) and for low vision.
  Effort: M. Notes: check the canvas fonts (drawing, graph) and terminal sizing follow it.
  Source: fresh review.

- [ ] **Screen reader and keyboard pass**
  Toasts have no `aria-live`, and only 2 dialogs use `aria-modal`; add live regions, focus trap and focus return in modals.
  Effort: M.
  Source: fresh review.

- [ ] **Lazy-load page scripts**
  `main.html` loads 54 scripts (about 1.8 MB of JS) at startup. Load Reporting, CVE, Settings etc. when first opened.
  Effort: M. Notes: risk of load-order bugs; page refresh relies on `loya:page-shown`, which helps.
  Source: fresh review.

- [ ] **SQLite FTS5 for note search**
  Use an FTS5 index inside the (encrypted) DB for content search instead of scanning notes / a JSON index.
  Effort: M. Notes: do after SQLCipher lands; check the sqlcipher3 build has FTS5.
  Source: fresh review.

## Fresh review - testing and CI

- [ ] **GitHub Actions: tests on Windows and Linux**
  There is no `.github/` folder. Add a workflow on `windows-latest` and `ubuntu-latest` (Python 3.10 and 3.13): `python -m unittest discover -s tests -p "test_*.py"`, `node tests/js/run.js`, the standalone `tests/js/*.js` suites, and the CRLF/version checks from the quality gate.
  Effort: S. Notes: tests are already pure logic, so no GUI needed.
  Source: fresh review.

- [ ] **CI release check**
  On a `v*` tag: build the zip with `git archive`, check the required/forbidden contents and `CurrentVersion.info`, write `SHA256SUMS`. Upload as a draft for you to publish.
  Effort: M. Notes: signing (D3) stays offline, not in CI.
  Source: fresh review.

- [ ] **Headless smoke test on Linux CI**
  Start the app under `xvfb` with WebKitGTK and check the UI loads (`update.launch_ready` is called). Catches "blank window" breaks.
  Effort: M/L. Notes: needs apt packages on the runner; may be flaky, keep it non-blocking at first.
  Source: fresh review.

---

## Storage and security

- [ ] **Hash chain for the audit log**
  Each line of `security_audit.jsonl` stores a hash of the line before it, so a deleted or edited line can be detected.
  Effort: M. Notes: a check on start (or in Settings) shows "audit log OK / broken at line N". Rotation must carry the chain on.
  Source: `Cores/storage_migration_plan.md` section 10; `SECURITY-AUDIT.md`.

- [ ] **Move target credentials into their own table**
  Keep target usernames/passwords apart from the other target values.
  Effort: M. Notes: schema change with a migration; masking for AI and MCP already exists and must keep working.
  Source: `Cores/storage_migration_plan.md` section 10.

- [ ] **Ask for the PIN on the other plaintext exports**
  The plain SQLite notes export already asks for the PIN when encryption is on. Do the same for notes JSON/CSV/Markdown, commands and targets.
  Effort: S/M. Notes: same "NOT encrypted" warning and `plain_export` audit event. Export All copies the encrypted files, so it can stay as it is.
  Source: `Cores/storage_migration_plan.md` section 10.

- [ ] **Windows sandbox for chain diagram scripts**
  On Windows, script nodes run with no isolation, as your user. Run them with a restricted token or in an AppContainer, like bubblewrap on Linux.
  Effort: L. Notes: Windows-only; needs testing on a real Windows box. Would let D8 default to "Sandboxed only" with no pain.
  Source: `SECURITY-AUDIT.md` (remaining risks); README "Script isolation".

## Chain Diagrams

- [ ] **Canvas: touch/pen, auto-pan, edge order, right-click menu**
  Touch and pen input. The canvas scrolls by itself when you drag near its edge. Reorder the edges that leave one port. A right-click menu on empty canvas (add node, paste, fit).
  Effort: M.
  Source: Chain Diagrams follow-ups.

- [ ] **MCP tool to answer Approval nodes?**
  Today an agent cannot answer an Approval node; only you can, in the app. This was left out on purpose. Do you want it (for example as an opt-in, shell-class permission)?
  Effort: S/M. Notes: it would let an AI approve its own run, which removes the human check; write `skip` if you want to keep it human-only.
  Source: Chain Diagrams / `docs/MCP-COVERAGE.md`.

## CVE Intel

- [ ] **Year filter in the CVE search UI**
  The bridge already supports a year filter; add a control for it in the UI.
  Effort: S.
  Source: CVE Intel follow-ups.

- [ ] **Typed CVE ID: fetch right away, or show the summary first?**
  With online lookups on, a typed ID that is only in the offline index opens a summary card with **Fetch full details**. Choose: fetch at once, or keep the summary first (no network until you click).
  Effort: S. Notes: could be a setting. "Summary first" sends fewer requests to NVD.
  Source: CVE Intel follow-ups.

## Targets

- [ ] **"Unused" filter**
  A filter that shows targets no note links to (links = 0) and that were not added by hand (not Manual).
  Effort: S. Notes: useful for cleaning up auto-added hosts.
  Source: Targets follow-ups.

## Mini window and terminal

- [ ] **Warn about unsaved changes when a window is closed**
  Closing the mini window or the app with unsaved edits loses them without asking. Add a "Save / Discard / Cancel" guard.
  Effort: M. Notes: the app has no close hook today, so one is needed on both pywebview backends (WebView2 and WebKitGTK).
  Source: Mini window / terminal follow-ups.

---

## Already in progress (no action needed)

- Final Linux and Windows E2E tests.

## Done since the first draft (no action)

- CVE Intel: lookup, news feed, watchlist, report picker, and the offline CVE index.
- Kali WSL setup with network modes, and PowerShell sessions.
- SQLCipher + Argon2id storage rebuild.
- Security audit (39 findings: 37 fixed, 1 accepted, 1 open by decision - see D10).
- Chain Diagrams.
- Full MCP access (see `docs/MCP-COVERAGE.md`).
