// Chain diagram model (UI/js/components/flow-model.js) and the DOM-free helpers of the editor (UI/js/components/flow-editor.js).
const fs=require("fs")
const path=require("path")
const vm=require("vm")
const ROOT=path.resolve(__dirname,"..","..")
const read=(...p)=>fs.readFileSync(path.join(ROOT,...p),"utf8")
const MODEL=read("UI","js","components","flow-model.js")
const CATALOG=read("UI","js","components","flow-catalog.js")
const EDITOR=read("UI","js","components","flow-editor.js")
const CSS=read("UI","css","flow-editor.css")
let passed=0,failed=0
function check(name,cond,detail){if(cond){passed++;return}failed++;console.log("  FAIL  "+name+(detail?"  ->  "+detail:""))}
function eq(name,a,b){check(name,JSON.stringify(a)===JSON.stringify(b),JSON.stringify(a)+" != "+JSON.stringify(b))}
function throws(name,fn){let ok=false;try{fn()}catch(e){ok=e instanceof Error||(e&&typeof e.message==="string")}check(name,ok)}
// ---- the model loads without any DOM (no document/window in the sandbox) and exports through module.exports
// The page loads flow-catalog.js first (the global FLOW_CATALOG), then the model: the same here.
const sandbox={module:{exports:{}},console}
vm.createContext(sandbox)
vm.runInContext(CATALOG+"\n"+MODEL,sandbox)
const M=sandbox.module.exports
const CAT=M.FLOW_CAT
// ... and once with no catalog at all (no global, no require): only the built-in types exist.
const bare={module:{exports:{}},console}
vm.createContext(bare)
vm.runInContext(MODEL,bare)
const M0=bare.module.exports
check("model: no DOM access in the source",!/\b(document|window|navigator|localStorage|sessionStorage)\b/.test(MODEL.replace(/\/\/.*$/gm,"")))
check("model: required by node directly too",typeof require(path.join(ROOT,"UI","js","components","flow-model.js")).flowNewGraph==="function")
const SPEC_FUNCS=["flowNewGraph","flowClone","flowNodePorts","flowNewId","flowAddNode","flowRemoveNodes","flowMoveNodes","flowConnect","flowRemoveEdges","flowRenamePort","flowPruneEdges","flowValidate","flowAutoLayout","flowHistoryCreate","flowCopy","flowPaste","flowSerialize","flowParse","flowLinearToGraph","flowSnap","flowEdgePath","flowNodeSize","flowPortPos"]
eq("model: every function of the contract is exported",SPEC_FUNCS.filter((f)=>typeof M[f]!=="function"),[])
eq("model: schema version (2 = the node catalog; the catalog file carries the same number)",[M.FLOW_SCHEMA_VERSION,CAT.schema,M0.FLOW_SCHEMA_VERSION],[2,2,2])
eq("model: limits",[M.FLOW_LIMITS.nodes,M.FLOW_LIMITS.edges,M.FLOW_LIMITS.branches,M.FLOW_LIMITS.conditions,M.FLOW_LIMITS.commands_per_node],[200,400,12,12,20])
// ---- node types mirror the contract
const TYPES=["start","command","script","decision","parse","set","foreach","wait","approval","output","subchain","end","comment"]
const ALL=Object.keys(M.FLOW_NODE_TYPES)
eq("types: without the catalog only the 13 built-in node types exist",Object.keys(M0.FLOW_NODE_TYPES).sort(),TYPES.slice().sort())
eq("types: with the catalog the 13 built-in types come first, then the catalog types (39 in all)",[ALL.slice(0,13),ALL.length,ALL.slice().sort()],[Object.keys(M0.FLOW_NODE_TYPES),39,Object.keys(CAT.types).sort()])
check("types: label, category, icon, color, defaults on each",ALL.every((t)=>{const d=M.FLOW_NODE_TYPES[t];return d.label&&d.category&&d.icon&&d.color&&d.defaults&&typeof d.defaults==="object"}))
const COMPONENTS=fs.readdirSync(path.join(ROOT,"UI","css")).filter((f)=>f.endsWith(".css")).map((f)=>read("UI","css",f)).join("\n")+fs.readdirSync(path.join(ROOT,"UI","css","pages")).filter((f)=>f.endsWith(".css")).map((f)=>read("UI","css","pages",f)).join("\n")
eq("types: every icon is an existing .icon-<name> class",ALL.filter((t)=>COMPONENTS.indexOf(".icon-"+M.FLOW_NODE_TYPES[t].icon+"{")<0||!fs.existsSync(path.join(ROOT,"Assets","icons",M.FLOW_NODE_TYPES[t].icon+".svg"))),[])
const cats=M.FLOW_CATEGORIES.map((c)=>c.id)
eq("types: picker groups in order",M.FLOW_CATEGORIES.map((c)=>c.id+"="+c.label),["input=Triggers & inputs","action=Actions","logic=Logic","math=Calculations & variables","transform=Data transform","analysis=Data analysis","app=App","output=Outputs","notify=Notifications & log","note=Notes"])
eq("types: the groups are the catalog's, and the built-in fallback has the same ids and labels",[M.FLOW_CATEGORIES.map((c)=>[c.id,c.label,c.hint]),M0.FLOW_CATEGORIES.map((c)=>[c.id,c.label])],[CAT.categories.map((c)=>[c.id,c.label,c.hint||""]),CAT.categories.map((c)=>[c.id,c.label])])
check("types: every category is a picker group",ALL.every((t)=>cats.indexOf(M.FLOW_NODE_TYPES[t].category)>=0))
const ports=(type,config)=>M.flowNodePorts({id:"x",type,config:config||M.flowDefaultConfig(type)})
eq("ports: start",ports("start"),{in:false,out:["out"]})
eq("ports: command",ports("command"),{in:true,out:["success","fail"]})
eq("ports: script = branches + error",ports("script",{branches:["alive","down"]}),{in:true,out:["alive","down","error"]})
eq("ports: decision = branch names + else",ports("decision",{branches:[{name:"alive"},{name:"down"}],else:"other"}),{in:true,out:["alive","down","other"]})
eq("ports: decision default else",ports("decision",{branches:[{name:"a"}]}).out,["a","else"])
eq("ports: parse / set / foreach / wait",[ports("parse").out,ports("set").out,ports("foreach").out,ports("wait").out],[["out","nomatch"],["out"],["item","done"],["out"]])
eq("ports: approval / output / subchain",[ports("approval").out,ports("output").out,ports("subchain").out],[["approved","rejected"],["out"],["success","fail"]])
eq("ports: end has none, comment has none and no input",[ports("end"),ports("comment")],[{in:true,out:[]},{in:false,out:[]}])
eq("ports: duplicate dynamic names collapse",ports("script",{branches:["a","a","error"]}).out,["a","error"])
eq("ports: a script with no branch falls back to out",ports("script",{branches:[]}).out,["out","error"])
eq("ports: unknown type",M.flowNodePorts({id:"x",type:"nope"}).out,[])
// ---- new graph, ids, add
let g=M.flowNewGraph()
eq("new graph: one start node, no edges",[g.schema,g.nodes.length,g.nodes[0].type,g.edges.length,g.viewport],[2,1,"start",0,{x:0,y:0,zoom:1}])
eq("new graph: settings",g.settings,{shell:"",run_timeout:1800,max_visits:200,on_error:"stop"})
check("new graph: validates apart from nothing",M.flowValidate(g).ok)
eq("new id: next free number",[M.flowNewId(g,"n"),M.flowNewId(g,"e")],["n2","e1"])
eq("new id: skips ids taken by either list",M.flowNewId({nodes:[{id:"n1"},{id:"n7"}],edges:[{id:"n8"}]},"n"),"n9")
const cmd=M.flowAddNode(g,"command",300,160,{commands:[{text:"ping -c 2 {IPv4}"}]})
eq("add: node shape",[cmd.id,cmd.type,cmd.title,cmd.x,cmd.y,cmd.config.mode,cmd.config.commands[0].text],["n2","command","Command",300,160,"sequence","ping -c 2 {IPv4}"])
eq("types: a script node has no network access by default",M.FLOW_NODE_TYPES.script.defaults.network,false)
check("add: defaults are copies, not shared",M.flowAddNode(M.flowNewGraph(),"command",0,0).config.commands!==M.FLOW_NODE_TYPES.command.defaults.commands)
eq("add: unknown type refused",M.flowAddNode(g,"nope",0,0),null)
eq("add: a second start refused",[M.flowAddNode(g,"start",0,0),g.nodes.length],[null,2])
const dec=M.flowAddNode(g,"decision",600,160,{branches:[{name:"alive",match:"all",conditions:[{source:"host_up",op:"is_true"}]}],else:"down"})
const end=M.flowAddNode(g,"end",900,160)
const note=M.flowAddNode(g,"comment",40,400,{text:"hello"})
eq("add: ids are unique and sequential",g.nodes.map((n)=>n.id),["n1","n2","n3","n4","n5"])
{const big=M.flowNewGraph();for(let i=0;i<300;i++)M.flowAddNode(big,"wait",i*10,0);eq("add: stops at the node limit",big.nodes.length,200)}
// ---- connect and its refusal rules
const e1=M.flowConnect(g,"n1","out",cmd.id)
eq("connect: edge shape",e1,{id:"e1",from:"n1",port:"out",to:"n2"})
const e2=M.flowConnect(g,cmd.id,"success",dec.id)
const e3=M.flowConnect(g,dec.id,"alive",end.id)
check("connect: three edges",!!e2&&!!e3&&g.edges.length===3)
eq("connect: duplicate refused",M.flowConnect(g,"n1","out",cmd.id),null)
eq("connect: self loop refused",M.flowConnect(g,cmd.id,"success",cmd.id),null)
eq("connect: into start refused",M.flowConnect(g,cmd.id,"fail","n1"),null)
eq("connect: into a comment refused",M.flowConnect(g,cmd.id,"fail",note.id),null)
eq("connect: from a comment refused",M.flowConnect(g,note.id,"out",end.id),null)
eq("connect: unknown port refused",M.flowConnect(g,cmd.id,"nope",end.id),null)
eq("connect: unknown node refused",[M.flowConnect(g,"zz","out",end.id),M.flowConnect(g,cmd.id,"fail","zz")],[null,null])
eq("connect: nothing was added by the refusals",g.edges.length,3)
check("connect: refusal text for the UI",M.flowConnectRefusal(g,cmd.id,"success",cmd.id)!==""&&M.flowConnectRefusal(g,cmd.id,"fail",end.id)==="")
check("connect: several edges may leave one port",!!M.flowConnect(g,cmd.id,"success",end.id))
check("connect: cycles are legal",!!M.flowConnect(g,dec.id,"down",cmd.id))
{const big=M.flowNewGraph();const a=M.flowAddNode(big,"command",0,0);for(let i=0;i<198;i++)M.flowAddNode(big,"wait",0,0);let made=0;big.nodes.forEach((n)=>{if(n.type==="wait"){if(M.flowConnect(big,a.id,"success",n.id))made++;if(M.flowConnect(big,a.id,"fail",n.id))made++}});big.nodes.filter((n)=>n.type==="wait").slice(0,10).forEach((n)=>{if(M.flowConnect(big,"n1","out",n.id))made++});eq("connect: stops at the edge limit",[made,big.edges.length],[400,400])}
// ---- move and snap
eq("snap: rounds to the grid",[M.flowSnap(29,20),M.flowSnap(30,20),M.flowSnap(-11,20),M.flowSnap(7,0),M.flowSnap(-4,20)],[20,40,-20,7,0])
M.flowMoveNodes(g,[cmd.id,dec.id],15,-5)
eq("move: both nodes moved by the delta",[cmd.x,cmd.y,dec.x,dec.y],[315,155,615,155])
M.flowMoveNodes(g,[cmd.id,dec.id],3,3,20)
eq("move: snap puts the first node on the grid and keeps offsets",[cmd.x,cmd.y,dec.x-cmd.x,dec.y-cmd.y],[320,160,300,0])
eq("move: unknown ids move nothing",M.flowMoveNodes(g,["zz"],5,5),0)
// ---- delete
{const d=M.flowClone(g);const n=M.flowRemoveNodes(d,[cmd.id]);eq("delete node: node and its edges go",[n,d.nodes.some((x)=>x.id===cmd.id),d.edges.map((e)=>e.id)],[1,false,["e3"]])}
{const d=M.flowClone(g);eq("delete edge: only that edge",[M.flowRemoveEdges(d,["e2","zz"]),d.edges.length,d.nodes.length],[1,4,5])}
check("clone: deep copy",M.flowClone(g)!==g&&M.flowClone(g).nodes[1].config!==g.nodes[1].config&&JSON.stringify(M.flowClone(g))===JSON.stringify(g))
// ---- port rename / prune
{const d=M.flowClone(g)
eq("rename: decision branch renamed in config and on edges",[M.flowRenamePort(d,dec.id,"alive","up"),M.flowFindNode(d,dec.id).config.branches[0].name,d.edges.filter((e)=>e.from===dec.id).map((e)=>e.port).sort()],[true,"up",["down","up"]])
eq("rename: the else port",[M.flowRenamePort(d,dec.id,"down","dead"),M.flowFindNode(d,dec.id).config.else,d.edges.filter((e)=>e.from===dec.id).map((e)=>e.port).sort()],[true,"dead",["dead","up"]])
eq("rename: onto an existing port refused",[M.flowRenamePort(d,dec.id,"up","dead"),M.flowFindNode(d,dec.id).config.branches[0].name],[false,"up"])
eq("rename: bad name refused",[M.flowRenamePort(d,dec.id,"up","has space"),M.flowRenamePort(d,dec.id,"up",""),M.flowRenamePort(d,dec.id,"up","x".repeat(25))],[false,false,false])
eq("rename: fixed ports cannot be renamed",M.flowRenamePort(d,cmd.id,"success","ok"),false)
const s=M.flowAddNode(d,"script",0,600,{branches:["a","b"],code:"print(1)"});M.flowConnect(d,s.id,"a",end.id);M.flowConnect(d,s.id,"b",end.id);M.flowConnect(d,s.id,"error",end.id)
eq("rename: script branch",[M.flowRenamePort(d,s.id,"a","first"),s.config.branches,d.edges.filter((e)=>e.from===s.id).map((e)=>e.port)],[true,["first","b"],["first","b","error"]])
s.config.branches=["first"]
eq("prune: edges of a removed port are dropped, and returned",[M.flowPruneEdges(d).map((e)=>e.port),d.edges.filter((e)=>e.from===s.id).map((e)=>e.port)],[["b"],["first","error"]])
eq("prune: nothing to do the second time",M.flowPruneEdges(d).length,0)
// the inspector edits the config directly, then the editor reconciles
const before=M.flowNodePorts(s).out;s.config.branches=["one"];M.flowReconcilePorts(d,s.id,before)
eq("reconcile: a single in-place rename keeps its edges",d.edges.filter((e)=>e.from===s.id).map((e)=>e.port),["one","error"])
const before2=M.flowNodePorts(s).out;s.config.branches=["x","y"];M.flowReconcilePorts(d,s.id,before2)
eq("reconcile: anything else prunes",d.edges.filter((e)=>e.from===s.id).map((e)=>e.port),["error"])
}
// ---- geometry
{const n={id:"a",type:"command",x:100,y:50,config:{}},size=M.flowNodeSize(n)
eq("geometry: node size",size,{w:M.FLOW_GEOM.w,h:M.FLOW_GEOM.head+M.FLOW_GEOM.sum+2*M.FLOW_GEOM.row+M.FLOW_GEOM.pad})
const pin=M.flowPortPos(n,"in"),p0=M.flowPortPos(n,"out","success"),p1=M.flowPortPos(n,"out","fail")
eq("geometry: input on the left edge, outputs on the right edge",[pin.x,p0.x,p1.x],[100,100+size.w,100+size.w])
check("geometry: output ports are stacked top to bottom inside the box",p0.y<p1.y&&p0.y>50&&p1.y<50+size.h)
eq("geometry: the first output sits level with the input (straight chains draw straight)",pin.y,p0.y)
eq("geometry: unknown port falls back to the first row",M.flowPortPos(n,"out","nope"),p0)
eq("geometry: comment size comes from its config, clamped",[M.flowNodeSize({type:"comment",config:{w:300,h:90}}),M.flowNodeSize({type:"comment",config:{w:5,h:99999}})],[{w:300,h:90},{w:M.FLOW_GEOM.commentMinW,h:M.FLOW_GEOM.commentMaxH}])
const d=M.flowEdgePath(0,0,200,100)
check("edge path: a cubic bezier that leaves and arrives horizontally",/^M0,0 C(\d+(\.\d+)?),0 (-?\d+(\.\d+)?),100 200,100$/.test(d),d)
const ends=(d)=>{const n=d.match(/-?\d+(\.\d+)?/g).map(Number);return {c1x:n[2],c1y:n[3],c2x:n[n.length-4],c2y:n[n.length-3],x2:n[n.length-2],y2:n[n.length-1]}}
const back=ends(M.flowEdgePath(300,0,0,50)),far=ends(M.flowEdgePath(300,0,0,400))
check("edge path: a backward edge still leaves to the right and arrives from the left",back.c1x>300&&back.c1y===0&&back.c2x<0&&back.c2y===50&&back.x2===0&&back.y2===50&&far.c1x>300&&far.c1y===0&&far.c2x<0&&far.c2y===400)
check("edge path: a backward edge on the same row loops underneath",/ L/.test(M.flowEdgePath(300,0,0,50))&&!/ L/.test(M.flowEdgePath(300,0,0,400))&&!/ L/.test(M.flowEdgePath(0,0,300,50)))
check("edge path: only finite numbers",[[0,0,0,0],[5,5,-5,5],[1e4,-1e4,-1e4,1e4]].every((a)=>!/NaN|Infinity/.test(M.flowEdgePath.apply(null,a))))
eq("bounds",M.flowGraphBounds({nodes:[{type:"wait",x:10,y:20,config:{}},{type:"comment",x:400,y:-30,config:{w:200,h:100}}]}),{x:10,y:-30,w:590,h:50+M.flowNodeSize({type:"wait"}).h})
eq("bounds: empty graph",M.flowGraphBounds({nodes:[]}),null)
const hg={nodes:[{id:"c",type:"comment",x:0,y:0,config:{w:400,h:300}},{id:"a",type:"wait",x:20,y:20,config:{}},{id:"c2",type:"comment",x:10,y:10,config:{w:400,h:300}}]}
eq("hit test: nodes win over sticky notes, later notes over earlier, miss is null",[M.flowHitNode(hg,30,30).id,M.flowHitNode(hg,390,290).id,M.flowHitNode(hg,5,5).id,M.flowHitNode(hg,900,900)],["a","c2","c",null])
eq("port tone",[M.flowPortTone("fail"),M.flowPortTone("error"),M.flowPortTone("success"),M.flowPortTone("alive")],["neg","neg","pos",""])
}
// ---- summaries
{const sum=(type,config)=>M.flowNodeSummary({type,config})
eq("summary: command shows the first command",[sum("command",{commands:[{text:"nmap -sV {IPv4}"}]}),sum("command",{commands:[{text:"a"},{text:"b"},{text:"c"}]}),sum("command",{commands:[]})],["nmap -sV {IPv4}","a  (+2 more)","No command yet"])
eq("summary: script",[sum("script",{language:"python",code:"a\nb\n"}),sum("script",{language:"bash",code:""})],["python script, 2 lines","bash script (empty)"])
eq("summary: decision counts rules",[sum("decision",{branches:[{name:"a",conditions:[{},{}]},{name:"b",conditions:[{}]}]}),sum("decision",{branches:[{name:"a",conditions:[{}]}]})],["3 rules in 2 branches","1 rule"])
eq("summary: others",[sum("wait",{seconds:5}),sum("end",{status:"fail"}),sum("parse",{mode:"tool",tool:"nmap"}),sum("set",{assign:[{var:"ip",value:"1.2.3.4"}]}),sum("start",{trigger:"caller"}),sum("subchain",{playbook_id:null})],["5 seconds","Ends as fail","nmap output","ip = 1.2.3.4","Runs from /caller","No chain picked"])
check("summary: every type gives a string",ALL.every((t)=>typeof sum(t,M.flowDefaultConfig(t))==="string"))
}
// ---- validation codes
const codes=(r,list)=>(list||r.errors).map((i)=>i.code)
{eq("validate: not a graph",codes(M.flowValidate(null)),["structure"])
eq("validate: nodes must be a list",codes(M.flowValidate({nodes:{},edges:[]})),["structure"])
const ok=M.flowLinearToGraph("x",[{command:"id"},{command:"whoami"}]);const r=M.flowValidate(ok)
eq("validate: a linear chain is fine; only the open fail ports warn",[r.ok,r.errors,codes(r,r.warnings)],[true,[],["port_unconnected","port_unconnected"]])
check("validate: issue shape {node,edge,code,message}",r.warnings.every((i)=>"node" in i&&"edge" in i&&typeof i.code==="string"&&typeof i.message==="string"&&i.message.length>0))
const mk=()=>M.flowClone(ok)
let v=mk();v.nodes=v.nodes.filter((n)=>n.type!=="start");v.edges=v.edges.filter((e)=>e.from!=="n1");check("validate: no_start",codes(M.flowValidate(v)).indexOf("no_start")>=0)
v=mk();v.nodes.push({id:"s2",type:"start",title:"Start",x:0,y:0,config:{}});eq("validate: many_start on each start",codes(M.flowValidate(v)).filter((c)=>c==="many_start").length,2)
v=mk();v.nodes.push({id:"q",type:"teleport",x:0,y:0,config:{}});check("validate: unknown_type",codes(M.flowValidate(v)).indexOf("unknown_type")>=0)
v=mk();v.nodes[1].id="bad id!";check("validate: bad_id (and its edges dangle)",codes(M.flowValidate(v)).indexOf("bad_id")>=0&&codes(M.flowValidate(v)).indexOf("dangling_edge")>=0)
v=mk();v.nodes[2].id=v.nodes[1].id;check("validate: duplicate_id",codes(M.flowValidate(v)).indexOf("duplicate_id")>=0)
v=mk();v.edges.push({id:"e9",from:"n2",port:"success",to:"ghost"});{const i=M.flowValidate(v).errors.find((x)=>x.code==="dangling_edge");eq("validate: dangling_edge names the edge",[!!i,i&&i.edge],[true,"e9"])}
v=mk();v.edges[1].port="nope";check("validate: unknown_port",codes(M.flowValidate(v)).indexOf("unknown_port")>=0)
v=mk();v.edges.push({id:"e9",from:"n3",port:"success",to:"n1"});check("validate: bad_edge_target (edge into start)",codes(M.flowValidate(v)).indexOf("bad_edge_target")>=0)
v=mk();v.edges.push({id:"e9",from:"n3",port:"success",to:"n3"});check("validate: self_loop",codes(M.flowValidate(v)).indexOf("self_loop")>=0)
v=mk();v.schema=3;check("validate: schema_version (a newer schema is refused)",codes(M.flowValidate(v)).indexOf("schema_version")>=0)
eq("validate: schema 2, schema 1 and no schema are all accepted",[2,1,undefined].map((sv)=>{const x=mk();x.schema=sv;return codes(M.flowValidate(x)).indexOf("schema_version")}),[-1,-1,-1])
v=mk();v.edges.push({id:"e9",from:"n2",port:"success",to:"n3"});check("validate: duplicate_edge is a warning",M.flowValidate(v).ok&&codes(null,M.flowValidate(v).warnings).indexOf("duplicate_edge")>=0)
v=mk();v.nodes[1].config.commands=[{text:"   "}];{const i=M.flowValidate(v).errors.find((x)=>x.code==="empty_command");eq("validate: empty_command names the node",[!!i,i&&i.node],[true,"n2"])}
v=mk();v.nodes[1].config.commands=[{text:"x".repeat(5000)}];check("validate: command_too_long",codes(M.flowValidate(v)).indexOf("command_too_long")>=0)
v=mk();v.nodes[1].config.commands=Array.from({length:21},()=>({text:"id"}));check("validate: too_many_commands",codes(M.flowValidate(v)).indexOf("too_many_commands")>=0)
v=mk();v.nodes[1].config.commands=[{text:"echo ${raw:name}"}];check("validate: raw_in_command warning",codes(null,M.flowValidate(v).warnings).indexOf("raw_in_command")>=0&&M.flowValidate(v).ok)
v=mk();M.flowAddNode(v,"wait",0,0);{const r2=M.flowValidate(v);check("validate: unreachable is a warning",r2.ok&&r2.warnings.some((i)=>i.code==="unreachable"&&i.node==="n4"))}
v=mk();M.flowAddNode(v,"comment",0,0);check("validate: a sticky note is never unreachable",!M.flowValidate(v).warnings.some((i)=>i.code==="unreachable"))
v=mk();M.flowAddNode(v,"script",0,0,{code:""});check("validate: empty_script",codes(M.flowValidate(v)).indexOf("empty_script")>=0)
v=mk();M.flowAddNode(v,"script",0,0,{code:"x",branches:["a b"]});check("validate: bad_port_name",codes(M.flowValidate(v)).indexOf("bad_port_name")>=0)
v=mk();M.flowAddNode(v,"script",0,0,{code:"x",branches:["a","a"]});check("validate: duplicate_port",codes(M.flowValidate(v)).indexOf("duplicate_port")>=0)
v=mk();M.flowAddNode(v,"script",0,0,{code:"x",branches:["error"]});check("validate: a branch named like the error port is a duplicate",codes(M.flowValidate(v)).indexOf("duplicate_port")>=0)
v=mk();M.flowAddNode(v,"decision",0,0,{branches:[]});check("validate: empty_decision",codes(M.flowValidate(v)).indexOf("empty_decision")>=0)
v=mk();M.flowAddNode(v,"decision",0,0,{branches:[{name:"a",match:"all",conditions:[]}]});check("validate: empty_branch (a branch with no rule)",codes(M.flowValidate(v)).indexOf("empty_branch")>=0)
v=mk();M.flowAddNode(v,"decision",0,0,{branches:Array.from({length:13},(_,i)=>({name:"b"+i,match:"all",conditions:[{source:"exit_code",op:"eq",value:"0"}]}))});check("validate: too_many_branches",codes(M.flowValidate(v)).indexOf("too_many_branches")>=0)
v=mk();M.flowAddNode(v,"decision",0,0,{branches:[{name:"a",match:"all",conditions:Array.from({length:13},()=>({source:"exit_code",op:"eq",value:"0"}))}]});check("validate: too_many_conditions",codes(M.flowValidate(v)).indexOf("too_many_conditions")>=0)
v=mk();M.flowAddNode(v,"decision",0,0,{branches:[{name:"a",match:"all",conditions:[{source:"output",op:"regex",value:"x".repeat(501)}]}]});check("validate: invalid_regex (too long)",codes(M.flowValidate(v)).indexOf("invalid_regex")>=0)
v=mk();M.flowAddNode(v,"parse",0,0);check("validate: invalid_regex (empty parse pattern)",codes(M.flowValidate(v)).indexOf("invalid_regex")>=0)
v=mk();M.flowAddNode(v,"subchain",0,0);M.flowAddNode(v,"foreach",0,0);M.flowAddNode(v,"script",0,0,{code:"x",language:"ruby"});M.flowAddNode(v,"script",0,0,{code:"x".repeat(70000)});eq("validate: subchain_unset, empty_items, bad_config, script_too_large",["subchain_unset","empty_items","bad_config","script_too_large"].filter((c)=>codes(M.flowValidate(v)).indexOf(c)<0),[])
v=mk();const dn=M.flowAddNode(v,"decision",0,0,{branches:[{name:"a",match:"all",conditions:[{source:"host_up",op:"is_true"}]}],else:"other"});M.flowConnect(v,"n3","success",dn.id);M.flowConnect(v,dn.id,"a","n2");{const r3=M.flowValidate(v);check("validate: open else port warns, open ordinary branch does not",r3.ok&&r3.warnings.some((i)=>i.code==="port_unconnected"&&i.node===dn.id&&/other/.test(i.message))&&r3.warnings.filter((i)=>i.node===dn.id).length===1)}
const many={schema:1,settings:{},nodes:[{id:"n1",type:"start",x:0,y:0,config:{}}],edges:[]};for(let i=0;i<205;i++)many.nodes.push({id:"w"+i,type:"wait",x:0,y:0,config:{seconds:1}});check("validate: too_many_nodes",codes(M.flowValidate(many)).indexOf("too_many_nodes")>=0)
check("validate: never throws on junk",[undefined,1,"x",[],{nodes:[null,1,{}],edges:[null,{from:1}]},{nodes:[{id:"a",type:"command"}],edges:[{id:"e",from:"a",to:"a"}]}].every((j)=>{try{return typeof M.flowValidate(j).ok==="boolean"}catch(e){return false}}))
}
// ---- history
{const h=M.flowHistoryCreate(100),a=M.flowNewGraph()
eq("history: empty",[h.canUndo(),h.canRedo(),h.undo(),h.redo()],[false,false,null,null])
h.reset(a)
eq("history: after reset nothing to undo",[h.canUndo(),h.canRedo()],[false,false])
const b=M.flowClone(a);M.flowAddNode(b,"wait",100,0);h.push(b)
const c=M.flowClone(b);M.flowAddNode(c,"end",200,0);h.push(c)
eq("history: two steps",[h.canUndo(),h.canRedo(),h.size()],[true,false,3])
eq("history: pushing an identical graph adds no step",[h.push(M.flowClone(c)),h.size()],[false,3])
{const moved=M.flowClone(c);moved.viewport={x:500,y:500,zoom:2};eq("history: a view change alone is not a step",h.push(moved),false)}
eq("history: undo returns the earlier graphs",[h.undo().nodes.length,h.undo().nodes.length,h.undo()],[2,1,null])
eq("history: redo walks forward again",[h.canRedo(),h.redo().nodes.length,h.redo().nodes.length,h.redo(),h.canRedo()],[true,2,3,null,false])
h.undo();const d=M.flowClone(b);M.flowAddNode(d,"comment",0,0);h.push(d)
eq("history: a new edit after undo drops the redo branch",[h.canRedo(),h.size(),h.undo().nodes.length,h.redo().nodes.map((n)=>n.type)],[false,3,2,["start","wait","comment"]])
const got=h.undo();got.nodes[0].title="mutated";eq("history: snapshots are copies",h.redo()&&h.undo().nodes[0].title,"Start")
const small=M.flowHistoryCreate(3);small.reset(a);for(let i=0;i<10;i++){const x=M.flowClone(a);x.nodes[0].x=i+1;small.push(x)}
eq("history: the limit keeps the newest entries",[small.size(),small.undo().nodes[0].x,small.undo().nodes[0].x,small.undo()],[3,9,8,null])
const co=M.flowHistoryCreate(10);co.reset(a);const t1=M.flowClone(a);t1.nodes[0].title="S";co.push(t1);const t2=M.flowClone(a);t2.nodes[0].title="St";co.replace(t2)
eq("history: replace coalesces into one step",[co.size(),co.undo().nodes[0].title,co.redo().nodes[0].title],[2,"Start","St"])
{const hv=M.flowHistoryCreate(5);hv.reset(a);const a2=M.flowClone(a);a2.nodes[0].x=99;hv.push(a2);check("history: no viewport in a snapshot",!("viewport" in hv.undo()))}
}
// ---- copy / paste
{const src=M.flowClone(g)
const clip=M.flowCopy(src,[cmd.id,dec.id,"n1"])
eq("copy: the nodes and only the edges between them",[clip.nodes.map((n)=>n.id).sort(),clip.edges.map((e)=>e.from+">"+e.to).sort()],[["n1","n2","n3"],["n1>n2","n2>n3","n3>n2"]])
clip.nodes[1].config.commands[0].text="changed";check("copy: the clip is a deep copy",M.flowFindNode(src,cmd.id).config.commands[0].text==="ping -c 2 {IPv4}")
const nodesBefore=src.nodes.length,edgesBefore=src.edges.length
const made=M.flowPaste(src,clip,40,40)
eq("paste: the start is skipped when the graph has one",[made.length,src.nodes.length-nodesBefore],[2,2])
check("paste: fresh unique ids",made.every((id)=>["n1","n2","n3","n4","n5"].indexOf(id)<0)&&new Set(src.nodes.map((n)=>n.id)).size===src.nodes.length)
const pc=M.flowFindNode(src,made[0]),pd=M.flowFindNode(src,made[1])
eq("paste: offset positions",[pc.x-cmd.x,pc.y-cmd.y,pd.x-dec.x],[40,40,40])
const fresh=src.edges.slice(edgesBefore)
eq("paste: internal edges are remapped onto the new nodes",fresh.map((e)=>[e.from,e.port,e.to]),[[made[0],"success",made[1]],[made[1],"down",made[0]]])
check("paste: edge ids are fresh and unique",new Set(src.edges.map((e)=>e.id)).size===src.edges.length)
check("paste: the originals keep their edges",src.edges.slice(0,edgesBefore).every((e,i)=>e.id===g.edges[i].id&&e.from===g.edges[i].from&&e.to===g.edges[i].to))
const empty={schema:1,settings:{},nodes:[],edges:[]};eq("paste: a start is kept when the graph has none",M.flowPaste(empty,clip,0,0).length,3)
eq("paste: junk clip",[M.flowPaste(src,null,0,0),M.flowPaste(src,{},0,0)],[[],[]])
check("paste: twice gives two independent copies",(()=>{const a=M.flowPaste(src,clip,80,80);return a.length===2&&a.every((id)=>made.indexOf(id)<0)})())
}
// ---- auto layout
function rects(graph){return graph.nodes.map((n)=>Object.assign({id:n.id,type:n.type,x:n.x,y:n.y},M.flowNodeSize(n)))}
function overlaps(graph){const r=rects(graph).filter((n)=>n.type!=="comment");let bad=0;for(let i=0;i<r.length;i++)for(let j=i+1;j<r.length;j++){const a=r[i],b=r[j];if(a.x<b.x+b.w&&b.x<a.x+a.w&&a.y<b.y+b.h&&b.y<a.y+a.h)bad++}return bad}
function leftToRight(graph){return graph.edges.every((e)=>{const a=M.flowFindNode(graph,e.from),b=M.flowFindNode(graph,e.to);return a.x+M.flowNodeSize(a).w<b.x})}
function startLeftmost(graph){const s=graph.nodes.find((n)=>n.type==="start");return graph.nodes.filter((n)=>n.type!=="comment"&&n!==s).every((n)=>n.x>s.x)}
{// a branching DAG, all dumped on one spot
const d=M.flowNewGraph();d.nodes[0].x=500;d.nodes[0].y=500
const ping=M.flowAddNode(d,"command",500,500,{commands:[{text:"ping"}]}),alive=M.flowAddNode(d,"decision",500,500,{branches:[{name:"alive",conditions:[{}]}],else:"down"})
const nmap=M.flowAddNode(d,"command",500,500),parse=M.flowAddNode(d,"parse",500,500),web=M.flowAddNode(d,"command",500,500),notify=M.flowAddNode(d,"output",500,500),fin=M.flowAddNode(d,"end",500,500)
const sticky=M.flowAddNode(d,"comment",-321,777,{text:"keep me"})
M.flowConnect(d,"n1","out",ping.id);M.flowConnect(d,ping.id,"success",alive.id);M.flowConnect(d,ping.id,"fail",notify.id);M.flowConnect(d,alive.id,"alive",nmap.id);M.flowConnect(d,alive.id,"down",notify.id)
M.flowConnect(d,nmap.id,"success",parse.id);M.flowConnect(d,parse.id,"out",web.id);M.flowConnect(d,web.id,"success",fin.id);M.flowConnect(d,notify.id,"out",fin.id);M.flowConnect(d,nmap.id,"fail",fin.id)
const ret=M.flowAutoLayout(d)
check("layout: returns the same graph",ret===d)
check("layout: every edge of a DAG goes left to right",leftToRight(d))
eq("layout: no two nodes overlap",overlaps(d),0)
check("layout: the start is leftmost",startLeftmost(d))
eq("layout: sticky notes are untouched",[sticky.x,sticky.y],[-321,777])
check("layout: column = longest path from the start",fin.x>web.x&&web.x>parse.x&&parse.x>nmap.x&&nmap.x>alive.x&&alive.x>ping.x&&notify.x>alive.x)
check("layout: positions are on the grid",d.nodes.filter((n)=>n.type!=="comment").every((n)=>n.x%20===0&&n.y%20===0))
check("layout: the success path sits above the fail path",nmap.y<=notify.y)
const again=JSON.stringify(d);M.flowAutoLayout(d);eq("layout: stable when run twice",JSON.stringify(d),again)
const custom=M.flowAutoLayout(M.flowClone(d),{gapX:200,gapY:60,grid:10,originX:100,originY:100});check("layout: options",custom.nodes[0].x===100&&Math.min(...custom.nodes.filter((n)=>n.type!=="comment").map((n)=>n.y))===100&&leftToRight(custom)&&overlaps(custom)===0)
}
{// a straight chain lays out on one row
const d=M.flowLinearToGraph("x",[{command:"a"},{command:"b"},{command:"c"}]);d.nodes.forEach((n)=>{n.x=0;n.y=0});M.flowAutoLayout(d)
check("layout: a straight chain is one straight row",leftToRight(d)&&d.edges.every((e)=>M.flowPortPos(M.flowFindNode(d,e.from),"out",e.port).y===M.flowPortPos(M.flowFindNode(d,e.to),"in").y))
}
{// a cycle, a detached node and an empty graph do not break it
const d=M.flowNewGraph();const a=M.flowAddNode(d,"command",0,0),b=M.flowAddNode(d,"command",0,0),lone=M.flowAddNode(d,"wait",0,0)
M.flowConnect(d,"n1","out",a.id);M.flowConnect(d,a.id,"success",b.id);M.flowConnect(d,b.id,"fail",a.id)
M.flowAutoLayout(d)
check("layout: with a cycle the forward edges still go left to right",d.nodes[0].x<a.x&&a.x<b.x&&overlaps(d)===0&&startLeftmost(d))
check("layout: finite numbers everywhere",d.nodes.every((n)=>Number.isFinite(n.x)&&Number.isFinite(n.y)))
eq("layout: empty graph / comments only",[M.flowAutoLayout({nodes:[],edges:[]}).nodes.length,M.flowAutoLayout({nodes:[{id:"c",type:"comment",x:5,y:6,config:{}}],edges:[]}).nodes[0].x],[0,5])
}
{// random DAGs: the three properties always hold
let seed=7;const rnd=()=>{seed=(seed*1103515245+12345)&0x7fffffff;return seed/0x7fffffff}
let bad=0
for(let round=0;round<25;round++){
const d=M.flowNewGraph(),ids=["n1"],n=5+Math.floor(rnd()*40)
for(let i=0;i<n;i++){const node=M.flowAddNode(d,rnd()<0.5?"command":"foreach",rnd()*900,rnd()*900);const from=ids[Math.floor(rnd()*ids.length)];const fp=M.flowNodePorts(M.flowFindNode(d,from)).out;M.flowConnect(d,from,fp[Math.floor(rnd()*fp.length)],node.id);if(rnd()<0.4){const f2=ids[Math.floor(rnd()*ids.length)],p2=M.flowNodePorts(M.flowFindNode(d,f2)).out;M.flowConnect(d,f2,p2[Math.floor(rnd()*p2.length)],node.id)}ids.push(node.id)}
M.flowAutoLayout(d)
if(!leftToRight(d)||overlaps(d)!==0||!startLeftmost(d))bad++
}
eq("layout: 25 random DAGs keep left-to-right, no overlap, start leftmost",bad,0)
const big=M.flowNewGraph();let prev="n1",port="out";for(let i=0;i<199;i++){const node=M.flowAddNode(big,"command",0,0);M.flowConnect(big,prev,port,node.id);if(i%3===0){prev=node.id;port="success"}}
const t0=Date.now();M.flowAutoLayout(big);check("layout: 200 nodes in well under a second",Date.now()-t0<1000&&overlaps(big)===0&&leftToRight(big),(Date.now()-t0)+" ms")
}
// ---- serialise / parse
{const text=M.flowSerialize(g)
check("serialise: a JSON string",typeof text==="string"&&JSON.parse(text).schema===2)
const back=M.flowParse(text)
eq("round trip: nodes, edges, settings and viewport survive",[back.nodes,back.edges,back.settings,back.viewport],[g.nodes,g.edges,g.settings,g.viewport])
eq("round trip: stable",M.flowSerialize(back),text)
check("parse: accepts an object as well as text",M.flowParse(JSON.parse(text)).nodes.length===g.nodes.length)
check("parse: accepts an export bundle",M.flowParse(JSON.stringify({loya_chain:1,name:"x",graph:JSON.parse(text)})).nodes.length===g.nodes.length)
throws("parse: bad JSON throws",()=>M.flowParse("{nope"))
throws("parse: not an object throws",()=>M.flowParse("[1,2]"))
throws("parse: no nodes throws",()=>M.flowParse("{\"edges\":[]}"))
throws("parse: node without id throws",()=>M.flowParse("{\"nodes\":[{\"type\":\"wait\"}]}"))
throws("parse: a newer schema throws",()=>M.flowParse("{\"schema\":3,\"nodes\":[]}"))
eq("parse: schema 2 and schema 1 are both read, and come back as schema 2",[M.flowParse("{\"schema\":2,\"nodes\":[]}").schema,M.flowParse("{\"schema\":1,\"nodes\":[]}").schema,M.flowParse("{\"nodes\":[]}").schema],[2,2,2])
throws("parse: null throws",()=>M.flowParse(null))
const loose=M.flowParse("{\"nodes\":[{\"id\":\"a\",\"type\":\"wait\",\"x\":\"12\",\"y\":null},{\"id\":\"b\",\"type\":\"command\",\"title\":\""+"T".repeat(200)+"\"}],\"edges\":[{\"from\":\"a\",\"port\":\"out\",\"to\":\"b\"}],\"settings\":{\"run_timeout\":1,\"max_visits\":99999,\"on_error\":\"explode\"},\"viewport\":{\"zoom\":50}}")
eq("parse: fills defaults and clamps",[loose.schema,loose.nodes[0].x,loose.nodes[0].y,loose.nodes[0].title,loose.nodes[0].config.seconds,loose.nodes[1].title.length,loose.nodes[1].config.mode,loose.edges[0].id,loose.settings.run_timeout,loose.settings.max_visits,loose.settings.on_error,loose.viewport.zoom],[2,12,0,"Wait",5,80,"sequence","e1",10,2000,"stop",2])
check("parse: unknown node types are kept for the validator",M.flowParse("{\"nodes\":[{\"id\":\"a\",\"type\":\"future\"}]}").nodes[0].type==="future")
const input={nodes:[{id:"a",type:"wait",config:{seconds:9}}],edges:[]};M.flowParse(input).nodes[0].config.seconds=1;eq("parse: does not mutate its input",input.nodes[0].config.seconds,9)
}
// ---- linear chain -> graph
{const lin=M.flowLinearToGraph("Recon",[{command_id:7,command_src:"db",label:"Ping",command:"ping -c 2 {IPv4}"},{command_id:null,command_src:"",label:"",command:"nmap -sV {IPv4}"},{command:"x".repeat(200)}])
eq("linear: start then one command node per step",lin.nodes.map((n)=>n.type),["start","command","command","command"])
eq("linear: joined on out, then success",lin.edges.map((e)=>[e.from,e.port,e.to]),[["n1","out","n2"],["n2","success","n3"],["n3","success","n4"]])
eq("linear: the command, its library id and source are kept",lin.nodes[1].config.commands,[{text:"ping -c 2 {IPv4}",command_id:7,src:"db",label:"Ping"}])
eq("linear: titles from the label or the command, capped",[lin.nodes[1].title,lin.nodes[2].title,lin.nodes[3].title.length],["Ping","nmap -sV {IPv4}",80])
check("linear: laid out left to right on one row",leftToRight(lin)&&overlaps(lin)===0&&new Set(lin.nodes.map((n)=>n.y)).size===1)
check("linear: validates",M.flowValidate(lin).ok)
check("linear: recognised as linear",M.flowGraphIsLinear(lin)&&M.flowGraphIsLinear(M.flowNewGraph()))
const br=M.flowClone(lin);M.flowConnect(br,"n2","fail","n4");check("linear: a branch is not linear",!M.flowGraphIsLinear(br)&&!M.flowGraphIsLinear(g))
eq("linear: no steps -> just the start",[M.flowLinearToGraph("x",[]).nodes.length,M.flowLinearToGraph("x",null).edges.length],[1,0])
}
// ---- node catalog (flow-catalog.js, generated from Cores/Services/flow_nodes.py) and the model table built from it
{const CT=CAT.types,same=(a,b)=>JSON.stringify(a)===JSON.stringify(b)
eq("catalog: every catalog type is a model type with the same ports",Object.keys(CT).filter((k)=>!M.FLOW_NODE_TYPES[k]||!same(M.FLOW_NODE_TYPES[k].ports,CT[k].ports)),[])
eq("catalog: ... the same defaults",Object.keys(CT).filter((k)=>!same(M.FLOW_NODE_TYPES[k].defaults,CT[k].defaults)||!same(M.flowDefaultConfig(k),CT[k].defaults)),[])
eq("catalog: ... the same label, category, colour, icon and input flag",Object.keys(CT).filter((k)=>{const a=M.FLOW_NODE_TYPES[k],c=CT[k];return a.label!==c.label||a.category!==c.category||a.color!==c.color||a.icon!==c.icon||!!a.input!==(c.input!==false)}),[])
eq("catalog: the built-in table of the model (used when the catalog is missing) agrees with the catalog",TYPES.filter((k)=>{const a=M0.FLOW_NODE_TYPES[k],c=CT[k];return !c||!same(a.ports,c.ports)||!same(a.defaults,c.defaults)||a.label!==c.label||a.category!==c.category||a.color!==c.color||a.icon!==c.icon||!!a.input!==(c.input!==false)}),[])
eq("catalog: typed fields, dynamic ports, tones and the fail port of the new types are carried over",Object.keys(CT).filter((k)=>TYPES.indexOf(k)<0).filter((k)=>{const a=M.FLOW_NODE_TYPES[k],c=CT[k];return !same(a.fields,c.fields||[])||!same(a.dynamic,c.dynamic||null)||!same(a.tones,c.tones||{})||a.fail_port!==(c.fail_port||"")||a.summary!==(c.summary||"")}),[])
check("catalog: defaults handed out are copies",M.flowDefaultConfig("switch")!==CT.switch.defaults&&M.flowDefaultConfig("switch").cases!==CT.switch.defaults.cases)
eq("catalog: every type's category is a listed category, every fixed port name is valid and unique",Object.keys(CT).filter((k)=>cats.indexOf(CT[k].category)<0||(Array.isArray(CT[k].ports)&&(CT[k].ports.some((p)=>!M.FLOW_PORT_RE.test(p))||new Set(CT[k].ports).size!==CT[k].ports.length))),[])
eq("catalog: tones and fail ports name real ports, with known tones",Object.keys(CT).filter((k)=>{const c=CT[k],fixed=(Array.isArray(c.ports)?c.ports:[]).concat(c.dynamic&&c.dynamic.fixed_key?[c.defaults[c.dynamic.fixed_key]]:[]);return Object.keys(c.tones||{}).some((p)=>fixed.indexOf(p)<0||["pos","neg","alt","cond","loop"].indexOf(c.tones[p])<0)||(c.fail_port&&fixed.indexOf(c.fail_port)<0)}),[])
eq("catalog: every field default exists and every select default is one of its options",Object.keys(CT).filter((k)=>(CT[k].fields||[]).some((f)=>!(f.key in CT[k].defaults)||(f.type==="select"&&!f.options.some((o)=>o.value===CT[k].defaults[f.key])))),[])
// presets
const PRE=CAT.presets
eq("catalog: presets point at known types and categories, with unique ids that are not type ids",PRE.filter((p)=>!CT[p.type]||cats.indexOf(p.category)<0||CT[p.id]||PRE.filter((q)=>q.id===p.id).length!==1||!p.label||!p.title).map((p)=>p.id),[])
eq("catalog: a preset only overlays config keys its type has",PRE.filter((p)=>Object.keys(p.config||{}).some((k)=>!(k in CT[p.type].defaults))).map((p)=>p.id),[])
// icons: the svg file, and a .icon-<name> mask rule in a stylesheet main.html links (the flow-* ones in chains-icons.css)
const MAINHTML=read("UI","windows","main.html"),linked=(MAINHTML.match(/<link rel="stylesheet" href="\.\.\/css\/[^"]+"/g)||[]).map((l)=>/css\/([^"]+)"/.exec(l)[1])
const sheets={};linked.forEach((f)=>{sheets[f]=read("UI","css",...f.split("/"))})
const iconHome=(name)=>linked.filter((f)=>sheets[f].indexOf(".icon-"+name+"{-webkit-mask-image:url(../../Assets/icons/"+name+".svg);mask-image:url(../../Assets/icons/"+name+".svg)}")>=0||sheets[f].indexOf(".icon-"+name+"{-webkit-mask-image:url(../../../Assets/icons/"+name+".svg);mask-image:url(../../../Assets/icons/"+name+".svg)}")>=0)
const icons=Array.from(new Set(ALL.map((k)=>M.FLOW_NODE_TYPES[k].icon).concat(PRE.map((p)=>p.icon),M.flowCatalogItems().map((i)=>i.icon))))
eq("icons: every type and preset icon has its Assets/icons/<name>.svg",icons.filter((i)=>!/^[a-z0-9-]+$/.test(i)||!fs.existsSync(path.join(ROOT,"Assets","icons",i+".svg"))),[])
eq("icons: ... and a .icon-<name> mask rule (with its -webkit- twin) in a stylesheet main.html loads",icons.filter((i)=>iconHome(i).length===0),[])
eq("icons: the flow-* icons live in chains-icons.css",icons.filter((i)=>/^flow-/.test(i)&&iconHome(i).indexOf("chains-icons.css")<0),[])
check("icons: at least the 20 new flow-* icons are in use",icons.filter((i)=>/^flow-/.test(i)).length>=20,String(icons.filter((i)=>/^flow-/.test(i)).length))
// colours: one .flow-cat-<id> rule per category (and per type colour), fed by a --flow-c-<id> variable in every theme block
const colours=Array.from(new Set(cats.concat(ALL.map((k)=>M.FLOW_NODE_TYPES[k].color),M.flowCatalogItems().map((i)=>i.color),["unknown"])))
eq("colours: every category colour has a .flow-cat-<id> rule in flow-editor.css",colours.filter((c)=>!new RegExp("(^|[,\\n])\\.flow-cat-"+c+"(,[^{]*)?\\{--flow-c:var\\(--flow-c-"+c+"\\)\\}","m").test(CSS)),[])
eq("colours: ... and a --flow-c-<id> value in the default, light and royal themes",colours.filter((c)=>[/^:root\{--flow-c-[^}]*\}/m,/^\[data-theme="light"\]\{--flow-c-[^}]*\}/m,/^\[data-theme="royal"\]\{--flow-c-[^}]*\}/m].some((re)=>{const m=re.exec(CSS);return !m||!new RegExp("--flow-c-"+c+":#[0-9a-fA-F]{6}[;}]").test(m[0])})),[])
eq("colours: sticky notes come in yellow, blue, green, red, purple and gray, each with its class and its variable",[M.FLOW_COMMENT_COLORS,M.FLOW_COMMENT_COLORS.filter((c)=>CSS.indexOf(".flow-comment-"+c+"{--flow-note:var(--flow-note-"+c+")}")<0||(CSS.match(new RegExp("--flow-note-"+c+":#","g"))||[]).length!==3),M.FLOW_NODE_TYPES.comment.defaults.color],[["yellow","blue","green","red","purple","gray"],[],"yellow"])
eq("colours: every wire tone has its class",["pos","neg","alt","cond","loop"].filter((t)=>CSS.indexOf(".flow-tone-"+t+"{--flow-t:var(--flow-w-"+t+")}")<0||CSS.indexOf("--flow-w-"+t+":")<0),[])
// picker items
const items=M.flowCatalogItems()
eq("items: one per type, then one per preset",[items.length,items.slice(0,ALL.length).map((i)=>i.id),items.slice(ALL.length).map((i)=>i.id),items.filter((i)=>i.preset).length],[ALL.length+PRE.length,ALL,PRE.map((p)=>p.id),PRE.length])
eq("items: a type item",M.flowCatalogItem("http"),{id:"http",type:"http",label:CT.http.label,description:CT.http.description,category:"action",icon:"flow-globe",color:"action",keywords:CT.http.keywords,config:null,title:"",preset:false})
{const p=PRE.find((x)=>x.id==="stop_fail");eq("items: a preset is a type with a config overlay, a title, its own icon and category",M.flowCatalogItem("stop_fail"),{id:"stop_fail",type:"end",label:p.label,description:p.description,category:"logic",icon:"warning",color:"logic",keywords:p.keywords,config:{status:"fail"},title:"Stop and fail",preset:true})}
eq("items: a preset files under its own category colour (evidence is an Output node shown under App)",[M.flowCatalogItem("evidence").type,M.flowCatalogItem("evidence").category,M.flowCatalogItem("evidence").color],["output","app","app"])
eq("items: unknown id",[M.flowCatalogItem("nope"),M.flowCatalogItem(""),M.flowCatalogItem(null)],[null,null,null])
eq("items: without the catalog there are just the 13 types and no preset",[M0.flowCatalogItems().length,M0.flowCatalogItems().some((i)=>i.preset)],[13,false])
// search
const S=(q,list)=>M.flowCatalogSearch(q,list).map((grp)=>grp.category.id+":"+grp.items.map((i)=>i.id).join(","))
const all=M.flowCatalogSearch("")
eq("search: an empty query lists everything, grouped in category order",[all.map((grp)=>grp.category.id),all.reduce((n,grp)=>n+grp.items.length,0),S("   "),S(null)],[cats,items.length,S(""),S("")])
check("search: a group is {category:{id,label},items} and holds only its own category",all.every((grp)=>grp.category.label===M.FLOW_CATEGORIES.find((c)=>c.id===grp.category.id).label&&grp.items.length>0&&grp.items.every((i)=>i.category===grp.category.id)))
eq("search: presets are listed with their category, after its types",[S("")[2],S("")[8]],["logic:decision,approval,foreach,wait,end,switch,merge,if,stop_fail,delay,loop","notify:log,notify"])
eq("search: by name (the best group first)",S("switch")[0],"logic:switch")
eq("search: an exact name beats a longer name and a keyword hit",[S("if")[0],S("python"),S("json")[0]],["logic:if,decision",["action:python_script,script"],"transform:json,json_parse,json_format,parse"])
eq("search: by category label",S("logic"),["logic:decision,approval,foreach,wait,end,switch,merge,if,stop_fail,delay,loop"])
eq("search: by keyword",[S("nmap"),S("sleep")],[["analysis:nmap_xml,nmap_grep,scan_parse","action:command","transform:parse"],["logic:wait,delay"]])
eq("search: every word must match, case does not matter",[S("HTTP post"),S("http zzzz"),S("HtTp PoSt")],[["action:http_post,http"],[],["action:http_post,http"]])
eq("search: no match -> []",[M.flowCatalogSearch("zzzz"),M.flowCatalogSearch("<script>")],[[],[]])
eq("search: only the given items are searched (the picker filters first)",S("",items.filter((i)=>i.type==="wait"||i.id==="comment")),["logic:wait,delay","note:comment"])
check("search: never throws on odd input",[undefined,0,{},[],"\\","(","[a-z"].every((q)=>{try{return Array.isArray(M.flowCatalogSearch(q))}catch(e){return false}}))
// hot bar
eq("hot bar: the default pins come from the catalog and all resolve",[M.FLOW_HOTBAR_DEFAULT,M.FLOW_HOTBAR_DEFAULT.filter((id)=>!M.flowCatalogItem(id)),M.FLOW_HOTBAR_MAX,M.FLOW_HOTBAR_DEFAULT.length<=M.FLOW_HOTBAR_MAX],[CAT.hotbar,[],12,true])
eq("hot bar: no list (null, junk) -> the default",[M.flowHotbarClean(),M.flowHotbarClean(null),M.flowHotbarClean("command"),M.flowHotbarClean({0:"wait"})],[CAT.hotbar,CAT.hotbar,CAT.hotbar,CAT.hotbar])
eq("hot bar: unknown ids, doubles, junk and Start are dropped; presets may be pinned; order is kept",M.flowHotbarClean(["start","wait","command","wait","nope",null,7,{},"if","<b>"]),["wait","command","if"])
eq("hot bar: an empty list stays empty (every pin removed)",M.flowHotbarClean([]),[])
eq("hot bar: capped at FLOW_HOTBAR_MAX, the first ones win",M.flowHotbarClean(ALL),ALL.filter((k)=>k!=="start").slice(0,12))
check("hot bar: a clean list is a new array",(()=>{const a=["wait"];return M.flowHotbarClean(a)!==a})()&&M.flowHotbarClean()!==M.FLOW_HOTBAR_DEFAULT)
}
// ---- the new node types in a graph: dynamic ports (switch), rename, tones, generic field validation
{const d=M.flowNewGraph()
const sw=M.flowAddNode(d,"switch",300,0,{cases:[{name:"web",op:"contains",value:"80/tcp"},{name:"ssh",op:"contains",value:"22/tcp"}],default:"other"})
const a=M.flowAddNode(d,"log",600,0,{message:"web"}),b=M.flowAddNode(d,"log",600,200,{message:"ssh"}),c=M.flowAddNode(d,"log",600,400,{message:"other"})
eq("switch: default node has one case and the default port",[M.flowNodePorts({type:"switch",config:M.flowDefaultConfig("switch")}),M.flowNodeSummary({type:"switch",config:M.flowDefaultConfig("switch")})],[{in:true,out:["case1","default"]},"1 case(s)"])
eq("switch: one port per case, then the default port",M.flowNodePorts(sw),{in:true,out:["web","ssh","other"]})
eq("switch: the card grows one row per port",[M.flowNodeSize(sw).h-M.flowNodeSize({type:"wait",config:{}}).h,M.flowPortPos(sw,"out","other").y-M.flowPortPos(sw,"out","web").y,M.flowPortPos(sw,"out","web").y,M.flowPortPos(sw,"in").y],[2*M.FLOW_GEOM.row,2*M.FLOW_GEOM.row,M.FLOW_GEOM.head+M.FLOW_GEOM.sum+M.FLOW_GEOM.row/2,M.FLOW_GEOM.head+M.FLOW_GEOM.sum+M.FLOW_GEOM.row/2])
eq("switch: a missing or empty default falls back to the type's default port; no case leaves just that port; duplicates collapse",[M.flowNodePorts({type:"switch",config:{cases:[{name:"x"}]}}).out,M.flowNodePorts({type:"switch",config:{cases:[{name:"x"}],default:""}}).out,M.flowNodePorts({type:"switch",config:{cases:[]}}).out,M.flowNodePorts({type:"switch",config:{cases:"junk"}}).out,M.flowNodePorts({type:"switch",config:{cases:[{name:"x"},{name:"x"},null,{name:""},{name:"default"}]}}).out],[["x","default"],["x","default"],["default"],["default"],["x","default"]])
check("switch: wired from every port",!!M.flowConnect(d,"n1","out",sw.id)&&!!M.flowConnect(d,sw.id,"web",a.id)&&!!M.flowConnect(d,sw.id,"ssh",b.id)&&!!M.flowConnect(d,sw.id,"other",c.id)&&M.flowConnect(d,sw.id,"default",c.id)===null&&M.flowConnect(d,sw.id,"out",c.id)===null)
{const r=M.flowValidate(d);eq("switch: a wired switch graph validates clean",[r.ok,r.errors,r.warnings],[true,[],[]])}
const portsOf=(g)=>g.edges.filter((e)=>e.from===sw.id).map((e)=>e.port)
{const x=M.flowClone(d),n=M.flowFindNode(x,sw.id)
eq("rename: a switch case is renamed in the config and on its edges",[M.flowRenamePort(x,sw.id,"web","http"),n.config.cases.map((r)=>r.name),n.config.default,portsOf(x),M.flowNodePorts(n).out],[true,["http","ssh"],"other",["http","ssh","other"],["http","ssh","other"]])
eq("rename: the default port of a switch",[M.flowRenamePort(x,sw.id,"other","rest"),n.config.default,n.config.cases.map((r)=>r.name),portsOf(x)],[true,"rest",["http","ssh"],["http","ssh","rest"]])
eq("rename: onto an existing port, a bad name or the same name is refused and changes nothing",[M.flowRenamePort(x,sw.id,"http","ssh"),M.flowRenamePort(x,sw.id,"http","rest"),M.flowRenamePort(x,sw.id,"http","has space"),M.flowRenamePort(x,sw.id,"http",""),M.flowRenamePort(x,sw.id,"http","x".repeat(25)),M.flowRenamePort(x,sw.id,"http","http"),n.config.cases.map((r)=>r.name),portsOf(x)],[false,false,false,false,false,false,["http","ssh"],["http","ssh","rest"]])
eq("rename: only dynamic types (a fixed-port catalog node is refused, an unknown node too)",[M.flowRenamePort(x,a.id,"out","next"),M.flowRenamePort(x,"zz","a","b"),M.flowNodePorts(M.flowFindNode(x,a.id)).out],[false,false,["out"]])
check("rename: the renamed graph still validates",M.flowValidate(x).ok&&M.flowValidate(x).warnings.length===0)
// the inspector edits rows in place, then the editor reconciles
const before=M.flowNodePorts(n).out;n.config.cases[1].name="secure";M.flowReconcilePorts(x,sw.id,before)
eq("reconcile: one case renamed in place keeps its edge",portsOf(x),["http","secure","rest"])
const before2=M.flowNodePorts(n).out;n.config.cases=[n.config.cases[0]];M.flowReconcilePorts(x,sw.id,before2)
eq("reconcile: a removed case drops its edge",[portsOf(x),M.flowNodePorts(n).out],[["http","rest"],["http","rest"]])
n.config.cases=[];eq("prune: with no case left only the default edge survives",[M.flowPruneEdges(x).map((e)=>e.port),portsOf(x)],[["http"],["rest"]])}
// wire and port tones
const tone=(type,port,config)=>M.flowPortTone(port,{type,config:config||M.flowDefaultConfig(type)})
eq("tone: decision - named branches are conditions, yes/no style names keep their colour, the else port is the alternative",[tone("decision","alive",{branches:[{name:"alive"}],else:"else"}),tone("decision","else",{branches:[{name:"alive"}],else:"else"}),tone("decision","else",{branches:[{name:"alive"}]}),tone("decision","yes",{branches:[{name:"yes"}],else:"no"}),tone("decision","no",{branches:[{name:"yes"}],else:"no"}),tone("decision","down",{branches:[{name:"down"}],else:"rest"}),tone("decision","rest",{branches:[{name:"down"}],else:"rest"})],["cond","alt","alt","pos","neg","neg","alt"])
eq("tone: switch - cases are conditions, the default port is the alternative (renamed or not)",[tone("switch","web",sw.config),tone("switch","ssh",sw.config),tone("switch","other",sw.config),tone("switch","case1"),tone("switch","default")],["cond","cond","alt","cond","alt"])
eq("tone: for each - the item path is the loop, done is the main path",[tone("foreach","item"),tone("foreach","done")],["loop",""])
eq("tone: script - named branches are conditions, error is negative, a lone out is the main path",[tone("script","alive",{branches:["alive","down"]}),tone("script","down",{branches:["alive","down"]}),tone("script","ok",{branches:["ok"]}),tone("script","error"),tone("script","out")],["cond","neg","pos","neg",""])
eq("tone: catalog tones (http, cve lookup, target, filter, file) and plain out ports",[tone("http","success"),tone("http","fail"),tone("cve_lookup","found"),tone("cve_lookup","none"),tone("input_target","missing"),tone("filter","empty"),tone("file_write","error"),tone("regex","nomatch"),tone("http","nope"),tone("math","out"),tone("merge","out")],["pos","neg","pos","neg","neg","neg","neg","neg","","",""])
eq("tone: every tone the catalog declares is what flowPortTone answers",Object.keys(CAT.types).filter((k)=>Object.keys(CAT.types[k].tones||{}).some((p)=>tone(k,p)!==CAT.types[k].tones[p])),[])
eq("tone: built-in fixed ports, with and without the node",[tone("command","success"),tone("command","fail"),tone("approval","approved"),tone("approval","rejected"),tone("parse","nomatch"),tone("wait","out"),M.flowPortTone("fail",null),M.flowPortTone("out",{type:"nope"}),M.flowPortTone("yes")],["pos","neg","pos","neg","neg","","neg","","pos"])
check("tone: only the five tone names (or none) for every port of every default node",ALL.every((k)=>M.flowNodePorts({type:k,config:M.flowDefaultConfig(k)}).out.every((p)=>["","pos","neg","alt","cond","loop"].indexOf(tone(k,p))>=0)))
// generic field validation of the catalog types
const errs=(type,config)=>{const x=M.flowNewGraph();M.flowAddNode(x,type,0,0,config);return M.flowValidate(x).errors.filter((i)=>i.node==="n2")}
const ecodes=(type,config)=>errs(type,config).map((i)=>i.code)
const NEW=ALL.filter((k)=>TYPES.indexOf(k)<0)
const requiredNow=(k)=>{const c=CAT.types[k].defaults,shown=(f)=>!f.show_if||Object.keys(f.show_if).every((s)=>[].concat(f.show_if[s]).indexOf(c[s])>=0);return (CAT.types[k].fields||[]).filter((f)=>f.required&&shown(f)&&(f.type==="rows"?!(c[f.key]||[]).length:!String(c[f.key]==null?"":c[f.key]).trim())).length+(CAT.types[k].fields||[]).filter((f)=>f.type==="rows"&&shown(f)).reduce((n,f)=>n+(c[f.key]||[]).reduce((m,r)=>m+(f.rows||[]).filter((sf)=>sf.required&&!String(r[sf.key]==null?"":r[sf.key]).trim()).length,0),0)}
eq("validate: a fresh node of a new type reports exactly its empty required fields, nothing else",NEW.filter((k)=>{const e=ecodes(k);return e.length!==requiredNow(k)||e.some((c)=>c!=="empty_field")}),[])
eq("validate: the types whose defaults are complete give no error at all",NEW.filter((k)=>requiredNow(k)===0).filter((k)=>ecodes(k).length),[])
eq("validate: which new types are complete out of the box",NEW.filter((k)=>requiredNow(k)===0),["input_target","input_text","switch","merge","template","split","json","scan_parse","note","finding","result"])
eq("validate: no built-in type reports a generic field code",TYPES.filter((k)=>k!=="start").filter((k)=>ecodes(k).some((c)=>["empty_field","bad_var","text_too_long","too_many_rows"].indexOf(c)>=0)),[])
{const i=errs("http")[0];eq("validate: empty_field names the node and the field",[errs("http").length,i.code,i.node,i.edge,i.message],[1,"empty_field","n2",null,"\"HTTP request\": URL is empty."])}
eq("validate: a required field of spaces only is still empty; filled in is fine",[ecodes("http",{url:"   "}),ecodes("http",{url:"https://{IPv4}/"}),ecodes("math",{expr:"1+1"}),ecodes("log",{message:"hi"})],[["empty_field"],[],[],[]])
eq("validate: bad_var (digits first, a dash, a space, too long); an empty variable is allowed",[ecodes("http",{url:"u",var:"1bad"}),ecodes("math",{expr:"1",var:"a-b"}),ecodes("template",{var:"a b"}),ecodes("template",{var:"v".repeat(41)}),ecodes("template",{var:"_ok9"}),ecodes("template",{var:"v".repeat(40)}),ecodes("template",{var:""})],[["bad_var"],["bad_var"],["bad_var"],["bad_var"],[],[],[]])
check("validate: the bad_var message quotes the name, cut short",/"1bad" is not a valid variable name/.test(errs("http",{url:"u",var:"1bad"})[0].message)&&errs("template",{var:"<".repeat(200)})[0].message.length<120)
eq("validate: bad_config (a select value that is not an option)",[ecodes("http",{url:"u",method:"BREW"}),ecodes("log",{message:"m",level:"loud"}),CAT.types.log.fields.find((f)=>f.key==="level").options.filter((o)=>ecodes("log",{message:"m",level:o.value}).length).length],[["bad_config"],["bad_config"],0])
eq("validate: text_too_long (the field's own max_chars)",[ecodes("http",{url:"x".repeat(4097)}),ecodes("http",{url:"x".repeat(4096)})],[["text_too_long"],[]])
eq("validate: too_many_rows and an empty row list",[ecodes("http",{url:"u",headers:Array.from({length:31},(_,i)=>({name:"h"+i,value:"v"}))}).filter((c)=>c==="too_many_rows"),ecodes("switch",{cases:Array.from({length:13},(_,i)=>({name:"c"+i,op:"equals",value:""}))}),ecodes("switch",{cases:[]}),ecodes("fields",{ops:[]})],[["too_many_rows"],["too_many_rows"],["empty_field"],["empty_field"]])
eq("validate: bad_port_name in a row and in the default port; duplicate port names",[ecodes("switch",{cases:[{name:"b c",op:"equals",value:""}]}),ecodes("switch",{default:"bad port"}),ecodes("switch",{cases:[{name:"",op:"equals",value:""}]}).filter((c)=>c!=="duplicate_port"),ecodes("switch",{cases:[{name:"a",op:"equals",value:""},{name:"a",op:"equals",value:""}]}),ecodes("switch",{cases:[{name:"default",op:"equals",value:""}]})],[["bad_port_name"],["bad_port_name"],["empty_field"],["duplicate_port"],["duplicate_port"]])
eq("validate: a field hidden by show_if is not checked until it shows",[ecodes("split",{mode:"lines",separator:""}),ecodes("split",{mode:"separator",separator:""}),ecodes("split",{mode:"separator",separator:","}),ecodes("json",{action:"parse",path:""}),ecodes("json",{action:"get",path:""}),ecodes("input_target",{source:"live",name:""}),ecodes("input_target",{source:"name",name:""})],[[],["empty_field"],[],[],["empty_field"],[],["empty_field"]])
check("validate: junk configs of the new types never throw",NEW.every((k)=>[null,1,"x",[],{cases:"x",headers:7,ops:[null,1],conditions:{},var:{},url:[]}].every((cfg)=>{try{return typeof M.flowValidate({schema:2,settings:{},nodes:[{id:"n1",type:"start",config:{}},{id:"n2",type:k,config:cfg}],edges:[]}).ok==="boolean"}catch(e){return false}})))
// graph-level validation with the new types
const gr=()=>{const x=M.flowNewGraph();const h=M.flowAddNode(x,"http",300,0,{url:"https://{IPv4}/"}),j=M.flowAddNode(x,"json",600,0),l=M.flowAddNode(x,"log",900,0,{message:"${json}"});M.flowConnect(x,"n1","out",h.id);M.flowConnect(x,h.id,"success",j.id);M.flowConnect(x,j.id,"out",l.id);return x}
{const r=M.flowValidate(gr());eq("graph: start -> http -> json -> log is valid; the open fail ports (the catalog's fail_port) warn",[r.ok,r.errors,r.warnings.map((i)=>[i.code,i.node])],[true,[],[["port_unconnected","n2"],["port_unconnected","n3"]]])}
{const x=gr();M.flowConnect(x,"n2","fail","n4");M.flowConnect(x,"n3","error","n4");eq("graph: wiring them clears the warnings",[M.flowValidate(x).ok,M.flowValidate(x).warnings],[true,[]])}
{const x=gr();x.edges[1].port="nope";const i=M.flowValidate(x).errors.find((e)=>e.code==="unknown_port");eq("graph: unknown_port on a new type names the node and the edge",[!!i,i&&i.node,i&&i.edge,/has no output named "nope"/.test(i?i.message:"")],[true,"n2","e2",true])}
{const x=gr();x.edges.push({id:"e9",from:"n3",port:"out",to:"ghost"});const i=M.flowValidate(x).errors.find((e)=>e.code==="dangling_edge");eq("graph: dangling_edge",[!!i,i&&i.edge,i&&i.node],[true,"e9","n3"])}
{const x=gr();M.flowRemoveNodes(x,["n3"]);eq("graph: removing a node takes its edges along (nothing dangles), the rest becomes unreachable",[x.edges.map((e)=>e.id),M.flowValidate(x).ok,M.flowValidate(x).warnings.filter((i)=>i.code==="unreachable").map((i)=>i.node)],[["e1"],true,["n4"]])}
{const x=gr();x.edges.push({id:"e9",from:"n4",port:"out",to:"n1"});check("graph: nothing connects into Start",codes(M.flowValidate(x)).indexOf("bad_edge_target")>=0)}
eq("graph: schema 2 accepted, schema 3 refused",[2,3].map((sv)=>{const x=gr();x.schema=sv;const r=M.flowValidate(x);return [r.ok,codes(r)]}),[[true,[]],[false,["schema_version"]]])
throws("graph: a schema 3 diagram does not load",()=>{const x=gr();x.schema=3;M.flowNormalize(x)})
throws("graph: ... nor from text, nor inside an export bundle",()=>{const x=gr();x.schema=3;M.flowParse(JSON.stringify({loya_chain:1,name:"x",graph:x}))})
{const old={schema:1,settings:{shell:"",run_timeout:1800,max_visits:200,on_error:"stop"},nodes:[{id:"n1",type:"start",title:"Start",x:0,y:0,config:{trigger:"manual"}},{id:"n2",type:"command",title:"Ping",x:280,y:0,config:{commands:[{text:"ping -c 1 {IPv4}"}],mode:"sequence",stop_on_fail:true,timeout:300,shell:""}},{id:"n3",type:"decision",title:"Up?",x:560,y:0,config:{branches:[{name:"alive",match:"all",conditions:[{source:"exit_code",op:"eq",value:"0"}]}],else:"down"}},{id:"n4",type:"end",title:"End",x:840,y:0,config:{status:"success",message:""}}],edges:[{id:"e1",from:"n1",port:"out",to:"n2"},{id:"e2",from:"n2",port:"success",to:"n3"},{id:"e3",from:"n2",port:"fail",to:"n3"},{id:"e4",from:"n3",port:"alive",to:"n4"},{id:"e5",from:"n3",port:"down",to:"n4"}],viewport:{x:10,y:20,zoom:0.5}}
const snap=JSON.stringify(old),up=M.flowNormalize(old)
eq("schema 1: an old diagram loads unchanged apart from the schema number",[up.schema,up.nodes,up.edges,up.settings,up.viewport],[2,old.nodes,old.edges,old.settings,old.viewport])
eq("schema 1: the input is not touched, and the loaded graph validates clean",[JSON.stringify(old)===snap,M.flowValidate(up).ok,M.flowValidate(up).errors,M.flowValidate(up).warnings],[true,true,[],[]])
eq("schema 1: saved again it is a schema 2 diagram that reads back the same",[JSON.parse(M.flowSerialize(old)).schema,M.flowParse(M.flowSerialize(old)).nodes],[2,old.nodes])
const mixed=M.flowNormalize({schema:2,nodes:[{id:"a",type:"start"},{id:"b",type:"switch"},{id:"c",type:"http",config:{url:"u"}}],edges:[{from:"a",port:"out",to:"b"}]})
eq("schema 2: catalog nodes get their label and missing config keys filled from the catalog defaults",[mixed.nodes[1].title,mixed.nodes[1].config,mixed.nodes[2].title,mixed.nodes[2].config.method,mixed.nodes[2].config.url,mixed.nodes[2].config.var],["Switch",CAT.types.switch.defaults,"HTTP request","GET","u","response"])}
{const x=gr();const text=M.flowSerialize(x),back=M.flowParse(text);eq("round trip: a graph of new node types survives",[back.nodes,back.edges,M.flowSerialize(back)===text],[x.nodes,x.edges,true])}
eq("geometry: card sizes of the studio (240 wide, 46 head, 24 summary, 22 per port row, 10 padding)",[M.FLOW_GEOM.w,M.FLOW_GEOM.head,M.FLOW_GEOM.sum,M.FLOW_GEOM.row,M.FLOW_GEOM.pad,M.flowNodeSize({type:"wait",config:{}}),M.flowNodeSize({type:"command",config:{}}),M.flowNodeSize({type:"end",config:{}})],[240,46,24,22,10,{w:240,h:102},{w:240,h:124},{w:240,h:102}])
{const lin=M.flowLinearToGraph("x",[{command:"a"},{command:"b"}]);eq("geometry: a converted linear chain steps one card plus 60 px",[lin.nodes[1].x-lin.nodes[0].x,lin.nodes[2].x-lin.nodes[1].x],[300,300])}
}
// ---- editor: DOM-free helpers (the file must load with no DOM at all)
const es={module:{exports:{}},console}
vm.createContext(es)
vm.runInContext(CATALOG+"\n"+MODEL,es)
let editorLoaded=true;try{vm.runInContext(EDITOR,es)}catch(e){editorLoaded=false;console.log("  editor load error: "+e.message)}
check("editor: loads without a DOM",editorLoaded)
const E=es.module.exports
check("editor: flowEditorCreate exported",typeof E.flowEditorCreate==="function")
const near=(a,b)=>Math.abs(a-b)<1e-6
{const view={x:100,y:50,zoom:2}
eq("view: world -> screen",E.flowViewToScreen(view,110,60),{x:20,y:20})
eq("view: screen -> world",E.flowViewToWorld(view,20,20),{x:110,y:60})
const p=E.flowViewToWorld(view,333,77),q=E.flowViewToScreen(view,p.x,p.y);check("view: the two are inverse",near(q.x,333)&&near(q.y,77))
eq("view: clamp zoom to 0.25..2",[E.flowClampZoom(0.01),E.flowClampZoom(9),E.flowClampZoom(1.25),E.flowClampZoom(NaN)],[0.25,2,1.25,1])
const z=E.flowViewZoomAt(view,300,200,0.5),beforeW=E.flowViewToWorld(view,300,200),afterW=E.flowViewToWorld(z,300,200)
check("view: zooming keeps the point under the cursor fixed",z.zoom===0.5&&near(beforeW.x,afterW.x)&&near(beforeW.y,afterW.y))
const z2=E.flowViewZoomAt(view,300,200,50);check("view: zoom-at clamps",z2.zoom===2&&near(z2.x,view.x)&&near(z2.y,view.y))
eq("view: pan by screen pixels",E.flowViewPan(view,40,-20),{x:80,y:60,zoom:2})
const fit=E.flowViewFit({x:0,y:0,w:1000,h:400},800,600,40)
const tl=E.flowViewToScreen(fit,0,0),br=E.flowViewToScreen(fit,1000,400)
check("view: fit shows the whole bounds inside the padding, centred",tl.x>=40-1e-6&&tl.y>=40-1e-6&&br.x<=760+1e-6&&br.y<=560+1e-6&&near(tl.x+br.x,800)&&near(tl.y+br.y,600))
check("view: fit never zooms in past 100% nor below 25%",E.flowViewFit({x:0,y:0,w:10,h:10},800,600,40).zoom===1&&E.flowViewFit({x:0,y:0,w:99999,h:99999},800,600,40).zoom===0.25)
eq("view: fit with nothing to show",E.flowViewFit(null,800,600,40),{x:0,y:0,zoom:1})
check("view: rect visibility",E.flowViewSees({x:0,y:0,zoom:1},800,600,{x:700,y:500,w:300,h:300})&&!E.flowViewSees({x:0,y:0,zoom:1},800,600,{x:900,y:0,w:10,h:10}))
eq("box: normalised rectangle from two corners",E.flowBoxRect(50,80,10,20),{x:10,y:20,w:40,h:60})
const bg={nodes:[{id:"a",type:"wait",x:0,y:0,config:{}},{id:"b",type:"wait",x:500,y:0,config:{}},{id:"c",type:"comment",x:0,y:300,config:{w:200,h:100}}]}
eq("box: nodes touched by the box",[E.flowBoxHits(bg,{x:-10,y:-10,w:100,h:50}),E.flowBoxHits(bg,{x:-10,y:-10,w:900,h:900}),E.flowBoxHits(bg,{x:300,y:200,w:50,h:50})],[["a"],["a","b","c"],[]])
const mm=E.flowMiniMap({x:0,y:0,w:1000,h:500},180,120,8)
const m0=E.flowMiniToMini(mm,0,0),m1=E.flowMiniToMini(mm,1000,500),w=E.flowMiniToWorld(mm,m1.x,m1.y)
check("minimap: the bounds fit inside the map and convert back",m0.x>=8-1e-6&&m0.y>=8-1e-6&&m1.x<=172+1e-6&&m1.y<=112+1e-6&&near(w.x,1000)&&near(w.y,500))
eq("text: wrap for sticky notes",E.flowWrapText("one two three four\nfive",9,3),["one two","three","four\u2026"])
eq("text: wrap breaks long words",E.flowWrapText("abcdefghij",4,5),["abcd","efgh","ij"])
eq("issues: grouped per node, errors first",(()=>{const m=E.flowIssueMap({errors:[{node:"a",code:"x",message:"E1"}],warnings:[{node:"a",code:"y",message:"W1"},{node:"b",code:"y",message:"W2"},{node:null,message:"global"}]});return [m.nodes.a.level,m.nodes.a.text,m.nodes.b.level,Object.keys(m.nodes).length]})(),["error","E1\nW1","warning",2])
eq("keys: the shortcut list for the Ctrl+/ sheet",[Array.isArray(E.FLOW_EDITOR_SHORTCUTS),E.FLOW_EDITOR_SHORTCUTS.every((s)=>s.keys&&s.label)],[true,true])
// auto-wire: a command connected to a decision takes its other result port along
const aw=M.flowNewGraph();const awc=M.flowAddNode(aw,"command",200,0),awd=M.flowAddNode(aw,"decision",400,0),awc2=M.flowAddNode(aw,"command",600,0),aws=M.flowAddNode(aw,"script",200,200)
const awe=M.flowConnect(aw,awc.id,"fail",awd.id)
const awt=M.flowAutoWireTwin(aw,awe)
eq("auto-wire: connecting fail to a decision also connects success",[awt&&awt.port,awt&&awt.to,aw.edges.filter((e)=>e.from===awc.id).map((e)=>e.port).sort(),awt.id!==awe.id],["success",awd.id,["fail","success"],true])
eq("auto-wire: nothing when the other port is already connected",M.flowAutoWireTwin(aw,awe),null)
M.flowRemoveEdges(aw,[awt.id])
eq("auto-wire: the twin is an ordinary edge that can be deleted alone",aw.edges.filter((e)=>e.from===awc.id).map((e)=>e.port),["fail"])
M.flowRemoveEdges(aw,[awe.id])
eq("auto-wire: only command -> decision, only result ports, junk-safe",[M.flowAutoWireTwin(aw,M.flowConnect(aw,awc.id,"success",awc2.id)),M.flowAutoWireTwin(aw,M.flowConnect(aw,aws.id,"out",awd.id)),M.flowAutoWireTwin(aw,M.flowConnect(aw,awd.id,"else",awc2.id)),M.flowAutoWireTwin(aw,null),M.flowAutoWireTwin(null,awe),M.flowAutoWireTwin(aw,{from:"zz",port:"fail",to:awd.id})],[null,null,null,null,null,null])
eq("settings: script isolation survives only as an explicit override",[M.flowNormalize({nodes:[{id:"n1",type:"start"}],settings:{script_isolation:"allow"}}).settings.script_isolation,M.flowNormalize({nodes:[{id:"n1",type:"start"}],settings:{script_isolation:"sandboxed"}}).settings.script_isolation,"script_isolation" in M.flowNormalize({nodes:[{id:"n1",type:"start"}],settings:{script_isolation:"inherit"}}).settings,"script_isolation" in M.flowNormalize({nodes:[{id:"n1",type:"start"}],settings:{script_isolation:"root"}}).settings],["allow","sandboxed",false,false])
eq("wheel: a plain wheel pans on both axes, Shift pans sideways, Ctrl zooms",[E.flowWheelAction(0,120,false,false),E.flowWheelAction(30,-40,false,false),E.flowWheelAction(0,120,false,true),E.flowWheelAction(50,0,false,true),E.flowWheelAction(0,0,false,false),E.flowWheelAction(0,0,true,false)],[{type:"pan",dx:0,dy:120},{type:"pan",dx:30,dy:-40},{type:"pan",dx:120,dy:0},{type:"pan",dx:50,dy:0},{type:"none"},{type:"none"}])
eq("wheel: Ctrl+wheel and pinch zoom in the right direction, pinch more sensitive, big deltas capped",(()=>{const out=E.flowWheelAction(0,120,true,false),inn=E.flowWheelAction(0,-120,true,false),pinch=E.flowWheelAction(0,-10,true,false),huge=E.flowWheelAction(0,-99999,true,false);return [out.type,out.factor<1,inn.factor>1,Math.abs(Math.log(pinch.factor)/10)>Math.abs(Math.log(inn.factor)/120),huge.factor===E.flowWheelAction(0,-300,true,false).factor]})(),["zoom",true,true,true,true])
check("keys: the sheet says wheel pans and Ctrl+wheel zooms",E.FLOW_EDITOR_SHORTCUTS.some((s)=>s.keys==="Wheel / two-finger scroll"&&/^Pan the canvas/.test(s.label))&&E.FLOW_EDITOR_SHORTCUTS.some((s)=>s.keys==="Ctrl+wheel / pinch"&&s.label==="Zoom at the cursor")&&/\| Wheel \/ two-finger scroll \| Pan the canvas/.test(require("fs").readFileSync(require("path").join(__dirname,"..","..","README.md"),"utf8")))
check("editor: a connect gesture auto-wires in the same undo step and reports it",/const twin=flowAutoWireTwin\(st\.graph,edge\)\nsyncEdges\(\[\]\);setSelection\(\[\],\[edge\.id\]\);commit\(\)\nif\(twin\)[^\n]*call\("onAutoWire"/.test(require("fs").readFileSync(require("path").join(__dirname,"..","..","UI","js","components","flow-editor.js"),"utf8")))
}
// ---- editor source and CSS conventions
check("editor: every drag captures its pointer",(EDITOR.match(/setPointerCapture/g)||[]).length>=1&&!/addEventListener\("(dragstart|drop|dragover)"/.test(EDITOR))
check("editor: no web storage",!/localStorage|sessionStorage/.test(EDITOR))
check("editor: no getScreenCTM",!/getScreenCTM/.test(EDITOR))
eq("css: -webkit-user-select beside every user-select",(CSS.match(/(^|[;{\s])user-select:none/g)||[]).length,(CSS.match(/-webkit-user-select:none/g)||[]).length)
check("css: no CSS zoom, no backdrop-filter",!/[;{\s]zoom:/.test(CSS)&&!/backdrop-filter\s*:/.test(CSS.replace(/\/\*[\s\S]*?\*\//g,"")))
// The rewritten canvas has no glass variant of its own (its surfaces are solid mixes, see the file header); the one glass rule of the
// studio lives in chains-studio.css. Wherever a glass variant is written it must stay keyed inside :where() (no extra specificity).
{const STUDIO=read("UI","css","chains-studio.css"),bareGlass=(t)=>(t.replace(/\/\*[\s\S]*?\*\//g,"").match(/(^|[^(])\[data-style="glass"\]/g)||[]).length
check("css: glass variants are keyed inside :where()",/html:where\(\[data-style="glass"\]\) \.cf-head\{/.test(STUDIO)&&bareGlass(CSS)===0&&bareGlass(STUDIO)===0)
check("css: the canvas surfaces are solid (no glass rule, no blur) in flow-editor.css",!/data-style/.test(CSS.replace(/\/\*[\s\S]*?\*\//g,""))&&!/blur\(/.test(CSS.replace(/\/\*[\s\S]*?\*\//g,"")))}
check("css: reduced motion is respected",/prefers-reduced-motion/.test(CSS))
eq("css: every state class of the contract is styled",["is-pending","is-running","is-success","is-fail","is-skipped","is-waiting","is-planned","is-selected","has-error","has-warning","is-taken"].filter((c)=>CSS.indexOf("."+c)<0),[])
{const body=CSS.replace(/\/\*[\s\S]*?\*\//g,"");const outside=body.split("\n").filter((l)=>/#[0-9a-fA-F]{3,8}\b|rgba?\(/.test(l)&&!/^\s*(:root|\[data-theme|:where\(\[data-style="glass"\]\[data-theme|html)[^{]*\{\s*--flow-/.test(l)&&!/^\s*--flow-/.test(l))
eq("css: colours only come from variables (literals only in --flow-* definitions)",outside,[])}
check("line endings: LF only",[MODEL,EDITOR,CSS,read("tests","js","flow_model.js")].every((t)=>t.indexOf("\r")<0))
console.log("flow_model: "+passed+" passed, "+failed+" failed")
if(failed)process.exit(1)
