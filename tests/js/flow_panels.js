// Chain diagrams: the node inspector (UI/js/components/flow-inspector.js) and the run panel (flow-run.js).
// Pure helpers are tested directly; the panels themselves run in a vm sandbox against a tiny fake DOM, a fake editor,
// a fake bridge and fake timers (debounced commits, port renames, the run dialog gates, polling and its backoff).
const fs=require("fs")
const path=require("path")
const vm=require("vm")
const ROOT=path.resolve(__dirname,"..","..")
const file=(...p)=>path.join(ROOT,...p)
const read=(...p)=>fs.readFileSync(file(...p),"utf8")
const RULES=read("UI","js","components","flow-rules.js")
const INSPECTOR=read("UI","js","components","flow-inspector.js")
const RUN=read("UI","js","components","flow-run.js")
const CSS=read("UI","css","flow-panels.css")
// The redesigned inspector: its typed-field renderer and the stylesheet of the header, tabs, fields and output preview.
const FIELDS=read("UI","js","components","flow-fields.js")
const CSS_FIELDS=read("UI","css","chains-fields.css")
const MODEL=fs.existsSync(file("UI","js","components","flow-model.js"))?read("UI","js","components","flow-model.js"):""
const EDITOR=fs.existsSync(file("UI","js","components","flow-editor.js"))?read("UI","js","components","flow-editor.js"):""
let passed=0,failed=0
function check(name,cond,detail){if(cond){passed++;return}failed++;console.log("  FAIL  "+name+(detail?"  ->  "+detail:""))}
function eq(name,a,b){check(name,JSON.stringify(a)===JSON.stringify(b),JSON.stringify(a)+" != "+JSON.stringify(b))}
// ---- fake DOM: just enough for the panels to mount, render strings and receive events
class FakeEl{
constructor(tag){
this.tagName=String(tag||"div").toUpperCase();this.children=[];this._html="";this._q={};this.dataset={};this.style={};this.listeners={};this.parentNode=null
this.textContent="";this.value="";this.scrollTop=0;this.scrollHeight=0;this.clientHeight=0;this.disabled=false;this.checked=false;this.className=""
const set=new Set()
this.classList={set:set,add:(c)=>set.add(c),remove:(c)=>set.delete(c),contains:(c)=>set.has(c),toggle:(c,on)=>{const want=on===undefined?!set.has(c):!!on;if(want)set.add(c);else set.delete(c);return want}}
}
get innerHTML(){return this._html}
set innerHTML(v){this._html=String(v);this._q={}}
insertAdjacentHTML(pos,html){this._html+=String(html)}
appendChild(c){c.parentNode=this;this.children.push(c);return c}
removeChild(c){this.children=this.children.filter((x)=>x!==c);c.parentNode=null;return c}
addEventListener(type,fn){(this.listeners[type]=this.listeners[type]||[]).push(fn)}
removeEventListener(type,fn){this.listeners[type]=(this.listeners[type]||[]).filter((x)=>x!==fn)}
dispatch(type,ev){(this.listeners[type]||[]).slice().forEach((fn)=>fn(ev))}
// One stable stand-in element per selector until the markup is replaced.
querySelector(sel){return this._q[sel]||(this._q[sel]=new FakeEl("div"))}
querySelectorAll(){return []}
contains(){return true}
closest(){return null}
focus(){}
setSelectionRange(){}
getBoundingClientRect(){return {width:340,height:400,left:0,top:0}}
get childElementCount(){return 0}
get firstElementChild(){return null}
}
function makeSandbox(){
const timers=[]
let timerId=0
const document={body:new FakeEl("body"),activeElement:null,createElement:(t)=>new FakeEl(t),listeners:{},addEventListener(type,fn){(this.listeners[type]=this.listeners[type]||[]).push(fn)},removeEventListener(type,fn){this.listeners[type]=(this.listeners[type]||[]).filter((x)=>x!==fn)},execCommand:()=>false}
const sandbox={module:{exports:{}},console:console,document:document,Promise:Promise,Date:Date,JSON:JSON,Math:Math,
setTimeout:(fn,ms)=>{timers.push({id:++timerId,fn:fn,ms:ms});return timerId},
clearTimeout:(id)=>{const i=timers.findIndex((t)=>t.id===id);if(i>=0)timers.splice(i,1)}}
vm.createContext(sandbox)
const api={}
const load=(src,name)=>{sandbox.module.exports={};vm.runInContext(src,sandbox,{filename:name});Object.assign(api,sandbox.module.exports)}
const snapshot=()=>{const out={};Object.keys(sandbox).forEach((k)=>{if(typeof sandbox[k]==="function")out[k]=sandbox[k]});return out}
// fire(): run the next pending timer. flushZero(): run the setTimeout(fn,0) ones (focus calls, deferred selection reads).
return {sandbox:sandbox,document:document,timers:timers,load:load,api:api,snapshot:snapshot,fire:()=>{const t=timers.shift();if(t)t.fn();return t},
flushZero:()=>{for(let i=timers.length-1;i>=0;i--)if(!timers[i].ms){const t=timers.splice(i,1)[0];t.fn()}}}
}
const tick=()=>new Promise((resolve)=>setImmediate(resolve))
const settle=async()=>{for(let i=0;i<6;i++)await tick();box.flushZero();for(let i=0;i<3;i++)await tick()}
// ---- loading: the files share one global scope in the page, so they must load together without a clash
const box=makeSandbox()
let loadError=""
const redeclared=[]
let before={},modelFns={},panelFns={}
function loadTracked(src,name){
const prev=box.snapshot()
box.load(src,name)
const now=box.snapshot()
Object.keys(prev).forEach((k)=>{if(now[k]!==prev[k]&&["setTimeout","clearTimeout","Promise","Date"].indexOf(k)===-1)redeclared.push(name+" redefines "+k)})
return now
}
try{
before=box.snapshot()
if(MODEL)loadTracked(MODEL,"flow-model.js")
modelFns=box.snapshot()
loadTracked(RULES,"flow-rules.js")
loadTracked(FIELDS,"flow-fields.js")
loadTracked(INSPECTOR,"flow-inspector.js")
panelFns=loadTracked(RUN,"flow-run.js")
}catch(err){loadError=String(err&&err.message?err.message:err)}
// A const/let declared by two files is a SyntaxError for the second one, exactly as in the page.
check("load: flow-model, flow-rules, flow-inspector and flow-run share one global scope",loadError==="",loadError)
check("globals: no function of an earlier file is redefined",redeclared.length===0,redeclared.join("; "))
const P=box.api
const mine=Object.keys(panelFns).filter((k)=>!modelFns[k]).concat(Object.keys(P).filter((k)=>typeof P[k]!=="function"&&!/^FLOW_(SCHEMA_VERSION|LIMITS|ID_RE|PORT_RE|SETTINGS_DEFAULT|CATEGORIES|NODE_TYPES|COMMENT_COLORS|GEOM)$/.test(k)))
check("globals: every panel global is flow*/FLOW_*/fi*/FI_*",mine.length>80&&mine.every((n)=>/^(flow[A-Z]|FLOW_|fi[A-Z]|FI_)/.test(n)),mine.filter((n)=>!/^(flow[A-Z]|FLOW_|fi[A-Z]|FI_)/.test(n)).join(","))
// flow-editor.js keeps its helpers inside flowEditorCreate; its few globals must not collide with ours either.
const editorGlobals=(EDITOR.match(/^(?:const|let|var|function)\s+(?:flow[A-Z]\w*|FLOW_\w+)/gm)||[]).map((m)=>m.replace(/^\w+\s+/,""))
check("globals: no clash with flow-editor.js",mine.every((n)=>editorGlobals.indexOf(n)===-1),mine.filter((n)=>editorGlobals.indexOf(n)!==-1).join(","))
;[["flow-rules.js",RULES],["flow-inspector.js",INSPECTOR],["flow-run.js",RUN]].forEach((f)=>{
check(f[0]+": exports for node at the end",/if\(typeof module!=="undefined"&&module\.exports\)module\.exports=\{[^}]+\}\s*$/.test(f[1]))
check(f[0]+": LF line endings, no localStorage, no eval",f[1].indexOf("\r")===-1&&!/localStorage|sessionStorage/.test(f[1])&&!/\beval\(|new Function\(/.test(f[1]))
})
check("rules: no DOM access in the pure file",!/\bdocument\b|\bwindow\b/.test(RULES))
const XSS="\"><img src=x onerror=alert(1)>'<script>x</script>"
const safe=(html)=>typeof html==="string"&&html.indexOf("<img")===-1&&html.indexOf("<script")===-1&&html.indexOf("onerror=alert(1)>")===-1&&html.indexOf("x</script>")===-1
// ---- inspector: small helpers
eq("fiSet / fiGet: nested paths",(()=>{const o={commands:[{text:"a"}]};P.fiSet(o,"commands.0.text","b");P.fiSet(o,"branches.1.name","x");return [P.fiGet(o,"commands.0.text"),P.fiGet(o,"branches.1.name"),Array.isArray(o.branches),P.fiGet(o,"nope.deep")]})(),["b","x",true,null].map((v,i)=>i===3?undefined:v))
check("fiSet: never writes through the prototype",(()=>{const o={};P.fiSet(o,"__proto__.polluted","x");P.fiSet(o,"constructor.prototype.polluted","x");return ({}).polluted===undefined})())
eq("fiMove: reorders inside bounds only",(()=>{const l=["a","b","c"];const r=[P.fiMove(l,0,1),P.fiMove(l,2,1),P.fiMove(l,0,-1)];return [l,r]})(),[["b","a","c"],[true,false,false]])
eq("fiClamp",[P.fiClamp("5",1,10),P.fiClamp("0",1,10),P.fiClamp("99",1,10),P.fiClamp("abc",1,10),P.fiClamp("",0,3600,5)],[5,1,10,1,5])
eq("fiNodePorts: the spec table",["start","command","script","decision","parse","set","foreach","wait","approval","output","subchain","end","comment"].map((t)=>P.fiNodePorts({type:t,config:t==="script"?{branches:["alive","down"]}:t==="decision"?{branches:[{name:"web"},{name:"ssh"}],else:"none"}:{}})),[["out"],["success","fail"],["alive","down","error"],["web","ssh","none"],["out","nomatch"],["out"],["item","done"],["out"],["approved","rejected"],["out"],["success","fail"],[],[]])
eq("command info: placeholders, vars, raw, destructive",P.fiCommandInfo("sudo nmap -p ${ports} {IPv4} ${raw:extra} {ipv4}"),{empty:false,placeholders:["IPv4"],vars:["ports"],raw:["extra"],destructive:true,long:false})
eq("command info: empty and too long",[P.fiCommandInfo("  ").empty,P.fiCommandInfo("x".repeat(4097)).long,P.fiCommandInfo("ping {IPv4}").destructive],[true,true,false])
const chips=P.fiCommandChipsHtml("rm -rf {Dir} ${name} ${raw:x}")
check("command chips: destructive warning, placeholder, var and unquoted warning",/fi-chip-danger[^>]*>Looks destructive/.test(chips)&&chips.indexOf("{Dir}")>0&&chips.indexOf("${name}")>0&&/fi-chip-warn[^>]*>unquoted \$\{raw:x\}/.test(chips))
check("command chips: a clean line has no warning chip",!/fi-chip-danger|fi-chip-warn/.test(P.fiCommandChipsHtml("ping -c 2 {IPv4}")))
check("command chips: placeholder names are escaped",safe(P.fiCommandChipsHtml("echo ${"+XSS+"} ${raw:<img src=x>}")))
eq("line numbers / line count",[P.fiLineNumbers(""),P.fiLineNumbers("a\nb\n"),P.fiLineCount("a\nb")],["1","1\n2\n3",2])
eq("byte length is UTF-8",[P.fiByteLength("abc"),P.fiByteLength("é"),P.fiByteLength("中"),P.fiByteLength("😀")],[3,2,3,4])
check("code stats: over the 64 KB limit",P.fiCodeStats("x".repeat(65537)).over===true&&P.fiCodeStats("x").over===false&&/^1 line - 1 B/.test(P.fiCodeStats("x").text))
// ---- inspector: code editor keys
const key=(value,s,e,k,shift,unit)=>{const ed=P.fiEditKey(value,s,e,k,!!shift,unit);return ed?[P.fiApplyEdit(value,ed),ed.selStart,ed.selEnd]:null}
eq("editor: Tab inserts one indent at the caret",key("ab",1,1,"Tab"),["a    b",5,5])
eq("editor: Tab replaces a one-line selection",key("abc",1,2,"Tab"),["a    c",5,5])
eq("editor: Tab indents every selected line",key("a\nb\nc",0,3,"Tab"),["    a\n    b\nc",4,11])
eq("editor: a selection ending at a line start leaves that line alone",key("a\nb\nc",0,4,"Tab"),["    a\n    b\nc",4,12])
eq("editor: Shift+Tab outdents the current line",key("    x",4,4,"Tab",true),["x",0,0])
eq("editor: Shift+Tab removes at most one unit, or one tab",[key("      x",6,6,"Tab",true),key("\tx",1,1,"Tab",true),key("x",1,1,"Tab",true)],[["  x",2,2],["x",0,0],["x",1,1]])
eq("editor: Shift+Tab outdents a block",key("    a\n  b\nc",0,10,"Tab",true),["a\nb\nc",0,4])
eq("editor: bash uses two spaces",key("x",0,0,"Tab",false,"  "),["  x",2,2])
eq("editor: Enter keeps the indentation",key("    foo",7,7,"Enter"),["    foo\n    ",12,12])
eq("editor: Enter indents after a block opener",[key("if x:",5,5,"Enter"),key("f() {",5,5,"Enter"),key("if a; then",10,10,"Enter"),key("x = 1",5,5,"Enter")].map((r)=>r[0]),["if x:\n    ","f() {\n    ","if a; then\n    ","x = 1\n"])
eq("editor: Enter in the middle of a line",key("  ab",3,3,"Enter"),["  a\n  b",6,6])
check("editor: other keys are left to the browser",P.fiEditKey("x",0,0,"a",false)===null)
// ---- inspector: names, branches, commands
eq("branch names: rule",[P.fiBranchNameError("alive",[]),!!P.fiBranchNameError("",[]),!!P.fiBranchNameError("has space",[]),!!P.fiBranchNameError("x".repeat(25),[]),!!P.fiBranchNameError("dup",["dup"]),P.fiBranchNameError("a-b_9",["dup"])],["",true,true,true,true,""])
eq("unique names",[P.fiUniqueName("branch",[]),P.fiUniqueName("branch",["branch"]),P.fiUniqueName("branch",["branch","branch2"])],["branch","branch2","branch3"])
eq("branches named in a script",[P.fiBranchesFromCode("print(json.dumps({\"branch\": \"alive\" if up else \"down\"}))\necho '{\"branch\":\"down\"}'\n@{ branch = 'web' }\nbranch=\"error\""),P.fiBranchesFromCode("")],[["alive","down","web"],[]])
const ROWS=[{id:1,src:"db",title:"Ping sweep",command:"ping -c 2 {IPv4}",category:"Recon"},{id:2,src:"db",title:"Nmap full",command:"nmap -p- {IPv4}\nsecond",category:"Scan"},{id:3,src:"db",title:"Empty",command:"  ",category:"X"}]
eq("command picker: search over title, category and command; blank commands dropped",[P.fiFilterCommands(ROWS,"").map((r)=>r.id),P.fiFilterCommands(ROWS,"SCAN").map((r)=>r.id),P.fiFilterCommands(ROWS,"ipv4 ping").map((r)=>r.id),P.fiFilterCommands(ROWS,"zzz").length,P.fiFilterCommands(null,"").length,P.fiFilterCommands(ROWS,"",1).length],[[1,2],[2],[1],0,0,1])
eq("issues: only this node's",P.fiNodeIssues({errors:[{node:"n2",message:"Empty command node"},{node:"n3",message:"other"}],warnings:[{node:"n2",code:"destructive"},{node:null,message:"graph"}]},"n2"),{errors:["Empty command node"],warnings:["destructive"]})
check("issues: html is escaped",safe(P.fiIssuesHtml({errors:[{node:"n",message:XSS}],warnings:[{node:"n",message:XSS}]},"n"))&&/fi-issue-error/.test(P.fiIssuesHtml({errors:[{node:"n",message:"x"}]},"n")))
// ---- inspector: forms
const CTX={catalog:{languages:{python:true,bash:true,powershell:false},script_templates:[],shells:[{id:"bash",label:"Bash"}],parsers:["nmap","ping"]},notes:["Recon notes"],reports:[{id:7,title:"Q3 pentest"}],chains:[{playbook_id:1,name:"Self"},{playbook_id:2,name:"Other",caller:"other"}],selfId:1,test:{},menuOpen:true}
const NODES={
start:{trigger:"manual"},
command:{commands:[{text:"ping -c 2 {IPv4}",command_id:4,src:"db",label:"Ping"},{text:"rm -rf /tmp/x",command_id:null,src:"",label:""}],mode:"sequence",stop_on_fail:true,timeout:300,shell:""},
script:{language:"powershell",code:"print('{\"branch\": \"alive\"}')\n",branches:["out"],timeout:60},
decision:{branches:[{name:"alive",match:"all",conditions:[{source:"output",field:"",op:"contains",value:"ttl=",ci:true},{source:"match_count",field:"open",op:"ge",value:"1",ci:true}]}],else:"down"},
parse:{mode:"regex",source:"stdout",pattern:"(\\d+)/tcp",flags:"i",tool:"nmap",path:"",assign:[{var:"port",from:"group:1"}],var:"parsed"},
set:{assign:[{var:"name",value:"text ${last.stdout}"}]},
foreach:{items:"${parsed.ports}",item_var:"item",index_var:"index",max_items:50,split:"lines"},
wait:{seconds:5},
approval:{message:"Continue with the exploit step?",timeout:0},
output:{action:"note_append",note_name:"Recon notes",report_id:null,title:"",severity:"info",content:"${last.stdout}"},
subchain:{playbook_id:2,pass_vars:true},
end:{status:"success",message:""},
comment:{text:"note",color:"yellow",w:220,h:120}
}
const form=(type,cfg,ctx)=>P.fiFormHtml({id:"n1",type:type,title:"T",config:cfg===undefined?NODES[type]:cfg},ctx||CTX)
check("forms: every node type renders with a title field",Object.keys(NODES).every((t)=>{const h=form(t);return h.indexOf('data-k="@title"')>0&&h.indexOf("no settings here")===-1}))
const KEYS={start:["trigger"],command:["commands.0.text","commands.0.label","commands.1.text","mode","stop_on_fail","timeout","shell"],script:["language","code","timeout"],decision:["branches.0.match","branches.0.conditions.0.op","branches.0.conditions.0.value","branches.0.conditions.0.ci","branches.0.conditions.1.field"],parse:["mode","source","pattern","flags","assign.0.var","assign.0.from","var"],set:["assign.0.var","assign.0.value"],foreach:["items","split","item_var","index_var","max_items"],wait:["seconds"],approval:["message","timeout"],output:["action","note_name","content"],subchain:["playbook_id","pass_vars"],end:["status","message"],comment:["text","color","w","h"]}
Object.keys(KEYS).forEach((t)=>{const h=form(t);const missing=KEYS[t].filter((k)=>h.indexOf('data-k="'+k+'"')===-1);check("form "+t+": binds every config key of the spec",missing.length===0,missing.join(","))})
check("form command: pick / type buttons, reorder and remove per row",/data-act="cmd-pick"/.test(form("command"))&&/data-act="cmd-type"/.test(form("command"))&&(form("command").match(/data-act="cmd-up"/g)||[]).length===2&&/data-act="cmd-del" data-i="1"/.test(form("command")))
check("form command: first row cannot move up, last cannot move down",/data-act="cmd-up" data-i="0"[^>]*disabled/.test(form("command"))&&/data-act="cmd-down" data-i="1"[^>]*disabled/.test(form("command"))&&!/data-act="cmd-down" data-i="0"[^>]*disabled/.test(form("command")))
check("form command: the destructive line carries the warning chip, the library row its badge",(()=>{const h=form("command");const second=h.slice(h.indexOf('data-chips="1"'));return /Looks destructive/.test(second)&&!/Looks destructive/.test(h.slice(h.indexOf('data-chips="0"'),h.indexOf('data-chips="1"')))&&/fi-chip-lib/.test(h)})())
check("form command: sequence shows stop-on-fail, parallel hides it",/data-k="stop_on_fail"/.test(form("command"))&&!/data-k="stop_on_fail"/.test(form("command",Object.assign({},NODES.command,{mode:"parallel"}))))
check("form command: add buttons disable at 20 commands",/data-act="cmd-pick"[^>]*disabled/.test(form("command",{commands:Array.from({length:20},()=>({text:"x"})),mode:"sequence"})))
check("form command: shell select from the catalog, text field without one",/<select[^>]*data-k="shell"/.test(form("command"))&&/<input[^>]*data-k="shell"/.test(form("command",undefined,{catalog:{}})))
const scriptForm=form("script")
check("form script: code editor with gutter, no spellcheck, no wrap",/<pre class="fi-code-gutter"[^>]*>1\n2<\/pre>/.test(scriptForm)&&/<textarea class="fi-code-area"[^>]*wrap="off"[^>]*spellcheck="false"/.test(scriptForm))
check("form script: unavailable language is marked",/PowerShell \(not found on this computer\)/.test(scriptForm)&&!/Python \(not found/.test(scriptForm)&&/powershell was not found/.test(scriptForm))
check("form script: templates menu falls back to the built-in examples",(scriptForm.match(/data-act="tpl" data-i=/g)||[]).length===3&&/Is the host alive\? \(Bash\)/.test(scriptForm))
check("form script: branch rows rename through data-rename, error port is fixed",/data-rename="branches\.0"/.test(scriptForm)&&/fi-port-fixed/.test(scriptForm)&&/data-act="sbranch-del"[^>]*disabled/.test(scriptForm))
check("form script: offers the branches the code mentions",/data-act="sbranch-detect"[^>]*>Add from code: alive</.test(scriptForm))
check("form script: help documents stdin payload and the result line",/LOYA_INPUT_FILE/.test(scriptForm)&&/&quot;branch&quot;: &quot;alive&quot;/.test(scriptForm)&&/LAST line of stdout/.test(scriptForm))
const decForm=form("decision")
check("form decision: live sentence preview",/data-preview>If output contains &#39;ttl=&#39; and matches of \/open\/ &gt;= 1 -&gt; alive\nOtherwise -&gt; down</.test(decForm),decForm.slice(decForm.indexOf("data-preview"),decForm.indexOf("data-preview")+160))
check("form decision: ALL/ANY switch, branch and else names rename",/data-k="branches\.0\.match" data-v="all"/.test(decForm)&&/data-k="branches\.0\.match" data-v="any"/.test(decForm)&&/data-rename="branches\.0\.name" value="alive"/.test(decForm)&&/data-rename="else" value="down"/.test(decForm))
check("form decision: operator list is limited to the source",(()=>{const h=P.fiCondHtml({source:"exit_code",op:"eq",value:"0"},0,0,1);const ops=h.slice(h.indexOf('data-k="branches.0.conditions.0.op"'));return /value="eq"/.test(ops)&&/value="le"/.test(ops)&&!/value="contains"/.test(ops)})())
check("form decision: field only when the source needs one, value only when the op needs one",(()=>{const a=P.fiCondHtml({source:"output",op:"contains",value:"x"},0,0,1),b=P.fiCondHtml({source:"var",field:"n",op:"is_empty"},0,0,1),c=P.fiCondHtml({source:"host_up",op:"is_true"},0,0,1);return !/\.field"/.test(a)&&/\.value"/.test(a)&&/\.field"/.test(b)&&!/\.value"/.test(b)&&!/\.field"/.test(c)&&!/\.value"/.test(c)&&!/\.ci"/.test(c)&&/\.ci"/.test(a)})())
check("form decision: a broken condition shows its problem",/data-cond-err="0\.0">Enter a number/.test(P.fiCondHtml({source:"exit_code",op:"eq",value:"abc"},0,0,1)))
check("form decision: test box",/data-test="stdout"/.test(decForm)&&/data-test="exit"/.test(decForm)&&/data-test-out/.test(decForm))
const testHtml=P.fiTestHtml(NODES.decision,{stdout:"64 bytes ttl=64\n22/tcp open ssh",exit:"0"})
check("test box: names the branch taken with per-condition true/false",/would go to <b class="fi-mono">alive<\/b>/.test(testHtml)&&(testHtml.match(/fi-test-flag yes">true</g)||[]).length===2,testHtml)
const testElse=P.fiTestHtml(NODES.decision,{stdout:"request timed out",exit:"1"})
check("test box: falls to the else branch and shows the false condition",/<b class="fi-mono">down<\/b> \(no branch matched\)/.test(testElse)&&/fi-test-flag no">false</.test(testElse))
check("test box: empty sample asks for input; sample output is escaped",/Paste some output/.test(P.fiTestHtml(NODES.decision,{}))&&safe(P.fiTestHtml({branches:[{name:"a",match:"all",conditions:[{source:"stdout",op:"not_empty"}]}],else:"e"},{stdout:XSS,exit:"0"})))
check("form parse: regex / tool / jsonpath modes",/data-k="pattern"/.test(form("parse"))&&/data-k="tool"/.test(form("parse",Object.assign({},NODES.parse,{mode:"tool"})))&&/data-k="path"/.test(form("parse",Object.assign({},NODES.parse,{mode:"jsonpath"})))&&!/data-k="pattern"/.test(form("parse",Object.assign({},NODES.parse,{mode:"tool"}))))
check("form parse: a dangerous regex is reported",/data-regex-err>The regex nests/.test(form("parse",Object.assign({},NODES.parse,{pattern:"(a+)+"}))))
check("form output: note picker and report picker from the bridge lists, text fallback without",/data-chg="note-pick"/.test(form("output"))&&/<select[^>]*data-k="report_id"[^>]*>[\s\S]*Q3 pentest/.test(form("output",Object.assign({},NODES.output,{action:"finding_draft"})))&&/<input[^>]*data-k="report_id"/.test(form("output",Object.assign({},NODES.output,{action:"evidence"}),{catalog:{}}))&&!/data-chg="note-pick"/.test(form("output",undefined,{catalog:{}})))
check("form output: fields follow the action",/data-k="severity"/.test(form("output",Object.assign({},NODES.output,{action:"finding_draft"})))&&!/data-k="severity"/.test(form("output"))&&!/data-k="note_name"/.test(form("output",Object.assign({},NODES.output,{action:"notify"}))))
check("form subchain: lists other chains, never itself",/>Other  \/other</.test(form("subchain"))&&!/>Self</.test(form("subchain")))
check("form comment: colours",/value="yellow" selected/.test(form("comment"))&&/value="pink"/.test(form("comment")))
check("forms: unknown type degrades to the title only",/no settings here/.test(form("mystery",{})))
// every string a graph can carry is escaped in every form
const poison=(v)=>typeof v==="string"?XSS:Array.isArray(v)?v.map(poison):v&&typeof v==="object"?Object.keys(v).reduce((o,k)=>{o[k]=poison(v[k]);return o},{}):v
Object.keys(NODES).forEach((t)=>{
const h=P.fiFormHtml({id:"n1",type:t,title:XSS,config:poison(NODES[t])},{catalog:{languages:{},script_templates:[{id:XSS,language:XSS,name:XSS,description:XSS,code:XSS}],shells:[{id:XSS,label:XSS}],parsers:[XSS]},notes:[XSS],reports:[{id:1,title:XSS}],chains:[{playbook_id:9,name:XSS,caller:XSS}],selfId:1,test:{stdout:XSS,stderr:XSS,exit:XSS},menuOpen:true,testOpen:true})
check("form "+t+": hostile strings never reach the markup unescaped",safe(h),h.slice(Math.max(0,h.indexOf("<img")-80),h.indexOf("<img")+40))
})
check("inspector head: type label and id are escaped",safe(P.fiHeadHtml({id:XSS,type:XSS},{node_types:{}}))&&/Inspector/.test(P.fiHeadHtml(null)))
// ---- run: pure helpers
eq("backoff: 700 ms beat, doubling to a 10 s cap",[0,1,2,3,4,5,50].map(P.flowRunBackoff),[700,1400,2800,5600,10000,10000,10000])
eq("backoff: junk counts as no failure",[P.flowRunBackoff(undefined),P.flowRunBackoff(-3),P.flowRunBackoff("x")],[700,700,700])
eq("final states",["running","paused","waiting_approval","done","failed","cancelled","timeout",""].map(P.flowRunIsFinal),[false,false,false,true,true,true,true,false])
eq("durations",[P.flowRunDuration(450),P.flowRunDuration(1500),P.flowRunDuration(12000),P.flowRunDuration(65000),P.flowRunDuration(3720000),P.flowRunDuration(-1),P.flowRunDuration("x")],["450 ms","1.5 s","12 s","1m 05s","1h 02m","",""])
eq("elapsed: running uses now, finished uses ended_at",[P.flowRunElapsedMs({started_at:"2026-01-01T00:00:00+00:00"},Date.parse("2026-01-01T00:00:05+00:00")),P.flowRunElapsedMs({started_at:"2026-01-01T00:00:00+00:00",ended_at:"2026-01-01T00:01:00+00:00"},0),P.flowRunElapsedMs({},0)],[5000,60000,null])
eq("error text",[P.flowRunErrorText(new Error("boom")),P.flowRunErrorText("plain"),P.flowRunErrorText(null,"fallback"),P.flowRunErrorText({})],["boom","plain","fallback","Something went wrong"])
const EV=(seq,text,node,level)=>({seq:seq,ts:"2026-01-01T10:00:0"+(seq%10)+"+00:00",node:node||null,level:level||"info",text:text})
const S1={run_id:"r1",playbook_id:5,name:"Recon",mode:"run",state:"running",reason:"",source:"flow",target:"lab-01",started_at:"2026-01-01T10:00:00+00:00",ended_at:"",current:"n2",nodes:{n1:{state:"success",visits:1},n2:{state:"running",visits:1},n3:{state:"pending",visits:0}},edges_taken:["e1"],events:[EV(1,"Run started"),EV(2,"Running ping","n2")],approval:null,vars:{},seq:2}
eq("last seq",[P.flowRunLastSeq(S1),P.flowRunLastSeq({}),P.flowRunLastSeq(null)],[2,0,0])
eq("last seq: the status counter wins when node changes moved it past the last event",[P.flowRunLastSeq(Object.assign({},S1,{seq:9})),P.flowRunLastSeq(Object.assign({},S1,{seq:1})),P.flowRunLastSeq({seq:"x"})],[9,2,0])
const merged=P.flowRunMergeStatus(S1,Object.assign({},S1,{state:"done",events:[EV(2,"dup","n2"),EV(3,"Done")]}))
eq("merge: new events are appended once, the rest is replaced",[merged.events.map((e)=>e.seq),merged.state,merged.events[1].text],[[1,2,3],"done","Running ping"])
eq("merge: another run starts a fresh log",P.flowRunMergeStatus(S1,{run_id:"r2",events:[EV(1,"x")]}).events.length,1)
eq("merge: caps the log, tolerates junk",[P.flowRunMergeStatus({run_id:"r",events:Array.from({length:2000},(_,i)=>EV(i+1,"e"))},{run_id:"r",events:[EV(2001,"new")]}).events.length,P.flowRunMergeStatus(S1,null)===S1,P.flowRunMergeStatus(null,{run_id:"r"}).events.length,Object.keys(P.flowRunMergeStatus(null,{run_id:"r"}).nodes).length],[2000,true,0,0])
// run_status(run_id,since) may send a node's output only when that node changed: earlier output must survive the merge
const O1=Object.assign({},S1,{nodes:{n1:{state:"success",seq:1,output:{stdout:"one"}},n2:{state:"running",seq:2,output:{stdout:"par"}}}})
const O2=P.flowRunMergeStatus(O1,Object.assign({},S1,{nodes:{n1:{state:"success",seq:1},n2:{state:"success",seq:5,output:{stdout:"partial done"}},n3:{state:"running",seq:6}}}))
eq("merge: output of unchanged nodes is kept, changed output replaces",[O2.nodes.n1.output.stdout,O2.nodes.n2.output.stdout,O2.nodes.n2.state,O2.nodes.n3.state,O2.nodes.n3.output],["one","partial done","success","running",undefined])
eq("merge: nodes left out of a partial status are kept",P.flowRunMergeStatus(O1,Object.assign({},S1,{nodes:{n2:{state:"success",seq:7}}})).nodes.n1.output.stdout,"one")
eq("merge: a full status still replaces everything it carries",P.flowRunMergeStatus(O1,Object.assign({},S1,{nodes:{n1:{state:"success",output:{stdout:"new"}}}})).nodes.n1.output.stdout,"new")
eq("merge: another run never inherits output",P.flowRunMergeStatus(O1,{run_id:"other",nodes:{n1:{state:"pending"}}}).nodes.n1.output,undefined)
const TITLES={n1:{title:"Start",type:"start"},n2:{title:"Ping host",type:"command"},n3:{title:"Alive?",type:"decision"}}
const NOW=Date.parse("2026-01-01T10:00:12+00:00")
const v1=P.flowRunStatusView(S1,NOW,TITLES)
eq("status view: a pause that waits for the node boundary reads Pausing... and cannot be paused again",(()=>{const v=P.flowRunStatusView(Object.assign({},S1,{pausing:true}),NOW,TITLES);const p=P.flowRunStatusView(Object.assign({},S1,{pausing:true,state:"paused"}),NOW,TITLES);const d=P.flowRunStatusView(Object.assign({},S1,{pausing:true,state:"done"}),NOW,TITLES);return [v.label,v.pausing,v.canPause,v.canStop,p.label,p.canResume,d.pausing,v1.pausing,v1.canPause]})(),["Pausing...",true,false,true,"Paused",true,false,false,true])
eq("issue text: an open fail port spells out the consequence, once",[P.flowIssueText({code:"port_unconnected",message:"Ping: nothing is connected to 'fail'."}),P.flowIssueText({code:"port_unconnected",message:"X: nothing is connected to 'error'."}),P.flowIssueText({code:"port_unconnected",message:"Output \"fail\" of \"Ping\" is not connected."}).indexOf(P.FLOW_FAIL_PORT_HINT)>0,P.flowIssueText({code:"port_unconnected",message:"a 'fail' "+P.FLOW_FAIL_PORT_HINT}).split(P.FLOW_FAIL_PORT_HINT).length,P.flowIssueText(null),P.flowIssueText({code:"c"})],["Ping: nothing is connected to 'fail'. A failed command stops the run unless its fail port is connected or the diagram's On error setting is Continue.","X: nothing is connected to 'error'.",true,2,"","c"])
check("inspector: the node's own warning carries the hint",P.fiNodeIssues({warnings:[{node:"n2",code:"port_unconnected",message:"Ping: nothing is connected to 'fail'."}]},"n2").warnings[0].indexOf("On error setting is Continue")>0)
check("inspector: output content says both kinds of value work",/\{Placeholders\} are filled from the live target and \$\{values\} from the chain/.test(P.fiFormHtml({id:"n",type:"output",title:"",config:{action:"notify",content:""}},{catalog:{}})))
eq("status view: running",[v1.cls,v1.label,v1.sub,v1.active,v1.final,v1.canPause,v1.canResume,v1.canStop,v1.percent,v1.approval],["running","Running","Ping host - 12 s - on lab-01",true,false,true,false,true,33,null])
const vp=P.flowRunStatusView(Object.assign({},S1,{state:"paused"}),NOW,TITLES)
eq("status view: paused offers Resume",[vp.cls,vp.label,vp.canPause,vp.canResume,vp.canStop],["paused","Paused",false,true,true])
const va=P.flowRunStatusView(Object.assign({},S1,{state:"waiting_approval",approval:{node:"n3",message:"Continue?"}}),NOW,TITLES)
eq("status view: approval prompt",[va.label,va.approval,va.canPause],["Waiting for approval",{node:"n3",message:"Continue?",title:"Alive?"},false])
const vd=P.flowRunStatusView(Object.assign({},S1,{state:"done",ended_at:"2026-01-01T10:01:05+00:00",current:null,nodes:{n1:{state:"success"},n2:{state:"success"},n3:{state:"skipped"}}}),NOW,TITLES)
eq("status view: finished",[vd.cls,vd.label,vd.sub,vd.final,vd.canStop,vd.canPause,vd.percent],["done","Finished","2 ok, 1 skipped - 1m 05s - on lab-01",true,false,false,100])
eq("status view: failed / stopped / timeout with the reason",["failed","cancelled","timeout"].map((st)=>{const v=P.flowRunStatusView(Object.assign({},S1,{state:st,reason:"locked",ended_at:"2026-01-01T10:00:02+00:00"}),NOW,TITLES);return [v.cls,v.label,/locked$/.test(v.sub)]}),[["failed","Failed",true],["stopped","Stopped",true],["failed","Timed out",true]])
const vdry=P.flowRunStatusView({mode:"dry",state:"done",nodes:{n1:{state:"planned"},n2:{state:"planned"}},started_at:"2026-01-01T10:00:00+00:00",ended_at:"2026-01-01T10:00:00+00:00"},NOW,TITLES)
eq("status view: dry run says nothing was executed and has no pause",[vdry.dry,vdry.label,/2 nodes would run - nothing was executed/.test(vdry.sub),vdry.canPause,vdry.canResume],[true,"Dry run finished",true,false,false])
eq("status view: empty status",[P.flowRunStatusView(null).label,P.flowRunStatusView(null).active,P.flowRunStatusView({}).canStop],["Starting",false,false])
// ---- run: plan -> dialog model
const PLAN={target:{name:"lab-01",values:{ipv4:"10.0.0.5"}},commands:[{node:"n2",title:"Ping host",text:"ping -c 2 {IPv4}",resolved:"ping -c 2 10.0.0.5",missing:[],destructive:false},{node:"n4",title:"Scan",text:"sudo nmap {IPv4}",resolved:"sudo nmap 10.0.0.5",missing:[],destructive:true},{node:"n4",title:"Scan",text:"nikto -h {URL}",resolved:"nikto -h {URL}",missing:["URL"],destructive:false}],scripts:[{node:"n5",title:"Decide",language:"python",lines:12}],approvals:1,ai_made:false,needs_review:false,errors:[],warnings:[{node:"n4",code:"destructive",message:"Destructive command"}],blocked:"",missing:["URL"]}
const m1=P.flowRunPlanModel(PLAN,{name:"Recon"})
eq("plan model: groups commands by node, in order",m1.groups.map((g)=>[g.node,g.title,g.commands.length]),[["n2","Ping host",1],["n4","Scan",2]])
eq("plan model: missing placeholders block the run",[m1.blocked,m1.missing,/\{URL\}/.test(m1.blockText),P.flowRunCanStart(m1,true)],[true,["URL"],true,false])
eq("plan model: counts",[m1.destructive,m1.summary,m1.target,m1.approvals,m1.runLabel,m1.warnings],[1,"3 commands, 1 script, 1 approval stop","lab-01",1,"Run chain",["Destructive command"]])
const okPlan=Object.assign({},PLAN,{commands:PLAN.commands.slice(0,2),missing:[]})
eq("plan model: a clean plan can start",[P.flowRunPlanModel(okPlan).blocked,P.flowRunCanStart(P.flowRunPlanModel(okPlan),false)],[false,true])
eq("plan model: graph errors block",(()=>{const m=P.flowRunPlanModel(Object.assign({},okPlan,{errors:[{node:"n9",code:"dangling",message:"Edge to nowhere"}]}));return [m.blocked,/Edge to nowhere/.test(m.blockText),P.flowRunCanStart(m,true)]})(),[true,true,false])
eq("plan model: the bridge's own block reason wins",P.flowRunPlanModel(Object.assign({},okPlan,{blocked:"The diagram has nothing to run yet."})).blockText,"The diagram has nothing to run yet.")
const aiModel=P.flowRunPlanModel(Object.assign({},okPlan,{ai_made:true,needs_review:true}))
eq("plan model: an unreviewed AI chain needs the checkbox",[aiModel.needsReview,P.flowRunCanStart(aiModel,false),P.flowRunCanStart(aiModel,"yes"),P.flowRunCanStart(aiModel,true)],[true,false,false,true])
eq("plan model: destructive is also detected client-side",P.flowRunPlanModel({commands:[{node:"n",title:"t",text:"rm -rf {Dir}",resolved:"rm -rf /tmp/x",missing:[],destructive:false}]}).destructive,1)
eq("plan model: run from a node",[P.flowRunPlanModel(okPlan,{from_node:"n4"}).runLabel,P.flowRunPlanModel(okPlan,{from_node:"n4"}).fromNode],["Run from this node","n4"])
eq("plan model: junk in, safe defaults out",(()=>{const m=P.flowRunPlanModel(null);return [m.commands.length,m.blocked,m.summary,m.target]})(),[0,false,"0 commands",""])
const dlg=P.flowRunConfirmHtml(m1,{n5:"import json\nprint(1)"})
check("confirm: lists every resolved command with the target",/Target <b>lab-01<\/b>/.test(dlg)&&dlg.indexOf("ping -c 2 10.0.0.5")>0&&dlg.indexOf("sudo nmap 10.0.0.5")>0&&dlg.indexOf("nikto -h {URL}")>0)
check("confirm: destructive and missing commands are marked",/fr-plan-cmd is-destructive[\s\S]*?Destructive<\/span>/.test(dlg)&&/fr-plan-cmd is-missing[\s\S]*?Missing \{URL\}/.test(dlg)&&/1 command looks destructive/.test(dlg))
check("confirm: blocked banner",/fr-banner-block"><b>This chain cannot run yet\.<\/b>/.test(dlg))
check("confirm: scripts show language, line count and expandable code",/<details class="fr-plan-node fr-plan-script"><summary>[\s\S]*python script, 12 lines[\s\S]*<pre class="fr-plan-text fr-plan-code">import json\nprint\(1\)<\/pre><\/details>/.test(dlg))
check("confirm: approvals and warnings",/pauses 1 time to ask/.test(dlg)&&/<summary>1 warning<\/summary>/.test(dlg))
// the sandbox line of flows.plan: scripts without isolation are called out
const noBox=P.flowRunConfirmHtml(P.flowRunPlanModel(Object.assign({},PLAN,{sandbox:{sandbox:"none",network_isolation:false},fingerprint:"abc123"}),{name:"Recon"}),{})
check("confirm: scripts with no sandbox get a plain warning",/fr-banner-sandbox"><b>Scripts run with no isolation\.<\/b>/.test(noBox))
const inBox=P.flowRunConfirmHtml(P.flowRunPlanModel(Object.assign({},PLAN,{sandbox:{sandbox:"bwrap",network_isolation:true}}),{name:"Recon"}),{})
check("confirm: a sandbox is named, with the network note",/Scripts run in a sandbox \(bwrap\), without network access unless a script node allows it\./.test(inBox)&&!/no isolation/.test(inBox))
check("confirm: no sandbox line without scripts or without the field",!/sandbox/i.test(P.flowRunConfirmHtml(P.flowRunPlanModel(Object.assign({},PLAN,{scripts:[],sandbox:{sandbox:"none"}})),{}))&&!/fr-banner-sandbox|fr-sandbox-note/.test(dlg))
eq("plan model: carries the fingerprint and the sandbox",[P.flowRunPlanModel(Object.assign({},PLAN,{fingerprint:"abc123",sandbox:{sandbox:"none"}})).fingerprint,P.flowRunPlanModel(Object.assign({},PLAN,{sandbox:{sandbox:"none"}})).sandbox,P.flowRunPlanModel(PLAN).sandbox,P.flowRunPlanModel(PLAN).fingerprint],["abc123",{mode:"none",networkIsolation:false},null,""])
check("run: the plan's fingerprint goes back with flows.run",/review_ack:model\.needsReview,fingerprint:model\.fingerprint\|\|undefined\}/.test(RUN))
const netOff=P.fiScriptFormHtml({language:"python",code:"",branches:["out"],timeout:60},{catalog:{}}),netOn=P.fiScriptFormHtml({language:"python",code:"",branches:["out"],network:true},{catalog:{}})
check("inspector: network access is its own switch at the top of the script form, off by default",netOff.indexOf('<div class="fi-switch-row">')===0&&/data-k="network" data-t="bool" data-rr="1"><span class="fi-switch-track">/.test(netOff)&&/fi-switch-state">Off</.test(netOff)&&/A sandboxed script has no network unless this is on\. Without a sandbox a script always has network access\./.test(netOff)&&netOn.indexOf('<div class="fi-switch-row is-on">')===0&&/data-rr="1" checked>/.test(netOn)&&/fi-switch-state">On</.test(netOn))
const polPlan=(sp,extra)=>P.flowRunPlanModel(Object.assign({},PLAN,{blocked:"",errors:[],missing:[],commands:[],scripts:[{node:"n5",title:"Check",language:"python",lines:3,network:true},{node:"n6",title:"Other",language:"bash",lines:1,network:false}],script_policy:sp},extra||{}),{name:"Recon"})
const unsafe=polPlan({mode:"allow",source:"global",unsandboxed:true,blocked:false})
const unsafeHtml=P.flowRunConfirmHtml(unsafe,{})
check("confirm: unsandboxed scripts get a clear warning that names the setting",/fr-banner-danger fr-banner-sandbox"><b>Scripts will run with no isolation\.<\/b>/.test(unsafeHtml)&&/the app setting allows unsandboxed scripts/.test(unsafeHtml)&&unsafe.blocked===false)
check("confirm: each script says network on or off",/fr-flag-net-on">network on<\/span>/.test(unsafeHtml)&&/fr-flag-net-off">network off<\/span>/.test(unsafeHtml)&&!/network o[nf]/.test(dlg))
const stopped=polPlan({mode:"sandboxed",source:"global",unsandboxed:false,blocked:true})
const stoppedHtml=P.flowRunConfirmHtml(stopped,{})
check("confirm: a policy block says why and where to change it, and the run cannot start",stopped.blocked===true&&P.flowRunCanStart(stopped,true)===false&&/its scripts are not allowed to run here\./.test(stoppedHtml)&&(stoppedHtml.match(/fr-banner-block/g)||[]).length===1&&/Settings &gt; Extensions &gt; Chain diagrams/.test(stoppedHtml)&&/Sandboxed only/.test(stoppedHtml))
check("confirm: a block set in the diagram points at the diagram's Settings",/this diagram&#39;s Settings say/.test(P.flowRunConfirmHtml(polPlan({mode:"sandboxed",source:"diagram",blocked:true}),{})))
check("confirm: an ignored per-diagram Allow says to review the diagram first",/is ignored while it is AI-made or not reviewed: mark it as reviewed first/.test(P.flowRunConfirmHtml(polPlan({mode:"sandboxed",source:"global",blocked:true},{warnings:[{code:"script_isolation_ignored",message:"x"}]}),{})))
check("confirm: the bridge's own block reason is kept",polPlan({mode:"sandboxed",source:"global",blocked:true},{blocked:"Engine says no."}).blockText==="Engine says no.")
check("confirm: sandboxed scripts say so",/Scripts run in a sandbox \(bwrap\), without network access unless a script node allows it\./.test(P.flowRunConfirmHtml(polPlan({mode:"sandboxed",source:"global",unsandboxed:false,blocked:false},{sandbox:{sandbox:"bwrap",network_isolation:true}}),{})))
check("history: every row can open its log",/data-fr="hist-log" data-run="r1"/.test(P.flowRunHistoryHtml([{run_id:"r1",chain_name:"Recon",state:"done",started_at:"2026-01-01T10:00:00+00:00"}])))
check("run bar: Open logs button, live log through flows.run_log with the status events as fallback",/data-fr="logs"/.test(RUN)&&/bridge\("flows\.run_log",\[runId,st\.logNext,500\]\)/.test(RUN)&&/bridge method missing[\s\S]{0,60}st\.noRunLog=true/.test(RUN))
const aiDlg=P.flowRunConfirmHtml(aiModel,{})
check("confirm: AI banner with the required checkbox",/fr-banner-ai"><b>AI-made - review before running\.<\/b>/.test(aiDlg)&&/<input type="checkbox" data-fr="ack">/.test(aiDlg)&&/I reviewed this chain/.test(aiDlg))
check("confirm: no AI banner on a reviewed chain, imported chains say so",!/data-fr="ack"/.test(P.flowRunConfirmHtml(P.flowRunPlanModel(okPlan),{}))&&/Imported - review before running/.test(P.flowRunConfirmHtml(P.flowRunPlanModel(Object.assign({},okPlan,{needs_review:true})),{})))
check("confirm: no live target is said plainly",/No live target\./.test(P.flowRunConfirmHtml(P.flowRunPlanModel({commands:[]}),{})))
const evilPlan={target:{name:XSS},commands:[{node:XSS,title:XSS,text:XSS,resolved:XSS,missing:[XSS],destructive:true}],scripts:[{node:"s",title:XSS,language:XSS,lines:1}],errors:[{message:XSS}],warnings:[{message:XSS}],blocked:XSS,needs_review:true,ai_made:true,approvals:1}
check("confirm: hostile plan text is escaped everywhere",safe(P.flowRunConfirmHtml(P.flowRunPlanModel(evilPlan,{name:XSS}),{s:XSS})))
eq("script code lookup",P.flowRunScriptCode({nodes:[{id:"a",type:"script",config:{code:"x"}},{id:"b",type:"command",config:{}},{id:"c",type:"script",config:{}}]}),{a:"x",c:""})
// ---- run: node output, trace, dry report, log, history
const SDONE={run_id:"r1",playbook_id:5,mode:"run",state:"done",nodes:{n2:{state:"success",visits:2,branch:"success",duration_ms:1234,error:"",output:{stdout:"64 bytes ttl=64",stderr:"",exit_code:0,parsed:{alive:true},vars_set:{alive:true},resolved:["ping -c 2 10.0.0.5"],trace:[]}},n3:{state:"success",visits:1,branch:"alive",output:{trace:[{branch:"alive",matched:true,conditions:[{result:true,actual:"up",text:"host is up",error:""}]}]}},n6:{state:"fail",visits:1,error:"exit 2",output:{stdout:"",stderr:"boom",exit_code:2}},n7:{state:"pending",visits:0,output:{}}}}
const nv=P.flowRunNodeView(SDONE,"n2",TITLES)
eq("node view: header facts",[nv.title,nv.state,nv.stateLabel,nv.meta,nv.resolved,nv.tab,nv.canRerun],["Ping host","success","Success","exit 0 - 1.2 s - 2 visits - took success",["ping -c 2 10.0.0.5"],"stdout",true])
eq("node view: parsed is pretty JSON",nv.tabs.parsed,"{\n  \"alive\": true\n}")
eq("node view: default tab follows the content",[P.flowRunNodeView(SDONE,"n3",TITLES).tab,P.flowRunNodeView(SDONE,"n6",TITLES).tab],["trace","stderr"])
eq("node view: re-run only after a real run ended, never from start",[P.flowRunNodeView(Object.assign({},SDONE,{state:"running"}),"n2",TITLES).canRerun,P.flowRunNodeView(Object.assign({},SDONE,{mode:"dry"}),"n2",TITLES).canRerun,P.flowRunNodeView(Object.assign({},SDONE,{nodes:{n1:{state:"success"}}}),"n1",TITLES).canRerun],[false,false,false])
eq("node view: a node outside the run",[P.flowRunNodeView(SDONE,"zz",TITLES).found,P.flowRunNodeView(null,"zz").stateLabel],[false,"Not part of this run"])
const nh=P.flowRunNodeHtml(nv)
check("node html: four tabs, output, resolved command, re-run button",["stdout","stderr","parsed","trace"].every((t)=>nh.indexOf('data-tab="'+t+'"')>0)&&/<pre class="fr-out" data-out="stdout">64 bytes ttl=64<\/pre>/.test(nh)&&/\$ ping -c 2 10\.0\.0\.5/.test(nh)&&/data-fr="rerun"/.test(nh))
check("node html: empty tabs say so",/No error output\./.test(P.flowRunNodeHtml(nv,"stderr"))&&/Not reached yet\./.test(P.flowRunNodeHtml(P.flowRunNodeView(SDONE,"n7",TITLES)))&&/not part of the run/.test(P.flowRunNodeHtml(P.flowRunNodeView(SDONE,"zz",TITLES))))
check("node html: decision trace with true/false per condition",/fr-trace-branch matched[\s\S]*matched<\/span>[\s\S]*fr-flag-ok">true<\/span>[\s\S]*host is up[\s\S]*\(got up\)/.test(P.flowRunNodeHtml(P.flowRunNodeView(SDONE,"n3",TITLES))))
const evil={run_id:"r",mode:"run",state:"done",playbook_id:1,nodes:{n:{state:XSS,branch:XSS,error:XSS,visits:1,output:{stdout:XSS,stderr:XSS,parsed:{k:XSS},vars_set:{k:XSS},resolved:[XSS],trace:[{branch:XSS,matched:true,conditions:[{result:true,actual:XSS,text:XSS}]}]}}}}
check("node html: attacker-controlled output is escaped in every tab",["stdout","stderr","parsed","trace"].every((t)=>safe(P.flowRunNodeHtml(P.flowRunNodeView(evil,"n",{n:{title:XSS,type:"command"}}),t))))
const GRAPH={nodes:[{id:"n1",type:"start",title:"Start",config:{}},{id:"n2",type:"command",title:"Ping host",config:{commands:[{text:"ping -c 2 {IPv4}"}],mode:"sequence"}},{id:"n3",type:"decision",title:"Alive?",config:NODES.decision},{id:"n4",type:"script",title:"Decide",config:{language:"bash",code:"a\nb"}},{id:"n5",type:"end",title:"Stop",config:{status:"fail"}},{id:"n9",type:"comment",title:"note",config:{}}],edges:[{id:"e1",from:"n1",port:"out",to:"n2"},{id:"e2",from:"n2",port:"success",to:"n3"},{id:"e3",from:"n3",port:"alive",to:"n4"},{id:"e4",from:"n3",port:"down",to:"n5"}]}
const DRY={run_id:"d1",mode:"dry",state:"done",nodes:{n1:{state:"planned",output:{}},n2:{state:"planned",output:{resolved:["ping -c 2 10.0.0.5"]}},n3:{state:"planned",output:{}},n4:{state:"planned",output:{}},n5:{state:"planned",output:{}},n9:{state:"pending",output:{}}}}
const report=P.flowRunDryReport(DRY,GRAPH)
eq("dry report: planned nodes in walk order",report.map((r)=>r.node),["n1","n2","n3","n4","n5"])
eq("dry report: resolved commands and where each port leads",report[1].lines,[{kind:"cmd",text:"ping -c 2 10.0.0.5"},{kind:"route",text:"success -> Alive?"}])
eq("dry report: decisions are spelled out in words, every branch listed",report[2].lines.map((l)=>l.text),["If output contains 'ttl=' and matches of /open/ >= 1 -> alive","Otherwise -> down","alive -> Decide","down -> Stop"])
check("dry report: scripts and ends",/bash script, 2 lines/.test(report[3].lines[0].text)&&/Ends the run as fail/.test(report[4].lines[0].text))
check("dry report: text and html are labelled 'nothing was executed'",/^Dry run - nothing was executed\n\n1\. Start \[start\]/.test(P.flowRunDryText(report))&&/<b>Dry run - nothing was executed\.<\/b>/.test(P.flowRunDryHtml(report))&&/\$ ping -c 2 10\.0\.0\.5/.test(P.flowRunDryHtml(report)))
check("dry report: empty and hostile input",/Nothing would run/.test(P.flowRunDryHtml([]))&&safe(P.flowRunDryHtml(P.flowRunDryReport({nodes:{a:{state:"planned",output:{resolved:[XSS]}}}},{nodes:[{id:"a",type:"command",title:XSS,config:{}}],edges:[{from:"a",port:XSS,to:"a"}]}))))
check("log row: time, node title, level, escaped text",(()=>{const h=P.flowRunEventHtml(EV(2,"Running <b>ping</b>","n2","warn"),TITLES);return /class="fr-ev fr-ev-warn" data-node="n2"/.test(h)&&/fr-ev-time">\d\d:\d\d:\d\d</.test(h)&&/fr-ev-node">Ping host</.test(h)&&h.indexOf("&lt;b&gt;ping&lt;/b&gt;")>0})())
check("log row: hostile event and unknown level",safe(P.flowRunEventHtml({seq:1,ts:XSS,node:XSS,level:XSS,text:XSS},{}))&&/fr-ev-info/.test(P.flowRunEventHtml({level:"weird",text:"x"})))
const hist=P.flowRunHistoryHtml([{run_id:"r1",playbook_id:5,chain_name:"Recon",mode:"run",state:"done",source:"flow",target:"lab-01",started_at:"2026-01-01T10:00:00+00:00",ended_at:"2026-01-01T10:01:05+00:00"},{run_id:"d1",chain_name:"Recon",mode:"dry",state:"failed",source:"flow-caller",target:"",started_at:"2026-01-01T09:00:00+00:00",ended_at:""}])
check("history: rows reopen a stored run, show state, mode, target and duration",/data-fr="hist-open" data-run="r1"/.test(hist)&&/fr-state-run-done">Finished</.test(hist)&&/Recon - on lab-01 - 1m 05s/.test(hist)&&/Dry run<\/span>/.test(hist)&&/from flow-caller/.test(hist)&&/data-fr="hist-del" data-run="d1"/.test(hist))
check("history: empty and hostile rows",/No runs recorded yet/.test(P.flowRunHistoryHtml([]))&&safe(P.flowRunHistoryHtml([{run_id:XSS,chain_name:XSS,mode:XSS,state:XSS,source:XSS,target:XSS,started_at:XSS,ended_at:XSS}])))
// ---- css
check("css: LF only, no hard-coded hex colours",CSS.indexOf("\r")===-1&&!/#[0-9a-fA-F]{3,8}\b/.test(CSS))
check("css: every user-select has its -webkit- twin",(()=>{const rules=CSS.match(/[^{}]+\{[^{}]*\}/g)||[];return rules.every((r)=>{const plain=(r.match(/(?:^|[;{])user-select:/g)||[]).length,webkit=(r.match(/-webkit-user-select:/g)||[]).length;return plain===webkit})})())
check("css: glass variants live in this file, keyed off data-style",(CSS.match(/^html:where\(\[data-style="glass"\]\) /gm)||[]).length>=3&&!/^\[data-style|^:where\(\[data-style/m.test(CSS))
check("css: colours come from theme variables",/var\(--text\)/.test(CSS)&&/var\(--glass-border\)/.test(CSS)&&/var\(--accent-a\)/.test(CSS)&&/var\(--danger\)/.test(CSS)&&/var\(--pal-success\)/.test(CSS))
const usedClasses=(src)=>{const out=new Set();(src.match(/\b(?:fi|fr)-[a-z0-9-]+/g)||[]).forEach((c)=>{if(!/-$/.test(c))out.add(c)});return out}
const dynamic=/^(fr-state-|fr-run-|fr-ev-|fr-dry-|fr-flag-|fi-chip-|fr-banner-)/
const unstyled=[...usedClasses(INSPECTOR),...usedClasses(RUN)].filter((c)=>CSS.indexOf("."+c)===-1&&CSS_FIELDS.indexOf("."+c)===-1&&!dynamic.test(c))
// Hook-only classes: used to find elements, they need no rule of their own.
const HOOKS=["fi-cmd-label","fi-cond-source","fi-cond-value","fi-picker-overlay","fi-picker-search","fi-grid-menu","fi-test-out","fr-choice","fr-tab","fr-log","fr-history","fr-out-trace","fr-pane","fi-area","fr-errors","fr-hist-main","fr-is-dry","fr-plan-script","fi-menu-host","fi-code-foot"]
check("css: every class the panels emit is styled",unstyled.filter((c)=>HOOKS.indexOf(c)===-1).length===0,unstyled.filter((c)=>HOOKS.indexOf(c)===-1).join(","))
check("css: the diagram name keeps some width when the caller and Unsaved badge crowd the header",/\.cf-name\{[^}]*min-width:4em/.test(CSS)&&/\.cf-caller\{[^}]*flex:0 1 auto;min-width:0;[^}]*text-overflow:ellipsis/.test(CSS))
check("css: run states painted for every node and run state",["success","fail","running","waiting","skipped","planned"].every((s)=>CSS.indexOf(".fr-state-"+s)!==-1)&&["done","failed","timeout","running","paused","waiting_approval","cancelled"].every((s)=>CSS.indexOf(".fr-state-run-"+s)!==-1)&&["running","paused","done","failed","stopped","idle"].every((s)=>CSS.indexOf(".fr-run-"+s)!==-1))
// ---- the panels against the fake DOM
function fakeEditor(graph){
const ed={graph:graph,updates:0,runStates:[],selection:[],el:new FakeEl("div"),
getGraph:()=>JSON.parse(JSON.stringify(ed.graph)),
updateNode:(id,fn)=>{const node=ed.graph.nodes.filter((n)=>n.id===id)[0];if(!node)return false;fn(node,ed.graph);ed.updates++;return true},
setRunState:(s)=>{ed.runStates.push(s)},getSelection:()=>ed.selection.slice(),select:(ids)=>{ed.selection=ids.slice()}}
return ed
}
const input=(k,value,extra)=>({target:Object.assign(new FakeEl("input"),{dataset:Object.assign({k:k,t:"str"},extra||{}),value:value,type:"text"})})
const click=(root,sel,dataset)=>{const btn=Object.assign(new FakeEl("button"),{dataset:dataset});root.dispatch("click",{target:{closest:(s)=>s===sel?btn:null},preventDefault(){}});return btn}
async function panels(){
// -- inspector: debounced commits
const graph={nodes:[{id:"n1",type:"start",title:"Start",x:0,y:0,config:{trigger:"manual"}},{id:"n2",type:"command",title:"Ping",x:200,y:0,config:{commands:[{text:"ping {IPv4}",command_id:null,src:"",label:""}],mode:"sequence",stop_on_fail:true,timeout:300,shell:""}},{id:"n3",type:"decision",title:"Alive?",x:400,y:0,config:{branches:[{name:"alive",match:"all",conditions:[{source:"output",field:"",op:"contains",value:"ttl=",ci:true}]}],else:"down"}},{id:"n4",type:"script",title:"S",x:600,y:0,config:{language:"python",code:"",branches:["out","other"],timeout:60}}],edges:[{id:"e1",from:"n1",port:"out",to:"n2"},{id:"e2",from:"n2",port:"success",to:"n3"},{id:"e3",from:"n3",port:"alive",to:"n4"},{id:"e4",from:"n3",port:"down",to:"n2"},{id:"e5",from:"n4",port:"other",to:"n2"}]}
const ed=fakeEditor(graph)
const host=new FakeEl("aside")
const toasts=[]
const insp=P.flowInspectorCreate(host,ed,{catalog:{languages:{}},toast:(m,k)=>toasts.push([m,k]),bridge:()=>Promise.resolve([]),commands:()=>Promise.resolve(ROWS),chains:()=>Promise.resolve([]),playbookId:1})
check("inspector: public API",["show","refresh","setIssues","destroy"].every((k)=>typeof insp[k]==="function")&&host.children[0]===insp.el&&insp.el.className==="flow-inspector")
check("inspector: empty state before a node is selected",/Select a node to edit it/.test(insp.el.querySelector(".fi-body").innerHTML))
insp.show("n2")
const body=()=>insp.el.querySelector(".fi-body").innerHTML
check("inspector: shows the command form for the selected node",/data-k="commands\.0\.text"/.test(body())&&/>Command</.test(insp.el.querySelector(".fi-head").innerHTML)&&insp.current()==="n2")
for(let i=1;i<=5;i++)insp.el.dispatch("input",input("commands.0.text","ping -c "+i+" {IPv4}",{fx:"cmd"}))
eq("inspector: five keystrokes commit nothing yet and leave one pending timer",[ed.updates,box.timers.length,box.timers[0]&&box.timers[0].ms],[0,1,P.FI_COMMIT_MS])
box.fire()
eq("inspector: the pause commits once, with the last text",[ed.updates,ed.graph.nodes[1].config.commands[0].text,box.timers.length],[1,"ping -c 5 {IPv4}",0])
insp.el.dispatch("change",input("commands.0.text","ping -c 5 {IPv4}"))
eq("inspector: the change event after a debounced commit adds no undo step",ed.updates,1)
insp.el.dispatch("input",input("@title","Ping twice"))
insp.el.dispatch("focusout",{target:new FakeEl("input")})
eq("inspector: blur flushes the pending edit at once",[ed.updates,ed.graph.nodes[1].title,box.timers.length],[2,"Ping twice",0])
insp.el.dispatch("input",input("timeout","9",{t:"int"}))
eq("inspector: number fields wait for change",[ed.updates,box.timers.length],[2,0])
const num=input("timeout","99999",{t:"int"});num.target.type="number";num.target.min="1";num.target.max="7200"
insp.el.dispatch("change",num)
eq("inspector: numbers are clamped to the node limits",[ed.graph.nodes[1].config.timeout,num.target.value],[7200,"7200"])
click(insp.el,"[data-act]",{act:"cmd-type"})
eq("inspector: 'Type a command' adds a free-text row immediately",[ed.graph.nodes[1].config.commands.length,ed.graph.nodes[1].config.commands[1],/data-k="commands\.1\.text"/.test(body())],[2,{text:"",command_id:null,src:"",label:""},true])
click(insp.el,"[data-act]",{act:"cmd-up",i:"1"})
eq("inspector: reorder",ed.graph.nodes[1].config.commands.map((c)=>c.text),["","ping -c 5 {IPv4}"])
click(insp.el,"[data-act]",{act:"cmd-del",i:"0"})
eq("inspector: remove",ed.graph.nodes[1].config.commands.map((c)=>c.text),["ping -c 5 {IPv4}"])
click(insp.el,"[data-act]",{act:"set",k:"mode",v:"parallel"})
eq("inspector: sequence/parallel toggle",ed.graph.nodes[1].config.mode,"parallel")
// picker
click(insp.el,"[data-act]",{act:"cmd-pick"})
await settle()
const overlay=box.document.body.children[box.document.body.children.length-1]
check("inspector: the picker lists the Commands library",overlay&&/fi-picker-item/.test(overlay.querySelector(".fi-picker-list").innerHTML)&&/Ping sweep/.test(overlay.querySelector(".fi-picker-list").innerHTML)&&!/Empty/.test(overlay.querySelector(".fi-picker-list").innerHTML))
const item=Object.assign(new FakeEl("button"),{dataset:{pick:"1"}})
overlay.dispatch("click",{target:{closest:(s)=>s==="[data-pick]"?item:null}})
eq("inspector: picking stores text, command_id, src and label",[ed.graph.nodes[1].config.commands[1],box.document.body.children.indexOf(overlay)],[{text:"nmap -p- {IPv4}\nsecond",command_id:2,src:"db",label:"Nmap full"},-1])
// issues
insp.setIssues({errors:[{node:"n2",message:"Empty <command>"}],warnings:[{node:"n3",message:"other node"}]})
check("inspector: setIssues shows this node's problems, escaped",/fi-issue-error">Empty &lt;command&gt;</.test(insp.el.querySelector(".fi-issues").innerHTML)&&!/other node/.test(insp.el.querySelector(".fi-issues").innerHTML))
// external change -> refresh reloads; own edits are not clobbered
ed.graph.nodes[1].title="Renamed by undo"
insp.refresh()
// The title is edited in the panel header since the redesign (it used to be the first field of the form).
const headHtml=()=>insp.el.querySelector(".fi-head").innerHTML
check("inspector: refresh picks up an undo/redo of the shown node",/value="Renamed by undo"/.test(headHtml()))
insp.el.dispatch("input",input("@title","Typing..."))
ed.graph.nodes[1].title="Changed elsewhere"
insp.refresh()
check("inspector: refresh never overwrites text that is still being typed",!/Changed elsewhere/.test(body())&&!/Changed elsewhere/.test(headHtml()))
insp.show("n3")
eq("inspector: switching node commits the pending edit first",[ed.graph.nodes[1].title,box.timers.length,insp.current()],["Typing...",0,"n3"])
// decision: rename keeps edges
const before=ed.updates
const ren=Object.assign(new FakeEl("input"),{dataset:{rename:"branches.0.name"},value:"up"})
insp.el.dispatch("change",{target:ren})
eq("inspector: renaming a branch moves its edges (flowRenamePort)",[ed.graph.nodes[2].config.branches[0].name,ed.graph.edges.filter((e)=>e.from==="n3").map((e)=>e.port),ed.updates-before],["up",["up","down"],1])
const renElse=Object.assign(new FakeEl("input"),{dataset:{rename:"else"},value:"dead"})
insp.el.dispatch("change",{target:renElse})
eq("inspector: renaming the else branch moves its edges",[ed.graph.nodes[2].config.else,ed.graph.edges.filter((e)=>e.from==="n3").map((e)=>e.port)],["dead",["up","dead"]])
const bad=Object.assign(new FakeEl("input"),{dataset:{rename:"branches.0.name"},value:"dead"})
insp.el.dispatch("change",{target:bad})
eq("inspector: a duplicate or invalid branch name is refused and restored",[ed.graph.nodes[2].config.branches[0].name,bad.value,ed.graph.edges.filter((e)=>e.from==="n3").map((e)=>e.port)],["up","up",["up","dead"]])
const src=Object.assign(new FakeEl("select"),{dataset:{chg:"cond-source",b:"0",c:"0"},value:"exit_code"})
insp.el.dispatch("change",{target:src})
eq("inspector: changing the source resets op and value to what it allows",ed.graph.nodes[2].config.branches[0].conditions[0],{source:"exit_code",field:"",op:"eq",value:"0",ci:true})
click(insp.el,"[data-act]",{act:"cond-add",b:"0"})
click(insp.el,"[data-act]",{act:"branch-add"})
eq("inspector: add condition / add branch",[ed.graph.nodes[2].config.branches[0].conditions.length,ed.graph.nodes[2].config.branches.map((b)=>b.name)],[2,["up","branch"]])
const t1=Object.assign(new FakeEl("textarea"),{dataset:{test:"stdout"},value:"anything"})
const updatesBeforeTest=ed.updates
insp.el.dispatch("input",{target:t1})
check("inspector: the test box evaluates locally and never edits the graph",ed.updates===updatesBeforeTest&&box.timers.length===0&&/would go to <b class="fi-mono">branch<\/b>\./.test(insp.el.querySelector("[data-test-out]").innerHTML))
// script: branches
insp.show("n4")
const sren=Object.assign(new FakeEl("input"),{dataset:{rename:"branches.1"},value:"alive"})
insp.el.dispatch("change",{target:sren})
eq("inspector: renaming a script branch moves its edges",[ed.graph.nodes[3].config.branches,ed.graph.edges.filter((e)=>e.from==="n4").map((e)=>e.port)],[["out","alive"],["alive"]])
const serr=Object.assign(new FakeEl("input"),{dataset:{rename:"branches.0"},value:"error"})
insp.el.dispatch("change",{target:serr})
eq("inspector: a script branch cannot be called error",ed.graph.nodes[3].config.branches,["out","alive"])
click(insp.el,"[data-act]",{act:"tpl",i:"0"})
check("inspector: a template fills the code and sets the language",/json\.load\(sys\.stdin\)/.test(ed.graph.nodes[3].config.code)&&ed.graph.nodes[3].config.language==="python")
click(insp.el,"[data-act]",{act:"sbranch-detect"})
eq("inspector: 'add from code' appends the branches the script prints",ed.graph.nodes[3].config.branches,["out","alive","down"])
// -- the redesigned panel: header, tabs, the generic form of catalog types, the output preview
check("inspector: header has the icon tile, the editable title, the type and the ports",/class="fi-tile flow-cat-action"><i class="icon icon-code-block">/.test(headHtml())&&/class="fi-title"[^>]*data-k="@title"/.test(headHtml())&&/>Script</.test(headHtml())&&/fi-port-chip fi-tone-neg">error</.test(headHtml()))
const tabsHtml=(i)=>i.el.querySelector(".fi-tabs").innerHTML
eq("inspector: three tabs, Parameters first",[(tabsHtml(insp).match(/data-act="tab" data-v="(\w+)"/g)||[]).length,/fi-tab active"[^>]*data-v="params"/.test(tabsHtml(insp)),insp.tab()],[3,true,"params"])
check("inspector: a legacy node keeps its run settings, on the Settings tab",!/data-k="timeout"/.test(body())&&!/data-k="network"/.test(body())&&/data-k="code"/.test(body()))
click(insp.el,"[data-act]",{act:"tab",v:"settings"})
check("inspector: Settings tab of a script has network and timeout, and says what the node is",/data-k="network"/.test(body())&&/data-k="timeout"/.test(body())&&/About this node/.test(body())&&!/data-k="code"/.test(body())&&insp.tab()==="settings")
click(insp.el,"[data-act]",{act:"tab",v:"params"})
const CAT={languages:{},categories:[{id:"action",label:"Actions"},{id:"logic",label:"Logic"}],types:{
http:{label:"HTTP request",category:"action",icon:"flow-globe",color:"action",input:true,ports:["success","fail"],tones:{success:"pos",fail:"neg"},description:"Call a URL <now>.",defaults:{method:"GET",url:"",headers:[],body:"",timeout:30,verify_tls:true,var:"response"},
fields:[{key:"method",label:"Method",type:"select",options:[{value:"GET",label:"GET"},{value:"POST",label:"POST"}]},{key:"url",label:"URL",type:"text",required:true},{key:"headers",label:"Headers",type:"rows",row_label:"header",max_rows:2,rows:[{key:"name",label:"Name",type:"text"},{key:"value",label:"Value",type:"text"}]},{key:"body",label:"Body",type:"textarea",show_if:{method:["POST"]}},{key:"timeout",label:"Timeout (s)",type:"number",min:1,max:300,integer:true},{key:"verify_tls",label:"Verify TLS",type:"bool"},{key:"var",label:"Store as",type:"var"}]},
switch:{label:"Switch",category:"logic",icon:"flow-switch",color:"logic",input:true,ports:[],dynamic:{rows:"cases",name:"name",fixed_key:"default"},defaults:{value:"${last.stdout}",cases:[],default:"default"},
fields:[{key:"value",label:"Value",type:"text"},{key:"cases",label:"Cases",type:"rows",row_label:"case",rows:[{key:"name",label:"Port",type:"port"},{key:"value",label:"Equals",type:"text"}]},{key:"default",label:"Otherwise",type:"port"}]}}}
ed.graph.nodes.push({id:"n5",type:"http",title:"Fetch",x:0,y:200,config:{method:"GET",url:"",headers:[{name:"Accept",value:XSS}],body:"",timeout:30,verify_tls:true,var:"response"}})
ed.graph.nodes.push({id:"n6",type:"switch",title:"Route",x:0,y:400,config:{value:"${last.stdout}",cases:[{name:"web",value:"80"},{name:"ssh",value:"22"}],default:"default"}})
ed.graph.edges.push({id:"e9",from:"n6",port:"web",to:"n2"},{id:"e10",from:"n5",port:"fail",to:"n2"})
const gi=P.flowInspectorCreate(new FakeEl("aside"),ed,{catalog:CAT,toast:(m,k)=>toasts.push([m,k]),bridge:()=>Promise.resolve([]),copy:(t)=>toasts.push(["copied",t])})
const gbody=()=>gi.el.querySelector(".fi-body").innerHTML
const ghead=()=>gi.el.querySelector(".fi-head").innerHTML
gi.show("n5")
check("inspector: a catalog type gets the generic form, escaped",/class="ff-form"/.test(gbody())&&/data-k="url"/.test(gbody())&&/data-k="headers\.0\.value"/.test(gbody())&&safe(gbody())&&!/data-k="body"/.test(gbody()))
check("inspector: generic header from the catalog, escaped",/>HTTP request</.test(ghead())&&/icon-flow-globe/.test(ghead())&&/Call a URL &lt;now&gt;\./.test(ghead())&&/fi-tone-pos">success</.test(ghead())&&/\$\{response\}/.test(ghead()))
check("inspector: run settings of a catalog type live on the Settings tab",!/data-k="timeout"/.test(gbody())&&!/data-k="verify_tls"/.test(gbody()))
const gBefore=ed.updates
for(let i=1;i<=4;i++)gi.el.dispatch("input",input("url","http://h/"+i,{ff:"1"}))
eq("inspector: typing in a generic field is debounced like the legacy forms",[ed.updates-gBefore,box.timers.length],[0,1])
box.fire()
eq("inspector: one burst, one update",[ed.updates-gBefore,ed.graph.nodes[4].config.url],[1,"http://h/4"])
const bad5=input("var","9bad",{ff:"1"})
gi.el.dispatch("input",bad5)
check("inspector: a bad variable name is flagged inline while typing",bad5.target.classList.contains("invalid")&&/letter or _/.test(gi.el.querySelector('[data-ferr="var"]').textContent))
gi.el.dispatch("input",input("var","response",{ff:"1"}))
gi.flush()
const sel=Object.assign(new FakeEl("select"),{dataset:{k:"method",t:"str",ff:"1",rr:"1"},value:"POST"})
gi.el.dispatch("change",{target:sel})
check("inspector: show_if is re-evaluated when its controlling field changes",ed.graph.nodes[4].config.method==="POST"&&/data-k="body"/.test(gbody()))
click(gi.el,"[data-act]",{act:"frow-add",f:"headers"})
click(gi.el,"[data-act]",{act:"frow-add",f:"headers"})
eq("inspector: rows are added up to max_rows",ed.graph.nodes[4].config.headers.map((h)=>h.name),["Accept",""])
click(gi.el,"[data-act]",{act:"frow-up",f:"headers",i:"1"})
click(gi.el,"[data-act]",{act:"frow-del",f:"headers",i:"1"})
eq("inspector: rows reorder and remove",ed.graph.nodes[4].config.headers,[{name:"",value:""}])
gi.el.dispatch("input",input("headers.0.name","X-Test",{ff:"1"}))
gi.flush()
eq("inspector: a row cell edits its own path",ed.graph.nodes[4].config.headers[0].name,"X-Test")
click(gi.el,"[data-act]",{act:"ins-open",for:"url"})
click(gi.el,"[data-act]",{act:"ins-pick",v:"${item}"})
gi.flush()
eq("inspector: the insert menu appends a value and closes",[ed.graph.nodes[4].config.url,gi.el.children.length],["http://h/4${item}",0])
click(gi.el,"[data-act]",{act:"tab",v:"settings"})
const num5=input("timeout","99999",{t:"num",ff:"1",int:"1"});num5.target.type="number";num5.target.min="1";num5.target.max="300"
gi.el.dispatch("input",num5)
gi.el.dispatch("change",num5)
eq("inspector: generic numbers wait for change and clamp",[/data-k="timeout"/.test(gbody()),ed.graph.nodes[4].config.timeout,num5.target.value],[true,300,"300"])
click(gi.el,"[data-act]",{act:"tab",v:"output"})
check("inspector: Output tab starts with the empty state",/Run or dry-run the chain to see this node&#39;s output/.test(gbody())&&typeof gi.setRun==="function")
gi.setRun({run_id:"r9",nodes:{n5:{state:"fail",visits:1,branch:"fail",duration_ms:1234,error:"boom "+XSS,output:{stdout:XSS,stderr:"",exit_code:1,parsed:{items:[XSS]},vars_set:{response:XSS},http:{status:500,url:"http://h/"+XSS,elapsed_ms:12,headers:{server:XSS}}}}}})
check("inspector: setRun paints the node's output, escaped",/fo-badge fo-b-warn/.test(gbody())&&/1\.2 s/.test(gbody())&&/data-sec="stdout"/.test(gbody())&&/data-sec="http"/.test(gbody())&&safe(gbody()))
check("inspector: the Output tab carries the status dot",/fi-tab-dot fo-b-warn/.test(tabsHtml(gi)))
click(gi.el,"[data-act]",{act:"out-copy",sec:"stdout"})
eq("inspector: Copy hands over the whole section text",toasts[toasts.length-1],["copied",XSS])
gi.setRun(null)
check("inspector: clearing the run brings the empty state back",/Run or dry-run/.test(gbody())&&!/fi-tab-dot/.test(tabsHtml(gi)))
click(gi.el,"[data-act]",{act:"tab",v:"params"})
gi.show("n6")
check("inspector: dynamic ports of a catalog type are listed",/fi-port-chip fi-tone-main">web</.test(ghead())&&/fi-port-chip[^>]*>default</.test(ghead())&&/data-rename="cases\.0\.name"/.test(gbody())&&/data-rename="default"/.test(gbody()))
const pren=Object.assign(new FakeEl("input"),{dataset:{rename:"cases.0.name",ff:"1"},value:"http"})
gi.el.dispatch("change",{target:pren})
eq("inspector: renaming a row port moves its edges",[ed.graph.nodes[5].config.cases[0].name,ed.graph.edges.filter((e)=>e.from==="n6").map((e)=>e.port)],["http",["http"]])
const pdup=Object.assign(new FakeEl("input"),{dataset:{rename:"default",ff:"1"},value:"ssh"})
gi.el.dispatch("change",{target:pdup})
eq("inspector: a port name already used on the node is refused",[ed.graph.nodes[5].config.default,pdup.value],["default","default"])
click(gi.el,"[data-act]",{act:"frow-add",f:"cases"})
eq("inspector: a new row gets a free port name",ed.graph.nodes[5].config.cases.map((c)=>c.name),["http","ssh","case3"])
gi.destroy()
// read-only
const ro=P.flowInspectorCreate(new FakeEl("aside"),ed,{readOnly:true,bridge:()=>Promise.resolve([])})
ro.show("n2")
const roBefore=ed.updates
ro.el.dispatch("input",input("@title","nope"))
click(ro.el,"[data-act]",{act:"cmd-type"})
eq("inspector: read-only never edits",[ed.updates-roBefore,box.timers.length],[0,0])
ro.destroy()
insp.el.dispatch("input",input("@title","Last words"))
insp.destroy()
eq("inspector: destroy flushes, removes the panel and leaves no timer",[ed.graph.nodes[3].title,host.children.length,box.timers.length],["Last words",0,0])
// -- run panel
const calls=[]
const handlers={}
const bridge=(p,args)=>{calls.push([p,JSON.parse(JSON.stringify(args))]);return handlers[p]?handlers[p](args):Promise.reject(new Error("bridge method missing: "+p))}
const red=fakeEditor(GRAPH)
const rhost=new FakeEl("section")
const finished=[],rtoasts=[]
const run=P.flowRunCreate(rhost,red,{bridge:bridge,toast:(m,k)=>rtoasts.push([m,k]),onFinish:(s)=>finished.push(s.state)})
check("run: public API",["confirmAndRun","dryRun","attach","stopWatching","showHistory","destroy"].every((k)=>typeof run[k]==="function")&&run.el.classList.contains("is-hidden")===false&&/is-hidden/.test(run.el.className))
const statusCalls=()=>calls.filter((c)=>c[0]==="flows.run_status")
let answer=()=>Promise.resolve(JSON.parse(JSON.stringify(S1)))
handlers["flows.run_status"]=(args)=>answer(args)
run.attach("r1",{playbookId:5})
await settle()
eq("run: attach polls at once with since=0 and paints the canvas",[statusCalls().map((c)=>c[1]),red.runStates.length,red.runStates[0].state,run.isWatching()],[[["r1",0]],1,"running",true])
eq("run: the next poll is scheduled about 700 ms later",[box.timers.length,box.timers[0].ms],[1,700])
check("run: bar shows state and the log holds the events",/^Running - Ping host/.test(run.el.querySelector(".fr-sub").textContent)&&run.el.querySelector(".fr-name").textContent==="Recon"&&(run.el.querySelector('[data-pane="log"]').innerHTML.match(/class="fr-ev /g)||[]).length===2)
check("run: Pause and Stop offered while running, Resume hidden",!run.el.querySelector('[data-fr="pause"]').classList.contains("is-hidden")&&!run.el.querySelector('[data-fr="stop"]').classList.contains("is-hidden")&&run.el.querySelector('[data-fr="resume"]').classList.contains("is-hidden"))
answer=()=>Promise.resolve(Object.assign(JSON.parse(JSON.stringify(S1)),{events:[EV(3,"<script>alert(1)</script>","n2","error")],seq:3}))
box.fire();await settle()
eq("run: later polls ask only for newer events",statusCalls()[1][1],["r1",2])
check("run: new events are appended, escaped, not repeated",(run.el.querySelector('[data-pane="log"]').innerHTML.match(/class="fr-ev /g)||[]).length===3&&safe(run.el.querySelector('[data-pane="log"]').innerHTML)&&/fr-ev-error/.test(run.el.querySelector('[data-pane="log"]').innerHTML))
// bridge errors: backoff, then recovery
answer=()=>Promise.reject(new Error("pywebview is gone"))
box.fire();await settle()
eq("run: a failed poll retries with backoff and says so",[box.timers.length,box.timers[0].ms,/^Connection lost - retrying in 1 s/.test(run.el.querySelector(".fr-conn").textContent),run.isWatching()],[1,1400,true,true])
box.fire();await settle()
box.fire();await settle()
eq("run: backoff keeps growing while the bridge is down",[box.timers[0].ms,/retrying in 6 s/.test(run.el.querySelector(".fr-conn").textContent)],[5600,true])
answer=()=>Promise.resolve(Object.assign(JSON.parse(JSON.stringify(S1)),{state:"waiting_approval",approval:{node:"n3",message:"Run the <exploit>?"},events:[],seq:3}))
box.fire();await settle()
eq("run: recovery clears the note and returns to the normal beat",[run.el.querySelector(".fr-conn").textContent,box.timers[0].ms,run.el.querySelector(".fr-conn").classList.contains("is-hidden")],["",700,true])
check("run: approval prompt for approval nodes, escaped",/<b>Alive\?<\/b> asks: Run the &lt;exploit&gt;\?/.test(run.el.querySelector(".fr-approval").innerHTML)&&/data-fr="approve"/.test(run.el.querySelector(".fr-approval").innerHTML)&&/data-fr="reject"/.test(run.el.querySelector(".fr-approval").innerHTML))
handlers["flows.approve"]=()=>Promise.resolve(true)
handlers["flows.pause"]=handlers["flows.resume"]=handlers["flows.stop"]=()=>Promise.resolve(true)
const pollsBefore=statusCalls().length
click(run.el,"[data-fr]",{fr:"approve"});await settle()
eq("run: Approve answers the waiting node and polls again at once",[calls.filter((c)=>c[0]==="flows.approve")[0][1],statusCalls().length-pollsBefore,box.timers.length],[["r1","n3",true],1,1])
click(run.el,"[data-fr]",{fr:"reject"});await settle()
eq("run: Reject sends false",calls.filter((c)=>c[0]==="flows.approve")[1][1],["r1","n3",false])
click(run.el,"[data-fr]",{fr:"pause"});await settle()
click(run.el,"[data-fr]",{fr:"resume"});await settle()
click(run.el,"[data-fr]",{fr:"stop"});await settle()
eq("run: Pause / Resume / Stop call the bridge with the run id",["flows.pause","flows.resume","flows.stop"].map((p)=>calls.filter((c)=>c[0]===p).map((c)=>c[1])),[[["r1"]],[["r1"]],[["r1"]]])
eq("run: control buttons never stack up poll timers",box.timers.length,1)
// node output viewer
red.selection=["n2"]
red.el.dispatch("click",{})
await settle()
check("run: clicking a node on the canvas opens its output",/fr-node-title">Ping host</.test(run.el.querySelector('[data-pane="node"]').innerHTML)&&run.el.querySelector('[data-pane="node"]').classList.contains("is-hidden")===false&&run.el.querySelector('[data-pane="log"]').classList.contains("is-hidden"))
// the run ends -> polling stops
answer=()=>Promise.resolve(Object.assign(JSON.parse(JSON.stringify(SDONE)),{name:"Recon",target:"lab-01",started_at:"2026-01-01T10:00:00+00:00",ended_at:"2026-01-01T10:00:09+00:00",events:[EV(4,"Run finished")],seq:4}))
box.timers.length=0
run.attach("r1",{playbookId:5});await settle()
eq("run: polling stops when the run ends",[box.timers.length,run.isWatching(),finished,red.runStates[red.runStates.length-1].state],[0,false,["done"],"done"])
check("run: the end is announced and Stop/Pause disappear",rtoasts.some((t)=>/Recon: finished/.test(t[0]))&&run.el.querySelector('[data-fr="stop"]').classList.contains("is-hidden")&&run.el.querySelector('[data-fr="pause"]').classList.contains("is-hidden"))
run.selectNode("n2")
check("run: node output after the run, with Re-run from this node",/data-fr="rerun"/.test(run.el.querySelector('[data-pane="node"]').innerHTML)&&/64 bytes ttl=64/.test(run.el.querySelector('[data-pane="node"]').innerHTML))
// confirmation dialog gates
let planAnswer=Object.assign({},PLAN)
handlers["flows.plan"]=()=>Promise.resolve(JSON.parse(JSON.stringify(planAnswer)))
handlers["flows.run"]=()=>Promise.resolve({run_id:"r2"})
const dialog=()=>box.document.body.children[box.document.body.children.length-1]
const choose=(what)=>{const d=dialog();const btn=d.querySelector('[data-fr-choice="'+what+'"]');btn.dataset.frChoice=what;d.dispatch("click",{target:{closest:(s)=>s==="[data-fr-choice]"?btn:null}});return btn}
let p1=run.confirmAndRun(5,{name:"Recon"});await settle()
eq("run: the confirmation is built from flows.plan",[calls.filter((c)=>c[0]==="flows.plan")[0][1],/confirm-box/.test(dialog().innerHTML),dialog().querySelector(".confirm-message").textContent],[[5,null,null],true,"Run \"Recon\"?"])
check("run: missing placeholders disable Run",dialog().querySelector('[data-fr-choice="run"]').disabled===true)
choose("run");await settle()
eq("run: a blocked dialog cannot start a run",[calls.filter((c)=>c[0]==="flows.run").length,box.document.body.children.indexOf(dialog())>=0],[0,true])
choose("cancel")
eq("run: Cancel resolves null and runs nothing",[await p1,calls.filter((c)=>c[0]==="flows.run").length],[null,0])
planAnswer=Object.assign({},okPlan,{ai_made:true,needs_review:true})
p1=run.confirmAndRun(5,{name:"Recon"});await settle()
const ack=dialog().querySelector('[data-fr="ack"]')
check("run: an AI-made chain keeps Run disabled until the review box is ticked",dialog().querySelector('[data-fr-choice="run"]').disabled===true)
choose("run");await settle()
eq("run: clicking Run without the review does nothing",calls.filter((c)=>c[0]==="flows.run").length,0)
ack.checked=true;ack.dispatch("change",{})
check("run: ticking the box enables Run",dialog().querySelector('[data-fr-choice="run"]').disabled===false)
box.timers.length=0
choose("run")
eq("run: a confirmed run sends confirmed + review_ack and starts watching",[await p1,calls.filter((c)=>c[0]==="flows.run")[0][1],run.runId()],["r2",[5,{mode:"run",from_node:null,source:"manual",confirmed:true,review_ack:true}],"r2"])
planAnswer=Object.assign({},okPlan)
calls.length=0
click(run.el,"[data-fr]",{fr:"rerun"});await settle()
eq("run: 're-run from this node' plans from that node",calls.filter((c)=>c[0]==="flows.plan").map((c)=>c[1]),[[5,null,"n2"]])
choose("run");await settle()
eq("run: and runs from it, without a review ack on a reviewed chain",calls.filter((c)=>c[0]==="flows.run")[0][1],[5,{mode:"run",from_node:"n2",source:"manual",confirmed:true,review_ack:false}])
handlers["flows.plan"]=()=>Promise.reject(new Error("The app is locked."))
eq("run: a failing plan call resolves null and tells the user",[await run.confirmAndRun(5,{}),rtoasts[rtoasts.length-1]],[null,["The app is locked.","error"]])
// dry run
calls.length=0;box.timers.length=0
handlers["flows.run"]=()=>Promise.resolve({run_id:"d1"})
answer=()=>Promise.resolve(Object.assign(JSON.parse(JSON.stringify(DRY)),{events:[EV(1,"Would run: ping -c 2 10.0.0.5","n2")],seq:1}))
const dryId=await run.dryRun(5,GRAPH);await settle()
eq("run: a dry run sends the unsaved graph, no confirmation, mode dry",[dryId,calls[0][0],calls[0][1][1].mode,calls[0][1][1].graph.nodes.length,calls[0][1][1].confirmed],["d1","flows.run","dry",6,null].map((v,i)=>i===4?undefined:v))
check("run: the dry-run report is shown and labelled",/Dry run - nothing was executed/.test(run.el.querySelector('[data-pane="dry"]').innerHTML)&&/\$ ping -c 2 10\.0\.0\.5/.test(run.el.querySelector('[data-pane="dry"]').innerHTML)&&run.el.querySelector('[data-pane="dry"]').classList.contains("is-hidden")===false&&box.timers.length===0)
// history
handlers["flows.runs"]=()=>Promise.resolve([{run_id:"r1",chain_name:"Recon",mode:"run",state:"done",started_at:"2026-01-01T10:00:00+00:00",ended_at:"2026-01-01T10:00:09+00:00"}])
handlers["flows.run_get"]=()=>Promise.resolve(Object.assign(JSON.parse(JSON.stringify(SDONE)),{name:"Recon",events:[EV(1,"stored")]}))
await run.showHistory(5);await settle()
eq("run: history asks for this chain's runs",calls.filter((c)=>c[0]==="flows.runs")[0][1],[5,30])
check("run: history lists stored runs",/data-fr="hist-open" data-run="r1"/.test(run.el.querySelector('[data-pane="history"]').innerHTML))
const paintsBefore=red.runStates.length
click(run.el,"[data-fr]",{fr:"hist-open",run:"r1"});await settle()
eq("run: a history entry reopens the stored run on the canvas without polling",[calls.filter((c)=>c[0]==="flows.run_get")[0][1],red.runStates.length-paintsBefore,red.runStates[red.runStates.length-1].state,box.timers.length,run.isWatching()],[["r1"],1,"done",0,false])
handlers["flows.run_delete"]=()=>Promise.resolve(true)
click(run.el,"[data-fr]",{fr:"hist-del",run:"r1"});await settle()
eq("run: deleting a history entry reloads the list",[calls.filter((c)=>c[0]==="flows.run_delete")[0][1],calls.filter((c)=>c[0]==="flows.runs").length],[["r1"],2])
// stopWatching / unknown run / destroy
answer=()=>Promise.resolve(JSON.parse(JSON.stringify(S1)))
run.attach("r1");await settle()
run.stopWatching()
eq("run: stopWatching clears the timer",[box.timers.length,run.isWatching()],[0,false])
answer=()=>Promise.reject(new Error("No such run."))
run.attach("gone");await settle()
eq("run: an unknown run stops polling instead of retrying forever",[box.timers.length,run.isWatching(),run.el.querySelector(".fr-conn").textContent],[0,false,"This run is no longer available."])
let release
answer=()=>new Promise((resolve)=>{release=()=>resolve(JSON.parse(JSON.stringify(S1)))})
run.attach("r1");await settle()
const paints=red.runStates.length
run.destroy()
release();await settle()
eq("run: destroy stops polling; a late answer is ignored; the canvas is cleared",[box.timers.length,red.runStates.length-paints,red.runStates[red.runStates.length-1],rhost.children.length],[0,1,null,0])
answer=()=>Promise.resolve(JSON.parse(JSON.stringify(S1)))
const run2=P.flowRunCreate(new FakeEl("section"),red,{bridge:bridge})
run2.attach("r1");await settle()
run2.clear()
eq("run: clear() hides the panel, stops polling and unpaints the canvas",[box.timers.length,run2.el.classList.contains("is-hidden"),red.runStates[red.runStates.length-1],run2.runId()],[0,true,null,null])
run2.destroy()
}
panels().catch((err)=>{failed++;console.log("  FAIL  panels threw  ->  "+(err&&err.stack?err.stack:err))}).then(()=>{
console.log("\nflow_panels: "+passed+" passed, "+failed+" failed")
process.exit(failed?1:0)
})
