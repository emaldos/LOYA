"""Full backups are always encrypted: a .loyabak under the backup password (encryption at rest off) or the PIN-wrapped data key
(on). The password is checked before anything is restored, can be remembered only in the OS keyring, automatic and update
backups are skipped (with a notice) rather than written unencrypted, and old plain .zip backups still restore with a warning."""
import json
import os
import shutil
import tempfile
import unittest
import zipfile
from unittest import mock

from _isolate import IsolatedData
from Cores import backup_password as bp
from Cores import common_db, crypto_store, loyabak
from Cores.Update import backup_restore as br
from Cores.Services import security_service as sec
from Cores.Services import settings_service as ss

PW = "test-backup-pw-1"
FAST_KDF = {"name": "argon2id", "m_kib": 8192, "t": 1, "p": 1} if crypto_store.has_argon2() else {"name": "scrypt", "n": 2 ** 14, "r": 8, "p": 1}
MARKERS = (b"MARKER-NOTE-7f3a", b"MARKER-FILE-91bc", b"MARKER-SETTING-2d4e")


class FakeKeyring:
    def __init__(self):
        self.store = {}

    def get_password(self, service, user):
        return self.store.get((service, user))

    def set_password(self, service, user, value):
        self.store[(service, user)] = value

    def delete_password(self, service, user):
        self.store.pop((service, user), None)


class Case(unittest.TestCase):
    def setUp(self):
        self.iso = IsolatedData()
        self.dir = self.iso.start()
        sec.clear_session_pin()
        common_db.set_locked(False)
        self.kr = FakeKeyring()
        self._kr = mock.patch.object(bp, "_keyring", lambda: self.kr)
        self._kr.start()
        # Fast Argon2id for the backup password wrap (the default costs 64 MiB per test).
        real_wrap = crypto_store.wrap_dek
        self._wrap = mock.patch.object(crypto_store, "wrap_dek", lambda dek, pin, kdf=None: real_wrap(dek, pin, kdf or FAST_KDF))
        self._wrap.start()
        self.out = tempfile.mkdtemp(prefix="loya_bk_enc_")
        with common_db.connection() as con:
            common_db.ensure_schema(con)
            con.execute("INSERT INTO Notes(note_name,content) VALUES('n1',?)", (MARKERS[0].decode(),))
        os.makedirs(os.path.join(self.dir, "Attachments", "1"), exist_ok=True)
        with open(os.path.join(self.dir, "Attachments", "1", "a.txt"), "wb") as f:
            f.write(MARKERS[1] * 50)
        with open(os.path.join(self.dir, "settings.json"), "w", encoding="utf-8") as f:
            json.dump({"appearance": {"theme": MARKERS[2].decode()}}, f)

    def tearDown(self):
        self._wrap.stop()
        self._kr.stop()
        sec.clear_session_pin()
        common_db.set_locked(False)
        self.iso.stop()
        shutil.rmtree(self.out, ignore_errors=True)

    def notes(self):
        with common_db.connection() as con:
            return [r[0] for r in con.execute("SELECT content FROM Notes ORDER BY id")]

    def raw(self, path):
        with open(path, "rb") as f:
            return f.read()


class AlwaysEncryptedTests(Case):
    def test_backup_is_a_loyabak_without_plaintext(self):
        out = br.create_data_backup(out_dir=self.out, password=PW)
        self.assertTrue(out.endswith(loyabak.EXT))
        raw = self.raw(out)
        self.assertTrue(raw.startswith(loyabak.MAGIC))
        for m in MARKERS:
            self.assertNotIn(m, raw)
        self.assertNotIn(PW.encode(), raw)
        self.assertEqual("password", br.backup_needs_pin(out)["protect"])
        self.assertTrue(br.backup_needs_pin(out)["needs_password"])
        # Every file the Backups folder holds is encrypted.
        for n in os.listdir(self.out):
            self.assertTrue(self.raw(os.path.join(self.out, n)).startswith(loyabak.MAGIC), n)

    def test_no_password_writes_nothing(self):
        with self.assertRaises(bp.PasswordRequired):
            br.create_data_backup(out_dir=self.out)
        self.assertEqual([], os.listdir(self.out))
        with self.assertRaises(ValueError):
            br.create_data_backup(out_dir=self.out, password="short")
        self.assertEqual([], os.listdir(self.out))

    def test_wrong_password_refused_then_round_trip(self):
        out = br.create_data_backup(out_dir=self.out, password=PW)
        with common_db.connection() as con:
            con.execute("UPDATE Notes SET content='changed'")
        before = self.raw(os.path.join(self.dir, "settings.json"))
        for pw in (None, "wrong-password"):
            ok, msg = br.restore_data_backup(out, mode="replace", password=pw)
            self.assertFalse(ok)
            self.assertIn("password", msg.lower())
        self.assertEqual("Restore failed: Wrong password.", br.restore_data_backup(out, mode="replace", password="wrong-password")[1])
        self.assertEqual(["changed"], self.notes(), "nothing restored")
        self.assertEqual(before, self.raw(os.path.join(self.dir, "settings.json")))
        ok, msg = br.restore_data_backup(out, mode="replace", password=PW)
        self.assertTrue(ok, msg)
        self.assertNotIn("not encrypted", msg)
        self.assertEqual([MARKERS[0].decode()], self.notes())

    def test_a_work_export_container_is_not_restored_as_a_backup(self):
        zp = os.path.join(self.out, "w.zip")
        with zipfile.ZipFile(zp, "w") as z:
            z.writestr("manifest.json", "{}")
        dek = crypto_store.DataKey.generate()
        out = os.path.join(self.out, "w.loyawork")
        loyabak.write(zp, out, dek, crypto_store.wrap_dek(dek, PW), {"kind": "work", "protect": "password"})
        ok, msg = br.restore_data_backup(out, mode="merge", password=PW)
        self.assertFalse(ok)
        self.assertIn("work export", msg)


class RememberedPasswordTests(Case):
    def test_remembered_password_lives_only_in_the_keyring(self):
        out = ss.Backup().create(password=PW, remember=True)
        self.assertTrue(loyabak.is_loyabak(out))
        self.assertEqual([PW], list(self.kr.store.values()))
        self.assertTrue(bp.has())
        for base, _d, files in os.walk(self.dir):
            for n in files:
                self.assertNotIn(PW.encode(), self.raw(os.path.join(base, n)), n)
        # A later backup (automatic or manual) uses the remembered password.
        again = br.create_data_backup(out_dir=self.out)
        ok, msg = br.restore_data_backup(again, mode="merge", password=PW)
        self.assertTrue(ok, msg)
        self.assertTrue(ss.backup_password_status()["remembered"])
        bp.forget()
        self.assertFalse(bp.has())
        with self.assertRaises(bp.PasswordRequired):
            br.create_data_backup(out_dir=self.out)

    def test_no_keyring_means_not_remembered(self):
        with mock.patch.object(bp, "_keyring", lambda: None):
            ss.Backup().create(password=PW, remember=True)
            self.assertFalse(bp.has())
        self.assertEqual({}, self.kr.store)

    def test_check_and_strength(self):
        self.assertIn(str(bp.MIN_LEN), bp.check("abc"))
        self.assertEqual("The passwords do not match.", bp.check(PW, PW + "x"))
        self.assertEqual("", bp.check(PW, PW))
        self.assertLess(bp.strength("aaaaaaaa")["score"], bp.strength("Ab3$kq9!Lm2#zx7&")["score"])


class AutoAndUpdateBackupTests(Case):
    def enable_auto(self):
        self.assertTrue(ss._save_backup_settings({"auto_enabled": True, "interval_hours": 24, "keep": 5}))

    def test_auto_backup_without_password_is_skipped_with_a_notice(self):
        self.enable_auto()
        ok, msg = ss.auto_backup_if_needed()
        self.assertFalse(ok)
        self.assertEqual(ss.AUTO_BACKUP_SKIPPED, msg)
        self.assertEqual(ss.AUTO_BACKUP_SKIPPED, ss.get_backup_notice()["text"])
        self.assertEqual([], ss.Backup().list())
        bp.remember(PW)
        ok, msg = ss.auto_backup_if_needed()
        self.assertTrue(ok, msg)
        (path, _mt, _sz), = ss.Backup().list()
        self.assertTrue(loyabak.is_loyabak(path))
        self.assertIsNone(ss.get_backup_notice(), "a good backup clears the notice")

    def test_update_backup_without_password_skips_the_data_copy(self):
        snap = {"path": os.path.join(self.out, "code.zip")}
        with mock.patch.object(br, "create_code_snapshot", return_value=snap):
            res = br.prepare_update_backups(current_version="1.0.0", data_backup_dir=self.out, code_backup_dir=self.out)
            self.assertEqual("", res["data_backup"])
            self.assertIn("set a backup password", res["data_backup_skipped"].lower())
            self.assertEqual(snap["path"], res["code_snapshot"])
            self.assertEqual([], os.listdir(self.out))
            bp.remember(PW)
            res = br.prepare_update_backups(current_version="1.0.0", data_backup_dir=self.out, code_backup_dir=self.out)
        self.assertTrue(loyabak.is_loyabak(res["data_backup"]))
        self.assertEqual("", res["data_backup_skipped"])


class LegacyPlainZipTests(Case):
    def test_old_plain_zip_restores_with_a_warning(self):
        zp = os.path.join(self.out, "Backup_old.zip")
        with zipfile.ZipFile(zp, "w") as z:
            z.writestr("Data/tag_colors.json", '{"web":"#ff0000"}')
        info = br.backup_needs_pin(zp)
        self.assertEqual(("none", True, False), (info["protect"], info["legacy_plain"], info["needs_password"]))
        ok, msg = br.restore_data_backup(zp, mode="merge")
        self.assertTrue(ok, msg)
        self.assertIn(br.LEGACY_PLAIN_WARNING, msg)
        with open(os.path.join(self.dir, "tag_colors.json"), encoding="utf-8") as f:
            self.assertEqual({"web": "#ff0000"}, json.load(f))


if __name__ == "__main__":
    unittest.main()
