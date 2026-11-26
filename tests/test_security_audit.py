"""Regression tests for the findings in SECURITY-AUDIT.md (phase 1). Each test names its finding ID."""
import ast,base64,hashlib,inspect,os,re,stat,sys,tempfile,shutil,unittest,zipfile
from unittest import mock
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from _isolate import IsolatedData,ROOT
import test_updater_pipeline as _tup
from Cores.Services import notes_service as ns
from Cores.Services import security_service as sec
from Cores.Services import ext_agents_service as ext
from Cores.Update import update_service as us
from Cores.Update import backup_restore as br
from Cores.Update import apply_update as ap
from Cores import os_toast
from Cores.Bridge import api
def _exposed(obj):
    """The names pywebview would publish to JS (mirrors webview.util get_functions: skips _names and _serializable=False)."""
    seen=set();out=[]
    def walk(o,base):
        if id(o) in seen:return
        seen.add(id(o))
        for name in dir(o):
            if name.startswith("_"):continue
            try:attr=getattr(o,name)
            except Exception:continue
            if not getattr(attr,"_serializable",True):continue
            full=f"{base}.{name}" if base else name
            if inspect.ismethod(attr) or inspect.isfunction(attr):out.append(full)
            elif inspect.isclass(attr) or (not callable(attr) and hasattr(attr,"__module__")):walk(attr,full)
    walk(obj,"")
    return out
class NoteSanitiserTests(unittest.TestCase):
    """SA-02: the write-side regex sanitiser left on* handlers in tags with a stray quote or a < in an unquoted value."""
    def test_handlers_removed_from_malformed_tags(self):
        for payload in ["<img src=x' onerror=alert(1)//>","<img title=< onerror=alert(1)>","<img src=x onerror=alert(1)>",'<img src="x"onerror="alert(1)">',"<img/src=x/onerror=alert(1)>"]:
            out=ns.sanitize_note_html(payload)
            self.assertNotRegex(out.lower(),r"onerror\s*=",payload)
    def test_clean_markup_is_kept(self):
        for html in ['<p title="a>b">ok</p>','<a href="https://x">x</a> <b>t</b>','<img src="cmdcard:abc" width="320" height="90" />']:
            self.assertEqual(html,ns.sanitize_note_html(html))
class NoteAppendTests(unittest.TestCase):
    """SA-02: notes.append (MCP notes_append) stored the addition without any sanitising."""
    def setUp(self):
        self.iso=IsolatedData();self.dir=self.iso.start()
        self._abs=ns._abs
        ns._abs=lambda *p:os.path.join(self.dir,*(p[1:] if p and p[0]=="Data" else p))
        ns._SETTINGS_CACHE=None;ns._SETTINGS_MTIME=None
        self._stubs=[(api._semantic_svc,"index_note",api._semantic_svc.index_note),(api._targets_svc,"auto_add_target_values",api._targets_svc.auto_add_target_values)]
        for mod,name,_ in self._stubs:setattr(mod,name,lambda *a,**k:0)
        self.api=api.NotesAPI()
    def tearDown(self):
        for mod,name,fn in self._stubs:setattr(mod,name,fn)
        ns._abs=self._abs;ns._SETTINGS_CACHE=None;ns._SETTINGS_MTIME=None
        self.iso.stop()
    def test_append_strips_script_and_handlers(self):
        nid=self.api.save(None,"A","","<p>start</p>",[],"")["id"]
        self.api.append(nid,"<p>more</p><img src=x' onerror=alert(1)//><script>alert(2)</script>")
        raw=next(n for n in ns._load_notes(ns._db_path()) if int(n["id"])==nid)["content"]
        self.assertIn("more",raw)
        self.assertNotRegex(raw.lower(),r"onerror\s*=|<script")
class BridgeExposureTests(unittest.TestCase):
    """SA-06: bind(window) was callable from JS on every module, so the page could replace a module's window with a string."""
    def setUp(self):
        self.iso=IsolatedData();self.iso.start()
    def tearDown(self):self.iso.stop()
    def test_bind_is_not_published_and_still_works_from_python(self):
        a=api.Api()
        names=_exposed(a)
        self.assertFalse([n for n in names if n.split(".")[-1]=="bind"],names)
        self.assertIn("notes.get",names)
        sentinel=object()
        a.dashboard.bind(sentinel)
        self.assertIs(sentinel,a.dashboard._window)
        m=api.MiniApi()
        self.assertFalse([n for n in _exposed(m) if n.split(".")[-1]=="bind"])
    def test_every_published_method_except_the_open_list_is_lock_guarded(self):
        a=api.Api()
        api._common_db.set_locked(True)
        try:
            with self.assertRaises(ValueError):a.notes.list()
            with self.assertRaises(ValueError):a.extAgents.overview()
            with self.assertRaises(ValueError):a.update.start_update()
        finally:api._common_db.set_locked(False)
@unittest.skipIf(os.name=="nt","POSIX permissions")
class DataPermissionTests(unittest.TestCase):
    """SA-04: Data/ (DB, settings with the PIN hash), Backups/ and Logs/ were readable - the DB even writable - by other local users."""
    def test_private_folders_become_0700_and_files_0600(self):
        root=tempfile.mkdtemp(prefix="loya_perm_")
        try:
            for d in ("Data/Attachments/1","Backups","Logs"):os.makedirs(os.path.join(root,d))
            files=["Data/Note_LOYA_V1.db","Data/settings.json","Data/Attachments/1/a.png","Backups/b.zip","Logs/x.log"]
            for f in files:
                p=os.path.join(root,f)
                with open(p,"w") as fh:fh.write("x")
                os.chmod(p,0o766)
            for d in ("Data","Data/Attachments","Backups","Logs"):os.chmod(os.path.join(root,d),0o775)
            self.assertGreater(sec.harden_data_permissions(root),0)
            for d in ("Data","Data/Attachments","Data/Attachments/1","Backups","Logs"):
                self.assertEqual(0o700,stat.S_IMODE(os.stat(os.path.join(root,d)).st_mode),d)
            for f in files:self.assertEqual(0o600,stat.S_IMODE(os.stat(os.path.join(root,f)).st_mode),f)
            self.assertEqual(0,sec.harden_data_permissions(root))
        finally:shutil.rmtree(root,ignore_errors=True)
    def test_symlinks_are_not_followed(self):
        root=tempfile.mkdtemp(prefix="loya_perm_");outside=tempfile.mkdtemp(prefix="loya_out_")
        try:
            os.makedirs(os.path.join(root,"Data"))
            target=os.path.join(outside,"t");open(target,"w").close();os.chmod(target,0o644)
            os.symlink(target,os.path.join(root,"Data","link"))
            sec.harden_data_permissions(root)
            self.assertEqual(0o644,stat.S_IMODE(os.stat(target).st_mode))
        finally:shutil.rmtree(root,ignore_errors=True);shutil.rmtree(outside,ignore_errors=True)
    def test_startup_lock_sync_hardens(self):
        was=sec._common_db.is_locked()
        try:
            with mock.patch.object(sec,"harden_data_permissions") as h,mock.patch.object(sec,"needs_unlock",lambda:False):
                sec.sync_lock_state()
            h.assert_called_once()
        finally:sec._common_db.set_locked(was)
class AgentGlobTests(unittest.TestCase):
    """SA-05: Glob's pattern (and Grep's glob filter) could reach outside the agent workspace while being auto-allowed."""
    cfg={"builtin_tools":["Glob","Grep","Read"]}
    def decide(self,tool,inp):return ext.builtin_tool_decision(self.cfg,"/tmp/loya-ws",tool,inp)[0]
    def test_outside_patterns_denied(self):
        for inp in ({"pattern":"/etc/**"},{"pattern":"../../**/*.key"},{"pattern":"C:/Users/**"},{"pattern":"~/.ssh/*"},{"pattern":"\\\\host\\share\\*"},{"pattern":"$HOME/*"}):
            self.assertEqual("deny",self.decide("Glob",inp),inp)
        self.assertEqual("deny",self.decide("Grep",{"pattern":"x","glob":"/etc/*"}))
    def test_workspace_patterns_allowed(self):
        self.assertEqual("allow",self.decide("Glob",{"pattern":"**/*.md"}))
        self.assertEqual("allow",self.decide("Grep",{"pattern":"/etc/passwd","glob":"*.txt"}))
class UpdateHelperTests(_tup._TempRoot):
    """SA-07 / SA-08: the apply helper runs isolated (-I) and extracts the very bytes it hashed."""
    make_install=_tup.ApplyHelperTests.make_install
    plan=_tup.ApplyHelperTests.plan
    run_helper=_tup.ApplyHelperTests.run_helper
    read=_tup.ApplyHelperTests.read
    new_pkg=_tup.ApplyHelperTests.new_pkg
    def test_helper_started_in_isolated_mode(self):
        with mock.patch.object(us.subprocess,"Popen") as p:
            p.return_value.pid=4242
            us._spawn_apply_helper("/tmp/h/apply_update.py","/tmp/plan.json")
        args=p.call_args[0][0]
        self.assertEqual("-I",args[1])
        self.assertEqual(["/tmp/h/apply_update.py","/tmp/plan.json"],args[2:])
    def test_package_swapped_after_the_hash_check_is_not_applied(self):
        snap=self.make_install()
        plan_path=self.plan(self.new_pkg(),snap,relaunch=False)
        import json
        with open(plan_path) as f:pkg=json.load(f)["package_path"]
        evil=_tup.build_package("1.0.1",files={"LOYA_Note.py":"EVIL\n","RunNote.py":"EVIL\n","Requirements.json":"{}\n","Assets/a.txt":"EVIL","Cores/x.py":"EVIL","Cores/Update/CurrentVersion.info":"1.0.1\n","UI/windows/main.html":"EVIL"},prefix="LOYA-Note-NG-v1.0.1")
        real=ap._copy_hashed
        def copy_then_swap(src,dst):
            out=real(src,dst)
            with open(src,"wb") as f:f.write(evil)
            return out
        with mock.patch.object(ap,"_copy_hashed",copy_then_swap):
            self.assertEqual(0,self.run_helper(plan_path))
        self.assertEqual("new",self.read("Cores/x.py"))
class BackupTests(_tup._TempRoot):
    """Request from the CVE-index agent: Data/cve_index (public, regenerable) stays out of data backups."""
    def test_cve_index_is_skipped(self):
        self.write("Data/cve_index/cve_index.sqlite","big")
        self.write("Data/settings.json","{}")
        self.write("Data/Attachments/cve_index/keep.png","x")
        from Cores import loyabak
        out=br.create_data_backup(root_dir=self.root,password="test-backup-pw")
        zp=out+".zip"
        with loyabak.unwrap(out,"test-backup-pw") as k:loyabak.decrypt_to(out,zp,k)
        names=zipfile.ZipFile(zp).namelist()
        self.assertIn("Data/settings.json",names)
        self.assertIn("Data/Attachments/cve_index/keep.png",names)
        self.assertFalse([n for n in names if n.startswith("Data/cve_index/")])
class OsToastInjectionTests(unittest.TestCase):
    """SA-03: Windows toasts built a PowerShell "..." string; typographic quotes end it, so a report name could run code."""
    def test_message_only_travels_as_base64(self):
        msg="Report x\u201d; Start-Process calc; \u201c `$(whoami) \"q\""
        with mock.patch.object(os_toast.subprocess,"run") as run:
            run.return_value.returncode=0
            os_toast._send_windows("LOYA Note NG",msg,"LOYA Note NG")
        script=run.call_args[0][0][-1]
        self.assertNotIn("calc",script)
        self.assertNotIn("\u201d",script)
        b64=base64.b64encode(msg.encode("utf-8")).decode("ascii")
        self.assertIn(f"FromBase64String('{b64}')",script)
        self.assertTrue(re.fullmatch(r"[A-Za-z0-9+/=]*",b64))
    def test_linux_message_cannot_become_an_option(self):
        with mock.patch.object(os_toast.subprocess,"run") as run:
            run.return_value.returncode=0
            os_toast._send_linux("--help","-u critical","LOYA Note NG")
        cmd=run.call_args[0][0]
        self.assertEqual(["--","--help","-u critical"],cmd[-3:])
class McpLockOrderTests(unittest.TestCase):
    """SA-09: quickrun_run / chains_run read the saved commands before the lock check (stdio mode has no HTTP guard)."""
    def test_lock_checked_first(self):
        with open(os.path.join(ROOT,"Cores","Bridge","mcp_server.py"),encoding="utf-8") as f:src=f.read()
        tree=ast.parse(src)
        fns={n.name:n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef)}
        for name in ("quickrun_run","chains_run"):
            first=fns[name].body[0]
            self.assertEqual("_lock_check",getattr(getattr(first,"value",None),"func",None).id,name)

# ------------------------------------------------------------------ phase 1b
import json,io,urllib.parse
from Cores import common_db as _cdb,settings_lock as _slock
from Cores.Update import health_check as _hc
class AppLockPinTests(unittest.TestCase):
    """SA-11 / H-01: turning app lock off needs the current PIN."""
    def setUp(self):
        self.iso=IsolatedData();self.dir=self.iso.start()
        self._sp=_hc.settings_path;_hc.settings_path=lambda:os.path.join(self.dir,"settings.json")
        self._it=sec._PIN_ITERS;sec._PIN_ITERS=1000
        sec.clear_session_pin();_cdb.set_locked(False)
    def tearDown(self):
        sec.clear_session_pin();_cdb.set_locked(False);sec._PIN_ITERS=self._it;_hc.settings_path=self._sp;self.iso.stop()
    def test_disable_requires_the_typed_pin(self):
        self.assertTrue(sec.set_app_lock(True,"4821")[0])
        self.assertEqual((False,"Wrong PIN."),sec.set_app_lock(False))
        self.assertEqual((False,"Wrong PIN."),sec.set_app_lock(False,"0000"))
        self.assertTrue(sec.get_security_settings()["app_lock_enabled"])
        self.assertTrue(sec.set_app_lock(False,"4821")[0])
        self.assertFalse(sec.get_security_settings()["app_lock_enabled"])
        self.assertTrue(any(e.get("event")=="app_lock_toggle" and not e.get("success") for e in sec.list_audit_events(50)))
    def test_settings_ui_asks_for_the_pin(self):
        with open(os.path.join(ROOT,"UI","js","pages","settings.js"),encoding="utf-8") as f:src=f.read()
        self.assertIn('bridgeCall("security.set_app_lock",[false,pin])',src)
        self.assertNotIn('bridgeCall("security.set_app_lock",[false])',src)
class WindowsAclTests(unittest.TestCase):
    """Windows counterpart of SA-04: owner-only ACL through icacls (mocked), idempotent, never without the user's SID."""
    class R:
        def __init__(self,rc=0,out="",err=""):self.returncode=rc;self.stdout=out;self.stderr=err
    def setUp(self):
        self.root=tempfile.mkdtemp(prefix="loya_acl_")
        for d in ("Data","Backups","Logs"):os.makedirs(os.path.join(self.root,d))
        self.dirs=[os.path.join(self.root,d) for d in ("Data","Backups","Logs")]
    def tearDown(self):shutil.rmtree(self.root,ignore_errors=True)
    def fake(self,inherited=True,sid="S-1-5-21-111-222-333-1001",fail_set=False):
        calls=[]
        def run(argv,**kw):
            calls.append(list(argv))
            self.assertNotIn("shell",kw)
            if argv[0]=="whoami":return self.R(0 if sid else 1,f'"pc\\\\bob","{sid}"\n' if sid else "")
            if argv[0]=="icacls" and len(argv)==2:
                return self.R(0,f"{argv[1]} BUILTIN\\Users:(I)(OI)(CI)(RX)\n            NT AUTHORITY\\SYSTEM:(I)(OI)(CI)(F)\n" if inherited else f"{argv[1]} pc\\bob:(OI)(CI)(F)\n")
            return self.R(1 if fail_set else 0)
        return run,calls
    def test_inheriting_folders_get_owner_only_acl(self):
        run,calls=self.fake();logs=[]
        self.assertEqual(3,sec._harden_windows_acls(self.dirs,run=run,log=logs.append))
        sets=[c for c in calls if c[0]=="icacls" and len(c)>2]
        self.assertEqual(3,len(sets))
        for c in sets:
            self.assertEqual("/inheritance:r",c[2])
            self.assertIn("*S-1-5-21-111-222-333-1001:(OI)(CI)F",c)
            self.assertIn("*S-1-5-18:(OI)(CI)F",c)
            self.assertFalse([a for a in c[2:] if "Users" in a or "Everyone" in a])
            self.assertNotIn("/T",c)
    def test_already_hardened_resets_unreadable_children(self):
        run,calls=self.fake(inherited=False);logs=[]
        broken=os.path.join(self.dirs[0],"Targets.json")
        with mock.patch.object(sec,"_win_unreadable_paths",side_effect=lambda top:[broken] if top==self.dirs[0] else []):
            self.assertEqual(1,sec._harden_windows_acls(self.dirs,run=run,log=logs.append))
        resets=[c for c in calls if c[0]=="icacls" and "/reset" in c]
        self.assertEqual([["icacls",os.path.join(self.dirs[0],"*"),"/reset","/T","/C","/Q"]],resets)
        self.assertFalse([c for c in calls if "/inheritance:r" in c])
    def test_unreadable_paths_finds_permission_errors(self):
        path=os.path.join(self.dirs[0],"a.json")
        with open(path,"w") as f:f.write("[]")
        self.assertEqual([],sec._win_unreadable_paths(self.dirs[0]))
        real_open=open
        def deny(p,*a,**k):
            if p==path:raise PermissionError(13,"denied",p)
            return real_open(p,*a,**k)
        with mock.patch("builtins.open",deny):
            self.assertEqual([path],sec._win_unreadable_paths(self.dirs[0]))
    def test_already_hardened_is_left_alone(self):
        run,calls=self.fake(inherited=False)
        self.assertEqual(0,sec._harden_windows_acls(self.dirs,run=run))
        self.assertFalse([c for c in calls if c[0]=="icacls" and len(c)>2])
    def test_unknown_sid_changes_nothing(self):
        run,calls=self.fake(sid="");logs=[]
        self.assertEqual(0,sec._harden_windows_acls(self.dirs,run=run,log=logs.append))
        self.assertFalse([c for c in calls if c[0]=="icacls"])
        self.assertTrue(logs)
    def test_failures_only_log(self):
        run,_=self.fake(fail_set=True);logs=[]
        self.assertEqual(0,sec._harden_windows_acls(self.dirs,run=run,log=logs.append))
        self.assertEqual(3,len([l for l in logs if "could not restrict" in l]))
        def boom(*a,**k):raise OSError("no icacls")
        self.assertEqual(0,sec._harden_windows_acls(self.dirs,run=boom,log=logs.append))
    def test_windows_branch_uses_it(self):
        with mock.patch.object(sec.os,"name","nt"),mock.patch.object(sec,"_harden_windows_acls",return_value=2) as h:
            self.assertEqual(2,sec.harden_data_permissions(self.root))
        self.assertEqual(self.dirs,h.call_args[0][0])
class NavGuardNativeTests(unittest.TestCase):
    """H-05: the native backstop only lets the windows show the app's own UI files."""
    def test_allowed(self):
        ui=api._ui_root_dir()
        good=["file://"+urllib.parse.quote(os.path.join(ui,"windows","main.html").replace("\\","/")),"about:blank","about:srcdoc"]
        bad=["https://evil.example/","http://127.0.0.1:8765/mcp","file:///etc/passwd","file://host/share/x.html","file://"+urllib.parse.quote(os.path.join(ui,"..","Data","x.html").replace("\\","/")),"data:text/html,<script>","javascript:alert(1)","ms-msdt:/id","blob:file:///x"]
        for u in good:self.assertTrue(api._nav_allowed(u),u)
        for u in bad:self.assertFalse(api._nav_allowed(u),u)
    def test_external_links_never_reach_webbrowser(self):
        before=api.webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"]
        try:
            api.webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"]=True
            api._harden_webview_settings()
            self.assertFalse(api.webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"])
        finally:api.webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"]=before
class BackupZipLimitTests(_tup._TempRoot):
    """SA-14: data / code restores validate the zip before writing anything."""
    def zipf(self,entries,name="b.zip"):
        p=os.path.join(self.root,name)
        with zipfile.ZipFile(p,"w",zipfile.ZIP_DEFLATED) as z:
            for n,data in entries:
                if isinstance(n,zipfile.ZipInfo):z.writestr(n,data)
                else:z.writestr(n,data)
        return p
    def test_good_backup_restores(self):
        p=self.zipf([("Data/settings.json","{}"),("Data/Attachments/1/a.png","x")])
        ok,msg=br.restore_data_backup(p,"replace",root_dir=self.root)
        self.assertTrue(ok,msg)
        self.assertEqual("{}",self.read_file("Data/settings.json"))
        if os.name!="nt":
            # Restored files stay owner-only (the temp extract's umask mode used to leak through copy2 as 0664).
            for rel in ("Data/settings.json","Data/Attachments/1/a.png"):
                self.assertEqual(0o600,stat.S_IMODE(os.stat(os.path.join(self.root,*rel.split("/"))).st_mode),rel)
    def test_migration_backup_layout_restores(self):
        # pre-encryption-*.loyabak (storage_migration.make_loyabak) keeps Data/'s contents at the root plus a manifest.
        p=self.zipf([("loyabak-manifest.json",'{"format":"loya-data-backup"}'),("settings.json",'{"a":1}'),("Profiles/x/Targets.json","[]")],"mig.zip")
        ok,msg=br.restore_data_backup(p,"replace",root_dir=self.root)
        self.assertTrue(ok,msg)
        self.assertEqual('{"a":1}',self.read_file("Data/settings.json"))
        self.assertEqual("[]",self.read_file("Data/Profiles/x/Targets.json"))
        self.assertFalse(os.path.exists(os.path.join(self.root,"Data","loyabak-manifest.json")))
        # As a .loyabak the decrypted zip sits in the restore temp folder: it must not be copied into Data/.
        def fake_open(path,tmp,pin=None,password=None,trusted=False):
            zp=os.path.join(tmp,"backup.zip");shutil.copy(p,zp);return zp,None
        with mock.patch("Cores.loyabak.is_loyabak",return_value=True),mock.patch.object(br,"_open_loyabak",fake_open):
            ok,msg=br.restore_data_backup(p,"replace",root_dir=self.root)
        self.assertTrue(ok,msg)
        self.assertEqual(sorted(["settings.json","Profiles"]),sorted(n for n in os.listdir(os.path.join(self.root,"Data")) if n in ("settings.json","Profiles","backup.zip","loyabak-manifest.json")))
        p2=self.zipf([("settings.json","{}")],"nomanifest.zip")
        self.assertEqual((False,"Missing Data/ in backup"),br.restore_data_backup(p2,"replace",root_dir=self.root))
    def read_file(self,rel):
        with open(os.path.join(self.root,*rel.split("/"))) as f:return f.read()
    def test_refused_archives(self):
        link=zipfile.ZipInfo("Data/link");link.external_attr=(stat.S_IFLNK|0o777)<<16
        cases={"traversal":[("Data/../../evil.txt","x")],"absolute":[("/etc/evil","x")],"drive":[("C:/evil","x")],"ads":[("Data/a.txt:stream","x")],"reserved":[("Data/CON.txt","x")],"symlink":[(link,"/etc/passwd")],"duplicate":[("Data/a","1"),("Data/A","2")],"bomb":[("Data/zeros.bin",b"\0"*(8*1024*1024))]}
        for name,entries in cases.items():
            p=self.zipf(entries,name+".zip")
            ok,msg=br.restore_data_backup(p,"merge",root_dir=self.root)
            self.assertFalse(ok,name)
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(self.root),"evil.txt")))
    def test_limits_are_enforced(self):
        p=self.zipf([("Data/a","123456"),("Data/b","123456")])
        with mock.patch.object(br,"BACKUP_MAX_TOTAL_BYTES",10):
            self.assertFalse(br.restore_data_backup(p,"merge",root_dir=self.root)[0])
        with mock.patch.object(br,"BACKUP_MAX_ENTRIES",1):
            self.assertFalse(br.restore_data_backup(p,"merge",root_dir=self.root)[0])
        with mock.patch.object(br.shutil,"disk_usage",return_value=mock.Mock(free=5)):
            self.assertFalse(br.restore_data_backup(p,"merge",root_dir=self.root)[0])
    def test_code_snapshot_restore_is_checked_too(self):
        p=self.zipf([("app/../../evil.py","x")],"snap.zip")
        self.assertFalse(br.restore_code_snapshot(p,root_dir=self.root)[0])
class SettingsWriteLockTests(unittest.TestCase):
    """H-10: every read-modify-write of settings.json happens under settings_lock.SETTINGS_LOCK."""
    def test_no_unlocked_settings_writer(self):
        names={"_write_settings","write_settings","_write_json","write_json"}
        bad=[]
        import glob
        for f in glob.glob(os.path.join(ROOT,"Cores","**","*.py"),recursive=True):
            with open(f,encoding="utf-8") as fh:src=fh.read()
            if "settings" not in src:continue
            tree=ast.parse(src);parents={}
            for n in ast.walk(tree):
                for c in ast.iter_child_nodes(n):parents[c]=n
            for n in ast.walk(tree):
                if not isinstance(n,ast.Call):continue
                fn=n.func.id if isinstance(n.func,ast.Name) else (n.func.attr if isinstance(n.func,ast.Attribute) else "")
                if fn not in names:continue
                if fn in ("_write_json","write_json") and not (n.args and "settings" in ast.unparse(n.args[0]).lower()):continue
                p=n;locked=False;func=None
                while p in parents:
                    p=parents[p]
                    if isinstance(p,ast.With) and "LOCK" in ast.unparse(p.items[0].context_expr).upper():locked=True
                    if isinstance(p,ast.FunctionDef):
                        func=func or p.name
                        if any("serialized" in ast.unparse(d) for d in p.decorator_list):locked=True
                if func and func.startswith(("_write","write")):continue
                if not locked:bad.append(f"{os.path.relpath(f,ROOT)}:{n.lineno} {func}")
        self.assertEqual([],bad)
    def test_concurrent_writers_keep_every_key(self):
        import threading
        d=tempfile.mkdtemp(prefix="loya_set_");p=os.path.join(d,"settings.json")
        try:
            def w(i):
                for j in range(20):_slock.update_json(p,lambda s:s.__setitem__(f"k{i}_{j}",j))
            ts=[threading.Thread(target=w,args=(i,)) for i in range(6)]
            [t.start() for t in ts];[t.join() for t in ts]
            with open(p) as f:self.assertEqual(120,len(json.load(f)))
        finally:shutil.rmtree(d,ignore_errors=True)
class RemoteImagePrefTests(NoteAppendTests):
    """Remote images in notes are blocked (click to load) unless the user turns it off."""
    def test_default_on_and_toggle(self):
        self.assertIs(True,ns.editor_prefs()["block_remote_images"])
        ns.set_editor_pref("block_remote_images",False)
        self.assertIs(False,ns.editor_prefs()["block_remote_images"])
        ns.set_editor_pref("block_remote_images",True)
        self.assertIs(True,ns.editor_prefs()["block_remote_images"])
    test_append_strips_script_and_handlers=None
class DependencyPinTests(unittest.TestCase):
    """SA-17 / SA-18: patched pins and minimum versions for the MCP server's transitive packages."""
    def test_pins(self):
        with open(os.path.join(ROOT,"Requirements.json"),encoding="utf-8") as f:d=json.load(f)
        pk={p["name"]:p["version"] for p in d["pip"]["packages"]}
        self.assertEqual("==2.2.0",pk["mcp"]);self.assertEqual("==2.8.8",pk["fpdf2"])
        self.assertEqual(">=1.3.1",pk["starlette"]);self.assertEqual(">=0.0.31",pk["python-multipart"]);self.assertEqual(">=4.14.2",pk["anyio"])
    def test_installed_versions_are_not_older(self):
        import importlib.metadata as md
        def v(s):return tuple(int(x) for x in re.findall(r"\d+",s)[:3])
        for name,floor in (("mcp","2.2.0"),("fpdf2","2.8.8"),("starlette","1.3.1"),("python-multipart","0.0.31"),("anyio","4.14.2")):
            try:have=md.version(name)
            except md.PackageNotFoundError:continue
            self.assertGreaterEqual(v(have),v(floor),name)
class McpErrorPassthroughTests(unittest.TestCase):
    """mcp 2.2 masks non-ToolError messages; AI Roles denials and the lock must still reach the agent (redacted)."""
    def test_expected_errors_pass_crashes_stay_masked(self):
        import asyncio
        from mcp.server.mcpserver import exceptions as ex
        from Cores.Services import mcp_local_service as ml
        if not hasattr(ex,"UnexpectedToolError"):self.skipTest("mcp < 2.2")
        class S:
            async def call_tool(self,name,arguments,context=None):
                cause={"deny":ValueError("AI permission Notes > Delete is set to Deny. password: hunter2"),"crash":KeyError("internal")}[name]
                raise ex.UnexpectedToolError(f"Error executing tool {name}") from cause
        s=ml.passthrough_expected_errors(S())
        self.assertIs(s,ml.passthrough_expected_errors(s))
        with self.assertRaises(ex.ToolError) as c:asyncio.run(s.call_tool("deny",{}))
        self.assertNotIsInstance(c.exception,ex.UnexpectedToolError)
        self.assertIn("Deny",str(c.exception));self.assertNotIn("hunter2",str(c.exception))
        with self.assertRaises(ex.UnexpectedToolError):asyncio.run(s.call_tool("crash",{}))

class LiveSecretMaskingTests(unittest.TestCase):
    """quickrun_list / terminal_run_status / chains_*: a live-target {Password} value never reaches an AI in a tool result,
    an error message or the approval/audit summary. Only targets_secret_values returns it."""
    class Ctx:
        def __init__(self):self.name="box";self.map={"password":"Sup3rS3cret!","ntlm hash":"aad3b435b51404ee","ip":"10.0.0.5","pin":"12"}
    def setUp(self):
        from Cores.Services import search_service as ss
        self.p=mock.patch.object(ss,"LiveTargetContext",self.Ctx);self.p.start()
    def tearDown(self):self.p.stop()
    def test_values_and_mask(self):
        from Cores.Services import mcp_local_service as ml
        self.assertEqual(["Sup3rS3cret!","aad3b435b51404ee"],sorted(ml.live_secret_values()))
        out=ml.mask_live_secrets({"resolved":"smbclient -U admin%Sup3rS3cret! //10.0.0.5/c$","steps":["x aad3b435b51404ee"]})
        self.assertNotIn("Sup3rS3cret!",json.dumps(out));self.assertNotIn("aad3b435b51404ee",json.dumps(out))
        self.assertIn("10.0.0.5",out["resolved"])
    def test_tool_results_errors_and_summaries_are_masked(self):
        import asyncio
        from mcp.types import CallToolResult,TextContent
        from mcp.server.mcpserver import exceptions as ex
        from Cores.Services import mcp_local_service as ml
        class S:
            async def call_tool(self,name,arguments,context=None):
                if name=="boom":
                    raise (ex.UnexpectedToolError("x") if hasattr(ex,"UnexpectedToolError") else ex.ToolError("x")) from ValueError("cannot run: Sup3rS3cret!")
                txt='{"resolved":"psexec -p Sup3rS3cret! 10.0.0.5"}'
                return CallToolResult(content=[TextContent(type="text",text=txt)],structured_content={"resolved":"psexec -p Sup3rS3cret! 10.0.0.5"})
        s=ml.passthrough_expected_errors(S())
        for tool in ("quickrun_list","terminal_run_status","chains_status"):
            r=asyncio.run(s.call_tool(tool,{}))
            self.assertNotIn("Sup3rS3cret!",r.content[0].text+json.dumps(r.structured_content),tool)
            self.assertIn("10.0.0.5",r.content[0].text)
        r=asyncio.run(s.call_tool("targets_secret_values",{}))
        self.assertIn("Sup3rS3cret!",r.content[0].text)
        if hasattr(ex,"UnexpectedToolError"):
            with self.assertRaises(ex.ToolError) as c:asyncio.run(s.call_tool("boom",{}))
            self.assertNotIn("Sup3rS3cret!",str(c.exception))
        from Cores.Services import ai_service as ai
        summary=ai.summarize_args({"command":"psexec -p Sup3rS3cret! 10.0.0.5","steps":["a aad3b435b51404ee"]})
        self.assertNotIn("Sup3rS3cret!",summary);self.assertNotIn("aad3b435b51404ee",summary)
    def test_real_server_is_wrapped(self):
        from Cores.Bridge import mcp_server
        self.assertTrue(getattr(mcp_server.build_server(),"_loya_errors_passthrough",False))

# ------------------------------------------------------------------ phase 2
class RedactionPatternTests(unittest.TestCase):
    """SA-25: redact_secrets missed curl -u, URL userinfo, smbclient -U, impacket user:pass@ and -hashes; -p matched inside --protocols."""
    def test_new_patterns(self):
        from Cores.Services.terminal_service import redact_secrets as r
        cases={"curl -u admin:Winter2024 https://x":"Winter2024","curl --user=bob:pw1 x":"pw1","curl https://admin:S3cret@10.0.0.5/api":"S3cret","ftp://u:FtpPass@h/":"FtpPass",
               "smbclient -U administrator%Passw0rd //h/c":"Passw0rd","secretsdump.py corp.local/admin:Pa55word@10.0.0.1":"Pa55word","psexec.py -hashes aad3b435:31d6cfe0 corp/admin@10.0.0.1":"31d6cfe0",
               "mysql -pHunter2 -u root":"Hunter2","sshpass -p Hunter2 ssh x":"Hunter2"}
        for cmd,secret in cases.items():
            out,found=r(cmd)
            self.assertNotIn(secret,out,cmd);self.assertTrue(found,cmd)
    def test_no_false_positives(self):
        from Cores.Services.terminal_service import redact_secrets as r
        for cmd in ("nmap --protocols tcp -p 80,443 host","nmap -p- host","ls -la /var/www/html","git clone https://github.com/x/y","scp file user@host:/tmp","echo well-positioned","ssh-pass-helper --version"):
            self.assertEqual(cmd,r(cmd)[0],cmd)
class AuditLogRedactionTests(unittest.TestCase):
    """SA-26: Data/security_audit.jsonl stored full commands (and anything else a caller logged) in plaintext."""
    def setUp(self):
        self.iso=IsolatedData();self.dir=self.iso.start()
        self._ap=sec._audit_path;sec._audit_path=lambda:os.path.join(self.dir,"security_audit.jsonl")
    def tearDown(self):sec._audit_path=self._ap;self.iso.stop()
    def test_every_entry_is_redacted_on_write(self):
        sec.log_audit_event("terminal_command","terminal:1 curl -u admin:Winter2024 https://x",True)
        sec.log_audit_event("ext_agent_tool","password=Hunter2 and Authorization: Bearer abc.def",True)
        with open(sec._audit_path(),encoding="utf-8") as f:raw=f.read()
        for secret in ("Winter2024","Hunter2","abc.def"):self.assertNotIn(secret,raw)
        self.assertIn("[redacted]",raw)
        self.assertEqual({"ts","event","detail","success"},set(json.loads(raw.splitlines()[0])))
class ReportSourcesTests(NoteAppendTests):
    """SA-27: reports.sources() sent raw target secret values to the page and relied on client-side filtering."""
    def test_secret_values_stay_server_side(self):
        from Cores import target_profiles
        from Cores.Services import reports_service as rs
        pid=target_profiles.active_profile_id() if hasattr(target_profiles,"active_profile_id") else None
        p=target_profiles.profile_targets_json_path(pid) if pid else None
        if not p:self.skipTest("no target profile API")
        os.makedirs(os.path.dirname(p),exist_ok=True)
        with open(p,"w",encoding="utf-8") as f:json.dump([{"id":"t1","name":"DC01","status":"live","values":{"IP":"10.0.0.5","Password":"Winter2024!","NTLM Hash":"aad3b435b51404ee","User":"admin"}}],f)
        src=rs.sources(pid)
        dump=json.dumps(src)
        for secret in ("Winter2024!","aad3b435b51404ee"):self.assertNotIn(secret,dump)
        t=src["targets"][0]
        self.assertEqual({"IP":"10.0.0.5"},t["values"])
        self.assertEqual({"Password","NTLM Hash","User"},set(t["secret_keys"]))
    test_append_strips_script_and_handlers=None
class ImportPathAllowListTests(unittest.TestCase):
    """SA-28: importExport.apply_*_import, apply_import_all and backup.restore accepted any path from the page."""
    def setUp(self):
        self.iso=IsolatedData();self.iso.start()
    def tearDown(self):api._PICKED_PATHS.clear();self.iso.stop()
    def test_unpicked_paths_refused(self):
        a=api.Api()
        for call in (lambda:a.importExport.apply_notes_import("/etc/passwd","csv",{}),lambda:a.importExport.apply_commands_import("/etc/passwd","csv",{}),
                     lambda:a.importExport.apply_target_values_import("/etc/passwd","csv",{}),lambda:a.importExport.apply_targets_import("/etc/passwd","csv",{}),
                     lambda:a.importExport.apply_import_all("/tmp/x.zip","merge"),lambda:a.backup.restore("/tmp/x.zip","merge")):
            with self.assertRaises(ValueError) as c:call()
            self.assertIn("no longer available",str(c.exception))
    def test_picked_path_accepted(self):
        d=tempfile.mkdtemp(prefix="loya_pick_")
        try:
            p=os.path.join(d,"t.csv")
            with open(p,"w") as f:f.write("key,priority\n")
            self.assertEqual(p,api._remember_pick(p))
            self.assertEqual(os.path.realpath(p),api._require_picked(p))
            self.assertEqual(os.path.realpath(p),api._require_picked(os.path.join(d,".","t.csv")))
        finally:shutil.rmtree(d,ignore_errors=True)
class ReportAiConsentTests(unittest.TestCase):
    """SA-29: reportAI.run/run_start from the page worked without the digest of the confirmed preview."""
    def test_digest_required(self):
        from Cores.Bridge import report_ai_api as ra
        b=ra.ReportAIAPI()
        for d in (None,"","abc","x"*64):
            with self.assertRaises(ValueError):b.run("exec_summary",{"reportId":1},d)
            with self.assertRaises(ValueError):b.run_start("exec_summary",{"reportId":1},d)
        with mock.patch.object(ra._svc,"run_start",return_value={"job_id":"j"}) as m:
            self.assertEqual({"job_id":"j"},b.run_start("exec_summary",{},"A"*64))
        self.assertEqual("a"*64,m.call_args[0][2])
class ElevatedHelperIsolationTests(unittest.TestCase):
    """SA-30: the elevated helper runs with -I -S (no .pth / PYTHON* from the user-writable venv).
    SA-39: it is passed as -c code, never written to a file a user-level process could swap before the UAC prompt."""
    def launch(self,shell_cmd=("C:\\Windows\\System32\\cmd.exe","/k")):
        import ctypes,shlex
        from Cores.Services import terminal_service as term
        seen={}
        def shell_execute(hwnd,verb,exe,params,cwd,show):
            seen.update(verb=verb,exe=exe,params=params);return 42
        fake=mock.Mock();fake.shell32.ShellExecuteW=shell_execute
        conn=mock.Mock();conn.recv.return_value=b""
        with mock.patch.object(ctypes,"windll",fake,create=True),\
             mock.patch.object(term,"_shell_command",return_value=list(shell_cmd)),\
             mock.patch.object(term,"_accept_verified_connection",return_value=conn) as acc,\
             mock.patch.object(term.tempfile,"mkdtemp",side_effect=AssertionError("no helper file may be written")),\
             mock.patch("builtins.open",side_effect=AssertionError("no helper file may be written")):
            term.ElevatedSession("cmd")
        token=acc.call_args[0][1]
        return seen,token,shlex.split(seen["params"],posix=True)
    def test_runas_with_isolated_code_argument(self):
        from Cores.Services import terminal_service as term
        seen,token,argv=self.launch()
        self.assertEqual("runas",seen["verb"])
        self.assertEqual(["-I","-S","-c"],argv[:3])
        self.assertTrue(argv[4].isdigit());self.assertEqual(["C:\\Windows\\System32\\cmd.exe","/k"],argv[5:])
        loader=argv[3]
        self.assertRegex(loader,r"^import base64;exec\(compile\(base64\.b64decode\('[A-Za-z0-9+/=]+'\),'loya_elevated_helper','exec'\)\)$")
        code=base64.b64decode(re.search(r"b64decode\('([^']+)'\)",loader).group(1)).decode("utf-8")
        self.assertEqual(term.elevated_helper_source(token),code)
        compile(code,"loya_elevated_helper","exec")
    def test_refuses_unsafe_values(self):
        from Cores.Services import terminal_service as term
        with self.assertRaises(ValueError):term.elevated_helper_source("not-hex")
        with self.assertRaises(ValueError):term.elevated_helper_parameters("ab"*16,0,["cmd.exe"])
        with self.assertRaises(ValueError):term.elevated_helper_parameters("ab"*16,4444,['cmd.exe" & calc & "'])
        with self.assertRaises(ValueError):term.elevated_helper_parameters("ab"*16,4444,["a\nb"])
    def test_no_temp_helper_code_left(self):
        with open(os.path.join(ROOT,"Cores","Services","terminal_service.py"),encoding="utf-8") as f:src=f.read()
        self.assertNotIn("_write_elevated_helper",src);self.assertNotIn("elevated_helper.py",src)
class ToolResultListTests(NoteAppendTests):
    """SA-32: ai_chat_service._call_tool turned a one-item list into a bare object (and ignored is_error)."""
    def test_one_item_list_stays_a_list(self):
        from Cores.Services import ai_chat_service as chat
        with mock.patch.object(chat._ai_svc if hasattr(chat,"_ai_svc") else api._ai_svc,"authorize",return_value="allow"):
            self.api.save(None,"Only","","<p>x</p>",[],"")
            ok,res=chat._call_tool("notes_list",{})
        self.assertTrue(ok);self.assertIsInstance(res,list);self.assertEqual(1,len(res))
    def test_is_error_is_a_failure(self):
        import asyncio
        from mcp.types import CallToolResult,TextContent
        from Cores.Services import ai_chat_service as chat
        class S:
            async def call_tool(self,name,args):return CallToolResult(content=[TextContent(type="text",text="denied")],is_error=True)
        with mock.patch.object(chat,"_get_server",return_value=S()):
            self.assertEqual((False,"denied"),chat._call_tool("x",{}))
    test_append_strips_script_and_handlers=None
class PhaseTwoDependencyTests(unittest.TestCase):
    """SA-33: system-site copies of pillow / httpx2 / httpcore2 / opentelemetry-api had open advisories."""
    def test_floors(self):
        with open(os.path.join(ROOT,"Requirements.json"),encoding="utf-8") as f:d=json.load(f)
        pk={p["name"]:p["version"] for p in d["pip"]["packages"]}
        for n,v in (("pillow",">=13.0.0"),("httpx2",">=2.12.0"),("httpcore2",">=2.10.0"),("opentelemetry-api",">=1.45.2")):self.assertEqual(v,pk.get(n),n)
        import importlib.metadata as md
        def ver(s):return tuple(int(x) for x in re.findall(r"\d+",s)[:3])
        for n,v in (("pillow","13.0.0"),("httpx2","2.12.0"),("httpcore2","2.10.0"),("opentelemetry-api","1.45.2")):
            try:self.assertGreaterEqual(ver(md.version(n)),ver(v),n)
            except md.PackageNotFoundError:pass

class AppSearchSecretTests(unittest.TestCase):
    """SA-36: MCP app_search returned every target's values (passwords included) and matched on them (an oracle)."""
    def test_hidden_for_ai(self):
        from Cores.Services import search_service as ss,targets_service as ts
        class Store:
            targets=[{"id":"t1","name":"DC01","values":{"IP":"10.0.0.5","Password":"Winter2024!"}}]
        with mock.patch.object(ts,"Store",Store),mock.patch.object(ss,"_load_cmds",return_value=("",[])),mock.patch("Cores.Services.notes_service._load_notes",return_value=[]):
            self.assertTrue(ss.global_search("Winter2024"))
            self.assertEqual([],ss.global_search("Winter2024",hide_secret_values=True))
            hits=ss.global_search("DC01",hide_secret_values=True)
            self.assertEqual(1,len(hits));self.assertNotIn("Winter2024",json.dumps(hits));self.assertIn("10.0.0.5",hits[0]["preview"])
    def test_tool_uses_it(self):
        with open(os.path.join(ROOT,"Cores","Bridge","mcp_app_tools.py"),encoding="utf-8") as f:src=f.read()
        self.assertIn("global_search(q[:200],hide_secret_values=True)",src)
if __name__=="__main__":unittest.main()
