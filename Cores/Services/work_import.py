"""Import of "Export my work" files (Settings > Import & Export > All Data).

Reads the work export format (Cores/Services/work_export.py: a zip with manifest.json, content.db, docs/, files/, optional
settings.json and ai_sessions/; or the same zip inside a password-protected .loyawork container) and the old full-Data zips
(the Export All format before 1.0.4 and old plain backup zips). Only CONTENT is taken from either: the classification lives in
work_export.CLASSIFICATION; anything else in the file (CLI connection tokens, the Secrets and AuditEvents tables, the key file,
settings.json of an old zip, deps_state, the pid file, the search index, terminal sessions ...) is listed as ignored and never
read into this install.

preview() shows what a file holds and what clashes with this install; apply() then merges (add what is missing; a clash is
renamed "<name> (imported)" or skipped) or replaces this install's content (its secrets, tokens, settings, key file, keyring
entries and audit log are never touched). Every write goes through common_db / doc_store / notes_service, so an importer with
encryption at rest on stores the imported content encrypted like the rest.

Decisions:
- Targets go into the profile they came from (same profile id). A profile this install does not have is created from the
  export's profiles.json (renamed "(imported)" when its name is taken by another profile). A file without any profiles.json
  (very old zips) puts its targets into the current active profile.
- Commands are deduplicated: the same command text in the same place is skipped in both clash modes (a renamed copy of an
  identical command would only be a duplicate).
- Chains go through chain_history.import_bundle: validated, scripts hardened, and marked unreviewed; run history comes with
  its run variables left behind (import_bundle never imports them).
- The settings of a work export are applied only when the file includes them AND the caller asks (apply_settings), and then
  only the portable keys, merged key by key. An old full-Data zip's settings.json is never applied.
"""
import json
import os
import re
import shutil
import tempfile
import uuid
import zipfile

from Cores import common_db as _common_db
from Cores import db_driver as _drv
from Cores import doc_store as _doc_store

FORMAT = "loya-work-export"
LEGACY_TYPE = "LOYA Note Export All"
DB_NAME = "Note_LOYA_V1.db"


class PasswordRequired(ValueError):
    pass


class WrongPassword(ValueError):
    pass


# ---------------------------------------------------------------- classification (work_export owns it; a local copy keeps
# this module usable on its own)
_CONTENT_TABLES = ("Notes", "NotesHistory", "CommandsNotes", "Commands", "CommandsHistory", "CommandsNotesHistory", "Playbooks",
                   "PlaybookSteps", "ChainGraphs", "ChainRuns", "ChainRunLogs", "Reports", "ReportSections", "ReportFindings",
                   "ReportVersions", "ReportEvidence", "ReportEvidenceEvents", "ReportAssets", "ReportTargets",
                   "ReportFindingTargets", "ReportTemplates", "FindingLibrary")
_CONTENT_DOCS = ("profiles.json", "Targets.json", "Targes.json", "target_values.json", "notes_meta.json", "notes_templates.json",
                 "QuicSpace.json", "tag_colors.json", "saved_searches.json")
_PROFILE_DOC_RX = re.compile(r"^Profiles/([A-Za-z0-9_-]{1,64})/(Targets\.json|target_values\.json)$")
_AI_RX = re.compile(r"^ai_sessions/([A-Za-z0-9_. -]{1,120}\.json)$")
_CHAIN_FILE_RX = re.compile(r"^chain/([^/\\]{1,180}\.html)$")
_ATTACH_RX = re.compile(r"^Attachments/(\d{1,12})/([A-Za-z0-9_.-]{1,200})$")
_SENSITIVE_KEY_RX = re.compile(r"key|token|secret|password|passwd|pin|path|shell|dir|geometry|window|cookie|auth|cred", re.I)


def _content_tables():
    try:
        from Cores.Services import work_export as _we
        cls = getattr(_we, "CLASSIFICATION", None)
        if isinstance(cls, dict):
            got = [k.split(":", 1)[1] for k, v in cls.items() if str(k).startswith("db:") and isinstance(v, dict) and v.get("class") == "content"]
            if got:
                return tuple(t for t in _CONTENT_TABLES if t in got) + tuple(t for t in got if t not in _CONTENT_TABLES)
    except Exception:
        pass
    return _CONTENT_TABLES


def _portable_settings(d):
    try:
        from Cores.Services import work_export as _we
        fn = getattr(_we, "portable_settings", None)
        if callable(fn):
            out = fn(d)
            if isinstance(out, dict):
                out.pop("security", None)
                return out
    except Exception:
        pass

    def clean(v):
        if isinstance(v, dict):
            return {k: clean(x) for k, x in v.items() if not _SENSITIVE_KEY_RX.search(str(k))}
        return v
    out = clean(d) if isinstance(d, dict) else {}
    for k in ("security", "backup", "external_agents", "mini_window", "window", "terminal", "deps", "update", "onboarding"):
        out.pop(k, None)
    return out


def doc_allowed(rel):
    return rel in _CONTENT_DOCS or bool(_PROFILE_DOC_RX.match(rel))


# ---------------------------------------------------------------- small helpers
def _s(v):
    return "" if v is None else str(v)


def _kci(v):
    return " ".join(_s(v).lower().split())


def _data_dir():
    return _common_db.data_dir()


def _free(name, taken, limit=180):
    """'<name> (imported)', then '(imported 2)' ... not in taken (case-insensitive keys)."""
    base = _s(name).strip()[:limit] or "Imported"
    for i in range(1, 10000):
        cand = f"{base} (imported)" if i == 1 else f"{base} (imported {i})"
        if _kci(cand) not in taken:
            return cand
    return f"{base} ({uuid.uuid4().hex[:8]})"


def _tables(con):
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}


def _cols(con, table):
    return [r[1] for r in con.execute(f'PRAGMA table_info("{table}")').fetchall()]


def _rows(con, table, have):
    if table not in have:
        return []
    cols = _cols(con, table)
    return [dict(zip(cols, r)) for r in con.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()]


def _insert(cur, table, row, live_cols, drop=("id",)):
    keys = [k for k in row if k in live_cols and k not in drop]
    cur.execute(f'INSERT INTO "{table}"({",".join(keys)}) VALUES({",".join("?" * len(keys))})', tuple(row[k] for k in keys))
    return cur.lastrowid


def _count(con, table, have):
    if table not in have:
        return 0
    try:
        return int(con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
    except Exception:
        return 0


# ---------------------------------------------------------------- reading a file
def _zip_names(path):
    try:
        with zipfile.ZipFile(path, "r") as z:
            return [n.replace("\\", "/") for n in z.namelist()]
    except Exception:
        return None


def _zip_manifest(path):
    try:
        with zipfile.ZipFile(path, "r") as z:
            info = next((i for i in z.infolist() if i.filename == "manifest.json"), None)
            if info is None or info.file_size > 4 * 1024 * 1024:
                return None
            d = json.loads(z.read(info).decode("utf-8"))
            return d if isinstance(d, dict) else None
    except Exception:
        return None


def _zip_kind(path):
    man = _zip_manifest(path)
    if man and man.get("format") == FORMAT:
        return "work"
    names = _zip_names(path)
    if names is None:
        return ""
    if (man and man.get("type") == LEGACY_TYPE) or any(n.startswith("Data/") and not n.endswith("/") for n in names):
        return "legacy"
    return ""


def detect(path):
    """'work' | 'work_protected' | 'legacy' | 'backup' | '' for a picked file."""
    if not path or not os.path.isfile(path):
        return ""
    from Cores import loyabak as _lb
    if _lb.is_loyabak(path):
        try:
            header = _lb.read_header(path)
        except Exception:
            return ""
        return "work_protected" if _s(header.get("kind")) == "work" else "backup"
    return _zip_kind(path)


class _Source:
    """An opened import file: content DB path (+ key), docs {rel: obj}, attachment files, chain files, settings, AI chats."""

    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="loya_import_")
        try:
            os.chmod(self.tmp, 0o700)
        except OSError:
            pass
        self.format = ""
        self.protected = False
        self.manifest = {}
        self.db = None
        self.db_key = None
        self.docs = {}
        self.attachments = {}    # old note id -> [(name, abs path)]
        self.chain_files = []    # (name, abs path)
        self.settings = None
        self.ai_chats = []       # (name, obj)
        self.quick_run = None    # {"favorites":[{key,source,id,note_name,category,sub_category,command}],"favorites_only"}
        self.cmd_map = {}        # source Commands id -> live id
        self.cn_map = {}         # source CommandsNotes id -> live id (imported, or the identical one already here)
        self.ignored = []
        self.attach_key = None   # legacy: attachments encrypted at rest with this install's key

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def read_bytes(self, path):
        with open(path, "rb") as f:
            raw = f.read()
        from Cores import crypto_store as _cs
        if raw[:8] == _cs.MAGIC:
            key = self.attach_key or _common_db.session_key()
            if key is None:
                raise ValueError("An attachment in this file is encrypted and cannot be read here.")
            return _cs.decrypt_bytes(raw, key)
        return raw


def _read_json_file(p):
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _extract(zip_path, dst):
    from Cores.Update import backup_restore as _br
    _br._safe_extract_backup(zip_path, dst)


def _open(path, password=None, pin=None):
    if not path or not os.path.isfile(path):
        raise ValueError("The file was not found.")
    kind = detect(path)
    if kind == "backup":
        raise ValueError("This is a full backup of an install. Restore it under Settings > Backup instead.")
    if not kind:
        raise ValueError("This file is not a LOYA NG work export or an old Export All zip.")
    src = _Source()
    try:
        zp = path
        if kind == "work_protected":
            from Cores import loyabak as _lb, crypto_store as _cs
            if not password:
                raise PasswordRequired("This export is protected with a password.")
            try:
                dek = _lb.unwrap(path, str(password))
            except _cs.WrongPin:
                raise WrongPassword("Wrong password.")
            try:
                zp = os.path.join(src.tmp, "work.zip")
                _lb.decrypt_to(path, zp, dek)
            finally:
                dek.wipe()
            src.protected = True
            kind = _zip_kind(zp)
            if kind != "work":
                raise ValueError("The protected file does not hold a work export.")
        ex = os.path.join(src.tmp, "x")
        os.makedirs(ex)
        _extract(zp, ex)
        if kind == "work":
            _load_work(src, ex)
        else:
            _load_legacy(src, ex)
        return src
    except BaseException:
        src.close()
        raise


def _walk(root):
    for b, _d, files in os.walk(root):
        for n in files:
            p = os.path.join(b, n)
            yield os.path.relpath(p, root).replace("\\", "/"), p


def _load_work(src, ex):
    src.format = "work"
    src.manifest = _read_json_file(os.path.join(ex, "manifest.json")) or {}
    inc = src.manifest.get("included") if isinstance(src.manifest.get("included"), dict) else {}
    for rel, p in _walk(ex):
        if rel == "manifest.json":
            continue
        if rel == "content.db":
            if _drv.file_kind(p) != "plain":
                raise ValueError("The content database in this export is not readable.")
            src.db = p
            continue
        if rel.startswith("docs/") and doc_allowed(rel[5:]):
            obj = _read_json_file(p)
            if obj is not None:
                src.docs["Targets.json" if rel[5:] == "Targes.json" else rel[5:]] = obj
            continue
        if rel.startswith("files/"):
            sub = rel[6:]
            m = _ATTACH_RX.match(sub)
            if m:
                src.attachments.setdefault(int(m.group(1)), []).append((m.group(2), p))
                continue
            m = _CHAIN_FILE_RX.match(sub)
            if m:
                src.chain_files.append((m.group(1), p))
                continue
        if rel == "quick_run.json":
            obj = _read_json_file(p)
            if isinstance(obj, dict) and isinstance(obj.get("favorites"), list):
                src.quick_run = {"favorites": [f for f in obj["favorites"] if isinstance(f, dict)][:5000], "favorites_only": bool(obj.get("favorites_only"))}
            continue
        if rel == "settings.json" and inc.get("settings", True):
            obj = _read_json_file(p)
            src.settings = _portable_settings(obj) if isinstance(obj, dict) else None
            continue
        m = _AI_RX.match(rel)
        if m:
            obj = _read_json_file(p)
            if obj is not None:
                src.ai_chats.append((m.group(1), obj))
            continue
        src.ignored.append(rel)


def _load_legacy(src, ex):
    """An old full-Data zip: only the allowlisted content is read; everything else is listed as ignored."""
    src.format = "legacy"
    src.manifest = _read_json_file(os.path.join(ex, "manifest.json")) or {}
    root = os.path.join(ex, "Data")
    if not os.path.isdir(root):
        raise ValueError("This zip does not contain LOYA Data files.")
    for rel, p in _walk(ex):
        if rel == "manifest.json":
            continue
        if not rel.startswith("Data/"):
            src.ignored.append(rel)
            continue
        sub = rel[5:]
        if sub == DB_NAME:
            src.db = p
            continue
        if doc_allowed(sub):
            obj = _read_json_file(p)
            if obj is not None:
                src.docs["Targets.json" if sub == "Targes.json" else sub] = obj
            continue
        m = _ATTACH_RX.match(sub)
        if m:
            src.attachments.setdefault(int(m.group(1)), []).append((m.group(2), p))
            continue
        m = _CHAIN_FILE_RX.match(sub)
        if m:
            src.chain_files.append((m.group(1), p))
            continue
        src.ignored.append(rel)   # settings.json, the key file, connections, deps_state, pid, audit log, search index ...
    if src.db:
        kind = _drv.file_kind(src.db)
        if kind == "encrypted":
            key = _common_db.session_key()
            ok = False
            if key is not None:
                try:
                    _drv.connect(src.db, key=key).close()
                    ok = True
                except Exception:
                    ok = False
            if not ok:
                raise ValueError("This old export was made with encryption at rest on another install (or while locked): restore it there and make a new work export.")
            src.db_key = key
            src.attach_key = key
        elif kind != "plain":
            src.db = None
        if src.db:
            # A legacy DB made with encryption at rest on keeps the JSON stores in AppDocs: read only the content docs.
            con = _drv.connect(src.db, key=src.db_key)
            try:
                if "AppDocs" in _tables(con):
                    for name, data in con.execute("SELECT name,data FROM AppDocs").fetchall():
                        n = "Targets.json" if name == "Targes.json" else _s(name)
                        if doc_allowed(n) and n not in src.docs:
                            try:
                                src.docs[n] = json.loads(data)
                            except ValueError:
                                pass
            finally:
                con.close()


# ---------------------------------------------------------------- live install helpers
def _guard():
    if _common_db.db_locked():
        raise _common_db.DatabaseLocked(_common_db.LOCKED_MESSAGE)


def _live_doc_path(rel):
    return os.path.join(_data_dir(), *rel.split("/"))


def _live_read(rel, default):
    return _doc_store.read_json(_live_doc_path(rel), default)


def _live_write(rel, obj):
    if not _doc_store.write_json(_live_doc_path(rel), obj):
        raise ValueError(f"Could not save {rel}.")


def _source_profiles(src):
    d = src.docs.get("profiles.json")
    return [p for p in d if isinstance(p, dict) and _s(p.get("id")).strip()] if isinstance(d, list) else []


def _targets_doc(pid):
    return "Targets.json" if pid == "default" else f"Profiles/{pid}/Targets.json"


def _values_doc(pid):
    return "target_values.json" if pid == "default" else f"Profiles/{pid}/target_values.json"


def _target_key(item):
    if isinstance(item, dict):
        if _s(item.get("id")).strip():
            return "id:" + _kci(item.get("id"))
        if _s(item.get("name")).strip():
            return "name:" + _kci(item.get("name"))
    return "raw:" + json.dumps(item, ensure_ascii=False, sort_keys=True)


def _source_target_sets(src):
    """[(source profile id or None for 'the active profile', targets list, values dict)]."""
    profiles = _source_profiles(src)
    out = []
    if profiles or any(_PROFILE_DOC_RX.match(k) for k in src.docs):
        ids = ["default"] + [p["id"] for p in profiles if p["id"] != "default"]
        for k in src.docs:
            m = _PROFILE_DOC_RX.match(k)
            if m and m.group(1) not in ids:
                ids.append(m.group(1))
        for pid in ids:
            t = src.docs.get(_targets_doc(pid))
            v = src.docs.get(_values_doc(pid))
            if t is None and v is None:
                continue
            out.append((pid, t if isinstance(t, list) else ([t] if isinstance(t, dict) else []), v if isinstance(v, dict) else {}))
    else:
        t = src.docs.get("Targets.json")
        v = src.docs.get("target_values.json")
        if t is not None or v is not None:
            out.append((None, t if isinstance(t, list) else ([t] if isinstance(t, dict) else []), v if isinstance(v, dict) else {}))
    return out


def _live_profiles():
    from Cores import target_profiles as _tp
    return _tp.list_profiles()


def _resolve_profile(pid, src):
    """The live profile id the source profile's targets go to (None: the active profile)."""
    from Cores import target_profiles as _tp
    if pid is None:
        return _tp.active_profile_id(), False
    live = _live_profiles()
    if any(p.get("id") == pid for p in live):
        return pid, False
    return pid, True


def _graph_ids(con, have):
    if "ChainGraphs" not in have:
        return set()
    return {int(r[0]) for r in con.execute("SELECT playbook_id FROM ChainGraphs").fetchall()}


# ---------------------------------------------------------------- preview
def _counts_and_clashes(src):
    counts = {}
    clashes = {}
    live_notes, live_chains, live_reports, live_tpl, live_lib = set(), set(), set(), set(), set()
    try:
        with _common_db.connection(timeout=10) as lc:
            lt = _tables(lc)
            if "Notes" in lt:
                live_notes = {_kci(r[0]) for r in lc.execute("SELECT note_name FROM Notes").fetchall()}
            if "Playbooks" in lt:
                live_chains = {_kci(r[0]) for r in lc.execute("SELECT name FROM Playbooks").fetchall()}
            if "Reports" in lt:
                live_reports = {_kci(r[0]) for r in lc.execute("SELECT title FROM Reports").fetchall()}
            if "ReportTemplates" in lt:
                live_tpl = {_kci(r[0]) for r in lc.execute("SELECT name FROM ReportTemplates").fetchall()}
            if "FindingLibrary" in lt:
                live_lib = {_kci(r[0]) for r in lc.execute("SELECT title FROM FindingLibrary").fetchall()}
    except _common_db.DatabaseLocked:
        raise
    except Exception:
        pass
    if src.db:
        con = _drv.connect(src.db, key=src.db_key)
        try:
            have = _tables(con)
            counts["notes"] = _count(con, "Notes", have)
            counts["note_versions"] = _count(con, "NotesHistory", have)
            counts["commands"] = _count(con, "CommandsNotes", have)
            counts["command_notes"] = _count(con, "Commands", have)
            counts["chains"] = _count(con, "Playbooks", have)
            counts["chain_runs"] = _count(con, "ChainRuns", have)
            counts["reports"] = _count(con, "Reports", have)
            counts["report_templates"] = _count(con, "ReportTemplates", have)
            counts["findings_library"] = _count(con, "FindingLibrary", have)
            counts["evidence"] = _count(con, "ReportEvidence", have)

            def hits(sql, live, table):
                if table not in have:
                    return []
                return [r[0] for r in con.execute(sql).fetchall() if _kci(r[0]) in live][:200]
            clashes["notes"] = hits("SELECT note_name FROM Notes", live_notes, "Notes")
            clashes["chains"] = hits("SELECT name FROM Playbooks", live_chains, "Playbooks")
            clashes["reports"] = hits("SELECT title FROM Reports", live_reports, "Reports")
            clashes["report_templates"] = hits("SELECT name FROM ReportTemplates", live_tpl, "ReportTemplates")
            clashes["findings_library"] = hits("SELECT title FROM FindingLibrary", live_lib, "FindingLibrary")
        finally:
            con.close()
    counts["attachments"] = sum(len(v) for v in src.attachments.values())
    counts["chain_files"] = len(src.chain_files)
    live_chain_files = set()
    cdir = os.path.join(_data_dir(), "chain")
    if os.path.isdir(cdir):
        live_chain_files = {n.lower() for n in os.listdir(cdir)}
    clashes["chain_files"] = [n for n, _ in src.chain_files if n.lower() in live_chain_files]
    sets = _source_target_sets(src)
    counts["targets"] = sum(len(t) for _, t, _ in sets)
    counts["target_values"] = sum(len(v) for _, _, v in sets)
    counts["target_profiles"] = len(_source_profiles(src))
    tclash = []
    for pid, targets, _v in sets:
        lpid, _new = _resolve_profile(pid, src)
        live = _live_read(_targets_doc(lpid), [])
        keys = {_target_key(x) for x in (live if isinstance(live, list) else [])}
        tclash += [(_s(t.get("name") or t.get("id")) if isinstance(t, dict) else _s(t))[:120] for t in targets if _target_key(t) in keys]
    clashes["targets"] = tclash[:200]
    counts["quick_space"] = 1 if _quick_text(src.docs.get("QuicSpace.json")) else 0
    counts["tag_colors"] = len(src.docs.get("tag_colors.json") or {}) if isinstance(src.docs.get("tag_colors.json"), dict) else 0
    meta = src.docs.get("notes_meta.json")
    counts["notes_meta"] = 1 if isinstance(meta, dict) else 0
    nt = src.docs.get("notes_templates.json")
    counts["note_templates"] = len(nt) if isinstance(nt, list) else 0
    counts["quick_run"] = len((src.quick_run or {}).get("favorites") or [])
    counts["settings"] = 1 if src.settings else 0
    counts["ai_chats"] = len(src.ai_chats)
    return counts, {k: v for k, v in clashes.items() if v}


def preview(path, password=None, pin=None):
    _guard()
    with _open(path, password, pin) as src:
        counts, clashes = _counts_and_clashes(src)
        inc = src.manifest.get("included") if isinstance(src.manifest.get("included"), dict) else {}
        return {"format": src.format, "protected": src.protected, "counts": counts, "clashes": clashes,
                "included": {"settings": bool(src.settings), "run_history": bool(counts.get("chain_runs")) or bool(inc.get("run_history")),
                             "ai_chats": bool(src.ai_chats)},
                "has_settings": bool(src.settings), "ignored": sorted(src.ignored)[:500], "ignored_count": len(src.ignored),
                "app_version": _s(src.manifest.get("app_version")), "created_at": _s(src.manifest.get("created_at"))}


# ---------------------------------------------------------------- apply
_FILE_URL_RX = re.compile(r"file:///*[^\"'<>\s]*?[\\/]Attachments[\\/]+(\d+)[\\/]")


def _rewrite_attachment_urls(html, old_id, new_dir):
    from Cores.Services import notes_service as _ns
    base = _ns._file_url(new_dir) + "/"
    return _FILE_URL_RX.sub(lambda m: base if m.group(1) == str(old_id) else m.group(0), _s(html))


def _quick_text(d):
    return _s(d.get("text")).strip() if isinstance(d, dict) else ""


class _Result:
    def __init__(self, mode):
        self.mode = mode
        self.added, self.renamed, self.skipped = {}, {}, {}

    def add(self, kind, n=1):
        self.added[kind] = self.added.get(kind, 0) + n

    def ren(self, kind, n=1):
        self.renamed[kind] = self.renamed.get(kind, 0) + n

    def skip(self, kind, n=1):
        self.skipped[kind] = self.skipped.get(kind, 0) + n


def _clear_live_content(lc):
    """Replace mode: this install's content goes (tables, content docs, attachments, chain files). Secrets, AuditEvents,
    settings, the key file, keyring, connections and terminal sessions stay."""
    have = _tables(lc)
    for t in _CONTENT_TABLES:
        if t in have:
            lc.execute(f'DELETE FROM "{t}"')
    from Cores.Services import notes_service as _ns
    root = _ns._attachments_root()
    for n in os.listdir(root):
        if n.isdigit() and os.path.isdir(os.path.join(root, n)):
            shutil.rmtree(os.path.join(root, n), ignore_errors=True)
    cdir = os.path.join(_data_dir(), "chain")
    if os.path.isdir(cdir):
        for n in os.listdir(cdir):
            if n.lower().endswith(".html") and os.path.isfile(os.path.join(cdir, n)):
                os.remove(os.path.join(cdir, n))


def _clear_live_docs(src):
    live = _live_profiles()
    for p in live:
        pid = p.get("id") or "default"
        _live_write(_targets_doc(pid), [])
        _live_write(_values_doc(pid), {})
    for rel, empty in (("notes_meta.json", {"pinned": [], "recent": [], "groups": [], "nav_collapsed_groups": []}),
                       ("notes_templates.json", []), ("tag_colors.json", {}), ("saved_searches.json", [])):
        if _doc_store.exists(_live_doc_path(rel)):
            _live_write(rel, empty)
    if _doc_store.exists(_live_doc_path("QuicSpace.json")):
        q = _live_read("QuicSpace.json", {})
        _live_write("QuicSpace.json", {**(q if isinstance(q, dict) else {}), "html": "<br>", "text": "\n"})
    imported = {p["id"] for p in _source_profiles(src)}
    if imported:
        # Profiles the import does not have are removed (their targets were cleared above); the Default profile always stays.
        keep = [p for p in live if p.get("id") == "default" or p.get("id") in imported]
        if len(keep) != len(live):
            _live_write("profiles.json", keep)


def _import_db(src, lc, res, clash, note_map):
    con = _drv.connect(src.db, key=src.db_key)
    try:
        have = _tables(con)
        cur = lc.cursor()
        live = {t: set(_cols(lc, t)) for t in _tables(lc)}
        # ---- notes, their versions and the commands extracted from them
        taken = {_kci(r[0]) for r in lc.execute("SELECT note_name FROM Notes").fetchall()}
        cmd_map, cn_map = {}, {}
        for row in _rows(con, "Notes", have):
            old = row.get("id")
            name = _s(row.get("note_name"))
            if _kci(name) in taken:
                if clash == "skip":
                    res.skip("notes")
                    continue
                row["note_name"] = _free(name, taken)
                res.ren("notes")
            taken.add(_kci(row["note_name"]))
            new = _insert(cur, "Notes", row, live["Notes"])
            note_map[int(old)] = (int(new), row["note_name"])
            res.add("notes")
        for row in _rows(con, "NotesHistory", have):
            m = note_map.get(int(row.get("note_id") or -1))
            if not m:
                continue
            row["note_id"], row["note_name"] = m[0], m[1]
            _insert(cur, "NotesHistory", row, live["NotesHistory"])
            res.add("note_versions")
        for row in _rows(con, "Commands", have):
            m = note_map.get(int(row.get("note_id") or -1))
            if not m:
                continue
            old = row.get("id")
            row["note_id"], row["note_name"] = m[0], m[1]
            cmd_map[int(old)] = int(_insert(cur, "Commands", row, live["Commands"]))
            res.add("command_notes")
        for row in _rows(con, "CommandsHistory", have):
            if int(row.get("cmd_id") or -1) not in cmd_map:
                continue
            m = note_map.get(int(row.get("note_id") or -1))
            row["cmd_id"] = cmd_map[int(row["cmd_id"])]
            if m:
                row["note_id"], row["note_name"] = m[0], m[1]
            _insert(cur, "CommandsHistory", row, live["CommandsHistory"])
        # ---- the command library (identical commands are skipped, never duplicated)
        seen = {}
        for rid, nn, cat, sub, cmd in lc.execute("SELECT id,note_name,category,sub_category,command FROM CommandsNotes").fetchall():
            seen[(_kci(nn), _kci(cat), _kci(sub), _s(cmd).strip())] = int(rid)
        for row in _rows(con, "CommandsNotes", have):
            k = (_kci(row.get("note_name")), _kci(row.get("category")), _kci(row.get("sub_category")), _s(row.get("command")).strip())
            if k in seen:
                cn_map[int(row["id"])] = (seen[k], False)
                res.skip("commands")
                continue
            new = int(_insert(cur, "CommandsNotes", row, live["CommandsNotes"]))
            seen[k] = new
            cn_map[int(row["id"])] = (new, True)
            res.add("commands")
        for row in _rows(con, "CommandsNotesHistory", have):
            m = cn_map.get(int(row.get("cmd_id") or -1))
            if not m or not m[1]:
                continue
            row["cmd_id"] = m[0]
            _insert(cur, "CommandsNotesHistory", row, live["CommandsNotesHistory"])
        # ---- linear chains (Playbooks without a diagram; diagram chains go through chain_history below)
        graphs = _graph_ids(con, have)
        ptaken = {_kci(r[0]) for r in lc.execute("SELECT name FROM Playbooks").fetchall()}
        callers = {_s(r[0]).lower() for r in lc.execute("SELECT caller FROM Playbooks WHERE caller IS NOT NULL AND caller<>''").fetchall()} if "caller" in live["Playbooks"] else set()
        pb_map = {}
        for row in _rows(con, "Playbooks", have):
            if int(row["id"]) in graphs:
                continue
            name = _s(row.get("name"))
            if _kci(name) in ptaken:
                if clash == "skip":
                    res.skip("chains")
                    continue
                row["name"] = _free(name, ptaken)
                res.ren("chains")
            ptaken.add(_kci(row["name"]))
            if "caller" in live["Playbooks"]:
                c = _s(row.get("caller")).strip()
                if not c or c.lower() in callers:
                    from Cores import chain_callers as _cc
                    c = _cc.suggest_caller(row["name"], callers)
                row["caller"] = c
                callers.add(c.lower())
            pb_map[int(row["id"])] = int(_insert(cur, "Playbooks", row, live["Playbooks"]))
            res.add("chains")
        for row in _rows(con, "PlaybookSteps", have):
            pid = pb_map.get(int(row.get("playbook_id") or -1))
            if pid is None:
                continue
            csrc = _s(row.get("command_src"))
            cid = int(row.get("command_id") or -1)
            new_cid = cmd_map.get(cid) if csrc == "Commands" else (cn_map.get(cid) or (None,))[0] if csrc == "CommandsNotes" else None
            if new_cid is None:
                continue
            row["playbook_id"], row["command_id"] = pid, new_cid
            _insert(cur, "PlaybookSteps", row, live["PlaybookSteps"])
        src.cmd_map = dict(cmd_map)
        src.cn_map = {k: v[0] for k, v in cn_map.items()}
        _import_reports(con, have, lc, cur, live, res, clash)
    finally:
        con.close()


def _uid_taken(lc, table, uid):
    return lc.execute(f'SELECT 1 FROM "{table}" WHERE uid=?', (uid,)).fetchone() is not None


def _import_reports(con, have, lc, cur, live, res, clash):
    # Images and evidence are shared by uid: one already here is reused, not duplicated.
    for row in _rows(con, "ReportAssets", have):
        if _uid_taken(lc, "ReportAssets", row.get("uid")):
            continue
        _insert(cur, "ReportAssets", row, live["ReportAssets"])
    ev_map = {}
    for row in _rows(con, "ReportEvidence", have):
        old = int(row["id"])
        if _uid_taken(lc, "ReportEvidence", row.get("uid")):
            res.skip("evidence")
            continue
        ev_map[old] = int(_insert(cur, "ReportEvidence", row, live["ReportEvidence"]))
        res.add("evidence")
    for row in _rows(con, "ReportEvidenceEvents", have):
        e = ev_map.get(int(row.get("evidence_id") or -1))
        if e is None:
            continue
        row["evidence_id"] = e
        _insert(cur, "ReportEvidenceEvents", row, live["ReportEvidenceEvents"])
    for table, field, kind in (("ReportTemplates", "name", "report_templates"), ("FindingLibrary", "title", "findings_library")):
        taken = {_kci(r[0]) for r in lc.execute(f'SELECT {field} FROM "{table}"').fetchall()}
        for row in _rows(con, table, have):
            val = _s(row.get(field))
            if _kci(val) in taken:
                if clash == "skip":
                    res.skip(kind)
                    continue
                row[field] = _free(val, taken)
                res.ren(kind)
            if _uid_taken(lc, table, row.get("uid")):
                row["uid"] = uuid.uuid4().hex
            taken.add(_kci(row[field]))
            _insert(cur, table, row, live[table])
            res.add(kind)
    taken = {_kci(r[0]) for r in lc.execute("SELECT title FROM Reports").fetchall()}
    rmap = {}
    for row in _rows(con, "Reports", have):
        old = int(row["id"])
        title = _s(row.get("title"))
        if _kci(title) in taken:
            if clash == "skip":
                res.skip("reports")
                continue
            row["title"] = _free(title, taken)
            res.ren("reports")
        if _uid_taken(lc, "Reports", row.get("uid")):
            row["uid"] = uuid.uuid4().hex
        taken.add(_kci(row["title"]))
        rmap[old] = int(_insert(cur, "Reports", row, live["Reports"]))
        res.add("reports")
    fmap = {}
    for table in ("ReportSections", "ReportFindings", "ReportVersions", "ReportTargets"):
        for row in _rows(con, table, have):
            r = rmap.get(int(row.get("report_id") or -1))
            if r is None:
                continue
            old = int(row["id"])
            row["report_id"] = r
            new = int(_insert(cur, table, row, live[table]))
            if table == "ReportFindings":
                fmap[old] = new
    for row in _rows(con, "ReportFindingTargets", have):
        f = fmap.get(int(row.get("finding_id") or -1))
        if f is None:
            continue
        row["finding_id"] = f
        _insert(cur, "ReportFindingTargets", row, live["ReportFindingTargets"])


def _import_chains(src, res, clash):
    """Diagram chains and run history through the chain bundle import (validated, hardened, unreviewed, run vars dropped)."""
    if not src.db:
        return
    from Cores.Services import chain_history as _hist
    bundle = _hist.bundle_from_db(src.db, src.db_key)
    if not bundle["chains"] and not bundle["runs"]:
        return
    out = _hist.import_bundle(bundle, {"chains": "skip" if clash == "skip" else "rename", "runs": "skip"}, origin="work import")
    created = out["chains"]["created"]
    res.add("chains", len(created))
    res.skip("chains", len(out["chains"]["skipped"]))
    names = {_kci(c.get("name")) for c in bundle["chains"] if isinstance(c, dict)}
    ren = sum(1 for c in created if _kci(c.get("name")) not in names)
    if ren:
        res.ren("chains", ren)
    res.add("chain_runs", int(out["runs"]["imported"]))
    if out["runs"]["skipped"]:
        res.skip("chain_runs", int(out["runs"]["skipped"]))


def _import_attachments(src, res, note_map):
    if not note_map:
        return
    from Cores.Services import notes_service as _ns
    with _common_db.connection(timeout=10) as lc:
        for old, files in src.attachments.items():
            m = note_map.get(int(old))
            if not m:
                continue
            new_id = m[0]
            d = _ns._attachments_note_dir(new_id)
            for name, p in files:
                _ns._write_attachment(os.path.join(d, name), src.read_bytes(p))
                res.add("attachments")
            row = lc.execute("SELECT content FROM Notes WHERE id=?", (new_id,)).fetchone()
            if row:
                new = _rewrite_attachment_urls(row[0], old, d)
                if new != _s(row[0]):
                    lc.execute("UPDATE Notes SET content=? WHERE id=?", (new, new_id))
        # Old ids that kept their attachments elsewhere are rewritten too, so no note points at another note's folder.
        for old, (new_id, _n) in note_map.items():
            if old in src.attachments:
                continue
            row = lc.execute("SELECT content FROM Notes WHERE id=?", (new_id,)).fetchone()
            if row and "Attachments" in _s(row[0]):
                new = _rewrite_attachment_urls(row[0], old, _ns._attachments_note_dir(new_id))
                if new != _s(row[0]):
                    lc.execute("UPDATE Notes SET content=? WHERE id=?", (new, new_id))


def _import_targets(src, res, clash):
    from Cores import target_profiles as _tp
    srcp = {p["id"]: p for p in _source_profiles(src)}
    for pid, targets, values in _source_target_sets(src):
        lpid, new_profile = _resolve_profile(pid, src)
        if new_profile:
            live = _live_profiles()
            names = {_kci(p.get("name")) for p in live}
            name = _s((srcp.get(pid) or {}).get("name")) or pid
            if _kci(name) in names:
                name = _free(name, names, 80)
            live.append({"id": pid, "name": name, "created_at": _s((srcp.get(pid) or {}).get("created_at")) or "", "active": False})
            _live_write("profiles.json", live)
            res.add("target_profiles")
        base = _live_read(_targets_doc(lpid), [])
        base = base if isinstance(base, list) else ([base] if isinstance(base, dict) else [])
        keys = {_target_key(x) for x in base}
        names = {_kci(x.get("name")) for x in base if isinstance(x, dict)}
        for t in targets:
            k = _target_key(t)
            if k in keys:
                if clash == "skip" or not isinstance(t, dict):
                    res.skip("targets")
                    continue
                t = dict(t)
                t["name"] = _free(t.get("name") or t.get("id"), names, 120)
                if _s(t.get("id")).strip():
                    t["id"] = uuid.uuid4().hex[:16]
                res.ren("targets")
                k = _target_key(t)
            keys.add(k)
            if isinstance(t, dict):
                names.add(_kci(t.get("name")))
            base.append(t)
            res.add("targets")
        _live_write(_targets_doc(lpid), base)
        vals = _live_read(_values_doc(lpid), {})
        vals = vals if isinstance(vals, dict) else {}
        for k, v in values.items():
            if not _s(k).strip():
                continue
            if k in vals:
                res.skip("target_values")
                continue
            vals[k] = v
            res.add("target_values")
        _live_write(_values_doc(lpid), vals)
    _tp.list_profiles()   # makes sure one profile is active


def _import_docs(src, res, clash, note_map):
    meta = src.docs.get("notes_meta.json")
    if isinstance(meta, dict):
        live = _live_read("notes_meta.json", {})
        live = live if isinstance(live, dict) else {}
        groups = list(live.get("groups") or [])
        low = {_kci(g) for g in groups}
        for g in meta.get("groups") or []:
            if _s(g).strip() and _kci(g) not in low:
                groups.append(g)
                low.add(_kci(g))
        pinned = list(live.get("pinned") or [])
        for ref in meta.get("pinned") or []:
            nid = ref.get("note_id") if isinstance(ref, dict) else None
            try:
                m = note_map.get(int(nid))
            except (TypeError, ValueError):
                m = None
            if m:
                pinned.append({"note_id": m[0], "note_name": m[1]})
        live.update({"groups": groups, "pinned": pinned})
        live.setdefault("recent", [])
        live.setdefault("nav_collapsed_groups", [])
        _live_write("notes_meta.json", live)
        res.add("notes_meta")
    tc = src.docs.get("tag_colors.json")
    if isinstance(tc, dict):
        live = _live_read("tag_colors.json", {})
        live = live if isinstance(live, dict) else {}
        for k, v in tc.items():
            if k in live:
                res.skip("tag_colors")
                continue
            live[k] = v
            res.add("tag_colors")
        _live_write("tag_colors.json", live)
    nt = src.docs.get("notes_templates.json")
    if isinstance(nt, list):
        live = _live_read("notes_templates.json", [])
        live = live if isinstance(live, list) else []
        names = {_kci(t.get("name")) for t in live if isinstance(t, dict)}
        ids = {_s(t.get("id")) for t in live if isinstance(t, dict)}
        for t in nt:
            if not isinstance(t, dict):
                continue
            t = dict(t)
            if _kci(t.get("name")) in names:
                if clash == "skip":
                    res.skip("note_templates")
                    continue
                t["name"] = _free(t.get("name"), names, 120)
                res.ren("note_templates")
            if _s(t.get("id")) in ids:
                t["id"] = uuid.uuid4().hex[:16]
            names.add(_kci(t["name"]))
            ids.add(_s(t.get("id")))
            live.append(t)
            res.add("note_templates")
        _live_write("notes_templates.json", live)
    ss = src.docs.get("saved_searches.json")
    if isinstance(ss, list):
        live = _live_read("saved_searches.json", [])
        live = live if isinstance(live, list) else []
        have = {json.dumps(x, sort_keys=True, ensure_ascii=False) for x in live}
        for x in ss:
            j = json.dumps(x, sort_keys=True, ensure_ascii=False)
            if j not in have:
                live.append(x)
                have.add(j)
        _live_write("saved_searches.json", live)
    q = src.docs.get("QuicSpace.json")
    if _quick_text(q):
        live = _live_read("QuicSpace.json", {})
        live = live if isinstance(live, dict) else {}
        if not _quick_text(live):
            live.update({"html": _s(q.get("html")), "text": _s(q.get("text"))})
            res.add("quick_space")
        elif _quick_text(live) == _quick_text(q) or clash == "skip":
            res.skip("quick_space")
        else:
            # Quick Space is one scratch page: the imported text is added below the live one.
            live["html"] = _s(live.get("html")) + "<hr><div>Imported</div>" + _s(q.get("html"))
            live["text"] = _s(live.get("text")).rstrip("\n") + "\n\n--- Imported ---\n" + _s(q.get("text"))
            res.add("quick_space")
            res.ren("quick_space")
        _live_write("QuicSpace.json", live)


def _import_files(src, res, clash):
    if src.chain_files:
        cdir = os.path.join(_data_dir(), "chain")
        os.makedirs(cdir, exist_ok=True)
        live = {n.lower() for n in os.listdir(cdir)}
        for name, p in src.chain_files:
            dst = name
            if name.lower() in live:
                if clash == "skip":
                    res.skip("chain_files")
                    continue
                stem = name[:-5]
                dst = _free(stem, {n[:-5] for n in live if n.endswith(".html")}) + ".html"
                res.ren("chain_files")
            live.add(dst.lower())
            out = os.path.join(cdir, dst)
            with open(out, "wb") as f:
                f.write(src.read_bytes(p))
            if os.name != "nt":
                try:
                    os.chmod(out, 0o600)
                except OSError:
                    pass
            res.add("chain_files")
    for name, obj in src.ai_chats:
        rel = f"ai_sessions/{name}"
        if _doc_store.exists(_live_doc_path(rel)):
            if clash == "skip":
                res.skip("ai_chats")
                continue
            rel = f"ai_sessions/imported_{uuid.uuid4().hex[:8]}_{name}"
            res.ren("ai_chats")
        _live_write(rel, obj)
        res.add("ai_chats")


def _merged_settings(src):
    from Cores.Services import settings_service as _ss
    live = _ss._read_settings()
    live = live if isinstance(live, dict) else {}
    port = _portable_settings(src.settings)

    def merge(dst, inc):
        for k, v in inc.items():
            if isinstance(v, dict) and isinstance(dst.get(k), dict):
                merge(dst[k], v)
            else:
                dst[k] = v
    merge(live, {k: v for k, v in port.items() if k != "security"})
    return live


def _apply_settings(src, res):
    if not src.settings:
        return
    from Cores import settings_lock as _slock
    from Cores.Services import settings_service as _ss
    with _slock.SETTINGS_LOCK:
        live = _merged_settings(src)
        ok = _ss._write_settings(live)
    if not ok:
        raise ValueError("Could not save the imported settings.")
    res.add("settings")


def _favourite_keys(src):
    """'Table:id' keys of the imported Quick Run favourites, pointing at the live command rows (imported or matching)."""
    out = []
    favs = (src.quick_run or {}).get("favorites") or []
    if not favs:
        return out
    with _common_db.connection(timeout=10) as lc:
        for f in favs:
            table = _s(f.get("source"))
            if table not in ("Commands", "CommandsNotes"):
                continue
            try:
                old = int(f.get("id"))
            except (TypeError, ValueError):
                old = None
            new = (src.cmd_map if table == "Commands" else src.cn_map).get(old) if old is not None else None
            if new is None:
                key = (_kci(f.get("note_name")), _kci(f.get("category")), _kci(f.get("sub_category")), _s(f.get("command")).strip())
                for rid, nn, cat, sub, cmd in lc.execute(f'SELECT id,note_name,category,sub_category,command FROM "{table}"').fetchall():
                    if (_kci(nn), _kci(cat), _kci(sub), _s(cmd).strip()) == key:
                        new = int(rid)
                        break
            if new is not None:
                out.append(f"{table}:{int(new)}")
    return out


def _import_quick_run(src, res, mode):
    """Quick Run favourites are content: they apply without apply_settings, and only mini_window.favorites is written."""
    if src.quick_run is None and mode != "replace":
        return
    keys = _favourite_keys(src)
    from Cores import settings_lock as _slock
    from Cores.Services import settings_service as _ss
    with _slock.SETTINGS_LOCK:
        live = _ss._read_settings()
        live = live if isinstance(live, dict) else {}
        mw = live.get("mini_window") if isinstance(live.get("mini_window"), dict) else {}
        cur = [str(x) for x in (mw.get("favorites") or []) if str(x).strip()] if isinstance(mw.get("favorites"), list) else []
        if mode == "replace":
            new = list(dict.fromkeys(keys))
            added = len(new)
        else:
            new = list(cur)
            added = 0
            for k in keys:
                if k in new:
                    res.skip("quick_run")
                    continue
                new.append(k)
                added += 1
        if new == cur:
            return
        mw["favorites"] = new
        if mode == "replace" and src.quick_run is not None:
            mw["favorites_only"] = bool(src.quick_run.get("favorites_only"))
        live["mini_window"] = mw
        ok = _ss._write_settings(live)
    if not ok:
        raise ValueError("Could not save the Quick Run favourites.")
    if added:
        res.add("quick_run", added)


def apply(path, mode="merge", clash="rename", password=None, apply_settings=False, pin=None):
    if mode not in ("merge", "replace"):
        raise ValueError("Invalid import mode.")
    if clash not in ("rename", "skip"):
        clash = "rename"
    _guard()
    res = _Result(mode)
    with _open(path, password, pin) as src:
        note_map = {}
        with _common_db.connection(timeout=15) as lc:
            _common_db.ensure_schema(lc)
            if mode == "replace":
                _clear_live_content(lc)
            if src.db:
                _import_db(src, lc, res, clash, note_map)
        if mode == "replace":
            _clear_live_docs(src)
        _import_chains(src, res, clash)
        _import_attachments(src, res, note_map)
        _import_targets(src, res, clash)
        _import_docs(src, res, clash, note_map)
        _import_files(src, res, clash)
        if apply_settings:
            _apply_settings(src, res)
        _import_quick_run(src, res, mode)
        fmt = src.format
    _audit(fmt, mode, res)
    total = sum(res.added.values())
    msg = f"Import done: {total} item(s) added" + (f", {sum(res.renamed.values())} renamed" if res.renamed else "") + \
          (f", {sum(res.skipped.values())} skipped" if res.skipped else "") + "."
    if res.added.get("chains"):
        msg += " Imported chains must be reviewed before they run."
    return {"added": res.added, "renamed": res.renamed, "skipped": res.skipped, "mode": mode, "format": fmt, "message": msg}


def _audit(fmt, mode, res):
    try:
        from Cores.Services import security_service as _sec
        _sec.log_audit_event("work_import", f"work import ({fmt}, {mode}): {sum(res.added.values())} item(s) added", True)
    except Exception:
        pass
