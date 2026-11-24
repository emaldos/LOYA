// CVE Intel page: look up CVEs (cache first, online only when the operator turned it on), the detail card with the
// "How to protect yourself" block, and the News feed with filters and the watchlist. Pure helpers live in cve_core.js (CveCore).
// Every field of a CVE record is remote text: it is only ever written through cveE() (CveCore.esc) or textContent, and links are
// https-only buttons opened in the system browser through notes.open_url - nothing here navigates the app window.
let cveState={ready:false,tab:"lookup",status:null,settings:null,ids:[],record:null,results:[],resultsTitle:"Saved CVEs",errors:[],searchTimer:null,searchSeq:0,lookupSeq:0,loading:"",affAll:false,refsAll:false,filters:null,feed:null,feedSeq:0,feedLimit:100,filterTimer:null,refreshPoll:null,unread:0,pendingId:"",searchFilters:{severity:"",kev_only:false},searchIndex:null,searchQuery:""}
const CVE_AFFECTED_FIRST=12
const CVE_REFS_FIRST=15
function cveE(s){return CveCore.esc(s)}
function cveEl(id){return document.getElementById(id)}
function cveErr(err,fallback){return err&&err.message?String(err.message):fallback}
function cveToast(msg,type){if(typeof showToast==="function")showToast(msg,type)}
function cveCall(method,args){return bridgeCall("cve."+method,args||[])}
function cveCopy(text,done){
if(!navigator.clipboard){cveToast("Clipboard is not available","error");return}
navigator.clipboard.writeText(text).then(()=>cveToast(done)).catch(()=>cveToast("Could not copy","error"))
}
function cveOpenUrl(url){
const u=CveCore.safeUrl(url)
if(!u){cveToast("Only https links can be opened","error");return}
bridgeCall("notes.open_url",[u]).catch((err)=>cveToast(cveErr(err,"Could not open the link"),"error"))
}
function cveLinkBtn(url,label,cls){
const u=CveCore.safeUrl(url)
if(!u)return ""
return `<button type="button" class="cve-link${cls?" "+cls:""}" data-cve-url="${cveE(u)}" title="${cveE(u)} - opens in your browser">${cveE(label||u)}</button>`
}
function cveSevBadge(sev,score){
const s=CveCore.normSeverity(sev)
const sc=score===undefined||score===null||score===""?"":" "+CveCore.fmtScore(score)
// No score at all (common for older CVEs in the offline index, which NVD scored but the CVE record does not): say so instead of "Info".
const label=sc===""&&s==="info"?"No score":CveCore.sevLabel(s)+sc
return `<span class="cve-badge ${CveCore.sevClass(s)}">${cveE(label)}</span>`
}
function cveKevBadge(kev){
if(!(kev===true||(kev&&kev.in_kev)))return ""
const ransom=kev&&typeof kev==="object"&&String(kev.ransomware||"").toLowerCase()==="known"
return `<span class="cve-badge cve-badge-kev" title="In the CISA Known Exploited Vulnerabilities catalog">KEV</span>${ransom?'<span class="cve-badge cve-badge-ransom" title="CISA lists known ransomware campaign use">Ransomware</span>':""}`
}
function cveSummaryOf(r){
return {id:r.id,title:r.title,description:r.description,severity:r.severity,score:r.score,kev:!!(r.kev&&r.kev.in_kev),epss:r.epss?r.epss.score:null,published:r.published,fetched_at:r.fetched_at,origin:r.origin}
}
// ---------------------------------------------------------------- status, banner
function cveLoadStatus(){
return cveCall("status").then((st)=>{cveState.status=st||{};cveRenderStatus();return st}).catch(()=>{cveState.status=cveState.status||{};cveRenderStatus()})
}
function cveRenderStatus(){
const st=cveState.status||{}
const banner=cveEl("cveBanner")
if(!banner)return
let msg=""
if(st.offline_only)msg="Offline only mode is on - showing cached data only. Nothing is sent or fetched."
else if(st.online===false)msg="Online lookups are off - showing cached data only. Turn them on in Settings to fetch CVEs from NVD, CISA KEV and EPSS."
banner.classList.toggle("hidden",!msg)
cveEl("cveBannerText").textContent=msg
const parts=[]
if(typeof st.cached==="number")parts.push(st.cached+" saved")
const ixCount=CveCore.indexCount(cveState.searchIndex,st.index)
if(ixCount)parts.push("offline index: "+CveCore.fmtCount(ixCount)+" CVEs")
if(st.kev_count)parts.push("KEV catalog: "+st.kev_count+" entries"+(st.kev_updated?", updated "+CveCore.relTime(st.kev_updated):""))
cveEl("cveHeadStatus").textContent=parts.join(" · ")
cveEl("cveNotice").textContent=st.notice||""
const rb=cveEl("cveRefreshBtn")
if(rb)rb.title=st.can_fetch?"Fetch the newest CVEs now":"Online lookups are off - nothing can be fetched"
}
function cveGoSettings(){
if(typeof goToPage!=="function")return
Promise.resolve(goToPage("settings")).then(()=>{
const tab=document.querySelector('.set-tab[data-tab="cve"]')
if(tab)tab.click()
}).catch(()=>{})
}
function cveSwitchTab(tab){
cveState.tab=tab==="news"?"news":"lookup"
document.querySelectorAll(".cve-tab").forEach((b)=>b.classList.toggle("active",b.dataset.cveTab===cveState.tab))
document.querySelectorAll(".cve-view").forEach((v)=>v.classList.toggle("hidden",v.dataset.cveView!==cveState.tab))
if(cveState.tab==="news")cveLoadFeed()
}
// ---------------------------------------------------------------- lookup
function cveRenderChips(){
const wrap=cveEl("cveChips")
wrap.innerHTML=cveState.ids.slice(0,20).map((id)=>`<button type="button" class="cve-chip" data-cve-id="${cveE(id)}" title="Look up ${cveE(id)}">${cveE(id)}</button>`).join("")+(cveState.ids.length>20?`<span class="cve-chip-more">+${cveState.ids.length-20} more (20 per lookup)</span>`:"")
cveEl("cveLookupBtn").disabled=!cveState.ids.length
cveEl("cveLookupBtn").textContent=cveState.ids.length>1?"Look up "+Math.min(20,cveState.ids.length):"Look up"
}
function cveOnSearchInput(){
const text=cveEl("cveSearchInput").value
cveState.ids=CveCore.extractIds(text)
cveRenderChips()
if(cveState.searchTimer)clearTimeout(cveState.searchTimer)
cveState.searchTimer=setTimeout(()=>cveSearchCache(text),220)
}
// Local cache only - this never touches the network, so it is safe on every keystroke.
function cveSearchCache(text){
const q=String(text||"").replace(/\s+/g," ").trim().slice(0,200)
const seq=++cveState.searchSeq
// The filters are the optional third argument; without one the plain call is used.
const f=CveCore.searchFilters(cveState.searchFilters)
cveState.searchQuery=q
return (f?cveCall("search",[q,30,f]):cveCall("search",[q,30])).then((res)=>{
if(seq!==cveState.searchSeq)return
cveState.results=(res&&Array.isArray(res.results))?res.results:[]
cveState.errors=[]
const hadIndex=CveCore.indexCount(cveState.searchIndex,null)
cveState.searchIndex=res&&res.index&&typeof res.index==="object"?res.index:null
cveState.resultsTitle=CveCore.resultsTitle(q,res,!!f)
cveRenderResults()
if(CveCore.indexCount(cveState.searchIndex,null)!==hadIndex)cveRenderStatus()
}).catch((err)=>{
if(seq!==cveState.searchSeq)return
cveState.results=[];cveState.errors=[];cveState.resultsTitle="Saved CVEs"
cveRenderResults(cveErr(err,"Could not search the saved CVEs"))
})
}
function cveRowHtml(s,opts){
const o=opts||{}
const active=cveState.record&&cveState.record.id===s.id
const epss=s.epss===undefined||s.epss===null?"":`<span class="cve-row-epss" title="EPSS: chance of exploitation in the next 30 days">EPSS ${cveE(CveCore.fmtEpss(s.epss))}</span>`
const watch=(Array.isArray(s.watch)?s.watch:[]).map((w)=>`<span class="cve-watch-chip" title="Matches your watchlist">${cveE(w)}</span>`).join("")
const kind=o.feed&&s.kind==="modified"?'<span class="cve-row-kind">modified</span>':o.feed&&s.kind==="kev"?'<span class="cve-row-kind">new in KEV</span>':""
const idx=!o.feed&&CveCore.isIndexOnly(s)
const chipIndex=idx?'<span class="cve-row-kind cve-row-index" title="From the bundled CVE index - summary only">index</span>':""
const chipState=CveCore.stateLabel(s.state)?`<span class="cve-row-kind cve-row-state">${cveE(CveCore.stateLabel(s.state))}</span>`:""
const meta=idx?[s.vendors,s.cwe].map((v)=>String(v===undefined||v===null?"":v).trim()).filter(Boolean).join(" \u00b7 "):""
const read=o.feed?`<button type="button" class="cve-row-read" data-cve-read="${s.is_read?"0":"1"}" title="${s.is_read?"Mark as unread":"Mark as read"}" aria-label="${s.is_read?"Mark as unread":"Mark as read"}"><i class="icon icon-${s.is_read?"bell":"check"}"></i></button>`:""
return `<div class="cve-row${active?" active":""}${o.feed&&!s.is_read?" unread":""}" data-cve-id="${cveE(s.id)}"${idx?' data-cve-index="1"':""} role="button" tabindex="0">
<div class="cve-row-top">${o.feed?'<span class="cve-row-dot" aria-hidden="true"></span>':""}<span class="cve-row-id">${cveE(s.id)}</span>${cveSevBadge(s.severity,s.score)}${cveKevBadge(s.kev)}${epss}${kind}${chipState}${chipIndex}<span class="cve-spacer"></span><span class="cve-row-date">${cveE(CveCore.fmtDate(s.published))}</span>${read}</div>
${o.feed&&s.vendors?`<div class="cve-row-vendors">${cveE(CveCore.clip(s.vendors,140))}</div>`:""}
${meta?`<div class="cve-row-vendors">${cveE(CveCore.clip(meta,140))}</div>`:""}
<div class="cve-row-desc">${cveE(CveCore.clip(s.description||s.title||"",o.feed?260:160))}</div>
${watch?`<div class="cve-row-watch">${watch}</div>`:""}
</div>`
}
function cveRenderResults(errorText){
const list=cveEl("cveResultsList")
if(!list)return
cveEl("cveResultsTitle").textContent=cveState.resultsTitle
const errs=cveState.errors.map((e)=>`<div class="cve-row-error"><span class="cve-row-id">${cveE(e.id)}</span><span>${cveE(e.error)}</span></div>`).join("")
if(errorText){list.innerHTML=`<div class="cve-empty">${cveE(errorText)}</div>`;return}
if(!cveState.results.length&&!errs){
const st=cveState.status||{}
list.innerHTML=`<div class="cve-empty">${cveE(CveCore.emptyResultsText(cveEl("cveSearchInput").value,CveCore.indexCount(cveState.searchIndex,st.index),!!st.can_fetch,!!CveCore.searchFilters(cveState.searchFilters)))}</div>`
return
}
list.innerHTML=errs+cveState.results.map((s)=>cveRowHtml(s)).join("")
}
function cveLookupTyped(){
const ids=cveState.ids.slice(0,20)
if(!ids.length){cveToast("No CVE ID found in the text","error");return}
if(ids.length===1){cveShowRecord(ids[0],false);return}
const seq=++cveState.lookupSeq
cveState.searchSeq++
cveState.resultsTitle="Looking up "+ids.length+" CVEs..."
cveState.results=[];cveState.errors=[]
cveRenderResults()
cveCall("lookup_many",[ids,false]).then((res)=>{
if(seq!==cveState.lookupSeq)return
const recs=(res&&Array.isArray(res.results))?res.results:[]
cveState.results=recs.map(cveSummaryOf)
cveState.errors=(res&&Array.isArray(res.errors))?res.errors:[]
cveState.resultsTitle="Lookup results ("+recs.length+" of "+ids.length+")"
if(recs.length)cveSetRecord(recs[0])
cveRenderResults()
cveLoadStatus()
}).catch((err)=>{
if(seq!==cveState.lookupSeq)return
cveState.resultsTitle="Lookup results"
cveRenderResults(cveErr(err,"Lookup failed"))
})
}
function cveShowRecord(id,refresh){
const cid=CveCore.normId(id)
if(!cid){cveToast("That is not a CVE ID","error");return Promise.resolve(null)}
const seq=++cveState.lookupSeq
cveState.loading=cid
cveRenderDetail()
return cveCall("lookup",[cid,!!refresh]).then((rec)=>{
if(seq!==cveState.lookupSeq)return rec
cveState.loading=""
cveSetRecord(rec)
cveRenderResults()
if(refresh)cveToast(rec&&rec.origin==="live"?cid+" refreshed":cid+" shown from the cache")
cveLoadStatus()
return rec
}).catch((err)=>{
if(seq!==cveState.lookupSeq)return null
cveState.loading=""
cveRenderDetail(cveErr(err,"Could not look up "+cid),cid)
return null
})
}
// An index-only row: show the summary from the bundled index. Nothing is fetched until the operator asks for the full record.
function cveShowIndex(id){
const cid=CveCore.normId(id)
if(!cid){cveToast("That is not a CVE ID","error");return Promise.resolve(null)}
const seq=++cveState.lookupSeq
cveState.loading=cid
cveRenderDetail()
return cveCall("index_get",[cid]).then((rec)=>{
if(seq!==cveState.lookupSeq)return rec
cveState.loading=""
cveSetRecord(rec)
cveRenderResults()
return rec
}).catch(()=>{
// Not in the index after all (or an older backend): fall back to the normal lookup, which explains itself.
if(seq!==cveState.lookupSeq)return null
cveState.loading=""
return cveShowRecord(cid,false)
})
}
function cveOpenRow(row){
if(!row)return
if(row.dataset.cveIndex==="1")cveShowIndex(row.dataset.cveId)
else cveShowRecord(row.dataset.cveId,false)
}
function cveSetRecord(rec){
cveState.record=rec&&rec.id?rec:null
cveState.affAll=false
cveState.refsAll=false
cveRenderDetail()
}
// ---------------------------------------------------------------- detail card
function cveCvssRow(label,m){
if(!m||!m.vector)return ""
return `<div class="cve-kv"><span class="cve-k">${cveE(label)}</span><span class="cve-v"><span class="cve-badge ${CveCore.sevClass(m.severity)}">${cveE(CveCore.fmtScore(m.score))}</span><code class="cve-vector">${cveE(m.vector)}</code>${m.source?`<span class="cve-dim">${cveE(m.source)}</span>`:""}</span></div>`
}
function cveCweChip(c){
const num=String(c&&c.id||"").match(/^CWE-(\d{1,6})$/i)
const label=cveE(c.id)+(c.name?" · "+cveE(c.name):"")
if(num)return `<button type="button" class="cve-cwe cve-link" data-cve-url="https://cwe.mitre.org/data/definitions/${num[1]}.html" title="Open the CWE definition in your browser">${label}</button>`
return `<span class="cve-cwe">${label}</span>`
}
function cveRefHtml(ref){
const kind=CveCore.refKind(ref.kind)
const tags=(Array.isArray(ref.tags)?ref.tags:[]).map((t)=>`<span class="cve-tag">${cveE(t)}</span>`).join("")
const u=CveCore.safeUrl(ref.url)
const body=u?cveLinkBtn(u,u,"cve-ref-url"):`<span class="cve-ref-plain">${cveE(ref.plain||ref.url||"")}</span><span class="cve-tag cve-tag-warn">not linked (not https)</span>`
return `<li class="cve-ref cve-ref-${kind}"><i class="icon icon-${CveCore.refIcon(kind)}" title="${cveE(CveCore.refKindLabel(kind))}"></i><div class="cve-ref-body">${body}<div class="cve-ref-tags"><span class="cve-tag cve-tag-kind">${cveE(CveCore.refKindLabel(kind))}</span>${tags}</div></div></li>`
}
function cveProtectHtml(r,summary){
const p=r.protect||{}
const out=[]
if(p.kev_action&&p.kev_action.text){
out.push(`<div class="cve-protect-part cve-protect-kev"><div class="cve-protect-label"><i class="icon icon-warning"></i>CISA KEV required action<span class="cve-protect-src">authoritative - from the CISA catalog</span></div><p class="cve-text">${cveE(p.kev_action.text)}</p><div class="cve-dim">${p.kev_action.date_added?"Added to KEV "+cveE(CveCore.fmtDate(p.kev_action.date_added)):""}${p.kev_action.due_date?" · due "+cveE(CveCore.fmtDate(p.kev_action.due_date)):""}</div></div>`)
}
const vendor=(Array.isArray(p.vendor)?p.vendor:[]).filter((v)=>CveCore.safeUrl(v.url))
// A summary from the index has no references, so "no vendor link listed" would be misleading there.
if(vendor.length||!summary)out.push(`<div class="cve-protect-part cve-protect-vendor"><div class="cve-protect-label"><i class="icon icon-shield"></i>Vendor guidance<span class="cve-protect-src">official - patches, vendor advisories and mitigations</span></div>${vendor.length?`<ul class="cve-list">${vendor.map((v)=>`<li><span class="cve-tag cve-tag-kind">${cveE(CveCore.refKindLabel(v.kind))}</span>${cveLinkBtn(v.url,v.url,"cve-ref-url")}</li>`).join("")}</ul>`:'<p class="cve-dim">No patch or vendor advisory link is listed for this CVE yet. Check the references and the vendor\'s own security page.</p>'}${p.vendor_note?`<p class="cve-dim">${cveE(p.vendor_note)}</p>`:""}</div>`)
const generic=Array.isArray(p.generic)?p.generic:[]
if(generic.length||(p.generic_note&&!summary)){
out.push(`<div class="cve-protect-part cve-protect-generic"><div class="cve-protect-label"><i class="icon icon-info"></i>Generic guidance<span class="cve-protect-src">from the weakness class - not specific to this product</span></div>${generic.map((g)=>`<div class="cve-generic"><div class="cve-generic-title">${cveE(g.cwe)}${g.name?(g.cwe?" · ":"")+cveE(g.name):""}</div>${(g.mitigations||[]).length?`<div class="cve-generic-sub">Mitigation</div><ul class="cve-list">${g.mitigations.map((m)=>`<li>${cveE(m)}</li>`).join("")}</ul>`:""}${(g.detection||[]).length?`<div class="cve-generic-sub">Detection</div><ul class="cve-list">${g.detection.map((m)=>`<li>${cveE(m)}</li>`).join("")}</ul>`:""}</div>`).join("")}${p.generic_note?`<p class="cve-dim">${cveE(p.generic_note)}</p>`:""}</div>`)
}
return out.join("")
}
function cveRenderDetail(errorText,errorId){
const box=cveEl("cveDetail")
if(!box)return
if(cveState.loading){box.innerHTML=`<div class="cve-empty"><span class="cve-spinner"></span>Looking up ${cveE(cveState.loading)}...</div>`;return}
if(errorText){
box.innerHTML=`<div class="cve-empty cve-empty-error"><div class="cve-empty-title">${cveE(errorId||"Lookup failed")}</div><div>${cveE(errorText)}</div>${errorId?`<div class="cve-actions">${cveLinkBtn("https://www.cve.org/CVERecord?id="+encodeURIComponent(errorId),"Open on cve.org","set-btn")}${cveLinkBtn("https://nvd.nist.gov/vuln/detail/"+encodeURIComponent(errorId),"Open on NVD","set-btn")}</div>`:""}</div>`
return
}
const r=cveState.record
if(!r){box.innerHTML='<div class="cve-empty"><i class="icon icon-shield"></i><div class="cve-empty-title">CVE Intel</div><div>Paste a CVE ID on the left to see its severity, exploitation status, affected products and how to protect yourself.</div></div>';return}
const cv=r.cvss||{}
const kev=r.kev&&r.kev.in_kev?r.kev:null
const links=r.links||{}
const aff=Array.isArray(r.affected)?r.affected:[]
const affShown=cveState.affAll?aff:aff.slice(0,CVE_AFFECTED_FIRST)
const affTotal=Math.max(aff.length,parseInt(r.affected_total,10)||0)
const refs=Array.isArray(r.references)?r.references:[]
const refsShown=cveState.refsAll?refs:refs.slice(0,CVE_REFS_FIRST)
const cwes=Array.isArray(r.cwes)?r.cwes:[]
const summary=CveCore.isIndexOnly(r)
const origin=r.origin==="live"?"Live":summary?"From the offline index":"From cache"
const canFetch=!!(cveState.status&&cveState.status.can_fetch)
const stateChip=CveCore.stateLabel(r.state)?`<span class="cve-badge cve-badge-plain">${cveE(CveCore.stateLabel(r.state))}</span>`:""
const summaryNote=!summary?"":canFetch?'<div class="cve-summary-note"><i class="icon icon-info"></i><span>This is the summary from the bundled offline index. The description details, affected products, references and vendor guidance are fetched on request.</span><button type="button" class="set-btn primary" data-cve-act="fetch">Fetch full details</button></div>':'<div class="cve-summary-note"><i class="icon icon-info"></i><span>Online lookups are off - this is the summary from the bundled index.</span><button type="button" class="set-btn" data-cve-act="settings">Open Settings</button></div>'
const protect=cveProtectHtml(r,summary)
const insert=typeof cveNotesInsertRecord==="function"?'<button type="button" class="set-btn" data-cve-act="insert">Insert into note</button>':""
box.innerHTML=`<div class="cve-detail-scroll">
<div class="cve-detail-head">
<div class="cve-detail-id">${cveE(r.id)}</div>
<div class="cve-detail-badges">${cveSevBadge(r.severity,r.score)}${cveKevBadge(kev)}${r.status?`<span class="cve-badge cve-badge-plain">${cveE(r.status)}</span>`:""}${stateChip}${r.partial&&!summary?'<span class="cve-badge cve-badge-plain" title="Only part of this record is saved. Refresh it online for the full record.">partial</span>':""}</div>
</div>
${r.title&&r.title!==r.id?`<div class="cve-detail-title">${cveE(r.title)}</div>`:""}
${r.warning?`<div class="cve-warning"><i class="icon icon-warning"></i><span>${cveE(r.warning)}</span></div>`:""}
${summaryNote}
${summary&&!r.description?"":`<p class="cve-text">${cveE(r.description||"No description available.")}</p>`}
<div class="cve-facts">
<div class="cve-kv"><span class="cve-k">Published</span><span class="cve-v">${cveE(CveCore.fmtDate(r.published)||"-")}${r.modified?` <span class="cve-dim">· modified ${cveE(CveCore.fmtDate(r.modified))}</span>`:""}</span></div>
${summary&&!r.epss?"":`<div class="cve-kv"><span class="cve-k">EPSS</span><span class="cve-v">${r.epss?`${cveE(CveCore.fmtEpss(r.epss))}${r.epss.date?` <span class="cve-dim">· ${cveE(CveCore.fmtDate(r.epss.date))}</span>`:""}`:'<span class="cve-dim">not available</span>'} <span class="cve-dim" title="Exploit Prediction Scoring System (FIRST): the estimated chance this CVE is exploited in the next 30 days">· chance of exploitation in 30 days</span></span></div>`}
${cveCvssRow("CVSS 4.0",cv.v40)}${cveCvssRow("CVSS 3.1",cv.v31)}${!cv.v40&&!cv.v31?cveCvssRow("CVSS 2.0",cv.v2):""}
${!cv.v40&&!cv.v31&&!cv.v2?`<div class="cve-kv"><span class="cve-k">CVSS</span><span class="cve-v cve-dim">${summary&&r.score!==undefined&&r.score!==null?cveE(CveCore.fmtScore(r.score)+(r.cvss_version?" (CVSS "+r.cvss_version+")":"")+" - the vector is in the full record"):"not scored yet"}</span></div>`:""}
<div class="cve-kv"><span class="cve-k">CWE</span><span class="cve-v cve-cwes">${cwes.length?cwes.map(cveCweChip).join(""):'<span class="cve-dim">not assigned</span>'}</span></div>
${kev?`<div class="cve-kv"><span class="cve-k">CISA KEV</span><span class="cve-v">${kev.name?cveE(kev.name)+" · ":""}${kev.date_added?"added "+cveE(CveCore.fmtDate(kev.date_added)):"in the catalog"}${kev.due_date?" · due "+cveE(CveCore.fmtDate(kev.due_date)):""}${kev.ransomware?" · ransomware use: "+cveE(kev.ransomware):""}</span></div>`:""}
</div>
${protect?`<div class="cve-section cve-protect"><div class="cve-section-title"><i class="icon icon-shield"></i>How to protect yourself</div>${protect}</div>`:""}
${summary&&!aff.length?"":`<div class="cve-section"><div class="cve-section-title">Affected products${affTotal?` <span class="cve-dim">(${affTotal})</span>`:""}</div>
${aff.length?`<div class="cve-table-wrap"><table class="cve-table"><thead><tr><th>Vendor</th><th>Product</th><th>Versions</th></tr></thead><tbody>${affShown.map((a)=>`<tr><td>${cveE(a.vendor)}</td><td>${cveE(a.product)}</td><td>${cveE(a.versions)}</td></tr>`).join("")}</tbody></table></div>${aff.length>CVE_AFFECTED_FIRST?`<button type="button" class="cve-more" data-cve-act="aff">${cveState.affAll?"Show fewer":"Show all "+aff.length}</button>`:""}${affTotal>aff.length?`<div class="cve-dim">Showing ${aff.length} of ${affTotal}. The full list is on the NVD page.</div>`:""}`:'<div class="cve-dim">No affected product data is listed yet.</div>'}
</div>`}
<div class="cve-section"><div class="cve-section-title">${summary&&!refs.length?"Online pages":`References <span class="cve-dim">(${refs.length})</span>`}</div>
<div class="cve-online">${cveLinkBtn(links.cve_org,"cve.org record","cve-online-btn")}${cveLinkBtn(links.nvd,"NVD detail page","cve-online-btn")}${kev?cveLinkBtn(links.kev,"CISA KEV catalog","cve-online-btn"):""}</div>
${refs.length?`<ul class="cve-refs">${refsShown.map(cveRefHtml).join("")}</ul>${refs.length>CVE_REFS_FIRST?`<button type="button" class="cve-more" data-cve-act="refs">${cveState.refsAll?"Show fewer":"Show all "+refs.length}</button>`:""}`:summary?"":'<div class="cve-dim">No references listed.</div>'}
</div>
</div>
<div class="cve-detail-foot">
<span class="cve-origin cve-origin-${r.origin==="live"?"live":"cache"}">${origin}</span><span class="cve-dim" title="${cveE(CveCore.fmtDateTime(r.fetched_at))}">${summary?"index built":"last fetched"} ${cveE(CveCore.relTime(r.fetched_at)||"-")}${r.stale?" · may be out of date":""}${Array.isArray(r.sources)&&r.sources.length?" · "+cveE(r.sources.join(", ")):""}</span>
<span class="cve-spacer"></span>
<button type="button" class="set-btn" data-cve-act="copyid">Copy ID</button>
<button type="button" class="set-btn" data-cve-act="copymd">Copy as Markdown</button>
${insert}
<button type="button" class="set-btn primary" data-cve-act="refresh"${canFetch?"":" disabled"} title="${canFetch?(summary?"Fetch the full record from the online sources":"Fetch this CVE again from the online sources"):"Online lookups are off"}"><i class="icon icon-refresh"></i><span>${summary?"Fetch full details":"Refresh"}</span></button>
</div>`
}
function cveDetailClick(e){
const link=e.target.closest("[data-cve-url]")
if(link){e.preventDefault();cveOpenUrl(link.dataset.cveUrl);return}
const act=e.target.closest("[data-cve-act]")
if(!act||act.disabled)return
const r=cveState.record
if(!r)return
const a=act.dataset.cveAct
if(a==="settings"){cveGoSettings();return}
if(a==="fetch"){cveShowRecord(r.id,true);return}
if(a==="aff"){cveState.affAll=!cveState.affAll;cveRenderDetail()}
else if(a==="refs"){cveState.refsAll=!cveState.refsAll;cveRenderDetail()}
else if(a==="copyid")cveCopy(r.id,"CVE ID copied")
else if(a==="copymd")cveCopy(CveCore.toMarkdown(r),"Copied as Markdown")
else if(a==="refresh")cveShowRecord(r.id,true)
else if(a==="insert"&&typeof cveNotesInsertRecord==="function")cveNotesInsertRecord(r)
}
// ---------------------------------------------------------------- news feed
function cveFiltersFromSettings(){
const f=(cveState.settings&&cveState.settings.feed)||{}
return {severity:f.min_severity||"",kev_only:!!f.kev_only,epss_min:f.epss_min||0,q:"",from:"",to:"",unread_only:false,watch_only:false}
}
function cveApplyFiltersToForm(){
const f=cveState.filters||{}
cveEl("cveFSeverity").value=f.severity||""
cveEl("cveFKev").checked=!!f.kev_only
cveEl("cveFEpss").value=f.epss_min?String(Math.round(f.epss_min*1000)/10):""
cveEl("cveFQuery").value=f.q||""
cveEl("cveFFrom").value=f.from||""
cveEl("cveFTo").value=f.to||""
cveEl("cveFUnread").checked=!!f.unread_only
cveEl("cveFWatch").checked=!!f.watch_only
}
function cveReadFilters(){
const pct=parseFloat(cveEl("cveFEpss").value)
cveState.filters={severity:cveEl("cveFSeverity").value,kev_only:cveEl("cveFKev").checked,epss_min:isNaN(pct)?0:Math.max(0,Math.min(100,pct))/100,q:cveEl("cveFQuery").value,from:cveEl("cveFFrom").value,to:cveEl("cveFTo").value,unread_only:cveEl("cveFUnread").checked,watch_only:cveEl("cveFWatch").checked}
cveState.feedLimit=100
}
function cveFiltersChanged(delay){
cveReadFilters()
if(cveState.filterTimer)clearTimeout(cveState.filterTimer)
cveState.filterTimer=setTimeout(()=>cveLoadFeed(),delay||0)
}
function cveLoadFeed(){
if(!cveState.ready)return Promise.resolve()
if(!cveState.filters)cveState.filters=cveFiltersFromSettings()
const f=CveCore.feedFilterNormalize(Object.assign({},cveState.filters,{limit:cveState.feedLimit}))
const seq=++cveState.feedSeq
return cveCall("feed",[f]).then((feed)=>{
if(seq!==cveState.feedSeq)return
cveState.feed=feed||{items:[],total:0,unread:0}
cveSetUnread(cveState.feed.unread)
cveRenderFeed()
}).catch((err)=>{
if(seq!==cveState.feedSeq)return
cveState.feed=null
cveRenderFeed(cveErr(err,"Could not load the feed"))
})
}
function cveRenderFeed(errorText){
const list=cveEl("cveFeedList")
if(!list)return
const feed=cveState.feed||{items:[],total:0,unread:0}
const st=cveState.status||{}
const items=Array.isArray(feed.items)?feed.items:[]
const refreshing=!!feed.refreshing
const btn=cveEl("cveRefreshBtn")
btn.disabled=refreshing||!st.can_fetch
btn.classList.toggle("busy",refreshing)
btn.querySelector("span").textContent=refreshing?"Refreshing...":"Refresh now"
cveEl("cveNewsStatus").textContent=refreshing?"Fetching the newest CVEs...":(feed.last_refresh?"Last refresh "+CveCore.relTime(feed.last_refresh):"Never refreshed")
const errBox=cveEl("cveNewsError")
errBox.classList.toggle("hidden",!feed.refresh_error)
errBox.textContent=feed.refresh_error?"Last refresh failed: "+feed.refresh_error:""
cveEl("cveMarkAllBtn").disabled=!feed.unread
cveEl("cveFeedTotal").textContent=errorText?"":(items.length?items.length+" of "+(feed.total||items.length)+" shown · "+(feed.unread||0)+" unread":"")
cveEl("cveFeedMore").classList.toggle("hidden",!(items.length<(feed.total||0)&&cveState.feedLimit<500))
if(errorText){list.innerHTML=`<div class="cve-empty cve-empty-error">${cveE(errorText)}</div>`;return}
if(!items.length){
let msg="No CVE matches these filters."
if(!feed.last_refresh&&!refreshing)msg=st.can_fetch?"The feed has not been fetched yet. Press Refresh now to get the newest CVEs.":(st.offline_only?"Offline only mode is on, so the feed cannot be fetched. Saved entries appear here.":"Online lookups are off, so the feed cannot be fetched. Turn them on in Settings > CVE Intel.")
else if(refreshing)msg="Fetching the newest CVEs..."
list.innerHTML=`<div class="cve-empty">${cveE(msg)}</div>`
return
}
list.innerHTML=items.map((s)=>cveRowHtml(s,{feed:true})).join("")
}
function cveSetUnread(n){
cveState.unread=Math.max(0,parseInt(n,10)||0)
const label=cveState.unread>99?"99+":String(cveState.unread)
const tabBadge=cveEl("cveNewsBadge")
if(tabBadge){tabBadge.textContent=label;tabBadge.classList.toggle("hidden",!cveState.unread)}
const nav=document.querySelector('#bottomNav .nav-btn[data-page="cve"]')
if(!nav)return
let badge=nav.querySelector(".cve-nav-badge")
if(!badge){badge=document.createElement("span");badge.className="cve-nav-badge hidden";nav.appendChild(badge)}
badge.textContent=label
badge.classList.toggle("hidden",!cveState.unread)
}
function cveMarkRead(ids,read){
return cveCall("mark_read",[ids,read!==false]).then((unread)=>{
const set=new Set(ids)
if(cveState.feed&&Array.isArray(cveState.feed.items))cveState.feed.items.forEach((s)=>{if(set.has(s.id))s.is_read=read!==false})
if(cveState.feed)cveState.feed.unread=typeof unread==="number"?unread:cveState.feed.unread
cveSetUnread(typeof unread==="number"?unread:cveState.unread)
cveRenderFeed()
}).catch((err)=>cveToast(cveErr(err,"Could not update the entry"),"error"))
}
function cveFeedClick(e){
const row=e.target.closest(".cve-row[data-cve-id]")
if(!row)return
const id=row.dataset.cveId
const readBtn=e.target.closest("[data-cve-read]")
if(readBtn){e.stopPropagation();cveMarkRead([id],readBtn.dataset.cveRead==="1");return}
const item=cveState.feed&&(cveState.feed.items||[]).find((s)=>s.id===id)
if(item&&!item.is_read)cveMarkRead([id],true)
cveSwitchTab("lookup")
cveShowRecord(id,false)
}
function cveRefreshFeed(){
const btn=cveEl("cveRefreshBtn")
btn.disabled=true
cveCall("refresh_feed").then((res)=>{
if(res&&res.message)cveToast(res.message,res.started||res.refreshing?"info":"error")
if(cveState.feed)cveState.feed.refreshing=!!(res&&res.refreshing)
cveRenderFeed()
if(res&&res.refreshing)cvePollRefresh()
}).catch((err)=>{cveToast(cveErr(err,"Could not refresh the feed"),"error");cveRenderFeed()})
}
// While a refresh runs the feed is polled every few seconds; the slow background tick takes over afterwards.
function cvePollRefresh(){
if(cveState.refreshPoll)return
let tries=0
cveState.refreshPoll=setInterval(()=>{
tries++
cveTick().then((t)=>{
if((t&&!t.refreshing)||tries>200){
clearInterval(cveState.refreshPoll);cveState.refreshPoll=null
cveLoadStatus();cveLoadFeed()
}
})
},3000)
}
// ---------------------------------------------------------------- watchlist
function cveLoadSettings(){
return cveCall("get_settings").then((s)=>{cveState.settings=s||{};cveRenderWatch();return s}).catch(()=>{cveState.settings=cveState.settings||{};cveRenderWatch()})
}
function cveRenderWatch(){
const list=cveEl("cveWatchList")
if(!list)return
const terms=(cveState.settings&&Array.isArray(cveState.settings.watchlist))?cveState.settings.watchlist:[]
list.innerHTML=terms.length?terms.map((t,i)=>`<span class="cve-watch-term"><span>${cveE(t)}</span><button type="button" data-cve-unwatch="${i}" title="Remove from the watchlist" aria-label="Remove"><i class="icon icon-close"></i></button></span>`).join(""):'<div class="cve-dim">Nothing on the watchlist yet.</div>'
}
function cveSaveWatch(terms,doneMsg){
const status=cveEl("cveWatchStatus")
return cveCall("set_settings",[{watchlist:terms},false]).then((s)=>{
cveState.settings=s||cveState.settings
status.textContent=doneMsg;status.classList.remove("error")
cveRenderWatch()
cveLoadFeed()
}).catch((err)=>{status.textContent=cveErr(err,"Could not save the watchlist");status.classList.add("error")})
}
function cveWatchAdd(){
const input=cveEl("cveWatchInput")
const cur=(cveState.settings&&Array.isArray(cveState.settings.watchlist))?cveState.settings.watchlist:[]
const next=CveCore.watchNormalize(cur,input.value)
if(next.length===cur.length){input.value="";return}
input.value=""
cveSaveWatch(next,"Added. New CVEs that match are flagged from the next refresh.")
}
// ---------------------------------------------------------------- background tick and notifications
function cveLocked(){
const o=document.getElementById("lockOverlay")
return !!(o&&!o.classList.contains("hidden"))
}
function cveHandleTick(t){
if(!t)return t
if(typeof t.unread==="number")cveSetUnread(t.unread)
;(Array.isArray(t.notifications)?t.notifications:[]).forEach((n)=>{
const id=CveCore.normId(n&&n.id)
if(!id||typeof toastAddHistory!=="function")return
toastAddHistory(CveCore.notifyText(n),"info",()=>cveOpenDetail(id))
})
if(cveState.feed){
const was=!!cveState.feed.refreshing
cveState.feed.refreshing=!!t.refreshing
if(t.last_refresh)cveState.feed.last_refresh=t.last_refresh
cveState.feed.refresh_error=t.refresh_error||""
if(cveState.ready&&cveState.tab==="news"){if(was&&!t.refreshing)cveLoadFeed();else cveRenderFeed()}
}
return t
}
function cveTick(){
if(typeof bridgeCall!=="function"||cveLocked())return Promise.resolve(null)
return cveCall("tick").then(cveHandleTick).catch(()=>null)
}
function cveStartPoller(){
if(cveState.pollerStarted)return
cveState.pollerStarted=true
setTimeout(cveTick,5000)
setInterval(cveTick,120000)
}
// ---------------------------------------------------------------- entry points
// Used by the notification bell, the note viewer's CVE links and the Reporting page.
function cveOpenDetail(id){
const cid=CveCore.normId(id)
if(!cid||typeof goToPage!=="function")return Promise.resolve(null)
return Promise.resolve(goToPage("cve")).then(()=>{
if(!cveState.ready){cveState.pendingId=cid;return null}
cveSwitchTab("lookup")
return cveShowRecord(cid,false)
})
}
function cveOnPageShown(e){
if(!e.detail||e.detail.page!=="cve"||e.detail.first||!cveState.ready)return
cveLoadStatus()
cveLoadSettings()
if(cveState.tab==="news")cveLoadFeed()
else if(!cveEl("cveSearchInput").value.trim()&&!cveState.errors.length)cveSearchCache("")
}
function initCve(){
return fetch("../pages/cve.html").then((r)=>r.text()).then((html)=>{
const page=document.querySelector('.page[data-page="cve"]')
page.innerHTML=html
page.querySelectorAll(".cve-tab").forEach((b)=>b.addEventListener("click",()=>cveSwitchTab(b.dataset.cveTab)))
cveEl("cveBannerBtn").addEventListener("click",cveGoSettings)
const input=cveEl("cveSearchInput")
input.addEventListener("input",cveOnSearchInput)
input.addEventListener("keydown",(e)=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();cveState.ids=CveCore.extractIds(input.value);cveRenderChips();if(cveState.ids.length)cveLookupTyped()}})
cveEl("cveLookupBtn").addEventListener("click",cveLookupTyped)
cveEl("cveChips").addEventListener("click",(e)=>{const c=e.target.closest("[data-cve-id]");if(c)cveShowRecord(c.dataset.cveId,false)})
const results=cveEl("cveResultsList")
results.addEventListener("click",(e)=>cveOpenRow(e.target.closest(".cve-row[data-cve-id]")))
results.addEventListener("keydown",(e)=>{if(e.key==="Enter"||e.key===" "){const row=e.target.closest(".cve-row[data-cve-id]");if(row){e.preventDefault();cveOpenRow(row)}}})
const searchFilterChanged=()=>{cveState.searchFilters={severity:cveEl("cveSSeverity").value,kev_only:cveEl("cveSKev").checked};cveSearchCache(input.value)}
cveEl("cveSSeverity").addEventListener("change",searchFilterChanged)
cveEl("cveSKev").addEventListener("change",searchFilterChanged)
cveEl("cveDetail").addEventListener("click",cveDetailClick)
;["cveFSeverity","cveFKev","cveFUnread","cveFWatch","cveFFrom","cveFTo"].forEach((id)=>cveEl(id).addEventListener("change",()=>cveFiltersChanged(0)))
;["cveFEpss","cveFQuery"].forEach((id)=>cveEl(id).addEventListener("input",()=>cveFiltersChanged(300)))
cveEl("cveFReset").addEventListener("click",()=>{cveState.filters=cveFiltersFromSettings();cveState.feedLimit=100;cveApplyFiltersToForm();cveLoadFeed()})
cveEl("cveRefreshBtn").addEventListener("click",cveRefreshFeed)
cveEl("cveMarkAllBtn").addEventListener("click",()=>cveCall("mark_all_read").then(()=>cveLoadFeed()).catch((err)=>cveToast(cveErr(err,"Could not mark the feed as read"),"error")))
cveEl("cveFeedMore").addEventListener("click",()=>{cveState.feedLimit=Math.min(500,cveState.feedLimit+100);cveLoadFeed()})
const feedList=cveEl("cveFeedList")
feedList.addEventListener("click",cveFeedClick)
feedList.addEventListener("keydown",(e)=>{if((e.key==="Enter"||e.key===" ")&&e.target.classList&&e.target.classList.contains("cve-row")){e.preventDefault();cveFeedClick(e)}})
cveEl("cveWatchAddBtn").addEventListener("click",cveWatchAdd)
cveEl("cveWatchInput").addEventListener("keydown",(e)=>{if(e.key==="Enter"){e.preventDefault();cveWatchAdd()}})
cveEl("cveWatchList").addEventListener("click",(e)=>{
const b=e.target.closest("[data-cve-unwatch]")
if(!b)return
const cur=(cveState.settings&&Array.isArray(cveState.settings.watchlist))?cveState.settings.watchlist.slice():[]
cur.splice(parseInt(b.dataset.cveUnwatch,10),1)
cveSaveWatch(cur,"Removed.")
})
cveState.ready=true
cveRenderChips()
cveRenderDetail()
return Promise.all([cveLoadStatus(),cveLoadSettings()]).then(()=>{
cveState.filters=cveFiltersFromSettings()
cveApplyFiltersToForm()
cveSwitchTab(cveState.tab)
const pending=cveState.pendingId
cveState.pendingId=""
if(pending){cveSwitchTab("lookup");cveShowRecord(pending,false)}
return cveSearchCache("")
})
}).catch((err)=>console.error("cve init failed",err))
}
if(typeof document!=="undefined"){
document.addEventListener("loya:page-shown",cveOnPageShown)
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",cveStartPoller)
else cveStartPoller()
}
