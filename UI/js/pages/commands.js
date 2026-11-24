let cmdsState={rows:[],search:"",categoryFilter:"",linkFilter:"",sortKey:"",sortDir:1,history:{},page:0,pageSize:20,stamp:"",pollTimer:null,clickTimer:null}
const CMDS_PAGE_SIZES=[10,20,50,100]
// Escapes quotes too: the result is also placed inside HTML attributes (title, data-*, value). The old textContent/innerHTML
// trick left " unescaped, so a saved name like  " onmouseover="...  injected a handler with full bridge access.
function cmdsEscapeHtml(s){
return String(s===undefined||s===null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")
}
function cmdsFilterRows(rows,st){
let list=rows||[]
const q=(st.search||"").trim().toLowerCase()
if(st.linkFilter==="linked")list=list.filter((r)=>r.src==="Commands")
else if(st.linkFilter==="standalone")list=list.filter((r)=>r.src==="CommandsNotes")
if(q)list=list.filter((r)=>[r.title,r.note_name,r.category,r.sub,r.tags,r.command,r.description].join(" ").toLowerCase().includes(q))
if(st.categoryFilter)list=list.filter((r)=>r.category===st.categoryFilter)
const key=st.sortKey,dir=st.sortDir||1
if(!key)return list.slice()
return list.slice().sort((a,b)=>{
const av=(a[key]||"").toString().toLowerCase()
const bv=(b[key]||"").toString().toLowerCase()
if(av<bv)return -1*dir
if(av>bv)return 1*dir
return 0
})
}
function cmdsPageSlice(list,page,size){
const per=Math.max(1,parseInt(size,10)||20)
const pages=Math.max(1,Math.ceil(list.length/per))
const p=Math.min(Math.max(0,page|0),pages-1)
return {rows:list.slice(p*per,p*per+per),page:p,pages}
}
function cmdsBraceContext(text,pos){
const left=String(text||"").slice(0,pos)
const lastOpen=left.lastIndexOf("{")
if(lastOpen<0)return null
const lastClose=left.lastIndexOf("}")
if(lastClose>lastOpen)return null
if(left.slice(lastClose+1,lastOpen).includes("{"))return null
const prefix=left.slice(lastOpen+1)
if(/[{}\r\n]/.test(prefix))return null
return {prefix,start:lastOpen+1,end:pos}
}
function cmdsApplyBraceKey(text,ctx,key){
const t=String(text||"")
const before=t.slice(0,ctx.start)+key
let after=t.slice(ctx.end)
if(!after.startsWith("}"))after="}"+after
return {text:before+after,pos:before.length+1}
}
function cmdsInsertToken(text,selStart,selEnd,token){
const raw=String(token||"").trim().replace(/^\{+|\}+$/g,"")
const t=String(text||"")
if(!raw)return {text:t,pos:selEnd}
const tok="{"+raw+"}"
const before=t.slice(0,selStart)+tok
return {text:before+t.slice(selEnd),pos:before.length}
}
function cmdsElementMatches(rows,prefix,limit){
const p=String(prefix||"").trim().replace(/^\{+|\}+$/g,"").toLowerCase()
const out=(rows||[]).filter((r)=>r&&r.key&&(!p||r.key.toLowerCase().startsWith(p)))
return limit>0?out.slice(0,limit):out
}
function cmdsSplitTags(s){
const out=[],seen=new Set()
String(s||"").replace(/;/g,",").split(",").forEach((p)=>{
const t=p.trim().split(/\s+/).filter(Boolean).join(" ")
if(!t||seen.has(t.toLowerCase()))return
seen.add(t.toLowerCase());out.push(t)
})
return out
}
function cmdsTagContext(text,pos){
const t=String(text||"")
const isSep=(c)=>c===","||c===";"
let start=pos
while(start>0&&!isSep(t[start-1]))start--
let end=pos
while(end<t.length&&!isSep(t[end]))end++
return {prefix:t.slice(start,pos).trim(),start,end}
}
function cmdsTagMatches(all,text,ctx,limit){
const p=(ctx.prefix||"").toLowerCase()
if(!p)return []
const others=new Set(cmdsSplitTags(text.slice(0,ctx.start)+","+text.slice(ctx.end)).map((x)=>x.toLowerCase()))
const seen=new Set()
return (all||[]).filter((tag)=>{
const k=String(tag||"").toLowerCase()
if(!k||seen.has(k)||others.has(k)||k===p||!k.startsWith(p))return false
seen.add(k);return true
}).slice(0,limit||8)
}
function cmdsApplyTag(text,ctx,tag){
const t=String(text||"")
const before=t.slice(0,ctx.start).replace(/\s+$/,"")
const after=t.slice(ctx.end).replace(/^[,;]\s*/,"")
const head=(before?before.replace(/[,;]$/,"")+", ":"")+tag+", "
return {text:head+after,pos:head.length}
}
function cmdsFormSig(d){
return JSON.stringify([d.cmd_note_title,d.command_type,d.noise_level,d.category,d.sub_category,d.description,d.tags,d.command].map((v)=>String(v==null?"":v)))
}
function cmdsRelatedSummary(notes){
const names=(notes||[]).map((n)=>n.note_name||"").filter(Boolean)
const shown=names.slice(0,3)
if(names.length>3)shown.push("+"+(names.length-3)+" more")
return shown.join(", ")||"-"
}
function cmdsSizeLabel(cmd){
const s=String(cmd||"")
const lines=Math.max(1,s.split(/\r?\n/).length)
return s.length+" chars | "+lines+" line"+(lines===1?"":"s")
}
function cmdsFilterSort(){
return cmdsFilterRows(cmdsState.rows,cmdsState)
}
function cmdsRenderCategoryFilter(){
const sel=document.getElementById("cmdsCategoryFilter")
const cur=sel.value
const cats=Array.from(new Set(cmdsState.rows.map((r)=>r.category).filter(Boolean))).sort((a,b)=>a.localeCompare(b))
sel.innerHTML='<option value="">All Categories</option>'+cats.map((c)=>`<option value="${cmdsEscapeHtml(c)}">${cmdsEscapeHtml(c)}</option>`).join("")
sel.value=cats.includes(cur)?cur:""
cmdsState.categoryFilter=sel.value
}
function cmdsRenderRow(row){
const tr=document.createElement("tr")
tr.className="cmds-row"
const tags=(row.tags||"").split(",").map((t)=>t.trim()).filter(Boolean)
tr.innerHTML=`<td class="cmds-cell-title">${cmdsEscapeHtml(row.title)}</td><td>${notesCmdTypeBadgeHtml(row.command_type)}</td><td>${cmdsNoiseBadgeHtml(row.noise_level)}</td><td>${cmdsEscapeHtml(row.category)}</td><td>${cmdsEscapeHtml(row.sub)}</td><td class="cmds-cell-command">${cmdsEscapeHtml(row.command)}</td><td class="cmds-cell-desc" title="${cmdsEscapeHtml(row.description)}">${cmdsEscapeHtml(row.description)}</td><td><div class="cmds-cell-tags">${tags.map((t)=>`<span class="cmds-tag">${cmdsEscapeHtml(t)}</span>`).join("")}</div></td><td><span class="cmds-badge ${row.src==="Commands"?"cmds-badge-linked":"cmds-badge-standalone"}">${row.src==="Commands"?"Linked":"Standalone"}</span></td><td><button type="button" class="cmds-run-btn" title="Run in Terminal"><i class="icon icon-command-line"></i></button></td>`
tr.querySelector(".cmds-run-btn").addEventListener("click",(e)=>{e.stopPropagation();cmdsRunInTerminal(row,undefined,e)})
tr.querySelector(".cmds-run-btn").addEventListener("dblclick",(e)=>e.stopPropagation())
tr.addEventListener("click",(e)=>cmdsHandleRowClick(row,e))
tr.addEventListener("dblclick",(e)=>{e.preventDefault();clearTimeout(cmdsState.clickTimer);cmdsOpenForm(row)})
tr.addEventListener("auxclick",(e)=>{if(e.button===1){e.preventDefault();cmdsRunInTerminal(row,undefined,{destination:"new"})}})
tr.addEventListener("contextmenu",(e)=>{e.preventDefault();cmdsOpenContextMenu(row,e.clientX,e.clientY)})
return tr
}
function cmdsRenderTable(){
const tbody=document.getElementById("cmdsTableBody")
if(!tbody)return
tbody.innerHTML=""
const list=cmdsFilterSort()
const view=cmdsPageSlice(list,cmdsState.page,cmdsState.pageSize)
cmdsState.page=view.page
document.getElementById("cmdsEmptyMsg").classList.toggle("hidden",list.length>0)
view.rows.forEach((row)=>tbody.appendChild(cmdsRenderRow(row)))
document.querySelectorAll(".cmds-table th[data-sort]").forEach((th)=>{
const on=th.dataset.sort===cmdsState.sortKey
th.classList.toggle("sorted",on)
if(!th.dataset.label)th.dataset.label=th.textContent
th.textContent=th.dataset.label+(on?(cmdsState.sortDir>0?" ▲":" ▼"):"")
})
document.getElementById("cmdsTotal").textContent="Total: "+list.length
document.getElementById("cmdsPageLabel").textContent=(view.page+1)+" of "+view.pages
document.getElementById("cmdsPagePrev").disabled=view.page<=0
document.getElementById("cmdsPageNext").disabled=view.page>=view.pages-1
}
function cmdsCopyCommand(row){
if(navigator.clipboard)navigator.clipboard.writeText(row.command||"").catch(()=>{})
}
const NOISE_LEVEL_OPTIONS=["stealthy","normal","noisy","destructive"]
function cmdsNoiseBadgeHtml(level){
const v=(level||"normal").toLowerCase()
return `<span class="cmds-noise cmds-noise-${cmdsEscapeHtml(v)}">${cmdsEscapeHtml(v)}</span>`
}
function cmdsTargetSnapshot(){
return bridgeCall("search.live_target").then((res)=>(res&&res.map)||{}).catch(()=>({}))
}
function cmdsRecordRun(row,text){
return cmdsTargetSnapshot().then((snap)=>bridgeCall("commands.record_run",[row.id,row.src,text,snap]).catch(()=>{}))
}
// Fill {KEY} placeholders from the live target, as Snippets does; keys without a live value stay as {KEY} for the run prompt.
function cmdsApplyLiveMap(text,map){
if(typeof snipIterPlaceholders!=="function"||!map||!Object.keys(map).length)return text
let out="",last=0
snipIterPlaceholders(text).forEach(([start,end,key])=>{
out+=text.slice(last,start)
const lk=key.toLowerCase()
out+=Object.prototype.hasOwnProperty.call(map,lk)?map[lk]:text.slice(start,end)
last=end
})
return out+text.slice(last)
}
function cmdsResolveLive(text){return cmdsTargetSnapshot().then((map)=>cmdsApplyLiveMap(text,map))}
function cmdsRunInTerminal(row,textOverride,event){
const raw=textOverride!==undefined?textOverride:(row.command||"")
if(!raw.trim()){showToast("Nothing to run","error");return}
const meta={noise_level:row.noise_level,confirmMode:termState.commandRunConfirm,destination:event&&event.destination?event.destination:undefined}
;(textOverride!==undefined?Promise.resolve(raw):cmdsResolveLive(raw)).then((text)=>termDispatchRun(text,meta).then((id)=>{
if(id)cmdsRecordRun(row,text)
})).catch((err)=>showToast(err&&err.message?err.message:"Run failed","error"))
}
function cmdsHandleRowClick(row,event){
if(event&&event.altKey){cmdsCopyCommand(row);showToast("Copied raw command");return}
clearTimeout(cmdsState.clickTimer)
if(event&&event.detail>1)return
const ev={ctrlKey:event.ctrlKey,metaKey:event.metaKey,shiftKey:event.shiftKey,altKey:false,clientX:event.clientX,clientY:event.clientY}
cmdsState.clickTimer=setTimeout(()=>{
const action=termResolveClickAction(termState.commandClickAction,ev)
if(action==="copy"){cmdsOpenInfoPanel(row);return}
if(action==="run"){cmdsRunInTerminal(row,undefined,ev);return}
const meta={noise_level:row.noise_level,confirmMode:termState.commandRunConfirm}
cmdsResolveLive(row.command||"").then((text)=>termPerformClickAction(action,text,meta,ev))
},240)
}
function cmdsOpenRelatedNote(row,x,y){
if(row.src!=="Commands"){showToast("This command is not linked to a note.","error");return}
snipShowInNote(row,x==null?Math.round(window.innerWidth/2-140):x,y==null?120:y)
}
function cmdsDeleteCommand(row){
if(row.src!=="CommandsNotes"){
const name=row.note_name&&row.note_name!=="Unlinked"?row.note_name:"(unknown note)"
appConfirm(`You can't delete this here. This command belongs to Note: ${name}. Delete it from the original note, or delete the note itself.`,{okLabel:"Open Note",cancelLabel:"Close"}).then((yes)=>{if(yes)cmdsOpenRelatedNote(row)})
return
}
appConfirm(`Delete "${row.title}"? This moves it to the Recycle Bin.`,{okLabel:"Delete",danger:true}).then((yes)=>{
if(!yes)return
bridgeCall("commands.delete",[row.id,row.src]).then(()=>cmdsRefresh()).catch((err)=>showToast(err&&err.message?err.message:"Delete failed","error"))
})
}
function cmdsOpenContextMenu(row,x,y){
const items=[{label:"Command Info",icon:"info",fn:()=>cmdsOpenInfoPanel(row)},{label:"Copy Command",icon:"copy",fn:()=>cmdsCopyCommand(row)},{label:"Run in Terminal",icon:"command-line",fn:()=>cmdsRunInTerminal(row)},{label:"Run against targets...",icon:"target",fn:()=>termOpenFanoutModal(row.command||"",{noise_level:row.noise_level})}]
if(row.src==="Commands")items.push({label:"Open Related Note",icon:"edit",fn:()=>cmdsOpenRelatedNote(row,x,y)})
items.push({label:"Edit",icon:"edit",fn:()=>cmdsOpenForm(row)})
items.push({label:"Delete",icon:"close",fn:()=>cmdsDeleteCommand(row),danger:row.src==="CommandsNotes"})
openContextMenu(items,x,y)
}
function cmdsCloseInfoPanel(){
const overlay=document.getElementById("cmdsInfoOverlay")
if(overlay)overlay.remove()
const panel=document.getElementById("cmdsInfoPanel")
if(panel)panel.remove()
}
function cmdsInfoRowHtml(label,value,id){
return `<div class="cmds-info-row"><label>${cmdsEscapeHtml(label)}</label><div${id?` id="${id}"`:""}>${cmdsEscapeHtml(value||"-")}</div></div>`
}
function cmdsOpenInfoPanel(row){
cmdsCloseInfoPanel()
const overlay=document.createElement("div")
overlay.id="cmdsInfoOverlay"
overlay.className="cmds-panel-overlay"
overlay.addEventListener("click",cmdsCloseInfoPanel)
document.body.appendChild(overlay)
const tags=(row.tags||"").split(",").map((t)=>t.trim()).filter(Boolean)
const linked=row.src==="Commands"
const panel=document.createElement("div")
panel.id="cmdsInfoPanel"
panel.className="cmds-info-panel glass-panel"
panel.innerHTML=`<div class="cmds-info-head"><h3>${cmdsEscapeHtml(row.title)}</h3>${notesCmdTypeBadgeHtml(row.command_type)}${cmdsNoiseBadgeHtml(row.noise_level)}<button class="cmds-info-close" id="cmdsInfoCloseBtn">&times;</button></div>${cmdsInfoRowHtml("Type",linked?"Linked to Note":"Standalone")}${cmdsInfoRowHtml("Used In",linked?"...":"0 notes","cmdsInfoUsedIn")}${linked?cmdsInfoRowHtml("Related Notes","...","cmdsInfoRelated"):""}${cmdsInfoRowHtml("Group",row.group_name)}${cmdsInfoRowHtml("Category",(row.category||"")+" / "+(row.sub||""))}${row.description?cmdsInfoRowHtml("Description",row.description):""}${cmdsInfoRowHtml("Size",cmdsSizeLabel(row.command))}<div class="cmds-info-row"><label>Command</label><pre class="cmds-info-code">${cmdsEscapeHtml(row.command)}</pre></div>${tags.length?`<div class="cmds-info-row"><label>Tags</label><div class="cmds-cell-tags">${tags.map((t)=>`<span class="cmds-tag">${cmdsEscapeHtml(t)}</span>`).join("")}</div></div>`:""}<div class="cmds-info-links hidden" id="cmdsInfoLinks"></div><div class="cmds-info-runs hidden" id="cmdsInfoRuns"></div><div class="cmds-info-actions"><button id="cmdsInfoCopyBtn">Copy</button><button id="cmdsInfoRunBtn">Run</button>${linked?'<button id="cmdsInfoRelatedBtn" disabled>Open Related</button>':""}<button id="cmdsInfoEditBtn">Edit</button>${row.src==="CommandsNotes"?'<button class="danger" id="cmdsInfoDeleteBtn">Delete</button>':""}</div>`
document.body.appendChild(panel)
panel.querySelector("#cmdsInfoCloseBtn").addEventListener("click",cmdsCloseInfoPanel)
panel.querySelector("#cmdsInfoCopyBtn").addEventListener("click",()=>{cmdsCopyCommand(row);showToast("Copied command")})
panel.querySelector("#cmdsInfoRunBtn").addEventListener("click",()=>cmdsRunInTerminal(row))
panel.querySelector("#cmdsInfoEditBtn").addEventListener("click",()=>{cmdsCloseInfoPanel();cmdsOpenForm(row)})
const delBtn=panel.querySelector("#cmdsInfoDeleteBtn")
if(delBtn)delBtn.addEventListener("click",()=>{cmdsCloseInfoPanel();cmdsDeleteCommand(row)})
bridgeCall("commands.runs",[row.id,row.src]).then((runs)=>{
if(!runs.length)return
const wrap=document.getElementById("cmdsInfoRuns")
if(!wrap)return
wrap.classList.remove("hidden")
wrap.innerHTML='<label class="cmds-info-links-title">Recently run</label>'+runs.map((r)=>`<div class="cmds-info-run-item" title="${cmdsEscapeHtml(r.text)}"><span>${cmdsEscapeHtml(r.ran_at)}</span></div>`).join("")
}).catch(()=>{})
if(linked){
bridgeCall("search.related_notes",[row]).then((all)=>{
if(document.getElementById("cmdsInfoPanel")!==panel)return
const notes=all||[]
const openable=notes.filter((n)=>n.note_id!=null)
panel.querySelector("#cmdsInfoUsedIn").textContent=notes.length+" note"+(notes.length===1?"":"s")
panel.querySelector("#cmdsInfoRelated").textContent=cmdsRelatedSummary(notes)
const relBtn=panel.querySelector("#cmdsInfoRelatedBtn")
relBtn.disabled=!openable.length
relBtn.addEventListener("click",(e)=>{cmdsCloseInfoPanel();cmdsOpenRelatedNote(row,e.clientX-280,e.clientY-120)})
if(!openable.length)return
const wrap=panel.querySelector("#cmdsInfoLinks")
wrap.classList.remove("hidden")
wrap.innerHTML='<label class="cmds-info-links-title">Used in '+openable.length+" note"+(openable.length===1?"":"s")+"</label>"
openable.forEach((r)=>{
const btn=document.createElement("button")
btn.className="cmds-info-link-item"
btn.textContent=(r.note_name||"Untitled")+(r.group_name?"  |  "+r.group_name:"")
btn.addEventListener("click",()=>{cmdsCloseInfoPanel();goToPage("notes").then(()=>notesOpen(r.note_id))})
wrap.appendChild(btn)
})
}).catch((err)=>console.error("related notes failed",err))
}
}
function cmdsClosePopover(){
closeModal(true)
}
function cmdsSuggestHide(){
const el=document.getElementById("cmdsSuggest")
if(el)el.remove()
cmdsSuggestState={items:[],selected:0,onPick:null,input:null}
}
let cmdsSuggestState={items:[],selected:0,onPick:null,input:null}
function cmdsSuggestRender(){
const st=cmdsSuggestState
let el=document.getElementById("cmdsSuggest")
if(!st.items.length||!st.input){cmdsSuggestHide();return}
if(!el){
el=document.createElement("div")
el.id="cmdsSuggest"
el.className="cmds-suggest glass-panel"
document.body.appendChild(el)
}
el.innerHTML=""
st.items.forEach((it,i)=>{
const b=document.createElement("button")
b.type="button"
b.className="cmds-suggest-item"+(i===st.selected?" active":"")
b.textContent=it.label
if(it.title)b.title=it.title
b.addEventListener("mousedown",(e)=>{e.preventDefault();cmdsSuggestPick(i)})
el.appendChild(b)
})
const input=st.input
let top,left
if(input.tagName==="TEXTAREA"&&typeof notesCaretCoords==="function"){const c=notesCaretCoords(input,input.selectionStart);top=c.top;left=c.left}
else{const r=input.getBoundingClientRect();top=r.bottom+2;left=r.left}
el.style.top=Math.round(Math.max(4,Math.min(top,window.innerHeight-el.offsetHeight-8)))+"px"
el.style.left=Math.round(Math.max(4,Math.min(left,window.innerWidth-el.offsetWidth-8)))+"px"
}
function cmdsSuggestShow(input,items,onPick){
cmdsSuggestState={items,selected:0,onPick,input}
cmdsSuggestRender()
}
function cmdsSuggestPick(i){
const st=cmdsSuggestState
const it=st.items[i]
const fn=st.onPick
cmdsSuggestHide()
if(it&&fn)fn(it)
}
function cmdsSuggestKeydown(e,input){
const st=cmdsSuggestState
if(!st.items.length||st.input!==input)return false
if(e.key==="ArrowDown"){e.preventDefault();st.selected=Math.min(st.items.length-1,st.selected+1);cmdsSuggestRender();return true}
if(e.key==="ArrowUp"){e.preventDefault();st.selected=Math.max(0,st.selected-1);cmdsSuggestRender();return true}
if(e.key==="Enter"||e.key==="Tab"){e.preventDefault();cmdsSuggestPick(st.selected);return true}
if(e.key==="Escape"){e.preventDefault();cmdsSuggestHide();return true}
return false
}
function cmdsWireCommandSuggest(ta,getRows,markDirty){
function refresh(){
const ctx=cmdsBraceContext(ta.value,ta.selectionStart)
if(!ctx||ta.selectionStart!==ta.selectionEnd||document.activeElement!==ta){if(cmdsSuggestState.input===ta)cmdsSuggestHide();return}
getRows().then((rows)=>{
const ctx2=cmdsBraceContext(ta.value,ta.selectionStart)
if(!ctx2||document.activeElement!==ta)return
const items=cmdsElementMatches(rows,ctx2.prefix,3).map((r)=>({label:r.token||"{"+r.key+"}",key:r.key,title:"Usage: "+(r.usage||0)+" | Priority: "+(r.priority||0)}))
if(!items.length){if(cmdsSuggestState.input===ta)cmdsSuggestHide();return}
cmdsSuggestShow(ta,items,(it)=>{
const c=cmdsBraceContext(ta.value,ta.selectionStart)
if(!c)return
const res=cmdsApplyBraceKey(ta.value,c,it.key)
ta.value=res.text
ta.selectionStart=ta.selectionEnd=res.pos
ta.focus()
markDirty()
})
})
}
ta.addEventListener("keydown",(e)=>{
if(cmdsSuggestKeydown(e,ta))return
if(e.key==="{"&&!e.ctrlKey&&!e.metaKey&&!e.altKey){
e.preventDefault()
const s=ta.selectionStart,en=ta.selectionEnd
ta.value=ta.value.slice(0,s)+"{}"+ta.value.slice(en)
ta.selectionStart=ta.selectionEnd=s+1
markDirty()
refresh()
return
}
if(e.key==="}"&&cmdsSuggestState.input===ta)cmdsSuggestHide()
if(e.key==="}"&&!e.ctrlKey&&!e.metaKey&&!e.altKey&&ta.selectionStart===ta.selectionEnd&&ta.value.charAt(ta.selectionStart)==="}"){e.preventDefault();ta.selectionStart=ta.selectionEnd=ta.selectionStart+1}
})
ta.addEventListener("input",refresh)
ta.addEventListener("click",refresh)
ta.addEventListener("blur",()=>setTimeout(()=>{if(cmdsSuggestState.input===ta&&document.activeElement!==ta)cmdsSuggestHide()},150))
}
function cmdsWireTagSuggest(input){
function refresh(){
const ctx=cmdsTagContext(input.value,input.selectionStart)
const items=cmdsTagMatches(cmdsState.history.tags||[],input.value,ctx,8).map((t)=>({label:t,tag:t}))
if(!items.length||document.activeElement!==input){if(cmdsSuggestState.input===input)cmdsSuggestHide();return}
cmdsSuggestShow(input,items,(it)=>{
const c=cmdsTagContext(input.value,input.selectionStart)
const res=cmdsApplyTag(input.value,c,it.tag)
input.value=res.text
input.selectionStart=input.selectionEnd=res.pos
input.focus()
input.dispatchEvent(new Event("input"))
})
}
input.addEventListener("keydown",(e)=>{cmdsSuggestKeydown(e,input)})
input.addEventListener("input",refresh)
input.addEventListener("blur",()=>setTimeout(()=>{if(cmdsSuggestState.input===input&&document.activeElement!==input)cmdsSuggestHide()},150))
}
function cmdsOpenElementsPanel(pop,ta,getRows,markDirty){
const panel=pop.querySelector("#cmdsElementsPanel")
if(!panel.classList.contains("hidden")){panel.classList.add("hidden");return}
const sel={start:ta.selectionStart,end:ta.selectionEnd}
panel.classList.remove("hidden")
const search=panel.querySelector("#cmdsElementsSearch")
const list=panel.querySelector("#cmdsElementsList")
search.value=""
list.innerHTML='<div class="cmds-elements-empty">Loading...</div>'
function insert(r){
const res=cmdsInsertToken(ta.value,sel.start,sel.end,r.token||r.key)
ta.value=res.text
panel.classList.add("hidden")
ta.focus()
ta.selectionStart=ta.selectionEnd=res.pos
markDirty()
}
getRows().then((rows)=>{
function render(){
const q=search.value.trim().replace(/^\{+|\}+$/g,"").toLowerCase()
const shown=(rows||[]).filter((r)=>!q||(r.key+" "+(r.source||"")).toLowerCase().includes(q))
list.innerHTML=shown.length?"":'<div class="cmds-elements-empty">No elements found</div>'
shown.forEach((r)=>{
const b=document.createElement("button")
b.type="button"
b.className="cmds-elements-item"
b.innerHTML=`<span class="cmds-elements-token">${cmdsEscapeHtml(r.token||"{"+r.key+"}")}</span><span class="cmds-elements-meta">${cmdsEscapeHtml("used "+(r.usage||0)+" | "+(r.source||""))}</span>`
b.title="Usage: "+(r.usage||0)+" | Priority: "+(r.priority||0)+" | Source: "+(r.source||"")
b.addEventListener("click",()=>insert(r))
list.appendChild(b)
})
}
search.oninput=render
search.onkeydown=(e)=>{if(e.key==="Enter"){e.preventDefault();const first=list.querySelector(".cmds-elements-item");if(first)first.click()}}
render()
search.focus()
})
}
function cmdsOpenForm(row){
const isEdit=!!row
const isLinked=isEdit&&row.src==="Commands"
const pop=document.createElement("div")
pop.id="cmdsFormPopover"
pop.className="cmds-popover glass-panel"
const typeOptions=COMMAND_TYPE_OPTIONS.map((t)=>`<option value="${cmdsEscapeHtml(t)}">${cmdsEscapeHtml(t)}</option>`).join("")
const noiseOptions=NOISE_LEVEL_OPTIONS.map((t)=>`<option value="${t}">${t.charAt(0).toUpperCase()+t.slice(1)}</option>`).join("")
pop.innerHTML=`<div class="cmds-popover-title">${isEdit?"Edit Command":"New Command"}</div><div class="cmds-popover-warning hidden" id="cmdsFormWarning"></div><div class="cmds-popover-field"><label>Command Note Title</label><input type="text" id="cmdsFieldTitle" list="cmdsNoteHistory"></div><div class="cmds-popover-field"><label>Command Type</label><select id="cmdsFieldType">${typeOptions}</select></div><div class="cmds-popover-field hidden" id="cmdsFieldTypeOtherWrap"><label>Custom Type</label><input type="text" id="cmdsFieldTypeOther"></div><div class="cmds-popover-field"><label>OPSEC / Noise Level</label><select id="cmdsFieldNoise">${noiseOptions}</select></div><div class="cmds-popover-field"><label>Category</label><input type="text" id="cmdsFieldCategory" list="cmdsCategoryHistory"></div><div class="cmds-popover-field"><label>Sub Category</label><input type="text" id="cmdsFieldSub" list="cmdsSubHistory"></div><div class="cmds-popover-field"><label>Description</label><input type="text" id="cmdsFieldDesc"></div><div class="cmds-popover-field"><label>Tags (comma separated)</label><input type="text" id="cmdsFieldTags" autocomplete="off"></div><div class="cmds-popover-field cmds-command-field"><div class="cmds-field-head"><label>Command</label><button type="button" class="cmds-elements-btn" id="cmdsElementsBtn" title="Insert an existing target element">{ } Elements</button></div><textarea id="cmdsFieldCommand" placeholder="Type { to insert a target element"></textarea><div class="cmds-elements-panel hidden" id="cmdsElementsPanel"><input type="text" id="cmdsElementsSearch" placeholder="Search elements..." autocomplete="off"><div class="cmds-elements-list" id="cmdsElementsList"></div></div></div><div class="cmds-popover-error hidden" id="cmdsFormError"></div><div class="cmds-popover-actions"><button type="button" id="cmdsFormCancel">Cancel</button><button type="button" class="cmds-popover-confirm" id="cmdsFormSave">${isEdit?"Save":"Create"}</button></div>`
const typeSelect=pop.querySelector("#cmdsFieldType")
const typeOtherWrap=pop.querySelector("#cmdsFieldTypeOtherWrap")
const typeOtherInput=pop.querySelector("#cmdsFieldTypeOther")
const ta=pop.querySelector("#cmdsFieldCommand")
const elementsPanel=pop.querySelector("#cmdsElementsPanel")
let savedSig="",saving=false,elementRows=null
function getRows(){
if(!elementRows)elementRows=bridgeCall("commands.target_elements",["",0]).catch(()=>{elementRows=null;return []})
return elementRows
}
function readForm(){
const commandType=typeSelect.value==="Other"?(typeOtherInput.value.trim()||"Other"):typeSelect.value
return {cmd_note_title:pop.querySelector("#cmdsFieldTitle").value.trim(),category:pop.querySelector("#cmdsFieldCategory").value.trim(),sub_category:pop.querySelector("#cmdsFieldSub").value.trim(),description:pop.querySelector("#cmdsFieldDesc").value.trim(),tags:pop.querySelector("#cmdsFieldTags").value.trim(),command:ta.value,command_type:commandType,noise_level:pop.querySelector("#cmdsFieldNoise").value}
}
const isDirty=()=>cmdsFormSig(readForm())!==savedSig
function save(){
if(saving)return Promise.resolve(false)
const data=readForm()
const errEl=pop.querySelector("#cmdsFormError")
errEl.classList.add("hidden")
let action
if(!isEdit)action=bridgeCall("commands.create",[data.cmd_note_title,data.category,data.sub_category,data.command,data.tags,data.description,data.command_type,data.noise_level])
else if(isLinked)action=bridgeCall("commands.update_linked",[row,data])
else action=bridgeCall("commands.update",[row.id,data.cmd_note_title,data.category,data.sub_category,data.command,data.tags,data.description,data.command_type,data.noise_level])
saving=true
return action.then(()=>{saving=false;cmdsSuggestHide();cmdsClosePopover();cmdsRefresh();return true}).catch((err)=>{
saving=false
errEl.textContent=err&&err.message?err.message:"Save failed"
errEl.classList.remove("hidden")
return false
})
}
function beforeClose(){
cmdsSuggestHide()
if(!isDirty())return true
return appConfirm("You have unsaved changes to this command.",{okLabel:"Save",extraLabel:"Discard",cancelLabel:"Keep Editing"}).then((r)=>{
if(r==="extra")return true
if(r===true)return save().then(()=>false)
return false
})
}
function onEscape(){
if(cmdsSuggestState.items.length){cmdsSuggestHide();return false}
if(!elementsPanel.classList.contains("hidden")){elementsPanel.classList.add("hidden");ta.focus();return false}
return true
}
openModal(pop,{closeOnBackdrop:false,onBeforeClose:beforeClose,onEscape})
function syncTypeOtherVisibility(){
typeOtherWrap.classList.toggle("hidden",typeSelect.value!=="Other")
}
typeSelect.addEventListener("change",syncTypeOtherVisibility)
if(isEdit){
pop.querySelector("#cmdsFieldTitle").value=row.cmd_note_title||row.title||""
const existingType=row.command_type||"other"
if(COMMAND_TYPE_OPTIONS.some((t)=>t.toLowerCase()===existingType.toLowerCase())){
typeSelect.value=COMMAND_TYPE_OPTIONS.find((t)=>t.toLowerCase()===existingType.toLowerCase())
}else{
typeSelect.value="Other"
typeOtherInput.value=row.command_type||""
}
pop.querySelector("#cmdsFieldNoise").value=NOISE_LEVEL_OPTIONS.includes(row.noise_level)?row.noise_level:"normal"
pop.querySelector("#cmdsFieldCategory").value=row.category||""
pop.querySelector("#cmdsFieldSub").value=row.sub||""
pop.querySelector("#cmdsFieldDesc").value=row.description||""
pop.querySelector("#cmdsFieldTags").value=row.tags||""
ta.value=row.command||""
}else{
const h=cmdsState.history||{}
pop.querySelector("#cmdsFieldTitle").value=h.last_note||""
pop.querySelector("#cmdsFieldCategory").value=h.last_category||""
pop.querySelector("#cmdsFieldSub").value=h.last_subcategory||""
pop.querySelector("#cmdsFieldNoise").value="normal"
}
syncTypeOtherVisibility()
savedSig=cmdsFormSig(readForm())
if(isLinked){
bridgeCall("commands.linked_note_count",[row]).then((count)=>{
if(count>=1){
const w=pop.querySelector("#cmdsFormWarning")
w.textContent="This command is used in "+count+" note"+(count===1?"":"s")+". If you update it here, it will be updated in all related notes."
w.classList.remove("hidden")
}
}).catch(()=>{})
}
cmdsWireCommandSuggest(ta,getRows,()=>{})
cmdsWireTagSuggest(pop.querySelector("#cmdsFieldTags"))
pop.querySelector("#cmdsElementsBtn").addEventListener("click",()=>cmdsOpenElementsPanel(pop,ta,getRows,()=>{}))
pop.querySelector("#cmdsFormCancel").addEventListener("click",()=>closeModal())
pop.querySelector("#cmdsFormSave").addEventListener("click",save)
const titleEl=pop.querySelector("#cmdsFieldTitle")
;(isEdit||titleEl.value?ta:titleEl).focus()
}
function cmdsPopulateHistoryLists(){
const h=cmdsState.history
document.getElementById("cmdsNoteHistory").innerHTML=(h.notes||[]).map((n)=>`<option value="${cmdsEscapeHtml(n)}">`).join("")
document.getElementById("cmdsCategoryHistory").innerHTML=(h.categories||[]).map((n)=>`<option value="${cmdsEscapeHtml(n)}">`).join("")
document.getElementById("cmdsSubHistory").innerHTML=(h.subcategories||[]).map((n)=>`<option value="${cmdsEscapeHtml(n)}">`).join("")
}
function cmdsRefresh(){
return bridgeCall("commands.stamp").catch(()=>"").then((stamp)=>Promise.all([bridgeCall("commands.list"),bridgeCall("commands.history")]).then((results)=>{
cmdsState.stamp=stamp||""
cmdsState.rows=results[0]
cmdsState.history=results[1]
cmdsRenderCategoryFilter()
cmdsRenderTable()
cmdsPopulateHistoryLists()
}))
}
function cmdsPageActive(){
const p=document.querySelector('.page[data-page="commands"]')
return !!(p&&p.classList.contains("active"))&&!document.hidden
}
function cmdsPollStamp(){
if(!cmdsPageActive()||!cmdsState.stamp)return
bridgeCall("commands.stamp").then((st)=>{if(st&&st!==cmdsState.stamp)cmdsRefresh()}).catch(()=>{})
}
function cmdsWireTableHeader(){
document.querySelectorAll(".cmds-table th[data-sort]").forEach((th)=>{
th.addEventListener("click",()=>{
const key=th.dataset.sort
if(cmdsState.sortKey===key)cmdsState.sortDir*=-1
else{cmdsState.sortKey=key;cmdsState.sortDir=1}
cmdsState.page=0
cmdsRenderTable()
})
})
}
function initCommands(){
return fetch("../pages/commands.html").then((r)=>r.text()).then((html)=>{
document.querySelector('.page[data-page="commands"]').innerHTML=html
document.getElementById("cmdsSearchInput").addEventListener("input",(e)=>{cmdsState.search=e.target.value;cmdsState.page=0;cmdsRenderTable()})
document.getElementById("cmdsCategoryFilter").addEventListener("change",(e)=>{cmdsState.categoryFilter=e.target.value;cmdsState.page=0;cmdsRenderTable()})
document.getElementById("cmdsLinkFilter").addEventListener("change",(e)=>{cmdsState.linkFilter=e.target.value;cmdsState.page=0;cmdsRenderTable()})
const sizeSel=document.getElementById("cmdsPageSize")
sizeSel.value=String(cmdsState.pageSize)
// Saved through the bridge: WebKitGTK runs in private mode, where localStorage does not exist.
bridgeCall("commands.get_page_size").then((ps)=>{ps=parseInt(ps,10);if(CMDS_PAGE_SIZES.includes(ps)&&ps!==cmdsState.pageSize){cmdsState.pageSize=ps;sizeSel.value=String(ps);cmdsState.page=0;cmdsRenderTable()}}).catch(()=>{})
sizeSel.addEventListener("change",()=>{cmdsState.pageSize=parseInt(sizeSel.value,10)||20;cmdsState.page=0;bridgeCall("commands.set_page_size",[cmdsState.pageSize]).catch(()=>{});cmdsRenderTable()})
document.getElementById("cmdsPagePrev").addEventListener("click",()=>{cmdsState.page--;cmdsRenderTable()})
document.getElementById("cmdsPageNext").addEventListener("click",()=>{cmdsState.page++;cmdsRenderTable()})
document.addEventListener("loya:page-shown",(e)=>{if(e.detail&&e.detail.page==="commands"&&!e.detail.first)cmdsRefresh().catch((err)=>console.error("commands refresh failed",err))})
// A key rename or merge in Targets rewrites {KEY}s inside saved commands, so reload the table.
document.addEventListener("loya:target-keys-changed",()=>{cmdsRefresh().catch((err)=>console.error("commands refresh failed",err))})
if(cmdsState.pollTimer)clearInterval(cmdsState.pollTimer)
cmdsState.pollTimer=setInterval(cmdsPollStamp,3000)
document.getElementById("cmdsNewBtn").addEventListener("click",()=>cmdsOpenForm(null))
cmdsWireTableHeader()
return cmdsRefresh()
}).catch((err)=>console.error("commands init failed",err))
}
