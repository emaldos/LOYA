"""JSON stores that move into the encrypted DB (storage rebuild, phase 2).

Data/ used to hold plaintext JSON next to the database: targets (with credentials), profiles, notes meta, templates, unsaved
drafts, terminal sessions (scrollback), QuicSpace, AI chats, the search index, recent searches, tag colours and external agent
usage. With encryption at rest on (common_db.encryption_configured()) each of those files is one row of AppDocs inside the
SQLCipher database instead, so nothing readable is left on disk - not after a crash, not while locked.

With encryption at rest off nothing changes: every call below falls through to the plain file, exactly as before. Services
keep using the same paths; they call doc_store.read_json/write_json/exists/mtime/remove instead of touching the file.

While locked (encryption on, no session key) reads return the default and writes fail (False): the stores are not reachable,
and nothing is ever written in plaintext as a fallback.
"""
import json
import os
import threading
import time

from Cores import common_db as _common_db

# Paths relative to Data/, forward slashes. Order does not matter.
DOC_PATTERNS = (
    "profiles.json",
    "Targets.json",
    "Targes.json",
    "target_values.json",
    "Profiles/*/Targets.json",
    "Profiles/*/target_values.json",
    "notes_meta.json",
    "notes_templates.json",
    "note_draft_recovery.json",
    "terminal_sessions.json",
    "QuicSpace.json",
    "ai_sessions/*.json",
    "search_index/index.json",
    "saved_searches.json",
    "recent_searches.json",
    "palette_recent.json",
    "tag_colors.json",
    "external_agents/usage.json",
    "external_agents/sessions.json",
)
_LOCK = threading.RLock()
_TABLE_OK = set()


def rel_name(path):
    """'Profiles/abc/Targets.json' for a doc path under Data/, else None."""
    if not path:
        return None
    try:
        base = os.path.normcase(os.path.abspath(_common_db.data_dir()))
        full = os.path.normcase(os.path.abspath(path))
    except Exception:
        return None
    if not full.startswith(base + os.sep):
        return None
    rel = os.path.relpath(os.path.abspath(path), os.path.abspath(_common_db.data_dir())).replace("\\", "/")
    if rel.startswith("../"):
        return None
    return rel if _match(rel) else None


def is_doc_path(path):
    return rel_name(path) is not None


def active(path=None):
    """True when the DB (not the file) is the store: encryption at rest is on (and, given a path, it is a doc path)."""
    if not _common_db.encryption_configured():
        return False
    return path is None or is_doc_path(path)


def available():
    """The doc table can be reached now (unlocked)."""
    return _common_db.session_key() is not None and not _common_db.is_locked()


def _con():
    con = _common_db.connect(timeout=10)
    key = _common_db.db_path()
    if key not in _TABLE_OK:
        try:
            _common_db._create_storage_tables(con.cursor())
            con.commit()
            _TABLE_OK.add(key)
        except Exception:
            pass
    return con


def _dumps(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- plain-file fallbacks (encryption off)

def _file_read(path, default):
    try:
        if not os.path.isfile(path):
            return default
        with open(path, "r", encoding="utf-8") as f:
            v = json.load(f)
        return v if v is not None else default
    except Exception:
        return default


def _file_write(path, obj):
    t = "%s.%d.%d.tmp" % (path, os.getpid(), threading.get_ident())
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(t, "w", encoding="utf-8") as f:
            f.write(_dumps(obj))
        os.replace(t, path)
        return True
    except Exception:
        try:
            if os.path.isfile(t):
                os.remove(t)
        except Exception:
            pass
        return False


# ---------------------------------------------------------------- DB-backed rows (encryption on)

def get_raw(rel):
    """(data_text, mtime) for a doc row, or None. Raises DatabaseLocked when locked."""
    con = _con()
    try:
        row = con.execute("SELECT data,mtime FROM AppDocs WHERE name=?", (rel,)).fetchone()
        return (row[0], row[1]) if row else None
    finally:
        con.close()


def put_raw(rel, text, mtime=None, con=None):
    mtime = time.time() if mtime is None else float(mtime)
    own = con is None
    con = con or _con()
    try:
        con.execute("INSERT INTO AppDocs(name,data,mtime,size) VALUES(?,?,?,?) ON CONFLICT(name) DO UPDATE SET data=excluded.data,mtime=excluded.mtime,size=excluded.size",
                    (rel, text, mtime, len(text.encode("utf-8"))))
        if own:
            con.commit()
    finally:
        if own:
            con.close()


def list_names(prefix=""):
    con = _con()
    try:
        rows = con.execute("SELECT name FROM AppDocs ORDER BY name").fetchall()
    finally:
        con.close()
    return [r[0] for r in rows if r[0].startswith(prefix)]


# ---------------------------------------------------------------- public API (path based)

def read_json(path, default=None):
    if not active(path):
        return _file_read(path, default)
    try:
        with _LOCK:
            row = get_raw(rel_name(path))
        if not row:
            return default
        v = json.loads(row[0])
        return v if v is not None else default
    except Exception:
        return default


def write_json(path, obj):
    if not active(path):
        return _file_write(path, obj)
    try:
        text = _dumps(obj)
        with _LOCK:
            put_raw(rel_name(path), text)
        return True
    except Exception:
        return False


def exists(path):
    if not active(path):
        return os.path.isfile(path)
    try:
        with _LOCK:
            return get_raw(rel_name(path)) is not None
    except Exception:
        return False


def mtime(path):
    """Modification time (epoch seconds) of the store, or None when it does not exist / cannot be read."""
    if not active(path):
        try:
            return os.path.getmtime(path)
        except OSError:
            return None
    try:
        with _LOCK:
            row = get_raw(rel_name(path))
        return float(row[1]) if row else None
    except Exception:
        return None


def signature(path):
    """A change detector like (st_mtime_ns, st_size); None when missing."""
    if not active(path):
        try:
            st = os.stat(path)
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None
    try:
        con = _con()
        try:
            row = con.execute("SELECT mtime,size FROM AppDocs WHERE name=?", (rel_name(path),)).fetchone()
        finally:
            con.close()
        return (int(float(row[0]) * 1e9), int(row[1] or 0)) if row else None
    except Exception:
        return None


def remove(path):
    if not active(path):
        try:
            if os.path.isfile(path):
                os.remove(path)
            return True
        except OSError:
            return False
    try:
        with _LOCK:
            con = _con()
            try:
                con.execute("DELETE FROM AppDocs WHERE name=?", (rel_name(path),))
                con.commit()
            finally:
                con.close()
        return True
    except Exception:
        return False


def remove_dir(dirpath):
    """Delete every doc under a Data/ sub-folder (e.g. a deleted profile's Profiles/<id>/)."""
    if not _common_db.encryption_configured():
        return
    try:
        rel = os.path.relpath(os.path.abspath(dirpath), os.path.abspath(_common_db.data_dir())).replace("\\", "/").rstrip("/") + "/"
    except Exception:
        return
    if rel.startswith("../"):
        return
    try:
        with _LOCK:
            con = _con()
            try:
                con.execute("DELETE FROM AppDocs WHERE substr(name,1,?)=?", (len(rel), rel))
                con.commit()
            finally:
                con.close()
    except Exception:
        pass


# ---------------------------------------------------------------- migration helpers

def iter_files(data_dir=None):
    """(rel, abs_path) of every doc file present on disk under data_dir (for import into the DB)."""
    root = os.path.abspath(data_dir or _common_db.data_dir())
    for d, dirs, files in os.walk(root):
        for n in files:
            p = os.path.join(d, n)
            rel = os.path.relpath(p, root).replace("\\", "/")
            if _match(rel):
                yield rel, p


def _match(rel):
    for pat in DOC_PATTERNS:
        if "*" in pat:
            head, tail = pat.split("*", 1)
            if rel.startswith(head) and rel.endswith(tail) and "/" not in rel[len(head):len(rel) - len(tail)] and len(rel) > len(head) + len(tail):
                return True
        elif rel == pat:
            return True
    return False
