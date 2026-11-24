let paletteState={open:false,items:[],selected:0,debounceTimer:null,lastQuery:""}
// Escapes quotes too: the result is also placed inside HTML attributes (title, data-*, value). The old textContent/innerHTML
// trick left " unescaped, so a saved name like  " onmouseover="...  injected a handler with full bridge access.
function paletteEscapeHtml(s){
return String(s===undefined||s===null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")
}
const PALETTE_ACTIONS=[
{id:"nav-dashboard",label:"Go to Dashboard",run:()=>goToPage("dashboard")},
{id:"nav-notes",label:"Go to Notes",run:()=>goToPage("notes")},
{id:"nav-reporting",label:"Go to Reporting",keywords:"reports pentest findings export pdf word",run:()=>goToPage("reporting")},
{id:"new-report",label:"New Report",keywords:"reporting pentest template",run:()=>goToPage("reporting").then(()=>window.Reporting&&Reporting.newReport())},
{id:"report-autogen",label:"Reporting: Auto-generate Report from Sessions",keywords:"terminal recording evidence draft",run:()=>goToPage("reporting").then(()=>window.ReportEvidence&&ReportEvidence.openAutogen())},
{id:"report-evidence",label:"Reporting: Open Evidence",keywords:"saved results recordings screenshots",run:()=>window.ReportEvidence&&ReportEvidence.openManager()},
{id:"report-library",label:"Reporting: Findings Library",keywords:"reusable findings",run:()=>goToPage("reporting").then(()=>window.ReportFindings&&ReportFindings.openLibrary())},
{id:"report-timeline",label:"Reporting: Open Timeline",keywords:"schedule milestones deadline reminder",run:()=>goToPage("reporting").then(()=>window.Reporting&&Reporting.current()?Reporting.openEntry("timeline"):showToast("Open a report first"))},
{id:"report-add-section",label:"Reporting: Add Section...",keywords:"executive summary scope methodology risk matrix attack narrative",run:()=>goToPage("reporting").then(()=>window.Reporting&&Reporting.current()?Reporting.addSection():showToast("Open a report first"))},
{id:"report-undo",label:"Reporting: Undo",run:()=>window.Reporting&&Reporting.undo()},
{id:"report-redo",label:"Reporting: Redo",run:()=>window.Reporting&&Reporting.redo()},
{id:"nav-chains",label:"Go to Chains",keywords:"action chains playbooks caller run sequence",run:()=>goToPage("chains")},
{id:"new-chain",label:"New Action Chain",keywords:"chains playbook caller",run:()=>goToPage("chains").then(()=>chainsCreatePrompt())},
{id:"nav-cve",label:"Go to CVE Intel",keywords:"cve vulnerability vulnerabilities nvd kev epss news",run:()=>goToPage("cve")},
{id:"nav-targets",label:"Go to Targets",run:()=>goToPage("targets")},
{id:"nav-snippets",label:"Go to Quick Run",keywords:"snippets cheat sheet favourites",run:()=>goToPage("snippets")},
{id:"nav-settings",label:"Go to Settings",run:()=>goToPage("settings")},
{id:"new-note",label:"New Note",run:()=>goToPage("notes").then(()=>notesOpenNewNote())},
{id:"toggle-theme",label:"Toggle Theme",run:()=>window.__toggleTheme&&window.__toggleTheme()},
{id:"open-terminal",label:"Open Terminal",run:()=>termTogglePanel()},
{id:"open-ai",label:"Open AI Assistant",run:()=>aiTogglePanel()},
{id:"term-new-session",label:"Terminal: New Session",run:()=>termPaletteAction(()=>termNewTab())},
{id:"term-reopen-closed",label:"Terminal: Reopen Closed Session",run:()=>termPaletteAction(()=>termReopenClosed())},
{id:"term-sessions",label:"Terminal: Saved Sessions",run:()=>termPaletteAction(()=>{if(!termState.sessionsOpen)termToggleSessionsDrawer()})},
{id:"term-jobs",label:"Terminal: Show Jobs",run:()=>termPaletteAction(()=>{if(!termState.jobsOpen)termToggleJobsDrawer()})},
{id:"term-search",label:"Terminal: Search Output",run:()=>termPaletteAction(termOpenSearch)},
{id:"term-iocs",label:"Terminal: Extract Indicators",run:()=>termPaletteAction(termOpenIocModal)},
{id:"term-rerun-last",label:"Terminal: Run Last Command Again",run:()=>termPaletteAction(termRunLastCommand)},
{id:"term-kill-jobs",label:"Terminal: Interrupt All Running Jobs",run:()=>termPaletteAction(termKillAllJobs)},
{id:"term-clear",label:"Terminal: Clear Output",run:()=>termPaletteAction(termClearOutput)},
]
function paletteMatchActions(query){
const q=(query||"").trim().toLowerCase()
if(!q)return []
return PALETTE_ACTIONS.filter((a)=>(a.label+" "+(a.keywords||"")).toLowerCase().includes(q))
}
function paletteKindIcon(kind){
if(kind==="note")return "icon-edit"
if(kind==="command")return "icon-command-line"
if(kind==="target")return "icon-target"
return "icon-star"
}
function paletteKindLabel(kind){
if(kind==="note")return "Note"
if(kind==="command")return "Command"
if(kind==="target")return "Target"
return "Action"
}
function paletteOpenResult(item){
const q=document.getElementById("paletteInput").value.trim()
if(q&&!item.__action)bridgeCall("search.record_recent_query",[q]).catch(()=>{})
paletteClose()
if(item.__action){item.run();return}
if(item.kind==="note"){goToPage("notes").then(()=>{if(typeof notesOpen==="function")notesOpen(item.id)});return}
if(item.kind==="command"){goToPage(item.src==="CommandsNotes"?"snippets":"commands");return}
if(item.kind==="target"){goToPage("targets");return}
}
function paletteRenderResults(){
const wrap=document.getElementById("paletteResults")
wrap.innerHTML=""
if(!paletteState.items.length){
const q=document.getElementById("paletteInput").value.trim()
wrap.innerHTML=`<div class="palette-empty">${q?"No matches":"Type to search notes, commands, targets and actions"}</div>`
return
}
paletteState.items.forEach((item,i)=>{
const row=document.createElement("button")
row.type="button"
row.className="palette-item"+(i===paletteState.selected?" active":"")
const icon=item.__action?"icon-star-filled":paletteKindIcon(item.kind)
const kindLabel=item.__action?"Action":paletteKindLabel(item.kind)
const title=item.__action?item.label:item.title
const preview=item.__action?"":(item.preview||"")
row.innerHTML=`<i class="icon ${icon}"></i><div class="palette-item-body"><div class="palette-item-title">${paletteEscapeHtml(title)}</div>${preview?`<div class="palette-item-preview">${paletteEscapeHtml(preview)}</div>`:""}</div><span class="palette-item-kind">${paletteEscapeHtml(kindLabel)}</span>`
row.addEventListener("click",()=>paletteOpenResult(item))
row.addEventListener("mouseenter",()=>{paletteState.selected=i;paletteHighlightSelected()})
wrap.appendChild(row)
})
paletteHighlightSelected()
}
function paletteHighlightSelected(){
const wrap=document.getElementById("paletteResults")
Array.from(wrap.children).forEach((el,i)=>el.classList.toggle("active",i===paletteState.selected))
const active=wrap.children[paletteState.selected]
if(active)active.scrollIntoView({block:"nearest"})
}
function paletteRenderRecent(){
bridgeCall("search.recent_queries").then((recent)=>{
const wrap=document.getElementById("paletteResults")
if(!recent.length){
wrap.innerHTML='<div class="palette-empty">Type to search notes, commands, targets and actions</div>'
return
}
wrap.innerHTML='<div class="palette-section-title">Recent Searches</div>'
recent.forEach((q)=>{
const btn=document.createElement("button")
btn.type="button"
btn.className="palette-recent-item"
btn.innerHTML=`<i class="icon icon-list"></i><span>${paletteEscapeHtml(q)}</span>`
btn.addEventListener("click",()=>{
document.getElementById("paletteInput").value=q
paletteRunQuery(q)
})
wrap.appendChild(btn)
})
}).catch(()=>{})
}
function paletteRunQuery(query){
const q=(query||"").trim()
paletteState.lastQuery=q
if(!q){
paletteState.items=paletteMatchActions("")
paletteRenderRecent()
return
}
const actionMatches=paletteMatchActions(q).map((a)=>({...a,__action:true}))
bridgeCall("search.global_search",[q]).then((rows)=>{
if(paletteState.lastQuery!==q)return
paletteState.items=[...actionMatches,...rows]
paletteState.selected=0
paletteRenderResults()
}).catch(()=>{
paletteState.items=actionMatches
paletteState.selected=0
paletteRenderResults()
})
}
function paletteOnInput(){
const val=document.getElementById("paletteInput").value
clearTimeout(paletteState.debounceTimer)
if(!val.trim()){
paletteState.items=[]
paletteRenderRecent()
return
}
paletteState.debounceTimer=setTimeout(()=>paletteRunQuery(val),150)
}
function paletteOpen(){
if(paletteState.open)return
paletteState.open=true
const input=document.getElementById("paletteInput")
input.value=""
paletteState.items=[]
paletteState.selected=0
document.getElementById("paletteOverlay").classList.remove("hidden")
paletteRenderRecent()
setTimeout(()=>input.focus(),0)
}
function paletteClose(){
if(!paletteState.open)return
paletteState.open=false
document.getElementById("paletteOverlay").classList.add("hidden")
}
function paletteToggle(){
if(paletteState.open)paletteClose()
else paletteOpen()
}
function paletteMoveSelection(dir){
if(!paletteState.items.length)return
paletteState.selected=(paletteState.selected+dir+paletteState.items.length)%paletteState.items.length
paletteHighlightSelected()
}
function paletteConfirmSelection(){
if(paletteState.items.length)paletteOpenResult(paletteState.items[paletteState.selected])
}
function initPalette(){
document.getElementById("paletteInput").addEventListener("input",paletteOnInput)
document.getElementById("paletteInput").addEventListener("keydown",(e)=>{
if(e.key==="ArrowDown"){e.preventDefault();paletteMoveSelection(1)}
else if(e.key==="ArrowUp"){e.preventDefault();paletteMoveSelection(-1)}
else if(e.key==="Enter"){e.preventDefault();paletteConfirmSelection()}
else if(e.key==="Escape"){e.preventDefault();paletteClose()}
})
document.getElementById("paletteOverlay").addEventListener("mousedown",(e)=>{
if(e.target.id==="paletteOverlay")paletteClose()
})
document.addEventListener("keydown",(e)=>{
const mod=e.ctrlKey||e.metaKey
if(mod&&(e.key==="k"||e.key==="K")){e.preventDefault();paletteToggle()}
})
}
