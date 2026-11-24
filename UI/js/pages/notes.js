let notesState={notes:[],groups:[],selectedId:null,openTabs:[],search:"",collapsed:{},editId:null,editOrigName:"",cmdCards:{},dirty:false,draftTimer:null,savedRange:null,draft:null,pendingAttachments:[],nameTouched:false,tagColors:{},editorTagList:[]}
const NOTES_MAX_TABS=8
function notesLoadTagColors(){
return bridgeCall("tags.colors").then((colors)=>{notesState.tagColors=colors||{}}).catch(()=>{})
}
function notesTagColor(tag){
return notesState.tagColors[(tag||"").toLowerCase()]||""
}
function notesTagPillStyle(tag){
const hex=notesTagColor(tag)
if(!hex)return ""
const rgb=notesHexToRgb(hex)
return `color:${hex};background:rgba(${Math.round(rgb.r)},${Math.round(rgb.g)},${Math.round(rgb.b)},0.16);border-color:rgba(${Math.round(rgb.r)},${Math.round(rgb.g)},${Math.round(rgb.b)},0.55)`
}
function notesTagTextStyle(tag){
const hex=notesTagColor(tag)
return hex?`color:${hex}`:""
}
// Escapes quotes too: the result is also placed inside HTML attributes (title, data-*, value). The old textContent/innerHTML
// trick left " unescaped, so a saved name like  " onmouseover="...  injected a handler with full bridge access.
function notesEscapeHtml(s){
return String(s===undefined||s===null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")
}
function notesSplitTags(s){
return (s||"").split(/[,;]/).map((t)=>t.trim()).filter(Boolean)
}
// Text of stored note HTML. Parsed in an inert DOMParser document: a div made with document.createElement belongs to the live
// page, so <img src=x onerror=...> in a note would run there (and reach the Python bridge) even though the div is never attached.
function notesInertText(html){
const doc=new DOMParser().parseFromString(String(html||""),"text/html")
return (doc.body&&doc.body.textContent)||""
}
function notesPlainTextFromHtml(html){
return notesInertText(html).replace(/\s+/g," ").trim()
}
function notesDoSummarize(){
const note=notesState.selectedNote
if(!note)return
const plain=notesPlainTextFromHtml(note.content_html).slice(0,6000)
if(!plain){showToast("This note has no content to summarize","error");return}
const prompt=`You are summarizing a pentest engagement note titled "${note.note_name}" for quick reference. Base the summary ONLY on the content below - do not invent details that aren't there. Keep it tight, no filler sentences. Use exactly this structure, omitting any section that has nothing to report:

**Key Findings:** (most severe first, one line each)
**Affected Targets/Assets:** (hosts, URLs, ports, services actually named in the note)
**Next Steps:** (concrete, actionable items only)

---
${plain}
---`
aiOpenPanel().then(()=>aiSendExternalPrompt(prompt)).catch((err)=>showToast(err&&err.message?err.message:"Summarize failed","error"))
}
function notesRenderTagSuggestions(replyText){
const wrap=document.getElementById("notesTagSuggestions")
const tags=(replyText||"").split(/[,\n]/).map((t)=>t.trim().toLowerCase().replace(/^[-*\d.\s]+/,"")).filter(Boolean).slice(0,6)
if(!tags.length){wrap.classList.add("hidden");wrap.innerHTML="";return}
wrap.innerHTML=tags.map((t)=>`<button type="button" class="notes-tag-chip" data-tag="${notesEscapeHtml(t)}">+ ${notesEscapeHtml(t)}</button>`).join("")
wrap.classList.remove("hidden")
wrap.querySelectorAll(".notes-tag-chip").forEach((btn)=>{
btn.addEventListener("click",()=>{
const existing=notesEditorTagsArray()
if(!existing.some((t)=>t.toLowerCase()===btn.dataset.tag.toLowerCase()))existing.push(btn.dataset.tag)
notesSetEditorTags(existing)
notesMarkDirty()
btn.remove()
if(!wrap.querySelector(".notes-tag-chip"))wrap.classList.add("hidden")
})
})
}
function notesDoSuggestTags(){
const body=document.getElementById("notesEditorBody")
const plain=notesPlainTextFromHtml(body.innerHTML).slice(0,4000)
if(!plain){showToast("Write some note content first","error");return}
const btn=document.getElementById("notesTagSuggestBtn")
btn.disabled=true
const prompt=`Suggest 2-4 short, lowercase tags for this pentest note based on its content. Reply with ONLY a comma-separated list of tags, nothing else - no explanation.\n\n---\n${plain}\n---`
aiOpenPanel().then(()=>aiSendExternalPrompt(prompt)).then((replyText)=>{
notesRenderTagSuggestions(replyText)
}).catch((err)=>showToast(err&&err.message?err.message:"Tag suggestion failed","error")).finally(()=>{btn.disabled=false})
}
// Matches the original: the note name or its group (plus NG's tags), not the body.
function notesDeleteNote(note,skipConfirm){
const doDelete=()=>{
bridgeCall("notes.delete",[note.id]).then(()=>{
const wasActive=notesState.selectedId===note.id
const idx=notesTabIndex(note.id)
if(idx>=0)notesState.openTabs.splice(idx,1)
if(wasActive){
const next=notesState.openTabs[idx]||notesState.openTabs[idx-1]
if(next){
notesState.selectedId=next
}else{
notesState.selectedId=null
notesState.selectedNote=null
notesShowEditor(false)
notesSetViewerMode("empty")
}
}
return notesRefreshLists().then(()=>{
if(wasActive&&notesState.selectedId)return bridgeCall("notes.get",[notesState.selectedId]).then(notesRenderViewer)
})
}).then(()=>showToast("Note moved to Recycle Bin")).catch((err)=>showToast(err&&err.message?err.message:"Delete failed","error"))
}
if(skipConfirm){doDelete();return}
appConfirm(`Delete note "${note.note_name}"? This moves it to the Recycle Bin.`,{okLabel:"Delete",danger:true}).then((yes)=>{if(yes)doDelete()})
}
// Group Manager (original Note.py _rename_selected_group/_move_selected_note/_delete_selected_empty_group/_nav_create_group).
function notesGroupNames(){
return Array.from(new Set(notesState.groups.filter((g)=>g.group_name&&g.group_name!=="__pinned__").map((g)=>g.label))).sort((a,b)=>a.localeCompare(b))
}
function notesAfterGroupChange(msg){
return notesRefreshLists().then(()=>{
if(msg)showToast(msg)
if(notesState.selectedId&&document.getElementById("notesEditor").classList.contains("hidden"))return bridgeCall("notes.get",[notesState.selectedId]).then(notesRenderViewer).catch(()=>{})
})
}
function notesMoveNote(note,group){
const target=(group||"").trim()
if(target.toLowerCase()===(note.group_name||"").toLowerCase()&&target===(note.group_name||""))return
bridgeCall("notes.move_note",[note.id,target]).then(()=>notesAfterGroupChange(target?`Moved note to ${target}`:"Removed note from group")).catch((err)=>showToast(err&&err.message?err.message:"Move failed","error"))
}
function notesPromptText(title,label,initial,okLabel){
return new Promise((resolve)=>{
const el=document.createElement("div")
el.className="notes-picker-modal glass-panel"
el.innerHTML=`<div class="notes-popover-title"></div><div class="notes-popover-field"><label></label><input type="text" id="notesPromptInput" autocomplete="off"></div><div class="notes-popover-error hidden" id="notesPromptErr"></div><div class="notes-popover-actions"><button type="button" id="notesPromptCancel">Cancel</button><button type="button" class="notes-popover-confirm" id="notesPromptOk"></button></div>`
el.querySelector(".notes-popover-title").textContent=title
el.querySelector("label").textContent=label
el.querySelector("#notesPromptOk").textContent=okLabel||"OK"
let done=false
const finish=(v)=>{if(done)return;done=true;closeModal(true);resolve(v)}
openModal(el,{onBeforeClose:()=>{if(!done){done=true;resolve(null)}return true}})
const input=el.querySelector("#notesPromptInput")
input.value=initial||""
const ok=()=>{const v=input.value.trim();if(!v){const err=el.querySelector("#notesPromptErr");err.textContent=`${label} is required.`;err.classList.remove("hidden");return}finish(v)}
el.querySelector("#notesPromptOk").addEventListener("click",ok)
el.querySelector("#notesPromptCancel").addEventListener("click",()=>finish(null))
input.addEventListener("keydown",(e)=>{if(e.key==="Enter"){e.preventDefault();ok()}})
input.focus();input.select()
})
}
function notesCreateGroup(){
notesPromptText("Create Group","Group name","","Create").then((name)=>{
if(!name)return
bridgeCall("notes.create_group",[name]).then((g)=>notesAfterGroupChange(`Created group ${g||name}`)).catch((err)=>showToast(err&&err.message?err.message:"Create failed","error"))
})
}
function notesDeleteGroup(g){
appConfirm(`Delete empty group: ${g.label}?`,{okLabel:"Delete",danger:true}).then((yes)=>{
if(!yes)return
bridgeCall("notes.delete_group",[g.group_name]).then(()=>notesAfterGroupChange(`Deleted empty group: ${g.label}`)).catch((err)=>showToast(err&&err.message?err.message:"Delete failed","error"))
})
}
function notesStripHtmlPreview(html){
return notesInertText(html).trim().slice(0,160)
}
function notesDiscardDraft(){
bridgeCall("notes.draft_clear").catch(()=>{})
notesState.draft=null
notesRenderGroups()
}
function notesTogglePinned(note){
const next=!note.pinned
bridgeCall("notes.set_pinned",[note.id,note.note_name,next]).then(()=>{
note.pinned=next
if(notesState.selectedNote&&notesState.selectedNote.id===note.id){
notesState.selectedNote.pinned=next
notesUpdatePinButton(next)
}
notesRefreshLists()
}).catch((err)=>showToast(err&&err.message?err.message:"Pin failed","error"))
}
function notesUpdatePinButton(pinned){
const btn=document.getElementById("notesPinBtn")
if(!btn)return
btn.classList.toggle("active",!!pinned)
btn.title=pinned?"Unpin note":"Pin note"
const label=btn.querySelector("span")
if(label)label.textContent=pinned?"Unpin":"Pin"
}
function notesTagChipsHtml(tags,maxCount,expandable){
if(!tags.length)return ""
const shown=tags.slice(0,maxCount)
const rest=tags.slice(maxCount)
let html=shown.map((t)=>`<span class="notes-item-tag" style="${notesTagPillStyle(t)}">${notesEscapeHtml(t)}</span>`).join("")
if(rest.length){
const label=`+${rest.length}`
if(expandable){
html+=`<button type="button" class="notes-item-tag notes-tag-more">${label}</button>`
}else{
html+=`<span class="notes-item-tag notes-tag-more" title="${notesEscapeHtml(rest.join(", "))}">${label}</span>`
}
}
return html
}
// The sidebar list is drawn by notes_sidebar.js (virtual list); every caller that changed the selection, the draft or the data lands here.
function notesRenderGroups(){
notesSbRender()
}
function notesRefreshLists(){
// One bridge call (notes.sidebar) carries the notes, groups, pinned order, recents and sidebar preferences: a single DB read per refresh.
return Promise.all([bridgeCall("notes.sidebar"),notesLoadTagColors()]).then((results)=>{
notesSbSetData(results[0])
const liveIds=new Set(notesState.notes.map((n)=>n.id))
notesState.openTabs=notesState.openTabs.filter((id)=>liveIds.has(id))
notesRenderGroups()
notesRenderTabStrip()
})
}
function notesSetViewerMode(mode){
document.getElementById("notesViewerEmpty").classList.toggle("hidden",mode!=="empty")
document.getElementById("notesViewerContent").classList.toggle("hidden",mode!=="view")
}
function notesShowEditor(show){
const was=notesEditorOpen()
document.getElementById("notesEditor").classList.toggle("hidden",!show)
if(was&&!show){if(notesFindState.open)notesFindClose();notesPhScheduleRefresh();notesProOnEditorClosed()}
}
function notesRenderViewerTagsState(tagsWrap,viewerTags,expanded){
if(expanded){
const chips=viewerTags.map((t)=>`<span class="notes-item-tag" style="${notesTagPillStyle(t)}">${notesEscapeHtml(t)}</span>`).join("")
tagsWrap.innerHTML=chips+'<button type="button" class="notes-item-tag notes-tag-more" id="notesViewerTagsLess">Show less</button>'
const lessBtn=tagsWrap.querySelector("#notesViewerTagsLess")
if(lessBtn)lessBtn.addEventListener("click",()=>notesRenderViewerTagsState(tagsWrap,viewerTags,false))
}else{
tagsWrap.innerHTML=notesTagChipsHtml(viewerTags,6,true)
const moreBtn=tagsWrap.querySelector(".notes-tag-more")
if(moreBtn)moreBtn.addEventListener("click",()=>notesRenderViewerTagsState(tagsWrap,viewerTags,true))
}
}
function notesRenderViewer(note){
notesState.selectedId=note.id
notesState.selectedNote=note
notesShowEditor(false)
notesSetViewerMode("view")
document.getElementById("notesViewerTitle").textContent=note.note_name
document.getElementById("notesViewerGroup").textContent=note.group_name||"Ungrouped"
document.getElementById("notesViewerUpdated").textContent="Updated "+note.updated_label
notesUpdatePinButton(!!note.pinned)
const tagsWrap=document.getElementById("notesViewerTags")
const viewerTags=notesSplitTags(note.tags)
notesRenderViewerTagsState(tagsWrap,viewerTags,false)
const body=document.getElementById("notesViewerBody")
notesFindClose()
notesProSetHtml(body,note.content_html)
notesProDecorate(body)
notesDecorateAttachmentChips(body)
notesWireAttachmentChips(body,"view")
// CVE ids become links to the CVE Intel card. Viewer only: the editor and the saved note are never touched.
if(typeof cveLinkify==="function")cveLinkify(body)
body.querySelectorAll(".cmd-card-copy").forEach((btn)=>{
btn.addEventListener("click",()=>{
const card=btn.closest(".cmd-card")
const code=card?card.querySelector(".cmd-card-code"):null
if(code&&navigator.clipboard)navigator.clipboard.writeText(code.textContent||"").then(()=>showToast("Command copied")).catch(()=>{})
})
})
const linksToIds=[];const linksToSeen=new Set()
body.querySelectorAll(".note-link[data-note-id]").forEach((a)=>{
const nid=parseInt(a.dataset.noteId,10)
if(isNaN(nid)||linksToSeen.has(nid))return
linksToSeen.add(nid);linksToIds.push(nid)
})
const linksToList=document.getElementById("notesLinksToList")
linksToList.innerHTML=""
document.getElementById("notesLinksToSection").classList.toggle("hidden",linksToIds.length===0)
linksToIds.forEach((nid)=>{
const target=notesState.notes.find((n)=>n.id===nid)
const btn=document.createElement("button")
btn.className="notes-linked-item"
btn.innerHTML=`<i class="icon icon-edit"></i><span>${notesEscapeHtml(target?target.note_name:"Unknown note")}</span>`
btn.addEventListener("click",()=>notesOpen(nid))
linksToList.appendChild(btn)
})
const linkedList=document.getElementById("notesLinkedList")
linkedList.innerHTML=""
document.getElementById("notesLinkedSection").classList.toggle("hidden",note.linked.length===0)
note.linked.forEach((l)=>{
const btn=document.createElement("button")
btn.className="notes-linked-item"
btn.innerHTML=`<i class="icon icon-edit"></i><span>${notesEscapeHtml(l.note_name)}</span>`
btn.addEventListener("click",()=>notesOpen(l.id))
linkedList.appendChild(btn)
})
notesRenderGroups()
notesPhScheduleRefresh()
}
// N7: a note's links must never navigate the app window (the page is a file:// URL). Note links open the note, cmd: anchors copy, web/mail links go to the system browser.
function notesDecodeCmdToken(token){
try{
const b=(token||"").replace(/-/g,"+").replace(/_/g,"/")
const raw=atob(b+"===".slice((b.length+3)%4))
const bytes=Uint8Array.from(raw,(c)=>c.charCodeAt(0))
const d=JSON.parse(new TextDecoder("utf-8").decode(bytes))
return d&&typeof d==="object"?d:{}
}catch(e){return {}}
}
// A cmd: link copies the command in its href. That must be exactly what the reader sees: the link text, or the command card
// drawn from the same token (cmdcard:<token>). An imported note could otherwise show "ls" and put "rm -rf ~" on the clipboard.
// Returns the command to copy, "" when there is none, or null when the href and what is shown disagree.
function notesCmdLinkCopyText(href,shownText,imgSrc){
const tok=String(href||"").replace(/^cmd[a-z]*:(edit:|copy:)?/i,"")
const d=notesDecodeCmdToken(tok)
if(!d.command)return ""
const norm=(t)=>String(t||"").replace(/\s+/g," ").trim()
const cardTok=String(imgSrc||"").replace(/^cmdcard:/i,"")
if(cardTok&&cardTok===tok&&!norm(shownText))return d.command
return norm(shownText)===norm(d.command)?d.command:null
}
function notesHandleLinkClick(a,e,allowOpen){
e.preventDefault()
if(!allowOpen)return
if(a.dataset.noteId){notesOpen(parseInt(a.dataset.noteId,10));return}
const href=(a.getAttribute("href")||"").trim()
if(/^notelink:/i.test(href)){
const d=notesDecodeCmdToken(href.slice(9))
const hit=notesState.notes.find((n)=>n.id===d.note_id)||notesState.notes.find((n)=>(n.note_name||"").toLowerCase()===(d.note_name||"").toLowerCase())
if(hit)notesOpen(hit.id);else showToast("Note not found: "+(d.note_name||""),"error")
return
}
if(/^cmd/i.test(href)){
const img=a.querySelector("img[src^='cmdcard:']")
const cmd=notesCmdLinkCopyText(href,a.textContent,img?img.getAttribute("src"):"")
if(cmd===null){showToast("Not copied: this link's command is not the text it shows","error");return}
if(cmd&&navigator.clipboard)navigator.clipboard.writeText(cmd).then(()=>showToast("Command copied")).catch(()=>{})
return
}
if(/^(https?:|mailto:)/i.test(href))bridgeCall("notes.open_url",[href]).catch((err)=>showToast(err&&err.message?err.message:"Could not open link","error"))
}
function notesWireLinkGuards(){
// A blocked remote image (see notesProBlockRemoteImg) loads only when the user clicks it.
;[document.getElementById("notesViewerBody"),notesEditorBody()].forEach((el)=>el.addEventListener("click",(e)=>{
const img=e.target&&e.target.closest?e.target.closest("img.note-remote-blocked"):null
if(img&&notesProLoadRemoteImg(img)){e.preventDefault();e.stopPropagation()}
},true))
document.getElementById("notesViewerBody").addEventListener("click",(e)=>{
const a=e.target.closest("a")
if(a)notesHandleLinkClick(a,e,true)
})
// In the editor a plain click only places the caret; Ctrl+click follows the link.
notesEditorBody().addEventListener("click",(e)=>{
const a=e.target.closest("a")
if(a)notesHandleLinkClick(a,e,e.ctrlKey||e.metaKey)
})
;[document.getElementById("notesViewerBody"),notesEditorBody()].forEach((el)=>el.addEventListener("auxclick",(e)=>{if(e.target.closest("a"))e.preventDefault()}))
}
function notesOpenGraphModal(){
const el=document.createElement("div")
el.className="notes-graph-modal glass-panel"
el.innerHTML=`<div class="notes-popover-title">Note Graph</div><div class="notes-graph-wrap" id="notesGraphWrap"><div class="notes-empty-msg">Loading...</div></div><div class="notes-popover-actions"><button type="button" id="notesGraphClose">Close</button></div>`
openModal(el)
el.querySelector("#notesGraphClose").addEventListener("click",closeModal)
bridgeCall("notes.graph").then((data)=>notesRenderGraph(el,data)).catch((err)=>{
el.querySelector("#notesGraphWrap").innerHTML=`<div class="notes-empty-msg">${notesEscapeHtml(err&&err.message?err.message:"Failed to load graph")}</div>`
})
}
function notesRenderGraph(el,data){
const wrap=el.querySelector("#notesGraphWrap")
const nodes=data.nodes||[]
if(!nodes.length){wrap.innerHTML='<div class="notes-empty-msg">No notes yet</div>';return}
const w=560,h=420,cx=w/2,cy=h/2,r=Math.min(cx,cy)-50
const pos={}
nodes.forEach((n,i)=>{
const a=(i/nodes.length)*Math.PI*2-Math.PI/2
pos[n.id]={x:cx+r*Math.cos(a),y:cy+r*Math.sin(a)}
})
const edgeLines=(data.edges||[]).map((e)=>{
const a=pos[e.source],b=pos[e.target]
if(!a||!b)return ""
return `<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" class="notes-graph-edge"></line>`
}).join("")
const nodeGroups=nodes.map((n)=>{
const p=pos[n.id]
const label=n.note_name.length>16?n.note_name.slice(0,15)+"…":n.note_name
return `<g class="notes-graph-node" data-id="${n.id}"><circle cx="${p.x}" cy="${p.y}" r="9"></circle><text x="${p.x}" y="${p.y+22}" text-anchor="middle">${notesEscapeHtml(label)}</text></g>`
}).join("")
wrap.innerHTML=`<svg viewBox="0 0 ${w} ${h}" class="notes-graph-svg">${edgeLines}${nodeGroups}</svg>`
wrap.querySelectorAll(".notes-graph-node").forEach((g)=>{
g.addEventListener("click",()=>{
closeModal()
notesOpen(parseInt(g.dataset.id,10))
})
})
}
function notesTabIndex(id){
return notesState.openTabs.indexOf(id)
}
function notesRenderTabStrip(){
const strip=document.getElementById("notesTabStrip")
if(!strip)return
if(notesState.openTabs.length<=1){strip.classList.add("hidden");strip.innerHTML="";return}
strip.classList.remove("hidden")
strip.innerHTML=notesState.openTabs.map((id)=>{
const n=notesState.notes.find((x)=>x.id===id)
const name=n?n.note_name:"..."
const active=id===notesState.selectedId
return `<button type="button" class="notes-tab${active?" active":""}" data-id="${id}" title="${notesEscapeHtml(name)}"><span class="notes-tab-label">${notesEscapeHtml(name)}</span><span class="notes-tab-close" data-close="${id}">&times;</span></button>`
}).join("")
strip.querySelectorAll(".notes-tab").forEach((tabEl)=>{
tabEl.addEventListener("click",(e)=>{
if(e.target.closest(".notes-tab-close"))return
notesOpen(parseInt(tabEl.dataset.id,10))
})
})
strip.querySelectorAll(".notes-tab-close").forEach((btn)=>{
btn.addEventListener("click",(e)=>{
e.stopPropagation()
notesCloseTab(parseInt(btn.dataset.close,10))
})
})
}
function notesCloseTab(id){
const idx=notesTabIndex(id)
if(idx<0)return
notesState.openTabs.splice(idx,1)
if(notesState.selectedId===id){
const next=notesState.openTabs[idx]||notesState.openTabs[idx-1]
if(next){
notesOpen(next)
return
}
notesState.selectedId=null
notesState.selectedNote=null
notesShowEditor(false)
notesSetViewerMode("empty")
}
notesRenderTabStrip()
notesRenderGroups()
}
function notesOpen(id){
if(notesEditorOpen()&&notesState.dirty){notesConfirmLeaveEditor().then((r)=>{if(r===true){notesCancelEdit();notesOpenNow(id)}else if(r==="saved")notesOpenNow(id)});return}
notesOpenNow(id)
}
function notesOpenNow(id){
if(id===null||id===undefined)return
if(notesTabIndex(id)<0){
notesState.openTabs.push(id)
if(notesState.openTabs.length>NOTES_MAX_TABS)notesState.openTabs.shift()
}
notesState.selectedId=id
notesRenderGroups()
notesRenderTabStrip()
bridgeCall("notes.touch_recent",[id]).catch(()=>{})
bridgeCall("notes.get",[id]).then(notesRenderViewer).catch((err)=>console.error("note load failed",err))
}
function notesCardKey(cmd){
return [cmd.cmd_note_title||"",cmd.category||"",cmd.sub_category||"",cmd.description||"",cmd.tags||"",cmd.command||""].join("|")
}
function notesGenCid(){
return "new-"+Math.random().toString(36).slice(2,10)
}
function notesCmdCardAlignClass(align){
return align==="left"||align==="center"||align==="right"?` cmd-card-align-${align}`:""
}
const COMMAND_TYPE_OPTIONS=["Linux Shell","PowerShell","CMD","SQL","Other"]
const NOTES_TAG_COLOR_PRESETS=["#ef4444","#f97316","#eab308","#22c55e","#14b8a6","#3b82f6","#6366f1","#a855f7","#ec4899","#64748b","#84cc16","#06b6d4"]
function notesCmdTypeSlug(t){
return (t||"").toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-+|-+$/g,"")||"other"
}
function notesCmdTypeBadgeHtml(type){
const t=type||"other"
return `<span class="cmd-card-type cmd-card-type-${notesCmdTypeSlug(t)}">${notesEscapeHtml(t)}</span>`
}
function notesRenderCmdCardEmbed(cid,data){
const el=document.createElement("div")
const align=data.align||""
el.className="cmd-card cmd-card-embed"+notesCmdCardAlignClass(align)
el.setAttribute("contenteditable","false")
el.draggable=true
el.dataset.cid=cid
const meta=[data.category,data.sub_category].filter(Boolean).join(" / ")
el.innerHTML=`<div class="cmd-card-head"><span class="cmd-card-grip" title="Drag to move"><i class="icon icon-grip"></i></span><span class="cmd-card-title">${notesEscapeHtml(data.cmd_note_title||"Command")}</span>${notesCmdTypeBadgeHtml(data.command_type)}${meta?`<span class="cmd-card-meta">${notesEscapeHtml(meta)}</span>`:""}<span class="cmd-card-actions"><button type="button" class="cmd-card-align-btn${align==="left"?" active":""}" data-align="left" title="Align left"><i class="icon icon-align-left"></i></button><button type="button" class="cmd-card-align-btn${align==="center"?" active":""}" data-align="center" title="Align center"><i class="icon icon-align-center"></i></button><button type="button" class="cmd-card-align-btn${align==="right"?" active":""}" data-align="right" title="Align right"><i class="icon icon-align-right"></i></button><button type="button" class="cmd-card-copy" title="Copy command">Copy</button><button type="button" class="cmd-card-menu" title="More options"><i class="icon icon-dots-vertical"></i></button></span></div>${data.description?`<div class="cmd-card-desc">${notesEscapeHtml(data.description)}</div>`:""}<pre class="cmd-card-code">${notesEscapeHtml(data.command||"")}</pre>`
return el
}
// ---- editor hosts. Every editor function below (and in notes_pro.js) works on ONE active host: the note editor, or another rich field mounted with notesHostMount (report sections).
// A host is {id,body,wrap,root,isOpen(),el(id),features,tags,store(name,dataUrl),data(id),onDirty(),prefGet(key),prefSet(key,value),title(),pasteHtml(html),structure(body),slash(),runAction(id),menu(items,e)}; only body and wrap are required.
// Switching swaps the per-editor state (selection, command cards, undo stack) and moves the floating overlay into the host's wrap.
let notesHost=null
let notesHostNotes=null
const notesHosts=[]
let notesHostDocWired=false
function notesHostHas(feature){return !(notesHost&&notesHost.features&&notesHost.features[feature]===false)}
function notesHostEl(id){return notesHost&&notesHost.el?notesHost.el(id):document.getElementById(id)}
function notesHostWrap(){return (notesHost&&notesHost.wrap)||document.getElementById("notesEdWrap")}
function notesHostOpen(){return notesHost&&notesHost.isOpen?!!notesHost.isOpen():notesEditorOpen()}
function notesHostTag(tag){return (notesHost&&notesHost.tags&&notesHost.tags[tag])||tag}
function notesHostBodies(){return notesHosts.filter((h)=>h.body&&(h.isOpen?h.isOpen():h.body.isConnected)).map((h)=>h.body)}
function notesHostFor(node){
for(const h of notesHosts)if(h.body&&h.body.contains(node))return h
return null
}
function notesHostTouch(){
if(notesHost&&notesHost.onDirty){notesHost.onDirty();return}
notesState.dirty=true
notesScheduleDraftSave()
}
function notesHostStore(name,dataUrl){
if(notesHost&&notesHost.store)return notesHost.store(name,dataUrl)
return bridgeCall("notes.insert_attachment",[name,dataUrl]).then((att)=>{notesState.pendingAttachments.push(att.id);return att})
}
function notesHostData(id){
if(notesHost&&notesHost.data)return notesHost.data(id)
return bridgeCall("notes.attachment_data",[id]).then((d)=>d.data_url)
}
function notesHostActivate(h){
if(!h||h===notesHost||notesHosts.indexOf(h)<0)return
const prev=notesHost
if(prev){
if(notesUndoState.debounceTimer){clearTimeout(notesUndoState.debounceTimer);notesUndoState.debounceTimer=null;if(prev.body&&prev.body.isConnected)notesUndoPushSnapshot()}
notesProSlashClose()
notesProChipHide()
notesProSetHover(null,null)
prev.savedRange=notesState.savedRange
prev.cmdCards=notesState.cmdCards
prev.undo=notesUndoState
}
notesHost=h
notesState.savedRange=h.savedRange||null
notesState.cmdCards=h.cmdCards||(h.cmdCards={})
notesUndoState=h.undo||(h.undo={stack:[{html:h.body.innerHTML,offset:0}],pointer:0,debounceTimer:null,applying:false})
const ov=notesProOverlay()
if(ov&&h.wrap&&ov.parentNode!==h.wrap)h.wrap.appendChild(ov)
}
function notesHostSelection(){
const sel=window.getSelection()
if(sel.rangeCount===0)return
const range=sel.getRangeAt(0)
const h=notesHostFor(range.startContainer)
if(!h)return
if(h!==notesHost){h.savedRange=range.cloneRange();return}
notesState.savedRange=range.cloneRange()
notesUpdateFontSizeDisplay()
}
// A pointer that only passes over another editor on its way to a popover or a menu must not switch hosts.
function notesHostBusy(){
return !!(notesProState.drag||notesProState.imgDrag||notesProState.colDrag||document.getElementById("notesPopover")||document.getElementById("appContextMenu")||document.getElementById("appModalBackdrop")||notesProOverlayOpen())
}
function notesHostMount(h){
notesHosts.push(h)
if(!notesHostDocWired){notesHostDocWired=true;document.addEventListener("selectionchange",notesHostSelection)}
notesProInitOverlay()
const on=()=>notesHostActivate(h)
const root=h.root||h.body
;["mousedown","focusin","keydown","beforeinput","paste","drop","contextmenu"].forEach((ev)=>root.addEventListener(ev,on,true))
h.body.addEventListener("mouseenter",()=>{if(!notesHostBusy())notesHostActivate(h)})
if(!h.native){
notesHostWireBody(h.body)
h.body.addEventListener("click",(e)=>{const a=e.target.closest("a");if(a)notesHandleLinkClick(a,e,e.ctrlKey||e.metaKey)})
h.body.addEventListener("auxclick",(e)=>{if(e.target.closest("a"))e.preventDefault()})
notesProWireBody(h.body)
h.body.addEventListener("keydown",notesEditorKeydown)
h.body.addEventListener("contextmenu",notesOpenEditorMenu)
}
if(!notesHost)notesHostActivate(h)
return h
}
function notesHostUnmount(h){
const i=notesHosts.indexOf(h)
if(i<0)return
if(notesHost===h){
const next=notesHostNotes&&notesHostNotes!==h?notesHostNotes:notesHosts.find((x)=>x!==h)
if(next)notesHostActivate(next)
else{notesProSlashClose();notesProChipHide();notesProSetHover(null,null);if(notesUndoState.debounceTimer){clearTimeout(notesUndoState.debounceTimer);notesUndoState.debounceTimer=null}notesHost=null}
}
notesHosts.splice(notesHosts.indexOf(h),1)
}
function notesEditorBody(){
return notesHost?notesHost.body:document.getElementById("notesEditorBody")
}
function notesOpenCmdCardMenu(card,anchorEl){
const rect=anchorEl.getBoundingClientRect()
openContextMenu([
{label:"Edit",icon:"edit",fn:()=>notesOpenCmdPopover(anchorEl,card.dataset.cid)},
{label:"Delete",icon:"close",danger:true,fn:()=>notesDeleteCmdCard(card)}
],rect.left,rect.bottom+4)
}
function notesDeleteCmdCard(card){
appConfirm("Delete this command block?",{okLabel:"Delete",danger:true}).then((yes)=>{
if(!yes)return
delete notesState.cmdCards[card.dataset.cid]
card.remove()
notesMarkDirty()
})
}
function notesUpdateCmdCardAlignButtons(card){
const align=(notesState.cmdCards[card.dataset.cid]||{}).align||""
card.querySelectorAll(".cmd-card-align-btn").forEach((btn)=>{
btn.classList.toggle("active",btn.dataset.align===align)
})
}
function notesSetCmdCardAlign(card,align){
const data=notesState.cmdCards[card.dataset.cid]
if(!data)return
data.align=align
card.classList.remove("cmd-card-align-left","cmd-card-align-center","cmd-card-align-right")
if(align)card.classList.add(`cmd-card-align-${align}`)
notesUpdateCmdCardAlignButtons(card)
notesMarkDirty()
}
function notesWireCmdCardButtons(){
const body=notesEditorBody()
notesHostWireBody(body)
body.addEventListener("input",notesAutoNameFromBody)
body.addEventListener("input",focusModeHandleInput)
body.addEventListener("blur",focusModeRestore)
}
// The listeners every host body needs (the note editor and report fields alike).
function notesHostWireBody(body){
body.addEventListener("click",(e)=>{
const copyBtn=e.target.closest(".cmd-card-copy")
const menuBtn=e.target.closest(".cmd-card-menu")
const alignBtn=e.target.closest(".cmd-card-align-btn")
if(copyBtn){
const card=copyBtn.closest(".cmd-card-embed")
const data=notesState.cmdCards[card.dataset.cid]
if(data&&navigator.clipboard)navigator.clipboard.writeText(data.command||"").catch(()=>{})
}else if(menuBtn){
const card=menuBtn.closest(".cmd-card-embed")
notesOpenCmdCardMenu(card,menuBtn)
}else if(alignBtn){
const card=alignBtn.closest(".cmd-card-embed")
const want=alignBtn.dataset.align
const cur=(notesState.cmdCards[card.dataset.cid]||{}).align||""
notesSetCmdCardAlign(card,cur===want?"":want)
}
})
body.addEventListener("input",notesMarkDirty)
body.addEventListener("keydown",(e)=>{
if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="z"){
e.preventDefault()
if(e.shiftKey)notesUndoRedo()
else notesUndoUndo()
}else if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="y"){
e.preventDefault()
notesUndoRedo()
}
})
body.addEventListener("paste",notesHandlePaste)
notesWireAttachmentEmbeds(body)
notesWireCmdCardDrag(body)
}
let notesDragCard=null
// Both editor dragstart listeners see every drag; each must let the other's element through, and a text-node target has no closest().
function notesDragEl(e){const t=e.target;return t&&t.nodeType===1?t:(t&&t.parentElement)||document.body}
function notesWireCmdCardDrag(body){
body.addEventListener("dragstart",(e)=>{
const card=notesDragEl(e).closest(".cmd-card-embed")
if(!card){if(!notesDragEl(e).closest(".note-embed"))e.preventDefault();return}
notesDragCard=card
e.dataTransfer.effectAllowed="move"
e.dataTransfer.setData("text/plain",card.dataset.cid||"")
card.classList.add("cmd-card-dragging")
})
body.addEventListener("dragend",()=>{
if(notesDragCard)notesDragCard.classList.remove("cmd-card-dragging")
notesDragCard=null
})
body.addEventListener("dragover",(e)=>{
if(!notesDragCard)return
e.preventDefault()
e.dataTransfer.dropEffect="move"
})
body.addEventListener("drop",(e)=>{
if(!notesDragCard)return
e.preventDefault()
const targetCard=e.target.closest?e.target.closest(".cmd-card-embed"):null
if(targetCard&&targetCard!==notesDragCard){
const rect=targetCard.getBoundingClientRect()
const before=e.clientY<rect.top+rect.height/2
targetCard.parentNode.insertBefore(notesDragCard,before?targetCard:targetCard.nextSibling)
notesMarkDirty()
return
}
const range=document.caretRangeFromPoint?document.caretRangeFromPoint(e.clientX,e.clientY):null
if(!range||notesDragCard.contains(range.startContainer))return
range.insertNode(notesDragCard)
notesMarkDirty()
})
}
function notesRestoreRange(){
const sel=window.getSelection()
sel.removeAllRanges()
if(notesState.savedRange){
sel.addRange(notesState.savedRange)
}else{
const r=document.createRange()
r.selectNodeContents(notesEditorBody())
r.collapse(false)
sel.addRange(r)
}
}
function notesInsertNodeAtCursor(node){
notesEditorBody().focus()
notesRestoreRange()
const sel=window.getSelection()
const range=sel.getRangeAt(0)
range.deleteContents()
range.insertNode(node)
range.setStartAfter(node)
range.collapse(true)
sel.removeAllRanges()
sel.addRange(range)
notesState.savedRange=range.cloneRange()
notesMarkDirty()
}
function notesInsertNodeAtRange(node,range){
range.deleteContents()
range.insertNode(node)
range.setStartAfter(node)
range.collapse(true)
const sel=window.getSelection()
sel.removeAllRanges()
sel.addRange(range)
notesState.savedRange=range.cloneRange()
notesMarkDirty()
}
function notesFormatBytes(n){
if(n===null||n===undefined||isNaN(n))return ""
if(n<1024)return n+" B"
if(n<1024*1024)return (n/1024).toFixed(1)+" KB"
return (n/(1024*1024)).toFixed(1)+" MB"
}
function notesBuildEmbedEl(att){
const fig=document.createElement("figure")
fig.className="note-embed note-embed-inline"
fig.contentEditable="false"
fig.draggable=true
fig.dataset.attachmentId=att.id
fig.dataset.attachmentUrl=att.url
fig.dataset.kind=att.kind
if(att.kind==="image"){
const img=document.createElement("img")
img.src=att.url
img.alt=att.filename
fig.appendChild(img)
}else{
const chip=document.createElement("div")
chip.className="note-embed-file"
chip.innerHTML=`<i class="icon icon-save"></i><span class="note-embed-filename">${notesEscapeHtml(att.filename)}</span><span class="note-embed-filesize">${notesFormatBytes(att.size)}</span>`
fig.appendChild(chip)
}
return fig
}
function notesAttachmentAccept(files,dropRange){
let first=true
const host=notesHost
Array.from(files||[]).forEach((file)=>{
const reader=new FileReader()
reader.onload=()=>{
notesHostActivate(host)
notesHostStore(file.name,reader.result).then((att)=>{
notesHostActivate(host)
const el=notesBuildEmbedEl(att)
if(first&&dropRange){notesInsertNodeAtRange(el,dropRange);first=false}
else notesProInsertBlock(el,null)
}).catch((err)=>showToast(err&&err.message?err.message:"Attachment failed","error"))
}
reader.readAsDataURL(file)
})
}
// ---- File attachment chips: Open (system app) and Save as... Only the attachment id and its shown name go to Python, which finds the
// file under Data/Attachments itself (and decrypts it when encryption at rest is on). Viewer: click opens; editor: double-click opens
// (a single click there selects/drags the block); right-click or the context-menu key shows Open / Save as... in both.
function notesAttachmentChipInfo(t){
const chip=t&&t.closest?t.closest(".note-embed-file"):null
const fig=chip&&chip.closest("figure.note-embed[data-attachment-id]")
if(!fig)return null
const nameEl=chip.querySelector(".note-embed-filename")
return {id:fig.dataset.attachmentId||"",name:(nameEl&&nameEl.textContent||"").trim(),chip}
}
function notesAttachmentError(err,fallback){showToast(err&&err.message?err.message:fallback,"error")}
function notesAttachmentOpen(info){
if(!info||!info.id)return Promise.resolve(null)
return bridgeCall("notes.attachment_open",[info.id,info.name]).then((r)=>{showToast("Opened "+((r&&r.name)||info.name||"attachment"));return r}).catch((err)=>notesAttachmentError(err,"Could not open the attachment"))
}
function notesAttachmentSaveAs(info){
if(!info||!info.id)return Promise.resolve(null)
return bridgeCall("notes.attachment_save_as",[info.id,info.name]).then((p)=>{if(p)showToast("Saved "+p);return p}).catch((err)=>notesAttachmentError(err,"Could not save the attachment"))
}
function notesAttachmentMenu(info,x,y){
openContextMenu([
{label:"Open",icon:"file",fn:()=>notesAttachmentOpen(info)},
{label:"Save as…",icon:"save",fn:()=>notesAttachmentSaveAs(info)}
],x,y)
}
function notesWireAttachmentChips(root,mode){
if(!root||root.dataset.attChipsWired)return
root.dataset.attChipsWired="1"
const openOn=mode==="view"?"click":"dblclick"
root.addEventListener(openOn,(e)=>{
const info=notesAttachmentChipInfo(e.target)
if(!info||e.button)return
e.preventDefault();e.stopPropagation()
notesAttachmentOpen(info)
})
// Capture phase: runs before the editor's own context menu on the same body, which then does not open.
root.addEventListener("contextmenu",(e)=>{
const info=notesAttachmentChipInfo(e.target)
if(!info)return
e.preventDefault();e.stopPropagation()
notesAttachmentMenu(info,e.clientX,e.clientY)
},true)
root.addEventListener("keydown",(e)=>{
const info=notesAttachmentChipInfo(e.target)
if(!info||e.target!==info.chip)return
if(e.key==="Enter"){e.preventDefault();notesAttachmentOpen(info)}
else if(e.key==="ContextMenu"||(e.key==="F10"&&e.shiftKey)){e.preventDefault();e.stopPropagation();const r=info.chip.getBoundingClientRect();notesAttachmentMenu(info,r.left+12,r.bottom+4)}
},true)
}
// Viewer chips are buttons: focusable, with a tooltip for the less obvious Save as.
function notesDecorateAttachmentChips(root){
root.querySelectorAll("figure.note-embed[data-attachment-id] .note-embed-file").forEach((chip)=>{
chip.setAttribute("role","button")
chip.tabIndex=0
chip.title="Open · right-click for Save as…"
})
}
let notesEmbedResizing=null,notesEmbedDocWired=false
function notesWireAttachmentEmbeds(body){
notesWireAttachmentChips(body,"edit")
body.addEventListener("click",(e)=>{
const btn=e.target.closest(".note-embed-btn")
if(!btn)return
e.stopPropagation()
const fig=btn.closest(".note-embed")
const wrap=btn.dataset.wrap
fig.classList.remove("note-embed-inline","note-embed-float-left","note-embed-float-right")
fig.classList.add("note-embed-"+wrap)
fig.querySelectorAll(".note-embed-btn").forEach((b)=>b.classList.toggle("active",b===btn))
notesMarkDirty()
})
body.addEventListener("mousedown",(e)=>{
const handle=e.target.closest(".note-embed-resize")
if(!handle)return
e.preventDefault()
const fig=handle.closest(".note-embed")
const img=fig.querySelector("img")
if(!img)return
notesEmbedResizing={img,startX:e.clientX,startW:img.getBoundingClientRect().width}
})
if(!notesEmbedDocWired){
notesEmbedDocWired=true
document.addEventListener("mousemove",(e)=>{
if(!notesEmbedResizing)return
const delta=e.clientX-notesEmbedResizing.startX
const w=Math.max(60,Math.round(notesEmbedResizing.startW+delta))
notesEmbedResizing.img.style.width=w+"px"
})
document.addEventListener("mouseup",()=>{
if(notesEmbedResizing){notesMarkDirty();notesEmbedResizing=null}
})
}
body.addEventListener("dragstart",(e)=>{
const fig=notesDragEl(e).closest(".note-embed")
if(!fig){if(!notesDragEl(e).closest(".cmd-card-embed"))e.preventDefault();return}
e.dataTransfer.setData("text/x-note-embed-id",fig.dataset.attachmentId)
e.dataTransfer.effectAllowed="move"
})
body.addEventListener("dragover",(e)=>{
if(e.dataTransfer&&(e.dataTransfer.types||[]).includes("Files"))e.preventDefault()
else if(e.dataTransfer&&(e.dataTransfer.types||[]).includes("text/x-note-embed-id"))e.preventDefault()
})
body.addEventListener("drop",(e)=>{
const hasFiles=e.dataTransfer&&e.dataTransfer.files&&e.dataTransfer.files.length
const embedId=e.dataTransfer?e.dataTransfer.getData("text/x-note-embed-id"):""
if(!hasFiles&&!embedId)return
e.preventDefault()
const range=document.caretRangeFromPoint?document.caretRangeFromPoint(e.clientX,e.clientY):null
if(embedId){
const fig=body.querySelector(`.note-embed[data-attachment-id="${embedId}"]`)
if(fig&&range){
fig.remove()
range.insertNode(fig)
notesMarkDirty()
}
return
}
if(hasFiles)notesAttachmentAccept(e.dataTransfer.files,range)
})
}
function notesMarkDirty(){
notesHostTouch()
notesUndoScheduleSnapshot()
}
let notesUndoState={stack:[{html:"",offset:0}],pointer:0,debounceTimer:null,applying:false}
const NOTES_UNDO_MAX=50
function notesUndoCaretOffset(){
const sel=window.getSelection()
if(!sel.rangeCount)return 0
const range=sel.getRangeAt(0)
const body=notesEditorBody()
if(!body.contains(range.startContainer))return 0
const pre=range.cloneRange()
pre.selectNodeContents(body)
pre.setEnd(range.startContainer,range.startOffset)
return pre.toString().length
}
function notesUndoRestoreCaret(offset){
const body=notesEditorBody()
const walker=document.createTreeWalker(body,NodeFilter.SHOW_TEXT,null)
let remaining=offset
let node=walker.nextNode()
let lastNode=null
while(node){
lastNode=node
if(remaining<=node.textContent.length){
const range=document.createRange()
range.setStart(node,Math.max(0,remaining))
range.collapse(true)
const sel=window.getSelection()
sel.removeAllRanges()
sel.addRange(range)
return
}
remaining-=node.textContent.length
node=walker.nextNode()
}
if(lastNode){
const range=document.createRange()
range.setStart(lastNode,lastNode.textContent.length)
range.collapse(true)
const sel=window.getSelection()
sel.removeAllRanges()
sel.addRange(range)
}
}
function notesUndoPushSnapshot(){
if(notesUndoState.applying)return
const html=notesEditorBody().innerHTML
if(notesUndoState.stack[notesUndoState.pointer]&&notesUndoState.stack[notesUndoState.pointer].html===html)return
notesUndoState.stack=notesUndoState.stack.slice(0,notesUndoState.pointer+1)
notesUndoState.stack.push({html,offset:notesUndoCaretOffset()})
if(notesUndoState.stack.length>NOTES_UNDO_MAX)notesUndoState.stack.shift()
notesUndoState.pointer=notesUndoState.stack.length-1
}
function notesUndoScheduleSnapshot(){
if(notesUndoState.debounceTimer)clearTimeout(notesUndoState.debounceTimer)
notesUndoState.debounceTimer=setTimeout(()=>{
notesUndoState.debounceTimer=null
notesUndoPushSnapshot()
},500)
}
function notesUndoReset(initialHtml){
if(notesUndoState.debounceTimer){clearTimeout(notesUndoState.debounceTimer);notesUndoState.debounceTimer=null}
notesUndoState.stack=[{html:initialHtml||"",offset:0}]
notesUndoState.pointer=0
}
function notesUndoApply(index){
const entry=notesUndoState.stack[index]
if(!entry)return
notesUndoState.applying=true
notesEditorBody().innerHTML=entry.html
notesProSetHover(null,null)
notesProAfterStructureChange()
notesUndoState.pointer=index
notesEditorBody().focus()
notesUndoRestoreCaret(entry.offset)
notesHostTouch()
notesUndoState.applying=false
}
function notesUndoUndo(){
if(notesUndoState.debounceTimer){clearTimeout(notesUndoState.debounceTimer);notesUndoState.debounceTimer=null;notesUndoPushSnapshot()}
if(notesUndoState.pointer<=0)return
notesUndoApply(notesUndoState.pointer-1)
}
function notesUndoRedo(){
if(notesUndoState.pointer>=notesUndoState.stack.length-1)return
notesUndoApply(notesUndoState.pointer+1)
}
let focusModeState={enabled:false,typingTimer:null,active:false}
function focusModeSetActive(active){
if(focusModeState.active===active)return
focusModeState.active=active
const root=document.getElementById("root")
if(root)root.classList.toggle("focus-mode",active)
}
function focusModeRestore(){
if(focusModeState.typingTimer){clearTimeout(focusModeState.typingTimer);focusModeState.typingTimer=null}
focusModeSetActive(false)
}
function focusModeHandleInput(){
if(!focusModeState.enabled)return
if(focusModeState.typingTimer)clearTimeout(focusModeState.typingTimer)
focusModeState.typingTimer=setTimeout(()=>{
focusModeState.typingTimer=null
focusModeSetActive(true)
},900)
}
function focusModeSetEnabled(enabled){
focusModeState.enabled=!!enabled
if(!focusModeState.enabled)focusModeRestore()
}
function initFocusMode(){
bridgeCall("focusMode.get").then((st)=>{focusModeState.enabled=!!st.enabled}).catch(()=>{})
document.addEventListener("mousemove",focusModeRestore,{passive:true})
document.addEventListener("keydown",(e)=>{if(e.key==="Escape"&&focusModeState.active)focusModeRestore()})
}
function notesClosePopover(){
const existing=document.getElementById("notesPopover")
if(existing)existing.remove()
document.removeEventListener("mousedown",notesPopoverOutsideClick,true)
notesPhSuggestHide()
}
function notesPopoverOutsideClick(e){
const pop=document.getElementById("notesPopover")
const suggest=document.getElementById("notesPhSuggest")
if(pop&&!pop.contains(e.target)&&!(suggest&&suggest.contains(e.target))&&!e.target.closest(".ui-select-popover"))notesClosePopover()
}
function notesOpenPopover(anchorEl,widthPx){
notesClosePopover()
const rect=anchorEl.getBoundingClientRect()
const pop=document.createElement("div")
pop.id="notesPopover"
pop.className="notes-popover glass-panel"
pop.style.visibility="hidden"
pop.style.left=Math.round(Math.min(rect.left,window.innerWidth-(widthPx||300)-16))+"px"
pop.style.top="0px"
document.body.appendChild(pop)
setTimeout(()=>document.addEventListener("mousedown",notesPopoverOutsideClick,true),0)
requestAnimationFrame(()=>{
const popH=pop.offsetHeight
const spaceBelow=window.innerHeight-rect.bottom-6
const spaceAbove=rect.top-6
let top=spaceBelow>=popH||spaceBelow>=spaceAbove?Math.round(rect.bottom+6):Math.round(rect.top-popH-6)
top=Math.max(8,Math.min(top,window.innerHeight-popH-8))
pop.style.top=top+"px"
pop.style.visibility="visible"
})
return pop
}
function notesUpdateGroupButtonLabel(){
const label=document.getElementById("notesEditorGroupLabel")
const val=document.getElementById("notesEditorGroup").value.trim()
// Show the chosen group itself (textContent, so names render as text).
label.textContent=val||"No group selected"
label.title=val?"Group: "+val:""
label.classList.toggle("placeholder",!val)
}
function notesSetEditorGroup(name){
document.getElementById("notesEditorGroup").value=(name||"").trim()
notesUpdateGroupButtonLabel()
}
function notesOpenGroupPicker(){
notesPickGroup(document.getElementById("notesEditorGroup").value,"Group",(g)=>{notesSetEditorGroup(g);notesMarkDirty()})
}
function notesPickGroup(currentGroup,title,onPick){
const el=document.createElement("div")
el.className="notes-picker-modal glass-panel"
el.innerHTML=`<div class="notes-popover-title"></div><input type="text" class="notes-popover-search" id="notesGroupPickerSearch" placeholder="Search or create group..." autocomplete="off"><div class="notes-popover-list" id="notesGroupPickerList"></div><div class="notes-popover-actions"><button type="button" id="notesGroupPickerClose">Close</button></div>`
el.querySelector(".notes-popover-title").textContent=title
openModal(el)
const search=el.querySelector("#notesGroupPickerSearch")
const list=el.querySelector("#notesGroupPickerList")
const names=notesGroupNames()
const current=(currentGroup||"").trim().toLowerCase()
const pick=(name)=>{closeModal();onPick((name||"").trim())}
function render(){
const q=search.value.trim().toLowerCase()
const filtered=q?names.filter((n)=>n.toLowerCase().includes(q)):names
list.innerHTML=""
const noneBtn=document.createElement("button")
noneBtn.type="button"
noneBtn.className="notes-popover-item"+(!current?" active":"")
noneBtn.textContent="(No group)"
noneBtn.addEventListener("click",()=>pick(""))
list.appendChild(noneBtn)
filtered.forEach((n)=>{
const b=document.createElement("button")
b.type="button"
b.className="notes-popover-item"+(n.toLowerCase()===current?" active":"")
b.textContent=n
b.addEventListener("click",()=>pick(n))
list.appendChild(b)
})
if(q&&!names.some((n)=>n.toLowerCase()===q)){
const createBtn=document.createElement("button")
createBtn.type="button"
createBtn.className="notes-popover-item notes-popover-create"
createBtn.textContent=`+ Create "${search.value.trim()}"`
createBtn.addEventListener("click",()=>pick(search.value))
list.appendChild(createBtn)
}
}
search.addEventListener("input",render)
search.addEventListener("keydown",(e)=>{
if(e.key==="Enter"){
e.preventDefault()
const q=search.value.trim()
if(q){const hit=names.find((n)=>n.toLowerCase()===q.toLowerCase());pick(hit||q)}else closeModal()
}
})
el.querySelector("#notesGroupPickerClose").addEventListener("click",()=>closeModal())
render()
search.focus()
}
function notesEditorTagsArray(){
return notesSplitTags(document.getElementById("notesEditorTags").value)
}
function notesUpdateTagsButtonLabel(){
const label=document.getElementById("notesEditorTagsLabel")
// Show the chosen tags themselves: up to three, then "+N"; the full list is in the tooltip.
const tags=notesEditorTagsArray(),n=tags.length
label.textContent=n===0?"No tags selected":tags.slice(0,3).join(", ")+(n>3?" +"+(n-3):"")
label.title=n?tags.join(", "):""
label.classList.toggle("placeholder",n===0)
}
function notesSetEditorTags(list){
const deduped=[]
const seen=new Set()
;(list||[]).forEach((t)=>{
const tt=(t||"").trim()
if(!tt)return
const k=tt.toLowerCase()
if(seen.has(k))return
seen.add(k);deduped.push(tt)
})
document.getElementById("notesEditorTags").value=deduped.join(",")
notesUpdateTagsButtonLabel()
}
function notesToggleEditorTag(tag){
const tags=notesEditorTagsArray()
const k=tag.trim().toLowerCase()
if(!k)return
const idx=tags.findIndex((t)=>t.toLowerCase()===k)
if(idx>=0)tags.splice(idx,1)
else tags.push(tag.trim())
notesSetEditorTags(tags)
notesMarkDirty()
}
function notesOpenCreateTagCard(prefillName){
const el=document.createElement("div")
el.className="notes-picker-modal notes-create-tag-modal glass-panel"
el.innerHTML=`<div class="notes-popover-title">Create Tag</div>
<div class="notes-popover-field"><label>Tag name</label><div class="notes-newtag-row"><input type="text" id="notesNewTagName" autocomplete="off" placeholder="Tag name"><button type="button" class="notes-popover-item-colorbtn notes-newtag-colorbtn" id="notesNewTagColorBtn" title="Choose color"></button></div></div>
<div class="notes-popover-error hidden" id="notesNewTagErr"></div>
<div class="notes-popover-actions"><button type="button" id="notesNewTagCancel">Cancel</button><button type="button" class="notes-popover-confirm" id="notesNewTagCreate">Create</button></div>`
openModal(el)
const nameInput=el.querySelector("#notesNewTagName")
const colorBtn=el.querySelector("#notesNewTagColorBtn")
const err=el.querySelector("#notesNewTagErr")
nameInput.value=prefillName||""
let chosenColor=""
colorBtn.addEventListener("click",()=>{
notesOpenColorPopover(colorBtn,NOTES_TAG_COLOR_PRESETS,(hex)=>{
if(hex==="transparent"){chosenColor="";colorBtn.style.background="";colorBtn.title="Choose color"}
else{chosenColor=hex;colorBtn.style.background=hex;colorBtn.title=hex}
},chosenColor||"#3b82f6",true)
})
el.querySelector("#notesNewTagCancel").addEventListener("click",()=>notesOpenTagsPicker())
function create(){
const name=nameInput.value.trim()
if(!name){err.textContent="Tag name is required.";err.classList.remove("hidden");return}
notesToggleEditorTag(name)
if(chosenColor)bridgeCall("tags.set_color",[name,chosenColor]).then(()=>notesLoadTagColors()).then(()=>notesOpenTagsPicker()).catch(()=>notesOpenTagsPicker())
else notesOpenTagsPicker()
}
el.querySelector("#notesNewTagCreate").addEventListener("click",create)
nameInput.addEventListener("keydown",(e)=>{if(e.key==="Enter"){e.preventDefault();create()}})
nameInput.focus()
}
function notesOpenTagsPicker(){
const el=document.createElement("div")
el.className="notes-picker-modal glass-panel"
el.innerHTML=`<div class="notes-popover-title">Tags</div><input type="text" class="notes-popover-search" id="notesTagPickerSearch" placeholder="Search tags..." autocomplete="off"><div class="notes-popover-list" id="notesTagPickerList"></div><div class="notes-popover-actions notes-popover-actions-split"><button type="button" id="notesTagCreateBtn">Create Tag</button><button type="button" class="notes-popover-confirm" id="notesTagPickerDone">Done</button></div>`
openModal(el)
const search=el.querySelector("#notesTagPickerSearch")
const list=el.querySelector("#notesTagPickerList")
function render(){
bridgeCall("notes.tags").then((allTags)=>{
if(!document.body.contains(search))return
const selectedTags=notesEditorTagsArray()
const byKey=new Map((allTags||[]).map((t)=>[t.tag.toLowerCase(),t]))
selectedTags.forEach((t)=>{
const k=t.toLowerCase()
if(!byKey.has(k))byKey.set(k,{tag:t,count:0})
})
const merged=Array.from(byKey.values()).sort((a,b)=>a.tag.toLowerCase().localeCompare(b.tag.toLowerCase()))
const q=search.value.trim().toLowerCase()
const selected=new Set(selectedTags.map((t)=>t.toLowerCase()))
const filtered=merged.filter((t)=>!q||t.tag.toLowerCase().includes(q))
list.innerHTML=""
filtered.forEach((t)=>{
const isSel=selected.has(t.tag.toLowerCase())
const color=notesTagColor(t.tag)
const row=document.createElement("div")
row.className="notes-popover-item notes-popover-item-row"+(isSel?" active":"")
const main=document.createElement("button")
main.type="button"
main.className="notes-popover-item-main"
main.innerHTML=`<span class="notes-popover-item-checkbox${isSel?" checked":""}">${isSel?"&#10003;":""}</span><span class="notes-popover-item-text">${notesEscapeHtml(t.tag)}</span>`
main.addEventListener("click",()=>{notesToggleEditorTag(t.tag);render()})
row.appendChild(main)
const colorBtn=document.createElement("button")
colorBtn.type="button"
colorBtn.className="notes-popover-item-colorbtn"
colorBtn.title="Set tag color"
colorBtn.style.background=color||"var(--glass-bg)"
colorBtn.addEventListener("click",(e)=>{
e.stopPropagation()
notesOpenColorPopover(colorBtn,NOTES_TAG_COLOR_PRESETS,(hex)=>{
const applied=hex==="transparent"?"":hex
bridgeCall("tags.set_color",[t.tag,applied]).then(()=>notesLoadTagColors()).then(render).catch(()=>{})
},color||"#3b82f6",true)
})
row.appendChild(colorBtn)
list.appendChild(row)
})
if(q&&!byKey.has(q)){
const createBtn=document.createElement("button")
createBtn.type="button"
createBtn.className="notes-popover-item notes-popover-create"
createBtn.textContent=`+ Create "${search.value.trim()}"`
createBtn.addEventListener("click",()=>notesOpenCreateTagCard(search.value.trim()))
list.appendChild(createBtn)
}
if(!filtered.length&&!q){
const empty=document.createElement("div")
empty.className="notes-empty-msg"
empty.textContent="No tags yet - use Create Tag below"
list.appendChild(empty)
}
}).catch(()=>{})
}
search.addEventListener("input",render)
search.addEventListener("keydown",(e)=>{
if(e.key==="Enter"){
e.preventDefault()
const q=search.value.trim()
if(q)notesOpenCreateTagCard(q)
}
})
el.querySelector("#notesTagCreateBtn").addEventListener("click",()=>notesOpenCreateTagCard(search.value.trim()))
el.querySelector("#notesTagPickerDone").addEventListener("click",()=>closeModal())
render()
search.focus()
}
let notesPhSuggestState={items:[],selected:0,textarea:null,start:0,end:0}
function notesPhSuggestHide(){
const el=document.getElementById("notesPhSuggest")
if(el)el.remove()
notesPhSuggestState={items:[],selected:0,textarea:null,start:0,end:0}
}
function notesCaretCoords(textarea,position){
const style=getComputedStyle(textarea)
const div=document.createElement("div")
const props=["boxSizing","width","paddingTop","paddingRight","paddingBottom","paddingLeft","borderTopWidth","borderRightWidth","borderBottomWidth","borderLeftWidth","fontStyle","fontVariant","fontWeight","fontSize","lineHeight","fontFamily","textAlign","textTransform","letterSpacing","wordSpacing"]
props.forEach((p)=>{div.style[p]=style[p]})
div.style.position="absolute"
div.style.visibility="hidden"
div.style.whiteSpace="pre-wrap"
div.style.wordWrap="break-word"
div.style.top="0"
div.style.left="-9999px"
document.body.appendChild(div)
div.textContent=textarea.value.substring(0,position)
const span=document.createElement("span")
span.textContent=textarea.value.substring(position)||"."
div.appendChild(span)
const rect=textarea.getBoundingClientRect()
const top=rect.top+span.offsetTop-textarea.scrollTop
const left=rect.left+span.offsetLeft-textarea.scrollLeft
const lineHeight=parseInt(style.lineHeight,10)||16
document.body.removeChild(div)
return {top:top+lineHeight,left}
}
function notesBraceContext(textarea){
const pos=textarea.selectionStart
const text=textarea.value
const left=text.slice(0,pos)
const lastOpen=left.lastIndexOf("{")
if(lastOpen<0)return null
const lastClose=left.lastIndexOf("}")
if(lastClose>lastOpen)return null
const prefix=left.slice(lastOpen+1)
if(/[{}\r\n]/.test(prefix))return null
return {prefix,start:lastOpen+1,end:pos}
}
function notesPhSuggestRender(textarea){
let el=document.getElementById("notesPhSuggest")
if(!el){
el=document.createElement("div")
el.id="notesPhSuggest"
el.className="notes-ph-suggest glass-panel"
document.body.appendChild(el)
}
el.innerHTML=""
notesPhSuggestState.items.forEach((k,i)=>{
const item=document.createElement("button")
item.type="button"
item.className="notes-ph-suggest-item"+(i===notesPhSuggestState.selected?" active":"")
item.textContent=k
item.addEventListener("mousedown",(e)=>{e.preventDefault();notesPhSuggestApply(i)})
el.appendChild(item)
})
const coords=notesCaretCoords(textarea,textarea.selectionStart)
el.style.top=Math.round(Math.min(coords.top,window.innerHeight-el.offsetHeight-8))+"px"
el.style.left=Math.round(Math.min(coords.left,window.innerWidth-220))+"px"
}
function notesPhSuggestShow(textarea){
const ctx=notesBraceContext(textarea)
if(!ctx){notesPhSuggestHide();return}
bridgeCall("targets.keys").then((keys)=>{
if(document.activeElement!==textarea)return
const ctx2=notesBraceContext(textarea)
if(!ctx2)return
let items=(keys||[]).map((k)=>k.key).filter(Boolean)
const lp=ctx2.prefix.toLowerCase()
if(lp)items=items.filter((k)=>k.toLowerCase().startsWith(lp))
if(!items.length){notesPhSuggestHide();return}
notesPhSuggestState={items,selected:0,textarea,start:ctx2.start,end:ctx2.end}
notesPhSuggestRender(textarea)
}).catch(()=>notesPhSuggestHide())
}
function notesPhSuggestApply(index){
const st=notesPhSuggestState
const key=st.items[index]
if(!key||!st.textarea)return
const ta=st.textarea
const before=ta.value.slice(0,st.start)
let after=ta.value.slice(st.end)
if(after.startsWith("}"))after=after.slice(1)
ta.value=before+key+"}"+after
const newPos=before.length+key.length+1
ta.selectionStart=ta.selectionEnd=newPos
notesPhSuggestHide()
ta.focus()
}
function notesWirePlaceholderSuggest(textarea){
textarea.addEventListener("keydown",(e)=>{
const st=notesPhSuggestState
if(st.items.length&&st.textarea===textarea){
if(e.key==="ArrowDown"){e.preventDefault();st.selected=Math.min(st.items.length-1,st.selected+1);notesPhSuggestRender(textarea);return}
if(e.key==="ArrowUp"){e.preventDefault();st.selected=Math.max(0,st.selected-1);notesPhSuggestRender(textarea);return}
if(e.key==="Enter"||e.key==="Tab"){e.preventDefault();notesPhSuggestApply(st.selected);return}
if(e.key==="Escape"){e.preventDefault();notesPhSuggestHide();return}
}
if(e.key==="{"){
e.preventDefault()
const start=textarea.selectionStart
const end=textarea.selectionEnd
const val=textarea.value
textarea.value=val.slice(0,start)+"{}"+val.slice(end)
textarea.selectionStart=textarea.selectionEnd=start+1
notesPhSuggestShow(textarea)
return
}
if(e.key==="}")notesPhSuggestHide()
})
textarea.addEventListener("input",()=>notesPhSuggestShow(textarea))
textarea.addEventListener("blur",()=>setTimeout(notesPhSuggestHide,150))
}
function notesPopulateCmdHistory(){
bridgeCall("commands.history").then((h)=>{
const catList=document.getElementById("notesCmdCategoryHistory")
const subList=document.getElementById("notesCmdSubHistory")
if(catList)catList.innerHTML=(h.categories||[]).map((n)=>`<option value="${notesEscapeHtml(n)}">`).join("")
if(subList)subList.innerHTML=(h.subcategories||[]).map((n)=>`<option value="${notesEscapeHtml(n)}">`).join("")
}).catch(()=>{})
}
function notesOpenCmdPopover(anchorEl,editCid){
const pop=notesOpenPopover(anchorEl,320)
const existing=editCid?notesState.cmdCards[editCid]:null
const typeOptions=COMMAND_TYPE_OPTIONS.map((t)=>`<option value="${notesEscapeHtml(t)}">${notesEscapeHtml(t)}</option>`).join("")
pop.innerHTML=`<div class="notes-popover-title">${existing?"Edit Command Block":"Command Block"}</div>
<div class="notes-popover-field"><label>Command Note Title</label><input type="text" id="notesCmdTitle"></div>
<div class="notes-popover-field"><label>Command Type</label><select id="notesCmdType">${typeOptions}</select></div>
<div class="notes-popover-field hidden" id="notesCmdTypeOtherWrap"><label>Custom Type</label><input type="text" id="notesCmdTypeOther"></div>
<div class="notes-popover-field"><label>Category</label><input type="text" id="notesCmdCategory" list="notesCmdCategoryHistory"></div>
<div class="notes-popover-field"><label>Sub Category</label><input type="text" id="notesCmdSub" list="notesCmdSubHistory"></div>
<div class="notes-popover-field"><label>Description</label><input type="text" id="notesCmdDesc"></div>
<div class="notes-popover-field"><label>Tags (comma separated)</label><input type="text" id="notesCmdTags"></div>
<div class="notes-popover-field"><label>Command</label><textarea id="notesCmdCommand"></textarea></div>
<div class="notes-popover-actions"><button type="button" id="notesCmdCancel">Cancel</button><button type="button" class="notes-popover-confirm" id="notesCmdInsert">${existing?"Save":"Insert"}</button></div>`
notesPopulateCmdHistory()
notesWirePlaceholderSuggest(pop.querySelector("#notesCmdCommand"))
const typeSelect=pop.querySelector("#notesCmdType")
const typeOtherWrap=pop.querySelector("#notesCmdTypeOtherWrap")
const typeOtherInput=pop.querySelector("#notesCmdTypeOther")
function syncTypeOtherVisibility(){
typeOtherWrap.classList.toggle("hidden",typeSelect.value!=="Other")
}
typeSelect.addEventListener("change",syncTypeOtherVisibility)
if(existing){
pop.querySelector("#notesCmdTitle").value=existing.cmd_note_title||""
const existingType=existing.command_type||"other"
if(COMMAND_TYPE_OPTIONS.some((t)=>t.toLowerCase()===existingType.toLowerCase())){
typeSelect.value=COMMAND_TYPE_OPTIONS.find((t)=>t.toLowerCase()===existingType.toLowerCase())
}else{
typeSelect.value="Other"
typeOtherInput.value=existing.command_type||""
}
pop.querySelector("#notesCmdCategory").value=existing.category||""
pop.querySelector("#notesCmdSub").value=existing.sub_category||""
pop.querySelector("#notesCmdDesc").value=existing.description||""
pop.querySelector("#notesCmdTags").value=existing.tags||""
pop.querySelector("#notesCmdCommand").value=existing.command||""
}
else pop.querySelector("#notesCmdTitle").value=notesHost&&notesHost.title?notesHost.title():document.getElementById("notesEditorName").value.trim()
syncTypeOtherVisibility()
const cmdTa=pop.querySelector("#notesCmdCommand")
const prefs=notesState.prefs||{}
cmdTa.style.height=(prefs.cmd_box_command_height||86)+"px"
cmdTa.style.minHeight=(prefs.cmd_box_min||72)+"px"
cmdTa.style.maxHeight=(prefs.cmd_box_max||180)+"px"
cmdTa.style.resize="vertical"
const startH=cmdTa.offsetHeight
const keepHeight=()=>{const h=Math.round(cmdTa.offsetHeight);if(h&&Math.abs(h-startH)>2)bridgeCall("notes.set_editor_pref",["cmd_box_command_height",h]).then((p)=>{notesState.prefs=p}).catch(()=>{})}
pop.addEventListener("mouseup",keepHeight)
pop.querySelector("#notesCmdCancel").addEventListener("click",notesClosePopover)
pop.querySelector("#notesCmdInsert").addEventListener("click",()=>{
const commandType=typeSelect.value==="Other"?(typeOtherInput.value.trim()||"Other"):typeSelect.value
const data={cmd_note_title:pop.querySelector("#notesCmdTitle").value.trim(),category:pop.querySelector("#notesCmdCategory").value.trim(),sub_category:pop.querySelector("#notesCmdSub").value.trim(),description:pop.querySelector("#notesCmdDesc").value.trim(),tags:pop.querySelector("#notesCmdTags").value.trim(),command:pop.querySelector("#notesCmdCommand").value,command_type:commandType}
if(!data.command.trim()){notesClosePopover();return}
if(existing){
notesState.cmdCards[editCid]=data
const card=notesEditorBody().querySelector(`.cmd-card-embed[data-cid="${editCid}"]`)
if(card)card.replaceWith(notesRenderCmdCardEmbed(editCid,data))
notesMarkDirty()
}else{
const cid=notesGenCid()
notesState.cmdCards[cid]=data
notesInsertNodeAtCursor(notesRenderCmdCardEmbed(cid,data))
}
notesClosePopover()
})
}
function notesOpenLinkPopover(anchorEl){
const pop=notesOpenPopover(anchorEl,300)
const candidates=notesState.notes.filter((n)=>n.id!==notesState.editId)
// N16: like the original _add_note_link, the selected text becomes the link text.
const selText=notesState.savedRange&&!notesState.savedRange.collapsed&&notesEditorBody().contains(notesState.savedRange.commonAncestorContainer)?notesState.savedRange.toString().trim():""
pop.innerHTML=`<div class="notes-popover-title">Insert Note Link</div><input type="text" class="notes-popover-search" id="notesLinkSearch" placeholder="Search notes..."><div class="notes-popover-list" id="notesLinkList"></div>`
const list=pop.querySelector("#notesLinkList")
function renderItems(q){
list.innerHTML=""
const qq=(q||"").toLowerCase()
candidates.filter((n)=>!qq||n.note_name.toLowerCase().includes(qq)).slice(0,50).forEach((n)=>{
const item=document.createElement("button")
item.className="notes-popover-item"
item.textContent=n.note_name
item.addEventListener("click",()=>{
bridgeCall("notes.link_token",[n.id,n.note_name]).then((token)=>{
const a=document.createElement("a")
a.href="notelink:"+token
a.textContent=selText||n.note_name
notesInsertNodeAtCursor(a)
notesClosePopover()
}).catch((err)=>console.error("link token failed",err))
})
list.appendChild(item)
})
}
renderItems("")
const search=pop.querySelector("#notesLinkSearch")
search.addEventListener("input",(e)=>renderItems(e.target.value))
// Typing goes straight into the search; Enter links the first match.
search.addEventListener("keydown",(e)=>{if(e.key==="Enter"){e.preventDefault();const first=list.querySelector(".notes-popover-item");if(first)first.click()}})
search.focus()
}
function notesAutoNameFromBody(){
if(notesState.nameTouched)return
// The first line only: with headings, lists and code blocks the whole text would run together.
const body=notesEditorBody()
const text=((body.innerText||body.textContent||"").split(/\r?\n/).map((l)=>l.replace(/\u200b/g,"").trim()).find(Boolean)||"")
if(!text||/^[\/`#>|\[-]/.test(text))return
let name=text.split(/\s+/).slice(0,6).join(" ")
if(name.length>60)name=name.slice(0,60).trim()
document.getElementById("notesEditorName").value=name
}
function notesOpenHistoryModal(){
const note=notesState.selectedNote
if(!note)return
const el=document.createElement("div")
el.className="notes-history-modal glass-panel"
el.innerHTML='<div class="notes-popover-title">Note History</div><div class="notes-history-list" id="notesHistoryList"><div class="notes-empty-msg">Loading...</div></div>'
openModal(el)
bridgeCall("notes.versions",[note.id]).then((versions)=>{
const list=el.querySelector("#notesHistoryList")
if(!versions.length){list.innerHTML='<div class="notes-empty-msg">No history yet</div>';return}
list.innerHTML=""
versions.forEach((v,idx)=>{
const row=document.createElement("div")
row.className="notes-history-row"
const btn=document.createElement("button")
btn.type="button"
btn.className="notes-history-item"
btn.innerHTML=`<span class="notes-history-time">${notesEscapeHtml(v.action_label)}${idx===0?' <span class="notes-history-current">(current)</span>':""}</span><span class="notes-history-preview">${notesEscapeHtml(v.preview)}</span>`
const diffWrap=document.createElement("div")
diffWrap.className="notes-history-diff hidden"
btn.addEventListener("click",()=>{
const wasHidden=diffWrap.classList.contains("hidden")
el.querySelectorAll(".notes-history-diff").forEach((d)=>d.classList.add("hidden"))
if(!wasHidden)return
diffWrap.classList.remove("hidden")
if(diffWrap.dataset.loaded)return
diffWrap.dataset.loaded="1"
diffWrap.innerHTML='<div class="notes-empty-msg">Loading diff...</div>'
bridgeCall("notes.version_diff",[note.id,v.id]).then((segs)=>{
const diffHtml=segs.map((s)=>{
if(s.type==="insert")return `<ins>${notesEscapeHtml(s.text)}</ins> `
if(s.type==="delete")return `<del>${notesEscapeHtml(s.text)}</del> `
return `${notesEscapeHtml(s.text)} `
}).join("")
const restoreBtn=idx===0?"":'<button type="button" class="notes-popover-confirm notes-history-restore">Restore this version</button>'
diffWrap.innerHTML=`<div class="notes-history-diff-text">${diffHtml||"<em>No text changes</em>"}</div>${restoreBtn}`
const rb=diffWrap.querySelector(".notes-history-restore")
if(rb)rb.addEventListener("click",()=>{
appConfirm("Restore this version? The current content will be replaced (this itself becomes a new history entry, so nothing is lost).",{okLabel:"Restore"}).then((yes)=>{
if(!yes)return
bridgeCall("notes.restore_version",[note.id,v.id]).then(()=>{
closeModal()
showToast("Note restored")
notesRefreshLists().then(()=>notesOpen(note.id))
}).catch((err)=>showToast(err&&err.message?err.message:"Restore failed","error"))
})
})
}).catch(()=>{diffWrap.innerHTML='<div class="notes-empty-msg">Failed to load diff</div>'})
})
row.appendChild(btn)
row.appendChild(diffWrap)
list.appendChild(row)
})
}).catch(()=>{})
}
function notesOpenTemplatesPopover(anchorEl){
const pop=notesOpenPopover(anchorEl,300)
pop.innerHTML=`<div class="notes-popover-title">New from Template</div><div class="notes-popover-list" id="notesTplList"></div>`
const list=pop.querySelector("#notesTplList")
function render(){
bridgeCall("notes.templates").then((templates)=>{
list.innerHTML=""
if(!templates.length){
const empty=document.createElement("div")
empty.className="notes-empty-msg"
empty.textContent="No templates saved yet"
list.appendChild(empty)
return
}
templates.forEach((t)=>{
const row=document.createElement("div")
row.className="notes-tpl-row"
const item=document.createElement("button")
item.type="button"
item.className="notes-popover-item"
item.textContent=t.name
item.addEventListener("click",()=>{
bridgeCall("notes.new_from_template",[t.id]).then((data)=>{
const cmdCards={}
data.commands.forEach((c)=>{cmdCards[c.cid]=c})
notesResetEditor(null,"","","","",data.content_html,cmdCards)
notesClosePopover()
}).catch((err)=>showToast(err&&err.message?err.message:"Failed to load template","error"))
})
const del=document.createElement("button")
del.type="button"
del.className="notes-tpl-delete"
del.title="Delete template"
del.innerHTML='<i class="icon icon-close"></i>'
del.addEventListener("click",(e)=>{
e.stopPropagation()
bridgeCall("notes.delete_template",[t.id]).then(render).catch(()=>{})
})
row.appendChild(item)
row.appendChild(del)
list.appendChild(row)
})
}).catch(()=>{})
}
render()
}
function notesOpenSaveTemplatePopover(anchorEl){
const pop=notesOpenPopover(anchorEl,280)
pop.innerHTML=`<div class="notes-popover-title">Save as Template</div><div class="notes-popover-field"><label>Template name</label><input type="text" id="notesTplNameInput"></div><div class="notes-popover-error hidden" id="notesTplErr"></div><div class="notes-popover-actions"><button type="button" id="notesTplCancel">Cancel</button><button type="button" class="notes-popover-confirm" id="notesTplOk">Save</button></div>`
const input=pop.querySelector("#notesTplNameInput")
const err=pop.querySelector("#notesTplErr")
input.value=document.getElementById("notesEditorName").value.trim()
input.focus()
pop.querySelector("#notesTplCancel").addEventListener("click",notesClosePopover)
function confirm(){
const name=input.value.trim()
if(!name){err.textContent="Template name is required.";err.classList.remove("hidden");return}
const content=notesSerializeContent()
const cmds=notesCollectCmds()
bridgeCall("notes.save_template",[name,content,cmds]).then(()=>{
notesClosePopover()
showToast("Saved as template")
}).catch((e)=>{err.textContent=e&&e.message?e.message:"Save failed";err.classList.remove("hidden")})
}
pop.querySelector("#notesTplOk").addEventListener("click",confirm)
input.addEventListener("keydown",(e)=>{if(e.key==="Enter"){e.preventDefault();confirm()}})
}
let notesBacklinkTimer=null
const notesBacklinkState={title:null,noteId:null,start:0,end:0,textNode:null,dismissed:new Set()}
function notesBacklinkCandidates(){
return notesState.notes.filter((n)=>n.id!==notesState.editId&&(n.note_name||"").trim().length>=3)
}
function notesBacklinkHide(){
const el=document.getElementById("notesBacklinkChip")
if(el)el.remove()
notesBacklinkState.title=null
notesBacklinkState.textNode=null
}
function notesBacklinkShow(textNode,match,range){
notesBacklinkState.title=match.name
notesBacklinkState.noteId=match.id
notesBacklinkState.start=match.start
notesBacklinkState.end=match.end
notesBacklinkState.textNode=textNode
let chip=document.getElementById("notesBacklinkChip")
if(!chip){
chip=document.createElement("button")
chip.type="button"
chip.id="notesBacklinkChip"
chip.className="notes-backlink-chip glass-panel"
chip.addEventListener("mousedown",(e)=>e.preventDefault())
chip.addEventListener("click",notesBacklinkAccept)
document.body.appendChild(chip)
}
chip.textContent=`Link to "${match.name}"?`
const r=range.cloneRange()
r.collapse(true)
const rect=r.getBoundingClientRect()
chip.style.left=Math.round(Math.min(rect.left,window.innerWidth-240))+"px"
chip.style.top=Math.round(rect.bottom+6)+"px"
}
function notesBacklinkCheck(){
const sel=window.getSelection()
if(!sel.rangeCount||!sel.isCollapsed){notesBacklinkHide();return}
const range=sel.getRangeAt(0)
const node=range.startContainer
if(!node||node.nodeType!==3||!notesEditorBody().contains(node)){notesBacklinkHide();return}
if(node.parentElement&&node.parentElement.closest("a")){notesBacklinkHide();return}
const offset=range.startOffset
const text=node.textContent||""
const before=text.slice(0,offset)
const lower=before.toLowerCase()
let best=null
notesBacklinkCandidates().forEach((n)=>{
const name=(n.note_name||"").trim()
const idx=lower.lastIndexOf(name.toLowerCase())
if(idx===-1)return
if(idx+name.length!==before.length)return
if(notesBacklinkState.dismissed.has(name.toLowerCase()))return
if(!best||name.length>best.name.length)best={name,id:n.id,start:idx,end:idx+name.length}
})
if(!best){notesBacklinkHide();return}
notesBacklinkShow(node,best,range)
}
function notesBacklinkScheduleCheck(){
if(notesBacklinkTimer)clearTimeout(notesBacklinkTimer)
notesBacklinkTimer=setTimeout(notesBacklinkCheck,400)
}
function notesBacklinkAccept(){
const st=notesBacklinkState
if(!st.title||!st.textNode)return
const textNode=st.textNode
const parent=textNode.parentNode
if(!parent){notesBacklinkHide();return}
const full=textNode.textContent||""
const before=full.slice(0,st.start)
const matchText=full.slice(st.start,st.end)
const after=full.slice(st.end)
bridgeCall("notes.link_token",[st.noteId,st.title]).then((token)=>{
const a=document.createElement("a")
a.href="notelink:"+token
a.textContent=matchText
const beforeNode=document.createTextNode(before)
const afterNode=document.createTextNode(after)
parent.insertBefore(beforeNode,textNode)
parent.insertBefore(a,textNode)
parent.insertBefore(afterNode,textNode)
parent.removeChild(textNode)
const sel=window.getSelection()
const r=document.createRange()
r.setStart(afterNode,0)
r.collapse(true)
sel.removeAllRanges()
sel.addRange(r)
notesState.savedRange=r.cloneRange()
notesMarkDirty()
notesBacklinkHide()
}).catch((err)=>console.error("backlink insert failed",err))
}
function notesWireBacklinkSuggest(){
const body=notesEditorBody()
body.addEventListener("input",notesBacklinkScheduleCheck)
body.addEventListener("blur",notesBacklinkHide)
body.addEventListener("keydown",(e)=>{
if(e.key==="Escape"&&notesBacklinkState.title){
e.preventDefault()
notesBacklinkState.dismissed.add(notesBacklinkState.title.toLowerCase())
notesBacklinkHide()
}
})
}
const NOTES_TEXT_COLORS=NotesPro.PALETTE_TEXT
const NOTES_HIGHLIGHT_COLORS=NotesPro.PALETTE_HIGHLIGHT
let notesColorTextCurrent="#3b82f6"
let notesColorHighlightCurrent="#fff3bf"
function notesApplyTextColor(color){
notesEditorBody().focus()
notesRestoreRange()
document.execCommand("foreColor",false,color)
notesMarkDirty()
notesColorTextCurrent=color
const sw=notesHostEl("notesColorTextSwatch")
if(sw)sw.style.background=color
notesEdSyncColors()
bridgeCall("notes.set_editor_pref",["note_text_color",color]).catch(()=>{})
}
function notesApplyHighlightColor(color){
notesEditorBody().focus()
notesRestoreRange()
document.execCommand("hiliteColor",false,color)
notesMarkDirty()
notesColorHighlightCurrent=color
const sw=notesHostEl("notesColorHighlightSwatch")
if(sw)sw.style.background=color
notesEdSyncColors()
if(/^#[0-9a-f]{6}$/i.test(color))bridgeCall("notes.set_editor_pref",["note_highlight_color",color]).catch(()=>{})
}
function notesHexToRgb(hex){
const m=/^#?([0-9a-f]{6})$/i.exec((hex||"").trim())
if(!m)return{r:0,g:0,b:0}
const n=parseInt(m[1],16)
return{r:(n>>16)&255,g:(n>>8)&255,b:n&255}
}
function notesRgbToHex(r,g,b){
return"#"+[r,g,b].map((v)=>Math.max(0,Math.min(255,Math.round(v))).toString(16).padStart(2,"0")).join("")
}
function notesRgbToHsv(r,g,b){
r/=255;g/=255;b/=255
const max=Math.max(r,g,b),min=Math.min(r,g,b),d=max-min
let h=0
if(d!==0){
if(max===r)h=60*(((g-b)/d)%6)
else if(max===g)h=60*((b-r)/d+2)
else h=60*((r-g)/d+4)
}
if(h<0)h+=360
const s=max===0?0:d/max
const v=max
return{h,s:s*100,v:v*100}
}
function notesHsvToRgb(h,s,v){
s/=100;v/=100
const c=v*s
const x=c*(1-Math.abs(((h/60)%2)-1))
const m=v-c
let r=0,g=0,b=0
if(h<60){r=c;g=x;b=0}
else if(h<120){r=x;g=c;b=0}
else if(h<180){r=0;g=c;b=x}
else if(h<240){r=0;g=x;b=c}
else if(h<300){r=x;g=0;b=c}
else{r=c;g=0;b=x}
return{r:(r+m)*255,g:(g+m)*255,b:(b+m)*255}
}
function notesOpenCustomColorPicker(anchorEl,initialHex,onApply){
const pop=notesOpenPopover(anchorEl,240)
pop.classList.add("notes-color-popover")
const startRgb=notesHexToRgb(initialHex||"#3b82f6")
const state=notesRgbToHsv(startRgb.r,startRgb.g,startRgb.b)
pop.innerHTML=`<div class="notes-color-custom">
<div class="notes-color-spectrum" id="notesColorSpectrum"><div class="notes-color-spectrum-cursor" id="notesColorSpectrumCursor"></div></div>
<div class="notes-color-hue" id="notesColorHue"><div class="notes-color-hue-cursor" id="notesColorHueCursor"></div></div>
<div class="notes-color-rgb">
<div class="notes-color-preview" id="notesColorPreview"></div>
<div class="notes-color-rgb-fields">
<div class="notes-color-rgb-field"><input type="number" min="0" max="255" id="notesColorR"><label>R</label></div>
<div class="notes-color-rgb-field"><input type="number" min="0" max="255" id="notesColorG"><label>G</label></div>
<div class="notes-color-rgb-field"><input type="number" min="0" max="255" id="notesColorB"><label>B</label></div>
</div>
</div>
<div class="notes-color-hex"><label>Hex</label><input type="text" id="notesColorHex" maxlength="7" autocomplete="off" spellcheck="false"></div>
<div class="notes-popover-actions"><button type="button" id="notesColorCancel">Cancel</button><button type="button" class="notes-popover-confirm" id="notesColorApply">Apply</button></div>
</div>`
const spectrum=pop.querySelector("#notesColorSpectrum")
const spectrumCursor=pop.querySelector("#notesColorSpectrumCursor")
const hue=pop.querySelector("#notesColorHue")
const hueCursor=pop.querySelector("#notesColorHueCursor")
const preview=pop.querySelector("#notesColorPreview")
const rInput=pop.querySelector("#notesColorR")
const gInput=pop.querySelector("#notesColorG")
const bInput=pop.querySelector("#notesColorB")
const hexInput=pop.querySelector("#notesColorHex")
function render(){
spectrum.style.backgroundColor=`hsl(${state.h},100%,50%)`
spectrumCursor.style.left=state.s+"%"
spectrumCursor.style.top=(100-state.v)+"%"
hueCursor.style.left=(state.h/360*100)+"%"
const rgb=notesHsvToRgb(state.h,state.s,state.v)
preview.style.background=notesRgbToHex(rgb.r,rgb.g,rgb.b)
if(document.activeElement!==rInput)rInput.value=Math.round(rgb.r)
if(document.activeElement!==gInput)gInput.value=Math.round(rgb.g)
if(document.activeElement!==bInput)bInput.value=Math.round(rgb.b)
if(document.activeElement!==hexInput)hexInput.value=notesRgbToHex(rgb.r,rgb.g,rgb.b)
}
function dragSpectrum(e){
const rect=spectrum.getBoundingClientRect()
const x=Math.max(0,Math.min(1,(e.clientX-rect.left)/rect.width))
const y=Math.max(0,Math.min(1,(e.clientY-rect.top)/rect.height))
state.s=x*100
state.v=(1-y)*100
render()
}
function dragHue(e){
const rect=hue.getBoundingClientRect()
const x=Math.max(0,Math.min(1,(e.clientX-rect.left)/rect.width))
state.h=x*360
render()
}
function onMouseMove(e){
if(!document.body.contains(spectrum)){
document.removeEventListener("mousemove",onMouseMove)
document.removeEventListener("mouseup",onMouseUp)
return
}
if(spectrum.dataset.dragging==="1")dragSpectrum(e)
if(hue.dataset.dragging==="1")dragHue(e)
}
function onMouseUp(){
if(!document.body.contains(spectrum)){
document.removeEventListener("mousemove",onMouseMove)
document.removeEventListener("mouseup",onMouseUp)
return
}
spectrum.dataset.dragging="0"
hue.dataset.dragging="0"
}
spectrum.addEventListener("mousedown",(e)=>{spectrum.dataset.dragging="1";dragSpectrum(e)})
hue.addEventListener("mousedown",(e)=>{hue.dataset.dragging="1";dragHue(e)})
document.addEventListener("mousemove",onMouseMove)
document.addEventListener("mouseup",onMouseUp)
function fromRgbInputs(){
const r=Math.max(0,Math.min(255,parseInt(rInput.value,10)||0))
const g=Math.max(0,Math.min(255,parseInt(gInput.value,10)||0))
const b=Math.max(0,Math.min(255,parseInt(bInput.value,10)||0))
Object.assign(state,notesRgbToHsv(r,g,b))
render()
}
rInput.addEventListener("input",fromRgbInputs)
gInput.addEventListener("input",fromRgbInputs)
bInput.addEventListener("input",fromRgbInputs)
hexInput.addEventListener("input",()=>{const h=NotesPro.normHex(hexInput.value);if(!h)return;const c=notesHexToRgb(h);Object.assign(state,notesRgbToHsv(c.r,c.g,c.b));render()})
hexInput.addEventListener("keydown",(e)=>{if(e.key==="Enter"){e.preventDefault();pop.querySelector("#notesColorApply").click()}})
pop.querySelector("#notesColorCancel").addEventListener("click",notesClosePopover)
pop.querySelector("#notesColorApply").addEventListener("click",()=>{
const rgb=notesHsvToRgb(state.h,state.s,state.v)
onApply(notesRgbToHex(rgb.r,rgb.g,rgb.b))
notesClosePopover()
})
render()
}
function notesRememberColor(hex){
const c=NotesPro.normHex(hex)
if(!c)return
const next=NotesPro.recentPush((notesState.prefs||{}).recent_colors,c,12)
if(!notesState.prefs)notesState.prefs={}
notesState.prefs.recent_colors=next
bridgeCall("notes.set_editor_pref",["recent_colors",next]).catch(()=>{})
}
// Colour picker used for text, highlight, tags and drawing shapes: severity colours, a preset palette, the colours used recently (kept in settings.json) and a custom colour.
function notesOpenColorPopover(anchorEl,colors,onPick,initialHex,allowClear){
const pop=notesOpenPopover(anchorEl,9*28+30)
pop.classList.add("notes-color-popover")
const choose=(c)=>{notesClosePopover();if(c!=="transparent")notesRememberColor(c);onPick(c)}
const section=(title)=>{const t=document.createElement("div");t.className="notes-color-section";t.textContent=title;pop.appendChild(t)}
const cellFor=(c,title)=>{
const cell=document.createElement("button")
cell.type="button"
cell.className="notes-color-cell"+(NotesPro.normHex(initialHex)===NotesPro.normHex(c)?" current":"")
cell.style.background=c
cell.title=title||c
cell.addEventListener("click",()=>choose(c))
return cell
}
section("Severity")
const sev=document.createElement("div")
sev.className="notes-color-sev"
NotesPro.SEVERITIES.forEach((s)=>{
const b=document.createElement("button")
b.type="button"
b.className="notes-color-sev-btn"
b.style.setProperty("--sev",s.color)
b.textContent=s.label
b.title=s.label+" "+s.color
b.addEventListener("click",()=>choose(s.color))
sev.appendChild(b)
})
pop.appendChild(sev)
section("Palette")
const grid=document.createElement("div")
grid.className="notes-color-grid"
colors.forEach((c)=>grid.appendChild(cellFor(c)))
pop.appendChild(grid)
const recent=((notesState.prefs||{}).recent_colors||[]).map(NotesPro.normHex).filter(Boolean)
if(recent.length){
section("Recent")
const rg=document.createElement("div")
rg.className="notes-color-grid"
recent.slice(0,9).forEach((c)=>rg.appendChild(cellFor(c)))
pop.appendChild(rg)
}
const row=document.createElement("div")
row.className="notes-color-actions"
const custom=document.createElement("button")
custom.type="button"
custom.className="notes-color-more"
custom.innerHTML='<span class="notes-color-cell notes-color-cell-custom"></span><span>Custom colour...</span>'
custom.addEventListener("click",()=>notesOpenCustomColorPicker(anchorEl,initialHex,(c)=>{notesRememberColor(c);onPick(c)}))
row.appendChild(custom)
if(allowClear){
const clear=document.createElement("button")
clear.type="button"
clear.className="notes-color-more"
clear.innerHTML='<span class="notes-color-cell notes-color-cell-clear"></span><span>No colour</span>'
clear.addEventListener("click",()=>choose("transparent"))
row.appendChild(clear)
}
pop.appendChild(row)
}
const NOTES_FONT_SIZE_DEFAULT=13
const NOTES_FONT_SIZE_MIN=1
const NOTES_FONT_SIZE_MAX=200
function notesCurrentFontSize(){
const sel=window.getSelection()
if(!sel.rangeCount)return NOTES_FONT_SIZE_DEFAULT
let node=sel.getRangeAt(0).startContainer
if(node.nodeType===3)node=node.parentElement
if(!node||!notesEditorBody().contains(node))return NOTES_FONT_SIZE_DEFAULT
const size=parseInt(getComputedStyle(node).fontSize,10)
return size||NOTES_FONT_SIZE_DEFAULT
}
function notesUpdateFontSizeDisplay(){
const input=notesHostEl("notesFontSizeInput")
if(input&&document.activeElement!==input)input.value=notesCurrentFontSize()
document.querySelectorAll(".notes-ed-size-input").forEach((i)=>{if(document.activeElement!==i)i.value=notesCurrentFontSize()})
}
function notesFontSpanFor(range,body){
let n=range.commonAncestorContainer
if(n&&n.nodeType===3)n=n.parentNode
if(!n||n===body||n.nodeType!==1||n.tagName!=="SPAN")return null
if(!/^\s*font-size\s*:[^;]+;?\s*$/i.test(n.getAttribute("style")||""))return null
return n.textContent===range.toString()?n:null
}
function notesApplyFontSize(size){
size=Math.max(NOTES_FONT_SIZE_MIN,Math.min(NOTES_FONT_SIZE_MAX,Math.round(size)||NOTES_FONT_SIZE_DEFAULT))
notesEditorBody().focus()
notesRestoreRange()
const sel=window.getSelection()
if(sel.rangeCount===0||sel.isCollapsed){notesUpdateFontSizeDisplay();return}
const range=sel.getRangeAt(0)
// Resizing the same selection again (A+ A+ A-) changes the span it already sits in instead of nesting one more span per click.
const own=notesFontSpanFor(range,notesEditorBody())
if(own){own.style.fontSize=size+"px";notesMarkDirty();notesUpdateFontSizeDisplay();return}
const span=document.createElement("span")
span.style.fontSize=size+"px"
try{
range.surroundContents(span)
}catch(e){
const frag=range.extractContents()
span.appendChild(frag)
range.insertNode(span)
}
sel.removeAllRanges()
const r=document.createRange()
r.selectNodeContents(span)
sel.addRange(r)
notesState.savedRange=r.cloneRange()
notesMarkDirty()
notesUpdateFontSizeDisplay()
}
// The toolbar is drawn from the command registry by notes_editor.js (notesEdInit); only the hidden file input is wired here.
function notesWireToolbar(){
document.getElementById("notesAttachmentFileInput").addEventListener("change",(e)=>{
notesAttachmentAccept(e.target.files,null)
e.target.value=""
})
notesEdInit()
}
function notesExtractAttachmentIds(html){
const ids=[]
const rx=/data-attachment-id="([^"]+)"/g
let m
while((m=rx.exec(html||"")))ids.push(m[1])
return ids
}
function notesDiscardPendingAttachments(){
if(notesState.pendingAttachments.length){
bridgeCall("notes.discard_pending_attachments",[notesState.pendingAttachments]).catch(()=>{})
}
notesState.pendingAttachments=[]
}
function notesResetEditor(id,origName,name,group,tags,contentHtml,cmdCards,showDraftNotice){
notesHostActivate(notesHostNotes)
notesDiscardPendingAttachments()
notesBacklinkHide()
notesBacklinkState.dismissed.clear()
notesState.editId=id
notesState.editOrigName=origName||""
notesState.cmdCards=cmdCards||{}
notesState.dirty=false
notesState.savedRange=null
notesState.pendingAttachments=notesExtractAttachmentIds(contentHtml)
notesState.nameTouched=!!id||!!(name||"").trim()
document.getElementById("notesEditorName").value=name||""
notesSetEditorGroup(group||"")
notesSetEditorTags(notesSplitTags(tags||""))
document.getElementById("notesTagSuggestions").classList.add("hidden")
document.getElementById("notesTagSuggestions").innerHTML=""
notesFindClose()
notesProSetHtml(notesEditorBody(),contentHtml||"")
notesUndoReset(notesEditorBody().innerHTML)
notesPhScheduleRefresh()
document.getElementById("notesEditorError").classList.add("hidden")
document.getElementById("notesEditorDraftNotice").classList.toggle("hidden",!showDraftNotice)
notesShowEditor(true)
notesProOnEditorReset()
document.getElementById("notesEditorName").focus()
}
function notesOpenNewNote(){
bridgeCall("notes.draft_get").then((d)=>{
if(d&&!d.note_id)notesApplyDraft(d,true)
else notesResetEditor(null,"","","","","",{})
}).catch(()=>notesResetEditor(null,"","","","","",{}))
}
function notesOpenEditNote(id){
// No selection (the note was closed or deleted): nothing to edit, and the backend must not be asked for a null id.
if(id===null||id===undefined)return
bridgeCall("notes.edit_content",[id]).then((data)=>{
const cmdCards={}
data.commands.forEach((c)=>{cmdCards[c.cid]=c})
notesResetEditor(data.id,data.note_name,data.note_name,data.group_name,data.tags,data.content_html,cmdCards)
}).catch((err)=>console.error("edit load failed",err))
}
function notesSerializeContent(){
notesHostActivate(notesHostNotes)
const clone=notesEditorBody().cloneNode(true)
clone.querySelectorAll(".cmd-card-embed").forEach((card)=>{
const marker=document.createElement("span")
marker.className="cmd-card-marker"
marker.dataset.cid=card.dataset.cid
card.replaceWith(marker)
})
notesProCleanClone(clone)
return clone.innerHTML
}
function notesCollectCmds(){
notesHostActivate(notesHostNotes)
return Array.from(notesEditorBody().querySelectorAll(".cmd-card-embed[data-cid]")).map((el)=>{
const data=notesState.cmdCards[el.dataset.cid]
return data?{cid:el.dataset.cid,...data}:null
}).filter(Boolean)
}
function notesShowError(msg){
const el=document.getElementById("notesEditorError")
el.textContent=msg
el.classList.remove("hidden")
}
function notesSaveNote(){
const name=document.getElementById("notesEditorName").value.trim()
if(!name){notesShowError("Note name is required.");return Promise.resolve(false)}
// One save at a time: a double or triple click must not send the note twice.
if(notesState.saving)return Promise.resolve(false)
notesState.saving=true
const group=document.getElementById("notesEditorGroup").value.trim()
const tags=document.getElementById("notesEditorTags").value.trim()
const content=notesSerializeContent()
const cmds=notesCollectCmds()
return bridgeCall("notes.save",[notesState.editId,name,group,content,cmds,tags]).then((res)=>{
notesState.dirty=false
if(res.action==="unchanged")showToast("Already saved")
notesState.pendingAttachments=[]
bridgeCall("notes.draft_clear").catch(()=>{})
notesState.draft=null
return notesRefreshLists().then(()=>{notesOpen(res.id);return true})
}).catch((err)=>{
console.error("note save failed",err)
notesShowError(err&&err.message?err.message:"Save failed")
return false
}).finally(()=>{notesState.saving=false})
}
function notesEditorOpen(){
const ed=document.getElementById("notesEditor")
return !!ed&&!ed.classList.contains("hidden")
}
// N10: the original asked Save / Discard / Cancel before closing a changed note (Note.py _confirm_save_if_dirty). Resolves true when the editor may close.
function notesConfirmLeaveEditor(){
if(!notesEditorOpen()||!notesState.dirty)return Promise.resolve(true)
return appConfirm("This note has unsaved changes.",{okLabel:"Save",extraLabel:"Discard",cancelLabel:"Cancel"}).then((r)=>{
if(r==="extra")return true
if(r===true)return Promise.resolve(notesSaveNote()).then((ok)=>ok===true?"saved":false)
return false
})
}
function notesRequestCloseEditor(){
notesConfirmLeaveEditor().then((r)=>{if(r===true)notesCancelEdit()})
}
function notesCancelEdit(){
notesDiscardPendingAttachments()
notesBacklinkHide()
notesState.dirty=false
if(notesState.draftTimer){clearTimeout(notesState.draftTimer);notesState.draftTimer=null}
bridgeCall("notes.draft_clear").catch(()=>{})
notesState.draft=null
notesShowEditor(false)
notesRenderGroups()
}
function notesSaveAsDraft(){
const payload=notesBuildDraftPayload()
bridgeCall("notes.draft_save",[payload]).then(()=>{
notesState.dirty=false
if(notesState.draftTimer){clearTimeout(notesState.draftTimer);notesState.draftTimer=null}
notesState.draft=payload
notesShowEditor(false)
notesRenderGroups()
showToast("Saved as draft")
}).catch((err)=>showToast(err&&err.message?err.message:"Save as draft failed","error"))
}
function notesBuildDraftPayload(){
return {note_id:notesState.editId,orig_name:notesState.editOrigName,name:document.getElementById("notesEditorName").value.trim(),group:document.getElementById("notesEditorGroup").value.trim(),tags:document.getElementById("notesEditorTags").value.trim(),html:notesSerializeContent(),cmd_cards:notesCollectCmds()}
}
function notesScheduleDraftSave(){
if(notesState.draftTimer)return
notesState.draftTimer=setTimeout(()=>{
notesState.draftTimer=null
if(!notesState.dirty)return
const payload=notesBuildDraftPayload()
bridgeCall("notes.draft_save",[payload]).then(()=>{
notesState.draft=payload
notesRenderGroups()
}).catch((err)=>console.error("draft save failed",err))
},1500)
}
function notesApplyDraft(d,showNotice){
const cmdCards={}
;(d.cmd_cards||[]).forEach((c)=>{if(c&&c.cid)cmdCards[c.cid]=c})
let html=d.html||""
Object.keys(cmdCards).forEach((cid)=>{
const marker=`<span class="cmd-card-marker" data-cid="${cid}"></span>`
if(html.includes(marker))html=html.replace(marker,notesRenderCmdCardEmbed(cid,cmdCards[cid]).outerHTML)
})
notesResetEditor(d.note_id||null,d.orig_name||"",d.name||"",d.group||"",d.tags||"",html,cmdCards,showNotice)
}
function notesCheckDraft(){
bridgeCall("notes.draft_get").then((d)=>{
notesState.draft=d||null
notesRenderGroups()
if(!d||!d.note_id)return
document.getElementById("notesDraftBanner").classList.remove("hidden")
document.getElementById("notesDraftEdit").onclick=()=>{
document.getElementById("notesDraftBanner").classList.add("hidden")
notesApplyDraft(d)
}
document.getElementById("notesDraftDiscard").onclick=()=>{
document.getElementById("notesDraftBanner").classList.add("hidden")
notesDiscardDraft()
}
document.getElementById("notesDraftDismiss").onclick=()=>{
document.getElementById("notesDraftBanner").classList.add("hidden")
}
}).catch((err)=>console.error("draft check failed",err))
}
// ---- N5: find in note (Ctrl+F). Highlights use the CSS Custom Highlight API when the engine has it, so the editor's HTML is never touched; the read-only viewer falls back to <mark> wrappers.
let notesFindState={open:false,query:"",ranges:[],index:-1,root:null,marks:false}
function notesHasHighlights(){return typeof CSS!=="undefined"&&CSS.highlights&&typeof Highlight!=="undefined"}
function notesFindRoot(){return notesEditorOpen()?notesEditorBody():document.getElementById("notesViewerBody")}
function notesTextRanges(root,test){
const out=[]
if(!root)return out
const w=document.createTreeWalker(root,NodeFilter.SHOW_TEXT,null)
let n
while((n=w.nextNode()))test(n,out)
return out
}
function notesFindMatches(root,q){
const lq=(q||"").toLowerCase()
if(!lq)return []
return notesTextRanges(root,(n,out)=>{
const t=(n.textContent||"").toLowerCase()
let i=t.indexOf(lq)
while(i>=0){const r=document.createRange();r.setStart(n,i);r.setEnd(n,i+lq.length);out.push(r);i=t.indexOf(lq,i+lq.length)}
})
}
function notesFindClearMarks(){
const root=document.getElementById("notesViewerBody")
if(!root)return
root.querySelectorAll("mark.notes-find-hit").forEach((m)=>{const p=m.parentNode;while(m.firstChild)p.insertBefore(m.firstChild,m);p.removeChild(m);p.normalize()})
notesFindState.marks=false
}
function notesFindPaint(){
const st=notesFindState
if(notesHasHighlights()){
CSS.highlights.set("notes-find",new Highlight(...st.ranges))
const cur=st.ranges[st.index]
if(cur)CSS.highlights.set("notes-find-current",new Highlight(cur));else CSS.highlights.delete("notes-find-current")
}else if(st.root&&st.root.id==="notesViewerBody"&&st.ranges.length){
const marks=[]
for(let i=st.ranges.length-1;i>=0;i--){const m=document.createElement("mark");m.className="notes-find-hit";try{st.ranges[i].surroundContents(m);marks.unshift(m)}catch(e){}}
marks.forEach((m,i)=>m.classList.toggle("current",i===st.index))
st.marks=true
st.ranges=marks.map((m)=>{const r=document.createRange();r.selectNodeContents(m);return r})
}else if(st.root&&st.ranges[st.index]){
const sel=window.getSelection();sel.removeAllRanges();sel.addRange(st.ranges[st.index].cloneRange())
}
const cur=st.ranges[st.index]
if(cur){const el=cur.startContainer.nodeType===1?cur.startContainer:cur.startContainer.parentElement;if(el)el.scrollIntoView({block:"center"})}
const count=document.getElementById("notesFindCount")
if(count)count.textContent=st.ranges.length?`${st.index+1}/${st.ranges.length}`:(st.query?"0/0":"")
}
function notesFindRun(keepIndex){
const st=notesFindState
notesFindClearMarks()
st.root=notesFindRoot()
st.ranges=notesFindMatches(st.root,st.query)
if(!st.ranges.length)st.index=-1
else if(!keepIndex||st.index<0)st.index=0
else st.index=Math.min(st.index,st.ranges.length-1)
notesFindPaint()
}
function notesFindStep(dir){
const st=notesFindState
notesFindRun(true)
if(!st.ranges.length)return
st.index=(st.index+dir+st.ranges.length)%st.ranges.length
notesFindClearMarks()
st.ranges=notesFindMatches(st.root,st.query)
notesFindPaint()
}
function notesFindOpen(){
const host=notesEditorOpen()?document.getElementById("notesEditorCard"):document.getElementById("notesViewerContent")
if(!host||host.classList.contains("hidden"))return
let bar=document.getElementById("notesFindBar")
if(bar&&bar.parentElement!==host){bar.remove();bar=null}
if(!bar){
bar=document.createElement("div")
bar.id="notesFindBar"
bar.className="notes-find-bar glass-panel"
bar.innerHTML='<i class="icon icon-search"></i><input type="text" id="notesFindInput" placeholder="Find in note..." autocomplete="off"><span class="notes-find-count" id="notesFindCount"></span><button type="button" id="notesFindPrev" title="Previous (Shift+Enter)"><i class="icon icon-arrow-up"></i></button><button type="button" id="notesFindNext" title="Next (Enter)"><i class="icon icon-arrow-down"></i></button><button type="button" id="notesFindClose" title="Close (Esc)"><i class="icon icon-close"></i></button>'
host.appendChild(bar)
const input=bar.querySelector("#notesFindInput")
input.addEventListener("input",()=>{notesFindState.query=input.value;notesFindRun(false)})
input.addEventListener("keydown",(e)=>{
if(e.key==="Enter"){e.preventDefault();notesFindStep(e.shiftKey?-1:1)}
else if(e.key==="Escape"){e.preventDefault();e.stopPropagation();notesFindClose()}
})
bar.querySelector("#notesFindPrev").addEventListener("mousedown",(e)=>e.preventDefault())
bar.querySelector("#notesFindNext").addEventListener("mousedown",(e)=>e.preventDefault())
bar.querySelector("#notesFindPrev").addEventListener("click",()=>notesFindStep(-1))
bar.querySelector("#notesFindNext").addEventListener("click",()=>notesFindStep(1))
bar.querySelector("#notesFindClose").addEventListener("click",notesFindClose)
}
notesFindState.open=true
const input=bar.querySelector("#notesFindInput")
const sel=window.getSelection()
const picked=sel&&sel.rangeCount&&!sel.isCollapsed?sel.toString().trim():""
if(picked&&picked.length<80&&!picked.includes("\n"))input.value=picked
notesFindState.query=input.value
input.focus();input.select()
notesFindRun(false)
}
function notesFindClose(){
const bar=document.getElementById("notesFindBar")
if(bar)bar.remove()
notesFindClearMarks()
if(notesHasHighlights()){CSS.highlights.delete("notes-find");CSS.highlights.delete("notes-find-current")}
notesFindState={open:false,query:"",ranges:[],index:-1,root:null,marks:false}
}
// ---- N20: underline {KEY} placeholders (known / unknown / invalid, original _PlaceholderHighlighter) and -Notename-X- refs, in the viewer and the editor.
let notesPhKeys=null,notesPhTimer=null
function notesPhLoadKeys(force){
if(notesPhKeys&&!force)return Promise.resolve(notesPhKeys)
return bridgeCall("targets.keys").then((keys)=>{notesPhKeys=new Set((keys||[]).map((k)=>(k.key||"").trim().toLowerCase()).filter(Boolean));return notesPhKeys}).catch(()=>{notesPhKeys=new Set();return notesPhKeys})
}
function notesPhClassify(inner,keys){
const k=(inner||"").trim()
if(!k||k!==inner||/[{}\r\n]/.test(k))return "invalid"
return keys.has(k.toLowerCase())?"known":"unknown"
}
// A {KEY} only counts as a placeholder when it is not a shell variable (${HOME}) and its name is identifier-like, the same rule as snippets.js snipIterPlaceholders: {id,email}, {2,3} and {1..10} are plain text.
function notesPhIsCandidate(text,index,inner){
if(index>0&&text[index-1]==="$")return false
const k=(inner||"").trim()
return !k||/^[A-Za-z_][A-Za-z0-9_ ]*$/.test(k)
}
function notesPhRanges(root,keys){
const out={known:[],unknown:[],invalid:[],ref:[]}
notesTextRanges(root,(n)=>{
const t=n.textContent||""
if(t.indexOf("{")>=0){const rx=/\{([^{}\r\n]*)\}/g;let m;while((m=rx.exec(t))){if(!notesPhIsCandidate(t,m.index,m[1]))continue;const r=document.createRange();r.setStart(n,m.index);r.setEnd(n,m.index+m[0].length);out[notesPhClassify(m[1],keys)].push(r)}}
if(/-notename-/i.test(t)&&!(n.parentElement&&n.parentElement.closest("a.note-ref,.note-ref"))){const rx=/-Notename-([^\r\n-]+)-/gi;let m;while((m=rx.exec(t))){const r=document.createRange();r.setStart(n,m.index);r.setEnd(n,m.index+m[0].length);out.ref.push(r)}}
})
return out
}
function notesPhRefresh(){
if(!notesHasHighlights())return
notesPhLoadKeys(false).then((keys)=>{
const all={known:[],unknown:[],invalid:[],ref:[]}
const roots=[document.getElementById("notesViewerBody")]
if(notesEditorOpen())roots.push(notesEditorBody())
roots.forEach((root)=>{const r=notesPhRanges(root,keys);Object.keys(all).forEach((k)=>all[k].push(...r[k]))})
Object.keys(all).forEach((k)=>CSS.highlights.set("notes-ph-"+k,new Highlight(...all[k])))
})
}
function notesPhScheduleRefresh(){
if(notesPhTimer)clearTimeout(notesPhTimer)
notesPhTimer=setTimeout(()=>{notesPhTimer=null;notesPhRefresh()},250)
}
// ---- S15/N19: editor preferences saved by the original (note_ref_color, last text/highlight colour, command box height).
function notesApplyPrefs(p){
notesState.prefs=p||{}
const ref=notesState.prefs.note_ref_color
;[document.querySelector('.page[data-page="notes"]'),document.getElementById("notesEditor")].forEach((el)=>{if(el&&ref)el.style.setProperty("--note-ref-color",ref)})
if(notesState.prefs.note_text_color){notesColorTextCurrent=notesState.prefs.note_text_color;const sw=document.getElementById("notesColorTextSwatch");if(sw)sw.style.background=notesColorTextCurrent}
if(notesState.prefs.note_highlight_color){notesColorHighlightCurrent=notesState.prefs.note_highlight_color;const sw=document.getElementById("notesColorHighlightSwatch");if(sw)sw.style.background=notesColorHighlightCurrent}
notesProOnPrefs()
}
function notesLoadPrefs(){
return bridgeCall("notes.editor_prefs").then(notesApplyPrefs).catch(()=>{})
}
// ---- N6: Pick Command (original _CmdPickerDlg): search the Commands tables and insert the chosen one as a card.
function notesOpenPickCommand(){
const el=document.createElement("div")
el.className="notes-picker-modal notes-cmd-picker glass-panel"
el.innerHTML=`<div class="notes-popover-title">Pick Command</div><input type="text" class="notes-popover-search" id="notesPickCmdSearch" placeholder="Search commands..." autocomplete="off"><div class="notes-popover-list notes-cmd-pick-list" id="notesPickCmdList"><div class="notes-empty-msg">Loading...</div></div><div class="notes-popover-actions"><button type="button" id="notesPickCmdClose">Close</button></div>`
openModal(el)
const search=el.querySelector("#notesPickCmdSearch")
const list=el.querySelector("#notesPickCmdList")
let rows=[]
function insert(r){
const data={cmd_note_title:r.title||r.cmd_note_title||"",category:r.category||"",sub_category:r.sub||r.sub_category||"",description:r.description||"",tags:r.tags||"",command:r.command||"",command_type:r.command_type||"other"}
closeModal()
const cid=notesGenCid()
notesState.cmdCards[cid]=data
notesInsertNodeAtCursor(notesRenderCmdCardEmbed(cid,data))
}
function render(){
const q=search.value.trim().toLowerCase()
const hits=rows.filter((r)=>!q||[r.note_name,r.title,r.category,r.sub,r.command,r.tags,r.description].join("\n").toLowerCase().includes(q)).slice(0,200)
list.innerHTML=""
if(!hits.length){list.innerHTML=`<div class="notes-empty-msg">${rows.length?"No commands match":"No commands yet"}</div>`;return}
hits.forEach((r)=>{
const b=document.createElement("button")
b.type="button"
b.className="notes-popover-item notes-cmd-pick-item"
b.innerHTML=`<span class="notes-cmd-pick-head"><span class="notes-cmd-pick-title">${notesEscapeHtml(r.title||"Command")}</span><span class="notes-cmd-pick-meta">${notesEscapeHtml([r.note_name,r.category,r.sub].filter(Boolean).join(" / "))}</span></span><code class="notes-cmd-pick-code">${notesEscapeHtml(r.command||"")}</code>`
b.addEventListener("click",()=>insert(r))
list.appendChild(b)
})
}
search.addEventListener("input",render)
search.addEventListener("keydown",(e)=>{if(e.key==="Enter"){e.preventDefault();const first=list.querySelector(".notes-cmd-pick-item");if(first)first.click()}})
el.querySelector("#notesPickCmdClose").addEventListener("click",()=>closeModal())
bridgeCall("commands.list").then((r)=>{rows=(r||[]).filter((x)=>(x.command||"").trim());render()}).catch((err)=>{list.innerHTML=`<div class="notes-empty-msg">${notesEscapeHtml(err&&err.message?err.message:"Failed to load commands")}</div>`})
search.focus()
}
// ---- N8: rich paste (sanitised) and pasted images saved as attachments (original saved them under Data/NoteImages). Ctrl+Shift+V pastes plain text.
let notesPastePlain=false
// The clipboard HTML goes through the same allow-list as every rendered note (NotesPro.sanAttr / sanTagAction), in its stricter "paste" mode: no classes or data-* attributes except the note's own block markup, no buttons.
function notesSanitizePaste(html){
const images=[]
return {html:notesProSanitizedHtml(html,"paste",images),images}
}
function notesClipboardFiles(cd){
const files=Array.from(cd.files||[])
if(files.length)return files
return Array.from(cd.items||[]).filter((i)=>i.kind==="file").map((i)=>i.getAsFile()).filter(Boolean)
}
function notesHandlePaste(e){
const cd=e.clipboardData||window.clipboardData
if(!cd)return
e.preventDefault()
const plain=notesPastePlain
notesPastePlain=false
const text=cd.getData("text/plain")
const html=plain?"":cd.getData("text/html")
const files=plain?[]:notesClipboardFiles(cd)
// Inside a code block every paste is plain text, with its line breaks kept.
const inCode=(()=>{const sel=window.getSelection();if(!sel.rangeCount)return false;const n=sel.getRangeAt(0).startContainer;const el=n.nodeType===1?n:n.parentElement;return !!(el&&el.closest("pre.note-code"))})()
if(inCode){notesProInsertPlain((text||"").replace(/\r\n?/g,"\n"));notesProScheduleTint();return}
if(files.length&&(!html||!notesPlainTextFromHtml(html))){notesAttachmentAccept(files,null);return}
if(!html&&!plain&&LoyaMarkdown.looksLikeMarkdown(text)&&notesProPasteMarkdown(text))return
if(!html){document.execCommand("insertText",false,text);notesMarkDirty();return}
const clean=notesSanitizePaste(html)
if(notesHost&&notesHost.pasteHtml)clean.html=notesHost.pasteHtml(clean.html)
document.execCommand("insertHTML",false,clean.html)
const host=notesHost,body=notesEditorBody()
clean.images.forEach((src,i)=>{
const ext=((/^data:image\/([a-z0-9+]+)/i.exec(src)||[])[1]||"png").replace("jpeg","jpg").replace("svg+xml","svg")
notesHostStore(`pasted-${Date.now()}-${i}.${ext}`,src).then((att)=>{
notesHostActivate(host)
const ph=body.querySelector(`span[data-paste-img="${i}"]`)
if(ph)ph.replaceWith(notesBuildEmbedEl(att))
notesMarkDirty()
}).catch((err)=>{const ph=body.querySelector(`span[data-paste-img="${i}"]`);if(ph)ph.remove();showToast(err&&err.message?err.message:"Image paste failed","error")})
})
notesMarkDirty()
}
// ---- N14: editor context menu, lists and tables (original Note.py 2195-2360, 4159-4264).
function notesInsertTable(rows,cols){
rows=Math.max(1,rows||3);cols=Math.max(1,cols||3)
const t=document.createElement("table")
t.className="note-table"
for(let r=0;r<rows;r++){const tr=t.insertRow();for(let c=0;c<cols;c++){tr.insertCell().innerHTML="<br>"}}
notesProInsertBlock(t,t.rows[0].cells[0])
}
function notesTableOp(cell,op){
const table=cell.closest("table")
const tr=cell.parentElement
const ci=cell.cellIndex
const rows=Array.from(table.rows)
if(op==="rowAbove")notesProTableAddRow(table,tr,null)
else if(op==="rowBelow")notesProTableAddRow(table,null,tr)
else if(op==="colLeft"||op==="colRight")notesProTableAddCol(table,ci,op==="colRight")
else if(op==="delRow"){if(rows.length<=1)table.remove();else tr.remove()}
else if(op==="delCol"){if(tr.cells.length<=1)table.remove();else rows.forEach((r)=>{if(r.cells[ci])r.cells[ci].remove()})}
else if(op==="delTable")table.remove()
notesMarkDirty()
notesProSetHover(null,null)
}
// No value means "", never null: WebKit turns a null value into the string "null" (insertHorizontalRule then writes <hr id="null">).
function notesExec(cmd,arg){notesEditorBody().focus();notesRestoreRange();document.execCommand(cmd,false,arg==null?"":arg);if(cmd==="insertUnorderedList"||cmd==="insertOrderedList")notesFixListInP();notesMarkDirty()}
// WebKitGTK turns a <p> into <p><ul>...</ul></p> on insert(Un)orderedList. That is invalid HTML: the parser splits it on reload, and the lines
// typed after the list stay inside the <p>, so a later block command (code block, quote) swallows them all. Lift the list out of the paragraph.
function notesLiftListFromP(body,node){
let n=node
while(n&&n!==body&&!(n.nodeType===1&&(n.tagName==="UL"||n.tagName==="OL")))n=n.parentNode
if(!n||n===body)return false
const p=n.parentNode
if(!p||p===body||p.tagName!=="P")return false
while(p.firstChild)p.parentNode.insertBefore(p.firstChild,p)
p.parentNode.removeChild(p)
return true
}
function notesFixListInP(){
const sel=window.getSelection()
if(!sel.rangeCount)return
const a=[sel.anchorNode,sel.anchorOffset,sel.focusNode,sel.focusOffset]
if(notesLiftListFromP(notesEditorBody(),a[0]))try{sel.setBaseAndExtent(a[0],a[1],a[2],a[3])}catch(e){}
}
// Right-click in the editor: the registry menu with submenus (notes_editor.js). Shift+right-click keeps the browser's own menu. A host's menu(items,e) entries are shown first.
function notesOpenEditorMenu(e){
if(e.shiftKey)return
e.preventDefault()
notesEdOpenContextMenu(e,false)
}
// ---- N16 Backspace removes a note link as one unit; N18 "---" + Enter becomes a horizontal line.
function notesLinkBeforeCaret(){
const sel=window.getSelection()
if(!sel.rangeCount||!sel.isCollapsed)return null
const r=sel.getRangeAt(0)
let n=r.startContainer,off=r.startOffset
if(n.nodeType===3){
const a=n.parentElement&&n.parentElement.closest("a[href^='notelink:']")
if(a&&off===n.textContent.length&&a.lastChild===n)return a
if(off>0)return null
}else if(off>0){const prev=n.childNodes[off-1];return prev&&prev.nodeType===1&&prev.matches("a[href^='notelink:']")?prev:null}
while(n&&n!==notesEditorBody()&&!n.previousSibling)n=n.parentNode
const prev=n&&n!==notesEditorBody()?n.previousSibling:null
return prev&&prev.nodeType===1&&prev.matches("a[href^='notelink:']")?prev:null
}
function notesEditorKeydown(e){
if(e.defaultPrevented)return
if(e.key==="Backspace"&&!e.ctrlKey&&!e.altKey){
const a=notesLinkBeforeCaret()
if(a){e.preventDefault();a.remove();notesMarkDirty();return}
}
if(e.key==="Enter"&&!e.shiftKey&&!e.ctrlKey&&!e.altKey){
const sel=window.getSelection()
if(!sel.rangeCount||!sel.isCollapsed)return
const n=sel.getRangeAt(0).startContainer
const body=notesEditorBody()
const block=(n.nodeType===1?n:n.parentElement).closest("div,p,li")
const own=block&&block!==body&&body.contains(block)?block:null
const text=own?own.textContent:(n.nodeType===3?n.textContent:"")
if(text.trim()!=="---")return
e.preventDefault()
if(own){own.innerHTML="<br>";const r=document.createRange();r.setStart(own,0);r.collapse(true);sel.removeAllRanges();sel.addRange(r)}
else{n.textContent="";const r=document.createRange();r.setStart(n,0);r.collapse(true);sel.removeAllRanges();sel.addRange(r)}
document.execCommand("insertHorizontalRule",false,"")
notesMarkDirty()
return
}
if((e.ctrlKey||e.metaKey)&&e.shiftKey&&e.key.toLowerCase()==="v")notesPastePlain=true
}
// ---- T14: target keys changed on the Targets page (rename/merge/remove). Refresh placeholder data; an open, unchanged editor reloads the note, a changed one asks first, so saving cannot write the old key back silently.
function notesOnTargetKeysChanged(e){
notesPhKeys=null
notesPhScheduleRefresh()
const kind=e&&e.detail&&e.detail.kind
if(kind&&!["rename","merge","remove"].includes(kind))return
notesRefreshLists().then(()=>{
if(notesEditorOpen()&&notesState.editId){
if(!notesState.dirty){notesOpenEditNote(notesState.editId);return}
appConfirm("Target keys were renamed or merged while this note is open, and the note was updated on disk. Reload it now? Your unsaved edits will be lost. If you keep editing, saving will write the old key names back.",{okLabel:"Reload",cancelLabel:"Keep editing"}).then((yes)=>{if(yes){notesState.dirty=false;notesOpenEditNote(notesState.editId)}})
}else if(!notesEditorOpen()&&notesState.selectedId)bridgeCall("notes.get",[notesState.selectedId]).then(notesRenderViewer).catch(()=>{})
}).catch(()=>{})
}
function notesOnPageShown(e){
if(!e.detail||e.detail.page!=="notes"||e.detail.first)return
notesPhKeys=null
notesRefreshLists().then(()=>{
// The open note may have been deleted elsewhere (terminal, AI, another page): do not keep showing its old title and body.
if(!notesEditorOpen()&&notesState.selectedId)return bridgeCall("notes.get",[notesState.selectedId]).then(notesRenderViewer).catch(()=>{notesState.selectedId=null;notesState.selectedNote=null;notesSetViewerMode("empty");notesRenderGroups();notesRenderTabStrip()})
}).catch((err)=>console.error("notes refresh failed",err))
}
function notesPageActive(){
const page=document.querySelector('.page[data-page="notes"]')
return !!page&&page.classList.contains("active")
}
function notesHandleKeydown(e){
if(e.defaultPrevented)return
const mod=e.ctrlKey||e.metaKey
const key=(e.key||"").toLowerCase()
if(mod&&key==="s"&&!e.shiftKey){
if(notesEditorOpen()&&!notesProOverlayOpen()){e.preventDefault();notesSaveNote()}
return
}
if(!notesPageActive()&&!notesEditorOpen())return
if(document.querySelector(".confirm-overlay"))return
if(mod&&!e.shiftKey&&!e.altKey&&key==="f"){
if(notesEditorOpen()||(notesState.selectedNote&&!document.getElementById("notesViewerContent").classList.contains("hidden"))){e.preventDefault();notesFindOpen()}
return
}
if(mod&&e.shiftKey&&!e.altKey&&key==="c"&&notesEditorOpen()&&!document.getElementById("appModalBackdrop")){
e.preventDefault()
notesOpenCmdPopover(notesEdAnchor("ins.cmd"))
return
}
if(e.key==="Escape"){
if(notesFindState.open){e.preventDefault();notesFindClose();return}
if(notesEditorOpen()&&!document.getElementById("notesPopover")&&!document.getElementById("appModalBackdrop")&&!document.getElementById("appContextMenu")&&!document.getElementById("notesBacklinkChip")&&!document.getElementById("notesPhSuggest")&&!notesProOverlayOpen()){e.preventDefault();notesRequestCloseEditor()}
}
}
function initNotes(){
return fetch("../pages/notes.html").then((r)=>r.text()).then((html)=>{
document.querySelector('.page[data-page="notes"]').innerHTML=html
document.getElementById("content").appendChild(document.getElementById("notesEditor"))
notesSbInit()
document.getElementById("notesNewBtn").addEventListener("click",notesOpenNewNote)
document.getElementById("notesTemplatesBtn").addEventListener("click",(e)=>notesOpenTemplatesPopover(e.currentTarget))
document.getElementById("notesEditorSaveTemplate").addEventListener("click",(e)=>notesOpenSaveTemplatePopover(e.currentTarget))
document.getElementById("notesEditorName").addEventListener("input",()=>{notesState.nameTouched=true;notesMarkDirty()})
document.getElementById("notesEditorGroupBtn").addEventListener("click",notesOpenGroupPicker)
document.getElementById("notesEditorTagsBtn").addEventListener("click",notesOpenTagsPicker)
document.getElementById("notesEditBtn").addEventListener("click",()=>notesOpenEditNote(notesState.selectedId))
document.getElementById("notesGraphBtn").addEventListener("click",notesOpenGraphModal)
document.getElementById("notesSummarizeBtn").addEventListener("click",notesDoSummarize)
document.getElementById("notesTagSuggestBtn").addEventListener("click",notesDoSuggestTags)
document.getElementById("notesPinBtn").addEventListener("click",()=>{
if(notesState.selectedNote)notesTogglePinned(notesState.selectedNote)
})
document.getElementById("notesHistoryBtn").addEventListener("click",notesOpenHistoryModal)
document.getElementById("notesDeleteBtn").addEventListener("click",(e)=>{
const note=notesState.selectedNote
if(note&&note.id===notesState.selectedId)notesDeleteNote(note,!!e.shiftKey)
})
document.getElementById("notesEditorCancel").addEventListener("click",notesRequestCloseEditor)
document.getElementById("notesEditorSaveDraft").addEventListener("click",notesSaveAsDraft)
document.getElementById("notesEditorSave").addEventListener("click",notesSaveNote)
document.getElementById("notesEditorDraftDiscard").addEventListener("click",()=>{
bridgeCall("notes.draft_clear").catch(()=>{})
notesState.draft=null
notesRenderGroups()
notesResetEditor(null,"","","","","",{})
})
notesHostNotes=notesHostMount({id:"notes",native:true,body:document.getElementById("notesEditorBody"),wrap:document.getElementById("notesEdWrap"),root:document.getElementById("notesEditor"),isOpen:notesEditorOpen})
notesHostActivate(notesHostNotes)
notesWireToolbar()
notesWireCmdCardButtons()
notesWireBacklinkSuggest()
notesWireLinkGuards()
notesProInit()
notesEditorBody().addEventListener("keydown",notesEditorKeydown)
notesEditorBody().addEventListener("contextmenu",notesOpenEditorMenu)
notesEditorBody().addEventListener("input",notesPhScheduleRefresh)
document.getElementById("notesNewGroupBtn").addEventListener("click",notesCreateGroup)
document.addEventListener("keydown",notesHandleKeydown)
document.addEventListener("loya:page-shown",notesOnPageShown)
document.addEventListener("loya:target-keys-changed",notesOnTargetKeysChanged)
notesLoadPrefs()
return notesRefreshLists()
}).then(()=>{
notesCheckDraft()
}).catch((err)=>console.error("notes init failed",err))
}
