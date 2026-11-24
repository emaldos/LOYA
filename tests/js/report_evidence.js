// Pure helpers of UI/js/components/report-evidence.js (no DOM): node tests/js/report_evidence.js
const path=require("path")
const m=require(path.join(__dirname,"..","..","UI","js","components","report-evidence.js"))
let passed=0,failed=0
function check(name,ok,detail){if(ok)passed++;else{failed++;console.log("FAIL: "+name+(detail!==undefined?" - "+JSON.stringify(detail):""))}}
function eq(name,actual,expected){check(name,JSON.stringify(actual)===JSON.stringify(expected),actual)}
// escaping
eq("esc covers the five HTML characters",m.esc('<img src=x onerror="a(\'b\')">&'),"&lt;img src=x onerror=&quot;a(&#39;b&#39;)&quot;&gt;&amp;")
eq("esc turns null and undefined into an empty string",[m.esc(null),m.esc(undefined),m.esc(0)],["","","0"])
// formatting
eq("elapsed under a minute",m.elapsed(9400),"00:09")
eq("elapsed minutes",m.elapsed(125000),"02:05")
eq("elapsed hours",m.elapsed(3723000),"1:02:03")
eq("elapsed never goes negative",[m.elapsed(-5),m.elapsed(undefined)],["00:00","00:00"])
eq("size bytes, KB, MB",[m.size(0),m.size(512),m.size(2048),m.size(150000),m.size(3*1024*1024)],["0 B","512 B","2.0 KB","146 KB","3.0 MB"])
eq("when keeps unparseable text and empties",[m.when(""),m.when("not a date")],["","not a date"])
check("when renders local date and time",/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/.test(m.when("2026-11-23T10:12:03+00:00")))
eq("kind labels",["command","recording","text","image","x"].map(m.kindLabel),["Command","Recording","Text","Screenshot","Evidence"])
eq("severity labels fall back to informational",[m.sevLabel("critical"),m.sevLabel("info"),m.sevLabel("bogus")],["Critical","Informational","Informational"])
// list helpers
const list=[
{id:1,kind:"command",title:"nmap -sV 10.0.0.5",command:"nmap -sV 10.0.0.5",session_id:"s1",preview:"22/tcp open ssh",target:"web01",meta:{session_label:"bash 1",tags:["recon"]}},
{id:2,kind:"recording",title:"Session recording",command:"",session_id:"s2",preview:"",target:"",meta:{session_label:"zsh 2",notes:"domain controller"}},
{id:3,kind:"text",title:"Scope",command:"",session_id:"",preview:"only 10.0.0.0/24",target:"",meta:{}},
{id:4,kind:"command",title:"id",command:"id",session_id:"s1",preview:"uid=0",target:"web01",meta:{}}]
eq("sessionsOf lists each session once with its label",m.sessionsOf(list),[{id:"s1",label:"bash 1"},{id:"s2",label:"zsh 2"}])
eq("sessionsOf falls back to a short id",m.sessionsOf([{session_id:"abcdef123456",meta:{}}]),[{id:"abcdef123456",label:"Session abcdef"}])
eq("sessionsOf tolerates nothing",m.sessionsOf(null),[])
const ids=(rows)=>rows.map((r)=>r.id)
eq("filter by kind",ids(m.filter(list,{kind:"command"})),[1,4])
eq("filter by allowed kinds",ids(m.filter(list,{kinds:["text","recording"]})),[2,3])
eq("filter by session",ids(m.filter(list,{session:"s1"})),[1,4])
eq("filter query matches the preview",ids(m.filter(list,{query:"OPEN SSH"})),[1])
eq("filter query matches notes and tags",[ids(m.filter(list,{query:"domain"})),ids(m.filter(list,{query:"recon"}))],[[2],[1]])
eq("filter query matches the target",ids(m.filter(list,{query:"web01"})),[1,4])
eq("filter combines conditions",ids(m.filter(list,{kind:"command",session:"s1",query:"uid"})),[4])
eq("empty filter keeps everything",ids(m.filter(list,{})),[1,2,3,4])
// job info from a terminal tab
const tab={sessionId:"s1",shellId:"bash",label:"bash 1",cwd:"/home/kali",buffer:"0123456789ABCDEFGHIJ"}
eq("jobInfo slices the tab buffer between the job offsets",m.jobInfo(tab,{jobId:"j1",command:"id",startIdx:5,endIdx:10,exitCode:0,startedAt:1000,endedAt:2000}),{session_id:"s1",job_key:"j1",command:"id",output:"56789",exit_code:0,cwd:"/home/kali",started_at:1000,ended_at:2000,shell:"bash",session_label:"bash 1"})
eq("jobInfo of a running job takes the buffer to its end",m.jobInfo(tab,{jobId:"j2",command:"sleep 9",startIdx:15,endIdx:null,exitCode:null,startedAt:1000,endedAt:null}).output,"FGHIJ")
eq("jobInfo keeps a null exit code",m.jobInfo(tab,{jobId:"j2",command:"x",startIdx:0,endIdx:null}).exit_code,null)
eq("jobInfo without a tab or record is null",[m.jobInfo(null,{}),m.jobInfo(tab,null)],[null,null])
// recorder queue
let clock=0
const q=new m.Queue(()=>"t"+(++clock))
q.push("out","a")
q.push("out","b")
q.push("cmd","id")
q.push("out","c")
q.push("out","")
q.push("exit",{code:0,duration:1})
eq("queue merges consecutive output and keeps event order",q.events,[{ts:"t1",kind:"out",data:"ab"},{ts:"t2",kind:"cmd",data:"id"},{ts:"t3",kind:"out",data:"c"},{ts:"t4",kind:"exit",data:{code:0,duration:1}}])
const taken=q.take()
eq("take empties the queue",[taken.length,q.events.length,q.chars],[4,0,0])
q.push("out","later")
q.putBack(taken)
eq("putBack restores unsent events in front of newer ones",q.events.map((e)=>e.kind+":"+(typeof e.data==="string"?e.data:"")),["out:ab","cmd:id","out:c","exit:","out:later"])
check("putBack recounts the size",q.chars===2+2+1+32+5,q.chars)
const big=new m.Queue(()=>"t")
big.push("cmd","first")
big.push("out","x".repeat(m.QUEUE_MAX))
big.push("cmd","second")
big.push("out","y".repeat(1000))
check("an overfull queue drops its oldest output",big.chars<=m.QUEUE_MAX&&!big.events.some((e)=>e.kind==="out"&&e.data[0]==="x"))
eq("an overfull queue keeps commands and marks the gap once",big.events.map((e)=>e.kind),["cmd","mark","cmd","out"])
big.push("out","z".repeat(m.QUEUE_MAX))
check("the gap marker is not repeated",big.events.filter((e)=>e.kind==="mark").length===1)
const fresh=new m.Queue()
fresh.push("mark","note")
check("the default clock gives ISO timestamps",/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/.test(fresh.events[0].ts))
// wizard helpers
const preview={timeline:[{},{},{}],tools:[{},{}],hosts:[{ports:[{},{}]},{ports:[{}]},{}],candidates:[{key:"a",confidence:"high"},{key:"b",confidence:"medium"},{key:"c",confidence:"low"}]}
eq("summary counts commands, tools, hosts, ports and candidates",m.summary(preview),{commands:3,tools:2,hosts:3,ports:3,candidates:3})
eq("summary of nothing is all zeroes",m.summary(null),{commands:0,tools:0,hosts:0,ports:0,candidates:0})
eq("low-confidence candidates start unticked",m.defaultAccepted(preview.candidates),{a:true,b:true,c:false})
eq("defaultAccepted tolerates nothing",m.defaultAccepted(undefined),{})
const day=new Date(2026,10,3)
eq("default title names the profile",m.defaultTitle("ACME Internal",day),"Penetration test report - ACME Internal - 2026-11-03")
eq("default title skips the Default profile",[m.defaultTitle("Default",day),m.defaultTitle("",day)],["Penetration test report - 2026-11-03","Penetration test report - 2026-11-03"])
check("loading under Node defines no browser global",typeof globalThis.ReportEvidence==="undefined")
console.log(passed+" passed, "+failed+" failed")
process.exit(failed?1:0)
