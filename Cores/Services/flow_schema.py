"""Chain diagrams ("flows"): the graph schema, validation/normalization, templates and the import/export bundle.
Pure data code: no DB, no subprocess. Heavier modules (terminal_service) are imported lazily so this stays cheap to import."""
import copy,json,os,re
from datetime import datetime,timezone
from Cores.Services import flow_nodes as _nodes
SCHEMA_VERSION=2   # 2: the field-driven node types of flow_nodes (http, switch, merge, math, ...). A schema-1 graph is a valid schema-2 graph.
LIMITS={
    "nodes":200,"edges":400,"script_bytes":65536,"commands_per_node":20,"command_bytes":4096,
    "branches":12,"conditions":12,"regex_chars":500,"graph_bytes":524288,
    "run_timeout_min":10,"run_timeout_max":86400,"max_visits_min":1,"max_visits_max":2000,
    "node_timeout_min":1,"node_timeout_max":7200,"wait_max":3600,"approval_timeout_max":86400,
    "foreach_items_max":1000,"assign_max":40,"title_chars":80,"text_chars":8192,"id_chars":40,"port_chars":24,
}
ID_RE=re.compile(r"^[A-Za-z0-9_-]{1,40}$")
PORT_RE=re.compile(r"^[A-Za-z0-9_-]{1,24}$")
VAR_RE=re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,39}$")
_PATH_RE=re.compile(r"^[A-Za-z0-9_.\[\]*:-]{1,200}$")
SOURCES=("exit_code","stdout","stderr","output","var","parsed","line_count","match_count","port_open","host_up")
OPS=("contains","not_contains","equals","not_equals","starts_with","ends_with","regex","not_regex",
     "eq","ne","gt","ge","lt","le","is_empty","not_empty","is_true","is_false")
PARSE_MODES=("regex","tool","jsonpath")
PARSE_TOOLS=("nmap","ping","lines","json","keyvalue","ips","urls")
SCRIPT_LANGUAGES=("python","bash","powershell")
OUTPUT_ACTIONS=("note_append","finding_draft","evidence","notify")
SEVERITIES=("critical","high","medium","low","info")
COMMENT_COLORS=("yellow","blue","green","red","purple","gray")
SPLIT_MODES=("lines","comma","json","auto")
SCRIPT_ISOLATION=("inherit","sandboxed","allow")   # per-diagram override of the global script isolation policy
DEFAULT_SETTINGS={"shell":"","run_timeout":1800,"max_visits":200,"on_error":"stop","script_isolation":"inherit"}
_DEFAULT_COND={"source":"output","field":"","op":"contains","value":"","ci":True}
# Every node type, legacy and field-driven, comes from flow_nodes.SPECS (the catalog the page and the MCP tools use too).
NODE_TYPES={name:{"label":spec["label"],"category":spec["category"],"ports":spec["ports"] if isinstance(spec["ports"],str) else list(spec["ports"]),
                  "defaults":copy.deepcopy(spec["defaults"]),"description":spec["description"]} for name,spec in _nodes.SPECS.items()}
_NO_INPUT=tuple(name for name,spec in _nodes.SPECS.items() if not spec["input"])
_OPTIONAL_PORTS=("fail","error")   # a missing edge here is only worth a warning (plus a decision's else port)
# ---------------------------------------------------------------- small helpers
def _text(value,limit=None):
    if value is None:value=""
    if not isinstance(value,str):
        value=str(value) if isinstance(value,(int,float,bool)) else ""
    value=value.replace("\x00","")
    return value if limit is None else value[:limit]
def _num(value,default,low,high,integer=True):
    if isinstance(value,bool):value=default
    if isinstance(value,str):
        try:value=float(value.strip())
        except ValueError:value=default
    if not isinstance(value,(int,float)) or value!=value or value in(float("inf"),float("-inf")):value=default
    value=max(low,min(high,value))
    return int(value) if integer else float(value)
def _bool(value,default):
    if isinstance(value,bool):return value
    if isinstance(value,(int,float)):return bool(value)
    if isinstance(value,str) and value.strip().lower() in("true","false","1","0","yes","no"):return value.strip().lower() in("true","1","yes")
    return default
def _coord(value):
    return _num(value,0,-100000,100000,integer=False)
def _tidy(number):
    return int(number) if float(number).is_integer() else round(float(number),2)
def _issue(code,message,node=None,edge=None):
    return {"node":node,"edge":edge,"code":code,"message":message}
def _defaults(node_type):
    return copy.deepcopy(NODE_TYPES[node_type]["defaults"])
def new_graph():
    return {"schema":SCHEMA_VERSION,"settings":dict(DEFAULT_SETTINGS),
            "nodes":[{"id":"n1","type":"start","title":"Start","x":40,"y":160,"config":_defaults("start")}],
            "edges":[],"viewport":{"x":0,"y":0,"zoom":1}}
def _port_names(values):
    names=[]
    for value in values:
        if isinstance(value,str) and PORT_RE.match(value) and value not in names:names.append(value)
    return names
def node_ports(node):
    """{"in":bool,"out":[port names]} for a node (tolerates a node that was never normalized)."""
    if not isinstance(node,dict):return {"in":False,"out":[]}
    node_type=node.get("type")
    spec=NODE_TYPES.get(node_type) if isinstance(node_type,str) else None
    if spec is None:return {"in":False,"out":[]}
    config=node.get("config") if isinstance(node.get("config"),dict) else {}
    if node_type=="script":
        branches=config.get("branches") if isinstance(config.get("branches"),list) else ["out"]
        out=[name for name in _port_names(branches) if name!="error"] or ["out"]
        out.append("error")
    elif node_type=="decision":
        branches=config.get("branches") if isinstance(config.get("branches"),list) else []
        out=_port_names([b.get("name") for b in branches if isinstance(b,dict)])
        other=config.get("else") if isinstance(config.get("else"),str) and PORT_RE.match(config.get("else")) else "else"
        if other not in out:out.append(other)
    elif _nodes.SPECS[node_type].get("dynamic"):out=_nodes.dynamic_ports(node_type,config)
    else:out=list(spec["ports"])
    return {"in":node_type not in _NO_INPUT,"out":out}
# ---------------------------------------------------------------- per-type config normalization
class _Ctx:
    """Collects issues for one node while its config is normalized."""
    def __init__(self,node_id,errors,warnings):
        self.node=node_id;self.errors=errors;self.warnings=warnings
    def error(self,code,message):self.errors.append(_issue(code,message,node=self.node))
    def warn(self,code,message):self.warnings.append(_issue(code,message,node=self.node))
def _enum(ctx,config,key,allowed,default,label):
    value=config.get(key,default)
    if value in allowed:return value
    ctx.error("bad_config","%s must be one of: %s."%(label,", ".join(str(a) for a in allowed)))
    return default
def _check_regex(ctx,pattern,flags,where):
    if len(pattern)>LIMITS["regex_chars"]:
        ctx.error("invalid_regex","%s: the regex is longer than %d characters."%(where,LIMITS["regex_chars"]));return
    try:
        from Cores.Services import flow_rules
        flow_rules.check_regex(pattern,flags)
    except ValueError as exc:ctx.error("invalid_regex","%s: %s"%(where,exc))
    except Exception as exc:ctx.error("invalid_regex","%s: the regex could not be checked (%s)."%(where,exc))
def _flags(value):
    return "".join(ch for ch in "imsx" if ch in _text(value,16).lower())
def _command_id(value):
    if isinstance(value,bool) or value is None:return None
    if isinstance(value,int):return value
    if isinstance(value,str) and re.match(r"^-?\d{1,12}$",value.strip()):return int(value.strip())
    return None
def _cfg_start(ctx,config):
    return {"trigger":_enum(ctx,config,"trigger",("manual","caller","live"),"manual","Trigger")}
def _cfg_command(ctx,config):
    raw=config.get("commands")
    if isinstance(raw,str):raw=[{"text":raw}]
    if not isinstance(raw,list):raw=[]
    commands=[]
    for item in raw:
        if isinstance(item,str):item={"text":item}
        if not isinstance(item,dict):continue
        text=_text(item.get("text")).strip()
        if not text:continue
        if len(text.encode("utf-8","replace"))>LIMITS["command_bytes"]:
            ctx.error("command_too_long","A command is longer than %d bytes."%LIMITS["command_bytes"])
            text=text.encode("utf-8","replace")[:LIMITS["command_bytes"]].decode("utf-8","ignore")
        commands.append({"text":text,"command_id":_command_id(item.get("command_id")),"src":_text(item.get("src"),40),"label":_text(item.get("label"),120)})
    if len(commands)>LIMITS["commands_per_node"]:
        ctx.error("too_many_commands","A command node holds at most %d commands."%LIMITS["commands_per_node"])
        commands=commands[:LIMITS["commands_per_node"]]
    if not commands:ctx.error("empty_command","This command node has no command.")
    for command in commands:
        if "${raw:" in command["text"]:ctx.warn("raw_in_command","Unquoted value in a command: %s"%command["text"][:120])
        if _is_destructive(command["text"]):ctx.warn("destructive_command","Possibly destructive command: %s"%command["text"][:120])
    return {"commands":commands,"mode":_enum(ctx,config,"mode",("sequence","parallel"),"sequence","Mode"),
            "stop_on_fail":_bool(config.get("stop_on_fail"),True),
            "timeout":_num(config.get("timeout"),300,LIMITS["node_timeout_min"],LIMITS["node_timeout_max"]),
            "shell":_text(config.get("shell"),80).strip()}
def _is_destructive(text):
    try:
        from Cores.Services import terminal_service
        return bool(terminal_service.command_is_destructive(text))
    except Exception:return False
def _branch_names(ctx,values,reserved=()):
    """Valid, unique port names from a list; reports bad/duplicate ones."""
    names=[]
    for value in values:
        name=_text(value,60).strip()
        if not PORT_RE.match(name):
            ctx.error("bad_port_name","Branch name %r is not valid (letters, digits, _ and -, up to %d characters)."%(name,LIMITS["port_chars"]));continue
        if name in names or name in reserved:
            ctx.error("duplicate_port","Branch name %r is used twice."%name);continue
        names.append(name)
    return names
def _cfg_script(ctx,config):
    code=_text(config.get("code")).replace("\r\n","\n").replace("\r","\n")
    if len(code.encode("utf-8","replace"))>LIMITS["script_bytes"]:
        ctx.error("script_too_large","The script is larger than %d KB."%(LIMITS["script_bytes"]//1024))
        code=code.encode("utf-8","replace")[:LIMITS["script_bytes"]].decode("utf-8","ignore")
    if not code.strip():ctx.error("empty_script","This script node has no code.")
    raw=config.get("branches") if isinstance(config.get("branches"),list) else ["out"]
    if len(raw)>LIMITS["branches"]:
        ctx.error("too_many_branches","A script has at most %d branches."%LIMITS["branches"]);raw=raw[:LIMITS["branches"]]
    branches=_branch_names(ctx,raw,reserved=("error",)) or ["out"]
    return {"language":_enum(ctx,config,"language",SCRIPT_LANGUAGES,"python","Language"),"code":code,"branches":branches,
            "timeout":_num(config.get("timeout"),60,LIMITS["node_timeout_min"],LIMITS["node_timeout_max"]),
            "network":_bool(config.get("network"),False)}
def _cond(ctx,raw,where):
    if not isinstance(raw,dict):
        ctx.error("bad_condition","%s: a condition is not an object."%where);return None
    source=raw.get("source","output");op=raw.get("op","contains")
    if source not in SOURCES:
        ctx.error("bad_condition","%s: unknown condition source %r."%(where,source));return None
    if op not in OPS:
        ctx.error("bad_condition","%s: unknown operator %r."%(where,op));return None
    cond={"source":source,"field":_text(raw.get("field"),LIMITS["regex_chars"]+1) if source=="match_count" else _text(raw.get("field"),200).strip(),
          "op":op,"value":_text(raw.get("value"),LIMITS["text_chars"]),"ci":_bool(raw.get("ci"),True)}
    flags="i" if cond["ci"] else ""
    if source in("port_open","host_up") and op not in("is_true","is_false"):cond["op"]="is_true"
    if source=="port_open":
        port=_text(cond["value"]).strip()
        if not port.startswith("${") and not(port.isdigit() and 1<=int(port)<=65535):
            ctx.error("bad_condition","%s: 'port is open' needs a port number from 1 to 65535."%where)
    if source=="var" and not cond["field"]:ctx.error("bad_condition","%s: the variable name is missing."%where)
    if source=="match_count":
        if not cond["field"]:ctx.error("invalid_regex","%s: the regex to count is empty."%where)
        else:_check_regex(ctx,cond["field"],flags,where)
    if cond["op"] in("regex","not_regex"):
        if not cond["value"]:ctx.error("invalid_regex","%s: the regex is empty."%where)
        else:_check_regex(ctx,cond["value"],flags,where)
    if cond["op"] in("eq","ne","gt","ge","lt","le") and "${" not in cond["value"]:
        try:float(cond["value"].strip())
        except ValueError:ctx.error("bad_condition","%s: %r is not a number."%(where,cond["value"][:40]))
    return cond
def _cfg_decision(ctx,config):
    raw=config.get("branches") if isinstance(config.get("branches"),list) else []
    if len(raw)>LIMITS["branches"]:
        ctx.error("too_many_branches","A decision has at most %d branches."%LIMITS["branches"]);raw=raw[:LIMITS["branches"]]
    branches=[];seen=[]
    for item in raw:
        if not isinstance(item,dict):
            ctx.error("bad_config","A decision branch is not an object.");continue
        name=_branch_names(ctx,[item.get("name")],reserved=seen)
        if not name:continue
        name=name[0];seen.append(name)
        conditions_raw=item.get("conditions") if isinstance(item.get("conditions"),list) else []
        if len(conditions_raw)>LIMITS["conditions"]:
            ctx.error("too_many_conditions","Branch %r has more than %d conditions."%(name,LIMITS["conditions"]))
            conditions_raw=conditions_raw[:LIMITS["conditions"]]
        conditions=[c for c in (_cond(ctx,entry,"Branch %r"%name) for entry in conditions_raw) if c is not None]
        if not conditions:ctx.error("empty_branch","Branch %r has no condition, so it can never be taken."%name)
        match=item.get("match","all")
        if match not in("all","any"):
            ctx.error("bad_config","Branch %r: match must be 'all' or 'any'."%name);match="all"
        branches.append({"name":name,"match":match,"conditions":conditions})
    if not branches:ctx.error("empty_decision","This decision has no branch.")
    other=_text(config.get("else","else"),60).strip() or "else"
    if not PORT_RE.match(other):
        ctx.error("bad_port_name","The else branch name %r is not valid."%other);other="else"
    if other in seen:
        ctx.error("duplicate_port","The else branch has the same name as branch %r."%other)
        other=next(candidate for candidate in ["else"]+["else%d"%i for i in range(2,40)] if candidate not in seen)
    return {"branches":branches,"else":other}
def _assign_from(ctx,raw):
    rows=[]
    for item in (raw if isinstance(raw,list) else [])[:LIMITS["assign_max"]]:
        if not isinstance(item,dict):continue
        name=_text(item.get("var"),60).strip()
        if not VAR_RE.match(name):
            ctx.error("bad_var","Variable name %r is not valid (letters, digits and _, not starting with a digit)."%name);continue
        rows.append((name,item))
    return rows
def _cfg_parse(ctx,config):
    mode=_enum(ctx,config,"mode",PARSE_MODES,"regex","Parse mode")
    source=_text(config.get("source","stdout"),200).strip() or "stdout"
    if source not in("stdout","stderr","output") and not _PATH_RE.match(source):
        ctx.error("bad_config","Parse source must be stdout, stderr, output or a variable name.");source="stdout"
    pattern=_text(config.get("pattern"),LIMITS["regex_chars"]+1);flags=_flags(config.get("flags","i"))
    tool=config.get("tool","nmap")
    if tool not in PARSE_TOOLS:
        if mode=="tool":ctx.error("bad_config","Unknown parser %r. Use one of: %s."%(tool,", ".join(PARSE_TOOLS)))
        tool="nmap"
    if mode=="regex":
        if not pattern:ctx.error("invalid_regex","The parse regex is empty.")
        else:_check_regex(ctx,pattern,flags,"Parse")
    var=_text(config.get("var","parsed"),60).strip()
    if var and not VAR_RE.match(var):
        ctx.error("bad_var","Variable name %r is not valid."%var);var="parsed"
    assign=[{"var":name,"from":_text(item.get("from"),200).strip()} for name,item in _assign_from(ctx,config.get("assign"))]
    return {"mode":mode,"source":source,"pattern":pattern[:LIMITS["regex_chars"]],"flags":flags,"tool":tool,
            "path":_text(config.get("path"),200).strip(),"assign":assign,"var":var}
def _cfg_set(ctx,config):
    return {"assign":[{"var":name,"value":_text(item.get("value"),LIMITS["text_chars"])} for name,item in _assign_from(ctx,config.get("assign"))]}
def _cfg_foreach(ctx,config):
    items=_text(config.get("items"),LIMITS["text_chars"])
    if not items.strip():ctx.error("empty_items","This for-each has nothing to loop over.")
    out={"items":items,"max_items":_num(config.get("max_items"),50,1,LIMITS["foreach_items_max"]),
         "split":_enum(ctx,config,"split",SPLIT_MODES,"auto","Split")}
    for key,default in(("item_var","item"),("index_var","index")):
        name=_text(config.get(key,default),60).strip() or default
        if not VAR_RE.match(name):
            ctx.error("bad_var","Variable name %r is not valid."%name);name=default
        out[key]=name
    return {"items":out["items"],"item_var":out["item_var"],"index_var":out["index_var"],"max_items":out["max_items"],"split":out["split"]}
def _cfg_wait(ctx,config):
    return {"seconds":_tidy(_num(config.get("seconds"),5,0,LIMITS["wait_max"],integer=False))}
def _cfg_approval(ctx,config):
    return {"message":_text(config.get("message","Continue?"),2000),"timeout":_num(config.get("timeout"),0,0,LIMITS["approval_timeout_max"])}
def _cfg_output(ctx,config):
    report_id=_command_id(config.get("report_id"))
    return {"action":_enum(ctx,config,"action",OUTPUT_ACTIONS,"notify","Output action"),"note_name":_text(config.get("note_name"),200),
            "report_id":report_id,"title":_text(config.get("title"),200),
            "severity":_enum(ctx,config,"severity",SEVERITIES,"info","Severity"),
            "content":_text(config.get("content","${last.stdout}"),LIMITS["text_chars"])}
def _cfg_subchain(ctx,config):
    playbook_id=_command_id(config.get("playbook_id"))
    if playbook_id is None:ctx.error("subchain_unset","This sub-chain node has no chain selected.")
    return {"playbook_id":playbook_id,"pass_vars":_bool(config.get("pass_vars"),True)}
def _cfg_end(ctx,config):
    return {"status":_enum(ctx,config,"status",("success","fail"),"success","End status"),"message":_text(config.get("message"),2000)}
def _cfg_comment(ctx,config):
    color=config.get("color","yellow")
    return {"text":_text(config.get("text"),LIMITS["text_chars"]),"color":color if color in COMMENT_COLORS else "yellow",
            "w":_num(config.get("w"),220,80,1200),"h":_num(config.get("h"),120,40,1200)}
_CONFIG={"start":_cfg_start,"command":_cfg_command,"script":_cfg_script,"decision":_cfg_decision,"parse":_cfg_parse,"set":_cfg_set,
         "foreach":_cfg_foreach,"wait":_cfg_wait,"approval":_cfg_approval,"output":_cfg_output,"subchain":_cfg_subchain,
         "end":_cfg_end,"comment":_cfg_comment}
for _name in _nodes.FIELD_TYPES:_CONFIG[_name]=(lambda ctx,config,_type=_name:_nodes.normalize(_type,config,ctx))   # the generic, field-driven path
def migrate(graph):
    """Bring a stored or imported graph up to SCHEMA_VERSION. Returns the same dict (already current, or not a known older
    version) or an upgraded shallow copy. 1 -> 2 only added node types, so nothing inside the graph changes."""
    if not isinstance(graph,dict):return graph
    version=graph.get("schema",SCHEMA_VERSION)
    if isinstance(version,bool) or not isinstance(version,int) or not 1<=version<SCHEMA_VERSION:return graph
    return dict(graph,schema=SCHEMA_VERSION)
# ---------------------------------------------------------------- validation
def _settings(raw,errors):
    raw=raw if isinstance(raw,dict) else {}
    on_error=raw.get("on_error","stop")
    if on_error not in("stop","continue"):
        errors.append(_issue("bad_config","settings.on_error must be 'stop' or 'continue'."));on_error="stop"
    isolation=raw.get("script_isolation","inherit")
    if isolation not in SCRIPT_ISOLATION:
        errors.append(_issue("bad_config","settings.script_isolation must be 'inherit', 'sandboxed' or 'allow'."));isolation="inherit"
    return {"shell":_text(raw.get("shell"),80).strip(),
            "run_timeout":_num(raw.get("run_timeout"),1800,LIMITS["run_timeout_min"],LIMITS["run_timeout_max"]),
            "max_visits":_num(raw.get("max_visits"),200,LIMITS["max_visits_min"],LIMITS["max_visits_max"]),"on_error":on_error,
            "script_isolation":isolation}
def _viewport(raw):
    raw=raw if isinstance(raw,dict) else {}
    return {"x":_tidy(_coord(raw.get("x"))),"y":_tidy(_coord(raw.get("y"))),"zoom":round(_num(raw.get("zoom"),1,0.1,4,integer=False),3)}
def validate_graph(graph):
    """Check and normalize a graph. Never raises. -> {"ok","errors":[ISSUE],"warnings":[ISSUE],"graph":normalized copy}."""
    errors=[];warnings=[]
    try:return _validate(graph,errors,warnings)
    except Exception as exc:   # a bug here must never take the editor or a run down
        errors.append(_issue("structure","The diagram could not be checked: %s"%exc))
        return {"ok":False,"errors":errors,"warnings":warnings,"graph":new_graph()}
def _validate(graph,errors,warnings):
    if isinstance(graph,(str,bytes)):
        try:
            if len(graph)>LIMITS["graph_bytes"]:raise ValueError("too large")
            graph=json.loads(graph)
        except Exception:graph=None
    if not isinstance(graph,dict):
        errors.append(_issue("structure","The diagram is not a JSON object."))
        return {"ok":False,"errors":errors,"warnings":warnings,"graph":new_graph()}
    graph=migrate(graph)
    schema=graph.get("schema",SCHEMA_VERSION)
    if isinstance(schema,bool) or not isinstance(schema,int) or schema<1:errors.append(_issue("structure","The schema version is missing or not a number."))
    elif schema>SCHEMA_VERSION:errors.append(_issue("schema_version","This diagram was made by a newer version (schema %d)."%schema))
    raw_nodes=graph.get("nodes");raw_edges=graph.get("edges",[])
    if not isinstance(raw_nodes,list):
        errors.append(_issue("structure","'nodes' must be a list."));raw_nodes=[]
    if not isinstance(raw_edges,list):
        errors.append(_issue("structure","'edges' must be a list."));raw_edges=[]
    if len(raw_nodes)>LIMITS["nodes"]:
        errors.append(_issue("too_many_nodes","A diagram holds at most %d nodes."%LIMITS["nodes"]));raw_nodes=raw_nodes[:LIMITS["nodes"]]
    if len(raw_edges)>LIMITS["edges"]:
        errors.append(_issue("too_many_edges","A diagram holds at most %d connections."%LIMITS["edges"]));raw_edges=raw_edges[:LIMITS["edges"]]
    nodes=[];by_id={}
    for raw in raw_nodes:
        if not isinstance(raw,dict):
            errors.append(_issue("structure","A node is not an object."));continue
        node_id=raw.get("id")
        if not isinstance(node_id,str) or not ID_RE.match(node_id):
            errors.append(_issue("bad_id","Node id %r is not valid."%(_text(node_id,60) if isinstance(node_id,(str,int)) else None,)));continue
        if node_id in by_id:
            errors.append(_issue("duplicate_id","Node id %r is used twice."%node_id,node=node_id));continue
        node_type=raw.get("type")
        if not isinstance(node_type,str) or node_type not in NODE_TYPES:
            errors.append(_issue("unknown_type","Unknown node type %r."%(_text(node_type,40),),node=node_id));continue
        config=raw.get("config") if isinstance(raw.get("config"),dict) else {}
        ctx=_Ctx(node_id,errors,warnings)
        node={"id":node_id,"type":node_type,"title":_text(raw.get("title",NODE_TYPES[node_type]["label"]),LIMITS["title_chars"]).strip() or NODE_TYPES[node_type]["label"],
              "x":_tidy(_coord(raw.get("x"))),"y":_tidy(_coord(raw.get("y"))),"config":_CONFIG[node_type](ctx,config)}
        nodes.append(node);by_id[node_id]=node
    starts=[n for n in nodes if n["type"]=="start"]
    if not starts:errors.append(_issue("no_start","The diagram has no Start node."))
    for extra in starts[1:]:errors.append(_issue("many_start","A diagram can have only one Start node.",node=extra["id"]))
    ports={node["id"]:node_ports(node) for node in nodes}
    edges=[];edge_ids=set();seen_links=set()
    for raw in raw_edges:
        if not isinstance(raw,dict):
            errors.append(_issue("structure","A connection is not an object."));continue
        edge_id=raw.get("id")
        if edge_id in(None,""):
            counter=len(edges)+1
            while "e%d"%counter in edge_ids:counter+=1
            edge_id="e%d"%counter
        if not isinstance(edge_id,str) or not ID_RE.match(edge_id):
            errors.append(_issue("bad_id","Connection id %r is not valid."%(_text(edge_id,60) if isinstance(edge_id,(str,int)) else None,)));continue
        if edge_id in edge_ids:
            errors.append(_issue("duplicate_id","Connection id %r is used twice."%edge_id,edge=edge_id));continue
        source=raw.get("from");target=raw.get("to");port=raw.get("port")
        if not isinstance(source,str) or source not in by_id or not isinstance(target,str) or target not in by_id:
            errors.append(_issue("dangling_edge","A connection points at a node that does not exist.",edge=edge_id));continue
        if not isinstance(port,str) or port not in ports[source]["out"]:
            errors.append(_issue("unknown_port","%s has no output called %r."%(by_id[source]["title"],_text(port,40)),node=source,edge=edge_id));continue
        if not ports[target]["in"]:
            errors.append(_issue("bad_edge_target","Nothing can connect into a %s node."%NODE_TYPES[by_id[target]["type"]]["label"],node=target,edge=edge_id));continue
        if source==target:
            errors.append(_issue("self_loop","A node cannot connect to itself.",node=source,edge=edge_id));continue
        link=(source,port,target)
        if link in seen_links:
            warnings.append(_issue("duplicate_edge","The same connection exists twice; the copy was dropped.",node=source,edge=edge_id));continue
        seen_links.add(link);edge_ids.add(edge_id)
        edges.append({"id":edge_id,"from":source,"port":port,"to":target})
    used={(e["from"],e["port"]) for e in edges}
    if starts:
        reachable={starts[0]["id"]};stack=[starts[0]["id"]]
        following={}
        for edge in edges:following.setdefault(edge["from"],[]).append(edge["to"])
        while stack:
            for nxt in following.get(stack.pop(),()):
                if nxt not in reachable:
                    reachable.add(nxt);stack.append(nxt)
        for node in nodes:
            if node["type"]!="comment" and node["id"] not in reachable:
                warnings.append(_issue("unreachable","%s is not connected to the Start node and will never run."%node["title"],node=node["id"]))
    for node in nodes:
        for port in ports[node["id"]]["out"]:
            if (node["id"],port) in used:continue
            optional=port in _OPTIONAL_PORTS and node["type"]!="decision" or node["type"]=="decision" and port==node["config"]["else"]
            dynamic=_nodes.SPECS[node["type"]].get("dynamic")
            if dynamic and port==node["config"].get(dynamic["fixed_key"]):optional=True
            if optional:warnings.append(_issue("port_unconnected","%s: nothing is connected to '%s'."%(node["title"],port),node=node["id"]))
    normalized={"schema":SCHEMA_VERSION,"settings":_settings(graph.get("settings"),errors),"nodes":nodes,"edges":edges,"viewport":_viewport(graph.get("viewport"))}
    try:size=len(json.dumps(normalized,ensure_ascii=False,separators=(",",":")).encode("utf-8","replace"))
    except Exception:size=LIMITS["graph_bytes"]+1
    if size>LIMITS["graph_bytes"]:errors.append(_issue("graph_too_large","The diagram is larger than %d KB."%(LIMITS["graph_bytes"]//1024)))
    return {"ok":not errors,"errors":errors,"warnings":warnings,"graph":normalized}
# ---------------------------------------------------------------- linear chains <-> graphs
def _step_text(step):
    command=step.get("command")
    if isinstance(command,dict):return _text(command.get("command") or command.get("text")).strip(),_text(command.get("title") or command.get("label")).strip()
    return _text(command).strip(),""
def linear_to_graph(name,steps):
    """A straight-line diagram (start -> command -> command ...) for a classic chain. steps=[{"command_id","command_src","label","command"}]."""
    graph=new_graph()
    previous="n1";port="out";column=1
    for step in (steps if isinstance(steps,(list,tuple)) else []):
        if isinstance(step,str):step={"command":step}
        if not isinstance(step,dict):continue
        text,title=_step_text(step)
        if not text:continue
        if len(graph["nodes"])>=LIMITS["nodes"]:break
        label=_text(step.get("label")).strip() or title
        node_id="n%d"%(len(graph["nodes"])+1)
        config=_defaults("command")
        config["commands"]=[{"text":text[:LIMITS["command_bytes"]],"command_id":_command_id(step.get("command_id")),
                             "src":_text(step.get("command_src") if step.get("command_src") is not None else step.get("src"),40),"label":label[:120]}]
        graph["nodes"].append({"id":node_id,"type":"command","title":(label or text)[:LIMITS["title_chars"]],"x":40+300*column,"y":160,"config":config})
        graph["edges"].append({"id":"e%d"%(len(graph["edges"])+1),"from":previous,"port":port,"to":node_id})
        previous=node_id;port="success";column+=1
    return graph
def graph_is_linear(graph):
    """True when the graph is exactly start -> command -> command ... (one command each, no branches), i.e. what linear_to_graph makes."""
    if not isinstance(graph,dict) or not isinstance(graph.get("nodes"),list) or not isinstance(graph.get("edges"),list):return False
    nodes=[n for n in graph["nodes"] if isinstance(n,dict) and n.get("type")!="comment"]
    starts=[n for n in nodes if n.get("type")=="start"]
    if len(starts)!=1:return False
    by_id={n.get("id"):n for n in nodes}
    if len(by_id)!=len(nodes):return False
    for node in nodes:
        if node is starts[0]:continue
        config=node.get("config") if isinstance(node.get("config"),dict) else {}
        commands=config.get("commands")
        if node.get("type")!="command" or not isinstance(commands,list) or len(commands)!=1:return False
    outgoing={}
    for edge in graph["edges"]:
        if not isinstance(edge,dict) or edge.get("from") not in by_id or edge.get("to") not in by_id:return False
        if edge["from"] in outgoing:return False
        expected="out" if by_id[edge["from"]] is starts[0] else "success"
        if edge.get("port")!=expected:return False
        outgoing[edge["from"]]=edge["to"]
    seen=[];current=starts[0].get("id")
    while current is not None and current not in seen:
        seen.append(current);current=outgoing.get(current)
    return current is None and len(seen)==len(nodes)
def graph_commands(graph):
    """Every command line of every command node, in node order: [{"node","title","index","text","command_id","src"}]."""
    rows=[]
    for node in (graph.get("nodes") if isinstance(graph,dict) and isinstance(graph.get("nodes"),list) else []):
        if not isinstance(node,dict) or node.get("type")!="command":continue
        config=node.get("config") if isinstance(node.get("config"),dict) else {}
        commands=config.get("commands") if isinstance(config.get("commands"),list) else []
        index=0
        for command in commands:
            if isinstance(command,str):command={"text":command}
            if not isinstance(command,dict) or not _text(command.get("text")).strip():continue
            rows.append({"node":node.get("id"),"title":_text(node.get("title")),"index":index,"text":_text(command.get("text")).strip(),
                         "command_id":_command_id(command.get("command_id")),"src":_text(command.get("src"),40)})
            index+=1
    return rows
def graph_scripts(graph):
    rows=[]
    for node in (graph.get("nodes") if isinstance(graph,dict) and isinstance(graph.get("nodes"),list) else []):
        if not isinstance(node,dict) or node.get("type")!="script":continue
        config=node.get("config") if isinstance(node.get("config"),dict) else {}
        rows.append({"node":node.get("id"),"title":_text(node.get("title")),"language":_text(config.get("language") or "python"),"code":_text(config.get("code"))})
    return rows
# ---------------------------------------------------------------- JSON schema (documentation / export / AI tool descriptions)
def _build_json_schema():
    cond={"type":"object","additionalProperties":False,"required":["source","op"],"properties":{
        "source":{"enum":list(SOURCES)},"field":{"type":"string"},"op":{"enum":list(OPS)},"value":{"type":"string"},"ci":{"type":"boolean"}}}
    port={"type":"string","pattern":PORT_RE.pattern};var={"type":"string","pattern":VAR_RE.pattern}
    timeout={"type":"integer","minimum":LIMITS["node_timeout_min"],"maximum":LIMITS["node_timeout_max"]}
    configs={
        "start":{"trigger":{"enum":["manual","caller","live"]}},
        "command":{"commands":{"type":"array","minItems":1,"maxItems":LIMITS["commands_per_node"],"items":{"type":"object","required":["text"],"additionalProperties":False,"properties":{
                       "text":{"type":"string","minLength":1,"maxLength":LIMITS["command_bytes"],"description":"The command line. {IPv4}-style target placeholders and ${flow.values} are allowed; ${name} is shell-quoted, ${raw:name} is not."},
                       "command_id":{"type":["integer","null"]},"src":{"type":"string"},"label":{"type":"string"}}}},
                   "mode":{"enum":["sequence","parallel"]},"stop_on_fail":{"type":"boolean"},"timeout":timeout,"shell":{"type":"string"}},
        "script":{"language":{"enum":list(SCRIPT_LANGUAGES)},"code":{"type":"string","maxLength":LIMITS["script_bytes"]},
                  "branches":{"type":"array","minItems":1,"maxItems":LIMITS["branches"],"items":port},"timeout":timeout,
                  "network":{"type":"boolean","default":False,"description":"allow network access when sandboxed"}},
        "decision":{"branches":{"type":"array","minItems":1,"maxItems":LIMITS["branches"],"items":{"type":"object","required":["name","conditions"],"additionalProperties":False,"properties":{
                        "name":port,"match":{"enum":["all","any"]},"conditions":{"type":"array","minItems":1,"maxItems":LIMITS["conditions"],"items":{"$ref":"#/$defs/condition"}}}}},
                    "else":port},
        "parse":{"mode":{"enum":list(PARSE_MODES)},"source":{"type":"string"},"pattern":{"type":"string","maxLength":LIMITS["regex_chars"]},"flags":{"type":"string","pattern":"^[imsx]*$"},
                 "tool":{"enum":list(PARSE_TOOLS)},"path":{"type":"string"},"var":{"type":"string"},
                 "assign":{"type":"array","items":{"type":"object","required":["var","from"],"additionalProperties":False,"properties":{"var":var,"from":{"type":"string","description":"group:N, group:name, match, all, count, value, or a path into the parsed data"}}}}},
        "set":{"assign":{"type":"array","items":{"type":"object","required":["var","value"],"additionalProperties":False,"properties":{"var":var,"value":{"type":"string"}}}}},
        "foreach":{"items":{"type":"string"},"item_var":var,"index_var":var,"max_items":{"type":"integer","minimum":1,"maximum":LIMITS["foreach_items_max"]},"split":{"enum":list(SPLIT_MODES)}},
        "wait":{"seconds":{"type":"number","minimum":0,"maximum":LIMITS["wait_max"]}},
        "approval":{"message":{"type":"string"},"timeout":{"type":"integer","minimum":0}},
        "output":{"action":{"enum":list(OUTPUT_ACTIONS)},"note_name":{"type":"string"},"report_id":{"type":["integer","null"]},"title":{"type":"string"},
                  "severity":{"enum":list(SEVERITIES)},"content":{"type":"string"}},
        "subchain":{"playbook_id":{"type":["integer","null"]},"pass_vars":{"type":"boolean"}},
        "end":{"status":{"enum":["success","fail"]},"message":{"type":"string"}},
        "comment":{"text":{"type":"string"},"color":{"enum":list(COMMENT_COLORS)},"w":{"type":"number"},"h":{"type":"number"}},
    }
    for node_type in _nodes.FIELD_TYPES:configs[node_type]=_nodes.json_schema(node_type)
    variants=[]
    for node_type,spec in NODE_TYPES.items():
        ports=spec["ports"] if spec["ports"]!="dynamic" else ("each name in config.branches plus 'error'" if node_type=="script" else "each branch name plus the else name")
        if _nodes.SPECS[node_type].get("dynamic"):ports=_nodes.param_schema(node_type)["ports"]
        variants.append({"if":{"properties":{"type":{"const":node_type}}},"then":{"description":"%s Output ports: %s."%(spec["description"],ports if isinstance(ports,str) else (", ".join(ports) or "none")),
                         "properties":{"config":{"type":"object","additionalProperties":False,"properties":configs[node_type]}}}})
    return {
        "$schema":"https://json-schema.org/draft/2020-12/schema","$id":"loya-note:chain-diagram:%d"%SCHEMA_VERSION,
        "title":"LOYA Note chain diagram","type":"object","required":["schema","nodes","edges"],"additionalProperties":False,
        "properties":{
            "schema":{"enum":list(range(1,SCHEMA_VERSION+1)),"description":"%d is current; older diagrams load unchanged."%SCHEMA_VERSION},
            "settings":{"type":"object","additionalProperties":False,"properties":{"shell":{"type":"string"},
                "run_timeout":{"type":"integer","minimum":LIMITS["run_timeout_min"],"maximum":LIMITS["run_timeout_max"]},
                "max_visits":{"type":"integer","minimum":LIMITS["max_visits_min"],"maximum":LIMITS["max_visits_max"]},"on_error":{"enum":["stop","continue"]},
                "script_isolation":{"enum":list(SCRIPT_ISOLATION),"description":"Script nodes: inherit the app policy, always require the sandbox, or allow unsandboxed scripts (only honoured for a reviewed chain that is not AI-made)."}}},
            "nodes":{"type":"array","minItems":1,"maxItems":LIMITS["nodes"],"items":{"$ref":"#/$defs/node"},"description":"Exactly one node of type 'start'."},
            "edges":{"type":"array","maxItems":LIMITS["edges"],"items":{"$ref":"#/$defs/edge"}},
            "viewport":{"type":"object","additionalProperties":False,"properties":{"x":{"type":"number"},"y":{"type":"number"},"zoom":{"type":"number","minimum":0.1,"maximum":4}}}},
        "$defs":{
            "id":{"type":"string","pattern":ID_RE.pattern},
            "condition":cond,
            "node":{"type":"object","required":["id","type"],"additionalProperties":False,
                    "properties":{"id":{"$ref":"#/$defs/id"},"type":{"enum":list(NODE_TYPES)},"title":{"type":"string","maxLength":LIMITS["title_chars"]},
                                  "x":{"type":"number"},"y":{"type":"number"},"config":{"type":"object"}},"allOf":variants},
            "edge":{"type":"object","required":["from","port","to"],"additionalProperties":False,
                    "description":"Leaves the named output port of 'from' and enters the input of 'to'. No edge may enter a start or comment node.",
                    "properties":{"id":{"$ref":"#/$defs/id"},"from":{"$ref":"#/$defs/id"},"port":port,"to":{"$ref":"#/$defs/id"}}}}}
JSON_SCHEMA=_build_json_schema()
# ---------------------------------------------------------------- templates
class _Builder:
    """Tiny helper to write template graphs without repeating ids and coordinates."""
    def __init__(self):
        self.graph=new_graph();self.graph["nodes"]=[]
    def node(self,node_type,title,column,row,/,**config):
        node_id="n%d"%(len(self.graph["nodes"])+1)
        merged=_defaults(node_type);merged.update(config)
        self.graph["nodes"].append({"id":node_id,"type":node_type,"title":title,"x":40+300*column,"y":160+170*row,"config":merged})
        return node_id
    def edge(self,source,port,target):
        self.graph["edges"].append({"id":"e%d"%(len(self.graph["edges"])+1),"from":source,"port":port,"to":target})
def _commands(*lines):
    return [{"text":line,"command_id":None,"src":"","label":""} for line in lines]
def _cond_row(source,op,value="",field="",ci=True):
    return {"source":source,"field":field,"op":op,"value":value,"ci":ci}
_PING="ping -n 2 {IPv4}" if os.name=="nt" else "ping -c 2 {IPv4}"
_ALIVE_PY='''import json, os

# The previous node's output arrives as JSON (also on stdin and in $LOYA_INPUT_FILE).
with open(os.environ["LOYA_INPUT_FILE"], encoding="utf-8") as handle:
    data = json.load(handle)
text = ((data.get("input") or {}).get("stdout") or "").lower()
alive = ("ttl=" in text or "bytes from" in text) and "100% packet loss" not in text
# The last line printed must be one JSON object: the branch to take and any variables to set.
print(json.dumps({"branch": "alive" if alive else "down", "vars": {"alive": alive}}))
'''
def _template_host_alive():
    b=_Builder()
    start=b.node("start","Start",0,0)
    ping=b.node("command","Ping the host",1,0,commands=_commands(_PING),timeout=60)
    alive=b.node("decision","Host alive?",2,0,branches=[{"name":"alive","match":"all","conditions":[_cond_row("host_up","is_true")]}],**{"else":"down"})
    scan=b.node("command","Port scan",3,0,commands=_commands("nmap -Pn -sV --top-ports 1000 {IPv4}"),timeout=1800)
    parse=b.node("parse","Read nmap ports",4,0,mode="tool",tool="nmap",source="stdout",var="scan",assign=[{"var":"open_ports","from":"open_ports"}])
    web=b.node("decision","Web port open?",5,0,branches=[{"name":"web","match":"any","conditions":[_cond_row("port_open","is_true","80"),_cond_row("port_open","is_true","443")]}],**{"else":"no-web"})
    enum=b.node("command","Web enumeration",6,0,commands=_commands("curl -skI http://{IPv4}/","curl -skI https://{IPv4}/","whatweb -a 1 {IPv4}"),stop_on_fail=False,timeout=600)
    done=b.node("output","Web enum finished",7,0,action="notify",title="Web enumeration finished",content="Open ports: ${open_ports}")
    noweb=b.node("output","No web ports",6,1,action="notify",title="No web service found",content="Open ports: ${open_ports}")
    down=b.node("output","Host is down",3,1,action="notify",title="Host did not answer",severity="low",content="${last.stdout}")
    failed=b.node("end","Scan failed",4,2,status="fail",message="The port scan failed.")
    for source,port,target in((start,"out",ping),(ping,"success",alive),(ping,"fail",alive),(alive,"alive",scan),(alive,"down",down),
                              (scan,"success",parse),(scan,"fail",failed),(parse,"out",web),(parse,"nomatch",noweb),
                              (web,"web",enum),(web,"no-web",noweb),(enum,"success",done),(enum,"fail",done)):b.edge(source,port,target)
    return b.graph
def _template_smb_null():
    b=_Builder()
    start=b.node("start","Start",0,0)
    probe=b.node("command","Null session probe",1,0,commands=_commands("smbclient -N -L //{IPv4}/"),timeout=120)
    check=b.node("decision","Null session allowed?",2,0,branches=[{"name":"open","match":"all","conditions":[
        _cond_row("exit_code","eq","0"),_cond_row("output","regex",r"Sharename|Disk|IPC\$"),_cond_row("output","not_contains","NT_STATUS_ACCESS_DENIED")]}],**{"else":"denied"})
    shares=b.node("command","Enumerate shares",3,0,commands=_commands("nxc smb {IPv4} -u '' -p '' --shares","smbmap -H {IPv4} -u '' -p ''"),stop_on_fail=False,timeout=600)
    note=b.node("output","Save to note",4,0,action="note_append",note_name="SMB enumeration",title="SMB null session on ${target.ipv4}",severity="medium",content="${last.stdout}")
    denied=b.node("output","No null session",3,1,action="notify",title="SMB null session refused",content="${last.stderr}")
    for source,port,target in((start,"out",probe),(probe,"success",check),(probe,"fail",check),(check,"open",shares),(check,"denied",denied),
                              (shares,"success",note),(shares,"fail",note)):b.edge(source,port,target)
    return b.graph
def _template_script_demo():
    b=_Builder()
    start=b.node("start","Start",0,0)
    ping=b.node("command","Ping the host",1,0,commands=_commands(_PING),timeout=60)
    script=b.node("script","Is the host alive?",2,0,language="python",code=_ALIVE_PY,branches=["alive","down"],timeout=30)
    up=b.node("output","Host is up",3,0,action="notify",title="Host is up",content="alive=${alive}")
    down=b.node("output","Host is down",3,1,action="notify",title="Host is down",severity="low",content="alive=${alive}")
    broken=b.node("end","Script failed",3,2,status="fail",message="The script did not finish: ${last.stderr}")
    for source,port,target in((start,"out",ping),(ping,"success",script),(ping,"fail",script),(script,"alive",up),(script,"down",down),(script,"error",broken)):b.edge(source,port,target)
    return b.graph
def _template_nmap_xml():
    b=_Builder()
    start=b.node("start","Start",0,0)
    scan=b.node("command","Nmap (XML output)",1,0,commands=_commands("nmap -Pn -sV --top-ports 1000 -oX - {IPv4}"),timeout=1800)
    parse=b.node("scan_parse","Read the XML",2,0,format="nmap_xml",source="${last.stdout}",var="scan")
    report=b.node("report_create","New report",3,0,name="Nmap ${target.ipv4}",var="report_id")
    loop=b.node("foreach","Each open port",4,0,items="${scan.ports}",max_items=200)
    finding=b.node("finding","Port as a finding",5,0,report="${report_id}",title="Open port ${item.port}/${item.proto} (${item.service}) on ${item.host}",severity="info",description="${item.service} ${item.version}")
    done=b.node("result","Open ports",5,1,label="Open ports",value="${scan.open_ports}")
    nothing=b.node("output","Nothing found",3,1,action="notify",title="No host or port in the scan",severity="low",content="${last.stderr}")
    failed=b.node("end","Scan failed",2,2,status="fail",message="The nmap scan failed.")
    for source,port,target in((start,"out",scan),(scan,"success",parse),(scan,"fail",failed),(parse,"out",report),(parse,"nomatch",nothing),
                              (report,"out",loop),(loop,"item",finding),(loop,"done",done)):b.edge(source,port,target)
    return b.graph
def _template_http_titles():
    b=_Builder()
    start=b.node("start","Start",0,0)
    urls=b.node("input_text","URLs to check",1,0,text="http://{IPv4}/\nhttps://{IPv4}/",format="lines",var="urls")
    loop=b.node("foreach","Each URL",2,0,items="${urls}",max_items=100)
    get=b.node("http","GET the page",3,0,method="GET",url="${item}",timeout=15,verify_tls=False,max_kb=256,var="response")
    title=b.node("regex","Page title",4,0,source="${response.body}",pattern=r"<title[^>]*>([^<]{1,200})",flags="i",mode="first",group="1",var="title")
    line=b.node("template","One line per page",5,0,template="${item} [${response.status}] ${title}",var="line")
    collect=b.node("merge","Collect",6,0,mode="any",collect="stdout",var="titles")
    unique=b.node("collection","Unique lines",3,1,op="dedupe",source="${titles}",var="unique")
    done=b.node("output","Show the titles",4,1,action="notify",title="Page titles",content="${unique}")
    skipped=b.node("log","No answer",4,2,level="warn",message="No usable answer from ${item}")
    for source,port,target in((start,"out",urls),(urls,"out",loop),(loop,"item",get),(get,"success",title),(get,"fail",skipped),(title,"out",line),(line,"out",collect),
                              (loop,"done",unique),(unique,"out",done)):b.edge(source,port,target)
    return b.graph
TEMPLATES=[
    {"id":"host-alive-portscan-web","name":"Host alive, port scan, web enum",
     "description":"Ping the target; when it answers run nmap, read the open ports and enumerate the web service if 80 or 443 is open.","graph":_template_host_alive()},
    {"id":"smb-null-session","name":"SMB null session",
     "description":"Try an anonymous SMB session; when it is allowed list the shares and save the result to a note.","graph":_template_smb_null()},
    {"id":"script-demo","name":"Script decision demo",
     "description":"Ping the target and let a small Python script decide whether the host is alive.","graph":_template_script_demo()},
    {"id":"nmap-xml-findings","name":"Nmap XML to findings",
     "description":"Scan with nmap -oX, read the XML, create a report and add one finding per open port.","graph":_template_nmap_xml()},
    {"id":"http-title-sweep","name":"HTTP title sweep",
     "description":"Request a list of URLs, pull each page title with a regex and show the unique results.","graph":_template_http_titles()},
]
def template(template_id):
    for entry in TEMPLATES:
        if entry["id"]==template_id:return copy.deepcopy(entry["graph"])
    return None
# ---------------------------------------------------------------- import / export
BUNDLE_VERSION=1
def export_bundle(name,caller,graph):
    return {"loya_chain":BUNDLE_VERSION,"name":_text(name,200).strip(),"caller":_text(caller,80).strip(),
            "graph":validate_graph(graph)["graph"],"exported_at":datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
def import_bundle(text_or_dict):
    """-> {"name","caller","graph"} (graph normalized). Raises ValueError with a readable message when the file is not a valid chain."""
    data=text_or_dict
    if isinstance(data,bytes):
        try:data=data.decode("utf-8-sig")
        except UnicodeDecodeError:raise ValueError("This file is not a chain export (it is not UTF-8 text).") from None
    if isinstance(data,str):
        if len(data.encode("utf-8","replace"))>LIMITS["graph_bytes"]*2:raise ValueError("This file is too large to be a chain export.")
        try:data=json.loads(data.lstrip("﻿"))
        except ValueError:raise ValueError("This file is not a chain export (it is not valid JSON).") from None
    if not isinstance(data,dict):raise ValueError("This file is not a chain export.")
    if "loya_chain" not in data:
        if "nodes" in data and "edges" in data:data={"loya_chain":BUNDLE_VERSION,"name":"","caller":"","graph":data}   # a bare graph is accepted too
        else:raise ValueError("This file is not a chain export (the 'loya_chain' marker is missing).")
    version=data.get("loya_chain")
    if isinstance(version,bool) or not isinstance(version,int) or version<1:raise ValueError("This chain export has no valid version.")
    if version>BUNDLE_VERSION:raise ValueError("This chain export was made by a newer version of LOYA Note.")
    if not isinstance(data.get("graph"),dict):raise ValueError("This chain export has no diagram in it.")
    result=validate_graph(data["graph"])
    if not result["ok"]:
        raise ValueError("The diagram in this file is not valid: "+"; ".join(issue["message"] for issue in result["errors"][:5]))
    return {"name":_text(data.get("name"),200).strip(),"caller":_text(data.get("caller"),80).strip(),"graph":result["graph"]}
