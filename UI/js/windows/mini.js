let miniState={tab:"commands",cmds:[],favorites:[],favoritesOnly:false,cmdSearch:"",liveMap:{},liveName:"",targets:[],tgtSearch:"",liveTimer:null,dataSig:null,quickLoading:false,quickSaveTimer:null,quickWrap:true,quickMatches:[],quickMatchIndex:-1,onTop:false,collapsed:false,liveKey:"",locked:false,quickDirty:0,quickStash:null,activityAt:0}
// Also used inside attribute values (title="..."), so quotes must be escaped too: textContent->innerHTML leaves " as is.
function miniEscapeHtml(s){
return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")
}
function miniIterPlaceholders(text){
const t=String(text||"")
const out=[]
const keyRe=/^[A-Za-z_][A-Za-z0-9_ ]*$/
let i=0
const n=t.length
while(i<n){
if(t[i]!=="{"){i++;continue}
const start=i
let j=i+1,bad=false
while(j<n&&t[j]!=="}"){
if(t[j]==="{"||t[j]==="\r"||t[j]==="\n")bad=true
j++
}
if(j>=n)break
if(!bad){
const raw=t.slice(start+1,j).trim()
if(raw&&keyRe.test(raw))out.push([start,j+1,raw])
}
i=j+1
}
return out
}
function miniResolveCommand(cmd){
const s=(cmd||"").toString().trim()
if(!s)return ""
const map=miniState.liveMap
if(!map||Object.keys(map).length===0)return s
const spans=miniIterPlaceholders(s)
if(!spans.length)return s
let out="",last=0
spans.forEach(([start,end,key])=>{
out+=s.slice(last,start)
const lk=key.toLowerCase()
out+=Object.prototype.hasOwnProperty.call(map,lk)?map[lk]:"{"+key+"}"
last=end
})
out+=s.slice(last)
return out
}
function miniCompactCmd(cmd){
const raw=(cmd||"").toString().trim()
if(!raw)return ""
return raw.split(/\r?\n/).map((l)=>l.trim()).filter(Boolean).join(" ").replace(/\s+/g," ").trim()
}
function miniFavKey(n){
if(!n)return ""
const src=n.src||""
if(n.id!==undefined&&n.id!==null)return src+":"+n.id
if(n.command)return n.command.trim().toLowerCase()
if(n.title)return n.title.trim().toLowerCase()
return ""
}
function miniIsFav(n){
return miniState.favorites.indexOf(miniFavKey(n))!==-1
}
function miniTokenize(s){
return (s||"").toLowerCase().split(/[,\s]+/).filter(Boolean)
}
function miniMatch(n,tokens){
if(!tokens.length)return true
const blob=[n.title,n.category,n.sub,n.tags,n.command,n.description].join(" ").toLowerCase()
return tokens.every((t)=>blob.includes(t))
}
function miniFilteredCmds(){
const tokens=miniTokenize(miniState.cmdSearch)
const base=miniState.cmds.filter((n)=>miniMatch(n,tokens))
if(miniState.favoritesOnly)return base.filter((n)=>miniIsFav(n))
const favs=base.filter((n)=>miniIsFav(n))
const rest=base.filter((n)=>!miniIsFav(n))
return favs.concat(rest)
}
function miniCopy(text){
if(miniState.locked||!text)return
if(!navigator.clipboard){showToast("Could not copy.","error");return}
navigator.clipboard.writeText(text).then(()=>showToast("Copied","success",1200)).catch(()=>showToast("Could not copy.","error"))
}
function miniToggleFavorite(n){
const key=miniFavKey(n)
if(!key)return
const idx=miniState.favorites.indexOf(key)
if(idx===-1)miniState.favorites.push(key)
else miniState.favorites.splice(idx,1)
bridgeCall("save_settings",[{favorites:miniState.favorites}]).catch((err)=>console.error("save favorites failed",err))
miniRenderCmds()
}
function miniCmdMeta(n){
const parts=[]
const cat=(n.category||"").trim(),sub=(n.sub||"").trim(),tags=(n.tags||"").trim()
if(cat||sub)parts.push(`${cat||"Uncategorized"}/${sub||"General"}`)
if(tags)parts.push("tags: "+tags)
return parts.join(" | ")
}
function miniOpenRelatedNote(note){
if(!note||note.note_id===null||note.note_id===undefined){showToast("Related note not found.","error");return}
miniQuickSaveNow().then(()=>bridgeCall("window.restore_and_open_note",[note.note_id])).then((ok)=>{if(!ok)showToast("Could not open the note.","error")}).catch(()=>showToast("Could not open the note.","error"))
}
function miniOpenCmdMenu(n,x,y,viaKeyboard){
const copy={label:"Copy Command",icon:"copy",fn:()=>miniCopy(miniResolveCommand(n.command))}
const lookup=n.src==="Commands"?bridgeCall("search.related_notes",[n.raw||n]).catch(()=>[]):Promise.resolve([])
lookup.then((notes)=>{
notes=(notes||[]).filter((r)=>r&&r.note_id!==null&&r.note_id!==undefined)
let items
if(notes.length>1)items=notes.slice(0,6).map((r)=>({label:"Open: "+miniEscapeHtml(r.note_name||"Untitled"),icon:"file",fn:()=>miniOpenRelatedNote(r)}))
else items=[{label:"Open Related Note",icon:"file",disabled:!notes.length,fn:()=>miniOpenRelatedNote(notes[0])}]
items.push(copy)
openContextMenu(items,x,y)
if(viaKeyboard){const first=document.querySelector("#appContextMenu .app-context-menu-item:not(:disabled)");if(first)first.focus()}
})
}
function miniEmptyRow(tbody,cols,text){
const tr=document.createElement("tr")
tr.className="mini-empty-row"
const td=document.createElement("td")
td.colSpan=cols
td.textContent=text
tr.appendChild(td)
tbody.appendChild(tr)
}
function miniRenderCmds(){
const tbody=document.getElementById("miniCmdTableBody")
tbody.innerHTML=""
const rows=miniFilteredCmds()
if(!rows.length&&!miniState.locked)miniEmptyRow(tbody,3,miniState.cmds.length?(miniState.favoritesOnly&&!miniState.cmdSearch.trim()?"No favorite commands yet.":"No commands match your search."):"No commands yet. Add them in the main window.")
rows.forEach((n)=>{
const tr=document.createElement("tr")
tr.className="mini-cmd-row"
tr.tabIndex=0
const isFav=miniIsFav(n)
const resolved=miniResolveCommand(n.command)
const meta=miniCmdMeta(n)
tr.innerHTML=`<td class="mini-cmd-fav"><button type="button" class="mini-fav-toggle${isFav?" active":""}" title="Toggle favorite"><i class="icon ${isFav?"icon-star-filled":"icon-star"}"></i></button></td><td class="mini-cmd-title"${meta?` title="${miniEscapeHtml(meta)}"`:""}>${miniEscapeHtml(n.title||"Untitled")}</td><td class="mini-cmd-cmd" title="${miniEscapeHtml(resolved)}">${miniEscapeHtml(miniCompactCmd(resolved))}</td>`
tr.querySelector(".mini-fav-toggle").addEventListener("click",(e)=>{e.stopPropagation();miniToggleFavorite(n)})
tr.addEventListener("click",()=>miniCopy(miniResolveCommand(n.command)))
tr.addEventListener("contextmenu",(e)=>{e.preventDefault();miniOpenCmdMenu(n,e.clientX,e.clientY)})
tr.addEventListener("keydown",(e)=>{
if(e.target!==tr)return
if(e.key==="Enter"||e.key===" "){e.preventDefault();miniCopy(miniResolveCommand(n.command))}
else if(e.key==="ContextMenu"||(e.shiftKey&&e.key==="F10")){e.preventDefault();const r=tr.getBoundingClientRect();miniOpenCmdMenu(n,r.left+40,r.bottom,true)}
else miniRowArrowNav(e,tr)
})
tbody.appendChild(tr)
})
document.getElementById("miniCmdFavBtn").classList.toggle("active",miniState.favoritesOnly)
}
// Up/Down move between rows; Up from the first row goes back to the search box of that tab.
function miniRowArrowNav(e,tr){
if(e.key!=="ArrowDown"&&e.key!=="ArrowUp")return
e.preventDefault()
const next=e.key==="ArrowDown"?tr.nextElementSibling:tr.previousElementSibling
if(next){next.focus();return}
if(e.key==="ArrowUp"){const input=tr.closest(".mini-page").querySelector(".mini-input");if(input)input.focus()}
}
function miniSearchKeyNav(e){
if(e.key!=="ArrowDown")return
const row=e.target.closest(".mini-page").querySelector("tbody tr[tabindex]")
if(row){e.preventDefault();row.focus()}
}
function miniUpdateStatus(){
document.getElementById("miniStatusDot").classList.toggle("active",!!miniState.liveName)
document.getElementById("miniStatusTarget").textContent=miniState.liveName||"None"
document.getElementById("miniCollapsedLabel").textContent=miniState.liveName?"Live: "+miniState.liveName:"LOYA NG Mini"
}
function miniLiveKey(name,map){
return JSON.stringify([name||"",map||{}])
}
function miniRefreshLiveTarget(){
return bridgeCall("search.live_target").then((res)=>{
if(miniState.locked)return
const key=miniLiveKey(res.name,res.map)
if(key===miniState.liveKey)return
miniState.liveKey=key
miniState.liveMap=res.map||{}
miniState.liveName=res.name||""
miniUpdateStatus()
miniRenderCmds()
}).catch(()=>{})
}
function miniRefreshCmds(){
return bridgeCall("search.list").then((rows)=>{
miniState.cmds=(rows||[]).map((r)=>({id:r.id,src:r.src,note_id:r.note_id,title:r.title||r.cmd_note_title||r.note_name||"Untitled",category:r.category,sub:r.sub,tags:r.tags,command:r.command,description:r.description,raw:r}))
miniRenderCmds()
})
}
// T5/T6: ORIG polled for DB/Targets.json changes; reload only the half that changed.
function miniRefreshIfChanged(){
return bridgeCall("data_sig").then((sig)=>{
const prev=miniState.dataSig
miniState.dataSig=sig
if(!prev)return
if(prev.db!==sig.db)miniRefreshCmds().catch(()=>{})
if(prev.targets!==sig.targets)miniRefreshTargets().catch(()=>{})
}).catch(()=>{})
}
function miniLiveTick(){
return bridgeCall("security.is_locked").then((locked)=>{
if(locked){miniLock();return}
if(miniState.locked){miniUnlock();return}
miniRefreshLiveTarget()
miniRefreshIfChanged()
}).catch(()=>{})
}
// The app locked (usually the main window's idle timer) while Mini was open: hide every command, target and note, and keep
// unsaved Quick Space edits in memory only, so they are saved after unlocking instead of being refused and lost.
function miniLock(){
if(miniState.locked)return
miniState.locked=true
if(miniState.quickSaveTimer){clearTimeout(miniState.quickSaveTimer);miniState.quickSaveTimer=null}
const body=miniQuickBody()
if(miniState.quickDirty)miniState.quickStash={html:miniQuickCleanHtml(body),wrap:miniState.quickWrap}
if(miniQuickSearchOpen())miniQuickCloseSearch()
if(typeof closeContextMenu==="function")closeContextMenu()
body.innerHTML=""
document.getElementById("miniCmdTableBody").innerHTML=""
document.getElementById("miniTgtTableBody").innerHTML=""
miniState.cmds=[];miniState.targets=[];miniState.liveMap={};miniState.liveName="";miniState.liveKey="";miniState.dataSig=null
miniUpdateStatus()
document.body.classList.add("mini-locked")
document.getElementById("miniLockOverlay").classList.remove("hidden")
}
function miniUnlock(){
if(!miniState.locked)return
miniState.locked=false
document.body.classList.remove("mini-locked")
document.getElementById("miniLockOverlay").classList.add("hidden")
const stash=miniState.quickStash
miniState.quickStash=null
if(stash){
miniSetQuickHtml(miniQuickBody(),stash.html)
miniQuickSetWrap(stash.wrap,false)
miniQuickSaveNow()
}else miniQuickLoad()
miniRefreshCmds().catch(()=>{})
miniRefreshTargets().catch(()=>{})
miniRefreshLiveTarget()
miniRefreshIfChanged()
}
// Mini input counts as activity for the main window's auto-lock (Python throttles the hand-off).
function miniNoteActivity(){
const now=Date.now()
if(miniState.locked||now-miniState.activityAt<15000)return
miniState.activityAt=now
bridgeCall("window.activity").catch(()=>{})
}
function miniFilteredTargets(){
const tokens=miniTokenize(miniState.tgtSearch)
if(!tokens.length)return miniState.targets
return miniState.targets.filter((t)=>tokens.every((tok)=>(t.name||"").toLowerCase().includes(tok)))
}
function miniRenderTargets(){
const tbody=document.getElementById("miniTgtTableBody")
tbody.innerHTML=""
const rows=miniFilteredTargets()
if(!rows.length&&!miniState.locked)miniEmptyRow(tbody,2,miniState.targets.length?"No targets match your search.":"No targets in this profile yet.")
rows.forEach((t)=>{
const tr=document.createElement("tr")
tr.className="mini-tgt-row"
tr.tabIndex=0
const isLive=t.status==="live"
tr.innerHTML=`<td class="mini-tgt-name">${miniEscapeHtml(t.name)}</td><td class="mini-tgt-status ${isLive?"live":"not-used"}">${isLive?"Live":"Not Used"}</td>`
tr.title=isLive?"Click to stop using this target":"Click to use this target"
tr.addEventListener("click",()=>miniSetLiveTarget(t.id))
tr.addEventListener("keydown",(e)=>{
if(e.key==="Enter"||e.key===" "){e.preventDefault();miniSetLiveTarget(t.id)}
else miniRowArrowNav(e,tr)
})
tbody.appendChild(tr)
})
}
function miniSetLiveTarget(tid){
if(miniState.locked)return
bridgeCall("set_live_target",[tid]).then((targets)=>{
miniState.targets=targets
miniRenderTargets()
miniRefreshLiveTarget()
}).catch((err)=>showToast(err&&err.message?err.message:"Could not change the live target","error"))
}
function miniRefreshTargets(){
return bridgeCall("targets_list").then((targets)=>{
miniState.targets=targets
miniRenderTargets()
})
}
function miniQuickBody(){
return document.getElementById("miniQuickBody")
}
function miniSetSaveMark(on){
document.getElementById("miniSaveMark").classList.toggle("active",!!on)
}
// Find highlights (fallback <mark>s, paint wrappers) must never reach QuicSpace.json.
function miniQuickCleanHtml(body){
const clone=body.cloneNode(true)
clone.querySelectorAll("mark.mini-highlight,span.mini-find-wrap").forEach((m)=>{
const parent=m.parentNode
while(m.firstChild)parent.insertBefore(m.firstChild,m)
parent.removeChild(m)
})
clone.normalize()
return clone.innerHTML
}
function miniQuickSave(flash){
if(miniState.locked)return Promise.resolve(false)
const body=miniQuickBody()
const dirty=miniState.quickDirty
return bridgeCall("quick_space_save",[miniQuickCleanHtml(body),body.innerText,miniState.quickWrap]).then(()=>{
if(miniState.quickDirty===dirty)miniState.quickDirty=0
if(flash){miniSetSaveMark(true);setTimeout(()=>miniSetSaveMark(false),500)}
return true
}).catch((err)=>{
console.error("quick space save failed",err)
// Locked meanwhile: the next tick stashes the edits; anything else is a real failure the user must see.
if(!/locked/i.test(String(err&&err.message||err)))showToast("Quick Space was not saved.","error")
return false
})
}
function miniQuickSaveNow(){
if(miniState.quickLoading||miniState.locked)return Promise.resolve()
if(miniState.quickSaveTimer){clearTimeout(miniState.quickSaveTimer);miniState.quickSaveTimer=null}
return miniQuickSave(true)
}
function miniQuickSetWrap(on,save){
miniState.quickWrap=!!on
miniQuickBody().classList.toggle("nowrap",!miniState.quickWrap)
document.getElementById("miniQuickWrapBtn").classList.toggle("active",miniState.quickWrap)
if(save)miniQuickScheduleSave()
}
function miniQuickSyncFormatState(){
document.querySelectorAll(".mini-quick-toolbar .mini-tb-btn[data-cmd]").forEach((btn)=>{
let on=false
try{on=document.queryCommandState(btn.dataset.cmd)}catch(e){on=false}
btn.classList.toggle("active",!!on)
})
}
function miniQuickScheduleSave(){
if(miniState.quickLoading||miniState.locked)return
miniState.quickDirty++
if(miniState.quickSaveTimer)clearTimeout(miniState.quickSaveTimer)
miniState.quickSaveTimer=setTimeout(()=>{miniState.quickSaveTimer=null;miniQuickSave(true)},1000)
}
// Quick Space HTML comes back from QuicSpace.json, which a restored or imported backup can carry: it is parsed in an inert
// <template>, cleaned with the notes allow-list (NotesPro, render mode) and moved over - never assigned as innerHTML.
function miniSanitizeNode(node){
Array.from(node.childNodes).forEach((c)=>{
if(c.nodeType===3)return
if(c.nodeType!==1){c.remove();return}
const tag=String(c.tagName||"").toUpperCase()
const act=NotesPro.sanTagAction(tag,"render")
if(act==="drop"){c.remove();return}
if(act==="unwrap"){miniSanitizeNode(c);while(c.firstChild)node.insertBefore(c.firstChild,c);c.remove();return}
Array.from(c.attributes).forEach((a)=>{
const v=NotesPro.sanAttr(tag,a.name,a.value,"render")
if(v===null)c.removeAttribute(a.name)
else if(v!==a.value)c.setAttribute(a.name,v)
})
if(tag==="IMG"&&!(c.getAttribute("src")||"").trim()){c.remove();return}
miniSanitizeNode(c)
})
return node
}
function miniSetQuickHtml(el,html){
const tpl=document.createElement("template")
tpl.innerHTML=String(html||"")
miniSanitizeNode(tpl.content)
while(el.firstChild)el.removeChild(el.firstChild)
el.appendChild(tpl.content)
}
function miniQuickLoad(){
miniState.quickLoading=true
bridgeCall("quick_space_get").then((data)=>{
data=data||{}
if(data.html)miniSetQuickHtml(miniQuickBody(),data.html)
else if(data.text)miniQuickBody().textContent=data.text
miniQuickSetWrap(data.wrap!==false,false)
miniState.quickLoading=false
}).catch(()=>{miniState.quickLoading=false})
}
function miniQuickHasHighlightApi(){
return !!(window.CSS&&CSS.highlights&&typeof window.Highlight==="function")
}
// WebKitGTK does not invalidate the text when a highlight is removed or moved, so old marks stay on screen; flipping an
// invisible outline makes it repaint the whole editor.
function miniQuickRepaint(){
if(miniState.repaintQueued)return
miniState.repaintQueued=true
requestAnimationFrame(()=>{miniState.repaintQueued=false;miniQuickBody().classList.toggle("mini-repaint")})
}
function miniQuickClearHighlight(){
if(miniQuickHasHighlightApi()){CSS.highlights.delete("mini-find");CSS.highlights.delete("mini-find-current");miniQuickRepaint()}
const body=miniQuickBody()
if(body.querySelector("mark.mini-highlight")){
body.querySelectorAll("mark.mini-highlight").forEach((m)=>{
const parent=m.parentNode
while(m.firstChild)parent.insertBefore(m.firstChild,m)
parent.removeChild(m)
})
body.normalize()
}
miniState.quickMatches=[]
miniState.quickMatchIndex=-1
document.getElementById("miniQuickCount").textContent=""
}
// WebKitGTK never paints a ::highlight() on a text node whose parent is the contenteditable root itself (typed first lines are
// exactly that), so wrap such nodes in a plain <span>; the caret is put back and the wrappers are dropped from saved HTML.
function miniQuickWrapRootText(body){
const sel=window.getSelection()
const a=sel&&sel.rangeCount?sel.getRangeAt(0):null
const keep=a?{sc:a.startContainer,so:a.startOffset,ec:a.endContainer,eo:a.endOffset}:null
let changed=false
Array.from(body.childNodes).forEach((n)=>{
if(n.nodeType!==3||!n.nodeValue)return
const span=document.createElement("span")
span.className="mini-find-wrap"
body.insertBefore(span,n)
span.appendChild(n)
changed=true
})
if(changed&&keep&&body.contains(keep.sc)&&body.contains(keep.ec)){
try{const r=document.createRange();r.setStart(keep.sc,keep.so);r.setEnd(keep.ec,keep.eo);sel.removeAllRanges();sel.addRange(r)}catch(e){}
}
}
function miniQuickFindRanges(body,q){
const out=[]
if(!q)return out
const needle=q.toLowerCase()
const walker=document.createTreeWalker(body,NodeFilter.SHOW_TEXT,null)
let node
while((node=walker.nextNode())){
const low=node.nodeValue.toLowerCase()
let start=0,idx
while((idx=low.indexOf(needle,start))!==-1){
const r=document.createRange()
r.setStart(node,idx)
r.setEnd(node,idx+q.length)
out.push(r)
start=idx+Math.max(1,q.length)
}
}
return out
}
function miniQuickPaintCurrent(){
if(!miniQuickHasHighlightApi())return
CSS.highlights.delete("mini-find-current")
const r=miniState.quickMatches[miniState.quickMatchIndex]
if(r)CSS.highlights.set("mini-find-current",new Highlight(r))
miniQuickRepaint()
}
// Uses the CSS Custom Highlight API where available so the editable DOM is never touched; falls back to <mark>s.
function miniQuickHighlight(){
const prevIndex=miniState.quickMatchIndex
miniQuickClearHighlight()
const q=document.getElementById("miniQuickSearchInput").value
if(!q)return
const body=miniQuickBody()
// Wrap before collecting ranges: moving a text node collapses any Range inside it.
if(miniQuickHasHighlightApi())miniQuickWrapRootText(body)
const ranges=miniQuickFindRanges(body,q)
let matches=ranges
if(miniQuickHasHighlightApi()){
if(ranges.length)CSS.highlights.set("mini-find",new Highlight(...ranges))
}else{
matches=[]
ranges.slice().reverse().forEach((r)=>{
const mark=document.createElement("mark")
mark.className="mini-highlight"
try{r.surroundContents(mark);matches.unshift(mark)}catch(e){}
})
}
miniState.quickMatches=matches
miniState.quickMatchIndex=matches.length?Math.min(Math.max(prevIndex,0),matches.length-1):-1
miniQuickPaintCurrent()
miniQuickUpdateCount()
}
function miniQuickUpdateCount(){
const el=document.getElementById("miniQuickCount")
el.textContent=miniState.quickMatches.length?`${miniState.quickMatchIndex+1}/${miniState.quickMatches.length}`:"0/0"
}
function miniQuickMatchRange(m){
if(!m)return null
if(m instanceof Range)return m
const r=document.createRange()
r.selectNodeContents(m)
return r
}
function miniQuickMoveMatch(delta,select){
if(!miniState.quickMatches.length)miniQuickHighlight()
if(!miniState.quickMatches.length)return
miniState.quickMatchIndex=(miniState.quickMatchIndex+delta+miniState.quickMatches.length)%miniState.quickMatches.length
if(select){
const sel=window.getSelection()
sel.removeAllRanges()
sel.addRange(miniQuickMatchRange(miniState.quickMatches[miniState.quickMatchIndex]))
}
miniQuickScrollToCurrent()
miniQuickPaintCurrent()
miniQuickUpdateCount()
}
function miniQuickShowSearch(){
document.getElementById("miniQuickSearchBar").classList.remove("hidden")
const input=document.getElementById("miniQuickSearchInput")
input.focus()
input.select()
miniState.quickMatchIndex=-1
miniQuickHighlight()
miniQuickScrollToCurrent()
}
function miniQuickSearchOpen(){
return !document.getElementById("miniQuickSearchBar").classList.contains("hidden")
}
function miniQuickCloseSearch(){
document.getElementById("miniQuickSearchBar").classList.add("hidden")
document.getElementById("miniQuickSearchInput").value=""
miniQuickClearHighlight()
miniQuickBody().focus()
}
function miniQuickScrollToCurrent(){
const r=miniQuickMatchRange(miniState.quickMatches[miniState.quickMatchIndex])
if(!r)return
const el=r.startContainer.nodeType===1?r.startContainer:r.startContainer.parentElement
if(el&&el.scrollIntoView)el.scrollIntoView({block:"center"})
}
function miniQuickSearchInput(){
if(!document.getElementById("miniQuickSearchInput").value){miniQuickCloseSearch();return}
miniState.quickMatchIndex=-1
miniQuickHighlight()
miniQuickScrollToCurrent()
}
function miniWireQuickSpace(){
const body=miniQuickBody()
body.addEventListener("input",()=>{
if(miniState.quickLoading)return
miniQuickScheduleSave()
if(miniQuickSearchOpen()&&miniQuickHasHighlightApi())miniQuickHighlight()
})
document.querySelectorAll(".mini-quick-toolbar .mini-tb-btn[data-cmd]").forEach((btn)=>{
btn.addEventListener("mousedown",(e)=>e.preventDefault())
btn.addEventListener("click",()=>{body.focus();document.execCommand(btn.dataset.cmd,false,null);miniQuickSyncFormatState()})
})
document.addEventListener("selectionchange",()=>{if(miniState.tab==="quick")miniQuickSyncFormatState()})
document.getElementById("miniQuickWrapBtn").addEventListener("click",()=>miniQuickSetWrap(!miniState.quickWrap,true))
document.getElementById("miniQuickListBtn").addEventListener("click",()=>{body.focus();document.execCommand("insertUnorderedList",false,null)})
document.getElementById("miniQuickSaveBtn").addEventListener("click",miniQuickSaveNow)
document.getElementById("miniQuickFindBtn").addEventListener("click",miniQuickShowSearch)
document.getElementById("miniQuickSearchInput").addEventListener("input",miniQuickSearchInput)
document.getElementById("miniQuickSearchInput").addEventListener("keydown",(e)=>{if(e.key==="Enter"){e.preventDefault();miniQuickMoveMatch(e.shiftKey?-1:1)}})
document.getElementById("miniQuickPrev").addEventListener("click",()=>miniQuickMoveMatch(-1,true))
document.getElementById("miniQuickNext").addEventListener("click",()=>miniQuickMoveMatch(1,true))
document.getElementById("miniQuickSearchClose").addEventListener("click",miniQuickCloseSearch)
document.addEventListener("keydown",(e)=>{
const menu=document.getElementById("appContextMenu")
if(menu&&(e.key==="Escape"||e.key==="ArrowDown"||e.key==="ArrowUp")){
e.preventDefault()
if(e.key==="Escape"){closeContextMenu();return}
const items=[...menu.querySelectorAll(".app-context-menu-item:not(:disabled)")]
const i=items.indexOf(document.activeElement)
const next=items[(i+(e.key==="ArrowDown"?1:-1)+items.length)%items.length]
if(next)next.focus()
return
}
if(miniState.tab!=="quick")return
if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="f"){e.preventDefault();miniQuickShowSearch();return}
if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="s"){e.preventDefault();miniQuickSaveNow();return}
if(e.key==="Escape"&&miniQuickSearchOpen())miniQuickCloseSearch()
})
miniQuickLoad()
}
function miniSwitchTab(tab){
miniState.tab=tab
document.querySelectorAll(".mini-tab").forEach((t)=>t.classList.toggle("active",t.dataset.tab===tab))
document.querySelectorAll(".mini-page").forEach((p)=>p.classList.toggle("active",p.dataset.page===tab))
}
function miniWireChrome(){
const topbar=document.getElementById("miniTopbar")
let dragging=false,dragAnchorX=0,dragAnchorY=0
topbar.addEventListener("mousedown",(e)=>{
if(e.target.closest("button")||e.target.closest(".mini-tab"))return
dragging=true;dragAnchorX=e.clientX;dragAnchorY=e.clientY;e.preventDefault()
})
window.addEventListener("mousemove",(e)=>{
if(!dragging)return
bridgeCall("window.drag_to",[e.screenX-dragAnchorX,e.screenY-dragAnchorY])
})
window.addEventListener("mouseup",()=>{
if(dragging){dragging=false;bridgeCall("window.save_geometry").catch(()=>{})}
})
const handle=document.getElementById("miniResizeHandle")
let resizing=false,rx=0,ry=0,rBaseW=0,rBaseH=0
handle.addEventListener("mousedown",(e)=>{
resizing=false
rx=e.screenX;ry=e.screenY
bridgeCall("window.size").then((s)=>{rBaseW=s.w;rBaseH=s.h;resizing=true})
e.preventDefault()
})
window.addEventListener("mousemove",(e)=>{
if(!resizing)return
bridgeCall("window.resize_to",[rBaseW+(e.screenX-rx),rBaseH+(e.screenY-ry)])
})
window.addEventListener("mouseup",()=>{
if(resizing){resizing=false;bridgeCall("window.save_geometry").catch(()=>{})}
})
document.querySelectorAll(".mini-tab").forEach((t)=>t.addEventListener("click",()=>miniSwitchTab(t.dataset.tab)))
document.getElementById("miniCloseBtn").addEventListener("click",miniCloseApp)
document.getElementById("miniRestoreBtn").addEventListener("click",()=>{miniQuickSaveNow().then(()=>bridgeCall("window.restore")).catch(()=>{})})
document.getElementById("miniCollapseBtn").addEventListener("click",()=>miniSetCollapsed(!miniState.collapsed))
document.getElementById("miniPinBtn").addEventListener("click",()=>{
miniState.onTop=!miniState.onTop
bridgeCall("window.set_on_top",[miniState.onTop]).then(()=>miniApplyPin()).catch(()=>{})
})
}
// T4: ORIG saved Quick Space and quit the whole app; Python destroys Mini and the hidden main window.
function miniCloseApp(){
miniQuickSaveNow().catch(()=>{}).then(()=>bridgeCall("window.close",[true])).catch(()=>{})
}
function miniApplyPin(){
const btn=document.getElementById("miniPinBtn")
btn.classList.toggle("active",miniState.onTop)
btn.title=miniState.onTop?"Unpin (stop staying on top)":"Pin on top"
btn.setAttribute("aria-pressed",miniState.onTop?"true":"false")
}
function miniApplyCollapsed(){
const btn=document.getElementById("miniCollapseBtn")
document.body.classList.toggle("mini-collapsed",miniState.collapsed)
btn.title=miniState.collapsed?"Open preview":"Close preview"
btn.querySelector(".icon").className="icon "+(miniState.collapsed?"icon-arrow-down":"icon-arrow-up")
}
function miniSetCollapsed(on){
miniState.collapsed=!!on
miniApplyCollapsed()
return bridgeCall("window.set_collapsed",[miniState.collapsed]).catch(()=>{})
}
// Theme (dark/light/royal/system), accent and style all come from the main window's settings. They can change while Mini is
// hidden (it is only hidden when the main window is shown), so re-apply whenever Mini becomes visible again.
function miniApplyStyle(){
if(typeof themeApplyAll==="function")return themeApplyAll().catch(()=>{})
return bridgeCall("theme.style").then((s)=>{if(s&&(s.style==="glass"||s.style==="classic"))document.documentElement.dataset.style=s.style}).catch(()=>{})
}
function miniApplyChrome(){
return bridgeCall("window.chrome").then((c)=>{document.documentElement.classList.toggle("window-rounded",!!(c&&c.rounded))}).catch(()=>{})
}
function miniInit(){
miniApplyStyle()
miniApplyChrome()
bridgeCall("security.is_locked").then((locked)=>{
if(locked){bridgeCall("window.close",[false]).catch(()=>{});return}
miniInitUnlocked()
}).catch(()=>miniInitUnlocked())
}
function miniInitUnlocked(){
miniWireChrome()
document.getElementById("miniCmdSearch").addEventListener("input",(e)=>{miniState.cmdSearch=e.target.value;miniRenderCmds()})
document.getElementById("miniCmdFavBtn").addEventListener("click",()=>{
miniState.favoritesOnly=!miniState.favoritesOnly
bridgeCall("save_settings",[{favorites_only:miniState.favoritesOnly}]).catch(()=>{})
miniRenderCmds()
})
document.getElementById("miniTgtSearch").addEventListener("input",(e)=>{miniState.tgtSearch=e.target.value;miniRenderTargets()})
document.getElementById("miniCmdSearch").addEventListener("keydown",miniSearchKeyNav)
document.getElementById("miniTgtSearch").addEventListener("keydown",miniSearchKeyNav)
document.getElementById("miniLockUnlockBtn").addEventListener("click",()=>bridgeCall("window.restore").catch(()=>{}))
;["mousedown","keydown","wheel"].forEach((ev)=>document.addEventListener(ev,miniNoteActivity,{passive:true,capture:true}))
miniWireQuickSpace()
bridgeCall("settings").then((cfg)=>{
miniState.favorites=cfg.favorites||[]
miniState.favoritesOnly=!!cfg.favorites_only
miniState.onTop=!!cfg.always_on_top
miniApplyPin()
if(cfg.collapsed)miniSetCollapsed(true)
return Promise.all([miniRefreshCmds(),miniRefreshTargets(),miniRefreshLiveTarget()])
}).catch((err)=>console.error("mini init failed",err))
miniRefreshIfChanged()
window.addEventListener("focus",miniLiveTick)
document.addEventListener("visibilitychange",()=>{if(!document.hidden){miniApplyStyle();miniLiveTick()}})
if(window.matchMedia)window.matchMedia("(prefers-color-scheme: light)").addEventListener("change",()=>miniApplyStyle())
if(miniState.liveTimer)clearInterval(miniState.liveTimer)
miniState.liveTimer=setInterval(miniLiveTick,2500)
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",miniInit)
else miniInit()
