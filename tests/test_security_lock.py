import os,json,base64,threading,unittest
from datetime import datetime,timezone,timedelta
from unittest import mock
from _isolate import IsolatedData
from Cores import common_db,settings_lock,db_driver,crypto_store
from Cores.Update import health_check
from Cores.Services import security_service as sec
PIN="4821"
EPIN="482193"  # encryption at rest needs 6+ characters
FAST_KDF={"name":"argon2id","m_kib":8192,"t":1,"p":1} if crypto_store.has_argon2() else {"name":"scrypt","n":2**14,"r":8,"p":1}
class SecurityCase(unittest.TestCase):
    def setUp(self):
        self.iso=IsolatedData();self.dir=self.iso.start()
        self.settings=os.path.join(self.dir,"settings.json")
        self._settings_path=health_check.settings_path
        health_check.settings_path=lambda:self.settings
        self._iters=sec._PIN_ITERS;sec._PIN_ITERS=1000
        self._kdf=sec._KDF;sec._KDF=FAST_KDF
        sec.clear_session_pin();common_db.set_locked(False);sec._MCP_RESUME_PORT=None
    def tearDown(self):
        sec.clear_session_pin();common_db.set_locked(False);sec._PIN_ITERS=self._iters;sec._KDF=self._kdf
        health_check.settings_path=self._settings_path
        self.iso.stop()
    def make_db(self,notes=3):
        with common_db.connection() as con:
            common_db.ensure_schema(con)
            for i in range(notes):con.execute("INSERT INTO Notes(note_name,content) VALUES(?,?)",(f"n{i}","secret-note-body"))
        return common_db.db_path()
    def rows(self):
        with common_db.connection() as con:return con.execute("SELECT COUNT(*) FROM Notes").fetchone()[0]
    def touch_db_like_a_bridge_call(self):
        # What every service does: connect, then ensure_schema. A locked/encrypted DB must refuse, never start an empty one.
        try:
            with common_db.connection(timeout=5) as con:
                common_db.ensure_schema(con)
                return con.execute("SELECT COUNT(*) FROM Notes").fetchone()[0]
        except Exception:return None
    def plaintext_hits(self,needle=b"secret-note-body"):
        hits=[]
        for d,_,files in os.walk(self.dir):
            for n in files:
                p=os.path.join(d,n)
                with open(p,"rb") as f:
                    if needle in f.read():hits.append(os.path.relpath(p,self.dir))
        return hits
_NEED=db_driver.has_sqlcipher() and sec._HAS_CRYPTO
@unittest.skipUnless(_NEED,"sqlcipher3/cryptography not installed")
class EncryptionAtRestTests(SecurityCase):
    """Storage rebuild: the DB is SQLCipher on disk at all times; the data key exists only in memory while unlocked."""
    def test_lock_then_db_access_then_unlock_keeps_the_data(self):
        self.make_db(3)
        ok,msg=sec.set_encryption(True,new_pin=EPIN);self.assertTrue(ok,msg)
        self.assertEqual("encrypted",db_driver.file_kind(common_db.db_path()))
        self.assertTrue(sec.lock_now("idle"))
        self.assertIsNone(common_db.session_key())
        self.assertIsNone(self.touch_db_like_a_bridge_call())
        self.assertEqual("encrypted",db_driver.file_kind(common_db.db_path()),"the file is never removed or replaced at lock")
        ok,msg=sec.unlock(EPIN);self.assertTrue(ok,msg)
        self.assertEqual(3,self.rows())
        self.assertTrue(sec.encrypt_on_exit()[0])
        self.assertIsNone(common_db.session_key())
        self.assertEqual([],self.plaintext_hits())
    def test_db_is_refused_while_locked(self):
        self.make_db(1)
        sec.set_encryption(True,new_pin=EPIN)
        sec.lock_now("idle")
        self.assertTrue(common_db.is_locked())
        with self.assertRaises(common_db.DatabaseLocked):common_db.connect()
        sec.unlock(EPIN)
        self.assertFalse(common_db.is_locked())
    def test_at_rest_check_works_without_the_flag(self):
        # Another process (stdio MCP) never sees the in-memory flag: an encrypted file without the key must still be refused.
        self.make_db(1)
        sec.set_encryption(True,new_pin=EPIN)
        sec.lock_now("idle");common_db.set_locked(False)
        self.assertTrue(common_db.db_locked())
        self.assertIsNone(self.touch_db_like_a_bridge_call())
        self.assertEqual("encrypted",db_driver.file_kind(common_db.db_path()))
    def test_a_missing_db_is_never_recreated_plain(self):
        self.make_db(1)
        sec.set_encryption(True,new_pin=EPIN)
        sec.lock_now("idle");common_db.set_locked(False)
        os.remove(common_db.db_path())
        self.assertIsNone(self.touch_db_like_a_bridge_call())
        self.assertFalse(os.path.exists(common_db.db_path()))
        sec.unlock(EPIN)
        self.assertEqual(0,self.touch_db_like_a_bridge_call(),"unlocked, a new DB is created - encrypted")
        self.assertEqual("encrypted",db_driver.file_kind(common_db.db_path()))
    def test_kill_while_unlocked_leaves_no_plaintext(self):
        self.make_db(2)
        json.dump([{"id":"t","name":"web","values":{"Password":"secret-note-body"}}],open(os.path.join(self.dir,"Targets.json"),"w"))
        sec.set_encryption(True,new_pin=EPIN)
        with common_db.connection() as con:con.execute("INSERT INTO Notes(note_name,content) VALUES('late','secret-note-body')")
        # "kill": no lock, no exit hook. Everything on disk must already be ciphertext.
        self.assertEqual([],self.plaintext_hits())
        import sqlite3
        c=sqlite3.connect(common_db.db_path())
        with self.assertRaises(sqlite3.DatabaseError):c.execute("SELECT * FROM sqlite_master").fetchall()
        c.close()
        self.assertFalse(os.path.exists(common_db.db_path()+".enc"))
    def test_wrong_pin_and_pin_change(self):
        self.make_db(2)
        sec.set_encryption(True,new_pin=EPIN)
        kf=crypto_store.load_keyfile(common_db.key_path())
        self.assertEqual((False,"Wrong current PIN."),sec.set_pin("newpin99","000000"))
        self.assertEqual((True,"PIN updated."),sec.set_pin("newpin99",EPIN))
        self.assertEqual(kf["key_id"],crypto_store.load_keyfile(common_db.key_path())["key_id"],"the data key is re-wrapped, not replaced")
        sec.lock_now("t")
        self.assertFalse(sec.unlock(EPIN)[0])
        self.assertTrue(sec.unlock("newpin99")[0])
        self.assertEqual(2,self.rows())
    def test_short_pin_refused_with_encryption(self):
        self.make_db(1)
        self.assertFalse(sec.set_encryption(True,new_pin="1234")[0])
        sec.set_app_lock(True,PIN)
        ok,msg=sec.set_encryption(True,pin=PIN)
        self.assertFalse(ok);self.assertIn("6",msg)
        self.assertEqual("plain",db_driver.file_kind(common_db.db_path()))
    def test_settings_hold_no_pin_hash(self):
        # SA-12: the PIN is verified by unwrapping the Argon2id key file; settings.json keeps no PBKDF2 hash.
        sec.set_app_lock(True,PIN)
        raw=json.load(open(self.settings))["security"]
        self.assertFalse(raw.get("pin_hash"));self.assertFalse(raw.get("pin_salt"))
        self.assertTrue(os.path.isfile(common_db.key_path()))
        self.assertTrue(sec.verify_pin(PIN));self.assertFalse(sec.verify_pin("0000"))
    def test_legacy_pin_hash_is_upgraded_on_unlock(self):
        salt,h=sec.hash_pin(PIN)
        sec.save_security_settings({"pin_salt":salt,"pin_hash":h,"app_lock_enabled":True})
        self.assertTrue(sec.pin_is_set())
        common_db.set_locked(True)
        self.assertFalse(sec.unlock("0000")[0])
        self.assertTrue(sec.unlock(PIN)[0])
        raw=json.load(open(self.settings))["security"]
        self.assertFalse(raw.get("pin_hash"))
        self.assertTrue(crypto_store.verify_pin(PIN,common_db.key_path()))
    def test_kdf_is_upgraded_on_unlock(self):
        sec.set_app_lock(True,PIN)
        self.assertTrue(crypto_store.needs_upgrade(common_db.key_path()))
        sec.clear_session_pin();common_db.set_locked(True)
        sec._KDF=None
        self.assertTrue(sec.unlock(PIN)[0])
        self.assertFalse(crypto_store.needs_upgrade(common_db.key_path()))
        self.assertIn("pin_kdf_upgraded",[e["event"] for e in sec.list_audit_events()])
    def _make_legacy(self,rows=3,plaintext_rows=None):
        """A v1 installation: PBKDF2 pin_hash + Fernet whole-file .db.enc (+ optionally a plaintext DB a crash left)."""
        from Cores import storage_migration as mig
        self.make_db(rows)
        enc_salt=base64.b64encode(os.urandom(16)).decode("ascii")
        f=mig.legacy_fernet(EPIN,enc_salt)
        with open(common_db.db_path(),"rb") as fh:blob=f.encrypt(fh.read())
        with open(common_db.db_path()+".enc","wb") as fh:fh.write(blob)
        if plaintext_rows is None:os.remove(common_db.db_path())
        else:
            with common_db.connection() as con:
                for i in range(plaintext_rows):con.execute("INSERT INTO Notes(note_name,content) VALUES(?,?)",(f"late{i}","secret-note-body"))
            os.utime(common_db.db_path(),None)
        salt,h=sec.hash_pin(EPIN)
        sec.save_security_settings({"pin_salt":salt,"pin_hash":h,"enc_enabled":True,"enc_salt":enc_salt})
        def cve(d):d["cve"]={"key_store":"encrypted","key_hint":"…abcd","key_enc":f.encrypt(b"nvd-legacy-key-0123456789abcd").decode()}
        settings_lock.update_json(self.settings,cve)
        common_db.set_locked(True)
    def test_legacy_v1_enc_is_migrated_on_unlock(self):
        self._make_legacy(3)
        self.assertTrue(common_db.db_locked())
        self.assertFalse(sec.unlock("000000")[0])
        ok,msg=sec.unlock(EPIN);self.assertTrue(ok,msg)
        self.assertEqual("encrypted",db_driver.file_kind(common_db.db_path()))
        self.assertFalse(os.path.exists(common_db.db_path()+".enc"))
        self.assertEqual(3,self.rows())
        raw=json.load(open(self.settings))["security"]
        self.assertEqual(2,raw["enc_version"]);self.assertFalse(raw.get("enc_salt"));self.assertFalse(raw.get("pin_hash"))
        self.assertTrue([n for n in os.listdir(common_db.backups_dir()) if n.endswith(".loyabak")])
        from Cores.Services import cve_service
        with cve_service._key_lock:cve_service._session_key[0]=None
        self.assertEqual("nvd-legacy-key-0123456789abcd",cve_service._get_api_key(),"a v1 Fernet API key moves into the Secrets table")
        self.assertNotIn("key_enc\": \"g",open(self.settings).read())
        self.assertEqual([],self.plaintext_hits())
    def test_legacy_plaintext_left_by_a_crash_is_the_newer_copy(self):
        self._make_legacy(2,plaintext_rows=3)
        self.assertTrue(sec.unlock(EPIN)[0])
        self.assertEqual(5,self.rows())
        self.assertEqual([],self.plaintext_hits())
    def test_failure_before_commit_rolls_back(self):
        from Cores import storage_migration as mig
        self.make_db(2)
        json.dump({"pinned":[1]},open(os.path.join(self.dir,"notes_meta.json"),"w"))
        with mock.patch.object(mig,"_verify_docs",side_effect=mig.MigrationError("simulated")):
            ok,msg=sec.set_encryption(True,new_pin=EPIN)
        self.assertFalse(ok);self.assertIn("simulated",msg)
        self.assertEqual("plain",db_driver.file_kind(common_db.db_path()))
        self.assertTrue(os.path.isfile(os.path.join(self.dir,"notes_meta.json")))
        self.assertFalse(os.path.exists(mig.work_dir()));self.assertIsNone(mig.read_journal())
        self.assertFalse(sec.get_security_settings()["enc_enabled"])
        self.assertEqual(2,self.rows())
    def test_crash_during_commit_is_finished_at_the_next_start(self):
        from Cores import storage_migration as mig
        self.make_db(2)
        json.dump({"pinned":[1]},open(os.path.join(self.dir,"notes_meta.json"),"w"))
        real=mig._commit_enable
        def half():
            # The DB rename happened, then the process died before the settings flip.
            wd=mig.work_dir();mig._sidecars(common_db.db_path())
            os.replace(os.path.join(wd,"enc.db"),common_db.db_path())
            raise KeyboardInterrupt("killed")
        with mock.patch.object(mig,"_commit_enable",half):
            with self.assertRaises(KeyboardInterrupt):sec.set_encryption(True,new_pin=EPIN)
        self.assertEqual("committing",mig.read_journal()["step"])
        sec.clear_session_pin()
        sec.sync_lock_state()  # next start
        self.assertIsNone(mig.read_journal());self.assertFalse(os.path.exists(mig.work_dir()))
        self.assertTrue(sec.get_security_settings()["enc_enabled"])
        self.assertFalse(os.path.isfile(os.path.join(self.dir,"notes_meta.json")),"the plaintext store is gone")
        self.assertTrue(common_db.is_locked())
        self.assertTrue(sec.unlock(EPIN)[0])
        self.assertEqual(2,self.rows())
        from Cores import doc_store
        self.assertEqual({"pinned":[1]},doc_store.read_json(os.path.join(self.dir,"notes_meta.json")))
    def test_disable_brings_plain_files_back(self):
        self.make_db(2)
        json.dump({"pinned":[1]},open(os.path.join(self.dir,"notes_meta.json"),"w"))
        sec.set_encryption(True,new_pin=EPIN)
        ok,msg=sec.set_encryption(False,pin=EPIN);self.assertTrue(ok,msg)
        self.assertEqual("plain",db_driver.file_kind(common_db.db_path()))
        self.assertEqual({"pinned":[1]},json.load(open(os.path.join(self.dir,"notes_meta.json"))))
        self.assertEqual(2,self.rows())
        self.assertTrue(sec.verify_pin(EPIN),"the PIN stays")
    def test_reset_pin_refused_while_encrypted(self):
        self.make_db(1)
        sec.set_encryption(True,new_pin=EPIN)
        ok,msg=sec.reset_pin()
        self.assertFalse(ok);self.assertIn("encrypted",msg)
        self.assertTrue(os.path.isfile(common_db.key_path()))
class LockTests(SecurityCase):
    def test_lock_without_pin_does_not_lock(self):
        self.assertFalse(sec.lock_now("idle"))
        self.assertFalse(common_db.is_locked())
    def test_startup_sync_locks_until_unlock(self):
        self.make_db(1)
        sec.set_app_lock(True,PIN);sec.clear_session_pin()
        self.assertTrue(sec.sync_lock_state())
        self.assertIsNone(self.touch_db_like_a_bridge_call())
        self.assertTrue(sec.unlock(PIN)[0])
        self.assertEqual(1,self.touch_db_like_a_bridge_call())
    def test_mcp_is_stopped_while_locked_and_resumed_after(self):
        from Cores.Services import mcp_local_service as mcp
        self.make_db(1);sec.set_app_lock(True,PIN)
        started=threading.Event()
        with mock.patch.object(mcp,"is_running",return_value=True),mock.patch.object(mcp,"status",return_value={"port":8765}),mock.patch.object(mcp,"stop_server") as stop,mock.patch.object(mcp,"start_server",side_effect=lambda port:started.set()) as start:
            sec.lock_now("idle")
            stop.assert_called_once()
            sec.unlock(PIN)
            self.assertTrue(started.wait(2))
            start.assert_called_once_with(8765)
class BridgeGateTests(SecurityCase):
    def test_bridge_refuses_data_calls_while_locked(self):
        from Cores.Bridge import api
        class Notes:
            def list(self):return ["n"]
            def bind(self,w):return "bound"
        class Security:
            def status(self):return "s"
            def set_app_lock(self,v):return "changed"
        class Fake:
            def __init__(self):
                self.notes=Notes();self.security=Security()
                api._guard_while_locked(self)
            def ping(self):return "pong"
        f=Fake()
        self.assertEqual(["n"],f.notes.list())
        common_db.set_locked(True)
        with self.assertRaises(ValueError):f.notes.list()
        with self.assertRaises(ValueError):f.security.set_app_lock(False)
        self.assertEqual("s",f.security.status())
        self.assertEqual("bound",f.notes.bind(None))
        self.assertEqual("pong",f.ping())
    def test_mcp_tools_refused_while_locked(self):
        try:from Cores.Bridge import mcp_server
        except Exception as e:self.skipTest(f"mcp not importable: {e}")
        common_db.set_locked(True)
        with self.assertRaises(ValueError):mcp_server._check("notes_list")
class WrongPinBackoffTests(SecurityCase):
    """S6: ORIG exits after 3 wrong PINs; NG backs off exponentially, persisted so a restart does not reset it."""
    def setUp(self):
        super().setUp()
        sec.set_app_lock(True,PIN);sec.clear_session_pin();common_db.set_locked(True)
    def test_three_free_attempts_then_delay(self):
        t=1000.0
        for i in range(3):self.assertFalse(sec.unlock("0000",now=t)[0])
        self.assertEqual(sec.LOCKOUT_BASE_SECONDS,sec.lockout_remaining(now=t))
        ok,msg=sec.unlock(PIN,now=t+1)
        self.assertFalse(ok);self.assertIn("Try again",msg)
        self.assertTrue(sec.unlock(PIN,now=t+sec.LOCKOUT_BASE_SECONDS+1)[0])
        self.assertEqual(0,sec.get_security_settings()["failed_attempts"])
    def test_delay_doubles_and_is_capped(self):
        self.assertEqual([0,0,30,60,120],[sec.lockout_delay(n) for n in (1,2,3,4,5)])
        self.assertEqual(sec.LOCKOUT_MAX_SECONDS,sec.lockout_delay(50))
    def test_counter_survives_restart(self):
        t=1000.0
        for i in range(3):sec.unlock("0000",now=t)
        raw=json.load(open(self.settings))["security"]
        self.assertEqual(3,raw["failed_attempts"]);self.assertGreater(raw["lockout_until"],t)
        sec.clear_session_pin()
        self.assertFalse(sec.unlock(PIN,now=t+5)[0])
    def test_clock_going_back_caps_the_wait(self):
        sec.save_security_settings({"failed_attempts":9,"lockout_until":10**10})
        self.assertEqual(sec.LOCKOUT_MAX_SECONDS,sec.lockout_remaining(now=1000.0))
        self.assertTrue(sec.unlock(PIN,now=1000.0+sec.LOCKOUT_MAX_SECONDS+1)[0])
    def test_reset_pin_clears_the_counter(self):
        sec.save_security_settings({"failed_attempts":5,"lockout_until":10**10})
        self.assertTrue(sec.reset_pin()[0])
        self.assertEqual(0,sec.get_security_settings()["failed_attempts"])
@unittest.skipUnless(_NEED,"sqlcipher3/cryptography not installed")
class EncryptionPinTests(SecurityCase):
    """S20: the dialog's PIN must be the one checked, never this session's unlock."""
    def test_enable_requires_the_typed_pin(self):
        self.make_db(1)
        sec.set_app_lock(True,EPIN)
        self.assertEqual((False,"Wrong PIN."),sec.set_encryption(True,pin="999999"))
        self.assertEqual((False,"Wrong PIN."),sec.set_encryption(True,pin=""))
        self.assertFalse(sec.get_security_settings()["enc_enabled"])
        self.assertTrue(sec.set_encryption(True,pin=EPIN)[0])
    def test_disable_requires_the_typed_pin(self):
        self.make_db(1)
        sec.set_encryption(True,new_pin=EPIN)
        self.assertEqual((False,"Wrong PIN."),sec.set_encryption(False,pin="999999"))
        self.assertTrue(sec.get_security_settings()["enc_enabled"])
        self.assertTrue(sec.set_encryption(False,pin=EPIN)[0])
class SettingsLockTests(SecurityCase):
    def test_parallel_read_modify_write_keeps_every_key(self):
        p=self.settings
        def worker(i):settings_lock.update_json(p,lambda d:d.__setitem__(f"k{i}",i))
        ts=[threading.Thread(target=worker,args=(i,)) for i in range(40)]
        [t.start() for t in ts];[t.join() for t in ts]
        d=json.load(open(p))
        self.assertEqual(set(f"k{i}" for i in range(40)),set(d))
    def test_security_and_other_writers_do_not_drop_keys(self):
        from Cores.Services import settings_service
        with mock.patch.object(settings_service,"_settings_path",lambda:self.settings):
            def a(i):sec.save_security_settings({f"s{i}":i})
            def b(i):settings_service.set_focus_mode_enabled(i%2==0)
            ts=[threading.Thread(target=f,args=(i,)) for i in range(20) for f in (a,b)]
            [t.start() for t in ts];[t.join() for t in ts]
        d=json.load(open(self.settings))
        self.assertIn("focus_mode",d)
        self.assertEqual(set(f"s{i}" for i in range(20)),set(d["security"]))
    def test_modules_share_one_lock(self):
        from Cores import recycle_bin
        from Cores.Services import terminal_service
        self.assertIs(settings_lock.SETTINGS_LOCK,recycle_bin._settings_lock)
        self.assertIs(settings_lock.SETTINGS_LOCK,terminal_service._settings_lock)
class AuditExpiryTests(SecurityCase):
    def test_amount_validation(self):
        for good,want in ((1,1),(999,999),("12",12),(" 7 ",7),(5.0,5)):
            self.assertEqual(want,sec.parse_audit_expiry_amount(good))
        for bad in (0,1000,-1,1.5,True,"abc","","1e2","1000",None,[1]):
            with self.assertRaises(ValueError,msg=repr(bad)):sec.parse_audit_expiry_amount(bad)
        for bad in ("weeks","",None):
            with self.assertRaises(ValueError):sec.parse_audit_expiry_unit(bad)
        self.assertEqual("months",sec.parse_audit_expiry_unit("Months"))
    def test_calendar_math(self):
        utc=timezone.utc
        self.assertEqual(datetime(2026,2,28,tzinfo=utc),sec.audit_cutoff(1,"months",datetime(2026,3,31,tzinfo=utc)))
        self.assertEqual(datetime(2024,2,29,tzinfo=utc),sec.audit_cutoff(1,"months",datetime(2024,3,31,tzinfo=utc)))
        self.assertEqual(datetime(2025,12,15,tzinfo=utc),sec.audit_cutoff(3,"months",datetime(2026,3,15,tzinfo=utc)))
        self.assertEqual(datetime(2023,2,28,tzinfo=utc),sec.audit_cutoff(1,"years",datetime(2024,2,29,tzinfo=utc)))
        self.assertEqual(datetime(2026,11,13,12,tzinfo=utc),sec.audit_cutoff(10,"days",datetime(2026,11,23,12,tzinfo=utc)))
        self.assertEqual(datetime(1027,11,23,tzinfo=utc),sec.audit_cutoff(999,"years",datetime(2026,11,23,tzinfo=utc)))
        self.assertEqual(datetime(1943,8,23,tzinfo=utc),sec.audit_cutoff(999,"months",datetime(2026,11,23,tzinfo=utc)))
    def write_log(self,entries):
        with open(sec._audit_path(),"w",encoding="utf-8") as f:
            for e in entries:f.write((e if isinstance(e,str) else json.dumps(e))+"\n")
    def test_prune_removes_old_keeps_new_and_records_itself(self):
        now=datetime.now(timezone.utc)
        self.write_log([{"ts":(now-timedelta(days=400)).isoformat(),"event":"old1"},{"ts":(now-timedelta(days=40)).isoformat(),"event":"old2"},{"ts":(now-timedelta(days=5)).isoformat(),"event":"new"},"not json"])
        res=sec.set_audit_expiry(True,1,"months")
        self.assertEqual(2,res["pruned"])
        events=[e["event"] for e in sec.list_audit_events()]
        self.assertNotIn("old1",events);self.assertNotIn("old2",events);self.assertIn("new",events)
        pruned=[e for e in sec.list_audit_events() if e["event"]=="audit_log_pruned"]
        self.assertEqual(1,len(pruned));self.assertIn("2 entries",pruned[0]["detail"])
        self.assertIn("not json",open(sec._audit_path()).read())
    def test_disabled_never_prunes(self):
        now=datetime.now(timezone.utc)
        self.write_log([{"ts":(now-timedelta(days=4000)).isoformat(),"event":"ancient"}])
        self.assertEqual(0,sec.set_audit_expiry(False,1,"days")["pruned"])
        self.assertEqual(0,sec.prune_audit_log())
        self.assertIn("ancient",[e["event"] for e in sec.list_audit_events()])
    def test_settings_persist_and_invalid_is_rejected_when_enabled(self):
        sec.set_audit_expiry(True,6,"months")
        self.assertEqual({"enabled":True,"amount":6,"unit":"months"},sec.get_audit_expiry())
        with self.assertRaises(ValueError):sec.set_audit_expiry(True,1000,"days")
        with self.assertRaises(ValueError):sec.set_audit_expiry(True,5,"weeks")
        self.assertEqual({"enabled":True,"amount":6,"unit":"months"},sec.get_audit_expiry())
        sec.set_audit_expiry(False,"",None)
        self.assertEqual({"enabled":False,"amount":6,"unit":"months"},sec.get_audit_expiry())
class SchedulerTests(unittest.TestCase):
    def setUp(self):
        import LOYA_Note;self.app=LOYA_Note
    def test_update_check_due(self):
        now=datetime(2026,11,23,12,tzinfo=timezone.utc);due=self.app._update_check_due
        self.assertFalse(due({"auto_enabled":False},"",now))
        self.assertTrue(due({"auto_enabled":True,"check_interval_hours":24},"",now))
        self.assertFalse(due({"auto_enabled":True,"check_interval_hours":24},(now-timedelta(hours=2)).isoformat(),now))
        self.assertTrue(due({"auto_enabled":True,"check_interval_hours":24},(now-timedelta(hours=25)).isoformat(),now))
        self.assertTrue(due({"auto_enabled":True,"check_interval_hours":6},(now-timedelta(hours=6)).isoformat(),now))
    def test_check_runs_only_when_due_and_never_raises(self):
        svc=mock.Mock()
        svc.get_update_settings.return_value={"auto_enabled":True,"check_interval_hours":24,"last_checked":""}
        svc.get_update_state.return_value={"last_checked":""}
        svc.check_for_updates.side_effect=OSError("offline")
        with mock.patch.object(self.app,"_update_svc",svc):
            self.assertIsNone(self.app._maybe_check_updates())
            svc.check_for_updates.assert_called_once()
            svc.get_update_settings.return_value={"auto_enabled":False}
            svc.check_for_updates.reset_mock()
            self.app._maybe_check_updates()
            svc.check_for_updates.assert_not_called()
    def test_auto_backup_skipped_while_locked(self):
        fn=mock.Mock(return_value=(False,"Recent backup exists."))
        with mock.patch.object(self.app,"_auto_backup_if_needed",fn):
            common_db.set_locked(True)
            try:self.assertIsNone(self.app._scheduled_auto_backup())
            finally:common_db.set_locked(False)
            fn.assert_not_called()
            self.app._scheduled_auto_backup()
            fn.assert_called_once()
if __name__=="__main__":unittest.main()
