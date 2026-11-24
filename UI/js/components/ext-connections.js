// Settings > AI > Agents > Connections: connect the operator's OWN official Claude Code / Codex CLI to LOYA NG (like the VS Code
// extensions do). The operator signs in to the CLI with the vendor's own flow; LOYA NG never sees or stores those credentials.
// LOYA NG registers its MCP server in the CLI (the CLI's own `mcp add`) and installs the LOYA skills. Backend: ext_connections_service.py.
// A missing CLI can be installed by hand (official commands with Copy) or by the setup assistant: a step-by-step dialog where every
// step (prerequisites, install, verify, sign in, connect, test) shows what it will do and waits for Approve or Cancel.
// The pure helpers between the two markers are loaded by tests/js/ext_connections.js - keep them free of DOM and bridge calls.
// ---- conn pure start
const CONN_TOOLS=["claude_code","codex_cli"]
const CONN_STEPS=[
{id:"prereq",title:"Check prerequisites"},
{id:"install",title:"Install"},
{id:"verify",title:"Verify the install"},
{id:"signin",title:"Sign in"},
{id:"connect",title:"Connect to LOYA NG"},
{id:"test",title:"Test connection"}]
function connSigninPill(st){
if(!st||!st.installed)return {text:"Not installed",cls:"not_installed"}
const s=st.signin&&st.signin.state
if(s==="signed_in")return {text:"Signed in",cls:"online"}
if(s==="signed_out")return {text:"Not signed in",cls:"offline"}
return {text:"Could not check sign-in",cls:"",title:(st.signin&&st.signin.detail)||"LOYA NG could not check the sign-in"}
}
// The sign-in state as one word: signed_in | signed_out | unknown ("could not check" is never shown as signed out).
function connSigninState(st){
const s=st&&st.signin&&st.signin.state
return s==="signed_in"||s==="signed_out"?s:"unknown"
}
// The "what next" line under an installed CLI, from the state the backend just reported.
function connNextText(st){
if(!st||!st.installed)return "Not found. Install it, then press Check again."
const s=connSigninState(st)
const last=st.signin&&st.signin.last
if(st.connected){
if(s==="signed_in")return "Signed in and connected to LOYA NG."
if(s==="signed_out")return "Connected to LOYA NG, but not signed in: Sign in to use it."
return "Connected to LOYA NG. "+(last==="signed_in"?"The sign-in could not be checked this time (it was signed in before); press Refresh to try again.":"The sign-in could not be checked; press Refresh to try again.")
}
if(s==="signed_in")return "Signed in. Next: Connect to LOYA NG."
if(s==="signed_out")return "Next: Sign in, then Connect to LOYA NG."
return (last==="signed_in"?"The sign-in could not be checked this time (it was signed in before). ":"The sign-in could not be checked. ")+"Press Refresh to try again, or Connect to LOYA NG now."
}
function connLinkPill(st){
if(!st||!st.connected)return {text:"Not connected",cls:""}
return {text:"Connected to LOYA NG",cls:"online"}
}
// The LOYA terminal shell to run a command in: a native shell (never a WSL distro: the Windows CLI is not on its PATH).
function connPickShell(shells,platform){
const ids=(shells||[]).map((s)=>s&&s.id).filter(Boolean)
const order=platform==="windows"?["pwsh","powershell","cmd"]:["shell"]
for(const id of order)if(ids.includes(id))return id
return ids.find((id)=>id.indexOf("wsl:")!==0)||""
}
function connStepsText(steps){
return (steps||[]).map((s)=>(s.ok?"OK  ":"NO  ")+s.name+(s.detail?" - "+s.detail:"")).join("\n")
}
// Shell family for showing a command: posix on Linux, PowerShell first on Windows (cmd as the alternative).
function connCommandFor(method,family){
const c=(method&&method.commands)||{}
return c[family]||c.ps||c.posix||c.cmd||""
}
function connPickMethod(methods){
const m=(methods||[]).find((x)=>x&&x.auto)
return m?m.id:""
}
// Is a step already satisfied by the CLI's current state? (Shown as "already done" with Continue / Cancel.)
function connStepDone(id,st){
st=st||{}
if(id==="prereq"||id==="install"||id==="verify")return !!st.installed
if(id==="signin")return !!(st.signin&&st.signin.state==="signed_in")
if(id==="connect")return !!st.connected
return false
}
// Where to resume: the first step that is not done yet. Never earlier than verify once the CLI is installed.
function connResumeIndex(st){
for(let i=0;i<CONN_STEPS.length;i++)if(!connStepDone(CONN_STEPS[i].id,st))return i
return CONN_STEPS.length-1
}
// Where a reopened assistant starts: the step the operator reached last time (kept for this app session), unless the
// CLI's state says an earlier step is needed again. Without the CLI, never past "Verify the install".
function connResumeStart(st,last){
const s=connResumeIndex(st)
if(typeof last!=="number"||last<=s)return s
return st&&st.installed?Math.min(last,CONN_STEPS.length-1):Math.min(last,2)
}
// ---- background steps
// Every CLI call (and the MCP server start) is a backend job: the start call returns at once, then short polls follow,
// so a slow or hung CLI never holds a bridge call and the page stays usable. Cancel stops waiting at once.
const CONN_CANCELLED={cancelled:true}
function connIsCancel(e){return e===CONN_CANCELLED||!!(e&&e.cancelled===true&&!e.message)}
function connErrText(e){return e&&e.message?e.message:String(e||"Failed")}
function connCancelToken(){
let fire=null
const t={cancelled:false}
t.promise=new Promise((r)=>{fire=r})
t.cancel=()=>{if(!t.cancelled){t.cancelled=true;fire(CONN_CANCELLED)}}
return t
}
// call(path,args) is bridgeCall. o.token (connCancelToken) cancels; o.onTick(poll) sees each poll; o.every: poll period ms.
// Resolves the step's result; rejects an Error with the backend's message, or CONN_CANCELLED.
async function connJobRun(call,kind,tool,o){
o=o||{}
const tok=o.token||connCancelToken()
const sleep=o.sleep||((ms)=>new Promise((r)=>setTimeout(r,ms)))
const race=(p)=>Promise.race([Promise.resolve(p),tok.promise])
if(tok.cancelled)throw CONN_CANCELLED
const startP=Promise.resolve(call("extAgents.connection_job_start",[kind,tool]))
const started=await race(startP)
if(started===CONN_CANCELLED){startP.then((s)=>s&&s.job&&call("extAgents.connection_job_cancel",[s.job])).catch(()=>{});throw CONN_CANCELLED}
const id=started&&started.job
if(!id)throw new Error("The step did not start.")
for(;;){
const r=await race(Promise.resolve(sleep(o.every||300)).then(()=>tok.cancelled?CONN_CANCELLED:call("extAgents.connection_job_poll",[id])))
if(r===CONN_CANCELLED){
// Tell the backend first (bounded: a stuck bridge never holds Cancel up), so a step started next sees it cancelled.
await Promise.race([Promise.resolve(call("extAgents.connection_job_cancel",[id])).catch(()=>{}),sleep(1500)])
throw CONN_CANCELLED
}
if(o.onTick)try{o.onTick(r||{})}catch(e){}
if(!r||!r.done)continue
if(r.cancelled)throw CONN_CANCELLED
if(r.ok===false)throw new Error(r.error||"Failed")
return r.result
}
}
// The flow. o.ask(view) resolves "approve" or anything else (= Cancel). o.act[id](status) runs a step and may return
// {retry:true} (ask the same step again, e.g. the install is not finished yet), {stop:true}, or {info} (a result line shown
// on the next step). Nothing runs without "approve". A step or status check that fails is shown on the same step (Approve
// tries again); one cancelled while it runs (rejects CONN_CANCELLED) ends the flow as {cancelled, running:true}.
async function connRunWizard(o){
let i=Math.max(0,Math.min(CONN_STEPS.length-1,o.start||0))
let note="",info="",st=null
while(i<CONN_STEPS.length){
const step=CONN_STEPS[i]
let failed=""
try{st=await o.status()}
catch(e){if(connIsCancel(e))return {cancelled:true,running:true,index:i};failed=connErrText(e)}
if(failed){
const a=await o.ask({index:i,step,status:st||{},done:false,note:failed,info:"",statusFailed:true})
if(a!=="approve")return {cancelled:true,index:i}
continue
}
const done=connStepDone(step.id,st)
const answer=await o.ask({index:i,step,status:st,done,note,info})
note="";info=""
if(answer!=="approve")return {cancelled:true,index:i}
if(!done){
let r
try{r=(await o.act[step.id](st))||{}}
catch(e){
if(connIsCancel(e))return {cancelled:true,running:true,index:i}
note=connErrText(e);continue
}
if(r.stop)return {stopped:true,index:i,message:r.message||""}
if(r.retry){note=r.message||"";continue}
if(step.id==="test")return {done:true,index:i,result:r}
info=r.info||""
}
i++
}
return {done:true,index:CONN_STEPS.length-1}
}
// ---- conn pure end
const connState={root:null,overview:null,busy:{},wizardOpen:false,reached:{}}
function connEsc(s){return String(s===undefined||s===null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")}
function connErr(err){return err&&err.message?err.message:String(err||"Failed")}
function connPlatform(){return connState.overview&&connState.overview.platform||"linux"}
function connMountSettings(root){
root=root||document.getElementById("setExtConnectionsRoot")
if(!root)return Promise.resolve()
connState.root=root
if(!root.innerHTML)root.innerHTML='<div class="set-status">Looking for Claude Code and Codex</div>'
return connJobRun(bridgeCall,"overview",null).then((ov)=>{connState.overview=ov;connRender(root,ov)}).catch((err)=>{root.innerHTML=`<div class="set-status error">${connEsc(connErr(err))}</div>`})
}
function connStatus(tool,msg,isError,steps){
const el=connState.root&&connState.root.querySelector(`.conn-status[data-tool="${tool}"]`)
if(!el)return
el.classList.toggle("error",!!isError)
if(steps&&steps.length){
el.innerHTML=`<div>${connEsc(msg||"")}</div><ul class="conn-steps">${steps.map((s)=>`<li class="${s.ok?"ok":"bad"}">${connEsc(s.name)}${s.detail?" - "+connEsc(s.detail):""}</li>`).join("")}</ul>`
return
}
el.textContent=msg||""
}
function connCopy(text){
const done=()=>{if(typeof showStatusIsland==="function")showStatusIsland("Copied","success")}
const fallback=()=>{
const ta=document.createElement("textarea");ta.value=text;ta.setAttribute("readonly","");ta.style.position="fixed";ta.style.opacity="0"
document.body.appendChild(ta);ta.select()
let ok=false;try{ok=document.execCommand("copy")}catch(e){ok=false}
ta.remove()
if(ok)done();else if(typeof showStatusIsland==="function")showStatusIsland("Could not copy - select the command and copy it","error")
}
if(navigator.clipboard&&navigator.clipboard.writeText)navigator.clipboard.writeText(text).then(done).catch(fallback)
else fallback()
}
function connCmdRow(label,cmd){
return `<div class="conn-cmd"><span class="conn-cmd-label">${connEsc(label)}</span><pre>${connEsc(cmd)}</pre><button type="button" class="set-btn conn-copy" data-copy="${connEsc(cmd)}" aria-label="Copy: ${connEsc(cmd)}">Copy</button></div>`
}
function connMissingHtml(m){
const miss=(m.missing||[]).map((x)=>`Needs ${connEsc(x.name)}${x.url?` (<button type="button" class="set-link-btn conn-link" data-url="${connEsc(x.url)}">get it</button>)`:""}`)
if(m.problem)miss.push(connEsc(m.problem))
return miss.length?`<div class="conn-missing">${miss.join(" | ")}</div>`:""
}
function connMethodHtml(m,platform){
const fam=platform==="windows"?[["ps","PowerShell"],["cmd","Command Prompt"]]:[["posix","Terminal"]]
const rows=fam.filter(([f])=>m.commands[f]).map(([f,l])=>connCmdRow(l,m.commands[f])).join("")
return `<div class="conn-method"><div class="conn-method-head"><b>${connEsc(m.label)}</b> <span class="conn-src">from <code>${connEsc(m.source)}</code></span></div>${rows}<div class="conn-method-note">${connEsc(m.note)}</div>${connMissingHtml(m)}</div>`
}
function connBox(st,platform){
const signin=connSigninPill(st)
const link=connLinkPill(st)
let body
if(!st.installed){
body=`<div class="conn-install"><span>${connEsc(st.label)} (${connEsc(st.vendor)}'s official CLI) was not found on this computer${platform==="windows"?" (looked in PATH, %APPDATA%\\npm and the installer folders)":" (looked in PATH and the usual install folders)"}.</span>
<div class="conn-actions"><button type="button" class="set-btn conn-wizard" data-tool="${st.tool}" title="A step-by-step assistant: every step waits for your Approve">Install for me</button><button type="button" class="set-btn conn-refresh" data-tool="${st.tool}">Check again</button></div>
<details class="conn-manual"><summary>Install manually</summary>
<p class="set-info">Run one of the vendor's official commands yourself, then press Check again. None of them needs sudo or Administrator rights.</p>
${(st.install_methods||[]).map((m)=>connMethodHtml(m,platform)).join("")}
<div class="conn-actions"><button type="button" class="set-btn conn-docs" data-tool="${st.tool}">Official install docs</button></div>
</details></div>`
}else{
const next=!st.connected||connSigninState(st)!=="signed_in"?connNextText(st):""
body=`<dl class="conn-facts"><dt>Path</dt><dd><code>${connEsc(st.path)}</code></dd><dt>Version</dt><dd>${connEsc(st.version||"unknown")}</dd>
<dt>Sign-in</dt><dd>${connEsc(st.signin&&st.signin.detail||"")}</dd>
<dt>LOYA tools</dt><dd>${st.connected?`MCP server <code>${connEsc(st.server_name)}</code> in your ${connEsc(st.label)} config${st.skills&&st.skills.length?"; skills "+connEsc(st.skills.join(", "))+" in <code>"+connEsc(st.skills_dir)+"</code>":""}`:"not connected"}</dd></dl>
${next?`<div class="conn-next">${connEsc(next)}</div>`:""}
<div class="conn-actions">
${!st.connected?`<button type="button" class="set-btn conn-wizard" data-tool="${st.tool}" title="Continue step by step from where you are">Set up</button>`:""}
<button type="button" class="set-btn conn-signin" data-tool="${st.tool}" title="Opens a terminal running: ${connEsc(st.login_command||"")}">${connSigninState(st)==="signed_in"?"Sign in again":"Sign in"}</button>
${st.connected?`<button type="button" class="set-btn conn-connect" data-tool="${st.tool}" title="Register LOYA NG's MCP server again and update the LOYA skills">Update connection</button><button type="button" class="set-btn conn-test" data-tool="${st.tool}">Test connection</button><button type="button" class="set-btn danger conn-disconnect" data-tool="${st.tool}">Disconnect</button>`:`<button type="button" class="set-btn conn-connect" data-tool="${st.tool}">Connect to LOYA NG</button>`}
<button type="button" class="set-btn conn-refresh" data-tool="${st.tool}">Refresh</button>
</div>`
}
return `<div class="ai-provider-box conn-box" data-tool="${st.tool}">
<div class="ai-provider-head"><span>${connEsc(st.label)}</span><span class="conn-pills"><span class="ai-status-pill ${signin.cls}"${signin.title?` title="${connEsc(signin.title)}"`:""}>${connEsc(signin.text)}</span>${st.installed?`<span class="ai-status-pill ${link.cls}">${connEsc(link.text)}</span>`:""}</span></div>
${body}
<div class="set-status conn-status" data-tool="${st.tool}" role="status"></div>
</div>`
}
function connRender(root,ov){
root.innerHTML=`<p class="set-info">Use your own Claude Code or Codex account, the way the VS Code extensions do: you sign in to the official CLI yourself, and <b>Connect to LOYA NG</b> adds LOYA NG's tools and skills to it. Claude Code / Codex then run on your own subscription or key, and LOYA NG's AI Roles still decide every tool call they make here.</p>
${CONN_TOOLS.filter((t)=>ov.tools[t]).map((t)=>connBox(ov.tools[t],ov.platform)).join("")}
<p class="set-info">LOYA NG never reads or stores the CLI's sign-in. Connect runs the CLI's own <code>mcp add</code> (user scope, server name <code>loya-note</code>); Disconnect removes it and revokes the connection's token. The CLI reaches LOYA NG only while LOYA NG is open and unlocked.</p>`
connWire(root)
}
function connBusy(tool,on){
connState.busy[tool]=on
if(!connState.root)return
connState.root.querySelectorAll(`.conn-box[data-tool="${tool}"] button`).forEach((b)=>{b.disabled=!!on})
}
function connAfter(tool,res,okMsg){
return connMountSettings(connState.root).then(()=>connStatus(tool,res&&res.message||okMsg,false))
}
function connUseLoyaTerminal(){
return typeof termState!=="undefined"&&termState.enabled&&typeof termNewTab==="function"&&typeof termOpenForRun==="function"
}
function connLoyaShell(){return connUseLoyaTerminal()?connPickShell(termState.shells,connPlatform()):""}
// Opens the CLI's own sign-in. Returns a short "where" text.
function connOpenSignIn(tool){
const st=connState.overview&&connState.overview.tools[tool]
const label=st?st.label:"CLI"
const viaOs=()=>bridgeCall("extAgents.connection_sign_in_os",[tool]).then((r)=>r.terminal)
const shell=connLoyaShell()
if(!shell)return viaOs()
return bridgeCall("extAgents.connection_sign_in_command",[tool,shell]).then((line)=>{
if(!line)return viaOs()
return termOpenForRun().then(()=>termNewTab(shell,{name:label+" sign-in",startup:line})).then(()=>"the LOYA NG terminal")
})
}
function connSignIn(tool){
const st=connState.overview&&connState.overview.tools[tool]
return connOpenSignIn(tool).then((where)=>connStatus(tool,"Opened "+where+". Finish "+(st?st.label:"the CLI")+"'s own sign-in there, then press Refresh.",false))
}
function connWire(root){
const on=(cls,fn)=>root.querySelectorAll(cls).forEach((b)=>b.addEventListener("click",()=>{
const tool=b.dataset.tool
if(connState.busy[tool])return
connBusy(tool,true)
Promise.resolve().then(()=>fn(tool)).catch((err)=>connStatus(tool,connErr(err),true)).finally(()=>connBusy(tool,false))
}))
on(".conn-refresh",(tool)=>connMountSettings(root).then(()=>{
const st=connState.overview.tools[tool]
connStatus(tool,st&&st.installed?"Found "+st.label+". "+connNextText(st):"Still not found.",!(st&&st.installed))
}))
on(".conn-docs",(tool)=>bridgeCall("notes.open_url",[connState.overview.tools[tool].docs]))
on(".conn-signin",connSignIn)
on(".conn-connect",(tool)=>{
connStatus(tool,"Connecting: starting LOYA NG's MCP server and registering it in the CLI",false)
return connJobRun(bridgeCall,"connect",tool).then((r)=>connAfter(tool,r,"Connected."))
})
on(".conn-disconnect",(tool)=>{
const st=connState.overview.tools[tool]
return appConfirm("Disconnect "+st.label+" from LOYA NG? This removes the loya-note MCP server from its config, revokes its token and removes the LOYA skills you have not edited.",{okLabel:"Disconnect",danger:true}).then((yes)=>{
if(!yes)return null
connStatus(tool,"Disconnecting",false)
return connJobRun(bridgeCall,"disconnect",tool).then((r)=>connAfter(tool,r,"Disconnected."))
})
})
on(".conn-test",(tool)=>{
connStatus(tool,"Testing the connection",false)
return connJobRun(bridgeCall,"test",tool).then((r)=>connStatus(tool,r.message,!r.ok,r.steps))
})
on(".conn-wizard",(tool)=>connWizard(tool))
root.querySelectorAll(".conn-copy").forEach((b)=>b.addEventListener("click",()=>connCopy(b.dataset.copy)))
root.querySelectorAll(".conn-link").forEach((b)=>b.addEventListener("click",()=>bridgeCall("notes.open_url",[b.dataset.url]).catch(()=>{})))
}
// ---------------------------------------------------------------- setup assistant (modal, one Approve per step)
// While a step runs the dialog shows it (spinner, text, seconds) and Cancel stays live: it stops waiting at once and the
// backend stops the CLI. Errors stay on the step, with Approve to try again.
function connWizard(tool){
if(connState.wizardOpen)return Promise.resolve()
const st0=connState.overview.tools[tool]
const label=st0.label
const w={method:"",plan:null,installedVia:"",testResult:null}
const before=document.activeElement
const overlay=document.createElement("div")
overlay.className="confirm-overlay conn-wiz-overlay"
const box=document.createElement("div")
box.className="confirm-box confirm-box-wide glass-panel conn-wiz"
box.setAttribute("role","dialog")
box.setAttribute("aria-modal","true")
const titleId="connWizTitle"+Date.now().toString(36)
box.setAttribute("aria-labelledby",titleId)
box.innerHTML=`<div class="confirm-message" id="${titleId}">Set up ${connEsc(label)}</div>
<ol class="conn-wiz-steps">${CONN_STEPS.map((s,i)=>`<li data-i="${i}"><span class="conn-wiz-num">${i+1}</span><span>${connEsc(s.title)}</span></li>`).join("")}</ol>
<div class="conn-wiz-body" aria-live="polite"></div>
<div class="confirm-actions"><button type="button" class="confirm-cancel">Cancel</button><button type="button" class="confirm-ok">Approve</button></div>`
overlay.appendChild(box)
document.body.appendChild(overlay)
connState.wizardOpen=true
const bodyEl=box.querySelector(".conn-wiz-body")
const okBtn=box.querySelector(".confirm-ok")
const cancelBtn=box.querySelector(".confirm-cancel")
let answer=null   // set while a step waits for Approve / Cancel
let running=null  // the cancel token of what is running now
const cancel=()=>{if(answer){answer("cancel");return}if(running)running.cancel()}
const onKey=(e)=>{if(typeof confirmTrapKey==="function")confirmTrapKey(e,box,cancel);else if(e.key==="Escape"){e.preventDefault();cancel()}}
document.addEventListener("keydown",onKey,true)
okBtn.addEventListener("click",()=>answer&&answer("approve"))
cancelBtn.addEventListener("click",cancel)
const close=()=>{if(running)running.cancel();document.removeEventListener("keydown",onKey,true);overlay.remove();connState.wizardOpen=false;if(before&&before.focus)try{before.focus()}catch(e){}}
const markSteps=(index,status)=>box.querySelectorAll(".conn-wiz-steps li").forEach((li)=>{
const i=Number(li.dataset.i)
li.classList.toggle("current",i===index)
li.classList.toggle("done",i<index||(i!==index&&connStepDone(CONN_STEPS[i].id,status)))
if(i===index)li.setAttribute("aria-current","step");else li.removeAttribute("aria-current")
})
// The running state: spinner, what is happening and for how long. Approve is off, Cancel stays on.
const busy=(text)=>{
const tok=connCancelToken()
running=tok
okBtn.disabled=true;cancelBtn.disabled=false
const el=document.createElement("div")
el.className="conn-wiz-running";el.setAttribute("role","status")
el.innerHTML=`<span class="conn-wiz-spin" aria-hidden="true"></span><span class="conn-wiz-running-text">${connEsc(text)}</span><span class="conn-wiz-elapsed">0 s</span>`
bodyEl.appendChild(el)
try{el.scrollIntoView({block:"nearest"})}catch(e){}
if(document.activeElement===okBtn||!box.contains(document.activeElement))cancelBtn.focus()
const t0=Date.now()
const timer=setInterval(()=>{
const sec=Math.round((Date.now()-t0)/1000)
el.querySelector(".conn-wiz-elapsed").textContent=sec+" s"
if(sec===20)el.querySelector(".conn-wiz-running-text").textContent=text+". Still working; Cancel stops waiting."
},1000)
tok.finish=()=>{clearInterval(timer);el.remove();if(running===tok)running=null}
return tok
}
const job=(kind,text)=>{const tok=busy(text);return connJobRun(bridgeCall,kind,tool,{token:tok}).finally(()=>tok.finish())}
const wait=(p,text)=>{const tok=busy(text);return Promise.race([Promise.resolve(p),tok.promise.then(()=>{throw CONN_CANCELLED})]).finally(()=>tok.finish())}
const status=()=>job("status","Checking "+label+": version, sign-in and connection").then((st)=>{connState.overview.tools[tool]=st;return st})
const head=(v)=>`<div class="conn-wiz-title">Step ${v.index+1} of ${CONN_STEPS.length}: ${connEsc(v.step.title)}</div>`
const waitAnswer=()=>new Promise((resolve)=>{answer=(a)=>{answer=null;okBtn.disabled=true;resolve(a)}})
// Builds the step's text (loading what it needs first), then waits for Approve / Cancel.
const ask=(v)=>{
markSteps(v.index,v.status)
okBtn.disabled=true
okBtn.textContent=v.done?"Continue":"Approve"
if(v.statusFailed){
bodyEl.innerHTML=`${head(v)}<div class="set-status error">Could not check ${connEsc(label)}: ${connEsc(v.note)}</div><p class="set-info">Approve checks again. Cancel closes the assistant.</p>`
okBtn.textContent="Check again";okBtn.disabled=false;okBtn.focus()
return waitAnswer()
}
bodyEl.innerHTML=head(v)
return wait(connStepView(tool,v,w),"Preparing this step").then((html)=>{
bodyEl.innerHTML=`${head(v)}${v.info?`<div class="set-status conn-wiz-ok">${connEsc(v.info)}</div>`:""}${v.note?`<div class="set-status error">${connEsc(v.note)}</div>`:""}${html.body}`
bodyEl.querySelectorAll(".conn-copy").forEach((b)=>b.addEventListener("click",()=>connCopy(b.dataset.copy)))
bodyEl.querySelectorAll(".conn-link").forEach((b)=>b.addEventListener("click",()=>bridgeCall("notes.open_url",[b.dataset.url]).catch(()=>{})))
bodyEl.querySelectorAll('input[name="connWizMethod"]').forEach((r)=>r.addEventListener("change",()=>{w.method=r.value;w.plan=null}))
okBtn.textContent=html.ok||(v.done?"Continue":"Approve")
okBtn.disabled=!!html.blocked
;(okBtn.disabled?cancelBtn:okBtn).focus()
return waitAnswer()
}).catch((err)=>{
if(connIsCancel(err))return "cancel"
bodyEl.innerHTML=`${head(v)}<div class="set-status error">${connEsc(connErr(err))}</div><p class="set-info">Cancel closes the assistant; open it again to retry.</p>`
okBtn.disabled=true;cancelBtn.focus()
return waitAnswer()
})
}
const act={
prereq:()=>{if(!w.method)return {retry:true,message:"Pick an install method that is ready to use."}},
install:()=>{
const p=w.plan
w.plan=null  // single use
if(!p)return {retry:true,message:"The install command expired. Approve again to run it."}
const shell=connLoyaShell()
const run=shell&&p.use_shell===shell?bridgeCall("extAgents.connection_install_command",[tool,p.method,shell,p.token]).then((line)=>termOpenForRun().then(()=>termNewTab(shell,{name:label+" install",startup:line})).then(()=>"the LOYA NG terminal"))
:bridgeCall("extAgents.connection_install_os",[tool,p.method,p.token]).then((r)=>r.terminal)
return wait(run,"Opening the terminal").then((where)=>{w.installedVia=where;return {info:"The installer is running in "+where+"."}})
},
verify:()=>job("detect","Looking for "+label+" in PATH and the install folders").then((d)=>d.installed?{info:"Found "+label+" at "+d.path+"."}:{retry:true,message:"Not found yet. Wait for the installer to finish in "+(w.installedVia||"the terminal")+", then press Check again."}),
signin:()=>wait(connOpenSignIn(tool),"Opening "+label+"'s own sign-in").then((where)=>{w.signinVia=where;return {info:"Opened "+where+" with "+label+"'s sign-in. Finish it there; you can connect now and sign in later."}}),
connect:()=>job("connect","Connecting: starting LOYA NG's MCP server, registering it in "+label+" and installing the LOYA skills").then((r)=>({info:(r&&r.message)||label+" is connected."})),
test:()=>job("test","Testing: the registration in "+label+", LOYA NG's MCP server and a tool list through the bridge").then((r)=>{w.testResult=r;return r})
}
const finish=(res)=>{
const tail=()=>connMountSettings(connState.root)
if(res.cancelled){
connState.reached[tool]=res.index;close()
const where="step "+(res.index+1)+" ("+CONN_STEPS[res.index].title+")"
const reopen=" Open the assistant again ("+(connState.overview.tools[tool].installed?"Set up":"Install for me")+") to continue from there."
const msg=res.running?"Cancelled during "+where+": LOYA NG stopped waiting and stopped the CLI. Nothing else was run."+reopen:"Setup stopped at "+where+". Nothing else was run."+reopen
return tail().then(()=>connStatus(tool,msg,false),()=>connStatus(tool,msg,false))
}
delete connState.reached[tool]
if(!res.done){close();return tail()}
const r=res.result||{}
markSteps(CONN_STEPS.length,{})
bodyEl.innerHTML=`<div class="conn-wiz-title">${r.ok?"All set":"Set up, but the test found a problem"}</div><div class="set-status${r.ok?"":" error"}">${connEsc(r.message||"")}</div><ul class="conn-steps">${(r.steps||[]).map((s)=>`<li class="${s.ok?"ok":"bad"}">${connEsc(s.name)}${s.detail?" - "+connEsc(s.detail):""}</li>`).join("")}</ul>`
cancelBtn.classList.add("hidden")
okBtn.textContent="Done";okBtn.disabled=false;okBtn.focus()
return new Promise((resolve)=>{answer=()=>{answer=null;resolve()}}).then(()=>{close();return tail()})
}
const first=()=>status().catch((e)=>{if(connIsCancel(e))throw e;return st0})
return first().then((st)=>connRunWizard({start:connResumeStart(st,connState.reached[tool]),status,ask,act})).then(finish).catch((err)=>{
if(connIsCancel(err))return finish({cancelled:true,running:true,index:connResumeStart(st0,connState.reached[tool])})
close();connStatus(tool,connErr(err),true)
})
}
// What each step shows. Returns {body, ok?:primary label, blocked?:true when Approve cannot be pressed}.
function connStepView(tool,v,w){
const st=v.status
const already=(text)=>Promise.resolve({body:`<p class="conn-wiz-done">Already done: ${connEsc(text)}</p><p class="set-info">Continue to the next step, or Cancel to stop here.</p>`})
const platform=connPlatform()
if(v.step.id==="prereq"){
if(v.done)return already(st.label+" is installed at "+st.path+".")
const methods=st.install_methods||[]
if(!w.method)w.method=connPickMethod(methods)
const rows=methods.map((m)=>`<label class="conn-wiz-method${m.auto?"":" off"}"><input type="radio" name="connWizMethod" value="${connEsc(m.id)}"${m.id===w.method?" checked":""}${m.auto?"":" disabled"}><span><b>${connEsc(m.label)}</b>${m.auto?" - ready":m.available?" - run it yourself (Install manually)":" - not ready"}${connMissingHtml(m)}</span></label>`).join("")
const ready=methods.some((m)=>m.auto)
return Promise.resolve({body:`<p>LOYA NG checked what each official install route needs on this ${platform==="windows"?"Windows":"Linux"} computer:</p><div class="conn-wiz-methods">${rows}</div>${ready?'<p class="set-info">Approve to continue with the selected route. Nothing is installed yet.</p>':'<p class="set-status error">No route is ready. Install the missing prerequisite (links above), or use Install manually, then open this assistant again.</p>'}`,blocked:!ready})
}
if(v.step.id==="install"){
if(v.done)return already(st.label+" is installed.")
if(!w.method)w.method=connPickMethod(st.install_methods)  // resumed here: the recommended ready route
const shell=connLoyaShell()
return bridgeCall("extAgents.connection_install_plan",[tool,w.method,shell]).then((p)=>{
const useLoya=!!shell&&p.use_loya_terminal
p.use_shell=useLoya?shell:""
w.plan=p
const cmd=useLoya?p.command:p.os_command
return {body:`<p>Approve opens ${useLoya?"a LOYA NG terminal tab":"your OS terminal"} and runs this official command:</p>${connCmdRow(p.label,cmd)}
<dl class="conn-facts"><dt>Source</dt><dd><code>${connEsc(p.source)}</code></dd><dt>Docs</dt><dd><button type="button" class="set-link-btn conn-link" data-url="${connEsc(p.docs)}">${connEsc(p.docs)}</button></dd></dl>
<p class="conn-wiz-warn">${connEsc(p.warning)}</p><p class="set-info">${connEsc(p.note)}</p>`,ok:"Approve and run"}
})
}
if(v.step.id==="verify"){
if(v.done)return Promise.resolve({body:`<p class="conn-wiz-done">Found ${connEsc(st.label)}${st.version?" "+connEsc(st.version):""} at <code>${connEsc(st.path)}</code>.</p><p class="set-info">Continue to sign in.</p>`})
return Promise.resolve({body:`<p>Wait until the installer in ${connEsc(w.installedVia||"the terminal")} says it is done, then check again. LOYA NG looks in PATH and the folders the installer uses.</p>`,ok:"Check again"})
}
if(v.step.id==="signin"){
if(v.done)return already(st.signin.detail||"signed in")
if(connSigninState(st)==="unknown")return Promise.resolve({body:`<div class="set-status error">${connEsc(st.signin&&st.signin.detail||"LOYA NG could not check the sign-in.")}</div><p>This does not mean you are signed out${st.signin&&st.signin.last==="signed_in"?" (the last check said you were signed in)":""}. If you already signed in, press Cancel and then Refresh on the card. Approve opens ${connEsc(st.label)}'s own sign-in anyway:</p>${connCmdRow("Command",st.login_command||"")}`,ok:"Open the sign-in"})
return Promise.resolve({body:`<p>Approve opens a terminal running ${connEsc(st.label)}'s own sign-in:</p>${connCmdRow("Command",st.login_command||"")}<p class="set-info">You complete the vendor's browser sign-in yourself; LOYA NG never sees or stores it. Come back here when it says you are signed in.</p>`})
}
if(v.step.id==="connect"){
if(v.done)return already(st.label+" already has LOYA NG's MCP server.")
return bridgeCall("extAgents.connection_connect_preview",[tool]).then((p)=>({body:`<p>Approve registers LOYA NG's MCP server in your ${connEsc(st.label)} user config with its own command:</p>${connCmdRow("Command",p.command)}<p class="set-info">It also installs the LOYA skills (${connEsc(p.skills.join(", "))}) in <code>${connEsc(p.skills_dir)}</code>. ${connEsc(st.label)} then runs on your own account, and LOYA NG's AI Roles decide every tool call.</p>${connSigninState(st)==="signed_out"?'<p class="set-info">You are not signed in yet; you can still connect and sign in later.</p>':connSigninState(st)==="unknown"?'<p class="set-info">LOYA NG could not check the sign-in; you can still connect.</p>':""}`}))
}
return Promise.resolve({body:`<p>Approve runs a check of the whole path: the registration in ${connEsc(st.label)}, LOYA NG's MCP server, and a real tool list through the bridge.</p>`,ok:"Run the test"})
}
