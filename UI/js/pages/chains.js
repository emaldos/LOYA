// Chains page: list, edit and run Action Chains (internally "playbooks"). The /caller lookup, pre-run checks and the live
// progress card live in components/action-chains.js. Command helpers (cmdsEscapeHtml, cmdsNoiseBadgeHtml, cmdsRunInTerminal,
// cmds-popover styles) come from pages/commands.js, which is always loaded before this file.
let chainsState={items:[],search:"",currentId:null,currentPlaybook:null,stepThrough:false,stepIndex:0,tab:"chains"}
function chainsEscapeHtml(s){
return String(s===undefined||s===null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")
}
// Pure: the chains whose name or /caller contains every word of the query.
function chainsFilterItems(items,query){
const words=String(query||"").trim().toLowerCase().replace(/^\//,"").split(/\s+/).filter(Boolean)
if(!words.length)return (items||[]).slice()
return (items||[]).filter((pb)=>{
const hay=((pb.name||"")+" /"+(pb.caller||"")).toLowerCase()
return words.every((w)=>hay.includes(w.replace(/^\//,"")))
})
}
function chainsPageActive(){
const p=document.querySelector('.page[data-page="chains"]')
return !!(p&&p.classList.contains("active"))
}
// withCaller: also ask for the /caller (suggested from the name until the user edits it). onConfirm(name,caller,showError).
function chainsOpenNamePopover(title,existingName,onConfirm,withCaller){
const pop=document.createElement("div")
pop.className="cmds-popover glass-panel"
const callerField=withCaller?`<div class="cmds-popover-field"><label>Caller</label><div class="cmds-chain-caller"><span class="cmds-chain-caller-slash">/</span><input type="text" id="cmdsPlaybookCallerInput" maxlength="32" spellcheck="false" autocomplete="off"></div><div class="cmds-popover-hint">Type it as /caller in the terminal or the AI input to run this chain. Lowercase letters, digits, - and _.</div></div>`:""
pop.innerHTML=`<div class="cmds-popover-title">${chainsEscapeHtml(title)}</div><div class="cmds-popover-field"><label>Action chain name</label><input type="text" id="cmdsPlaybookNameInput"></div>${callerField}<div class="cmds-popover-error hidden" id="cmdsPlaybookNameErr"></div><div class="cmds-popover-actions"><button type="button" id="cmdsPlaybookNameCancel">Cancel</button><button type="button" class="cmds-popover-confirm" id="cmdsPlaybookNameOk">Save</button></div>`
openModal(pop)
const input=pop.querySelector("#cmdsPlaybookNameInput")
const callerInput=pop.querySelector("#cmdsPlaybookCallerInput")
const err=pop.querySelector("#cmdsPlaybookNameErr")
let callerEdited=false
input.value=existingName||""
input.focus()
if(callerInput&&typeof acSlugifyCaller==="function"){
input.addEventListener("input",()=>{if(!callerEdited)callerInput.value=acSlugifyCaller(input.value)})
callerInput.addEventListener("input",()=>{callerEdited=true;callerInput.value=callerInput.value.toLowerCase().replace(/^\//,"")})
}
pop.querySelector("#cmdsPlaybookNameCancel").addEventListener("click",closeModal)
function confirmName(){
const name=input.value.trim()
if(!name){
err.textContent="Name is required."
err.classList.remove("hidden")
return
}
const caller=callerInput?callerInput.value.trim():undefined
const problem=caller&&typeof acCallerError==="function"?acCallerError(caller,acState.callers,null):""
if(problem){err.textContent=problem;err.classList.remove("hidden");return}
onConfirm(name,caller,(message)=>{err.textContent=message;err.classList.remove("hidden")})
}
pop.querySelector("#cmdsPlaybookNameOk").addEventListener("click",confirmName)
input.addEventListener("keydown",(e)=>{if(e.key==="Enter"){e.preventDefault();confirmName()}})
if(callerInput)callerInput.addEventListener("keydown",(e)=>{if(e.key==="Enter"){e.preventDefault();confirmName()}})
}
function chainsCreatePrompt(){
const ready=typeof acRefreshCallers==="function"?acRefreshCallers(true):Promise.resolve()
ready.then(()=>chainsOpenNamePopover("New Action Chain","",(name,caller,showError)=>{
bridgeCall("playbooks.create",[name,caller===undefined?null:caller]).then((res)=>{
closeModal()
if(typeof acInvalidateCallers==="function")acInvalidateCallers()
chainsRefreshList().then(()=>chainsOpenChain(res.id))
}).catch((err)=>showError(err&&err.message?err.message:"Create failed"))
},true))
}
// The caller editor in the chain detail view: saves on Enter or blur, an empty caller removes it.
function chainsSaveCaller(){
const input=document.getElementById("cmdsChainCallerInput")
const wrap=document.getElementById("cmdsChainCallerWrap")
const errEl=document.getElementById("cmdsChainCallerErr")
const pb=chainsState.currentPlaybook
if(!input||!pb)return Promise.resolve()
const value=input.value.trim().toLowerCase().replace(/^\//,"")
if(value===(pb.caller||"")){wrap.classList.remove("invalid");errEl.textContent="";return Promise.resolve()}
const problem=value&&typeof acCallerError==="function"?acCallerError(value,acState.callers,pb.id):""
if(problem){wrap.classList.add("invalid");errEl.textContent=problem;return Promise.resolve()}
return bridgeCall("playbooks.set_caller",[pb.id,value]).then((res)=>{
pb.caller=res&&res.caller||""
input.value=pb.caller
wrap.classList.remove("invalid")
errEl.textContent=""
if(typeof acInvalidateCallers==="function")acInvalidateCallers()
showStatusIsland(pb.caller?"Caller set - type /"+pb.caller+" in the terminal or the AI input":"Caller removed")
}).catch((err)=>{wrap.classList.add("invalid");errEl.textContent=err&&err.message?err.message:"Could not save the caller"})
}
function chainsShowList(){
chainsState.currentId=null
chainsState.currentPlaybook=null
document.getElementById("cmdsPlaybookDetail").classList.add("hidden")
document.getElementById("cmdsPlaybooksList").classList.remove("hidden")
}
function chainsRenderList(){
const wrap=document.getElementById("cmdsPlaybooksList")
if(!wrap)return
const all=chainsState.items||[]
const items=chainsFilterItems(all,chainsState.search)
const count=document.getElementById("chainsCount")
if(count)count.textContent=all.length?(items.length===all.length?all.length+" chain"+(all.length===1?"":"s"):items.length+" of "+all.length):""
wrap.innerHTML=""
if(!items.length){
const empty=document.createElement("div")
empty.className="cmds-empty-msg"
if(all.length){empty.textContent="No action chains match your search"}
else{
empty.innerHTML='<div>No action chains yet</div><div class="chains-empty-hint">An action chain runs saved commands one after another against the live target.</div><button type="button" class="cmds-playbook-new-btn chains-empty-new"><i class="icon icon-add"></i><span>New Action Chain</span></button>'
empty.querySelector("button").addEventListener("click",chainsCreatePrompt)
}
wrap.appendChild(empty)
return
}
items.forEach((pb)=>{
const card=document.createElement("button")
card.type="button"
card.className="cmds-playbook-card"
card.dataset.chain=String(pb.id)
card.innerHTML=`<span class="cmds-playbook-card-name">${chainsEscapeHtml(pb.name)}</span>${pb.caller?`<span class="cmds-playbook-card-caller">/${chainsEscapeHtml(pb.caller)}</span>`:""}<span class="cmds-playbook-card-count">${pb.step_count} step${pb.step_count===1?"":"s"}</span>`
card.addEventListener("click",()=>chainsOpenChain(pb.id))
// Hook for the diagram editor (chains_flow.js): badges such as "Diagram" / "AI-made".
if(typeof chainsFlowDecorateCard==="function")chainsFlowDecorateCard(card,pb)
wrap.appendChild(card)
})
}
function chainsRefreshList(){
chainsShowList()
return bridgeCall("playbooks.list").then((items)=>{
chainsState.items=items||[]
chainsRenderList()
}).catch((err)=>console.error("playbooks list failed",err))
}
// The Chains page has two sub-tabs: "chains" (the list, the step list and the diagram editor) and "history" (Run History,
// pages/chains_history.js). The page element carries chh-history-on while the history shows; chains-history.css hides the
// chains-only toolbar items and panels then. Pure: which tab a value names.
function chainsTabName(tab){return tab==="history"?"history":"chains"}
function chainsSetTab(tab,opts){
const next=chainsTabName(tab)
const page=document.querySelector('.page[data-page="chains"]')
const host=document.getElementById("chainsHistoryHost")
const prev=chainsState.tab
chainsState.tab=next
if(page)page.classList.toggle("chh-history-on",next==="history")
if(host)host.classList.toggle("hidden",next!=="history")
document.querySelectorAll(".chh-switch-btn").forEach((b)=>{const on=b.dataset.chainsTab===next;b.classList.toggle("active",on);b.setAttribute("aria-selected",on?"true":"false");b.tabIndex=on?0:-1})
if(next==="history"){if(typeof chhShow==="function")chhShow(opts)}
else{
if(typeof chhHide==="function")chhHide()
if(prev==="history"&&chainsState.currentId==null)chainsRefreshList()
}
return next
}
// Entry point for other code: the Run History, optionally filtered to one chain.
function loyaOpenChainHistory(playbookId){
return Promise.resolve(typeof goToPage==="function"?goToPage("chains"):null).then(()=>chainsSetTab("history",playbookId==null?{}:{playbookId:playbookId}))
}
function chainsOpenChain(id){
// A chain that has a diagram opens in the diagram editor (chains_flow.js) instead of the step list.
if(typeof chainsFlowOpenChain==="function"&&chainsFlowOpenChain(id))return Promise.resolve()
// (the diagram editor switches the sub-tab itself: see the chainsFlowHost observer in initChains)
if(chainsState.tab!=="chains")chainsSetTab("chains")
chainsState.currentId=id
chainsState.stepThrough=false
chainsState.stepIndex=0
return bridgeCall("playbooks.get",[id]).then((pb)=>{
if(String(chainsState.currentId)!==String(id))return
chainsState.currentPlaybook=pb
document.getElementById("cmdsPlaybooksList").classList.add("hidden")
document.getElementById("cmdsPlaybookDetail").classList.remove("hidden")
document.getElementById("cmdsPlaybookTitle").textContent=pb.name
const callerInput=document.getElementById("cmdsChainCallerInput")
if(callerInput){callerInput.value=pb.caller||"";document.getElementById("cmdsChainCallerWrap").classList.remove("invalid");document.getElementById("cmdsChainCallerErr").textContent=""}
if(typeof acRefreshCallers==="function")acRefreshCallers(false)
if(typeof acShowRunsFor==="function")acShowRunsFor(pb.id,document.getElementById("cmdsChainRunHost"))
chainsRenderSteps()
}).catch((err)=>{showToast(err&&err.message?err.message:"Failed to open the action chain","error");chainsRefreshList()})
}
// Reloads the open chain's steps without leaving Step-Through (used after a reorder or a removed step).
function chainsReloadCurrent(){
const id=chainsState.currentId
if(id==null)return Promise.resolve()
return bridgeCall("playbooks.get",[id]).then((pb)=>{
if(String(chainsState.currentId)!==String(id))return
chainsState.currentPlaybook=pb
chainsState.stepIndex=Math.min(chainsState.stepIndex,pb.steps.length)
document.getElementById("cmdsPlaybookTitle").textContent=pb.name
chainsRenderSteps()
}).catch(()=>{if(String(chainsState.currentId)===String(id))chainsRefreshList()})
}
// Entry point for other pages: open the Chains page, optionally on one chain.
function loyaOpenChain(id){
return Promise.resolve(goToPage("chains")).then(()=>id==null?chainsRefreshList():chainsOpenChain(id))
}
function chainsAdvanceIfActive(idx){
if(!chainsState.stepThrough||idx!==chainsState.stepIndex)return
chainsState.stepIndex=Math.min(chainsState.stepIndex+1,chainsState.currentPlaybook.steps.length)
chainsRenderSteps()
}
function chainsMoveStep(stepId,direction){
bridgeCall("playbooks.move_step",[stepId,direction]).then(()=>chainsReloadCurrent()).catch(()=>{})
}
function chainsRemoveStep(stepId){
appConfirm("Remove this step from the action chain?",{okLabel:"Remove",danger:true}).then((yes)=>{
if(!yes)return
bridgeCall("playbooks.remove_step",[stepId]).then(()=>chainsReloadCurrent()).catch(()=>{})
})
}
// Other views (a diagram editor) listen for this to redraw: detail {id, playbook}, fired whenever the open chain's steps render.
function chainsNotifyRendered(){
const pb=chainsState.currentPlaybook
if(pb)document.dispatchEvent(new CustomEvent("loya:chain-rendered",{detail:{id:pb.id,playbook:pb}}))
}
function chainsRenderSteps(){
const pb=chainsState.currentPlaybook
const wrap=document.getElementById("cmdsPlaybookSteps")
wrap.innerHTML=""
document.getElementById("cmdsPlaybookStepThroughBtn").textContent=chainsState.stepThrough?"Exit Step-Through":"Start Step-Through"
if(!pb.steps.length){
const empty=document.createElement("div")
empty.className="cmds-empty-msg"
empty.textContent="No steps yet. Add a command to get started."
wrap.appendChild(empty)
chainsNotifyRendered()
return
}
pb.steps.forEach((step,idx)=>{
const row=document.createElement("div")
row.className="cmds-playbook-step"
if(chainsState.stepThrough&&idx===chainsState.stepIndex)row.classList.add("active")
else if(chainsState.stepThrough&&idx<chainsState.stepIndex)row.classList.add("done")
const cmd=step.command
if(!cmd){
row.innerHTML=`<div class="cmds-playbook-step-num">${idx+1}</div><div class="cmds-playbook-step-body"><em>Command no longer exists</em></div><div class="cmds-playbook-step-actions"><button type="button" class="cmds-playbook-step-remove" title="Remove step"><i class="icon icon-close"></i></button></div>`
row.querySelector(".cmds-playbook-step-remove").addEventListener("click",()=>chainsRemoveStep(step.step_id))
}else{
row.innerHTML=`<div class="cmds-playbook-step-num">${idx+1}</div><div class="cmds-playbook-step-body"><div class="cmds-playbook-step-head"><span class="cmds-playbook-step-title">${chainsEscapeHtml(cmd.title)}</span>${notesCmdTypeBadgeHtml(cmd.command_type)}${cmdsNoiseBadgeHtml(cmd.noise_level)}</div><pre class="cmds-info-code">${chainsEscapeHtml(cmd.command)}</pre></div><div class="cmds-playbook-step-actions"><button type="button" class="cmds-playbook-step-copy" title="Copy"><i class="icon icon-copy"></i></button><button type="button" class="cmds-playbook-step-run" title="Run in Terminal"><i class="icon icon-command-line"></i></button><button type="button" class="cmds-playbook-step-up" title="Move up"${idx===0?" disabled":""}><i class="icon icon-arrow-up"></i></button><button type="button" class="cmds-playbook-step-down" title="Move down"${idx===pb.steps.length-1?" disabled":""}><i class="icon icon-arrow-down"></i></button><button type="button" class="cmds-playbook-step-remove" title="Remove step"><i class="icon icon-close"></i></button></div>`
row.querySelector(".cmds-playbook-step-copy").addEventListener("click",()=>{
if(navigator.clipboard)navigator.clipboard.writeText(cmd.command||"").catch(()=>{})
chainsAdvanceIfActive(idx)
})
row.querySelector(".cmds-playbook-step-run").addEventListener("click",()=>{
cmdsRunInTerminal(cmd)
chainsAdvanceIfActive(idx)
})
row.querySelector(".cmds-playbook-step-up").addEventListener("click",()=>chainsMoveStep(step.step_id,-1))
row.querySelector(".cmds-playbook-step-down").addEventListener("click",()=>chainsMoveStep(step.step_id,1))
row.querySelector(".cmds-playbook-step-remove").addEventListener("click",()=>chainsRemoveStep(step.step_id))
}
wrap.appendChild(row)
})
chainsNotifyRendered()
}
function chainsRunAll(){
const book=chainsState.currentPlaybook
if(!book){showToast("Open an action chain first","error");return}
if(!termState.enabled){showToast("Enable the terminal in Settings first","error");return}
// Live-target checks, the run policy and the progress card all live in action-chains.js.
if(typeof acRunChain==="function"){acRunChain(book.id,{name:book.name,caller:book.caller,source:"chains"});return}
termRunPlaybook(book.id,book.name)
}
// The step picker loads the command list itself: the Commands page may never have been opened.
function chainsOpenAddStepPopover(){
const pop=document.createElement("div")
pop.className="cmds-popover glass-panel"
pop.innerHTML='<div class="cmds-popover-title">Add Step</div><input type="text" class="cmds-popover-search" id="cmdsAddStepSearch" placeholder="Search commands..."><div class="cmds-popover-list" id="cmdsAddStepList"><div class="cmds-empty-msg">Loading commands...</div></div>'
openModal(pop)
const list=pop.querySelector("#cmdsAddStepList")
const search=pop.querySelector("#cmdsAddStepSearch")
let rows=[]
function render(q){
list.innerHTML=""
const qq=(q||"").toLowerCase()
const candidates=rows.filter((r)=>!qq||[r.title,r.category,r.command].join(" ").toLowerCase().includes(qq)).slice(0,50)
if(!candidates.length){
const empty=document.createElement("div")
empty.className="cmds-empty-msg"
empty.textContent=rows.length?"No commands match":"No saved commands yet - add some on the Commands page"
list.appendChild(empty)
return
}
candidates.forEach((row)=>{
const item=document.createElement("button")
item.type="button"
item.className="cmds-popover-list-item"
item.textContent=row.title+" - "+(row.command||"").split("\n")[0].slice(0,50)
item.addEventListener("click",()=>{
bridgeCall("playbooks.add_step",[chainsState.currentId,row.id,row.src]).then(()=>{
closeModal()
chainsReloadCurrent()
}).catch((err)=>showToast(err&&err.message?err.message:"Add step failed","error"))
})
list.appendChild(item)
})
}
search.focus()
search.addEventListener("input",(e)=>render(e.target.value))
bridgeCall("commands.list").then((r)=>{rows=r||[];render(search.value)}).catch((err)=>{list.innerHTML="";showToast(err&&err.message?err.message:"Could not load commands","error")})
}
function chainsDeleteCurrent(){
appConfirm("Delete this action chain? This cannot be undone.",{okLabel:"Delete",danger:true}).then((yes)=>{
if(!yes)return
bridgeCall("playbooks.delete",[chainsState.currentId]).then(()=>{
if(typeof acInvalidateCallers==="function")acInvalidateCallers()
chainsRefreshList()
}).catch((err)=>showToast(err&&err.message?err.message:"Delete failed","error"))
})
}
function initChains(){
return fetch("../pages/chains.html").then((r)=>r.text()).then((html)=>{
document.querySelector('.page[data-page="chains"]').innerHTML=html
const search=document.getElementById("chainsSearchInput")
search.addEventListener("input",()=>{
chainsState.search=search.value
if(chainsState.currentId!=null)chainsShowList()
chainsRenderList()
})
search.addEventListener("keydown",(e)=>{if(e.key==="Escape"&&search.value){e.preventDefault();e.stopPropagation();search.value="";chainsState.search="";chainsRenderList()}})
document.getElementById("chainsNewBtn").addEventListener("click",chainsCreatePrompt)
document.querySelectorAll(".chh-switch-btn").forEach((b)=>{
b.addEventListener("click",()=>chainsSetTab(b.dataset.chainsTab))
b.addEventListener("keydown",(e)=>{if(e.key==="ArrowRight"||e.key==="ArrowLeft"){e.preventDefault();const t=chainsSetTab(chainsState.tab==="history"?"chains":"history");const on=document.querySelector('.chh-switch-btn[data-chains-tab="'+t+'"]');if(on)on.focus()}})
})
const exportBtn=document.getElementById("chainsExportBtn")
if(exportBtn)exportBtn.addEventListener("click",()=>{if(typeof chhExportChainsPrompt==="function")chhExportChainsPrompt()})
const importBtn=document.getElementById("chainsImportBundleBtn")
if(importBtn)importBtn.addEventListener("click",()=>{if(typeof chhImport==="function")chhImport()})
const detailHistory=document.getElementById("chainsDetailHistoryBtn")
if(detailHistory)detailHistory.addEventListener("click",()=>{const id=chainsState.currentId;if(id!=null)chainsSetTab("history",{playbookId:id})})
// The diagram editor (chains_flow.js) can open from anywhere (loyaOpenChainDiagram): it always belongs to the Chains tab.
const flowHost=document.getElementById("chainsFlowHost")
if(flowHost&&typeof MutationObserver==="function")new MutationObserver(()=>{if(!flowHost.classList.contains("hidden")&&chainsState.tab!=="chains")chainsSetTab("chains")}).observe(flowHost,{attributes:true,attributeFilter:["class"]})
document.getElementById("cmdsPlaybookRunAllBtn").addEventListener("click",chainsRunAll)
document.getElementById("cmdsPlaybookBackBtn").addEventListener("click",()=>chainsRefreshList())
document.getElementById("cmdsPlaybookAddStepBtn").addEventListener("click",chainsOpenAddStepPopover)
const chainCaller=document.getElementById("cmdsChainCallerInput")
chainCaller.addEventListener("keydown",(e)=>{if(e.key==="Enter"){e.preventDefault();chainsSaveCaller()}else if(e.key==="Escape"){e.preventDefault();chainCaller.value=(chainsState.currentPlaybook||{}).caller||"";chainsSaveCaller()}})
chainCaller.addEventListener("blur",chainsSaveCaller)
chainCaller.addEventListener("input",()=>{const v=chainCaller.value.toLowerCase().replace(/^\//,"");if(v!==chainCaller.value)chainCaller.value=v})
document.getElementById("cmdsPlaybookDeleteBtn").addEventListener("click",chainsDeleteCurrent)
document.getElementById("cmdsPlaybookStepThroughBtn").addEventListener("click",()=>{
chainsState.stepThrough=!chainsState.stepThrough
chainsState.stepIndex=0
chainsRenderSteps()
})
// Chains can change elsewhere (the AI, a deleted command), so reload whenever the page comes back.
document.addEventListener("loya:page-shown",(e)=>{
if(!e.detail||e.detail.page!=="chains"||e.detail.first)return
if(chainsState.tab==="history")return
if(chainsState.currentId!=null)chainsReloadCurrent()
else chainsRefreshList()
})
return chainsRefreshList()
}).catch((err)=>console.error("chains init failed",err))
}
if(typeof module!=="undefined"&&module.exports)module.exports={chainsFilterItems,chainsEscapeHtml,chainsTabName}
