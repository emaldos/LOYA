// Reporting: AI help. window.ReportAI = {available(), run(action,payload)} exists only while an AI provider is usable.
// run() never sends anything by itself: it asks the backend what would be sent (reportAI.preview), shows that in a consent dialog,
// and only "Send to AI" starts the request. Replies are untrusted text: Markdown -> the report's rich subset -> ReportCore.sanitizeHtml.
var ReportAIKit=(function(){
const NODE=typeof module!=="undefined"&&module.exports&&typeof window==="undefined"
const RC=NODE?require("./reporting_core.js"):ReportCore
const MD=NODE?require("../components/markdown.js"):(typeof LoyaMarkdown!=="undefined"?LoyaMarkdown:null)
const POLL_MS=700
const TITLES={exec_summary:"Draft the executive summary",rewrite_finding:"Rewrite finding text",suggest_remediation:"Suggest remediation",suggest_cvss:"Suggest a CVSS 3.1 vector",summarise_session:"Summarise captured evidence"}

// ---- pure helpers (also exported for node tests/js/reporting_ai.js) ----
function esc(s){return RC.escapeHtml(s===undefined||s===null?"":String(s))}
// The rich subset has h3/h4 only; a model that answers with "# Title" still gets a heading instead of losing it.
function demoteHeadings(html){
return String(html||"").replace(/<(\/?)h([1-6])>/g,(m,slash,n)=>"<"+slash+(Number(n)<=3?"h3":"h4")+">").replace(/<pre data-lang="[^"]*">/g,"<pre>")
}
function mdToHtml(md){
const text=String(md===undefined||md===null?"":md).trim()
if(!text)return ""
const html=MD?MD.toHtml(text,{noteClasses:false}):text.split(/\n{2,}/).map((p)=>"<p>"+esc(p.trim()).replace(/\n/g,"<br>")+"</p>").join("")
return RC.sanitizeHtml(demoteHeadings(html))
}
// Evidence summaries are shown as plain text by the evidence manager: drop the Markdown marks, keep the list shape.
function mdToPlain(md){
return String(md===undefined||md===null?"":md).replace(/\r\n?/g,"\n").split("\n").map((l)=>l
.replace(/^\s{0,3}#{1,6}\s+/,"")
.replace(/^(\s*)[*+]\s+/,"$1- ")
.replace(/\*\*([^*\n]+)\*\*/g,"$1")
.replace(/__([^_\n]+)__/g,"$1")
.replace(/`([^`\n]+)`/g,"$1")).join("\n").replace(/\n{3,}/g,"\n\n").trim()
}
function normalizeResult(action,res){
res=res&&typeof res==="object"?res:{}
const out={text:"",html:"",vector:"",rationale:"",score:null,severity:"",provider:String(res.provider||""),model:String(res.model||"")}
if(action==="suggest_cvss"){
const vector=String(res.vector||"").trim()
// The backend validated it already; this guards the UI against a bridge that returns something else.
if(RC.cvssScore(vector)===null)return null
out.vector=RC.cvssBuild(RC.cvssParse(vector).metrics)
out.score=RC.cvssScore(out.vector)
out.severity=RC.sevFromScore(out.score)
out.rationale=mdToPlain(res.rationale||res.text||"")
out.text=out.rationale
out.html=mdToHtml(res.rationale||res.text||"")
return out
}
const text=String(res.text||"").trim()
if(!text)return null
out.text=action==="summarise_session"?mdToPlain(text):text
out.html=mdToHtml(text)
return out
}
function chars(n){
n=Number(n)||0
return n>=1000?(Math.round(n/100)/10).toLocaleString("en-US")+"k characters":n+" characters"
}
function destinationLine(p){
p=p||{}
const model=p.model?String(p.model):"the provider's default model"
return {provider:String(p.provider||"AI provider"),model:model,where:p.local?"On this machine"+(p.destination?" ("+p.destination+")":""):(p.destination?"Sent to "+p.destination:"Sent over the network"),local:!!p.local}
}
function errMessage(err,fallback){
const m=err&&err.message?String(err.message):(typeof err==="string"?err:"")
if(!m||/^bridge method missing/.test(m))return fallback
return m
}
const pure={mdToHtml,mdToPlain,demoteHeadings,normalizeResult,chars,destinationLine,errMessage,TITLES}
if(NODE)return pure

// ---- browser ----
const RW=ReportWidgets
function el(tag,cls,text){
const e=document.createElement(tag)
if(cls)e.className=cls
if(text!==undefined&&text!==null)e.textContent=text
return e
}
function call(method,args){return bridgeCall("reportAI."+method,args||[])}
let status=null,busy=false
const api={available:available,run:run,status:()=>status}
function publish(st){
status=st||null
const on=!!(st&&st.available),had=window.ReportAI===api
if(on===had)return
window.ReportAI=on?api:undefined
// The Reporting UI builds its AI buttons when it renders; let the visible page pick the change up now.
const page=document.querySelector(".page.active")
if(page&&page.dataset.page==="reporting"&&page.children.length)document.dispatchEvent(new CustomEvent("loya:page-shown",{detail:{page:"reporting",first:false,reportAI:true}}))
}
function refresh(){
return call("status").then((st)=>{publish(st);return !!(st&&st.available)}).catch(()=>{publish(null);return false})
}
function available(){return refresh()}

function detailsBlock(p){
const wrap=el("div","rai-details hidden")
const add=(label,text)=>{
wrap.appendChild(el("div","rai-details-label",label))
wrap.appendChild(el("pre","rai-pre",text))
}
add("Instructions to the model",p.system||"")
add("Data from this app",p.prompt||"")
return wrap
}
function consentBody(action,p){
const d=destinationLine(p)
const box=el("div","rai-box")
const dest=el("div","rai-dest"+(d.local?"":" rai-dest-remote"))
const row=(label,value,cls)=>{
const r=el("div","rai-dest-row")
r.appendChild(el("span","rai-dest-label",label))
r.appendChild(el("span","rai-dest-value"+(cls?" "+cls:""),value))
dest.appendChild(r)
}
row("Provider",d.provider)
row("Model",d.model,"rai-mono")
row("Destination",d.where)
box.appendChild(dest)
if(p.note)box.appendChild(el("div","rai-warn",p.note))
box.appendChild(el("div","rai-head","What will be sent"))
const list=el("ul","rai-list")
;(p.summary||[]).forEach((s)=>list.appendChild(el("li","",s)))
box.appendChild(list)
const meta=el("div","rai-meta")
meta.appendChild(el("span","","About "+chars(p.prompt_chars)+" in total."))
const toggle=el("button","rpt-link rai-toggle","Show the exact text")
toggle.type="button"
meta.appendChild(toggle)
box.appendChild(meta)
const details=detailsBlock(p)
box.appendChild(details)
toggle.addEventListener("click",()=>{
const open=details.classList.toggle("hidden")
toggle.textContent=open?"Show the exact text":"Hide the exact text"
})
box.appendChild(el("div","rai-foot","Nothing has been sent yet. Secrets the app recognises are replaced with a redaction marker, but check the text above for anything the client would not want shared."))
return box
}
function progressBody(p){
const d=destinationLine(p)
const box=el("div","rai-box rai-progress")
box.appendChild(el("div","rai-spinner"))
box.appendChild(el("div","rai-progress-text","Waiting for "+d.provider+" ("+d.model+")..."))
const time=el("div","rai-progress-time","0 s")
box.appendChild(time)
box._time=time
return box
}
function errorBody(message){
const box=el("div","rai-box")
box.appendChild(el("div","rai-error",message))
box.appendChild(el("div","rai-foot","Nothing was changed in the report."))
return box
}
function run(action,payload){
if(busy){RW.toast("An AI request is already open.");return Promise.resolve(null)}
if(!TITLES[action])return Promise.reject(new Error("Unknown AI action."))
busy=true
return call("preview",[action,payload||{}]).then((p)=>dialog(action,payload||{},p),(err)=>{
RW.toast(errMessage(err,"AI help is not available in this build."),true)
refresh()
return null
}).then((res)=>{busy=false;return res},(err)=>{busy=false;throw err})
}
function dialog(action,payload,p){
return new Promise((resolve)=>{
let settled=false,jobId=null,timer=null,tick=null,m=null
function stop(){
if(timer){clearTimeout(timer);timer=null}
if(tick){clearInterval(tick);tick=null}
}
function settle(value){
if(settled)return
settled=true
stop()
if(jobId){call("run_cancel",[jobId]).catch(()=>{});jobId=null}
resolve(value)
}
function setBody(node){
m.body.innerHTML=""
m.body.appendChild(node)
}
function fail(err){
if(settled)return
stop()
jobId=null
setBody(errorBody(errMessage(err,"The AI request failed.")))
// Trying again starts from a fresh preview: the data may have changed, and the operator agrees to what is sent now.
m.setButtons([{label:"Close"},{label:"Try again",primary:true,keepOpen:true,onClick:(ctl,btn)=>{
btn.disabled=true
call("preview",[action,payload]).then((fresh)=>{if(settled)return;p=fresh;showConsent()}).catch(fail)
return false
}}])
}
function finish(raw){
jobId=null
const res=normalizeResult(action,raw)
if(!res){fail(new Error(action==="suggest_cvss"?"The AI did not return a valid CVSS 3.1 vector. Try again, or use the calculator.":"The AI returned an empty reply."));return}
settled=true
stop()
m.close()
resolve(res)
}
function poll(){
if(settled||!jobId)return
call("run_poll",[jobId]).then((r)=>{
if(settled)return
if(!r||!r.done){timer=setTimeout(poll,POLL_MS);return}
if(r.error)fail(new Error(r.error))
else finish(r.result)
}).catch(fail)
}
function send(){
const body=progressBody(p),started=Date.now()
setBody(body)
m.setButtons([{label:"Cancel"}])
tick=setInterval(()=>{body._time.textContent=Math.round((Date.now()-started)/1000)+" s"},1000)
call("run_start",[action,payload,p.digest||null]).then((r)=>{
if(settled){if(r&&r.job_id)call("run_cancel",[r.job_id]).catch(()=>{});return}
jobId=r&&r.job_id
if(!jobId){fail(new Error("The AI request could not be started."));return}
timer=setTimeout(poll,POLL_MS)
}).catch(fail)
}
function showConsent(){
setBody(consentBody(action,p))
m.setButtons([{label:"Cancel"},{label:"Send to AI",primary:true,keepOpen:true,onClick:()=>{send();return false}}])
}
// Escape belongs to this dialog alone: the evidence manager underneath listens for it on document and would close as well.
function onKey(e){
if(e.key!=="Escape"||document.querySelector(".confirm-overlay"))return
e.preventDefault()
e.stopImmediatePropagation()
m.close()
}
m=RW.modal({title:"Send to AI: "+(p.label||TITLES[action]),bodyEl:el("div"),className:"rai-modal",closeOnBackdrop:false,onClose:()=>{window.removeEventListener("keydown",onKey,true);settle(null)}})
window.addEventListener("keydown",onKey,true)
// The evidence manager is a body-level overlay above the app's modal layer; the consent dialog must never open behind it.
const layer=m.el.parentNode
if(layer&&layer!==document.body&&document.querySelector(".rpt-ev-overlay")){layer.classList.add("rai-top");document.body.appendChild(layer)}
showConsent()
})
}
function boot(){
refresh()
// Providers and AI Roles are changed on the Settings page; unlocking the app re-fires this event too.
document.addEventListener("loya:page-shown",(e)=>{if(!(e.detail&&e.detail.reportAI))refresh()})
}
boot()
return Object.assign({api:api,refresh:refresh},pure)
})()
if(typeof module!=="undefined"&&module.exports)module.exports=ReportAIKit
