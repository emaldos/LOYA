"""Chain Diagrams node catalog (Cores/Services/flow_nodes.py): the catalog and its generated JS copy, the generic field-driven
validation, the schema-1 migration, the math evaluator, the scan parsers and every field-driven node type run through a
real FlowRun; plus the plan's `actions`, the AI gate (force_ask) and the MCP tools of Cores/Bridge/mcp_flow_tools.py."""
import copy,http.server,json,os,shutil,sys,tempfile,threading,time,unittest
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from _isolate import IsolatedData
from _flow_helpers import WINDOWS,node,cmd,graph,set_live_target,wait_until
from Cores import common_db
from Cores.Bridge import api as bridge_api
from Cores.Bridge import mcp_flow_tools as flow_tools
from Cores.Services import ai_service as ai
from Cores.Services import ai_chat_service as chat
from Cores.Services import flow_engine as engine
from Cores.Services import flow_nodes as nodes
from Cores.Services import flow_rules as rules
from Cores.Services import flow_schema as schema
from Cores.Services import flow_service as flows
from Cores.Services import flow_store as store
from Cores.Services import security_service as security
from Cores.Services import terminal_service as terminal
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEW_ICONS={"flow-filter","flow-merge","flow-switch","flow-math","flow-globe","flow-json","flow-template","flow-sort","flow-scan","flow-log","flow-file-in",
           "flow-file-out","flow-note","flow-split","flow-join","flow-regex","flow-list","flow-map","flow-fields","flow-result","flow-finding","flow-count"}
# The contract (CONTRACT.md "Node types"): type -> (category, icon, ports, defaults). The canvas and the inspector are built on it.
CONTRACT={
    "input_target":("input","target",["out","missing"],{"source":"live","name":"","var":"tgt"}),
    "input_text":("input","flow-list",["out"],{"text":"","format":"text","var":"input"}),
    "input_file":("input","flow-file-in",["out","error"],{"path":"","format":"text","max_kb":1024,"var":"file"}),
    "http":("action","flow-globe",["success","fail"],{"method":"GET","url":"","headers":[],"body":"","timeout":30,"verify_tls":True,"follow_redirects":True,"max_kb":512,"var":"response"}),
    "switch":("logic","flow-switch",[],{"value":"${last.stdout}","cases":[{"name":"case1","op":"equals","value":""}],"default":"default","ci":True}),
    "merge":("logic","flow-merge",["out"],{"mode":"any","collect":"parsed","var":"merged"}),
    "math":("math","flow-math",["out","error"],{"expr":"","var":"result","decimals":-1}),
    "template":("transform","flow-template",["out"],{"template":"","var":"text"}),
    "fields":("transform","flow-fields",["out"],{"source":"${last.parsed}","ops":[{"op":"set","field":"","value":""}],"var":"data"}),
    "map":("transform","flow-map",["out"],{"source":"","template":"${item}","var":"mapped"}),
    "filter":("transform","flow-filter",["out","empty"],{"source":"","match":"all","conditions":[{"field":"","op":"contains","value":""}],"ci":True,"var":"filtered"}),
    "split":("transform","flow-split",["out"],{"source":"${last.stdout}","mode":"lines","separator":"","trim":True,"drop_empty":True,"var":"items"}),
    "join":("transform","flow-join",["out"],{"source":"","separator":"\n","var":"joined"}),
    "regex":("transform","flow-regex",["out","nomatch"],{"source":"${last.stdout}","pattern":"","flags":"i","mode":"all","group":"0","var":"matches"}),
    "json":("transform","flow-json",["out","error"],{"action":"parse","source":"${last.stdout}","path":"","indent":2,"var":"json"}),
    "collection":("analysis","flow-sort",["out"],{"op":"count","source":"","field":"","order":"asc","numeric":False,"limit":10,"var":"result"}),
    "scan_parse":("analysis","flow-scan",["out","nomatch"],{"format":"auto","source":"${last.stdout}","var":"scan"}),
    "note":("app","flow-note",["out"],{"action":"upsert","note_name":"","title":"","content":"${last.stdout}"}),
    "finding":("app","flow-finding",["out"],{"report":"","title":"","severity":"info","description":"${last.stdout}"}),
    "report_create":("app","report",["out"],{"name":"","var":"report_id"}),
    "target_update":("app","crosshair",["out","missing"],{"target":"live","name":"","key":"","value":"","create_missing":False}),
    "cve_lookup":("app","bug",["found","none"],{"query":"","limit":5,"var":"cves"}),
    "live_target":("app","target",["out","missing"],{"name":""}),
    "file_write":("output","flow-file-out",["out","error"],{"path":"","content":"${last.stdout}","mode":"overwrite"}),
    "result":("output","flow-result",["out"],{"label":"","value":"${last.stdout}"}),
    "log":("notify","flow-log",["out"],{"level":"info","message":""}),
}
LEGACY_CATEGORY={"start":"input","command":"action","script":"action","subchain":"action","decision":"logic","approval":"logic","foreach":"logic","wait":"logic","end":"logic",
                 "parse":"transform","set":"math","output":"output","comment":"note"}
def check(nodes_,edges=(),schema_version=2):
    """validate_graph for start + nodes; edges as "a.port>b"."""
    rows=[]
    for index,spec in enumerate(edges):
        left,target=spec.split(">");source,port=left.split(".")
        rows.append({"id":"e%d"%(index+1),"from":source,"port":port,"to":target})
    return schema.validate_graph({"schema":schema_version,"nodes":[node("start","start")]+list(nodes_),"edges":rows})
def codes(issues):
    return [issue["code"] for issue in issues]
def chain(*steps):
    """Nodes joined in a row through their first output: start -> a -> b ..."""
    edges=[];previous="start";port="out"
    for item in steps:
        edges.append("%s.%s>%s"%(previous,port,item["id"]))
        previous=item["id"];port=schema.node_ports(item)["out"][0] if schema.node_ports(item)["out"] else "out"
    return graph(list(steps),edges)
class Base(unittest.TestCase):
    def setUp(self):
        self.iso=IsolatedData();self.iso.start()
        self.started=[]
        self.tmp=tempfile.mkdtemp(prefix="loya_flow_nodes_")
    def tearDown(self):
        common_db.set_locked(False)
        for run in self.started:
            run.stop("test teardown");run.finished.wait(10)
        flows.stop_all("test teardown")
        for run in list(engine._runs.values()):run.finished.wait(10)
        engine._runs.clear();del engine._unsaved[:]
        terminal.clear_batch_output()
        shutil.rmtree(self.tmp,ignore_errors=True)
        self.iso.stop()
    def run_graph(self,g,timeout=40,**kw):
        kw.setdefault("name","Test chain")
        run=engine.start_run(g,**kw)
        self.started.append(run)
        self.assertTrue(run.finished.wait(timeout),"the run did not finish: %r"%run.status()["state"])
        return run.status()
    def run_chain(self,*steps,**kw):
        return self.run_graph(chain(*steps),**kw)
    def states(self,status):
        return {k:v["state"] for k,v in status["nodes"].items()}
    def audit(self,event):
        return [e["detail"] for e in security.list_audit_events(500) if e["event"]==event]
    def texts(self,status):
        return [e["text"] for e in status["events"]]
# ---------------------------------------------------------------- the catalog
class CatalogTests(unittest.TestCase):
    def test_categories_in_contract_order(self):
        self.assertEqual(["input","action","logic","math","transform","analysis","app","output","notify","note"],[c["id"] for c in nodes.CATEGORIES])
        self.assertEqual(["Triggers & inputs","Actions","Logic","Calculations & variables","Data transform","Data analysis","App","Outputs","Notifications & log","Notes"],[c["label"] for c in nodes.CATEGORIES])
        for category in nodes.CATEGORIES:self.assertEqual({"id","label","hint"},set(category))
    def test_every_contract_type_has_its_ports_defaults_category_and_icon(self):
        self.assertEqual(set(CONTRACT),set(nodes.FIELD_TYPES))
        self.assertEqual(set(LEGACY_CATEGORY),set(nodes.LEGACY_TYPES))
        self.assertEqual(39,len(nodes.SPECS))
        for name,(category,icon,ports,defaults) in CONTRACT.items():
            spec=nodes.SPECS[name]
            self.assertEqual((category,category,icon,ports,defaults,True),(spec["category"],spec["color"],spec["icon"],spec["ports"],spec["defaults"],spec["input"]),name)
            self.assertEqual([f["key"] for f in spec["fields"]],list(defaults),"%s: one field per default key, in order"%name)
            self.assertTrue(spec["label"] and spec["description"] and spec["keywords"],name)
        for name,category in LEGACY_CATEGORY.items():
            spec=nodes.SPECS[name]
            self.assertEqual((category,category),(spec["category"],spec["color"]),name)
            self.assertNotIn("fields",spec,"legacy types keep their hand-written forms")
            self.assertEqual({"label","category","icon","color","input","ports","defaults","description","keywords"},set(spec),name)
        self.assertEqual({"start","comment"},{name for name,spec in nodes.SPECS.items() if not spec["input"]})
        self.assertEqual("dynamic",nodes.SPECS["script"]["ports"]);self.assertEqual("dynamic",nodes.SPECS["decision"]["ports"])
        self.assertEqual({"rows":"cases","name":"name","fixed_key":"default"},nodes.SPECS["switch"]["dynamic"])
    def test_tones_fail_ports_and_icons(self):
        known={os.path.splitext(name)[0] for name in os.listdir(os.path.join(ROOT,"Assets","icons"))}|NEW_ICONS
        tones={"input_target":{"missing":"neg"},"input_file":{"error":"neg"},"http":{"success":"pos","fail":"neg"},"switch":{"default":"alt"},"math":{"error":"neg"},
               "filter":{"empty":"neg"},"regex":{"nomatch":"neg"},"json":{"error":"neg"},"scan_parse":{"nomatch":"neg"},"target_update":{"missing":"neg"},
               "cve_lookup":{"found":"pos","none":"neg"},"live_target":{"missing":"neg"},"file_write":{"error":"neg"}}
        fail={"input_file":"error","http":"fail","math":"error","json":"error","file_write":"error"}
        for name,spec in nodes.SPECS.items():
            self.assertIn(spec["icon"],known,name)
            self.assertEqual(tones.get(name,{}),spec.get("tones",{}),name)
            self.assertEqual(fail.get(name,""),nodes.fail_port(name),name)
            if nodes.fail_port(name):self.assertIn(nodes.fail_port(name),spec["ports"])
        for preset in nodes.PRESETS:self.assertIn(preset["icon"],known,preset["id"])
    def test_field_specs_are_well_formed(self):
        kinds={"text","textarea","code","number","bool","select","var","port","rows"}
        allowed={"key","label","type","help","placeholder","required","options","min","max","integer","max_chars","show_if","rows","max_rows","row_label","suggest","regex","flags_key"}
        for name in nodes.FIELD_TYPES:
            spec=nodes.SPECS[name];keys=[f["key"] for f in spec["fields"]]
            for field in spec["fields"]:
                self.assertIn(field["type"],kinds,name);self.assertLessEqual(set(field),allowed,"%s.%s"%(name,field["key"]))
                if field["type"]=="select":
                    self.assertTrue(all(set(o)=={"value","label"} for o in field["options"]))
                    self.assertIn(spec["defaults"][field["key"]],[o["value"] for o in field["options"]],"%s.%s default"%(name,field["key"]))
                if field["type"]=="number":self.assertTrue(field["min"]<=spec["defaults"][field["key"]]<=field["max"],"%s.%s"%(name,field["key"]))
                if field["type"]=="rows":
                    for sub in field["rows"]:self.assertIn(sub["type"],{"text","select","number","bool","var","port"},"%s.%s.%s"%(name,field["key"],sub["key"]))
                    for row in spec["defaults"][field["key"]]:self.assertEqual({s["key"] for s in field["rows"]},set(row))
                for controller,values in (field.get("show_if") or {}).items():
                    self.assertLess(keys.index(controller),keys.index(field["key"]),"%s: %s must come before %s"%(name,controller,field["key"]))
                    self.assertLessEqual(set(values),{o["value"] for o in next(f for f in spec["fields"] if f["key"]==controller)["options"]})
                if field.get("suggest"):self.assertIn(field["suggest"],{"notes","reports","targets","chains","vars"})
            for key in __import__("re").findall(r"\{(\w+)\}",spec.get("summary","")):self.assertIn(key,spec["defaults"],"%s summary"%name)
    def test_presets_and_hotbar(self):
        wanted={"if","stop_fail","delay","loop","python_script","bash_script","powershell_script","saved_command","notify","evidence","note_append","count","dedupe","sort","group_by","sum",
                "nmap_xml","nmap_grep","json_parse","json_format","regex_ips","http_get","http_post"}
        ids=[p["id"] for p in nodes.PRESETS]
        self.assertLessEqual(wanted,set(ids));self.assertEqual(len(ids),len(set(ids)))
        self.assertFalse(set(ids)&set(nodes.SPECS),"a preset id may not shadow a node type (hot bar pins use both)")
        categories={c["id"] for c in nodes.CATEGORIES}
        for preset in nodes.PRESETS:
            self.assertEqual({"id","type","label","description","category","icon","keywords","config","title"},set(preset))
            self.assertIn(preset["type"],nodes.SPECS);self.assertIn(preset["category"],categories)
            self.assertLessEqual(set(preset["config"]),set(nodes.SPECS[preset["type"]]["defaults"]),preset["id"])
        by_id={p["id"]:p for p in nodes.PRESETS}
        self.assertEqual(("decision","end","wait","foreach","script","command","output","output","note"),tuple(by_id[k]["type"] for k in ("if","stop_fail","delay","loop","bash_script","saved_command","notify","evidence","note_append")))
        self.assertEqual("fail",by_id["stop_fail"]["config"]["status"]);self.assertEqual("evidence",by_id["evidence"]["config"]["action"])
        rules.check_regex(by_id["regex_ips"]["config"]["pattern"],"")
        self.assertEqual(["10.0.0.1","192.168.1.20"],rules.regex_findall(by_id["regex_ips"]["config"]["pattern"],"a 10.0.0.1 b 192.168.1.20 c"))
        self.assertEqual(["command","decision","script","http","scan_parse","foreach","set","output","note"],nodes.HOTBAR)
        self.assertLessEqual(set(nodes.HOTBAR),set(nodes.catalog_ids()))
    def test_operator_and_severity_lists_agree_with_the_engine(self):
        self.assertEqual(tuple(schema.OPS),tuple(nodes.OPS));self.assertEqual(tuple(rules.OPS),tuple(nodes.OPS))
        self.assertEqual(tuple(schema.SEVERITIES),tuple(nodes.SEVERITIES))
        self.assertEqual(schema.PORT_RE.pattern,nodes.PORT_RE.pattern);self.assertEqual(schema.VAR_RE.pattern,nodes.VAR_RE.pattern)
        self.assertLessEqual(nodes.REGEX_MAX+2,rules.MAX_REGEX_CHARS)
        op_field=next(f for f in nodes.SPECS["switch"]["fields"] if f["key"]=="cases")["rows"][1]
        self.assertEqual(list(nodes.OPS),[o["value"] for o in op_field["options"]])
    def test_flow_catalog_shape_and_the_generated_file_is_fresh(self):
        catalog=nodes.flow_catalog(schema.SCHEMA_VERSION)
        self.assertEqual(["schema","categories","types","presets","hotbar"],list(catalog))
        self.assertEqual(2,catalog["schema"]);self.assertEqual(list(nodes.SPECS),list(catalog["types"]))
        for spec in catalog["types"].values():self.assertNotIn("guide",spec)
        json.dumps(catalog)
        sys.path.insert(0,os.path.join(ROOT,"tools"))
        try:import gen_flow_catalog as gen
        finally:sys.path.remove(os.path.join(ROOT,"tools"))
        text=gen.render()
        with open(gen.OUTPUT,"r",encoding="utf-8",newline="") as handle:on_disk=handle.read()
        self.assertEqual(text,on_disk,"UI/js/components/flow-catalog.js is stale: run python tools/gen_flow_catalog.py")
        lines=text.split("\n")
        self.assertEqual(4,len(lines));self.assertEqual("",lines[3]);self.assertNotIn("\r",text)
        self.assertEqual("// GENERATED by tools/gen_flow_catalog.py from Cores/Services/flow_nodes.py - do not edit by hand.",lines[0])
        self.assertTrue(lines[1].startswith("const FLOW_CATALOG={"));self.assertTrue(lines[1].isascii())
        self.assertEqual('if(typeof module!=="undefined"&&module.exports)module.exports={FLOW_CATALOG}',lines[2])
        self.assertEqual(catalog,json.loads(lines[1][len("const FLOW_CATALOG="):]))
        self.assertEqual(0,gen.main(["--check"]))
    def test_node_types_table_and_json_schema_cover_every_type(self):
        self.assertEqual(list(nodes.SPECS),list(schema.NODE_TYPES))
        for name,spec in schema.NODE_TYPES.items():
            self.assertEqual({"label","category","ports","defaults","description"},set(spec))
            self.assertEqual(nodes.SPECS[name]["defaults"],spec["defaults"])
        self.assertEqual(set(nodes.SPECS),set(schema._CONFIG))
        variants=schema.JSON_SCHEMA["$defs"]["node"]["allOf"]
        self.assertEqual(list(nodes.SPECS),[v["if"]["properties"]["type"]["const"] for v in variants])
        http=variants[list(nodes.SPECS).index("http")]["then"]["properties"]["config"]["properties"]
        self.assertEqual(set(CONTRACT["http"][3]),set(http))
        self.assertEqual(list(nodes.HTTP_METHODS),http["method"]["enum"]);self.assertEqual({"type":"integer","minimum":1,"maximum":300},http["timeout"])
        self.assertEqual([1,2],schema.JSON_SCHEMA["properties"]["schema"]["enum"])
    def test_service_catalog_and_hotbar_prefs(self):
        iso=IsolatedData();iso.start()
        try:
            cat=flows.catalog()
            for key in ("schema","node_types","limits","templates","script_templates","languages","ops","sources","parsers","shells","output_actions","severities","categories","types","presets","hotbar"):self.assertIn(key,cat)
            self.assertEqual(nodes.flow_catalog(2)["types"],cat["types"]);self.assertEqual(nodes.HOTBAR,cat["hotbar"])
            json.dumps(cat)
            self.assertEqual(nodes.HOTBAR,flows.prefs_get()["hotbar"])
            out=flows.prefs_set({"hotbar":["http","if","http","nope",5,"math"]})
            self.assertEqual(["http","if","math"],out["hotbar"]);self.assertEqual(out,flows.prefs_get())
            self.assertEqual(12,len(flows.prefs_set({"hotbar":list(nodes.SPECS)})["hotbar"]))
            self.assertEqual([],flows.prefs_set({"hotbar":[]})["hotbar"])               # the user may empty the bar
            self.assertEqual([],flows.prefs_set({"snap":False})["hotbar"])               # another pref leaves the pins alone
            self.assertEqual(nodes.HOTBAR,flows._clean_prefs({"hotbar":"junk"})["hotbar"])
        finally:iso.stop()
# ---------------------------------------------------------------- validation
GOOD=[
    node("it","input_target"),node("itx","input_text",text="a\nb",format="lines"),node("if","input_file",path="~/hosts.txt"),
    node("h","http",url="https://{IPv4}/x",headers=[{"name":"X-A","value":"1"}]),node("sw","switch",value="${x}",cases=[{"name":"one","op":"equals","value":"1"},{"name":"big","op":"gt","value":"5"}],default="other"),
    node("mg","merge",mode="all"),node("m","math",expr="(a+1)*2"),node("t","template",template="x ${a}"),node("f","fields",ops=[{"op":"set","field":"a","value":"1"}]),
    node("mp","map",source="${xs}"),node("fl","filter",source="${xs}",conditions=[{"field":"port","op":"regex","value":"^80"}]),node("sp","split",mode="regex",separator=r"\s*;\s*"),
    node("j","join",source="${xs}",separator=", "),node("rx","regex",pattern=r"(?P<port>\d+)/tcp",group="port"),node("js","json",action="get",path="a[0].b"),
    node("c","collection",op="sort",source="${xs}",field="port",order="desc",numeric=True),node("sc","scan_parse",format="nmap_xml"),node("n","note",note_name="N"),
    node("fd","finding",title="T",severity="high"),node("rc","report_create",name="R"),node("tu","target_update",key="Port",value="80"),node("cv","cve_lookup",query="openssh 8.2"),
    node("lt","live_target",name="web01"),node("fw","file_write",path="/tmp/out.txt",mode="append"),node("r","result",label="x"),node("lg","log",message="hi",level="warn"),
]
class ValidationTests(unittest.TestCase):
    def one(self,node_type,**config):
        return check([node("x",node_type,**config)],["start.out>x"])
    def cfg(self,node_type,**config):
        return self.one(node_type,**config)["graph"]["nodes"][1]["config"]
    def test_every_field_driven_type_in_one_valid_graph(self):
        self.assertEqual(set(nodes.FIELD_TYPES),{n["type"] for n in GOOD})
        edges=["start.out>"+GOOD[0]["id"]]
        for left,right in zip(GOOD,GOOD[1:]):
            for port in schema.node_ports(left)["out"]:edges.append("%s.%s>%s"%(left["id"],port,right["id"]))
        result=check(GOOD,edges)
        self.assertTrue(result["ok"],result["errors"])
        self.assertEqual([],result["warnings"])
        again=schema.validate_graph(result["graph"])
        self.assertEqual(result["graph"],again["graph"],"normalizing twice changes nothing")
        for item in result["graph"]["nodes"][1:]:self.assertEqual(list(nodes.SPECS[item["type"]]["defaults"]),list(item["config"]),item["type"])
    def test_defaults_fill_in_and_values_are_coerced(self):
        self.assertEqual(CONTRACT["merge"][3],self.cfg("merge"))
        cfg=self.cfg("http",url=" https://x/ ",timeout="9999",max_kb=0,verify_tls="no",follow_redirects=1,method="POST",junk=1)
        self.assertEqual(("https://x/",300,1,False,True,"POST"),(cfg["url"],cfg["timeout"],cfg["max_kb"],cfg["verify_tls"],cfg["follow_redirects"],cfg["method"]))
        self.assertNotIn("junk",cfg)
        self.assertEqual(12,self.cfg("math",expr="1",decimals=99)["decimals"]);self.assertEqual(-1,self.cfg("math",expr="1",decimals="x")["decimals"])
        self.assertEqual("ims",self.cfg("regex",pattern="a",flags="S-i,M q")["flags"])
        self.assertEqual("a b",self.cfg("report_create",name="a\nb")["name"])          # a one-line field holds one line
        self.assertEqual("a\nb",self.cfg("template",template="a\r\nb")["template"])    # a textarea keeps its lines (LF)
        self.assertEqual("",self.cfg("merge",var="")["var"])                           # no variable is allowed
    def test_required_fields(self):
        for node_type,config,label in (("http",{},"URL"),("math",{},"Expression"),("regex",{},"Pattern"),("input_file",{},"File path"),("file_write",{},"File path"),("map",{},"List"),
                                       ("filter",{},"List"),("join",{},"List"),("collection",{},"List"),("report_create",{"name":"  "},"Report title"),("target_update",{},"Parameter"),
                                       ("cve_lookup",{},"Search"),("live_target",{},"Target name"),("log",{},"Message"),("split",{"mode":"separator"},"Separator"),("json",{"action":"get"},"Path"),
                                       ("input_target",{"source":"name"},"Target name"),("target_update",{"key":"k","target":"name"},"Target name")):
            result=self.one(node_type,**config)
            issue=next((i for i in result["errors"] if i["code"]=="empty_field"),None)
            self.assertIsNotNone(issue,"%s %r: %r"%(node_type,config,result["errors"]))
            self.assertEqual(("x",label+" is empty."),(issue["node"],issue["message"]))
        # show_if: a field that is not shown is not required
        for node_type,config in (("input_target",{"source":"live"}),("split",{"mode":"lines"}),("json",{"action":"parse"}),("target_update",{"key":"k","target":"live"})):
            self.assertTrue(self.one(node_type,**config)["ok"],node_type)
        self.assertIn("Cases: add at least one case.",[i["message"] for i in self.one("switch",cases=[])["errors"]])
        self.assertIn("Changes, change 1: Field is empty.",[i["message"] for i in self.one("fields")["errors"]])
        self.assertIn("Headers, header 2: Name is empty.",[i["message"] for i in self.one("http",url="http://x/",headers=[{"name":"A","value":""},{"name":"","value":"v"}])["errors"]])
    def test_bad_values_are_reported_with_the_existing_codes(self):
        self.assertIn("bad_config",codes(self.one("http",url="http://x/",method="TRACE")["errors"]))
        self.assertIn("Method must be one of: GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS.",[i["message"] for i in self.one("http",url="http://x/",method="TRACE")["errors"]])
        self.assertEqual("GET",self.cfg("http",url="http://x/",method="TRACE")["method"])
        self.assertIn("bad_var",codes(self.one("math",expr="1",var="1bad")["errors"]));self.assertEqual("result",self.cfg("math",expr="1",var="1bad")["var"])
        self.assertIn("bad_var",codes(self.one("math",expr="1",var="x"*41)["errors"]))
        self.assertIn("text_too_long",codes(self.one("log",message="x"*4001)["errors"]));self.assertEqual(4000,len(self.cfg("log",message="x"*4001)["message"]))
        self.assertIn("too_many_rows",codes(self.one("switch",cases=[{"name":"c%d"%i,"op":"equals","value":""} for i in range(13)])["errors"]))
        self.assertIn("bad_config",codes(self.one("switch",cases=["x"])["errors"]))
        self.assertIn("bad_config",codes(self.one("collection",source="${x}",op="median")["errors"]))
        self.assertIn("bad_config",codes(self.one("fields",ops=[{"op":"drop","field":"a","value":""}])["errors"]))
        for bad in ("ftp://x/","file:///etc/passwd","x/","javascript:alert(1)"):self.assertIn("bad_config",codes(self.one("http",url=bad)["errors"]),bad)
        for fine in ("http://x/","HTTPS://x/","${url}","{URL}/login"):self.assertTrue(self.one("http",url=fine)["ok"],fine)
        self.assertIn("bad_config",codes(self.one("http",url="http://x/",headers=[{"name":"Bad Name","value":"1"}])["errors"]))
        for bad in ("out.txt","./x","..\\x"):
            self.assertIn("bad_config",codes(self.one("file_write",path=bad)["errors"]),bad);self.assertIn("bad_config",codes(self.one("input_file",path=bad)["errors"]),bad)
        for fine in ("/tmp/x","~/x","C:\\out\\x.txt","${dir}/x","{Dir}/x"):self.assertTrue(self.one("file_write",path=fine)["ok"],fine)
        self.assertIn("bad_config",codes(self.one("regex",pattern="a",group="1 or 2")["errors"]))
    def test_regex_fields_go_through_the_redos_screen(self):
        for config in ({"pattern":"(a+)+$"},{"pattern":"("},{"pattern":"x"*499}):
            result=self.one("regex",**config)
            self.assertTrue({"invalid_regex","text_too_long"}&set(codes(result["errors"])),config)
        self.assertIn("invalid_regex",codes(self.one("split",mode="regex",separator="(a+)+$")["errors"]))
        self.assertTrue(self.one("split",mode="separator",separator="(a+)+$")["ok"],"a plain separator is not a regex")
        self.assertIn("invalid_regex",codes(self.one("switch",cases=[{"name":"a","op":"regex","value":"(a+)+$"}])["errors"]))
        self.assertIn("invalid_regex",codes(self.one("switch",cases=[{"name":"a","op":"regex","value":""}])["errors"]))
        self.assertIn("invalid_regex",codes(self.one("filter",source="${x}",conditions=[{"field":"","op":"not_regex","value":"(a+)+$"}])["errors"]))
        self.assertIn("bad_condition",codes(self.one("filter",source="${x}",conditions=[{"field":"","op":"gt","value":"many"}])["errors"]))
        self.assertTrue(self.one("filter",source="${x}",conditions=[{"field":"","op":"gt","value":"${limit}"}])["ok"])
    def test_switch_ports(self):
        sw=node("sw","switch",cases=[{"name":"a","op":"equals","value":"1"},{"name":"b","op":"equals","value":"2"}],default="rest")
        self.assertEqual({"in":True,"out":["a","b","rest"]},schema.node_ports(sw))
        self.assertEqual(["case1","default"],schema.node_ports({"type":"switch"})["out"])
        self.assertEqual(["ok","default"],schema.node_ports({"type":"switch","config":{"cases":[5,{"name":"bad name"},{"name":"ok"},{"name":"ok"}],"default":"also bad"}})["out"])
        result=check([sw,node("l","log",message="x")],["start.out>sw","sw.a>l","sw.b>l"])
        self.assertTrue(result["ok"],result["errors"])
        self.assertEqual(["port_unconnected"],codes(result["warnings"]),"the default port is optional, like a decision's else")
        self.assertIn("unknown_port",codes(check([sw,node("l","log",message="x")],["start.out>sw","sw.c>l"])["errors"]))
        self.assertIn("duplicate_port",codes(self.one("switch",cases=[{"name":"a","op":"equals","value":""},{"name":"a","op":"equals","value":""}])["errors"]))
        self.assertIn("bad_port_name",codes(self.one("switch",cases=[{"name":"not ok","op":"equals","value":""}])["errors"]))
        clash=self.one("switch",cases=[{"name":"default","op":"equals","value":""}])
        self.assertIn("duplicate_port",codes(clash["errors"]));self.assertEqual("default2",clash["graph"]["nodes"][1]["config"]["default"])
    def test_fail_and_error_ports_are_optional_warnings(self):
        result=check([node("h","http",url="http://x/"),node("m","math",expr="1")],["start.out>h","h.success>m"])
        self.assertTrue(result["ok"])
        self.assertEqual({"h":"port_unconnected","m":"port_unconnected"},{w["node"]:w["code"] for w in result["warnings"]})
        self.assertIn("bad_edge_target",codes(check([node("m","math",expr="1")],["m.out>start"])["errors"]))
    def test_math_syntax_is_checked_when_the_diagram_is_saved(self):
        for bad in ("1+","(1","foo(1)","1 $ 2","__import__('os')","a b","1,2"):
            self.assertIn("bad_expression",codes(self.one("math",expr=bad)["errors"]),bad)
        for fine in ("1/0","a/b","len(xs)*2","${a.b}+1","sqrt(x-5)","-x**2","round(a/3,2)"):
            self.assertTrue(self.one("math",expr=fine)["ok"],fine)
    def test_schema_1_graphs_and_bundles_still_load(self):
        old={"schema":1,"settings":{"on_error":"continue"},"nodes":[node("s","start"),cmd("c","echo hi"),node("p","parse",mode="tool",tool="nmap"),node("o","output",action="notify")],
             "edges":[{"id":"e1","from":"s","port":"out","to":"c"},{"id":"e2","from":"c","port":"success","to":"p"},{"id":"e3","from":"p","port":"out","to":"o"}]}
        result=schema.validate_graph(copy.deepcopy(old))
        self.assertTrue(result["ok"],result["errors"])
        self.assertEqual(2,result["graph"]["schema"])
        as_v2=schema.validate_graph(dict(copy.deepcopy(old),schema=2))
        self.assertEqual(as_v2["graph"],result["graph"],"a schema-1 graph is a valid schema-2 graph, unchanged")
        self.assertEqual(old["nodes"][1]["config"]["commands"][0]["text"],result["graph"]["nodes"][1]["config"]["commands"][0]["text"])
        self.assertEqual(1,old["schema"],"migrate does not change its input")
        self.assertEqual(2,schema.migrate(old)["schema"]);self.assertIs(old,schema.migrate(dict(old,schema=2)) and old)
        current={"schema":2,"nodes":[]}
        self.assertIs(current,schema.migrate(current))
        for junk in (None,5,"x",{"schema":"1"},{"schema":True},{"schema":0},{"schema":99}):self.assertEqual(junk,schema.migrate(junk))
        self.assertIn("schema_version",codes(schema.validate_graph(dict(old,schema=3))["errors"]))
        self.assertEqual(2,schema.new_graph()["schema"])
        bundle={"loya_chain":1,"name":"Old export","caller":"old","graph":copy.deepcopy(old)}
        loaded=schema.import_bundle(json.dumps(bundle))
        self.assertEqual(("Old export","old",2,4),(loaded["name"],loaded["caller"],loaded["graph"]["schema"],len(loaded["graph"]["nodes"])))
        self.assertEqual(1,schema.BUNDLE_VERSION);self.assertEqual(1,schema.export_bundle("x","",old)["loya_chain"])
        self.assertEqual(2,schema.export_bundle("x","",old)["graph"]["schema"])
    def test_stored_schema_1_diagram_loads_and_runs_through_the_service(self):
        iso=IsolatedData();iso.start()
        try:
            from Cores.Services import playbooks_service as chains
            pid=chains.create_playbook("Old one",None)
            old={"schema":1,"settings":dict(schema.DEFAULT_SETTINGS),"nodes":[node("n1","start"),node("n2","set",assign=[{"var":"a","value":"1"}])],"edges":[{"id":"e1","from":"n1","port":"out","to":"n2"}],"viewport":{"x":0,"y":0,"zoom":1}}
            store.save_graph(pid,old,schema_version=1)
            got=flows.get(pid)
            self.assertEqual(([],2,False),(got["errors"],got["graph"]["schema"],got["derived"]))
            self.assertEqual("planned",flows.wait(flows.run(pid,{"mode":"dry"})["run_id"],20)["nodes"]["n2"]["state"])
            imported=flows.import_json(json.dumps({"loya_chain":1,"name":"Old export","graph":old}))
            self.assertEqual(2,flows.get(imported["playbook_id"])["graph"]["schema"])
        finally:
            flows.stop_all("test teardown")
            for run in list(engine._runs.values()):run.finished.wait(10)
            engine._runs.clear();del engine._unsaved[:]
            iso.stop()
    def test_templates_with_the_new_nodes_are_valid(self):
        ids=[t["id"] for t in schema.TEMPLATES]
        self.assertIn("nmap-xml-findings",ids);self.assertIn("http-title-sweep",ids)
        for entry in schema.TEMPLATES:
            result=schema.validate_graph(entry["graph"])
            self.assertTrue(result["ok"],(entry["id"],result["errors"]))
            self.assertEqual([],[w for w in result["warnings"] if w["code"]=="unreachable"],entry["id"])
        types={n["type"] for n in schema.template("nmap-xml-findings")["nodes"]}
        self.assertLessEqual({"command","scan_parse","foreach","finding","report_create","result"},types)
        self.assertIn("-oX -",schema.graph_commands(schema.template("nmap-xml-findings"))[0]["text"])
        self.assertLessEqual({"input_text","foreach","http","regex","merge","collection","output"},{n["type"] for n in schema.template("http-title-sweep")["nodes"]})
# ---------------------------------------------------------------- math
class MathTests(unittest.TestCase):
    def ev(self,expr,**values):
        scope={"vars":values}
        return nodes.math_eval(expr,lambda name:rules.resolve(scope,name))
    def test_precedence_and_associativity(self):
        for expr,want in (("2+3*4",14),("(2+3)*4",20),("2*3+4*5",26),("10-4-3",3),("2**3**2",512),("-2**2",-4),("(-2)**2",4),("2**-1",0.5),("7//2",3),("-7//2",-4),("7%3",1),("10/4",2.5),
                          ("8/2",4.0),("1+2*3-4/2",5.0),("--3",3),("-+-3",3),("2*-3",-6),("1.5e2+.5",150.5),("3 * ( 2 + 1 ) ",9),("100//7%5",4),("2**0.5*2**0.5",2.0000000000000004)):
            self.assertEqual(want,self.ev(expr),expr)
    def test_functions(self):
        for expr,want in (("min(3,1,2)",1),("max(3,1,2)",3),("abs(-4.5)",4.5),("round(2.567,2)",2.57),("round(2.5)",2),("round(1234,-2)",1200),("floor(2.9)",2),("ceil(2.1)",3),("sqrt(16)",4.0),
                          ("int(7.9)",7),("float(3)",3.0),("max(1,2)*min(3,4)",6),("sum(1,2,3)",6),("len(xs)",3),("sum(xs)",60),("min(xs)+max(xs)",40),("sum(xs)/len(xs)",20.0),("len(name)",5),("len(none)+1",2)):
            self.assertEqual(want,self.ev(expr,xs=[10,20,"30"],name="hello",none=7),expr)
    def test_variables_and_flow_values(self):
        self.assertEqual(15,self.ev("a*b+${c}",a=2,b="5",c=5))
        self.assertEqual(7,self.ev("${scan.count}+ports[0]+obj.n",scan={"count":2},ports=[4],obj={"n":1}))
        self.assertEqual(3,self.ev("t+t+f+2*1",t=True,f=False)-1)
        self.assertEqual(2.5,self.ev("x*2",x=" 1.25 "))
        scope={"vars":{},"last":{"exit_code":3},"item":4,"index":1}
        self.assertEqual(8,nodes.math_eval("last.exit_code+item+index",lambda name:rules.resolve(scope,name)))
    def test_errors(self):
        for expr,needle in (("1/0","Division by zero"),("5//0","Division by zero"),("5%0","Division by zero"),("0**-1","Division by zero"),("a+1","has no value"),("name*2","not a number"),
                            ("xs+1","is a list"),("sqrt(-1)","negative"),("(-8)**0.5","real number"),("1+","ends too early"),("(1","Missing )"),("1 2","Unexpected"),("2 ^ 3","Unexpected"),
                            ("","empty"),("   ","empty"),("min()","nothing to compare"),("round(1,2,3)","round()"),("abs(1,2)","one value"),("max(1","Missing )"),("1,2","Unexpected")):
            with self.assertRaises(nodes.MathError,msg=expr) as caught:self.ev(expr,xs=[1],name="abc")
            self.assertIn(needle,str(caught.exception),expr)
    def test_nothing_is_evaluated_as_python(self):
        marker=os.path.join(tempfile.gettempdir(),"loya_math_marker_%d"%os.getpid())
        for expr in ("__import__('os').system('touch %s')"%marker,"__import__(1)","open('%s','w')"%marker,"eval(1)","exec(1)","().__class__","x.__class__.__mro__","getattr(x,1)","lambda: 1",
                     "[1,2]","{1:2}","'a'*3","\"a\"","1 if 1 else 2","x=1","import os","1;2","print(1)","os.system(1)","a.b()","globals()","__builtins__","x[0]()","1 and 2","not 1","1==1","~1","1<<64","0x10","1_000"):
            with self.assertRaises(nodes.MathError,msg=expr):self.ev(expr,x=1)
        self.assertFalse(os.path.exists(marker))
        # A variable that holds code is only ever read as a number.
        with self.assertRaises(nodes.MathError):self.ev("a+1",a="__import__('os').getcwd()")
        with self.assertRaises(nodes.MathError):self.ev("${a}",a="1+1")
    def test_size_bounds(self):
        for expr in ("9**9**9","2**100000","10**5000","(2**4000)*(2**4000)","99999999999999999999**300","1e308*10","2.0**5000","9"*61,"1"+"+1"*400,"("*70+"1"+")"*70,"-"*70+"1","1e400"):
            began=time.monotonic()
            with self.assertRaises(nodes.MathError,msg=expr[:30]):self.ev(expr)
            self.assertLess(time.monotonic()-began,1.0,expr[:30])
        with self.assertRaises(nodes.MathError):self.ev("1+"*1100+"1")
        self.assertEqual(2**4000,self.ev("2**4000"))
        self.assertEqual(1267650600228229401496703205376,self.ev("2**100"))
        with self.assertRaises(nodes.MathError):self.ev("sum(xs)",xs=[2**4090]*100)
        self.assertEqual(2e61,self.ev("a*2",a="1"+"0"*61))   # a very long number in a variable is read as a float
# ---------------------------------------------------------------- scan parsing
NMAP_NORMAL="""Starting Nmap 7.94 ( https://nmap.org )
Nmap scan report for web01.lab (10.0.0.5)
Host is up (0.0010s latency).
PORT     STATE  SERVICE VERSION
22/tcp   open   ssh     OpenSSH 8.2p1 Ubuntu
80/tcp   open   http    nginx 1.18.0
443/tcp  closed https
Nmap scan report for 10.0.0.9
Host is up.
PORT   STATE SERVICE
53/udp open  domain
"""
NMAP_XML="""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE nmaprun>
<nmaprun scanner="nmap" args="nmap -sV -oX - 10.0.0.5" version="7.94">
<host><status state="up" reason="echo-reply"/><address addr="10.0.0.5" addrtype="ipv4"/><address addr="00:11:22:33:44:55" addrtype="mac"/>
<hostnames><hostname name="web01.lab" type="PTR"/></hostnames>
<ports><port protocol="tcp" portid="22"><state state="open" reason="syn-ack"/><service name="ssh" product="OpenSSH" version="8.2p1" extrainfo="Ubuntu"/></port>
<port protocol="tcp" portid="80"><state state="open"/><service name="http" product="nginx"/></port>
<port protocol="tcp" portid="443"><state state="closed"/><service name="https"/></port></ports></host>
<host><status state="down"/><address addr="10.0.0.6" addrtype="ipv4"/></host>
<host><status state="up"/><address addr="fe80::1" addrtype="ipv6"/><ports><port protocol="udp" portid="53"><state state="open"/></port><port protocol="tcp" portid="99999"><state state="open"/></port></ports></host>
</nmaprun>
"""
NMAP_GREP="""# Nmap 7.94 scan initiated as: nmap -sV -oG - 10.0.0.5
Host: 10.0.0.5 (web01.lab)\tStatus: Up
Host: 10.0.0.5 (web01.lab)\tPorts: 22/open/tcp//ssh//OpenSSH 8.2p1 Ubuntu/, 80/open/tcp//http//nginx 1.18.0/, 443/closed/tcp//https///\tIgnored State: filtered (997)
Host: 10.0.0.9 ()\tStatus: Down
# Nmap done at ... -- 2 IP addresses (1 host up) scanned
"""
class ScanParseTests(unittest.TestCase):
    def host_shape(self,result):
        self.assertEqual(["format","hosts","ports","open_ports","host_count","port_count"],list(result))
        for host in result["hosts"]:
            self.assertEqual(["ip","hostname","state","ports"],list(host))
            for port in host["ports"]:self.assertEqual(["port","proto","state","service","version"],list(port))
        for port in result["ports"]:
            self.assertEqual("open",port["state"]);self.assertLessEqual({"port","proto","state","service","version","host","ip","hostname"},set(port))
        json.dumps(result)
    def test_normal_output_reuses_the_existing_parser(self):
        result=nodes.parse_scan(NMAP_NORMAL,"nmap");self.host_shape(result)
        self.assertEqual([("10.0.0.5","web01.lab","up",3),("10.0.0.9","","up",1)],[(h["ip"],h["hostname"],h["state"],len(h["ports"])) for h in result["hosts"]])
        self.assertEqual({"port":22,"proto":"tcp","state":"open","service":"ssh","version":"OpenSSH 8.2p1 Ubuntu"},result["hosts"][0]["ports"][0])
        self.assertEqual([22,53,80],result["open_ports"])
        self.assertEqual([("10.0.0.5",22),("10.0.0.5",80),("10.0.0.9",53)],[(p["host"],p["port"]) for p in result["ports"]])
        self.assertEqual(rules.parse_tool_output("nmap",NMAP_NORMAL)["open_ports"],result["open_ports"])
    def test_xml(self):
        result=nodes.parse_scan(NMAP_XML,"nmap_xml");self.host_shape(result)
        self.assertEqual([("10.0.0.5","web01.lab","up"),("10.0.0.6","","down"),("fe80::1","","up")],[(h["ip"],h["hostname"],h["state"]) for h in result["hosts"]])
        self.assertEqual([{"port":22,"proto":"tcp","state":"open","service":"ssh","version":"OpenSSH 8.2p1 Ubuntu"},{"port":80,"proto":"tcp","state":"open","service":"http","version":"nginx"},
                          {"port":443,"proto":"tcp","state":"closed","service":"https","version":""}],result["hosts"][0]["ports"])
        self.assertEqual([22,53,80],result["open_ports"]);self.assertEqual(1,len(result["hosts"][2]["ports"]),"port 99999 is not a port")
        # Text around the document (a shell banner, stderr) is tolerated.
        self.assertEqual([22,53,80],nodes.parse_scan("Starting...\n"+NMAP_XML+"\n$ ","nmap_xml")["open_ports"])
    def test_xml_refuses_entities_and_broken_documents(self):
        bomb='<?xml version="1.0"?><!DOCTYPE nmaprun [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">]><nmaprun><host><address addr="&b;" addrtype="ipv4"/></host></nmaprun>'
        external='<?xml version="1.0"?><!DOCTYPE nmaprun [<!entity xxe SYSTEM "file:///etc/passwd">]><nmaprun><host><address addr="&xxe;" addrtype="ipv4"/></host></nmaprun>'
        for hostile in (bomb,external):
            with self.assertRaises(ValueError) as refused:nodes.parse_scan(hostile,"nmap_xml")
            self.assertIn("entity",str(refused.exception))
            with self.assertRaises(ValueError):nodes.parse_scan(hostile,"auto")
        for broken,needle in ((NMAP_XML[:400],"could not be read"),("<html><body/></html>","not nmap XML"),("just text","not nmap XML"),('<?xml version="1.0"?><other/>',"not nmap XML")):
            with self.assertRaises(ValueError) as refused:nodes.parse_scan(broken,"nmap_xml")
            self.assertIn(needle,str(refused.exception))
        with self.assertRaises(ValueError) as refused:nodes.parse_scan("x"*(nodes.SCAN_MAX+1),"auto")
        self.assertIn("larger than",str(refused.exception))
    def test_grepable(self):
        result=nodes.parse_scan(NMAP_GREP,"nmap_grep");self.host_shape(result)
        self.assertEqual([("10.0.0.5","web01.lab","up",3),("10.0.0.9","","down",0)],[(h["ip"],h["hostname"],h["state"],len(h["ports"])) for h in result["hosts"]])
        self.assertEqual({"port":22,"proto":"tcp","state":"open","service":"ssh","version":"OpenSSH 8.2p1 Ubuntu"},result["hosts"][0]["ports"][0])
        self.assertEqual({"port":443,"proto":"tcp","state":"closed","service":"https","version":""},result["hosts"][0]["ports"][2])
        self.assertEqual([22,80],result["open_ports"])
    def test_auto_detects_the_format(self):
        for text,fmt in ((NMAP_NORMAL,"nmap"),(NMAP_XML,"nmap_xml"),("\n  "+NMAP_XML,"nmap_xml"),(NMAP_GREP,"nmap_grep"),("",""),("nothing here","nmap")):
            self.assertEqual(fmt or "nmap",nodes.detect_scan_format(text));self.assertEqual(fmt or "nmap",nodes.parse_scan(text,"auto")["format"])
        same=[nodes.parse_scan(text,"auto") for text in (NMAP_NORMAL,NMAP_XML,NMAP_GREP)]
        self.assertEqual([[22,80]]*3,[sorted(p["port"] for p in r["ports"] if p["ip"]=="10.0.0.5") for r in same])
        self.assertEqual({"hosts":[],"ports":[],"open_ports":[]},{k:nodes.parse_scan("no scan","auto")[k] for k in ("hosts","ports","open_ports")})
# ---------------------------------------------------------------- execution: data nodes
class DataNodeTests(Base):
    def test_input_text_formats_and_template(self):
        set_live_target({"IPv4":"10.0.0.5"})
        status=self.run_chain(node("a","input_text",text="  one\n\n two \n",format="lines",var="xs"),node("b","input_text",text="u,p\nadmin, s3\n",format="csv",var="rows"),
                              node("c","input_text",text='{"a":[1,2]}',format="json",var="obj"),node("d","input_text",text="http://{IPv4}/ ${xs}",var="plain"),
                              node("t","template",template="  ${obj.a[1]} items on {IPv4}: ${xs}\n",var="line"))
        self.assertEqual("done",status["state"],status["reason"])
        self.assertEqual((["one","two"],[["u","p"],["admin","s3"]],{"a":[1,2]},"http://10.0.0.5/ one,two","  2 items on 10.0.0.5: one,two\n"),tuple(status["vars"][k] for k in ("xs","rows","obj","plain","line")))
        out=status["nodes"]["a"]["output"]
        self.assertEqual((["one","two"],"one,two","",0,{"xs":["one","two"]}),(out["parsed"],out["stdout"],out["stderr"],out["exit_code"],out["vars_set"]))
        self.assertEqual("failed",self.run_chain(node("c","input_text",text="{not json",format="json"))["state"])
    def test_split_join_map(self):
        status=self.run_chain(node("s","input_text",text="b ; a;;c ;a",var="raw"),node("sp","split",source="${raw}",mode="separator",separator=";",var="parts"),
                              node("rx","split",source="${raw}",mode="regex",separator=r"\s*;+\s*",var="by_regex"),node("ws","split",source="x  y\tz",mode="whitespace",var="words"),
                              node("cm","split",source="1, 2,,3",mode="comma",drop_empty=False,trim=False,var="cells"),node("js","split",source='[1,{"a":2}]',mode="json",var="loaded"),
                              node("ln","split",source="${raw}",mode="lines",var="lines"),node("mp","map",source="${parts}",template="<${index}:${item}>",var="mapped"),
                              node("j","join",source="${mapped}",separator="\\n",var="joined"),node("j2","join",source="${parts}",separator=" | ",var="piped"))
        self.assertEqual("done",status["state"],status["reason"])
        v=status["vars"]
        self.assertEqual((["b","a","c","a"],["b","a","c","a"],["x","y","z"],["1"," 2","","3"],[1,{"a":2}],["b ; a;;c ;a"]),(v["parts"],v["by_regex"],v["words"],v["cells"],v["loaded"],v["lines"]))
        self.assertEqual((["<0:b>","<1:a>","<2:c>","<3:a>"],"<0:b>\n<1:a>\n<2:c>\n<3:a>","b | a | c | a"),(v["mapped"],v["joined"],v["piped"]))
        self.assertEqual("b\na\nc\na",status["nodes"]["sp"]["output"]["stdout"])
    def test_map_keeps_structure_for_a_single_value_and_fields_edit_objects(self):
        ports=[{"port":22,"service":"ssh","junk":1},{"port":80,"service":"http","junk":2}]
        status=self.run_chain(node("s","input_text",text=json.dumps(ports),format="json",var="ports"),node("m","map",source="${ports}",template="${item.port}",var="numbers"),
                              node("f","fields",source="${ports}",ops=[{"op":"set","field":"url","value":"http://h:${item.port}/"},{"op":"set","field":"n","value":"${index}"},{"op":"rename","field":"service","value":"name"},{"op":"remove","field":"junk","value":""}],var="edited"),
                              node("k","fields",source="${ports[0]}",ops=[{"op":"keep","field":"port, service","value":""}],var="kept"),
                              node("b","fields",source="${nothing}",ops=[{"op":"set","field":"a","value":"1"}],var="built"))
        self.assertEqual("done",status["state"],status["reason"])
        v=status["vars"]
        self.assertEqual([22,80],v["numbers"])
        self.assertEqual([{"port":22,"name":"ssh","url":"http://h:22/","n":0},{"port":80,"name":"http","url":"http://h:80/","n":1}],v["edited"])
        self.assertEqual(["port","name","url","n"],list(v["edited"][0]),"rename keeps the position")
        self.assertEqual(({"port":22,"service":"ssh"},{"a":"1"}),(v["kept"],v["built"]))
        self.assertEqual(ports,v["ports"],"the source is not changed in place")
        self.assertEqual("failed",self.run_chain(node("s","input_text",text="[1,2]",format="json",var="xs"),node("f","fields",source="${xs}",ops=[{"op":"set","field":"a","value":"1"}]))["state"])
    def test_filter(self):
        ports=[{"port":22,"service":"ssh"},{"port":80,"service":"HTTP"},{"port":8080,"service":"http-proxy"},{"port":443,"service":"https"}]
        g=graph([node("s","input_text",text=json.dumps(ports),format="json",var="ports"),
                 node("web",  "filter",source="${ports}",conditions=[{"field":"service","op":"starts_with","value":"http"},{"field":"port","op":"lt","value":"1000"}],var="web"),
                 node("any",  "filter",source="${ports}",match="any",conditions=[{"field":"port","op":"eq","value":"22"},{"field":"service","op":"regex","value":"proxy$"}],var="either"),
                 node("cs",   "filter",source="${ports}",ci=False,conditions=[{"field":"service","op":"contains","value":"http"}],var="exact"),
                 node("plain","filter",source="a,b,ab",conditions=[{"field":"","op":"contains","value":"${needle}"}],var="plain"),
                 node("none", "filter",source="${ports}",conditions=[{"field":"port","op":"gt","value":"99999"}],var="none"),
                 node("hit","set",assign=[{"var":"took","value":"empty"}]),node("needle","set",assign=[{"var":"needle","value":"a"}])],
                ["start.out>s","s.out>needle","needle.out>web","web.out>any","any.out>cs","cs.out>plain","plain.out>none","none.empty>hit"])
        status=self.run_graph(g)
        self.assertEqual("done",status["state"],status["reason"])
        v=status["vars"]
        self.assertEqual(([80,443],[22,8080],[8080,443],["a","ab"],[],"empty"),([p["port"] for p in v["web"]],[p["port"] for p in v["either"]],[p["port"] for p in v["exact"]],v["plain"],v["none"],v["took"]))
        self.assertEqual("empty",status["nodes"]["none"]["branch"])
    def test_regex(self):
        text="22/tcp open ssh\n80/tcp open http\n443/tcp closed https"
        g=graph([node("s","input_text",text=text,var="t"),node("all","regex",source="${t}",pattern=r"(\d+)/tcp\s+open",var="whole"),
                 node("g1","regex",source="${t}",pattern=r"(\d+)/tcp\s+open",group="1",var="ports"),node("named","regex",source="${t}",pattern=r"(?P<port>\d+)/tcp\s+(?P<state>\w+)",group="state",var="states"),
                 node("first","regex",source="${t}",pattern=r"(\d+)/TCP",mode="first",group="1",var="first"),node("flag","regex",source="${t}",pattern=r"(?i)^(\d+)/TCP",flags="m",group="1",var="multiline"),
                 node("plain","regex",source="${t}",pattern=r"\d+/tcp",var="nogroup"),node("none","regex",source="${t}",pattern="zzz",var="nothing"),
                 node("cs","regex",source="${t}",pattern="TCP",flags="",var="case"),node("after","set",assign=[{"var":"took","value":"nomatch"}])],
                ["start.out>s","s.out>all","all.out>g1","g1.out>named","named.out>first","first.out>flag","flag.out>plain","plain.out>none","none.nomatch>cs","cs.nomatch>after"])
        status=self.run_graph(g)
        self.assertEqual("done",status["state"],status["reason"])
        v=status["vars"]
        self.assertEqual((["22/tcp open","80/tcp open"],["22","80"],["open","open","closed"],"22",["22","80","443"],["22/tcp","80/tcp","443/tcp"],[],[],"nomatch"),
                         (v["whole"],v["ports"],v["states"],v["first"],v["multiline"],v["nogroup"],v["nothing"],v["case"],v["took"]))
        self.assertEqual((2,"22\n80"),(status["nodes"]["g1"]["output"]["match_count"],status["nodes"]["g1"]["output"]["stdout"]))
        for bad in (node("r","regex",source="x",pattern="(a)",group="3"),node("r","regex",source="x",pattern="(a)",group="nope")):
            failed=self.run_chain(bad)
            self.assertEqual("failed",failed["state"]);self.assertIn("no group",failed["nodes"]["r"]["error"])
    def test_json(self):
        g=graph([node("s","input_text",text='noise\n{"a":{"b":[10,{"c":"deep"}]},"n":1}',var="raw"),node("p","json",action="parse",source="${raw}",var="obj"),
                 node("g","json",action="get",source="${obj}",path="a.b[1].c",var="deep"),node("g2","json",action="get",source="${raw}",path="a.b[*]",var="star"),
                 node("f","json",action="format",source="${obj.a}",indent=0,var="compact"),node("f2","json",action="format",source="${obj.a.b}",indent=2,var="pretty"),
                 node("bad","json",action="parse",source="not json",var="never"),node("miss","json",action="get",source="${obj}",path="x.y",var="never2"),
                 node("e1","set",assign=[{"var":"first","value":"error"}]),node("e2","set",assign=[{"var":"second","value":"error"}])],
                ["start.out>s","s.out>p","p.out>g","g.out>g2","g2.out>f","f.out>f2","f2.out>bad","bad.error>e1","e1.out>miss","miss.error>e2"])
        status=self.run_graph(g)
        self.assertEqual("done",status["state"],status["reason"])
        v=status["vars"]
        self.assertEqual(({"a":{"b":[10,{"c":"deep"}]},"n":1},"deep",[10,{"c":"deep"}],'{"b":[10,{"c":"deep"}]}',json.dumps([10,{"c":"deep"}],indent=2),"error","error"),
                         (v["obj"],v["deep"],v["star"],v["compact"],v["pretty"],v["first"],v["second"]))
        self.assertNotIn("never",v);self.assertNotIn("never2",v)
        self.assertEqual(("fail","error"),(status["nodes"]["bad"]["state"],status["nodes"]["bad"]["branch"]))
        self.assertIn("nothing at 'x.y'",status["nodes"]["miss"]["error"])
    def test_collection_operations(self):
        rows=[{"host":"a","port":80,"svc":"http"},{"host":"b","port":22,"svc":"ssh"},{"host":"a","port":443,"svc":"http"},{"host":"c","port":"9","svc":"x"}]
        ops=[("count",{},4),("sum",{"field":"port"},554),("min",{"field":"port"},9),("max",{"field":"port"},443),("avg",{"field":"port"},138.5),
             ("dedupe",{"field":"host"},["a","b","c"]),("sort",{"field":"port","numeric":True},[9,22,80,443]),("sort",{"field":"port","numeric":True,"order":"desc"},[443,80,22,9]),
             ("sort",{"field":"svc"},["http","http","ssh","x"]),("reverse",{},["c","a","b","a"]),("limit",{"limit":2},["a","b"]),("first",{},"a"),("last",{},"c"),
             ("group",{"field":"host"},{"a":2,"b":1,"c":1}),("group_count",{"field":"svc"},{"http":2,"ssh":1,"x":1}),("pluck",{"field":"port"},[80,22,443,"9"])]
        steps=[node("s","input_text",text=json.dumps(rows),format="json",var="rows")]+[node("c%d"%i,"collection",op=op,source="${rows}",var="v%d"%i,**extra) for i,(op,extra,_want) in enumerate(ops)]
        steps+=[node("fl","collection",op="flatten",source="${nested}",var="flat"),node("txt","collection",op="count",source="a,b,c",var="lines"),node("dd","collection",op="dedupe",source="b,a,b",var="plain"),
                node("mx","collection",op="max",source="pear,apple",var="word"),node("em","collection",op="first",source="${missing}",var="empty")]
        steps.insert(1,node("n","input_text",text="[[1,2],[3],4]",format="json",var="nested"))
        status=self.run_chain(*steps)
        self.assertEqual("done",status["state"],status["reason"])
        v=status["vars"]
        for i,(op,extra,want) in enumerate(ops):
            got=v["v%d"%i]
            if op in("dedupe","reverse","limit"):got=[r["host"] for r in got]
            elif op=="sort":got=[int(r["port"]) if "numeric" in extra else r["svc"] for r in got]
            elif op in("first","last"):got=got["host"]
            elif op=="group":got={k:len(members) for k,members in got.items()}
            self.assertEqual(want,got,"%s %r"%(op,extra))
        self.assertEqual(([1,2,3,4],3,["b","a"],"pear",None),(v["flat"],v["lines"],v["plain"],v["word"],v["empty"]))
    def test_math_node_and_its_error_port(self):
        g=graph([node("s","input_text",text="[3,4,5]",format="json",var="xs"),node("m","math",expr="sum(xs)/len(xs)",var="avg"),node("r","math",expr="avg*100/7",var="pct",decimals=2),
                 node("i","math",expr="${pct}",var="whole",decimals=0),node("z","math",expr="avg/(len(xs)-3)",var="never"),node("h","set",assign=[{"var":"took","value":"error"}])],
                ["start.out>s","s.out>m","m.out>r","r.out>i","i.out>z","z.error>h"])
        status=self.run_graph(g)
        self.assertEqual("done",status["state"],status["reason"])
        self.assertEqual((4,57.14,57,"error"),tuple(status["vars"][k] for k in ("avg","pct","whole","took")))
        self.assertEqual(("fail","error","Division by zero."),(status["nodes"]["z"]["state"],status["nodes"]["z"]["branch"],status["nodes"]["z"]["error"]))
        unhandled=self.run_chain(node("z","math",expr="1/0"),node("after","log",message="never"))
        self.assertEqual(("failed","skipped"),(unhandled["state"],unhandled["nodes"]["after"]["state"]))
    def test_node_values_are_never_trusted_for_raw_insertion(self):
        # ${raw:name} skips the shell quoter: only a literal Set-variable value may use it, never what a node computed.
        g=graph([node("s","input_text",text="; echo INJECTED",var="x"),node("t","template",template="$(id)",var="y"),node("m","math",expr="1+1",var="n"),cmd("c","echo ${raw:x} ${raw:y} ${raw:n}")],
                ["start.out>s","s.out>t","t.out>m","m.out>c"])
        status=self.run_graph(g)
        self.assertEqual("failed",status["state"])
        self.assertIn("${raw:",status["nodes"]["c"]["error"]);self.assertEqual([],status["nodes"]["c"]["job_keys"],"nothing was executed")
        # ... and a trusted literal loses its trust when a node writes over it.
        g=graph([node("lit","set",assign=[{"var":"x","value":"safe"}]),node("over","template",template="; id",var="x"),cmd("c","echo ${raw:x}")],["start.out>lit","lit.out>over","over.out>c"])
        self.assertEqual("failed",self.run_graph(g)["state"])
        quoted=self.run_graph(graph([node("s","input_text",text="a; echo INJECTED",var="x"),cmd("c","echo ${x}")],["start.out>s","s.out>c"]))
        self.assertEqual(("done","a; echo INJECTED"),(quoted["state"],quoted["nodes"]["c"]["output"]["stdout"].strip()))
    def test_big_values_are_capped_in_the_status_but_not_in_the_run(self):
        status=self.run_chain(node("s","input_text",text="\n".join("line-%05d"%i for i in range(4000)),format="lines",var="short"),node("m","map",source="${short}",template="${item}-"+"x"*60,var="xs"),
                              node("c","collection",op="count",source="${xs}",var="n"),node("l","collection",op="last",source="${xs}",var="last"))
        self.assertEqual((4000,"line-03999-"+"x"*60),(status["vars"]["n"],status["vars"]["last"]),"later nodes work on the whole value")
        out=status["nodes"]["m"]["output"]
        self.assertTrue(out["truncated"]);self.assertLess(len(out["parsed"]),4000)
        self.assertLessEqual(len(json.dumps(out["parsed"],separators=(",",":"))),nodes.PARSED_CAP+16);self.assertLessEqual(len(out["stdout"]),engine.OUTPUT_CAP)
        self.assertEqual((["a"],False),nodes.cap_value(["a"]));self.assertEqual(("x"*10,True),nodes.cap_value("x"*50,10))
        self.assertEqual({"truncated":True,"preview":'{"k": "'+"v"*43},nodes.cap_value({"k":"v"*500},100)[0])
# ---------------------------------------------------------------- execution: logic
class LogicNodeTests(Base):
    def switch_run(self,value,**config):
        cases=[{"name":"ssh","op":"equals","value":"22"},{"name":"web","op":"regex","value":"^(80|443|8080)$"},{"name":"high","op":"gt","value":"1024"},{"name":"named","op":"contains","value":"${word}"}]
        g=graph([node("w","set",assign=[{"var":"word","value":"SMB"},{"var":"v","value":value}]),node("sw","switch",value="${v}",cases=cases,default="other",**config)]+
                [node(name,"set",assign=[{"var":"took","value":name}]) for name in ("ssh","web","high","named","other")],
                ["start.out>w","w.out>sw"]+["sw.%s>%s"%(name,name) for name in ("ssh","web","high","named","other")])
        return self.run_graph(g)
    def test_switch_takes_the_first_matching_case_else_the_default(self):
        for value,want in (("22","ssh"),(" 22 ","ssh"),("443","web"),("8443","high"),("8080","web"),("smb-share","named"),("21","other"),("","other")):
            status=self.switch_run(value)
            self.assertEqual(("done",want,want),(status["state"],status["vars"]["took"],status["nodes"]["sw"]["branch"]),value)
        self.assertEqual("other",self.switch_run("smb-share",ci=False)["vars"]["took"])
        trace=self.switch_run("443")["nodes"]["sw"]["output"]["trace"]
        self.assertEqual([("ssh",False),("web",True)],[(t["branch"],t["matched"]) for t in trace],"cases after the match are not evaluated")
    def test_switch_on_a_list_and_pass_through(self):
        g=graph([node("s","input_text",text="[22,80]",format="json",var="ports"),node("sw","switch",value="${ports}",cases=[{"name":"web","op":"eq","value":"80"}],default="none"),node("t","template",template="${last.stdout}|${last.parsed}",var="seen")],
                ["start.out>s","s.out>sw","sw.web>t"])
        status=self.run_graph(g)
        self.assertEqual("22,80|22,80",status["vars"]["seen"],"a switch hands the previous output on unchanged")
    def test_merge_all_waits_for_every_incoming_connection(self):
        g=graph([node("a","input_text",text="A",var="a"),node("b","input_text",text="B",var="b"),node("c","input_text",text="C",var="c"),node("m","merge",mode="all",collect="stdout",var="got"),
                 node("after","template",template="after:${got}",var="done")],
                ["start.out>a","start.out>b","start.out>c","a.out>m","b.out>m","c.out>m","m.out>after"])
        status=self.run_graph(g)
        self.assertEqual("done",status["state"],status["reason"])
        self.assertEqual((["A","B","C"],"after:A,B,C"),(status["vars"]["got"],status["vars"]["done"]))
        self.assertEqual((3,1,"out"),(status["nodes"]["m"]["visits"],status["nodes"]["after"]["visits"],status["nodes"]["m"]["branch"]))
        self.assertEqual({"arrived":3,"of":3},status["nodes"]["m"]["output"]["merge"])
        self.assertEqual(2,sum("waiting" in t for t in self.texts(status)))
        # A branch that never arrives: the merge does not fire, and the run still ends cleanly.
        g=graph([node("a","input_text",text="A"),node("z","math",expr="1/0"),node("m","merge",mode="all",var="got"),node("after","log",message="never")],
                ["start.out>a","start.out>z","a.out>m","z.out>m","m.out>after"],on_error="continue")
        status=self.run_graph(g)
        self.assertEqual(("done","skipped",1),(status["state"],status["nodes"]["after"]["state"],status["nodes"]["m"]["visits"]))
        self.assertNotIn("got",status["vars"])
    def test_merge_any_passes_every_arrival_on_and_accumulates(self):
        g=graph([node("xs","input_text",text="a\nb\nc",format="lines",var="xs"),node("loop","foreach",items="${xs}"),node("up","template",template="<${item}>",var="one"),
                 node("m","merge",mode="any",collect="stdout",var="all"),node("seen","template",template="${all}",var="snapshot"),node("end","collection",op="count",source="${all}",var="n")],
                ["start.out>xs","xs.out>loop","loop.item>up","up.out>m","m.out>seen","loop.done>end"])
        status=self.run_graph(g)
        self.assertEqual("done",status["state"],status["reason"])
        self.assertEqual((["<a>","<b>","<c>"],3,"<a>,<b>,<c>"),(status["vars"]["all"],status["vars"]["n"],status["vars"]["snapshot"]))
        self.assertEqual((3,3),(status["nodes"]["m"]["visits"],status["nodes"]["seen"]["visits"]))
        g=graph([node("p","input_text",text='{"k":1}',format="json"),node("m","merge",collect="parsed",var="objs"),node("n","merge",collect="none",var="nothing")],["start.out>p","p.out>m","m.out>n"])
        status=self.run_graph(g)
        self.assertEqual(([{"k":1}],[]),(status["vars"]["objs"],status["vars"]["nothing"]))
    def test_merge_all_starts_empty_again_in_a_loop(self):
        g=graph([node("xs","input_text",text="1\n2",format="lines",var="xs"),node("loop","foreach",items="${xs}"),node("a","template",template="a${item}"),node("b","template",template="b${item}"),
                 node("m","merge",mode="all",collect="stdout",var="pair"),node("out","merge",mode="any",collect="parsed",var="pairs")],
                ["start.out>xs","xs.out>loop","loop.item>a","loop.item>b","a.out>m","b.out>m","m.out>out"])
        status=self.run_graph(g)
        self.assertEqual([["a1","b1"],["a2","b2"]],status["vars"]["pairs"])
    def test_on_error_continue_uses_the_plain_way_out(self):
        expected={"template":"out","merge":"out","result":"out","log":"out","note":"out","regex":"nomatch","filter":"empty","scan_parse":"nomatch","input_target":"missing","cve_lookup":"none",
                  "http":"","math":"","json":"","input_file":"","file_write":""}
        for node_type,port in expected.items():self.assertEqual(port,engine.result_port_for_continue({"type":node_type,"config":{}},""),node_type)
        self.assertEqual("rest",engine.result_port_for_continue({"type":"switch","config":{"cases":[{"name":"a"}],"default":"rest"}},""))
        self.assertEqual(("out","else","nomatch",""),tuple(engine.result_port_for_continue({"type":t,"config":{}},"") for t in ("set","decision","parse","command")))
        g=graph([node("s","input_text",text="x",var="t"),node("f","fields",source="${t}",ops=[{"op":"set","field":"a","value":"1"}]),node("after","template",template="went on",var="after")],["start.out>s","s.out>f","f.out>after"],on_error="continue")
        status=self.run_graph(g)
        self.assertEqual(("done","fail","went on"),(status["state"],status["nodes"]["f"]["state"],status["vars"]["after"]))
        self.assertIn("1 node(s) failed",status["reason"])
    def test_results_log_and_the_stored_snapshot(self):
        g=graph([node("s","input_text",text="[22,80]",format="json",var="ports"),node("r1","result",label="Open ports",value="${ports}"),node("r2","result",value="count=${ports} token=abc"),
                 node("li","log",level="info",message="info ${ports}"),node("lw","log",level="warn",message="careful"),node("le","log",level="error",message="bad thing")],
                ["start.out>s","s.out>r1","r1.out>r2","r2.out>li","li.out>lw","lw.out>le"])
        status=self.run_graph(g,playbook_id=5)
        self.assertEqual("done",status["state"],"a log node never fails the run, whatever its level")
        self.assertEqual([{"node":"r1","label":"Open ports","value":[22,80]},{"node":"r2","label":"r2","value":"count=22,80 token=abc"}],status["results"])
        self.assertEqual([22,80],status["nodes"]["r1"]["output"]["parsed"])
        self.assertEqual("22,80",status["nodes"]["li"]["output"]["stdout"],"result and log nodes pass the previous output on")
        log=flows.run_log(status["run_id"])["entries"]
        messages=[(e["level"],e["text"]) for e in log if e["kind"]=="message"]
        self.assertEqual([("info","info 22,80"),("warn","careful"),("error","bad thing")],messages)
        end=next(e for e in log if e["kind"]=="run_end")
        self.assertEqual((1,1),(end["data"]["warnings"],end["data"]["errors"]))
        self.assertTrue(wait_until(lambda:store.get_run(status["run_id"]) is not None))
        self.assertEqual(status["results"],store.get_run(status["run_id"])["results"],"results are part of the stored snapshot")
        engine._runs.clear()
        self.assertEqual(status["results"],flows.run_status(status["run_id"])["results"])
        # A run stored before result nodes existed has no `results` key: it reads as an empty list.
        old=dict(store.get_run(status["run_id"]),run_id="runold000001");old.pop("results")
        store.save_run(old)
        self.assertNotIn("results",store.get_run("runold000001"))
        self.assertEqual([],flows.run_status("runold000001")["results"]);self.assertEqual([],flows.run_status("runold000001",since=3)["results"])
    def test_dry_run_plans_the_new_nodes(self):
        set_live_target({"IPv4":"10.0.0.5"})
        g=graph([node("h","http",method="POST",url="https://{IPv4}/api?q=${q}"),node("w","file_write",path="/tmp/loya-never-written.txt"),node("r","input_file",path="~/in.txt"),node("n","note",note_name="Recon {IPv4}",action="append"),
                 node("f","finding",severity="high",title="x"),node("rc","report_create",name="R"),node("tu","target_update",key="Port",value="1"),node("lt","live_target",name="dc01"),
                 node("cv","cve_lookup",query="openssh"),node("m","math",expr="1+1")],
                ["start.out>h","h.success>w","w.out>r","r.out>n","n.out>f","f.out>rc","rc.out>tu","tu.out>lt","lt.out>cv","cv.found>m"])
        status=self.run_graph(g,mode="dry")
        self.assertEqual("done",status["state"])
        self.assertEqual({"planned"},set(self.states(status).values()))
        texts=self.texts(status)
        for line in ("Would request POST https://10.0.0.5/api?q=${q}","Would write file /tmp/loya-never-written.txt (overwrite)","Would read file ~/in.txt","Would append to note 'Recon 10.0.0.5'",
                     "Would add a high finding to the newest report","Would create report 'R'","Would set Port on the live target","Would make 'dc01' the live target","Would search the offline CVE index for 'openssh'"):
            self.assertIn(line,texts)
        self.assertEqual("Would request POST https://10.0.0.5/api?q=${q}",status["nodes"]["h"]["output"]["planned"])
        self.assertFalse(os.path.exists("/tmp/loya-never-written.txt"))
        self.assertEqual([],self.audit("terminal_command"));self.assertEqual({},status["vars"])
# ---------------------------------------------------------------- execution: app nodes
class AppNodeTests(Base):
    def targets(self):
        api=bridge_api.TargetsAPI()
        for key in ("IPv4","Port","Password"):api.add_key(key,0)
        api.upsert_target(None,"web01","not_used",{"IPv4":"10.0.0.5","Password":"Winter2024!"})
        api.upsert_target(None,"dc01","not_used",{"IPv4":"10.0.0.10"})
        api.set_live_target(next(t["id"] for t in api.targets() if t["name"]=="web01"))
        return api
    def by_name(self,api,name):
        return next((t for t in bridge_api.TargetsAPI().targets() if t["name"]==name),None)
    def test_input_target_live_named_and_missing(self):
        self.targets()
        g=graph([node("live","input_target",var="tgt"),node("named","input_target",source="name",name="DC01",var="dc"),node("gone","input_target",source="name",name="nope",var="none"),
                 node("t","template",template="${tgt.ipv4} ${tgt.name} ${dc.ipv4} ${dc.values.ipv4}",var="line"),node("m","set",assign=[{"var":"took","value":"missing"}])],
                ["start.out>live","live.out>named","named.out>t","t.out>gone","gone.missing>m"])
        status=self.run_graph(g)
        self.assertEqual("done",status["state"],status["reason"])
        self.assertEqual(("10.0.0.5 web01 10.0.0.10 10.0.0.10","missing"),(status["vars"]["line"],status["vars"]["took"]))
        self.assertEqual({"ipv4":"10.0.0.5","password":"Winter2024!","name":"web01","values":{"ipv4":"10.0.0.5","password":"Winter2024!"}},status["vars"]["tgt"])
        self.assertNotIn("none",status["vars"])
    def test_input_target_without_a_live_target_takes_missing(self):
        status=self.run_graph(graph([node("live","input_target"),node("m","log",message="no target")],["start.out>live","live.missing>m"]))
        self.assertEqual(("missing","success"),(status["nodes"]["live"]["branch"],status["nodes"]["m"]["state"]))
    def test_target_update_live_named_created_and_missing(self):
        api=self.targets()
        g=graph([node("a","target_update",key="port",value="8080"),node("b","target_update",target="name",name="dc01",key="Domain",value="corp.local"),
                 node("c","target_update",target="name",name="new-box",key="IPv4",value="10.0.0.77",create_missing=True),node("d","target_update",target="name",name="ghost",key="IPv4",value="1.1.1.1"),
                 cmd("e","echo {Port}"),node("m","set",assign=[{"var":"took","value":"missing"}])],
                ["start.out>a","a.out>b","b.out>c","c.out>d","d.missing>m","m.out>e"])
        status=self.run_graph(g)
        self.assertEqual("done",status["state"],status["reason"])
        self.assertEqual({"IPv4":"10.0.0.5","Password":"Winter2024!","Port":"8080"},self.by_name(api,"web01")["values"],"the existing key is matched without regard to case")
        self.assertEqual({"IPv4":"10.0.0.10","Domain":"corp.local"},self.by_name(api,"dc01")["values"])
        self.assertIn("Domain",[k["key"] for k in bridge_api.TargetsAPI().keys()],"a new parameter is registered")
        self.assertEqual({"IPv4":"10.0.0.77"},self.by_name(api,"new-box")["values"])
        self.assertIsNone(self.by_name(api,"ghost"));self.assertEqual("missing",status["vars"]["took"])
        self.assertEqual("8080",status["nodes"]["e"]["output"]["stdout"].strip(),"a later command sees the live target's new value")
        self.assertEqual("live",self.by_name(api,"web01")["status"])
    def test_live_target_switches_for_the_rest_of_the_run(self):
        api=self.targets()
        g=graph([cmd("before","echo {IPv4}"),node("sw","live_target",name="dc01"),cmd("after","echo {IPv4}"),node("again","live_target",name="DC01"),node("t","input_target",var="tgt"),
                 node("gone","live_target",name="ghost"),node("m","set",assign=[{"var":"took","value":"missing"}])],
                ["start.out>before","before.success>sw","sw.out>after","after.success>again","again.out>t","t.out>gone","gone.missing>m"])
        status=self.run_graph(g)
        self.assertEqual("done",status["state"],status["reason"])
        self.assertEqual(("10.0.0.5","10.0.0.10"),(status["nodes"]["before"]["output"]["stdout"].strip(),status["nodes"]["after"]["output"]["stdout"].strip()))
        self.assertEqual(("live","not_used"),(self.by_name(api,"dc01")["status"],self.by_name(api,"web01")["status"]),"setting the live target twice does not clear it")
        self.assertEqual(("dc01","missing"),(status["vars"]["tgt"]["name"],status["vars"]["took"]))
        self.assertTrue(any("made 'dc01' the live target" in d for d in self.audit("chain_live_target")))
    def test_note_actions(self):
        notes=bridge_api.NotesAPI()
        status=self.run_chain(node("s","input_text",text="<b>scan</b> output",var="t"),node("n1","note",note_name="Recon",title="First",content="${t}"),node("n2","note",action="append",note_name="recon",content="second"),
                              node("n3","note",action="create",note_name="Other",content="x"),node("n4","note",content="fallback name"))
        self.assertEqual("done",status["state"],status["reason"])
        listed={n["name"] if "name" in n else n.get("note_name"):n for n in notes.list()}
        self.assertEqual({"Recon","Other","Chain output - Test chain"},set(listed))
        content=notes.get(listed["Recon"]["id"])["content_html"]
        self.assertIn("&lt;b&gt;scan&lt;/b&gt; output",content);self.assertNotIn("<b>scan",content);self.assertIn("First",content);self.assertIn("second",content)
        self.assertEqual("Created note 'Recon'",status["nodes"]["n1"]["output"]["result"]["text"]);self.assertEqual("Appended to note 'recon'",status["nodes"]["n2"]["output"]["result"]["text"])
        for bad,needle in ((node("n","note",action="append",note_name="Nope",content="x"),"no note named"),(node("n","note",action="create",note_name="Recon",content="x"),"already exists"),(node("n","note",note_name="E",content="  "),"Nothing to write")):
            failed=self.run_chain(bad)
            self.assertEqual("failed",failed["state"]);self.assertIn(needle,failed["nodes"]["n"]["error"])
        self.assertEqual(3,len(notes.list()))
    def test_report_create_and_finding(self):
        from Cores.Services import reports_service
        status=self.run_chain(node("rc","report_create",name="Nmap ${nothing}10.0.0.5",var="rid"),node("f1","finding",report="${rid}",title="Open port 22",severity="medium",description="<script>x</script> ssh"),
                              node("f2","finding",report="nmap 10.0.0.5",severity="low"),node("f3","finding",title="Newest"))
        self.assertEqual("done",status["state"],status["reason"])
        report=reports_service.get_report(status["vars"]["rid"])
        self.assertEqual("Nmap 10.0.0.5",report["title"])
        self.assertEqual([("Open port 22","medium"),("f2","low"),("Newest","info")],[(f["title"],f["severity"]) for f in report["findings"]])
        self.assertIn("&lt;script&gt;",report["findings"][0]["description"]);self.assertNotIn("<script>",report["findings"][0]["description"])
        failed=self.run_chain(node("f","finding",report="No such report",title="x"))
        self.assertEqual("failed",failed["state"]);self.assertIn("no report",failed["nodes"]["f"]["error"])
    def test_finding_without_any_report_fails_readably(self):
        failed=self.run_chain(node("f","finding",title="x"))
        self.assertEqual("failed",failed["state"]);self.assertIn("Create a report first",failed["nodes"]["f"]["error"])
    def test_cve_lookup_is_local_and_branches(self):
        from Cores.Services import cve_service
        g=graph([node("cv","cve_lookup",query="log4j ${nothing}",limit=3,var="cves"),node("f","set",assign=[{"var":"took","value":"found"}]),node("n","set",assign=[{"var":"took","value":"none"}])],["start.out>cv","cv.found>f","cv.none>n"])
        status=self.run_graph(g)
        self.assertEqual(("done","none",[]),(status["state"],status["vars"]["took"],status["vars"]["cves"]),"an empty install has no CVE data, and nothing is fetched")
        self.assertEqual([],cve_service.request_log())
        real=cve_service.search;seen=[]
        def fake(query,limit=20,filters=None):
            seen.append((query,limit,filters))
            return {"origin":"cache","query":query,"results":[{"id":"CVE-2021-44228","title":"Log4Shell","description":"long text","severity":"critical","score":10.0,"kev":True,"epss":0.97,"published":"2021-12-10","extra":"dropped"}]}
        cve_service.search=fake
        try:status=self.run_graph(g)
        finally:cve_service.search=real
        self.assertEqual([("log4j",3,None)],seen)
        self.assertEqual(("found",[{"id":"CVE-2021-44228","title":"Log4Shell","severity":"critical","score":10.0,"kev":True,"epss":0.97,"published":"2021-12-10"}]),(status["vars"]["took"],status["vars"]["cves"]))
        self.assertIn("CVE-2021-44228 critical Log4Shell",status["nodes"]["cv"]["output"]["stdout"])
    def test_scan_parse_node(self):
        g=graph([node("x","input_text",text=NMAP_XML,var="xml"),node("sc","scan_parse",source="${xml}",var="scan"),node("loop","foreach",items="${scan.ports}"),node("t","template",template="${item.host}:${item.port}/${item.proto} ${item.service}",var="line"),
                 node("m","merge",collect="stdout",var="lines"),node("g","scan_parse",format="nmap_grep",source="${grep}",var="g"),node("bad","scan_parse",format="nmap_xml",source="<!DOCTYPE x [<!ENTITY a 'b'>]><nmaprun/>",var="never"),
                 node("gs","input_text",text=NMAP_GREP,var="grep"),node("nm","set",assign=[{"var":"took","value":"nomatch"}])],
                ["start.out>x","x.out>gs","gs.out>sc","sc.out>loop","loop.item>t","t.out>m","loop.done>g","g.out>bad","bad.nomatch>nm"])
        status=self.run_graph(g)
        self.assertEqual("done",status["state"],status["reason"])
        v=status["vars"]
        self.assertEqual((["10.0.0.5:22/tcp ssh","10.0.0.5:80/tcp http","fe80::1:53/udp "],[22,80],"nomatch"),(v["lines"],v["g"]["open_ports"],v["took"]))
        self.assertEqual("nmap_xml",v["scan"]["format"]);self.assertNotIn("never",v)
        self.assertIn("entity",status["nodes"]["bad"]["error"])
        self.assertEqual(NMAP_XML,status["nodes"]["sc"]["output"]["stdout"],"the scan text itself stays the node's text output")
# ---------------------------------------------------------------- execution: files
class FileNodeTests(Base):
    def test_write_then_read(self):
        path=os.path.join(self.tmp,"sub","out.txt")
        status=self.run_chain(node("s","input_text",text="line one\nline two",var="t"),node("w","file_write",path=path,content="${t}\n"),node("a","file_write",path=path,content="appended ünï\n",mode="append"),
                              node("r","input_file",path=path,var="text"),node("l","input_file",path=path,format="lines",var="lines"),node("j","file_write",path=os.path.join(self.tmp,"data.json"),content='{"a":[1,2]}'),
                              node("rj","input_file",path=os.path.join(self.tmp,"data.json"),format="json",var="obj"))
        self.assertEqual("done",status["state"],status["reason"])
        with open(path,"rb") as handle:self.assertEqual("line one\nline two\nappended ünï\n".encode("utf-8"),handle.read())
        self.assertEqual(("line one\nline two\nappended ünï\n",["line one","line two","appended ünï"],{"a":[1,2]}),(status["vars"]["text"],status["vars"]["lines"],status["vars"]["obj"]))
        self.assertEqual({"path":os.path.realpath(path),"bytes":18,"mode":"overwrite"},status["nodes"]["w"]["output"]["file"])
        self.assertTrue(any(os.path.realpath(path) in d and "wrote" in d for d in self.audit("chain_file_write")));self.assertTrue(any("appended to" in d for d in self.audit("chain_file_write")))
        self.assertTrue(any(os.path.realpath(path) in d for d in self.audit("chain_file_read")))
    def test_home_paths_and_templated_paths(self):
        real=os.path.expanduser
        os.path.expanduser=lambda p:(self.tmp+p[1:]) if str(p).startswith("~") else real(p)
        try:
            set_live_target({"IPv4":"10.0.0.5"})
            status=self.run_chain(node("n","set",assign=[{"var":"name","value":"loot"}]),node("w","file_write",path="~/{IPv4}-${name}.txt",content="x"),node("r","input_file",path="~/10.0.0.5-loot.txt",var="back"))
        finally:os.path.expanduser=real
        self.assertEqual(("done","x"),(status["state"],status["vars"].get("back")))
        self.assertTrue(os.path.isfile(os.path.join(self.tmp,"10.0.0.5-loot.txt")))
    def refuse(self,item,needle):
        g=graph([item,node("h","set",assign=[{"var":"took","value":"error"}])],["start.out>%s"%item["id"],"%s.error>h"%item["id"]])
        status=self.run_graph(g)
        self.assertEqual(("done","fail","error","error"),(status["state"],status["nodes"][item["id"]]["state"],status["nodes"][item["id"]]["branch"],status["vars"].get("took")),status["nodes"][item["id"]])
        self.assertIn(needle,status["nodes"][item["id"]]["error"])
        return status
    def test_the_data_and_backups_folders_are_off_limits(self):
        # The isolated Backups/ lives inside the isolated Data/; give it a place of its own so both rules are exercised.
        data=common_db.data_dir();backups=os.path.join(self.tmp,"AppBackups");os.makedirs(backups)
        real_backups=common_db.backups_dir;common_db.backups_dir=lambda:backups
        try:self._off_limits(data,backups)
        finally:common_db.backups_dir=real_backups   # before tearDown restores the isolated one
    def _off_limits(self,data,backups):
        secret=os.path.join(data,"settings.json")
        with open(secret,"w",encoding="utf-8") as handle:handle.write('{"secret":"do-not-read"}')
        for path in (secret,os.path.join(data,"Note_LOYA_V1.db"),os.path.join(data,"new","x.txt"),os.path.join(data,"..",os.path.basename(data),"settings.json"),os.path.join(backups,"b.loyabak")):
            status=self.refuse(node("r","input_file",path=path,var="leak"),"Data folder" if not path.startswith(backups) else "Backups folder")
            self.assertNotIn("leak",status["vars"])
            self.refuse(node("w","file_write",path=path,content="overwritten"),"Data folder" if not path.startswith(backups) else "Backups folder")
        with open(secret,encoding="utf-8") as handle:self.assertEqual('{"secret":"do-not-read"}',handle.read())
        self.assertFalse(os.path.exists(os.path.join(data,"new")));self.assertEqual([],os.listdir(backups))
        if os.path.exists(os.path.join(data,"Note_LOYA_V1.db")):
            with open(os.path.join(data,"Note_LOYA_V1.db"),"rb") as handle:self.assertNotEqual(b"overwritten",handle.read(11))
        self.assertEqual([],self.audit("chain_file_write"));self.assertEqual([],self.audit("chain_file_read"))
        # The folder arrives through a variable (validation cannot see it): still refused at run time.
        g=graph([node("s","set",assign=[{"var":"dir","value":data}]),node("w","file_write",path="${dir}/via-var.txt",content="x"),node("h","log",message="refused")],["start.out>s","s.out>w","w.error>h"])
        self.assertEqual("fail",self.run_graph(g)["nodes"]["w"]["state"]);self.assertFalse(os.path.exists(os.path.join(data,"via-var.txt")))
    @unittest.skipIf(WINDOWS,"symlinks need a privilege on Windows")
    def test_a_symlink_into_data_is_followed_and_refused(self):
        data=common_db.data_dir()
        with open(os.path.join(data,"settings.json"),"w",encoding="utf-8") as handle:handle.write("secret")
        os.symlink(data,os.path.join(self.tmp,"link"));os.symlink(os.path.join(data,"settings.json"),os.path.join(self.tmp,"file-link"))
        for path in (os.path.join(self.tmp,"link","settings.json"),os.path.join(self.tmp,"file-link")):
            self.refuse(node("r","input_file",path=path,var="leak"),"Data folder");self.refuse(node("w","file_write",path=path,content="x"),"Data folder")
        with open(os.path.join(data,"settings.json"),encoding="utf-8") as handle:self.assertEqual("secret",handle.read())
    def test_safe_path(self):
        self.assertEqual(os.path.realpath(os.path.join(self.tmp,"a.txt")),nodes.safe_path(os.path.join(self.tmp,"a.txt")))
        for bad in ("","  ","relative.txt","./x","a\x00b"):
            with self.assertRaises(ValueError,msg=repr(bad)):nodes.safe_path(bad)
        with self.assertRaises(ValueError):nodes.safe_path(common_db.data_dir())
        with self.assertRaises(ValueError):nodes.safe_path(os.path.join(common_db.backups_dir(),"x"))
    def test_size_caps_missing_files_and_folders(self):
        big=os.path.join(self.tmp,"big.txt")
        with open(big,"wb") as handle:handle.write(b"x"*3000)
        self.refuse(node("r","input_file",path=big,max_kb=2),"larger than 2 KB")
        self.assertEqual("x"*3000,self.run_chain(node("r","input_file",path=big,max_kb=3,var="t"))["vars"]["t"])
        self.refuse(node("r","input_file",path=os.path.join(self.tmp,"nope.txt")),"no file")
        self.refuse(node("r","input_file",path=self.tmp),"no file")
        self.refuse(node("w","file_write",path=self.tmp,content="x"),"folder")
        self.refuse(node("r","input_file",path=big,format="json"),"not valid JSON")
        binary=os.path.join(self.tmp,"bin.dat")
        with open(binary,"wb") as handle:handle.write(b"ok\xff\xfe\r\nnext")
        self.assertEqual("ok\ufffd\ufffd\nnext",self.run_chain(node("r","input_file",path=binary,var="t"))["vars"]["t"],"bytes that are not UTF-8 are replaced, not an error")
        real=nodes.WRITE_MAX;nodes.WRITE_MAX=10
        try:self.refuse(node("w","file_write",path=os.path.join(self.tmp,"toobig.txt"),content="x"*11),"larger than")
        finally:nodes.WRITE_MAX=real
        self.assertFalse(os.path.exists(os.path.join(self.tmp,"toobig.txt")))
# ---------------------------------------------------------------- execution: http
class _Handler(http.server.BaseHTTPRequestHandler):
    seen=[]
    def log_message(self,*args):pass
    def _send(self,code,body,ctype="text/plain; charset=utf-8",headers=()):
        data=body if isinstance(body,bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type",ctype);self.send_header("Content-Length",str(len(data)))
        for name,value in headers:self.send_header(name,value)
        self.end_headers()
        if self.command!="HEAD":self.wfile.write(data)
    def _serve(self):
        length=int(self.headers.get("Content-Length") or 0)
        body=self.rfile.read(length).decode("utf-8") if length else ""
        type(self).seen.append({"method":self.command,"path":self.path,"headers":{k.lower():v for k,v in self.headers.items()},"body":body})
        path=self.path.split("?")[0]
        if path=="/json":return self._send(200,json.dumps({"ok":True,"items":[1,2],"token":"abc"}),"application/json",[("X-Served-By","loya-test")])
        if path=="/html":return self._send(200,"<html><head><title>Lab Login</title></head></html>","text/html; charset=utf-8")
        if path=="/echo":return self._send(200,json.dumps({"method":self.command,"body":body,"auth":self.headers.get("Authorization"),"ctype":self.headers.get("Content-Type"),"agent":self.headers.get("User-Agent")}),"application/json")
        if path=="/redirect":return self._send(302,"moved","text/plain",[("Location","/json")])
        if path=="/redirect-file":return self._send(302,"moved","text/plain",[("Location","file:///etc/passwd")])
        if path=="/big":return self._send(200,"x"*5000)
        if path=="/latin":return self._send(200,"caf\xe9".encode("latin-1"),"text/plain; charset=iso-8859-1")
        if path=="/slow":
            time.sleep(float(self.path.split("?")[1]) if "?" in self.path else 5)
            return self._send(200,"late")
        if path=="/500":return self._send(500,"boom")
        return self._send(404,"not here")
    do_GET=do_POST=do_PUT=do_PATCH=do_DELETE=do_HEAD=do_OPTIONS=_serve
class HttpNodeTests(Base):
    @classmethod
    def setUpClass(cls):
        cls.server=http.server.ThreadingHTTPServer(("127.0.0.1",0),_Handler)
        cls.server.daemon_threads=True
        cls.base="http://127.0.0.1:%d"%cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever,daemon=True).start()
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close()
    def setUp(self):
        super().setUp();del _Handler.seen[:]
    def http(self,path="/json",**config):
        config.setdefault("timeout",10)
        return node("h","http",url=self.base+path,**config)
    def both(self,item,*more,**kw):
        """Run one http node with both ports handled; vars["took"] says which was taken."""
        g=graph([item,node("ok","set",assign=[{"var":"took","value":"success"}]),node("bad","set",assign=[{"var":"took","value":"fail"}])]+list(more),["start.out>h","h.success>ok","h.fail>bad"])
        return self.run_graph(g,**kw)
    def test_get_json(self):
        status=self.both(self.http())
        self.assertEqual(("done","success"),(status["state"],status["vars"]["took"]))
        response=status["vars"]["response"]
        self.assertEqual(["status","headers","body","url","elapsed_ms","truncated","json"],list(response))
        self.assertEqual((200,{"ok":True,"items":[1,2],"token":"abc"},self.base+"/json",False),(response["status"],response["json"],response["url"],response["truncated"]))
        self.assertEqual(("loya-test","application/json"),(response["headers"]["X-Served-By"],response["headers"]["Content-Type"]))
        out=status["nodes"]["h"]["output"]
        self.assertEqual(["status","url","elapsed_ms","headers"],list(out["http"]));self.assertEqual(200,out["http"]["status"])
        self.assertEqual((response["body"],0,{"response"}),(out["stdout"],out["exit_code"],set(out["vars_set"])))
        self.assertEqual("GET",_Handler.seen[0]["method"]);self.assertEqual("LOYA-NG/1.0.0",_Handler.seen[0]["headers"]["user-agent"])
    def test_the_response_feeds_later_nodes(self):
        g=graph([self.http("/html"),node("r","regex",source="${response.body}",pattern=r"<title>([^<]+)",mode="first",group="1",var="title"),node("j","http",url=self.base+"/json",var="api",timeout=10),
                 node("t","template",template="${title}|${response.status}|${api.json.items[1]}|${api.headers.x-served-by}|${last.stdout}",var="line")],["start.out>h","h.success>r","r.out>j","j.success>t"])
        status=self.run_graph(g)
        self.assertEqual("done",status["state"],status["reason"])
        self.assertTrue(status["vars"]["line"].startswith("Lab Login|200|2|loya-test|{"),status["vars"]["line"])
    def test_post_with_headers_body_and_values(self):
        set_live_target({"Token":"tok-123"})
        status=self.both(self.http("/echo?id=${n}",method="POST",headers=[{"name":"Authorization","value":"Bearer {Token}"},{"name":"X-N","value":"${n}"}],body='{"n":${n}}'),node("n","set",assign=[{"var":"n","value":"7"}]))
        self.assertEqual("success",status["vars"]["took"])
        seen=_Handler.seen[0]
        self.assertEqual(("POST","/echo?id=",'{"n":}'),(seen["method"],seen["path"],seen["body"]),"the set node is not on the path, so ${n} is empty")
        self.assertEqual(("Bearer tok-123","application/json"),(seen["headers"]["authorization"],seen["headers"]["content-type"]))
        g=graph([node("n","set",assign=[{"var":"n","value":"7"}]),self.http("/echo?id=${n}",method="PUT",headers=[{"name":"Content-Type","value":"text/plain"},{"name":"User-Agent","value":"mine"}],body="n=${n}")],["start.out>n","n.out>h"])
        echoed=self.run_graph(g)["vars"]["response"]["json"]
        self.assertEqual({"method":"PUT","body":"n=7","auth":None,"ctype":"text/plain","agent":"mine"},echoed)
        self.assertEqual("/echo?id=7",_Handler.seen[-1]["path"])
        for method in ("DELETE","PATCH","OPTIONS"):self.assertEqual(method,self.run_chain(self.http("/echo",method=method))["vars"]["response"]["json"]["method"])
        head=self.run_chain(self.http("/json",method="HEAD"))["vars"]["response"]
        self.assertEqual((200,""),(head["status"],head["body"]))
    def test_status_400_and_up_takes_the_fail_port_with_the_response(self):
        for path,code in (("/missing",404),("/500",500)):
            status=self.both(self.http(path))
            self.assertEqual(("done","fail","fail","HTTP %d"%code),(status["state"],status["vars"]["took"],status["nodes"]["h"]["state"],status["nodes"]["h"]["error"]))
            self.assertEqual(code,status["vars"]["response"]["status"]);self.assertEqual(1,status["nodes"]["h"]["output"]["exit_code"])
        self.assertEqual("not here",status["vars"]["response"]["body"] if code==404 else self.both(self.http("/missing"))["vars"]["response"]["body"])
        unhandled=self.run_chain(self.http("/missing"),node("after","log",message="never"))
        self.assertEqual(("failed","skipped"),(unhandled["state"],unhandled["nodes"]["after"]["state"]))
        self.assertIn("HTTP 404",unhandled["reason"])
        # Red when nobody handles it, yellow when the fail port is connected - the log semantics of commands.
        levels=lambda s:[e["level"] for e in flows.run_log(s["run_id"])["entries"] if e["kind"]=="http" and "HTTP 404" in e["text"]]
        self.assertEqual((["error"],["warn"]),(levels(unhandled),levels(self.both(self.http("/missing")))))
    def test_redirects(self):
        followed=self.both(self.http("/redirect"))["vars"]["response"]
        self.assertEqual((200,self.base+"/json",True),(followed["status"],followed["url"],followed["json"]["ok"]))
        kept=self.both(self.http("/redirect",follow_redirects=False))
        self.assertEqual(("success",302,"/json"),(kept["vars"]["took"],kept["vars"]["response"]["status"],kept["vars"]["response"]["headers"]["Location"]))
        self.assertEqual(["/redirect"],[s["path"] for s in _Handler.seen[-1:]])
        refused=self.both(self.http("/redirect-file"))
        self.assertEqual("fail",refused["vars"]["took"]);self.assertNotIn("response",refused["vars"])
        self.assertNotIn("root:",json.dumps(refused["nodes"]["h"]["output"]))
    def test_only_http_and_https(self):
        for url in ("file:///etc/passwd","ftp://127.0.0.1/x","gopher://127.0.0.1/","data:text/plain,hi","//127.0.0.1/x","127.0.0.1/x",""):
            g=graph([node("u","set",assign=[{"var":"u","value":url}]),node("h","http",url="${u}"),node("bad","set",assign=[{"var":"took","value":"fail"}])],["start.out>u","u.out>h","h.fail>bad"])
            status=self.run_graph(g)
            self.assertEqual(("fail","fail"),(status["nodes"]["h"]["state"],status["vars"].get("took")),url)
            self.assertNotIn("response",status["vars"])
        self.assertEqual([],_Handler.seen)
        for bad in ("http://127.0.0.1/a b","http://127.0.0.1/a\r\nX: y"):
            with self.assertRaises(ValueError):nodes.http_request("GET",bad)
        with self.assertRaises(ValueError):nodes.http_request("GET",self.base+"/json",headers=[("X-A","1\r\nX-Injected: 1")])
        with self.assertRaises(ValueError):nodes.http_request("GET",self.base+"/json",headers=[("Bad Name","1")])
        with self.assertRaises(ValueError):nodes.http_request("TRACE",self.base+"/json")
    def test_size_cap_charset_and_connection_errors(self):
        big=self.both(self.http("/big",max_kb=1))["vars"]["response"]
        self.assertEqual((1024,True),(len(big["body"]),big["truncated"]))
        self.assertEqual("café",self.both(self.http("/latin"))["vars"]["response"]["body"])
        closed=http.server.ThreadingHTTPServer(("127.0.0.1",0),_Handler);port=closed.server_address[1];closed.server_close()
        status=self.both(node("h","http",url="http://127.0.0.1:%d/"%port,timeout=5))
        self.assertEqual(("fail","fail"),(status["vars"]["took"],status["nodes"]["h"]["state"]))
        self.assertIn("request failed",status["nodes"]["h"]["error"])
    def test_timeout(self):
        began=time.monotonic()
        status=self.both(self.http("/slow?4",timeout=1))
        self.assertLess(time.monotonic()-began,3.5)
        self.assertEqual("fail",status["vars"]["took"]);self.assertIn("Timed out after 1 s",status["nodes"]["h"]["error"])
    def test_a_stop_ends_a_request_that_is_waiting(self):
        run=engine.start_run(chain(self.http("/slow?8",timeout=30),node("after","log",message="never")),name="Slow");self.started.append(run)
        self.assertTrue(wait_until(lambda:len(_Handler.seen)==1,10))
        began=time.monotonic()
        run.stop("stopped by the test")
        self.assertTrue(run.finished.wait(5),"the run did not stop while the request was waiting")
        self.assertLess(time.monotonic()-began,3)
        status=run.status()
        self.assertEqual(("cancelled","skipped"),(status["state"],status["nodes"]["after"]["state"]))
        self.assertNotIn("response",status["vars"])
    def test_the_request_is_audited_like_a_command_with_secrets_redacted(self):
        status=self.both(self.http("/json?password=Sup3rSecret99&x=1"),source="ai")
        details=self.audit("terminal_command")
        self.assertEqual(1,len(details))
        self.assertTrue(details[0].startswith("flow-ai:flow:"+status["run_id"]+" [http] GET "+self.base+"/json"),details[0])
        self.assertNotIn("Sup3rSecret99",details[0])
        self.assertNotIn("Sup3rSecret99",json.dumps(flows.run_log(status["run_id"])["entries"]))
    def test_verify_tls_refuses_a_plain_server_on_https_either_way(self):
        for verify in (True,False):
            status=self.both(node("h","http",url=self.base.replace("http://","https://")+"/json",verify_tls=verify,timeout=5))
            self.assertEqual("fail",status["vars"]["took"])
# ---------------------------------------------------------------- the plan, the AI gate and the MCP tools
def call(tool,**args):
    return chat._call_tool(tool,args)
class PlanAndAiTests(Base):
    def setUp(self):
        super().setUp()
        terminal.set_enabled(True)
        ai.revoke_session_grant()
        self.asked=[];self.answer="approved"
        self._real_request=ai.request_approval
        def fake(tool_name,summary="",timeout=None,reason=None,labels=None):
            self.asked.append((tool_name,summary))
            return self.answer
        ai.request_approval=fake
    def tearDown(self):
        ai.request_approval=self._real_request
        ai.revoke_session_grant()
        super().tearDown()
    def ok(self,tool,**args):
        good,result=call(tool,**args)
        self.assertTrue(good,result)
        return result
    def refused(self,tool,**args):
        good,result=call(tool,**args)
        self.assertFalse(good,result)
        return str(result)
    def acting(self):
        return graph([node("h","http",method="POST",url="https://{IPv4}/login"),node("w","file_write",path="/tmp/loya-plan.txt"),node("r","input_file",path="~/in.txt"),node("n","note",note_name="Recon"),
                      node("f","finding",severity="high",report="Q4"),node("rc","report_create",name="New"),node("tu","target_update",target="name",name="dc01",key="Port",value="1"),node("lt","live_target",name="dc01"),
                      node("m","math",expr="1+1"),node("un","http",url="http://unreachable.invalid/")],
                     ["start.out>h","h.success>w","w.out>r","r.out>n","n.out>f","f.out>rc","rc.out>tu","tu.out>lt","lt.out>m"])
    def test_plan_lists_what_acts_outside_the_run(self):
        set_live_target({"IPv4":"10.0.0.5"})
        pid=flows.create("Acts",self.acting())["playbook_id"]
        plan=flows.plan(pid)
        self.assertEqual([("h","http","POST https://10.0.0.5/login"),("w","file_write","Write file /tmp/loya-plan.txt (overwrite)"),("r","input_file","Read file ~/in.txt"),("n","note","Append to or create note 'Recon'"),
                          ("f","finding","Add a high finding to report 'Q4'"),("rc","report_create","Create report 'New'"),("tu","target_update","Set Port on target 'dc01'"),("lt","live_target","Make 'dc01' the live target")],
                         [(a["node"],a["type"],a["summary"]) for a in plan["actions"]],"the unreachable http node is not listed")
        for action in plan["actions"]:self.assertEqual({"node","title","type","summary"},set(action))
        self.assertEqual([],plan["commands"]);self.assertEqual("",plan["blocked"])
        self.assertEqual(["tu","lt"],[a["node"] for a in flows.plan(pid,from_node="tu")["actions"]])
        self.assertEqual([],flows.plan(flows.create("Pure",chain(node("m","math",expr="1+1")))["playbook_id"])["actions"])
        self.assertIn("(TLS not verified)",nodes.action_summary(node("h","http",url="https://x/",verify_tls=False)))
    def test_ai_runs_of_http_and_file_chains_always_ask(self):
        set_live_target({"IPv4":"10.0.0.5"})
        cases={"http":node("x","http",url="http://127.0.0.1:9/"),"file_write":node("x","file_write",path=os.path.join(self.tmp,"o.txt")),"input_file":node("x","input_file",path=os.path.join(self.tmp,"i.txt"))}
        for kind,item in cases.items():
            info=flows.ai_run_info(flows.create("Outside "+kind,chain(item))["playbook_id"])
            self.assertTrue(info["force_ask"],kind);self.assertEqual(1,len(info["actions"]))
            self.assertEqual((False,[],0,[]),(info["unreviewed"],info["destructive"],info["scripts"],info["subchains"]),"the node alone forces the prompt")
        quiet=flows.ai_run_info(flows.create("Inside",chain(node("n","note",note_name="N",content="x"),node("m","math",expr="1+1"),cmd("c","echo hi")))["playbook_id"])
        self.assertFalse(quiet["force_ask"]);self.assertEqual(["Append to or create note 'N'"],quiet["actions"])
    def test_the_approval_prompt_names_the_request_whatever_the_permission_level(self):
        target=os.path.join(self.tmp,"written.txt")
        pid=flows.create("Writes",chain(node("w","file_write",path=target,content="by the chain")))["playbook_id"]
        ai.set_permission_levels({"chain_diagrams_run":"allow"})
        self.answer="denied"
        self.refused("chain_run",chain_id=pid)
        self.assertEqual(["chain_run"],[a[0] for a in self.asked]);self.assertIn("Write file "+target,str(self.asked[0][1]))
        self.assertFalse(os.path.exists(target),"a denied run writes nothing")
        self.answer="approved"
        status=flows.wait(self.ok("chain_run",chain_id=pid,reason="test")["run_id"],30)
        self.assertEqual("done",status["state"])
        with open(target,encoding="utf-8") as handle:self.assertEqual("by the chain",handle.read())
        self.assertEqual(2,len(self.asked),"allow + a file node still asks, every run")
        pure=flows.create("Pure",chain(node("m","math",expr="1+1",var="n"),node("r","result",label="n",value="${n}")))["playbook_id"]
        run_id=self.ok("chain_run",chain_id=pure)["run_id"]
        self.assertEqual(2,len(self.asked),"a chain that only computes runs on the permission alone")
        flows.wait(run_id,30)
        self.assertEqual([{"node":"r","label":"n","value":2}],self.ok("chain_run_status",run_id=run_id)["results"])
        ai.set_permission_levels({"chain_diagrams_run":"deny"})
        self.assertIn("Deny",self.refused("chain_run",chain_id=pid))
    def test_tools_are_registered_once_under_the_existing_chain_permissions(self):
        names=[t.name for t in chat._list_tools()]
        self.assertEqual({"chain_node_types","chain_validate","chain_run_output","chain_node_add","chain_node_set","chain_node_delete","chain_connect"},set(flow_tools.all_tool_names()))
        for tool in flow_tools.all_tool_names():
            self.assertIn(tool,names);self.assertEqual(1,sum(tool in tools for tools in ai.PERMISSION_TOOL_MAP.values()),tool)
        for tool in ("chain_node_types","chain_validate","chain_run_output"):self.assertEqual("chain_diagrams_read",ai.permission_key(tool))
        for tool in ("chain_node_add","chain_node_set","chain_node_delete","chain_connect"):self.assertEqual("chain_diagrams_edit",ai.permission_key(tool))
        self.assertEqual({"Chain Diagrams"},{ai.PERMISSION_LABELS[ai.permission_key(t)][0] for t in flow_tools.all_tool_names()},"no new AI Roles entity")
        self.assertEqual("deny",ai.tool_decision("chain_run"),"running stays denied by default")
        for name in names:self.assertIsNotNone(ai.permission_key(name),name)
    def test_node_types_listing_is_compact_paged_and_filterable(self):
        first=self.ok("chain_node_types")
        self.assertEqual((39,20,True,0),(first["total"],len(first["items"]),first["more"],first["offset"]))
        self.assertLess(len(json.dumps(first)),6000,"the listing must not flood the context")
        self.assertEqual({"type","label","category","ports","description"},set(first["items"][0]))
        self.assertEqual([c["id"] for c in nodes.CATEGORIES],[c["id"] for c in first["categories"]]);self.assertEqual(39,sum(c["types"] for c in first["categories"]))
        rest=self.ok("chain_node_types",offset=20,limit=60)
        self.assertEqual((19,False),(len(rest["items"]),rest["more"]))
        self.assertEqual(list(nodes.SPECS),[r["type"] for r in first["items"]+rest["items"]])
        self.assertEqual(["note","finding","report_create","target_update","cve_lookup","live_target"],[r["type"] for r in self.ok("chain_node_types",category="app")["items"]])
        self.assertEqual(["http"],[r["type"] for r in self.ok("chain_node_types",query="curl request")["items"]])
        self.assertEqual([],self.ok("chain_node_types",category="nope")["items"])
        one=self.ok("chain_node_types",type="http")["types"][0]
        self.assertEqual(("http",["success","fail"],"fail",CONTRACT["http"][3]),(one["type"],one["ports"],one["fail_port"],one["defaults"]))
        fields={f["key"]:f for f in one["fields"]}
        self.assertEqual(list(CONTRACT["http"][3]),list(fields))
        self.assertEqual((list(nodes.HTTP_METHODS),True,1,300,["name","value"]),(fields["method"]["options"],fields["url"]["required"],fields["timeout"]["min"],fields["timeout"]["max"],[r["key"] for r in fields["headers"]["rows"]]))
        self.assertEqual(["http_get","http_post"],[p["id"] for p in one["presets"]])
        several=self.ok("chain_node_types",type="switch, command,json")["types"]
        self.assertEqual(["switch","command","json"],[t["type"] for t in several])
        self.assertIn("config.cases",several[0]["ports"]);self.assertNotIn("fields",several[1]);self.assertEqual({"action":["get"]},next(f for f in several[2]["fields"] if f["key"]=="path")["only_when"])
        self.assertIn("chain_node_types",self.refused("chain_node_types",type="nope"))
        for name in nodes.SPECS:self.assertLess(len(json.dumps(flows.ai_node_types(node_type=name))),5000,name)
        ai.set_permission_levels({"chain_diagrams_read":"deny"})
        self.assertIn("Deny",self.refused("chain_node_types"));self.assertIn("Deny",self.refused("chain_validate",graph=schema.new_graph()))
    def test_templates_tool_points_at_the_catalog_and_stays_readable(self):
        out=self.ok("chain_templates")
        self.assertEqual(set(nodes.SPECS),set(out["node_types"]));self.assertIn("chain_node_types",out["notes"])
        self.assertIn("nmap-xml-findings",[t["id"] for t in out["templates"]])
        spelled=[v["if"]["properties"]["type"]["const"] for v in out["graph_schema"]["$defs"]["node"]["allOf"]]
        self.assertEqual(list(nodes.LEGACY_TYPES),spelled);self.assertEqual(set(nodes.SPECS),set(out["graph_schema"]["$defs"]["node"]["properties"]["type"]["enum"]))
        self.assertEqual(39,len(schema.JSON_SCHEMA["$defs"]["node"]["allOf"]),"the full schema is not changed by the slim copy")
    def test_validate_does_not_save(self):
        from Cores.Services import playbooks_service as chains
        good=chain(node("m","math",expr="1+1"))
        self.assertEqual({"ok":True,"errors":[],"warnings":[{"node":"m","edge":None,"code":"port_unconnected","message":"m: nothing is connected to 'error'."}],"nodes":2,"edges":1},self.ok("chain_validate",graph=good))
        bad={"schema":2,"nodes":[node("start","start"),node("h","http",url="ftp://x/"),node("sw","switch",cases=[])],"edges":[{"id":"e1","from":"start","port":"nope","to":"h"}]}
        out=self.ok("chain_validate",graph=bad)
        self.assertFalse(out["ok"]);self.assertLessEqual({"bad_config","empty_field","unknown_port"},set(codes(out["errors"])))
        self.assertNotIn("graph",out)
        self.assertEqual([],chains.list_playbooks(),"nothing was stored")
        pid=flows.create("Mine",good)["playbook_id"]
        self.assertTrue(self.ok("chain_validate",graph=good,chain_id=pid)["ok"])
        self.assertTrue(flows.get(pid)["ai_reviewed"],"validating does not touch the review flag")
    def test_node_by_node_edits_mark_the_chain_ai_made_and_unreviewed(self):
        pid=flows.create("Mine",schema.new_graph())["playbook_id"]
        self.assertEqual((False,True),(flows.get(pid)["ai_made"],flows.get(pid)["ai_reviewed"]))
        token=ai.set_client({"id":"c1","label":"Claude Code","provider":"mcp"})
        try:
            a=self.ok("chain_node_add",chain_id=pid,type="input_text",config={"text":"a\nb","format":"lines","var":"xs"},title="Hosts",after="n1")
            self.assertEqual((True,"n2","e1",pid),(a["ok"],a["node_id"],a["edge_id"],a["playbook_id"]))
            got=flows.get(pid)
            self.assertEqual((True,False,"Claude Code"),(got["ai_made"],got["ai_reviewed"],got["ai_client"]))
            flows.mark_reviewed(pid)
            b=self.ok("chain_node_add",chain_id=pid,type="count",after="n2",config={"source":"${xs}"})       # a preset id
            c=self.ok("chain_node_add",chain_id=pid,type="result",config={"label":"n","value":"${count}"},x=1000,y=500)
            self.assertEqual(("n3","e2","n4",""),(b["node_id"],b["edge_id"],c["node_id"],c["edge_id"]))
            self.assertEqual(["unreachable"],codes(c["warnings"]))
            self.assertEqual("e3",self.ok("chain_connect",chain_id=pid,from_node="n3",to_node="n4")["edge_id"])
            self.assertTrue(self.ok("chain_connect",chain_id=pid,from_node="n3",to_node="n4",port="out")["unchanged"])
            self.ok("chain_node_set",chain_id=pid,node_id="n2",config={"text":"a\nb\nc"},title="Three hosts",x=333)
        finally:ai.reset_client(token)
        got=flows.get(pid)
        by_id={n["id"]:n for n in got["graph"]["nodes"]}
        self.assertEqual(("Three hosts",333,160,{"text":"a\nb\nc","format":"lines","var":"xs"}),(by_id["n2"]["title"],by_id["n2"]["x"],by_id["n2"]["y"],by_id["n2"]["config"]))
        self.assertEqual(("collection","Count items",640,160),(by_id["n3"]["type"],by_id["n3"]["title"],by_id["n3"]["x"],by_id["n3"]["y"]))
        self.assertEqual(({"op":"count","source":"${xs}","var":"count"},(1000,500)),({k:by_id["n3"]["config"][k] for k in ("op","source","var")},(by_id["n4"]["x"],by_id["n4"]["y"])))
        self.assertEqual([("n1","out","n2"),("n2","out","n3"),("n3","out","n4")],[(e["from"],e["port"],e["to"]) for e in got["graph"]["edges"]])
        self.assertEqual((True,False,[]),(got["ai_made"],got["ai_reviewed"],got["errors"]),"every small edit resets the review")
        self.assertTrue(flows.plan(pid)["needs_review"])
        self.assertTrue(any("by AI (Claude Code)" in d for d in self.audit("chain_diagram_edit")))
        # A run confirms it works end to end; then removing things.
        flows.mark_reviewed(pid)
        status=flows.wait(flows.run(pid,{"mode":"run","confirmed":True})["run_id"],30)
        self.assertEqual([{"node":"n4","label":"n","value":3}],status["results"])
        self.assertTrue(self.ok("chain_connect",chain_id=pid,from_node="n3",to_node="n4",remove=True)["removed"])
        self.assertIn("no connection",self.refused("chain_connect",chain_id=pid,from_node="n3",to_node="n4",remove=True))
        self.assertEqual(1,self.ok("chain_node_delete",chain_id=pid,node_id="n3")["edges_removed"])
        self.assertEqual(["n1","n2","n4"],[n["id"] for n in flows.get(pid)["graph"]["nodes"]])
        self.assertFalse(flows.get(pid)["ai_reviewed"])
    def test_edits_that_would_break_the_diagram_are_refused_and_change_nothing(self):
        pid=flows.create("Mine",chain(node("m","math",expr="1+1")))["playbook_id"]
        before=flows.get(pid)["graph"]
        for tool,args,needle in (("chain_node_add",{"type":"http"},"URL is empty"),("chain_node_add",{"type":"nope"},"Unknown node type"),("chain_node_add",{"type":"log","config":{"message":"x"},"after":"ghost"},"no node 'ghost'"),
                                 ("chain_node_add",{"type":"log","config":{"message":"x"},"after":"m","port":"nope"},"no output called"),("chain_node_set",{"node_id":"m","config":{"expr":"1+"}},"Expression"),
                                 ("chain_node_set",{"node_id":"ghost","config":{}},"no node 'ghost'"),("chain_node_delete",{"node_id":"start"},"Start node"),("chain_connect",{"from_node":"m","to_node":"start"},"Nothing can connect into"),
                                 ("chain_connect",{"from_node":"m","to_node":"m"},"cannot connect to itself")):
            self.assertIn(needle,self.refused(tool,chain_id=pid,**args),tool)
        self.assertIn("not found",self.refused("chain_node_add",chain_id=9999,type="log",config={"message":"x"}))
        self.assertEqual(before,flows.get(pid)["graph"]);self.assertTrue(flows.get(pid)["ai_reviewed"])
        ai.set_permission_levels({"chain_diagrams_edit":"deny"})
        for tool,args in (("chain_node_add",{"type":"log","config":{"message":"x"}}),("chain_node_set",{"node_id":"m","title":"x"}),("chain_node_delete",{"node_id":"m"}),("chain_connect",{"from_node":"start","to_node":"m"})):
            self.assertIn("Deny",self.refused(tool,chain_id=pid,**args),tool)
        self.assertEqual(before,flows.get(pid)["graph"])
        ai.set_permission_levels({"chain_diagrams_edit":"ask"})
        self.answer="denied"
        self.refused("chain_node_delete",chain_id=pid,node_id="m")
        self.assertEqual(["chain_node_delete"],[a[0] for a in self.asked]);self.assertEqual(before,flows.get(pid)["graph"])
    def test_run_output_is_redacted_masked_and_capped(self):
        api=bridge_api.TargetsAPI()
        for key in ("IPv4","Password"):api.add_key(key,0)
        api.upsert_target(None,"web01","not_used",{"IPv4":"10.0.0.5","Password":"Winter2024!"})
        api.set_live_target(api.targets()[0]["id"])
        g=chain(node("t","input_target",var="tgt"),node("s","input_text",text="login ok --password=Sup3rSecret99 done\n"+"y"*30000,var="text"),node("j","input_text",text='{"host":"a","api_key":"AKIAABCDEFGHIJKLMNOP","rows":[1,2,3]}',format="json",var="obj"),node("tj","json",action="format",source="${tgt}",var="tgt_json"),
                node("r","result",label="Creds seen",value="${text}"),node("r2","result",label="obj",value="${obj}"))
        pid=flows.create("Out",g)["playbook_id"]
        run_id=flows.run(pid,{"mode":"run","confirmed":True})["run_id"]
        self.assertEqual("done",flows.wait(run_id,30)["state"])
        self.assertEqual("Winter2024!",flows.run_status(run_id)["vars"]["tgt"]["password"],"the operator's own status is not masked")
        summary=self.ok("chain_run_output",run_id=run_id)
        self.assertEqual(["run_id","playbook_id","name","mode","state","reason","results","nodes"],list(summary))
        self.assertEqual(["start","t","s","j","tj","r","r2"],[n["node"] for n in summary["nodes"]])
        row=next(n for n in summary["nodes"] if n["node"]=="j")
        self.assertEqual({"node":"j","state":"success","branch":"out","visits":1,"error":"","stdout_chars":len('{"host":"a","api_key":"AKIAABCDEFGHIJKLMNOP","rows":[1,2,3]}'),"stderr_chars":0,"has_parsed":True,"vars_set":["obj"]},row)
        self.assertEqual(["Creds seen","obj"],[r["label"] for r in summary["results"]])
        text=json.dumps(summary)
        for secret in ("Sup3rSecret99","Winter2024!","AKIAABCDEFGHIJKLMNOP"):self.assertNotIn(secret,text)
        self.assertLess(len(text),20000)
        target=self.ok("chain_run_output",run_id=run_id,node_id="t")["output"]
        self.assertEqual("10.0.0.5",target["parsed"]["ipv4"]);self.assertEqual(target["parsed"]["password"],target["parsed"]["values"]["password"])
        self.assertIn("hidden",target["parsed"]["password"]);self.assertNotIn("Winter2024!",json.dumps(target))
        big=self.ok("chain_run_output",run_id=run_id,node_id="s",max_chars=500)["output"]
        self.assertEqual((500,True),(len(big["stdout"]),big["parsed_truncated"]));self.assertLessEqual(len(big["parsed"]),500)
        full=self.ok("chain_run_output",run_id=run_id,node_id="s",max_chars=40000)["output"]
        self.assertNotIn("Sup3rSecret99",json.dumps(full));self.assertIn("login ok",full["parsed"])
        obj=self.ok("chain_run_output",run_id=run_id,node_id="j")["output"]
        self.assertEqual(("a",[1,2,3],["obj"]),(obj["parsed"]["host"],obj["parsed"]["rows"],list(obj["vars_set"])));self.assertNotIn("AKIA",json.dumps(obj))
        as_text=self.ok("chain_run_output",run_id=run_id,node_id="tj")["output"]
        self.assertIn('"ipv4": "10.0.0.5"',as_text["stdout"]);self.assertIn('"password": "[hidden]"',as_text["stdout"],"a secret-keyed value is hidden in JSON text too")
        self.assertNotIn("Winter2024!",json.dumps(as_text))
        self.assertNotIn("Winter2024!",json.dumps(self.ok("chain_run_status",run_id=run_id)))
        self.assertEqual({"node","state","branch","visits","duration_ms","error","exit_code","stdout","stderr","parsed","parsed_truncated","vars_set","resolved","result"},set(self.ok("chain_run_output",run_id=run_id,node_id="r")["output"]))
        self.assertIn("no node 'ghost'",self.refused("chain_run_output",run_id=run_id,node_id="ghost"));self.assertIn("No such run",self.refused("chain_run_output",run_id="nope"))
        ai.set_permission_levels({"chain_diagrams_read":"deny"})
        self.assertIn("Deny",self.refused("chain_run_output",run_id=run_id))
    def test_every_tool_is_refused_while_the_app_is_locked(self):
        pid=flows.create("Mine",chain(node("m","math",expr="1+1")))["playbook_id"]
        common_db.set_locked(True)
        try:
            for tool,args in (("chain_node_types",{}),("chain_validate",{"graph":schema.new_graph()}),("chain_node_add",{"chain_id":pid,"type":"log","config":{"message":"x"}}),("chain_node_set",{"chain_id":pid,"node_id":"m","title":"x"}),
                              ("chain_node_delete",{"chain_id":pid,"node_id":"m"}),("chain_connect",{"chain_id":pid,"from_node":"start","to_node":"m"}),("chain_run_output",{"run_id":"x"})):
                self.assertIn("locked",self.refused(tool,**args),tool)
        finally:common_db.set_locked(False)
        self.assertEqual(2,len(flows.get(pid)["graph"]["nodes"]))
    def test_the_authoring_guide_and_tool_description_cover_the_new_nodes(self):
        guide=flows.ai_guide()["guide"]
        for name in nodes.FIELD_TYPES:
            line=next(l for l in guide.splitlines() if l.startswith("- %s: "%name))
            for field in nodes.SPECS[name]["fields"]:
                if field["type"]=="select":
                    note=guide.splitlines()[guide.splitlines().index(line)+1]
                    for option in field["options"]:self.assertIn(str(option["value"]),note,"%s.%s"%(name,field["key"]))
        self.assertIn("300",guide);self.assertIn('stores its result in that variable',guide)
        text={t.name:t for t in chat._list_tools()}["chain_create"].description
        self.assertIn("chain_node_types",text);self.assertIn('"schema":2',text)
if __name__=="__main__":
    unittest.main()
