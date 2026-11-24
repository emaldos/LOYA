import hashlib,io,json,os,shutil,stat,subprocess,sys,tempfile,threading,unittest,urllib.error,zipfile
from datetime import datetime,timedelta,timezone
from unittest import mock
from _isolate import ROOT
from _fake_github import FakeGitHub,build_package,patch_updater_for
from Cores.Update import update_helpers as h
from Cores.Update import update_service as us
from Cores.Update import backup_restore as br
from Cores.Update import apply_update as ap
def _zip(entries):
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,"w") as z:
        for name,data in entries:
            if isinstance(name,zipfile.ZipInfo):z.writestr(name,data)
            else:z.writestr(name,data)
    return buf.getvalue()
class _TempRoot(unittest.TestCase):
    """Every path the updater uses (state.json, CurrentVersion.info, Logs, Backups, Data/settings.json) lives in a temp root."""
    def setUp(self):
        self.root=tempfile.mkdtemp(prefix="loya_upd_")
        os.makedirs(os.path.join(self.root,"Cores","Update"))
        os.makedirs(os.path.join(self.root,"Data"))
        with open(os.path.join(self.root,"Cores","Update","CurrentVersion.info"),"w") as f:f.write("1.0.0\n")
        self._p=mock.patch.object(h,"root_dir",lambda:__import__("pathlib").Path(self.root))
        self._p.start()
    def tearDown(self):
        self._p.stop()
        shutil.rmtree(self.root,ignore_errors=True)
    def write(self,rel,data):
        p=os.path.join(self.root,*rel.split("/"));os.makedirs(os.path.dirname(p),exist_ok=True)
        with open(p,"wb" if isinstance(data,bytes) else "w") as f:f.write(data)
        return p
class VersionTests(unittest.TestCase):
    def test_semver_compare(self):
        self.assertEqual(1,h.compare_semver("1.0.10","1.0.9"))
        self.assertEqual(-1,h.compare_semver("1.0.0","1.0.1"))
        self.assertEqual(0,h.compare_semver("2.1.0","2.1.0"))
        self.assertEqual(1,h.compare_semver("2.0.0","1.99.99"))
    def test_prerelease_and_junk_versions_are_not_semver(self):
        for bad in ("1.0.1-beta","1.0.1+build","01.0.0","1.0","v1.0.0","1.0.0.0",""," "):
            self.assertIsNone(h.parse_semver(bad),bad)
        with self.assertRaises(ValueError):h.compare_semver("1.0.1-rc1","1.0.0")
    def test_tags(self):
        self.assertEqual("1.2.3",h.tag_to_version("v1.2.3"))
        self.assertEqual("",h.tag_to_version("v1.2.3-rc1"))
        self.assertEqual("v1.2.3",h.version_to_tag("1.2.3"))
        self.assertEqual("LOYA-NG-v1.2.3.zip",h.expected_package_asset_name("1.2.3"))
class ManifestTests(unittest.TestCase):
    def release(self,**kw):
        p={"id":5,"tag_name":"v1.0.1","name":"1.0.1","draft":False,"prerelease":False,"target_commitish":"main","html_url":"https://github.com/emaldos/LOYA/releases/tag/v1.0.1","published_at":"2026-11-20T10:00:00Z","body":"## Fixes\n- one","assets":[{"name":"LOYA-NG-v1.0.1.zip","size":1000,"digest":"sha256:"+"a"*64,"browser_download_url":"https://github.com/emaldos/LOYA/releases/download/v1.0.1/LOYA-NG-v1.0.1.zip"}]}
        p.update(kw);return p
    def test_good_release(self):
        m=us._manifest_from_github_release(self.release())
        self.assertEqual(("1.0.1","v1.0.1","a"*64,"LOYA-NG-v1.0.1.zip",1000),(m["version"],m["source_tag"],m["digest_sha256"],m["asset_name"],m["asset_size"]))
        self.assertIn("Fixes",m["release_notes"])
    def test_tag_must_be_semver(self):
        with self.assertRaises(ValueError):us._manifest_from_github_release(self.release(tag_name="v1.0.1-beta"))
        with self.assertRaises(ValueError):h.validate_remote_manifest({"source_repo":h.OFFICIAL_SOURCE_REPO,"version":"1.0.1","source_tag":"v1.0.2","release_id":"1"})
    def test_drafts_and_prereleases_are_refused(self):
        for kw in ({"draft":True},{"prerelease":True}):
            with self.assertRaises(ValueError):us._manifest_from_github_release(self.release(**kw))
    def test_release_page_from_another_repo_is_refused(self):
        with self.assertRaises(ValueError):us._manifest_from_github_release(self.release(html_url="https://github.com/attacker/LOYA/releases/tag/v1.0.1"))
        with self.assertRaises(ValueError):h.validate_remote_manifest({"source_repo":"https://github.com/emaldos/LOYA","source_owner":"attacker","version":"1.0.1","release_id":"1"})
    def test_asset_must_be_a_release_asset_of_this_tag(self):
        bad=[("https://github.com/emaldos/LOYA-x/releases/download/v1.0.1/LOYA-NG-v1.0.1.zip"),
             ("http://github.com/emaldos/LOYA/releases/download/v1.0.1/LOYA-NG-v1.0.1.zip"),
             ("https://github.com/emaldos/LOYA/archive/refs/tags/v1.0.1.zip"),
             ("https://codeload.github.com/emaldos/LOYA/zip/refs/tags/v1.0.1"),
             ("https://github.com/emaldos/LOYA/releases/download/v0.9.0/LOYA-NG-v1.0.1.zip"),
             ("https://github.com/emaldos/LOYA/releases/download/v1.0.1/../../x.zip")]
        for url in bad:
            rel=self.release(assets=[{"name":"LOYA-NG-v1.0.1.zip","size":10,"browser_download_url":url}])
            with self.assertRaises(ValueError,msg=url):us._manifest_from_github_release(rel)
        self.assertTrue(h.is_official_package_url("https://api.github.com/repos/emaldos/LOYA/releases/assets/123"))
        self.assertFalse(h.is_official_package_url("https://api.github.com/repos/emaldos/LOYA/zipball/v1.0.1"))
    def test_redirect_hosts(self):
        self.assertTrue(h.is_allowed_download_redirect_url("https://release-assets.githubusercontent.com/x"))
        self.assertTrue(h.is_allowed_download_redirect_url("https://objects.githubusercontent.com/x"))
        self.assertFalse(h.is_allowed_download_redirect_url("http://objects.githubusercontent.com/x"))
        self.assertFalse(h.is_allowed_download_redirect_url("https://evil.example/x"))
    def test_asset_choice(self):
        other={"name":"notes.zip","size":1,"browser_download_url":"https://github.com/emaldos/LOYA/releases/download/v1.0.1/notes.zip"}
        main=self.release()["assets"][0]
        m=us._manifest_from_github_release(self.release(assets=[other,main]))
        self.assertEqual("LOYA-NG-v1.0.1.zip",m["asset_name"])
        m=us._manifest_from_github_release(self.release(assets=[]))
        self.assertEqual("",m["asset_url"])
    def test_too_large_release_is_refused(self):
        a=dict(self.release()["assets"][0]);a["size"]=h.MAX_PACKAGE_BYTES+1
        with self.assertRaises(ValueError):us._manifest_from_github_release(self.release(assets=[a]))
    def test_sha_sources(self):
        name="LOYA-NG-v1.0.1.zip"
        self.assertEqual("b"*64,h.parse_sha256_listing(f"{'c'*64}  other.zip\n{'b'*64}  {name}\n",name))
        self.assertEqual("b"*64,h.parse_sha256_listing(f"{'b'*64} *{name}",name))
        self.assertEqual("d"*64,h.sha256_from_release_body(f"Notes\n\nSHA256: `{'d'*64}`",name))
        self.assertEqual("d"*64,h.sha256_from_release_body(f"SHA-256 ({name}): {'d'*64}",name))
        self.assertEqual("",h.sha256_from_release_body(f"SHA-256 (other.zip): {'d'*64}",name))
        with self.assertRaises(ValueError):h.sha256_from_release_body(f"SHA256: {'d'*64}\nSHA256: {'e'*64}",name)
    def test_conflicting_or_missing_sha_is_refused(self):
        with self.assertRaises(us.UpdateError) as cm:us.resolve_expected_sha256({"digest_sha256":"a"*64,"body_sha256":"b"*64})
        self.assertEqual("integrity",cm.exception.kind)
        with self.assertRaises(us.UpdateError):us.resolve_expected_sha256({})
        self.assertEqual("a"*64,us.resolve_expected_sha256({"digest_sha256":"a"*64,"body_sha256":"a"*64}))
class HttpErrorTests(unittest.TestCase):
    def test_error_kinds(self):
        e404=urllib.error.HTTPError("u",404,"nf",{},None)
        self.assertEqual("no_release",us._describe_error(e404,"x").kind)
        e403=urllib.error.HTTPError("u",403,"rl",{"X-RateLimit-Remaining":"0","X-RateLimit-Reset":"2000000000"},None)
        self.assertEqual("rate_limited",us._describe_error(e403,"x").kind)
        self.assertEqual("http",us._describe_error(urllib.error.HTTPError("u",500,"x",{},None),"x").kind)
        self.assertEqual("offline",us._describe_error(urllib.error.URLError(OSError("Name or service not known")),"x").kind)
        self.assertEqual("offline",us._describe_error(TimeoutError("timed out"),"x").kind)
        import ssl
        self.assertEqual("tls",us._describe_error(urllib.error.URLError(ssl.SSLError("bad cert")),"x").kind)
class ZipSafetyTests(unittest.TestCase):
    def check_bad(self,entries):
        d=tempfile.mkdtemp();p=os.path.join(d,"p.zip")
        try:
            with open(p,"wb") as f:f.write(_zip(entries))
            with self.assertRaises(ValueError):h.inspect_package_zip(p)
            with self.assertRaises(RuntimeError):ap._safe_extract(p,os.path.join(d,"out"))
            self.assertFalse(os.path.exists(os.path.join(d,"evil")))
        finally:shutil.rmtree(d,ignore_errors=True)
    def test_traversal_absolute_and_drive_paths(self):
        for name in ("../evil","a/../../evil","/etc/evil","C:/evil","a\\..\\evil","a/b:stream"):
            self.check_bad([(name,"x")])
    def test_symlink_entry(self):
        info=zipfile.ZipInfo("Cores/link");info.external_attr=(stat.S_IFLNK|0o777)<<16
        self.check_bad([(info,"/etc/passwd")])
    def test_duplicates_and_reserved_names(self):
        d=tempfile.mkdtemp();p=os.path.join(d,"p.zip")
        try:
            for entries in ([("Cores/A.py","1"),("cores/a.py","2")],[("Cores/con.py","x")]):
                with open(p,"wb") as f:f.write(_zip(entries))
                with self.assertRaises(ValueError):h.inspect_package_zip(p)
        finally:shutil.rmtree(d,ignore_errors=True)
    def test_zip_bomb_limits(self):
        d=tempfile.mkdtemp();p=os.path.join(d,"p.zip")
        try:
            with zipfile.ZipFile(p,"w",zipfile.ZIP_DEFLATED) as z:z.writestr("Cores/big.bin",b"\0"*(3*1024*1024))
            with self.assertRaises(ValueError):h.inspect_package_zip(p)
            with mock.patch.object(h,"MAX_ZIP_RATIO",10**9),mock.patch.object(h,"MAX_ZIP_TOTAL_BYTES",1024):
                with self.assertRaises(ValueError):h.inspect_package_zip(p)
        finally:shutil.rmtree(d,ignore_errors=True)
    @unittest.skipIf(os.name=="nt","POSIX file modes")
    def test_extract_keeps_exec_bit_but_never_setuid(self):
        d=tempfile.mkdtemp();p=os.path.join(d,"p.zip")
        try:
            a=zipfile.ZipInfo("run.sh");a.external_attr=(stat.S_IFREG|0o4777)<<16
            b=zipfile.ZipInfo("plain.txt");b.external_attr=(stat.S_IFREG|0o644)<<16
            with open(p,"wb") as f:f.write(_zip([(a,"#!/bin/sh\n"),(b,"x")]))
            ap._safe_extract(p,os.path.join(d,"out"))
            self.assertEqual(0o755,stat.S_IMODE(os.stat(os.path.join(d,"out","run.sh")).st_mode))
            self.assertEqual(0o644,stat.S_IMODE(os.stat(os.path.join(d,"out","plain.txt")).st_mode))
        finally:shutil.rmtree(d,ignore_errors=True)
    def test_valid_package_and_version_check(self):
        d=tempfile.mkdtemp();p=os.path.join(d,"p.zip")
        try:
            with open(p,"wb") as f:f.write(build_package("1.0.1",prefix="LOYA-NG-v1.0.1"))
            meta=us._validate_package_archive(p,"1.0.1")
            self.assertEqual("LOYA-NG-v1.0.1",meta["prefix"]);self.assertIn("UI/windows/main.html",meta["files"])
            with self.assertRaises(us.UpdateError):us._validate_package_archive(p,"1.0.2")
            with open(p,"wb") as f:f.write(build_package("1.0.1",files={"LOYA_Note.py":"x","Cores/Update/CurrentVersion.info":"1.0.1"}))
            with self.assertRaises(us.UpdateError):us._validate_package_archive(p,"1.0.1")
        finally:shutil.rmtree(d,ignore_errors=True)
class DownloadTests(_TempRoot):
    def setUp(self):
        super().setUp()
        self.fake=FakeGitHub().start()
        self.undo=patch_updater_for(self.fake,h)
    def tearDown(self):
        self.undo();self.fake.stop();super().tearDown()
    def test_real_validators_reject_the_fake_server(self):
        self.undo()
        try:self.assertFalse(h.is_official_package_url(self.fake.base+self.fake.asset_path("v1.0.1","LOYA-NG-v1.0.1.zip")))
        finally:self.undo=patch_updater_for(self.fake,h)
    def test_check_reports_release_and_notes(self):
        self.fake.publish("1.0.1",build_package("1.0.1"),body="## New\n- **Faster** search")
        out=us.check_for_updates(timeout=5)
        self.assertTrue(out["ok"],out["error"]);self.assertTrue(out["update_available"])
        st=us.get_update_state()
        self.assertEqual(("1.0.1","LOYA-NG-v1.0.1.zip"),(st["last_available_version"],st["asset_name"]))
        self.assertIn("Faster",st["release_notes"])
    def test_no_release_is_a_quiet_error(self):
        out=us.check_for_updates(timeout=5)
        self.assertFalse(out["ok"]);self.assertEqual("no_release",out["error_kind"])
    def test_same_or_older_version_is_not_offered(self):
        self.fake.publish("1.0.0",build_package("1.0.0"))
        self.assertFalse(us.check_for_updates(timeout=5)["update_available"])
        with self.assertRaises(us.UpdateError):us.stage_update(timeout=5)
    def test_stage_verifies_and_keeps_the_install_untouched(self):
        pkg=build_package("1.0.1")
        self.fake.publish("1.0.1",pkg)
        out=us.stage_update(timeout=5)
        self.assertEqual(hashlib.sha256(pkg).hexdigest(),out["package"]["sha256"])
        self.assertTrue(os.path.isfile(out["package"]["path"]))
        self.assertTrue(out["package"]["path"].startswith(os.path.join(self.root,"Backups","PendingUpdate")))
        self.assertEqual("1.0.0",us.get_app_version())
        self.assertEqual("1.0.1",us.staged_update_info()["version"])
    def test_sha_mismatch_is_refused_and_nothing_changes(self):
        self.fake.publish("1.0.1",build_package("1.0.1"),sha_override="0"*64)
        before=us.get_update_state()
        with self.assertRaises(us.UpdateError) as cm:us.stage_update(timeout=5)
        self.assertEqual("integrity",cm.exception.kind)
        self.assertIn("does not match",str(cm.exception))
        st=us.get_update_state()
        self.assertFalse(st["update_in_progress"]);self.assertEqual("",st["staged_version"]);self.assertEqual("1.0.0",us.get_app_version())
        stage=os.path.join(self.root,"Backups","PendingUpdate","v1.0.1")
        self.assertEqual([],[f for f in os.listdir(stage) if f.endswith(".zip") or f.endswith(".part")])
        self.assertFalse(os.path.isdir(os.path.join(self.root,"Cores","Update","OldVersions")) and os.listdir(os.path.join(self.root,"Cores","Update","OldVersions")))
        out=us.start_update_install(timeout=5)
        self.assertFalse(out["ok"]);self.assertEqual("integrity",out["error_kind"])
        self.assertEqual(before["current_version"],us.get_update_state()["current_version"])
    def test_release_without_any_sha_is_refused(self):
        self.fake.publish("1.0.1",build_package("1.0.1"),digest=False)
        with self.assertRaises(us.UpdateError) as cm:us.stage_update(timeout=5)
        self.assertIn("SHA-256",str(cm.exception))
    def test_checksum_file_and_body_sha_are_used(self):
        pkg=build_package("1.0.1");sha=hashlib.sha256(pkg).hexdigest()
        sums_path=self.fake.asset_path("v1.0.1","SHA256SUMS")
        self.fake.set(sums_path,f"{sha}  LOYA-NG-v1.0.1.zip\n".encode())
        self.fake.publish("1.0.1",pkg,digest=False,body=f"SHA256: {sha}",extra_assets=[{"name":"SHA256SUMS","size":10,"browser_download_url":self.fake.base+sums_path}])
        self.assertEqual(sha,us.stage_update(timeout=5)["package"]["sha256"])
        self.fake.set(sums_path,f"{'1'*64}  LOYA-NG-v1.0.1.zip\n".encode())
        us.discard_staged_update()
        with self.assertRaises(us.UpdateError):us.stage_update(timeout=5)
    def test_wrong_inner_version_is_refused(self):
        self.fake.publish("1.0.1",build_package("1.0.2"))
        with self.assertRaises(us.UpdateError) as cm:us.stage_update(timeout=5)
        self.assertEqual("package",cm.exception.kind)
    def test_redirect_off_github_is_refused(self):
        pkg=build_package("1.0.1")
        self.fake.publish("1.0.1",pkg)
        self.fake.set(self.fake.asset_path("v1.0.1","LOYA-NG-v1.0.1.zip"),b"",status=302,headers={"Location":f"http://localhost:{self.fake.port}/x.zip"})
        with self.assertRaises(us.UpdateError) as cm:us.stage_update(timeout=5)
        self.assertIn("GitHub",str(cm.exception))
    def test_resume_and_cancel(self):
        pkg=build_package("1.0.1",extra={"Assets/big.bin":os.urandom(600*1024)})
        self.fake.publish("1.0.1",pkg)
        m=us.fetch_latest_release_manifest(timeout=5)
        stage=os.path.join(self.root,"Backups","PendingUpdate","v1.0.1");os.makedirs(stage)
        with open(os.path.join(stage,"LOYA-NG-v1.0.1.zip.part"),"wb") as f:f.write(pkg[:1000])
        out=us._download_package(m,timeout=5,stage_dir=stage,expected_sha256=hashlib.sha256(pkg).hexdigest())
        self.assertEqual(hashlib.sha256(pkg).hexdigest(),out["sha256"])
        os.remove(out["path"])
        ev=threading.Event();ev.set()
        with self.assertRaises(us.UpdateCancelled):us._download_package(m,timeout=5,stage_dir=stage,expected_sha256=hashlib.sha256(pkg).hexdigest(),cancel=ev)
class NoticeTests(unittest.TestCase):
    now=datetime(2026,11,23,12,tzinfo=timezone.utc)
    def st(self,**kw):
        s={"current_version":"1.0.0","last_available_version":"1.0.1","update_in_progress":False,"asset_name":"LOYA-NG-v1.0.1.zip","release_notes":"- x","release_html_url":"https://github.com/emaldos/LOYA/releases/tag/v1.0.1"};s.update(kw);return s
    def cfg(self,**kw):
        c={"auto_enabled":True,"on_available":"ask","skipped_version":"","remind_version":"","remind_until":"","remind_session":""};c.update(kw);return c
    def n(self,st=None,cfg=None,session="s1",now=None):
        return us.update_notice(session_id=session,now=now or self.now,state=st or self.st(),cfg=cfg or self.cfg())
    def test_ask_mode_pops_up(self):
        out=self.n()
        self.assertTrue(out["show"]);self.assertTrue(out["popup"])
        self.assertEqual("LOYA NG 1.0.1 is available",out["title"])
    def test_disabled_up_to_date_in_progress(self):
        self.assertEqual("checks_disabled",self.n(cfg=self.cfg(auto_enabled=False))["reason"])
        self.assertEqual("up_to_date",self.n(st=self.st(last_available_version="1.0.0"))["reason"])
        self.assertEqual("up_to_date",self.n(st=self.st(last_available_version="0.9.0"))["reason"])
        self.assertEqual("in_progress",self.n(st=self.st(update_in_progress=True))["reason"])
    def test_skip_is_per_version(self):
        self.assertEqual("skipped",self.n(cfg=self.cfg(skipped_version="1.0.1"))["reason"])
        self.assertTrue(self.n(st=self.st(last_available_version="1.0.2"),cfg=self.cfg(skipped_version="1.0.1"))["show"])
    def test_remind_later_until_next_launch_or_time(self):
        until=(self.now+timedelta(hours=8)).strftime("%Y-%m-%dT%H:%M:%SZ")
        cfg=self.cfg(remind_version="1.0.1",remind_until=until,remind_session="s1")
        self.assertEqual("remind_later",self.n(cfg=cfg)["reason"])
        self.assertTrue(self.n(cfg=cfg,session="s2")["show"],"a new launch shows it again")
        self.assertTrue(self.n(cfg=cfg,now=self.now+timedelta(hours=9))["show"],"after the reminder time it shows again")
        self.assertTrue(self.n(cfg=cfg,st=self.st(last_available_version="1.0.2"))["show"],"a newer version is not postponed")
    def test_modes(self):
        self.assertFalse(self.n(cfg=self.cfg(on_available="notify"))["popup"])
        self.assertTrue(self.n(cfg=self.cfg(on_available="notify"))["show"])
        self.assertFalse(self.n(cfg=self.cfg(on_available="background"))["popup"])
    def test_rolled_back_release_is_not_pushed_again(self):
        out=self.n(st=self.st(last_update_result={"ok":False,"version":"1.0.1","message":"rolled back","acknowledged":True}))
        self.assertTrue(out["show"]);self.assertFalse(out["popup"])
        self.assertTrue(self.n(st=self.st(last_available_version="1.0.2",last_update_result={"ok":False,"version":"1.0.1","message":"x"}))["popup"])
    def test_result_is_reported_until_acknowledged(self):
        st=self.st(last_available_version="1.0.0",last_update_result={"ok":False,"message":"rolled back","version":"1.0.1","acknowledged":False})
        self.assertEqual("rolled back",self.n(st=st)["result"]["message"])
        st["last_update_result"]["acknowledged"]=True
        self.assertIsNone(self.n(st=st)["result"])
class SettingsTests(_TempRoot):
    def test_partial_saves_keep_other_keys(self):
        self.write("Data/settings.json",json.dumps({"theme":"dark","update":{"auto_enabled":True,"check_interval_hours":72}}))
        us.save_update_settings({"on_available":"background"})
        us.save_update_settings({"on_available":"bogus"})
        cfg=us.get_update_settings()
        self.assertEqual(("background",True,72),(cfg["on_available"],cfg["auto_enabled"],cfg["check_interval_hours"]))
        with open(os.path.join(self.root,"Data","settings.json")) as f:d=json.load(f)
        self.assertEqual("dark",d["theme"])
        self.assertEqual(h.OFFICIAL_SOURCE_REPO,d["update"]["repo_url"])
    def test_source_cannot_be_redirected_by_settings(self):
        self.write("Data/settings.json",json.dumps({"update":{"repo_url":"https://github.com/attacker/x","manifest_url":"https://evil.example/latest"}}))
        cfg=us.get_update_settings()
        self.assertEqual((h.OFFICIAL_SOURCE_REPO,h.GITHUB_RELEASES_API_URL),(cfg["repo_url"],cfg["manifest_url"]))
        self.assertNotIn("evil",h.GITHUB_RELEASES_API_URL)
    def test_remind_and_skip_persist(self):
        until=us.remind_later("1.0.1",session_id="abc",hours=4,now=datetime(2026,1,1,tzinfo=timezone.utc))
        cfg=us.get_update_settings()
        self.assertEqual(("1.0.1","abc","2026-01-01T04:00:00Z"),(cfg["remind_version"],cfg["remind_session"],until))
        us.skip_version("1.0.1")
        self.assertEqual("1.0.1",us.get_update_settings()["skipped_version"])
        with self.assertRaises(ValueError):us.skip_version("nope")
    def test_default_mode_is_ask(self):
        self.assertEqual("ask",us.get_update_settings()["on_available"])
class ApplyHelperTests(_TempRoot):
    """Runs apply_update.main() for real against a temp install, with a fake launcher script."""
    def make_install(self):
        files={"LOYA_Note.py":"old\n","RunNote.py":"old\n","Requirements.json":"{}\n","Assets/a.txt":"old","Cores/x.py":"old","Cores/Update/apply_update.py":"#","UI/windows/main.html":"old","UI/js/appearance-boot.js":"user-theme","UI/old_only.js":"stale","Data/notes.db":"precious","Cores/Update/state.json":json.dumps({"current_version":"1.0.0"})}
        for rel,data in files.items():self.write(rel,data)
        snap=br.create_code_snapshot(version="1.0.0",reason="test",root_dir=self.root)["path"]
        return snap
    def plan(self,pkg_bytes,snap,launcher_code=None,relaunch=True):
        stage=os.path.join(self.root,"Backups","PendingUpdate","v1.0.1");os.makedirs(stage,exist_ok=True)
        pkg=os.path.join(stage,"LOYA-NG-v1.0.1.zip")
        with open(pkg,"wb") as f:f.write(pkg_bytes)
        launcher=os.path.join(self.root,"fake_runnote.py")
        with open(launcher,"w") as f:f.write(launcher_code or "raise SystemExit(0)\n")
        plan={"root_dir":self.root,"parent_pid":0,"launcher_python":sys.executable,"launcher_script":launcher,"package_path":pkg,"expected_sha256":hashlib.sha256(pkg_bytes).hexdigest(),"requested_url":"https://github.com/emaldos/LOYA/releases/download/v1.0.1/LOYA-NG-v1.0.1.zip","stage_dir":stage,"current_version":"1.0.0","target_version":"1.0.1","manifest":{"version":"1.0.1","source_tag":"v1.0.1","source_repo":h.OFFICIAL_SOURCE_REPO},"code_snapshot":snap,"allowed_dirs":list(us._ALLOWED_UPDATE_DIRS),"allowed_files":list(us._ALLOWED_UPDATE_FILES),"required_dirs":list(us._REQUIRED_UPDATE_DIRS),"required_files":list(us._REQUIRED_UPDATE_FILES),"preserve_paths":list(us._PRESERVE_UPDATE_PATHS),"relaunch":relaunch,"confirm_timeout":30}
        p=os.path.join(stage,"update_plan.json")
        with open(p,"w") as f:json.dump(plan,f)
        return p
    def run_helper(self,plan_path):
        with mock.patch.object(sys,"argv",["apply_update.py",plan_path]):
            return ap.main()
    def read(self,rel):
        with open(os.path.join(self.root,*rel.split("/"))) as f:return f.read()
    def new_pkg(self,**extra):
        files={"LOYA_Note.py":"new\n","RunNote.py":"new\n","Requirements.json":"{}\n","Assets/a.txt":"new","Cores/x.py":"new","Cores/Update/apply_update.py":"#new","Cores/Update/CurrentVersion.info":"1.0.1\n","UI/windows/main.html":"new","UI/js/appearance-boot.js":"package-default"}
        files.update(extra);return build_package("1.0.1",files=files,prefix="LOYA-NG-v1.0.1")
    def test_apply_replaces_code_and_never_touches_data(self):
        snap=self.make_install()
        rc=self.run_helper(self.plan(self.new_pkg(),snap,relaunch=False))
        self.assertEqual(0,rc)
        self.assertEqual(("new","new\n","1.0.1\n"),(self.read("Cores/x.py"),self.read("LOYA_Note.py"),self.read("Cores/Update/CurrentVersion.info")))
        self.assertEqual("precious",self.read("Data/notes.db"))
        self.assertEqual("user-theme",self.read("UI/js/appearance-boot.js"))
        self.assertFalse(os.path.exists(os.path.join(self.root,"UI","old_only.js")))
    def test_confirmed_launch_keeps_the_update(self):
        snap=self.make_install()
        code=("import json,os\nroot=os.path.dirname(os.path.abspath(__file__))\np=os.path.join(root,'Cores','Update','state.json')\n"
              "s=json.load(open(p));s.update(update_in_progress=False,current_version='1.0.1',last_good_version='1.0.1');json.dump(s,open(p,'w'))\n")
        self.assertEqual(0,self.run_helper(self.plan(self.new_pkg(),snap,launcher_code=code)))
        self.assertEqual("new",self.read("Cores/x.py"))
        self.assertFalse(os.path.isdir(os.path.join(self.root,"Backups","PendingUpdate","v1.0.1")))
    def test_failed_launch_rolls_back(self):
        snap=self.make_install()
        rc=self.run_helper(self.plan(self.new_pkg(),snap,launcher_code="raise SystemExit(7)\n"))
        self.assertEqual(5,rc)
        self.assertEqual(("old","old\n","1.0.0\n"),(self.read("Cores/x.py"),self.read("LOYA_Note.py"),self.read("Cores/Update/CurrentVersion.info")))
        self.assertTrue(os.path.exists(os.path.join(self.root,"UI","old_only.js")))
        self.assertEqual("precious",self.read("Data/notes.db"))
        st=json.loads(self.read("Cores/Update/state.json"))
        self.assertFalse(st["update_in_progress"]);self.assertFalse(st["recovery_required"])
        self.assertFalse(st["last_update_result"]["ok"]);self.assertIn("rolled back to 1.0.0",st["last_update_result"]["message"])
    def test_tampered_package_is_refused_before_anything_changes(self):
        snap=self.make_install()
        plan=self.plan(self.new_pkg(),snap,relaunch=False)
        with open(plan) as f:pkg=json.load(f)["package_path"]
        with open(pkg,"ab") as f:f.write(b"tamper")
        self.assertEqual(4,self.run_helper(plan))
        self.assertEqual("old",self.read("Cores/x.py"))
        self.assertIn("SHA-256",json.loads(self.read("Cores/Update/state.json"))["last_update_result"]["message"])
    def test_plan_cannot_target_data_or_venvs(self):
        snap=self.make_install()
        p=self.plan(self.new_pkg(**{"Data/notes.db":"overwritten"}),snap,relaunch=False)
        with open(p) as f:plan=json.load(f)
        plan["allowed_dirs"].append("Data")
        with open(p,"w") as f:json.dump(plan,f)
        self.assertEqual(2,self.run_helper(p))
        self.assertEqual("precious",self.read("Data/notes.db"))
    def test_official_url_check_matches_the_ng_repo(self):
        self.assertTrue(ap._is_official_package_url("https://github.com/emaldos/LOYA/releases/download/v1.0.1/LOYA-NG-v1.0.1.zip"))
        self.assertFalse(ap._is_official_package_url("https://github.com/emaldos/LOYA-Note/releases/download/v1.0.1/x.zip"))
        self.assertFalse(ap._is_official_package_url("http://github.com/emaldos/LOYA/releases/download/v1.0.1/x.zip"))
class SchedulerUpdateTests(_TempRoot):
    def setUp(self):
        super().setUp()
        import LOYA_Note;self.app=LOYA_Note
    def test_os_toast_once_per_version(self):
        sent=[]
        with mock.patch.object(self.app._os_toast,"send",lambda *a:sent.append(a)),mock.patch.object(self.app,"_get_notification_settings",lambda:{"os_enabled":True}):
            self.assertTrue(self.app._notify_update_once("1.0.1"))
            self.assertFalse(self.app._notify_update_once("1.0.1"))
            self.assertTrue(self.app._notify_update_once("1.0.2"))
        self.assertEqual(2,len(sent))
    def test_background_download_only_in_background_mode(self):
        st={"current_version":"1.0.0","last_available_version":"1.0.1","asset_name":"LOYA-NG-v1.0.1.zip","update_in_progress":False}
        svc=mock.Mock(wraps=us)
        svc.get_update_state.return_value=st
        svc.staged_update_info.return_value=None
        svc.stage_update.return_value={"ok":1}
        for mode,called in (("ask",False),("notify",False),("background",True)):
            svc.stage_update.reset_mock()
            svc.get_update_settings.return_value={"auto_enabled":True,"on_available":mode,"skipped_version":""}
            with mock.patch.object(self.app,"_update_svc",svc):self.app._maybe_stage_update()
            self.assertEqual(called,svc.stage_update.called,mode)
        svc.stage_update.reset_mock();svc.stage_update.side_effect=OSError("offline")
        svc.get_update_settings.return_value={"auto_enabled":True,"on_available":"background","skipped_version":""}
        with mock.patch.object(self.app,"_update_svc",svc):
            self.assertIsNone(self.app._maybe_stage_update(now=1000))
            self.assertIsNone(self.app._maybe_stage_update(now=1001))
        self.assertEqual(1,svc.stage_update.call_count,"a failed background download waits before retrying")

class UpdateBridgeLockTests(unittest.TestCase):
    def test_no_update_ui_or_apply_while_locked(self):
        from Cores.Bridge import api
        from Cores import common_db
        a=api.Api()
        common_db.set_locked(True)
        try:
            for name in ("start_update","notice","remind_later","skip_version","check_now","update_now","restart_to_apply"):
                with self.assertRaises(ValueError,msg=name):getattr(a.update,name)(*(["1.0.1"] if name in ("remind_later","skip_version") else []))
            with mock.patch.object(us,"confirm_launch_health",return_value={"completed":False}):
                self.assertEqual({"completed":False},a.update.launch_ready())
            self.assertEqual("locked",api.UpdateAPI().notice()["reason"])
        finally:common_db.set_locked(False)
if __name__=="__main__":unittest.main()
