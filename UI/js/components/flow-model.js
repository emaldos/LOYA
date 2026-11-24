// Chain diagram ("flow") model: pure data functions shared by the editor, the inspector and the node tests.
// NO DOM access in this file. Mirrors Cores/Services/flow_schema.py (node types, ports, limits, validation codes).
// Graph JSON (schema 2; schema 1 graphs load unchanged): {schema,settings,nodes:[{id,type,title,x,y,config}],edges:[{id,from,port,to}],viewport:{x,y,zoom}}
// viewport.x/y = the canvas (world) point shown at the top-left corner of the editor; screen=(world-viewport)*zoom.
const FLOW_SCHEMA_VERSION=2
const FLOW_LIMITS={nodes:200,edges:400,script_bytes:65536,commands_per_node:20,command_bytes:4096,branches:12,conditions:12,regex_chars:500,graph_bytes:524288,title_chars:80,port_chars:24,id_chars:40,text_chars:8192,wait_max:3600,approval_timeout_max:86400,foreach_items_max:1000,assign_max:40,run_timeout_min:10,run_timeout_max:86400,max_visits_min:1,max_visits_max:2000,node_timeout_min:1,node_timeout_max:7200}
const FLOW_ID_RE=/^[A-Za-z0-9_-]{1,40}$/
const FLOW_PORT_RE=/^[A-Za-z0-9_-]{1,24}$/
const FLOW_SETTINGS_DEFAULT={shell:"",run_timeout:1800,max_visits:200,on_error:"stop"}
// Palette groups, in display order.
// The node catalog (every type, its ports, defaults, typed fields, presets) is generated from Cores/Services/flow_nodes.py into
// flow-catalog.js. In the page it is the global FLOW_CATALOG; in node it is required. Without it only the 13 built-in types exist.
const FLOW_CAT=(()=>{if(typeof FLOW_CATALOG!=="undefined"&&FLOW_CATALOG)return FLOW_CATALOG;try{if(typeof module!=="undefined"&&module.exports&&typeof require==="function")return require("./flow-catalog.js").FLOW_CATALOG}catch(e){}return null})()
const FLOW_CATEGORIES=FLOW_CAT&&Array.isArray(FLOW_CAT.categories)?FLOW_CAT.categories.map((c)=>({id:c.id,label:c.label,hint:c.hint||""})):[{id:"input",label:"Triggers & inputs"},{id:"action",label:"Actions"},{id:"logic",label:"Logic"},{id:"math",label:"Calculations & variables"},{id:"transform",label:"Data transform"},{id:"analysis",label:"Data analysis"},{id:"app",label:"App"},{id:"output",label:"Outputs"},{id:"notify",label:"Notifications & log"},{id:"note",label:"Notes"}]
// icon = an existing Assets/icons name (.icon-<name>); color = category accent token (--flow-c-<color> in flow-editor.css);
// ports = fixed output port names, or "dynamic" (see flowNodePorts); input = has the single input port.
const FLOW_NODE_TYPES={
start:{label:"Start",category:"input",icon:"play",color:"input",input:false,ports:["out"],defaults:{trigger:"manual"},description:"Where the chain begins. Every diagram has exactly one."},
command:{label:"Command",category:"action",icon:"command-line",color:"action",input:true,ports:["success","fail"],defaults:{commands:[],mode:"sequence",stop_on_fail:true,timeout:300,shell:""},description:"Run one or more terminal commands, then continue on success or fail."},
script:{label:"Script",category:"action",icon:"code-block",color:"action",input:true,ports:"dynamic",defaults:{language:"python",code:"",branches:["out"],timeout:60,network:false},description:"Run a Python, Bash or PowerShell script that picks the next branch."},
subchain:{label:"Sub-chain",category:"action",icon:"chain",color:"action",input:true,ports:["success","fail"],defaults:{playbook_id:null,pass_vars:true},description:"Run another chain, then continue on success or fail."},
decision:{label:"Decision",category:"logic",icon:"shuffle",color:"logic",input:true,ports:"dynamic",defaults:{branches:[{name:"yes",match:"all",conditions:[{source:"output",field:"",op:"contains",value:"",ci:true}]}],else:"else"},description:"Pick a branch with no-code rules on the previous output."},
approval:{label:"Approval",category:"logic",icon:"clipboard-check",color:"logic",input:true,ports:["approved","rejected"],defaults:{message:"Continue?",timeout:0},description:"Pause and ask the operator before going on."},
parse:{label:"Parse",category:"transform",icon:"search",color:"transform",input:true,ports:["out","nomatch"],defaults:{mode:"regex",source:"stdout",pattern:"",flags:"i",tool:"nmap",path:"",assign:[],var:"parsed"},description:"Pull values out of the previous output (regex, tool parser or path)."},
set:{label:"Set variable",category:"math",icon:"pairs",color:"math",input:true,ports:["out"],defaults:{assign:[]},description:"Store values in flow variables."},
foreach:{label:"For each",category:"logic",icon:"refresh",color:"logic",input:true,ports:["item","done"],defaults:{items:"",item_var:"item",index_var:"index",max_items:50,split:"auto"},description:"Run the item path once per item, then continue on done."},
wait:{label:"Wait",category:"logic",icon:"clock",color:"logic",input:true,ports:["out"],defaults:{seconds:5},description:"Pause for a number of seconds."},
end:{label:"End",category:"logic",icon:"stop",color:"logic",input:true,ports:[],defaults:{status:"success",message:""},description:"Stop the run with a success or fail status."},
output:{label:"Output",category:"output",icon:"report",color:"output",input:true,ports:["out"],defaults:{action:"notify",note_name:"",report_id:null,title:"",severity:"info",content:"${last.stdout}"},description:"Append to a note, draft a finding, save evidence or notify."},
comment:{label:"Comment",category:"note",icon:"text",color:"note",input:false,ports:[],defaults:{text:"",color:"yellow",w:220,h:120},description:"A sticky note. It is never run."}
}
// Catalog types join the table; the built-in ones take their category, icon and keywords from the catalog too.
if(FLOW_CAT&&FLOW_CAT.types)Object.keys(FLOW_CAT.types).forEach((k)=>{
const c=FLOW_CAT.types[k],cur=FLOW_NODE_TYPES[k]
if(cur){cur.category=c.category||cur.category;cur.color=c.color||cur.color;cur.icon=c.icon||cur.icon;cur.keywords=c.keywords||[];if(c.description)cur.description=c.description;return}
FLOW_NODE_TYPES[k]={label:c.label||k,category:c.category||"action",icon:c.icon||"_",color:c.color||c.category||"action",input:c.input!==false,ports:Array.isArray(c.ports)?c.ports.slice():[],dynamic:c.dynamic||null,tones:c.tones||{},defaults:c.defaults||{},description:c.description||"",keywords:c.keywords||[],summary:c.summary||"",fields:Array.isArray(c.fields)?c.fields:[],fail_port:c.fail_port||""}
})
const FLOW_HOTBAR_DEFAULT=FLOW_CAT&&Array.isArray(FLOW_CAT.hotbar)?FLOW_CAT.hotbar.slice():["command","decision","script","foreach","set","output"]
const FLOW_HOTBAR_MAX=12
// Everything the node picker offers: one item per type plus the presets (a type with a config overlay and a title).
function flowCatalogItems(){
const out=[]
Object.keys(FLOW_NODE_TYPES).forEach((k)=>{const t=FLOW_NODE_TYPES[k];out.push({id:k,type:k,label:t.label,description:t.description||"",category:t.category,icon:t.icon,color:t.color,keywords:t.keywords||[],config:null,title:"",preset:false})})
;((FLOW_CAT&&FLOW_CAT.presets)||[]).forEach((p)=>{const t=FLOW_NODE_TYPES[p.type];if(!t||!p.id||FLOW_NODE_TYPES[p.id])return;out.push({id:p.id,type:p.type,label:p.label||p.id,description:p.description||t.description||"",category:p.category||t.category,icon:p.icon||t.icon,color:p.category||t.color,keywords:p.keywords||[],config:p.config||null,title:p.title||p.label||"",preset:true})})
return out
}
function flowCatalogItem(id){const items=flowCatalogItems();for(let i=0;i<items.length;i++)if(items[i].id===id)return items[i];return null}
// Search by name, category and keywords. Every word of the query must match somewhere; name matches rank first.
// -> [{category:{id,label},items:[item]}] in category order (empty groups are left out).
function flowCatalogSearch(query,items){
items=items||flowCatalogItems()
const words=String(query==null?"":query).toLowerCase().split(/\s+/).filter(Boolean)
const catLabel={};FLOW_CATEGORIES.forEach((c)=>{catLabel[c.id]=c.label})
const scored=[]
items.forEach((it,i)=>{
const name=it.label.toLowerCase(),cat=String(catLabel[it.category]||it.category).toLowerCase(),keys=(it.keywords||[]).join(" ").toLowerCase(),desc=String(it.description||"").toLowerCase(),tid=String(it.type).toLowerCase()
let score=0
for(let w=0;w<words.length;w++){const q=words[w];let s=0
if(name===q)s=100;else if(name.indexOf(q)===0)s=60;else if(name.indexOf(q)>=0)s=40;else if(tid.indexOf(q)>=0||it.id.toLowerCase().indexOf(q)>=0)s=30;else if(keys.indexOf(q)>=0)s=20;else if(cat.indexOf(q)>=0)s=10;else if(desc.indexOf(q)>=0)s=5
if(!s)return
score+=s}
scored.push({it,score:score-(it.preset?1:0),i})
})
const groups=[]
FLOW_CATEGORIES.forEach((c)=>{const list=scored.filter((x)=>x.it.category===c.id);if(!list.length)return;list.sort((a,b)=>b.score-a.score||a.i-b.i);groups.push({category:{id:c.id,label:c.label},items:list.map((x)=>x.it),best:list[0].score})})
if(words.length)groups.sort((a,b)=>b.best-a.best)
return groups
}
// A clean hot bar list: known ids only, no doubles, at most FLOW_HOTBAR_MAX.
function flowHotbarClean(list){
const out=[];(Array.isArray(list)?list:FLOW_HOTBAR_DEFAULT).forEach((id)=>{id=String(id||"");if(out.indexOf(id)<0&&out.length<FLOW_HOTBAR_MAX&&flowCatalogItem(id)&&id!=="start")out.push(id)})
return out
}
const FLOW_COMMENT_COLORS=["yellow","blue","green","red","purple","gray"]
// Node box geometry (canvas px). Shared by the editor, the auto-layout and the minimap.
const FLOW_GEOM={w:240,head:46,sum:24,row:22,pad:10,commentMinW:120,commentMinH:60,commentMaxW:800,commentMaxH:600}

function flowClone(g){return g==null?g:JSON.parse(JSON.stringify(g))}
function flowIsObj(v){return !!v&&typeof v==="object"&&!Array.isArray(v)}
function flowNum(v,d){const n=Number(v);return Number.isFinite(n)?n:d}
function flowClamp(v,lo,hi){return Math.min(hi,Math.max(lo,v))}
function flowTruncate(s,n){s=String(s==null?"":s);return s.length>n?s.slice(0,Math.max(0,n-1))+"\u2026":s}
function flowSnap(v,grid){v=flowNum(v,0);grid=flowNum(grid,0);if(!(grid>0))return v;const r=Math.round(v/grid)*grid;return r===0?0:r}
function flowFindNode(graph,id){const ns=(graph&&graph.nodes)||[];for(let i=0;i<ns.length;i++)if(ns[i].id===id)return ns[i];return null}
function flowFindEdge(graph,id){const es=(graph&&graph.edges)||[];for(let i=0;i<es.length;i++)if(es[i].id===id)return es[i];return null}
function flowNewGraph(){return {schema:FLOW_SCHEMA_VERSION,settings:flowClone(FLOW_SETTINGS_DEFAULT),nodes:[{id:"n1",type:"start",title:"Start",x:40,y:160,config:{trigger:"manual"}}],edges:[],viewport:{x:0,y:0,zoom:1}}}
// Lowest unused "<prefix><number>" over node AND edge ids.
function flowNewId(graph,prefix){
prefix=prefix||"n"
const used=new Set();let max=0
const take=(id)=>{id=String(id);used.add(id);if(id.indexOf(prefix)===0){const n=Number(id.slice(prefix.length));if(Number.isInteger(n)&&n>max)max=n}}
;((graph&&graph.nodes)||[]).forEach((n)=>take(n.id));((graph&&graph.edges)||[]).forEach((e)=>take(e.id))
let n=max+1;while(used.has(prefix+n))n++
return prefix+n
}
function flowUniq(list){const out=[],seen=new Set();list.forEach((p)=>{p=String(p==null?"":p);if(p&&!seen.has(p)){seen.add(p);out.push(p)}});return out}
// {in:bool,out:[port names]} for a node; dynamic types read their config.
function flowNodePorts(node){
const t=node&&FLOW_NODE_TYPES[node.type]
if(!t)return {in:true,out:[]}
const cfg=flowIsObj(node.config)?node.config:{}
let out
if(node.type==="script"){const bs=flowUniq(Array.isArray(cfg.branches)?cfg.branches:[]).filter((b)=>b!=="error");out=(bs.length?bs:["out"]).concat(["error"])}
else if(node.type==="decision")out=flowUniq((Array.isArray(cfg.branches)?cfg.branches:[]).map((b)=>flowIsObj(b)?b.name:"").concat([cfg.else||"else"]))
else if(t.dynamic){const rows=Array.isArray(cfg[t.dynamic.rows])?cfg[t.dynamic.rows]:[];const fixed=t.dynamic.fixed_key?String(cfg[t.dynamic.fixed_key]||(t.defaults&&t.defaults[t.dynamic.fixed_key])||""):"";out=flowUniq(rows.map((r)=>flowIsObj(r)?r[t.dynamic.name||"name"]:"").concat(t.ports,fixed?[fixed]:[]))}
else out=t.ports.slice()
return {in:!!t.input,out}
}
function flowNodeSize(node){
const G=FLOW_GEOM
if(node&&node.type==="comment"){const c=flowIsObj(node.config)?node.config:{};return {w:flowClamp(flowNum(c.w,220),G.commentMinW,G.commentMaxW),h:flowClamp(flowNum(c.h,120),G.commentMinH,G.commentMaxH)}}
const n=flowNodePorts(node).out.length
return {w:G.w,h:G.head+G.sum+Math.max(1,n)*G.row+G.pad}
}
// Absolute canvas position of a port. kind "in" -> left edge; "out" -> right edge, one row per port (unknown port -> first row).
function flowPortPos(node,kind,port){
const G=FLOW_GEOM,x=flowNum(node&&node.x,0),y=flowNum(node&&node.y,0),rowY=G.head+G.sum+G.row/2
if(kind==="in")return {x,y:y+rowY}
const i=Math.max(0,flowNodePorts(node).out.indexOf(port))
return {x:x+flowNodeSize(node).w,y:y+rowY+i*G.row}
}
// Horizontal cubic bezier from an output port (x1,y1) to an input port (x2,y2): it leaves to the right and arrives from the left.
// A backward edge on (about) the same row loops underneath the nodes instead of running through them.
function flowEdgePath(x1,y1,x2,y2){
const dx=x2-x1,r=(v)=>Math.round(v*10)/10
if(dx<-20&&Math.abs(y2-y1)<120){
const yb=Math.max(y1,y2)+90,c=56
return "M"+r(x1)+","+r(y1)+" C"+r(x1+c)+","+r(y1)+" "+r(x1+c)+","+r(yb)+" "+r(x1)+","+r(yb)+" L"+r(x2)+","+r(yb)+" C"+r(x2-c)+","+r(yb)+" "+r(x2-c)+","+r(y2)+" "+r(x2)+","+r(y2)
}
const c=dx>=0?Math.max(40,dx/2):Math.max(60,Math.min(240,-dx/2+60))
return "M"+r(x1)+","+r(y1)+" C"+r(x1+c)+","+r(y1)+" "+r(x2-c)+","+r(y2)+" "+r(x2)+","+r(y2)
}
function flowGraphBounds(graph,ids){
let x0=Infinity,y0=Infinity,x1=-Infinity,y1=-Infinity
const only=ids?new Set(ids):null
;((graph&&graph.nodes)||[]).forEach((n)=>{if(only&&!only.has(n.id))return;const s=flowNodeSize(n);x0=Math.min(x0,n.x);y0=Math.min(y0,n.y);x1=Math.max(x1,n.x+s.w);y1=Math.max(y1,n.y+s.h)})
return x0===Infinity?null:{x:x0,y:y0,w:x1-x0,h:y1-y0}
}
// Topmost node under a canvas point (executable nodes sit above sticky notes). pad grows every box, for forgiving drops.
function flowHitNode(graph,x,y,pad){
pad=pad||0
const ns=(graph&&graph.nodes)||[]
for(let pass=0;pass<2;pass++)for(let i=ns.length-1;i>=0;i--){const n=ns[i];if((n.type==="comment")!==(pass===1))continue;const s=flowNodeSize(n);if(x>=n.x-pad&&x<=n.x+s.w+pad&&y>=n.y-pad&&y<=n.y+s.h+pad)return n}
return null
}
// Wire and port colour. neg = fail-like, pos = success-like, alt = the "otherwise" way out (decision else, switch default),
// cond = a named branch of a decision / switch / script, loop = a for-each item path, "" = the main path.
const FLOW_TONE_NEG=["fail","error","rejected","nomatch","false","no","empty","none","missing","down","denied","timeout"]
const FLOW_TONE_POS=["success","approved","true","yes","found","ok"]
function flowPortTone(port,node){
const t=node&&FLOW_NODE_TYPES[node.type]
if(t){
if(t.tones&&t.tones[port])return t.tones[port]
const cfg=flowIsObj(node.config)?node.config:{}
if(node.type==="foreach")return port==="item"?"loop":""
if(node.type==="decision"){if(port===(cfg.else||"else"))return FLOW_TONE_NEG.indexOf(port)>=0?"neg":"alt";return FLOW_TONE_NEG.indexOf(port)>=0?"neg":FLOW_TONE_POS.indexOf(port)>=0?"pos":"cond"}
if(t.dynamic){if(t.dynamic.fixed_key&&port===String(cfg[t.dynamic.fixed_key]||""))return "alt";if(t.ports.indexOf(port)<0)return "cond"}
if(node.type==="script"&&port!=="error"&&port!=="out")return FLOW_TONE_NEG.indexOf(port)>=0?"neg":FLOW_TONE_POS.indexOf(port)>=0?"pos":"cond"
}
if(FLOW_TONE_NEG.indexOf(port)>=0)return "neg"
if(FLOW_TONE_POS.indexOf(port)>=0)return "pos"
return ""
}
function flowDefaultConfig(type){const t=FLOW_NODE_TYPES[type];return t?flowClone(t.defaults):{}}
function flowHasStart(graph){return ((graph&&graph.nodes)||[]).some((n)=>n.type==="start")}
// Adds a node; returns it, or null (unknown type, node limit, or a second start).
function flowAddNode(graph,type,x,y,config){
const t=FLOW_NODE_TYPES[type]
if(!t||!graph||!Array.isArray(graph.nodes))return null
if(graph.nodes.length>=FLOW_LIMITS.nodes)return null
if(type==="start"&&flowHasStart(graph))return null
const node={id:flowNewId(graph,"n"),type,title:t.label,x:flowNum(x,0),y:flowNum(y,0),config:Object.assign(flowDefaultConfig(type),flowIsObj(config)?flowClone(config):{})}
graph.nodes.push(node)
return node
}
function flowRemoveNodes(graph,ids){
const kill=new Set(ids||[]),before=graph.nodes.length
graph.nodes=graph.nodes.filter((n)=>!kill.has(n.id))
graph.edges=graph.edges.filter((e)=>!kill.has(e.from)&&!kill.has(e.to))
return before-graph.nodes.length
}
function flowRemoveEdges(graph,ids){
const kill=new Set(ids||[]),before=graph.edges.length
graph.edges=graph.edges.filter((e)=>!kill.has(e.id))
return before-graph.edges.length
}
// Moves nodes by (dx,dy). With snap (a grid size) the first node lands on the grid and the others keep their offsets to it.
function flowMoveNodes(graph,ids,dx,dy,snap){
const want=new Set(ids||[]),list=graph.nodes.filter((n)=>want.has(n.id))
if(!list.length)return 0
dx=flowNum(dx,0);dy=flowNum(dy,0)
if(snap>0){const a=list[0];dx=flowSnap(a.x+dx,snap)-a.x;dy=flowSnap(a.y+dy,snap)-a.y}
list.forEach((n)=>{n.x+=dx;n.y+=dy})
return list.length
}
// Why an edge from -> to is refused ("" when it is fine). Used for the live target highlight too.
function flowConnectRefusal(graph,from,port,to){
const a=flowFindNode(graph,from),b=flowFindNode(graph,to)
if(!a||!b)return "missing node"
if(from===to)return "a node cannot connect to itself"
if(!flowNodePorts(b).in)return "this node has no input"
if(flowNodePorts(a).out.indexOf(port)<0)return "unknown output port"
if(graph.edges.some((e)=>e.from===from&&e.port===port&&e.to===to))return "already connected"
if(graph.edges.length>=FLOW_LIMITS.edges)return "edge limit reached"
return ""
}
function flowConnect(graph,from,port,to){
if(flowConnectRefusal(graph,from,port,to))return null
const edge={id:flowNewId(graph,"e"),from,port,to}
graph.edges.push(edge)
return edge
}
// A command's result usually goes to one decision whatever the exit code. After connecting one result port (success or
// fail) of a COMMAND node to a DECISION node: when the other result port has no connection yet, connect it to the same
// decision. -> the extra edge, or null. Both edges stay ordinary edges (each can be deleted on its own).
function flowAutoWireTwin(graph,edge){
if(!graph||!edge)return null
const from=flowFindNode(graph,edge.from),to=flowFindNode(graph,edge.to)
if(!from||!to||from.type!=="command"||to.type!=="decision")return null
const other=edge.port==="success"?"fail":edge.port==="fail"?"success":null
if(!other||graph.edges.some((e)=>e.from===from.id&&e.port===other))return null
return flowConnect(graph,from.id,other,to.id)
}
// Renames an output port: in the node config when it is still there (script branches, decision branch/else) and on its edges.
function flowRenamePort(graph,nodeId,oldName,newName){
const node=flowFindNode(graph,nodeId)
if(!node||oldName===newName||!FLOW_PORT_RE.test(String(newName||"")))return false
const dyn=FLOW_NODE_TYPES[node.type]&&FLOW_NODE_TYPES[node.type].dynamic
if(node.type!=="script"&&node.type!=="decision"&&!dyn)return false
const cfg=node.config||(node.config={})
const inConfig=flowNodePorts(node).out.indexOf(oldName)>=0
if(inConfig&&flowNodePorts(node).out.indexOf(newName)>=0)return false
if(dyn){let hit=false;(Array.isArray(cfg[dyn.rows])?cfg[dyn.rows]:[]).forEach((r)=>{if(flowIsObj(r)&&r[dyn.name||"name"]===oldName&&!hit){r[dyn.name||"name"]=newName;hit=true}});if(!hit&&dyn.fixed_key&&String(cfg[dyn.fixed_key]||"")===oldName)cfg[dyn.fixed_key]=newName}
else if(node.type==="script"){if(Array.isArray(cfg.branches))cfg.branches=cfg.branches.map((b)=>b===oldName?newName:b)}
else{let hit=false;(Array.isArray(cfg.branches)?cfg.branches:[]).forEach((b)=>{if(flowIsObj(b)&&b.name===oldName&&!hit){b.name=newName;hit=true}});if(!hit&&(cfg.else||"else")===oldName)cfg.else=newName}
graph.edges.forEach((e)=>{if(e.from===nodeId&&e.port===oldName)e.port=newName})
return true
}
// Drops edges whose source port (or either node) no longer exists, and edges into nodes without an input. Returns the removed edges.
function flowPruneEdges(graph){
const ports=new Map();graph.nodes.forEach((n)=>ports.set(n.id,flowNodePorts(n)))
const gone=[]
graph.edges=graph.edges.filter((e)=>{const a=ports.get(e.from),b=ports.get(e.to);const ok=!!a&&!!b&&b.in&&a.out.indexOf(e.port)>=0;if(!ok)gone.push(e);return ok})
return gone
}
// After a config edit: when exactly one port name changed in place, its edges follow the rename; the rest is pruned.
function flowReconcilePorts(graph,nodeId,oldPorts){
const node=flowFindNode(graph,nodeId);if(!node)return
const now=flowNodePorts(node).out,old=oldPorts||[]
if(old.length===now.length){
const diff=[];for(let i=0;i<now.length;i++)if(old[i]!==now[i])diff.push(i)
if(diff.length===1&&now.indexOf(old[diff[0]])<0&&old.indexOf(now[diff[0]])<0)graph.edges.forEach((e)=>{if(e.from===nodeId&&e.port===old[diff[0]])e.port=now[diff[0]]})
}
flowPruneEdges(graph)
}
// One line describing a node's config, shown under its title.
function flowNodeSummary(node){
const c=flowIsObj(node&&node.config)?node.config:{},plural=(n,w)=>n+" "+w+(n===1?"":"s")
switch(node&&node.type){
case "start":return c.trigger==="caller"?"Runs from /caller":c.trigger==="live"?"Runs on the live target":"Manual run"
case "command":{const cmds=(Array.isArray(c.commands)?c.commands:[]).map((x)=>String((flowIsObj(x)?x.text:x)||"").trim()).filter(Boolean);if(!cmds.length)return "No command yet";return cmds[0].split("\n")[0]+(cmds.length>1?"  (+"+(cmds.length-1)+" more)":"")}
case "script":{const code=String(c.code||"");const lines=code.trim()?code.replace(/\s+$/,"").split("\n").length:0;return (c.language||"python")+" script"+(lines?", "+plural(lines,"line"):" (empty)")}
case "decision":{const bs=Array.isArray(c.branches)?c.branches:[];const rules=bs.reduce((n,b)=>n+((flowIsObj(b)&&Array.isArray(b.conditions))?b.conditions.length:0),0);return plural(rules,"rule")+(bs.length>1?" in "+bs.length+" branches":"")}
case "parse":return c.mode==="tool"?(c.tool||"tool")+" output":c.mode==="jsonpath"?"path: "+(c.path||"(none)"):"regex: "+(c.pattern||"(none)")
case "set":{const a=(Array.isArray(c.assign)?c.assign:[]).filter((x)=>flowIsObj(x)&&x.var);return a.length===1?a[0].var+" = "+String(a[0].value==null?"":a[0].value):plural(a.length,"variable")}
case "foreach":return "each "+(c.item_var||"item")+" in "+(c.items||"(nothing)")
case "wait":return plural(flowNum(c.seconds,0),"second")
case "approval":return String(c.message||"Ask before continuing")
case "output":return c.action==="note_append"?"Append to note"+(c.note_name?" "+c.note_name:""):c.action==="finding_draft"?"Draft a finding"+(c.title?": "+c.title:""):c.action==="evidence"?"Save evidence"+(c.title?": "+c.title:""):"Notify"+(c.title?": "+c.title:"")
case "subchain":return c.playbook_id==null||c.playbook_id===""?"No chain picked":(c.playbook_name?String(c.playbook_name):"Chain #"+c.playbook_id)
case "end":return "Ends as "+(c.status==="fail"?"fail":"success")+(c.message?": "+c.message:"")
case "comment":return String(c.text||"")
}
const spec=node&&FLOW_NODE_TYPES[node.type]
if(spec&&spec.summary)return String(spec.summary).replace(/\{([A-Za-z0-9_]+)\}/g,(m,k)=>{const v=c[k];return Array.isArray(v)?String(v.length):v==null?"":String(v).split("\n")[0]}).replace(/\s+/g," ").trim()
return spec?spec.description||"":""
}
// ---- validation (codes follow flow_schema.validate_graph where practical)
function flowValidate(graph){
const errors=[],warnings=[]
const err=(code,message,node,edge)=>errors.push({node:node||null,edge:edge||null,code,message})
const warn=(code,message,node,edge)=>warnings.push({node:node||null,edge:edge||null,code,message})
const done=()=>({ok:errors.length===0,errors,warnings})
if(!flowIsObj(graph)||!Array.isArray(graph.nodes)||!Array.isArray(graph.edges)){err("structure","The diagram is not a valid graph object.");return done()}
if(Number(graph.schema)>FLOW_SCHEMA_VERSION)err("schema_version","This diagram was made by a newer version (schema "+graph.schema+").")
const L=FLOW_LIMITS
if(graph.nodes.length>L.nodes)err("too_many_nodes","Too many nodes ("+graph.nodes.length+", the limit is "+L.nodes+").")
if(graph.edges.length>L.edges)err("too_many_edges","Too many connections ("+graph.edges.length+", the limit is "+L.edges+").")
const byId=new Map(),ports=new Map()
let starts=0
graph.nodes.forEach((n)=>{
if(!flowIsObj(n)||typeof n.id!=="string"){err("structure","A node is not an object with an id.");return}
if(!FLOW_ID_RE.test(n.id))err("bad_id","Node id \""+flowTruncate(n.id,40)+"\" is not valid.",n.id)
if(byId.has(n.id)){err("duplicate_id","Node id \""+n.id+"\" is used twice.",n.id);return}
byId.set(n.id,n)
if(!FLOW_NODE_TYPES[n.type]){err("unknown_type","Unknown node type \""+n.type+"\".",n.id);ports.set(n.id,{in:true,out:[]});return}
ports.set(n.id,flowNodePorts(n))
if(n.type==="start")starts++
flowValidateNode(n,err,warn)
})
if(starts===0)err("no_start","The diagram needs a Start node.")
if(starts>1)graph.nodes.forEach((n)=>{if(flowIsObj(n)&&n.type==="start")err("many_start","Only one Start node is allowed.",n.id)})
const edgeIds=new Set(),pairs=new Set(),used=new Set(),next=new Map()
graph.edges.forEach((e)=>{
if(!flowIsObj(e)||typeof e.from!=="string"||typeof e.to!=="string"){err("structure","A connection is not an object with from/to.");return}
const id=typeof e.id==="string"?e.id:""
if(!FLOW_ID_RE.test(id))err("bad_id","Connection id \""+flowTruncate(id,40)+"\" is not valid.",null,id||null)
else if(edgeIds.has(id)||byId.has(id))err("duplicate_id","Connection id \""+id+"\" is used twice.",null,id)
edgeIds.add(id)
const a=byId.get(e.from),b=byId.get(e.to)
if(!a||!b){err("dangling_edge","A connection points at a node that does not exist.",a?e.from:(b?e.to:null),id);return}
if(ports.get(e.from).out.indexOf(e.port)<0){err("unknown_port","\""+(a.title||a.id)+"\" has no output named \""+e.port+"\".",e.from,id);return}
if(!ports.get(e.to).in){err("bad_edge_target","Nothing can connect into \""+(b.title||b.id)+"\".",e.to,id);return}
if(e.from===e.to){err("self_loop","A node cannot connect to itself.",e.from,id);return}
const key=e.from+"\u0000"+e.port+"\u0000"+e.to
if(pairs.has(key))warn("duplicate_edge","The same connection exists twice.",e.from,id)
pairs.add(key);used.add(e.from+"\u0000"+e.port)
if(!next.has(e.from))next.set(e.from,[]);next.get(e.from).push(e.to)
})
// reachability from the start node
const start=graph.nodes.find((n)=>flowIsObj(n)&&n.type==="start")
if(start&&starts===1){
const seen=new Set([start.id]),stack=[start.id]
while(stack.length){const id=stack.pop();(next.get(id)||[]).forEach((t)=>{if(!seen.has(t)){seen.add(t);stack.push(t)}})}
byId.forEach((n,id)=>{if(n.type!=="comment"&&!seen.has(id))warn("unreachable","\""+(n.title||id)+"\" is not reachable from Start.",id)})
}
byId.forEach((n,id)=>{
if(!FLOW_NODE_TYPES[n.type])return
const elseName=n.type==="decision"?String((n.config&&n.config.else)||"else"):null
ports.get(id).out.forEach((p)=>{if((p==="fail"||p==="error"||p===elseName||(FLOW_NODE_TYPES[n.type].fail_port===p))&&!used.has(id+"\u0000"+p))warn("port_unconnected","Output \""+p+"\" of \""+(n.title||id)+"\" is not connected.",id)})
})
let size=0;try{size=JSON.stringify(graph).length}catch(e){err("structure","The diagram cannot be serialised.")}
if(size>L.graph_bytes)err("graph_too_large","The diagram is too large ("+Math.round(size/1024)+" KB, the limit is "+Math.round(L.graph_bytes/1024)+" KB).")
return done()
}
function flowValidateNode(n,err,warn){
const L=FLOW_LIMITS,c=flowIsObj(n.config)?n.config:{},name=n.title||n.id
const checkPorts=(names,what)=>{const seen=new Set();names.forEach((p)=>{p=String(p==null?"":p);if(!FLOW_PORT_RE.test(p))err("bad_port_name",what+" name \""+flowTruncate(p,30)+"\" is not valid (letters, digits, _ and -, up to "+L.port_chars+").",n.id);else if(seen.has(p))err("duplicate_port",what+" name \""+p+"\" is used twice.",n.id);seen.add(p)})}
if(n.type==="command"){
const cmds=Array.isArray(c.commands)?c.commands:[]
const texts=cmds.map((x)=>String((flowIsObj(x)?x.text:x)||""))
if(!texts.some((t)=>t.trim()))err("empty_command","\""+name+"\" has no command.",n.id)
if(cmds.length>L.commands_per_node)err("too_many_commands","\""+name+"\" has more than "+L.commands_per_node+" commands.",n.id)
if(texts.some((t)=>t.length>L.command_bytes))err("command_too_long","A command in \""+name+"\" is longer than "+L.command_bytes+" characters.",n.id)
if(texts.some((t)=>t.indexOf("${raw:")>=0))warn("raw_in_command","\""+name+"\" inserts an unquoted value (${raw:...}) in a command.",n.id)
}else if(n.type==="script"){
if(!String(c.code||"").trim())err("empty_script","\""+name+"\" has no script code.",n.id)
if(String(c.code||"").length>L.script_bytes)err("script_too_large","The script in \""+name+"\" is larger than "+Math.round(L.script_bytes/1024)+" KB.",n.id)
if(["python","bash","powershell"].indexOf(c.language)<0)err("bad_config","\""+name+"\" has an unknown script language.",n.id)
const bs=Array.isArray(c.branches)?c.branches:[]
if(bs.length>L.branches)err("too_many_branches","\""+name+"\" has more than "+L.branches+" branches.",n.id)
checkPorts(bs.concat(bs.indexOf("error")>=0?["error"]:[]),"Branch")
}else if(n.type==="decision"){
const bs=Array.isArray(c.branches)?c.branches:[]
if(!bs.length)err("empty_decision","\""+name+"\" needs at least one branch.",n.id)
if(bs.length>L.branches)err("too_many_branches","\""+name+"\" has more than "+L.branches+" branches.",n.id)
checkPorts(bs.map((b)=>flowIsObj(b)?b.name:"").concat([c.else||"else"]),"Branch")
bs.forEach((b)=>{
const conds=flowIsObj(b)&&Array.isArray(b.conditions)?b.conditions:[]
if(!conds.length)err("empty_branch","Branch \""+((b&&b.name)||"?")+"\" of \""+name+"\" has no rule.",n.id)
if(conds.length>L.conditions)err("too_many_conditions","Branch \""+((b&&b.name)||"?")+"\" of \""+name+"\" has more than "+L.conditions+" rules.",n.id)
conds.forEach((k)=>{if(flowIsObj(k)&&(k.op==="regex"||k.op==="not_regex"||k.source==="match_count")){const rx=String(k.source==="match_count"?k.field:k.value||"");if(rx.length>L.regex_chars)err("invalid_regex","A regex in \""+name+"\" is longer than "+L.regex_chars+" characters.",n.id);else if(!rx)err("invalid_regex","A regex rule in \""+name+"\" is empty.",n.id)}})
})
}else if(n.type==="parse"){
if(c.mode==="regex"||!c.mode){const p=String(c.pattern||"");if(!p)err("invalid_regex","\""+name+"\" has no pattern.",n.id);else if(p.length>L.regex_chars)err("invalid_regex","The pattern in \""+name+"\" is longer than "+L.regex_chars+" characters.",n.id)}
else if(c.mode==="jsonpath"){if(!String(c.path||"").trim())err("bad_config","\""+name+"\" has no path.",n.id)}
else if(c.mode!=="tool")err("bad_config","\""+name+"\" has an unknown parse mode.",n.id)
}else if(n.type==="foreach"){
if(!String(c.items||"").trim())err("empty_items","\""+name+"\" has nothing to loop over.",n.id)
}else if(n.type==="subchain"){
if(c.playbook_id==null||c.playbook_id==="")err("subchain_unset","\""+name+"\" has no chain picked.",n.id)
}else{
const spec=FLOW_NODE_TYPES[n.type]
if(!spec||!spec.fields||!spec.fields.length)return
const shown=(f)=>!flowIsObj(f.show_if)||Object.keys(f.show_if).every((k)=>(Array.isArray(f.show_if[k])?f.show_if[k]:[f.show_if[k]]).indexOf(c[k])>=0)
spec.fields.forEach((f)=>{
if(!shown(f))return
const v=c[f.key],label=f.label||f.key
if(f.type==="rows"){
const rows=Array.isArray(v)?v:[]
if(f.required&&!rows.length)err("empty_field","\""+name+"\": "+label+" needs at least one row.",n.id)
if(f.max_rows&&rows.length>f.max_rows)err("too_many_rows","\""+name+"\": "+label+" has more than "+f.max_rows+" rows.",n.id)
rows.forEach((r)=>(f.rows||[]).forEach((sf)=>{const rv=flowIsObj(r)?r[sf.key]:"";if(sf.required&&!String(rv==null?"":rv).trim())err("empty_field","\""+name+"\": "+(sf.label||sf.key)+" is empty in a "+(f.row_label||"row")+".",n.id);else if(sf.type==="port"&&String(rv||"")&&!FLOW_PORT_RE.test(String(rv)))err("bad_port_name","\""+name+"\": port name \""+flowTruncate(rv,30)+"\" is not valid.",n.id)}))
return
}
const text=String(v==null?"":v)
if(f.required&&!text.trim())err("empty_field","\""+name+"\": "+label+" is empty.",n.id)
else if(f.type==="var"&&text&&!/^[A-Za-z_][A-Za-z0-9_]{0,39}$/.test(text))err("bad_var","\""+name+"\": \""+flowTruncate(text,30)+"\" is not a valid variable name.",n.id)
else if(f.type==="port"&&text&&!FLOW_PORT_RE.test(text))err("bad_port_name","\""+name+"\": port name \""+flowTruncate(text,30)+"\" is not valid.",n.id)
else if(f.type==="select"&&Array.isArray(f.options)&&f.options.length&&!f.options.some((o)=>o&&o.value===v))err("bad_config","\""+name+"\": "+label+" has an unknown value.",n.id)
else if(f.max_chars&&text.length>f.max_chars)err("text_too_long","\""+name+"\": "+label+" is longer than "+f.max_chars+" characters.",n.id)
})
if(spec.dynamic){const ports=flowNodePorts(n).out,rows=Array.isArray(c[spec.dynamic.rows])?c[spec.dynamic.rows]:[];if(ports.length<rows.filter((r)=>flowIsObj(r)&&String(r[spec.dynamic.name||"name"]||"")).length+(spec.dynamic.fixed_key?1:0)+spec.ports.length)err("duplicate_port","\""+name+"\" uses a port name twice.",n.id)}
}
}
// ---- auto-layout: layered, left to right
// Column = longest path from the start (back edges of cycles are ignored), rows ordered by barycentre sweeps to reduce crossings.
// Sticky notes are not moved. Mutates and returns the graph. opts={gapX,gapY,grid,originX,originY}.
function flowAutoLayout(graph,opts){
opts=opts||{}
const gapX=flowNum(opts.gapX,80),gapY=flowNum(opts.gapY,30),grid=flowNum(opts.grid,20)>0?flowNum(opts.grid,20):1
const ox=flowNum(opts.originX,40),oy=flowNum(opts.originY,40)
const nodes=((graph&&graph.nodes)||[]).filter((n)=>n.type!=="comment")
if(!nodes.length)return graph
const byId=new Map(nodes.map((n)=>[n.id,n]))
const out=new Map(),inc=new Map();nodes.forEach((n)=>{out.set(n.id,[]);inc.set(n.id,[])})
const seen=new Set()
graph.edges.forEach((e,i)=>{
if(!byId.has(e.from)||!byId.has(e.to)||e.from===e.to)return
const key=e.from+"\u0000"+e.to;if(seen.has(key))return;seen.add(key)
out.get(e.from).push({to:e.to,port:e.port,pi:Math.max(0,flowNodePorts(byId.get(e.from)).out.indexOf(e.port)),i})
})
out.forEach((list)=>list.sort((a,b)=>a.pi-b.pi||a.i-b.i))
// depth-first walk: discovery order, post order, back edges
const color=new Map(),disc=[],post=[],back=new Set()
const walk=(root)=>{
if(color.get(root))return
const stack=[{id:root,k:0}];color.set(root,1);disc.push(root)
while(stack.length){
const top=stack[stack.length-1],list=out.get(top.id)
if(top.k<list.length){const t=list[top.k++].to,c=color.get(t)||0;if(c===1)back.add(top.id+"\u0000"+t);else if(c===0){color.set(t,1);disc.push(t);stack.push({id:t,k:0})}}
else{color.set(top.id,2);post.push(top.id);stack.pop()}
}
}
const hasIn=new Set();out.forEach((list)=>list.forEach((x)=>hasIn.add(x.to)))
const start=nodes.find((n)=>n.type==="start")
if(start)walk(start.id)
nodes.forEach((n)=>{if(!hasIn.has(n.id))walk(n.id)})
nodes.forEach((n)=>walk(n.id))
out.forEach((list,id)=>list.forEach((x)=>{if(!back.has(id+"\u0000"+x.to))inc.get(x.to).push({from:id,port:x.port})}))
const fwd=(id)=>out.get(id).filter((x)=>!back.has(id+"\u0000"+x.to))
// layers: longest path over the forward edges, in topological (reverse post) order
const layer=new Map(),topo=post.slice().reverse()
topo.forEach((id)=>{
const preds=inc.get(id);let l=0
if(preds.length)preds.forEach((p)=>{l=Math.max(l,(layer.get(p.from)||0)+1)})
else l=(start&&id!==start.id)?1:0
layer.set(id,l)
})
const layers=[];disc.forEach((id)=>{const l=layer.get(id);(layers[l]||(layers[l]=[])).push(id)})
for(let i=0;i<layers.length;i++)if(!layers[i])layers[i]=[]
// crossing reduction: barycentre sweeps
const pos=new Map();const index=()=>layers.forEach((l)=>l.forEach((id,i)=>pos.set(id,i)));index()
const sweep=(l,neigh)=>{
const key=new Map();l.forEach((id,i)=>{const ns=neigh(id);key.set(id,ns.length?ns.reduce((s,x)=>s+pos.get(x),0)/ns.length:i)})
const order=l.map((id,i)=>({id,i}));order.sort((a,b)=>key.get(a.id)-key.get(b.id)||a.i-b.i)
order.forEach((o,i)=>{l[i]=o.id});l.forEach((id,i)=>pos.set(id,i))
}
for(let it=0;it<4;it++){
for(let i=1;i<layers.length;i++)sweep(layers[i],(id)=>inc.get(id).map((p)=>p.from))
for(let i=layers.length-2;i>=0;i--)sweep(layers[i],(id)=>fwd(id).map((x)=>x.to))
}
for(let i=1;i<layers.length;i++)sweep(layers[i],(id)=>inc.get(id).map((p)=>p.from))
// coordinates
const up=(v)=>Math.ceil(v/grid-1e-9)*grid
let x=up(ox)
layers.forEach((l)=>{
let cursor=-Infinity,maxW=0
l.forEach((id)=>{
const n=byId.get(id),size=flowNodeSize(n),preds=inc.get(id)
let want=cursor===-Infinity?oy:cursor
if(preds.length){const ys=preds.map((p)=>flowPortPos(byId.get(p.from),"out",p.port).y);want=ys.reduce((s,v)=>s+v,0)/ys.length-(flowPortPos(n,"in").y-n.y)}
n.x=x;n.y=up(cursor===-Infinity?want:Math.max(want,cursor))
cursor=n.y+size.h+gapY;maxW=Math.max(maxW,size.w)
})
x=up(x+maxW+gapX)
})
let minY=Infinity;nodes.forEach((n)=>{minY=Math.min(minY,n.y)})
const shift=up(oy)-minY;if(shift)nodes.forEach((n)=>{n.y+=shift})
return graph
}
// ---- history: snapshots of the graph (viewport excluded, so undo never jumps the view)
function flowHistoryCreate(limit){
limit=limit>0?Math.floor(limit):100
let stack=[],idx=-1
const snap=(g)=>{const c=flowClone(g)||{};delete c.viewport;return JSON.stringify(c)}
return {
push(g){const s=snap(g);if(idx>=0&&stack[idx]===s)return false;stack=stack.slice(0,idx+1);stack.push(s);if(stack.length>limit)stack=stack.slice(stack.length-limit);idx=stack.length-1;return true},
// Overwrites the newest entry (used to coalesce a burst of edits to one node into a single undo step).
replace(g){if(idx<=0)return this.push(g);stack=stack.slice(0,idx+1);stack[idx]=snap(g);return true},
undo(){if(idx<=0)return null;idx--;return JSON.parse(stack[idx])},
redo(){if(idx>=stack.length-1)return null;idx++;return JSON.parse(stack[idx])},
canUndo(){return idx>0},
canRedo(){return idx<stack.length-1},
reset(g){stack=g?[snap(g)]:[];idx=stack.length-1},
size(){return stack.length}
}
}
// ---- clipboard
function flowCopy(graph,ids){
const want=new Set(ids||[])
const nodes=graph.nodes.filter((n)=>want.has(n.id)).map(flowClone)
const have=new Set(nodes.map((n)=>n.id))
return {flow_clip:1,nodes,edges:graph.edges.filter((e)=>have.has(e.from)&&have.has(e.to)).map(flowClone)}
}
// Pastes with fresh ids (edges between pasted nodes are kept). A Start is skipped when the graph already has one. Returns the new node ids.
function flowPaste(graph,clip,dx,dy){
if(!clip||!Array.isArray(clip.nodes))return []
dx=flowNum(dx,0);dy=flowNum(dy,0)
const map=new Map(),made=[]
clip.nodes.forEach((src)=>{
if(!flowIsObj(src)||graph.nodes.length>=FLOW_LIMITS.nodes)return
if(src.type==="start"&&flowHasStart(graph))return
const n=flowClone(src);n.id=flowNewId(graph,"n");n.x=flowNum(n.x,0)+dx;n.y=flowNum(n.y,0)+dy
graph.nodes.push(n);map.set(src.id,n.id);made.push(n.id)
})
;(clip.edges||[]).forEach((e)=>{if(map.has(e.from)&&map.has(e.to))flowConnect(graph,map.get(e.from),e.port,map.get(e.to))})
return made
}
// ---- (de)serialisation
// Fills defaults and coerces types so the editor can trust the shape. Unknown node types are kept (the validator reports them).
function flowNormalize(input){
if(!flowIsObj(input))throw new Error("The diagram must be a JSON object.")
if(flowIsObj(input.graph)&&!Array.isArray(input.nodes))input=input.graph
if(!Array.isArray(input.nodes))throw new Error("The diagram has no \"nodes\" list.")
if(input.edges!=null&&!Array.isArray(input.edges))throw new Error("The diagram's \"edges\" is not a list.")
if(input.schema!=null&&Number(input.schema)>FLOW_SCHEMA_VERSION)throw new Error("This diagram was made by a newer version (schema "+input.schema+").")
const s=flowIsObj(input.settings)?input.settings:{},L=FLOW_LIMITS
const g={schema:FLOW_SCHEMA_VERSION,settings:{shell:typeof s.shell==="string"?s.shell:"",run_timeout:flowClamp(Math.round(flowNum(s.run_timeout,1800)),L.run_timeout_min,L.run_timeout_max),max_visits:flowClamp(Math.round(flowNum(s.max_visits,200)),L.max_visits_min,L.max_visits_max),on_error:s.on_error==="continue"?"continue":"stop"},nodes:[],edges:[],viewport:{x:0,y:0,zoom:1}}
// Per-diagram script isolation: only an explicit override is stored; "inherit" (the app setting) is the absence of the key.
if(s.script_isolation==="sandboxed"||s.script_isolation==="allow")g.settings.script_isolation=s.script_isolation
input.nodes.forEach((raw)=>{
if(!flowIsObj(raw))throw new Error("A node is not an object.")
if(typeof raw.id!=="string"&&typeof raw.id!=="number")throw new Error("A node has no id.")
const t=FLOW_NODE_TYPES[raw.type]
const node={id:String(raw.id),type:String(raw.type||""),title:typeof raw.title==="string"?raw.title.slice(0,L.title_chars):(t?t.label:String(raw.type||"")),x:flowNum(raw.x,0),y:flowNum(raw.y,0),config:Object.assign(flowDefaultConfig(raw.type),flowIsObj(raw.config)?flowClone(raw.config):{})}
g.nodes.push(node)
})
;(input.edges||[]).forEach((raw)=>{
if(!flowIsObj(raw))throw new Error("A connection is not an object.")
g.edges.push({id:raw.id==null?"":String(raw.id),from:String(raw.from==null?"":raw.from),port:String(raw.port==null?"":raw.port),to:String(raw.to==null?"":raw.to)})
})
g.edges.forEach((e)=>{if(!e.id)e.id=flowNewId(g,"e")})
const v=flowIsObj(input.viewport)?input.viewport:{}
g.viewport={x:flowNum(v.x,0),y:flowNum(v.y,0),zoom:flowClamp(flowNum(v.zoom,1)||1,0.25,2)}
return g
}
function flowSerialize(graph){
const g=flowNormalize(flowClone(graph))
g.nodes.forEach((n)=>{n.x=Math.round(n.x*100)/100;n.y=Math.round(n.y*100)/100})
g.viewport={x:Math.round(g.viewport.x*100)/100,y:Math.round(g.viewport.y*100)/100,zoom:Math.round(g.viewport.zoom*1000)/1000}
return JSON.stringify(g)
}
function flowParse(text){
let data=text
if(typeof text==="string"){try{data=JSON.parse(text)}catch(e){throw new Error("The diagram is not valid JSON: "+e.message)}}
return flowNormalize(data)
}
// A linear chain as a straight-line diagram: start -> command -> command ... (one command node per step, joined on success).
function flowLinearToGraph(name,steps){
const g=flowNewGraph(),stepX=FLOW_GEOM.w+60
let prev=g.nodes[0],port="out"
;(Array.isArray(steps)?steps:[]).forEach((s,i)=>{
s=flowIsObj(s)?s:{command:String(s==null?"":s)}
const text=String(s.command==null?(s.text==null?"":s.text):s.command),label=String(s.label||"")
const node=flowAddNode(g,"command",prev.x+stepX,prev.y,{commands:[{text,command_id:s.command_id==null?null:s.command_id,src:String(s.command_src||s.src||""),label}]})
if(!node)return
node.title=flowTruncate(label||text.split("\n")[0]||("Step "+(i+1)),FLOW_LIMITS.title_chars)
flowConnect(g,prev.id,port,node.id)
prev=node;port="success"
})
return g
}
// True when the graph is just start -> command -> command ... on the success path (what the old linear runner can do).
function flowGraphIsLinear(graph){
const ns=((graph&&graph.nodes)||[]).filter((n)=>n.type!=="comment")
const start=ns.find((n)=>n.type==="start")
if(!start||ns.some((n)=>n.type!=="start"&&n.type!=="command"))return false
if(graph.edges.length!==ns.length-1)return false
let cur=start,port="out",count=1
for(;;){const outs=graph.edges.filter((e)=>e.from===cur.id);if(!outs.length)break;if(outs.length!==1||outs[0].port!==port)return false;cur=flowFindNode(graph,outs[0].to);if(!cur||cur.type!=="command")return false;port="success";count++;if(count>ns.length)return false}
return count===ns.length
}
if(typeof module!=="undefined"&&module.exports)module.exports={FLOW_CAT,FLOW_HOTBAR_DEFAULT,FLOW_HOTBAR_MAX,FLOW_TONE_NEG,FLOW_TONE_POS,flowCatalogItems,flowCatalogItem,flowCatalogSearch,flowHotbarClean,FLOW_SCHEMA_VERSION,FLOW_LIMITS,FLOW_ID_RE,FLOW_PORT_RE,FLOW_SETTINGS_DEFAULT,FLOW_CATEGORIES,FLOW_NODE_TYPES,FLOW_COMMENT_COLORS,FLOW_GEOM,flowClone,flowTruncate,flowSnap,flowFindNode,flowFindEdge,flowNewGraph,flowNewId,flowNodePorts,flowNodeSize,flowPortPos,flowEdgePath,flowGraphBounds,flowHitNode,flowPortTone,flowDefaultConfig,flowHasStart,flowAddNode,flowRemoveNodes,flowRemoveEdges,flowMoveNodes,flowConnectRefusal,flowConnect,flowAutoWireTwin,flowRenamePort,flowPruneEdges,flowReconcilePorts,flowNodeSummary,flowValidate,flowAutoLayout,flowHistoryCreate,flowCopy,flowPaste,flowNormalize,flowSerialize,flowParse,flowLinearToGraph,flowGraphIsLinear}
