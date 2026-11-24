// Pure helpers of the Reporting page (UI/js/pages/reporting.js). Run: node tests/js/reporting_page.js
const path=require("path")
const ROOT=path.resolve(__dirname,"..","..")
const api=require(path.join(ROOT,"UI","js","pages","reporting.js"))
let passed=0,failed=0
function check(name,cond,detail){if(cond){passed++;return}failed++;console.log("  FAIL  "+name+(detail?"  ->  "+detail:""))}
function eq(name,a,b){check(name,JSON.stringify(a)===JSON.stringify(b),JSON.stringify(a)+" != "+JSON.stringify(b))}

// escaping
eq("escape html and both quotes",api.rpgEsc(`<img src=x onerror="a('b')">&`),"&lt;img src=x onerror=&quot;a(&#39;b&#39;)&quot;&gt;&amp;")
eq("escape null",api.rpgEsc(null),"")
eq("escape number",api.rpgEsc(0),"0")

// section kinds
eq("every contract kind is offered",api.RPG_SECTION_KINDS.map((k)=>k.kind).sort(),["appendix_commands","appendix_evidence","appendix_timeline","appendix_tools","attack_narrative","conclusion","custom","document_control","executive_summary","findings","findings_summary","methodology","project_timeline","remediation_roadmap","risk_matrix","scope"])
check("every kind has an icon and a description for the picker",api.RPG_SECTION_KINDS.every((k)=>api.RPG_KIND_META[k.kind]&&api.RPG_KIND_META[k.kind].icon&&api.RPG_KIND_META[k.kind].desc.length>20))
check("quick-add kinds exist",api.RPG_QUICK_KINDS.length===6&&api.RPG_QUICK_KINDS.every((k)=>api.RPG_SECTION_KINDS.some((x)=>x.kind===k)))
eq("new kinds: auto flags",["risk_matrix","attack_narrative","project_timeline"].map((k)=>api.rpgKindInfo(k).auto),[true,false,true])
check("findings is auto",api.rpgKindInfo("findings").auto===true)
check("executive summary is not auto",api.rpgKindInfo("executive_summary").auto===false)
eq("unknown kind falls back to a readable label",api.rpgKindInfo("my_thing").label,"my thing")
eq("status label",[api.rpgStatusLabel("review"),api.rpgStatusLabel("bogus")],["In review","Draft"])

// time
const now=Date.parse("2026-11-23T12:00:00Z")
eq("just now",api.rpgRelTime("2026-11-23T11:59:30Z",now),"Just now")
eq("minutes",api.rpgRelTime("2026-11-23T11:15:00Z",now),"45m ago")
eq("hours, no timezone suffix is read as UTC",api.rpgRelTime("2026-11-23 09:00:00",now),"3h ago")
eq("days",api.rpgRelTime("2026-11-20T12:00:00+00:00",now),"3d ago")
eq("old dates print the day",api.rpgRelTime("2026-01-05T08:00:00Z",now),"2026-01-05")
eq("bad date is empty",api.rpgRelTime("nonsense",now),"")
eq("future clamps to now",api.rpgRelTime("2026-11-23T13:00:00Z",now),"Just now")

// severity counting
const fs=[{severity:"critical",status:"open"},{severity:"high",status:"fixed"},{severity:"high",status:"retest"},{severity:"weird",status:"??"},{severity:"info",status:"accepted"}]
const st=api.rpgCountSeverities(fs)
eq("severity counts",st.counts,{critical:1,high:2,medium:0,low:0,info:2})
eq("totals",[st.total,st.open],[5,2])
eq("by status",st.by_status,{open:2,retest:1,fixed:1,accepted:1})
eq("empty findings",api.rpgCountSeverities(null).total,0)

// list filter + sort
const list=[
{id:1,title:"Acme web test",client:"Acme",profile_name:"acme-prod",status:"draft",updated_at:"2026-11-20T10:00:00Z",created_at:"2026-11-01T10:00:00Z",counts:{critical:0,high:2,medium:1,low:0,info:0}},
{id:2,title:"Zeta internal",client:"Zeta Corp",profile_name:"",status:"final",updated_at:"2026-11-22T10:00:00Z",created_at:"2026-10-01T10:00:00Z",counts:{critical:1,high:0,medium:0,low:0,info:0}},
{id:3,title:"beta retest",client:"",profile_name:"lab",status:"review",updated_at:"2026-11-21T10:00:00Z",created_at:"2026-11-15T10:00:00Z",counts:{critical:0,high:2,medium:4,low:0,info:0}}
]
const ids=(rows)=>rows.map((r)=>r.id)
eq("default sort: recently updated",ids(api.rpgFilterReports(list,"","","updated")),[2,3,1])
eq("sort by created",ids(api.rpgFilterReports(list,"","","created")),[3,1,2])
eq("sort by title is case-insensitive",ids(api.rpgFilterReports(list,"","","title")),[1,3,2])
eq("sort by client",ids(api.rpgFilterReports(list,"","","client")),[3,1,2])
eq("sort by risk: critical first, then more highs/mediums",ids(api.rpgFilterReports(list,"","","risk")),[2,3,1])
eq("status filter",ids(api.rpgFilterReports(list,"","final","updated")),[2])
eq("search title",ids(api.rpgFilterReports(list,"RETEST","","updated")),[3])
eq("search client and profile, all words",ids(api.rpgFilterReports(list,"acme prod","","updated")),[1])
eq("search by status label",ids(api.rpgFilterReports(list,"in review","","updated")),[3])
eq("search no match",ids(api.rpgFilterReports(list,"nope","","updated")),[])
eq("filter does not mutate the input",ids(list),[1,2,3])
eq("filter survives null list",api.rpgFilterReports(null,"x","","updated"),[])

// patch merging (autosave queue)
eq("meta merges key by key",api.rpgMergePatch({title:"a",meta:{client:"x",version:"1"}},{meta:{client:"y"},status:"final"}),{title:"a",meta:{client:"y",version:"1"},status:"final"})
eq("merge onto nothing",api.rpgMergePatch(null,{branding:{accent:"#fff"}}),{branding:{accent:"#fff"}})
const base={meta:{client:"x"}};api.rpgMergePatch(base,{meta:{client:"y"}})
eq("merge does not mutate the base",base,{meta:{client:"x"}})
eq("arrays inside meta are replaced whole",api.rpgMergePatch({meta:{scope_in:["a","b"]}},{meta:{scope_in:["c"]}}),{meta:{scope_in:["c"]}})
eq("failed patch goes back UNDER newer edits",api.rpgMergePatch({title:"old",meta:{client:"old",version:"1"}},{meta:{client:"new"}}),{title:"old",meta:{client:"new",version:"1"}})

// colours
eq("hex normalise",[api.rpgNormHex("#ABC"),api.rpgNormHex("1d4ed8"),api.rpgNormHex(" #1D4ED8 "),api.rpgNormHex("#12345"),api.rpgNormHex("red"),api.rpgNormHex("#12345g")],["#aabbcc","#1d4ed8","#1d4ed8","","",""])
eq("hex rejects injection",api.rpgNormHex('#fff;background:url(x)'),"")
eq("contrast text",[api.rpgContrastText("#ffffff"),api.rpgContrastText("#0f172a"),api.rpgContrastText("#f59e0b"),api.rpgContrastText("nope")],["#111827","#ffffff","#111827","#ffffff"])

// reordering
eq("move down",api.rpgMoveItem([1,2,3,4],0,2),[2,3,1,4])
eq("move up",api.rpgMoveItem([1,2,3,4],3,0),[4,1,2,3])
eq("move clamps",api.rpgMoveItem([1,2,3],1,99),[1,3,2])
eq("move bad index is a copy",api.rpgMoveItem([1,2,3],7,0),[1,2,3])
const arr=[1,2,3];api.rpgMoveItem(arr,0,2)
eq("move does not mutate",arr,[1,2,3])
const mids=[10,30,50,70]
eq("drop slot above first",api.rpgDropIndex(mids,5),0)
eq("drop slot between",api.rpgDropIndex(mids,40),2)
eq("drop slot below last",api.rpgDropIndex(mids,400),4)
eq("slot to index: dragging row 0 below row 2",api.rpgSlotToIndex(0,3),2)
eq("slot to index: dragging row 3 to the top",api.rpgSlotToIndex(3,0),0)
eq("slot to index: dropping on either side of itself is no move",[api.rpgSlotToIndex(2,2),api.rpgSlotToIndex(2,3)],[2,2])
eq("drag row 0 to the very end",api.rpgMoveItem(["a","b","c"],0,api.rpgSlotToIndex(0,3)),["b","c","a"])
eq("drag last row to slot 1",api.rpgMoveItem(["a","b","c"],2,api.rpgSlotToIndex(2,1)),["a","c","b"])

// dates and lists
eq("valid dates",[api.rpgValidDate("2026-11-23"),api.rpgValidDate("2026-02-30"),api.rpgValidDate("23/11/2026"),api.rpgValidDate(""),api.rpgValidDate("2024-02-29")],[true,false,false,false,true])
eq("clean list trims, drops empties and duplicates",api.rpgCleanList([" a ","","b","a",null,"  "]),["a","b"])
eq("split pasted lines",api.rpgSplitLines("10.0.0.1\r\n10.0.0.2\n\n app.example.com ; 10.0.0.1"),["10.0.0.1","10.0.0.2","app.example.com"])
eq("clean testers",api.rpgCleanTesters([{name:" Ann ",role:"Lead",email:""},{name:"",role:"",email:" "},{email:"b@x.io"}]),[{name:"Ann",role:"Lead",email:""},{name:"",role:"",email:"b@x.io"}])
eq("target scope line with values",api.rpgTargetScopeLine({name:"dc01",values:{IP:"10.0.0.5",URL:""}}),"dc01: 10.0.0.5")
eq("target scope line: value equals name",api.rpgTargetScopeLine({name:"10.0.0.5",values:{IP:"10.0.0.5"}}),"10.0.0.5")
eq("target scope line: no values",api.rpgTargetScopeLine({name:"web",values:{}}),"web")
eq("scope values: addresses only",["10.0.0.5","10.0.0.0/24","10.0.0.1-50","https://x.io/a","app.example.com","*.example.com","fe80::1","2001:db8::/32","443","j.doe","/usr/share/wordlists/x.txt","admin","P@ss w0rd","",null].map(api.rpgIsScopeValue),[true,true,true,true,true,true,true,true,false,true,false,false,false,false,false])
eq("target scope line drops ports, paths and names",api.rpgTargetScopeLine({name:"web01",values:{WORDLIST:"/usr/share/x.txt",PORT:"443",URL:"https://portal.example",IP:"10.10.20.15",USER:"admin"}}),"web01: https://portal.example, 10.10.20.15")
eq("target scope line drops values stored under a secret-looking key",api.rpgTargetScopeLine({name:"dc",values:{Password:"corp.example",API_KEY:"10.9.8.7",Username:"j.doe",Domain:"globex.local"}}),"dc: globex.local")
eq("target scope line: several values",api.rpgTargetScopeLine({name:"web",values:{IP:"10.0.0.9",URL:"https://x.io"}}),"web: 10.0.0.9, https://x.io")

// html helpers
eq("html to text",api.rpgHtmlToText("<p>Hello <strong>world</strong></p><p>a &amp; b &lt;c&gt;</p>"),"Hello world a & b <c>")
eq("excerpt truncates",api.rpgExcerpt("<p>"+"x".repeat(50)+"</p>",20).length,20)
eq("excerpt short text untouched",api.rpgExcerpt("<p>short</p>",20),"short")
const rep={sections:[{content:'<figure class="rpt-ev" data-evidence="E1"><pre>x</pre></figure><p>t</p>'}],findings:[{steps:'<figure class="rpt-ev" data-evidence="E2"></figure>',description:'<figure data-evidence="E1"></figure>',evidence:[{evidence_uid:"E3",asset_uid:""},{evidence_uid:"",asset_uid:"A1"},{evidence_uid:"E2"}]}]}
eq("evidence used by a report, unique",api.rpgEvidenceUids(rep).sort(),["E1","E2","E3","asset:A1"])
eq("evidence of an empty report",api.rpgEvidenceUids({}),[])
eq("roadmap order: severity, then cvss, then position",api.rpgSortedForRoadmap([{id:1,severity:"low",cvss_score:3,position:0},{id:2,severity:"critical",cvss_score:9.1,position:1},{id:3,severity:"critical",cvss_score:9.8,position:2},{id:4,severity:"medium",cvss_score:null,position:3},{id:5,severity:"medium",cvss_score:null,position:1}]).map((f)=>f.id),[3,2,5,4,1])

// save indicator
eq("save state: error wins",api.rpgSaveStateInfo({errors:true,saving:true,pending:true}).cls,"error")
eq("save state: saving",api.rpgSaveStateInfo({errors:false,saving:true,pending:true}).cls,"saving")
eq("save state: unsaved",api.rpgSaveStateInfo({errors:false,saving:false,pending:true}).label,"Unsaved changes")
eq("save state: saved",api.rpgSaveStateInfo({errors:false,saving:false,pending:false}).label,"Saved")

// preview document hardening
const doc=api.rpgPreviewDoc("<!doctype html><html><head><title>x</title></head><body><a href='https://x.io'>l</a></body></html>")
check("preview: CSP is the first thing in head",/<head><meta http-equiv="Content-Security-Policy" content="default-src 'none';/.test(doc),doc)
check("preview: links target a blocked popup",doc.includes('<base target="_blank">'))
check("preview: no script source allowed",!/script-src/.test(doc)&&doc.includes("default-src 'none'"))
check("preview: headless html still gets the guard",api.rpgPreviewDoc("<p>x</p>").startsWith("<meta http-equiv"))
eq("preview: null input",typeof api.rpgPreviewDoc(null),"string")

// ---- schedule, timeline, undo history (scoped: the names above are taken)
{
const T="2026-11-23"
const ids=(()=>{let n=0;return ()=>"id"+(++n)})()
const norm=api.rpgNormSchedule({milestones:[{id:"a1",key:"handover",date:"2026-11-30",time:"17:00",done:1,remind:[{days_before:1},{days_before:7},{days_before:1},{days_before:-1},3,"x"],notes:"n"},{id:"a1",key:"bogus",label:"  ",date:"2026-02-30",time:"9:5"},null,"junk"]},ids)
eq("schedule: complete milestone",norm.milestones[0],{id:"a1",key:"handover",label:"Hand-over",date:"2026-11-30",time:"17:00",done:true,remind:[{days_before:7},{days_before:3},{days_before:1}],notes:"n"})
eq("schedule: bad key, duplicate id, bad date and time",norm.milestones[1],{id:"id1",key:"custom",label:"Milestone",date:"",time:"",done:false,remind:[],notes:""})
eq("schedule: garbage in, empty out",[api.rpgNormSchedule(null),api.rpgNormSchedule("x"),api.rpgNormSchedule({milestones:5})],[{milestones:[]},{milestones:[]},{milestones:[]}])
eq("schedule: at most 60 milestones",api.rpgNormSchedule(Array.from({length:90},()=>({key:"custom"}))).milestones.length,60)
eq("milestone labels match the server",api.RPG_MS_KEYS.map((k)=>k.key+"="+k.label).join(","),"kickoff=Kick-off,testing_start=Testing start,testing_end=Testing end,draft_due=Draft report,review=QA / review,handover=Hand-over,retest_start=Retest start,retest_end=Retest end,custom=Milestone")
eq("day numbers round-trip",[api.rpgDayStr(api.rpgDayNum("2026-11-23")),api.rpgDayNum("2026-11-24")-api.rpgDayNum("2026-11-23"),isNaN(api.rpgDayNum("nope"))],["2026-11-23",1,true])
eq("today is the local calendar day",api.rpgTodayStr(new Date(2026,0,5,23,59)),"2026-01-05")
eq("valid times",["00:00","23:59","24:00","9:30","12:60",""].map(api.rpgValidTime),[true,true,false,false,false,false])
eq("milestone states",[{date:"2026-11-20",done:true},{date:"2026-11-20"},{date:T},{date:"2026-11-24"},{date:""}].map((m)=>api.rpgMsState(m,T)),["done","overdue","today","upcoming","unset"])
eq("sorted by date then time, undated last",api.rpgMsSorted([{id:1,date:""},{id:2,date:"2026-12-01"},{id:3,date:"2026-11-01",time:"15:00"},{id:4,date:"2026-11-01",time:"09:00"},{id:5,date:"2026-11-01"}]).map((m)=>m.id),[4,3,5,2,1])

// next deadline
const repS=(status,ms)=>({status,meta:{schedule:{milestones:ms}}})
const nd=api.rpgNextDeadline(repS("draft",[{id:"k",key:"kickoff",date:"2026-11-01",done:true},{id:"h",key:"handover",date:"2026-11-26",time:"17:00"},{id:"d",key:"draft_due",date:"2026-11-24"},{id:"r",key:"review"}]),T)
eq("next deadline: earliest open milestone",[nd.milestone,nd.label,nd.date,nd.days_left,nd.overdue],["d","Draft report","2026-11-24",1,false])
eq("next deadline: overdue comes first",api.rpgNextDeadline(repS("review",[{key:"handover",date:"2026-11-26"},{key:"draft_due",date:"2026-11-21"}]),T).days_left,-2)
eq("next deadline: none for a final report, an empty schedule or all done",[api.rpgNextDeadline(repS("final",[{key:"handover",date:"2026-11-26"}]),T),api.rpgNextDeadline({status:"draft",meta:{}},T),api.rpgNextDeadline(repS("draft",[{key:"handover",date:"2026-11-26",done:true}]),T),api.rpgNextDeadline(null,T)],[null,null,null,null])

// chip and reminder text
eq("deadline chip text",[3,1,0,-1,-2].map((n)=>api.rpgDeadlineText("Hand-over",n)),["Hand-over in 3 days","Hand-over tomorrow","Hand-over today","Overdue by 1 day","Overdue by 2 days"])
eq("deadline chip, short form",[12,1,0,-1,-9].map(api.rpgDeadlineShort),["12d","1d","today","1d late","9d late"])
eq("days text",[0,1,-1,5,-5].map(api.rpgDaysText),["today","tomorrow","yesterday","in 5 days","5 days ago"])
eq("reminder message",api.rpgReminderMessage("ACME External Pentest","Hand-over","2026-11-30",1),"Hand-over for 'ACME External Pentest' is due tomorrow (2026-11-30)")
eq("reminder message: today with a time",api.rpgReminderMessage("X","Hand-over","2026-11-30",0,"17:00"),"Hand-over for 'X' is due today (2026-11-30 17:00)")
eq("reminder message: in days",api.rpgReminderMessage("X","Draft report","2026-11-30",3),"Draft report for 'X' is due in 3 days (2026-11-30)")
eq("reminder message: overdue",[api.rpgReminderMessage("X","Draft report","2026-11-30",-1),api.rpgReminderMessage("","","2026-11-30",-4)],["Draft report for 'X' was due yesterday (2026-11-30)","Milestone for 'Untitled report' was due 4 days ago (2026-11-30)"])
eq("reminder chips",[0,1,3,7,14,10].map(api.rpgRemindLabel),["On the day","1 day before","3 days before","1 week before","2 weeks before","10 days before"])

// timeline layout
const plan=[{id:"k",key:"kickoff",label:"Kick-off",date:"2026-11-03",done:true},{id:"ts",key:"testing_start",label:"Testing start",date:"2026-11-05",done:true},{id:"te",key:"testing_end",label:"Testing end",date:"2026-11-17",done:true},{id:"d",key:"draft_due",label:"Draft report",date:"2026-11-21"},{id:"r",key:"review",label:"QA / review",date:T},{id:"h",key:"handover",label:"Hand-over",date:"2026-11-24",time:"17:00"},{id:"rs",key:"retest_start",label:"Retest start",date:"2026-12-13"},{id:"re",key:"retest_end",label:"Retest end",date:"2026-12-17"},{id:"x",key:"custom",label:"No date",date:""}]
const lay=api.rpgTimelineLayout(plan,T,{minGap:10})
check("timeline: not empty, undated left out",lay.empty===false&&lay.items.length===8)
eq("timeline: padded range",[lay.start,lay.end,lay.days],["2026-10-31","2026-12-20",50])
check("timeline: every x is inside the track",lay.items.every((i)=>i.pct>0&&i.pct<100)&&lay.today.pct>0&&lay.today.pct<100)
check("timeline: x grows with the date",lay.items.every((it,i)=>i===0||it.pct>=lay.items[i-1].pct))
eq("timeline: kick-off position",lay.items[0].pct,6)
eq("timeline: today marker",lay.today,{pct:46,date:T})
eq("timeline: states",lay.items.map((i)=>i.state),["done","done","done","overdue","today","upcoming","upcoming","upcoming"])
eq("timeline: days left",lay.items.map((i)=>i.days_left),[-20,-18,-6,-2,0,1,20,24])
eq("timeline: close milestones go to further lanes",lay.items.map((i)=>i.lane),[0,1,0,1,0,2,0,1])
eq("timeline: lane count",lay.lanes,3)
check("timeline: no two labels in one lane are closer than the gap",lay.items.every((a,i)=>lay.items.every((b,j)=>j<=i||a.lane!==b.lane||Math.abs(a.pct-b.pct)>=10)))
eq("timeline: phases",lay.phases,[{key:"testing",label:"Testing",from:"2026-11-05",to:"2026-11-17",left:10,width:24},{key:"retest",label:"Retest",from:"2026-12-13",to:"2026-12-17",left:86,width:8}])
check("timeline: ticks are inside the range, in order, and few",lay.ticks.length>=2&&lay.ticks.length<=8&&lay.ticks.every((t,i)=>t.pct>=0&&t.pct<=100&&(i===0||t.pct>lay.ticks[i-1].pct)))
eq("timeline: weekly ticks fall on Mondays",lay.ticks.map((t)=>new Date(t.date+"T00:00:00Z").getUTCDay()),lay.ticks.map(()=>1))
eq("timeline: tick labels (two-week steps for a 50 day range)",lay.ticks.map((t)=>t.label),["9 Nov","23 Nov","7 Dec"])
eq("timeline: a wide gap needs more lanes",api.rpgTimelineLayout(plan,T,{minGap:40}).lanes>lay.lanes,true)
eq("timeline: fewer ticks when there is little room",api.rpgTimelineLayout(plan,T,{maxTicks:3}).ticks.length<=3,true)
eq("timeline: nothing dated",api.rpgTimelineLayout([{id:"a",date:""}],T),{empty:true,items:[],phases:[],ticks:[],lanes:0,today:null})
const one=api.rpgTimelineLayout([{id:"a",key:"handover",label:"Hand-over",date:T}],T)
eq("timeline: a single milestone today is centred",[one.items[0].pct,one.today.pct,one.days,one.phases.length],[50,50,2,0])
eq("timeline: no phase without both ends, or with the end first",[api.rpgTimelineLayout([{id:"a",key:"testing_start",date:"2026-11-05"}],T).phases.length,api.rpgTimelineLayout([{id:"a",key:"testing_start",date:"2026-11-09"},{id:"b",key:"testing_end",date:"2026-11-05"}],T).phases.length],[0,0])
eq("timeline: long ranges label ticks by month",/^[A-Z][a-z]{2} \d{4}$/.test(api.rpgTimelineLayout([{id:"a",date:"2025-01-10"},{id:"b",date:"2028-01-10"}],T).ticks[0].label),true)

// fill from engagement dates
const idg=(()=>{let n=0;return ()=>"n"+(++n)})()
const filled=api.rpgScheduleFromDates({milestones:[]},{start_date:"2026-11-05",end_date:"2026-11-17",report_date:"2026-11-28"},idg,T).milestones
eq("fill: an empty schedule gets the usual milestones",filled.map((m)=>[m.key,m.date,m.done]),[["kickoff","2026-11-05",true],["testing_start","2026-11-05",true],["testing_end","2026-11-17",true],["draft_due","",false],["review","",false],["handover","2026-11-28",false]])
eq("fill: hand-over and draft get reminders",[filled[5].remind,filled[3].remind],[[{days_before:3},{days_before:1}],[{days_before:1}]])
const refill=api.rpgScheduleFromDates({milestones:[{id:"h",key:"handover",date:"2026-12-02"},{id:"s",key:"testing_start",date:"2026-01-01",notes:"keep"}]},{start_date:"2026-11-05",end_date:"2026-11-19",report_date:"2026-11-28"},idg,T).milestones
eq("fill: existing milestones stay, the testing window follows the dates",refill.map((m)=>[m.id,m.key,m.date]),[["s","testing_start","2026-11-05"],["n7","testing_end","2026-11-19"],["h","handover","2026-12-02"]])
eq("fill: notes survive",refill[0].notes,"keep")
eq("fill: no dates and an existing schedule changes nothing",api.rpgScheduleFromDates({milestones:[{id:"h",key:"handover",label:"Hand-over",date:"2026-12-02",time:"",done:false,remind:[],notes:""}]},{},idg,T).milestones,[{id:"h",key:"handover",label:"Hand-over",date:"2026-12-02",time:"",done:false,remind:[],notes:""}])
eq("fill: future testing dates are not marked done",api.rpgScheduleFromDates({milestones:[]},{start_date:"2026-12-01",end_date:"2026-12-05"},idg,T).milestones.filter((m)=>m.done).length,0)

// ---- undo / redo history
const H=api.rpgHistNew
let h=H()
eq("history starts empty",[h.undo.length,h.redo.length,h.limit],[0,0,100])
eq("tooltips when empty",[api.rpgHistTip(h,"undo"),api.rpgHistTip(h,"redo")],["Nothing to undo (Ctrl+Z)","Nothing to redo (Ctrl+Shift+Z)"])
api.rpgHistPush(h,{type:"sec-del",label:"delete section 'Scope'",sec:{id:5},index:1},1000)
eq("tooltip names the step",api.rpgHistTip(h,"undo"),"Undo: delete section 'Scope' (Ctrl+Z)")
api.rpgHistPush(h,{type:"report",path:"title",key:"report:title",label:"rename the report",before:"A",after:"Ab"},2000)
api.rpgHistPush(h,{type:"report",path:"title",key:"report:title",label:"rename the report",before:"Ab",after:"Abc"},2400)
api.rpgHistPush(h,{type:"report",path:"title",key:"report:title",label:"rename the report",before:"Abc",after:"Abcd"},3500)
eq("rapid typing in one field is one step",[h.undo.length,h.undo[1].before,h.undo[1].after],[2,"A","Abcd"])
api.rpgHistPush(h,{type:"report",path:"title",key:"report:title",label:"rename the report",before:"Abcd",after:"Abcde"},3500+api.RPG_COALESCE_MS+1)
eq("a pause starts a new step",[h.undo.length,h.undo[2].before,h.undo[2].after],[3,"Abcd","Abcde"])
api.rpgHistPush(h,{type:"report",path:"meta.client",key:"report:meta.client",label:"edit client",before:"",after:"X"},5000)
eq("another field never merges",h.undo.length,4)
api.rpgHistSeal(h)
api.rpgHistPush(h,{type:"report",path:"meta.client",key:"report:meta.client",label:"edit client",before:"X",after:"Xy"},5100)
eq("a sealed step (field lost focus) is not extended",h.undo.length,5)
api.rpgHistPush(h,{type:"sec-order",label:"reorder the sections",before:[1,2],after:[2,1]},5200)
api.rpgHistPush(h,{type:"sec-order",label:"reorder the sections",before:[2,1],after:[1,2]},5210)
eq("steps without a key never merge",h.undo.length,7)
eq("a change to the same value is not a step",[api.rpgHistPush(h,{type:"report",path:"status",key:null,before:"draft",after:"draft"},5300),h.undo.length],[null,7])
// typing something and deleting it again within the window leaves no step
h=H()
api.rpgHistPush(h,{type:"report",path:"t",key:"k",before:"A",after:"Ab"},10)
api.rpgHistPush(h,{type:"report",path:"t",key:"k",before:"Ab",after:"A"},20)
eq("a merged step that ends where it began disappears",h.undo.length,0)
// undo / redo
h=H()
;["one","two","three"].forEach((l,i)=>api.rpgHistPush(h,{type:"x",label:l},i*5000))
eq("peek",[api.rpgHistPeek(h,"undo").label,api.rpgHistPeek(h,"redo")],["three",null])
const u1=api.rpgHistTake(h,"undo")
eq("undo takes the newest step",[u1.label,h.undo.length,h.redo.length,api.rpgHistTip(h,"redo")],["three",2,1,"Redo: three (Ctrl+Shift+Z)"])
api.rpgHistTake(h,"undo")
eq("redo brings back in reverse order",[api.rpgHistTake(h,"redo").label,api.rpgHistTake(h,"redo").label,api.rpgHistTake(h,"redo")],["two","three",null])
eq("after redo everything is undoable again",[h.undo.map((o)=>o.label),h.redo.length],[["one","two","three"],0])
api.rpgHistTake(h,"undo")
api.rpgHistPush(h,{type:"x",label:"new"},99999)
eq("a new change drops the redo steps",[h.undo.map((o)=>o.label),h.redo.length],[["one","two","new"],0])
eq("nothing to take",api.rpgHistTake(H(),"undo"),null)
// a step taken back is sealed: typing after an undo is its own step
h=H()
api.rpgHistPush(h,{type:"report",key:"k",before:"A",after:"B"},100)
api.rpgHistTake(h,"undo");api.rpgHistTake(h,"redo")
api.rpgHistPush(h,{type:"report",key:"k",before:"B",after:"C"},150)
eq("no merge into a step that was undone and redone",h.undo.length,2)
// failed apply
h=H()
api.rpgHistPush(h,{type:"x",label:"a"},1);api.rpgHistPush(h,{type:"x",label:"b"},2)
const failed1=api.rpgHistTake(h,"undo")
api.rpgHistGiveBack(h,"undo",failed1)
eq("a step that could not be applied goes back where it was",[h.undo.map((o)=>o.label),h.redo.length],[["a","b"],0])
const failed2=api.rpgHistTake(h,"undo");api.rpgHistGiveBack(h,"redo",failed2)
eq("give back in the wrong direction is harmless",[h.undo.length,h.redo.length],[1,1])
// bound
h=H(5)
for(let i=0;i<12;i++)api.rpgHistPush(h,{type:"x",label:"s"+i},i*10000)
eq("history is bounded, oldest steps go first",h.undo.map((o)=>o.label),["s7","s8","s9","s10","s11"])
eq("default bound",api.RPG_UNDO_LIMIT,100)
h=H()
for(let i=0;i<130;i++)api.rpgHistPush(h,{type:"x",label:"s"+i},i*10000)
eq("100 steps per open report",[h.undo.length,h.undo[0].label],[100,"s30"])
// native (field) undo: the recorded steps follow the text back
h=H()
api.rpgHistPush(h,{type:"x",label:"earlier"},1)
api.rpgHistPush(h,{type:"sec-edit",key:"sec:1:content",before:"A",after:"AB"},10000)
api.rpgHistPush(h,{type:"sec-edit",key:"sec:1:content",before:"AB",after:"ABC"},20000)
api.rpgHistPush(h,{type:"sec-edit",key:"sec:1:content",before:"ABC",after:"AB"},20100,{merge:true})
eq("field undo back to an earlier state removes the step above it",h.undo.map((o)=>o.after||o.label),["earlier","AB"])
api.rpgHistPush(h,{type:"sec-edit",key:"sec:1:content",before:"AB",after:"A"},20200,{merge:true})
eq("field undo back to the start removes every step of that field",h.undo.map((o)=>o.label),["earlier"])
h=H()
api.rpgHistPush(h,{type:"sec-edit",key:"sec:1:content",before:"A",after:"AB"},10000)
api.rpgHistPush(h,{type:"sec-edit",key:"sec:1:content",before:"AB",after:"ABC"},20000)
api.rpgHistTake(h,"undo")
api.rpgHistPush(h,{type:"sec-edit",key:"sec:1:content",before:"AB",after:"A"},20100,{merge:true})
eq("field undo keeps the redo steps",[h.undo.length,h.redo.length],[0,1])
h=H()
api.rpgHistPush(h,{type:"sec-edit",key:"sec:1:content",before:"A",after:"AB"},10000)
api.rpgHistPush(h,{type:"sec-edit",key:"sec:1:content",before:"AB",after:"A-other"},10100,{merge:true})
eq("field undo to a state never recorded rewrites the newest step",[h.undo.length,h.undo[0].before,h.undo[0].after],[1,"A","A-other"])
h=H()
api.rpgHistPush(h,{type:"sec-edit",key:"sec:2:content",before:"x",after:"y"},10000)
api.rpgHistPush(h,{type:"sec-edit",key:"sec:1:content",before:"A",after:"AB"},10100,{merge:true})
eq("merge mode with another field on top is an ordinary step",h.undo.length,2)
// invalidation: clear, and ids that changed
h=H()
api.rpgHistPush(h,{type:"sec-del",label:"d",sec:{id:5,title:"Scope"},index:1},1)
api.rpgHistPush(h,{type:"sec-edit",id:5,field:"title",key:"sec:5:title",before:"a",after:"b"},2)
api.rpgHistPush(h,{type:"sec-order",before:[4,5,6],after:[5,4,6]},3)
api.rpgHistPush(h,{type:"f-edit",id:5,key:"f:5:title",before:{title:"a"},after:{title:"b"}},4)
api.rpgHistPush(h,{type:"f-order",before:[5,9],after:[9,5]},5)
api.rpgHistPush(h,{type:"f-del",finding:{id:9},index:0},6)
api.rpgHistTake(h,"undo")
api.rpgHistRemap(h,"sec",5,50)
eq("a restored section's new id reaches every step that mentions it",[h.undo[0].sec.id,h.undo[1].id,h.undo[1].key,h.undo[2].before,h.undo[2].after],[50,50,"sec:50:title",[4,50,6],[50,4,6]])
eq("findings with the same number are untouched",[h.undo[3].id,h.undo[3].key,h.undo[4].before],[5,"f:5:title",[5,9]])
api.rpgHistRemap(h,"f",9,90)
eq("a restored finding's new id reaches both stacks",[h.undo[4].before,h.undo[4].after,h.redo[0].finding.id,h.undo[2].before],[[5,90],[90,5],90,[4,50,6]])
eq("edit values are never mistaken for ids",[h.undo[1].before,h.undo[3].before],["a",{title:"a"}])
api.rpgHistClear(h)
eq("clear (another report was opened)",[h.undo.length,h.redo.length],[0,0])
eq("same ids whatever the order",[api.rpgSameIds([{id:1},{id:2}],[{id:2},{id:1}]),api.rpgSameIds([{id:1}],[{id:1},{id:2}]),api.rpgSameIds([],null),api.rpgSameIds([{id:"3"}],[{id:3}])],[true,false,true,true])
eq("step names for report fields",["title","status","meta.client","meta.schedule","branding.accent","options.page_size","branding.theme"].map(api.rpgPathLabel),["rename the report","change the status","edit client","edit the timeline","edit branding: accent","edit export option: page size","change the report theme"])
eq("same / clone",[api.rpgSame({a:[1]},{a:[1]}),api.rpgSame(undefined,null),api.rpgSame("",null),api.rpgClone(undefined),api.rpgClone({a:1}).a],[true,true,false,undefined,1])

// where a new section goes
const secs=[{id:1,kind:"executive_summary"},{id:2,kind:"findings"},{id:3,kind:"appendix_tools"},{id:4,kind:"appendix_evidence"}]
eq("new section: after the open one",api.rpgInsertIndex(secs,2,"custom"),2)
eq("new section: in front of the appendices",[api.rpgInsertIndex(secs,null,"risk_matrix"),api.rpgInsertIndex(secs,99,"conclusion")],[2,2])
eq("new section: an appendix goes last",api.rpgInsertIndex(secs,null,"appendix_commands"),4)
eq("new section: no appendices, empty report",[api.rpgInsertIndex(secs.slice(0,2),null,"scope"),api.rpgInsertIndex([],null,"scope"),api.rpgInsertIndex(null,null,"scope")],[2,0,0])

// risk matrix
const mx=api.rpgRiskMatrix([{severity:"critical",likelihood:"high"},{severity:"critical",likelihood:"High"},{severity:"high",likelihood:"low"},{severity:"medium"},{severity:"weird",likelihood:"medium"}])
eq("risk matrix columns",mx.cols,["High","Medium","Low","Not set"])
eq("risk matrix counts",mx.rows.map((r)=>r.sev+":"+r.cells.join("")),["critical:2000","high:0010","medium:0001","low:0000","info:0100"])
eq("risk matrix of nothing",api.rpgRiskMatrix(null).rows.every((r)=>r.cells.join("")==="0000"),true)
}

// report list: compact numbers
{
const c=api.rpgCompactNum
eq("compact: small numbers are exact",[0,1,7,999].map((n)=>c(n)),["0","1","7","999"])
eq("compact: thousands",[1000,1001,1099,1100,1234,9999].map((n)=>c(n)),["1k","1k","1k","1.1k","1.2k","9.9k"])
eq("compact: ten thousands keep one decimal",[10000,10049,12345,99999].map((n)=>c(n)),["10k","10k","12.3k","99.9k"])
eq("compact: hundred thousands have no decimal",[100000,499995,999999].map((n)=>c(n)),["100k","499k","999k"])
eq("compact: millions and beyond",[1e6,1234567,999999999,1e9,2.5e12].map((n)=>c(n)),["1M","1.2M","999M","1B","2.5T"])
eq("compact: never rounds up",[c(1999),c(19999),c(999999)],["1.9k","19.9k","999k"])
eq("compact: negatives",[-1,-999,-1000,-1234,-99999,-1e6].map((n)=>c(n)),["-1","-999","-1k","-1.2k","-99.9k","-1M"])
eq("compact: junk is zero",[NaN,undefined,null,"x",Infinity].map((n)=>c(n)),["0","0","0","0","0"])
eq("compact: fractions and numeric text",[c(12.9),c("1500"),c(-0.5)],["12","1.5k","0"])
eq("compact tight: no decimal from 10k",[999,1234,9999,10000,12345,99999,999999,1500000].map((n)=>c(n,true)),["999","1.2k","9.9k","10k","12k","99k","999k","1.5M"])
check("compact: at most five characters up to the trillions",[1,12,123,1234,12345,123456,1234567,12345678,123456789,1234567890,99999999999].every((n)=>c(n).length<=5))
check("compact tight: at most four characters",[1,12,123,1234,12345,123456,1234567,12345678,123456789,1234567890].every((n)=>c(n,true).length<=4))
eq("exact number with separators",[0,999,1000,99999,499995,1234567,-1234567,NaN].map(api.rpgExactNum),["0","999","1,000","99,999","499,995","1,234,567","-1,234,567","0"])
}

// report list: clamped text and tooltips
{
const ch=String.fromCharCode
eq("clamp: short text is untouched",api.rpgClampText("ACME Corp",20),"ACME Corp")
eq("clamp: null and undefined",[api.rpgClampText(null),api.rpgClampText(undefined),api.rpgClampText(0)],["","","0"])
eq("clamp: white space collapses",api.rpgClampText("  a\t\tb\n\nc   d  "),"a b c d")
const long=api.rpgClampText("A".repeat(230),50)
eq("clamp: cut to the limit with an ellipsis",[long.length,long.slice(-1),long.slice(0,49)],[50,ch(0x2026),"A".repeat(49)])
eq("clamp: exactly the limit is not cut",api.rpgClampText("A".repeat(50),50),"A".repeat(50))
eq("clamp: default limit is 600",Array.from(api.rpgClampText("x".repeat(5000))).length,600)
const emoji=ch(0xd83d,0xdd12)
const cut=api.rpgClampText(emoji.repeat(10),4)
eq("clamp: never splits a surrogate pair",[Array.from(cut).length,cut.slice(0,2),/[\ud800-\udbff]$/.test(cut.slice(0,-1))],[4,emoji,false])
eq("clamp: bidi overrides and isolates are dropped",api.rpgClampText("abc"+ch(0x202e)+"gpj.exe"+ch(0x202c)+ch(0x2066)+"x"+ch(0x2069)+ch(0x200f)),"abcgpj.exex")
eq("clamp: control characters become spaces",api.rpgClampText("a"+ch(0)+ch(7)+"b"+ch(0x2028)+"c"+ch(0x85)+"d"),"a b c d")
const rtl=ch(0x645,0x631,0x62d,0x628,0x627)+" ACME"
eq("clamp: right-to-left text is kept as it is",api.rpgClampText(rtl,40),rtl)
eq("clamp: a cut does not leave a trailing space",api.rpgClampText("aaaa bbbb",6),"aaaa"+ch(0x2026))
}

// report list: extreme dates
{
const now=Date.parse("2026-11-24T12:00:00Z")
eq("stamp text",api.rpgStampText("2026-11-24T10:05:59+00:00"),"2026-11-24 10:05 UTC")
eq("stamp text without a zone is UTC",api.rpgStampText("2026-11-24 10:05:59"),"2026-11-24 10:05 UTC")
eq("stamp text: 1970 and 2999",[api.rpgStampText("1970-01-01T00:00:00"),api.rpgStampText("2999-12-31T23:59:59")],["1970-01-01 00:00 UTC","2999-12-31 23:59 UTC"])
eq("stamp text: junk",[api.rpgStampText(""),api.rpgStampText(null),api.rpgStampText("nonsense"),api.rpgStampText("275760-09-13T00:00:00Z")],["","","",""])
eq("relative time: very old date",api.rpgRelTime("1970-01-01T00:00:00",now),"1970-01-01")
eq("relative time: far future prints the date",api.rpgRelTime("2999-12-31T23:59:59",now),"2999-12-31")
eq("relative time: a few hours ahead is a clock difference",api.rpgRelTime("2026-11-24T20:00:00Z",now),"Just now")
eq("relative time: more than a day ahead prints the date",api.rpgRelTime("2026-11-26T12:00:00Z",now),"2026-11-26")
eq("day span: days",[0,1,2,99].map((n)=>api.rpgDaySpan(n)),["0 days","1 day","2 days","99 days"])
eq("day span: months and years",[100,365,729,730,20367,355000].map((n)=>api.rpgDaySpan(n)),["3 months","11 months","23 months","1 years","55 years","971 years"])
eq("day span: short form",[5,99,100,729,730,20367].map((n)=>api.rpgDaySpan(n,true)),["5d","99d","3mo","23mo","1y","55y"])
eq("day span: sign and junk are ignored",[api.rpgDaySpan(-20367),api.rpgDaySpan("x"),api.rpgDaySpan(-3,true)],["55 years","0 days","3d"])
eq("deadline chip: 1970 is overdue by years, not 20000 days",api.rpgDeadlineText("Hand-over",-20781),"Overdue by 56 years")
eq("deadline chip: 2999 is years away",api.rpgDeadlineText("Draft report",355300),"Draft report in 972 years")
eq("deadline chip: months",[api.rpgDeadlineText("QA",120),api.rpgDeadlineText("QA",-120)],["QA in 3 months","Overdue by 3 months"])
eq("deadline chip short: extremes",[-20781,355300,150,-150].map(api.rpgDeadlineShort),["56y late","972y","4mo","4mo late"])
eq("deadline parts: the name is separate from the when",[api.rpgDeadlineParts("Hand-over",3),api.rpgDeadlineParts("",0),api.rpgDeadlineParts("Hand-over",-2)],[{name:"Hand-over",when:"in 3 days"},{name:"Milestone",when:"today"},{name:"",when:"Overdue by 2 days"}])
check("deadline chip text stays short for any date",[-999999,-20781,-1,0,1,99,100,729,730,355300,999999].every((n)=>api.rpgDeadlineParts("X",n).when.length<=22&&api.rpgDeadlineShort(n).length<=10))
}

// report list: chunks
{
eq("chunk size",api.RPG_CHUNK,36)
eq("first chunk",[0,1,7,36,60,500].map((t)=>api.rpgChunkNext(0,t)),[0,1,7,36,36,36])
eq("next chunks stop at the total",[api.rpgChunkNext(36,60),api.rpgChunkNext(36,500),api.rpgChunkNext(468,500),api.rpgChunkNext(500,500)],[60,72,500,500])
eq("chunk with its own size and junk",[api.rpgChunkNext(10,100,25),api.rpgChunkNext(-5,100,25),api.rpgChunkNext(NaN,100,25),api.rpgChunkNext(10,-3,25)],[35,25,25,0])
let shown=0,steps=0
while(shown<500){shown=api.rpgChunkNext(shown,500);steps++}
eq("500 cards arrive in 14 chunks",steps,14)
eq("chunk that holds an index",[0,35,36,71,72,499].map((i)=>api.rpgChunkFor(i,500)),[36,36,72,72,108,500])
eq("chunk for an index: short lists and junk",[api.rpgChunkFor(0,7),api.rpgChunkFor(6,7),api.rpgChunkFor(-1,500),api.rpgChunkFor(undefined,500),api.rpgChunkFor(0,0),api.rpgChunkFor(-1,0),api.rpgChunkFor(999,500)],[7,7,36,36,0,0,500])
}

// report list: grid and keyboard
{
eq("grid columns follow the list width",[0,269,270,551,552,834,1476,1860].map((w)=>api.rpgGridCols(w)),[1,1,1,1,2,3,5,6])
eq("grid columns with other sizes",[api.rpgGridCols(1000,200,0),api.rpgGridCols(1000,300,20),api.rpgGridCols("x")],[5,3,1])
eq("card inner width",[api.rpgCardInner(1476),api.rpgCardInner(712),api.rpgCardInner(270),api.rpgCardInner(0)],[255,320,240,0])
const nav=(cur,key,cols,total,page)=>api.rpgNavIndex(cur,key,cols,total,page)
eq("nav: left and right stop at the ends",[nav(0,"ArrowLeft",5,7),nav(3,"ArrowLeft",5,7),nav(3,"ArrowRight",5,7),nav(6,"ArrowRight",5,7)],[0,2,4,6])
eq("nav: right wraps to the next row",nav(4,"ArrowRight",5,7),5)
eq("nav: up and down keep the column",[nav(1,"ArrowDown",5,12),nav(6,"ArrowUp",5,12),nav(1,"ArrowUp",5,12),nav(6,"ArrowDown",5,12)],[6,1,1,11])
eq("nav: down into a shorter last row lands on the last card",[nav(2,"ArrowDown",5,7),nav(4,"ArrowDown",5,7),nav(0,"ArrowDown",5,7)],[6,6,5])
eq("nav: down on the last row stays",[nav(5,"ArrowDown",5,7),nav(6,"ArrowDown",5,7)],[5,6])
eq("nav: home and end",[nav(3,"Home",5,500),nav(3,"End",5,500)],[0,499])
eq("nav: page down and up",[nav(2,"PageDown",5,500,3),nav(17,"PageUp",5,500,3),nav(2,"PageUp",5,500,3),nav(497,"PageDown",5,500,3),nav(490,"PageDown",5,500,3)],[17,2,2,497,495])
eq("nav: page down past a short last row",nav(3,"PageDown",5,7,3),6)
eq("nav: one column",[nav(0,"ArrowDown",1,3),nav(2,"ArrowDown",1,3),nav(2,"ArrowUp",1,3),nav(1,"ArrowRight",1,3)],[1,2,1,2])
eq("nav: no cards, no current card, unknown key",[nav(0,"ArrowDown",5,0),nav(-1,"ArrowDown",5,7),nav(-1,"End",5,7),nav(3,"a",5,7),nav(99,"ArrowLeft",5,7)],[-1,0,6,3,5])
check("nav: every key keeps the index inside the list",(()=>{for(let total=1;total<=13;total++)for(let cols=1;cols<=6;cols++)for(let cur=0;cur<total;cur++)for(const k of ["ArrowLeft","ArrowRight","ArrowUp","ArrowDown","Home","End","PageUp","PageDown"]){const to=nav(cur,k,cols,total,2);if(!(to>=0&&to<total))return false}return true})())
check("nav: every card can be reached with the arrows from the first",(()=>{for(let total=1;total<=13;total++)for(let cols=1;cols<=6;cols++){const seen=new Set([0]);let grew=true;while(grew){grew=false;Array.from(seen).forEach((c)=>["ArrowLeft","ArrowRight","ArrowUp","ArrowDown"].forEach((k)=>{const to=nav(c,k,cols,total);if(!seen.has(to)){seen.add(to);grew=true}}))}if(seen.size!==total)return false}return true})())
}

// report list: the severity row fits one line
{
const lay=(c,total,w)=>api.rpgSevLayout(c,total,w)
const one=lay({critical:1},1,240)
eq("one finding: label and total",[one.level,one.parts.map((p)=>p.text+" "+p.short),one.total,one.totalTip],[0,["1 Crit"],"1 finding","1 finding"])
eq("zero counts are left out",lay({critical:0,high:2,medium:0,low:3,info:0},5,400).parts.map((p)=>p.id),["high","low"])
eq("no findings",[lay({},0,240).parts,lay(null,0,240).parts,lay({},0,240).total],[[],[],""])
const five={critical:3,high:12,medium:40,low:7,info:2}
eq("wide card: labels and total",[lay(five,64,460).level,lay(five,64,460).total],[0,"64 findings"])
eq("labels win over the total",[lay({critical:3,high:12,medium:40},55,256).level,lay({critical:3,high:12,medium:40},55,256).total],[0,""])
eq("narrow card: numbers only",lay(five,64,240).level,1)
const big={critical:99999,high:99999,medium:99999,low:99999,info:99999}
const b=lay(big,499995,240)
eq("99999 of each: tight pills, short total, exact tooltip",[b.level,b.parts.map((p)=>p.text),b.total,b.totalTip],[2,["99k","99k","99k","99k","99k"],"499k","499,995 findings"])
eq("thousands on a wide card keep the decimal",lay({critical:1234,high:5678},6912,400).parts.map((p)=>p.text),["1.2k","5.6k"])
eq("the exact count travels with each part",b.parts.map((p)=>p.n),[99999,99999,99999,99999,99999])
check("levels only get tighter as the card narrows",(()=>{let prev=0;for(let w=600;w>=200;w-=10){const l=lay({critical:1234,high:5678,medium:12345,low:9999,info:10000},39256,w).level;if(l<prev)return false;prev=l}return prev===2})())
eq("default width is the narrowest card",lay(five,64).level,lay(five,64,240).level)
}

console.log("")
console.log(passed+" passed, "+failed+" failed")
process.exit(failed?1:0)
