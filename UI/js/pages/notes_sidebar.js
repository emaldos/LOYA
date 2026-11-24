// Notes sidebar (DOM side). Pure logic lives in notes_sidebar_core.js (NotesSidebar). notes.js keeps the note actions (open, move, pin,
// delete, group manager) and calls notesSbInit() once the markup exists, notesSbSetData() after each refresh and notesSbRender() to redraw.
// The list is virtual: only the rows in view are in the DOM, so 500+ notes scroll and filter without rebuilding the whole list.
const notesSb={data:{groups:[],pinned:[],recent:[],targets:[]},prefs:NotesSidebar.normPrefs({}),model:null,items:[],lay:{tops:[],total:0,heights:NotesSidebar.HEIGHTS.comfortable},els:new Map(),cursor:"",hits:new Map(),hitsQuery:"",hitsTimer:null,hitsSeq:0,hitsPending:false,session:{},renaming:null,drag:null,raf:0,loaded:false,stickyKey:"",lastRenderMs:0}
function notesSbList(){return document.getElementById("notesGroups")}
function notesSbItemKey(it){
if(it.type==="head")return "h:"+it.key
if(it.type==="row")return "r:"+it.section+":"+it.note.id
return it.type+":"+it.section
}
function notesSbPersisted(kind){return kind==="group"||kind==="pinned"||kind==="recent"}
function notesSbCollapsedMap(){return Object.assign({},notesState.collapsed,notesSb.session)}
function notesSbContentOn(){return notesSb.prefs.scopes.indexOf("content")>=0}
function notesSbQuery(){return (notesState.search||"").trim()}
// ---- data
function notesSbSetData(payload){
const d=payload||{}
notesSb.data={groups:d.groups||[],pinned:d.pinned||[],recent:d.recent||[],targets:d.targets||[]}
notesSb.prefs=NotesSidebar.normPrefs(d.prefs||notesSb.prefs)
notesSb.loaded=true
notesState.notes=d.notes||[]
notesState.collapsed={}
;(d.collapsed||[]).forEach((k)=>{notesState.collapsed[k]=true})
// Kept in the old shape for the Group Manager pickers.
notesState.groups=NotesSidebar.groupNames(notesState.notes,notesSb.data.groups).map((g)=>({group_name:g,label:g}))
notesSb.hitsQuery=""
notesSbApplyPrefs()
notesSbScheduleContent(true)
}
function notesSbSetPref(key,value){
const next=Object.assign({},notesSb.prefs)
next[key]=value
notesSb.prefs=NotesSidebar.normPrefs(next)
notesSbApplyPrefs()
if(key==="scopes")notesSbScheduleContent(true)
notesSbRender({keepScroll:key==="width"})
bridgeCall("notes.set_sidebar_pref",[key,notesSb.prefs[key]]).catch(()=>{})
}
function notesSbApplyPrefs(){
const p=notesSb.prefs
const side=document.getElementById("notesSidebar")
if(!side)return
side.style.width=p.width+"px"
side.dataset.density=p.density
side.dataset.view=p.view
side.classList.toggle("wide",p.width>=330)
document.querySelectorAll("#notesSbViews [data-view]").forEach((b)=>{
const on=b.dataset.view===p.view
b.classList.toggle("active",on)
b.setAttribute("aria-selected",on?"true":"false")
b.tabIndex=on?0:-1
})
document.querySelectorAll("#notesSbScopes [data-scope]").forEach((b)=>{
const on=p.scopes.indexOf(b.dataset.scope)>=0
b.classList.toggle("active",on)
b.setAttribute("aria-pressed",on?"true":"false")
})
const labels={name:"Name",edited:"Edited",created:"Created"}
document.getElementById("notesSbSortLabel").textContent=labels[p.sort]
const sortBtn=document.getElementById("notesSbSort")
sortBtn.querySelector(".icon").className="icon icon-arrow-"+(p.dir==="desc"?"down":"up")
sortBtn.title="Sort: "+labels[p.sort]+(p.dir==="desc"?", descending":", ascending")
const handle=document.getElementById("notesSbResize")
handle.setAttribute("aria-valuenow",String(p.width))
handle.setAttribute("aria-valuemin",String(p.width_min))
handle.setAttribute("aria-valuemax",String(p.width_max))
}
// ---- model and drawing
function notesSbCompute(){
const q=notesSbQuery()
const useHits=notesSbContentOn()&&q&&notesSb.hitsQuery===q
const model=NotesSidebar.buildSections({notes:notesState.notes,groups:notesSb.data.groups,pinned:notesSb.data.pinned,recent:notesSb.data.recent,targets:notesSb.data.targets,prefs:notesSb.prefs,search:q,contentIds:useHits?new Set(notesSb.hits.keys()):null,draft:notesState.draft,now:Date.now()})
notesSb.model=model
notesSb.items=NotesSidebar.flatten(model.sections,notesSbCollapsedMap(),model.searching)
notesSb.lay=NotesSidebar.layout(notesSb.items,notesSb.prefs.density)
}
function notesSbRender(opts){
const list=notesSbList()
if(!list||!notesSb.loaded)return
const t0=performance.now()
const o=opts||{}
if(notesSb.renaming&&!o.keepRename)notesSb.renaming=null
notesSbCompute()
let canvas=list.querySelector(".notes-sb-canvas")
if(!canvas){
list.innerHTML='<div class="notes-sb-canvas"></div><div class="notes-sb-empty hidden" id="notesSbEmpty"></div>'
list.removeAttribute("aria-busy")
canvas=list.firstChild
}
canvas.textContent=""
notesSb.els.clear()
canvas.style.height=notesSb.lay.total+"px"
if(o.resetScroll)list.scrollTop=0
const keys=new Set(notesSb.items.map(notesSbItemKey))
if(notesSb.cursor&&!keys.has(notesSb.cursor))notesSb.cursor=""
notesSbRenderChrome()
notesSbRenderEmpty()
notesSb.stickyKey="\0"
notesSbWindow()
notesSb.lastRenderMs=performance.now()-t0
}
function notesSbRenderChrome(){
const m=notesSb.model
const q=notesSbQuery()
document.getElementById("notesSbCount").textContent=NotesSidebar.countLabel(m)+(notesSb.hitsPending?" ...":"")
document.getElementById("notesSearchClear").classList.toggle("hidden",!q)
document.getElementById("notesSbScopes").classList.toggle("hidden",!q)
const counts=NotesSidebar.filterCounts(notesState.notes)
document.querySelectorAll("#notesSbFilters [data-filter]").forEach((b)=>{
const on=notesSb.prefs.filters.indexOf(b.dataset.filter)>=0
b.classList.toggle("active",on)
b.setAttribute("aria-pressed",on?"true":"false")
const n=counts[b.dataset.filter]||0
b.querySelector(".notes-sb-chip-n").textContent=String(n)
b.setAttribute("aria-label",b.dataset.label+", "+n+(n===1?" note":" notes"))
})
const keys=NotesSidebar.sectionKeys(m.sections).filter((k)=>k!=="__draft__")
const col=notesSbCollapsedMap()
const anyOpen=keys.some((k)=>!col[k])
const all=document.getElementById("notesSbToggleAll")
all.dataset.mode=anyOpen?"collapse":"expand"
all.title=anyOpen?"Collapse all":"Expand all"
all.setAttribute("aria-label",all.title)
all.querySelector(".icon").className="icon icon-"+(anyOpen?"shrink":"expand")
all.disabled=!keys.length||m.searching
}
function notesSbRenderEmpty(){
const empty=document.getElementById("notesSbEmpty")
const m=notesSb.model
const none=notesSb.items.length===0
empty.classList.toggle("hidden",!none)
if(!none){empty.textContent="";return}
const narrowed=m.searching||m.filtering
let html='<i class="icon icon-'+(narrowed?"search":"edit")+'"></i>'
if(!narrowed){
html+='<div class="notes-sb-empty-title">No notes yet</div><div class="notes-sb-empty-hint">Notes you write appear here, organised by group, tag, date or target.</div><button type="button" class="notes-sb-empty-btn primary" data-empty="new">Create a note</button>'
}else{
html+='<div class="notes-sb-empty-title">No notes match</div><div class="notes-sb-empty-hint">'+(m.searching?"Nothing found for <b>"+notesEscapeHtml(notesSbQuery())+"</b>"+(m.filtering?" with the active filters":"")+".":"No note has every active filter.")+"</div>"
if(m.searching&&!notesSbContentOn())html+='<button type="button" class="notes-sb-empty-btn primary" data-empty="content">Search note content too</button>'
if(m.searching)html+='<button type="button" class="notes-sb-empty-btn" data-empty="search">Clear search</button>'
if(m.filtering)html+='<button type="button" class="notes-sb-empty-btn" data-empty="filters">Clear filters</button>'
}
empty.innerHTML=html
}
function notesSbHeadIcon(it){
if(it.kind==="pinned")return "pin"
if(it.kind==="recent"||it.kind==="bucket")return "clock"
if(it.kind==="target")return "target"
if(it.kind==="draft")return "edit"
if(it.kind==="tag")return ""
const st=notesSb.prefs.group_styles[it.key]
return (st&&st.icon)||(it.key===NotesSidebar.UNGROUPED?"file":"folder")
}
function notesSbHeadHtml(it,plain){
const words=notesSb.model.words
const nameScope=notesSb.prefs.scopes.indexOf("name")>=0
const icon=notesSbHeadIcon(it)
const iconHtml=it.kind==="tag"?'<span class="notes-head-icon notes-head-hash">#</span>':`<span class="notes-head-icon"><i class="icon icon-${icon}"></i></span>`
const renaming=!plain&&notesSb.renaming&&notesSb.renaming.key===it.key
const label=renaming?`<input type="text" class="notes-head-rename" value="${notesEscapeHtml(notesSb.renaming.label)}" aria-label="Group name" autocomplete="off" spellcheck="false">`:`<span class="notes-head-label" title="${notesEscapeHtml(it.title)}">${it.kind==="group"&&nameScope?NotesSidebar.highlight(it.label,words,notesEscapeHtml):notesEscapeHtml(it.label)}</span>`
let actions=""
if(!plain&&it.kind==="group"&&!renaming)actions=`<span class="notes-head-actions"><button type="button" class="notes-icon-btn" data-act="add" tabindex="-1" title="New note in this group" aria-label="New note in this group"><i class="icon icon-add"></i></button><button type="button" class="notes-icon-btn" data-act="menu" tabindex="-1" title="Group actions" aria-label="Group actions"><i class="icon icon-dots-vertical"></i></button></span>`
return `<span class="notes-head-chev"></span>${iconHtml}${label}<span class="notes-head-count">${Number(it.count)||0}</span>${actions}`
}
function notesSbTagChips(tags,words,max){
if(!tags.length)return ""
const tagScope=notesSb.prefs.scopes.indexOf("tags")>=0
// A tag that matches the search is shown first, so the reason a note matched is visible.
const ordered=tagScope&&words.length?tags.slice().sort((a,b)=>(words.some((w)=>b.toLowerCase().indexOf(w)>=0)?1:0)-(words.some((w)=>a.toLowerCase().indexOf(w)>=0)?1:0)):tags
const shown=ordered.slice(0,max||2),rest=ordered.slice(max||2)
let html=shown.map((t)=>`<span class="notes-row-tag" style="${notesEscapeHtml(notesTagPillStyle(t))}" title="${notesEscapeHtml(t)}">${tagScope?NotesSidebar.highlight(t,words,notesEscapeHtml):notesEscapeHtml(t)}</span>`).join("")
if(rest.length)html+=`<span class="notes-row-tag notes-row-tag-more" title="${notesEscapeHtml(rest.join(", "))}">+${rest.length}</span>`
return `<span class="notes-row-tags">${html}</span>`
}
function notesSbRowHtml(it){
const n=it.note
const P=NotesSidebar
const m=notesSb.model
const words=m.words
const prefs=notesSb.prefs
const nameScope=prefs.scopes.indexOf("name")>=0
const sev=P.SEVERITIES.indexOf(n.sev)>=0?n.sev:""
const sevHtml=sev?`<span class="notes-row-sev sev-${sev}" title="Highest finding severity: ${P.sevLabel(sev)}"></span>`:(Number(n.findings)>0?'<span class="notes-row-sev sev-none" title="Has findings (no severity set)"></span>':'<span class="notes-row-sev"></span>')
const created=prefs.sort==="created"
const ts=created?n.created_ts:n.updated_ts
const rel=P.relTime(ts)
const timeHtml=rel?`<span class="notes-row-time" title="${created?"Created":"Edited"} ${notesEscapeHtml(P.relTimeLong(ts))}${created?"":" - "+notesEscapeHtml(n.updated_label||"")}">${rel}</span>`:""
const cmds=Number(n.cmds)||0
const cmdHtml=cmds?`<span class="notes-row-badge" title="${cmds} command block${cmds===1?"":"s"}"><i class="icon icon-command-line"></i>${cmds}</span>`:""
const pinHtml=n.pinned?'<span class="notes-row-pin" title="Pinned"><i class="icon icon-pin"></i></span>':""
const title=`<span class="notes-row-title" title="${notesEscapeHtml(n.note_name)}">${nameScope?P.highlight(n.note_name,words,notesEscapeHtml):notesEscapeHtml(n.note_name)}</span>`
const actions=`<span class="notes-row-actions"><button type="button" class="notes-icon-btn${n.pinned?" on":""}" data-act="pin" tabindex="-1" title="${n.pinned?"Unpin":"Pin"}" aria-label="${n.pinned?"Unpin note":"Pin note"}"><i class="icon icon-pin"></i></button><button type="button" class="notes-icon-btn" data-act="edit" tabindex="-1" title="Open in editor" aria-label="Open in editor"><i class="icon icon-edit"></i></button><button type="button" class="notes-icon-btn" data-act="menu" tabindex="-1" title="More actions" aria-label="More actions"><i class="icon icon-dots-vertical"></i></button></span>`
if(prefs.density==="compact")return `${sevHtml}${title}${cmdHtml}${pinHtml}${timeHtml}${actions}`
const snippet=m.searching&&notesSbContentOn()&&notesSb.hitsQuery===notesSbQuery()?notesSb.hits.get(n.id):""
let meta
if(snippet)meta=`<span class="notes-row-snippet" title="${notesEscapeHtml(snippet)}">${P.highlight(snippet,words,notesEscapeHtml)}</span>`
else{
const showGroup=it.kind!=="group"&&n.group_name
const groupHtml=showGroup?`<span class="notes-row-group" title="Group: ${notesEscapeHtml(n.group_name)}"><i class="icon icon-folder"></i>${nameScope?P.highlight(n.group_name,words,notesEscapeHtml):notesEscapeHtml(n.group_name)}</span>`:""
meta=`${timeHtml}${cmdHtml}${groupHtml}${notesSbTagChips(P.splitTags(n.tags),words,showGroup?1:2)}`
}
return `${sevHtml}<span class="notes-row-main"><span class="notes-row-top">${title}${pinHtml}</span><span class="notes-row-meta">${meta}</span></span>${actions}`
}
function notesSbBuildItem(it,i){
const el=document.createElement("div")
const lay=notesSb.lay
el.id="notesSbI"+i
el.dataset.i=String(i)
el.style.top=lay.tops[i]+"px"
el.style.height=NotesSidebar.itemHeight(it,lay.heights)+"px"
el.style.setProperty("--d",String(it.depth))
el.setAttribute("role","treeitem")
el.setAttribute("aria-level",String(it.depth+1))
if(it.type==="head"){
el.className="notes-head kind-"+it.kind+(it.collapsed?" collapsed":"")+(it.depth?" nested":"")
el.setAttribute("aria-expanded",it.collapsed?"false":"true")
el.dataset.key=it.key
const st=it.kind==="group"?notesSb.prefs.group_styles[it.key]:null
if(st&&st.color)el.style.setProperty("--g",st.color)
else if(it.kind==="tag"&&it.tag&&notesTagColor(it.tag)&&NotesSidebar.normHex(notesTagColor(it.tag)))el.style.setProperty("--g",NotesSidebar.normHex(notesTagColor(it.tag)))
el.innerHTML=notesSbHeadHtml(it)
}else if(it.type==="row"){
const n=it.note
el.className="notes-row"+(n.id===notesState.selectedId?" active":"")
el.setAttribute("aria-selected",n.id===notesState.selectedId?"true":"false")
el.draggable=true
el.dataset.id=String(n.id)
el.innerHTML=notesSbRowHtml(it)
}else if(it.type==="draft"){
const d=it.draft||{}
el.className="notes-row notes-row-draft"
el.innerHTML=`<span class="notes-row-sev"></span><span class="notes-row-main"><span class="notes-row-top"><span class="notes-row-title">${notesEscapeHtml((d.name&&d.name.trim())||"Untitled")} (Draft)</span></span><span class="notes-row-meta"><span class="notes-row-snippet">${notesEscapeHtml(notesStripHtmlPreview(d.html))}</span></span></span>`
}else{
el.className="notes-empty-row"
el.setAttribute("role","none")
el.removeAttribute("aria-level")
el.textContent=it.text
}
if(notesSb.cursor&&notesSbItemKey(it)===notesSb.cursor)el.classList.add("cursor")
return el
}
function notesSbWindow(){
const list=notesSbList()
const canvas=list&&list.querySelector(".notes-sb-canvas")
if(!canvas)return
const items=notesSb.items
const r=NotesSidebar.windowRange(notesSb.lay.tops,notesSb.lay.total,list.scrollTop,list.clientHeight,8)
const want=new Set()
const frag=document.createDocumentFragment()
for(let i=r.start;i<=r.end;i++){
const key=notesSbItemKey(items[i])
want.add(key)
if(!notesSb.els.has(key)){
const el=notesSbBuildItem(items[i],i)
notesSb.els.set(key,el)
frag.appendChild(el)
}
}
canvas.appendChild(frag)
const keepRename=notesSb.renaming?"h:"+notesSb.renaming.key:""
notesSb.els.forEach((el,key)=>{
if(want.has(key)||key===keepRename||(notesSb.drag&&el===notesSb.drag.el))return
el.remove()
notesSb.els.delete(key)
})
const cur=notesSb.cursor&&notesSb.els.get(notesSb.cursor)
if(cur)list.setAttribute("aria-activedescendant",cur.id);else list.removeAttribute("aria-activedescendant")
notesSbUpdateSticky()
notesSbUpdateJump()
}
function notesSbOnScroll(){
if(notesSb.raf)return
notesSb.raf=requestAnimationFrame(()=>{notesSb.raf=0;notesSbWindow()})
}
// The header of the section at the top of the view stays pinned there while its rows scroll under it.
function notesSbUpdateSticky(){
const list=notesSbList()
const sticky=document.getElementById("notesSbSticky")
const items=notesSb.items,tops=notesSb.lay.tops
let idx=-1
if(items.length&&list.scrollTop>0){
let i=NotesSidebar.windowRange(tops,notesSb.lay.total,list.scrollTop,0,0).start
while(i>=0&&items[i].type!=="head")i--
if(i>=0&&tops[i]<list.scrollTop)idx=i
}
const key=idx<0?"":items[idx].key
// The next header pushes the pinned one up as it arrives, instead of sliding under it.
let push=0
if(idx>=0){
let j=idx+1
while(j<items.length&&items[j].type!=="head")j++
if(j<items.length)push=Math.min(0,tops[j]-list.scrollTop-notesSb.lay.heights.head)
}
sticky.style.transform=push?`translateY(${push}px)`:""
if(key===notesSb.stickyKey)return
notesSb.stickyKey=key
sticky.classList.toggle("hidden",idx<0)
if(idx<0){sticky.textContent="";return}
const it=items[idx]
sticky.className="notes-sb-sticky notes-head kind-"+it.kind
sticky.dataset.i=String(idx)
sticky.style.removeProperty("--g")
const st=it.kind==="group"?notesSb.prefs.group_styles[it.key]:null
if(st&&st.color)sticky.style.setProperty("--g",st.color)
sticky.innerHTML=notesSbHeadHtml(Object.assign({},it,{label:it.title||it.label}),true)
}
function notesSbUpdateJump(){
const btn=document.getElementById("notesSbJump")
const list=notesSbList()
const id=notesState.selectedId
let show=false
if(id&&notesSb.model&&NotesSidebar.sectionPath(notesSb.model.sections,id)){
const i=NotesSidebar.rowIndex(notesSb.items,id)
if(i<0)show=true
else{
// Visible when any copy of the note (pinned, recent, its group) is in view.
show=true
for(let j=0;j<notesSb.items.length;j++){
const it=notesSb.items[j]
if(it.type!=="row"||it.note.id!==id)continue
const top=notesSb.lay.tops[j]
if(top+notesSb.lay.heights.row>list.scrollTop&&top<list.scrollTop+list.clientHeight){show=false;break}
}
}
}
btn.classList.toggle("hidden",!show)
}
function notesSbScrollToIndex(i,center){
const list=notesSbList()
if(i<0||i>=notesSb.items.length)return
const top=notesSb.lay.tops[i],h=NotesSidebar.itemHeight(notesSb.items[i],notesSb.lay.heights)
const pad=notesSb.items[i].type==="head"?0:notesSb.lay.heights.head
if(center)list.scrollTop=Math.max(0,top-Math.round((list.clientHeight-h)/2))
else if(top-pad<list.scrollTop)list.scrollTop=Math.max(0,top-pad)
else if(top+h>list.scrollTop+list.clientHeight)list.scrollTop=top+h-list.clientHeight
notesSbWindow()
}
function notesSbJumpToCurrent(){
const id=notesState.selectedId
if(!id||!notesSb.model)return
const path=NotesSidebar.sectionPath(notesSb.model.sections,id,["pinned","recent"])||NotesSidebar.sectionPath(notesSb.model.sections,id)
if(!path)return
const col=notesSbCollapsedMap()
const closed=path.filter((k)=>col[k])
if(closed.length){
closed.forEach((k)=>{delete notesState.collapsed[k];delete notesSb.session[k]})
bridgeCall("notes.set_groups_collapsed",[closed,false]).catch(()=>{})
notesSbRender({keepScroll:true})
}
const i=NotesSidebar.rowIndex(notesSb.items,id,path[path.length-1])
if(i<0)return
notesSbSetCursor(notesSbItemKey(notesSb.items[i]))
notesSbScrollToIndex(i,true)
}
// ---- cursor (keyboard position) and keyboard
function notesSbSetCursor(key){
const list=notesSbList()
list.querySelectorAll(".cursor").forEach((el)=>el.classList.remove("cursor"))
notesSb.cursor=key||""
const el=notesSb.cursor&&notesSb.els.get(notesSb.cursor)
if(el){el.classList.add("cursor");list.setAttribute("aria-activedescendant",el.id)}
else list.removeAttribute("aria-activedescendant")
}
function notesSbCursorIndex(){
if(!notesSb.cursor)return -1
for(let i=0;i<notesSb.items.length;i++)if(notesSbItemKey(notesSb.items[i])===notesSb.cursor)return i
return -1
}
function notesSbGoTo(j){
if(j<0||j>=notesSb.items.length)return
notesSbScrollToIndex(j,false)
notesSbSetCursor(notesSbItemKey(notesSb.items[j]))
}
function notesSbMoveCursor(dir,rowsOnly){
const items=notesSb.items
const stop=(it)=>it.type!=="empty"&&(!rowsOnly||it.type==="row"||it.type==="draft")
let j=notesSbCursorIndex()
if(j<0)j=dir>0?-1:items.length
for(j+=dir;j>=0&&j<items.length;j+=dir)if(stop(items[j]))break
notesSbGoTo(j)
}
function notesSbActivate(it){
if(!it)return
if(it.type==="head")notesSbToggle(it)
else if(it.type==="row")notesOpen(it.note.id)
else if(it.type==="draft")notesApplyDraft(it.draft,false)
}
function notesSbListKeydown(e){
if(e.target!==notesSbList()||e.ctrlKey||e.metaKey||e.altKey)return
const items=notesSb.items
const i=notesSbCursorIndex()
const it=i>=0?items[i]:null
const key=e.key
if(key==="ArrowDown"){e.preventDefault();notesSbMoveCursor(1)}
else if(key==="ArrowUp"){e.preventDefault();notesSbMoveCursor(-1)}
else if(key==="Home"||key==="End"){
e.preventDefault()
let j=key==="Home"?NotesSidebar.firstStop(items):items.length-1
while(j>0&&items[j].type==="empty")j--
if(j>=0)notesSbGoTo(j)
}else if(key==="Enter"||key===" "){
if(it){e.preventDefault();notesSbActivate(it)}
}else if(key==="ArrowRight"){
if(it&&it.type==="head"){e.preventDefault();if(it.collapsed)notesSbToggle(it);else notesSbMoveCursor(1)}
}else if(key==="ArrowLeft"){
if(!it)return
e.preventDefault()
if(it.type==="head"&&!it.collapsed){notesSbToggle(it);return}
let j=i-1
while(j>=0&&!(items[j].type==="head"&&items[j].depth<it.depth))j--
if(j>=0)notesSbGoTo(j)
}else if(key==="F2"){
if(it&&it.type==="head"&&it.kind==="group"&&it.group){e.preventDefault();notesSbStartRename(it)}
}else if(key==="ContextMenu"||(key==="F10"&&e.shiftKey)){
const el=it&&notesSb.els.get(notesSb.cursor)
if(!el)return
e.preventDefault()
const r=el.getBoundingClientRect()
notesSbOpenMenu(it,r.left+24,r.bottom-4)
}else if(key==="Escape"&&notesSbQuery()){e.preventDefault();notesSbClearSearch()}
}
function notesSbSearchKeydown(e){
if(e.key==="ArrowDown"){e.preventDefault();notesSbMoveCursor(1,true)}
else if(e.key==="ArrowUp"){e.preventDefault();notesSbMoveCursor(-1,true)}
else if(e.key==="Enter"){
e.preventDefault()
let it=notesSb.items[notesSbCursorIndex()]
if(!it||it.type!=="row")it=notesSb.items.find((x)=>x.type==="row")
if(it)notesOpen(it.note.id)
}else if(e.key==="Escape"){
e.preventDefault()
e.stopPropagation()
if(e.target.value)notesSbClearSearch()
else notesSbList().focus()
}
}
function notesSbFocusSearch(){
const input=document.getElementById("notesSearchInput")
input.focus()
input.select()
}
// "/" and Ctrl+Shift+F focus the search from anywhere on the Notes page (not while typing in a field, the editor or a dialog).
function notesSbGlobalKeydown(e){
if(e.defaultPrevented||!notesPageActive()||notesEditorOpen())return
const slash=e.key==="/"&&!e.ctrlKey&&!e.metaKey&&!e.altKey
const combo=(e.ctrlKey||e.metaKey)&&e.shiftKey&&!e.altKey&&(e.key||"").toLowerCase()==="f"
if(!slash&&!combo)return
if(document.getElementById("appModalBackdrop")||document.querySelector(".confirm-overlay")||document.getElementById("appContextMenu")||document.getElementById("notesPopover"))return
const t=e.target
if(slash&&t&&t.nodeType===1&&(t.isContentEditable||/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)))return
e.preventDefault()
notesSbFocusSearch()
}
// ---- search
function notesSbOnSearchInput(e){
notesState.search=e.target.value
notesSb.cursor=""
notesSbScheduleContent(false)
notesSbRender({resetScroll:true})
}
function notesSbClearSearch(){
const input=document.getElementById("notesSearchInput")
input.value=""
notesState.search=""
notesSbScheduleContent(false)
notesSbRender({resetScroll:true})
}
// Content search runs in the backend (plain text of every note), debounced so typing does not queue a call per key.
function notesSbScheduleContent(now){
clearTimeout(notesSb.hitsTimer)
const q=notesSbQuery()
if(!notesSbContentOn()||q.length<2){notesSb.hitsSeq++;notesSb.hitsPending=false;notesSb.hits=new Map();notesSb.hitsQuery="";return}
if(q===notesSb.hitsQuery)return
notesSb.hitsPending=true
const seq=++notesSb.hitsSeq
notesSb.hitsTimer=setTimeout(()=>{
bridgeCall("notes.search_content",[q]).then((rows)=>{
if(seq!==notesSb.hitsSeq)return
notesSb.hits=new Map((rows||[]).map((r)=>[r.id,r.snippet||""]))
notesSb.hitsQuery=q
notesSb.hitsPending=false
notesSbRender({keepScroll:true})
}).catch(()=>{if(seq===notesSb.hitsSeq){notesSb.hitsPending=false;notesSbRender({keepScroll:true})}})
},now?0:220)
}
// ---- collapse
function notesSbSetCollapsed(it,closed){
if(notesSbPersisted(it.kind)){
if(closed)notesState.collapsed[it.key]=true;else delete notesState.collapsed[it.key]
bridgeCall("notes.set_group_collapsed",[it.key===NotesSidebar.UNGROUPED?"":it.key,closed]).catch(()=>{})
}else if(closed)notesSb.session[it.key]=true
else delete notesSb.session[it.key]
}
function notesSbToggle(it){
if(notesSb.model.searching||it.kind==="draft")return
notesSbSetCollapsed(it,!it.collapsed)
notesSb.cursor="h:"+it.key
notesSbRender({keepScroll:true})
}
function notesSbSetAllCollapsed(closed){
const keys=NotesSidebar.sectionKeys(notesSb.model.sections).filter((k)=>k!=="__draft__")
const kinds=new Map()
const walk=(s)=>{kinds.set(s.key,s.kind);s.children.forEach(walk)}
notesSb.model.sections.forEach(walk)
const persisted=keys.filter((k)=>notesSbPersisted(kinds.get(k)))
keys.forEach((k)=>{
const store=notesSbPersisted(kinds.get(k))?notesState.collapsed:notesSb.session
if(closed)store[k]=true;else delete store[k]
})
if(persisted.length)bridgeCall("notes.set_groups_collapsed",[persisted,closed]).catch(()=>{})
notesSbRender({resetScroll:closed})
}
// ---- menus
function notesSbCheck(on,label){return (on?"✓ ":"  ")+label}
function notesSbMenuAt(el,items){
const r=el.getBoundingClientRect()
openContextMenu(items,r.left,r.bottom+4)
}
function notesSbOpenSortMenu(btn){
const p=notesSb.prefs
const set=(sort)=>{
if(sort!==p.sort){
notesSbSetPref("sort",sort)
notesSbSetPref("dir",sort==="name"?"asc":"desc")
}
}
notesSbMenuAt(btn,[
{label:notesSbCheck(p.sort==="name","Name"),fn:()=>set("name")},
{label:notesSbCheck(p.sort==="edited","Last edited"),fn:()=>set("edited")},
{label:notesSbCheck(p.sort==="created","Created"),fn:()=>set("created")},
{sep:true},
{label:notesSbCheck(p.dir==="asc",p.sort==="name"?"A to Z":"Oldest first"),fn:()=>notesSbSetPref("dir","asc")},
{label:notesSbCheck(p.dir==="desc",p.sort==="name"?"Z to A":"Newest first"),fn:()=>notesSbSetPref("dir","desc")}
])
}
function notesSbOpenOptionsMenu(btn){
const p=notesSb.prefs
notesSbMenuAt(btn,[
{label:notesSbCheck(p.density==="comfortable","Comfortable rows"),fn:()=>notesSbSetPref("density","comfortable")},
{label:notesSbCheck(p.density==="compact","Compact rows"),fn:()=>notesSbSetPref("density","compact")},
{sep:true},
{label:notesSbCheck(p.nested,"Nest groups named Parent/Child"),fn:()=>notesSbSetPref("nested",!p.nested)},
{label:notesSbCheck(p.show_recent,"Show recently opened"),fn:()=>notesSbSetPref("show_recent",!p.show_recent)},
{sep:true},
{label:"Expand all",icon:"expand",fn:()=>notesSbSetAllCollapsed(false)},
{label:"Collapse all",icon:"shrink",fn:()=>notesSbSetAllCollapsed(true)},
{sep:true},
{label:"New Group...",icon:"folder",fn:notesCreateGroup}
])
}
function notesSbMovePinned(note,delta){
notesSb.data.pinned=NotesSidebar.moveBy(notesSb.data.pinned,note.id,delta)
notesSbRender({keepScroll:true})
bridgeCall("notes.reorder_pinned",[notesSb.data.pinned]).catch((err)=>showToast(err&&err.message?err.message:"Reorder failed","error"))
}
function notesSbOpenNoteMenu(note,x,y){
const pinned=notesSb.data.pinned
const at=pinned.indexOf(note.id)
const items=[
{label:"Open",icon:"file",fn:()=>notesOpen(note.id)},
{label:"Edit",icon:"edit",fn:()=>notesOpenEditNote(note.id)},
{label:note.pinned?"Unpin":"Pin",icon:"pin",fn:()=>notesTogglePinned(note)}
]
if(at>=0&&pinned.length>1){
items.push({label:"Move Up in Pinned",icon:"arrow-up",disabled:at===0,fn:()=>notesSbMovePinned(note,-1)})
items.push({label:"Move Down in Pinned",icon:"arrow-down",disabled:at===pinned.length-1,fn:()=>notesSbMovePinned(note,1)})
}
items.push({sep:true},
{label:"Move to Group...",icon:"folder",fn:()=>notesPickGroup(note.group_name,"Move Note",(g)=>notesMoveNote(note,g))},
{label:"Remove from Group",icon:"close",disabled:!note.group_name,fn:()=>notesMoveNote(note,"")},
{sep:true},
{label:"Delete",icon:"close",danger:true,fn:(e)=>notesDeleteNote(note,!!(e&&e.shiftKey))})
openContextMenu(items,x,y)
}
function notesSbNewNoteInGroup(group){
notesOpenNewNote()
// notesOpenNewNote resets the editor after a bridge call; set the group once the blank editor is up (a restored draft keeps its own group).
const started=Date.now()
const wait=()=>{
if(notesEditorOpen()){if(!notesState.editId&&!document.getElementById("notesEditorGroup").value)notesSetEditorGroup(group);return}
if(Date.now()-started<2000)setTimeout(wait,30)
}
if(group)wait()
}
function notesSbCreateSubGroup(parent){
notesPromptText("Create Sub-group","Name under "+parent,"","Create").then((name)=>{
if(!name)return
const full=NotesSidebar.pathParts(parent).concat(NotesSidebar.pathParts(name)).join("/")
bridgeCall("notes.create_group",[full]).then((g)=>notesAfterGroupChange(`Created group ${g||full}`)).catch((err)=>showToast(err&&err.message?err.message:"Create failed","error"))
})
}
function notesSbOpenHeadMenu(it,x,y,anchorEl){
if(it.kind==="draft"){
openContextMenu([{label:"Resume Draft",icon:"edit",fn:()=>notesApplyDraft(it.draft||notesState.draft,false)},{label:"Discard Draft",icon:"close",danger:true,fn:()=>notesDiscardDraft()}],x,y)
return
}
const all=[{label:"Expand all",icon:"expand",fn:()=>notesSbSetAllCollapsed(false)},{label:"Collapse all",icon:"shrink",fn:()=>notesSbSetAllCollapsed(true)}]
if(it.kind!=="group"){
openContextMenu([{label:it.collapsed?"Expand":"Collapse",icon:it.collapsed?"arrow-down":"arrow-up",fn:()=>notesSbToggle(it)},{sep:true}].concat(all),x,y)
return
}
const named=!!it.group
const items=[
{label:"New Note Here",icon:"add",fn:()=>notesSbNewNoteInGroup(it.group||"")},
{label:"New Group...",icon:"folder",fn:notesCreateGroup},
{label:"New Sub-group...",icon:"folder",disabled:!named||!notesSb.prefs.nested,fn:()=>notesSbCreateSubGroup(it.group)},
{sep:true},
{label:"Rename Group",icon:"edit",disabled:!named,fn:()=>notesSbStartRename(it)},
{label:"Colour and Icon...",icon:"color",fn:()=>notesSbOpenStylePopover(it,anchorEl||notesSb.els.get("h:"+it.key)||notesSbList())},
{sep:true}
].concat(all,[
{sep:true},
{label:"Delete Empty Group",icon:"trash",danger:true,disabled:!named||!it.real||it.count>0||it.hasChildren,fn:()=>notesDeleteGroup({group_name:it.group,label:it.group})}
])
openContextMenu(items,x,y)
}
function notesSbOpenMenu(it,x,y,anchorEl){
if(it.type==="row")notesSbOpenNoteMenu(it.note,x,y)
else if(it.type==="head")notesSbOpenHeadMenu(it,x,y,anchorEl)
else if(it.type==="draft")notesSbOpenHeadMenu({kind:"draft",draft:it.draft},x,y)
}
// ---- group colour and icon
function notesSbOpenStylePopover(it,anchorEl){
const pop=notesOpenPopover(anchorEl,236)
pop.classList.add("notes-sb-style-pop")
pop.style.width="236px"
const cur=()=>notesSb.prefs.group_styles[it.key]||{color:"",icon:""}
const save=(color,icon)=>{
bridgeCall("notes.set_group_style",[it.key===NotesSidebar.UNGROUPED?"":it.key,color,icon]).then((styles)=>{
notesSb.prefs=NotesSidebar.normPrefs(Object.assign({},notesSb.prefs,{group_styles:styles||{}}))
notesSbRender({keepScroll:true})
draw()
}).catch((err)=>showToast(err&&err.message?err.message:"Could not save the group style","error"))
}
const draw=()=>{
const st=cur()
const sw=NotesSidebar.COLORS.map((c)=>`<button type="button" class="notes-sb-swatch${st.color===c?" active":""}" data-color="${c}" style="--g:${c}" title="${c}" aria-label="Colour ${c}" aria-pressed="${st.color===c}"></button>`).join("")
const ic=NotesSidebar.ICONS.map((i)=>`<button type="button" class="notes-sb-iconpick${(st.icon||"folder")===i?" active":""}" data-icon="${i}" title="${i}" aria-label="Icon ${i}" aria-pressed="${(st.icon||"folder")===i}"><i class="icon icon-${i}"></i></button>`).join("")
pop.innerHTML=`<div class="notes-popover-title"></div><div class="notes-sb-swatches"><button type="button" class="notes-sb-swatch none${st.color?"":" active"}" data-color="" title="Default colour" aria-label="Default colour"></button>${sw}</div><div class="notes-sb-iconpicks">${ic}</div><div class="notes-popover-actions"><button type="button" data-reset="1">Reset</button><button type="button" class="notes-popover-confirm" data-done="1">Done</button></div>`
pop.querySelector(".notes-popover-title").textContent="Colour and icon: "+it.label
}
draw()
pop.addEventListener("click",(e)=>{
const b=e.target.closest("button")
if(!b)return
const st=cur()
if(b.dataset.color!==undefined)save(b.dataset.color,st.icon)
else if(b.dataset.icon)save(st.color,b.dataset.icon==="folder"?"":b.dataset.icon)
else if(b.dataset.reset)save("","")
else if(b.dataset.done)notesClosePopover()
})
}
// ---- inline rename
function notesSbStartRename(it){
if(it.kind!=="group"||!it.group)return
notesSb.renaming={key:it.key,group:it.group,label:it.label,done:false}
notesSbRender({keepScroll:true,keepRename:true})
const el=notesSb.els.get("h:"+it.key)
const input=el&&el.querySelector(".notes-head-rename")
if(!input){notesSb.renaming=null;return}
input.focus()
input.select()
const finish=(commit)=>{
const r=notesSb.renaming
if(!r||r.done)return
r.done=true
const value=NotesSidebar.norm(input.value)
notesSb.renaming=null
if(commit&&value&&value!==r.label)notesSbRenameGroup(r.group,r.label,value)
else notesSbRender({keepScroll:true})
notesSbList().focus()
}
input.addEventListener("keydown",(e)=>{
e.stopPropagation()
if(e.key==="Enter"){e.preventDefault();finish(true)}
else if(e.key==="Escape"){e.preventDefault();finish(false)}
})
input.addEventListener("blur",()=>finish(true))
;["click","dblclick","mousedown","contextmenu"].forEach((t)=>input.addEventListener(t,(e)=>e.stopPropagation()))
}
// Renames a group and, when it has sub-groups ("Parent/Child"), every group under it, one rename_group call each.
function notesSbRenameGroup(oldPath,oldLabel,newLabel){
const nested=notesSb.prefs.nested
const parts=nested?NotesSidebar.pathParts(oldPath):[oldPath]
const newPath=nested?parts.slice(0,-1).concat(NotesSidebar.pathParts(newLabel)).join("/"):newLabel
if(!newPath||newPath===oldPath){notesSbRender({keepScroll:true});return}
const names=notesGroupNames()
const jobs=[]
names.forEach((g)=>{
if(g.toLowerCase()===oldPath.toLowerCase())jobs.push([g,newPath])
else if(nested){
const to=NotesSidebar.renamedPath(g,oldPath,newPath)
if(to&&to!==g)jobs.push([g,to])
}
})
if(!jobs.length){notesSbRender({keepScroll:true});return}
const taken=new Set(names.map((g)=>g.toLowerCase()))
jobs.forEach((j)=>taken.delete(j[0].toLowerCase()))
if(jobs.some((j)=>taken.has(j[1].toLowerCase()))){showToast("A group with that name already exists.","error");notesSbRender({keepScroll:true});return}
let chain=Promise.resolve()
jobs.forEach((j)=>{chain=chain.then(()=>bridgeCall("notes.rename_group",[j[0],j[1]]))})
// A virtual parent ("CTF" of "CTF/HTB") is not a stored group, so its collapsed state is carried to the new name here.
const oldKey=oldPath.toLowerCase()
if(notesState.collapsed[oldKey]&&!jobs.some((j)=>j[0].toLowerCase()===oldKey))chain=chain.then(()=>bridgeCall("notes.set_groups_collapsed",[[oldKey],false])).then(()=>bridgeCall("notes.set_groups_collapsed",[[newPath],true]))
chain.then(()=>notesAfterGroupChange(`Renamed group to ${newPath}`)).catch((err)=>{showToast(err&&err.message?err.message:"Rename failed","error");notesRefreshLists()})
}
// ---- clicks
function notesSbItemFromEvent(e){
const el=e.target.closest&&e.target.closest("[data-i]")
if(!el||!notesSbList().parentElement.contains(el))return null
const it=notesSb.items[Number(el.dataset.i)]
return it?{it,el}:null
}
function notesSbOnClick(e){
const hit=notesSbItemFromEvent(e)
if(!hit){
const b=e.target.closest("[data-empty]")
if(!b)return
if(b.dataset.empty==="new")notesOpenNewNote()
else if(b.dataset.empty==="search")notesSbClearSearch()
else if(b.dataset.empty==="filters")notesSbSetPref("filters",[])
else if(b.dataset.empty==="content")notesSbSetPref("scopes",notesSb.prefs.scopes.concat("content"))
return
}
const it=hit.it
const act=e.target.closest("[data-act]")
if(act){
e.stopPropagation()
const r=act.getBoundingClientRect()
if(it.type==="row"){
if(act.dataset.act==="pin")notesTogglePinned(it.note)
else if(act.dataset.act==="edit")notesOpenEditNote(it.note.id)
else notesSbOpenNoteMenu(it.note,r.left,r.bottom+4)
}else if(it.type==="head"){
if(act.dataset.act==="add")notesSbNewNoteInGroup(it.group||"")
else notesSbOpenHeadMenu(it,r.left,r.bottom+4,hit.el)
}
return
}
if(it.type==="empty")return
notesSbSetCursor(notesSbItemKey(it))
notesSbActivate(it)
}
function notesSbOnStickyClick(){
const i=Number(document.getElementById("notesSbSticky").dataset.i)
if(i>=0&&i<notesSb.items.length){notesSbList().scrollTop=notesSb.lay.tops[i];notesSbWindow()}
}
function notesSbOnDblClick(e){
const hit=notesSbItemFromEvent(e)
if(!hit||e.target.closest("[data-act]"))return
if(hit.it.type==="row")notesOpenEditNote(hit.it.note.id)
}
function notesSbOnContextMenu(e){
const hit=notesSbItemFromEvent(e)
if(e.target.closest(".notes-head-rename"))return
e.preventDefault()
if(!hit){notesSbOpenOptionsMenuAt(e.clientX,e.clientY);return}
if(hit.it.type==="empty")return
notesSbSetCursor(notesSbItemKey(hit.it))
notesSbOpenMenu(hit.it,e.clientX,e.clientY,hit.el)
}
function notesSbOpenOptionsMenuAt(x,y){
openContextMenu([
{label:"New Note",icon:"add",fn:notesOpenNewNote},
{label:"New Group...",icon:"folder",fn:notesCreateGroup},
{sep:true},
{label:"Expand all",icon:"expand",fn:()=>notesSbSetAllCollapsed(false)},
{label:"Collapse all",icon:"shrink",fn:()=>notesSbSetAllCollapsed(true)}
],x,y)
}
// ---- drag and drop: a note onto a group moves it, onto Pinned pins it, and pinned notes reorder among themselves.
function notesSbDropTarget(e){
const d=notesSb.drag
const hit=notesSbItemFromEvent(e)
if(!d||!hit||hit.el.id==="notesSbSticky"&&hit.it.kind!=="group"&&hit.it.kind!=="pinned")return null
const it=hit.it
const kind=it.kind
if(kind==="pinned"){
if(it.type==="row"&&d.note.pinned){
if(it.note.id===d.note.id)return null
const r=hit.el.getBoundingClientRect()
return {type:"reorder",el:hit.el,toId:it.note.id,after:e.clientY>r.top+r.height/2}
}
if(d.note.pinned)return null
return {type:"pin",el:notesSb.els.get("h:"+NotesSidebar.PINNED)||hit.el}
}
if(kind!=="group"||notesSb.prefs.view!=="groups")return null
let head=it
if(it.type!=="head"){
head=null
for(let i=Number(hit.el.dataset.i);i>=0;i--){const x=notesSb.items[i];if(x.type==="head"&&x.key===it.section){head=x;break}}
if(!head)return null
}
const group=head.group||""
if(group.toLowerCase()===(d.note.group_name||"").toLowerCase())return null
return {type:"move",el:hit.el.id==="notesSbSticky"?hit.el:(notesSb.els.get("h:"+head.key)||hit.el),group,rowEl:it.type!=="head"?hit.el:null}
}
function notesSbClearDropMarks(){
notesSbList().parentElement.querySelectorAll(".drop,.drop-before,.drop-after,.drop-in").forEach((el)=>el.classList.remove("drop","drop-before","drop-after","drop-in"))
}
function notesSbOnDragStart(e){
const hit=notesSbItemFromEvent(e)
if(!hit||hit.it.type!=="row"||notesSb.renaming){e.preventDefault();return}
notesSb.drag={note:hit.it.note,el:hit.el}
try{e.dataTransfer.effectAllowed="move";e.dataTransfer.setData("text/plain",hit.it.note.note_name||"")}catch(err){}
hit.el.classList.add("dragging")
notesSbList().classList.add("dragging")
}
function notesSbOnDragOver(e){
if(!notesSb.drag)return
const list=notesSbList()
const box=list.getBoundingClientRect()
if(e.clientY<box.top+26)list.scrollTop-=12
else if(e.clientY>box.bottom-26)list.scrollTop+=12
const t=notesSbDropTarget(e)
notesSbClearDropMarks()
if(!t)return
e.preventDefault()
try{e.dataTransfer.dropEffect="move"}catch(err){}
if(t.type==="reorder")t.el.classList.add(t.after?"drop-after":"drop-before")
else{t.el.classList.add("drop");if(t.rowEl)t.rowEl.classList.add("drop-in")}
}
function notesSbOnDrop(e){
const d=notesSb.drag
const t=notesSbDropTarget(e)
notesSbEndDrag()
if(!d||!t)return
e.preventDefault()
if(t.type==="reorder"){
notesSb.data.pinned=NotesSidebar.reorder(notesSb.data.pinned,d.note.id,t.toId,t.after)
notesSbRender({keepScroll:true})
bridgeCall("notes.reorder_pinned",[notesSb.data.pinned]).catch((err)=>showToast(err&&err.message?err.message:"Reorder failed","error"))
}else if(t.type==="pin")notesTogglePinned(d.note)
else notesMoveNote(d.note,t.group)
}
function notesSbEndDrag(){
if(!notesSb.drag)return
if(notesSb.drag.el)notesSb.drag.el.classList.remove("dragging")
notesSb.drag=null
notesSbList().classList.remove("dragging")
notesSbClearDropMarks()
notesSbWindow()
}
// ---- init
function notesSbInit(){
const list=notesSbList()
const wrap=list.parentElement
const search=document.getElementById("notesSearchInput")
search.addEventListener("input",notesSbOnSearchInput)
search.addEventListener("keydown",notesSbSearchKeydown)
document.getElementById("notesSearchClear").addEventListener("click",()=>{notesSbClearSearch();search.focus()})
document.getElementById("notesSbScopes").addEventListener("click",(e)=>{
const b=e.target.closest("[data-scope]")
if(!b)return
const cur=notesSb.prefs.scopes
const next=cur.indexOf(b.dataset.scope)>=0?cur.filter((s)=>s!==b.dataset.scope):cur.concat(b.dataset.scope)
if(!next.length)return
notesSbSetPref("scopes",next)
})
const views=document.getElementById("notesSbViews")
views.addEventListener("click",(e)=>{
const b=e.target.closest("[data-view]")
if(b&&b.dataset.view!==notesSb.prefs.view){notesSb.cursor="";notesSbSetPref("view",b.dataset.view);notesSbList().scrollTop=0;notesSbWindow()}
})
views.addEventListener("keydown",(e)=>{
if(e.key!=="ArrowLeft"&&e.key!=="ArrowRight")return
e.preventDefault()
const order=NotesSidebar.VIEWS
const next=order[(order.indexOf(notesSb.prefs.view)+(e.key==="ArrowRight"?1:order.length-1))%order.length]
notesSbSetPref("view",next)
notesSbList().scrollTop=0
notesSbWindow()
const btn=views.querySelector(`[data-view="${next}"]`)
if(btn)btn.focus()
})
document.getElementById("notesSbFilters").addEventListener("click",(e)=>{
const b=e.target.closest("[data-filter]")
if(!b)return
const cur=notesSb.prefs.filters
notesSbSetPref("filters",cur.indexOf(b.dataset.filter)>=0?cur.filter((f)=>f!==b.dataset.filter):cur.concat(b.dataset.filter))
notesSbList().scrollTop=0
notesSbWindow()
})
document.getElementById("notesSbSort").addEventListener("click",(e)=>notesSbOpenSortMenu(e.currentTarget))
document.getElementById("notesSbOptions").addEventListener("click",(e)=>notesSbOpenOptionsMenu(e.currentTarget))
document.getElementById("notesSbToggleAll").addEventListener("click",(e)=>notesSbSetAllCollapsed(e.currentTarget.dataset.mode==="collapse"))
document.getElementById("notesSbJump").addEventListener("click",notesSbJumpToCurrent)
document.getElementById("notesSbSticky").addEventListener("click",notesSbOnStickyClick)
list.addEventListener("scroll",notesSbOnScroll,{passive:true})
list.addEventListener("click",notesSbOnClick)
list.addEventListener("dblclick",notesSbOnDblClick)
wrap.addEventListener("contextmenu",notesSbOnContextMenu)
list.addEventListener("keydown",notesSbListKeydown)
list.addEventListener("focus",()=>{if(!notesSb.cursor&&notesSb.items.length){const i=Math.max(NotesSidebar.rowIndex(notesSb.items,notesState.selectedId),NotesSidebar.firstStop(notesSb.items));if(i>=0)notesSbSetCursor(notesSbItemKey(notesSb.items[i]))}})
wrap.addEventListener("dragstart",notesSbOnDragStart)
wrap.addEventListener("dragover",notesSbOnDragOver)
wrap.addEventListener("drop",notesSbOnDrop)
wrap.addEventListener("dragend",notesSbEndDrag)
wrap.addEventListener("dragleave",(e)=>{if(!wrap.contains(e.relatedTarget))notesSbClearDropMarks()})
document.addEventListener("keydown",notesSbGlobalKeydown)
if(typeof ResizeObserver!=="undefined")new ResizeObserver(()=>{if(notesSb.loaded)notesSbWindow()}).observe(list)
else window.addEventListener("resize",()=>{if(notesSb.loaded)notesSbWindow()})
const side=document.getElementById("notesSidebar")
const handle=document.getElementById("notesSbResize")
initSidePanelResize({handle,panel:side,config:()=>({axis:"x",anchorSide:"left",min:notesSb.prefs.width_min,max:Math.min(notesSb.prefs.width_max,Math.max(notesSb.prefs.width_min,Math.round(window.innerWidth*0.5)))}),onCommit:(w)=>{if(w!==notesSb.prefs.width)notesSbSetPref("width",w)}})
handle.addEventListener("dblclick",()=>notesSbSetPref("width",280))
handle.addEventListener("keydown",(e)=>{
if(e.key!=="ArrowLeft"&&e.key!=="ArrowRight")return
e.preventDefault()
notesSbSetPref("width",NotesSidebar.clampWidth(notesSb.prefs.width+(e.key==="ArrowRight"?16:-16),notesSb.prefs.width_min,notesSb.prefs.width_max))
})
}
