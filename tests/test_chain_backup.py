"""Backups keep the chains and their history: a data backup (plain .zip and encrypted .loyabak) and Export All carry the
ChainGraphs / ChainRuns / ChainRunLogs rows as a consistent DB snapshot, a replace restore brings them back exactly (chains
unreviewed), a merge restore adds the backup's missing chains and runs, and every other user table (reports, CVE, AppDocs,
Secrets, ...) and settings.json section (CVE settings, AI roles) round-trips too."""
import json,os,shutil,sys,tempfile,unittest,zipfile
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from _isolate import IsolatedData
from Cores import common_db,crypto_store,db_driver
from Cores.Update import backup_restore
from Cores.Services import chain_history as hist
from Cores.Services import flow_service as flows
from Cores.Services import flow_store as store
from Cores.Services import playbooks_service as chains
from Cores.Services import security_service as sec
from test_chain_history import GRAPH,status,add_log
EPIN="482193"
FAST_KDF={"name":"argon2id","m_kib":8192,"t":1,"p":1} if crypto_store.has_argon2() else {"name":"scrypt","n":2**14,"r":8,"p":1}
SETTINGS={"cve":{"nvd_api_key_set":True,"watchlist":["openssl"],"feed":{"kev":True}},"ai":{"permissions":{"notes_read":"allow","chain_history_delete":"deny"}},"extensions":{"flows":{"script_isolation":"sandboxed"}}}
def table_counts():
    with common_db.connection() as con:
        return {t:n for t,n in db_driver.row_counts(con).items() if n}
class Base(unittest.TestCase):
    def setUp(self):
        self._kdf=sec._KDF;sec._KDF=FAST_KDF
        self.out=tempfile.mkdtemp(prefix="loya_chain_bk_")
        self.iso=None
        self.fresh()
    def fresh(self):
        if self.iso is not None:
            sec.clear_session_pin();self.iso.stop()
        self.iso=IsolatedData();self.dir=self.iso.start()
        sec.clear_session_pin();common_db.set_locked(False)
    def tearDown(self):
        sec.clear_session_pin();common_db.set_locked(False)
        sec._KDF=self._kdf
        self.iso.stop()
        shutil.rmtree(self.out,ignore_errors=True)
    def seed(self):
        self.a=flows.create("Recon",GRAPH,"recon")["playbook_id"]
        flows.mark_reviewed(self.a)
        self.linear=chains.create_playbook("Linear one","linear")
        store.save_run(status("runA1",self.a));add_log("runA1")
        store.save_run(status("runA2",self.a,state="failed",started="2026-11-21T09:00:00+00:00",ended="2026-11-21T09:01:00+00:00"))
        with open(os.path.join(self.dir,"settings.json"),"w",encoding="utf-8") as fh:json.dump(SETTINGS,fh)
        with common_db.connection() as con:
            common_db.ensure_schema(con)
            con.execute("INSERT INTO Reports(uid,title,created_at) VALUES('r-1','ACME external','2026-11-20')")
            con.execute("INSERT INTO ReportFindings(report_id,uid,title,severity) VALUES(1,'f-1','SQLi','high')")
            con.execute("INSERT INTO CveRecords(cve_id,data,fetched_at,is_read) VALUES('CVE-2024-3400','{}','2026-11-20',1)")
            common_db._create_storage_tables(con.cursor())
            con.execute("INSERT INTO AppDocs(name,data,mtime,size) VALUES('notes_meta.json','{}',1,2)")
    def assert_chains_back(self,reviewed=False):
        got=flows.get(self.a)
        self.assertEqual(["n1","n2","n3"],[n["id"] for n in got["graph"]["nodes"]])
        self.assertFalse(got["derived"])
        self.assertEqual(reviewed,got["ai_reviewed"],"a restored chain must be reviewed again before it runs")
        self.assertEqual({"Recon","Linear one"},{c["name"] for c in flows.list_flows()})
        page=hist.list_runs({})
        self.assertEqual(["runA2","runA1"],[r["run_id"] for r in page["items"]])
        self.assertEqual(self.a,page["items"][0]["playbook_id"])
        self.assertEqual(["info","warn","error"],[e["level"] for e in flows.run_log("runA1")["entries"]])
        self.assertEqual("Ping it",hist.run_detail("runA1")["timeline"][1]["title"])
class PlainBackupTest(Base):
    def test_backup_restore_round_trip_keeps_chains_history_and_everything_else(self):
        self.seed()
        before=table_counts()
        for t in ("ChainGraphs","ChainRuns","ChainRunLogs","Playbooks","Reports","ReportFindings","CveRecords","AppDocs"):self.assertIn(t,before)
        out=backup_restore.create_data_backup(out_dir=self.out)
        with zipfile.ZipFile(out) as z:
            names=z.namelist()
            self.assertIn("Data/Note_LOYA_V1.db",names)
            self.assertFalse([n for n in names if n.endswith(("-journal","-wal","-shm"))],"the DB goes in as one consistent snapshot")
            self.assertFalse([n for n in names if "/.loya_backup_" in n or n.startswith("Data/cve_index")])
        self.fresh()
        ok,msg=backup_restore.restore_data_backup(out,mode="replace")
        self.assertTrue(ok,msg)
        self.assertEqual(before,table_counts(),"every user table comes back row for row")
        self.assert_chains_back()
        with open(os.path.join(self.dir,"settings.json"),encoding="utf-8") as fh:back=json.load(fh)
        for key in ("cve","ai","extensions"):self.assertEqual(SETTINGS[key],back[key])
    def test_a_backup_never_holds_older_backups(self):
        self.seed()
        inside=os.path.join(self.dir,"Backups")
        first=backup_restore.create_data_backup(out_dir=inside)
        os.makedirs(os.path.join(self.dir,"cve_index"),exist_ok=True)
        with open(os.path.join(self.dir,"cve_index","big.db"),"wb") as fh:fh.write(b"x"*1000)
        second=backup_restore.create_data_backup(out_dir=inside)
        with zipfile.ZipFile(second) as z:names=z.namelist()
        self.assertFalse([n for n in names if n.startswith("Data/Backups/")],names)
        self.assertFalse([n for n in names if n.startswith("Data/cve_index/")])
        self.assertTrue(os.path.isfile(first))
    def test_merge_restore_adds_the_backups_missing_chains_and_runs(self):
        self.seed()
        out=backup_restore.create_data_backup(out_dir=self.out)
        self.fresh()
        mine=flows.create("Recon",GRAPH,"mine")["playbook_id"]   # same name as the backup's chain: kept, not duplicated
        other=flows.create("Web sweep",GRAPH,"web")["playbook_id"]
        store.save_run(status("runMine",other,name="Web sweep",started="2026-11-23T08:00:00+00:00",ended="2026-11-23T08:00:01+00:00"))
        store.save_run(status("runA2",other,name="Web sweep",started="2026-11-23T09:00:00+00:00",ended="2026-11-23T09:00:01+00:00"))   # run_id collision: the live one stays
        ok,msg=backup_restore.restore_data_backup(out,mode="merge")
        self.assertTrue(ok,msg)
        self.assertIn("chain run(s) added",msg)
        names=[c["name"] for c in flows.list_flows()]
        self.assertEqual(1,names.count("Recon"))
        self.assertIn("Web sweep",names)
        page=hist.list_runs({})
        self.assertEqual({"runMine","runA2","runA1"},{r["run_id"] for r in page["items"]})
        self.assertEqual(other,next(r for r in page["items"] if r["run_id"]=="runA2")["playbook_id"])
        a1=next(r for r in page["items"] if r["run_id"]=="runA1")
        self.assertEqual(mine,a1["playbook_id"],"a backup run attaches to the same-named chain")
        self.assertEqual(3,len(flows.run_log("runA1")["entries"]))
        self.assertFalse(flows.get(mine)["ai_reviewed"])
    def test_restore_copies_the_db_before_its_own_sidecars(self):
        self.seed()
        out=os.path.join(self.out,"old-style.zip")
        with zipfile.ZipFile(out,"w") as z:
            z.writestr("Data/Note_LOYA_V1.db-journal",b"")   # an old raw-copy backup could hold one; it must survive the DB copy
            z.write(common_db.db_path(),"Data/Note_LOYA_V1.db")
        self.fresh()
        order=[]
        real=backup_restore.shutil.copy2
        backup_restore.shutil.copy2=lambda a,b:(order.append(os.path.basename(b)),real(a,b))[1]
        try:ok,msg=backup_restore.restore_data_backup(out,mode="replace")
        finally:backup_restore.shutil.copy2=real
        self.assertTrue(ok,msg)
        self.assertLess(order.index("Note_LOYA_V1.db"),order.index("Note_LOYA_V1.db-journal"))
    def test_export_all_holds_a_consistent_db_with_the_chain_tables(self):
        from Cores.Services import settings_service
        from Cores.Update import health_check
        self.seed()
        os.makedirs(os.path.join(self.dir,"cve_index"),exist_ok=True)
        with open(os.path.join(self.dir,"cve_index","big.db"),"wb") as fh:fh.write(b"x")
        real=health_check.data_dir
        health_check.data_dir=lambda:self.dir
        try:
            out=os.path.join(self.out,"all.zip")
            settings_service.export_all_zip(out)
        finally:
            health_check.data_dir=real
        with zipfile.ZipFile(out) as z:
            names=z.namelist()
            self.assertFalse([n for n in names if n.startswith("Data/cve_index/") or "/.loya_backup_" in n or n.startswith("Data/Backups/")])
            db=os.path.join(self.out,"x.db")
            with open(db,"wb") as fh:fh.write(z.read("Data/Note_LOYA_V1.db"))
        con=db_driver.connect(db)
        try:counts=db_driver.row_counts(con)
        finally:con.close()
        self.assertEqual((1,2,3),(counts["ChainGraphs"],counts["ChainRuns"],counts["ChainRunLogs"]))
class ConnectionTokensStayOutTest(Base):
    """Data/external_agents/connections/*.json hold the bearer tokens a connected Claude Code / Codex CLI uses to call
    LOYA NG's tools. They must never end up in a backup or an Export All zip."""
    def _tokens(self):
        d=os.path.join(self.dir,"external_agents","connections");os.makedirs(d,exist_ok=True)
        for tool in ("claude_code","codex_cli"):
            with open(os.path.join(d,tool+".json"),"w",encoding="utf-8") as fh:fh.write('{"token":"SECRET-TEST-TOKEN"}')
        os.makedirs(os.path.join(self.dir,"external_agents","other"),exist_ok=True)
        with open(os.path.join(self.dir,"external_agents","other","keep.json"),"w") as fh:fh.write("{}")
    def _check(self,out):
        with zipfile.ZipFile(out) as z:
            names=z.namelist()
            self.assertFalse([n for n in names if "external_agents/connections" in n.replace("\\","/")],names)
            self.assertFalse([n for n in names if b"SECRET-TEST-TOKEN" in z.read(n)])
            self.assertTrue([n for n in names if n.endswith("external_agents/other/keep.json")],"only the tokens folder is left out")
    def test_plain_backup_leaves_the_tokens_out(self):
        self._tokens()
        self._check(backup_restore.create_data_backup(out_dir=self.out))
    def test_export_all_leaves_the_tokens_out(self):
        from Cores.Services import settings_service
        from Cores.Update import health_check
        self._tokens()
        real=health_check.data_dir
        health_check.data_dir=lambda:self.dir
        try:
            out=os.path.join(self.out,"all.zip")
            settings_service.export_all_zip(out)
        finally:
            health_check.data_dir=real
        self._check(out)
@unittest.skipUnless(db_driver.has_sqlcipher(),"sqlcipher3 not installed")
class EncryptedBackupTest(Base):
    def test_loyabak_round_trip_keeps_chains_history_appdocs_and_secrets(self):
        from Cores import secret_store
        self.seed()
        ok,msg=sec.set_encryption(True,new_pin=EPIN)
        self.assertTrue(ok,msg)
        self.assertTrue(secret_store.put("cve:nvd","TEST-KEY-123"))
        before=table_counts()
        for t in ("ChainGraphs","ChainRuns","ChainRunLogs","AppDocs","Secrets","Reports"):self.assertIn(t,before)
        out=backup_restore.create_data_backup(out_dir=self.out)
        self.assertTrue(out.endswith(".loyabak"))
        hist.clear_runs();flows.revert_linear(self.a)
        with common_db.connection() as con:
            con.execute("DELETE FROM Secrets");con.execute("DELETE FROM AppDocs")
        ok,msg=backup_restore.restore_data_backup(out,mode="replace")
        self.assertTrue(ok,msg)
        after=table_counts()
        for t,n in before.items():
            if t!="AuditEvents":self.assertEqual(n,after.get(t),t)
        self.assert_chains_back()
        self.assertEqual("TEST-KEY-123",secret_store.get("cve:nvd"))
    def test_the_pre_encryption_backup_holds_the_chain_tables(self):
        from Cores import loyabak
        self.seed()
        ok,msg=sec.set_encryption(True,new_pin=EPIN)
        self.assertTrue(ok,msg)
        made=[os.path.join(r,n) for r,_d,files in os.walk(self.dir) for n in files if n.startswith("pre-encryption") and n.endswith(loyabak.EXT)]
        self.assertEqual(1,len(made),"storage_migration writes one verified backup before it encrypts")
        zp=os.path.join(self.out,"pre.zip");loyabak.decrypt_to(made[0],zp,common_db.session_key())
        db=os.path.join(self.out,"pre.db")
        with zipfile.ZipFile(zp) as z,open(db,"wb") as fh:fh.write(z.read("Note_LOYA_V1.db"))
        con=db_driver.connect(db)
        try:counts=db_driver.row_counts(con)
        finally:con.close()
        self.assertEqual((1,2,3),(counts["ChainGraphs"],counts["ChainRuns"],counts["ChainRunLogs"]))
    def test_merge_restore_reads_an_encrypted_backup(self):
        self.seed()
        ok,msg=sec.set_encryption(True,new_pin=EPIN)
        self.assertTrue(ok,msg)
        out=backup_restore.create_data_backup(out_dir=self.out)
        hist.clear_runs()
        ok,msg=backup_restore.restore_data_backup(out,mode="merge")
        self.assertTrue(ok,msg)
        self.assertEqual({"runA1","runA2"},{r["run_id"] for r in hist.list_runs({})["items"]})
if __name__=="__main__":
    unittest.main()
