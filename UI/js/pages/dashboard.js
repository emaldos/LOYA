let dashState={cards:[],catalog:{widgets:[],sizes:[]},stats:null,editMode:false,dragId:null,timer:null,loading:false,pending:null,again:false}
const DASH_REFRESH_MS=20000
const DASH_SIZE_LABELS={"0.25x1":"Small","0.25x1.5":"Tile","1x1":"Medium","1x1.5":"Medium tall","1x2":"Tall","2x0.5":"Wide strip","2x1":"Wide","2x2":"Large","full":"Full"}
function dashCardIndex(id){
return dashState.cards.findIndex((c)=>c.id===id)
}
function dashPageActive(){
const p=document.querySelector('.page[data-page="dashboard"]')
return !!(p&&p.classList.contains("active"))&&!document.hidden
}
function persistDashLayout(){
const cards=dashState.cards.map((c)=>({id:c.id,widget:c.widget,size:c.size}))
bridgeCall("dashboard.save_layout",[cards]).catch((err)=>{console.error("dashboard save failed",err);showToast("Could not save the dashboard layout","error")})
}
function closeDashPopover(){
const existing=document.getElementById("dashPopover")
if(existing)existing.remove()
document.removeEventListener("mousedown",dashPopoverOutsideClick,true)
document.removeEventListener("keydown",dashPopoverKeydown,true)
const held=document.querySelector("[data-held-title]")
if(held){held.title=held.dataset.heldTitle;delete held.dataset.heldTitle}
}
function dashPopoverOutsideClick(e){
const pop=document.getElementById("dashPopover")
if(pop&&!pop.contains(e.target))closeDashPopover()
}
function dashPopoverKeydown(e){
if(e.key!=="Escape")return
const pop=document.getElementById("dashPopover")
if(!pop)return
e.stopPropagation()
const id=pop.dataset.cardId
closeDashPopover()
const card=document.querySelector(`.dash-card[data-id="${CSS.escape(id||"")}"]`)
if(card)card.focus()
}
function dashWidgetButton(w,active){
const item=document.createElement("button")
item.type="button"
item.className="dash-popover-item"+(active?" active":"")
item.innerHTML=`<i class="icon icon-${dashEsc(w.icon)}" aria-hidden="true"></i><span>${dashEsc(w.label)}</span>`
return item
}
function openDashPopover(cardId,anchorEl){
closeDashPopover()
const card=dashState.cards[dashCardIndex(cardId)]
if(!card)return
const rect=anchorEl.getBoundingClientRect()
const pop=document.createElement("div")
pop.id="dashPopover"
pop.dataset.cardId=cardId
pop.className="dash-popover glass-panel"
pop.setAttribute("role","dialog")
pop.setAttribute("aria-label","Card options")
pop.style.visibility="hidden"
pop.style.left=Math.round(Math.max(8,Math.min(rect.left,window.innerWidth-252)))+"px"
pop.style.top="0px"
const showTitle=document.createElement("div")
showTitle.className="dash-popover-title"
showTitle.textContent="Show"
pop.appendChild(showTitle)
const list=document.createElement("div")
list.className="dash-popover-list"
dashState.catalog.widgets.forEach((w)=>{
const item=dashWidgetButton(w,w.id===card.widget)
item.addEventListener("click",()=>{card.widget=w.id;renderDashGrid();persistDashLayout();closeDashPopover()})
list.appendChild(item)
})
pop.appendChild(list)
const sizeTitle=document.createElement("div")
sizeTitle.className="dash-popover-title"
sizeTitle.textContent="Size"
pop.appendChild(sizeTitle)
pop.appendChild(renderSizePicker(dashState.catalog.sizes,card.size,(size)=>{card.size=size;renderDashGrid();persistDashLayout();closeDashPopover();dashFocusCard(cardId)},DASH_SIZE_LABELS))
const removeBtn=document.createElement("button")
removeBtn.type="button"
removeBtn.className="dash-popover-remove"
removeBtn.textContent="Remove card"
removeBtn.addEventListener("click",()=>{
dashState.cards.splice(dashCardIndex(cardId),1)
renderDashGrid()
persistDashLayout()
closeDashPopover()
})
pop.appendChild(removeBtn)
document.body.appendChild(pop)
const popH=pop.offsetHeight
const spaceBelow=window.innerHeight-rect.bottom-6
const spaceAbove=rect.top-6
let top=spaceBelow>=popH||spaceBelow>=spaceAbove?Math.round(rect.bottom+6):Math.round(rect.top-popH-6)
top=Math.max(8,Math.min(top,window.innerHeight-popH-8))
pop.style.top=top+"px"
pop.style.visibility="visible"
const first=pop.querySelector(".dash-popover-item.active")||pop.querySelector("button")
if(first)first.focus()
setTimeout(()=>{document.addEventListener("mousedown",dashPopoverOutsideClick,true);document.addEventListener("keydown",dashPopoverKeydown,true)},0)
}
function dashFocusCard(id){
const el=document.querySelector(`#dashGrid .dash-card[data-id="${CSS.escape(id)}"]`)
if(el)el.focus()
}
function dashMoveCard(id,delta){
const from=dashCardIndex(id)
const to=from+delta
if(from<0||to<0||to>=dashState.cards.length)return
const moved=dashState.cards.splice(from,1)[0]
dashState.cards.splice(to,0,moved)
renderDashGrid()
persistDashLayout()
dashFocusCard(id)
}
function wireDashCardEvents(){
const grid=document.getElementById("dashGrid")
if(!dashState.editMode)return
grid.querySelectorAll(".dash-card-menu").forEach((btn)=>{
btn.addEventListener("click",(e)=>{e.stopPropagation();openDashPopover(btn.dataset.id,btn)})
})
grid.querySelectorAll(".dash-card").forEach((el)=>{
el.addEventListener("dragstart",()=>{dashState.dragId=el.dataset.id;el.classList.add("dragging")})
el.addEventListener("dragend",()=>{el.classList.remove("dragging");dashState.dragId=null})
el.addEventListener("dragover",(e)=>{if(dashState.editMode)e.preventDefault()})
el.addEventListener("drop",(e)=>{
e.preventDefault()
if(!dashState.dragId||dashState.dragId===el.dataset.id)return
const from=dashCardIndex(dashState.dragId)
const to=dashCardIndex(el.dataset.id)
if(from<0||to<0)return
const moved=dashState.cards.splice(from,1)[0]
dashState.cards.splice(to,0,moved)
renderDashGrid()
persistDashLayout()
})
// Keyboard reordering: arrows move the focused card, Enter/Space opens its options.
el.addEventListener("keydown",(e)=>{
if(e.target!==el)return
if(e.key==="ArrowLeft"||e.key==="ArrowUp"){e.preventDefault();dashMoveCard(el.dataset.id,-1)}
else if(e.key==="ArrowRight"||e.key==="ArrowDown"){e.preventDefault();dashMoveCard(el.dataset.id,1)}
else if(e.key==="Enter"||e.key===" "){e.preventDefault();const b=el.querySelector(".dash-card-menu");if(b)openDashPopover(el.dataset.id,b)}
else if(e.key==="Delete"){e.preventDefault();dashState.cards.splice(dashCardIndex(el.dataset.id),1);renderDashGrid();persistDashLayout()}
})
})
}
function addDashCard(){
const pop=document.createElement("div")
pop.className="dash-popover glass-panel dash-add-modal"
pop.innerHTML='<div class="dash-popover-title">Add Card</div><div class="dash-add-groups"></div>'
const wrap=pop.querySelector(".dash-add-groups")
const groups={}
dashState.catalog.widgets.forEach((w)=>{(groups[w.group||"Other"]=groups[w.group||"Other"]||[]).push(w)})
Object.keys(groups).forEach((g)=>{
const sec=document.createElement("div")
sec.className="dash-add-group"
sec.innerHTML=`<div class="dash-add-group-title">${dashEsc(g)}</div>`
groups[g].forEach((w)=>{
const used=dashState.cards.some((c)=>c.widget===w.id)
const item=document.createElement("button")
item.type="button"
item.className="dash-add-item"
item.innerHTML=`<i class="icon icon-${dashEsc(w.icon)}" aria-hidden="true"></i><span class="dash-add-text"><span class="dash-add-label">${dashEsc(w.label)}${used?' <span class="dash-add-used">on dashboard</span>':""}</span><span class="dash-add-desc">${dashEsc(w.description||"")}</span></span>`
item.addEventListener("click",()=>{
const id=w.id+"-"+Math.random().toString(36).slice(2,8)
dashState.cards.push({id:id,widget:w.id,size:w.default_size||"1x1"})
renderDashGrid()
persistDashLayout()
closeModal()
dashFocusCard(id)
})
sec.appendChild(item)
})
wrap.appendChild(sec)
})
openModal(pop)
const first=pop.querySelector(".dash-add-item")
if(first)first.focus()
}
function dashSyncHeader(){
// The header quick buttons duplicate the Quick Actions card; hide them while that card is on the dashboard.
const hasCard=dashState.cards.some((c)=>c.widget==="quick_actions")
const qa=document.querySelector(".dash-quick-actions")
if(qa)qa.classList.toggle("hidden",hasCard)
}
function renderDashGrid(){
const grid=document.getElementById("dashGrid")
if(!grid)return
// Keep keyboard focus across re-renders (timer refreshes rebuild every card).
const active=document.activeElement
let focusSel=null
if(active&&grid.contains(active)){
const card=active.closest(".dash-card")
if(card){
const act=active.dataset&&active.dataset.act
focusSel={card:card.dataset.id,act:act||null,idx:active.dataset?active.dataset.idx:null,self:active===card}
}
}
grid.innerHTML=""
const ctx={catalog:dashState.catalog,stats:dashState.stats,editMode:dashState.editMode}
dashState.cards.forEach((card)=>grid.appendChild(renderCard(card,ctx)))
if(!dashState.cards.length&&!dashState.editMode){
const empty=document.createElement("div")
empty.className="dash-grid-empty glass-panel"
empty.innerHTML='<div>Your dashboard is empty.</div><button type="button" class="dash-empty-btn" data-act="edit-layout"><span>Add cards</span></button><button type="button" class="dash-empty-btn" data-act="reset-default"><span>Use the default layout</span></button>'
grid.appendChild(empty)
}
if(dashState.editMode){
const addTile=document.createElement("button")
addTile.type="button"
addTile.className="dash-add-tile"
addTile.setAttribute("aria-label","Add card")
addTile.innerHTML=`<i class="icon icon-add" aria-hidden="true"></i><span>Add card</span>`
addTile.addEventListener("click",addDashCard)
grid.appendChild(addTile)
}
wireDashCardEvents()
dashSyncHeader()
if(focusSel){
const card=grid.querySelector(`.dash-card[data-id="${CSS.escape(focusSel.card)}"]`)
let target=null
if(card&&focusSel.self)target=card
else if(card&&focusSel.act){
const cands=Array.from(card.querySelectorAll(`[data-act="${CSS.escape(focusSel.act)}"]`))
target=cands.find((b)=>(b.dataset.idx||null)===(focusSel.idx||null))||cands[0]
}
if(target)target.focus()
}
}
function toggleDashEditMode(){
dashState.editMode=!dashState.editMode
const btn=document.getElementById("dashEditBtn")
btn.classList.toggle("active",dashState.editMode)
btn.setAttribute("aria-pressed",dashState.editMode?"true":"false")
btn.querySelector("span").textContent=dashState.editMode?"Done":"Edit Layout"
document.getElementById("dashGrid").classList.toggle("editing",dashState.editMode)
closeDashPopover()
renderDashGrid()
if(dashState.editMode)showStatusIsland("Drag cards, or focus one and use the arrow keys to move it")
}
function dashEscapeHtml(s){return dashEsc(s)}
function dashQuickGoto(page,after){
return goToPage(page).then(()=>{if(typeof after==="function")after()})
}
function dashErr(err,fallback){return err&&err.message?err.message:fallback}
function dashOpenTerminal(){
if(typeof termState==="undefined"||!termState.enabled){showToast("Enable the Terminal extension in Settings first","error");return}
if(!termState.open)termOpenPanel()
else{const i=document.getElementById("terminalInput");if(i)i.focus()}
}
function dashQuickAction(q){
if(q==="note")return dashQuickGoto("notes",notesOpenNewNote)
if(q==="command")return dashQuickGoto("commands",()=>cmdsOpenForm(null))
if(q==="target")return dashQuickGoto("targets",()=>tgtOpenTargetForm(null))
if(q==="terminal")return dashOpenTerminal()
if(q==="playbooks")return dashQuickGoto("chains")
if(q==="search"&&typeof paletteToggle==="function")return paletteToggle()
}
function wireDashQuickActions(){
document.getElementById("dashQuickNote").addEventListener("click",()=>dashQuickAction("note"))
document.getElementById("dashQuickCommand").addEventListener("click",()=>dashQuickAction("command"))
document.getElementById("dashQuickTarget").addEventListener("click",()=>dashQuickAction("target"))
}
function dashHandleKeydown(e){
if(!e.altKey)return
if(!document.querySelector('.page[data-page="dashboard"]').classList.contains("active"))return
const active=document.activeElement
const tag=active?active.tagName:""
if(tag==="INPUT"||tag==="TEXTAREA"||(active&&active.isContentEditable))return
const key=e.key.toLowerCase()
if(key==="n"){e.preventDefault();dashQuickAction("note")}
else if(key==="c"){e.preventDefault();dashQuickAction("command")}
else if(key==="t"){e.preventDefault();dashQuickAction("target")}
}
function dashCopy(text,msg){
if(!text){showToast("Nothing to copy","error");return}
if(navigator.clipboard)navigator.clipboard.writeText(text).then(()=>showToast(msg||"Copied")).catch(()=>showToast("Copy failed","error"))
}
function dashLiveTarget(){return ((dashState.stats||{}).live_target||{}).target||null}
function dashOpenLiveTargetForm(findKey){
const live=dashLiveTarget()
return dashQuickGoto("targets",()=>{
const t=live&&(tgtState.targets||[]).find((x)=>x.id===live.id)
if(!t){tgtSwitchTab("targets");return}
tgtOpenTargetForm(t)
if(findKey){
const f=document.getElementById("tgtFieldFind")
if(f){f.value=findKey;f.dispatchEvent(new Event("input"))}
const inp=document.querySelector(`.tgt-value-input[data-key="${CSS.escape(findKey)}"]`)
if(inp)inp.focus()
}
})
}
function dashCmdItem(el){
const list=(dashState.stats||{})[el.dataset.list]||[]
return list[parseInt(el.dataset.idx,10)]||null
}
function dashCmdRow(c){return {id:c.id,src:c.src,noise_level:c.noise_level,title:c.title,command:c.command}}
function dashRunCommand(c,stage){
if(typeof termState==="undefined"||!termState.enabled){showToast("Enable the Terminal extension in Settings first","error");return}
const text=c.resolved||c.command
if(stage){termStageCommand(text).catch((err)=>showToast(dashErr(err,"Terminal unavailable"),"error"));return}
termDispatchRun(text,{noise_level:c.noise_level,confirmMode:termState.commandRunConfirm,source:"dashboard"}).then((id)=>{
if(!id)return
bridgeCall("search.live_target").then((res)=>bridgeCall("commands.record_run",[c.id,c.src,text,(res&&res.map)||{}])).catch(()=>{}).then(()=>dashRefresh(true))
}).catch((err)=>showToast(dashErr(err,"Run failed"),"error"))
}
function dashOpenCommand(id,src){
const page=src==="CommandsNotes"?"commands":"commands"
return dashQuickGoto(page,()=>{
const row=(cmdsState.rows||[]).find((r)=>String(r.id)===String(id)&&r.src===src)
if(row)cmdsOpenInfoPanel(row)
else showToast("That command no longer exists","error")
})
}
function dashOpenJob(job){
if(!job)return
if(typeof termFindTab==="function"&&termFindTab(job.session_id)&&typeof termJumpToJob==="function"){
if(!termState.open)termOpenPanel()
termJumpToJob(job.session_id,job.job_key)
return
}
if(typeof termShowJobOutput==="function")termShowJobOutput(job)
}
function dashFeedOpen(el){
const kind=el.dataset.kind,id=el.dataset.id,src=el.dataset.src
if(kind==="note")return dashQuickGoto("notes",()=>notesOpen(parseInt(id,10)))
if(kind==="command")return dashOpenCommand(parseInt(id,10),src)
if(kind==="target")return dashQuickGoto("targets",()=>{const t=(tgtState.targets||[]).find((x)=>x.id===id);if(t)tgtOpenTargetForm(t)})
if(kind==="job"){
const jobs=((dashState.stats||{}).recent_jobs||{}).items||[]
const job=jobs.find((j)=>j.job_key===id)
if(job)return dashOpenJob(job)
bridgeCall("terminal.job_get",[id]).then((j)=>{if(j)dashOpenJob(j);else showToast("That job is no longer recorded","error")}).catch(()=>showToast("That job is no longer recorded","error"))
}
}
// Live-target picker: a search box over the profile's targets (name, IP, domain); arrows + Enter pick, Esc closes.
function dashOpenLivePicker(anchorEl){
closeDashPopover()
// GTK keeps the native tooltip on screen after the click, over the search box: no title while the picker is open.
if(anchorEl.title){anchorEl.dataset.heldTitle=anchorEl.title;anchorEl.removeAttribute("title")}
const data=(dashState.stats||{}).live_target||{}
const all=data.targets||[]
const rect=anchorEl.getBoundingClientRect()
const pop=document.createElement("div")
pop.id="dashPopover"
pop.className="dash-popover dash-live-picker glass-panel"
pop.setAttribute("role","dialog")
pop.setAttribute("aria-label","Choose the live target")
pop.style.visibility="hidden"
pop.style.top="0px"
pop.innerHTML=`<div class="dash-live-search">${typeof dashIcon==="function"?dashIcon("search"):""}<input type="text" id="dashLiveSearch" placeholder="Search targets by name, IP or domain..." autocomplete="off" spellcheck="false" aria-label="Search targets"></div><div class="dash-live-results" role="listbox" id="dashLiveResults"></div>`
document.body.appendChild(pop)
const input=pop.querySelector("#dashLiveSearch"),box=pop.querySelector("#dashLiveResults")
let rows=[],active=0
const render=()=>{
const q=input.value
rows=dashFilterTargets(all,q)
const live=all.some((t)=>t.live)
const none=live&&!q.trim()?[{id:"",name:"No live target",hint:"Stop filling {PLACEHOLDERS} from a target"}]:[]
rows=none.concat(rows)
if(active>=rows.length)active=Math.max(0,rows.length-1)
box.innerHTML=rows.length?rows.map((t,i)=>`<button type="button" class="dash-live-row${i===active?" active":""}${t.live?" is-live":""}" role="option" aria-selected="${i===active}" data-i="${i}"><span class="dash-live-row-name">${dashEsc(t.name)}${t.live?' <span class="dash-live-row-badge">live</span>':""}</span>${t.hint?`<span class="dash-live-row-hint mono">${dashEsc(t.hint)}</span>`:""}</button>`).join(""):`<div class="dash-live-empty">No target matches "${dashEsc(q)}"</div>`
const a=box.querySelector(".dash-live-row.active");if(a)a.scrollIntoView({block:"nearest"})
}
const pick=(i)=>{const t=rows[i];if(!t)return;closeDashPopover();if(t.live)return;dashSwitchLive(t.id)}
input.addEventListener("input",()=>{active=0;render()})
input.addEventListener("keydown",(e)=>{
if(e.key==="ArrowDown"){e.preventDefault();if(rows.length){active=(active+1)%rows.length;render()}}
else if(e.key==="ArrowUp"){e.preventDefault();if(rows.length){active=(active-1+rows.length)%rows.length;render()}}
else if(e.key==="Enter"){e.preventDefault();pick(active)}
})
box.addEventListener("mousedown",(e)=>{const b=e.target.closest(".dash-live-row");if(b){e.preventDefault();pick(Number(b.dataset.i))}})
active=Math.max(0,all.findIndex((t)=>t.live)+(all.some((t)=>t.live)?1:0))
render()
const w=Math.max(rect.width,320)
pop.style.width=w+"px"
pop.style.left=Math.round(Math.max(8,Math.min(rect.left,window.innerWidth-w-8)))+"px"
const popH=pop.offsetHeight,spaceBelow=window.innerHeight-rect.bottom-6,spaceAbove=rect.top-6
let top=spaceBelow>=popH||spaceBelow>=spaceAbove?Math.round(rect.bottom+6):Math.round(rect.top-popH-6)
pop.style.top=Math.max(8,Math.min(top,window.innerHeight-popH-8))+"px"
pop.style.visibility=""
document.addEventListener("mousedown",dashPopoverOutsideClick,true)
document.addEventListener("keydown",dashPopoverKeydown,true)
input.focus()
}
function dashSwitchLive(tid){
const live=dashLiveTarget()
let call
if(tid)call=bridgeCall("targets.set_live_target",[tid])
else if(live)call=bridgeCall("targets.set_live_target",[live.id])
else return
call.then(()=>{
document.dispatchEvent(new CustomEvent("loya:live-target-changed",{detail:{id:tid||""}}))
showToast(tid?"Live target switched":"No target in use now")
return dashRefresh(true)
}).catch((err)=>{showToast(dashErr(err,"Could not change the live target"),"error");dashRefresh(true)})
}
function dashHandleGridClick(e){
const el=e.target.closest("[data-act]")
if(!el||!document.getElementById("dashGrid").contains(el)||dashState.editMode&&el.closest(".dash-card-body"))return
const act=el.dataset.act
if(act==="live-switch")return
e.preventDefault()
if(act==="live-pick")return dashOpenLivePicker(el)
if(act==="goto"){
const page=el.dataset.page
if(page==="terminal")return dashOpenTerminal()
if(page==="targets"&&el.dataset.edit==="live")return dashOpenLiveTargetForm()
return dashQuickGoto(page,()=>{if(page==="targets"&&typeof tgtSwitchTab==="function")tgtSwitchTab(el.dataset.tab||"targets")})
}
if(act==="quick")return dashQuickAction(el.dataset.q)
if(act==="report-open"||act==="report-new"){
if(typeof Reporting==="undefined")return showToast("Reporting is not available","error")
const p=act==="report-new"?Reporting.newReport():Reporting.open(parseInt(el.dataset.id,10))
return Promise.resolve(p).catch((err)=>showToast(dashErr(err,"Could not open the report"),"error"))
}
if(act==="retry")return dashRefresh(true)
if(act==="edit-layout"){if(!dashState.editMode)toggleDashEditMode();return addDashCard()}
if(act==="reset-default")return dashApplyPreset("default")
if(act==="feed-open")return dashFeedOpen(el)
if(act==="note-open")return dashQuickGoto("notes",()=>notesOpen(parseInt(el.dataset.id,10)))
if(act==="settings-tab")return dashQuickGoto("settings",()=>{if(typeof setSwitchTab==="function")setSwitchTab(el.dataset.tab)})
if(act==="copy-value"){
const t=dashLiveTarget()
const v=t&&t.values[parseInt(el.dataset.idx,10)]
if(v)dashCopy(v.value,"Copied {"+v.key+"}")
return
}
if(act==="target-edit")return dashOpenLiveTargetForm()
if(act==="missing-key"){
const mp=(dashState.stats||{}).missing_placeholders||{}
if(mp.live)return dashOpenLiveTargetForm(el.dataset.key)
return dashQuickGoto("targets",()=>tgtSwitchTab("targets"))
}
if(act==="job-open"||act==="job-rerun"){
const job=(((dashState.stats||{}).recent_jobs||{}).items||[])[parseInt(el.dataset.idx,10)]
if(!job)return
if(act==="job-open")return dashOpenJob(job)
if(typeof termState==="undefined"||!termState.enabled){showToast("Enable the Terminal extension in Settings first","error");return}
termDispatchRun(job.command||"",{confirmMode:termState.commandRunConfirm,source:"terminal"}).then(()=>setTimeout(dashRefresh,800)).catch((err)=>showToast(dashErr(err,"Run failed"),"error"))
return
}
if(act==="cmd-open"||act==="cmd-run"||act==="cmd-insert"||act==="cmd-copy"){
const c=dashCmdItem(el)
if(!c)return
if(act==="cmd-open")return dashOpenCommand(c.id,c.src)
if(act==="cmd-copy")return dashCopy(c.resolved||c.command,"Copied command")
return dashRunCommand(c,act==="cmd-insert")
}
}
function dashHandleGridChange(e){
const el=e.target.closest('[data-act="live-switch"]')
if(el)dashSwitchLive(el.value)
}
function dashPromptLayoutName(){
return new Promise((resolve)=>{
const pop=document.createElement("div")
pop.className="dash-popover glass-panel dash-name-popover"
pop.innerHTML=`<div class="dash-popover-title">Save Current Dashboard</div><input type="text" id="dashNameInput" class="dash-name-input" placeholder="Layout name" aria-label="Layout name"><div class="dash-popover-error hidden" id="dashNameErr">Name is required.</div><div class="dash-popover-actions"><button type="button" id="dashNameCancel">Cancel</button><button type="button" class="dash-popover-confirm" id="dashNameOk">Save</button></div>`
openModal(pop)
const input=pop.querySelector("#dashNameInput")
input.focus()
function finish(val){closeModal();resolve(val)}
pop.querySelector("#dashNameCancel").addEventListener("click",()=>finish(null))
function submitName(){
const v=input.value.trim()
if(!v){pop.querySelector("#dashNameErr").classList.remove("hidden");return}
finish(v)
}
pop.querySelector("#dashNameOk").addEventListener("click",submitName)
input.addEventListener("keydown",(e)=>{if(e.key==="Enter")submitName()})
})
}
function dashApplyCards(cards){
dashState.cards=cards||[]
closeDashPopover()
renderDashGrid()
}
function dashApplyPreset(id){
return bridgeCall("dashboard.apply_preset",[id]).then((cards)=>{dashApplyCards(cards);closeModal();showStatusIsland("Layout applied")}).catch((err)=>showToast(dashErr(err,"Could not apply the layout"),"error"))
}
function openDashLayoutsMenu(){
Promise.all([bridgeCall("dashboard.list_layouts"),bridgeCall("dashboard.presets").catch(()=>[])]).then(([names,presets])=>{
const pop=document.createElement("div")
pop.className="dash-popover glass-panel dash-layouts-menu"
let html='<div class="dash-popover-title">Built-in Layouts</div><div class="dash-popover-list dash-preset-list">'
presets.forEach((p)=>{
html+=`<button type="button" class="dash-preset" data-preset="${dashEsc(p.id)}"><span class="dash-preset-name">${dashEsc(p.name)}</span><span class="dash-preset-desc">${dashEsc(p.description)}</span></button>`
})
html+="</div>"
if(names.length){
html+='<div class="dash-popover-title">Saved Layouts</div><div class="dash-popover-list">'
names.forEach((n)=>{
html+=`<div class="dash-layout-row"><button type="button" class="dash-popover-item dash-layout-apply" data-name="${dashEsc(n)}"><i class="icon icon-table" aria-hidden="true"></i><span>${dashEsc(n)}</span></button><button type="button" class="dash-layout-delete" data-name="${dashEsc(n)}" title="Delete layout" aria-label="Delete layout ${dashEsc(n)}"><i class="icon icon-close" aria-hidden="true"></i></button></div>`
})
html+="</div>"
}
html+='<div class="dash-popover-actions-col"><button type="button" class="dash-btn-full" id="dashSaveCurrentBtn"><i class="icon icon-save" aria-hidden="true"></i><span>Save Current Dashboard...</span></button><button type="button" class="dash-btn-full" id="dashRestoreDefaultBtn"><i class="icon icon-restore" aria-hidden="true"></i><span>Reset to Default</span></button></div>'
pop.innerHTML=html
openModal(pop)
pop.querySelectorAll(".dash-preset").forEach((btn)=>btn.addEventListener("click",()=>dashApplyPreset(btn.dataset.preset)))
pop.querySelectorAll(".dash-layout-apply").forEach((btn)=>{
btn.addEventListener("click",()=>{
bridgeCall("dashboard.apply_layout",[btn.dataset.name]).then((cards)=>{dashApplyCards(cards);closeModal()}).catch((err)=>showToast(dashErr(err,"Could not apply the layout"),"error"))
})
})
pop.querySelectorAll(".dash-layout-delete").forEach((btn)=>{
btn.addEventListener("click",(e)=>{
e.stopPropagation()
bridgeCall("dashboard.delete_layout",[btn.dataset.name]).then(()=>openDashLayoutsMenu()).catch((err)=>showToast(dashErr(err,"Delete failed"),"error"))
})
})
pop.querySelector("#dashSaveCurrentBtn").addEventListener("click",()=>{
dashPromptLayoutName().then((name)=>{
if(!name)return
bridgeCall("dashboard.save_layout_as",[name]).then(()=>showStatusIsland("Layout saved")).catch((err)=>showToast(dashErr(err,"Save failed"),"error"))
})
})
pop.querySelector("#dashRestoreDefaultBtn").addEventListener("click",()=>{
appConfirm("Reset the dashboard to the default layout? Your saved layouts are kept.",{okLabel:"Reset"}).then((ok)=>{
if(!ok)return
bridgeCall("dashboard.restore_default").then((cards)=>{dashApplyCards(cards);closeModal()}).catch((err)=>showToast(dashErr(err,"Reset failed"),"error"))
})
})
const first=pop.querySelector("button")
if(first)first.focus()
}).catch((err)=>showToast(dashErr(err,"Could not list layouts"),"error"))
}
function dashBusy(force){
// Do not rebuild the cards under the user while they drag, use a popover or have the live-target select open.
if(dashState.dragId||document.getElementById("dashPopover"))return true
if(force)return false
const a=document.activeElement
return !!(a&&a.tagName==="SELECT"&&a.closest("#dashGrid"))
}
function dashRefresh(force){
// force: the user asked for it (switch, retry, run), so re-render even if the live-target select still has focus.
if(force)dashState.forceRender=true
// One request at a time; a refresh asked for meanwhile runs once more afterwards so it sees the newest data.
if(dashState.pending){dashState.again=true;return dashState.pending}
dashState.loading=true
dashState.pending=bridgeCall("dashboard.stats").then((stats)=>{
dashState.stats=stats||{}
}).catch((err)=>{
console.error("dashboard stats failed",err)
if(!dashState.stats||dashState.stats.__error)dashState.stats={__error:true}
else showToast("Could not refresh the dashboard","error")
}).then(()=>{
dashState.loading=false
dashState.pending=null
// With a follow-up queued, keep the force flag for that run (it renders the newest data).
const force=dashState.forceRender&&!dashState.again
if(!dashState.again)dashState.forceRender=false
if(!dashBusy(force))renderDashGrid()
if(dashState.again){dashState.again=false;return dashRefresh()}
})
return dashState.pending
}
function dashStartTimer(){
dashStopTimer()
dashState.timer=setInterval(()=>{
if(!dashPageActive()){dashStopTimer();return}
if(!dashBusy())dashRefresh()
},DASH_REFRESH_MS)
}
function dashStopTimer(){
if(dashState.timer){clearInterval(dashState.timer);dashState.timer=null}
}
function dashOnPageShown(e){
const page=e.detail&&e.detail.page
if(page!=="dashboard"){dashStopTimer();return}
if(!e.detail.first)dashRefresh()
dashStartTimer()
}
function initDashboard(){
return fetch("../pages/dashboard.html").then((r)=>r.text()).then((html)=>{
document.querySelector('.page[data-page="dashboard"]').innerHTML=html
document.getElementById("dashEditBtn").addEventListener("click",toggleDashEditMode)
document.getElementById("dashLayoutsBtn").addEventListener("click",openDashLayoutsMenu)
const grid=document.getElementById("dashGrid")
grid.addEventListener("click",dashHandleGridClick)
grid.addEventListener("change",dashHandleGridChange)
wireDashQuickActions()
document.addEventListener("keydown",dashHandleKeydown)
document.addEventListener("visibilitychange",()=>{if(!document.hidden&&dashPageActive()){dashRefresh();dashStartTimer()}})
renderDashGrid()
return Promise.all([bridgeCall("dashboard.catalog"),bridgeCall("dashboard.get_layout")])
}).then((results)=>{
dashState.catalog=results[0]
dashState.cards=results[1]
renderDashGrid()
return dashRefresh()
}).catch((err)=>{
console.error("dashboard init failed",err)
dashState.stats={__error:true}
renderDashGrid()
})
}
document.addEventListener("loya:page-shown",dashOnPageShown)
