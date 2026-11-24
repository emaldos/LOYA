"""The one place LOYA NG opens SQLite databases (storage rebuild, phase 1).

Why a shim
----------
sqlcipher3 ships its own SQLite build with its own exception classes and its own Row type:
`sqlcipher3.Error` is NOT a `sqlite3.Error`, and `sqlite3.Row` refuses sqlcipher3 cursors.
Code that does `except sqlite3.IntegrityError` silently stops catching anything once the
connection is a sqlcipher3 one. Everything therefore goes through this module:

    from Cores import db_driver
    con = db_driver.connect(path, key=dek)        # key=None -> plain, unencrypted file
    con.row_factory = db_driver.Row
    try: ...
    except (db_driver.IntegrityError, ValueError): ...

One driver per process
----------------------
DRIVER is sqlcipher3 when it can be imported, else the stdlib sqlite3 (or forced with the
environment variable LOYA_DB_DRIVER=sqlite3). Every connection, keyed or not, uses DRIVER:
sqlcipher3 without a key reads and writes ordinary SQLite files, byte-compatible with sqlite3.
So Error, IntegrityError, OperationalError, Row, ... are the real classes of that one driver,
and `except db_driver.X`, `except (db_driver.X, ValueError)`, isinstance() and subclassing
all behave normally.

Why not tuples of both drivers' classes: Python 3 rejects nested tuples in `except`
("catching classes that do not inherit from BaseException is not allowed"), so
`except (db_driver.Error, ValueError)` would blow up at the moment of the error. For
transition code that must catch an error from either library, ANY_ERROR is a flat tuple
(`except db_driver.ANY_ERROR:` or `except (*db_driver.ANY_ERROR, ValueError):`).

Do not mix libraries on one file: two different SQLite builds opening the SAME file in one
process break POSIX advisory locking (sqlite.org/howtocorrupt.html section 2.2.1). Phase 2 must
therefore move every opener of the main DB to this module in one step. Other files (such as
the public CVE index) may keep using sqlite3.

Key
---
`key` is a crypto_store.DataKey (its HKDF purpose key for SQLCipher is used), 32 raw bytes
(used as-is), or a 64-char hex string (used as-is). It is applied as a raw key,
PRAGMA key="x'<64 hex>'", so SQLCipher's own PBKDF2 is skipped (the PIN KDF already ran).
"""
import os
import re
import sqlite3 as _sqlite3
from contextlib import contextmanager

_FORCE_PLAIN = os.environ.get("LOYA_DB_DRIVER", "").strip().lower() == "sqlite3"
_sqlcipher = None
_sqlcipher_import_error = None
if not _FORCE_PLAIN:
    try:
        import sqlcipher3 as _sqlcipher
    except Exception as e:  # pragma: no cover - depends on the environment
        _sqlcipher = None
        _sqlcipher_import_error = e
else:
    _sqlcipher_import_error = RuntimeError("disabled by LOYA_DB_DRIVER=sqlite3")

DRIVER = _sqlcipher if _sqlcipher is not None else _sqlite3
DRIVER_NAME = "sqlcipher3" if _sqlcipher is not None else "sqlite3"
SQLITE_MAGIC = b"SQLite format 3\x00"


def has_sqlcipher():
    return _sqlcipher is not None


def sqlcipher_version():
    """e.g. '4.20.0 community', or None when sqlcipher3 is not the driver."""
    if _sqlcipher is None:
        return None
    con = _sqlcipher.connect(":memory:")
    try:
        row = con.execute("PRAGMA cipher_version").fetchone()
        return row[0] if row else None
    finally:
        con.close()


Warning = DRIVER.Warning
Error = DRIVER.Error
InterfaceError = DRIVER.InterfaceError
DatabaseError = DRIVER.DatabaseError
DataError = DRIVER.DataError
OperationalError = DRIVER.OperationalError
IntegrityError = DRIVER.IntegrityError
InternalError = DRIVER.InternalError
ProgrammingError = DRIVER.ProgrammingError
NotSupportedError = DRIVER.NotSupportedError
Row = DRIVER.Row
Connection = DRIVER.Connection
Cursor = DRIVER.Cursor
Binary = DRIVER.Binary
PARSE_DECLTYPES = DRIVER.PARSE_DECLTYPES
PARSE_COLNAMES = DRIVER.PARSE_COLNAMES
# Flat tuple of both libraries' base Error, for transition code only (see the module docstring).
ANY_ERROR = (_sqlite3.Error,) if DRIVER is _sqlite3 else (_sqlite3.Error, DRIVER.Error)


class DriverError(DatabaseError):
    """Shim-level failure (verification mismatch, bad source...)."""


class EncryptionUnavailable(OperationalError):
    """A key was given but sqlcipher3 is not installed (or disabled)."""


class WrongKeyError(DatabaseError):
    """The key does not open this database, or a key is needed and none was given."""


class NotEncryptedError(DatabaseError):
    """A key was given for a plain (unencrypted) SQLite file."""


# ---------------------------------------------------------------- file inspection

def file_kind(path):
    """'missing' | 'empty' | 'plain' | 'encrypted'. 'encrypted' means "exists, not empty, and not
    a plain SQLite header": without the key we cannot tell an encrypted DB from random bytes."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return "missing"
    if size == 0:
        return "empty"
    try:
        with open(path, "rb") as f:
            head = f.read(16)
    except OSError:
        return "missing"
    return "plain" if head == SQLITE_MAGIC else "encrypted"


def is_encrypted_file(path):
    return file_kind(path) == "encrypted"


def _is_memory(path):
    p = str(path)
    return p == ":memory:" or p == "" or p.startswith("file:")


# ---------------------------------------------------------------- connect

import threading as _threading
import weakref as _weakref

_OPEN = _weakref.WeakSet()
_OPEN_LOCK = _threading.Lock()


def _track(con):
    with _OPEN_LOCK:
        _OPEN.add(con)
    return con


class _PlainConnection(DRIVER.Connection):
    """Every connection made here is tracked (weakly), so lock/migration can wait for them to close."""

    def close(self):
        try:
            super().close()
        finally:
            with _OPEN_LOCK:
                _OPEN.discard(self)


if _sqlcipher is not None:
    class _KeyedConnection(_sqlcipher.Connection):
        """Marks connections that were opened with a key (plain ones are sqlcipher3 too)."""

        def close(self):
            try:
                super().close()
            finally:
                with _OPEN_LOCK:
                    _OPEN.discard(self)
else:
    _KeyedConnection = None


def open_connections():
    """Connections opened through this module that are not closed yet (GC'd ones drop out)."""
    with _OPEN_LOCK:
        return list(_OPEN)


def open_count(collect=False):
    if collect:
        import gc
        gc.collect()
    return len(open_connections())

_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")


def _key_hex(key):
    if hasattr(key, "sqlcipher_hex"):
        return key.sqlcipher_hex()
    if isinstance(key, (bytes, bytearray, memoryview)):
        if len(key) != 32:
            raise ValueError("raw key must be 32 bytes")
        return bytes(key).hex()
    if isinstance(key, str) and _HEX64.match(key):
        return key.lower()
    raise ValueError("key must be a DataKey, 32 raw bytes or 64 hex characters")


def _apply_key(con, key):
    con.execute("PRAGMA key=\"x'%s'\"" % _key_hex(key))
    con.execute("PRAGMA cipher_log_level=NONE")


def _probe(con):
    con.execute("SELECT count(*) FROM sqlite_master").fetchone()


def connect(path, key=None, timeout=5.0, **kwargs):
    """Open `path` with DRIVER. key=None -> plain file (refuses an encrypted one with WrongKeyError);
    key given -> SQLCipher with the raw key (WrongKeyError on a wrong key, NotEncryptedError
    for a plain file, EncryptionUnavailable without sqlcipher3). Other kwargs go to connect()."""
    disk = not _is_memory(path)
    kind = file_kind(path) if disk else "missing"
    if key is None:
        if kind == "encrypted":
            raise WrongKeyError("database is encrypted; unlock LOYA NG first")
        kwargs.setdefault("factory", _PlainConnection)
        return _track(DRIVER.connect(path, timeout=timeout, **kwargs))
    if _sqlcipher is None:
        raise EncryptionUnavailable("sqlcipher3 is not installed: %s" % (_sqlcipher_import_error,))
    if kind == "plain":
        raise NotEncryptedError("database is not encrypted; migrate it first")
    kwargs.setdefault("factory", _KeyedConnection)
    con = _sqlcipher.connect(path, timeout=timeout, **kwargs)
    try:
        _apply_key(con, key)
        _probe(con)
        con.execute("PRAGMA temp_store=MEMORY")  # sorts/temp tables never touch disk
    except _sqlcipher.DatabaseError as e:
        con.close()
        if isinstance(e, (WrongKeyError, NotEncryptedError)):
            raise
        raise WrongKeyError("wrong key or not a database: %s" % e) from None
    except BaseException:
        con.close()
        raise
    return _track(con)


@contextmanager
def connection(path, key=None, timeout=5.0, row_factory=None, **kwargs):
    """`with db_driver.connection(p, key) as con:` commits on success, rolls back on error and
    ALWAYS closes. (`with sqlite3.connect(p) as con` does not close, which keeps the file open
    on Windows until GC and blocks os.replace/remove of the DB.)"""
    con = connect(path, key=key, timeout=timeout, **kwargs)
    if row_factory is not None:
        con.row_factory = row_factory
    try:
        yield con
        con.commit()
    except BaseException:
        try:
            con.rollback()
        except Exception:
            pass
        raise
    finally:
        con.close()


def is_encrypted_connection(con):
    """True for connections opened by connect(..., key=...)."""
    return _KeyedConnection is not None and isinstance(con, _KeyedConnection)


# ---------------------------------------------------------------- export / migrate

def _user_tables(con, schema="main"):
    rows = con.execute("SELECT name FROM %s.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%%' ORDER BY name" % schema).fetchall()
    return [r[0] for r in rows]


def _fts5_tables(con, schema="main"):
    rows = con.execute("SELECT name,sql FROM %s.sqlite_master WHERE type='table' AND sql LIKE 'CREATE VIRTUAL TABLE%%'" % schema).fetchall()
    return [r[0] for r in rows if re.search(r"\busing\s+fts5\b", r[1] or "", re.I)]


def _q(name):
    return '"%s"' % str(name).replace('"', '""')


def row_counts(con, schema="main"):
    return {t: con.execute("SELECT count(*) FROM %s.%s" % (schema, _q(t))).fetchone()[0] for t in _user_tables(con, schema)}


def _pragma(con, name, schema="main"):
    row = con.execute("PRAGMA %s.%s" % (schema, name)).fetchone()
    return row[0] if row else None


def _cleanup(path):
    for suffix in ("", "-wal", "-shm", "-journal"):
        try:
            os.remove(path + suffix)
        except OSError:
            pass


def _replace(src, dst):
    from Cores import crypto_store  # local import: crypto_store needs cryptography, connect() must not
    crypto_store._replace(src, dst)
    crypto_store._fsync_dir(os.path.dirname(os.path.abspath(dst)))


def _fsync_file(path):
    fd = os.open(path, os.O_RDWR | getattr(os, "O_BINARY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _verify(path, key, expect_counts, expect_user_version, expect_app_id):
    """Open the finished copy on its own connection and check it against the source."""
    con = connect(path, key=key) if key is not None else DRIVER.connect(path)
    try:
        if key is not None:
            bad = con.execute("PRAGMA cipher_integrity_check").fetchall()
            if bad:
                raise DriverError("cipher_integrity_check failed: %r" % (bad[:5],))
        ok = con.execute("PRAGMA integrity_check").fetchall()
        if ok != [("ok",)] and [tuple(r) for r in ok] != [("ok",)]:
            raise DriverError("integrity_check failed: %r" % (ok[:5],))
        for t in _fts5_tables(con):
            con.execute("INSERT INTO %s(%s) VALUES('integrity-check')" % (_q(t), _q(t)))
        got = row_counts(con)
        if got != expect_counts:
            diff = {t: (expect_counts.get(t), got.get(t)) for t in set(got) | set(expect_counts) if got.get(t) != expect_counts.get(t)}
            raise DriverError("row counts differ after export: %r" % (diff,))
        if _pragma(con, "user_version") != expect_user_version or _pragma(con, "application_id") != expect_app_id:
            raise DriverError("user_version/application_id differ after export")
        con.commit()
        return got
    finally:
        con.close()


def _export(src, src_key, dst, dst_key, overwrite=False):
    """Copy src -> dst with sqlcipher_export, under a write lock on src, into a temp file that
    replaces dst only after verification. Returns a report dict. src is never modified."""
    if _sqlcipher is None:
        raise EncryptionUnavailable("sqlcipher3 is not installed: %s" % (_sqlcipher_import_error,))
    src = os.path.abspath(src)
    dst = os.path.abspath(dst)
    if src == dst:
        raise ValueError("src and dst must differ")
    if not overwrite and os.path.exists(dst):
        raise FileExistsError(dst)
    src_kind = file_kind(src)
    if src_kind in ("missing", "empty"):
        raise DriverError("source database is missing or empty")
    if (src_kind == "encrypted") != (src_key is not None):
        raise (WrongKeyError if src_kind == "encrypted" else NotEncryptedError)("source is %s" % src_kind)
    tmp = "%s.%d.export.tmp" % (dst, os.getpid())
    _cleanup(tmp)
    con = _sqlcipher.connect(src, timeout=30, isolation_level=None)
    try:
        if src_key is not None:
            _apply_key(con, src_key)
        try:
            _probe(con)
        except _sqlcipher.DatabaseError as e:
            raise WrongKeyError("cannot open the source: %s" % e) from None
        journal = str(_pragma(con, "journal_mode") or "delete").lower()
        if journal == "wal":
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
        dkey = "x'%s'" % _key_hex(dst_key) if dst_key is not None else ""
        con.execute("ATTACH DATABASE ? AS loya_export KEY \"%s\"" % dkey, (tmp,))
        try:
            con.execute("BEGIN IMMEDIATE")  # no writer may slip in between the counts and the copy
            try:
                counts = row_counts(con)
                user_version = _pragma(con, "user_version")
                app_id = _pragma(con, "application_id")
                con.execute("SELECT sqlcipher_export('loya_export')").fetchall()
                # sqlcipher_export copies schema and rows but not these header fields.
                con.execute("PRAGMA loya_export.user_version=%d" % int(user_version or 0))
                con.execute("PRAGMA loya_export.application_id=%d" % int(app_id or 0))
                con.execute("COMMIT")
            except BaseException:
                try:
                    con.execute("ROLLBACK")
                except Exception:
                    pass
                raise
        finally:
            con.execute("DETACH DATABASE loya_export")
    except BaseException:
        con.close()
        _cleanup(tmp)
        raise
    con.close()
    def _open_tmp():
        return connect(tmp, key=dst_key) if dst_key is not None else DRIVER.connect(tmp)
    try:
        if journal == "wal":
            c2 = _open_tmp()
            try:
                c2.execute("PRAGMA journal_mode=WAL").fetchall()
            finally:
                c2.close()
        _verify(tmp, dst_key, counts, user_version, app_id)
        if journal == "wal":
            # Fold anything _verify wrote (FTS integrity-check) back into the main file, so the
            # single file we move is complete on its own.
            c3 = _open_tmp()
            try:
                c3.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
            finally:
                c3.close()
        _fsync_file(tmp)
        for suffix in ("-wal", "-shm"):
            # A fully checkpointed, closed DB has no WAL content left; stale sidecars next to dst
            # would otherwise be replayed against the new file.
            try:
                os.remove(dst + suffix)
            except OSError:
                pass
        _replace(tmp, dst)
    except BaseException:
        _cleanup(tmp)
        raise
    _cleanup(tmp)
    return {"src": src, "dst": dst, "tables": counts, "user_version": user_version, "application_id": app_id, "journal_mode": journal}


def migrate_plain_to_encrypted(src, dst, key, overwrite=False):
    """Plain SQLite `src` -> new SQLCipher file `dst` under `key`. Verified with
    cipher_integrity_check, integrity_check, FTS5 integrity-check, per-table row counts,
    user_version and application_id before dst appears. `src` is left untouched: deleting it
    (after a backup exists) is the caller's decision. Requires that no other connection is
    writing to src (run it at startup/unlock, before services open the DB)."""
    if key is None:
        raise ValueError("key is required")
    return _export(src, None, dst, key, overwrite=overwrite)


def export_plain(src_enc, dst, key, overwrite=False):
    """User-requested decrypted export: SQLCipher `src_enc` -> plain SQLite `dst` (verified)."""
    if key is None:
        raise ValueError("key is required")
    return _export(src_enc, key, dst, None, overwrite=overwrite)


def backup_encrypted(src_enc, dst, key, dst_key=None, overwrite=False):
    """Consistent encrypted copy of an encrypted DB (for backups); dst_key defaults to key."""
    if key is None:
        raise ValueError("key is required")
    return _export(src_enc, key, dst, dst_key if dst_key is not None else key, overwrite=overwrite)
