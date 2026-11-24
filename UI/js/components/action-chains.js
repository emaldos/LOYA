// Action chains (internally "playbooks"): /caller lookup, the pre-run checks against the live target, and the live progress card.
// terminal.js, commands.js and the AI panel all start a chain through acRunChain / loyaRunChainByCaller, so the checks live in one place.
// The progress card reads the same TerminalJobs records (chain_id/chain_pos/state) the Jobs drawer shows - there is no second model.
const AC_RESERVED_CALLERS=["help","explain","summarize-note","new-note","new-command","fix-command","suggest-next","run","target","search","newchain"]
const AC_CALLER_RE=/^[a-z0-9_-]{1,32}$/
const AC_CALLER_MAX=32
const AC_POLL_MS=700
const AC_CALLERS_TTL_MS=3000
let acState={callers:[],loadedAt:0,loading:null,runs:[]}
function acEscape(value){
return String(value===undefined||value===null?"":value).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")
}
// ---- Pure helpers (also loaded by tests/js) ----
function acNormalizeCaller(value){
let text=String(value===undefined||value===null?"":value).trim()
if(text.charAt(0)==="/")text=text.slice(1).trim()
return text.toLowerCase()
}
// "" when the caller is fine. callers: the known chains [{id,caller}]; selfId: the chain being edited (its own caller is not a clash).
function acCallerError(caller,callers,selfId){
const value=acNormalizeCaller(caller)
if(!value)return "A caller is required."
if(value.length>AC_CALLER_MAX)return "A caller is at most "+AC_CALLER_MAX+" characters."
if(!AC_CALLER_RE.test(value))return "A caller may only use lowercase letters, digits, - and _."
if(AC_RESERVED_CALLERS.indexOf(value)!==-1)return "/"+value+" is a built-in AI command - pick another caller."
const clash=(callers||[]).find((c)=>c&&c.caller===value&&String(c.id)!==String(selfId))
if(clash)return "/"+value+" is already used by "+(clash.name||"another action chain")+"."
return ""
}
function acSlugifyCaller(name){
let text=String(name||"")
if(text.normalize)text=text.normalize("NFKD")
text=text.replace(/[̀-ͯ]/g,"").toLowerCase().replace(/[^a-z0-9_-]+/g,"-").replace(/-{2,}/g,"-").replace(/^[-_]+|[-_]+$/g,"")
return text.slice(0,AC_CALLER_MAX).replace(/[-_]+$/,"")
}
// The terminal shows chain suggestions only while the line is a single token that starts with "/" at position 0.
function acIsSlashTrigger(value){
const text=String(value===undefined||value===null?"":value)
return text.charAt(0)==="/"&&!/\s/.test(text)
}
function acMatchCallers(callers,value){
if(!acIsSlashTrigger(value))return []
const q=String(value).slice(1).toLowerCase()
if(q.indexOf("/")!==-1)return []
const list=(callers||[]).filter((c)=>c&&c.caller)
const starts=list.filter((c)=>c.caller.indexOf(q)===0).sort((a,b)=>a.caller.length-b.caller.length||(a.caller<b.caller?-1:a.caller>b.caller?1:0))
const rest=q?list.filter((c)=>c.caller.indexOf(q)!==0&&(c.caller.indexOf(q)!==-1||String(c.name||"").toLowerCase().indexOf(q)!==-1)):[]
return starts.concat(rest)
}
// Enter only runs a chain when the whole line is exactly "/caller" (trailing blanks allowed). /usr/bin/id and friends go to the shell.
function acExactCaller(callers,value){
const text=String(value===undefined||value===null?"":value).replace(/[ \t]+$/,"")
if(!/^\/[a-z0-9_-]{1,32}$/.test(text))return null
const name=text.slice(1)
return (callers||[]).find((c)=>c&&c.caller===name)||null
}
function acPlaceholderKeys(command){
if(typeof snipIterPlaceholders!=="function")return []
const source=String(command||"")
const seen={}
const out=[]
snipIterPlaceholders(source).forEach((span)=>{
if(span[0]>0&&source[span[0]-1]==="$")return
const lower=span[2].toLowerCase()
if(seen[lower])return
seen[lower]=true
out.push(span[2])
})
return out
}
function acValueMap(values){
const map={}
Object.keys(values||{}).forEach((key)=>{
const value=values[key]
const text=value===undefined||value===null?"":String(value).trim()
if(text)map[String(key).toLowerCase()]=text
})
return map
}
// One entry per step that uses an element the target has no value for: [{index,label,command,missing:[key]}].
function acMissingByStep(steps,values){
const map=acValueMap(values)
const out=[]
;(steps||[]).forEach((step,index)=>{
const missing=acPlaceholderKeys(step&&step.command).filter((key)=>!Object.prototype.hasOwnProperty.call(map,key.toLowerCase()))
if(missing.length)out.push({index:index,label:(step&&step.label)||"Step "+(index+1),command:(step&&step.command)||"",missing:missing})
})
return out
}
function acFirstBlockedStep(steps,values){
const missing=acMissingByStep(steps,values)
return missing.length?missing[0].index:-1
}
function acResolveCommand(command,values){
const text=String(command||"")
if(typeof snipIterPlaceholders!=="function")return text
const map=acValueMap(values)
let out="",last=0
snipIterPlaceholders(text).forEach((span)=>{
if(span[0]>0&&text[span[0]-1]==="$")return
out+=text.slice(last,span[0])
const lower=span[2].toLowerCase()
out+=Object.prototype.hasOwnProperty.call(map,lower)?map[lower]:"{"+span[2]+"}"
last=span[1]
})
return out+text.slice(last)
}
// The items sent to terminal.chain_start. stopAt>=0 marks that step and every later one skipped (the backend runs only the ones before).
function acBuildChainItems(steps,values,stopAt){
const missing={}
acMissingByStep(steps,values).forEach((row)=>{missing[row.index]=row.missing})
return (steps||[]).map((step,index)=>{
const item={label:step.label||"",command:acResolveCommand(step.command,values)}
if(stopAt>=0&&index>=stopAt){
const own=missing[index]?"Missing "+missing[index].map((k)=>"{"+k+"}").join(", "):""
item.skip_reason=index===stopAt?own||"Stopped here":"Stopped before step "+(stopAt+1)+(own?" - also "+own.charAt(0).toLowerCase()+own.slice(1):"")
}
return item
})
}
function acParseTime(value){
if(!value)return NaN
// JavaScriptCore rejects more than 3 fractional digits; the backend writes microseconds.
return Date.parse(String(value).replace(/(\.\d{3})\d+/,"$1"))
}
function acFormatDuration(ms){
if(!(ms>=0))return ""
const seconds=Math.floor(ms/1000)
if(seconds<60)return seconds+"s"
if(seconds<3600)return Math.floor(seconds/60)+"m "+String(seconds%60).padStart(2,"0")+"s"
return Math.floor(seconds/3600)+"h "+String(Math.floor((seconds%3600)/60)).padStart(2,"0")+"m"
}
function acStepDuration(step,now){
if(!step||step.state==="pending"||step.state==="skipped")return ""
const start=acParseTime(step.started_at)
const end=step.ended_at?acParseTime(step.ended_at):(now||Date.now())
if(isNaN(start)||isNaN(end)||end<start)return ""
return acFormatDuration(end-start)
}
function acRunSummary(status){
const steps=(status&&status.steps)||[]
const count=(state)=>steps.filter((s)=>s.state===state).length
const settled=steps.filter((s)=>s.state!=="pending"&&s.state!=="running").length
const runningIndex=steps.findIndex((s)=>s.state==="running")
const active=steps.some((s)=>s.state==="running"||s.state==="pending")
const failed=count("failed")+count("killed")+count("orphaned")
return {total:steps.length,settled:settled,done:count("done"),failed:failed,skipped:count("skipped"),running:runningIndex,active:active,percent:steps.length?Math.round(settled/steps.length*100):0,state:active?"running":failed?"failed":count("skipped")?"stopped":"done"}
}
// ---- Callers cache ----
function acRefreshCallers(force){
if(acState.loading)return acState.loading
if(!force&&acState.loadedAt&&Date.now()-acState.loadedAt<AC_CALLERS_TTL_MS)return Promise.resolve(acState.callers)
if(typeof bridgeCall!=="function")return Promise.resolve(acState.callers)
acState.loading=bridgeCall("playbooks.callers").then((rows)=>{
acState.callers=(Array.isArray(rows)?rows:[]).filter((r)=>r&&r.caller)
acState.loadedAt=Date.now()
return acState.callers
}).catch(()=>acState.callers).then((rows)=>{acState.loading=null;return rows})
return acState.loading
}
function acInvalidateCallers(){
acState.loadedAt=0
return acRefreshCallers(true)
}
// Terminal hooks (terminal.js calls these when present).
function acTerminalSlashActive(value,caret){
const text=String(value||"")
if(caret!==undefined&&caret!==null&&caret!==text.length)return false
return acIsSlashTrigger(text)
}
function acTerminalSuggestItems(value){
return acMatchCallers(acState.callers,value).slice(0,8).map((c)=>({command:"/"+c.caller,title:"Action chain - "+c.steps+" step"+(c.steps===1?"":"s"),category:c.name,chainCaller:c.caller,family:"any"}))
}
function acTerminalExactCaller(value){
return acExactCaller(acState.callers,value)
}
// ---- Public API for the AI panel (and anyone else) ----
function loyaChainCallers(){
return acRefreshCallers(true).then((rows)=>rows.map((c)=>({caller:c.caller,name:c.name||"",steps:parseInt(c.steps,10)||0,description:c.description||""})))
}
function loyaRunChainByCaller(caller,opts){
opts=opts||{}
const wanted=acNormalizeCaller(caller)
return acRefreshCallers(true).then((rows)=>{
const hit=rows.find((c)=>c.caller===wanted)
if(!hit){
if(typeof showToast==="function")showToast("No action chain is called /"+wanted,"error")
return {started:false,reason:"unknown-caller"}
}
return acRunChain(hit.id,{name:hit.name,caller:hit.caller,source:opts.source||"terminal"})
})
}
// ---- Dialogs ----
function acDialog(message,bodyHtml,buttons,onMount){
return new Promise((resolve)=>{
const overlay=document.createElement("div")
overlay.className="confirm-overlay"
const box=document.createElement("div")
box.className="confirm-box confirm-box-wide glass-panel ac-dialog"
box.innerHTML='<div class="confirm-message"></div><div class="confirm-body">'+(bodyHtml||"")+'</div><div class="confirm-actions">'+buttons.map((b,i)=>'<button type="button" class="'+acEscape(b.cls||"")+'" data-ac-choice="'+i+'">'+acEscape(b.label)+"</button>").join("")+"</div>"
box.querySelector(".confirm-message").textContent=message
overlay.appendChild(box)
document.body.appendChild(overlay)
let done=false
function close(value){
if(done)return
done=true
document.removeEventListener("keydown",onKey,true)
overlay.remove()
resolve(value===undefined?null:value)
}
function onKey(e){if(e.key==="Escape"){e.preventDefault();e.stopPropagation();close(null)}}
document.addEventListener("keydown",onKey,true)
box.querySelectorAll("[data-ac-choice]").forEach((btn)=>btn.addEventListener("click",()=>close(buttons[parseInt(btn.dataset.acChoice,10)].value)))
overlay.addEventListener("click",(e)=>{if(e.target===overlay)close(null)})
if(typeof onMount==="function")onMount(box,close)
const primary=box.querySelector(".confirm-ok")
if(primary)setTimeout(()=>primary.focus(),0)
})
}
function acChainTitle(ctx){
return (ctx.name||"Action chain")+(ctx.caller?" (/"+ctx.caller+")":"")
}
function acAskForTarget(ctx){
return bridgeCall("targets.targets").catch(()=>[]).then((targets)=>{
targets=Array.isArray(targets)?targets:[]
const list=targets.length?'<div class="ac-target-picks">'+targets.slice().sort((a,b)=>String(a.name||"").localeCompare(String(b.name||""))).map((t)=>'<button type="button" class="ac-target-pick" data-target="'+acEscape(t.id)+'"><i class="icon icon-target"></i><span>'+acEscape(t.name)+'</span><span class="ac-target-count">'+Object.keys(t.values||{}).length+" values</span></button>").join("")+"</div>":'<div class="ac-note">You have no targets yet.</div>'
const body='<div class="ac-note">'+acEscape(acChainTitle(ctx))+" fills its {elements} from the live target, and no target is live. "+(targets.length?"Pick one to use now, or set it up on the Targets page.":"Add one on the Targets page first.")+"</div>"+list
let picked=null
return acDialog("Select a target first",body,[{label:"Cancel",value:null,cls:"confirm-cancel"},{label:"Go to Targets",value:"goto",cls:"confirm-ok"}],(box,close)=>{
box.querySelectorAll(".ac-target-pick").forEach((btn)=>btn.addEventListener("click",()=>{picked=btn.dataset.target;close("pick")}))
}).then((choice)=>{
if(choice==="goto"){if(typeof goToPage==="function")goToPage("targets").then(()=>{if(typeof tgtSwitchTab==="function")tgtSwitchTab("targets")}).catch(()=>{});return false}
if(choice!=="pick"||!picked)return false
return bridgeCall("targets.set_live_target",[picked]).then(()=>{
const t=targets.find((x)=>x.id===picked)
if(typeof showStatusIsland==="function")showStatusIsland("Live target: "+(t?t.name:"set"))
document.dispatchEvent(new CustomEvent("loya:live-target-changed",{detail:{id:picked}}))
return true
}).catch((err)=>{showToast(err&&err.message?err.message:"Could not set the live target","error");return false})
})
})
}
function acMissingBodyHtml(ctx,target,missing,steps){
const rows=missing.map((row)=>'<div class="ac-missing-step"><div class="ac-missing-head"><span class="ac-missing-num">Step '+(row.index+1)+'</span><span class="ac-missing-label">'+acEscape(row.label)+'</span></div><div class="ac-missing-keys">'+row.missing.map((k)=>'<span class="ac-key">{'+acEscape(k)+"}</span>").join("")+"</div></div>").join("")
const first=missing[0].index
const runs=first>0?"Run anyway runs step"+(first===1?" 1":"s 1-"+first)+" and stops before step "+(first+1)+".":"Step 1 already needs a missing element, so nothing can run until they are filled."
return '<div class="ac-note">Live target <b>'+acEscape(target.name)+"</b> has no value for "+(missing.length===1?"an element":"elements")+" used by "+missing.length+" of "+steps.length+' steps.</div><div class="ac-missing-list">'+rows+'</div><div class="ac-note ac-note-dim">'+acEscape(runs)+"</div>"
}
function acAskMissing(ctx,target,missing,steps){
const first=missing[0].index
const buttons=[{label:"Cancel",value:null,cls:"confirm-cancel"},{label:"Fill them first",value:"fill",cls:first>0?"confirm-extra":"confirm-ok"}]
if(first>0)buttons.push({label:"Run anyway - stop at step "+(first+1),value:"run",cls:"confirm-ok"})
return acDialog(acChainTitle(ctx)+" needs target values",acMissingBodyHtml(ctx,target,missing,steps),buttons)
}
function acUniqueKeys(missing){
const seen={}
const out=[]
missing.forEach((row)=>row.missing.forEach((k)=>{const l=k.toLowerCase();if(!seen[l]){seen[l]=true;out.push(k)}}))
return out
}
// Opens the live target's edit form on the Targets page, showing only the missing elements.
function acOpenFillForm(target,keys,ctx){
if(typeof goToPage!=="function"||typeof tgtOpenTargetForm!=="function"){showToast("Open the Targets page to fill the missing values","error");return Promise.resolve(false)}
return goToPage("targets").then(()=>typeof tgtRefreshAll==="function"?tgtRefreshAll():null).then(()=>{
if(typeof tgtSwitchTab==="function")tgtSwitchTab("targets")
const fresh=(typeof tgtState!=="undefined"&&tgtState.targets||[]).find((t)=>t.id===target.id)||target
tgtOpenTargetForm(fresh)
const pop=document.getElementById("tgtPopover")
if(!pop)return false
const wanted={}
keys.forEach((k)=>{wanted[k.toLowerCase()]=k})
const found={}
let first=null
pop.querySelectorAll(".tgt-value-input").forEach((input)=>{
const lower=String(input.dataset.key||"").toLowerCase()
const field=input.closest(".tgt-popover-field")
const hit=Object.prototype.hasOwnProperty.call(wanted,lower)
if(field){field.classList.toggle("hidden",!hit);field.classList.toggle("ac-fill-field",hit)}
if(hit){found[lower]=true;if(!first)first=input}
})
const finder=pop.querySelector(".tgt-field-finder")
if(finder)finder.classList.add("hidden")
const absent=keys.filter((k)=>!found[k.toLowerCase()])
const note=document.createElement("div")
note.className="ac-fill-note"
note.innerHTML='<div><b>'+acEscape(acChainTitle(ctx))+"</b> needs "+(keys.length===1?"this element":"these elements")+"."+(absent.length?' Not a target element yet: '+absent.map((k)=>'<span class="ac-key">{'+acEscape(k)+"}</span>").join(" ")+" - add it on the Elements tab.":"")+'</div><button type="button" class="ac-fill-all">Show all fields</button>'
const anchor=pop.querySelector(".tgt-popover-values")||pop.querySelector(".tgt-popover-actions")
if(anchor)anchor.parentNode.insertBefore(note,anchor)
note.querySelector(".ac-fill-all").addEventListener("click",()=>{
pop.querySelectorAll(".tgt-popover-field.hidden").forEach((f)=>f.classList.remove("hidden"))
note.querySelector(".ac-fill-all").remove()
})
if(first)setTimeout(()=>{first.focus()},0)
// Once the form saves (it closes itself), offer to run the chain straight away.
const save=pop.querySelector("#tgtFormSave")
if(save&&ctx&&ctx.id)save.addEventListener("click",()=>{
const started=Date.now()
const watch=setInterval(()=>{
if(document.getElementById("tgtPopover")===pop&&Date.now()-started<6000)return
clearInterval(watch)
if(document.getElementById("tgtPopover")===pop)return
appConfirm("Run "+acChainTitle(ctx)+" now?",{okLabel:"Run",cancelLabel:"Not now"}).then((yes)=>{if(yes)acRunChain(ctx.id,ctx)})
},150)
})
return true
})
}
// ---- Running ----
function acLiveTarget(){
return bridgeCall("targets.targets").then((targets)=>(Array.isArray(targets)?targets:[]).find((t)=>t&&t.status==="live")||null)
}
function acRunChain(playbookId,opts){
const ctx=Object.assign({source:"chains"},opts||{},{id:playbookId})
if(typeof termState==="undefined"||!termState.enabled){showToast("Enable the terminal in Settings first","error");return Promise.resolve({started:false,reason:"terminal-disabled"})}
// A chain that has a diagram runs through the flow engine with its own confirmation (pages/chains_flow.js); null = linear chain.
if(!ctx.linear&&typeof chainsFlowRunChain==="function")return chainsFlowRunChain(playbookId,ctx).then((handled)=>handled||acRunChain(playbookId,Object.assign({},ctx,{linear:true})))
return Promise.all([bridgeCall("playbooks.get",[playbookId]),bridgeCall("playbooks.commands",[playbookId])]).then((res)=>{
const book=res[0]||{}
const steps=Array.isArray(res[1])?res[1]:[]
ctx.name=book.name||ctx.name||"Action chain"
ctx.caller=book.caller||ctx.caller||""
if(!steps.length){showToast("This action chain has no runnable steps","error");return {started:false,reason:"empty"}}
return acLiveTarget().then((target)=>{
if(!target)return acAskForTarget(ctx).then((picked)=>picked?acRunChain(playbookId,ctx):{started:false,reason:"no-target"})
const missing=acMissingByStep(steps,target.values)
if(!missing.length)return acConfirmAndStart(ctx,steps,target,-1)
return acAskMissing(ctx,target,missing,steps).then((choice)=>{
if(choice==="fill"){acOpenFillForm(target,acUniqueKeys(missing),ctx);return {started:false,reason:"fill"}}
if(choice!=="run")return {started:false,reason:"cancelled"}
return acConfirmAndStart(ctx,steps,target,missing[0].index)
})
})
}).catch((err)=>{
showToast(err&&err.message?err.message:"Could not load the action chain","error")
return {started:false,reason:"error"}
})
}
function acConfirmAndStart(ctx,steps,target,stopAt){
const items=acBuildChainItems(steps,target.values,stopAt)
const runnable=stopAt>=0?items.slice(0,stopAt):items
const risky=runnable.filter((item,i)=>typeof termCommandRisks==="function"&&termCommandRisks(item.command,{noise_level:steps[i].noise_level}).length).length
const notes=[]
if(risky)notes.push("<li>"+risky+" of "+runnable.length+" steps were flagged risky.</li>")
if(stopAt>=0)notes.push("<li>Stops before step "+(stopAt+1)+" - steps "+(stopAt+1)+"-"+items.length+" will be skipped (missing target values).</li>")
const preview=items.map((item,i)=>(stopAt>=0&&i>=stopAt?"-- ":"")+(i+1)+". "+item.command).join("\n")
const body='<div class="term-run-destination">Target <b>'+acEscape(target.name)+"</b>. Steps run one at a time in the background, not in a terminal session.</div>"+(notes.length?'<ul class="term-risk-list">'+notes.join("")+"</ul>":"")+'<pre class="term-run-preview">'+acEscape(preview)+"</pre>"
const ask=typeof termAskChainPolicy==="function"?termAskChainPolicy(acChainTitle(ctx),runnable.length,body,risky>0):Promise.resolve("stop")
return ask.then((policy)=>{
if(!policy)return {started:false,reason:"cancelled"}
const shellSelect=document.getElementById("terminalShellSelect")
const shellId=shellSelect?shellSelect.value:""
return bridgeCall("terminal.chain_start",[shellId,items,policy,"playbook",ctx.name]).then((res)=>{
if(typeof showStatusIsland==="function")showStatusIsland("Running "+acChainTitle(ctx)+" on "+target.name)
const run=acTrackRun(res.chain_id,ctx,target,policy)
if(typeof termRefreshJobs==="function")termRefreshJobs()
if(typeof termStartJobsWatch==="function")termStartJobsWatch()
return {started:true,chain_id:res.chain_id,stop_at:stopAt,policy:policy,target:target.name,run:run?run.chainId:null}
})
}).catch((err)=>{
showToast(err&&err.message?err.message:"Could not start the chain","error")
return {started:false,reason:"error"}
})
}
// ---- Live progress card ----
function acTrackRun(chainId,ctx,target,policy){
const run={chainId:chainId,playbookId:ctx.id,name:ctx.name,caller:ctx.caller,source:ctx.source,target:target?target.name:"",policy:policy,status:null,open:{},outputs:{},views:[],timer:null,collapsed:false}
acState.runs=acState.runs.filter((r)=>r.views.length||r.status&&acRunSummary(r.status).active).concat([run])
if(acState.runs.length>12)acState.runs.splice(0,acState.runs.length-12)
const host=acHostFor(ctx.source)
if(host)acMountRun(run,host)
// The Chains page detail view also shows the run when that chain is open there, wherever the run started.
const chainsHost=document.getElementById("cmdsChainRunHost")
if(chainsHost&&chainsHost!==host&&typeof chainsState!=="undefined"&&String(chainsState.currentId)===String(ctx.id))acMountRun(run,chainsHost)
acPollRun(run)
run.timer=setInterval(()=>acPollRun(run),AC_POLL_MS)
return run
}
function acHostFor(source){
const panel=document.getElementById("terminalPanel")
const panelOpen=panel&&!panel.classList.contains("hidden")
if(source==="chains"||source==="commands"){
const host=document.getElementById("cmdsChainRunHost")
// The host itself is display:none while empty, so test the chain view around it (visible while a chain is open).
if(host&&host.parentElement&&host.parentElement.offsetParent!==null)return host
}
if(source==="terminal"||panelOpen){
if(panel&&panelOpen)return acTerminalHost(panel)
}
return acDockHost()
}
function acTerminalHost(panel){
let host=document.getElementById("acTerminalRuns")
if(!host){
host=document.createElement("div")
host.id="acTerminalRuns"
host.className="ac-runs-overlay"
panel.appendChild(host)
}
return host
}
function acDockHost(){
let host=document.getElementById("acChainDock")
if(!host){
host=document.createElement("div")
host.id="acChainDock"
host.className="ac-runs-dock"
;(document.getElementById("content")||document.body).appendChild(host)
}
return host
}
function acMountRun(run,host){
if(run.views.some((v)=>v.parentNode===host))return
// One card per host: a newer run replaces a finished one in the same spot.
host.querySelectorAll(".ac-run").forEach((el)=>{
const other=acState.runs.find((r)=>r.views.indexOf(el)!==-1)
if(other&&other.status&&acRunSummary(other.status).active&&host.id!=="cmdsChainRunHost")return
if(other)other.views=other.views.filter((v)=>v!==el)
el.remove()
})
const el=document.createElement("div")
el.className="ac-run"
el.dataset.chain=run.chainId
el.addEventListener("click",(e)=>acHandleRunClick(run,el,e))
host.appendChild(el)
run.views.push(el)
acRenderRun(run)
}
function acUnmountView(run,el){
run.views=run.views.filter((v)=>v!==el)
el.remove()
}
// Shows the latest run of a chain inside the Chains page detail view (called by pages/chains.js).
function acShowRunsFor(playbookId,host){
if(!host)return
host.querySelectorAll(".ac-run").forEach((el)=>{
acState.runs.forEach((r)=>{r.views=r.views.filter((v)=>v!==el)})
el.remove()
})
const runs=acState.runs.filter((r)=>String(r.playbookId)===String(playbookId))
if(runs.length)acMountRun(runs[runs.length-1],host)
}
function acPollRun(run){
if(run.polling)return
run.polling=true
bridgeCall("terminal.chain_status",[run.chainId]).then((status)=>{
if(!status){acStopPolling(run);return}
run.status=status
const outs=Object.keys(run.open).filter((key)=>run.open[key]).map((key)=>{
const step=status.steps.find((s)=>s.job_key===key)
if(!step||step.state==="pending"||step.state==="skipped")return null
if(run.outputs[key]!==undefined&&step.state!=="running"&&run.outputs[key+":final"])return null
return bridgeCall("terminal.batch_output",[key,false]).then((text)=>{run.outputs[key]=text||"";if(step.state!=="running")run.outputs[key+":final"]=true}).catch(()=>{})
}).filter(Boolean)
return Promise.all(outs).then(()=>{
acRenderRun(run)
if(!acRunSummary(status).active){
acStopPolling(run)
acRunFinished(run)
}
})
}).catch(()=>{}).then(()=>{run.polling=false})
}
function acStopPolling(run){
if(run.timer)clearInterval(run.timer)
run.timer=null
}
function acRunFinished(run){
const s=acRunSummary(run.status)
if(typeof termRefreshJobs==="function")termRefreshJobs()
if(typeof showStatusIsland==="function")showStatusIsland(acChainTitle(run)+(s.failed?" - "+s.failed+" failed":s.skipped?" - stopped, "+s.skipped+" skipped":" - all "+s.total+" steps done"),s.failed?"error":"")
}
function acRunElapsed(run){
const steps=(run.status&&run.status.steps)||[]
const starts=steps.filter((s)=>s.state!=="pending"&&s.state!=="skipped").map((s)=>acParseTime(s.started_at)).filter((t)=>!isNaN(t))
if(!starts.length)return ""
const start=Math.min.apply(null,starts)
const s=acRunSummary(run.status)
let end=Date.now()
if(!s.active){
const ends=steps.map((x)=>acParseTime(x.ended_at)).filter((t)=>!isNaN(t))
if(ends.length)end=Math.max.apply(null,ends)
}
return acFormatDuration(Math.max(0,end-start))
}
function acStepMeta(step){
if(step.state==="pending")return "pending"
if(step.state==="running")return "running "+acStepDuration(step)
if(step.state==="skipped")return "skipped"
const code=step.exit_code===null||step.exit_code===undefined?"":"exit "+step.exit_code
if(step.state==="done")return [code||"done",acStepDuration(step)].filter(Boolean).join(" - ")
return [step.state==="failed"?code||"failed":step.state,acStepDuration(step)].filter(Boolean).join(" - ")
}
function acRunHtml(run){
const status=run.status
const steps=(status&&status.steps)||[]
const s=acRunSummary(status)
const current=s.running>=0?"Step "+(s.running+1)+" of "+s.total:s.active?"Starting...":s.state==="done"?"All "+s.total+" steps done":s.state==="failed"?s.failed+" failed":"Stopped"
const sub=[current,acRunElapsed(run),run.target?"on "+run.target:""].filter(Boolean).join(" - ")
const actions=(s.active?'<button type="button" class="ac-run-btn ac-run-cancel" data-ac="cancel" title="Cancel the rest of this chain"><i class="icon icon-stop"></i><span>Cancel</span></button>':'<button type="button" class="ac-run-btn" data-ac="again" title="Run this chain again"><i class="icon icon-refresh"></i></button>')+'<button type="button" class="ac-run-btn" data-ac="collapse" title="'+(run.collapsed?"Show steps":"Hide steps")+'"><i class="icon icon-arrow-'+(run.collapsed?"down":"up")+'"></i></button>'+(s.active?"":'<button type="button" class="ac-run-btn" data-ac="close" title="Close"><i class="icon icon-close"></i></button>')
const bar='<div class="ac-run-bar" title="'+s.percent+'%">'+steps.map((step)=>'<span class="ac-seg ac-'+acEscape(step.state)+'"></span>').join("")+"</div>"
const rows=steps.map((step,i)=>{
const open=!!run.open[step.job_key]
const reason=step.state==="skipped"&&step.skip_reason?'<div class="ac-step-reason">'+acEscape(step.skip_reason)+"</div>":""
const out=open?'<pre class="ac-step-out" data-out="'+acEscape(step.job_key)+'">'+acEscape(step.state==="pending"?"Not started yet.":step.state==="skipped"?"This step did not run.":run.outputs[step.job_key]===undefined?"Loading output...":run.outputs[step.job_key]||"(no output)")+"</pre>":""
return '<div class="ac-step ac-'+acEscape(step.state)+(open?" open":"")+'" data-job="'+acEscape(step.job_key)+'" title="Click to '+(open?"hide":"show")+' this step\'s output"><span class="ac-step-mark"></span><span class="ac-step-num">'+(i+1)+'</span><div class="ac-step-main"><div class="ac-step-label">'+acEscape(step.label||"Step "+(i+1))+'</div><div class="ac-step-cmd">'+acEscape(step.command||"")+"</div>"+reason+'</div><span class="ac-step-meta">'+acEscape(acStepMeta(step))+"</span></div>"+out
}).join("")
const foot=s.active?"":'<div class="ac-run-foot"><span>'+[s.done+" done",s.failed?s.failed+" failed":"",s.skipped?s.skipped+" skipped":""].filter(Boolean).join(" - ")+'</span>'+(typeof loyaOpenChain==="function"?'<button type="button" class="ac-run-link" data-ac="open" title="Open this chain on the Chains page">Open chain</button>':"")+'<button type="button" class="ac-run-link" data-ac="jobs">Open in Jobs</button></div>'
return '<div class="ac-run-head"><span class="ac-run-icon"></span><div class="ac-run-titles"><div class="ac-run-name">'+(run.caller?'<span class="ac-run-caller">/'+acEscape(run.caller)+"</span>":"")+acEscape(run.name||"Action chain")+'</div><div class="ac-run-sub">'+acEscape(sub)+'</div></div><div class="ac-run-actions">'+actions+'</div></div>'+bar+'<div class="ac-run-steps">'+rows+"</div>"+foot
}
function acRenderRun(run){
const s=acRunSummary(run.status)
run.views.forEach((el)=>{
const list=el.querySelector(".ac-run-steps")
const listTop=list?list.scrollTop:0
const pins={}
el.querySelectorAll(".ac-step-out").forEach((pre)=>{pins[pre.dataset.out]={top:pre.scrollTop,bottom:pre.scrollTop+pre.clientHeight>=pre.scrollHeight-4}})
el.className="ac-run ac-run-"+s.state+(run.collapsed?" collapsed":"")
el.innerHTML=run.status?acRunHtml(run):'<div class="ac-run-head"><span class="ac-run-icon"></span><div class="ac-run-titles"><div class="ac-run-name">'+acEscape(run.name||"Action chain")+'</div><div class="ac-run-sub">Starting...</div></div></div>'
const newList=el.querySelector(".ac-run-steps")
if(newList)newList.scrollTop=listTop
el.querySelectorAll(".ac-step-out").forEach((pre)=>{
const pin=pins[pre.dataset.out]
pre.scrollTop=!pin||pin.bottom?pre.scrollHeight:pin.top
})
})
}
function acHandleRunClick(run,el,e){
const btn=e.target.closest("[data-ac]")
if(btn){
e.stopPropagation()
const what=btn.dataset.ac
if(what==="cancel"){
bridgeCall("terminal.chain_cancel",[run.chainId]).then(()=>{showStatusIsland("Chain cancelled - remaining steps skipped");acPollRun(run)}).catch((err)=>showToast(err&&err.message?err.message:"Could not cancel the chain","error"))
}else if(what==="close")acUnmountView(run,el)
else if(what==="collapse"){run.collapsed=!run.collapsed;acRenderRun(run)}
else if(what==="again")acRunChain(run.playbookId,{name:run.name,caller:run.caller,source:run.source})
else if(what==="open"&&typeof loyaOpenChain==="function")loyaOpenChain(run.playbookId).catch(()=>{})
else if(what==="jobs"&&typeof termToggleJobsDrawer==="function"){
if(typeof termOpenPanel==="function"&&typeof termState!=="undefined"&&!termState.open)termOpenPanel()
if(typeof termState!=="undefined"&&!termState.jobsOpen)termToggleJobsDrawer()
}
return
}
if(e.target.closest(".ac-step-out"))return
const row=e.target.closest(".ac-step")
if(!row)return
const key=row.dataset.job
run.open[key]=!run.open[key]
acRenderRun(run)
if(run.open[key])bridgeCall("terminal.batch_output",[key,false]).then((text)=>{run.outputs[key]=text||"";acRenderRun(run)}).catch(()=>{})
}
document.addEventListener("DOMContentLoaded",()=>{setTimeout(()=>acRefreshCallers(true),1500)})
if(typeof module!=="undefined"&&module.exports)module.exports={acNormalizeCaller,acCallerError,acSlugifyCaller,acIsSlashTrigger,acMatchCallers,acExactCaller,acPlaceholderKeys,acValueMap,acMissingByStep,acFirstBlockedStep,acResolveCommand,acBuildChainItems,acParseTime,acFormatDuration,acRunSummary,AC_RESERVED_CALLERS}
