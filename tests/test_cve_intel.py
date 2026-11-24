"""CVE Intel: parsing NVD / KEV / EPSS / CVE.org data, the opt-in and offline guards, the app lock, untrusted-text handling,
rate-limit back-off, the cache, the news feed, watchlist matching, settings (validation, persistence, audit), key storage,
finding data for Reporting and the MCP tool. No real source is contacted - a local fake server stands in for all of them."""
import json,os,sqlite3,ssl,types,unittest,urllib.error
from _isolate import IsolatedData
import _fake_cve as F
from Cores import common_db
from Cores.Services import cve_service as cve
from Cores.Services import cve_guidance as guidance
from Cores.Services import ext_agents_service as ext
from Cores.Services import security_service as security
NVD_KEY="0123abcd-4567-89ef-0123-456789abcdef"
class Base(unittest.TestCase):
    def setUp(self):
        self.iso=IsolatedData();self.dir=self.iso.start()
        self.fake=F.FakeCve().start()
        self.undo=F.patch_service(self.fake,cve)
        self._saved={"sleep":cve._sleep,"keyring":ext._keyring,"secrets":ext._secrets,"base":cve.BACKOFF_BASE}
        self.sleeps=[]
        cve._sleep=lambda s:self.sleeps.append(s)
        ext._keyring=lambda:None;ext._secrets=lambda:None
        self.reset()
        self.fake.json("/rest/json/cves/2.0",F.nvd_page([F.nvd_cve()]))
        self.fake.json("/kev.json",F.kev_catalog(),headers={"ETag":'"v1"'})
        self.fake.json("/data/v1/epss",F.epss([("CVE-2021-44228","0.999990000","1.000000000")]))
    def reset(self):
        cve._stamps.clear();cve._cooldown.clear();cve._REQ_LOG.clear();cve._session_key[0]=None
        cve._refresh.update(running=False,error="",note="");cve._launch_done[0]=False
    def tearDown(self):
        cve._sleep=self._saved["sleep"];ext._keyring=self._saved["keyring"];ext._secrets=self._saved["secrets"];cve.BACKOFF_BASE=self._saved["base"]
        self.reset();self.undo();self.fake.stop()
        common_db.set_locked(False)
        self.iso.stop()
    def online(self,patch=None):
        return cve.set_settings({"online":True,**(patch or {})},True)
    def audit(self,event=None):
        return [e for e in security.list_audit_events(500) if event is None or e["event"]==event]
    def settings_text(self):
        with open(os.path.join(self.dir,"settings.json"),encoding="utf-8") as f:return f.read()
class ParsingTest(unittest.TestCase):
    def test_nvd_record(self):
        r=cve.parse_nvd(F.nvd_cve(v40=True))
        self.assertEqual("CVE-2021-44228",r["id"])
        self.assertEqual("Apache Log4j2 Remote Code Execution Vulnerability",r["title"])
        self.assertTrue(r["description"].startswith("Apache Log4j2"))  # the English text, not the first language
        self.assertEqual({"version":"3.1","vector":"CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H","score":10.0,"severity":"critical","source":"nvd@nist.gov"},r["cvss"]["v31"])  # Primary wins over Secondary
        self.assertEqual("4.0",r["cvss"]["v40"]["version"]);self.assertEqual(9.3,r["cvss"]["v40"]["score"])
        self.assertEqual(9.3,r["cvss"]["v2"]["score"]);self.assertEqual("high",r["cvss"]["v2"]["severity"])
        self.assertEqual(("critical",10.0,"3.1"),(r["severity"],r["score"],r["cvss_version"]))
        self.assertEqual(["CWE-917","CWE-502","CWE-400","CWE-20"],[c["id"] for c in r["cwes"]])
        self.assertEqual("Deserialization of Untrusted Data",r["cwes"][1]["name"])
        self.assertEqual({"vendor":"Apache Software Foundation","product":"Apache Log4j2","versions":"2.0-beta9 to before 2.15.0"},r["affected"][0])
        self.assertIn({"vendor":"apache","product":"log4j","versions":"from 2.0.1 before 2.3.1"},r["affected"])
        self.assertFalse(any(a["vendor"]=="siemens" for a in r["affected"]))  # not-vulnerable CPEs are left out
        self.assertEqual({"in_kev":True,"date_added":"2021-12-10","due_date":"2021-12-24"},{k:r["kev"][k] for k in ("in_kev","date_added","due_date")})
        self.assertEqual("2021-12-10T10:15:09.143",r["published"])
    def test_metrics_without_cvss_data_are_ignored(self):
        c=F.nvd_cve();c["metrics"]={"ssvcV203":[{"source":"x","ssvcData":{}}],"cvssMetricV31":[{"source":"x"},"junk"]}
        r=cve.parse_nvd(c)
        self.assertEqual({"v31":None,"v40":None,"v2":None},r["cvss"]);self.assertEqual(("info",None,""),(r["severity"],r["score"],r["cvss_version"]))
    def test_references_are_tagged_sorted_and_only_https_becomes_a_link(self):
        refs=cve.parse_nvd(F.nvd_cve())["references"]
        self.assertEqual(["patch","vendor","exploit"],[r["kind"] for r in refs if r["url"]])  # linkable first, most useful kind first
        self.assertEqual("https://github.com/apache/logging-log4j2/pull/608",refs[0]["url"])
        for r in refs:
            self.assertTrue(r["url"]=="" or r["url"].startswith("https://"))
            self.assertNotRegex(r["url"],r"[\"'<>\s]")
        plain=[r["plain"] for r in refs if not r["url"]]
        self.assertIn("http://packetstormsecurity.com/files/165225/x.html",plain)
        self.assertIn("javascript:alert(1)",plain)
        self.assertTrue(any("<script>" in p for p in plain))  # kept as inert text for the UI to escape, never as a link
    def test_https_filter(self):
        for bad in ("http://a.example","javascript:alert(1)","data:text/html,x","//a.example","https://","https://a.example/\"x","https://a.example/<b>","https://user:pw@a.example/","https://a.example/ x","ftp://a.example",None,""," https:/x"):
            self.assertEqual("",cve._https(bad),bad)
        self.assertEqual("https://a.example/p?q=1#f",cve._https(" https://a.example/p?q=1#f "))
    def test_text_is_cleaned(self):
        c=F.nvd_cve(desc="A\x00B\x1b[31m ‮evil‬\r\n\r\n\r\n\r\nend"+"x"*9000,kev=False)
        d=cve.parse_nvd(c)["description"]
        self.assertNotRegex(d,r"[\x00-\x08\x1b‮]");self.assertIn("AB[31m evil",d);self.assertNotIn("\n\n\n",d);self.assertLessEqual(len(d),6000)
        self.assertEqual("",cve._date("2021-12-10<script>"));self.assertEqual("",cve._txt({"a":1}))
    def test_ids(self):
        self.assertEqual(["CVE-2021-44228","CVE-2026-129448","CVE-2019-0708"],cve.extract_ids("see cve-2021-44228, CVE-2026-129448; CVE-2021-44228 again (CVE-2019-0708). not: CVE-99-1, XCVE-2020-1234, CVE-2020-123"))
        self.assertEqual([],cve.extract_ids(None))
        self.assertEqual("CVE-2021-44228",cve.norm_id(" cve-2021-44228 "))
        for bad in ("","CVE-2021-1","CVE-2021-44228; DROP","2021-44228","CVE-2021-44228/../x",None):
            with self.assertRaises(cve.CveError):cve.norm_id(bad)
    def test_kev_catalog(self):
        entries,info=cve.parse_kev_catalog(F.kev_catalog([F.kev_entry(),F.kev_entry("CVE-2026-129448","2026-11-20","Apache","Roller","Unknown"),{"cveID":"nope"},"junk"]))
        self.assertEqual({"CVE-2021-44228","CVE-2026-129448"},set(entries))
        e=entries["CVE-2021-44228"]
        self.assertEqual(("2021-12-10","2021-12-24","Known",["CWE-502"]),(e["date_added"],e["due_date"],e["ransomware"],e["cwes"]))
        self.assertIn("Apply updates",e["required_action"])
        self.assertEqual({"version":"2026.11.23","released":"2026-11-23T12:54:37.9646Z","count":2},info)
    def test_epss(self):
        d=cve.parse_epss(F.epss([("CVE-2021-44228","0.999990000","1.000000000"),("CVE-2019-0708","0.5","0.97"),("bad","0.1","0.1"),("CVE-2020-0001","7","0.1")]))
        self.assertEqual({"score":0.99999,"percentile":1.0,"date":"2026-11-23"},d["CVE-2021-44228"])
        self.assertEqual({"CVE-2021-44228","CVE-2019-0708"},set(d))
    def test_cveorg_record(self):
        r=cve.parse_cveorg(F.cveorg())
        self.assertEqual(("CVE-2026-0001","Acme Router command injection","high",8.8),(r["id"],r["title"],r["severity"],r["score"]))
        self.assertEqual(["CWE-78"],[c["id"] for c in r["cwes"]])
        self.assertEqual([{"vendor":"Acme","product":"Router","versions":"before 3.2"}],r["affected"])
        self.assertEqual(["https://acme.example/advisories/1",""],[x["url"] for x in r["references"]])
        self.assertEqual(["vendor","patch"],sorted((x["kind"] for x in r["references"]),reverse=True))
        self.assertEqual(["CVE.org"],r["sources"])
    def test_protect_block_separates_vendor_and_generic(self):
        r=cve.parse_nvd(F.nvd_cve())
        p=cve.build_protect(r)
        self.assertEqual("Apply updates per vendor instructions.",p["kev_action"]["text"])
        self.assertEqual(["https://github.com/apache/logging-log4j2/pull/608","https://logging.apache.org/log4j/2.x/security.html"],[v["url"] for v in p["vendor"]])
        self.assertEqual(["CWE-917","CWE-502","CWE-400"],[g["cwe"] for g in p["generic"]])
        self.assertTrue(all(g["mitigations"] and g["detection"] for g in p["generic"]))
        self.assertIn("Vendor guidance",p["vendor_note"]);self.assertIn("not specific",p["generic_note"])
        self.assertEqual([],cve.build_protect(r,False)["generic"])
        r["cwes"]=[{"id":"NVD-CWE-noinfo","name":""}]
        g=cve.build_protect(r)["generic"]
        self.assertEqual([("",guidance.FALLBACK["name"])],[(x["cwe"],x["name"]) for x in g])
    def test_watchlist_matching(self):
        r=cve.parse_nvd(F.nvd_cve())
        self.assertEqual(["log4j","Apache Log4j2","apache"],cve.watch_matches(r,["log4j","Apache Log4j2","apache","log4","nginx","jndi ldap nginx"]))
        self.assertEqual(["JNDI LDAP"],cve.watch_matches(r,["JNDI LDAP"]))  # every word, any order, whole words
        self.assertEqual([],cve.watch_matches(r,[]))
        self.assertEqual(["a.b (c)"],cve.watch_matches({"search":"vendor a.b (c) thing"},["a.b (c)",".*"]))  # terms are text, not regex
        self.assertEqual(["Log4j","nginx"],cve.norm_watchlist([" Log4j ","log4j","x","nginx",5,None,"a"*200][:6]))
class GuardTest(Base):
    def test_off_by_default_and_nothing_is_sent(self):
        s=cve.get_settings()
        self.assertFalse(s["online"]);self.assertFalse(s["offline_only"]);self.assertFalse(cve.can_fetch())
        for call in (lambda:cve.lookup("CVE-2021-44228"),cve.refresh_feed,lambda:cve.refresh_feed(wait=True),cve.test_api_key,lambda:cve.to_finding("CVE-2021-44228"),lambda:cve._request("nvd",cve.ENDPOINTS["nvd"])):
            with self.assertRaises(cve.CveError) as cm:call()
            self.assertEqual("disabled",cm.exception.code)
        self.assertEqual([],self.fake.hits)
        self.assertEqual({"refreshing":False,"unread":0,"notifications":[],"last_refresh":"","refresh_error":""},cve.tick())
        self.assertEqual([],self.fake.hits)
    def test_enabling_needs_consent_and_is_audited(self):
        with self.assertRaises(cve.CveError) as cm:cve.set_settings({"online":True})
        self.assertEqual("consent",cm.exception.code)
        self.assertFalse(cve.get_settings()["online"])
        self.assertFalse(self.audit("cve_settings")[0]["success"])
        s=self.online()
        self.assertTrue(s["online"]);self.assertTrue(s["consent_ts"]);self.assertTrue(cve.can_fetch())
        self.assertIn("online: False -> True",self.audit("cve_settings")[0]["detail"])
    def test_offline_only_wins_and_uses_the_cache(self):
        self.online()
        self.assertEqual("live",cve.lookup("CVE-2021-44228")["origin"])
        n=len(self.fake.hits)
        cve.set_settings({"offline_only":True})
        self.assertFalse(cve.can_fetch())
        r=cve.lookup("CVE-2021-44228",True)
        self.assertEqual("cache",r["origin"]);self.assertIn("Offline only",r["warning"])
        for call in (lambda:cve.lookup("CVE-2019-0708"),cve.refresh_feed,cve.test_api_key):
            with self.assertRaises(cve.CveError) as cm:call()
            self.assertEqual("offline_only",cm.exception.code)
        cve.set_settings({"auto_refresh_hours":1,"refresh_on_launch":True})
        self.assertFalse(cve.tick()["refreshing"])
        self.assertEqual(n,len(self.fake.hits))
    def test_locked_refuses_everything(self):
        self.online();cve.lookup("CVE-2021-44228")
        n=len(self.fake.hits)
        common_db.set_locked(True)
        for call in (cve.status,cve.tick,cve.feed,lambda:cve.search("log4j"),lambda:cve.lookup("CVE-2021-44228"),lambda:cve.lookup("CVE-2021-44228",True),lambda:cve.to_finding("CVE-2021-44228"),lambda:cve.ai_lookup("CVE-2021-44228"),cve.refresh_feed,cve.clear_cache,
                     lambda:cve.set_settings({"offline_only":True}),lambda:cve.set_api_key(NVD_KEY),cve.clear_api_key,cve.test_api_key,cve.mark_all_read,lambda:cve.mark_read(["CVE-2021-44228"]),lambda:cve._request("nvd",cve.ENDPOINTS["nvd"])):
            with self.assertRaises(cve.CveError) as cm:call()
            self.assertEqual("locked",cm.exception.code)
        self.assertEqual(n,len(self.fake.hits))
    def test_bridge_module_is_guarded_while_locked(self):
        from Cores.Bridge import api
        a=api.Api()
        self.assertNotIn("cve",api._LOCK_OPEN)
        common_db.set_locked(True)
        for name in ("status","get_settings","search","lookup","to_finding","feed","tick","privacy_info","request_log","extract_ids"):
            with self.assertRaises(ValueError,msg=name):getattr(a.cve,name)(*(["CVE-2021-44228"] if name in ("lookup","to_finding","search","extract_ids") else []))
    def test_only_fixed_https_hosts_and_no_foreign_redirects(self):
        self.online()
        for url in ("http://services.nvd.nist.gov/rest/json/cves/2.0","https://evil.example/x","https://services.nvd.nist.gov.evil.example/","https://user@services.nvd.nist.gov/","https://services.nvd.nist.gov:8443/","file:///etc/passwd","http://127.0.0.1:1/x"):
            self.assertFalse(cve._url_allowed(url),url)
            with self.assertRaises(cve.CveError) as cm:cve._request("nvd",url)
            self.assertEqual("blocked",cm.exception.code)
        for k,u in {"nvd":"https://services.nvd.nist.gov/rest/json/cves/2.0","kev":"https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json","epss":"https://api.first.org/data/v1/epss","cveorg":"https://cveawg.mitre.org/api/cve/"}.items():
            self.undo();self.assertEqual(u,cve.ENDPOINTS[k]);self.assertTrue(cve._url_allowed(u));self.undo=F.patch_service(self.fake,cve)
        self.fake.on("/rest/json/cves/2.0",lambda q,h,p:(302,b"",{"Location":"http://169.254.169.254/latest/meta-data"}))
        with self.assertRaises(cve.CveError) as cm:cve.lookup("CVE-2019-0708")
        self.assertEqual("blocked",cm.exception.code)
    def test_what_is_sent(self):
        self.online();cve.set_api_key(NVD_KEY)
        cve.set_settings({"watchlist":["SecretClientProduct"]})
        cve.lookup("CVE-2021-44228")
        by={p:(q,h) for p,q,h in self.fake.hits}
        q,h=by["/rest/json/cves/2.0"]
        self.assertEqual({"cveId":"CVE-2021-44228"},q)
        self.assertEqual(NVD_KEY,h["apikey"]);self.assertEqual(cve.USER_AGENT,h["user-agent"])
        self.assertNotIn("apikey",by["/kev.json"][1]);self.assertNotIn("apikey",by["/data/v1/epss"][1])  # the key only ever goes to NVD
        self.assertEqual({"cve":"CVE-2021-44228","limit":"1"},by["/data/v1/epss"][0])
        self.assertEqual({},by["/kev.json"][0])
        sent=json.dumps(self.fake.hits)
        self.assertNotIn("SecretClientProduct",sent);self.assertNotIn(os.path.basename(os.path.expanduser("~")),sent)
        log=cve.request_log()
        self.assertEqual(3,len(log));self.assertEqual({"ts","host","url","status","ms"},set(log[0]))
        self.assertNotIn(NVD_KEY,json.dumps(log));self.assertNotIn(NVD_KEY,self.settings_text());self.assertNotIn(NVD_KEY,json.dumps(self.audit()))
        self.assertNotIn(NVD_KEY,json.dumps(cve.status()));self.assertNotIn(NVD_KEY,json.dumps(cve.get_settings()))
class NetworkTest(Base):
    def test_backoff_then_success(self):
        self.online()
        n={"c":0}
        def flaky(q,h,p):
            n["c"]+=1
            if n["c"]==1:return 429,b"",{"Retry-After":"7"}
            if n["c"]==2:return 503,b"",{}
            return 200,F.nvd_page([F.nvd_cve()]),{}
        self.fake.on("/rest/json/cves/2.0",flaky)
        self.assertEqual("live",cve.lookup("CVE-2021-44228")["origin"])
        self.assertEqual([7,cve.BACKOFF_BASE*3],self.sleeps[:2])  # Retry-After first, then exponential
        self.assertEqual(3,n["c"])
    def test_rate_limited_gives_up_cools_down_and_explains(self):
        self.online({"sources":{"cveorg":False}})
        self.fake.on("/rest/json/cves/2.0",lambda q,h,p:(403,b"",{}))
        with self.assertRaises(cve.CveError) as cm:cve.lookup("CVE-2021-44228")
        self.assertEqual("rate_limited",cm.exception.code);self.assertIn("API key",str(cm.exception))
        self.assertEqual(cve.RETRIES+1,len(self.fake.hits))
        with self.assertRaises(cve.CveError) as cm:cve.lookup("CVE-2021-44228")  # cool-down: fails fast, no request
        self.assertEqual("rate_limited",cm.exception.code)
        self.assertEqual(cve.RETRIES+1,len(self.fake.hits))
    def test_sliding_window_waits_instead_of_exceeding_the_limit(self):
        self.online()
        clock={"t":1000.0}
        saved=cve._mono
        cve._mono=lambda:clock["t"]
        def sleep(s):self.sleeps.append(s);clock["t"]+=s
        cve._sleep=sleep
        try:
            limit,window=cve._LIMITS["nvd"]
            for _ in range(limit):cve._throttle("nvd")
            self.assertEqual([],self.sleeps)
            cve._throttle("nvd")
            self.assertEqual(1,len(self.sleeps));self.assertAlmostEqual(window,self.sleeps[0],1)
            self.assertLessEqual(limit,5);self.assertLessEqual(cve._LIMITS["nvd_key"][0],50)  # NVD: 5 / 30 s without a key, 50 with
        finally:cve._mono=saved
    def test_stale_copy_is_served_when_the_source_fails(self):
        self.online();cve.lookup("CVE-2021-44228")
        self.fake.on("/rest/json/cves/2.0",lambda q,h,p:(500,b"",{}))
        r=cve.lookup("CVE-2021-44228",True)
        self.assertEqual("cache",r["origin"]);self.assertTrue(r["stale"]);self.assertIn("HTTP 500",r["warning"])
    def test_error_messages(self):
        e=cve._net_error("nvd",urllib.error.URLError(ssl.SSLCertVerificationError("CERTIFICATE_VERIFY_FAILED")))
        self.assertEqual("certificate",e.code);self.assertIn("certificate",str(e))
        self.assertEqual("timeout",cve._net_error("kev",urllib.error.URLError(TimeoutError("timed out"))).code)
        e=cve._net_error("epss",urllib.error.URLError(OSError("Name or service not known")))
        self.assertEqual("offline",e.code);self.assertIn("offline",str(e))
        self.assertEqual("proxy",cve._net_error("nvd",urllib.error.URLError("Tunnel connection failed: 407 Proxy Authentication Required")).code)
        self.online();self.fake.stop()
        with self.assertRaises(cve.CveError) as cm:cve.lookup("CVE-2021-44228")
        self.assertEqual("offline",cm.exception.code)
        self.assertEqual("failed",cve.request_log()[0]["status"])
        self.fake=F.FakeCve().start()
    def test_bad_payloads_do_not_crash(self):
        self.online({"sources":{"cveorg":False,"kev":False,"epss":False}})
        self.fake.on("/rest/json/cves/2.0",lambda q,h,p:(200,b"<html>captive portal</html>",{}))
        with self.assertRaises(cve.CveError) as cm:cve.lookup("CVE-2021-44228")
        self.assertEqual("bad_data",cm.exception.code)
        self.fake.json("/rest/json/cves/2.0",{"vulnerabilities":[{"cve":{"id":"<script>"}},{"cve":None},7]})
        with self.assertRaises(cve.CveError) as cm:cve.lookup("CVE-2021-44228")
        self.assertEqual("not_found",cm.exception.code)
    def test_cveorg_fallback_when_nvd_has_nothing(self):
        self.online()
        self.fake.json("/rest/json/cves/2.0",F.nvd_page([]))
        self.fake.json("/api/cve/",F.cveorg())
        self.fake.json("/data/v1/epss",F.epss([]))
        r=cve.lookup("CVE-2026-0001")
        self.assertEqual((["CVE.org"],"high","live"),(r["sources"],r["severity"],r["origin"]))
        self.assertIn("/api/cve/CVE-2026-0001",self.fake.paths())
        cve.set_settings({"sources":{"cveorg":False}})
        with self.assertRaises(cve.CveError) as cm:cve.lookup("CVE-2026-0002")
        self.assertEqual("not_found",cm.exception.code)
class CacheTest(Base):
    def test_lookup_is_cached_and_works_offline(self):
        self.online()
        r=cve.lookup("cve-2021-44228")
        self.assertEqual("live",r["origin"]);self.assertFalse(r["stale"])
        self.assertEqual({"score":0.99999,"percentile":1.0,"date":"2026-11-23"},r["epss"])
        self.assertEqual("Known",r["kev"]["ransomware"])  # from the KEV catalog, which NVD's own fields do not carry
        self.assertEqual({"cve_org":"https://www.cve.org/CVERecord?id=CVE-2021-44228","nvd":"https://nvd.nist.gov/vuln/detail/CVE-2021-44228"},{k:r["links"][k] for k in ("cve_org","nvd")})
        self.assertTrue(r["links"]["kev"].startswith("https://www.cisa.gov/known-exploited-vulnerabilities-catalog"))
        self.assertEqual(["NVD","FIRST EPSS","CISA KEV"],r["sources"])
        n=len(self.fake.hits)
        cve.set_settings({"online":False})
        c=cve.lookup("CVE-2021-44228")
        self.assertEqual("cache",c["origin"]);self.assertEqual(r["fetched_at"],c["fetched_at"]);self.assertEqual(r["description"],c["description"])
        self.assertEqual(n,len(self.fake.hits))
        s=cve.search("log4j apache")
        self.assertEqual(("cache",["CVE-2021-44228"]),(s["origin"],[x["id"] for x in s["results"]]))
        self.assertEqual({"id","title","description","severity","score","cvss_version","kev","epss","published","modified","fetched_at","origin","index_only"},set(s["results"][0]))
        self.assertEqual(["CVE-2021-44228"],[x["id"] for x in cve.search("")["results"]])
        self.assertEqual([],cve.search("100%_nothing")["results"])
        self.assertEqual([],cve.search("' OR 1=1 --")["results"])
        self.assertEqual(["CVE-2021-44228"],[x["id"] for x in cve.search("please check cve-2021-44228 asap")["results"]])
        st=cve.status()
        self.assertEqual((1,1,False),(st["cached"],st["kev_count"],st["can_fetch"]));self.assertEqual(cve.NVD_NOTICE,st["notice"])
    def test_kev_catalog_is_conditional_and_not_refetched_each_time(self):
        self.online()
        seen=[]
        def kev(q,h,p):
            seen.append(h.get("if-none-match"))
            return (304,b"",{}) if h.get("if-none-match")=='"v1"' else (200,F.kev_catalog(),{"ETag":'"v1"'})
        self.fake.on("/kev.json",kev)
        cve.lookup("CVE-2021-44228");cve.lookup("CVE-2021-44228",True)
        self.assertEqual([None],seen)  # within the hour: no second download
        cve.refresh_feed(wait=True)
        self.assertEqual([None,'"v1"'],seen)
        self.assertEqual(1,cve.status()["kev_count"])
    def test_lookup_many(self):
        self.online()
        out=cve.lookup_many(["CVE-2021-44228","nope","cve-2021-44228"])
        self.assertEqual(["CVE-2021-44228"],[r["id"] for r in out["results"]]);self.assertEqual(["nope"],[e["id"] for e in out["errors"]])
    def test_retention_and_clear(self):
        self.online();cve.lookup("CVE-2021-44228")
        with sqlite3.connect(common_db.db_path()) as con:con.execute("UPDATE CveRecords SET fetched_at='2020-01-01T00:00:00+00:00'")
        self.assertTrue(cve.lookup("CVE-2021-44228")["stale"])
        cve.set_settings({"retention_days":30})  # applies at once
        self.assertEqual(0,cve.status()["cached"])
        cve.set_settings({"online":True},True);cve.lookup("CVE-2021-44228",True)
        self.assertEqual({"removed":1},cve.clear_cache())
        st=cve.status();self.assertEqual((0,0),(st["cached"],st["kev_count"]))
        self.assertIn("cleared",self.audit("cve_cache")[0]["detail"])
    def test_schema_migration_from_v14(self):
        p=common_db.db_path()
        con=sqlite3.connect(p);common_db.ensure_schema(con)
        for t in ("CveRecords","CveKev","CveMeta"):con.execute(f"DROP TABLE {t}")
        con.execute("DELETE FROM SchemaMigrations WHERE version=15");con.execute("PRAGMA user_version=14");con.commit();con.close()
        con=sqlite3.connect(p);common_db.ensure_schema(con)
        self.assertGreaterEqual(common_db.DB_SCHEMA_VERSION,15)
        self.assertEqual(common_db.DB_SCHEMA_VERSION,con.execute("PRAGMA user_version").fetchone()[0])
        self.assertEqual({"CveRecords","CveKev","CveMeta"},{r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Cve%'")})
        self.assertIn(15,[r[0] for r in con.execute("SELECT version FROM SchemaMigrations")])
        cols={r[1] for r in con.execute("PRAGMA table_info(CveRecords)")}
        self.assertTrue({"cve_id","data","severity","kev","epss","fetched_at","in_feed","is_read","notified","watch_hit"}<=cols)
        con.close()
class FeedTest(Base):
    def feed_server(self,cves,kev=None):
        def nvd(q,h,p):
            if "cveId" in q:return 200,F.nvd_page([c for c in cves if c["id"]==q["cveId"]]),{}
            start=int(q.get("startIndex",0));size=int(q.get("resultsPerPage",2000))
            return 200,F.nvd_page(cves[start:start+size],len(cves),start),{}
        self.fake.on("/rest/json/cves/2.0",nvd)
        self.fake.json("/kev.json",F.kev_catalog(kev if kev is not None else [F.kev_entry()]))
        self.fake.json("/data/v1/epss",F.epss([("CVE-2026-1001","0.91","0.99"),("CVE-2026-1002","0.02","0.4")]))
    def cves(self):
        from datetime import datetime,timezone
        today=datetime.now(timezone.utc).strftime("%Y-%m-%dT08:00:00.000")
        return [F.nvd_cve("CVE-2026-1001",9.8,"CRITICAL","Remote code execution in Acme Router web UI.",today,False,"acme","router",("CWE-78",)),
                F.nvd_cve("CVE-2026-1002",5.3,"MEDIUM","Information disclosure in Foo CMS.",today,False,"foo","cms",("CWE-200",)),
                F.nvd_cve("CVE-2026-1003",7.5,"HIGH","Denial of service in nginx module.",today,False,"f5","nginx",("CWE-400",))]
    def test_refresh_fills_the_feed_and_filters_work(self):
        self.feed_server(self.cves())
        self.online({"watchlist":["Acme Router","nginx"]})
        out=cve.refresh_feed(wait=True)
        self.assertEqual("Feed refreshed.",out["message"])
        f=cve.feed({})
        self.assertEqual((3,3,False,""),(f["total"],f["unread"],f["refreshing"],f["refresh_error"]));self.assertTrue(f["last_refresh"])
        by={i["id"]:i for i in f["items"]}
        self.assertEqual({"id","title","description","severity","score","cvss_version","kev","epss","published","modified","fetched_at","origin","is_read","watch","kind","vendors"},set(by["CVE-2026-1001"]))
        self.assertEqual((["Acme Router"],"new",0.91,False,"acme router"),(by["CVE-2026-1001"]["watch"],by["CVE-2026-1001"]["kind"],by["CVE-2026-1001"]["epss"],by["CVE-2026-1001"]["is_read"],by["CVE-2026-1001"]["vendors"].split(", ")[-1]))
        ids=lambda **k:sorted(i["id"] for i in cve.feed(k)["items"])
        self.assertEqual(["CVE-2026-1001","CVE-2026-1003"],ids(severity="high"))
        self.assertEqual(["CVE-2026-1001"],ids(severity="critical"))
        self.assertEqual(["CVE-2026-1001"],ids(epss_min=0.5))
        self.assertEqual(["CVE-2026-1002"],ids(q="foo cms"))
        self.assertEqual(["CVE-2026-1001","CVE-2026-1003"],ids(watch_only=True))
        self.assertEqual([],ids(kev_only=True))
        self.assertEqual([],ids(**{"to":"2020-01-01"}));self.assertEqual(3,len(ids(**{"from":"2020-01-01"})))
        self.assertEqual(1,len(cve.feed({"limit":1,"offset":1})["items"]))
        cve.set_settings({"feed":{"min_severity":"critical"}})
        self.assertEqual(["CVE-2026-1001"],[i["id"] for i in cve.feed(None)["items"]])  # null filters = the Settings defaults
        # only dates / paging / severity were sent to NVD - never the watchlist
        nvd_q=[q for p,q,h in self.fake.hits if p=="/rest/json/cves/2.0"]
        self.assertTrue(all(set(q)<={"pubStartDate","pubEndDate","lastModStartDate","lastModEndDate","resultsPerPage","startIndex","noRejected","cvssV3Severity","cvssV4Severity"} for q in nvd_q),nvd_q)
        self.assertRegex(nvd_q[0]["pubStartDate"],r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.000Z$")
        self.assertNotIn("nginx",json.dumps(self.fake.hits).lower())
    def test_read_state_and_notifications_are_delivered_once(self):
        self.feed_server(self.cves())
        self.online({"watchlist":["Acme Router"]})
        cve.refresh_feed(wait=True)
        t=cve.tick()
        self.assertEqual(3,t["unread"])
        self.assertEqual([("CVE-2026-1001","watch")],[(n["id"],n["kind"]) for n in t["notifications"]])
        self.assertEqual("[Acme Router] Remote code execution in Acme Router web UI.",t["notifications"][0]["message"])
        self.assertEqual([],cve.tick()["notifications"])
        self.assertEqual(2,cve.mark_read(["CVE-2026-1001","junk"]))
        self.assertEqual(["CVE-2026-1002","CVE-2026-1003"],sorted(i["id"] for i in cve.feed({"unread_only":True})["items"]))
        self.assertEqual(3,cve.mark_read(["CVE-2026-1001"],False))
        self.assertEqual(0,cve.mark_all_read());self.assertEqual(0,cve.feed({})["unread"])
        cve.refresh_feed(wait=True)  # a second refresh does not re-notify or reset read state
        t=cve.tick();self.assertEqual((0,[]),(t["unread"],t["notifications"]))
    def test_new_kev_entries_notify_but_the_first_download_does_not(self):
        self.feed_server([],[F.kev_entry()])
        self.online({"sources":{"nvd":False,"epss":False}})
        cve.refresh_feed(wait=True)
        self.assertEqual([],cve.tick()["notifications"])  # 1790 entries on first load must not become 1790 toasts
        self.feed_server([],[F.kev_entry(),F.kev_entry("CVE-2026-129448","2026-11-20","Apache","Roller","Unknown")])
        cve.refresh_feed(wait=True)
        t=cve.tick()
        self.assertEqual([("CVE-2026-129448","kev")],[(n["id"],n["kind"]) for n in t["notifications"]])
        self.assertEqual("Apache Roller Remote Code Execution Vulnerability",t["notifications"][0]["message"])
        item=cve.feed({"kev_only":True})["items"][0]
        self.assertEqual(("CVE-2026-129448","kev",True),(item["id"],item["kind"],item["kev"]))
        r=cve.lookup("CVE-2026-129448")  # a KEV stub: partial until the full record can be fetched
        self.assertTrue(r["partial"]);self.assertTrue(r["stale"]);self.assertIn("Apply updates",r["protect"]["kev_action"]["text"])
        self.fake.json("/rest/json/cves/2.0",F.nvd_page([F.nvd_cve("CVE-2026-129448",kev=False)]))  # NVD without its cisa* fields must not clear the KEV flag
        cve.set_settings({"sources":{"nvd":True}});cve.refresh_feed(wait=True);cve.set_settings({"sources":{"nvd":False}})
        self.assertTrue(cve.feed({"kev_only":True})["items"][0]["kev"]);self.assertFalse(cve.lookup("CVE-2026-129448")["partial"])
        cve.set_settings({"notify_kev":False})
        self.feed_server([],[F.kev_entry(),F.kev_entry("CVE-2026-129448","2026-11-20"),F.kev_entry("CVE-2026-5000","2026-11-21")])
        cve.refresh_feed(wait=True)
        self.assertEqual([],cve.tick()["notifications"])
    def test_min_severity_narrows_the_nvd_query(self):
        self.feed_server(self.cves())
        self.online({"feed":{"min_severity":"critical","days_back":3},"sources":{"kev":False,"epss":False}})
        cve.refresh_feed(wait=True)
        qs=[q for p,q,h in self.fake.hits if p=="/rest/json/cves/2.0"]
        self.assertEqual([("CRITICAL",None),(None,"CRITICAL")],[(q.get("cvssV3Severity"),q.get("cvssV4Severity")) for q in qs])
    def test_auto_refresh_schedule(self):
        self.feed_server(self.cves())
        self.online()
        self.assertFalse(cve.tick()["refreshing"]);self.assertEqual([],self.fake.hits)  # Off + no refresh on launch
        cve._launch_done[0]=False
        cve.set_settings({"refresh_on_launch":True})
        self.assertTrue(cve.tick()["refreshing"])
        cve._refresh["thread"].join(20)
        self.assertEqual(3,cve.feed({})["total"])
        n=len(self.fake.hits)
        self.assertFalse(cve.tick()["refreshing"])  # launch refresh happens once
        cve.set_settings({"auto_refresh_hours":6})
        self.assertFalse(cve.tick()["refreshing"])  # not due yet
        with sqlite3.connect(common_db.db_path()) as con:con.execute("UPDATE CveMeta SET value='2020-01-01T00:00:00+00:00' WHERE key='last_attempt'")
        self.assertTrue(cve.tick()["refreshing"])  # the new interval applied without a restart
        cve._refresh["thread"].join(20)
        self.assertGreater(len(self.fake.hits),n)
    def test_refresh_error_is_reported_not_raised(self):
        self.online({"sources":{"kev":False}})
        self.fake.on("/rest/json/cves/2.0",lambda q,h,p:(500,b"",{}))
        out=cve.refresh_feed(wait=True)
        self.assertIn("HTTP 500",out["message"]);self.assertIn("HTTP 500",cve.feed({})["refresh_error"])
class SettingsTest(Base):
    def test_defaults(self):
        self.assertEqual({"online":False,"offline_only":False,"sources":{"nvd":True,"kev":True,"epss":True,"cveorg":True},"auto_refresh_hours":0,"refresh_on_launch":False,"retention_days":90,
            "feed":{"min_severity":"","kev_only":False,"epss_min":0.0,"days_back":7},"watchlist":[],"notify_watchlist":True,"notify_kev":True,"report":{"cvss_version":"3.1","generic_guidance":True},"index_auto":"off","consent_ts":""},cve.get_settings())
    def test_every_setting_persists_merges_and_is_audited(self):
        with open(os.path.join(self.dir,"settings.json"),"w",encoding="utf-8") as f:json.dump({"appearance":{"mode":"royal"},"cve":{"key_hint":"…cdef","key_store":"session"}},f)
        patches=[({"offline_only":True},"offline_only: False -> True"),({"sources":{"epss":False}},"sources.epss: True -> False"),({"auto_refresh_hours":12},"auto_refresh_hours: 0 -> 12"),({"refresh_on_launch":True},"refresh_on_launch"),
                 ({"retention_days":30},"retention_days: 90 -> 30"),({"feed":{"min_severity":"high","kev_only":True,"epss_min":0.25,"days_back":14}},"feed.min_severity: '' -> 'high'"),({"watchlist":["Log4j","nginx","log4j"]},"watchlist: 0 -> 2 term(s)"),
                 ({"notify_watchlist":False},"notify_watchlist"),({"notify_kev":False},"notify_kev"),({"report":{"cvss_version":"4.0"}},"report.cvss_version: '3.1' -> '4.0'"),({"report":{"generic_guidance":False}},"report.generic_guidance")]
        for i,(patch,expect) in enumerate(patches):
            cve.set_settings(patch)
            a=self.audit("cve_settings")
            self.assertEqual(i+1,len(a),patch);self.assertIn(expect,a[0]["detail"]);self.assertTrue(a[0]["success"])
        s=cve.get_settings()
        self.assertEqual({"nvd":True,"kev":True,"epss":False,"cveorg":True},s["sources"])  # nested objects merge
        self.assertEqual({"min_severity":"high","kev_only":True,"epss_min":0.25,"days_back":14},s["feed"])
        self.assertEqual((["Log4j","nginx"],12,30,True,{"cvss_version":"4.0","generic_guidance":False}),(s["watchlist"],s["auto_refresh_hours"],s["retention_days"],s["offline_only"],s["report"]))
        with open(os.path.join(self.dir,"settings.json"),encoding="utf-8") as f:d=json.load(f)
        self.assertEqual({"mode":"royal"},d["appearance"]);self.assertEqual("…cdef",d["cve"]["key_hint"]);self.assertEqual(14,d["cve"]["feed"]["days_back"])
        cve.set_settings({"retention_days":30,"unknown_key":1})  # nothing changed: no audit noise
        self.assertEqual(len(patches),len(self.audit("cve_settings")))
        self.assertNotIn("Log4j",json.dumps(self.audit()))  # watchlist terms stay out of the audit log
    def test_invalid_values_are_rejected_and_change_nothing(self):
        before=cve.get_settings()
        for bad in ({"online":"yes"},{"auto_refresh_hours":5},{"feed":{"min_severity":"urgent"}},{"report":{"cvss_version":"2.0"}},{"watchlist":"log4j"},{"sources":{"nvd":1}},{"feed":"x"},{"retention_days":"soon"},{"feed":{"epss_min":"high"}},"x",None):
            with self.assertRaises(cve.CveError,msg=bad):cve.set_settings(bad)
        self.assertEqual(before,cve.get_settings())
        s=cve.set_settings({"retention_days":999999,"feed":{"epss_min":7,"days_back":400}})
        self.assertEqual((3650,1.0,30),(s["retention_days"],s["feed"]["epss_min"],s["feed"]["days_back"]))
    def test_corrupt_stored_settings_fall_back_to_safe_defaults(self):
        for stored in ("x",{"online":"true","offline_only":1,"sources":[],"feed":{"days_back":"a","epss_min":"NaN"},"auto_refresh_hours":5,"watchlist":{"a":1},"report":7}):
            with open(os.path.join(self.dir,"settings.json"),"w",encoding="utf-8") as f:json.dump({"cve":stored},f)
            s=cve.get_settings()
            self.assertFalse(s["online"]);self.assertFalse(cve.can_fetch());self.assertEqual(0,s["auto_refresh_hours"]);self.assertEqual([],s["watchlist"])
    def test_settings_apply_immediately(self):
        self.online()
        cve.lookup("CVE-2021-44228")
        cve.set_settings({"sources":{"epss":False,"kev":False}})
        n=len(self.fake.hits)
        cve.lookup("CVE-2021-44228",True)
        self.assertEqual(["/rest/json/cves/2.0"],self.fake.paths()[n:])
        self.assertEqual("3.1",cve.to_finding("CVE-2021-44228")["cvss"]["version"])
        self.assertEqual("3.1",cve.status()["default_cvss"])
        cve.set_settings({"report":{"cvss_version":"4.0"}})
        self.assertEqual("4.0",cve.status()["default_cvss"])
    def test_privacy_info(self):
        p=cve.privacy_info()
        self.assertEqual({"services.nvd.nist.gov","www.cisa.gov","api.first.org","cveawg.mitre.org","api.github.com","github.com","release-assets.githubusercontent.com","objects.githubusercontent.com"},{h["host"] for h in p["hosts"]})
        self.assertEqual(set(cve._ALLOWED_HOSTS),{h["host"] for h in p["hosts"]})
        self.assertTrue(any("CVE ids" in s for s in p["sent"]));self.assertTrue(any("Note, report" in s for s in p["never"]))
class KeyTest(Base):
    def test_session_only_when_no_keyring_and_no_encryption(self):
        st=cve.set_api_key(NVD_KEY)
        self.assertEqual({"set":True,"masked":"…cdef","store":"session","stored_but_locked":False},st)
        self.assertNotIn(NVD_KEY,self.settings_text());self.assertNotIn(NVD_KEY,json.dumps(self.audit()))
        self.assertIn("saved (session)",self.audit("cve_key")[0]["detail"])
        self.assertNotIn("key_enc",json.dumps(cve.get_settings()));self.assertNotIn("key_hint",json.dumps(cve.get_settings()))
        cve._session_key[0]=None
        self.assertTrue(cve.key_state()["stored_but_locked"])
        self.assertEqual({"set":False,"masked":"","store":"","stored_but_locked":False},cve.clear_api_key())
        self.assertIn("removed",self.audit("cve_key")[0]["detail"])
    def test_keyring_and_pin_encryption(self):
        store={}
        kr=types.SimpleNamespace(set_password=lambda s,u,p:store.__setitem__((s,u),p),get_password=lambda s,u:store.get((s,u)),delete_password=lambda s,u:store.pop((s,u),None))
        ext._keyring=lambda:kr
        self.assertEqual("keyring",cve.set_api_key(NVD_KEY)["store"])
        self.assertEqual([cve._KEYRING_SERVICE],[k[0] for k in store]);self.assertNotIn(NVD_KEY,self.settings_text())
        cve._session_key[0]=None
        self.assertEqual(NVD_KEY,cve._get_api_key())
        cve.clear_api_key();self.assertEqual({},store)
        ext._keyring=lambda:None
        vault={}
        st=types.SimpleNamespace(put=lambda n,v,h="":vault.__setitem__(n,v) or True,get=lambda n:vault.get(n),delete=lambda n:vault.pop(n,None))
        ext._secrets=lambda:st  # encryption at rest on and unlocked: the key goes into the encrypted database's Secrets table
        self.assertEqual("encrypted",cve.set_api_key(NVD_KEY)["store"])
        self.assertEqual({"cve:nvd":NVD_KEY},vault)
        raw=self.settings_text();self.assertNotIn(NVD_KEY,raw);self.assertNotIn(NVD_KEY,json.dumps(self.audit()))
        cve._session_key[0]=None;self.assertEqual(NVD_KEY,cve._get_api_key())
        cve.set_settings({"watchlist":["x1"]})  # a settings change keeps the stored key
        cve._session_key[0]=None;self.assertEqual(NVD_KEY,cve._get_api_key())
        cve._session_key[0]=None;ext._secrets=lambda:None  # locked / encryption off: the key cannot be read, and the UI says so
        self.assertIsNone(cve._get_api_key());self.assertTrue(cve.key_state()["stored_but_locked"])
        ext._secrets=lambda:st
        cve.clear_api_key();self.assertEqual({},vault)
    def test_rejects_garbage_and_tests_the_key(self):
        for bad in ("has space","short","x"*300,"key\nInjected: header","<script>alert(1)</script>"):
            with self.assertRaises(cve.CveError):cve.set_api_key(bad)
        self.online()
        self.assertFalse(cve.test_api_key()["ok"])
        cve.set_api_key(NVD_KEY)
        self.assertEqual(True,cve.test_api_key()["ok"])
        self.assertEqual(NVD_KEY,self.fake.hits[-1][2]["apikey"])
        self.fake.on("/rest/json/cves/2.0",lambda q,h,p:(403,b"",{}))
        out=cve.test_api_key()
        self.assertFalse(out["ok"]);self.assertIn("rejected",out["message"])
class ReportingTest(Base):
    def setUp(self):
        super().setUp()
        self.fake.json("/rest/json/cves/2.0",F.nvd_page([F.nvd_cve(v40=True)]))
        self.online()
    def test_finding_shape(self):
        f=cve.to_finding("CVE-2021-44228")
        self.assertEqual({"cve_id","title","severity","cvss","cvss_all","cvss_vector","cvss_score","cwe","cwes","description","impact","remediation","remediation_parts","references","reference_urls","affected","kev","epss","tags","source","origin","fetched_at","stale"},set(f))
        self.assertEqual("CVE-2021-44228: Apache Log4j2 Remote Code Execution Vulnerability",f["title"])
        self.assertEqual(("critical",{"version":"3.1","vector":"CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H","score":10.0},"CWE-917"),(f["severity"],f["cvss"],f["cwe"]))
        self.assertEqual((f["cvss"]["vector"],f["cvss"]["score"]),(f["cvss_vector"],f["cvss_score"]))
        self.assertEqual(9.3,f["cvss_all"]["v40"]["score"])
        self.assertEqual(["https://www.cve.org/CVERecord?id=CVE-2021-44228","https://nvd.nist.gov/vuln/detail/CVE-2021-44228"],f["reference_urls"][:2])
        self.assertTrue(all(r["url"].startswith("https://") and set(r)=={"url","tags"} for r in f["references"]))
        self.assertEqual([r["url"] for r in f["references"]],f["reference_urls"])
        self.assertIn("CVSS 3.1 base score 10.0 (Critical). Attack vector: network; attack complexity: low; privileges required: none; user interaction: none.",f["impact"])
        self.assertIn("Impact on confidentiality high, integrity high, availability high.",f["impact"])
        self.assertIn("Known to be exploited in the wild (CISA KEV, added 2021-12-10). Known to be used in ransomware campaigns.",f["impact"])
        self.assertIn("EPSS: 100.00%",f["impact"])
        r=f["remediation"]
        self.assertLess(r.index("CISA KEV required action (due 2021-12-24):"),r.index("Vendor guidance:"));self.assertLess(r.index("Vendor guidance:"),r.index("Generic guidance (CWE-917"))
        self.assertIn("not vendor-specific",r);self.assertIn("- https://github.com/apache/logging-log4j2/pull/608 (Patch)",r)
        self.assertEqual({"in_kev":True,"date_added":"2021-12-10","due_date":"2021-12-24","ransomware":"Known"},{k:f["kev"][k] for k in ("in_kev","date_added","due_date","ransomware")})
        self.assertEqual((["cve","kev"],"cve:CVE-2021-44228","live"),(f["tags"],f["source"],f["origin"]))
        self.assertEqual("cache",cve.to_finding("CVE-2021-44228")["origin"])
    def test_cvss_version_and_generic_guidance_follow_settings_and_opts(self):
        cve.lookup("CVE-2021-44228")
        cve.set_settings({"report":{"cvss_version":"4.0","generic_guidance":False}})
        f=cve.to_finding("CVE-2021-44228")
        self.assertEqual(("4.0",9.3,"critical"),(f["cvss"]["version"],f["cvss"]["score"],f["severity"]))
        self.assertIn("Impact on confidentiality high",f["impact"])
        self.assertNotIn("Generic guidance",f["remediation"]);self.assertEqual([],f["remediation_parts"]["generic"])
        f=cve.to_finding("CVE-2021-44228",{"cvss_version":"3.1","generic":True})
        self.assertEqual("3.1",f["cvss"]["version"]);self.assertIn("Generic guidance",f["remediation"])
        self.fake.json("/rest/json/cves/2.0",F.nvd_page([F.nvd_cve("CVE-2020-1111",kev=False)]))  # no v4.0 published: falls back to 3.1
        self.assertEqual("3.1",cve.to_finding("CVE-2020-1111")["cvss"]["version"])
    def test_finding_fits_the_reporting_model(self):
        from Cores.Services import reports_service as reports
        f=cve.to_finding("CVE-2021-44228")
        self.assertIn(f["severity"],reports.SEVERITIES)
        rep=reports.create_report("CVE test")
        made=reports.add_finding(rep["id"],{"title":f["title"],"severity":f["severity"],"cvss_vector":f["cvss_vector"],"cwe":f["cwe"],"description":f["description"],"impact":f["impact"],"remediation":f["remediation"],"references":f["reference_urls"],"tags":f["tags"]})
        made=made if "title" in made else made.get("finding",made)
        self.assertEqual((f["title"],"critical",10.0),(made["title"],made["severity"],made["cvss_score"]))
class McpTest(Base):
    def test_cve_lookup_goes_through_ai_roles(self):
        from Cores.Services import ai_service as ai
        from Cores.Services import ai_chat_service as chat
        self.assertEqual(("CVE Intel","Read"),ai.PERMISSION_LABELS["cve_read"]);self.assertIn("cve_lookup",ai.PERMISSION_TOOL_MAP["cve_read"])
        self.assertIn("cve_lookup",[t.name for t in chat._list_tools()])
        ok,msg=chat._call_tool("cve_lookup",{"cve_id":"CVE-2021-44228"})
        self.assertFalse(ok);self.assertIn("Online CVE lookups are off",str(msg))  # same opt-in as the UI
        self.assertEqual([],self.fake.hits)
        self.online()
        ok,r=chat._call_tool("cve_lookup",{"cve_id":"CVE-2021-44228"})
        self.assertTrue(ok,r);self.assertEqual(("CVE-2021-44228","critical"),(r["id"],r["severity"]));self.assertIn("untrusted",r["note"])
        self.assertTrue(all(x["url"].startswith("https://") for x in r["references"]))
        common_db.set_locked(True)
        ok,msg=chat._call_tool("cve_lookup",{"cve_id":"CVE-2021-44228"})
        self.assertFalse(ok);self.assertIn("locked",str(msg))
if __name__=="__main__":unittest.main()
