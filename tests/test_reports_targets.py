import os
os.environ.setdefault("LOYA_REPORT_PDF_ENGINE","fallback")
import csv,io,json,shutil,sqlite3,subprocess,tempfile,unittest,zipfile
from _isolate import IsolatedData
from Cores import common_db,recycle_bin,target_profiles
from Cores.Services import reports_service as reports
from Cores.Services import report_export as rx
from Cores.Services import report_import
from Cores.Bridge.reports_api import ReportsAPI
PDFTOTEXT=shutil.which("pdftotext")
SECRET="Sup3r-S3cret-Pw!"
HASH="aad3b435b51404eeaad3b435b51404ee"
V40="CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N"
def tv(uid,key,text="stale"):return f'<span class="rpt-tv" data-target="{uid}" data-key="{key}">{text}</span>'
class Base(unittest.TestCase):
    def setUp(self):
        self.isolated=IsolatedData();self.dir=self.isolated.start();self.api=ReportsAPI()
        self.tmp=tempfile.mkdtemp(prefix="loya_rt_")
        ok,_msg,self.pid=target_profiles.create_profile("Client B")
        self.assertTrue(ok)
        self.write("default",[
            {"id":"t-web","name":"web01","status":"live","engagement_status":"in_progress","values":{"IPv4":"10.0.0.5","Domain":"shop.acme.example","URL":"https://shop.acme.example","Password":SECRET,"Username":"svc_web","NTLM Hash":HASH,"Port":"443"}},
            {"id":"t-db","name":"db01","status":"not_used","engagement_status":"not_started","values":{"IPv4":"10.0.0.22","Port":"5432"}}])
        self.write(self.pid,[{"id":"t-vpn","name":"vpn-gw","status":"not_used","engagement_status":"compromised","values":{"IPv4":"203.0.113.9","API Token":"tok_live_123"}}])
        self.rep=self.api.create({"title":"Scope test","template_id":"web_app"})
        self.rid=self.rep["id"]
    def tearDown(self):
        common_db.set_locked(False);self.isolated.stop();shutil.rmtree(self.tmp,ignore_errors=True)
    def write(self,pid,targets):
        with open(target_profiles.profile_targets_json_path(pid),"w",encoding="utf-8") as f:json.dump(targets,f)
    def read(self,pid):
        with open(target_profiles.profile_targets_json_path(pid),"r",encoding="utf-8") as f:return json.load(f)
    def link_all(self):
        return self.api.target_link(self.rid,[{"target_id":"t-web","profile_id":"default"},{"target_id":"t-vpn","profile_id":self.pid}])
    def count(self,table,where="1=1",args=()):
        con=sqlite3.connect(common_db.db_path())
        try:return con.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}",args).fetchone()[0]
        finally:con.close()
    def scope_section(self,rep=None):return next(s for s in (rep or self.api.get(self.rid))["sections"] if s["kind"]=="scope")
class LinkTests(Base):
    def test_report_without_links_is_unchanged(self):
        rep=self.api.get(self.rid)
        self.assertEqual([],rep["targets"])
        self.assertTrue(all(f["targets"]==[] for f in rep["findings"]))
        self.assertNotIn("scope_columns",rep["options"]);self.assertNotIn("scope_table",rep["options"])
        self.assertNotIn("Targets in scope",rx.build_html(rep))
    def test_available_lists_every_profile_without_secret_values(self):
        av=self.api.targets_available()
        self.assertEqual(["web01","db01","vpn-gw"],[t["name"] for t in av])
        web=av[0]
        self.assertEqual({"target_id","profile_id","profile_name","profile_active","name","live","values","secret_keys","engagement_status"},set(web))
        self.assertTrue(web["live"]);self.assertEqual("Default",web["profile_name"]);self.assertEqual("in_progress",web["engagement_status"])
        self.assertEqual({"IPv4","Domain","URL","Port"},set(web["values"]))
        self.assertEqual({"Password","Username","NTLM Hash"},set(web["secret_keys"]))
        dump=json.dumps(av)
        for s in (SECRET,HASH,"svc_web","tok_live_123"):self.assertNotIn(s,dump)
        self.assertEqual(["vpn-gw"],[t["name"] for t in self.api.targets_available("client b")])
        self.assertEqual(["db01"],[t["name"] for t in self.api.targets_available("10.0.0.22")])
        self.assertEqual([],self.api.targets_available(SECRET))
    def test_link_snapshot_shape_and_unlink(self):
        links=self.link_all()
        self.assertEqual(["web01","vpn-gw"],[l["name"] for l in links])
        l=links[0]
        self.assertEqual({"uid","target_id","profile_id","profile_name","name","snapshot","allowed_secret_keys","position","linked_at","updated_at","state","changed_keys","live","secret_keys"},set(l))
        self.assertEqual({"values":{"IPv4":"10.0.0.5","Domain":"shop.acme.example","URL":"https://shop.acme.example","Port":"443"},"engagement_status":"in_progress"},l["snapshot"])
        self.assertEqual(("ok",[],True,[]),(l["state"],l["changed_keys"],l["live"],l["allowed_secret_keys"]))
        self.assertEqual("Client B",links[1]["profile_name"]);self.assertEqual("compromised",links[1]["snapshot"]["engagement_status"])
        self.assertEqual(links,self.api.get(self.rid)["targets"]);self.assertEqual(links,self.api.targets_list(self.rid))
        # linking again is a no-op; an unknown target is an error
        self.assertEqual(2,len(self.api.target_link(self.rid,[{"target_id":"t-web","profile_id":"default"}])))
        with self.assertRaisesRegex(ValueError,"Target not found"):self.api.target_link(self.rid,[{"target_id":"nope","profile_id":"default"}])
        with self.assertRaisesRegex(ValueError,"Report not found"):self.api.target_link(999,[{"target_id":"t-web","profile_id":"default"}])
        left=self.api.target_unlink(self.rid,l["uid"])
        self.assertEqual(["vpn-gw"],[x["name"] for x in left]);self.assertEqual(0,left[0]["position"])
        with self.assertRaisesRegex(ValueError,"not linked"):self.api.target_unlink(self.rid,l["uid"])
    def test_nothing_secret_is_stored_at_linking_time(self):
        self.link_all()
        con=sqlite3.connect(common_db.db_path())
        try:dump=json.dumps(con.execute("SELECT * FROM ReportTargets").fetchall())
        finally:con.close()
        for s in (SECRET,HASH,"svc_web","tok_live_123"):self.assertNotIn(s,dump)
    def test_changed_then_update_from_target(self):
        uid=self.link_all()[0]["uid"]
        t=self.read("default");t[0]["values"]["IPv4"]="10.0.0.99";t[0]["values"]["Password"]="changed-secret";t[0]["engagement_status"]="compromised";t[0]["name"]="web01-new"
        self.write("default",t)
        l=self.api.targets_list(self.rid)[0]
        self.assertEqual("changed",l["state"]);self.assertEqual(["@name","@status","IPv4"],l["changed_keys"])
        # the snapshot is untouched until the user updates; a secret that changed is not a change of the link
        self.assertEqual("10.0.0.5",l["snapshot"]["values"]["IPv4"]);self.assertEqual("web01",l["name"])
        l=next(x for x in self.api.target_update(self.rid,uid) if x["uid"]==uid)
        self.assertEqual(("ok","web01-new","10.0.0.99","compromised"),(l["state"],l["name"],l["snapshot"]["values"]["IPv4"],l["snapshot"]["engagement_status"]))
        self.assertNotIn("Password",l["snapshot"]["values"])
        t[0]["values"]["Password"]="again";self.write("default",t)
        self.assertEqual("ok",self.api.targets_list(self.rid)[0]["state"])
    def test_update_all_skips_removed(self):
        self.link_all()
        t=self.read("default");t[0]["values"]["Port"]="8443";self.write("default",t);self.write(self.pid,[])
        links=self.api.target_update(self.rid,None)
        self.assertEqual(["ok","removed"],[l["state"] for l in links]);self.assertEqual("8443",links[0]["snapshot"]["values"]["Port"])
    def test_deleted_target_keeps_the_snapshot(self):
        uid=self.link_all()[1]["uid"]
        self.write(self.pid,[])
        l=self.api.targets_list(self.rid)[1]
        self.assertEqual(("removed","vpn-gw",{"IPv4":"203.0.113.9"},False,[]),(l["state"],l["name"],l["snapshot"]["values"],l["live"],l["secret_keys"]))
        with self.assertRaisesRegex(ValueError,"removed from the Targets page"):self.api.target_update(self.rid,uid)
        self.assertIn("203.0.113.9",rx.build_html(self.api.get(self.rid)))
        # a deleted profile behaves the same
        target_profiles.delete_profile(self.pid)
        self.assertEqual("removed",self.api.targets_list(self.rid)[1]["state"])
    def test_reorder(self):
        a,b=[l["uid"] for l in self.link_all()]
        self.assertEqual([b,a],[l["uid"] for l in self.api.targets_reorder(self.rid,[b,"junk",b])])
        self.assertEqual([0,1],[l["position"] for l in self.api.targets_list(self.rid)])
    def test_scope_options(self):
        self.api.update(self.rid,{"options":{"scope_columns":["IPv4","@status","IPv4","bad{key}",5],"scope_table":0}})
        o=self.api.get(self.rid)["options"]
        self.assertEqual((["IPv4","@status","5"],False),(o["scope_columns"],o["scope_table"]))
        self.api.update(self.rid,{"options":{"scope_columns":None,"scope_table":None}})
        o=self.api.get(self.rid)["options"]
        self.assertNotIn("scope_columns",o);self.assertNotIn("scope_table",o)
class SecretTests(Base):
    def test_allow_flow(self):
        uid=self.link_all()[0]["uid"]
        self.assertEqual(["Password","Username","NTLM Hash"],self.api.targets_list(self.rid)[0]["secret_keys"])
        with self.assertRaisesRegex(ValueError,"not a protected"):self.api.target_allow_secret(self.rid,uid,"IPv4",True)
        with self.assertRaisesRegex(ValueError,"no value"):self.api.target_allow_secret(self.rid,uid,"Session Cookie",True)
        l=self.api.target_allow_secret(self.rid,uid,"password",True)[0]
        self.assertEqual(["Password"],l["allowed_secret_keys"]);self.assertEqual(SECRET,l["snapshot"]["values"]["Password"])
        self.assertEqual(["Username","NTLM Hash"],l["secret_keys"])
        self.assertNotIn(HASH,json.dumps(self.api.get(self.rid)))
        # an allowed key is part of the snapshot from then on: a change shows, an update takes it
        t=self.read("default");t[0]["values"]["Password"]="rotated!";self.write("default",t)
        l=self.api.targets_list(self.rid)[0]
        self.assertEqual(("changed",["Password"]),(l["state"],l["changed_keys"]))
        self.assertEqual("rotated!",self.api.target_update(self.rid,uid)[0]["snapshot"]["values"]["Password"])
        l=self.api.target_allow_secret(self.rid,uid,"Password",False)[0]
        self.assertEqual([],l["allowed_secret_keys"]);self.assertNotIn("Password",l["snapshot"]["values"])
        self.assertNotIn("rotated!",json.dumps(self.api.get(self.rid)))
    def test_restore_cannot_smuggle_a_secret(self):
        self.link_all()
        st=self.api.targets_state(self.rid)
        st["targets"][0]["snapshot"]["values"]["Password"]="smuggled";st["targets"][0]["snapshot"]["values"]["Notes"]="fine"
        out=self.api.targets_restore(self.rid,st)
        self.assertNotIn("smuggled",json.dumps(out));self.assertEqual("fine",out["targets"][0]["snapshot"]["values"]["Notes"])
        st["targets"][0]["allowed_secret_keys"]=["Password","IPv4"]
        out=self.api.targets_restore(self.rid,st)
        self.assertEqual(["Password"],out["targets"][0]["allowed_secret_keys"]);self.assertEqual("smuggled",out["targets"][0]["snapshot"]["values"]["Password"])
    def test_secret_reference_is_withheld_unless_allowed(self):
        uid=self.link_all()[0]["uid"]
        sec=self.scope_section()
        self.api.section_update(sec["id"],{"content":f"<p>pw {tv(uid,'Password',SECRET)} ip {tv(uid,'IPv4','old')}</p>"})
        stored=self.scope_section()["content"]
        self.assertNotIn(SECRET,stored);self.assertIn(reports.TV_WITHHELD,stored);self.assertIn(">10.0.0.5</span>",stored)
        html=rx.build_html(self.api.get(self.rid))
        self.assertNotIn(SECRET,html);self.assertIn("[withheld]",html)
        self.api.target_allow_secret(self.rid,uid,"Password",True)
        self.assertIn(SECRET,self.scope_section()["content"]);self.assertIn(SECRET,rx.build_html(self.api.get(self.rid)))
        self.api.target_allow_secret(self.rid,uid,"Password",False)
        self.assertNotIn(SECRET,json.dumps(self.api.get(self.rid)));self.assertNotIn(SECRET,rx.build_html(self.api.get(self.rid)))
    def test_export_never_trusts_stale_text_or_a_tampered_report(self):
        uid=self.link_all()[0]["uid"]
        rep=self.api.get(self.rid)
        # a report dict that carries a secret in a snapshot without the key being allowed (old data, a hand-edited import)
        rep["targets"][0]["snapshot"]["values"]["Password"]=SECRET
        self.scope_section(rep)["content"]=f"<p>{tv(uid,'Password',SECRET)} {tv('gone','API Token','tok_live_123')} {tv('gone','IPv4','198.51.100.7')}</p>"
        rep["options"]["scope_columns"]=["IPv4","Password"]
        html=rx.build_html(rep)
        self.assertNotIn(SECRET,html);self.assertNotIn("tok_live_123",html);self.assertIn("198.51.100.7",html)
        self.assertNotIn(SECRET,json.dumps(rx.build_json(rep)["report"]["sections"]))
class FindingTests(Base):
    def test_finding_targets_set_get_and_cascade(self):
        a,b=[l["uid"] for l in self.link_all()]
        f=self.api.finding_add(self.rid,{"title":"SQLi","severity":"high","targets":[{"uid":a,"keys":["URL","IPv4"]}]})
        self.assertEqual([{"uid":a,"keys":["URL","IPv4"]}],f["targets"])
        f=self.api.finding_targets_set(f["id"],[{"uid":b,"keys":[]},{"uid":a,"keys":["IPv4","IPv4","bad{}"]},{"uid":"nope","keys":[]},{"uid":b}])
        self.assertEqual([{"uid":b,"keys":[]},{"uid":a,"keys":["IPv4"]}],f["targets"])
        self.assertEqual(f["targets"],self.api.get(self.rid)["findings"][0]["targets"]);self.assertEqual(f["targets"],self.api.finding_get(f["id"])["targets"])
        f=self.api.finding_update(f["id"],{"title":"SQL injection"})
        self.assertEqual(2,len(f["targets"]))
        f=self.api.finding_update(f["id"],{"targets":[{"uid":a,"keys":["Domain"]}]})
        self.assertEqual([{"uid":a,"keys":["Domain"]}],f["targets"])
        self.api.target_unlink(self.rid,a)
        self.assertEqual([],self.api.finding_get(f["id"])["targets"]);self.assertEqual(0,self.count("ReportFindingTargets"))
    def test_finding_recycle_round_trip(self):
        a=self.link_all()[0]["uid"]
        f=self.api.finding_add(self.rid,{"title":"X","targets":[{"uid":a,"keys":["IPv4"]}]})
        self.api.finding_delete(f["id"])
        self.assertEqual(0,self.count("ReportFindingTargets"))
        entry=[e for e in recycle_bin.list_entries() if e["entity_type"]==reports.TYPE_REPORT_FINDING][0]
        ok,msg=recycle_bin.restore_entry(entry["id"]);self.assertTrue(ok,msg)
        self.assertEqual([{"uid":a,"keys":["IPv4"]}],self.api.get(self.rid)["findings"][0]["targets"])
class RoundTripTests(Base):
    def seed(self):
        a,b=[l["uid"] for l in self.link_all()]
        self.api.target_allow_secret(self.rid,a,"Username",True)
        self.api.update(self.rid,{"options":{"scope_columns":["IPv4","URL","@status"]}})
        self.api.section_update(self.scope_section()["id"],{"content":f"<p>Main host {tv(a,'IPv4')} ({tv(a,'@name')}).</p>"})
        self.api.finding_add(self.rid,{"title":"SQLi","severity":"high","description":f"<p>Seen on {tv(b,'IPv4')}</p>","targets":[{"uid":a,"keys":["URL"]},{"uid":b,"keys":[]}],"affected":[{"name":"typed-host","value":""}]})
        return a,b
    def check(self,rep,a,b):
        self.assertEqual([a,b],[l["uid"] for l in rep["targets"]])
        self.assertEqual("svc_web",rep["targets"][0]["snapshot"]["values"]["Username"]);self.assertEqual(["Username"],rep["targets"][0]["allowed_secret_keys"])
        self.assertEqual([{"uid":a,"keys":["URL"]},{"uid":b,"keys":[]}],rep["findings"][0]["targets"])
        self.assertEqual(["IPv4","URL","@status"],rep["options"]["scope_columns"])
        self.assertIn(">10.0.0.5</span>",self.scope_section(rep)["content"])
    def test_duplicate(self):
        a,b=self.seed()
        copy=self.api.duplicate(self.rid)
        self.check(copy,a,b)
        self.api.target_unlink(copy["id"],a)
        self.check(self.api.get(self.rid),a,b)
    def test_version_snapshot_and_restore(self):
        a,b=self.seed()
        v=self.api.version_create(self.rid,"v1")
        self.api.target_unlink(self.rid,a);self.api.target_unlink(self.rid,b)
        self.assertEqual([],self.api.get(self.rid)["targets"])
        self.check(self.api.version_restore(self.rid,v["id"]),a,b)
    def test_old_version_without_targets_keeps_the_links(self):
        a,b=self.seed()
        con=sqlite3.connect(common_db.db_path())
        try:
            snap=reports._report_snapshot(self.api.get(self.rid));snap.pop("targets")
            for f in snap["findings"]:f.pop("targets")
            con.execute("INSERT INTO ReportVersions(report_id,label,snapshot,created_at) VALUES(?,?,?,?)",(self.rid,"old",json.dumps(snap),"2026-01-01T00:00:00+00:00"));con.commit()
            vid=con.execute("SELECT MAX(id) FROM ReportVersions").fetchone()[0]
        finally:con.close()
        rep=self.api.version_restore(self.rid,vid)
        self.assertEqual([a,b],[l["uid"] for l in rep["targets"]]);self.assertEqual([],rep["findings"][0]["targets"])
    def test_recycle_bin_delete_and_restore(self):
        a,b=self.seed()
        self.api.delete(self.rid)
        self.assertEqual((0,0),(self.count("ReportTargets"),self.count("ReportFindingTargets")))
        entry=[e for e in recycle_bin.list_entries() if e["entity_type"]==reports.TYPE_REPORT][0]
        ok,msg=recycle_bin.restore_entry(entry["id"]);self.assertTrue(ok,msg)
        self.check(self.api.get(self.api.list()[0]["id"]),a,b)
    def test_json_export_import(self):
        a,b=self.seed()
        path=os.path.join(self.tmp,"r.json")
        rx.render(self.api.get(self.rid),"json",path)
        with open(path,encoding="utf-8") as f:data=json.load(f)
        self.assertEqual(2,len(data["report"]["targets"]));self.assertNotIn(SECRET,json.dumps(data));self.assertNotIn(HASH,json.dumps(data))
        self.api.delete(self.rid);self.write("default",[])
        out=report_import.apply(path,"report_json")
        rep=self.api.get(out["report_ids"][0])
        self.check(rep,a,b)
        self.assertEqual(["removed","ok"],[l["state"] for l in rep["targets"]])
    def test_undo_state_round_trip(self):
        a,b=self.seed()
        before=self.api.targets_state(self.rid)
        self.api.target_unlink(self.rid,a)
        out=self.api.targets_restore(self.rid,before)
        self.assertEqual([a,b],[l["uid"] for l in out["targets"]])
        self.assertEqual(before,self.api.targets_state(self.rid))
        self.check(self.api.get(self.rid),a,b)
        with self.assertRaisesRegex(ValueError,"Invalid scope state"):self.api.targets_restore(self.rid,{"targets":"x"})
class ExportTests(Base):
    def seed(self):
        a,b=[l["uid"] for l in self.link_all()]
        self.a,self.b=a,b
        self.api.section_update(self.scope_section()["id"],{"content":f"<p>The main host is {tv(a,'IPv4','STALETEXT')} named {tv(a,'@name','x')}, status {tv(b,'@status','x')}.</p>"})
        self.api.finding_add(self.rid,{"title":"SQL injection","severity":"high","cvss_vector":"CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H","description":f"<p>Reproduced against {tv(a,'URL','x')}.</p>",
            "targets":[{"uid":a,"keys":["URL","Password"]},{"uid":b,"keys":[]}],"affected":[{"target_id":"","name":"typed-host","value":"192.0.2.44"}]})
        return self.api.get(self.rid)
    def render(self,fmt,rep=None,options=None):
        path=os.path.join(self.tmp,"out."+rx.FORMAT_BY_ID[fmt]["ext"].lstrip("."))
        rx.render(rep or self.api.get(self.rid),fmt,path,options)
        return path
    def test_prepare_resolves_references_and_affected(self):
        doc=rx.prepare(self.seed())
        scope=rx.blocks_text(next(s for s in doc["sections"] if s["kind"]=="scope")["blocks"])
        self.assertIn("The main host is 10.0.0.5 named web01, status Compromised.",scope);self.assertNotIn("STALETEXT",scope)
        self.assertIn("Targets in scope",scope);self.assertIn("vpn-gw",scope);self.assertIn("203.0.113.9",scope);self.assertIn("In progress",scope)
        f=doc["findings"][0]
        self.assertEqual("web01 (https://shop.acme.example), vpn-gw, typed-host (192.0.2.44)",f["affected_text"])
        self.assertEqual(["web01","vpn-gw","typed-host"],f["affected_names"]);self.assertEqual(["web01","vpn-gw"],f["targets"])
        self.assertIn("Reproduced against https://shop.acme.example.",rx.blocks_text(f["description"]))
        self.assertNotIn(SECRET,json.dumps(doc["sections"],default=str))
    def test_update_from_target_reaches_the_export(self):
        self.seed()
        t=self.read("default");t[0]["values"]["IPv4"]="10.9.9.9";self.write("default",t)
        self.assertIn("The main host is 10.0.0.5",rx.rich_text(rx.resolve_target_values(self.scope_section()["content"],{l["uid"]:l for l in rx.report_links(self.api.get(self.rid))})))
        self.api.target_update(self.rid,None)
        self.assertIn(">10.9.9.9</span>",self.scope_section()["content"])
        self.assertIn("The main host is 10.9.9.9",rx.blocks_text(next(s for s in rx.prepare(self.api.get(self.rid))["sections"] if s["kind"]=="scope")["blocks"]))
    def test_scope_table_columns_toggle_and_widget(self):
        rep=self.seed()
        table=lambda r,o=None:next((b for b in next(s for s in rx.prepare(r,o)["sections"] if s["kind"]=="scope")["blocks"] if b["t"]=="table" and b.get("scope")),None)
        head=lambda t:[c["text"] for c in t["rows"][0]]
        self.assertEqual(["#","Target","IPv4","Domain","URL","Status"],head(table(rep)))
        self.assertEqual(["2","vpn-gw","203.0.113.9","-","-","Compromised"],[c["text"] for c in table(rep)["rows"][2]])
        self.api.update(self.rid,{"options":{"scope_columns":["Port","Password","Nope"]}})
        rep=self.api.get(self.rid)
        self.assertEqual(["#","Target","Port"],head(table(rep)))
        self.api.target_allow_secret(self.rid,self.a,"Password",True)
        t=table(self.api.get(self.rid))
        self.assertEqual(["#","Target","Port","Password"],head(t));self.assertEqual([SECRET,"-"],[r[3]["text"] for r in t["rows"][1:]])
        self.api.update(self.rid,{"options":{"scope_columns":[]}})
        self.assertEqual(["#","Target"],head(table(self.api.get(self.rid))))
        self.api.update(self.rid,{"options":{"scope_table":False}})
        self.assertIsNone(table(self.api.get(self.rid)))
        self.assertEqual(["#","Target"],head(table(self.api.get(self.rid),{"scope_table":True})))
        # the widget places the table anywhere, and replaces the automatic one in the scope section
        self.api.update(self.rid,{"options":{"scope_table":None,"scope_columns":None}})
        rep=self.api.get(self.rid)
        concl=next(s for s in rep["sections"] if s["kind"]!="scope" and s["kind"] not in rx.AUTO_KINDS)
        self.api.section_update(concl["id"],{"content":'<p>See</p><div class="rpt-widget" data-widget="scope_targets"></div>'})
        self.api.section_update(self.scope_section()["id"],{"content":'<div class="rpt-widget" data-widget="scope_targets"></div><p>after</p>'})
        doc=rx.prepare(self.api.get(self.rid))
        for kind in ("scope",concl["kind"]):
            blocks=next(s for s in doc["sections"] if s["kind"]==kind)["blocks"]
            self.assertEqual(1,len([b for b in blocks if b["t"]=="table" and b.get("scope")]),kind)
        self.assertNotIn("Targets in scope",rx.blocks_text(next(s for s in doc["sections"] if s["kind"]=="scope")["blocks"]))
        for u in (self.a,self.b):self.api.target_unlink(self.rid,u)
        self.assertIn("No targets are linked",rx.blocks_text(next(s for s in rx.prepare(self.api.get(self.rid))["sections"] if s["kind"]==concl["kind"])["blocks"]))
    def assert_clean(self,text,fmt):
        for s in (SECRET,HASH,"svc_web","tok_live_123","STALETEXT"):self.assertNotIn(s,text,fmt)
    def test_every_format(self):
        self.seed()
        html=open(self.render("html"),encoding="utf-8").read()
        for s in ("Targets in scope","203.0.113.9","The main host is 10.0.0.5 named web01","web01 (https://shop.acme.example)","vpn-gw","typed-host (192.0.2.44)"):self.assertIn(s,html)
        self.assert_clean(html,"html");self.assertNotIn("rpt-tv",html);self.assertNotIn("<script",html.lower())
        with zipfile.ZipFile(self.render("markdown")) as z:md=z.read(next(n for n in z.namelist() if n.endswith(".md"))).decode("utf-8")
        self.assertIn("Targets in scope",md);self.assertIn("10.0.0.5",md);self.assertIn("web01 (https://shop.acme.example)",md.replace("\\",""));self.assert_clean(md,"markdown")
        with open(self.render("csv"),encoding="utf-8-sig",newline="") as f:rows=list(csv.reader(f))
        aff=rows[1][rows[0].index("Affected")]
        self.assertEqual("web01 (https://shop.acme.example)\nvpn-gw\ntyped-host (192.0.2.44)",aff);self.assert_clean(json.dumps(rows),"csv")
        with zipfile.ZipFile(self.render("xlsx")) as z:xl="".join(z.read(n).decode("utf-8","replace") for n in z.namelist() if n.endswith(".xml"))
        self.assertIn("web01 (https://shop.acme.example)",xl);self.assertIn("vpn-gw",xl);self.assert_clean(xl,"xlsx")
        with open(self.render("sarif"),encoding="utf-8") as f:sarif=json.load(f)
        locs=sarif["runs"][0]["results"][0]["locations"]
        self.assertEqual(["https://shop.acme.example","vpn-gw","192.0.2.44"],[l["logicalLocations"][0]["name"] for l in locs])
        self.assertEqual("web01 https://shop.acme.example",locs[0]["logicalLocations"][0]["fullyQualifiedName"]);self.assert_clean(json.dumps(sarif),"sarif")
        with zipfile.ZipFile(self.render("docx")) as z:docx=z.read("word/document.xml").decode("utf-8")
        for s in ("TARGETS IN SCOPE","203.0.113.9","10.0.0.5","vpn-gw"):self.assertIn(s,docx)
        self.assert_clean(docx,"docx")
        pdf=self.render("pdf")
        self.assertGreater(os.path.getsize(pdf),2000)
        if PDFTOTEXT:
            text=subprocess.run([PDFTOTEXT,"-layout",pdf,"-"],capture_output=True,timeout=60).stdout.decode("utf-8","replace")
            for s in ("TARGETS IN SCOPE","203.0.113.9","10.0.0.5","vpn-gw"):self.assertIn(s,text.replace("Targets in scope","TARGETS IN SCOPE"))
            self.assert_clean(text,"pdf")
        with open(self.render("json"),encoding="utf-8") as f:data=f.read()
        self.assert_clean(data,"json");self.assertIn(">10.0.0.5</span>",json.loads(data)["report"]["sections"][[s["kind"] for s in self.api.get(self.rid)["sections"]].index("scope")]["content"])
    def test_allowed_secret_is_exported_only_where_used(self):
        self.seed()
        self.api.target_allow_secret(self.rid,self.a,"Password",True)
        html=open(self.render("html"),encoding="utf-8").read()
        # the finding asked for the Password value of web01; the scope table (default columns) still leaves it out
        self.assertIn("web01 (https://shop.acme.example, "+SECRET.replace("!","!")+")",html.replace("&#x27;","'"))
        self.assertEqual(1,html.count(SECRET));self.assertNotIn(HASH,html)
class CvssVersionTests(unittest.TestCase):
    def finding(self,**kw):
        f={"id":1,"uid":"f1","position":0,"title":"Only rated in 4.0","severity":"critical","status":"open","cvss_vector":"","cvss_score":9.3,"description":"<p>d</p>",
            "cves":[{"id":"CVE-2025-11111","title":"t","cvss_version":"4.0","cvss_vector":V40,"cvss_score":9.3,"severity":"critical","source":"index"}]}
        f.update(kw)
        return {"title":"R","sections":[{"id":1,"kind":"findings","title":"Findings","content":"","position":0}],"findings":[f]}
    def test_v4_only_score_is_labelled_and_keeps_its_vector(self):
        rep=self.finding();doc=rx.prepare(rep);f=doc["findings"][0]
        self.assertEqual(("4.0",V40,"CVSS v4.0","9.3",""),(f["cvss_version"],f["cvss_vector_any"],f["cvss_label"],f["cvss"],f["cvss_vector"]))
        html=rx.html_from_doc(doc)
        self.assertIn("CVSS v4.0",html);self.assertNotIn("CVSS v3.1",html);self.assertIn(V40,html)
        tmp=tempfile.mkdtemp(prefix="loya_cv_")
        try:
            p=os.path.join(tmp,"f.csv");rx.render(rep,"csv",p)
            with open(p,encoding="utf-8-sig",newline="") as fh:rows=list(csv.reader(fh))
            self.assertEqual(("9.3",V40),(rows[1][rows[0].index("CVSS Score")],rows[1][rows[0].index("CVSS Vector")]))
            p=os.path.join(tmp,"f.sarif");rx.render(rep,"sarif",p)
            with open(p,encoding="utf-8") as fh:props=json.load(fh)["runs"][0]["results"][0]["properties"]
            self.assertEqual((V40,"4.0"),(props["cvssVector"],props["cvssVersion"]))
            p=os.path.join(tmp,"f.md.zip");rx.render(rep,"markdown",p)
            with zipfile.ZipFile(p) as z:md=z.read(next(n for n in z.namelist() if n.endswith(".md"))).decode("utf-8")
            self.assertIn("CVSS v4.0",md);self.assertNotIn("CVSS v3.1",md)
            p=os.path.join(tmp,"f.docx");rx.render(rep,"docx",p)
            with zipfile.ZipFile(p) as z:dx=z.read("word/document.xml").decode("utf-8")
            self.assertIn("CVSS v4.0",dx);self.assertNotIn("CVSS v3.1",dx)
            p=os.path.join(tmp,"f.xlsx");rx.render(rep,"xlsx",p)
            with zipfile.ZipFile(p) as z:xl="".join(z.read(n).decode("utf-8","replace") for n in z.namelist() if n.endswith(".xml"))
            self.assertIn("CVSS:4.0/",xl)
            p=os.path.join(tmp,"f.pdf");rx.render(rep,"pdf",p)
            if PDFTOTEXT:
                text=subprocess.run([PDFTOTEXT,"-layout",p,"-"],capture_output=True,timeout=60).stdout.decode("utf-8","replace")
                self.assertIn("CVSS v4.0",text);self.assertNotIn("CVSS v3.1",text)
        finally:shutil.rmtree(tmp,ignore_errors=True)
    def test_v31_fallback_keeps_the_31_label_and_lists_the_cve_rating(self):
        v31="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"
        doc=rx.prepare(self.finding(cvss_vector=v31,cvss_score=9.8));f=doc["findings"][0]
        self.assertEqual(("3.1",v31,"CVSS v3.1"),(f["cvss_version"],f["cvss_vector_any"],f["cvss_label"]))
        html=rx.html_from_doc(doc)
        self.assertIn("CVE Details",html);self.assertIn("9.3 (v4.0)",html);self.assertIn(V40,html)
    def test_bare_score_without_a_matching_cve_is_just_cvss(self):
        f=rx.prepare(self.finding(cves=[],cvss_score=5.0))["findings"][0]
        self.assertEqual(("","","CVSS"),(f["cvss_version"],f["cvss_vector_any"],f["cvss_label"]))
        self.assertEqual("CVSS v3.1",rx.prepare(self.finding(cves=[],cvss_score=None))["findings"][0]["cvss_label"])
    def test_index_source_is_kept(self):
        iso=IsolatedData();iso.start()
        try:
            rep=reports.create_report({"title":"x"})
            f=reports.add_finding(rep["id"],{"title":"c","cves":[{"id":"CVE-2025-11111","source":"index","cvss_version":"4.0","cvss_vector":V40,"cvss_score":9.3},{"id":"CVE-2025-22222","source":"weird"}]})
            self.assertEqual(["index","manual"],[c["source"] for c in f["cves"]]);self.assertEqual(V40,f["cves"][0]["cvss_vector"])
        finally:iso.stop()
class SanitizerTests(unittest.TestCase):
    def test_reference_chip_and_widget(self):
        ok='<p>a <span class="rpt-tv" data-target="abc123" data-key="IPv4">10.0.0.5</span> b</p>'
        self.assertEqual(ok,reports.sanitize_html(ok))
        self.assertEqual('<span class="rpt-tv" data-target="u1" data-key="@name">web01</span>',reports.sanitize_html('<span class="x rpt-tv" data-target="u1" data-key="@name" onclick="x()" style="color:red"><b>web</b><img src=x onerror=1>01<script>1</script></span>'))
        self.assertEqual('<span class="rpt-tv" data-target="u1" data-key="NTLM Hash">h</span>',reports.sanitize_html('<span class="rpt-tv" data-target="u1" data-key="NTLM Hash">h</span>'))
        for bad in ('data-target="a b" data-key="IPv4"','data-target="u1" data-key=""','data-target="u1"','data-key="IPv4"','data-target="u1" data-key="a&quot;b"','data-target="u1" data-key="a&lt;b"','data-target="u1" data-key="{x}"','data-target="'+"u"*65+'" data-key="k"','data-target="u1" data-key="'+"k"*81+'"'):
            self.assertEqual("text",reports.sanitize_html(f'<span class="rpt-tv" {bad}>text</span>'),bad)
        self.assertEqual('<div class="rpt-widget" data-widget="scope_targets"></div>',reports.sanitize_html('<div class="rpt-widget" data-widget="scope_targets">junk<b>x</b></div>'))
        self.assertEqual('<p><span class="rpt-tv" data-target="u1" data-key="k">v</span> <strong>after</strong></p>',reports.sanitize_html('<p><span class="rpt-tv" data-target="u1" data-key="k">v</span> <strong>after</strong></p>'))
    def test_resolver(self):
        links=[{"uid":"u1","name":"web01","snapshot":{"values":{"IPv4":"10.0.0.5","Password":"pw<1>"},"engagement_status":"reported"},"allowed_secret_keys":[]}]
        src=tv("u1","IPv4","old")+tv("u1","ipv4","old")+tv("u1","@name")+tv("u1","@status")+tv("u1","Password","leak")+tv("u1","Missing","kept")+tv("zz","IPv4","kept2")+tv("zz","Token","leak2")
        out=reports.resolve_target_values(src,links,plain=True)
        self.assertEqual("10.0.0.510.0.0.5web01Reported[withheld]keptkept2[withheld]",out)
        links[0]["allowed_secret_keys"]=["Password"]
        self.assertIn(">pw&lt;1&gt;</span>",reports.resolve_target_values(src,links))
        self.assertEqual("<p>x</p>",reports.resolve_target_values("<p>x</p>",links))
    def test_secret_key_rule(self):
        for k in ("Password","pass","PWD","API Token","NTLM Hash","SSH Key","Credentials","Cookie","Session","Private","OTP","PIN","Username","Login","Client Secret"):self.assertTrue(reports.is_secret_key(k),k)
        for k in ("IPv4","IPv6","Domain","URL","Hostname","Port","FQDN","CIDR","Wordlist","OS","Notes"):self.assertFalse(reports.is_secret_key(k),k)
        self.assertEqual(reports._TARGET_SECRET_KEY_RE.pattern,rx._SECRET_KEY_RX.pattern)
class MigrationTests(unittest.TestCase):
    def setUp(self):self.isolated=IsolatedData();self.isolated.start()
    def tearDown(self):self.isolated.stop()
    def test_v16_database_gains_the_tables_and_keeps_its_rows(self):
        self.assertGreaterEqual(common_db.DB_SCHEMA_VERSION,17)
        con=sqlite3.connect(common_db.db_path())
        try:
            common_db.ensure_schema(con)
            con.execute("INSERT INTO Reports(uid,title,status,meta,branding,options,created_at,updated_at) VALUES('r-old','Old report','draft','{}','{}','{}','2026-01-01','2026-01-01')")
            con.execute("INSERT INTO ReportFindings(report_id,uid,position,title,severity,status,data) VALUES(1,'f-old',0,'Old finding','high','open','{}')")
            con.execute("INSERT INTO Notes(note_name,content) VALUES('n','c')")
            con.execute("DROP TABLE ReportTargets");con.execute("DROP TABLE ReportFindingTargets")
            con.execute("DELETE FROM SchemaMigrations WHERE version>=17");con.execute("PRAGMA user_version=16");con.commit()
        finally:con.close()
        # a v16 database is not re-created by the unconditional CREATE in ensure_schema alone: run only the migration path first
        con=sqlite3.connect(common_db.db_path())
        try:
            common_db.apply_migrations(con)
            tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("ReportTargets",tables);self.assertIn("ReportFindingTargets",tables)
            self.assertEqual(common_db.DB_SCHEMA_VERSION,con.execute("PRAGMA user_version").fetchone()[0])
            self.assertEqual(1,con.execute("SELECT COUNT(*) FROM SchemaMigrations WHERE version=17").fetchone()[0])
            self.assertEqual(("Old report",),con.execute("SELECT title FROM Reports").fetchone());self.assertEqual(("Old finding",),con.execute("SELECT title FROM ReportFindings").fetchone())
            self.assertEqual(1,con.execute("SELECT COUNT(*) FROM Notes").fetchone()[0])
            cols=[r[1] for r in con.execute("PRAGMA table_info(ReportTargets)")]
            self.assertEqual(["id","report_id","uid","target_id","profile_id","name","snapshot","allowed_secret_keys","position","linked_at","updated_at"],cols)
            self.assertEqual(["id","finding_id","report_target_uid","keys","position"],[r[1] for r in con.execute("PRAGMA table_info(ReportFindingTargets)")])
            common_db.ensure_schema(con);common_db.apply_migrations(con)
        finally:con.close()
        rep=reports.get_report("r-old")
        self.assertEqual(([],[]),(rep["targets"],rep["findings"][0]["targets"]))
if __name__=="__main__":unittest.main()
