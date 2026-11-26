"""A data restore never silently brings back an old PIN, and never rolls back the security audit log (E2E issues 3 and 5)."""
import json
import os
import shutil
import tempfile
import unittest

from _isolate import IsolatedData
from Cores import common_db, crypto_store, db_driver
from Cores.Update import backup_restore
from Cores.Services import security_service as sec

EPIN = "482193"
NEW_PIN = "731905"
FAST_KDF = {"name": "argon2id", "m_kib": 8192, "t": 1, "p": 1} if crypto_store.has_argon2() else {"name": "scrypt", "n": 2 ** 14, "r": 8, "p": 1}
BKPW = "test-backup-pw"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Case(unittest.TestCase):
    def setUp(self):
        self._kdf = sec._KDF
        sec._KDF = FAST_KDF
        self.bk = tempfile.mkdtemp(prefix="loya_bk_")
        self.iso = None
        self.start()

    def start(self):
        if self.iso is not None:
            sec.clear_session_pin()
            self.iso.stop()
        self.iso = IsolatedData()
        self.dir = self.iso.start()
        sec.clear_session_pin()
        common_db.set_locked(False)
        with common_db.connection() as con:
            common_db.ensure_schema(con)
            con.execute("INSERT INTO Notes(note_name,content) VALUES('n1','body')")

    def tearDown(self):
        sec.clear_session_pin()
        common_db.set_locked(False)
        sec._KDF = self._kdf
        self.iso.stop()
        shutil.rmtree(self.bk, ignore_errors=True)

    def p(self, *a):
        return os.path.join(self.dir, *a)

    def notes(self):
        with common_db.connection() as con:
            return con.execute("SELECT COUNT(*) FROM Notes").fetchone()[0]

    def events(self):
        return [(e["event"], e.get("detail", "")) for e in sec.list_audit_events(1000)]

    def read(self, rel):
        with open(self.p(rel), "rb") as f:
            return f.read()


class PlainAuditTests(Case):
    def test_audit_file_survives_restore_and_logs_the_restore(self):
        sec.log_audit_event("unlock", "before-backup", True)
        out = backup_restore.create_data_backup(out_dir=self.bk, password=BKPW)
        sec.log_audit_event("pin_change", "after-backup", True)
        ok, msg = backup_restore.restore_data_backup(out, mode="replace", password=BKPW)
        self.assertTrue(ok, msg)
        ev = self.events()
        self.assertIn(("unlock", "before-backup"), ev)
        self.assertIn(("pin_change", "after-backup"), ev, "events written after the backup survive the restore")
        self.assertTrue([d for e, d in ev if e == "backup_restored" and os.path.basename(out) in d])
        self.assertEqual(1, [e for e, _d in ev].count("unlock"), "no duplicate entries after the merge")

    def test_merge_keeps_live_and_adds_backup_only_entries(self):
        live, bak = self.p("live.jsonl"), self.p("bak.jsonl")
        a = {"ts": "2026-01-01T00:00:00+00:00", "event": "lock", "detail": "a", "success": True}
        b = {"ts": "2026-01-02T00:00:00+00:00", "event": "lock", "detail": "b", "success": True}
        c = {"ts": "2026-01-03T00:00:00+00:00", "event": "lock", "detail": "c", "success": True}
        with open(live, "w", encoding="utf-8") as f:
            f.write(json.dumps(a) + "\n" + json.dumps(c) + "\n")
        with open(bak, "w", encoding="utf-8") as f:
            f.write(json.dumps(a) + "\n" + json.dumps(b) + "\n")
        sec.merge_audit_file(live, bak)
        with open(live, encoding="utf-8") as f:
            got = [json.loads(x)["detail"] for x in f if x.strip()]
        self.assertEqual(["a", "b", "c"], got)

    def test_merge_mode_keeps_live_log(self):
        out = backup_restore.create_data_backup(out_dir=self.bk, password=BKPW)
        sec.log_audit_event("lock", "after-backup", True)
        ok, msg = backup_restore.restore_data_backup(out, mode="merge", password=BKPW)
        self.assertTrue(ok, msg)
        self.assertIn(("lock", "after-backup"), self.events())


@unittest.skipUnless(db_driver.has_sqlcipher(), "sqlcipher3 not installed")
class EncryptedRestoreTests(Case):
    def enable(self, pin=EPIN):
        ok, msg = sec.set_encryption(True, new_pin=pin)
        self.assertTrue(ok, msg)

    def relock_unlock(self, pin):
        sec.lock_now("t")
        return sec.unlock(pin)

    def test_same_pin_restore(self):
        self.enable()
        out = backup_restore.create_data_backup(out_dir=self.bk)
        with common_db.connection() as con:
            con.execute("DELETE FROM Notes")
        self.assertFalse(backup_restore.backup_needs_pin(out)["needs_pin"])
        self.assertEqual("pin", backup_restore.backup_needs_pin(out)["protect"], "a PIN backup still asks for the PIN")
        ok, msg = backup_restore.restore_data_backup(out, mode="replace")
        self.assertFalse(ok, "no PIN typed: nothing is restored")
        ok, msg = backup_restore.restore_data_backup(out, mode="replace", pin="000000")
        self.assertEqual((False, "Restore failed: Wrong PIN."), (ok, msg))
        self.assertEqual(0, self.notes())
        ok, msg = backup_restore.restore_data_backup(out, mode="replace", pin=EPIN)
        self.assertTrue(ok, msg)
        self.assertEqual(1, self.notes())
        ok, msg = self.relock_unlock(EPIN)
        self.assertTrue(ok, msg)

    def test_pin_changed_after_backup_keeps_current_pin(self):
        self.enable()
        out = backup_restore.create_data_backup(out_dir=self.bk)
        ok, msg = sec.set_pin(NEW_PIN, EPIN)
        self.assertTrue(ok, msg)
        self.assertFalse(backup_restore.backup_needs_pin(out)["needs_pin"], "same data key: no foreign-PIN prompt")
        ok, msg = backup_restore.restore_data_backup(out, mode="replace", pin=NEW_PIN)
        self.assertTrue(ok, msg)
        self.assertTrue(sec.verify_pin(NEW_PIN))
        self.assertFalse(sec.verify_pin(EPIN), "the backup's old PIN must not come back")
        ok, msg = self.relock_unlock(NEW_PIN)
        self.assertTrue(ok, msg)
        self.assertEqual(1, self.notes())

    def _foreign_backup(self):
        """A backup made by another installation (another data key) under EPIN; this installation then runs under NEW_PIN."""
        self.enable(EPIN)
        with common_db.connection() as con:
            con.execute("INSERT INTO Notes(note_name,content) VALUES('n2','from-backup')")
        out = backup_restore.create_data_backup(out_dir=self.bk)
        self.start()
        self.enable(NEW_PIN)
        self.assertTrue(backup_restore.backup_needs_pin(out)["needs_pin"])
        return out

    def test_other_key_restore_rewraps_under_current_pin(self):
        out = self._foreign_backup()
        ok, msg = backup_restore.restore_data_backup(out, mode="replace", pin=EPIN, current_pin=NEW_PIN)
        self.assertTrue(ok, msg)
        self.assertEqual(2, self.notes())
        self.assertTrue(sec.verify_pin(NEW_PIN))
        self.assertFalse(sec.verify_pin(EPIN))
        ok, msg = self.relock_unlock(NEW_PIN)
        self.assertTrue(ok, msg)
        self.assertEqual(2, self.notes())
        self.assertFalse(self.relock_unlock(EPIN)[0], "the backup's PIN does not unlock")

    def test_wrong_pins_are_refused_with_data_untouched(self):
        out = self._foreign_backup()
        db0, key0 = self.read("Note_LOYA_V1.db"), self.read("Note_LOYA_V1.key")
        for pin, cur in (("000000", NEW_PIN), (EPIN, "999999")):
            ok, msg = backup_restore.restore_data_backup(out, mode="replace", pin=pin, current_pin=cur)
            self.assertFalse(ok, (pin, cur))
            self.assertIn("PIN", msg)
            self.assertEqual(db0, self.read("Note_LOYA_V1.db"))
            self.assertEqual(key0, self.read("Note_LOYA_V1.key"))
            self.assertFalse(common_db.is_locked())
        self.assertEqual(1, self.notes())
        self.assertTrue(sec.verify_pin(NEW_PIN))
        self.assertEqual(2, len([e for e, _d in self.events() if e == "backup_restored"]), "failed attempts are audited")

    def test_skipping_current_pin_brings_backup_pin_and_ui_warns(self):
        out = self._foreign_backup()
        ok, msg = backup_restore.restore_data_backup(out, mode="replace", pin=EPIN)
        self.assertTrue(ok, msg)
        self.assertTrue(sec.verify_pin(EPIN), "fallback: the backup's PIN comes back")
        self.assertIn("backup's PIN restored", " ".join(d for e, d in self.events() if e == "backup_restored"))
        with open(os.path.join(ROOT, "UI", "js", "pages", "settings.js"), encoding="utf-8") as f:
            js = f.read()
        self.assertIn("This backup uses the PIN that was set when it was made. After restore, unlock with that PIN.", js)

    def test_encrypted_audit_events_survive_restore(self):
        self.enable()
        sec.log_audit_event("terminal_command", "before-backup", True)
        out = backup_restore.create_data_backup(out_dir=self.bk)
        sec.log_audit_event("terminal_command", "after-backup", True)
        sec.log_audit_event("unlock", "plain-after-backup", True)
        with common_db.connection() as con:
            self.assertEqual(2, con.execute("SELECT COUNT(*) FROM AuditEvents WHERE event='terminal_command'").fetchone()[0])
        ok, msg = backup_restore.restore_data_backup(out, mode="replace", pin=EPIN)
        self.assertTrue(ok, msg)
        with common_db.connection() as con:
            rows = [r[0] for r in con.execute("SELECT detail FROM AuditEvents WHERE event='terminal_command' ORDER BY ts").fetchall()]
        self.assertEqual(["before-backup", "after-backup"], rows, "kept, not duplicated")
        ev = self.events()
        self.assertIn(("unlock", "plain-after-backup"), ev)
        self.assertTrue([d for e, d in ev if e == "backup_restored" and "current PIN kept" in d])

    def test_encrypted_audit_events_survive_other_key_restore(self):
        out = self._foreign_backup()
        sec.log_audit_event("terminal_command", "live-only", True)
        ok, msg = backup_restore.restore_data_backup(out, mode="replace", pin=EPIN, current_pin=NEW_PIN)
        self.assertTrue(ok, msg)
        self.assertIn(("terminal_command", "live-only"), self.events())


if __name__ == "__main__":
    unittest.main()
