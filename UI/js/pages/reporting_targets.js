// Reporting: targets linked to a report as its scope (optional). A link is a snapshot of a target of the Targets page; the pure helpers
// at the top also run under Node for tests, the rest is the scope block of the Details pane and the pickers the editors use.
var ReportTargets=(function(){
// Keys that name a credential or an account (same rule as reports_service._TARGET_SECRET_KEY_RE). Their values stay on the Targets
// page unless the user allows that key for that link after a warning.
const SECRET_KEY_RX=/pass|pwd|secret|token|hash|key|cred|cookie|session|private|otp|pin|user|login/i
const ADDRESS_KEY_RX=/ip|url|uri|domain|host|fqdn|address|cidr|subnet|network|range/i
const KEY_RX=/^@?[^\u0000-\u001f\u007f"'<>&{}\\`$,;=|()*]{1,80}$/
const UID_RX=/^[A-Za-z0-9_\-]{1,64}$/
const STATUS_LABELS={not_started:"Not started",in_progress:"In progress",compromised:"Compromised",reported:"Reported"}
const WITHHELD="[withheld]"
const MAX_COLUMNS=12
const RICH_FIELDS=["description","impact","steps","remediation"]
function arr(v){return Array.isArray(v)?v:[]}
function str(v){return v===undefined||v===null?"":String(v)}
function esc(s){return str(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")}
function isSecretKey(k){return SECRET_KEY_RX.test(str(k))}
function lower(list){return arr(list).map((k)=>str(k).toLowerCase())}
// What a link may hold of a target's values: everything that is not protected, plus the protected keys allowed on this link.
function publicValues(values,allowed){
const allow=lower(allowed),out={}
Object.keys(values&&typeof values==="object"?values:{}).forEach((k)=>{
const v=str(values[k]).trim()
if(!k||!v)return
if(isSecretKey(k)&&allow.indexOf(k.toLowerCase())<0)return
out[k]=v
})
return out
}
function secretNames(values,allowed){
const allow=lower(allowed)
return Object.keys(values&&typeof values==="object"?values:{}).filter((k)=>str(values[k]).trim()&&isSecretKey(k)&&allow.indexOf(k.toLowerCase())<0)
}
function statusOf(v){return Object.prototype.hasOwnProperty.call(STATUS_LABELS,str(v))?str(v):"not_started"}
function statusLabel(v){return STATUS_LABELS[statusOf(v)]}
function snapshotOf(link){
const s=link&&link.snapshot&&typeof link.snapshot==="object"?link.snapshot:{}
return {values:publicValues(s.values,link&&link.allowed_secret_keys),engagement_status:statusOf(s.engagement_status)}
}
// {state:"ok"|"changed"|"removed",changed:[keys]} of a link against the live target ({name,values,engagement_status} or null).
function linkState(link,target){
if(!target)return {state:"removed",changed:[]}
const a=snapshotOf(link).values,b=publicValues(target.values,link.allowed_secret_keys)
const changed=[]
if(str(target.name)!==str(link.name))changed.push("@name")
if(statusOf(target.engagement_status)!==snapshotOf(link).engagement_status)changed.push("@status")
const keys={}
Object.keys(a).concat(Object.keys(b)).forEach((k)=>{keys[k]=1})
Object.keys(keys).sort().forEach((k)=>{if(a[k]!==b[k])changed.push(k)})
return {state:changed.length?"changed":"ok",changed:changed}
}
// The text a reference shows: a value key, "@name" or "@status"; null when the link does not hold it.
function valueOf(link,key){
if(!link)return null
key=str(key)
if(key==="@name")return str(link.name)
const snap=snapshotOf(link)
if(key==="@status")return statusLabel(snap.engagement_status)
const hit=Object.keys(snap.values).find((k)=>k===key)||Object.keys(snap.values).find((k)=>k.toLowerCase()===key.toLowerCase())
return hit===undefined?null:snap.values[hit]
}
function keyLabel(key){return key==="@name"?"Target name":key==="@status"?"Engagement status":str(key)}
function byUid(links){
const out={}
arr(links).forEach((l)=>{if(l&&l.uid)out[l.uid]=l})
return out
}
// The stored text of every reference in sanitised HTML, rewritten from the link snapshots (what the server does on save and export).
function resolveHtml(html,links){
html=str(html)
if(html.indexOf("rpt-tv")<0)return html
const by=byUid(links)
return html.replace(/(<span class="rpt-tv" data-target="([A-Za-z0-9_\-]{1,64})" data-key="([^"<>]{1,480})">)([^<]*)<\/span>/g,(all,open,uid,rawKey,text)=>{
const key=rawKey.replace(/&quot;/g,"\"").replace(/&#39;|&#x27;/g,"'").replace(/&lt;/g,"<").replace(/&gt;/g,">").replace(/&amp;/g,"&")
const v=valueOf(by[uid],key)
return open+(v===null?(isSecretKey(key)?esc(WITHHELD):text):esc(v).replace(/&quot;/g,"\"").replace(/&#39;/g,"'"))+"</span>"
})
}
function chipHtml(uid,key,value){
if(!UID_RX.test(str(uid))||!KEY_RX.test(str(key)))return esc(value)
return "<span class=\"rpt-tv\" data-target=\""+uid+"\" data-key=\""+esc(key)+"\">"+esc(value)+"</span>"
}
function allKeys(links){
const keys=[]
arr(links).forEach((l)=>{Object.keys(snapshotOf(l).values).forEach((k)=>{if(keys.indexOf(k)<0)keys.push(k)})})
return keys
}
// Columns of the generated scope table: the user's choice, else the address-like keys of the linked targets plus the status
// (same rule as report_export.scope_columns).
function scopeColumns(links,chosen){
if(Array.isArray(chosen)){
const cols=[]
chosen.forEach((k)=>{k=str(k).trim();if(k&&k!=="@name"&&cols.indexOf(k)<0)cols.push(k)})
return cols.slice(0,MAX_COLUMNS)
}
const keys=allKeys(links).filter((k)=>!isSecretKey(k))
const addr=keys.filter((k)=>ADDRESS_KEY_RX.test(k))
return (addr.length?addr:keys).slice(0,3).concat(["@status"])
}
// "name (v1, v2)" of a finding's linked target, as the exports print it.
function affectedLabel(link,keys){
if(!link)return ""
const vals=[]
arr(keys).forEach((k)=>{const v=k==="@name"?null:valueOf(link,k);if(v&&vals.indexOf(v)<0)vals.push(v)})
return str(link.name)+(vals.length?" ("+vals.join(", ")+")":"")
}
function normFindingTargets(list,links){
const by=byUid(links),out=[],seen={}
arr(list).forEach((e)=>{
if(typeof e==="string")e={uid:e}
if(!e||!by[e.uid]||seen[e.uid])return
seen[e.uid]=1
const keys=[]
arr(e.keys).forEach((k)=>{k=str(k);if(KEY_RX.test(k)&&keys.indexOf(k)<0)keys.push(k)})
out.push({uid:e.uid,keys:keys})
})
return out
}
function stateLabel(link){return link.state==="removed"?"target removed":link.state==="changed"?"changed":""}
function linkSummary(link){
const snap=snapshotOf(link)
const lines=Object.keys(snap.values).map((k)=>k+": "+snap.values[k])
lines.push("Engagement status: "+statusLabel(snap.engagement_status))
if(link.state==="changed")lines.push("Changed on the Targets page: "+arr(link.changed_keys).map(keyLabel).join(", "))
if(link.state==="removed")lines.push("The target was removed from the Targets page; the report keeps this snapshot.")
return lines.join("\n")
}
const core={SECRET_KEY_RX:SECRET_KEY_RX,KEY_RX:KEY_RX,STATUS_LABELS:STATUS_LABELS,WITHHELD:WITHHELD,isSecretKey:isSecretKey,publicValues:publicValues,secretNames:secretNames,statusLabel:statusLabel,linkState:linkState,valueOf:valueOf,keyLabel:keyLabel,
resolveHtml:resolveHtml,chipHtml:chipHtml,scopeColumns:scopeColumns,allKeys:allKeys,affectedLabel:affectedLabel,normFindingTargets:normFindingTargets,stateLabel:stateLabel,linkSummary:linkSummary}
if(typeof document==="undefined"||typeof ReportWidgets==="undefined")return core

// ---- UI ----
const RW=ReportWidgets
const el=RW.el
const SECRET_WARNING="Passwords, hashes, tokens and account names are normally kept out of reports."
function call(method,args){return bridgeCall("reports."+method,args||[])}
function oops(fallback){return (err)=>{RW.toast(RW.errText(err,fallback),true)}}
function clone(o){return JSON.parse(JSON.stringify(o===undefined?null:o))}
function currentReport(){
try{return window.Reporting&&typeof window.Reporting.current==="function"?window.Reporting.current():null}catch(e){return null}
}
function textBtn(label,cls,title,icon){
const b=el("button","rpt-btn"+(cls?" "+cls:""))
b.type="button"
if(title)b.title=title
b.innerHTML=(icon?`<i class="icon icon-${icon}"></i>`:"")+`<span>${esc(label)}</span>`
return b
}
function searchBox(placeholder){
const wrap=el("div","rpt-search rtg-search")
wrap.innerHTML='<i class="icon icon-search"></i>'
const input=el("input")
input.type="text"
input.placeholder=placeholder
input.spellcheck=false
input.setAttribute("aria-label",placeholder)
wrap.appendChild(input)
return {el:wrap,input:input}
}
function badge(text,cls,title){
const b=el("span","rtg-badge"+(cls?" "+cls:""),text)
if(title)b.title=title
return b
}
// The page that owns the open report: its callbacks outlive the Details pane, so a change made from an editor menu still reaches
// the page's copy of the report and its undo history.
const hooks={reportId:null,ctx:null,mounts:[]}
function publish(reportId,links,findingMap){
const rep=currentReport()
if(rep&&rep.id===reportId){
rep.targets=links
// The server rewrote the text of the references when the links changed; the page's copy follows, so opening a section is not an edit.
arr(rep.sections).forEach((s)=>{if(typeof s.content==="string"&&s.content.indexOf("rpt-tv")>=0)s.content=resolveHtml(s.content,links)})
arr(rep.findings).forEach((f)=>{RICH_FIELDS.forEach((k)=>{if(typeof f[k]==="string"&&f[k].indexOf("rpt-tv")>=0)f[k]=resolveHtml(f[k],links)})})
if(findingMap)arr(rep.findings).forEach((f)=>{f.targets=arr(findingMap[String(f.id)])})
else{
// Findings only ever point at links that still exist.
const by=byUid(links)
arr(rep.findings).forEach((f)=>{if(arr(f.targets).length)f.targets=f.targets.filter((t)=>by[t.uid])})
}
}
if(hooks.reportId===reportId){
if(hooks.ctx&&typeof hooks.ctx.onChanged==="function"){try{hooks.ctx.onChanged(links,findingMap||null)}catch(e){console.error(e)}}
hooks.mounts.forEach((m)=>m.render(links))
}
if(typeof ReportRich!=="undefined"&&typeof ReportRich.refreshTargetValues==="function")ReportRich.refreshTargetValues(links)
}
// One user action on the links: runs it, tells the page, and hands the page the before/after state as an undo step.
function mutate(reportId,label,run){
return call("targets_state",[reportId]).then((before)=>run().then((links)=>call("targets_state",[reportId]).then((after)=>{
publish(reportId,arr(links))
if(hooks.reportId===reportId&&hooks.ctx&&typeof hooks.ctx.onOp==="function"&&JSON.stringify(before)!==JSON.stringify(after)){
// The step carries its data (before / after, for applyOp) and ready-made undo / redo functions: the page may use either.
const op={type:"targets",label:label,before:before,after:after}
op.undo=()=>applyOp(reportId,op,true)
op.redo=()=>applyOp(reportId,op,false)
try{hooks.ctx.onOp(op)}catch(e){console.error(e)}
}
return arr(links)
})))
}
// Undo / redo of a {type:"targets"} step: puts the links (and the findings' use of them) back and refreshes every view.
function applyOp(reportId,op,undo){
return call("targets_restore",[reportId,clone(undo?op.before:op.after)]).then((res)=>{
publish(reportId,arr(res&&res.targets),(res&&res.findings)||{})
return arr(res&&res.targets)
})
}
function confirmSecret(link,key){
return RW.confirm("Add “"+key+"” of "+link.name+" to this report? "+SECRET_WARNING+" If you continue, the current value of this one key is copied into the report: it can then be inserted into the text, shown for findings and in the scope table, and it WILL appear in exports that use it. You can withdraw it again from the target’s details.",{okLabel:"Add to the report",danger:true})
}
function allowSecret(reportId,link,key,allow){
return mutate(reportId,(allow?"allow":"withdraw")+" “"+key+"” of "+link.name,()=>call("target_allow_secret",[reportId,link.uid,key,!!allow]))
}

// ---- link picker: every target of every profile ----
function pickToLink(reportId,linked){
return new Promise((resolve)=>{
let result=null,all=[],loaded=false
const picked={}
const have={}
arr(linked).forEach((l)=>{have[l.profile_id+"|"+l.target_id]=1})
const wrap=el("div","rtg-pick")
wrap.appendChild(el("div","rpt-ai-note","Linked targets become the report’s scope data. The report keeps a snapshot of each target, so later changes on the Targets page only reach the report when you update it. Passwords, hashes, tokens and account names are not copied."))
const search=searchBox("Search targets, profiles and values")
wrap.appendChild(search.el)
const listEl=el("div","rpt-pick-list rtg-pick-list")
wrap.appendChild(listEl)
const count=el("span","rtg-pick-count rpt-muted","")
function sync(){
const n=Object.keys(picked).length
count.textContent=n?n+" selected":""
if(m)m.foot.querySelectorAll(".rpt-btn-primary").forEach((b)=>{b.disabled=!n})
}
function render(){
const q=search.input.value.trim().toLowerCase()
listEl.innerHTML=""
if(!loaded){listEl.appendChild(el("div","rpt-empty","Loading targets…"));return}
let lastProfile=null,shown=0
all.forEach((t)=>{
const vals=Object.keys(t.values||{}).map((k)=>k+": "+t.values[k])
if(q&&(t.name+" "+t.profile_name+" "+vals.join(" ")).toLowerCase().indexOf(q)<0)return
if(t.profile_id!==lastProfile){
lastProfile=t.profile_id
listEl.appendChild(el("div","rpt-pick-group-title",(t.profile_name||"Profile")+(t.profile_active?" (active profile)":"")))
}
shown++
const id=t.profile_id+"|"+t.target_id
const row=el("label","rpt-pick-row rtg-pick-row")
const cb=el("input")
cb.type="checkbox"
cb.checked=!!picked[id]||!!have[id]
cb.disabled=!!have[id]
cb.addEventListener("change",()=>{if(cb.checked)picked[id]=t;else delete picked[id];sync()})
row.appendChild(cb)
const text=el("span","rpt-pick-text")
const name=el("span","rpt-pick-name")
name.appendChild(el("span",null,t.name||"Unnamed target"))
if(t.live)name.appendChild(badge("live","live","The live target of the active profile"))
text.appendChild(name)
text.appendChild(el("span","rpt-pick-sub rpt-mono",vals.join("  ·  ")||"No values"))
row.appendChild(text)
const right=el("span","rpt-pick-right")
right.textContent=have[id]?"Already linked":statusLabel(t.engagement_status)
row.appendChild(right)
listEl.appendChild(row)
})
if(!shown)listEl.appendChild(el("div","rpt-empty",all.length?"No targets match.":"There are no targets yet. Add them on the Targets page."))
}
const m=RW.modal({title:"Link targets to this report",bodyEl:wrap,wide:true,className:"rtg-modal",onClose:()=>resolve(result),buttons:[
{label:"Cancel"},
{label:"Link selected",primary:true,onClick:()=>{result=Object.keys(picked).map((k)=>({target_id:picked[k].target_id,profile_id:picked[k].profile_id}))}}
]})
m.foot.insertBefore(count,m.foot.firstChild)
search.input.addEventListener("input",render)
render()
sync()
call("targets_available",[null]).then((list)=>{all=arr(list);loaded=true;render()}).catch((err)=>{listEl.innerHTML="";listEl.appendChild(el("div","rpt-empty",RW.errText(err,"The targets could not be loaded.")))})
setTimeout(()=>search.input.focus(),30)
})
}

// ---- details of one link: its snapshot, what changed, protected values ----
function openDetails(reportId,uid,getLinks){
const wrap=el("div","rtg-details")
let m=null
function link(){return arr(getLinks()).find((l)=>l.uid===uid)||null}
function render(){
const l=link()
wrap.innerHTML=""
if(!l){if(m)m.close();return}
const head=el("div","rtg-details-head")
head.appendChild(el("span","rtg-details-name",l.name))
head.appendChild(el("span","rpt-muted",(l.profile_name||"Unknown profile")+" · "+statusLabel(l.snapshot&&l.snapshot.engagement_status)))
if(l.live)head.appendChild(badge("live","live"))
if(l.state!=="ok")head.appendChild(badge(stateLabel(l),l.state))
wrap.appendChild(head)
if(l.state==="changed"){
const note=el("div","rtg-note changed")
note.appendChild(el("span",null,"Changed on the Targets page since this snapshot: "+arr(l.changed_keys).map(keyLabel).join(", ")+"."))
const b=textBtn("Update from target","rpt-btn-small","Take the target’s current name, values and status into the report","refresh")
b.addEventListener("click",()=>mutate(reportId,"update "+l.name+" from the target",()=>call("target_update",[reportId,uid])).then(()=>{RW.toast("Updated from the target");render()}).catch(oops("The target could not be updated.")))
note.appendChild(b)
wrap.appendChild(note)
}else if(l.state==="removed")wrap.appendChild(el("div","rtg-note removed","This target was removed from the Targets page. The report keeps the snapshot below; it can no longer be updated."))
const snap=snapshotOf(l)
const table=el("div","rtg-values")
const keys=Object.keys(snap.values)
if(!keys.length)table.appendChild(el("div","rpt-muted","The snapshot holds no values."))
keys.forEach((k)=>{
const row=el("div","rtg-value")
row.appendChild(el("span","rtg-value-key",k))
row.appendChild(el("span","rtg-value-val rpt-mono",snap.values[k]))
if(isSecretKey(k)){
row.classList.add("protected")
const b=el("button","rpt-link","Withdraw")
b.type="button"
b.title="Remove this protected value from the report again"
b.addEventListener("click",()=>allowSecret(reportId,l,k,false).then(()=>{RW.toast("“"+k+"” was withdrawn from the report");render()}).catch(oops("The value could not be withdrawn.")))
row.appendChild(badge("protected, allowed","secret","You allowed this protected value for this report"))
row.appendChild(b)
}
table.appendChild(row)
})
wrap.appendChild(table)
if(arr(l.secret_keys).length){
const sec=el("div","rtg-secrets")
sec.appendChild(el("div","rtg-secrets-title","Protected values (not in the report)"))
sec.appendChild(el("div","rpt-ai-note",SECRET_WARNING+" They are never copied, inserted or exported unless you add one here."))
l.secret_keys.forEach((k)=>{
const row=el("div","rtg-value protected")
row.appendChild(el("span","rtg-value-key",k))
row.appendChild(el("span","rtg-value-val rpt-muted","••••••"))
const b=el("button","rpt-link","Add to the report…")
b.type="button"
b.addEventListener("click",()=>confirmSecret(l,k).then((ok)=>{
if(!ok)return
return allowSecret(reportId,l,k,true).then(()=>{RW.toast("“"+k+"” is now part of this report");render()})
}).catch(oops("The value could not be added.")))
row.appendChild(b)
sec.appendChild(row)
})
wrap.appendChild(sec)
}
wrap.appendChild(el("div","rtg-details-foot rpt-muted","Linked "+(typeof ReportCore!=="undefined"&&ReportCore.fmtDate?ReportCore.fmtDate(l.linked_at):str(l.linked_at).slice(0,10))+(l.updated_at&&l.updated_at!==l.linked_at?" · snapshot updated "+(typeof ReportCore!=="undefined"&&ReportCore.fmtDate?ReportCore.fmtDate(l.updated_at):str(l.updated_at).slice(0,10)):"")))
}
render()
m=RW.modal({title:"Linked target",bodyEl:wrap,wide:true,className:"rtg-modal",buttons:[
{label:"Unlink",danger:true,left:true,keepOpen:true,onClick:()=>{
const l=link()
if(!l)return
unlink(reportId,l).then((done)=>{if(done)m.close()})
return false
}},
{label:"Close"}
]})
return m
}
function unlink(reportId,l){
const rep=currentReport()
const used=rep&&rep.id===reportId?arr(rep.findings).filter((f)=>arr(f.targets).some((t)=>t.uid===l.uid)).length:0
const ask=used?RW.confirm("Unlink "+l.name+"? "+used+" finding"+(used===1?" lists":"s list")+" it as affected; it is removed from "+(used===1?"that finding":"those findings")+". Text that already shows its values keeps the last value.",{okLabel:"Unlink",danger:true}):Promise.resolve(true)
return ask.then((ok)=>{
if(!ok)return false
return mutate(reportId,"unlink target "+l.name,()=>call("target_unlink",[reportId,l.uid])).then(()=>true)
}).catch((err)=>{RW.toast(RW.errText(err,"The target could not be unlinked."),true);return false})
}

// ---- the scope block of the Details pane ----
// ctx: {reportId,getReport():Report,onChanged(targets,findingMap|null),onOp({type:"targets",label,before,after}),setOption(key,value)}
function mountScope(host,ctx){
ctx=ctx||{}
const reportId=ctx.reportId
if(hooks.reportId!==reportId){hooks.reportId=reportId;hooks.mounts=[]}
hooks.ctx=ctx
const root=el("div","rtg")
host.appendChild(root)
let links=[],alive=true
function report(){return (typeof ctx.getReport==="function"?ctx.getReport():null)||{}}
function setOption(key,value){
const rep=report()
if(typeof ctx.setOption==="function"){ctx.setOption(key,value);return}
// No page hook for options: store it here and hand the page an undo step of its own.
const before=rep.options&&rep.options[key]!==undefined?clone(rep.options[key]):null
const apply=(v)=>{
const r=report()
if(r.options){if(v===null)delete r.options[key];else r.options[key]=clone(v)}
return call("update",[reportId,{options:{[key]:v}}]).then(()=>{render()})
}
apply(value).catch(oops("The scope table setting could not be saved."))
if(typeof ctx.onOp==="function"&&JSON.stringify(before)!==JSON.stringify(value)){
try{ctx.onOp({type:"targets-option",label:"change the scope table",key:key,before:before,after:value,undo:()=>apply(before),redo:()=>apply(value)})}catch(e){console.error(e)}
}
}
function render(next){
if(!alive)return
if(Array.isArray(next))links=next
else links=arr(report().targets)
const rep=report(),opts=rep.options||{}
root.innerHTML=""
const head=el("div","rtg-head")
const title=el("div","rtg-head-text")
title.appendChild(el("span","rtg-hint",links.length?"Their data can be used for findings, inserted into the text and listed in the scope table.":"Optional. Link targets from the Targets page to use their data in findings, in the text and in a generated scope table."))
head.appendChild(title)
const actions=el("div","rtg-actions")
const stale=links.filter((l)=>l.state==="changed")
if(stale.length){
const up=textBtn("Update all ("+stale.length+")","rpt-btn-small","Take the current data of every changed target into the report","refresh")
up.addEventListener("click",()=>mutate(reportId,"update the linked targets",()=>call("target_update",[reportId,null])).then(()=>RW.toast("Updated from the targets")).catch(oops("The targets could not be updated.")))
actions.appendChild(up)
}
const add=textBtn("Link targets…","rpt-btn-small","Choose targets from any profile","target")
add.addEventListener("click",()=>pickToLink(reportId,links).then((items)=>{
if(!items||!items.length)return
return mutate(reportId,"link "+items.length+" target"+(items.length===1?"":"s"),()=>call("target_link",[reportId,items])).then(()=>RW.toast("Linked "+items.length+" target"+(items.length===1?"":"s")))
}).catch(oops("The targets could not be linked.")))
actions.appendChild(add)
head.appendChild(actions)
root.appendChild(head)
if(!links.length)return
const chips=el("div","rtg-chips")
links.forEach((l)=>{
const c=el("span","rtg-chip"+(l.state!=="ok"?" "+l.state:""))
c.dataset.uid=l.uid
const open=el("button","rtg-chip-main")
open.type="button"
open.title=linkSummary(l)+"\n\nClick for details"
if(l.live)open.appendChild(el("span","rtg-live-dot"))
open.appendChild(el("span","rtg-chip-name",l.name))
open.appendChild(el("span","rtg-chip-profile",l.profile_name||"profile removed"))
if(l.state!=="ok")open.appendChild(badge(stateLabel(l),l.state))
if(arr(l.allowed_secret_keys).length)open.appendChild(badge(l.allowed_secret_keys.length+" protected","secret","Protected values allowed for this report: "+l.allowed_secret_keys.join(", ")))
open.addEventListener("click",()=>openDetails(reportId,l.uid,()=>links))
c.appendChild(open)
if(l.state==="changed"){
const up=el("button","rtg-chip-btn")
up.type="button"
up.title="Update from target"
up.setAttribute("aria-label","Update "+l.name+" from the target")
up.innerHTML='<i class="icon icon-refresh"></i>'
up.addEventListener("click",()=>mutate(reportId,"update "+l.name+" from the target",()=>call("target_update",[reportId,l.uid])).then(()=>RW.toast("Updated from the target")).catch(oops("The target could not be updated.")))
c.appendChild(up)
}
const x=el("button","rtg-chip-btn rtg-chip-x")
x.type="button"
x.title="Unlink"
x.setAttribute("aria-label","Unlink "+l.name)
x.innerHTML='<i class="icon icon-close"></i>'
x.addEventListener("click",()=>unlink(reportId,l))
c.appendChild(x)
chips.appendChild(c)
})
root.appendChild(chips)
// Scope table
const tableOn=opts.scope_table!==false
const tb=el("div","rtg-table")
const tl=el("label","rtg-check")
const cb=el("input")
cb.type="checkbox"
cb.checked=tableOn
cb.addEventListener("change",()=>{setOption("scope_table",cb.checked?null:false);render()})
tl.appendChild(cb)
tl.appendChild(el("span",null,"List the linked targets as a table in the Scope section"))
tb.appendChild(tl)
const explicit=Array.isArray(opts.scope_columns)
const cols=scopeColumns(links,explicit?opts.scope_columns:null)
const avail=allKeys(links).concat(["@status"])
cols.forEach((k)=>{if(avail.indexOf(k)<0)avail.push(k)})
const colRow=el("div","rtg-cols"+(tableOn?"":" off"))
colRow.appendChild(el("span","rtg-cols-label","Columns"))
colRow.appendChild(el("span","rtg-col fixed","Target"))
avail.forEach((k)=>{
const on=cols.indexOf(k)>=0
const b=el("button","rtg-col"+(on?" on":"")+(isSecretKey(k)?" secret":""),k==="@status"?"Status":k)
b.type="button"
b.setAttribute("aria-pressed",on?"true":"false")
b.title=(on?"Shown":"Hidden")+" in the scope table"+(isSecretKey(k)?" (protected value you allowed)":"")
b.addEventListener("click",()=>{
const next=on?cols.filter((c)=>c!==k):avail.filter((c)=>c===k||cols.indexOf(c)>=0)
if(next.length>MAX_COLUMNS){RW.toast("The scope table shows at most "+MAX_COLUMNS+" columns.",true);return}
setOption("scope_columns",next)
render()
})
colRow.appendChild(b)
})
if(explicit){
const reset=el("button","rpt-link","Reset")
reset.type="button"
reset.title="Back to the automatic columns (addresses and status)"
reset.addEventListener("click",()=>{setOption("scope_columns",null);render()})
colRow.appendChild(reset)
}
tb.appendChild(colRow)
tb.appendChild(el("div","rtg-hint","The table can also be placed anywhere with the editor’s Widget menu (“Scope targets table”). Single values go in with “Target value”."))
root.appendChild(tb)
}
const handle={render:render}
hooks.mounts.push(handle)
render()
// The links carry their state (changed / target removed) as of the last load: ask again, the Targets page may have been used since.
call("targets_list",[reportId]).then((list)=>{
if(!alive)return
const fresh=arr(list)
if(JSON.stringify(fresh)!==JSON.stringify(links)){
const rep=report()
if(rep)rep.targets=fresh
render(fresh)
if(typeof ctx.onChanged==="function"){try{ctx.onChanged(fresh,null)}catch(e){console.error(e)}}
}
}).catch(()=>{})
return {
refresh:()=>render(),
destroy:()=>{alive=false;const i=hooks.mounts.indexOf(handle);if(i>=0)hooks.mounts.splice(i,1);root.remove()},
applyOp:(op,undo)=>applyOp(reportId,op,undo)
}
}

// ---- finding: which linked targets it affects, and which of their values to show ----
// Resolves [{uid,keys}] or null when cancelled.
function pickForFinding(report,current){
return new Promise((resolve)=>{
const links=arr(report&&report.targets)
let result=null
const sel={}
normFindingTargets(current,links).forEach((t)=>{sel[t.uid]=t.keys.slice()})
const wrap=el("div","rtg-pick")
if(!links.length){
wrap.appendChild(el("div","rpt-empty","This report has no linked targets yet. Link them in Details › Scope (“Link targets…”), or type the affected asset by hand."))
RW.modal({title:"Affected targets",bodyEl:wrap,onClose:()=>resolve(null),buttons:[{label:"Close"}]})
return
}
wrap.appendChild(el("div","rpt-ai-note","Tick the targets this finding affects, then the values to print next to each name. Protected values appear only after you added them to the report from the target’s details."))
const search=searchBox("Filter the linked targets")
if(links.length>6)wrap.appendChild(search.el)
const listEl=el("div","rpt-pick-list rtg-pick-list")
wrap.appendChild(listEl)
function render(){
const q=search.input.value.trim().toLowerCase()
listEl.innerHTML=""
links.forEach((l)=>{
const snap=snapshotOf(l)
const keys=Object.keys(snap.values)
keys.sort((a,b)=>(ADDRESS_KEY_RX.test(a)?0:1)-(ADDRESS_KEY_RX.test(b)?0:1))
if(q&&(l.name+" "+keys.map((k)=>k+" "+snap.values[k]).join(" ")).toLowerCase().indexOf(q)<0)return
const group=el("div","rtg-ft"+(sel[l.uid]?" on":""))
const row=el("label","rpt-pick-row rtg-pick-row")
const cb=el("input")
cb.type="checkbox"
cb.checked=!!sel[l.uid]
cb.addEventListener("change",()=>{if(cb.checked)sel[l.uid]=sel[l.uid]||[];else delete sel[l.uid];render()})
row.appendChild(cb)
const text=el("span","rpt-pick-text")
const name=el("span","rpt-pick-name")
name.appendChild(el("span",null,l.name))
if(l.state!=="ok")name.appendChild(badge(stateLabel(l),l.state))
text.appendChild(name)
text.appendChild(el("span","rpt-pick-sub",sel[l.uid]?"Printed as: "+affectedLabel(l,sel[l.uid]):(l.profile_name||"")))
row.appendChild(text)
group.appendChild(row)
if(sel[l.uid]&&keys.length){
const vals=el("div","rtg-ft-values")
keys.forEach((k)=>{
const vr=el("label","rtg-ft-value"+(isSecretKey(k)?" protected":""))
const vc=el("input")
vc.type="checkbox"
vc.checked=sel[l.uid].indexOf(k)>=0
vc.addEventListener("change",()=>{
const cur=sel[l.uid]||[]
sel[l.uid]=vc.checked?keys.filter((x)=>x===k||cur.indexOf(x)>=0):cur.filter((x)=>x!==k)
render()
})
vr.appendChild(vc)
vr.appendChild(el("span","rtg-value-key",k))
vr.appendChild(el("span","rtg-value-val rpt-mono",snap.values[k]))
if(isSecretKey(k))vr.appendChild(badge("protected","secret"))
vals.appendChild(vr)
})
group.appendChild(vals)
}
listEl.appendChild(group)
})
if(!listEl.firstChild)listEl.appendChild(el("div","rpt-empty","No linked targets match."))
}
search.input.addEventListener("input",render)
render()
RW.modal({title:"Affected targets",bodyEl:wrap,wide:true,className:"rtg-modal",onClose:()=>resolve(result),buttons:[
{label:"Cancel"},
{label:"Apply",primary:true,onClick:()=>{result=links.filter((l)=>sel[l.uid]).map((l)=>({uid:l.uid,keys:sel[l.uid].slice()}))}}
]})
})
}

// ---- editor: pick one value of a linked target ----
// Resolves {uid,key,value,plain:bool} or null. plain=true: insert the text as it is now, without a live reference.
function pickValue(report){
return new Promise((resolve)=>{
const reportId=report&&report.id
let result=null,m=null
const wrap=el("div","rtg-pick")
function links(){const rep=currentReport();return arr(rep&&rep.id===reportId?rep.targets:report&&report.targets)}
if(!links().length){
wrap.appendChild(el("div","rpt-empty","This report has no linked targets yet. Link them in Details › Scope (“Link targets…”) first."))
RW.modal({title:"Insert a target value",bodyEl:wrap,onClose:()=>resolve(null),buttons:[{label:"Close"}]})
return
}
const search=searchBox("Search targets and values")
wrap.appendChild(search.el)
const listEl=el("div","rpt-pick-list rtg-pick-list")
wrap.appendChild(listEl)
const mode=el("label","rtg-check rtg-plain")
const plain=el("input")
plain.type="checkbox"
mode.appendChild(plain)
mode.appendChild(el("span",null,"Insert as plain text (it will not follow “Update from target”)"))
wrap.appendChild(mode)
function choose(l,key){
const value=valueOf(l,key)
if(value===null)return
result={uid:l.uid,key:key,value:value,plain:plain.checked}
m.close()
}
function render(){
const q=search.input.value.trim().toLowerCase()
listEl.innerHTML=""
links().forEach((l)=>{
const snap=snapshotOf(l)
const rows=[["@name",l.name]].concat(Object.keys(snap.values).map((k)=>[k,snap.values[k]])).concat([["@status",statusLabel(snap.engagement_status)]])
const match=rows.filter((r)=>!q||(l.name+" "+keyLabel(r[0])+" "+r[1]).toLowerCase().indexOf(q)>=0)
const locked=arr(l.secret_keys).filter((k)=>!q||(l.name+" "+k).toLowerCase().indexOf(q)>=0)
if(!match.length&&!locked.length)return
const title=el("div","rpt-pick-group-title")
title.appendChild(el("span",null,l.name+(l.profile_name?" · "+l.profile_name:"")))
if(l.state!=="ok")title.appendChild(badge(stateLabel(l),l.state))
listEl.appendChild(title)
match.forEach((r)=>{
const b=el("button","rpt-pick-item rtg-value-item"+(isSecretKey(r[0])?" protected":""))
b.type="button"
b.appendChild(el("span","rtg-value-key",keyLabel(r[0])))
b.appendChild(el("span","rtg-value-val rpt-mono",r[1]))
if(isSecretKey(r[0]))b.appendChild(badge("protected, allowed","secret"))
b.addEventListener("click",()=>choose(l,r[0]))
listEl.appendChild(b)
})
locked.forEach((k)=>{
const b=el("button","rpt-pick-item rtg-value-item protected locked")
b.type="button"
b.title="Protected value: you are asked before it is added to the report"
b.appendChild(el("span","rtg-value-key",k))
b.appendChild(el("span","rtg-value-val rpt-muted","••••••"))
b.appendChild(badge("protected","secret"))
b.addEventListener("click",()=>confirmSecret(l,k).then((ok)=>{
if(!ok)return
return allowSecret(reportId,l,k,true).then((list)=>{
const fresh=arr(list).find((x)=>x.uid===l.uid)
if(fresh&&valueOf(fresh,k)!==null)choose(fresh,k)
else render()
})
}).catch(oops("The value could not be added.")))
listEl.appendChild(b)
})
})
if(!listEl.firstChild)listEl.appendChild(el("div","rpt-empty","Nothing matches."))
}
search.input.addEventListener("input",render)
search.input.addEventListener("keydown",(e)=>{if(e.key==="Enter"){e.preventDefault();const first=listEl.querySelector(".rtg-value-item:not(.locked)");if(first)first.click()}})
m=RW.modal({title:"Insert a target value",bodyEl:wrap,wide:true,className:"rtg-modal",onClose:()=>resolve(result),buttons:[{label:"Close"}]})
render()
setTimeout(()=>search.input.focus(),30)
})
}
return Object.assign({mountScope:mountScope,pickForFinding:pickForFinding,pickValue:pickValue,pickToLink:pickToLink,applyOp:applyOp,openDetails:openDetails},core)
})()
if(typeof module!=="undefined"&&module.exports)module.exports=ReportTargets
if(typeof window!=="undefined")window.ReportTargets=ReportTargets
