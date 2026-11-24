// Reporting: shared widgets (badges, CVSS calculator, risk chart, modal helpers) and ReportRich, the report fields' mount of the Notes editor.
var ReportWidgets=(function(){
const RC=ReportCore
const esc=RC.escapeHtml
function el(tag,cls,text){
const e=document.createElement(tag)
if(cls)e.className=cls
if(text!==undefined&&text!==null)e.textContent=text
return e
}
function sevId(sev){return RC.SEVERITIES.some((s)=>s.id===sev)?sev:"info"}
function severityBadge(sev){
const id=sevId(sev)
return `<span class="rpt-sev rpt-sev-${id}">${esc(RC.sevLabel(id))}</span>`
}
function statusBadge(status){
const id=RC.STATUSES.some((s)=>s.id===status)?status:"open"
return `<span class="rpt-status rpt-status-${id}">${esc(RC.statusLabel(id))}</span>`
}
function toast(msg,isError){
if(typeof showToast==="function")showToast(String(msg===undefined||msg===null?"":msg),isError?"error":undefined)
}
function errText(err,fallback){
return err&&err.message?String(err.message):(typeof err==="string"&&err?err:fallback||"Something went wrong.")
}
function confirm(text,opts){
opts=opts||{}
if(typeof appConfirm!=="function")return Promise.resolve(false)
return appConfirm(String(text),{danger:!!opts.danger,okLabel:esc(opts.okLabel||(opts.danger?"Delete":"OK")),cancelLabel:esc(opts.cancelLabel||"Cancel")}).then((r)=>r===true)
}
function copyText(text){
const done=()=>toast("Copied")
const fallback=()=>{
const ta=el("textarea","rpt-offscreen")
ta.value=text
document.body.appendChild(ta)
ta.select()
let ok=false
try{ok=document.execCommand("copy")}catch(e){ok=false}
ta.remove()
if(ok)done()
else toast("Copy failed",true)
}
if(navigator.clipboard&&navigator.clipboard.writeText)navigator.clipboard.writeText(text).then(done).catch(fallback)
else fallback()
}

// ---- modal: the app's modal for the first one, a stacked layer for a dialog opened from inside another (openModal is a singleton) ----
const modalStack=[]
function modal(opts){
opts=opts||{}
const card=el("div","rpt-modal glass-panel"+(opts.wide?" rpt-modal-wide":"")+(opts.className?" "+opts.className:""))
const head=el("div","rpt-modal-head")
head.appendChild(el("div","rpt-modal-title",opts.title||""))
const x=el("button","rpt-icon-btn rpt-modal-x")
x.type="button"
x.title="Close"
x.innerHTML='<i class="icon icon-close"></i>'
head.appendChild(x)
card.appendChild(head)
const body=el("div","rpt-modal-body")
if(opts.bodyEl)body.appendChild(opts.bodyEl)
else if(opts.html)body.innerHTML=opts.html
card.appendChild(body)
const foot=el("div","rpt-modal-foot")
card.appendChild(foot)
let closed=false,layer=null
const ctl={el:card,body:body,foot:foot,close:close,setButtons:setButtons}
function finish(){
if(closed)return false
closed=true
const i=modalStack.indexOf(ctl)
if(i>=0)modalStack.splice(i,1)
if(typeof opts.onClose==="function")opts.onClose()
return true
}
function close(){
if(closed)return
if(layer){
window.removeEventListener("keydown",onKey,true)
layer.remove()
finish()
return
}
finish()
const bd=document.getElementById("appModalBackdrop")
if(bd&&bd.contains(card)&&typeof closeModal==="function")closeModal(true)
else card.remove()
}
// Closing by Escape, the X or the backdrop asks first when opts.confirmClose() returns a question (unsaved form).
function guard(){
const q=typeof opts.confirmClose==="function"?opts.confirmClose():""
return q?confirm(q,{danger:true,okLabel:"Discard"}):Promise.resolve(true)
}
function softClose(){
if(closed)return
if(!layer&&typeof closeModal==="function"){closeModal();return}
guard().then((ok)=>{if(ok)close()})
}
function onKey(e){
if(e.key!=="Escape"||modalStack[modalStack.length-1]!==ctl)return
if(document.querySelector(".confirm-overlay"))return
e.preventDefault()
e.stopPropagation()
softClose()
}
function setButtons(buttons){
foot.innerHTML=""
;(buttons||[]).forEach((b)=>{
const btn=el("button","rpt-btn"+(b.primary?" rpt-btn-primary":"")+(b.danger?" rpt-btn-danger":""),b.label)
btn.type="button"
if(b.title)btn.title=b.title
if(b.left)btn.classList.add("rpt-btn-left")
btn.addEventListener("click",()=>{
const r=typeof b.onClick==="function"?b.onClick(ctl,btn):undefined
if(r!==false&&!b.keepOpen)close()
})
foot.appendChild(btn)
b.el=btn
})
foot.classList.toggle("hidden",!foot.children.length)
}
setButtons(opts.buttons)
x.addEventListener("click",softClose)
if(!document.getElementById("appModalBackdrop")&&typeof openModal==="function"){
openModal(card,{closeOnBackdrop:opts.closeOnBackdrop!==false,onBeforeClose:()=>guard().then((ok)=>{if(ok)finish();return ok})})
}else{
layer=el("div","app-modal-backdrop rpt-modal-stack")
card.classList.add("app-modal-card")
layer.appendChild(card)
if(opts.closeOnBackdrop!==false)layer.addEventListener("mousedown",(e)=>{if(e.target===layer)softClose()})
// window-capture runs before the app modal's document-capture Escape handler, so only the top dialog closes.
window.addEventListener("keydown",onKey,true)
;(document.getElementById("content")||document.body).appendChild(layer)
}
modalStack.push(ctl)
return ctl
}
// A small form dialog. fields: [{key,label,value,placeholder,type:"text"|"number"|"textarea"|"select",options:[[value,label]],list:[suggestions],min,max,hint}]
function ask(opts){
return new Promise((resolve)=>{
let result=null
const form=el("div","rpt-form")
const inputs={}
const err=el("div","rpt-form-error")
;(opts.fields||[]).forEach((f,i)=>{
const row=el("label","rpt-field")
row.appendChild(el("span","rpt-field-label",f.label||""))
let input
if(f.type==="textarea"){input=el("textarea","rpt-input rpt-textarea");input.rows=f.rows||4}
else if(f.type==="select"){
input=el("select","rpt-input rpt-select")
;(f.options||[]).forEach((o)=>{const op=el("option",null,o[1]);op.value=o[0];input.appendChild(op)})
}else{
input=el("input","rpt-input")
input.type=f.type==="number"?"number":"text"
if(f.min!==undefined)input.min=f.min
if(f.max!==undefined)input.max=f.max
if(f.list&&f.list.length){
const dl=el("datalist")
dl.id="rptAskList"+Date.now()+"_"+i
f.list.forEach((v)=>{const op=el("option");op.value=v;dl.appendChild(op)})
row.appendChild(dl)
input.setAttribute("list",dl.id)
}
input.addEventListener("keydown",(e)=>{if(e.key==="Enter"){e.preventDefault();submit()}})
}
if(f.placeholder)input.placeholder=f.placeholder
input.value=f.value===undefined||f.value===null?"":f.value
input.spellcheck=false
row.appendChild(input)
if(f.hint)row.appendChild(el("span","rpt-field-hint",f.hint))
form.appendChild(row)
inputs[f.key]=input
})
form.appendChild(err)
function submit(){
const values={}
Object.keys(inputs).forEach((k)=>{values[k]=inputs[k].value})
const problem=typeof opts.validate==="function"?opts.validate(values):""
if(problem){err.textContent=problem;return false}
result=values
m.close()
return false
}
const buttons=[{label:"Cancel"}]
if(opts.extraLabel)buttons.push({label:opts.extraLabel,danger:!!opts.extraDanger,onClick:()=>{result={_extra:true}}})
buttons.push({label:opts.okLabel||"OK",primary:true,keepOpen:true,onClick:submit})
const m=modal({title:opts.title||"",bodyEl:form,buttons:buttons,className:"rpt-modal-ask",onClose:()=>resolve(result)})
const first=inputs[Object.keys(inputs)[0]]
if(first)setTimeout(()=>{first.focus();if(first.select)first.select()},30)
})
}

// ---- CVSS v3.1 calculator ----
function cvssCalculator(host,opts){
opts=opts||{}
const root=el("div","rpt-cvss")
const head=el("div","rpt-cvss-head")
const score=el("div","rpt-cvss-score")
const sevText=el("div","rpt-cvss-sev")
const vecInput=el("input","rpt-input rpt-cvss-vector")
vecInput.type="text"
vecInput.spellcheck=false
vecInput.placeholder="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"
vecInput.title="Paste or type a CVSS 3.1 vector"
const copyBtn=el("button","rpt-btn rpt-btn-small","Copy")
copyBtn.type="button"
copyBtn.title="Copy the vector string"
const clearBtn=el("button","rpt-btn rpt-btn-small","Clear")
clearBtn.type="button"
clearBtn.title="Remove the CVSS vector"
const scoreBox=el("div","rpt-cvss-scorebox")
scoreBox.appendChild(score)
scoreBox.appendChild(sevText)
head.appendChild(scoreBox)
head.appendChild(vecInput)
head.appendChild(copyBtn)
head.appendChild(clearBtn)
root.appendChild(head)
const errLine=el("div","rpt-cvss-error")
root.appendChild(errLine)
const grid=el("div","rpt-cvss-grid")
root.appendChild(grid)
let metrics={}
const buttons={}
RC.CVSS_METRICS.forEach((m)=>{
const row=el("div","rpt-cvss-row")
const label=el("div","rpt-cvss-label")
label.title=m.help
label.appendChild(el("span","rpt-cvss-name",m.name))
label.appendChild(el("span","rpt-cvss-key",m.key))
row.appendChild(label)
const group=el("div","rpt-cvss-group")
group.setAttribute("role","radiogroup")
group.setAttribute("aria-label",m.name)
buttons[m.key]={}
m.values.forEach((v)=>{
const b=el("button","rpt-cvss-opt",v.label)
b.type="button"
b.title=v.label+" ("+m.key+":"+v.v+") \u2014 "+v.help
b.setAttribute("role","radio")
b.addEventListener("click",()=>{
metrics[m.key]=v.v
errLine.textContent=""
paint(true)
emit()
})
group.appendChild(b)
buttons[m.key][v.v]=b
})
row.appendChild(group)
grid.appendChild(row)
})
function complete(){return RC.CVSS_ORDER.every((k)=>metrics[k])}
function current(){
if(!complete())return {vector:"",score:null,severity:""}
const vector=RC.cvssBuild(metrics)
const sc=RC.cvssScore(vector)
return {vector:vector,score:sc,severity:RC.sevFromScore(sc)}
}
function paint(writeInput){
RC.CVSS_METRICS.forEach((m)=>m.values.forEach((v)=>{
const on=metrics[m.key]===v.v
buttons[m.key][v.v].classList.toggle("active",on)
buttons[m.key][v.v].setAttribute("aria-checked",on?"true":"false")
}))
const cur=current()
score.textContent=cur.score===null?"\u2013":cur.score.toFixed(1)
root.dataset.sev=cur.score===null?"none":cur.severity
sevText.textContent=cur.score===null?(Object.keys(metrics).length?"Incomplete":"Not scored"):(cur.score===0?"None":RC.sevLabel(cur.severity))
if(writeInput&&cur.vector)vecInput.value=cur.vector
copyBtn.disabled=!cur.vector
}
function emit(){
if(typeof opts.onChange!=="function")return
const cur=current()
if(cur.vector)opts.onChange(cur)
}
function readInput(){
const raw=vecInput.value.trim()
if(!raw){errLine.textContent="";return}
const p=RC.cvssParse(raw)
if(!p.valid){errLine.textContent=p.error;return}
errLine.textContent=""
metrics=Object.assign({},p.metrics)
paint(false)
emit()
}
vecInput.addEventListener("input",readInput)
vecInput.addEventListener("blur",()=>{if(complete()&&RC.cvssParse(vecInput.value).valid)vecInput.value=RC.cvssBuild(metrics)})
copyBtn.addEventListener("click",()=>{const cur=current();if(cur.vector)copyText(cur.vector)})
clearBtn.addEventListener("click",()=>{
metrics={}
vecInput.value=""
errLine.textContent=""
paint(false)
if(typeof opts.onChange==="function")opts.onChange({vector:"",score:null,severity:""})
})
function setVector(v){
const p=RC.cvssParse(v)
metrics=p.valid?Object.assign({},p.metrics):{}
vecInput.value=p.valid?RC.cvssBuild(metrics):String(v||"")
errLine.textContent=v&&!p.valid?p.error:""
paint(false)
}
host.appendChild(root)
setVector(opts.vector||"")
return {setVector:setVector,getValue:current,destroy:()=>root.remove(),el:root}
}

// ---- risk chart: stacked severity bar with a labelled legend, plus an impact x likelihood matrix when findings carry a likelihood ----
const SVG_NS="http://www.w3.org/2000/svg"
function svg(tag,attrs,text){
const n=document.createElementNS(SVG_NS,tag)
Object.keys(attrs||{}).forEach((k)=>n.setAttribute(k,attrs[k]))
if(text!==undefined)n.textContent=text
return n
}
function riskChart(host,findings,opts){
opts=opts||{}
const root=el("div","rpt-chart"+(opts.compact?" rpt-chart-compact":""))
host.appendChild(root)
let data=findings||[],lastW=0
const LK=[["low","Low"],["medium","Medium"],["high","High"]]
function render(){
const W=Math.max(220,Math.floor(root.clientWidth||host.clientWidth||520))
lastW=W
root.innerHTML=""
const sum=RC.riskSummary(data)
if(!sum.total){
root.appendChild(el("div","rpt-chart-empty","No findings yet."))
return
}
const compact=!!opts.compact
const withLk=data.filter((f)=>f&&(f.likelihood==="low"||f.likelihood==="medium"||f.likelihood==="high"))
const showMatrix=!compact&&withLk.length>0
const side=showMatrix&&W>=600
const barW=side?Math.floor(W*0.5)-16:W
const barH=compact?10:14
const present=RC.SEVERITIES.filter((s)=>sum.counts[s.id]>0)
const s=svg("svg",{class:"rpt-chart-svg",role:"img","aria-label":"Findings by severity: "+RC.SEVERITIES.map((x)=>sum.counts[x.id]+" "+x.label).join(", ")})
root.appendChild(s)
const headH=compact?0:22
const legendTop=headH+barH+12
// Legend: swatch, label and count per severity; rows wrap by the measured text width.
const items=RC.SEVERITIES.map((sv)=>{
const g=svg("g",{class:"rpt-chart-legend"+(sum.counts[sv.id]?"":" rpt-chart-zero")})
g.appendChild(svg("rect",{x:0,y:2,width:10,height:10,rx:3,class:"rpt-fill-"+sv.id}))
const t=svg("text",{x:15,y:11})
t.appendChild(svg("tspan",{class:"rpt-chart-label"},sv.label))
t.appendChild(svg("tspan",{class:"rpt-chart-count",dx:6},String(sum.counts[sv.id])))
g.appendChild(t)
s.appendChild(g)
let w=0
try{w=t.getComputedTextLength()}catch(e){w=0}
if(!w)w=sv.label.length*6.4+14
return {g:g,w:15+w+16}
})
let lx=0,ly=0
const lineH=20
items.forEach((it)=>{
if(lx>0&&lx+it.w-16>barW){lx=0;ly+=lineH}
it.g.setAttribute("transform","translate("+lx+","+(legendTop+ly)+")")
lx+=it.w
})
const leftH=legendTop+ly+lineH
// Matrix geometry.
const cell=compact?0:28,gap=2,rowLabelW=92,mxCols=LK.length
const mW=rowLabelW+mxCols*(64+gap)
const mH=22+RC.SEVERITIES.length*(cell+gap)+20
const mX=side?W-mW:0
const mY=side?0:leftH+18
const H=showMatrix?(side?Math.max(leftH,mH):mY+mH):leftH
s.setAttribute("width",W)
s.setAttribute("height",H)
s.setAttribute("viewBox","0 0 "+W+" "+H)
if(!compact){
s.appendChild(svg("text",{x:0,y:13,class:"rpt-chart-title"},"Findings by severity"))
s.appendChild(svg("text",{x:barW,y:13,class:"rpt-chart-total","text-anchor":"end"},sum.total+" total \u00b7 "+sum.open+" open"))
}
// Stacked bar: 2px surface gaps between segments, 4px radius on the outer ends only.
const gaps=(present.length-1)*2
let x=0
present.forEach((sv,i)=>{
const last=i===present.length-1
const w=last?barW-x:Math.max(4,Math.round((barW-gaps)*sum.counts[sv.id]/sum.total))
const r=Math.min(4,w/2,barH/2)
const rl=i===0?r:0,rr=last?r:0
const y=headH
const d="M"+(x+rl)+","+y+"H"+(x+w-rr)+(rr?"a"+rr+","+rr+" 0 0 1 "+rr+","+rr:"")+"V"+(y+barH-rr)+(rr?"a"+rr+","+rr+" 0 0 1 -"+rr+","+rr:"")+"H"+(x+rl)+(rl?"a"+rl+","+rl+" 0 0 1 -"+rl+",-"+rl:"")+"V"+(y+rl)+(rl?"a"+rl+","+rl+" 0 0 1 "+rl+",-"+rl:"")+"Z"
const seg=svg("path",{d:d,class:"rpt-chart-seg rpt-fill-"+sv.id})
seg.appendChild(svg("title",{},sv.label+": "+sum.counts[sv.id]+" of "+sum.total+" ("+Math.round(100*sum.counts[sv.id]/sum.total)+"%)"))
s.appendChild(seg)
x+=w+2
})
if(showMatrix){
const g=svg("g",{transform:"translate("+mX+","+mY+")"})
g.appendChild(svg("text",{x:0,y:13,class:"rpt-chart-title"},"Impact by likelihood"))
const grid={}
let max=0
withLk.forEach((f)=>{
const k=sevId(f.severity)+"|"+f.likelihood
grid[k]=(grid[k]||0)+1
if(grid[k]>max)max=grid[k]
})
RC.SEVERITIES.forEach((sv,r)=>{
const y=22+r*(cell+gap)
g.appendChild(svg("text",{x:rowLabelW-10,y:y+cell/2+4,class:"rpt-chart-label","text-anchor":"end"},sv.label))
LK.forEach((lk,c)=>{
const n=grid[sv.id+"|"+lk[0]]||0
const cx=rowLabelW+c*(64+gap)
const rect=svg("rect",{x:cx,y:y,width:64,height:cell,rx:4,class:n?"rpt-chart-cell rpt-fill-"+sv.id:"rpt-chart-cell rpt-chart-cell-empty"})
if(n)rect.setAttribute("fill-opacity",(0.28+0.5*n/max).toFixed(2))
rect.appendChild(svg("title",{},sv.label+" severity, "+lk[1].toLowerCase()+" likelihood: "+n+" finding"+(n===1?"":"s")))
g.appendChild(rect)
if(n)g.appendChild(svg("text",{x:cx+32,y:y+cell/2+4,class:"rpt-chart-cellnum","text-anchor":"middle"},String(n)))
})
})
const ay=22+RC.SEVERITIES.length*(cell+gap)+12
LK.forEach((lk,c)=>g.appendChild(svg("text",{x:rowLabelW+c*(64+gap)+32,y:ay,class:"rpt-chart-axis","text-anchor":"middle"},lk[1])))
const rest=sum.total-withLk.length
if(rest>0){
const note=svg("text",{x:0,y:ay,class:"rpt-chart-axis"},rest+" not rated")
note.appendChild(svg("title",{},rest+" finding"+(rest===1?" has":"s have")+" no likelihood set"))
g.appendChild(note)
}
s.appendChild(g)
}
}
let ro=null
if(typeof ResizeObserver==="function"){
ro=new ResizeObserver(()=>{
const w=Math.floor(root.clientWidth||0)
if(w&&Math.abs(w-lastW)>4)render()
})
ro.observe(root)
}
render()
return {update:(f)=>{data=f||[];render()},destroy:()=>{if(ro)ro.disconnect();root.remove()},el:root}
}
return {severityBadge:severityBadge,statusBadge:statusBadge,cvssCalculator:cvssCalculator,riskChart:riskChart,modal:modal,confirm:confirm,toast:toast,ask:ask,copyText:copyText,errText:errText,el:el}
})()
if(typeof window!=="undefined")window.ReportWidgets=ReportWidgets
// ---- ReportRich: report fields are edited with the Notes editor. Each field is a "host" mounted on the shared editor code (notes.js notesHostMount, notes_pro.js, notes_draw.js);
// this module only supplies what differs for reports: images are DB assets (rptasset:UID), the stored HTML is the report subset v2 (ReportCore.sanitizeHtml), and the report-specific inserts.
var ReportRich=(function(){
const RC=ReportCore,RW=ReportWidgets
const el=RW.el
const esc=RC.escapeHtml
const IMG_TYPES=["image/png","image/jpeg","image/gif","image/webp"]
const IMG_MAX=10*1024*1024
const UID_RE=/^[A-Za-z0-9_\-]{6,64}$/
const MD_FILE_MAX=2*1024*1024
const ALIGN_TAGS={P:1,H3:1,H4:1,LI:1,BLOCKQUOTE:1,TD:1,TH:1}
const WIDGETS=[{id:"risk_matrix",label:"Risk matrix"},{id:"severity_summary",label:"Severity summary"},{id:"findings_table",label:"Findings overview table"},{id:"commands_run",label:"Commands run (generated)"},{id:"scope_targets",label:"Scope targets table (linked targets)"}]
const assetCache={},viewCache={}
// Live editors, so a change of the report's linked targets can refresh the reference chips they show.
const liveEditors=[]
function targetsApi(){return typeof window!=="undefined"&&window.ReportTargets&&typeof window.ReportTargets.pickValue==="function"?window.ReportTargets:null}
// A reference chip shows the link's current value; one whose link or value is gone keeps its text and is drawn as unlinked.
function refreshTv(root,links){
const T=targetsApi()
const nodes=root.querySelectorAll?root.querySelectorAll(".rpt-tv"):[]
if(!nodes.length)return false
if(links===undefined){const rep=currentReport();links=rep&&Array.isArray(rep.targets)?rep.targets:null}
let hit=false
nodes.forEach((n)=>{
n.contentEditable="false"
if(!T||!links)return
const key=n.getAttribute("data-key")||""
const link=links.find((l)=>l.uid===n.getAttribute("data-target"))
const v=T.valueOf(link,key)
const text=v===null?(T.isSecretKey(key)?T.WITHHELD:n.textContent):v
if(n.textContent!==text){n.textContent=text;hit=true}
n.classList.toggle("unlinked",v===null)
n.title=v===null?"This value is no longer available from the report’s linked targets":(link.name+" · "+T.keyLabel(key)+" (follows the linked target)")
})
return hit
}
function refreshTargetValues(links){liveEditors.slice().forEach((fn)=>{try{fn(links)}catch(e){console.error(e)}})}
function assetUrl(uid){
if(!assetCache[uid]){
assetCache[uid]=bridgeCall("reports.asset_get",[uid]).then((a)=>(a&&a.data_url)||"").catch(()=>{delete assetCache[uid];return ""})
}
return assetCache[uid]
}
// Short blob: URLs keep the editor's HTML (and its undo snapshots) small; a data: URL is the fallback.
function blobUrl(dataUrl){
try{
const m=/^data:([^;,]+);base64,(.*)$/.exec(dataUrl)
if(!m)return dataUrl
const bin=atob(m[2])
const bytes=new Uint8Array(bin.length)
for(let i=0;i<bin.length;i++)bytes[i]=bin.charCodeAt(i)
return URL.createObjectURL(new Blob([bytes],{type:m[1]}))
}catch(e){return dataUrl}
}
function viewUrl(uid){
if(!viewCache[uid])viewCache[uid]=assetUrl(uid).then((d)=>{if(!d){delete viewCache[uid];return ""}return blobUrl(d)})
return viewCache[uid]
}
function uploadDataUrl(name,dataUrl){
return bridgeCall("reports.asset_add",[name||"image.png",dataUrl]).then((a)=>{
if(!a||!a.uid)throw new Error("The image could not be stored.")
assetCache[a.uid]=Promise.resolve(dataUrl)
return a
})
}
function readFile(file){
return new Promise((resolve,reject)=>{
if(!file||IMG_TYPES.indexOf(file.type)<0){reject(new Error("Only PNG, JPEG, GIF and WebP images can be added."));return}
if(file.size>IMG_MAX){reject(new Error("The image is larger than 10 MB."));return}
const r=new FileReader()
r.onload=()=>resolve(String(r.result||""))
r.onerror=()=>reject(new Error("The image could not be read."))
r.readAsDataURL(file)
})
}
function uploadFile(file){
return readFile(file).then((dataUrl)=>uploadDataUrl(file.name||("pasted-"+Date.now()+"."+(file.type.split("/")[1]||"png")),dataUrl).then((a)=>({asset:a,dataUrl:dataUrl})))
}
// Opens the system file picker; resolves with [{asset,dataUrl}] for the images that could be stored.
function pickImages(multiple){
return new Promise((resolve)=>{
const input=el("input","rpt-offscreen")
input.type="file"
input.accept=IMG_TYPES.join(",")
input.multiple=!!multiple
document.body.appendChild(input)
input.addEventListener("change",()=>{
const files=Array.prototype.slice.call(input.files||[])
input.remove()
Promise.all(files.map((f)=>uploadFile(f).catch((err)=>{RW.toast(RW.errText(err,"Image upload failed."),true);return null}))).then((r)=>resolve(r.filter(Boolean)))
})
input.click()
// No "cancel" event on older engines: the orphan input is removed the next time the window gets focus.
window.addEventListener("focus",()=>setTimeout(()=>{if(input.isConnected&&!(input.files&&input.files.length))input.remove()},1500),{once:true})
})
}
// The editor's storage hook: an image file / data URL becomes a report asset (never a notes attachment).
function storeAsset(name,dataUrl){
const m=/^data:([^;,]+)[;,]/.exec(String(dataUrl||""))
if(!m||IMG_TYPES.indexOf(m[1].toLowerCase())<0)return Promise.reject(new Error("Only PNG, JPEG, GIF and WebP images can be added to a report."))
if(dataUrl.length>IMG_MAX*1.4)return Promise.reject(new Error("The image is larger than 10 MB."))
return uploadDataUrl(name,dataUrl).then((a)=>{
if(!viewCache[a.uid])viewCache[a.uid]=Promise.resolve(blobUrl(dataUrl))
return viewCache[a.uid].then((url)=>({id:a.uid,url:url,kind:"image",filename:a.name||name||"image",size:0}))
})
}
function rename(node,tag){
const n=document.createElement(tag)
const al=node.getAttribute&&node.getAttribute("data-align")
if(al)n.setAttribute("data-align",al)
while(node.firstChild)n.appendChild(node.firstChild)
node.replaceWith(n)
return n
}
function unwrap(node){
const p=node.parentNode
if(!p)return
while(node.firstChild)p.insertBefore(node.firstChild,node)
p.removeChild(node)
}
function toHex(v){
const s=String(v||"").trim().toLowerCase()
let m=/^#([0-9a-f]{6})$/.exec(s)
if(m)return "#"+m[1]
m=/^#([0-9a-f])([0-9a-f])([0-9a-f])$/.exec(s)
if(m)return "#"+m[1]+m[1]+m[2]+m[2]+m[3]+m[3]
m=/^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*(?:,\s*([\d.]+)\s*)?\)$/.exec(s)
if(m&&(m[4]===undefined||parseFloat(m[4])>0))return "#"+[m[1],m[2],m[3]].map((x)=>Math.min(255,parseInt(x,10)).toString(16).padStart(2,"0")).join("")
return ""
}
const BLOCKS="p,h3,h4,ul,ol,pre,blockquote,table,figure,hr,div,h1,h2,h5,h6,li"
const KEEP_DIV=".note-callout,.rpt-widget"
function isBlockEl(n){return n.nodeType===1&&n.matches(BLOCKS)}
// Engine output and pasted markup -> tags of the subset (the sanitiser only unwraps what it does not know).
function normaliseTree(root){
root.querySelectorAll("h1,h2").forEach((n)=>rename(n,"h3"))
root.querySelectorAll("h5,h6").forEach((n)=>rename(n,"h4"))
root.querySelectorAll("strike,del").forEach((n)=>rename(n,"s"))
root.querySelectorAll("ins").forEach((n)=>rename(n,"u"))
root.querySelectorAll("tt,kbd,samp,var").forEach((n)=>rename(n,"code"))
// Google Docs wraps the whole clipboard in <b style="font-weight:normal">.
root.querySelectorAll("b[style],strong[style]").forEach((n)=>{if(/font-weight\s*:\s*(normal|[1-4]00)/i.test(n.getAttribute("style")||""))unwrap(n)})
Array.prototype.slice.call(root.querySelectorAll("div,section,article,header,footer,main,aside,center,address,dd,dt")).reverse().forEach((n)=>{
if(n.matches(KEEP_DIV))return
if(n.closest("pre")){n.appendChild(document.createTextNode("\n"));unwrap(n);return}
if(n.querySelector(BLOCKS))unwrap(n)
else if(n.closest("p,h3,h4,figcaption")){if(n.previousSibling)n.before(document.createElement("br"));unwrap(n)}
else rename(n,"p")
})
// A paragraph may not hold block content: lift nested blocks out by unwrapping the paragraph.
root.querySelectorAll("p").forEach((p)=>{if(p.querySelector("p,ul,ol,table,pre,blockquote,figure,h3,h4,hr,div"))unwrap(p)})
}
function wrapLooseInline(root){
let run=null
Array.prototype.slice.call(root.childNodes).forEach((n)=>{
const block=isBlockEl(n)
if(block){run=null;return}
if(n.nodeType===3&&!n.nodeValue.trim()&&!run){n.remove();return}
if(n.nodeType!==1&&n.nodeType!==3){n.remove();return}
if(n.nodeType===1&&n.tagName==="BR"&&!run){n.remove();return}
if(!run){run=document.createElement("p");root.insertBefore(run,n)}
run.appendChild(n)
})
}
function isBlankBlock(n){
return n.nodeType===1&&/^(P|H3|H4)$/.test(n.tagName)&&!n.textContent.replace(/[\s ​]/g,"")&&!n.querySelector("img")
}
function plainToHtml(text){
return String(text).replace(/\r\n?/g,"\n").split(/\n{2,}/).map((para)=>"<p>"+para.split("\n").map(esc).join("<br>")+"</p>").join("")
}
// data-* of the stored subset -> what the browser needs to show it (shared by the editor and the read-only view).
function applyData(root){
root.querySelectorAll("[data-align]").forEach((n)=>{n.style.textAlign=n.getAttribute("data-align");n.removeAttribute("data-align")})
root.querySelectorAll("span[data-color],span[data-bg],span[data-size]").forEach((n)=>{
const c=n.getAttribute("data-color"),b=n.getAttribute("data-bg"),s=n.getAttribute("data-size")
if(c)n.style.color=c
if(b)n.style.backgroundColor=b
if(s)n.style.fontSize=s+"px"
n.removeAttribute("data-color");n.removeAttribute("data-bg");n.removeAttribute("data-size")
})
root.querySelectorAll("td[data-width],th[data-width]").forEach((n)=>{const w=n.getAttribute("data-width")+"px";n.style.width=w;n.style.minWidth=w;n.removeAttribute("data-width")})
root.querySelectorAll("img[data-width]").forEach((n)=>{const w=n.getAttribute("data-width");n.style.width=/%|px$/.test(w)?w:w+"px";n.style.height="auto";n.removeAttribute("data-width")})
}
function loadImages(root){
root.querySelectorAll("img[data-attachment-id]").forEach((img)=>{
img.classList.add("rpt-img-loading")
viewUrl(img.dataset.attachmentId).then((url)=>{
img.classList.remove("rpt-img-loading")
if(url)img.src=url
else img.classList.add("rpt-img-missing")
})
})
root.querySelectorAll("figure.note-embed[data-attachment-id]").forEach((fig)=>viewUrl(fig.dataset.attachmentId).then((url)=>{if(url)fig.dataset.attachmentUrl=url}))
}
// Stored subset -> editor DOM. `cards` receives the data of command figures (they are shown as the Notes command cards).
function toEditable(html,cards){
const tpl=document.createElement("template")
tpl.innerHTML=RC.sanitizeHtml(html)
const root=tpl.content
root.querySelectorAll("img").forEach((img)=>{
const m=/^rptasset:(.+)$/.exec(img.getAttribute("src")||"")
img.removeAttribute("src")
if(!m){img.remove();return}
img.dataset.attachmentId=m[1]
let fig=img.closest("figure")
if(!fig){
// A bare image of subset v1 becomes a figure, so it can be moved, resized and annotated like any picture.
fig=document.createElement("figure")
fig.className="note-embed note-embed-inline"
fig.dataset.kind="image"
const p=img.parentNode
img.replaceWith(fig)
fig.appendChild(img)
if(p&&p.nodeType===1&&p.tagName==="P"&&p.childNodes.length===1)p.replaceWith(fig)
}
})
root.querySelectorAll("figure.note-embed").forEach((fig)=>{
const img=fig.querySelector("img")
if(!img){fig.remove();return}
const orig=fig.getAttribute("data-asset")||img.dataset.attachmentId
fig.removeAttribute("data-asset")
fig.dataset.attachmentId=orig
if(!fig.dataset.kind)fig.dataset.kind="image"
if(!/note-embed-(inline|float-left|float-right)|note-align-(center|right)/.test(fig.className))fig.classList.add("note-embed-inline")
fig.contentEditable="false"
fig.draggable=true
})
root.querySelectorAll("figure.rpt-ev").forEach((f)=>{f.contentEditable="false"})
root.querySelectorAll("figure.rpt-cmd").forEach((f)=>{
const cap=f.querySelector("figcaption"),p=f.querySelector("p"),pre=f.querySelector("pre")
const data={cmd_note_title:cap?cap.textContent.trim():"",description:p?p.textContent.trim():"",command:pre?pre.textContent:"",command_type:f.getAttribute("data-type")||"other",category:f.getAttribute("data-cat")||"",sub_category:f.getAttribute("data-sub")||"",tags:f.getAttribute("data-tags")||""}
if(!data.command.trim()||!cards){f.remove();return}
const cid=notesGenCid()
cards[cid]=data
f.replaceWith(notesRenderCmdCardEmbed(cid,data))
})
root.querySelectorAll("pre").forEach((pre)=>{if(!pre.closest("figure,.cmd-card"))pre.classList.add("note-code")})
root.querySelectorAll(".rpt-widget,.rpt-fref,.rpt-ph,.rpt-tv").forEach((n)=>{n.contentEditable="false"})
refreshTv(root)
applyData(root)
return root
}
// The engine re-applies the theme's own text colour and size as inline style when blocks merge (Backspace at a paragraph start,
// typing over a selection that spans blocks). Kept, that dark-theme near-white text is invisible on an exported white page.
function themeTextStyle(body){
const colors=new Set()
const els=[body];["p","li","h3","h4","td","th","blockquote"].forEach((t)=>{const e=body.querySelector(t);if(e)els.push(e)})
els.forEach((e)=>{try{const h=toHex(getComputedStyle(e).color);if(h)colors.add(h)}catch(err){}})
let size="";try{size=getComputedStyle(body).fontSize||""}catch(err){}
return {colors,size}
}
function styleToData(c,theme){
c.querySelectorAll("font").forEach((f)=>{
const s=document.createElement("span")
const col=toHex(f.getAttribute("color"))
if(col)s.style.color=col
if(f.style.backgroundColor)s.style.backgroundColor=f.style.backgroundColor
while(f.firstChild)s.appendChild(f.firstChild)
f.replaceWith(s)
})
c.querySelectorAll("[align]").forEach((n)=>{if(!n.style.textAlign)n.style.textAlign=n.getAttribute("align")})
c.querySelectorAll("[style]").forEach((n)=>{
const st=n.style
const ta=String(st.textAlign||"").toLowerCase().replace(/^-webkit-/,"")
if(ta==="center"||ta==="right"||ta==="justify")n.setAttribute("data-align",ta)
if(n.tagName==="SPAN"&&!n.className){
const engine=!!(st.caretColor||st.fontFamily||st.letterSpacing||st.textTransform)
const col=toHex(st.color),bg=toHex(st.backgroundColor),fs=engine||(theme&&theme.size&&st.fontSize===theme.size)?null:/^(\d{1,3})(?:\.\d+)?px$/.exec(st.fontSize||"")
if(col&&!(theme&&theme.colors.has(col)))n.setAttribute("data-color",col)
if(bg)n.setAttribute("data-bg",bg)
if(fs)n.setAttribute("data-size",String(Math.max(8,Math.min(72,parseInt(fs[1],10)))))
}
if(n.tagName==="TD"||n.tagName==="TH"){const w=/^(\d{2,4})(?:\.\d+)?px$/.exec(st.width||"");if(w)n.setAttribute("data-width",w[1])}
if(n.tagName==="IMG"){const w=/^(\d{1,4})(?:\.\d+)?(px|%)$/.exec(st.width||"");if(w)n.setAttribute("data-width",w[1]+w[2])}
})
}
// Editor DOM -> stored subset (always through the sanitiser).
function fromEditable(body,cards){
const theme=themeTextStyle(body)
const c=body.cloneNode(true)
c.querySelectorAll(".rpt-ui").forEach((n)=>n.remove())
notesProCleanClone(c)
c.querySelectorAll(".cmd-card-embed").forEach((card)=>{
const d=(cards||{})[card.dataset.cid]
if(!d||!String(d.command||"").trim()){card.remove();return}
const f=document.createElement("figure")
f.className="rpt-cmd"
const put=(k,v)=>{v=String(v||"").replace(/[^A-Za-z0-9 ._+#\/(),\-]/g," ").replace(/\s+/g," ").trim();if(v)f.setAttribute(k,v.slice(0,k==="data-tags"?200:k==="data-type"?40:80))}
put("data-type",d.command_type);put("data-cat",(d.category||"").replace(/,/g," "));put("data-sub",(d.sub_category||"").replace(/,/g," "));put("data-tags",d.tags)
const cap=document.createElement("figcaption");cap.textContent=d.cmd_note_title||"Command";f.appendChild(cap)
if(d.description){const p=document.createElement("p");p.textContent=d.description;f.appendChild(p)}
const pre=document.createElement("pre");pre.textContent=d.command;f.appendChild(pre)
card.replaceWith(f)
})
styleToData(c,theme)
c.querySelectorAll("figure.note-embed").forEach((fig)=>{
if(fig.dataset.kind==="file"||!fig.querySelector("img")){fig.remove();return}
const orig=fig.dataset.attachmentId||""
if(UID_RE.test(orig))fig.setAttribute("data-asset",orig)
const img=fig.querySelector("img")
if(!img.dataset.attachmentId&&orig)img.dataset.attachmentId=orig
})
c.querySelectorAll("img").forEach((img)=>{
const uid=img.dataset.attachmentId||""
if(UID_RE.test(uid))img.setAttribute("src","rptasset:"+uid)
else{const fig=img.closest("figure.note-embed");(fig||img).remove()}
})
c.querySelectorAll("pre").forEach((pre)=>{
if(pre.closest("figure"))return
pre.querySelectorAll("br").forEach((br)=>br.replaceWith(document.createTextNode("\n")))
pre.querySelectorAll("div,p").forEach((d)=>{d.appendChild(document.createTextNode("\n"));unwrap(d)})
pre.textContent=(pre.textContent||"").replace(/\n$/,"")
})
c.querySelectorAll(".rpt-widget").forEach((w)=>{w.textContent=""})
normaliseTree(c)
// Engines store a typed or pasted space next to an inline boundary as U+00A0; a lone one is an ordinary space (keeps exported text wrapping).
const tw=document.createTreeWalker(c,NodeFilter.SHOW_TEXT)
let tn
while((tn=tw.nextNode())){
if(tn.nodeValue.indexOf(" ")<0||tn.parentNode.closest("pre,code"))continue
tn.nodeValue=tn.nodeValue.replace(/(^|[^\s ]) (?![\s ])/g,"$1 ")
}
wrapLooseInline(c)
while(c.lastChild&&(isBlankBlock(c.lastChild)||(c.lastChild.nodeType===3&&!c.lastChild.nodeValue.trim())))c.removeChild(c.lastChild)
if(!c.textContent.replace(/[\s ​]/g,"")&&!c.querySelector("img,figure,hr,table,.rpt-widget"))return ""
return RC.sanitizeHtml(c.innerHTML.replace(/​/g,""))
}
// Clipboard HTML (Word, browsers, Google Docs) -> subset. data: images are handed to `onDataImage` and get a temporary id.
function cleanPasted(html,onDataImage){
let body
try{body=new DOMParser().parseFromString(String(html),"text/html").body}catch(e){body=null}
if(!body)return RC.sanitizeHtml(html)
body.querySelectorAll("script,style,meta,link,title,head,xml,template,noscript").forEach((n)=>n.remove())
normaliseTree(body)
body.querySelectorAll("p,h3,h4,li").forEach((n)=>{if(n.tagName!=="LI"&&isBlankBlock(n))n.remove()})
return RC.sanitizeHtml(body.innerHTML,{imgSrc:(src)=>{
if(/^data:image\/(png|jpeg|gif|webp);base64,/i.test(src)&&src.length<IMG_MAX*1.4)return "rptasset:"+onDataImage(src)
return null
}})
}
function mdLib(){return typeof LoyaMarkdown!=="undefined"?LoyaMarkdown:null}
function currentReport(){
try{return window.Reporting&&typeof window.Reporting.current==="function"?window.Reporting.current():null}catch(e){return null}
}
// The editor code lives in the Notes scripts; without them a field cannot be mounted (reporting.js then shows its plain fallback).
function editorReady(){return typeof notesHostMount==="function"&&typeof notesProWireBody==="function"&&typeof NotesPro!=="undefined"}
let prefsAsked=false
function ensurePrefs(){
if(prefsAsked)return
prefsAsked=true
if(typeof notesState!=="undefined"&&!notesState.prefs&&typeof notesLoadPrefs==="function")notesLoadPrefs()
}
// Toolbar model. The editor commands come from the Notes command registry (notes_editor.js: notesEdMountToolbar draws the same toolbar, More panel, selection bubble and right-click menu for this host);
// the tools marked `own` are the report-specific ones and sit in a second row. Without the registry scripts the whole list below is drawn instead, so a field never loses its tools.
// `fn(x,btn)` runs with the field's host active and its selection restored. `compact:false` moves a tool into the More menu of compact fields.
const TOOLS=[
{id:"style",text:"H",title:"Text style: paragraph, headings, quote (or type # and a space)",fn:(x,b)=>x.styleMenu(b)},
{id:"bold",icon:"bold",title:"Bold (Ctrl+B)",cmd:"bold"},
{id:"italic",icon:"italic",title:"Italic (Ctrl+I)",cmd:"italic"},
{id:"underline",icon:"underline",title:"Underline (Ctrl+U)",cmd:"underline"},
{id:"strike",text:"S",cls:"rpt-tb-strike",title:"Strikethrough",cmd:"strikeThrough",compact:false},
{id:"inlineCode",text:"`c`",cls:"rpt-tb-mono",title:"Inline code (or type `code`)",fn:(x)=>x.inlineCode(),compact:false},
{sep:true},
{id:"alignL",icon:"align-left",title:"Align left",cmd:"justifyLeft",compact:false},
{id:"alignC",icon:"align-center",title:"Align center",cmd:"justifyCenter",compact:false},
{id:"alignR",icon:"align-right",title:"Align right",cmd:"justifyRight",compact:false},
{sep:true,compact:false},
{id:"ul",icon:"list",title:"Bullet list (or type - and a space)",cmd:"insertUnorderedList"},
{id:"ol",text:"1.",title:"Numbered list (or type 1. and a space)",cmd:"insertOrderedList"},
{id:"check",text:"☑",title:"Checklist (or type [] and a space)",fn:()=>notesProInsertChecklist(false)},
{id:"table",icon:"table",title:"Insert table (hover it for + row / + column, handles and column resize)",fn:()=>notesInsertTable(3,3)},
{sep:true},
{id:"color",kind:"color",icon:"color",swatch:"text",title:"Text colour",fn:(x,b)=>notesOpenColorPopover(b,NOTES_TEXT_COLORS,notesApplyTextColor,notesColorTextCurrent,false),compact:false},
{id:"highlight",kind:"color",icon:"marker",swatch:"highlight",title:"Highlight colour",fn:(x,b)=>notesOpenColorPopover(b,NOTES_HIGHLIGHT_COLORS,notesApplyHighlightColor,notesColorHighlightCurrent,true),compact:false},
{id:"smaller",icon:"font-smaller",title:"Decrease font size",fn:()=>notesApplyFontSize(notesCurrentFontSize()-1),compact:false},
{id:"bigger",icon:"font-bigger",title:"Increase font size",fn:()=>notesApplyFontSize(notesCurrentFontSize()+1),compact:false},
{sep:true,compact:false},
{id:"image",icon:"image",title:"Insert image (or paste / drop one)",fn:(x)=>x.fileInput.click()},
{id:"hr",icon:"hr",title:"Horizontal line (or type --- and Enter)",cmd:"insertHorizontalRule",compact:false},
{id:"cmd",icon:"command-line",title:"New command block",fn:(x,b)=>notesOpenCmdPopover(b),compact:false},
{id:"pickcmd",icon:"search",title:"Insert a saved command (search the Commands page)",fn:()=>notesOpenPickCommand(),compact:false},
{id:"link",icon:"link",title:"Web link (Ctrl+K)",fn:(x)=>x.linkDialog()},
{sep:true},
{id:"codeBlock",text:"</>",cls:"rpt-tb-mono",title:"Code block (or type ``` and Enter)",fn:()=>notesProInsertCode("")},
{id:"callout",icon:"info",title:"Callout: finding, vulnerability, info, warning, credential, evidence",fn:(x,b)=>notesProOpenCalloutMenu(b)},
{id:"drawing",text:"✎",title:"Drawing (hover a picture and press Annotate to draw on it)",fn:()=>notesProInsertSketch(),compact:false},
{id:"time",icon:"clock",title:"Insert timestamp (Ctrl+Shift+;)",fn:()=>notesProInsertTimestamp(),compact:false},
{id:"ioc",text:"IOC",title:"IOC tools: IPs, domains, URLs, hashes in the selection or the text",fn:(x,b)=>notesProOpenIoc(b),compact:false},
{id:"mask",text:"•••",title:"Mask the selected text as a secret (click again inside it to unmask)",fn:()=>notesProMaskSelection()},
{id:"redact",own:true,text:"Redact",title:"Mark the selection as redacted (hidden in exports)",fn:(x)=>x.toggleRedact(),compact:false},
{id:"clear",text:"Tx",title:"Clear formatting",cmd:"removeFormat",compact:false},
{sep:true},
{id:"fref",own:true,text:"Finding",icon:"target",title:"Insert a reference to a finding of this report",fn:(x)=>x.pickFinding(),report:true},
{id:"evidence",own:true,text:"Evidence",icon:"command-line",title:"Insert captured evidence (command output, screenshots)",fn:(x)=>x.pickEvidence()},
{id:"placeholder",own:true,text:"{{ }}",cls:"rpt-tb-mono",title:"Insert a placeholder filled from the report details on export",fn:(x,b)=>x.placeholderMenu(b),compact:false},
{id:"tvalue",own:true,text:"Target",icon:"crosshair",title:"Insert a value of a linked target (IP, URL, name...): it follows the target when the report is updated from it",fn:(x)=>x.pickTargetValue(),report:true,compact:false},
{id:"widget",own:true,text:"Widget",icon:"report",title:"Insert a generated block: risk matrix, severity summary, findings table, commands run",fn:(x,b)=>x.widgetMenu(b),report:true,compact:false},
{id:"cmdTable",own:true,text:"Cmds",icon:"table",title:"Insert a table of the commands captured as evidence for this engagement",fn:(x)=>x.commandsTable(),report:true,compact:false},
{id:"ai",own:true,text:"AI",icon:"brain",title:"AI assistance",fn:(x)=>x.runAI()},
{sep:true},
{id:"md",own:true,text:"Markdown",title:"Switch between the formatted view and the Markdown source",fn:(x)=>x.setSource(!x.isSource()),always:true},
{id:"mdImport",own:true,text:"Import .md",title:"Insert a Markdown or text file at the caret",fn:(x)=>x.importMarkdown(),always:true,compact:false},
{sep:true,compact:false},
{id:"outline",icon:"list",title:"Outline (headings)",fn:()=>notesProToggleOutline(),compact:false,full:true},
{id:"undo",text:"↶",title:"Undo (Ctrl+Z)",fn:()=>notesUndoUndo(),compact:false},
{id:"redo",text:"↷",title:"Redo (Ctrl+Y)",fn:()=>notesUndoRedo(),compact:false}
]
let seq=0
function create(host,opts){
opts=opts||{}
if(!editorReady())throw new Error("The note editor scripts are not loaded.")
ensurePrefs()
const compact=!!opts.compact
const root=el("div","rpt-rich"+(compact?" rpt-rich-compact":""))
const registry=typeof notesEdMountToolbar==="function"&&typeof notesEdWireDoc==="function"
const regBar=registry?el("div","notes-toolbar rpt-rich-regbar"):null
const bar=el("div","rpt-rich-bar"+(registry?" rpt-rich-bar-own":""))
const main=el("div","rpt-rich-main")
const outline=el("aside","notes-outline rpt-rich-outline hidden")
const wrap=el("div","notes-editor-body-wrap rpt-rich-wrap")
const body=el("div","notes-editor-body rpt-rich-body")
body.contentEditable="true"
body.spellcheck=true
body.setAttribute("role","textbox")
body.setAttribute("aria-multiline","true")
body.dataset.placeholder=opts.placeholder||""
if(opts.minHeight)body.style.minHeight=(typeof opts.minHeight==="number"?opts.minHeight+"px":opts.minHeight)
const src=el("textarea","rpt-rich-src hidden")
src.spellcheck=false
src.setAttribute("aria-label","Markdown source")
src.placeholder="Markdown source"
const fileInput=el("input","rpt-offscreen rpt-ui")
fileInput.type="file"
fileInput.accept=IMG_TYPES.join(",")
fileInput.multiple=true
wrap.appendChild(body)
main.appendChild(outline)
main.appendChild(wrap)
if(regBar)root.appendChild(regBar)
root.appendChild(bar)
root.appendChild(main)
root.appendChild(src)
root.appendChild(fileInput)
host.appendChild(root)
let changeTimer=null,destroyed=false,srcMode=false,lastHtml="",outlineOpen=false,observer=null
const btns={}
const moreTools=[]
const SLASH=NotesPro.SLASH_ITEMS.filter((s)=>s.id!=="h2"&&(s.id!=="toc"||!compact)).map((s)=>s.id==="h1"?Object.assign({},s,{label:"Heading",hint:"Section heading"}):s.id==="h3"?Object.assign({},s,{label:"Sub-heading",hint:"Smaller heading"}):s.id==="image"?Object.assign({},s,{label:"Image",hint:"Screenshot or picture"}):s).concat([
{id:"r-pickcmd",label:"Saved command",hint:"Pick from the Commands page",keys:"saved command pick existing cmd"},
{id:"r-finding",label:"Finding reference",hint:"Link to a finding of this report",keys:"finding reference ref link"},
{id:"r-evidence",label:"Evidence",hint:"Captured command output or screenshot",keys:"evidence proof output capture"},
{id:"r-placeholder",label:"Placeholder",hint:"{{client}}, {{engagement}}...",keys:"placeholder variable client engagement date"},
{id:"r-target",label:"Target value",hint:"IP, URL or name of a linked target",keys:"target value ip url host domain scope linked"},
{id:"r-widget",label:"Report widget",hint:"Risk matrix, summary, findings table",keys:"widget risk matrix summary chart findings table"},
{id:"r-commands",label:"Commands run table",hint:"From the captured evidence",keys:"commands run table history appendix"}
])
const ed=notesHostMount({
id:"report-"+(++seq),body:body,wrap:wrap,root:root,
isOpen:()=>!destroyed&&!srcMode&&body.isConnected,
el:(id)=>{
if(id==="notesOutline")return compact?null:outline
if(id==="notesOutlineBtn")return btns.outline||null
if(id==="notesAttachmentFileInput")return fileInput
if(id==="notesColorTextSwatch")return btns.color?btns.color.querySelector(".notes-tb-color-swatch"):null
if(id==="notesColorHighlightSwatch")return btns.highlight?btns.highlight.querySelector(".notes-tb-color-swatch"):null
if(id==="notesInsertCmd")return shown(btns.cmd)
if(id==="notesInsertCallout")return shown(btns.callout)
if(id==="notesIocTools")return shown(btns.ioc)
return null
},
features:{noteLinks:false,suggest:false,files:false,"view.find":false,"view.outline":!compact,"style.h2":false},
tags:{h1:"h3",h2:"h3",h3:"h4",h5:"h4",h6:"h4"},
labels:{"style.h1":"Heading","style.h3":"Sub-heading"},
store:storeAsset,
data:(id)=>assetUrl(id).then((url)=>{if(!url)throw new Error("The image is no longer in the report.");return url}),
onDirty:()=>changed(),
prefGet:(key)=>key==="editor_outline"?outlineOpen:undefined,
prefSet:(key,value)=>{if(key!=="editor_outline")return false;outlineOpen=!!value&&!compact;return true},
title:()=>"",
pasteHtml:(html)=>{
const t=document.createElement("template")
t.innerHTML=html
t.content.querySelectorAll("img").forEach((n)=>n.remove())
return t.innerHTML
},
structure:(b)=>liveFix(b),
slash:()=>SLASH,
runAction:(id)=>{
if(id==="r-pickcmd")notesOpenPickCommand()
else if(id==="r-finding")api2.pickFinding()
else if(id==="r-evidence")api2.pickEvidence()
else if(id==="r-placeholder")api2.placeholderMenu(caretAnchor())
else if(id==="r-target")api2.pickTargetValue()
else if(id==="r-widget")api2.widgetMenu(caretAnchor())
else if(id==="r-commands")api2.commandsTable()
else return false
return true
},
menu:(items,e)=>{
const t=e.target&&e.target.closest?e.target:null
const fig=t?t.closest("figure.rpt-ev,.rpt-widget,.rpt-fref,.rpt-ph,.rpt-tv"):null
if(fig&&body.contains(fig))items.push({label:fig.matches("figure.rpt-ev")?"Remove Evidence Block":fig.matches(".rpt-widget")?"Remove Widget":"Remove Reference",icon:"trash",danger:true,fn:()=>{fig.remove();notesMarkDirty();notesProAfterStructureChange()}})
if(currentReport())items.push({label:"Finding Reference...",icon:"target",fn:()=>api2.pickFinding()})
items.push({label:"Evidence...",icon:"command-line",fn:()=>api2.pickEvidence()})
items.push({label:"Placeholder...",icon:"edit",fn:()=>api2.placeholderMenu({getBoundingClientRect:()=>({left:e.clientX,right:e.clientX,top:e.clientY,bottom:e.clientY})})})
if(currentReport()&&targetsApi())items.push({label:"Target Value...",icon:"crosshair",fn:()=>api2.pickTargetValue()})
if(currentReport()){
items.push({label:"Report Widget...",icon:"report",fn:()=>api2.widgetMenu({getBoundingClientRect:()=>({left:e.clientX,right:e.clientX,top:e.clientY,bottom:e.clientY})})})
items.push({label:"Commands Run Table",icon:"table",fn:()=>api2.commandsTable()})
}
if(!registry)items.push({label:"Web Link...",icon:"link",fn:()=>api2.linkDialog()})
items.push({label:"Redact Selection",icon:"pin",fn:()=>api2.toggleRedact()})
}
})
function shown(b){return b&&b.offsetParent?b:(regBar?(regBar.querySelector(".notes-ed-more-btn")||regBar):(btns.more&&btns.more.offsetParent?btns.more:bar))}
function activate(){notesHostActivate(ed)}
function cards(){return notesHost===ed?notesState.cmdCards:(ed.cmdCards||{})}
function caretAnchor(){
const r=notesState.savedRange
let rect=r?r.getBoundingClientRect():null
if(!rect||(!rect.width&&!rect.height&&!rect.top)){const n=r?notesProEl(r.startContainer):null;rect=(n||body).getBoundingClientRect()}
return {getBoundingClientRect:()=>rect}
}
function focusBody(){
activate()
body.focus()
notesRestoreRange()
}
function runTool(t,btn){
if(destroyed)return
if(t.always){t.fn(api2,btn);return}
if(srcMode)return
focusBody()
if(t.cmd){document.execCommand(t.cmd,false,null);notesMarkDirty();notesProAfterStructureChange()}
else t.fn(api2,btn)
syncState()
}
function toolButton(t){
const b=el("button",t.kind==="color"?"notes-tb-color rpt-tb-color":"rpt-tb"+(t.cls?" "+t.cls:"")+(t.icon&&t.text?" rpt-tb-wide":""))
b.type="button"
b.title=t.title||""
b.setAttribute("aria-label",t.title||t.text||t.id)
b.innerHTML=(t.icon?`<i class="icon icon-${t.icon}"></i>`:"")+(t.text?`<span>${esc(t.text)}</span>`:"")+(t.kind==="color"?`<span class="notes-tb-color-swatch ${t.swatch}"></span>`:"")
// Keep the editor's selection: a toolbar press must not move focus.
b.addEventListener("mousedown",(e)=>e.preventDefault())
b.addEventListener("click",()=>runTool(t,b))
return b
}
let lastSep=true
if(registry){notesEdWireDoc();notesEdMountToolbar(regBar,{host:ed})}
// The shared style dropdown offers Heading 1-3 and names the block by its tag, but a report field has two heading levels (h3 and h4):
// its dropdown opens the field's own style menu, and the label is rewritten whenever the shared toolbar sets it.
let styleObs=null
function styleName(){
const s=window.getSelection()
if(!s||!s.rangeCount||!body.contains(s.anchorNode))return ""
const n=s.anchorNode.nodeType===1?s.anchorNode:s.anchorNode.parentElement
const b=n&&n.closest?n.closest("pre,h3,h4,blockquote"):null
return b&&body.contains(b)?{PRE:"Code block",H3:"Heading",H4:"Sub-heading",BLOCKQUOTE:"Quote"}[b.tagName]:"Normal"
}
function syncStyleLabel(){
const name=styleName()
if(name)regBar.querySelectorAll(".notes-ed-style-label").forEach((l)=>{if(l.textContent!==name)l.textContent=name})
}
if(registry){
regBar.addEventListener("click",(e)=>{
const b=e.target.closest?e.target.closest(".notes-ed-style"):null
if(!b||destroyed||srcMode)return
e.stopPropagation()
focusBody()
styleMenu(b)
},true)
if(typeof MutationObserver!=="undefined"){
styleObs=new MutationObserver(syncStyleLabel)
styleObs.observe(regBar,{childList:true,subtree:true})
}
}
TOOLS.forEach((t)=>{
if(registry&&!t.own&&!(t.sep&&!lastSep))return
if(t.full&&compact)return
if(compact&&t.compact===false){if(!t.sep)moreTools.push(t);return}
if(t.sep){if(!lastSep)bar.appendChild(el("span","rpt-tb-sep"));lastSep=true;return}
const b=toolButton(t)
btns[t.id]=b
bar.appendChild(b)
lastSep=false
})
if(moreTools.length){
const more=el("button","rpt-tb rpt-tb-wide")
more.type="button"
more.title="More editor tools"
more.setAttribute("aria-label","More editor tools")
more.innerHTML='<i class="icon icon-dots-vertical"></i><span>More</span>'
more.addEventListener("mousedown",(e)=>e.preventDefault())
more.addEventListener("click",()=>{
if(destroyed||srcMode)return
const r=more.getBoundingClientRect()
openContextMenu(moreTools.filter((t)=>!(t.report&&!currentReport())&&!(t.id==="ai"&&!aiOn())&&!(t.id==="tvalue"&&!targetsApi())).map((t)=>({label:(t.title||t.id).replace(/\s*\(.*$/,"").replace(/:.*$/,""),icon:t.icon||undefined,fn:()=>runTool(t,more)})),r.left,r.bottom+4)
})
btns.more=more
bar.insertBefore(more,btns.md||null)
}
function aiOn(){return !!(window.ReportAI&&typeof opts.onAI==="function")}
function syncAI(){
if(btns.ai)btns.ai.classList.toggle("hidden",!aiOn())
const rep=!!currentReport()
;["fref","widget","cmdTable"].forEach((id)=>{if(btns[id])btns[id].classList.toggle("hidden",!rep)})
if(btns.tvalue)btns.tvalue.classList.toggle("hidden",!rep||!targetsApi())
}
function syncEmpty(){
const empty=!body.textContent.replace(/[\s​]/g,"")&&!body.querySelector("img,figure,hr,table,li,pre,blockquote,h3,h4,.note-callout,.cmd-card-embed,.rpt-widget")
body.classList.toggle("is-empty",empty)
}
function syncState(){
if(destroyed||srcMode)return
const has=document.activeElement===body
const q=(c)=>{try{return has&&document.queryCommandState(c)}catch(e){return false}}
;[["bold","bold"],["italic","italic"],["underline","underline"],["strike","strikeThrough"],["ul","insertUnorderedList"],["ol","insertOrderedList"]].forEach((p)=>{if(btns[p[0]])btns[p[0]].classList.toggle("active",q(p[1]))})
}
// Headings outside the subset (pasted Markdown, the "# " shortcut of the shared editor) are renamed in place, so the field shows what will be stored.
function liveFix(b){
b.querySelectorAll("h1,h2,h5,h6").forEach((h)=>{
const n=document.createElement(/H[12]/.test(h.tagName)?"h3":"h4")
while(h.firstChild)n.appendChild(h.firstChild)
h.replaceWith(n)
})
b.querySelectorAll("pre:not(.note-code)").forEach((pre)=>{if(!pre.closest("figure,.cmd-card"))pre.classList.add("note-code")})
}
function getHTML(){
return srcMode?RC.markdownToHtml(src.value,mdLib()):fromEditable(body,cards())
}
function fire(){
changeTimer=null
if(destroyed)return
const html=getHTML()
if(html===lastHtml)return
lastHtml=html
if(typeof opts.onChange==="function")opts.onChange(html)
}
function changed(){
if(destroyed)return
if(!srcMode)syncEmpty()
if(changeTimer)clearTimeout(changeTimer)
changeTimer=setTimeout(fire,250)
}
function flush(){
if(changeTimer){clearTimeout(changeTimer);fire()}
}
function loadBody(html){
activate()
notesProSlashClose()
notesProSetHover(null,null)
const fresh={}
const frag=toEditable(html||"",fresh)
notesState.cmdCards=fresh
ed.cmdCards=fresh
while(body.firstChild)body.removeChild(body.firstChild)
body.appendChild(frag)
loadImages(body)
notesState.savedRange=null
notesProApplyCollapse(body)
notesProEnsureTail()
notesUndoReset(body.innerHTML)
notesProScheduleTint()
if(!compact)notesProRenderOutline()
syncEmpty()
}
// Block content goes after the caret's block (never inside a paragraph); inline content at the caret.
function insertFragment(frag){
focusBody()
const hasBlock=Array.prototype.some.call(frag.childNodes,(n)=>n.nodeType===1&&n.matches("p,h3,h4,ul,ol,pre,blockquote,table,figure,hr,div"))
let range=notesProSel()
if(!range){range=document.createRange();range.selectNodeContents(body);range.collapse(false)}
const nodes=Array.prototype.slice.call(frag.childNodes)
if(!nodes.length)return
if(!hasBlock){
range.deleteContents()
range.insertNode(frag)
const last=nodes[nodes.length-1]
const r=document.createRange();r.setStartAfter(last);r.collapse(true)
const sel=window.getSelection();sel.removeAllRanges();sel.addRange(r)
notesState.savedRange=r.cloneRange()
}else{
const at=notesProEl(range.startContainer)
const callout=at?at.closest(".note-callout"):null
const cont=callout&&body.contains(callout)&&callout!==at.closest("figure,.cmd-card-embed")?callout:body
let top=range.startContainer===cont?(cont.childNodes[range.startOffset-1]||null):range.startContainer
while(top&&top.parentNode!==cont)top=top.parentNode
if(top){
const empty=top.nodeType===1&&top.matches("p,div")&&!top.textContent.trim()&&!top.querySelector("img,figure,table,hr,.cmd-card-embed")
let ref=top
nodes.forEach((n)=>{ref.after(n);ref=n})
if(empty)top.remove()
}else{
const first=cont.firstChild
nodes.forEach((n)=>cont.insertBefore(n,first))
}
const last=nodes[nodes.length-1]
if(!last.nextSibling)last.after(notesProEmptyPara())
if(last.nodeType===1&&last.matches("p,h3,h4,blockquote,li"))notesProCaretInto(last,true)
else notesProCaretInto(last.nextSibling&&last.nextSibling.nodeType===1?last.nextSibling:body,false)
}
loadImages(body)
notesMarkDirty()
notesProAfterStructureChange()
}
function insertHTML(html){
if(destroyed)return
if(srcMode){insertSource(RC.htmlToMarkdown(RC.sanitizeHtml(html)),true);return}
activate()
const extra={}
const frag=toEditable(html,extra)
Object.assign(notesState.cmdCards,extra)
insertFragment(frag)
}
function insertNodeInline(node){
focusBody()
notesProLeaveIsland()
notesInsertNodeAtCursor(node)
const sp=document.createTextNode(" ")
node.after(sp)
notesProSetCaret(sp,1)
}
function linkDialog(){
focusBody()
const saved=notesState.savedRange?notesState.savedRange.cloneRange():null
const cur=saved?notesProEl(saved.startContainer):null
const a=cur?cur.closest("a"):null
RW.ask({title:a?"Edit link":"Insert link",fields:[{key:"url",label:"Address",value:a?a.getAttribute("href")||"":"",placeholder:"https://example.com"},{key:"text",label:"Text",value:a?a.textContent:(saved&&!saved.collapsed?saved.toString():"")}],okLabel:a?"Save":"Insert",validate:(v)=>{
const u=normaliseUrl(v.url)
return u||!v.url.trim()?"":"Use an http://, https:// or mailto: address."
}}).then((v)=>{
if(!v||destroyed)return
const url=normaliseUrl(v.url)
activate()
if(a&&body.contains(a)){
if(!url){unwrap(a)}else{a.setAttribute("href",url);if(v.text.trim())a.textContent=v.text}
notesMarkDirty();return
}
if(!url)return
if(saved)notesState.savedRange=saved
const link=document.createElement("a")
link.setAttribute("href",url)
link.textContent=v.text.trim()||url
insertNodeInline(link)
})
}
function normaliseUrl(v){
v=String(v||"").trim()
if(!v)return ""
if(/^(https?:\/\/|mailto:)\S+$/i.test(v))return v
if(/^[\w.-]+@[\w.-]+\.\w+$/.test(v))return "mailto:"+v
if(/^[\w-]+(\.[\w-]+)+(\/\S*)?$/.test(v))return "https://"+v
return ""
}
function wrapInline(tag,cls,msg){
focusBody()
const range=notesProSel()
if(!range)return
const inside=notesProInside(range,cls?tag+"."+cls:tag)
if(inside&&body.contains(inside)){unwrap(inside);notesMarkDirty();return}
if(range.collapsed){RW.toast(msg,true);return}
const n=document.createElement(tag)
if(cls)n.className=cls
n.textContent=range.toString()
range.deleteContents()
range.insertNode(n)
const after=document.createTextNode(" ")
n.after(after)
notesProSetCaret(after,1)
notesMarkDirty()
}
function styleMenu(anchor){
const r=anchor.getBoundingClientRect()
const items=[
{label:"Paragraph",fn:()=>{activate();notesProFormatBlock("p")}},
// notesProFormatBlock maps the tag through the host (tags: h1 -> h3, h3 -> h4), so the Notes names are passed here.
{label:"Heading",fn:()=>{activate();notesProFormatBlock("h1")}},
{label:"Sub-heading",fn:()=>{activate();notesProFormatBlock("h3")}},
{label:"Quote",fn:()=>{activate();notesProFormatBlock("blockquote")}},
{sep:true},
{label:"Code block",fn:()=>{activate();notesProInsertCode("")}},
{label:"Checklist",fn:()=>{activate();notesProInsertChecklist(false)}}
]
if(!compact)items.push({sep:true},{label:"Show / hide outline",icon:"list",fn:()=>{activate();notesProToggleOutline()}})
const cur=styleName()
items.forEach((it)=>{if(it.label&&it.label===(cur==="Normal"?"Paragraph":cur))it.icon="check"})
openContextMenu(items,r.left,r.bottom+4)
}
function pickEvidence(){
const saved=notesState.savedRange?notesState.savedRange.cloneRange():null
const ev=window.ReportEvidence
if(!ev||typeof ev.pick!=="function"){RW.toast("The evidence library is not available yet.",true);return}
Promise.resolve(ev.pick({multiple:true})).then((list)=>{
if(destroyed||!list||!list.length)return
activate()
if(saved)notesState.savedRange=saved
insertHTML(list.map((e)=>RC.evidenceFigureHtml(e)).join(""))
}).catch((err)=>RW.toast(RW.errText(err,"Evidence could not be loaded."),true))
}
function pickFinding(){
const rep=currentReport()
const list=rep&&Array.isArray(rep.findings)?rep.findings:[]
if(!rep){RW.toast("Open a report to reference its findings.",true);return}
if(!list.length){RW.toast("This report has no findings yet.",true);return}
const saved=notesState.savedRange?notesState.savedRange.cloneRange():null
const prefix=(rep.options&&rep.options.finding_id_prefix)||"F-"
const box=el("div","rpt-pick")
const search=el("input","rpt-input")
search.type="text"
search.placeholder="Search findings..."
const rows=el("div","rpt-pick-list")
box.appendChild(search)
box.appendChild(rows)
let m=null
const paint=()=>{
const q=search.value.trim().toLowerCase()
rows.innerHTML=""
list.forEach((f,i)=>{
const num=RC.findingNumber(prefix,i)
if(q&&(num+" "+(f.title||"")).toLowerCase().indexOf(q)<0)return
const b=el("button","rpt-pick-item")
b.type="button"
b.innerHTML=RW.severityBadge(f.severity)+`<span class="rpt-pick-num">${esc(num)}</span><span class="rpt-pick-title">${esc(f.title||"Untitled finding")}</span>`
b.addEventListener("click",()=>{
m.close()
if(destroyed)return
activate()
if(saved)notesState.savedRange=saved
const s=document.createElement("span")
s.className="rpt-fref"
s.setAttribute("data-finding",f.uid||"")
s.contentEditable="false"
s.textContent=num+" "+(f.title||"Untitled finding")
insertNodeInline(s)
})
rows.appendChild(b)
})
if(!rows.firstChild)rows.appendChild(el("div","rpt-pick-empty","No findings match"))
}
search.addEventListener("input",paint)
search.addEventListener("keydown",(e)=>{if(e.key==="Enter"){e.preventDefault();const first=rows.querySelector(".rpt-pick-item");if(first)first.click()}})
m=RW.modal({title:"Reference a finding",bodyEl:box,buttons:[{label:"Close"}]})
paint()
setTimeout(()=>search.focus(),60)
}
let phCache=null
function placeholderMenu(anchor){
const saved=notesState.savedRange?notesState.savedRange.cloneRange():null
const r=anchor.getBoundingClientRect()
const open=(list)=>{
if(destroyed)return
if(!list.length){RW.toast("No placeholders are defined.",true);return}
openContextMenu(list.map((p)=>({label:p.token+"  "+(p.label||""),fn:()=>{
const token=String(p.token||"").replace(/[{}\s]/g,"")
if(!/^[a-z_]{1,40}$/.test(token))return
activate()
if(saved)notesState.savedRange=saved
const s=document.createElement("span")
s.className="rpt-ph"
s.setAttribute("data-token",token)
s.contentEditable="false"
s.textContent="{{"+token+"}}"
insertNodeInline(s)
}})),r.left,r.bottom+4)
}
if(phCache){open(phCache);return}
bridgeCall("reports.placeholders",[]).then((list)=>{phCache=Array.isArray(list)?list:[];open(phCache)}).catch((err)=>RW.toast(RW.errText(err,"Placeholders could not be loaded."),true))
}
// A value of one of the report's linked targets: a reference chip that takes the link's current value again on every save, preview
// and export, or (the picker's "plain text" box) just the text as it is now.
function pickTargetValue(){
const rep=currentReport(),T=targetsApi()
if(!rep||!T){RW.toast("Open a report to insert target values.",true);return}
const saved=notesState.savedRange?notesState.savedRange.cloneRange():null
T.pickValue(rep).then((v)=>{
if(destroyed||!v)return
activate()
if(saved)notesState.savedRange=saved
if(v.plain||!/^[A-Za-z0-9_\-]{1,64}$/.test(v.uid)||!T.KEY_RX.test(v.key)){insertNodeInline(document.createTextNode(v.value));return}
const s=document.createElement("span")
s.className="rpt-tv"
s.setAttribute("data-target",v.uid)
s.setAttribute("data-key",v.key)
s.contentEditable="false"
s.textContent=v.value
insertNodeInline(s)
refreshTv(body)
}).catch((err)=>RW.toast(RW.errText(err,"The target value could not be inserted."),true))
}
function widgetMenu(anchor){
const saved=notesState.savedRange?notesState.savedRange.cloneRange():null
const r=anchor.getBoundingClientRect()
openContextMenu(WIDGETS.map((w)=>({label:w.label,fn:()=>{
activate()
if(saved)notesState.savedRange=saved
const d=document.createElement("div")
d.className="rpt-widget"
d.setAttribute("data-widget",w.id)
d.contentEditable="false"
notesProInsertBlock(d,null)
}})),r.left,r.bottom+4)
}
function commandsTable(){
const rep=currentReport()
const saved=notesState.savedRange?notesState.savedRange.cloneRange():null
const flt={kind:"command",limit:500}
if(rep&&rep.profile_id)flt.profile_id=rep.profile_id
bridgeCall("evidence.list",[flt]).then((list)=>{
if(destroyed)return
const rows=(Array.isArray(list)?list:[]).filter((e)=>String(e.command||"").trim())
if(!rows.length){RW.toast("No captured commands for this engagement yet. Save terminal jobs as evidence first.",true);return}
rows.sort((a,b)=>String(a.started_at||a.created_at||"").localeCompare(String(b.started_at||b.created_at||"")))
const cell=(t,tag)=>"<"+(tag||"td")+">"+esc(t)+"</"+(tag||"td")+">"
const html='<table class="note-table"><thead><tr>'+cell("Time (UTC)","th")+cell("Target","th")+cell("Command","th")+cell("Exit","th")+"</tr></thead><tbody>"+rows.map((e)=>"<tr>"+cell(RC.fmtUtc?RC.fmtUtc(e.started_at||e.created_at):String(e.started_at||e.created_at||""))+cell(e.target||"")+"<td><code>"+esc(String(e.command).slice(0,600))+"</code></td>"+cell(e.exit_code===null||e.exit_code===undefined?"":String(e.exit_code))+"</tr>").join("")+"</tbody></table>"
activate()
if(saved)notesState.savedRange=saved
insertHTML(html)
RW.toast("Inserted "+rows.length+" command"+(rows.length===1?"":"s"))
}).catch((err)=>RW.toast(RW.errText(err,"The captured commands could not be loaded."),true))
}
function setSource(on){
on=!!on
if(on===srcMode||destroyed)return
if(on){
activate()
notesProSlashClose()
notesProSetHover(null,null)
src.value=RC.htmlToMarkdown(fromEditable(body,cards()))
src.style.height=Math.max(160,Math.min(body.offsetHeight+24,Math.round(window.innerHeight*0.6)))+"px"
srcMode=true
}else{
const html=RC.markdownToHtml(src.value,mdLib())
srcMode=false
loadBody(html)
}
root.classList.toggle("rpt-rich-source",srcMode)
main.classList.toggle("hidden",srcMode)
src.classList.toggle("hidden",!srcMode)
Object.keys(btns).forEach((id)=>{if(id!=="md"&&id!=="mdImport")btns[id].disabled=srcMode})
btns.md.classList.toggle("active",srcMode)
btns.md.setAttribute("aria-pressed",srcMode?"true":"false")
if(srcMode){
src.focus()
src.setSelectionRange(0,0)
src.scrollTop=0
}else{
body.focus()
syncState()
}
}
function insertSource(text,block){
text=String(text||"").replace(/\r\n?/g,"\n")
if(!text)return
const a=src.selectionStart||0,b=src.selectionEnd||0
const head=src.value.slice(0,a),tail=src.value.slice(b)
if(block)text=(head&&!/\n\n$/.test(head)?(/\n$/.test(head)?"\n":"\n\n"):"")+text.replace(/\n+$/,"")+(tail&&!/^\n\n/.test(tail)?(/^\n/.test(tail)?"\n":"\n\n"):"")
src.value=head+text+tail
const at=head.length+text.length
src.focus()
src.setSelectionRange(at,at)
changed()
}
function importMarkdown(){
const saved=!srcMode&&notesState.savedRange?notesState.savedRange.cloneRange():null
const input=el("input","rpt-offscreen")
input.type="file"
input.accept=".md,.markdown,.txt,text/markdown,text/plain"
document.body.appendChild(input)
input.addEventListener("change",()=>{
const f=input.files&&input.files[0]
input.remove()
if(!f||destroyed)return
if(f.size>MD_FILE_MAX){RW.toast("The file is larger than 2 MB.",true);return}
const fr=new FileReader()
fr.onerror=()=>RW.toast("The file could not be read.",true)
fr.onload=()=>{
if(destroyed)return
const text=String(fr.result||"").replace(/^﻿/,"").replace(/\u0000/g,"")
if(!text.trim()){RW.toast("That file is empty.",true);return}
if(srcMode)insertSource(text,true)
else{
const L=mdLib()
const asMd=L&&(/\.(md|markdown)$/i.test(f.name||"")||L.looksLikeMarkdown(text))
activate()
if(saved)notesState.savedRange=saved
insertHTML(asMd?RC.markdownToHtml(text,L):plainToHtml(text))
}
RW.toast("Imported "+(f.name||"file"))
}
fr.readAsText(f)
})
input.click()
window.addEventListener("focus",()=>setTimeout(()=>{if(input.isConnected&&!(input.files&&input.files.length))input.remove()},1500),{once:true})
}
const api2={
styleMenu:styleMenu,linkDialog:linkDialog,fileInput:fileInput,
inlineCode:()=>wrapInline("code","","Select the text to format as code first."),
toggleRedact:()=>wrapInline("span","rpt-redact","Select the text to redact first."),
pickFinding:pickFinding,pickEvidence:pickEvidence,placeholderMenu:placeholderMenu,pickTargetValue:pickTargetValue,widgetMenu:widgetMenu,commandsTable:commandsTable,
runAI:()=>{flush();if(aiOn())opts.onAI(api)},
setSource:setSource,isSource:()=>srcMode,importMarkdown:importMarkdown
}
fileInput.addEventListener("change",()=>{
const files=Array.prototype.slice.call(fileInput.files||[])
fileInput.value=""
if(!files.length||destroyed)return
activate()
notesAttachmentAccept(files,null)
})
body.addEventListener("focus",()=>root.classList.add("focused"))
body.addEventListener("blur",()=>{root.classList.remove("focused");flush()})
body.addEventListener("input",()=>{syncEmpty();syncState()})
body.addEventListener("keydown",(e)=>{
if(!registry&&(e.ctrlKey||e.metaKey)&&!e.altKey&&!e.shiftKey&&(e.key||"").toLowerCase()==="k"){e.preventDefault();linkDialog()}
})
body.addEventListener("keyup",syncState)
body.addEventListener("mouseup",syncState)
// A paste never lands inside a non-editable block (command card, figure, widget, reference chip): the caret moves to the line after it first.
// WebKitGTK gives a pasted screenshot no files on the paste event; the async Clipboard API has it.
body.addEventListener("paste",(e)=>{
const r=notesProSel()
const at=r?notesProEl(r.startContainer):null
const island=at?at.closest(".cmd-card-embed,figure,.rpt-widget,.rpt-fref,.rpt-ph,.rpt-tv"):null
if(island&&body.contains(island)){
let top=island
while(top.parentNode!==body&&top.parentNode&&!top.parentNode.matches(".note-callout,td,th,li"))top=top.parentNode
let next=top.nextSibling
if(island.matches(".rpt-fref,.rpt-ph,.rpt-tv")){const t=document.createTextNode("\u200b");island.after(t);notesProSetCaret(t,1)}
else{
if(!next||next.nodeType!==1||!next.matches("p,div")){next=notesProEmptyPara();top.after(next)}
notesProCaretInto(next,false)
}
}
const cd=e.clipboardData
if(!cd||!navigator.clipboard||typeof navigator.clipboard.read!=="function")return
if((cd.files&&cd.files.length)||cd.getData("text/plain")||cd.getData("text/html"))return
e.preventDefault()
e.stopImmediatePropagation()
navigator.clipboard.read().then((items)=>Promise.all(items.map((it)=>{
const type=IMG_TYPES.find((t)=>it.types.indexOf(t)>=0)
return type?it.getType(type).then((blob)=>new File([blob],"pasted-"+Date.now()+"."+type.split("/")[1],{type:type})):null
}))).then((files)=>{
files=files.filter(Boolean)
if(!files.length||destroyed)return
activate()
notesAttachmentAccept(files,null)
}).catch(()=>{})
},true)
// Dropped files that are not images never reach the shared handler (a report holds images only).
body.addEventListener("drop",(e)=>{
const files=e.dataTransfer&&e.dataTransfer.files?Array.prototype.slice.call(e.dataTransfer.files):[]
if(files.length&&files.some((f)=>IMG_TYPES.indexOf(f.type)<0)){e.preventDefault();e.stopImmediatePropagation();RW.toast("Only PNG, JPEG, GIF and WebP images can be added to a report.",true)}
},true)
// Edits made by the shared editor after a pause (popover choices, drags) also reach onChange.
if(typeof MutationObserver!=="undefined"){
observer=new MutationObserver(()=>changed())
observer.observe(body,{childList:true,characterData:true,subtree:true,attributes:true,attributeFilter:["data-checked","data-callout","data-sev","data-cvss","data-lang","data-shapes","data-collapsed","data-attachment-id","style","href"]})
}
src.addEventListener("input",changed)
src.addEventListener("focus",()=>root.classList.add("focused"))
src.addEventListener("blur",()=>{root.classList.remove("focused");flush()})
src.addEventListener("keydown",(e)=>{
// Tab indents (nested lists need it); Escape still reaches the dialog the editor sits in.
if(e.key!=="Tab"||e.shiftKey||e.ctrlKey||e.metaKey||e.altKey)return
e.preventDefault()
const a=src.selectionStart,b=src.selectionEnd
src.value=src.value.slice(0,a)+"  "+src.value.slice(b)
src.setSelectionRange(a+2,a+2)
changed()
})
const onPageShown=()=>syncAI()
document.addEventListener("loya:page-shown",onPageShown)
// The chips are rewritten in place without becoming an edit: the server stores the same text when the links change.
const onLinks=(links)=>{
if(destroyed||srcMode)return
const pending=changeTimer!==null
if(pending)flush()
if(refreshTv(body,links)){if(observer)observer.takeRecords();lastHtml=getHTML()}
}
liveEditors.push(onLinks)
function setHTML(html){
if(changeTimer){clearTimeout(changeTimer);changeTimer=null}
if(srcMode){src.value=RC.htmlToMarkdown(html||"");lastHtml=getHTML();return}
loadBody(html)
if(observer)observer.takeRecords()
lastHtml=getHTML()
}
const api={
el:root,body:body,source:src,host:ed,
getHTML:getHTML,
setHTML:setHTML,
focus:()=>{if(srcMode){src.focus();return}focusBody()},
insertHTML:insertHTML,
isEmpty:()=>getHTML()==="",
isSource:()=>srcMode,
setSource:setSource,
flush:flush,
isPending:()=>changeTimer!==null,
refreshAI:syncAI,
destroy:()=>{
if(destroyed)return
flush()
destroyed=true
if(observer)observer.disconnect()
{const li=liveEditors.indexOf(onLinks);if(li>=0)liveEditors.splice(li,1)}
if(styleObs)styleObs.disconnect()
if(regBar&&typeof notesEdUnmountToolbar==="function")notesEdUnmountToolbar(regBar)
document.removeEventListener("loya:page-shown",onPageShown)
notesHostUnmount(ed)
root.remove()
}
}
syncAI()
setHTML(opts.html||"")
return api
}
// Read-only rendering of stored rich HTML (library preview, AI review): sanitised, images resolved from the asset store.
function render(container,html){
container.classList.add("rpt-rich-view","note-body")
const tpl=document.createElement("template")
tpl.innerHTML=RC.sanitizeHtml(html||"")
tpl.content.querySelectorAll("img").forEach((img)=>{
const m=/^rptasset:(.+)$/.exec(img.getAttribute("src")||"")
img.removeAttribute("src")
if(m)img.dataset.attachmentId=m[1]
})
tpl.content.querySelectorAll("pre").forEach((pre)=>{if(!pre.closest("figure"))pre.classList.add("note-code")})
applyData(tpl.content)
container.innerHTML=""
container.appendChild(tpl.content)
loadImages(container)
container.querySelectorAll("a").forEach((a)=>a.addEventListener("click",(e)=>e.preventDefault()))
return container
}
return {create:create,render:render,assetUrl:assetUrl,pickImages:pickImages,uploadFile:uploadFile,cleanPasted:cleanPasted,plainToHtml:plainToHtml,toEditable:toEditable,fromEditable:fromEditable,refreshTargetValues:refreshTargetValues}
})()
if(typeof window!=="undefined")window.ReportRich=ReportRich
