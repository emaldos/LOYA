"""The AI panel's chain authoring: the /newchain guide (built from flow_schema, so it cannot drift), the draft a chat reply is
stored as (AI-made, not reviewed, audited) and the chain_create / chain_update tool descriptions an MCP agent reads."""
import json,os,re,sys,unittest
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from _isolate import IsolatedData
from _flow_helpers import node,cmd,graph,set_live_target
from Cores import chain_callers,common_db
from Cores.Bridge.flows_api import FlowsAPI
from Cores.Services import ai_chat_service as chat
from Cores.Services import flow_engine as engine
from Cores.Services import flow_schema as schema
from Cores.Services import flow_service as flows
from Cores.Services import flow_store as store
from Cores.Services import playbooks_service as chains
from Cores.Services import security_service as security
from Cores.Services import terminal_service as terminal
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def _block(text):
    """The JSON inside the guide's ```loya-chain example block."""
    found=re.search(r"```"+re.escape(flows.GUIDE_FENCE)+r"\n(.*?)\n```",text,re.S)
    return json.loads(found.group(1)) if found else None
class GuideTests(unittest.TestCase):
    def setUp(self):
        self.out=flows.ai_guide()
        self.guide=self.out["guide"]
    def test_shape(self):
        self.assertEqual({"fence","guide","example"},set(self.out))
        self.assertEqual("loya-chain",self.out["fence"])
        self.assertIn("```loya-chain",self.guide)
        self.assertLess(len(self.guide),14000,"the guide rides along with every /newchain request: keep it compact (39 node types since schema 2)")
        json.dumps(self.out)   # must cross the bridge
    def test_mentions_every_node_type_with_its_ports_and_config_keys(self):
        for name,spec in schema.NODE_TYPES.items():
            line=next((l for l in self.guide.splitlines() if l.startswith("- %s: "%name)),None)
            self.assertIsNotNone(line,"node type %s is missing from the guide"%name)
            self.assertIn(spec["description"],line)
            if isinstance(spec["ports"],list):
                for port in spec["ports"]:self.assertRegex(line.split("| ports:")[1].split("| config:")[0],r"\b%s\b"%re.escape(port),name)
            else:
                self.assertIn(name,flows._GUIDE_PORTS,"a dynamic-port node type needs its ports explained")
            for key in spec["defaults"]:self.assertIn('"%s"'%key,line.split("| config:")[1],"%s.%s"%(name,key))
    def test_condition_format_lists_every_source_and_operator(self):
        for source in schema.SOURCES:self.assertRegex(self.guide,r"\b%s\b"%source)
        for op in schema.OPS:self.assertRegex(self.guide,r"\b%s\b"%op)
        self.assertIn('{"source":S,"field":"","op":OP,"value":"","ci":true}',self.guide)
        for mode in schema.PARSE_TOOLS+schema.OUTPUT_ACTIONS+schema.SCRIPT_LANGUAGES+schema.SPLIT_MODES:self.assertIn(mode,self.guide)
    def test_explains_placeholders_versus_flow_values(self):
        self.assertIn("{IPv4}",self.guide)
        self.assertIn("${last.stdout}",self.guide)
        self.assertIn("shell-quoted",self.guide)
        self.assertIn("Never use ${raw:",self.guide)
        self.assertIn("LOYA_INPUT_FILE",self.guide)   # the script protocol
        self.assertIn('"branch"',self.guide)
    def test_limits_come_from_the_schema(self):
        for key in ("nodes","edges","commands_per_node","branches","conditions"):self.assertIn(str(schema.LIMITS[key]),self.guide)
    def test_example_validates_and_is_the_one_shown(self):
        example=self.out["example"]
        self.assertEqual(example,_block(self.guide))
        result=schema.validate_graph(example["graph"])
        self.assertTrue(result["ok"],result["errors"])
        self.assertEqual([],result["errors"])
        types=[n["type"] for n in result["graph"]["nodes"]]
        self.assertEqual(1,types.count("start"))
        self.assertIn("decision",types)
        self.assertTrue(example["name"])
        self.assertLessEqual(len(example["graph"]["nodes"]),6,"keep the example small")
        # It is the request from the brief: ping, alive -> nmap, otherwise notify.
        texts=[c["text"] for c in schema.graph_commands(result["graph"])]
        self.assertTrue(any("ping" in t and "{IPv4}" in t for t in texts) and any("nmap" in t for t in texts),texts)
        self.assertTrue(any(n["type"]=="output" and n["config"]["action"]=="notify" for n in result["graph"]["nodes"]))
    def test_never_tells_the_model_to_run_anything(self):
        self.assertIn("never say the chain was run",self.guide)
        self.assertIn("Do not use tools for this",self.guide)
        self.assertNotIn("chain_run",self.guide)
    def test_bridge_exposes_it(self):
        self.assertEqual(self.out,FlowsAPI().ai_guide())
class DraftTests(unittest.TestCase):
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
    def audit(self,event="chain_diagram_create"):
        return [e["detail"] for e in security.list_audit_events(500) if e["event"]==event]
    def test_draft_is_ai_made_unreviewed_and_audited(self):
        example=flows.ai_guide()["example"]
        out=FlowsAPI().create_ai_draft(example["name"],example["graph"],"llama3")
        self.assertEqual([],out["errors"])
        pid=out["playbook_id"]
        row=store.get_graph_row(pid)
        self.assertEqual((1,0),(int(row["ai_made"]),int(row["ai_reviewed"])))
        self.assertEqual("AI panel: llama3",row["ai_client"])
        got=flows.get(pid)
        self.assertEqual((example["name"],True,False,False),(got["name"],got["ai_made"],got["ai_reviewed"],got["derived"]))
        listed=next(r for r in flows.list_flows() if r["playbook_id"]==pid)
        self.assertEqual((True,True,False),(listed["has_graph"],listed["ai_made"],listed["ai_reviewed"]))
        details=self.audit()
        self.assertTrue(any("chain %d "%pid in d and "source=ai-panel" in d and "not reviewed" in d for d in details),details)
    def test_draft_never_runs_without_the_review(self):
        set_live_target({"IPv4":"127.0.0.1"})
        pid=flows.create_ai_draft("Echo",graph([cmd("c","echo hi")],["start.out>c"]))["playbook_id"]
        self.assertTrue(flows.plan(pid)["needs_review"])
        with self.assertRaises(ValueError):flows.run(pid,{"mode":"run"})                     # not confirmed
        with self.assertRaises(ValueError) as refused:flows.run(pid,{"mode":"run","confirmed":True})
        self.assertIn("has not been reviewed",str(refused.exception))
        self.assertEqual(0,int(store.get_graph_row(pid)["ai_reviewed"]))
        self.assertEqual([],[r for r in flows.runs(pid) if r["mode"]=="run"])
    def test_invalid_draft_is_refused_like_chain_create(self):
        # Storing normalizes (the bad edge would be dropped): a broken diagram must not turn into a different, runnable one.
        bad={"schema":1,"nodes":[node("start","start"),cmd("c","echo hi")],"edges":[{"id":"e1","from":"start","port":"nope","to":"c"}]}
        before=len(chains.list_playbooks())
        with self.assertRaises(ValueError) as refused:flows.create_ai_draft("Broken",bad)
        self.assertIn("not valid",str(refused.exception))
        self.assertEqual(before,len(chains.list_playbooks()))
    def test_accepts_a_bundle_and_falls_back_on_the_name(self):
        example=flows.ai_guide()["example"]
        pid=flows.create_ai_draft("",{"name":"From the bundle","graph":example["graph"]})["playbook_id"]
        self.assertEqual("From the bundle",flows.get(pid)["name"])
        self.assertEqual("AI panel",store.get_graph_row(pid)["ai_client"])
        pid=flows.create_ai_draft(None,example["graph"])["playbook_id"]
        self.assertEqual("AI chain",flows.get(pid)["name"])
        pid=flows.create_ai_draft("As text",json.dumps(example["graph"]))["playbook_id"]
        self.assertEqual(5,len(flows.get(pid)["graph"]["nodes"]))
    def test_rubbish_is_refused_and_leaves_no_chain_behind(self):
        before=len(chains.list_playbooks())
        for rubbish in (None,"not json",{"nodes":"x"},[],42,{"graph":"x"}):
            with self.assertRaises(ValueError):flows.create_ai_draft("x",rubbish)
        self.assertEqual(before,len(chains.list_playbooks()))
        self.assertEqual([],self.audit())
    def test_hostile_text_is_stored_as_text(self):
        evil='<img src=x onerror="alert(1)">'
        out=flows.create_ai_draft(evil,{"schema":1,"nodes":[{"id":"n1","type":"start","title":evil,"config":{}}],"edges":[]},client=evil*5)
        got=flows.get(out["playbook_id"])
        self.assertEqual(evil,got["name"])
        self.assertLessEqual(len(store.get_graph_row(out["playbook_id"])["ai_client"]),80)
    def test_page_cannot_reach_the_ai_run_entry_points(self):
        api=FlowsAPI()
        for name in ("ai_run","ai_create","ai_update","ai_run_info"):self.assertFalse(hasattr(api,name),name)
class ToolDescriptionTests(unittest.TestCase):
    """An MCP agent only sees the tool description: it has to be enough to write a valid graph."""
    @classmethod
    def setUpClass(cls):
        cls.tools={t.name:t for t in chat._list_tools()}
    def test_chain_create_describes_the_graph(self):
        text=self.tools["chain_create"].description
        for name,spec in schema.NODE_TYPES.items():
            self.assertRegex(text,r"\b%s\b"%name)
            if isinstance(spec["ports"],list):
                for port in spec["ports"]:self.assertRegex(text,r"\b%s\b"%port,"%s port %s"%(name,port))
        for source in schema.SOURCES:self.assertRegex(text,r"\b%s\b"%source)
        for op in schema.OPS:self.assertRegex(text,r"\b%s\b"%op)
        for needle in ('"nodes"','"edges"','"port"',"{IPv4}","${last.stdout}","chain_templates","unreviewed","else"):self.assertIn(needle,text)
        self.assertLess(len(text),3000)
    def test_chain_update_describes_ports_and_replacement(self):
        text=self.tools["chain_update"].description
        for needle in ("WHOLE","chain_get","success/fail","error","out/nomatch","item/done","approved/rejected","source","op","chain_templates","unreviewed"):self.assertIn(needle,text)
        self.assertLess(len(text),1500)
    def test_signatures_are_unchanged(self):
        self.assertEqual(["name","graph","caller"],list(self.tools["chain_create"].input_schema["properties"]))
        self.assertEqual(["name","graph"],self.tools["chain_create"].input_schema["required"])
        self.assertEqual(["chain_id","graph","name"],list(self.tools["chain_update"].input_schema["properties"]))
        self.assertEqual(["chain_id","graph"],self.tools["chain_update"].input_schema["required"])
    def test_the_example_in_the_description_is_a_real_graph(self):
        # The same five nodes and edges the description spells out, built literally: it must validate.
        nodes=[{"id":"n1","type":"start","title":"Start","x":40,"y":160,"config":{}},
               {"id":"n2","type":"command","title":"Ping","x":300,"y":160,"config":{"commands":[{"text":"ping -c 2 {IPv4}"}],"timeout":300}},
               {"id":"n3","type":"decision","title":"Alive?","x":560,"y":160,"config":{"branches":[{"name":"alive","match":"all","conditions":[{"source":"host_up","op":"is_true"}]}],"else":"down"}},
               {"id":"n4","type":"command","title":"Nmap","x":820,"y":160,"config":{"commands":[{"text":"nmap -Pn -sV {IPv4}"}]}},
               {"id":"n5","type":"output","title":"Down","x":820,"y":310,"config":{"action":"notify","title":"","content":"${last.stdout}"}}]
        edges=[{"id":"e%d"%(i+1),"from":a,"port":p,"to":b} for i,(a,p,b) in enumerate((("n1","out","n2"),("n2","success","n3"),("n2","fail","n3"),("n3","alive","n4"),("n3","down","n5")))]
        result=schema.validate_graph({"schema":1,"nodes":nodes,"edges":edges})
        self.assertTrue(result["ok"],result["errors"])
        text=self.tools["chain_create"].description
        for piece in ('{"commands":[{"text":"ping -c 2 {IPv4}"}],"timeout":300}','{"branches":[{"name":"alive","match":"all","conditions":[{"source":"host_up","op":"is_true"}]}],"else":"down"}',"n1.out->n2, n2.success->n3, n2.fail->n3, n3.alive->n4, n3.down->n5"):self.assertIn(piece,text)
class SlashCommandTests(unittest.TestCase):
    def test_chain_is_reserved_and_the_lists_agree(self):
        self.assertIn("newchain",chain_callers.RESERVED_CALLERS)
        self.assertIn("built-in",chain_callers.caller_error("newchain"))
        self.assertNotIn("chain",chain_callers.RESERVED_CALLERS)
        self.assertEqual("",chain_callers.caller_error("chain"))   # free for a user chain again
        with open(os.path.join(ROOT,"UI","js","components","ai.js"),encoding="utf-8") as handle:source=handle.read()
        start=source.index("const AI_SLASH_COMMANDS")
        names=re.findall(r'\{name:"([^"]+)"',source[start:source.index("\n]",start)])
        self.assertEqual(sorted(chain_callers.RESERVED_CALLERS),sorted(names))
    def test_callers_around_the_reserved_name(self):
        self.assertEqual("chain",chain_callers.suggest_caller("Chain"))
        shadowed=chain_callers.suggest_caller("Newchain")
        self.assertNotEqual("newchain",shadowed)
        self.assertEqual("",chain_callers.caller_error(shadowed))
if __name__=="__main__":
    unittest.main()
