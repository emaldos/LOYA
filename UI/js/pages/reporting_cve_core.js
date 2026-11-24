// Reporting: pure helpers for the CVEs of a finding (ids, entries, auto-fill merge). No DOM: runs under Node for tests.
var ReportCve=(function(){
const RC=typeof ReportCore!=="undefined"?ReportCore:require("./reporting_core.js")
const esc=RC.escapeHtml
const ID_RX=/^CVE-\d{4}-\d{4,}$/
const SEVS=["critical","high","medium","low","info"]
const VERSIONS=["3.1","4.0","3.0","2.0"]
// Where an entry came from: typed by hand, the CVE Intel cache, an online lookup, or the bundled offline index (a summary).
const SOURCES=["manual","cache","live","index"]
const CVSS_NOTES={v31_fallback:"Using the CVSS 3.1 vector; the 4.0 vector is kept on the CVE.",v40_only:"This CVE is rated in CVSS 4.0 only. The finding takes its score, shown read-only as CVSS 4.0; the 4.0 vector is kept on the CVE."}
const MAX_CVES=50
const MAX_ENTRY_REFS=30
const MAX_FILL_REFS=25
const BLANK_TITLES=["","new finding","untitled finding"]
const MERGE_ROWS=[
{key:"title",label:"Title",kind:"text"},
{key:"severity",label:"Severity",kind:"choice"},
{key:"cvss",label:"CVSS",kind:"cvss"},
{key:"cwe",label:"CWE",kind:"text"},
{key:"description",label:"Description",kind:"rich"},
{key:"impact",label:"Impact",kind:"rich"},
{key:"remediation",label:"Remediation",kind:"rich"},
{key:"references",label:"References",kind:"list"}
]
const MODE_LABELS={keep:"Keep",fill:"Fill",replace:"Replace",append:"Append"}
function str(v,max){
let t=v===undefined||v===null?"":String(v)
t=t.replace(/\u0000/g,"").trim()
return max&&t.length>max?t.slice(0,max):t
}
function arr(v){return Array.isArray(v)?v:[]}
function normId(v){
const m=/^\s*(?:CVE[-\s_]*)?(\d{4})[-\s_]+(\d{4,19})\s*$/i.exec(str(v))
return m?"CVE-"+m[1]+"-"+m[2]:""
}
function isId(v){return typeof v==="string"&&ID_RX.test(v)}
// The offline fallback of cve.extract_ids: every CVE id written in a text, in order, once.
function extractIds(text){
const out=[],seen={}
String(text===undefined||text===null?"":text).replace(/\bCVE[-_ ]?(\d{4})[-_ ](\d{4,19})\b/gi,(_m,y,n)=>{
const id="CVE-"+y+"-"+n
if(!seen[id]){seen[id]=true;out.push(id)}
return ""
})
return out
}
function safeUrl(u){
const t=str(u)
return t.length<=1000&&/^https?:\/\/[^\s"'<>`\\\u0000-\u001f]+$/i.test(t)?t:""
}
function refKey(u){return u.replace(/^http:/i,"https:").replace(/\/+$/,"").toLowerCase()}
function dedupeRefs(list,max){
const out=[],seen={}
arr(list).forEach((u)=>{
const s=safeUrl(u&&typeof u==="object"?u.url:u)
if(!s||seen[refKey(s)])return
seen[refKey(s)]=true
out.push(s)
})
return max?out.slice(0,max):out
}
function score(v){
if(v===null||v===undefined||v===""||typeof v==="boolean")return null
const n=Number(String(v).replace(",","."))
if(!isFinite(n)||n<0||n>10)return null
return Math.round(n*10)/10
}
function sev(v,fallback){
const t=str(v).toLowerCase()
if(SEVS.indexOf(t)>=0)return t
if(t==="none"||t==="informational")return "info"
return fallback===undefined?"":fallback
}
function links(id,kev){
const cid=normId(id)
if(!cid)return []
const out=["https://nvd.nist.gov/vuln/detail/"+cid,"https://www.cve.org/CVERecord?id="+cid]
if(kev)out.push("https://www.cisa.gov/known-exploited-vulnerabilities-catalog?search_api_fulltext="+cid)
return out
}
// Remote text is plain text, never markup: every character is escaped. Blank lines split paragraphs, "- " lines become a
// list, and a line that ends in a colon (the labelled sections of the remediation text) is set in bold.
function plainToHtml(text){
const t=String(text===undefined||text===null?"":text).replace(/\r\n?/g,"\n").replace(/\u0000/g,"").trim()
if(!t)return ""
return t.split(/\n{2,}/).map((para)=>{
let out="",lines=[],items=[]
const flush=()=>{
if(lines.length)out+="<p>"+lines.join("<br>")+"</p>"
if(items.length)out+="<ul>"+items.map((i)=>"<li>"+i+"</li>").join("")+"</ul>"
lines=[];items=[]
}
para.split("\n").map((l)=>l.trim()).filter(Boolean).forEach((l)=>{
const bullet=/^[-*\u2022]\s+(.+)$/.exec(l)
if(bullet){if(lines.length)flush();items.push(esc(bullet[1]))}
else{if(items.length)flush();lines.push(l.length<=240&&/[^:]:$/.test(l)?"<strong>"+esc(l)+"</strong>":esc(l))}
})
flush()
return out
}).join("")
}
function richText(html){return html?RC.htmlToText(html):""}
function richEmpty(html){return !richText(html)&&!/<(?:img|hr)\b/i.test(String(html||""))}
function preview(text,max){
const t=str(text).replace(/\s+/g," ")
max=max||180
return t.length>max?t.slice(0,max-1).trimEnd()+"…":t
}
function normEntry(e){
e=e&&typeof e==="object"?e:{}
const id=normId(e.id||e.cve_id)
if(!id)return null
const version=VERSIONS.indexOf(str(e.cvss_version))>=0?str(e.cvss_version):""
const sc=score(e.cvss_score)
const epss=e.epss===null||e.epss===undefined||e.epss===""?null:Number(e.epss)
const source=SOURCES.indexOf(str(e.source))>=0?str(e.source):"manual"
return {id:id,title:str(e.title,300),cvss_version:version,cvss_vector:str(e.cvss_vector,200),cvss_score:sc,severity:sev(e.severity,sc===null?"":RC.sevFromScore(sc)),cwe:str(e.cwe,120),
description:str(e.description,20000),remediation:str(e.remediation,20000),references:dedupeRefs(e.references,MAX_ENTRY_REFS),kev:e.kev===true,kev_due:str(e.kev_due,40),
epss:epss!==null&&isFinite(epss)&&epss>=0&&epss<=1?epss:null,source:source,fetched_at:str(e.fetched_at,40)}
}
function normList(list){
const out=[],seen={}
arr(list).forEach((e)=>{
const n=normEntry(e)
if(!n||seen[n.id]||out.length>=MAX_CVES)return
seen[n.id]=true
out.push(n)
})
return out
}
// The report's CVSS calculator reads v3.1 only, so that is the vector a finding takes; a CVE that only has a v4.0
// rating keeps its vector on the CVE entry and gives the finding its score without a vector.
function pickCvss(p){
p=p&&typeof p==="object"?p:{}
const all=p.cvss_all&&typeof p.cvss_all==="object"?p.cvss_all:{}
const main=p.cvss&&typeof p.cvss==="object"?p.cvss:{}
const cands=[]
if(all.v31)cands.push({version:"3.1",vector:all.v31.vector,score:all.v31.score,severity:all.v31.severity})
cands.push({version:str(main.version),vector:main.vector||p.cvss_vector,score:main.score!==undefined?main.score:p.cvss_score,severity:p.severity})
if(all.v40)cands.push({version:"4.0",vector:all.v40.vector,score:all.v40.score,severity:all.v40.severity})
let finding=null,entry=null
cands.forEach((c)=>{
const vector=str(c.vector,200)
const parsed=vector&&/^CVSS:3\.[01]\//i.test(vector)?RC.cvssParse(vector):null
if(parsed&&parsed.valid&&!finding){
const norm=RC.cvssBuild(parsed.metrics)
finding={vector:norm,score:RC.cvssScore(norm),version:"3.1"}
// the entry keeps the score its source states; the finding takes the one its vector computes (the server does the same)
if(!entry||entry.version!=="3.1")entry={version:"3.1",vector:norm,score:score(c.score)!==null?score(c.score):RC.cvssScore(norm),severity:sev(c.severity)}
}else if(!entry&&(vector||score(c.score)!==null)){
entry={version:VERSIONS.indexOf(c.version)>=0?c.version:(/^CVSS:4\.0\//i.test(vector)?"4.0":""),vector:vector,score:score(c.score),severity:sev(c.severity)}
}
})
// CVE Intel's own rating is 4.0 (the user's default version): the CVE keeps that rating, the finding's 3.1 calculator takes v31.
const main4=str(main.version)==="4.0"?{version:"4.0",vector:str(main.vector||p.cvss_vector,200),score:score(main.score!==undefined?main.score:p.cvss_score),severity:sev(p.severity)||sev(all.v40&&all.v40.severity)}:null
if(main4&&(main4.vector||main4.score!==null))entry=main4
if(!finding&&entry&&entry.score!==null)finding={vector:"",score:entry.score,version:entry.version}
const note=finding&&entry&&entry.version==="4.0"?(finding.version==="3.1"?"v31_fallback":finding.version==="4.0"?"v40_only":""):""
return {finding:finding,entry:entry,note:note}
}
function entryFromPayload(p){
p=p&&typeof p==="object"?p:{}
const cv=pickCvss(p).entry||{version:"",vector:"",score:null,severity:""}
const kev=p.kev&&typeof p.kev==="object"&&p.kev.in_kev===true
const id=normId(p.cve_id||p.id)
const title=str(p.title)
return normEntry({id:id,title:id&&title.toUpperCase().indexOf(id)===0?title.slice(id.length).replace(/^\s*[:\u2013-]\s*/,""):title,cvss_version:cv.version,cvss_vector:cv.vector,cvss_score:cv.score,severity:sev(p.severity)||cv.severity,cwe:p.cwe,description:p.description,remediation:p.remediation,
references:arr(p.reference_urls).length?p.reference_urls:arr(p.references),kev:kev,kev_due:kev?p.kev.due_date:"",epss:p.epss&&typeof p.epss==="object"?p.epss.score:null,source:p.origin==="live"?"live":p.origin==="index"?"index":"cache",fetched_at:p.fetched_at})
}
// What a CVE offers to a finding, in the finding's own field formats (rich fields as escaped HTML).
function incomingFrom(p){
p=p&&typeof p==="object"?p:{}
const id=normId(p.cve_id||p.id)
const picked=pickCvss(p)
const cv=picked.finding
const kev=p.kev&&typeof p.kev==="object"&&p.kev.in_kev===true
const urls=arr(p.reference_urls).length?p.reference_urls:arr(p.references)
return {cvss_note:CVSS_NOTES[picked.note]||"",id:id,title:str(p.title,300),severity:sev(p.severity)||(cv&&cv.score!==null?RC.sevFromScore(cv.score):""),cvss:cv,cwe:str(p.cwe,120),
description:plainToHtml(p.description),impact:plainToHtml(p.impact),remediation:plainToHtml(p.remediation),references:dedupeRefs(links(id,kev).concat(dedupeRefs(urls)),MAX_FILL_REFS)}
}
// A hand-written CVE entry offers the same fields, so manual entry goes through the same merge.
function incomingFromEntry(entry){
const e=normEntry(entry)
if(!e)return null
const p={cve_id:e.id,title:e.title,severity:e.severity,cvss:{version:e.cvss_version,vector:e.cvss_vector,score:e.cvss_score},cwe:e.cwe,description:e.description,remediation:e.remediation,reference_urls:e.references,kev:{in_kev:e.kev}}
if(e.cvss_version==="4.0")p.cvss_all={v40:{vector:e.cvss_vector,score:e.cvss_score,severity:e.severity}}
return incomingFrom(p)
}
function cvssText(c){
if(!c)return ""
const sc=score(c.score)
return [sc===null?"":sc.toFixed(1)+(c.version&&c.version!=="3.1"?" (CVSS "+c.version+")":""),c.vector||""].filter(Boolean).join("  ")
}
function findingCvss(f){
const vector=str(f.cvss_vector),sc=score(f.cvss_score)
return vector||sc!==null?{vector:vector,score:sc,version:"3.1"}:null
}
// Which CVSS version a finding's score is in: its own vector is 3.1; a score without a vector that is a CVE's 4.0 (2.0, 3.0) rating
// is that version; any other bare score has no stated version ("").
function findingCvssVersion(f){
f=f&&typeof f==="object"?f:{}
if(str(f.cvss_vector))return "3.1"
const sc=score(f.cvss_score)
if(sc===null)return ""
const hit=arr(f.cves).find((c)=>c&&score(c.cvss_score)===sc&&VERSIONS.indexOf(str(c.cvss_version))>=0&&str(c.cvss_version)!=="3.1")
return hit?str(hit.cvss_version):""
}
function findingCvssLabel(f){const v=findingCvssVersion(f);return v?"CVSS "+v:"CVSS"}
function sourceText(e){
const src=str(e&&e.source)
return src==="manual"?"Entered by hand":src==="live"?"Looked up online":src==="index"?"From the offline index (summary)":"From the CVE cache"
}
function titleBlank(t){return BLANK_TITLES.indexOf(str(t).toLowerCase())>=0}
// One row per field the CVE has something for. Defaults never overwrite: an empty field is filled, a written one is kept,
// references are appended; with another CVE already on the finding everything is kept and only references are appended.
function mergePlan(finding,incoming,opts){
const f=finding&&typeof finding==="object"?finding:{}
const inc=incoming&&typeof incoming==="object"?incoming:{}
const others=arr(f.cves).filter((c)=>c&&c.id!==inc.id).length
const additional=opts&&opts.additional!==undefined?!!opts.additional:others>0
const curCvss=findingCvss(f)
const pristine=titleBlank(f.title)&&richEmpty(f.description)&&!curCvss
const rows=[]
MERGE_ROWS.forEach((def)=>{
const k=def.key
let empty,current,next,same
if(k==="cvss"){
if(!inc.cvss)return
empty=!curCvss
current=cvssText(curCvss)
next=cvssText(inc.cvss)
same=!!curCvss&&curCvss.vector===inc.cvss.vector&&curCvss.score===score(inc.cvss.score)
}else if(k==="severity"){
if(!inc.severity)return
empty=pristine||(!curCvss&&sev(f.severity,"info")==="info")
current=RC.sevLabel(sev(f.severity,"info"))
next=RC.sevLabel(inc.severity)
same=sev(f.severity,"info")===inc.severity
}else if(def.kind==="rich"){
if(richEmpty(inc[k]))return
empty=richEmpty(f[k])
current=preview(richText(f[k]),400)
next=preview(richText(inc[k]),400)
same=!empty&&richText(f[k])===richText(inc[k])
}else if(def.kind==="list"){
const cur=dedupeRefs(f[k])
const add=dedupeRefs(inc[k])
if(!add.length)return
const have={}
cur.forEach((u)=>{have[refKey(u)]=true})
const fresh=add.filter((u)=>!have[refKey(u)])
empty=!arr(f[k]).filter(Boolean).length
current=arr(f[k]).filter(Boolean).length?arr(f[k]).filter(Boolean).length+" reference"+(arr(f[k]).filter(Boolean).length===1?"":"s"):""
next=add.length+" link"+(add.length===1?"":"s")+(empty?"":" ("+fresh.length+" new)")
same=!fresh.length
rows.push({key:k,label:def.label,kind:def.kind,empty:empty,same:same,current:current,incoming:next,items:add,fresh:fresh,options:empty?["fill","keep"]:["keep","append","replace"],choice:same?"keep":(empty?"fill":"append")})
return
}else{
if(!str(inc[k]))return
empty=k==="title"?titleBlank(f[k]):!str(f[k])
current=str(f[k])
next=str(inc[k])
same=current===next
}
const options=empty?["fill","keep"]:(def.kind==="rich"?["keep","append","replace"]:["keep","replace"])
rows.push({key:k,label:def.label,kind:def.kind,empty:empty,same:same,current:current,incoming:next,options:options,choice:same||additional?"keep":(empty?"fill":"keep")})
})
return rows
}
function planChoices(rows){
const out={}
arr(rows).forEach((r)=>{out[r.key]=r.choice})
return out
}
// The finding patch of a merge: only the fields whose choice changes something.
function applyMerge(finding,incoming,choices){
const f=finding&&typeof finding==="object"?finding:{}
const inc=incoming&&typeof incoming==="object"?incoming:{}
const patch={}
mergePlan(f,inc,{additional:false}).forEach((row)=>{
const k=row.key
let mode=choices&&choices[k]
if(row.options.indexOf(mode)<0||mode==="keep"||row.same)return
if(mode==="fill"&&!row.empty)return
if(k==="cvss"){
patch.cvss_vector=inc.cvss.vector||""
patch.cvss_score=score(inc.cvss.score)
}else if(row.kind==="list"){
patch[k]=mode==="append"?arr(f[k]).filter(Boolean).concat(row.fresh):dedupeRefs(inc[k])
}else if(row.kind==="rich"){
patch[k]=mode==="append"?String(f[k]||"")+(inc.id?"<p><strong>"+esc(inc.id)+"</strong></p>":"")+inc[k]:inc[k]
}else patch[k]=inc[k]
})
return patch
}
function addCve(list,entry){
const e=normEntry(entry)
const cur=normList(list)
if(!e)return cur
const at=cur.findIndex((c)=>c.id===e.id)
if(at>=0){cur[at]=e;return cur}
if(cur.length>=MAX_CVES)return cur
cur.push(e)
return cur
}
function removeCve(list,id){
const cid=normId(id)||str(id)
return normList(list).filter((c)=>c.id!==cid)
}
function chipLabel(entry){
const e=entry&&typeof entry==="object"?entry:{}
const sc=score(e.cvss_score)
return str(e.id)+(sc===null?"":" · "+sc.toFixed(1))
}
function chipTitle(entry){
const e=entry&&typeof entry==="object"?entry:{}
const sc=score(e.cvss_score)
return [str(e.title),e.severity?RC.sevLabel(e.severity)+(sc===null?"":" "+sc.toFixed(1))+(e.cvss_version?" (CVSS "+e.cvss_version+")":""):"",e.kev?"Known exploited (CISA KEV)":"",
e.source==="manual"?"Entered by hand":e.source==="index"?"From the offline CVE index (summary)":(e.fetched_at?"From CVE Intel, "+RC.fmtDate(e.fetched_at):"")].filter(Boolean).join("\n")
}
// The fields of a new finding written from a CVE (a CVE Intel record, or an entry typed by hand).
function newFinding(inc,entry,tagList){
if(!inc||!entry)return null
const tags=[]
arr(tagList).forEach((t)=>{const s=str(t,60);if(s&&tags.indexOf(s)<0&&tags.length<10)tags.push(s)})
return {title:inc.title||entry.id,severity:inc.severity||"info",status:"open",cvss_vector:inc.cvss?inc.cvss.vector:"",cvss_score:inc.cvss?score(inc.cvss.score):null,cwe:inc.cwe,
description:inc.description,impact:inc.impact,remediation:inc.remediation,references:inc.references,tags:tags,cves:[entry],source:{kind:"cve",ref:entry.id}}
}
function findingFrom(p){return newFinding(incomingFrom(p),entryFromPayload(p),p&&p.tags)}
function findingFromEntry(entry){
const e=normEntry(entry)
return e?newFinding(incomingFromEntry(e),e,["cve"].concat(e.kev?["kev"]:[])):null
}
// What the finding's reference list becomes when a CVE's links are added to it; null when nothing is new.
function withLinks(refs,entry){
const cur=arr(refs).filter(Boolean)
const have={}
cur.forEach((u)=>{have[refKey(String(u))]=true})
const fresh=links(entry&&entry.id,entry&&entry.kev).filter((u)=>!have[refKey(u)])
return fresh.length?cur.concat(fresh):null
}
function idsText(list){return arr(list).map((c)=>c&&c.id).filter(Boolean).join(", ")}
return {SOURCES:SOURCES,CVSS_NOTES:CVSS_NOTES,findingCvssVersion:findingCvssVersion,findingCvssLabel:findingCvssLabel,sourceText:sourceText,ID_RX:ID_RX,MAX_CVES:MAX_CVES,VERSIONS:VERSIONS,MODE_LABELS:MODE_LABELS,normId:normId,isId:isId,extractIds:extractIds,safeUrl:safeUrl,dedupeRefs:dedupeRefs,score:score,sev:sev,links:links,plainToHtml:plainToHtml,richEmpty:richEmpty,preview:preview,
normEntry:normEntry,normList:normList,pickCvss:pickCvss,entryFromPayload:entryFromPayload,incomingFrom:incomingFrom,incomingFromEntry:incomingFromEntry,mergePlan:mergePlan,planChoices:planChoices,applyMerge:applyMerge,
addCve:addCve,removeCve:removeCve,chipLabel:chipLabel,chipTitle:chipTitle,findingFrom:findingFrom,findingFromEntry:findingFromEntry,withLinks:withLinks,idsText:idsText}
})()
if(typeof module!=="undefined"&&module.exports)module.exports=ReportCve
if(typeof window!=="undefined")window.ReportCve=ReportCve
