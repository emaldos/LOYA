// Chain diagrams: the run log viewer. flowLogOpen({runId,name,titles,bridge,toast,live}) opens a modal over the app with
// search (matches highlighted), a level filter, a node filter, "Group by node", Copy, Export and a live tail that stops
// following when the user scrolls up. The pure parts (filtering, grouping, highlight segments, the follow decision, chunking)
// are at the top and exported for tests/js/flow_log.js. Log text comes from command output and scanned hosts: every string
// goes through flowLogEscape before it reaches the DOM. Needs nothing but the bridge; flow-rules.js is optional.
const FLOW_LOG_POLL_MS=900
const FLOW_LOG_CHUNK=400
const FLOW_LOG_DOM_MAX=4000
const FLOW_LOG_LEVELS=[["all","All"],["error","Errors"],["warn","Warnings"],["info","Info"]]
// ---- pure helpers
function flowLogEscape(value){
return String(value===undefined||value===null?"":value).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")
}
function flowLogLevel(level){
const l=String(level||"").toLowerCase()
return l==="error"||l==="err"||l==="fatal"?"error":l==="warn"||l==="warning"?"warn":"info"
}
// One entry in a fixed shape, whatever the bridge sent.
function flowLogNormalize(entry,titles){
const e=entry&&typeof entry==="object"?entry:{}
const node=e.node===undefined||e.node===null?"":String(e.node)
const known=titles&&node&&titles[node]
return {seq:Number(e.seq)||0,ts:e.ts?String(e.ts):"",node:node,title:String(e.title||(known&&known.title)||node||""),level:flowLogLevel(e.level),kind:String(e.kind||""),text:String(e.text===undefined||e.text===null?"":e.text)}
}
// The fallback when flows.run_log does not exist: the run status events are the log.
function flowLogFromEvents(events,titles){
return (Array.isArray(events)?events:[]).filter((e)=>e&&typeof e==="object").map((e)=>flowLogNormalize(e,titles))
}
// Appends the entries of a poll that are newer than what is already there (by seq). -> the same array, grown.
function flowLogMerge(list,fresh){
const out=Array.isArray(list)?list:[]
let last=out.length?out[out.length-1].seq:0
;(Array.isArray(fresh)?fresh:[]).forEach((e)=>{if(e&&e.seq>last){out.push(e);last=e.seq}})
return out
}
function flowLogWords(query){
return String(query||"").toLowerCase().split(/\s+/).filter(Boolean)
}
// filter={level:"all"|"error"|"warn"|"info",node:""|id,query:"words"}: every word must be in the text, the node title or the kind.
function flowLogFilter(entries,filter){
const f=filter||{}
const level=f.level&&f.level!=="all"?String(f.level):""
const node=f.node?String(f.node):""
const words=flowLogWords(f.query)
const list=Array.isArray(entries)?entries:[]
if(!level&&!node&&!words.length)return list
return list.filter((e)=>{
if(level&&e.level!==level)return false
if(node&&e.node!==node)return false
if(!words.length)return true
const hay=(e.text+"\n"+e.title+"\n"+e.kind).toLowerCase()
return words.every((w)=>hay.indexOf(w)>=0)
})
}
function flowLogCounts(entries){
const c={all:0,error:0,warn:0,info:0}
;(Array.isArray(entries)?entries:[]).forEach((e)=>{c.all++;c[e.level]=(c[e.level]||0)+1})
return c
}
// The nodes that have entries, in order of first appearance: [{node,title,count}].
function flowLogNodes(entries){
const out=[],by={}
;(Array.isArray(entries)?entries:[]).forEach((e)=>{
if(!e.node)return
if(!by[e.node]){by[e.node]={node:e.node,title:e.title||e.node,count:0};out.push(by[e.node])}
by[e.node].count++
})
return out
}
// Group by node, groups in order of first appearance; entries without a node form the "Run" group.
function flowLogGroup(entries){
const out=[],by={}
;(Array.isArray(entries)?entries:[]).forEach((e)=>{
const key=e.node||""
if(!by[key]){by[key]={node:key,title:key?(e.title||key):"Run",entries:[],errors:0,warnings:0};out.push(by[key])}
by[key].entries.push(e)
if(e.level==="error")by[key].errors++
else if(e.level==="warn")by[key].warnings++
})
return out
}
// Splits text into [{text,hit}] so that every occurrence of a search word can be wrapped in <mark>. Case-insensitive,
// overlapping matches are merged, and no regular expression is built from what the user typed.
function flowLogSegments(text,query){
const src=String(text===undefined||text===null?"":text)
const words=flowLogWords(query)
if(!words.length||!src)return [{text:src,hit:false}]
const low=src.toLowerCase(),spans=[]
words.forEach((w)=>{let at=low.indexOf(w);while(at>=0){spans.push([at,at+w.length]);at=low.indexOf(w,at+w.length)}})
if(!spans.length)return [{text:src,hit:false}]
spans.sort((a,b)=>a[0]-b[0]||a[1]-b[1])
const merged=[spans[0].slice()]
for(let i=1;i<spans.length;i++){const lastSpan=merged[merged.length-1];if(spans[i][0]<=lastSpan[1])lastSpan[1]=Math.max(lastSpan[1],spans[i][1]);else merged.push(spans[i].slice())}
const out=[];let pos=0
merged.forEach((s)=>{if(s[0]>pos)out.push({text:src.slice(pos,s[0]),hit:false});out.push({text:src.slice(s[0],s[1]),hit:true});pos=s[1]})
if(pos<src.length)out.push({text:src.slice(pos),hit:false})
return out
}
function flowLogMarkHtml(text,query){
return flowLogSegments(text,query).map((s)=>s.hit?"<mark>"+flowLogEscape(s.text)+"</mark>":flowLogEscape(s.text)).join("")
}
// Follow the tail? Only while the view is at (or within `slack` px of) the bottom.
function flowLogShouldStick(scrollTop,clientHeight,scrollHeight,slack){
const s=Number(slack)>=0?Number(slack):24
return Number(scrollTop)+Number(clientHeight)>=Number(scrollHeight)-s
}
// Which part of a long list goes into the DOM: the newest `max`, with the number of older ones left out.
function flowLogWindow(total,max,extra){
const cap=Math.max(1,Math.floor(Number(max)||FLOW_LOG_DOM_MAX))+Math.max(0,Math.floor(Number(extra)||0))
const n=Math.max(0,Math.floor(Number(total)||0))
return {start:Math.max(0,n-cap),hidden:Math.max(0,n-cap)}
}
function flowLogClock(ts){
const t=ts?Date.parse(String(ts)):NaN
if(isNaN(t))return ""
const d=new Date(t),two=(v)=>("0"+v).slice(-2)
return two(d.getHours())+":"+two(d.getMinutes())+":"+two(d.getSeconds())
}
function flowLogRowHtml(entry,query,hideNode){
const e=entry||{}
return '<div class="fl-row fl-'+flowLogLevel(e.level)+'"><span class="fl-time">'+flowLogEscape(flowLogClock(e.ts))+'</span><span class="fl-level">'+(e.level==="error"?"ERROR":e.level==="warn"?"WARN":"info")+"</span>"+(e.node&&!hideNode?'<span class="fl-node">'+flowLogMarkHtml(e.title||e.node,query)+"</span>":"")+'<span class="fl-text">'+flowLogMarkHtml(e.text,query)+"</span></div>"
}
function flowLogGroupHeadHtml(group){
const g=group||{}
return '<div class="fl-group"><span class="fl-group-title">'+flowLogEscape(g.title)+'</span><span class="fl-group-count">'+(g.entries?g.entries.length:0)+" line"+(g.entries&&g.entries.length===1?"":"s")+"</span>"+(g.errors?'<span class="fl-pill fl-pill-error">'+g.errors+" error"+(g.errors===1?"":"s")+"</span>":"")+(g.warnings?'<span class="fl-pill fl-pill-warn">'+g.warnings+" warning"+(g.warnings===1?"":"s")+"</span>":"")+"</div>"
}
// The plain text of a (filtered) view, for Copy and for the export fallback.
function flowLogText(entries,grouped){
const line=(e)=>[flowLogClock(e.ts),e.level==="error"?"ERROR":e.level==="warn"?"WARN ":"info ",e.node?"["+(e.title||e.node)+"]":"",e.text].filter((p)=>p!=="").join(" ")
if(!grouped)return (Array.isArray(entries)?entries:[]).map(line).join("\n")
return flowLogGroup(entries).map((g)=>"== "+g.title+" ==\n"+g.entries.map(line).join("\n")).join("\n\n")
}
function flowLogBridgeMissing(err){
return /bridge method missing/i.test(err&&err.message?String(err.message):String(err||""))
}
// ---- the viewer
let flowLogCurrent=null
function flowLogClose(){
const v=flowLogCurrent
if(!v)return
flowLogCurrent=null
v.closed=true
if(v.timer)clearTimeout(v.timer)
if(v.renderTimer)clearTimeout(v.renderTimer)
document.removeEventListener("keydown",v.onKey,true)
if(v.el.parentNode)v.el.parentNode.removeChild(v.el)
if(typeof uiSelectClose==="function")uiSelectClose()
document.body.classList.remove("fl-open")
}
function flowLogOpen(opts){
const o=opts||{}
flowLogClose()
const bridge=(path,args)=>typeof o.bridge==="function"?Promise.resolve().then(()=>o.bridge(path,args||[])):typeof bridgeCall==="function"?bridgeCall(path,args||[]):Promise.reject(new Error("bridge unavailable"))
const toast=(msg,kind)=>{if(typeof o.toast==="function")o.toast(msg,kind);else if(typeof showToast==="function")showToast(msg,kind)}
const v={runId:String(o.runId||""),entries:[],next:0,live:o.live!==false,useEvents:false,filter:{level:"all",node:"",query:""},grouped:false,stick:true,extra:0,hidden:0,shown:[],closed:false,timer:null,renderTimer:null,renderToken:0,total:0}
const overlay=document.createElement("div")
overlay.className="confirm-overlay fl-overlay"
overlay.innerHTML='<div class="confirm-box glass-panel fl-box" role="dialog" aria-label="Run log"><div class="fl-head"><div class="fl-titles"><div class="fl-title"></div><div class="fl-sub"></div></div><button type="button" class="fl-btn" data-fl="copy" title="Copy what is shown (the whole log when nothing is filtered)"><i class="icon icon-copy"></i><span>Copy</span></button><button type="button" class="fl-btn" data-fl="export" title="Save the whole log as a text file"><i class="icon icon-file"></i><span>Export</span></button><button type="button" class="fl-btn" data-fl="export-json" title="Save the whole log as JSON"><span>JSON</span></button><button type="button" class="fl-icon-btn" data-fl="close" title="Close (Esc)" aria-label="Close"><i class="icon icon-close"></i></button></div>'+
'<div class="fl-tools"><div class="fl-search"><i class="icon icon-search"></i><input type="text" class="fl-query" placeholder="Search the log..." spellcheck="false" autocomplete="off"></div><div class="fl-levels">'+FLOW_LOG_LEVELS.map((l)=>'<button type="button" class="fl-level-btn" data-fl="level" data-level="'+l[0]+'"><span>'+l[1]+'</span><span class="fl-count"></span></button>').join("")+'</div><select class="fl-node-pick" aria-label="Node"><option value="">All nodes</option></select><label class="fl-check"><input type="checkbox" class="fl-group-toggle"><span>Group by node</span></label></div>'+
'<div class="fl-body"><div class="fl-list" tabindex="0"></div><button type="button" class="fl-jump fl-hidden" data-fl="jump">Jump to latest</button></div><div class="fl-foot"></div></div>'
v.el=overlay
const $=(sel)=>overlay.querySelector(sel)
const list=$(".fl-list"),foot=$(".fl-foot"),jump=$(".fl-jump"),pick=$(".fl-node-pick")
$(".fl-title").textContent=(o.name?String(o.name)+" - ":"")+"run log"
function paintTools(){
const counts=flowLogCounts(v.entries)
overlay.querySelectorAll(".fl-level-btn").forEach((b)=>{
b.classList.toggle("active",b.dataset.level===v.filter.level)
b.querySelector(".fl-count").textContent=String(counts[b.dataset.level]||0)
})
const nodes=flowLogNodes(v.entries)
const sig=nodes.map((n)=>n.node+":"+n.count).join("|")
if(pick.dataset.sig!==sig){
pick.dataset.sig=sig
pick.innerHTML='<option value="">All nodes</option>'+nodes.map((n)=>'<option value="'+flowLogEscape(n.node)+'">'+flowLogEscape(n.title)+" ("+n.count+")</option>").join("")
pick.value=v.filter.node
if(pick.value!==v.filter.node){v.filter.node="";pick.value=""}
}
$(".fl-sub").textContent=(v.live?"Live - ":"")+counts.all+" line"+(counts.all===1?"":"s")+(counts.error?", "+counts.error+" error"+(counts.error===1?"":"s"):"")+(counts.warn?", "+counts.warn+" warning"+(counts.warn===1?"":"s"):"")
}
function paintFoot(hidden){
const filtered=v.shown.length!==v.entries.length
foot.innerHTML=(hidden?'<button type="button" class="fl-btn" data-fl="earlier">Show '+Math.min(hidden,FLOW_LOG_DOM_MAX)+" earlier lines</button><span>"+hidden+" older lines are not drawn</span>":"")+"<span>"+(filtered?v.shown.length+" of "+v.entries.length+" lines match":v.entries.length+" lines")+"</span>"
}
// Full redraw, in chunks so a long log never blocks the page: each chunk is one insertAdjacentHTML, then the next timer tick.
function redraw(){
const token=++v.renderToken
if(v.renderTimer){clearTimeout(v.renderTimer);v.renderTimer=null}
v.shown=flowLogFilter(v.entries,v.filter)
const win=flowLogWindow(v.shown.length,FLOW_LOG_DOM_MAX,v.extra)
const rows=v.shown.slice(win.start)
list.innerHTML=""
v.hidden=win.hidden
paintTools()
paintFoot(win.hidden)
if(!rows.length){list.innerHTML='<div class="fl-empty">'+(v.entries.length?"Nothing matches these filters.":v.live?"Waiting for the first log line...":"This run has no log.")+"</div>";return}
let parts
if(v.grouped){
parts=[]
flowLogGroup(rows).forEach((g)=>{parts.push(flowLogGroupHeadHtml(g));g.entries.forEach((e)=>parts.push(flowLogRowHtml(e,v.filter.query,true)))})
}else parts=rows.map((e)=>flowLogRowHtml(e,v.filter.query,false))
let at=0
const step=()=>{
v.renderTimer=null
if(v.closed||token!==v.renderToken)return
list.insertAdjacentHTML("beforeend",parts.slice(at,at+FLOW_LOG_CHUNK).join(""))
at+=FLOW_LOG_CHUNK
if(v.stick)list.scrollTop=list.scrollHeight
if(at<parts.length)v.renderTimer=setTimeout(step,0)
}
step()
}
// New lines while live: append when the view is a plain tail, otherwise redraw (grouping and windows shift).
function append(fresh){
if(!fresh.length)return
paintTools()
const match=flowLogFilter(fresh,v.filter)
// unfiltered, the shown list IS the entry list (flowLogFilter returns it as it is) and already has the new lines
if(v.shown!==v.entries)v.shown=v.shown.concat(match)
if(v.grouped||v.renderTimer||list.querySelector(".fl-empty")||list.childElementCount+match.length>FLOW_LOG_DOM_MAX+v.extra+FLOW_LOG_CHUNK){redraw();return}
if(match.length)list.insertAdjacentHTML("beforeend",match.map((e)=>flowLogRowHtml(e,v.filter.query,false)).join(""))
paintFoot(v.hidden)
if(v.stick)list.scrollTop=list.scrollHeight
else jump.classList.remove("fl-hidden")
}
function take(entries){
const before=v.entries.length
flowLogMerge(v.entries,entries)
return v.entries.slice(before)
}
function schedule(){
if(v.closed||!v.live)return
v.timer=setTimeout(poll,FLOW_LOG_POLL_MS)
}
function fromStatus(){
return bridge("flows.run_status",[v.runId,0]).then((status)=>{
if(v.closed)return
const s=status||{}
const fresh=take(flowLogFromEvents(s.events,o.titles))
v.live=["done","failed","cancelled","timeout"].indexOf(String(s.state||""))<0
if(v.first){v.first=false;redraw()}else append(fresh)
if(!v.live)paintTools()
schedule()
})
}
function poll(){
v.timer=null
if(v.closed)return
const job=v.useEvents?fromStatus():bridge("flows.run_log",[v.runId,v.next,2000]).then((res)=>{
if(v.closed)return
const r=res||{}
const fresh=take((Array.isArray(r.entries)?r.entries:[]).map((e)=>flowLogNormalize(e,o.titles)))
if(Number(r.next)>v.next)v.next=Number(r.next)
else if(v.entries.length)v.next=Math.max(v.next,v.entries[v.entries.length-1].seq)
v.total=Number(r.total)||v.entries.length
const more=Array.isArray(r.entries)&&r.entries.length>=2000
v.live=r.live===true
if(v.first){v.first=false;redraw()}else append(fresh)
if(!v.live)paintTools()
if(more){v.timer=setTimeout(poll,0);return}
schedule()
},(err)=>{
if(!flowLogBridgeMissing(err))throw err
v.useEvents=true
return fromStatus()
})
job.catch((err)=>{
if(v.closed)return
if(v.first){v.first=false;redraw()}
foot.textContent="Could not load the log: "+(err&&err.message?err.message:"unknown error")
if(v.live)v.timer=setTimeout(poll,FLOW_LOG_POLL_MS*4)
})
}
function copyText(text){
const done=()=>toast("Log copied")
const viaField=()=>{const ta=document.createElement("textarea");ta.value=text;ta.style.position="fixed";ta.style.opacity="0";overlay.appendChild(ta);ta.select();try{document.execCommand("copy");done()}catch(_){toast("Could not copy the log","error")}overlay.removeChild(ta)}
if(navigator.clipboard&&navigator.clipboard.writeText)navigator.clipboard.writeText(text).then(done).catch(viaField)
else viaField()
}
function doCopy(){
const filtered=v.grouped||v.filter.level!=="all"||v.filter.node||v.filter.query
if(filtered||v.useEvents){copyText(flowLogText(v.shown,v.grouped));return}
bridge("flows.run_log_text",[v.runId]).then((text)=>copyText(String(text||"")),()=>copyText(flowLogText(v.entries,false)))
}
function doExport(fmt){
bridge("flows.run_log_export",[v.runId,fmt]).then((res)=>{if(res&&res.ok&&res.path)toast("Log saved to "+res.path)},(err)=>{
if(!flowLogBridgeMissing(err))throw err
return bridge("terminal.save_output_to_file",[fmt==="json"?JSON.stringify(v.entries,null,2):flowLogText(v.entries,false)]).then((path)=>{if(path)toast("Log saved to "+path)})
}).catch((err)=>toast(err&&err.message?err.message:"Could not save the log","error"))
}
let typing=null
$(".fl-query").addEventListener("input",(e)=>{
if(typing)clearTimeout(typing)
const value=e.target.value
typing=setTimeout(()=>{typing=null;if(v.closed)return;v.filter.query=value;v.extra=0;redraw()},160)
})
pick.addEventListener("change",()=>{v.filter.node=pick.value;v.extra=0;redraw()})
$(".fl-group-toggle").addEventListener("change",(e)=>{v.grouped=!!e.target.checked;redraw()})
list.addEventListener("scroll",()=>{
v.stick=flowLogShouldStick(list.scrollTop,list.clientHeight,list.scrollHeight)
if(v.stick)jump.classList.add("fl-hidden")
})
overlay.addEventListener("click",(e)=>{
if(e.target===overlay){flowLogClose();return}
const btn=e.target.closest&&e.target.closest("[data-fl]")
if(!btn)return
const what=btn.dataset.fl
if(what==="close")flowLogClose()
else if(what==="level"){v.filter.level=btn.dataset.level;v.extra=0;redraw()}
else if(what==="jump"){v.stick=true;jump.classList.add("fl-hidden");list.scrollTop=list.scrollHeight}
else if(what==="earlier"){v.extra+=FLOW_LOG_DOM_MAX;v.stick=false;redraw()}
else if(what==="copy")doCopy()
else if(what==="export")doExport("text")
else if(what==="export-json")doExport("json")
})
v.onKey=(e)=>{
if(e.key==="Escape"){e.preventDefault();e.stopPropagation();flowLogClose()}
else if((e.ctrlKey||e.metaKey)&&String(e.key).toLowerCase()==="f"){e.preventDefault();e.stopPropagation();$(".fl-query").focus();$(".fl-query").select()}
}
document.addEventListener("keydown",v.onKey,true)
document.body.appendChild(overlay)
// the app's select popover normally sits below dialogs: flow-panels.css lifts it while the viewer is open
document.body.classList.add("fl-open")
flowLogCurrent=v
v.first=true
list.innerHTML='<div class="fl-empty">Loading the log...</div>'
poll()
setTimeout(()=>{if(!v.closed)$(".fl-query").focus()},0)
return {close:flowLogClose,el:overlay,state:v}
}
if(typeof module!=="undefined"&&module.exports)module.exports={FLOW_LOG_POLL_MS,FLOW_LOG_CHUNK,FLOW_LOG_DOM_MAX,FLOW_LOG_LEVELS,flowLogEscape,flowLogLevel,flowLogNormalize,flowLogFromEvents,flowLogMerge,flowLogWords,flowLogFilter,flowLogCounts,flowLogNodes,flowLogGroup,flowLogSegments,flowLogMarkHtml,flowLogShouldStick,flowLogWindow,flowLogClock,flowLogRowHtml,flowLogGroupHeadHtml,flowLogText,flowLogBridgeMissing,flowLogOpen,flowLogClose}
