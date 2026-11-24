// Chain diagrams: running a diagram. The pre-run confirmation (built from flows.plan), the live run bar, the event log,
// the per-node output viewer, the dry-run report and the run history. Needs flow-rules.js loaded first.
// Command text, output and names come from the graph and from scanned hosts: every string goes through flowEscape
// (or textContent) before it reaches the DOM.
const FLOW_RUN_POLL_MS=700
const FLOW_RUN_BACKOFF_MAX_MS=10000
const FLOW_RUN_MAX_EVENTS=2000
const FLOW_RUN_FINAL_STATES=["done","failed","cancelled","timeout"]
const FLOW_RUN_STATE_LABELS={running:"Running",paused:"Paused",waiting_approval:"Waiting for approval",done:"Finished",failed:"Failed",cancelled:"Stopped",timeout:"Timed out"}
const FLOW_RUN_NODE_LABELS={pending:"Not reached",running:"Running",success:"Success",fail:"Failed",skipped:"Skipped",waiting:"Waiting",planned:"Would run"}
// ---- pure helpers (exported for tests/js/flow_panels.js)
function flowRunIsFinal(state){
return FLOW_RUN_FINAL_STATES.indexOf(state)!==-1
}
// Delay before the next status poll: the normal beat, doubling after each failed call up to a cap.
function flowRunBackoff(failures){
const n=Math.max(0,Math.floor(Number(failures)||0))
if(!n)return FLOW_RUN_POLL_MS
return Math.min(FLOW_RUN_BACKOFF_MAX_MS,FLOW_RUN_POLL_MS*Math.pow(2,Math.min(n,10)))
}
function flowRunErrorText(err,fallback){
const text=err&&err.message?String(err.message):typeof err==="string"?err:""
return text||fallback||"Something went wrong"
}
function flowRunDuration(ms){
const n=Number(ms)
if(!isFinite(n)||n<0)return ""
if(n<1000)return Math.round(n)+" ms"
if(n<10000)return (n/1000).toFixed(1)+" s"
const s=Math.floor(n/1000)
if(s<60)return s+" s"
const m=Math.floor(s/60)
if(m<60)return m+"m "+("0"+(s%60)).slice(-2)+"s"
return Math.floor(m/60)+"h "+("0"+(m%60)).slice(-2)+"m"
}
function flowRunParseTime(value){
if(!value)return NaN
return Date.parse(String(value))
}
function flowRunClock(ts){
const t=flowRunParseTime(ts)
if(isNaN(t))return ""
const d=new Date(t)
const two=(v)=>("0"+v).slice(-2)
return two(d.getHours())+":"+two(d.getMinutes())+":"+two(d.getSeconds())
}
function flowRunElapsedMs(status,now){
const s=status||{}
const start=flowRunParseTime(s.started_at)
if(isNaN(start))return null
const end=s.ended_at?flowRunParseTime(s.ended_at):NaN
return Math.max(0,(isNaN(end)?(now===undefined?Date.now():now):end)-start)
}
function flowRunLastSeq(status){
const s=status||{}
let seq=0
;(Array.isArray(s.events)?s.events:[]).forEach((e)=>{if(e&&Number(e.seq)>seq)seq=Number(e.seq)})
// The status carries the run's own counter (events and node changes share it): everything up to it has been delivered.
if(Number(s.seq)>seq)seq=Number(s.seq)
return seq
}
// run_status(since) only returns the new events: keep the ones already seen, append the new ones, cap the list.
function flowRunMergeStatus(prev,next){
if(!next||typeof next!=="object")return prev||null
const out=Object.assign({},next)
const same=prev&&prev.run_id===next.run_id
const old=same&&Array.isArray(prev.events)?prev.events:[]
const last=flowRunLastSeq({events:old})
const fresh=(Array.isArray(next.events)?next.events:[]).filter((e)=>e&&Number(e.seq)>last)
let events=old.concat(fresh)
if(events.length>FLOW_RUN_MAX_EVENTS)events=events.slice(events.length-FLOW_RUN_MAX_EVENTS)
out.events=events
if(!out.nodes||typeof out.nodes!=="object")out.nodes={}
// A poll with `since` may leave out the output of nodes that did not change (or leave those nodes out entirely):
// keep what the earlier polls delivered.
if(same&&prev.nodes&&typeof prev.nodes==="object"){
const merged=Object.assign({},prev.nodes)
Object.keys(out.nodes).forEach((id)=>{
const rec=out.nodes[id],before=prev.nodes[id]
merged[id]=rec&&typeof rec==="object"&&rec.output===undefined&&before&&before.output!==undefined?Object.assign({},rec,{output:before.output}):rec
})
out.nodes=merged
}
if(!Array.isArray(out.edges_taken))out.edges_taken=[]
return out
}
function flowRunTitles(graph){
const map={}
;((graph&&graph.nodes)||[]).forEach((n)=>{if(n&&n.id)map[n.id]={title:String(n.title||n.type||n.id),type:String(n.type||"")}})
return map
}
// Everything the run bar shows, derived from one status object.
function flowRunStatusView(status,now,titles){
const s=status||{}
const state=String(s.state||"")
const dry=s.mode==="dry"
const final=flowRunIsFinal(state)
const counts={total:0,success:0,fail:0,skipped:0,running:0,waiting:0,planned:0,pending:0}
Object.keys(s.nodes||{}).forEach((id)=>{
const rec=s.nodes[id]||{}
counts.total++
if(Object.prototype.hasOwnProperty.call(counts,rec.state))counts[rec.state]++
})
const settled=counts.success+counts.fail+counts.skipped+counts.planned
const elapsed=flowRunElapsedMs(s,now)
const known=titles||{}
const current=s.current&&known[s.current]?known[s.current].title:(s.current||"")
let label=FLOW_RUN_STATE_LABELS[state]||state||"Starting"
// A pause only takes effect between nodes: until then the engine reports pausing.
const pausing=!final&&!dry&&s.pausing===true&&state!=="paused"
if(pausing)label="Pausing..."
if(dry)label=final?(state==="done"?"Dry run finished":"Dry run "+label.toLowerCase()):"Dry run"
const parts=[]
if(!final&&current)parts.push(current)
if(final&&!dry)parts.push([counts.success?counts.success+" ok":"",counts.fail?counts.fail+" failed":"",counts.skipped?counts.skipped+" skipped":""].filter(Boolean).join(", "))
if(final&&dry)parts.push(counts.planned+" node"+(counts.planned===1?"":"s")+" would run - nothing was executed")
if(elapsed!==null&&!dry)parts.push(flowRunDuration(elapsed))
if(s.target)parts.push("on "+s.target)
if(s.reason&&final&&state!=="done")parts.push(String(s.reason))
const cls=state==="done"?"done":state==="failed"||state==="timeout"?"failed":state==="cancelled"?"stopped":state==="paused"||state==="waiting_approval"?"paused":"running"
return {state:state,cls:cls,label:label,sub:parts.filter(Boolean).join(" - "),name:String(s.name||""),dry:dry,final:final,active:!final&&!!state,
pausing:pausing,canPause:!dry&&state==="running"&&!pausing,canResume:!dry&&state==="paused",canStop:!final&&!!state,
approval:state==="waiting_approval"&&s.approval&&s.approval.node?{node:String(s.approval.node),message:String(s.approval.message||""),title:known[s.approval.node]?known[s.approval.node].title:String(s.approval.node)}:null,
counts:counts,percent:counts.total?Math.round(settled*100/counts.total):0,current:s.current||null,elapsed:elapsed,reason:String(s.reason||"")}
}
// flows.plan -> what the confirmation dialog shows and whether Run may be pressed.
function flowRunPlanModel(plan,opts){
const p=plan&&typeof plan==="object"?plan:{}
const o=opts||{}
const text=(v)=>v===undefined||v===null?"":String(v)
const commands=(Array.isArray(p.commands)?p.commands:[]).map((c)=>{
const resolved=text(c&&(c.resolved===undefined||c.resolved===null||c.resolved===""?c.text:c.resolved))
return {node:text(c&&c.node),title:text(c&&c.title),text:text(c&&c.text),resolved:resolved,missing:(c&&Array.isArray(c.missing)?c.missing:[]).map(text),destructive:!!(c&&c.destructive)||flowCommandIsDestructive(resolved)}
})
const groups=[]
const byNode={}
commands.forEach((c)=>{
if(!byNode[c.node]){byNode[c.node]={node:c.node,title:c.title||c.node,commands:[]};groups.push(byNode[c.node])}
byNode[c.node].commands.push(c)
})
const missing=[]
;(Array.isArray(p.missing)?p.missing:[]).map(text).concat(commands.reduce((all,c)=>all.concat(c.missing),[])).forEach((m)=>{if(m&&missing.indexOf(m)===-1)missing.push(m)})
const issue=(i)=>flowIssueText(i)
const errors=(Array.isArray(p.errors)?p.errors:[]).map(issue).filter(Boolean)
const warnings=(Array.isArray(p.warnings)?p.warnings:[]).map(issue).filter(Boolean)
const scripts=(Array.isArray(p.scripts)?p.scripts:[]).map((s)=>({node:text(s&&s.node),title:text(s&&s.title)||text(s&&s.node),language:text(s&&s.language)||"python",lines:Number(s&&s.lines)||0,network:s&&typeof s.network==="boolean"?s.network:null}))
// script_policy: how scripts may run here. mode "sandboxed" | "allow"; source "global" (the app setting) or "diagram";
// unsandboxed = they will run with no isolation; blocked = the policy wants a sandbox and this system has none.
const sp=p.script_policy&&typeof p.script_policy==="object"?p.script_policy:null
const policy=sp?{mode:sp.mode==="allow"?"allow":"sandboxed",source:sp.source==="diagram"?"diagram":"global",unsandboxed:sp.unsandboxed===true,blocked:sp.blocked===true,ignored:(Array.isArray(p.warnings)?p.warnings:[]).some((w)=>w&&w.code==="script_isolation_ignored")}:null
let blockText=text(p.blocked)
if(!blockText&&policy&&policy.blocked&&scripts.length)blockText=flowRunPolicyBlockText(policy)
if(!blockText&&errors.length)blockText="The diagram has errors: "+errors.slice(0,3).join("; ")
if(!blockText&&missing.length)blockText="Fill these in on the live target first: "+missing.map((m)=>"{"+m+"}").join(", ")
const destructive=commands.filter((c)=>c.destructive).length
const box=p.sandbox&&typeof p.sandbox==="object"?{mode:text(p.sandbox.sandbox)||"none",networkIsolation:!!p.sandbox.network_isolation}:null
const count=commands.length
const bits=[count+" command"+(count===1?"":"s")]
if(scripts.length)bits.push(scripts.length+" script"+(scripts.length===1?"":"s"))
if(Number(p.approvals)>0)bits.push(Number(p.approvals)+" approval stop"+(Number(p.approvals)===1?"":"s"))
return {name:text(o.name),fromNode:o.from_node?text(o.from_node):"",target:text(p.target&&p.target.name),commands:commands,groups:groups,scripts:scripts,approvals:Number(p.approvals)||0,
missing:missing,errors:errors,warnings:warnings,blocked:!!blockText,blockText:blockText,aiMade:!!p.ai_made,needsReview:!!p.needs_review,destructive:destructive,
sandbox:box,policy:policy,fingerprint:text(p.fingerprint),
summary:bits.join(", "),runLabel:o.from_node?"Run from this node":"Run chain"}
}
// Why the script policy stops a run, and where to change it.
function flowRunPolicyBlockText(policy){
const p=policy||{}
if(p.ignored)return "This diagram has scripts, this system has no sandbox for them, and the app setting says \"Sandboxed only\". The diagram's own \"Allow unsandboxed scripts\" is ignored while it is AI-made or not reviewed: mark it as reviewed first, or change the app setting in Settings > Extensions > Chain diagrams."
return "This diagram has scripts, this system has no sandbox for them, and "+(p.source==="diagram"?"this diagram's Settings say":"the app setting says")+" \"Sandboxed only\". "+(p.source==="diagram"?"Open the diagram's Settings and choose \"Allow unsandboxed scripts\" (or \"Use app setting\")":"Go to Settings > Extensions > Chain diagrams and choose \"Allow unsandboxed scripts\", or set it for this diagram only in its Settings")+" if you accept scripts running with no isolation."
}
function flowRunCanStart(model,reviewed){
const m=model||{}
return !m.blocked&&(!m.needsReview||reviewed===true)
}
function flowRunScriptCode(graph){
const out={}
;((graph&&graph.nodes)||[]).forEach((n)=>{if(n&&n.type==="script"&&n.config)out[n.id]=String(n.config.code===undefined||n.config.code===null?"":n.config.code)})
return out
}
function flowRunConfirmHtml(model,codeByNode){
const m=model||{}
const code=codeByNode||{}
const E=flowEscape
let html='<div class="term-run-destination">'+(m.target?"Target <b>"+E(m.target)+"</b>. ":"No live target. ")+"Commands run in the background, not in a terminal session."+(m.fromNode?" Starts at the selected node and reuses the values of the last run.":"")+"</div>"
// A script-policy block gets its own banner below (why, and where to change it): no need to say it twice.
const policyBlock=!!(m.policy&&m.policy.blocked&&m.scripts&&m.scripts.length&&/sandbox/i.test(m.blockText||""))
if(m.blocked&&!policyBlock)html+='<div class="fr-banner fr-banner-block"><b>This chain cannot run yet.</b> '+E(m.blockText)+"</div>"
if(m.needsReview)html+='<div class="fr-banner fr-banner-ai"><b>'+(m.aiMade?"AI-made":"Imported")+' - review before running.</b> '+(m.aiMade?"An AI client built this chain and nobody has reviewed it yet.":"This chain was imported and nobody has reviewed it yet.")+' Read every command and script below.<label class="fr-ack"><input type="checkbox" data-fr="ack"><span>I reviewed this chain</span></label></div>'
if(m.destructive)html+='<div class="fr-banner fr-banner-danger">'+m.destructive+" command"+(m.destructive===1?" looks":"s look")+" destructive or privileged. Check "+(m.destructive===1?"it":"them")+" before you run.</div>"
if(m.scripts&&m.scripts.length&&m.policy){
if(m.policy.blocked)html+='<div class="fr-banner fr-banner-block fr-banner-sandbox"><b>This chain cannot run yet: its scripts are not allowed to run here.</b> '+E(flowRunPolicyBlockText(m.policy))+"</div>"
else if(m.policy.unsandboxed)html+='<div class="fr-banner fr-banner-danger fr-banner-sandbox"><b>Scripts will run with no isolation.</b> There is no sandbox on this system and '+(m.policy.source==="diagram"?"this diagram's Settings allow":"the app setting allows")+" unsandboxed scripts. They can read and change the same files as the app and always have network access. Read each script below before you run.</div>"
else html+='<div class="fr-plan-note fr-sandbox-note">Scripts run in a sandbox'+(m.sandbox&&m.sandbox.mode&&m.sandbox.mode!=="none"?" ("+E(m.sandbox.mode)+")":"")+", without network access unless a script node allows it.</div>"
}else if(m.scripts&&m.scripts.length&&m.sandbox){
if(m.sandbox.mode==="none")html+='<div class="fr-banner fr-banner-danger fr-banner-sandbox"><b>Scripts run with no isolation.</b> They can read and change the same files as the app. Read each script below before you run.</div>'
else html+='<div class="fr-plan-note fr-sandbox-note">Scripts run in a sandbox ('+E(m.sandbox.mode)+")"+(m.sandbox.networkIsolation?", without network access unless a script node allows it":"")+".</div>"
}
if(m.errors&&m.errors.length)html+='<ul class="term-risk-list fr-errors">'+m.errors.map((e)=>"<li>"+E(e)+"</li>").join("")+"</ul>"
html+='<div class="fr-plan-summary">'+E(m.summary||"")+"</div>"
html+='<div class="fr-plan">'
;(m.groups||[]).forEach((g)=>{
html+='<div class="fr-plan-node"><div class="fr-plan-title">'+E(g.title)+'<span class="fr-plan-id">'+E(g.node)+"</span></div>"+g.commands.map((c)=>'<div class="fr-plan-cmd'+(c.destructive?" is-destructive":"")+(c.missing.length?" is-missing":"")+'"><pre class="fr-plan-text"'+(c.text&&c.text!==c.resolved?' title="'+E(c.text)+'"':"")+">"+E(c.resolved)+"</pre>"+(c.destructive||c.missing.length?'<div class="fr-plan-flags">'+(c.destructive?'<span class="fr-flag fr-flag-danger">Destructive</span>':"")+c.missing.map((k)=>'<span class="fr-flag fr-flag-missing">Missing {'+E(k)+"}</span>").join("")+"</div>":"")+"</div>").join("")+"</div>"
})
;(m.scripts||[]).forEach((s)=>{
const body=Object.prototype.hasOwnProperty.call(code,s.node)?code[s.node]:null
html+='<details class="fr-plan-node fr-plan-script"><summary><span class="fr-plan-title">'+E(s.title)+'</span><span class="fr-flag fr-flag-script">'+E(s.language)+" script, "+s.lines+" line"+(s.lines===1?"":"s")+"</span>"+(s.network===null||s.network===undefined?"":'<span class="fr-flag '+(s.network?"fr-flag-net-on":"fr-flag-net-off")+'">network '+(s.network?"on":"off")+"</span>")+"</summary>"+(body===null?'<div class="fr-plan-note">Open the node to read its code.</div>':'<pre class="fr-plan-text fr-plan-code">'+E(body)+"</pre>")+"</details>"
})
if(!(m.groups||[]).length&&!(m.scripts||[]).length)html+='<div class="fr-plan-note">No commands or scripts on this path.</div>'
html+="</div>"
if(m.approvals)html+='<div class="fr-plan-note">The run pauses '+m.approvals+" time"+(m.approvals===1?"":"s")+" to ask for your approval.</div>"
if(m.warnings&&m.warnings.length)html+='<details class="fr-plan-warnings"><summary>'+m.warnings.length+" warning"+(m.warnings.length===1?"":"s")+"</summary><ul>"+m.warnings.map((w)=>"<li>"+E(w)+"</li>").join("")+"</ul></details>"
return html
}
// What the node output viewer shows for one node of a run.
function flowRunNodeView(status,nodeId,titles){
const s=status||{}
const rec=(s.nodes&&s.nodes[nodeId])||null
const known=(titles&&titles[nodeId])||{title:nodeId,type:""}
if(!rec)return {id:nodeId,title:known.title,type:known.type,found:false,state:"",stateLabel:"Not part of this run",meta:"",error:"",resolved:[],tabs:{stdout:"",stderr:"",parsed:"",trace:[]},vars:"",tab:"stdout",canRerun:false}
const out=rec.output&&typeof rec.output==="object"?rec.output:{}
const text=(v)=>v===undefined||v===null?"":typeof v==="string"?v:flowValueText(v)
const pretty=(v)=>{
if(v===undefined||v===null||v==="")return ""
if(typeof v==="string")return v
try{return JSON.stringify(v,null,2)}catch(_){return String(v)}
}
const meta=[]
if(out.exit_code!==undefined&&out.exit_code!==null)meta.push("exit "+out.exit_code)
if(rec.duration_ms)meta.push(flowRunDuration(rec.duration_ms))
if(rec.visits>1)meta.push(rec.visits+" visits")
if(rec.branch)meta.push("took "+rec.branch)
const trace=Array.isArray(out.trace)?out.trace:[]
const stdout=text(out.stdout),stderr=text(out.stderr)
const tab=trace.length?"trace":rec.state==="fail"&&stderr&&!stdout?"stderr":"stdout"
const final=flowRunIsFinal(s.state)
return {id:nodeId,title:known.title,type:known.type,found:true,state:String(rec.state||""),stateLabel:FLOW_RUN_NODE_LABELS[rec.state]||String(rec.state||""),meta:meta.join(" - "),error:text(rec.error),
resolved:(Array.isArray(out.resolved)?out.resolved:[]).map(text),tabs:{stdout:stdout,stderr:stderr,parsed:pretty(out.parsed),trace:trace},vars:pretty(out.vars_set),tab:tab,
canRerun:final&&s.mode==="run"&&known.type!=="start"&&known.type!=="comment"&&s.playbook_id!==undefined&&s.playbook_id!==null}
}
function flowRunTraceHtml(trace){
const list=Array.isArray(trace)?trace:[]
if(!list.length)return '<div class="fr-empty">No decision was recorded for this node.</div>'
const E=flowEscape
return list.map((b)=>{
const conds=b&&Array.isArray(b.conditions)?b.conditions:[]
return '<div class="fr-trace-branch'+(b&&b.matched?" matched":"")+'"><div class="fr-trace-head"><span class="fr-mono">'+E(b&&b.branch)+'</span><span class="fr-flag '+(b&&b.matched?"fr-flag-ok":"fr-flag-no")+'">'+(b&&b.matched?"matched":"no match")+"</span></div>"+conds.map((c)=>'<div class="fr-trace-cond"><span class="fr-flag '+(c&&c.result?"fr-flag-ok":"fr-flag-no")+'">'+(c&&c.result?"true":"false")+'</span><span class="fr-trace-text">'+E(c&&c.text)+(c&&c.actual!==undefined&&c.actual!==null&&String(c.actual)!==""?' <span class="fr-trace-actual">(got '+E(String(c.actual).slice(0,120))+")</span>":"")+"</span></div>").join("")+"</div>"
}).join("")
}
function flowRunNodeHtml(view,tab){
const v=view||{}
const E=flowEscape
if(!v.found)return '<div class="fr-node-head"><span class="fr-node-title">'+E(v.title||v.id)+'</span></div><div class="fr-empty">This node is not part of the run shown.</div>'
const cur=tab||v.tab
const tabs=[["stdout","Output"],["stderr","Errors"],["parsed","Parsed"],["trace","Decision"]]
const has={stdout:!!v.tabs.stdout,stderr:!!v.tabs.stderr,parsed:!!v.tabs.parsed,trace:v.tabs.trace.length>0}
let pane
if(cur==="trace")pane='<div class="fr-out fr-out-trace" data-out="trace">'+flowRunTraceHtml(v.tabs.trace)+"</div>"
else{
const body=v.tabs[cur]||""
const empty=v.state==="pending"?"Not reached yet.":v.state==="skipped"?"This node did not run.":v.state==="planned"?"Dry run: nothing was executed.":cur==="parsed"?"No parsed data.":cur==="stderr"?"No error output.":"No output."
pane=body?'<pre class="fr-out" data-out="'+E(cur)+'">'+E(body)+"</pre>":'<div class="fr-empty" data-out="'+E(cur)+'">'+empty+"</div>"
}
return '<div class="fr-node-head"><span class="fr-node-title">'+E(v.title)+'</span><span class="fr-state fr-state-'+E(v.state)+'">'+E(v.stateLabel)+'</span><span class="fr-node-meta">'+E(v.meta)+"</span>"+(v.canRerun?'<button type="button" class="fr-btn" data-fr="rerun" title="Start a new run at this node, keeping the values of the last run"><i class="icon icon-refresh"></i><span>Re-run from this node</span></button>':"")+"</div>"+
(v.error?'<div class="fr-node-error">'+E(v.error)+"</div>":"")+
(v.resolved.length?'<pre class="fr-resolved">'+v.resolved.map((c)=>"$ "+E(c)).join("\n")+"</pre>":"")+
(v.vars&&v.vars!=="{}"?'<div class="fr-node-vars"><span class="fr-label">Set</span><span class="fr-mono">'+E(v.vars.length>400?v.vars.slice(0,400)+"...":v.vars)+"</span></div>":"")+
'<div class="fr-subtabs">'+tabs.map((t)=>'<button type="button" class="fr-subtab'+(t[0]===cur?" active":"")+(has[t[0]]?"":" is-empty")+'" data-fr="subtab" data-tab="'+t[0]+'">'+t[1]+"</button>").join("")+"</div>"+pane
}
// Dry run as text: nodes in walk order, the commands each would run and where each port leads.
function flowRunDryReport(status,graph){
const s=status||{}
const g=graph||{}
const nodes=Array.isArray(g.nodes)?g.nodes:[]
const edges=Array.isArray(g.edges)?g.edges:[]
const byId={}
nodes.forEach((n)=>{if(n&&n.id)byId[n.id]=n})
const planned=(id)=>s.nodes&&s.nodes[id]&&s.nodes[id].state==="planned"
const order=[],seen={}
const start=nodes.filter((n)=>n&&n.type==="start")[0]
const queue=start?[start.id]:[]
while(queue.length){
const id=queue.shift()
if(seen[id]||!byId[id])continue
seen[id]=true
order.push(id)
edges.forEach((e)=>{if(e&&e.from===id&&!seen[e.to])queue.push(e.to)})
}
Object.keys(s.nodes||{}).forEach((id)=>{if(!seen[id]&&byId[id]){seen[id]=true;order.push(id)}})
const title=(id)=>byId[id]?String(byId[id].title||byId[id].type||id):String(id)
return order.filter(planned).map((id)=>{
const n=byId[id]
const cfg=n.config||{}
const out=(s.nodes[id].output)||{}
const lines=[]
if(n.type==="command"){
const resolved=Array.isArray(out.resolved)&&out.resolved.length?out.resolved:(Array.isArray(cfg.commands)?cfg.commands.map((c)=>c&&c.text):[])
resolved.forEach((c)=>lines.push({kind:"cmd",text:String(c===undefined||c===null?"":c)}))
if(resolved.length>1)lines.push({kind:"text",text:cfg.mode==="parallel"?"All at once":"One after another"+(cfg.stop_on_fail===false?"":", stopping at the first failure")})
}else if(n.type==="decision")flowDecisionDescribe(cfg).split("\n").forEach((l)=>lines.push({kind:"text",text:l}))
else if(n.type==="script")lines.push({kind:"text",text:String(cfg.language||"python")+" script, "+String(cfg.code||"").split("\n").length+" lines (branch decided when it runs)"})
else if(n.type==="approval")lines.push({kind:"text",text:"Asks: "+String(cfg.message||"")})
else if(n.type==="wait")lines.push({kind:"text",text:"Waits "+String(cfg.seconds===undefined?"":cfg.seconds)+" s"})
else if(n.type==="foreach")lines.push({kind:"text",text:"Repeats for each item of "+String(cfg.items||"")})
else if(n.type==="parse")lines.push({kind:"text",text:"Reads the previous output ("+String(cfg.mode||"regex")+")"})
else if(n.type==="output")lines.push({kind:"text",text:"Writes output: "+String(cfg.action||"")})
else if(n.type==="subchain")lines.push({kind:"text",text:"Runs chain "+String(cfg.playbook_id===null||cfg.playbook_id===undefined?"(none picked)":cfg.playbook_id)})
else if(n.type==="end")lines.push({kind:"text",text:"Ends the run as "+String(cfg.status||"success")})
const ports={}
const portOrder=[]
edges.forEach((e)=>{
if(!e||e.from!==id)return
if(!ports[e.port]){ports[e.port]=[];portOrder.push(e.port)}
ports[e.port].push(title(e.to))
})
portOrder.forEach((p)=>lines.push({kind:"route",text:p+" -> "+ports[p].join(", ")}))
return {node:id,title:title(id),type:String(n.type||""),lines:lines}
})
}
function flowRunDryText(report){
return "Dry run - nothing was executed\n\n"+(report||[]).map((r,i)=>(i+1)+". "+r.title+" ["+r.type+"]\n"+r.lines.map((l)=>"   "+(l.kind==="cmd"?"$ ":l.kind==="route"?"-> ":"")+l.text).join("\n")).join("\n\n")
}
function flowRunDryHtml(report){
const E=flowEscape
const list=report||[]
return '<div class="fr-banner fr-banner-dry"><b>Dry run - nothing was executed.</b> This is what the chain would do with the current live target. Decisions and scripts cannot know their answer yet, so every branch is listed.</div>'+(list.length?list.map((r,i)=>'<div class="fr-dry-node" data-node="'+E(r.node)+'"><div class="fr-dry-title"><span class="fr-dry-num">'+(i+1)+"</span>"+E(r.title)+'<span class="fr-plan-id">'+E(r.type)+"</span></div>"+r.lines.map((l)=>'<div class="fr-dry-line fr-dry-'+l.kind+'">'+(l.kind==="cmd"?"$ ":"")+E(l.text)+"</div>").join("")+"</div>").join(""):'<div class="fr-empty">Nothing would run.</div>')
}
function flowRunEventHtml(event,titles){
const e=event||{}
const level=e.level==="warn"||e.level==="error"?e.level:"info"
const known=titles&&e.node&&titles[e.node]
return '<div class="fr-ev fr-ev-'+level+'"'+(e.node?' data-node="'+flowEscape(e.node)+'"':"")+'><span class="fr-ev-time">'+flowEscape(flowRunClock(e.ts))+"</span>"+(e.node?'<span class="fr-ev-node">'+flowEscape(known?known.title:e.node)+"</span>":"")+'<span class="fr-ev-text">'+flowEscape(e.text)+"</span></div>"
}
function flowRunHistoryHtml(rows){
const E=flowEscape
const list=Array.isArray(rows)?rows:[]
if(!list.length)return '<div class="fr-empty">No runs recorded yet.</div>'
return list.map((r)=>{
const state=String((r&&r.state)||"")
const dur=r&&r.ended_at?flowRunDuration(flowRunParseTime(r.ended_at)-flowRunParseTime(r.started_at)):""
const when=flowRunParseTime(r&&r.started_at)
const stamp=isNaN(when)?"":new Date(when).toLocaleString()
return '<div class="fr-hist-row"><button type="button" class="fr-hist-open" data-fr="hist-open" data-run="'+E(r&&r.run_id)+'"><span class="fr-state fr-state-run-'+E(state)+'">'+E(FLOW_RUN_STATE_LABELS[state]||state)+'</span><span class="fr-hist-main"><span class="fr-hist-when">'+E(stamp)+(r&&r.mode==="dry"?' <span class="fr-flag fr-flag-script">Dry run</span>':"")+'</span><span class="fr-hist-sub">'+E([r&&r.chain_name,r&&r.target?"on "+r.target:"",r&&r.source&&r.source!=="manual"&&r.source!=="flow"?"from "+r.source:"",dur].filter(Boolean).join(" - "))+'</span></span></button><button type="button" class="fr-icon-btn" data-fr="hist-del" data-run="'+E(r&&r.run_id)+'" title="Delete this run" aria-label="Delete this run"><i class="icon icon-trash"></i></button><button type="button" class="fr-icon-btn" data-fr="hist-log" data-run="'+E(r&&r.run_id)+'" data-name="'+E(r&&r.chain_name)+'" title="Open the log of this run" aria-label="Open the log of this run"><i class="icon icon-list"></i></button></div>'
}).join("")
}
// ---- the panel
function flowRunCreate(host,editor,deps){
deps=deps||{}
const st={runId:null,playbookId:null,status:null,token:0,timer:null,failures:0,watching:false,tab:"log",node:null,nodeTab:"",nodeSig:"",logSeq:0,logPinned:true,barSig:"",apprSig:"",notices:0,dryShown:false,history:null,historyFor:null,destroyed:false,dialog:null}
const root=document.createElement("div")
root.className="flow-run is-hidden"
root.innerHTML='<div class="fr-bar"><span class="fr-icon"></span><div class="fr-titles"><div class="fr-name"></div><div class="fr-sub"></div></div><div class="fr-actions">'+
'<button type="button" class="fr-btn" data-fr="pause" title="Pause after the current node"><span>Pause</span></button>'+
'<button type="button" class="fr-btn" data-fr="resume" title="Continue the run"><i class="icon icon-play"></i><span>Resume</span></button>'+
'<button type="button" class="fr-btn fr-btn-stop" data-fr="stop" title="Stop the run and kill what is running"><i class="icon icon-stop"></i><span>Stop</span></button>'+
'<button type="button" class="fr-btn" data-fr="logs" title="Open the full log of this run: search, filters, copy, export"><i class="icon icon-list"></i><span>Open logs</span></button>'+
'<button type="button" class="fr-btn" data-fr="history" title="Earlier runs of this chain"><i class="icon icon-clock"></i><span>History</span></button>'+
'<button type="button" class="fr-icon-btn" data-fr="close" title="Close and clear the run from the canvas" aria-label="Close"><i class="icon icon-close"></i></button></div></div>'+
'<div class="fr-progress"><span class="fr-progress-fill"></span></div><div class="fr-conn"></div><div class="fr-approval"></div>'+
'<div class="fr-tabs"><button type="button" class="fr-tab" data-fr="tab" data-tab="log">Log</button><button type="button" class="fr-tab" data-fr="tab" data-tab="node">Node output</button><button type="button" class="fr-tab" data-fr="tab" data-tab="dry">Dry-run report</button><button type="button" class="fr-tab" data-fr="tab" data-tab="history">History</button></div>'+
'<div class="fr-pane fr-log" data-pane="log"></div><div class="fr-pane fr-node" data-pane="node"></div><div class="fr-pane fr-dry" data-pane="dry"></div><div class="fr-pane fr-history" data-pane="history"></div>'
host.appendChild(root)
const $=(sel)=>root.querySelector(sel)
const ui={bar:$(".fr-bar"),name:$(".fr-name"),sub:$(".fr-sub"),fill:$(".fr-progress-fill"),conn:$(".fr-conn"),approval:$(".fr-approval"),log:$('[data-pane="log"]'),node:$('[data-pane="node"]'),dry:$('[data-pane="dry"]'),history:$('[data-pane="history"]')}
const toast=(msg,kind)=>{if(typeof deps.toast==="function")deps.toast(msg,kind);else if(typeof showToast==="function")showToast(msg,kind)}
const bridge=(path,args)=>{
if(typeof deps.bridge==="function")return Promise.resolve().then(()=>deps.bridge(path,args||[]))
if(typeof bridgeCall==="function")return bridgeCall(path,args||[])
return Promise.reject(new Error("bridge unavailable"))
}
const graph=()=>{try{return editor&&typeof editor.getGraph==="function"?editor.getGraph():null}catch(_){return null}}
const paint=(status)=>{try{if(editor&&typeof editor.setRunState==="function")editor.setRunState(status)}catch(_){}}
const setHidden=(el,hidden)=>{if(el&&el.classList)el.classList.toggle("is-hidden",!!hidden)}
function showPanel(){
setHidden(root,false)
if(typeof deps.onShow==="function")deps.onShow(true)
}
// -- rendering
function setTab(tab){
st.tab=tab
root.querySelectorAll(".fr-tab").forEach((b)=>b.classList.toggle("active",b.dataset.tab===tab))
;["log","node","dry","history"].forEach((name)=>setHidden(ui[name],name!==tab))
if(tab==="node")renderNode(true)
if(tab==="log"&&st.logPinned)ui.log.scrollTop=ui.log.scrollHeight
}
function setConn(text){
if(ui.conn.textContent!==text)ui.conn.textContent=text
setHidden(ui.conn,!text)
}
function renderBar(){
const view=flowRunStatusView(st.status,Date.now(),flowRunTitles(graph()))
ui.name.textContent=view.name||"Chain run"
ui.sub.textContent=view.label+(view.sub?" - "+view.sub:"")
ui.fill.style.width=(view.final?100:view.percent)+"%"
const sig=view.cls+"|"+view.canPause+view.canResume+view.canStop+view.dry
if(sig!==st.barSig){
st.barSig=sig
root.className="flow-run fr-run-"+view.cls+(view.dry?" fr-is-dry":"")
setHidden($('[data-fr="pause"]'),!view.canPause)
setHidden($('[data-fr="resume"]'),!view.canResume)
setHidden($('[data-fr="stop"]'),!view.canStop)
setHidden($('[data-fr="logs"]'),false)
setHidden($('.fr-tab[data-tab="dry"]'),!view.dry)
}
const appr=view.approval?view.approval.node+"|"+view.approval.message:""
if(appr!==st.apprSig){
st.apprSig=appr
ui.approval.innerHTML=view.approval?'<div class="fr-approval-text"><b>'+flowEscape(view.approval.title)+"</b> asks: "+flowEscape(view.approval.message||"Continue?")+'</div><div class="fr-approval-actions"><button type="button" class="fr-btn fr-btn-stop" data-fr="reject">Reject</button><button type="button" class="fr-btn fr-btn-go" data-fr="approve">Approve</button></div>':""
setHidden(ui.approval,!view.approval)
}
return view
}
// The Log tab shows the structured run log (flows.run_log, polled with since) when the bridge has it; otherwise the status events.
function pollLog(token){
if(st.noRunLog||!st.runId)return
const runId=st.runId
bridge("flows.run_log",[runId,st.logNext,500]).then((res)=>{
if(token!==st.token||st.destroyed||runId!==st.runId)return
const r=res||{}
const fresh=(Array.isArray(r.entries)?r.entries:[]).filter((e)=>e&&Number(e.seq)>st.logNext)
if(!st.useRunLog){st.useRunLog=true;st.logSeq=0;st.logRows=[];ui.log.innerHTML=""}
fresh.forEach((e)=>{st.logRows.push(e);if(Number(e.seq)>st.logNext)st.logNext=Number(e.seq)})
if(Number(r.next)>st.logNext)st.logNext=Number(r.next)
if(st.logRows.length>FLOW_RUN_MAX_EVENTS)st.logRows=st.logRows.slice(st.logRows.length-FLOW_RUN_MAX_EVENTS)
renderLog()
// the tail of a run that just finished: one more round until the log says it is complete
if(fresh.length>=500||(r.live===true&&!st.watching&&!st.logTail)){st.logTail=!st.watching;setTimeout(()=>pollLog(token),fresh.length>=500?0:FLOW_RUN_POLL_MS)}
}).catch((err)=>{if(/bridge method missing/i.test(flowRunErrorText(err,"")))st.noRunLog=true})
}
function renderLog(){
const events=st.useRunLog?st.logRows:(st.status&&st.status.events)||[]
const titles=flowRunTitles(graph())
let html=""
let last=st.logSeq
events.forEach((e)=>{
if(!e||Number(e.seq)<=st.logSeq)return
html+=flowRunEventHtml(e,titles)
if(Number(e.seq)>last)last=Number(e.seq)
})
if(!html)return
st.logSeq=last
ui.log.insertAdjacentHTML("beforeend",html)
// The DOM keeps the same cap as the status object.
let extra=ui.log.childElementCount-FLOW_RUN_MAX_EVENTS
while(extra-->0&&ui.log.firstElementChild)ui.log.removeChild(ui.log.firstElementChild)
if(st.logPinned)ui.log.scrollTop=ui.log.scrollHeight
}
function renderNode(force){
if(st.tab!=="node"&&!force)return
if(!st.node||!st.status){
if(st.nodeSig!=="-"){st.nodeSig="-";ui.node.innerHTML='<div class="fr-empty">Click a node on the canvas to see what it did in this run.</div>'}
return
}
const view=flowRunNodeView(st.status,st.node,flowRunTitles(graph()))
const tab=st.nodeTab||view.tab
const sig=JSON.stringify([view,tab])
if(sig===st.nodeSig)return
st.nodeSig=sig
const pre=ui.node.querySelector("[data-out]")
const keep=pre&&pre.dataset&&pre.dataset.out===tab?{top:pre.scrollTop,pinned:pre.scrollTop+pre.clientHeight>=pre.scrollHeight-24}:null
ui.node.innerHTML=flowRunNodeHtml(view,tab)
const now=ui.node.querySelector("[data-out]")
if(now)now.scrollTop=keep&&!keep.pinned?keep.top:now.scrollHeight
}
function renderDry(){
ui.dry.innerHTML=flowRunDryHtml(flowRunDryReport(st.status,graph()))
}
function renderHistory(){
const head='<div class="fr-hist-head"><span class="fr-label">'+(st.history?st.history.length+" run"+(st.history.length===1?"":"s"):"Loading...")+'</span><span class="fr-hist-actions"><button type="button" class="fr-btn" data-fr="hist-refresh"><i class="icon icon-refresh"></i><span>Refresh</span></button>'+(st.history&&st.history.length?'<button type="button" class="fr-btn fr-btn-stop" data-fr="hist-clear"><i class="icon icon-trash"></i><span>Clear</span></button>':"")+"</span></div>"
ui.history.innerHTML=head+(st.history?flowRunHistoryHtml(st.history):"")
}
function apply(status){
st.status=status
paint(status)
const view=renderBar()
renderLog()
renderNode(false)
if(view.dry&&view.final&&!st.dryShown){
st.dryShown=true
renderDry()
setTab("dry")
}
const notices=Array.isArray(status.notices)?status.notices:[]
if(st.watching&&notices.length>st.notices)notices.slice(st.notices).forEach((n)=>toast(String((n&&n.title)||"Chain")+(n&&n.text?": "+String(n.text).slice(0,200):"")))
st.notices=notices.length
return view
}
function reset(runId,playbookId){
stopWatching()
st.runId=runId
st.playbookId=playbookId===undefined||playbookId===null?st.playbookId:playbookId
st.status=null
st.logSeq=0
st.logNext=0
st.logRows=[]
st.useRunLog=false
st.logTail=false
st.logPinned=true
st.nodeSig=""
st.nodeTab=""
st.barSig=""
st.apprSig="?"
st.notices=0
st.dryShown=false
st.failures=0
ui.log.innerHTML=""
ui.dry.innerHTML=""
setConn("")
showPanel()
setTab("log")
}
// -- polling
function schedule(ms){
if(st.timer)clearTimeout(st.timer)
const token=st.token
st.timer=setTimeout(()=>{st.timer=null;if(token===st.token&&st.watching)poll()},ms)
}
function poll(){
const token=st.token
bridge("flows.run_status",[st.runId,flowRunLastSeq(st.status)]).then((res)=>{
if(token!==st.token||st.destroyed)return
if(!res||typeof res!=="object")throw new Error("empty status")
st.failures=0
setConn("")
const view=apply(flowRunMergeStatus(st.status,res))
pollLog(token)
if(st.playbookId===null&&res.playbook_id!==undefined)st.playbookId=res.playbook_id
if(view.final){finish(view);return}
schedule(FLOW_RUN_POLL_MS)
}).catch((err)=>{
if(token!==st.token||st.destroyed)return
const text=flowRunErrorText(err,"")
if(/no such run/i.test(text)){
st.watching=false
setConn("This run is no longer available.")
return
}
st.failures++
const delay=flowRunBackoff(st.failures)
setConn("Connection lost - retrying in "+Math.max(1,Math.round(delay/1000))+" s"+(/locked/i.test(text)?" (the app is locked)":""))
schedule(delay)
})
}
function finish(view){
st.watching=false
if(st.timer){clearTimeout(st.timer);st.timer=null}
if(typeof deps.onFinish==="function")deps.onFinish(st.status)
if(!view.dry)toast((view.name||"Chain")+": "+view.label.toLowerCase()+(view.reason&&view.state!=="done"?" ("+view.reason+")":""),view.state==="done"?undefined:"error")
if(st.history)loadHistory(st.historyFor)
}
function attach(runId,opts){
const o=opts||{}
if(!runId)return
reset(String(runId),o.playbookId)
st.watching=true
st.token++
poll()
}
function stopWatching(){
st.watching=false
st.token++
if(st.timer){clearTimeout(st.timer);st.timer=null}
}
function showStored(runId){
return bridge("flows.run_get",[runId]).then((res)=>{
if(st.destroyed||!res||typeof res!=="object")return null
if(!flowRunIsFinal(res.state)){attach(runId,{playbookId:res.playbook_id});return runId}
reset(String(runId),res.playbook_id)
apply(flowRunMergeStatus(null,res))
pollLog(st.token)
return runId
}).catch((err)=>{toast(flowRunErrorText(err,"Could not open that run"),"error");return null})
}
function clear(){
stopWatching()
closeDialog(null)
st.runId=null
st.status=null
st.node=null
paint(null)
setHidden(root,true)
if(typeof deps.onShow==="function")deps.onShow(false)
}
function selectNode(nodeId){
if(!st.status||!nodeId)return
if(st.node!==nodeId){st.node=nodeId;st.nodeTab="";st.nodeSig=""}
setTab("node")
}
// -- history
function loadHistory(playbookId){
st.historyFor=playbookId===undefined?st.historyFor:playbookId
return bridge("flows.runs",[st.historyFor===undefined?null:st.historyFor,30]).then((rows)=>{
if(st.destroyed)return
st.history=Array.isArray(rows)?rows:[]
renderHistory()
}).catch((err)=>{
if(st.destroyed)return
st.history=[]
renderHistory()
toast(flowRunErrorText(err,"Could not load the run history"),"error")
})
}
function showHistory(playbookId){
if(playbookId!==undefined&&playbookId!==null)st.playbookId=playbookId
showPanel()
if(!st.status){
ui.name.textContent="Run history"
ui.sub.textContent=""
root.className="flow-run fr-run-idle"
;["pause","resume","stop","logs"].forEach((k)=>setHidden($('[data-fr="'+k+'"]'),true))
setHidden($('.fr-tab[data-tab="dry"]'),true)
setHidden(ui.approval,true)
setHidden(ui.conn,true)
}
st.history=null
renderHistory()
setTab("history")
return loadHistory(playbookId===undefined?st.playbookId:playbookId)
}
// -- confirmation dialog (same shell as acDialog so it looks like the linear chain prompt)
function closeDialog(value){
const d=st.dialog
if(!d)return
st.dialog=null
document.removeEventListener("keydown",d.onKey,true)
if(d.el.parentNode)d.el.parentNode.removeChild(d.el)
d.resolve(value===undefined?null:value)
}
function openConfirm(model,code){
closeDialog(null)
return new Promise((resolve)=>{
const overlay=document.createElement("div")
overlay.className="confirm-overlay"
const title=(model.fromNode?"Run \""+(model.name||"this chain")+"\" from the selected node?":"Run \""+(model.name||"this chain")+"\"?")
overlay.innerHTML='<div class="confirm-box confirm-box-wide glass-panel ac-dialog fr-dialog"><div class="confirm-message"></div><div class="confirm-body">'+flowRunConfirmHtml(model,code)+'</div><div class="confirm-actions"><button type="button" class="confirm-cancel" data-fr-choice="cancel">Cancel</button><button type="button" class="confirm-extra" data-fr-choice="dry" title="Walk the chain without executing anything">Dry run</button><button type="button" class="confirm-ok'+(model.destructive?" danger":"")+'" data-fr-choice="run">'+flowEscape(model.runLabel)+"</button></div></div>"
const msg=overlay.querySelector(".confirm-message")
if(msg)msg.textContent=title
const d={el:overlay,resolve:resolve,onKey:(e)=>{if(e.key==="Escape"){e.preventDefault();e.stopPropagation();closeDialog(null)}}}
st.dialog=d
const runBtn=overlay.querySelector('[data-fr-choice="run"]')
const ack=overlay.querySelector('[data-fr="ack"]')
const sync=()=>{if(runBtn)runBtn.disabled=!flowRunCanStart(model,!!(ack&&ack.checked))}
sync()
if(ack)ack.addEventListener("change",sync)
overlay.addEventListener("click",(e)=>{
if(e.target===overlay){closeDialog(null);return}
const btn=e.target.closest&&e.target.closest("[data-fr-choice]")
if(!btn||btn.disabled)return
const choice=btn.dataset.frChoice
if(choice==="run"&&!flowRunCanStart(model,!!(ack&&ack.checked)))return
closeDialog(choice==="cancel"?null:choice)
})
document.addEventListener("keydown",d.onKey,true)
document.body.appendChild(overlay)
const first=overlay.querySelector(".confirm-cancel")
if(first&&typeof first.focus==="function")setTimeout(()=>{if(st.dialog===d)first.focus()},0)
})
}
function confirmAndRun(playbookId,opts){
const o=opts||{}
const fromNode=o.from_node||null
st.playbookId=playbookId
return bridge("flows.plan",[playbookId,null,fromNode]).then((plan)=>{
if(st.destroyed)return null
const model=flowRunPlanModel(plan,{from_node:fromNode,name:o.name||(plan&&plan.name)||""})
return openConfirm(model,flowRunScriptCode((plan&&plan.graph)||graph())).then((choice)=>{
if(choice==="dry")return dryRun(playbookId,null,{from_node:fromNode})
if(choice!=="run")return null
return bridge("flows.run",[playbookId,{mode:"run",from_node:fromNode,source:o.source||"manual",confirmed:true,review_ack:model.needsReview,fingerprint:model.fingerprint||undefined}]).then((res)=>{
if(!res||!res.run_id)throw new Error("The run did not start")
if(model.needsReview&&typeof deps.onReviewed==="function")deps.onReviewed(playbookId)
attach(res.run_id,{playbookId:playbookId})
return res.run_id
})
})
}).catch((err)=>{toast(flowRunErrorText(err,"Could not start the run"),"error");return null})
}
function dryRun(playbookId,unsaved,opts){
const o=opts||{}
st.playbookId=playbookId
return bridge("flows.run",[playbookId,{mode:"dry",graph:unsaved||null,from_node:o.from_node||null,source:"manual"}]).then((res)=>{
if(!res||!res.run_id)throw new Error("The dry run did not start")
attach(res.run_id,{playbookId:playbookId})
return res.run_id
}).catch((err)=>{toast(flowRunErrorText(err,"Could not start the dry run"),"error");return null})
}
// -- actions
function control(method,args,failText){
return bridge("flows."+method,args).then(()=>{
if(st.watching){if(st.timer){clearTimeout(st.timer);st.timer=null}poll()}
}).catch((err)=>toast(flowRunErrorText(err,failText),"error"))
}
function onClick(e){
const row=e.target.closest&&e.target.closest("[data-node]")
const btn=e.target.closest&&e.target.closest("[data-fr]")
if(!btn){
if(row&&root.contains(row)&&row.dataset.node){
try{if(editor&&typeof editor.select==="function")editor.select([row.dataset.node])}catch(_){}
selectNode(row.dataset.node)
}
return
}
if(!root.contains(btn)||btn.disabled)return
const what=btn.dataset.fr
if(what==="tab"){setTab(btn.dataset.tab);if(btn.dataset.tab==="history"&&!st.history)loadHistory(st.playbookId);return}
if(what==="subtab"){st.nodeTab=btn.dataset.tab;st.nodeSig="";renderNode(true);return}
if(what==="close"){clear();return}
if(what==="history"){showHistory(st.playbookId);return}
if(what==="logs"||what==="hist-log"){
const runId=what==="logs"?st.runId:btn.dataset.run
if(runId&&typeof flowLogOpen==="function")flowLogOpen({runId:runId,name:what==="logs"?(st.status&&st.status.name)||"":btn.dataset.name||"",titles:flowRunTitles(graph()),bridge:bridge,toast:toast,live:what==="logs"&&st.watching})
return
}
if(what==="pause"){control("pause",[st.runId],"Could not pause the run");return}
if(what==="resume"){control("resume",[st.runId],"Could not resume the run");return}
if(what==="stop"){control("stop",[st.runId],"Could not stop the run");return}
if(what==="approve"||what==="reject"){
const node=st.status&&st.status.approval&&st.status.approval.node
if(node)control("approve",[st.runId,node,what==="approve"],"Could not answer the approval")
return
}
if(what==="rerun"){
const pid=st.status&&st.status.playbook_id!==undefined&&st.status.playbook_id!==null?st.status.playbook_id:st.playbookId
if(pid!==null&&pid!==undefined&&st.node)confirmAndRun(pid,{from_node:st.node,name:st.status&&st.status.name})
return
}
if(what==="hist-refresh"){loadHistory(st.historyFor);return}
if(what==="hist-open"){showStored(btn.dataset.run);return}
if(what==="hist-del"){
bridge("flows.run_delete",[btn.dataset.run]).then(()=>loadHistory(st.historyFor)).catch((err)=>toast(flowRunErrorText(err,"Could not delete that run"),"error"))
return
}
if(what==="hist-clear"){
const go=()=>bridge("flows.runs_clear",[st.historyFor===undefined?null:st.historyFor]).then(()=>loadHistory(st.historyFor)).catch((err)=>toast(flowRunErrorText(err,"Could not clear the history"),"error"))
if(typeof appConfirm==="function")appConfirm("Delete the recorded runs of this chain?",{okLabel:"Delete",danger:true}).then((ok)=>{if(ok)go()})
else go()
}
}
function onLogScroll(){
st.logPinned=ui.log.scrollTop+ui.log.clientHeight>=ui.log.scrollHeight-24
}
// A click on the canvas while a run is shown opens that node's output.
function onCanvasClick(){
if(!st.status||st.destroyed)return
setTimeout(()=>{
if(!st.status||st.destroyed)return
let sel=[]
try{sel=typeof editor.getSelection==="function"?editor.getSelection()||[]:[]}catch(_){sel=[]}
if(sel.length===1&&sel[0]!==st.node)selectNode(sel[0])
},0)
}
root.addEventListener("click",onClick)
ui.log.addEventListener("scroll",onLogScroll)
const canvas=editor&&editor.el&&typeof editor.el.addEventListener==="function"?editor.el:null
if(canvas)canvas.addEventListener("click",onCanvasClick)
function destroy(){
if(st.destroyed)return
stopWatching()
closeDialog(null)
st.destroyed=true
if(canvas)canvas.removeEventListener("click",onCanvasClick)
paint(null)
if(root.parentNode)root.parentNode.removeChild(root)
}
return {confirmAndRun:confirmAndRun,dryRun:dryRun,attach:attach,stopWatching:stopWatching,showHistory:showHistory,showStored:showStored,selectNode:selectNode,clear:clear,destroy:destroy,
isWatching:()=>st.watching,runId:()=>st.runId,status:()=>st.status,el:root}
}
if(typeof module!=="undefined"&&module.exports)module.exports={FLOW_RUN_POLL_MS,FLOW_RUN_BACKOFF_MAX_MS,FLOW_RUN_MAX_EVENTS,FLOW_RUN_FINAL_STATES,FLOW_RUN_STATE_LABELS,FLOW_RUN_NODE_LABELS,flowRunIsFinal,flowRunBackoff,flowRunErrorText,flowRunDuration,flowRunClock,flowRunElapsedMs,flowRunLastSeq,flowRunMergeStatus,flowRunTitles,flowRunStatusView,flowRunPlanModel,flowRunCanStart,flowRunPolicyBlockText,flowRunScriptCode,flowRunConfirmHtml,flowRunNodeView,flowRunTraceHtml,flowRunNodeHtml,flowRunDryReport,flowRunDryText,flowRunDryHtml,flowRunEventHtml,flowRunHistoryHtml,flowRunCreate}
