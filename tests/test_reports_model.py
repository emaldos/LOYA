import base64,json,os,sqlite3,struct,unittest,zlib
from datetime import datetime,timedelta,timezone
from _isolate import IsolatedData
from Cores import common_db,recycle_bin,target_profiles
from Cores.Services import reports_service as reports
from Cores.Services import report_templates
from Cores.Bridge.reports_api import ReportsAPI
VEC="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"
def png(w=3,h=2,seed=0):
    def chunk(tag,data):return struct.pack(">I",len(data))+tag+data+struct.pack(">I",zlib.crc32(tag+data)&0xffffffff)
    raw=b"".join(b"\x00"+bytes([seed%256,0,0])*w for _ in range(h))
    return b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR",struct.pack(">IIBBBBB",w,h,8,2,0,0,0))+chunk(b"IDAT",zlib.compress(raw))+chunk(b"IEND",b"")
GIF=b"GIF89a"+struct.pack("<HH",5,4)+b"\x80\x00\x00"+b"\x00\x00\x00\xff\xff\xff"+b"!\xf9\x04\x00\x00\x00\x00\x00,\x00\x00\x00\x00\x05\x00\x04\x00\x00\x02\x04\x84\x8f\xa9\x58\x00;"
class Base(unittest.TestCase):
    def setUp(self):
        self.isolated=IsolatedData()
        self.dir=self.isolated.start()
        self.api=ReportsAPI()
    def tearDown(self):
        common_db.set_locked(False)
        self.isolated.stop()
    def db(self):return sqlite3.connect(common_db.db_path())
    def count(self,table,where="1=1",args=()):
        con=self.db()
        try:return con.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}",args).fetchone()[0]
        finally:con.close()
class ReportCrudTests(Base):
    def test_create_get_shape(self):
        rep=self.api.create({"title":"  ACME web test  ","template_id":"web_app"})
        self.assertEqual("ACME web test",rep["title"])
        self.assertEqual({"id","uid","title","status","template_id","profile_id","created_at","updated_at","meta","branding","options","sections","targets","findings","versions","stats"},set(rep))
        self.assertEqual("draft",rep["status"]);self.assertEqual("web_app",rep["template_id"]);self.assertEqual("",rep["profile_id"])
        self.assertEqual({"client","client_contact","engagement","project_code","report_type","start_date","end_date","report_date","testers","scope_in","scope_out","rules_of_engagement","methodology","classification","version","authors","reviewers","distribution"},set(rep["meta"]))
        self.assertEqual({"company","logo_asset","accent","secondary","banner","footer","cover_subtitle","show_cover","theme","font","cover_style"},set(rep["branding"]))
        self.assertEqual({"page_size","include_toc","include_appendices","number_sections","finding_id_prefix"},set(rep["options"]))
        self.assertEqual({"counts":{"critical":0,"high":0,"medium":0,"low":0,"info":0},"total":0,"open":0,"by_status":{"open":0,"retest":0,"fixed":0,"accepted":0}},rep["stats"])
        self.assertEqual("Confidential",rep["meta"]["classification"])
        self.assertRegex(rep["meta"]["report_date"],r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual(rep,self.api.get(rep["id"]))
        self.assertEqual(rep,reports.get_report(rep["uid"]))
        for s in rep["sections"]:self.assertEqual({"id","uid","kind","title","content","position","hidden","options"},set(s))
        self.assertEqual(list(range(len(rep["sections"]))),[s["position"] for s in rep["sections"]])
    def test_get_missing_report(self):
        for bad in (999,"nope",None,"12x"):
            with self.assertRaisesRegex(ValueError,"Report not found."):self.api.get(bad)
    def test_create_defaults_and_unknown_template(self):
        rep=self.api.create({})
        self.assertEqual("Untitled report",rep["title"]);self.assertEqual("blank",rep["template_id"]);self.assertEqual([],rep["sections"])
        with self.assertRaisesRegex(ValueError,"Template not found."):self.api.create({"title":"x","template_id":"no_such"})
    def test_profile_scope_leaves_out_credentials_and_non_addresses(self):
        ok,_,pid=target_profiles.create_profile("Creds")
        self.assertTrue(ok)
        with open(target_profiles.profile_targets_json_path(pid),"w",encoding="utf-8") as fh:
            json.dump([{"id":"t1","name":"dc01","values":{"IPv4":"172.16.5.10","Password":"Summer2026!","Pass2":"corp.example","Username":"j.doe","Port":"445","Wordlist":"/usr/share/wordlists/rockyou.txt","URL":"https://portal.example/login","Net":"10.0.0.0/24","Domain":"globex.local","NTLM_Hash":"aad3b435b51404eeaad3b435b51404ee:31d6cfe0d16ae931b73c59d7e0c089c0"}}],fh)
        rep=self.api.create({"title":"R","template_id":"blank","profile_id":pid})
        self.assertEqual(["dc01: 172.16.5.10, https://portal.example/login, 10.0.0.0/24, globex.local"],rep["meta"]["scope_in"])
    def test_create_with_profile_seeds_engagement_and_scope(self):
        ok,_,pid=target_profiles.create_profile("Globex internal")
        self.assertTrue(ok)
        with open(target_profiles.profile_targets_json_path(pid),"w",encoding="utf-8") as fh:
            json.dump([{"id":"t1","name":"DC01","status":"live","engagement_status":"compromised","values":{"IP":"10.0.0.5","HOST":"dc01.globex.local","DUP":"10.0.0.5","EMPTY":""}},{"id":"t2","name":"Printer","values":{}},{"name":""},"junk"],fh)
        rep=self.api.create({"title":"R","template_id":"internal_network","profile_id":pid,"meta":{"client":"Globex"}})
        self.assertEqual(pid,rep["profile_id"])
        self.assertEqual("Globex internal",rep["meta"]["engagement"])
        self.assertEqual(["DC01: 10.0.0.5, dc01.globex.local","Printer"],rep["meta"]["scope_in"])
        self.assertEqual("Globex",rep["meta"]["client"])
        row=self.api.list()[0]
        self.assertEqual({"id","uid","title","status","client","profile_id","profile_name","template_id","updated_at","created_at","counts","total"},set(row))
        self.assertEqual("Globex internal",row["profile_name"]);self.assertEqual("Globex",row["client"])
        src=self.api.sources(pid)
        self.assertEqual(pid,src["profile_id"])
        # SA-27: the pickers get public values only (empty and secret-named ones dropped) plus the secret key names.
        self.assertEqual([{"id":"t1","name":"DC01","values":{"IP":"10.0.0.5","HOST":"dc01.globex.local","DUP":"10.0.0.5"},"secret_keys":[],"status":"live","engagement_status":"compromised"},{"id":"t2","name":"Printer","values":{},"secret_keys":[],"status":"not_used","engagement_status":"not_started"}],[{k:v for k,v in t.items()} for t in src["targets"]])
        self.assertEqual([],self.api.sources()["targets"])
        self.assertEqual("",self.api.create({"title":"x","profile_id":"missing"})["profile_id"])
    def test_update_is_a_merge_patch(self):
        rep=self.api.create({"title":"R","template_id":"blank","meta":{"client":"ACME","scope_in":["a"]},"branding":{"company":"Red Co","accent":"#112233"}})
        out=self.api.update(rep["id"],{"title":"R2","status":"review","meta":{"client_contact":"Jo","start_date":"2026-11-01","end_date":"not a date","testers":[{"name":"A","role":"Lead","email":"a@x.io","extra":1},"B",{}],"scope_out":"x\ny\n\n","autogen":{"hosts":[1]}},"branding":{"accent":"red","secondary":"#ABCDEF","show_cover":False},"options":{"page_size":"Letter","include_toc":False,"finding_id_prefix":"VULN-","bogus":1},"unknown":"ignored","id":77,"uid":"zzz"})
        self.assertEqual({"id","updated_at"},set(out))
        got=self.api.get(rep["id"])
        self.assertEqual(out["updated_at"],got["updated_at"]);self.assertEqual(rep["uid"],got["uid"])
        self.assertEqual("R2",got["title"]);self.assertEqual("review",got["status"])
        m=got["meta"]
        self.assertEqual("ACME",m["client"]);self.assertEqual(["a"],m["scope_in"]);self.assertEqual("Jo",m["client_contact"])
        self.assertEqual("2026-11-01",m["start_date"]);self.assertEqual("",m["end_date"])
        self.assertEqual([{"name":"A","role":"Lead","email":"a@x.io"},{"name":"B","role":"","email":""}],m["testers"])
        self.assertEqual(["x","y"],m["scope_out"]);self.assertEqual({"hosts":[1]},m["autogen"])
        self.assertEqual("Red Co",got["branding"]["company"]);self.assertEqual("#112233",got["branding"]["accent"]);self.assertEqual("#abcdef",got["branding"]["secondary"]);self.assertFalse(got["branding"]["show_cover"])
        self.assertEqual({"page_size":"Letter","include_toc":False,"include_appendices":True,"number_sections":True,"finding_id_prefix":"VULN-"},got["options"])
        with self.assertRaisesRegex(ValueError,"status"):self.api.update(rep["id"],{"status":"published"})
        with self.assertRaisesRegex(ValueError,"title"):self.api.update(rep["id"],{"title":"   "})
        with self.assertRaises(ValueError):self.api.update(rep["id"],{"profile_id":"missing"})
        with self.assertRaises(ValueError):self.api.update(rep["id"],"x")
        self.api.update(rep["id"],{"title":"t"*500,"meta":{"client":"c"*999}})
        got=self.api.get(rep["id"])
        self.assertEqual(300,len(got["title"]));self.assertEqual(200,len(got["meta"]["client"]))
    def test_duplicate(self):
        rep=self.api.create({"title":"Orig","template_id":"retest_short"})
        self.api.finding_add(rep["id"],{"title":"F1","severity":"high"})
        self.api.version_create(rep["id"],"v1")
        dup=self.api.duplicate(rep["id"])
        self.assertEqual("Orig (copy)",dup["title"]);self.assertNotEqual(rep["uid"],dup["uid"]);self.assertEqual("draft",dup["status"])
        self.assertEqual(len(rep["sections"]),len(dup["sections"]));self.assertEqual(["F1"],[f["title"] for f in dup["findings"]])
        self.assertEqual([],dup["versions"])
        self.assertFalse({s["uid"] for s in rep["sections"]}&{s["uid"] for s in dup["sections"]})
        self.assertEqual(2,len(self.api.list()))
class SectionTests(Base):
    def test_add_update_delete_reorder(self):
        rep=self.api.create({"title":"R"})
        a=self.api.section_add(rep["id"],{"kind":"executive_summary","title":"Summary","content":"<p onclick=x>Hi<script>1</script></p>"})
        b=self.api.section_add(rep["id"],{"kind":"nonsense","title":""})
        c=self.api.section_add(rep["id"],{"kind":"custom","title":"Middle","after_id":a["id"]})
        d=self.api.section_add(rep["id"],{"kind":"scope","after_id":0})
        self.assertEqual("<p>Hi</p>",a["content"]);self.assertEqual("custom",b["kind"]);self.assertEqual("New Section",b["title"]);self.assertEqual("Scope and Rules of Engagement",d["title"])
        order=lambda:[s["id"] for s in self.api.get(rep["id"])["sections"]]
        self.assertEqual([d["id"],a["id"],c["id"],b["id"]],order())
        out=self.api.section_update(a["id"],{"title":"Exec","content":"<h3>T</h3><img src=x onerror=1>","hidden":1,"options":{"page_break":True},"position":99,"report_id":5})
        self.assertEqual({"id","updated_at"},set(out))
        s=[x for x in self.api.get(rep["id"])["sections"] if x["id"]==a["id"]][0]
        self.assertEqual(("Exec","<h3>T</h3>",True,{"page_break":True},1),(s["title"],s["content"],s["hidden"],s["options"],s["position"]))
        self.api.section_update(a["id"],{"hidden":False,"options":{"x":1,"page_break":None}})
        s=[x for x in self.api.get(rep["id"])["sections"] if x["id"]==a["id"]][0]
        self.assertEqual(("Exec","<h3>T</h3>",False,{"x":1}),(s["title"],s["content"],s["hidden"],s["options"]))
        self.assertTrue(self.api.sections_reorder(rep["id"],[b["id"],"junk",9999,a["id"],b["id"]]))
        self.assertEqual([b["id"],a["id"],d["id"],c["id"]],order())
        self.assertEqual([0,1,2,3],[s["position"] for s in self.api.get(rep["id"])["sections"]])
        self.assertTrue(self.api.section_delete(a["id"]))
        self.assertEqual([0,1,2],[s["position"] for s in self.api.get(rep["id"])["sections"]])
        with self.assertRaisesRegex(ValueError,"Section not found."):self.api.section_delete(a["id"])
        with self.assertRaisesRegex(ValueError,"Section not found."):self.api.section_update(12345,{"title":"x"})
        with self.assertRaisesRegex(ValueError,"Report not found."):self.api.section_add(999,{"kind":"custom"})
    def test_other_reports_sections_are_not_reordered(self):
        r1=self.api.create({"title":"1","template_id":"retest_short"});r2=self.api.create({"title":"2","template_id":"retest_short"})
        before=[s["id"] for s in r2["sections"]]
        self.api.sections_reorder(r1["id"],list(reversed(before)))
        self.assertEqual(before,[s["id"] for s in self.api.get(r2["id"])["sections"]])
        self.assertEqual([s["id"] for s in r1["sections"]],[s["id"] for s in self.api.get(r1["id"])["sections"]])
    def test_service_add_section_accepts_keywords(self):
        rep=reports.create_report({"title":"R"})
        s=reports.add_section(rep["id"],kind="appendix_tools",title="Tools",content="<p>x</p>")
        self.assertEqual(("appendix_tools","Tools","<p>x</p>"),(s["kind"],s["title"],s["content"]))
class FindingTests(Base):
    def setUp(self):
        super().setUp()
        self.rep=self.api.create({"title":"R"})
        self.rid=self.rep["id"]
    def test_add_shape_and_defaults(self):
        f=self.api.finding_add(self.rid,{})
        self.assertEqual({"id","uid","report_id","position","title","severity","cvss_vector","cvss_score","status","cwe","owasp","references","affected","description","impact","likelihood","steps","remediation","evidence","tags","retest_notes","source","cves","targets","created_at","updated_at"},set(f))
        self.assertEqual(("Untitled finding","info","",None,"open",0),(f["title"],f["severity"],f["cvss_vector"],f["cvss_score"],f["status"],f["position"]))
        self.assertEqual({"kind":"","ref":""},f["source"])
        self.assertEqual(1,self.api.finding_add(self.rid,{"title":"b"})["position"])
    def test_add_normalises_fields(self):
        f=self.api.finding_add(self.rid,{"title":"x"*400,"cvss_vector":"AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H","status":"Retest","cwe":"CWE-89","owasp":"A03:2021 Injection","references":"https://a\nhttps://b\n","affected":[{"target_id":"t1","name":"DC01","value":"10.0.0.5","x":1},"web01",{},5],
            "description":"<p>d</p><script>x</script>","impact":"<div>i</div>","steps":"<ol><li>s</li></ol>","remediation":"<p style='x'>r</p>","likelihood":"HIGH","tags":"sqli, web;SQLi","retest_notes":"n",
            "evidence":[{"evidence_uid":"ev1","asset_uid":"as1","caption":"c"},{"asset_uid":"rptasset:as2"},{"caption":"none"},"x"],"source":{"kind":"Note","ref":7},"id":999,"report_id":5,"uid":"mine","position":42})
        self.assertEqual(300,len(f["title"]));self.assertEqual("critical",f["severity"]);self.assertEqual(VEC,f["cvss_vector"]);self.assertEqual(9.8,f["cvss_score"]);self.assertEqual("retest",f["status"])
        self.assertEqual(["https://a","https://b"],f["references"])
        self.assertEqual([{"target_id":"t1","name":"DC01","value":"10.0.0.5"},{"target_id":"","name":"web01","value":""}],f["affected"])
        self.assertEqual(("<p>d</p>","i","<ol><li>s</li></ol>","<p>r</p>","high"),(f["description"],f["impact"],f["steps"],f["remediation"],f["likelihood"]))
        self.assertEqual(["sqli","web"],f["tags"])
        self.assertEqual([{"evidence_uid":"ev1","asset_uid":"","caption":"c"},{"evidence_uid":"","asset_uid":"as2","caption":""}],f["evidence"])
        self.assertEqual({"kind":"note","ref":"7"},f["source"])
        self.assertEqual((self.rid,0),(f["report_id"],f["position"]));self.assertNotEqual("mine",f["uid"])
    def test_update_is_a_merge_patch_and_recomputes_cvss(self):
        f=self.api.finding_add(self.rid,{"title":"T","severity":"low","description":"<p>d</p>","tags":["a"],"cvss_vector":VEC})
        self.assertEqual("low",f["severity"])
        g=self.api.finding_update(f["id"],{"impact":"<p>i</p>","cvss_score":1.0,"bogus":1})
        self.assertEqual(("T","low","<p>d</p>","<p>i</p>",["a"],VEC,9.8),(g["title"],g["severity"],g["description"],g["impact"],g["tags"],g["cvss_vector"],g["cvss_score"]))
        g=self.api.finding_update(f["id"],{"cvss_vector":"CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:C/C:L/I:L/A:N","cvss_score":9.9})
        self.assertEqual((6.1,"low"),(g["cvss_score"],g["severity"]))
        g=self.api.finding_update(f["id"],{"cvss_vector":"AV:N/garbage"})
        self.assertEqual(("AV:N/garbage",None),(g["cvss_vector"],g["cvss_score"]))
        g=self.api.finding_update(f["id"],{"cvss_vector":"","cvss_score":"7,5"})
        self.assertEqual(("",7.5),(g["cvss_vector"],g["cvss_score"]))
        self.assertIsNone(self.api.finding_update(f["id"],{"cvss_score":11})["cvss_score"])
        g=self.api.finding_update(f["id"],{"severity":"Informational","status":"fixed","tags":[],"likelihood":"whatever"})
        self.assertEqual(("info","fixed",[],""),(g["severity"],g["status"],g["tags"],g["likelihood"]))
        self.assertGreaterEqual(g["updated_at"],f["updated_at"]);self.assertEqual(f["created_at"],g["created_at"])
        for bad in ({"severity":"urgent"},{"severity":""},{"status":"wontfix"}):
            with self.assertRaises(ValueError):self.api.finding_update(f["id"],bad)
        with self.assertRaisesRegex(ValueError,"Finding not found."):self.api.finding_update(9999,{"title":"x"})
        with self.assertRaises(ValueError):self.api.finding_add(self.rid,{"severity":"urgent"})
        self.assertEqual(g,self.api.finding_get(f["id"]))
    def test_reorder_and_sort(self):
        mk=lambda t,s,v=None,st="open":self.api.finding_add(self.rid,{"title":t,"severity":s,"cvss_score":v,"status":st})["id"]
        low=mk("b low","low",3.1);crit=mk("a crit","critical",9.8,"fixed");med=mk("c med","medium",5.0,"retest");high=mk("d high","high",None,"accepted");info=mk("A info","info",0)
        ids=lambda fs:[f["id"] for f in fs]
        self.assertTrue(self.api.findings_reorder(self.rid,[info,crit]))
        got=self.api.get(self.rid)["findings"]
        self.assertEqual([info,crit,low,med,high],ids(got));self.assertEqual([0,1,2,3,4],[f["position"] for f in got])
        self.assertEqual([crit,high,med,low,info],ids(self.api.findings_sort(self.rid,"severity")))
        self.assertEqual([crit,high,med,low,info],ids(self.api.get(self.rid)["findings"]))
        self.assertEqual([crit,med,low,info,high],ids(self.api.findings_sort(self.rid,"cvss")))
        self.assertEqual([crit,info,low,med,high],ids(self.api.findings_sort(self.rid,"title")))
        self.assertEqual([low,med,high,crit,info][:1]+[info,med,high,crit],ids(self.api.findings_sort(self.rid,"status")))
        with self.assertRaises(ValueError):self.api.findings_sort(self.rid,"random")
        st=self.api.get(self.rid)["stats"]
        self.assertEqual({"critical":1,"high":1,"medium":1,"low":1,"info":1},st["counts"]);self.assertEqual((5,2),(st["total"],st["open"]));self.assertEqual({"open":2,"retest":1,"fixed":1,"accepted":1},st["by_status"])
        self.assertEqual({"critical":1,"high":1,"medium":1,"low":1,"info":1},self.api.list()[0]["counts"]);self.assertEqual(5,self.api.list()[0]["total"])
        self.assertEqual({"critical":1,"high":0,"medium":0,"low":0,"info":2},reports.severity_counts([{"severity":"critical"},{"severity":"??"},{},"x"][:3]))
    def test_stats_for_the_dashboard(self):
        self.assertEqual({"reports":1,"by_status":{"draft":1,"review":0,"final":0},"findings":{"critical":0,"high":0,"medium":0,"low":0,"info":0},"open_by_severity":{"critical":0,"high":0,"medium":0,"low":0,"info":0},"open_findings":0,"recent":[{"id":self.rid,"title":"R","status":"draft","updated_at":self.api.get(self.rid)["updated_at"]}],"next_deadline":None,"overdue":0},self.api.stats())
        other=self.api.create({"title":"Other"});self.api.update(other["id"],{"status":"final"})
        self.api.finding_add(self.rid,{"title":"a","severity":"high"});self.api.finding_add(other["id"],{"title":"b","severity":"high","status":"fixed"});self.api.finding_add(other["id"],{"title":"c","severity":"low"})
        for i in range(6):self.api.create({"title":f"n{i}"})
        st=self.api.stats()
        self.assertEqual(8,st["reports"]);self.assertEqual({"draft":7,"review":0,"final":1},st["by_status"]);self.assertEqual(2,st["findings"]["high"]);self.assertEqual(1,st["findings"]["low"]);self.assertEqual(2,st["open_findings"])
        self.assertEqual(5,len(st["recent"]));self.assertEqual("n5",st["recent"][0]["title"])
class RecycleBinTests(Base):
    def test_report_delete_and_restore(self):
        rep=self.api.create({"title":"Doomed","template_id":"web_app","meta":{"client":"ACME"}})
        f=self.api.finding_add(rep["id"],{"title":"SQLi","cvss_vector":VEC,"description":"<p>d</p>"})
        self.api.version_create(rep["id"],"v1")
        self.assertTrue(self.api.delete(rep["id"]))
        with self.assertRaisesRegex(ValueError,"Report not found."):self.api.get(rep["id"])
        for t in ("Reports","ReportSections","ReportFindings","ReportVersions"):self.assertEqual(0,self.count(t))
        entries=recycle_bin.list_entries()
        self.assertEqual(1,len(entries))
        e=entries[0]
        self.assertEqual(("report","Doomed",rep["uid"],"ACME"),(e["entity_type"],e["label"],e["entity_key"],e["source"]))
        self.assertEqual("Report",recycle_bin.TYPE_LABELS[e["entity_type"]])
        self.assertEqual((True,"Restored"),recycle_bin.restore_entry(e["id"]))
        self.assertEqual([],recycle_bin.list_entries())
        back=self.api.list()[0]
        got=self.api.get(back["id"])
        self.assertEqual(rep["uid"],got["uid"]);self.assertNotEqual(rep["id"],got["id"]);self.assertEqual("Doomed",got["title"]);self.assertEqual("ACME",got["meta"]["client"])
        self.assertEqual([(s["uid"],s["kind"],s["title"],s["content"]) for s in rep["sections"]],[(s["uid"],s["kind"],s["title"],s["content"]) for s in got["sections"]])
        self.assertEqual([(f["uid"],"SQLi",9.8,"<p>d</p>")],[(x["uid"],x["title"],x["cvss_score"],x["description"]) for x in got["findings"]])
        self.assertEqual(["v1"],[v["label"] for v in got["versions"]])
    def test_restoring_a_report_twice_does_not_clash(self):
        rep=self.api.create({"title":"A"})
        self.api.delete(rep["id"])
        payload=recycle_bin.list_entries()[0]["payload"]
        recycle_bin.put_entry(recycle_bin.TYPE_REPORT,"A",payload,entity_key=rep["uid"])
        for e in recycle_bin.list_entries():self.assertEqual((True,"Restored"),recycle_bin.restore_entry(e["id"]))
        uids=[r["uid"] for r in self.api.list()]
        self.assertEqual(2,len(set(uids)));self.assertIn(rep["uid"],uids)
    def test_finding_delete_and_restore_keeps_position(self):
        rep=self.api.create({"title":"R"})
        a,b,c=[self.api.finding_add(rep["id"],{"title":t,"severity":"medium","tags":[t]}) for t in "abc"]
        self.assertTrue(self.api.finding_delete(b["id"]))
        self.assertEqual([("a",0),("c",1)],[(f["title"],f["position"]) for f in self.api.get(rep["id"])["findings"]])
        e=recycle_bin.list_entries()[0]
        self.assertEqual(("report_finding","b",b["uid"],"R"),(e["entity_type"],e["label"],e["entity_key"],e["source"]))
        self.assertEqual((True,"Restored"),recycle_bin.restore_entry(e["id"]))
        got=self.api.get(rep["id"])["findings"]
        self.assertEqual([("a",0),("b",1),("c",2)],[(f["title"],f["position"]) for f in got])
        self.assertEqual((b["uid"],["b"],"medium"),(got[1]["uid"],got[1]["tags"],got[1]["severity"]))
    def test_finding_restore_needs_its_report(self):
        rep=self.api.create({"title":"R"})
        f=self.api.finding_add(rep["id"],{"title":"f"})
        self.api.finding_delete(f["id"]);self.api.delete(rep["id"])
        by={e["entity_type"]:e for e in recycle_bin.list_entries()}
        ok,msg=recycle_bin.restore_entry(by["report_finding"]["id"])
        self.assertFalse(ok);self.assertIn("no longer exists",msg)
        self.assertEqual(2,len(recycle_bin.list_entries()))
        self.assertTrue(recycle_bin.restore_entry(by["report"]["id"])[0])
        self.assertTrue(recycle_bin.restore_entry(by["report_finding"]["id"])[0])
        self.assertEqual(["f"],[x["title"] for x in self.api.get(self.api.list()[0]["id"])["findings"]])
    def test_invalid_payload_is_refused(self):
        ok,rid=recycle_bin.put_entry(recycle_bin.TYPE_REPORT,"x",{"report":{}})
        self.assertEqual((False,"Recycle Bin report payload is invalid."),recycle_bin.restore_entry(rid))
class VersionTests(Base):
    def test_create_restore_delete(self):
        rep=self.api.create({"title":"V","template_id":"retest_short","meta":{"client":"ACME"}})
        rid=rep["id"]
        f=self.api.finding_add(rid,{"title":"keep","severity":"high"})
        v=self.api.version_create(rid,"Draft sent to client")
        self.assertEqual({"id","label","created_at"},set(v));self.assertEqual("Draft sent to client",v["label"])
        self.assertTrue(self.api.version_create(rid,"")["label"].startswith("Version 1.0"))
        self.api.update(rid,{"title":"V changed","status":"final","meta":{"client":"Other"}})
        self.api.finding_update(f["id"],{"title":"changed"});self.api.finding_add(rid,{"title":"new"})
        self.api.section_delete(rep["sections"][0]["id"]);self.api.section_update(rep["sections"][1]["id"],{"content":"<p>edited</p>"})
        back=self.api.version_restore(rid,v["id"])
        self.assertEqual((rid,rep["uid"],"V","draft","ACME"),(back["id"],back["uid"],back["title"],back["status"],back["meta"]["client"]))
        self.assertEqual([(f["uid"],"keep")],[(x["uid"],x["title"]) for x in back["findings"]])
        self.assertEqual([(s["uid"],s["content"]) for s in rep["sections"]],[(s["uid"],s["content"]) for s in back["sections"]])
        labels=[x["label"] for x in self.api.versions(rid)]
        self.assertEqual(3,len(labels));self.assertTrue(any(l.startswith("Before restoring") for l in labels))
        auto=[x for x in self.api.versions(rid) if x["label"].startswith("Before restoring")][0]
        self.assertEqual("V changed",self.api.version_restore(rid,auto["id"])["title"])
        self.assertTrue(self.api.version_delete(v["id"]))
        self.assertNotIn(v["id"],[x["id"] for x in self.api.versions(rid)])
        with self.assertRaisesRegex(ValueError,"Version not found."):self.api.version_delete(v["id"])
        with self.assertRaisesRegex(ValueError,"Version not found."):self.api.version_restore(rid,v["id"])
        other=self.api.create({"title":"O"})
        with self.assertRaisesRegex(ValueError,"Version not found."):self.api.version_restore(other["id"],auto["id"])
class TemplateTests(Base):
    def test_all_builtins_seed_sections(self):
        listed=self.api.templates()
        self.assertEqual(["web_app","internal_network","external_network","cloud","mobile","red_team","retest_short","blank"],[t["id"] for t in listed])
        needles={"web_app":"OWASP Web Security Testing Guide","internal_network":"NIST SP 800-115","external_network":"Penetration Testing Execution Standard","cloud":"CIS Benchmark","mobile":"MASVS","red_team":"MITRE ATT&amp;CK","retest_short":"retest"}
        for t in listed:
            self.assertEqual({"id","name","description","builtin","sections"},set(t));self.assertTrue(t["builtin"]);self.assertTrue(t["name"]);self.assertTrue(t["description"])
            full=self.api.template_get(t["id"])
            self.assertEqual({"id","name","description","builtin","sections","meta","options"},set(full))
            self.assertEqual(t["sections"],len(full["sections"]))
            rep=self.api.create({"title":t["name"],"template_id":t["id"]})
            self.assertEqual([(s["kind"],s["title"],s["hidden"]) for s in full["sections"]],[(s["kind"],s["title"],s["hidden"]) for s in rep["sections"]])
            for s,src in zip(rep["sections"],full["sections"]):
                self.assertIn(s["kind"],reports.SECTION_KINDS)
                self.assertEqual(src["content"],s["content"])
                self.assertEqual(s["content"],reports.sanitize_html(s["content"]),f"{t['id']}/{s['title']} is outside the rich subset")
            if t["id"]=="blank":
                self.assertEqual([],rep["sections"]);continue
            kinds=[s["kind"] for s in rep["sections"]]
            for k in ("executive_summary","scope","methodology","findings_summary","findings","conclusion","document_control"):self.assertIn(k,kinds,t["id"])
            if t["id"]!="retest_short":
                for k in ("remediation_roadmap","appendix_tools","appendix_commands","appendix_evidence","appendix_timeline"):self.assertIn(k,kinds,t["id"])
                self.assertGreater(len([s for s in rep["sections"] if s["kind"]=="methodology"][0]["content"]),800)
            body="".join(s["content"] for s in rep["sections"])
            self.assertIn(needles[t["id"]],body)
            for token in ("{{client}}","{{company}}","{{start_date}}","{{end_date}}","{{engagement}}"):self.assertIn(token,body,t["id"])
            self.assertIn("Critical",body);self.assertIn("point-in-time",body)
            self.assertTrue(rep["meta"]["report_type"]);self.assertTrue(rep["meta"]["methodology"])
        self.assertFalse(self.api.create({"title":"x","template_id":"retest_short"})["options"]["include_appendices"])
    def test_placeholders(self):
        self.assertEqual(["{{client}}","{{engagement}}","{{start_date}}","{{end_date}}","{{company}}","{{report_date}}"],[p["token"] for p in self.api.placeholders()])
        rep=self.api.create({"title":"R","meta":{"client":"A & B <Ltd>","start_date":"2026-11-01"},"branding":{"company":"Red"}})
        self.assertEqual("<p>A &amp; B &lt;Ltd&gt; / Red / 2026-11-01 / {{end_date}} / {{unknown}}</p>",reports.apply_placeholders("<p>{{client}} / {{ company }} / {{start_date}} / {{end_date}} / {{unknown}}</p>",rep))
        self.assertEqual("A & B <Ltd> - [end date]",reports.apply_placeholders("{{client}} - {{end_date}}",rep,escape=False,missing="[end date]"))
    def test_user_templates(self):
        rep=self.api.create({"title":"R","template_id":"web_app","options":{"page_size":"Letter"}})
        self.api.section_update(rep["sections"][0]["id"],{"content":"<p>My summary</p>","hidden":True})
        t=self.api.template_save_from_report(rep["id"],"House style","Our standard")
        self.assertFalse(t["builtin"]);self.assertEqual(("House style","Our standard"),(t["name"],t["description"]))
        self.assertEqual(len(rep["sections"]),len(t["sections"]));self.assertEqual(("<p>My summary</p>",True),(t["sections"][0]["content"],t["sections"][0]["hidden"]))
        self.assertEqual("Web Application Penetration Test",t["meta"]["report_type"]);self.assertEqual("Letter",t["options"]["page_size"])
        self.assertIn({"id":t["id"],"name":"House style","description":"Our standard","builtin":False,"sections":len(t["sections"])},self.api.templates())
        made=self.api.create({"title":"From mine","template_id":t["id"]})
        self.assertEqual(t["id"],made["template_id"]);self.assertEqual("<p>My summary</p>",made["sections"][0]["content"]);self.assertTrue(made["sections"][0]["hidden"]);self.assertEqual("Letter",made["options"]["page_size"])
        t2=self.api.template_save({"id":t["id"],"name":"Renamed","description":"","sections":[{"kind":"custom","title":"Only","content":"<p>x</p><script>1</script>"},{"kind":"bad"},"junk"],"meta":{"methodology":"PTES","client":"leak"},"options":{}})
        self.assertEqual(t["id"],t2["id"]);self.assertEqual("Renamed",t2["name"])
        self.assertEqual([{"kind":"custom","title":"Only","content":"<p>x</p>","hidden":False},{"kind":"custom","title":"New Section","content":"","hidden":False}],t2["sections"])
        self.assertEqual({"methodology":"PTES"},t2["meta"])
        copy=self.api.template_save({"id":"web_app","name":"My web","sections":[]})
        self.assertNotEqual("web_app",copy["id"]);self.assertFalse(copy["builtin"])
        self.assertTrue(self.api.template_get("web_app")["sections"])
        with self.assertRaisesRegex(ValueError,"name"):self.api.template_save({"name":" "})
        with self.assertRaisesRegex(ValueError,"Built-in"):self.api.template_delete("web_app")
        self.assertTrue(self.api.template_delete(t["id"]))
        with self.assertRaisesRegex(ValueError,"Template not found."):self.api.template_delete(t["id"])
        with self.assertRaisesRegex(ValueError,"Template not found."):self.api.template_get(t["id"])
class LibraryTests(Base):
    def test_seeded_once_with_quality_entries(self):
        rows=self.api.library_list()
        self.assertGreaterEqual(len(rows),25);self.assertEqual(len(report_templates.LIBRARY),len(rows))
        self.assertEqual({"id","uid","title","category","severity","cvss_vector","cvss_score","updated_at","builtin"},set(rows[0]))
        self.assertEqual(len(rows),len({r["uid"] for r in rows}))
        titles=" | ".join(r["title"] for r in rows).lower()
        for needle in ("sql injection","reflected cross-site scripting","stored cross-site scripting","insecure direct object","weak tls","default credentials","smb signing","llmnr","kerberoast","security headers","outdated","storage bucket"):self.assertIn(needle,titles)
        for r in rows:
            e=self.api.library_get(r["id"])
            self.assertTrue(e["builtin"]);self.assertTrue(e["category"])
            calc=reports.cvss_calc(e["cvss_vector"])
            self.assertTrue(calc["valid"],e["title"]);self.assertEqual(calc["score"],e["cvss_score"]);self.assertEqual(calc["vector"],e["cvss_vector"])
            self.assertIn(e["severity"],reports.SEVERITIES)
            self.assertRegex(e["cwe"],r"^CWE-\d+$",e["title"]);self.assertTrue(e["owasp"],e["title"]);self.assertTrue(e["references"],e["title"])
            for k in ("description","impact","remediation"):
                self.assertGreater(len(e[k]),120,f"{e['title']} {k}")
                self.assertEqual(e[k],reports.sanitize_html(e[k]),f"{e['title']} {k} is outside the rich subset")
            self.assertEqual(e["steps"],reports.sanitize_html(e["steps"]))
            for ref in e["references"]:self.assertRegex(ref,r"^https://")
            self.assertNotIn("affected",e);self.assertNotIn("evidence",e);self.assertNotIn("status",e)
        self.assertTrue(self.api.library_delete(rows[0]["id"]))
        self.assertEqual(len(rows)-1,len(self.api.library_list()))
        with open(os.path.join(self.dir,"settings.json"),encoding="utf-8") as fh:self.assertEqual(1,json.load(fh)["reports"]["library_seed"])
        self.assertNotIn("library_seed",self.api.defaults_get())
    def test_crud(self):
        e=self.api.library_save({"title":"Custom thing","category":"Mine","cvss_vector":VEC,"description":"<p>d</p><script>x</script>","tags":["t"],"affected":[{"name":"x"}],"status":"fixed"})
        self.assertEqual(("Custom thing","Mine","critical",9.8,"<p>d</p>",False),(e["title"],e["category"],e["severity"],e["cvss_score"],e["description"],e["builtin"]))
        self.assertNotIn("affected",e)
        e2=self.api.library_save({"id":e["id"],"remediation":"<p>fix</p>","severity":"low"})
        self.assertEqual((e["id"],e["uid"],"Custom thing","Mine","low","<p>d</p>","<p>fix</p>"),(e2["id"],e2["uid"],e2["title"],e2["category"],e2["severity"],e2["description"],e2["remediation"]))
        self.assertEqual(e2,self.api.library_get(e["id"]));self.assertEqual(e2,self.api.library_get(e["uid"]))
        with self.assertRaisesRegex(ValueError,"title"):self.api.library_save({"category":"x"})
        with self.assertRaisesRegex(ValueError,"Library entry not found."):self.api.library_save({"id":99999,"title":"x"})
        self.assertTrue(self.api.library_delete(e["id"]))
        with self.assertRaisesRegex(ValueError,"Library entry not found."):self.api.library_get(e["id"])
    def test_finding_from_library_and_save_from_finding(self):
        rep=self.api.create({"title":"R"})
        sqli=[r for r in self.api.library_list() if r["uid"]=="builtin-sqli"][0]
        f=self.api.finding_from_library(rep["id"],sqli["id"])
        self.assertEqual(("SQL Injection","critical",9.8,"CWE-89","open",{"kind":"library","ref":"builtin-sqli"}),(f["title"],f["severity"],f["cvss_score"],f["cwe"],f["status"],f["source"]))
        self.assertIn("parameterised queries",f["remediation"]);self.assertTrue(f["steps"]);self.assertEqual(rep["id"],f["report_id"])
        self.api.finding_update(f["id"],{"title":"SQLi in login","affected":[{"name":"web01"}],"evidence":[{"asset_uid":"abc123"}],"retest_notes":"still there","status":"retest"})
        saved=self.api.library_save_from_finding(f["id"],"Client X")
        self.assertEqual(("SQLi in login","Client X","critical","CWE-89","",False),(saved["title"],saved["category"],saved["severity"],saved["cwe"],saved["retest_notes"],saved["builtin"]))
        self.assertNotIn("affected",saved);self.assertNotIn("evidence",saved)
        self.assertEqual("Custom",self.api.library_save_from_finding(f["id"])["category"])
        with self.assertRaisesRegex(ValueError,"Library entry not found."):self.api.finding_from_library(rep["id"],424242)
        with self.assertRaisesRegex(ValueError,"Report not found."):self.api.finding_from_library(999,sqli["id"])
class AssetTests(Base):
    def test_add_get_and_dedupe(self):
        raw=png(7,5)
        a=self.api.asset_add("shot one.png","data:image/png;base64,"+base64.b64encode(raw).decode())
        self.assertEqual({"uid","mime","width","height","name"},set(a))
        self.assertEqual(("image/png",7,5,"shot one.png"),(a["mime"],a["width"],a["height"],a["name"]))
        self.assertEqual(a,self.api.asset_add("other name.png",base64.b64encode(raw).decode()))
        self.assertEqual(a["uid"],reports.add_asset("x",raw)["uid"])
        self.assertEqual(1,self.count("ReportAssets"))
        got=self.api.asset_get(a["uid"])
        self.assertEqual({"uid","mime","name","width","height","data_url"},set(got))
        self.assertEqual(raw,base64.b64decode(got["data_url"].split(",",1)[1]));self.assertTrue(got["data_url"].startswith("data:image/png;base64,"))
        svc=reports.get_asset("rptasset:"+a["uid"])
        self.assertEqual(raw,svc["data"]);self.assertEqual("image/png",svc["mime"])
        g=reports.add_asset("../../etc/pass:wd.gif",GIF)
        self.assertEqual(("image/gif",5,4,"_.._etc_pass_wd.gif"),(g["mime"],g["width"],g["height"],g["name"]))
        self.assertNotEqual(a["uid"],g["uid"])
    def test_header_parsers_without_pillow(self):
        self.assertEqual((7,5),tuple(reports._header_size(png(7,5),"image/png")))
        self.assertEqual((5,4),tuple(reports._header_size(GIF,"image/gif")))
        jpeg=b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xdb\x00\x05\x00\x01\x02\x03\xff\xc0\x00\x11\x08\x00\x20\x00\x40\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01\xff\xd9"
        self.assertEqual("image/jpeg",reports._sniff_image(jpeg));self.assertEqual((64,32),tuple(reports._header_size(jpeg,"image/jpeg")))
        webp=b"RIFF"+struct.pack("<I",22)+b"WEBPVP8X"+struct.pack("<I",10)+b"\x00\x00\x00\x00"+(99).to_bytes(3,"little")+(49).to_bytes(3,"little")
        self.assertEqual("image/webp",reports._sniff_image(webp));self.assertEqual((100,50),tuple(reports._header_size(webp,"image/webp")))
        self.assertEqual((0,0),tuple(reports._header_size(b"\x89PNG\r\n\x1a\n",  "image/png")))
    def test_rejects_non_images_and_oversize(self):
        self.api.list()
        for name,raw in (("a.svg",b"<svg xmlns='http://www.w3.org/2000/svg' onload='alert(1)'/>"),("a.html",b"<html><script>alert(1)</script>"),("a.exe",b"MZ\x90\x00"),("a.pdf",b"%PDF-1.7"),("a.bmp",b"BM"+b"\x00"*60),("a.png",b"\x89PNG but not really"),("empty.png",b"")):
            with self.assertRaises(ValueError,msg=name):reports.add_asset(name,raw)
            with self.assertRaises(ValueError,msg=name):self.api.asset_add(name,base64.b64encode(raw).decode())
        with self.assertRaisesRegex(ValueError,"too large"):reports.add_asset("big.png",png()+b"\x00"*reports.ASSET_MAX)
        with self.assertRaisesRegex(ValueError,"too large"):self.api.asset_add("big.png","A"*(reports.ASSET_MAX*4//3+1000))
        for bad in ("!!!not base64!!!","data:image/png;base64","",None,123):
            with self.assertRaises(ValueError,msg=repr(bad)):self.api.asset_add("x.png",bad)
        with self.assertRaises(ValueError):reports.add_asset("x.png","a string")
        self.assertEqual(0,self.count("ReportAssets"))
        for bad in ("","nope","../x",None,"rptasset:"):
            with self.assertRaisesRegex(ValueError,"Asset not found."):self.api.asset_get(bad)
    def test_data_url_images_in_rich_text_become_assets(self):
        rep=self.api.create({"title":"R"})
        url="data:image/png;base64,"+base64.b64encode(png(4,4)).decode()
        s=self.api.section_add(rep["id"],{"kind":"custom","title":"S","content":f'<p>a</p><img src="{url}" alt="shot"><img src="data:image/png;base64,AAAA"><img src="data:text/html;base64,PHNjcmlwdD4=">'})
        uid=reports.add_asset("x",png(4,4))["uid"]
        self.assertEqual(f'<p>a</p><img src="rptasset:{uid}" alt="shot">',s["content"])
        f=self.api.finding_add(rep["id"],{"title":"f","steps":f'<img src="{url}">'})
        self.assertEqual(f'<img src="rptasset:{uid}" alt="">',f["steps"])
        self.assertEqual(1,self.count("ReportAssets"))
    def test_purge_orphan_assets(self):
        rep=self.api.create({"title":"R"})
        mk=lambda i:reports.add_asset(f"{i}.png",png(2,2,i))["uid"]
        in_section,in_finding,in_evidence_list,logo,in_version,in_bin,in_library,in_defaults,fresh,orphan=[mk(i) for i in range(10)]
        self.api.section_add(rep["id"],{"kind":"custom","content":f'<img src="rptasset:{in_section}" alt="">'})
        self.api.finding_add(rep["id"],{"title":"f","description":f'<img src="rptasset:{in_finding}" alt="">',"evidence":[{"asset_uid":in_evidence_list}]})
        self.api.update(rep["id"],{"branding":{"logo_asset":logo}})
        tmp=self.api.section_add(rep["id"],{"kind":"custom","content":f'<img src="rptasset:{in_version}" alt="">'})
        self.api.version_create(rep["id"],"with image");self.api.section_delete(tmp["id"])
        gone=self.api.finding_add(rep["id"],{"title":"g","impact":f'<img src="rptasset:{in_bin}" alt="">'});self.api.finding_delete(gone["id"])
        self.api.library_save({"title":"L","steps":f'<img src="rptasset:{in_library}" alt="">'})
        self.api.defaults_set({"branding":{"logo_asset":in_defaults}})
        old=(datetime.now(timezone.utc)-timedelta(days=3)).isoformat()
        con=self.db();con.execute("UPDATE ReportAssets SET created_at=? WHERE uid<>?",(old,fresh));con.commit();con.close()
        self.assertEqual(1,reports.purge_orphan_assets())
        left={r[0] for r in self.db().execute("SELECT uid FROM ReportAssets")}
        self.assertEqual({in_section,in_finding,in_evidence_list,logo,in_version,in_bin,in_library,in_defaults,fresh},left)
        self.assertNotIn(orphan,left)
        self.assertEqual(1,reports.purge_orphan_assets(grace_seconds=0))
        # Emptying the Recycle Bin releases the image only the deleted finding used.
        con=self.db();con.execute("UPDATE ReportAssets SET created_at=?",(old,));con.commit();con.close()
        recycle_bin.purge_all()
        self.assertEqual(0,self.count("ReportAssets","uid=?",(in_bin,)))
        self.assertEqual(7,self.count("ReportAssets"))
class DefaultsTests(Base):
    def test_get_set(self):
        d=self.api.defaults_get()
        self.assertEqual({"default_format","page_size","include_appendices","include_toc","branding","testers","classification","redact_evidence"},set(d))
        self.assertEqual(("pdf","A4",True,True,[],"Confidential",True),(d["default_format"],d["page_size"],d["include_appendices"],d["include_toc"],d["testers"],d["classification"],d["redact_evidence"]))
        self.assertEqual({"company","logo_asset","accent","secondary","banner","footer","cover_subtitle","show_cover","theme","font","cover_style"},set(d["branding"]))
        with open(os.path.join(self.dir,"settings.json"),"w",encoding="utf-8") as fh:json.dump({"theme":"dark","reports":{"library_seed":1}},fh)
        out=self.api.defaults_set({"default_format":"docx","page_size":"Letter","include_toc":False,"branding":{"company":"Red Co","accent":"#AA0000","banner":"CONFIDENTIAL"},"testers":[{"name":"Ana","role":"Lead","email":"ana@red.co"}],"classification":"Secret","redact_evidence":False,"junk":1})
        self.assertEqual(out,self.api.defaults_get())
        self.assertEqual(("docx","Letter",False,True,"Secret",False),(out["default_format"],out["page_size"],out["include_toc"],out["include_appendices"],out["classification"],out["redact_evidence"]))
        self.assertEqual(("Red Co","#aa0000","CONFIDENTIAL",True),(out["branding"]["company"],out["branding"]["accent"],out["branding"]["banner"],out["branding"]["show_cover"]))
        out=self.api.defaults_set({"default_format":"exe","page_size":"A3","branding":{"footer":"f","accent":"nope"}})
        self.assertEqual(("docx","Letter","Red Co","f","#aa0000"),(out["default_format"],out["page_size"],out["branding"]["company"],out["branding"]["footer"],out["branding"]["accent"]))
        with open(os.path.join(self.dir,"settings.json"),encoding="utf-8") as fh:stored=json.load(fh)
        self.assertEqual("dark",stored["theme"]);self.assertEqual(1,stored["reports"]["library_seed"]);self.assertNotIn("junk",stored["reports"])
        with self.assertRaises(ValueError):self.api.defaults_set("x")
    def test_new_reports_use_the_defaults(self):
        self.api.defaults_set({"page_size":"Letter","include_toc":False,"include_appendices":False,"branding":{"company":"Red Co","footer":"red.co"},"testers":[{"name":"Ana","role":"Lead"},{"name":"Bo"}],"classification":"Restricted"})
        rep=self.api.create({"title":"R","template_id":"web_app","branding":{"footer":"custom"},"options":{"include_toc":True}})
        self.assertEqual(("Red Co","custom"),(rep["branding"]["company"],rep["branding"]["footer"]))
        self.assertEqual(("Letter",True,False),(rep["options"]["page_size"],rep["options"]["include_toc"],rep["options"]["include_appendices"]))
        self.assertEqual("Restricted",rep["meta"]["classification"]);self.assertEqual("Ana, Bo",rep["meta"]["authors"])
        self.assertEqual([{"name":"Ana","role":"Lead","email":""},{"name":"Bo","role":"","email":""}],rep["meta"]["testers"])
    def test_corrupt_settings_do_not_break_defaults(self):
        with open(os.path.join(self.dir,"settings.json"),"w",encoding="utf-8") as fh:fh.write("{not json")
        self.assertEqual("pdf",self.api.defaults_get()["default_format"])
        with open(os.path.join(self.dir,"settings.json"),"w",encoding="utf-8") as fh:json.dump({"reports":["x"]},fh)
        self.assertEqual("A4",self.api.defaults_get()["page_size"])
class LockTests(Base):
    def test_locked_database_raises(self):
        rep=self.api.create({"title":"R"})
        common_db.set_locked(True)
        calls=(lambda:self.api.list(),lambda:self.api.get(rep["id"]),lambda:self.api.create({"title":"x"}),lambda:self.api.update(rep["id"],{"title":"y"}),lambda:self.api.finding_add(rep["id"],{"title":"f"}),lambda:self.api.library_list(),lambda:self.api.templates(),lambda:self.api.stats(),lambda:self.api.sources(),lambda:self.api.asset_add("a.png",base64.b64encode(png()).decode()),lambda:self.api.asset_get("abc"),lambda:self.api.note_findings([1]),lambda:self.api.note_content(1),lambda:self.api.versions(rep["id"]),lambda:self.api.delete(rep["id"]))
        for i,call in enumerate(calls):
            with self.assertRaises(common_db.DatabaseLocked,msg=f"call {i}"):call()
        common_db.set_locked(False)
        self.assertEqual("R",self.api.get(rep["id"])["title"])
    def test_encrypted_at_rest_raises(self):
        self.api.create({"title":"R"})
        os.replace(common_db.db_path(),common_db.db_path()+".enc")
        with self.assertRaises(common_db.DatabaseLocked):self.api.list()
        self.assertFalse(os.path.isfile(common_db.db_path()) and os.path.getsize(common_db.db_path())>0)
    def test_failed_write_rolls_back(self):
        rep=self.api.create({"title":"R"})
        with self.assertRaises(ValueError):self.api.create({"title":"x","findings":[{"title":"ok"}],"sections":[{"kind":"custom"}],"template_id":"missing"})
        with self.assertRaises(ValueError):self.api.findings_sort(rep["id"],"bad")
        self.assertEqual(1,self.count("Reports"));self.assertEqual(0,self.count("ReportFindings"))
        self.assertEqual("R",self.api.get(rep["id"])["title"])
class MigrationTests(Base):
    def test_v12_database_is_upgraded_in_place(self):
        path=common_db.db_path()
        con=sqlite3.connect(path)
        con.execute("CREATE TABLE Notes(id INTEGER PRIMARY KEY AUTOINCREMENT,note_name TEXT,group_name TEXT,tags TEXT,content TEXT,created_at TEXT,updated_at TEXT)")
        con.execute("CREATE TABLE RecycleBin(id INTEGER PRIMARY KEY AUTOINCREMENT,entity_type TEXT NOT NULL,entity_key TEXT,label TEXT,payload TEXT NOT NULL,source TEXT,deleted_at TEXT NOT NULL,expires_at TEXT NOT NULL)")
        con.execute("CREATE TABLE SchemaMigrations(version INTEGER PRIMARY KEY,applied_at TEXT)")
        for v in range(1,13):con.execute("INSERT INTO SchemaMigrations(version,applied_at) VALUES(?,?)",(v,"2026-01-01T00:00:00+00:00"))
        con.executemany("INSERT INTO Notes(note_name,group_name,tags,content,created_at,updated_at) VALUES(?,?,?,?,?,?)",[("Recon","ACME","web","<p>nmap</p>","2026-01-01","2026-01-02"),("Loot","ACME","","<p>creds</p>","2026-01-03","2026-01-04")])
        con.execute("INSERT INTO RecycleBin(entity_type,entity_key,label,payload,source,deleted_at,expires_at) VALUES('note','','Old','{}','','2026-01-01T00:00:00+00:00','2999-01-01T00:00:00+00:00')")
        con.execute("PRAGMA user_version=12");con.commit();con.close()
        con=sqlite3.connect(path)
        try:
            self.assertEqual(12,con.execute("PRAGMA user_version").fetchone()[0])
            self.assertIsNone(con.execute("SELECT 1 FROM sqlite_master WHERE name='Reports'").fetchone())
            common_db.ensure_schema(con)
            self.assertGreaterEqual(common_db.DB_SCHEMA_VERSION,13);self.assertEqual(common_db.DB_SCHEMA_VERSION,con.execute("PRAGMA user_version").fetchone()[0])
            self.assertEqual([("Recon","ACME","web","<p>nmap</p>"),("Loot","ACME","","<p>creds</p>")],con.execute("SELECT note_name,group_name,tags,content FROM Notes ORDER BY id").fetchall())
            self.assertEqual(1,con.execute("SELECT COUNT(*) FROM RecycleBin").fetchone()[0])
            tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for t in ("Reports","ReportSections","ReportFindings","FindingLibrary","ReportTemplates","ReportVersions","ReportEvidence","ReportEvidenceEvents","ReportAssets"):self.assertIn(t,tables)
            self.assertEqual((common_db.DB_SCHEMA_VERSION,),con.execute("SELECT MAX(version) FROM SchemaMigrations").fetchone())
            common_db.ensure_schema(con)
            self.assertEqual(2,con.execute("SELECT COUNT(*) FROM Notes").fetchone()[0])
        finally:con.close()
        rep=self.api.create({"title":"After upgrade","template_id":"web_app"})
        self.assertEqual(12,len(rep["sections"]))
        self.assertEqual(["Loot","Recon"],[n["name"] for n in self.api.sources()["notes"]])
        self.assertEqual({"id","name","group","tags","updated_at","findings"},set(self.api.sources()["notes"][0]))
if __name__=="__main__":unittest.main()
