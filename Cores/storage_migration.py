"""Turning encryption at rest on and off (storage rebuild, phase 2): a step-journalled, resumable migration.

enable(dek, keyfile)  plain SQLite + plaintext JSON stores + plain attachments, or a v1 Fernet `.db.enc` (legacy=...)
                      ->  SQLCipher DB (raw key from the envelope data key) + stores in AppDocs + encrypted files.
disable(dek)          the reverse, for a user who turns encryption off with the typed PIN.

Every step is recorded in Data/storage_migration.json (plaintext, never a secret). Nothing original is modified before the
commit step, so a failure or a crash before it rolls back by deleting the work folder (Data/.migrate/). The commit itself is a
short sequence of renames plus one settings flip, all repeatable without the key, so recover() can always finish it at the
next start. A verified encrypted backup (.loyabak) of the pre-migration state is written before anything else.

The caller (security_service) holds the DB lock (common_db.set_locked(True)) and waits for open connections to close before
calling enable()/disable(), so no service can write while files move. Windows: os.replace onto an open file fails, which is
why that wait matters; crypto_store._replace retries briefly for antivirus/indexer handles.
"""
import base64
import json
import os
import shutil
import threading
import time
import zipfile
from datetime import datetime, timezone

from Cores import common_db as _common_db
from Cores import crypto_store as _cs
from Cores import db_driver as _drv
from Cores import doc_store as _docs
from Cores import loyabak as _loyabak

JOURNAL_NAME = "storage_migration.json"
WORK_NAME = ".migrate"
FILE_STORE_DIRS = ("Attachments", "job_output")  # encrypted in place (crypto_store streams) while encryption is on
BACKUP_SKIP_DIRS = ("cve_index", WORK_NAME, "_backups")  # public CVE index: plain, regenerable, never backed up
_RUN_LOCK = threading.Lock()
STEPS_ENABLE = ("prepared", "backed_up", "exported", "docs_imported", "files_ready", "committing", "committed")


class MigrationError(Exception):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat()


def _data():
    return _common_db.data_dir()


def journal_path():
    return os.path.join(_data(), JOURNAL_NAME)


def work_dir():
    return os.path.join(_data(), WORK_NAME)


def read_journal():
    try:
        with open(journal_path(), "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def _write_journal(d):
    d = dict(d, updated_at=_now())
    with _cs.atomic_write(journal_path()) as f:
        f.write((json.dumps(d, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return d


def _clear_journal():
    try:
        os.remove(journal_path())
    except OSError:
        pass


def _rmtree(p):
    if os.path.isdir(p):
        shutil.rmtree(p, ignore_errors=True)


def _private_dir(p):
    os.makedirs(p, mode=0o700, exist_ok=True)
    if os.name != "nt":
        try:
            os.chmod(p, 0o700)
        except OSError:
            pass
    return p


def _audit(event, detail, ok=True):
    try:
        from Cores.Services import security_service as _sec
        _sec.log_audit_event(event, detail, ok)
    except Exception:
        pass


def _settings_path():
    return os.path.join(_data(), "settings.json")


def _update_security(values=None, drop=()):
    from Cores import settings_lock as _sl

    def mutate(d):
        cur = d.get("security") if isinstance(d.get("security"), dict) else {}
        cur.update(values or {})
        for k in drop:
            cur.pop(k, None)
        d["security"] = cur
    if not _sl.update_json(_settings_path(), mutate):
        raise MigrationError("Could not write settings.json.")


def _remove_quiet(p):
    try:
        if os.path.isfile(p):
            os.remove(p)
        return True
    except OSError:
        return False


def _shred(p):
    """Best effort: overwrite a small plaintext file with zeros before unlinking. SSD wear levelling and file-system journals
    can still hold older copies; full-disk encryption is the real answer to that."""
    try:
        n = os.path.getsize(p)
        if n <= 64 * 1024 * 1024:
            with open(p, "r+b") as f:
                f.write(b"\0" * n)
                f.flush()
                os.fsync(f.fileno())
    except OSError:
        pass
    return _remove_quiet(p)


def _sidecars(dbp):
    for s in ("-wal", "-shm", "-journal"):
        _remove_quiet(dbp + s)


# ---------------------------------------------------------------- legacy v1 (Fernet whole-file copy)

def legacy_fernet(pin, enc_salt_b64):
    """The v1 key: Fernet(PBKDF2-SHA256(PIN, enc_salt, 200k)). Used only to read a v1 .db.enc / key_enc once."""
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    salt = base64.b64decode(enc_salt_b64 or "")
    if not salt:
        raise MigrationError("The legacy encryption salt is missing.")
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=200000)
    return Fernet(base64.urlsafe_b64encode(kdf.derive(str(pin).encode("utf-8"))))


def _legacy_decrypt_db(fernet, enc_path, dst):
    from cryptography.fernet import InvalidToken
    with open(enc_path, "rb") as f:
        blob = f.read()
    try:
        plain = fernet.decrypt(blob)
    except InvalidToken:
        raise MigrationError("The legacy encrypted database does not open with this PIN.")
    fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(plain)
        out.flush()
        os.fsync(out.fileno())


# ---------------------------------------------------------------- pieces

def _snapshot_plain(src, dst):
    """Consistent copy of a plain SQLite DB (WAL content included) via the backup API."""
    s = _drv.connect(src, timeout=30)
    try:
        d = _drv.connect(dst)
        try:
            s.backup(d)
        finally:
            d.close()
    finally:
        s.close()
    if os.name != "nt":
        os.chmod(dst, 0o600)


def _iter_file_store(root=None):
    root = root or _data()
    for top in FILE_STORE_DIRS:
        base = os.path.join(root, top)
        if not os.path.isdir(base):
            continue
        for d, dirs, files in os.walk(base):
            for n in files:
                if n.endswith(".tmp"):
                    continue
                p = os.path.join(d, n)
                yield os.path.relpath(p, root).replace("\\", "/"), p


def _backup_members(plain_db=None, root=None):
    """(arcname, path) of everything a data backup holds. The main DB comes from plain_db (a consistent copy) when given."""
    root = root or _data()
    main = os.path.normcase(os.path.abspath(_common_db.db_path()))
    skip_exact = {JOURNAL_NAME, "Note_LOYA_V1.key"}
    for d, dirs, files in os.walk(root):
        rel_d = os.path.relpath(d, root).replace("\\", "/")
        dirs[:] = [x for x in dirs if not (rel_d == "." and x in BACKUP_SKIP_DIRS)]
        for n in files:
            p = os.path.join(d, n)
            rel = os.path.relpath(p, root).replace("\\", "/")
            ap = os.path.normcase(os.path.abspath(p))
            if rel in skip_exact or n.endswith(".tmp") or n.endswith(".snap") or n.endswith(".probe"):
                continue
            if ap.startswith(main):  # the DB, its -wal/-shm/-journal and the legacy .enc
                continue
            yield rel, p
    if plain_db and os.path.isfile(plain_db):
        yield "Note_LOYA_V1.db", plain_db


def _backups_dir():
    """<app>/Backups for the real Data/; a private sub-folder when Data/ was moved (tests, portable copies)."""
    return _private_dir(_common_db.backups_dir())


def make_loyabak(dek, keyfile, label, plain_db=None, decrypt_files=False, out_dir=None):
    """Zip Data/ (CVE index excluded) and seal it as a verified .loyabak. decrypt_files: file-store members that are
    crypto_store streams are decrypted into the zip (the whole archive is encrypted anyway). Returns the path."""
    out_dir = out_dir or _backups_dir()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = os.path.join(out_dir, f"{label}-{stamp}{_loyabak.EXT}")
    wd = _private_dir(work_dir())
    tmp_zip = os.path.join(wd, f"backup-{os.getpid()}-{threading.get_ident()}.zip")
    try:
        with zipfile.ZipFile(tmp_zip, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for arc, p in _backup_members(plain_db):
                if decrypt_files and _cs.is_encrypted_file(p):
                    with open(p, "rb") as fh:
                        z.writestr(arc, b"".join(_cs.decrypt_stream(fh, dek)))
                else:
                    z.write(p, arc)
            z.writestr("loyabak-manifest.json", json.dumps({"created_at": _now(), "label": label, "format": "loya-data-backup", "v": 1}))
        _loyabak.write(tmp_zip, dst, dek, keyfile, {"kind": "data", "label": label, "created_at": _now()})
        _loyabak.verify(dst, dek)
    finally:
        _shred(tmp_zip)
    return dst


def _verify_docs(con, expected):
    got = {r[0]: r[1] for r in con.execute("SELECT name,data FROM AppDocs").fetchall()}
    for rel, text in expected.items():
        if got.get(rel) != text:
            raise MigrationError(f"Store {rel} did not round-trip into the database.")


# ---------------------------------------------------------------- enable

def enable(dek, keyfile, legacy=None):
    """Plain (or legacy v1) -> encrypted. legacy={"pin":..., "enc_salt":...} when a v1 .db.enc exists.
    Returns a report dict. Raises MigrationError (or db_driver errors); on any error before commit nothing changed."""
    if not _drv.has_sqlcipher():
        raise MigrationError("sqlcipher3 is not installed, so the database cannot be encrypted.")
    with _RUN_LOCK:
        j = read_journal()
        if j and j.get("step") in ("committing", "committed"):
            raise MigrationError("A previous migration is still finishing; restart LOYA NG first.")
        _rollback_work()
        dbp = _common_db.db_path()
        need = _data_size() * 3 + 50 * 1024 * 1024
        free = shutil.disk_usage(_data()).free
        if free < need:
            raise MigrationError(f"Not enough free disk space for the migration (need about {need // (1024 * 1024)} MB).")
        wd = _private_dir(work_dir())
        plain = os.path.join(wd, "plain.db")
        enc = os.path.join(wd, "enc.db")
        source = "empty"
        report = {"op": "enable", "started_at": _now()}
        j = _write_journal({"v": 1, "op": "enable", "step": "prepared", "started_at": report["started_at"]})
        try:
            kind = _drv.file_kind(dbp)
            enc_legacy = dbp + ".enc"
            if legacy and os.path.isfile(enc_legacy):
                # A plaintext DB with rows next to the .enc is newer (a crash while unlocked left it there): keep it.
                if kind == "plain" and _common_db.db_has_data(dbp) and os.path.getmtime(dbp) >= os.path.getmtime(enc_legacy) - 1:
                    _snapshot_plain(dbp, plain)
                    source = "legacy-plaintext"
                else:
                    _legacy_decrypt_db(legacy_fernet(legacy["pin"], legacy["enc_salt"]), enc_legacy, plain)
                    source = "legacy-enc"
            elif kind == "plain":
                _snapshot_plain(dbp, plain)
                source = "plain"
            elif kind == "encrypted":
                raise MigrationError("The database is already encrypted.")
            j = _write_journal(dict(j, source=source))
            report["backup"] = make_loyabak(dek, keyfile, "pre-encryption", plain_db=plain if os.path.isfile(plain) else None)
            j = _write_journal(dict(j, step="backed_up", backup=report["backup"]))
            if os.path.isfile(plain):
                report["db"] = _drv.migrate_plain_to_encrypted(plain, enc, dek)
            else:
                c = _drv.connect(enc, key=dek)
                c.close()
            j = _write_journal(dict(j, step="exported"))
            con = _drv.connect(enc, key=dek)
            try:
                _common_db._create_storage_tables(con.cursor())
                expected = {}
                for rel, p in _docs.iter_files():
                    with open(p, "r", encoding="utf-8", errors="replace") as f:
                        text = f.read()
                    expected[rel] = text
                    _docs.put_raw(rel, text, mtime=os.path.getmtime(p), con=con)
                moved = _audit_into(con)
                con.commit()
                _verify_docs(con, expected)
            finally:
                con.close()
            report["docs"] = sorted(expected)
            report["audit_moved"] = moved
            j = _write_journal(dict(j, step="docs_imported", docs=len(expected)))
            files = 0
            for rel, p in _iter_file_store():
                if _cs.is_encrypted_file(p):
                    continue
                out = os.path.join(wd, "files", rel)
                _private_dir(os.path.dirname(out))
                _cs.encrypt_file(p, out, dek)
                with open(p, "rb") as a, open(out, "rb") as b:
                    same = a.read() == b"".join(_cs.decrypt_stream(b, dek))
                if not same:
                    raise MigrationError(f"{rel} did not round-trip.")
                files += 1
            report["files"] = files
            j = _write_journal(dict(j, step="files_ready", files=files))
        except BaseException as e:
            _rollback_work()
            _audit("storage_migration_failed", f"enable: {type(e).__name__}: {e}", False)
            raise
        _write_journal(dict(j, step="committing"))
        _commit_enable()
        _finish_enable()
        _audit("storage_migrated", f"encryption at rest on (source: {source}, {len(report['docs'])} stores, {report['files']} files)", True)
        return report


def _data_size():
    total = 0
    for rel, p in _backup_members():
        try:
            total += os.path.getsize(p)
        except OSError:
            pass
    try:
        total += os.path.getsize(_common_db.db_path())
    except OSError:
        pass
    return total


def _rollback_work():
    j = read_journal()
    if j and j.get("step") in ("committing", "committed"):
        return False
    _rmtree(work_dir())
    _clear_journal()
    return True


def _audit_path():
    return os.path.join(_data(), "security_audit.jsonl")


def _audit_into(con):
    """Content events (commands, tool calls...) of the plaintext audit log go into the encrypted AuditEvents table."""
    p = _audit_path()
    if not os.path.isfile(p):
        return 0
    from Cores.Services import security_service as _sec
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        _keep, move = _sec.split_audit_lines(f.readlines())
    for e in move:
        con.execute("INSERT INTO AuditEvents(ts,event,detail,success) VALUES(?,?,?,?)",
                    (str(e.get("ts", "")), str(e.get("event", "")), str(e.get("detail", "")), 1 if e.get("success", True) else 0))
    return len(move)


def _audit_keep_only_security():
    p = _audit_path()
    if not os.path.isfile(p):
        return
    from Cores.Services import security_service as _sec
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        keep, move = _sec.split_audit_lines(f.readlines())
    if not move:
        return
    with _cs.atomic_write(p) as out:
        out.write("".join(keep).encode("utf-8"))


def _commit_enable():
    """Repeatable without the key: renames, then the settings flip."""
    wd = work_dir()
    dbp = _common_db.db_path()
    enc = os.path.join(wd, "enc.db")
    if os.path.isfile(enc):
        _sidecars(dbp)
        _cs._replace(enc, dbp)
        if os.name != "nt":
            os.chmod(dbp, 0o600)
    files_root = os.path.join(wd, "files")
    if os.path.isdir(files_root):
        for d, dirs, files in os.walk(files_root):
            for n in files:
                src = os.path.join(d, n)
                rel = os.path.relpath(src, files_root)
                dst = os.path.join(_data(), rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                _cs._replace(src, dst)
    _update_security({"enc_enabled": True, "enc_version": 2})
    _audit_keep_only_security()
    j = read_journal() or {"v": 1, "op": "enable"}
    _write_journal(dict(j, step="committed"))


def _finish_enable():
    """Remove every plaintext copy the encrypted DB now holds. Safe to repeat."""
    dbp = _common_db.db_path()
    for rel, p in list(_docs.iter_files()):
        _shred(p)
    _shred(dbp + ".enc")
    wd = work_dir()
    if os.path.isdir(wd):
        for d, dirs, files in os.walk(wd):
            for n in files:
                _shred(os.path.join(d, n))
        _rmtree(wd)
    _clear_journal()


# ---------------------------------------------------------------- disable

def disable(dek):
    """Encrypted -> plain. Rows of Secrets are dropped (an API key never sits in a plain DB); stores go back to JSON files."""
    with _RUN_LOCK:
        j = read_journal()
        if j and j.get("step") in ("committing", "committed"):
            raise MigrationError("A previous migration is still finishing; restart LOYA NG first.")
        _rollback_work()
        dbp = _common_db.db_path()
        wd = _private_dir(work_dir())
        plain = os.path.join(wd, "plain.db")
        j = _write_journal({"v": 1, "op": "disable", "step": "prepared", "started_at": _now()})
        report = {"op": "disable"}
        try:
            kind = _drv.file_kind(dbp)
            docs = {}
            if kind == "encrypted":
                _drv.export_plain(dbp, plain, dek)
                con = _drv.connect(plain)
                try:
                    try:
                        rows = con.execute("SELECT name,data,mtime FROM AppDocs").fetchall()
                    except _drv.OperationalError:
                        rows = []
                    for name, data, mtime in rows:
                        if not _docs._match(name):
                            continue
                        out = os.path.join(wd, "docs", name)
                        _private_dir(os.path.dirname(out))
                        with _cs.atomic_write(out) as f:
                            f.write(data.encode("utf-8"))
                        try:
                            os.utime(out, (float(mtime), float(mtime)))
                        except Exception:
                            pass
                        docs[name] = data
                    try:
                        arows = con.execute("SELECT ts,event,detail,success FROM AuditEvents ORDER BY ts,id").fetchall()
                    except _drv.OperationalError:
                        arows = []
                    if arows:
                        with _cs.atomic_write(os.path.join(wd, "audit_rows.json")) as f:
                            f.write(json.dumps([{"ts": r[0], "event": r[1], "detail": r[2] or "", "success": bool(r[3])} for r in arows], ensure_ascii=False).encode("utf-8"))
                    for t in ("AppDocs", "Secrets", "AuditEvents"):
                        try:
                            con.execute(f"DELETE FROM {t}")
                        except _drv.OperationalError:
                            pass
                    con.commit()
                    con.execute("VACUUM")  # deleted secret pages must not survive in the plain file
                finally:
                    con.close()
                if os.name != "nt":
                    os.chmod(plain, 0o600)
            j = _write_journal(dict(j, step="exported", docs=len(docs)))
            files = 0
            for rel, p in _iter_file_store():
                if not _cs.is_encrypted_file(p):
                    continue
                out = os.path.join(wd, "files", rel)
                _private_dir(os.path.dirname(out))
                _cs.decrypt_file(p, out, dek)
                files += 1
            report.update(docs=sorted(docs), files=files)
            j = _write_journal(dict(j, step="files_ready", files=files))
        except BaseException as e:
            _rollback_work()
            _audit("storage_migration_failed", f"disable: {type(e).__name__}: {e}", False)
            raise
        _write_journal(dict(j, step="committing"))
        _commit_disable()
        _finish_disable()
        _audit("storage_migrated", f"encryption at rest off ({len(report['docs'])} stores, {report['files']} files)", True)
        return report


def _commit_disable():
    wd = work_dir()
    dbp = _common_db.db_path()
    plain = os.path.join(wd, "plain.db")
    if os.path.isfile(plain):
        _sidecars(dbp)
        _cs._replace(plain, dbp)
    for sub in ("docs", "files"):
        root = os.path.join(wd, sub)
        if not os.path.isdir(root):
            continue
        for d, dirs, files in os.walk(root):
            for n in files:
                src = os.path.join(d, n)
                dst = os.path.join(_data(), os.path.relpath(src, root))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                _cs._replace(src, dst)
    rows_p = os.path.join(wd, "audit_rows.json")
    if os.path.isfile(rows_p):
        with open(rows_p, "r", encoding="utf-8") as f:
            rows = json.load(f)
        cur = []
        if os.path.isfile(_audit_path()):
            with open(_audit_path(), "r", encoding="utf-8", errors="replace") as f:
                cur = [ln if ln.endswith("\n") else ln + "\n" for ln in f.readlines() if ln.strip()]
        merged = cur + [json.dumps(r, ensure_ascii=False) + "\n" for r in rows]

        def ts(line):
            try:
                return str(json.loads(line).get("ts", ""))
            except Exception:
                return ""
        merged.sort(key=ts)
        with _cs.atomic_write(_audit_path()) as out:
            out.write("".join(merged).encode("utf-8"))
        os.remove(rows_p)
    _update_security({"enc_enabled": False, "enc_version": 0})
    j = read_journal() or {"v": 1, "op": "disable"}
    _write_journal(dict(j, step="committed"))


def _finish_disable():
    _rmtree(work_dir())
    _clear_journal()


# ---------------------------------------------------------------- recovery

def recover():
    """Call at startup and before any migration: roll back an unfinished migration, or finish a committed one. Needs no key.
    Returns what it did: None | "rolled_back" | "finished"."""
    with _RUN_LOCK:
        j = read_journal()
        if not j:
            if os.path.isdir(work_dir()):
                _rmtree(work_dir())  # a work folder without a journal never reached its commit
                return "rolled_back"
            return None
        step, op = j.get("step"), j.get("op")
        if step not in ("committing", "committed"):
            _rollback_work()
            _audit("storage_migration_rolled_back", f"{op}: stopped at step {step}", True)
            return "rolled_back"
        if op == "enable":
            if step == "committing":
                _commit_enable()
            _finish_enable()
        else:
            if step == "committing":
                _commit_disable()
            _finish_disable()
        _audit("storage_migration_finished", f"{op}: finished after a restart", True)
        return "finished"
