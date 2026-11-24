// Reporting: export and import dialogs, plus the report defaults form shown in Settings (window.ReportExport).
var ReportExport=(function(){
const FORMATS=[
{id:"pdf",label:"PDF",ext:"pdf",description:"The report design printed to PDF: cover, contents with page numbers, running headers, bookmarks."},
{id:"docx",label:"Word",ext:"docx",description:"Editable Word document in the report's theme: heading styles, a real table of contents, headers and footers."},
{id:"html",label:"HTML",ext:"html",description:"One self-contained web page (no scripts) with the same design as the PDF."},
{id:"markdown",label:"Markdown",ext:"zip",description:"ZIP with report.md and an assets folder - for wikis, Git and ticket systems."},
{id:"json",label:"JSON",ext:"json",description:"Full-fidelity backup with images and evidence. Can be imported again."},
{id:"csv",label:"CSV",ext:"csv",description:"Findings table for spreadsheets and ticket imports."},
{id:"xlsx",label:"Excel",ext:"xlsx",description:"Findings workbook with severity colours, filters and a summary sheet."},
{id:"sarif",label:"SARIF",ext:"sarif",description:"SARIF 2.1.0 findings for code-scanning dashboards and CI pipelines."},
]
const STATUSES=[["open","Open"],["retest","Retest"],["fixed","Fixed"],["accepted","Risk accepted"]]
const SEVERITIES=[["critical","Critical"],["high","High"],["medium","Medium"],["low","Low"],["info","Info"]]
const KINDS=[["auto","Detect automatically"],["report_json","Report (JSON, single or bundle)"],["findings_csv","Findings (CSV, incl. Nessus-style scanner exports)"],["templates","Report templates (JSON)"],["library","Findings library (JSON)"]]
const DOC_FORMATS=["pdf","docx","html","markdown"]
const UPLOAD_MAX=100*1024*1024
let session=null
// ---- pure helpers (also exercised by tests/js/reporting_export.js) ----
function esc(s){return String(s===undefined||s===null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")}
function applicable(fmt){
const doc=DOC_FORMATS.indexOf(fmt)>=0
const paged=fmt==="pdf"||fmt==="docx"||fmt==="html"
return {page_size:paged,theme:paged,embed_fonts:fmt==="html",include_cover:doc,include_toc:doc,include_appendices:doc,redact:fmt!=="json",findings_status:fmt!=="json"}
}
function cleanStatuses(list){
const ok=STATUSES.map((s)=>s[0])
const out=(Array.isArray(list)?list:[]).filter((s,i,a)=>ok.indexOf(s)>=0&&a.indexOf(s)===i)
return out.length?out:ok.slice()
}
// Initial dialog state: the report's own layout options, then what the user chose last time for everything the report does not store.
function initialState(report,defaults,prefs){
report=report||{};defaults=defaults||{};prefs=prefs||{}
const ro=report.options||{},br=report.branding||{}
const fmt=FORMATS.some((f)=>f.id===prefs.format)?prefs.format:(FORMATS.some((f)=>f.id===defaults.default_format)?defaults.default_format:"pdf")
const pick=(a,b,c)=>typeof a==="boolean"?a:(typeof b==="boolean"?b:c)
const size=(v)=>v==="Letter"||v==="A4"?v:""
return {
format:fmt,
page_size:size(ro.page_size)||size(defaults.page_size)||"A4",
include_toc:pick(ro.include_toc,defaults.include_toc,true),
include_appendices:pick(ro.include_appendices,defaults.include_appendices,true),
include_cover:pick(prefs.include_cover,br.show_cover,true),
redact:prefs.redact!==false,
embed_fonts:prefs.embed_fonts!==false,
theme:"",
findings_status:cleanStatuses(prefs.findings_status),
}
}
// What to tell the user after an export: the path, and for PDF which engine produced the file.
function exportMessage(info){
if(!info||!info.path)return ""
if(info.format==="pdf"&&info.message)return info.message+" Saved to "+info.path
return "Report exported to "+info.path
}
// Only the options that mean something for the chosen format cross the bridge.
function exportOptions(state){
const a=applicable(state.format),o={}
if(a.page_size)o.page_size=state.page_size
if(a.include_cover)o.include_cover=!!state.include_cover
if(a.include_toc)o.include_toc=!!state.include_toc
if(a.include_appendices)o.include_appendices=!!state.include_appendices
if(a.redact)o.redact=!!state.redact
// "" keeps the design saved with the report; a theme id is a one-off override for this export.
if(a.theme&&state.theme)o.theme=state.theme
if(a.embed_fonts)o.embed_fonts=state.embed_fonts!==false
if(a.findings_status&&state.findings_status.length<STATUSES.length)o.findings_status=state.findings_status.slice()
return o
}
function fileExt(name){const m=/\.([a-z0-9]+)$/i.exec(String(name||""));return m?m[1].toLowerCase():""}
function importable(name){return ["json","csv","tsv"].indexOf(fileExt(name))>=0}
function plural(n,one,many){return n+" "+(n===1?one:(many||one+"s"))}
function summaryChips(s){
s=s||{}
const out=[]
if(s.reports)out.push(plural(s.reports,"report"))
if(s.templates)out.push(plural(s.templates,"template"))
if(s.library)out.push(plural(s.library,"library entry","library entries"))
if(s.findings)out.push(plural(s.findings,"finding"))
if(s.sections)out.push(plural(s.sections,"section"))
if(s.assets)out.push(plural(s.assets,"image"))
if(s.evidence)out.push(plural(s.evidence,"evidence item"))
return out
}
// "Name, Role, Email" per line <-> [{name,role,email}]
function parseTesters(text){
return String(text||"").split(/\r?\n/).map((line)=>{
const p=line.split(",").map((x)=>x.trim())
return {name:p[0]||"",role:p[1]||"",email:p.slice(2).join(", ")}
}).filter((t)=>t.name||t.role||t.email)
}
function formatTesters(list){
return (Array.isArray(list)?list:[]).map((t)=>[t.name||"",t.role||"",t.email||""].join(", ").replace(/(, )+$/,"")).join("\n")
}
function validHex(v){return /^#[0-9a-fA-F]{6}$/.test(String(v||"").trim())}
// ---- small UI helpers ----
function el(tag,cls,text){
const e=document.createElement(tag)
if(cls)e.className=cls
if(text!==undefined&&text!==null)e.textContent=text
return e
}
function toast(msg,isError){if(typeof showToast==="function")showToast(String(msg||""),isError?"error":undefined)}
function errText(err,fallback){return err&&err.message?String(err.message):(typeof err==="string"&&err?err:fallback)}
function has(path){
if(typeof bridgeResolve!=="function")return true
const t=bridgeResolve(path)
return !!(t&&typeof t.fn==="function")
}
function call(path,args,fallback){
if(!has(path))return fallback===undefined?Promise.reject(new Error("This feature is not available in this build.")):Promise.resolve(fallback)
return bridgeCall(path,args||[])
}
// The reporting widgets' modal stacks on top of an open dialog; without it (stub build) the app's single modal is used.
function modal(opts){
if(window.ReportWidgets&&typeof ReportWidgets.modal==="function")return ReportWidgets.modal(opts)
const card=el("div","rpt-modal glass-panel"+(opts.wide?" rpt-modal-wide":"")+(opts.className?" "+opts.className:""))
const head=el("div","rpt-modal-head")
head.appendChild(el("div","rpt-modal-title",opts.title||""))
const body=el("div","rpt-modal-body"),foot=el("div","rpt-modal-foot")
if(opts.bodyEl)body.appendChild(opts.bodyEl)
card.appendChild(head);card.appendChild(body);card.appendChild(foot)
const ctl={el:card,body:body,foot:foot,close:()=>{if(typeof closeModal==="function")closeModal(true)},setButtons:setButtons}
function setButtons(buttons){
foot.innerHTML=""
;(buttons||[]).forEach((b)=>{
const btn=el("button","rpt-btn"+(b.primary?" rpt-btn-primary":""),b.label)
btn.type="button"
if(b.left)btn.classList.add("rpt-btn-left")
btn.addEventListener("click",()=>{const r=typeof b.onClick==="function"?b.onClick(ctl,btn):undefined;if(r!==false&&!b.keepOpen)ctl.close()})
foot.appendChild(btn)
b.el=btn
})
}
setButtons(opts.buttons)
if(typeof openModal==="function")openModal(card,{})
return ctl
}
function check(label,checked,hint){
const wrap=el("label","rpt-x-check")
const input=el("input")
input.type="checkbox"
input.checked=!!checked
wrap.appendChild(input)
const text=el("span","rpt-x-check-text")
text.appendChild(el("span","rpt-x-check-label",label))
if(hint)text.appendChild(el("span","rpt-x-check-hint",hint))
wrap.appendChild(text)
return {wrap:wrap,input:input}
}
function status(host,text,kind){
host.textContent=text||""
host.className="rpt-x-status"+(kind?" "+kind:"")
}
function copyPath(path){
if(window.ReportWidgets&&typeof ReportWidgets.copyText==="function")return ReportWidgets.copyText(path)
if(navigator.clipboard&&navigator.clipboard.writeText)navigator.clipboard.writeText(path).then(()=>toast("Copied")).catch(()=>toast("Copy failed",true))
}
function savedLine(host,path,what){
host.textContent=""
host.className="rpt-x-status ok"
host.appendChild(el("span","rpt-x-saved-label",(what||"Saved to")+" "))
host.appendChild(el("span","rpt-x-saved-path",path))
const btn=el("button","rpt-x-link","Copy path")
btn.type="button"
btn.addEventListener("click",()=>copyPath(path))
host.appendChild(btn)
}
// ---- export dialog ----
function open(reportId){
if(reportId===undefined||reportId===null||reportId===""){toast("Open a report first.",true);return Promise.resolve(null)}
return Promise.all([
call("reports.get",[reportId]),
call("reports.defaults_get",[],{}).catch(()=>({})),
call("reportsIO.export_prefs_get",[],{}).catch(()=>({})),
call("reportsIO.formats",[],FORMATS).catch(()=>FORMATS),
call("reportsIO.themes",[],[]).catch(()=>[]),
]).then((r)=>openExport(r[0],r[1]||{},Object.assign({},r[2]||{},session||{}),Array.isArray(r[3])&&r[3].length?r[3]:FORMATS,Array.isArray(r[4])?r[4]:[])).catch((err)=>{toast(errText(err,"Could not open the export dialog."),true);return null})
}
function openExport(report,defaults,prefs,formats,themes){
themes=themes||[]
const state=initialState(report,defaults,prefs)
const body=el("div","rpt-x")
const total=(report.findings||[]).length
const sub=el("div","rpt-x-sub")
sub.appendChild(el("span","rpt-x-sub-title",report.title||"Untitled report"))
sub.appendChild(el("span","rpt-x-sub-meta",[report.meta&&report.meta.client,plural(total,"finding")].filter(Boolean).join(" - ")))
body.appendChild(sub)
body.appendChild(el("div","rpt-x-label","Format"))
const grid=el("div","rpt-x-formats")
grid.setAttribute("role","radiogroup")
const cards={}
formats.forEach((f)=>{
const card=el("button","rpt-x-format")
card.type="button"
card.setAttribute("role","radio")
card.dataset.format=f.id
const top=el("span","rpt-x-format-top")
top.appendChild(el("span","rpt-x-format-name",f.label))
top.appendChild(el("span","rpt-x-format-ext","."+f.ext))
card.appendChild(top)
card.appendChild(el("span","rpt-x-format-desc",f.description))
card.addEventListener("click",()=>{state.format=f.id;sync()})
card.addEventListener("dblclick",()=>{state.format=f.id;sync();run()})
grid.appendChild(card)
cards[f.id]=card
})
body.appendChild(grid)
body.appendChild(el("div","rpt-x-label","Options"))
const opts=el("div","rpt-x-options")
const sizeField=el("label","rpt-x-field")
sizeField.appendChild(el("span","rpt-x-field-label","Page size"))
const size=el("select","rpt-input rpt-select rpt-x-select")
;[["A4","A4 (210 x 297 mm)"],["Letter","US Letter (8.5 x 11 in)"]].forEach((o)=>{const op=el("option",null,o[1]);op.value=o[0];size.appendChild(op)})
size.value=state.page_size
size.addEventListener("change",()=>{state.page_size=size.value})
sizeField.appendChild(size)
const fields=el("div","rpt-x-fields")
fields.appendChild(sizeField)
opts.appendChild(fields)
const themeField=el("label","rpt-x-field")
themeField.appendChild(el("span","rpt-x-field-label","Design"))
const theme=el("select","rpt-input rpt-select rpt-x-select")
const own=themes.filter((t)=>t.id===((report.branding||{}).theme||"corporate"))[0]
;[["","Report design"+(own?" ("+own.name+")":"")]].concat(themes.map((t)=>[t.id,t.name+" theme"])).forEach((o)=>{const op=el("option",null,o[1]);op.value=o[0];theme.appendChild(op)})
theme.value=state.theme
theme.addEventListener("change",()=>{state.theme=theme.value})
themeField.appendChild(theme)
if(themes.length)fields.appendChild(themeField)
const toggles=el("div","rpt-x-toggles")
const cover=check("Cover page",state.include_cover)
const toc=check("Table of contents",state.include_toc)
const app=check("Appendices",state.include_appendices,"Tools, commands, evidence and timeline")
const red=check("Mask credentials and secrets",state.redact,"Passwords, tokens and keys in evidence and code blocks are masked")
const fonts=check("Embed fonts",state.embed_fonts,"Same typography on every computer; the file is about 300 KB larger")
;[[cover,"include_cover"],[toc,"include_toc"],[app,"include_appendices"],[red,"redact"],[fonts,"embed_fonts"]].forEach((p)=>{
p[0].input.addEventListener("change",()=>{state[p[1]]=p[0].input.checked})
toggles.appendChild(p[0].wrap)
})
opts.appendChild(toggles)
body.appendChild(opts)
const stLabel=el("div","rpt-x-label","Findings to include")
body.appendChild(stLabel)
const stRow=el("div","rpt-x-statuses")
const counts={}
;(report.findings||[]).forEach((f)=>{counts[f.status]=(counts[f.status]||0)+1})
const stInputs=STATUSES.map((s)=>{
const c=check(s[1]+" ("+(counts[s[0]]||0)+")",state.findings_status.indexOf(s[0])>=0)
c.wrap.classList.add("rpt-x-chip")
c.input.addEventListener("change",()=>{
state.findings_status=STATUSES.map((x,i)=>stInputs[i].input.checked?x[0]:null).filter(Boolean)
sync()
})
stRow.appendChild(c.wrap)
return c
})
body.appendChild(stRow)
const note=el("div","rpt-x-note")
body.appendChild(note)
const st=el("div","rpt-x-status")
body.appendChild(st)
let busy=false
const m=modal({title:"Export Report",bodyEl:body,wide:true,className:"rpt-x-modal",buttons:[
{label:"Close"},
{label:"Export...",primary:true,keepOpen:true,onClick:()=>{run();return false}},
]})
const exportBtn=m.foot.querySelector(".rpt-btn-primary")
function sync(){
const a=applicable(state.format)
Object.keys(cards).forEach((k)=>{cards[k].classList.toggle("active",k===state.format);cards[k].setAttribute("aria-checked",k===state.format?"true":"false")})
size.disabled=!a.page_size
sizeField.classList.toggle("off",!a.page_size)
theme.disabled=!a.theme
themeField.classList.toggle("off",!a.theme)
fonts.wrap.hidden=!a.embed_fonts
;[[cover,a.include_cover],[toc,a.include_toc],[app,a.include_appendices],[red,a.redact],[fonts,a.embed_fonts]].forEach((p)=>{p[0].input.disabled=!p[1];p[0].wrap.classList.toggle("off",!p[1])})
stInputs.forEach((c)=>{c.input.disabled=!a.findings_status;c.wrap.classList.toggle("off",!a.findings_status)})
stLabel.classList.toggle("off",!a.findings_status)
const none=a.findings_status&&!state.findings_status.length
note.classList.toggle("warn",state.format==="json")
note.textContent=state.format==="json"?"JSON is a full backup: it contains unmasked evidence, including any credentials. Store and share it accordingly."
:(state.format==="csv"||state.format==="xlsx"||state.format==="sarif")?"This format contains the findings table only."
:none?"Select at least one finding status.":""
if(exportBtn)exportBtn.disabled=busy||none
}
function run(){
if(busy||(applicable(state.format).findings_status&&!state.findings_status.length))return
busy=true
sync()
status(st,"Choose where to save the file...")
session={format:state.format,include_cover:state.include_cover,redact:state.redact,embed_fonts:state.embed_fonts,findings_status:state.findings_status.slice()}
if(state.format==="pdf")status(st,"Choose where to save the file. Printing the report can take a few seconds...")
call("reports.defaults_set",[{default_format:state.format}],null).catch(()=>{})
call("reportsIO.export_prefs_set",[session],null).catch(()=>{})
const ex=has("reportsIO.export_ex")
call(ex?"reportsIO.export_ex":"reportsIO.export",[report.id,state.format,exportOptions(state)]).then((res)=>{
busy=false
sync()
const info=res&&typeof res==="object"?res:(res?{path:res,format:state.format,message:""}:null)
if(!info||!info.path){status(st,"Export cancelled.");return}
savedLine(st,info.path,info.format==="pdf"&&info.message?(info.native?"PDF created with the built-in print engine":"PDF created with the basic PDF writer"):undefined)
toast(exportMessage(info))
}).catch((err)=>{
busy=false
sync()
status(st,errText(err,"Export failed."),"error")
})
}
sync()
return m
}
function simpleExport(method,args,done){
return call(method,args).then((path)=>{if(path)toast((done||"Exported to")+" "+path);return path||null}).catch((err)=>{toast(errText(err,"Export failed."),true);return null})
}
function exportAll(fmt){return simpleExport("reportsIO.export_many",[[],fmt||"json"],"Reports exported to")}
function exportTemplates(ids){return simpleExport("reportsIO.export_templates",[ids||[]],"Templates exported to")}
function exportLibrary(){return simpleExport("reportsIO.export_library",[],"Findings library exported to")}
// ---- import dialog ----
function readB64(file){
return new Promise((res,rej)=>{
const r=new FileReader()
r.onload=()=>{const s=String(r.result||"");res(s.slice(s.indexOf(",")+1))}
r.onerror=()=>rej(new Error("Could not read the file."))
r.readAsDataURL(file)
})
}
function openImport(opts){
opts=opts||{}
const body=el("div","rpt-x rpt-x-import")
const m=modal({title:"Import into Reporting",bodyEl:body,wide:true,className:"rpt-x-modal",buttons:[]})
let kind=KINDS.some((k)=>k[0]===opts.kind)?opts.kind:"auto"
function stepPick(message,isError){
body.textContent=""
const field=el("label","rpt-x-field")
field.appendChild(el("span","rpt-x-field-label","What to import"))
const sel=el("select","rpt-input rpt-select rpt-x-select")
KINDS.forEach((k)=>{const o=el("option",null,k[1]);o.value=k[0];sel.appendChild(o)})
sel.value=kind
sel.addEventListener("change",()=>{kind=sel.value})
field.appendChild(sel)
body.appendChild(field)
const zone=el("div","rpt-x-drop")
zone.tabIndex=0
zone.setAttribute("role","button")
zone.setAttribute("aria-label","Import a file: drop it here or press Enter to browse")
zone.innerHTML='<i class="icon icon-add rpt-x-drop-icon"></i><div class="rpt-x-drop-text"><strong>Drop a file here to import</strong><span>or click to browse - report JSON, findings CSV, templates or library JSON</span></div>'
const input=el("input","hidden")
input.type="file"
input.accept=".json,.csv,.tsv"
body.appendChild(zone)
body.appendChild(input)
const st=el("div","rpt-x-status"+(isError?" error":""),message||"")
body.appendChild(st)
const hint=el("div","rpt-x-note","Report JSON files recreate the whole report with its images and evidence. A findings CSV can be added to an existing report or start a new one; scanner exports are grouped by finding with every affected host collected.")
body.appendChild(hint)
const take=(file)=>{
if(!file)return
if(!importable(file.name)){status(st,"\""+file.name+"\" is not an importable file. Use JSON or CSV.","error");return}
if(file.size>UPLOAD_MAX){status(st,"That file is larger than 100 MB.","error");return}
status(st,"Reading "+file.name+"...")
readB64(file).then((b64)=>call("importExport.stage_upload",[file.name,b64])).then((up)=>pick(up.path,st)).catch((err)=>status(st,errText(err,"Import failed."),"error"))
}
const browse=()=>{input.value="";input.click()}
zone.addEventListener("click",browse)
zone.addEventListener("keydown",(e)=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();browse()}})
input.addEventListener("change",()=>{if(input.files&&input.files[0])take(input.files[0])})
let depth=0
zone.addEventListener("dragenter",(e)=>{e.preventDefault();depth++;zone.classList.add("drag-over")})
zone.addEventListener("dragover",(e)=>{e.preventDefault();if(e.dataTransfer)e.dataTransfer.dropEffect="copy"})
zone.addEventListener("dragleave",()=>{depth=Math.max(0,depth-1);if(!depth)zone.classList.remove("drag-over")})
zone.addEventListener("drop",(e)=>{
e.preventDefault();depth=0;zone.classList.remove("drag-over")
const files=e.dataTransfer&&e.dataTransfer.files
if(files&&files.length)take(files[0])
})
m.setButtons([
{label:"Cancel"},
{label:"Browse...",primary:true,keepOpen:true,onClick:()=>{pick(null,st);return false}},
])
}
function pick(staged,st){
if(st)status(st,staged?"Checking the file...":"Choose a file...")
return call("reportsIO.pick_import",staged?[kind,staged]:[kind]).then((res)=>{
if(!res){if(st)status(st,"");return}
stepConfirm(res)
}).catch((err)=>{
if(st)status(st,errText(err,"Import failed."),"error")
else stepPick(errText(err,"Import failed."),true)
})
}
function stepConfirm(res){
const s=res.summary||{}
body.textContent=""
const head=el("div","rpt-x-sub")
head.appendChild(el("span","rpt-x-sub-title",res.name||"File"))
head.appendChild(el("span","rpt-x-sub-meta",res.label||res.kind||""))
body.appendChild(head)
const chips=el("div","rpt-x-chips")
summaryChips(s).forEach((c)=>chips.appendChild(el("span","rpt-x-count",c)))
body.appendChild(chips)
if(s.severity){
const sev=el("div","rpt-x-sevs")
SEVERITIES.forEach((p)=>{
const n=s.severity[p[0]]||0
const b=el("span","rpt-x-sev rpt-sev rpt-sev-"+p[0],p[1]+" "+n)
if(!n)b.classList.add("zero")
sev.appendChild(b)
})
body.appendChild(sev)
}
const options={}
let target=null,info=null
if(res.kind==="findings_csv"){
const field=el("label","rpt-x-field")
field.appendChild(el("span","rpt-x-field-label","Add the findings to"))
target=el("select","rpt-input rpt-select rpt-x-select")
const fresh=el("option",null,"A new report")
fresh.value=""
target.appendChild(fresh)
field.appendChild(target)
body.appendChild(field)
call("reports.list",[],[]).then((list)=>{
;(list||[]).forEach((r)=>{const o=el("option",null,(r.title||"Untitled report")+(r.client?" - "+r.client:""));o.value=String(r.id);target.appendChild(o)})
const want=opts.reportId!==undefined&&opts.reportId!==null?String(opts.reportId):(window.Reporting&&typeof Reporting.current==="function"&&Reporting.current()?String(Reporting.current().id):"")
if(want&&[...target.options].some((o)=>o.value===want))target.value=want
}).catch(()=>{})
if(s.scanner&&s.severity&&s.severity.info){
info=check("Include informational findings ("+s.severity.info+")",false,"Scanner exports usually carry many informational rows")
body.appendChild(info.wrap)
}
if(s.columns){
const cols=Object.keys(s.columns).filter((k)=>k!=="plugin_id").map((k)=>k.replace(/_/g," ")+" = "+s.columns[k])
body.appendChild(el("div","rpt-x-note","Columns recognised: "+cols.join("; ")))
}
}
if(Array.isArray(s.items)&&s.items.length){
const list=el("div","rpt-x-items")
s.items.forEach((it)=>{
const row=el("div","rpt-x-item")
row.appendChild(el("span","rpt-x-item-title",it.title||""))
row.appendChild(el("span","rpt-x-item-detail",it.detail||""))
list.appendChild(row)
})
const shown=s.items.length,all=(s.reports||0)+(s.templates||0)+(s.library||0)||s.findings||shown
if(all>shown)list.appendChild(el("div","rpt-x-item rpt-x-item-more","and "+(all-shown)+" more"))
body.appendChild(list)
}
;(s.warnings||[]).forEach((w)=>body.appendChild(el("div","rpt-x-warn",w)))
const st=el("div","rpt-x-status")
body.appendChild(st)
let busy=false
m.setButtons([
{label:"Back",left:true,keepOpen:true,onClick:()=>{if(!busy)stepPick();return false}},
{label:"Cancel"},
{label:"Import",primary:true,keepOpen:true,onClick:(ctl,btn)=>{
if(busy)return false
busy=true
btn.disabled=true
status(st,"Importing...")
if(target&&target.value)options.report_id=parseInt(target.value,10)
if(info)options.include_info=info.input.checked
call("reportsIO.apply_import",[res.path,res.kind,options]).then((out)=>stepDone(out||{})).catch((err)=>{
busy=false
btn.disabled=false
status(st,errText(err,"Import failed."),"error")
})
return false
}},
])
}
function stepDone(out){
body.textContent=""
body.appendChild(el("div","rpt-x-done",out.message||"Import finished."))
toast(out.message||"Import finished.")
if(window.Reporting&&typeof Reporting.refresh==="function"){try{Reporting.refresh()}catch(e){}}
if(typeof opts.onDone==="function"){try{opts.onDone(out)}catch(e){}}
const ids=Array.isArray(out.report_ids)?out.report_ids:[]
const buttons=[{label:"Close",primary:!ids.length}]
if(ids.length===1)buttons.push({label:"Open report",primary:true,onClick:()=>{openReport(ids[0])}})
m.setButtons(buttons)
}
if(opts.picked&&opts.picked.path)stepConfirm(opts.picked)
else if(opts.staged&&opts.staged.path){
stepPick("Checking the file...")
pick(opts.staged.path,body.querySelector(".rpt-x-status"))
}else stepPick()
return m
}
function openReport(id){
const go=()=>{if(window.Reporting&&typeof Reporting.open==="function")return Reporting.open(id)}
if(typeof goToPage==="function"){
const r=goToPage("reporting")
if(r&&typeof r.then==="function")return r.then(go).catch(()=>{})
setTimeout(go,60)
return
}
go()
}
// A staged upload from another drop zone (Settings): open the import dialog only when the file is one of ours.
function tryStaged(path,name){
return call("reportsIO.sniff",[path],{kind:""}).then((r)=>{
if(!r||!r.kind)return false
openImport({staged:{path:path,name:name},kind:r.kind})
return true
}).catch(()=>false)
}
// ---- report defaults form (Settings > Import & Export) ----
function mountDefaults(host){
if(!host)return Promise.resolve(null)
host.textContent=""
host.classList.add("rpt-x-defaults")
const row=(label,control,hint)=>{
const f=el("label","rpt-x-field")
f.appendChild(el("span","rpt-x-field-label",label))
f.appendChild(control)
if(hint)f.appendChild(el("span","rpt-x-check-hint",hint))
return f
}
const text=(ph,max)=>{const i=el("input","rpt-input");i.type="text";i.placeholder=ph||"";if(max)i.maxLength=max;return i}
const select=(pairs)=>{const s=el("select","rpt-input rpt-select");pairs.forEach((p)=>{const o=el("option",null,p[1]);o.value=p[0];s.appendChild(o)});return s}
const fmt=select(FORMATS.map((f)=>[f.id,f.label+" (."+f.ext+")"]))
const size=select([["A4","A4"],["Letter","US Letter"]])
const cls=text("Confidential",80)
const company=text("Your company name",200)
const subtitle=text("Penetration Test Report",300)
const banner=text("Confidential - {{client}} only",300)
const footer=text("Company - website - contact",300)
const accent=text("#1f4e79",7)
const secondary=text("#5b6770",7)
const testers=el("textarea","rpt-input rpt-x-testers")
testers.rows=3
testers.placeholder="Name, Role, Email (one per line)"
const toc=check("Table of contents",true)
const app=check("Appendices",true)
const coverCk=check("Cover page",true)
const redact=check("Mask secrets when evidence is captured",true)
const swatch=(input)=>{
const w=el("span","rpt-x-color")
const dot=el("span","rpt-x-swatch")
const paint=()=>{const ok=validHex(input.value);dot.style.background=ok?input.value.trim():"transparent";input.classList.toggle("invalid",!!input.value.trim()&&!ok)}
input.addEventListener("input",paint)
w.appendChild(dot);w.appendChild(input)
w._paint=paint
return w
}
const accentW=swatch(accent),secondaryW=swatch(secondary)
let logoUid=""
const logoBox=el("div","rpt-x-logo")
const logoPrev=el("div","rpt-x-logo-prev","No logo")
const logoPick=el("button","rpt-btn rpt-btn-small","Choose logo...")
logoPick.type="button"
const logoClear=el("button","rpt-btn rpt-btn-small","Remove")
logoClear.type="button"
const logoInput=el("input","hidden")
logoInput.type="file"
logoInput.accept="image/png,image/jpeg,image/gif,image/webp"
logoBox.appendChild(logoPrev);logoBox.appendChild(logoPick);logoBox.appendChild(logoClear);logoBox.appendChild(logoInput)
const st=el("div","rpt-x-status")
function showLogo(uid){
logoUid=uid||""
logoClear.classList.toggle("hidden",!logoUid)
if(!logoUid){logoPrev.textContent="No logo";return}
call("reports.asset_get",[logoUid]).then((a)=>{
if(logoUid!==uid||!a||!/^data:image\/(png|jpeg|gif|webp);base64,/.test(a.data_url||""))return
logoPrev.textContent=""
const img=el("img")
img.alt="Logo"
img.src=a.data_url
logoPrev.appendChild(img)
}).catch(()=>{logoPrev.textContent="Logo not available"})
}
logoPick.addEventListener("click",()=>{logoInput.value="";logoInput.click()})
logoClear.addEventListener("click",()=>showLogo(""))
logoInput.addEventListener("change",()=>{
const file=logoInput.files&&logoInput.files[0]
if(!file)return
if(file.size>10*1024*1024){status(st,"The logo is larger than 10 MB.","error");return}
readB64(file).then((b64)=>call("reports.asset_add",[file.name,b64])).then((a)=>{showLogo(a.uid);status(st,"Logo added. Save to keep it.")}).catch((err)=>status(st,errText(err,"Could not add the logo."),"error"))
})
const grid=el("div","rpt-x-defgrid")
grid.appendChild(row("Default export format",fmt))
grid.appendChild(row("Page size",size))
grid.appendChild(row("Default classification",cls))
grid.appendChild(row("Company",company))
grid.appendChild(row("Cover subtitle",subtitle))
grid.appendChild(row("Confidentiality banner",banner,"Shown at the top of every page"))
grid.appendChild(row("Footer text",footer))
grid.appendChild(row("Accent colour",accentW))
grid.appendChild(row("Secondary colour",secondaryW))
host.appendChild(grid)
const two=el("div","rpt-x-defgrid rpt-x-defgrid-wide")
const logoField=el("div","rpt-x-field")
logoField.appendChild(el("span","rpt-x-field-label","Logo"))
logoField.appendChild(logoBox)
two.appendChild(logoField)
two.appendChild(row("Default testers",testers,"Name, Role, Email - one tester per line"))
host.appendChild(two)
const toggles=el("div","rpt-x-toggles")
;[toc,app,coverCk,redact].forEach((c)=>toggles.appendChild(c.wrap))
host.appendChild(toggles)
const actions=el("div","rpt-x-defactions")
const save=el("button","rpt-btn rpt-btn-primary","Save defaults")
save.type="button"
actions.appendChild(save)
actions.appendChild(st)
host.appendChild(actions)
function fill(d){
d=d||{}
const b=d.branding||{}
fmt.value=d.default_format||"pdf"
size.value=d.page_size==="Letter"?"Letter":"A4"
cls.value=d.classification||""
company.value=b.company||""
subtitle.value=b.cover_subtitle||""
banner.value=b.banner||""
footer.value=b.footer||""
accent.value=b.accent||""
secondary.value=b.secondary||""
accentW._paint();secondaryW._paint()
testers.value=formatTesters(d.testers)
toc.input.checked=d.include_toc!==false
app.input.checked=d.include_appendices!==false
coverCk.input.checked=b.show_cover!==false
redact.input.checked=d.redact_evidence!==false
showLogo(b.logo_asset||"")
}
save.addEventListener("click",()=>{
for(const c of [accent,secondary]){
if(c.value.trim()&&!validHex(c.value)){status(st,"Colours must look like #1f4e79.","error");c.focus();return}
}
const branding={company:company.value.trim(),cover_subtitle:subtitle.value.trim(),banner:banner.value.trim(),footer:footer.value.trim(),logo_asset:logoUid,show_cover:coverCk.input.checked}
if(validHex(accent.value))branding.accent=accent.value.trim().toLowerCase()
if(validHex(secondary.value))branding.secondary=secondary.value.trim().toLowerCase()
const patch={default_format:fmt.value,page_size:size.value,classification:cls.value.trim(),include_toc:toc.input.checked,include_appendices:app.input.checked,redact_evidence:redact.input.checked,testers:parseTesters(testers.value),branding:branding}
save.disabled=true
status(st,"Saving...")
call("reports.defaults_set",[patch]).then((d)=>{save.disabled=false;fill(d);status(st,"Saved. New reports start with these values.","ok")}).catch((err)=>{save.disabled=false;status(st,errText(err,"Could not save the defaults."),"error")})
})
return call("reports.defaults_get",[]).then((d)=>{fill(d);return d}).catch((err)=>{status(st,errText(err,"Report defaults are not available."),"error");return null})
}
return {open:open,openImport:openImport,exportAll:exportAll,exportTemplates:exportTemplates,exportLibrary:exportLibrary,tryStaged:tryStaged,mountDefaults:mountDefaults,
_pure:{FORMATS:FORMATS,exportMessage:exportMessage,applicable:applicable,initialState:initialState,exportOptions:exportOptions,cleanStatuses:cleanStatuses,summaryChips:summaryChips,parseTesters:parseTesters,formatTesters:formatTesters,validHex:validHex,importable:importable,fileExt:fileExt,esc:esc,plural:plural}}
})()
if(typeof module!=="undefined"&&module.exports)module.exports=ReportExport
if(typeof window!=="undefined")window.ReportExport=ReportExport
