"""The offline CVE index: building rows from CVE records, the compressed seed (install, upgrade, integrity, xz-bomb limits),
searching, how CVE Intel uses it (search, index-only summaries, offline fallback, finding data), delta-zip limits, the in-app
updater (deltas, full download, SHA-256 and size checks, opt-in / offline / lock, cancel, audit, auto-update) and the
maintainer build tool. A local fake server stands in for GitHub; nothing real is contacted."""
import io,json,lzma,os,sqlite3,sys,tempfile,shutil,unittest,zipfile
from datetime import datetime,timezone
from _isolate import IsolatedData,ROOT
import _fake_cve as F
from Cores import common_db
from Cores.Services import cve_service as cve
from Cores.Services import cve_index as X
from Cores.Services import cve_index_updater as U
from Cores.Services import ext_agents_service as ext
from Cores.Services import security_service as security
UP="CVEProject/cvelistV5"
def base_records():
    return [F.cve_record("CVE-2021-44228","Apache Log4j2 JNDI features do not protect against attacker controlled LDAP",score=10.0,sev="CRITICAL",vector="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H",cwe="CWE-502",vendor="Apache Software Foundation",product="Apache Log4j2",published="2021-12-10T00:00:00.000Z"),
            F.cve_record("CVE-2021-44229","",desc="Buffer overflow in ExampleD allows remote attackers to crash the service. More text follows here.",score=7.5,cwe="CWE-787",vendor="Example",product="ExampleD"),
            F.cve_record("CVE-2021-4422","Nginx module request smuggling",score=5.3,sev="MEDIUM",cwe="CWE-444",vendor="F5",product="nginx"),
            F.cve_record("CVE-2024-3094","Xz: malicious code in distributed source",adp_score=5.0,vendor="n/a",product="xz"),
            F.cve_record("CVE-2025-0001","Unscored thing in Acme Router",vendor="Acme",product="Router"),
            F.cve_record("CVE-2025-0002",state="REJECTED")]
def build_index(path,records,watermark="2026-11-20T00:00:00Z",kev=("CVE-2021-44228",)):
    con=X.create(path)
    X.insert_rows(con,[X.summarize(r) for r in records])
    X.apply_kev(con,kev)
    X.finish(con,watermark,built_at="2026-11-20T01:00:00+00:00")
    con.close()
    return path
class Base(unittest.TestCase):
    def setUp(self):
        self.iso=IsolatedData();self.dir=self.iso.start()
        self.tmp=tempfile.mkdtemp(prefix="loya_cveidx_")
        self.fake=F.FakeCve().start()
        self.undo=F.patch_service(self.fake,cve)
        self._saved={"sleep":cve._sleep,"keyring":ext._keyring,"secrets":ext._secrets,"seed_dir":X.seed_dir,"now":U._now,"repo":U._app_repo,"max_raw":X.MAX_RAW_BYTES}
        cve._sleep=lambda s:None
        ext._keyring=lambda:None;ext._secrets=lambda:None
        self.seed=os.path.join(self.tmp,"seed");os.makedirs(self.seed)
        X.seed_dir=lambda:self.seed
        X._state["checked"]=None
        U._now=lambda:datetime(2026,11,23,19,30,tzinfo=timezone.utc)
        U._app_repo=lambda:"emaldos/LOYA"
        self.reset()
    def reset(self):
        cve._stamps.clear();cve._cooldown.clear();cve._REQ_LOG.clear();cve._session_key[0]=None
        U._state.update(running=False,error="",result="");U._cancel.clear()
    def tearDown(self):
        cve._sleep=self._saved["sleep"];ext._keyring=self._saved["keyring"];ext._secrets=self._saved["secrets"];X.seed_dir=self._saved["seed_dir"];U._now=self._saved["now"];U._app_repo=self._saved["repo"];X.MAX_RAW_BYTES=self._saved["max_raw"]
        X._state["checked"]=None
        self.reset();self.undo();self.fake.stop()
        common_db.set_locked(False)
        self.iso.stop();shutil.rmtree(self.tmp,ignore_errors=True)
    def make_seed(self,records=None,watermark="2026-11-20T00:00:00Z"):
        raw=build_index(os.path.join(self.tmp,"raw.sqlite"),records or base_records(),watermark)
        xz=os.path.join(self.seed,X.SEED_NAME)
        X.compress(raw,xz,1)
        info={"sha256":X.sha256_file(xz),"size":os.path.getsize(xz),"raw_size":os.path.getsize(raw),"index_version":X.INDEX_VERSION,"count":len(records or base_records()),"built_at":"2026-11-20T01:00:00+00:00","watermark":watermark}
        with open(os.path.join(self.seed,X.SEED_INFO),"w") as f:json.dump(info,f)
        X._state["checked"]=None
        return xz
    def install(self,records=None,watermark="2026-11-20T00:00:00Z"):
        build_index(X.index_path(),records or base_records(),watermark);X._state["checked"]=None
    def online(self,patch=None):return cve.set_settings({"online":True,**(patch or {})},True)
    def audit(self,event="cve_index"):return [e for e in security.list_audit_events(500) if e["event"]==event]
    def ids(self,*a,**k):return [r["id"] for r in X.search(*a,**k)]
class RowsTest(unittest.TestCase):
    def test_summarize(self):
        r=X.summarize(base_records()[0])
        self.assertEqual({"id":20210044228,"pub":20211210,"mod":20261102,"state":0,"sev":4,"score":100,"ver":31,"vec":"AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H","cwe":"502","kev":0,"title":"Apache Log4j2 JNDI features do not protect against attacker controlled LDAP","vp":"Apache Software Foundation Apache Log4j2"},r)
        r=X.summarize(base_records()[1])
        self.assertEqual("Buffer overflow in ExampleD allows remote attackers to crash the service.",r["title"])  # no CNA title: the first sentence
        self.assertEqual((3,75,"ExampleD"),(r["sev"],r["score"],r["vp"]))  # the vendor is not repeated when the product name already starts with it
        r=X.summarize(base_records()[3])
        self.assertEqual((2,50,"xz"),(r["sev"],r["score"],r["vp"]))  # the ADP score when the CNA gave none; "n/a" vendors dropped
        r=X.summarize(base_records()[4]);self.assertEqual((0,None,0,""),(r["sev"],r["score"],r["ver"],r["vec"]))
        r=X.summarize(base_records()[5])
        self.assertEqual((1,"Rejected: This CVE ID was rejected because it is a duplicate.",None),(r["state"],r["title"],r["score"]))
    def test_untrusted_text_is_cleaned_and_capped(self):
        rec=F.cve_record("CVE-2026-0009","Bad\x00 title‮ with <script>alert(1)</script> "+"x"*500,vendor="V\x1b[31m",product="P\r\nQ",score=11,vector="javascript:alert(1) x")
        r=X.summarize(rec)
        self.assertLessEqual(len(r["title"]),X.TITLE_MAX);self.assertNotRegex(r["title"]+r["vp"],r"[\x00-\x1f‮]")
        self.assertIn("<script>",r["title"])  # kept as inert text; the UI escapes it
        self.assertEqual((None,0,""),(r["score"],r["sev"],r["vec"]))  # out-of-range score and a junk vector are dropped
        for bad in (None,"x",{},{"cveMetadata":{"cveId":"CVE-1-1"}},{"cveMetadata":{"cveId":"<img>"}}):self.assertIsNone(X.summarize(bad))
    def test_id_codec(self):
        for cid in ("CVE-1999-0001","CVE-2021-44228","CVE-2026-129448","CVE-2026-1234567"):self.assertEqual(cid,X.int_to_id(X.id_to_int(cid)))
        self.assertIsNone(X.id_to_int("CVE-2021-1"));self.assertIsNone(X.id_to_int("nope"))
class SeedTest(Base):
    def test_installs_from_the_bundled_seed_on_first_use(self):
        self.assertEqual(False,X.info()["installed"]);self.assertEqual([],X.search("log4j"))
        self.make_seed()
        info=X.ensure_installed()
        self.assertEqual((True,6,"2026-11-20T00:00:00Z",X.INDEX_VERSION,5,4),(info["installed"],info["count"],info["watermark"],info["version"],info["published"],info["scored"]))
        self.assertTrue(os.path.isfile(os.path.join(self.dir,"cve_index","cve_index.sqlite")))
        self.assertFalse(os.path.exists(X.index_path()+".new"))
        self.assertEqual(["CVE-2021-44228"],self.ids("log4j"))
        self.assertEqual({"installed":True,"count":6,"built_at":"2026-11-20T01:00:00+00:00","watermark":"2026-11-20T00:00:00Z"},cve.status()["index"])
        self.assertEqual([],self.fake.hits)  # no network involved, and online lookups are still off
    def test_a_newer_seed_replaces_the_index_and_an_older_one_does_not(self):
        self.make_seed();X.ensure_installed()
        self.make_seed(base_records()+[F.cve_record("CVE-2026-0500","Brand new thing")],"2026-11-22T00:00:00Z")
        self.assertEqual(7,X.ensure_installed()["count"])
        self.make_seed(base_records()[:2],"2026-11-01T00:00:00Z")  # e.g. the index was updated in-app after this seed was built
        self.assertEqual((7,"2026-11-22T00:00:00Z"),(X.ensure_installed()["count"],X.info()["watermark"]))
    def test_a_bad_seed_never_replaces_a_good_index(self):
        self.make_seed();X.ensure_installed()
        xz=self.make_seed(base_records()[:1],"2026-11-25T00:00:00Z")
        with open(xz,"r+b") as f:f.seek(40);f.write(b"\x00\x00\x00\x00")  # corrupted in transit: SHA-256 no longer matches
        self.assertEqual(6,X.ensure_installed()["count"])
        with self.assertRaises(X.IndexError_):X.install_xz(xz,X.index_path(),json.load(open(os.path.join(self.seed,X.SEED_INFO)))["sha256"])
        junk=os.path.join(self.tmp,"junk.xz")
        with open(junk,"wb") as f:f.write(b"not xz at all")
        with self.assertRaises(X.IndexError_):X.install_xz(junk)
        notdb=os.path.join(self.tmp,"notdb.xz")
        with lzma.open(notdb,"wb") as f:f.write(b"hello"*1000)
        with self.assertRaises(X.IndexError_):X.install_xz(notdb)
        empty=os.path.join(self.tmp,"empty.sqlite");c=X.create(empty);X.finish(c,"2026-11-26T00:00:00Z");c.close()
        X.compress(empty,empty+".xz",1)
        with self.assertRaises(X.IndexError_):X.install_xz(empty+".xz")
        self.assertEqual(6,X.info()["count"]);self.assertEqual(["CVE-2021-44228"],self.ids("log4j"))
        self.assertEqual([],[n for n in os.listdir(X.index_dir()) if n.endswith(".new")])
    def test_xz_bomb_is_refused(self):
        bomb=os.path.join(self.tmp,"bomb.xz")
        with lzma.open(bomb,"wb",preset=1) as f:
            for _ in range(64):f.write(b"\x00"*1024*1024)
        self.assertLess(os.path.getsize(bomb),100_000)
        with self.assertRaises(X.IndexError_) as cm:X.install_xz(bomb)
        self.assertIn("larger than expected",str(cm.exception))
        X.MAX_RAW_BYTES=1024
        self.make_seed()
        self.assertFalse(X.ensure_installed()["installed"])
    def test_wrong_format_version_is_refused(self):
        raw=build_index(os.path.join(self.tmp,"v.sqlite"),base_records())
        c=sqlite3.connect(raw);c.execute("UPDATE meta SET value='99' WHERE key='index_version'");c.commit();c.close()
        with self.assertRaises(X.IndexError_):X.validate(raw)
class SearchTest(Base):
    def setUp(self):
        super().setUp();self.install()
    def test_ids_prefixes_keywords_and_filters(self):
        self.assertEqual(["CVE-2021-44228"],self.ids("",ids=["cve-2021-44228","CVE-1999-9999"]))
        self.assertEqual(["CVE-2021-44229","CVE-2021-44228","CVE-2021-4422"],self.ids("2021-4422"))
        self.assertEqual(["CVE-2021-44229","CVE-2021-44228","CVE-2021-4422"],self.ids("CVE-2021-442"))
        self.assertEqual(["CVE-2021-44229","CVE-2021-44228"],self.ids("cve-2021-4422",exclude=["CVE-2021-4422"]))
        self.assertEqual(["CVE-2025-0002","CVE-2025-0001"],self.ids("CVE-2025"))
        self.assertEqual(["CVE-2021-44228"],self.ids("apache log4"))          # all words, last one as a prefix
        self.assertEqual(["CVE-2021-44228"],self.ids("LDAP Apache"))          # any order, case-insensitive
        self.assertEqual(["CVE-2025-0001"],self.ids("acme router"))           # vendor / product
        self.assertEqual(["CVE-2021-4422"],self.ids("nginx"))
        self.assertEqual([],self.ids("apache nginx"))
        self.assertEqual([],self.ids('") OR 1=1 --'));self.assertEqual([],self.ids("title:* NEAR(a b)"))  # query text is never FTS syntax
        self.assertEqual(["CVE-2021-44229","CVE-2021-44228"],self.ids("",filters={"severity":"high"}))
        self.assertEqual(["CVE-2021-44228"],self.ids("",filters={"severity":"critical"}))
        self.assertEqual(["CVE-2021-44228"],self.ids("",filters={"kev_only":True}))
        self.assertEqual(["CVE-2024-3094"],self.ids("",filters={"year":2024}))
        self.assertEqual(["CVE-2021-4422"],self.ids("request",filters={"severity":"medium","year":2021}))
        self.assertEqual(6,len(self.ids("")));self.assertEqual(2,len(self.ids("",limit=2)))
    def test_row_shape(self):
        r=X.get("CVE-2021-44228")
        self.assertEqual({"id":"CVE-2021-44228","title":"Apache Log4j2 JNDI features do not protect against attacker controlled LDAP","description":"","severity":"critical","score":10.0,"cvss_version":"3.1","vector":"CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H",
            "kev":True,"epss":None,"published":"2021-12-10","modified":"2026-11-02","fetched_at":"2026-11-20T01:00:00+00:00","origin":"index","index_only":True,"state":"published","cwe":"CWE-502","cwes":["CWE-502"],"vendors":"Apache Software Foundation Apache Log4j2"},r)
        self.assertEqual("rejected",X.get("CVE-2025-0002")["state"]);self.assertIsNone(X.get("CVE-1999-0001"));self.assertIsNone(X.get("junk"))
    def test_like_fallback_without_fts(self):
        c=sqlite3.connect(X.index_path());c.execute("DROP TABLE cve_fts");c.commit();c.close()
        self.assertEqual(["CVE-2021-44228"],self.ids("apache log4"));self.assertEqual([],self.ids("100%_x"))
    def test_cve_intel_search_uses_the_index_after_the_cache(self):
        self.fake.json("/rest/json/cves/2.0",F.nvd_page([F.nvd_cve()]));self.fake.json("/kev.json",F.kev_catalog());self.fake.json("/data/v1/epss",F.epss([]))
        self.online();cve.lookup("CVE-2021-44228");cve.set_settings({"online":False})
        n=len(self.fake.hits)
        res=cve.search("2021-4422")
        self.assertEqual(("cache",{"used":True,"count":6}),(res["origin"],res["index"]))
        self.assertEqual([("CVE-2021-44228","cache",False),("CVE-2021-44229","index",True),("CVE-2021-4422","index",True)],[(r["id"],r["origin"],r["index_only"]) for r in res["results"]])
        base={"id","title","description","severity","score","cvss_version","kev","epss","published","modified","fetched_at","origin","index_only"}
        self.assertEqual(base,set(res["results"][0]));self.assertEqual(base|{"state","cwe","vendors"},set(res["results"][1]))  # the cached-row shape Reporting relies on is unchanged
        self.assertEqual(["CVE-2021-44228"],[r["id"] for r in cve.search("log4j")["results"]])  # in both: listed once, from the cache
        self.assertEqual(["CVE-2021-4422"],[r["id"] for r in cve.search("please look at cve-2021-4422")["results"]])
        self.assertEqual(["CVE-2021-44228"],[r["id"] for r in cve.search("",20,{"kev_only":True})["results"]])
        self.assertEqual(["CVE-2021-44228","CVE-2021-44229"],[r["id"] for r in cve.search("",20,{"severity":"high"})["results"]])
        res=cve.search("")
        self.assertEqual((["CVE-2021-44228"],False),([r["id"] for r in res["results"]],res["index"]["used"]))  # no query: the saved CVEs only
        self.assertEqual(n,len(self.fake.hits))
    def test_index_only_summary_and_offline_fallbacks(self):
        r=cve.index_get("cve-2021-44229")
        self.assertEqual(("CVE-2021-44229",True,True,"index",True,"high",7.5,"published"),(r["id"],r["partial"],r["index_only"],r["origin"],r["stale"],r["severity"],r["score"],r["state"]))
        self.assertEqual({"version":"3.1","vector":"CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H","score":7.5,"severity":"high","source":"CVE.org"},r["cvss"]["v31"])
        self.assertEqual(([{"id":"CVE-787","name":"Out-of-bounds Write"}] if False else "CWE-787"),r["cwes"][0]["id"]);self.assertTrue(r["cwes"][0]["name"])
        self.assertEqual(["CWE-787"],[g["cwe"] for g in r["protect"]["generic"]]);self.assertEqual([],r["protect"]["vendor"])
        self.assertEqual("https://nvd.nist.gov/vuln/detail/CVE-2021-44229",r["links"]["nvd"]);self.assertIn("offline CVE index",r["warning"])
        self.assertEqual(set(cve.parse_nvd(F.nvd_cve()))|{"protect","links","origin","fetched_at","stale","warning","index_only","state"},set(r))  # same shape as a full record
        self.assertTrue(cve.index_get("CVE-2021-44228")["kev"]["in_kev"])
        with self.assertRaises(cve.CveError) as cm:cve.index_get("CVE-1999-0001")
        self.assertEqual("not_found",cm.exception.code)
        # online lookups off: lookup and to_finding answer from the index instead of failing
        r=cve.lookup("CVE-2021-44229")
        self.assertEqual(("index",True),(r["origin"],r["partial"]));self.assertIn("Online lookups are off",r["warning"])
        f=cve.to_finding("CVE-2021-44229")
        self.assertEqual(("CVE-2021-44229: Buffer overflow in ExampleD allows remote attackers to crash the service.","high","CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",7.5,"CWE-787","index"),(f["title"],f["severity"],f["cvss_vector"],f["cvss_score"],f["cwe"],f["origin"]))
        with self.assertRaises(cve.CveError) as cm:cve.lookup("CVE-1999-0001")
        self.assertEqual("disabled",cm.exception.code)
        self.assertEqual([],self.fake.hits)
        common_db.set_locked(True)
        for call in (lambda:cve.index_get("CVE-2021-44229"),lambda:cve.search("log4j"),U.status,U.start):
            with self.assertRaises(cve.CveError) as cm:call()
            self.assertEqual("locked",cm.exception.code)
    def test_online_lookup_still_fetches_the_full_record(self):
        self.fake.json("/rest/json/cves/2.0",F.nvd_page([F.nvd_cve("CVE-2021-44229",kev=False)]));self.fake.json("/kev.json",F.kev_catalog());self.fake.json("/data/v1/epss",F.epss([]))
        self.online()
        r=cve.lookup("CVE-2021-44229")
        self.assertEqual(("live",False),(r["origin"],r["partial"]));self.assertNotIn("index_only",r)
class DeltaZipTest(Base):
    def test_reads_records_and_skips_junk(self):
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,"w",zipfile.ZIP_DEFLATED) as z:
            z.writestr("deltaCves/CVE-2026-0001.json",json.dumps(F.cve_record("CVE-2026-0001","One")))
            z.writestr("deltaCves/CVE-2026-0002.json","{not json")
            z.writestr("deltaCves/readme.txt","hi");z.writestr("../../evil/CVE-2026-0003.json",json.dumps(F.cve_record("CVE-2026-0003","Path is only a name here")))
            z.writestr("deltaCves/CVE-2026-0004.json",json.dumps({"cveMetadata":{"cveId":"CVE-2026-9999999999"}}))
        rows=X.read_delta_zip(buf.getvalue())
        self.assertEqual(["CVE-2026-0001","CVE-2026-0003"],[X.int_to_id(r["id"]) for r in rows])  # nothing is ever extracted to disk, so a hostile path is harmless
    def test_limits(self):
        with self.assertRaises(X.IndexError_):X.read_delta_zip(b"PK not a zip")
        saved=(X.MAX_DELTA_ENTRIES,X.MAX_DELTA_FILE_BYTES,X.MAX_DELTA_TOTAL_BYTES)
        try:
            data=F.delta_zip([F.cve_record(f"CVE-2026-{1000+i}","T") for i in range(5)])
            X.MAX_DELTA_ENTRIES=4
            with self.assertRaises(X.IndexError_):X.read_delta_zip(data)
            X.MAX_DELTA_ENTRIES=saved[0];X.MAX_DELTA_TOTAL_BYTES=600
            with self.assertRaises(X.IndexError_):X.read_delta_zip(data)
            X.MAX_DELTA_TOTAL_BYTES=saved[2];X.MAX_DELTA_FILE_BYTES=100
            with self.assertRaises(X.IndexError_):X.read_delta_zip(data)
            X.MAX_DELTA_FILE_BYTES=saved[1]
            buf=io.BytesIO()
            with zipfile.ZipFile(buf,"w",zipfile.ZIP_DEFLATED) as z:z.writestr("deltaCves/CVE-2026-0001.json",b" "*(3*1024*1024))
            with self.assertRaises(X.IndexError_) as cm:X.read_delta_zip(buf.getvalue())
            self.assertIn("zip bomb",str(cm.exception))
        finally:X.MAX_DELTA_ENTRIES,X.MAX_DELTA_FILE_BYTES,X.MAX_DELTA_TOTAL_BYTES=saved
    def test_apply_delta_updates_rows_fts_and_keeps_kev(self):
        self.install()
        rows=[X.summarize(F.cve_record("CVE-2021-44228","Apache Log4j2 remote code execution (renamed)",score=10.0,sev="CRITICAL")),X.summarize(F.cve_record("CVE-2026-0700","Fresh Tomcat issue",score=8.1))]
        self.assertEqual((1,1),X.apply_delta(rows,"2026-11-21T23:59:59Z"))
        self.assertEqual(["CVE-2021-44228"],self.ids("renamed"));self.assertEqual([],self.ids("jndi"));self.assertEqual(["CVE-2026-0700"],self.ids("tomcat"))
        self.assertTrue(X.get("CVE-2021-44228")["kev"])  # a record update does not clear the KEV flag
        info=X.info();self.assertEqual((7,"2026-11-21T23:59:59Z","2026-11-20T01:00:00+00:00"),(info["count"],info["watermark"],info["built_at"]))
        X.apply_delta([],None,["CVE-2026-0700"])
        self.assertEqual(["CVE-2026-0700"],self.ids("",filters={"kev_only":True}))
        with self.assertRaises(Exception):X.apply_delta([{"id":1}],"2026-11-22T23:59:59Z")  # a bad row rolls the whole delta back
        self.assertEqual("2026-11-21T23:59:59Z",X.info()["watermark"])
class UpdaterTest(Base):
    def publish_days(self):
        F.gh_release(self.fake,UP,"cve_2026-11-20_at_end_of_day","2026-11-20_delta_CVEs_at_end_of_day.zip",F.delta_zip([F.cve_record("CVE-2026-2001","Day twenty item",score=9.1,sev="CRITICAL")]))
        F.gh_release(self.fake,UP,"cve_2026-11-21_at_end_of_day","2026-11-21_delta_CVEs_at_end_of_day.zip",F.delta_zip([F.cve_record("CVE-2026-2002","Day twenty-one item"),F.cve_record("CVE-2021-44229","ExampleD overflow (updated)",score=9.8,sev="CRITICAL")]))
        F.gh_release(self.fake,UP,"cve_2026-11-22_at_end_of_day","2026-11-22_delta_CVEs_at_end_of_day.zip",F.delta_zip([]))
        F.gh_release(self.fake,UP,"cve_2026-11-23_1800Z","2026-11-23_delta_CVEs_at_1800Z.zip",F.delta_zip([F.cve_record("CVE-2026-2003","Today item")]))
    def test_plan(self):
        now=datetime(2026,11,23,19,30,tzinfo=timezone.utc)
        self.assertEqual(["cve_2026-11-20_at_end_of_day","cve_2026-11-21_at_end_of_day","cve_2026-11-22_at_end_of_day"],[s[0] for s in U.plan("2026-11-20T00:00:00Z",now)])
        self.assertEqual(["cve_2026-11-22_at_end_of_day"],[s[0] for s in U.plan("2026-11-21T23:59:59Z",now)])
        self.assertEqual([],U.plan("2026-11-23T05:00:00Z",now));self.assertIsNone(U.plan("garbage",now))
    def test_delta_update(self):
        self.install();self.publish_days();self.online({"sources":{"kev":False}})
        out=U.start(wait=True)
        self.assertEqual("",U._state["error"],out)
        self.assertIn("3 new and 1 changed CVEs",out["message"]);self.assertIn("data up to 2026-11-23T18:00:00Z",out["message"])
        st=U.status()
        self.assertEqual((True,9,"2026-11-23T18:00:00Z",False,"",True,"off"),(st["installed"],st["count"],st["watermark"],st["updating"],st["error"],st["can_update"],st["auto"]))
        self.assertTrue(st["last_update"]);self.assertEqual({"phase":"","done":0,"total":0,"message":""},st["progress"])
        self.assertEqual(["CVE-2026-2003"],self.ids("today"));self.assertEqual("critical",X.get("CVE-2021-44229")["severity"])
        a=self.audit()
        self.assertTrue(a[0]["success"]);self.assertIn("2026-11-20T00:00:00Z -> 2026-11-23T18:00:00Z",a[0]["detail"])
        # only public release paths were requested, with nothing personal in them
        paths=self.fake.paths()
        self.assertTrue(all(p.startswith(("/ghapi/repos/CVEProject/cvelistV5/releases/tags/cve_2026-11-","/gh/CVEProject/cvelistV5/releases/download/cve_2026-11-")) for p in paths),paths)
        self.assertTrue(all(q=={} for _p,q,_h in self.fake.hits));self.assertFalse(any("apikey" in h or "authorization" in h or "cookie" in h for _p,_q,h in self.fake.hits))
        n=len(self.fake.hits)
        out=U.start(wait=True)  # again: nothing new - only the next hour is asked for, no file is downloaded twice
        self.assertIn("already up to date",out["message"])
        self.assertEqual(["/ghapi/repos/CVEProject/cvelistV5/releases/tags/cve_2026-11-23_1900Z"],self.fake.paths()[n:])
    def test_integrity_failures_leave_the_index_untouched(self):
        self.install();self.publish_days();self.online({"sources":{"kev":False}})
        good=F.delta_zip([F.cve_record("CVE-2026-2001","Day twenty item")]);evil=F.delta_zip([F.cve_record("CVE-2026-6666","Evil swapped file")])
        cases={"sha":dict(digest="0"*64),"size":dict(size=len(good)+1),"nodigest":dict(digest=False),"host":dict(url="https://evil.example/x.zip"),"otherrepo":dict(url=self.fake.base+"/gh/someone/else/releases/download/t/x.zip"),"huge":dict(size=U.MAX_DELTA_ZIP_BYTES+1)}
        for name,kw in cases.items():
            self.reset()
            F.gh_release(self.fake,UP,"cve_2026-11-20_at_end_of_day","2026-11-20_delta_CVEs_at_end_of_day.zip",good,**kw)
            if name=="sha":self.fake.routes["/gh/CVEProject/cvelistV5/releases/download/cve_2026-11-20_at_end_of_day/2026-11-20_delta_CVEs_at_end_of_day.zip"]=lambda q,h,p:(200,evil,{})
            out=U.start(wait=True)
            self.assertTrue(U._state["error"],name);self.assertEqual((6,"2026-11-20T00:00:00Z"),(X.info()["count"],X.info()["watermark"]),name)
            self.assertFalse(self.audit()[0]["success"],name)
        self.assertNotIn("/x.zip",self.fake.paths())  # a foreign address is refused before it is contacted
        self.reset()
        F.gh_release(self.fake,UP,"cve_2026-11-20_at_end_of_day","2026-11-20_delta_CVEs_at_end_of_day.zip",b"PK\x03\x04 broken")
        U.start(wait=True);self.assertIn("not a readable zip",U._state["error"])
        self.reset()
        del self.fake.routes["/ghapi/repos/CVEProject/cvelistV5/releases/tags/cve_2026-11-20_at_end_of_day"]
        U.start(wait=True);self.assertIn("has not published the update for 2026-11-20",U._state["error"])
    def test_a_partial_run_keeps_the_days_already_applied(self):
        self.install();self.publish_days();self.online({"sources":{"kev":False}})
        del self.fake.routes["/ghapi/repos/CVEProject/cvelistV5/releases/tags/cve_2026-11-21_at_end_of_day"]
        U.start(wait=True)
        self.assertTrue(U._state["error"]);self.assertEqual((7,"2026-11-20T23:59:59Z"),(X.info()["count"],X.info()["watermark"]))
    def test_opt_in_offline_only_and_lock(self):
        self.install();self.publish_days()
        for setup,code in ((lambda:None,"disabled"),(lambda:(self.online(),cve.set_settings({"offline_only":True})),"offline_only")):
            setup()
            with self.assertRaises(cve.CveError) as cm:U.start()
            self.assertEqual(code,cm.exception.code)
            self.assertFalse(U.status()["can_update"])
            cve.set_settings({"index_auto":"daily"});self.assertFalse(U.auto_tick())
        self.assertEqual([],self.fake.hits)
        cve.set_settings({"offline_only":False})
        common_db.set_locked(True)
        with self.assertRaises(cve.CveError) as cm:U.start()
        self.assertEqual("locked",cm.exception.code)
        common_db.set_locked(False)
        # locked in the middle of a run: the next request is refused
        calls={"n":0}
        orig=self.fake.routes["/ghapi/repos/CVEProject/cvelistV5/releases/tags/cve_2026-11-20_at_end_of_day"]
        def lock_then(q,h,p):
            common_db.set_locked(True);return orig(q,h,p)
        self.fake.routes["/ghapi/repos/CVEProject/cvelistV5/releases/tags/cve_2026-11-20_at_end_of_day"]=lock_then
        U.start(wait=True)
        common_db.set_locked(False)
        self.assertIn("locked",U._state["error"]);self.assertEqual(6,X.info()["count"])
    def test_cancel(self):
        self.install();self.publish_days();self.online({"sources":{"kev":False}})
        orig=self.fake.routes["/ghapi/repos/CVEProject/cvelistV5/releases/tags/cve_2026-11-21_at_end_of_day"]
        def cancel_then(q,h,p):
            U._cancel.set();return orig(q,h,p)
        self.fake.routes["/ghapi/repos/CVEProject/cvelistV5/releases/tags/cve_2026-11-21_at_end_of_day"]=cancel_then
        self.assertEqual({"cancelled":False},U.cancel())
        U.start(wait=True)
        self.assertIn("cancelled",U._state["error"]);self.assertEqual("2026-11-20T23:59:59Z",X.info()["watermark"])
        self.assertEqual([],[a for a in self.audit() if "cancel" in a["detail"]])
    def publish_full(self,records=None,watermark="2026-11-22T00:00:00Z",**kw):
        raw=build_index(os.path.join(self.tmp,"full.sqlite"),records or base_records()+[F.cve_record("CVE-2026-3000","From the full index")],watermark)
        xz=os.path.join(self.tmp,"full.xz");X.compress(raw,xz,1)
        with open(xz,"rb") as f:data=f.read()
        return F.gh_release(self.fake,"emaldos/LOYA","v1.0.0","cve-index-20261122.sqlite.xz",data,api_path="/ghapi/repos/emaldos/LOYA/releases/latest",**kw)
    def test_full_download_when_there_is_no_index_then_deltas(self):
        self.publish_full();self.publish_days();self.online({"sources":{"kev":False}})
        self.assertFalse(U.status()["installed"])
        out=U.start(wait=True)
        self.assertEqual("",U._state["error"],out);self.assertTrue(out["message"].startswith("Full index installed, then 1 new"))
        self.assertEqual((8,"2026-11-23T18:00:00Z"),(X.info()["count"],X.info()["watermark"]))
        self.assertEqual(["CVE-2026-3000"],self.ids("full index"));self.assertIn("full download",self.audit()[0]["detail"])
        self.assertEqual([],[n for n in os.listdir(X.index_dir()) if n.endswith((".part",".new"))])
    def test_full_download_when_the_index_is_too_old_and_bad_downloads_keep_the_old_one(self):
        self.install(watermark="2026-01-01T00:00:00Z");self.online({"sources":{"kev":False}})
        U.start(wait=True);self.assertIn("No published CVE index",U._state["error"])
        for kw in (dict(digest="1"*64),dict(digest=False),dict(size=5)):
            self.reset();self.publish_full(**kw)
            U.start(wait=True)
            self.assertTrue(U._state["error"]);self.assertEqual((6,"2026-01-01T00:00:00Z"),(X.info()["count"],X.info()["watermark"]))
        self.reset()
        F.gh_release(self.fake,"emaldos/LOYA","v1.0.0","cve-index-20261122.sqlite.xz",b"\xfd7zXZ\x00 truncated",api_path="/ghapi/repos/emaldos/LOYA/releases/latest")
        U.start(wait=True);self.assertIn("damaged",U._state["error"]);self.assertEqual(6,X.info()["count"])
        self.reset();self.publish_full();self.publish_days()
        U.start(wait=True);self.assertEqual("",U._state["error"]);self.assertEqual("2026-11-23T18:00:00Z",X.info()["watermark"])
    def test_kev_flags_follow_the_catalog(self):
        self.install();self.publish_days();self.online()
        self.fake.json("/kev.json",F.kev_catalog([F.kev_entry("CVE-2021-4422"),F.kev_entry("CVE-2026-2001")]))
        U.start(wait=True)
        self.assertEqual("",U._state["error"]);self.assertEqual(["CVE-2026-2001","CVE-2021-4422"],self.ids("",filters={"kev_only":True}))
    def test_auto_update_setting_and_schedule(self):
        for bad in ("hourly",1,None,True):
            with self.assertRaises(cve.CveError):cve.set_settings({"index_auto":bad})
        self.install();self.publish_days();self.online({"sources":{"kev":False}})
        self.assertFalse(U.auto_tick())  # off by default
        self.assertEqual("weekly",cve.set_settings({"index_auto":"weekly"})["index_auto"])
        self.assertIn("index_auto: 'off' -> 'weekly'",self.audit("cve_settings")[0]["detail"])
        self.assertEqual("weekly",U.status()["auto"])
        cve.tick()  # the UI's poller is what triggers it
        U._state["thread"].join(20)
        self.assertEqual("2026-11-23T18:00:00Z",X.info()["watermark"])
        self.assertFalse(U.auto_tick())  # not again within the week
        with sqlite3.connect(common_db.db_path()) as con:con.execute("UPDATE CveMeta SET value='2026-11-10T00:00:00+00:00' WHERE key='index_last_attempt'")
        cve.set_settings({"index_auto":"daily"})
        self.assertTrue(U.auto_tick());U._state["thread"].join(20)
class BuildToolTest(Base):
    def tool(self):
        sys.path.insert(0,os.path.join(ROOT,"tools"))
        try:
            import build_cve_index as T
        finally:sys.path.pop(0)
        return T
    def test_offline_build_from_a_baseline_zip_and_packaging(self):
        T=self.tool()
        inner=io.BytesIO()
        with zipfile.ZipFile(inner,"w",zipfile.ZIP_DEFLATED) as z:
            for r in base_records():
                cid=r["cveMetadata"]["cveId"];z.writestr(f"cves/{cid[4:8]}/x/{cid}.json",json.dumps(r))
            z.writestr("cves/delta.json","{}");z.writestr("cves/deltaLog.json","[]")
        outer=os.path.join(self.tmp,"2026-11-20_all_CVEs_at_midnight.zip.zip")
        with zipfile.ZipFile(outer,"w",zipfile.ZIP_DEFLATED) as z:z.writestr("cves.zip",inner.getvalue())
        out=os.path.join(self.tmp,"out")
        saved=T.MIN_RECORDS
        try:
            with self.assertRaises(SystemExit):T.main(["--out",out,"--baseline-zip",outer,"--baseline-date","2026-11-20","--offline","--preset","1"])  # refuses a truncated build
            T.MIN_RECORDS=3
            pkg=os.path.join(self.tmp,"LOYA-NG-v9.9.9.zip")
            with zipfile.ZipFile(pkg,"w") as z:z.writestr("LOYA-NG-v9.9.9/Assets/logox.png","png");z.writestr("LOYA-NG-v9.9.9/LOYA_Note.py","x")
            self.assertEqual(0,T.main(["--out",out,"--baseline-zip",outer,"--baseline-date","2026-11-20","--offline","--preset","1","--install-seed","--add-to-package",pkg]))
        finally:T.MIN_RECORDS=saved
        info=json.load(open(os.path.join(out,X.SEED_INFO)))
        self.assertEqual((6,5,4,"2026-11-20T00:00:00Z",X.INDEX_VERSION,"cve-index-20261120.sqlite.xz"),(info["count"],info["published"],info["scored"],info["watermark"],info["index_version"],info["name"]))
        asset=os.path.join(out,"cve-index-20261120.sqlite.xz")
        self.assertEqual(info["sha256"],X.sha256_file(asset));self.assertEqual(info["size"],os.path.getsize(asset))
        self.assertEqual(info["sha256"]+"  cve-index-20261120.sqlite.xz\n",open(asset+".sha256").read())
        self.assertEqual(6,X.ensure_installed()["count"])  # --install-seed put it where the app looks, and the app installs it
        self.assertEqual(["CVE-2021-44228"],self.ids("log4j"))
        with zipfile.ZipFile(pkg) as z:
            self.assertIn("LOYA-NG-v9.9.9/Assets/cve/cve-index.sqlite.xz",z.namelist());self.assertIn("LOYA-NG-v9.9.9/Assets/cve/cve-index.json",z.namelist())
        from Cores.Update import update_helpers as h
        rows=h.inspect_package_zip(pkg)  # the updater's own zip-safety gate accepts the package with the index in it
        self.assertTrue(any("cve-index.sqlite.xz" in str(r) for r in rows))
        with self.assertRaises(SystemExit):T.add_to_package(pkg,asset,os.path.join(out,X.SEED_INFO))  # never twice
    def test_the_tool_only_talks_https_to_expected_hosts(self):
        T=self.tool()
        for bad in ("http://github.com/x","https://evil.example/x","file:///etc/passwd"):
            with self.assertRaises(SystemExit):T._check_url(bad)
        T._check_url("https://github.com/CVEProject/cvelistV5/releases/download/t/f.zip")
    def test_index_files_are_git_ignored_and_the_updater_ships_assets(self):
        with open(os.path.join(ROOT,".gitignore"),encoding="utf-8") as f:ig=f.read()
        self.assertIn("Assets/cve/cve-index.sqlite.xz",ig);self.assertIn("Assets/cve/cve-index.json",ig)
        from Cores.Update import update_service as us
        self.assertIn("Assets",us._ALLOWED_UPDATE_DIRS)
if __name__=="__main__":unittest.main()
