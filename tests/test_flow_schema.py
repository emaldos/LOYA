import copy,json,os,sys,unittest
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from _isolate import IsolatedData
from Cores.Services import flow_schema as schema
from Cores.Services import flow_nodes
def node(node_id,node_type,**config):
    return {"id":node_id,"type":node_type,"title":node_type.title(),"x":0,"y":0,"config":config}
def cmd(node_id,*lines,**extra):
    return node(node_id,"command",commands=[{"text":line} for line in lines],**extra)
def edge(source,port,target,edge_id=None):
    row={"from":source,"port":port,"to":target}
    if edge_id is not None:row["id"]=edge_id
    return row
def graph(nodes,edges=(),**extra):
    data={"schema":1,"nodes":[node("s","start")]+list(nodes),"edges":list(edges)}
    data.update(extra)
    return data
def codes(issues):
    return [issue["code"] for issue in issues]
def decision(node_id,branches,other="else"):
    return node(node_id,"decision",branches=branches,**{"else":other})
def cond(source="output",op="contains",value="x",field="",ci=True):
    return {"source":source,"field":field,"op":op,"value":value,"ci":ci}
class FlowSchemaBase(unittest.TestCase):
    def setUp(self):
        self.isolated=IsolatedData();self.isolated.start()
    def tearDown(self):
        self.isolated.stop()
    def check(self,data):
        return schema.validate_graph(data)
    def assertError(self,data,code):
        result=self.check(data)
        self.assertFalse(result["ok"],code)
        self.assertIn(code,codes(result["errors"]))
        for issue in result["errors"]+result["warnings"]:
            self.assertEqual({"node","edge","code","message"},set(issue))
            self.assertTrue(issue["message"])
        return result
class ValidGraphTests(FlowSchemaBase):
    def test_new_graph_is_valid(self):
        result=self.check(schema.new_graph())
        self.assertTrue(result["ok"],result["errors"])
        self.assertEqual([],result["warnings"])
        self.assertEqual(["start"],[n["type"] for n in result["graph"]["nodes"]])
    def test_every_node_type_in_one_graph(self):
        nodes=[cmd("c","echo hi"),node("sc","script",language="bash",code="echo hi",branches=["a","b"]),
               decision("d",[{"name":"yes","match":"any","conditions":[cond()]}],"no"),
               node("p","parse",mode="regex",pattern=r"(\d+)",assign=[{"var":"n","from":"group:1"}]),
               node("st","set",assign=[{"var":"a","value":"${n}"}]),node("f","foreach",items="${a}"),node("w","wait",seconds=1),
               node("a","approval",message="ok?"),node("o","output",action="notify"),node("sub","subchain",playbook_id=3),
               node("e","end"),node("note","comment",text="hello")]
        edges=[edge("s","out","c"),edge("c","success","sc"),edge("c","fail","e"),edge("sc","a","d"),edge("sc","b","d"),edge("sc","error","e"),
               edge("d","yes","p"),edge("d","no","e"),edge("p","out","st"),edge("p","nomatch","e"),edge("st","out","f"),edge("f","item","w"),
               edge("f","done","a"),edge("a","approved","o"),edge("a","rejected","e"),edge("o","out","sub"),edge("sub","success","e"),edge("sub","fail","e")]
        result=self.check(graph(nodes,edges))
        self.assertTrue(result["ok"],result["errors"])
        self.assertEqual([],result["warnings"])
        # The 13 hand-written types; the field-driven ones of flow_nodes have their own all-in-one graph in test_flow_nodes.py.
        self.assertEqual(set(flow_nodes.LEGACY_TYPES),{n["type"] for n in result["graph"]["nodes"]})
        self.assertEqual(set(schema.NODE_TYPES),set(flow_nodes.LEGACY_TYPES)|set(flow_nodes.FIELD_TYPES))
    def test_cycles_are_legal(self):
        result=self.check(graph([cmd("a","echo 1"),cmd("b","echo 2")],[edge("s","out","a"),edge("a","success","b"),edge("b","success","a"),edge("a","fail","b"),edge("b","fail","a")]))
        self.assertTrue(result["ok"],result["errors"])
    def test_several_edges_may_leave_one_port_in_order(self):
        result=self.check(graph([cmd("a","echo 1"),cmd("b","echo 2")],[edge("s","out","b"),edge("s","out","a")]))
        self.assertTrue(result["ok"])
        self.assertEqual(["b","a"],[e["to"] for e in result["graph"]["edges"]])
    def test_accepts_a_json_string(self):
        self.assertTrue(self.check(json.dumps(schema.new_graph()))["ok"])
    def test_result_is_a_copy(self):
        original=graph([cmd("a","echo 1")],[edge("s","out","a")])
        before=copy.deepcopy(original)
        result=self.check(original)
        result["graph"]["nodes"][1]["config"]["commands"][0]["text"]="changed"
        self.assertEqual(before,original)
    def test_validating_twice_changes_nothing(self):
        for template in schema.TEMPLATES:
            once=self.check(template["graph"])["graph"]
            self.assertEqual(once,self.check(once)["graph"])
class NormalizationTests(FlowSchemaBase):
    def test_defaults_are_filled(self):
        result=self.check({"schema":1,"nodes":[{"id":"s","type":"start"},{"id":"c","type":"command","config":{"commands":["echo hi"]}}],"edges":[{"from":"s","port":"out","to":"c"}]})
        self.assertTrue(result["ok"],result["errors"])
        g=result["graph"]
        self.assertEqual({"shell":"","run_timeout":1800,"max_visits":200,"on_error":"stop","script_isolation":"inherit"},g["settings"])
        self.assertEqual({"x":0,"y":0,"zoom":1},g["viewport"])
        self.assertEqual("Command",g["nodes"][1]["title"])
        self.assertEqual({"commands":[{"text":"echo hi","command_id":None,"src":"","label":""}],"mode":"sequence","stop_on_fail":True,"timeout":300,"shell":""},g["nodes"][1]["config"])
        self.assertEqual("e1",g["edges"][0]["id"])
    def test_script_isolation_setting(self):
        for value in schema.SCRIPT_ISOLATION:
            result=self.check(graph([],[],settings={"script_isolation":value}))
            self.assertTrue(result["ok"],result["errors"])
            self.assertEqual(value,result["graph"]["settings"]["script_isolation"])
        bad=self.check(graph([],[],settings={"script_isolation":"off"}))
        self.assertFalse(bad["ok"])
        self.assertEqual("inherit",bad["graph"]["settings"]["script_isolation"])
        self.assertEqual(["inherit","sandboxed","allow"],schema.JSON_SCHEMA["properties"]["settings"]["properties"]["script_isolation"]["enum"])
        self.assertEqual("inherit",schema.new_graph()["settings"]["script_isolation"])
    def test_values_are_clamped(self):
        data=graph([cmd("c","echo hi",timeout=999999),node("w","wait",seconds=-5),node("f","foreach",items="a,b",max_items=10**9),node("sc","script",code="x",timeout=0)],
                   [edge("s","out","c"),edge("c","success","w"),edge("w","out","f"),edge("f","item","sc")],
                   settings={"run_timeout":1,"max_visits":10**6,"on_error":"continue","shell":"bash"},viewport={"x":"12","y":None,"zoom":99})
        g=self.check(data)["graph"]
        by={n["id"]:n["config"] for n in g["nodes"]}
        self.assertEqual(schema.LIMITS["node_timeout_max"],by["c"]["timeout"])
        self.assertEqual(0,by["w"]["seconds"])
        self.assertEqual(schema.LIMITS["foreach_items_max"],by["f"]["max_items"])
        self.assertEqual(schema.LIMITS["node_timeout_min"],by["sc"]["timeout"])
        self.assertEqual({"shell":"bash","run_timeout":10,"max_visits":2000,"on_error":"continue","script_isolation":"inherit"},g["settings"])
        self.assertEqual({"x":12,"y":0,"zoom":4},g["viewport"])
    def test_unknown_keys_are_dropped(self):
        data=graph([dict(cmd("c","echo hi",evil="x"),extra=1)],[dict(edge("s","out","c"),label="zzz")],junk=True)
        g=self.check(data)["graph"]
        self.assertEqual({"schema","settings","nodes","edges","viewport"},set(g))
        self.assertEqual({"id","type","title","x","y","config"},set(g["nodes"][1]))
        self.assertNotIn("evil",g["nodes"][1]["config"])
        self.assertEqual({"id","from","port","to"},set(g["edges"][0]))
    def test_title_is_truncated_and_bad_numbers_are_reset(self):
        data=graph([dict(cmd("c","echo hi"),title="t"*200,x="oops",y=float("nan"))],[edge("s","out","c")])
        n=self.check(data)["graph"]["nodes"][1]
        self.assertEqual(80,len(n["title"]))
        self.assertEqual((0,0),(n["x"],n["y"]))
    def test_empty_command_lines_are_dropped_and_ids_kept(self):
        data=graph([node("c","command",commands=[{"text":"  "},{"text":" id ","command_id":"7","src":"db","label":"who"},{"text":"ls","command_id":True}])],[edge("s","out","c")])
        commands=self.check(data)["graph"]["nodes"][1]["config"]["commands"]
        self.assertEqual([{"text":"id","command_id":7,"src":"db","label":"who"},{"text":"ls","command_id":None,"src":"","label":""}],commands)
    def test_script_network_flag(self):
        self.assertIs(False,schema.NODE_TYPES["script"]["defaults"]["network"])
        prop=schema.JSON_SCHEMA["$defs"]["node"]["allOf"][list(schema.NODE_TYPES).index("script")]["then"]["properties"]["config"]["properties"]["network"]
        self.assertEqual(("boolean","allow network access when sandboxed"),(prop["type"],prop["description"]))
        cases=[({}, False),({"network":True},True),({"network":"true"},True),({"network":1},True),({"network":"yes please"},False),({"network":None},False),({"network":[1]},False),({"network":0},False)]
        for extra,expected in cases:
            data=graph([node("sc","script",code="x",**extra)],[edge("s","out","sc"),edge("sc","error","s2")] if False else [edge("s","out","sc")])
            self.assertIs(expected,self.check(data)["graph"]["nodes"][1]["config"]["network"],extra)
        self.assertEqual({"language","code","branches","timeout","network"},set(self.check(graph([node("sc","script",code="x")]))["graph"]["nodes"][1]["config"]))
        for entry in schema.TEMPLATES:
            for item in entry["graph"]["nodes"]:
                if item["type"]=="script":self.assertIs(False,item["config"]["network"],entry["id"])
    def test_script_newlines_and_flags(self):
        data=graph([node("sc","script",code="a\r\nb\rc"),node("p","parse",mode="regex",pattern="a",flags="IMz")],[edge("s","out","sc"),edge("sc","out","p")])
        by={n["id"]:n["config"] for n in self.check(data)["graph"]["nodes"]}
        self.assertEqual("a\nb\nc",by["sc"]["code"])
        self.assertEqual("im",by["p"]["flags"])
    def test_port_and_host_conditions_use_boolean_ops(self):
        data=graph([decision("d",[{"name":"b","conditions":[cond("port_open","contains","80"),cond("host_up","equals","")]}])],[edge("s","out","d")])
        conditions=self.check(data)["graph"]["nodes"][1]["config"]["branches"][0]["conditions"]
        self.assertEqual(["is_true","is_true"],[c["op"] for c in conditions])
    def test_never_raises_on_garbage(self):
        for junk in(None,5,"not json","[1,2]",[],{"nodes":5},{"nodes":[None,5,"x",{}],"edges":[None,{}]},{"schema":"x","nodes":[{"id":["a"],"type":{}}],"edges":"e"},
                    {"nodes":[{"id":"a","type":"decision","config":{"branches":[None,{"name":5,"conditions":[None,{"source":[]}]}],"else":[]}}]},b"\xff"):
            result=schema.validate_graph(junk)
            self.assertFalse(result["ok"])
            self.assertIn("nodes",result["graph"])
class ErrorCodeTests(FlowSchemaBase):
    def test_structure(self):
        self.assertError("nope","structure")
        self.assertError({"schema":1,"nodes":"x","edges":[]},"structure")
        self.assertError(graph([],edges=[5]),"structure")
    def test_schema_version(self):
        self.assertError(dict(schema.new_graph(),schema=99),"schema_version")
    def test_bad_and_duplicate_ids(self):
        self.assertError(graph([cmd("bad id!","echo")]),"bad_id")
        self.assertError(graph([cmd("x"*41,"echo")]),"bad_id")
        self.assertError(graph([cmd("a","echo"),cmd("a","echo")]),"duplicate_id")
        self.assertError(graph([cmd("a","echo")],[edge("s","out","a","bad id")]),"bad_id")
        self.assertError(graph([cmd("a","echo"),cmd("b","echo")],[edge("s","out","a","e1"),edge("s","out","b","e1")]),"duplicate_id")
    def test_unknown_type(self):
        result=self.assertError(graph([node("a","teleport")]),"unknown_type")
        self.assertEqual("a",[i for i in result["errors"] if i["code"]=="unknown_type"][0]["node"])
    def test_start_count(self):
        self.assertError({"schema":1,"nodes":[cmd("a","echo")],"edges":[]},"no_start")
        result=self.assertError(graph([node("s2","start")]),"many_start")
        self.assertEqual("s2",result["errors"][0]["node"])
    def test_edges(self):
        self.assertError(graph([],[edge("s","out","ghost")]),"dangling_edge")
        self.assertError(graph([cmd("a","echo")],[edge("ghost","out","a")]),"dangling_edge")
        self.assertError(graph([cmd("a","echo")],[edge("s","success","a")]),"unknown_port")
        self.assertError(graph([cmd("a","echo")],[edge("s","out","a"),edge("a","success","s")]),"bad_edge_target")
        self.assertError(graph([node("n","comment")],[edge("s","out","n")]),"bad_edge_target")
        self.assertError(graph([cmd("a","echo")],[edge("s","out","a"),edge("a","success","a")]),"self_loop")
        self.assertError(graph([node("e","end"),cmd("a","echo")],[edge("s","out","e"),edge("e","out","a")]),"unknown_port")
    def test_an_edge_from_a_removed_branch_is_reported(self):
        data=graph([decision("d",[{"name":"yes","conditions":[cond()]}]),node("e","end")],[edge("s","out","d"),edge("d","gone","e"),edge("d","else","e")])
        self.assertError(data,"unknown_port")
    def test_limits(self):
        limits=schema.LIMITS
        self.assertError(graph([node("w%d"%i,"wait") for i in range(limits["nodes"])]),"too_many_nodes")
        self.assertError(graph([cmd("a","echo")],[edge("s","out","a","e%d"%i) for i in range(limits["edges"]+1)]),"too_many_edges")
        self.assertError(graph([cmd("a",*["echo %d"%i for i in range(limits["commands_per_node"]+1)])],[edge("s","out","a")]),"too_many_commands")
        self.assertError(graph([cmd("a","x"*(limits["command_bytes"]+1))],[edge("s","out","a")]),"command_too_long")
        self.assertError(graph([node("a","script",code="#"*(limits["script_bytes"]+1))],[edge("s","out","a")]),"script_too_large")
        self.assertError(graph([node("a","script",code="x",branches=["b%d"%i for i in range(limits["branches"]+1)])],[edge("s","out","a")]),"too_many_branches")
        self.assertError(graph([decision("d",[{"name":"b%d"%i,"conditions":[cond()]} for i in range(limits["branches"]+1)])],[edge("s","out","d")]),"too_many_branches")
        self.assertError(graph([decision("d",[{"name":"b","conditions":[cond()]*(limits["conditions"]+1)}])],[edge("s","out","d")]),"too_many_conditions")
        big=[node("sc%d"%i,"script",code="#"*60000) for i in range(10)]
        self.assertError(graph(big,[edge("s","out","sc0")]),"graph_too_large")
    def test_limits_are_exact(self):
        limits=schema.LIMITS
        ok=graph([cmd("a",*["echo %d"%i for i in range(limits["commands_per_node"])]),cmd("b","x"*limits["command_bytes"]),node("sc","script",code="#"*limits["script_bytes"])],
                 [edge("s","out","a"),edge("a","success","b"),edge("b","success","sc")])
        self.assertTrue(self.check(ok)["ok"],self.check(ok)["errors"])
        self.assertTrue(self.check(graph([node("w%d"%i,"wait") for i in range(limits["nodes"]-1)]))["ok"])
    def test_command_node(self):
        self.assertError(graph([node("a","command",commands=[])],[edge("s","out","a")]),"empty_command")
        self.assertError(graph([node("a","command",commands=[{"text":"   "}])],[edge("s","out","a")]),"empty_command")
        self.assertError(graph([cmd("a","echo",mode="chaos")],[edge("s","out","a")]),"bad_config")
    def test_script_node(self):
        self.assertError(graph([node("a","script",code="  ")],[edge("s","out","a")]),"empty_script")
        self.assertError(graph([node("a","script",code="x",language="ruby")],[edge("s","out","a")]),"bad_config")
        self.assertError(graph([node("a","script",code="x",branches=["ok","bad name"])],[edge("s","out","a")]),"bad_port_name")
        self.assertError(graph([node("a","script",code="x",branches=["a","a"])],[edge("s","out","a")]),"duplicate_port")
        self.assertError(graph([node("a","script",code="x",branches=["error"])],[edge("s","out","a")]),"duplicate_port")
    def test_decision_node(self):
        self.assertError(graph([decision("d",[])],[edge("s","out","d")]),"empty_decision")
        self.assertError(graph([decision("d",[{"name":"b","conditions":[]}])],[edge("s","out","d")]),"empty_branch")
        self.assertError(graph([decision("d",[{"name":"b","conditions":[cond()]},{"name":"b","conditions":[cond()]}])],[edge("s","out","d")]),"duplicate_port")
        self.assertError(graph([decision("d",[{"name":"else","conditions":[cond()]}])],[edge("s","out","d")]),"duplicate_port")
        self.assertError(graph([decision("d",[{"name":"b","conditions":[cond()]}],"bad name")],[edge("s","out","d")]),"bad_port_name")
        self.assertError(graph([decision("d",[{"name":"b","match":"most","conditions":[cond()]}])],[edge("s","out","d")]),"bad_config")
        for broken in(cond(source="moon"),cond(op="resembles"),cond("exit_code","gt","abc"),cond("port_open","is_true","99999"),cond("var","is_empty","",field=""),"text"):
            self.assertError(graph([decision("d",[{"name":"b","conditions":[broken]}])],[edge("s","out","d")]),"bad_condition")
    def test_invalid_regex(self):
        for broken in(cond(op="regex",value="(a+)+$"),cond(op="regex",value="(unclosed"),cond(op="not_regex",value=""),cond(op="regex",value="a"*501),
                      cond("match_count","gt","1",field="(a|aa)*"),cond("match_count","gt","1",field="")):
            self.assertError(graph([decision("d",[{"name":"b","conditions":[broken]}])],[edge("s","out","d")]),"invalid_regex")
        self.assertError(graph([node("p","parse",mode="regex",pattern="")],[edge("s","out","p")]),"invalid_regex")
        self.assertError(graph([node("p","parse",mode="regex",pattern="[z-a]")],[edge("s","out","p")]),"invalid_regex")
        self.assertError(graph([node("p","parse",mode="regex",pattern="(.*)*")],[edge("s","out","p")]),"invalid_regex")
    def test_parse_set_foreach_subchain(self):
        self.assertError(graph([node("p","parse",mode="xml")],[edge("s","out","p")]),"bad_config")
        self.assertError(graph([node("p","parse",mode="tool",tool="nessus")],[edge("s","out","p")]),"bad_config")
        self.assertError(graph([node("p","parse",mode="tool",source="$(id)")],[edge("s","out","p")]),"bad_config")
        self.assertError(graph([node("p","parse",mode="tool",assign=[{"var":"1bad","from":"x"}])],[edge("s","out","p")]),"bad_var")
        self.assertError(graph([node("p","parse",mode="tool",var="has space")],[edge("s","out","p")]),"bad_var")
        self.assertError(graph([node("v","set",assign=[{"var":"a-b","value":"1"}])],[edge("s","out","v")]),"bad_var")
        self.assertError(graph([node("f","foreach",items=" ")],[edge("s","out","f")]),"empty_items")
        self.assertError(graph([node("f","foreach",items="a",item_var="9x")],[edge("s","out","f")]),"bad_var")
        self.assertError(graph([node("f","foreach",items="a",split="tabs")],[edge("s","out","f")]),"bad_config")
        self.assertError(graph([node("x","subchain")],[edge("s","out","x")]),"subchain_unset")
    def test_other_enums(self):
        self.assertError(graph([node("o","output",action="email")],[edge("s","out","o")]),"bad_config")
        self.assertError(graph([node("o","output",severity="apocalyptic")],[edge("s","out","o")]),"bad_config")
        self.assertError(graph([node("e","end",status="maybe")],[edge("s","out","e")]),"bad_config")
        self.assertError(graph([],settings={"on_error":"explode"}),"bad_config")
        self.assertError({"schema":1,"nodes":[node("s","start",trigger="cron")],"edges":[]},"bad_config")
class WarningTests(FlowSchemaBase):
    def warnings(self,data):
        result=self.check(data)
        self.assertTrue(result["ok"],result["errors"])
        return result["warnings"]
    def test_unreachable_node_but_not_comments(self):
        found=self.warnings(graph([node("w","wait"),node("note","comment")]))
        self.assertEqual([("unreachable","w")],[(i["code"],i["node"]) for i in found])
    def test_unconnected_optional_ports_only(self):
        data=graph([cmd("c","echo"),node("sc","script",code="x"),decision("d",[{"name":"yes","conditions":[cond()]}],"no"),node("p","parse",mode="tool")],
                   [edge("s","out","c"),edge("c","success","sc"),edge("sc","out","d"),edge("d","yes","p")])
        found=[(i["node"],i["message"]) for i in self.warnings(data) if i["code"]=="port_unconnected"]
        self.assertEqual(["c","sc","d"],[n for n,_ in found])
        self.assertIn("'fail'",found[0][1]);self.assertIn("'error'",found[1][1]);self.assertIn("'no'",found[2][1])
    def test_raw_value_in_a_command(self):
        found=self.warnings(graph([cmd("c","echo ${raw:x}","echo ${x}")],[edge("s","out","c"),edge("c","fail","s2")] if False else [edge("s","out","c")]))
        self.assertEqual(1,codes(found).count("raw_in_command"))
    def test_destructive_command(self):
        found=self.warnings(graph([cmd("c","rm -rf /tmp/x","sudo id","echo fine")],[edge("s","out","c")]))
        self.assertEqual(2,codes(found).count("destructive_command"))
    def test_duplicate_edge_is_dropped(self):
        result=self.check(graph([cmd("c","echo")],[edge("s","out","c"),edge("s","out","c")]))
        self.assertIn("duplicate_edge",codes(result["warnings"]))
        self.assertEqual(1,len(result["graph"]["edges"]))
class PortTests(FlowSchemaBase):
    def test_static_ports(self):
        expected={"start":(False,["out"]),"command":(True,["success","fail"]),"parse":(True,["out","nomatch"]),"set":(True,["out"]),
                  "foreach":(True,["item","done"]),"wait":(True,["out"]),"approval":(True,["approved","rejected"]),"output":(True,["out"]),
                  "subchain":(True,["success","fail"]),"end":(True,[]),"comment":(False,[])}
        for node_type,(has_input,out) in expected.items():
            self.assertEqual({"in":has_input,"out":out},schema.node_ports({"type":node_type,"config":{}}),node_type)
            self.assertEqual(out,schema.NODE_TYPES[node_type]["ports"])
    def test_dynamic_ports(self):
        self.assertEqual("dynamic",schema.NODE_TYPES["script"]["ports"])
        self.assertEqual("dynamic",schema.NODE_TYPES["decision"]["ports"])
        self.assertEqual(["alive","down","error"],schema.node_ports(node("x","script",branches=["alive","down"]))["out"])
        self.assertEqual(["out","error"],schema.node_ports({"type":"script"})["out"])
        self.assertEqual(["a","b","other"],schema.node_ports(decision("d",[{"name":"a"},{"name":"b"}],"other"))["out"])
        self.assertEqual(["else"],schema.node_ports({"type":"decision","config":{}})["out"])
    def test_tolerates_bad_input(self):
        for junk in(None,5,{},{"type":"nope"},{"type":["x"]},{"type":"script","config":{"branches":[5,None,"ok","bad name","ok","error"]}}):
            ports=schema.node_ports(junk)
            self.assertIsInstance(ports["out"],list)
        self.assertEqual(["ok","error"],schema.node_ports({"type":"script","config":{"branches":[5,None,"ok","bad name","ok","error"]}})["out"])
    def test_node_type_table(self):
        self.assertEqual({"start","command","script","decision","parse","set","foreach","wait","approval","output","subchain","end","comment"},set(flow_nodes.LEGACY_TYPES))
        self.assertEqual(set(flow_nodes.SPECS),set(schema.NODE_TYPES))
        self.assertEqual(list(flow_nodes.LEGACY_TYPES),list(schema.NODE_TYPES)[:13])
        for spec in schema.NODE_TYPES.values():
            self.assertEqual({"label","category","ports","defaults","description"},set(spec))
        json.dumps(schema.NODE_TYPES);json.dumps(schema.LIMITS);json.dumps(schema.JSON_SCHEMA)
        self.assertEqual("https://json-schema.org/draft/2020-12/schema",schema.JSON_SCHEMA["$schema"])
        self.assertEqual(set(schema.NODE_TYPES),set(schema.JSON_SCHEMA["$defs"]["node"]["properties"]["type"]["enum"]))
        self.assertEqual(200,schema.LIMITS["nodes"]);self.assertEqual(400,schema.LIMITS["edges"])
class LinearTests(FlowSchemaBase):
    STEPS=[{"command_id":4,"command_src":"db","label":"Ping","command":"ping -c 2 {IPv4}"},
           {"command_id":None,"command_src":"","label":"","command":{"command":"nmap {IPv4}","title":"Scan"}},
           {"command_id":9,"command_src":"user","label":"","command":"   "},
           {"command_id":"12","command_src":"db","label":"","command":"whoami"}]
    def test_linear_to_graph(self):
        g=schema.linear_to_graph("Recon",self.STEPS)
        result=self.check(g)
        self.assertTrue(result["ok"],result["errors"])
        self.assertEqual(g["nodes"],result["graph"]["nodes"])
        self.assertEqual(g["edges"],result["graph"]["edges"])
        self.assertEqual(["start","command","command","command"],[n["type"] for n in g["nodes"]])
        self.assertEqual(["Start","Ping","Scan","whoami"],[n["title"] for n in g["nodes"]])
        self.assertEqual([("n1","out","n2"),("n2","success","n3"),("n3","success","n4")],[(e["from"],e["port"],e["to"]) for e in g["edges"]])
        xs=[n["x"] for n in g["nodes"]]
        self.assertEqual([40,340,640,940],xs)   # 300 px apart: the editor draws nodes 240 px wide
        self.assertEqual(sorted(xs),xs);self.assertEqual(1,len({n["y"] for n in g["nodes"]}))
    def test_round_trip_through_graph_commands(self):
        g=schema.linear_to_graph("Recon",self.STEPS)
        self.assertTrue(schema.graph_is_linear(g))
        rows=schema.graph_commands(g)
        self.assertEqual(["ping -c 2 {IPv4}","nmap {IPv4}","whoami"],[r["text"] for r in rows])
        self.assertEqual([(4,"db"),(None,""),(12,"db")],[(r["command_id"],r["src"]) for r in rows])
        self.assertEqual({"node","title","index","text","command_id","src"},set(rows[0]))
        again=schema.linear_to_graph("Recon",[{"command_id":r["command_id"],"command_src":r["src"],"label":r["title"],"command":r["text"]} for r in rows])
        self.assertEqual(rows,schema.graph_commands(again))
        self.assertEqual((g["edges"],[(n["id"],n["title"],n["x"],n["y"]) for n in g["nodes"]]),(again["edges"],[(n["id"],n["title"],n["x"],n["y"]) for n in again["nodes"]]))
    def test_empty_chain(self):
        g=schema.linear_to_graph("Empty",[])
        self.assertEqual(schema.new_graph(),g)
        self.assertTrue(schema.graph_is_linear(g))
        self.assertEqual(schema.new_graph(),schema.linear_to_graph("x",None))
    def test_graph_is_linear_false_cases(self):
        base=schema.linear_to_graph("x",self.STEPS)
        with_note=copy.deepcopy(base);with_note["nodes"].append(node("note","comment"))
        self.assertTrue(schema.graph_is_linear(with_note))
        branch=copy.deepcopy(base);branch["edges"].append({"id":"e9","from":"n2","port":"fail","to":"n4"})
        self.assertFalse(schema.graph_is_linear(branch))
        two=copy.deepcopy(base);two["nodes"][1]["config"]["commands"].append({"text":"id"})
        self.assertFalse(schema.graph_is_linear(two))
        loose=copy.deepcopy(base);loose["edges"].pop()
        self.assertFalse(schema.graph_is_linear(loose))
        other=copy.deepcopy(base);other["nodes"].append(node("w","wait"))
        self.assertFalse(schema.graph_is_linear(other))
        for template in schema.TEMPLATES:self.assertFalse(schema.graph_is_linear(template["graph"]))
        for junk in(None,{},{"nodes":5,"edges":[]}):self.assertFalse(schema.graph_is_linear(junk))
    def test_graph_commands_and_scripts_order(self):
        g=graph([cmd("b","two","three"),node("sc","script",language="bash",code="echo"),cmd("a","one")])
        self.assertEqual([("b",0,"two"),("b",1,"three"),("a",0,"one")],[(r["node"],r["index"],r["text"]) for r in schema.graph_commands(g)])
        self.assertEqual([{"node":"sc","title":"Script","language":"bash","code":"echo"}],schema.graph_scripts(g))
        self.assertEqual([],schema.graph_commands(None));self.assertEqual([],schema.graph_scripts({"nodes":"x"}))
class TemplateTests(FlowSchemaBase):
    def test_required_templates_exist(self):
        ids=[t["id"] for t in schema.TEMPLATES]
        for wanted in("host-alive-portscan-web","smb-null-session","script-demo"):self.assertIn(wanted,ids)
        self.assertEqual(len(ids),len(set(ids)))
    def test_every_template_validates_cleanly(self):
        for entry in schema.TEMPLATES:
            self.assertEqual({"id","name","description","graph"},set(entry))
            result=self.check(entry["graph"])
            self.assertTrue(result["ok"],(entry["id"],result["errors"]))
            self.assertEqual([],result["warnings"],entry["id"])
            self.assertEqual(entry["graph"],result["graph"],entry["id"])
    def test_template_returns_a_deep_copy(self):
        first=schema.template("script-demo")
        first["nodes"][0]["title"]="changed"
        self.assertEqual("Start",schema.template("script-demo")["nodes"][0]["title"])
        self.assertIsNone(schema.template("nope"))
    def test_template_shapes(self):
        types=lambda tid:[n["type"] for n in schema.template(tid)["nodes"]]
        host=types("host-alive-portscan-web")
        self.assertEqual(2,host.count("decision"));self.assertIn("parse",host);self.assertGreaterEqual(host.count("command"),3)
        texts=" ".join(r["text"] for r in schema.graph_commands(schema.template("host-alive-portscan-web")))
        self.assertIn("ping",texts);self.assertIn("nmap",texts);self.assertIn("{IPv4}",texts)
        smb=" ".join(r["text"] for r in schema.graph_commands(schema.template("smb-null-session")))
        self.assertIn("smbclient -N -L",smb)
        self.assertIn("note_append",[n["config"].get("action") for n in schema.template("smb-null-session")["nodes"]])
        scripts=schema.graph_scripts(schema.template("script-demo"))
        self.assertEqual(1,len(scripts));self.assertIn("LOYA_INPUT_FILE",scripts[0]["code"])
class BundleTests(FlowSchemaBase):
    def test_export_then_import(self):
        g=schema.template("smb-null-session")
        bundle=schema.export_bundle(" SMB ","/smb",g)
        self.assertEqual({"loya_chain","name","caller","graph","exported_at"},set(bundle))
        self.assertEqual((1,"SMB","/smb"),(bundle["loya_chain"],bundle["name"],bundle["caller"]))
        self.assertRegex(bundle["exported_at"],r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        for payload in(bundle,json.dumps(bundle),json.dumps(bundle).encode("utf-8"),"\ufeff"+json.dumps(bundle)):
            self.assertEqual({"name":"SMB","caller":"/smb","graph":g},schema.import_bundle(payload))
    def test_import_accepts_a_bare_graph(self):
        self.assertEqual({"name":"","caller":"","graph":schema.new_graph()},schema.import_bundle(json.dumps(schema.new_graph())))
    def test_import_normalizes(self):
        bundle={"loya_chain":1,"name":"x","graph":{"schema":1,"nodes":[{"id":"s","type":"start","junk":1}],"edges":[]}}
        self.assertEqual({"id","type","title","x","y","config"},set(schema.import_bundle(bundle)["graph"]["nodes"][0]))
    def test_import_rejects_bad_input(self):
        cases=[("not json at all","not valid JSON"),("[1,2]","not a chain export"),('{"a":1}',"loya_chain"),(b"\xff\xfe\x00","UTF-8"),(5,"not a chain export"),
               ({"loya_chain":2,"graph":schema.new_graph()},"newer version"),({"loya_chain":"x","graph":schema.new_graph()},"version"),
               ({"loya_chain":1,"graph":"x"},"no diagram"),({"loya_chain":1,"graph":{"schema":1,"nodes":[],"edges":[]}},"not valid"),
               ("x"*(schema.LIMITS["graph_bytes"]*2+10),"too large")]
        for payload,fragment in cases:
            with self.assertRaises(ValueError) as caught:schema.import_bundle(payload)
            self.assertIn(fragment,str(caught.exception))
    def test_import_reports_the_graph_problem(self):
        bad=graph([cmd("a","echo")],[edge("s","nope","a")])
        with self.assertRaises(ValueError) as caught:schema.import_bundle({"loya_chain":1,"graph":bad})
        self.assertIn("no output called",str(caught.exception))
if __name__=="__main__":unittest.main()
