"""Chain Run History MCP tools (Cores/Bridge/mcp_chain_history_tools.py): each is registered under exactly one AI Roles key,
gated (Read allow, import Ask, Delete Deny), refuses while locked, redacts secrets and marks AI imports as AI-made."""
import json,os,sys,threading,time,unittest
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from _isolate import IsolatedData
from Cores import common_db
from Cores.Services import ai_service as ai
from Cores.Services import ai_chat_service as chat
from Cores.Services import chain_history as hist
from Cores.Services import flow_service as flows
from Cores.Services import flow_store as store
from Cores.Bridge import mcp_chain_history_tools as tools
from test_chain_history import GRAPH,status,add_log
def call(_tool,**args):
    ok,res=chat._call_tool(_tool,args)
    if not ok:raise AssertionError(f"{_tool} failed: {res}")
    return res
def fails(_tool,**args):
    ok,res=chat._call_tool(_tool,args)
    return None if ok else str(res)
def approve_next(decision="once"):
    def run():
        end=time.time()+10
        while time.time()<end:
            rows=ai.pending_approvals()
            if rows:ai.resolve_approval(rows[0]["id"],decision);return
            time.sleep(0.02)
    t=threading.Thread(target=run,daemon=True);t.start()
    return t
class Base(unittest.TestCase):
    def setUp(self):
        self.iso=IsolatedData();self.iso.start()
        ai.revoke_session_grant()
        self.a=flows.create("Recon",GRAPH,"recon")["playbook_id"]
        run=status("runA1",self.a)
        run["nodes"]["n2"]["output"]["stdout"]="login password=Hunter2xyzSecret ok"
        store.save_run(run);add_log("runA1")
        store.save_run(status("runA2",self.a,state="failed",started="2026-11-21T09:00:00+00:00",ended="2026-11-21T09:01:00+00:00"))
    def tearDown(self):
        common_db.set_locked(False)
        ai.revoke_session_grant()
        self.iso.stop()
class RegistryTest(Base):
    def test_every_tool_is_registered_once_and_exists(self):
        server_tools={t.name for t in chat._list_tools()}
        for n in tools.all_tool_names():
            self.assertIn(n,server_tools,n)
            self.assertEqual(1,sum(n in t for t in ai.PERMISSION_TOOL_MAP.values()),n)
        with open(__file__,encoding="utf-8") as handle:src=handle.read().split("class ToolsTest",1)[1]
        for n in tools.all_tool_names():self.assertIn('"'+n+'"',src,f"{n} is not exercised in this file")
    def test_defaults(self):
        lv=ai.get_permission_levels()
        self.assertEqual(("allow","ask","deny"),(lv["chain_history_read"],lv["chain_history_add"],lv["chain_history_delete"]))
class ToolsTest(Base):
    def test_list_get_and_log_redact_secrets(self):
        page=call("chain_runs_list",chain_id=self.a,state="done")
        self.assertEqual(["runA1"],[r["run_id"] for r in page["items"]])
        self.assertEqual(2,call("chain_runs_list")["total"])
        detail=call("chain_run_get",run_id="runA1")
        out=json.dumps(detail)
        self.assertNotIn("Hunter2xyzSecret",out);self.assertIn("Ping it",out)
        log=call("chain_run_log",run_id="runA1",level="error")
        self.assertEqual(["Exit code 1"],[e["text"] for e in log["entries"]])
        self.assertEqual(["slow answer"],[e["text"] for e in call("chain_run_log",run_id="runA1",query="SLOW")["entries"]])
    def test_export_is_a_redacted_bundle(self):
        out=call("chain_history_export",chain_ids=[self.a],runs_of_chain=self.a)
        self.assertEqual((1,2),(out["chains"],out["runs"]))
        self.assertEqual(("loya-chain-bundle",1),(out["bundle"]["format"],out["bundle"]["version"]))
        self.assertNotIn("Hunter2xyzSecret",json.dumps(out))
        self.assertIn("Say what",fails("chain_history_export") or "")
    def test_import_asks_and_marks_chains_ai_made(self):
        bundle=hist.export_bundle([self.a],None,include_chains=True,include_runs=True,runs_of_chain=self.a)
        t=approve_next()
        out=call("chain_history_import",bundle=bundle)
        t.join()
        created=out["chains"]["created"][0]
        self.assertEqual("Recon (imported)",created["name"])
        self.assertEqual(0,out["runs"]["imported"]);self.assertEqual(2,out["runs"]["skipped"])
        got=flows.get(created["playbook_id"])
        self.assertTrue(got["ai_made"]);self.assertFalse(got["ai_reviewed"])
        t=approve_next("deny")
        self.assertIn("did not approve",fails("chain_history_import",bundle=bundle) or "")
        t.join()
        self.assertIn("not a LOYA chain bundle",fails("chain_history_import",bundle={"x":1}) or "")
    def test_delete_is_denied_by_default_and_works_when_allowed(self):
        self.assertIn("Deny",fails("chain_runs_delete",run_ids=["runA1"]) or "")
        ai.set_permission_levels({"chain_history_delete":"allow"})
        self.assertEqual(1,call("chain_runs_delete",run_ids=["runA1"])["deleted"])
        t=approve_next()
        self.assertEqual(1,call("chain_runs_delete",chain_id=self.a)["deleted"])   # a whole chain always asks
        t.join()
        self.assertEqual(0,call("chain_runs_list")["total"])
        self.assertIn("Say what",fails("chain_runs_delete") or "")
        store.save_run(status("runZ",self.a))
        t=approve_next()
        self.assertEqual(1,call("chain_runs_delete",all_runs=True)["deleted"])
        t.join()
    def test_locked_refuses_every_tool(self):
        common_db.set_locked(True)
        for name,args in (("chain_runs_list",{}),("chain_run_get",{"run_id":"runA1"}),("chain_run_log",{"run_id":"runA1"}),("chain_history_export",{"all_chains":True}),("chain_runs_delete",{"all_runs":True}),("chain_history_import",{"bundle":{"format":"loya-chain-bundle","version":1}})):
            self.assertIn("locked",(fails(name,**args) or "").lower(),name)
if __name__=="__main__":
    unittest.main()
