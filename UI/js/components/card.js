// Dashboard card renderers. Everything here builds HTML strings from stats data and must escape every
// piece of user text with dashEsc (note, command, target and key names can contain markup).
// Interactive bits are real <button>/<select> elements carrying data-act; dashboard.js wires them by delegation.
function dashEsc(s){
return String(s===undefined||s===null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")
}
function widgetMeta(catalog,id){
return ((catalog&&catalog.widgets)||[]).find((w)=>w.id===id)||{id:id,label:id,icon:"info",kind:"stat"}
}
function formatBytes(n){
if(!n)return "0 B"
const units=["B","KB","MB","GB"]
let i=0
let v=n
while(v>=1024&&i<units.length-1){v/=1024;i++}
return v.toFixed(v<10&&i>0?1:0)+" "+units[i]
}
function dashFmtDuration(s){
if(s===null||s===undefined||isNaN(s))return ""
s=Math.max(0,Math.round(s))
if(s<60)return s+"s"
if(s<3600)return Math.floor(s/60)+"m "+(s%60)+"s"
return Math.floor(s/3600)+"h "+Math.floor((s%3600)/60)+"m"
}
function dashPlural(n,word){return n+" "+word+(n===1?"":"s")}
function dashIcon(name){return `<i class="icon icon-${dashEsc(name)}" aria-hidden="true"></i>`}
function dashEmpty(text,actionHtml){
return `<div class="dash-empty"><div class="dash-empty-text">${dashEsc(text)}</div>${actionHtml||""}</div>`
}
function dashBtn(act,label,icon,attrs,cls){
return `<button type="button" class="${cls||"dash-mini-btn"}" data-act="${dashEsc(act)}"${attrs||""} title="${dashEsc(label)}" aria-label="${dashEsc(label)}">${icon?dashIcon(icon):""}${cls==="dash-link-btn"||cls==="dash-empty-btn"?`<span>${dashEsc(label)}</span>`:""}</button>`
}
function cardStatInfo(widget,stats){
if(widget==="notes_count")return {value:String(stats.notes_count||0),sub:"total notes"}
if(widget==="commands_count")return {value:String(stats.commands_count||0),sub:(stats.commands_standalone||0)+" standalone / "+(stats.commands_linked||0)+" linked"}
if(widget==="targets_count")return {value:String(stats.targets_count||0),sub:"saved targets"}
if(widget==="recycle_bin_count")return {value:String(stats.recycle_bin_count||0),sub:"items in recycle bin"}
if(widget==="backup_status"){
const b=stats.backup_status||{}
const days=b.latest_days_ago
const val=days==null?"Never":(days===0?"Today":days+"d ago")
return {value:val,sub:(b.count||0)+" backups"}
}
if(widget==="storage_usage")return {value:formatBytes(stats.storage_usage_bytes),sub:"database size"}
if(widget==="time_since_activity"){
const t=stats.time_since_activity||{}
return {value:t.label||"-",sub:t.what||""}
}
if(widget==="active_engagement"){
const e=stats.active_engagement||{}
return {value:e.name||"Default",sub:(e.targets_count||0)+" targets"}
}
if(widget==="update_status"){
const u=stats.update_status||{}
return {value:u.label||"-",sub:u.sub||""}
}
if(widget==="terminal_jobs"){
const j=stats.terminal_jobs||{}
return {value:String(j.running||0),sub:j.total?"running, "+(j.failed||0)+" failed of "+j.total+" recorded":"running, no jobs recorded yet"}
}
return {value:"-",sub:""}
}
// Which stats key feeds a widget: used to show a per-card error when the backend reports that part failed.
const DASH_WIDGET_DATA={notes_count:"kpi",commands_count:"kpi",targets_count:"kpi",terminal_jobs:"kpi",recent_activity:"recent_activity",recent_jobs:"recent_jobs",engagements:"engagements",live_target:"live_target",most_used_commands:"most_used_commands",favorite_snippets:"favorite_snippets",recent_notes:"recent_notes",pinned_notes:"pinned_notes",missing_placeholders:"missing_placeholders",activity_heat:"activity_heat",security_health:"security_health",reports:"reports"}
function renderSparkline(series){
const vals=(series||[]).map((v)=>Number(v)||0)
if(vals.length<2)return ""
const max=Math.max(1,...vals)
const w=100,h=28
const step=w/(vals.length-1)
const pts=vals.map((v,i)=>(i*step).toFixed(2)+","+(h-2-(v/max)*(h-4)).toFixed(2))
return `<svg class="dash-spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true"><polygon class="dash-spark-area" points="0,${h} ${pts.join(" ")} ${w},${h}"></polygon><polyline class="dash-spark-line" points="${pts.join(" ")}"></polyline></svg>`
}
const DASH_KPI={notes_count:{key:"notes",sub:"notes",delta:"new this week",goto:"notes"},commands_count:{key:"commands",sub:"commands",delta:"new this week",goto:"commands"},targets_count:{key:"targets",sub:"targets",delta:"new this week",goto:"targets"},terminal_jobs:{key:"jobs",sub:"running now",delta:"started this week",goto:"terminal"}}
function renderKpi(widget,stats){
const spec=DASH_KPI[widget]
// Older backends (and a partial failure) have no kpi block: fall back to the plain counts.
const legacy={notes:stats.notes_count,commands:stats.commands_count,targets:stats.targets_count,jobs:(stats.terminal_jobs||{}).running}
const k=((stats.kpi||{})[spec.key])||{value:legacy[spec.key]||0,week:0,series:[]}
const week=Number(k.week)||0
let sub=spec.sub
if(widget==="commands_count")sub=(stats.commands_standalone||0)+" standalone / "+(stats.commands_linked||0)+" linked"
const hasKpi=!!((stats.kpi||{})[spec.key])
const delta=!hasKpi?"":`<span class="dash-delta${week>0?" up":""}">${week>0?"+":""}${week} ${dashEsc(spec.delta)}</span>`
const failed=widget==="terminal_jobs"&&k.failed_day?`<span class="dash-delta down">${k.failed_day} failed today</span>`:""
const label=spec.goto==="terminal"?"Open the terminal":"Go to "+spec.goto
return `<button type="button" class="dash-kpi" data-act="goto" data-page="${spec.goto}" aria-label="${dashEsc(label)}"><span class="dash-kpi-value">${dashEsc(k.value)}</span><span class="dash-kpi-sub">${dashEsc(sub)}</span><span class="dash-kpi-deltas">${delta}${failed}</span>${renderSparkline(k.series)}</button>`
}
const DASH_FEED_ICONS={note:"edit",command:"commands",target:"target",job:"play"}
function renderFeed(items){
if(!items||!items.length)return dashEmpty("No activity yet - create a note or command to get started.",dashBtn("quick","Add note","edit",' data-q="note"',"dash-empty-btn"))
const rows=items.map((it)=>{
const failed=/failed|interrupted|lost/.test(it.action||"")
const body=`<span class="dash-feed-dot dash-feed-${dashEsc(it.kind)}${failed?" bad":""}">${dashIcon(DASH_FEED_ICONS[it.kind]||"info")}</span><span class="dash-feed-text"><span class="dash-feed-title">${dashEsc(it.title)}</span><span class="dash-feed-meta">${dashEsc((it.kind==="job"?"Job":it.kind==="note"?"Note":it.kind==="target"?"Target":"Command")+" "+(it.action||""))}</span></span><span class="dash-feed-time">${dashEsc(it.relative)}</span>`
if(it.deleted)return `<li class="dash-feed-item deleted">${body}</li>`
return `<li class="dash-feed-item"><button type="button" class="dash-feed-btn" data-act="feed-open" data-kind="${dashEsc(it.kind)}" data-id="${dashEsc(it.ref_id)}" data-src="${dashEsc(it.ref_src)}">${body}</button></li>`
}).join("")
return `<ol class="dash-feed">${rows}</ol>`
}
const DASH_JOB_STATES={running:"Running",pending:"Queued",done:"Done",failed:"Failed",killed:"Interrupted",skipped:"Skipped",orphaned:"Lost"}
function dashJobStateLevel(state){
if(state==="running"||state==="pending")return "run"
if(state==="done")return "ok"
if(state==="failed"||state==="killed")return "bad"
return "info"
}
function renderJobs(data){
data=data||{}
const items=data.items||[]
if(!items.length)return dashEmpty("No jobs yet - run a command from Commands or Quick Run.",dashBtn("goto","Open Commands","commands",' data-page="commands"',"dash-empty-btn"))
const rows=items.map((j,i)=>{
const state=DASH_JOB_STATES[j.state]||j.state||"-"
const code=j.state==="failed"&&j.exit_code!==null&&j.exit_code!==undefined?" "+j.exit_code:""
const meta=[j.relative,dashFmtDuration(j.duration_s)].filter(Boolean).join(" - ")
return `<li class="dash-row"><button type="button" class="dash-row-main" data-act="job-open" data-idx="${i}" title="View output"><span class="dash-pill ${dashJobStateLevel(j.state)}">${dashEsc(state+code)}</span><span class="dash-row-text"><span class="dash-row-title mono">${dashEsc(j.command||j.label||"command")}</span><span class="dash-row-meta">${dashEsc(meta)}</span></span></button><span class="dash-row-actions">${dashBtn("job-rerun","Re-run","play",` data-idx="${i}"`)}</span></li>`
}).join("")
return `<ul class="dash-list">${rows}</ul>`
}
function renderCommandList(items,listKey,emptyText,emptyAction){
if(!items||!items.length)return dashEmpty(emptyText,emptyAction||"")
const rows=items.map((c,i)=>{
const a=` data-list="${listKey}" data-idx="${i}"`
const meta=[c.runs?dashPlural(c.runs,"run"):"",c.relative||"",c.meta||""].filter(Boolean).join(" - ")
return `<li class="dash-row"><button type="button" class="dash-row-main" data-act="cmd-open"${a} title="${dashEsc(c.resolved||c.command)}"><span class="dash-row-text"><span class="dash-row-title">${dashEsc(c.title)}</span><span class="dash-row-meta mono">${dashEsc(c.resolved||c.command)}</span>${meta?`<span class="dash-row-meta">${dashEsc(meta)}</span>`:""}</span></button><span class="dash-row-actions">${dashBtn("cmd-run","Run in terminal","play",a)}${dashBtn("cmd-insert","Type into terminal without running","command-line",a)}${dashBtn("cmd-copy","Copy (live target filled in)","copy",a)}</span></li>`
}).join("")
return `<ul class="dash-list">${rows}</ul>`
}
function renderNoteList(items,listKey,emptyText,emptyAction){
if(!items||!items.length)return dashEmpty(emptyText,emptyAction||"")
const rows=items.map((n,i)=>`<li class="dash-row"><button type="button" class="dash-row-main" data-act="note-open" data-id="${dashEsc(n.id)}"><span class="dash-row-icon">${dashIcon(n.pinned?"pin":"edit")}</span><span class="dash-row-text"><span class="dash-row-title">${dashEsc(n.name)}</span><span class="dash-row-meta">${dashEsc([n.group,n.relative].filter(Boolean).join(" - "))}</span></span></button></li>`).join("")
return `<ul class="dash-list">${rows}</ul>`
}
const DASH_ENGAGEMENT_COLORS={not_started:"var(--text-dim)",in_progress:"var(--accent-a)",compromised:"var(--danger)",reported:"var(--pal-success)"}
function renderBars(data){
data=data||{}
const total=Number(data.total)||0
if(!total)return dashEmpty("No targets yet - add one to track its engagement status.",dashBtn("quick","Add target","target",' data-q="target"',"dash-empty-btn"))
const statuses=data.statuses||[]
const segs=statuses.filter((s)=>s.count>0).map((s)=>`<span class="dash-bar-seg" style="flex-grow:${Number(s.count)};background:${DASH_ENGAGEMENT_COLORS[s.id]||"var(--accent-b)"}" title="${dashEsc(s.label+": "+s.count)}"></span>`).join("")
const chips=statuses.map((s)=>`<button type="button" class="dash-legend-chip" data-act="goto" data-page="targets"><span class="dash-legend-dot" style="background:${DASH_ENGAGEMENT_COLORS[s.id]||"var(--accent-b)"}"></span><span class="dash-legend-label">${dashEsc(s.label)}</span><span class="dash-legend-count">${dashEsc(s.count)}</span></button>`).join("")
const done=statuses.filter((s)=>s.id==="compromised"||s.id==="reported").reduce((a,s)=>a+s.count,0)
return `<div class="dash-bars"><div class="dash-bars-head"><span class="dash-kpi-value small">${total}</span><span class="dash-kpi-sub">${dashPlural(total,"target")} - ${Math.round(100*done/total)}% compromised or reported</span></div><div class="dash-bar" role="img" aria-label="${dashEsc(statuses.map((s)=>s.label+" "+s.count).join(", "))}">${segs}</div><div class="dash-legend">${chips}</div></div>`
}
function dashHeatLevel(v,max){
if(!v)return 0
if(max<=4)return Math.min(4,v)
return Math.min(4,1+Math.floor(3*v/max))
}
function renderHeat(data){
data=data||{}
const days=data.days||[]
if(!days.length)return dashEmpty("No activity data.")
const max=Number(data.max)||0
const cells=days.map((d)=>{
const tip=`${d.label}: ${dashPlural(d.notes,"note edit")}, ${dashPlural(d.commands,"command change/run")}, ${dashPlural(d.jobs,"job")}`
return `<span class="dash-heat-cell l${dashHeatLevel(d.total,max)}" title="${dashEsc(tip)}"></span>`
}).join("")
const summary=data.total?`${dashPlural(data.total,"action")} on ${dashPlural(data.active_days||0,"day")} in the last 30 days`:"No activity in the last 30 days"
return `<div class="dash-heat"><div class="dash-heat-strip" role="img" aria-label="${dashEsc(summary)}">${cells}</div><div class="dash-heat-foot"><span>${dashEsc(days[0].label)}</span><span class="dash-heat-summary">${dashEsc(summary)}</span><span class="dash-heat-scale">Less<span class="dash-heat-cell l0"></span><span class="dash-heat-cell l1"></span><span class="dash-heat-cell l2"></span><span class="dash-heat-cell l3"></span><span class="dash-heat-cell l4"></span>More</span></div></div>`
}
const DASH_QUICK_ACTIONS=[
{q:"note",label:"New note",icon:"edit",key:"Alt+N"},
{q:"command",label:"New command",icon:"commands",key:"Alt+C"},
{q:"target",label:"New target",icon:"target",key:"Alt+T"},
{q:"terminal",label:"Terminal",icon:"play",key:""},
{q:"playbooks",label:"Chains",icon:"chain",key:""},
{q:"search",label:"Search",icon:"search",key:""}
]
function renderActions(){
return `<div class="dash-actions">${DASH_QUICK_ACTIONS.map((a)=>`<button type="button" class="dash-action" data-act="quick" data-q="${a.q}"${a.key?` title="${a.label} (${a.key})"`:""}>${dashIcon(a.icon)}<span>${dashEsc(a.label)}</span></button>`).join("")}</div>`
}
function dashTargetOptions(targets,includeNone){
const opts=(targets||[]).map((t)=>`<option value="${dashEsc(t.id)}"${t.live?" selected":""}>${dashEsc(t.name)}</option>`).join("")
return (includeNone?`<option value=""${(targets||[]).some((t)=>t.live)?"":" selected"}>No live target</option>`:"")+opts
}
// Words must all appear in the name, the hint or the searchable values (case-insensitive); the live target sorts first.
function dashFilterTargets(list,q){
const words=String(q||"").toLowerCase().split(/\s+/).filter(Boolean)
const out=(list||[]).filter((t)=>{const hay=(String(t.name||"")+" "+String(t.hint||"")+" "+String(t.search||"")).toLowerCase();return words.every((w)=>hay.includes(w))})
return out.sort((a,b)=>(b.live?1:0)-(a.live?1:0)||String(a.name).localeCompare(String(b.name)))
}
function renderLive(data){
data=data||{}
const targets=data.targets||[]
if(!targets.length)return dashEmpty("No targets yet - add one and mark it live to fill {PLACEHOLDERS} automatically.",dashBtn("quick","Add target","target",' data-q="target"',"dash-empty-btn"))
// A searchable picker (opened by dashboard.js) instead of a plain select: find a target by name, IP or domain.
const cur=targets.find((x)=>x.live)
const sel=`<button type="button" class="dash-live-pick" data-act="live-pick" aria-haspopup="listbox" title="Switch live target - search by name, IP or domain">${dashIcon("target")}<span class="dash-live-pick-name">${dashEsc(cur?cur.name:"No live target")}</span>${dashIcon("arrow-down")}</button>`
const t=data.target
if(!t)return `<div class="dash-live">${sel}${dashEmpty("No live target - pick one above so commands get its values.")}</div>`
const vals=(t.values||[]).map((v,i)=>`<li class="dash-kv"><span class="dash-kv-key">{${dashEsc(v.key)}}</span><span class="dash-kv-val mono" title="${dashEsc(v.value)}">${dashEsc(v.value)}</span>${dashBtn("copy-value","Copy "+v.key,"copy",` data-idx="${i}"`)}</li>`).join("")
const more=t.value_count>(t.values||[]).length?`<li class="dash-kv-more">+${t.value_count-(t.values||[]).length} more</li>`:""
return `<div class="dash-live"><div class="dash-live-head">${sel}<span class="dash-pill eng-${dashEsc(t.engagement_status)}">${dashEsc(t.engagement_label)}</span></div>${vals?`<ul class="dash-kv-list">${vals}${more}</ul>`:dashEmpty("This target has no values yet.")}<div class="dash-card-foot"><span class="dash-foot-note">Profile: ${dashEsc(data.profile||"Default")}</span>${dashBtn("target-edit","Edit values","edit","","dash-link-btn")}</div></div>`
}
function renderChips(data){
data=data||{}
if(!data.used_keys)return dashEmpty("No commands use {PLACEHOLDERS} yet.")
const list=data.missing||[]
if(!list.length)return `<div class="dash-allgood">${dashIcon("star-filled")}<span>All ${dashPlural(data.used_keys,"element")} are filled for ${dashEsc(data.live_name)}.</span></div>`
const head=data.live?`<div class="dash-chips-head">${dashPlural(data.missing_count,"element")} used by your commands ${data.missing_count===1?"has":"have"} no value in <strong>${dashEsc(data.live_name)}</strong></div>`:`<div class="dash-chips-head">No live target - set one so these get filled in.</div>`
const chips=list.map((m)=>`<button type="button" class="dash-chip" data-act="missing-key" data-key="${dashEsc(m.key)}" title="${dashEsc(dashPlural(m.commands,"command")+(m.notes?", in "+dashPlural(m.notes,"note"):""))}"><span class="dash-chip-key">{${dashEsc(m.key)}}</span><span class="dash-chip-count">${dashEsc(m.commands)}</span></button>`).join("")
const more=data.missing_count>list.length?`<span class="dash-foot-note">+${data.missing_count-list.length} more</span>`:""
return `<div class="dash-chips-wrap">${head}<div class="dash-chips">${chips}</div><div class="dash-card-foot">${more}${dashBtn("goto",data.live?"Fill values":"Choose a live target",data.live?"edit":"target",data.live?' data-page="targets" data-edit="live"':' data-page="targets"',"dash-link-btn")}${dashBtn("goto","Set Elements","list",' data-page="targets" data-tab="elements"',"dash-link-btn")}</div></div>`
}
function renderStatus(data){
data=data||{}
const items=data.items||[]
if(!items.length)return dashEmpty("No status available.")
return `<ul class="dash-status">${items.map((it)=>`<li><button type="button" class="dash-status-row" data-act="settings-tab" data-tab="${dashEsc(it.tab)}"><span class="dash-status-dot ${dashEsc(it.level)}" aria-hidden="true"></span><span class="dash-status-label">${dashEsc(it.label)}</span><span class="dash-status-value">${dashEsc(it.value)}</span></button></li>`).join("")}</ul>`
}
const DASH_WHEEL_COLORS=["var(--accent-a)","var(--accent-b)","var(--pal-success)","var(--pal-ph-known)","var(--pal-ph-unknown)"]
function renderWheel(groups){
const entries=Object.entries(groups||{})
const total=entries.reduce((sum,entry)=>sum+entry[1],0)
const size=96
const radius=40
const circumference=2*Math.PI*radius
let offset=0
let circles=""
if(total===0){
circles=`<circle cx="${size/2}" cy="${size/2}" r="${radius}" fill="none" stroke="var(--glass-border)" stroke-width="12"></circle>`
}else{
entries.forEach((entry,i)=>{
const dash=entry[1]/total*circumference
circles+=`<circle cx="${size/2}" cy="${size/2}" r="${radius}" fill="none" stroke="${DASH_WHEEL_COLORS[i%DASH_WHEEL_COLORS.length]}" stroke-width="12" stroke-dasharray="${dash} ${circumference-dash}" stroke-dashoffset="${-offset}" transform="rotate(-90 ${size/2} ${size/2})"></circle>`
offset+=dash
})
}
const label=total===0?"No notes yet":total+" notes across "+entries.length+" group"+(entries.length===1?"":"s")
const legend=entries.slice(0,6).map((e,i)=>`<li><span class="dash-legend-dot" style="background:${DASH_WHEEL_COLORS[i%DASH_WHEEL_COLORS.length]}"></span><span class="dash-legend-label">${dashEsc(e[0])}</span><span class="dash-legend-count">${dashEsc(e[1])}</span></li>`).join("")
const more=entries.length>6?`<li class="dash-foot-note">+${entries.length-6} more</li>`:""
return `<div class="dash-wheel-wrap"><svg class="dash-wheel" viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" role="img" aria-label="${dashEsc(label)}">${circles}</svg>${legend?`<ul class="dash-wheel-legend">${legend}${more}</ul>`:""}</div><div class="dash-card-sub">${dashEsc(label)}</div>`
}
const DASH_REPORT_SEVS=[["critical","Critical"],["high","High"],["medium","Medium"],["low","Low"],["info","Info"]]
const DASH_REPORT_STATUSES=[["draft","Draft"],["review","In review"],["final","Final"]]
function dashDeadlineText(d){
const n=Number(d.days_left)||0
const when=d.overdue?(n<0?dashPlural(-n,"day")+" overdue":"overdue"):(n===0?"today":n===1?"tomorrow":"in "+n+" days")
return (d.label||"Deadline")+" - "+(d.title||"Untitled report")+" - "+(d.date||"")+" ("+when+")"
}
function renderReports(data){
data=data||{}
const total=Number(data.reports)||0
if(!total)return dashEmpty("No reports yet - turn your notes, findings and terminal evidence into one.",dashBtn("report-new","New report","report","","dash-empty-btn"))
const by=data.by_status||{}
const status=DASH_REPORT_STATUSES.map((s)=>`<span class="dash-rep-stat"><strong>${dashEsc(Number(by[s[0]])||0)}</strong> ${dashEsc(s[1])}</span>`).join("")
// Open findings per severity; a backend without that split falls back to all findings.
const sev=data.open_by_severity||data.findings||{}
const pills=DASH_REPORT_SEVS.filter((s)=>Number(sev[s[0]])>0).map((s)=>`<span class="dash-pill sev-${s[0]}" title="${dashEsc(s[1]+": "+sev[s[0]])}">${dashEsc(sev[s[0]])} ${dashEsc(s[1])}</span>`).join("")
const open=Number(data.open_findings)||0
const d=data.next_deadline
const deadline=d?`<button type="button" class="dash-rep-deadline${d.overdue?" overdue":""}" data-act="report-open" data-id="${dashEsc(d.report_id)}" title="Open this report">${dashIcon("clock")}<span>${dashEsc(dashDeadlineText(d))}</span></button>`:`<div class="dash-rep-deadline none">${dashIcon("clock")}<span>No upcoming deadline</span></div>`
const rows=(data.recent||[]).slice(0,3).map((r)=>`<li class="dash-row"><button type="button" class="dash-row-main" data-act="report-open" data-id="${dashEsc(r.id)}"><span class="dash-row-icon">${dashIcon("report")}</span><span class="dash-row-text"><span class="dash-row-title">${dashEsc(r.title||"Untitled report")}</span><span class="dash-row-meta">${dashEsc((DASH_REPORT_STATUSES.find((s)=>s[0]===r.status)||["","Draft"])[1])}</span></span></button></li>`).join("")
return `<div class="dash-reports"><div class="dash-bars-head"><span class="dash-kpi-value small">${total}</span><span class="dash-rep-stats">${status}</span></div><div class="dash-rep-sevs" aria-label="Open findings by severity"><span class="dash-foot-note">${dashEsc(dashPlural(open,"open finding"))}</span>${pills}</div>${deadline}<ul class="dash-list">${rows}</ul><div class="dash-card-foot">${dashBtn("goto","All reports","list",' data-page="reporting"',"dash-link-btn")}${dashBtn("report-new","New report","add","","dash-link-btn")}</div></div>`
}
function renderActivityList(items){
if(!items||!items.length)return '<div class="dash-card-sub">No recent activity</div>'
const rows=items.map((it)=>`<div class="dash-activity-row"><span class="dash-activity-label">${dashEsc(it.label||"")}</span><span class="dash-activity-time">${dashEsc(it.relative||"")}</span></div>`).join("")
return `<div class="dash-activity-list">${rows}</div>`
}
function renderCardBody(widget,stats,kind){
if(stats===null||stats===undefined)return '<div class="dash-loading" aria-busy="true"><span class="dash-skel"></span><span class="dash-skel short"></span></div>'
if(stats.__error)return `<div class="dash-error">${dashEsc("Couldn't load the dashboard.")}${dashBtn("retry","Retry","refresh","","dash-empty-btn")}</div>`
const dataKey=DASH_WIDGET_DATA[widget]
if(dataKey&&(stats.errors||[]).indexOf(dataKey)!==-1)return `<div class="dash-error">${dashEsc("Couldn't load this card.")}${dashBtn("retry","Retry","refresh","","dash-empty-btn")}</div>`
if(DASH_KPI[widget])return renderKpi(widget,stats)
if(widget==="notes_by_group")return renderWheel(stats.notes_by_group||{})
if(widget==="recent_activity")return stats.activity_feed?renderFeed(stats.activity_feed):renderActivityList(stats.recent_activity||[])
if(widget==="recent_jobs")return renderJobs(stats.recent_jobs)
if(widget==="engagements")return renderBars(stats.engagements)
if(widget==="activity_heat")return renderHeat(stats.activity_heat)
if(widget==="quick_actions")return renderActions()
if(widget==="live_target")return renderLive(stats.live_target)
if(widget==="missing_placeholders")return renderChips(stats.missing_placeholders)
if(widget==="security_health")return renderStatus(stats.security_health)
if(widget==="reports")return renderReports(stats.reports)
if(widget==="most_used_commands")return renderCommandList(stats.most_used_commands,"most_used_commands","No runs yet - commands you run from Commands show up here.",dashBtn("goto","Open Commands","commands",' data-page="commands"',"dash-empty-btn"))
if(widget==="favorite_snippets")return renderCommandList(stats.favorite_snippets,"favorite_snippets","No favourites yet - star commands on the Quick Run page.",dashBtn("goto","Open Quick Run","play",' data-page="snippets"',"dash-empty-btn"))
if(widget==="recent_notes")return renderNoteList(stats.recent_notes,"recent_notes","No notes yet.",dashBtn("quick","Add note","edit",' data-q="note"',"dash-empty-btn"))
if(widget==="pinned_notes")return renderNoteList(stats.pinned_notes,"pinned_notes","No pinned notes - pin one from the Notes list.",dashBtn("goto","Open Notes","edit",' data-page="notes"',"dash-empty-btn"))
const info=cardStatInfo(widget,stats)
return `<div class="dash-card-value">${dashEsc(info.value)}</div><div class="dash-card-sub">${dashEsc(info.sub)}</div>`
}
function dashCardBadge(widget,stats){
if(!stats||stats.__error)return ""
if(widget==="recent_jobs"&&stats.recent_jobs&&stats.recent_jobs.running)return `<span class="dash-pill run">${dashEsc(stats.recent_jobs.running)} running</span>`
if(widget==="missing_placeholders"&&stats.missing_placeholders&&stats.missing_placeholders.missing_count)return `<span class="dash-pill warn">${dashEsc(stats.missing_placeholders.missing_count)}</span>`
if(widget==="reports"&&stats.reports&&stats.reports.overdue)return `<span class="dash-pill bad">${dashEsc(stats.reports.overdue)} overdue</span>`
if(widget==="security_health"&&stats.security_health&&stats.security_health.overall&&stats.security_health.overall!=="ok")return `<span class="dash-status-dot ${dashEsc(stats.security_health.overall)}" aria-label="Needs attention"></span>`
return ""
}
function renderCardHtml(card,ctx){
const meta=widgetMeta(ctx.catalog,card.widget)
const edit=ctx.editMode?`<span class="dash-card-handle" aria-hidden="true">${dashIcon("grip")}</span><button type="button" class="dash-card-menu" data-id="${dashEsc(card.id)}" aria-label="Card options: ${dashEsc(meta.label)}">${dashIcon("dots-vertical")}</button>`:dashCardBadge(card.widget,ctx.stats)
return `<div class="dash-card-head"><i class="icon icon-${dashEsc(meta.icon)} dash-card-icon" aria-hidden="true"></i><h3 class="dash-card-label">${dashEsc(meta.label)}</h3>${edit}</div><div class="dash-card-body" data-kind="${dashEsc(meta.kind||"stat")}"${ctx.editMode?" inert":""}>${renderCardBody(card.widget,ctx.stats,meta.kind)}</div>`
}
function renderCard(card,ctx){
const meta=widgetMeta(ctx.catalog,card.widget)
const el=document.createElement("section")
el.className="dash-card glass-panel dash-kind-"+(meta.kind||"stat")+(ctx.editMode?" editing":"")
el.dataset.id=card.id
el.dataset.widget=card.widget
el.dataset.size=card.size
el.setAttribute("aria-label",meta.label)
el.draggable=!!ctx.editMode
if(ctx.editMode)el.tabIndex=0
el.innerHTML=renderCardHtml(card,ctx)
return el
}
