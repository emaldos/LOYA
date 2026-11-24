import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _isolate import ROOT  # noqa: F401  (puts the repo on sys.path)

from Cores import db_driver as dd

try:
    import sqlcipher3
except Exception:
    sqlcipher3 = None
try:
    from Cores import crypto_store as cs
except Exception:
    cs = None

_NEED = "sqlcipher3 and cryptography are required"


class _Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="loya_dbdrv_")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def p(self, name):
        return os.path.join(self.dir, name)

    def make_plain(self, name="plain.db", wal=True):
        con = sqlite3.connect(self.p(name))
        try:
            if wal:
                self.assertEqual(con.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
            con.execute("PRAGMA user_version=15")
            con.execute("PRAGMA application_id=1280266561")
            con.execute("CREATE TABLE Notes(id INTEGER PRIMARY KEY, note_name TEXT UNIQUE, content TEXT)")
            con.executemany("INSERT INTO Notes(note_name,content) VALUES(?,?)",
                            [("n%d" % i, "password Winter%d! nmap -sV 10.0.0.%d" % (i, i % 250)) for i in range(800)])
            con.execute("CREATE VIRTUAL TABLE NotesFts USING fts5(note_name, content)")
            con.execute("INSERT INTO NotesFts SELECT note_name, content FROM Notes")
            con.execute("CREATE INDEX idx_notes_content ON Notes(content)")
            con.execute("CREATE TABLE Blobs(id INTEGER PRIMARY KEY, data BLOB)")
            con.execute("INSERT INTO Blobs(data) VALUES(?)", (os.urandom(300000),))
            con.commit()
            # Rows that only live in the WAL, as after a crash: copy db + -wal while the writer is
            # still open (closing would checkpoint and delete the WAL).
            con.execute("PRAGMA wal_autocheckpoint=0")
            con.execute("INSERT INTO Notes(note_name,content) VALUES('wal-only','only in the wal')")
            con.commit()
            if wal:
                shutil.copyfile(self.p(name), self.p("crash.db"))
                shutil.copyfile(self.p(name) + "-wal", self.p("crash.db-wal"))
        finally:
            con.close()
        if wal:
            os.replace(self.p("crash.db"), self.p(name))
            os.replace(self.p("crash.db-wal"), self.p(name) + "-wal")
        return self.p(name)


class ExceptionMappingTests(_Base):
    def test_driver_choice(self):
        if sqlcipher3 is not None and os.environ.get("LOYA_DB_DRIVER", "").lower() != "sqlite3":
            self.assertIs(dd.DRIVER, sqlcipher3)
            self.assertFalse(issubclass(sqlcipher3.IntegrityError, sqlite3.Error), "the reason the shim exists")
        else:
            self.assertIs(dd.DRIVER, sqlite3)
            self.assertFalse(dd.has_sqlcipher())
        for name in ("Error", "DatabaseError", "IntegrityError", "OperationalError", "ProgrammingError",
                     "InterfaceError", "DataError", "InternalError", "NotSupportedError", "Warning", "Row"):
            self.assertIs(getattr(dd, name), getattr(dd.DRIVER, name))
            self.assertTrue(isinstance(getattr(dd, name), type), "real classes, not tuples")

    def test_errors_from_plain_connections_are_caught(self):
        con = dd.connect(":memory:")
        con.execute("CREATE TABLE t(x UNIQUE)")
        con.execute("INSERT INTO t VALUES(1)")
        with self.assertRaises(dd.IntegrityError):
            con.execute("INSERT INTO t VALUES(1)")
        with self.assertRaises(dd.OperationalError):
            con.execute("SELECT * FROM missing")
        try:
            con.execute("INSERT INTO t VALUES(1)")
        except (dd.IntegrityError, ValueError) as e:  # mixed except tuples must work
            self.assertIsInstance(e, dd.Error)
            self.assertIsInstance(e, dd.DatabaseError)
        con.close()
        with self.assertRaises(dd.ProgrammingError):
            con.execute("SELECT 1")

    @unittest.skipUnless(dd.has_sqlcipher() and cs is not None, _NEED)
    def test_errors_from_encrypted_connections_are_caught(self):
        with cs.DataKey.generate() as k:
            con = dd.connect(self.p("e.db"), key=k)
            con.execute("CREATE TABLE t(x UNIQUE)")
            con.execute("INSERT INTO t VALUES(1)")
            try:
                con.execute("INSERT INTO t VALUES(1)")
                self.fail("no error")
            except (dd.IntegrityError, KeyError) as e:
                self.assertIsInstance(e, dd.Error)
            with self.assertRaises(dd.OperationalError):
                con.execute("SELECT * FROM missing")
            con.close()

    def test_any_error_catches_stdlib_sqlite3(self):
        con = sqlite3.connect(":memory:")
        try:
            con.execute("SELECT * FROM missing")
        except dd.ANY_ERROR:
            pass
        try:
            con.execute("SELECT * FROM missing")
        except (*dd.ANY_ERROR, ValueError):
            pass
        con.close()

    def test_shim_errors_are_driver_errors(self):
        for cls in (dd.DriverError, dd.EncryptionUnavailable, dd.WrongKeyError, dd.NotEncryptedError):
            self.assertTrue(issubclass(cls, dd.Error), cls)
        self.assertTrue(issubclass(dd.EncryptionUnavailable, dd.OperationalError))
        with self.assertRaises(dd.Error):
            raise dd.DriverError("raisable")

    def test_row_factory(self):
        con = dd.connect(":memory:")
        self.assertFalse(dd.is_encrypted_connection(con))
        con.row_factory = dd.Row
        r = con.execute("SELECT 1 AS a, 'x' AS b").fetchone()
        self.assertIsInstance(r, dd.Row)
        self.assertEqual((r["a"], r["b"], dict(r), r.keys()), (1, "x", {"a": 1, "b": "x"}, ["a", "b"]))
        con.close()

    def test_connection_context_closes_and_rolls_back(self):
        path = self.p("c.db")
        with dd.connection(path) as con:
            con.execute("CREATE TABLE t(x)")
            con.execute("INSERT INTO t VALUES(1)")
        with self.assertRaises(dd.ProgrammingError):
            con.execute("SELECT 1")  # closed
        with self.assertRaises(ZeroDivisionError):
            with dd.connection(path) as con:
                con.execute("INSERT INTO t VALUES(2)")
                1 / 0
        with dd.connection(path, row_factory=dd.Row) as con:
            self.assertEqual([r["x"] for r in con.execute("SELECT x FROM t")], [1])


class FileKindTests(_Base):
    def test_kinds(self):
        self.assertEqual(dd.file_kind(self.p("none")), "missing")
        open(self.p("empty"), "wb").close()
        self.assertEqual(dd.file_kind(self.p("empty")), "empty")
        self.assertEqual(dd.file_kind(self.make_plain(wal=False)), "plain")
        with open(self.p("rnd"), "wb") as f:
            f.write(os.urandom(4096))
        self.assertEqual(dd.file_kind(self.p("rnd")), "encrypted")
        self.assertTrue(dd.is_encrypted_file(self.p("rnd")))
        self.assertFalse(dd.is_encrypted_file(self.p("plain.db")))
        self.assertFalse(dd.is_encrypted_file(self.p("empty")))


@unittest.skipUnless(dd.has_sqlcipher() and cs is not None, _NEED)
class EncryptedTests(_Base):
    def setUp(self):
        super().setUp()
        self.key = cs.DataKey.generate()

    def tearDown(self):
        self.key.wipe()
        super().tearDown()

    def test_version(self):
        self.assertTrue(dd.sqlcipher_version().startswith("4."), dd.sqlcipher_version())

    def test_create_reopen_and_unreadable_by_sqlite3(self):
        path = self.p("enc.db")
        with dd.connection(path, key=self.key) as con:
            self.assertTrue(dd.is_encrypted_connection(con))
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("CREATE TABLE secrets(v TEXT)")
            con.execute("INSERT INTO secrets VALUES('Winter2026!')")
        self.assertEqual(dd.file_kind(path), "encrypted")
        with open(path, "rb") as f:
            raw = f.read()
        self.assertNotIn(b"Winter2026", raw)
        self.assertNotIn(b"SQLite format 3", raw)
        con = sqlite3.connect(path)
        with self.assertRaises(sqlite3.DatabaseError):
            con.execute("SELECT * FROM sqlite_master").fetchall()
        con.close()
        with self.assertRaises(dd.WrongKeyError):
            dd.connect(path)  # no key: refused before sqlite3 can touch it
        with dd.connection(path, key=self.key, row_factory=dd.Row) as con:
            self.assertEqual(con.execute("SELECT v FROM secrets").fetchone()["v"], "Winter2026!")

    def test_wrong_key(self):
        path = self.p("enc.db")
        with dd.connection(path, key=self.key) as con:
            con.execute("CREATE TABLE t(x)")
        with cs.DataKey.generate() as other:
            with self.assertRaises(dd.WrongKeyError):
                dd.connect(path, key=other)
            try:
                dd.connect(path, key=other)
            except dd.Error:
                pass  # catchable through the shim tuple
        with self.assertRaises(dd.WrongKeyError):
            dd.connect(path, key=os.urandom(32))

    def test_key_forms(self):
        raw = os.urandom(32)
        path = self.p("raw.db")
        with dd.connection(path, key=raw) as con:
            con.execute("CREATE TABLE t(x)")
        with dd.connection(path, key=raw.hex()) as con:
            con.execute("SELECT * FROM t")
        for bad in (b"short", "zz" * 32, 12345):
            with self.assertRaises(ValueError):
                dd.connect(self.p("bad.db"), key=bad)

    def test_key_on_plain_file_refused(self):
        path = self.make_plain(wal=False)
        with self.assertRaises(dd.NotEncryptedError):
            dd.connect(path, key=self.key)

    def test_migrate_with_fts5_and_wal(self):
        src = self.make_plain()
        self.assertTrue(os.path.exists(src + "-wal"))
        dst = self.p("enc.db")
        rep = dd.migrate_plain_to_encrypted(src, dst, self.key)
        self.assertEqual(rep["tables"]["Notes"], 801, "WAL-only rows must be migrated")
        self.assertEqual(rep["journal_mode"], "wal")
        self.assertIn("NotesFts", rep["tables"])
        self.assertEqual(dd.file_kind(dst), "encrypted")
        self.assertTrue(os.path.exists(src), "the original is kept")
        con = dd.connect(dst, key=self.key)
        try:
            self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], 15)
            self.assertEqual(con.execute("PRAGMA application_id").fetchone()[0], 1280266561)
            self.assertEqual(con.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            self.assertEqual(con.execute("SELECT count(*) FROM NotesFts WHERE NotesFts MATCH 'nmap'").fetchone()[0], 800)
            self.assertEqual(con.execute("SELECT content FROM Notes WHERE note_name='wal-only'").fetchone()[0], "only in the wal")
            self.assertEqual(len(con.execute("SELECT data FROM Blobs").fetchone()[0]), 300000)
            self.assertEqual(con.execute("PRAGMA cipher_integrity_check").fetchall(), [])
            con.execute("INSERT INTO NotesFts(NotesFts) VALUES('integrity-check')")
        finally:
            con.close()
        with open(dst, "rb") as f:
            self.assertNotIn(b"Winter1", f.read())
        leftovers = [n for n in os.listdir(self.dir) if "tmp" in n]
        self.assertEqual(leftovers, [])
        c = sqlite3.connect(src)
        self.assertEqual(c.execute("SELECT count(*) FROM Notes").fetchone()[0], 801, "source still intact")
        c.close()

    def test_migrate_refuses_existing_dst_and_bad_sources(self):
        src = self.make_plain(wal=False)
        dst = self.p("enc.db")
        with open(dst, "wb") as f:
            f.write(b"keep me")
        with self.assertRaises(FileExistsError):
            dd.migrate_plain_to_encrypted(src, dst, self.key)
        with open(dst, "rb") as f:
            self.assertEqual(f.read(), b"keep me")
        with self.assertRaises(dd.Error):
            dd.migrate_plain_to_encrypted(self.p("missing.db"), self.p("x.db"), self.key)
        dd.migrate_plain_to_encrypted(src, self.p("e2.db"), self.key)
        with self.assertRaises(dd.WrongKeyError):
            dd.migrate_plain_to_encrypted(self.p("e2.db"), self.p("e3.db"), self.key)  # already encrypted
        with self.assertRaises(ValueError):
            dd.migrate_plain_to_encrypted(src, self.p("e4.db"), None)

    def test_failed_verify_leaves_nothing(self):
        src = self.make_plain(wal=False)
        dst = self.p("enc.db")
        orig = dd._verify

        def broken(*a, **k):
            raise dd.DriverError("simulated mismatch")
        dd._verify = broken
        try:
            with self.assertRaises(dd.DriverError):
                dd.migrate_plain_to_encrypted(src, dst, self.key)
        finally:
            dd._verify = orig
        self.assertFalse(os.path.exists(dst))
        self.assertEqual(sorted(os.listdir(self.dir)), ["plain.db"])

    def test_export_plain_round_trip(self):
        src = self.make_plain()
        enc = self.p("enc.db")
        dd.migrate_plain_to_encrypted(src, enc, self.key)
        out = self.p("export.db")
        rep = dd.export_plain(enc, out, self.key)
        self.assertEqual(dd.file_kind(out), "plain")
        c = sqlite3.connect(out)
        try:
            self.assertEqual(c.execute("SELECT count(*) FROM Notes").fetchone()[0], 801)
            self.assertEqual(c.execute("SELECT count(*) FROM NotesFts WHERE NotesFts MATCH 'winter5'").fetchone()[0], 1)
            self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0], 15)
        finally:
            c.close()
        self.assertEqual(rep["tables"]["Notes"], 801)
        with cs.DataKey.generate() as other, self.assertRaises(dd.WrongKeyError):
            dd.export_plain(enc, self.p("export2.db"), other)

    def test_backup_encrypted_and_rekey_copy(self):
        src = self.make_plain(wal=False)
        enc = self.p("enc.db")
        dd.migrate_plain_to_encrypted(src, enc, self.key)
        dd.backup_encrypted(enc, self.p("bak.db"), self.key)
        with dd.connection(self.p("bak.db"), key=self.key) as con:
            self.assertEqual(con.execute("SELECT count(*) FROM Notes").fetchone()[0], 801)
        with cs.DataKey.generate() as other:
            dd.backup_encrypted(enc, self.p("bak2.db"), self.key, dst_key=other)
            with dd.connection(self.p("bak2.db"), key=other) as con:
                self.assertEqual(con.execute("SELECT count(*) FROM Notes").fetchone()[0], 801)
            with self.assertRaises(dd.WrongKeyError):
                dd.connect(self.p("bak2.db"), key=self.key)


@unittest.skipIf(dd.has_sqlcipher(), "only meaningful without sqlcipher3")
class NoSqlcipherTests(_Base):
    def test_key_needs_sqlcipher(self):
        with self.assertRaises(dd.EncryptionUnavailable):
            dd.connect(self.p("x.db"), key=os.urandom(32))


class MissingSqlcipherSimulationTests(_Base):
    def test_simulated_missing_driver(self):
        saved = dd._sqlcipher
        dd._sqlcipher = None
        try:
            with self.assertRaises(dd.EncryptionUnavailable):
                dd.connect(self.p("x.db"), key=os.urandom(32))
            with self.assertRaises(dd.Error):
                dd.connect(self.p("x.db"), key=os.urandom(32))
            self.assertFalse(dd.has_sqlcipher())
        finally:
            dd._sqlcipher = saved


if __name__ == "__main__":
    unittest.main()
