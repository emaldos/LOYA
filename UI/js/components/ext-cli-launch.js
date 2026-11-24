// AI panel > Agents > "Claude Code (your CLI)" / "Codex CLI (your CLI)": the operator's OWN official CLI, run interactively in a
// LOYA NG terminal tab (like VS Code's integrated terminal). Picking one shows its connection state (from the Connections
// background jobs) and "Open in terminal"; the chat box is hidden for it.
// Policy (Anthropic Agent SDK docs): LOYA NG may not offer claude.ai login or rate limits in its product. So nothing here, or in
// ai.js, sends chat-panel text to the CLI, and the CLI is never run non-interactively (-p / --print / exec) for the operator.
// The starter buttons only put text into the terminal's input box for the operator to send with Enter themselves.
// Backend: Cores/Services/ext_cli_launch.py. The pure helpers between the markers are loaded by tests/js/ext_cli_launch.js.
// ---- cli pure start
const CLI_ENTRY_KINDS={
"cli:claude_code":{tool:"claude_code",label:"Claude Code (your CLI)",name:"Claude Code"},
"cli:codex_cli":{tool:"codex_cli",label:"Codex CLI (your CLI)",name:"Codex CLI"}}
const CLI_STARTERS=[
{label:"Use the loya-basics skill",text:"Use the loya-basics skill"},
{label:"Use the loya-notes skill",text:"Use the loya-notes skill"},
{label:"Use the loya-recon skill",text:"Use the loya-recon skill"}]
function cliIsEntryKind(kind){return Object.prototype.hasOwnProperty.call(CLI_ENTRY_KINDS,String(kind||""))}
function cliToolOf(kind){return cliIsEntryKind(kind)?CLI_ENTRY_KINDS[kind].tool:""}
function cliKindOf(tool){return Object.keys(CLI_ENTRY_KINDS).find((k)=>CLI_ENTRY_KINDS[k].tool===tool)||""}
// Same table as cli_state() in ext_cli_launch.py. A sign-in state LOYA NG could not read is its own state ("signin_unknown"):
// it still offers Open in terminal, since the CLI asks for its own sign-in when it starts.
function cliEntryState(st){
if(!st||!st.installed)return "not_installed"
if(st.signin&&st.signin.state==="signed_out")return "not_signed_in"
if(!st.connected)return "not_connected"
if(!st.signin||st.signin.state!=="signed_in")return "signin_unknown"
return "ready"
}
const CLI_STATE_VIEW={
checking:{text:"Checking",cls:"",dot:""},
not_installed:{text:"Not installed",cls:"not_installed",dot:"offline"},
not_signed_in:{text:"Not signed in",cls:"offline",dot:"offline"},
not_connected:{text:"Not connected",cls:"",dot:"offline"},
signin_unknown:{text:"Sign-in unknown",cls:"",dot:""},
ready:{text:"Ready",cls:"online",dot:"online"},
error:{text:"Could not check",cls:"offline",dot:"offline"}}
function cliStateView(state){return CLI_STATE_VIEW[state]||CLI_STATE_VIEW.checking}
function cliCanOpen(state){return state==="ready"||state==="signin_unknown"}
function cliOptionLabel(kind,state){
const k=CLI_ENTRY_KINDS[kind]
if(!k)return ""
return state&&state!=="checking"?k.label+" - "+cliStateView(state).text.toLowerCase():k.label
}
function cliHelperText(kind){
const k=CLI_ENTRY_KINDS[kind]
if(!k)return ""
return "Runs the official "+k.name+" in a LOYA NG terminal on your own account. It uses LOYA NG through its tools, and AI Roles decide each call."
}
function cliNextStep(state){
if(state==="not_installed")return "Install it in Settings > AI > Agents > Connections."
if(state==="not_signed_in")return "Sign in to it in Settings > AI > Agents > Connections."
if(state==="not_connected")return "Press Connect to LOYA NG in Settings > AI > Agents > Connections."
if(state==="signin_unknown")return "LOYA NG could not read its sign-in state. If it asks, sign in there."
if(state==="error")return "Open Settings > AI > Agents > Connections to see what is wrong."
return ""
}
// The provider list: the CLI entries go last in the "Agents" group (created when no in-app agent is enabled).
function cliAddToGroups(groups,states){
const out=(groups||[]).map((g)=>({label:g.label,options:g.options.slice()}))
let agents=out.find((g)=>g.label==="Agents")
if(!agents){agents={label:"Agents",options:[]};out.push(agents)}
Object.keys(CLI_ENTRY_KINDS).forEach((kind)=>agents.options.push({kind,label:cliOptionLabel(kind,(states||{})[CLI_ENTRY_KINDS[kind].tool])}))
return out
}
// Where to run it: a native LOYA terminal shell (never WSL: the Windows CLI is not on its PATH), else the OS terminal.
function cliLaunchPlan(terminalOn,shellId){
return terminalOn&&shellId&&String(shellId).indexOf("wsl:")!==0?{via:"loya",shell:shellId}:{via:"os",shell:""}
}
// ---- cli pure end
const cliState={states:{},checkedAt:0,job:null,tabs:{},via:{}}
function cliEsc(s){return String(s===undefined||s===null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")}
function cliErr(err){return err&&err.message?err.message:String(err||"Failed")}
function cliSelected(){return typeof aiState!=="undefined"&&cliIsEntryKind(aiState.selectedKind)?aiState.selectedKind:""}
// One Connections "overview" job at a time, in the background (connJobRun polls; the bridge call returns at once).
function cliRefreshStates(force){
if(cliState.job)return cliState.job
if(!force&&cliState.checkedAt&&Date.now()-cliState.checkedAt<30000)return Promise.resolve(cliState.states)
if(typeof connJobRun!=="function")return Promise.resolve(cliState.states)
Object.keys(CLI_ENTRY_KINDS).forEach((k)=>{const t=CLI_ENTRY_KINDS[k].tool;if(!cliState.states[t])cliState.states[t]="checking"})
cliUpdateView()
cliState.job=connJobRun(bridgeCall,"overview",null).then((ov)=>{
cliState.overview=ov
Object.keys(CLI_ENTRY_KINDS).forEach((k)=>{const t=CLI_ENTRY_KINDS[k].tool;cliState.states[t]=cliEntryState(ov&&ov.tools&&ov.tools[t])})
cliState.checkedAt=Date.now()
return cliState.states
}).catch((err)=>{
cliState.error=cliErr(err)
Object.keys(CLI_ENTRY_KINDS).forEach((k)=>{cliState.states[CLI_ENTRY_KINDS[k].tool]="error"})
return cliState.states
}).finally(()=>{cliState.job=null;cliUpdateView()})
return cliState.job
}
function cliUpdateOptionLabels(){
const select=document.getElementById("aiProviderSelect")
if(!select)return
Array.from(select.options).forEach((o)=>{if(cliIsEntryKind(o.value))o.textContent=cliOptionLabel(o.value,cliState.states[cliToolOf(o.value)])})
const v=select.value
select.value=v  // ui-select: refresh the trigger's label
}
function cliUpdateView(){
cliUpdateOptionLabels()
const kind=cliSelected()
if(!kind)return
cliSetDot()
const wrap=document.getElementById("aiChatMessages")
if(wrap&&wrap.querySelector(".ai-cli-entry"))cliRenderEntry(wrap)
}
function cliSetDot(){
const kind=cliSelected()
if(!kind||typeof aiSetStatusDot!=="function")return
aiSetStatusDot(cliStateView(cliState.states[cliToolOf(kind)]).dot)
}
// ai.js: the provider list gets the CLI entries; the status poll never runs a CLI (the cached state is shown).
function cliProviderGroups(groups){
cliRefreshStates(false)
return cliAddToGroups(groups,cliState.states)
}
function cliPollStatus(){cliSetDot()}
// ai.js calls this from aiRenderChat: true when a CLI entry is shown instead of the chat.
function cliRenderIfSelected(wrap){
const panel=document.getElementById("aiPanelBody")
const kind=cliSelected()
if(panel)panel.classList.toggle("ai-cli-mode",!!kind)
if(!kind)return false
cliRenderEntry(wrap)
cliRefreshStates(false)
return true
}
function cliTabAlive(tool){
const id=cliState.tabs[tool]
return !!(id&&typeof termFindTab==="function"&&termFindTab(id)&&!termFindTab(id).dead)
}
function cliRenderEntry(wrap){
const kind=cliSelected()
if(!kind||!wrap)return
const tool=cliToolOf(kind)
const k=CLI_ENTRY_KINDS[kind]
const state=cliState.states[tool]||"checking"
const view=cliStateView(state)
const st=cliState.overview&&cliState.overview.tools&&cliState.overview.tools[tool]
const detail=state==="error"?cliState.error||"":st?[st.version,st.signin&&st.signin.state==="signed_in"?st.signin.detail:""].filter(Boolean).join(" | "):""
const ready=cliCanOpen(state)
const tabOpen=cliTabAlive(tool)
const starters=ready?`<div class="ai-cli-starters"><div class="ai-cli-sub">Starter prompts (typed into its terminal, you press Enter)</div><div class="ai-cli-starter-row">${CLI_STARTERS.map((s,i)=>`<button type="button" class="set-btn ai-cli-starter" data-i="${i}" ${tabOpen||cliState.via[tool]==="os"?"":"disabled"} title="${cliEsc(tabOpen?"Type it into the "+k.name+" terminal tab":cliState.via[tool]==="os"?"Copy it, then paste it into "+k.name:"Open "+k.name+" in a terminal first")}">${cliEsc(s.label)}</button>`).join("")}</div></div>`:""
wrap.innerHTML=`<div class="ai-cli-entry" data-tool="${tool}">
<div class="ai-cli-head"><i class="icon icon-command-line"></i><span class="ai-cli-title">${cliEsc(k.label)}</span><span class="ai-status-pill ${view.cls}">${cliEsc(view.text)}</span></div>
<p class="ai-cli-help">${cliEsc(cliHelperText(kind))}</p>
${detail?`<div class="ai-cli-detail">${cliEsc(detail)}</div>`:""}
${state==="ready"?"":state==="signin_unknown"?`<div class="ai-cli-next">${cliEsc(cliNextStep(state))}</div>`:state==="checking"?`<div class="ai-cli-detail">Checking ${cliEsc(k.name)}</div>`:`<div class="ai-cli-next">${cliEsc(cliNextStep(state))}</div>`}
<div class="ai-cli-actions">
${ready?`<button type="button" class="set-btn primary ai-cli-open">${tabOpen?"Show its terminal":"Open in terminal"}</button>${tabOpen?'<button type="button" class="set-btn ai-cli-open-new">New tab</button>':""}`:`<button type="button" class="set-btn primary ai-cli-settings">Open Connections</button>`}
<button type="button" class="set-btn ai-cli-refresh" ${state==="checking"?"disabled":""}>Check again</button>
</div>
${starters}
<div class="ai-cli-status" role="status"></div>
</div>`
const box=wrap.querySelector(".ai-cli-entry")
const on=(sel,fn)=>{const b=box.querySelector(sel);if(b)b.addEventListener("click",fn)}
on(".ai-cli-open",()=>cliOpen(tool,false))
on(".ai-cli-open-new",()=>cliOpen(tool,true))
on(".ai-cli-settings",cliGoToConnections)
on(".ai-cli-refresh",()=>cliRefreshStates(true))
box.querySelectorAll(".ai-cli-starter").forEach((b)=>b.addEventListener("click",()=>cliStarter(tool,CLI_STARTERS[+b.dataset.i])))
}
function cliStatus(msg,isError){
const el=document.querySelector(".ai-cli-entry .ai-cli-status")
if(!el)return
el.textContent=msg||""
el.classList.toggle("error",!!isError)
}
function cliGoToConnections(){
const go=typeof goToPage==="function"?goToPage("settings"):Promise.resolve()
return Promise.resolve(go).then(()=>{if(typeof setSwitchTab==="function")setSwitchTab("ai","agents")}).then(()=>{
const el=document.getElementById("setExtConnectionsRoot")
if(el&&el.scrollIntoView)el.scrollIntoView({block:"start"})
})
}
function cliShellFor(){
const on=typeof termState!=="undefined"&&termState.enabled&&typeof termNewTab==="function"&&typeof termOpenForRun==="function"
const platform=(typeof termState!=="undefined"&&termState.platform)||(cliState.overview&&cliState.overview.platform)||"linux"
const shell=on&&typeof connPickShell==="function"?connPickShell(termState.shells,platform==="windows"?"windows":"linux"):""
return cliLaunchPlan(on,shell)
}
function cliOpen(tool,fresh){
const kind=cliKindOf(tool)
const k=CLI_ENTRY_KINDS[kind]
if(!fresh&&cliTabAlive(tool)){
return termOpenForRun().then(()=>{termActivateTab(cliState.tabs[tool]);cliStatus("Showing the "+k.name+" terminal tab.",false)})
}
const plan=cliShellFor()
const viaOs=()=>bridgeCall("extAgents.cli_launch_os",[tool]).then((r)=>{
cliState.via[tool]="os"
cliStatus("Opened "+k.name+" in "+(r&&r.terminal||"the system terminal")+".",false)
cliRenderAfterOpen()
})
let p
if(plan.via!=="loya")p=viaOs()
else p=bridgeCall("extAgents.cli_launch_command",[tool,plan.shell]).then((r)=>{
if(!r||!r.line)return viaOs()
return termOpenForRun().then(()=>termNewTab(plan.shell,{name:r.name||k.label,cwd:r.cwd,startup:r.line})).then((id)=>{
cliState.tabs[tool]=id
cliState.via[tool]="loya"
// The CLI is interactive: lines typed in this tab go to it as typed (terminal.js skips its job markers for rawInput tabs).
const tab=typeof termFindTab==="function"?termFindTab(id):null
if(tab)tab.rawInput=true
cliStatus("Opened "+k.name+" in a LOYA NG terminal tab. Talk to it there.",false)
cliRenderAfterOpen()
})
})
return p.catch((err)=>{cliStatus(cliErr(err),true);if(typeof showStatusIsland==="function")showStatusIsland(cliErr(err),"error")})
}
function cliRenderAfterOpen(){
const msg=document.querySelector(".ai-cli-entry .ai-cli-status")
const keep=msg?{text:msg.textContent,error:msg.classList.contains("error")}:null
const wrap=document.getElementById("aiChatMessages")
if(wrap&&cliSelected())cliRenderEntry(wrap)
if(keep)cliStatus(keep.text,keep.error)
}
// Puts a starter prompt into the CLI tab's input box. It is never sent: the operator presses Enter.
function cliStarter(tool,starter){
if(!starter)return
const k=CLI_ENTRY_KINDS[cliKindOf(tool)]
if(cliTabAlive(tool)){
return termOpenForRun().then(()=>{
termActivateTab(cliState.tabs[tool])
const input=document.getElementById("terminalInput")
if(!input)return
input.value=starter.text
if(typeof termUpdateLiveEcho==="function")termUpdateLiveEcho()
input.focus()
cliStatus("Typed into the "+k.name+" tab. Press Enter there to send it.",false)
})
}
if(navigator.clipboard&&navigator.clipboard.writeText){
return navigator.clipboard.writeText(starter.text).then(()=>cliStatus("Copied. Paste it into "+k.name+" and press Enter.",false)).catch(()=>cliStatus("Could not copy. Type it into "+k.name+": "+starter.text,true))
}
cliStatus("Type it into "+k.name+": "+starter.text,false)
}
// Policy guard for ai.js: a CLI entry never receives chat-panel text.
function cliRefuseChat(){
const kind=cliSelected()
if(!kind)return false
const msg=CLI_ENTRY_KINDS[kind].name+" runs in its own terminal tab on your account. Use Open in terminal, or pick another provider to chat here."
if(typeof showStatusIsland==="function")showStatusIsland(msg,"error")
return true
}
