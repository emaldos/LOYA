"""Chain Diagrams for AI clients: the AI Roles rows, the MCP tools (through build_server) and the forced first-run approval."""
import os,sys,time,unittest
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from _isolate import IsolatedData
from _flow_helpers import slow,node,cmd,graph,set_live_target,wait_until
from Cores import common_db
from Cores.Services import ai_service as ai
from Cores.Services import ai_chat_service as chat
from Cores.Services import flow_engine as engine
from Cores.Services import flow_service as flows
from Cores.Services import flow_store as store
from Cores.Services import playbooks_service as chains
from Cores.Services import terminal_service as terminal
from Cores.Services import security_service as security
TOOLS=("chain_get","chain_templates","chain_create","chain_update","chain_dry_run","chain_run","chain_run_status","chain_run_stop")
class Base(unittest.TestCase):
    def setUp(self):
        self.iso=IsolatedData();self.iso.start()
        terminal.set_enabled(True)   # real runs need the terminal extension
        ai.revoke_session_grant()
        self.asked=[]
        self.answer="approved"
        self._real_request=ai.request_approval
        def fake(tool_name,summary="",timeout=None,reason=None,labels=None):
            self.asked.append((tool_name,summary))
            return self.answer
        ai.request_approval=fake
    def tearDown(self):
        ai.request_approval=self._real_request
        ai.revoke_session_grant()
        common_db.set_locked(False)
        flows.stop_all("test teardown")
        for run in list(engine._runs.values()):run.finished.wait(10)
        engine._runs.clear();del engine._unsaved[:]
        terminal.clear_batch_output()
        self.iso.stop()
    def ok(self,tool,**args):
        good,result=chat._call_tool(tool,args)
        self.assertTrue(good,result)
        return result
    def refused(self,tool,**args):
        good,result=chat._call_tool(tool,args)
        self.assertFalse(good,result)
        return str(result)
    def audit(self,event="ai_tool"):
        return [e["detail"] for e in security.list_audit_events(500) if e["event"]==event]
    def simple(self,*lines):
        return graph([cmd("a",*(lines or ("echo from-ai",)))],["start.out>a"])
    def finish(self,run_id,timeout=30):
        return flows.wait(run_id,timeout)
class PermissionRowsTest(Base):
    def test_the_four_rows_exist_with_their_tools(self):
        # mcp_flow_tools adds the node catalog, validate-without-saving and node output readers to Read and the node-by-node edits to Edit.
        self.assertEqual(["chain_get","chain_dry_run","chain_run_status","chain_templates","chain_node_types","chain_validate","chain_run_output"],ai.PERMISSION_TOOL_MAP["chain_diagrams_read"])
        self.assertEqual(["chain_create"],ai.PERMISSION_TOOL_MAP["chain_diagrams_add"])
        self.assertEqual(["chain_update","chain_node_add","chain_node_set","chain_node_delete","chain_connect"],ai.PERMISSION_TOOL_MAP["chain_diagrams_edit"])
        self.assertEqual(["chain_run","chain_run_stop"],ai.PERMISSION_TOOL_MAP["chain_diagrams_run"])
        for key,action in (("chain_diagrams_read","Read"),("chain_diagrams_add","Add"),("chain_diagrams_edit","Edit"),("chain_diagrams_run","Run")):
            self.assertEqual(("Chain Diagrams",action),ai.PERMISSION_LABELS[key])
    def test_run_is_shell_class_and_denied_by_default(self):
        levels=ai.get_permission_levels()
        self.assertEqual("deny",levels["chain_diagrams_run"])
        self.assertEqual(("allow","allow","allow"),(levels["chain_diagrams_read"],levels["chain_diagrams_add"],levels["chain_diagrams_edit"]))
        rows={r["key"]:r for r in ai.permission_rows()}
        self.assertTrue(rows["chain_diagrams_run"]["is_shell"])
        self.assertFalse(rows["chain_diagrams_read"]["is_shell"])
        self.assertEqual("deny",ai.tool_decision("chain_run"));self.assertEqual("deny",ai.tool_decision("chain_run_stop"))
    def test_presets_never_hand_over_run_silently(self):
        self.assertEqual("deny",ai.preset_levels("read_only")["chain_diagrams_run"])
        self.assertEqual("deny",ai.preset_levels("assistant")["chain_diagrams_run"])
        self.assertEqual("ask",ai.preset_levels("full")["chain_diagrams_run"])
        ai.select_all_permissions()
        self.assertFalse(ai.tool_allowed("chain_run"))
    def test_every_chain_tool_is_registered_and_covered_once(self):
        names=[t.name for t in chat._list_tools()]
        for tool in TOOLS:
            self.assertIn(tool,names)
            self.assertEqual(1,sum(tool in tools for tools in ai.PERMISSION_TOOL_MAP.values()),tool)
        for tool in ("chains_list","chains_run","chains_status"):self.assertIn(tool,names)
    def test_an_unlisted_tool_is_denied(self):
        self.assertEqual("deny",ai.tool_decision("chain_delete"))
        with self.assertRaises(ai.AIPermissionError):ai.authorize("chain_delete",{"chain_id":1})
        self.assertTrue(any("chain_delete - blocked" in d for d in self.audit()))
class CreateAndEditTest(Base):
    def test_chain_create_marks_the_chain_ai_made_and_unreviewed(self):
        token=ai.set_client({"id":"c1","label":"Claude Code","provider":"mcp"})
        try:out=self.ok("chain_create",name="AI recon",graph=self.simple(),caller="airecon")
        finally:ai.reset_client(token)
        pid=out["playbook_id"]
        got=flows.get(pid)
        self.assertEqual((True,False,"Claude Code","airecon",False),(got["ai_made"],got["ai_reviewed"],got["ai_client"],got["caller"],got["derived"]))
        self.assertTrue(any("by AI (Claude Code)" in d for d in self.audit("chain_diagram_create")))
        self.assertTrue(any("chain_create - allowed" in d for d in self.audit()))
        listed=self.ok("chains_list")
        rows={r["id"]:r for r in (listed if isinstance(listed,list) else [listed])}
        self.assertEqual((True,True),(rows[pid]["has_diagram"],rows[pid]["ai_made"]))
    def test_chain_create_refuses_an_invalid_graph_and_leaves_nothing_behind(self):
        bad={"schema":1,"nodes":[node("start","start"),node("x","command",commands=[])],"edges":[{"id":"e1","from":"start","port":"nowhere","to":"x"}]}
        message=self.refused("chain_create",name="Broken",graph=bad)
        self.assertIn("not valid",message)
        self.assertEqual([],chains.list_playbooks())
    def test_chain_create_honours_the_add_permission(self):
        ai.set_permission_levels({"chain_diagrams_add":"deny"})
        self.assertIn("Deny",self.refused("chain_create",name="x",graph=self.simple()))
        self.assertEqual([],chains.list_playbooks())
        ai.set_permission_levels({"chain_diagrams_add":"ask"})
        self.answer="denied"
        self.refused("chain_create",name="x",graph=self.simple())
        self.assertEqual(["chain_create"],[a[0] for a in self.asked])
        self.assertEqual([],chains.list_playbooks())
    def test_chain_update_resets_the_review_and_can_rename(self):
        pid=flows.create("Mine",self.simple("echo mine"))["playbook_id"]
        self.assertTrue(flows.get(pid)["ai_reviewed"])
        out=self.ok("chain_update",chain_id=pid,graph=self.simple("echo changed-by-ai"),name="Renamed by AI")
        self.assertTrue(out["ok"])
        got=flows.get(pid)
        self.assertEqual((True,False,"Renamed by AI"),(got["ai_made"],got["ai_reviewed"],got["name"]))
        self.assertIn("changed-by-ai",str(got["graph"]))
        self.assertIn("not valid",self.refused("chain_update",chain_id=pid,graph={"schema":1,"nodes":[],"edges":[]}))
        self.assertIn("changed-by-ai",str(flows.get(pid)["graph"]))
        self.refused("chain_update",chain_id=9999,graph=self.simple())
    def test_chain_get_and_templates(self):
        pid=flows.create("Mine",self.simple())["playbook_id"]
        got=self.ok("chain_get",chain_id=pid)
        self.assertEqual(pid,got["playbook_id"]);self.assertIn("nodes",got["graph"])
        templates=self.ok("chain_templates")
        self.assertIn("host-alive-portscan-web",[t["id"] for t in templates["templates"]])
        self.assertIn("command",templates["node_types"]);self.assertIn("graph_schema",templates)
        ai.set_permission_levels({"chain_diagrams_read":"deny"})
        self.assertIn("Deny",self.refused("chain_get",chain_id=pid))
        self.assertIn("Deny",self.refused("chain_templates"))
class RunGateTest(Base):
    def ai_chain(self,*lines):
        return self.ok("chain_create",name="AI chain",graph=self.simple(*lines))["playbook_id"]
    def test_run_is_denied_out_of_the_box(self):
        pid=self.ai_chain()
        message=self.refused("chain_run",chain_id=pid)
        self.assertIn("Deny",message)
        self.assertEqual([],self.asked)
        self.assertEqual([],terminal.list_jobs());self.assertEqual([],flows.runs())
        self.assertFalse(flows.get(pid)["ai_reviewed"])
        self.assertTrue(any("chain_run - denied by AI Roles" in d for d in self.audit()))
    def test_first_run_of_an_ai_chain_asks_even_at_level_allow(self):
        ai.set_permission_levels({"chain_diagrams_run":"allow"})
        pid=self.ai_chain()
        out=self.ok("chain_run",chain_id=pid,reason="checking the host")
        self.assertEqual(["chain_run"],[a[0] for a in self.asked])
        self.assertIn("first_run_of_unreviewed_chain",self.asked[0][1])
        status=self.finish(out["run_id"])
        self.assertEqual(("done","ai"),(status["state"],status["source"]))
        self.assertEqual({"flow-ai"},{j["source"] for j in terminal.list_jobs()})
        self.assertTrue(flows.get(pid)["ai_reviewed"])
        self.ok("chain_run",chain_id=pid)
        self.assertEqual(1,len(self.asked),"a reviewed, harmless chain runs without asking at level allow")
    def test_first_run_asks_even_with_a_session_grant(self):
        ai.set_permission_levels({"chain_diagrams_run":"ask"})
        ai.grant_session("chain_diagrams_run")
        self.assertEqual("allow",ai.tool_decision("chain_run"))
        pid=self.ai_chain()
        out=self.ok("chain_run",chain_id=pid)
        self.assertEqual(1,len(self.asked))
        self.finish(out["run_id"])
        self.ok("chain_run",chain_id=pid)
        self.assertEqual(1,len(self.asked))
    def test_a_declined_first_run_executes_nothing_and_stays_unreviewed(self):
        ai.set_permission_levels({"chain_diagrams_run":"allow"})
        pid=self.ai_chain()
        self.answer="denied"
        message=self.refused("chain_run",chain_id=pid)
        self.assertIn("did not approve",message)
        self.assertEqual([],terminal.list_jobs());self.assertEqual([],flows.runs())
        self.assertFalse(flows.get(pid)["ai_reviewed"])
        self.answer="expired"
        self.refused("chain_run",chain_id=pid)
        self.assertEqual([],flows.runs())
    def test_an_edit_by_the_ai_brings_the_approval_back(self):
        ai.set_permission_levels({"chain_diagrams_run":"allow"})
        pid=self.ai_chain()
        self.finish(self.ok("chain_run",chain_id=pid)["run_id"])
        self.ok("chain_update",chain_id=pid,graph=self.simple("echo edited"))
        self.finish(self.ok("chain_run",chain_id=pid)["run_id"])
        self.assertEqual(2,len(self.asked))
    def test_an_edit_made_while_the_approval_is_pending_cancels_the_run(self):
        ai.set_permission_levels({"chain_diagrams_run":"allow"})
        pid=self.ai_chain("echo harmless")
        def swap_then_approve(tool_name,summary="",timeout=None,reason=None,labels=None):
            self.asked.append((tool_name,summary))
            flows.ai_update(pid,self.simple("echo swapped-in-after-the-prompt"),client="Claude")
            return "approved"
        ai.request_approval=swap_then_approve
        message=self.refused("chain_run",chain_id=pid)
        self.assertIn("changed",message)
        self.assertIn("echo harmless",self.asked[0][1])
        self.assertEqual([],terminal.list_jobs());self.assertEqual([],flows.runs())
        self.assertFalse(flows.get(pid)["ai_reviewed"])
    def test_a_chain_with_a_sub_chain_always_asks_and_an_unreviewed_sub_chain_blocks(self):
        ai.set_permission_levels({"chain_diagrams_run":"allow"})
        child=flows.create("Child",self.simple("echo child"))["playbook_id"]
        parent=flows.create("Parent",graph([node("s","subchain",playbook_id=child)],["start.out>s"]))["playbook_id"]
        self.finish(self.ok("chain_run",chain_id=parent)["run_id"])
        self.assertEqual(1,len(self.asked));self.assertIn("Child",self.asked[0][1])
        self.ok("chain_update",chain_id=child,graph=self.simple("echo changed-child"))
        message=self.refused("chain_run",chain_id=parent)
        self.assertIn("not been reviewed",message)
        self.assertEqual(1,len(self.asked))
        with self.assertRaises(ValueError):flows.run(parent,{"confirmed":True})
        self.assertIn("Child",flows.plan(parent)["blocked"])
        self.assertEqual(1,len(flows.runs()))
    def test_a_raw_value_in_an_ai_chain_is_refused_before_anyone_is_asked(self):
        ai.set_permission_levels({"chain_diagrams_run":"allow"})
        raw=graph([node("v","set",assign=[{"var":"flags","value":"-n"}]),cmd("a","echo ${raw:flags} hi")],["start.out>v","v.out>a"])
        pid=self.ok("chain_create",name="AI raw",graph=raw)["playbook_id"]
        self.assertIn("${raw:",self.refused("chain_run",chain_id=pid))
        store.set_reviewed(pid,True)   # reviewed through a first run, still AI-made
        self.assertIn("${raw:",self.refused("chain_run",chain_id=pid))
        self.assertEqual([],self.asked);self.assertEqual([],flows.runs())
        flows.mark_reviewed(pid)       # the operator's explicit review makes it a normal chain
        self.assertEqual("done",self.finish(self.ok("chain_run",chain_id=pid)["run_id"])["state"])
        self.assertEqual([],self.asked)
    def test_chain_run_is_refused_under_the_sandboxed_policy_without_a_sandbox(self):
        ai.set_permission_levels({"chain_diagrams_run":"allow"})
        scripted=graph([node("s","script",language="python",code="print('hi')\n",branches=["out"])],["start.out>s"],script_isolation="allow")
        pid=self.ok("chain_create",name="AI script",graph=scripted)["playbook_id"]
        real=engine.sandbox_info
        engine.sandbox_info=lambda:{"sandbox":"none","network_isolation":False}
        try:
            flows.policy_set({"script_isolation":"sandboxed"})
            self.assertIn("Sandboxed",self.refused("chain_run",chain_id=pid))
            self.assertEqual([],self.asked);self.assertEqual([],flows.runs())
            self.assertEqual("done",self.ok("chain_dry_run",chain_id=pid)["state"])
        finally:
            engine.sandbox_info=real
    def test_an_unsandboxed_ai_script_chain_runs_only_through_the_approval_each_time(self):
        ai.set_permission_levels({"chain_diagrams_run":"allow"})
        scripted=graph([node("s","script",language="python",code="print('hi')\n",branches=["out"])],["start.out>s"])
        pid=self.ok("chain_create",name="AI script",graph=scripted)["playbook_id"]
        real=flows._sandbox_info
        flows._sandbox_info=lambda:{"sandbox":"none","network_isolation":False}
        try:
            for _ in range(2):self.assertEqual("done",self.finish(self.ok("chain_run",chain_id=pid)["run_id"])["state"])
            self.assertEqual(2,len(self.asked))
            self.answer="denied"
            self.refused("chain_run",chain_id=pid)
        finally:
            flows._sandbox_info=real
        self.assertEqual(2,len(flows.runs()))
    def test_the_ai_cannot_build_a_sub_chain_loop(self):
        a=self.ok("chain_create",name="A",graph=self.simple())["playbook_id"]
        b=self.ok("chain_create",name="B",graph=graph([node("s","subchain",playbook_id=a)],["start.out>s"]))["playbook_id"]
        message=self.refused("chain_update",chain_id=a,graph=graph([node("s","subchain",playbook_id=b)],["start.out>s"]))
        self.assertIn("run itself",message)
        self.assertNotIn("subchain",str(flows.get(a)["graph"]))
    def test_chain_run_is_refused_while_the_terminal_extension_is_off(self):
        ai.set_permission_levels({"chain_diagrams_run":"allow"})
        pid=self.ai_chain()
        terminal.set_enabled(False)
        self.assertIn("Enable the terminal in Settings first",self.refused("chain_run",chain_id=pid))
        self.assertEqual([],self.asked);self.assertEqual([],terminal.list_jobs())
        self.assertFalse(flows.get(pid)["ai_reviewed"])
        self.assertEqual("done",self.ok("chain_dry_run",chain_id=pid)["state"])
        terminal.set_enabled(True)
        self.finish(self.ok("chain_run",chain_id=pid)["run_id"])
    def test_scripts_and_destructive_commands_always_ask(self):
        ai.set_permission_levels({"chain_diagrams_run":"allow"})
        scripted=graph([node("s","script",language="python",code="print('hi')\n",branches=["out"])],["start.out>s"])
        pid=flows.create("Operator script chain",scripted)["playbook_id"]
        self.assertTrue(flows.get(pid)["ai_reviewed"])
        for _ in range(2):self.finish(self.ok("chain_run",chain_id=pid)["run_id"])
        self.assertEqual(2,len(self.asked))
        risky=flows.create("Risky",self.simple("echo sudo make me a sandwich"))["playbook_id"]
        self.finish(self.ok("chain_run",chain_id=risky)["run_id"])
        self.assertEqual(3,len(self.asked))
        self.assertIn("destructive",self.asked[2][1])
    def test_a_chain_that_cannot_run_is_refused_before_anyone_is_asked(self):
        ai.set_permission_levels({"chain_diagrams_run":"allow"})
        pid=self.ai_chain("echo {IPv4}")
        message=self.refused("chain_run",chain_id=pid)
        self.assertIn("{IPv4}",message)
        self.assertEqual([],self.asked)
        self.refused("chain_run",chain_id=4242)
        set_live_target({"IPv4":"127.0.0.1"})
        self.finish(self.ok("chain_run",chain_id=pid)["run_id"])
        self.assertIn("echo 127.0.0.1",self.asked[0][1])
    def test_everything_is_refused_while_locked(self):
        ai.set_permission_levels({"chain_diagrams_run":"allow"})
        pid=self.ai_chain()
        common_db.set_locked(True)
        for name,args in (("chain_run",{"chain_id":pid}),("chain_get",{"chain_id":pid}),("chain_templates",{}),("chain_create",{"name":"x","graph":self.simple()}),("chain_update",{"chain_id":pid,"graph":self.simple()}),("chain_dry_run",{"chain_id":pid}),("chain_run_status",{"run_id":"r"}),("chain_run_stop",{"run_id":"r"}),("chains_run",{"chain_id":pid})):
            self.assertIn("locked",self.refused(name,**args),name)
        common_db.set_locked(False)
        self.assertEqual([],self.asked);self.assertEqual([],flows.runs())
    def test_ai_calls_are_audited(self):
        ai.set_permission_levels({"chain_diagrams_run":"allow"})
        pid=self.ai_chain()
        run_id=self.ok("chain_run",chain_id=pid)["run_id"]
        self.finish(run_id)
        self.assertTrue(any("chain_run - approved once" in d for d in self.audit()))
        self.assertTrue(any("flow-ai run "+run_id in d for d in self.audit("chain_run_start")))
        self.assertTrue(any("approved its first AI run" in d for d in self.audit("chain_diagram_edit")))
        self.assertTrue(any(d.startswith("flow-ai:chain:") for d in self.audit("terminal_command")))
class RunToolsTest(Base):
    def test_dry_run_executes_nothing_and_needs_only_read(self):
        set_live_target({"IPv4":"10.0.0.9"})
        pid=flows.create("Dry",self.simple("echo {IPv4}"))["playbook_id"]
        out=self.ok("chain_dry_run",chain_id=pid)
        self.assertEqual(("dry","done"),(out["mode"],out["state"]))
        self.assertEqual(["echo 10.0.0.9"],out["nodes"]["a"]["resolved"])
        self.assertEqual("planned",out["nodes"]["a"]["state"])
        self.assertEqual([],terminal.list_jobs());self.assertEqual([],self.asked)
    def test_status_redacts_secrets_and_stop_ends_a_run(self):
        ai.set_permission_levels({"chain_diagrams_run":"allow"})
        pid=flows.create("Leaky",graph([cmd("a","echo password=Sup3rSecret99"),cmd("b",slow(30))],["start.out>a","a.success>b"]))["playbook_id"]
        run_id=self.ok("chain_run",chain_id=pid)["run_id"]
        self.assertTrue(wait_until(lambda:bool(flows.run_status(run_id)["nodes"]["b"]["job_keys"])))
        status=self.ok("chain_run_status",run_id=run_id)
        self.assertEqual("running",status["state"])
        self.assertNotIn("Sup3rSecret99",str(status))
        self.assertIn("[redacted]",status["nodes"]["a"]["stdout"])
        self.assertTrue(self.ok("chain_run_stop",run_id=run_id))
        self.assertEqual("cancelled",self.finish(run_id)["state"])
        self.assertIn("No such run",self.refused("chain_run_status",run_id="nope"))
        ai.set_permission_levels({"chain_diagrams_run":"deny"})
        self.assertIn("Deny",self.refused("chain_run_stop",run_id=run_id))
    def test_chains_list_reports_diagrams(self):
        linear=chains.create_playbook("Linear")
        drawn=flows.create("Drawn",self.simple())["playbook_id"]
        rows={r["id"]:r for r in self.ok("chains_list")}
        self.assertEqual((False,False),(rows[linear]["has_diagram"],rows[linear]["ai_made"]))
        self.assertEqual((True,False),(rows[drawn]["has_diagram"],rows[drawn]["ai_made"]))
        self.assertIn("steps",rows[linear])
    def test_chains_run_on_a_diagram_goes_through_the_diagram_gate(self):
        pid=self.ok("chain_create",name="AI chain",graph=self.simple())["playbook_id"]
        ai.set_permission_levels({"chains_run":"allow"})
        self.assertIn("Chain Diagrams > Run",self.refused("chains_run",chain_id=pid))
        self.assertEqual([],flows.runs())
        ai.set_permission_levels({"chain_diagrams_run":"allow"})
        out=self.ok("chains_run",chain_id=pid)
        self.assertIn("run_id",out)
        self.assertEqual(["chain_run"],[a[0] for a in self.asked])
        self.assertEqual("done",self.finish(out["run_id"])["state"])
        self.assertTrue(flows.get(pid)["ai_reviewed"])
        ai.set_permission_levels({"chains_run":"deny"})
        self.assertIn("Action Chains > Run",self.refused("chains_run",chain_id=pid))
    def test_chains_run_on_a_linear_chain_keeps_the_old_path(self):
        import sqlite3
        ai.set_permission_levels({"chains_run":"allow"})
        pid=chains.create_playbook("Linear")
        con=sqlite3.connect(common_db.db_path())
        try:
            common_db.ensure_schema(con)
            cid=con.execute("INSERT INTO CommandsNotes(note_name,category,sub_category,command,tags) VALUES('t','c','s','echo linear-step','')").lastrowid
            con.commit()
        finally:
            con.close()
        chains.add_step(pid,cid,"CommandsNotes")
        out=self.ok("chains_run",chain_id=pid)
        self.assertIn("chain_id",out);self.assertNotIn("run_id",out)
        self.assertTrue(wait_until(lambda:not terminal.chain_status(out["chain_id"])["active"]))
        self.assertEqual(["ai"],[s["source"] for s in terminal.chain_status(out["chain_id"])["steps"]])
        self.assertEqual([],flows.runs())
if __name__=="__main__":unittest.main()
