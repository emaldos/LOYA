// Pure logic for the CVE Intel page (no DOM, no bridge): escaping, link checks, id detection, formatting and Markdown export.
// Loaded by the app as a plain script (global CveCore) and by tests/js/cve_core.js through require().
// Everything a CVE record carries is remote text and is treated as untrusted: it only reaches the page through esc() and safeUrl().
const CveCore=(function(){
const SEVERITIES=["critical","high","medium","low","info"]
const SEV_LABELS={critical:"Critical",high:"High",medium:"Medium",low:"Low",info:"Info"}
const SEV_RANK={info:0,low:1,medium:2,high:3,critical:4}
const REF_KINDS={patch:{label:"Patch",icon:"check"},vendor:{label:"Vendor advisory",icon:"shield"},mitigation:{label:"Mitigation",icon:"key"},exploit:{label:"Exploit",icon:"bug"},advisory:{label:"Advisory",icon:"info"},other:{label:"Reference",icon:"link"}}
const ID_RX=/CVE-\d{4}-\d{4,7}(?!\d)/gi
function str(v){return v===undefined||v===null?"":String(v)}
// Escapes quotes too: the result is also placed inside HTML attributes (title, data-*, value).
function esc(s){
return str(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")
}
// Only absolute https links are ever made clickable. Anything else (http, javascript, data, relative, credentials in the URL) gives "".
function safeUrl(u){
const s=str(u).trim()
if(!/^https:\/\/[A-Za-z0-9]/i.test(s)||/[\s<>"'`\\\u0000-\u001f\u007f]/.test(s))return ""
const rest=s.slice(8)
const host=rest.split(/[/?#]/)[0]
if(!host||host.includes("@"))return ""
return s
}
function normId(v){
const m=str(v).trim().toUpperCase().match(/^CVE-\d{4}-\d{4,7}$/)
return m?m[0]:""
}
function extractIds(text){
const out=[]
const seen=new Set()
const t=str(text)
ID_RX.lastIndex=0
let m
while((m=ID_RX.exec(t))!==null){
// "XCVE-2021-1234" or "CVE-2021-1234" glued to a longer word is not an id.
const prev=m.index>0?t[m.index-1]:""
if(prev&&/[A-Za-z0-9]/.test(prev))continue
const id=m[0].toUpperCase()
if(!seen.has(id)){seen.add(id);out.push(id)}
}
return out
}
function normSeverity(v){
const s=str(v).trim().toLowerCase()
if(s==="informational"||s==="none")return "info"
return SEVERITIES.includes(s)?s:""
}
function sevLabel(v){return SEV_LABELS[normSeverity(v)]||"Unknown"}
function sevClass(v){return "cve-sev-"+(normSeverity(v)||"unknown")}
function sevRank(v){const s=normSeverity(v);return s?SEV_RANK[s]:-1}
function num(v){
if(v===undefined||v===null||v==="")return null
const n=typeof v==="number"?v:parseFloat(str(v))
return isFinite(n)?n:null
}
function fmtScore(v){
const n=num(v)
if(n===null||n<0||n>10)return "-"
return (Math.round(n*10)/10).toFixed(1)
}
function pct(v,digits){
const n=num(v)
if(n===null||n<0||n>1)return ""
return (n*100).toFixed(digits)+"%"
}
// epss: a number (score only) or {score,percentile}. "97.2% (99.9th percentile)".
function fmtEpss(epss){
if(epss===undefined||epss===null||epss==="")return "-"
const score=typeof epss==="object"?epss.score:epss
const s=pct(score,num(score)!==null&&num(score)<0.1?2:1)
if(!s)return "-"
const p=typeof epss==="object"?pct(epss.percentile,1):""
return p?s+" ("+p.replace("%","")+"th percentile)":s
}
function parseDate(v){
const s=str(v).trim()
if(!s)return null
// NVD timestamps carry no zone ("2021-12-10T10:15:09.143") and are UTC.
const iso=/^\d{4}-\d{2}-\d{2}T[\d:.]+$/.test(s)?s+"Z":s
const d=new Date(iso)
return isNaN(d.getTime())?null:d
}
function fmtDate(v){
const s=str(v).trim()
const m=s.match(/^(\d{4}-\d{2}-\d{2})/)
if(m)return m[1]
const d=parseDate(s)
return d?d.toISOString().slice(0,10):""
}
function fmtDateTime(v){
const d=parseDate(v)
if(!d)return ""
return d.toISOString().slice(0,16).replace("T"," ")+" UTC"
}
function relTime(v,now){
const d=parseDate(v)
if(!d)return ""
const delta=Math.max(0,(now===undefined?Date.now():now)-d.getTime())
if(delta<60000)return "just now"
if(delta<3600000)return Math.floor(delta/60000)+"m ago"
if(delta<86400000)return Math.floor(delta/3600000)+"h ago"
if(delta<86400000*60)return Math.floor(delta/86400000)+"d ago"
return fmtDate(v)
}
function refKind(k){const s=str(k).toLowerCase();return REF_KINDS[s]?s:"other"}
function refKindLabel(k){return REF_KINDS[refKind(k)].label}
function refIcon(k){return REF_KINDS[refKind(k)].icon}
function clip(s,n){
const t=str(s).replace(/\s+/g," ").trim()
return t.length>n?t.slice(0,Math.max(0,n-1)).trimEnd()+"…":t
}
function summaryLine(s){
if(!s)return ""
const parts=[str(s.id)]
const sev=normSeverity(s.severity)
if(sev)parts.push(sevLabel(sev)+(num(s.score)!==null?" "+fmtScore(s.score):""))
if(s.kev===true||(s.kev&&s.kev.in_kev))parts.push("KEV")
const e=typeof s.epss==="object"&&s.epss?s.epss.score:s.epss
if(num(e)!==null)parts.push("EPSS "+pct(e,1))
return parts.filter(Boolean).join(" · ")
}
// ---- the bundled offline index
// The optional 3rd argument of cve.search, or null when no filter is set (so the plain two-argument call is used).
function searchFilters(f){
const x=f&&typeof f==="object"?f:{}
const out={}
const sev=normSeverity(x.severity)
if(sev&&sev!=="info")out.severity=sev
if(x.kev_only===true)out.kev_only=true
return Object.keys(out).length?out:null
}
function fmtCount(n){
const v=num(n)
return v===null||v<0?"0":Math.round(v).toLocaleString("en-US")
}
function isIndexOnly(s){return !!(s&&(s.index_only===true||s.origin==="index"))}
function stateLabel(state){
const v=str(state).trim().toLowerCase()
return v==="rejected"?"Rejected":v==="reserved"?"Reserved":""
}
// How many CVEs the installed index holds: from the last search answer, else from cve.status(); 0 when none is installed.
function indexCount(searchIndex,statusIndex){
const a=searchIndex&&typeof searchIndex==="object"?num(searchIndex.count):null
if(a!==null&&a>0)return Math.round(a)
const b=statusIndex&&typeof statusIndex==="object"&&statusIndex.installed!==false?num(statusIndex.count):null
return b!==null&&b>0?Math.round(b):0
}
function resultsTitle(q,res,filtered){
const used=!!(res&&res.index&&res.index.used)
if(!str(q).trim()&&!filtered)return used?"Saved CVEs and the offline index":"Saved CVEs"
return used?"Matches - saved CVEs first, then the offline index":"Saved CVEs matching your text"
}
function emptyResultsText(q,count,canFetch,filtered){
if(str(q).trim()||filtered)return count>0?"No match in the saved CVEs or the offline index of "+fmtCount(count)+" CVEs.":"No saved CVE matches. Paste a CVE ID to look it up"+(canFetch?".":" once online lookups are on.")
return count>0?"Search "+fmtCount(count)+" CVEs offline by ID, product or keyword.":"Nothing saved yet. CVEs you look up are kept here so they also work offline."
}
function isoDay(v){const m=str(v).trim().match(/^\d{4}-\d{2}-\d{2}$/);return m?m[0]:""}
// The filter object sent to cve.feed: only known keys, clamped, empty ones left out.
function feedFilterNormalize(f){
const x=f&&typeof f==="object"?f:{}
const out={}
const sev=normSeverity(x.severity)
if(sev&&sev!=="info")out.severity=sev
if(x.kev_only)out.kev_only=true
const e=num(x.epss_min)
if(e!==null&&e>0)out.epss_min=Math.min(1,e>1?e/100:e)
const q=str(x.q).replace(/\s+/g," ").trim().slice(0,200)
if(q)out.q=q
let from=isoDay(x.from),to=isoDay(x.to)
if(from&&to&&from>to){const t=from;from=to;to=t}
if(from)out.from=from
if(to)out.to=to
if(x.unread_only)out.unread_only=true
if(x.watch_only)out.watch_only=true
const lim=num(x.limit)
out.limit=lim===null?100:Math.max(1,Math.min(500,Math.floor(lim)))
const off=num(x.offset)
if(off!==null&&off>0)out.offset=Math.floor(off)
return out
}
function watchNormalize(list,add){
const out=[]
const seen=new Set()
;(Array.isArray(list)?list:[]).concat(add===undefined?[]:[add]).forEach((t)=>{
const v=str(t).replace(/\s+/g," ").trim().slice(0,80)
const k=v.toLowerCase()
if(v&&!seen.has(k)&&out.length<100){seen.add(k);out.push(v)}
})
return out
}
// Markdown text is remote too: neutralise what could start markup or a link, and keep it on one line.
function mdText(s){
return str(s).replace(/\r?\n+/g," ").replace(/([\\`*_{}\[\]()<>|#])/g,"\\$1").trim()
}
function mdLink(url,label){
const u=safeUrl(url)
if(!u)return ""
return "["+mdText(label||u)+"](<"+u.replace(/[<>]/g,"")+">)"
}
function toMarkdown(r){
if(!r||!r.id)return ""
const L=[]
const id=normId(r.id)||mdText(r.id)
L.push("## "+id+(r.title&&str(r.title)!==str(r.id)?" - "+mdText(r.title):""))
L.push("")
const facts=[]
const sev=normSeverity(r.severity)
if(sev)facts.push("**Severity:** "+sevLabel(sev)+(num(r.score)!==null?" ("+fmtScore(r.score)+")":""))
const cv=r.cvss||{}
;[["v40","CVSS 4.0"],["v31","CVSS 3.1"],["v2","CVSS 2.0"]].forEach(([k,label])=>{
if(cv[k]&&cv[k].vector)facts.push("**"+label+":** "+fmtScore(cv[k].score)+" `"+str(cv[k].vector).replace(/`/g,"")+"`")
})
if(r.epss&&num(r.epss.score)!==null)facts.push("**EPSS:** "+fmtEpss(r.epss))
if(r.kev&&r.kev.in_kev)facts.push("**CISA KEV:** yes"+(r.kev.date_added?", added "+mdText(fmtDate(r.kev.date_added)):"")+(r.kev.due_date?", due "+mdText(fmtDate(r.kev.due_date)):"")+(str(r.kev.ransomware).toLowerCase()==="known"?", known ransomware use":""))
if(Array.isArray(r.cwes)&&r.cwes.length)facts.push("**CWE:** "+r.cwes.map((c)=>mdText(c.id)+(c.name?" "+mdText(c.name):"")).join("; "))
if(r.published)facts.push("**Published:** "+mdText(fmtDate(r.published))+(r.modified?" · **Modified:** "+mdText(fmtDate(r.modified)):""))
facts.forEach((f)=>L.push("- "+f))
if(r.description){L.push("");L.push(mdText(r.description))}
const aff=Array.isArray(r.affected)?r.affected:[]
if(aff.length){
L.push("");L.push("### Affected products")
aff.slice(0,25).forEach((a)=>L.push("- "+mdText([a.vendor,a.product,a.versions].filter(Boolean).join(" "))))
if((r.affected_total||aff.length)>25)L.push("- ... "+((r.affected_total||aff.length)-25)+" more")
}
const p=r.protect||{}
const vendor=(Array.isArray(p.vendor)?p.vendor:[]).map((v)=>({v,link:mdLink(v.url)})).filter((x)=>x.link)
const generic=Array.isArray(p.generic)?p.generic:[]
if((p.kev_action&&p.kev_action.text)||vendor.length||generic.length){
L.push("");L.push("### How to protect yourself")
if(p.kev_action&&p.kev_action.text){L.push("");L.push("**CISA KEV required action:** "+mdText(p.kev_action.text)+(p.kev_action.due_date?" (due "+mdText(fmtDate(p.kev_action.due_date))+")":""))}
if(vendor.length){
L.push("");L.push("**Vendor guidance:**")
vendor.forEach((x)=>L.push("- "+refKindLabel(x.v.kind)+": "+x.link))
}
generic.forEach((g)=>{
L.push("");L.push("**Generic guidance ("+[mdText(g.cwe),g.name?mdText(g.name):""].filter(Boolean).join(" ")+") - not specific to this product:**")
;(g.mitigations||[]).forEach((m)=>L.push("- "+mdText(m)))
if((g.detection||[]).length){L.push("");L.push("*Detection:*");g.detection.forEach((m)=>L.push("- "+mdText(m)))}
})
}
const links=r.links||{}
const online=[["cve.org",links.cve_org],["NVD",links.nvd],["CISA KEV",r.kev&&r.kev.in_kev?links.kev:""]].map(([label,u])=>mdLink(u,label)).filter(Boolean)
const refs=(Array.isArray(r.references)?r.references:[]).map((x)=>({x,link:mdLink(x.url)})).filter((y)=>y.link)
if(online.length||refs.length){
L.push("");L.push("### References")
if(online.length)L.push("- "+online.join(" · "))
refs.slice(0,40).forEach((y)=>L.push("- "+y.link+((y.x.tags||[]).length?" ("+y.x.tags.map(mdText).join(", ")+")":"")))
}
return L.join("\n")+"\n"
}
// The text of one bell-history entry.
function notifyText(n){
if(!n)return ""
const id=normId(n.id)||clip(n.id,40)
const head=n.kind==="kev"?"New CISA KEV entry":n.kind==="watch"?"Watchlist match":"CVE"
const body=clip(n.message||n.title||"",160)
return head+": "+id+(body&&body!==id?" - "+body:"")
}
return {SEVERITIES,REF_KINDS,esc,safeUrl,normId,extractIds,normSeverity,sevLabel,sevClass,sevRank,fmtScore,fmtEpss,fmtDate,fmtDateTime,relTime,refKind,refKindLabel,refIcon,clip,summaryLine,feedFilterNormalize,watchNormalize,mdText,toMarkdown,notifyText,searchFilters,fmtCount,isIndexOnly,stateLabel,indexCount,resultsTitle,emptyResultsText}
})()
if(typeof module!=="undefined"&&module.exports)module.exports=CveCore
