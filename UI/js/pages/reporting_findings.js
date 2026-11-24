// Reporting: the findings workspace (list + finding editor) used inside the report editor, and the finding library manager.
var ReportFindings=(function(){
const RC=ReportCore,RW=ReportWidgets
const el=RW.el
const esc=RC.escapeHtml
const SAVE_DELAY=700
const RICH_FIELDS=[
{key:"description",label:"Description",placeholder:"What the vulnerability is and where it was found."},
{key:"impact",label:"Impact",placeholder:"What an attacker gains and what it means for the business."},
{key:"steps",label:"Steps to reproduce",placeholder:"Numbered steps, requests and commands that reproduce the issue."},
{key:"remediation",label:"Remediation",placeholder:"How to fix it, with short-term mitigations where useful."}
]
// Same rule as ReportTargets.SECRET_KEY_RX / reports_service._TARGET_SECRET_KEY_RE (kept here so the filter never depends on load order).
const SECRET_KEY_RX=/pass|pwd|secret|token|hash|key|cred|cookie|session|private|otp|pin|user|login/i
const CONTENT_KEYS=["title","severity","cvss_vector","cwe","owasp","references","description","impact","likelihood","steps","remediation","tags","cves"]
let current=null
function call(method,args){return bridgeCall("reports."+method,args||[])}
function oops(fallback){return (err)=>{RW.toast(RW.errText(err,fallback),true)}}
function clone(o){return JSON.parse(JSON.stringify(o===undefined?null:o))}
function arr(v){return Array.isArray(v)?v:[]}
function iconBtn(icon,title,cls){
const b=el("button","rpt-icon-btn"+(cls?" "+cls:""))
b.type="button"
b.title=title
b.setAttribute("aria-label",title)
b.innerHTML=`<i class="icon icon-${icon}"></i>`
return b
}
function textBtn(label,cls,title,icon){
const b=el("button","rpt-btn"+(cls?" "+cls:""))
b.type="button"
if(title)b.title=title
b.innerHTML=(icon?`<i class="icon icon-${icon}"></i>`:"")+`<span>${esc(label)}</span>`
return b
}
function selectEl(options,value,cls){
const s=el("select","rpt-input rpt-select"+(cls?" "+cls:""))
options.forEach((o)=>{const op=el("option",null,o[1]);op.value=o[0];s.appendChild(op)})
s.value=value===undefined||value===null?"":value
return s
}
function datalist(id,values){
let dl=document.getElementById(id)
if(dl)return dl
dl=el("datalist")
dl.id=id
values.forEach((v)=>{const op=el("option");op.value=v[0];if(v[1])op.label=v[1];dl.appendChild(op)})
document.body.appendChild(dl)
return dl
}
function scoreText(f){
return typeof f.cvss_score==="number"&&isFinite(f.cvss_score)?f.cvss_score.toFixed(1):""
}
function pickContent(src){
const out={}
CONTENT_KEYS.forEach((k)=>{if(src&&src[k]!==undefined&&src[k]!==null)out[k]=clone(src[k])})
return out
}
function prefixOf(ctx){
const r=ctx&&typeof ctx.getReport==="function"?ctx.getReport():null
const p=r&&r.options?r.options.finding_id_prefix:undefined
return p===undefined||p===null?"F-":String(p)
}

// ---- AI review: results are always shown first and applied only on Accept ----
function aiReview(title,result,onAccept){
const box=el("div","rpt-ai-review")
box.appendChild(el("div","rpt-ai-note","Review the suggestion. Nothing changes until you accept it."))
let html=""
if(result&&result.vector){
const sc=RC.cvssScore(result.vector)
const v=el("div","rpt-ai-vector")
v.innerHTML=`<code>${esc(result.vector)}</code>`+(sc===null?'<span class="rpt-ai-bad">Not a valid CVSS 3.1 vector</span>':`<span class="rpt-cvss-pill" data-sev="${RC.sevFromScore(sc)}">${sc.toFixed(1)}</span>${RW.severityBadge(RC.sevFromScore(sc))}`)
box.appendChild(v)
}
if(result&&result.html)html=RC.sanitizeHtml(result.html)
else if(result&&result.text)html=ReportRich.plainToHtml(result.text)
if(html)box.appendChild(ReportRich.render(el("div","rpt-ai-result"),html))
const valid=result&&(result.vector?RC.cvssScore(result.vector)!==null:!!html)
RW.modal({title:title,bodyEl:box,wide:true,buttons:[
{label:"Discard"},
{label:"Accept",primary:true,onClick:()=>{if(valid)onAccept({html:html,vector:result.vector||"",text:result.text||""})}}
]})
}
function aiRun(action,payload,title,onAccept,btn){
const ai=window.ReportAI
if(!ai||typeof ai.run!=="function")return
if(btn){btn.disabled=true;btn.classList.add("busy")}
Promise.resolve().then(()=>ai.run(action,payload)).then((res)=>{
if(res&&(res.html||res.text||res.vector))aiReview(title,res,onAccept)
}).catch(oops("The AI request failed.")).then(()=>{if(btn){btn.disabled=false;btn.classList.remove("busy")}})
}

// ---- library ----
function libraryFilter(list,query,category){
const q=String(query||"").trim().toLowerCase()
return list.filter((e)=>(!category||(e.category||"")===category)&&(!q||[e.title,e.category,e.cwe,e.owasp,e.severity].join(" ").toLowerCase().indexOf(q)>=0))
}
function libraryEdit(entry,onSaved){
const e=entry?clone(entry):{title:"",category:"",severity:"medium",cvss_vector:"",cwe:"",owasp:"",likelihood:"",references:[],tags:[],description:"",impact:"",steps:"",remediation:""}
const form=el("div","rpt-form rpt-lib-form")
const riches={}
function row(label,control,cls){
const r=el("label","rpt-field"+(cls?" "+cls:""))
r.appendChild(el("span","rpt-field-label",label))
r.appendChild(control)
form.appendChild(r)
return control
}
function input(value,placeholder,list){
const i=el("input","rpt-input")
i.type="text"
i.value=value||""
i.spellcheck=false
if(placeholder)i.placeholder=placeholder
if(list)i.setAttribute("list",list)
return i
}
const grid=el("div","rpt-form-grid")
form.appendChild(grid)
function gridRow(label,control){
const r=el("label","rpt-field")
r.appendChild(el("span","rpt-field-label",label))
r.appendChild(control)
grid.appendChild(r)
return control
}
datalist("rptCweList",RC.COMMON_CWES)
datalist("rptOwaspList",RC.OWASP_TOP10.map((o)=>[o]))
const title=row("Title",input(e.title,"Reflected cross-site scripting"))
form.insertBefore(title.parentNode,grid)
const category=gridRow("Category",input(e.category,"Web, Network, Active Directory..."))
const severity=gridRow("Severity",selectEl(RC.SEVERITIES.map((s)=>[s.id,s.label]),e.severity||"medium"))
const vector=gridRow("CVSS 3.1 vector",input(e.cvss_vector,"CVSS:3.1/AV:N/AC:L/..."))
const likelihood=gridRow("Likelihood",selectEl(RC.LIKELIHOODS.map((s)=>[s.id,s.label]),e.likelihood||""))
const cwe=gridRow("CWE",input(e.cwe,"CWE-79","rptCweList"))
const owasp=gridRow("OWASP",input(e.owasp,"A03:2021 Injection","rptOwaspList"))
RICH_FIELDS.forEach((rf)=>{
const wrap=el("div","rpt-field")
wrap.appendChild(el("span","rpt-field-label",rf.label))
form.appendChild(wrap)
riches[rf.key]=ReportRich.create(wrap,{html:e[rf.key]||"",placeholder:rf.placeholder,compact:true,minHeight:70})
})
const refs=el("textarea","rpt-input rpt-textarea")
refs.rows=3
refs.spellcheck=false
refs.placeholder="One URL per line"
refs.value=arr(e.references).join("\n")
row("References",refs)
const tags=row("Tags",input(arr(e.tags).join(", "),"Comma separated"))
const err=el("div","rpt-form-error")
form.appendChild(err)
let touched=false
form.addEventListener("input",()=>{touched=true})
const m=RW.modal({title:entry?"Edit library entry":"New library entry",bodyEl:form,wide:true,closeOnBackdrop:false,confirmClose:()=>touched?"Discard the changes to this library entry?":"",onClose:()=>Object.keys(riches).forEach((k)=>riches[k].destroy()),buttons:[
{label:"Cancel"},
{label:"Save",primary:true,keepOpen:true,onClick:(ctl,btn)=>{
const v=vector.value.trim()
if(!title.value.trim()){err.textContent="Give the entry a title.";return false}
if(v&&!RC.cvssParse(v).valid){err.textContent="CVSS vector: "+RC.cvssParse(v).error;return false}
const out=Object.assign({},e,{title:title.value.trim(),category:category.value.trim(),severity:severity.value,cvss_vector:v?RC.cvssBuild(RC.cvssParse(v).metrics):"",likelihood:likelihood.value,cwe:cwe.value.trim(),owasp:owasp.value.trim(),
references:refs.value.split("\n").map((s)=>s.trim()).filter(Boolean),tags:tags.value.split(",").map((s)=>s.trim()).filter(Boolean)})
RICH_FIELDS.forEach((rf)=>{out[rf.key]=riches[rf.key].getHTML()})
btn.disabled=true
call("library_save",[out]).then((saved)=>{m.close();RW.toast("Library entry saved");if(onSaved)onSaved(saved||out)}).catch((e2)=>{btn.disabled=false;err.textContent=RW.errText(e2,"Could not save the entry.")})
return false
}}
]})
setTimeout(()=>title.focus(),30)
}
function openLibrary(opts){
opts=opts||{}
const inst=current
const st={list:[],query:"",category:"",selected:null,entry:null}
const wrap=el("div","rpt-lib")
const side=el("div","rpt-lib-side")
const view=el("div","rpt-lib-view")
wrap.appendChild(side)
wrap.appendChild(view)
const search=el("input","rpt-input rpt-lib-search")
search.type="text"
search.placeholder="Search the library"
search.spellcheck=false
const cat=selectEl([["","All categories"]],"")
const tools=el("div","rpt-lib-tools")
tools.appendChild(search)
tools.appendChild(cat)
side.appendChild(tools)
const listEl=el("div","rpt-lib-list")
side.appendChild(listEl)
const newBtn=textBtn("New entry","rpt-btn-small","Write a reusable finding","add")
side.appendChild(newBtn)
function renderCats(){
const cats=Array.from(new Set(st.list.map((e)=>e.category||"").filter(Boolean))).sort()
const keep=st.category
cat.innerHTML=""
;[["","All categories"]].concat(cats.map((c)=>[c,c])).forEach((o)=>{const op=el("option",null,o[1]);op.value=o[0];cat.appendChild(op)})
cat.value=cats.indexOf(keep)>=0?keep:""
st.category=cat.value
}
function renderList(){
const shown=libraryFilter(st.list,st.query,st.category)
listEl.innerHTML=""
if(!shown.length){listEl.appendChild(el("div","rpt-empty",st.list.length?"No entries match.":"The library is empty."));return}
shown.forEach((e)=>{
const b=el("button","rpt-lib-item"+(st.selected===e.id?" active":""))
b.type="button"
b.innerHTML=`<span class="rpt-lib-item-title">${esc(e.title||"Untitled")}</span><span class="rpt-lib-item-meta">${RW.severityBadge(e.severity)}${e.category?`<span class="rpt-lib-cat">${esc(e.category)}</span>`:""}${typeof e.cvss_score==="number"?`<span class="rpt-score">${e.cvss_score.toFixed(1)}</span>`:""}</span>`
b.addEventListener("click",()=>select(e.id))
listEl.appendChild(b)
})
}
function renderView(){
view.innerHTML=""
const e=st.entry
if(!e){view.appendChild(el("div","rpt-empty","Select an entry to preview it."));return}
const head=el("div","rpt-lib-head")
head.appendChild(el("div","rpt-lib-title",e.title||"Untitled"))
const meta=el("div","rpt-lib-meta")
const sc=RC.cvssScore(e.cvss_vector)
meta.innerHTML=RW.severityBadge(e.severity)+(sc!==null?`<span class="rpt-score">CVSS ${sc.toFixed(1)}</span>`:"")+(e.category?`<span class="rpt-lib-cat">${esc(e.category)}</span>`:"")+(e.cwe?`<span class="rpt-lib-cat">${esc(e.cwe)}</span>`:"")+(e.owasp?`<span class="rpt-lib-cat">${esc(e.owasp)}</span>`:"")
head.appendChild(meta)
if(e.cvss_vector)head.appendChild(el("div","rpt-lib-vector",e.cvss_vector))
view.appendChild(head)
const actions=el("div","rpt-lib-actions")
if(inst&&inst.alive()){
const add=textBtn("Add to current report","rpt-btn-primary rpt-btn-small","Copy this entry into the open report as a new finding","add")
add.addEventListener("click",()=>{add.disabled=true;inst.addFromLibrary(e.id).then(()=>{if(opts.closeOnAdd)m.close()}).catch(()=>{}).then(()=>{add.disabled=false})})
actions.appendChild(add)
}
const edit=textBtn("Edit","rpt-btn-small","Edit this entry","edit")
edit.addEventListener("click",()=>libraryEdit(e,(saved)=>{st.selected=saved&&saved.id!==undefined?saved.id:st.selected;load()}))
actions.appendChild(edit)
const del=textBtn("Delete","rpt-btn-small rpt-btn-danger","Delete this entry","trash")
del.addEventListener("click",()=>RW.confirm("Delete \""+(e.title||"Untitled")+"\" from the finding library?",{danger:true}).then((ok)=>{
if(!ok)return
call("library_delete",[e.id]).then(()=>{st.selected=null;st.entry=null;RW.toast("Library entry deleted");load()}).catch(oops("Could not delete the entry."))
}))
actions.appendChild(del)
view.appendChild(actions)
const bodyEl=el("div","rpt-lib-body")
RICH_FIELDS.forEach((rf)=>{
if(!e[rf.key])return
bodyEl.appendChild(el("div","rpt-lib-section",rf.label))
bodyEl.appendChild(ReportRich.render(el("div"),e[rf.key]))
})
if(arr(e.references).length){
bodyEl.appendChild(el("div","rpt-lib-section","References"))
const ul=el("ul","rpt-lib-refs")
arr(e.references).forEach((r)=>ul.appendChild(el("li",null,r)))
bodyEl.appendChild(ul)
}
if(arr(e.tags).length){
const t=el("div","rpt-chips")
arr(e.tags).forEach((x)=>t.appendChild(el("span","rpt-chip",x)))
bodyEl.appendChild(t)
}
view.appendChild(bodyEl)
}
function select(id){
st.selected=id
renderList()
call("library_get",[id]).then((e)=>{if(st.selected===id){st.entry=e;renderView()}}).catch(oops("Could not load the entry."))
}
function load(){
return call("library_list").then((list)=>{
st.list=arr(list)
renderCats()
renderList()
if(st.selected!==null&&st.list.some((e)=>e.id===st.selected))select(st.selected)
else{st.selected=null;st.entry=null;renderView()}
}).catch((err)=>{listEl.innerHTML="";listEl.appendChild(el("div","rpt-empty",RW.errText(err,"The library could not be loaded.")))})
}
search.addEventListener("input",()=>{st.query=search.value;renderList()})
cat.addEventListener("change",()=>{st.category=cat.value;renderList()})
newBtn.addEventListener("click",()=>libraryEdit(null,(saved)=>{st.selected=saved&&saved.id!==undefined?saved.id:null;load()}))
const m=RW.modal({title:opts.title||"Finding library",bodyEl:wrap,wide:true,className:"rpt-modal-lib",buttons:[{label:"Close"}]})
renderView()
load()
setTimeout(()=>search.focus(),30)
return m
}

// ---- CVEs: picker (CVE Intel cache / live lookup by id), manual entry form and the per-field merge dialog ----
// Everything that comes from CVE Intel is remote plain text: it only ever reaches the page through textContent or esc().
const CV=typeof ReportCve!=="undefined"?ReportCve:null
function cveCall(method,args){return bridgeCall("cve."+method,args||[])}
function cveMissing(err){return /bridge method missing/.test(RW.errText(err,""))}
function openUrl(url){
const u=CV.safeUrl(url)
if(u)bridgeCall("notes.open_url",[u]).catch(oops("Could not open the link."))
}
function cveBadges(c){
const sc=CV.score(c.cvss_score!==undefined?c.cvss_score:c.score)
const sv=CV.sev(c.severity)
return (sv?RW.severityBadge(sv):"")+(sc===null?"":`<span class="rpt-score" title="CVSS${c.cvss_version?" "+esc(c.cvss_version):""} base score">${sc.toFixed(1)}</span>`)+(c.kev===true?'<span class="rpt-kev" title="Listed in the CISA Known Exploited Vulnerabilities catalog">Known exploited</span>':"")
}
function cveForm(entry,opts){
opts=opts||{}
const isNew=!!opts.isNew
const e=Object.assign({id:"",title:"",cvss_version:"3.1",cvss_vector:"",cvss_score:null,severity:"",cwe:"",description:"",remediation:"",references:[],kev:false,kev_due:"",epss:null,source:"manual",fetched_at:""},entry||{})
const form=el("div","rpt-form rpt-cve-form")
if(opts.note)form.appendChild(el("div","rpt-ai-note",opts.note))
function input(value,placeholder,cls){
const i=el("input","rpt-input"+(cls?" "+cls:""))
i.type="text"
i.value=value===null||value===undefined?"":String(value)
i.spellcheck=false
if(placeholder)i.placeholder=placeholder
return i
}
function field(host,label,control,cls){
const r=el("label","rpt-field"+(cls?" "+cls:""))
r.appendChild(el("span","rpt-field-label",label))
r.appendChild(control)
host.appendChild(r)
return control
}
function area(value,placeholder,rows){
const t=el("textarea","rpt-input rpt-textarea")
t.rows=rows||3
t.spellcheck=false
t.placeholder=placeholder||""
t.value=value||""
return t
}
const top=el("div","rpt-form-grid rpt-cve-grid")
form.appendChild(top)
const idIn=field(top,"CVE ID",input(e.id,"CVE-2024-12345","rpt-mono"))
const titleIn=field(top,"Title",input(e.title,"Short name of the vulnerability"),"rpt-cve-span2")
const verIn=field(top,"CVSS version",selectEl(CV.VERSIONS.map((v)=>[v,"CVSS "+v]).concat([["","Not stated"]]),e.cvss_version||""))
const scoreIn=field(top,"CVSS score",input(e.cvss_score===null?"":Number(e.cvss_score).toFixed(1),"0.0 – 10.0","rpt-mono"))
const sevIn=field(top,"Severity",selectEl([["","From the score"]].concat(RC.SEVERITIES.map((s)=>[s.id,s.label])),isNew?"":(e.severity||"")))
const vecIn=field(top,"CVSS vector",input(e.cvss_vector,"CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H","rpt-mono"),"rpt-cve-span2")
datalist("rptCweList",RC.COMMON_CWES)
const cweIn=field(top,"CWE",input(e.cwe,"CWE-79"))
cweIn.setAttribute("list","rptCweList")
const descIn=field(form,"Description",area(e.description,"What the vulnerability is.",4))
const fixIn=field(form,"How to fix or protect against it",area(e.remediation,"Fixed versions, patches, workarounds and mitigations.",4))
const refsIn=field(form,"References",area(arr(e.references).join("\n"),"One https:// link per line",3))
const kevRow=el("div","rpt-inline-row rpt-cve-kev")
const kevLabel=el("label","rpt-pick-row rpt-cve-check")
const kevIn=el("input")
kevIn.type="checkbox"
kevIn.checked=e.kev===true
kevLabel.appendChild(kevIn)
kevLabel.appendChild(el("span",null,"Known to be exploited (CISA KEV)"))
kevRow.appendChild(kevLabel)
const dueIn=input(e.kev_due,"KEV due date (YYYY-MM-DD)")
kevRow.appendChild(dueIn)
form.appendChild(kevRow)
function syncKev(){dueIn.classList.toggle("hidden",!kevIn.checked)}
kevIn.addEventListener("change",syncKev)
syncKev()
if(!isNew){
const links=el("div","rpt-cve-links")
const id0=CV.normId(e.id)
CV.links(id0,e.kev).forEach((u,i)=>{
const b=el("button","rpt-link",["Open on NVD","Open on cve.org","Open in CISA KEV"][i])
b.type="button"
b.title=u
b.addEventListener("click",()=>openUrl(u))
links.appendChild(b)
})
if(typeof cveOpenDetail==="function"&&typeof opts.onView==="function"){
const b=el("button","rpt-link","View in CVE Intel")
b.type="button"
b.addEventListener("click",()=>{m.close();opts.onView(id0)})
links.appendChild(b)
}
const facts=[e.source==="manual"?"Entered by hand":CV.sourceText(e)+(e.fetched_at?" on "+RC.fmtDate(e.fetched_at):""),e.epss!==null&&e.epss!==undefined&&isFinite(Number(e.epss))?"EPSS "+(Number(e.epss)*100).toFixed(1)+"%":""].filter(Boolean)
links.appendChild(el("span","rpt-muted",facts.join(" · ")))
form.insertBefore(links,top)
}
const err=el("div","rpt-form-error")
form.appendChild(err)
let touched=false
form.addEventListener("input",()=>{touched=true})
// v3 vectors are scored here, so a pasted vector fills the score; other versions keep the score typed by the user.
vecIn.addEventListener("change",()=>{
const v=vecIn.value.trim()
if(!v)return
const m4=/^CVSS:(\d\.\d)\//i.exec(v)
if(m4&&CV.VERSIONS.indexOf(m4[1])>=0)verIn.value=m4[1]
if(/^3\./.test(verIn.value)){const sc=RC.cvssScore(v);if(sc!==null)scoreIn.value=sc.toFixed(1)}
})
function read(){
const id=CV.normId(idIn.value)
if(!id)return "Enter a CVE ID such as CVE-2024-12345."
if(arr(opts.taken).indexOf(id)>=0)return id+" is already on this finding."
const vector=vecIn.value.trim()
const v3=/^3\./.test(verIn.value)&&vector?RC.cvssParse(vector):null
if(v3&&!v3.valid)return "CVSS vector: "+v3.error
let sc=scoreIn.value.trim()===""?null:CV.score(scoreIn.value)
if(scoreIn.value.trim()!==""&&sc===null)return "The CVSS score is a number from 0.0 to 10.0."
if(sc===null&&v3)sc=RC.cvssScore(vector)
const lines=refsIn.value.split("\n").map((s)=>s.trim()).filter(Boolean)
const bad=lines.find((l)=>!CV.safeUrl(l))
if(bad)return "References must be http:// or https:// links: "+bad.slice(0,80)
return CV.normEntry({id:id,title:titleIn.value,cvss_version:vector||sc!==null?verIn.value:"",cvss_vector:v3?RC.cvssBuild(v3.metrics):vector,cvss_score:sc,severity:sevIn.value||(sc===null?"":RC.sevFromScore(sc)),cwe:cweIn.value.replace(/^(?:cwe[-\s]?)?(\d{1,5})$/i,"CWE-$1"),
description:descIn.value,remediation:fixIn.value,references:lines,kev:kevIn.checked,kev_due:kevIn.checked?dueIn.value:"",epss:e.epss,source:isNew?"manual":e.source,fetched_at:e.fetched_at})
}
function act(fn){
return ()=>{
const out=read()
if(typeof out==="string"||!out){err.textContent=out||"Enter a CVE ID.";return false}
m.close()
fn(out)
return false
}
}
const buttons=[]
if(!isNew&&typeof opts.onRemove==="function")buttons.push({label:"Remove",danger:true,left:true,onClick:()=>{opts.onRemove()}})
buttons.push({label:"Cancel"})
if(!isNew&&typeof opts.onLinks==="function")buttons.push({label:"Add links to references",title:"Add the NVD, cve.org and CISA KEV links of this CVE to the finding's references",keepOpen:true,onClick:act((out)=>opts.onLinks(out))})
if(typeof opts.onFill==="function")buttons.push({label:isNew?"Add and fill the finding…":"Fill the finding…",title:"Choose, field by field, what the finding takes from this CVE",keepOpen:true,onClick:act((out)=>opts.onFill(out))})
buttons.push({label:isNew?(opts.okLabel||"Add CVE"):"Save",primary:true,keepOpen:true,onClick:act((out)=>opts.onSave(out))})
const m=RW.modal({title:opts.title||(isNew?"Enter a CVE by hand":e.id),bodyEl:form,wide:true,className:"rpt-modal-cve",closeOnBackdrop:false,confirmClose:()=>touched?"Discard what you typed for this CVE?":"",buttons:buttons})
setTimeout(()=>{const t=isNew&&!e.id?idIn:titleIn;t.focus();try{t.setSelectionRange(0,0)}catch(e2){}},30)
return m
}
// opts: {title,taken:[ids already on the finding],fillLabel:bool,onPick(payload),onManual(entry,fill)}
function cvePicker(opts){
opts=opts||{}
const manual=(id,note)=>cveForm({id:id||""},{isNew:true,note:note,taken:opts.taken,okLabel:opts.manualLabel,onSave:(entry)=>opts.onManual(entry,false),onFill:opts.canFill?(entry)=>opts.onManual(entry,true):null})
return cveCall("status").then((st)=>st||{},(err)=>cveMissing(err)?null:{}).then((status)=>{
// No CVE Intel in this build: manual entry is the whole picker.
if(status===null){manual("","CVE Intel is not available in this build. Enter the CVE by hand; nothing is looked up.");return}
const wrap=el("div","rpt-cve-pick")
const cached=typeof status.cached==="number"?status.cached:null
const note=el("div","rpt-ai-note")
note.textContent=status.can_fetch?"Search looks in the local CVE cache"+(cached===null?"":" ("+cached+" cached)")+". A CVE ID that is not cached can be looked up online.":"From cache only: online lookups are off"+(cached===null?"":" ("+cached+" cached)")+". A CVE that is not cached can be entered by hand."
if(!status.can_fetch)note.classList.add("rpt-cve-offline")
wrap.appendChild(note)
const searchWrap=el("div","rpt-search rpt-cve-search")
searchWrap.innerHTML='<i class="icon icon-search"></i>'
const search=el("input")
search.type="text"
search.placeholder="CVE ID, product or keyword"
search.spellcheck=false
search.setAttribute("aria-label","Search CVEs")
searchWrap.appendChild(search)
const searchRow=el("div","rpt-cve-search-row")
searchRow.appendChild(searchWrap)
const kevLabel=el("label","rpt-cve-kevonly")
const kevOnly=el("input")
kevOnly.type="checkbox"
kevLabel.title="Only CVEs listed in the CISA Known Exploited Vulnerabilities catalog"
kevLabel.appendChild(kevOnly)
kevLabel.appendChild(el("span",null,"KEV only"))
searchRow.appendChild(kevLabel)
wrap.appendChild(searchRow)
const listEl=el("div","rpt-cve-results")
listEl.setAttribute("role","listbox")
wrap.appendChild(listEl)
const err=el("div","rpt-form-error")
wrap.appendChild(err)
let results=[],rows=[],active=0,seq=0,timer=null,busy=false,loaded=false
const m=RW.modal({title:opts.title||"Add a CVE",bodyEl:wrap,wide:true,className:"rpt-modal-cve",onClose:()=>{clearTimeout(timer);seq++},buttons:[
{label:"Enter manually…",left:true,keepOpen:true,title:"Type the CVE yourself; nothing is looked up",onClick:()=>{openManual(CV.extractIds(search.value)[0]||CV.normId(search.value));return false}},
{label:"Close"}
]})
function openManual(id){m.close();manual(id)}
function setActive(i,scroll){
active=Math.max(0,Math.min(rows.length-1,i))
Array.prototype.forEach.call(listEl.children,(n,k)=>{
if(!n.classList.contains("rpt-cve-row"))return
n.classList.toggle("active",k===active)
n.setAttribute("aria-selected",k===active?"true":"false")
if(k===active&&scroll&&n.scrollIntoView)n.scrollIntoView({block:"nearest"})
})
}
function render(){
const typed=CV.extractIds(search.value)
const one=CV.normId(search.value)
if(one&&typed.indexOf(one)<0)typed.push(one)
rows=results.map((r)=>({type:"result",id:CV.normId(r.id),r:r})).filter((r)=>r.id)
typed.forEach((id)=>{if(!rows.some((r)=>r.id===id))rows.push({type:status.can_fetch?"lookup":"manual",id:id})})
listEl.innerHTML=""
if(!rows.length){
listEl.appendChild(el("div","rpt-empty",!loaded?"Searching…":search.value.trim()||kevOnly.checked?"No cached CVE matches. "+(status.can_fetch?"Type the full CVE ID to look it up online, or enter it manually.":"Enter it manually."):"Type a CVE ID, a product or a keyword."))
return
}
rows.forEach((row,i)=>{
const b=el("button","rpt-cve-row")
b.type="button"
b.setAttribute("role","option")
if(row.type==="result"){
const r=row.r
const head=el("span","rpt-cve-row-head")
head.appendChild(el("span","rpt-cve-id",row.id))
const badges=el("span","rpt-cve-badges")
badges.innerHTML=cveBadges({severity:r.severity,cvss_score:r.score,cvss_version:r.cvss_version,kev:r.kev===true})+(typeof r.epss==="number"&&isFinite(r.epss)?`<span class="rpt-lib-cat" title="Probability of exploitation in the next 30 days">EPSS ${(r.epss*100).toFixed(1)}%</span>`:"")
head.appendChild(badges)
// A row of the bundled offline index is a summary (no description, references or EPSS): it is labelled and still pickable.
const offline=r.origin==="index"||r.index_only===true
if(offline){const o=el("span","rpt-cve-origin","offline index");o.title="Summary from the bundled offline CVE index: title, severity and CWE. Look the CVE up online for the full record.";badges.appendChild(o)}
if(r.state==="rejected"){const o=el("span","rpt-cve-origin","rejected");badges.appendChild(o)}
const when=offline?"":(r.fetched_at?"cached "+RC.fmtDate(r.fetched_at):"")
head.appendChild(el("span","rpt-cve-when",arr(opts.taken).indexOf(row.id)>=0?"Already on this finding":when))
b.appendChild(head)
b.appendChild(el("span","rpt-cve-row-title",r.title||CV.preview(r.description,140)||(offline?[r.cwe,r.vendors].filter((x)=>typeof x==="string"&&x).join(" \u00b7 ")||"Summary only":"No description")))
}else{
b.classList.add("rpt-cve-row-action")
b.innerHTML=`<i class="icon icon-${row.type==="lookup"?"search":"edit"}"></i>`
b.appendChild(el("span",null,row.type==="lookup"?"Look up "+row.id+" online":row.id+" is not in the cache – enter it manually"))
}
b.addEventListener("click",()=>choose(row,b))
b.addEventListener("mousemove",()=>{if(active!==i)setActive(i,false)})
listEl.appendChild(b)
})
setActive(Math.min(active,rows.length-1),false)
}
function run(){
const mine=++seq
const q=search.value.trim()
cveCall("search",kevOnly.checked?[q,20,{kev_only:true}]:[q,20]).then((res)=>{
if(mine!==seq)return
results=arr(res&&res.results)
loaded=true
err.textContent=""
active=0
render()
}).catch((e2)=>{
if(mine!==seq)return
results=[]
loaded=true
err.textContent=cveMissing(e2)?"CVE search is not available in this build. Enter the CVE manually.":RW.errText(e2,"The CVE cache could not be searched.")
render()
})
}
function choose(row,btn){
if(!row||busy)return
if(row.type==="manual"){openManual(row.id);return}
busy=true
err.textContent=""
if(btn)btn.classList.add("busy")
const label=btn&&row.type==="lookup"?btn.querySelector("span"):null
if(label)label.textContent="Looking up "+row.id+"…"
cveCall("to_finding",[row.id,null]).then((payload)=>{
if(!payload||!CV.entryFromPayload(payload))throw new Error("CVE Intel returned no usable record for "+row.id+".")
m.close()
opts.onPick(payload)
}).catch((e2)=>{
busy=false
if(btn)btn.classList.remove("busy")
if(label)label.textContent="Look up "+row.id+" online"
err.textContent=RW.errText(e2,"The CVE could not be loaded.")+" You can enter it manually."
})
}
search.addEventListener("input",()=>{clearTimeout(timer);timer=setTimeout(run,180);render()})
kevOnly.addEventListener("change",()=>{clearTimeout(timer);run()})
search.addEventListener("keydown",(e)=>{
if(e.key==="ArrowDown"||e.key==="ArrowUp"){e.preventDefault();if(rows.length)setActive(active+(e.key==="ArrowDown"?1:-1),true)}
else if(e.key==="Enter"){e.preventDefault();if(rows.length)choose(rows[active],listEl.children[active])}
})
render()
run()
setTimeout(()=>search.focus(),30)
})
}
// The per-field choice shown before a CVE writes into a finding. Nothing is applied until Apply.
function cveMerge(f,incoming,entry,onApply){
const rows=CV.mergePlan(f,incoming)
if(!rows.some((r)=>!r.same)){onApply({});return}
const additional=arr(f.cves).some((c)=>c&&c.id!==entry.id)
const choices=CV.planChoices(rows)
const wrap=el("div","rpt-cve-merge")
const head=el("div","rpt-cve-merge-head")
head.appendChild(el("span","rpt-cve-id",entry.id))
const badges=el("span","rpt-cve-badges")
badges.innerHTML=cveBadges(entry)
head.appendChild(badges)
if(entry.title)head.appendChild(el("span","rpt-cve-merge-title",entry.title))
wrap.appendChild(head)
wrap.appendChild(el("div","rpt-ai-note",additional?"This finding already has a CVE, so its text is kept unless you choose otherwise; the links are added to the references. Nothing changes until you apply.":"Empty fields are filled; what you already wrote is kept unless you choose otherwise. Nothing changes until you apply."))
if(incoming.cvss_note&&rows.some((r)=>r.key==="cvss")){const n=el("div","rpt-cvss-v4-note",incoming.cvss_note);n.setAttribute("role","note");wrap.appendChild(n)}
if(entry.source==="index")wrap.appendChild(el("div","rpt-ai-note","This CVE comes from the offline index: a summary (title, severity, CWE). Look it up online in CVE Intel for the description, references and EPSS."))
const table=el("div","rpt-cve-merge-rows")
wrap.appendChild(table)
rows.forEach((row)=>{
const r=el("div","rpt-cve-mrow"+(row.same?" same":""))
r.dataset.key=row.key
r.appendChild(el("div","rpt-cve-mlabel",row.label))
const vals=el("div","rpt-cve-mvals")
const cur=el("div","rpt-cve-mval")
cur.appendChild(el("span","rpt-cve-mcap","Current"))
cur.appendChild(el("span","rpt-cve-mtext"+(row.current?"":" rpt-muted")+(row.kind==="cvss"?" rpt-mono":""),row.current||"Empty"))
const inc=el("div","rpt-cve-mval incoming")
inc.appendChild(el("span","rpt-cve-mcap","From "+entry.id))
inc.appendChild(el("span","rpt-cve-mtext"+(row.kind==="cvss"?" rpt-mono":""),row.incoming))
if(row.kind==="list"){
const ul=el("ul","rpt-cve-mlist")
row.items.slice(0,6).forEach((u)=>ul.appendChild(el("li",row.fresh.indexOf(u)<0?"rpt-muted":"",u)))
if(row.items.length>6)ul.appendChild(el("li","rpt-muted","and "+(row.items.length-6)+" more"))
inc.appendChild(ul)
}
vals.appendChild(cur)
vals.appendChild(inc)
r.appendChild(vals)
const seg=el("div","rpt-cve-seg")
if(row.same)seg.appendChild(el("span","rpt-muted",row.kind==="list"?"Already listed":"Already the same"))
else row.options.forEach((mode)=>{
const b=el("button","rpt-cve-opt"+(choices[row.key]===mode?" active":""),CV.MODE_LABELS[mode])
b.type="button"
b.dataset.mode=mode
b.setAttribute("aria-pressed",choices[row.key]===mode?"true":"false")
b.title={keep:"Leave this field as it is",fill:"Write the CVE's value into the empty field",replace:"Replace what is there with the CVE's value",append:row.kind==="list"?"Add the links that are not listed yet":"Add the CVE's text after what is there"}[mode]
b.addEventListener("click",()=>{
choices[row.key]=mode
Array.prototype.forEach.call(seg.children,(x)=>{x.classList.toggle("active",x===b);x.setAttribute("aria-pressed",x===b?"true":"false")})
r.classList.toggle("changes",mode!=="keep")
})
seg.appendChild(b)
})
r.classList.toggle("changes",!row.same&&choices[row.key]!=="keep")
r.appendChild(seg)
table.appendChild(r)
})
RW.modal({title:"Fill the finding from "+entry.id,bodyEl:wrap,wide:true,className:"rpt-modal-cve rpt-modal-cve-merge",closeOnBackdrop:false,buttons:[
{label:"Cancel"},
{label:"Apply",primary:true,onClick:()=>{onApply(CV.applyMerge(f,incoming,choices))}}
]})
}

// ---- the workspace ----
function mount(host,ctx){
ctx=ctx||{}
const reportId=ctx.reportId
const st={findings:[],selectedId:null,sevFilter:{},statusFilter:"",query:"",pending:{},timers:{},chains:{},inflight:0,failed:false,alive:true}
const ed={id:null,riches:{},cvss:null,els:{},renderCves:null}
const root=el("div","rpt-fw")
const listPane=el("div","rpt-fw-list rpt-pane")
const editPane=el("div","rpt-fw-edit rpt-pane")
root.appendChild(listPane)
root.appendChild(editPane)
host.appendChild(root)

function report(){return typeof ctx.getReport==="function"?(ctx.getReport()||{}):{}}
function byId(id){return st.findings.find((f)=>f.id===id)||null}
function indexOf(id){return st.findings.findIndex((f)=>f.id===id)}
function number(id){return RC.findingNumber(prefixOf(ctx),Math.max(0,indexOf(id)))}
function notify(){
if(typeof ctx.onChanged!=="function")return
try{ctx.onChanged(st.findings.slice())}catch(e){console.error(e)}
}
// Every change the user makes is also reported as an operation, so the page can offer undo / redo for it.
function emit(op){
if(typeof ctx.onOp!=="function")return
try{ctx.onOp(op)}catch(e){console.error(e)}
}
// The report's linked targets a finding affects, as the exports print them ("name (value, value)").
function linkedLabels(f){
const T=window.ReportTargets
if(!T||!arr(f.targets).length)return []
const links=arr(report().targets)
return T.normFindingTargets(f.targets,links).map((t)=>T.affectedLabel(links.find((l)=>l.uid===t.uid),t.keys))
}
function filtersActive(){return !!(st.query.trim()||st.statusFilter||Object.keys(st.sevFilter).some((k)=>st.sevFilter[k]))}
function visible(){
const q=st.query.trim().toLowerCase()
const sevOn=Object.keys(st.sevFilter).filter((k)=>st.sevFilter[k])
return st.findings.filter((f)=>{
if(sevOn.length&&sevOn.indexOf(f.severity)<0)return false
if(st.statusFilter&&f.status!==st.statusFilter)return false
if(!q)return true
return [f.title,f.cwe,f.owasp,arr(f.tags).join(" "),arr(f.cves).map((c)=>c.id).join(" "),arr(f.affected).map((a)=>(a.name||"")+" "+(a.value||"")).join(" "),linkedLabels(f).join(" ")].join(" ").toLowerCase().indexOf(q)>=0
})
}

// ---- autosave ----
function setSaveState(){
const s=ed.els.save
if(!s)return
const dirty=Object.keys(st.pending).length>0
let text="Saved",cls=""
if(st.failed){text="Save failed \u2013 retry";cls="error"}
else if(st.inflight>0){text="Saving\u2026";cls="busy"}
else if(dirty){text="Unsaved changes";cls="busy"}
s.textContent=text
s.className="rpt-save-state"+(cls?" "+cls:"")
s.title=st.failed?"Click to try saving again":""
}
function send(id){
if(st.timers[id]){clearTimeout(st.timers[id]);delete st.timers[id]}
const run=()=>{
const p=st.pending[id]
if(!p)return Promise.resolve()
delete st.pending[id]
st.inflight++
setSaveState()
return call("finding_update",[id,p]).then((res)=>{
st.inflight--
st.failed=false
const f=byId(id)
const newer=st.pending[id]||{}
if(f&&res){
// Only server-owned values come back into the local copy: the fields being typed in are never re-rendered from a response.
if(res.updated_at)f.updated_at=res.updated_at
if(!("cvss_vector" in newer)&&res.cvss_score!==undefined)f.cvss_score=res.cvss_score
}
renderList()
syncEditorDerived()
setSaveState()
notify()
}).catch((err)=>{
st.inflight--
st.pending[id]=Object.assign({},p,st.pending[id]||{})
if(!st.failed)RW.toast(RW.errText(err,"The finding could not be saved."),true)
st.failed=true
setSaveState()
})
}
st.chains[id]=(st.chains[id]||Promise.resolve()).then(run,run)
return st.chains[id]
}
function patch(id,p){
const f=byId(id)
if(!f)return
const before={}
Object.keys(p).forEach((k)=>{before[k]=clone(f[k])})
emit({type:"edit",id:id,title:f.title||"",before:before,after:clone(p)})
Object.assign(f,p)
st.pending[id]=Object.assign(st.pending[id]||{},clone(p))
if(st.timers[id])clearTimeout(st.timers[id])
st.timers[id]=setTimeout(()=>send(id),SAVE_DELAY)
renderList()
setSaveState()
notify()
}
function flush(){
Object.keys(ed.riches).forEach((k)=>ed.riches[k].flush())
const ids=Array.from(new Set(Object.keys(st.pending).concat(Object.keys(st.timers)).map(Number)))
return Promise.all(ids.map(send).concat(Object.keys(st.chains).map((k)=>st.chains[k]))).then(()=>{})
}
function isDirty(){
return Object.keys(st.pending).length>0||st.inflight>0||Object.keys(ed.riches).some((k)=>ed.riches[k].isPending())
}

// ---- list pane ----
const lp={}
function buildList(){
const actions=el("div","rpt-fw-actions")
const add=textBtn("New finding","rpt-btn-primary","Add an empty finding","add")
const lib=textBtn("From library\u2026","","Add a finding from the reusable library")
const notes=textBtn("From notes\u2026","","Import the finding callouts written in your notes")
actions.appendChild(add)
actions.appendChild(lib)
actions.appendChild(notes)
if(CV){
const cve=textBtn("From CVE\u2026","","Write a new finding from a CVE")
actions.appendChild(cve)
cve.addEventListener("click",newFromCve)
}
listPane.appendChild(actions)
const tools=el("div","rpt-fw-tools")
const searchWrap=el("div","rpt-search")
searchWrap.innerHTML='<i class="icon icon-search"></i>'
const search=el("input")
search.type="text"
search.placeholder="Search findings"
search.spellcheck=false
searchWrap.appendChild(search)
tools.appendChild(searchWrap)
const status=selectEl([["","Any status"]].concat(RC.STATUSES.map((s)=>[s.id,s.label])),"","rpt-select-small")
status.title="Filter by status"
tools.appendChild(status)
const sort=textBtn("Sort","rpt-btn-small","Reorder the findings in the report")
tools.appendChild(sort)
listPane.appendChild(tools)
const chips=el("div","rpt-fw-sevs")
listPane.appendChild(chips)
const rows=el("div","rpt-fw-rows")
listPane.appendChild(rows)
const foot=el("div","rpt-fw-foot")
listPane.appendChild(foot)
lp.search=search
lp.status=status
lp.chips=chips
lp.rows=rows
lp.foot=foot
add.addEventListener("click",()=>addFinding({title:"New finding",severity:"medium",status:"open"},true))
lib.addEventListener("click",()=>openLibrary({title:"Add from the finding library"}))
notes.addEventListener("click",importFromNotes)
search.addEventListener("input",()=>{st.query=search.value;renderList()})
status.addEventListener("change",()=>{st.statusFilter=status.value;renderList()})
sort.addEventListener("click",(e)=>{
const r=sort.getBoundingClientRect()
openContextMenu([
{label:"Sort by severity",fn:()=>sortBy("severity")},
{label:"Sort by CVSS score",fn:()=>sortBy("cvss")},
{label:"Sort by title",fn:()=>sortBy("title")},
{label:"Sort by status",fn:()=>sortBy("status")}
],r.left,r.bottom+4)
e.stopPropagation()
})
}
function renderChips(){
const sum=RC.riskSummary(st.findings)
lp.chips.innerHTML=""
RC.SEVERITIES.forEach((s)=>{
const b=el("button","rpt-sev-chip rpt-sev-"+s.id+(st.sevFilter[s.id]?" active":""))
b.type="button"
b.title="Show only "+s.label.toLowerCase()+" findings"
b.setAttribute("aria-pressed",st.sevFilter[s.id]?"true":"false")
b.innerHTML=`<span class="rpt-sev-dot"></span><span>${esc(s.label)}</span><span class="rpt-sev-n">${sum.counts[s.id]}</span>`
b.addEventListener("click",()=>{st.sevFilter[s.id]=!st.sevFilter[s.id];renderList()})
lp.chips.appendChild(b)
})
}
function renderList(){
if(!st.alive)return
renderChips()
const shown=visible()
const canDrag=!filtersActive()&&st.findings.length>1
const top=lp.rows.scrollTop
lp.rows.innerHTML=""
if(!shown.length){
lp.rows.appendChild(el("div","rpt-empty",st.findings.length?"No findings match the filters.":"No findings yet. Add one, pull one from the library, or import the findings written in your notes."))
}
shown.forEach((f)=>{
const row=el("div","rpt-fi"+(f.id===st.selectedId?" active":""))
row.tabIndex=0
row.dataset.id=String(f.id)
row.setAttribute("role","button")
const grip=el("span","rpt-fi-grip"+(canDrag?"":" disabled"))
grip.title=canDrag?"Drag to reorder (or Alt+Up / Alt+Down)":"Clear the filters to reorder"
grip.innerHTML='<i class="icon icon-grip"></i>'
row.appendChild(grip)
const main=el("div","rpt-fi-main")
const line1=el("div","rpt-fi-line")
line1.appendChild(el("span","rpt-fi-num",number(f.id)))
line1.appendChild(el("span","rpt-fi-title",f.title||"Untitled finding"))
main.appendChild(line1)
const line2=el("div","rpt-fi-meta")
line2.innerHTML=RW.severityBadge(f.severity)+(scoreText(f)?`<span class="rpt-score" title="${esc(CV?CV.findingCvssLabel(f):"CVSS")} base score">${scoreText(f)}</span>`:"")+RW.statusBadge(f.status)+(arr(f.cves).length?`<span class="rpt-lib-cat rpt-fi-cve" title="${esc(arr(f.cves).map((c)=>c.id).join(", "))}">${esc(arr(f.cves)[0].id)}${f.cves.length>1?" +"+(f.cves.length-1):""}</span>`:"")
main.appendChild(line2)
row.appendChild(main)
const menu=iconBtn("dots-vertical","Finding actions","rpt-fi-menu")
row.appendChild(menu)
row.addEventListener("click",(e)=>{if(!e.target.closest(".rpt-fi-menu,.rpt-fi-grip"))selectFinding(f.id)})
row.addEventListener("keydown",(e)=>{
if(e.target!==row)return
if(e.key==="Enter"||e.key===" "){e.preventDefault();selectFinding(f.id)}
else if(e.altKey&&(e.key==="ArrowUp"||e.key==="ArrowDown")&&canDrag){
e.preventDefault()
e.stopPropagation()
const from=indexOf(f.id)
moveFinding(from,from+(e.key==="ArrowUp"?-1:1),true)
}
})
menu.addEventListener("click",(e)=>{
e.stopPropagation()
const r=menu.getBoundingClientRect()
openContextMenu(findingMenu(f),r.left-170,r.bottom+4)
})
row.addEventListener("contextmenu",(e)=>{e.preventDefault();openContextMenu(findingMenu(f),e.clientX,e.clientY)})
if(canDrag)grip.addEventListener("pointerdown",(e)=>startDrag(e,row,grip,f))
lp.rows.appendChild(row)
})
lp.rows.scrollTop=top
const total=st.findings.length
lp.foot.textContent=total?(shown.length===total?total+" finding"+(total===1?"":"s"):shown.length+" of "+total+" shown"):""
}
function findingMenu(f){
return [
{label:"Duplicate",icon:"copy",fn:()=>duplicateFinding(f.id)},
{label:"Save to library\u2026",icon:"save",fn:()=>saveToLibrary(f.id)},
{sep:true},
{label:"Delete",icon:"trash",danger:true,fn:()=>deleteFinding(f.id)}
]
}
// Pointer-based reorder: HTML5 drag and drop is unreliable in WebKitGTK.
function startDrag(e,row,grip,f){
if(e.button!==undefined&&e.button!==0)return
e.preventDefault()
const startY=e.clientY
let moved=false,target=null
const marker=el("div","rpt-fi-drop")
try{grip.setPointerCapture(e.pointerId)}catch(err){}
function rowsNow(){return Array.prototype.slice.call(lp.rows.querySelectorAll(".rpt-fi"))}
function move(ev){
if(!moved&&Math.abs(ev.clientY-startY)<4)return
moved=true
row.classList.add("dragging")
root.classList.add("rpt-dragging")
const box=lp.rows.getBoundingClientRect()
if(ev.clientY<box.top+24)lp.rows.scrollTop-=12
else if(ev.clientY>box.bottom-24)lp.rows.scrollTop+=12
const rows=rowsNow()
let idx=rows.length
for(let i=0;i<rows.length;i++){
const r=rows[i].getBoundingClientRect()
if(ev.clientY<r.top+r.height/2){idx=i;break}
}
target=idx
if(idx>=rows.length)lp.rows.appendChild(marker)
else lp.rows.insertBefore(marker,rows[idx])
}
function done(ev){
grip.removeEventListener("pointermove",move)
grip.removeEventListener("pointerup",done)
grip.removeEventListener("pointercancel",done)
try{grip.releasePointerCapture(e.pointerId)}catch(err){}
marker.remove()
row.classList.remove("dragging")
root.classList.remove("rpt-dragging")
if(!moved||target===null||ev.type==="pointercancel")return
const from=indexOf(f.id)
moveFinding(from,target>from?target-1:target,false)
}
grip.addEventListener("pointermove",move)
grip.addEventListener("pointerup",done)
grip.addEventListener("pointercancel",done)
}
function moveFinding(from,to,keepFocus){
if(from<0||to<0||to>=st.findings.length||from===to)return
const order=st.findings.map((f)=>f.id)
const item=st.findings.splice(from,1)[0]
st.findings.splice(to,0,item)
st.findings.forEach((f,i)=>{f.position=i})
emit({type:"reorder",before:order,after:st.findings.map((f)=>f.id)})
renderList()
syncEditorDerived()
if(keepFocus){const r=lp.rows.querySelector('.rpt-fi[data-id="'+item.id+'"]');if(r)r.focus()}
notify()
call("findings_reorder",[reportId,st.findings.map((f)=>f.id)]).catch(oops("The new order could not be saved."))
}
function sortBy(mode){
flush().then(()=>call("findings_sort",[reportId,mode])).then((list)=>{
if(!Array.isArray(list))return
emit({type:"reorder",before:st.findings.map((f)=>f.id),after:list.map((f)=>f.id)})
st.findings=list
renderList()
syncEditorDerived()
notify()
}).catch(oops("The findings could not be sorted."))
}
function addFinding(fields,focusTitle){
return call("finding_add",[reportId,fields]).then((f)=>{
if(!f||f.id===undefined)throw new Error("The finding was not created.")
st.findings.push(f)
emit({type:"add",finding:clone(f),index:st.findings.length-1})
selectFinding(f.id)
notify()
if(focusTitle&&ed.els.title){ed.els.title.focus();ed.els.title.select()}
const r=lp.rows.querySelector('.rpt-fi[data-id="'+f.id+'"]')
if(r&&r.scrollIntoView)r.scrollIntoView({block:"nearest"})
return f
}).catch((err)=>{RW.toast(RW.errText(err,"The finding could not be added."),true);throw err})
}
function addFromLibrary(libraryId){
return call("finding_from_library",[reportId,libraryId]).then((f)=>{
if(!f||f.id===undefined)throw new Error("The finding was not created.")
st.findings.push(f)
emit({type:"add",finding:clone(f),index:st.findings.length-1})
selectFinding(f.id)
notify()
RW.toast("Added \""+(f.title||"finding")+"\" to the report")
return f
}).catch((err)=>{RW.toast(RW.errText(err,"The library entry could not be added."),true);throw err})
}
function duplicateFinding(id){
const src=byId(id)
if(!src)return
flush().then(()=>{
const fields=pickContent(src)
fields.title=(src.title||"Finding")+" (copy)"
fields.status=src.status||"open"
fields.affected=clone(arr(src.affected))
if(arr(src.targets).length)fields.targets=clone(src.targets)
fields.evidence=clone(arr(src.evidence))
fields.retest_notes=src.retest_notes||""
return addFinding(fields,true)
}).catch(()=>{})
}
function saveToLibrary(id){
const f=byId(id)
if(!f)return
flush().then(()=>call("library_list").catch(()=>[])).then((list)=>{
const cats=Array.from(new Set(arr(list).map((e)=>e.category||"").filter(Boolean))).sort()
return RW.ask({title:"Save to the finding library",okLabel:"Save",fields:[{key:"category",label:"Category",value:"",placeholder:"Web, Network, Active Directory...",list:cats,hint:"Affected assets, evidence and status stay with this report; the reusable text is copied."}]})
}).then((res)=>{
if(!res)return
return call("library_save_from_finding",[id,res.category.trim()]).then(()=>RW.toast("Saved \""+(f.title||"finding")+"\" to the library"))
}).catch(oops("The finding could not be saved to the library."))
}
function deleteFinding(id){
const f=byId(id)
if(!f)return
RW.confirm("Delete \""+(f.title||"Untitled finding")+"\"? It moves to the Recycle Bin.",{danger:true}).then((ok)=>{
if(!ok)return
if(st.timers[id]){clearTimeout(st.timers[id]);delete st.timers[id]}
delete st.pending[id]
const wait=st.chains[id]||Promise.resolve()
return wait.then(()=>call("finding_delete",[id])).then(()=>{
const i=indexOf(id)
if(i>=0){emit({type:"delete",finding:clone(st.findings[i]),index:i});st.findings.splice(i,1)}
delete st.pending[id]
if(st.selectedId===id){
const next=st.findings[Math.min(i,st.findings.length-1)]
st.selectedId=null
if(ed.id===id)dropEditor(true)
selectFinding(next?next.id:null)
}else{renderList();syncEditorDerived()}
setSaveState()
notify()
})
}).catch(oops("The finding could not be deleted."))
}
function importFromNotes(){
const wrap=el("div","rpt-notes-import")
const info=el("div","rpt-ai-note","Findings are read from the finding callouts in your notes. Pick the notes to scan.")
const listEl=el("div","rpt-pick-list")
wrap.appendChild(info)
wrap.appendChild(listEl)
let step=1,notes=[],drafts=[]
const m=RW.modal({title:"Import findings from notes",bodyEl:wrap,wide:true,buttons:[]})
function checkRow(label,sub,checked,right){
const row=el("label","rpt-pick-row")
const cb=el("input")
cb.type="checkbox"
cb.checked=!!checked
row.appendChild(cb)
const text=el("span","rpt-pick-text")
text.appendChild(el("span","rpt-pick-name",label))
if(sub)text.appendChild(el("span","rpt-pick-sub",sub))
row.appendChild(text)
if(right){const r=el("span","rpt-pick-right");r.innerHTML=right;row.appendChild(r)}
listEl.appendChild(row)
return cb
}
function showNotes(){
step=1
listEl.innerHTML=""
info.textContent="Findings are read from the finding callouts in your notes. Pick the notes to scan."
const withF=notes.filter((n)=>(n.findings||0)>0)
if(!withF.length){
listEl.appendChild(el("div","rpt-empty","None of your notes contains a finding callout yet. Write findings in a note with the Finding block, then import them here."))
m.setButtons([{label:"Close"}])
return
}
const boxes=withF.map((n)=>({n:n,cb:checkRow(n.name||"Untitled note",[n.group,arr(n.tags).join(", ")].filter(Boolean).join(" \u00b7 "),true,`<span class="rpt-lib-cat">${Number(n.findings)||0} finding${Number(n.findings)===1?"":"s"}</span>`)}))
m.setButtons([{label:"Cancel"},{label:"Read findings",primary:true,keepOpen:true,onClick:(ctl,btn)=>{
const ids=boxes.filter((b)=>b.cb.checked).map((b)=>b.n.id)
if(!ids.length){RW.toast("Pick at least one note.",true);return false}
btn.disabled=true
call("note_findings",[ids]).then((list)=>{drafts=arr(list);showDrafts()}).catch((err)=>{btn.disabled=false;RW.toast(RW.errText(err,"The notes could not be read."),true)})
return false
}}])
}
function showDrafts(){
step=2
listEl.innerHTML=""
if(!drafts.length){
info.textContent="No findings were found in the selected notes."
m.setButtons([{label:"Back",keepOpen:true,onClick:()=>{showNotes();return false}},{label:"Close"}])
return
}
info.textContent="Choose the findings to add to this report. You can edit them afterwards."
const boxes=drafts.map((d)=>({d:d,cb:checkRow(d.title||"Untitled finding",RC.htmlToText(d.description||"").slice(0,140),true,RW.severityBadge(d.severity)+(typeof d.cvss_score==="number"?`<span class="rpt-score">${d.cvss_score.toFixed(1)}</span>`:""))}))
m.setButtons([{label:"Back",keepOpen:true,left:true,onClick:()=>{showNotes();return false}},{label:"Cancel"},{label:"Add to report",primary:true,keepOpen:true,onClick:(ctl,btn)=>{
const picked=boxes.filter((b)=>b.cb.checked).map((b)=>b.d)
if(!picked.length){RW.toast("Pick at least one finding.",true);return false}
btn.disabled=true
let added=0,firstId=null
picked.reduce((p,d)=>p.then(()=>{
const fields=pickContent(d)
fields.status=d.status||"open"
if(Array.isArray(d.affected))fields.affected=clone(d.affected)
if(Array.isArray(d.evidence))fields.evidence=clone(d.evidence)
fields.source=d.source&&d.source.kind?clone(d.source):{kind:"note",ref:String(d.note_id||"")}
return call("finding_add",[reportId,fields]).then((f)=>{if(f&&f.id!==undefined){st.findings.push(f);emit({type:"add",finding:clone(f),index:st.findings.length-1});added++;if(firstId===null)firstId=f.id}})
}),Promise.resolve()).catch(oops("Some findings could not be added.")).then(()=>{
m.close()
if(added){RW.toast(added+" finding"+(added===1?"":"s")+" added from notes");selectFinding(firstId);notify()}
})
return false
}}])
}
listEl.appendChild(el("div","rpt-empty","Loading notes\u2026"))
call("sources",[report().profile_id||""]).then((src)=>{notes=arr(src&&src.notes);if(step===1)showNotes()}).catch((err)=>{listEl.innerHTML="";listEl.appendChild(el("div","rpt-empty",RW.errText(err,"The notes could not be loaded.")));m.setButtons([{label:"Close"}])})
}

// ---- the CVEs of a finding ----
function flushRich(){Object.keys(ed.riches).forEach((k)=>ed.riches[k].flush())}
// After a merge wrote several fields at once the editor is rebuilt from the finding, keeping its scroll position.
function rebuildEditor(){
const f=byId(ed.id)
if(!f)return
const sc=editPane.querySelector(".rpt-fe-scroll")
const top=sc?sc.scrollTop:0
dropEditor(true)
buildEditor(f)
const sc2=editPane.querySelector(".rpt-fe-scroll")
if(sc2)sc2.scrollTop=top
}
// One patch, so one undo step: the fields the user chose in the merge plus the CVE list.
function writeCves(id,cves,fields){
if(!byId(id))return false
const p=Object.assign({},fields||{},{cves:cves})
patch(id,p)
if(ed.id===id){
if(Object.keys(p).length>1)rebuildEditor()
else if(ed.renderCves)ed.renderCves()
}
return true
}
function fillFromCve(id,incoming,entry,cvesWith){
const f=byId(id)
if(!f||!incoming||!entry)return
const had=arr(f.cves).some((c)=>c.id===entry.id)
cveMerge(f,incoming,entry,(fields)=>{
const now=byId(id)
if(!st.alive||!now)return
const n=Object.keys(fields).length-("cvss_vector" in fields&&"cvss_score" in fields?1:0)
if(writeCves(id,cvesWith?cvesWith(now):CV.addCve(now.cves,entry),fields))RW.toast(n?entry.id+": "+n+" field"+(n===1?"":"s")+" filled":(had?"The finding already has everything "+entry.id+" offers":entry.id+" added"))
})
}
function addCveTo(id){
flushRich()
const f=byId(id)
if(!f||!CV)return
if(arr(f.cves).length>=CV.MAX_CVES){RW.toast("A finding holds at most "+CV.MAX_CVES+" CVEs.",true);return}
cvePicker({title:"Add a CVE to "+number(id),taken:arr(f.cves).map((c)=>c.id),canFill:true,
onPick:(payload)=>fillFromCve(id,CV.incomingFrom(payload),CV.entryFromPayload(payload)),
onManual:(entry,fill)=>{
if(fill)fillFromCve(id,CV.incomingFromEntry(entry),entry)
else if(byId(id)&&writeCves(id,CV.addCve(byId(id).cves,entry)))RW.toast(entry.id+" added")
}}).catch(oops("The CVE picker could not be opened."))
}
function openCve(id,cveId){
flushRich()
const f=byId(id)
const cur=f?arr(f.cves).find((c)=>c.id===cveId):null
if(!cur)return
const swap=(entry)=>(now)=>CV.normList(arr(now.cves).map((c)=>c.id===cveId?entry:c))
cveForm(cur,{taken:arr(f.cves).filter((c)=>c.id!==cveId).map((c)=>c.id),
onSave:(entry)=>{if(byId(id))writeCves(id,swap(entry)(byId(id)))},
onRemove:()=>{if(byId(id))writeCves(id,CV.removeCve(byId(id).cves,cveId))},
onLinks:(entry)=>{
const now=byId(id)
if(!now)return
const refs=CV.withLinks(now.references,entry)
writeCves(id,swap(entry)(now),refs?{references:refs}:{})
RW.toast(refs?"The links of "+entry.id+" were added to the references":"The references already list "+entry.id)
},
onFill:(entry)=>{
const own=()=>fillFromCve(id,CV.incomingFromEntry(entry),entry,swap(entry))
if(entry.source==="manual"){own();return}
// A CVE Intel record also carries impact and the full remediation text; without it the entry's own text is offered.
cveCall("to_finding",[entry.id,null]).then((payload)=>{const inc=payload?CV.incomingFrom(payload):null;if(inc&&inc.id===entry.id)fillFromCve(id,inc,entry,swap(entry));else own()},own)
},
onView:(cid)=>flush().then(()=>cveOpenDetail(cid))})
}
function newFromCve(){
const create=(fields,from)=>{
if(!fields)return
addFinding(fields,false).then(()=>RW.toast("Finding created from "+from)).catch(()=>{})
}
cvePicker({title:"New finding from a CVE",manualLabel:"Create finding",
onPick:(payload)=>{
const fields=CV.findingFrom(payload)
create(fields,fields?fields.source.ref:"")
const note=fields?CV.incomingFrom(payload).cvss_note:""
if(note)RW.toast(note)
},
onManual:(entry)=>create(CV.findingFromEntry(entry),entry.id)
}).catch(oops("The CVE picker could not be opened."))
}

// ---- editor pane ----
function dropEditor(discard){
Object.keys(ed.riches).forEach((k)=>{
if(discard){try{ed.riches[k].setHTML("")}catch(e){}}
ed.riches[k].destroy()
})
if(ed.cvss)ed.cvss.destroy()
ed.id=null
ed.riches={}
ed.cvss=null
ed.els={}
ed.renderCves=null
editPane.innerHTML=""
}
function selectFinding(id){
if(id!==null&&!byId(id))id=null
if(id===null&&st.findings.length)id=st.findings[0].id
st.selectedId=id
renderList()
if(ed.id===id&&id!==null)return
dropEditor(false)
if(id===null){
const empty=el("div","rpt-fw-placeholder")
empty.innerHTML='<i class="icon icon-report"></i><div class="rpt-fw-placeholder-title">No finding selected</div><div>Add a finding to start writing, or pick one from the list.</div>'
editPane.appendChild(empty)
return
}
buildEditor(byId(id))
}
function section(title,cls){
const s=el("section","rpt-sec"+(cls?" "+cls:""))
const head=el("div","rpt-sec-head")
head.appendChild(el("span","rpt-sec-title",title))
s.appendChild(head)
s._head=head
return s
}
function labelled(label,control,cls){
const w=el("label","rpt-field"+(cls?" "+cls:""))
w.appendChild(el("span","rpt-field-label",label))
w.appendChild(control)
return w
}
function textInput(value,placeholder,list){
const i=el("input","rpt-input")
i.type="text"
i.value=value||""
i.spellcheck=false
if(placeholder)i.placeholder=placeholder
if(list)i.setAttribute("list",list)
return i
}
function chipsEditor(getItems,labelOf,onRemove,titleOf){
const box=el("div","rpt-chips")
function render(){
box.innerHTML=""
const items=getItems()
items.forEach((it,i)=>{
const c=el("span","rpt-chip")
c.appendChild(el("span","rpt-chip-text",labelOf(it)))
if(titleOf)c.title=titleOf(it)
const x=el("button","rpt-chip-x")
x.type="button"
x.title="Remove"
x.setAttribute("aria-label","Remove "+labelOf(it))
x.innerHTML='<i class="icon icon-close"></i>'
x.addEventListener("click",()=>onRemove(i))
c.appendChild(x)
box.appendChild(c)
})
box.classList.toggle("empty",!items.length)
}
render()
return {el:box,render:render}
}
function pickTargets(f,onPicked){
const wrap=el("div","rpt-notes-import")
const tools=el("div","rpt-lib-tools")
const search=textInput("","Filter targets")
const profile=selectEl([["","Active profile"]],"")
tools.appendChild(search)
tools.appendChild(profile)
wrap.appendChild(tools)
const listEl=el("div","rpt-pick-list")
wrap.appendChild(listEl)
let rows=[],targets=[],profilesLoaded=false
const picked={}
function render(){
const q=search.value.trim().toLowerCase()
listEl.innerHTML=""
rows=[]
const have=new Set(arr(f.affected).map((a)=>(a.target_id||"")+"|"+(a.value||"")))
let shown=0
targets.forEach((t)=>{
// Passwords, hashes, tokens and account names of a target are never offered as an "affected asset".
const vals=t.values&&typeof t.values==="object"?Object.keys(t.values).filter((k)=>!SECRET_KEY_RX.test(k)&&String(t.values[k]===null||t.values[k]===undefined?"":t.values[k]).trim()):[]
// Addresses first (they are what a report lists); the bare target name is always offered.
const rank=(k)=>/ip|url|domain|host|fqdn|address/i.test(k)?0:1
vals.sort((a,b)=>rank(a)-rank(b))
const entries=[{target_id:String(t.id),name:t.name||"",value:"",key:"Target name only"}].concat(vals.map((k)=>({target_id:String(t.id),name:t.name||"",value:String(t.values[k]),key:k})))
const match=entries.filter((en)=>!q||(en.name+" "+en.key+" "+en.value).toLowerCase().indexOf(q)>=0)
if(!match.length)return
shown++
const group=el("div","rpt-pick-group")
group.appendChild(el("div","rpt-pick-group-title",t.name||"Unnamed target"))
match.forEach((en)=>{
const id=en.target_id+"|"+en.value
const row=el("label","rpt-pick-row")
const cb=el("input")
cb.type="checkbox"
cb.checked=!!picked[id]
cb.disabled=have.has(id)
cb.addEventListener("change",()=>{if(cb.checked)picked[id]=en;else delete picked[id]})
row.appendChild(cb)
const text=el("span","rpt-pick-text")
text.appendChild(el("span","rpt-pick-name rpt-mono",en.value||en.name))
if(en.key)text.appendChild(el("span","rpt-pick-sub",en.key))
row.appendChild(text)
if(cb.disabled){const r=el("span","rpt-pick-right");r.textContent="Already added";row.appendChild(r)}
group.appendChild(row)
})
listEl.appendChild(group)
})
if(!shown)listEl.appendChild(el("div","rpt-empty",targets.length?"No targets match.":"This profile has no targets. Add them on the Targets page, or type an asset by hand."))
}
function load(profileId){
listEl.innerHTML=""
listEl.appendChild(el("div","rpt-empty","Loading targets\u2026"))
call("sources",[profileId||""]).then((src)=>{
targets=arr(src&&src.targets)
if(!profilesLoaded){
profilesLoaded=true
profile.innerHTML=""
const profs=arr(src&&src.profiles)
if(!profs.length){const op=el("option",null,"No profiles");op.value="";profile.appendChild(op)}
profs.forEach((p)=>{const op=el("option",null,(p.name||"Profile")+(p.active?" (active)":""));op.value=String(p.id);profile.appendChild(op)})
const want=profileId||((profs.find((p)=>p.active)||{}).id)
if(want!==undefined&&want!==null)profile.value=String(want)
}
render()
}).catch((err)=>{listEl.innerHTML="";listEl.appendChild(el("div","rpt-empty",RW.errText(err,"The targets could not be loaded.")))})
}
search.addEventListener("input",render)
profile.addEventListener("change",()=>load(profile.value))
RW.modal({title:"Add affected assets from targets",bodyEl:wrap,wide:true,buttons:[
{label:"Cancel"},
{label:"Add selected",primary:true,onClick:()=>{
const list=Object.keys(picked).map((k)=>({target_id:picked[k].target_id,name:picked[k].name,value:picked[k].value}))
if(list.length)onPicked(list)
}}
]})
load(report().profile_id||"")
setTimeout(()=>search.focus(),30)
}
const evTitleCache={}
function evidenceTitle(uid){
if(!evTitleCache[uid])evTitleCache[uid]=bridgeCall("evidence.get",[uid]).then((ev)=>ev?{title:RC.evidenceCaption(ev),kind:ev.kind||"",asset:(ev.meta&&ev.meta.asset_uid)||""}:null).catch(()=>{delete evTitleCache[uid];return null})
return evTitleCache[uid]
}
function buildEditor(f){
const id=f.id
ed.id=id
const E=ed.els
const AI=!!window.ReportAI
const wrap=el("div","rpt-fe")
// Header
const head=el("div","rpt-fe-head")
E.num=el("span","rpt-fe-num",number(id))
E.title=el("input","rpt-input rpt-fe-title")
E.title.type="text"
E.title.value=f.title||""
E.title.placeholder="Finding title"
E.title.spellcheck=true
E.save=el("button","rpt-save-state","Saved")
E.save.type="button"
const menu=iconBtn("dots-vertical","Finding actions")
head.appendChild(E.num)
head.appendChild(E.title)
head.appendChild(E.save)
head.appendChild(menu)
wrap.appendChild(head)
E.title.addEventListener("input",()=>patch(id,{title:E.title.value}))
E.save.addEventListener("click",()=>{if(st.failed){st.failed=false;flush()}})
menu.addEventListener("click",(e)=>{e.stopPropagation();const r=menu.getBoundingClientRect();openContextMenu(findingMenu(f),r.right-210,r.bottom+4)})
const scroll=el("div","rpt-fe-scroll")
wrap.appendChild(scroll)

// Classification
const cls=section("Classification")
const grid=el("div","rpt-fe-grid")
E.severity=selectEl(RC.SEVERITIES.map((s)=>[s.id,s.label]),f.severity||"info")
const sevWrap=labelled("Severity",E.severity)
E.useCvss=el("button","rpt-link hidden")
E.useCvss.type="button"
sevWrap.appendChild(E.useCvss)
grid.appendChild(sevWrap)
E.status=selectEl(RC.STATUSES.map((s)=>[s.id,s.label]),f.status||"open")
grid.appendChild(labelled("Status",E.status))
E.likelihood=selectEl(RC.LIKELIHOODS.map((s)=>[s.id,s.label]),f.likelihood||"")
grid.appendChild(labelled("Likelihood",E.likelihood))
datalist("rptCweList",RC.COMMON_CWES)
datalist("rptOwaspList",RC.OWASP_TOP10.map((o)=>[o]))
E.cwe=textInput(f.cwe,"CWE-79","rptCweList")
grid.appendChild(labelled("CWE",E.cwe))
E.owasp=textInput(f.owasp,"A03:2021 Injection","rptOwaspList")
grid.appendChild(labelled("OWASP Top 10",E.owasp,"rpt-field-wide"))
cls.appendChild(grid)
if(CV){
const cveField=el("div","rpt-field rpt-cve-field")
cveField.appendChild(el("span","rpt-field-label","CVEs"))
const cveRow=el("div","rpt-cve-chips")
cveField.appendChild(cveRow)
const cveAdd=textBtn("Add CVE\u2026","rpt-btn-small","Pick a CVE from CVE Intel or enter one by hand; you choose what it fills in","add")
cveAdd.addEventListener("click",()=>addCveTo(id))
ed.renderCves=()=>{
cveRow.innerHTML=""
arr(f.cves).forEach((c)=>{
const chip=el("span","rpt-chip rpt-cve-chip rpt-sev-"+(CV.sev(c.severity)||"info"))
const open=el("button","rpt-cve-chip-main")
open.type="button"
open.title=CV.chipTitle(c)||c.id
open.appendChild(el("span","rpt-sev-dot"))
open.appendChild(el("span","rpt-cve-chip-id",c.id))
if(CV.score(c.cvss_score)!==null)open.appendChild(el("span","rpt-cve-chip-score",CV.score(c.cvss_score).toFixed(1)))
if(c.kev===true)open.appendChild(el("span","rpt-kev","Known exploited"))
open.addEventListener("click",()=>openCve(id,c.id))
chip.appendChild(open)
const x=el("button","rpt-chip-x")
x.type="button"
x.title="Remove "+c.id+" from this finding"
x.setAttribute("aria-label","Remove "+c.id)
x.innerHTML='<i class="icon icon-close"></i>'
x.addEventListener("click",()=>writeCves(id,CV.removeCve(f.cves,c.id)))
chip.appendChild(x)
cveRow.appendChild(chip)
})
cveRow.appendChild(cveAdd)
}
ed.renderCves()
cls.appendChild(cveField)
}
scroll.appendChild(cls)
E.severity.addEventListener("change",()=>{patch(id,{severity:E.severity.value});syncEditorDerived()})
E.status.addEventListener("change",()=>{patch(id,{status:E.status.value});syncEditorDerived()})
E.likelihood.addEventListener("change",()=>patch(id,{likelihood:E.likelihood.value}))
E.cwe.addEventListener("input",()=>patch(id,{cwe:E.cwe.value.trim()}))
E.cwe.addEventListener("change",()=>{
const m=/^(?:cwe[-\s]?)?(\d{1,5})$/i.exec(E.cwe.value.trim())
if(m){E.cwe.value="CWE-"+m[1];patch(id,{cwe:E.cwe.value})}
})
E.owasp.addEventListener("input",()=>patch(id,{owasp:E.owasp.value.trim()}))
E.useCvss.addEventListener("click",()=>{
const sc=RC.cvssScore(f.cvss_vector)
if(sc===null)return
E.severity.value=RC.sevFromScore(sc)
patch(id,{severity:E.severity.value})
syncEditorDerived()
})

// CVSS (collapsible)
const cv=section("CVSS 3.1","rpt-sec-collapsible")
E.cvssSummary=el("span","rpt-cvss-summary")
cv._head.appendChild(E.cvssSummary)
const cvToggle=el("button","rpt-link",f.cvss_vector?"Show calculator":"Hide calculator")
cvToggle.type="button"
cv._head.appendChild(cvToggle)
if(AI){
const b=textBtn("Suggest CVSS","rpt-btn-small rpt-btn-ai","Ask the AI for a CVSS vector; you review it before anything changes","brain")
b.addEventListener("click",()=>flush().then(()=>aiRun("suggest_cvss",{reportId:reportId,findingId:id},"Suggested CVSS vector",(res)=>{
if(!res.vector||ed.id!==id)return
ed.cvss.setVector(res.vector)
patch(id,{cvss_vector:RC.cvssBuild(RC.cvssParse(res.vector).metrics),cvss_score:RC.cvssScore(res.vector)})
syncEditorDerived()
},b)))
cv._head.appendChild(b)
}
const cvBody=el("div","rpt-sec-body"+(f.cvss_vector?" hidden":""))
cv.appendChild(cvBody)
ed.cvss=RW.cvssCalculator(cvBody,{vector:f.cvss_vector||"",onChange:(v)=>{
patch(id,{cvss_vector:v.vector,cvss_score:v.vector?v.score:null})
syncEditorDerived()
}})
cvToggle.addEventListener("click",()=>{
const hide=!cvBody.classList.contains("hidden")
cvBody.classList.toggle("hidden",hide)
cvToggle.textContent=hide?"Show calculator":"Hide calculator"
})
scroll.appendChild(cv)

// Affected assets
const af=section("Affected assets")
// Linked targets of the report come first: a finding points at the link and names the values to print.
const T=window.ReportTargets&&typeof window.ReportTargets.pickForFinding==="function"?window.ReportTargets:null
const tgChips=el("div","rpt-chips rpt-chips-targets")
function renderTargets(){
tgChips.innerHTML=""
const links=arr(report().targets)
const list=T?T.normFindingTargets(f.targets,links):[]
list.forEach((t)=>{
const link=links.find((l)=>l.uid===t.uid)
const c=el("span","rpt-chip rpt-chip-target")
const label=T.affectedLabel(link,t.keys)
const ic=el("span","rpt-chip-target-icon")
ic.innerHTML='<i class="icon icon-target"></i>'
c.appendChild(ic)
const text=el("span","rpt-chip-text",label)
text.title="Linked target"+(link.state==="removed"?" (removed from the Targets page; the report keeps its snapshot)":link.state==="changed"?" (changed on the Targets page; update it in Details \u203a Scope)":"")+". Click to choose the values shown."
text.addEventListener("click",pickLinked)
c.appendChild(text)
const x=el("button","rpt-chip-x")
x.type="button"
x.title="Remove"
x.setAttribute("aria-label","Remove "+label)
x.innerHTML='<i class="icon icon-close"></i>'
x.addEventListener("click",()=>{patch(id,{targets:list.filter((o)=>o.uid!==t.uid)});renderTargets()})
c.appendChild(x)
tgChips.appendChild(c)
})
tgChips.classList.toggle("empty",!list.length)
}
function pickLinked(){
T.pickForFinding(report(),f.targets).then((res)=>{
if(!res||ed.id!==id)return
if(JSON.stringify(res)!==JSON.stringify(T.normFindingTargets(f.targets,arr(report().targets))))patch(id,{targets:res})
renderTargets()
}).catch(oops("The linked targets could not be shown."))
}
ed.renderTargets=renderTargets
renderTargets()
af.appendChild(tgChips)
const afChips=chipsEditor(()=>arr(f.affected),(a)=>a.value?(a.name?a.name+": "+a.value:a.value):(a.name||"Asset"),(i)=>{
const next=arr(f.affected).slice()
next.splice(i,1)
patch(id,{affected:next})
afChips.render()
},(a)=>a.target_id?"Linked to a target":"Typed by hand")
af.appendChild(afChips.el)
const afRow=el("div","rpt-inline-row")
const afInput=textInput("","Host, URL or component")
const afAdd=textBtn("Add","rpt-btn-small","Add the typed asset")
const afPick=textBtn("Add from targets\u2026","rpt-btn-small","Copy a name or address from the Targets page as text","target")
afRow.appendChild(afInput)
afRow.appendChild(afAdd)
if(T){
const afLinked=textBtn("Linked targets\u2026","rpt-btn-small","Choose which of the report\u2019s linked targets this finding affects, and the values to show","crosshair")
afLinked.addEventListener("click",pickLinked)
afRow.appendChild(afLinked)
}
afRow.appendChild(afPick)
af.appendChild(afRow)
function addTyped(){
const v=afInput.value.trim()
if(!v)return
if(!arr(f.affected).some((a)=>!a.target_id&&a.name===v))patch(id,{affected:arr(f.affected).concat([{target_id:"",name:v,value:""}])})
afInput.value=""
afChips.render()
}
afAdd.addEventListener("click",addTyped)
afInput.addEventListener("keydown",(e)=>{if(e.key==="Enter"){e.preventDefault();addTyped()}})
afPick.addEventListener("click",()=>pickTargets(f,(list)=>{
if(ed.id!==id)return
patch(id,{affected:arr(f.affected).concat(list)})
afChips.render()
}))
scroll.appendChild(af)

// Rich fields
RICH_FIELDS.forEach((rf)=>{
const s=section(rf.label,"rpt-sec-rich")
if(AI){
const b=textBtn("Rewrite professionally","rpt-btn-small rpt-btn-ai","Ask the AI to rewrite this text; you review it before anything changes","brain")
b.addEventListener("click",()=>{
const text=ed.riches[rf.key].getHTML()
if(!text){RW.toast("Write something first.");return}
flush().then(()=>aiRun("rewrite_finding",{reportId:reportId,findingId:id,field:rf.key,text:text},"Rewritten "+rf.label.toLowerCase(),(res)=>{
if(!res.html||ed.id!==id)return
ed.riches[rf.key].setHTML(res.html)
patch(id,{[rf.key]:ed.riches[rf.key].getHTML()})
},b))
})
s._head.appendChild(b)
if(rf.key==="remediation"){
const b2=textBtn("Suggest remediation","rpt-btn-small rpt-btn-ai","Ask the AI for remediation advice; you review it before anything changes","brain")
b2.addEventListener("click",()=>flush().then(()=>aiRun("suggest_remediation",{reportId:reportId,findingId:id},"Suggested remediation",(res)=>{
if(!res.html||ed.id!==id)return
ed.riches.remediation.setHTML(res.html)
patch(id,{remediation:ed.riches.remediation.getHTML()})
},b2)))
s._head.appendChild(b2)
}
}
ed.riches[rf.key]=ReportRich.create(s,{html:f[rf.key]||"",placeholder:rf.placeholder,compact:true,minHeight:rf.key==="description"||rf.key==="steps"?110:80,onChange:(html)=>{if(byId(id)&&html!==(f[rf.key]||""))patch(id,{[rf.key]:html})}})
scroll.appendChild(s)
})

// References
const rs=section("References")
const refList=el("div","rpt-ref-list")
rs.appendChild(refList)
const refAdd=textBtn("Add reference","rpt-btn-small","Add a URL (advisory, CVE, vendor documentation)","add")
rs.appendChild(refAdd)
let refsUi=arr(f.references).slice()
function saveRefs(){patch(id,{references:refsUi.filter(Boolean)})}
function renderRefs(focusLast){
refList.innerHTML=""
refsUi.forEach((r,i)=>{
const row=el("div","rpt-ref-row")
const input=textInput(r,"https://")
input.classList.toggle("invalid",!!r&&!/^https?:\/\/\S+$/i.test(r))
input.addEventListener("input",()=>{
refsUi[i]=input.value.trim()
input.classList.toggle("invalid",!!refsUi[i]&&!/^https?:\/\/\S+$/i.test(refsUi[i]))
saveRefs()
})
input.addEventListener("keydown",(e)=>{if(e.key==="Enter"){e.preventDefault();refAdd.click()}})
const x=iconBtn("close","Remove reference","rpt-icon-small")
x.addEventListener("click",()=>{
const had=!!refsUi[i]
refsUi.splice(i,1)
if(had)saveRefs()
renderRefs(false)
})
row.appendChild(input)
row.appendChild(x)
refList.appendChild(row)
})
if(focusLast&&refList.lastChild)refList.lastChild.querySelector("input").focus()
}
refAdd.addEventListener("click",()=>{
if(refsUi.some((r)=>!r)){const blank=refList.children[refsUi.findIndex((r)=>!r)];if(blank)blank.querySelector("input").focus();return}
refsUi.push("")
renderRefs(true)
})
renderRefs(false)
scroll.appendChild(rs)

// Evidence attachments
const es=section("Evidence")
const evList=el("div","rpt-ev-list")
es.appendChild(evList)
const evRow=el("div","rpt-inline-row")
const evPick=textBtn("Attach evidence\u2026","rpt-btn-small","Attach captured command output, recordings or screenshots","command-line")
const evUpload=textBtn("Upload image\u2026","rpt-btn-small","Attach a screenshot from a file","image")
evRow.appendChild(evPick)
evRow.appendChild(evUpload)
es.appendChild(evRow)
function renderEvidence(){
evList.innerHTML=""
arr(f.evidence).forEach((it,i)=>{
const row=el("div","rpt-ev-row")
const thumb=el("div","rpt-ev-thumb")
const info=el("div","rpt-ev-info")
const name=el("div","rpt-ev-name",it.asset_uid?"Image":"Evidence")
const cap=textInput(it.caption,"Caption shown in the report")
info.appendChild(name)
info.appendChild(cap)
function showImg(uid){
ReportRich.assetUrl(uid).then((url)=>{if(url){const img=el("img");img.src=url;img.alt="";thumb.innerHTML="";thumb.appendChild(img)}})
}
if(it.asset_uid){thumb.innerHTML='<i class="icon icon-image"></i>';showImg(it.asset_uid)}
else{
thumb.innerHTML='<i class="icon icon-command-line"></i>'
evidenceTitle(it.evidence_uid).then((info2)=>{
if(!info2){name.textContent="Evidence "+it.evidence_uid;return}
name.textContent=info2.title
if(info2.kind==="image"&&info2.asset){thumb.innerHTML='<i class="icon icon-image"></i>';showImg(info2.asset)}
})
}
cap.addEventListener("input",()=>{
const next=clone(arr(f.evidence))
next[i].caption=cap.value
patch(id,{evidence:next})
})
const x=iconBtn("close","Remove attachment","rpt-icon-small")
x.addEventListener("click",()=>{
const next=clone(arr(f.evidence))
next.splice(i,1)
patch(id,{evidence:next})
renderEvidence()
})
row.appendChild(thumb)
row.appendChild(info)
row.appendChild(x)
evList.appendChild(row)
})
if(!arr(f.evidence).length)evList.appendChild(el("div","rpt-empty rpt-empty-small","No evidence attached. Attachments are printed under the finding in the report."))
}
evPick.classList.toggle("hidden",!(window.ReportEvidence&&typeof window.ReportEvidence.pick==="function"))
E.evPick=evPick
evPick.addEventListener("click",()=>{
Promise.resolve(window.ReportEvidence.pick({multiple:true})).then((list)=>{
if(ed.id!==id||!list||!list.length)return
const have=new Set(arr(f.evidence).map((e)=>e.evidence_uid).filter(Boolean))
const add=list.filter((ev)=>ev&&ev.uid&&!have.has(ev.uid)).map((ev)=>({evidence_uid:ev.uid,asset_uid:"",caption:ev.title||RC.evidenceCaption(ev)}))
if(!add.length)return
patch(id,{evidence:arr(f.evidence).concat(add)})
renderEvidence()
}).catch(oops("Evidence could not be attached."))
})
evUpload.addEventListener("click",()=>ReportRich.pickImages(true).then((list)=>{
if(ed.id!==id||!list.length)return
patch(id,{evidence:arr(f.evidence).concat(list.map((it)=>({evidence_uid:"",asset_uid:it.asset.uid,caption:(it.asset.name||"").replace(/\.[a-z0-9]+$/i,"")})))})
renderEvidence()
}))
renderEvidence()
scroll.appendChild(es)

// Tags
const ts=section("Tags")
const tagChips=chipsEditor(()=>arr(f.tags),(t)=>t,(i)=>{
const next=arr(f.tags).slice()
next.splice(i,1)
patch(id,{tags:next})
tagChips.render()
})
ts.appendChild(tagChips.el)
const tagInput=textInput("","Add a tag and press Enter")
tagInput.classList.add("rpt-input-short")
ts.appendChild(tagInput)
function addTags(){
const parts=tagInput.value.split(",").map((s)=>s.trim()).filter(Boolean)
if(!parts.length)return
const next=arr(f.tags).slice()
parts.forEach((p)=>{if(next.indexOf(p)<0)next.push(p)})
patch(id,{tags:next})
tagInput.value=""
tagChips.render()
}
tagInput.addEventListener("keydown",(e)=>{if(e.key==="Enter"||e.key===","){e.preventDefault();addTags()}})
tagInput.addEventListener("blur",addTags)
scroll.appendChild(ts)

// Retest notes (only relevant once the finding went back for a retest or was fixed)
E.retestSec=section("Retest notes")
E.retest=el("textarea","rpt-input rpt-textarea")
E.retest.rows=4
E.retest.placeholder="What was retested, when, and the result."
E.retest.value=f.retest_notes||""
E.retest.addEventListener("input",()=>patch(id,{retest_notes:E.retest.value}))
E.retestSec.appendChild(E.retest)
scroll.appendChild(E.retestSec)

E.meta=el("div","rpt-fe-meta")
scroll.appendChild(E.meta)
editPane.appendChild(wrap)
syncEditorDerived()
setSaveState()
}
// Everything in the editor that is derived from the finding and is never a focused input.
function syncEditorDerived(){
const f=byId(ed.id)
const E=ed.els
if(!f||!E.num)return
E.num.textContent=number(f.id)
const sc=RC.cvssScore(f.cvss_vector)
if(sc===null){
// A score without a vector comes from a CVE that is only rated in CVSS 4.0 (or from imported data).
const bare=!f.cvss_vector&&typeof f.cvss_score==="number"&&isFinite(f.cvss_score)
const ver=bare&&CV?CV.findingCvssVersion(f):""
const from=ver?arr(f.cves).find((c)=>c&&c.cvss_version===ver&&c.cvss_score===f.cvss_score):null
E.cvssSummary.innerHTML=bare?`<span class="rpt-cvss-pill" data-sev="${RC.sevFromScore(f.cvss_score)}">${f.cvss_score.toFixed(1)}</span><span class="rpt-muted rpt-cvss-version" title="${esc(from&&from.cvss_vector?from.cvss_vector:"")}">${ver?esc("CVSS "+ver+(from?" score of "+from.id:"")+" (read-only; set a vector below to rate it in CVSS 3.1)"):"Score without a CVSS 3.1 vector"}</span>`:'<span class="rpt-muted">Not scored</span>'
E.useCvss.classList.add("hidden")
}else{
const sev=RC.sevFromScore(sc)
E.cvssSummary.innerHTML=`<span class="rpt-cvss-pill" data-sev="${sev}">${sc.toFixed(1)}</span><span class="rpt-cvss-summary-vec">${esc(f.cvss_vector)}</span>`
E.useCvss.textContent="Use CVSS severity ("+RC.sevLabel(sev)+")"
E.useCvss.classList.toggle("hidden",sev===f.severity)
}
E.retestSec.classList.toggle("hidden",!(f.status==="retest"||f.status==="fixed"))
const src=f.source&&f.source.kind?"Source: "+f.source.kind+(f.source.ref?" ("+f.source.ref+")":""):""
E.meta.textContent=[src,f.created_at?"Created "+RC.fmtDate(f.created_at):"",f.updated_at?"Updated "+RC.fmtDate(f.updated_at):""].filter(Boolean).join(" \u00b7 ")
}
function refresh(findings){
if(!st.alive)return
const incoming=Array.isArray(findings)?findings:arr(report().findings)
// Local edits that are still on their way to the server win over the incoming copy.
st.findings=incoming.map((f)=>{
const p=st.pending[f.id]
return p?Object.assign({},f,clone(p)):clone(f)
})
const sel=byId(st.selectedId)
if(!sel){
st.selectedId=null
if(ed.id!==null)dropEditor(true)
selectFinding(null)
return
}
const busy=editPane.contains(document.activeElement)||isDirty()
if(!busy){dropEditor(true);buildEditor(sel)}
else syncEditorDerived()
renderList()
}
// Replace everything with the given findings (after the page applied an undo / redo on the server): nothing local is kept.
function reload(findings,selectId){
if(!st.alive)return
Object.keys(st.timers).forEach((k)=>clearTimeout(st.timers[k]))
st.timers={}
st.pending={}
st.findings=arr(findings).map(clone)
if(ed.id!==null)dropEditor(true)
st.selectedId=null
selectFinding(selectId!==undefined&&selectId!==null&&byId(selectId)?selectId:null)
setSaveState()
}
function onPageShown(){
if(!st.alive)return
const AI=!!window.ReportAI
const hasAI=!!editPane.querySelector(".rpt-btn-ai")
if(ed.els.evPick)ed.els.evPick.classList.toggle("hidden",!(window.ReportEvidence&&typeof window.ReportEvidence.pick==="function"))
// AI buttons are built with the editor; rebuild it when availability flipped and nothing is being typed.
if(AI!==hasAI&&ed.id!==null&&!editPane.contains(document.activeElement)){
const f=byId(ed.id)
flush().then(()=>{if(st.alive&&f&&ed.id===f.id){dropEditor(false);buildEditor(f)}})
}
}
function destroy(){
if(!st.alive)return
flush()
st.alive=false
document.removeEventListener("loya:page-shown",onPageShown)
Object.keys(ed.riches).forEach((k)=>ed.riches[k].destroy())
if(ed.cvss)ed.cvss.destroy()
root.remove()
if(current===api)current=null
}
const api={
refresh:refresh,
reload:reload,
flush:flush,
isDirty:isDirty,
destroy:destroy,
openFinding:(id)=>{
selectFinding(id)
const r=lp.rows.querySelector('.rpt-fi[data-id="'+id+'"]')
if(r&&r.scrollIntoView)r.scrollIntoView({block:"nearest"})
},
addFromLibrary:addFromLibrary,
alive:()=>st.alive&&root.isConnected,
el:root
}
document.addEventListener("loya:page-shown",onPageShown)
buildList()
st.findings=arr(report().findings).map(clone)
selectFinding(null)
current=api
return api
}
return {mount:mount,openLibrary:openLibrary}
})()
if(typeof window!=="undefined")window.ReportFindings=ReportFindings
