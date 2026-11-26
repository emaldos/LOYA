"""Export my work: the shareable content of this install as one file, built from an ALLOWLIST.

The file moves work between installs and people, so it holds only what the user made (notes, commands, Quick Run favourites,
Quick Space, targets and profiles, reports, chains) and never machine-local state or secrets. Anything not named CONTENT in
CLASSIFICATION below is left out, so a new table or file stays out of the export until someone classifies it.

Format "loya-work-export" v2: a zip with
    manifest.json            format, version, app version, counts per kind, what was included, the entry list
    content.db               a fresh plain SQLite file holding only the CONTENT tables (no Secrets, AuditEvents or AppDocs)
    docs/<rel>.json          the content JSON stores, read through doc_store (so encryption at rest works), as plain JSON
    quick_run.json           Quick Run favourites, each with the command it points at (ids change on import)
    files/Attachments/<note id>/<name>, files/chain/<name>.html    plain bytes
    settings.json            only with include_settings: the PORTABLE_SETTINGS subset
    ai_sessions/<name>.json  only with include_ai_chats
With a password the zip is wrapped in a .loyabak container (Cores/loyabak.py, header kind "work", protect "password"): a fresh
data key, wrapped under the password with Argon2id (crypto_store.wrap_dek), encrypts the zip with AES-256-GCM. Extension
.loyawork. Encryption at rest on: the content is read with the session key and written out readable (or under the password);
a readable copy without a password needs the PIN typed now (security_service.plain_export_allowed, audited).
"""
import json
import os
import re
import shutil
import tempfile
import time
import zipfile

from Cores import common_db as _common_db
from Cores import db_driver as _drv
from Cores import doc_store as _doc_store

FORMAT = "loya-work-export"
FORMAT_VERSION = 2
PROTECTED_EXT = ".loyawork"
CONTENT, MACHINE, REBUILDABLE = "content", "machine_secret", "rebuildable"

# kind -> class. "db:<table>", "doc:<Data-relative JSON store>", "file:<Data-relative file>", "dir:<Data-relative folder>".
# opt_in: off by default; opt_out: on by default.
CLASSIFICATION = {
    # ---- content tables
    "db:Notes": {"class": CONTENT, "kind": "notes"},
    "db:NotesHistory": {"class": CONTENT, "kind": "note_versions"},
    "db:CommandsNotes": {"class": CONTENT, "kind": "command_notes"},
    "db:Commands": {"class": CONTENT, "kind": "commands"},
    "db:CommandsHistory": {"class": CONTENT, "kind": "command_versions"},
    "db:CommandsNotesHistory": {"class": CONTENT, "kind": "command_versions"},
    "db:Playbooks": {"class": CONTENT, "kind": "chains"},
    "db:PlaybookSteps": {"class": CONTENT, "kind": "chains"},
    "db:ChainGraphs": {"class": CONTENT, "kind": "chains"},
    "db:ChainRuns": {"class": CONTENT, "kind": "chain_runs", "opt_out": "run_history", "note": "run variables, approvals and job keys stripped"},
    "db:ChainRunLogs": {"class": CONTENT, "kind": "chain_runs", "opt_out": "run_history"},
    "db:Reports": {"class": CONTENT, "kind": "reports"},
    "db:ReportSections": {"class": CONTENT, "kind": "reports"},
    "db:ReportFindings": {"class": CONTENT, "kind": "reports"},
    "db:ReportVersions": {"class": CONTENT, "kind": "reports"},
    "db:ReportTargets": {"class": CONTENT, "kind": "reports"},
    "db:ReportFindingTargets": {"class": CONTENT, "kind": "reports"},
    "db:ReportAssets": {"class": CONTENT, "kind": "reports"},
    "db:ReportEvidence": {"class": CONTENT, "kind": "evidence"},
    "db:ReportEvidenceEvents": {"class": CONTENT, "kind": "evidence"},
    "db:ReportTemplates": {"class": CONTENT, "kind": "report_templates"},
    "db:FindingLibrary": {"class": CONTENT, "kind": "findings_library"},
    # ---- content JSON stores
    "doc:profiles.json": {"class": CONTENT, "kind": "target_profiles"},
    "doc:Targets.json": {"class": CONTENT, "kind": "targets"},
    "doc:Targes.json": {"class": CONTENT, "kind": "targets", "note": "old misspelt name"},
    "doc:target_values.json": {"class": CONTENT, "kind": "target_values"},
    "doc:Profiles/*/Targets.json": {"class": CONTENT, "kind": "targets"},
    "doc:Profiles/*/target_values.json": {"class": CONTENT, "kind": "target_values"},
    "doc:notes_meta.json": {"class": CONTENT, "kind": "notes_meta"},
    "doc:notes_templates.json": {"class": CONTENT, "kind": "note_templates"},
    "doc:QuicSpace.json": {"class": CONTENT, "kind": "quick_space"},
    "doc:tag_colors.json": {"class": CONTENT, "kind": "tag_colors"},
    "doc:saved_searches.json": {"class": CONTENT, "kind": "saved_searches"},
    "doc:ai_sessions/*.json": {"class": CONTENT, "kind": "ai_chats", "opt_in": "ai_chats", "note": "can hold pasted secrets and tool output"},
    "settings:mini_window.favorites": {"class": CONTENT, "kind": "quick_run", "note": "Quick Run favourites, re-keyed by command"},
    "settings:portable": {"class": CONTENT, "kind": "settings", "opt_in": "settings", "note": "PORTABLE_SETTINGS subset only"},
    # ---- content files
    "dir:Attachments": {"class": CONTENT, "kind": "attachments", "note": "per-note folders; _pending is never exported"},
    "dir:chain": {"class": CONTENT, "kind": "chain_files", "note": "*.html files saved by the user"},
    # ---- machine-local state and secrets: never exported
    "db:Secrets": {"class": MACHINE, "note": "stored API keys"},
    "db:AuditEvents": {"class": MACHINE, "note": "security audit log"},
    "db:TerminalJobs": {"class": MACHINE, "note": "running and finished terminal jobs"},
    "db:CommandRuns": {"class": MACHINE, "note": "run log with target snapshots"},
    "db:RecycleBin": {"class": MACHINE, "note": "deleted items of this install"},
    "file:Note_LOYA_V1.key": {"class": MACHINE, "note": "PIN-wrapped data key"},
    "file:settings.json": {"class": MACHINE, "note": "whole file: PIN data, API key hints, paths, shells, window geometry"},
    "file:security_audit.jsonl": {"class": MACHINE},
    "file:deps_state.json": {"class": MACHINE},
    "file:loya.pid": {"class": MACHINE},
    "doc:terminal_sessions.json": {"class": MACHINE, "note": "terminal sessions and scrollback"},
    "doc:note_draft_recovery.json": {"class": MACHINE},
    "doc:recent_searches.json": {"class": MACHINE},
    "doc:palette_recent.json": {"class": MACHINE},
    "dir:external_agents": {"class": MACHINE, "note": "CLI connection tokens, agent configs, usage, sessions, cli_workspace"},
    "dir:job_output": {"class": MACHINE},
    "dir:_backups": {"class": MACHINE, "note": "backups"},
    "keyring": {"class": MACHINE, "note": "OS keyring entries (API keys, backup password) are never read"},
    # ---- rebuildable: never exported
    "db:CveRecords": {"class": REBUILDABLE}, "db:CveKev": {"class": REBUILDABLE}, "db:CveMeta": {"class": REBUILDABLE},
    "db:AppDocs": {"class": REBUILDABLE, "note": "its content docs go out as docs/ JSON"},
    "db:SchemaMigrations": {"class": REBUILDABLE}, "db:sqlite_sequence": {"class": REBUILDABLE},
    "dir:search_index": {"class": REBUILDABLE}, "dir:cve_index": {"class": REBUILDABLE}, "dir:.migrate": {"class": REBUILDABLE},
}

CONTENT_TABLES = tuple(k[3:] for k, v in CLASSIFICATION.items() if k.startswith("db:") and v["class"] == CONTENT)
RUN_TABLES = ("ChainRuns", "ChainRunLogs")
CONTENT_DOC_PATTERNS = tuple(k[4:] for k, v in CLASSIFICATION.items() if k.startswith("doc:") and v["class"] == CONTENT and not v.get("opt_in"))
AI_CHAT_PATTERN = "ai_sessions/*.json"

# settings.json keys that may travel (top-level section -> allowed sub-keys, or None for every sub-key that passes the filter).
PORTABLE_SETTINGS = {
    "appearance": None,
    "extensions": ("ai_permissions", "ai_terminal_approval", "ai_enabled", "ai_panel_mode", "ai_width", "ai_panel_height"),
    "cve": None,
    "dashboard_layouts": None,
}
_FORBIDDEN_KEY_RX = re.compile(r"key|token|secret|passw|pin|path|shell|dir|geometry|window|consent|cookie|auth|cred", re.I)
_KDF = None  # tests set a fast KDF here


class ExportError(ValueError):
    pass


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _app_version():
    try:
        from Cores.Update import update_service as _up
        ident = _up.get_app_identity() or {}
        return str(ident.get("display_version") or ident.get("version") or "")
    except Exception:
        return ""


def _min_len():
    try:
        from Cores import backup_password as _bp
        return int(_bp.MIN_LEN)
    except Exception:
        return 8


def _match(rel, pat):
    if "*" not in pat:
        return rel == pat
    head, tail = pat.split("*", 1)
    mid = rel[len(head):len(rel) - len(tail)] if len(rel) >= len(head) + len(tail) else ""
    return rel.startswith(head) and rel.endswith(tail) and bool(mid) and "/" not in mid and mid not in (".", "..")


def classify(rel):
    """The CLASSIFICATION entry for a Data-relative path ('doc:', 'file:' or 'dir:' rule), or None (= not exported)."""
    rel = str(rel or "").replace("\\", "/").strip("/")
    for k, v in CLASSIFICATION.items():
        if k.startswith(("doc:", "file:")) and _match(rel, k.split(":", 1)[1]):
            return v
    top = rel.split("/", 1)[0]
    return CLASSIFICATION.get("dir:" + top)


def _clean_value(v):
    if isinstance(v, dict):
        return {k: _clean_value(x) for k, x in v.items() if not _FORBIDDEN_KEY_RX.search(str(k))}
    if isinstance(v, list):
        return [_clean_value(x) for x in v]
    return v


def portable_settings(settings):
    """The PORTABLE_SETTINGS subset of a settings dict: no PIN data, keys, tokens, paths, shells or window geometry."""
    out = {}
    if not isinstance(settings, dict):
        return out
    for sec, allowed in PORTABLE_SETTINGS.items():
        val = settings.get(sec)
        if not isinstance(val, dict):
            continue
        if allowed is not None:
            val = {k: val[k] for k in allowed if k in val}
        val = _clean_value(val)
        if sec == "cve":
            for k in ("key_hint", "key_store", "key_enc", "consent_ts", "online"):
                val.pop(k, None)
        if val:
            out[sec] = val
    return out


def _settings_path():
    from Cores.Update import health_check as _hc
    return _hc.settings_path()


def _read_settings():
    try:
        with open(_settings_path(), "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


# ---------------------------------------------------------------- DB
def strip_run_data(raw, row):
    """ChainRuns.data without anything a real run could be seeded from (the chain_history import rules: vars, approval,
    notices, job keys go). Returns the cleaned JSON text, or None when the run cannot be cleaned (it is then left out)."""
    from Cores.Services import chain_history as _hist
    try:
        status = json.loads(raw or "{}")
    except ValueError:
        status = {}
    if not isinstance(status, dict):
        status = {}
    run_id, playbook_id, chain_name, mode, state, source, target, started, ended = row
    item = {"run_id": run_id, "chain_name": chain_name, "mode": mode, "state": state, "source": source, "target": target,
            "started_at": started, "ended_at": ended, "status": status, "node_titles": status.get("node_titles"),
            "node_types": status.get("node_types")}
    clean, problem = _hist._clean_run(item, 0)
    if problem:
        return None
    run = clean["run"]
    run["playbook_id"] = playbook_id
    return json.dumps(run, ensure_ascii=False)


def _src_tables(con):
    return {r[0]: r[1] for r in con.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL")}


def _build_content_db(dst_path, include_runs):
    """Copy the CONTENT tables of the live DB into a fresh plain SQLite file. Returns {table: rows}."""
    src = _common_db.connect(timeout=10)
    counts = {}
    try:
        schema = _src_tables(src)
        indexes = src.execute("SELECT tbl_name,sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL").fetchall()
        dst = _drv.connect(dst_path)
        try:
            for t in CONTENT_TABLES:
                if t not in schema or (t in RUN_TABLES and not include_runs):
                    continue
                dst.execute(schema[t])
                for tbl, sql in indexes:
                    if tbl == t:
                        try:
                            dst.execute(sql)
                        except Exception:
                            pass
                cols = [r[1] for r in src.execute('PRAGMA table_info("%s")' % t)]
                qc = ",".join('"%s"' % c for c in cols)
                ins = 'INSERT INTO "%s"(%s) VALUES(%s)' % (t, qc, ",".join("?" * len(cols)))
                n = 0
                cur = src.execute('SELECT %s FROM "%s"' % (qc, t))
                if t == "ChainRuns":
                    pos = {c: i for i, c in enumerate(cols)}
                    keys = ("run_id", "playbook_id", "chain_name", "mode", "state", "source", "target", "started_at", "ended_at")
                for row in cur:
                    row = list(row)
                    if t == "ChainRuns":
                        data = strip_run_data(row[pos["data"]], [row[pos[k]] for k in keys])
                        if data is None:
                            continue
                        row[pos["data"]] = data
                        if row[pos["state"]] not in _final_states():
                            row[pos["state"]] = "cancelled"
                    dst.execute(ins, row)
                    n += 1
                counts[t] = n
            if include_runs and "ChainRunLogs" in counts and "ChainRuns" in counts:
                # Logs only for the runs that went out.
                dst.execute("DELETE FROM ChainRunLogs WHERE run_id NOT IN (SELECT run_id FROM ChainRuns)")
                counts["ChainRunLogs"] = dst.execute("SELECT COUNT(*) FROM ChainRunLogs").fetchone()[0]
            dst.execute("PRAGMA user_version=%d" % int(_common_db.DB_SCHEMA_VERSION))
            dst.commit()
            dst.execute("VACUUM")
        finally:
            dst.close()
    finally:
        src.close()
    return counts


def _final_states():
    from Cores.Services import chain_history as _hist
    return _hist.FINAL_STATES


def _quick_run(content_db):
    """Quick Run favourites ('Table:id' keys) with the command each one points at, so an import can find it again."""
    favs = (_read_settings().get("mini_window") or {})
    if not isinstance(favs, dict):
        return None
    keys = [str(x) for x in (favs.get("favorites") or []) if isinstance(x, str) and x.strip()]
    if not keys:
        return None
    out = []
    con = _drv.connect(content_db)
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for k in keys:
            m = re.match(r"^([A-Za-z0-9_]{1,40}):(\d{1,12})$", k)
            if not m or m.group(1) not in ("Commands", "CommandsNotes") or m.group(1) not in tables:
                continue
            row = con.execute('SELECT note_name,category,sub_category,command FROM "%s" WHERE id=?' % m.group(1), (int(m.group(2)),)).fetchone()
            if row:
                out.append({"key": k, "source": m.group(1), "id": int(m.group(2)), "note_name": row[0], "category": row[1],
                            "sub_category": row[2], "command": row[3]})
    finally:
        con.close()
    return {"favorites": out, "favorites_only": bool(favs.get("favorites_only"))} if out else None


# ---------------------------------------------------------------- JSON stores and files
def _doc_names(include_ai_chats):
    data = _common_db.data_dir()
    names = set(p for p in CONTENT_DOC_PATTERNS if "*" not in p)
    for sub in ("Profiles", "ai_sessions"):
        d = os.path.join(data, sub)
        if os.path.isdir(d):
            for n in os.listdir(d):
                if sub == "Profiles":
                    names.add("Profiles/%s/Targets.json" % n)
                    names.add("Profiles/%s/target_values.json" % n)
                elif include_ai_chats:
                    names.add("ai_sessions/" + n)
    try:
        for p in _doc_store.read_json(os.path.join(data, "profiles.json"), []) or []:
            pid = str((p or {}).get("id") or "") if isinstance(p, dict) else ""
            if re.match(r"^[A-Za-z0-9_-]{1,64}$", pid):
                names.add("Profiles/%s/Targets.json" % pid)
                names.add("Profiles/%s/target_values.json" % pid)
    except Exception:
        pass
    if _doc_store.active():
        for n in _doc_store.list_names():
            names.add(n)
    pats = CONTENT_DOC_PATTERNS + ((AI_CHAT_PATTERN,) if include_ai_chats else ())
    return sorted(n for n in names if any(_match(n, p) for p in pats))


_MISSING = object()


def _read_doc(rel):
    p = os.path.join(_common_db.data_dir(), *rel.split("/"))
    if not _doc_store.exists(p):
        return _MISSING
    v = _doc_store.read_json(p, _MISSING)
    return v


def _plain_file(path):
    from Cores.Services import notes_service as _ns
    with open(path, "rb") as f:
        return _ns.attachment_bytes(f.read())


def _iter_files():
    """(arcname, abs path) of the content files: per-note attachment folders and chain/*.html."""
    data = _common_db.data_dir()
    att = os.path.join(data, "Attachments")
    if os.path.isdir(att):
        for nid in sorted(os.listdir(att)):
            d = os.path.join(att, nid)
            if not nid.isdigit() or not os.path.isdir(d) or os.path.islink(d):
                continue
            for n in sorted(os.listdir(d)):
                p = os.path.join(d, n)
                if os.path.isfile(p) and not os.path.islink(p) and not n.endswith(".tmp"):
                    yield "files/Attachments/%s/%s" % (nid, n), p
    ch = os.path.join(data, "chain")
    if os.path.isdir(ch):
        for n in sorted(os.listdir(ch)):
            p = os.path.join(ch, n)
            if n.lower().endswith(".html") and os.path.isfile(p) and not os.path.islink(p):
                yield "files/chain/" + n, p


def _len(v):
    if isinstance(v, (list, dict)):
        for k in ("items", "entries", "notes", "cards"):
            if isinstance(v, dict) and isinstance(v.get(k), list):
                return len(v[k])
        return len(v)
    return 1 if v not in (None, "") else 0


# ---------------------------------------------------------------- export
def check_password(password):
    pw = str(password or "")
    if len(pw) < _min_len():
        raise ExportError("The export password must be at least %d characters." % _min_len())
    return pw


def build_zip(zip_path, include_settings=False, include_run_history=True, include_ai_chats=False, work=None):
    """Write the plain work-export zip. Returns (counts, entries)."""
    if _common_db.db_locked():
        raise _common_db.DatabaseLocked(_common_db.LOCKED_MESSAGE)
    own = work is None
    work = work or tempfile.mkdtemp(prefix=".loya_backup_export_", dir=_common_db.data_dir())
    try:
        cdb = os.path.join(work, "content.db")
        tc = _build_content_db(cdb, include_run_history)
        counts = {k: 0 for k in ("notes", "note_versions", "attachments", "commands", "command_notes", "command_versions",
                                 "quick_space", "quick_run", "target_profiles", "targets", "target_values", "reports",
                                 "report_templates", "findings_library", "evidence", "chains", "chain_runs", "chain_files",
                                 "tag_colors", "notes_meta", "note_templates", "saved_searches", "settings", "ai_chats")}
        for t, k in (("Notes", "notes"), ("NotesHistory", "note_versions"), ("Commands", "commands"), ("CommandsNotes", "command_notes"),
                     ("Reports", "reports"), ("ReportTemplates", "report_templates"), ("FindingLibrary", "findings_library"),
                     ("ReportEvidence", "evidence"), ("Playbooks", "chains"), ("ChainRuns", "chain_runs")):
            counts[k] += tc.get(t, 0)
        counts["command_versions"] = tc.get("CommandsHistory", 0) + tc.get("CommandsNotesHistory", 0)
        entries = []
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.write(cdb, "content.db"); entries.append("content.db")
            for rel in _doc_names(include_ai_chats):
                v = _read_doc(rel)
                if v is _MISSING:
                    continue
                arc = ("ai_sessions/" + rel.split("/", 1)[1]) if rel.startswith("ai_sessions/") else "docs/" + rel
                z.writestr(arc, json.dumps(v, ensure_ascii=False, indent=2)); entries.append(arc)
                kind = (classify(rel) or {}).get("kind")
                if kind == "target_profiles":
                    counts[kind] += len(v) if isinstance(v, list) else 0
                elif kind in ("notes_meta",):
                    counts[kind] += 1
                elif kind == "ai_chats":
                    counts[kind] += 1
                elif kind in counts:
                    counts[kind] += _len(v)
            qr = _quick_run(cdb)
            if qr:
                z.writestr("quick_run.json", json.dumps(qr, ensure_ascii=False, indent=2)); entries.append("quick_run.json")
                counts["quick_run"] = len(qr["favorites"])
            for arc, p in _iter_files():
                z.writestr(arc, _plain_file(p)); entries.append(arc)
                counts["attachments" if arc.startswith("files/Attachments/") else "chain_files"] += 1
            if include_settings:
                s = portable_settings(_read_settings())
                if s:  # nothing portable set (all defaults): no settings.json, so the importer offers nothing to apply
                    z.writestr("settings.json", json.dumps(s, ensure_ascii=False, indent=2)); entries.append("settings.json")
                    counts["settings"] = 1
            manifest = {"format": FORMAT, "format_version": FORMAT_VERSION, "created_at": _now(), "app_version": _app_version(),
                        "counts": counts, "included": {"settings": bool(include_settings), "run_history": bool(include_run_history),
                                                       "ai_chats": bool(include_ai_chats)},
                        "kinds": sorted(k for k, n in counts.items() if n), "entries": entries}
            z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        return counts, entries
    finally:
        if own:
            shutil.rmtree(work, ignore_errors=True)


def protect(zip_path, out_path, password, meta=None):
    """Wrap a zip as a password-protected .loyabak container (kind "work")."""
    from Cores import crypto_store as _cs, loyabak as _lb
    dek = _cs.DataKey.generate()
    try:
        kf = _cs.wrap_dek(dek, check_password(password), _KDF)
        header = {"kind": "work", "protect": "password", "format": FORMAT, "format_version": FORMAT_VERSION,
                  "created_at": _now(), "app": _app_version()}
        header.update(meta or {})
        _lb.write(zip_path, out_path, dek, kf, header)
    finally:
        dek.wipe()
    return out_path


def export_work_zip(out_path, include_settings=False, include_run_history=True, include_ai_chats=False, password=None, pin=None):
    """Write the work export to out_path. password: protect it (.loyawork container). Returns
    {"path","name","counts","protected","files"}."""
    out_abs = os.path.abspath(out_path)
    if password:
        check_password(password)
    elif _common_db.encryption_configured():
        from Cores.Services import security_service as _sec
        ok, msg = _sec.plain_export_allowed(pin, "work export")
        if not ok:
            raise ExportError(msg)
    os.makedirs(os.path.dirname(out_abs) or ".", exist_ok=True)
    # Inside Data/ (private, 0700) and named like the backup work folders, which backups and exports skip.
    work = tempfile.mkdtemp(prefix=".loya_backup_export_", dir=_common_db.data_dir())
    try:
        os.chmod(work, 0o700)
    except OSError:
        pass
    try:
        zp = os.path.join(work, "export.zip")
        counts, entries = build_zip(zp, include_settings, include_run_history, include_ai_chats, work=work)
        if password:
            protect(zp, out_abs, password)
        else:
            tmp = out_abs + ".tmp"
            shutil.copyfile(zp, tmp)
            os.replace(tmp, out_abs)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return {"path": out_abs, "name": os.path.basename(out_abs), "counts": counts, "protected": bool(password), "files": len(entries) + 1}
