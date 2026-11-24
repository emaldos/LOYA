import os,json,base64,shutil,tempfile,unittest
from _isolate import ROOT,IsolatedData
import _report_fixture as fx
from Cores.Services import report_export as rx
from Cores.Services import report_import as ri
from Cores.Services import reports_service as svc
from Cores.Services import evidence_service as ev
from Cores.Bridge import api,reports_io_api
NESSUS_CSV='''Plugin ID,CVE,CVSS v2.0 Base Score,Risk,Host,Protocol,Port,Name,Synopsis,Description,Solution,See Also,Plugin Output,CVSS v3.0 Base Score
10863,,,None,10.0.0.5,tcp,443,SSL Certificate Information,Certificate info.,Displays the certificate.,n/a,,Subject: CN=x,
42873,CVE-2016-2183,5.0,Medium,10.0.0.5,tcp,443,SSL Medium Strength Cipher Suites Supported (SWEET32),The remote service supports medium strength SSL ciphers.,"The remote host supports the use of SSL ciphers
that offer medium strength encryption.",Reconfigure the affected application to avoid medium strength ciphers.,https://sweet32.info,"Medium Strength Ciphers: DES-CBC3-SHA",7.5
42873,CVE-2016-2183,5.0,Medium,10.0.0.6,tcp,8443,SSL Medium Strength Cipher Suites Supported (SWEET32),The remote service supports medium strength SSL ciphers.,"The remote host supports the use of SSL ciphers
that offer medium strength encryption.",Reconfigure the affected application to avoid medium strength ciphers.,https://sweet32.info,"Medium Strength Ciphers: DES-CBC3-SHA",7.5
97833,"CVE-2017-0143,CVE-2017-0144",10.0,Critical,10.0.0.9,tcp,445,MS17-010: Security Update for Microsoft Windows SMB Server (ETERNALBLUE),The remote Windows host is affected by multiple vulnerabilities.,Remote code execution via SMBv1.,Apply the MS17-010 patches.,https://technet.microsoft.com/library/security/MS17-010,<script>alert(1)</script>,9.8
'''
class ImportCase(unittest.TestCase):
    def setUp(self):
        self.iso=IsolatedData();self.iso.start()
        self.tmp=tempfile.mkdtemp(prefix="loya_ri_")
    def tearDown(self):
        shutil.rmtree(self.tmp,ignore_errors=True);self.iso.stop()
    def write(self,name,data):
        p=os.path.join(self.tmp,name)
        with open(p,"wb") as f:f.write(data if isinstance(data,bytes) else data.encode("utf-8"))
        return p
    def write_json(self,name,obj):return self.write(name,json.dumps(obj))
    def seed(self):
        """The fixture report stored through the real services (assets and evidence get the store's own uids)."""
        src=fx.report();amap={};emap={}
        for uid,a in src["_assets"].items():amap[uid]=svc.add_asset(a["name"],a["data"])["uid"]
        for row in src["_evidence"]:
            data=dict(row);data.pop("id",None);events=data.pop("events",[])
            if data["meta"].get("asset_uid"):data["meta"]=dict(data["meta"],asset_uid=amap[data["meta"]["asset_uid"]])
            ev.restore_entry({"evidence":data,"events":events});emap[row["uid"]]=row["uid"]
        payload=ri._report_payload(svc,src,amap,emap,{"blank","external_network"})
        return svc.create_report(payload),amap
def content(rep):
    """What must survive an export/import round trip (ids, uids of assets and timestamps aside)."""
    return {"title":rep["title"],"status":rep["status"],"meta":rep["meta"],"options":rep["options"],"branding":{k:v for k,v in rep["branding"].items() if k!="logo_asset"},
        "sections":[(s["kind"],s["title"],s["content"],s["hidden"],s["options"]) for s in rep["sections"]],
        "findings":[{k:v for k,v in f.items() if k not in ("id","report_id","uid","created_at","updated_at")} for f in rep["findings"]]}
class ReportJsonRoundTripTests(ImportCase):
    def test_export_wipe_import_gives_equal_content(self):
        rep,_amap=self.seed()
        path=rx.render(svc.get_report(rep["id"]),"json",os.path.join(self.tmp,"r.json"))
        before=content(svc.get_report(rep["id"]))
        self.iso.stop();self.iso.start()
        self.assertEqual([],svc.list_reports())
        info=ri.summarize(path,"auto")
        self.assertEqual("report_json",info["kind"])
        self.assertEqual((1,5,3,4),(info["summary"]["reports"],info["summary"]["findings"],info["summary"]["assets"],info["summary"]["evidence"]))
        self.assertEqual({"critical":1,"high":1,"medium":1,"low":1,"info":1},info["summary"]["severity"]);self.assertEqual([],info["summary"]["warnings"])
        out=ri.apply(path,"report_json")
        self.assertEqual((1,5,1),(out["reports"],out["findings"],len(out["report_ids"])));self.assertIn("Imported 1 report",out["message"])
        got=svc.get_report(out["report_ids"][0])
        after=content(got)
        # asset uids are assigned by the store, so compare the rich text with them normalised
        norm=lambda c:json.loads(rx._ASSET_RX.sub("rptasset:X",json.dumps(c)))
        self.maxDiff=None
        strip=lambda c:{**c,"findings":[{**f,"evidence":[{**e,"asset_uid":"X" if e["asset_uid"] else ""} for e in f["evidence"]]} for f in c["findings"]]}
        self.assertEqual(strip(norm(before)),strip(norm(after)))
        self.assertEqual(rep["uid"],got["uid"])
        logo=svc.get_asset(got["branding"]["logo_asset"]);self.assertEqual(b"\x89PNG",logo["data"][:4])
        shot=[e for e in got["findings"][0]["evidence"] if e["asset_uid"]][0];self.assertEqual((900,520),(svc.get_asset(shot["asset_uid"])["width"],svc.get_asset(shot["asset_uid"])["height"]))
        rec=ev.get("ev-rec");self.assertEqual(6,len(rec["events"]));self.assertEqual("db01",rec["target"])
        self.assertIn(fx.SECRET,ev.get("ev-sqlmap")["content"])
        img=ev.get("ev-shot");self.assertEqual(b"\x89PNG",svc.get_asset(img["meta"]["asset_uid"])["data"][:4])
        html=rx.build_html(got)
        self.assertIn("Admin console reachable without authentication",html);self.assertGreaterEqual(html.count("data:image/png;base64,"),4)
    def test_importing_twice_keeps_both_with_a_new_uid(self):
        rep,_amap=self.seed()
        path=rx.render(svc.get_report(rep["id"]),"json",os.path.join(self.tmp,"r.json"))
        assets_before=self.count("ReportAssets");evidence_before=self.count("ReportEvidence")
        out=ri.apply(path,"report_json")
        got=svc.get_report(out["report_ids"][0])
        self.assertNotEqual(rep["uid"],got["uid"]);self.assertNotEqual(rep["id"],got["id"])
        self.assertEqual("ACME External Pentest Report (imported)",got["title"])
        self.assertEqual(2,len(svc.list_reports()))
        self.assertEqual(assets_before,self.count("ReportAssets"));self.assertEqual(evidence_before,self.count("ReportEvidence"))
    def count(self,table):
        import sqlite3
        from Cores import common_db
        con=sqlite3.connect(common_db.db_path())
        try:return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        finally:con.close()
    def test_changed_evidence_with_a_known_uid_gets_a_new_uid(self):
        rep,_amap=self.seed()
        data=rx.build_json(svc.get_report(rep["id"]))
        for e in data["evidence"]:
            if e["uid"]=="ev-nmap":e["content"]="different output"
        out=ri.import_reports(data)
        got=svc.get_report(out["report_ids"][0])
        self.assertNotIn('data-evidence="ev-nmap"',got["findings"][0]["steps"])
        new_uid=rx._EVID_RX.search(got["findings"][0]["steps"]).group(1)
        self.assertEqual("different output",ev.get(new_uid)["content"]);self.assertIn("Starting Nmap",ev.get("ev-nmap")["content"])
    def test_bundle_round_trip(self):
        rep,_amap=self.seed()
        second=svc.create_report({"title":"Second report","template_id":"web_app"})
        path=rx.render_many([svc.get_report(rep["id"]),svc.get_report(second["id"])],"json",os.path.join(self.tmp,"b.json"))
        self.iso.stop();self.iso.start()
        info=ri.summarize(path,"auto");self.assertEqual(2,info["summary"]["reports"])
        out=ri.apply(path,"auto")
        self.assertEqual(2,out["reports"]);self.assertEqual(["ACME External Pentest Report","Second report"],sorted(r["title"] for r in svc.list_reports()))
class HostileReportJsonTests(ImportCase):
    def payload(self):
        r=fx.report();assets=r.pop("_assets");r.pop("_evidence")
        return {"format":"loya-report","version":1,"report":r,"assets":{k:{"mime":v["mime"],"name":v["name"],"data_b64":base64.b64encode(v["data"]).decode()} for k,v in assets.items()},"evidence":fx.evidence()}
    def test_rich_text_is_sanitised_and_ids_are_not_trusted(self):
        p=self.payload();r=p["report"]
        existing=svc.create_report({"title":"Existing","template_id":"blank"})
        r["id"]=existing["id"];r["profile_id"]="no-such-profile";r["template_id"]="../../evil"
        r["sections"][1]["content"]='<p onclick="x()">ok</p><script>alert(1)</script><iframe src="//evil"></iframe><a href="javascript:alert(1)">l</a><img src="http://evil/x.png"><img src="rptasset:asset-inline">'
        r["sections"][1]["id"]=1;r["findings"][0]["id"]=existing["id"];r["findings"][0]["report_id"]=existing["id"]
        r["findings"][0]["description"]='<p>d</p><style>*{}</style><svg onload="x()"></svg><form action="//evil"><input></form>'
        r["findings"][0]["severity"]="<script>";r["findings"][0]["status"]="hacked";r["status"]="owned"
        out=ri.import_reports(p)
        self.assertEqual(svc.get_report(existing["id"])["title"],"Existing");self.assertEqual([],svc.get_report(existing["id"])["findings"])
        got=svc.get_report(out["report_ids"][0])
        self.assertNotEqual(existing["id"],got["id"]);self.assertEqual("",got["profile_id"]);self.assertEqual("blank",got["template_id"]);self.assertEqual("draft",got["status"])
        blob=json.dumps([s["content"] for s in got["sections"]]+[f[k] for f in got["findings"] for k in ("description","impact","steps","remediation")]).lower()
        for bad in ("<script","onclick","<iframe","javascript:","http://evil","<style","<svg","<form","onload"):self.assertNotIn(bad,blob)
        self.assertIn("rptasset:",got["sections"][1]["content"]);self.assertNotIn("rptasset:asset-inline",got["sections"][1]["content"])
        self.assertIn(got["findings"][0]["severity"],rx.SEVERITIES);self.assertIn(got["findings"][0]["status"],rx.STATUSES)
    def test_images_are_checked_by_magic_bytes(self):
        p=self.payload()
        p["assets"]["asset-shot"]["data_b64"]=base64.b64encode(b"MZ\x90\x00 this is an executable").decode()
        p["assets"]["asset-inline"]["data_b64"]="%%% not base64 %%%"
        p["assets"]["asset-logo"]["mime"]="text/html"
        info=ri._reports_summary(p)
        self.assertEqual(1,info["assets"]);self.assertIn("2 images in the file are not valid",info["warnings"][0])
        got=svc.get_report(ri.import_reports(p)["report_ids"][0])
        self.assertEqual("image/png",svc.get_asset(got["branding"]["logo_asset"])["mime"])
        import sqlite3
        from Cores import common_db
        con=sqlite3.connect(common_db.db_path())
        try:
            rows=con.execute("SELECT mime,data FROM ReportAssets").fetchall()
        finally:con.close()
        self.assertEqual(1,len(rows));self.assertEqual(b"\x89PNG",bytes(rows[0][1])[:4])
    def test_junk_is_rejected(self):
        cases=[("empty.json",b""),("notjson.json",b"{not json"),("binary.json",b"\x00\x01\x02\xff\xfe"*50),("list.json",b"[1,2,3]"),("str.json",b'"hello"'),("nested.json",b"["*100000+b"]"*100000),
            ("noreport.json",json.dumps({"format":"loya-report","version":1,"report":"x"})),("badsections.json",json.dumps({"format":"loya-report","report":{"title":"t","sections":"x","findings":[]}})),
            ("notitle.json",json.dumps({"format":"loya-report","report":{"title":5,"sections":[],"findings":[]}})),("future.json",json.dumps({"format":"loya-report","version":99,"report":{"title":"t","sections":[],"findings":[]}})),
            ("nobundle.json",json.dumps({"format":"loya-report-bundle","reports":[]})),("badmeta.json",json.dumps({"format":"loya-report","report":{"title":"t","sections":[],"findings":[],"meta":[1]}}))]
        for name,data in cases:
            p=self.write(name,data)
            with self.assertRaises(ValueError,msg=name):ri.summarize(p,"report_json")
            with self.assertRaises(ValueError,msg=name):ri.apply(p,"report_json")
        self.assertEqual([],svc.list_reports())
        with self.assertRaises(ValueError):ri.summarize(os.path.join(self.tmp,"missing.json"),"report_json")
        with self.assertRaises(ValueError):ri.summarize(self.write("x.bin",b"\x7fELF"),"auto")
        with self.assertRaises(ValueError):ri.apply(self.write("ok.json",json.dumps(self.payload())),"nonsense")
    def test_size_limits(self):
        p=self.payload();path=self.write_json("big.json",p)
        saved=ri.MAX_JSON_BYTES;ri.MAX_JSON_BYTES=100
        try:
            with self.assertRaises(ValueError):ri.summarize(path,"report_json")
        finally:ri.MAX_JSON_BYTES=saved
        saved=ri.MAX_FINDINGS;ri.MAX_FINDINGS=2
        try:
            with self.assertRaises(ValueError):ri.import_reports(p)
        finally:ri.MAX_FINDINGS=saved
        saved=ri.MAX_REPORTS;ri.MAX_REPORTS=1
        try:
            with self.assertRaises(ValueError):ri.import_reports({"format":"loya-report-bundle","reports":[p["report"],p["report"]]})
        finally:ri.MAX_REPORTS=saved
        self.assertEqual([],svc.list_reports())
    def test_a_failed_import_rolls_everything_back(self):
        p=self.payload();good=dict(p["report"]);bad=dict(p["report"]);bad["sections"]=[{"kind":"custom","title":"x","content":"<p>x</p>"}]
        calls={"n":0};real=svc.create_report
        def flaky(payload=None):
            calls["n"]+=1
            if calls["n"]==2:raise RuntimeError("boom")
            return real(payload)
        svc.create_report=flaky
        try:
            with self.assertRaises(RuntimeError):ri.import_reports({"format":"loya-report-bundle","reports":[good,bad],"assets":p["assets"],"evidence":p["evidence"]})
        finally:svc.create_report=real
        self.assertEqual([],svc.list_reports())
        with self.assertRaises(ValueError):ev.get("ev-nmap")
class FindingsCsvTests(ImportCase):
    def test_generic_headers_are_matched_flexibly(self):
        p=self.write("f.csv","Name;Risk;CVSS;Host;Recommendation;Details;CWE ID;References;State\r\nWeak TLS;High;7.4;10.0.0.1, 10.0.0.2;Disable TLS 1.0;\"Old protocols are enabled.\n\nSecond paragraph <b>x</b>.\";326;\"https://a.example; https://b.example\";closed\r\nNo severity given;;9.9;;;;;;\r\nPlain;;;;;;;;\r\n;High;;;;;;;\r\n")
        parsed=ri.parse_findings_csv(p,"f.csv")
        self.assertEqual({"title":"Name","severity":"Risk","cvss_score":"CVSS","affected":"Host","remediation":"Recommendation","description":"Details","cwe":"CWE ID","references":"References","status":"State"},parsed["columns"])
        f=parsed["findings"];self.assertEqual(3,len(f));self.assertFalse(parsed["scanner"])
        self.assertEqual(("Weak TLS","high",7.4,"fixed","CWE-326"),(f[0]["title"],f[0]["severity"],f[0]["cvss_score"],f[0]["status"],f[0]["cwe"]))
        self.assertEqual(["10.0.0.1","10.0.0.2"],[a["value"] for a in f[0]["affected"]]);self.assertEqual(["https://a.example","https://b.example"],f[0]["references"])
        self.assertEqual("<p>Old protocols are enabled.</p><p>Second paragraph &lt;b&gt;x&lt;/b&gt;.</p>",f[0]["description"]);self.assertEqual("<p>Disable TLS 1.0</p>",f[0]["remediation"])
        self.assertEqual(("critical","info"),(f[1]["severity"],f[2]["severity"]));self.assertEqual({"kind":"import","ref":"f.csv"},f[0]["source"])
    def test_nessus_rows_are_grouped_by_name_with_hosts_collected(self):
        p=self.write("scan.csv",NESSUS_CSV)
        info=ri.summarize(p,"auto")
        self.assertEqual("findings_csv",info["kind"]);s=info["summary"]
        self.assertTrue(s["scanner"]);self.assertEqual(3,s["findings"]);self.assertEqual({"critical":1,"high":0,"medium":1,"low":0,"info":1},s["severity"])
        self.assertTrue(any("informational" in w for w in s["warnings"]))
        out=ri.apply(p,"findings_csv")
        self.assertEqual((1,2),(out["reports"],out["findings"]))
        rep=svc.get_report(out["report_ids"][0]);self.assertEqual("Imported findings - scan",rep["title"])
        self.assertEqual(["findings_summary","findings"],[s["kind"] for s in rep["sections"]][1:3])
        eb,sw=rep["findings"]
        self.assertTrue(eb["title"].startswith("MS17-010"));self.assertEqual(("critical",9.8),(eb["severity"],eb["cvss_score"]))
        self.assertEqual(["10.0.0.9:445/tcp"],[a["value"] for a in eb["affected"]])
        self.assertEqual(["https://technet.microsoft.com/library/security/MS17-010","https://nvd.nist.gov/vuln/detail/CVE-2017-0143","https://nvd.nist.gov/vuln/detail/CVE-2017-0144"],eb["references"])
        self.assertNotIn("<script",eb["steps"]);self.assertIn("&lt;script&gt;",eb["steps"]);self.assertTrue(eb["steps"].startswith("<pre>"))
        self.assertEqual(["10.0.0.5:443/tcp","10.0.0.6:8443/tcp"],[a["value"] for a in sw["affected"]])
        self.assertIn("medium strength SSL ciphers",sw["description"]);self.assertIn("offer medium strength encryption",sw["description"]);self.assertEqual("import",sw["source"]["kind"])
        with_info=ri.apply(p,"findings_csv",{"include_info":True});self.assertEqual(3,with_info["findings"])
    def test_findings_are_added_to_an_existing_report(self):
        rep=svc.create_report({"title":"Target","template_id":"web_app"})
        svc.add_finding(rep["id"],{"title":"Already there","severity":"low"})
        out=ri.apply(self.write("scan.csv",NESSUS_CSV),"findings_csv",{"report_id":rep["id"]})
        self.assertEqual((0,2,[rep["id"]]),(out["reports"],out["findings"],out["report_ids"]))
        got=svc.get_report(rep["id"]);self.assertEqual(3,len(got["findings"]));self.assertEqual("Already there",got["findings"][0]["title"])
        self.assertEqual(1,len(svc.list_reports()))
        with self.assertRaises(ValueError):ri.apply(self.write("scan2.csv",NESSUS_CSV),"findings_csv",{"report_id":987654})
    def test_our_own_csv_export_imports_back_without_the_formula_guards(self):
        path=rx.render(fx.report(),"csv",os.path.join(self.tmp,"own.csv"))
        f=ri.parse_findings_csv(path)["findings"]
        self.assertEqual(5,len(f));self.assertEqual("=cmd|' /C calc'!A0",f[2]["title"]);self.assertEqual("<p>+SUM(1) formula-looking text</p>",f[2]["description"])
        self.assertEqual(("critical",9.8,"CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H","CWE-89","A03:2021 Injection"),(f[0]["severity"],f[0]["cvss_score"],f[0]["cvss_vector"],f[0]["cwe"],f[0]["owasp"]))
        self.assertEqual(["retest","fixed","accepted"],[x["status"] for x in f[1:4]]);self.assertEqual(["web","injection"],f[0]["tags"])
    def test_affected_linked_target_keeps_its_values_together(self):
        # Our CSV writes a linked target as "name (value, value)", one asset per line: the comma inside must not split it.
        f=ri.parse_findings_csv(self.write("aff.csv",'Title,Affected\nX,"web01 (https://portal.example, 10.10.20.15)\n192.0.2.1/admin"\nY,"a, b; c"\n'))["findings"]
        self.assertEqual(["web01 (https://portal.example, 10.10.20.15)","192.0.2.1/admin"],[a["value"] for a in f[0]["affected"]])
        self.assertEqual(["a","b","c"],[a["value"] for a in f[1]["affected"]])
    def test_encodings_and_delimiters(self):
        for name,data in (("u16.csv","Title,Severity\nÜmlaut finding,Low\n".encode("utf-16")),("cp.csv","Title,Severity\nCaf\xe9 finding,Low\n".encode("cp1252")),("tab.tsv",b"Title\tSeverity\nTabbed\tLow\n"),("bom.csv",b"\xef\xbb\xbfTitle,Severity\nBom,Low\n")):
            f=ri.parse_findings_csv(self.write(name,data))["findings"]
            self.assertEqual((1,"low"),(len(f),f[0]["severity"]),name)
        self.assertEqual("Café finding",ri.parse_findings_csv(os.path.join(self.tmp,"cp.csv"))["findings"][0]["title"])
    def test_junk_csv_is_rejected(self):
        for name,data in (("empty.csv",b""),("header.csv",b"Title,Severity\n"),("notitle.csv",b"foo,bar\n1,2\n"),("bin.csv",b"\x00\x01\x02\x03"*100),("blank.csv",b"Title,Severity\n,High\n ,Low\n")):
            with self.assertRaises(ValueError,msg=name):ri.summarize(self.write(name,data),"findings_csv")
        saved=ri.MAX_CSV_BYTES;ri.MAX_CSV_BYTES=10
        try:
            with self.assertRaises(ValueError):ri.parse_findings_csv(self.write("big.csv",b"Title,Severity\nA,High\n"))
        finally:ri.MAX_CSV_BYTES=saved
    def test_severity_and_score_parsing(self):
        self.assertEqual(["info","low","medium","high","critical","info"],[ri.sev_from_score(x) for x in (0,3.9,4.0,8.9,9.0,None)])
        self.assertEqual([9.8,7.0,None,None,5.5],[ri._score(x) for x in ("9.8","7","n/a","11","CVSS 5,5")])
class TemplatesLibraryTests(ImportCase):
    def test_templates_round_trip(self):
        rep=svc.create_report({"title":"Base","template_id":"web_app"})
        svc.template_save_from_report(rep["id"],"House style","Our layout")
        data=ri.build_templates_export()
        self.assertEqual(("loya-report-templates",1),(data["format"],len(data["templates"])))
        path=self.write_json("t.json",data)
        info=ri.summarize(path,"auto");self.assertEqual(("templates",1),(info["kind"],info["summary"]["templates"]))
        out=ri.apply(path,"templates");self.assertEqual(1,out["templates"])
        names=sorted(t["name"] for t in svc.templates() if not t["builtin"])
        self.assertEqual(["House style","House style (imported)"],names)
        new=[t for t in svc.templates() if t["name"]=="House style (imported)"][0]
        self.assertEqual([s["kind"] for s in svc.template_get("web_app")["sections"]],[s["kind"] for s in svc.template_get(new["id"])["sections"]])
        hostile=self.write_json("h.json",{"format":"loya-report-templates","templates":[{"name":"Evil","id":"web_app","sections":[{"kind":"custom","title":"x","content":"<p>ok</p><script>alert(1)</script>"}]}]})
        ri.apply(hostile,"templates")
        evil=[t for t in svc.templates() if t["name"]=="Evil"][0]
        self.assertFalse(evil["builtin"]);self.assertNotIn("script",svc.template_get(evil["id"])["sections"][0]["content"])
        self.assertTrue(svc.template_get("web_app")["builtin"])
        with self.assertRaises(ValueError):ri.build_templates_export(["no-such-id"])
    def test_library_round_trip_skips_what_already_exists(self):
        seeded=len(svc.library_list())
        svc.library_save({"title":"Custom weak thing","category":"Custom","severity":"medium","description":"<p>desc</p>","remediation":"<p>fix</p>","references":["https://x.example"]})
        data=ri.build_library_export();self.assertEqual(seeded+1,len(data["entries"]))
        data["entries"].append({"title":"Brand new entry","severity":"high","category":"New","description":"<p>n</p><script>x</script>","id":1,"uid":"builtin-sqli"})
        data["entries"].append({"title":"","severity":"high"})
        path=self.write_json("l.json",data)
        info=ri.summarize(path,"library");self.assertEqual(seeded+2,info["summary"]["library"]);self.assertIn("already exist",info["summary"]["warnings"][0])
        out=ri.apply(path,"library")
        self.assertEqual((1,seeded+1),(out["library"],out["skipped"]));self.assertEqual(seeded+2,len(svc.library_list()))
        new=svc.library_get([e for e in svc.library_list() if e["title"]=="Brand new entry"][0]["id"])
        self.assertEqual(("high","New","<p>n</p>"),(new["severity"],new["category"],new["description"]));self.assertFalse(new["builtin"])
    def test_kinds_are_not_confused(self):
        lib=self.write_json("l.json",{"format":"loya-report-library","entries":[{"title":"x"}]})
        tpl=self.write_json("t.json",{"format":"loya-report-templates","templates":[{"name":"n","sections":[]}]})
        rep=self.write_json("r.json",{"format":"loya-report","report":{"title":"t","sections":[],"findings":[]}})
        self.assertEqual(["library","templates","report_json"],[ri.sniff(p) for p in (lib,tpl,rep)])
        self.assertEqual("",ri.sniff(self.write_json("n.json",[{"note_name":"a"}])));self.assertEqual("",ri.sniff(self.write_json("o.json",{"notes":[]})))
        self.assertEqual("findings_csv",ri.sniff(self.write("x.csv","a,b\n")))
        for path,kind in ((lib,"report_json"),(tpl,"library"),(rep,"templates"),(rep,"library")):
            with self.assertRaises(ValueError):ri.summarize(path,kind)
class BridgeImportTests(ImportCase):
    def setUp(self):
        super().setUp()
        self.saved=api._upload_state["dir"];api._upload_state["dir"]=None
        self.io=reports_io_api.ReportsIOAPI()
        class NoDialog:
            def create_file_dialog(self,*a,**k):raise AssertionError("dialog must not open for a staged file")
        self.io.bind(NoDialog())
    def tearDown(self):
        d=api._upload_state["dir"]
        if d:shutil.rmtree(d,ignore_errors=True)
        api._upload_state["dir"]=self.saved
        super().tearDown()
    def stage(self,name,data):return api._stage_upload(name,base64.b64encode(data if isinstance(data,bytes) else data.encode("utf-8")).decode("ascii"))
    def test_staged_pick_then_apply(self):
        staged=self.stage("scan.csv",NESSUS_CSV)
        res=self.io.pick_import("auto",staged)
        self.assertEqual(("scan.csv","findings_csv","Findings (CSV)"),(res["name"],res["kind"],res["label"]));self.assertEqual(3,res["summary"]["findings"])
        out=self.io.apply_import(res["path"],res["kind"],{"include_info":True})
        self.assertEqual({"reports","findings","templates","library","report_ids","message"},set(out));self.assertEqual(3,out["findings"])
        with self.assertRaises(ValueError):self.io.apply_import(res["path"],res["kind"])
    def test_auto_detects_every_kind_and_csv_lands_in_the_chosen_report(self):
        rep=svc.create_report({"title":"Target report","template_id":"blank"})
        files={"report_json":("r.json",json.dumps({"format":"loya-report","version":1,"report":{"id":999,"uid":"../../x","title":"Auto","sections":[{"id":5,"kind":"custom","title":"Code","content":"<pre data-lang=\"bash\" onclick=\"x()\">id</pre><script>alert(1)</script>"}],"findings":[]}})),
            "templates":("t.json",json.dumps({"format":"loya-report-templates","templates":[{"name":"Auto tpl","sections":[{"kind":"custom","title":"A","content":"<p>x</p>"}]}]})),
            "library":("l.json",json.dumps({"format":"loya-report-library","entries":[{"title":"Auto library entry","severity":"high"}]})),
            "findings_csv":("f.csv","Title,Severity,CVSS\nWeak cipher,Medium,5.3\nRCE,Critical,9.8\n")}
        for kind,(name,body) in files.items():
            res=self.io.pick_import("auto",self.stage(name,body))
            self.assertEqual(kind,res["kind"],name)
            out=self.io.apply_import(res["path"],res["kind"],{"report_id":rep["id"]} if kind=="findings_csv" else None)
            if kind=="report_json":
                got=svc.get_report(out["report_ids"][0]);self.assertNotEqual(999,got["id"]);self.assertNotEqual("../../x",got["uid"])
                self.assertEqual('<pre data-lang="bash">id</pre>',got["sections"][0]["content"])
            if kind=="findings_csv":
                self.assertEqual(([rep["id"]],0,2),(out["report_ids"],out["reports"],out["findings"]))
                self.assertEqual(["RCE","Weak cipher"],[f["title"] for f in svc.get_report(rep["id"])["findings"]])
        for name,body in (("junk.json","{not json"),("empty.json",""),("other.json",json.dumps({"hello":"world"})),("bin.json",b"\x00\x01\x02\xff"*50),("deep.json","["*100000)):
            with self.assertRaises(ValueError,msg=name):self.io.pick_import("auto",self.stage(name,body))
        with self.assertRaises(ValueError):self.io.pick_import("nonsense",self.stage("f2.csv","Title\nx\n"))
    def test_apply_refuses_paths_that_were_not_picked(self):
        outside=self.write("scan.csv",NESSUS_CSV)
        with self.assertRaises(ValueError):self.io.apply_import(outside,"findings_csv")
        with self.assertRaises(ValueError):self.io.pick_import("auto",outside)
        with self.assertRaises(ValueError):self.io.pick_import("nonsense",self.stage("a.csv",NESSUS_CSV))
        staged=self.stage("scan.csv",NESSUS_CSV);res=self.io.pick_import("findings_csv",staged)
        with self.assertRaises(ValueError):self.io.apply_import(res["path"],"exe")
        with self.assertRaises(ValueError):self.io.apply_import("","findings_csv")
        self.assertEqual([],svc.list_reports())
    def test_native_dialog_is_used_without_a_staged_file(self):
        path=self.write_json("r.json",{"format":"loya-report","version":1,"report":{"title":"Picked","sections":[],"findings":[]}})
        calls=[]
        class Win:
            def create_file_dialog(self,kind,directory="",file_types=(),**kw):
                calls.append(file_types);return (path,)
        self.io.bind(Win())
        res=self.io.pick_import("report_json")
        self.assertEqual(("report_json",1),(res["kind"],res["summary"]["reports"]));self.assertIn("*.json",calls[0][0])
        res=self.io.pick_import("auto");self.assertIn("*.json",calls[1][0]);self.assertIn("*.csv",calls[1][0])
        self.assertEqual("Picked",svc.get_report(self.io.apply_import(res["path"],res["kind"])["report_ids"][0])["title"])
        class Cancel:
            def create_file_dialog(self,*a,**k):return None
        self.io.bind(Cancel());self.assertIsNone(self.io.pick_import("auto"))
    def test_sniff_only_claims_files_with_our_format_marker(self):
        self.assertEqual({"kind":"report_json"},self.io.sniff(self.stage("a.json",json.dumps({"format":"loya-report","report":{}}))))
        self.assertEqual({"kind":"report_json"},self.io.sniff(self.stage("b.json",json.dumps({"format":"loya-report-bundle","reports":[]}))))
        self.assertEqual({"kind":"templates"},self.io.sniff(self.stage("c.json",json.dumps({"format":"loya-report-templates"}))))
        self.assertEqual({"kind":"library"},self.io.sniff(self.stage("d.json",json.dumps({"format":"loya-report-library"}))))
        self.assertEqual({"kind":""},self.io.sniff(self.stage("notes.json",json.dumps([{"note_name":"a","sections":[],"findings":[]}]))))
        self.assertEqual({"kind":""},self.io.sniff(self.stage("x.csv","Title,Severity\na,b\n")))
        with self.assertRaises(ValueError):self.io.sniff(self.write("out.json","{}"))
if __name__=="__main__":unittest.main()
