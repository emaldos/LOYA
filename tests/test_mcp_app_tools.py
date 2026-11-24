"""App-wide MCP tools (Cores/Bridge/mcp_app_tools.py): every tool is permission-gated, works through the app's own
services, masks secrets, refuses while locked, asks through the approval queue and tells the UI to refresh."""
import base64,json,threading,time,unittest
from _isolate import IsolatedData
from Cores import common_db
from Cores.Services import ai_service as ai
from Cores.Services import ai_chat_service as chat
from Cores.Services import security_service as security
from Cores.Services import cve_service
from Cores.Bridge import mcp_app_tools as app
PNG=base64.b64encode(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")).decode()
FAKE_CVE={"cve_id":"CVE-2024-3400","title":"CVE-2024-3400: PAN-OS GlobalProtect command injection","severity":"critical","cvss_vector":"CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H","cvss_score":10.0,
          "cwe":"CWE-77","description":"Command injection in GlobalProtect.","impact":"Remote code execution as root.","remediation":"Upgrade PAN-OS.","reference_urls":["https://nvd.nist.gov/vuln/detail/CVE-2024-3400"],"affected":["paloaltonetworks pan-os 10.2"]}
def call(_tool,**args):
    ok,res=chat._call_tool(_tool,args)
    if not ok:raise AssertionError(f"{_tool} failed: {res}")
    return res
def fails(_tool,**args):
    ok,res=chat._call_tool(_tool,args)
    return None if ok else str(res)
class Base(unittest.TestCase):
    def setUp(self):
        self.iso=IsolatedData();self.dir=self.iso.start()
        ai.revoke_session_grant()
        self._cve={n:getattr(cve_service,n) for n in ("to_finding","search","feed")}
        cve_service.to_finding=lambda cid,opts=None:dict(FAKE_CVE)
        cve_service.search=lambda q,limit=20,filters=None:{"items":[{"id":"CVE-2024-3400","title":"PAN-OS"}],"total":1}
        cve_service.feed=lambda filters=None:{"items":[{"id":"CVE-2024-3400"},{"id":"CVE-2023-4966"}],"total":2,"unread":2}
        app.ui_events.clear()
    def tearDown(self):
        for n,f in self._cve.items():setattr(cve_service,n,f)
        common_db.set_locked(False)
        ai.revoke_session_grant()
        self.iso.stop()
    def seed(self):
        note=call("notes_create",name="Recon web01",content="<p>nmap done</p>",group="Recon",tags="recon")
        self.note_id=note.get("id") or note.get("note_id")
        for k in ("IP","Password","NTLM Hash"):call("parameter_add",key=k)
        # targets_add returns the whole target list (ai_chat_service no longer unwraps a one-item list, SA-32).
        added=call("targets_add",name="web01",values={"IP":"10.0.0.5","Password":"Winter2024!","NTLM Hash":"aad3b435b51404ee"})
        self.target_id=next(t for t in (added if isinstance(added,list) else [added]) if t.get("name")=="web01")["id"]
        rep=call("reports_create",title="ACME external")
        self.report_id=rep["id"]
        return note
    def audit(self,event="ai_tool"):return [e["detail"] for e in security.list_audit_events(500) if e["event"]==event]
class RegistryTest(Base):
    def test_every_new_tool_is_registered_once_and_exists(self):
        server_tools={t.name for t in chat._list_tools()}
        for n in app.all_tool_names():
            self.assertIn(n,server_tools,n)
            self.assertEqual(1,sum(n in tools for tools in ai.PERMISSION_TOOL_MAP.values()),n)
        for n in server_tools:self.assertIsNotNone(ai.permission_key(n),n)
    def test_every_new_tool_has_a_test(self):
        src=open(__file__,encoding="utf-8").read().split("class ToolsTest",1)[1]
        for n in app.all_tool_names():self.assertIn('"'+n+'"',src,f"{n} is not exercised in this file")
    def test_defaults(self):
        lv=ai.get_permission_levels()
        self.assertEqual("allow",lv["app_read"])
        self.assertEqual("deny",lv["audit_read"]);self.assertEqual("deny",lv["targets_secrets"])
        self.assertEqual("ask",lv["quickrun_edit"])
        self.assertEqual("deny",ai.preset_levels("assistant")["targets_secrets"])
        self.assertEqual("ask",ai.preset_levels("full")["targets_secrets"])
        self.assertNotIn("targets_secrets",[k for k,v in ai.select_all_permissions().items() if v])
        self.assertIn("Secrets",ai.roles_state()["actions"])
    def test_resources_and_prompts_are_exposed(self):
        import asyncio
        s=chat._get_server()
        uris={str(r.uri) for r in asyncio.run(s.list_resources())}
        self.assertEqual({"loya://app/context","loya://targets/live"},uris)
        self.assertEqual(["loya://reports/{report_id}/outline"],[t.uri_template for t in asyncio.run(s.list_resource_templates())])
        self.assertEqual({"loya-note-from-output","loya-finding-from-cve"},{p.name for p in asyncio.run(s.list_prompts())})
class ToolsTest(Base):
    def test_app_tools(self):
        self.seed()
        call("targets_set_live",target_id=self.target_id)
        ctx=call("app_context")
        self.assertEqual("web01",ctx["live_target"]["name"])
        self.assertEqual("10.0.0.5",ctx["live_target"]["values"]["ip"])
        self.assertNotIn("Winter2024!",json.dumps(ctx))
        self.assertIsInstance(call("app_search",query="web01"),(dict,list))
        self.assertIsInstance(call("dashboard_stats"),dict)
        self.assertIn("Deny",fails("audit_log_read"))
        ai.set_permission_levels({"audit_read":"allow"})
        log=call("audit_log_read",event="ai_tool",limit=5)
        self.assertLessEqual(len(log["items"]),5);self.assertTrue(log["total"]>0)
    def test_note_tools(self):
        self.seed()
        self.assertTrue(call("notes_search",query="nmap")["total"]>=1)
        self.assertTrue(any("Recon" in json.dumps(g) for g in call("notes_groups")))
        call("notes_group_create",name="Loot")
        call("notes_move",note_id=self.note_id,group="Loot")
        call("notes_group_rename",old_name="Loot",new_name="Loot2")
        self.assertEqual("Loot2",call("notes_get",note_id=self.note_id)["group_name"])
        call("notes_pin",note_id=self.note_id,pinned=True)
        call("notes_update",note_id=self.note_id,name="Recon web01",content="<p>nmap done, 3 ports</p>",group="Loot2")
        vers=call("notes_versions",note_id=self.note_id)
        vers=vers if isinstance(vers,list) else [vers]
        self.assertTrue(vers,"saving keeps a version")
        vid=vers[0].get("id") or vers[0].get("version_id")
        self.assertIsInstance(call("notes_version_diff",note_id=self.note_id,version_id=vid),dict)
        call("notes_restore_version",note_id=self.note_id,version_id=vid)
        att=call("notes_attachment_add",note_id=self.note_id,filename="shot.png",data_base64=PNG)
        self.assertEqual("image",att["kind"])
        self.assertIn(att["id"],call("notes_get",note_id=self.note_id)["content_html"])
        self.assertIn("notes",app.ui_events)
    def test_command_and_terminal_history_tools(self):
        self.assertIn("items",call("commands_history"))
        self.assertIn("items",call("command_runs",command_id=1))
        self.assertIn("Deny",fails("terminal_jobs_list"))
        ai.set_permission_levels({"terminal_read":"allow"})
        self.assertIn("items",call("terminal_jobs_list"))
        self.assertIsNotNone(fails("terminal_job_get",job_id="nope"))
    def test_target_tools_and_secret_masking(self):
        self.seed()
        self.assertNotIn("Winter2024!",json.dumps(call("targets_list")))
        self.assertNotIn("aad3b435b51404ee",json.dumps(call("targets_list")))
        call("targets_set_live",target_id=self.target_id)
        live=call("targets_live_get")
        self.assertEqual(app.MASK,live["values"]["password"])
        self.assertIn("Deny",fails("targets_secret_values",target_id=self.target_id))
        ai.set_permission_levels({"targets_secrets":"allow"})
        self.assertEqual("Winter2024!",call("targets_secret_values",target_id=self.target_id)["values"]["Password"])
        call("targets_set_engagement_status",target_id=self.target_id,status="in_progress")
        profiles=call("target_profiles_list")
        call("target_profile_create",name="Engagement B")
        self.assertIn("Engagement B",json.dumps(call("target_profiles_list")))
        pid=(profiles if isinstance(profiles,dict) else profiles[0])["id"]
        call("target_profile_switch",profile_id=pid)
        self.assertIn("targets",app.ui_events)
    def test_report_tools(self):
        self.seed()
        rid=self.report_id
        self.assertIsInstance(call("reports_stats"),dict)
        call("reports_deadlines")
        v=call("report_version_create",report_id=rid,label="before AI")
        vers=call("report_versions_list",report_id=rid)
        self.assertTrue(vers)
        vid=(vers[0] if isinstance(vers,list) else vers)["id"]
        call("report_version_restore",report_id=rid,version_id=vid)
        call("report_schedule_set",report_id=rid,schedule={"milestones":[{"label":"Final report","date":"2026-12-01"}]})
        self.assertIn("Final report",json.dumps(call("report_schedule_get",report_id=rid)))
        tpl=call("report_templates_list")[0]["id"]
        self.assertIsNotNone(call("report_template_get",template_id=tpl))
        ev=call("report_evidence_add_text",content="$ id\nuid=0(root) password=hunter2",title="root shell",command="id")
        self.assertNotIn("hunter2",json.dumps(call("evidence_list")))
        call("report_evidence_add_image",name="shot.png",data_base64=PNG,title="login page")
        lib=call("findings_library_add",entry={"title":"Weak SSH ciphers","severity":"low","description":"<p>CBC ciphers enabled.</p>"})
        lib_id=lib.get("id") if isinstance(lib,dict) else lib
        f1=call("findings_add_from_library",report_id=rid,library_id=lib_id)
        self.assertIn("Weak SSH ciphers",json.dumps(f1))
        f2=call("findings_add_from_cve",report_id=rid,cve_id="cve-2024-3400")
        self.assertEqual("critical",f2["severity"]);self.assertEqual("CWE-77",f2["cwe"]);self.assertIn("CVE-2024-3400",[c.get("id") if isinstance(c,dict) else c for c in f2["cves"]])
        self.assertIn("reports",app.ui_events)
        import asyncio
        outline=json.loads(asyncio.run(chat._get_server().read_resource(f"loya://reports/{rid}/outline"))[0].content)
        self.assertEqual(2,len(outline["findings"]))
    def test_report_scope_tools_never_show_secrets(self):
        from Cores.Bridge.reports_api import ReportsAPI
        self.seed();rid=self.report_id
        avail=call("report_targets_available",query="web01")["items"]
        self.assertTrue(avail);self.assertNotIn("Winter2024!",json.dumps(avail))
        t=avail[0]
        links=call("report_target_link",report_id=rid,items=[{"target_id":t["target_id"],"profile_id":t["profile_id"]}])
        links=links if isinstance(links,list) else [links]
        uid=links[0]["uid"]
        f=call("findings_add",report_id=rid,title="SMB signing disabled",severity="medium")
        self.assertEqual(uid,call("finding_targets_set",finding_id=f["id"],targets=[{"uid":uid,"keys":["@name"]}])["targets"][0]["uid"])
        call("report_target_update",report_id=rid)
        call("report_targets_reorder",report_id=rid,uids=[uid])
        key=next(k for k in (links[0].get("secret_keys") or []) if "pass" in k.lower())
        ReportsAPI().target_allow_secret(rid,uid,key,True)  # the operator's own action, not exposed to AI
        self.assertIn("Winter2024!",json.dumps(ReportsAPI().get(rid)["targets"]),"fixture: the secret is in the report now")
        for res in (call("report_targets_list",report_id=rid),call("reports_get",report_id=rid)):
            self.assertNotIn("Winter2024!",json.dumps(res))
        self.assertNotIn("target_allow_secret",{t.name for t in chat._list_tools()})
        call("report_target_unlink",report_id=rid,uid=uid)
    def test_cve_and_quickrun_tools(self):
        self.assertEqual(1,call("cve_search",query="pan-os")["total"])
        self.assertEqual(2,call("cve_feed")["total"])
        self.assertIn("favorites",call("quickrun_favorites"))
        ai.set_permission_levels({"quickrun_edit":"allow"})
        self.assertIn("CommandsNotes:7",call("quickrun_favorite_set",key="CommandsNotes:7")["favorites"])
        self.assertNotIn("CommandsNotes:7",call("quickrun_favorite_set",key="CommandsNotes:7",favorite=False)["favorites"])
        self.assertIsNotNone(fails("quickrun_favorite_set",key="../../etc"))
class PolicyTest(Base):
    def test_lock_refuses_every_new_tool(self):
        common_db.set_locked(True)
        for n in ("app_context","notes_search","targets_live_get","findings_add_from_cve","cve_feed"):
            self.assertIn("locked",(fails(n,query="x",report_id=1,cve_id="CVE-1") or "").lower() if n!="app_context" else (fails(n) or "").lower(),n)
    def test_ask_goes_through_the_approval_queue_and_is_audited(self):
        seen={}
        def approve():
            end=time.time()+10
            while time.time()<end:
                rows=ai.pending_approvals()
                if rows:seen.update(rows[0]);ai.resolve_approval(rows[0]["id"],"once");return
                time.sleep(0.02)
        t=threading.Thread(target=approve,daemon=True);t.start()
        call("quickrun_favorite_set",key="CommandsNotes:3")
        t.join()
        self.assertEqual(("Quick Run","Edit"),(seen["entity"],seen["action"]))
        self.assertTrue(any("quickrun_favorite_set - approved once" in d for d in self.audit()))
        self.assertIn("quickrun",app.ui_events)
    def test_writes_are_audited(self):
        self.seed()
        # core write tools (notes_create, targets_add, reports_create) refresh the UI too, not only the app-wide ones
        self.assertTrue({"notes","targets","reports"}<=set(app.ui_events),app.ui_events)
        n=len(app.ui_events);call("notes_list");self.assertEqual(n,len(app.ui_events),"reads do not refresh the UI")
        call("notes_group_create",name="X")
        self.assertTrue(any("notes_group_create - allowed" in d for d in self.audit()))
    def test_quickrun_never_shows_secret_placeholders_to_the_ai(self):
        from Cores.Services import terminal_service as term
        self.seed()
        call("targets_set_live",target_id=self.target_id)
        call("commands_create",note_name="SMB",category="Recon",sub_category="smb",command="nxc smb {IP} -u admin -p {Password}")
        rows=call("quickrun_list",query="nxc")
        row=rows if isinstance(rows,dict) else rows[0]
        self.assertIn("10.0.0.5",row["resolved"]);self.assertIn(app.MASK,row["resolved"]);self.assertNotIn("Winter2024!",json.dumps(row))
        ai.set_permission_levels({"quickrun_run":"ask"})
        term.clear_ai_requests()
        out=call("quickrun_run",command_id=row["id"],reason="check SMB")
        self.assertNotIn("Winter2024!",json.dumps(out))
        self.assertNotIn("Winter2024!",json.dumps(security.list_audit_events(500)))
        queued=[r["command"] for r in term.list_ai_requests(True)]
        self.assertEqual(["nxc smb 10.0.0.5 -u admin -p Winter2024!"],queued,"only the command queued for approval gets the real value")
        term.clear_ai_requests()
    def test_ui_scripts_are_fixed_literals(self):
        self.assertFalse(app.notify_ui("x');alert(1);//"))
        for js in app._NOTIFY_SCRIPTS.values():self.assertRegex(js,r"\('[a-z]+','[a-z]*'\);0$")
    def test_page_caps(self):
        p=app.page(list(range(1000)),0,999)
        self.assertEqual(app.MAX_PAGE,len(p["items"]));self.assertTrue(p["more"])
        self.assertIn("more characters cut",app._cap("x"*(app.MAX_TEXT+10)))
class AgentEndToEndTest(Base):
    """An agent session through LOYA's real MCP server (HTTP, its own bearer token), driven the way the Claude Agent SDK
    drives it: create a note, create a report with a finding from a CVE, edit the finding."""
    def test_agent_flow(self):
        import socket,urllib.request
        from Cores.Services import mcp_local_service as mcp
        s=socket.socket();s.bind(("127.0.0.1",0));port=s.getsockname()[1];s.close()
        mcp.start_server(port,register_provider=False)
        tok=mcp.issue_client_token({"id":"runE2E","label":"Claude Agent","provider":"claude","session_id":"e2e"})
        url=f"http://127.0.0.1:{port}/mcp"
        def post(body,sid=None):
            req=urllib.request.Request(url,data=json.dumps(body).encode(),method="POST",headers={"Content-Type":"application/json","Accept":"application/json, text/event-stream","Authorization":"Bearer "+tok})
            if sid:req.add_header("mcp-session-id",sid)
            with urllib.request.urlopen(req,timeout=20) as r:return r.headers.get("mcp-session-id"),r.read().decode()
        def tool(sid,name,args):
            _h,body=post({"jsonrpc":"2.0","id":int(time.time()*1000)%100000,"method":"tools/call","params":{"name":name,"arguments":args}},sid)
            data=json.loads([l[5:] for l in body.splitlines() if l.startswith("data:")][-1],strict=False) if "data:" in body else json.loads(body,strict=False)
            res=data["result"];self.assertFalse(res.get("isError"),res)
            sc=res.get("structuredContent")
            return sc.get("result",sc) if isinstance(sc,dict) else json.loads(res["content"][0]["text"],strict=False)
        try:
            sid,_=post({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"fake-sdk","version":"1"}}})
            post({"jsonrpc":"2.0","method":"notifications/initialized"},sid)
            note=tool(sid,"notes_create",{"name":"Agent note","content":"<p>Found PAN-OS 10.2 on 10.0.0.5. password: hunter2</p>"})
            rep=tool(sid,"reports_create",{"title":"Agent report"})
            f=tool(sid,"findings_add_from_cve",{"report_id":rep["id"],"cve_id":"CVE-2024-3400"})
            tool(sid,"findings_update",{"finding_id":f["id"],"fields":{"affected":["10.0.0.5"],"status":"retest"}})
            got=tool(sid,"reports_get",{"report_id":rep["id"]})
            fs=got["findings"]
            self.assertEqual(1,len(fs));self.assertEqual("10.0.0.5",fs[0]["affected"][0]["name"])
            back=tool(sid,"notes_get",{"note_id":note.get("id") or note.get("note_id")})
            self.assertNotIn("hunter2",json.dumps(back),"results to an agent are redacted")
        finally:
            mcp.revoke_client_token(tok);mcp.stop_server()
        rows=self.audit()
        for n in ("notes_create","reports_create","findings_add_from_cve","findings_update"):
            self.assertTrue(any(d.startswith("[Claude Agent session e2e] "+n) for d in rows),n)
if __name__=="__main__":
    unittest.main()
