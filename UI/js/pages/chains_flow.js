// Chains page: the diagram view of an Action Chain (the "n8n style" editor). Wires flow-editor.js (canvas), flow-inspector.js
// (node forms) and flow-run.js (confirmation, live run, history) into #chainsFlowHost, and plugs into pages/chains.js through
// its hooks: chainsFlowDecorateCard(card,pb), chainsFlowDecorateList(wrap,query), chainsFlowOpenChain(id), #chainsOpenDiagramBtn.
// The page's one "New chain" chooser (chainsNewChooser) opens chainsFlowNewPrompt, chainsFlowDemosPrompt or chainsFlowTemplatesPrompt.
// Nothing is autosaved: Save is explicit and leaving with unsaved changes asks first. No localStorage: preferences go through
// flows.prefs_get / flows.prefs_set. Every string that reaches innerHTML goes through flowEscape.
// Public entry points for other code: loyaOpenChainDiagram(playbookId), loyaOpenChainDraft({name,graph,ai_made,caller}).
const CHAINS_FLOW_VALIDATE_MS=350
const CHAINS_FLOW_PREFS={snap:true,grid:20,minimap:true,inspector_width:340,hotbar:null}
// ids: playbook ids that have a diagram (what chainsFlowOpenChain answers from, synchronously); meta: one row per chain.
const chainsFlowState={ids:{},meta:{},loaded:false,catalog:null,catalogWait:null,prefs:null,prefsWait:null,mounted:false,view:null,open:null,token:0,headless:null}
// ---- pure helpers (exported for tests/js/chains_flow.js)
function chainsFlowIndex(rows){
const ids={},meta={}
;(Array.isArray(rows)?rows:[]).forEach((r)=>{
if(!r||r.playbook_id===undefined||r.playbook_id===null)return
const id=String(r.playbook_id)
meta[id]={id:r.playbook_id,name:String(r.name||""),caller:String(r.caller||""),steps:Number(r.step_count)||0,hasGraph:!!r.has_graph,nodes:Number(r.node_count)||0,aiMade:!!r.ai_made,reviewed:r.ai_reviewed!==false,origin:String(r.origin||"")}
if(r.has_graph)ids[id]=true
})
return {ids,meta}
}
// What an unreviewed chain is called: an AI built it, it is a copy of a built-in demo, or it was imported from a file.
function chainsFlowOrigin(aiMade,origin){
return aiMade?"AI-made":origin==="demo"?"Demo copy":"Imported"
}
function chainsFlowOriginText(aiMade,origin){
return aiMade?"An AI client built this chain":origin==="demo"?"This chain is a copy of a built-in demo":"This chain was imported"
}
function chainsFlowBadges(m){
if(!m||!m.hasGraph)return []
const out=[{cls:"cf-badge-diagram",text:"Diagram",title:"This chain is a flow diagram"+(m.nodes?" ("+m.nodes+" node"+(m.nodes===1?"":"s")+")":"")}]
if(!m.reviewed)out.push({cls:"cf-badge-ai",text:chainsFlowOrigin(m.aiMade,m.origin)+" - review",title:chainsFlowOriginText(m.aiMade,m.origin)+" and nobody has reviewed it yet. Review it before running."})
return out
}
function chainsFlowBadgesHtml(m){
return chainsFlowBadges(m).map((b)=>'<span class="cf-badge '+flowEscape(b.cls)+'" title="'+flowEscape(b.title)+'">'+flowEscape(b.text)+"</span>").join("")
}
// The part of a graph that counts as "content": moving the viewport is not an unsaved change.
function chainsFlowGraphSig(graph){
const g=graph&&typeof graph==="object"?graph:{}
return JSON.stringify({s:g.settings||{},n:Array.isArray(g.nodes)?g.nodes:[],e:Array.isArray(g.edges)?g.edges:[]})
}
// Only the Start node (or nothing): replacing it needs no confirmation.
function chainsFlowIsBlank(graph){
const nodes=graph&&Array.isArray(graph.nodes)?graph.nodes:[]
return nodes.filter((n)=>n&&n.type!=="start").length===0
}
function chainsFlowIssueSummary(issues){
const e=issues&&Array.isArray(issues.errors)?issues.errors.length:0
const w=issues&&Array.isArray(issues.warnings)?issues.warnings.length:0
const parts=[]
if(e)parts.push(e+" error"+(e===1?"":"s"))
if(w)parts.push(w+" warning"+(w===1?"":"s"))
return {errors:e,warnings:w,cls:e?"is-error":w?"is-warn":"is-ok",text:parts.length?parts.join(", "):"No issues"}
}
function chainsFlowIssuesHtml(issues){
const row=(i,level)=>'<button type="button" class="cf-issue cf-issue-'+level+'" data-cf="issue" data-node="'+flowEscape(i&&i.node?i.node:"")+'"><span class="cf-issue-level">'+(level==="error"?"Error":"Warning")+'</span><span class="cf-issue-text">'+flowEscape(flowIssueText(i))+"</span>"+(i&&i.node?'<span class="cf-issue-node">'+flowEscape(i.node)+"</span>":"")+"</button>"
const e=issues&&Array.isArray(issues.errors)?issues.errors:[],w=issues&&Array.isArray(issues.warnings)?issues.warnings:[]
if(!e.length&&!w.length)return '<div class="cf-issue-none">No issues. This diagram can run.</div>'
return e.map((i)=>row(i,"error")).join("")+w.map((i)=>row(i,"warn")).join("")
}
// The export format flows.import_json reads, built for an unsaved draft.
function chainsFlowBundle(name,caller,graph){
return JSON.stringify({loya_chain:1,name:String(name||""),caller:String(caller||""),graph:graph||{}})
}
// Where a run was asked for (action-chains.js contexts) -> the flow engine's source.
function chainsFlowRunSource(source){
if(source==="live")return "live"
if(source==="chains"||source==="commands"||source==="manual"||!source)return "manual"
return "caller"
}
function chainsFlowFileName(name){
const slug=String(name||"").toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-+|-+$/g,"").slice(0,60)
return (slug||"chain")+".loya-chain.json"
}
function chainsFlowTemplatesHtml(templates,current){
const list=Array.isArray(templates)?templates:[]
if(!list.length)return '<div class="cmds-empty-msg">No starter templates.</div>'
return list.map((t)=>'<div class="cf-tpl'+(current&&current===t.id?" active":"")+'" data-tpl="'+flowEscape(t.id)+'"><div class="cf-tpl-name">'+flowEscape(t.name||t.id)+'</div><div class="cf-tpl-desc">'+flowEscape(t.description||"")+'</div><div class="cf-tpl-actions"><button type="button" class="cf-btn" data-cf-tpl="new" data-id="'+flowEscape(t.id)+'">New chain from this</button><button type="button" class="cf-btn" data-cf-tpl="here" data-id="'+flowEscape(t.id)+'">Use in this diagram</button></div></div>').join("")
}
// Pure: the demos whose name, description or tags hold every word of the query (the Chains page search).
function chainsFlowFilterDemos(demos,query){
const list=Array.isArray(demos)?demos.filter((d)=>d&&d.id):[]
const words=String(query||"").trim().toLowerCase().split(/\s+/).filter(Boolean)
if(!words.length)return list.slice()
return list.filter((d)=>{const hay=[d.name,d.description].concat(Array.isArray(d.tags)?d.tags:[]).join(" ").toLowerCase();return words.every((w)=>hay.includes(w))})
}
// One card per demo. Each is a button: opening it copies the demo into the user's chains.
function chainsFlowDemosHtml(demos){
const list=Array.isArray(demos)?demos.filter((d)=>d&&d.id):[]
if(!list.length)return '<div class="cmds-empty-msg">No demos match.</div>'
return list.map((d)=>{
const n=Number(d.node_count)||0
const tags=(Array.isArray(d.tags)?d.tags:[]).slice(0,4).map((t)=>'<span class="cf-demo-tag">'+flowEscape(t)+"</span>").join("")
return '<button type="button" class="cf-demo" data-demo="'+flowEscape(d.id)+'" title="Open a copy of this demo in your chains"><span class="cf-demo-name">'+flowEscape(d.name||d.id)+'</span><span class="cf-demo-desc">'+flowEscape(d.description||"")+'</span><span class="cf-demo-foot"><span class="cf-demo-tags">'+tags+'</span><span class="cf-demo-count">'+n+" node"+(n===1?"":"s")+'</span><span class="cf-demo-open">Open a copy</span></span></button>'
}).join("")
}
function chainsFlowHeadState(open){
const o=open||{}
const saved=!o.draft&&o.playbookId!==null&&o.playbookId!==undefined
return {canSave:!o.saving&&(!!o.dirty||!!o.draft||!!o.derived),saveLabel:o.derived?"Save as diagram":"Save",canRun:true,needsSaved:!saved,canRevert:saved&&!o.derived&&Number(o.steps)>0,canDelete:saved,
banner:!o.reviewed?"review":o.derived?"derived":""}
}
// bridge.js rejects with "bridge method missing: <path>" when the Python side does not have a method (yet).
function chainsFlowBridgeMissing(err){
return /bridge method missing/i.test(err&&err.message?String(err.message):String(err||""))
}
function chainsFlowErrorText(err,fallback){
return err&&err.message?String(err.message):typeof err==="string"&&err?err:fallback
}
// ---- data
function chainsFlowCatalog(){
const st=chainsFlowState
if(st.catalog)return Promise.resolve(st.catalog)
if(!st.catalogWait)st.catalogWait=bridgeCall("flows.catalog").then((c)=>{st.catalog=c||{};return st.catalog}).catch((err)=>{st.catalogWait=null;console.error("flows.catalog failed",err);return {}})
return st.catalogWait
}
function chainsFlowPrefs(){
const st=chainsFlowState
if(st.prefs)return Promise.resolve(st.prefs)
if(!st.prefsWait)st.prefsWait=bridgeCall("flows.prefs_get").then((p)=>{st.prefs=Object.assign({},CHAINS_FLOW_PREFS,p||{});return st.prefs}).catch(()=>{st.prefsWait=null;return Object.assign({},CHAINS_FLOW_PREFS)})
return st.prefsWait
}
function chainsFlowSavePrefs(values){
const st=chainsFlowState
st.prefs=Object.assign({},CHAINS_FLOW_PREFS,st.prefs||{},values||{})
bridgeCall("flows.prefs_set",[values]).catch(()=>{})
}
function chainsFlowRefreshIndex(){
const st=chainsFlowState
return bridgeCall("flows.list").then((rows)=>{
const idx=chainsFlowIndex(rows)
const changed=!st.loaded||JSON.stringify(idx.meta)!==JSON.stringify(st.meta)
st.ids=idx.ids;st.meta=idx.meta;st.loaded=true
if(changed&&typeof chainsRenderList==="function"&&document.getElementById("cmdsPlaybooksList"))chainsRenderList()
const open=st.open
if(open&&!open.draft&&st.meta[String(open.playbookId)]){
const m=st.meta[String(open.playbookId)]
open.steps=m.steps
if(m.hasGraph){open.reviewed=m.reviewed;open.aiMade=m.aiMade;open.origin=m.origin}
chainsFlowSyncHead()
}
// A diagram chain that was opened as a step list before the index arrived belongs in the editor.
if(!open&&typeof chainsState!=="undefined"&&chainsState.currentId!=null&&st.ids[String(chainsState.currentId)]&&chainsFlowPageActive())chainsFlowOpen(chainsState.currentId)
return idx
}).catch((err)=>{console.error("flows.list failed",err);return {ids:st.ids,meta:st.meta}})
}
function chainsFlowPageActive(){
const p=document.querySelector('.page[data-page="chains"]')
return !!(p&&p.classList.contains("active"))
}
function chainsFlowToast(message,kind){
if(typeof showToast==="function")showToast(message,kind)
}
// ---- hooks called by pages/chains.js
function chainsFlowDecorateCard(card,pb){
chainsFlowMount()
const m=pb?chainsFlowState.meta[String(pb.id)]:null
if(!card||!m||!m.hasGraph)return
card.classList.add("cf-card-diagram")
const count=card.querySelector(".cmds-playbook-card-count")
if(count)count.textContent=m.nodes+" node"+(m.nodes===1?"":"s")
const wrap=document.createElement("span")
wrap.className="cf-badges"
wrap.innerHTML=chainsFlowBadgesHtml(m)
if(count)card.insertBefore(wrap,count)
else card.appendChild(wrap)
}
// Called synchronously at the top of chainsOpenChain: true = the diagram editor takes this chain.
function chainsFlowOpenChain(id){
const st=chainsFlowState
if(!chainsFlowMount())return false
const cur=st.open
if(cur){
if(!cur.draft&&String(cur.playbookId)===String(id))return true
if(cur.dirty){chainsFlowLeave().then((ok)=>{if(ok&&typeof chainsOpenChain==="function")chainsOpenChain(id)});return true}
chainsFlowClose()
}
if(!st.ids[String(id)])return false
chainsFlowOpen(id)
return true
}
function chainsFlowMount(){
const st=chainsFlowState
if(st.mounted)return true
const host=typeof document!=="undefined"&&document.getElementById?document.getElementById("chainsFlowHost"):null
if(!host)return false
st.mounted=true
const openBtn=document.getElementById("chainsOpenDiagramBtn")
if(openBtn){
openBtn.classList.remove("hidden")
openBtn.addEventListener("click",()=>{if(typeof chainsState!=="undefined"&&chainsState.currentId!=null)chainsFlowOpen(chainsState.currentId)})
}
const slot=document.getElementById("chainsToolbarSlot")
if(slot){
const imp=document.createElement("button")
imp.type="button"
imp.className="chains-tool-btn"
imp.id="chainsFlowImportBtn"
imp.title="Import a chain diagram from a JSON export"
imp.innerHTML='<i class="icon icon-file"></i><span>Import</span>'
imp.addEventListener("click",()=>chainsFlowImportPrompt())
slot.appendChild(imp)
}
chainsFlowRefreshIndex()
chainsFlowCatalog()
chainsFlowPrefs()
return true
}
// ---- the view
function chainsFlowViewHtml(){
const btn=(act,label,icon,title,cls)=>'<button type="button" class="cf-btn'+(cls?" "+cls:"")+'" data-cf="'+act+'" title="'+flowEscape(title)+'">'+(icon?'<i class="icon icon-'+icon+'"></i>':"")+"<span>"+flowEscape(label)+"</span></button>"
return '<div class="cf-view glass-panel"><div class="cf-head">'+
'<button type="button" class="cmds-playbook-back" data-cf="back"><i class="icon icon-arrow-left"></i><span>All chains</span></button>'+
'<div class="cf-title"><span class="cf-name"></span><span class="cf-caller"></span><span class="cf-dirty hidden" title="This diagram has changes that are not saved yet">Unsaved</span></div>'+
'<div class="cf-status-wrap"><button type="button" class="cf-status is-ok" data-cf="issues" title="Validation: click to list the problems"></button><div class="cf-issues-pop hidden"></div></div>'+
'<div class="cf-actions">'+
btn("save","Save","save","Save this diagram (Ctrl+S)","cf-primary")+
btn("run","Run","play","Run this chain on the live target (asks first)","cf-run-btn")+
btn("dry","Dry run","eye-off","Walk the diagram without executing anything")+
btn("history","History","clock","Earlier runs of this chain")+
btn("settings","Settings","sliders","What happens when a node fails, time limits, the shell")+
'<span class="cf-sep"></span>'+
btn("templates","Templates","list","Starter diagrams")+
btn("import","Import","file","Import a chain diagram from JSON, as a new chain")+
btn("export","Export","copy","Export this chain as JSON")+
btn("revert","Revert to linear","undo","Delete the diagram and go back to the step list")+
btn("delete","Delete","trash","Delete this action chain","cf-danger")+
"</div></div>"+
'<div class="cf-banner hidden"></div>'+
'<div class="cf-main"><div class="cf-left"><div class="cf-editor"></div><div class="cf-run hidden"></div></div><div class="cf-side"></div></div></div>'
}
function chainsFlowSetShown(shown){
const host=document.getElementById("chainsFlowHost")
const wrap=document.getElementById("cmdsPlaybooksWrap")
const page=document.querySelector('.page[data-page="chains"]')
const bar=page?page.querySelector(".chains-toolbar"):null
if(host){host.classList.toggle("hidden",!shown);host.classList.toggle("cf-full",shown)}
if(wrap)wrap.classList.toggle("hidden",shown)
if(bar)bar.classList.toggle("hidden",shown)
}
// Narrow room (the terminal docked beside the page, a small window): the hot bar drops its labels and the inspector only
// appears, over the canvas, while a node is selected (flow-panels.css .cf-compact). Both come back when the room does.
const CHAINS_FLOW_COMPACT_BELOW=960
function chainsFlowIsCompact(width){return Number(width)>0&&Number(width)<CHAINS_FLOW_COMPACT_BELOW}
// A jump in width this big is a panel opening or closing (the terminal), not a window being dragged: show the whole diagram again.
function chainsFlowNeedsRefit(prevWidth,width,modeChanged){return Number(prevWidth)>0&&Number(width)>0&&(!!modeChanged||Math.abs(width-prevWidth)>=120)}
function chainsFlowWatchSpace(view){
const main=view&&view.root&&view.root.querySelector?view.root.querySelector(".cf-main"):null
if(!main||typeof ResizeObserver!=="function")return
let last=0,frame=0
const measure=()=>{
frame=0
if(chainsFlowState.view!==view)return
const width=main.clientWidth
if(!width)return
const compact=chainsFlowIsCompact(width)
const changed=view.root.classList.contains("cf-compact")!==compact
view.root.classList.toggle("cf-compact",compact)
if(chainsFlowNeedsRefit(last,width,changed))requestAnimationFrame(()=>{if(chainsFlowState.view===view)try{view.editor.fit()}catch(_){}})
last=width
}
view.spaceWatch=new ResizeObserver(()=>{if(!frame)frame=requestAnimationFrame(measure)})
view.spaceWatch.observe(main)
}
function chainsFlowDestroyView(){
const st=chainsFlowState,v=st.view,open=st.open
if(open&&open.vTimer){clearTimeout(open.vTimer);open.vTimer=null}
st.view=null;st.open=null
if(!v)return
if(v.spaceWatch){try{v.spaceWatch.disconnect()}catch(_){}}
try{v.run.destroy()}catch(_){}
try{v.inspector.destroy()}catch(_){}
try{v.editor.destroy()}catch(_){}
if(v.host)v.host.innerHTML=""
}
function chainsFlowClose(){
chainsFlowState.token++
chainsFlowDestroyView()
chainsFlowSetShown(false)
}
// Leaving the open diagram: asks when there are unsaved changes. -> Promise<boolean> (true = the view is closed).
function chainsFlowLeave(){
const st=chainsFlowState,open=st.open
if(!open)return Promise.resolve(true)
if(st.view)st.view.inspector.flush()
if(!open.dirty){chainsFlowClose();return Promise.resolve(true)}
return appConfirm("This diagram has unsaved changes.",{okLabel:"Discard changes",danger:true,extraLabel:"Save",cancelLabel:"Keep editing",bodyHtml:"<div>"+flowEscape(open.draft?"\""+open.name+"\" has not been saved yet. Leaving now throws it away.":"Leaving now throws away what you changed in \""+open.name+"\" since the last save.")+"</div>"}).then((choice)=>{
if(st.open!==open)return true
if(choice===true){chainsFlowClose();return true}
if(choice==="extra")return chainsFlowSave().then((saved)=>{if(saved&&st.open===open)chainsFlowClose();return !!saved})
return false
})
}
function chainsFlowShow(info,graph,issues){
const st=chainsFlowState
chainsFlowDestroyView()
const host=document.getElementById("chainsFlowHost")
if(!host)return null
host.innerHTML=chainsFlowViewHtml()
chainsFlowSetShown(true)
const prefs=Object.assign({},CHAINS_FLOW_PREFS,st.prefs||{})
const open=st.open=Object.assign({playbookId:null,name:"",caller:"",derived:false,aiMade:false,reviewed:true,draft:false,flagged:false,steps:0,dirty:false,saving:false,sig:"",issues:{errors:[],warnings:[]},vTimer:null,vSeq:0},info)
const root=host.querySelector(".cf-view"),side=host.querySelector(".cf-side"),runHost=host.querySelector(".cf-run")
side.style.width=prefs.inspector_width+"px"
side.style.flexBasis=prefs.inspector_width+"px"
root.style.setProperty("--cf-side-w",prefs.inspector_width+"px")
// Narrow from the start: compact before the editor measures its canvas, so the first fit uses the real width.
const mainEl=root.querySelector(".cf-main")
if(mainEl)root.classList.toggle("cf-compact",chainsFlowIsCompact(mainEl.clientWidth))
let inspector=null
const editor=flowEditorCreate(host.querySelector(".cf-editor"),{graph:graph,prefs:{snap:prefs.snap,grid:prefs.grid,minimap:prefs.minimap,hotbar:prefs.hotbar},
onChange:()=>chainsFlowChanged(open),
onSelect:(ids)=>{if(inspector)inspector.show(ids&&ids.length===1?ids[0]:null);root.classList.toggle("cf-has-sel",!!(ids&&ids.length===1))},
onOpenNode:(id,tab)=>{
if(!inspector)return
inspector.show(id)
if(typeof inspector.setTab==="function")inspector.setTab(tab==="output"?"output":"params")
root.classList.add("cf-has-sel")
if(tab==="output")return
const first=inspector.el.querySelector(".fi-body input:not([type=checkbox]),.fi-body textarea")
if(first)setTimeout(()=>{try{first.focus()}catch(_){}},0)
},
onAutoWire:(info)=>chainsFlowToast("Both success and fail now lead to \""+info.to+"\". Delete either connection if you want them to differ."),
onRunState:(status)=>{if(inspector&&typeof inspector.setRun==="function")inspector.setRun(status)},
onPrefs:(p)=>chainsFlowSavePrefs(p)})
inspector=flowInspectorCreate(side,editor,{catalog:st.catalog||{},playbookId:()=>open.playbookId,toast:chainsFlowToast,side:"right",onResize:(w)=>{root.style.setProperty("--cf-side-w",w+"px");st.prefs=Object.assign({},CHAINS_FLOW_PREFS,st.prefs||{},{inspector_width:w})}})
const run=flowRunCreate(runHost,editor,{toast:chainsFlowToast,
onShow:(on)=>{
const was=!runHost.classList.contains("hidden")
runHost.classList.toggle("hidden",!on)
runHost.parentNode.classList.toggle("cf-has-run",!!on)
// The canvas just lost (or got back) a third of its height: show the whole diagram again.
if(was!==!!on)requestAnimationFrame(()=>{if(st.view&&st.view.editor===editor)editor.fit()})
},
onFinish:()=>{chainsFlowRefreshIndex()},
onReviewed:()=>{open.reviewed=true;chainsFlowSyncHead();chainsFlowRefreshIndex()}})
st.view={host:host,root:root,editor:editor,inspector:inspector,run:run}
chainsFlowWatchSpace(st.view)
open.sig=chainsFlowGraphSig(editor.getGraph())
root.addEventListener("click",chainsFlowOnClick)
chainsFlowApplyIssues(open,issues||flowValidate(editor.getGraph()))
chainsFlowSyncHead()
setTimeout(()=>{if(st.open===open)editor.focus()},0)
return open
}
function chainsFlowOpen(id){
const st=chainsFlowState,token=++st.token
if(!chainsFlowMount())return Promise.resolve(null)
return Promise.all([bridgeCall("flows.get",[id]),chainsFlowCatalog(),chainsFlowPrefs(),st.loaded?null:chainsFlowRefreshIndex()]).then((res)=>{
if(token!==st.token)return null
const data=res[0]||{}
const m=st.meta[String(data.playbook_id)]
const open=chainsFlowShow({playbookId:data.playbook_id,name:String(data.name||""),caller:String(data.caller||""),derived:!!data.derived,aiMade:!!data.ai_made,reviewed:data.ai_reviewed!==false,origin:String(data.origin||""),steps:m?m.steps:0},data.graph,{errors:data.errors||[],warnings:data.warnings||[]})
if(typeof chainsState!=="undefined"){chainsState.currentId=null;chainsState.currentPlaybook=null}
// A run of this chain that is still going (started by /caller, or before the page was left) shows up again.
bridgeCall("flows.active_runs").then((rows)=>{
const live=(Array.isArray(rows)?rows:[]).find((r)=>r&&String(r.playbook_id)===String(data.playbook_id))
if(live&&st.open===open&&st.view)st.view.run.attach(live.run_id,{playbookId:data.playbook_id})
}).catch(()=>{})
return open
}).catch((err)=>{
if(token===st.token)chainsFlowToast(chainsFlowErrorText(err,"Could not open the diagram"),"error")
return null
})
}
// The saved diagram may have changed while the page was hidden (the AI edited it): reload when nothing is at stake here.
function chainsFlowReload(){
const st=chainsFlowState,open=st.open
if(!open||open.draft||open.dirty||open.saving||!st.view||st.view.run.isWatching())return
bridgeCall("flows.get",[open.playbookId]).then((data)=>{
if(st.open!==open||open.dirty||!data)return
const probe=chainsFlowGraphSig(flowNormalize(flowClone(data.graph)))
open.reviewed=data.ai_reviewed!==false;open.aiMade=!!data.ai_made;open.origin=String(data.origin||"");open.name=String(data.name||open.name);open.caller=String(data.caller||"")
if(probe!==open.sig&&!!data.derived===open.derived){
st.view.editor.setGraph(data.graph,{keepView:true})
open.sig=chainsFlowGraphSig(st.view.editor.getGraph())
st.view.inspector.show(null)
chainsFlowApplyIssues(open,{errors:data.errors||[],warnings:data.warnings||[]})
}
chainsFlowSyncHead()
}).catch(()=>{chainsFlowClose();if(typeof chainsRefreshList==="function")chainsRefreshList()})
}
function chainsFlowSyncHead(){
const st=chainsFlowState,open=st.open,v=st.view
if(!open||!v)return
const root=v.root,$=(sel)=>root.querySelector(sel)
const hs=chainsFlowHeadState(open)
$(".cf-name").textContent=open.name||"Untitled chain"
$(".cf-name").title=open.name||""
$(".cf-caller").textContent=open.caller?"/"+open.caller:""
$(".cf-dirty").classList.toggle("hidden",!(open.dirty||open.draft))
$(".cf-dirty").textContent=open.draft?"Not saved yet":"Unsaved"
const sum=chainsFlowIssueSummary(open.issues)
const chip=$(".cf-status")
chip.className="cf-status "+sum.cls
chip.textContent=sum.text
const save=$('[data-cf="save"]')
save.disabled=!hs.canSave
save.querySelector("span").textContent=open.saving?"Saving...":hs.saveLabel
;["history","export"].forEach((k)=>{const b=$('[data-cf="'+k+'"]');if(!b.dataset.title)b.dataset.title=b.title;b.disabled=hs.needsSaved;b.title=hs.needsSaved?"Save the diagram first":b.dataset.title})
$('[data-cf="revert"]').classList.toggle("hidden",!hs.canRevert)
$('[data-cf="delete"]').classList.toggle("hidden",!hs.canDelete)
const banner=$(".cf-banner")
let html=""
if(hs.banner==="review"){
const origin=chainsFlowOrigin(open.aiMade,open.origin)
html='<div class="cf-banner-text"><b>'+origin+" - review before running.</b> "+chainsFlowOriginText(open.aiMade,open.origin)+"."+(open.origin==="demo"&&!open.aiMade?" The built-in original stays unchanged. Check the target before you run it.":"")+" Open every node and read its commands and scripts. The first run asks you to confirm that you did.</div>"+(open.draft?"":'<button type="button" class="cf-btn" data-cf="reviewed">Mark as reviewed</button>')
banner.className="cf-banner cf-banner-ai"
}else if(hs.banner==="derived"){
html='<div class="cf-banner-text"><b>Linear chain shown as a diagram.</b> Nothing changes until you save. Saving turns it into a diagram chain; its step list is kept, and "Revert to linear" brings it back.</div>'
banner.className="cf-banner cf-banner-info"
}else banner.className="cf-banner hidden"
if(banner.dataset.sig!==html){banner.dataset.sig=html;banner.innerHTML=html}
}
function chainsFlowApplyIssues(open,issues){
const st=chainsFlowState
if(st.open!==open||!st.view)return
open.issues={errors:Array.isArray(issues&&issues.errors)?issues.errors:[],warnings:Array.isArray(issues&&issues.warnings)?issues.warnings:[]}
st.view.editor.setIssues(open.issues)
st.view.inspector.setIssues(open.issues)
const pop=st.view.root.querySelector(".cf-issues-pop")
if(pop&&!pop.classList.contains("hidden"))pop.innerHTML=chainsFlowIssuesHtml(open.issues)
chainsFlowSyncHead()
}
function chainsFlowValidateNow(open){
const st=chainsFlowState
if(st.open!==open||!st.view)return Promise.resolve()
if(open.vTimer){clearTimeout(open.vTimer);open.vTimer=null}
const seq=++open.vSeq,graph=st.view.editor.getGraph()
return bridgeCall("flows.validate",[graph]).catch(()=>flowValidate(graph)).then((res)=>{
if(st.open===open&&seq===open.vSeq)chainsFlowApplyIssues(open,res)
})
}
function chainsFlowChanged(open){
const st=chainsFlowState
if(st.open!==open||!st.view)return
open.dirty=open.draft||chainsFlowGraphSig(st.view.editor.getGraph())!==open.sig
st.view.inspector.refresh()
chainsFlowSyncHead()
if(open.vTimer)clearTimeout(open.vTimer)
open.vTimer=setTimeout(()=>{open.vTimer=null;chainsFlowValidateNow(open)},CHAINS_FLOW_VALIDATE_MS)
}
// ---- actions
function chainsFlowSave(){
const st=chainsFlowState,open=st.open
if(!open||!st.view||open.saving)return Promise.resolve(false)
st.view.inspector.flush()
let ready=Promise.resolve(true)
if(open.derived)ready=appConfirm("Save \""+open.name+"\" as a diagram?",{okLabel:"Save as diagram",wide:true,bodyHtml:"<div>From now on this chain runs as the diagram everywhere: the Run button, <b>/caller</b> in the terminal and the AI.</div><div>Its "+Number(open.steps||0)+" step"+(Number(open.steps)===1?"":"s")+" stay stored and untouched. <b>Revert to linear</b> deletes the diagram and brings the step list back.</div>"})
return ready.then((ok)=>{
if(!ok||st.open!==open||!st.view)return false
const graph=st.view.editor.getGraph()
const sig=chainsFlowGraphSig(graph)
// An AI draft is stored as "AI-made, not reviewed" (flows.create_ai_draft); that call refuses a diagram with errors, so
// those are shown first and the draft stays open. An older bridge without the method falls back to the import path.
const importDraft=()=>bridgeCall("flows.import_json",[chainsFlowBundle(open.name,open.caller,graph),open.name]).then((res)=>Object.assign({},res,{viaImport:true}))
const aiDraft=()=>bridgeCall("flows.validate",[graph]).catch(()=>flowValidate(graph)).then((check)=>{
const errors=check&&Array.isArray(check.errors)?check.errors:[]
if(errors.length){
if(st.open===open){chainsFlowApplyIssues(open,check);chainsFlowToggleIssues(true)}
throw new Error("Fix "+errors.length+" error"+(errors.length===1?"":"s")+" before saving this AI-made diagram: "+flowIssueText(errors[0]))
}
return bridgeCall("flows.create_ai_draft",[open.name,graph,open.client||""]).catch((err)=>{if(chainsFlowBridgeMissing(err))return importDraft();throw err})
})
let call
if(open.draft)call=open.flagged?aiDraft():bridgeCall("flows.create",[open.name,graph,open.caller||null,null])
else call=bridgeCall("flows.save",[open.playbookId,graph])
open.saving=true
chainsFlowSyncHead()
return call.then((res)=>{
open.saving=false
const wasDraft=open.draft
if(wasDraft){open.draft=false;open.playbookId=res.playbook_id;open.reviewed=!open.flagged;open.aiMade=open.flagged&&!res.viaImport}
open.derived=false
open.sig=sig
st.ids[String(open.playbookId)]=true
if(st.open===open&&st.view){
open.dirty=chainsFlowGraphSig(st.view.editor.getGraph())!==sig
if(res&&Array.isArray(res.errors))chainsFlowApplyIssues(open,{errors:res.errors,warnings:res.warnings||[]})
else chainsFlowValidateNow(open)
chainsFlowSyncHead()
}
const errors=res&&Array.isArray(res.errors)?res.errors.length:0
chainsFlowToast(errors?"Saved as a draft - fix "+errors+" error"+(errors===1?"":"s")+" before it can run":"Diagram saved")
if(typeof acInvalidateCallers==="function")acInvalidateCallers()
chainsFlowRefreshIndex()
if(wasDraft&&typeof chainsRefreshList==="function")chainsRefreshList()
return true
}).catch((err)=>{
open.saving=false
if(st.open===open)chainsFlowSyncHead()
chainsFlowToast(chainsFlowErrorText(err,"Could not save the diagram"),"error")
return false
})
})
}
// Real runs use the SAVED diagram (the confirmation is built from it), so unsaved changes are saved first.
function chainsFlowSavedThen(question,okLabel){
const st=chainsFlowState,open=st.open
if(!open||!st.view)return Promise.resolve(false)
st.view.inspector.flush()
if(!open.draft&&!open.dirty)return Promise.resolve(true)
return appConfirm(question,{okLabel:okLabel}).then((ok)=>ok&&st.open===open?chainsFlowSave():false)
}
function chainsFlowRun(opts){
const st=chainsFlowState,open=st.open
if(!open||!st.view)return Promise.resolve(null)
if(typeof termState!=="undefined"&&termState&&termState.enabled===false){chainsFlowToast("Enable the terminal in Settings first","error");return Promise.resolve(null)}
return chainsFlowSavedThen(open.draft?"Save this diagram before running it?":"Save your changes before running?","Save and run").then((ready)=>{
if(!ready||st.open!==open||!st.view)return null
return st.view.run.confirmAndRun(open.playbookId,Object.assign({name:open.name,source:"manual"},opts||{}))
})
}
function chainsFlowDryRun(){
const st=chainsFlowState,open=st.open
if(!open||!st.view)return Promise.resolve(null)
st.view.inspector.flush()
if(open.draft)return chainsFlowSavedThen("Save this diagram before the dry run?","Save and dry run").then((ready)=>ready&&st.open===open&&st.view?st.view.run.dryRun(open.playbookId,null):null)
// A dry run executes nothing, so it may use the unsaved diagram as it is on screen.
return st.view.run.dryRun(open.playbookId,open.dirty?st.view.editor.getGraph():null)
}
function chainsFlowMarkReviewed(){
const st=chainsFlowState,open=st.open
if(!open||open.draft)return
appConfirm("Mark \""+open.name+"\" as reviewed?",{okLabel:"I reviewed it",bodyHtml:"<div>Only do this after reading every command and script in the diagram.</div><div>It becomes a normal chain: the \"review before running\" banner and badge go away and runs no longer ask for the review.</div>"}).then((ok)=>{
if(!ok||st.open!==open)return
bridgeCall("flows.mark_reviewed",[open.playbookId]).then(()=>{open.reviewed=true;open.aiMade=false;open.origin="";chainsFlowToast("Marked as reviewed");chainsFlowSyncHead();chainsFlowRefreshIndex()}).catch((err)=>chainsFlowToast(chainsFlowErrorText(err,"Could not mark the chain as reviewed"),"error"))
})
}
function chainsFlowRevert(){
const st=chainsFlowState,open=st.open
if(!open||open.draft||open.derived)return
const id=open.playbookId
appConfirm("Revert \""+open.name+"\" to a linear chain?",{okLabel:"Delete the diagram",danger:true,bodyHtml:"<div>The diagram is deleted and cannot be brought back. The chain runs its "+Number(open.steps||0)+" saved step"+(Number(open.steps)===1?"":"s")+" one after another again.</div>"}).then((ok)=>{
if(!ok||st.open!==open)return
bridgeCall("flows.revert_linear",[id]).then(()=>{
delete st.ids[String(id)]
chainsFlowClose()
chainsFlowToast("Back to the linear chain")
chainsFlowRefreshIndex()
if(typeof chainsRefreshList==="function")chainsRefreshList().then(()=>chainsOpenChain(id))
}).catch((err)=>chainsFlowToast(chainsFlowErrorText(err,"Could not revert the chain"),"error"))
})
}
function chainsFlowDelete(){
const st=chainsFlowState,open=st.open
if(!open||open.draft)return
const id=open.playbookId
appConfirm("Delete this action chain? This cannot be undone.",{okLabel:"Delete",danger:true}).then((ok)=>{
if(!ok||st.open!==open)return
bridgeCall("playbooks.delete",[id]).then(()=>{
delete st.ids[String(id)]
chainsFlowClose()
if(typeof acInvalidateCallers==="function")acInvalidateCallers()
chainsFlowRefreshIndex()
if(typeof chainsRefreshList==="function")chainsRefreshList()
}).catch((err)=>chainsFlowToast(chainsFlowErrorText(err,"Delete failed"),"error"))
})
}
function chainsFlowCopyText(text,field){
const done=()=>chainsFlowToast("Copied")
if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(text).then(done).catch(()=>{if(field){field.focus();field.select();try{document.execCommand("copy");done()}catch(_){}}});return}
if(field){field.focus();field.select();try{document.execCommand("copy");done()}catch(_){}}
}
function chainsFlowExport(){
const st=chainsFlowState,open=st.open
if(!open||open.draft)return
const show=()=>bridgeCall("flows.export_json",[open.playbookId]).then((text)=>{
const pop=document.createElement("div")
pop.className="cmds-popover glass-panel cf-dialog"
pop.innerHTML='<div class="cmds-popover-title">Export "'+flowEscape(open.name)+'"</div><div class="cmds-popover-hint">This JSON holds the whole diagram. Import it here or on another computer with Import. Suggested file name: <b>'+flowEscape(chainsFlowFileName(open.name))+'</b></div><div class="cmds-popover-field"><textarea class="cf-json" readonly spellcheck="false"></textarea></div><div class="cmds-popover-actions"><button type="button" data-x="close">Close</button><button type="button" data-x="file">Save to a file...</button><button type="button" class="cmds-popover-confirm" data-x="copy">Copy</button></div>'
const area=pop.querySelector("textarea")
area.value=String(text||"")
openModal(pop)
pop.querySelector('[data-x="close"]').addEventListener("click",()=>closeModal())
pop.querySelector('[data-x="copy"]').addEventListener("click",()=>chainsFlowCopyText(area.value,area))
// The app has one "save this text" dialog (the terminal's): it proposes a .txt name, the content is the same JSON.
pop.querySelector('[data-x="file"]').addEventListener("click",()=>bridgeCall("flows.export_file",[open.playbookId]).then((res)=>res&&res.ok&&res.path?res.path:null,(err)=>{
if(!chainsFlowBridgeMissing(err))throw err
return bridgeCall("terminal.save_output_to_file",[area.value])
}).then((path)=>{if(path)chainsFlowToast("Saved to "+path)}).catch((err)=>chainsFlowToast(chainsFlowErrorText(err,"Could not save the file"),"error")))
setTimeout(()=>{area.focus();area.select()},0)
}).catch((err)=>chainsFlowToast(chainsFlowErrorText(err,"Could not export the chain"),"error"))
if(!open.dirty){show();return}
appConfirm("Export with your unsaved changes?",{okLabel:"Save and export",extraLabel:"Export the saved version"}).then((choice)=>{
if(st.open!==open)return
if(choice==="extra")show()
else if(choice===true)chainsFlowSave().then((saved)=>{if(saved)show()})
})
}
function chainsFlowImportPrompt(){
const pop=document.createElement("div")
pop.className="cmds-popover glass-panel cf-dialog"
pop.innerHTML='<div class="cmds-popover-title">Import a chain diagram</div><div class="cmds-popover-hint">Paste the JSON of a chain export, or pick the file. It is added as a new chain and marked "review before running".</div>'+
'<div class="cmds-popover-field"><label>Chain JSON</label><textarea class="cf-json" spellcheck="false" placeholder=\'{"loya_chain":1,"name":"...","graph":{...}}\'></textarea></div>'+
'<div class="cmds-popover-field"><label>Name (optional: the name in the file is used otherwise)</label><input type="text" class="cf-import-name" maxlength="120" autocomplete="off"></div>'+
'<input type="file" class="cf-file hidden" accept=".json,application/json,text/plain">'+
'<div class="cmds-popover-error hidden"></div><div class="cmds-popover-actions"><button type="button" data-x="cancel">Cancel</button><button type="button" data-x="pick">Choose a file...</button><button type="button" class="cmds-popover-confirm" data-x="ok">Import</button></div>'
openModal(pop)
const area=pop.querySelector("textarea"),nameInput=pop.querySelector(".cf-import-name"),file=pop.querySelector(".cf-file"),err=pop.querySelector(".cmds-popover-error")
const fail=(message)=>{err.textContent=message;err.classList.remove("hidden")}
pop.querySelector('[data-x="cancel"]').addEventListener("click",()=>closeModal())
const imported=(res)=>{
closeModal(true)
chainsFlowToast("Chain imported - review it before running")
if(typeof acInvalidateCallers==="function")acInvalidateCallers()
return Promise.all([chainsFlowRefreshIndex(),typeof chainsRefreshList==="function"&&!chainsFlowState.open?chainsRefreshList():null]).then(()=>{if(res&&res.playbook_id!==undefined)chainsOpenChain(res.playbook_id)})
}
// The native file dialog (flows.import_file) picks and imports in one step; without it the page reads the file itself.
pop.querySelector('[data-x="pick"]').addEventListener("click",()=>bridgeCall("flows.import_file",[]).then((res)=>{
if(res&&res.playbook_id!==undefined&&res.ok!==false)return imported(res)
if(res&&res.error)fail(String(res.error))
},(e)=>{if(chainsFlowBridgeMissing(e))file.click();else fail(chainsFlowErrorText(e,"Import failed"))}))
file.addEventListener("change",()=>{
const f=file.files&&file.files[0]
if(!f)return
if(f.size>2*1024*1024){fail("That file is too large to be a chain export.");return}
const reader=new FileReader()
reader.onload=()=>{area.value=String(reader.result||"");err.classList.add("hidden")}
reader.onerror=()=>fail("Could not read that file.")
reader.readAsText(f)
file.value=""
})
pop.querySelector('[data-x="ok"]').addEventListener("click",()=>{
const text=area.value.trim()
if(!text){fail("Paste the chain JSON or choose a file first.");return}
bridgeCall("flows.import_json",[text,nameInput.value.trim()||null]).then(imported).catch((e)=>fail(chainsFlowErrorText(e,"Import failed")))
})
setTimeout(()=>area.focus(),0)
}
// The starter gallery. Inside the editor a template can replace the open diagram; everywhere it can start a new chain.
function chainsFlowTemplatesPrompt(){
const st=chainsFlowState
chainsFlowCatalog().then((catalog)=>{
const pop=document.createElement("div")
pop.className="cmds-popover glass-panel cf-dialog cf-gallery"
pop.innerHTML='<div class="cmds-popover-title">Starter diagrams</div><div class="cf-tpl-list">'+chainsFlowTemplatesHtml(catalog.templates)+'</div><div class="cmds-popover-actions"><button type="button" data-x="close">Close</button></div>'
if(!st.open)pop.querySelectorAll('[data-cf-tpl="here"]').forEach((b)=>b.remove())
openModal(pop)
pop.querySelector('[data-x="close"]').addEventListener("click",()=>closeModal())
pop.addEventListener("click",(e)=>{
const btn=e.target.closest&&e.target.closest("[data-cf-tpl]")
if(!btn)return
const id=btn.dataset.id
if(btn.dataset.cfTpl==="new"){closeModal(true);chainsFlowNewPrompt(id);return}
const open=st.open
if(!open||!st.view)return
const apply=()=>bridgeCall("flows.template",[id]).then((graph)=>{
if(st.open!==open||!st.view)return
closeModal(true)
st.view.editor.setGraph(graph)
st.view.inspector.show(null)
chainsFlowChanged(open)
st.view.editor.focus()
}).catch((err)=>chainsFlowToast(chainsFlowErrorText(err,"Could not load the template"),"error"))
if(chainsFlowIsBlank(st.view.editor.getGraph())){apply();return}
appConfirm("Replace this diagram with the template?",{okLabel:"Replace",danger:true,bodyHtml:"<div>Every node of the open diagram is replaced. Nothing is stored until you save.</div>"}).then((ok)=>{if(ok)apply()})
})
})
}
// ---- built-in demos (flow_demos.py). They are shipped in code; opening one copies it into the user's chains as an
// unreviewed "Demo copy" (flows.create_from_demo), so the originals stay pristine and nothing is stored before that.
function chainsFlowOpenDemo(demoId){
const st=chainsFlowState
if(st.demoBusy)return Promise.resolve(null)
st.demoBusy=true
return bridgeCall("flows.create_from_demo",[demoId]).then((res)=>{
st.demoBusy=false
if(typeof closeModal==="function")closeModal(true)
if(typeof acInvalidateCallers==="function")acInvalidateCallers()
const d=((st.catalog&&st.catalog.demos)||[]).find((x)=>x.id===demoId)
chainsFlowToast("Copied the demo"+(d?" \""+d.name+"\"":"")+" into your chains. Review it before you run it.")
st.ids[String(res.playbook_id)]=true
chainsFlowRefreshIndex()
if(typeof chainsRefreshList==="function"&&!st.open)chainsRefreshList().then(()=>chainsOpenChain(res.playbook_id))
else if(typeof chainsOpenChain==="function")chainsOpenChain(res.playbook_id)
return res
}).catch((err)=>{st.demoBusy=false;chainsFlowToast(chainsFlowErrorText(err,"Could not open the demo"),"error");return null})
}
function chainsFlowDemosBind(root){
root.addEventListener("click",(e)=>{
const b=e.target&&e.target.closest?e.target.closest("[data-demo]"):null
if(b)chainsFlowOpenDemo(b.dataset.demo)
})
}
// The demos gallery (the "Start from a demo" choice of New chain).
function chainsFlowDemosPrompt(){
return chainsFlowCatalog().then((catalog)=>{
const pop=document.createElement("div")
pop.className="cmds-popover glass-panel cf-dialog cf-gallery cf-demo-gallery"
pop.setAttribute("role","dialog")
pop.setAttribute("aria-label","Demo diagrams")
pop.innerHTML='<div class="cmds-popover-title">Demo diagrams</div><div class="cf-demo-intro">Worked pentest workflows built from the node catalog. Opening one copies it into your chains, marked for review; the built-in original stays unchanged.</div><div class="cf-demo-grid">'+chainsFlowDemosHtml(catalog.demos)+'</div><div class="cmds-popover-actions"><button type="button" data-x="close">Close</button></div>'
openModal(pop)
pop.querySelector('[data-x="close"]').addEventListener("click",()=>closeModal())
chainsFlowDemosBind(pop)
const first=pop.querySelector(".cf-demo")
if(first)setTimeout(()=>first.focus(),0)
return pop
})
}
// Called by chainsRenderList (pages/chains.js) after the cards: the Demos section under the user's chains.
function chainsFlowDecorateList(wrap,query){
const st=chainsFlowState
if(!wrap||!chainsFlowMount())return
if(!st.catalog){chainsFlowCatalog().then((c)=>{if(c&&Array.isArray(c.demos)&&c.demos.length&&typeof chainsRenderList==="function"&&st.catalog)chainsRenderList()});return}
const demos=chainsFlowFilterDemos(st.catalog.demos,query)
if(!demos.length)return
const sec=document.createElement("section")
sec.className="cf-demos"+(st.demosCollapsed?" is-collapsed":"")
sec.setAttribute("aria-label","Demos")
sec.innerHTML='<div class="cf-demos-head"><button type="button" class="cf-demos-toggle" aria-expanded="'+(st.demosCollapsed?"false":"true")+'"><i class="icon icon-arrow-down"></i><span>Demos</span></button><span class="cf-demos-sub">Built-in example diagrams. Opening one makes a copy in your chains.</span></div><div class="cf-demo-grid">'+chainsFlowDemosHtml(demos)+"</div>"
sec.querySelector(".cf-demos-toggle").addEventListener("click",(e)=>{
st.demosCollapsed=!st.demosCollapsed
sec.classList.toggle("is-collapsed",st.demosCollapsed)
e.currentTarget.setAttribute("aria-expanded",st.demosCollapsed?"false":"true")
})
chainsFlowDemosBind(sec.querySelector(".cf-demo-grid"))
wrap.appendChild(sec)
}
// New Diagram: name, optional /caller, optional starter template -> flows.create -> open it. opts.blank: the "Blank diagram"
// choice of the New chain chooser, so no template list.
function chainsFlowNewPrompt(templateId,opts){
const blank=!!(opts&&opts.blank)
const st=chainsFlowState
const ready=typeof acRefreshCallers==="function"?Promise.resolve(acRefreshCallers(true)).catch(()=>{}):Promise.resolve()
Promise.all([chainsFlowCatalog(),ready]).then((res)=>{
const templates=Array.isArray(res[0].templates)?res[0].templates:[]
let picked=templateId&&templates.some((t)=>t.id===templateId)?templateId:""
const pop=document.createElement("div")
pop.className="cmds-popover glass-panel cf-dialog cf-new"
pop.innerHTML='<div class="cmds-popover-title">'+(blank?"New blank diagram":"New diagram")+'</div><div class="cmds-popover-field"><label>Chain name</label><input type="text" class="cf-new-name" maxlength="120" autocomplete="off"></div>'+
'<div class="cmds-popover-field"><label>Caller (optional)</label><div class="cmds-chain-caller"><span class="cmds-chain-caller-slash">/</span><input type="text" class="cf-new-caller" maxlength="32" spellcheck="false" autocomplete="off"></div><div class="cmds-popover-hint">Type it as /caller in the terminal or the AI input to run this chain. Lowercase letters, digits, - and _.</div></div>'+
(blank?"":'<div class="cmds-popover-field"><label>Start from</label><div class="cf-pick-list"><button type="button" class="cf-pick" data-tpl=""><span class="cf-pick-name">Blank diagram</span><span class="cf-pick-desc">Only a Start node.</span></button>'+templates.map((t)=>'<button type="button" class="cf-pick" data-tpl="'+flowEscape(t.id)+'"><span class="cf-pick-name">'+flowEscape(t.name||t.id)+'</span><span class="cf-pick-desc">'+flowEscape(t.description||"")+"</span></button>").join("")+"</div></div>")+
'<div class="cmds-popover-error hidden"></div><div class="cmds-popover-actions"><button type="button" data-x="cancel">Cancel</button><button type="button" class="cmds-popover-confirm" data-x="ok">Create</button></div>'
openModal(pop)
const nameInput=pop.querySelector(".cf-new-name"),callerInput=pop.querySelector(".cf-new-caller"),err=pop.querySelector(".cmds-popover-error")
const fail=(message)=>{err.textContent=message;err.classList.remove("hidden")}
const paint=()=>pop.querySelectorAll(".cf-pick").forEach((b)=>b.classList.toggle("active",b.dataset.tpl===picked))
paint()
let callerEdited=false
nameInput.addEventListener("input",()=>{if(!callerEdited&&typeof acSlugifyCaller==="function")callerInput.value=acSlugifyCaller(nameInput.value)})
callerInput.addEventListener("input",()=>{callerEdited=true;callerInput.value=callerInput.value.toLowerCase().replace(/^\//,"")})
const pickList=pop.querySelector(".cf-pick-list")
if(pickList)pickList.addEventListener("click",(e)=>{
const b=e.target.closest&&e.target.closest(".cf-pick")
if(!b)return
picked=b.dataset.tpl||""
paint()
if(!nameInput.value.trim()&&picked){const t=templates.find((x)=>x.id===picked);if(t){nameInput.value=t.name||"";nameInput.dispatchEvent(new Event("input"))}}
})
let busy=false
function create(){
const name=nameInput.value.trim(),caller=callerInput.value.trim()
if(!name){fail("Name is required.");return}
const problem=caller&&typeof acCallerError==="function"&&typeof acState!=="undefined"?acCallerError(caller,acState.callers,null):""
if(problem){fail(problem);return}
if(busy)return
busy=true
bridgeCall("flows.create",[name,null,caller||null,picked||null]).then((res)=>{
closeModal(true)
if(typeof acInvalidateCallers==="function")acInvalidateCallers()
st.ids[String(res.playbook_id)]=true
chainsFlowRefreshIndex()
if(typeof chainsRefreshList==="function"&&!st.open)chainsRefreshList().then(()=>chainsOpenChain(res.playbook_id))
else chainsOpenChain(res.playbook_id)
}).catch((e)=>{busy=false;fail(chainsFlowErrorText(e,"Create failed"))})
}
pop.querySelector('[data-x="cancel"]').addEventListener("click",()=>closeModal())
pop.querySelector('[data-x="ok"]').addEventListener("click",create)
;[nameInput,callerInput].forEach((el)=>el.addEventListener("keydown",(e)=>{if(e.key==="Enter"){e.preventDefault();create()}}))
setTimeout(()=>nameInput.focus(),0)
})
}
// Pure: the chain settings form values -> a clean settings object (limits as in flow_schema.LIMITS).
function chainsFlowCleanSettings(raw,base){
const r=raw&&typeof raw==="object"?raw:{}
const b=Object.assign({shell:"",run_timeout:1800,max_visits:200,on_error:"stop"},base&&typeof base==="object"?base:{})
const num=(v,low,high,fallback)=>{const n=Math.round(Number(v));return Number.isFinite(n)?Math.max(low,Math.min(high,n)):fallback}
const out=Object.assign({},b,{shell:String(r.shell===undefined||r.shell===null?b.shell:r.shell),run_timeout:num(r.run_timeout,10,86400,b.run_timeout),max_visits:num(r.max_visits,1,2000,b.max_visits),on_error:r.on_error==="continue"?"continue":r.on_error==="stop"?"stop":b.on_error})
// script isolation: only an explicit override is stored; "inherit" (use the app setting) is the absence of the key
const iso=r.script_isolation===undefined?b.script_isolation:r.script_isolation
if(iso==="sandboxed"||iso==="allow")out.script_isolation=iso
else delete out.script_isolation
return out
}
// Settings of the whole chain (graph.settings). Applied through editor.updateNode so the change is one undo step.
function chainsFlowSettingsPrompt(){
const st=chainsFlowState,open=st.open
if(!open||!st.view)return
const graph=st.view.editor.getGraph()
const cur=chainsFlowCleanSettings({},graph.settings)
const shells=Array.isArray((st.catalog||{}).shells)?st.catalog.shells:[]
const pop=document.createElement("div")
pop.className="cmds-popover glass-panel cf-dialog cf-new"
pop.innerHTML='<div class="cmds-popover-title">Chain settings</div>'+
'<div class="cmds-popover-field"><label>On error: when a node fails and nothing is connected to its fail / error port</label><div class="cf-pick-list"><button type="button" class="cf-pick" data-err="stop"><span class="cf-pick-name">Stop the run</span><span class="cf-pick-desc">The run ends as failed. Connect the fail port to handle a failure yourself.</span></button><button type="button" class="cf-pick" data-err="continue"><span class="cf-pick-name">Continue</span><span class="cf-pick-desc">That path simply ends there; the rest of the run carries on.</span></button></div></div>'+
'<div class="cmds-popover-field"><label>Time limit for the whole run (seconds, 10 - 86400)</label><input type="number" class="cf-set-timeout" min="10" max="86400" value="'+flowEscape(cur.run_timeout)+'"></div>'+
'<div class="cmds-popover-field"><label>Most node visits in one run (stops endless loops, 1 - 2000)</label><input type="number" class="cf-set-visits" min="1" max="2000" value="'+flowEscape(cur.max_visits)+'"></div>'+
'<div class="cmds-popover-field"><label>Shell for the commands</label><select class="cf-set-shell fi-select"><option value="">App default</option>'+shells.map((s)=>'<option value="'+flowEscape(s.id)+'"'+(s.id===cur.shell?" selected":"")+">"+flowEscape(s.label||s.id)+"</option>").join("")+"</select></div>"+
'<div class="cmds-popover-field"><label>Scripts in this diagram</label><div class="cf-pick-list cf-iso-list"><button type="button" class="cf-pick" data-iso="inherit"><span class="cf-pick-name">Use app setting</span><span class="cf-pick-desc">Follow Settings &gt; Extensions &gt; Chain diagrams.</span></button><button type="button" class="cf-pick" data-iso="sandboxed"><span class="cf-pick-name">Sandboxed only</span><span class="cf-pick-desc">Scripts run only inside a sandbox. On a system without one, this diagram does not run.</span></button><button type="button" class="cf-pick" data-iso="allow"><span class="cf-pick-name">Allow unsandboxed scripts</span><span class="cf-pick-desc">Where there is no sandbox, scripts run with no isolation. Ignored for AI-made or unreviewed diagrams.</span></button></div></div>'+
'<div class="cmds-popover-actions"><button type="button" data-x="cancel">Cancel</button><button type="button" class="cmds-popover-confirm" data-x="ok">Apply</button></div>'
let onError=cur.on_error,iso=cur.script_isolation||"inherit"
const paint=()=>{pop.querySelectorAll("[data-err]").forEach((b)=>b.classList.toggle("active",b.dataset.err===onError));pop.querySelectorAll("[data-iso]").forEach((b)=>b.classList.toggle("active",b.dataset.iso===iso))}
pop.querySelector(".cf-iso-list").addEventListener("click",(e)=>{const b=e.target.closest&&e.target.closest("[data-iso]");if(b){iso=b.dataset.iso;paint()}})
paint()
openModal(pop)
pop.querySelector(".cf-pick-list").addEventListener("click",(e)=>{const b=e.target.closest&&e.target.closest("[data-err]");if(b){onError=b.dataset.err;paint()}})
pop.querySelector('[data-x="cancel"]').addEventListener("click",()=>closeModal())
pop.querySelector('[data-x="ok"]').addEventListener("click",()=>{
const next=chainsFlowCleanSettings({shell:pop.querySelector(".cf-set-shell").value,run_timeout:pop.querySelector(".cf-set-timeout").value,max_visits:pop.querySelector(".cf-set-visits").value,on_error:onError,script_isolation:iso},cur)
closeModal(true)
if(st.open!==open||!st.view||JSON.stringify(next)===JSON.stringify(cur))return
const anchor=st.view.editor.getGraph().nodes[0]
if(anchor)st.view.editor.updateNode(anchor.id,(node,g)=>{g.settings=next})
st.view.editor.focus()
})
}
function chainsFlowToggleIssues(force){
const st=chainsFlowState,open=st.open
if(!open||!st.view)return
const pop=st.view.root.querySelector(".cf-issues-pop")
const show=force===undefined?pop.classList.contains("hidden"):!!force
if(show)pop.innerHTML=chainsFlowIssuesHtml(open.issues)
pop.classList.toggle("hidden",!show)
}
function chainsFlowOnClick(e){
const st=chainsFlowState,open=st.open
if(!open||!st.view)return
const btn=e.target.closest&&e.target.closest("[data-cf]")
if(!btn||btn.disabled){if(!(e.target.closest&&e.target.closest(".cf-status-wrap")))chainsFlowToggleIssues(false);return}
const what=btn.dataset.cf
if(what!=="issues"&&what!=="issue")chainsFlowToggleIssues(false)
if(what==="back")chainsFlowLeave().then((ok)=>{if(ok&&typeof chainsRefreshList==="function")chainsRefreshList()})
else if(what==="save")chainsFlowSave()
else if(what==="run")chainsFlowRun()
else if(what==="dry")chainsFlowDryRun()
else if(what==="history"){
// The Run History tab of the Chains page (pages/chains.js) when it is there, else the run panel's own list.
if(typeof loyaOpenChainHistory==="function"){const id=open.playbookId;chainsFlowLeave().then((ok)=>{if(ok)loyaOpenChainHistory(id)})}
else st.view.run.showHistory(open.playbookId)
}
else if(what==="settings")chainsFlowSettingsPrompt()
else if(what==="templates")chainsFlowTemplatesPrompt()
else if(what==="import")chainsFlowImportPrompt()
else if(what==="export")chainsFlowExport()
else if(what==="revert")chainsFlowRevert()
else if(what==="delete")chainsFlowDelete()
else if(what==="reviewed")chainsFlowMarkReviewed()
else if(what==="issues")chainsFlowToggleIssues()
else if(what==="issue"){
const node=btn.dataset.node
chainsFlowToggleIssues(false)
if(node){st.view.editor.select([node]);st.view.inspector.show(node);st.view.editor.focus()}
}
}
// Pure: does Ctrl+S belong to the diagram view? Yes while focus is inside it, or nowhere in particular (a dialog just
// closed and left focus on the page body). Never while a dialog is open or another panel (terminal, AI) has the focus.
function chainsFlowOwnsSave(active,root,body,dialogOpen){
if(dialogOpen||!root)return false
if(!active||active===body)return true
return typeof root.contains==="function"&&root.contains(active)
}
function chainsFlowOnKey(e){
if(!(e.ctrlKey||e.metaKey)||e.altKey||e.shiftKey||String(e.key).toLowerCase()!=="s")return
const st=chainsFlowState
if(!st.open||!st.view||!chainsFlowPageActive())return
if(!chainsFlowOwnsSave(document.activeElement,st.view.root,document.body,!!document.querySelector(".confirm-overlay,#appModalBackdrop,.lock-screen:not(.hidden)")))return
e.preventDefault()
e.stopPropagation()
chainsFlowSave()
}
// ---- running a diagram chain from elsewhere (/caller in the terminal or the AI input, "Run again" on a run card)
function chainsFlowHeadless(){
const st=chainsFlowState
if(st.headless)return st.headless
const host=document.createElement("div")
st.headless=flowRunCreate(host,null,{toast:chainsFlowToast,
onFinish:(status)=>{
chainsFlowRefreshIndex()
// A dry run has nothing to show but its report: open the diagram with it.
if(status&&status.mode==="dry"&&status.playbook_id!=null)loyaOpenChainDiagram(status.playbook_id).then((ok)=>{if(ok&&chainsFlowState.view)chainsFlowState.view.run.showStored(status.run_id)})
},
onReviewed:()=>chainsFlowRefreshIndex()})
return st.headless
}
// The branch path a run took, from its status (edges_taken in the order the engine took them) and the diagram:
// "Ping the host -> Host alive? [alive] -> Nmap scan". Branch names are shown except the plain out/success ports.
function chainsFlowRunPath(graph,status){
const s=status||{},g=graph||{}
const nodes={},edges={}
;(Array.isArray(g.nodes)?g.nodes:[]).forEach((n)=>{if(n&&n.id)nodes[n.id]=n})
;(Array.isArray(g.edges)?g.edges:[]).forEach((e)=>{if(e&&e.id)edges[e.id]=e})
const recs=s.nodes&&typeof s.nodes==="object"?s.nodes:{}
const name=(id)=>{const n=nodes[id];const t=String(n&&(n.title||(typeof FLOW_NODE_TYPES!=="undefined"&&FLOW_NODE_TYPES[n.type]&&FLOW_NODE_TYPES[n.type].label)||n.type)||id);return recs[id]&&recs[id].state==="fail"?t+" (failed)":t}
const steps=[]
const taken=(Array.isArray(s.edges_taken)?s.edges_taken:[]).map((id)=>edges[id]).filter(Boolean)
if(taken.length){
let last=null
taken.forEach((e)=>{
const from=nodes[e.from]
if(e.from!==last&&!(from&&from.type==="start"))steps.push(name(e.from))
const port=String(e.port||"")
if(port&&port!=="out"&&port!=="success"&&steps.length)steps[steps.length-1]+=" ["+port+"]"
steps.push(name(e.to))
last=e.to
})
}else{
Object.keys(recs).filter((id)=>recs[id]&&(recs[id].state==="success"||recs[id].state==="fail")&&!(nodes[id]&&nodes[id].type==="start")).sort((a,b)=>String(recs[a].started_at||"").localeCompare(String(recs[b].started_at||""))||(Number(recs[a].seq)||0)-(Number(recs[b].seq)||0)).forEach((id)=>steps.push(name(id)))
}
const shown=steps.length>12?steps.slice(0,5).concat(["..."],steps.slice(-6)):steps
return shown.join(" \u2192 ")
}
// What a /caller diagram run leaves in the terminal when it ends. -> {kind:"ok"|"error"|"info", lines:[...]}
function chainsFlowRunSummary(status,graph,info){
const s=status||{},o=info||{}
const view=typeof flowRunStatusView==="function"?flowRunStatusView(s,Date.now(),typeof flowRunTitles==="function"?flowRunTitles(graph):{}):{label:String(s.state||""),sub:"",state:String(s.state||"")}
const name=String(s.name||o.name||"Action chain")
const title="Chain "+(o.caller?"/"+o.caller+" ("+name+")":name)+": "+view.label+(view.sub?" - "+view.sub:"")
const path=chainsFlowRunPath(graph,s)
const lines=[title]
if(path)lines.push("Path: "+path)
lines.push("Open logs: Chains page > "+name+" > History, then the log icon of this run")
const state=String(s.state||"")
return {kind:state==="done"?"ok":state==="failed"||state==="timeout"?"error":"info",lines:lines}
}
// Watches a run started from the terminal and prints its summary there when it ends. Status polls skip node outputs.
function chainsFlowReportToTerminal(runId,playbookId,sessionId,info){
let errors=0
const poll=()=>bridgeCall("flows.run_status",[runId,1e9]).then((status)=>{
errors=0
if(!status||typeof flowRunIsFinal!=="function"||!flowRunIsFinal(status.state)){setTimeout(poll,1500);return}
return bridgeCall("flows.get",[playbookId]).then((d)=>d&&d.graph,()=>null).then((graph)=>{
const sum=chainsFlowRunSummary(status,graph,info)
if(typeof termPrintNotice==="function")termPrintNotice(sessionId,sum.lines,sum.kind)
})
}).catch((err)=>{
if(/no such run/i.test(chainsFlowErrorText(err,""))||++errors>20)return
setTimeout(poll,Math.min(15000,1500*errors))
})
setTimeout(poll,1000)
}
// -> Promise<null> when the chain has no diagram (the caller then runs it the linear way), else {started,flow:true,run_id}.
// A failed lookup also answers {started:false}: a diagram chain must never fall back to its old step list.
function chainsFlowRunChain(playbookId,ctx){
const st=chainsFlowState
if(typeof flowRunCreate!=="function")return Promise.resolve(null)
return bridgeCall("flows.list").then((rows)=>{
const idx=chainsFlowIndex(rows)
st.ids=idx.ids;st.meta=idx.meta;st.loaded=true
const m=idx.meta[String(playbookId)]
if(!m||!m.hasGraph)return null
const source=chainsFlowRunSource(ctx&&ctx.source)
const open=st.open
// Typed as /caller in the terminal: the result is printed in that session when the run ends (a linear chain shows its card there).
const session=ctx&&ctx.source==="terminal"&&typeof termState!=="undefined"?termState.activeId:null
const report=(runId)=>{if(runId&&session)chainsFlowReportToTerminal(runId,playbookId,session,{name:m.name,caller:m.caller})}
// The diagram is on screen: run it there, so the node states light up.
if(open&&!open.draft&&String(open.playbookId)===String(playbookId)&&chainsFlowPageActive())return chainsFlowRun({source:source}).then((runId)=>{report(runId);return {started:!!runId,flow:true,run_id:runId||null}})
return chainsFlowHeadless().confirmAndRun(playbookId,{name:m.name,source:source}).then((runId)=>{
if(runId&&typeof showStatusIsland==="function")showStatusIsland("Running "+m.name+" - open it on the Chains page to watch")
report(runId)
return {started:!!runId,flow:true,run_id:runId||null}
})
}).catch((err)=>{
// Not knowing whether the chain has a diagram is no reason to run its old step list instead: nothing runs.
chainsFlowToast(chainsFlowErrorText(err,"Could not check the action chain"),"error")
return {started:false,flow:true,reason:"error"}
})
}
// ---- public entry points
function loyaOpenChainDiagram(playbookId){
return Promise.resolve(goToPage("chains")).then(()=>{
const st=chainsFlowState
if(!chainsFlowMount())return false
if(st.open&&!st.open.draft&&String(st.open.playbookId)===String(playbookId))return true
return chainsFlowLeave().then((ok)=>ok?chainsFlowOpen(playbookId).then((open)=>!!open):false)
})
}
// Opens an UNSAVED diagram for review (what an AI proposes). Nothing is stored until the operator presses Save.
function loyaOpenChainDraft(draft){
const d=draft&&typeof draft==="object"?draft:{}
// Checked before anything is closed: a bad proposal must not cost the operator the diagram that is open.
let graph=d.graph
try{
if(typeof graph==="string")graph=flowParse(graph)
if(!graph||typeof graph!=="object"||!Array.isArray(graph.nodes))throw new Error("That diagram is not valid: 'nodes' is missing.")
graph=flowNormalize(flowClone(graph))
}catch(err){chainsFlowToast(chainsFlowErrorText(err,"That diagram is not valid"),"error");return Promise.resolve(false)}
return Promise.resolve(goToPage("chains")).then(()=>{
if(!chainsFlowMount())return false
return chainsFlowLeave().then((ok)=>{
if(!ok)return false
return Promise.all([chainsFlowCatalog(),chainsFlowPrefs()]).then(()=>{
const flagged=d.ai_made!==false
const open=chainsFlowShow({playbookId:null,name:String(d.name||"New diagram").trim().slice(0,120)||"New diagram",caller:String(d.caller||"").trim().toLowerCase().replace(/^\//,""),aiMade:flagged,reviewed:!flagged,draft:true,flagged:flagged,dirty:true,client:String(d.client||"").slice(0,60)},graph)
if(!open)return false
chainsFlowValidateNow(open)
return true
})
})
})
}
if(typeof document!=="undefined"&&document.addEventListener){
document.addEventListener("keydown",chainsFlowOnKey,true)
document.addEventListener("loya:page-shown",(e)=>{
if(!e.detail||e.detail.page!=="chains")return
if(!chainsFlowMount())return
if(!e.detail.first){chainsFlowRefreshIndex();chainsFlowReload()}
})
// Chains were created or changed elsewhere (the AI card): refresh the diagram index and the list behind it.
document.addEventListener("loya:chains-changed",()=>{
if(!chainsFlowState.mounted)return
chainsFlowRefreshIndex()
if(typeof chainsRefreshList==="function"&&chainsFlowPageActive()&&!chainsFlowState.open&&typeof chainsState!=="undefined"&&chainsState.currentId==null)chainsRefreshList()
else chainsFlowReload()
})
// A diagram chain never shows as a step list (e.g. it was opened before the index of diagrams had loaded).
document.addEventListener("loya:chain-rendered",(e)=>{
const id=e.detail&&e.detail.id
if(id!=null&&chainsFlowState.ids[String(id)]&&!chainsFlowState.open)chainsFlowOpen(id)
})
}
if(typeof module!=="undefined"&&module.exports)module.exports={CHAINS_FLOW_PREFS,chainsFlowState,chainsFlowIndex,chainsFlowOrigin,chainsFlowOriginText,chainsFlowFilterDemos,chainsFlowDemosHtml,chainsFlowBadges,chainsFlowBadgesHtml,chainsFlowGraphSig,chainsFlowIsBlank,chainsFlowIssueSummary,chainsFlowIssuesHtml,chainsFlowBundle,chainsFlowRunSource,chainsFlowFileName,chainsFlowTemplatesHtml,chainsFlowHeadState,chainsFlowErrorText,chainsFlowViewHtml,chainsFlowCleanSettings,chainsFlowOwnsSave,chainsFlowBridgeMissing,chainsFlowIsCompact,chainsFlowNeedsRefit,chainsFlowRunPath,chainsFlowRunSummary}
