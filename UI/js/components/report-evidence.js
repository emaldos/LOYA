// Reporting evidence: the evidence picker and manager, the auto-generate wizard, and the terminal session recorder.
// Everything is reached through window.ReportEvidence; the terminal calls it through hooks guarded with `window.ReportEvidence&&`.
(function(root){
const REV_FLUSH_MS=2000
const REV_FLUSH_CHARS=256*1024
const REV_QUEUE_MAX=2*1024*1024
const REV_KINDS=[{id:"",label:"All"},{id:"command",label:"Commands"},{id:"recording",label:"Recordings"},{id:"text",label:"Text"},{id:"image",label:"Screenshots"}]
const REV_SEVERITIES=[{id:"critical",label:"Critical"},{id:"high",label:"High"},{id:"medium",label:"Medium"},{id:"low",label:"Low"},{id:"info",label:"Informational"}]
// ---- pure helpers (also exported for the Node runner)
function revEsc(s){
return String(s===undefined||s===null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")
}
function revPad(n){return (n<10?"0":"")+n}
function revElapsed(ms){
const total=Math.max(0,Math.floor((Number(ms)||0)/1000))
const h=Math.floor(total/3600),m=Math.floor((total%3600)/60),s=total%60
return (h?h+":"+revPad(m):revPad(m))+":"+revPad(s)
}
function revSize(n){
n=Number(n)||0
if(n<1024)return n+" B"
if(n<1024*1024)return (n/1024).toFixed(n<10240?1:0)+" KB"
return (n/1024/1024).toFixed(1)+" MB"
}
function revWhen(iso){
if(!iso)return ""
const d=new Date(iso)
if(isNaN(d.getTime()))return String(iso)
return d.getFullYear()+"-"+revPad(d.getMonth()+1)+"-"+revPad(d.getDate())+" "+revPad(d.getHours())+":"+revPad(d.getMinutes())
}
function revKindLabel(kind){
return {command:"Command",recording:"Recording",text:"Text",image:"Screenshot"}[kind]||"Evidence"
}
function revSevLabel(id){
const sev=REV_SEVERITIES.find((s)=>s.id===id)
return sev?sev.label:"Informational"
}
function revSessionsOf(list){
const seen={},out=[]
;(list||[]).forEach((ev)=>{
const id=ev&&ev.session_id
if(!id||seen[id])return
seen[id]=true
out.push({id,label:(ev.meta&&ev.meta.session_label)||("Session "+String(id).slice(0,6))})
})
return out
}
function revFilter(list,f){
f=f||{}
const q=String(f.query||"").trim().toLowerCase()
return (list||[]).filter((ev)=>{
if(f.kind&&ev.kind!==f.kind)return false
if(f.kinds&&f.kinds.length&&f.kinds.indexOf(ev.kind)<0)return false
if(f.session&&ev.session_id!==f.session)return false
if(!q)return true
const tags=ev.meta&&Array.isArray(ev.meta.tags)?ev.meta.tags.join(" "):""
return [ev.title,ev.command,ev.target,ev.preview,ev.meta&&ev.meta.notes,tags].some((v)=>String(v||"").toLowerCase().indexOf(q)>=0)
})
}
// What a terminal job block becomes when it is saved: the slice of the tab buffer between the job's offsets.
function revJobInfo(tab,record){
if(!tab||!record)return null
let end=record.endIdx===null||record.endIdx===undefined?(tab.buffer||"").length:record.endIdx
// The terminal closes a job when its result marker arrives; a command typed right after is already in the buffer by then, so the slice stops where the next job starts.
const start=Math.max(0,record.startIdx||0)
;(tab.jobHistory||[]).concat(tab.activeJob?[tab.activeJob]:[]).forEach((j)=>{if(j&&j!==record&&j.jobId!==record.jobId&&j.startIdx>start&&j.startIdx<end)end=j.startIdx})
return {session_id:tab.sessionId,job_key:record.jobId,command:record.command||"",output:(tab.buffer||"").slice(Math.max(0,record.startIdx||0),end),exit_code:record.exitCode===undefined?null:record.exitCode,cwd:tab.cwd||"",started_at:record.startedAt||null,ended_at:record.endedAt||null,shell:tab.shellId||"",session_label:tab.label||""}
}
// Buffers one session's events between flushes. Consecutive output is merged into one event; when the backend cannot be
// reached the oldest output is dropped (with a marker) instead of growing without bound.
function RevQueue(now){
this.now=now||(()=>new Date().toISOString())
this.events=[]
this.chars=0
this.dropped=false
}
RevQueue.prototype.push=function(kind,data){
const last=this.events[this.events.length-1]
if(kind==="out"){
const text=String(data||"")
if(!text)return
if(last&&last.kind==="out")last.data+=text
else this.events.push({ts:this.now(),kind:"out",data:text})
this.chars+=text.length
}else{
this.events.push({ts:this.now(),kind,data})
this.chars+=typeof data==="string"?data.length:32
}
while(this.chars>REV_QUEUE_MAX){
const at=this.events.findIndex((e)=>e.kind==="out")
if(at<0)break
this.chars-=this.events[at].data.length
this.events.splice(at,1)
if(!this.dropped){this.dropped=true;this.events.splice(at,0,{ts:this.now(),kind:"mark",data:"Some output was not recorded (the recorder could not reach the evidence store)."})}
}
}
RevQueue.prototype.take=function(){
const out=this.events
this.events=[];this.chars=0;this.dropped=false
return out
}
RevQueue.prototype.putBack=function(events){
this.events=events.concat(this.events)
this.chars=this.events.reduce((n,e)=>n+(typeof e.data==="string"?e.data.length:32),0)
}
function revToolSummary(preview){
const p=preview||{}
const hosts=(p.hosts||[]).length
const ports=(p.hosts||[]).reduce((n,h)=>n+(h.ports||[]).length,0)
return {commands:(p.timeline||[]).length,tools:(p.tools||[]).length,hosts,ports,candidates:(p.candidates||[]).length}
}
function revDefaultAccepted(candidates){
const out={}
;(candidates||[]).forEach((c)=>{out[c.key]=c.confidence!=="low"})
return out
}
function revDefaultTitle(profileName,date){
const d=date||new Date()
return "Penetration test report"+(profileName&&profileName!=="Default"?" - "+profileName:"")+" - "+d.getFullYear()+"-"+revPad(d.getMonth()+1)+"-"+revPad(d.getDate())
}
const pure={esc:revEsc,elapsed:revElapsed,size:revSize,when:revWhen,kindLabel:revKindLabel,sevLabel:revSevLabel,sessionsOf:revSessionsOf,filter:revFilter,jobInfo:revJobInfo,Queue:RevQueue,summary:revToolSummary,defaultAccepted:revDefaultAccepted,defaultTitle:revDefaultTitle,QUEUE_MAX:REV_QUEUE_MAX}
if(typeof module!=="undefined"&&module.exports)module.exports=pure
if(typeof document==="undefined")return
// ---- shared UI plumbing
function revCall(method,args){return bridgeCall("evidence."+method,args||[])}
function revToast(message,isError){
if(typeof showToast==="function")showToast(message,isError?"error":undefined)
}
function revFail(fallback){
return (err)=>{revToast(err&&err.message?err.message:fallback,true)}
}
function revConfirm(message,opts){
if(typeof appConfirm==="function")return appConfirm(message,opts)
return Promise.resolve(window.confirm(message))
}
const revOverlays=[]
function revKeydown(e){
if(e.key!=="Escape"||!revOverlays.length)return
if(document.querySelector(".confirm-overlay"))return
e.stopPropagation();e.preventDefault()
revOverlays[revOverlays.length-1].close()
}
// The app's openModal holds one modal at a time, and the picker is opened from inside other modals (the finding editor),
// so these dialogs stack on their own overlay.
function revOverlay(opts){
opts=opts||{}
const wrap=document.createElement("div")
wrap.className="rpt-ev-overlay"
const card=document.createElement("div")
card.className="rpt-ev-modal glass-panel"+(opts.size?" rpt-ev-modal-"+opts.size:"")
card.setAttribute("role","dialog")
card.innerHTML='<div class="rpt-ev-head"><div class="rpt-ev-title"></div><button type="button" class="rpt-ev-icon-btn rpt-ev-close" title="Close"><i class="icon icon-close"></i></button></div><div class="rpt-ev-body"></div><div class="rpt-ev-foot"></div>'
card.querySelector(".rpt-ev-title").textContent=opts.title||""
wrap.appendChild(card)
const handle={el:card,body:card.querySelector(".rpt-ev-body"),foot:card.querySelector(".rpt-ev-foot"),closed:false,setTitle(t){card.querySelector(".rpt-ev-title").textContent=t},close(){
if(handle.closed)return
handle.closed=true
const at=revOverlays.indexOf(handle)
if(at>=0)revOverlays.splice(at,1)
wrap.remove()
if(!revOverlays.length){document.removeEventListener("keydown",revKeydown,true);document.body.classList.remove("rpt-ev-open")}
if(typeof opts.onClose==="function")opts.onClose()
}}
card.querySelector(".rpt-ev-close").addEventListener("click",()=>handle.close())
wrap.addEventListener("mousedown",(e)=>{if(e.target===wrap)handle.close()})
if(!revOverlays.length)document.addEventListener("keydown",revKeydown,true)
revOverlays.push(handle)
document.body.classList.add("rpt-ev-open")
document.body.appendChild(wrap)
return handle
}
function revButton(label,cls,onClick){
const b=document.createElement("button")
b.type="button"
b.className="rpt-ev-btn"+(cls?" "+cls:"")
b.textContent=label
if(onClick)b.addEventListener("click",onClick)
return b
}
function revMetaLine(ev){
const parts=[revKindLabel(ev.kind)]
if(ev.kind==="recording"&&ev.meta&&ev.meta.state==="recording")parts.push("recording now")
if(ev.target)parts.push(ev.target)
if(ev.meta&&ev.meta.session_label)parts.push(ev.meta.session_label)
parts.push(revWhen(ev.started_at||ev.created_at))
if(ev.kind!=="image"&&ev.size!==undefined)parts.push(revSize(ev.size))
return parts.filter(Boolean).join(" · ")
}
// ---- evidence browser (shared by the picker and the manager)
function revBrowser(host,opts){
opts=opts||{}
const state={all:[],query:"",kind:"",session:"",selected:{},activeId:null,cache:{},timer:null,loadSeq:0}
host.innerHTML='<div class="rpt-ev-browser"><div class="rpt-ev-side"><div class="rpt-ev-filters"><input type="text" class="rpt-ev-input rpt-ev-search" placeholder="Search title, command, output..." autocomplete="off" spellcheck="false"><div class="rpt-ev-chips"></div><select class="rpt-ev-select rpt-ev-session" data-drop-down="down"></select></div><div class="rpt-ev-list"></div></div><div class="rpt-ev-preview"></div></div>'
const listEl=host.querySelector(".rpt-ev-list"),previewEl=host.querySelector(".rpt-ev-preview"),chipsEl=host.querySelector(".rpt-ev-chips"),sessionEl=host.querySelector(".rpt-ev-session"),searchEl=host.querySelector(".rpt-ev-search")
const kinds=REV_KINDS.filter((k)=>!k.id||!opts.kinds||!opts.kinds.length||opts.kinds.indexOf(k.id)>=0)
chipsEl.innerHTML=kinds.map((k)=>'<button type="button" class="rpt-ev-chip'+(k.id===""?" active":"")+'" data-kind="'+revEsc(k.id)+'">'+revEsc(k.label)+'</button>').join("")
function visible(){return revFilter(state.all,{kind:state.kind,session:state.session})}
function selectedIds(){return Object.keys(state.selected).filter((id)=>state.selected[id]).map(Number)}
function emit(){if(typeof opts.onSelection==="function")opts.onSelection(selectedIds())}
function renderSessions(){
const sessions=revSessionsOf(state.all)
const keep=state.session
sessionEl.innerHTML='<option value="">All sessions</option>'+sessions.map((s)=>'<option value="'+revEsc(s.id)+'">'+revEsc(s.label)+'</option>').join("")
sessionEl.value=sessions.some((s)=>s.id===keep)?keep:""
state.session=sessionEl.value
sessionEl.disabled=!sessions.length
}
function renderList(){
const rows=visible()
if(!rows.length){
listEl.innerHTML='<div class="rpt-ev-empty">'+(state.all.length||state.query?"Nothing matches these filters.":"No evidence yet. Save a command from the terminal with \"Save for report\", record a session, or add text or a screenshot.")+'</div>'
return
}
listEl.innerHTML=rows.map((ev)=>{
const live=ev.kind==="recording"&&ev.meta&&ev.meta.state==="recording"
const check=opts.selectable?'<input type="checkbox" class="rpt-ev-check" data-id="'+ev.id+'"'+(state.selected[ev.id]?" checked":"")+' title="Select">':""
return '<div class="rpt-ev-row'+(ev.id===state.activeId?" active":"")+'" data-id="'+ev.id+'">'+check+'<div class="rpt-ev-row-main"><div class="rpt-ev-row-title"><span class="rpt-ev-kind rpt-ev-kind-'+revEsc(ev.kind)+'">'+revEsc(revKindLabel(ev.kind))+'</span>'+(live?'<span class="rpt-ev-rec"><span class="rpt-ev-rec-dot"></span>REC</span>':"")+'<span class="rpt-ev-row-name">'+revEsc(ev.title||ev.command||"Untitled")+'</span></div><div class="rpt-ev-row-meta">'+revEsc(revMetaLine(ev).replace(/^[^·]+· /,""))+'</div></div></div>'
}).join("")
}
function renderPreview(){
const ev=state.all.find((x)=>x.id===state.activeId)
if(!ev){previewEl.innerHTML='<div class="rpt-ev-empty">Select an item to preview it.</div>';return}
const full=state.cache[ev.id]
const exit=ev.exit_code===null||ev.exit_code===undefined?"":'<span class="rpt-ev-exit'+(ev.exit_code===0?"":" bad")+'">exit '+revEsc(ev.exit_code)+'</span>'
const redacted=ev.meta&&ev.meta.redacted?'<span class="rpt-ev-note-chip" title="Secrets were replaced with [redacted] when this was captured">'+revEsc(ev.meta.redacted)+' redacted</span>':""
let html='<div class="rpt-ev-pv-head"><div class="rpt-ev-pv-title">'+revEsc(ev.title||"Untitled")+'</div><div class="rpt-ev-pv-meta">'+revEsc(revMetaLine(ev))+exit+redacted+'</div>'+(ev.command?'<div class="rpt-ev-pv-cmd"><code>$ '+revEsc(ev.command)+'</code></div>':"")+'</div>'
if(!full)html+='<div class="rpt-ev-empty">Loading...</div>'
else if(ev.kind==="image")html+='<div class="rpt-ev-pv-image">'+(full.dataUrl?'<img alt="'+revEsc(ev.title)+'" src="'+revEsc(full.dataUrl)+'">':'<div class="rpt-ev-empty">The image is not available.</div>')+'</div>'
else html+='<pre class="rpt-ev-pv-pre">'+revEsc(full.content||"(no output)")+'</pre>'
html+='<div class="rpt-ev-pv-extra"></div>'
previewEl.innerHTML=html
if(typeof opts.renderExtra==="function")opts.renderExtra(previewEl.querySelector(".rpt-ev-pv-extra"),ev,full||null)
}
function loadFull(id){
if(state.cache[id])return Promise.resolve(state.cache[id])
return revCall("get",[id]).then((full)=>{
if(full.kind!=="image"){state.cache[id]=full;return full}
return revCall("image_data",[id]).catch(()=>"").then((dataUrl)=>{full.dataUrl=dataUrl||"";state.cache[id]=full;return full})
})
}
function activate(id){
state.activeId=id
renderList();renderPreview()
if(id===null)return
loadFull(id).then(()=>{if(state.activeId===id)renderPreview()}).catch((err)=>{if(state.activeId===id)previewEl.innerHTML='<div class="rpt-ev-empty">'+revEsc(err&&err.message?err.message:"Could not load this item.")+'</div>'})
}
function reload(keepActive){
const seq=++state.loadSeq
const filter={limit:500}
if(opts.kinds&&opts.kinds.length)filter.kinds=opts.kinds
if(state.query)filter.query=state.query
return revCall("list",[filter]).then((rows)=>{
if(seq!==state.loadSeq)return
state.all=rows||[]
const ids={}
state.all.forEach((ev)=>{ids[ev.id]=true})
Object.keys(state.selected).forEach((id)=>{if(!ids[id])delete state.selected[id]})
renderSessions()
const rowsNow=visible()
if(!keepActive||!rowsNow.some((ev)=>ev.id===state.activeId))state.activeId=rowsNow.length?rowsNow[0].id:null
activate(state.activeId)
emit()
}).catch((err)=>{listEl.innerHTML='<div class="rpt-ev-empty">'+revEsc(err&&err.message?err.message:"Could not load the evidence list.")+'</div>'})
}
searchEl.addEventListener("input",()=>{
clearTimeout(state.timer)
state.timer=setTimeout(()=>{state.query=searchEl.value.trim();reload(true)},220)
})
chipsEl.addEventListener("click",(e)=>{
const chip=e.target.closest(".rpt-ev-chip")
if(!chip)return
state.kind=chip.dataset.kind
chipsEl.querySelectorAll(".rpt-ev-chip").forEach((c)=>c.classList.toggle("active",c===chip))
const rows=visible()
if(!rows.some((ev)=>ev.id===state.activeId))state.activeId=rows.length?rows[0].id:null
activate(state.activeId)
})
sessionEl.addEventListener("change",()=>{
state.session=sessionEl.value
const rows=visible()
if(!rows.some((ev)=>ev.id===state.activeId))state.activeId=rows.length?rows[0].id:null
activate(state.activeId)
})
listEl.addEventListener("click",(e)=>{
const row=e.target.closest(".rpt-ev-row")
if(!row)return
const id=Number(row.dataset.id)
const check=e.target.closest(".rpt-ev-check")
if(check){
if(opts.multiple===false){state.selected={};if(check.checked)state.selected[id]=true}
else state.selected[id]=check.checked
if(opts.multiple===false)renderList()
emit()
return
}
activate(id)
})
listEl.addEventListener("dblclick",(e)=>{
const row=e.target.closest(".rpt-ev-row")
if(row&&typeof opts.onOpen==="function")opts.onOpen(Number(row.dataset.id))
})
return {reload,selectedIds,activeId:()=>state.activeId,active:()=>state.all.find((x)=>x.id===state.activeId)||null,all:()=>state.all,loadFull,forget(id){delete state.cache[id]},clearSelection(){state.selected={}},select(ids,on){(ids||[]).forEach((id)=>{state.selected[id]=on!==false});renderList();emit()},selectVisible(on){visible().forEach((ev)=>{state.selected[ev.id]=!!on});renderList();emit()},refreshPreview:renderPreview,focusSearch(){searchEl.focus()}}
}
// ---- picker
function revPick(opts){
opts=opts||{}
const multiple=opts.multiple!==false
return new Promise((resolve)=>{
let done=false
const ov=revOverlay({title:multiple?"Add evidence":"Choose evidence",size:"wide",onClose(){if(!done){done=true;resolve([])}}})
const count=document.createElement("span")
count.className="rpt-ev-foot-note"
const add=revButton(multiple?"Add evidence":"Use this evidence","rpt-ev-primary",finish)
add.disabled=true
const browser=revBrowser(ov.body,{selectable:true,multiple,kinds:opts.kinds,onSelection(ids){count.textContent=ids.length?ids.length+" selected":"Tick the items to add";add.disabled=!ids.length},onOpen(id){if(!multiple)browser.clearSelection();browser.select([id]);if(!multiple)finish()}})
function finish(){
const ids=browser.selectedIds()
if(!ids.length)return
add.disabled=true
Promise.all(ids.map((id)=>browser.loadFull(id))).then((items)=>{done=true;ov.close();resolve(items)}).catch((err)=>{add.disabled=false;revFail("Could not load the selected evidence.")(err)})
}
const manage=revButton("Manage evidence...","",()=>{revOpenManager({onClose:()=>browser.reload(true)})})
ov.foot.appendChild(manage)
ov.foot.appendChild(count)
ov.foot.appendChild(revButton("Cancel","",()=>ov.close()))
ov.foot.appendChild(add)
browser.reload().then(()=>browser.focusSearch())
})
}
// ---- manual evidence dialogs
function revAddText(onSaved){
const ov=revOverlay({title:"Add text evidence",size:"narrow"})
ov.body.innerHTML='<div class="rpt-ev-form"><label class="rpt-ev-label">Title<input type="text" class="rpt-ev-input" id="rptEvTextTitle" maxlength="200" placeholder="What this shows"></label><label class="rpt-ev-label">Command (optional)<input type="text" class="rpt-ev-input rpt-ev-mono" id="rptEvTextCmd" placeholder="The command that produced the output, if any" autocomplete="off" spellcheck="false"></label><label class="rpt-ev-label">Text or tool output<textarea class="rpt-ev-input rpt-ev-mono rpt-ev-textarea" id="rptEvTextBody" spellcheck="false" placeholder="Paste output here"></textarea></label><div class="rpt-ev-hint" id="rptEvTextHint"></div></div>'
revCall("redaction_enabled").then((on)=>{const hint=ov.body.querySelector("#rptEvTextHint");if(hint)hint.textContent=on?"Passwords, tokens and keys are replaced with [redacted] when the text is saved (Reporting defaults).":"Secret redaction is switched off in the Reporting defaults: the text is stored as pasted."}).catch(()=>{})
const save=revButton("Save evidence","rpt-ev-primary",()=>{
const body=ov.body.querySelector("#rptEvTextBody").value
if(!body.trim()){revToast("Paste some text first",true);return}
save.disabled=true
revCall("save_text",[{title:ov.body.querySelector("#rptEvTextTitle").value,command:ov.body.querySelector("#rptEvTextCmd").value,content:body}]).then((ev)=>{ov.close();revToast("Evidence saved");if(onSaved)onSaved(ev)}).catch((err)=>{save.disabled=false;revFail("Could not save the evidence")(err)})
})
ov.foot.appendChild(revButton("Cancel","",()=>ov.close()))
ov.foot.appendChild(save)
ov.body.querySelector("#rptEvTextTitle").focus()
}
function revReadImage(file){
return new Promise((resolve,reject)=>{
if(!file||!/^image\/(png|jpeg|gif|webp)$/.test(file.type||"")){reject(new Error("Only PNG, JPEG, GIF and WebP images can be added."));return}
if(file.size>10*1024*1024){reject(new Error("The image is larger than 10 MB."));return}
const reader=new FileReader()
reader.onload=()=>resolve(String(reader.result||""))
reader.onerror=()=>reject(new Error("The image could not be read."))
reader.readAsDataURL(file)
})
}
function revAddImage(onSaved){
const ov=revOverlay({title:"Add screenshot",size:"narrow"})
let dataUrl="",name="screenshot.png"
ov.body.innerHTML='<div class="rpt-ev-form"><label class="rpt-ev-label">Title<input type="text" class="rpt-ev-input" id="rptEvImgTitle" maxlength="200" placeholder="What the screenshot shows"></label><div class="rpt-ev-drop" id="rptEvImgDrop" tabindex="0"><div class="rpt-ev-drop-text">Paste an image (Ctrl+V), drop one here, or <button type="button" class="rpt-ev-link" id="rptEvImgBrowse">choose a file</button></div><img class="rpt-ev-drop-img hidden" id="rptEvImgPreview" alt="Preview"></div><input type="file" id="rptEvImgFile" accept="image/png,image/jpeg,image/gif,image/webp" class="rpt-ev-file"><div class="rpt-ev-hint">PNG, JPEG, GIF or WebP, up to 10 MB. The image is stored inside the encrypted database.</div></div>'
const drop=ov.body.querySelector("#rptEvImgDrop"),fileEl=ov.body.querySelector("#rptEvImgFile"),img=ov.body.querySelector("#rptEvImgPreview")
const save=revButton("Save screenshot","rpt-ev-primary",()=>{
if(!dataUrl)return
save.disabled=true
revCall("save_image",[name,dataUrl,ov.body.querySelector("#rptEvImgTitle").value]).then((ev)=>{ov.close();revToast("Screenshot saved");if(onSaved)onSaved(ev)}).catch((err)=>{save.disabled=false;revFail("Could not save the screenshot")(err)})
})
save.disabled=true
function take(file){
revReadImage(file).then((url)=>{dataUrl=url;name=file.name||"screenshot.png";img.src=url;img.classList.remove("hidden");drop.classList.add("has-image");save.disabled=false}).catch(revFail("The image could not be read."))
}
ov.body.querySelector("#rptEvImgBrowse").addEventListener("click",()=>fileEl.click())
fileEl.addEventListener("change",()=>{if(fileEl.files&&fileEl.files[0])take(fileEl.files[0])})
drop.addEventListener("dragover",(e)=>{e.preventDefault();e.dataTransfer.dropEffect="copy";drop.classList.add("over")})
drop.addEventListener("dragleave",()=>drop.classList.remove("over"))
drop.addEventListener("drop",(e)=>{e.preventDefault();drop.classList.remove("over");const f=e.dataTransfer&&e.dataTransfer.files&&e.dataTransfer.files[0];if(f)take(f)})
ov.el.addEventListener("paste",(e)=>{
const items=(e.clipboardData&&e.clipboardData.items)||[]
for(let i=0;i<items.length;i++){if(items[i].kind==="file"&&/^image\//.test(items[i].type)){e.preventDefault();take(items[i].getAsFile());return}}
})
ov.foot.appendChild(revButton("Cancel","",()=>ov.close()))
ov.foot.appendChild(save)
drop.focus()
}
// ---- manager
function revSaveToNote(ev,full){
const title=(ev.title||"Evidence")+" - "+revWhen(ev.started_at||ev.created_at)
const body="<h3>"+revEsc(ev.title||"Evidence")+"</h3>"+(ev.command?"<p><code>$ "+revEsc(ev.command)+"</code></p>":"")+"<pre>"+revEsc(full.content||"")+"</pre>"
return bridgeCall("notes.save",[null,title,"Report Evidence",body,[],"evidence"]).then(()=>revToast("Saved as the note \""+title+"\"")).catch(revFail("Could not save the note"))
}
function revOpenManager(opts){
opts=opts||{}
const ov=revOverlay({title:"Evidence",size:"wide",onClose:opts.onClose})
let browser=null
const count=document.createElement("span")
count.className="rpt-ev-foot-note"
const del=revButton("Delete selected","rpt-ev-danger",()=>{
const ids=browser.selectedIds()
if(!ids.length)return
revConfirm("Move "+ids.length+" evidence item"+(ids.length===1?"":"s")+" to the Recycle Bin?",{okLabel:"Delete",danger:true}).then((ok)=>{
if(!ok)return
revCall("delete_many",[ids]).then((n)=>{revToast(n+" item"+(n===1?"":"s")+" moved to the Recycle Bin");ids.forEach((id)=>revForgetRecording(id));browser.reload(true)}).catch(revFail("Delete failed"))
})
})
const gen=revButton("Generate report...","rpt-ev-primary",()=>{
const ids=browser.selectedIds()
revOpenAutogen({evidenceIds:ids})
})
function renderExtra(box,ev,full){
const meta=ev.meta||{}
const live=ev.kind==="recording"&&meta.state==="recording"
box.innerHTML='<div class="rpt-ev-edit"><label class="rpt-ev-label">Title<input type="text" class="rpt-ev-input" data-f="title" maxlength="300" value="'+revEsc(ev.title||"")+'"></label><label class="rpt-ev-label">Tags<input type="text" class="rpt-ev-input" data-f="tags" placeholder="comma separated" value="'+revEsc((Array.isArray(meta.tags)?meta.tags:[]).join(", "))+'"></label><label class="rpt-ev-label rpt-ev-label-wide">Notes<textarea class="rpt-ev-input rpt-ev-notes" data-f="notes" placeholder="Context for the report: what this proves, where it was run">'+revEsc(meta.notes||"")+'</textarea></label></div><div class="rpt-ev-actions"></div><div class="rpt-ev-ai hidden"></div>'
const actions=box.querySelector(".rpt-ev-actions")
actions.appendChild(revButton("Save details","rpt-ev-primary",()=>{
const patch={title:box.querySelector('[data-f="title"]').value,notes:box.querySelector('[data-f="notes"]').value,tags:box.querySelector('[data-f="tags"]').value.split(",").map((t)=>t.trim()).filter(Boolean)}
revCall("update",[ev.id,patch]).then(()=>{revToast("Evidence updated");browser.forget(ev.id);browser.reload(true)}).catch(revFail("Could not update the evidence"))
}))
if(live)actions.appendChild(revButton("Stop recording","",()=>{revStopByEvidence(ev.id).then(()=>{browser.forget(ev.id);browser.reload(true)})}))
if(full&&ev.kind!=="image"){
actions.appendChild(revButton("Copy text","",()=>{if(navigator.clipboard)navigator.clipboard.writeText(full.content||"").then(()=>revToast("Copied")).catch(()=>{})}))
actions.appendChild(revButton("Save to a note","",()=>revSaveToNote(ev,full)))
}
if(window.ReportAI&&!live&&(ev.kind==="recording"||ev.kind==="command")){
actions.appendChild(revButton("AI summary","",(e)=>{
const btn=e.currentTarget,out=box.querySelector(".rpt-ev-ai")
btn.disabled=true
Promise.resolve(window.ReportAI.run("summarise_session",{evidenceId:ev.id})).then((res)=>{
btn.disabled=false
const text=res&&(res.text||"")
if(!text)return
out.classList.remove("hidden")
out.innerHTML='<div class="rpt-ev-ai-title">AI summary</div><div class="rpt-ev-ai-text"></div>'
out.querySelector(".rpt-ev-ai-text").textContent=text
out.appendChild(revButton("Add to the notes","",()=>{const notes=box.querySelector('[data-f="notes"]');notes.value=(notes.value?notes.value+"\n\n":"")+text;revToast("Added to the notes - save details to keep it")}))
}).catch((err)=>{btn.disabled=false;if(err&&err.message)revToast(err.message,true)})
}))
}
actions.appendChild(revButton("Delete","rpt-ev-danger",()=>{
revConfirm("Move this evidence to the Recycle Bin?",{okLabel:"Delete",danger:true,bodyHtml:'<div class="rpt-ev-confirm-name">'+revEsc(ev.title||"Untitled")+'</div>'}).then((ok)=>{
if(!ok)return
revCall("delete",[ev.id]).then(()=>{revToast("Moved to the Recycle Bin");revForgetRecording(ev.id);browser.reload()}).catch(revFail("Delete failed"))
})
}))
}
browser=revBrowser(ov.body,{selectable:true,multiple:true,renderExtra,onSelection(ids){count.textContent=ids.length?ids.length+" selected":"";del.disabled=!ids.length;gen.textContent=ids.length?"Generate report from "+ids.length+"...":"Generate report..."}})
del.disabled=true
const saved=()=>browser.reload(true)
ov.foot.appendChild(revButton("Add text","",()=>revAddText(saved)))
ov.foot.appendChild(revButton("Add screenshot","",()=>revAddImage(saved)))
ov.foot.appendChild(count)
ov.foot.appendChild(del)
ov.foot.appendChild(gen)
ov.foot.appendChild(revButton("Close","",()=>ov.close()))
revFlushAll().then(()=>browser.reload()).then(()=>browser.focusSearch())
return ov
}
// ---- auto-generate wizard
function revSevSelect(key,value){
return '<select class="rpt-ev-select rpt-ev-sev rpt-ev-sev-'+revEsc(value)+'" data-key="'+revEsc(key)+'" title="Severity">'+REV_SEVERITIES.map((s)=>'<option value="'+s.id+'"'+(s.id===value?" selected":"")+'>'+revEsc(s.label)+'</option>').join("")+'</select>'
}
function revTable(headers,rows,cls){
return '<table class="rpt-ev-table'+(cls?" "+cls:"")+'"><thead><tr>'+headers.map((h)=>"<th>"+revEsc(h)+"</th>").join("")+'</tr></thead><tbody>'+rows.map((r)=>"<tr>"+r.map((c)=>"<td>"+c+"</td>").join("")+"</tr>").join("")+'</tbody></table>'
}
function revOpenAutogen(opts){
opts=opts||{}
const ov=revOverlay({title:"Generate a report from evidence",size:"wide"})
const st={step:1,evidence:[],picked:{},notes:[],notePicked:{},profiles:[],templates:[],profileId:opts.profileId||"",templateId:opts.templateId||"",title:opts.title||"",titleTouched:!!opts.title,noteQuery:"",preview:null,accepted:{},severity:{},reportsOk:true,busy:false}
const preset={}
;(opts.evidenceIds||[]).forEach((id)=>{preset[id]=true})
function profileName(){const p=st.profiles.find((x)=>x.id===st.profileId);return p?p.name:""}
function pickedIds(){return st.evidence.filter((ev)=>st.picked[ev.id]).map((ev)=>ev.id)}
function noteIds(){return st.notes.filter((n)=>st.notePicked[n.id]).map((n)=>n.id)}
function steps(){
return '<div class="rpt-ev-steps">'+["Sources","Review","Create"].map((label,i)=>'<span class="rpt-ev-step'+(st.step===i+1?" active":"")+(st.step>i+1?" done":"")+'"><span class="rpt-ev-step-n">'+(i+1)+'</span>'+label+'</span>').join("")+'</div>'
}
function loadNotes(){
return bridgeCall("reports.sources",[st.profileId||null]).then((src)=>{
st.profiles=(src&&src.profiles)||[]
if(!st.profileId){const active=st.profiles.find((p)=>p.active);st.profileId=active?active.id:(st.profiles[0]?st.profiles[0].id:"")}
st.notes=(src&&src.notes)||[]
}).catch(()=>{st.reportsOk=false;st.notes=[];st.profiles=[]})
}
function renderSources(){
ov.setTitle("Generate a report from evidence")
if(!st.titleTouched)st.title=revDefaultTitle(profileName())
const rows=st.evidence.map((ev)=>'<label class="rpt-ev-src-row"><input type="checkbox" data-ev="'+ev.id+'"'+(st.picked[ev.id]?" checked":"")+'><span class="rpt-ev-kind rpt-ev-kind-'+revEsc(ev.kind)+'">'+revEsc(revKindLabel(ev.kind))+'</span><span class="rpt-ev-src-name">'+revEsc(ev.title||ev.command||"Untitled")+'</span><span class="rpt-ev-src-meta">'+revEsc([ev.target,ev.meta&&ev.meta.session_label,revWhen(ev.started_at||ev.created_at)].filter(Boolean).join(" · "))+'</span></label>').join("")
const q=st.noteQuery.toLowerCase()
const notes=st.notes.filter((n)=>!q||String(n.name||"").toLowerCase().indexOf(q)>=0||String(n.group||"").toLowerCase().indexOf(q)>=0)
const noteRows=notes.map((n)=>'<label class="rpt-ev-src-row"><input type="checkbox" data-note="'+revEsc(n.id)+'"'+(st.notePicked[n.id]?" checked":"")+'><span class="rpt-ev-src-name">'+revEsc(n.name||"Untitled")+'</span><span class="rpt-ev-src-meta">'+revEsc([n.group,n.findings?n.findings+" finding"+(n.findings===1?"":"s"):""].filter(Boolean).join(" · "))+'</span></label>').join("")
ov.body.innerHTML=steps()+'<div class="rpt-ev-wiz"><div class="rpt-ev-wiz-main"><div class="rpt-ev-sec-head"><span>Evidence to analyse</span><span class="rpt-ev-sec-tools"><button type="button" class="rpt-ev-link" data-all="1">All</button><button type="button" class="rpt-ev-link" data-all="0">None</button></span></div><div class="rpt-ev-src-list" id="rptEvSrcList">'+(rows||'<div class="rpt-ev-empty">No command output or recordings have been saved yet. In the terminal, use "Save for report" on a command or record a session.</div>')+'</div></div><div class="rpt-ev-wiz-side"><label class="rpt-ev-label">Report title<input type="text" class="rpt-ev-input" id="rptEvGenTitle" maxlength="200" value="'+revEsc(st.title)+'"></label><label class="rpt-ev-label">Template<select class="rpt-ev-select" id="rptEvGenTemplate" data-drop-down="down">'+st.templates.map((t)=>'<option value="'+revEsc(t.id)+'"'+(t.id===st.templateId?" selected":"")+'>'+revEsc(t.name)+'</option>').join("")+'</select></label><label class="rpt-ev-label">Target profile (engagement)<select class="rpt-ev-select" id="rptEvGenProfile" data-drop-down="down">'+st.profiles.map((p)=>'<option value="'+revEsc(p.id)+'"'+(p.id===st.profileId?" selected":"")+'>'+revEsc(p.name)+'</option>').join("")+'</select></label><div class="rpt-ev-sec-head"><span>Include notes (optional)</span></div><input type="text" class="rpt-ev-input" id="rptEvGenNoteSearch" placeholder="Filter notes..." value="'+revEsc(st.noteQuery)+'" autocomplete="off"><div class="rpt-ev-src-list rpt-ev-note-list" id="rptEvNoteList">'+(noteRows||'<div class="rpt-ev-empty">'+(st.reportsOk?"No notes.":"Notes are not available.")+'</div>')+'</div></div></div>'
ov.body.querySelector("#rptEvSrcList").addEventListener("change",(e)=>{const id=e.target.dataset.ev;if(id){st.picked[id]=e.target.checked;foot()}})
ov.body.querySelectorAll("[data-all]").forEach((b)=>b.addEventListener("click",()=>{st.evidence.forEach((ev)=>{st.picked[ev.id]=b.dataset.all==="1"});renderSources();foot()}))
ov.body.querySelector("#rptEvNoteList").addEventListener("change",(e)=>{const id=e.target.dataset.note;if(id!==undefined)st.notePicked[id]=e.target.checked})
ov.body.querySelector("#rptEvGenTitle").addEventListener("input",(e)=>{st.title=e.target.value;st.titleTouched=true})
ov.body.querySelector("#rptEvGenTemplate").addEventListener("change",(e)=>{st.templateId=e.target.value})
ov.body.querySelector("#rptEvGenProfile").addEventListener("change",(e)=>{st.profileId=e.target.value;loadNotes().then(()=>{if(st.step===1)renderSources()})})
const search=ov.body.querySelector("#rptEvGenNoteSearch")
search.addEventListener("input",()=>{st.noteQuery=search.value;const at=search.selectionStart;renderSources();const again=ov.body.querySelector("#rptEvGenNoteSearch");again.focus();again.setSelectionRange(at,at)})
}
function renderReview(){
const p=st.preview,sum=revToolSummary(p)
const cands=p.candidates||[]
const candHtml=cands.map((c)=>{
const sev=st.severity[c.key]||c.severity
const affected=(c.affected||[]).map((a)=>a.value||a.name).filter(Boolean)
return '<div class="rpt-ev-cand'+(st.accepted[c.key]?"":" off")+'"><input type="checkbox" data-cand="'+revEsc(c.key)+'"'+(st.accepted[c.key]?" checked":"")+' title="Add this finding to the report"><div class="rpt-ev-cand-main"><div class="rpt-ev-cand-top">'+revSevSelect(c.key,sev)+'<span class="rpt-ev-cand-title">'+revEsc(c.title)+'</span><span class="rpt-ev-conf rpt-ev-conf-'+revEsc(c.confidence)+'" title="How strongly the captured output supports this candidate">'+revEsc(c.confidence)+' confidence</span></div><div class="rpt-ev-cand-reason">'+revEsc(c.reason)+'</div>'+(affected.length?'<div class="rpt-ev-cand-aff">Affected: '+affected.slice(0,8).map((a)=>'<code>'+revEsc(a)+'</code>').join(" ")+(affected.length>8?" +"+(affected.length-8)+" more":"")+'</div>':"")+'</div></div>'
}).join("")
const hostsHtml=(p.hosts||[]).map((h)=>'<div class="rpt-ev-host"><div class="rpt-ev-host-name">'+revEsc(h.host)+(h.hostnames&&h.hostnames.length?' <span class="rpt-ev-dim">('+revEsc(h.hostnames.join(", "))+')</span>':"")+(h.os?' <span class="rpt-ev-dim">'+revEsc(h.os)+'</span>':"")+'</div>'+revTable(["Port","State","Service","Version"],(h.ports||[]).map((port)=>[revEsc(port.port+"/"+port.proto+(port.address?" on "+port.address:"")),'<span class="rpt-ev-state rpt-ev-state-'+revEsc(String(port.state).replace(/[^a-z]/g,""))+'">'+revEsc(port.state)+'</span>',revEsc(port.service),revEsc(port.version)]))+'</div>').join("")
const timeline=revTable(["Time","Session","Command","Exit"],(p.timeline||[]).map((t)=>[revEsc(revWhen(t.ts)),revEsc(t.session_label||String(t.session_id||"").slice(0,6)),'<code>'+revEsc(t.command)+'</code>',t.exit_code===null||t.exit_code===undefined?"":'<span class="rpt-ev-exit'+(t.exit_code===0?"":" bad")+'">'+revEsc(t.exit_code)+'</span>']),"rpt-ev-timeline")
const tools=(p.tools||[]).map((t)=>'<span class="rpt-ev-tool" title="'+revEsc(t.purpose||"")+'"><code>'+revEsc(t.name)+'</code> '+revEsc(t.count)+'</span>').join("")
ov.setTitle("Review what was found")
ov.body.innerHTML=steps()+'<div class="rpt-ev-review"><div class="rpt-ev-stats"><span><b>'+sum.commands+'</b> command'+(sum.commands===1?"":"s")+'</span><span><b>'+sum.tools+'</b> tool'+(sum.tools===1?"":"s")+'</span><span><b>'+sum.hosts+'</b> host'+(sum.hosts===1?"":"s")+'</span><span><b>'+sum.ports+'</b> port'+(sum.ports===1?"":"s")+'</span><span><b>'+sum.candidates+'</b> candidate finding'+(sum.candidates===1?"":"s")+'</span>'+((p.notes||[]).length?'<span><b>'+p.notes.length+'</b> note'+(p.notes.length===1?"":"s")+'</span>':"")+'</div><div class="rpt-ev-sec-head"><span>Candidate findings</span><span class="rpt-ev-sec-tools"><button type="button" class="rpt-ev-link" data-cands="1">All</button><button type="button" class="rpt-ev-link" data-cands="0">None</button></span></div>'+(cands.length?'<div class="rpt-ev-warn">These are pattern matches over the captured output, not confirmed vulnerabilities. Tick the ones you have verified or want to investigate; each is added as a draft finding tagged "unconfirmed" that you can edit or delete.</div><div class="rpt-ev-cands" id="rptEvCands">'+candHtml+'</div>':'<div class="rpt-ev-empty">No candidate findings were recognised in the selected evidence. The report is still created with the timeline, commands and hosts.</div>')+(tools?'<div class="rpt-ev-sec-head"><span>Tools used</span></div><div class="rpt-ev-tools">'+tools+'</div>':"")+(hostsHtml?'<div class="rpt-ev-sec-head"><span>Discovered hosts and services</span></div>'+hostsHtml:"")+((p.timeline||[]).length?'<div class="rpt-ev-sec-head"><span>Timeline</span></div>'+timeline:"")+'</div>'
const box=ov.body.querySelector("#rptEvCands")
if(box)box.addEventListener("change",(e)=>{
if(e.target.dataset.cand){st.accepted[e.target.dataset.cand]=e.target.checked;e.target.closest(".rpt-ev-cand").classList.toggle("off",!e.target.checked);foot()}
else if(e.target.dataset.key){st.severity[e.target.dataset.key]=e.target.value;e.target.className="rpt-ev-select rpt-ev-sev rpt-ev-sev-"+e.target.value;const trig=e.target.nextElementSibling;if(trig&&trig.classList.contains("ui-select-trigger"))trig.className="ui-select-trigger "+e.target.className.replace("ui-select-native","").trim()}
})
ov.body.querySelectorAll("[data-cands]").forEach((b)=>b.addEventListener("click",()=>{cands.forEach((c)=>{st.accepted[c.key]=b.dataset.cands==="1"});renderReview();foot()}))
}
function acceptedKeys(){return ((st.preview&&st.preview.candidates)||[]).filter((c)=>st.accepted[c.key]).map((c)=>c.key)}
function foot(){
ov.foot.innerHTML=""
const note=document.createElement("span")
note.className="rpt-ev-foot-note"
ov.foot.appendChild(note)
if(st.step===1){
const n=pickedIds().length
note.textContent=n?n+" evidence item"+(n===1?"":"s")+" selected":"Select at least one evidence item"
ov.foot.appendChild(revButton("Cancel","",()=>ov.close()))
const next=revButton("Analyse","rpt-ev-primary",analyse)
next.disabled=!n||st.busy
ov.foot.appendChild(next)
}else{
const n=acceptedKeys().length
note.textContent=n+" finding"+(n===1?"":"s")+" will be added to \""+(st.title||"the report")+"\""
ov.foot.appendChild(revButton("Back","",()=>{st.step=1;renderSources();foot()}))
const create=revButton(st.busy?"Creating...":"Create draft report","rpt-ev-primary",createReport)
create.disabled=st.busy||!st.reportsOk
if(!st.reportsOk)create.title="The report model is not available"
ov.foot.appendChild(create)
}
}
function analyse(){
st.busy=true;foot()
revCall("autogen_preview",[{evidence_ids:pickedIds(),note_ids:noteIds(),profile_id:st.profileId}]).then((preview)=>{
st.busy=false
st.preview=preview||{}
const defaults=revDefaultAccepted(st.preview.candidates)
Object.keys(defaults).forEach((key)=>{if(st.accepted[key]===undefined)st.accepted[key]=defaults[key]})
st.step=2
renderReview();foot()
ov.body.scrollTop=0
}).catch((err)=>{st.busy=false;foot();revFail("The evidence could not be analysed")(err)})
}
function createReport(){
st.busy=true;st.step=3;foot()
const overrides={}
Object.keys(st.severity).forEach((key)=>{overrides[key]={severity:st.severity[key]}})
revCall("autogen_create",[{title:st.title.trim(),template_id:st.templateId,profile_id:st.profileId,evidence_ids:pickedIds(),note_ids:noteIds(),accepted:acceptedKeys(),overrides}]).then((res)=>{
st.busy=false
ov.close()
// The evidence manager the wizard was opened from would cover the report that is about to open.
revOverlays.slice().forEach((o)=>o.close())
revToast("Draft report created with "+res.findings+" finding"+(res.findings===1?"":"s"))
if(typeof opts.onCreated==="function")opts.onCreated(res)
const open=()=>{if(window.Reporting&&typeof window.Reporting.open==="function")return window.Reporting.open(res.report_id)}
if(typeof goToPage==="function")Promise.resolve(goToPage("reporting")).then(open).catch(()=>{})
else open()
}).catch((err)=>{st.busy=false;st.step=2;foot();revFail("The report could not be created")(err)})
}
ov.body.innerHTML='<div class="rpt-ev-empty">Loading...</div>'
const loads=[
revFlushAll().then(()=>revCall("list",[{kinds:["command","recording","text"],limit:500}])).then((rows)=>{
st.evidence=rows||[]
const any=Object.keys(preset).length>0
st.evidence.forEach((ev)=>{st.picked[ev.id]=any?!!preset[ev.id]:true})
}),
bridgeCall("reports.templates").then((list)=>{
st.templates=list||[]
if(!st.templates.some((t)=>t.id===st.templateId))st.templateId=(st.templates.find((t)=>t.id==="internal_network")||st.templates[0]||{id:""}).id
}).catch(()=>{st.reportsOk=false;st.templates=[]}),
loadNotes()
]
Promise.all(loads).then(()=>{if(ov.closed)return;renderSources();foot()}).catch((err)=>{ov.body.innerHTML='<div class="rpt-ev-empty">'+revEsc(err&&err.message?err.message:"Could not load the evidence.")+'</div>'})
return ov
}
// ---- terminal integration: save a job, record sessions
const revSavedJobs={}
const revRecs={}
let revFlushTimer=null,revClockTimer=null
function revTabsChanged(){
if(typeof termRenderTabs==="function"){try{termRenderTabs()}catch(e){}}
revSyncHeadButton()
}
// Optional panel-header toggle: when main.html carries a #terminalRecordBtn it follows the active session's state.
function revSyncHeadButton(){
const btn=document.getElementById("terminalRecordBtn")
if(!btn)return
const on=typeof termState!=="undefined"&&revIsRecording(termState.activeId)
btn.classList.toggle("active",on)
btn.classList.toggle("rpt-ev-rec-on",on)
btn.title=on?"Stop recording this session":"Record this session for the report"
}
document.addEventListener("click",(e)=>{
const btn=e.target.closest&&e.target.closest("#terminalRecordBtn")
if(btn){
const tab=revTerminalTabs().find((t)=>t.sessionId===termState.activeId)
if(!tab){revToast("Open a terminal session first",true);return}
revToggleRecording(tab.sessionId,revTabInfo(tab))
return
}
if(e.target.closest&&e.target.closest(".terminal-tab"))setTimeout(revSyncHeadButton,0)
})
function revJobButtonHtml(jobId){
const saved=!!revSavedJobs[jobId]
return '<span class="rpt-ev-jobbtn'+(saved?" saved":"")+'" data-rpt-job="'+revEsc(jobId)+'" title="'+(saved?"Saved as report evidence - click to save the latest output again":"Save this command and its output as report evidence")+'"><i class="icon icon-report"></i>'+(saved?"Saved":"Save for report")+'</span>'
}
function revSaveJob(info){
if(!info)return Promise.resolve(null)
return revCall("save_job",[info]).then((ev)=>{
if(info.job_key)revSavedJobs[info.job_key]=ev.id
const n=ev.meta&&ev.meta.redacted
revToast("Saved for the report"+(n?" ("+n+" secret"+(n===1?"":"s")+" redacted)":""))
document.querySelectorAll(".rpt-ev-jobbtn").forEach((el)=>{if(el.dataset.rptJob===info.job_key){el.classList.add("saved");el.lastChild.textContent="Saved"}})
return ev
}).catch((err)=>{revFail("Could not save the evidence")(err);return null})
}
function revSaveJobRecord(tab,record){
return revSaveJob(revJobInfo(tab,record))
}
// A row of the terminal's Jobs drawer: its output is in the tab buffer, or (batch and playbook jobs) held by the backend.
function revSaveJobFromList(job,output){
if(!job)return Promise.resolve(null)
const tab=revTerminalTabs().find((t)=>t.sessionId===job.session_id)
const info=(text)=>({session_id:job.session_id||"",job_key:job.job_key||"",command:job.command||"",output:text||"",exit_code:job.exit_code===undefined?null:job.exit_code,cwd:job.cwd||"",started_at:job.started_at||null,ended_at:job.ended_at||null,shell:tab?tab.shellId:"",session_label:tab?tab.label:(job.source==="batch"?"Batch":"")})
if(output)return revSaveJob(info(output))
return bridgeCall("terminal.batch_output",[job.job_key,true]).catch(()=>"").then((text)=>revSaveJob(info(text)))
}
function revIsRecording(sessionId){return !!revRecs[sessionId]}
function revRecordingBadgeHtml(sessionId){
const rec=revRecs[sessionId]
if(!rec)return ""
return '<span class="rpt-ev-rec" data-rpt-rec="'+revEsc(sessionId)+'" title="Recording this session for the report"><span class="rpt-ev-rec-dot"></span><span class="rpt-ev-rec-time">'+revElapsed(Date.now()-rec.startedAt)+'</span></span>'
}
function revTick(){
document.querySelectorAll(".rpt-ev-rec[data-rpt-rec]").forEach((el)=>{
const rec=revRecs[el.dataset.rptRec]
const time=el.querySelector(".rpt-ev-rec-time")
if(rec&&time)time.textContent=revElapsed(Date.now()-rec.startedAt)
})
}
function revTimers(){
const any=Object.keys(revRecs).length>0
if(any&&!revFlushTimer){revFlushTimer=setInterval(()=>{revFlushAll()},REV_FLUSH_MS);revClockTimer=setInterval(revTick,1000)}
if(!any&&revFlushTimer){clearInterval(revFlushTimer);clearInterval(revClockTimer);revFlushTimer=null;revClockTimer=null}
}
function revFlush(sessionId){
const rec=revRecs[sessionId]
if(!rec)return Promise.resolve()
rec.chain=rec.chain.then(()=>{
if(!rec.queue.events.length)return
const events=rec.queue.take()
return revCall("recording_append",[rec.evidenceId,events]).then((res)=>{
if(res&&res.capped&&!rec.capped){rec.capped=true;revToast("The recording reached its size limit; further output is not stored.",true)}
}).catch((err)=>{
// A recording that no longer exists or was stopped elsewhere cannot take more events; anything else is retried on the next flush.
if(err&&/not active|not found/i.test(err.message||"")){delete revRecs[sessionId];revTimers();revTabsChanged();return}
rec.queue.putBack(events)
})
})
return rec.chain
}
function revFlushAll(){
return Promise.all(Object.keys(revRecs).map(revFlush)).catch(()=>{})
}
function revPush(sessionId,kind,data){
const rec=revRecs[sessionId]
if(!rec||rec.stopping)return
rec.queue.push(kind,data)
rec.used=true
if(rec.queue.chars>REV_FLUSH_CHARS)revFlush(sessionId)
}
function revStart(sessionId,info){
info=info||{}
if(revRecs[sessionId])return Promise.resolve(true)
return revCall("recording_start",[{session_id:sessionId,label:info.label||"",shell:info.shell||"",cwd:info.cwd||"",title:info.title||""}]).then((ev)=>{
const started=new Date(ev.started_at).getTime()
revRecs[sessionId]={evidenceId:ev.id,startedAt:isNaN(started)?Date.now():started,queue:new RevQueue(),chain:Promise.resolve(),jobs:{},stopping:false,capped:false}
revTimers();revTabsChanged()
return true
})
}
function revStop(sessionId,note){
const rec=revRecs[sessionId]
if(!rec)return Promise.resolve(null)
if(note)rec.queue.push("mark",note)
rec.stopping=true
return revFlush(sessionId).then(()=>revCall("recording_stop",[rec.evidenceId])).catch(()=>null).then((ev)=>{
if(revRecs[sessionId]===rec)delete revRecs[sessionId]
revTimers();revTabsChanged()
return ev
})
}
function revStopByEvidence(evidenceId){
const sid=Object.keys(revRecs).find((id)=>revRecs[id].evidenceId===evidenceId)
if(sid)return revStop(sid)
return revCall("recording_stop",[evidenceId]).catch(revFail("Could not stop the recording"))
}
function revForgetRecording(evidenceId){
const sid=Object.keys(revRecs).find((id)=>revRecs[id].evidenceId===evidenceId)
if(!sid)return
delete revRecs[sid]
revTimers();revTabsChanged()
}
function revToggleRecording(sessionId,info){
if(!sessionId)return Promise.resolve(false)
if(revRecs[sessionId]){
return revStop(sessionId).then((ev)=>{
const n=ev&&ev.meta?ev.meta.commands||0:0
revToast(!ev?"Recording stopped":ev.meta&&ev.meta.discarded?"Recording discarded - nothing was captured":"Recording saved as evidence ("+n+" command"+(n===1?"":"s")+")")
return false
})
}
return revStart(sessionId,info).then(()=>{revToast("Recording "+((info&&info.label)||"this session")+" for the report");return true}).catch((err)=>{revFail("Could not start the recording")(err);return false})
}
function revTerminalTabs(){
return typeof termState!=="undefined"&&termState&&Array.isArray(termState.tabs)?termState.tabs.filter((t)=>!t.dead):[]
}
function revTabInfo(tab){return {label:tab.label||"",shell:tab.shellId||"",cwd:tab.cwd||""}}
function revRecordAll(tabs){
const list=(tabs||revTerminalTabs()).filter((t)=>!revRecs[t.sessionId])
if(!list.length){revToast("Every open session is already being recorded");return Promise.resolve(0)}
return Promise.all(list.map((t)=>revStart(t.sessionId,revTabInfo(t)).then(()=>1).catch(()=>0))).then((res)=>{
const n=res.reduce((a,b)=>a+b,0)
revToast(n?"Recording "+n+" session"+(n===1?"":"s")+" for the report":"Could not start recording",!n)
return n
})
}
function revStopAll(){
const ids=Object.keys(revRecs)
return Promise.all(ids.map((id)=>revStop(id))).then((res)=>{
const kept=res.filter((ev)=>ev&&!(ev.meta&&ev.meta.discarded)).length
if(ids.length)revToast(kept?kept+" recording"+(kept===1?"":"s")+" saved as evidence":"Recordings discarded - nothing was captured")
return res.length
})
}
// Context-menu entries for a terminal tab, so the terminal's hook is a single spread.
function revTabMenuItems(tab){
if(!tab)return []
const on=revIsRecording(tab.sessionId)
const active=Object.keys(revRecs).length
const open=revTerminalTabs()
return [{sep:true},
{label:on?"Stop recording":"Record session for report",icon:on?"stop":"report",disabled:!on&&!!tab.dead,fn:()=>revToggleRecording(tab.sessionId,revTabInfo(tab))},
{label:active>1||(active===1&&!on)?"Stop all recordings":"Record all open sessions",icon:active>1||(active===1&&!on)?"stop":"report",disabled:!(active>1||(active===1&&!on))&&open.filter((t)=>!revRecs[t.sessionId]).length<2,fn:()=>active>1||(active===1&&!on)?revStopAll():revRecordAll()},
{label:"Report evidence...",icon:"list",fn:()=>revOpenManager()}]
}
function revOnSessionOutput(sessionId,text){revPush(sessionId,"out",text)}
function revOnJobStart(sessionId,job){
const rec=revRecs[sessionId]
if(!rec||!job)return
rec.jobs[job.jobId]=job.startedAt||Date.now()
revPush(sessionId,"cmd",job.command||"")
}
function revOnJobFinish(sessionId,job){
const rec=revRecs[sessionId]
if(!rec||!job)return
const started=rec.jobs[job.jobId]
if(started===undefined)return
delete rec.jobs[job.jobId]
const ended=job.endedAt||Date.now()
revPush(sessionId,"exit",{code:job.exitCode===undefined?null:job.exitCode,duration:Math.max(0,(ended-started)/1000)})
}
function revOnSessionClosed(sessionId){
if(revRecs[sessionId])revStop(sessionId,revRecs[sessionId].used?"Session closed":"").then((ev)=>{if(ev&&!(ev.meta&&ev.meta.discarded))revToast("Recording saved as evidence")})
}
// The buffers live in this page: after a reload nothing can continue an earlier recording, so close whatever the backend still has open.
function revAdoptOrphans(){
revCall("recordings_active").then((rows)=>{
;(rows||[]).forEach((ev)=>{if(!Object.keys(revRecs).some((id)=>revRecs[id].evidenceId===ev.id))revCall("recording_stop",[ev.id]).catch(()=>{})})
}).catch(()=>{})
}
window.addEventListener("pagehide",()=>{revFlushAll()})
window.addEventListener("beforeunload",()=>{revFlushAll()})
if(window.pywebview&&window.pywebview.api)revAdoptOrphans()
else window.addEventListener("pywebviewready",revAdoptOrphans,{once:true})
root.ReportEvidence={pick:revPick,openManager:revOpenManager,openAutogen:revOpenAutogen,addText:revAddText,addScreenshot:revAddImage,saveJob:revSaveJob,saveJobRecord:revSaveJobRecord,saveJobFromList:revSaveJobFromList,jobButtonHtml:revJobButtonHtml,toggleRecording:revToggleRecording,isRecording:revIsRecording,recordAll:revRecordAll,stopAll:revStopAll,recordingBadgeHtml:revRecordingBadgeHtml,tabMenuItems:revTabMenuItems,onSessionOutput:revOnSessionOutput,onJobStart:revOnJobStart,onJobFinish:revOnJobFinish,onSessionClosed:revOnSessionClosed,flush:revFlushAll,activeRecordings:()=>Object.keys(revRecs),_pure:pure}
})(typeof window!=="undefined"?window:globalThis)
