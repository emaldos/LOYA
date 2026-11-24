import copy,os,re,sys,unittest
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from _isolate import IsolatedData
from Cores.Services import flow_schema as schema
from Cores.Services import flow_demos as demos
# Node box geometry of the editor (UI/js/components/flow-model.js FLOW_GEOM / flowNodeSize).
GEOM={"w":240,"head":46,"sum":24,"row":22,"pad":10}
GAP=20
# Every node type except these two is used by at least one demo. A sub-chain needs the id of a chain saved on this
# machine (an unset one is a validation error) and a script node needs the operator's sandbox policy.
NOT_COVERED={"subchain","script"}
FORBIDDEN=[r"\brm\s+-", r"\bmkfs", r"\bdd\s+if=", r":\(\)\s*\{", r"\bshutdown\b", r"\breboot\b", r"\bhydra\b", r"\bmedusa\b",
           r"sqlmap\s.*--os", r"\bmsfconsole\b", r"\bmsfvenom\b", r"\bpoweroff\b", r"\bhalt\b", r"\bformat\s+[a-z]:", r"\bdel\s+/", r"Remove-Item",
           r">\s*/dev/sd", r"\bchmod\s+777", r"--script\s*=?\s*(brute|exploit|dos)"]
BAD_CHARS=("\u2014","\u2013","\u2026","\u00b7")   # em dash, en dash, ellipsis, middle dot
SAFE_HOST=re.compile(r"^(?:\{IPv4\}|\{Host\}|\{Domain\}|(?:scanme\.)?nmap\.org|(?:[a-z0-9-]+\.)*example\.com)$",re.I)
def size(node):
    if node["type"]=="comment":
        cfg=node.get("config") or {}
        return min(800,max(120,cfg.get("w",220))),min(600,max(60,cfg.get("h",120)))
    ports=len(schema.node_ports(node)["out"])
    return GEOM["w"],GEOM["head"]+GEOM["sum"]+max(1,ports)*GEOM["row"]+GEOM["pad"]
def strings(value):
    if isinstance(value,str):yield value
    elif isinstance(value,dict):
        for key,item in value.items():
            yield from strings(key);yield from strings(item)
    elif isinstance(value,list):
        for item in value:yield from strings(item)
class FlowDemoTests(unittest.TestCase):
    def setUp(self):
        self.isolated=IsolatedData();self.isolated.start()
    def tearDown(self):
        self.isolated.stop()
    def test_registry_shape(self):
        self.assertGreaterEqual(len(demos.DEMOS),6)
        ids=[d["id"] for d in demos.DEMOS];names=[d["name"] for d in demos.DEMOS]
        self.assertEqual(len(ids),len(set(ids)));self.assertEqual(len(names),len(set(names)))
        for entry in demos.DEMOS:
            self.assertEqual({"id","name","description","tags","graph"},set(entry))
            self.assertRegex(entry["id"],r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
            self.assertTrue(entry["name"].strip() and entry["description"].strip())
            self.assertTrue(entry["tags"])
            for tag in entry["tags"]:self.assertRegex(tag,r"^[a-z0-9-]{1,20}$")
    def test_every_demo_is_valid_with_no_warnings(self):
        for entry in demos.DEMOS:
            with self.subTest(demo=entry["id"]):
                result=schema.validate_graph(entry["graph"])
                self.assertTrue(result["ok"],result["errors"])
                self.assertEqual([],result["errors"]);self.assertEqual([],result["warnings"])
                # normalizing changes nothing that matters: same nodes, edges and positions
                self.assertEqual([n["id"] for n in entry["graph"]["nodes"]],[n["id"] for n in result["graph"]["nodes"]])
                self.assertEqual(len(entry["graph"]["edges"]),len(result["graph"]["edges"]))
    def test_ids_edges_and_ports(self):
        for entry in demos.DEMOS:
            graph=entry["graph"]
            with self.subTest(demo=entry["id"]):
                node_ids=[n["id"] for n in graph["nodes"]];edge_ids=[e["id"] for e in graph["edges"]]
                self.assertEqual(len(node_ids),len(set(node_ids)));self.assertEqual(len(edge_ids),len(set(edge_ids)))
                by_id={n["id"]:n for n in graph["nodes"]}
                self.assertEqual(1,sum(1 for n in graph["nodes"] if n["type"]=="start"))
                for edge in graph["edges"]:
                    self.assertIn(edge["from"],by_id);self.assertIn(edge["to"],by_id)
                    self.assertIn(edge["port"],schema.node_ports(by_id[edge["from"]])["out"],edge)
                    self.assertNotIn(by_id[edge["to"]]["type"],("start","comment"))
    def test_every_node_reachable_from_start(self):
        for entry in demos.DEMOS:
            graph=entry["graph"]
            with self.subTest(demo=entry["id"]):
                start=next(n["id"] for n in graph["nodes"] if n["type"]=="start")
                seen={start};stack=[start]
                while stack:
                    current=stack.pop()
                    for edge in graph["edges"]:
                        if edge["from"]==current and edge["to"] not in seen:
                            seen.add(edge["to"]);stack.append(edge["to"])
                for node in graph["nodes"]:
                    if node["type"]!="comment":self.assertIn(node["id"],seen,node["title"])
    def test_exactly_one_sticky_note(self):
        for entry in demos.DEMOS:
            with self.subTest(demo=entry["id"]):
                notes=[n for n in entry["graph"]["nodes"] if n["type"]=="comment"]
                self.assertEqual(1,len(notes))
                cfg=notes[0]["config"]
                self.assertTrue(cfg["text"].strip())
                self.assertIn(cfg["color"],schema.COMMENT_COLORS)
                self.assertTrue(120<=cfg["w"]<=800 and 60<=cfg["h"]<=600)
    def test_no_overlapping_boxes(self):
        for entry in demos.DEMOS:
            nodes=entry["graph"]["nodes"]
            with self.subTest(demo=entry["id"]):
                boxes=[(n["title"],n["x"],n["y"])+size(n) for n in nodes]
                for i,a in enumerate(boxes):
                    for b in boxes[i+1:]:
                        apart=(a[1]+a[3]+GAP<=b[1] or b[1]+b[3]+GAP<=a[1] or a[2]+a[4]+GAP<=b[2] or b[2]+b[4]+GAP<=a[2])
                        self.assertTrue(apart,"%r and %r overlap or touch"%(a[0],b[0]))
                for n in nodes:self.assertTrue(n["x"]>=0 and n["y"]>=0)
    def test_left_to_right(self):
        for entry in demos.DEMOS:
            by_id={n["id"]:n for n in entry["graph"]["nodes"]}
            with self.subTest(demo=entry["id"]):
                for edge in entry["graph"]["edges"]:
                    source=by_id[edge["from"]];target=by_id[edge["to"]]
                    self.assertGreaterEqual(target["x"],source["x"],"%s -> %s goes backwards"%(source["title"],target["title"]))
                    if target["x"]==source["x"]:self.assertNotEqual(target["y"],source["y"])
    def test_node_type_coverage(self):
        used=set()
        for entry in demos.DEMOS:used|={n["type"] for n in entry["graph"]["nodes"]}
        self.assertEqual(set(schema.NODE_TYPES)-NOT_COVERED,used)
        self.assertEqual(set(),used-set(schema.NODE_TYPES))
    def test_demo_returns_a_deep_copy(self):
        entry=demos.DEMOS[0]
        before=copy.deepcopy(entry["graph"])
        graph=demos.demo(entry["id"])
        self.assertEqual(before,graph)
        graph["nodes"][0]["title"]="changed";graph["nodes"][1]["config"]["changed"]=True;graph["edges"].clear()
        self.assertEqual(before,entry["graph"])
        self.assertIsNot(demos.demo(entry["id"]),demos.demo(entry["id"]))
    def test_unknown_demo(self):
        self.assertIsNone(demos.demo("no-such-demo"));self.assertIsNone(demos.demo(None));self.assertIsNone(demos.demo(""))
    def test_summaries(self):
        rows=demos.summaries()
        self.assertEqual([d["id"] for d in demos.DEMOS],[r["id"] for r in rows])
        for row,entry in zip(rows,demos.DEMOS):
            self.assertEqual({"id","name","description","tags","node_count"},set(row))
            self.assertEqual(len(entry["graph"]["nodes"]),row["node_count"])
            self.assertEqual(entry["tags"],row["tags"])
            row["tags"].append("x")
            self.assertNotIn("x",entry["tags"])
    def test_flow_schema_does_not_import_demos(self):
        with open(schema.__file__,encoding="utf-8") as handle:self.assertNotIn("flow_demos",handle.read())
    def test_no_forbidden_text_or_characters(self):
        for entry in demos.DEMOS:
            texts=list(strings(entry["graph"]))+[entry["name"],entry["description"]]+list(entry["tags"])
            with self.subTest(demo=entry["id"]):
                for text in texts:
                    for char in BAD_CHARS:self.assertNotIn(char,text)
                    for pattern in FORBIDDEN:self.assertIsNone(re.search(pattern,text,re.I),"%r in %r"%(pattern,text[:120]))
    def test_end_messages_are_plain_text(self):
        # an End node's message is shown as written: ${values} would stay unexpanded
        for entry in demos.DEMOS:
            for node in entry["graph"]["nodes"]:
                if node["type"]=="end":self.assertNotIn("${",node["config"]["message"],node["title"])
    def test_commands_only_touch_the_live_target(self):
        for entry in demos.DEMOS:
            for node in entry["graph"]["nodes"]:
                if node["type"]!="command":continue
                for command in node["config"]["commands"]:
                    text=command["text"]
                    with self.subTest(demo=entry["id"],command=text):
                        self.assertIn("{IPv4}",text)
                        self.assertIsNone(re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b",text))
                        for host in re.findall(r"https?://([^/\s:]+)",text):self.assertRegex(host,SAFE_HOST)
                        self.assertNotRegex(text,r"[;&|`]|\$\(")
                        self.assertLessEqual(node["config"]["timeout"],1800)
    def test_hosts_are_placeholders_or_demo_hosts(self):
        for entry in demos.DEMOS:
            for node in entry["graph"]["nodes"]:
                cfg=node["config"]
                with self.subTest(demo=entry["id"],node=node["title"]):
                    if node["type"]=="http":
                        url=cfg["url"]
                        self.assertRegex(url,r"^(?:https?://|\$\{)")
                        self.assertLessEqual(cfg["timeout"],30)
                        for host in re.findall(r"https?://([^/\s:]+)",url):self.assertRegex(host,SAFE_HOST)
                    if node["type"] in("input_text","map"):
                        text=cfg.get("text") if node["type"]=="input_text" else cfg.get("template")
                        for host in re.findall(r"https?://([^/\s:]+)",text):
                            if "${" not in host:self.assertRegex(host,SAFE_HOST)
                        for line in text.splitlines():
                            if re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}",line.strip(),re.I):self.assertRegex(line.strip(),SAFE_HOST)
                    if node["type"]=="file_write":
                        self.assertTrue(cfg["path"].startswith("~/loya-demos/"),cfg["path"])
class DemoServiceTests(unittest.TestCase):
    """Opening a demo copies it into the user's chains; the built-in original is never stored or changed."""
    def setUp(self):
        self.iso=IsolatedData();self.iso.start()
    def tearDown(self):
        self.iso.stop()
    def test_catalog_lists_the_demos_without_graphs(self):
        from Cores.Services import flow_service as flows
        rows=flows.catalog()["demos"]
        self.assertEqual([d["id"] for d in demos.DEMOS],[d["id"] for d in rows])
        self.assertTrue(all("graph" not in d and d["node_count"]>0 for d in rows))
    def test_nothing_is_stored_until_a_demo_is_opened(self):
        from Cores.Services import flow_service as flows
        flows.catalog();flows.demo(demos.DEMOS[0]["id"])
        self.assertEqual([],flows.list_flows())
    def test_copy_is_a_new_unreviewed_demo_chain(self):
        from Cores.Services import flow_service as flows
        first=demos.DEMOS[0]
        before=copy.deepcopy(first["graph"])
        res=flows.create_from_demo(first["id"])
        got=flows.get(res["playbook_id"])
        self.assertEqual(first["name"],got["name"]);self.assertFalse(got["derived"])
        self.assertFalse(got["ai_made"]);self.assertFalse(got["ai_reviewed"]);self.assertEqual("demo",got["origin"])
        self.assertEqual([],got["errors"])
        self.assertEqual(len(first["graph"]["nodes"]),len(got["graph"]["nodes"]))
        row=[r for r in flows.list_flows() if r["playbook_id"]==res["playbook_id"]][0]
        self.assertEqual("demo",row["origin"]);self.assertFalse(row["ai_reviewed"])
        # editing the copy never touches the built-in original
        graph=got["graph"];graph["nodes"]=[n for n in graph["nodes"] if n["type"]=="start"];graph["edges"]=[]
        flows.save(res["playbook_id"],graph)
        self.assertEqual(before,first["graph"]);self.assertEqual(before,flows.demo(first["id"]))
        # a second copy is a separate chain; review clears the demo origin
        again=flows.create_from_demo(first["id"],"My copy")
        self.assertNotEqual(res["playbook_id"],again["playbook_id"]);self.assertEqual("My copy",flows.get(again["playbook_id"])["name"])
        flows.mark_reviewed(again["playbook_id"])
        self.assertEqual("",flows.get(again["playbook_id"])["origin"])
    def test_unknown_demo_is_refused(self):
        from Cores.Services import flow_service as flows
        with self.assertRaises(ValueError):flows.create_from_demo("no-such-demo")
        with self.assertRaises(ValueError):flows.demo("no-such-demo")
        self.assertEqual([],flows.list_flows())
    def test_mcp_templates_carry_the_demos(self):
        from Cores.Services import flow_service as flows
        out=flows.ai_templates()
        self.assertEqual([d["id"] for d in demos.DEMOS],[d["id"] for d in out["demos"]])
        self.assertTrue(all("nodes" in d["graph"] for d in out["demos"]))
        self.assertIn("host-alive-portscan-web",[t["id"] for t in out["templates"]])
    def test_other_origins(self):
        from Cores.Services import flow_service as flows
        self.assertEqual("",flows._origin(None))
        self.assertEqual("ai",flows._origin({"ai_made":True,"ai_reviewed":False,"ai_client":"x"}))
        self.assertEqual("import",flows._origin({"ai_made":False,"ai_reviewed":False,"ai_client":"import"}))
        self.assertEqual("",flows._origin({"ai_made":False,"ai_reviewed":True,"ai_client":"demo"}))
if __name__=="__main__":unittest.main()
