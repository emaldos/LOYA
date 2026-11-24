import os
os.environ.setdefault("LOYA_REPORT_PDF_ENGINE","fallback")  # the fpdf2 writer; the print engine has its own tests
import csv,json,shutil,zipfile,tempfile,subprocess,unittest
from _isolate import IsolatedData
import _report_fixture as fx
from Cores.Services import report_export as rx
from Cores.Services import report_export_pdf as rpdf
from Cores.Services import report_import as ri
from Cores.Services import reports_service as svc
from Cores.Bridge.reports_api import ReportsAPI
PDFTOTEXT=shutil.which("pdftotext")
VEC="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H"
V4="CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N"
XSS='<script>alert(1)</script><img src=x onerror=alert(2)>'
def cve(cid="CVE-2021-44228",**kw):
    e={"id":cid,"title":"Apache Log4j2 JNDI remote code execution","cvss_version":"3.1","cvss_vector":VEC,"cvss_score":10.0,"severity":"critical","cwe":"CWE-502","description":"Log4j2 JNDI features do not protect against attacker controlled LDAP endpoints.",
       "remediation":"Upgrade to 2.17.1 or later.","references":["https://logging.apache.org/log4j/2.x/security.html"],"kev":True,"kev_due":"2021-12-24","epss":0.97,"source":"cache","fetched_at":"2026-11-20T10:00:00Z"}
    e.update(kw)
    return e
def report_with_cves():
    rep=fx.report()
    rep["findings"][0]["cves"]=[cve(),cve("CVE-2024-3094",title="xz backdoor "+XSS,cvss_version="4.0",cvss_vector=V4,cvss_score=9.3,kev=False,kev_due="")]
    rep["findings"][1]["cves"]=[{"id":"CVE-2017-0144","title":"","cvss_vector":"","cvss_score":None}]
    return rep
class ModelTests(unittest.TestCase):
    def setUp(self):
        self.iso=IsolatedData();self.iso.start()
        self.api=ReportsAPI()
        self.rid=self.api.create({"title":"R","template_id":"blank"})["id"]
    def tearDown(self):self.iso.stop()
    def test_entry_is_stored_and_read_back(self):
        f=self.api.finding_add(self.rid,{"title":"Log4Shell","cves":[cve()]})
        self.assertEqual([cve()],f["cves"])
        self.assertEqual([cve()],self.api.get(self.rid)["findings"][0]["cves"])
        self.assertEqual([],self.api.finding_add(self.rid,{"title":"none"})["cves"])
    def test_bad_ids_are_dropped_and_ids_are_uppercased_and_unique(self):
        f=self.api.finding_add(self.rid,{"title":"x","cves":[{"id":"cve-2021-44228"},{"id":"CVE-2021-44228","title":"dup"},{"id":"CVE-21-1"},{"id":"CVE-2021-123"},{"id":"<script>"},{"id":"CVE-2021-44228; DROP"},"CVE-2020-0601",{"title":"no id"},None,7,{"id":"  CVE-2019-0708  "}]})
        self.assertEqual(["CVE-2021-44228","CVE-2020-0601","CVE-2019-0708"],[c["id"] for c in f["cves"]])
        self.assertEqual("",f["cves"][0]["title"])
    def test_caps_and_field_validation(self):
        f=self.api.finding_add(self.rid,{"title":"x","cves":[{"id":f"CVE-2024-{10000+i}"} for i in range(80)]})
        self.assertEqual(50,len(f["cves"]))
        refs=["https://example.com/a","HTTPS://example.com/a","http://example.com/b","javascript:alert(1)","ftp://example.com/c","data:text/html,x","https://exa mple.com/","https://example.com/\"onmouseover=x","file:///etc/passwd"]+[f"https://example.com/{i}" for i in range(60)]
        f=self.api.finding_update(f["id"],{"cves":[cve(title="t"*900,cvss_version="9.9",cvss_score="11",severity="bogus",cwe="c"*500,description="d"*30000,remediation="r"*30000,references=refs,kev="yes",kev_due="x"*100,epss=7,source="evil",fetched_at="z"*100)]})
        c=f["cves"][0]
        self.assertEqual(300,len(c["title"]));self.assertEqual("",c["cvss_version"]);self.assertIsNone(c["cvss_score"]);self.assertEqual("",c["severity"])
        self.assertEqual(120,len(c["cwe"]));self.assertEqual(20000,len(c["description"]));self.assertEqual(20000,len(c["remediation"]))
        self.assertEqual(30,len(c["references"]));self.assertEqual(["https://example.com/a","http://example.com/b","https://example.com/0"],c["references"][:3])
        self.assertTrue(all(r.lower().startswith(("http://","https://")) for r in c["references"]))
        self.assertIs(False,c["kev"]);self.assertEqual(40,len(c["kev_due"]));self.assertIsNone(c["epss"]);self.assertEqual("manual",c["source"]);self.assertEqual(40,len(c["fetched_at"]))
    def test_severity_falls_back_to_the_score_and_text_is_kept_as_plain_text(self):
        f=self.api.finding_add(self.rid,{"title":"x","cves":[{"id":"CVE-2024-3094","cvss_version":"4.0","cvss_vector":V4,"cvss_score":9.3,"title":XSS,"description":XSS,"epss":"0.5"}]})
        c=f["cves"][0]
        self.assertEqual("critical",c["severity"]);self.assertEqual(9.3,c["cvss_score"]);self.assertEqual(V4,c["cvss_vector"]);self.assertEqual(XSS,c["title"]);self.assertEqual(0.5,c["epss"])
    def test_a_v4_only_cve_gives_the_finding_a_score_without_a_vector(self):
        f=self.api.finding_add(self.rid,{"title":"xz","severity":"critical","cvss_vector":"","cvss_score":9.3,"cves":[cve("CVE-2024-3094",cvss_version="4.0",cvss_vector=V4,cvss_score=9.3)]})
        self.assertEqual("",f["cvss_vector"]);self.assertEqual(9.3,f["cvss_score"])
        f=self.api.finding_update(f["id"],{"cvss_vector":VEC,"cvss_score":10.0})
        self.assertEqual(10.0,f["cvss_score"])
        f=self.api.finding_update(f["id"],{"cvss_vector":"","cvss_score":9.3})
        self.assertEqual(("",9.3),(f["cvss_vector"],f["cvss_score"]))
    def test_patch_without_cves_keeps_them_and_an_empty_list_clears_them(self):
        f=self.api.finding_add(self.rid,{"title":"x","cves":[cve()]})
        self.assertEqual(1,len(self.api.finding_update(f["id"],{"title":"y"})["cves"]))
        self.assertEqual([],self.api.finding_update(f["id"],{"cves":[]})["cves"])
        self.assertEqual([],self.api.finding_update(f["id"],{"cves":"nonsense"})["cves"])
    def test_cves_survive_duplicate_version_restore_recycle_bin_and_the_library(self):
        f=self.api.finding_add(self.rid,{"title":"Log4Shell","cves":[cve()]})
        self.assertEqual("CVE-2021-44228",self.api.duplicate(self.rid)["findings"][0]["cves"][0]["id"])
        v=self.api.version_create(self.rid,"v1")
        self.api.finding_update(f["id"],{"cves":[]})
        self.assertEqual([cve()],self.api.version_restore(self.rid,v["id"])["findings"][0]["cves"])
        entry=self.api.library_save_from_finding(self.api.get(self.rid)["findings"][0]["id"],"Web")
        self.assertEqual([cve()],self.api.library_get(entry["id"])["cves"])
        self.assertEqual([cve()],self.api.finding_from_library(self.rid,entry["id"])["cves"])
    def test_source_kind_cve_is_kept(self):
        f=self.api.finding_add(self.rid,{"title":"x","source":{"kind":"cve","ref":"CVE-2021-44228"}})
        self.assertEqual({"kind":"cve","ref":"CVE-2021-44228"},f["source"])
class ExportTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.mkdtemp(prefix="loya_cve_")
    def tearDown(self):shutil.rmtree(self.tmp,ignore_errors=True)
    def out(self,name):return os.path.join(self.tmp,name)
    def test_prepare_lists_valid_cves_once(self):
        rep=fx.report();rep["findings"][0]["cves"]=[cve(),cve(),{"id":"nope"},"CVE-2020-0601",None]
        f=rx.prepare(rep)["findings"][0]
        self.assertEqual(["CVE-2021-44228","CVE-2020-0601"],[c["id"] for c in f["cves"]])
        self.assertEqual("https://nvd.nist.gov/vuln/detail/CVE-2021-44228",f["cves"][0]["url"]);self.assertEqual("10.0",f["cves"][0]["cvss"]);self.assertTrue(f["cves"][0]["kev"])
        self.assertEqual([],rx.prepare(fx.report())["findings"][0]["cves"])
    def test_html_has_linked_ids_kev_badge_and_the_details_table(self):
        html=rx.build_html(report_with_cves())
        for cid in ("CVE-2021-44228","CVE-2024-3094","CVE-2017-0144"):self.assertIn(f'<a href="https://nvd.nist.gov/vuln/detail/{cid}" target="_blank" rel="noopener noreferrer">{cid}</a>',html)
        self.assertIn("Known exploited",html);self.assertIn("CVE Details",html);self.assertIn("9.3 (v4.0)",html);self.assertIn(V4,html)
        self.assertNotIn("<script>alert(1)</script>",html.replace(fx.XSS,""));self.assertNotIn("<img src=x",html);self.assertIn("xz backdoor &lt;script&gt;",html)
        self.assertNotIn("<script",html.lower())
    def test_no_details_table_when_the_cve_rating_is_the_findings_own(self):
        rep=fx.report();f=rep["findings"][0]
        f["cves"]=[{"id":"CVE-2021-44228","title":"x","cvss_vector":f["cvss_vector"],"cvss_score":f["cvss_score"]}]
        html=rx.build_html(rep)
        self.assertIn("CVE-2021-44228",html);self.assertNotIn("CVE Details",html)
        self.assertNotIn("CVE Details",rx.build_html(fx.report()))
    def test_pdf(self):
        doc=rx.prepare(report_with_cves())
        p=self.out("r.pdf");rpdf.write_pdf(doc,p)
        with open(p,"rb") as f:data=f.read()
        self.assertTrue(data.startswith(b"%PDF-"))
        if not PDFTOTEXT:self.skipTest("pdftotext not installed: structure checked only")
        t=subprocess.run([PDFTOTEXT,"-layout",p,"-"],capture_output=True,timeout=60).stdout.decode("utf-8","replace")
        for needle in ("CVE-2021-44228","CVE-2024-3094","CVE-2017-0144","Known exploited","CVE DETAILS","9.3 (v4.0)"):self.assertIn(needle,t)
    def test_pdf_blocks_carry_the_cves_without_pdftotext(self):
        doc=rx.prepare(report_with_cves())
        text=rx.blocks_text([b for s in doc["sections"] for b in s["blocks"]])
        for needle in ("CVE-2021-44228 (Known exploited), CVE-2024-3094","CVE-2017-0144","CVE Details","9.3 (v4.0)"):self.assertIn(needle,text)
    def test_docx(self):
        import docx
        p=rx.render(report_with_cves(),"docx",self.out("r.docx"))
        d=docx.Document(p)
        cells="\n".join(c.text for t in d.tables for row in t.rows for c in row.cells)
        for needle in ("CVE-2021-44228","CVE-2024-3094","CVE-2017-0144","Known exploited","9.3 (v4.0)"):self.assertIn(needle,cells)
        with zipfile.ZipFile(p) as z:rels=z.read("word/_rels/document.xml.rels").decode("utf-8")
        self.assertIn("https://nvd.nist.gov/vuln/detail/CVE-2021-44228",rels)
    def test_markdown(self):
        p=rx.render(report_with_cves(),"markdown",self.out("r.zip"))
        with zipfile.ZipFile(p) as z:md=z.read("report.md").decode("utf-8")
        self.assertIn("[CVE-2021-44228](<https://nvd.nist.gov/vuln/detail/CVE-2021-44228>)",md);self.assertIn("**CVE**",md);self.assertIn("Known exploited",md);self.assertIn("**CVE Details**",md)
        self.assertNotIn("<script>alert(1)</script>",md.replace(fx.XSS,""))
    def test_csv_and_xlsx_have_a_cve_column(self):
        self.assertEqual("CVE",rx.FINDING_COLUMNS[-1])
        p=rx.render(report_with_cves(),"csv",self.out("f.csv"))
        with open(p,encoding="utf-8-sig",newline="") as f:rows=list(csv.reader(f))
        at=rows[0].index("CVE")
        self.assertEqual("CVE-2021-44228, CVE-2024-3094",rows[1][at]);self.assertEqual("CVE-2017-0144",rows[2][at]);self.assertEqual("",rows[3][at])
        p=rx.render(report_with_cves(),"xlsx",self.out("f.xlsx"))
        with zipfile.ZipFile(p) as z:xml=z.read("xl/worksheets/sheet1.xml").decode("utf-8")+"".join(z.read(n).decode("utf-8") for n in z.namelist() if n.endswith("sharedStrings.xml"))
        self.assertIn("CVE-2021-44228, CVE-2024-3094",xml);self.assertIn(">CVE<",xml)
    def test_sarif_properties_and_tags(self):
        s=rx.build_sarif(rx.prepare(report_with_cves()))
        run=s["runs"][0];rule=run["tool"]["driver"]["rules"][0];res=run["results"][0]
        self.assertEqual(["CVE-2021-44228","CVE-2024-3094"],rule["properties"]["cve"]);self.assertEqual(["CVE-2021-44228","CVE-2024-3094"],res["properties"]["cve"])
        self.assertIn("CVE-2021-44228",rule["properties"]["tags"])
        self.assertNotIn("cve",run["tool"]["driver"]["rules"][2]["properties"]);self.assertNotIn("cve",run["results"][2]["properties"])
    def test_json_keeps_every_field(self):
        rep=report_with_cves()
        data=rx.build_json(rep)
        self.assertEqual(rep["findings"][0]["cves"],json.loads(json.dumps(data))["report"]["findings"][0]["cves"])
class ImportTests(unittest.TestCase):
    def setUp(self):
        self.iso=IsolatedData();self.iso.start()
        self.tmp=tempfile.mkdtemp(prefix="loya_cvei_")
    def tearDown(self):
        shutil.rmtree(self.tmp,ignore_errors=True);self.iso.stop()
    def write(self,name,text):
        p=os.path.join(self.tmp,name)
        with open(p,"w",encoding="utf-8",newline="") as f:f.write(text)
        return p
    def test_json_round_trip(self):
        rid=svc.create_report({"title":"Round trip","template_id":"blank"})["id"]
        svc.add_finding(rid,{"title":"Log4Shell","severity":"critical","cves":[cve(),cve("CVE-2024-3094",cvss_version="4.0",cvss_vector=V4,cvss_score=9.3,kev=False,kev_due="",title=XSS)]})
        before=svc.get_report(rid)
        p=rx.render(before,"json",os.path.join(self.tmp,"r.json"))
        res=ri.apply(p,"report_json")
        after=svc.get_report(res["report_ids"][0])
        self.assertNotEqual(rid,after["id"]);self.assertEqual(before["findings"][0]["cves"],after["findings"][0]["cves"]);self.assertEqual(2,len(after["findings"][0]["cves"]))
    def test_hostile_json_cves_are_normalised_on_import(self):
        rid=svc.create_report({"title":"H","template_id":"blank"})["id"]
        svc.add_finding(rid,{"title":"x","cves":[cve()]})
        p=rx.render(svc.get_report(rid),"json",os.path.join(self.tmp,"h.json"))
        with open(p,encoding="utf-8") as f:data=json.load(f)
        data["report"]["findings"][0]["cves"]=[{"id":"<img src=x>"},{"id":"cve-2020-0601","references":["javascript:alert(1)","https://ok.example/"],"kev":"1","cvss_score":"99"},"garbage",{"id":"CVE-2020-0601"}]
        with open(p,"w",encoding="utf-8") as f:json.dump(data,f)
        after=svc.get_report(ri.apply(p,"report_json")["report_ids"][0])
        c=after["findings"][0]["cves"]
        self.assertEqual(["CVE-2020-0601"],[x["id"] for x in c]);self.assertEqual(["https://ok.example/"],c[0]["references"]);self.assertIs(False,c[0]["kev"]);self.assertIsNone(c[0]["cvss_score"])
    def test_findings_csv_cve_column_becomes_cves(self):
        p=self.write("f.csv","Title,Severity,CVE,References\r\nLog4Shell,Critical,\"cve-2021-44228, CVE-2021-45046 and junk CVE-1-2\",https://a.example/\r\nNo cve,Low,,\r\n")
        res=ri.apply(p,"findings_csv")
        fs={f["title"]:f for f in svc.get_report(res["report_ids"][0])["findings"]}
        self.assertEqual(["CVE-2021-44228","CVE-2021-45046"],[c["id"] for c in fs["Log4Shell"]["cves"]])
        self.assertEqual("manual",fs["Log4Shell"]["cves"][0]["source"])
        self.assertIn("https://nvd.nist.gov/vuln/detail/CVE-2021-44228",fs["Log4Shell"]["references"])
        self.assertEqual([],fs["No cve"]["cves"])
    def test_exported_csv_reads_back_with_its_cves(self):
        rid=svc.create_report({"title":"C","template_id":"blank"})["id"]
        svc.add_finding(rid,{"title":"Log4Shell","severity":"critical","cves":[cve(),cve("CVE-2021-45046")]})
        p=rx.render(svc.get_report(rid),"csv",os.path.join(self.tmp,"e.csv"))
        res=ri.apply(p,"findings_csv")
        self.assertEqual(["CVE-2021-44228","CVE-2021-45046"],[c["id"] for c in svc.get_report(res["report_ids"][0])["findings"][0]["cves"]])
    def test_library_export_import_keeps_cves(self):
        e=svc.library_save({"title":"Log4Shell unique entry","category":"Web","severity":"critical","cves":[cve()]})
        self.assertEqual([cve()],e["cves"])
        data=ri.build_library_export()
        self.assertEqual([cve()],[x for x in data["entries"] if x["title"]=="Log4Shell unique entry"][0]["cves"])
if __name__=="__main__":unittest.main()
