# LOYA NG - Security Audit (phase 1)

Date: 2026-11-23. Branch: `s30b-linux-verification`. App version: 1.0.0 (unchanged).
Phase 1 covers the finished areas and fixes gaps only in files no other agent is editing. Phase 2 covers the rest after the
other agents finish.

## 1. Scope

**Audited and fixed where needed**

- Updater: `Cores/Update/*`, plus the update paths in `RunNote.py` and `LOYA_Note.py`.
- External agents and MCP: `ext_agents_service.py`, `ext_agent_claude_runner.py`, `Bridge/ext_agents_api.py`,
  `mcp_local_service.py`, `Bridge/mcp_server.py`, `ai_service.py` (the permission engine), `ext-agents.js`, `ai.js`, `ai-dock.js`.
- Notes: `notes_service.py`, `UI/js/pages/notes*.js`, `markdown.js`, and the `notes_pro_core.js` sanitiser and paste allow-list.
- App shell: `live-target-badge.js`, `panel-dock.js`, `update-notice.js`, `toast.js`.
- Security and helpers: `security_service.py` (lock and PIN; the encryption parts are reported only), `settings_lock.py`,
  `recycle_bin.py`, `note_refs.py`. Also `Cores/os_toast.py` (not listed, but nobody else was editing it).
- The bridge: `Cores/Bridge/api.py`, except the Terminal, Reports and CVE sections.
- Dependencies (`Requirements.json` plus the packages installed in the venv), git secrets, `.gitignore`, and the secret scan in
  `gate.sh`.

**Audited only (hand-off in section 5):** `reports_*`, `reporting*`, `report_*`, `cve*`, `terminal_service.py`, `terminal.js`,
`settings.html`, `settings.js`, `common_db.py`, plus `UI/js/windows/mini.js` and `UI/js/app.js`.

## 2. Method

- **Code read:** every bridge module, the MCP tool table, the updater pipeline end to end (manifest, download, verification,
  staging, plan, apply helper, rollback), the agent child-process launch, and the HTML sanitisers on both sides.
- **Bridge enumeration:** `Api()` and `MiniApi()` were built in an isolated data dir and walked the same way pywebview's
  `get_functions` does. That found 464 published methods, and each one was checked against `_LOCK_OPEN`.
- **MCP check:** an AST check confirmed that every `@server.tool` calls `_check`/`authorize`.
- **Proof-of-concept payloads:** run against `sanitize_note_html`, `NotesPro.sanUrl`/`sanAttr`/`sanStyle` and `LoyaMarkdown`.
- **Dependency check:** OSV (`https://api.osv.dev/v1/query` and `/v1/querybatch`) for every pinned package and every package
  installed in `.venv_linux`.
- **Secrets:** `git log --all -p` grepped with the gate's key patterns; `.gitignore` reviewed.
- **Regression tests:** every fix has one, in `tests/test_security_audit.py` and `tests/js/security_audit.js`.

## 3. Findings

Severity is for this app's threat model. The main threats are:

- Untrusted content reaching the WebView: imported notes or backups, release notes, agent or MCP output, notes written by a
  prompt-injected agent.
- Other local users on the machine.
- The network path to GitHub.

Because the WebView has a Python bridge (`terminal.*`, `extAgents.*` and so on), any script running in it amounts to code
execution as the user.

| ID | Sev | Area | File:line | Description | Status | Test |
|---|---|---|---|---|---|---|
| SA-01 | **High** | Notes XSS | `UI/js/pages/notes.js:29,153` (call at :39) | `notesPlainTextFromHtml` and `notesStripHtmlPreview` set the stored note HTML as `innerHTML` of a `document.createElement("div")`. A detached element still belongs to the live page, so `<img src=x onerror=...>` runs and can reach the bridge. One trigger is **Summarize** on a note that was imported or written by an MCP agent. Fixed with an inert `DOMParser` document. | Fixed | `tests/js/security_audit.js` (SA-01) |
| SA-02 | Medium | Notes sanitiser | `Cores/Services/notes_service.py:342`; `Cores/Bridge/api.py:491` | The write-side regex sanitiser missed tags that contain a stray quote (`<img src=x' onerror=...>`) or a `<` in an unquoted value (`<img title=< onerror=...>`): the tag regex never matched them, so their `on*` handlers stayed in place. Separately, `notes.append` (MCP `notes_append`) stored its addition without sanitising at all. The tag regex now tolerates both forms, and `append` sanitises the combined HTML. (Rendering goes through the client DOM allow-list, which was not bypassed; this layer is defence in depth for other readers of the stored HTML.) | Fixed | `test_security_audit.NoteSanitiserTests`, `NoteAppendTests` |
| SA-03 | Medium (Windows) | Notes, NTLM leak | `UI/js/pages/notes_pro_core.js:435` | The render and paste policies allowed any `file:` URL as an image source. On Windows, `file://host/share/x.png` (or `file:////host`, `\\`, `%5C`) is a UNC path, so WebView2 opens SMB to that host and sends the user's NTLM hash as soon as the note is shown. The new `sanLocalFileUrl` keeps only local paths: Windows `file:///C:/...` and Linux `file:////home/...`. | Fixed | `tests/js/security_audit.js` (SA-03) |
| SA-03b | **High** (Windows, conditional) | OS notifications, command injection | `Cores/os_toast.py:6` | Windows toasts put the title and message inside a PowerShell `"..."` string, escaping only `` ` `` `"` `$`. PowerShell also ends a string at the typographic quotes U+201C, U+201D and U+201E. Report-reminder messages contain the report title, which an MCP agent can set, so a title like `x”;calc;“` runs code when the reminder fires (OS notifications must be on). Text is now passed as base64 in a single-quoted literal. On Linux, `notify-send` now gets `--` so a message starting with `-` cannot become an option. | Fixed | `test_security_audit.OsToastInjectionTests` |
| SA-04 | **High** (multi-user Linux) | Files, permissions | `Cores/Services/security_service.py:207` | `Data/`, `Backups/` and `Logs/` were created with the process umask: on this machine 775/664, and the DB and audit log were **766** (world-writable). Other local users could read the PIN hash, notes and targets, and write the DB (stored XSS, which means code execution as the victim). The new `harden_data_permissions()` sets folders to 0700 and files to 0600. It runs on every start from `sync_lock_state()`, never follows symlinks, skips files the user does not own, and does nothing on Windows. | Fixed | `test_security_audit.DataPermissionTests` |
| SA-05 | Medium | Agents, workspace escape | `Cores/Services/ext_agents_service.py:889` | For the Claude built-in tools, only `file_path`/`path` were checked against the workspace. Glob's `pattern` (`/etc/**`, `../../**`, `C:/Users/**`, `~/.ssh/*`) and Grep's `glob` filter could list files anywhere while being **auto-allowed** as read-only tools. These patterns are now confined to the workspace too. | Fixed | `test_security_audit.AgentGlobTests` |
| SA-06 | Low | Bridge | `Cores/Bridge/api.py:1832` | Every module's `bind(window)` (and `Api.bind`) was published to JS, so the page could call for example `reports.bind("x")` and break that module's window (DoS, and possibly confused behaviour). The methods are now hidden from pywebview with `_serializable=False` and still work from Python. | Fixed | `test_security_audit.BridgeExposureTests` |
| SA-07 | Low | Updater | `Cores/Update/update_service.py:597` | The apply helper ran from a temp folder that was first on `sys.path`, honoured `PYTHON*` variables and loaded user site-packages. It now runs with `python -I`. | Fixed | `UpdateHelperTests.test_helper_started_in_isolated_mode` |
| SA-08 | Low | Updater, TOCTOU | `Cores/Update/apply_update.py:87,473` | The helper hashed `package_path` and then extracted it again by path, so the file could be swapped between the check and the extraction (same-user attacker). It now copies the package into a private temp folder while hashing and extracts that copy. | Fixed | `UpdateHelperTests.test_package_swapped_after_the_hash_check_is_not_applied` |
| SA-09 | Low | MCP | `Cores/Bridge/mcp_server.py:8` | `quickrun_run` and `chains_run` read the saved commands (and returned errors naming placeholders) before the lock check. That matters in stdio mode, which has no HTTP guard. They now check the lock first. | Fixed | `McpLockOrderTests` |
| SA-10 | Low | Secrets, gate | `.claude/skills/ng-quality-gate/scripts/gate.sh:36` | The secret scan dropped any line containing `test` or `example` (so `latest`, or a `# test` comment, hid a real key), skipped `tests/` entirely, and missed newer key formats (`sk-proj-` keys with `-`/`_`, `gho_`/`ghs_`, `glpat-`, `ASIA`, `xoxa`/`xoxr`, service-account `private_key`). The exemption now applies to the matched value only, `tests/` is scanned, and the patterns were added. | Fixed | Manual check (see section 6) |
| SA-11 | Medium | Lock, PIN | `Cores/Services/security_service.py:453` | `security.set_app_lock(false)` turns app lock off without the PIN. Anyone at an unlocked session can disable it permanently, whereas encryption-off asks for the PIN (S20). A backend-only fix would break the current Settings UI, so it is in the hand-off (H-01). | Fixed (1b) | `AppLockPinTests` |
| SA-12 | Medium | Encryption (report only) | `security_service.py:14`, `settings.json` | The PIN hash and salt sit in `settings.json`, and the DB key is derived from the same PIN with PBKDF2-SHA256 at 200k iterations. A 4-character PIN can be brute-forced offline from a copied `Data/` folder in seconds to minutes, and the online throttle does not apply offline. So encryption at rest is only as strong as the PIN. Recommend: enforce a longer passphrase when encryption is on, use a memory-hard KDF (scrypt or Argon2id) or at least 600k iterations, and keep the verifier separate from the key-derivation salt. | Fixed (storage phase 2; re-verified) | storage tests; final re-verification, section 9 |
| SA-13 | Low | Lock | `Cores/Bridge/api.py:1819` | While locked, `terminal.read` stays open, so terminal output can be read through the bridge (for example from devtools or an XSS). Also open while locked: `theme.*`, `focusMode.set`, the Mini `settings`/`save_settings`, and the whole `window` module including Mini `activity` and `restore_and_open_note`. All of these are harmless except `terminal.read`. That one is left open on purpose because the terminal UI polls through the lock; see H-03. | Fixed (by the terminal/WSL agent; re-verified in phase 2: `terminal.read` is no longer in `_LOCK_OPEN`) | bridge enumeration (section 8) |
| SA-14 | Low | Backup restore | `Cores/Update/backup_restore.py:123,233` | `restore_data_backup` and `restore_code_snapshot` use `extractall` with no entry-count or size limits (zip bomb), and `backup.restore(path)` accepts any zip path from JS. `extractall` already strips `..` and absolute names, and symlinks are not created. Recommend running `update_helpers.inspect_package_zip`-style limits sized for Data backups. | Fixed (1b) | `BackupZipLimitTests` |
| SA-15 | Low | Notes | `UI/js/pages/notes.js:306` | A `cmd:` link copies the command encoded in its href, which can differ from the visible card or link text (pastejacking from an imported note). Recommend showing the copied command in the toast, or copying only from rendered cards. | Fixed (1b) | `tests/js/security_audit.js` (SA-15) |
| SA-16 | Info | Updater | `update_service.py` `resolve_expected_sha256` | All SHA-256 sources (asset digest, SHA256SUMS, release body) come from the same GitHub release. Integrity is therefore relative to the GitHub account; there is no publisher signature. See section 6. | Accepted risk | - |
| SA-17 | Medium | Dependencies | `Requirements.json` | **mcp 2.0.0**: GHSA-84m7-p3x7-pcfv (CVE-2026-59951), unbounded StreamableHTTP session accumulation (DoS; reachable only with a valid bearer token). GHSA-5h93-6whr-6q8j, GHSA-qx49-fqc8-xw99, GHSA-rwrf-2pqf-9j8j and GHSA-w4fh-qvv9-3v23 (client-side and OAuth issues, not used by LOYA) are fixed in 2.2.0. **fpdf2 2.8.7**: GHSA-rw7v-4hrq-x6r9 (CVE-2026-114609), implicit loading of external URLs and local image paths when rendering attacker-controlled content (relevant to PDF export of imported findings), and GHSA-wqw6-wpr3-45rh (SVG `<use>` blow-up), both fixed in 2.8.8. **cryptography 48.0.1**: GHSA-g6cj-pr64-35w5, GHSA-jwv3-5hgf-82ww and GHSA-m2h6-j472-rp4c cover PKCS#7 decryption and X.509 path validation only; LOYA uses Fernet and PBKDF2 only, so it is not affected (fixed in 49/50). **pywebview 6.2.1, python-docx 1.2.0, claude-agent-sdk 0.2.182, keyring 25.7.0**: no OSV entries. Pins were not changed in phase 1 because new versions need an install and test run; see H-08. | Fixed (1b) | `DependencyPinTests`, `McpErrorPassthroughTests` |
| SA-18 | Low | Dependencies, environment | `.venv_linux/pyvenv.cfg` | `include-system-site-packages = true`: unpinned transitive packages come from the OS (Kali). Examples: starlette 1.1.0 (GHSA-jp82-jpqv-5vv3, GHSA-82w8-qh3p-5jfq), python-multipart 0.0.26 (GHSA-pp6c-gr5w-3c5g and 4 more), anyio 4.12.1 (GHSA-82r6-8w77-94w6). These serve the MCP server. Recommend an isolated venv with a constraints file for the `mcp` dependency tree. | Fixed (1b) | `DependencyPinTests` |
| SA-19 | Medium | App shell, navigation | `UI/js/components/nav-guard.js`; `Cores/Bridge/api.py` `_install_nav_guard` | pywebview injects `window.pywebview.api` into every page the window loads, and nothing stopped the window navigating away: link clicks outside the notes viewer, `window.location`, `form.submit()`, `window.open`, dropped URLs. Also, `target=_blank` and `window.open` went to `webbrowser.open()` with any scheme, which on Windows is `os.startfile` (`ms-msdt:`, `search-ms:`, `file:`). Fixed in two layers. The JS layer blocks link clicks, form submits and URL drops, and disables `window.open`. The native layer is a GTK `decide-policy` handler or WebView2 `NavigationStarting` cancel for any top-level navigation outside `UI/` (`about:blank` and `about:srcdoc` are allowed). `OPEN_EXTERNAL_LINKS_IN_BROWSER` is now off. Links still open externally only through `notes.open_url`. | Fixed (1b) | `NavGuardNativeTests`; `tests/js/security_audit.js` (H-05); live test, see section 7 |
| SA-20 | Low | Mini window | `UI/js/windows/mini.js` `miniSetQuickHtml` | Quick Space HTML (from `QuicSpace.json`, which a backup can carry) was set with `innerHTML`. It is now parsed in a `<template>` and cleaned with the notes allow-list (`NotesPro`, render mode). | Fixed (1b) | `tests/js/security_audit.js` (H-04); live test, see section 7 |
| SA-21 | Low | Settings integrity | `api.py` `_remember_dialog_dir`; `notes_service.py` colour setters; `search_service.save_favorites`; `targets_service._set_allow_dots_colons`; `Theme/tokens.py` `set_mode`/`set_accent` | These did read-modify-write on `settings.json` outside `SETTINGS_LOCK`, some with a fixed `.tmp` name, so concurrent bridge calls could lose keys or tear the file. All of them now go through `settings_lock.update_json` or `@settings_lock.serialized`, and `tokens._write_settings` uses `settings_lock.write_json`. An AST test fails on any future unlocked writer. | Fixed (1b) | `SettingsWriteLockTests` |
| SA-22 | Low (privacy) | Notes | `UI/js/pages/notes_pro.js` `notesProBlockRemoteImg` | Remote `http(s)` images loaded as soon as a note was shown (tracking pixel, IP leak). New setting **Block remote images**, on by default, under Notes editor > More > View. Blocked images become a click-to-load placeholder. Their URL is restored on save, so the note never changes. | Fixed (1b) | `RemoteImagePrefTests`; `tests/js/security_audit.js` (remote images); live test, see section 7 |
| SA-23 | Medium (Windows) | Files, ACL | `security_service.py` `_harden_windows_acls` | Windows counterpart of SA-04. On every start, `Data/`, `Logs/` and `Backups/` get an owner-only ACL (current user by SID, plus SYSTEM and Administrators), and only if the folder still inherits its ACL. It runs `icacls` with an argv list. It is idempotent, does nothing if the user's SID cannot be read, and only logs on failure. | Fixed (1b), real Windows run pending in the Windows E2E | `WindowsAclTests` (mocked icacls) |
| SA-24 | Medium | MCP, secrets | `Cores/Services/mcp_local_service.py` `mask_live_secrets`; `ai_service.summarize_args` | Live-target secret values (for example `{Password}` or `{NTLM Hash}`) reached AIs inside resolved commands: in `quickrun_list`, `terminal_run_status`, `chains_*` step lists and output tails, error messages, and approval and audit summaries. Two layers now cover this. (1) The External Agents agent masks at the source: `masked_resolver` in `quickrun_list`/`quickrun_run`, and masked dict keys in `summarize_args`. (2) As a central backstop, every tool result, ToolError message and argument summary has the live target's secret-named values (4 characters or more) replaced with the mask. The exception is `targets_secret_values`, which has its own key and is Deny by default. The real command still goes, unmasked, only into the operator's approval queue. | Fixed (1b) | `LiveSecretMaskingTests`; `test_mcp_app_tools.test_quickrun_never_shows_secret_placeholders_to_the_ai` |
| SA-25 | Medium | Secrets, redaction | `Cores/Services/terminal_service.py` `_SECRET_PATTERNS` | `redact_secrets` missed `curl -u user:pass`, `--user=`, `https://user:pass@host` (any scheme), `smbclient -U user%pass`, impacket `domain/user:pass@host` and `-hashes LM:NT`, so these reached saved jobs, recordings, evidence, exports and AI context in clear. Its `-p` rule had no left boundary (`--protocols` became `--p[redacted]`). New patterns were added and `(?<![\w-])` boundaries put in. False positives (`nmap -p 80`, `-p-`, `user@host:/path`, `well-positioned`) are checked. | Fixed (P2) | `RedactionPatternTests` |
| SA-26 | Medium | Audit log | `Cores/Services/security_service.py` `log_audit_event` | `Data/security_audit.jsonl` stored whatever callers logged: full commands, tool arguments, agent summaries. Every entry is now redacted at that one entry point. The format is unchanged, and the storage agent has been told. | Fixed (P2) | `AuditLogRedactionTests` |
| SA-27 | Medium | Reporting | `Cores/Services/reports_service.py` `sources()` | `reports.sources()` returned raw target values (passwords, hashes) to the page and relied on client-side filtering. It now returns public values only, plus `secret_keys` names, the same as `targets_available()`. | Fixed (P2) | `ReportSourcesTests`; `test_reports_model` |
| SA-28 | Low | Bridge, paths | `Cores/Bridge/api.py` `_require_picked` | `importExport.apply_notes/commands/target_values/targets_import`, `apply_import_all` and `backup.restore` accepted any file path from the page. They now need a path handed out by a `pick_*` call in this session, or a backup from LOYA's own list (`reportsIO` already did this). | Fixed (P2) | `ImportPathAllowListTests` |
| SA-29 | Low | Reporting AI consent | `Cores/Bridge/report_ai_api.py` | `reportAI.run`/`run_start` from the page worked without the digest of the preview the operator confirmed, so the consent dialog could be skipped. The bridge now requires a 64-hex digest; the service still checks it against the content. | Fixed (P2) | `ReportAiConsentTests` |
| SA-30 | Medium (Windows) | Terminal, elevation | `terminal_service.py` `_ElevatedSession._start` | The administrator helper ran the venv interpreter normally. `.pth` files and `PYTHON*` variables from the user-writable venv and environment ran with administrator rights. It now runs with `-I -S` (standard library only). | Fixed (P2) | `ElevatedHelperIsolationTests` |
| SA-32 | Low | AI chat | `Cores/Services/ai_chat_service.py` `_call_tool` | A one-item list from a tool without an output schema came back as a bare object, and an `is_error` result counted as success. The tool's declared return type now decides, and `is_error` means failure. `test_mcp_app_tools` relied on the old unwrap and was adjusted. | Fixed (P2) | `ToolResultListTests` |
| SA-33 | Medium | Dependencies | `Requirements.json` | OSV against the venv: system copies of pillow 12.3.0 (43 advisories; decodes imported report images), httpx2/httpcore2 2.9.1 and opentelemetry-api 1.44.0 (mcp) had open advisories. Minimum versions were added (`pillow>=13.0.0`, `httpx2>=2.12.0`, `httpcore2>=2.10.0`, `opentelemetry-api>=1.45.2`) and installed (13.0.0, 2.16.2, 2.16.2, 1.45.2). | Fixed (P2) | `PhaseTwoDependencyTests` |
| SA-34 | Low | App shell | `UI/js/components/confirm-dialog.js`, `components.css` | The confirmation dialog had no focus trap and no Esc handling, and Enter and Tab could reach the page behind it. Button labels were interpolated as HTML, and long names overflowed. Fixed: a focus trap, Esc cancels, focus starts on Cancel for dangerous actions, labels are set as text, `overflow-wrap:anywhere`. | Fixed (P2) | `tests/js/security_audit.js` (SA-34); live test, see section 7 |
| SA-35 | Low | App shell | `UI/js/components/resize.js` | A fast click on a window edge released the button before `window.bounds` answered, and the late answer turned resize mode on with no button held. Fixed with a `pressed` flag, a `buttons===0` stop and `blur`. | Fixed (P2) | `tests/js/security_audit.js` (SA-35) |
| SA-36 | Medium | MCP | `Cores/Bridge/mcp_app_tools.py` `app_search`; `search_service.global_search` | `app_search` (App > Read, Allow) returned every target's values, passwords included, in its previews. It also matched on them, so it worked as an oracle for guessed secrets. It now uses `hide_secret_values=True`: secret-named values are neither matched nor shown. | Fixed (P2) | `AppSearchSecretTests` |
| SA-37 | Low | Exports | `notes_service.py:1561`, `commands_service.py:556`, `settings_service.py:204,294` | The notes/commands/targets CSV exports do not neutralise cells that start like a formula (`=`, `+`, `-`, `@`); report CSV/XLSX exports do. These files are LOYA's own round-trip format, so escaping would change re-imported data. Recommend `csv_safe` plus a matching unescape on import, or an "open in a spreadsheet" warning. | Open | - |
| SA-38 | Low | Chains, backup | `Cores/Update/backup_restore.py` (storage agent) | A data restore brings chain diagrams back with their stored "reviewed" flag, so a restored backup vouches for its own scripts. Handed to the storage agent: mark every `ChainGraphs` row unreviewed after a restore, as `flow_service.import_json` does. | Fixed (storage phase 2; re-verified) | `backup_restore._mark_chains_unreviewed`; section 9 |
| SA-39 | Low | Terminal, elevation (Windows) | `terminal_service.py` `elevated_helper_parameters` | The elevated helper was a script in a temp folder that the administrator process ran after UAC; a process already running as the user could swap it in that window. It is now never a file: its source (with the session token) goes base64-encoded inside the `-c` argument of `python -I -S` handed to `ShellExecuteW(runas)`, and the port and shell arguments are checked (no `"` or line breaks). Verified on Linux that the `-I -S -c` loader starts and completes the token handshake. | Fixed (P2) | `ElevatedHelperIsolationTests` (mocked `ShellExecuteW`; no file or temp folder may be created); `test_backend_support` |

**Verified with no finding:**

- **Markdown converter:** escapes everything and only links `http`, `https`, `mailto` and `notelink`.
- **Client DOM sanitiser:** drops `on*`, `srcdoc`, `javascript:`/`vbscript:`/`data:text`, SVG, MATH, STYLE, TEMPLATE and
  NOSCRIPT; CSS `url()`, `expression()`, backslash escapes and `position` are dropped too. Parsing happens in an inert
  `<template>`.
- **Paste allow-list:** classes and `data-*` attributes are restricted.
- **Release notes:** rendered through LoyaMarkdown, with links re-filtered to https or mailto.
- **Agent and AI chat output:** always `aiEscapeHtml`.
- **`notes.open_url`:** http, https and mailto only.
- **`update.open_release_page`:** official repository only.
- **Updater network checks:** an HTTPS GitHub host allow-list on every redirect hop; the official owner, repo and tag in the
  asset URL; size caps; at least one published SHA-256, with every source required to agree.
- **Zip handling:** zip-slip, absolute and drive paths, `:` (ADS), symlinks and special files, encrypted entries,
  case-insensitive duplicates, and ratio and size limits are all checked.
- **Staged-update re-verification:** checks again at start-up. Rollback uses a pre-apply snapshot, and the apply helper
  re-validates the plan (official repository and URL, semver, SHA format).
- **MCP server:** binds to 127.0.0.1. It requires a 256-bit `secrets.token_urlsafe(32)` bearer token compared with
  `hmac.compare_digest`. Tokens are made per start and per agent run and revoked when the run ends or the app locks. Host and
  Origin allow-lists block DNS rebinding and browsers. A client-sent `x-loya-client` header is stripped. HTTP 423 is returned
  while locked. All 55 tools go through `authorize()`.
- **Agent child processes:**
  - They get a minimal environment (`child_env`), with no inherited API keys.
  - They run in their own process group or session, and `kill_tree` ends the whole tree with `killpg` or `taskkill /T`.
  - The MCP config file is created 0600, and stderr is redacted.
  - Plaintext keyring backends are refused.
  - The runner starts with `-I`, and `--ignore-user-config` and `disableAllHooks` are set.
- **PIN:** PBKDF2 with a timing-safe compare. Wrong-PIN throttling is persisted and serialised by `_UNLOCK_LOCK`, and a clock
  jump cannot extend the wait.
- **Lock guard:** every published bridge method other than the open list above raises while locked.
- **No `shell=True`** anywhere in the audited code.
- **`.gitignore`** covers `Data/`, `Logs/`, `Backups/`, `state.json`, `.env*`, keys and `settings.local.json`.
- **Git history:** the only key-shaped strings are fake test fixtures.

## 4. Fixes made (files)

- `UI/js/pages/notes.js`: `notesInertText()` with DOMParser (SA-01).
- `UI/js/pages/notes_pro_core.js`: `sanLocalFileUrl()` and `sanIsWindows()`, exported (SA-03).
- `Cores/Services/notes_service.py`: the `_SAN_ANY_TAG_RX` fix (SA-02).
- `Cores/Bridge/api.py`: `append()` sanitises (SA-02); `_hide_from_js()` for `bind` (SA-06).
- `Cores/Services/security_service.py`: `harden_data_permissions()`, called from `sync_lock_state()` (SA-04).
- `Cores/Services/ext_agents_service.py`: `_glob_within()` in `builtin_tool_decision` (SA-05).
- `Cores/Update/update_service.py`: the helper runs with `-I` (SA-07).
- `Cores/Update/apply_update.py`: `_copy_hashed()`, and extraction from the verified copy (SA-08).
- `Cores/Update/backup_restore.py`: data backups skip `Data/cve_index/`, as the CVE-index agent asked.
- `Cores/Bridge/mcp_server.py`: `_lock_check()` first in `quickrun_run` and `chains_run` (SA-09).
- `Cores/os_toast.py`: base64 PowerShell literals, and `--` for `notify-send` (SA-03b).
- `.claude/skills/ng-quality-gate/scripts/gate.sh`: the secret scan (SA-10).
- New tests: `tests/test_security_audit.py` (16 tests) and `tests/js/security_audit.js` (42 checks).

**Phase 1b**

- `Cores/Services/security_service.py`: `set_app_lock(False, pin)` needs the typed PIN (SA-11); `_harden_windows_acls()` and `_win_user_sid()` (SA-23).
- `UI/js/pages/settings.js` (`setDoToggleLock`, small change): asks for the PIN before turning app lock off.
- `UI/js/components/nav-guard.js` (new) and the `<script>` tag in `UI/windows/main.html` and `mini.html`; `api.py` `_nav_allowed()`, `_install_nav_guard()`, `_harden_webview_settings()` (SA-19).
- `UI/js/windows/mini.js`: `miniSanitizeNode()` and `miniSetQuickHtml()`; `mini.html` now loads `notes_pro_core.js` (SA-20).
- `UI/js/pages/notes.js`: `notesCmdLinkCopyText()` (SA-15), and click-to-load for blocked images.
- `UI/js/pages/notes_pro.js`: blocking and unblocking of remote images; `notes_editor_core.js` and `notes_editor.js`: the "Block remote images" toggle; `notes_service.py`: the `block_remote_images` preference, default on; `UI/css/pages/notes.css`: the placeholder (SA-22).
- `Cores/Update/backup_restore.py`: `_safe_extract_backup()` with limits, used by data and code restores (SA-14).
- Locked settings writers (SA-21): `api.py`, `notes_service.py`, `search_service.py`, `targets_service.py`, `Theme/tokens.py`.
- `Requirements.json`: `mcp==2.2.0`, `fpdf2==2.8.8`, `starlette>=1.3.1`, `python-multipart>=0.0.31`, `anyio>=4.14.2`, all installed in `.venv_linux` (SA-17, SA-18).
- `Cores/Services/mcp_local_service.py`: `passthrough_expected_errors()` (for mcp 2.2 error masking), `mask_live_secrets()` and `live_secret_values()` (SA-24); `ai_service.summarize_args` masks live secret values.
- Tests: 19 more Python tests in `tests/test_security_audit.py` (38 in total) and 26 more JS checks in `tests/js/security_audit.js` (68 in total).

## 5. Hand-off: files owned by other agents

| ID | Sev | Owner file(s) | Finding | Suggested fix |
|---|---|---|---|---|
| H-01 | Medium | `settings.js` and `security_service.set_app_lock` | Turning app lock off needs no PIN (SA-11). | **Done (1b):** backend requires the typed PIN; Settings prompts for it (`settings.js` setDoToggleLock). |
| H-02 | Medium | `common_db.py` | `data_dir()` and the DB are created with the umask (SA-04 is mitigated at start-up only). A Data folder restored or recreated mid-session is 0775 until the next start. | Routed to the storage phase 2 rewrite. |
| H-03 | Low | `terminal.js` / `api.py` `_LOCK_OPEN` | `terminal.read` is callable while locked (SA-13). | Routed to the terminal/WSL agent. |
| H-04 | Low | `UI/js/windows/mini.js:234,349` | Quick Space HTML is loaded with `innerHTML` unsanitised. It is local data, but a restored or imported backup can carry it. | **Done (1b):** SA-20. |
| H-05 | Low | `UI/js/app.js` | There is no app-wide guard against a plain `<a href>` click navigating the main window, and pywebview re-injects `window.pywebview.api` into any page the window navigates to. Only the notes viewer and the update notice intercept link clicks. | **Done (1b):** SA-19. Kept out of `app.js` (the Chains agent edits it): a standalone `nav-guard.js` loaded right after `bridge.js` in both windows, plus the native guard in `api.py`. |
| H-06 | Low | `report_schedule.py` | Reminder messages embed report titles that agents control (the injection itself is now neutralised in `os_toast`). | Routed to the Reporting team. |
| H-07 | Low | `report_export_pdf.py`, `report_pdf_native.py` | fpdf2 2.8.7 loads external URLs and local image paths from content (GHSA-rw7v-4hrq-x6r9). | Routed to the Reporting team; fpdf2 is now 2.8.8 (leader notified). |
| H-08 | Medium | Owner of `Requirements.json` and `RunNote.py` | Outdated pins (SA-17). | **Done (1b):** `mcp==2.2.0`, `fpdf2==2.8.8`, installed in `.venv_linux`. mcp 2.2 masks non-ToolError messages, so `mcp_local_service.passthrough_expected_errors()` re-raises expected refusals (ValueError, PermissionError, TimeoutError, DatabaseLocked) as a redacted ToolError, and real crashes stay masked. The External Agents agent added the hook to `build_server()`. |
| H-09 | Info | Reporting UI / `reports_service.py` | Reviewed with no finding: the HTMLParser allow-list sanitiser (`_Sanitizer`), the client `RC.sanitizeHtml`, `rptasset:`-only image sources, escaped badges and pickers. | Keep `reporting_widgets.js:887` `pasteHtml` running through `RC.sanitizeHtml` (it currently only removes `<img>` from a `<template>` and relies on later sanitising). |
| H-10 | Info | `recycle_bin.py:45`, `notes_service._write_settings` | `settings.json` is written outside `SETTINGS_LOCK` and with a fixed `.tmp` name, so a concurrent save can be lost (integrity, not security). | **Done (1b):** SA-21. |

## 6. Residual risks and recommendations

1. **No publisher signature on updates (SA-16).** A compromised GitHub account or release token can ship a validly hashed
   malicious update. Sign `SHA256SUMS` (minisign or Sigstore) with an offline key and pin the public key in `update_helpers.py`.
2. **Windows ACLs (code folder: accepted, owner decision 2026-11-23).** LOYA NG is open source and is not packaged or
   installed; users clone or copy it to a folder they choose, so where the code lives is the user's choice and out of scope.
   For `Data/`, `Logs/` and `Backups/` this is now done: they get an owner-only ACL on Windows (SA-23).
3. **`codex.cmd` on Windows.** If Codex is an npm `.cmd` shim, `subprocess` runs it through `cmd.exe`, and arguments are not
   escaped for cmd metacharacters. The current arguments are constrained (`_MODEL_RX`, fixed lists, and the prompt goes over
   stdin), but a workspace path containing `&` or `%` would be interpreted. Prefer resolving the real `node` and `codex.js`, or
   reject `.cmd`/`.bat` paths.
4. **Remote images in notes.** Done in 1b (SA-22): blocked by default with click-to-load. Report previews were not changed. They already use
   a CSP of `img-src data:` in a sandboxed iframe.
5. **Agent project settings.** Claude runs with `setting_sources=["user","project"]`. If an operator enables Write for the agent,
   it can write `.claude/settings.json` in its own workspace for the next run. Hooks are disabled and the tool set is fixed by
   LOYA, but `["user"]` alone would be tighter.
6. **Gate secret scan (SA-10)** was checked by hand: a key on a line containing "latest" is now caught, `sk-ant-TEST-...` and
   `AKIAABCDEFGH...` fixtures are exempt, and `bash -n` passes. It only scans staged changes, so also run a history scanner
   (gitleaks or trufflehog) before the first public release.
7. **SA-18 and system site-packages.** The Linux venv must see the system site-packages (PyGObject/GTK for pywebview), so a
   plain `==` pin cannot keep the OS copies out. Minimum-version floors in `Requirements.json` (`starlette>=1.3.1`,
   `python-multipart>=0.0.31`, `anyio>=4.14.2`) work because pip then installs patched copies into the venv, and those shadow the
   system ones (verified: 1.10.0, 0.0.34, 4.16.0). Packages the app does not depend on directly can still be old in the system
   site-packages; they are not imported by LOYA.
8. **Phase 2** should repeat the `bridge_enum` and `innerHTML` sweeps after the reporting, terminal, settings and CVE work
   lands, and re-run OSV against the final pins.

## 7. Test results

**Phase 1b (2026-11-24)**

- `.venv_linux/bin/python3 -m unittest discover -s tests`: **1581 tests, OK** (1 skipped). This was run on mcp 2.2.0 and fpdf2 2.8.8.
- `node tests/js/run.js`: **418 passed, 0 failed**. All 33 `tests/js/*.js` files pass, including `security_audit.js` with 68 checks.
- The version is still 1.0.0, and no CRLF was introduced.

**Live test (SA-19, SA-20, SA-22).** The app ran from a copy of the code in the scratchpad, with an empty `Data/`, on a private Xvfb display `:97`, never `:0`, under the `linux-ui-audit` harness.

- After each attempt below, `window.__probe` (a marker set in the page) and `location.href` were unchanged, so the page did not navigate:
  - a link `.click()`;
  - a real `xdotool` left click and middle click on an `https://` link;
  - `location.href = "https://..."`;
  - `location.assign("file:///etc/hostname")`;
  - `form.requestSubmit()` and `form.submit()`;
  - in the Mini window, `location.href = "https://..."`.
- The native guard logged the attempts that got past the JS layer: `[nav-guard] blocked navigation to https://example.com/`, `file:///etc/hostname`, `https://example.com/y?` and `.../mini`.
- `window.open()` returned null.
- A synthetic URL `dragover` and `drop` were both default-prevented.
- Mini: `miniSetQuickHtml` with `<img onerror>`, `<svg onload>` and a `javascript:` link rendered as `<p>ok</p><a>j</a>`, and no script ran.
- Notes: an `https://` image rendered as a blocked placeholder with no `src`. Clicking it loaded the image. Serialising the editor kept the original `src`.
- Not tested: dragging a URL in from another X application (the native guard covers that case too). The Windows ACL and the WebView2 guard are pending in the Windows E2E.

**Phase 1 (before 1b)**


- `.venv_linux/bin/python3 -m unittest discover -s tests`: **1231 tests, OK** (1 skipped). The baseline before the fixes was
  1122, all OK.
- `node tests/js/run.js`: **418 passed, 0 failed**.
- Every `tests/js/*.js`: all pass (32 files, including `security_audit.js` with 42 checks). There are no reporting failures.

## 8. Phase 2 (2026-11-24)

**Scope**

- **Reporting:** `reports_*`, `report_*`, `evidence_service`, `cvss`, the export pipeline (HTML, PDF via the WebKit/WebView2 print helper, DOCX, XLSX, SARIF, CSV), the importers, both sanitisers, the preview sandbox and CSP, the AI consent flow, and the report MCP tools.
- **Terminal and WSL:** `terminal_service.py` (PTY/ConPTY, elevation, recording, jobs, redaction), `wsl_kali_service.py`, `wsl_api.py` and the PowerShell flow.
- **CVE:** `cve_service`, `cve_index`, `cve_index_updater`.
- **Targets UI.**
- **Chain diagrams:** `flow_*` and `flows_api`.
- **The 112 MCP tools.**
- **The Reporting QA leads.**
- **Dependencies.**

The storage files (`common_db`, `db_driver`, `crypto_store`, the encryption parts of `security_service`, `backup_restore`, `health_check`) were audited only; findings went to the storage agent.

**Method**

- Code reading.
- A differential sanitiser test: 38 XSS and mXSS payloads through both `RC.sanitizeHtml` (JS) and `reports_service.sanitize_html` (Python).
- An AST walk of every `@server.tool`/`resource`/`prompt` against `ai_service.permission_key`.
- Bash round-trip fuzzing of the chain-diagram shell quoters, plus cmd/PowerShell refusal checks.
- OSV against `Requirements.json` and every package the venv actually imports.
- A bridge enumeration that mirrors pywebview's own walk.
- A live re-check of the navigation guard and the confirm dialog on a sandbox copy, on Xvfb `:97`.

**Verified, no finding**

- **Sanitisers:** no dangerous output from either side. Three cosmetic differences: Python adds `alt=""`, and the two handle text left over from a stray `noscript` differently.
- **Report preview:** a `sandbox=""` iframe with CSP `default-src 'none'`. The exported HTML carries the same CSP.
- **PDF helper:**
  - WebKit: JavaScript off, plugins, file access and developer tools off, an ephemeral context, and every navigation except the `about:` document refused.
  - WebView2: script, host objects and web messages off.
- **XLSX:** never writes formulas. Report CSV/SARIF go through `csv_safe`.
- **Importers:** size and count limits; `reportsIO.apply_import` only accepts picked paths; staged uploads are confined to their own folder.
- **WSL:**
  - `ps_literal` doubles typographic single quotes and refuses control characters.
  - Every network value goes through `validate_network` and comes out canonical.
  - Distro writes use argv with `"$1"`.
- **CVE updater:** GitHub asset SHA-256 and size checks, zip and xz bomb limits, fixed hosts, and the opt-in gate.
- **MCP:**
  - All 112 tools resolve to a permission key and call `_check`, which checks the lock and then `authorize`.
  - Resources go through their tools.
  - Prompts are static.
  - Defaults: 90 Allow, 21 Deny (every shell, delete and secret tool), 1 Ask.
- **Chain diagrams:**
  - Quoting: 0 of 48 bash round-trips leaked.
  - cmd.exe refuses `& % ^ | < > " ! ( )`.
  - PowerShell escapes the typographic double quotes inside `"..."` and doubles the typographic single quotes inside `'...'`.
  - bubblewrap: `--unshare-net` by default, tmpfs over Data, Logs, Backups and the home secret folders.
  - Unreviewed and imported chains always ask first; `${raw:}` is refused for unreviewed chains.

**Re-verification of the phase 1 and 1b fixes** (many files changed after them)

- `tests/test_security_audit.py` (53 tests) and `tests/js/security_audit.js` (77 checks) cover SA-01 to SA-36 and all pass against the current tree.
- Bridge enumeration: 505 published methods. No `bind`. Open while locked: only `window`, `theme`, `focusMode`, the `security` lock/unlock calls, `update.status`/`launch_ready`, and the terminal status calls (`terminal.read` is gone).
- Live check on `:97`: `location.href`, a link click, `form.submit()` and `window.open` did not navigate, and the native guard logged the submit. In the confirm dialog, focus started on Cancel for a dangerous action, two Tabs wrapped back to it, and Esc closed it.

**Dependencies (final)**

- `pywebview` 6.2.1, `mcp` 2.2.0, `python-docx` 1.2.0, `fpdf2` 2.8.8, `starlette` 1.10.0, `python-multipart` 0.0.34, `anyio` 4.16.0, `pillow` 13.0.0, `httpx2`/`httpcore2` 2.16.2, `opentelemetry-api` 1.45.2 and `keyring` 25.7.0: no OSV advisories.
- `cryptography` 48.0.1: 3 advisories, all in PKCS#7 and X.509 code paths LOYA does not use (SA-17).
- `sqlcipher3` 0.6.5 and `argon2-cffi` 25.1.0 are installed with no advisories, but are not yet pinned in `Requirements.json`; the storage agent was asked to pin them, and OSV has to be re-run then.

**Hand-off to the storage agent** (sent)

- the SA-12 KDF, verifier and PIN-length points;
- open new DB files 0600;
- no plaintext `-wal`/`-shm` or snapshot left after lock;
- keep `_safe_extract_backup` and the audit redaction;
- SA-38.

**Final status:** 39 findings (SA-01 to SA-39 plus SA-03b; SA-31 was not used). By severity: 3 High, 15 Medium, 20 Low, 1 Info.

- **Fixed:** 37 (SA-12 and SA-38 after the storage phase 2 landed).
- **Open:** 1. SA-37 (Low) stays open by decision: LOYA's own import format wins.
- **Accepted:** 1 (SA-16).
- SA-23 is fixed in code; the real Windows check is pending in the Windows E2E.

**Residual risks added in phase 2**

- On Windows, script nodes in chain diagrams run with no OS sandbox. They are confirmed on every run when the chain is AI-made.
- LOYA's own CSV round-trip exports are not formula-safe (SA-37).
- On Linux, system site-packages remain visible to the venv. Minimum versions cover what LOYA imports, not unrelated system packages.

**Phase 2 test results (2026-11-24)**

- `.venv_linux/bin/python3 -m unittest discover -s tests`: 1724 tests, 65 errors, 1 skipped.
  - All 65 errors are the same `AttributeError: ext_agents_service has no attribute '_pin_fernet'`, in `test_cve_index` and `test_cve_intel`. The storage rebuild in progress replaced `_pin_fernet` with `Cores.secret_store`, and those CVE tests still patch the old name. The CVE agent has been told. These errors are not caused by any audit change.
  - All 60 `test_security_audit` tests pass, and so do all suites touched by this audit: reports, terminal redaction, MCP, AI, ext agents and import.
- `node tests/js/run.js`: 418 passed, 0 failed.
- All 33 `tests/js/*.js` files: 0 failed, including `security_audit.js` with 77 checks.
- The version is still 1.0.0. Nothing is committed.

**After SA-39 (2026-11-24)**

- Full suite: 1726 tests, 7 failures, 0 errors. The 65 CVE errors are gone (the CVE agent fixed the `_pin_fernet` patching).
- All 7 failures are in the Chains team's `test_flow_scripts` (6: timeout/kill-tree/isolation tests) and `test_flow_service` (1: `test_the_api_registers_flows`). Both modules pass on their own (49 and 42 tests OK), so these depend on load or test order and are not related to the audit.
- `test_security_audit` passes (53 tests). `node tests/js/run.js`: 418 passed. `security_audit.js`: 77 passed.

## 9. Final re-verification after the storage phase 2 (2026-11-24)

**SA-12, PIN and keys**
- The PBKDF2 `pin_hash` is gone. The PIN is checked by unwrapping the Argon2id key file `Data/Note_LOYA_V1.key` (m=64 MiB, t=3, p=4) with an AES-GCM tag check (`security_service._check_pin`). No verifier is left in `settings.json` to attack offline.
- KDF parameters read from a key file, including one inside a backup header, are bounds-checked (`crypto_store.validate_kdf`, `ARGON2_BOUNDS`, scrypt memory cap). A crafted backup therefore cannot force a huge KDF.
- `ENC_MIN_PIN=6` is enforced when encryption is on.
- No PIN is kept in memory. The data key is wiped at lock, after the WAL checkpoint (`_forget_session`).
- SQLCipher 4.20.0 community, built on SQLite 3.54.1. The WAL is encrypted and `temp_store=MEMORY` is set on keyed connections.

**No plaintext after lock or kill** (live test in a scratch `Data/`)
- Setup: turned encryption on, then wrote a note, a target password, Quick Space and a terminal audit event, each carrying a marker. This was done once with `lock_now` at the end and once with SIGKILL while unlocked.
- Result: `Data/` held only `Note_LOYA_V1.db`, `Note_LOYA_V1.key`, `settings.json` and `security_audit.jsonl`, all 0600. None of the markers was found by `grep -a` in any file.
- So the JSON stores (`doc_store`), the API keys (`secret_store`) and the terminal/tool audit events (encrypted `AuditEvents`) all stay inside the SQLCipher DB.
- The lifecycle events in `security_audit.jsonl` hold no command text.
- One stray item: the test's pre-encryption `.loyabak` landed in the repository's `Backups/`, because the backup folder follows the app root, not `Data/`. I deleted it.

**SA-38**
- `restore_data_backup` sets every `ChainGraphs` row back to `ai_reviewed=0` after any restore.

**`.loyabak`**
- Format: magic, a bounded header (≤64 KiB) with a validated key file, then an AES-256-GCM chunk stream. Each chunk nonce encodes its index and a final flag, so tampering, reordering and truncation are all detected.
- Decryption happens into a 0700 temp folder, and the zip inside it holds the still-encrypted DB and stores. `_safe_extract_backup` still runs on every restore.
- An encrypted backup is refused when encryption is off, and a plain one is refused when it is on.
- The live DB's `-wal`/`-shm` files are removed before the DB is replaced. A backup made under another PIN needs that PIN.

**Permissions (H-02)**
- `common_db.data_dir()` creates `Data/` 0700, and new stores and attachments are opened 0600.
- In the user's real `Data/`, a few older files are still 664/775 under the 0700 top folder. Other users cannot reach them, and the startup pass (SA-04) tightens them on the next start.

**Audit log split**
- `AUDIT_PLAINTEXT_EVENTS` (unlock, lock, PIN, encryption toggles and similar) go to `security_audit.jsonl`. With encryption on, everything else goes to the encrypted `AuditEvents` table.
- Redaction (SA-26) happens before either is written.
- Still open on the storage side: a hash chain over the audit log (`storage_migration_plan.md` section 10). This is a recommendation, not a finding.

**New modules reviewed**
- `secret_store`: works only while encryption is on and the app is unlocked, and never falls back to plaintext.
- `doc_store`: while locked, writes fail closed.
- `loyabak`: described above.
- `storage_migration`: work files go to `Data/.migrate`, mode 0700/0600, are shredded and unlinked when done, and are cleaned up by `recover()` after a crash.
- I did not edit any of them.

**OSV, final pins**
- `sqlcipher3==0.6.5`, `argon2-cffi==25.1.0` and `argon2-cffi-bindings==25.1.0`: no advisories. Their wheel SHA-256 values are recorded in `Requirements.json`.
- Every other pin: no advisories, except `cryptography` 48.0.1 (3 advisories in code paths LOYA does not use; SA-17).

**Full suite**
- `.venv_linux/bin/python3 -m unittest discover -s tests`: **1772 tests, OK** (1 skipped).
- All 40 `tests/js/*.js` files: 0 failed, including `run.js` (418) and `security_audit.js` (77).
- `test_security_audit`: 53 OK.
- The version is still 1.0.0. Nothing is committed.

**Final status:** 39 findings. 37 fixed, 1 accepted (SA-16), 1 open by decision (SA-37). SA-23 and SA-39 still need confirming in the Windows E2E.
