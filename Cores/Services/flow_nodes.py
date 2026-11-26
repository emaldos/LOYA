"""Chain Diagrams node catalog: the single source of truth for every node type (palette categories, ports, defaults and,
for the field-driven types, the FIELD list that drives the generic config normalizer here, the generic inspector form in
the page, the generated UI/js/components/flow-catalog.js and the MCP parameter schema) plus one executor per field-driven
type. The 13 legacy types keep their hand-written normalizers in flow_schema and their handlers in flow_engine.
Nothing here evaluates user text as code: `math` has its own tokenizer and recursive-descent evaluator.
Only the standard library is imported at module level (flow_schema imports this file); services are imported lazily."""
import copy,csv,io,json,math,os,re,ssl,threading,time,urllib.error,urllib.parse,urllib.request
PORT_RE=re.compile(r"^[A-Za-z0-9_-]{1,24}$")
VAR_RE=re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,39}$")
OPS=("contains","not_contains","equals","not_equals","starts_with","ends_with","regex","not_regex",
     "eq","ne","gt","ge","lt","le","is_empty","not_empty","is_true","is_false")
SEVERITIES=("critical","high","medium","low","info")
TEXT_MAX=8192            # default cap of a one-line text field
AREA_MAX=65536           # default cap of a textarea / code field
REGEX_MAX=498            # the engine wraps a pattern in one group, so two characters under flow_rules.MAX_REGEX_CHARS
ROWS_MAX=40
ITEMS_MAX=5000           # items a list node works on
PARSED_CAP=64*1024       # JSON size of a node's `parsed` / `vars_set` in the run status
RESULTS_MAX=200
SCAN_MAX=8*1024*1024
FILE_KB_MAX=4096
WRITE_MAX=4*1024*1024
HTTP_METHODS=("GET","POST","PUT","PATCH","DELETE","HEAD","OPTIONS")
ACTION_TYPES=("http","file_write","input_file","note","finding","report_create","target_update","live_target")   # act outside the run: listed in the plan
FORCE_ASK_TYPES=("http","file_write","input_file")   # an AI run of a chain with one of these always asks the operator
CATEGORIES=[
    {"id":"input","label":"Triggers & inputs","hint":"Where a chain starts and the data it starts with."},
    {"id":"action","label":"Actions","hint":"Run commands, scripts, other chains and HTTP requests."},
    {"id":"logic","label":"Logic","hint":"Branch, loop, wait, merge and stop."},
    {"id":"math","label":"Calculations & variables","hint":"Store values and calculate with them."},
    {"id":"transform","label":"Data transform","hint":"Reshape text, lists and objects."},
    {"id":"analysis","label":"Data analysis","hint":"Count, sort, group and read scan output."},
    {"id":"app","label":"App","hint":"Notes, reports, targets and CVE data of this app."},
    {"id":"output","label":"Outputs","hint":"Where results go."},
    {"id":"notify","label":"Notifications & log","hint":"Tell the operator or write to the run log."},
    {"id":"note","label":"Notes","hint":"Sticky notes on the canvas. Never executed."},
]
# ---------------------------------------------------------------- field helpers
def _labelize(value):
    text=str(value).replace("_"," ")
    return text[:1].upper()+text[1:] if text.islower() else text
def _opts(*values):
    return [{"value":v[0],"label":v[1]} if isinstance(v,tuple) else {"value":v,"label":_labelize(v)} for v in values]
def _f(key,label,kind="text",**extra):
    field={"key":key,"label":label,"type":kind}
    field.update(extra)
    return field
def _var(help_text="The flow variable the result is stored in (use it later as ${name})."):
    return _f("var","Store in variable","var",help=help_text,placeholder="name")
_OP_OPTIONS=_opts(("contains","contains"),("not_contains","does not contain"),("equals","is"),("not_equals","is not"),("starts_with","starts with"),("ends_with","ends with"),
                  ("regex","matches regex"),("not_regex","does not match regex"),("eq","="),("ne","≠"),("gt",">"),("ge","≥"),("lt","<"),("le","≤"),
                  ("is_empty","is empty"),("not_empty","is not empty"),("is_true","is true"),("is_false","is false"))
_COND={"source":"output","field":"","op":"contains","value":"","ci":True}
def _legacy(label,category,icon,ports,defaults,description,keywords,node_input=True):
    return {"label":label,"category":category,"icon":icon,"color":category,"input":node_input,"ports":ports,"defaults":defaults,"description":description,"keywords":keywords}
def _spec(label,category,icon,ports,defaults,description,keywords,fields,summary="",tones=None,fail_port="",dynamic=None,guide=""):
    spec={"label":label,"category":category,"icon":icon,"color":category,"input":True,"ports":ports}
    if dynamic:spec["dynamic"]=dynamic
    if tones:spec["tones"]=tones
    spec.update({"defaults":defaults,"description":description,"keywords":keywords})
    if summary:spec["summary"]=summary
    spec["fields"]=fields
    if fail_port:spec["fail_port"]=fail_port
    if guide:spec["guide"]=guide   # one line for the AI authoring guide; not part of the generated catalog
    return spec
_SOURCE_HELP="A ${value}: a variable, ${last.stdout}, ${last.parsed}, ${nodes.<id>.parsed} ..."
SPECS={
    # ---- legacy types: configs, ports and handlers are unchanged (flow_schema._cfg_*, flow_engine._node_*)
    "start":_legacy("Start","input","play",["out"],{"trigger":"manual"},"Where the chain begins. Every diagram has exactly one.",["begin","trigger","manual","entry"],node_input=False),
    "command":_legacy("Command","action","command-line",["success","fail"],{"commands":[],"mode":"sequence","stop_on_fail":True,"timeout":300,"shell":""},
                      "Run one or more commands in the terminal, one after another or in parallel.",["shell","terminal","run","exec","nmap","tool"]),
    "script":_legacy("Script","action","code-block","dynamic",{"language":"python","code":"","branches":["out"],"timeout":60,"network":False},
                     "Run a Python, Bash or PowerShell script that reads the previous output and picks a branch.",["python","bash","powershell","code"]),
    "decision":_legacy("Decision","logic","shuffle","dynamic",{"branches":[{"name":"yes","match":"all","conditions":[dict(_COND)]}],"else":"else"},
                       "Choose a path with no-code rules about the previous output.",["if","else","condition","branch","rule"]),
    "parse":_legacy("Parse","transform","search",["out","nomatch"],{"mode":"regex","source":"stdout","pattern":"","flags":"i","tool":"nmap","path":"","assign":[],"var":"parsed"},
                    "Pull values out of the previous output with a regex, a tool parser or a JSON path.",["extract","regex","parser","nmap","ping","jsonpath"]),
    "set":_legacy("Set variable","math","pairs",["out"],{"assign":[]},"Store values in flow variables.",["variable","assign","value","store"]),
    "foreach":_legacy("For each","logic","refresh",["item","done"],{"items":"","item_var":"item","index_var":"index","max_items":50,"split":"auto"},
                      "Repeat the 'item' path once per item, then continue on 'done'.",["loop","iterate","repeat","list","each"]),
    "wait":_legacy("Wait","logic","clock",["out"],{"seconds":5},"Pause for a number of seconds.",["delay","sleep","pause","timer"]),
    "approval":_legacy("Approval","logic","clipboard-check",["approved","rejected"],{"message":"Continue?","timeout":0},
                       "Stop and ask the operator before continuing.",["confirm","ask","gate","human","manual"]),
    "output":_legacy("Output","output","report",["out"],{"action":"notify","note_name":"","report_id":None,"title":"","severity":"info","content":"${last.stdout}"},
                     "Append to a note, draft a finding, save evidence or show a notification.",["notify","note","finding","evidence","toast"]),
    "subchain":_legacy("Sub-chain","action","chain",["success","fail"],{"playbook_id":None,"pass_vars":True},
                       "Run another chain and continue when it finishes.",["chain","call","nested","reuse"]),
    "end":_legacy("End","logic","stop",[],{"status":"success","message":""},"Stop the run with a success or fail status.",["stop","finish","exit","fail"]),
    "comment":_legacy("Comment","note","text",[],{"text":"","color":"yellow","w":220,"h":120},"A sticky note. Never executed.",["note","sticky","label","annotation"],node_input=False),
    # ---- field-driven types
    "input_target":_spec("Target","input","target",["out","missing"],{"source":"live","name":"","var":"tgt"},
        "Read the live target (or a named one) into a variable.",["target","live","host","ip","scope"],
        [_f("source","Target","select",options=_opts(("live","Live target"),("name","Target by name")),help="The live target, or a target picked by its name."),
         _f("name","Target name",help="Name of the target on the Targets page.",placeholder="web01",required=True,max_chars=200,show_if={"source":["name"]},suggest="targets"),
         _var("Holds the target's values, e.g. ${tgt.ipv4}, plus ${tgt.name}.")],
        summary="{source} -> {var}",tones={"missing":"neg"},guide="${tgt.ipv4}-style values (lower-case keys) plus ${tgt.name}."),
    "input_text":_spec("Text / list input","input","flow-list",["out"],{"text":"","format":"text","var":"input"},
        "Start from text you type: plain text, one item per line, CSV rows or JSON.",["text","list","lines","csv","json","wordlist","constant"],
        [_f("text","Text","textarea",help="{Placeholders} and ${values} are filled in.",max_chars=AREA_MAX,placeholder="one item per line"),
         _f("format","Read as","select",options=_opts(("text","Plain text"),("lines","Lines (list)"),("csv","CSV (rows)"),("json","JSON")),help="Lines: a list without the empty lines. CSV: a list of rows, each a list of cells."),
         _var()],
        summary="{format} -> {var}"),
    "input_file":_spec("File input","input","flow-file-in",["out","error"],{"path":"","format":"text","max_kb":1024,"var":"file"},
        "Read a text file from this computer.",["file","read","load","wordlist","import"],
        [_f("path","File path",help="Absolute path or ~/... Files inside the app's Data and Backups folders are refused.",placeholder="~/scans/hosts.txt",required=True,max_chars=1024),
         _f("format","Read as","select",options=_opts(("text","Plain text"),("lines","Lines (list)"),("json","JSON"))),
         _f("max_kb","Size limit (KB)","number",min=1,max=FILE_KB_MAX,integer=True,help="A larger file is refused."),
         _var()],
        summary="{path}",tones={"error":"neg"},fail_port="error"),
    "http":_spec("HTTP request","action","flow-globe",["success","fail"],
        {"method":"GET","url":"","headers":[],"body":"","timeout":30,"verify_tls":True,"follow_redirects":True,"max_kb":512,"var":"response"},
        "Send an HTTP(S) request and read the answer.",["http","https","request","get","post","api","web","url","curl","rest"],
        [_f("method","Method","select",options=_opts(*HTTP_METHODS)),
         _f("url","URL",help="http:// or https://. {Placeholders} and ${values} are filled in.",placeholder="https://{IPv4}/",required=True,max_chars=4096),
         _f("headers","Headers","rows",rows=[_f("name","Name",placeholder="Authorization",required=True,max_chars=200),_f("value","Value",max_chars=4096)],max_rows=30,row_label="header"),
         _f("body","Body","textarea",max_chars=AREA_MAX,help="Sent as written (JSON bodies get a JSON content type)."),
         _f("timeout","Timeout (s)","number",min=1,max=300,integer=True),
         _f("verify_tls","Verify the TLS certificate","bool",help="Turn off for self-signed lab hosts."),
         _f("follow_redirects","Follow redirects","bool"),
         _f("max_kb","Read at most (KB)","number",min=1,max=FILE_KB_MAX,integer=True),
         _var("${response.status}, ${response.body}, ${response.headers.server}, ${response.json...}")],
        summary="{method} {url}",tones={"success":"pos","fail":"neg"},fail_port="fail",
        guide="headers = [{\"name\":\"\",\"value\":\"\"}]. success = status below 400. The variable holds {status,headers,body,json,url,elapsed_ms}."),
    "switch":_spec("Switch","logic","flow-switch",[],{"value":"${last.stdout}","cases":[{"name":"case1","op":"equals","value":""}],"default":"default","ci":True},
        "Compare one value against several cases; the first that matches wins.",["switch","case","match","route","branch","select"],
        [_f("value","Value",help=_SOURCE_HELP,max_chars=TEXT_MAX),
         _f("cases","Cases","rows",rows=[_f("name","Port","port",required=True),_f("op","Test","select",options=_OP_OPTIONS),_f("value","Compare with",max_chars=TEXT_MAX)],max_rows=12,row_label="case",required=True),
         _f("default","Default port","port",help="Taken when no case matches."),
         _f("ci","Ignore case","bool")],
        summary="{cases} case(s)",tones={"default":"alt"},dynamic={"rows":"cases","name":"name","fixed_key":"default"},
        guide="cases = [{\"name\":\"<port>\",\"op\":OP,\"value\":\"\"}] tested top to bottom (op = any condition OP); none -> the port named by default."),
    "merge":_spec("Merge","logic","flow-merge",["out"],{"mode":"any","collect":"parsed","var":"merged"},
        "Join branches again and collect what each one brought.",["merge","join","combine","collect","wait","gather","accumulate"],
        [_f("mode","Continue","select",options=_opts(("any","Every time a branch arrives"),("all","Once, when every incoming connection has arrived")),help="All: for several connections that leave the same port."),
         _f("collect","Collect","select",options=_opts(("parsed","The parsed value"),("stdout","The text output"),("none","Nothing"))),
         _var("The list of collected values, one per arrival.")],
        summary="{mode} -> {var}",guide="any: passes every arrival on and keeps appending to the variable (collect loop results). all: waits for one arrival per incoming edge."),
    "math":_spec("Math","math","flow-math",["out","error"],{"expr":"","var":"result","decimals":-1},
        "Calculate a number from numbers and variables.",["math","calc","calculate","add","sum","number","formula","expression","count"],
        [_f("expr","Expression",help="+ - * / // % ** and ( ), variable names or ${values}, and min max abs round floor ceil sqrt len sum int float.",placeholder="(open_count * 100) / total",required=True,max_chars=2000),
         _var(),
         _f("decimals","Decimals","number",min=-1,max=12,integer=True,help="-1 keeps the result as it is.")],
        summary="{var} = {expr}",tones={"error":"neg"},fail_port="error",
        guide="expr: + - * / // % ** ( ), numbers, variable names or ${values}, functions min max abs round floor ceil sqrt len sum int float. Division by zero -> error."),
    "template":_spec("Template text","transform","flow-template",["out"],{"template":"","var":"text"},
        "Build text from values.",["template","text","format","string","compose","message"],
        [_f("template","Text","textarea",help="{Placeholders} and ${values} are filled in.",max_chars=AREA_MAX,placeholder="Host ${tgt.ipv4} has ${count} open ports"),
         _var()],
        summary="-> {var}"),
    "fields":_spec("Edit fields","transform","flow-fields",["out"],{"source":"${last.parsed}","ops":[{"op":"set","field":"","value":""}],"var":"data"},
        "Set, rename, remove or keep fields of an object (or of every object in a list).",["fields","set","rename","remove","keep","object","properties","edit"],
        [_f("source","Object or list",help=_SOURCE_HELP,max_chars=TEXT_MAX),
         _f("ops","Changes","rows",rows=[_f("op","Do","select",options=_opts("set","rename","remove","keep")),_f("field","Field",required=True,max_chars=200),_f("value","Value / new name",max_chars=TEXT_MAX)],max_rows=ROWS_MAX,row_label="change",required=True),
         _var()],
        summary="{ops} change(s) -> {var}",guide="ops = [{\"op\":\"set|rename|remove|keep\",\"field\":\"\",\"value\":\"\"}]; in a set value ${item} is the object."),
    "map":_spec("Map items","transform","flow-map",["out"],{"source":"","template":"${item}","var":"mapped"},
        "Turn every item of a list into something else.",["map","each","transform","convert","list","project"],
        [_f("source","List",help=_SOURCE_HELP,required=True,max_chars=TEXT_MAX),
         _f("template","Each item becomes",help="${item} is the item, ${item.field} one of its fields, ${index} its position.",max_chars=TEXT_MAX),
         _var()],
        summary="{template} -> {var}"),
    "filter":_spec("Filter items","transform","flow-filter",["out","empty"],{"source":"","match":"all","conditions":[{"field":"","op":"contains","value":""}],"ci":True,"var":"filtered"},
        "Keep the items of a list that pass your tests.",["filter","where","select","keep","only","grep"],
        [_f("source","List",help=_SOURCE_HELP,required=True,max_chars=TEXT_MAX),
         _f("match","Keep an item when","select",options=_opts(("all","all tests pass"),("any","any test passes"))),
         _f("conditions","Tests","rows",rows=[_f("field","Field",help="Empty = the item itself.",max_chars=200),_f("op","Test","select",options=_OP_OPTIONS),_f("value","Compare with",max_chars=TEXT_MAX)],max_rows=12,row_label="test",required=True),
         _f("ci","Ignore case","bool"),
         _var()],
        summary="{conditions} test(s) -> {var}",tones={"empty":"neg"},guide="conditions = [{\"field\":\"\",\"op\":OP,\"value\":\"\"}] (field empty = the item itself; op = any condition OP). empty = nothing passed."),
    "split":_spec("Split","transform","flow-split",["out"],{"source":"${last.stdout}","mode":"lines","separator":"","trim":True,"drop_empty":True,"var":"items"},
        "Cut text into a list.",["split","lines","words","separate","tokenize","list"],
        [_f("source","Text",help=_SOURCE_HELP,max_chars=TEXT_MAX),
         _f("mode","Split by","select",options=_opts(("lines","Lines"),("comma","Commas"),("whitespace","Whitespace"),("separator","A separator"),("regex","A regex"),("json","JSON list"))),
         _f("separator","Separator",help="Text (\\n and \\t are understood) or, for the regex mode, the pattern.",required=True,max_chars=REGEX_MAX,show_if={"mode":["separator","regex"]}),
         _f("trim","Trim spaces","bool"),
         _f("drop_empty","Drop empty items","bool"),
         _var()],
        summary="by {mode} -> {var}"),
    "join":_spec("Join","transform","flow-join",["out"],{"source":"","separator":"\n","var":"joined"},
        "Glue the items of a list into one text.",["join","concat","combine","text","list"],
        [_f("source","List",help=_SOURCE_HELP,required=True,max_chars=TEXT_MAX),
         _f("separator","Separator",help="\\n and \\t are understood.",max_chars=200),
         _var()],
        summary="-> {var}"),
    "regex":_spec("Regex extract","transform","flow-regex",["out","nomatch"],{"source":"${last.stdout}","pattern":"","flags":"i","mode":"all","group":"0","var":"matches"},
        "Find text with a regular expression.",["regex","regexp","extract","match","find","pattern","grep"],
        [_f("source","Text",help=_SOURCE_HELP,max_chars=TEXT_MAX),
         _f("pattern","Pattern",placeholder=r"(\d+)/tcp\s+open",required=True,max_chars=REGEX_MAX,regex=True,flags_key="flags"),
         _f("flags","Flags",help="i ignore case, m multi-line, s dot matches newline, x verbose.",max_chars=8,placeholder="i"),
         _f("mode","Return","select",options=_opts(("first","The first match (text)"),("all","Every match (list)"))),
         _f("group","Group",help="0 = the whole match, 1.. = a group, or a group name.",max_chars=40),
         _var()],
        summary="/{pattern}/ -> {var}",tones={"nomatch":"neg"}),
    "json":_spec("JSON","transform","flow-json",["out","error"],{"action":"parse","source":"${last.stdout}","path":"","indent":2,"var":"json"},
        "Read JSON text, write a value as JSON, or pick one value by path.",["json","parse","format","stringify","path","object"],
        [_f("action","Do","select",options=_opts(("parse","Parse text into a value"),("format","Format a value as JSON text"),("get","Get the value at a path"))),
         _f("source","Source",help=_SOURCE_HELP,max_chars=TEXT_MAX),
         _f("path","Path",placeholder="items[0].name",required=True,max_chars=200,show_if={"action":["get"]},help="a.b[0].c, or ports[*].port for a list."),
         _f("indent","Indent","number",min=0,max=8,integer=True,show_if={"action":["format"]}),
         _var()],
        summary="{action} -> {var}",tones={"error":"neg"},fail_port="error"),
    "collection":_spec("List operation","analysis","flow-sort",["out"],{"op":"count","source":"","field":"","order":"asc","numeric":False,"limit":10,"var":"result"},
        "Count, sum, sort, de-duplicate, group or cut a list.",["count","sum","min","max","average","dedupe","unique","sort","reverse","limit","first","last","group","flatten","pluck","list","aggregate"],
        [_f("op","Operation","select",options=_opts(("count","Count"),("sum","Sum"),("min","Minimum"),("max","Maximum"),("avg","Average"),("dedupe","Remove duplicates"),("sort","Sort"),("reverse","Reverse"),
                                                    ("limit","First N items"),("first","First item"),("last","Last item"),("group","Group by field"),("group_count","Count per group"),("flatten","Flatten one level"),("pluck","Pluck a field"))),
         _f("source","List",help=_SOURCE_HELP,required=True,max_chars=TEXT_MAX),
         _f("field","Field",help="Field of each item to work on (empty = the item itself).",max_chars=200,show_if={"op":["sum","min","max","avg","dedupe","sort","group","group_count","pluck"]}),
         _f("order","Order","select",options=_opts(("asc","Ascending"),("desc","Descending")),show_if={"op":["sort"]}),
         _f("numeric","Compare as numbers","bool",show_if={"op":["sort","min","max"]}),
         _f("limit","N","number",min=1,max=ITEMS_MAX,integer=True,show_if={"op":["limit"]}),
         _var()],
        summary="{op} -> {var}"),
    "scan_parse":_spec("Parse scan output","analysis","flow-scan",["out","nomatch"],{"format":"auto","source":"${last.stdout}","var":"scan"},
        "Read nmap output (normal, XML or grepable) into hosts and ports.",["nmap","scan","xml","grepable","ports","hosts","parse","services"],
        [_f("format","Format","select",options=_opts(("auto","Detect"),("nmap","nmap normal output"),("nmap_xml","nmap XML (-oX)"),("nmap_grep","nmap grepable (-oG)"))),
         _f("source","Text",help=_SOURCE_HELP,max_chars=TEXT_MAX),
         _var("${scan.hosts}, ${scan.ports} (the open ones) and ${scan.open_ports} (numbers).")],
        summary="{format} -> {var}",tones={"nomatch":"neg"},
        guide="The variable holds {\"hosts\":[{ip,hostname,state,ports:[{port,proto,state,service,version}]}],\"ports\":[open ports, each with host],\"open_ports\":[numbers]}."),
    "note":_spec("Note","app","flow-note",["out"],{"action":"upsert","note_name":"","title":"","content":"${last.stdout}"},
        "Write to a note in this app.",["note","notes","write","append","save","document"],
        [_f("action","Do","select",options=_opts(("upsert","Append, or create the note"),("append","Append to an existing note"),("create","Create a new note"))),
         _f("note_name","Note name",max_chars=200,suggest="notes",placeholder="Recon ${target.ipv4}"),
         _f("title","Heading",max_chars=200),
         _f("content","Text","textarea",max_chars=16384)],
        summary="{action} {note_name}"),
    "finding":_spec("Report finding","app","flow-finding",["out"],{"report":"","title":"","severity":"info","description":"${last.stdout}"},
        "Add a finding draft to a report.",["finding","report","vulnerability","issue","draft"],
        [_f("report","Report",help="A report id or title. Empty = the newest report.",max_chars=200,suggest="reports"),
         _f("title","Title",max_chars=200),
         _f("severity","Severity","select",options=_opts(*SEVERITIES)),
         _f("description","Description","textarea",max_chars=16384)],
        summary="{severity}: {title}"),
    "report_create":_spec("Create report","app","report",["out"],{"name":"","var":"report_id"},
        "Create a new draft report and keep its id.",["report","create","new","engagement"],
        [_f("name","Report title",required=True,max_chars=200),
         _var("The new report's id, e.g. for a Report finding node.")],
        summary="{name}"),
    "target_update":_spec("Update target","app","crosshair",["out","missing"],{"target":"live","name":"","key":"","value":"","create_missing":False},
        "Store a value on a target.",["target","update","set","value","parameter","save"],
        [_f("target","Target","select",options=_opts(("live","Live target"),("name","Target by name"))),
         _f("name","Target name",required=True,max_chars=200,show_if={"target":["name"]},suggest="targets"),
         _f("key","Parameter",help="The target parameter to set, e.g. Port. It is added to the parameter list when it is new.",required=True,max_chars=80,placeholder="Port"),
         _f("value","Value",max_chars=TEXT_MAX),
         _f("create_missing","Create the target when it does not exist","bool",show_if={"target":["name"]})],
        summary="{key} = {value}",tones={"missing":"neg"}),
    "cve_lookup":_spec("CVE lookup","app","bug",["found","none"],{"query":"","limit":5,"var":"cves"},
        "Search the offline CVE index.",["cve","vulnerability","exploit","lookup","search","kev"],
        [_f("query","Search",help="A CVE id, a product or keywords. Nothing is sent to the internet.",placeholder="${item.service} ${item.version}",required=True,max_chars=200),
         _f("limit","Results","number",min=1,max=50,integer=True),
         _var("A list of {id,title,severity,score,kev,published}.")],
        summary="{query}",tones={"found":"pos","none":"neg"}),
    "live_target":_spec("Set live target","app","target",["out","missing"],{"name":""},
        "Make a target the live target for the rest of the run.",["target","live","switch","select"],
        [_f("name","Target name",required=True,max_chars=200,suggest="targets")],
        summary="{name}",tones={"missing":"neg"}),
    "file_write":_spec("Write file","output","flow-file-out",["out","error"],{"path":"","content":"${last.stdout}","mode":"overwrite"},
        "Write text to a file on this computer.",["file","write","save","export","append","output"],
        [_f("path","File path",help="Absolute path or ~/... Files inside the app's Data and Backups folders are refused.",placeholder="~/loot/${target.ipv4}.txt",required=True,max_chars=1024),
         _f("content","Text","textarea",max_chars=AREA_MAX),
         _f("mode","When the file exists","select",options=_opts(("overwrite","Overwrite it"),("append","Append to it")))],
        summary="{path}",tones={"error":"neg"},fail_port="error"),
    "result":_spec("Return result","output","flow-result",["out"],{"label":"","value":"${last.stdout}"},
        "Add a value to the run's results list.",["result","return","output","value","answer","export"],
        [_f("label","Label",max_chars=200),
         _f("value","Value","textarea",help="One ${value} alone keeps its type (a list stays a list).",max_chars=TEXT_MAX)],
        summary="{label}"),
    "log":_spec("Log message","notify","flow-log",["out"],{"level":"info","message":""},
        "Write a line to the run log.",["log","message","print","debug","warn","error","echo"],
        [_f("level","Level","select",options=_opts(("info","Info"),("warn","Warning"),("error","Error"))),
         _f("message","Message","textarea",required=True,max_chars=4000)],
        summary="{level}: {message}"),
}
LEGACY_TYPES=tuple(name for name,spec in SPECS.items() if "fields" not in spec)
FIELD_TYPES=tuple(name for name,spec in SPECS.items() if "fields" in spec)
def _preset(preset_id,node_type,label,description,config,keywords=(),icon="",category="",title=""):
    spec=SPECS[node_type]
    return {"id":preset_id,"type":node_type,"label":label,"description":description,"category":category or spec["category"],"icon":icon or spec["icon"],
            "keywords":list(keywords),"config":config,"title":title or label}
PRESETS=[
    _preset("if","decision","If","A yes / no decision about the previous output.",{"branches":[{"name":"yes","match":"all","conditions":[dict(_COND)]}],"else":"no"},("if","else","condition","true","false")),
    _preset("stop_fail","end","Stop and fail","End the run as failed.",{"status":"fail"},("stop","fail","abort","error"),icon="warning"),
    _preset("delay","wait","Delay","Wait a few seconds.",{"seconds":10},("delay","sleep","wait")),
    _preset("loop","foreach","Loop","Repeat a path for every item of a list.",{"items":"${items}"},("loop","for","each","iterate")),
    _preset("python_script","script","Python script","Run a Python script.",{"language":"python"},("python","py","script")),
    _preset("bash_script","script","Bash script","Run a Bash script.",{"language":"bash"},("bash","sh","shell","script")),
    _preset("powershell_script","script","PowerShell script","Run a PowerShell script.",{"language":"powershell"},("powershell","pwsh","ps1","script")),
    _preset("saved_command","command","Saved command","Pick one of your saved commands.",{},("saved","library","quick run","snippet"),icon="commands"),
    _preset("notify","output","Notify","Show a notification.",{"action":"notify"},("notify","toast","alert","message"),icon="bell",category="notify"),
    _preset("evidence","output","Save evidence","Save the previous output as evidence.",{"action":"evidence"},("evidence","proof","capture"),icon="shield",category="app"),
    _preset("note_append","note","Append to note","Add text to the end of an existing note.",{"action":"append"},("note","append","add")),
    _preset("count","collection","Count items","How many items a list has.",{"op":"count","var":"count"},("count","length","size","how many"),icon="flow-count"),
    _preset("dedupe","collection","Remove duplicates","Keep every item once.",{"op":"dedupe","var":"unique"},("dedupe","unique","distinct")),
    _preset("sort","collection","Sort","Sort a list.",{"op":"sort","var":"sorted"},("sort","order")),
    _preset("group_by","collection","Group by","Group the items of a list by a field.",{"op":"group","var":"groups"},("group","bucket","by")),
    _preset("sum","collection","Sum","Add up the numbers of a list.",{"op":"sum","var":"total"},("sum","total","add")),
    _preset("nmap_xml","scan_parse","Parse nmap XML","Read nmap -oX output.",{"format":"nmap_xml"},("nmap","xml","oX")),
    _preset("nmap_grep","scan_parse","Parse nmap grepable","Read nmap -oG output.",{"format":"nmap_grep"},("nmap","grepable","oG","gnmap")),
    _preset("json_parse","json","Parse JSON","Turn JSON text into a value.",{"action":"parse"},("json","parse","decode")),
    _preset("json_format","json","Format JSON","Write a value as JSON text.",{"action":"format","source":"${last.parsed}","var":"text"},("json","format","stringify","encode")),
    _preset("regex_ips","regex","Extract IP addresses","Find every IPv4 address in the text.",{"pattern":r"\b(?:\d{1,3}\.){3}\d{1,3}\b","mode":"all","group":"0","var":"ips"},("ip","ipv4","address","extract")),
    _preset("http_get","http","HTTP GET","Fetch a URL.",{"method":"GET"},("get","fetch","download","curl")),
    _preset("http_post","http","HTTP POST","Send data to a URL.",{"method":"POST"},("post","send","submit","api")),
]
HOTBAR=["command","decision","script","http","scan_parse","foreach","set","output","note"]
def catalog_ids():
    """Every id a hot bar pin may use: node types and presets."""
    return list(SPECS)+[p["id"] for p in PRESETS]
def flow_catalog(schema_version=2):
    """The FLOW_CATALOG object (see tools/gen_flow_catalog.py): JSON-safe, python-only keys removed."""
    types={name:{key:copy.deepcopy(value) for key,value in spec.items() if key!="guide"} for name,spec in SPECS.items()}
    return {"schema":schema_version,"categories":copy.deepcopy(CATEGORIES),"types":types,"presets":copy.deepcopy(PRESETS),"hotbar":list(HOTBAR)}
def fail_port(node_type):
    return str((SPECS.get(node_type) or {}).get("fail_port") or "")
def dynamic_ports(node_type,config):
    """Output ports of a row-driven type (switch): each row's name, then the port named by config[fixed_key]."""
    spec=SPECS[node_type];dyn=spec.get("dynamic") or {}
    config=config if isinstance(config,dict) else {}
    out=list(spec["ports"])
    rows=config.get(dyn.get("rows")) if isinstance(config.get(dyn.get("rows")),list) else spec["defaults"].get(dyn.get("rows"),[])
    for row in rows:
        name=row.get(dyn.get("name")) if isinstance(row,dict) else None
        if isinstance(name,str) and PORT_RE.match(name) and name not in out:out.append(name)
    fixed=config.get(dyn.get("fixed_key"))
    if not(isinstance(fixed,str) and PORT_RE.match(fixed)):fixed=spec["defaults"].get(dyn.get("fixed_key")) or "default"
    if fixed not in out:out.append(fixed)
    return out
def continue_port(node):
    """Where a failed field-driven node goes on when on_error is "continue": its plain way out. None = not one of ours."""
    node_type=node.get("type");spec=SPECS.get(node_type)
    if spec is None or "fields" not in spec:return None
    if spec.get("dynamic"):return dynamic_ports(node_type,node.get("config"))[-1]
    ports=list(spec["ports"])
    if ports==["out"]:return "out"
    tones=spec.get("tones") or {}
    return next((port for port in ports if tones.get(port)=="neg" and port!=spec.get("fail_port")),"")
# ---------------------------------------------------------------- generic config normalization
_MISSING=object()
def _text(value,limit=None):
    if value is None:value=""
    if not isinstance(value,str):value=str(value) if isinstance(value,(int,float)) and not isinstance(value,bool) else ("true" if value is True else "false" if value is False else "")
    value=value.replace("\x00","")
    return value if limit is None else value[:limit]
def _number(value,default,low,high,integer):
    if isinstance(value,bool):value=default
    if isinstance(value,str):
        try:value=float(value.strip())
        except ValueError:value=default
    if not isinstance(value,(int,float)) or value!=value or value in(float("inf"),float("-inf")):value=default
    value=max(low,min(high,value))
    return int(value) if integer or float(value).is_integer() else float(value)
def _boolean(value,default):
    if isinstance(value,bool):return value
    if isinstance(value,(int,float)):return bool(value)
    if isinstance(value,str) and value.strip().lower() in("true","false","1","0","yes","no"):return value.strip().lower() in("true","1","yes")
    return default
def _text_limit(field):
    return int(field.get("max_chars") or (AREA_MAX if field["type"] in("textarea","code") else TEXT_MAX))
def _coerce(ctx,field,value,default,where):
    """One raw config value -> its normalized form (type, range, allowed options). Reports what it had to correct."""
    kind=field["type"];label=where+field["label"]
    if value is _MISSING:value=copy.deepcopy(default)
    if kind in("text","textarea","code"):
        text=_text(value)
        if kind=="text":text=text.replace("\r\n","\n").replace("\r","\n") if "\n" in str(default) else text.replace("\r"," ").replace("\n"," ")
        else:text=text.replace("\r\n","\n").replace("\r","\n")
        limit=_text_limit(field)
        if len(text)>limit:
            ctx.error("text_too_long","%s is longer than %d characters."%(label,limit));text=text[:limit]
        return text
    if kind=="number":
        return _number(value,default if isinstance(default,(int,float)) and not isinstance(default,bool) else 0,field.get("min",-1e12),field.get("max",1e12),bool(field.get("integer")))
    if kind=="bool":return _boolean(value,bool(default))
    if kind=="select":
        allowed=[option["value"] for option in field.get("options") or []]
        if value in allowed:return value
        ctx.error("bad_config","%s must be one of: %s."%(label,", ".join(str(a) for a in allowed)))
        return default if default in allowed else (allowed[0] if allowed else "")
    if kind=="var":
        name=_text(value,60).strip()
        if name and not VAR_RE.match(name):
            ctx.error("bad_var","Variable name %r is not valid (letters, digits and _, not starting with a digit)."%name);name=default if isinstance(default,str) else ""
        return name
    if kind=="port":
        name=_text(value,60).strip()
        if not name and isinstance(default,str):name=default
        if name and not PORT_RE.match(name):
            ctx.error("bad_port_name","%s: %r is not a valid port name (letters, digits, _ and -, up to 24 characters)."%(label,name));name=default if isinstance(default,str) and PORT_RE.match(default) else ""
        return name
    if kind=="rows":
        raw=value if isinstance(value,list) else []
        limit=int(field.get("max_rows") or ROWS_MAX)
        if len(raw)>limit:
            ctx.error("too_many_rows","%s holds at most %d rows."%(label,limit));raw=raw[:limit]
        rows=[]
        for item in raw:
            if not isinstance(item,dict):
                ctx.error("bad_config","%s: a row is not an object."%label);continue
            row_where="%s, %s %d: "%(label,field.get("row_label") or "row",len(rows)+1)
            rows.append({sub["key"]:_coerce(ctx,sub,item.get(sub["key"],_MISSING),_row_default(sub),row_where) for sub in field.get("rows") or []})
        return rows
    return copy.deepcopy(default)
def _row_default(sub):
    if sub["type"]=="select":return (sub.get("options") or [{"value":""}])[0]["value"]
    if sub["type"]=="number":return sub.get("min",0)
    if sub["type"]=="bool":return False
    return ""
def _blank(value):
    return value is None or (isinstance(value,str) and not value.strip()) or (isinstance(value,list) and not value)
def _regex_issue(pattern,flags):
    try:
        from Cores.Services import flow_rules
        flow_rules.check_regex(pattern,flags)
    except ValueError as exc:return str(exc)
    except Exception as exc:return "the regex could not be checked (%s)."%exc
    return ""
def clean_flags(value):
    return "".join(ch for ch in "imsx" if ch in _text(value,16).lower())
def _check_fields(ctx,fields,values,where):
    for field in fields:
        shown=all(values.get(key) in allowed for key,allowed in (field.get("show_if") or {}).items())
        if not shown:continue
        value=values.get(field["key"]);label=where+field["label"]
        if field.get("required") and _blank(value):
            ctx.error("empty_field","%s is empty."%label if field["type"]!="rows" else "%s: add at least one %s."%(label,field.get("row_label") or "row"));continue
        if field.get("regex") and isinstance(value,str) and value:
            problem=_regex_issue(value,clean_flags(values.get(field.get("flags_key") or "")))
            if problem:ctx.error("invalid_regex","%s: %s"%(label,problem))
        if field["type"]=="rows":
            for position,row in enumerate(value or []):
                _check_fields(ctx,field.get("rows") or [],row,"%s, %s %d: "%(label,field.get("row_label") or "row",position+1))
def _check_ops(ctx,rows,ci,what):
    """Rows that carry a condition operator (switch cases, filter tests): a regex must be safe, a number must be a number."""
    for position,row in enumerate(rows):
        where="%s %d"%(what,position+1);value=row.get("value") or ""
        if row.get("op") in("regex","not_regex"):
            if not value:ctx.error("invalid_regex","%s: the regex is empty."%where)
            elif "${" not in value:
                problem=_regex_issue(value,"i" if ci else "")
                if problem:ctx.error("invalid_regex","%s: %s"%(where,problem))
        if row.get("op") in("eq","ne","gt","ge","lt","le") and "${" not in value:
            try:float(value.strip())
            except ValueError:ctx.error("bad_condition","%s: %r is not a number."%(where,value[:40]))
def _post_switch(ctx,cfg):
    seen=[]
    for row in cfg["cases"]:
        if row["name"] in seen:ctx.error("duplicate_port","Case name %r is used twice."%row["name"])
        elif row["name"]:seen.append(row["name"])
    cfg["cases"]=[row for row in cfg["cases"] if row["name"]]
    if not cfg["default"]:cfg["default"]="default"
    if cfg["default"] in seen:
        ctx.error("duplicate_port","The default port has the same name as case %r."%cfg["default"])
        cfg["default"]=next(name for name in ["default"]+["default%d"%i for i in range(2,40)] if name not in seen)
    _check_ops(ctx,cfg["cases"],cfg["ci"],"Case")
def _post_filter(ctx,cfg):
    _check_ops(ctx,cfg["conditions"],cfg["ci"],"Test")
def _post_regex(ctx,cfg):
    cfg["flags"]=clean_flags(cfg["flags"])
    group=cfg["group"].strip() or "0"
    if not(group.isdigit() and int(group)<=99) and not VAR_RE.match(group):
        ctx.error("bad_config","Group must be a number (0 = the whole match) or a group name.");group="0"
    cfg["group"]=group
def _post_split(ctx,cfg):
    if cfg["mode"]=="regex" and cfg["separator"]:
        problem=_regex_issue(cfg["separator"],"")
        if problem:ctx.error("invalid_regex","Separator: %s"%problem)
_HEADER_NAME=re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]{1,200}$")
def _post_http(ctx,cfg):
    url=cfg["url"].strip();cfg["url"]=url
    if url and not url.startswith(("${","{")) and not re.match(r"^https?://",url,re.I):
        ctx.error("bad_config","URL must start with http:// or https://.")
    for row in cfg["headers"]:
        row["name"]=row["name"].strip()
        if row["name"] and "${" not in row["name"] and not _HEADER_NAME.match(row["name"]):ctx.error("bad_config","Header name %r is not valid."%row["name"][:60])
def _post_math(ctx,cfg):
    if cfg["expr"].strip():
        try:math_check(cfg["expr"])
        except MathError as exc:ctx.error("bad_expression","Expression: %s"%exc)
def _post_paths(ctx,cfg):
    cfg["path"]=cfg["path"].strip()
    path=cfg["path"]
    if path and not path.startswith(("${","{","~")) and not os.path.isabs(path) and not re.match(r"^[A-Za-z]:[\\/]",path) and not path.startswith(("/","\\\\")):
        ctx.error("bad_config","File path must be absolute or start with ~.")
def _post_fields(ctx,cfg):
    for row in cfg["ops"]:row["field"]=row["field"].strip()
_POST={"switch":_post_switch,"filter":_post_filter,"regex":_post_regex,"split":_post_split,"http":_post_http,"math":_post_math,
       "input_file":_post_paths,"file_write":_post_paths,"fields":_post_fields}
def normalize(node_type,config,ctx):
    """Generic normalizer of a field-driven type. ctx has error(code,message) and warn(code,message) (flow_schema._Ctx)."""
    spec=SPECS[node_type]
    config=config if isinstance(config,dict) else {}
    out={field["key"]:_coerce(ctx,field,config.get(field["key"],_MISSING),spec["defaults"][field["key"]],"") for field in spec["fields"]}
    _check_fields(ctx,spec["fields"],out,"")
    post=_POST.get(node_type)
    if post is not None:post(ctx,out)
    return out
def _field_schema(field):
    kind=field["type"]
    if kind=="number":
        out={"type":"integer" if field.get("integer") else "number"}
        if "min" in field:out["minimum"]=field["min"]
        if "max" in field:out["maximum"]=field["max"]
        return out
    if kind=="bool":return {"type":"boolean"}
    if kind=="select":return {"enum":[option["value"] for option in field.get("options") or []]}
    if kind=="var":return {"type":"string","pattern":"^$|"+VAR_RE.pattern}
    if kind=="port":return {"type":"string","pattern":PORT_RE.pattern}
    if kind=="rows":
        return {"type":"array","maxItems":int(field.get("max_rows") or ROWS_MAX),"items":{"type":"object","additionalProperties":False,
                "required":[sub["key"] for sub in field.get("rows") or [] if sub.get("required")],"properties":{sub["key"]:_field_schema(sub) for sub in field.get("rows") or []}}}
    return {"type":"string","maxLength":_text_limit(field)}
def json_schema(node_type):
    """JSON Schema properties of a field-driven type's config."""
    return {field["key"]:_field_schema(field) for field in SPECS[node_type]["fields"]}
def guide_note(node_type):
    """One compact line for the AI authoring guide: the allowed option values plus the type's own hint."""
    spec=SPECS[node_type];parts=[]
    for field in spec.get("fields") or []:
        if field["type"]=="select":parts.append("%s: %s."%(field["key"]," | ".join(str(option["value"]) for option in field["options"])))
    if spec.get("guide"):parts.append(spec["guide"])
    return " ".join(parts)
def param_schema(node_type):
    """What an AI client needs to configure one node type: ports, defaults and one line per config key."""
    spec=SPECS[node_type]
    out={"type":node_type,"label":spec["label"],"category":spec["category"],"description":spec["description"],"input":bool(spec["input"]),
         "ports":spec["ports"] if not spec.get("dynamic") else "one per row of config.%s (its %s), then the port named by config.%s"%(spec["dynamic"]["rows"],spec["dynamic"]["name"],spec["dynamic"]["fixed_key"]),
         "defaults":copy.deepcopy(spec["defaults"])}
    if spec.get("fail_port"):out["fail_port"]=spec["fail_port"]
    if "fields" in spec:
        def describe(field):
            row={"key":field["key"],"type":field["type"]}
            if field.get("required"):row["required"]=True
            if field["type"]=="select":row["options"]=[option["value"] for option in field["options"]]
            if field["type"]=="number":row.update({key:field[key] for key in("min","max") if key in field})
            if field.get("show_if"):row["only_when"]=field["show_if"]
            if field.get("help"):row["help"]=field["help"]
            if field["type"]=="rows":row["rows"]=[describe(sub) for sub in field["rows"]];row["max_rows"]=field.get("max_rows") or ROWS_MAX
            return row
        out["fields"]=[describe(field) for field in spec["fields"]]
        if spec.get("guide"):out["notes"]=spec["guide"]
    out["presets"]=[{"id":p["id"],"label":p["label"],"config":copy.deepcopy(p["config"])} for p in PRESETS if p["type"]==node_type]
    return out
# ---------------------------------------------------------------- math: tokenizer + recursive-descent evaluator (no eval)
class MathError(ValueError):pass
_MATH_TOKEN=re.compile(r"\s*(?:(?P<num>(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?)|(?P<ref>\$\{[^{}\r\n]{1,200}\})|(?P<name>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+|\[-?\d{1,9}\])*)|(?P<op>\*\*|//|[-+*/%(),]))")
_MATH_TOKENS_MAX=400
_MATH_DEPTH_MAX=60
_MATH_BITS_MAX=4096
_MATH_LIST_MAX=100000
def _math_tokens(text):
    text=str(text or "")
    if len(text)>2000:raise MathError("The expression is longer than 2000 characters.")
    tokens=[];position=0
    while position<len(text):
        match=_MATH_TOKEN.match(text,position)
        if match is None or match.end()==position:
            if not text[position:].strip():break
            raise MathError("Unexpected %r at position %d."%(text[position:].strip()[:12],position+1))
        position=match.end()
        kind=match.lastgroup;value=match.group(kind)
        if kind=="num":
            if len(value)>60:raise MathError("A number is too long.")
            tokens.append(("num",int(value) if value.isdigit() else float(value)))
        else:tokens.append((kind,value))
        if len(tokens)>_MATH_TOKENS_MAX:raise MathError("The expression is too long.")
    if not tokens:raise MathError("The expression is empty.")
    return tokens
def _math_check_number(value):
    if isinstance(value,bool):return int(value)
    if isinstance(value,int):
        if value.bit_length()>_MATH_BITS_MAX:raise MathError("The number is too large.")
        return value
    if isinstance(value,float):
        if value!=value or value in(float("inf"),float("-inf")):raise MathError("The result is not a finite number.")
        return value
    raise MathError("The result is not a number.")
def _math_scalar(value,what="A value"):
    if isinstance(value,bool):return int(value)
    if isinstance(value,(int,float)):return _math_check_number(value)
    if value is None:raise MathError("%s has no value."%what)
    if isinstance(value,str):
        text=value.strip()
        if re.match(r"^[+-]?\d{1,60}$",text):return _math_check_number(int(text))
        if re.match(r"^[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d{1,4})?$",text):return _math_check_number(float(text))
        raise MathError("%s (%r) is not a number."%(what,text[:40]))
    if isinstance(value,(list,tuple,dict)):raise MathError("%s is a list; use len(), sum(), min() or max() on it."%what)
    raise MathError("%s is not a number."%what)
def _math_numbers(args,name):
    values=list(args[0]) if len(args)==1 and isinstance(args[0],(list,tuple)) else list(args)
    if len(values)>_MATH_LIST_MAX:raise MathError("%s(): the list is too long."%name)
    return [_math_scalar(value,"An item of %s()"%name) for value in values]
def _math_binary(op,left,right):
    left=_math_scalar(left);right=_math_scalar(right)
    try:
        if op=="+":return _math_check_number(left+right)
        if op=="-":return _math_check_number(left-right)
        if op=="*":return _math_check_number(left*right)
        if op in("/","//","%"):
            if right==0:raise MathError("Division by zero.")
            return _math_check_number(left/right if op=="/" else left//right if op=="//" else left%right)
        if op=="**":
            if isinstance(left,int) and isinstance(right,int) and right>=0:
                if abs(left)>1 and right*(abs(left).bit_length()-1)>=_MATH_BITS_MAX:raise MathError("The number is too large.")   # checked before the power is computed
                return _math_check_number(left**right)
            if left==0 and right<0:raise MathError("Division by zero.")
            result=float(left)**float(right)
            if isinstance(result,complex):raise MathError("The result is not a real number.")
            return _math_check_number(result)
    except OverflowError:raise MathError("The number is too large.") from None
    except ZeroDivisionError:raise MathError("Division by zero.") from None
    raise MathError("Unknown operator %r."%op)
def _math_one(args,name):
    if len(args)!=1:raise MathError("%s() takes one value."%name)
    return _math_scalar(args[0],"The value of %s()"%name)
def _math_call(name,args):
    try:
        if name=="len":
            if len(args)!=1:raise MathError("len() takes one value.")
            return len(args[0]) if isinstance(args[0],(list,tuple,dict,str)) else (0 if args[0] is None else 1)
        if name=="sum":return _math_check_number(sum(_math_numbers(args,name)))
        if name in("min","max"):
            numbers=_math_numbers(args,name)
            if not numbers:raise MathError("%s() has nothing to compare."%name)
            return min(numbers) if name=="min" else max(numbers)
        if name=="round":
            if len(args) not in(1,2):raise MathError("round() takes a value and an optional number of decimals.")
            digits=int(_math_scalar(args[1],"The decimals of round()")) if len(args)==2 else 0
            if not -12<=digits<=12:raise MathError("round(): decimals must be between -12 and 12.")
            result=round(_math_scalar(args[0],"The value of round()"),digits)
            return int(result) if digits<=0 else result
        value=_math_one(args,name)
        if name=="abs":return abs(value)
        if name=="floor":return math.floor(value)
        if name=="ceil":return math.ceil(value)
        if name=="int":return int(value)
        if name=="float":return float(value)
        if name=="sqrt":
            if value<0:raise MathError("sqrt() of a negative number.")
            return math.sqrt(value)
    except OverflowError:raise MathError("The number is too large.") from None
    raise MathError("Unknown function %s()."%name)
MATH_FUNCTIONS=("min","max","abs","round","floor","ceil","sqrt","len","sum","int","float")
class _MathParser:
    def __init__(self,tokens,lookup):
        self.tokens=tokens;self.position=0;self.lookup=lookup;self.depth=0
    def peek(self):
        return self.tokens[self.position] if self.position<len(self.tokens) else (None,None)
    def op(self,*symbols):
        kind,value=self.peek()
        if kind=="op" and value in symbols:
            self.position+=1
            return value
        return None
    def deeper(self):
        self.depth+=1
        if self.depth>_MATH_DEPTH_MAX:raise MathError("The expression is nested too deep.")
    def parse(self):
        value=self.expr()
        if self.position<len(self.tokens):raise MathError("Unexpected %r."%str(self.peek()[1])[:20])
        return value
    def expr(self):
        value=self.term()
        while True:
            symbol=self.op("+","-")
            if symbol is None:return value
            value=_math_binary(symbol,value,self.term())
    def term(self):
        value=self.unary()
        while True:
            symbol=self.op("*","/","//","%")
            if symbol is None:return value
            value=_math_binary(symbol,value,self.unary())
    def unary(self):
        symbol=self.op("-","+")
        if symbol is None:return self.power()
        self.deeper()
        value=_math_scalar(self.unary())
        self.depth-=1
        return -value if symbol=="-" else value
    def power(self):
        base=self.atom()
        if self.op("**") is None:return base
        self.deeper()
        exponent=self.unary()   # right-associative, and -2**2 is -(2**2)
        self.depth-=1
        return _math_binary("**",base,exponent)
    def atom(self):
        kind,value=self.peek()
        if kind is None:raise MathError("The expression ends too early.")
        self.position+=1
        if kind=="num":return value
        if kind=="ref":return self.value_of(value[2:-1].strip())
        if kind=="name":
            if self.peek()==("op","("):
                if value not in MATH_FUNCTIONS:raise MathError("Unknown function %s()."%value[:40])
                self.position+=1;self.deeper()
                args=[]
                if self.op(")") is None:
                    while True:
                        args.append(self.expr())
                        if self.op(")") is not None:break
                        if self.op(",") is None:raise MathError("Missing ) after %s(."%value)
                        if len(args)>50:raise MathError("%s() has too many values."%value)
                self.depth-=1
                return _math_call(value,args)
            return self.value_of(value)
        if kind=="op" and value=="(":
            self.deeper()
            inner=self.expr()
            if self.op(")") is None:raise MathError("Missing ).")
            self.depth-=1
            return inner
        raise MathError("Unexpected %r."%str(value)[:20])
    def value_of(self,name):
        if name.startswith("raw:"):name=name[4:].strip()
        if self.lookup is None:return 1   # syntax check only
        value=self.lookup(name)
        if value is None:raise MathError("%s has no value."%name[:60])
        return value
def math_eval(expression,lookup=None):
    """Evaluate an arithmetic expression. lookup(name) -> value of a variable / ${path} (None = unknown). Raises MathError."""
    try:return _math_check_number(_math_scalar(_MathParser(_math_tokens(expression),lookup).parse(),"The result"))
    except RecursionError:raise MathError("The expression is nested too deep.") from None
def math_check(expression):
    """Syntax check at validation time (every name counts as 1; a division by zero only shows at run time)."""
    try:_MathParser(_math_tokens(expression),None).parse()
    except MathError as exc:
        if "zero" in str(exc) or "too large" in str(exc) or "negative" in str(exc):return None
        raise
    except RecursionError:raise MathError("The expression is nested too deep.") from None
    return None
# ---------------------------------------------------------------- scan output parsing
_IPISH=re.compile(r"^(?:\d{1,3}(?:\.\d{1,3}){3}|[0-9A-Fa-f:]*:[0-9A-Fa-f:.]*)$")
_PORTS_MAX=50000
def _scan_port(port,proto,state,service="",version=""):
    try:number=int(str(port).strip())
    except (TypeError,ValueError):return None
    if not 0<=number<=65535:return None
    return {"port":number,"proto":str(proto or "").lower()[:12],"state":str(state or "").lower()[:24],"service":str(service or "")[:120],"version":" ".join(str(version or "").split())[:300]}
def _scan_result(hosts,fmt):
    ports=[];numbers=set();total=0
    for host in hosts:
        total+=len(host["ports"])
        for port in host["ports"]:
            if port["state"]!="open":continue
            ports.append(dict(port,host=host["ip"] or host["hostname"],ip=host["ip"],hostname=host["hostname"]))
            numbers.add(port["port"])
    return {"format":fmt,"hosts":hosts,"ports":ports,"open_ports":sorted(numbers),"host_count":len(hosts),"port_count":total}
def _scan_normal(text):
    from Cores.Services import flow_rules
    hosts=[]
    for raw in flow_rules.parse_tool_output("nmap",text).get("hosts") or []:
        name=str(raw.get("host") or "");names=[str(n) for n in raw.get("hostnames") or [] if n]
        ip=name if _IPISH.match(name) else ""
        ports=[p for p in (_scan_port(q.get("port"),q.get("proto"),q.get("state"),q.get("service"),q.get("version")) for q in raw.get("ports") or [] if isinstance(q,dict)) if p]
        hosts.append({"ip":ip,"hostname":names[0] if names else ("" if ip else name),"state":"up","ports":ports})
    return hosts
def _scan_xml(text):
    import xml.etree.ElementTree as ET
    if "<!entity" in text.lower():raise ValueError("The XML declares an entity, so it was refused.")
    start=min([i for i in (text.find("<?xml"),text.find("<nmaprun")) if i>=0],default=-1)
    end=text.rfind("</nmaprun>")
    if start<0:raise ValueError("This is not nmap XML output.")
    body=text[start:end+len("</nmaprun>")] if end>start else text[start:]
    try:root=ET.fromstring(body.encode("utf-8","replace"))
    except ET.ParseError as exc:raise ValueError("The nmap XML could not be read (%s). Was the scan cut short?"%exc) from None
    if root.tag!="nmaprun":raise ValueError("This is not nmap XML output.")
    hosts=[];total=0
    for element in root.iter("host"):
        status=element.find("status")
        ip="";fallback=""
        for address in element.findall("address"):
            if address.get("addrtype") in("ipv4","ipv6") and not ip:ip=str(address.get("addr") or "")
            elif not fallback:fallback=str(address.get("addr") or "")
        name=next((str(h.get("name") or "") for h in element.iter("hostname") if h.get("name")),"")
        ports=[]
        for port in element.iter("port"):
            state=port.find("state");service=port.find("service")
            version=" ".join(str(service.get(key) or "") for key in("product","version","extrainfo")) if service is not None else ""
            row=_scan_port(port.get("portid"),port.get("protocol"),state.get("state") if state is not None else "",service.get("name") if service is not None else "",version)
            if row:ports.append(row)
        total+=len(ports)
        hosts.append({"ip":(ip or fallback)[:80],"hostname":name[:255],"state":str(status.get("state") if status is not None else "up").lower()[:24],"ports":ports})
        if len(hosts)>=ITEMS_MAX or total>=_PORTS_MAX:break
    return hosts
_GREP_HOST=re.compile(r"^Host:\s+(\S+)\s+\(([^)]*)\)")
def _scan_grep(text):
    hosts={};total=0
    for line in text.splitlines():
        match=_GREP_HOST.match(line)
        if not match:continue
        key=match.group(1)
        host=hosts.get(key)
        if host is None:
            if len(hosts)>=ITEMS_MAX:break
            host=hosts[key]={"ip":key[:80] if _IPISH.match(key) else "","hostname":match.group(2)[:255] or ("" if _IPISH.match(key) else key[:255]),"state":"up","ports":[]}
        for part in line.split("\t")[1:]:
            label,_,value=part.partition(":")
            label=label.strip().lower();value=value.strip()
            if label=="status":host["state"]=value.lower()[:24] or "up"
            elif label=="ports":
                for entry in value.split(","):
                    bits=entry.strip().split("/")
                    if len(bits)<3:continue
                    row=_scan_port(bits[0],bits[2],bits[1],bits[4] if len(bits)>4 else "",bits[6] if len(bits)>6 else "")
                    if row and total<_PORTS_MAX:
                        host["ports"].append(row);total+=1
    return list(hosts.values())
def detect_scan_format(text):
    head=text.lstrip()[:4000]
    if head.startswith("<?xml") or "<nmaprun" in text[:20000]:return "nmap_xml"
    if re.search(r"^Host:\s+\S+\s+\([^)]*\)\s*\t?\s*(?:Status|Ports):",text,re.M):return "nmap_grep"
    return "nmap"
def parse_scan(text,fmt="auto"):
    """nmap normal / XML (-oX) / grepable (-oG) output -> {"format","hosts":[{"ip","hostname","state","ports":[{"port","proto",
    "state","service","version"}]}],"ports":[open ports with their host],"open_ports":[numbers],...}. Raises ValueError."""
    text=str(text or "").replace("\r\n","\n")
    if len(text)>SCAN_MAX:raise ValueError("The scan output is larger than %d MB."%(SCAN_MAX//(1024*1024)))
    if fmt not in("nmap","nmap_xml","nmap_grep"):fmt=detect_scan_format(text)
    hosts={"nmap":_scan_normal,"nmap_xml":_scan_xml,"nmap_grep":_scan_grep}[fmt](text)
    return _scan_result(hosts,fmt)
# ---------------------------------------------------------------- executor helpers
def _rules():
    from Cores.Services import flow_rules
    return flow_rules
def _engine():
    from Cores.Services import flow_engine
    return flow_engine
def _cfg(node):
    return node.get("config") if isinstance(node.get("config"),dict) else {}
def _warn(run,node,warnings):
    for warning in warnings or []:run._event(node["id"],"warn",str(warning))
_UNSET=object()
def _scope(run,last,item=_UNSET,index=None):
    scope=run._scope(last)
    if item is not _UNSET:scope["item"]=item;scope["index"]=index
    return scope
def _expand(run,node,last,text,scope=None):
    """Text with {Placeholders} (live target) and ${values} filled in, as plain text. Leading/trailing blanks survive."""
    text=str(text if text is not None else "")
    core=text.strip()
    if not core:return text
    lead=text[:len(text)-len(text.lstrip())];tail=text[len(text.rstrip()):]
    value,_missing,warnings=_engine().resolve_command(core,run.replacer,scope if scope is not None else _scope(run,last),None,raw_ok=lambda name:True)
    _warn(run,node,warnings)
    return lead+str(value)+tail
def _resolve(run,node,last,text,scope=None):
    """A source: exactly one ${name} gives the value itself (lists stay lists); anything else is expanded as text."""
    value,warnings=_rules().resolve_value(text,scope if scope is not None else _scope(run,last))
    _warn(run,node,warnings)
    return value
def _value(run,node,last,text):
    """Like _resolve, but text around the value also gets its {Placeholders} filled."""
    rules=_rules()
    match=rules._TEMPLATE_RE.fullmatch(str(text or "").strip())
    if match and not match.group(1):return _resolve(run,node,last,text)
    return _expand(run,node,last,text)
def _as_text(value):
    return value if isinstance(value,str) else _rules().to_text(value)
def _as_list(run,node,value):
    if value is None:return []
    if isinstance(value,tuple):value=list(value)
    if isinstance(value,str):value=_rules().split_items(value,"auto",1000)
    elif not isinstance(value,list):value=[value]
    if len(value)>ITEMS_MAX:
        run._event(node["id"],"warn","More than %d items: only the first %d are used"%(ITEMS_MAX,ITEMS_MAX))
        value=value[:ITEMS_MAX]
    return value
def _tidy(number):
    return int(number) if isinstance(number,float) and number.is_integer() and abs(number)<1e15 else number
def _json_size(value):
    try:return len(json.dumps(value,ensure_ascii=False,separators=(",",":"),default=str))
    except (TypeError,ValueError,RecursionError):return PARSED_CAP+1
def cap_value(value,limit=PARSED_CAP):
    """(a JSON-safe value of at most ~limit characters, truncated?) for the run status."""
    if value is None or isinstance(value,(bool,int,float)):return value,False
    if isinstance(value,str):return (value,False) if len(value)<=limit else (value[:limit],True)
    if _json_size(value)<=limit:
        try:return json.loads(json.dumps(value,ensure_ascii=False,default=str)),False
        except (TypeError,ValueError,RecursionError):return str(value)[:limit],True
    if isinstance(value,list):
        kept=[];used=2
        for item in value:
            size=_json_size(item)+1
            if used+size>limit:break
            kept.append(item);used+=size
        return cap_value(kept,limit)[0],True
    try:preview=json.dumps(value,ensure_ascii=False,default=str)[:limit//2]
    except (TypeError,ValueError,RecursionError):preview=str(value)[:limit//2]
    return {"truncated":True,"preview":preview},True
def _emit(run,node,env,output,value,text=None):
    """Hand a node's value on: the envelope (parsed + text form), the variable named by config.var (never trusted for
    ${raw:...}) and the capped copies the run status shows."""
    env["parsed"]=value
    env["stdout"]=_as_text(value) if text is None else str(text)
    env["stderr"]="";env["exit_code"]=0
    shown,cut=cap_value(value)
    output["parsed"]=shown
    if cut:output["truncated"]=True
    name=str(_cfg(node).get("var") or "").strip()
    if name and VAR_RE.match(name):
        run.vars[name]=value
        run.trusted.discard(name)
        output["vars_set"]={name:shown}
    else:output.setdefault("vars_set",{})
def _say(run,node,text):
    run._event(node["id"],"info",str(text)[:500])
def _unescape(text):
    return str(text or "").replace("\\n","\n").replace("\\t","\t").replace("\\r","\r")
# ---------------------------------------------------------------- executors: inputs
def _targets_api():
    from Cores.Bridge import api as _api
    return _api.TargetsAPI()
def _find_target(api,name):
    wanted=str(name or "").strip().lower()
    if not wanted:return None
    return next((t for t in api.targets() if isinstance(t,dict) and str(t.get("name") or "").strip().lower()==wanted),None)
def _refresh_live(run):
    name,values,replacer=_engine().live_target()
    current=run
    while current is not None:
        current.target_name,current.target_values,current.replacer=name,values,replacer
        current=current.parent
def _h_input_target(run,node,last,env,output):
    cfg=_cfg(node)
    if cfg.get("source")=="name":
        wanted=_expand(run,node,last,cfg.get("name")).strip()
        target=_find_target(_targets_api(),wanted)
        if target is None:
            _say(run,node,"There is no target named '%s'"%wanted[:80])
            return {"branch":"missing"}
        name=str(target.get("name") or "")
        values={str(k).lower():v for k,v in (target.get("values") or {}).items() if str(v or "").strip()}
    else:
        name=str(run.target_name or "");values=dict(run.target_values or {})
        if not name and not values:
            _say(run,node,"There is no live target")
            return {"branch":"missing"}
    value=dict(values);value["name"]=name;value["values"]=values
    _emit(run,node,env,output,value,text=name)
    _say(run,node,"Target: "+name[:80])
    return {"branch":"out"}
def _read_format(text,fmt):
    if fmt=="lines":return [line.strip() for line in text.splitlines() if line.strip()][:ITEMS_MAX]
    if fmt=="csv":
        rows=[]
        for row in csv.reader(io.StringIO(text)):
            cells=[cell.strip() for cell in row]
            if any(cells):rows.append(cells)
            if len(rows)>=ITEMS_MAX:break
        return rows
    if fmt=="json":
        try:return json.loads(text)
        except ValueError:raise ValueError("The text is not valid JSON.") from None
    return text
def _h_input_text(run,node,last,env,output):
    cfg=_cfg(node)
    value=_read_format(_expand(run,node,last,cfg.get("text")),str(cfg.get("format") or "text"))
    _emit(run,node,env,output,value)
    return {"branch":"out"}
def _inside(path,root):
    path=os.path.normcase(path);root=os.path.normcase(root)
    try:return os.path.commonpath([path,root])==root
    except ValueError:return False   # another drive
def safe_path(text):
    """An absolute (or ~) path a chain may read or write -> its real path. Raises ValueError for anything else,
    including every path inside the app's Data/ and Backups/ folders (symlinks are followed first)."""
    from Cores import common_db
    path=os.path.expanduser(str(text or "").strip())
    if not path:raise ValueError("The file path is empty.")
    if "\x00" in path:raise ValueError("The file path is not valid.")
    if not os.path.isabs(path):raise ValueError("The file path must be absolute or start with ~: "+path[:200])
    real=os.path.realpath(path)
    for label,folder in(("Data",common_db.data_dir),("Backups",common_db.backups_dir)):
        try:root=os.path.realpath(folder())
        except Exception:continue
        if _inside(real,root):raise ValueError("A chain may not read or write files inside the app's %s folder."%label)
    return real
def _audit(event,detail,success=True):
    _engine()._audit(event,detail,success)
def _h_input_file(run,node,last,env,output):
    cfg=_cfg(node)
    path=safe_path(_expand(run,node,last,cfg.get("path")))
    limit=int(_number(cfg.get("max_kb"),1024,1,FILE_KB_MAX,True))*1024
    if not os.path.isfile(path):raise ValueError("There is no file at "+path[:300])
    size=os.path.getsize(path)
    if size>limit:raise ValueError("The file is larger than %d KB (%d KB)."%(limit//1024,size//1024+1))
    with open(path,"rb") as handle:raw=handle.read(limit+1)
    if len(raw)>limit:raise ValueError("The file is larger than %d KB."%(limit//1024))
    _audit("chain_file_read",f"run {run.root.run_id} chain {run.root.playbook_id} node {node['id']} read {path[:400]} ({len(raw)} bytes)")
    value=_read_format(raw.decode("utf-8",errors="replace").replace("\r\n","\n"),str(cfg.get("format") or "text"))
    _emit(run,node,env,output,value)
    output["file"]={"path":path,"bytes":len(raw)}
    _say(run,node,"Read %s (%d bytes)"%(path[:200],len(raw)))
    return {"branch":"out"}
# ---------------------------------------------------------------- executors: http
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):return None
class _HttpOnlyRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        if urllib.parse.urlsplit(newurl).scheme.lower() not in("http","https"):raise urllib.error.URLError("redirect to a non-HTTP address refused")
        return super().redirect_request(req,fp,code,msg,headers,newurl)
def _http_fetch(opener,request,timeout,limit,stop,box,follow=True):
    response=None
    try:
        try:response=opener.open(request,timeout=timeout)
        except urllib.error.HTTPError as exc:
            response=exc   # a 4xx/5xx answer is still an answer
            where=str(exc.headers.get("Location") or "") if exc.headers is not None else ""
            # urllib would not follow this redirect (file:, ftp:, a loop ...): that is a failed request, not an answer.
            if follow and 300<=int(exc.code or 0)<400 and where:
                raise urllib.error.URLError("redirect to "+urllib.parse.urlsplit(urllib.parse.urljoin(request.full_url,where)).scheme[:20]+": address refused") from None
        box["response"]=response
        chunks=[];held=0
        while held<limit and not stop.is_set() and request.get_method()!="HEAD":
            chunk=response.read(min(16384,limit-held))
            if not chunk:break
            chunks.append(chunk);held+=len(chunk)
        box.update(status=int(getattr(response,"status",None) or getattr(response,"code",0) or 0),url=str(response.geturl() or request.full_url),
                   headers=[(str(k),str(v)) for k,v in response.headers.items()][:80],charset=response.headers.get_content_charset() or "",
                   content_type=str(response.headers.get("Content-Type") or ""),body=b"".join(chunks),truncated=held>=limit)
    except Exception as exc:
        box["error"]=exc
    finally:
        try:
            if response is not None:response.close()
        except Exception:pass
def http_request(method,url,headers=None,body="",timeout=30,verify_tls=True,follow_redirects=True,max_kb=512,stop=None):
    """One HTTP(S) request through urllib. -> {"status","headers","body","json"?,"url","elapsed_ms","truncated"}.
    Raises ValueError (bad URL, connection problem, timeout, stopped). `stop` is a threading.Event checked while waiting."""
    url=str(url or "").strip()
    parts=urllib.parse.urlsplit(url)
    if parts.scheme.lower() not in("http","https") or not parts.netloc:raise ValueError("Only http:// and https:// addresses can be requested: "+url[:200])
    if any(ch in url for ch in "\r\n\x00 "):raise ValueError("The URL contains a space or a line break.")
    method=str(method or "GET").upper()
    if method not in HTTP_METHODS:raise ValueError("Unknown HTTP method "+method[:20])
    data=str(body or "").encode("utf-8","replace") if body and method not in("GET","HEAD") else None
    request=urllib.request.Request(url,data=data,method=method)
    sent=set()
    for name,value in headers or []:
        name=str(name or "").strip();value=str(value if value is not None else "")
        if not name:continue
        if not _HEADER_NAME.match(name) or any(ch in value for ch in "\r\n\x00"):raise ValueError("Header %r is not valid."%name[:60])
        request.add_header(name,value);sent.add(name.lower())
    if "user-agent" not in sent:request.add_header("User-Agent","LOYA-NG/1.0.4")
    if data is not None and "content-type" not in sent and str(body).lstrip()[:1] in("{","["):request.add_header("Content-Type","application/json")
    context=ssl.create_default_context()
    if not verify_tls:
        context.check_hostname=False;context.verify_mode=ssl.CERT_NONE
    opener=urllib.request.build_opener(_HttpOnlyRedirect() if follow_redirects else _NoRedirect(),urllib.request.HTTPSHandler(context=context))
    timeout=max(1.0,min(300.0,float(timeout or 30)))
    limit=max(1,min(FILE_KB_MAX,int(max_kb or 512)))*1024
    stop=stop if stop is not None else threading.Event()
    mine=threading.Event();box={}
    worker=threading.Thread(target=_http_fetch,args=(opener,request,timeout,limit,mine,box,bool(follow_redirects)),name="flow-http",daemon=True)
    began=time.monotonic();worker.start()
    deadline=began+timeout+1.0
    while worker.is_alive():
        worker.join(0.05)
        halted=stop.is_set()
        if halted or time.monotonic()>deadline:
            mine.set()
            try:
                if box.get("response") is not None:box["response"].close()
            except Exception:pass
            raise ValueError("stopped" if halted else "Timed out after %d s"%int(timeout))
    elapsed=int((time.monotonic()-began)*1000)
    if "error" in box:
        exc=box["error"]
        reason=getattr(exc,"reason",None)
        if isinstance(reason,ssl.SSLCertVerificationError) or isinstance(exc,ssl.SSLCertVerificationError):raise ValueError("The TLS certificate could not be verified (%s). Turn off 'Verify the TLS certificate' for a lab host."%str(getattr(reason,"verify_message","") or reason or exc)[:200])
        if isinstance(exc,TimeoutError) or isinstance(reason,TimeoutError) or "timed out" in str(exc).lower():raise ValueError("Timed out after %d s"%int(timeout))
        raise ValueError("The request failed: "+str(reason or exc)[:300])
    try:text=box["body"].decode(box["charset"] or "utf-8",errors="replace")
    except LookupError:text=box["body"].decode("utf-8",errors="replace")
    result={"status":box["status"],"headers":{name:value[:2000] for name,value in box["headers"]},"body":text,"url":box["url"],"elapsed_ms":elapsed,"truncated":bool(box["truncated"])}
    if "json" in box["content_type"].lower() or text.lstrip()[:1] in("{","["):
        try:result["json"]=json.loads(text)
        except ValueError:pass
    return result
def _h_http(run,node,last,env,output):
    cfg=_cfg(node)
    method=str(cfg.get("method") or "GET").upper()
    url=_expand(run,node,last,cfg.get("url")).strip()
    headers=[(_expand(run,node,last,row.get("name")).strip(),_expand(run,node,last,row.get("value"))) for row in cfg.get("headers") or [] if isinstance(row,dict)]
    body=_expand(run,node,last,cfg.get("body"))
    timeout=min(_number(cfg.get("timeout"),30,1,300,True),max(1.0,run._remaining()))
    try:_engine()._terminal().audit_command("[http] "+method+" "+url[:800],run.job_source,"flow:"+run.root.run_id)
    except Exception:pass
    run._event(node["id"],"info",method+" "+url[:400],"http",{"method":method,"url":url[:800],"verify_tls":cfg.get("verify_tls") is not False,"follow_redirects":cfg.get("follow_redirects") is not False,"timeout":timeout})
    result=http_request(method,url,headers,body,timeout,cfg.get("verify_tls") is not False,cfg.get("follow_redirects") is not False,cfg.get("max_kb"),run._halt_evt)
    _emit(run,node,env,output,result,text=result["body"])
    env["exit_code"]=0 if result["status"]<400 else 1
    output["http"]={"status":result["status"],"url":result["url"],"elapsed_ms":result["elapsed_ms"],"headers":result["headers"]}
    ok=0<result["status"]<400
    run._note("http",node["id"],"HTTP %d in %d ms (%d bytes)"%(result["status"],result["elapsed_ms"],len(result["body"])),{"status":result["status"],"url":result["url"][:800],"elapsed_ms":result["elapsed_ms"],"bytes":len(result["body"]),"truncated":result["truncated"]},"info" if ok else "warn" if run.edges_out.get((node["id"],"fail")) else "error")
    run._exit_noted.add(node["id"])
    if ok:return {"branch":"success"}
    return {"ok":False,"branch":"fail","error":"HTTP "+str(result["status"])}
# ---------------------------------------------------------------- executors: logic
def _h_switch(run,node,last,env,output):
    rules=_rules();cfg=_cfg(node);scope=_scope(run,last)
    actual=_resolve(run,node,last,cfg.get("value"),scope)
    ci=cfg.get("ci",True) is not False
    chosen="";trace=[]
    for case in cfg.get("cases") or []:
        expected,warnings=rules.expand_template(str(case.get("value") if case.get("value") is not None else ""),scope)
        _warn(run,node,warnings)
        op=str(case.get("op") or "equals")
        matched=bool(rules._apply(op,actual,expected,ci))
        trace.append({"branch":str(case.get("name") or ""),"matched":matched,"conditions":[{"text":"value %s %s"%(op.replace("_"," "),expected[:80]),"result":matched,"actual":rules.to_text(actual)[:200]}]})
        if matched:
            chosen=str(case.get("name") or "");break
    output["trace"]=trace
    branch=chosen or str(cfg.get("default") or "default")
    _say(run,node,"Switch: "+branch)
    return {"branch":branch}
def _h_merge(run,node,last,env,output):
    cfg=_cfg(node);node_id=node["id"]
    state=run._merge.setdefault(node_id,{"count":0,"items":[]})
    state["count"]+=1
    collect=str(cfg.get("collect") or "parsed")
    if collect=="parsed" and (last or {}).get("parsed") is not None:state["items"].append((last or {}).get("parsed"))
    elif collect=="stdout" and str((last or {}).get("stdout") or "")!="":state["items"].append(str((last or {}).get("stdout") or ""))
    del state["items"][:-ITEMS_MAX]
    items=list(state["items"])
    if cfg.get("mode")=="all":
        wanted=max(1,int(run.edges_in.get(node_id,1)))
        if state["count"]<wanted:
            output["merge"]={"arrived":state["count"],"of":wanted}
            _say(run,node,"Merge: %d of %d arrived, waiting"%(state["count"],wanted))
            return {"branch":""}
        run._merge.pop(node_id,None)   # the next round (a loop) starts empty
        output["merge"]={"arrived":wanted,"of":wanted}
    _emit(run,node,env,output,items)
    _say(run,node,"Merge: %d value(s)"%len(items))
    return {"branch":"out"}
def _h_math(run,node,last,env,output):
    cfg=_cfg(node);rules=_rules();scope=_scope(run,last)
    value=math_eval(str(cfg.get("expr") or ""),lambda name:rules.resolve(scope,name))
    decimals=int(_number(cfg.get("decimals"),-1,-1,12,True))
    if decimals>=0:value=round(value,decimals) if decimals else int(round(value))
    value=_tidy(value)
    _emit(run,node,env,output,value)
    _say(run,node,"%s = %s"%(str(cfg.get("var") or "result"),rules.to_text(value)))
    return {"branch":"out"}
# ---------------------------------------------------------------- executors: transform
def _h_template(run,node,last,env,output):
    _emit(run,node,env,output,_expand(run,node,last,_cfg(node).get("template")))
    return {"branch":"out"}
def _object_source(run,node,last,text):
    value=_resolve(run,node,last,text)
    if isinstance(value,str) and value.strip():
        try:value=_rules()._load_json(value)
        except ValueError:raise ValueError("The source is text, not an object or a list of objects.") from None
    return value
def _h_fields(run,node,last,env,output):
    cfg=_cfg(node);rules=_rules()
    source=_object_source(run,node,last,cfg.get("source"))
    if source is None or source=="":source={}
    ops=[row for row in cfg.get("ops") or [] if isinstance(row,dict) and str(row.get("field") or "").strip()]
    def change(obj,index):
        if not isinstance(obj,dict):raise ValueError("Edit fields works on objects; item %d is not one."%(index+1))
        out=dict(obj);keep=None
        for row in ops:
            field=str(row["field"]).strip();op=row.get("op")
            if op=="set":out[field]=_resolve(run,node,last,row.get("value"),_scope(run,last,obj,index))
            elif op=="rename":
                new=_expand(run,node,last,row.get("value")).strip()
                if new and field in out:out={(new if key==field else key):value for key,value in out.items()}
            elif op=="remove":out.pop(field,None)
            elif op=="keep":keep=(keep or [])+[name.strip() for name in field.split(",") if name.strip()]
        return out if keep is None else {key:value for key,value in out.items() if key in keep}
    if isinstance(source,list):value=[change(item,index) for index,item in enumerate(source[:ITEMS_MAX])]
    else:value=change(source,0)
    _emit(run,node,env,output,value)
    return {"branch":"out"}
def _h_map(run,node,last,env,output):
    cfg=_cfg(node)
    items=_as_list(run,node,_resolve(run,node,last,cfg.get("source")))
    template=str(cfg.get("template") if cfg.get("template") is not None else "${item}")
    rules=_rules();mapped=[];unknown=set()
    for index,item in enumerate(items):
        value,warnings=rules.resolve_value(template,_scope(run,last,item,index))
        unknown.update(str(w) for w in warnings or [])
        mapped.append(value)
    _warn(run,node,sorted(unknown)[:5])
    _emit(run,node,env,output,mapped)
    _say(run,node,"Map: %d item(s)"%len(mapped))
    return {"branch":"out"}
def _h_filter(run,node,last,env,output):
    cfg=_cfg(node);rules=_rules();scope=_scope(run,last)
    items=_as_list(run,node,_resolve(run,node,last,cfg.get("source")))
    ci=cfg.get("ci",True) is not False
    tests=[]
    for row in cfg.get("conditions") or []:
        expected,warnings=rules.expand_template(str(row.get("value") if row.get("value") is not None else ""),scope)
        _warn(run,node,warnings)
        tests.append((str(row.get("field") or "").strip(),str(row.get("op") or "contains"),expected))
    every=cfg.get("match")!="any"
    def passes(item):
        results=(bool(rules._apply(op,item if not field else (rules.lookup(item,field) if isinstance(item,(dict,list)) else None),expected,ci)) for field,op,expected in tests)
        return all(results) if every else any(results)
    kept=[item for item in items if passes(item)] if tests else list(items)
    _emit(run,node,env,output,kept)
    _say(run,node,"Filter: kept %d of %d"%(len(kept),len(items)))
    return {"branch":"out" if kept else "empty"}
def _regex_wrap(pattern):
    """The pattern inside one outer group, so findall always gives [whole match, group 1, ...] rows."""
    lead=re.match(r"^\(\?[aiLmsux]+\)",pattern)
    return (lead.group(0) if lead else "")+"("+pattern[lead.end() if lead else 0:]+")"
def _regex_rows(pattern,text,flags,limit=ITEMS_MAX):
    rows=_rules().regex_findall(_regex_wrap(pattern),text,flags,limit=limit)
    return [row if isinstance(row,(list,tuple)) else [row] for row in rows]
def _h_split(run,node,last,env,output):
    cfg=_cfg(node);rules=_rules()
    text=_as_text(_resolve(run,node,last,cfg.get("source")))
    mode=str(cfg.get("mode") or "lines");separator=str(cfg.get("separator") or "")
    if mode=="json":
        loaded=rules._load_json(text) if text.strip() else []
        parts=loaded if isinstance(loaded,list) else [loaded]
    elif mode=="comma":parts=text.split(",")
    elif mode=="whitespace":parts=text.split()
    elif mode=="separator":
        separator=_unescape(separator)
        if not separator:raise ValueError("The separator is empty.")
        parts=text.split(separator)
    elif mode=="regex":
        parts=[];position=0
        for row in _regex_rows(separator,text,""):
            found=str(row[0])
            if not found:continue
            at=text.find(found,position)
            if at<0:continue
            parts.append(text[position:at]);position=at+len(found)
        parts.append(text[position:])
    else:parts=text.splitlines()
    if mode!="json":
        if cfg.get("trim",True) is not False:parts=[part.strip() for part in parts]
        if cfg.get("drop_empty",True) is not False:parts=[part for part in parts if part!=""]
    if len(parts)>ITEMS_MAX:
        run._event(node["id"],"warn","More than %d items: only the first %d are kept"%(ITEMS_MAX,ITEMS_MAX));parts=parts[:ITEMS_MAX]
    _emit(run,node,env,output,parts,text="\n".join(_as_text(part) for part in parts))
    _say(run,node,"Split: %d item(s)"%len(parts))
    return {"branch":"out"}
def _h_join(run,node,last,env,output):
    cfg=_cfg(node)
    items=_as_list(run,node,_resolve(run,node,last,cfg.get("source")))
    _emit(run,node,env,output,_unescape(cfg.get("separator") if cfg.get("separator") is not None else "\n").join(_as_text(item) for item in items))
    return {"branch":"out"}
def _h_regex(run,node,last,env,output):
    cfg=_cfg(node);rules=_rules()
    text=_as_text(_resolve(run,node,last,cfg.get("source")))
    pattern=str(cfg.get("pattern") or "");flags=clean_flags(cfg.get("flags"))
    group=str(cfg.get("group") or "0").strip() or "0"
    rules.check_regex(pattern,flags)
    compiled=re.compile(pattern,rules._flag_bits(flags))   # only to read its groups; matching goes through the guarded flow_rules functions
    if group.isdigit():
        index=int(group)
        if index>compiled.groups:raise ValueError("The pattern has no group %d."%index)
    else:
        index=compiled.groupindex.get(group)
        if index is None:raise ValueError("The pattern has no group named '%s'."%group[:40])
    first=cfg.get("mode")=="first"
    rows=_regex_rows(pattern,text,flags,1 if first else ITEMS_MAX)
    found=[row[index] if index<len(row) and row[index] is not None else "" for row in rows]
    output["match_count"]=len(found)
    if not found:
        _emit(run,node,env,output,"" if first else [],text="")
        _say(run,node,"Regex: no match")
        return {"branch":"nomatch"}
    value=found[0] if first else found
    _emit(run,node,env,output,value,text=found[0] if first else "\n".join(str(f) for f in found))
    _say(run,node,"Regex: %d match(es)"%len(found))
    return {"branch":"out"}
def _h_json(run,node,last,env,output):
    cfg=_cfg(node);rules=_rules()
    action=str(cfg.get("action") or "parse")
    source=_resolve(run,node,last,cfg.get("source"))
    if action=="format":
        if isinstance(source,str) and source.strip()[:1] in("{","["):
            try:source=json.loads(source)
            except ValueError:pass
        indent=int(_number(cfg.get("indent"),2,0,8,True))
        _emit(run,node,env,output,json.dumps(source,ensure_ascii=False,indent=indent or None,separators=None if indent else (",",":"),default=str))
        return {"branch":"out"}
    value=rules._load_json(source) if isinstance(source,str) else source
    if value is None:raise ValueError("There is no JSON to read.")
    if action=="get":
        path=_expand(run,node,last,cfg.get("path")).strip()
        value=rules.lookup(value,path)
        if value is None:raise ValueError("There is nothing at '%s'."%path[:120])
    _emit(run,node,env,output,value)
    return {"branch":"out"}
# ---------------------------------------------------------------- executors: analysis
def _sort_key(value,numeric):
    rules=_rules()
    if numeric:
        number=rules._number(value)
        return (number is None,number if number is not None else 0.0,"")
    return (value is None,0.0,rules.to_text(value).lower())
def _h_collection(run,node,last,env,output):
    cfg=_cfg(node);rules=_rules()
    items=_as_list(run,node,_resolve(run,node,last,cfg.get("source")))
    op=str(cfg.get("op") or "count");field=str(cfg.get("field") or "").strip()
    pick=(lambda item:rules.lookup(item,field) if isinstance(item,(dict,list)) else None) if field else (lambda item:item)
    numeric=cfg.get("numeric") is True
    if op=="count":value=len(items)
    elif op in("sum","avg"):
        numbers=[n for n in (rules._number(pick(item)) for item in items) if n is not None]
        if len(numbers)<len(items):run._event(node["id"],"warn","%d item(s) are not numbers and were skipped"%(len(items)-len(numbers)))
        value=_tidy(float(sum(numbers))) if op=="sum" else (_tidy(sum(numbers)/len(numbers)) if numbers else 0)
    elif op in("min","max"):
        values=[v for v in (pick(item) for item in items) if v is not None]
        numbers=[rules._number(v) for v in values]
        if values and (numeric or all(n is not None for n in numbers)):
            numbers=[n for n in numbers if n is not None]
            value=_tidy(min(numbers) if op=="min" else max(numbers)) if numbers else None
        else:value=(min if op=="min" else max)(values,key=lambda v:rules.to_text(v).lower()) if values else None
    elif op=="dedupe":
        seen=set();value=[]
        for item in items:
            key=json.dumps(pick(item),sort_keys=True,ensure_ascii=False,default=str)
            if key not in seen:
                seen.add(key);value.append(item)
    elif op=="sort":value=sorted(items,key=lambda item:_sort_key(pick(item),numeric),reverse=cfg.get("order")=="desc")
    elif op=="reverse":value=list(reversed(items))
    elif op=="limit":value=items[:int(_number(cfg.get("limit"),10,1,ITEMS_MAX,True))]
    elif op=="first":value=items[0] if items else None
    elif op=="last":value=items[-1] if items else None
    elif op in("group","group_count"):
        groups={}
        for item in items:groups.setdefault(rules.to_text(pick(item)),[]).append(item)
        value=groups if op=="group" else {key:len(members) for key,members in groups.items()}
    elif op=="flatten":
        value=[]
        for item in items:
            if isinstance(item,list):value.extend(item)
            else:value.append(item)
        value=value[:ITEMS_MAX]
    elif op=="pluck":value=[v for v in (pick(item) for item in items) if v is not None]
    else:raise ValueError("Unknown list operation '%s'"%op)
    _emit(run,node,env,output,value)
    _say(run,node,"%s: %s"%(op,rules.to_text(value)[:120] if not isinstance(value,(list,dict)) else "%d item(s)"%len(value)))
    return {"branch":"out"}
def _h_scan_parse(run,node,last,env,output):
    cfg=_cfg(node)
    text=_as_text(_resolve(run,node,last,cfg.get("source")))
    try:result=parse_scan(text,str(cfg.get("format") or "auto"))
    except ValueError as exc:
        return {"branch":"nomatch","error":str(exc)[:300]}
    _emit(run,node,env,output,result,text=text)
    found=bool(result["hosts"])
    _say(run,node,"Scan (%s): %d host(s), %d open port(s)"%(result["format"],len(result["hosts"]),len(result["ports"])))
    return {"branch":"out" if found else "nomatch"}
# ---------------------------------------------------------------- executors: app
def _done(run,node,output,result):
    output["result"]=result
    _say(run,node,str(result.get("text") or ""))
def _h_note(run,node,last,env,output):
    import html
    from Cores.Bridge import api as _api
    from Cores.Services import notes_service
    cfg=_cfg(node);action=str(cfg.get("action") or "upsert")
    name=_expand(run,node,last,cfg.get("note_name")).strip()[:200] or ("Chain output - "+str(run.root.name or "chain"))
    content=_expand(run,node,last,cfg.get("content"))
    title=_expand(run,node,last,cfg.get("title")).strip()[:200]
    if not content.strip():raise ValueError("Nothing to write to the note")
    body=(("<p><strong>"+html.escape(title)+"</strong></p>") if title else "")+"<pre>"+html.escape(content)+"</pre>"
    found=next((n for n in notes_service._load_notes(notes_service._db_path()) if str(n.get("note_name") or "").strip().lower()==name.lower()),None)
    if action=="append" and not found:raise ValueError("There is no note named '%s'"%name[:120])
    if action=="create" and found:raise ValueError("A note named '%s' already exists"%name[:120])
    notes_api=_api.NotesAPI()
    saved=notes_api.append(found["id"],body) if found else notes_api.save(None,name,"",body,[],"")
    _done(run,node,output,{"action":action,"note_id":saved.get("id") if isinstance(saved,dict) else None,"text":("Appended to" if found else "Created")+" note '"+name+"'"})
    return {"branch":"out"}
def _find_report(reports_service,wanted):
    reports=reports_service.list_reports()
    wanted=str(wanted or "").strip()
    if not wanted:
        if not reports:raise ValueError("There is no report to add the finding to. Create a report first.")
        return reports[0]["id"]
    if wanted.isdigit() and any(int(r["id"])==int(wanted) for r in reports):return int(wanted)
    match=next((r for r in reports if str(r.get("title") or "").strip().lower()==wanted.lower()),None)
    if match is None:raise ValueError("There is no report '%s'"%wanted[:120])
    return match["id"]
def _h_finding(run,node,last,env,output):
    import html
    from Cores.Services import reports_service
    cfg=_cfg(node)
    report_id=_find_report(reports_service,_expand(run,node,last,cfg.get("report")))
    title=_expand(run,node,last,cfg.get("title")).strip()[:200] or str(node.get("title") or "Chain finding")
    severity=str(cfg.get("severity") or "info").lower()
    if severity not in reports_service.SEVERITIES:severity="info"
    finding=reports_service.add_finding(report_id,{"title":title,"severity":severity,"description":"<pre>"+html.escape(_expand(run,node,last,cfg.get("description")))+"</pre>","tags":["chain-draft"]})
    _done(run,node,output,{"action":"finding","finding_id":finding.get("id"),"report_id":report_id,"text":"Finding '"+title[:80]+"' added to report "+str(report_id)})
    return {"branch":"out"}
def _h_report_create(run,node,last,env,output):
    from Cores.Services import reports_service
    name=_expand(run,node,last,_cfg(node).get("name")).strip()[:200]
    if not name:raise ValueError("The report title is empty")
    report=reports_service.create_report({"title":name})
    _emit(run,node,env,output,report.get("id"))
    _done(run,node,output,{"action":"report_create","report_id":report.get("id"),"text":"Report '"+name[:80]+"' created (id "+str(report.get("id"))+")"})
    return {"branch":"out"}
def _is_live(target):
    return str(target.get("status") or "").strip().lower()=="live"
def _h_target_update(run,node,last,env,output):
    cfg=_cfg(node);api=_targets_api()
    key=_expand(run,node,last,cfg.get("key")).strip().strip("{}").strip()
    value=_expand(run,node,last,cfg.get("value")).strip()
    if not key:raise ValueError("The parameter name is empty")
    if cfg.get("target")=="name":
        wanted=_expand(run,node,last,cfg.get("name")).strip()
        target=_find_target(api,wanted)
        if target is None and cfg.get("create_missing") is True and wanted:
            api.upsert_target(None,wanted,"not_used",{})
            target=_find_target(api,wanted)
    else:
        wanted="the live target"
        target=next((t for t in api.targets() if isinstance(t,dict) and _is_live(t)),None)
    if target is None:
        _say(run,node,"Target not found: "+wanted[:80])
        return {"branch":"missing"}
    known=next((k for k in api._get_store().ordered_keys() if str(k).strip().lower()==key.lower()),None)
    if known is None:
        api.add_key(key,0)
        known=next((k for k in api._get_store().ordered_keys() if str(k).strip().lower()==key.lower()),key)
    values=dict(target.get("values") or {})
    values[known]=value
    api.upsert_target(target["id"],target["name"],target.get("status") or "not_used",values)
    if _is_live(target):_refresh_live(run)
    _done(run,node,output,{"action":"target_update","target":target["name"],"key":known,"text":"Set "+str(known)+" on target '"+str(target["name"])[:80]+"'"})
    return {"branch":"out"}
def _h_live_target(run,node,last,env,output):
    api=_targets_api()
    wanted=_expand(run,node,last,_cfg(node).get("name")).strip()
    target=_find_target(api,wanted)
    if target is None:
        _say(run,node,"There is no target named '%s'"%wanted[:80])
        return {"branch":"missing"}
    if not _is_live(target):api.set_live_target(target["id"])   # set_live_target on the live target would clear it
    _refresh_live(run)
    _audit("chain_live_target",f"run {run.root.run_id} chain {run.root.playbook_id} made '{str(target['name'])[:120]}' the live target")
    _done(run,node,output,{"action":"live_target","target":target["name"],"text":"Live target: "+str(target["name"])[:80]})
    return {"branch":"out"}
def _h_cve_lookup(run,node,last,env,output):
    from Cores.Services import cve_service
    cfg=_cfg(node)
    query=_expand(run,node,last,cfg.get("query")).strip()[:200]
    if not query:raise ValueError("The CVE search is empty")
    found=cve_service.search(query,int(_number(cfg.get("limit"),5,1,50,True)),None)   # local only: the cache and the offline index
    rows=[{key:row.get(key) for key in("id","title","severity","score","kev","epss","published") if key in row} for row in (found.get("results") if isinstance(found,dict) else found) or [] if isinstance(row,dict)]
    _emit(run,node,env,output,rows,text="\n".join("%s %s %s"%(row.get("id"),str(row.get("severity") or ""),str(row.get("title") or "")) for row in rows))
    _say(run,node,"CVE lookup: %d result(s) for '%s'"%(len(rows),query[:80]))
    return {"branch":"found" if rows else "none"}
# ---------------------------------------------------------------- executors: outputs
def _h_file_write(run,node,last,env,output):
    cfg=_cfg(node)
    path=safe_path(_expand(run,node,last,cfg.get("path")))
    content=_expand(run,node,last,cfg.get("content"))
    data=content.encode("utf-8","replace")
    if len(data)>WRITE_MAX:raise ValueError("The text is larger than %d MB."%(WRITE_MAX//(1024*1024)))
    if os.path.isdir(path):raise ValueError("That path is a folder: "+path[:300])
    append=cfg.get("mode")=="append"
    folder=os.path.dirname(path)
    if folder:os.makedirs(folder,exist_ok=True)
    path=safe_path(path)   # again, now that the folders exist (a symlinked parent)
    with open(path,"ab" if append else "wb") as handle:handle.write(data)
    _audit("chain_file_write",f"run {run.root.run_id} chain {run.root.playbook_id} node {node['id']} {'appended to' if append else 'wrote'} {path[:400]} ({len(data)} bytes)")
    output["file"]={"path":path,"bytes":len(data),"mode":"append" if append else "overwrite"}
    _done(run,node,output,{"action":"file_write","path":path,"text":("Appended %d bytes to " if append else "Wrote %d bytes to ")%len(data)+path[:200]})
    return {"branch":"out"}
def _h_result(run,node,last,env,output):
    cfg=_cfg(node)
    value=_value(run,node,last,cfg.get("value"))
    label=_expand(run,node,last,cfg.get("label")).strip()[:200] or str(node.get("title") or "Result")
    shown,cut=cap_value(value)
    root=run.root
    with root._lock:
        results=root.data.setdefault("results",[])
        results.append({"node":node["id"] if run is root else run._root_node(),"label":label,"value":shown})
        del results[:-RESULTS_MAX]
    output["parsed"]=shown;output["stdout"]=_as_text(shown)[:PARSED_CAP]
    if cut:output["truncated"]=True
    _done(run,node,output,{"action":"result","label":label,"text":"Result '"+label[:80]+"'"})
    return {"branch":"out"}
def _h_log(run,node,last,env,output):
    cfg=_cfg(node)
    level=cfg.get("level") if cfg.get("level") in("info","warn","error") else "info"
    message=_expand(run,node,last,cfg.get("message"))[:4000]
    run._event(node["id"],level,message,"message",{"level":level})
    output["result"]={"action":"log","level":level,"text":message[:500]}
    return {"branch":"out"}
HANDLERS={"input_target":_h_input_target,"input_text":_h_input_text,"input_file":_h_input_file,"http":_h_http,"switch":_h_switch,"merge":_h_merge,
          "math":_h_math,"template":_h_template,"fields":_h_fields,"map":_h_map,"filter":_h_filter,"split":_h_split,"join":_h_join,"regex":_h_regex,
          "json":_h_json,"collection":_h_collection,"scan_parse":_h_scan_parse,"note":_h_note,"finding":_h_finding,"report_create":_h_report_create,
          "target_update":_h_target_update,"cve_lookup":_h_cve_lookup,"live_target":_h_live_target,"file_write":_h_file_write,"result":_h_result,"log":_h_log}
def run_node(run,node,last,env,output):
    """Execute one field-driven node for flow_engine.FlowRun._run_node. -> {"branch","ok"?,"error"?}; raising = the node failed."""
    handler=HANDLERS.get(str(node.get("type") or ""))
    if handler is None:raise ValueError("Unknown node type '"+str(node.get("type") or "")+"'")
    result=handler(run,node,last,env,output)
    output.setdefault("vars_set",{})
    return result
# ---------------------------------------------------------------- plans (dry run, run confirmation, AI approval prompt)
def action_summary(node,replacer=None):
    """One line saying what a node would do outside the run ("" for a node that only works on run data).
    {Placeholders} are filled from the live target; ${values} stay as written because they do not exist yet."""
    cfg=_cfg(node);node_type=node.get("type")
    def shown(key,limit=300):
        try:text=_engine().resolve_command(str(cfg.get(key) or ""),replacer,keep_tokens=True)[0]
        except Exception:text=str(cfg.get(key) or "")
        return " ".join(str(text).split())[:limit]
    if node_type=="http":return "%s %s"%(str(cfg.get("method") or "GET"),shown("url",600))+("" if cfg.get("verify_tls") is not False else " (TLS not verified)")
    if node_type=="file_write":return "Write file %s (%s)"%(shown("path"),"append" if cfg.get("mode")=="append" else "overwrite")
    if node_type=="input_file":return "Read file %s"%shown("path")
    if node_type=="note":return "%s note '%s'"%({"create":"Create","append":"Append to"}.get(cfg.get("action"),"Append to or create"),shown("note_name",120) or "Chain output")
    if node_type=="finding":return "Add a %s finding to %s"%(str(cfg.get("severity") or "info"),("report '%s'"%shown("report",120)) if str(cfg.get("report") or "").strip() else "the newest report")
    if node_type=="report_create":return "Create report '%s'"%shown("name",120)
    if node_type=="target_update":return "Set %s on %s"%(shown("key",80),("target '%s'"%shown("name",120)) if cfg.get("target")=="name" else "the live target")
    if node_type=="live_target":return "Make '%s' the live target"%shown("name",120)
    if node_type=="cve_lookup":return "Search the offline CVE index for '%s'"%shown("query",120)
    return ""
def plan_line(node,replacer=None):
    """The dry-run log line of a field-driven node, or ""."""
    summary=action_summary(node,replacer)
    if not summary:return ""
    if node.get("type")=="http":return "Would request "+summary
    return "Would "+summary[:1].lower()+summary[1:]
def plan_actions(nodes,scope=None,replacer=None):
    """[{node,title,type,summary}] for the nodes (inside `scope`, when given) that act on the world outside the run."""
    out=[]
    for node in nodes or []:
        if not isinstance(node,dict) or node.get("type") not in ACTION_TYPES:continue
        if scope is not None and node.get("id") not in scope:continue
        out.append({"node":node.get("id"),"title":str(node.get("title") or ""),"type":node.get("type"),"summary":action_summary(node,replacer)})
    return out
