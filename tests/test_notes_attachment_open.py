"""Notes file attachments: Open (system app via a private plain copy) and Save as (stream into the chosen file). Only ids come from
the UI; the path is resolved under Data/Attachments, a locked app refuses, and every attempt is in the security audit log."""
import base64
import os
import stat
import tempfile
import unittest
from unittest import mock

from _isolate import IsolatedData
from Cores import common_db, crypto_store, db_driver
from Cores.Services import notes_service as ns
from Cores.Services import security_service as sec

EPIN = "482193"
FAST_KDF = {"name": "argon2id", "m_kib": 8192, "t": 1, "p": 1} if crypto_store.has_argon2() else {"name": "scrypt", "n": 2 ** 14, "r": 8, "p": 1}
BLOB = os.urandom(200_000) + b"tail-marker"


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
        real_abs = ns._abs
        ns._abs = lambda *p: os.path.join(self.dir, *(p[1:] if p and p[0] == "Data" else p))
        self.addCleanup(setattr, ns, "_abs", real_abs)
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.addCleanup(ns.purge_open_attachment_copies)

    def tearDown(self):
        sec.clear_session_pin()
        common_db.set_locked(False)
        sec._KDF = self._kdf
        self.iso.stop()

    def p(self, *a):
        return os.path.join(self.dir, *a)

    def add(self, name="report.pdf", data=BLOB):
        return ns.save_pending_attachment(name, base64.b64encode(data).decode())

    def events(self, name):
        return [e for e in sec.list_audit_events(500) if e.get("event") == name]


class AllowListTests(Case):
    def test_bad_ids_are_rejected(self):
        for bad in ("../../etc/passwd", "/etc/passwd", "..", "", "abc", "ABCDEF0123456789/../x", "C:\\Windows\\win.ini", "abcdef0123456789\x00"):
            with self.assertRaises(ValueError, msg=bad):
                ns.resolve_attachment_file(bad)
        opener = mock.Mock()
        with self.assertRaises(ValueError):
            ns.open_attachment("../../etc/passwd", "x", opener=opener)
        opener.assert_not_called()

    def test_unknown_id(self):
        with self.assertRaises(ValueError):
            ns.resolve_attachment_file("0123456789abcdef")

    def test_symlink_out_of_the_folder_is_rejected(self):
        outside = os.path.join(self.tmp, "secret.txt")
        with open(outside, "wb") as f:
            f.write(b"outside")
        d = self.p("Attachments", "7")
        os.makedirs(d)
        try:
            os.symlink(outside, os.path.join(d, "aaaabbbbccccdddd.txt"))
            os.symlink(self.tmp, self.p("Attachments", "8"))
        except (OSError, NotImplementedError):
            self.skipTest("no symlinks here")
        with open(os.path.join(self.tmp, "1111222233334444.txt"), "wb") as f:
            f.write(b"outside dir")
        for aid in ("aaaabbbbccccdddd", "1111222233334444"):
            with self.assertRaises(ValueError, msg=aid):
                ns.resolve_attachment_file(aid)
            with self.assertRaises(ValueError):
                ns.save_attachment_copy(aid, os.path.join(self.tmp, "out.txt"))

    def test_display_name_cannot_steer_the_copy(self):
        att = self.add("report.pdf")
        path, name = ns.attachment_open_copy(att["id"], "../../evil/..\\x.desktop")
        self.assertEqual("x.pdf", name)
        self.assertEqual(os.path.realpath(ns._ATTACHMENT_OPEN_STATE["dir"]), os.path.dirname(os.path.dirname(os.path.realpath(path))))

    def test_program_types_are_save_only(self):
        att = self.add("run.desktop", b"[Desktop Entry]\nExec=xterm\n")
        opener = mock.Mock()
        with self.assertRaises(ValueError):
            ns.open_attachment(att["id"], "run.desktop", opener=opener)
        opener.assert_not_called()
        out = ns.save_attachment_copy(att["id"], os.path.join(self.tmp, "run.desktop"))
        with open(out, "rb") as f:
            self.assertEqual(b"[Desktop Entry]\nExec=xterm\n", f.read())


class PlainTests(Case):
    def test_open_makes_a_private_identical_copy_and_audits(self):
        att = self.add("report.pdf")
        opener = mock.Mock()
        r = ns.open_attachment(att["id"], "report.pdf", opener=opener)
        self.assertEqual("report.pdf", r["name"])
        path = opener.call_args[0][0]
        with open(path, "rb") as f:
            self.assertEqual(BLOB, f.read())
        if os.name != "nt":
            self.assertEqual(0o600, stat.S_IMODE(os.stat(path).st_mode))
            self.assertEqual(0o700, stat.S_IMODE(os.stat(ns._ATTACHMENT_OPEN_STATE["dir"]).st_mode))
        ev = self.events("attachment_open")
        self.assertTrue(ev and ev[-1]["success"] and att["id"] in ev[-1]["detail"])
        ns.purge_open_attachment_copies()
        self.assertFalse(os.path.exists(path))

    def test_save_as_copies_bytes_and_audits(self):
        att = self.add("data.bin")
        out = ns.save_attachment_copy(att["id"], os.path.join(self.tmp, "copy.bin"), "data.bin")
        with open(out, "rb") as f:
            self.assertEqual(BLOB, f.read())
        ev = self.events("attachment_save")
        self.assertTrue(ev and ev[-1]["success"] and "copy.bin" in ev[-1]["detail"])

    def test_finalized_attachment_is_found(self):
        att = self.add("notes.txt", b"hello")
        ns.finalize_attachments(f'<figure data-attachment-id="{att["id"]}"></figure>', 3)
        self.assertTrue(ns.resolve_attachment_file(att["id"]).startswith(os.path.realpath(self.p("Attachments", "3"))))

    def test_stale_copies_of_a_dead_process_are_swept(self):
        dead = os.path.join(self.tmp, ns._ATTACHMENT_OPEN_PREFIX + "999999999_x")
        mine = os.path.join(self.tmp, ns._ATTACHMENT_OPEN_PREFIX + str(os.getpid()) + "_y")
        os.makedirs(dead)
        os.makedirs(mine)
        ns.sweep_stale_attachment_copies(self.tmp)
        self.assertFalse(os.path.exists(dead))
        self.assertTrue(os.path.exists(mine))


@unittest.skipUnless(db_driver.has_sqlcipher(), "sqlcipher3 not installed")
class EncryptedTests(Case):
    def enable(self):
        ok, msg = sec.set_encryption(True, new_pin=EPIN)
        self.assertTrue(ok, msg)

    def test_open_decrypts_to_private_temp(self):
        self.enable()
        att = self.add("report.pdf")
        self.assertTrue(crypto_store.is_encrypted_file(ns.resolve_attachment_file(att["id"])))
        opener = mock.Mock()
        ns.open_attachment(att["id"], "report.pdf", opener=opener)
        path = opener.call_args[0][0]
        with open(path, "rb") as f:
            self.assertEqual(BLOB, f.read())
        if os.name != "nt":
            self.assertEqual(0o600, stat.S_IMODE(os.stat(path).st_mode))
        self.assertTrue(self.events("attachment_open")[-1]["success"])
        sec.lock_now("t")
        self.assertFalse(os.path.exists(path), "lock drops the decrypted copy")

    def test_save_as_streams_plaintext(self):
        self.enable()
        att = self.add("data.bin")
        out = ns.save_attachment_copy(att["id"], os.path.join(self.tmp, "plain.bin"), "data.bin")
        with open(out, "rb") as f:
            self.assertEqual(BLOB, f.read())

    def test_tampered_stream_leaves_nothing(self):
        self.enable()
        att = self.add("data.bin")
        real = ns.resolve_attachment_file(att["id"])
        with open(real, "r+b") as f:
            f.seek(-5, 2)
            f.write(b"XXXXX")
        target = os.path.join(self.tmp, "t.bin")
        with self.assertRaises(crypto_store.TamperError):
            ns.save_attachment_copy(att["id"], target)
        self.assertFalse(os.path.exists(target))
        self.assertEqual([], [n for n in os.listdir(self.tmp)])

    def test_locked_refuses_and_audits(self):
        self.enable()
        att = self.add("data.bin")
        sec.lock_now("t")
        opener = mock.Mock()
        with self.assertRaises(common_db.DatabaseLocked):
            ns.open_attachment(att["id"], "data.bin", opener=opener)
        opener.assert_not_called()
        with self.assertRaises(common_db.DatabaseLocked):
            ns.save_attachment_copy(att["id"], os.path.join(self.tmp, "x.bin"))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "x.bin")))
        ev = self.events("attachment_open") + self.events("attachment_save")
        self.assertTrue(ev and not any(e["success"] for e in ev))


class BridgeTests(Case):
    def test_save_as_uses_the_native_dialog_path(self):
        from Cores.Bridge import api
        att = self.add("data.bin")
        n = api.NotesAPI()
        win = mock.Mock()
        target = os.path.join(self.tmp, "picked.bin")
        with mock.patch.object(api, "_save_dialog", return_value=target) as dlg:
            n.bind(win)
            self.assertEqual(target, n.attachment_save_as(att["id"], "data.bin"))
        self.assertEqual(("data.bin",), dlg.call_args[0][3:])
        with open(target, "rb") as f:
            self.assertEqual(BLOB, f.read())
        with mock.patch.object(api, "_save_dialog", return_value=None):
            self.assertIsNone(n.attachment_save_as(att["id"], "data.bin"))

    def test_locked_bridge_refuses(self):
        from Cores.Bridge import api
        att = self.add("data.bin")
        n = api.NotesAPI()
        n.bind(mock.Mock())
        with mock.patch.object(sec, "is_locked", return_value=True), mock.patch.object(api, "_save_dialog") as dlg:
            with self.assertRaises(common_db.DatabaseLocked):
                n.attachment_save_as(att["id"], "data.bin")
            with self.assertRaises(common_db.DatabaseLocked):
                n.attachment_open(att["id"], "data.bin")
        dlg.assert_not_called()

    def test_system_opener_is_platform_gated(self):
        with mock.patch.object(ns.os, "name", "posix"), mock.patch("Cores.Update.recovery.open_with_desktop", return_value=(True, "")) as xo:
            ns._open_with_system("/tmp/x.pdf")
        xo.assert_called_once_with("/tmp/x.pdf")
        with mock.patch.object(ns.os, "name", "nt"), mock.patch.object(ns.os, "startfile", create=True) as sf:
            ns._open_with_system("C:\\x.pdf")
        sf.assert_called_once_with("C:\\x.pdf")


if __name__ == "__main__":
    unittest.main()
