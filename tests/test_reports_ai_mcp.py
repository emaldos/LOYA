import json,os,time,unittest
from _isolate import IsolatedData
from Cores import common_db
from Cores.Services import ai_service as ai
from Cores.Services import ai_chat_service as chat
from Cores.Services import reports_service as reports
from Cores.Services import evidence_service as evidence
from Cores.Services import report_ai
from Cores.Bridge.report_ai_api import ReportAIAPI
VECTOR="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"
SECRET="wJalrXUtnFEMIK7MDENGbPxRfiCYEXAMPLEKEY"
REPORT_TOOLS={
    "reports_read":{"reports_list","reports_get","findings_list","report_templates_list","findings_library_search","evidence_list","evidence_get","report_export"},
    "reports_add":{"reports_create","report_section_add","findings_add"},
    "reports_edit":{"reports_update","report_section_update","findings_update"},
    "reports_delete":{"reports_delete","findings_delete"},
}
def tool(name,**args):
    ok,result=chat._call_tool(name,args)
    if not ok:raise AssertionError(f"{name} failed: {result}")
    return result
class Base(unittest.TestCase):
    def setUp(self):
        self.isolated=IsolatedData()
        self.data_dir=self.isolated.start()
        ai.revoke_session_grant()
        report_ai._jobs.clear()
        self._complete=report_ai.complete
        self.calls=[]
    def tearDown(self):
        report_ai.complete=self._complete
        common_db.set_locked(False)
        ai.revoke_session_grant()
        self.isolated.stop()
    def provider(self):
        ai.set_provider("ollama",{"enabled":True,"model":"llama3.2"})
    def fake(self,*replies):
        """Replace the provider call; replies are returned in order (the last one repeats)."""
        queue=list(replies)
        def complete(provider,system,messages):
            self.calls.append({"provider":provider,"system":system,"messages":[dict(m) for m in messages]})
            return queue.pop(0) if len(queue)>1 else queue[0]
        report_ai.complete=complete
    def report(self,**meta):
        m={"client":"ACME Corp","engagement":"Q4 external test","start_date":"2026-11-02","end_date":"2026-11-13","scope_in":["shop.acme.example","10.20.0.0/24"]}
        m.update(meta)
        rep=reports.create_report({"title":"ACME external test","template_id":"web_app","meta":m})
        f=reports.add_finding(rep["id"],{"title":"SQL injection in item lookup","cvss_vector":VECTOR,"cwe":"CWE-89","affected":[{"name":"web01","value":"10.20.0.15"}],
            "description":"<p>The <strong>id</strong> parameter is concatenated into a query.</p>","impact":"<p>Full read access to the shop database.</p>","steps":"<ol><li>Request /item?id=7'</li></ol>"})
        return reports.get_report(rep["id"]),f
class PermissionTests(Base):
    def test_reports_entity_rows_and_defaults(self):
        rows={r["key"]:r for r in ai.permission_rows() if r["entity"]=="Reports"}
        self.assertEqual({"reports_read","reports_add","reports_edit","reports_delete"},set(rows))
        self.assertEqual({"Read","Add","Edit","Delete"},{r["action"] for r in rows.values()})
        for key in ("reports_read","reports_add","reports_edit"):self.assertEqual("allow",rows[key]["level"],key)
        self.assertEqual("deny",rows["reports_delete"]["level"])
        self.assertTrue(rows["reports_delete"]["is_delete"])
        self.assertFalse(any(r["is_shell"] for r in rows.values()))
        # The Reports tools must all be under these keys; other report-related tools (app-wide MCP tools) may join them.
        for key,tools in REPORT_TOOLS.items():self.assertTrue(tools<=set(rows[key]["tools"]),key)
    def test_same_defaults_as_the_notes_entity(self):
        levels=ai.get_permission_levels()
        for action in ("read","add","edit","delete"):self.assertEqual(levels["notes_"+action],levels["reports_"+action],action)
    def test_every_mcp_tool_is_mapped_and_every_mapped_tool_exists(self):
        names={t.name for t in chat._list_tools()}
        self.assertEqual([],sorted(n for n in names if ai.permission_key(n) is None))
        for key,tools in REPORT_TOOLS.items():
            for name in tools:
                self.assertIn(name,names)
                self.assertEqual(key,ai.permission_key(name),name)
        mapped=[t for tools in ai.PERMISSION_TOOL_MAP.values() for t in tools]
        self.assertEqual(len(mapped),len(set(mapped)),"a tool is listed under two permissions")
        self.assertEqual([],sorted(t for t in mapped if t not in names))
    def test_tool_descriptions_use_the_product_words(self):
        for t in chat._list_tools():
            if ai.permission_key(t.name) not in REPORT_TOOLS:continue
            self.assertTrue(len(t.description or "")>40,t.name)
            for word in ("playbook","snippet"):self.assertNotIn(word,t.description.lower(),t.name)
    def test_presets_cover_reports(self):
        self.assertEqual({"reports_read":"allow","reports_add":"deny","reports_edit":"deny","reports_delete":"deny"},{k:v for k,v in ai.preset_levels("read_only").items() if k.startswith("reports_")})
        self.assertEqual({"reports_read":"allow","reports_add":"ask","reports_edit":"ask","reports_delete":"deny"},{k:v for k,v in ai.preset_levels("assistant").items() if k.startswith("reports_")})
        self.assertEqual({"reports_read":"allow","reports_add":"allow","reports_edit":"allow","reports_delete":"ask"},{k:v for k,v in ai.preset_levels("full").items() if k.startswith("reports_")})
    def test_delete_is_denied_out_of_the_box(self):
        rep,f=self.report()
        for name,args in (("findings_delete",{"finding_id":f["id"]}),("reports_delete",{"report_id":rep["id"]})):
            ok,msg=chat._call_tool(name,args)
            self.assertFalse(ok,name)
            self.assertIn("Reports > Delete",msg)
        self.assertEqual(1,len(reports.get_report(rep["id"])["findings"]))
    def test_denied_read_blocks_every_report_tool(self):
        rep,f=self.report()
        ai.set_permission_levels({"reports_read":"deny"})
        calls={"reports_list":{},"reports_get":{"report_id":rep["id"]},"findings_list":{"report_id":rep["id"]},"report_templates_list":{},"findings_library_search":{},"evidence_list":{},"evidence_get":{"evidence_id":"1"},
            "report_export":{"report_id":rep["id"]},"reports_create":{"title":"x"},"report_section_add":{"report_id":rep["id"],"title":"x"},"findings_add":{"report_id":rep["id"],"title":"x"},
            "reports_update":{"report_id":rep["id"],"title":"x"},"report_section_update":{"section_id":rep["sections"][0]["id"],"title":"x"},"findings_update":{"finding_id":f["id"],"fields":{"title":"x"}},
            "findings_delete":{"finding_id":f["id"]},"reports_delete":{"report_id":rep["id"]}}
        self.assertEqual(set().union(*REPORT_TOOLS.values()),set(calls))
        for name,args in calls.items():
            ok,msg=chat._call_tool(name,args)
            self.assertFalse(ok,name)
            self.assertIn("Deny",msg,name)
        after=reports.get_report(rep["id"])
        self.assertEqual("ACME external test",after["title"])
        self.assertEqual(1,len(reports.list_reports()))
    def test_authorize_raises_for_a_denied_tool(self):
        ai.set_permission_levels({"reports_edit":"deny"})
        with self.assertRaises(ai.AIPermissionError):ai.authorize("findings_update",{"finding_id":1})
    def test_locked_app_refuses_before_anything_else(self):
        rep,f=self.report()
        common_db.set_locked(True)
        try:
            for name,args in (("reports_list",{}),("reports_get",{"report_id":rep["id"]}),("findings_add",{"report_id":rep["id"],"title":"x"}),("evidence_get",{"evidence_id":"1"}),("report_export",{"report_id":rep["id"]})):
                ok,msg=chat._call_tool(name,args)
                self.assertFalse(ok,name)
                self.assertIn("locked",msg.lower(),name)
        finally:
            common_db.set_locked(False)
        self.assertEqual(1,len(reports.get_report(rep["id"])["findings"]))
    def test_bridge_class_is_guarded_while_locked(self):
        from Cores.Bridge import api as bridge
        class Holder:
            def __init__(self):self.reportAI=ReportAIAPI()
        holder=Holder()
        bridge._guard_while_locked(holder)
        common_db.set_locked(True)
        try:
            for call in (lambda:holder.reportAI.status(),lambda:holder.reportAI.preview("exec_summary",{"reportId":1}),lambda:holder.reportAI.run_start("exec_summary",{"reportId":1}),lambda:holder.reportAI.run_poll("x")):
                with self.assertRaises(ValueError):call()
        finally:
            common_db.set_locked(False)
        self.assertIn("available",holder.reportAI.status())
class ToolRoundTripTests(Base):
    def test_create_add_update_list_export(self):
        ai.set_permission_levels({"reports_delete":"allow"})
        self.assertIn("web_app",[t["id"] for t in tool("report_templates_list")])
        rep=tool("reports_create",title="ACME web test",template_id="web_app",client="ACME Corp",meta={"engagement":"Q4","scope_in":["shop.acme.example"]})
        rid=rep["id"]
        self.assertEqual(["ACME Corp","Q4",["shop.acme.example"]],[rep["meta"]["client"],rep["meta"]["engagement"],rep["meta"]["scope_in"]])
        self.assertTrue(any(s["kind"]=="executive_summary" for s in rep["sections"]))
        f=tool("findings_add",report_id=rid,title="Stored XSS in comments",cvss_vector="CVSS:3.1/AV:N/AC:L/PR:L/UI:R/S:C/C:L/I:L/A:N",description='<p onclick="x()">Comments are rendered <script>alert(1)</script>unescaped.</p>',affected=["web01"],tags="xss, web")
        self.assertEqual([5.4,"medium","<p>Comments are rendered unescaped.</p>",["xss","web"],"ai"],[f["cvss_score"],f["severity"],f["description"],f["tags"],f["source"]["kind"]])
        self.assertEqual("web01",f["affected"][0]["name"])
        g=tool("findings_update",finding_id=f["id"],fields={"status":"fixed","remediation":"<p>Encode output.</p><iframe src=x></iframe>","cvss_vector":VECTOR,"source":{"kind":"note","ref":"1"}})
        self.assertEqual(["fixed","<p>Encode output.</p>",9.8,"ai"],[g["status"],g["remediation"],g["cvss_score"],g["source"]["kind"]])
        self.assertEqual("Stored XSS in comments",g["title"])
        listed=tool("findings_list",report_id=rid)
        listed=listed if isinstance(listed,list) else [listed]
        self.assertEqual([f["id"]],[x["id"] for x in listed])
        tool("reports_update",report_id=rid,status="review",meta={"methodology":"OWASP WSTG"})
        sec=tool("report_section_add",report_id=rid,title="Lessons",content="<p>ok</p><style>p{}</style>")
        self.assertEqual(["custom","<p>ok</p>"],[sec["kind"],sec["content"]])
        summary=next(s for s in rep["sections"] if s["kind"]=="executive_summary")
        tool("report_section_update",section_id=summary["id"],content='<p>Summary <a href="javascript:alert(1)">x</a></p>')
        full=tool("reports_get",report_id=rid)
        self.assertEqual(["ACME web test","review","OWASP WSTG","ACME Corp"],[full["title"],full["status"],full["meta"]["methodology"],full["meta"]["client"]])
        self.assertEqual(sec["id"],full["sections"][-1]["id"])
        stored=next(s for s in full["sections"] if s["id"]==summary["id"])
        self.assertNotIn("javascript",stored["content"])
        self.assertEqual(summary["title"],stored["title"])
        row=tool("reports_list")
        row=row[0] if isinstance(row,list) else row
        self.assertEqual([rid,1],[row["id"],row["total"]])
        md=tool("report_export",report_id=rid,fmt="markdown")
        self.assertEqual("markdown",md["format"])
        self.assertTrue(md["content"].startswith("# ACME web test"))
        self.assertIn("Stored XSS in comments",md["content"])
        self.assertEqual(len(md["content"]),md["chars"])
        self.assertTrue(tool("findings_delete",finding_id=f["id"]))
        self.assertTrue(tool("reports_delete",report_id=rid))
        self.assertEqual([],reports.list_reports())
    def test_empty_patches_are_refused(self):
        rep,f=self.report()
        for name,args in (("reports_update",{"report_id":rep["id"]}),("report_section_update",{"section_id":rep["sections"][0]["id"]}),("findings_update",{"finding_id":f["id"],"fields":{}})):
            ok,msg=chat._call_tool(name,args)
            self.assertFalse(ok,name)
            self.assertIn("Nothing to change",msg)
    def test_invalid_values_are_rejected_by_the_service(self):
        rep,f=self.report()
        for name,args in (("findings_add",{"report_id":rep["id"],"title":"x","severity":"catastrophic"}),("reports_update",{"report_id":rep["id"],"status":"shipped"}),("reports_get",{"report_id":9999})):
            self.assertFalse(chat._call_tool(name,args)[0],name)
    def test_export_text_formats_and_binary_refusal(self):
        rep,f=self.report()
        html=report_ai.export_text(rep["id"],"html")["content"]
        self.assertIn("SQL injection in item lookup",html)
        self.assertNotIn("<script",html.lower())
        data=json.loads(report_ai.export_text(rep["id"],"json")["content"])
        self.assertEqual("ACME external test",data["report"]["title"])
        self.assertIn("not a re-importable backup",data["note"])
        sarif=json.loads(report_ai.export_text(rep["id"],"sarif")["content"])
        self.assertEqual("2.1.0",sarif["version"])
        csv_text=report_ai.export_text(rep["id"],"csv")["content"]
        self.assertTrue(csv_text.startswith('"ID","Title","Severity"'))
        self.assertIn("SQL injection in item lookup",csv_text)
        self.assertEqual("markdown",report_ai.export_text(rep["id"],"md")["format"])
        chat._call_tool("reports_list",{})
        before=set(os.listdir(self.data_dir))
        for fmt in ("pdf","docx","xlsx"):
            ok,msg=chat._call_tool("report_export",{"report_id":rep["id"],"fmt":fmt})
            self.assertFalse(ok,fmt)
            self.assertIn("export it from the app",msg)
        self.assertFalse(chat._call_tool("report_export",{"report_id":rep["id"],"fmt":"exe"})[0])
        self.assertEqual(before,set(os.listdir(self.data_dir)),"an export wrote a file into the data directory")
    def test_export_redacts_evidence_and_drops_image_data(self):
        reports.defaults_set({"redact_evidence":False})
        ev=evidence.save_text({"title":"env dump","content":"AWS_SECRET_ACCESS_KEY="+SECRET+"\nok\n"})
        rep,f=self.report()
        reports.update_finding(f["id"],{"evidence":[{"evidence_uid":ev["uid"],"caption":"Environment"}]})
        self.assertIn(SECRET,evidence.get(ev["uid"])["content"])
        for fmt in report_ai.EXPORT_TEXT_FORMATS:
            self.assertNotIn(SECRET,report_ai.export_text(rep["id"],fmt)["content"],fmt)
        self.assertIn("[redacted]",report_ai.export_text(rep["id"],"markdown")["content"])
        data=json.loads(report_ai.export_text(rep["id"],"json")["content"])
        self.assertEqual([ev["uid"]],[e["uid"] for e in data["evidence"]])
        self.assertFalse(any("data_b64" in a for a in data["assets"].values()))
    def test_library_search(self):
        hits=report_ai.library_search("sql injection",5)
        self.assertTrue(hits and "sql" in hits[0]["title"].lower())
        self.assertTrue(hits[0]["description"] and hits[0]["remediation"])
        self.assertEqual(3,len(report_ai.library_search("",3)))
        self.assertEqual([],report_ai.library_search("zzz-no-such-entry"))
        self.assertTrue(report_ai.library_search("CWE-79"))
class EvidenceToolTests(Base):
    def setUp(self):
        super().setUp()
        reports.defaults_set({"redact_evidence":False})
    def test_evidence_get_redacts_and_drops_events(self):
        ev=evidence.save_job({"session_id":"s1","job_key":"j1","command":"mysql -u root --password=Hunter2pass -e 'show databases'","output":"api_key=sk-live-123456\nAuthorization: Bearer abc.def.ghi\nshop\nusers\n","exit_code":0,"started_at":"2026-11-23T10:00:00Z","ended_at":"2026-11-23T10:00:02Z"})
        raw=evidence.get(ev["id"])
        self.assertIn("sk-live-123456",raw["content"])
        got=tool("evidence_get",evidence_id=str(ev["id"]))
        blob=json.dumps(got)
        for secret in ("sk-live-123456","abc.def.ghi","Hunter2pass"):self.assertNotIn(secret,blob,secret)
        self.assertIn("[redacted]",got["content"])
        self.assertIn("shop",got["content"])
        self.assertTrue(got["redacted_for_ai"]>=3)
        self.assertFalse(got["truncated"])
        self.assertNotIn("events",got)
        self.assertEqual(got["uid"],tool("evidence_get",evidence_id=ev["uid"])["uid"])
    def test_evidence_get_shortens_huge_output(self):
        ev=evidence.save_text({"title":"big","content":"HEAD\n"+("line of output\n"*20000)+"TAIL token=supersecretvalue\n"})
        got=report_ai.evidence_for_ai(ev["id"])
        self.assertTrue(got["truncated"])
        self.assertTrue(len(got["content"])<report_ai.EVIDENCE_TOOL_LIMIT+200)
        self.assertTrue(got["content"].startswith("HEAD"))
        self.assertIn("characters left out",got["content"])
        self.assertIn("TAIL",got["content"])
        self.assertNotIn("supersecretvalue",got["content"])
    def test_evidence_list_redacts_previews(self):
        evidence.save_text({"title":"creds","content":"password: Sup3rSecret!\nmore"})
        rows=report_ai.evidence_list_for_ai()
        self.assertEqual(1,len(rows))
        self.assertNotIn("Sup3rSecret!",json.dumps(rows))
        self.assertNotIn("content",rows[0])
        self.assertEqual([],report_ai.evidence_list_for_ai(query="nothing-matches-this"))
    def test_missing_evidence_is_an_error(self):
        ok,msg=chat._call_tool("evidence_get",{"evidence_id":"999"})
        self.assertFalse(ok)
        self.assertIn("Evidence not found",msg)
class StatusTests(Base):
    def test_no_provider_means_unavailable(self):
        st=report_ai.status()
        self.assertFalse(st["available"])
        self.assertIn("No AI provider is enabled",st["reason"])
        with self.assertRaises(ValueError):report_ai.preview("exec_summary",{"reportId":1})
    def test_enabled_provider_is_reported_without_touching_the_network(self):
        self.provider()
        st=ReportAIAPI().status()
        self.assertEqual([True,"Ollama","llama3.2",True],[st["available"],st["provider"],st["model"],st["local"]])
    def test_ai_switched_off_hides_the_feature(self):
        self.provider()
        ai.set_enabled(False)
        self.assertFalse(report_ai.status()["available"])
    def test_the_default_provider_wins(self):
        self.provider()
        ai.set_provider("api",{"enabled":True,"provider_kind":"anthropic","api_key":"sk-test-0000","model":"claude-test"})
        ai.set_default_provider("api")
        p=report_ai.resolve_provider()
        self.assertEqual(["Anthropic API","claude-test","api.anthropic.com",False,"anthropic"],[p["provider"],p["model"],p["destination"],p["local"],p["style"]])
        self.assertIn("api.anthropic.com",p["note"])
        self.assertNotIn("sk-test-0000",json.dumps(report_ai.status()))
    def test_api_without_a_key_is_unavailable(self):
        ai.set_provider("api",{"enabled":True,"provider_kind":"openai","api_key":""})
        self.assertIn("No API key",report_ai.status()["reason"])
    def test_ollama_cloud_models_are_flagged_as_leaving_the_machine(self):
        ai.set_provider("ollama",{"enabled":True,"model":"gpt-oss:120b-cloud"})
        p=report_ai.resolve_provider()
        self.assertFalse(p["local"])
        self.assertIn("leaves this machine",p["note"])
class PreviewTests(Base):
    def setUp(self):
        super().setUp()
        self.provider()
        self.fake("SHOULD NOT BE CALLED")
    def test_exec_summary_preview_builds_the_prompt_without_calling_the_provider(self):
        rep,f=self.report()
        p=report_ai.preview("exec_summary",{"reportId":rep["id"]})
        self.assertEqual([],self.calls)
        self.assertEqual(["Ollama","llama3.2",True],[p["provider"],p["model"],p["local"]])
        for needle in ("ACME external test","ACME Corp","2026-11-02 to 2026-11-13","shop.acme.example","1 critical","[CRITICAL] SQL injection in item lookup","web01 (10.20.0.15)","concatenated into a query"):self.assertIn(needle,p["prompt"],needle)
        self.assertNotIn("<p>",p["prompt"])
        self.assertTrue(p["prompt"].rstrip().endswith("=== END DATA ==="))
        self.assertIn("Never invent",p["system"])
        self.assertIn("Not enough information",p["system"])
        self.assertEqual(len(p["system"])+len(p["prompt"]),p["prompt_chars"])
        self.assertTrue(any("1 finding" in s for s in p["summary"]))
        self.assertTrue(any("2 in-scope entries" in s for s in p["summary"]))
        self.assertEqual(64,len(p["digest"]))
    def test_preview_redacts_secrets_and_says_so(self):
        rep,f=self.report()
        reports.update_finding(f["id"],{"description":"<p>Login with password=Winter2026! works. AWS_SECRET_ACCESS_KEY="+SECRET+"</p>"})
        for action,payload in (("exec_summary",{"reportId":rep["id"]}),("suggest_remediation",{"reportId":rep["id"],"findingId":f["id"]}),("suggest_cvss",{"reportId":rep["id"],"findingId":f["id"]}),
                ("rewrite_finding",{"reportId":rep["id"],"findingId":f["id"],"field":"description","text":"<p>token=abcdef123456 was accepted. "+SECRET+"=x AWS_SECRET_ACCESS_KEY="+SECRET+"</p>"})):
            p=report_ai.preview(action,payload)
            self.assertNotIn("AWS_SECRET_ACCESS_KEY="+SECRET,p["prompt"],action)
            self.assertNotIn("Winter2026!",p["prompt"],action)
            self.assertNotIn("abcdef123456",p["prompt"],action)
            self.assertIn("[redacted]",p["prompt"],action)
            self.assertTrue(p["redacted"]>=1,action)
            self.assertTrue(any("redaction marker" in s for s in p["summary"]),action)
        self.assertEqual([],self.calls)
    def test_prose_with_a_hyphenated_p_word_is_not_mistaken_for_a_password_flag(self):
        rep,f=self.report()
        reports.update_finding(f["id"],{"impact":"<p>A well-positioned attacker on a non-production host can intercept traffic. Seen with mysql -pTopSecret1 on the host.</p>"})
        p=report_ai.preview("exec_summary",{"reportId":rep["id"]})
        self.assertIn("well-positioned attacker on a non-production host",p["prompt"])
        self.assertNotIn("TopSecret1",p["prompt"])
        self.assertNotIn("\ue000",p["prompt"])
        self.assertEqual(1,p["redacted"])
    def test_exec_summary_stays_inside_the_budget(self):
        rep,f=self.report()
        for i in range(80):reports.add_finding(rep["id"],{"title":f"Finding number {i}","severity":"low","description":"<p>"+("Long description text. "*200)+"</p>","impact":"<p>"+("Impact text. "*200)+"</p>"})
        p=report_ai.preview("exec_summary",{"reportId":rep["id"]})
        self.assertTrue(len(p["prompt"])<=report_ai.PROMPT_BUDGET+400,len(p["prompt"]))
        self.assertIn("SQL injection in item lookup",p["prompt"])
        self.assertTrue(any("60 most severe of 81" in s for s in p["summary"]))
    def test_session_preview_redacts_and_truncates(self):
        reports.defaults_set({"redact_evidence":False})
        body="$ cat .env\nAWS_SECRET_ACCESS_KEY="+SECRET+"\n"+("scan line with nothing special\n"*4000)+"LAST LINE api_key=tail-secret-value\n"
        ev=evidence.save_text({"title":"recon session","content":body,"command":"cat .env"})
        self.assertIn(SECRET,evidence.get(ev["id"])["content"])
        p=report_ai.preview("summarise_session",{"evidenceId":ev["id"]})
        self.assertNotIn(SECRET,p["prompt"])
        self.assertNotIn("tail-secret-value",p["prompt"])
        self.assertIn("[redacted]",p["prompt"])
        self.assertIn("LAST LINE",p["prompt"])
        self.assertIn("characters left out",p["prompt"])
        self.assertTrue(len(p["prompt"])<report_ai.EVIDENCE_BUDGET+1500,len(p["prompt"]))
        self.assertTrue(any("shortened" in s for s in p["summary"]))
        self.assertEqual([],self.calls)
    def test_rewrite_uses_the_unsaved_editor_text(self):
        rep,f=self.report()
        p=report_ai.preview("rewrite_finding",{"reportId":rep["id"],"findingId":f["id"],"field":"impact","text":"<p>attacker can <b>dump</b> everything<script>x</script></p>"})
        self.assertIn("attacker can dump everything",p["prompt"])
        self.assertNotIn("script",p["prompt"].split("=== DATA ===")[1])
        self.assertNotIn("Full read access",p["prompt"])
        self.assertIn('"Impact"',p["prompt"])
    def test_bad_input_is_refused(self):
        rep,f=self.report()
        cases=(("nope",{}),("exec_summary",{"reportId":9999}),("rewrite_finding",{"reportId":rep["id"],"findingId":f["id"],"field":"title","text":"x"}),("rewrite_finding",{"reportId":rep["id"],"findingId":f["id"],"field":"impact","text":"<p> </p>"}),
            ("suggest_cvss",{"reportId":rep["id"],"findingId":9999}),("summarise_session",{"evidenceId":9999}),("exec_summary",None))
        for action,payload in cases:
            with self.assertRaises(ValueError,msg=action):report_ai.preview(action,payload)
        other=reports.create_report({"title":"Other"})
        with self.assertRaises(ValueError):report_ai.preview("suggest_cvss",{"reportId":other["id"],"findingId":f["id"]})
        empty=reports.add_finding(rep["id"],{"title":"Bare"})
        with self.assertRaises(ValueError):report_ai.preview("suggest_cvss",{"reportId":rep["id"],"findingId":empty["id"]})
        self.assertEqual([],self.calls)
    def test_denied_reports_read_refuses_and_points_to_ai_roles(self):
        rep,f=self.report()
        ai.set_permission_levels({"reports_read":"deny"})
        for call in (lambda:report_ai.preview("exec_summary",{"reportId":rep["id"]}),lambda:report_ai.run("exec_summary",{"reportId":rep["id"]}),lambda:report_ai.run_start("exec_summary",{"reportId":rep["id"]})):
            with self.assertRaises(ValueError) as ctx:call()
            self.assertIn("Settings > AI > Roles",str(ctx.exception))
        self.assertEqual([],self.calls)
        ai.set_permission_levels({"reports_read":"ask"})
        self.assertTrue(report_ai.preview("exec_summary",{"reportId":rep["id"]})["prompt"])
class RunTests(Base):
    def setUp(self):
        super().setUp()
        self.provider()
    def test_run_sends_exactly_the_previewed_text_with_no_tools(self):
        rep,f=self.report()
        self.fake("<think>plan</think>\nThe assessment identified **one** critical issue.\n\n<script>alert(1)</script>")
        p=report_ai.preview("exec_summary",{"reportId":rep["id"]})
        out=report_ai.run("exec_summary",{"reportId":rep["id"]},p["digest"])
        self.assertEqual(1,len(self.calls))
        call=self.calls[0]
        self.assertEqual([p["system"],[{"role":"user","content":p["prompt"]}]],[call["system"],call["messages"]])
        self.assertEqual("llama3.2",call["provider"]["model"])
        self.assertNotIn("plan",out["text"])
        self.assertTrue(out["text"].startswith("The assessment identified"))
        self.assertEqual(["","",None,"Ollama"],[out["html"],out["vector"],out["score"],out["provider"]])
    def test_a_changed_report_invalidates_the_consent(self):
        rep,f=self.report()
        self.fake("text")
        p=report_ai.preview("exec_summary",{"reportId":rep["id"]})
        reports.add_finding(rep["id"],{"title":"New finding after the preview","severity":"high"})
        with self.assertRaises(ValueError) as ctx:report_ai.run("exec_summary",{"reportId":rep["id"]},p["digest"])
        self.assertIn("changed since you reviewed",str(ctx.exception))
        self.assertEqual([],self.calls)
    def test_output_cleaning(self):
        self.assertEqual("Body text.",report_ai.clean_output("```markdown\nBody text.\n```"))
        self.assertEqual("a\nb",report_ai.clean_output("a\r\nb\x00\x07"))
        self.assertEqual("",report_ai.clean_output(None))
        self.assertEqual(report_ai.MAX_OUTPUT,len(report_ai.clean_output("x"*(report_ai.MAX_OUTPUT+500))))
    def test_empty_and_not_enough_information_replies_are_errors(self):
        rep,f=self.report()
        for reply in ("","  \n","<think>only thoughts</think>","Not enough information."):
            self.fake(reply)
            with self.assertRaises(ValueError,msg=repr(reply)):report_ai.run("suggest_remediation",{"reportId":rep["id"],"findingId":f["id"]})
    def test_cvss_reply_is_validated_and_normalised(self):
        rep,f=self.report()
        self.fake("VECTOR: cvss:3.1/av:n/ac:l/pr:n/ui:n/s:u/c:h/i:h/a:n\nRATIONALE:\n- AV: reachable over the network\n- AC: no special conditions")
        out=report_ai.run("suggest_cvss",{"reportId":rep["id"],"findingId":f["id"]})
        self.assertEqual(["CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:N",9.1,"critical"],[out["vector"],out["score"],out["severity"]])
        self.assertEqual("- AV: reachable over the network\n- AC: no special conditions",out["rationale"])
        self.assertEqual(1,len(self.calls))
        self.assertNotIn(VECTOR,self.calls[0]["messages"][0]["content"],"the stored vector must not anchor the suggestion")
    def test_invalid_cvss_is_retried_once_then_accepted(self):
        rep,f=self.report()
        self.fake("VECTOR: CVSS:3.1/AV:X/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H\nRATIONALE:\n- AV: unsure","VECTOR: CVSS:3.1/AV:A/AC:H/PR:L/UI:N/S:U/C:L/I:L/A:N\nRATIONALE:\n- AV: adjacent")
        out=report_ai.run("suggest_cvss",{"reportId":rep["id"],"findingId":f["id"]})
        self.assertEqual("CVSS:3.1/AV:A/AC:H/PR:L/UI:N/S:U/C:L/I:L/A:N",out["vector"])
        self.assertEqual(2,len(self.calls))
        retry=self.calls[1]["messages"]
        self.assertEqual(["user","assistant","user"],[m["role"] for m in retry])
        self.assertIn("did not contain a valid CVSS v3.1 base vector",retry[2]["content"])
    def test_invalid_cvss_twice_is_an_error(self):
        rep,f=self.report()
        for reply in ("I think this is about a 9.8, critical.","VECTOR: CVSS:3.1/AV:N/AC:L","VECTOR: CVSS:2.0/AV:N/AC:L/Au:N/C:P/I:P/A:P","VECTOR: CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H/AV:L"):
            self.calls.clear()
            self.fake(reply)
            with self.assertRaises(ValueError,msg=reply) as ctx:report_ai.run("suggest_cvss",{"reportId":rep["id"],"findingId":f["id"]})
            self.assertIn("valid CVSS 3.1 vector",str(ctx.exception))
            self.assertEqual(2,len(self.calls),reply)
    def test_parse_cvss_helper(self):
        res,rationale=report_ai.parse_cvss("Sure.\nAV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H is my answer")
        self.assertEqual(["CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H",10.0],[res["vector"],res["score"]])
        self.assertEqual("Sure.",rationale)
        self.assertIsNone(report_ai.parse_cvss("")[0])
    def test_summarise_session_never_sends_a_secret(self):
        reports.defaults_set({"redact_evidence":False})
        ev=evidence.save_job({"session_id":"s1","job_key":"j1","command":"curl -H 'Authorization: Bearer eyJhbGciOi.payload.sig' https://api.acme.example/me","output":"{\"user\":\"admin\"}\n","exit_code":0})
        self.fake("The tester queried the API as **admin**.\n\n- /me returned the admin account")
        out=report_ai.run("summarise_session",{"evidenceId":ev["id"]})
        sent=self.calls[0]["messages"][0]["content"]
        self.assertNotIn("eyJhbGciOi.payload.sig",sent)
        self.assertIn("admin",sent)
        self.assertIn("returned the admin account",out["text"])
    def test_provider_errors_surface_as_messages(self):
        rep,f=self.report()
        def boom(provider,system,messages):raise RuntimeError("Could not reach http://127.0.0.1:11434/v1/chat/completions: Connection refused")
        report_ai.complete=boom
        with self.assertRaises(RuntimeError):report_ai.run("exec_summary",{"reportId":rep["id"]})
    def test_run_is_written_to_the_ai_activity_log(self):
        rep,f=self.report()
        self.fake("Summary.")
        report_ai.run("exec_summary",{"reportId":rep["id"]})
        rows=[r for r in ai.activity(20) if "report_ai.exec_summary" in json.dumps(r)]
        self.assertEqual(1,len(rows))
        self.assertNotIn("concatenated into a query",json.dumps(rows))
    def wait(self,job_id,timeout=5):
        deadline=time.time()+timeout
        while time.time()<deadline:
            r=report_ai.run_poll(job_id)
            if r["done"]:return r
            time.sleep(0.02)
        self.fail("the job did not finish")
    def test_job_start_poll(self):
        rep,f=self.report()
        self.fake("Remediate by using parameterised queries.")
        api=ReportAIAPI()
        p=api.preview("suggest_remediation",{"reportId":rep["id"],"findingId":f["id"]})
        job=api.run_start("suggest_remediation",{"reportId":rep["id"],"findingId":f["id"]},p["digest"])
        r=self.wait(job["job_id"])
        self.assertIsNone(r["error"])
        self.assertEqual("Remediate by using parameterised queries.",r["result"]["text"])
        self.assertTrue(report_ai.run_poll(job["job_id"])["error"])
        self.assertEqual({},report_ai._jobs)
    def test_job_errors_are_reported_by_poll(self):
        rep,f=self.report()
        self.fake("no vector here")
        job=report_ai.run_start("suggest_cvss",{"reportId":rep["id"],"findingId":f["id"]})
        r=self.wait(job["job_id"])
        self.assertIn("valid CVSS 3.1 vector",r["error"])
        self.assertIsNone(r["result"])
    def test_a_cancelled_job_throws_its_reply_away(self):
        import threading
        rep,f=self.report()
        gate=threading.Event();entered=threading.Event()
        def slow(provider,system,messages):
            entered.set();gate.wait(5)
            return "late reply"
        report_ai.complete=slow
        job=report_ai.run_start("exec_summary",{"reportId":rep["id"]})
        self.assertTrue(entered.wait(5))
        self.assertFalse(report_ai.run_poll(job["job_id"])["done"])
        self.assertTrue(report_ai.run_cancel(job["job_id"]))
        gate.set()
        deadline=time.time()+5
        while job["job_id"] in report_ai._jobs and time.time()<deadline:time.sleep(0.02)
        self.assertNotIn(job["job_id"],report_ai._jobs)
        self.assertFalse(report_ai.run_cancel(job["job_id"]))
        self.assertFalse(report_ai.run_cancel("nope"))
class ProviderCallTests(Base):
    def setUp(self):
        super().setUp()
        self._post=chat._http_post_json
        self.posts=[]
    def tearDown(self):
        chat._http_post_json=self._post
        super().tearDown()
    def capture(self,reply):
        def post(url,body,headers=None,timeout=120):
            self.posts.append({"url":url,"body":body,"headers":headers or {}})
            return reply
        chat._http_post_json=post
    def test_openai_style_request_has_no_tools(self):
        self.provider()
        self.capture({"choices":[{"message":{"content":"hello"}}]})
        self.assertEqual("hello",report_ai.complete(report_ai.resolve_provider(),"SYS",[{"role":"user","content":"DATA"}]))
        post=self.posts[0]
        self.assertEqual("http://127.0.0.1:11434/v1/chat/completions",post["url"])
        self.assertEqual({"model":"llama3.2","messages":[{"role":"system","content":"SYS"},{"role":"user","content":"DATA"}],"stream":False},post["body"])
    def test_anthropic_style_request_has_no_tools(self):
        ai.set_provider("api",{"enabled":True,"provider_kind":"anthropic","api_key":"sk-test-0000","model":"claude-test"})
        self.capture({"content":[{"type":"thinking","thinking":"x"},{"type":"text","text":"hello"}],"stop_reason":"end_turn"})
        self.assertEqual("hello",report_ai.complete(report_ai.resolve_provider(),"SYS",[{"role":"user","content":"DATA"}]))
        post=self.posts[0]
        self.assertEqual("https://api.anthropic.com/v1/messages",post["url"])
        self.assertEqual({"model","max_tokens","system","messages"},set(post["body"]))
        self.assertEqual("sk-test-0000",post["headers"]["x-api-key"])
    def test_anthropic_refusal_is_an_error(self):
        ai.set_provider("api",{"enabled":True,"provider_kind":"anthropic","api_key":"sk-test-0000","model":"claude-test"})
        self.capture({"content":[],"stop_reason":"refusal"})
        with self.assertRaises(ValueError):report_ai.complete(report_ai.resolve_provider(),"SYS",[{"role":"user","content":"DATA"}])
class ClipTests(unittest.TestCase):
    def test_clip(self):
        self.assertEqual("short",report_ai.clip("short",100))
        out=report_ai.clip("a"*500+"\n"+"b"*500+"\nEND",300,tail=50)
        self.assertTrue(out.startswith("aaa") and out.endswith("END"))
        self.assertIn("characters left out",out)
        self.assertTrue(len(out)<400)
        self.assertEqual("",report_ai.clip(None,10))
if __name__=="__main__":
    unittest.main()
