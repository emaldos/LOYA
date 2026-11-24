// AI panel <-> Chain Diagrams. A chat model answers a "/newchain ..." request with a fenced ```loya-chain block (graph JSON or
// an export bundle {name, graph}); a tool-capable client calls chain_create / chain_update itself. Either way the panel shows
// a review card instead of raw JSON. Nothing here runs a chain: the card only opens the diagram editor, and the chain is
// stored as AI-made + not reviewed, so the run confirmation demands the review.
// Everything in the JSON came from a model and may be hostile: every value is coerced to a capped string and escaped
// before it reaches HTML, there are no inline handlers, and the text is only ever parsed with JSON.parse.
const AI_CHAIN_FENCE="loya-chain"
const AI_CHAIN_FLAG="AI-made - review before running"
const AI_CHAIN_MAX_BYTES=600000
const AI_CHAIN_OUTLINE_MAX=40
const AI_CHAIN_TOOLS=["chain_create","chain_update"]
function aiChainEsc(s){
return String(s===undefined||s===null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")
}
function aiChainIsObj(v){return !!v&&typeof v==="object"&&!Array.isArray(v)}
// Any value -> one line of plain text, capped. Objects never reach the page as "[object Object]" surprises or huge dumps.
function aiChainText(v,max){
let s=typeof v==="string"?v:(typeof v==="number"||typeof v==="boolean")?String(v):""
s=s.replace(/[\u0000-\u001f\u007f\u2028\u2029\u202a-\u202e\u2066-\u2069]+/g," ").replace(/\s+/g," ").trim()
max=max||120
return s.length>max?s.slice(0,max-1)+"\u2026":s
}
function aiChainPlural(n,word){return n+" "+word+(n===1?"":"s")}
// {ok,name,graph,error}: accepts {name,graph}, an export bundle {loya_chain,name,graph} or a bare graph {nodes,edges}.
function aiChainParse(raw){
const text=String(raw===undefined||raw===null?"":raw).trim()
if(!text)return {ok:false,name:"",graph:null,error:"The block is empty."}
if(text.length>AI_CHAIN_MAX_BYTES)return {ok:false,name:"",graph:null,error:"The diagram is too large."}
let data
try{data=JSON.parse(text)}catch(err){return {ok:false,name:"",graph:null,error:"The diagram is not valid JSON ("+aiChainText(err&&err.message,140)+")."}}
if(!aiChainIsObj(data))return {ok:false,name:"",graph:null,error:"The diagram must be a JSON object."}
let graph=data,name=""
if(aiChainIsObj(data.graph)){graph=data.graph;name=aiChainText(data.name,200)}
else if(typeof data.name==="string")name=aiChainText(data.name,200)
if(!Array.isArray(graph.nodes))return {ok:false,name:name,graph:null,error:"The diagram has no \"nodes\" list."}
if(!Array.isArray(graph.edges))graph=Object.assign({},graph,{edges:[]})
return {ok:true,name:name,graph:graph,error:""}
}
function aiChainLooksLikeGraph(raw){
const text=String(raw||"")
if(!/"nodes"\s*:/.test(text)||!/"edges"\s*:/.test(text)||!/"type"\s*:/.test(text))return false
return aiChainParse(text).ok
}
// Every chain block of a reply: [{start,end,raw,complete}]. A ```loya-chain fence always counts (even with broken JSON, so the
// user gets the error and a "fix it" button); a ```json / untagged fence counts only when it really holds a graph.
function aiChainFindBlocks(text){
text=String(text===undefined||text===null?"":text)
const out=[]
const re=/```[ \t]*([A-Za-z0-9_+-]*)[^\n]*\r?\n([\s\S]*?)(```|$)/g
let m
while((m=re.exec(text))){
if(m[0]==="")break
const lang=m[1].toLowerCase(),complete=m[3]==="```"
const tagged=lang===AI_CHAIN_FENCE
if(tagged||((lang===""||lang==="json")&&complete&&aiChainLooksLikeGraph(m[2])))out.push({start:m.index,end:m.index+m[0].length,raw:m[2],complete:complete})
if(!complete)break
}
return out
}
function aiChainBlocks(text){
return aiChainFindBlocks(text).map((b)=>{
const parsed=b.complete?aiChainParse(b.raw):{ok:false,name:"",graph:null,error:"The reply was cut off before the diagram was complete."}
return {raw:b.raw,ok:parsed.ok,name:parsed.name,graph:parsed.graph,error:parsed.error}
})
}
// The reply without its chain blocks (the card replaces them).
function aiChainStripBlocks(text){
text=String(text===undefined||text===null?"":text)
const blocks=aiChainFindBlocks(text)
if(!blocks.length)return text
let out="",at=0
blocks.forEach((b)=>{out+=text.slice(at,b.start);at=b.end})
return (out+text.slice(at)).replace(/\n{3,}/g,"\n\n").trim()
}
function aiChainCounts(graph){
const nodes=aiChainIsObj(graph)&&Array.isArray(graph.nodes)?graph.nodes.filter(aiChainIsObj):[]
const edges=aiChainIsObj(graph)&&Array.isArray(graph.edges)?graph.edges.filter(aiChainIsObj):[]
let commands=0,scripts=0,approvals=0
nodes.forEach((n)=>{
const cfg=aiChainIsObj(n.config)?n.config:{}
if(n.type==="command")commands+=Array.isArray(cfg.commands)?cfg.commands.length:(typeof cfg.commands==="string"?1:0)
else if(n.type==="script")scripts++
else if(n.type==="approval")approvals++
})
return {nodes:nodes.length,edges:edges.length,commands:commands,scripts:scripts,approvals:approvals}
}
function aiChainNodeDetail(node){
const cfg=aiChainIsObj(node.config)?node.config:{}
const type=node.type
if(type==="command"){
const list=(Array.isArray(cfg.commands)?cfg.commands:(typeof cfg.commands==="string"?[cfg.commands]:[])).map((c)=>aiChainText(aiChainIsObj(c)?c.text:c,160)).filter(Boolean)
if(!list.length)return "(no command)"
return list[0]+(list.length>1?"  (+"+(list.length-1)+" more"+(cfg.mode==="parallel"?", in parallel":"")+")":"")
}
if(type==="script"){
const lines=typeof cfg.code==="string"?cfg.code.split(/\r?\n/).filter((l)=>l.trim()).length:0
return (aiChainText(cfg.language,12)||"python")+" script, "+aiChainPlural(lines,"line")+(cfg.network===true?", network on":"")
}
if(type==="decision"){
const names=(Array.isArray(cfg.branches)?cfg.branches:[]).map((b)=>aiChainText(aiChainIsObj(b)?b.name:"",24)).filter(Boolean)
return "branches: "+names.concat([aiChainText(cfg.else,24)||"else"]).join(" / ")
}
if(type==="parse")return cfg.mode==="tool"?"read "+(aiChainText(cfg.tool,20)||"nmap")+" output":cfg.mode==="jsonpath"?"JSON path "+aiChainText(cfg.path,80):"regex "+aiChainText(cfg.pattern,80)
if(type==="set")return "set "+((Array.isArray(cfg.assign)?cfg.assign:[]).map((a)=>aiChainText(aiChainIsObj(a)?a.var:"",40)).filter(Boolean).join(", ")||"(nothing)")
if(type==="foreach")return "for each of "+(aiChainText(cfg.items,80)||"(nothing)")
if(type==="wait")return "wait "+(aiChainText(cfg.seconds,10)||"5")+" s"
if(type==="approval")return "asks: "+(aiChainText(cfg.message,100)||"Continue?")
if(type==="output")return (aiChainText(cfg.action,20)||"notify").replace(/_/g," ")+(aiChainText(cfg.title,80)?": "+aiChainText(cfg.title,80):"")
if(type==="subchain")return "runs chain #"+(aiChainText(cfg.playbook_id,12)||"?")
if(type==="end")return "ends the run ("+(cfg.status==="fail"?"fail":"success")+")"
if(type==="comment")return aiChainText(cfg.text,100)
return ""
}
// One row per node, in the order a run would reach them (breadth-first from the start node; the rest in file order):
// [{id,type,title,detail,next:[{port,to}]}] plus {more:n} when the list was cut. Plain data - aiChainCardHtml escapes it.
function aiChainOutline(graph,limit){
limit=limit||AI_CHAIN_OUTLINE_MAX
const nodes=aiChainIsObj(graph)&&Array.isArray(graph.nodes)?graph.nodes.filter(aiChainIsObj):[]
const edges=aiChainIsObj(graph)&&Array.isArray(graph.edges)?graph.edges.filter(aiChainIsObj):[]
const byId=new Map()
nodes.forEach((n)=>{const id=aiChainText(n.id,40);if(id&&!byId.has(id))byId.set(id,n)})
const titleOf=(n)=>aiChainText(n.title,80)||aiChainText(n.type,20)||"node"
const outs=new Map()
edges.forEach((e)=>{
const from=aiChainText(e.from,40),to=aiChainText(e.to,40)
if(!byId.has(from))return
if(!outs.has(from))outs.set(from,[])
outs.get(from).push({port:aiChainText(e.port,24)||"out",to:byId.has(to)?titleOf(byId.get(to)):"(missing node "+to+")",id:to})
})
const order=[],seen=new Set()
const visit=(startId)=>{
const queue=[startId]
while(queue.length){
const id=queue.shift()
if(seen.has(id)||!byId.has(id))continue
seen.add(id);order.push(id)
;(outs.get(id)||[]).forEach((o)=>queue.push(o.id))
}
}
nodes.filter((n)=>n.type==="start").forEach((n)=>visit(aiChainText(n.id,40)))
byId.forEach((_n,id)=>visit(id))
const rows=order.slice(0,limit).map((id)=>{
const n=byId.get(id)
return {id:id,type:aiChainText(n.type,20)||"?",title:titleOf(n),detail:aiChainNodeDetail(n),next:(outs.get(id)||[]).slice(0,12).map((o)=>({port:o.port,to:o.to}))}
})
if(order.length>limit)rows.push({more:order.length-limit})
return rows
}
function aiChainIssueTexts(issues,limit){
const list=(Array.isArray(issues)?issues:[]).map((i)=>aiChainText(aiChainIsObj(i)?i.message:i,300)).filter(Boolean)
limit=limit||8
return list.length>limit?list.slice(0,limit).concat(["and "+(list.length-limit)+" more"]):list
}
// model: {name,graph,state:"checking"|"checked"|"broken"|"stored"|"missing"|"unknown",error,errors,warnings,stored,playbookId,tool,reviewed}
// -> HTML string. Every interpolated value goes through aiChainEsc.
function aiChainCardHtml(model){
model=model||{}
const esc=aiChainEsc
const state=model.state||"checking"
const errors=aiChainIssueTexts(model.errors),warnings=aiChainIssueTexts(model.warnings)
const broken=state==="broken"
const name=aiChainText(model.name,120)||(broken?"Chain diagram":"Untitled chain")
let html='<div class="ai-chain-head"><i class="icon icon-chain"></i><span class="ai-chain-name">'+esc(name)+'</span>'+(model.reviewed?'':'<span class="ai-chain-flag">'+esc(AI_CHAIN_FLAG)+'</span>')+'</div>'
if(state==="unknown")return html+'<div class="ai-chain-note">'+esc(model.note||"The agent created or changed a chain diagram.")+'</div><div class="ai-chain-actions"><button type="button" class="ai-chain-btn ai-chain-btn-main" data-act="chains">Open Chains</button></div>'
if(state==="missing")return html+'<div class="ai-chain-note">'+esc(model.error||"This chain no longer exists.")+'</div>'
if(broken){
html+='<div class="ai-chain-issues ai-chain-errors"><b>The AI did not return a usable diagram</b><ul><li>'+esc(aiChainText(model.error,300)||"The diagram could not be read.")+'</li></ul></div>'
return html+'<div class="ai-chain-actions"><button type="button" class="ai-chain-btn ai-chain-btn-main" data-act="fix">Ask the AI to fix it</button><button type="button" class="ai-chain-btn" data-act="copy">Copy JSON</button></div>'
}
const c=aiChainCounts(model.graph)
const meta=[aiChainPlural(c.nodes,"node"),aiChainPlural(c.edges,"connection")]
if(c.commands)meta.push(aiChainPlural(c.commands,"command"))
if(c.scripts)meta.push(aiChainPlural(c.scripts,"script"))
if(c.approvals)meta.push(aiChainPlural(c.approvals,"approval"))
if(model.tool)meta.push(model.tool==="chain_update"?"changed by the AI":"created by the AI")
html+='<div class="ai-chain-meta">'+esc(meta.join(" \u00b7 "))+'</div>'
const rows=aiChainOutline(model.graph)
if(rows.length){
html+='<ol class="ai-chain-outline">'+rows.map((r)=>{
if(r.more)return '<li class="ai-chain-more">'+esc("+ "+aiChainPlural(r.more,"more node"))+'</li>'
const next=r.next.map((o)=>o.port+" \u2192 "+o.to).join(", ")
return '<li><span class="ai-chain-type ai-chain-type-'+esc(r.type.replace(/[^a-z]/g,""))+'">'+esc(r.type)+'</span><span class="ai-chain-title">'+esc(r.title)+'</span>'+(r.detail?'<span class="ai-chain-detail">'+esc(r.detail)+'</span>':'')+(next?'<span class="ai-chain-next">'+esc(next)+'</span>':'')+'</li>'
}).join("")+'</ol>'
}
if(errors.length)html+='<div class="ai-chain-issues ai-chain-errors"><b>'+esc(aiChainPlural(errors.length,"error")+" - it cannot run until fixed")+'</b><ul>'+errors.map((t)=>'<li>'+esc(t)+'</li>').join("")+'</ul></div>'
if(warnings.length)html+='<div class="ai-chain-issues ai-chain-warnings"><b>'+esc(aiChainPlural(warnings.length,"warning"))+'</b><ul>'+warnings.map((t)=>'<li>'+esc(t)+'</li>').join("")+'</ul></div>'
if(state==="checking")html+='<div class="ai-chain-note">Checking the diagram\u2026</div>'
else if(model.error)html+='<div class="ai-chain-note">'+esc(aiChainText(model.error,300))+'</div>'
else if(!errors.length&&state==="checked")html+='<div class="ai-chain-note">The diagram is valid. Open it to review every step - it runs only after you confirm.</div>'
// A draft with errors is not opened: storing would normalize it into something the model never wrote. A stored chain always opens.
const fixable=errors.length>0&&!model.stored
html+='<div class="ai-chain-actions">'+(fixable?'<button type="button" class="ai-chain-btn ai-chain-btn-main" data-act="fix">Ask the AI to fix it</button>':'<button type="button" class="ai-chain-btn ai-chain-btn-main" data-act="open">Open in diagram editor</button>')+'<button type="button" class="ai-chain-btn" data-act="copy">Copy JSON</button></div>'
return html
}
function aiChainJson(model){
if(model&&model.graph)return JSON.stringify({name:aiChainText(model.name,200),graph:model.graph},null,2)
return String((model&&model.raw)||"")
}
// The follow-up prompt for "Ask the AI to fix it". guide is added only when the conversation does not hold it yet.
function aiChainFixPrompt(model,guide){
const errors=aiChainIssueTexts(model&&model.errors,20)
const problems=errors.length?errors:[aiChainText(model&&model.error,300)||"The diagram could not be read."]
return (guide?guide+"\n\n":"")+"The chain diagram you wrote is not valid yet. Problems reported by LOYA NG:\n"+problems.map((t)=>"- "+t).join("\n")+"\n\nFix them and reply with the COMPLETE corrected diagram in one fenced code block tagged "+AI_CHAIN_FENCE+" ({\"name\":...,\"graph\":{...}}). Keep everything that was already right."
}
// "create a chain that pings the target ..." typed without /newchain. Deliberately narrow: a verb of making + chain/diagram/flow.
function aiChainIntent(text){
const t=String(text||"").trim()
if(!t||t.startsWith("/")||t.length>4000)return false
return /^(?:(?:please|pls|can you|could you|hey|hi|ok|okay)[ ,]+)*(?:create|make|build|generate|design|draw|write|draft)\s+(?:me\s+|us\s+)?(?:an?\s+|the\s+|some\s+)?(?:new\s+)?(?:(?:action|attack|automation|recon|scan|pentest)[ -]+)?(?:chain|chain diagram|flow|attack[ -]flow|flow diagram|diagram|workflow)\b/i.test(t)
}
function aiChainChatPrompt(guide,request){
return String(guide||"")+"\n\nWHAT THE CHAIN SHOULD DO\n"+String(request||"").trim()
}
// A finished tool call of an in-app chat turn: {tool,playbookId} for a successful chain_create / chain_update, else null.
function aiChainToolResult(turn){
if(!turn||turn.role!=="tool"||AI_CHAIN_TOOLS.indexOf(turn.tool_name)<0)return null
const content=String(turn.content||"")
if(!content||content.startsWith("Error:"))return null
let data
try{data=JSON.parse(content)}catch(err){return null}
const id=aiChainIsObj(data)?data.playbook_id:null
if(typeof id!=="number"||!Number.isInteger(id)||id<=0)return null
return {tool:turn.tool_name,playbookId:id}
}
// An external agent's turn only lists the tool NAMES it used (no results).
function aiChainAgentTouched(turn){
return !!turn&&turn.role==="assistant"&&Array.isArray(turn.agent_tools)&&turn.agent_tools.some((n)=>AI_CHAIN_TOOLS.indexOf(n)>=0)
}
// Chains that are new, or changed, between two flows.list() results and carry the AI-made mark: [playbook_id].
function aiChainListDiff(before,after){
const old=new Map()
;(Array.isArray(before)?before:[]).forEach((r)=>{if(aiChainIsObj(r))old.set(String(r.playbook_id),String(r.updated_at||""))})
return (Array.isArray(after)?after:[]).filter((r)=>aiChainIsObj(r)&&r.ai_made&&r.has_graph!==false&&(!old.has(String(r.playbook_id))||old.get(String(r.playbook_id))!==String(r.updated_at||""))).map((r)=>r.playbook_id)
}
// ---- DOM side (the app only; node tests stop above) -------------------------------------------------------------------
const aiChainCache={checks:new Map(),stored:new Map(),drafts:new Map(),agent:new Map(),watch:null,guide:null}
function aiChainBridge(path,args){
return typeof bridgeCall==="function"?bridgeCall(path,args||[]):Promise.reject(new Error("The app bridge is not ready."))
}
function aiChainSay(msg,type){
if(typeof showToast==="function")showToast(msg,type)
}
function aiChainErr(err,fallback){
return aiChainText(err&&err.message?err.message:"",240)||fallback
}
function aiChainGuide(){
if(aiChainCache.guide)return Promise.resolve(aiChainCache.guide)
return aiChainBridge("flows.ai_guide").then((g)=>{
if(!g||typeof g.guide!=="string"||!g.guide)throw new Error("The chain guide is not available.")
aiChainCache.guide=g.guide
return g.guide
})
}
function aiChainOpenStored(id){
if(typeof loyaOpenChainDiagram==="function")return Promise.resolve(loyaOpenChainDiagram(id))
if(typeof loyaOpenChain==="function")return Promise.resolve(loyaOpenChain(id))
return Promise.reject(new Error("The Chains page is not available."))
}
// A chain appeared or changed behind the Chains page's back: drop the caller caches and, when that page is showing its list
// (no chain open - refreshing would close it), reload the list so the new chain and its "AI-made - review" badge show.
function aiChainChanged(ids){
if(typeof aiState!=="undefined")aiState.chainCache=null
try{
document.dispatchEvent(new CustomEvent("loya:chains-changed",{detail:{ids:ids||[],source:"ai"}}))
if(typeof acInvalidateCallers==="function")acInvalidateCallers()
const page=document.querySelector?document.querySelector('.page[data-page="chains"]'):null
const listShown=!!page&&page.classList.contains("active")&&typeof chainsState!=="undefined"&&chainsState.currentId==null&&!(typeof chainsFlowState!=="undefined"&&chainsFlowState.open)
if(listShown&&typeof chainsRefreshList==="function")chainsRefreshList()
if(typeof chainsFlowRefreshIndex==="function")chainsFlowRefreshIndex()
}catch(err){}
}
// Nodes an LLM left without positions all sit on one spot: lay them out once, left to right, before the editor opens.
function aiChainLaidOut(graph){
try{
const nodes=graph.nodes.filter(aiChainIsObj)
const spots=new Set(nodes.map((n)=>(Number(n.x)||0)+":"+(Number(n.y)||0)))
if(nodes.length>2&&spots.size<nodes.length&&typeof flowAutoLayout==="function"){
const copy=JSON.parse(JSON.stringify(graph))
return flowAutoLayout(copy)||copy
}
}catch(err){}
return graph
}
// Open a model-written draft: it is stored through flows.create_ai_draft (AI-made, not reviewed, audit-logged with source
// "ai-panel") and opened by id, so it carries the AI-made mark from the first moment - exactly like a chain an AI client
// made with chain_create. One draft is stored once only. If storing is not possible the diagram page takes it as an
// unsaved draft instead (loyaOpenChainDraft), still flagged for review.
function aiChainOpenDraft(model){
const key=model.raw
if(aiChainCache.drafts.has(key))return aiChainOpenStored(aiChainCache.drafts.get(key))
const name=aiChainText(model.name,200)||"AI chain"
const graph=aiChainLaidOut(model.graph)
const client=typeof aiState!=="undefined"?aiChainText(aiState.currentModel||aiState.selectedKind,60):""
return aiChainBridge("flows.create_ai_draft",[name,graph,client]).then((r)=>{
aiChainCache.drafts.set(key,r.playbook_id)
aiChainChanged([r.playbook_id])
return aiChainOpenStored(r.playbook_id)
},(err)=>{
if(typeof loyaOpenChainDraft!=="function")throw err
return Promise.resolve(loyaOpenChainDraft({name:name,graph:graph,ai_made:true,source:"ai-panel",client:client})).then((ok)=>{if(ok===false)throw err})
})
}
function aiChainAskFix(model){
if(typeof aiSendPrompt!=="function"||typeof aiState==="undefined")return
if(aiState.sending){aiChainSay("Wait for the current reply first","error");return}
const hasGuide=aiState.chatHistory.some((t)=>t.role==="user"&&String(t.content||"").indexOf("```"+AI_CHAIN_FENCE)>=0)
const n=aiChainIssueTexts(model.errors,99).length
const shown="Fix the chain diagram ("+(n?aiChainPlural(n,"error"):"it could not be read")+")"
;(hasGuide?Promise.resolve(""):aiChainGuide().catch(()=>"")).then((guide)=>aiSendPrompt(aiChainFixPrompt(model,guide),shown,[]))
}
function aiChainPaint(el,model){
el.className="ai-chain-card"+(model.state==="broken"||(model.errors&&model.errors.length)?" ai-chain-card-invalid":"")
el.innerHTML=aiChainCardHtml(model)
el.querySelectorAll("[data-act]").forEach((btn)=>btn.addEventListener("click",()=>{
const act=btn.dataset.act
if(act==="copy"){
const text=aiChainJson(model)
if(navigator.clipboard)navigator.clipboard.writeText(text).then(()=>aiChainSay("Chain JSON copied")).catch(()=>aiChainSay("Copy failed","error"))
return
}
if(act==="fix"){aiChainAskFix(model);return}
if(act==="chains"){if(typeof loyaOpenChain==="function")Promise.resolve(loyaOpenChain(null)).catch(()=>{});return}
if(act==="open"){
btn.disabled=true
const go=model.stored?aiChainOpenStored(model.playbookId):aiChainOpenDraft(model)
Promise.resolve(go).catch((err)=>aiChainSay(aiChainErr(err,"Could not open the diagram"),"error")).finally(()=>{btn.disabled=false})
}
}))
}
// Card for a ```loya-chain block of a reply. Validation goes through the backend (flows.validate) and is cached per block,
// so re-rendering the chat does not ask again.
function aiChainBlockCard(block){
const el=document.createElement("div")
const model={raw:block.raw,name:block.name,graph:block.graph,state:block.ok?"checking":"broken",error:block.error,errors:[],warnings:[]}
if(!block.ok){aiChainPaint(el,model);return el}
const apply=(res)=>{
if(res&&res.failed){model.state="checked";model.error="The diagram could not be checked: "+res.failed}
else{
model.state="checked"
model.errors=(res&&res.errors)||[];model.warnings=(res&&res.warnings)||[]
if(res&&aiChainIsObj(res.graph)&&Array.isArray(res.graph.nodes)&&res.graph.nodes.length&&!model.errors.some((e)=>e&&e.code==="structure"))model.graph=res.graph
}
aiChainPaint(el,model)
}
const hit=aiChainCache.checks.get(block.raw)
if(hit&&!hit.then){apply(hit);return el}
aiChainPaint(el,model)
const pending=hit||aiChainBridge("flows.validate",[block.graph]).then((res)=>res||{},(err)=>({failed:aiChainErr(err,"the check failed")}))
if(!hit){
aiChainCache.checks.set(block.raw,pending)
pending.then((res)=>{if(res.failed)aiChainCache.checks.delete(block.raw);else aiChainCache.checks.set(block.raw,res)})
}
pending.then(apply)
return el
}
// Card for a chain that is already stored (an AI client called chain_create / chain_update).
function aiChainStoredCard(id,tool,cacheKey){
const el=document.createElement("div")
const model={state:"checking",name:"Chain #"+id,graph:{nodes:[],edges:[]},errors:[],warnings:[],stored:true,playbookId:id,tool:tool}
const apply=(res)=>{
if(res&&res.failed){model.state="missing";model.error=res.failed}
else{
model.state="stored";model.name=res.name;model.graph=res.graph;model.errors=res.errors||[];model.warnings=res.warnings||[]
model.reviewed=!!res.ai_reviewed&&!!res.ai_made
}
aiChainPaint(el,model)
}
const hit=aiChainCache.stored.get(cacheKey)
if(hit&&!hit.then){apply(hit);return el}
aiChainPaint(el,model)
const pending=hit||aiChainBridge("flows.get",[id]).then((res)=>res||{failed:"This chain no longer exists."},(err)=>({failed:aiChainErr(err,"This chain no longer exists.")}))
if(!hit){
aiChainCache.stored.set(cacheKey,pending)
pending.then((res)=>aiChainCache.stored.set(cacheKey,res))
aiChainChanged([id])
}
pending.then(apply)
return el
}
// Called when a chat turn starts with an external agent: remember the chains as they are, so the turn's chain_create /
// chain_update calls (which reach the panel as tool names only) can be told apart afterwards.
function aiChainWatchStart(){
aiChainCache.watch=null
if(typeof aiState==="undefined"||typeof extIsAgentKind!=="function"||!extIsAgentKind(aiState.selectedKind))return
aiChainCache.watch={before:aiChainBridge("flows.list").catch(()=>null)}
}
function aiChainAgentCards(turn,index){
const key=(typeof aiState!=="undefined"?String(aiState.sessionId):"")+":"+index
const holder=document.createElement("div")
holder.className="ai-chain-cards"
const show=(ids)=>{
holder.innerHTML=""
if(!ids||!ids.length){
const el=document.createElement("div")
aiChainPaint(el,{state:"unknown",name:"Chain diagram",note:"This agent created or changed a chain diagram with its tools. Open the Chains page to review it - it is marked AI-made and cannot run before you do."})
holder.appendChild(el)
return
}
ids.slice(0,6).forEach((id)=>holder.appendChild(aiChainStoredCard(id,"",key+":"+id)))
}
const known=aiChainCache.agent.get(key)
if(known&&!known.then){show(known);return [holder]}
const watch=aiChainCache.watch
const isLast=typeof aiState!=="undefined"&&index===aiState.chatHistory.length-1
if(!known&&(!watch||!isLast)){show([]);return [holder]}
const pending=known||Promise.all([watch.before,aiChainBridge("flows.list").catch(()=>null)]).then(([before,after])=>before&&after?aiChainListDiff(before,after):[])
if(!known){
aiChainCache.watch=null
aiChainCache.agent.set(key,pending)
pending.then((ids)=>{aiChainCache.agent.set(key,ids);if(ids.length){aiChainChanged(ids);aiChainSay(ids.length===1?"The agent made a chain diagram - review it before running":"The agent changed "+ids.length+" chain diagrams - review them before running")}})
}
pending.then(show)
return [holder]
}
// The cards that belong under one chat turn (called by aiRenderChat for tool and assistant turns).
function aiChainTurnCards(turn,index){
try{
if(!turn)return []
if(turn.role==="tool"){
const hit=aiChainToolResult(turn)
return hit?[aiChainStoredCard(hit.playbookId,hit.tool,(turn.tool_call_id||"t"+index)+":"+hit.playbookId)]:[]
}
if(turn.role!=="assistant")return []
const cards=aiChainBlocks(turn.content).map(aiChainBlockCard)
return aiChainAgentTouched(turn)?cards.concat(aiChainAgentCards(turn,index)):cards
}catch(err){
console.error("chain card failed",err)
return []
}
}
// /newchain <what it should do>, and a plain "create a chain that ..." request: send the request with the authoring guide.
function aiChainRequest(request,shown,attachments){
return aiChainGuide().then((guide)=>aiSendPrompt(aiChainChatPrompt(guide,request||"See the attached item(s)."),shown,attachments||[])).catch((err)=>{
if(typeof showStatusIsland==="function")showStatusIsland(aiChainErr(err,"The chain guide is not available"),"error")
})
}
if(typeof module!=="undefined"&&module.exports)module.exports={AI_CHAIN_FENCE,AI_CHAIN_FLAG,AI_CHAIN_TOOLS,aiChainEsc,aiChainText,aiChainParse,aiChainFindBlocks,aiChainBlocks,aiChainStripBlocks,aiChainCounts,aiChainNodeDetail,aiChainOutline,aiChainIssueTexts,aiChainCardHtml,aiChainJson,aiChainFixPrompt,aiChainIntent,aiChainChatPrompt,aiChainToolResult,aiChainAgentTouched,aiChainListDiff}
