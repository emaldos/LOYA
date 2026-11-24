"""Chain Diagrams facade and bridge: derived linear diagrams, saving, planning, the run gates, history, prefs, the lock."""
import json,os,sys,sqlite3,time,unittest
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from _isolate import IsolatedData
from _flow_helpers import WINDOWS,slow,node,cmd,graph,set_live_target,wait_until
from Cores import common_db
from Cores.Services import flow_engine as engine
from Cores.Services import flow_schema as schema
from Cores.Services import flow_service as flows
from Cores.Services import flow_store as store
from Cores.Services import playbooks_service as chains
from Cores.Services import terminal_service as terminal
from Cores.Services import security_service as security
def add_command(text,title="cmd"):
    con=sqlite3.connect(common_db.db_path())
    try:
        common_db.ensure_schema(con)
        cur=con.execute("INSERT INTO CommandsNotes(note_name,category,sub_category,command,tags) VALUES(?,?,?,?,?)",(title,"cat","sub",text,""))
        con.commit()
        return int(cur.lastrowid)
    finally:
        con.close()
def linear_chain(name,*commands):
    pid=chains.create_playbook(name)
    for index,text in enumerate(commands):chains.add_step(pid,add_command(text,"step %d"%(index+1)),"CommandsNotes")
    return pid
class Base(unittest.TestCase):
    def setUp(self):
        self.iso=IsolatedData();self.iso.start()
        terminal.set_enabled(True)   # real runs need the terminal extension, like the linear chains
    def tearDown(self):
        common_db.set_locked(False)
        flows.stop_all("test teardown")
        for run in list(engine._runs.values()):run.finished.wait(10)
        engine._runs.clear();del engine._unsaved[:]
        terminal.clear_batch_output()
        self.iso.stop()
    def audit(self,event):
        return [e for e in security.list_audit_events(500) if e["event"]==event]
    def finish(self,started,timeout=40):
        status=flows.wait(started["run_id"],timeout)
        self.assertIn(status["state"],engine.FINAL_STATES,"the run did not finish")
        return status
    def diagram(self,name,g):
        return flows.create(name,g)["playbook_id"]
class LinearChainTests(Base):
    def test_a_linear_chain_is_listed_and_shown_as_a_derived_diagram(self):
        pid=linear_chain("Recon","echo one","echo two {IPv4}")
        rows=flows.list_flows()
        self.assertEqual([{"playbook_id":pid,"name":"Recon","caller":"recon","step_count":2,"has_graph":False,"node_count":3,"ai_made":False,"ai_reviewed":True,"origin":""}],[{k:v for k,v in r.items() if k!="updated_at"} for r in rows])
        got=flows.get(pid)
        self.assertTrue(got["derived"])
        self.assertEqual(("Recon","recon",False,True,[]),(got["name"],got["caller"],got["ai_made"],got["ai_reviewed"],got["errors"]))
        self.assertTrue(schema.graph_is_linear(got["graph"]))
        self.assertEqual(["echo one","echo two {IPv4}"],[c["text"] for c in schema.graph_commands(got["graph"])])
        self.assertEqual(["start","command","command"],[n["type"] for n in got["graph"]["nodes"]])
    def test_looking_at_a_linear_chain_changes_nothing(self):
        pid=linear_chain("Recon","echo one","echo two")
        before=chains.get_playbook(pid)
        flows.get(pid);flows.plan(pid);flows.list_flows();flows.export_json(pid)
        self.assertEqual(before,chains.get_playbook(pid))
        self.assertFalse(store.has_graph(pid))
        self.assertEqual(["echo one","echo two"],[s["command"] for s in chains.playbook_commands(pid)])
    def test_the_old_linear_runner_still_works_next_to_a_diagram(self):
        pid=linear_chain("Recon","echo one","echo two")
        other=self.diagram("Diagram",graph([cmd("a","echo d")],["start.out>a"]))
        started=terminal.start_chain("",[{"command":s["command"],"label":s["label"]} for s in chains.playbook_commands(pid)],"stop","playbook","Recon")
        self.assertTrue(wait_until(lambda:not terminal.chain_status(started["chain_id"])["active"]))
        self.assertEqual(["done","done"],[s["state"] for s in terminal.chain_status(started["chain_id"])["steps"]])
        self.assertEqual([],store.list_runs(pid))
        self.assertTrue(store.has_graph(other))
    def test_saving_a_diagram_converts_and_reverting_restores_the_linear_chain(self):
        pid=linear_chain("Recon","echo one","echo two")
        steps=chains.get_playbook(pid)["steps"]
        derived=flows.get(pid)["graph"]
        out=flows.save(pid,derived)
        self.assertTrue(out["ok"])
        got=flows.get(pid)
        self.assertFalse(got["derived"])
        self.assertTrue(flows.list_flows()[0]["has_graph"])
        self.assertEqual(steps,chains.get_playbook(pid)["steps"])
        self.assertTrue(flows.revert_linear(pid))
        self.assertFalse(flows.revert_linear(pid))
        self.assertTrue(flows.get(pid)["derived"])
        self.assertEqual(steps,chains.get_playbook(pid)["steps"])
        self.assertEqual(1,len(self.audit("chain_diagram_edit")))
        self.assertEqual(1,len(self.audit("chain_diagram_delete")))
    def test_a_derived_diagram_can_be_dry_run_and_run(self):
        pid=linear_chain("Recon","echo one","echo two")
        status=self.finish(flows.run(pid,{"mode":"dry"}))
        self.assertEqual("done",status["state"])
        self.assertEqual([],terminal.list_jobs())
        status=self.finish(flows.run(pid,{"confirmed":True}))
        self.assertEqual("done",status["state"])
        self.assertEqual(["echo two","echo one"],[j["command"] for j in terminal.list_jobs()])
        self.assertFalse(store.has_graph(pid))
    def test_unknown_chain(self):
        for call in (lambda:flows.get(999),lambda:flows.save(999,schema.new_graph()),lambda:flows.plan(999),lambda:flows.run(999,{"mode":"dry"}),lambda:flows.get("abc")):
            with self.assertRaises(ValueError):call()
class CatalogTests(Base):
    def test_catalog_shape(self):
        cat=flows.catalog()
        for key in ("schema","node_types","limits","templates","script_templates","languages","ops","sources","parsers"):self.assertIn(key,cat)
        self.assertEqual(2,cat["schema"])
        for key in ("categories","types","presets","hotbar"):self.assertIn(key,cat)   # the node catalog (flow_nodes)
        self.assertEqual({"id","name","description"},set(cat["templates"][0]))
        self.assertIn("command",cat["node_types"]);self.assertIn("python",cat["languages"])
        json.dumps(cat)
    def test_templates_are_valid_and_can_seed_a_chain(self):
        for entry in flows.catalog()["templates"]:
            g=flows.template(entry["id"])
            self.assertTrue(flows.validate(g)["ok"],entry["id"])
        pid=flows.create("From template",template_id="script-demo")["playbook_id"]
        self.assertFalse(flows.get(pid)["derived"])
        with self.assertRaises(ValueError):flows.template("nope")
        with self.assertRaises(ValueError):flows.create("x",template_id="nope")
class SaveTests(Base):
    def test_create_makes_a_chain_with_a_diagram(self):
        out=flows.create("New diagram")
        got=flows.get(out["playbook_id"])
        self.assertEqual((False,False,True,"new-diagram"),(got["derived"],got["ai_made"],got["ai_reviewed"],got["caller"]))
        self.assertEqual(["start"],[n["type"] for n in got["graph"]["nodes"]])
        self.assertEqual(1,len(self.audit("chain_diagram_create")))
        with self.assertRaises(ValueError):flows.create("")
        self.assertEqual(1,len(chains.list_playbooks()))
    def test_a_draft_with_errors_is_saved_but_cannot_run(self):
        pid=self.diagram("Draft",schema.new_graph())
        draft={"schema":1,"settings":{},"nodes":[node("start","start"),node("c","command",commands=[])],"edges":[{"id":"e1","from":"start","port":"out","to":"c"}]}
        out=flows.save(pid,draft)
        self.assertFalse(out["ok"]);self.assertTrue(out["errors"])
        self.assertEqual(2,len(flows.get(pid)["graph"]["nodes"]))
        self.assertTrue(flows.plan(pid)["blocked"])
        with self.assertRaises(ValueError):flows.run(pid,{"confirmed":True})
        with self.assertRaises(ValueError):flows.run(pid,{"mode":"dry"})
    def test_something_that_is_not_a_diagram_is_refused_and_the_old_one_kept(self):
        pid=self.diagram("Keep",graph([cmd("a","echo keep")],["start.out>a"]))
        for bad in (None,"{not json",{"edges":[]},[1,2],42):
            with self.assertRaises(ValueError):flows.save(pid,bad)
        self.assertEqual(["echo keep"],[c["text"] for c in schema.graph_commands(flows.get(pid)["graph"])])
    def test_a_sub_chain_loop_is_an_error_at_any_length(self):
        def calls(target):
            return graph([node("s","subchain",playbook_id=target)],["start.out>s"])
        a=self.diagram("A",schema.new_graph());b=self.diagram("B",schema.new_graph());c=self.diagram("C",schema.new_graph())
        self.assertTrue(flows.save(a,calls(b))["ok"])
        self.assertTrue(flows.save(b,calls(c))["ok"])
        out=flows.save(c,calls(a))
        self.assertFalse(out["ok"])
        issue=next(i for i in out["errors"] if i["code"]=="subchain_cycle")
        self.assertEqual("s",issue["node"]);self.assertIn("C > A > B > C",issue["message"])
        self.assertIn("subchain_cycle",[i["code"] for i in flows.get(c)["errors"]])
        self.assertIn("subchain_cycle",[i["code"] for i in flows.get(a)["errors"]])
        self.assertTrue(flows.plan(a)["blocked"])
        with self.assertRaises(ValueError):flows.run(a,{"confirmed":True})
        with self.assertRaises(ValueError):flows.run(c,{"mode":"dry"})
        self.assertFalse(flows.validate(calls(a),c)["ok"])
        self.assertTrue(flows.validate(calls(a))["ok"])
        self.assertIn("subchain_cycle",[i["code"] for i in flows.validate(calls(b),b)["errors"]])
        with self.assertRaises(ValueError) as caught:flows.save(c,calls(a),ai_client="Claude")
        self.assertIn("run itself",str(caught.exception))
        self.assertTrue(flows.save(c,schema.new_graph())["ok"])
        self.assertEqual([],flows.get(a)["errors"])
    def test_import_clears_sub_chain_targets(self):
        child=self.diagram("Child",graph([cmd("c","echo child")],["start.out>c"]))
        parent=self.diagram("Parent",graph([node("s","subchain",playbook_id=child),cmd("a","echo after")],["start.out>s","s.success>a"]))
        out=flows.import_json(flows.export_json(parent))
        self.assertIn("subchain_cleared",[w["code"] for w in out["warnings"]])
        self.assertEqual("s",next(w for w in out["warnings"] if w["code"]=="subchain_cleared")["node"])
        copy=flows.get(out["playbook_id"])
        self.assertIsNone(next(n for n in copy["graph"]["nodes"] if n["type"]=="subchain")["config"]["playbook_id"])
        self.assertTrue(flows.plan(out["playbook_id"])["blocked"])
        self.assertEqual(child,next(n for n in flows.get(parent)["graph"]["nodes"] if n["type"]=="subchain")["config"]["playbook_id"])
    def test_export_and_import_round_trip(self):
        pid=self.diagram("Original",graph([cmd("a","echo {IPv4}")],["start.out>a"]))
        text=flows.export_json(pid)
        self.assertEqual(1,json.loads(text)["loya_chain"])
        out=flows.import_json(text)
        self.assertNotEqual(pid,out["playbook_id"])
        copy=flows.get(out["playbook_id"])
        self.assertEqual("Original",copy["name"])
        self.assertNotEqual(flows.get(pid)["caller"],copy["caller"])
        self.assertEqual(flows.get(pid)["graph"]["nodes"],copy["graph"]["nodes"])
        self.assertFalse(copy["ai_reviewed"])
        self.assertTrue(flows.plan(out["playbook_id"])["needs_review"])
        self.assertEqual("Renamed",flows.get(flows.import_json(text,"Renamed")["playbook_id"])["name"])
        with self.assertRaises(ValueError):flows.import_json("not a chain")
    def test_deleting_the_chain_drops_its_diagram(self):
        from Cores.Bridge import api
        pid=self.diagram("Gone",graph([cmd("a","echo x")],["start.out>a"]))
        self.assertTrue(api.PlaybooksAPI().delete(pid))
        self.assertIsNone(store.get_graph_row(pid))
        self.assertEqual([],flows.list_flows())
        self.assertTrue(any("deleted" in e["detail"] for e in self.audit("chain_diagram_delete")))
        self.assertTrue(api.PlaybooksAPI().delete(linear_chain("Linear","echo x")))
    def test_mark_reviewed(self):
        pid=flows.create("AI made",graph([cmd("a","echo x")],["start.out>a"]),ai_client="Claude")["playbook_id"]
        self.assertEqual((True,False,"Claude"),tuple(flows.get(pid)[k] for k in ("ai_made","ai_reviewed","ai_client")))
        self.assertTrue(flows.mark_reviewed(pid))
        self.assertEqual((False,True),(flows.get(pid)["ai_made"],flows.get(pid)["ai_reviewed"]))
        row=flows.list_flows()[0]
        self.assertEqual((False,True),(row["ai_made"],row["ai_reviewed"]))
        self.assertTrue(any("chain %d"%pid in e["detail"] for e in self.audit("chain_diagram_reviewed")))
        self.assertFalse(flows.mark_reviewed(linear_chain("Linear","echo x")))
    def test_confirming_the_first_run_keeps_the_ai_made_flag_and_an_ai_edit_sets_both_again(self):
        pid=flows.create("AI made",graph([cmd("a","echo x")],["start.out>a"]),ai_client="Claude")["playbook_id"]
        self.finish(flows.run(pid,{"confirmed":True,"review_ack":True}))
        self.assertEqual((True,True),(flows.get(pid)["ai_made"],flows.get(pid)["ai_reviewed"]))
        flows.mark_reviewed(pid)
        self.assertEqual((False,True),(flows.get(pid)["ai_made"],flows.get(pid)["ai_reviewed"]))
        self.assertEqual("done",self.finish(flows.run(pid,{"confirmed":True}))["state"])
        flows.ai_update(pid,graph([cmd("a","echo y")],["start.out>a"]),client="Claude")
        self.assertEqual((True,False),(flows.get(pid)["ai_made"],flows.get(pid)["ai_reviewed"]))
        draft=flows.create_ai_draft("Draft",graph([cmd("a","echo z")],["start.out>a"]))["playbook_id"]
        self.assertEqual((True,False),(flows.get(draft)["ai_made"],flows.get(draft)["ai_reviewed"]))
    def test_the_export_file_name_helper(self):
        fix=flows.file_name_with_ext
        self.assertEqual("/tmp/a.json",fix("/tmp/a.json","json"))
        self.assertEqual("/tmp/a.JSON",fix("/tmp/a.JSON","json"))
        self.assertEqual("/tmp/a.loya-chain.json",fix("/tmp/a.loya-chain.json","json"))
        self.assertEqual("/tmp/a.json",fix("/tmp/a.json.json","json"))
        self.assertEqual("/tmp/a.json",fix("/tmp/a.json.JSON.json","json"))
        self.assertEqual("/tmp/a.json",fix("/tmp/a","json"))
        self.assertEqual("/tmp/a.json",fix("/tmp/a.",".json"))
        self.assertEqual("/tmp/a.txt.log",fix("/tmp/a.txt","log"))
        self.assertEqual("/tmp/run.log",fix("/tmp/run.log","log"))
        self.assertEqual("",fix("","json"));self.assertEqual("/tmp/a",fix("/tmp/a",""))
        pid=self.diagram("Web: quick/wins",schema.new_graph())
        self.assertEqual("Web_ quick_wins.loya-chain.json",flows.export_name(pid))
    def test_prefs_round_trip_and_are_clamped(self):
        hotbar=list(flows.PREF_DEFAULTS["hotbar"])   # the pinned node types; test_flow_nodes.py covers pinning
        self.assertEqual({"snap":True,"grid":20,"minimap":True,"inspector_width":340,"hotbar":hotbar},flows.prefs_get())
        out=flows.prefs_set({"snap":False,"grid":4000,"junk":1,"inspector_width":"wide"})
        self.assertEqual({"snap":False,"grid":100,"minimap":True,"inspector_width":340,"hotbar":hotbar},out)
        self.assertEqual(out,flows.prefs_get())
        self.assertEqual(False,flows.prefs_set({"minimap":False})["snap"])
        with open(os.path.join(self.iso.dir,"settings.json"),encoding="utf-8") as handle:
            self.assertEqual({"snap":False,"grid":100,"minimap":False,"inspector_width":340,"hotbar":hotbar},json.load(handle)["extensions"]["flow_editor"])
class PlanTests(Base):
    def test_plan_lists_resolved_commands_missing_values_scripts_and_approvals(self):
        set_live_target({"IPv4":"10.1.2.3"},"dc01")
        g=graph([cmd("a","nmap {IPv4}","rm -rf /tmp/x-{Missing}"),node("s","script",language="python",code="print(1)\nprint(2)\n",branches=["out"]),node("ask","approval",message="go?"),cmd("island","echo {AlsoMissing}")],["start.out>a","a.success>s","s.out>ask"])
        plan=flows.plan(self.diagram("Plan",g))
        self.assertEqual({"name":"dc01","values":{"ipv4":"10.1.2.3"}},plan["target"])
        self.assertEqual([("a","nmap {IPv4}","nmap 10.1.2.3",[],False),("a","rm -rf /tmp/x-{Missing}","rm -rf /tmp/x-{Missing}",["Missing"],True)],[(c["node"],c["text"],c["resolved"],c["missing"],c["destructive"]) for c in plan["commands"]])
        self.assertEqual([{"node":"s","title":"s","language":"python","lines":2,"network":False}],plan["scripts"])
        self.assertEqual((1,False,False),(plan["approvals"],plan["ai_made"],plan["needs_review"]))
        self.assertIn("{Missing}",plan["blocked"]);self.assertNotIn("AlsoMissing",plan["blocked"])
        self.assertNotIn("graph",plan)
    def test_plan_of_an_unsaved_graph_and_from_a_node(self):
        pid=self.diagram("Plan",graph([cmd("a","echo saved")],["start.out>a"]))
        unsaved=graph([cmd("a","echo first"),cmd("b","echo second")],["start.out>a","a.success>b"])
        self.assertEqual(["echo first","echo second"],[c["text"] for c in flows.plan(pid,unsaved)["commands"]])
        self.assertEqual(["echo second"],[c["text"] for c in flows.plan(pid,unsaved,"b")["commands"]])
        self.assertTrue(flows.plan(pid,unsaved,"ghost")["blocked"])
        self.assertEqual("",flows.plan(pid)["blocked"])
class RunGateTests(Base):
    def setUp(self):
        super().setUp()
        self.pid=self.diagram("Gate",graph([cmd("a","echo ran")],["start.out>a"]))
    def test_a_real_run_needs_confirmation(self):
        for opts in (None,{},{"mode":"run"},{"confirmed":False}):
            with self.assertRaises(ValueError):flows.run(self.pid,opts)
        self.assertEqual([],terminal.list_jobs())
        status=self.finish(flows.run(self.pid,{"confirmed":True}))
        self.assertEqual("done",status["state"])
    def test_run_is_refused_while_locked(self):
        common_db.set_locked(True)
        with self.assertRaises(ValueError) as caught:flows.run(self.pid,{"confirmed":True})
        self.assertIn("locked",str(caught.exception))
        with self.assertRaises(ValueError):flows.run(self.pid,{"mode":"dry"})
        common_db.set_locked(False)
        self.assertEqual([],terminal.list_jobs())
        self.assertEqual([],flows.runs())
    def test_unfilled_placeholders_block_a_real_run_but_not_a_dry_run(self):
        pid=self.diagram("Needs target",graph([cmd("a","echo {IPv4}")],["start.out>a"]))
        self.assertEqual(["IPv4"],flows.plan(pid)["commands"][0]["missing"])
        with self.assertRaises(ValueError) as caught:flows.run(pid,{"confirmed":True})
        self.assertIn("{IPv4}",str(caught.exception))
        self.assertEqual("done",self.finish(flows.run(pid,{"mode":"dry"}))["state"])
        set_live_target({"IPv4":"127.0.0.1"})
        status=self.finish(flows.run(pid,{"confirmed":True}))
        self.assertIn("127.0.0.1",status["nodes"]["a"]["output"]["stdout"])
    def test_an_unreviewed_chain_needs_the_review_acknowledgement(self):
        pid=flows.create("AI made",graph([cmd("a","echo ai")],["start.out>a"]),ai_client="Claude")["playbook_id"]
        self.assertTrue(flows.plan(pid)["needs_review"]);self.assertTrue(flows.plan(pid)["ai_made"])
        with self.assertRaises(ValueError) as caught:flows.run(pid,{"confirmed":True})
        self.assertIn("review",str(caught.exception).lower())
        self.assertFalse(flows.get(pid)["ai_reviewed"])
        self.assertEqual("done",self.finish(flows.run(pid,{"mode":"dry"}))["state"])
        self.assertFalse(flows.get(pid)["ai_reviewed"])
        self.assertEqual("done",self.finish(flows.run(pid,{"confirmed":True,"review_ack":True}))["state"])
        self.assertTrue(flows.get(pid)["ai_reviewed"])
        self.assertEqual("done",self.finish(flows.run(pid,{"confirmed":True}))["state"])
    def test_an_unsaved_graph_can_only_be_dry_run(self):
        unsaved=graph([cmd("a","echo unsaved")],["start.out>a"])
        with self.assertRaises(ValueError):flows.run(self.pid,{"confirmed":True,"graph":unsaved})
        status=self.finish(flows.run(self.pid,{"mode":"dry","graph":unsaved}))
        self.assertEqual(["echo unsaved"],status["nodes"]["a"]["output"]["resolved"])
        self.assertEqual(["echo ran"],[c["text"] for c in schema.graph_commands(flows.get(self.pid)["graph"])])
    def test_a_plan_fingerprint_pins_the_run_to_what_was_shown(self):
        shown=flows.plan(self.pid)
        self.assertEqual(shown["fingerprint"],flows.plan(self.pid)["fingerprint"])
        flows.save(self.pid,graph([cmd("a","echo changed-meanwhile")],["start.out>a"]))
        with self.assertRaises(ValueError) as caught:flows.run(self.pid,{"confirmed":True,"fingerprint":shown["fingerprint"]})
        self.assertIn("changed",str(caught.exception))
        self.assertEqual([],terminal.list_jobs())
        self.assertEqual("done",self.finish(flows.run(self.pid,{"confirmed":True,"fingerprint":flows.plan(self.pid)["fingerprint"]}))["state"])
    def test_an_unreviewed_sub_chain_is_never_run(self):
        child=flows.create("AI child",graph([cmd("c","echo ai-child")],["start.out>c"]),ai_client="Claude")["playbook_id"]
        parent=self.diagram("Parent",graph([node("s","subchain",playbook_id=child)],["start.out>s"]))
        plan=flows.plan(parent)
        self.assertEqual([{"node":"s","title":"s","playbook_id":child,"name":"AI child","needs_review":True,"error":""}],plan["subchains"])
        self.assertIn("AI child",plan["blocked"])
        with self.assertRaises(ValueError):flows.run(parent,{"confirmed":True})
        with self.assertRaises(ValueError):flows._subchain_loader(child)
        flows.mark_reviewed(child)
        self.assertEqual("",flows.plan(parent)["blocked"])
        self.assertEqual("done",self.finish(flows.run(parent,{"confirmed":True}))["state"])
        gone=self.diagram("Dangling",graph([node("s","subchain",playbook_id=98765)],["start.out>s"]))
        self.assertIn("no longer exists",flows.plan(gone)["blocked"])
    def test_raw_values_are_refused_in_ai_made_or_unreviewed_chains(self):
        raw=graph([node("v","set",assign=[{"var":"flags","value":"-n"}]),cmd("a","echo ${raw:flags} hi")],["start.out>v","v.out>a"])
        mine=self.diagram("Mine",raw)
        plan=flows.plan(mine)
        self.assertEqual((["flags"],False,""),(plan["raw"],plan["raw_refused"],plan["blocked"]))
        self.assertEqual("done",self.finish(flows.run(mine,{"confirmed":True}))["state"])
        made=flows.create("AI raw",raw,ai_client="Claude")["playbook_id"]
        for reviewed in (False,True):
            if reviewed:store.set_reviewed(made,True)   # what confirming a first run records: reviewed, still AI-made
            plan=flows.plan(made)
            self.assertTrue(plan["raw_refused"]);self.assertIn("${raw:",plan["blocked"])
            with self.assertRaises(ValueError) as caught:flows.run(made,{"confirmed":True,"review_ack":True})
            self.assertIn("${raw:",str(caught.exception))
        flows.mark_reviewed(made)   # the explicit review turns it into a normal chain
        self.assertFalse(flows.plan(made)["raw_refused"])
        self.assertEqual("done",self.finish(flows.run(made,{"confirmed":True}))["state"])
        flows.runs_clear(made)
        imported=flows.import_json(flows.export_json(mine))["playbook_id"]
        self.assertTrue(flows.plan(imported)["raw_refused"])
        flows.mark_reviewed(imported)
        self.assertFalse(flows.plan(imported)["raw_refused"])
        self.assertEqual(1,len(flows.runs()))
    def test_an_ai_made_script_chain_without_a_sandbox_is_confirmed_on_every_run(self):
        scripted=graph([node("s","script",language="python",code="print('hi')\n",branches=["out"])],["start.out>s"])
        made=flows.create("AI script",scripted,ai_client="Claude")["playbook_id"]
        mine=self.diagram("My script",scripted)
        real=flows._sandbox_info
        try:
            flows._sandbox_info=lambda:{"sandbox":"none","network_isolation":False}
            self.assertEqual({"sandbox":"none","network_isolation":False},flows.plan(made)["sandbox"])
            self.assertEqual("done",self.finish(flows.run(made,{"confirmed":True,"review_ack":True}))["state"])
            self.assertTrue(flows.get(made)["ai_reviewed"])
            plan=flows.plan(made)
            self.assertEqual((True,True),(plan["needs_review"],plan["review_each_run"]))
            with self.assertRaises(ValueError) as caught:flows.run(made,{"confirmed":True})
            self.assertIn("every run",str(caught.exception))
            self.assertEqual("done",self.finish(flows.run(made,{"confirmed":True,"review_ack":True}))["state"])
            self.assertFalse(flows.plan(mine)["needs_review"])
            flows._sandbox_info=lambda:{"sandbox":"bwrap","network_isolation":True}
            self.assertEqual((False,False),(flows.plan(made)["needs_review"],flows.plan(made)["review_each_run"]))
            self.assertEqual("done",self.finish(flows.run(made,{"confirmed":True}))["state"])
        finally:
            flows._sandbox_info=real
        self.assertEqual({"sandbox","network_isolation"},set(flows.plan(made)["sandbox"]))
    def test_a_real_run_needs_the_terminal_extension(self):
        terminal.set_enabled(False)
        plan=flows.plan(self.pid)
        self.assertEqual((False,"Enable the terminal in Settings first"),(plan["terminal_enabled"],plan["blocked"]))
        with self.assertRaises(ValueError) as caught:flows.run(self.pid,{"confirmed":True})
        self.assertEqual("Enable the terminal in Settings first",str(caught.exception))
        self.assertEqual([],terminal.list_jobs());self.assertEqual([],flows.runs())
        self.assertEqual("done",self.finish(flows.run(self.pid,{"mode":"dry"}))["state"])
        self.assertEqual([],terminal.list_jobs())
        terminal.set_enabled(True)
        self.assertEqual("",flows.plan(self.pid)["blocked"])
        self.assertEqual("done",self.finish(flows.run(self.pid,{"confirmed":True}))["state"])
    def scripted(self,**settings):
        return graph([node("s","script",language="python",code="print('hi')\n",branches=["out"],network=True),cmd("a","echo after")],["start.out>s","s.out>a"],**settings)
    def test_script_policy_setting_round_trips_and_is_audited(self):
        self.assertEqual({"script_isolation","sandbox"},set(flows.policy_get()))
        self.assertEqual("allow",flows.policy_get()["script_isolation"])
        out=flows.policy_set({"script_isolation":"sandboxed"})
        self.assertEqual("sandboxed",out["script_isolation"]);self.assertEqual({"sandbox","network_isolation"},set(out["sandbox"]))
        with open(os.path.join(self.iso.dir,"settings.json"),encoding="utf-8") as handle:
            self.assertEqual("sandboxed",json.load(handle)["extensions"]["flows"]["script_isolation"])
        flows.policy_set({"script_isolation":"sandboxed"})
        flows.policy_set({"script_isolation":"allow"})
        self.assertEqual(["script isolation allow -> sandboxed","script isolation sandboxed -> allow"],sorted(e["detail"] for e in self.audit("chain_script_policy")))
        for bad in (None,{},{"script_isolation":"off"},{"script_isolation":"inherit"}):
            with self.assertRaises(ValueError):flows.policy_set(bad)
        self.assertEqual("allow",flows.policy_get()["script_isolation"])
    def test_sandboxed_policy_blocks_script_chains_where_there_is_no_sandbox(self):
        pid=self.diagram("Scripted",self.scripted())
        plain=self.pid
        real=engine.sandbox_info
        try:
            engine.sandbox_info=lambda:{"sandbox":"none","network_isolation":False}
            plan=flows.plan(pid)
            self.assertEqual({"mode":"allow","source":"global","unsandboxed":True,"blocked":False},plan["script_policy"])
            self.assertEqual([True],[s["network"] for s in plan["scripts"]])
            flows.policy_set({"script_isolation":"sandboxed"})
            plan=flows.plan(pid)
            self.assertEqual({"mode":"sandboxed","source":"global","unsandboxed":True,"blocked":True},plan["script_policy"])
            self.assertEqual(flows.SCRIPTS_BLOCKED,plan["blocked"])
            with self.assertRaises(ValueError) as caught:flows.run(pid,{"confirmed":True})
            self.assertEqual(flows.SCRIPTS_BLOCKED,str(caught.exception))
            self.assertEqual("done",self.finish(flows.run(pid,{"mode":"dry"}))["state"])
            self.assertEqual([],terminal.list_jobs())
            self.assertFalse(flows.plan(plain)["script_policy"]["blocked"])
            self.assertEqual("done",self.finish(flows.run(plain,{"confirmed":True}))["state"])
            engine.sandbox_info=lambda:{"sandbox":"bwrap","network_isolation":True}
            self.assertEqual({"mode":"sandboxed","source":"global","unsandboxed":False,"blocked":False},flows.plan(pid)["script_policy"])
        finally:
            engine.sandbox_info=real
    def test_a_diagram_can_tighten_and_only_a_trusted_one_can_loosen(self):
        real=engine.sandbox_info
        try:
            engine.sandbox_info=lambda:{"sandbox":"none","network_isolation":False}
            tight=self.diagram("Tight",self.scripted(script_isolation="sandboxed"))
            self.assertEqual({"mode":"sandboxed","source":"diagram","unsandboxed":True,"blocked":True},flows.plan(tight)["script_policy"])
            with self.assertRaises(ValueError):flows.run(tight,{"confirmed":True})
            flows.policy_set({"script_isolation":"sandboxed"})
            loose=self.diagram("Loose",self.scripted(script_isolation="allow"))
            plan=flows.plan(loose)
            self.assertEqual({"mode":"allow","source":"diagram","unsandboxed":True,"blocked":False},plan["script_policy"])
            self.assertNotIn("script_isolation_ignored",[w["code"] for w in plan["warnings"]])
            self.assertEqual("done",self.finish(flows.run(loose,{"confirmed":True}))["state"])
            made=flows.create("AI loose",self.scripted(script_isolation="allow"),ai_client="Claude")["playbook_id"]
            for step in ("unreviewed","reviewed but AI-made"):
                plan=flows.plan(made)
                self.assertEqual({"mode":"sandboxed","source":"global","unsandboxed":True,"blocked":True},plan["script_policy"],step)
                self.assertIn("script_isolation_ignored",[w["code"] for w in plan["warnings"]],step)
                with self.assertRaises(ValueError):flows.run(made,{"confirmed":True,"review_ack":True})
                store.set_reviewed(made,True)
            flows.mark_reviewed(made)
            self.assertEqual("allow",flows.plan(made)["script_policy"]["mode"])
        finally:
            engine.sandbox_info=real
    def test_the_engine_refuses_a_script_under_the_policy_even_inside_a_sub_chain(self):
        real=engine.sandbox_info
        try:
            engine.sandbox_info=lambda:{"sandbox":"none","network_isolation":False}
            child=self.diagram("Child",self.scripted(script_isolation="sandboxed"))
            parent=self.diagram("Parent",graph([node("sub","subchain",playbook_id=child),cmd("h","echo handled")],["start.out>sub","sub.fail>h"]))
            self.assertFalse(flows.plan(parent)["script_policy"]["blocked"])
            status=self.finish(flows.run(parent,{"confirmed":True}))
            self.assertEqual("done",status["state"])
            self.assertEqual(("fail","success"),(status["nodes"]["sub"]["state"],status["nodes"]["h"]["state"]))
            self.assertEqual("fail",status["nodes"]["sub"]["output"]["sub_run"]["nodes"]["s"]["state"])
            self.assertIn("sandbox",status["nodes"]["sub"]["output"]["sub_run"]["nodes"]["s"]["error"])
            self.assertEqual(["echo handled"],[j["command"] for j in terminal.list_jobs()])
            self.assertFalse(any("[script:" in e["detail"] for e in self.audit("terminal_command")))
            direct=engine.start_run(self.scripted(),name="direct",script_mode="sandboxed")
            direct.finished.wait(20)
            self.assertEqual("failed",direct.status()["state"])
            self.assertEqual(engine.SCRIPTS_NEED_SANDBOX,direct.status()["nodes"]["s"]["error"])
        finally:
            engine.sandbox_info=real
    def test_the_same_chain_cannot_run_twice_at_once(self):
        pid=self.diagram("Slow",graph([cmd("a",slow(30))],["start.out>a"]))
        started=flows.run(pid,{"confirmed":True})
        with self.assertRaises(ValueError):flows.run(pid,{"confirmed":True})
        self.assertEqual([started["run_id"]],[r["run_id"] for r in flows.active_runs()])
        self.assertTrue(flows.stop(started["run_id"]))
        self.assertEqual("cancelled",self.finish(started)["state"])
        self.assertEqual([],flows.active_runs())
    def test_run_start_and_end_are_audited_with_the_source(self):
        self.finish(flows.run(self.pid,{"confirmed":True,"source":"caller"}))
        self.assertTrue(any("flow-caller run" in e["detail"] and "chain %d"%self.pid in e["detail"] for e in self.audit("chain_run_start")))
        self.assertEqual(1,len(self.audit("chain_run_end")))
        self.assertTrue(any(e["detail"].startswith("flow-caller:chain:") for e in self.audit("terminal_command")))
class RunControlTests(Base):
    def test_pause_resume_approve_through_the_service(self):
        g=graph([node("ask","approval",message="continue?"),cmd("a","echo yes")],["start.out>ask","ask.approved>a"])
        started=flows.run(self.diagram("Ask",g),{"confirmed":True})
        rid=started["run_id"]
        self.assertTrue(wait_until(lambda:flows.run_status(rid)["state"]=="waiting_approval"))
        self.assertFalse(flows.approve(rid,"other",True))
        self.assertTrue(flows.approve(rid,"ask",True))
        self.assertEqual("done",self.finish(started)["state"])
        self.assertEqual(1,len(self.audit("chain_run_approval")))
        for call in (flows.pause,flows.resume,flows.stop):
            self.assertFalse(call(rid))
        with self.assertRaises(ValueError):flows.stop("no-such-run")
        with self.assertRaises(ValueError):flows.run_status("no-such-run")
    def test_history_lists_runs_and_keeps_the_final_status(self):
        pid=self.diagram("History",graph([cmd("a","echo logged")],["start.out>a"]))
        first=self.finish(flows.run(pid,{"confirmed":True}))
        self.finish(flows.run(pid,{"mode":"dry"}))
        rows=flows.runs(pid)
        self.assertEqual(["dry","run"],[r["mode"] for r in rows])
        self.assertEqual({"run_id","playbook_id","chain_name","mode","state","source","target","started_at","ended_at"},set(rows[0]))
        self.assertEqual(rows,flows.runs())
        self.assertEqual([],flows.runs(pid+100))
        engine._runs.clear()
        stored=flows.run_get(first["run_id"])
        self.assertEqual("done",stored["state"])
        self.assertIn("logged",stored["nodes"]["a"]["output"]["stdout"])
        self.assertEqual([],flows.run_status(first["run_id"],since=stored["seq"])["events"])
        self.assertTrue(flows.run_delete(first["run_id"]))
        self.assertEqual(1,flows.runs_clear(pid))
        self.assertEqual([],flows.runs())
    def test_a_stored_run_is_slimmed_by_since_too(self):
        pid=self.diagram("History",graph([cmd("a","echo logged")],["start.out>a"]))
        done=self.finish(flows.run(pid,{"confirmed":True}))
        engine._runs.clear()
        self.assertIn("output",flows.run_status(done["run_id"])["nodes"]["a"])
        later=flows.run_status(done["run_id"],since=done["seq"])
        self.assertNotIn("output",later["nodes"]["a"])
        self.assertEqual("success",later["nodes"]["a"]["state"])
    def test_every_run_has_a_structured_redacted_log(self):
        d=node("d","decision",branches=[{"name":"yes","match":"all","conditions":[{"source":"output","op":"contains","value":"token"}]}],**{"else":"no"})
        g=graph([cmd("a","echo token --password=Sup3rSecret99"),d,cmd("y","exit 3"),cmd("h","echo handled")],["start.out>a","a.success>d","d.yes>y","y.fail>h"])
        pid=self.diagram("Logged",g)
        started=flows.run(pid,{"confirmed":True})
        status=self.finish(started)
        log=flows.run_log(started["run_id"])
        self.assertEqual({"run_id","entries","next","live","total"},set(log))
        self.assertEqual((False,len(log["entries"])),(log["live"],log["total"]))
        entries=log["entries"]
        self.assertEqual(list(range(1,len(entries)+1)),[e["seq"] for e in entries])
        self.assertEqual(entries[-1]["seq"],log["next"])
        for entry in entries:self.assertEqual({"seq","ts","node","title","level","kind","text","data"},set(entry))
        kinds=[e["kind"] for e in entries]
        self.assertEqual(("run_start","run_end"),(kinds[0],kinds[-1]))
        for kind in ("node_start","command","exit","branch","node_end"):self.assertIn(kind,kinds)
        self.assertNotIn("Sup3rSecret99",json.dumps(entries))
        command=next(e for e in entries if e["kind"]=="command" and e["node"]=="a")
        self.assertIn("[redacted]",command["text"]);self.assertEqual("a",command["title"]);self.assertIn("job_key",command["data"])
        exits=[e for e in entries if e["kind"]=="exit"]
        self.assertEqual([0,3,0],[e["data"]["exit_code"] for e in exits])
        self.assertEqual(["info","warn","info"],[e["level"] for e in exits])
        branch=next(e for e in entries if e["kind"]=="branch" and e["node"]=="d")
        self.assertEqual("yes",branch["data"]["branch"]);self.assertTrue(branch["data"]["rules"][0]["matched"])
        end=next(e for e in entries if e["kind"]=="node_end" and e["node"]=="y")
        self.assertEqual(("fail","fail","warn",True),(end["data"]["state"],end["data"]["branch"],end["level"],end["data"]["handled"]))
        self.assertEqual([],[e for e in entries if e["level"]=="error"],"a failure the chain handles is not an error")
        self.assertEqual(["exit","node_end"],[e["kind"] for e in entries if e["node"]=="y" and e["level"]=="warn"])
        self.assertIn("duration_ms",end["data"])
        totals=entries[-1]["data"]
        self.assertEqual(("done",3),(totals["state"],totals["commands"]))
        self.assertIn("duration_ms",totals)
        # the same log from the database once the run is no longer in memory
        engine._runs.clear()
        stored=flows.run_log(started["run_id"])
        self.assertEqual(entries,stored["entries"])
        self.assertEqual(entries[5:],flows.run_log(started["run_id"],since=5)["entries"])
        page=flows.run_log(started["run_id"],since=2,limit=3)
        self.assertEqual(([3,4,5],5,len(entries)),([e["seq"] for e in page["entries"]],page["next"],page["total"]))
        text=flows.run_log_text(started["run_id"])
        lines=text.splitlines()
        self.assertEqual(len(entries)+1,len(lines))
        self.assertRegex(lines[0],r"^# times are local, UTC offset [+-]\d\d:\d\d$")
        self.assertRegex(lines[1],r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d INFO  Run started")
        self.assertRegex(lines[2],r"^\d\d:\d\d:\d\d INFO  ")
        from datetime import datetime
        local=datetime.fromisoformat(entries[0]["ts"]).astimezone()
        self.assertTrue(lines[1].startswith(local.strftime("%Y-%m-%d %H:%M:%S")))
        offset=int(local.utcoffset().total_seconds()//60)
        self.assertTrue(lines[0].endswith("%s%02d:%02d"%("-" if offset<0 else "+",abs(offset)//60,abs(offset)%60)))
        self.assertIn("WARN  [y] Exit code 3",text);self.assertNotIn("Sup3rSecret99",text)
        con=sqlite3.connect(common_db.db_path())
        try:self.assertNotIn("Sup3rSecret99",json.dumps(con.execute("SELECT text,data FROM ChainRunLogs").fetchall()))
        finally:con.close()
        with self.assertRaises(ValueError):flows.run_log("no-such-run")
    def test_a_failed_command_logs_the_end_of_its_stderr_once(self):
        noisy="for i in $(seq 1 30); do echo err-line-$i 1>&2; done; echo --password=T4ilSecret99 1>&2; exit 7"
        handled=self.diagram("Handled",graph([cmd("a",noisy),cmd("h","echo handled")],["start.out>a","a.fail>h"]))
        started=flows.run(handled,{"confirmed":True});self.assertEqual("done",self.finish(started)["state"])
        entries=flows.run_log(started["run_id"])["entries"]
        self.assertEqual([],[e for e in entries if e["level"]=="error"])
        about=[e for e in entries if e["node"]=="a" and e["level"]!="info"]
        self.assertEqual([("exit","warn"),("node_end","warn")],[(e["kind"],e["level"]) for e in about])
        tail=about[0]["data"]["stderr_tail"]
        self.assertEqual(20,len(tail.splitlines()))
        self.assertEqual("err-line-12",tail.splitlines()[0]);self.assertIn("[redacted]",tail.splitlines()[-1])
        self.assertNotIn("T4ilSecret99",str(about[0]))
        self.assertEqual("Exit code 7\n"+tail,about[0]["text"])
        self.assertIn("\n    err-line-30\n",flows.run_log_text(started["run_id"]))
        # nothing handles it: the same two entries, now errors, and the run fails
        bare=self.diagram("Unhandled",graph([cmd("a","echo only-stdout; exit 2")],["start.out>a"]))
        started=flows.run(bare,{"confirmed":True});self.assertEqual("failed",self.finish(started)["state"])
        entries=flows.run_log(started["run_id"])["entries"]
        about=[e for e in entries if e["node"]=="a" and e["level"]!="info"]
        self.assertEqual([("exit","error"),("node_end","error")],[(e["kind"],e["level"]) for e in about])
        self.assertEqual("only-stdout",about[0]["data"]["stderr_tail"])
        self.assertEqual("error",entries[-1]["level"])
        # on_error=continue with no edge is still an error
        g=graph([cmd("a","exit 2"),cmd("b","echo next")],["start.out>a","start.out>b"],on_error="continue")
        started=flows.run(self.diagram("Continue",g),{"confirmed":True});self.assertEqual("done",self.finish(started)["state"])
        about=[e for e in flows.run_log(started["run_id"])["entries"] if e["node"]=="a" and e["kind"]=="exit"]
        self.assertEqual(["error"],[e["level"] for e in about])
    def test_failed_scripts_and_refusals_carry_their_message(self):
        def scripted(code,*edges,**config):
            return graph([node("s","script",language="python",code=code,branches=["out"],**config),cmd("h","echo handled")],["start.out>s"]+list(edges))
        started=flows.run(self.diagram("Script fail",scripted("import sys\nsys.stderr.write('boom-detail\\n')\nsys.exit(4)\n","s.error>h")),{"confirmed":True})
        self.assertEqual("done",self.finish(started)["state"])
        entries=flows.run_log(started["run_id"])["entries"]
        about=[e for e in entries if e["node"]=="s" and e["level"]!="info"]
        self.assertEqual([("exit","warn"),("node_end","warn")],[(e["kind"],e["level"]) for e in about])
        self.assertEqual(("boom-detail","Exit code 4\nboom-detail"),(about[0]["data"]["stderr_tail"],about[0]["text"]))
        started=flows.run(self.diagram("Script slow",scripted("import time\ntime.sleep(30)\n",timeout=1)),{"confirmed":True})
        self.assertEqual("failed",self.finish(started)["state"])
        exit_entry=next(e for e in flows.run_log(started["run_id"])["entries"] if e["kind"]=="exit")
        self.assertEqual(("error",True),(exit_entry["level"],exit_entry["data"]["timed_out"]))
        self.assertTrue(exit_entry["text"].startswith("Timed out"))
        real=engine.sandbox_info
        try:
            engine.sandbox_info=lambda:{"sandbox":"none","network_isolation":False}
            refused=engine.start_run(scripted("print(1)\n"),name="refused",script_mode="sandboxed")
            refused.finished.wait(20)
        finally:
            engine.sandbox_info=real
        entries=refused.log_entries()[0]
        self.assertEqual([],[e for e in entries if e["kind"]=="exit"])
        self.assertTrue(any(e["kind"]=="error" and e["node"]=="s" and engine.SCRIPTS_NEED_SANDBOX in e["text"] for e in entries))
    def test_dry_runs_are_logged_and_logs_go_with_their_run(self):
        pid=self.diagram("Dry log",graph([cmd("a","echo {IPv4}")],["start.out>a"]))
        dry=flows.run(pid,{"mode":"dry"});self.finish(dry)
        log=flows.run_log(dry["run_id"])
        kinds=[e["kind"] for e in log["entries"]]
        self.assertEqual(("run_start","run_end"),(kinds[0],kinds[-1]))
        planned=next(e for e in log["entries"] if e["kind"]=="command")
        self.assertEqual((True,["IPv4"],"warn"),(planned["data"]["dry"],planned["data"]["missing"],planned["level"]))
        set_live_target({"IPv4":"127.0.0.1"})
        real=flows.run(pid,{"confirmed":True});self.finish(real)
        engine._runs.clear()
        self.assertTrue(flows.run_delete(dry["run_id"]))
        with self.assertRaises(ValueError):flows.run_log(dry["run_id"])
        self.assertTrue(flows.run_log(real["run_id"])["total"])
        self.assertEqual(1,flows.runs_clear(pid))
        con=sqlite3.connect(common_db.db_path())
        try:self.assertEqual(0,con.execute("SELECT COUNT(*) FROM ChainRunLogs").fetchone()[0])
        finally:con.close()
    def test_a_live_log_can_be_followed_and_survives_a_lock(self):
        pid=self.diagram("Live log",graph([cmd("a","echo first"),cmd("b",slow(30))],["start.out>a","a.success>b"]))
        started=flows.run(pid,{"confirmed":True})
        rid=started["run_id"]
        self.assertTrue(wait_until(lambda:bool(flows.run_status(rid)["nodes"]["b"]["job_keys"])))
        first=flows.run_log(rid)
        self.assertTrue(first["live"])
        self.assertIn("command",[e["kind"] for e in first["entries"]])
        self.assertEqual([],flows.run_log(rid,since=first["next"])["entries"])
        common_db.set_locked(True)
        status=flows.wait(rid,10)
        self.assertEqual("cancelled",status["state"])
        engine._runs.clear()
        self.assertTrue(engine.pending_log(rid))
        common_db.set_locked(False)
        after=flows.run_log(rid)
        self.assertEqual("run_end",after["entries"][-1]["kind"])
        self.assertEqual(list(range(1,after["total"]+1)),[e["seq"] for e in after["entries"]])
        self.assertEqual([],engine.pending_log(rid))
        self.assertEqual(first["entries"],after["entries"][:len(first["entries"])])
    def test_the_log_is_capped(self):
        old=engine.LOG_MAX
        engine.LOG_MAX=12
        try:
            g=graph([node("a","set",assign=[{"var":"x","value":"1"}]),node("b","set",assign=[{"var":"y","value":"2"}])],["start.out>a","a.out>b","b.out>a"],max_visits=40)
            started=flows.run(self.diagram("Chatty",g),{"confirmed":True})
            self.finish(started)
            log=flows.run_log(started["run_id"])
        finally:
            engine.LOG_MAX=old
        self.assertEqual(12,log["total"])
        self.assertIn("Log truncated",log["entries"][-1]["text"])
    def test_the_run_log_export_uses_the_save_dialog(self):
        from Cores.Bridge import api
        from Cores.Bridge.flows_api import FlowsAPI
        pid=self.diagram("Export: log",graph([cmd("a","echo logged")],["start.out>a"]))
        started=flows.run(pid,{"confirmed":True});self.finish(started)
        rid=started["run_id"]
        bridge=FlowsAPI();bridge.bind("window")
        seen={}
        real=api._save_dialog
        try:
            def save(window,label,ext,default):
                seen["call"]=(label,ext,default)
                return seen.get("to")
            api._save_dialog=save
            self.assertEqual({"ok":False,"path":""},bridge.run_log_export(rid))
            self.assertEqual(("Log","log","Export_ log-"+rid+".log"),seen["call"])
            seen["to"]=os.path.join(self.iso.dir,"picked.log.log")
            out=bridge.run_log_export(rid,"text")
            self.assertEqual({"ok":True,"path":os.path.join(self.iso.dir,"picked.log")},out)
            self.assertEqual(flows.run_log_text(rid),open(out["path"],encoding="utf-8").read())
            seen["to"]=os.path.join(self.iso.dir,"picked.JSON")
            out=bridge.run_log_export(rid,"json")
            self.assertEqual(("JSON","json","Export_ log-"+rid+".json"),seen["call"])
            self.assertTrue(out["path"].endswith("picked.JSON"))
            data=json.load(open(out["path"],encoding="utf-8"))
            self.assertEqual((rid,"Export: log"),(data["run_id"],data["chain"]))
            self.assertEqual(flows.run_log(rid)["entries"],data["entries"])
            self.assertEqual(flows.run_log(rid),bridge.run_log(rid));self.assertEqual(flows.run_log_text(rid),bridge.run_log_text(rid))
        finally:
            api._save_dialog=real
    def test_re_run_from_a_node_uses_the_last_run(self):
        g=graph([cmd("a","echo first-output"),node("v","set",assign=[{"var":"kept","value":"${last.stdout}"}]),cmd("b","echo again ${kept}")],["start.out>a","a.success>v","v.out>b"])
        pid=self.diagram("Rerun",g)
        self.finish(flows.run(pid,{"confirmed":True}))
        engine._runs.clear()
        status=self.finish(flows.run(pid,{"confirmed":True,"from_node":"b"}))
        self.assertEqual("done",status["state"])
        self.assertEqual({"start":"skipped","a":"skipped","v":"skipped","b":"success"},{k:v["state"] for k,v in status["nodes"].items()})
        self.assertIn("again first-output",status["nodes"]["b"]["output"]["stdout"])
        with self.assertRaises(ValueError):flows.run(pid,{"confirmed":True,"from_node":"ghost"})
    def test_sub_chains_resolve_saved_and_linear_chains(self):
        child=linear_chain("Child","echo from-linear-child")
        other=self.diagram("Other",graph([cmd("c","echo from-diagram-child")],["start.out>c"]))
        parent=self.diagram("Parent",graph([node("s1","subchain",playbook_id=child),node("s2","subchain",playbook_id=other)],["start.out>s1","s1.success>s2"]))
        status=self.finish(flows.run(parent,{"confirmed":True}))
        self.assertEqual("done",status["state"],status["nodes"])
        self.assertEqual(["echo from-diagram-child","echo from-linear-child"],[j["command"] for j in terminal.list_jobs()])
        self.assertEqual([parent],[r["playbook_id"] for r in flows.runs()])
    def test_locking_stops_a_service_run(self):
        pid=self.diagram("Slow",graph([cmd("a",slow(30))],["start.out>a"]))
        started=flows.run(pid,{"confirmed":True})
        self.assertTrue(wait_until(lambda:bool(flows.run_status(started["run_id"])["nodes"]["a"]["job_keys"])))
        common_db.set_locked(True)
        status=flows.wait(started["run_id"],10)
        self.assertEqual(("cancelled","locked"),(status["state"],status["reason"]))
        common_db.set_locked(False)
        self.assertEqual(["cancelled"],[r["state"] for r in flows.runs(pid)])
class BridgeTests(Base):
    def test_every_flows_method_is_refused_while_locked(self):
        from Cores.Bridge import api
        from Cores.Bridge.flows_api import FlowsAPI
        self.assertNotIn("flows",api._LOCK_OPEN)
        class Fake:
            def __init__(self):
                self.flows=FlowsAPI()
                api._guard_while_locked(self)
        bridge=Fake().flows
        self.assertEqual([],bridge.list())
        names=[n for n in dir(FlowsAPI) if not n.startswith("_") and n!="bind"]
        self.assertEqual({"catalog","list","get","create","save","validate","revert_linear","export_json","import_json","template","demos","demo","create_from_demo","plan","run","run_status","active_runs","pause","resume","stop","approve","runs","run_get","run_delete","runs_clear","mark_reviewed","prefs_get","prefs_set","ai_guide","create_ai_draft","export_file","import_file","run_log","run_log_text","run_log_export","policy_get","policy_set"},set(names)-{"bind"})
        common_db.set_locked(True)
        for name in names:
            with self.assertRaises(ValueError,msg=name) as caught:getattr(bridge,name)()
            self.assertIn("locked",str(caught.exception),name)
    def test_export_and_import_through_the_native_dialogs(self):
        import inspect
        from Cores.Bridge import api
        from Cores.Bridge.flows_api import FlowsAPI
        self.assertIn("self.flows.bind(window)",inspect.getsource(api.Api.bind))
        bridge=FlowsAPI()
        pid=bridge.create("Web: quick/wins",graph([cmd("a","echo {IPv4}")],["start.out>a"]))["playbook_id"]
        with self.assertRaises(ValueError):bridge.export_file(pid)
        seen={}
        target=os.path.join(self.iso.dir,"out.json")
        real_save,real_open=api._save_dialog,api._open_dialog
        try:
            def save(window,label,ext,default):
                seen["save"]=(window,label,ext,default)
                return seen.get("save_to")
            def pick(window,label,ext):
                seen["open"]=(window,label,ext)
                return seen.get("open_from")
            api._save_dialog,api._open_dialog=save,pick
            bridge.bind("window")
            self.assertEqual({"ok":False,"path":""},bridge.export_file(pid))
            self.assertEqual(("window","JSON","json","Web_ quick_wins.loya-chain.json"),seen["save"])
            self.assertFalse(os.path.exists(target))
            seen["save_to"]=target
            self.assertEqual({"ok":True,"path":target},bridge.export_file(pid))
            raw=open(target,"rb").read()
            self.assertNotIn(b"\r",raw)
            self.assertEqual(1,json.loads(raw.decode("utf-8"))["loya_chain"])
            self.assertEqual({"ok":False},bridge.import_file())
            self.assertEqual(("window","JSON","json"),seen["open"])
            seen["open_from"]=[target]
            out=bridge.import_file()
            self.assertEqual({"playbook_id","warnings","ok","path"},set(out))
            self.assertTrue(out["ok"])
            self.assertNotEqual(pid,out["playbook_id"])
            self.assertEqual(flows.get(pid)["graph"]["nodes"],flows.get(out["playbook_id"])["graph"]["nodes"])
            self.assertFalse(flows.get(out["playbook_id"])["ai_reviewed"])
            with open(target,"w") as handle:handle.write("not a chain")
            with self.assertRaises(ValueError):bridge.import_file()
            with self.assertRaises(ValueError):bridge.export_file(424242)
        finally:
            api._save_dialog,api._open_dialog=real_save,real_open
    def test_the_file_dialog_methods_are_refused_while_locked_and_bind_is_python_only(self):
        from Cores.Bridge import api
        from Cores.Bridge.flows_api import FlowsAPI
        class Fake:
            def __init__(self):
                self.flows=FlowsAPI()
                api._guard_while_locked(self)
        bridge=Fake().flows
        self.assertFalse(getattr(bridge.bind,"_serializable",True))
        common_db.set_locked(True)
        with self.assertRaises(ValueError):bridge.export_file(1)
        with self.assertRaises(ValueError):bridge.import_file()
    def test_the_api_registers_flows(self):
        import inspect
        from Cores.Bridge import api
        self.assertIn("self.flows=FlowsAPI()",inspect.getsource(api.Api.__init__))
        self.assertLess(inspect.getsource(api.Api.__init__).index("self.flows=FlowsAPI()"),inspect.getsource(api.Api.__init__).index("_guard_while_locked(self)"))
    def test_bridge_shapes(self):
        from Cores.Bridge.flows_api import FlowsAPI
        bridge=FlowsAPI()
        made=bridge.create("Bridge",graph([cmd("a","echo bridge")],["start.out>a"]))
        self.assertEqual({"playbook_id"},set(made))
        pid=made["playbook_id"]
        self.assertEqual({"playbook_id","name","caller","graph","derived","ai_made","ai_reviewed","ai_client","origin","errors","warnings"},set(bridge.get(pid)))
        self.assertEqual({"ok","errors","warnings"},set(bridge.save(pid,bridge.get(pid)["graph"])))
        self.assertEqual({"ok","errors","warnings","graph"},set(bridge.validate(bridge.get(pid)["graph"])))
        self.assertEqual({"target","commands","scripts","actions","approvals","subchains","ai_made","needs_review","review_each_run","terminal_enabled","sandbox","script_policy","raw","raw_refused","errors","warnings","blocked","missing","fingerprint"},set(bridge.plan(pid)))
        started=bridge.run(pid,{"confirmed":True,"source":"ai"})
        self.assertEqual({"run_id"},set(started))
        status=self.finish(started)
        self.assertEqual("manual",status["source"])
        for key in ("run_id","playbook_id","name","mode","state","reason","source","target","started_at","ended_at","current","nodes","edges_taken","events","approval","vars","seq"):self.assertIn(key,status)
        self.assertEqual({"state","visits","branch","started_at","ended_at","duration_ms","error","job_keys","output","seq"},set(status["nodes"]["a"]))
        self.assertEqual({"seq","ts","node","level","text"},set(status["events"][0]))
        json.dumps(status)
        self.assertIsInstance(bridge.export_json(pid),str)
        self.assertEqual({"playbook_id","warnings"},set(bridge.import_json(bridge.export_json(pid))))
if __name__=="__main__":unittest.main()
