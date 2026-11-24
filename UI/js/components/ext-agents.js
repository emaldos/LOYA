// External Agents: Claude Agent (Claude Agent SDK) and OpenAI Codex, run from the AI panel through LOYA's own MCP server.
// The pure helpers between the two markers are loaded by tests/js/ext_agents.js - keep them free of DOM and bridge calls.
// ---- ext pure start
const EXT_AGENT_KINDS={"ext:claude":{provider:"claude",label:"Claude Agent",vendor:"Anthropic"},"ext:codex":{provider:"codex",label:"OpenAI Codex",vendor:"OpenAI"}}
function extIsAgentKind(kind){return Object.prototype.hasOwnProperty.call(EXT_AGENT_KINDS,String(kind||""))}
function extProviderOf(kind){return extIsAgentKind(kind)?EXT_AGENT_KINDS[kind].provider:""}
function extProviderGroups(loyaList,agentList){
const groups=[]
const loya=(loyaList||[]).filter((p)=>p&&p.kind&&!extIsAgentKind(p.kind)).map((p)=>({kind:p.kind,label:p.label||p.kind}))
const agents=(agentList||[]).filter((p)=>p&&extIsAgentKind(p.kind)).map((p)=>({kind:p.kind,label:EXT_AGENT_KINDS[p.kind].label}))
if(loya.length)groups.push({label:"LOYA AI",options:loya})
if(agents.length)groups.push({label:"Agents",options:agents})
return groups
}
function extPickProvider(groups,current,preferred){
const all=[].concat(...(groups||[]).map((g)=>g.options.map((o)=>o.kind)))
if(current&&all.includes(current))return current
if(preferred&&all.includes(preferred))return preferred
return all[0]||""
}
function extSkillMatches(skills,query,taken){
const q=String(query||"").toLowerCase()
const takenSet=new Set((taken||[]).map((n)=>String(n).toLowerCase().replace(/^\//,"")))
const list=(skills||[]).filter((s)=>s&&s.name&&!takenSet.has(String(s.name).toLowerCase()))
const label=(s)=>EXT_AGENT_KINDS["ext:"+s.provider]?EXT_AGENT_KINDS["ext:"+s.provider].label:"Agent"
const what=(s)=>s.source==="LOYA skill"?"LOYA skill · for "+label(s):label(s)+" "+(s.kind==="prompt"?"prompt":s.kind==="command"?"command":"skill")+" · "+(s.source||"")
const row=(s)=>({kind:"agent-skill",label:"/"+s.name,name:s.name,provider:s.provider,detail:what(s)+(s.description?" - "+s.description:"")})
const starts=list.filter((s)=>String(s.name).toLowerCase().startsWith(q))
const rest=q?list.filter((s)=>!String(s.name).toLowerCase().startsWith(q)&&(String(s.name)+" "+(s.description||"")).toLowerCase().includes(q)):[]
return starts.concat(rest).map(row)
}
function extMergeSlashRows(){
const seen=new Set()
const out=[]
for(const rows of arguments){
for(const r of rows||[]){
const k=String(r&&r.label||"").toLowerCase()
if(!k||seen.has(k))continue
seen.add(k)
out.push(r)
}
}
return out
}
function extFindSkill(skills,name){
const n=String(name||"").toLowerCase()
return (skills||[]).find((s)=>s&&String(s.name).toLowerCase()===n)||null
}
function extBannerText(kind,permissions){
const k=EXT_AGENT_KINDS[kind]
if(!k)return ""
return "Data is sent to "+k.vendor+" ("+k.label+") · permissions: "+(permissions||"see Settings > AI > Roles")
}
function extStatusPill(st){
if(!st)return {text:"Unknown",cls:""}
if(!st.installed)return {text:"Not installed",cls:"offline"}
if(st.running)return {text:"Running",cls:"online"}
if(st.ready)return {text:"Ready",cls:"online"}
const map={no_key:"No key",consent_required:"Off",reconsent_required:"Needs consent",disabled:"Off"}
return {text:map[st.reason]||"Installed",cls:st.reason==="reconsent_required"?"offline":""}
}
// ---- ext pure end
const extState={skills:{},skillsAt:{},summary:{},settingsRoot:null,overview:null,installTimer:null}
function extEsc(s){return String(s===undefined||s===null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")}
function extErr(err){return err&&err.message?err.message:String(err||"Failed")}
// ---------------------------------------------------------------- AI panel
function extAgentSkills(kind,fresh){
const p=extProviderOf(kind)
if(!p)return Promise.resolve([])
if(!fresh&&extState.skills[p]&&Date.now()-(extState.skillsAt[p]||0)<15000)return Promise.resolve(extState.skills[p])
return bridgeCall("extAgents.skills",[p]).then((rows)=>{extState.skills[p]=rows||[];extState.skillsAt[p]=Date.now();return extState.skills[p]}).catch(()=>extState.skills[p]||[])
}
function extEnsureBanner(){
let el=document.getElementById("aiExtBanner")
if(el)return el
const head=document.querySelector("#aiPanel .ai-panel-head")
if(!head)return null
el=document.createElement("div")
el.id="aiExtBanner"
el.className="ai-ext-banner hidden"
el.setAttribute("role","status")
head.parentNode.insertBefore(el,head.nextSibling)
return el
}
function extAgentsOnProviderChange(kind){
const el=extEnsureBanner()
if(!el)return
if(!extIsAgentKind(kind)){el.classList.add("hidden");el.textContent="";return}
el.classList.remove("hidden")
el.innerHTML=`<i class="icon icon-info"></i><span>${extEsc(extBannerText(kind,extState.summary[kind]))}</span><button type="button" class="ai-ext-stop hidden" title="Stop the agent and end its process">Stop</button>`
el.querySelector(".ai-ext-stop").addEventListener("click",()=>{if(typeof aiStopSending==="function")aiStopSending()})
bridgeCall("extAgents.permission_summary",[kind]).then((s)=>{
extState.summary[kind]=s
const span=el.querySelector("span")
if(span&&typeof aiState!=="undefined"&&aiState.selectedKind===kind)span.textContent=extBannerText(kind,s)
}).catch(()=>{})
extAgentSkills(kind,true)
}
function extAgentsSetRunning(running){
const b=document.querySelector("#aiExtBanner .ai-ext-stop")
if(b)b.classList.toggle("hidden",!running)
}
function extAgentsHandleRunError(err){
const code=err&&err.code
const msg=extErr(err)
if(/consent/i.test(msg)||code==="reconsent_required"){
showStatusIsland(msg,"error")
}
}
// ---------------------------------------------------------------- consent dialog
function extConsentDialog(provider){
return bridgeCall("extAgents.consent_info",[provider]).then((info)=>new Promise((resolve)=>{
const overlay=document.createElement("div")
overlay.className="confirm-overlay ext-consent-overlay"
const box=document.createElement("div")
box.className="confirm-box confirm-box-wide glass-panel ext-consent"
box.setAttribute("role","dialog")
box.setAttribute("aria-modal","true")
box.innerHTML=`<div class="confirm-message">Enable ${extEsc(info.label)}?</div>
<div class="ext-consent-body"><p>Before you turn this on, please read what it means:</p><ul>${info.points.map((p)=>`<li>${extEsc(p)}</li>`).join("")}</ul>
<p class="ext-consent-perm"><b>Current permissions:</b> ${extEsc(info.permissions)}</p>
<details class="ext-consent-disclaimer"><summary>Read DISCLAIMER.md</summary><pre>${extEsc(info.disclaimer)}</pre></details>
<label class="set-check ext-consent-ack"><input type="checkbox" class="ext-consent-check"><span>I have read this and I agree. Record my consent.</span></label></div>
<div class="confirm-actions"><button class="confirm-cancel">Cancel</button><button class="confirm-ok" disabled>Enable</button></div>`
overlay.appendChild(box)
document.body.appendChild(overlay)
const ok=box.querySelector(".confirm-ok")
box.querySelector(".ext-consent-check").addEventListener("change",(e)=>{ok.disabled=!e.target.checked})
const close=(v)=>{overlay.remove();resolve(v)}
box.querySelector(".confirm-cancel").addEventListener("click",()=>close(false))
ok.addEventListener("click",()=>close(true))
}))
}
function extEnableFlow(provider){
return extConsentDialog(provider).then((yes)=>{
if(!yes)return null
return bridgeCall("extAgents.grant_consent",[provider,true]).then(()=>bridgeCall("extAgents.overview")).then((ov)=>{
const st=ov.providers[provider].status
if(provider==="claude"&&!st.installed)return bridgeCall("extAgents.install",[provider]).then(()=>{extWatchInstall();return bridgeCall("extAgents.set_enabled",[provider,true])})
return bridgeCall("extAgents.set_enabled",[provider,true])
})
})
}
// ---------------------------------------------------------------- Settings > AI > Agents > External Agents
function extAgentsMountSettings(root){
root=root||document.getElementById("setExtAgentsRoot")
if(!root)return Promise.resolve()
extState.settingsRoot=root
return bridgeCall("extAgents.overview").then((ov)=>{extState.overview=ov;extRenderSettings(root,ov)}).catch((err)=>{root.innerHTML=`<div class="set-status error">${extEsc(extErr(err))}</div>`})
}
function extSettingsStatus(provider,msg,isError){
const el=extState.settingsRoot&&extState.settingsRoot.querySelector(`.ext-status[data-provider="${provider}"]`)
if(!el)return
el.textContent=msg||""
el.classList.toggle("error",!!isError)
}
function extRemount(){return extAgentsMountSettings(extState.settingsRoot).then(()=>{if(typeof aiPopulateProviderSelect==="function"&&typeof aiState!=="undefined"&&aiState.open)aiPopulateProviderSelect()})}
function extProviderBox(p,ov){
const st=ov.providers[p].status
const cfg=ov.providers[p].config
const pill=extStatusPill(st)
const keyNote=st.key.set?`Key ${extEsc(st.key.masked)} - ${st.key.store==="keyring"?"stored in your OS keyring":st.key.store==="encrypted"?"encrypted with your PIN":"kept for this session only"}`:(st.key.stored_but_locked?"A key was saved but cannot be read now (OS keyring unavailable, or encrypted and the app is locked). Unlock, or enter it again.":"No key set.")
const efforts=ov.efforts[p].map((e)=>`<option value="${e}"${cfg.effort===e?" selected":""}>${e}</option>`).join("")
const lim=(k,label,step)=>cfg[k]===undefined?"":`<label class="ext-lim"><span>${label}</span><input type="number" class="set-input ext-field" data-provider="${p}" data-field="${k}" value="${extEsc(cfg[k])}"${step?` step="${step}"`:""}></label>`
let auth=""
let advanced=""
let install=""
if(p==="claude"){
auth=`<select class="set-select ext-field" data-provider="claude" data-field="auth" title="How the agent authenticates. claude.ai sign-in is not supported."><option value="api_key"${cfg.auth==="api_key"?" selected":""}>Anthropic API key</option><option value="bedrock"${cfg.auth==="bedrock"?" selected":""}>Amazon Bedrock (AWS credentials)</option><option value="vertex"${cfg.auth==="vertex"?" selected":""}>Google Vertex AI (Google credentials)</option></select>
<input type="text" class="set-input ext-field${cfg.auth==="bedrock"?"":" hidden"}" data-provider="claude" data-field="bedrock_region" placeholder="AWS region" value="${extEsc(cfg.bedrock_region)}">
<input type="text" class="set-input ext-field${cfg.auth==="vertex"?"":" hidden"}" data-provider="claude" data-field="vertex_project" placeholder="Vertex project id" value="${extEsc(cfg.vertex_project)}">
<input type="text" class="set-input ext-field${cfg.auth==="vertex"?"":" hidden"}" data-provider="claude" data-field="vertex_region" placeholder="Vertex region" value="${extEsc(cfg.vertex_region)}">`
advanced=`<details class="ext-advanced"><summary>Advanced: Claude's own built-in tools (off by default)</summary><p class="set-info">With these off, the agent can only use LOYA's tools (checked by AI Roles) and skills. File tools are limited to a workspace folder for each conversation under Data/external_agents. Read, Glob and Grep run without asking; Write, Edit, Bash, WebFetch and WebSearch ask you every time. Turning any on asks for consent again.</p><div class="ext-tools">${ov.claude_tools.map((t)=>`<label class="set-check"><input type="checkbox" class="ext-tool" value="${t}"${(cfg.builtin_tools||[]).includes(t)?" checked":""}><span>${t}</span></label>`).join("")}</div></details>`
install=st.installed?`<span class="ext-version">claude-agent-sdk ${extEsc(st.version)}</span>`:`<span class="ext-version">Needs the optional Python package ${extEsc(ov.sdk.package)}==${extEsc(ov.sdk.version)} - installed after you consent.</span>`
}else{
advanced=`<details class="ext-advanced"><summary>Advanced: Codex sandbox</summary><p class="set-info">Codex runs its own shell commands inside its sandbox, in a workspace folder for each conversation. Read-only is the default; widening it asks for consent again. Commands for your terminal still go through LOYA's approval queue.</p><select class="set-select ext-field" data-provider="codex" data-field="sandbox">${ov.codex_sandboxes.map((s)=>`<option value="${s}"${cfg.sandbox===s?" selected":""}>${s}</option>`).join("")}</select><input type="text" class="set-input ext-field" data-provider="codex" data-field="codex_path" placeholder="Path to the codex executable (optional)" value="${extEsc(cfg.codex_path)}"></details>`
install=st.installed?`<span class="ext-version">${extEsc(st.version||"codex found")}</span>`:`<span class="ext-version">Codex CLI not found. Install it yourself from OpenAI's official instructions (LOYA never installs it), or set its path under Advanced.</span>`
}
const model=p==="claude"?`<input type="text" class="set-input ext-field" data-provider="claude" data-field="model" list="extClaudeModels" placeholder="Model" value="${extEsc(cfg.model)}"><datalist id="extClaudeModels">${ov.claude_models.map((m)=>`<option value="${extEsc(m)}">`).join("")}</datalist>`:`<input type="text" class="set-input ext-field" data-provider="codex" data-field="model" placeholder="Model (empty = Codex default)" value="${extEsc(cfg.model)}">`
const consent=st.consent.granted?(st.consent.needs_reconsent?`<div class="ext-reconsent">Permissions were widened since you consented: ${extEsc(st.consent.widened.join("; "))}. <button type="button" class="set-btn ext-reconsent-btn" data-provider="${p}">Review and consent</button></div>`:`<span class="ext-consent-ts">Consent recorded ${extEsc(new Date(st.consent.ts).toLocaleString())}</span>`):""
return `<div class="ai-provider-box ext-box" data-provider="${p}">
<div class="ai-provider-head"><label class="set-check"><input type="checkbox" class="ext-enable" data-provider="${p}"${st.enabled?" checked":""}><span>${extEsc(st.label)}${p==="claude"?' <span class="ext-powered">Powered by Claude</span>':""}</span></label><span class="ai-status-pill ${pill.cls}">${extEsc(pill.text)}</span></div>
<div class="ext-line">${install} ${consent}</div>
<div class="ai-provider-fields">${auth}
<input type="password" class="set-input ext-key" data-provider="${p}" autocomplete="off" spellcheck="false" placeholder="${p==="claude"?"Anthropic API key":"OpenAI API key"}"><button type="button" class="set-btn ext-key-save" data-provider="${p}">Save key</button>${st.key.set?`<button type="button" class="set-btn danger ext-key-clear" data-provider="${p}">Remove key</button>`:""}
<button type="button" class="set-btn ext-test" data-provider="${p}">Test connection</button></div>
<div class="ext-line ext-keynote">${keyNote}</div>
<div class="ai-provider-fields">${model}<label class="ext-lim"><span>Effort</span><select class="set-select ext-field" data-provider="${p}" data-field="effort">${efforts}</select></label></div>
<div class="ext-limits">${lim("max_turns","Max turns")}${lim("max_budget_usd","Max $ per run","0.05")}${lim("timeout_min","Time limit (min)")}${lim("daily_requests","Requests per day")}${lim("daily_tokens","Tokens per day","1000")}</div>
<label class="set-check"><input type="checkbox" class="ext-field" data-provider="${p}" data-field="personal_skills"${cfg.personal_skills?" checked":""}><span>Offer my personal skills (${p==="claude"?"~/.claude/skills":"~/.codex/skills and prompts"}) in the AI panel's / menu</span></label>
${advanced}
<div class="ext-line ext-usage">Today: ${st.usage.requests} request(s), ~${Number(st.usage.tokens).toLocaleString()} tokens${st.usage.cost_usd?", ~$"+st.usage.cost_usd:""} · permissions: ${extEsc(st.permissions)}</div>
<div class="set-status ext-status" data-provider="${p}"></div>
</div>`
}
function extRenderSettings(root,ov){
const inst=ov.install&&ov.install.state==="running"?`<div class="set-status">${extEsc(ov.install.message)}</div>`:(ov.install&&ov.install.state==="failed"?`<div class="set-status error">${extEsc(ov.install.message)}</div>`:"")
root.innerHTML=`<p class="set-info">Run Claude (through Anthropic's Claude Agent SDK) or OpenAI Codex from the AI panel. They work on your notes, commands, targets and reports only through LOYA's own MCP tools, so Settings > AI > Roles decides what they may do and Ask stops for your approval. Both are off by default, use your own API key, and are billed by the provider. Nothing they suggest runs in your terminal without going through the approval queue.</p>
${inst}
${["claude","codex"].map((p)=>extProviderBox(p,ov)).join("")}
<div class="ai-provider-box ext-box">
<div class="ai-provider-head"><span>Safety</span></div>
<label class="set-check"><input type="checkbox" id="extRedactToggle"${ov.redact?" checked":""}><span>Redact secrets before anything is sent to an external agent (recommended)</span></label>
<p class="set-info">Masks note secrets, credential callouts and the terminal's secret patterns (passwords, tokens, keys, connection strings) in your prompts and in every tool result an agent receives.</p>
<div class="ext-line">Key storage: ${ov.key_storage.keyring?"OS keyring available":"no OS keyring"}${ov.key_storage.encrypted?" · PIN encryption available":""}. Without either, keys are kept only until LOYA closes.</div>
<div class="ext-mcp-token"><span>LOYA MCP server access token</span><code id="extMcpTokenMasked">-</code><button type="button" class="set-btn" id="extMcpTokenCopy">Copy</button></div>
<p class="set-info">Only for an MCP client you connect yourself: it must send <code>Authorization: Bearer &lt;token&gt;</code>. A new token is made every time the server starts; LOYA's agents get their own.</p>
</div>`
extWireSettings(root)
bridgeCall("extAgents.mcp_token",[false]).then((t)=>{const el=document.getElementById("extMcpTokenMasked");if(el)el.textContent=t.running?t.masked:"server not running"}).catch(()=>{})
}
function extSaveField(el){
const p=el.dataset.provider
const f=el.dataset.field
const v=el.type==="checkbox"?el.checked:el.value
return bridgeCall("extAgents.set_config",[p,{[f]:v}]).then((cfg)=>{
extSettingsStatus(p,"Saved.",false)
if(cfg&&cfg.consent&&cfg.consent.needs_reconsent)return extRemount()
if(f==="auth")return extRemount()
}).catch((err)=>extSettingsStatus(p,extErr(err),true))
}
function extWireSettings(root){
root.querySelectorAll(".ext-enable").forEach((el)=>el.addEventListener("change",()=>{
const p=el.dataset.provider
if(!el.checked){bridgeCall("extAgents.set_enabled",[p,false]).then(extRemount).catch((err)=>extSettingsStatus(p,extErr(err),true));return}
el.checked=false
extEnableFlow(p).then((r)=>{if(r)extRemount().then(()=>extSettingsStatus(p,"Enabled.",false))}).catch((err)=>{extSettingsStatus(p,extErr(err),true);extRemount()})
}))
root.querySelectorAll(".ext-reconsent-btn").forEach((b)=>b.addEventListener("click",()=>{
const p=b.dataset.provider
extConsentDialog(p).then((yes)=>yes?bridgeCall("extAgents.grant_consent",[p,true]).then(extRemount):null).catch((err)=>extSettingsStatus(p,extErr(err),true))
}))
root.querySelectorAll(".ext-field").forEach((el)=>el.addEventListener("change",()=>extSaveField(el)))
root.querySelectorAll(".ext-advanced .ext-tools").forEach((wrap)=>wrap.addEventListener("change",()=>{
const tools=[...wrap.querySelectorAll(".ext-tool:checked")].map((x)=>x.value)
bridgeCall("extAgents.set_config",["claude",{builtin_tools:tools}]).then(extRemount).catch((err)=>extSettingsStatus("claude",extErr(err),true))
}))
root.querySelectorAll(".ext-key-save").forEach((b)=>b.addEventListener("click",()=>{
const p=b.dataset.provider
const input=root.querySelector(`.ext-key[data-provider="${p}"]`)
const v=input.value.trim()
if(!v){extSettingsStatus(p,"Paste a key first.",true);return}
bridgeCall("extAgents.set_api_key",[p,v]).then(()=>{input.value="";return extRemount()}).then(()=>extSettingsStatus(p,"Key saved.",false)).catch((err)=>{input.value="";extSettingsStatus(p,extErr(err),true)})
}))
root.querySelectorAll(".ext-key-clear").forEach((b)=>b.addEventListener("click",()=>{
const p=b.dataset.provider
bridgeCall("extAgents.clear_api_key",[p]).then(extRemount).catch((err)=>extSettingsStatus(p,extErr(err),true))
}))
root.querySelectorAll(".ext-test").forEach((b)=>b.addEventListener("click",()=>{
const p=b.dataset.provider
extSettingsStatus(p,"Testing…",false)
bridgeCall("extAgents.test_connection",[p]).then((r)=>extSettingsStatus(p,r.message,r.status==="offline")).catch((err)=>extSettingsStatus(p,extErr(err),true))
}))
const red=document.getElementById("extRedactToggle")
if(red)red.addEventListener("change",()=>{
const go=()=>bridgeCall("extAgents.set_redaction",[red.checked]).catch(()=>{})
if(red.checked)return go()
appConfirm("Turn off redaction? Secrets in your notes and terminal output would be sent to the provider as they are.",{okLabel:"Turn off",danger:true}).then((yes)=>{if(yes)go();else red.checked=true})
})
const copy=document.getElementById("extMcpTokenCopy")
if(copy)copy.addEventListener("click",()=>bridgeCall("extAgents.mcp_token",[true]).then((t)=>{
if(!t.running||!t.token){showStatusIsland("The MCP server is not running","error");return}
const done=()=>showStatusIsland("Token copied","success")
if(navigator.clipboard&&navigator.clipboard.writeText)navigator.clipboard.writeText(t.token).then(done).catch(()=>showStatusIsland("Could not copy","error"))
}).catch((err)=>showStatusIsland(extErr(err),"error")))
}
function extWatchInstall(){
if(extState.installTimer)return
extState.installTimer=setInterval(()=>{
bridgeCall("extAgents.install_status").then((s)=>{
if(s.state==="running")return
clearInterval(extState.installTimer);extState.installTimer=null
showStatusIsland(s.message||"Install finished",s.state==="done"?"success":"error")
extRemount()
}).catch(()=>{clearInterval(extState.installTimer);extState.installTimer=null})
},2000)
}
