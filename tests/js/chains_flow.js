// The diagram view of the Chains page (UI/js/pages/chains_flow.js): pure helpers, the hooks pages/chains.js calls, a mounted
// view against fake panels (save, dirty marker, leave prompt, draft, validation), and how the file is wired into the app.
const fs=require("fs")
const path=require("path")
const vm=require("vm")
const ROOT=path.resolve(__dirname,"..","..")
const read=(...p)=>fs.readFileSync(path.join(ROOT,...p),"utf8")
const SRC=read("UI","js","pages","chains_flow.js")
const MODEL=read("UI","js","components","flow-model.js")
const RULES=read("UI","js","components","flow-rules.js")
const MAIN=read("UI","windows","main.html")
const PAGE=read("UI","js","pages","chains.js")
const AC=read("UI","js","components","action-chains.js")
const SHORTCUTS=read("UI","js","components","shortcuts.js")
const EDITOR=read("UI","js","components","flow-editor.js")
const CSS=read("UI","css","flow-panels.css")
const GLASS=read("UI","css","glass.css")
let passed=0,failed=0
function check(name,cond,detail){if(cond){passed++;return}failed++;console.log("  FAIL  "+name+(detail?"  ->  "+detail:""))}
function eq(name,a,b){check(name,JSON.stringify(a)===JSON.stringify(b),JSON.stringify(a)+" != "+JSON.stringify(b))}
// ---- a tiny fake DOM: elements found by id or by the selectors the view uses
class El{
constructor(tag){
this.tagName=String(tag||"div").toUpperCase();this.children=[];this.dataset={};this.style={props:{},setProperty(k,v){this.props[k]=String(v)},getPropertyValue(k){return this.props[k]||""},removeProperty(k){delete this.props[k]}};this.listeners={};this.parentNode=null
this.textContent="";this.title="";this.value="";this.disabled=false;this._html="";this._q={};this.id=""
const set=new Set()
this.classList={add:(...c)=>c.forEach((x)=>set.add(x)),remove:(...c)=>c.forEach((x)=>set.delete(x)),contains:(c)=>set.has(c),toggle:(c,on)=>{const want=on===undefined?!set.has(c):!!on;if(want)set.add(c);else set.delete(c);return want}}
this._set=set
}
get className(){return Array.from(this._set).join(" ")}
set className(v){this._set.clear();String(v||"").split(/\s+/).filter(Boolean).forEach((c)=>this._set.add(c))}
get innerHTML(){return this._html}
set innerHTML(v){this._html=String(v);this._q={};this.children=[]}
appendChild(c){c.parentNode=this;this.children.push(c);return c}
insertBefore(c,ref){c.parentNode=this;const i=this.children.indexOf(ref);this.children.splice(i<0?this.children.length:i,0,c);return c}
remove(){if(this.parentNode)this.parentNode.children=this.parentNode.children.filter((x)=>x!==this)}
addEventListener(t,fn){(this.listeners[t]=this.listeners[t]||[]).push(fn)}
setAttribute(k,v){(this._attrs=this._attrs||{})[k]=String(v)}
getAttribute(k){return this._attrs&&k in this._attrs?this._attrs[k]:null}
removeEventListener(){}
querySelector(sel){if(!(sel in this._q)){const el=new El("div");el.parentNode=this;this._q[sel]=el}return this._q[sel]}
querySelectorAll(){return []}
contains(other){for(let n=other;n;n=n.parentNode)if(n===this)return true;return false}
focus(){}
closest(){return null}
}
function makeBox(){
const ids={}
const byId=(id)=>ids[id]||(ids[id]=Object.assign(new El("div"),{id:id}))
;["chainsFlowHost","cmdsPlaybooksWrap","chainsOpenDiagramBtn","chainsToolbarSlot","cmdsPlaybooksList"].forEach(byId)
ids.chainsOpenDiagramBtn.classList.add("hidden");ids.chainsFlowHost.classList.add("hidden")
const page=new El("section");page.classList.add("active")
const docListeners={}
const calls=[],handlers={},toasts=[],confirms=[]
let confirmAnswer=true
const box={console:{log(){},warn(){},error(){}},JSON,Math,Promise,Object,Array,String,Number,Date,Error,Set,
setTimeout:(fn)=>{box.timers.push(fn);return box.timers.length},clearTimeout:()=>{},requestAnimationFrame:(fn)=>{box.timers.push(fn);return 1},timers:[],
module:{exports:{}},
document:{body:new El("body"),activeElement:null,getElementById:(id)=>ids[id]||null,createElement:(t)=>new El(t),addEventListener:(t,fn)=>{(docListeners[t]=docListeners[t]||[]).push(fn)},
querySelector:(sel)=>sel.indexOf('data-page="chains"')>=0?page:null,querySelectorAll:()=>[]},
bridgeCall:(name,args)=>{calls.push([name,args||[]]);const h=handlers[name];try{return Promise.resolve(h?h.apply(null,args||[]):null)}catch(err){return Promise.reject(err)}},
showToast:(m,k)=>toasts.push([m,k||""]),
appConfirm:(msg,opts)=>{confirms.push([msg,opts||{}]);return Promise.resolve(typeof confirmAnswer==="function"?confirmAnswer(msg):confirmAnswer)},
goToPage:()=>Promise.resolve(),
chainsState:{items:[],currentId:null,currentPlaybook:null},
chainsRenderList:()=>{box.renders=(box.renders||0)+1},
chainsRefreshList:()=>{box.refreshes=(box.refreshes||0)+1;return Promise.resolve()},
chainsOpenChain:(id)=>{box.opened=(box.opened||[]).concat([id])},
termState:{enabled:true},
navigator:{}}
// fake panels: just what chains_flow.js touches
box.flowEditorCreate=(host,opts)=>{
const ed={el:new El("div"),graph:JSON.parse(JSON.stringify(opts.graph)),opts:opts,issues:null,focused:0,fits:0,
getGraph(){return JSON.parse(JSON.stringify(ed.graph))},setGraph(g){ed.graph=JSON.parse(JSON.stringify(g))},setIssues(i){ed.issues=i},select(ids){ed.sel=ids},focus(){ed.focused++},fit(){ed.fits++},destroy(){ed.destroyed=true},
updateNode(id,fn){const n=ed.graph.nodes.find((x)=>x.id===id);fn(n,ed.graph);opts.onChange(ed.getGraph());return true},
change(fn){fn(ed.graph);opts.onChange(ed.getGraph())}}
box.editor=ed
return ed
}
box.flowInspectorCreate=(host,editor,deps)=>{const insp={el:new El("div"),deps:deps,shown:undefined,flushed:0,refreshed:0,show(id){insp.shown=id},refresh(){insp.refreshed++},setIssues(i){insp.issues=i},flush(){insp.flushed++},destroy(){insp.destroyed=true}};box.inspector=insp;return insp}
box.flowRunCreate=(host,editor,deps)=>{const run={deps:deps,calls:[],watching:false,confirmAndRun(id,o){run.calls.push(["run",id,o]);return Promise.resolve("r1")},dryRun(id,g){run.calls.push(["dry",id,g]);return Promise.resolve("d1")},showHistory(id){run.calls.push(["history",id])},showStored(id){run.calls.push(["stored",id])},attach(id){run.calls.push(["attach",id])},isWatching(){return run.watching},status(){return null},destroy(){run.destroyed=true}};(box.runs=box.runs||[]).push(run);if(editor)box.run=run;return run}
vm.createContext(box)
vm.runInContext(MODEL+"\n"+RULES+"\n"+SRC,box)
// let/const of the scripts are not properties of the sandbox: fetch them by name
const get=(expr)=>vm.runInContext(expr,box)
return {box,ids,page,docListeners,calls,handlers,toasts,confirms,get,setConfirm:(v)=>{confirmAnswer=v},C:box.module.exports}
}
const flush=async(box)=>{for(let i=0;i<12;i++){await Promise.resolve();await new Promise((r)=>setImmediate(r));const t=box.timers.splice(0);t.forEach((fn)=>{try{fn()}catch(_){}})}}
const GRAPH={schema:1,settings:{shell:"",run_timeout:1800,max_visits:200,on_error:"stop"},nodes:[{id:"n1",type:"start",title:"Start",x:0,y:0,config:{trigger:"manual"}},{id:"n2",type:"command",title:"Ping",x:280,y:0,config:{commands:[{text:"ping -c 1 {IPv4}",command_id:null,src:"",label:""}],mode:"sequence",stop_on_fail:true,timeout:300,shell:""}}],edges:[{id:"e1",from:"n1",port:"out",to:"n2"}],viewport:{x:0,y:0,zoom:1}}
const LIST=[{playbook_id:1,name:"Linear one",caller:"lin",step_count:3,has_graph:false,node_count:4,ai_made:false,ai_reviewed:true},{playbook_id:2,name:"Diagram <b>",caller:"dia",step_count:2,has_graph:true,node_count:6,ai_made:false,ai_reviewed:true},{playbook_id:3,name:"From AI",caller:"",step_count:0,has_graph:true,node_count:1,ai_made:true,ai_reviewed:false},{playbook_id:4,name:"From file",caller:"",step_count:0,has_graph:true,node_count:2,ai_made:false,ai_reviewed:false}]
;(async()=>{
// ---- pure helpers
const scripts=(MAIN.match(/<script src="\.\.\/js\/[^"]+"><\/script>/g)||[]).map((s)=>/js\/([^"]+)"/.exec(s)[1])
const at=(name)=>scripts.indexOf(name)
const T=makeBox(),C=T.C
const idx=C.chainsFlowIndex(LIST)
eq("index: only chains with a diagram are in ids",Object.keys(idx.ids),["2","3","4"])
eq("index: meta per chain",[idx.meta["1"].hasGraph,idx.meta["1"].steps,idx.meta["2"].nodes,idx.meta["3"].aiMade,idx.meta["3"].reviewed,idx.meta["2"].reviewed],[false,3,6,true,false,true])
eq("index: junk in, empty out",[C.chainsFlowIndex(null),C.chainsFlowIndex([null,{},{playbook_id:null}])],[{ids:{},meta:{}},{ids:{},meta:{}}])
eq("badges: a linear chain has none",C.chainsFlowBadges(idx.meta["1"]),[])
eq("badges: Diagram",C.chainsFlowBadges(idx.meta["2"]).map((b)=>b.text),["Diagram"])
eq("badges: AI-made and imported chains ask for a review until reviewed",[C.chainsFlowBadges(idx.meta["3"]).map((b)=>b.text),C.chainsFlowBadges(idx.meta["4"]).map((b)=>b.text)],[["Diagram","AI-made - review"],["Diagram","Imported - review"]])
check("badges: html is escaped and classed",/^<span class="cf-badge cf-badge-diagram" title="[^"<>]*">Diagram<\/span><span class="cf-badge cf-badge-ai"/.test(C.chainsFlowBadgesHtml(idx.meta["3"])))
const g2=JSON.parse(JSON.stringify(GRAPH));g2.viewport={x:50,y:-9,zoom:0.5}
check("sig: panning or zooming is not a change",C.chainsFlowGraphSig(GRAPH)===C.chainsFlowGraphSig(g2))
const g3=JSON.parse(JSON.stringify(GRAPH));g3.nodes[1].x=300
const g4=JSON.parse(JSON.stringify(GRAPH));g4.settings.on_error="continue"
check("sig: moving a node, or a setting, is",C.chainsFlowGraphSig(GRAPH)!==C.chainsFlowGraphSig(g3)&&C.chainsFlowGraphSig(GRAPH)!==C.chainsFlowGraphSig(g4))
eq("sig: null-safe",C.chainsFlowGraphSig(null),'{"s":{},"n":[],"e":[]}')
eq("blank: only the Start node counts as blank",[C.chainsFlowIsBlank({nodes:[{type:"start"}]}),C.chainsFlowIsBlank(GRAPH),C.chainsFlowIsBlank(null)],[true,false,true])
eq("issues: summary text and class",[C.chainsFlowIssueSummary({errors:[],warnings:[]}),C.chainsFlowIssueSummary({errors:[{}],warnings:[{},{}]}),C.chainsFlowIssueSummary({warnings:[{}]}),C.chainsFlowIssueSummary(null)].map((s)=>s.cls+":"+s.text),["is-ok:No issues","is-error:1 error, 2 warnings","is-warn:1 warning","is-ok:No issues"])
const issuesHtml=C.chainsFlowIssuesHtml({errors:[{node:"n2",message:"<img src=x onerror=1>"}],warnings:[{node:null,message:"loose end"}]})
check("issues: list is escaped, errors first, node id carried",issuesHtml.indexOf("<img")<0&&/cf-issue-error" data-cf="issue" data-node="n2"[\s\S]*cf-issue-warn" data-cf="issue" data-node=""/.test(issuesHtml))
check("issues: an empty list says the diagram can run",/can run/.test(C.chainsFlowIssuesHtml({errors:[],warnings:[]})))
eq("bundle: the export format import_json reads",JSON.parse(C.chainsFlowBundle("N","c",{nodes:[],edges:[]})),{loya_chain:1,name:"N",caller:"c",graph:{nodes:[],edges:[]}})
eq("run source: where the run was asked for",["chains","commands",undefined,"terminal","ai","live","palette"].map(C.chainsFlowRunSource),["manual","manual","manual","caller","caller","live","caller"])
eq("file name: a safe slug",[C.chainsFlowFileName("Host alive / check!"),C.chainsFlowFileName(""),C.chainsFlowFileName("../../etc")],["host-alive-check.loya-chain.json","chain.loya-chain.json","etc.loya-chain.json"])
const tpl=C.chainsFlowTemplatesHtml([{id:"a<b",name:"<i>N</i>",description:"D & d"}])
check("templates: escaped cards with both actions",tpl.indexOf("<i>")<0&&tpl.indexOf("D &amp; d")>0&&/data-cf-tpl="new" data-id="a&lt;b"/.test(tpl)&&/data-cf-tpl="here"/.test(tpl))
check("templates: empty list",/No starter templates/.test(C.chainsFlowTemplatesHtml(null)))
eq("head: a clean saved diagram",C.chainsFlowHeadState({playbookId:2,reviewed:true,steps:3}),{canSave:false,saveLabel:"Save",canRun:true,needsSaved:false,canRevert:true,canDelete:true,banner:""})
eq("head: a derived linear chain offers the conversion, not Revert",[C.chainsFlowHeadState({playbookId:1,derived:true,reviewed:true,steps:3}).saveLabel,C.chainsFlowHeadState({playbookId:1,derived:true,reviewed:true,steps:3}).canSave,C.chainsFlowHeadState({playbookId:1,derived:true,reviewed:true,steps:3}).canRevert,C.chainsFlowHeadState({playbookId:1,derived:true,reviewed:true}).banner],["Save as diagram",true,false,"derived"])
eq("head: an unsaved draft cannot be exported, reverted or deleted",(()=>{const h=C.chainsFlowHeadState({playbookId:null,draft:true,dirty:true,reviewed:false});return [h.canSave,h.needsSaved,h.canRevert,h.canDelete,h.banner]})(),[true,true,false,false,"review"])
eq("head: no Revert without steps to go back to; no Save while saving",[C.chainsFlowHeadState({playbookId:2,reviewed:true,steps:0}).canRevert,C.chainsFlowHeadState({playbookId:2,reviewed:true,dirty:true,saving:true}).canSave],[false,false])
eq("settings: script isolation is stored only as an explicit override",[C.chainsFlowCleanSettings({script_isolation:"allow"},{}).script_isolation,C.chainsFlowCleanSettings({script_isolation:"sandboxed"},{script_isolation:"allow"}).script_isolation,"script_isolation" in C.chainsFlowCleanSettings({script_isolation:"inherit"},{script_isolation:"allow"}),C.chainsFlowCleanSettings({},{script_isolation:"allow"}).script_isolation,"script_isolation" in C.chainsFlowCleanSettings({script_isolation:"root"},{})],["allow","sandboxed",false,"allow",false])
check("settings: the dialog offers the three isolation choices and says when Allow is ignored",/data-iso="inherit"[\s\S]*data-iso="sandboxed"[\s\S]*data-iso="allow"[\s\S]*Ignored for AI-made or unreviewed diagrams/.test(SRC))
check("main: flow-settings.js loads before settings.js, which mounts it into its container",at("components/flow-settings.js")>=0&&at("components/flow-settings.js")<at("pages/settings.js")&&read("UI","js","pages","settings.js").includes('if(typeof flowSettingsMount==="function")flowSettingsMount(document.getElementById("setFlowBox"))')&&read("UI","pages","settings.html").includes('<div class="set-box glass-panel hidden" id="setFlowBox"></div>'))
check("review: marking as reviewed explains it becomes a normal chain and clears the AI flag in the view",/It becomes a normal chain/.test(SRC)&&/flows\.mark_reviewed",\[open\.playbookId\]\)\.then\(\(\)=>\{open\.reviewed=true;open\.aiMade=false/.test(SRC))
check("auto-wire: the editor's hint reaches the user",/onAutoWire:\(info\)=>chainsFlowToast\("Both success and fail now lead to \\""\+info\.to/.test(SRC))
const FS=require(path.join(ROOT,"UI","js","components","flow-settings.js"))
eq("flow settings: model from the policy",[FS.flowSettingsModel({script_isolation:"allow",sandbox:{sandbox:"bwrap",network_isolation:true}}),FS.flowSettingsModel({script_isolation:"x",sandbox:{sandbox:"none"}}).mode,FS.flowSettingsModel(null).hasSandbox,/No sandbox on this system/.test(FS.flowSettingsModel({}).detected)],[{mode:"allow",hasSandbox:true,sandbox:"bwrap",detected:"bubblewrap is available on this system: scripts run inside it, without network access unless a script node turns it on."},"sandboxed",false,true])
const fsHtml=FS.flowSettingsHtml(FS.flowSettingsModel({script_isolation:"sandboxed",sandbox:{sandbox:"none"}}))
check("flow settings: two choices with a sentence each, the current one checked, the detected sandbox stated",/value="sandboxed" checked/.test(fsHtml)&&/value="allow">/.test(fsHtml)&&/Sandboxed only/.test(fsHtml)&&/Allow unsandboxed scripts/.test(fsHtml)&&/flow-set-detected is-none">No sandbox on this system/.test(fsHtml)&&/Never applies to AI-made or unreviewed diagrams/.test(fsHtml))
eq("settings: clamped and whitelisted",[C.chainsFlowCleanSettings({run_timeout:"5",max_visits:99999,on_error:"explode",shell:"bash"},{on_error:"continue"}),C.chainsFlowCleanSettings(null,null)],[{shell:"bash",run_timeout:10,max_visits:2000,on_error:"continue"},{shell:"",run_timeout:1800,max_visits:200,on_error:"stop"}])
const root=new El("div"),inside=new El("input"),outside=new El("textarea"),body=new El("body");root.appendChild(inside)
eq("ctrl+s: owned inside the view or with focus on the body, never under a dialog or in another panel",[C.chainsFlowOwnsSave(inside,root,body,false),C.chainsFlowOwnsSave(body,root,body,false),C.chainsFlowOwnsSave(null,root,body,false),C.chainsFlowOwnsSave(outside,root,body,false),C.chainsFlowOwnsSave(inside,root,body,true),C.chainsFlowOwnsSave(inside,null,body,false)],[true,true,true,false,false,false])
eq("bridge: a missing method is told apart from a refusal",[C.chainsFlowBridgeMissing(new Error("bridge method missing: flows.export_file")),C.chainsFlowBridgeMissing(new Error("locked")),C.chainsFlowBridgeMissing(null)],[true,false,false])
check("issues: an open fail port says what it means",C.chainsFlowIssuesHtml({errors:[],warnings:[{node:"n2",code:"port_unconnected",message:"Ping: nothing is connected to 'fail'."}]}).indexOf("stops the run unless its fail port is connected or the diagram&#39;s On error setting is Continue.")>0)
check("files: native export/import dialogs first, the old ways when the bridge lacks them",/bridgeCall\("flows\.export_file",\[open\.playbookId\]\)[\s\S]{0,200}chainsFlowBridgeMissing\(err\)[\s\S]{0,80}terminal\.save_output_to_file/.test(SRC)&&/bridgeCall\("flows\.import_file",\[\]\)[\s\S]{0,260}chainsFlowBridgeMissing\(e\)\)file\.click\(\)/.test(SRC))
eq("error text",[C.chainsFlowErrorText(new Error("boom"),"x"),C.chainsFlowErrorText(null,"fallback"),C.chainsFlowErrorText("plain","x")],["boom","fallback","plain"])
const viewHtml=C.chainsFlowViewHtml()
eq("view: every header action is there",["back","save","run","dry","history","settings","templates","import","export","revert","delete","issues"].filter((a)=>viewHtml.indexOf('data-cf="'+a+'"')<0),[])
check("view: editor, run panel and inspector hosts",/class="cf-main"><div class="cf-left"><div class="cf-editor"><\/div><div class="cf-run hidden"><\/div><\/div><div class="cf-side"><\/div>/.test(viewHtml)&&/class="cf-banner hidden"/.test(viewHtml))
// ---- hooks and the mounted view
T.handlers["flows.list"]=()=>LIST
T.handlers["flows.catalog"]=()=>({templates:[{id:"t1",name:"T1",description:"d"}],shells:[]})
T.handlers["flows.prefs_get"]=()=>({snap:false,grid:10,minimap:true,inspector_width:400})
T.handlers["flows.get"]=(id)=>({playbook_id:id,name:id===1?"Linear one":"Diagram <b>",caller:"dia",graph:JSON.parse(JSON.stringify(GRAPH)),derived:id===1,ai_made:false,ai_reviewed:true,errors:[],warnings:[{node:"n2",message:"w"}]})
T.handlers["flows.active_runs"]=()=>[]
T.handlers["flows.validate"]=(g)=>({ok:true,errors:[],warnings:[],graph:g})
T.handlers["flows.save"]=(id)=>{LIST.forEach((r)=>{if(r.playbook_id===id)r.has_graph=true});return {ok:true,errors:[],warnings:[]}}
const st=T.get("chainsFlowState")
eq("hook: before the page exists nothing mounts and nothing is taken",(()=>{const B=makeBox();B.ids.chainsFlowHost=null;return [B.box.chainsFlowOpenChain(2),B.get("chainsFlowState").mounted]})(),[false,false])
check("hook: an unknown chain is left to the step list (and the page gets mounted)",T.box.chainsFlowOpenChain(2)===false&&st.mounted===true)
check("mount: no separate New Diagram button is wired any more",!SRC.includes("chainsNewDiagramBtn"))
check("mount: the Open Diagram button is shown and an Import button is added",!T.ids.chainsOpenDiagramBtn.classList.contains("hidden")&&T.ids.chainsToolbarSlot.children.length===1&&/Import/.test(T.ids.chainsToolbarSlot.children[0].innerHTML))
await flush(T.box)
check("mount: flows.list fills the cache and the list is drawn again",st.loaded&&st.ids["2"]===true&&!st.ids["1"]&&T.box.renders>=1)
eq("mount: catalog and prefs come through the bridge, not localStorage",[T.calls.some((c)=>c[0]==="flows.catalog"),T.calls.some((c)=>c[0]==="flows.prefs_get"),/localStorage|sessionStorage/.test(SRC.replace(/^\/\/.*$/gm,""))],[true,true,false])
const card=new El("button"),count=new El("span");count.classList.add("cmds-playbook-card-count");card._q[".cmds-playbook-card-count"]=count;card.appendChild(count)
T.box.chainsFlowDecorateCard(card,{id:3})
check("card: badges before the count, which now counts nodes",card.classList.contains("cf-card-diagram")&&card.children.length===2&&card.children[0].classList.contains("cf-badges")&&/AI-made - review/.test(card.children[0].innerHTML)&&count.textContent==="1 node")
const plain=new El("button");T.box.chainsFlowDecorateCard(plain,{id:1})
check("card: a linear chain is left alone",plain.children.length===0&&!plain.classList.contains("cf-card-diagram"))
check("hook: a diagram chain is taken synchronously",T.box.chainsFlowOpenChain(2)===true)
await flush(T.box)
const open=st.open
check("open: the view is mounted and the list is hidden",!!open&&open.playbookId===2&&!T.ids.chainsFlowHost.classList.contains("hidden")&&T.ids.chainsFlowHost.classList.contains("cf-full")&&T.ids.cmdsPlaybooksWrap.classList.contains("hidden"))
eq("open: prefs reach the editor, the width reaches the inspector host",[T.box.editor.opts.prefs,T.ids.chainsFlowHost.querySelector(".cf-side").style.width],[{snap:false,grid:10,minimap:true,hotbar:null},"400px"])
eq("open: the inspector width is also a CSS variable on the view (the hot bar centres beside the panel)",T.ids.chainsFlowHost.querySelector(".cf-view").style.getPropertyValue("--cf-side-w"),"400px")
// the redesigned editor: node double-click / status pill open the properties panel on a tab, run state reaches the inspector, pins are saved
{const insp=T.box.inspector,tabs=[],runs=[];insp.setTab=(t)=>tabs.push(t);insp.setRun=(s)=>runs.push(s)
const root0=T.ids.chainsFlowHost.querySelector(".cf-view");root0.classList.remove("cf-has-sel")
T.box.editor.opts.onOpenNode("n2","output")
eq("editor: onOpenNode(id,'output') shows the node on the Output tab and reveals the panel",[insp.shown,tabs,root0.classList.contains("cf-has-sel")],["n2",["output"],true])
T.box.editor.opts.onOpenNode("n2");T.box.editor.opts.onOpenNode("n2","anything")
eq("editor: any other tab value falls back to the parameters tab",tabs,["output","params","params"])
const rs={status:"running",nodes:{}};T.box.editor.opts.onRunState(rs);T.box.editor.opts.onRunState(null)
eq("editor: onRunState is passed on to inspector.setRun",runs,[rs,null])
delete insp.setTab;delete insp.setRun
check("editor: an inspector without setTab / setRun does not break the callbacks",(()=>{try{T.box.editor.opts.onOpenNode("n2","output");T.box.editor.opts.onRunState(rs);return true}catch(_){return false}})())
const n0=T.calls.filter((c)=>c[0]==="flows.prefs_set").length
T.box.editor.opts.onPrefs({hotbar:["command","http"]})
eq("editor: pinning a node saves prefs.hotbar through the bridge and keeps the other prefs",[T.calls.filter((c)=>c[0]==="flows.prefs_set").slice(n0).map((c)=>c[1]),st.prefs.hotbar,st.prefs.grid,st.prefs.inspector_width],[[[{hotbar:["command","http"]}]],["command","http"],10,400])
T.box.inspector.deps.onResize(444)
eq("inspector: resizing updates the CSS variable and the remembered width, pins survive",[root0.style.getPropertyValue("--cf-side-w"),st.prefs.inspector_width,st.prefs.hotbar],["444px",444,["command","http"]])
T.box.inspector.deps.onResize(400)
// the History button: the run panel's own list while the Chains page has no Run History tab
const click=(what)=>root0.listeners.click.forEach((fn)=>fn({target:{closest:(sel)=>sel==="[data-cf]"?{dataset:{cf:what},disabled:false}:null}}))
const h0=T.box.run.calls.length;click("history")
eq("history: without loyaOpenChainHistory the run panel lists the runs",T.box.run.calls.slice(h0),[["history",2]])}
eq("open: issues from flows.get paint both panels",[T.box.editor.issues.warnings.length,T.box.inspector.issues.warnings.length,open.dirty,open.steps],[1,1,false,2])
check("open: the same chain again is a no-op that still takes over",T.box.chainsFlowOpenChain(2)===true&&st.open===open)
const vroot=st.view.root
eq("head: name is set as text, never as html",[vroot.querySelector(".cf-name").textContent,vroot.querySelector(".cf-caller").textContent,vroot.querySelector(".cf-dirty").classList.contains("hidden"),vroot.querySelector('[data-cf="save"]').disabled],["Diagram <b>","/dia",true,true])
// an edit: dirty marker, inspector refresh, debounced bridge validation
T.handlers["flows.validate"]=(g)=>({ok:false,errors:[{node:"n2",message:"bad"}],warnings:[],graph:g})
T.box.editor.change((g)=>{g.nodes[1].title="Ping twice"})
eq("edit: marks the diagram unsaved at once",[open.dirty,vroot.querySelector(".cf-dirty").classList.contains("hidden"),vroot.querySelector('[data-cf="save"]').disabled,T.box.inspector.refreshed>0],[true,false,false,true])
await flush(T.box)
eq("edit: validation runs through the bridge and lands in both panels and the chip",[T.calls.filter((c)=>c[0]==="flows.validate").length,T.box.editor.issues.errors.length,T.box.inspector.issues.errors.length,vroot.querySelector(".cf-status").textContent],[1,1,1,"1 error"])
// leaving with unsaved changes asks first
T.setConfirm(false)
check("leave: opening another chain asks, and staying keeps everything",T.box.chainsFlowOpenChain(1)===true)
await flush(T.box)
eq("leave: Keep editing",[st.open===open,T.confirms.length,T.confirms[0][1].extraLabel,T.confirms[0][1].danger,T.box.opened||[]],[true,1,"Save",true,[]])
// running with unsaved changes saves first
T.setConfirm(true)
const clickOn=(act)=>{const btn=new El("button");btn.dataset.cf=act;btn.closest=(sel)=>sel==="[data-cf]"?btn:null;vroot.listeners.click.forEach((fn)=>fn({target:btn}))}
clickOn("run")
await flush(T.box)
eq("run: unsaved changes are saved, then the SAVED diagram is confirmed and run",[T.calls.filter((c)=>c[0]==="flows.save").map((c)=>c[1][0]),T.box.run.calls.filter((c)=>c[0]==="run").map((c)=>[c[1],c[2].name,c[2].source]),open.dirty,T.box.inspector.flushed>0],[[2],[[2,"Diagram <b>","manual"]],false,true])
check("save: says so and refreshes the index",T.toasts.some((t)=>t[0]==="Diagram saved")&&T.calls.filter((c)=>c[0]==="flows.list").length>=2)
T.box.editor.change((g)=>{g.nodes[1].x=500})
clickOn("dry")
await flush(T.box)
eq("dry run: uses the unsaved diagram as it is on screen, without saving",[T.box.run.calls.filter((c)=>c[0]==="dry").map((c)=>[c[1],c[2]&&c[2].nodes[1].x]),T.calls.filter((c)=>c[0]==="flows.save").length],[[[2,500]],1])
T.box.termState.enabled=false
clickOn("run")
await flush(T.box)
eq("run: refused while the terminal is disabled",[T.box.run.calls.filter((c)=>c[0]==="run").length,T.toasts.some((t)=>/Enable the terminal/.test(t[0]))],[1,true])
T.box.termState.enabled=true
// Ctrl+S
const key=(k,extra)=>{const e=Object.assign({key:k,ctrlKey:true,prevented:false,preventDefault(){e.prevented=true},stopPropagation(){}},extra||{});T.docListeners.keydown.forEach((fn)=>fn(e));return e}
T.box.document.activeElement=T.box.document.body
const ks=key("s")
await flush(T.box)
eq("ctrl+s: saves the open diagram",[ks.prevented,T.calls.filter((c)=>c[0]==="flows.save").length,open.dirty],[true,2,false])
eq("ctrl+s: other chords and other pages are left alone",(()=>{const a=key("s",{shiftKey:true}).prevented;T.page.classList.remove("active");const b=key("s").prevented;T.page.classList.add("active");return [a,b]})(),[false,false])
// settings go through updateNode so they are one undo step and count as a change
T.box.editor.updateNode("n1",(n,g)=>{g.settings.on_error="continue"})
check("settings: a changed setting marks the diagram unsaved",open.dirty===true)
// discard and leave
clickOn("back")
await flush(T.box)
eq("back: discarding closes the view and shows the list again",[st.open,T.box.editor.destroyed,T.box.inspector.destroyed,T.box.run.destroyed,T.ids.chainsFlowHost.classList.contains("hidden"),T.ids.cmdsPlaybooksWrap.classList.contains("hidden"),T.box.refreshes>=1],[null,true,true,true,true,false,true])
// a linear chain opened as a diagram: saving converts it, after a plain explanation
await T.box.chainsFlowOpen(1)
await flush(T.box)
const lin=st.open
eq("derived: banner and Save as diagram",[lin.derived,lin.steps,st.view.root.querySelector(".cf-banner").className,st.view.root.querySelector('[data-cf="save"]').querySelector("span").textContent,st.view.root.querySelector('[data-cf="save"]').disabled],[true,3,"cf-banner cf-banner-info","Save as diagram",false])
T.confirms.length=0
T.setConfirm(false)
eq("derived: declining the conversion saves nothing",[await T.box.chainsFlowSave(),T.calls.filter((c)=>c[0]==="flows.save").length,/runs as the diagram everywhere/.test(T.confirms[0][1].bodyHtml)&&/Revert to linear/.test(T.confirms[0][1].bodyHtml)&&/3 steps/.test(T.confirms[0][1].bodyHtml)],[false,2,true])
T.setConfirm(true)
eq("derived: accepting converts it; Revert to linear appears",[await T.box.chainsFlowSave(),lin.derived,st.ids["1"],T.get("chainsFlowHeadState")(lin).canRevert],[true,false,true,true])
// revert
T.handlers["flows.revert_linear"]=(id)=>{LIST.forEach((r)=>{if(r.playbook_id===id)r.has_graph=false});return true}
st.view.root.listeners.click.forEach((fn)=>{const btn=new El("button");btn.dataset.cf="revert";btn.closest=(sel)=>sel==="[data-cf]"?btn:null;fn({target:btn})})
await flush(T.box)
eq("revert: the diagram is dropped and the step list opens",[T.calls.some((c)=>c[0]==="flows.revert_linear"&&c[1][0]===1),st.ids["1"],st.open,(T.box.opened||[]).slice(-1)],[true,undefined,null,[1]])
// an AI draft: nothing stored until Save, which goes through the import path so it stays "not reviewed"
T.handlers["flows.import_json"]=(text,name)=>{T.imported=[JSON.parse(text),name];return {playbook_id:9,warnings:[]}}
eq("draft: opens unsaved with the review banner",[await T.box.loyaOpenChainDraft({name:"AI idea",graph:GRAPH,ai_made:true}),st.open.draft,st.open.dirty,st.open.playbookId,st.view.root.querySelector(".cf-banner").className,/AI-made - review before running/.test(st.view.root.querySelector(".cf-banner").innerHTML),/reviewed/.test(st.view.root.querySelector(".cf-banner").innerHTML)],[true,true,true,null,"cf-banner cf-banner-ai",true,false])
eq("draft: nothing was written to the bridge",T.calls.filter((c)=>/flows\.(create|create_ai_draft|save|import_json)/.test(c[0])).length,3)
// errors: the draft stays open and the problems are listed
T.handlers["flows.validate"]=(g)=>({ok:false,errors:[{node:"n2",code:"empty_command",message:"This command node has no command."}],warnings:[],graph:g})
T.toasts.length=0
eq("draft: an AI draft with errors is not stored; the errors are shown and it stays open",[await T.box.chainsFlowSave(),st.open.draft,st.open.saving,T.calls.some((c)=>c[0]==="flows.create_ai_draft"),st.open.issues.errors.length,st.view.root.querySelector(".cf-issues-pop").classList.contains("hidden"),/Fix 1 error before saving this AI-made diagram: This command node has no command\./.test((T.toasts[0]||[])[0]),(T.toasts[0]||[])[1]],[false,true,false,false,1,false,true,"error"])
T.handlers["flows.validate"]=(g)=>({ok:true,errors:[],warnings:[],graph:g})
// an older bridge without create_ai_draft: the import path keeps it unreviewed
T.handlers["flows.create_ai_draft"]=()=>{throw new Error("bridge method missing: flows.create_ai_draft")}
eq("draft: without create_ai_draft it is imported, still flagged for review",[await T.box.chainsFlowSave(),T.imported[0].loya_chain,T.imported[0].name,T.imported[0].graph.nodes.length,T.imported[1],st.open.playbookId,st.open.draft,st.open.reviewed,st.open.aiMade],[true,1,"AI idea",2,"AI idea",9,false,false,false])
T.handlers["flows.create_ai_draft"]=(name,graph,client)=>{T.aiDraft=[name,graph.nodes.length,client];return {playbook_id:11,errors:[],warnings:[]}}
st.open.dirty=false
await T.box.loyaOpenChainDraft({name:"AI two",graph:GRAPH,ai_made:true,client:"Claude"})
eq("draft: Save stores an AI draft as AI-made and not reviewed",[await T.box.chainsFlowSave(),T.aiDraft,st.open.playbookId,st.open.draft,st.open.reviewed,st.open.aiMade,/AI-made - review before running/.test(st.view.root.querySelector(".cf-banner").innerHTML)],[true,["AI two",2,"Claude"],11,false,false,true,true])
T.handlers["flows.create_ai_draft"]=()=>{throw new Error("The diagram is not valid: x")}
await T.box.loyaOpenChainDraft({name:"AI three",graph:GRAPH})
eq("draft: a refusal from the bridge keeps the draft open and says why",[await T.box.chainsFlowSave(),st.open.draft,st.open.saving,T.toasts.some((t)=>t[0]==="The diagram is not valid: x"&&t[1]==="error")],[false,true,false,true])
st.open.dirty=false
const kept=st.open
check("draft: a diagram that is not one is refused, and the open diagram stays",await T.box.loyaOpenChainDraft({name:"x",graph:"{not json"})===false&&await T.box.loyaOpenChainDraft({name:"x",graph:{edges:[]}})===false&&T.toasts.some((t)=>t[1]==="error")&&st.open===kept)
T.handlers["flows.create"]=(name,graph)=>{T.created=[name,graph.nodes.length];return {playbook_id:10}}
st.open.dirty=false
await T.box.loyaOpenChainDraft({name:"Mine",graph:GRAPH,ai_made:false})
eq("draft: a draft that is not AI-made is created as a normal chain",[await T.box.chainsFlowSave(),T.created,st.open.reviewed],[true,["Mine",2],true])
// routing a run that starts elsewhere (/caller, the AI input, Run again)
eq("route: a linear chain is not handled",await T.box.chainsFlowRunChain(1,{source:"terminal"}),null)
T.page.classList.remove("active")
const routed=await T.box.chainsFlowRunChain(2,{source:"terminal"})
const headless=T.box.runs[T.box.runs.length-1]
eq("route: a diagram chain goes to the flow confirmation as a caller run",[routed,headless.calls],[{started:true,flow:true,run_id:"r1"},[["run",2,{name:"Diagram <b>",source:"caller"}]]])
T.handlers["flows.list"]=()=>{throw new Error("locked")}
eq("route: when the lookup fails nothing runs (never the old step list of a diagram chain)",[await T.box.chainsFlowRunChain(2,{}),T.toasts.some((t)=>t[0]==="locked"&&t[1]==="error")],[{started:false,flow:true,reason:"error"},true])
// chains changed elsewhere (the AI card)
const before=T.calls.filter((c)=>c[0]==="flows.list").length
T.handlers["flows.list"]=()=>LIST
;(T.docListeners["loya:chains-changed"]||[]).forEach((fn)=>fn({detail:{ids:[2]}}))
await flush(T.box)
check("event: loya:chains-changed refreshes the diagram index",T.calls.filter((c)=>c[0]==="flows.list").length===before+1)
// ---- wiring
// ---- the History button when the Chains page has its Run History tab: leave the diagram (asking when unsaved), then open the tab
{const H=makeBox();Object.assign(H.handlers,T.handlers);H.handlers["flows.list"]=()=>LIST;H.handlers["flows.get"]=(id)=>({playbook_id:id,name:"D",caller:"",graph:JSON.parse(JSON.stringify(GRAPH)),derived:false,ai_made:false,ai_reviewed:true,errors:[],warnings:[]})
const opened=[];H.box.loyaOpenChainHistory=(id)=>opened.push(id)
H.box.chainsFlowOpenChain(2);await flush(H.box);H.box.chainsFlowOpenChain(2);await flush(H.box)
const hs=H.get("chainsFlowState"),hroot=hs.view.root
const click=(what)=>hroot.listeners.click.forEach((fn)=>fn({target:{closest:(sel)=>sel==="[data-cf]"?{dataset:{cf:what},disabled:false}:null}}))
H.box.editor.change((g)=>{g.nodes[1].title="edited"});H.setConfirm(false);click("history");await flush(H.box)
eq("history: with unsaved changes it asks first, and staying opens nothing",[H.confirms.length,opened,!!hs.open,H.box.run.calls.filter((c)=>c[0]==="history").length],[1,[],true,0])
H.setConfirm(true);click("history");await flush(H.box)
eq("history: the Run History tab of the page is opened for this chain and the diagram is closed",[opened,hs.open,H.box.run.calls.filter((c)=>c[0]==="history").length],[[2],null,0])}
eq("main: load order chains.js, catalog, model, rules, editor, fields, inspector, run, log, chains_flow, then app.js",["pages/chains.js","components/flow-catalog.js","components/flow-model.js","components/flow-rules.js","components/flow-editor.js","components/flow-fields.js","components/flow-inspector.js","components/flow-run.js","components/flow-log.js","pages/chains_flow.js"].map(at).every((v,i,a)=>v>=0&&(i===0||v===a[i-1]+1))&&at("pages/chains_flow.js")<at("app.js"),true)
const links=(MAIN.match(/<link rel="stylesheet"[^>]*>/g)||[])
eq("main: flow and chains css right before glass.css, which stays last",links.slice(-6).map((l)=>/css\/([^"]+)"/.exec(l)[1]),["flow-editor.css","flow-panels.css","chains-fields.css","chains-icons.css","chains-studio.css","glass.css"])
check("chains.js: the hooks this file implements are still called",PAGE.includes("chainsFlowDecorateCard(card,pb)")&&PAGE.includes("chainsFlowOpenChain(id)"))
check("action-chains: diagram chains are routed to the flow engine, linear ones fall through",AC.includes('if(!ctx.linear&&typeof chainsFlowRunChain==="function")return chainsFlowRunChain(playbookId,ctx).then((handled)=>handled||acRunChain(playbookId,Object.assign({},ctx,{linear:true})))')&&AC.indexOf("chainsFlowRunChain")>AC.indexOf('showToast("Enable the terminal in Settings first","error")'))
check("shortcuts: the editor's list is on the Ctrl+/ sheet",/typeof FLOW_EDITOR_SHORTCUTS!=="undefined"/.test(SHORTCUTS)&&/scope:"Chain diagram editor"/.test(SHORTCUTS)&&/const FLOW_EDITOR_SHORTCUTS=\[/.test(EDITOR))
const sheet=new Function("FLOW_EDITOR_SHORTCUTS",SHORTCUTS.slice(0,SHORTCUTS.indexOf("function shortcutSheetColumns"))+";return shortcutSheetSections()")([{keys:"F",label:"Fit"}])
eq("shortcuts: the section sits right after Chains and starts with Ctrl+S",(()=>{const i=sheet.findIndex((s)=>s.scope==="Chain diagram editor");return [sheet[i-1].scope,sheet[i].items.map((r)=>r.keys+"="+r.desc)]})(),["Chains",["Ctrl+S=Save the diagram","F=Fit"]])
check("public: the two entry points other code uses",/^function loyaOpenChainDiagram\(playbookId\)\{/m.test(SRC)&&/^function loyaOpenChainDraft\(draft\)\{/m.test(SRC))
check("no autosave: flows.save is only called from chainsFlowSave",(SRC.match(/"flows\.save"/g)||[]).length===1)
check("safety: data never reaches innerHTML unescaped",!/innerHTML=[^\n]*\+(open|data|res|m|t|pb)\.(name|caller|title|description)\b(?!\))/.test(SRC.replace(/flowEscape\([^)]*\)/g,"ESC")))
// class names only: "--cf-side-w" is a custom property (checked below), the redesign's classes live in chains-studio.css
const used=Array.from(new Set((SRC.match(/(?<![\w-])cf-[a-z0-9-]+/g)||[])))
const STUDIO=read("UI","css","chains-studio.css")
check("css: the --cf-side-w variable the view sets is read by the studio sheet",/root\.style\.setProperty\("--cf-side-w"/.test(SRC)&&/var\(--cf-side-w,340px\)/.test(STUDIO))
check("css: the Run button has its accent rule in the studio sheet",/\.cf-btn\.cf-run-btn:not\(:disabled\)\{/.test(STUDIO))
eq("css: every cf- class the view uses is styled",used.filter((c)=>CSS.indexOf("."+c)<0&&STUDIO.indexOf("."+c)<0&&["cf-full","cf-card-diagram","cf-has-run","cf-file","cf-import-name","cf-new-name","cf-new-caller","cf-set-timeout","cf-set-visits","cf-set-shell","cf-gallery","cf-new","cf-iso-list","cf-issue-warn","cf-left","cf-banner-text","cf-badge-diagram","cf-editor"].indexOf(c)<0),[])
check("css: user-select always has its -webkit- twin",(CSS.match(/(?<!-webkit-)user-select:/g)||[]).length===(CSS.match(/-webkit-user-select:/g)||[]).length)
check("css: glass variants stay in the flow files, glass.css is untouched",/html:where\(\[data-style="glass"\]\) :is\(\.cf-btn/.test(CSS)&&!/\.cf-|\.flow-|\.fi-|\.fr-/.test(GLASS))
check("line endings: LF only",[SRC,CSS,MAIN,AC,SHORTCUTS,fs.readFileSync(__filename,"utf8")].every((t)=>t.indexOf("\r")<0))
// ---- demos: origin, badges, filter, cards, opening a copy, the Demos section under the list
{
eq("origin: names",[C.chainsFlowOrigin(true,"demo"),C.chainsFlowOrigin(false,"demo"),C.chainsFlowOrigin(false,""),C.chainsFlowOrigin(false),C.chainsFlowOrigin(true)],["AI-made","Demo copy","Imported","Imported","AI-made"])
eq("origin: sentences",[C.chainsFlowOriginText(false,"demo"),C.chainsFlowOriginText(true,"demo"),C.chainsFlowOriginText(false,"file")],["This chain is a copy of a built-in demo","An AI client built this chain","This chain was imported"])
const DL=LIST.concat([{playbook_id:5,name:"Demo one",has_graph:true,node_count:9,ai_made:false,ai_reviewed:false,origin:"demo"},{playbook_id:6,name:"Reviewed demo",has_graph:true,ai_reviewed:true,origin:"demo"}])
const di=C.chainsFlowIndex(DL)
eq("index: origin is carried, empty when missing",[di.meta["5"].origin,di.meta["6"].origin,di.meta["1"].origin],["demo","demo",""])
const db=C.chainsFlowBadges(di.meta["5"])
eq("badges: an unreviewed demo copy says so",db.map((b)=>b.text),["Diagram","Demo copy - review"])
check("badges: the demo copy title explains it",/^This chain is a copy of a built-in demo and nobody has reviewed it yet/.test(db[1].title)&&db[1].cls==="cf-badge-ai")
eq("badges: a reviewed demo copy is a plain diagram",C.chainsFlowBadges(di.meta["6"]).map((b)=>b.text),["Diagram"])
const DEMOS=[{id:"web",name:"Web quick wins",description:"Headers and TLS",tags:["http","tls"],node_count:7},{id:"smb",name:"SMB sweep",description:"Shares and signing",tags:["windows"],node_count:1},null,{name:"no id"}]
eq("demo filter: blank keeps every demo with an id",C.chainsFlowFilterDemos(DEMOS,"  ").map((d)=>d.id),["web","smb"])
eq("demo filter: name, description and tags, case-insensitive, every word",[C.chainsFlowFilterDemos(DEMOS,"WEB").map((d)=>d.id),C.chainsFlowFilterDemos(DEMOS,"signing").map((d)=>d.id),C.chainsFlowFilterDemos(DEMOS,"windows").map((d)=>d.id),C.chainsFlowFilterDemos(DEMOS,"tls quick").map((d)=>d.id),C.chainsFlowFilterDemos(DEMOS,"tls smb")],[["web"],["smb"],["smb"],["web"],[]])
eq("demo filter: null-safe and does not return the input",[C.chainsFlowFilterDemos(null,"x"),C.chainsFlowFilterDemos(undefined,"")],[[],[]])
const dh=C.chainsFlowDemosHtml(DEMOS)
eq("demo cards: one button per demo with its data-demo id",(dh.match(/<button type="button" class="cf-demo" data-demo="([^"]+)"/g)||[]).map((x)=>/data-demo="([^"]+)"/.exec(x)[1]),["web","smb"])
check("demo cards: node count with plural, tags, open label",/>7 nodes</.test(dh)&&/>1 node</.test(dh)&&dh.includes('<span class="cf-demo-tag">http</span>')&&/Open a copy/.test(dh))
const evil=C.chainsFlowDemosHtml([{id:'x"><img>',name:"<script>a</script>",description:"a & b",tags:["<b>t</b>"]}])
check("demo cards: id, name, description and tags are escaped",!/<img|<script|<b>/.test(evil)&&evil.includes("&lt;script&gt;")&&evil.includes("a &amp; b")&&evil.includes("&lt;b&gt;t&lt;/b&gt;")&&/data-demo="x&quot;&gt;&lt;img&gt;"/.test(evil))
check("demo cards: name falls back to the id; empty list says so",/cf-demo-name">bare</.test(C.chainsFlowDemosHtml([{id:"bare"}]))&&/No demos match/.test(C.chainsFlowDemosHtml([]))&&/No demos match/.test(C.chainsFlowDemosHtml(null)))
// opening a copy
const D=makeBox()
D.box.closeModal=(x)=>{D.box.closed=(D.box.closed||[]).concat([x===undefined?null:x])}
D.handlers["flows.catalog"]=()=>({templates:[],demos:DEMOS.slice(0,2)})
D.handlers["flows.list"]=()=>LIST
D.handlers["flows.create_from_demo"]=(id)=>({playbook_id:77,name:"copy of "+id})
const dst=D.get("chainsFlowState")
dst.catalog={templates:[],demos:DEMOS.slice(0,2)}
const p1=D.box.chainsFlowOpenDemo("web"),p2=D.box.chainsFlowOpenDemo("web")
const [r1,r2]=await Promise.all([p1,p2])
await flush(D.box)
eq("open demo: calls flows.create_from_demo once, even when clicked twice",D.calls.filter((c)=>c[0]==="flows.create_from_demo"),[["flows.create_from_demo",["web"]]])
eq("open demo: resolves with the new chain, the second click with null",[r1&&r1.playbook_id,r2],[77,null])
check("open demo: closes the gallery, refreshes the list, then opens the copy",JSON.stringify(D.box.closed)==="[true]"&&D.box.refreshes>=1&&JSON.stringify(D.box.opened)==="[77]")
check("open demo: the toast names the demo and asks for a review",D.toasts.some((t)=>/Copied the demo "Web quick wins"/.test(t[0])&&/Review it before you run it/.test(t[0])))
check("open demo: no longer busy afterwards",dst.demoBusy===false)
D.handlers["flows.create_from_demo"]=()=>{throw new Error("no such demo")}
const r3=await D.box.chainsFlowOpenDemo("gone")
check("open demo: a failure shows an error toast and frees the button",r3===null&&dst.demoBusy===false&&D.toasts.some((t)=>t[0]==="no such demo"&&t[1]==="error"))
// with a diagram already open the copy opens directly (the chain list is not on screen)
const E=makeBox()
E.handlers["flows.create_from_demo"]=()=>({playbook_id:88})
E.get("chainsFlowState").open={playbookId:2}
await E.box.chainsFlowOpenDemo("web")
check("open demo: with a diagram open it opens the copy without redrawing the list",JSON.stringify(E.box.opened)==="[88]"&&!E.box.refreshes)
// the Demos section under the list
const L=makeBox()
L.handlers["flows.catalog"]=()=>({templates:[],demos:DEMOS.slice(0,2)})
const wrap=new El("div")
L.box.chainsFlowDecorateList(wrap,"")
check("demos section: nothing is added before the catalog has loaded",wrap.children.length===0)
await flush(L.box)
check("demos section: the list is drawn again once the catalog has demos",L.box.renders>=1&&!!L.get("chainsFlowState").catalog)
L.box.chainsFlowDecorateList(wrap,"")
const sec=wrap.children[0]
check("demos section: appended under the list as a labelled section",wrap.children.length===1&&sec.tagName==="SECTION"&&sec.classList.contains("cf-demos")&&sec.getAttribute("aria-label")==="Demos")
check("demos section: has the Demos toggle and every demo card",/class="cf-demos-toggle" aria-expanded="true"/.test(sec.innerHTML)&&/<span>Demos<\/span>/.test(sec.innerHTML)&&(sec.innerHTML.match(/data-demo=/g)||[]).length===2)
const tog=sec.querySelector(".cf-demos-toggle")
tog.listeners.click.forEach((fn)=>fn({currentTarget:tog}))
check("demos section: the toggle collapses it",sec.classList.contains("is-collapsed")&&L.get("chainsFlowState").demosCollapsed===true&&tog._attrs&&tog._attrs["aria-expanded"]==="false")
const grid=sec.querySelector(".cf-demo-grid")
L.handlers["flows.create_from_demo"]=()=>({playbook_id:99})
grid.listeners.click.forEach((fn)=>fn({target:{closest:(sel)=>sel==="[data-demo]"?{dataset:{demo:"smb"}}:null}}))
await flush(L.box)
eq("demos section: clicking a card opens a copy of that demo",L.calls.filter((c)=>c[0]==="flows.create_from_demo"),[["flows.create_from_demo",["smb"]]])
const w2=new El("div");L.box.chainsFlowDecorateList(w2,"smb")
check("demos section: filtered by the list search",w2.children.length===1&&(w2.children[0].innerHTML.match(/data-demo=/g)||[]).length===1&&/data-demo="smb"/.test(w2.children[0].innerHTML))
check("demos section: collapsed state is kept on the next render",w2.children[0].classList.contains("is-collapsed")&&/aria-expanded="false"/.test(w2.children[0].innerHTML))
const w3=new El("div");L.box.chainsFlowDecorateList(w3,"zzz")
check("demos section: no section when no demo matches",w3.children.length===0)
const N=makeBox();N.handlers["flows.catalog"]=()=>({templates:[]});N.get("chainsFlowState").catalog={templates:[]}
const w4=new El("div");N.box.chainsFlowDecorateList(w4,"")
check("demos section: no section when the catalog has no demos",w4.children.length===0)
const H=makeBox();H.ids.chainsFlowHost=null;const w5=new El("div");H.box.chainsFlowDecorateList(w5,"")
check("demos section: nothing before the page exists",w5.children.length===0)
check("chains.js: the list hook is called with the search",PAGE.includes("chainsFlowDecorateList(wrap,chainsState.search)"))
}
console.log("chains_flow: "+passed+" passed, "+failed+" failed")
process.exit(failed?1:0)
})().catch((err)=>{console.error(err);process.exit(1)})
