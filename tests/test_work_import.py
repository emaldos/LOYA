"""Import of "Export my work" files (Cores/Services/work_import.py): the work export format (plain zip and password-protected
.loyawork) and old full-Data zips. Only content arrives; secrets, tokens, the key file, settings, the audit log and other
machine files of an old zip are ignored; a merge renames or skips clashes; a replace keeps this install's own secrets,
audit log, settings and key file; imported chains are unreviewed and land without their run variables."""
import json,os,shutil,sys,tempfile,unittest,zipfile
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from _isolate import IsolatedData
from Cores import common_db,crypto_store,db_driver,doc_store,loyabak
from Cores.Services import chain_history as hist
from Cores.Services import flow_service as flows
from Cores.Services import flow_store as store
from Cores.Services import notes_service as ns
from Cores.Services import work_import as wi
from test_chain_history import GRAPH,status,add_log
FAST_KDF={"name":"argon2id","m_kib":8192,"t":1,"p":1} if crypto_store.has_argon2() else {"name":"scrypt","n":2**14,"r":8,"p":1}
SECRET="SECRET-MARKER-7f3a91"
TOKEN="TOKEN-MARKER-c0ffee"
AUDIT="AUDIT-MARKER-5512"
PNG=b"\x89PNG\r\n\x1a\nfake-image-bytes"
_CONTENT=set(wi._CONTENT_TABLES)
class _Install:
    """One isolated Data dir with notes_service attachments redirected into it."""
    def __init__(self):
        self.iso=IsolatedData();self.dir=self.iso.start()
        self._abs=ns._abs
        d=self.dir
        ns._abs=lambda *p:os.path.join(d,*(p[1:] if p and p[0]=="Data" else p))
        common_db.set_locked(False)
        with common_db.connection() as con:common_db.ensure_schema(con)
    def stop(self):
        ns._abs=self._abs;self.iso.stop()
def _seed_source(d):
    """Content of every kind in the current isolated install, plus planted secrets."""
    pid=flows.create("Recon",GRAPH,"recon")["playbook_id"];flows.mark_reviewed(pid)
    run=status("runA1",pid);run["vars"]={"password":SECRET};store.save_run(run);add_log("runA1")
    with common_db.connection() as con:
        con.execute("INSERT INTO Notes(id,note_name,group_name,tags,content,created_at,updated_at) VALUES(5,'Box notes','Recon','web',?, '2026-11-01','2026-11-02')",
                    ('<p>see</p><img src="file:///home/old/LOYA/Data/Attachments/5/abc123.png" data-attachment-id="abc123">',))
        con.execute("INSERT INTO NotesHistory(note_id,note_name,group_name,content,action,action_at) VALUES(5,'Box notes','Recon','<p>old</p>','update','2026-11-01')")
        con.execute("INSERT INTO Commands(id,note_id,note_name,cmd_note_title,category,sub_category,command) VALUES(9,5,'Box notes','t','Recon','Web','nmap -sV 10.0.0.1')")
        con.execute("INSERT INTO CommandsNotes(id,note_name,category,sub_category,command) VALUES(3,'Lib','Recon','Web','gobuster dir -u x')")
        con.execute("INSERT INTO Playbooks(id,name,caller) VALUES(50,'Linear one','linear')")
        con.execute("INSERT INTO PlaybookSteps(playbook_id,command_id,command_src,position) VALUES(50,3,'CommandsNotes',0)")
        con.execute("INSERT INTO Reports(id,uid,title,created_at) VALUES(1,'r-1','ACME external','2026-11-20')")
        con.execute("INSERT INTO ReportSections(report_id,uid,title,content) VALUES(1,'s-1','Summary','<p>x</p>')")
        con.execute("INSERT INTO ReportFindings(id,report_id,uid,title,severity) VALUES(1,1,'f-1','SQLi','high')")
        con.execute("INSERT INTO ReportFindingTargets(finding_id,report_target_uid) VALUES(1,'rt-1')")
        con.execute("INSERT INTO ReportTemplates(uid,name) VALUES('tpl-1','My template')")
        con.execute("INSERT INTO FindingLibrary(uid,title) VALUES('lib-1','Weak TLS')")
        con.execute("INSERT INTO ReportEvidence(uid,kind,title,created_at) VALUES('ev-1','terminal','scan','2026-11-20')")
        con.execute("INSERT INTO Secrets(name,value) VALUES('ext_agent:openai',?)",(SECRET,))
        con.execute("INSERT INTO AuditEvents(ts,event,detail) VALUES('2026-11-20','x',?)",(AUDIT,))
    os.makedirs(os.path.join(d,"Attachments","5"),exist_ok=True)
    with open(os.path.join(d,"Attachments","5","abc123.png"),"wb") as f:f.write(PNG)
    os.makedirs(os.path.join(d,"chain"),exist_ok=True)
    with open(os.path.join(d,"chain","flow.html"),"w") as f:f.write("<html>flow</html>")
    docs={"profiles.json":[{"id":"default","name":"Default","active":True},{"id":"p2","name":"Client B","active":False}],
          "Targets.json":[{"id":"t1","name":"web01","values":{"PASS":"hunter2"}}],"target_values.json":{"PASS":{"priority":1}},
          "Profiles/p2/Targets.json":[{"id":"t9","name":"dc01"}],"Profiles/p2/target_values.json":{"DOMAIN":{"priority":2}},
          "notes_meta.json":{"pinned":[{"note_id":5,"note_name":"Box notes"}],"recent":[],"groups":["Recon"],"nav_collapsed_groups":[]},
          "tag_colors.json":{"web":"#ff0000"},"QuicSpace.json":{"html":"<p>scratch</p>","text":"scratch","wrap":True}}
    for rel,obj in docs.items():
        p=os.path.join(d,*rel.split("/"));os.makedirs(os.path.dirname(p),exist_ok=True)
        with open(p,"w",encoding="utf-8") as f:json.dump(obj,f)
    return docs
def _content_db(out):
    src=db_driver.connect(common_db.db_path())
    try:
        dst=db_driver.connect(out)
        try:src.backup(dst)
        finally:dst.close()
    finally:src.close()
    con=db_driver.connect(out)
    try:
        for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
            if t not in _CONTENT:con.execute(f'DROP TABLE "{t}"')
        con.execute("UPDATE ChainRuns SET data=json_remove(data,'$.vars')");con.commit()
    finally:con.close()
def build_work_zip(out,d,docs,settings=None,extra=None):
    """A zip in the work export format (written here directly, independent of work_export.py)."""
    work=tempfile.mkdtemp(prefix="loya_wz_")
    try:
        db=os.path.join(work,"content.db");_content_db(db)
        with zipfile.ZipFile(out,"w",zipfile.ZIP_DEFLATED) as z:
            man={"format":"loya-work-export","format_version":2,"app_version":"1.0.3","included":{"settings":settings is not None,"run_history":True,"ai_chats":False}}
            z.writestr("manifest.json",json.dumps(man))
            z.write(db,"content.db")
            for rel,obj in docs.items():z.writestr("docs/"+rel,json.dumps(obj))
            z.write(os.path.join(d,"Attachments","5","abc123.png"),"files/Attachments/5/abc123.png")
            z.write(os.path.join(d,"chain","flow.html"),"files/chain/flow.html")
            if settings is not None:z.writestr("settings.json",json.dumps(settings))
            for k,v in (extra or {}).items():z.writestr(k,v)
    finally:shutil.rmtree(work,ignore_errors=True)
    return out
def build_legacy_zip(out,d):
    """An old Export All: the whole Data/ folder, secrets and machine files included."""
    files={"Data/settings.json":json.dumps({"theme":"dark","security":{"pin_hash":SECRET},"cve":{"nvd_api_key":SECRET}}),
           "Data/Note_LOYA_V1.key":json.dumps({"format":"loya-keyfile","marker":SECRET}),
           "Data/external_agents/connections/claude.json":json.dumps({"token":TOKEN}),
           "Data/deps_state.json":json.dumps({"m":SECRET}),"Data/loya.pid":"12345","Data/security_audit.jsonl":json.dumps({"detail":AUDIT})+"\n",
           "Data/search_index/index.json":json.dumps({"x":SECRET}),"Data/terminal_sessions.json":json.dumps({"scroll":SECRET})}
    with zipfile.ZipFile(out,"w",zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json",json.dumps({"type":"LOYA Note Export All","format_version":1}))
        for b,_dirs,names in os.walk(d):
            for n in names:
                p=os.path.join(b,n);rel=os.path.relpath(p,d).replace("\\","/")
                if rel.startswith(("Backups/","_backups/")) or n.endswith(("-wal","-shm")) or "Data/"+rel in files:continue
                z.write(p,"Data/"+rel)
        for k,v in files.items():z.writestr(k,v)
    return out
def _scan_live(test,d,markers):
    for b,_dirs,names in os.walk(d):
        for n in names:
            with open(os.path.join(b,n),"rb") as f:blob=f.read()
            for m in markers:test.assertNotIn(m.encode(),blob,f"{m} leaked into {os.path.join(b,n)}")
class WorkImportTest(unittest.TestCase):
    def setUp(self):
        self.out=tempfile.mkdtemp(prefix="loya_wi_")
        self.src=_Install()
        self.docs=_seed_source(self.src.dir)
        self.work=build_work_zip(os.path.join(self.out,"work.zip"),self.src.dir,self.docs,settings={"theme":"light","appearance":{"theme":"light","density":"compact"},"cve":{"nvd_api_key":SECRET,"watchlist":["openssl"]}})
        self.legacy=build_legacy_zip(os.path.join(self.out,"legacy.zip"),self.src.dir)
        self.src.stop()
        self.dst=_Install()
        with open(os.path.join(self.dst.dir,"settings.json"),"w") as f:json.dump({"theme":"dark","mine":"keep"},f)
        with common_db.connection() as con:
            con.execute("INSERT INTO Secrets(name,value) VALUES('cve:nvd','LIVE-SECRET')")
            con.execute("INSERT INTO AuditEvents(ts,event,detail) VALUES('2026-11-25','live','LIVE-AUDIT')")
        with open(os.path.join(self.dst.dir,"Note_LOYA_V1.key"),"w") as f:f.write("LIVE-KEY")
    def tearDown(self):
        common_db.set_locked(False)
        self.dst.stop();shutil.rmtree(self.out,ignore_errors=True)
    def rows(self,sql,*a):
        with common_db.connection() as con:return con.execute(sql,a).fetchall()
    def test_detect_and_preview_counts(self):
        self.assertEqual("work",wi.detect(self.work));self.assertEqual("legacy",wi.detect(self.legacy))
        p=wi.preview(self.work)
        c=p["counts"]
        self.assertEqual(("work",False),(p["format"],p["protected"]))
        for k,v in {"notes":1,"note_versions":1,"commands":1,"command_notes":1,"reports":1,"report_templates":1,"findings_library":1,"evidence":1,
                    "attachments":1,"chain_files":1,"targets":2,"target_values":2,"target_profiles":2,"quick_space":1,"tag_colors":1,"chain_runs":1,"settings":1}.items():
            self.assertEqual(v,c.get(k),k)
        self.assertEqual(2,c["chains"])
        self.assertEqual({},p["clashes"])
        self.assertTrue(p["has_settings"])
    def test_merge_into_a_fresh_install_brings_every_kind(self):
        res=wi.apply(self.work,"merge")
        self.assertEqual(["Box notes"],[r[0] for r in self.rows("SELECT note_name FROM Notes")])
        nid=self.rows("SELECT id FROM Notes")[0][0]
        content=self.rows("SELECT content FROM Notes")[0][0]
        att=os.path.join(self.dst.dir,"Attachments",str(nid),"abc123.png")
        self.assertTrue(os.path.isfile(att));self.assertIn(ns._file_url(os.path.dirname(att))+"/abc123.png",content);self.assertNotIn("/home/old/",content)
        with open(att,"rb") as f:self.assertEqual(PNG,f.read())
        self.assertEqual([(nid,)],self.rows("SELECT note_id FROM NotesHistory"))
        self.assertEqual([(nid,"nmap -sV 10.0.0.1")],self.rows("SELECT note_id,command FROM Commands"))
        self.assertEqual(1,len(self.rows("SELECT 1 FROM CommandsNotes")))
        self.assertEqual({"Recon","Linear one"},{r[0] for r in self.rows("SELECT name FROM Playbooks")})
        self.assertEqual(1,len(self.rows("SELECT 1 FROM PlaybookSteps")))
        self.assertEqual([(0,)],self.rows("SELECT ai_reviewed FROM ChainGraphs"),"an imported chain must be reviewed before it runs")
        self.assertEqual(["runA1"],[r["run_id"] for r in hist.list_runs({})["items"]])
        self.assertNotIn(SECRET,json.dumps(self.rows("SELECT data FROM ChainRuns")),"run variables never come with an import")
        self.assertEqual(1,len(self.rows("SELECT 1 FROM ReportFindingTargets")));self.assertEqual(1,len(self.rows("SELECT 1 FROM ReportSections")))
        for t in ("Reports","ReportTemplates","FindingLibrary","ReportEvidence"):self.assertEqual(1,len(self.rows(f"SELECT 1 FROM {t}")),t)
        rd=lambda rel,dflt=None:doc_store.read_json(os.path.join(self.dst.dir,*rel.split("/")),dflt)
        self.assertEqual("web01",rd("Targets.json")[0]["name"]);self.assertEqual("dc01",rd("Profiles/p2/Targets.json")[0]["name"])
        self.assertIn("DOMAIN",rd("Profiles/p2/target_values.json"));self.assertIn("p2",{p["id"] for p in rd("profiles.json")})
        self.assertEqual("#ff0000",rd("tag_colors.json")["web"]);self.assertEqual("scratch",rd("QuicSpace.json")["text"])
        self.assertEqual([{"note_id":nid,"note_name":"Box notes"}],rd("notes_meta.json")["pinned"]);self.assertIn("Recon",rd("notes_meta.json")["groups"])
        self.assertTrue(os.path.isfile(os.path.join(self.dst.dir,"chain","flow.html")))
        with open(os.path.join(self.dst.dir,"settings.json")) as f:self.assertEqual("dark",json.load(f)["theme"],"settings only with apply_settings")
        self.assertIn("reviewed",res["message"])
    def test_apply_settings_takes_only_portable_keys(self):
        wi.apply(self.work,"merge",apply_settings=True)
        with open(os.path.join(self.dst.dir,"settings.json")) as f:s=json.load(f)
        self.assertEqual("light",s["appearance"]["theme"]);self.assertEqual("compact",s["appearance"]["density"]);self.assertEqual("keep",s["mine"])
        self.assertEqual(["openssl"],s["cve"]["watchlist"]);self.assertEqual("dark",s["theme"],"only the portable sections are applied")
        self.assertNotIn(SECRET,json.dumps(s))
    def test_merge_clash_rename_and_skip(self):
        wi.apply(self.work,"merge")
        p=wi.preview(self.work)
        self.assertEqual(["Box notes"],p["clashes"]["notes"]);self.assertIn("Recon",p["clashes"]["chains"]);self.assertEqual(["ACME external"],p["clashes"]["reports"])
        res=wi.apply(self.work,"merge",clash="skip")
        self.assertEqual(0,sum(res["added"].get(k,0) for k in ("notes","reports","chains","report_templates","findings_library","targets")))
        self.assertEqual(1,len(self.rows("SELECT 1 FROM Notes")));self.assertEqual(1,len(self.rows("SELECT 1 FROM Reports")))
        res=wi.apply(self.work,"merge",clash="rename")
        self.assertEqual({"Box notes","Box notes (imported)"},{r[0] for r in self.rows("SELECT note_name FROM Notes")})
        self.assertEqual({"ACME external","ACME external (imported)"},{r[0] for r in self.rows("SELECT title FROM Reports")})
        self.assertEqual(2,len({r[0] for r in self.rows("SELECT uid FROM Reports")}))
        self.assertIn("Linear one (imported)",{r[0] for r in self.rows("SELECT name FROM Playbooks")})
        self.assertEqual(4,len(self.rows("SELECT 1 FROM Playbooks")))
        self.assertEqual(1,len(self.rows("SELECT 1 FROM CommandsNotes")),"an identical library command is never duplicated")
        names=[t["name"] for t in doc_store.read_json(os.path.join(self.dst.dir,"Targets.json"),[])]
        self.assertEqual(["web01","web01 (imported)"],names)
        self.assertGreaterEqual(res["renamed"]["notes"],1)
        new=[r for r in self.rows("SELECT id,content FROM Notes WHERE note_name='Box notes (imported)'")][0]
        self.assertTrue(os.path.isfile(os.path.join(self.dst.dir,"Attachments",str(new[0]),"abc123.png")));self.assertIn(f"Attachments/{new[0]}/",new[1])
    def test_replace_keeps_live_secrets_audit_settings_and_key(self):
        with common_db.connection() as con:con.execute("INSERT INTO Notes(note_name,content) VALUES('Live only','x')")
        wi.apply(self.work,"replace")
        self.assertEqual(["Box notes"],[r[0] for r in self.rows("SELECT note_name FROM Notes")])
        self.assertEqual([("cve:nvd","LIVE-SECRET")],self.rows("SELECT name,value FROM Secrets"))
        self.assertIn(("LIVE-AUDIT",),self.rows("SELECT detail FROM AuditEvents"))
        self.assertNotIn((AUDIT,),self.rows("SELECT detail FROM AuditEvents"))
        with open(os.path.join(self.dst.dir,"Note_LOYA_V1.key")) as f:self.assertEqual("LIVE-KEY",f.read())
        with open(os.path.join(self.dst.dir,"settings.json")) as f:self.assertEqual({"theme":"dark","mine":"keep"},json.load(f))
    def test_old_full_data_zip_imports_content_without_secrets(self):
        p=wi.preview(self.legacy)
        self.assertEqual("legacy",p["format"]);self.assertFalse(p["has_settings"])
        for name in ("Data/settings.json","Data/Note_LOYA_V1.key","Data/external_agents/connections/claude.json","Data/deps_state.json","Data/loya.pid",
                     "Data/security_audit.jsonl","Data/search_index/index.json","Data/terminal_sessions.json"):
            self.assertIn(name,p["ignored"])
        wi.apply(self.legacy,"merge",apply_settings=True)
        self.assertEqual(["Box notes"],[r[0] for r in self.rows("SELECT note_name FROM Notes")])
        self.assertEqual({"Recon","Linear one"},{r[0] for r in self.rows("SELECT name FROM Playbooks")})
        self.assertEqual([("cve:nvd","LIVE-SECRET")],self.rows("SELECT name,value FROM Secrets"))
        self.assertNotIn((AUDIT,),self.rows("SELECT detail FROM AuditEvents"))
        with open(os.path.join(self.dst.dir,"settings.json")) as f:self.assertEqual({"theme":"dark","mine":"keep"},json.load(f))
        with open(os.path.join(self.dst.dir,"Note_LOYA_V1.key")) as f:self.assertEqual("LIVE-KEY",f.read())
        for rel in ("external_agents","deps_state.json","loya.pid","search_index","terminal_sessions.json"):
            self.assertFalse(os.path.exists(os.path.join(self.dst.dir,rel)),rel)
        _scan_live(self,self.dst.dir,[SECRET,TOKEN,AUDIT])
    def test_unknown_entries_of_a_work_zip_are_ignored(self):
        # A work zip that also lists secret files: those entries are reported as ignored and never written.
        work=tempfile.mkdtemp(prefix="loya_wz2_")
        try:
            with zipfile.ZipFile(self.work) as zin,zipfile.ZipFile(os.path.join(work,"w.zip"),"w") as zout:
                for i in zin.infolist():zout.writestr(i,zin.read(i))
                zout.writestr("docs/terminal_sessions.json",json.dumps({"s":SECRET}));zout.writestr("Note_LOYA_V1.key",SECRET)
            p=wi.preview(os.path.join(work,"w.zip"))
            self.assertIn("docs/terminal_sessions.json",p["ignored"]);self.assertIn("Note_LOYA_V1.key",p["ignored"])
            wi.apply(os.path.join(work,"w.zip"),"merge")
            self.assertFalse(os.path.exists(os.path.join(self.dst.dir,"terminal_sessions.json")))
            _scan_live(self,self.dst.dir,[SECRET])
        finally:shutil.rmtree(work,ignore_errors=True)
    def test_password_protected_export(self):
        dek=crypto_store.DataKey.generate()
        kf=crypto_store.wrap_dek(dek,"correct horse 42",FAST_KDF)
        prot=os.path.join(self.out,"work.loyawork")
        loyabak.write(self.work,prot,dek,kf,{"kind":"work","protect":"password"});dek.wipe()
        with open(prot,"rb") as f:blob=f.read()
        self.assertTrue(blob.startswith(loyabak.MAGIC));self.assertNotIn(b"Box notes",blob)
        self.assertEqual("work_protected",wi.detect(prot))
        with self.assertRaises(wi.PasswordRequired):wi.preview(prot)
        with self.assertRaises(wi.WrongPassword):wi.preview(prot,password="nope nope nope")
        with self.assertRaises(wi.WrongPassword):wi.apply(prot,"merge",password="nope nope nope")
        self.assertEqual([],self.rows("SELECT 1 FROM Notes"),"a wrong password imports nothing")
        p=wi.preview(prot,password="correct horse 42")
        self.assertTrue(p["protected"]);self.assertEqual(1,p["counts"]["notes"])
        wi.apply(prot,"merge",password="correct horse 42")
        self.assertEqual(["Box notes"],[r[0] for r in self.rows("SELECT note_name FROM Notes")])
    def test_a_full_backup_is_not_imported_here(self):
        dek=crypto_store.DataKey.generate();kf=crypto_store.wrap_dek(dek,"pw pw pw pw",FAST_KDF)
        bak=os.path.join(self.out,"b.loyabak");loyabak.write(self.work,bak,dek,kf,{"kind":"data"});dek.wipe()
        self.assertEqual("backup",wi.detect(bak))
        with self.assertRaisesRegex(ValueError,"Settings > Backup"):wi.preview(bak)
    def test_import_into_an_install_with_encryption_at_rest(self):
        from Cores.Services import security_service as sec
        kdf=sec._KDF;sec._KDF=FAST_KDF
        try:
            os.remove(os.path.join(self.dst.dir,"Note_LOYA_V1.key"))
            ok,msg=sec.set_encryption(True,new_pin="482193");self.assertTrue(ok,msg)
            wi.apply(self.work,"merge")
            self.assertEqual(["Box notes"],[r[0] for r in self.rows("SELECT note_name FROM Notes")])
            self.assertEqual("web01",doc_store.read_json(os.path.join(self.dst.dir,"Targets.json"),[])[0]["name"])
            self.assertFalse(os.path.isfile(os.path.join(self.dst.dir,"Targets.json")),"targets go into the encrypted DB, not a plain file")
            nid=self.rows("SELECT id FROM Notes")[0][0]
            with open(os.path.join(self.dst.dir,"Attachments",str(nid),"abc123.png"),"rb") as f:blob=f.read()
            self.assertTrue(blob.startswith(crypto_store.MAGIC));self.assertEqual(PNG,ns.attachment_bytes(blob))
            with open(common_db.db_path(),"rb") as f:self.assertNotIn(b"hunter2",f.read())
        finally:
            sec.clear_session_pin();sec._KDF=kdf
    def _quick_run_zip(self):
        qr={"favorites":[{"key":"Commands:9","source":"Commands","id":9,"note_name":"Box notes","category":"Recon","sub_category":"Web","command":"nmap -sV 10.0.0.1"},
                         {"key":"CommandsNotes:3","source":"CommandsNotes","id":3,"note_name":"Lib","category":"Recon","sub_category":"Web","command":"gobuster dir -u x"}],"favorites_only":True}
        out=os.path.join(self.out,"qr.zip")
        with zipfile.ZipFile(self.work) as zin,zipfile.ZipFile(out,"w") as zout:
            for i in zin.infolist():zout.writestr(i,zin.read(i))
            zout.writestr("quick_run.json",json.dumps(qr))
        return out
    def test_quick_run_favourites_follow_the_new_command_ids(self):
        with open(os.path.join(self.dst.dir,"settings.json"),"w") as f:json.dump({"theme":"dark","mini_window":{"favorites":["CommandsNotes:77"],"w":500}},f)
        with common_db.connection() as con:con.execute("INSERT INTO CommandsNotes(id,note_name,category,sub_category,command) VALUES(40,'Lib','Recon','Web','gobuster dir -u x')")
        z=self._quick_run_zip()
        self.assertEqual(2,wi.preview(z)["counts"]["quick_run"])
        res=wi.apply(z,"merge")
        nid=self.rows("SELECT id FROM Commands WHERE command='nmap -sV 10.0.0.1'")[0][0]
        with open(os.path.join(self.dst.dir,"settings.json")) as f:s=json.load(f)
        self.assertEqual(["CommandsNotes:77",f"Commands:{nid}","CommandsNotes:40"],s["mini_window"]["favorites"],"the deduped library command maps to the one already here")
        self.assertEqual(500,s["mini_window"]["w"]);self.assertEqual("dark",s["theme"]);self.assertNotIn("favorites_only",s["mini_window"])
        self.assertEqual(2,res["added"]["quick_run"])
        wi.apply(z,"merge",clash="skip")
        with open(os.path.join(self.dst.dir,"settings.json")) as f:self.assertEqual(3,len(json.load(f)["mini_window"]["favorites"]))
        wi.apply(z,"replace")
        nid=self.rows("SELECT id FROM Commands")[0][0];cid=self.rows("SELECT id FROM CommandsNotes")[0][0]
        with open(os.path.join(self.dst.dir,"settings.json")) as f:s=json.load(f)
        self.assertEqual([f"Commands:{nid}",f"CommandsNotes:{cid}"],s["mini_window"]["favorites"]);self.assertTrue(s["mini_window"]["favorites_only"])
        self.assertEqual(500,s["mini_window"]["w"])
    def test_locked_install_refuses(self):
        common_db.set_locked(True)
        with self.assertRaises(common_db.DatabaseLocked):wi.apply(self.work,"merge")
if __name__=="__main__":unittest.main()
