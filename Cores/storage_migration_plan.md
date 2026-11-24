# Storage and encryption rebuild: as built (phase 2)

Phase 1 added `Cores/crypto_store.py` (Argon2id envelope key file and AES-256-GCM streams) and `Cores/db_driver.py` (the
SQLite/SQLCipher shim). Phase 2 wires them into the app. The version stays 1.0.0. Everything here works on Windows and Linux.
Windows-only paths are gated and listed in section 9.

## 1. Default mode: what "encryption at rest off" means

**Decision: with encryption at rest off, the DB is a plain SQLite file, as before. With it on, the DB is SQLCipher, keyed by a
random data key (DEK) that only a PIN can unwrap. There is no hidden keyring-held key for users without a PIN.**

Why we rejected always-encrypted with the DEK in the OS keyring when no PIN is set:
- **Lock-out risk.** If the keyring entry is lost, the data is gone for a user who never chose encryption. This happens on a
  Windows profile reset, an admin password reset (DPAPI), a GNOME keyring reset or a new Linux install. It also happens when
  Secret Service is missing: headless sessions, root sessions on Kali, WSL. Without a PIN there is no recovery path at all.
- **Little protection gained.** The keyring unlocks with the same OS session that can already read `Data/`. It helps against
  someone who has only the disk, but full-disk encryption already covers that case, and covers it better.
- **Machine-bound backups.** Backups would only restore on the same machine and the same OS account.
- **Not always available.** `keyring` is an optional dependency that RunNote.py does not install.

What every user gets regardless of mode:
- `Data/` is 0700 and its files are 0600 (owner-only ACL on Windows).
- JSON stores are consolidated behind one seam (`Cores/doc_store.py`).
- A PIN, once set, is an Argon2id key file. There is no PBKDF2 hash in settings.json any more (SA-12).
- Settings show the mode honestly and offer to turn encryption on, with a 6+ character PIN.

## 2. Files

| File | Role |
|---|---|
| `Cores/crypto_store.py` | Argon2id (scrypt fallback) key file: create, unwrap, rewrap, KDF upgrade. AES-256-GCM chunked streams. Atomic writes. |
| `Cores/db_driver.py` | The only SQLite opener. One driver per process (sqlcipher3 when installed). Raw-key `PRAGMA key`. Connection tracking. Export, migration and backup helpers. |
| `Cores/common_db.py` | `connect()` / `connection()` with the session key. `set_session_key` / `clear_session_key` / `session_key`. `encryption_configured()` reads settings.json (cached on mtime). `at_rest_locked()`. `wait_idle()`. `key_path()`. Schema v18 adds AppDocs, Secrets and AuditEvents. `Data/` is created 0700. |
| `Cores/doc_store.py` | JSON stores: plain files when off, AppDocs rows when on. Path-based API: `read_json`, `write_json`, `exists`, `mtime`, `signature`, `remove`, `remove_dir`. |
| `Cores/secret_store.py` | API keys in the Secrets table (replaces `ext_agents_service._pin_fernet`). |
| `Cores/loyabak.py` | `.loyabak` encrypted backup container. |
| `Cores/storage_migration.py` | Step-journalled `enable()` / `disable()` / `recover()`. `legacy_fernet()` for v1. `make_loyabak()`. |
| `Cores/Services/security_service.py` | PIN as key file. Lock/unlock, PIN change, encryption toggle and reset rebuilt around the DEK. KDF upgrade. Audit-log split. |
| `Cores/Update/backup_restore.py` | `.loyabak` backups. Encryption-aware restore. ChainGraphs set back to unreviewed after any restore. |
| `Cores/Update/health_check.py` | An encrypted DB is "locked", never "corrupt". The target stores are not recreated as files. |

## 3. Every former sqlite3 opener, now going through `common_db.connect`/`connection`

Switched in one change, to avoid two SQLite libraries on one file in one process.
`with sqlite3.connect(p) as con` became `with common_db.connection(p) as con`, which commits, rolls back on error and always
closes. `sqlite3.Row`, `IntegrityError`, `Error` and `Binary` became the `db_driver` classes.

- `Cores/note_refs.py`
- `Cores/recycle_bin.py`
- `Cores/Services/commands_service.py`
- `Cores/Services/cve_service.py` (`_db`)
- `Cores/Services/dashboard_service.py`
- `Cores/Services/evidence_service.py`
- `Cores/Services/flow_store.py` (Chains team agreed)
- `Cores/Services/notes_service.py` (including `export_db`, which still writes a plain export file on purpose)
- `Cores/Services/playbooks_service.py`
- `Cores/Services/report_autogen.py`
- `Cores/Services/report_schedule.py`
- `Cores/Services/reports_service.py`
- `Cores/Services/search_service.py`
- `Cores/Services/settings_service.py`
- `Cores/Services/targets_service.py`
- `Cores/Services/templates_service.py`
- `Cores/Services/terminal_service.py`
- `Cores/Update/health_check.py`

Left alone on purpose:
- `Cores/Services/cve_index.py`: its own read-only file `Data/cve_index/cve_index.sqlite`, which holds public data.

## 4. JSON stores moved into the encrypted DB (`AppDocs`, one row per file)

`doc_store.DOC_PATTERNS` lists them:
- `profiles.json`
- `Targets.json`, `Targes.json`, `target_values.json`, and the same files under `Profiles/<id>/`
- `notes_meta.json`, `notes_templates.json`, `note_draft_recovery.json`
- `terminal_sessions.json`
- `QuicSpace.json`
- `ai_sessions/*.json`
- `search_index/index.json`
- `saved_searches.json`, `recent_searches.json`, `palette_recent.json`
- `tag_colors.json`
- `external_agents/usage.json`, `external_agents/sessions.json`

The seams that now route through doc_store:
- The `_read_json` / `_write_json` helpers in `target_profiles`, `recycle_bin`, `targets_service`, `search_service`,
  `settings_service`, `ai_sessions_service`, `quick_space_service`, `semantic_search_service` and `notes_service`.
- `settings_lock.read_json` / `write_json`, so `terminal_sessions` and `reports_service` follow too.
- Direct readers: `dashboard_service` (targets count, mtime, key order), `evidence_service.live_target_name`,
  `report_autogen._profile_targets`, the `targets_service.store_signature` / `_load_values` mtime watchers,
  `search_service._safe_mtime` and `ai_index_service._signature`.
- Deletes: profile delete, AI session delete, draft clear.
- `ext_agents_service` usage and session map.

**Deviation from the phase 1 plan:** one generic `AppDocs(name, data, mtime, size)` table replaces the per-store normalised
tables (Profiles, Targets, TargetValues, TerminalSessions, QuickSpaceItems, AiSessions, AiMessages, SearchIndexDocs).
- Every consumer keeps its exact JSON shape, so return types (targets lists, MCP tools) are unchanged.
- The two modes share one code path.
- Splitting target credentials into a separate table is deferred. They are encrypted with the DB, and masking for AI and MCP
  is already done in `mcp_app_tools`.

**Files encrypted in place** (same name, `LOYAENC` stream):
- `Data/Attachments/**`. `notes_service._write_attachment` encrypts and `attachment_bytes` decrypts. The notes view shows them
  through the new bridge call `notes.attachment_view`, which `notes_pro.js` reaches via an `error` capture listener. Saving
  always restores the `file://` URL (`notesProAttachmentsForSave`). `reports_service._note_image_resolver` decrypts too.
- `Data/job_output/*` (terminal spill).

## 5. API keys

- `ext_agents_service` and `cve_service` store keys in the keyring first. Otherwise they use `secret_store` (names
  `ext_agent:<provider>` and `cve:nvd`). If neither is available, the key lives for the session only.
- `key_enc` stays empty. Old v1 Fernet tokens are adopted once at the legacy unlock: `adopt_legacy_keys` / `adopt_legacy_key`,
  called from `security_service._adopt_legacy_keys`.
- Turning encryption off drops the Secrets rows. The keys must be entered again; we do not write them into a plain DB.

## 6. Security audit log

- Security lifecycle events stay in the plaintext `security_audit.jsonl`: unlock, lock, PIN, encryption, migration, audit
  expiry, MCP pause, key saved/removed (`AUDIT_PLAINTEXT_EVENTS`). It has to be readable while locked and record wrong PINs
  before any key exists.
- With encryption on, every other event goes to the encrypted `AuditEvents` table: terminal commands, AI/agent tool calls,
  chain runs. These name hosts and commands.
- While locked, such an event is written to the file with its detail withheld.
- Enabling encryption moves existing content lines into the DB. Disabling merges them back into the file.
- Redaction stays at the single entry point, `log_audit_event`.
- A hash chain for tamper evidence is still open (section 10).

## 7. Lock / unlock / PIN (security_service)

- **PIN set:** `Data/Note_LOYA_V1.key` exists. `pin_is_set` is "key file exists, or a legacy v1 hash is present".
- **Unlock:**
  - Lockout policy as before.
  - `crypto_store.unwrap`; a wrong PIN counts as a failure.
  - A v1 hash is replaced by a fresh key file (SA-12).
  - KDF upgrade (`_upgrade_kdf`).
  - `storage_migration.recover()`.
  - For a v1 `.db.enc`, the one-time migration runs.
  - `_open_encrypted` checks that the DEK really opens the DB, then sets it as the session key.
  - With app lock only, the DEK is wiped straight away.
- **Lock:** set the DB lock, then pause MCP, then suspend agents and flows, then checkpoint the WAL, then wait for open
  connections, then wipe the key. There is no file encryption step: the file never existed in plaintext.
- **Exit** (`encrypt_on_exit`, name kept): checkpoint and wipe. A kill at any moment leaves only ciphertext. This fixes the
  Reporting-QA finding of a plaintext DB left beside the `.enc`.
- **PIN change:** `crypto_store.rewrap` (atomic). The data key and the data are untouched.
- **Encryption toggle:** needs the typed PIN (S20). Enabling needs 6+ characters (`ENC_MIN_PIN`); app lock alone keeps 4.
- **reset_pin:** refused while encryption is on, because the data would become unreadable.

## 8. Migration (enable), step by step

`Data/storage_migration.json` journals each step. Nothing original changes before `committing`.

1. **prepared.** Check that sqlcipher3 is present and there is about 3x the data size in free disk. Take a consistent plain
   copy into `Data/.migrate/plain.db` (0700 folder, 0600 file):
   - from the backup API on a plain DB;
   - from the v1 Fernet decrypt; or
   - from the newer plaintext DB that a v1 crash left behind.
2. **backed_up.** Write `Backups/pre-encryption-<stamp>.loyabak`, verified chunk by chunk. It holds the plaintext DB copy,
   the stores and attachments, and excludes the CVE index.
3. **exported.** `db_driver.migrate_plain_to_encrypted`, then `cipher_integrity_check`, `integrity_check`, FTS5
   integrity-check, row counts, `user_version` and `application_id`.
4. **docs_imported.** Every JSON store goes into AppDocs and audit content events into AuditEvents, in one transaction,
   verified by read-back.
5. **files_ready.** Attachments and spill files are encrypted into `.migrate/files/`, each verified by a decrypt round-trip.
6. **committing.** Repeatable without the key:
   - remove the old `-wal`/`-shm`;
   - `os.replace` `enc.db` over the DB;
   - replace the files;
   - set `enc_enabled=true, enc_version=2`;
   - remove content lines from the audit log;
   - journal `committed`.
7. **finish.** Zero-fill and unlink the plaintext stores, the legacy `.enc` and `.migrate/`, then clear the journal.

**Rollback / resume** (`recover()`, run at startup and before every migration):
- A journal before `committing`, or a `.migrate/` with no journal: delete the work folder. The originals were never touched.
- `committing`: finish the renames and the settings flip.
- `committed`: finish the cleanup.

`disable()` runs the same way in reverse:
- `export_plain`, and AppDocs written back to files.
- Secrets dropped, and VACUUM so their pages do not survive.
- Files decrypted.
- Audit rows merged into the file.

## 9. Windows checklist (not yet run on Windows; do before release)

- [ ] `pip install` on Windows Python 3.10-3.14 gets the `sqlcipher3-0.6.5-cpXY-win_amd64` wheel and
  `argon2-cffi-bindings` abi3 (all exist on PyPI). No compiler is needed. Check that the bundled OpenSSL loads and Defender
  does not quarantine the `.pyd`.
- [ ] Enable encryption with notes open: `_exclusive()` sets the lock and calls `wait_idle(10)` before `os.replace`. Watch for
  `PermissionError` from any handle that is still open (WebView2 does not open the DB; check the Mini window and the MCP
  thread).
- [ ] `crypto_store._replace` retries `PermissionError` for about 10 s. Test with Defender real-time scanning on.
- [ ] The `-wal`/`-shm` removal before the swap succeeds (no other process maps the DB). Single-instance guard on.
- [ ] Notes with image attachments show (data URL path in WebView2). Annotate, save, reopen. The stored HTML keeps
  `file:///C:/...`.
- [ ] The kill test: Task Manager, End task while unlocked. Data\ contains only the DB (SQLCipher), the `.key`, settings and
  the audit log.
- [ ] `harden_data_permissions` ACL plus files created by `os.open(..., 0o600)` (the mode is ignored on Windows; the ACL is what
  protects them).
- [ ] The `.loyabak` restore to another machine with the old PIN.
- [ ] Long paths: `.migrate\files\Attachments\<id>\<aid>.<ext>` stays well under MAX_PATH for a normal install path.
- [ ] `resetPIN.py` refuses while encrypted.

## 10. Open items

- A tamper-evident hash chain for `security_audit.jsonl`.
- Done since: the plain SQLite notes export needs the PIN typed again with encryption on. It shows a "NOT encrypted"
  warning and is audited as `plain_export` (`security_service.plain_export_allowed`, `NotesExport.export_db(pin)`,
  `importExport.export_needs_pin`).
- Done since: restoring a `.loyabak` made under another PIN or key asks for that PIN (`backup_restore.backup_needs_pin`,
  `backup.needs_pin` / `importExport.import_needs_pin`, `setBackupPin` in settings.js). A wrong PIN shows "Wrong PIN for
  this backup.".
- Done since: a restore never silently brings back an old PIN. When the backup wraps this session's data key (the PIN changed
  after the backup), the live key file is kept. When it wraps another key, the current PIN (asked after the backup's PIN,
  checked before anything is written) re-wraps that key; skipping shows "This backup uses the PIN that was set when it was
  made. After restore, unlock with that PIN." (`restore_data_backup(current_pin=...)`).
- Done since: a restore never rolls back the audit log. `security_audit.jsonl` keeps every live entry and only gains the
  backup's missing ones (`security_service.merge_audit_file`); the live `AuditEvents` rows are copied into the restored DB
  (`merge_audit_rows`); the restore itself is audited as `backup_restored` (plaintext event).
- Done since: `common_db.backups_dir()` can be overridden (tests/_isolate.py points it into the scratch dir). A moved
  `Data/` uses `Data/_backups`, so scratch runs never write into the app's `Backups/`.
- Other plaintext exports (JSON, CSV and Markdown notes, commands, targets, Export All) do not ask for the PIN yet. Export
  All copies the files as they are on disk, so with encryption on it holds ciphertext plus the PIN-wrapped key file.
- Optional `PRAGMA cipher_memory_security=ON`: measure the cost first.
- Split target credentials into their own table (masking for AI and MCP already exists).

## 11. Tests

- `tests/test_crypto_store.py` (31) and `tests/test_db_driver.py` (20).
- `tests/test_security_lock.py`: rewritten for the DEK design. Covers lock and unlock, a missing DB never recreated plain,
  kill while unlocked, PIN change, PIN length, the SA-12 hash upgrade, KDF upgrade, the v1 `.db.enc` migration with the API
  key adopted, plaintext newer than the `.enc`, rollback before commit, a crash during commit finished at the next start,
  disable and reset.
- `tests/test_storage_encryption.py`: doc_store in both modes, targets round-trip, Secrets, legacy key adoption, attachments,
  spill, health check, `.loyabak` backup and restore (CVE index excluded, chains unreviewed), a backup made under another PIN,
  a plain backup refused while encrypted, tamper detection, and the audit-log split.
- `tests/_isolate.py` also isolates `health_check.settings_path` and the session key, so no test ever reads the real
  settings.json.
