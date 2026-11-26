"""Storage rebuild (phase 2): what lives where once encryption at rest is on - JSON stores, API keys, attachments, terminal spill
files, backups, health check - and that nothing changes with encryption off."""
import base64
import json
import os
import unittest
import zipfile
from unittest import mock

from _isolate import IsolatedData
from Cores import common_db, crypto_store, db_driver, doc_store, loyabak, secret_store
from Cores.Update import backup_restore, health_check
from Cores.Services import security_service as sec

EPIN = "482193"
FAST_KDF = {"name": "argon2id", "m_kib": 8192, "t": 1, "p": 1} if crypto_store.has_argon2() else {"name": "scrypt", "n": 2 ** 14, "r": 8, "p": 1}
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


class Case(unittest.TestCase):
    def setUp(self):
        self.iso = IsolatedData()
        self.dir = self.iso.start()
        self._kdf = sec._KDF
        sec._KDF = FAST_KDF
        sec.clear_session_pin()
        common_db.set_locked(False)
        with common_db.connection() as con:
            common_db.ensure_schema(con)
            con.execute("INSERT INTO Notes(note_name,content) VALUES('n1','secret-body')")

    def tearDown(self):
        sec.clear_session_pin()
        common_db.set_locked(False)
        sec._KDF = self._kdf
        self.iso.stop()

    def p(self, *a):
        return os.path.join(self.dir, *a)

    def write_json(self, rel, obj):
        os.makedirs(os.path.dirname(self.p(rel)), exist_ok=True)
        with open(self.p(rel), "w", encoding="utf-8") as f:
            json.dump(obj, f)

    def enable(self):
        ok, msg = sec.set_encryption(True, new_pin=EPIN)
        self.assertTrue(ok, msg)


class PlainModeTests(Case):
    """Encryption off: the stores are the same plain files as before."""

    def test_doc_store_falls_through_to_files(self):
        path = self.p("notes_meta.json")
        self.assertFalse(doc_store.active(path))
        self.assertTrue(doc_store.write_json(path, {"pinned": [1]}))
        with open(path, encoding="utf-8") as f:
            self.assertEqual({"pinned": [1]}, json.load(f))
        self.assertEqual({"pinned": [1]}, doc_store.read_json(path))
        self.assertTrue(doc_store.exists(path))
        self.assertIsNotNone(doc_store.mtime(path))
        doc_store.remove(path)
        self.assertFalse(os.path.exists(path))

    def test_doc_patterns(self):
        for rel in ("profiles.json", "Profiles/ab12/Targets.json", "ai_sessions/x1.json", "search_index/index.json", "external_agents/usage.json"):
            self.assertTrue(doc_store.is_doc_path(self.p(rel)), rel)
        for rel in ("settings.json", "security_audit.jsonl", "Profiles/a/b/Targets.json", "cve_index/cve_index.sqlite", "Note_LOYA_V1.key"):
            self.assertFalse(doc_store.is_doc_path(self.p(rel)), rel)

    def test_secret_store_unavailable(self):
        self.assertFalse(secret_store.available())
        self.assertFalse(secret_store.put("x", "y"))
        self.assertIsNone(secret_store.get("x"))


@unittest.skipUnless(db_driver.has_sqlcipher(), "sqlcipher3 not installed")
class EncryptedModeTests(Case):
    def test_stores_move_into_the_db_and_back(self):
        self.write_json("Profiles/ab12/Targets.json", [{"id": "t", "values": {"Password": "Hunter2!"}}])
        self.write_json("ai_sessions/s1.json", {"messages": ["hello secret-body"]})
        self.enable()
        self.assertFalse(os.path.exists(self.p("Profiles/ab12/Targets.json")))
        self.assertFalse(os.path.exists(self.p("ai_sessions/s1.json")))
        self.assertEqual([{"id": "t", "values": {"Password": "Hunter2!"}}], doc_store.read_json(self.p("Profiles/ab12/Targets.json")))
        doc_store.write_json(self.p("notes_meta.json"), {"pinned": [2]})
        self.assertFalse(os.path.exists(self.p("notes_meta.json")), "new writes go to the DB, not a file")
        sig = doc_store.signature(self.p("notes_meta.json"))
        self.assertIsNotNone(sig)
        doc_store.remove_dir(self.p("Profiles", "ab12"))
        self.assertIsNone(doc_store.read_json(self.p("Profiles/ab12/Targets.json")))
        sec.lock_now("t")
        self.assertEqual("locked", doc_store.read_json(self.p("notes_meta.json"), "locked"))
        self.assertFalse(doc_store.write_json(self.p("notes_meta.json"), {}), "no plaintext fallback while locked")
        self.assertFalse(os.path.exists(self.p("notes_meta.json")))
        sec.unlock(EPIN)
        self.assertEqual({"pinned": [2]}, doc_store.read_json(self.p("notes_meta.json")))

    def test_targets_service_round_trip(self):
        from Cores.Services import targets_service as ts
        self.enable()
        st = ts.Store()
        st.values = {"IP": {"priority": 1}}
        st.save_values()
        ok, _msg = st.upsert_target(None, "web01", "not_used", {"IP": "10.0.0.5"})
        self.assertTrue(ok)
        again = ts.Store()
        self.assertEqual(["web01"], [t["name"] for t in again.targets])
        self.assertFalse([n for n in os.listdir(self.dir) if n.endswith(".json") and n != "settings.json"])

    def test_api_keys_live_in_secrets(self):
        from Cores.Services import ext_agents_service as ext
        self.enable()
        provider = ext.PROVIDERS[0]
        with mock.patch.object(ext, "_keyring", return_value=None):
            state = ext.set_api_key(provider, "sk-test-0123456789abcdef")
            self.assertEqual("encrypted", state["store"])
            with open(self.p("settings.json"), "rb") as f:
                self.assertNotIn(b"0123456789abcdef", f.read())
            ext._session_keys.clear()
            self.assertEqual("sk-test-0123456789abcdef", ext.get_api_key(provider))
            sec.lock_now("t")
            ext._session_keys.clear()
            self.assertIsNone(ext.get_api_key(provider))
            self.assertTrue(ext.key_state(provider)["stored_but_locked"])
            sec.unlock(EPIN)
            self.assertEqual("sk-test-0123456789abcdef", ext.get_api_key(provider))

    def test_legacy_fernet_api_key_is_adopted(self):
        from Cores import storage_migration as mig
        from Cores.Services import ext_agents_service as ext
        self.enable()
        provider = ext.PROVIDERS[0]
        f = mig.legacy_fernet(EPIN, base64.b64encode(b"s" * 16).decode())
        ext._save_cfg(provider, lambda cur: cur.update(key_store="encrypted", key_hint="x", key_enc=f.encrypt(b"sk-legacy-key-000111").decode()))
        sec._adopt_legacy_keys(f)
        self.assertEqual("", ext._cfg(provider)["key_enc"])
        ext._session_keys.clear()
        self.assertEqual("sk-legacy-key-000111", ext.get_api_key(provider))

    def test_attachments_are_encrypted_and_viewable(self):
        from Cores.Services import notes_service as ns
        real_abs = ns._abs
        ns._abs = lambda *p: os.path.join(self.dir, *(p[1:] if p and p[0] == "Data" else p))
        self.addCleanup(setattr, ns, "_abs", real_abs)
        os.makedirs(self.p("Attachments", "1"), exist_ok=True)
        with open(self.p("Attachments", "1", "abcdef0123456789.png"), "wb") as f:
            f.write(PNG)
        self.enable()
        self.assertTrue(crypto_store.is_encrypted_file(self.p("Attachments", "1", "abcdef0123456789.png")))
        att = ns.save_pending_attachment("shot.png", base64.b64encode(PNG).decode())
        pending = [n for n in os.listdir(self.p("Attachments", "_pending"))]
        with open(self.p("Attachments", "_pending", pending[0]), "rb") as f:
            self.assertTrue(crypto_store.is_encrypted_blob(f.read()))
        for aid in ("abcdef0123456789", att["id"]):
            view = ns.attachment_view(aid)
            self.assertEqual(base64.b64encode(PNG).decode(), view["data_url"].split(",", 1)[1])
        self.assertEqual(len(PNG), ns.attachment_data_url(att["id"])["size"])
        sec.lock_now("t")
        with self.assertRaises(common_db.DatabaseLocked):
            ns.attachment_view(att["id"])

    def test_spill_files_are_encrypted(self):
        from Cores.Services import terminal_service as term
        self.enable()
        body = "x" * (term._SPILL_THRESHOLD + 10) + "secret-body"
        term._batch_store_output("job1", body)
        rec = term._batch_outputs["job1"]
        with open(rec["path"], "rb") as f:
            self.assertTrue(crypto_store.is_encrypted_blob(f.read()))
        self.assertTrue(term.batch_output("job1", full=True).endswith("secret-body"))
        term.clear_batch_output("job1")

    def test_health_check_treats_encrypted_db_as_locked(self):
        self.enable()
        sec.lock_now("t")
        rep = health_check.HealthReport() if hasattr(health_check, "HealthReport") else None
        if rep is None:
            self.skipTest("no HealthReport class")
        health_check._check_database(rep, False, json.load(open(health_check.settings_path())))
        self.assertTrue(rep.db_deferred)
        self.assertEqual([], rep.errors)
        self.assertEqual("encrypted", db_driver.file_kind(common_db.db_path()))

    def test_encrypted_backup_and_restore(self):
        os.makedirs(self.p("cve_index"), exist_ok=True)
        with open(self.p("cve_index", "cve_index.sqlite"), "wb") as f:
            f.write(b"public")
        self.write_json("notes_meta.json", {"pinned": [1]})
        self.enable()
        with common_db.connection() as con:
            con.execute("CREATE TABLE IF NOT EXISTS ChainGraphs(playbook_id INTEGER PRIMARY KEY,graph TEXT NOT NULL,schema_version INTEGER NOT NULL DEFAULT 1,ai_made INTEGER NOT NULL DEFAULT 0,ai_reviewed INTEGER NOT NULL DEFAULT 1,ai_client TEXT,created_at TEXT,updated_at TEXT)")
            con.execute("INSERT OR REPLACE INTO ChainGraphs(playbook_id,graph,ai_reviewed) VALUES(1,'{}',1)")
        out = backup_restore.create_data_backup(out_dir=self.p("bk"))
        self.assertTrue(out.endswith(".loyabak"))
        self.assertTrue(loyabak.is_loyabak(out))
        with open(out, "rb") as f:
            raw = f.read()
        self.assertNotIn(b"secret-body", raw)
        self.assertNotIn(b"pinned", raw)
        zp = self.p("bk", "x.zip")
        loyabak.decrypt_to(out, zp, common_db.session_key())
        with zipfile.ZipFile(zp) as z:
            names = z.namelist()
        self.assertIn("Data/Note_LOYA_V1.db", names)
        self.assertIn("Data/Note_LOYA_V1.key", names)
        self.assertFalse([n for n in names if "cve_index" in n], "the public CVE index is never backed up")
        with common_db.connection() as con:
            con.execute("DELETE FROM Notes")
        ok, msg = backup_restore.restore_data_backup(out, mode="replace", pin=EPIN)
        self.assertTrue(ok, msg)
        with common_db.connection() as con:
            self.assertEqual(1, con.execute("SELECT COUNT(*) FROM Notes").fetchone()[0])
            self.assertEqual(0, con.execute("SELECT ai_reviewed FROM ChainGraphs").fetchone()[0], "a restore never vouches for its chains")
        self.assertEqual("encrypted", db_driver.file_kind(common_db.db_path()))

    def test_backup_from_another_pin_needs_that_pin(self):
        self.enable()
        out = backup_restore.create_data_backup(out_dir=self.p("bk"))
        other = crypto_store.DataKey.generate()
        common_db.set_session_key(other)
        try:
            ok, msg = backup_restore.restore_data_backup(out, mode="replace")
            self.assertFalse(ok)
            self.assertIn("PIN", msg)
            ok, msg = backup_restore.restore_data_backup(out, mode="replace", pin="000000")
            self.assertFalse(ok)
            ok, msg = backup_restore.restore_data_backup(out, mode="replace", pin=EPIN)
            self.assertTrue(ok, msg)
            self.assertFalse(common_db.session_key() is other, "the session continues with the backup's key")
        finally:
            other.wipe()

    def test_plain_backup_is_refused_while_encrypted(self):
        plain = backup_restore.create_data_backup(out_dir=self.p("bk"), password="test-backup-pw")
        self.assertTrue(loyabak.is_loyabak(plain), "a backup made with encryption at rest off is password-protected")
        self.enable()
        ok, msg = backup_restore.restore_data_backup(plain, mode="replace", password="test-backup-pw")
        self.assertFalse(ok)
        self.assertIn("not encrypted", msg)
        self.assertEqual("encrypted", db_driver.file_kind(common_db.db_path()))

    def test_audit_content_events_move_into_the_db(self):
        sec.log_audit_event("terminal_command", "nmap -sV corp-dc01.globex.local", True)
        self.enable()
        with open(sec._audit_path(), encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("globex", text, "existing command lines left the plaintext log")
        self.assertIn("encryption_toggle", text)
        sec.log_audit_event("terminal_command", "smbclient //files01.globex/share", True)
        with open(sec._audit_path(), encoding="utf-8") as f:
            self.assertNotIn("files01", f.read())
        events = [e["detail"] for e in sec.list_audit_events() if e["event"] == "terminal_command"]
        self.assertEqual(2, len(events))
        sec.lock_now("t")
        sec.log_audit_event("terminal_command", "secret-while-locked.globex", True)
        with open(sec._audit_path(), encoding="utf-8") as f:
            self.assertNotIn("secret-while-locked", f.read())
        sec.unlock(EPIN)
        self.assertTrue(sec.set_encryption(False, pin=EPIN)[0])
        with open(sec._audit_path(), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("corp-dc01.globex.local", text, "with encryption off they come back to the file")
        self.assertIn("files01.globex", text)

    def test_plain_db_export_needs_the_typed_pin(self):
        import sqlite3
        from Cores.Services import notes_service as ns
        ne = ns.NotesExport()
        out = self.p("export.db")
        ne.export_db(out)  # encryption off: no PIN asked, as before
        self.assertTrue(os.path.isfile(out))
        os.remove(out)
        self.enable()
        with self.assertRaises(ValueError) as ctx:
            ne.export_db(out)
        self.assertIn("NOT encrypted", str(ctx.exception))
        with self.assertRaises(ValueError) as ctx:
            ne.export_db(out, pin="000000")
        self.assertIn("Wrong PIN", str(ctx.exception))
        self.assertFalse(os.path.exists(out))
        ne.export_db(out, pin=EPIN)
        c = sqlite3.connect(out)
        try:
            self.assertEqual(1, c.execute("SELECT COUNT(*) FROM Notes").fetchone()[0], "the export is a plain, readable copy")
        finally:
            c.close()
        with open(sec._audit_path(), encoding="utf-8") as f:
            events = [json.loads(line) for line in f if line.strip()]
        plain = [(e["success"], e["detail"]) for e in events if e["event"] == "plain_export"]
        self.assertEqual([False, True], [x[0] for x in plain], plain)

    def test_bridge_export_and_restore_pin_checks(self):
        from Cores.Bridge import api
        ie = api.ImportExportAPI()
        self.assertFalse(ie.export_needs_pin("notes", "db")["needs_pin"])
        self.enable()
        self.assertTrue(ie.export_needs_pin("notes", "db")["needs_pin"])
        self.assertFalse(ie.export_needs_pin("notes", "json")["needs_pin"])
        self.assertIn("NOT encrypted", ie.export_needs_pin("notes", "db")["warning"])
        own = backup_restore.create_data_backup(out_dir=self.p("bk"))
        self.assertEqual({"encrypted": True, "needs_pin": False, "protect": "pin"}, {k: v for k, v in backup_restore.backup_needs_pin(own).items() if k in ("encrypted", "needs_pin", "protect")})
        plain_zip = self.p("bk", "plain.zip")
        with zipfile.ZipFile(plain_zip, "w") as z:
            z.writestr("Data/x.txt", "x")
        self.assertFalse(backup_restore.backup_needs_pin(plain_zip)["encrypted"])
        other = crypto_store.DataKey.generate()
        mine = common_db.session_key()
        common_db.set_session_key(other)
        try:
            self.assertTrue(backup_restore.backup_needs_pin(own)["needs_pin"], "made under another key: ask for its PIN")
            api._remember_pick(own)
            self.assertTrue(ie.import_needs_pin(own)["needs_pin"])
            # A full backup is restored under Settings > Backup (Import & Export takes work exports only).
            bk = api.BackupAPI()
            with self.assertRaises(ValueError) as ctx:
                bk.restore(own, "replace", "000000")
            self.assertIn("Wrong PIN", str(ctx.exception))
            self.assertEqual("Restore done. Restart app if needed.", bk.restore(own, "replace", EPIN))
        finally:
            other.wipe()
            if common_db.session_key() is other:
                common_db.set_session_key(mine)

    def test_backups_stay_in_the_scratch_area(self):
        from Cores.Update import health_check as hc
        real = os.path.normcase(os.path.abspath(hc.backups_dir()))
        before = set(os.listdir(real)) if os.path.isdir(real) else set()
        self.enable()
        made = backup_restore.create_data_backup()
        self.assertTrue(os.path.normcase(os.path.abspath(made)).startswith(os.path.normcase(self.dir)), made)
        self.assertTrue([n for n in os.listdir(common_db.backups_dir()) if n.startswith("pre-encryption-")])
        after = set(os.listdir(real)) if os.path.isdir(real) else set()
        self.assertEqual(before, after, "nothing was written into the app's real Backups/")
        # Without the _isolate override, a moved Data/ still never uses the app's Backups/.
        override = common_db.backups_dir
        common_db.backups_dir = self.iso._backups_dir
        try:
            self.assertEqual(os.path.join(self.dir, "_backups"), common_db.backups_dir())
        finally:
            common_db.backups_dir = override

    def test_loyabak_tamper_is_detected(self):
        self.enable()
        out = backup_restore.create_data_backup(out_dir=self.p("bk"))
        with open(out, "r+b") as f:
            f.seek(-5, 2)
            b = f.read(1)
            f.seek(-5, 2)
            f.write(bytes([b[0] ^ 1]))
        with self.assertRaises(crypto_store.TamperError):
            loyabak.verify(out, common_db.session_key())
        ok, _msg = backup_restore.restore_data_backup(out, mode="replace")
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
