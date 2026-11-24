// Post-E2E UX fixes: the result of a /caller diagram run printed in the terminal (display-only), long status pills that wrap,
// the Commands table fitting at 1280 px, and the diagram view giving the canvas room when the terminal is docked.
const fs=require("fs")
const path=require("path")
const vm=require("vm")
const ROOT=path.resolve(__dirname,"..","..")
const read=(...p)=>fs.readFileSync(path.join(ROOT,...p),"utf8")
const FLOW=read("UI","js","pages","chains_flow.js")
const MODEL=read("UI","js","components","flow-model.js")
const RUN=read("UI","js","components","flow-run.js")
const TERM=read("UI","js","components","terminal.js")
const ISLAND=read("UI","js","components","status-island.js")
const COMPONENTS=read("UI","css","components.css")
const COMMANDS=read("UI","css","pages","commands.css")
const PANELS=read("UI","css","flow-panels.css")
let passed=0,failed=0
function check(name,cond,detail){if(cond){passed++;return}failed++;console.log("  FAIL  "+name+(detail?"  ->  "+detail:""))}
function eq(name,a,b){check(name,JSON.stringify(a)===JSON.stringify(b),JSON.stringify(a)+" != "+JSON.stringify(b))}
function slice(source,from,to){const a=source.indexOf(from),b=source.indexOf(to,a);if(a<0||b<0)throw new Error("slice "+from);return source.slice(a,b)}
function rule(css,selector){const i=css.indexOf(selector+"{");if(i<0)return "";return css.slice(i,css.indexOf("}",i)+1)}

// ---- chains_flow.js in a sandbox with the real flow model and run helpers, a fake bridge and manual timers
const timers=[],notices=[],calls=[]
const handlers={}
const box={module:{exports:{}},console,
setTimeout:(fn)=>{timers.push(fn);return timers.length},clearTimeout:()=>{},requestAnimationFrame:(fn)=>{timers.push(fn);return 1},
bridgeCall:(p,a)=>{calls.push([p,a]);const h=handlers[p];return h?Promise.resolve().then(()=>h.apply(null,a||[])):Promise.reject(new Error("no handler "+p))},
termPrintNotice:(session,lines,kind)=>{notices.push({session,lines,kind});return true},
termState:{enabled:true,activeId:"sess-7"},
showStatusIsland:()=>{},showToast:()=>{}}
vm.createContext(box)
vm.runInContext(MODEL+"\n"+RUN+"\n"+FLOW,box)
const C=box.module.exports
const flush=async()=>{for(let i=0;i<30;i++){await Promise.resolve();await new Promise((r)=>setImmediate(r));timers.splice(0).forEach((fn)=>{try{fn()}catch(_){}})}}
const GRAPH={nodes:[{id:"n1",type:"start",title:"Start"},{id:"n2",type:"command",title:"Ping the host"},{id:"n3",type:"decision",title:"Host alive?"},{id:"n4",type:"command",title:"Nmap scan"},{id:"n5",type:"output",title:"Host is down"}],
edges:[{id:"e1",from:"n1",port:"out",to:"n2"},{id:"e2",from:"n2",port:"success",to:"n3"},{id:"e3",from:"n2",port:"fail",to:"n3"},{id:"e4",from:"n3",port:"alive",to:"n4"},{id:"e5",from:"n3",port:"down",to:"n5"}]}

;(async()=>{
// ---- a) the branch path and the summary of a diagram run
const ARROW=" → "
eq("path: the taken edges in order, branch names shown, Start and plain success ports left out",C.chainsFlowRunPath(GRAPH,{edges_taken:["e1","e2","e4"],nodes:{}}),["Ping the host","Host alive? [alive]","Nmap scan"].join(ARROW))
eq("path: the down branch, and a failed node is marked",C.chainsFlowRunPath(GRAPH,{edges_taken:["e1","e3","e5"],nodes:{n2:{state:"fail"}}}),["Ping the host (failed) [fail]","Host alive? [down]","Host is down"].join(ARROW))
eq("path: without edges_taken, the settled nodes in start order",C.chainsFlowRunPath(GRAPH,{nodes:{n1:{state:"success",started_at:"1"},n4:{state:"success",started_at:"3"},n2:{state:"success",started_at:"2"},n5:{state:"pending"}}}),["Ping the host","Nmap scan"].join(ARROW))
eq("path: null-safe",[C.chainsFlowRunPath(null,null),C.chainsFlowRunPath(GRAPH,{edges_taken:["zz"]})],["",""])
const long={nodes:[{id:"s",type:"start"}],edges:[]};const taken=[]
for(let i=0;i<20;i++){long.nodes.push({id:"x"+i,type:"wait",title:"W"+i});long.edges.push({id:"k"+i,from:i?"x"+(i-1):"s",port:"out",to:"x"+i});taken.push("k"+i)}
check("path: a long path is shortened in the middle",C.chainsFlowRunPath(long,{edges_taken:taken}).split(ARROW).length===12&&C.chainsFlowRunPath(long,{edges_taken:taken}).indexOf("...")>0)
const done=C.chainsFlowRunSummary({state:"done",name:"E2E Ping",target:"lab",started_at:"2026-01-01T00:00:00",ended_at:"2026-01-01T00:00:12",edges_taken:["e1","e2","e4"],nodes:{n1:{state:"success"},n2:{state:"success"},n3:{state:"success"},n4:{state:"success"},n5:{state:"skipped"}}},GRAPH,{caller:"ping-scan"})
eq("summary: done is ok",done.kind,"ok")
check("summary: status line names the caller, the chain, the result and the target",/^Chain \/ping-scan \(E2E Ping\): Finished - 4 ok/.test(done.lines[0])&&/on lab/.test(done.lines[0]),done.lines[0])
eq("summary: the path line",done.lines[1],"Path: "+["Ping the host","Host alive? [alive]","Nmap scan"].join(ARROW))
check("summary: says where the logs are",/^Open logs: Chains page > E2E Ping > History/.test(done.lines[2]),done.lines[2])
eq("summary: failed and timed out runs are errors, stopped ones info",[C.chainsFlowRunSummary({state:"failed"},GRAPH,{}).kind,C.chainsFlowRunSummary({state:"timeout"},GRAPH,{}).kind,C.chainsFlowRunSummary({state:"cancelled"},GRAPH,{}).kind],["error","error","info"])
// the whole loop: /caller from the terminal -> run -> the summary lands in the session it was typed in
let polls=0
handlers["flows.list"]=()=>[{playbook_id:4,name:"E2E Ping",caller:"ping-scan",has_graph:true,node_count:5}]
handlers["flows.run_status"]=(id,since)=>{polls++;return polls<3?{run_id:id,state:"running",nodes:{}}:{run_id:id,state:"done",name:"E2E Ping",edges_taken:["e1","e2","e4"],nodes:{n4:{state:"success"}}}}
handlers["flows.get"]=()=>({graph:GRAPH})
vm.runInContext("chainsFlowHeadless=()=>({confirmAndRun:()=>Promise.resolve('run-1')})",box)
const res=await vm.runInContext("chainsFlowRunChain(4,{source:'terminal'})",box)
eq("caller run: started through the flow engine",[res.started,res.run_id],[true,"run-1"])
await flush()
eq("caller run: one notice, in the session that typed /caller",notices.map((n)=>[n.session,n.kind,n.lines.length]),[["sess-7","ok",3]])
check("caller run: polled until final, without node outputs",polls===3&&calls.filter((c)=>c[0]==="flows.run_status").every((c)=>c[1][0]==="run-1"&&c[1][1]>=1e9))
notices.length=0;polls=0
await vm.runInContext("chainsFlowRunChain(4,{source:'ai'})",box)
await flush()
eq("other sources (AI, Run button) print nothing in the terminal",[notices.length,polls],[0,0])

// ---- a) termPrintNotice: display-only, above the prompt line, indices after it shifted
const termFns=slice(TERM,"function termPrintNotice","function termElevationFailureText")
const sent=[]
const tab={sessionId:"s1",visible:"$ ls\nfile\n",pendingRaw:"$ ",buffer:"$ ls\nfile\n$ ",renderVersion:0,listings:[{startIdx:2,endIdx:9}],jobHistory:[{startIdx:12,endIdx:null},{startIdx:0,endIdx:5}],pendingCapture:{startIdx:12}}
const env=new Function("termState","termFindTab","termPendingVisible","termInvalidateRender","termTrimScrollback","termRenderSession","termSendRaw",termFns+";return termPrintNotice")(
{activeId:"s1"},(id)=>id===tab.sessionId?tab:null,(t)=>t.pendingRaw,(t)=>{t.renderVersion++},()=>false,(id)=>{tab.rendered=id},(x)=>sent.push(x))
check("notice: printed into the session",env("s1",["Chain /x: Done","Path: a → b","esc \x1b[2J gone"],"ok")===true)
const added=tab.visible.slice("$ ls\nfile\n".length)
check("notice: above the prompt, which stays the pending line",tab.visible.indexOf("$ ls\nfile\n")===0&&tab.buffer===tab.visible+"$ "&&tab.rendered==="s1"&&tab.renderVersion===1)
check("notice: first line bold green, the rest dim and indented",/^\x1b\[0m\x1b\[1;32mChain \/x: Done\x1b\[0m\n\x1b\[2m  Path: a → b\x1b\[0m\n/.test(added),JSON.stringify(added))
check("notice: control characters from the text cannot inject escapes",added.indexOf("\x1b[2J")<0&&/esc +\[2J gone/.test(added))
eq("notice: indices at or after the prompt move down, earlier ones stay",[tab.listings[0],tab.jobHistory[0].startIdx,tab.jobHistory[0].endIdx,tab.jobHistory[1],tab.pendingCapture.startIdx],[{startIdx:2,endIdx:9},12+added.length,null,{startIdx:0,endIdx:5},12+added.length])
eq("notice: nothing is sent to the shell",sent,[])
const t2={sessionId:"s2",visible:"half",pendingRaw:"",buffer:"half",renderVersion:0}
new Function("termState","termFindTab","termPendingVisible","termInvalidateRender","termTrimScrollback","termRenderSession",termFns+";return termPrintNotice")({activeId:"s2"},(id)=>id==="s2"?t2:null,()=>"",()=>{},()=>false,()=>{})("gone",["x"],"error")
check("notice: a closed session falls back to the active one, starting on a new line, red for errors",t2.visible==="half\n\x1b[0m\x1b[1;31mx\x1b[0m\n",JSON.stringify(t2.visible))
const t3={sessionId:"s3",visible:"$ id\nuid=0\n\x1b[32m\u250c\u2500\u2500(kali)-[~]\r\n",pendingRaw:"\u2514\u2500$ ",buffer:"",renderVersion:0,jobHistory:[{startIdx:0,endIdx:30}]}
new Function("termState","termFindTab","termPendingVisible","termInvalidateRender","termTrimScrollback","termRenderSession",termFns+";return termPrintNotice")({activeId:"s3"},()=>t3,(t)=>t.pendingRaw,()=>{},()=>false,()=>{})("s3",["Chain done"],"ok")
check("notice: goes above both lines of a two-line Kali prompt",t3.visible==="$ id\nuid=0\n\x1b[0m\x1b[1;32mChain done\x1b[0m\n\x1b[32m\u250c\u2500\u2500(kali)-[~]\r\n"&&t3.buffer===t3.visible+"\u2514\u2500$ ",JSON.stringify(t3.visible))
eq("notice: a job that ends inside the prompt keeps covering it",t3.jobHistory[0].endIdx,30+"\x1b[0m\x1b[1;32mChain done\x1b[0m\n".length)
check("notice: no session -> false (the toast and the bell still have it)",new Function("termState","termFindTab",termFns+";return termPrintNotice")({activeId:null},()=>null)("s",["x"])===false)
check("notice: terminal.js never writes it with a bridge call",!/bridgeCall|termSend/.test(termFns))

// ---- b) long status pills wrap instead of being cut off
const pill=rule(COMPONENTS,".status-island")
check("pill: wraps, capped width, no nowrap and no max-width animation from 0",/white-space:normal/.test(pill)&&/max-width:min\(520px,calc\(100% - 32px\)\)/.test(pill)&&/width:max-content/.test(pill)&&!/nowrap/.test(pill)&&!/max-width:0/.test(pill)&&!/max-width 260ms/.test(pill),pill)
check("pill: the shown state no longer clamps to 420px",!/max-width:420px/.test(rule(COMPONENTS,".status-island.show")))
check("pill: a multi-line pill gets a card radius",/\.status-island\.status-island-multi\{border-radius:14px/.test(COMPONENTS)&&/classList\.toggle\("status-island-multi",host\.offsetHeight>40\)/.test(ISLAND))
check("pill: full text as a tooltip too",/host\.title=message\|\|""/.test(ISLAND))
const I=require("../../UI/js/components/status-island.js")
eq("pill: long messages stay up longer, capped at 9 s",[I.statusIslandDuration("short"),I.statusIslandDuration("x".repeat(110)),I.statusIslandDuration("x".repeat(1000))],[3200,5200,9000])

// ---- c) the Commands table fits its card
const cmdCell=rule(COMMANDS,".cmds-cell-command")
check("commands: the command column takes the leftover width (ellipsis idiom), no fixed 320px",/width:100%/.test(cmdCell)&&/max-width:0/.test(cmdCell)&&/min-width:140px/.test(cmdCell)&&!/320px/.test(cmdCell)&&/text-overflow:ellipsis/.test(cmdCell),cmdCell)

check("commands: with less room the least needed columns go before the table scrolls sideways",/\.cmds-table-wrap\{container-type:inline-size;container-name:cmds-table\}/.test(COMMANDS)&&/@container cmds-table \(max-width:1100px\)\{\.cmds-table :is\(th,td\):is\(:nth-child\(5\),:nth-child\(7\)\)\{display:none\}\}/.test(COMMANDS)&&/@container cmds-table \(max-width:900px\)/.test(COMMANDS)&&/@container cmds-table \(max-width:720px\)/.test(COMMANDS))
const HEAD=read("UI","pages","commands.html")
eq("commands: the hidden columns are Category, Sub Category, Description and Tags",[4,5,7,8].map((n)=>(HEAD.match(/<th[^>]*>[^<]*<\/th>/g)||[])[n-1].replace(/<[^>]+>/g,"")),["Category","Sub Category","Description","Tags"])
// ---- d) the diagram view in a narrow room
eq("compact: below 960 px of room",[C.chainsFlowIsCompact(800),C.chainsFlowIsCompact(959),C.chainsFlowIsCompact(960),C.chainsFlowIsCompact(1400),C.chainsFlowIsCompact(0)],[true,true,false,false,false])
eq("refit: on a panel-sized jump or a mode change, not on small drags or the first size",[C.chainsFlowNeedsRefit(1180,800,false),C.chainsFlowNeedsRefit(800,1180,false),C.chainsFlowNeedsRefit(1180,1170,false),C.chainsFlowNeedsRefit(1000,950,true),C.chainsFlowNeedsRefit(0,800,true)],[true,true,false,true,false])
check("compact: watched per view and disconnected with it",/st\.view=\{host:host,root:root,editor:editor,inspector:inspector,run:run\}\nchainsFlowWatchSpace\(st\.view\)/.test(FLOW)&&/if\(v\.spaceWatch\)\{try\{v\.spaceWatch\.disconnect\(\)\}catch\(_\)\{\}\}/.test(FLOW))
check("compact: the selection drives the inspector overlay",/root\.classList\.toggle\("cf-has-sel",!!\(ids&&ids\.length===1\)\)/.test(FLOW))
check("compact css: icon-only palette, inspector over the canvas only with a selection",/\.cf-compact \.flow-palette\{flex-basis:46px/.test(PANELS)&&/\.cf-compact \.flow-palette-label\{display:none\}/.test(PANELS)&&/\.cf-compact \.cf-side\{position:absolute;top:0;right:0;bottom:0/.test(PANELS)&&/\.cf-compact:not\(\.cf-has-sel\) \.cf-side\{display:none\}/.test(PANELS)&&/\.cf-compact \.cf-main\{position:relative\}/.test(PANELS))
check("line endings: LF only",[FLOW,TERM,ISLAND,COMPONENTS,COMMANDS,PANELS,fs.readFileSync(__filename,"utf8")].every((t)=>t.indexOf("\r")<0))
console.log("ux_fit_and_feedback: "+passed+" passed, "+failed+" failed")
process.exit(failed?1:0)
})().catch((err)=>{console.error(err);process.exit(1)})
