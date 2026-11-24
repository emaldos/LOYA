// CVE Intel inside Notes: the "CVE" editor command (insert a CVE as a vulnerability callout) and the viewer's CVE-id links.
// Everything in a CVE record is remote text: it is escaped here, links are https only, and the callout is sanitised again by notesProFragment before it reaches the editor.
// The pure part is also loaded by tests/js/cve_notes.js through require().
const CVE_NOTES_ID_RE=/CVE-\d{4}-\d{4,7}(?!\d)/gi
const CVE_NOTES_SEVERITIES=["critical","high","medium","low","info"]
const CVE_NOTES_MAX_REFS=15
const CVE_NOTES_MAX_AFFECTED=8
function cveNotesEsc(s){
return String(s===undefined||s===null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")
}
function cveNotesIds(text){
const out=[]
const seen=new Set()
const m=String(text===undefined||text===null?"":text).match(CVE_NOTES_ID_RE)||[]
m.forEach((x)=>{const id=x.toUpperCase();if(!seen.has(id)){seen.add(id);out.push(id)}})
return out
}
// "see CVE-2021-44228 now" -> [{t:"see "},{cve:"CVE-2021-44228"},{t:" now"}]. An id glued to a word (xCVE-..., CVE-...x) is left alone.
function cveNotesSegments(text){
const s=String(text===undefined||text===null?"":text)
const out=[]
const re=new RegExp(CVE_NOTES_ID_RE.source,"gi")
let last=0,m
while((m=re.exec(s))!==null){
const before=m.index>0?s[m.index-1]:""
const after=s[m.index+m[0].length]||""
if(/[A-Za-z0-9_-]/.test(before)||/[A-Za-z_]/.test(after))continue
if(m.index>last)out.push({t:s.slice(last,m.index)})
out.push({cve:m[0].toUpperCase(),raw:m[0]})
last=m.index+m[0].length
}
if(last<s.length)out.push({t:s.slice(last)})
return out
}
function cveNotesHttps(url){
const u=String(url===undefined||url===null?"":url).trim()
return /^https:\/\/[^\s<>"'`\\]+$/i.test(u)?u:""
}
function cveNotesSeverity(v){
const k=String(v||"").trim().toLowerCase()
return CVE_NOTES_SEVERITIES.includes(k)?k:"info"
}
function cveNotesDay(v){
const s=String(v||"")
return /^\d{4}-\d{2}-\d{2}/.test(s)?s.slice(0,10):s.slice(0,40)
}
function cveNotesScore(v){
const n=typeof v==="number"?v:parseFloat(v)
return isNaN(n)||n<0||n>10?"":(Math.round(n*10)/10).toFixed(1)
}
function cveNotesPct(v){
const n=typeof v==="number"?v:parseFloat(v)
return isNaN(n)?"":(n*100).toFixed(n*100<10?2:1)+"%"
}
function cveNotesLink(url,label){
const u=cveNotesHttps(url)
const text=cveNotesEsc(label||url)
return u?`<a href="${cveNotesEsc(u)}">${text}</a>`:text
}
function cveNotesList(items){
return items.length?"<ul>"+items.map((x)=>"<li>"+x+"</li>").join("")+"</ul>":""
}
// A CVE record (see cve.lookup) as note HTML. Uses only the note's own block markup, so both sanitisers keep it as it is.
function cveNotesCalloutHtml(record){
const r=record&&typeof record==="object"?record:{}
const E=cveNotesEsc
const arr=(v)=>Array.isArray(v)?v:[]
const sev=cveNotesSeverity(r.severity)
const cvss=r.cvss&&typeof r.cvss==="object"?r.cvss:{}
const top=cveNotesScore(r.score)
const row=(k,v)=>v?`<tr><th>${E(k)}</th><td>${v}</td></tr>`:""
const id=E(String(r.id||"").toUpperCase())
const title=String(r.title||"").trim()
const head=id+(title&&title.toUpperCase()!==String(r.id||"").toUpperCase()?": "+E(title):"")
const vectors=[["v40","CVSS 4.0"],["v31","CVSS 3.1"],["v2","CVSS 2.0"]].map(([k,label])=>{
const c=cvss[k]
if(!c||typeof c!=="object")return ""
const sc=cveNotesScore(c.score)
return `${E(label)}: ${sc?"<strong>"+sc+"</strong> ":""}${c.severity?"("+E(c.severity)+") ":""}${c.vector?"<code>"+E(c.vector)+"</code>":""}`
}).filter(Boolean).join("<br>")
const cwes=arr(r.cwes).map((c)=>c&&typeof c==="object"?E(c.id)+(c.name?" - "+E(c.name):""):E(c)).filter(Boolean).join("<br>")
const epss=r.epss&&typeof r.epss==="object"&&cveNotesPct(r.epss.score)?`${cveNotesPct(r.epss.score)} chance of exploitation in the next 30 days${cveNotesPct(r.epss.percentile)?" (percentile "+cveNotesPct(r.epss.percentile)+")":""}${r.epss.date?", "+E(cveNotesDay(r.epss.date)):""}`:""
const kev=r.kev&&typeof r.kev==="object"&&r.kev.in_kev?r.kev:null
const kevText=kev?`<strong>Known exploited</strong>${kev.date_added?" - added "+E(cveNotesDay(kev.date_added)):""}${kev.due_date?", due "+E(cveNotesDay(kev.due_date)):""}${kev.ransomware?", ransomware use: "+E(kev.ransomware):""}`:(r.kev===null&&!r.partial?"Not in the CISA KEV catalog":"")
const dates=[r.published?"Published "+E(cveNotesDay(r.published)):"",r.modified?"last modified "+E(cveNotesDay(r.modified)):""].filter(Boolean).join(", ")
const affected=arr(r.affected)
const total=Math.max(parseInt(r.affected_total,10)||0,affected.length)
const affLines=affected.slice(0,CVE_NOTES_MAX_AFFECTED).map((a)=>a&&typeof a==="object"?E([a.vendor,a.product,a.versions].filter(Boolean).join(" ")):E(a)).filter(Boolean)
if(total>affLines.length&&affLines.length)affLines.push("and "+(total-affLines.length)+" more")
const table=row("Severity",E(sev.charAt(0).toUpperCase()+sev.slice(1))+(top?" ("+top+")":""))+row("CVSS",vectors)+row("CWE",cwes)+row("EPSS",epss)+row("CISA KEV",kevText)+row("Dates",dates)+row("Affected",affLines.join("<br>"))
// ---- how to protect yourself: what the vendor / CISA say first, generic weakness-class advice last and labelled as such.
const p=r.protect&&typeof r.protect==="object"?r.protect:{}
let protect=""
const act=p.kev_action&&typeof p.kev_action==="object"?p.kev_action:null
if(act&&act.text)protect+=`<p><strong>CISA KEV required action</strong>${act.due_date?" (due "+E(cveNotesDay(act.due_date))+")":""}: ${E(act.text)}</p>`
const vendor=arr(p.vendor).filter((v)=>v&&cveNotesHttps(v.url))
if(vendor.length)protect+=`<p><strong>Vendor guidance</strong> (patches and advisories from the vendor or official sources):</p>`+cveNotesList(vendor.slice(0,10).map((v)=>cveNotesLink(v.url)+(arr(v.tags).length?" <em>("+E(arr(v.tags).join(", "))+")</em>":"")))
else protect+=`<p><strong>Vendor guidance</strong>: no vendor patch or advisory link is listed for this CVE yet. Check the vendor's site and the references below.</p>`
arr(p.generic).forEach((g)=>{
if(!g||typeof g!=="object")return
const mit=arr(g.mitigations).map((x)=>E(x))
const det=arr(g.detection).map((x)=>E(x))
if(!mit.length&&!det.length)return
protect+=`<p><strong>Generic guidance (${E(g.cwe||"weakness class")}${g.name?" - "+E(g.name):""}, not specific to this product)</strong></p>`
if(mit.length)protect+="<p>Mitigation:</p>"+cveNotesList(mit)
if(det.length)protect+="<p>Detection:</p>"+cveNotesList(det)
})
// ---- references: the online pages first, then the record's own; only https becomes a link.
const links=r.links&&typeof r.links==="object"?r.links:{}
const refs=[]
const seen=new Set()
const addRef=(url,label,tags)=>{
const u=cveNotesHttps(url)
if(!u||seen.has(u))return
seen.add(u)
refs.push(cveNotesLink(u,label||u)+(tags&&tags.length?" <em>("+E(tags.join(", "))+")</em>":""))
}
addRef(links.cve_org,"CVE.org record")
addRef(links.nvd,"NVD detail page")
if(kev)addRef(links.kev,"CISA Known Exploited Vulnerabilities catalog")
const fixed=refs.length
let hidden=0
arr(r.references).forEach((ref)=>{
if(!ref||typeof ref!=="object")return
if(refs.length-fixed>=CVE_NOTES_MAX_REFS){hidden++;return}
if(cveNotesHttps(ref.url))addRef(ref.url,"",arr(ref.tags))
else if(ref.plain||ref.url)refs.push(E(ref.plain||ref.url)+" <em>(not https, not linked)</em>")
})
if(hidden)refs.push(hidden+" more on NVD")
const sources=arr(r.sources).length?arr(r.sources).map((s)=>E(s)).join(" / "):"NVD / CISA KEV / FIRST EPSS"
const foot=`<p><small>Source: ${sources}${r.fetched_at?" - fetched "+E(cveNotesDay(r.fetched_at)):""}. CVE data is third-party text; check the linked pages before relying on it.</small></p>`
return `<div class="note-callout note-finding" data-callout="vuln" data-sev="${sev}"${top?` data-cvss="${top}"`:""}><h3>${head||"CVE"}</h3>${table?`<table class="note-table note-table-head"><tbody>${table}</tbody></table>`:""}<h4>Description</h4><p>${E(r.description)||"<br>"}</p><h4>How to protect yourself</h4>${protect}${refs.length?"<h4>References</h4>"+cveNotesList(refs):""}${foot}</div>`
}
// ---------------------------------------------------------------- editor: insert a CVE callout
function cveNotesInsertAt(record,range){
notesEdBody().focus()
if(range){notesEdCollapseAfter(range);notesRestoreRange()}
notesProLeaveIsland()
const frag=notesProFragment(cveNotesCalloutHtml(record),"render")
const div=frag.firstElementChild
if(!div)return false
notesProInsertBlock(div,div.querySelector("h3"))
notesMarkDirty()
return true
}
function cveNotesError(err){
const msg=err&&err.message?String(err.message):"The CVE could not be loaded."
return /bridge method missing/.test(msg)?"CVE Intel is not available in this build.":msg
}
function cveNotesOpenInsert(ctx){
const range=ctx&&ctx.range?ctx.range.cloneRange():null
const preset=cveNotesIds(ctx&&ctx.hasSel?ctx.text:"")[0]||""
const pop=notesEdPop("pt.cve",380,"Insert CVE")
const input=notesEdInput("CVE-2021-44228, or search the saved CVEs",preset)
input.className="notes-popover-search"
pop.appendChild(input)
const list=notesEdEl("div","notes-popover-list")
pop.appendChild(list)
const status=notesEdEl("p","notes-ed-cve-status","")
pop.appendChild(status)
pop.appendChild(notesEdEl("p","notes-pro-hint","Inserts severity, CVSS, KEV, EPSS, how to protect yourself and references as a vulnerability callout. Saved CVEs work offline; a new one is fetched only when online lookups are on in Settings > CVE Intel."))
let rows=[],index=-1,busy=false,seq=0
const say=(msg,isError)=>{status.textContent=msg||"";status.classList.toggle("error",!!isError)}
const mark=()=>rows.forEach((r,i)=>{r.el.classList.toggle("active",i===index);if(i===index)r.el.scrollIntoView({block:"nearest"})})
const insert=(id)=>{
const cve=cveNotesIds(id||input.value)[0]
if(busy)return
if(!cve){say("Type a CVE id like CVE-2021-44228, or pick one from the list.",true);return}
busy=true
say("Loading "+cve+"...")
bridgeCall("cve.lookup",[cve,false]).then((rec)=>{
busy=false
if(!document.body.contains(pop))return
notesClosePopover()
if(cveNotesInsertAt(rec,range))showToast(cve+" inserted"+(rec&&rec.origin==="cache"?" (from the saved copy)":""))
}).catch((err)=>{busy=false;say(cveNotesError(err),true)})
}
const render=(results)=>{
list.innerHTML=""
rows=[]
;(results||[]).forEach((s)=>{
if(!s||!cveNotesIds(s.id).length)return
const b=notesEdEl("button","notes-ed-cve-row")
b.type="button"
b.appendChild(notesEdEl("span","notes-ed-cve-id",s.id))
b.appendChild(notesEdEl("span","notes-ed-cve-sev",cveNotesSeverity(s.severity)+(cveNotesScore(s.score)?" "+cveNotesScore(s.score):"")))
b.appendChild(notesEdEl("span","notes-ed-cve-title",s.title||s.description||""))
b.addEventListener("click",()=>insert(s.id))
list.appendChild(b)
rows.push({id:s.id,el:b})
})
index=-1
}
const search=()=>{
const q=input.value.trim()
const mine=++seq
if(!q){render([]);return}
bridgeCall("cve.search",[q,8]).then((res)=>{if(mine===seq&&document.body.contains(pop))render(res&&res.results)}).catch(()=>{if(mine===seq)render([])})
}
input.addEventListener("input",()=>{say("");search()})
input.addEventListener("keydown",(e)=>{
if(e.key==="ArrowDown"||e.key==="ArrowUp"){e.preventDefault();if(rows.length){index=(index+(e.key==="ArrowDown"?1:-1)+rows.length)%rows.length;mark()}}
else if(e.key==="Enter"){e.preventDefault();insert(rows[index]?rows[index].id:"")}
})
notesEdActions(pop,[{label:"Cancel",fn:notesClosePopover},{label:"Insert",primary:true,fn:()=>insert(rows[index]?rows[index].id:"")}])
search()
notesProFocusSoon(input)
}
// For the CVE Intel page's "Insert into note" button: puts the callout at the caret of the note that is open in the editor.
function cveNotesInsertRecord(record){
if(!record||!cveNotesIds(record.id).length)return Promise.resolve(false)
if(typeof notesEditorOpen!=="function"||!document.getElementById("notesEditor")||!notesEditorOpen()){
showToast("Open a note in the editor first, then insert the CVE.","error")
return Promise.resolve(false)
}
return Promise.resolve(typeof goToPage==="function"?goToPage("notes"):null).then(()=>{
const ok=cveNotesInsertAt(record,null)
if(ok)showToast(String(record.id).toUpperCase()+" inserted into the note")
return ok
})
}
// ---------------------------------------------------------------- viewer: CVE ids open the CVE Intel card
const CVE_NOTES_SKIP="a,code,pre,kbd,samp,script,style,textarea,button,.cmd-card,.cmd-card-embed,.note-secret,.cve-ref"
function cveLinkify(root){
if(!root||typeof document==="undefined")return 0
const w=document.createTreeWalker(root,NodeFilter.SHOW_TEXT,null)
const nodes=[]
let n
while((n=w.nextNode())){
if(!/CVE-\d{4}-\d{4}/i.test(n.nodeValue||""))continue
const p=n.parentElement
if(!p||p.closest(CVE_NOTES_SKIP))continue
nodes.push(n)
}
let count=0
nodes.forEach((node)=>{
const segs=cveNotesSegments(node.nodeValue)
if(!segs.some((s)=>s.cve))return
const frag=document.createDocumentFragment()
segs.forEach((s)=>{
if(!s.cve){frag.appendChild(document.createTextNode(s.t));return}
const span=document.createElement("span")
span.className="cve-ref"
span.setAttribute("role","link")
span.tabIndex=0
span.dataset.cve=s.cve
span.title="Open "+s.cve+" in CVE Intel"
span.textContent=s.raw
frag.appendChild(span)
count++
})
node.parentNode.replaceChild(frag,node)
})
return count
}
function cveNotesRefOpen(e){
const t=e.target&&e.target.closest?e.target.closest(".cve-ref"):null
if(!t)return
if(e.type==="keydown"&&e.key!=="Enter")return
const id=cveNotesIds(t.dataset.cve)[0]
if(!id)return
e.preventDefault()
if(typeof cveOpenDetail==="function")cveOpenDetail(id)
else if(typeof showToast==="function")showToast("CVE Intel is not available in this build.","error")
}
if(typeof document!=="undefined"){
document.addEventListener("click",cveNotesRefOpen)
document.addEventListener("keydown",cveNotesRefOpen)
}
if(typeof module!=="undefined"&&module.exports)module.exports={cveNotesEsc,cveNotesIds,cveNotesSegments,cveNotesHttps,cveNotesSeverity,cveNotesCalloutHtml}
