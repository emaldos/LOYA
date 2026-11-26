import json,os,sys,unittest,zipfile,io
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from _isolate import IsolatedData
from Cores import common_db,crypto_store,db_driver,loyabak
from Cores.Services import work_export as we
FAST_KDF={"name":"argon2id","m_kib":8192,"t":1,"p":1} if crypto_store.has_argon2() else {"name":"scrypt","n":2**14,"r":8,"p":1}
EPIN="482193"
# Planted markers: none of them may appear anywhere in the export.
SECRETS=("MARK-SECRETS-ROW","MARK-AUDIT-ROW","MARK-CONN-TOKEN","MARK-SETTINGS-APIKEY","MARK-AUDIT-JSONL","MARK-DEPS-STATE",
         "MARK-SEARCH-INDEX","MARK-TERMINAL-SESSION","MARK-KEYFILE","MARK-RUN-VAR","MARK-PID","MARK-RECYCLE","MARK-CMDRUN",
         "MARK-TERMJOB","MARK-AGENT-USAGE","MARK-DRAFT","MARK-CVE-KEY","MARK-SHELL-PATH")
CONTENT=("MARK-NOTE-BODY","MARK-NOTE-VERSION","MARK-CMD","MARK-CMDNOTE","MARK-CHAIN-GRAPH","MARK-RUN-STDOUT","MARK-REPORT",
         "MARK-FINDING","MARK-TEMPLATE","MARK-LIBRARY","MARK-EVIDENCE","MARK-TARGET-PW","MARK-PROFILE-TARGET","MARK-QUICKSPACE",
         "MARK-ATTACHMENT","MARK-CHAIN-HTML","MARK-TAGCOLOR")
def seed(d,pin_data=True):
    with common_db.connection() as con:
        common_db.ensure_schema(con);common_db._create_storage_tables(con.cursor())
        x=con.execute
        x("INSERT INTO Notes(id,note_name,group_name,tags,content) VALUES(7,'Recon','G','web','<p>MARK-NOTE-BODY</p><img src=\"Attachments/7/a.png\">')")
        x("INSERT INTO NotesHistory(note_id,note_name,content,action,action_at) VALUES(7,'Recon','MARK-NOTE-VERSION','edit','2026-01-01')")
        x("INSERT INTO Commands(id,note_id,note_name,cmd_note_title,category,command) VALUES(3,7,'Recon','t','web','nmap MARK-CMD')")
        x("INSERT INTO CommandsNotes(id,note_name,category,command) VALUES(4,'Tools','web','curl MARK-CMDNOTE')")
        x("INSERT INTO Playbooks(id,name) VALUES(1,'Flow')")
        x("INSERT INTO ChainGraphs(playbook_id,graph) VALUES(1,?)",(json.dumps({"nodes":[{"id":"n1","title":"MARK-CHAIN-GRAPH"}],"edges":[]}),))
        status={"vars":{"pw":"MARK-RUN-VAR"},"approval":{"x":"MARK-RUN-VAR"},"nodes":{"n1":{"state":"done","output":{"stdout":"MARK-RUN-STDOUT"},"job_keys":["MARK-RUN-VAR"]}},"events":[]}
        x("INSERT INTO ChainRuns(run_id,playbook_id,chain_name,mode,state,started_at,ended_at,data) VALUES('r1',1,'Flow','run','done','2026-01-01T00:00:00+00:00','2026-01-01T00:01:00+00:00',?)",(json.dumps(status),))
        x("INSERT INTO ChainRunLogs(run_id,seq,ts,level,kind,text) VALUES('r1',1,'2026-01-01','info','info','log line')")
        x("INSERT INTO Reports(id,uid,title) VALUES(1,'u1','MARK-REPORT')")
        x("INSERT INTO ReportFindings(report_id,uid,title) VALUES(1,'f1','MARK-FINDING')")
        x("INSERT INTO ReportTemplates(uid,name) VALUES('t1','MARK-TEMPLATE')")
        x("INSERT INTO FindingLibrary(uid,title) VALUES('l1','MARK-LIBRARY')")
        x("INSERT INTO ReportEvidence(uid,kind,title,created_at) VALUES('e1','text','MARK-EVIDENCE','2026')")
        x("INSERT INTO Secrets(name,value) VALUES('ext_agent:claude','MARK-SECRETS-ROW')")
        x("INSERT INTO AuditEvents(ts,event,detail) VALUES('2026','x','MARK-AUDIT-ROW')")
        x("INSERT INTO RecycleBin(entity_type,payload,deleted_at,expires_at) VALUES('note','MARK-RECYCLE','a','b')")
        x("INSERT INTO CommandRuns(command_id,text,target_snapshot,ran_at) VALUES(3,'x','MARK-CMDRUN','a')")
        x("INSERT INTO TerminalJobs(job_key,command,state,started_at) VALUES('j','MARK-TERMJOB','done','a')")
    def w(rel,obj,raw=False):
        p=os.path.join(d,*rel.split("/"));os.makedirs(os.path.dirname(p),exist_ok=True)
        data=obj if isinstance(obj,bytes) else (obj if raw else json.dumps(obj)).encode("utf-8")
        with open(p,"wb") as f:f.write(data)
    w("profiles.json",[{"id":"default","name":"Default","active":True},{"id":"abc123","name":"Client"}])
    w("Targets.json",[{"name":"web01","password":"MARK-TARGET-PW"}])
    w("target_values.json",{"ip":"10.0.0.1"})
    w("Profiles/abc123/Targets.json",[{"name":"MARK-PROFILE-TARGET"}])
    w("QuicSpace.json",{"items":[{"text":"MARK-QUICKSPACE"}]})
    w("tag_colors.json",{"web":"MARK-TAGCOLOR"})
    w("notes_meta.json",{"pinned":[7]})
    w("Attachments/7/a.png",b"MARK-ATTACHMENT")
    w("Attachments/_pending/p.png",b"MARK-DRAFT")
    w("chain/flow.html","<html>MARK-CHAIN-HTML</html>",raw=True)
    w("external_agents/connections/claude.json",{"token":"MARK-CONN-TOKEN"})
    w("external_agents/usage.json",{"x":"MARK-AGENT-USAGE"})
    w("settings.json",{"appearance":{"theme":"dark","font_size":14},"extensions":{"ai_permissions":{"notes_read":"allow"},"api_key":"MARK-SETTINGS-APIKEY","shell_path":"MARK-SHELL-PATH"},
                       "cve":{"retention_days":30,"key_hint":"MARK-CVE-KEY"},**({"security":{"pin_hash":"MARK-KEYFILE"}} if pin_data else {}),"mini_window":{"favorites":["Commands:3"],"x":5}})
    w("security_audit.jsonl","MARK-AUDIT-JSONL\n",raw=True)
    w("deps_state.json",{"x":"MARK-DEPS-STATE"})
    w("search_index/index.json",{"x":"MARK-SEARCH-INDEX"})
    w("terminal_sessions.json",{"x":"MARK-TERMINAL-SESSION"})
    w("note_draft_recovery.json",{"x":"MARK-DRAFT"})
    if pin_data:w("Note_LOYA_V1.key","MARK-KEYFILE",raw=True)
    w("loya.pid","MARK-PID",raw=True)
def all_bytes(z):
    out=b""
    for n in z.namelist():
        out+=n.encode()+b"\n"+z.read(n)
    return out
def db_bytes_from(z):
    """content.db rows as text (SQLite stores small text unencoded, but scan the decoded rows too)."""
    import tempfile
    t=tempfile.mkdtemp();p=os.path.join(t,"c.db")
    with open(p,"wb") as f:f.write(z.read("content.db"))
    con=db_driver.connect(p);txt=[]
    try:
        for (name,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            txt.append(name)
            for r in con.execute('SELECT * FROM "%s"'%name):txt.append(repr(r))
        tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        ver=con.execute("PRAGMA user_version").fetchone()[0]
    finally:con.close()
    return "\n".join(txt),tables,ver
class WorkExportTests(unittest.TestCase):
    def setUp(self):
        self.iso=IsolatedData();self.dir=self.iso.start();common_db.set_locked(False)
        self._kdf=we._KDF;we._KDF=FAST_KDF
        seed(self.dir);self.out=os.path.join(self.dir,"..",os.path.basename(self.dir)+"_out")
        os.makedirs(self.out,exist_ok=True)
    def tearDown(self):
        we._KDF=self._kdf;self.iso.stop()
        import shutil;shutil.rmtree(self.out,ignore_errors=True)
    def export(self,**kw):
        p=os.path.join(self.out,"work.zip");res=we.export_work_zip(p,**kw);return p,res
    def test_content_present_and_secrets_absent(self):
        p,res=self.export(include_settings=True)
        with zipfile.ZipFile(p) as z:
            blob=all_bytes(z);rows,tables,ver=db_bytes_from(z);names=z.namelist();man=json.loads(z.read("manifest.json"))
        hay=blob.decode("utf-8","ignore")+rows
        for m in CONTENT:self.assertIn(m,hay,m)
        for m in SECRETS:self.assertNotIn(m,hay,m)
        self.assertFalse(tables&{"Secrets","AuditEvents","AppDocs","RecycleBin","CommandRuns","TerminalJobs","CveRecords"})
        self.assertEqual(ver,common_db.DB_SCHEMA_VERSION)
        self.assertEqual(man["format"],"loya-work-export");self.assertEqual(man["format_version"],2)
        self.assertIn("docs/Profiles/abc123/Targets.json",names);self.assertIn("files/Attachments/7/a.png",names)
        self.assertFalse(any(n.startswith(("Data/","external_agents","search_index")) for n in names))
        c=man["counts"]
        for k,n in (("notes",1),("note_versions",1),("commands",1),("command_notes",1),("chains",1),("chain_runs",1),("reports",1),
                    ("report_templates",1),("findings_library",1),("evidence",1),("attachments",1),("chain_files",1),("target_profiles",2),
                    ("targets",2),("quick_run",1),("settings",1)):self.assertEqual(c[k],n,k)
        self.assertEqual(res["counts"],c)
        s=json.loads(zipfile.ZipFile(p).read("settings.json"))
        self.assertEqual(s["appearance"]["theme"],"dark");self.assertEqual(s["extensions"],{"ai_permissions":{"notes_read":"allow"}})
        self.assertNotIn("security",s);self.assertNotIn("mini_window",s)
        qr=json.loads(zipfile.ZipFile(p).read("quick_run.json"))
        self.assertEqual(qr["favorites"][0]["command"],"nmap MARK-CMD")
    def test_options_off(self):
        p,res=self.export(include_run_history=False)
        with zipfile.ZipFile(p) as z:
            names=z.namelist();rows,tables,_=db_bytes_from(z);man=json.loads(z.read("manifest.json"))
        self.assertNotIn("settings.json",names);self.assertFalse(tables&{"ChainRuns","ChainRunLogs"})
        self.assertEqual(man["included"],{"settings":False,"run_history":False,"ai_chats":False})
        self.assertNotIn("MARK-RUN-STDOUT",rows)
    def test_run_vars_stripped(self):
        p,_=self.export()
        with zipfile.ZipFile(p) as z:rows,_,_=db_bytes_from(z)
        self.assertIn("MARK-RUN-STDOUT",rows);self.assertNotIn("MARK-RUN-VAR",rows)
    def test_ai_chats_opt_in(self):
        os.makedirs(os.path.join(self.dir,"ai_sessions"))
        with open(os.path.join(self.dir,"ai_sessions","s1.json"),"w") as f:json.dump({"m":"MARK-CHAT"},f)
        p,_=self.export()
        self.assertNotIn(b"MARK-CHAT",all_bytes(zipfile.ZipFile(p)))
        p,res=self.export(include_ai_chats=True)
        self.assertIn("ai_sessions/s1.json",zipfile.ZipFile(p).namelist());self.assertEqual(res["counts"]["ai_chats"],1)
    def test_password_round_trip(self):
        p=os.path.join(self.out,"work.loyawork")
        res=we.export_work_zip(p,password="correct horse battery")
        self.assertTrue(res["protected"]);self.assertTrue(loyabak.is_loyabak(p))
        with open(p,"rb") as f:raw=f.read()
        for m in CONTENT+SECRETS:self.assertNotIn(m.encode(),raw)
        h=loyabak.read_header(p);self.assertEqual((h["kind"],h["protect"]),("work","password"))
        with self.assertRaises(crypto_store.WrongPin):loyabak.unwrap(p,"wrong password!!")
        dek=loyabak.unwrap(p,"correct horse battery");zp=os.path.join(self.out,"dec.zip")
        loyabak.decrypt_to(p,zp,dek);dek.wipe()
        with zipfile.ZipFile(zp) as z:self.assertIn("MARK-NOTE-BODY",z.read("content.db").decode("utf-8","ignore")+db_bytes_from(z)[0])
    def test_short_password_refused(self):
        with self.assertRaises(ValueError):we.export_work_zip(os.path.join(self.out,"x.loyawork"),password="abc")
    def test_classification_is_an_allowlist(self):
        self.assertIsNone(we.classify("something_new.json"))
        self.assertEqual(we.classify("external_agents/connections/x.json")["class"],we.MACHINE)
        self.assertEqual(we.classify("Profiles/abc/Targets.json")["class"],we.CONTENT)
        for t in ("Secrets","AuditEvents","AppDocs","CveRecords"):self.assertNotIn(t,we.CONTENT_TABLES)
@unittest.skipUnless(db_driver.has_sqlcipher(),"sqlcipher3 not installed")
class EncryptedAtRestExportTests(unittest.TestCase):
    def setUp(self):
        from Cores.Services import security_service as sec
        self.sec=sec
        self.iso=IsolatedData();self.dir=self.iso.start();common_db.set_locked(False)
        self._kdf=sec._KDF;sec._KDF=FAST_KDF;self._wkdf=we._KDF;we._KDF=FAST_KDF;sec.clear_session_pin()
        seed(self.dir,pin_data=False)
        ok,msg=sec.set_encryption(True,new_pin=EPIN);self.assertTrue(ok,msg)
        self.out=os.path.join(self.dir,"..",os.path.basename(self.dir)+"_out");os.makedirs(self.out,exist_ok=True)
    def tearDown(self):
        self.sec.clear_session_pin();common_db.set_locked(False);self.sec._KDF=self._kdf;we._KDF=self._wkdf;self.iso.stop()
        import shutil;shutil.rmtree(self.out,ignore_errors=True)
    def test_plain_export_needs_pin_and_is_readable(self):
        self.assertTrue(common_db.encryption_configured());self.assertFalse(os.path.isfile(os.path.join(self.dir,"Targets.json")))
        with open(os.path.join(self.dir,"Attachments","7","a.png"),"rb") as f:self.assertTrue(f.read().startswith(crypto_store.MAGIC))
        ct=crypto_store.load_keyfile(common_db.key_path())["wrap"]["ct"]
        p=os.path.join(self.out,"w.zip")
        with self.assertRaises(ValueError):we.export_work_zip(p)
        with self.assertRaises(ValueError):we.export_work_zip(p,pin="000000")
        we.export_work_zip(p,pin=EPIN)
        with zipfile.ZipFile(p) as z:
            hay=all_bytes(z).decode("utf-8","ignore")+db_bytes_from(z)[0]
        for m in ("MARK-NOTE-BODY","MARK-TARGET-PW","MARK-ATTACHMENT","MARK-PROFILE-TARGET"):self.assertIn(m,hay,m)
        for m in SECRETS:self.assertNotIn(m,hay,m)
        self.assertNotIn(ct,hay)
    def test_password_export_needs_no_pin(self):
        p=os.path.join(self.out,"w.loyawork")
        we.export_work_zip(p,password="a long passphrase")
        self.assertTrue(loyabak.is_loyabak(p))
if __name__=="__main__":unittest.main()
