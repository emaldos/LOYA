// The run log viewer of chain diagrams (UI/js/components/flow-log.js): filtering, grouping, search highlight segments,
// the follow-the-tail decision, the DOM window for long logs, and that no log text reaches the page unescaped.
const fs=require("fs")
const path=require("path")
const ROOT=path.resolve(__dirname,"..","..")
const SRC=fs.readFileSync(path.join(ROOT,"UI","js","components","flow-log.js"),"utf8")
const CSS=fs.readFileSync(path.join(ROOT,"UI","css","flow-panels.css"),"utf8")
const MAIN=fs.readFileSync(path.join(ROOT,"UI","windows","main.html"),"utf8")
const L=require(path.join(ROOT,"UI","js","components","flow-log.js"))
let passed=0,failed=0
function check(name,cond,detail){if(cond){passed++;return}failed++;console.log("  FAIL  "+name+(detail?"  ->  "+detail:""))}
function eq(name,a,b){check(name,JSON.stringify(a)===JSON.stringify(b),JSON.stringify(a)+" != "+JSON.stringify(b))}
const TITLES={n2:{title:"Ping",type:"command"},n3:{title:"Alive?",type:"decision"}}
const RAW=[
{seq:1,ts:"2026-01-01T10:00:00+00:00",node:null,level:"info",kind:"run",text:"Run started"},
{seq:2,ts:"2026-01-01T10:00:01+00:00",node:"n2",title:"Ping host",level:"info",kind:"command",text:"$ ping -c 2 10.0.0.5"},
{seq:3,ts:"2026-01-01T10:00:02+00:00",node:"n2",level:"warn",kind:"exit",text:"Ping: exit code 1"},
{seq:4,ts:"2026-01-01T10:00:02+00:00",node:"n3",level:"info",kind:"decision",text:"Decision: down"},
{seq:5,ts:"2026-01-01T10:00:03+00:00",node:"n4",level:"ERROR",kind:"script",text:"Traceback: <img src=x onerror=alert(1)> boom"},
{seq:6,ts:"bad",node:"n2",level:"warning",text:"PING again & again"}]
const E=RAW.map((e)=>L.flowLogNormalize(e,TITLES))
eq("normalize: fixed shape, levels folded, titles from the entry, the graph, or the id",E.map((e)=>[e.seq,e.node,e.title,e.level]),[[1,"","","info"],[2,"n2","Ping host","info"],[3,"n2","Ping","warn"],[4,"n3","Alive?","info"],[5,"n4","n4","error"],[6,"n2","Ping","warn"]])
eq("normalize: junk in, safe defaults out",[L.flowLogNormalize(null),L.flowLogNormalize({seq:"x",text:null,level:7})],[{seq:0,ts:"",node:"",title:"",level:"info",kind:"",text:""},{seq:0,ts:"",node:"",title:"",level:"info",kind:"",text:""}])
eq("levels",["error","err","FATAL","warn","Warning","info","debug",null].map(L.flowLogLevel),["error","error","error","warn","warn","info","info","info"])
eq("events fallback: status events become log entries",L.flowLogFromEvents([{seq:1,ts:"t",node:"n2",level:"warn",text:"x"},null,"junk"],TITLES).map((e)=>[e.seq,e.title,e.level,e.text]),[[1,"Ping","warn","x"]])
// merge
const grown=L.flowLogMerge(E.slice(0,3),E.slice(1))
eq("merge: only newer entries are appended, in place",grown.map((e)=>e.seq),[1,2,3,4,5,6])
eq("merge: empty and junk",[L.flowLogMerge([],null).length,L.flowLogMerge(null,[E[0]]).length,L.flowLogMerge([E[5]],[E[0],null]).length],[0,1,1])
// filter
check("filter: no filter returns the same list (no copy for 20k entries)",L.flowLogFilter(E,{level:"all",node:"",query:"  "})===E&&L.flowLogFilter(E,null)===E)
eq("filter: by level",[L.flowLogFilter(E,{level:"error"}).map((e)=>e.seq),L.flowLogFilter(E,{level:"warn"}).map((e)=>e.seq),L.flowLogFilter(E,{level:"info"}).map((e)=>e.seq)],[[5],[3,6],[1,2,4]])
eq("filter: by node",L.flowLogFilter(E,{node:"n2"}).map((e)=>e.seq),[2,3,6])
eq("filter: search is case-insensitive, every word must match, node titles and kinds count",[L.flowLogFilter(E,{query:"PING"}).map((e)=>e.seq),L.flowLogFilter(E,{query:"ping exit"}).map((e)=>e.seq),L.flowLogFilter(E,{query:"alive?"}).map((e)=>e.seq),L.flowLogFilter(E,{query:"script"}).map((e)=>e.seq),L.flowLogFilter(E,{query:"zzz"}).length],[[2,3,6],[3],[4],[5],0])
eq("filter: combined",L.flowLogFilter(E,{level:"warn",node:"n2",query:"again"}).map((e)=>e.seq),[6])
eq("filter: null-safe",L.flowLogFilter(null,{level:"error"}),[])
eq("counts",[L.flowLogCounts(E),L.flowLogCounts(null)],[{all:6,error:1,warn:2,info:3},{all:0,error:0,warn:0,info:0}])
eq("nodes: the ones that have entries, first appearance first, with counts",L.flowLogNodes(E),[{node:"n2",title:"Ping host",count:3},{node:"n3",title:"Alive?",count:1},{node:"n4",title:"n4",count:1}])
// grouping
const groups=L.flowLogGroup(E)
eq("group: by node in order of first appearance, run-level lines in their own group",groups.map((g)=>[g.node,g.title,g.entries.map((e)=>e.seq),g.errors,g.warnings]),[["","Run",[1],0,0],["n2","Ping host",[2,3,6],0,2],["n3","Alive?",[4],0,0],["n4","n4",[5],1,0]])
eq("group: empty",L.flowLogGroup(null),[])
// highlight segments
eq("segments: no query, one plain piece",L.flowLogSegments("abc",""),[{text:"abc",hit:false}])
eq("segments: every occurrence, case kept",L.flowLogSegments("Ping ping PING","ping"),[{text:"Ping",hit:true},{text:" ",hit:false},{text:"ping",hit:true},{text:" ",hit:false},{text:"PING",hit:true}])
eq("segments: several words, overlaps merged",L.flowLogSegments("abcdef","abc cde"),[{text:"abcde",hit:true},{text:"f",hit:false}])
eq("segments: nothing found, empty text, regex characters are plain text",[L.flowLogSegments("abc","x"),L.flowLogSegments("","x"),L.flowLogSegments("a.*b (x)","(x) .*")],[[{text:"abc",hit:false}],[{text:"",hit:false}],[{text:"a",hit:false},{text:".*",hit:true},{text:"b ",hit:false},{text:"(x)",hit:true}]])
check("segments: joined back they are the original text",["Ping ping PING","abcdef","<b>x</b>"].every((t)=>L.flowLogSegments(t,"p b c").map((s)=>s.text).join("")===t))
eq("mark html: escaped inside and outside the marks",L.flowLogMarkHtml("<b>x&y</b>","b x&"),"&lt;<mark>b</mark>&gt;<mark>x&amp;</mark>y&lt;/<mark>b</mark>&gt;")
// rows
const row=L.flowLogRowHtml(E[4],"boom")
check("row: log text never reaches the page as html",row.indexOf("<img")<0&&row.indexOf("&lt;img src=x onerror=alert(1)&gt;")>0&&/<mark>boom<\/mark>/.test(row))
check("row: errors and warnings are classed and labelled",/class="fl-row fl-error"/.test(row)&&/fl-level">ERROR</.test(row)&&/class="fl-row fl-warn"/.test(L.flowLogRowHtml(E[2],""))&&/fl-level">WARN</.test(L.flowLogRowHtml(E[2],""))&&/class="fl-row fl-info"/.test(L.flowLogRowHtml(E[0],"")))
check("row: time, node title; the node is left out inside a group",/fl-time">\d\d:\d\d:\d\d</.test(L.flowLogRowHtml(E[1],""))&&/fl-node">Ping host</.test(L.flowLogRowHtml(E[1],""))&&!/fl-node/.test(L.flowLogRowHtml(E[1],"",true))&&/fl-time"></.test(L.flowLogRowHtml(E[5],"")))
check("group head: escaped title, line count, error and warning pills",(()=>{const h=L.flowLogGroupHeadHtml({title:"<x>",entries:[1,2],errors:1,warnings:2});return h.indexOf("<x>")<0&&/2 lines/.test(h)&&/fl-pill-error">1 error</.test(h)&&/fl-pill-warn">2 warnings</.test(h)})()&&!/fl-pill/.test(L.flowLogGroupHeadHtml(groups[0]))&&/1 line</.test(L.flowLogGroupHeadHtml(groups[0])))
// follow the tail
eq("stick: only at (or near) the bottom",[L.flowLogShouldStick(900,100,1000),L.flowLogShouldStick(880,100,1000),L.flowLogShouldStick(800,100,1000),L.flowLogShouldStick(0,100,100),L.flowLogShouldStick(850,100,1000,60)],[true,true,false,true,true])
// the DOM window
eq("window: the newest lines are drawn, older ones are counted",[L.flowLogWindow(100,4000),L.flowLogWindow(20000,4000),L.flowLogWindow(20000,4000,4000),L.flowLogWindow(0,4000),L.flowLogWindow("x",0)],[{start:0,hidden:0},{start:16000,hidden:16000},{start:12000,hidden:12000},{start:0,hidden:0},{start:0,hidden:0}])
check("window: the viewer never draws more than the window plus one chunk at a time",L.FLOW_LOG_DOM_MAX<=5000&&L.FLOW_LOG_CHUNK<=500&&/parts\.slice\(at,at\+FLOW_LOG_CHUNK\)/.test(SRC)&&/v\.renderTimer=setTimeout\(step,0\)/.test(SRC))
// 20k entries stay cheap in the pure parts
const big=Array.from({length:20000},(_,i)=>L.flowLogNormalize({seq:i+1,ts:"2026-01-01T10:00:00+00:00",node:"n"+(i%7),level:i%50===0?"error":i%9===0?"warn":"info",text:"line "+i+" of output from 10.0.0."+(i%255)}))
const t0=Date.now()
const hits=L.flowLogFilter(big,{level:"all",node:"n3",query:"output 10.0.0.7"})
const grouped=L.flowLogGroup(big)
const rendered=big.slice(L.flowLogWindow(big.length,L.FLOW_LOG_DOM_MAX).start).map((e)=>L.flowLogRowHtml(e,"output")).join("")
const took=Date.now()-t0
check("scale: filtering, grouping and rendering the window of 20k lines is fast",hits.length>0&&grouped.length===7&&rendered.length>0&&took<1500,took+" ms")
// text
eq("text: one line per entry",L.flowLogText(E.slice(0,3),false).split("\n").map((l)=>l.replace(/^\d\d:\d\d:\d\d /,"")),["info  Run started","info  [Ping host] $ ping -c 2 10.0.0.5","WARN  [Ping] Ping: exit code 1"])
check("text: grouped",/^== Run ==\n[^\n]*Run started\n\n== Ping host ==\n/.test(L.flowLogText(E,true)))
eq("bridge missing",[L.flowLogBridgeMissing(new Error("bridge method missing: flows.run_log")),L.flowLogBridgeMissing(new Error("No such run.")),L.flowLogBridgeMissing(null)],[true,false,false])
// ---- the viewer's wiring
check("viewer: polls flows.run_log with since, and falls back to the status events",/bridge\("flows\.run_log",\[v\.runId,v\.next,2000\]\)/.test(SRC)&&/flowLogBridgeMissing\(err\)\)throw err\nv\.useEvents=true/.test(SRC))
check("viewer: Copy uses run_log_text for the whole log and the view when filtered; Export uses run_log_export",/bridge\("flows\.run_log_text",\[v\.runId\]\)/.test(SRC)&&/if\(filtered\|\|v\.useEvents\)\{copyText\(flowLogText\(v\.shown,v\.grouped\)\)/.test(SRC)&&/bridge\("flows\.run_log_export",\[v\.runId,fmt\]\)/.test(SRC))
check("viewer: scrolling up stops the tail and offers Jump to latest",/v\.stick=flowLogShouldStick\(list\.scrollTop,list\.clientHeight,list\.scrollHeight\)/.test(SRC)&&/Jump to latest/.test(SRC)&&/else jump\.classList\.remove\("fl-hidden"\)/.test(SRC))
check("viewer: search, level filter, node filter, group toggle",/class="fl-query"/.test(SRC)&&/data-fl="level"/.test(SRC)&&/class="fl-node-pick"/.test(SRC)&&/class="fl-group-toggle"/.test(SRC))
check("viewer: no innerHTML takes a raw entry field",!/innerHTML[^\n]*\+\s*(e|entry|r|res)\.(text|title|node|name)\b/.test(SRC.replace(/flowLogEscape\([^)]*\)/g,"ESC")))
check("viewer: no localStorage, no regex built from the search box",!/localStorage|sessionStorage/.test(SRC.replace(/^\/\/.*$/gm,""))&&!/new RegExp/.test(SRC))
const used=Array.from(new Set(SRC.match(/\bfl-[a-z-]+/g)||[]))
eq("css: every fl- class is styled",used.filter((c)=>CSS.indexOf("."+c)<0&&["fl-info","fl-group-toggle"].indexOf(c)<0),[])
check("css: errors use the danger colour and warnings the warning colour of the theme",/\.fl-error \.fl-text,\.fl-error \.fl-level\{color:var\(--danger\)\}/.test(CSS)&&/\.fl-warn \.fl-text,\.fl-warn \.fl-level\{color:var\(--fl-warn\)\}/.test(CSS)&&/:root\{--fl-warn:color-mix\(in srgb,var\(--pal-warn-border\) 88%,var\(--text\)\)\}\n\[data-theme="light"\]\{--fl-warn:color-mix\(/.test(CSS))
check("main: flow-log.js is loaded",MAIN.includes('<script src="../js/components/flow-log.js"></script>'))
check("line endings: LF only",SRC.indexOf("\r")<0)
console.log("flow_log: "+passed+" passed, "+failed+" failed")
process.exit(failed?1:0)
