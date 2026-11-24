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
return {text:"Sign-in unknown",cls:""}
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
// The flow. o.ask(view) resolves "approve" or anything else (= Cancel). o.act[id](status) runs a step and may return
// {retry:true} (ask the same step again, e.g. the install is not finished yet) or {stop:true}. Nothing runs without "approve".
async function connRunWizard(o){
let i=Math.max(0,Math.min(CONN_STEPS.length-1,o.start||0))
let note=""
while(i<CONN_STEPS.length){
const step=CONN_STEPS[i]
const st=await o.status()
const done=connStepDone(step.id,st)
const answer=await o.ask({index:i,step,status:st,done,note})
note=""
if(answer!=="approve")return {cancelled:true,index:i}
if(!done){
const r=(await o.act[step.id](st))||{}
if(r.stop)return {stopped:true,index:i,message:r.message||""}
if(r.retry){note=r.message||"";continue}
if(step.id==="test")return {done:true,index:i,result:r}
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
if(!root.innerHTML)root.innerHTML='<div class="set-status">Looking for Claude Code and Codex...</div>'
return bridgeCall("extAgents.connections").then((ov)=>{connState.overview=ov;connRender(root,ov)}).catch((err)=>{root.innerHTML=`<div class="set-status error">${connEsc(connErr(err))}</div>`})
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
const next=!st.connected?(st.signin&&st.signin.state==="signed_in"?"Next: Connect to LOYA NG.":"Next: Sign in, then Connect to LOYA NG."):""
body=`<dl class="conn-facts"><dt>Path</dt><dd><code>${connEsc(st.path)}</code></dd><dt>Version</dt><dd>${connEsc(st.version||"unknown")}</dd>
<dt>Sign-in</dt><dd>${connEsc(st.signin&&st.signin.detail||"")}</dd>
<dt>LOYA tools</dt><dd>${st.connected?`MCP server <code>${connEsc(st.server_name)}</code> in your ${connEsc(st.label)} config${st.skills&&st.skills.length?"; skills "+connEsc(st.skills.join(", "))+" in <code>"+connEsc(st.skills_dir)+"</code>":""}`:"not connected"}</dd></dl>
${next?`<div class="conn-next">${connEsc(next)}</div>`:""}
<div class="conn-actions">
${!st.connected?`<button type="button" class="set-btn conn-wizard" data-tool="${st.tool}" title="Continue step by step from where you are">Set up</button>`:""}
<button type="button" class="set-btn conn-signin" data-tool="${st.tool}" title="Opens a terminal running: ${connEsc(st.login_command||"")}">${st.signin&&st.signin.state==="signed_in"?"Sign in again":"Sign in"}</button>
${st.connected?`<button type="button" class="set-btn conn-connect" data-tool="${st.tool}" title="Register LOYA NG's MCP server again and update the LOYA skills">Update connection</button><button type="button" class="set-btn conn-test" data-tool="${st.tool}">Test connection</button><button type="button" class="set-btn danger conn-disconnect" data-tool="${st.tool}">Disconnect</button>`:`<button type="button" class="set-btn conn-connect" data-tool="${st.tool}">Connect to LOYA NG</button>`}
<button type="button" class="set-btn conn-refresh" data-tool="${st.tool}">Refresh</button>
</div>`
}
return `<div class="ai-provider-box conn-box" data-tool="${st.tool}">
<div class="ai-provider-head"><span>${connEsc(st.label)}</span><span class="conn-pills"><span class="ai-status-pill ${signin.cls}">${connEsc(signin.text)}</span>${st.installed?`<span class="ai-status-pill ${link.cls}">${connEsc(link.text)}</span>`:""}</span></div>
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
connStatus(tool,st&&st.installed?"Found "+st.label+". Next: Sign in, then Connect to LOYA NG.":"Still not found.",!(st&&st.installed))
}))
on(".conn-docs",(tool)=>bridgeCall("notes.open_url",[connState.overview.tools[tool].docs]))
on(".conn-signin",connSignIn)
on(".conn-connect",(tool)=>{
connStatus(tool,"Connecting...",false)
return bridgeCall("extAgents.connection_connect",[tool]).then((r)=>connAfter(tool,r,"Connected."))
})
on(".conn-disconnect",(tool)=>{
const st=connState.overview.tools[tool]
return appConfirm("Disconnect "+st.label+" from LOYA NG? This removes the loya-note MCP server from its config, revokes its token and removes the LOYA skills you have not edited.",{okLabel:"Disconnect",danger:true}).then((yes)=>{
if(!yes)return null
return bridgeCall("extAgents.connection_disconnect",[tool]).then((r)=>connAfter(tool,r,"Disconnected."))
})
})
on(".conn-test",(tool)=>{
connStatus(tool,"Testing...",false)
return bridgeCall("extAgents.connection_test",[tool]).then((r)=>connStatus(tool,r.message,!r.ok,r.steps))
})
on(".conn-wizard",(tool)=>connWizard(tool))
root.querySelectorAll(".conn-copy").forEach((b)=>b.addEventListener("click",()=>connCopy(b.dataset.copy)))
root.querySelectorAll(".conn-link").forEach((b)=>b.addEventListener("click",()=>bridgeCall("notes.open_url",[b.dataset.url]).catch(()=>{})))
}
// ---------------------------------------------------------------- setup assistant (modal, one Approve per step)
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
let answer=null
const onKey=(e)=>{if(typeof confirmTrapKey==="function")confirmTrapKey(e,box,()=>answer&&answer("cancel"));else if(e.key==="Escape"){e.preventDefault();answer&&answer("cancel")}}
document.addEventListener("keydown",onKey,true)
okBtn.addEventListener("click",()=>answer&&answer("approve"))
cancelBtn.addEventListener("click",()=>answer&&answer("cancel"))
const close=()=>{document.removeEventListener("keydown",onKey,true);overlay.remove();connState.wizardOpen=false;if(before&&before.focus)try{before.focus()}catch(e){}}
const markSteps=(index,status)=>box.querySelectorAll(".conn-wiz-steps li").forEach((li)=>{
const i=Number(li.dataset.i)
li.classList.toggle("current",i===index)
li.classList.toggle("done",i<index||(i!==index&&connStepDone(CONN_STEPS[i].id,status)))
if(i===index)li.setAttribute("aria-current","step");else li.removeAttribute("aria-current")
})
const status=()=>bridgeCall("extAgents.connection_status",[tool]).then((st)=>{connState.overview.tools[tool]=st;return st})
// Builds the step's text (loading what it needs first), then waits for Approve / Cancel.
const ask=(v)=>{
markSteps(v.index,v.status)
okBtn.disabled=true
okBtn.textContent=v.done?"Continue":"Approve"
bodyEl.innerHTML=`<div class="conn-wiz-title">Step ${v.index+1} of ${CONN_STEPS.length}: ${connEsc(v.step.title)}</div><div class="set-status">Checking...</div>`
return connStepView(tool,v,w).then((html)=>{
bodyEl.innerHTML=`<div class="conn-wiz-title">Step ${v.index+1} of ${CONN_STEPS.length}: ${connEsc(v.step.title)}</div>${v.note?`<div class="set-status error">${connEsc(v.note)}</div>`:""}${html.body}`
bodyEl.querySelectorAll(".conn-copy").forEach((b)=>b.addEventListener("click",()=>connCopy(b.dataset.copy)))
bodyEl.querySelectorAll(".conn-link").forEach((b)=>b.addEventListener("click",()=>bridgeCall("notes.open_url",[b.dataset.url]).catch(()=>{})))
bodyEl.querySelectorAll('input[name="connWizMethod"]').forEach((r)=>r.addEventListener("change",()=>{w.method=r.value;w.plan=null}))
okBtn.textContent=html.ok||(v.done?"Continue":"Approve")
okBtn.disabled=!!html.blocked
;(okBtn.disabled?cancelBtn:okBtn).focus()
return new Promise((resolve)=>{answer=(a)=>{answer=null;okBtn.disabled=true;resolve(a)}})
}).catch((err)=>{
bodyEl.innerHTML=`<div class="conn-wiz-title">${connEsc(v.step.title)}</div><div class="set-status error">${connEsc(connErr(err))}</div>`
okBtn.disabled=true;cancelBtn.focus()
return new Promise((resolve)=>{answer=(a)=>{answer=null;resolve(a)}})
})
}
const working=(text)=>{bodyEl.insertAdjacentHTML("beforeend",`<div class="set-status">${connEsc(text)}</div>`)}
const act={
prereq:()=>{if(!w.method)return {retry:true,message:"Pick an install method that is ready to use."}},
install:()=>{
working("Opening the terminal...")
const p=w.plan
w.plan=null  // single use
const shell=connLoyaShell()
const run=shell&&p.use_shell===shell?bridgeCall("extAgents.connection_install_command",[tool,p.method,shell,p.token]).then((line)=>termOpenForRun().then(()=>termNewTab(shell,{name:label+" install",startup:line})).then(()=>"the LOYA NG terminal"))
:bridgeCall("extAgents.connection_install_os",[tool,p.method,p.token]).then((r)=>r.terminal)
return run.then((where)=>{w.installedVia=where})
},
verify:()=>bridgeCall("extAgents.connection_detect",[tool]).then((d)=>d.installed?null:{retry:true,message:"Not found yet. Wait for the installer to finish in "+(w.installedVia||"the terminal")+", then press Check again."}),
signin:()=>connOpenSignIn(tool).then((where)=>{w.signinVia=where}),
connect:()=>{working("Connecting...");return bridgeCall("extAgents.connection_connect",[tool]).then(()=>null)},
test:()=>{working("Testing...");return bridgeCall("extAgents.connection_test",[tool]).then((r)=>{w.testResult=r;return r})}
}
const finish=(res)=>{
const tail=()=>connMountSettings(connState.root)
if(res.cancelled){connState.reached[tool]=res.index;close();return tail().then(()=>connStatus(tool,"Setup stopped at step "+(res.index+1)+" ("+CONN_STEPS[res.index].title+"). Nothing else was run. Open the assistant again ("+(connState.overview.tools[tool].installed?"Set up":"Install for me")+") to continue from there.",false))}
delete connState.reached[tool]
if(!res.done){close();return tail()}
const r=res.result||{}
markSteps(CONN_STEPS.length,{})
bodyEl.innerHTML=`<div class="conn-wiz-title">${r.ok?"All set":"Set up, but the test found a problem"}</div><div class="set-status${r.ok?"":" error"}">${connEsc(r.message||"")}</div><ul class="conn-steps">${(r.steps||[]).map((s)=>`<li class="${s.ok?"ok":"bad"}">${connEsc(s.name)}${s.detail?" - "+connEsc(s.detail):""}</li>`).join("")}</ul>`
cancelBtn.classList.add("hidden")
okBtn.textContent="Done";okBtn.disabled=false;okBtn.focus()
return new Promise((resolve)=>{answer=()=>{answer=null;resolve()}}).then(()=>{close();return tail()})
}
return status().then((st)=>connRunWizard({start:connResumeStart(st,connState.reached[tool]),status,ask,act})).then(finish).catch((err)=>{close();connStatus(tool,connErr(err),true)})
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
return Promise.resolve({body:`<p>Approve opens a terminal running ${connEsc(st.label)}'s own sign-in:</p>${connCmdRow("Command",st.login_command||"")}<p class="set-info">You complete the vendor's browser sign-in yourself; LOYA NG never sees or stores it. Come back here when it says you are signed in.</p>`})
}
if(v.step.id==="connect"){
if(v.done)return already(st.label+" already has LOYA NG's MCP server.")
return bridgeCall("extAgents.connection_connect_preview",[tool]).then((p)=>({body:`<p>Approve registers LOYA NG's MCP server in your ${connEsc(st.label)} user config with its own command:</p>${connCmdRow("Command",p.command)}<p class="set-info">It also installs the LOYA skills (${connEsc(p.skills.join(", "))}) in <code>${connEsc(p.skills_dir)}</code>. ${connEsc(st.label)} then runs on your own account, and LOYA NG's AI Roles decide every tool call.</p>${st.signin&&st.signin.state!=="signed_in"?'<p class="set-info">You are not signed in yet; you can still connect and sign in later.</p>':""}`}))
}
return Promise.resolve({body:`<p>Approve runs a check of the whole path: the registration in ${connEsc(st.label)}, LOYA NG's MCP server, and a real tool list through the bridge.</p>`,ok:"Run the test"})
}
