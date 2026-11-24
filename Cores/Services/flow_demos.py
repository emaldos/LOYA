"""Built-in demo chain diagrams: worked pentest workflows that show off the node catalog.

They ship in code like the starter templates in flow_schema (TEMPLATES), but are larger and each carries one sticky
note that explains what it does and how to use it. Every graph is built at import time and passes
flow_schema.validate_graph with no errors and no warnings.

Command lines only use live-target placeholders ({IPv4}) and HTTP requests only go to the live target or example.com
hosts, so a demo is safe to run against an authorised lab target. flow_schema must never import this module.
"""
import copy
from Cores.Services import flow_schema as _schema
# ---------------------------------------------------------------- layout
COL_X=300        # column step: a node is 240 wide, so 60 px between columns
ROW_Y=210        # row step: room for a node with up to 5 output ports (190 px) plus a 20 px gap
TOP_Y=230        # first row of nodes; the sticky note sits above it
NOTE_X=40;NOTE_Y=20
class _Demo:
    """Small graph builder: nodes on a grid (column, row), sequential ids, one sticky note at the top left."""
    def __init__(self):
        self.graph=_schema.new_graph();self.graph["nodes"]=[];self.graph["edges"]=[]
    def node(self,node_type,title,column,row,/,**config):
        node_id="n%d"%(len(self.graph["nodes"])+1)
        merged=_schema._defaults(node_type);merged.update(config)
        self.graph["nodes"].append({"id":node_id,"type":node_type,"title":title,"x":40+COL_X*column,"y":TOP_Y+ROW_Y*row,"config":merged})
        return node_id
    def note(self,text,width=620,height=160,color="yellow"):
        node_id="n%d"%(len(self.graph["nodes"])+1)
        self.graph["nodes"].append({"id":node_id,"type":"comment","title":"About this demo","x":NOTE_X,"y":NOTE_Y,
                                    "config":{"text":text,"color":color,"w":width,"h":height}})
        return node_id
    def edges(self,*rows):
        for source,port,target in rows:
            self.graph["edges"].append({"id":"e%d"%(len(self.graph["edges"])+1),"from":source,"port":port,"to":target})
        return self.graph
def _commands(*lines):
    return [{"text":line,"command_id":None,"src":"","label":""} for line in lines]
def _cond(source,op,value="",field="",ci=True):
    return {"source":source,"field":field,"op":op,"value":value,"ci":ci}
# A canned nmap normal-output scan of the Nmap project's public test host, so the summary demo runs without a scan file.
SAMPLE_SCAN="""Starting Nmap 7.94 ( https://nmap.org )
Nmap scan report for scanme.nmap.org (45.33.32.156)
Host is up (0.15s latency).
Not shown: 995 closed tcp ports (reset)
PORT      STATE    SERVICE    VERSION
22/tcp    open     ssh        OpenSSH 6.6.1p1 Ubuntu 2ubuntu2.13 (Ubuntu Linux; protocol 2.0)
80/tcp    open     http       Apache httpd 2.4.7 ((Ubuntu))
443/tcp   open     https      Apache httpd 2.4.7 ((Ubuntu))
9929/tcp  open     nping-echo Nping echo
31337/tcp open     tcpwrapped
Nmap done: 1 IP address (1 host up) scanned in 12.34 seconds
"""
# ---------------------------------------------------------------- demos
def _nmap_host_triage():
    d=_Demo()
    d.note("Nmap host triage\n\nScans the live target with nmap (XML output), reads every open port and sorts it: "
           "web services become report findings, everything else goes to a port inventory note.\n\n"
           "Set a live target with an IPv4 value, then press Run. Only scan hosts you are allowed to test.")
    start=d.node("start","Start",0,0)
    scan=d.node("command","Nmap service scan",1,0,commands=_commands("nmap -Pn -sV --top-ports 200 -oX - {IPv4}"),timeout=1800)
    parse=d.node("scan_parse","Read the XML",2,0,format="nmap_xml",source="${last.stdout}",var="scan")
    report=d.node("report_create","New triage report",3,0,name="Nmap triage ${target.ipv4}",var="report_id")
    loop=d.node("foreach","Each open port",4,0,items="${scan.ports}",max_items=200)
    web=d.node("decision","Web service?",5,0,branches=[{"name":"web","match":"any","conditions":[
        _cond("var","regex",r"^(80|443|8000|8080|8443)$",field="item.port"),_cond("var","regex",r"http",field="item.service")]}],**{"else":"other"})
    finding=d.node("finding","Web service finding",6,0,report="${report_id}",title="Web service on ${item.host}:${item.port}",severity="info",
                   description="${item.service} ${item.version} answers on ${item.port}/${item.proto}. Enumerate it next.")
    inventory=d.node("note","Port inventory",6,1,action="upsert",note_name="Nmap triage ${target.ipv4}",title="${item.port}/${item.proto} ${item.service}",
                     content="Host ${item.host}: ${item.service} ${item.version}")
    summary=d.node("result","Open ports",5,1,label="Open ports",value="${scan.open_ports}")
    done=d.node("end","Triage done",6,2,status="success",message="Triage finished.")
    nothing=d.node("log","Nothing open",3,1,level="warn",message="The scan found no open port on ${target.ipv4}.")
    failed=d.node("end","Scan failed",2,1,status="fail",message="The nmap scan failed; see the run log.")
    return d.edges((start,"out",scan),(scan,"success",parse),(scan,"fail",failed),(parse,"out",report),(parse,"nomatch",nothing),
                   (report,"out",loop),(loop,"item",web),(web,"web",finding),(web,"other",inventory),
                   (loop,"done",summary),(summary,"out",done),(nothing,"out",done))
def _http_status_switch():
    d=_Demo()
    d.note("HTTP status switch\n\nRequests a list of URLs without following redirects and routes each answer by its status code: "
           "2xx pages get their title collected, 3xx redirects, 4xx errors and anything else are logged.\n\n"
           "Edit the URL list (the live target's {IPv4} plus example.com), then Run. The collected lines show as a notification.")
    start=d.node("start","Start",0,0)
    urls=d.node("input_text","URLs to check",1,0,format="lines",var="urls",
                text="http://{IPv4}/\nhttps://{IPv4}/\nhttps://example.com/\nhttp://example.com/missing-page")
    loop=d.node("foreach","Each URL",2,0,items="${urls}",max_items=50)
    get=d.node("http","GET (no redirects)",3,0,method="GET",url="${item}",timeout=15,verify_tls=False,follow_redirects=False,max_kb=256,var="response")
    status=d.node("switch","Status code",4,0,value="${response.status}",default="other",ci=True,cases=[
        {"name":"ok","op":"regex","value":r"^2\d\d$"},{"name":"redirect","op":"regex","value":r"^3\d\d$"},{"name":"client_error","op":"regex","value":r"^4\d\d$"}])
    title=d.node("regex","Page title",5,0,source="${response.body}",pattern=r"<title[^>]*>([^<]{1,200})",flags="i",mode="first",group="1",var="title")
    line=d.node("template","One line per page",6,0,template="${item} [${response.status}] ${title}",var="line")
    collect=d.node("merge","Collect live pages",7,0,mode="any",collect="stdout",var="live")
    moved=d.node("log","Redirect",5,1,level="info",message="${item} redirects to ${response.headers.location}")
    denied=d.node("log","Client error",5,2,level="warn",message="${item} answered ${response.status}")
    other=d.node("log","No usable answer",5,3,level="warn",message="${item}: no 2xx, 3xx or 4xx answer (${response.status})")
    joined=d.node("join","Join the lines",3,1,source="${live}",separator="\n",var="live_text")
    show=d.node("output","Show live pages",4,1,action="notify",title="Live pages",content="${live_text}")
    return d.edges((start,"out",urls),(urls,"out",loop),(loop,"item",get),(get,"success",status),(get,"fail",status),
                   (status,"ok",title),(status,"redirect",moved),(status,"client_error",denied),(status,"other",other),
                   (title,"out",line),(title,"nomatch",line),(line,"out",collect),
                   (loop,"done",joined),(joined,"out",show))
def _subdomain_probe():
    d=_Demo()
    d.note("Subdomain probe\n\nTakes a pasted subdomain list, splits it, removes duplicates, sorts it and turns each name into an "
           "https:// URL. Every URL is probed; hosts that answer become findings in a new report.\n\n"
           "Replace the example.com names with in-scope subdomains (for example from your passive recon), then Run.")
    start=d.node("start","Start",0,0)
    raw=d.node("input_text","Subdomain list",1,0,format="text",var="raw",
               text="www.example.com\napi.example.com\nwww.example.com\nmail.example.com\n\ndev.example.com")
    split=d.node("split","One per line",2,0,source="${raw}",mode="lines",trim=True,drop_empty=True,var="subs")
    unique=d.node("collection","Remove duplicates",3,0,op="dedupe",source="${subs}",var="unique")
    ordered=d.node("collection","Sort A to Z",4,0,op="sort",source="${unique}",order="asc",var="hosts")
    urls=d.node("map","Build URLs",5,0,source="${hosts}",template="https://${item}/",var="urls")
    report=d.node("report_create","New report",6,0,name="Subdomain probe ${target.domain}",var="report_id")
    loop=d.node("foreach","Each URL",7,0,items="${urls}",max_items=100)
    probe=d.node("http","Probe",8,0,method="GET",url="${item}",timeout=10,verify_tls=True,follow_redirects=True,max_kb=64,var="response")
    live=d.node("finding","Live web host",9,0,report="${report_id}",title="Live web host ${item}",severity="info",
                description="${item} answered ${response.status} (server: ${response.headers.server}).")
    dead=d.node("log","No answer",9,1,level="warn",message="${item} did not answer (${response.status})")
    total=d.node("result","Hosts probed",8,1,label="Hosts probed",value="${hosts}")
    done=d.node("end","Done",9,2,status="success",message="Probed the subdomain list.")
    return d.edges((start,"out",raw),(raw,"out",split),(split,"out",unique),(unique,"out",ordered),(ordered,"out",urls),
                   (urls,"out",report),(report,"out",loop),(loop,"item",probe),(probe,"success",live),(probe,"fail",dead),
                   (loop,"done",total),(total,"out",done))
def _cve_for_services():
    d=_Demo()
    d.note("CVEs for services\n\nRuns an nmap version scan, keeps the open ports that report a product version and looks each "
           "service up in the offline CVE index. Matches are drafted as medium findings for you to verify.\n\n"
           "Set a live target, then Run. Nothing is sent to the internet for the lookup; a match is a lead, not a confirmed issue.")
    start=d.node("start","Start",0,0)
    scan=d.node("command","Version scan",1,0,commands=_commands("nmap -Pn -sV --top-ports 100 {IPv4}"),timeout=1800)
    parse=d.node("scan_parse","Read the scan",2,0,format="nmap",source="${last.stdout}",var="scan")
    versioned=d.node("filter","Has a version",3,0,source="${scan.ports}",match="all",ci=True,var="versioned",
                     conditions=[{"field":"version","op":"not_empty","value":""}])
    query=d.node("fields","Add a search query",4,0,source="${versioned}",var="services",
                 ops=[{"op":"set","field":"query","value":"${item.service} ${item.version}"}])
    report=d.node("report_create","New report",5,0,name="CVE leads ${target.ipv4}",var="report_id")
    loop=d.node("foreach","Each service",6,0,items="${services}",max_items=100)
    lookup=d.node("cve_lookup","CVE lookup",7,0,query="${item.query}",limit=5,var="cves")
    ids=d.node("collection","CVE ids",8,0,op="pluck",source="${cves}",field="id",var="cve_ids")
    finding=d.node("finding","CVE lead finding",9,0,report="${report_id}",severity="medium",
                   title="Possible CVEs for ${item.service} on ${item.host}:${item.port}",
                   description="Service: ${item.service} ${item.version}\nIndex matches: ${cve_ids}\nVerify the exact version before reporting.")
    clean=d.node("log","No CVE match",8,1,level="info",message="No CVE in the index for ${item.query}")
    done=d.node("end","Done",7,2,status="success",message="CVE lookup finished.")
    nothing=d.node("log","No versions",4,1,level="warn",message="No open port reported a product version.")
    failed=d.node("end","Scan failed",2,1,status="fail",message="The nmap scan failed; see the run log.")
    return d.edges((start,"out",scan),(scan,"success",parse),(scan,"fail",failed),(parse,"out",versioned),(parse,"nomatch",nothing),
                   (versioned,"out",query),(versioned,"empty",nothing),(query,"out",report),(report,"out",loop),
                   (loop,"item",lookup),(lookup,"found",ids),(lookup,"none",clean),(ids,"out",finding),
                   (loop,"done",done),(nothing,"out",done))
def _target_update_approval():
    d=_Demo()
    d.note("Target update with approval\n\nReads the live target, grabs the HTTP Server header with curl and asks you before "
           "storing it as the WebServer parameter on the target. The target then stays live and the change is noted.\n\n"
           "Set a live target with an IPv4 value, then Run. Reject the approval to leave the target untouched.")
    start=d.node("start","Start",0,0)
    target=d.node("input_target","Live target",1,0,source="live",var="tgt")
    banner=d.node("command","HTTP headers",2,0,commands=_commands("curl -skI --max-time 10 http://{IPv4}/"),timeout=30)
    header=d.node("parse","Server header",3,0,mode="regex",source="stdout",pattern=r"^Server:\s*(?P<server>[^\r\n]+)",flags="im",
                  assign=[{"var":"server","from":"group:server"}],var="server_match")
    ask=d.node("approval","Save it?",4,0,message="Store WebServer = ${server} on target ${tgt.name}?",timeout=0)
    update=d.node("target_update","Store on target",5,0,target="live",key="WebServer",value="${server}")
    keep=d.node("live_target","Keep it live",6,0,name="${tgt.name}")
    note=d.node("note","Note the change",7,0,action="upsert",note_name="Target changes",title="${tgt.name}",content="WebServer set to ${server}")
    done=d.node("end","Saved",8,0,status="success",message="WebServer stored on the target.")
    declined=d.node("log","Declined",5,1,level="info",message="Operator kept the target unchanged.")
    lost=d.node("log","Target gone",6,2,level="warn",message="The target ${tgt.name} no longer exists.")
    no_header=d.node("log","No Server header",4,2,level="warn",message="The answer had no Server header.")
    stopped=d.node("end","Stopped",7,2,status="success",message="Nothing was stored.")
    no_target=d.node("end","No live target",2,1,status="fail",message="Pick a live target first.")
    no_answer=d.node("end","No HTTP answer",3,1,status="fail",message="curl got no HTTP answer from the target.")
    return d.edges((start,"out",target),(target,"out",banner),(target,"missing",no_target),(banner,"success",header),(banner,"fail",no_answer),
                   (header,"out",ask),(header,"nomatch",no_header),(ask,"approved",update),(ask,"rejected",declined),
                   (update,"out",keep),(update,"missing",lost),(keep,"out",note),(keep,"missing",lost),(note,"out",done),
                   (declined,"out",stopped),(lost,"out",stopped),(no_header,"out",stopped))
def _scan_analysis_summary():
    d=_Demo()
    d.note("Scan analysis summary\n\nReads a saved nmap scan (~/scans/nmap-demo.txt). When the file is not there it falls back to "
           "a built-in sample scan of scanme.nmap.org, so the demo always runs. It counts hosts and open ports, counts ports per "
           "service and writes the summary to a note, a result and a demo text file.\n\n"
           "Point File input at your own nmap -oN output to analyse a real scan.",height=180)
    start=d.node("start","Start",0,0)
    load=d.node("input_file","Saved scan file",1,0,path="~/scans/nmap-demo.txt",format="text",max_kb=1024,var="scan_text")
    sample=d.node("input_text","Sample scan",2,1,text=SAMPLE_SCAN,format="text",var="scan_text")
    parse=d.node("scan_parse","Read the scan",3,0,format="nmap",source="${scan_text}",var="scan")
    hosts=d.node("collection","Count hosts",4,0,op="count",source="${scan.hosts}",var="host_count")
    ports=d.node("collection","Count open ports",5,0,op="count",source="${scan.ports}",var="port_count")
    per_service=d.node("collection","Ports per service",6,0,op="group_count",source="${scan.ports}",field="service",var="per_service")
    as_json=d.node("json","Format as JSON",7,0,action="format",source="${per_service}",indent=2,var="per_service_text")
    summary=d.node("template","Write the summary",8,0,var="summary",
                   template="Hosts up: ${host_count}\nOpen ports: ${port_count} (${scan.open_ports})\nPorts per service:\n${per_service_text}")
    note=d.node("note","Summary note",9,0,action="upsert",note_name="Scan summary",title="Scan analysis",content="${summary}")
    save=d.node("file_write","Save a copy",10,0,path="~/loya-demos/scan-summary.txt",content="${summary}",mode="overwrite")
    result=d.node("result","Summary",11,0,label="Scan summary",value="${summary}")
    done=d.node("end","Done",12,0,status="success",message="Scan summary written.")
    bad_json=d.node("log","JSON failed",8,1,level="error",message="Could not format the per-service counts.")
    not_saved=d.node("log","File not saved",11,1,level="warn",message="Could not write ~/loya-demos/scan-summary.txt")
    empty=d.node("log","No hosts in scan",4,1,level="warn",message="The scan text has no host or open port.")
    return d.edges((start,"out",load),(load,"out",parse),(load,"error",sample),(sample,"out",parse),
                   (parse,"out",hosts),(parse,"nomatch",empty),(hosts,"out",ports),(ports,"out",per_service),(per_service,"out",as_json),
                   (as_json,"out",summary),(as_json,"error",bad_json),(bad_json,"out",summary),(summary,"out",note),(note,"out",save),
                   (save,"out",result),(save,"error",not_saved),(not_saved,"out",result),(result,"out",done),(empty,"out",done))
def _logic_math_tour():
    d=_Demo()
    d.note("Logic and math tour\n\nNo network, no commands: a walk through the logic nodes. It sets a few variables, loops over a "
           "port list with a running total and a short pause, averages the ports, reads a threshold from JSON and branches on it. "
           "The math and JSON error ports lead to a fail end.\n\n"
           "Run it and watch the run log; edit the port list or the JSON to see other paths.",height=180,color="blue")
    start=d.node("start","Start",0,0)
    setup=d.node("set","Set the inputs",1,0,assign=[{"var":"ports","value":"22,80,443,8080"},{"var":"total","value":"0"},
                                                     {"var":"settings","value":"{\"threshold\": 1000}"}])
    loop=d.node("foreach","Each port",2,0,items="${ports}",split="comma",max_items=20)
    add=d.node("math","Running total",3,0,expr="total + int(item)",var="total",decimals=-1)
    line=d.node("template","Port line",4,0,template="port ${item} (total so far ${total})",var="line")
    collect=d.node("merge","Collect lines",5,0,mode="any",collect="stdout",var="lines")
    pause=d.node("wait","Short pause",6,0,seconds=1)
    split=d.node("split","Port list",3,1,source="${ports}",mode="comma",trim=True,drop_empty=True,var="port_list")
    average=d.node("math","Average port",4,1,expr="total / len(port_list)",var="average",decimals=1)
    config=d.node("json","Read the settings",5,1,action="parse",source="${settings}",var="cfg")
    high=d.node("decision","Above threshold?",6,1,branches=[{"name":"high","match":"all","conditions":[
        _cond("var","gt","${cfg.threshold}",field="average")]}],**{"else":"low"})
    is_high=d.node("result","High average",7,1,label="Average port (high)",value="${average}")
    is_low=d.node("result","Low average",7,2,label="Average port (low)",value="${average}")
    done=d.node("end","Done",8,1,status="success",message="Tour finished; the average is in the results.")
    math_err=d.node("log","Math error",5,3,level="error",message="A calculation failed (empty port list?).")
    failed=d.node("end","Failed",6,3,status="fail",message="The tour stopped on an error.")
    return d.edges((start,"out",setup),(setup,"out",loop),(loop,"item",add),(add,"out",line),(add,"error",math_err),
                   (line,"out",collect),(collect,"out",pause),
                   (loop,"done",split),(split,"out",average),(average,"out",config),(average,"error",math_err),(config,"out",high),(config,"error",failed),
                   (high,"high",is_high),(high,"low",is_low),(is_high,"out",done),(is_low,"out",done),(math_err,"out",failed))
# ---------------------------------------------------------------- registry
DEMOS=[
    {"id":"nmap-host-triage","name":"Nmap host triage","tags":["nmap","recon","findings","notes"],
     "description":"Scan the live target with nmap XML output and sort every open port: web services become findings, the rest go to a port inventory note.",
     "graph":_nmap_host_triage()},
    {"id":"http-status-switch","name":"HTTP status switch","tags":["http","web","switch"],
     "description":"Request a list of URLs and route each answer by status code: 2xx titles are collected, redirects and errors are logged.",
     "graph":_http_status_switch()},
    {"id":"subdomain-probe","name":"Subdomain probe","tags":["recon","subdomains","http","findings"],
     "description":"Clean up a pasted subdomain list (split, dedupe, sort), probe each host over HTTPS and report the live ones as findings.",
     "graph":_subdomain_probe()},
    {"id":"cve-for-services","name":"CVEs for services","tags":["nmap","cve","findings"],
     "description":"Version-scan the live target, look every versioned service up in the offline CVE index and draft findings for the matches.",
     "graph":_cve_for_services()},
    {"id":"target-update-approval","name":"Target update with approval","tags":["targets","approval","http"],
     "description":"Grab the HTTP Server header of the live target and, after your approval, store it as a parameter on the target.",
     "graph":_target_update_approval()},
    {"id":"scan-analysis-summary","name":"Scan analysis summary","tags":["nmap","analysis","notes","offline"],
     "description":"Read a saved nmap scan (or a built-in sample), count hosts, ports and services, and write a summary note.",
     "graph":_scan_analysis_summary()},
    {"id":"logic-math-tour","name":"Logic and math tour","tags":["logic","math","tutorial","offline"],
     "description":"A no-network tour of loops, variables, math, merge, wait, JSON, decisions and error ports.",
     "graph":_logic_math_tour()},
]
def demo(demo_id):
    """A deep copy of the demo's graph, or None for an unknown id."""
    for entry in DEMOS:
        if entry["id"]==demo_id:return copy.deepcopy(entry["graph"])
    return None
def summaries():
    """[{"id","name","description","tags","node_count"}] for every demo, in order (node_count includes the sticky note)."""
    return [{"id":entry["id"],"name":entry["name"],"description":entry["description"],"tags":list(entry["tags"]),
             "node_count":len(entry["graph"]["nodes"])} for entry in DEMOS]
