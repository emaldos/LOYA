// Reporting page: report list, report editor (outline + details / branding / sections), autosave, preview, versions, templates.
// Everything here is prefixed rpg (functions) / rpg- (classes); the shared report widgets from the other reporting files use rpt.
const RPG_SAVE_DELAY=1200
const RPG_SEARCH_DELAY=120
const RPG_SEVS=[{id:"critical",label:"Critical",short:"Crit",color:"#9b1c1c"},{id:"high",label:"High",short:"High",color:"#dc2626"},{id:"medium",label:"Medium",short:"Med",color:"#f59e0b"},{id:"low",label:"Low",short:"Low",color:"#2563eb"},{id:"info",label:"Informational",short:"Info",color:"#6b7280"}]
const RPG_STATUSES=[{id:"draft",label:"Draft"},{id:"review",label:"In review"},{id:"final",label:"Final"}]
const RPG_SECTION_KINDS=[
{kind:"executive_summary",label:"Executive summary",auto:false},
{kind:"scope",label:"Scope and rules of engagement",auto:false},
{kind:"methodology",label:"Methodology",auto:false},
{kind:"findings_summary",label:"Findings summary",auto:true},
{kind:"findings",label:"Detailed findings",auto:true},
{kind:"remediation_roadmap",label:"Remediation roadmap",auto:true},
{kind:"risk_matrix",label:"Risk matrix",auto:true},
{kind:"attack_narrative",label:"Attack narrative",auto:false},
{kind:"project_timeline",label:"Project timeline",auto:true},
{kind:"conclusion",label:"Conclusion",auto:false},
{kind:"document_control",label:"Document control",auto:true},
{kind:"appendix_tools",label:"Appendix: Tools used",auto:false},
{kind:"appendix_commands",label:"Appendix: Commands run",auto:true},
{kind:"appendix_evidence",label:"Appendix: Evidence",auto:true},
{kind:"appendix_timeline",label:"Appendix: Testing timeline",auto:true},
{kind:"custom",label:"Custom section",auto:false}
]
// Icon and one-line description of each kind, for the add-section picker and the quick-add row.
const RPG_KIND_META={
executive_summary:{icon:"icon-star",desc:"The result in business terms for a non-technical reader: overall assessment, key findings, recommendations."},
scope:{icon:"icon-target",desc:"What was tested and what was not, the rules of engagement and the limitations."},
methodology:{icon:"icon-list",desc:"The standards and phases the testing followed, and how severity is rated."},
findings_summary:{icon:"icon-table",desc:"Severity table, risk chart and an overview table of every finding."},
findings:{icon:"icon-report",desc:"One detailed block per finding: description, impact, steps, remediation and evidence."},
remediation_roadmap:{icon:"icon-settings",desc:"A prioritised table of the remediation actions, most severe first."},
risk_matrix:{icon:"rpg-ic-matrix",desc:"Likelihood against impact: where every finding sits and what to fix first."},
attack_narrative:{icon:"icon-link",desc:"The kill chain as a story: initial access, execution, privilege escalation, lateral movement, objectives."},
project_timeline:{icon:"rpg-ic-flag",desc:"The milestones of the engagement, taken from the report's Timeline."},
conclusion:{icon:"icon-marker",desc:"The overall result, the next steps and the limitations and disclaimer."},
document_control:{icon:"icon-file",desc:"Version history, authors, reviewers, distribution list and the testing team."},
appendix_tools:{icon:"icon-commands",desc:"The tools used during the engagement and what each was used for."},
appendix_commands:{icon:"icon-command-line",desc:"The commands that were run, taken from the evidence used in the report."},
appendix_evidence:{icon:"icon-image",desc:"Every piece of evidence the report refers to, in full."},
appendix_timeline:{icon:"icon-clock",desc:"The recorded testing activity in chronological order."},
custom:{icon:"icon-add",desc:"An empty section with your own title and text."}
}
// One click (or Alt+1 ... Alt+6) adds these with their starting text.
const RPG_QUICK_KINDS=["executive_summary","scope","methodology","findings","attack_narrative","conclusion"]
const RPG_AUTO_INFO={
findings_summary:"Generated on export: a severity table, the risk chart and an overview table of every finding. The text below is printed before it.",
findings:"Generated on export: one detailed block per finding (severity, CVSS, affected assets, description, impact, steps to reproduce, remediation, evidence). Write and order the findings here.",
remediation_roadmap:"Generated on export: a prioritised table built from the remediation text of every finding, most severe first. The text below is printed before it.",
risk_matrix:"Generated on export: a likelihood against impact matrix that places every finding, built from each finding's severity and likelihood. The text below is printed before it.",
project_timeline:"Generated on export: the milestones of the engagement with their dates and status, taken from the Timeline of this report. The text below is printed before it.",
document_control:"Generated on export: document version, authors, reviewers, distribution list and the testing team, taken from Details.",
appendix_commands:"Generated on export: the commands that were run, taken from the evidence used in this report. Text you write below is printed before the list.",
appendix_evidence:"Generated on export: every piece of evidence used in this report, in full.",
appendix_timeline:"Generated on export: a timeline of the recorded activity, taken from the evidence used in this report. Text you write below is printed before it."
}
const RPG_MS_KEYS=[{key:"kickoff",label:"Kick-off"},{key:"testing_start",label:"Testing start"},{key:"testing_end",label:"Testing end"},{key:"draft_due",label:"Draft report"},{key:"review",label:"QA / review"},{key:"handover",label:"Hand-over"},{key:"retest_start",label:"Retest start"},{key:"retest_end",label:"Retest end"},{key:"custom",label:"Milestone"}]
const RPG_REMIND_PRESETS=[1,3,7]
const RPG_UNDO_LIMIT=100
const RPG_COALESCE_MS=1200
const RPG_CLASSIFICATIONS=["Public","Internal","Confidential","Strictly Confidential","Restricted","TLP:CLEAR","TLP:GREEN","TLP:AMBER","TLP:AMBER+STRICT","TLP:RED"]
const RPG_REPORT_TYPES=["Web Application Penetration Test","Internal Network Penetration Test","External Network Penetration Test","Cloud Security Assessment","Mobile Application Penetration Test","API Penetration Test","Red Team Engagement","Vulnerability Assessment","Retest Report"]
const RPG_SWATCHES=["#1d4ed8","#0f766e","#b91c1c","#7c3aed","#c2410c","#0f172a","#475569","#d4af37"]
const RPG_PAGE_WIDTHS={A4:794,Letter:816}
const RPG_LOGO_MAX=10*1024*1024

// ---- pure helpers (also exported for tests/js/reporting_page.js) ----
function rpgEsc(s){
return String(s===undefined||s===null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")
}
function rpgKindInfo(kind){
return RPG_SECTION_KINDS.find((k)=>k.kind===kind)||{kind:kind||"custom",label:kind?String(kind).replace(/_/g," "):"Section",auto:false}
}
function rpgStatusLabel(id){
const s=RPG_STATUSES.find((x)=>x.id===id)
return s?s.label:"Draft"
}
function rpgParseTime(iso){
if(!iso)return NaN
let s=String(iso).trim().replace(" ","T")
if(/^\d{4}-\d{2}-\d{2}T[\d:.]+$/.test(s))s+="Z"
return Date.parse(s)
}
function rpgRelTime(iso,now){
const t=rpgParseTime(iso)
if(isNaN(t))return ""
const delta=(now===undefined?Date.now():now)-t
// A stamp slightly ahead is a clock or time-zone difference; one far ahead is shown as the date it is.
if(delta<-86400000)return rpgStampText(iso).slice(0,10)
if(delta<60000)return "Just now"
if(delta<3600000)return Math.floor(delta/60000)+"m ago"
if(delta<86400000)return Math.floor(delta/3600000)+"h ago"
if(delta<86400000*30)return Math.floor(delta/86400000)+"d ago"
return rpgStampText(iso).slice(0,10)
}
function rpgSevRank(id){
const i=RPG_SEVS.findIndex((s)=>s.id===id)
return i<0?RPG_SEVS.length:i
}
function rpgCountSeverities(findings){
const counts={critical:0,high:0,medium:0,low:0,info:0}
const by_status={open:0,retest:0,fixed:0,accepted:0}
;(findings||[]).forEach((f)=>{
const sev=counts[f.severity]===undefined?"info":f.severity
counts[sev]++
const st=by_status[f.status]===undefined?"open":f.status
by_status[st]++
})
return {counts,total:(findings||[]).length,open:by_status.open,by_status}
}
// Highest severity first, then most findings, for the "risk" sort of the list.
function rpgRiskKey(counts){
counts=counts||{}
return RPG_SEVS.map((s)=>String(Math.min(99999,counts[s.id]||0)).padStart(5,"0")).join("")
}
function rpgFilterReports(list,query,status,sort){
const words=String(query||"").toLowerCase().split(/\s+/).filter(Boolean)
let rows=(list||[]).filter((r)=>{
if(status&&r.status!==status)return false
if(!words.length)return true
const hay=[r.title,r.client,r.profile_name,rpgStatusLabel(r.status)].join(" ").toLowerCase()
return words.every((w)=>hay.includes(w))
})
const txt=(v)=>String(v||"").toLowerCase()
const time=(v)=>{const t=rpgParseTime(v);return isNaN(t)?0:t}
const cmp={
updated:(a,b)=>time(b.updated_at)-time(a.updated_at),
created:(a,b)=>time(b.created_at)-time(a.created_at),
title:(a,b)=>txt(a.title).localeCompare(txt(b.title)),
client:(a,b)=>txt(a.client).localeCompare(txt(b.client))||txt(a.title).localeCompare(txt(b.title)),
risk:(a,b)=>rpgRiskKey(b.counts).localeCompare(rpgRiskKey(a.counts))||time(b.updated_at)-time(a.updated_at)
}[sort]||null
if(cmp)rows=rows.slice().sort(cmp)
return rows
}
// Merge a report patch into another: meta/branding/options merge key by key (like the server does), everything else overwrites.
function rpgMergePatch(base,patch){
const out=Object.assign({},base||{})
Object.keys(patch||{}).forEach((k)=>{
if((k==="meta"||k==="branding"||k==="options")&&patch[k]&&typeof patch[k]==="object")out[k]=Object.assign({},out[k]||{},patch[k])
else out[k]=patch[k]
})
return out
}
function rpgNormHex(value){
let s=String(value||"").trim().toLowerCase()
if(s[0]==="#")s=s.slice(1)
if(/^[0-9a-f]{3}$/.test(s))s=s.split("").map((c)=>c+c).join("")
return /^[0-9a-f]{6}$/.test(s)?"#"+s:""
}
// Black or white, whichever reads better on the given colour (WCAG relative luminance).
function rpgContrastText(hex){
const h=rpgNormHex(hex)
if(!h)return "#ffffff"
const lin=(i)=>{const c=parseInt(h.slice(i,i+2),16)/255;return c<=0.03928?c/12.92:Math.pow((c+0.055)/1.055,2.4)}
const lum=0.2126*lin(1)+0.7152*lin(3)+0.0722*lin(5)
return lum>0.42?"#111827":"#ffffff"
}
function rpgMoveItem(arr,from,to){
const out=(arr||[]).slice()
if(from<0||from>=out.length)return out
to=Math.max(0,Math.min(out.length-1,to))
const item=out.splice(from,1)[0]
out.splice(to,0,item)
return out
}
// Insertion slot (0..n) for a pointer at y, given the vertical midpoints of the rows.
function rpgDropIndex(mids,y){
let i=0
while(i<mids.length&&y>mids[i])i++
return i
}
// Slot (as returned by rpgDropIndex, counted with the dragged row still in place) -> final index after the move.
function rpgSlotToIndex(from,slot){
return slot>from?slot-1:slot
}
function rpgValidDate(s){
if(!/^\d{4}-\d{2}-\d{2}$/.test(String(s||"")))return false
const d=new Date(s+"T00:00:00Z")
return !isNaN(d.getTime())&&d.toISOString().slice(0,10)===s
}
function rpgCleanList(arr){
const seen=new Set(),out=[]
;(arr||[]).forEach((v)=>{
const s=String(v===undefined||v===null?"":v).trim()
if(s&&!seen.has(s)){seen.add(s);out.push(s)}
})
return out
}
function rpgSplitLines(text){
return rpgCleanList(String(text||"").split(/\r?\n|;/))
}
function rpgCleanTesters(rows){
return (rows||[]).map((t)=>({name:String(t.name||"").trim(),role:String(t.role||"").trim(),email:String(t.email||"").trim()})).filter((t)=>t.name||t.role||t.email)
}
// Target values also hold ports, user names, wordlist paths...; only addresses belong in a scope list.
function rpgIsScopeValue(v){
v=String(v||"").trim()
if(!v||/\s/.test(v))return false
if(/^https?:\/\/[^/]+/i.test(v))return true
if(/^\d{1,3}(\.\d{1,3}){3}(\/\d{1,2})?(-\d{1,3})?$/.test(v))return true
if(/^[0-9a-f]*:[0-9a-f:]*:[0-9a-f:.]*(\/\d{1,3})?$/i.test(v))return true
return /^(\*\.)?([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$/i.test(v)
}
function rpgTargetScopeLine(t){
const vals=rpgCleanList(Object.keys(t.values||{}).filter((k)=>!/pass|pwd|secret|token|hash|cred|cookie|key|user|login/i.test(k)).map((k)=>t.values[k])).filter(rpgIsScopeValue)
const name=String(t.name||"").trim()
if(!vals.length)return name
if(vals.length===1&&vals[0]===name)return name
return name?name+": "+vals.join(", "):vals.join(", ")
}
function rpgHtmlToText(html){
return String(html||"").replace(/<(br|\/p|\/li|\/h\d|\/tr|\/pre|\/blockquote)\s*\/?>/gi," ").replace(/<[^>]*>/g,"").replace(/&nbsp;/g," ").replace(/&lt;/g,"<").replace(/&gt;/g,">").replace(/&quot;/g,'"').replace(/&#39;/g,"'").replace(/&amp;/g,"&").replace(/\s+/g," ").trim()
}
function rpgExcerpt(html,max){
const t=rpgHtmlToText(html)
max=max||160
return t.length>max?t.slice(0,max-1).trimEnd()+"…":t
}
function rpgEvidenceUids(report){
const out=new Set()
const scan=(html)=>{const rx=/data-evidence="([^"]+)"/g;let m;while((m=rx.exec(String(html||""))))out.add(m[1])}
;((report&&report.sections)||[]).forEach((s)=>scan(s.content))
;((report&&report.findings)||[]).forEach((f)=>{
["description","impact","steps","remediation"].forEach((k)=>scan(f[k]))
;(f.evidence||[]).forEach((e)=>{if(e&&(e.evidence_uid||e.asset_uid))out.add(e.evidence_uid||("asset:"+e.asset_uid))})
})
return Array.from(out)
}
function rpgSaveStateInfo(st){
if(st.errors)return {cls:"error",label:"Save failed - Retry"}
if(st.saving)return {cls:"saving",label:"Saving…"}
if(st.pending)return {cls:"dirty",label:"Unsaved changes"}
return {cls:"saved",label:"Saved"}
}
// The preview document is foreign HTML: forbid every remote load and send link clicks nowhere (the iframe sandbox blocks popups).
function rpgPreviewDoc(html){
const guard='<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'; font-src data:"><base target="_blank">'
html=String(html||"")
return /<head[^>]*>/i.test(html)?html.replace(/<head[^>]*>/i,(m)=>m+guard):guard+html
}
function rpgSortedForRoadmap(findings){
return (findings||[]).slice().sort((a,b)=>rpgSevRank(a.severity)-rpgSevRank(b.severity)||(b.cvss_score||0)-(a.cvss_score||0)||(a.position||0)-(b.position||0))
}
// ---- schedule / timeline (pure) ----
function rpgSame(a,b){return JSON.stringify(a===undefined?null:a)===JSON.stringify(b===undefined?null:b)}
function rpgClone(o){return o===undefined?undefined:JSON.parse(JSON.stringify(o))}
function rpgMsLabel(key){
const k=RPG_MS_KEYS.find((x)=>x.key===key)
return k?k.label:"Milestone"
}
function rpgDayNum(s){return rpgValidDate(s)?Math.round(Date.parse(s+"T00:00:00Z")/86400000):NaN}
function rpgDayStr(n){return new Date(n*86400000).toISOString().slice(0,10)}
// Today in the user's own time zone (deadlines are calendar days, not UTC instants).
function rpgTodayStr(d){
d=d||new Date()
return d.getFullYear()+"-"+String(d.getMonth()+1).padStart(2,"0")+"-"+String(d.getDate()).padStart(2,"0")
}
function rpgNewId(){return Math.random().toString(36).slice(2,8)+Date.now().toString(36).slice(-6)}
function rpgValidTime(s){return /^([01]\d|2[0-3]):[0-5]\d$/.test(String(s||""))}
// Same rules as Cores/Services/report_schedule.py normalize(): every milestone comes back complete and valid.
function rpgNormSchedule(schedule,newId){
const src=Array.isArray(schedule)?schedule:(schedule&&Array.isArray(schedule.milestones)?schedule.milestones:[])
const seen=new Set(),out=[]
src.forEach((m)=>{
if(!m||typeof m!=="object"||out.length>=60)return
const key=RPG_MS_KEYS.some((k)=>k.key===m.key)?m.key:"custom"
let id=String(m.id===undefined||m.id===null?"":m.id)
if(!/^[A-Za-z0-9_-]{1,40}$/.test(id)||seen.has(id))id=(newId||rpgNewId)()
seen.add(id)
const days=[]
;(Array.isArray(m.remind)?m.remind:[]).forEach((r)=>{
const n=Number(r&&typeof r==="object"?r.days_before:r)
if(Number.isInteger(n)&&n>=0&&n<=365&&days.indexOf(n)<0)days.push(n)
})
days.sort((a,b)=>b-a)
out.push({id,key,label:String(m.label||"").trim().slice(0,120)||rpgMsLabel(key),date:rpgValidDate(m.date)?m.date:"",time:rpgValidTime(m.time)?m.time:"",done:!!m.done,remind:days.slice(0,8).map((n)=>({days_before:n})),notes:String(m.notes||"").slice(0,2000)})
})
return {milestones:out}
}
function rpgMsState(m,today){
if(m.done)return "done"
if(!rpgValidDate(m.date))return "unset"
const d=rpgDayNum(m.date)-rpgDayNum(today)
return d<0?"overdue":d===0?"today":"upcoming"
}
function rpgMsSorted(milestones){
return (milestones||[]).slice().sort((a,b)=>(a.date||"9999").localeCompare(b.date||"9999")||(a.time||"99:99").localeCompare(b.time||"99:99"))
}
// The earliest milestone that is not done (so an overdue one comes first); final reports have no deadline.
function rpgNextDeadline(report,today){
if(!report||report.status==="final")return null
const rows=rpgMsSorted(rpgNormSchedule(report.meta&&report.meta.schedule,()=>"x"+Math.random()).milestones.filter((m)=>m.date&&!m.done))
if(!rows.length)return null
const m=rows[0],left=rpgDayNum(m.date)-rpgDayNum(today)
return {milestone:m.id,key:m.key,label:m.label,date:m.date,time:m.time,days_left:left,overdue:left<0}
}
function rpgDaysText(n){
if(n===0)return "today"
if(n===1)return "tomorrow"
if(n===-1)return "yesterday"
return n>0?"in "+n+" days":(-n)+" days ago"
}
// "Hand-over in 3 days" / "Hand-over today" / "Overdue by 2 days" (the chip's tooltip names the overdue milestone).
function rpgDeadlineText(label,daysLeft){
const p=rpgDeadlineParts(label,daysLeft)
return p.name?p.name+" "+p.when:p.when
}
function rpgDeadlineShort(daysLeft){
return daysLeft<0?rpgDaySpan(daysLeft,true)+" late":daysLeft===0?"today":rpgDaySpan(daysLeft,true)
}
// Same wording as report_schedule.reminder_message(): Hand-over for 'ACME External Pentest' is due tomorrow (2026-11-30)
function rpgReminderMessage(title,label,date,daysLeft,time){
return `${label||"Milestone"} for '${title||"Untitled report"}' ${daysLeft<0?"was":"is"} due ${rpgDaysText(daysLeft)} (${date}${time?" "+time:""})`
}
function rpgRemindLabel(days){
if(days===0)return "On the day"
if(days===1)return "1 day before"
if(days%7===0)return days/7+(days===7?" week before":" weeks before")
return days+" days before"
}
function rpgTickLabel(day,withYear){
const d=new Date(day*86400000),mon=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][d.getUTCMonth()]
return withYear?mon+" "+d.getUTCFullYear():d.getUTCDate()+" "+mon
}
// Positions for the horizontal timeline. Every x is a percentage of the track. Labels are centred on their marker and need
// opts.minGap percent of room, so milestones that are closer together go to the next lane.
function rpgTimelineLayout(milestones,today,opts){
opts=opts||{}
const t=rpgDayNum(today)
const dated=rpgMsSorted((milestones||[]).filter((m)=>rpgValidDate(m.date))).map((m)=>({m,day:rpgDayNum(m.date)}))
if(!dated.length||isNaN(t))return {empty:true,items:[],phases:[],ticks:[],lanes:0,today:null}
let lo=Math.min(t,dated[0].day),hi=Math.max(t,dated[dated.length-1].day)
const pad=Math.max(1,Math.ceil((hi-lo)*0.06))
lo-=pad;hi+=pad
const span=hi-lo
const pct=(day)=>Math.round((day-lo)/span*10000)/100
const minGap=opts.minGap||14,laneEnd=[]
const items=dated.map(({m,day})=>{
const x=pct(day)
let lane=0
while(lane<laneEnd.length&&x-laneEnd[lane]<minGap)lane++
laneEnd[lane]=x
return {id:m.id,key:m.key,label:m.label||rpgMsLabel(m.key),date:m.date,time:m.time||"",done:!!m.done,pct:x,lane,state:rpgMsState(m,today),days_left:day-t}
})
const first=(key)=>dated.find((d)=>d.m.key===key)
const phases=[["testing","Testing","testing_start","testing_end"],["retest","Retest","retest_start","retest_end"]].map((p)=>{
const a=first(p[2]),b=first(p[3])
if(!a||!b||b.day<a.day)return null
return {key:p[0],label:p[1],from:a.m.date,to:b.m.date,left:pct(a.day),width:Math.round((pct(b.day)-pct(a.day))*100)/100}
}).filter(Boolean)
const maxTicks=opts.maxTicks||7
const step=[1,2,7,14,28,56,91,182,365].find((s)=>span/s<=maxTicks)||730
const ticks=[]
for(let day=lo;day<=hi;day++){
// Weekly steps land on Mondays (day 4 of the epoch was a Monday).
if(((day-(step%7===0?4:0))%step+step)%step===0)ticks.push({pct:pct(day),label:rpgTickLabel(day,step>=182),date:rpgDayStr(day)})
}
return {empty:false,start:rpgDayStr(lo),end:rpgDayStr(hi),days:span,today:{pct:pct(t),date:today},items,phases,ticks,lanes:laneEnd.length}
}
// "Fill from engagement dates": testing start / end follow the engagement dates; an empty schedule also gets the usual milestones.
// Testing dates that have already passed are added as done (they are events, not deliverables).
function rpgScheduleFromDates(schedule,meta,newId,today){
const ms=rpgNormSchedule(schedule,newId).milestones
meta=meta||{}
const empty=!ms.length
const past=(key,date)=>key!=="handover"&&rpgValidDate(date)&&rpgValidDate(today)&&date<today
const mk=(key,date,remind)=>({id:(newId||rpgNewId)(),key,label:rpgMsLabel(key),date:rpgValidDate(date)?date:"",time:"",done:past(key,date),remind:(remind||[]).map((n)=>({days_before:n})),notes:""})
const set=(key,date,remind)=>{
const m=ms.find((x)=>x.key===key)
if(m){if(rpgValidDate(date))m.date=date}
else if(rpgValidDate(date)||empty)ms.push(mk(key,date,remind))
}
if(empty)set("kickoff",meta.start_date)
set("testing_start",meta.start_date)
set("testing_end",meta.end_date)
if(empty){set("draft_due","",[1]);set("review","")}
const later=rpgValidDate(meta.report_date)&&(!rpgValidDate(meta.end_date)||meta.report_date>=meta.end_date)
if(empty||(later&&!ms.some((m)=>m.key==="handover")))set("handover",later?meta.report_date:"",[3,1])
return {milestones:empty?ms:rpgMsSorted(ms)}
}

// ---- undo / redo history (pure) ----
function rpgHistNew(limit){return {undo:[],redo:[],limit:limit||RPG_UNDO_LIMIT}}
// op: {type,label,key?,before?,after?,...}. Two ops with the same key that arrive within RPG_COALESCE_MS merge into one step
// (rapid typing in one field). opts.merge is for a change made by the field's own (native) undo or redo: the steps recorded
// for that field are taken back as far as the text went back, instead of a new step being added on top.
function rpgHistPush(h,op,now,opts){
now=now===undefined?Date.now():now
const top=h.undo[h.undo.length-1]
const merge=!!(opts&&opts.merge)
if(merge&&op.key&&top&&top.key===op.key){
let i=h.undo.length-1
while(i>=0&&h.undo[i].key===op.key&&!rpgSame(h.undo[i].before,op.after))i--
if(i>=0&&h.undo[i].key===op.key){h.undo.splice(i);return null}
top.after=op.after
top.at=now
return top
}
if(op.key&&top&&top.key===op.key&&!top.sealed&&now-top.at<=RPG_COALESCE_MS){
top.after=op.after
top.at=now
h.redo=[]
if(rpgSame(top.before,top.after))h.undo.pop()
return top
}
if("before" in op&&"after" in op&&rpgSame(op.before,op.after))return null
h.redo=[]
op.at=now
h.undo.push(op)
if(h.undo.length>h.limit)h.undo.splice(0,h.undo.length-h.limit)
return op
}
// The next typing in the same field starts a new step (called when the field loses focus).
function rpgHistSeal(h){
const top=h.undo[h.undo.length-1]
if(top)top.sealed=true
}
function rpgHistPeek(h,dir){
const s=dir==="redo"?h.redo:h.undo
return s.length?s[s.length-1]:null
}
// Moves the next step to the other stack and returns it; rpgHistGiveBack puts it back when applying it failed.
function rpgHistTake(h,dir){
const from=dir==="redo"?h.redo:h.undo,to=dir==="redo"?h.undo:h.redo
const op=from.pop()
if(!op)return null
op.sealed=true
to.push(op)
return op
}
function rpgHistGiveBack(h,dir,op){
const from=dir==="redo"?h.redo:h.undo,to=dir==="redo"?h.undo:h.redo
const at=to.lastIndexOf(op)
if(at<0)return
to.splice(at,1)
from.push(op)
}
function rpgHistClear(h){h.undo=[];h.redo=[]}
// A restored section / finding comes back with a new id: every step that mentions the old one follows it.
function rpgHistRemap(h,kind,oldId,newId){
const sec=kind==="sec"
const fix=(op)=>{
if(!op||op.type.indexOf(sec?"sec-":"f-")!==0)return
if(op.id===oldId)op.id=newId
const ent=sec?op.sec:op.finding
if(ent&&ent.id===oldId)ent.id=newId
;["before","after"].forEach((k)=>{if(Array.isArray(op[k])&&/-order$/.test(op.type))op[k]=op[k].map((x)=>x===oldId?newId:x)})
if(op.key)op.key=op.key.replace(kind+":"+oldId+":",kind+":"+newId+":")
}
h.undo.forEach(fix);h.redo.forEach(fix)
}
function rpgHistTip(h,dir){
const op=rpgHistPeek(h,dir),name=dir==="redo"?"Redo":"Undo",keys=dir==="redo"?"Ctrl+Shift+Z":"Ctrl+Z"
return op?`${name}: ${op.label||"last change"} (${keys})`:`Nothing to ${name.toLowerCase()} (${keys})`
}
function rpgSameIds(a,b){
const ids=(l)=>(l||[]).map((x)=>Number(x.id)).sort((x,y)=>x-y).join(",")
return ids(a)===ids(b)
}
function rpgPathLabel(path){
const names={title:"rename the report",status:"change the status",profile_id:"change the engagement profile","meta.schedule":"edit the timeline","meta.testers":"edit the testers","meta.scope_in":"edit the scope","meta.scope_out":"edit the scope","meta.distribution":"edit the distribution list","branding.logo_asset":"change the logo","branding.theme":"change the report theme","branding.font":"change the report font","branding.cover_style":"change the cover style"}
if(names[path])return names[path]
const p=String(path).split(".")
return "edit "+(p[0]==="branding"?"branding: ":p[0]==="options"?"export option: ":"")+String(p[p.length-1]).replace(/_/g," ")
}
// Where a new section goes (index into sections): right after the open section; otherwise an appendix goes last and
// everything else goes in front of the appendices.
function rpgInsertIndex(sections,currentId,kind){
sections=sections||[]
const cur=sections.findIndex((s)=>s.id===currentId)
if(cur>=0)return cur+1
if(/^appendix_/.test(String(kind||"")))return sections.length
const app=sections.findIndex((s)=>/^appendix_/.test(String(s.kind||"")))
return app<0?sections.length:app
}
// Likelihood x severity counts for the risk matrix preview: rows follow RPG_SEVS, columns high / medium / low / not set.
function rpgRiskMatrix(findings){
const cols=["high","medium","low",""]
const rows=RPG_SEVS.map((s)=>({sev:s.id,label:s.label,cells:cols.map(()=>0)}))
;(findings||[]).forEach((f)=>{
const r=rows[Math.min(rpgSevRank(f.severity),rows.length-1)]
const c=cols.indexOf(String(f.likelihood||"").toLowerCase())
r.cells[c<0?3:c]++
})
return {cols:["High","Medium","Low","Not set"],rows}
}
// ---- report list: pure helpers (numbers, clamped text, chunks, keyboard grid) ----
const RPG_CHUNK=36
const RPG_CARD_MIN=270
const RPG_CARD_GAP=12
// 999 -> "999", 1234 -> "1.2k", 99999 -> "99.9k", 499995 -> "499k", 1e6 -> "1M". Truncated, never rounded up, so a compact
// number never claims more than there is. tight drops the decimal from 10k upwards ("99k").
function rpgCompactNum(n,tight){
n=Number(n)
if(!isFinite(n))return "0"
n=Math.trunc(n)
const a=Math.abs(n),sign=n<0?"-":""
if(a<1000)return sign+a
const u=[[1e12,"T"],[1e9,"B"],[1e6,"M"],[1e3,"k"]].find((x)=>a>=x[0])
const tenths=Math.floor(a/(u[0]/10))
return sign+(tenths>=1000||(tight&&tenths>=100)?String(Math.floor(tenths/10)):String(tenths/10))+u[1]
}
function rpgExactNum(n){
n=Number(n)
if(!isFinite(n))return "0"
return String(Math.trunc(n)).replace(/\B(?=(\d{3})+(?!\d))/g,",")
}
// One line of plain text for a card or a tooltip: control and bidi-override characters are dropped (a title must not be able
// to reorder the text around it), white space collapses, and the result is cut on a whole character.
function rpgClampText(s,max){
const t=String(s===undefined||s===null?"":s).replace(/[\u202a-\u202e\u2066-\u2069\u200e\u200f\u061c]/g,"").replace(/[\u0000-\u001f\u007f-\u009f\u2028\u2029]+/g," ").replace(/\s+/g," ").trim()
max=max>0?max:600
const chars=Array.from(t)
return chars.length<=max?t:chars.slice(0,max-1).join("").trimEnd()+"…"
}
// "2026-11-24 10:00 UTC" for tooltips; "" for anything that is not a date with a four-digit year.
function rpgStampText(iso){
const t=rpgParseTime(iso)
if(isNaN(t))return ""
const d=new Date(t),y=d.getUTCFullYear()
if(isNaN(y)||y<0||y>9999)return ""
return d.toISOString().slice(0,16).replace("T"," ")+" UTC"
}
// A length of time that stays short however far away the date is: 12 days, 7 months, 55 years (short: 12d, 7mo, 55y).
function rpgDaySpan(n,short){
n=Math.abs(Math.trunc(Number(n)||0))
if(n<100)return short?n+"d":n+(n===1?" day":" days")
if(n<730){const m=Math.floor(n/30.4375);return short?m+"mo":m+" months"}
const y=rpgCompactNum(Math.floor(n/365.25))
return short?y+"y":y+" years"
}
// The chip's two halves: the milestone name may be cut short, the "when" never is.
function rpgDeadlineParts(label,daysLeft){
if(daysLeft<0)return {name:"",when:"Overdue by "+rpgDaySpan(daysLeft)}
return {name:label||"Milestone",when:daysLeft<=1?rpgDaysText(daysLeft):"in "+rpgDaySpan(daysLeft)}
}
// Columns of the card grid for a list of that inner width (the same sum CSS auto-fill does).
function rpgGridCols(width,min,gap){
min=min||RPG_CARD_MIN
gap=gap===undefined?RPG_CARD_GAP:gap
return Math.max(1,Math.floor(((Number(width)||0)+gap)/(min+gap)))
}
// Width in px left for a card's text in a list of that inner width (card border 1px and padding 14px on each side).
function rpgCardInner(width,min,gap){
gap=gap===undefined?RPG_CARD_GAP:gap
const cols=rpgGridCols(width,min,gap)
return Math.max(0,Math.floor(((Number(width)||0)-(cols-1)*gap)/cols)-30)
}
// How many cards are in the DOM after one more chunk, and how many are needed for the card at an index to exist.
function rpgChunkNext(shown,total,size){
size=size>0?size:RPG_CHUNK
total=Math.max(0,Number(total)||0)
return Math.min(total,Math.max(0,Number(shown)||0)+size)
}
function rpgChunkFor(index,total,size){
size=size>0?size:RPG_CHUNK
total=Math.max(0,Number(total)||0)
if(!(index>=0))return Math.min(total,size)
return Math.min(total,(Math.floor(index/size)+1)*size)
}
// Arrow keys, Home/End and PageUp/PageDown in a grid of cols columns holding total cards. Returns the new index (cur when the
// key does not move). Down from the last full row goes to the last card when that one sits on a further row.
function rpgNavIndex(cur,key,cols,total,pageRows){
total=Math.max(0,Number(total)||0)
if(!total)return -1
cols=Math.max(1,Number(cols)||1)
const last=total-1
if(!(cur>=0))return key==="End"?last:0
cur=Math.min(cur,last)
const row=(i)=>Math.floor(i/cols)
const jump=(rows)=>{
const to=cur+rows*cols
if(to<0)return cur%cols
if(to>last)return row(cur)===row(last)?cur:Math.min(last,row(last)*cols+cur%cols)
return to
}
if(key==="ArrowRight")return Math.min(last,cur+1)
if(key==="ArrowLeft")return Math.max(0,cur-1)
if(key==="ArrowDown")return jump(1)
if(key==="ArrowUp")return cur-cols<0?cur:cur-cols
if(key==="Home")return 0
if(key==="End")return last
if(key==="PageDown")return jump(Math.max(1,pageRows||3))
if(key==="PageUp")return jump(-Math.max(1,pageRows||3))
return cur
}
// The severity colour comes from a class (rpg-sev-critical ...): an inline custom property on every pill made a long list slow.
// The severity row of a card always fits one line. Widest first: pills with labels and the total, pills with labels, numbers
// only with the total, numbers only, then tight pills (no dot, 99k instead of 99.9k). Sizes are estimates for the 11px UI font, a little on the wide side.
function rpgSevLayout(counts,total,width){
counts=counts||{}
width=width>0?width:240
const sevs=RPG_SEVS.filter((s)=>Number(counts[s.id])>0)
total=Number(total)||0
const num=(n,tight)=>rpgCompactNum(n,tight)
const textW=(s,per)=>String(s).length*per
const parts=(tight)=>sevs.map((s)=>({id:s.id,label:s.label,short:s.short,n:Number(counts[s.id]),text:num(counts[s.id],tight)}))
const pills=(level)=>{
const ps=parts(level===2),gap=level===2?3:5
return ps.reduce((w,p)=>w+(level===2?14:30.5)+textW(p.text,6.3)+(level===0?28.5:0),0)+Math.max(0,ps.length-1)*gap
}
const totalLong=total?num(total)+(total===1?" finding":" findings"):"",totalShort=total?num(total,true):""
const wLong=total?8+textW(totalLong,5):0,wShort=total?8+textW(totalShort,6.3):0
const tries=[[0,totalLong,wLong],[0,"",0],[1,totalLong,wLong],[1,"",0],[2,totalShort,wShort],[2,"",0]]
const pick=tries.find((t)=>pills(t[0])+t[2]<=width)||tries[tries.length-1]
return {level:pick[0],parts:parts(pick[0]===2),total:pick[1],totalTip:rpgExactNum(total)+(total===1?" finding":" findings")}
}
if(typeof module!=="undefined"&&module.exports)module.exports={RPG_CHUNK,rpgCompactNum,rpgExactNum,rpgClampText,rpgStampText,rpgDaySpan,rpgDeadlineParts,rpgGridCols,rpgCardInner,rpgChunkNext,rpgChunkFor,rpgNavIndex,rpgSevLayout,RPG_KIND_META,RPG_QUICK_KINDS,RPG_MS_KEYS,RPG_UNDO_LIMIT,RPG_COALESCE_MS,rpgSame,rpgClone,rpgMsLabel,rpgDayNum,rpgDayStr,rpgTodayStr,rpgValidTime,rpgNormSchedule,rpgMsState,rpgMsSorted,rpgNextDeadline,rpgDaysText,rpgDeadlineText,rpgDeadlineShort,rpgReminderMessage,rpgRemindLabel,rpgTimelineLayout,rpgScheduleFromDates,rpgHistNew,rpgHistPush,rpgHistSeal,rpgHistPeek,rpgHistTake,rpgHistGiveBack,rpgHistClear,rpgHistRemap,rpgHistTip,rpgSameIds,rpgPathLabel,rpgInsertIndex,rpgRiskMatrix,RPG_SECTION_KINDS,RPG_SEVS,rpgEsc,rpgKindInfo,rpgStatusLabel,rpgParseTime,rpgRelTime,rpgCountSeverities,rpgRiskKey,rpgFilterReports,rpgMergePatch,rpgNormHex,rpgContrastText,rpgMoveItem,rpgDropIndex,rpgSlotToIndex,rpgValidDate,rpgCleanList,rpgSplitLines,rpgCleanTesters,rpgIsScopeValue,rpgTargetScopeLine,rpgHtmlToText,rpgExcerpt,rpgEvidenceUids,rpgSaveStateInfo,rpgPreviewDoc,rpgSortedForRoadmap}

// ---- state ----
const rpgS={ready:false,view:"list",list:[],listError:"",q:"",status:"",sort:"updated",report:null,entry:"details",dirtyReport:null,dirtySections:{},timers:{},chains:{},saving:0,errors:{},rich:null,richSection:null,findings:null,chart:null,sources:null,placeholders:null,logos:{},opening:0,deadlines:{},rows:[],shown:0,cardW:0,listSig:"",listIO:null,listRO:null,searchTimer:0,resizeTimer:0,menuReturn:null,menuKbdAt:0,targets:null,hist:rpgHistNew(),undoBusy:false,applying:false,nativeHist:false,nativeUntil:0,typed:typeof WeakSet==="undefined"?{has:()=>false,add:()=>{},delete:()=>{}}:new WeakSet(),inputSeq:0,tlObserver:null,tlWidth:0}
function rpgErr(err,fallback){return err&&err.message?String(err.message):fallback}
function rpgHas(path){
const t=typeof bridgeResolve==="function"?bridgeResolve(path):null
return !!(t&&typeof t.fn==="function")
}
function rpgToast(msg,isError){if(typeof showToast==="function")showToast(msg,isError?"error":undefined)}
function rpgPageActive(){
const page=document.querySelector('.page[data-page="reporting"]')
return !!page&&page.classList.contains("active")
}
function rpgEl(id){return document.getElementById(id)}
// A dialog owns the keyboard while it is open: a modal, a confirmation, or the command palette.
function rpgDialogOpen(){
const pal=document.getElementById("paletteOverlay")
return !!(document.getElementById("appModalBackdrop")||document.querySelector(".confirm-overlay")||(pal&&!pal.classList.contains("hidden")))
}
function rpgSanitize(html){
if(window.ReportCore&&typeof ReportCore.sanitizeHtml==="function")return ReportCore.sanitizeHtml(html)
return "<p>"+rpgEsc(rpgHtmlToText(html))+"</p>"
}
function rpgSevColor(id){return `var(--rpt-sev-${id},${(RPG_SEVS.find((s)=>s.id===id)||RPG_SEVS[4]).color})`}
function rpgSevPills(counts,opts){
opts=opts||{}
counts=counts||{}
const parts=RPG_SEVS.filter((s)=>opts.all||counts[s.id]).map((s)=>`<span class="rpg-sev rpg-sev-${s.id}${counts[s.id]?"":" zero"}" title="${rpgExactNum(counts[s.id]||0)} ${s.label}"><i></i><b>${rpgCompactNum(counts[s.id]||0)}</b><span>${opts.short?s.short:s.label}</span></span>`)
return parts.join("")
}
function rpgSevBadge(sev){
if(window.ReportWidgets&&typeof ReportWidgets.severityBadge==="function")return ReportWidgets.severityBadge(sev)
const s=RPG_SEVS.find((x)=>x.id===sev)||RPG_SEVS[4]
return `<span class="rpg-sev" style="--sev:${rpgSevColor(s.id)}"><i></i><span>${s.label}</span></span>`
}

// ---- menus and modals ----
function rpgCloseMenu(){
const m=rpgEl("rpgMenu")
if(m){
// A menu opened from the keyboard hands the focus back to where it came from.
const back=rpgS.menuReturn&&m.contains(document.activeElement)?rpgS.menuReturn:null
m.remove()
if(back&&back.isConnected&&typeof back.focus==="function")back.focus({preventScroll:true})
}
rpgS.menuReturn=null
document.removeEventListener("mousedown",rpgMenuOutside,true)
document.removeEventListener("keydown",rpgMenuKey,true)
}
function rpgMenuOutside(e){
const m=rpgEl("rpgMenu")
if(m&&!m.contains(e.target))rpgCloseMenu()
}
function rpgMenuKey(e){
if(e.key==="Escape"){e.preventDefault();e.stopPropagation();rpgCloseMenu();return}
if(e.key==="Tab"){rpgCloseMenu();return}
const m=rpgEl("rpgMenu"),step={ArrowDown:1,ArrowUp:-1,Home:0,End:0}[e.key]
if(!m||step===undefined)return
const items=Array.from(m.querySelectorAll(".rpg-menu-item:not(:disabled)"))
if(!items.length)return
e.preventDefault();e.stopPropagation()
const cur=items.indexOf(document.activeElement)
const to=e.key==="Home"?0:e.key==="End"?items.length-1:cur<0?(step>0?0:items.length-1):(cur+step+items.length)%items.length
items[to].focus()
}
// items: {label,icon,tag,note,danger,disabled,fn} or {sep:true}. anchor: an element (menu drops below it) or {x,y}.
// opts.kbd: opened from the keyboard - the first item takes the focus and closing gives it back.
function rpgOpenMenu(anchor,items,opts){
rpgCloseMenu()
const opener=opts&&opts.kbd?document.activeElement:null
const menu=document.createElement("div")
menu.id="rpgMenu"
menu.setAttribute("role","menu")
menu.className="rpg-menu glass-panel"
items.forEach((it)=>{
if(it.sep){const sep=document.createElement("div");sep.className="rpg-menu-sep";menu.appendChild(sep);return}
const btn=document.createElement("button")
btn.type="button"
btn.className="rpg-menu-item"+(it.danger?" danger":"")
btn.setAttribute("role","menuitem")
btn.disabled=!!it.disabled
btn.innerHTML=`<i class="icon ${it.icon||"rpg-ic-none"}"></i><span class="rpg-menu-label"></span>`+(it.note?'<span class="rpg-menu-note"></span>':"")+(it.tag?'<span class="rpg-tag"></span>':"")
btn.querySelector(".rpg-menu-label").textContent=it.label
if(it.note)btn.querySelector(".rpg-menu-note").textContent=it.note
if(it.tag)btn.querySelector(".rpg-tag").textContent=it.tag
if(!it.disabled)btn.addEventListener("click",(e)=>{rpgCloseMenu();it.fn(e)})
menu.appendChild(btn)
})
menu.style.visibility="hidden"
document.body.appendChild(menu)
const w=menu.offsetWidth,h=menu.offsetHeight
let x,y
if(anchor&&anchor.getBoundingClientRect){
const r=anchor.getBoundingClientRect()
x=r.left
y=window.innerHeight-r.bottom-6>=h||r.top<h?r.bottom+6:r.top-h-6
}else{x=anchor.x;y=anchor.y}
menu.style.left=Math.round(Math.max(8,Math.min(x,window.innerWidth-w-8)))+"px"
menu.style.top=Math.round(Math.max(8,Math.min(y,window.innerHeight-h-8)))+"px"
menu.style.visibility="visible"
if(opener){rpgS.menuReturn=opener;const first=menu.querySelector(".rpg-menu-item:not(:disabled)");if(first)first.focus({preventScroll:true})}
setTimeout(()=>{document.addEventListener("mousedown",rpgMenuOutside,true);document.addEventListener("keydown",rpgMenuKey,true)},0)
}
function rpgModal(title,bodyHtml,opts){
opts=opts||{}
const el=document.createElement("div")
el.className="rpg-modal glass-panel"+(opts.cls?" "+opts.cls:"")
el.innerHTML=`<div class="rpg-modal-head"><div class="rpg-modal-title">${rpgEsc(title)}</div><div class="rpg-modal-tools"></div><button type="button" class="rpg-icon-btn" data-rpg-close title="Close"><i class="icon icon-close"></i></button></div><div class="rpg-modal-body">${bodyHtml||""}</div><div class="rpg-modal-foot"></div>`
openModal(el,opts.modal||{})
el.querySelector("[data-rpg-close]").addEventListener("click",()=>closeModal())
return {el,body:el.querySelector(".rpg-modal-body"),foot:el.querySelector(".rpg-modal-foot"),tools:el.querySelector(".rpg-modal-tools"),isOpen:()=>document.body.contains(el)}
}
function rpgFootBtn(modal,label,cls,fn){
const b=document.createElement("button")
b.type="button"
b.className="rpg-btn"+(cls?" "+cls:"")
b.textContent=label
b.addEventListener("click",fn)
modal.foot.appendChild(b)
return b
}

// ---- autosave ----
function rpgSaveStatus(){
return {errors:Object.keys(rpgS.errors).length>0,saving:rpgS.saving>0,pending:!!rpgS.dirtyReport||Object.keys(rpgS.dirtySections).length>0||!!(rpgS.findings&&rpgS.findings.isDirty&&rpgS.findings.isDirty())}
}
function rpgRenderSaveState(){
const el=rpgEl("rpgSaveState")
if(!el)return
const st=rpgSaveStatus(),info=rpgSaveStateInfo(st)
el.className="rpg-save-state "+info.cls
el.querySelector("span").textContent=info.label
const first=Object.keys(rpgS.errors)[0]
el.title=st.errors?"Could not save: "+rpgS.errors[first]+". Click to try again.":(st.pending||st.saving?"Changes are saved automatically. Ctrl+S saves now.":"All changes are saved")
el.disabled=!st.errors&&!st.pending
}
function rpgSchedule(key){
clearTimeout(rpgS.timers[key])
rpgS.timers[key]=setTimeout(()=>rpgSaveKey(key),RPG_SAVE_DELAY)
rpgRenderSaveState()
}
function rpgQueueReport(patch){
if(!rpgS.report)return
rpgS.dirtyReport=rpgMergePatch(rpgS.dirtyReport,patch)
rpgSchedule("report")
}
function rpgQueueSection(id,patch){
if(!rpgS.report)return
rpgS.dirtySections[id]=Object.assign(rpgS.dirtySections[id]||{},patch)
rpgSchedule("sec:"+id)
}
// One save at a time per entity; edits made while a save is in flight stay queued and go out in the next one.
function rpgSaveKey(key){
clearTimeout(rpgS.timers[key])
delete rpgS.timers[key]
const run=()=>{
const rep=rpgS.report
if(!rep)return true
let patch,call
if(key==="report"){
patch=rpgS.dirtyReport
if(!patch)return true
rpgS.dirtyReport=null
call=bridgeCall("reports.update",[rep.id,patch])
}else{
const id=Number(key.slice(4))
patch=rpgS.dirtySections[id]
if(!patch)return true
delete rpgS.dirtySections[id]
call=bridgeCall("reports.section_update",[id,patch])
}
rpgS.saving++
rpgRenderSaveState()
return call.then((res)=>{
rpgS.saving--
delete rpgS.errors[key]
if(rpgS.report===rep&&res&&res.updated_at)rep.updated_at=res.updated_at
rpgRenderSaveState()
return true
},(err)=>{
rpgS.saving--
// Put the failed patch back underneath whatever was typed since, so nothing is lost and a retry sends both.
if(rpgS.report===rep){
if(key==="report")rpgS.dirtyReport=rpgMergePatch(patch,rpgS.dirtyReport)
else{const id=Number(key.slice(4));if(rep.sections.some((s)=>s.id===id))rpgS.dirtySections[id]=Object.assign({},patch,rpgS.dirtySections[id]||{})}
rpgS.errors[key]=rpgErr(err,"save failed")
}
rpgRenderSaveState()
return false
})
}
const chain=(rpgS.chains[key]||Promise.resolve()).then(run,run)
rpgS.chains[key]=chain
return chain
}
function rpgSyncRich(){
const sec=rpgS.richSection
if(!rpgS.rich||!sec||!rpgS.report||rpgS.report.sections.indexOf(sec)<0)return
let html
try{html=rpgS.rich.getHTML()}catch(e){return}
if(typeof html==="string")rpgSecSet(sec,"content",html)
}
// Resolves true when everything is stored, false when something could not be saved (the changes stay queued).
function rpgFlush(){
if(!rpgS.report)return Promise.resolve(true)
rpgSyncRich()
const keys=new Set(Object.keys(rpgS.chains))
if(rpgS.dirtyReport)keys.add("report")
Object.keys(rpgS.dirtySections).forEach((id)=>keys.add("sec:"+id))
const jobs=Array.from(keys).map((k)=>(k==="report"?rpgS.dirtyReport:rpgS.dirtySections[k.slice(4)])?rpgSaveKey(k):rpgS.chains[k])
if(rpgS.findings&&typeof rpgS.findings.flush==="function")jobs.push(Promise.resolve().then(()=>rpgS.findings.flush()).then(()=>true,(err)=>{rpgS.errors.findings=rpgErr(err,"save failed");return false}))
return Promise.all(jobs).then((res)=>{
if(res.every((r)=>r!==false))delete rpgS.errors.findings
rpgRenderSaveState()
return res.every((r)=>r!==false)&&!Object.keys(rpgS.errors).length
})
}
function rpgIsDirty(){
const st=rpgSaveStatus()
return st.pending||st.saving||st.errors
}
function rpgDropPending(){
Object.keys(rpgS.timers).forEach((k)=>clearTimeout(rpgS.timers[k]))
rpgS.timers={};rpgS.dirtyReport=null;rpgS.dirtySections={};rpgS.errors={};rpgS.chains={}
rpgRenderSaveState()
}
// Before anything that replaces the open report: save, and if that fails let the user retry, discard or stay.
function rpgLeaveGuard(){
if(!rpgS.report)return Promise.resolve(true)
return rpgFlush().then((ok)=>{
if(ok)return true
const first=Object.keys(rpgS.errors)[0]
return appConfirm("Some changes to this report could not be saved"+(first?" ("+rpgS.errors[first]+")":"")+". Discard them?",{okLabel:"Discard changes",danger:true,extraLabel:"Try again",cancelLabel:"Keep editing"}).then((ans)=>{
if(ans==="extra")return rpgLeaveGuard()
if(ans===true){rpgDropPending();return true}
return false
})
})
}

// ---- list view ----
function rpgLoadList(){
if(!rpgHas("reports.list")){rpgS.list=[];rpgS.listError="The reporting backend is not available in this build.";rpgRenderList();return Promise.resolve()}
const deadlines=rpgHas("reports.deadlines")?bridgeCall("reports.deadlines",[]).catch(()=>null):Promise.resolve(null)
return Promise.all([bridgeCall("reports.list"),deadlines]).then((res)=>{rpgS.list=Array.isArray(res[0])?res[0]:[];if(res[1]&&typeof res[1]==="object")rpgS.deadlines=res[1];rpgS.listError="";rpgRenderList({keep:true})}).catch((err)=>{rpgS.listError=rpgErr(err,"Could not load the reports.");rpgRenderList()})
}
function rpgSevRowHtml(r,width){
const lay=rpgSevLayout(r.counts,r.total,width)
if(!lay.parts.length)return '<span class="rpg-dim">No findings yet</span>'
return `<span class="rpg-card-pills lv${lay.level}">${lay.parts.map((p)=>`<span class="rpg-sev rpg-sev-${p.id}" title="${rpgExactNum(p.n)} ${p.label}"><i></i><b>${p.text}</b>${lay.level===0?`<span>${p.short}</span>`:""}</span>`).join("")}</span>${lay.total?`<span class="rpg-card-total">${lay.total}</span>`:""}`
}
function rpgCardHtml(r,width){
const title=rpgClampText(r.title,300)||"Untitled report"
const client=rpgClampText(r.client,200),prof=rpgClampText(r.profile_name,200)
const sub=[client?`<bdi class="rpg-card-client" title="Client: ${rpgEsc(client)}">${rpgEsc(client)}</bdi>`:"",prof?`<bdi class="rpg-card-prof" title="Engagement: ${rpgEsc(prof)}">${rpgEsc(prof)}</bdi>`:""].filter(Boolean).join('<span class="rpg-card-dot" aria-hidden="true">&middot;</span>')
const total=Number(r.total)||0,stamp=rpgStampText(r.updated_at),made=rpgStampText(r.created_at)
return `<div class="rpg-card" data-id="${Number(r.id)}" tabindex="0" role="button" aria-label="Open report ${rpgEsc(rpgClampText(r.title,120)||"Untitled report")}" aria-keyshortcuts="Enter F2 Delete Shift+F10">
<div class="rpg-card-top"><span class="rpg-status rpg-status-${rpgEsc(r.status||"draft")}">${rpgEsc(rpgStatusLabel(r.status))}</span>${r.status==="final"?"":rpgDeadlineChip(rpgS.deadlines[String(r.id)],"rpg-deadline-card")}<span class="rpg-card-time" title="${rpgEsc((stamp?"Updated "+stamp:"")+(made?(stamp?", created ":"Created ")+made:""))}">${rpgEsc(rpgRelTime(r.updated_at))}</span></div>
<div class="rpg-card-title" dir="auto" title="${rpgEsc(rpgClampText(r.title,600)||"Untitled report")}">${rpgEsc(title)}</div>
<div class="rpg-card-sub">${sub||'<span class="rpg-dim">No client set</span>'}</div>
<div class="rpg-card-sev"${total?` title="${rpgExactNum(total)} finding${total===1?"":"s"}"`:""}>${rpgSevRowHtml(r,width)}</div>
<div class="rpg-card-actions">
<button type="button" class="rpg-btn rpg-btn-sm" data-act="open" tabindex="-1"><i class="icon icon-edit"></i><span>Open</span></button>
<span class="rpg-spacer"></span>
<button type="button" class="rpg-icon-btn" data-act="rename" tabindex="-1" title="Rename (F2)"><i class="icon icon-marker"></i></button>
<button type="button" class="rpg-icon-btn" data-act="duplicate" tabindex="-1" title="Duplicate"><i class="icon icon-copy"></i></button>
<button type="button" class="rpg-icon-btn" data-act="export" tabindex="-1" title="Export..."><i class="icon rpg-ic-export"></i></button>
<button type="button" class="rpg-icon-btn danger" data-act="delete" tabindex="-1" title="Delete (moves to the Recycle Bin)"><i class="icon icon-trash"></i></button>
</div></div>`
}
function rpgEmptyHtml(){
return `<div class="rpg-empty glass-panel">
<i class="icon icon-report rpg-empty-icon"></i>
<div class="rpg-empty-title">Write your penetration-test reports here</div>
<div class="rpg-empty-text">A report is built from a template (web application, internal or external network, cloud, mobile, red team, retest), your findings with CVSS scores, and the evidence you captured in the terminal. Export it as PDF, Word, HTML or Markdown when it is ready.</div>
<div class="rpg-empty-points">
<div><i class="icon icon-file"></i><span>Start from a template with professional boilerplate, or from a blank report.</span></div>
<div><i class="icon icon-target"></i><span>Link the report to a target profile so the scope fills itself in.</span></div>
<div><i class="icon icon-command-line"></i><span>Attach recorded terminal output and screenshots as evidence, or let the app draft a report from your sessions.</span></div>
</div>
<div class="rpg-empty-actions"><button type="button" class="rpg-btn rpg-btn-primary" data-act="new"><i class="icon icon-add"></i><span>New report</span></button><button type="button" class="rpg-btn" data-act="autogen"><span>Auto-generate from sessions...</span></button><button type="button" class="rpg-btn" data-act="import"><span>Import...</span></button></div>
</div>`
}
function rpgNoResultsHtml(){
const q=rpgClampText(rpgS.q,60)
const what=[q?`"${rpgEsc(q)}"`:"",rpgS.status?"status "+rpgEsc(rpgStatusLabel(rpgS.status)):""].filter(Boolean).join(" with ")
return `<div class="rpg-none rpg-noresults"><i class="icon icon-search"></i><div class="rpg-noresults-title">No report matches ${what||"the filter"}</div><div>${rpgS.list.length} report${rpgS.list.length===1?" is":"s are"} hidden by the search or the status filter.</div><button type="button" class="rpg-btn" data-act="clear-filters"><span>Clear filters</span></button></div>`
}
// Only the first cards are built; the rest follow in chunks as the list is scrolled (or from the button, which is also what
// the observer watches). Five hundred cards at once take the list about half a second to lay out.
function rpgCardsHtml(from,to){
let html=""
for(let i=from;i<to;i++)html+=rpgCardHtml(rpgS.rows[i],rpgS.cardW)
return html
}
function rpgMoreHtml(){
const left=rpgS.rows.length-rpgS.shown
return left>0?`<div class="rpg-more" id="rpgMore"><span>Showing ${rpgS.shown} of ${rpgS.rows.length}</span><button type="button" class="rpg-btn rpg-btn-sm" data-act="more">Show ${Math.min(left,RPG_CHUNK)} more</button></div>`:""
}
function rpgListUnobserve(){
if(rpgS.listIO){rpgS.listIO.disconnect();rpgS.listIO=null}
}
function rpgListObserve(){
const host=rpgEl("rpgList"),more=rpgEl("rpgMore")
if(!host||!more||typeof IntersectionObserver==="undefined")return
rpgS.listIO=new IntersectionObserver((entries)=>{if(entries.some((x)=>x.isIntersecting))rpgShowMore()},{root:host,rootMargin:"0px 0px 600px 0px"})
rpgS.listIO.observe(more)
}
function rpgShowMore(upTo){
const host=rpgEl("rpgList"),grid=host&&host.querySelector(".rpg-cards")
if(!grid||rpgS.shown>=rpgS.rows.length)return
const from=rpgS.shown
rpgS.shown=Math.min(rpgS.rows.length,Math.max(rpgChunkNext(from,rpgS.rows.length),Number(upTo)||0))
grid.insertAdjacentHTML("beforeend",rpgCardsHtml(from,rpgS.shown))
// Watching the new footer starts with a fresh report, so a footer that is still in view loads the next chunk too.
rpgListUnobserve()
const more=rpgEl("rpgMore")
if(more)more.outerHTML=rpgMoreHtml()
rpgListObserve()
}
function rpgListWidth(){
const host=rpgEl("rpgList")
return host?Math.max(0,host.clientWidth-4):0
}
function rpgFocusCard(id,quiet){
const host=rpgEl("rpgList"),card=host&&host.querySelector(`.rpg-card[data-id="${Number(id)}"]`)
if(card)card.focus({preventScroll:!!quiet})
return card
}
// opts.keep: the data was reloaded or the window resized - the scroll position and the cards already shown stay.
function rpgRenderList(opts){
opts=opts||{}
clearTimeout(rpgS.searchTimer)
const host=rpgEl("rpgList")
if(!host)return
const count=rpgEl("rpgListCount")
if(rpgS.listError||!rpgS.list.length){
rpgListUnobserve()
rpgS.rows=[];rpgS.shown=0;rpgS.listSig=""
host.innerHTML=rpgS.listError?`<div class="rpg-none error">${rpgEsc(rpgS.listError)}</div>`:rpgEmptyHtml()
if(count)count.textContent=""
return
}
const width=rpgListWidth()
const cardW=width?rpgCardInner(width):rpgS.cardW
// Relative times ("5m ago") are part of what is on screen, so an unchanged list is still repainted every ten minutes.
const sig=JSON.stringify([rpgS.q,rpgS.status,rpgS.sort,cardW,Math.floor(Date.now()/600000),rpgS.list,rpgS.deadlines])
if(opts.keep&&sig===rpgS.listSig&&host.firstElementChild)return
rpgS.listSig=sig
const active=document.activeElement&&host.contains(document.activeElement)?document.activeElement.closest(".rpg-card"):null
const focusId=active?Number(active.dataset.id):0
const keep=!!opts.keep&&!!host.querySelector(".rpg-cards"),scroll=host.scrollTop
// Kept: the cards down to a little below the visible part (and the focused one); those further down come back on scroll.
let last=0
if(keep){
const cards=host.querySelectorAll(".rpg-card"),limit=scroll+host.clientHeight+600
last=cards.length-1
for(let i=0;i<cards.length;i++){if(cards[i].offsetTop>limit){last=i;break}}
if(active)last=Math.max(last,Array.prototype.indexOf.call(cards,active))
}
const rows=rpgFilterReports(rpgS.list,rpgS.q,rpgS.status,rpgS.sort)
rpgListUnobserve()
rpgS.rows=rows
rpgS.cardW=cardW
rpgS.shown=rpgChunkFor(Math.min(last,rows.length-1),rows.length)
if(count){count.textContent=rows.length===rpgS.list.length?rpgCompactNum(rows.length)+(rows.length===1?" report":" reports"):rpgCompactNum(rows.length)+" of "+rpgCompactNum(rpgS.list.length);count.title=rpgExactNum(rows.length)+" of "+rpgExactNum(rpgS.list.length)+" reports shown"}
host.innerHTML=rows.length?`<div class="rpg-cards">${rpgCardsHtml(0,rpgS.shown)}</div>${rpgMoreHtml()}`:rpgNoResultsHtml()
host.scrollTop=keep?scroll:0
rpgListObserve()
if(focusId)rpgFocusCard(focusId,true)
}
function rpgListResized(){
clearTimeout(rpgS.resizeTimer)
rpgS.resizeTimer=setTimeout(()=>{
const host=rpgEl("rpgList"),width=rpgListWidth()
if(!host||!width||rpgS.view!=="list"||rpgCardInner(width)===rpgS.cardW||host.querySelector(".rpg-card-title-input"))return
rpgRenderList({keep:true})
},150)
}
function rpgClearFilters(){
rpgS.q="";rpgS.status=""
const search=rpgEl("rpgSearch"),status=rpgEl("rpgStatusFilter")
if(search)search.value=""
if(status)status.value=""
rpgRenderList()
if(search)search.focus()
}
function rpgCardMenu(id,at,kbd){
const card=document.querySelector(`.rpg-card[data-id="${Number(id)}"]`)
if(!card)return
const r=card.getBoundingClientRect()
if(kbd)rpgS.menuKbdAt=Date.now()
rpgOpenMenu(at||{x:Math.round(r.left+14),y:Math.round(r.top+44)},[{label:"Open",icon:"icon-edit",note:"Enter",fn:()=>rpgListAction("open",id)},{label:"Rename",icon:"icon-marker",note:"F2",fn:()=>rpgListAction("rename",id)},{label:"Duplicate",icon:"icon-copy",fn:()=>rpgListAction("duplicate",id)},{label:"Export...",icon:"rpg-ic-export",fn:()=>rpgListAction("export",id)},{sep:true},{label:"Delete",icon:"icon-trash",note:"Del",danger:true,fn:()=>rpgListAction("delete",id)}],{kbd:!!kbd})
}
// Keys on a focused card: arrows, Home/End and PageUp/PageDown move through the grid (loading further chunks when needed),
// Enter opens, F2 renames, Delete asks to delete, the menu key or Shift+F10 opens the card menu.
function rpgListKey(e){
const host=rpgEl("rpgList"),card=e.target
if(!host||!card.classList||!card.classList.contains("rpg-card")||e.ctrlKey||e.metaKey||e.altKey||rpgDialogOpen())return
const id=Number(card.dataset.id),k=e.key
if(k==="ContextMenu"||(k==="F10"&&e.shiftKey)){e.preventDefault();e.stopPropagation();rpgCardMenu(id,null,true);return}
if(e.shiftKey)return
if(k==="Enter"||k===" "){e.preventDefault();rpgOpen(id);return}
if(k==="Delete"){e.preventDefault();rpgListAction("delete",id);return}
if(k==="F2"){e.preventDefault();rpgListAction("rename",id);return}
if(!/^(Arrow(Left|Right|Up|Down)|Home|End|PageUp|PageDown)$/.test(k))return
e.preventDefault()
const cards=Array.from(host.querySelectorAll(".rpg-card")),cur=cards.indexOf(card)
let cols=0
while(cols<cards.length&&cards[cols].offsetTop===cards[0].offsetTop)cols++
const to=rpgNavIndex(cur,k,cols,rpgS.rows.length,Math.max(1,Math.floor(host.clientHeight/(card.offsetHeight+RPG_CARD_GAP))))
if(to===cur||to<0)return
if(to>=rpgS.shown)rpgShowMore(rpgChunkFor(to,rpgS.rows.length))
const next=host.querySelectorAll(".rpg-card")[to]
if(next){next.focus({preventScroll:true});next.scrollIntoView({block:"nearest"})}
}
function rpgOptional(name,method,label,args){
const mod=window[name]
if(mod&&typeof mod[method]==="function"){try{return mod[method].apply(mod,args||[])}catch(err){rpgToast(rpgErr(err,label+" failed"),true)}return}
rpgToast(label+" is not available in this build.",true)
}
function rpgExport(id){
const go=()=>rpgOptional("ReportExport","open","The export module",[id])
if(rpgS.report&&rpgS.report.id===id)rpgFlush().then(go)
else go()
}
function rpgDuplicate(id){
return bridgeCall("reports.duplicate",[id]).then((rep)=>{rpgToast("Report duplicated");return rpgLoadList().then(()=>rep)}).catch((err)=>rpgToast(rpgErr(err,"Could not duplicate the report"),true))
}
// A delete question about something the user named: the name goes in the dialog body, where a long one without spaces can
// wrap and is cut after three lines.
function rpgConfirmNamed(question,name,note){
const asked=appConfirm(question,{okLabel:"Delete",danger:true,bodyHtml:`<div class="rpg-confirm-name" dir="auto" title="${rpgEsc(rpgClampText(name,600))}">${rpgEsc(rpgClampText(name,300))}</div><div class="rpg-confirm-note">${rpgEsc(note)}</div>`})
// The dialog does not take the focus by itself: without this a question asked from the keyboard could not be answered from it.
const all=document.querySelectorAll(".confirm-overlay"),overlay=all[all.length-1]
if(overlay){
const ok=overlay.querySelector(".confirm-ok"),cancel=overlay.querySelector(".confirm-cancel")
if(ok)ok.focus()
overlay.addEventListener("keydown",(e)=>{if(e.key==="Escape"&&cancel){e.preventDefault();e.stopPropagation();cancel.click()}})
}
return asked
}
function rpgDelete(id,title){
return rpgConfirmNamed("Delete this report?",title||"Untitled report","It moves to the Recycle Bin with its sections and findings.").then((yes)=>{
if(!yes)return false
return bridgeCall("reports.delete",[id]).then(()=>{rpgToast("Report moved to the Recycle Bin");return true}).catch((err)=>{rpgToast(rpgErr(err,"Could not delete the report"),true);return false})
})
}
// Rename a report from the list: the card title becomes an inline field (Enter saves, Esc cancels).
function rpgRenameReportInline(id){
const card=document.querySelector(`.rpg-card[data-id="${Number(id)}"]`)
const t=card&&card.querySelector(".rpg-card-title")
if(!t||card.querySelector(".rpg-card-title-input"))return
const row=rpgS.list.find((r)=>r.id===Number(id))
const old=(row&&row.title)||t.textContent.trim()
const input=document.createElement("input")
input.type="text";input.className="rpg-input rpg-card-title-input";input.dir="auto";input.maxLength=300;input.value=old;input.setAttribute("aria-label","Report title")
t.replaceWith(input);input.focus();input.select()
let done=false
const finish=(save)=>{
if(done)return
done=true
const v=input.value.trim()
// The card takes the focus back only when the field still had it (Enter or Esc), not when the user clicked elsewhere.
const back=document.activeElement===input
const restore=()=>{if(input.isConnected)input.replaceWith(t);if(back&&card.isConnected)card.focus({preventScroll:true})}
if(!save||!v||v===old){restore();return}
bridgeCall("reports.update",[Number(id),{title:v}]).then(()=>{
if(row)row.title=v
t.textContent=rpgClampText(v,300);t.title=rpgClampText(v,600)
card.setAttribute("aria-label","Open report "+rpgClampText(v,120))
rpgS.listSig=""
restore();rpgToast("Report renamed")
}).catch((err)=>{restore();rpgToast(rpgErr(err,"Could not rename the report"),true)})
}
input.addEventListener("keydown",(e)=>{if(e.key==="Enter"){e.preventDefault();finish(true)}else if(e.key==="Escape"){e.preventDefault();e.stopPropagation();finish(false)}})
input.addEventListener("blur",()=>finish(true))
input.addEventListener("click",(e)=>e.stopPropagation())
}
function rpgListAction(act,id){
const row=rpgS.list.find((r)=>r.id===id)
if(act==="new")return rpgNewReport()
// The arrow beside "New report" holds the other ways to start a report.
if(act==="create-menu"){const b=document.querySelector(".rpg-create-more");const r=b?b.getBoundingClientRect():{left:0,bottom:0};return rpgOpenMenu({x:Math.round(r.left),y:Math.round(r.bottom+4)},[{label:"Blank or from a template...",icon:"icon-add",fn:()=>rpgNewReport()},{label:"Auto-generate from sessions...",icon:"icon-command-line",fn:()=>rpgListAction("autogen")},{label:"Import...",icon:"rpg-ic-import",fn:()=>rpgListAction("import")}])}
if(act==="import")return rpgOptional("ReportExport","openImport","The import module",[{}])
if(act==="autogen")return rpgOptional("ReportEvidence","openAutogen","Auto-generate",[{}])
if(act==="library")return rpgOptional("ReportFindings","openLibrary","The findings library")
if(act==="evidence")return rpgOptional("ReportEvidence","openManager","The evidence manager")
if(act==="templates")return rpgOpenTemplates()
if(act==="clear-filters")return rpgClearFilters()
if(act==="more"){const from=rpgS.shown;rpgShowMore();const first=document.querySelectorAll("#rpgList .rpg-card")[from];if(first)first.focus({preventScroll:true});return}
if(!row)return
if(act==="open")return rpgOpen(id)
if(act==="rename")return rpgRenameReportInline(id)
if(act==="duplicate")return rpgDuplicate(id)
if(act==="export")return rpgExport(id)
if(act==="delete"){
// After the delete the focus lands on the neighbouring card, so a keyboard user can carry on from there.
const at=rpgS.rows.findIndex((r)=>r.id===id),near=rpgS.rows[at+1]||rpgS.rows[at-1]
const idle=()=>{const a=document.activeElement,host=rpgEl("rpgList");return !a||a===document.body||(host&&host.contains(a))}
return rpgDelete(id,row.title).then((ok)=>{
if(!ok){if(idle())rpgFocusCard(id,true);return}
return rpgLoadList().then(()=>{if(near&&idle())rpgFocusCard(near.id,true)})
})
}
}
function rpgShowView(view){
rpgS.view=view
const list=rpgEl("rpgListView"),ed=rpgEl("rpgEditor")
if(list)list.classList.toggle("hidden",view!=="list")
if(ed)ed.classList.toggle("hidden",view!=="editor")
}

// ---- new report / templates ----
function rpgLoadSources(profileId){
if(!rpgHas("reports.sources"))return Promise.resolve({profiles:[],targets:[],notes:[]})
return bridgeCall("reports.sources",profileId?[profileId]:[]).then((src)=>{
src=src||{}
return {profiles:src.profiles||[],targets:src.targets||[],notes:src.notes||[]}
})
}
function rpgProfileOptions(profiles,current){
const known=(profiles||[]).some((p)=>String(p.id)===String(current||""))
return `<option value="">None</option>`+(profiles||[]).map((p)=>`<option value="${rpgEsc(p.id)}"${String(p.id)===String(current||"")?" selected":""}>${rpgEsc(p.name)}${p.active?" (active)":""}</option>`).join("")+(current&&!known?`<option value="${rpgEsc(current)}" selected>Unknown profile</option>`:"")
}
function rpgTplCardHtml(t,selected){
return `<button type="button" class="rpg-tpl${selected?" active":""}" data-id="${rpgEsc(t.id)}"><span class="rpg-tpl-name" dir="auto" title="${rpgEsc(rpgClampText(t.name,600))}">${rpgEsc(t.name)}</span><span class="rpg-tpl-desc" dir="auto">${rpgEsc(t.description||"")}</span><span class="rpg-tpl-meta">${Number(t.sections)||0} section${Number(t.sections)===1?"":"s"}${t.builtin?"":'<span class="rpg-tag">yours</span>'}</span></button>`
}
function rpgCreateReport(payload){
return bridgeCall("reports.create",[payload]).then((rep)=>{
rpgLoadList()
return rpgShowReport(rep).then(()=>rep)
})
}
function rpgNewReport(opts){
opts=opts||{}
if(opts.templateId){
const payload={title:opts.title||"Untitled report",template_id:opts.templateId}
if(opts.profileId)payload.profile_id=opts.profileId
if(opts.client)payload.meta={client:opts.client}
return rpgLeaveGuard().then((ok)=>ok?rpgCreateReport(payload).catch((err)=>{rpgToast(rpgErr(err,"Could not create the report"),true);return null}):null)
}
return rpgLeaveGuard().then((ok)=>{
if(!ok)return null
return new Promise((resolve)=>{
let done=false
const finish=(v)=>{if(!done){done=true;resolve(v)}}
const m=rpgModal("New report",`<div class="rpg-form-label">Template</div><div class="rpg-tpl-grid" id="rpgTplGrid"><div class="rpg-none">Loading templates...</div></div>
<div class="rpg-grid rpg-grid-modal">
<label class="rpg-field rpg-span2"><span class="rpg-field-label">Report title</span><input type="text" class="rpg-input" id="rpgNewTitle" maxlength="200" placeholder="e.g. ACME Web Application Penetration Test" value="${rpgEsc(opts.title||"")}"></label>
<label class="rpg-field"><span class="rpg-field-label">Client</span><input type="text" class="rpg-input" id="rpgNewClient" maxlength="200" placeholder="Client organisation" value="${rpgEsc(opts.client||"")}"></label>
<div class="rpg-field"><span class="rpg-field-label">Engagement (target profile)</span><select class="rpg-select" id="rpgNewProfile"><option value="">None</option></select></div>
</div><div class="rpg-hint">Linking a target profile fills the scope with that profile's targets. You can change everything later.</div>`,{cls:"rpg-modal-new",modal:{onBeforeClose:()=>{finish(null);return true}}})
let tplId="",templates=[]
const grid=m.body.querySelector("#rpgTplGrid")
const paint=()=>{grid.innerHTML=templates.length?templates.map((t)=>rpgTplCardHtml(t,t.id===tplId)).join(""):'<div class="rpg-none">No templates found. The report starts empty.</div>'}
grid.addEventListener("click",(e)=>{const b=e.target.closest(".rpg-tpl");if(!b)return;tplId=b.dataset.id;paint()})
grid.addEventListener("dblclick",(e)=>{if(e.target.closest(".rpg-tpl"))create()})
bridgeCall("reports.templates").then((rows)=>{templates=rows||[];tplId=(templates.find((t)=>t.id===opts.preselect)||templates.find((t)=>t.id==="web_app")||templates[0]||{}).id||"";paint()}).catch((err)=>{grid.innerHTML=`<div class="rpg-none error">${rpgEsc(rpgErr(err,"Could not load the templates"))}</div>`})
rpgLoadSources().then((src)=>{const sel=m.body.querySelector("#rpgNewProfile");if(sel)sel.innerHTML=rpgProfileOptions(src.profiles,opts.profileId||"")}).catch(()=>{})
rpgFootBtn(m,"Cancel","",()=>closeModal())
const ok=rpgFootBtn(m,"Create report","rpg-btn-primary",()=>create())
function create(){
if(ok.disabled)return
const title=m.body.querySelector("#rpgNewTitle").value.trim()||"Untitled report"
const client=m.body.querySelector("#rpgNewClient").value.trim()
const payload={title,template_id:tplId||"blank",profile_id:m.body.querySelector("#rpgNewProfile").value||""}
if(client)payload.meta={client}
ok.disabled=true
rpgCreateReport(payload).then((rep)=>{finish(rep);closeModal(true)}).catch((err)=>{ok.disabled=false;rpgToast(rpgErr(err,"Could not create the report"),true)})
}
m.body.addEventListener("keydown",(e)=>{if(e.key==="Enter"&&e.target.tagName==="INPUT"){e.preventDefault();create()}})
setTimeout(()=>{const t=m.body.querySelector("#rpgNewTitle");if(t)t.focus()},30)
})
})
}
function rpgOpenTemplates(){
const m=rpgModal("Report templates",'<div class="rpg-hint">Built-in templates cannot be changed. To make your own, open a report and choose "Save as template".</div><div class="rpg-rows" id="rpgTplRows"><div class="rpg-none">Loading...</div></div>',{cls:"rpg-modal-mid"})
const rows=m.body.querySelector("#rpgTplRows")
const load=()=>bridgeCall("reports.templates").then((list)=>{
if(!m.isOpen())return
list=list||[]
rows.innerHTML=list.length?list.map((t)=>`<div class="rpg-row" data-id="${rpgEsc(t.id)}"><div class="rpg-row-main"><div class="rpg-row-title">${rpgEsc(t.name)}${t.builtin?'<span class="rpg-tag">built-in</span>':'<span class="rpg-tag">yours</span>'}</div><div class="rpg-row-sub">${rpgEsc(t.description||"")}${t.description?" &middot; ":""}${Number(t.sections)||0} sections</div></div><button type="button" class="rpg-btn rpg-btn-sm" data-act="use">Use</button>${t.builtin?"":'<button type="button" class="rpg-icon-btn danger" data-act="delete" title="Delete template"><i class="icon icon-trash"></i></button>'}</div>`).join(""):'<div class="rpg-none">No templates.</div>'
rows._list=list
}).catch((err)=>{rows.innerHTML=`<div class="rpg-none error">${rpgEsc(rpgErr(err,"Could not load the templates"))}</div>`})
rows.addEventListener("click",(e)=>{
const btn=e.target.closest("[data-act]"),row=e.target.closest(".rpg-row")
if(!btn||!row)return
const t=(rows._list||[]).find((x)=>x.id===row.dataset.id)
if(!t)return
if(btn.dataset.act==="use"){closeModal(true);rpgNewReport({preselect:t.id})}
if(btn.dataset.act==="delete")rpgConfirmNamed("Delete this template?",t.name,"Reports already created from it are not affected.").then((yes)=>{if(yes)bridgeCall("reports.template_delete",[t.id]).then(load).catch((err)=>rpgToast(rpgErr(err,"Could not delete the template"),true))})
})
rpgFootBtn(m,"Import templates...","",()=>{closeModal(true);rpgOptional("ReportExport","openImport","The import module",[{kind:"templates"}])})
rpgFootBtn(m,"Export templates...","",()=>{
if(window.ReportExport&&typeof ReportExport.exportTemplates==="function")return ReportExport.exportTemplates()
if(!rpgHas("reportsIO.export_templates"))return rpgToast("The export module is not available in this build.",true)
bridgeCall("reportsIO.export_templates",[]).then((path)=>{if(path)rpgToast("Templates exported")}).catch((err)=>rpgToast(rpgErr(err,"Export failed"),true))
})
rpgFootBtn(m,"Close","rpg-btn-primary",()=>closeModal())
load()
}
function rpgSaveAsTemplate(){
const rep=rpgS.report
if(!rep)return
const m=rpgModal("Save as template",`<div class="rpg-hint">Saves this report's sections and their text as a template for new reports. Findings and client details are not included.</div>
<label class="rpg-field"><span class="rpg-field-label">Template name</span><input type="text" class="rpg-input" id="rpgTplName" maxlength="120" value="${rpgEsc((rep.title||"Report")+" template")}"></label>
<label class="rpg-field"><span class="rpg-field-label">Description</span><input type="text" class="rpg-input" id="rpgTplDesc" maxlength="240" placeholder="When to use this template"></label>`,{cls:"rpg-modal-small"})
rpgFootBtn(m,"Cancel","",()=>closeModal())
const ok=rpgFootBtn(m,"Save template","rpg-btn-primary",()=>{
const name=m.body.querySelector("#rpgTplName").value.trim()
if(!name){rpgToast("Give the template a name",true);return}
ok.disabled=true
rpgFlush().then((ok)=>{if(!ok)throw new Error("Some changes could not be saved, so the template would be out of date.")}).then(()=>bridgeCall("reports.template_save_from_report",[rep.id,name,m.body.querySelector("#rpgTplDesc").value.trim()])).then(()=>{closeModal(true);rpgToast("Template saved")}).catch((err)=>{ok.disabled=false;rpgToast(rpgErr(err,"Could not save the template"),true)})
})
setTimeout(()=>{const i=m.body.querySelector("#rpgTplName");if(i){i.focus();i.select()}},30)
}

// ---- editor: open / header ----
function rpgNormReport(rep){
rep.meta=rep.meta||{};rep.branding=rep.branding||{};rep.options=rep.options||{}
rep.sections=(rep.sections||[]).slice().sort((a,b)=>(a.position||0)-(b.position||0))
rep.findings=rep.findings||[]
rep.versions=rep.versions||[]
if(!rep.stats||!rep.stats.counts)rep.stats=rpgCountSeverities(rep.findings)
return rep
}
function rpgShowReport(rep,entry){
rpgTeardownEntry(true)
rpgDropPending()
rpgS.report=rpgNormReport(rep)
rpgS.hist=rpgHistNew()
rpgS.sources=null
rpgS.entry=""
rpgShowView("editor")
rpgRenderHead()
rpgRenderOutline()
let key=entry||"details"
if(key!=="details"&&key!=="branding"&&key!=="timeline"&&!/^sec:/.test(key)){const s=rpgS.report.sections.find((x)=>x.kind===key);key=s?"sec:"+s.id:"details"}
return rpgSelectEntry(key,true)
}
function rpgOpen(reportId,opts){
opts=opts||{}
const token=++rpgS.opening
const nav=rpgPageActive()||typeof goToPage!=="function"?Promise.resolve():Promise.resolve(goToPage("reporting"))
return nav.then(()=>initReporting()).then(()=>rpgLeaveGuard()).then((ok)=>{
if(!ok)return null
return bridgeCall("reports.get",[Number(reportId)]).then((rep)=>{
if(token!==rpgS.opening)return rep
return rpgShowReport(rep,opts.entry).then(()=>rep)
})
}).catch((err)=>{rpgToast(rpgErr(err,"Could not open the report"),true);return null})
}
function rpgBackToList(){
return rpgLeaveGuard().then((ok)=>{
if(!ok)return false
rpgTeardownEntry(true)
rpgDropPending()
rpgS.report=null
rpgShowView("list")
rpgLoadList()
return true
})
}
function rpgRenderRisk(){
const el=rpgEl("rpgRisk"),rep=rpgS.report
if(!el||!rep)return
const st=rep.stats||rpgCountSeverities(rep.findings)
el.innerHTML=rpgSevPills(st.counts,{all:true,short:true})
el.title=`${rpgExactNum(st.total)} finding${st.total===1?"":"s"}, ${rpgExactNum(st.open)} open. Click to open the findings.`
}
function rpgRenderHead(){
const rep=rpgS.report
if(!rep)return
const title=rpgEl("rpgTitle"),status=rpgEl("rpgStatus")
if(title&&document.activeElement!==title)title.value=rep.title||""
if(title&&title.parentElement)title.parentElement.title=(rpgClampText(rep.title,600)||"Untitled report")+" (click to rename)"
if(status){status.value=rep.status||"draft";status.dataset.status=rep.status||"draft";rpgPaintStatusSelect()}
rpgRenderRisk()
rpgRenderDeadline()
rpgRenderUndo()
rpgRenderSaveState()
}
function rpgPaintStatusSelect(){
const status=rpgEl("rpgStatus")
if(!status)return
const trigger=status.nextElementSibling
if(trigger&&trigger.classList.contains("ui-select-trigger"))trigger.dataset.status=status.value
}
function rpgFindingsChanged(findings){
const rep=rpgS.report
if(!rep)return
if(Array.isArray(findings))rep.findings=findings
rep.stats=rpgCountSeverities(rep.findings)
rpgRenderRisk()
rpgRenderOutline()
rpgRenderSaveState()
}
function rpgOpenMore(anchor){
const rep=rpgS.report
if(!rep)return
rpgOpenMenu(anchor,[
{label:"Versions...",icon:"icon-clock",fn:()=>rpgFlush().then(rpgOpenVersions)},
{label:"Save as template...",icon:"icon-save",fn:rpgSaveAsTemplate},
{label:"Manage templates...",icon:"icon-file",fn:()=>rpgFlush().then(rpgOpenTemplates)},
{sep:true},
{label:"Findings library",icon:"icon-list",fn:()=>rpgOptional("ReportFindings","openLibrary","The findings library")},
{label:"Evidence manager",icon:"icon-image",fn:()=>rpgOptional("ReportEvidence","openManager","The evidence manager")},
{sep:true},
{label:"Duplicate report",icon:"icon-copy",fn:()=>rpgFlush().then((ok)=>ok?rpgDuplicate(rep.id):rpgToast("Save the report first: some changes could not be saved.",true))},
{label:"Delete report",icon:"icon-trash",danger:true,fn:()=>rpgDelete(rep.id,rep.title).then((ok)=>{if(ok){rpgDropPending();rpgTeardownEntry(true);rpgS.report=null;rpgShowView("list");rpgLoadList()}})}
])
}

// ---- editor: outline ----
function rpgOutlineRowHtml(s,n){
const info=rpgKindInfo(s.kind)
const count=s.kind==="findings"&&rpgS.report.findings.length?`<span class="rpg-ol-count" title="${rpgExactNum(rpgS.report.findings.length)} findings">${rpgCompactNum(rpgS.report.findings.length)}</span>`:""
return `<div class="rpg-ol-row${rpgS.entry==="sec:"+s.id?" active":""}${s.hidden?" off":""}" data-id="${Number(s.id)}" tabindex="0" title="${rpgEsc(info.label)}${s.hidden?" (hidden: left out of the export)":""}">
<span class="rpg-ol-grip" title="Drag to reorder"><i class="icon icon-grip"></i></span>
<span class="rpg-ol-num">${n}</span>
<span class="rpg-ol-title">${rpgEsc(s.title||info.label)}</span>${count}${info.auto?'<span class="rpg-tag" title="Part of this section is generated when you export">auto</span>':""}
<span class="rpg-ol-tools"><button type="button" class="rpg-ol-btn" data-act="hide" title="${s.hidden?"Show in the report":"Hide from the report"}"><i class="icon ${s.hidden?"rpg-ic-eye-off":"rpg-ic-eye"}"></i></button><button type="button" class="rpg-ol-btn danger" data-act="delete" title="Delete section"><i class="icon icon-trash"></i></button></span>
</div>`
}
function rpgRenderOutline(){
const rep=rpgS.report,list=rpgEl("rpgOutlineList"),fixed=rpgEl("rpgOutlineFixed")
if(!rep||!list||!fixed)return
fixed.innerHTML=[["details","icon-info","Details"],["branding","icon-color","Branding & cover"],["timeline","rpg-ic-flag","Timeline"]].map((e)=>`<button type="button" class="rpg-ol-fixed${rpgS.entry===e[0]?" active":""}" data-entry="${e[0]}"><i class="icon ${e[1]}"></i><span>${e[2]}</span></button>`).join("")
const scroll=list.scrollTop
let n=0
list.innerHTML=rep.sections.length?rep.sections.map((s)=>rpgOutlineRowHtml(s,s.hidden?"":++n)).join(""):'<div class="rpg-none">No sections yet. Add one below.</div>'
list.scrollTop=scroll
const quick=rpgEl("rpgQuickAdd")
if(quick)quick.innerHTML=rpgQuickAddHtml()
}
function rpgSectionById(id){
return rpgS.report?rpgS.report.sections.find((s)=>s.id===Number(id)):null
}
function rpgCurrentSection(){
return /^sec:/.test(rpgS.entry)?rpgSectionById(rpgS.entry.slice(4)):null
}
function rpgApplyOrder(ids){
const rep=rpgS.report
if(!rep)return
const by={},before=rep.sections.map((s)=>s.id)
rep.sections.forEach((s)=>{by[s.id]=s})
rep.sections=ids.map((id)=>by[id]).filter(Boolean)
rep.sections.forEach((s,i)=>{s.position=i})
rpgRecord({type:"sec-order",label:"reorder the sections",before,after:rep.sections.map((s)=>s.id)})
rpgRenderOutline()
bridgeCall("reports.sections_reorder",[rep.id,rep.sections.map((s)=>s.id)]).catch((err)=>rpgToast(rpgErr(err,"Could not save the new order"),true))
}
function rpgMoveSection(id,delta){
const ids=rpgS.report.sections.map((s)=>s.id),from=ids.indexOf(Number(id))
if(from<0||from+delta<0||from+delta>=ids.length)return
rpgApplyOrder(rpgMoveItem(ids,from,from+delta))
const row=rpgEl("rpgOutlineList").querySelector(`.rpg-ol-row[data-id="${Number(id)}"]`)
if(row)row.focus()
}
function rpgToggleHidden(id){
const s=rpgSectionById(id)
if(!s)return
rpgSecSet(s,"hidden",!s.hidden)
rpgRenderOutline()
const box=rpgEl("rpgSecInclude")
if(box&&rpgCurrentSection()===s)box.checked=!s.hidden
}
function rpgDeleteSection(id){
const s=rpgSectionById(id)
if(!s)return
const info=rpgKindInfo(s.kind)
const extra=s.kind==="findings"?" The findings themselves stay in the report, but they are only exported when a Detailed findings section exists.":""
appConfirm(`Delete the section "${s.title||info.label}" and its text?${extra}`,{okLabel:"Delete",danger:true}).then((yes)=>{
if(!yes)return
const current=rpgCurrentSection()===s
const drop=()=>{
rpgDropSectionSaves(s.id)
return (rpgS.chains["sec:"+s.id]||Promise.resolve()).then(()=>bridgeCall("reports.section_delete",[s.id])).then(()=>{
const rep=rpgS.report
if(!rep)return
const at=rep.sections.indexOf(s)
if(at>=0){rep.sections.splice(at,1);rpgRecord({type:"sec-del",label:`delete section '${rpgSecName(s)}'`,sec:rpgClone(s),index:at})}
rpgRenderOutline()
rpgRenderSaveState()
if(current){rpgS.entry="";const next=rep.sections[Math.min(at,rep.sections.length-1)];rpgSelectEntry(next?"sec:"+next.id:"details",true)}
}).catch((err)=>rpgToast(rpgErr(err,"Could not delete the section"),true))
}
if(current)rpgTeardownEntry().then(drop)
else drop()
})
}
function rpgRenameSection(id){
const s=rpgSectionById(id),list=rpgEl("rpgOutlineList")
const row=list&&list.querySelector(`.rpg-ol-row[data-id="${Number(id)}"]`)
if(!s||!row||row.querySelector("input"))return
const span=row.querySelector(".rpg-ol-title")
const input=document.createElement("input")
input.type="text";input.className="rpg-ol-input";input.maxLength=200;input.value=s.title||""
span.replaceWith(input)
row.classList.add("renaming")
input.focus();input.select()
let done=false
const finish=(save)=>{
if(done)return
done=true
const v=input.value.trim()
if(save&&v&&v!==s.title){
rpgSecSet(s,"title",v)
rpgHistSeal(rpgS.hist)
const t=rpgEl("rpgSecTitle")
if(t&&rpgCurrentSection()===s)t.value=v
}
rpgRenderOutline()
}
input.addEventListener("keydown",(e)=>{e.stopPropagation();if(e.key==="Enter"){e.preventDefault();finish(true)}else if(e.key==="Escape"){e.preventDefault();finish(false)}})
input.addEventListener("blur",()=>finish(true))
}
function rpgSectionMenu(id,pos){
const s=rpgSectionById(id)
if(!s)return
const ids=rpgS.report.sections.map((x)=>x.id),at=ids.indexOf(s.id)
rpgOpenMenu(pos,[
{label:"Rename",icon:"icon-edit",fn:()=>rpgRenameSection(id)},
{label:s.hidden?"Show in the report":"Hide from the report",icon:s.hidden?"rpg-ic-eye":"rpg-ic-eye-off",fn:()=>rpgToggleHidden(id)},
{sep:true},
{label:"Move up",icon:"icon-arrow-up",disabled:at<=0,fn:()=>rpgMoveSection(id,-1)},
{label:"Move down",icon:"icon-arrow-down",disabled:at>=ids.length-1,fn:()=>rpgMoveSection(id,1)},
{sep:true},
{label:"Delete section",icon:"icon-trash",danger:true,fn:()=>rpgDeleteSection(id)}
])
}
function rpgAddSection(k){
const rep=rpgS.report
if(!rep)return Promise.resolve(null)
const cur=rpgCurrentSection()
// No content is sent: the server starts the section with the boilerplate for its kind.
const payload={kind:k.kind,title:k.kind==="custom"?"New section":k.label}
const want=rpgInsertIndex(rep.sections,cur?cur.id:null,k.kind)
payload.after_id=want>0?rep.sections[want-1].id:0
return bridgeCall("reports.section_add",[rep.id,payload]).then((sec)=>{
if(rpgS.report!==rep||!sec)return null
const prev=rep.sections.findIndex((s)=>s.id===payload.after_id)
const at=payload.after_id?(prev>=0?prev+1:rep.sections.length):0
rep.sections.splice(at,0,sec)
rep.sections.forEach((s,i)=>{s.position=i})
rpgRecord({type:"sec-add",label:`add section '${rpgSecName(sec)}'`,sec:rpgClone(sec),index:at})
return rpgSelectEntry("sec:"+sec.id).then(()=>{
const row=rpgEl("rpgOutlineList").querySelector(`.rpg-ol-row[data-id="${sec.id}"]`)
if(row&&row.scrollIntoView)row.scrollIntoView({block:"nearest"})
if(k.kind==="custom"){const t=rpgEl("rpgSecTitle");if(t){t.focus();t.select()}}
return sec
})
}).catch((err)=>{rpgToast(rpgErr(err,"Could not add the section"),true);return null})
}
// Pointer-based reordering: HTML5 drag and drop is unreliable in WebKitGTK. A press that does not move is a click (select).
function rpgOutlinePointerDown(e){
if(e.button!==undefined&&e.button!==0)return
const row=e.target.closest(".rpg-ol-row")
if(!row||e.target.closest("button,input"))return
const list=rpgEl("rpgOutlineList"),id=Number(row.dataset.id)
const startY=e.clientY,startScroll=list.scrollTop
let dragging=false,line=null,slot=-1
const rows=()=>Array.from(list.querySelectorAll(".rpg-ol-row"))
const cleanup=()=>{
window.removeEventListener("pointermove",move,true)
window.removeEventListener("pointerup",up,true)
window.removeEventListener("pointercancel",cancel,true)
document.removeEventListener("keydown",key,true)
row.classList.remove("dragging");row.style.transform=""
list.classList.remove("drag-active")
if(line)line.remove()
}
const move=(ev)=>{
if(!dragging){
if(Math.abs(ev.clientY-startY)<5)return
dragging=true
row.classList.add("dragging");list.classList.add("drag-active")
line=document.createElement("div");line.className="rpg-ol-dropline";list.appendChild(line)
}
ev.preventDefault()
const box=list.getBoundingClientRect()
if(ev.clientY<box.top+26)list.scrollTop-=10
else if(ev.clientY>box.bottom-26)list.scrollTop+=10
row.style.transform=`translateY(${ev.clientY-startY+list.scrollTop-startScroll}px)`
const all=rows(),base=box.top-list.scrollTop
slot=rpgDropIndex(all.map((r)=>base+r.offsetTop+r.offsetHeight/2),ev.clientY)
const last=all[all.length-1]
line.style.top=(slot<all.length?all[slot].offsetTop:last.offsetTop+last.offsetHeight)-1+"px"
}
const up=()=>{
const was=dragging
cleanup()
if(!was){rpgSelectEntry("sec:"+id);return}
const ids=rpgS.report.sections.map((s)=>s.id),from=ids.indexOf(id)
if(from<0||slot<0)return
const to=rpgSlotToIndex(from,slot)
if(to!==from)rpgApplyOrder(rpgMoveItem(ids,from,to))
}
const cancel=()=>cleanup()
const key=(ev)=>{if(ev.key==="Escape"&&dragging){ev.preventDefault();ev.stopPropagation();cleanup()}}
window.addEventListener("pointermove",move,true)
window.addEventListener("pointerup",up,true)
window.addEventListener("pointercancel",cancel,true)
document.addEventListener("keydown",key,true)
}
function rpgOutlineKey(e){
const row=e.target.closest(".rpg-ol-row")
if(!row||e.target.tagName==="INPUT")return
const id=Number(row.dataset.id)
if(e.key==="Enter"||e.key===" "){e.preventDefault();rpgSelectEntry("sec:"+id)}
else if(e.key==="F2"){e.preventDefault();rpgRenameSection(id)}
else if(e.altKey&&e.key==="ArrowUp"){e.preventDefault();rpgMoveSection(id,-1)}
else if(e.altKey&&e.key==="ArrowDown"){e.preventDefault();rpgMoveSection(id,1)}
else if(e.key==="ArrowDown"||e.key==="ArrowUp"){
const next=e.key==="ArrowDown"?row.nextElementSibling:row.previousElementSibling
if(next&&next.classList.contains("rpg-ol-row")){e.preventDefault();next.focus()}
}
}

// ---- editor: entries ----
function rpgTeardownEntry(sync){
rpgSyncRich()
const rich=rpgS.rich,mount=rpgS.findings,linked=rpgS.targets
rpgS.rich=null;rpgS.richSection=null;rpgS.chart=null;rpgS.targets=null
if(linked&&typeof linked.destroy==="function"){try{linked.destroy()}catch(e){}}
clearInterval(rpgS.findingsPoll)
if(rpgS.tlObserver){rpgS.tlObserver.disconnect();rpgS.tlObserver=null}
if(rich&&typeof rich.destroy==="function"){try{rich.destroy()}catch(e){}}
if(!mount)return Promise.resolve(true)
rpgS.findings=null
const kill=()=>{try{if(typeof mount.destroy==="function")mount.destroy()}catch(e){}}
if(sync){try{if(typeof mount.flush==="function")Promise.resolve(mount.flush()).catch(()=>{})}catch(e){}kill();return Promise.resolve(true)}
return Promise.resolve().then(()=>typeof mount.flush==="function"?mount.flush():null).then(()=>{kill();return true},(err)=>{rpgS.findings=mount;rpgToast(rpgErr(err,"Could not save the finding"),true);return false})
}
function rpgSelectEntry(key,force){
if(!rpgS.report)return Promise.resolve()
if(key===rpgS.entry&&!force)return Promise.resolve()
return rpgTeardownEntry().then((ok)=>{
if(!ok||!rpgS.report)return
rpgFlush()
rpgHistSeal(rpgS.hist)
rpgS.entry=key
rpgRenderOutline()
rpgRenderEntry()
})
}
function rpgRenderEntry(){
const main=rpgEl("rpgMain"),rep=rpgS.report
if(!main||!rep)return
main.scrollTop=0
main.className="rpg-main"
if(rpgS.entry==="details")return rpgRenderDetails(main)
if(rpgS.entry==="branding")return rpgRenderBranding(main)
if(rpgS.entry==="timeline")return rpgRenderTimelinePane(main)
const sec=rpgCurrentSection()
if(!sec){rpgS.entry="details";rpgRenderOutline();return rpgRenderDetails(main)}
rpgRenderSection(main,sec)
}
function rpgField(label,inner,cls){
return `<div class="rpg-field${cls?" "+cls:""}"><span class="rpg-field-label">${label}</span>${inner}</div>`
}
function rpgText(path,value,ph,attrs){
return `<input type="text" class="rpg-input" data-bind="${path}" value="${rpgEsc(value)}" placeholder="${rpgEsc(ph||"")}" maxlength="300" ${attrs||""}>`
}
function rpgDate(path,value){
return rpgDateHtml(`data-bind="${path}"`,value)
}
function rpgCombo(path,options,value){
value=String(value||"")
const custom=value&&options.indexOf(value)<0
return `<div class="rpg-combo" data-combo="${path}"><select class="rpg-select"><option value="">Not set</option>${options.map((o)=>`<option value="${rpgEsc(o)}"${o===value?" selected":""}>${rpgEsc(o)}</option>`).join("")}<option value="__custom"${custom?" selected":""}>Custom...</option></select><input type="text" class="rpg-input${custom?"":" hidden"}" value="${custom?rpgEsc(value):""}" placeholder="Custom value" maxlength="120"></div>`
}
function rpgCheck(path,value,label,hint){
return `<label class="rpg-check"><input type="checkbox" data-bind="${path}"${value?" checked":""}><span>${label}</span>${hint?`<em>${hint}</em>`:""}</label>`
}
function rpgListRowHtml(v,ph){
return `<div class="rpg-le-row"><input type="text" class="rpg-input" value="${rpgEsc(v)}" placeholder="${rpgEsc(ph||"")}" maxlength="400"><button type="button" class="rpg-icon-btn" data-act="le-remove" title="Remove"><i class="icon icon-close"></i></button></div>`
}
function rpgListEditor(path,values,ph,extraBtn){
const rows=(values&&values.length?values:[""]).map((v)=>rpgListRowHtml(v,ph)).join("")
return `<div class="rpg-le" data-list="${path}" data-ph="${rpgEsc(ph||"")}"><div class="rpg-le-rows">${rows}</div><div class="rpg-le-foot"><button type="button" class="rpg-btn rpg-btn-sm" data-act="le-add"><i class="icon icon-add"></i><span>Add</span></button>${extraBtn||""}</div></div>`
}
function rpgTesterRowHtml(t){
t=t||{}
return `<div class="rpg-le-row rpg-tester"><input type="text" class="rpg-input" data-k="name" value="${rpgEsc(t.name)}" placeholder="Name" maxlength="120"><input type="text" class="rpg-input" data-k="role" value="${rpgEsc(t.role)}" placeholder="Role" maxlength="120"><input type="text" class="rpg-input" data-k="email" value="${rpgEsc(t.email)}" placeholder="Email" maxlength="200"><button type="button" class="rpg-icon-btn" data-act="le-remove" title="Remove"><i class="icon icon-close"></i></button></div>`
}
function rpgRenderDetails(main){
const r=rpgS.report,m=r.meta,o=r.options
main.innerHTML=`<div class="rpg-pane">
<div class="rpg-pane-title">Report details</div>
<div class="rpg-pane-sub">These fields fill the cover page, the document control table and the placeholders used in section text.</div>
<div class="rpg-group"><div class="rpg-group-title">Engagement</div><div class="rpg-grid">
${rpgField("Client",rpgText("meta.client",m.client,"Client organisation"))}
${rpgField("Client contact",rpgText("meta.client_contact",m.client_contact,"Name, role, email"))}
${rpgField("Engagement (target profile)",`<select class="rpg-select" id="rpgProfileSel">${rpgProfileOptions([],r.profile_id)}</select>`)}
${rpgField("Engagement name",rpgText("meta.engagement",m.engagement,"e.g. Q4 external assessment"))}
${rpgField("Project code",rpgText("meta.project_code",m.project_code,"e.g. PT-2026-014"))}
${rpgField("Report type",rpgCombo("meta.report_type",RPG_REPORT_TYPES,m.report_type))}
</div></div>
<div class="rpg-group"><div class="rpg-group-title">Dates</div><div class="rpg-grid rpg-grid-3">
${rpgField("Testing started",rpgDate("meta.start_date",m.start_date))}
${rpgField("Testing ended",rpgDate("meta.end_date",m.end_date))}
${rpgField("Report date",rpgDate("meta.report_date",m.report_date))}
</div></div>
<div class="rpg-group"><div class="rpg-group-title">Team</div>
${rpgField("Testers",`<div class="rpg-le" data-testers="1"><div class="rpg-le-rows">${(m.testers&&m.testers.length?m.testers:[{}]).map(rpgTesterRowHtml).join("")}</div><div class="rpg-le-foot"><button type="button" class="rpg-btn rpg-btn-sm" data-act="le-add"><i class="icon icon-add"></i><span>Add tester</span></button></div></div>`)}
<div class="rpg-grid">
${rpgField("Authors",rpgText("meta.authors",m.authors,"Who wrote the report"))}
${rpgField("Reviewers",rpgText("meta.reviewers",m.reviewers,"Who reviewed it"))}
</div></div>
<div class="rpg-group"><div class="rpg-group-title">Scope</div>
<div class="rpg-field rpg-linked-targets hidden" id="rpgTargetsField"><span class="rpg-field-label">Linked targets (optional)</span><div id="rpgTargetsHost"></div></div>
<div class="rpg-grid">
${rpgField("In scope",rpgListEditor("meta.scope_in",m.scope_in,"Host, range, URL or application",'<button type="button" class="rpg-btn rpg-btn-sm" data-act="fill-targets" title="Add the targets of the linked profile (or the active profile)"><i class="icon icon-target"></i><span>Fill from targets</span></button>'))}
${rpgField("Out of scope",rpgListEditor("meta.scope_out",m.scope_out,"Excluded host, range or technique"))}
</div>
${rpgField("Rules of engagement",`<textarea class="rpg-input rpg-textarea" data-bind="meta.rules_of_engagement" rows="4" maxlength="8000" placeholder="Testing windows, permitted techniques, restrictions, emergency contacts...">${rpgEsc(m.rules_of_engagement)}</textarea>`)}
${rpgField("Methodology",rpgText("meta.methodology",m.methodology,"e.g. OWASP WSTG, PTES, NIST SP 800-115"))}
</div>
<div class="rpg-group"><div class="rpg-group-title">Document control</div><div class="rpg-grid">
${rpgField("Classification",rpgCombo("meta.classification",RPG_CLASSIFICATIONS,m.classification))}
${rpgField("Document version",rpgText("meta.version",m.version,"e.g. 1.0"))}
</div>
${rpgField("Distribution list",rpgListEditor("meta.distribution",m.distribution,"Name, organisation"))}
</div>
<div class="rpg-group"><div class="rpg-group-title">Export options</div><div class="rpg-grid">
${rpgField("Page size",`<select class="rpg-select" data-bind="options.page_size"><option value="A4"${o.page_size==="Letter"?"":" selected"}>A4</option><option value="Letter"${o.page_size==="Letter"?" selected":""}>Letter</option></select>`)}
${rpgField("Finding ID prefix",rpgText("options.finding_id_prefix",o.finding_id_prefix,"e.g. F-",'maxlength="12"'))}
</div><div class="rpg-checks">
${rpgCheck("options.include_toc",o.include_toc!==false,"Table of contents")}
${rpgCheck("options.include_appendices",o.include_appendices!==false,"Include appendices")}
${rpgCheck("options.number_sections",o.number_sections!==false,"Number the sections")}
</div></div>
</div>`
rpgFixDateInputs(main)
rpgMountTargets()
rpgLoadSources().then((src)=>{
rpgS.sources=src
const sel=rpgEl("rpgProfileSel")
if(sel&&rpgS.report===r){sel.innerHTML=rpgProfileOptions(src.profiles,r.profile_id);sel.value=r.profile_id||""}
}).catch(()=>{})
}
// An engine without a date picker turns type=date into a text box; keep it usable as a plain YYYY-MM-DD field there.
function rpgFixDateInputs(root){
root.querySelectorAll("input[data-date]").forEach((inp)=>{if(inp.type!=="date")inp.parentNode.classList.add("as-text")})
}
// The one way a report field changes: records the undo step and queues the save. opts {key,label}: the step's coalescing key
// (default: one per field; null never merges) and its name in the Undo tooltip.
function rpgSetPath(path,value,opts){
const rep=rpgS.report
if(!rep)return
opts=opts||{}
const parts=path.split(".")
const before=parts.length===1?rep[path]:rep[parts[0]][parts[1]]
if(rpgSame(before,value))return
rpgRecord({type:"report",path,key:"key" in opts?opts.key:"report:"+path,label:opts.label||rpgPathLabel(path),before:rpgClone(before),after:rpgClone(value)})
if(parts.length===1){rep[path]=value;rpgQueueReport({[path]:value})}
else{rep[parts[0]][parts[1]]=value;rpgQueueReport({[parts[0]]:{[parts[1]]:value}})}
if(parts[0]==="branding"||path==="title"||path==="meta.client"||path==="meta.classification"||path==="meta.report_date"||path==="meta.version")rpgRenderCover()
if(path==="status"||path==="meta.schedule")rpgRenderDeadline()
}
// Several keys of meta / branding / options changed by one action: one undo step.
function rpgSetGroup(group,values,label){
const rep=rpgS.report
if(!rep||!rep[group])return
const before={},after={}
Object.keys(values||{}).forEach((k)=>{if(!rpgSame(rep[group][k],values[k])){before[k]=rpgClone(rep[group][k]);after[k]=rpgClone(values[k])}})
if(!Object.keys(after).length)return
rpgRecord({type:"report-group",group,label:label||"edit the report",before,after})
Object.assign(rep[group],after)
rpgQueueReport({[group]:after})
if(group==="branding")rpgRenderCover()
}
function rpgCollectList(box){
if(box.dataset.testers){
const rows=Array.from(box.querySelectorAll(".rpg-le-row")).map((row)=>{const t={};row.querySelectorAll("input").forEach((i)=>{t[i.dataset.k]=i.value});return t})
rpgSetPath("meta.testers",rpgCleanTesters(rows))
}else rpgSetPath(box.dataset.list,rpgCleanList(Array.from(box.querySelectorAll(".rpg-le-row input")).map((i)=>i.value)))
}
function rpgListAddRow(box,value,after){
const wrap=document.createElement("div")
wrap.innerHTML=box.dataset.testers?rpgTesterRowHtml({}):rpgListRowHtml(value||"",box.dataset.ph)
const row=wrap.firstElementChild
if(after)after.insertAdjacentElement("afterend",row)
else box.querySelector(".rpg-le-rows").appendChild(row)
return row
}
function rpgFillFromTargets(box){
const rep=rpgS.report
rpgLoadSources(rep.profile_id||undefined).then((src)=>{
if(rpgS.report!==rep)return
const lines=rpgCleanList((src.targets||[]).map(rpgTargetScopeLine))
if(!lines.length){rpgToast(rep.profile_id?"The linked profile has no targets.":"There are no targets in the active profile.",true);return}
const have=new Set(rpgCleanList(rep.meta.scope_in||[]))
const add=lines.filter((l)=>!have.has(l))
if(!add.length){rpgToast("Every target is already in scope");return}
const rowsEl=box.querySelector(".rpg-le-rows")
Array.from(rowsEl.querySelectorAll(".rpg-le-row")).forEach((row)=>{if(!row.querySelector("input").value.trim())row.remove()})
add.forEach((l)=>rpgListAddRow(box,l))
rpgCollectList(box)
rpgToast(`Added ${add.length} target${add.length===1?"":"s"} to the scope`)
}).catch((err)=>rpgToast(rpgErr(err,"Could not load the targets"),true))
}
function rpgProfileChanged(sel){
const rep=rpgS.report,profiles=(rpgS.sources&&rpgS.sources.profiles)||[]
const old=profiles.find((p)=>String(p.id)===String(rep.profile_id||"")),now=profiles.find((p)=>String(p.id)===String(sel.value))
rpgSetPath("profile_id",sel.value)
// Keep the engagement name following the profile until the user types their own.
if(now&&(!rep.meta.engagement||(old&&rep.meta.engagement===old.name))){
rpgSetPath("meta.engagement",now.name)
const inp=rpgEl("rpgMain").querySelector('[data-bind="meta.engagement"]')
if(inp)inp.value=now.name
}
}

// ---- branding ----
function rpgColorField(path,value,label){
const hex=rpgNormHex(value)||"#1d4ed8"
return rpgField(label,`<div class="rpg-color" data-color="${path}"><input type="color" class="rpg-color-native" value="${hex}" title="Pick a colour"><input type="text" class="rpg-input rpg-color-hex" value="${hex}" maxlength="7" spellcheck="false" placeholder="#rrggbb"><div class="rpg-swatches">${RPG_SWATCHES.map((c)=>`<button type="button" class="rpg-swatch" data-act="swatch" data-hex="${c}" style="background:${c}" title="${c}"></button>`).join("")}</div></div>`)
}
function rpgRenderBranding(main){
const r=rpgS.report,b=r.branding
main.innerHTML=`<div class="rpg-pane">
<div class="rpg-pane-title">Branding &amp; cover</div>
<div class="rpg-pane-sub">How the exported report looks: your company, logo and colours, and the text printed on every page.</div>
<div class="rpg-brand">
<div class="rpg-brand-form">
<div class="rpg-group"><div class="rpg-group-title">Company</div>
${rpgField("Company name",rpgText("branding.company",b.company,"Your company"))}
${rpgField("Logo",`<div class="rpg-logo" id="rpgLogoBox"><div class="rpg-logo-preview" id="rpgLogoPreview"><span class="rpg-dim">No logo</span></div><div class="rpg-logo-side"><div class="rpg-logo-btns"><button type="button" class="rpg-btn rpg-btn-sm" data-act="logo-pick"><i class="icon icon-image"></i><span>Upload logo...</span></button><button type="button" class="rpg-btn rpg-btn-sm${b.logo_asset?"":" hidden"}" id="rpgLogoRemove" data-act="logo-remove">Remove</button></div><div class="rpg-hint">PNG, JPEG, GIF or WebP, up to 10 MB. You can also drop an image here.</div></div><input type="file" id="rpgLogoFile" class="rpg-file" accept="image/png,image/jpeg,image/gif,image/webp"></div>`)}
</div>
<div class="rpg-group"><div class="rpg-group-title">Colours</div><div class="rpg-grid">
${rpgColorField("branding.accent",b.accent||"#1d4ed8","Accent colour")}
${rpgColorField("branding.secondary",b.secondary||"#0f172a","Secondary colour")}
</div></div>
<div class="rpg-group"><div class="rpg-group-title">Cover and page text</div>
${rpgCheck("branding.show_cover",b.show_cover!==false,"Cover page")}
${rpgField("Cover subtitle",rpgText("branding.cover_subtitle",b.cover_subtitle,"e.g. Penetration Test Report"))}
${rpgField("Confidentiality banner",rpgText("branding.banner",b.banner,"Printed at the top of every page, e.g. CONFIDENTIAL"))}
${rpgField("Footer text",rpgText("branding.footer",b.footer,"Printed at the bottom of every page"))}
</div>
<div class="rpg-group hidden" id="rpgThemeGroup"><div class="rpg-group-title">Report theme</div><div class="rpg-theme-host" id="rpgThemeHost"></div></div>
</div>
<div class="rpg-brand-preview"><div class="rpg-group-title">Cover preview</div><div class="rpg-cover" id="rpgCover"></div><div class="rpg-hint">A sketch of the cover. Use Preview to see the real layout.</div></div>
</div></div>`
rpgRenderCover()
rpgLoadLogo()
rpgMountThemes()
const box=rpgEl("rpgLogoBox")
box.addEventListener("dragover",(e)=>{e.preventDefault();e.dataTransfer.dropEffect="copy";box.classList.add("drop")})
box.addEventListener("dragleave",()=>box.classList.remove("drop"))
box.addEventListener("drop",(e)=>{e.preventDefault();box.classList.remove("drop");const f=e.dataTransfer&&e.dataTransfer.files&&e.dataTransfer.files[0];if(f)rpgUploadLogo(f)})
rpgEl("rpgLogoFile").addEventListener("change",(e)=>{const f=e.target.files&&e.target.files[0];e.target.value="";if(f)rpgUploadLogo(f)})
}
function rpgRenderCover(){
const el=rpgEl("rpgCover"),r=rpgS.report
if(!el||!r)return
const b=r.branding,m=r.meta
const accent=rpgNormHex(b.accent)||"#1d4ed8",secondary=rpgNormHex(b.secondary)||"#0f172a"
const logo=b.logo_asset&&rpgS.logos[b.logo_asset]?`<img src="${rpgEsc(rpgS.logos[b.logo_asset])}" alt="">`:""
const banner=b.banner||m.classification||""
el.style.setProperty("--c-accent",accent)
el.style.setProperty("--c-secondary",secondary)
el.style.setProperty("--c-accent-text",rpgContrastText(accent))
el.classList.toggle("off",b.show_cover===false)
el.innerHTML=`${banner?`<div class="rpg-cover-banner">${rpgEsc(banner)}</div>`:""}
<div class="rpg-cover-band"></div>
<div class="rpg-cover-body">
<div class="rpg-cover-logo">${logo}</div>
<div class="rpg-cover-company">${rpgEsc(b.company||"Your company")}</div>
<div class="rpg-cover-title">${rpgEsc(r.title||"Report title")}</div>
<div class="rpg-cover-sub">${rpgEsc(b.cover_subtitle||m.report_type||"")}</div>
<div class="rpg-cover-rule"></div>
<div class="rpg-cover-meta">${m.client?`<div><span>Prepared for</span>${rpgEsc(m.client)}</div>`:""}${m.report_date?`<div><span>Date</span>${rpgEsc(m.report_date)}</div>`:""}${m.version?`<div><span>Version</span>${rpgEsc(m.version)}</div>`:""}</div>
</div>
${b.footer?`<div class="rpg-cover-footer">${rpgEsc(b.footer)}</div>`:""}
${b.show_cover===false?'<div class="rpg-cover-off">Cover page is off</div>':""}`
}
function rpgLoadLogo(){
const r=rpgS.report,uid=r&&r.branding.logo_asset
const paint=()=>{
const prev=rpgEl("rpgLogoPreview"),rm=rpgEl("rpgLogoRemove")
const cur=rpgS.report&&rpgS.report.branding.logo_asset
if(prev)prev.innerHTML=cur&&rpgS.logos[cur]?`<img src="${rpgEsc(rpgS.logos[cur])}" alt="Logo">`:'<span class="rpg-dim">No logo</span>'
if(rm)rm.classList.toggle("hidden",!cur)
rpgRenderCover()
}
if(!uid||rpgS.logos[uid]){paint();return}
bridgeCall("reports.asset_get",[uid]).then((a)=>{if(a&&/^data:image\/(png|jpeg|gif|webp);base64,/.test(a.data_url||""))rpgS.logos[uid]=a.data_url;paint()}).catch(()=>paint())
}
function rpgUploadLogo(file){
if(!/^image\/(png|jpeg|gif|webp)$/.test(file.type||"")){rpgToast("The logo must be a PNG, JPEG, GIF or WebP image.",true);return}
if(file.size>RPG_LOGO_MAX){rpgToast("The logo is larger than 10 MB.",true);return}
const rep=rpgS.report,reader=new FileReader()
reader.onerror=()=>rpgToast("Could not read the image file.",true)
reader.onload=()=>{
bridgeCall("reports.asset_add",[file.name||"logo",String(reader.result)]).then((a)=>{
if(rpgS.report!==rep||!a||!a.uid)return
rpgS.logos[a.uid]=String(reader.result)
rpgSetPath("branding.logo_asset",a.uid)
rpgLoadLogo()
}).catch((err)=>rpgToast(rpgErr(err,"Could not store the logo"),true))
}
reader.readAsDataURL(file)
}
function rpgSetColor(box,hex,from){
hex=rpgNormHex(hex)
const text=box.querySelector(".rpg-color-hex"),native=box.querySelector(".rpg-color-native")
text.classList.toggle("invalid",!hex)
if(!hex)return
if(from!=="text")text.value=hex
if(from!=="native")native.value=hex
rpgSetPath(box.dataset.color,hex)
}

// ---- sections ----
function rpgRichCreate(host,opts){
if(window.ReportRich&&typeof ReportRich.create==="function"){
try{return ReportRich.create(host,opts)}catch(err){console.error("ReportRich.create failed",err)}
}
// Plain fallback while the rich editor module is missing: same interface, no toolbar.
host.innerHTML=""
const ed=document.createElement("div")
ed.className="rpg-plain-editor"
ed.contentEditable="true"
ed.spellcheck=true
ed.dataset.placeholder=opts.placeholder||""
if(opts.minHeight)ed.style.minHeight=opts.minHeight+"px"
ed.innerHTML=rpgSanitize(opts.html||"")
if(!rpgHtmlToText(opts.html||"")&&!/<(img|figure|table|hr)/i.test(opts.html||""))ed.innerHTML=""
host.appendChild(ed)
const get=()=>ed.textContent.trim()||ed.querySelector("img,figure,table,hr")?(window.ReportCore&&ReportCore.sanitizeHtml?ReportCore.sanitizeHtml(ed.innerHTML):ed.innerHTML):""
const changed=()=>{if(opts.onChange)opts.onChange(get())}
ed.addEventListener("input",changed)
ed.addEventListener("paste",(e)=>{
e.preventDefault()
const text=(e.clipboardData||window.clipboardData).getData("text/plain")
document.execCommand("insertText",false,text)
})
return {
getHTML:get,
setHTML:(h)=>{ed.innerHTML=rpgSanitize(h||"")},
focus:()=>ed.focus(),
insertHTML:(h)=>{ed.focus();const clean=rpgSanitize(h||"");const sel=window.getSelection();if(!sel.rangeCount||!ed.contains(sel.anchorNode)){const r=document.createRange();r.selectNodeContents(ed);r.collapse(false);sel.removeAllRanges();sel.addRange(r)}document.execCommand("insertHTML",false,clean);changed()},
isEmpty:()=>!get(),
destroy:()=>{host.innerHTML=""}
}
}
function rpgRenderSection(main,sec){
const rep=rpgS.report,info=rpgKindInfo(sec.kind)
const isFindings=sec.kind==="findings"
const ai=sec.kind==="executive_summary"&&window.ReportAI?'<button type="button" class="rpg-btn rpg-btn-sm" data-act="ai-draft" title="Draft the executive summary with the AI provider. Nothing is sent until you confirm."><i class="icon icon-brain"></i><span>AI: draft</span></button>':""
main.classList.toggle("rpg-main-findings",isFindings)
main.innerHTML=`<div class="rpg-pane rpg-pane-sec">
<div class="rpg-sec-head">
<input type="text" class="rpg-sec-title" id="rpgSecTitle" maxlength="200" value="${rpgEsc(sec.title||"")}" placeholder="${rpgEsc(info.label)}" title="Section title">
<span class="rpg-tag rpg-tag-kind">${rpgEsc(info.label)}</span>${info.auto?'<span class="rpg-tag">auto</span>':""}
${isFindings?'<button type="button" class="rpg-btn rpg-btn-sm" data-act="toggle-intro" id="rpgIntroToggle" title="Text printed before the findings in the exported report"><i class="icon icon-arrow-down"></i><span>Introduction text</span></button>':""}
<label class="rpg-check rpg-sec-include" title="Hidden sections stay in the report but are left out of the export"><input type="checkbox" id="rpgSecInclude"${sec.hidden?"":" checked"}><span>Include in export</span></label>
</div>
<div class="rpg-intro${isFindings?" collapsed":""}" id="rpgIntro">
${info.auto?`<div class="rpg-auto-note"><i class="icon icon-info"></i><span>${rpgEsc(RPG_AUTO_INFO[sec.kind]||"Part of this section is generated on export.")}</span></div>`:""}
<div class="rpg-sec-tools">${info.auto?'<span class="rpg-field-label rpg-intro-label">Introduction</span>':""}<div class="rpg-ph" id="rpgPlaceholders"></div><span class="rpg-spacer"></span><button type="button" class="rpg-btn rpg-btn-sm" data-act="insert-note" title="Insert the content of one of your notes"><i class="icon icon-edit"></i><span>Insert from note...</span></button>${ai}</div>
<div class="rpg-rich-host${info.auto?" compact":""}" id="rpgRichHost"></div>
</div>
${info.auto?`<div class="rpg-gen${isFindings?" rpg-gen-findings":""}" id="rpgGen"></div>`:""}
</div>`
rpgS.richSection=sec
rpgS.rich=rpgRichCreate(rpgEl("rpgRichHost"),{html:sec.content||"",placeholder:info.auto?"Optional text printed before the generated content...":"Write this section...",minHeight:info.auto?(isFindings?70:110):320,compact:!!info.auto,onChange:(html)=>{
if(rpgS.richSection!==sec||typeof html!=="string")return
rpgSecSet(sec,"content",html)
}})
rpgRenderPlaceholders()
if(info.auto)rpgRenderGenerated(sec)
}
function rpgRenderPlaceholders(){
const paint=()=>{
const host=rpgEl("rpgPlaceholders")
if(!host||!rpgS.placeholders||!rpgS.placeholders.length)return
host.innerHTML='<span class="rpg-field-label" title="Replaced with the values from Details when the report is exported">Placeholders</span>'+rpgS.placeholders.map((p)=>`<button type="button" class="rpg-ph-chip" data-act="placeholder" data-token="${rpgEsc(p.token)}" title="Insert: ${rpgEsc(p.label||p.token)}">${rpgEsc(p.token)}</button>`).join("")
}
if(rpgS.placeholders)return paint()
if(!rpgHas("reports.placeholders"))return
bridgeCall("reports.placeholders").then((rows)=>{rpgS.placeholders=(rows||[]).filter((p)=>p&&p.token);paint()}).catch(()=>{rpgS.placeholders=[]})
}
function rpgFindingNumber(i){
const prefix=rpgS.report.options.finding_id_prefix
if(window.ReportCore&&typeof ReportCore.findingNumber==="function")return ReportCore.findingNumber(prefix||"",i)
return (prefix||"")+String(i+1).padStart(2,"0")
}
function rpgFindingStatusLabel(st){
if(window.ReportCore&&typeof ReportCore.statusLabel==="function")return ReportCore.statusLabel(st||"open")
return {open:"Open",retest:"Retest",fixed:"Fixed",accepted:"Risk accepted"}[st]||"Open"
}
function rpgFindingsTableHtml(findings,withRemediation){
if(!findings.length)return '<div class="rpg-none">No findings yet. Add them in the Detailed findings section.</div>'
const order=rpgS.report.findings
return `<div class="rpg-table-wrap"><table class="rpg-table"><thead><tr><th>ID</th><th>Finding</th><th>Severity</th>${withRemediation?"<th>Remediation</th>":"<th>CVSS</th><th>Status</th>"}</tr></thead><tbody>${findings.map((f)=>`<tr><td class="rpg-mono">${rpgEsc(rpgFindingNumber(order.indexOf(f)))}</td><td>${rpgEsc(f.title||"Untitled finding")}</td><td>${rpgSevBadge(f.severity)}</td>${withRemediation?`<td class="rpg-dim-cell">${rpgEsc(rpgExcerpt(f.remediation,180))||'<span class="rpg-dim">No remediation written</span>'}</td>`:`<td class="rpg-mono">${f.cvss_score===null||f.cvss_score===undefined?"-":rpgEsc(Number(f.cvss_score).toFixed(1))}</td><td>${rpgEsc(rpgFindingStatusLabel(f.status))}</td>`}</tr>`).join("")}</tbody></table></div>`
}
function rpgFallbackChart(host,findings){
const st=rpgCountSeverities(findings),max=Math.max(1,...RPG_SEVS.map((s)=>st.counts[s.id]))
host.innerHTML=`<div class="rpg-bars">${RPG_SEVS.map((s)=>`<div class="rpg-bar-row"><span class="rpg-bar-label">${s.label}</span><span class="rpg-bar-track"><span class="rpg-bar-fill" style="width:${Math.round(st.counts[s.id]/max*100)}%;background:${rpgSevColor(s.id)}"></span></span><b>${st.counts[s.id]}</b></div>`).join("")}</div>`
}
function rpgRenderGenerated(sec){
const host=rpgEl("rpgGen"),rep=rpgS.report
if(!host||!rep)return
const kind=sec.kind,m=rep.meta
if(kind==="findings"){
if(window.ReportFindings&&typeof ReportFindings.mount==="function"){
// The workspace saves its own edits; poll its dirty flag so the header indicator covers typing inside a finding too.
try{rpgS.findings=ReportFindings.mount(host,{reportId:rep.id,getReport:()=>rpgS.report,onChanged:rpgFindingsChanged,onOp:rpgFindingOp});clearInterval(rpgS.findingsPoll);rpgS.findingsPoll=setInterval(rpgRenderSaveState,600);return}catch(err){console.error("ReportFindings.mount failed",err)}
}
host.innerHTML=`<div class="rpg-gen-title">Findings</div><div class="rpg-none">The findings workspace is not available in this build.</div>${rpgFindingsTableHtml(rep.findings)}`
return
}
if(kind==="findings_summary"){
const st=rep.stats||rpgCountSeverities(rep.findings)
host.innerHTML=`<div class="rpg-gen-title">Generated from the findings <span class="rpg-dim">(${st.total} total, ${st.open} open)</span></div><div class="rpg-summary"><div class="rpg-chart" id="rpgChart"></div><div class="rpg-summary-pills">${rpgSevPills(st.counts,{all:true})}</div></div>${rpgFindingsTableHtml(rep.findings)}`
const chart=rpgEl("rpgChart")
if(window.ReportWidgets&&typeof ReportWidgets.riskChart==="function"){try{rpgS.chart=ReportWidgets.riskChart(chart,rep.findings,{});return}catch(err){console.error("riskChart failed",err)}}
rpgFallbackChart(chart,rep.findings)
return
}
if(kind==="remediation_roadmap"){
host.innerHTML=`<div class="rpg-gen-title">Generated from the findings <span class="rpg-dim">(most severe first)</span></div>${rpgFindingsTableHtml(rpgSortedForRoadmap(rep.findings),true)}`
return
}
if(kind==="risk_matrix"){
const mx=rpgRiskMatrix(rep.findings)
host.innerHTML=`<div class="rpg-gen-title">Generated from the findings <span class="rpg-dim">(severity against likelihood)</span></div><div class="rpg-summary"><div class="rpg-table-wrap rpg-matrix-wrap"><table class="rpg-table rpg-matrix"><thead><tr><th>Severity \\ Likelihood</th>${mx.cols.map((c)=>`<th>${c}</th>`).join("")}</tr></thead><tbody>${mx.rows.map((r)=>`<tr><th>${rpgSevBadge(r.sev)}</th>${r.cells.map((n,i)=>`<td class="${n?"on":""}" style="--sev:${rpgSevColor(r.sev)};--w:${n?Math.min(1,0.35+(3-Math.min(i,3))*0.2):0}">${n||""}</td>`).join("")}</tr>`).join("")}</tbody></table></div><div class="rpg-chart" id="rpgChart"></div></div><div class="rpg-hint">Set the likelihood of a finding in its Classification block. Findings without one are counted under "Not set".</div>`
const chart=rpgEl("rpgChart")
if(window.ReportWidgets&&typeof ReportWidgets.riskChart==="function"){try{rpgS.chart=ReportWidgets.riskChart(chart,rep.findings,{compact:true});return}catch(err){console.error("riskChart failed",err)}}
rpgFallbackChart(chart,rep.findings)
return
}
if(kind==="project_timeline"){
const today=rpgTodayStr(),ms=rpgMsSorted(rpgMilestones())
host.innerHTML=`<div class="rpg-gen-title">Generated from the Timeline of this report</div><div class="rpg-tl-host" id="rpgTlView"></div>${ms.length?`<div class="rpg-table-wrap"><table class="rpg-table"><thead><tr><th>Milestone</th><th>Date</th><th>Status</th><th>Notes</th></tr></thead><tbody>${ms.map((m)=>`<tr><td>${rpgEsc(m.label)}</td><td class="rpg-mono">${rpgEsc(m.date||"-")}${m.time?" "+rpgEsc(m.time):""}</td><td><span class="rpg-ms-state ${rpgMsState(m,today)}">${rpgEsc(rpgMsStateText(m,today))}</span></td><td class="rpg-dim-cell">${rpgEsc(m.notes)}</td></tr>`).join("")}</tbody></table></div>`:'<div class="rpg-none">The timeline has no milestones yet.</div>'}<button type="button" class="rpg-btn rpg-btn-sm" data-act="goto-timeline"><i class="icon rpg-ic-flag"></i><span>Edit the timeline</span></button>`
rpgPaintTimeline()
rpgWatchTimeline()
return
}
if(kind==="document_control"){
const testers=(m.testers||[]).map((t)=>[t.name,t.role,t.email].filter(Boolean).join(", ")).filter(Boolean)
const row=(k,v)=>`<tr><th>${k}</th><td>${v||'<span class="rpg-dim">Not set</span>'}</td></tr>`
host.innerHTML=`<div class="rpg-gen-title">Generated from Details</div><div class="rpg-table-wrap"><table class="rpg-table rpg-table-kv"><tbody>
${row("Document version",rpgEsc(m.version))}${row("Classification",rpgEsc(m.classification))}${row("Report date",rpgEsc(m.report_date))}${row("Authors",rpgEsc(m.authors))}${row("Reviewers",rpgEsc(m.reviewers))}${row("Testers",testers.map(rpgEsc).join("<br>"))}${row("Distribution",(m.distribution||[]).map(rpgEsc).join("<br>"))}${row("Saved versions",rep.versions.length?rep.versions.map((v)=>rpgEsc(v.label||"Version")+' <span class="rpg-dim">'+rpgEsc(String(v.created_at||"").slice(0,10))+"</span>").join("<br>"):"")}
</tbody></table></div><button type="button" class="rpg-btn rpg-btn-sm" data-act="goto-details">Edit in Details</button>`
return
}
const n=rpgEvidenceUids(rep).length
host.innerHTML=`<div class="rpg-gen-title">Generated from the evidence in this report</div><div class="rpg-none">${n?`${n} piece${n===1?"":"s"} of evidence ${n===1?"is":"are"} used in this report.`:"No evidence is used in this report yet. Attach evidence to a finding, or insert it into a section with the Evidence button of the editor."}</div>${window.ReportEvidence&&typeof ReportEvidence.openManager==="function"?'<button type="button" class="rpg-btn rpg-btn-sm" data-act="evidence">Open the evidence manager</button>':""}`
}
function rpgInsertFromNote(){
const sec=rpgS.richSection
if(!rpgS.rich||!sec)return
const m=rpgModal("Insert from note",'<div class="rpg-search rpg-search-wide"><i class="icon icon-search"></i><input type="text" id="rpgNoteSearch" placeholder="Search notes..." autocomplete="off" spellcheck="false"></div><div class="rpg-rows" id="rpgNoteRows"><div class="rpg-none">Loading notes...</div></div>',{cls:"rpg-modal-mid"})
const rows=m.body.querySelector("#rpgNoteRows"),search=m.body.querySelector("#rpgNoteSearch")
let notes=[]
const paint=()=>{
const words=search.value.toLowerCase().split(/\s+/).filter(Boolean)
const list=notes.filter((n)=>{const hay=[n.name,n.group,Array.isArray(n.tags)?n.tags.join(" "):n.tags].join(" ").toLowerCase();return words.every((w)=>hay.includes(w))})
rows.innerHTML=list.length?list.slice(0,200).map((n)=>`<button type="button" class="rpg-row rpg-row-btn" data-id="${rpgEsc(n.id)}"><div class="rpg-row-main"><div class="rpg-row-title">${rpgEsc(n.name||"Untitled note")}${n.findings?`<span class="rpg-tag">${Number(n.findings)} finding${Number(n.findings)===1?"":"s"}</span>`:""}</div><div class="rpg-row-sub">${[n.group,rpgRelTime(n.updated_at)].filter(Boolean).map(rpgEsc).join(" &middot; ")}</div></div><i class="icon icon-arrow-right"></i></button>`).join(""):`<div class="rpg-none">${notes.length?"No note matches the search.":"There are no notes yet."}</div>`
}
search.addEventListener("input",paint)
rows.addEventListener("click",(e)=>{
const b=e.target.closest(".rpg-row-btn")
if(!b||b.disabled)return
const note=notes.find((n)=>String(n.id)===b.dataset.id)
if(!note)return
rows.querySelectorAll("button").forEach((x)=>{x.disabled=true})
bridgeCall("reports.note_content",[note.id]).then((res)=>{
closeModal(true)
if(rpgS.richSection!==sec||!rpgS.rich)return
const html=rpgSanitize((res&&res.html)||"")
if(!rpgHtmlToText(html)&&!/<(img|figure|table)/i.test(html)){rpgToast("That note is empty",true);return}
rpgS.rich.insertHTML(html)
rpgSyncRich()
rpgToast(`Inserted "${(res&&res.name)||note.name||"note"}"`)
}).catch((err)=>{rows.querySelectorAll("button").forEach((x)=>{x.disabled=false});rpgToast(rpgErr(err,"Could not read the note"),true)})
})
rpgFootBtn(m,"Cancel","",()=>closeModal())
rpgLoadSources().then((src)=>{notes=src.notes||[];if(m.isOpen())paint()}).catch((err)=>{rows.innerHTML=`<div class="rpg-none error">${rpgEsc(rpgErr(err,"Could not load the notes"))}</div>`})
setTimeout(()=>search.focus(),30)
}
function rpgAiDraft(btn){
const sec=rpgS.richSection,rep=rpgS.report
if(!sec||!rep||!window.ReportAI||typeof ReportAI.run!=="function")return
btn.disabled=true
rpgFlush().then(()=>ReportAI.run("exec_summary",{reportId:rep.id})).then((res)=>{
btn.disabled=false
if(!res||rpgS.richSection!==sec||!rpgS.rich)return
const html=res.html?rpgSanitize(res.html):(res.text?String(res.text).split(/\n{2,}/).map((p)=>"<p>"+rpgEsc(p.trim())+"</p>").join(""):"")
if(!html)return
if(rpgS.rich.isEmpty()){rpgS.rich.setHTML(html);rpgSyncRich();return}
return appConfirm("This section already has text. Replace it with the AI draft, or add the draft below it?",{okLabel:"Replace",extraLabel:"Add below"}).then((ans)=>{
if(!ans||rpgS.richSection!==sec||!rpgS.rich)return
if(ans==="extra")rpgS.rich.setHTML(rpgS.rich.getHTML()+html)
else rpgS.rich.setHTML(html)
rpgSyncRich()
})
}).catch((err)=>{btn.disabled=false;rpgToast(rpgErr(err,"The AI draft failed"),true)})
}

// ---- timeline & schedule ----
function rpgMilestones(){
const rep=rpgS.report
return rep?rpgNormSchedule(rep.meta.schedule).milestones:[]
}
function rpgShortDate(s){return rpgValidDate(s)?rpgTickLabel(rpgDayNum(s),false):""}
function rpgMsStateText(m,today){
const st=rpgMsState(m,today)
if(st==="done")return "Done"
if(st==="unset")return "No date"
const left=rpgDayNum(m.date)-rpgDayNum(today)
if(st==="overdue")return "Overdue by "+(-left)+(left===-1?" day":" days")
return left===0?"Today":rpgDaysText(left).replace(/^./,(c)=>c.toUpperCase())
}
function rpgTimelineHtml(milestones,today,width){
const inner=Math.max(180,(width||600)-116)
const lay=rpgTimelineLayout(milestones,today,{minGap:Math.min(70,Math.round(120/inner*1000)/10),maxTicks:Math.max(3,Math.floor(inner/72))})
if(lay.empty)return '<div class="rpg-none">Give a milestone a date to see the timeline.</div>'
const tip=(it)=>rpgEsc(`${it.label}: ${it.date}${it.time?" "+it.time:""} (${rpgMsStateText(it,today)})`)
return `<div class="rpg-tl" style="--lanes:${lay.lanes}" role="img" aria-label="Timeline from ${lay.start} to ${lay.end}">
<div class="rpg-tl-in">
<div class="rpg-tl-lanes">${lay.items.map((it)=>`<div class="rpg-tl-flag ${it.state}" style="left:${it.pct}%;bottom:${it.lane*34+4}px" title="${tip(it)}"><b>${rpgEsc(it.label)}</b><span>${rpgEsc(rpgShortDate(it.date))}</span></div>`).join("")}</div>
<div class="rpg-tl-track">
${lay.phases.map((p)=>`<div class="rpg-tl-phase ${p.key}" style="left:${p.left}%;width:${p.width}%" title="${rpgEsc(p.label)} window: ${p.from} to ${p.to}"><span>${rpgEsc(p.label)}</span></div>`).join("")}
<div class="rpg-tl-line"></div>
${lay.items.map((it)=>`<i class="rpg-tl-stem ${it.state}" style="left:${it.pct}%;height:${it.lane*34+18}px"></i><i class="rpg-tl-dot ${it.state}" style="left:${it.pct}%" title="${tip(it)}"></i>`).join("")}
<div class="rpg-tl-today" style="left:${lay.today.pct}%" title="Today, ${rpgEsc(today)}"><span>Today</span></div>
</div>
<div class="rpg-tl-axis">${lay.ticks.map((t)=>`<span style="left:${t.pct}%">${rpgEsc(t.label)}</span>`).join("")}</div>
</div>
<div class="rpg-tl-legend"><span><i class="rpg-tl-dot done"></i>Done</span><span><i class="rpg-tl-dot upcoming"></i>Upcoming</span><span><i class="rpg-tl-dot overdue"></i>Overdue</span><span><i class="rpg-tl-key testing"></i>Testing window</span><span><i class="rpg-tl-key retest"></i>Retest window</span></div>
</div>`
}
function rpgPaintTimeline(){
const host=rpgEl("rpgTlView")
if(!host||!rpgS.report)return
rpgS.tlWidth=host.clientWidth
host.innerHTML=rpgTimelineHtml(rpgMilestones(),rpgTodayStr(),host.clientWidth)
}
// The lanes depend on the width, so the view is laid out again when the pane is resized.
function rpgWatchTimeline(){
const host=rpgEl("rpgTlView")
if(rpgS.tlObserver){rpgS.tlObserver.disconnect();rpgS.tlObserver=null}
if(!host||typeof ResizeObserver==="undefined")return
rpgS.tlObserver=new ResizeObserver(()=>{if(Math.abs(host.clientWidth-(rpgS.tlWidth||0))>8)rpgPaintTimeline()})
rpgS.tlObserver.observe(host)
}
function rpgDateHtml(attrs,value){
const v=rpgValidDate(value)?value:""
return `<div class="rpg-datewrap${v?"":" empty"}"><input type="date" class="rpg-input rpg-date" ${attrs} data-date="1" value="${v}" placeholder="YYYY-MM-DD" maxlength="10"><span class="rpg-date-ph">Not set</span><button type="button" class="rpg-icon-btn" data-act="date-clear" title="Clear the date"><i class="icon icon-close"></i></button></div>`
}
function rpgMsRemindHtml(m){
const days=m.remind.map((r)=>r.days_before)
const chip=(d,on)=>`<button type="button" class="rpg-chip${on?" active":""}" data-act="ms-remind" data-days="${d}" aria-pressed="${on?"true":"false"}" title="${on?"Reminder set: click to remove it":"Remind me "+rpgRemindLabel(d).toLowerCase()}">${rpgEsc(rpgRemindLabel(d))}</button>`
return `<span class="rpg-field-label">Remind me</span>${RPG_REMIND_PRESETS.map((d)=>chip(d,days.indexOf(d)>=0)).join("")}${days.filter((d)=>RPG_REMIND_PRESETS.indexOf(d)<0).map((d)=>chip(d,true)).join("")}<button type="button" class="rpg-chip rpg-chip-add" data-act="ms-remind-custom" title="Remind me any number of days before">Custom...</button>`
}
function rpgMsRowHtml(m,today){
return `<div class="rpg-ms ${rpgMsState(m,today)}" data-ms="${rpgEsc(m.id)}">
<label class="rpg-ms-done" title="Mark this milestone as done"><input type="checkbox" data-f="done"${m.done?" checked":""} aria-label="Done"></label>
<input type="text" class="rpg-input rpg-ms-label" data-f="label" value="${rpgEsc(m.label)}" maxlength="120" placeholder="${rpgEsc(rpgMsLabel(m.key))}" aria-label="Milestone name">
${rpgDateHtml('data-f="date" aria-label="Date"',m.date)}
<input type="text" class="rpg-input rpg-ms-time" data-f="time" value="${rpgEsc(m.time)}" placeholder="HH:MM" maxlength="5" spellcheck="false" title="Time of day, 24-hour HH:MM (optional)" aria-label="Time">
<span class="rpg-ms-state">${rpgEsc(rpgMsStateText(m,today))}</span>
<button type="button" class="rpg-icon-btn danger" data-act="ms-remove" title="Remove this milestone"><i class="icon icon-trash"></i></button>
<div class="rpg-ms-extra"><div class="rpg-ms-remind">${rpgMsRemindHtml(m)}</div><input type="text" class="rpg-input rpg-ms-notes" data-f="notes" value="${rpgEsc(m.notes)}" maxlength="2000" placeholder="Notes (optional)" aria-label="Notes"></div>
</div>`
}
function rpgRenderTimelinePane(main){
const rep=rpgS.report,today=rpgTodayStr(),ms=rpgMsSorted(rpgMilestones())
const dates=rpgValidDate(rep.meta.start_date)||rpgValidDate(rep.meta.end_date)
main.innerHTML=`<div class="rpg-pane rpg-pane-tl">
<div class="rpg-pane-title">Timeline &amp; schedule</div>
<div class="rpg-pane-sub">Plan the engagement from kick-off to hand-over and retest, and get reminded before a deadline. A Project timeline section prints these milestones in the report.</div>
<div class="rpg-group"><div class="rpg-group-title">Timeline</div><div class="rpg-tl-host" id="rpgTlView"></div></div>
<div class="rpg-group"><div class="rpg-group-head"><div class="rpg-group-title">Milestones</div><span class="rpg-spacer"></span>
<button type="button" class="rpg-btn rpg-btn-sm" data-act="ms-fill" title="${dates?"Set the testing window from the dates in Details"+(ms.length?"":" and add the usual milestones"):"Add the usual milestones. Set the testing dates in Details to fill them in."}"><i class="icon icon-clock"></i><span>Fill from engagement dates</span></button>
<button type="button" class="rpg-btn rpg-btn-sm" data-act="ms-add"><i class="icon icon-add"></i><span>Add milestone</span></button></div>
<div class="rpg-ms-list" id="rpgMsList">${ms.length?ms.map((m)=>rpgMsRowHtml(m,today)).join(""):'<div class="rpg-none">No milestones yet. Add one, or fill the usual ones from the engagement dates.</div>'}</div>
<div class="rpg-hint">A reminder is delivered once, while the app is open and unlocked: as a notification inside the app, and as a desktop notification when those are turned on in Settings. Reports marked Final send no reminders.</div>
</div></div>`
rpgFixDateInputs(main)
rpgPaintTimeline()
rpgWatchTimeline()
}
function rpgCommitMs(milestones,opts){
rpgSetPath("meta.schedule",{milestones},opts)
rpgPaintTimeline()
}
function rpgMsRepaintRow(row,m){
const today=rpgTodayStr()
row.className="rpg-ms "+rpgMsState(m,today)
const st=row.querySelector(".rpg-ms-state")
if(st)st.textContent=rpgMsStateText(m,today)
}
function rpgMsField(row,t){
const ms=rpgMilestones(),m=ms.find((x)=>x.id===row.dataset.ms),f=t.dataset.f
if(!m)return
const was=rpgShortName(m.label)
if(f==="done")m.done=!!t.checked
else if(f==="date"){
t.parentNode.classList.toggle("empty",!t.value)
if(t.value!==""&&!rpgValidDate(t.value)){t.classList.add("invalid");return}
t.classList.remove("invalid")
m.date=t.value
}else if(f==="time"){
const v=t.value.trim(),ok=v===""||rpgValidTime(v)
t.classList.toggle("invalid",!ok)
if(!ok)return
m.time=v
}else if(f==="label")m.label=t.value.trim()||rpgMsLabel(m.key)
else if(f==="notes")m.notes=t.value
else return
rpgCommitMs(ms,{key:f==="done"?null:`report:meta.schedule:${m.id}:${f}`,label:f==="done"?(m.done?`mark '${was}' as done`:`reopen milestone '${was}'`):f==="label"?`rename milestone '${was}'`:`edit milestone '${was}'`})
rpgMsRepaintRow(row,m)
}
function rpgMsToggleRemind(row,days){
const ms=rpgMilestones(),m=ms.find((x)=>x.id===row.dataset.ms)
if(!m||!Number.isInteger(days)||days<0||days>365)return
const have=m.remind.map((r)=>r.days_before),at=have.indexOf(days)
if(at>=0)have.splice(at,1)
else have.push(days)
m.remind=have.sort((a,b)=>b-a).slice(0,8).map((n)=>({days_before:n}))
rpgCommitMs(ms,{key:null,label:`change the reminders of '${m.label}'`})
const box=row.querySelector(".rpg-ms-remind")
if(box)box.innerHTML=rpgMsRemindHtml(m)
}
function rpgMsCustomRemind(row,btn){
if(row.querySelector(".rpg-ms-custom"))return
const wrap=document.createElement("span")
wrap.className="rpg-ms-custom"
wrap.innerHTML='<input type="number" class="rpg-input" min="0" max="365" step="1" placeholder="Days" aria-label="Days before the date"><span>days before</span>'
btn.replaceWith(wrap)
const input=wrap.querySelector("input")
let done=false
const finish=(save)=>{
if(done)return
done=true
const n=Number(input.value)
if(save&&input.value.trim()!==""&&Number.isInteger(n)&&n>=0&&n<=365)return rpgMsToggleRemindOn(row,n)
const box=row.querySelector(".rpg-ms-remind"),m=rpgMilestones().find((x)=>x.id===row.dataset.ms)
if(box&&m)box.innerHTML=rpgMsRemindHtml(m)
}
input.addEventListener("keydown",(e)=>{if(e.key==="Enter"){e.preventDefault();e.stopPropagation();finish(true)}else if(e.key==="Escape"){e.preventDefault();e.stopPropagation();finish(false)}})
input.addEventListener("input",(e)=>e.stopPropagation())
input.addEventListener("change",(e)=>e.stopPropagation())
input.addEventListener("blur",()=>finish(true))
input.focus()
}
function rpgMsToggleRemindOn(row,days){
const m=rpgMilestones().find((x)=>x.id===row.dataset.ms)
if(m&&m.remind.some((r)=>r.days_before===days)){const box=row.querySelector(".rpg-ms-remind");if(box)box.innerHTML=rpgMsRemindHtml(m);return}
rpgMsToggleRemind(row,days)
}
function rpgMsAdd(key){
const ms=rpgMilestones()
const m={id:rpgNewId(),key,label:key==="custom"?"New milestone":rpgMsLabel(key),date:"",time:"",done:false,remind:key==="handover"?[{days_before:3},{days_before:1}]:[],notes:""}
ms.push(m)
rpgCommitMs(ms,{key:null,label:`add milestone '${m.label}'`})
rpgRerenderEntry()
const row=rpgEl("rpgMsList")&&rpgEl("rpgMsList").querySelector(`[data-ms="${m.id}"]`)
if(row){row.scrollIntoView({block:"nearest"});const inp=row.querySelector(key==="custom"?".rpg-ms-label":".rpg-date");if(inp){inp.focus();if(key==="custom")inp.select()}}
}
function rpgMsAddMenu(anchor){
const have=new Set(rpgMilestones().map((m)=>m.key))
rpgOpenMenu(anchor,RPG_MS_KEYS.map((k)=>({label:k.key==="custom"?"Custom milestone":k.label,icon:k.key==="custom"?"icon-add":"rpg-ic-flag",note:k.key!=="custom"&&have.has(k.key)?"in timeline":"",fn:()=>rpgMsAdd(k.key)})))
}
function rpgMsFill(){
const rep=rpgS.report,before=rpgMilestones()
const next=rpgScheduleFromDates({milestones:before},rep.meta,null,rpgTodayStr()).milestones
if(rpgSame(before,next)){rpgToast(rpgValidDate(rep.meta.start_date)||rpgValidDate(rep.meta.end_date)?"The timeline already follows the engagement dates":"Set the testing dates in Details first",true);return}
rpgCommitMs(next,{key:null,label:"fill the timeline from the engagement dates"})
rpgRerenderEntry()
rpgToast(before.length?"Testing window updated from the engagement dates":"Milestones added. Give the remaining ones a date.")
}
function rpgMsRemove(row){
const ms=rpgMilestones(),at=ms.findIndex((x)=>x.id===row.dataset.ms)
if(at<0)return
const m=ms.splice(at,1)[0]
rpgCommitMs(ms,{key:null,label:`remove milestone '${m.label}'`})
rpgRerenderEntry()
}
function rpgDeadlineTip(dl){
return `${rpgClampText(dl.label,120)||"Milestone"}: ${dl.overdue?"was due":"due"} ${rpgDaysText(dl.days_left)} (${dl.date}${dl.time?" "+dl.time:""})`
}
function rpgDeadlineChip(dl,cls){
if(!dl)return ""
const p=rpgDeadlineParts(rpgClampText(dl.label,120),dl.days_left)
return `<span class="rpg-deadline ${cls||""}${dl.overdue?" overdue":dl.days_left<=1?" soon":""}" title="${rpgEsc(rpgDeadlineTip(dl))}"><i class="icon icon-clock"></i><span class="rpg-dl-long">${p.name?`<bdi class="rpg-dl-name">${rpgEsc(p.name)}</bdi>`:""}<span class="rpg-dl-when">${rpgEsc(p.when)}</span></span><span class="rpg-dl-short">${rpgEsc(rpgDeadlineShort(dl.days_left))}</span></span>`
}
function rpgRenderDeadline(){
const el=rpgEl("rpgDeadline"),rep=rpgS.report
if(!el||!rep)return
const dl=rpgNextDeadline(rep,rpgTodayStr())
el.classList.toggle("hidden",!dl)
el.innerHTML=rpgDeadlineChip(dl)
el.title=dl?rpgDeadlineTip(dl)+". Click to open the timeline.":""
}
// In-app half of the reminders (the scheduler sends the desktop notification): each one shows once as a toast and stays in
// the notification centre. Refused quietly while the app is locked.
function rpgPollReminders(){
if(!rpgHas("reports.reminders_due"))return Promise.resolve([])
return bridgeCall("reports.reminders_due",[]).then((rows)=>{
rows=Array.isArray(rows)?rows:[]
rows.forEach((r)=>{if(r&&r.message)rpgToast(String(r.message))})
if(rows.length&&rpgS.ready&&rpgS.view==="list")rpgLoadList()
return rows
}).catch(()=>[])
}

// ---- add section: picker and quick-add row ----
function rpgQuickAddHtml(){
const rep=rpgS.report,have=new Set(rep?rep.sections.map((s)=>s.kind):[])
return RPG_QUICK_KINDS.map((kind,i)=>{
const k=rpgKindInfo(kind),meta=RPG_KIND_META[kind]||{},on=have.has(kind)
return `<button type="button" class="rpg-quick${on?" have":""}" data-kind="${kind}" title="${on?rpgEsc(k.label)+" is in the report: click to open it":"Add "+rpgEsc(k.label)+" with starting text"} (Alt+${i+1})" aria-label="${on?"Open":"Add"} ${rpgEsc(k.label)}"><i class="icon ${meta.icon||"icon-file"}"></i></button>`
}).join("")
}
function rpgQuickAdd(kind){
const rep=rpgS.report
if(!rep)return
const have=rep.sections.find((s)=>s.kind===kind)
if(have)return rpgSelectEntry("sec:"+have.id)
return rpgAddSection(rpgKindInfo(kind))
}
function rpgOpenSectionPicker(){
const rep=rpgS.report
if(!rep||rpgDialogOpen())return
rpgCloseMenu()
const have=new Set(rep.sections.map((s)=>s.kind)),cur=rpgCurrentSection()
const m=rpgModal("Add a section",`<div class="rpg-hint">${cur?`The section is added after "${rpgEsc(rpgSecName(cur))}"`:"The section is added in front of the appendices (an appendix goes last)"} and starts with professional boilerplate text you can edit. Sections marked <span class="rpg-tag rpg-tag-inline">auto</span> are filled in from the findings, the timeline or the evidence when you export.</div>
<div class="rpg-kinds">${RPG_SECTION_KINDS.map((k)=>{
const meta=RPG_KIND_META[k.kind]||{},on=k.kind!=="custom"&&have.has(k.kind),q=RPG_QUICK_KINDS.indexOf(k.kind)
return `<button type="button" class="rpg-kind${on?" have":""}" data-kind="${k.kind}"><i class="icon ${meta.icon||"icon-file"}"></i><span class="rpg-kind-main"><span class="rpg-kind-name"><span>${rpgEsc(k.label)}</span>${k.auto?'<span class="rpg-tag">auto</span>':""}${on?'<span class="rpg-tag rpg-tag-kind">in report</span>':""}${q>=0?`<kbd>Alt+${q+1}</kbd>`:""}</span><span class="rpg-kind-desc">${rpgEsc(meta.desc||"")}</span></span></button>`
}).join("")}</div>`,{cls:"rpg-modal-kinds"})
m.body.addEventListener("click",(e)=>{
const b=e.target.closest(".rpg-kind")
if(!b)return
closeModal(true)
rpgAddSection(rpgKindInfo(b.dataset.kind))
})
rpgFootBtn(m,"Cancel","",()=>closeModal())
setTimeout(()=>{const b=m.body.querySelector(".rpg-kind");if(b)b.focus()},30)
}
// Linked targets (reporting_targets.js) are optional: without the module nothing is shown. Its changes become undo steps
// through rpgTargetsOp, and the report in memory follows through onChanged.
function rpgMountTargets(){
const field=rpgEl("rpgTargetsField"),host=rpgEl("rpgTargetsHost"),rep=rpgS.report
if(!field||!host||!rep||rpgS.targets||!window.ReportTargets||typeof ReportTargets.mountScope!=="function")return
try{
rpgS.targets=ReportTargets.mountScope(host,{reportId:rep.id,getReport:()=>rpgS.report,onChanged:(targets)=>{if(rpgS.report===rep)rep.targets=Array.isArray(targets)?targets:[]},onOp:rpgTargetsOp,setOption:(key,value)=>{if(rpgS.report!==rep)return;rpgSetPath("options."+key,value,{key:null,label:"change the scope table"});if(rpgS.targets&&typeof rpgS.targets.refresh==="function")rpgS.targets.refresh()}})||{}
field.classList.remove("hidden")
}catch(err){console.error("ReportTargets.mountScope failed",err)}
}
function rpgTargetsOp(op){
if(!op||!rpgS.report||typeof op.undo!=="function"||typeof op.redo!=="function")return
rpgRecord({type:"ext",label:rpgShortName(op.label||"change the linked targets"),undo:op.undo,redo:op.redo})
}
function rpgApplyExt(op,undo){
return Promise.resolve((undo?op.undo:op.redo)()).then(()=>{
if(rpgS.entry!=="details")return rpgSelectEntry("details")
if(rpgS.targets&&typeof rpgS.targets.refresh==="function")rpgS.targets.refresh()
})
}
function rpgMountThemes(){
const host=rpgEl("rpgThemeHost"),rep=rpgS.report
if(!host||!rep||host.dataset.mounted||!window.ReportThemes||typeof ReportThemes.mountPicker!=="function")return
host.dataset.mounted="1"
try{
ReportThemes.mountPicker(host,{branding:rep.branding,onChange:(patch)=>{
if(rpgS.report!==rep||!patch)return
const next={}
;["theme","font","cover_style"].forEach((k)=>{if(k in patch)next[k]=patch[k]})
rpgSetGroup("branding",next,"change the report theme")
}})
rpgEl("rpgThemeGroup").classList.remove("hidden")
}catch(err){console.error("ReportThemes.mountPicker failed",err);delete host.dataset.mounted}
}

// ---- undo / redo ----
// Every change to the open report is recorded as a step (rpgRecord). Undo applies the opposite through the normal save paths,
// so the server follows. Inside a text field Ctrl+Z stays the field's own undo for as long as that still changes something;
// after that (or with the focus elsewhere, or from the header buttons) it steps back through this history.
function rpgRenderUndo(){
[["undo","rpgUndoBtn"],["redo","rpgRedoBtn"]].forEach((p)=>{
const b=rpgEl(p[1])
if(!b)return
b.disabled=rpgS.undoBusy||!rpgHistPeek(rpgS.hist,p[0])
b.title=rpgHistTip(rpgS.hist,p[0])
})
}
function rpgRecord(op){
if(!rpgS.report||rpgS.applying)return
rpgHistPush(rpgS.hist,op,Date.now(),{merge:rpgS.nativeHist||Date.now()<rpgS.nativeUntil})
rpgRenderUndo()
}
function rpgShortName(s){s=String(s||"");return s.length>44?s.slice(0,43).trimEnd()+"…":s}
function rpgSecName(sec){return rpgShortName(sec.title||rpgKindInfo(sec.kind).label)}
// The one way a section field changes: records the step and queues the save. Returns false when nothing changed.
function rpgSecSet(sec,field,value){
if(rpgSame(sec[field],value))return false
const name=rpgSecName(sec)
const label=field==="content"?`edit section '${name}'`:field==="title"?`rename section '${name}'`:`${value?"hide":"show"} section '${name}'`
rpgRecord({type:"sec-edit",id:sec.id,field,key:field==="hidden"?"":`sec:${sec.id}:${field}`,label,before:rpgClone(sec[field]),after:rpgClone(value)})
sec[field]=value
rpgQueueSection(sec.id,{[field]:value})
return true
}
function rpgFindingOp(op){
if(!op||!rpgS.report)return
const name=(f)=>`'${rpgShortName((f&&f.title)||"Untitled finding")}'`
if(op.type==="edit")rpgRecord({type:"f-edit",id:op.id,key:`f:${op.id}:${Object.keys(op.after||{}).sort().join(",")}`,label:"edit finding "+name(op),before:op.before,after:op.after})
else if(op.type==="add")rpgRecord({type:"f-add",label:"add finding "+name(op.finding),finding:op.finding,index:op.index})
else if(op.type==="delete")rpgRecord({type:"f-del",label:"delete finding "+name(op.finding),finding:op.finding,index:op.index})
else if(op.type==="reorder")rpgRecord({type:"f-order",label:"reorder the findings",before:op.before,after:op.after})
}
function rpgUndoRedo(dir){
if(!rpgS.report||rpgS.view!=="editor"||rpgS.undoBusy||rpgDialogOpen())return Promise.resolve(false)
// Text that is still on its way out of an editor becomes a step first, so it is what gets undone.
rpgSyncRich()
let pre=Promise.resolve()
if(rpgS.findings&&typeof rpgS.findings.flush==="function"){try{pre=Promise.resolve(rpgS.findings.flush()).catch(()=>{})}catch(e){}}
const op=rpgHistTake(rpgS.hist,dir)
if(!op){rpgRenderUndo();return Promise.resolve(false)}
const rep=rpgS.report
rpgS.undoBusy=true;rpgS.applying=true
// A step back in the report also ends the fields' own undo: their text is about to be replaced.
if(typeof WeakSet!=="undefined")rpgS.typed=new WeakSet()
rpgRenderUndo()
return pre.then(()=>rpgApplyOp(op,dir==="undo")).then(()=>true,(err)=>{
if(rpgS.report===rep)rpgHistGiveBack(rpgS.hist,dir,op)
rpgToast(rpgErr(err,"That step could not be "+(dir==="undo"?"undone":"redone")),true)
return false
}).then((ok)=>{rpgS.undoBusy=false;rpgS.applying=false;rpgRenderUndo();rpgRenderSaveState();return ok})
}
function rpgApplyOp(op,undo){
const v=undo?op.before:op.after
if(op.type==="report")return rpgApplyReportValue(op.path,v)
if(op.type==="report-group")return rpgApplyReportGroup(op.group,v,undo?op.after:op.before)
if(op.type==="sec-edit")return rpgApplySecEdit(op.id,op.field,v)
if(op.type==="sec-order")return rpgApplySecOrder(v)
if(op.type==="sec-add")return undo?rpgApplySecRemove(op):rpgApplySecRestore(op)
if(op.type==="sec-del")return undo?rpgApplySecRestore(op):rpgApplySecRemove(op)
if(op.type==="f-edit")return rpgApplyFindingEdit(op.id,v)
if(op.type==="f-order")return rpgApplyFindingOrder(v)
if(op.type==="f-add")return undo?rpgApplyFindingRemove(op):rpgApplyFindingRestore(op)
if(op.type==="f-del")return undo?rpgApplyFindingRestore(op):rpgApplyFindingRemove(op)
if(op.type==="ext")return rpgApplyExt(op,undo)
}
function rpgRerenderEntry(){
const main=rpgEl("rpgMain"),scroll=main?main.scrollTop:0
rpgTeardownEntry(true)
rpgRenderEntry()
if(main)main.scrollTop=scroll
}
function rpgApplyReportValue(path,value){
const rep=rpgS.report,parts=path.split(".")
value=rpgClone(value)
// A key that did not exist before is sent as null: the server drops it (or falls back to its default).
const wire=value===undefined?null:value
if(parts.length===1){rep[path]=value;rpgQueueReport({[path]:wire})}
else{
if(value===undefined)delete rep[parts[0]][parts[1]]
else rep[parts[0]][parts[1]]=value
rpgQueueReport({[parts[0]]:{[parts[1]]:wire}})
}
rpgRenderHead()
if(path==="title"){const t=rpgEl("rpgTitle");if(t)t.value=rep.title||""}
rpgRenderCover()
if(path==="title"||path==="status")return
const entry=path==="meta.schedule"?"timeline":parts[0]==="branding"?"branding":"details"
if(rpgS.entry===entry){rpgRerenderEntry();return}
const cur=rpgCurrentSection()
if(path==="meta.schedule"&&cur&&cur.kind==="project_timeline"){rpgRenderGenerated(cur);return}
return rpgSelectEntry(entry)
}
function rpgApplyReportGroup(group,values,from){
const rep=rpgS.report,wire={}
// Keys come from the side being left, so one that did not exist on the other side is cleared (sent as null).
Object.keys(from||{}).forEach((k)=>{
const v=rpgClone((values||{})[k])
if(v===undefined){delete rep[group][k];wire[k]=null}
else{rep[group][k]=v;wire[k]=v}
})
rpgQueueReport({[group]:wire})
rpgRenderCover()
const entry=group==="branding"?"branding":"details"
if(rpgS.entry===entry){rpgRerenderEntry();return}
return rpgSelectEntry(entry)
}
function rpgApplySecEdit(id,field,value){
const sec=rpgSectionById(id)
if(!sec)throw new Error("That section is no longer in the report.")
value=rpgClone(value)
const current=rpgCurrentSection()===sec
if(field==="content"){
if(current&&rpgS.rich&&rpgS.richSection===sec){
rpgS.rich.setHTML(value||"")
// Keep what the editor now holds, so its next change event is not mistaken for an edit.
try{const now=rpgS.rich.getHTML();if(typeof now==="string")value=now}catch(e){}
}
sec.content=value
rpgQueueSection(sec.id,{content:value})
if(!current)return rpgSelectEntry("sec:"+sec.id)
return
}
sec[field]=value
rpgQueueSection(sec.id,{[field]:value})
rpgRenderOutline()
if(!current)return
if(field==="title"){const t=rpgEl("rpgSecTitle");if(t)t.value=value||""}
if(field==="hidden"){const box=rpgEl("rpgSecInclude");if(box)box.checked=!value}
}
function rpgApplySecOrder(ids){
const rep=rpgS.report,have=rep.sections.map((s)=>s.id)
const want=(ids||[]).filter((id)=>have.indexOf(id)>=0)
have.forEach((id)=>{if(want.indexOf(id)<0)want.push(id)})
const by={}
rep.sections.forEach((s)=>{by[s.id]=s})
rep.sections=want.map((id)=>by[id])
rep.sections.forEach((s,i)=>{s.position=i})
rpgRenderOutline()
return bridgeCall("reports.sections_reorder",[rep.id,want])
}
function rpgDropSectionSaves(id){
clearTimeout(rpgS.timers["sec:"+id]);delete rpgS.timers["sec:"+id];delete rpgS.dirtySections[id];delete rpgS.errors["sec:"+id]
}
function rpgApplySecRemove(op){
const rep=rpgS.report,sec=rpgSectionById(op.sec.id)
if(!sec)return
const current=rpgCurrentSection()===sec
return (current?rpgTeardownEntry():Promise.resolve(true)).then(()=>{
// The step keeps the section as it is right now, so restoring it brings back exactly this text and place.
op.sec=rpgClone(sec);op.index=rep.sections.indexOf(sec)
rpgDropSectionSaves(sec.id)
return (rpgS.chains["sec:"+sec.id]||Promise.resolve()).then(()=>bridgeCall("reports.section_delete",[sec.id]))
}).then(()=>{
if(rpgS.report!==rep)return
const at=rep.sections.indexOf(sec)
if(at>=0)rep.sections.splice(at,1)
rep.sections.forEach((s,i)=>{s.position=i})
rpgRenderOutline()
if(current){rpgS.entry="";const next=rep.sections[Math.min(at,rep.sections.length-1)];return rpgSelectEntry(next?"sec:"+next.id:"details",true)}
})
}
function rpgApplySecRestore(op){
const rep=rpgS.report,snap=op.sec,at=Math.max(0,Math.min(op.index,rep.sections.length))
const payload={kind:snap.kind,title:snap.title,content:snap.content||"",hidden:!!snap.hidden,options:snap.options||{},after_id:at>0?rep.sections[at-1].id:0}
return bridgeCall("reports.section_add",[rep.id,payload]).then((sec)=>{
if(rpgS.report!==rep||!sec)return
rep.sections.splice(at,0,sec)
rep.sections.forEach((s,i)=>{s.position=i})
if(sec.id!==snap.id)rpgHistRemap(rpgS.hist,"sec",snap.id,sec.id)
return rpgSelectEntry("sec:"+sec.id,true)
})
}
function rpgFindingFields(f){
const out=rpgClone(f)
;["id","uid","report_id","position","created_at","updated_at","cvss_score"].forEach((k)=>{delete out[k]})
return out
}
// After the server applied a finding step: refresh the counters and show the result in the findings workspace.
function rpgFindingsSync(selectId){
const rep=rpgS.report
rep.findings.forEach((f,i)=>{f.position=i})
rep.stats=rpgCountSeverities(rep.findings)
rpgRenderRisk();rpgRenderOutline()
if(rpgS.findings&&typeof rpgS.findings.reload==="function"){rpgS.findings.reload(rep.findings,selectId);return}
const sec=rep.sections.find((s)=>s.kind==="findings")
if(!sec){const cur=rpgCurrentSection();if(cur&&rpgKindInfo(cur.kind).auto)rpgRenderGenerated(cur);return}
return rpgSelectEntry("sec:"+sec.id,true).then(()=>{if(rpgS.findings&&selectId!==undefined&&selectId!==null&&typeof rpgS.findings.openFinding==="function")rpgS.findings.openFinding(selectId)})
}
function rpgApplyFindingEdit(id,values){
const rep=rpgS.report
if(!rep.findings.some((f)=>f.id===id))throw new Error("That finding is no longer in the report.")
return bridgeCall("reports.finding_update",[id,rpgClone(values)]).then((f)=>{
if(rpgS.report!==rep||!f)return
const at=rep.findings.findIndex((x)=>x.id===id)
if(at>=0)rep.findings[at]=f
return rpgFindingsSync(id)
})
}
function rpgApplyFindingOrder(ids){
const rep=rpgS.report,have=rep.findings.map((f)=>f.id)
const want=(ids||[]).filter((id)=>have.indexOf(id)>=0)
have.forEach((id)=>{if(want.indexOf(id)<0)want.push(id)})
return bridgeCall("reports.findings_reorder",[rep.id,want]).then(()=>{
if(rpgS.report!==rep)return
const by={}
rep.findings.forEach((f)=>{by[f.id]=f})
rep.findings=want.map((id)=>by[id])
const sel=document.querySelector("#rpgGen .rpt-fi.active")
return rpgFindingsSync(sel?Number(sel.dataset.id):undefined)
})
}
function rpgApplyFindingRemove(op){
const rep=rpgS.report,at=rep.findings.findIndex((f)=>f.id===op.finding.id)
if(at<0)return
op.finding=rpgClone(rep.findings[at]);op.index=at
return bridgeCall("reports.finding_delete",[op.finding.id]).then(()=>{
if(rpgS.report!==rep)return
rep.findings=rep.findings.filter((f)=>f.id!==op.finding.id)
const next=rep.findings[Math.min(at,rep.findings.length-1)]
return rpgFindingsSync(next?next.id:null)
})
}
function rpgApplyFindingRestore(op){
const rep=rpgS.report,snap=op.finding,at=Math.max(0,Math.min(op.index,rep.findings.length))
return bridgeCall("reports.finding_add",[rep.id,rpgFindingFields(snap)]).then((f)=>{
if(rpgS.report!==rep||!f)return
rep.findings=rep.findings.slice()
rep.findings.splice(at,0,f)
if(f.id!==snap.id)rpgHistRemap(rpgS.hist,"f",snap.id,f.id)
const done=()=>rpgFindingsSync(f.id)
if(at===rep.findings.length-1)return done()
return bridgeCall("reports.findings_reorder",[rep.id,rep.findings.map((x)=>x.id)]).then(done)
})
}
// The editable element that owns the caret, when it is one of this page's fields.
function rpgFocusedField(){
const el=document.activeElement
if(!el||el===document.body)return null
if(el.isContentEditable)return el.closest('[contenteditable="true"],[contenteditable=""]')||el
if(el.tagName==="TEXTAREA")return el
if(el.tagName==="INPUT"&&!/^(checkbox|radio|button|submit|reset|range|color|file)$/i.test(el.type||""))return el
return null
}
function rpgFieldText(el){return el.isContentEditable?el.innerHTML:el.value}
// Ctrl+Z / Ctrl+Shift+Z / Ctrl+Y. Returns true when the key was taken.
function rpgUndoKey(e,dir){
if(rpgDialogOpen())return false
const field=rpgFocusedField(),root=rpgEl("rpgRoot")
if(field&&!(root&&root.contains(field)))return false
if(!field||!rpgS.typed.has(field)){
e.preventDefault();e.stopPropagation()
rpgUndoRedo(dir)
return true
}
// The field has text of its own to undo: that goes first. If it changed nothing, its history is used up and the report's
// takes over. (The engine's undo history is shared by the whole page, so it may change another field: any input event counts.)
const before=rpgFieldText(field),seq=rpgS.inputSeq
const webkit=document.documentElement.classList.contains("engine-webkit")
rpgS.nativeUntil=Date.now()+1500
setTimeout(()=>{
// GTK has no key binding for undo, so WebKitGTK does nothing by itself: run the field's undo for it, unless the field's
// own key handler already took the key. Chromium has done it by now.
if(webkit&&!e.defaultPrevented&&document.activeElement&&field.contains(document.activeElement)){try{document.execCommand(dir)}catch(err){}}
setTimeout(()=>{
if(!document.contains(field)||rpgS.inputSeq!==seq||rpgFieldText(field)!==before)return
rpgS.nativeUntil=0
rpgS.typed.delete(field)
rpgUndoRedo(dir)
},40)
},0)
return false
}

// ---- main pane events (delegated once) ----
function rpgMainInput(e){
const t=e.target,rep=rpgS.report
if(!rep||!t||!t.closest)return
const ms=t.closest("[data-ms]")
if(ms){if(t.dataset.f)rpgMsField(ms,t);return}
if(t.id==="rpgSecTitle"){
const sec=rpgCurrentSection(),v=t.value.trim()
if(sec&&v&&rpgSecSet(sec,"title",v)){const span=rpgEl("rpgOutlineList").querySelector(`.rpg-ol-row[data-id="${sec.id}"] .rpg-ol-title`);if(span)span.textContent=v}
return
}
const color=t.closest(".rpg-color")
if(color){
// While typing only a full #rrggbb applies; the short #rgb form is accepted when the field is left (see rpgMainChange).
if(t.classList.contains("rpg-color-native"))rpgSetColor(color,t.value,"native")
else if(/^#?[0-9a-f]{6}$/i.test(t.value.trim()))rpgSetColor(color,t.value,"text")
else t.classList.toggle("invalid",!/^#?[0-9a-f]{0,5}$/i.test(t.value.trim()))
return
}
const combo=t.closest(".rpg-combo")
if(combo){if(t.tagName==="INPUT")rpgSetPath(combo.dataset.combo,t.value.trim());return}
const le=t.closest(".rpg-le")
if(le){rpgCollectList(le);return}
const path=t.dataset.bind
if(!path||t.type==="checkbox"||t.tagName==="SELECT")return
if(t.dataset.date){
t.parentNode.classList.toggle("empty",!t.value)
if(t.value===""||rpgValidDate(t.value)){t.classList.remove("invalid");if(rep[path.split(".")[0]][path.split(".")[1]]!==t.value)rpgSetPath(path,t.value)}
else t.classList.add("invalid")
return
}
rpgSetPath(path,t.value)
}
function rpgMainChange(e){
const t=e.target,rep=rpgS.report
if(!rep||!t||!t.closest)return
const ms=t.closest("[data-ms]")
if(ms){if(t.dataset.f)rpgMsField(ms,t);return}
if(t.id==="rpgSecInclude"){const sec=rpgCurrentSection();if(sec&&sec.hidden===t.checked)rpgToggleHidden(sec.id);return}
if(t.id==="rpgProfileSel"){rpgProfileChanged(t);return}
if(t.classList.contains("rpg-color-hex")){
const box=t.closest(".rpg-color"),hex=rpgNormHex(t.value)
if(hex)rpgSetColor(box,hex,"blur")
else{const p=box.dataset.color.split(".");t.value=rpgNormHex(rep[p[0]][p[1]])||box.querySelector(".rpg-color-native").value;t.classList.remove("invalid")}
return
}
const combo=t.closest(".rpg-combo")
if(combo&&t.tagName==="SELECT"){
const inp=combo.querySelector("input")
const custom=t.value==="__custom"
inp.classList.toggle("hidden",!custom)
if(custom){inp.focus();rpgSetPath(combo.dataset.combo,inp.value.trim())}
else rpgSetPath(combo.dataset.combo,t.value)
return
}
const path=t.dataset.bind
if(!path)return
if(t.type==="checkbox")rpgSetPath(path,t.checked)
else if(t.tagName==="SELECT")rpgSetPath(path,t.value)
else if(t.dataset.date)rpgMainInput(e)
}
function rpgMainClick(e){
const btn=e.target.closest("[data-act]")
if(!btn||!rpgS.report)return
const act=btn.dataset.act,le=btn.closest(".rpg-le")
if(act==="le-add"&&le){const row=rpgListAddRow(le);row.querySelector("input").focus();return}
if(act==="le-remove"&&le){
const rows=le.querySelectorAll(".rpg-le-row")
if(rows.length>1)btn.closest(".rpg-le-row").remove()
else btn.closest(".rpg-le-row").querySelectorAll("input").forEach((i)=>{i.value=""})
rpgCollectList(le)
return
}
if(act==="date-clear"){const inp=btn.parentNode.querySelector("input");inp.value="";rpgMainInput({target:inp});return}
if(act==="fill-targets"&&le)return rpgFillFromTargets(le)
if(act==="swatch")return rpgSetColor(btn.closest(".rpg-color"),btn.dataset.hex,"swatch")
if(act==="logo-pick")return rpgEl("rpgLogoFile").click()
if(act==="logo-remove"){rpgSetPath("branding.logo_asset","");rpgLoadLogo();return}
if(act==="toggle-intro"){const box=rpgEl("rpgIntro");btn.classList.toggle("open",box.classList.toggle("collapsed")===false);return}
if(act==="insert-note")return rpgInsertFromNote()
if(act==="ai-draft")return rpgAiDraft(btn)
if(act==="placeholder"){if(rpgS.rich){rpgS.rich.insertHTML(rpgEsc(btn.dataset.token));rpgSyncRich()}return}
if(act==="goto-details")return rpgSelectEntry("details")
if(act==="goto-timeline")return rpgSelectEntry("timeline")
const ms=btn.closest("[data-ms]")
if(act==="ms-add")return rpgMsAddMenu(btn)
if(act==="ms-fill")return rpgMsFill()
if(act==="ms-remove"&&ms)return rpgMsRemove(ms)
if(act==="ms-remind"&&ms)return rpgMsToggleRemind(ms,Number(btn.dataset.days))
if(act==="ms-remind-custom"&&ms)return rpgMsCustomRemind(ms,btn)
if(act==="evidence")return rpgOptional("ReportEvidence","openManager","The evidence manager")
}
function rpgMainKeydown(e){
const t=e.target,le=t.closest&&t.closest(".rpg-le")
if(!le||t.tagName!=="INPUT"||e.key!=="Enter")return
e.preventDefault()
const row=rpgListAddRow(le,"",t.closest(".rpg-le-row"))
row.querySelector("input").focus()
}
// Pasting several lines into a list row makes one row per line.
function rpgMainPaste(e){
const t=e.target,le=t.closest&&t.closest(".rpg-le")
if(!le||le.dataset.testers||t.tagName!=="INPUT")return
const text=(e.clipboardData||window.clipboardData||{getData:()=>""}).getData("text/plain")||""
const lines=rpgSplitLines(text)
if(lines.length<2)return
e.preventDefault()
let after=t.closest(".rpg-le-row")
if(!t.value.trim()){t.value=lines.shift()}
lines.forEach((l)=>{after=rpgListAddRow(le,l,after)})
rpgCollectList(le)
}

// ---- preview ----
function rpgOpenPreview(){
const rep=rpgS.report
if(!rep)return
if(!rpgHas("reportsIO.preview_html")){
const m=rpgModal("Preview",'<div class="rpg-none">The export module is not available in this build, so the report cannot be previewed.</div>',{cls:"rpg-modal-small"})
rpgFootBtn(m,"Close","rpg-btn-primary",()=>closeModal())
return
}
let size=rep.options.page_size==="Letter"?"Letter":"A4"
const m=rpgModal("Preview: "+(rep.title||"Untitled report"),'<div class="rpg-prev-stage" id="rpgPrevStage"><div class="rpg-none">Building the preview...</div></div>',{cls:"rpg-modal-preview"})
m.tools.innerHTML=`<div class="rpg-seg" id="rpgPrevSize"><button type="button" data-size="A4">A4</button><button type="button" data-size="Letter">Letter</button></div><button type="button" class="rpg-btn rpg-btn-sm" id="rpgPrevRefresh" title="Rebuild the preview"><i class="icon icon-refresh"></i><span>Refresh</span></button><button type="button" class="rpg-btn rpg-btn-sm" id="rpgPrevExport"><i class="icon rpg-ic-export"></i><span>Export...</span></button>`
m.foot.remove()
const stage=m.body.querySelector("#rpgPrevStage")
let frame=null,token=0
const fit=()=>{
if(!frame||!m.isOpen())return
const w=RPG_PAGE_WIDTHS[size],avail=stage.clientWidth-32,scale=Math.min(1,avail/w)
frame.style.width=w+"px"
frame.style.height=Math.max(200,Math.floor((stage.clientHeight-32)/scale))+"px"
frame.style.transform=scale<1?`scale(${scale})`:""
frame.parentNode.style.width=Math.floor(w*scale)+"px"
frame.parentNode.style.height=Math.floor((stage.clientHeight-32))+"px"
}
const load=()=>{
const mine=++token
m.tools.querySelectorAll("#rpgPrevSize button").forEach((b)=>b.classList.toggle("active",b.dataset.size===size))
stage.innerHTML='<div class="rpg-none">Building the preview...</div>'
frame=null
rpgFlush().then(()=>bridgeCall("reportsIO.preview_html",[rep.id,{page_size:size}])).then((html)=>{
if(mine!==token||!m.isOpen())return
stage.innerHTML='<div class="rpg-prev-page"><iframe class="rpg-prev-frame" sandbox="" referrerpolicy="no-referrer" title="Report preview"></iframe></div>'
frame=stage.querySelector("iframe")
frame.srcdoc=rpgPreviewDoc(html)
fit()
}).catch((err)=>{if(mine===token&&m.isOpen())stage.innerHTML=`<div class="rpg-none error">${rpgEsc(rpgErr(err,"Could not build the preview"))}</div>`})
}
m.tools.addEventListener("click",(e)=>{
const b=e.target.closest("button")
if(!b)return
if(b.dataset.size){size=b.dataset.size;load()}
else if(b.id==="rpgPrevRefresh")load()
else if(b.id==="rpgPrevExport"){closeModal(true);rpgExport(rep.id)}
})
const onResize=()=>{if(!m.isOpen()){window.removeEventListener("resize",onResize);return}fit()}
window.addEventListener("resize",onResize)
load()
}

// ---- versions ----
function rpgOpenVersions(){
const rep=rpgS.report
if(!rep)return
const m=rpgModal("Versions",`<div class="rpg-hint">A version is a snapshot of the whole report (details, sections and findings). Restoring one replaces the current content.</div>
<div class="rpg-ver-new"><input type="text" class="rpg-input" id="rpgVerLabel" maxlength="120" placeholder="Label, e.g. Draft sent to the client"><button type="button" class="rpg-btn rpg-btn-primary" id="rpgVerSave"><i class="icon icon-save"></i><span>Save version</span></button></div>
<div class="rpg-rows" id="rpgVerRows"><div class="rpg-none">Loading...</div></div>`,{cls:"rpg-modal-mid"})
const rows=m.body.querySelector("#rpgVerRows"),label=m.body.querySelector("#rpgVerLabel"),save=m.body.querySelector("#rpgVerSave")
const paint=(list)=>{
rep.versions=list||[]
rows.innerHTML=rep.versions.length?rep.versions.map((v)=>`<div class="rpg-row" data-id="${Number(v.id)}"><i class="icon icon-clock"></i><div class="rpg-row-main"><div class="rpg-row-title">${rpgEsc(v.label||"Version")}</div><div class="rpg-row-sub" title="${rpgEsc(v.created_at||"")}">${rpgEsc(rpgRelTime(v.created_at))} &middot; ${rpgEsc(String(v.created_at||"").replace("T"," ").slice(0,16))} UTC</div></div><button type="button" class="rpg-btn rpg-btn-sm" data-act="restore">Restore</button><button type="button" class="rpg-icon-btn danger" data-act="delete" title="Delete this version"><i class="icon icon-trash"></i></button></div>`).join(""):'<div class="rpg-none">No versions saved yet.</div>'
}
const load=()=>bridgeCall("reports.versions",[rep.id]).then((list)=>{if(m.isOpen())paint(list)}).catch((err)=>{rows.innerHTML=`<div class="rpg-none error">${rpgEsc(rpgErr(err,"Could not load the versions"))}</div>`})
const create=()=>{
if(save.disabled)return
save.disabled=true
rpgFlush().then((ok)=>{if(!ok)throw new Error("the report has changes that could not be saved");return bridgeCall("reports.version_create",[rep.id,label.value.trim()||"Version "+(rep.versions.length+1)])}).then(()=>{label.value="";save.disabled=false;rpgToast("Version saved");return load()}).catch((err)=>{save.disabled=false;rpgToast(rpgErr(err,"Could not save the version"),true)})
}
save.addEventListener("click",create)
label.addEventListener("keydown",(e)=>{if(e.key==="Enter"){e.preventDefault();create()}})
rows.addEventListener("click",(e)=>{
const btn=e.target.closest("[data-act]"),row=e.target.closest(".rpg-row")
if(!btn||!row)return
const v=rep.versions.find((x)=>x.id===Number(row.dataset.id))
if(!v)return
if(btn.dataset.act==="delete")appConfirm(`Delete the version "${v.label||"Version"}"? This cannot be undone.`,{okLabel:"Delete",danger:true}).then((yes)=>{if(yes)bridgeCall("reports.version_delete",[v.id]).then(load).catch((err)=>rpgToast(rpgErr(err,"Could not delete the version"),true))})
if(btn.dataset.act==="restore")appConfirm(`Restore the version "${v.label||"Version"}"? The current content of the report is replaced. Save a version first if you want to keep it.`,{okLabel:"Restore",danger:true}).then((yes)=>{
if(!yes)return
rpgFlush().then((ok)=>{if(!ok)throw new Error("The report has changes that could not be saved. Save them or go back to the list and discard them first.");return bridgeCall("reports.version_restore",[rep.id,v.id])}).then((restored)=>{
closeModal(true)
const entry=/^sec:/.test(rpgS.entry)?(rpgCurrentSection()||{}).kind:rpgS.entry
rpgDropPending()
return rpgShowReport(restored,entry).then(()=>rpgToast("Version restored"))
}).catch((err)=>rpgToast(rpgErr(err,"Could not restore the version"),true))
})
})
rpgFootBtn(m,"Close","",()=>closeModal())
load()
setTimeout(()=>label.focus(),30)
}

// ---- lifecycle ----
function rpgRefresh(){
if(!rpgS.ready)return Promise.resolve()
if(rpgS.view!=="editor"||!rpgS.report)return rpgLoadList()
const rep=rpgS.report
// Queued or failed saves (for example refused while the app was locked) go out first; only a clean report is re-read.
return rpgFlush().then((ok)=>{
if(!ok||rpgS.report!==rep||rpgIsDirty())return
return bridgeCall("reports.get",[rep.id]).then((fresh)=>{
if(rpgS.report!==rep||rpgIsDirty())return
const main=rpgEl("rpgMain"),typing=main&&main.contains(document.activeElement)&&document.activeElement!==document.body
fresh=rpgNormReport(fresh)
// Sections or findings were added or removed elsewhere (import, AI tools, another window): the recorded steps no longer fit.
if(!rpgSameIds(rep.sections,fresh.sections)||!rpgSameIds(rep.findings,fresh.findings)){rpgHistClear(rpgS.hist);rpgRenderUndo()}
if(typing||document.getElementById("appModalBackdrop")){rep.findings=fresh.findings;rep.stats=fresh.stats;rep.versions=fresh.versions;rpgRenderRisk();rpgRenderOutline();return}
const cur=rpgCurrentSection()
if(cur&&cur.kind==="findings"&&rpgS.findings&&fresh.sections.some((s)=>s.id===cur.id)){
// Keep the findings workspace (and the finding that is open in it) alive; only hand it the new data.
const keep=fresh.sections.find((s)=>s.id===cur.id)
Object.assign(cur,keep,{content:cur.content})
fresh.sections[fresh.sections.indexOf(keep)]=cur
rpgS.report=fresh
rpgRenderHead();rpgRenderOutline()
if(typeof rpgS.findings.refresh==="function")try{rpgS.findings.refresh(fresh.findings)}catch(e){}
return
}
const scroll=main?main.scrollTop:0,entry=rpgS.entry
rpgTeardownEntry(true)
rpgS.report=fresh
rpgRenderHead()
if(/^sec:/.test(entry)&&!rpgCurrentSection())rpgS.entry="details"
rpgRenderOutline();rpgRenderEntry()
if(main)main.scrollTop=scroll
}).catch((err)=>{if(/not found/i.test(rpgErr(err,""))){rpgToast("This report no longer exists.",true);rpgDropPending();rpgTeardownEntry(true);rpgS.report=null;rpgShowView("list");rpgLoadList()}})
})
}
function rpgHandleKeydown(e){
if(e.defaultPrevented||!rpgPageActive()||!rpgS.report||rpgS.view!=="editor")return
const mod=e.ctrlKey||e.metaKey,key=(e.key||"").toLowerCase()
if(mod&&!e.altKey&&key==="z"){rpgUndoKey(e,e.shiftKey?"redo":"undo");return}
if(mod&&!e.altKey&&!e.shiftKey&&key==="y"){rpgUndoKey(e,"redo");return}
if(e.altKey&&!mod&&!e.shiftKey&&!rpgDialogOpen()){
const field=rpgFocusedField(),root=rpgEl("rpgRoot")
// Typing in the terminal or the AI panel is not ours to interrupt.
if(!field||(root&&root.contains(field))){
const n=/^Digit[1-9]$/.test(e.code||"")?Number(e.code.slice(5)):0
if(e.code==="KeyA"||key==="a"){e.preventDefault();e.stopPropagation();rpgOpenSectionPicker();return}
if(n&&n<=RPG_QUICK_KINDS.length){e.preventDefault();e.stopPropagation();rpgQuickAdd(RPG_QUICK_KINDS[n-1]);return}
}
}
if(mod&&!e.altKey&&!e.shiftKey&&key==="s"){
e.preventDefault();e.stopPropagation()
rpgFlush().then((ok)=>rpgToast(ok?"Report saved":"Some changes could not be saved",!ok))
return
}
if(mod&&!e.altKey&&e.shiftKey&&key==="p"){
if(document.getElementById("appModalBackdrop"))return
e.preventDefault();e.stopPropagation()
rpgOpenPreview()
}
}
function rpgBind(){
const root=rpgEl("rpgRoot")
root.querySelector(".rpg-toolbar").addEventListener("click",(e)=>{const b=e.target.closest("[data-act]");if(b)rpgListAction(b.dataset.act)})
const search=rpgEl("rpgSearch")
// Typing repaints once it pauses; Enter does it at once and the down arrow steps into the cards.
search.addEventListener("input",()=>{rpgS.q=search.value;clearTimeout(rpgS.searchTimer);rpgS.searchTimer=setTimeout(rpgRenderList,RPG_SEARCH_DELAY)})
search.addEventListener("keydown",(e)=>{
if(e.key==="Escape"&&search.value){e.stopPropagation();search.value="";rpgS.q="";rpgRenderList()}
else if(e.key==="Enter"){rpgS.q=search.value;rpgRenderList()}
else if(e.key==="ArrowDown"){rpgS.q=search.value;rpgRenderList({keep:true});const first=document.querySelector("#rpgList .rpg-card");if(first){e.preventDefault();first.focus()}}
})
rpgEl("rpgStatusFilter").addEventListener("change",(e)=>{rpgS.status=e.target.value;rpgRenderList()})
rpgEl("rpgSort").addEventListener("change",(e)=>{rpgS.sort=e.target.value;rpgRenderList()})
const list=rpgEl("rpgList")
list.addEventListener("click",(e)=>{
const btn=e.target.closest("[data-act]"),card=e.target.closest(".rpg-card")
if(btn)return rpgListAction(btn.dataset.act,card?Number(card.dataset.id):0)
if(card)rpgOpen(Number(card.dataset.id))
})
list.addEventListener("keydown",rpgListKey)
list.addEventListener("contextmenu",(e)=>{
const card=e.target.closest(".rpg-card")
if(!card)return
e.preventDefault()
// The menu key raises this event too (without a pointer position): the menu then opens on the card, with the focus in it.
const kbd=e.button!==2&&document.activeElement===card
rpgCardMenu(Number(card.dataset.id),kbd?null:{x:e.clientX,y:e.clientY},kbd)
})
// Where the menu key raises its contextmenu event after the keydown that already opened the card menu, that event is dropped.
document.addEventListener("contextmenu",(e)=>{if(Date.now()-rpgS.menuKbdAt<700&&rpgEl("rpgMenu")){e.preventDefault();e.stopPropagation()}},true)
if(typeof ResizeObserver!=="undefined"){rpgS.listRO=new ResizeObserver(rpgListResized);rpgS.listRO.observe(list)}
else window.addEventListener("resize",rpgListResized)
rpgEl("rpgBackBtn").addEventListener("click",rpgBackToList)
const title=rpgEl("rpgTitle")
title.addEventListener("input",()=>{const v=title.value.trim();if(rpgS.report&&v)rpgSetPath("title",v)})
title.addEventListener("blur",()=>{if(rpgS.report&&!title.value.trim())title.value=rpgS.report.title||"Untitled report"})
title.addEventListener("keydown",(e)=>{if(e.key==="Enter"){e.preventDefault();title.blur()}})
rpgEl("rpgStatus").addEventListener("change",(e)=>{if(rpgS.report){rpgSetPath("status",e.target.value,{key:null});e.target.dataset.status=e.target.value;rpgPaintStatusSelect()}})
rpgEl("rpgUndoBtn").addEventListener("click",()=>rpgUndoRedo("undo"))
rpgEl("rpgRedoBtn").addEventListener("click",()=>rpgUndoRedo("redo"))
rpgEl("rpgDeadline").addEventListener("click",()=>rpgSelectEntry("timeline"))
rpgEl("rpgQuickAdd").addEventListener("click",(e)=>{const b=e.target.closest("[data-kind]");if(b)rpgQuickAdd(b.dataset.kind)})
// Which fields have text of their own to undo, and whether a change came from the field's own undo (see rpgUndoKey).
root.addEventListener("input",(e)=>{
rpgS.nativeHist=/^history/.test(e.inputType||"")
rpgS.inputSeq++
const f=e.target&&e.target.isContentEditable?(e.target.closest('[contenteditable="true"],[contenteditable=""]')||e.target):e.target
if(f&&f.nodeType===1)rpgS.typed.add(f)
setTimeout(()=>{rpgS.nativeHist=false},0)
},true)
root.addEventListener("focusout",()=>rpgHistSeal(rpgS.hist))
rpgEl("rpgRisk").addEventListener("click",()=>{const s=rpgS.report&&rpgS.report.sections.find((x)=>x.kind==="findings");if(s)rpgSelectEntry("sec:"+s.id);else rpgToast("This report has no Detailed findings section. Add one from the outline.",true)})
rpgEl("rpgSaveState").addEventListener("click",()=>rpgFlush())
rpgEl("rpgPreviewBtn").addEventListener("click",rpgOpenPreview)
rpgEl("rpgExportBtn").addEventListener("click",()=>rpgS.report&&rpgExport(rpgS.report.id))
rpgEl("rpgVersionsBtn").addEventListener("click",()=>rpgFlush().then(rpgOpenVersions))
rpgEl("rpgTplSaveBtn").addEventListener("click",rpgSaveAsTemplate)
rpgEl("rpgMoreBtn").addEventListener("click",(e)=>rpgOpenMore(e.currentTarget))
rpgEl("rpgOutlineFixed").addEventListener("click",(e)=>{const b=e.target.closest("[data-entry]");if(b)rpgSelectEntry(b.dataset.entry)})
const ol=rpgEl("rpgOutlineList")
ol.addEventListener("pointerdown",rpgOutlinePointerDown)
ol.addEventListener("keydown",rpgOutlineKey)
ol.addEventListener("click",(e)=>{
const btn=e.target.closest("[data-act]"),row=e.target.closest(".rpg-ol-row")
if(!btn||!row)return
if(btn.dataset.act==="hide")rpgToggleHidden(row.dataset.id)
if(btn.dataset.act==="delete")rpgDeleteSection(row.dataset.id)
})
ol.addEventListener("dblclick",(e)=>{const row=e.target.closest(".rpg-ol-row");if(row&&!e.target.closest("button,input"))rpgRenameSection(row.dataset.id)})
ol.addEventListener("contextmenu",(e)=>{const row=e.target.closest(".rpg-ol-row");if(!row)return;e.preventDefault();rpgSectionMenu(row.dataset.id,{x:e.clientX,y:e.clientY})})
rpgEl("rpgAddSection").addEventListener("click",()=>rpgOpenSectionPicker())
const main=rpgEl("rpgMain")
main.addEventListener("input",rpgMainInput)
main.addEventListener("change",rpgMainChange)
main.addEventListener("click",rpgMainClick)
main.addEventListener("keydown",rpgMainKeydown)
main.addEventListener("paste",rpgMainPaste)
document.addEventListener("keydown",rpgHandleKeydown,true)
document.addEventListener("loya:page-shown",(e)=>{
const d=e.detail||{}
if(d.page==="reporting"){if(!d.first)rpgRefresh();rpgPollReminders();if(rpgS.entry==="branding")rpgMountThemes();if(rpgS.entry==="details")rpgMountTargets()}
// Navigation cannot be blocked, so everything pending is sent the moment another page is shown.
else if(rpgS.report)rpgFlush()
})
window.addEventListener("beforeunload",()=>{if(rpgS.report)rpgFlush()})
}
let rpgReadyPromise=null
function initReporting(){
if(rpgReadyPromise)return rpgReadyPromise
rpgReadyPromise=fetch("../pages/reporting.html").then((r)=>r.text()).then((html)=>{
document.querySelector('.page[data-page="reporting"]').innerHTML=html
rpgBind()
rpgS.ready=true
rpgShowView(rpgS.view)
return rpgLoadList()
})
return rpgReadyPromise
}
if(typeof window!=="undefined"){
window.Reporting={
open:(reportId,opts)=>rpgOpen(reportId,opts),
newReport:(opts)=>{
const nav=rpgPageActive()||typeof goToPage!=="function"?Promise.resolve():Promise.resolve(goToPage("reporting"))
return nav.then(()=>initReporting()).then(()=>rpgNewReport(opts))
},
refresh:()=>rpgRefresh(),
isDirty:()=>rpgIsDirty(),
flush:()=>rpgFlush(),
current:()=>rpgS.report,
undo:()=>rpgUndoRedo("undo"),
redo:()=>rpgUndoRedo("redo"),
addSection:()=>rpgOpenSectionPicker(),
openEntry:(key)=>rpgS.report?rpgSelectEntry(key):Promise.resolve(),
checkReminders:()=>rpgPollReminders()
}
// Deadline reminders are checked shortly after start and every five minutes, whichever page is open.
if(typeof document!=="undefined"&&typeof setInterval==="function"){
setTimeout(rpgPollReminders,6000)
setInterval(rpgPollReminders,5*60*1000)
}
}
