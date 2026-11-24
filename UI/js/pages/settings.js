let setState={tab:"security",backups:[],backupSelected:new Set(),tags:[],tagSelected:new Set(),tagSearch:"",rb:[],rbSelected:new Set(),rbType:"",rbSearch:""}
// Escapes quotes too: the result is also placed inside HTML attributes (title, data-*, value). The old textContent/innerHTML
// trick left " unescaped, so a saved name like  " onmouseover="...  injected a handler with full bridge access.
function setEscapeHtml(s){
return String(s===undefined||s===null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")
}
function setSwitchTab(tab,sub){
if(tab==="airoles")tab="ai"  // the old "AI Roles" tab is now AI > Roles
setState.tab=tab
document.querySelectorAll(".set-tab").forEach((t)=>t.classList.toggle("active",t.dataset.tab===tab))
document.querySelectorAll(".set-panel").forEach((p)=>p.classList.toggle("active",p.dataset.tabPanel===tab))
if(tab==="ai")setSwitchAiTab(sub||setState.aiTab||"agents")
setRefreshTabData(tab)
}
function setRefreshTabData(tab){
if(!document.getElementById("setTagTableBody"))return
if(tab==="tags")setRefreshTags().catch(()=>{})
else if(tab==="recycle"){setRefreshRb().catch(()=>{});setRefreshRbRetention()}
else if(tab==="backup")setRefreshBackups().catch(()=>{})
else if(tab==="update")setLoadUpdate()
else if(tab==="cve"&&typeof cveMountSettings==="function")cveMountSettings(document.getElementById("setCveRoot"))
}
// Settings > AI: Agents (default: Connections to your own CLI, Claude Agent / OpenAI Codex, AI Assistant) and Roles (AI Roles & Permissions).
function setSwitchAiTab(sub){
sub=sub==="roles"?"roles":"agents"
setState.aiTab=sub
document.querySelectorAll(".set-subtab[data-ai-tab]").forEach((b)=>{const on=b.dataset.aiTab===sub;b.classList.toggle("active",on);b.setAttribute("aria-selected",on?"true":"false")})
document.querySelectorAll(".set-subpanel[data-ai-panel]").forEach((p)=>p.classList.toggle("active",p.dataset.aiPanel===sub))
// The Connections card runs the CLIs (--version, sign-in status): only when the Agents tab is looked at.
if(sub==="agents"&&typeof connMountSettings==="function")connMountSettings(document.getElementById("setExtConnectionsRoot"))
}
function setStatus(id,msg,isError){
const el=document.getElementById(id)
el.textContent=msg||""
el.classList.toggle("error",!!isError)
}
function setClosePopover(){
const p=document.getElementById("setPopover")
if(p)p.remove()
}
function setLoadAppearance(){
return Promise.all([bridgeCall("theme.get"),bridgeCall("theme.accent"),bridgeCall("focusMode.get"),bridgeCall("theme.style").catch(()=>({style:"glass"}))]).then(([themeState,accent,focusMode,styleState])=>{
document.getElementById("setThemeModeSelect").value=themeState.mode
document.getElementById("setStyleSelect").value=styleState&&styleState.style==="classic"?"classic":"glass"
setRenderAccentGrid(accent)
document.getElementById("setFocusModeToggle").checked=!!focusMode.enabled
return bridgeCall("notes.editor_prefs").then((p)=>{
document.getElementById("setNoteSuggestTitle").checked=p.suggest_title===true
document.getElementById("setNoteAutoPairs").checked=p.auto_pairs_off!==true
document.getElementById("setNoteSuggestTags").checked=p.suggest_tags===true
})
}).catch(()=>{})
}
function setDoToggleNoteSuggest(key,el){
bridgeCall("notes.set_editor_pref",[key,el.checked===true]).then((p)=>{if(typeof notesApplyPrefs==="function")notesApplyPrefs(p)}).catch((err)=>{el.checked=!el.checked;showToast(err&&err.message?err.message:"Failed","error")})
}
function setDoToggleFocusMode(){
const enabled=document.getElementById("setFocusModeToggle").checked
bridgeCall("focusMode.set",[enabled]).then((res)=>{focusModeSetEnabled(res.enabled)}).catch((err)=>showToast(err&&err.message?err.message:"Failed","error"))
}
function setRenderAccentGrid(current){
const grid=document.getElementById("setAccentGrid")
grid.innerHTML=""
;(current.presets||[]).forEach((p)=>{
const isActive=p.a.toLowerCase()===current.a.toLowerCase()&&p.b.toLowerCase()===current.b.toLowerCase()
const cell=document.createElement("button")
cell.type="button"
cell.className="set-accent-cell"+(isActive?" active":"")
cell.innerHTML=`<span class="set-accent-swatch" style="background:linear-gradient(135deg,${p.a},${p.b})"></span><span class="set-accent-label">${setEscapeHtml(p.name)}</span>`
cell.addEventListener("click",()=>{
bridgeCall("theme.set_accent",[p.a,p.b]).then((acc)=>{
applyAccentState(acc)
setRenderAccentGrid(acc)
}).catch((err)=>showToast(err&&err.message?err.message:"Failed to set accent color","error"))
})
grid.appendChild(cell)
})
}
function setDoChangeStyle(){
const style=document.getElementById("setStyleSelect").value
bridgeCall("theme.set_style",[style]).then(applyStyleState).catch((err)=>showToast(err&&err.message?err.message:"Failed to set style","error"))
}
function setDoChangeThemeMode(){
const mode=document.getElementById("setThemeModeSelect").value
bridgeCall("theme.set",[mode]).then(()=>themeApplyAll()).catch((err)=>showToast(err&&err.message?err.message:"Failed to set theme","error"))
}
function setOpenPopover(widthPx){
setClosePopover()
const pop=document.createElement("div")
pop.id="setPopover"
pop.className="set-popover glass-panel"
pop.style.top="70px"
pop.style.left=Math.round((window.innerWidth-(widthPx||420))/2)+"px"
document.body.appendChild(pop)
return pop
}
function setPromptPin(title,message,needConfirm,skipLabel){
return new Promise((resolve)=>{
const pop=setOpenPopover(340)
pop.innerHTML=`<div class="set-popover-title">${setEscapeHtml(title)}</div>${message?`<p class="set-info">${setEscapeHtml(message)}</p>`:""}<div class="set-popover-field"><label>PIN</label><input type="password" id="setPinInput1"></div>${needConfirm?'<div class="set-popover-field"><label>Confirm PIN</label><input type="password" id="setPinInput2"></div>':""}<div class="set-popover-error hidden" id="setPinErr"></div><div class="set-popover-actions"><button type="button" id="setPinCancel">Cancel</button>${skipLabel?`<button type="button" id="setPinSkip">${setEscapeHtml(skipLabel)}</button>`:""}<button type="button" class="set-popover-confirm" id="setPinOk">OK</button></div>`
const input1=pop.querySelector("#setPinInput1")
input1.focus()
function finish(val){setClosePopover();resolve(val)}
pop.querySelector("#setPinCancel").addEventListener("click",()=>finish(null))
if(skipLabel)pop.querySelector("#setPinSkip").addEventListener("click",()=>finish(""))  // "" = skipped, null = cancelled
// Enter submits and Escape cancels, as in the lock screen; before, typing a PIN and pressing Enter did nothing.
pop.addEventListener("keydown",(e)=>{if(e.key==="Enter"){e.preventDefault();pop.querySelector("#setPinOk").click()}else if(e.key==="Escape"){e.preventDefault();finish(null)}})
pop.querySelector("#setPinOk").addEventListener("click",()=>{
const p1=input1.value
const p2=needConfirm?pop.querySelector("#setPinInput2").value:p1
const errEl=pop.querySelector("#setPinErr")
if(!p1){errEl.textContent="PIN is required.";errEl.classList.remove("hidden");return}
if(needConfirm&&p1!==p2){errEl.textContent="PINs do not match.";errEl.classList.remove("hidden");return}
finish(p1)
})
})
}
function setLoadSecurity(){
bridgeCall("security.status").then((cfg)=>{
document.getElementById("setLockToggle").checked=cfg.app_lock_enabled
document.getElementById("setEncToggle").checked=cfg.enc_enabled
document.getElementById("setPinStatus").textContent="PIN: "+(cfg.pin_set?"Set":"Not set")
document.getElementById("setEncStatus").textContent=cfg.enc_enabled?(cfg.enc_file_exists?"Database encrypted (SQLCipher, AES-256)":"Encryption on: the database is created encrypted"):"Encryption: Off"
document.getElementById("setAutoLockSelect").value=String(cfg.auto_lock_minutes||0)
setApplyAuditExpiry(cfg.audit_expiry)
}).catch((err)=>console.error("security status failed",err))
setLoadAuditLog()
}
function setDoChangeAutoLock(){
const minutes=parseInt(document.getElementById("setAutoLockSelect").value,10)||0
bridgeCall("security.set_auto_lock_minutes",[minutes]).then(()=>{
setStatus("setSecStatus",minutes?`Auto-lock set to ${minutes} minute(s) of inactivity.`:"Auto-lock disabled.",false)
if(typeof idleRefreshSetting==="function")idleRefreshSetting()
}).catch((err)=>setStatus("setSecStatus",err&&err.message?err.message:"Failed",true))
}
// Audit log expiry: whole numbers 1-999 only (Python validates again).
function setParseAuditExpiryAmount(raw){
const s=String(raw==null?"":raw).trim()
if(!/^[0-9]{1,3}$/.test(s))return null
const n=parseInt(s,10)
return n>=1&&n<=999?n:null
}
function setApplyAuditExpiry(cfg){
if(!cfg)return
const toggle=document.getElementById("setAuditExpiryToggle")
toggle.checked=!!cfg.enabled
document.getElementById("setAuditExpiryAmount").value=String(cfg.amount||90)
document.getElementById("setAuditExpiryUnit").value=cfg.unit||"days"
setSyncAuditExpiryInputs()
}
function setSyncAuditExpiryInputs(){
const on=document.getElementById("setAuditExpiryToggle").checked
document.getElementById("setAuditExpiryAmount").disabled=!on
document.getElementById("setAuditExpiryUnit").disabled=!on
}
function setDoSaveAuditExpiry(){
const enabled=document.getElementById("setAuditExpiryToggle").checked
const raw=document.getElementById("setAuditExpiryAmount").value
const amount=setParseAuditExpiryAmount(raw)
const unit=document.getElementById("setAuditExpiryUnit").value
if(enabled&&amount===null){setStatus("setAuditExpiryStatus","Enter a whole number from 1 to 999.",true);return}
bridgeCall("security.set_audit_expiry",[enabled,amount===null?raw:amount,unit]).then((res)=>{
setApplyAuditExpiry(res)
const pruned=res&&res.pruned?` Removed ${res.pruned} expired entr${res.pruned===1?"y":"ies"}.`:""
setStatus("setAuditExpiryStatus",(res.enabled?`Entries older than ${res.amount} ${res.amount===1?res.unit.replace(/s$/,""):res.unit} are removed.`:"Old entries are kept.")+pruned,false)
setLoadAuditLog()
}).catch((err)=>setStatus("setAuditExpiryStatus",err&&err.message?err.message:"Failed",true))
}
function setFmtAuditWhen(iso){
try{return new Date(iso).toLocaleString()}catch(e){return iso||""}
}
function setLoadAuditLog(){
bridgeCall("security.audit_log",[200]).then((rows)=>{
const body=document.getElementById("setAuditTableBody")
body.innerHTML=""
if(!rows.length){
setStatus("setAuditStatus","No audit events recorded yet.",false)
return
}
setStatus("setAuditStatus","",false)
rows.forEach((r)=>{
const tr=document.createElement("tr")
tr.innerHTML=`<td>${setEscapeHtml(setFmtAuditWhen(r.ts))}</td><td>${setEscapeHtml(r.event)}</td><td>${setEscapeHtml(r.detail||"-")}</td><td>${r.success?"OK":"Failed"}</td>`
if(!r.success)tr.style.color="var(--danger)"
body.appendChild(tr)
})
}).catch((err)=>console.error("audit log load failed",err))
}
function setDoSetPin(){
bridgeCall("security.status").then((cfg)=>{
const flow=cfg.pin_set?setPromptPin("Verify current PIN","Enter your current PIN.",false).then((cur)=>{
if(cur===null)return null
return setPromptPin("Set New PIN","Enter a new PIN (min 4 characters; 6 or more with encryption at rest).",true).then((np)=>np===null?null:{cur,np})
}):setPromptPin("Set PIN","Enter a new PIN (min 4 characters).",true).then((np)=>np===null?null:{cur:null,np})
flow.then((res)=>{
if(!res)return
bridgeCall("security.set_pin",[res.np,res.cur]).then((msg)=>{
setStatus("setSecStatus",msg,false)
setLoadSecurity()
}).catch((err)=>setStatus("setSecStatus",err&&err.message?err.message:"Failed",true))
})
})
}
function setDoToggleLock(){
const checked=document.getElementById("setLockToggle").checked
if(checked){
bridgeCall("security.status").then((cfg)=>{
const p=cfg.pin_set?Promise.resolve(""):setPromptPin("Set PIN","PIN is required to enable app lock.",true)
p.then((newPin)=>{
if(newPin===null){document.getElementById("setLockToggle").checked=false;return}
bridgeCall("security.set_app_lock",[true,newPin]).then((msg)=>{setStatus("setSecStatus",msg,false);setLoadSecurity()}).catch((err)=>{
setStatus("setSecStatus",err&&err.message?err.message:"Failed",true)
document.getElementById("setLockToggle").checked=false
})
})
})
}else{
// Turning the lock off needs the current PIN (the backend refuses without it).
bridgeCall("security.status").then((cfg)=>{
const p=cfg.pin_set?setPromptPin("Disable App Lock","Enter your PIN to turn app lock off.",false):Promise.resolve("")
p.then((pin)=>{
if(pin===null){document.getElementById("setLockToggle").checked=true;return}
bridgeCall("security.set_app_lock",[false,pin]).then((msg)=>{setStatus("setSecStatus",msg,false);setLoadSecurity()}).catch((err)=>{
setStatus("setSecStatus",err&&err.message?err.message:"Failed",true)
document.getElementById("setLockToggle").checked=true
})
})
})
}
}
function setDoToggleEnc(){
const checked=document.getElementById("setEncToggle").checked
if(checked){
bridgeCall("security.status").then((cfg)=>{
if(!cfg.crypto_available){setStatus("setSecStatus","cryptography is not installed.",true);document.getElementById("setEncToggle").checked=false;return}
const p=cfg.pin_set?setPromptPin("Enable Encryption","Enter PIN to enable encryption.",false).then((pin)=>pin===null?null:{pin,newPin:null}):setPromptPin("Set PIN","PIN is required for encryption (at least 6 characters).",true).then((np)=>np===null?null:{pin:null,newPin:np})
p.then((res)=>{
if(!res){document.getElementById("setEncToggle").checked=false;return}
bridgeCall("security.set_encryption",[true,res.pin,res.newPin]).then((msg)=>{setStatus("setSecStatus",msg,false);setLoadSecurity()}).catch((err)=>{
setStatus("setSecStatus",err&&err.message?err.message:"Failed",true)
document.getElementById("setEncToggle").checked=false
})
})
})
}else{
bridgeCall("security.status").then((cfg)=>{
const p=cfg.enc_enabled?setPromptPin("Disable Encryption","Enter PIN to disable encryption.",false):Promise.resolve("")
p.then((pin)=>{
if(pin===null){document.getElementById("setEncToggle").checked=true;return}
bridgeCall("security.set_encryption",[false,pin,null]).then((msg)=>{setStatus("setSecStatus",msg,false);setLoadSecurity()}).catch((err)=>{
setStatus("setSecStatus",err&&err.message?err.message:"Failed",true)
document.getElementById("setEncToggle").checked=true
})
})
})
}
}
const SET_RUN_BEHAVIOUR_FIELDS={setSnipClickAction:"snippet_click_action",setCmdClickAction:"command_click_action",setSnipRunConfirm:"snippet_run_confirm",setCmdRunConfirm:"command_run_confirm",setRunDestination:"run_destination"}
function setApplyRunBehaviour(s){
Object.keys(SET_RUN_BEHAVIOUR_FIELDS).forEach((id)=>{
const el=document.getElementById(id)
if(el&&s[SET_RUN_BEHAVIOUR_FIELDS[id]])el.value=s[SET_RUN_BEHAVIOUR_FIELDS[id]]
})
document.getElementById("setTermPasteConfirm").checked=s.confirm_multiline_paste!==false
const fullDefault=document.getElementById("setTermFullDefault")
if(fullDefault)fullDefault.checked=!!s.full_terminal_default
}
function setDoSaveRunBehaviour(){
const values={confirm_multiline_paste:document.getElementById("setTermPasteConfirm").checked,use_conpty:document.getElementById("setTermConpty").checked,full_terminal_default:!!(document.getElementById("setTermFullDefault")||{}).checked}
Object.keys(SET_RUN_BEHAVIOUR_FIELDS).forEach((id)=>{values[SET_RUN_BEHAVIOUR_FIELDS[id]]=document.getElementById(id).value})
bridgeCall("terminal.set_run_behaviour",[values]).then((s)=>{
setApplyRunBehaviour(s)
termApplyRunBehaviour(s)
setStatus("setRunBehaviourStatus","Saved.",false)
}).catch((err)=>setStatus("setRunBehaviourStatus",err&&err.message?err.message:"Failed",true))
}
function setApplyTerminalSuggest(s){
if(!s)return
const box=document.getElementById("setTermSuggest")
if(box)box.checked=s.suggest_enabled!==false
const wrap=document.getElementById("setTermShortcuts")
if(!wrap||typeof TERM_SHORTCUT_ACTIONS==="undefined")return
wrap.innerHTML=TERM_SHORTCUT_ACTIONS.map((a)=>{
const combo=termShortcutFor(s.shortcuts,a.id)
return '<div class="set-row set-shortcut-row"><span>'+setEscapeHtml(a.label)+'</span><input type="text" readonly class="set-input set-shortcut-input" data-action="'+setEscapeHtml(a.id)+'" data-combo="'+setEscapeHtml(combo)+'" value="'+setEscapeHtml(combo||"Not set")+'"><button type="button" class="set-btn set-shortcut-reset" data-action="'+setEscapeHtml(a.id)+'"'+(combo===a.fallback?" disabled":"")+'>Reset</button></div>'
}).join("")
}
function setSaveTerminalShortcut(action,combo){
const values={}
values[action]=combo
bridgeCall("terminal.set_shortcuts",[values]).then((s)=>{
setApplyTerminalSuggest(s)
termApplySuggestSettings(s)
setStatus("setTermShortcutStatus","Saved.",false)
}).catch((err)=>{
setStatus("setTermShortcutStatus",err&&err.message?err.message:"Failed",true)
bridgeCall("terminal.get_settings").then(setApplyTerminalSuggest).catch(()=>{})
})
}
function setHandleShortcutKeydown(e){
const input=e.target.closest(".set-shortcut-input")
if(!input)return
e.preventDefault()
e.stopPropagation()
if(e.key==="Escape"){input.value=input.dataset.combo||"Not set";input.blur();return}
if((e.key==="Backspace"||e.key==="Delete")&&!e.ctrlKey&&!e.altKey){setSaveTerminalShortcut(input.dataset.action,"");input.blur();return}
const combo=shortcutFromEvent(e)
if(!combo)return
const normal=shortcutNormalize(combo)
if(!normal){setStatus("setTermShortcutStatus",combo+" needs Ctrl or Alt, or use F1-F12.",true);return}
const conflict=shortcutConflict(normal)
if(conflict){setStatus("setTermShortcutStatus",conflict,true);return}
input.value=normal
input.blur()
setSaveTerminalShortcut(input.dataset.action,normal)
}
function setParseEnv(text){
const env={}
String(text||"").split(",").forEach((pair)=>{
const at=pair.indexOf("=")
if(at<1)return
const key=pair.slice(0,at).trim()
if(key)env[key]=pair.slice(at+1).trim()
})
return env
}
function setFormatEnv(env){
return Object.keys(env||{}).map((key)=>key+"="+env[key]).join(", ")
}
function setRenderProfiles(profiles){
const wrap=document.getElementById("setProfileList")
if(!profiles.length){wrap.innerHTML='<div class="set-info">No profiles saved yet.</div>';return}
wrap.innerHTML=profiles.map((p)=>{
const bits=[p.shell_id||"default shell",p.cwd||"",p.startup?"runs: "+p.startup:""].filter(Boolean).join("  |  ")
return '<div class="set-profile-row" data-id="'+setEscapeHtml(p.id)+'"><span class="set-profile-name">'+setEscapeHtml(p.name)+'</span><span class="set-profile-meta">'+setEscapeHtml(bits)+'</span><button type="button" class="set-btn set-profile-edit">Edit</button><button type="button" class="set-btn set-profile-del">Delete</button></div>'
}).join("")
}
function setLoadProfiles(){
return Promise.all([bridgeCall("terminal.profiles"),bridgeCall("terminal.shells")]).then(([profiles,shells])=>{
setProfileCache=profiles
setRenderProfiles(profiles)
const select=document.getElementById("setProfileShell")
select.innerHTML=shells.map((s)=>'<option value="'+setEscapeHtml(s.id)+'">'+setEscapeHtml(s.label)+"</option>").join("")
}).catch((err)=>console.error("profiles load failed",err))
}
function setResetProfileForm(){
document.getElementById("setProfileId").value=""
document.getElementById("setProfileName").value=""
document.getElementById("setProfileCwd").value=""
document.getElementById("setProfileStartup").value=""
document.getElementById("setProfileEnv").value=""
}
function setDoSaveProfile(){
const profile={id:document.getElementById("setProfileId").value||undefined,name:document.getElementById("setProfileName").value,shell_id:document.getElementById("setProfileShell").value,cwd:document.getElementById("setProfileCwd").value,startup:document.getElementById("setProfileStartup").value,env:setParseEnv(document.getElementById("setProfileEnv").value)}
bridgeCall("terminal.profile_save",[profile]).then((profiles)=>{
setProfileCache=profiles
setRenderProfiles(profiles)
setResetProfileForm()
setStatus("setProfileStatus","Profile saved.",false)
termRefreshProfiles()
}).catch((err)=>setStatus("setProfileStatus",err&&err.message?err.message:"Failed",true))
}
let setProfileCache=[]
function setLoadExtensions(){
bridgeCall("terminal.get_settings").then((s)=>{
document.getElementById("setTermToggle").checked=s.enabled
document.getElementById("setTermConptyRow").classList.toggle("hidden",!s.conpty_supported)
document.getElementById("setTermConptyInfo").classList.toggle("hidden",!s.conpty_supported)
document.getElementById("setTermConpty").checked=!!s.use_conpty
setApplyRunBehaviour(s)
setApplyTerminalSuggest(s)
}).catch((err)=>console.error("terminal settings load failed",err))
setLoadProfiles()
bridgeCall("ai.get_settings").then((s)=>{
document.getElementById("setAiToggle").checked=s.enabled
}).catch((err)=>console.error("ai settings load failed",err))
}
function setDoToggleTerminal(){
const checked=document.getElementById("setTermToggle").checked
bridgeCall("terminal.set_enabled",[checked]).then(()=>{
setStatus("setTermStatus",checked?"Terminal extension enabled.":"Terminal extension disabled.",false)
termRefreshEnabled()
}).catch((err)=>{
setStatus("setTermStatus",err&&err.message?err.message:"Failed",true)
document.getElementById("setTermToggle").checked=!checked
})
}
function setDoToggleAi(){
const checked=document.getElementById("setAiToggle").checked
bridgeCall("ai.set_enabled",[checked]).then(()=>{
setStatus("setAiStatus",checked?"AI extension enabled.":"AI extension disabled.",false)
aiRefreshEnabled()
}).catch((err)=>{
setStatus("setAiStatus",err&&err.message?err.message:"Failed",true)
document.getElementById("setAiToggle").checked=!checked
})
}
function setAiStatusPillId(kind){
return {api:"aiStatusApi",ollama:"aiStatusOllama",lmstudio:"aiStatusLmstudio",mcp:"aiStatusMcp"}[kind]
}
function setAiOfflineCardId(kind){
return {api:"aiOfflineCardApi",ollama:"aiOfflineCardOllama",lmstudio:"aiOfflineCardLmstudio",mcp:"aiOfflineCardMcp"}[kind]
}
const AI_OFFLINE_GUIDANCE={
ollama:"Install Ollama from <code>ollama.com</code>, then run <code>ollama serve</code> (or <code>ollama run &lt;model&gt;</code>) and Test again.",
lmstudio:"Install LM Studio, load a model, and enable the local server (Developer tab) on the port configured above.",
api:"Check that the API key is correct and the base URL matches the provider's docs.",
mcp:"Check that the server URL is correct and the MCP server is running and reachable - or click \"Start Local Server\" above to run LOYA NG's own bundled server instead.",
}
function setApplyAiStatus(kind,result){
const status=result&&result.status?result.status:"offline"
const el=document.getElementById(setAiStatusPillId(kind))
if(el){
el.className="ai-status-pill "+status
el.textContent=status==="not_installed"?"Not Installed":status==="online"?"Online":"Offline"
}
const card=document.getElementById(setAiOfflineCardId(kind))
if(!card)return
if(status==="offline"||status==="not_installed"){
const guidance=AI_OFFLINE_GUIDANCE[kind]||""
const err=result&&result.error?`<div class="ai-offline-card-text">Error: ${setEscapeHtml(result.error)}</div>`:""
card.innerHTML=`<i class="icon icon-info"></i><div class="ai-offline-card-body"><div class="ai-offline-card-title">${status==="not_installed"?"Not Installed":"Offline"}</div><div class="ai-offline-card-text">${guidance}</div>${err}</div>`
card.classList.remove("hidden")
}else{
card.classList.add("hidden")
card.innerHTML=""
}
}
function setApplyAiDefaultButtons(defaultKind){
document.querySelectorAll(".ai-default-btn").forEach((btn)=>{
const isDefault=btn.dataset.provider===defaultKind
btn.classList.toggle("active",isDefault)
btn.querySelector(".icon").className="icon "+(isDefault?"icon-star-filled":"icon-star")
})
}
function setPopulateAiModelSelect(kind,models){
const select=document.querySelector(`.ai-model-select[data-provider="${kind}"]`)
if(!select)return
const cur=select.value
select.innerHTML='<option value="">Auto-detect / default</option>'
models.forEach((m)=>{
const opt=document.createElement("option")
opt.value=m.id
opt.textContent=m.label
select.appendChild(opt)
})
if(cur&&!Array.from(select.options).some((o)=>o.value===cur)){
const opt=document.createElement("option")
opt.value=cur
opt.textContent=cur
select.insertBefore(opt,select.options[1]||null)
}
select.value=cur
}
function setLoadAiProviders(){
bridgeCall("ai.providers").then((providers)=>{
Object.keys(providers).forEach((kind)=>{
const cfg=providers[kind]
document.querySelector(`.ai-provider-enable[data-provider="${kind}"]`).checked=!!cfg.enabled
document.querySelectorAll(`.ai-field[data-provider="${kind}"]`).forEach((el)=>{
const field=el.dataset.field
if(field==="api_key"){el.placeholder=cfg.api_key_set?`API key (set: ${cfg.api_key_masked})`:"API key";return}
if(field==="model"&&el.classList.contains("ai-model-select")){
if(cfg.model&&!Array.from(el.options).some((o)=>o.value===cfg.model)){
const opt=document.createElement("option")
opt.value=cfg.model
opt.textContent=cfg.model
el.appendChild(opt)
}
el.value=cfg.model||""
return
}
if(field in cfg)el.value=cfg[field]
})
})
}).catch((err)=>console.error("ai providers load failed",err))
bridgeCall("ai.get_default").then(setApplyAiDefaultButtons).catch((err)=>console.error("ai default load failed",err))
}
function setSaveAiField(kind,field,value){
bridgeCall("ai.set_provider",[kind,{[field]:value}]).catch((err)=>console.error("ai provider save failed",err))
}
function setDoToggleAiProvider(kind,checked){
bridgeCall("ai.set_provider",[kind,{enabled:checked}]).then(()=>{
if(!checked)bridgeCall("ai.get_default").then(setApplyAiDefaultButtons).catch(()=>{})
}).catch((err)=>console.error("ai provider toggle failed",err))
}
function setDoToggleAiDefault(kind){
const btn=document.querySelector(`.ai-default-btn[data-provider="${kind}"]`)
const nextKind=btn.classList.contains("active")?null:kind
bridgeCall("ai.set_default",[nextKind]).then(setApplyAiDefaultButtons).catch((err)=>setStatus("setAiDetectStatus",err&&err.message?err.message:"Failed",true))
}
function setLoadAiRoles(){
// Settings > AI > Roles: presets, Allow/Ask/Deny per entity and action, session grants and recent AI activity (ai.js aiRolesMount).
if(typeof aiRolesMount==="function")aiRolesMount(document.getElementById("setAiRolesRoot"))
bridgeCall("ai.terminal_approval_mode").then(setApplyTerminalApproval).catch(()=>{})
}
function setApplyTerminalApproval(mode){
const select=document.getElementById("setAiTerminalApproval")
const note=document.getElementById("setAiTerminalApprovalNote")
if(!select)return
select.value=mode==="allow"?"allow":"ask"
if(note)note.textContent=select.value==="allow"?"Commands run as soon as the AI asks. Anything matching a destructive pattern still stops for your approval - that fallback is enforced in the backend, not in this page.":"Every command the AI proposes waits for you to approve it, with the command and the AI's stated reason shown before you decide."
}
function setLoadOllamaSuggestions(){
bridgeCall("ai.ollama_suggested_models").then((items)=>{
const list=document.getElementById("aiOllamaSuggestList")
if(!list)return
list.innerHTML=items.map((m)=>`<option value="${setEscapeHtml(m.name)}">${m.cloud?"Cloud model":"Local model"}</option>`).join("")
}).catch(()=>{})
}
function setPollOllamaPull(pullId){
const statusEl=document.getElementById("aiOllamaPullStatus")
bridgeCall("ai.ollama_pull_poll",[pullId]).then((r)=>{
statusEl.classList.remove("error","success")
if(r.error){
statusEl.textContent=r.error
statusEl.classList.add("error")
document.getElementById("aiOllamaPullBtn").disabled=false
return
}
if(!r.done){
const pct=r.total?Math.round(100*(r.completed||0)/r.total):null
statusEl.textContent=(r.status||"Working...")+(pct!==null?` - ${pct}%`:"")
setTimeout(()=>setPollOllamaPull(pullId),500)
return
}
statusEl.textContent="Model pulled successfully."
statusEl.classList.add("success")
document.getElementById("aiOllamaPullBtn").disabled=false
bridgeCall("ai.list_models",["ollama"]).then((models)=>setPopulateAiModelSelect("ollama",models)).catch(()=>{})
}).catch((err)=>{
statusEl.classList.add("error")
statusEl.textContent=err&&err.message?err.message:"Pull failed"
document.getElementById("aiOllamaPullBtn").disabled=false
})
}
function setDoPullOllamaModel(){
const input=document.getElementById("aiOllamaPullInput")
const name=input.value.trim()
const statusEl=document.getElementById("aiOllamaPullStatus")
statusEl.classList.remove("error","success")
if(!name){statusEl.textContent="Enter a model name first.";statusEl.classList.add("error");return}
document.getElementById("aiOllamaPullBtn").disabled=true
statusEl.textContent="Starting..."
bridgeCall("ai.ollama_pull_start",[name]).then((pullId)=>{
setPollOllamaPull(pullId)
}).catch((err)=>{
statusEl.classList.add("error")
statusEl.textContent=err&&err.message?err.message:"Failed to start pull"
document.getElementById("aiOllamaPullBtn").disabled=false
})
}
function setDoTestAiProvider(kind){
const el=document.getElementById(setAiStatusPillId(kind))
if(el){el.className="ai-status-pill";el.textContent="Testing..."}
bridgeCall("ai.test_provider",[kind]).then((r)=>setApplyAiStatus(kind,r)).catch((err)=>{
setApplyAiStatus(kind,{status:"offline"})
setStatus("setAiDetectStatus",err&&err.message?err.message:"Test failed",true)
})
bridgeCall("ai.list_models",[kind]).then((models)=>setPopulateAiModelSelect(kind,models)).catch(()=>{})
}
function setLoadSemanticStatus(){
bridgeCall("ai.semantic_status").then((st)=>{
const pill=document.getElementById("setSemanticModePill")
pill.className="ai-status-pill "+(st.mode==="embedding"?"online":"")
pill.textContent=st.mode==="embedding"?`Embedding (${st.embed_model})`:"Keyword fallback"
setStatus("setSemanticStatus",`${st.doc_count} item(s) indexed`,false)
}).catch(()=>{})
}
function setDoRebuildSemanticIndex(){
const btn=document.getElementById("setSemanticRebuildBtn")
btn.disabled=true
setStatus("setSemanticStatus","Rebuilding…",false)
bridgeCall("ai.semantic_rebuild").then((r)=>{
setStatus("setSemanticStatus",`Rebuilt - ${r.count} item(s) indexed (${r.mode==="embedding"?`embedding: ${r.embed_model}`:"keyword fallback"})`,false)
setLoadSemanticStatus()
}).catch((err)=>setStatus("setSemanticStatus",err&&err.message?err.message:"Rebuild failed",true)).finally(()=>{btn.disabled=false})
}
function setApplyMcpLocalStatus(st){
const startBtn=document.getElementById("setMcpLocalStartBtn")
const stopBtn=document.getElementById("setMcpLocalStopBtn")
const statusEl=document.getElementById("setMcpLocalStatus")
if(!startBtn||!stopBtn||!statusEl)return
startBtn.classList.toggle("hidden",!!st.running)
stopBtn.classList.toggle("hidden",!st.running)
statusEl.textContent=st.running?`Local MCP server running at ${st.url}`:""
}
function setRefreshMcpLocalStatus(){
bridgeCall("ai.mcp_local_status").then(setApplyMcpLocalStatus).catch(()=>{})
}
function setDoStartMcpLocal(){
const btn=document.getElementById("setMcpLocalStartBtn")
btn.disabled=true
bridgeCall("ai.mcp_local_start").then((st)=>{
setApplyMcpLocalStatus(st)
setLoadAiProviders()
setDoTestAiProvider("mcp")
}).catch((err)=>{
setStatus("setMcpLocalStatus",err&&err.message?err.message:"Failed to start local server",true)
}).finally(()=>{btn.disabled=false})
}
function setDoStopMcpLocal(){
const btn=document.getElementById("setMcpLocalStopBtn")
btn.disabled=true
bridgeCall("ai.mcp_local_stop").then((st)=>{
setApplyMcpLocalStatus(st)
setLoadAiProviders()
}).catch((err)=>{
setStatus("setMcpLocalStatus",err&&err.message?err.message:"Failed to stop local server",true)
}).finally(()=>{btn.disabled=false})
}
function setDoDetectAiProviders(){
setStatus("setAiDetectStatus","Detecting...",false)
bridgeCall("ai.detect_all").then((results)=>{
Object.keys(results).forEach((kind)=>setApplyAiStatus(kind,results[kind]))
setStatus("setAiDetectStatus","Detection complete.",false)
}).catch((err)=>setStatus("setAiDetectStatus",err&&err.message?err.message:"Detection failed",true))
}
function setFmtSize(n){
n=n||0
if(n>=1048576)return (n/1048576).toFixed(1)+" MB"
if(n>=1024)return (n/1024).toFixed(1)+" KB"
return n+" B"
}
function setFmtWhen(ts){
if(!ts)return "-"
const d=new Date(ts*1000)
return d.getFullYear()+"-"+String(d.getMonth()+1).padStart(2,"0")+"-"+String(d.getDate()).padStart(2,"0")+" "+String(d.getHours()).padStart(2,"0")+":"+String(d.getMinutes()).padStart(2,"0")
}
function setRenderBackups(){
const tbody=document.getElementById("setBkTableBody")
tbody.innerHTML=""
setState.backups.forEach((b)=>{
const tr=document.createElement("tr")
tr.className=setState.backupSelected.has(b.path)?"selected":""
tr.innerHTML=`<td><input type="checkbox" ${setState.backupSelected.has(b.path)?"checked":""}></td><td>${setEscapeHtml(b.name)}</td><td>${setEscapeHtml(setFmtWhen(b.modified))}</td><td>${setEscapeHtml(setFmtSize(b.size))}</td><td><button type="button" class="set-row-x" title="Delete">&times;</button></td>`
tr.querySelector('input[type="checkbox"]').addEventListener("change",(e)=>{
if(e.target.checked)setState.backupSelected.add(b.path)
else setState.backupSelected.delete(b.path)
setRenderBackups()
})
tr.querySelector(".set-row-x").addEventListener("click",()=>{
appConfirm(`Delete backup "${b.name}"?`,{okLabel:"Delete",danger:true}).then((yes)=>{
if(!yes)return
bridgeCall("backup.delete",[[b.path]]).then((res)=>{setStatus("setBkStatus",`Deleted: ${res.ok} | Failed: ${res.bad}`,false);setRefreshBackups()}).catch((err)=>setStatus("setBkStatus",err&&err.message?err.message:"Failed",true))
})
})
tbody.appendChild(tr)
})
}
function setRefreshBackups(){
return bridgeCall("backup.list").then((rows)=>{setState.backups=rows;setRenderBackups()})
}
function setLoadBackupSettings(){
bridgeCall("backup.settings").then((cfg)=>{
document.getElementById("setBkAutoToggle").checked=cfg.auto_enabled
document.getElementById("setBkFreq").value=String(cfg.interval_hours)
document.getElementById("setBkKeep").value=String(cfg.keep)
document.getElementById("setBkOffsiteInput").value=cfg.offsite_dir||""
}).catch(()=>{})
}
function setSaveBackupSettings(){
const cfg={auto_enabled:document.getElementById("setBkAutoToggle").checked,interval_hours:parseInt(document.getElementById("setBkFreq").value,10),keep:parseInt(document.getElementById("setBkKeep").value,10),offsite_dir:document.getElementById("setBkOffsiteInput").value}
bridgeCall("backup.save_settings",[cfg]).then(()=>setStatus("setBkStatus","Auto backup settings saved.",false)).catch((err)=>setStatus("setBkStatus",err&&err.message?err.message:"Failed",true))
}
function setDoBrowseOffsiteDir(){
bridgeCall("backup.pick_offsite_dir").then((dir)=>{
if(!dir)return
document.getElementById("setBkOffsiteInput").value=dir
setSaveBackupSettings()
setStatus("setBkOffsiteStatus","Off-machine backup folder set.",false)
}).catch((err)=>setStatus("setBkOffsiteStatus",err&&err.message?err.message:"Failed",true))
}
function setDoClearOffsiteDir(){
document.getElementById("setBkOffsiteInput").value=""
setSaveBackupSettings()
setStatus("setBkOffsiteStatus","Off-machine backup copy disabled.",false)
}
function setLoadNotifySettings(){
return Promise.all([bridgeCall("notifications.settings"),bridgeCall("notifications.available")]).then(([cfg,avail])=>{
document.getElementById("setNotifyOsToggle").checked=!!cfg.os_enabled
document.getElementById("setNotifyOsToggle").disabled=!avail
document.getElementById("setNotifyTestBtn").disabled=!avail
if(!avail)setStatus("setNotifyStatus","OS notifications aren't available on this system.",true)
}).catch(()=>{})
}
function setSaveNotifySettings(){
const enabled=document.getElementById("setNotifyOsToggle").checked
bridgeCall("notifications.save_settings",[enabled]).then(()=>setStatus("setNotifyStatus",enabled?"OS notifications enabled.":"OS notifications disabled.",false)).catch((err)=>setStatus("setNotifyStatus",err&&err.message?err.message:"Failed",true))
}
function setDoTestNotify(){
setStatus("setNotifyStatus","Sending test notification...",false)
bridgeCall("notifications.send_test").then((ok)=>{setStatus("setNotifyStatus",ok?"Test notification sent.":"Could not send a notification on this system.",!ok)}).catch((err)=>setStatus("setNotifyStatus",err&&err.message?err.message:"Failed",true))
}
function setDoBackupNow(){
setStatus("setBkStatus","Creating backup...",false)
bridgeCall("backup.create").then((res)=>{
setStatus("setBkStatus","Created: "+res.name,false)
showStatusIsland("Backup complete","success")
setRefreshBackups()
}).catch((err)=>{
setStatus("setBkStatus",err&&err.message?err.message:"Failed",true)
showStatusIsland(err&&err.message?err.message:"Backup failed","error")
})
}
function setChooseRestoreMode(name,files){
return new Promise((resolve)=>{
const pop=setOpenPopover(340)
pop.innerHTML=`<div class="set-popover-title">Restore from ${setEscapeHtml(name)}</div>${files?`<p class="set-info">Files: ${files|0}</p>`:""}<p class="set-info">Merge keeps existing files and adds or updates from the ZIP. Replace swaps the Data folder for the ZIP contents.</p><div class="set-popover-actions"><button type="button" id="setModeCancel">Cancel</button><button type="button" id="setModeMerge">Merge</button><button type="button" class="set-popover-confirm" id="setModeReplace">Replace</button></div>`
pop.querySelector("#setModeCancel").addEventListener("click",()=>{setClosePopover();resolve("")})
pop.querySelector("#setModeMerge").addEventListener("click",()=>{setClosePopover();resolve("merge")})
pop.querySelector("#setModeReplace").addEventListener("click",()=>{setClosePopover();resolve("replace")})
})
}
// An encrypted .loyabak made under another PIN (or on another machine) opens only with that PIN: ask for it, never guess.
// A backup under this session's data key keeps the current key file (and PIN) by itself. Another key replaces it: the current
// PIN re-wraps the backup's key so the PIN does not change; skipping that brings the backup's PIN back, after a clear warning.
const SET_BACKUP_PIN_WARNING="This backup uses the PIN that was set when it was made. After restore, unlock with that PIN."
function setBackupPin(inspectFn,path,mode){
return bridgeCall(inspectFn,[path]).then((chk)=>{
if(!chk||!chk.needs_pin)return {pin:null,current_pin:null}
return setPromptPin("Backup PIN","This encrypted backup was made under a different PIN. Enter the PIN that was set when it was made.",false).then((pin)=>{
if(pin===null)return null
if(mode!=="replace")return {pin,current_pin:null}
return setPromptPin("Keep your current PIN","Enter your current PIN to keep using it after the restore. Skip to switch to the backup's PIN.",false,"Skip").then((cur)=>{
if(cur===null)return null
if(cur)return {pin,current_pin:cur}
return appConfirm(SET_BACKUP_PIN_WARNING,{okLabel:"Restore anyway",danger:true}).then((yes)=>yes?{pin,current_pin:null}:null)
})
})
})
}
function setDoRestoreSelected(){
const sel=Array.from(setState.backupSelected)
const pick=sel.length?Promise.resolve({path:sel[0],name:(setState.backups.find((x)=>x.path===sel[0])||{}).name||sel[0]}):bridgeCall("importExport.pick_import_all")
pick.then((src)=>{
if(!src)return
return setChooseRestoreMode(src.name,src.files).then((mode)=>{
if(!mode)return
return setBackupPin("backup.needs_pin",src.path,mode).then((p)=>{
if(!p){setStatus("setBkStatus","Restore cancelled.",false);return}
setStatus("setBkStatus","Restoring...",false)
return bridgeCall("backup.restore",[src.path,mode,p.pin,p.current_pin]).then((msg)=>setStatus("setBkStatus",msg,false))
})
})
}).catch((err)=>setStatus("setBkStatus",err&&err.message?err.message:"Failed",true))
}
function setDoDeleteSelectedBackups(){
const sel=Array.from(setState.backupSelected)
if(sel.length<2)return
appConfirm(`Delete ${sel.length} selected backups?`,{okLabel:"Delete",danger:true}).then((yes)=>{
if(!yes)return
bridgeCall("backup.delete",[sel]).then((res)=>{setStatus("setBkStatus",`Deleted: ${res.ok} | Failed: ${res.bad}`,false);setState.backupSelected.clear();setRefreshBackups()}).catch((err)=>setStatus("setBkStatus",err&&err.message?err.message:"Failed",true))
})
}
function setFilteredTags(){
const q=setState.tagSearch.trim().toLowerCase()
if(!q)return setState.tags
return setState.tags.filter((t)=>t.tag.toLowerCase().includes(q))
}
function setRenderTags(){
const tbody=document.getElementById("setTagTableBody")
tbody.innerHTML=""
setFilteredTags().forEach((t)=>{
const tr=document.createElement("tr")
tr.className=setState.tagSelected.has(t.tag)?"selected":""
tr.innerHTML=`<td><input type="checkbox" ${setState.tagSelected.has(t.tag)?"checked":""}></td><td>${setEscapeHtml(t.tag)}</td><td>${t.commands_notes|0}</td><td>${t.linked|0}</td><td>${t.notes_tagged|0}</td><td>${t.total|0}</td>`
tr.querySelector('input[type="checkbox"]').addEventListener("change",(e)=>{
if(e.target.checked)setState.tagSelected.add(t.tag)
else setState.tagSelected.delete(t.tag)
setRenderTags()
})
tbody.appendChild(tr)
})
}
function setRefreshTags(){
return bridgeCall("tags.list").then((rows)=>{
setState.tags=rows||[]
const live=new Set(setState.tags.map((t)=>t.tag))
Array.from(setState.tagSelected).forEach((t)=>{if(!live.has(t))setState.tagSelected.delete(t)})
setRenderTags()
})
}
function setTagCheck(mode,tags,newTag){
if(!tags.length)return "Select at least one tag."
if(mode==="rename"&&tags.length!==1)return "Select exactly one tag to rename."
if(mode==="merge"&&tags.length<2)return "Select two or more tags to merge."
if(mode!=="delete"&&!newTag)return "Enter the new tag name."
if(mode==="rename"&&tags[0].toLowerCase()===newTag.toLowerCase())return "The new name matches the old tag."
return ""
}
function setTagApply(mode){
const tags=Array.from(setState.tagSelected)
const newTag=document.getElementById("setTagNew").value.trim()
const includeLinked=document.getElementById("setTagLinked").checked
const problem=setTagCheck(mode,tags,newTag)
if(problem){setStatus("setTagStatus",problem,true);return}
const msg=`${mode[0].toUpperCase()+mode.slice(1)} tag(s): ${tags.join(", ")}`+(mode!=="delete"?` -> ${newTag}`:"")
appConfirm(msg+"\n\nThis updates Commands Notes and note tags"+(includeLinked?", plus linked commands and command cards inside notes.":"."),{okLabel:"Apply",danger:mode==="delete"}).then((yes)=>{
if(!yes){setStatus("setTagStatus","Cancelled. Nothing was changed.",false);return}
const call=mode==="rename"?bridgeCall("tags.rename",[tags,newTag,includeLinked]):mode==="merge"?bridgeCall("tags.merge",[tags,newTag,includeLinked]):bridgeCall("tags.delete",[tags,includeLinked])
call.then((res)=>{
setStatus("setTagStatus",`Updated Commands Notes:${res.commands_notes} Note tags:${res.note_tags||0} Linked:${res.linked} Note cards:${res.notes}`,false)
setState.tagSelected.clear()
document.getElementById("setTagNew").value=""
setRefreshTags()
}).catch((err)=>setStatus("setTagStatus",err&&err.message?err.message:"Failed",true))
})
}
function setFmtWhenIso(s){
if(!s)return "-"
try{return new Date(s).toISOString().slice(0,19).replace("T"," ")}catch(e){return s}
}
function setDaysLeft(expires){
if(!expires)return "-"
try{
const d=new Date(expires)
const now=new Date()
const days=Math.ceil((d-now)/86400000)
if(days<0)return "Expired"
if(days===0)return "Today"
return days+"d"
}catch(e){return "-"}
}
const RB_TYPE_LABELS={note:"Note",command:"Command",target:"Target",report:"Report",report_finding:"Report finding",report_evidence:"Report evidence"}
function setFilteredRb(){
const q=setState.rbSearch.trim().toLowerCase()
if(!q)return setState.rb
return setState.rb.filter((it)=>(it.label||"").toLowerCase().includes(q)||(it.source||"").toLowerCase().includes(q)||(RB_TYPE_LABELS[it.entity_type]||it.entity_type||"").toLowerCase().includes(q))
}
function setRenderRb(){
const tbody=document.getElementById("setRbTableBody")
tbody.innerHTML=""
setFilteredRb().forEach((it)=>{
const tr=document.createElement("tr")
tr.className=setState.rbSelected.has(it.id)?"selected":""
tr.innerHTML=`<td><input type="checkbox" ${setState.rbSelected.has(it.id)?"checked":""}></td><td>${setEscapeHtml(RB_TYPE_LABELS[it.entity_type]||it.entity_type)}</td><td>${setEscapeHtml(it.label||"-")}</td><td>${setEscapeHtml(it.source||"-")}</td><td>${setEscapeHtml(setFmtWhenIso(it.deleted_at))}</td><td>${setEscapeHtml(setFmtWhenIso(it.expires_at))}</td><td>${setEscapeHtml(setDaysLeft(it.expires_at))}</td>`
tr.querySelector('input[type="checkbox"]').addEventListener("change",(e)=>{
if(e.target.checked)setState.rbSelected.add(it.id)
else setState.rbSelected.delete(it.id)
setRenderRb()
})
tbody.appendChild(tr)
})
}
function setRefreshRb(){
return bridgeCall("recycleBin.list",[setState.rbType]).then((rows)=>{
setState.rb=rows
setRenderRb()
setStatus("setRbStatus",rows.length+" item(s) in Recycle Bin.",false)
})
}
function setRefreshRbRetention(){
return bridgeCall("recycleBin.get_retention_days").then((days)=>{
document.getElementById("setRbRetentionInput").value=days
}).catch(()=>{})
}
function setSaveRbRetention(){
const val=parseInt(document.getElementById("setRbRetentionInput").value,10)
bridgeCall("recycleBin.set_retention_days",[val]).then((days)=>{
document.getElementById("setRbRetentionInput").value=days
setStatus("setRbRetentionStatus",`Retention set to ${days} day(s).`,false)
}).catch((err)=>setStatus("setRbRetentionStatus",err&&err.message?err.message:"Failed",true))
}
function setRbReport(verb,res){
const failed=(res&&res.failed)||[]
const why=failed.slice(0,5).map((f)=>`${f.label||"#"+f.id}: ${f.error}`).join("; ")
setStatus("setRbStatus",`${verb}: ${(res&&res.ok)||0} | Failed: ${failed.length}`+(why?` - ${why}`+(failed.length>5?" ...":""):""),failed.length>0)
}
function setDoRestoreSelectedRb(){
const ids=Array.from(setState.rbSelected)
if(!ids.length)return
appConfirm(`Restore ${ids.length} item(s) from Recycle Bin?`,{okLabel:"Restore"}).then((yes)=>{
if(!yes)return
bridgeCall("recycleBin.restore_many",[ids]).then((res)=>{
setState.rbSelected.clear()
return setRefreshRb().then(()=>setRbReport("Restored",res))
}).catch((err)=>setStatus("setRbStatus",err&&err.message?err.message:"Failed",true))
})
}
function setDoDeleteSelectedRb(){
const ids=Array.from(setState.rbSelected)
if(!ids.length)return
appConfirm(`Permanently delete ${ids.length} Recycle Bin item(s)? This cannot be undone.`,{okLabel:"Delete",danger:true}).then((yes)=>{
if(!yes)return
bridgeCall("recycleBin.delete_many",[ids]).then((res)=>{
setState.rbSelected.clear()
return setRefreshRb().then(()=>setRbReport("Deleted permanently",res))
}).catch((err)=>setStatus("setRbStatus",err&&err.message?err.message:"Failed",true))
})
}
function setDoRestoreAllRb(){
const ids=setFilteredRb().map((it)=>it.id)
if(!ids.length)return
appConfirm(`Restore all ${ids.length} item(s) currently shown from Recycle Bin?`,{okLabel:"Restore All"}).then((yes)=>{
if(!yes)return
bridgeCall("recycleBin.restore_many",[ids]).then((res)=>setRefreshRb().then(()=>setRbReport("Restored all",res))).catch((err)=>setStatus("setRbStatus",err&&err.message?err.message:"Failed",true))
})
}
function setDoPurgeNow(){
bridgeCall("recycleBin.list",[""]).then((all)=>{
const total=(all||[]).length
if(!total){setStatus("setRbStatus","The Recycle Bin is empty.",false);return}
const hidden=total-setFilteredRb().length
return appConfirm(`Permanently delete ALL ${total} item(s) in the Recycle Bin`+(hidden>0?`, including ${hidden} not shown by the current filter`:"")+`? This cannot be undone.`,{okLabel:"Purge All",danger:true}).then((yes)=>{
if(!yes)return
return bridgeCall("recycleBin.purge_all").then((n)=>{setState.rbSelected.clear();return setRefreshRb().then(()=>setStatus("setRbStatus",`Purged: ${n} item(s).`,false))})
})
}).catch((err)=>setStatus("setRbStatus",err&&err.message?err.message:"Failed",true))
}
const SET_IE_ENTITIES={
all:{label:"All Data (full backup ZIP)",formats:null},
target_values:{label:"Target Values",formats:["json","csv"],exportFn:"export_target_values",pickFn:"pick_target_values_import",applyFn:"apply_target_values_import"},
targets:{label:"Targets",formats:["json","csv"],exportFn:"export_targets",pickFn:"pick_targets_import",applyFn:"apply_targets_import"},
notes:{label:"Notes",formats:["json","csv","markdown","json_all","csv_zip","db"],importFormats:["json","csv","json_all","csv_zip","db","markdown_folder","cherrytree"],exportFn:"export_notes",pickFn:"pick_notes_import",applyFn:"apply_notes_import"},
commands:{label:"Commands",formats:["json","csv"],exportFn:"export_commands",pickFn:"pick_commands_import",applyFn:"apply_commands_import"},
}
const SET_IE_FORMAT_LABELS={json:"JSON",csv:"CSV",markdown:"Markdown (ZIP)",markdown_folder:"Markdown folder (Obsidian / Joplin)",cherrytree:"CherryTree (.ctd)",json_all:"JSON - all tables (Notes + Commands)",csv_zip:"CSV ZIP - all tables",db:"SQLite database (.db)"}
const SET_IE_PICK_FORMAT={json_all:"json"}
// Dropped or browsed files: which formats each data type accepts for the file's extension ("all" = a full backup ZIP).
const SET_IE_EXT_FORMATS={json:["json","json_all"],csv:["csv"],zip:["csv_zip"],db:["db"],sqlite:["db"],ctd:["cherrytree"]}
function setIeFileExt(name){const m=/\.([a-z0-9]+)$/i.exec(String(name||""));return m?m[1].toLowerCase():""}
function setIeDropFormats(what,drop){
const ext=setIeFileExt(drop.name)
if(what==="all")return ext==="zip"?["all"]:[]
const cfg=SET_IE_ENTITIES[what];if(!cfg||!cfg.formats)return []
const allowed=cfg.importFormats||cfg.formats.filter((f)=>f!=="markdown")
return (SET_IE_EXT_FORMATS[ext]||[]).filter((f)=>allowed.includes(f))
}
function setIeGuessEntity(name){
const n=String(name||"").toLowerCase()
if(/target.?value|param/.test(n))return "target_values"
if(/target/.test(n))return "targets"
if(/command|cmd/.test(n))return "commands"
return "notes"
}
function setIeEntityOptions(drop){
return Object.keys(SET_IE_ENTITIES).filter((k)=>!drop||setIeDropFormats(k,drop).length).map((k)=>`<option value="${k}">${setEscapeHtml(SET_IE_ENTITIES[k].label)}</option>`).join("")
}
function setOpenExportModal(){
const el=document.createElement("div")
el.className="set-ie-modal glass-panel"
el.innerHTML=`<div class="set-ie-modal-title">Export Data</div><div class="set-ie-field"><label>What to export</label><select id="setIeExpWhat" class="set-select">${setIeEntityOptions()}</select></div><div class="set-ie-field" id="setIeExpFormatWrap"><label>Format</label><select id="setIeExpFormat" class="set-select"></select></div><div class="set-status" id="setIeExpStatus"></div><div class="set-ie-modal-actions"><button type="button" id="setIeExpCancel">Cancel</button><button type="button" class="set-ie-confirm" id="setIeExpConfirm">Export</button></div>`
openModal(el)
function refreshFormats(){
const cfg=SET_IE_ENTITIES[document.getElementById("setIeExpWhat").value]
const wrap=document.getElementById("setIeExpFormatWrap")
if(!cfg.formats){wrap.classList.add("hidden");return}
wrap.classList.remove("hidden")
document.getElementById("setIeExpFormat").innerHTML=cfg.formats.map((f)=>`<option value="${f}">${SET_IE_FORMAT_LABELS[f]}</option>`).join("")
}
document.getElementById("setIeExpWhat").addEventListener("change",refreshFormats)
refreshFormats()
document.getElementById("setIeExpCancel").addEventListener("click",closeModal)
document.getElementById("setIeExpConfirm").addEventListener("click",()=>{
const what=document.getElementById("setIeExpWhat").value
const statusEl=document.getElementById("setIeExpStatus")
statusEl.classList.remove("error")
statusEl.textContent="Working..."
if(what==="all"){
bridgeCall("importExport.export_all").then((res)=>{statusEl.textContent=res?`Created: ${res.name} (${res.files} file(s))`:"Cancelled."}).catch((err)=>{statusEl.textContent=err&&err.message?err.message:"Failed";statusEl.classList.add("error")})
return
}
const fmt=document.getElementById("setIeExpFormat").value
// Encryption at rest on: a full plain copy (SQLite DB) is written only after the PIN is typed again, with an explicit warning.
bridgeCall("importExport.export_needs_pin",[what,fmt]).then((chk)=>{
if(!chk||!chk.needs_pin)return [fmt]
return setPromptPin("Unencrypted export",chk.warning+" Enter your PIN to continue.",false).then((pin)=>pin===null?null:[fmt,pin])
}).then((args)=>{
if(!args){statusEl.textContent="Cancelled.";return}
return bridgeCall(`importExport.${SET_IE_ENTITIES[what].exportFn}`,args).then((path)=>{statusEl.textContent=path?(args.length>1?"Exported (NOT encrypted) to ":"Exported to ")+path:"Cancelled."})
}).catch((err)=>{statusEl.textContent=err&&err.message?err.message:"Failed";statusEl.classList.add("error")})
})
}
function setOpenReportModal(){
const el=document.createElement("div")
el.className="set-ie-modal set-report-modal glass-panel"
el.innerHTML=`<div class="set-ie-modal-title">Build Report</div>
<div class="set-ie-field">
<label>Notes to include</label>
<div class="set-report-picker-actions"><button type="button" id="setReportSelectAll">Select all</button><button type="button" id="setReportSelectNone">Select none</button></div>
<div class="set-report-notelist" id="setReportNoteList"><div class="set-status">Loading...</div></div>
</div>
<div class="set-ie-field"><label>Report title</label><input type="text" id="setReportTitle" class="set-input" placeholder="LOYA NG Report"></div>
<div class="set-ie-field"><label>Format</label><select id="setReportFormat" class="set-select"><option value="markdown">Markdown</option><option value="html">HTML</option><option value="pdf">PDF</option><option value="docx">Word Document (DOCX)</option></select></div>
<div class="set-report-branding hidden" id="setReportBrandingWrap">
<div class="set-ie-field"><label>Client name (optional)</label><input type="text" id="setReportClient" class="set-input" placeholder="Client name"></div>
<div class="set-ie-field"><label>Date (optional)</label><input type="text" id="setReportDate" class="set-input" placeholder="2026-08-01"></div>
<div class="set-ie-field"><label>Logo (optional)</label><div class="set-report-logo-row"><button type="button" class="set-btn" id="setReportLogoBtn">Choose Logo...</button><span id="setReportLogoName">No logo selected</span></div><input type="file" id="setReportLogoInput" accept="image/*" class="hidden"></div>
</div>
<div class="set-status" id="setReportStatus"></div>
<div class="set-ie-modal-actions"><button type="button" id="setReportCancel">Cancel</button><button type="button" class="set-ie-confirm" id="setReportBuild">Build Report</button></div>`
openModal(el)
let logoDataUrl=""
bridgeCall("notes.list").then((notes)=>{
const list=el.querySelector("#setReportNoteList")
if(!notes||!notes.length){list.innerHTML='<div class="set-status">No notes yet.</div>';return}
list.innerHTML=notes.map((n)=>`<label class="set-report-note-row"><input type="checkbox" class="setReportNoteCk" value="${n.id}"><span class="set-report-note-name">${setEscapeHtml(n.note_name)}</span><span class="set-report-note-group">${setEscapeHtml(n.group_name||"Ungrouped")}</span></label>`).join("")
}).catch(()=>{el.querySelector("#setReportNoteList").innerHTML='<div class="set-status error">Failed to load notes.</div>'})
el.querySelector("#setReportSelectAll").addEventListener("click",()=>{el.querySelectorAll(".setReportNoteCk").forEach((c)=>{c.checked=true})})
el.querySelector("#setReportSelectNone").addEventListener("click",()=>{el.querySelectorAll(".setReportNoteCk").forEach((c)=>{c.checked=false})})
const formatSelect=el.querySelector("#setReportFormat")
const brandingWrap=el.querySelector("#setReportBrandingWrap")
formatSelect.addEventListener("change",()=>{brandingWrap.classList.toggle("hidden",formatSelect.value!=="docx")})
el.querySelector("#setReportLogoBtn").addEventListener("click",()=>el.querySelector("#setReportLogoInput").click())
el.querySelector("#setReportLogoInput").addEventListener("change",(e)=>{
const file=e.target.files[0]
if(!file)return
const reader=new FileReader()
reader.onload=()=>{logoDataUrl=reader.result;el.querySelector("#setReportLogoName").textContent=file.name}
reader.readAsDataURL(file)
})
el.querySelector("#setReportCancel").addEventListener("click",closeModal)
el.querySelector("#setReportBuild").addEventListener("click",()=>{
const ids=Array.from(el.querySelectorAll(".setReportNoteCk:checked")).map((c)=>parseInt(c.value,10))
const statusEl=el.querySelector("#setReportStatus")
statusEl.classList.remove("error")
if(!ids.length){statusEl.textContent="Select at least one note.";statusEl.classList.add("error");return}
const fmt=formatSelect.value
const branding={title:el.querySelector("#setReportTitle").value.trim(),client_name:el.querySelector("#setReportClient").value.trim(),date:el.querySelector("#setReportDate").value.trim(),logo_b64:logoDataUrl}
statusEl.textContent="Working..."
bridgeCall("importExport.build_report",[ids,fmt,branding]).then((path)=>{statusEl.textContent=path?"Report saved to "+path:"Cancelled."}).catch((err)=>{statusEl.textContent=err&&err.message?err.message:"Failed";statusEl.classList.add("error")})
})
}
function setOpenStatsModal(){
const el=document.createElement("div")
el.className="set-ie-modal glass-panel"
el.innerHTML=`<div class="set-ie-modal-title">Report Statistics</div><div class="set-ie-field"><label>Format</label><select id="setStatsFormat" class="set-select"><option value="json">JSON</option><option value="html">HTML</option><option value="pdf">PDF</option><option value="png">PNG</option></select></div><div class="set-status" id="setStatsStatus"></div><div class="set-ie-modal-actions"><button type="button" id="setStatsCancel">Cancel</button><button type="button" class="set-ie-confirm" id="setStatsExport">Export</button></div>`
openModal(el)
el.querySelector("#setStatsCancel").addEventListener("click",closeModal)
el.querySelector("#setStatsExport").addEventListener("click",()=>{
const fmt=el.querySelector("#setStatsFormat").value
const statusEl=el.querySelector("#setStatsStatus")
statusEl.classList.remove("error")
statusEl.textContent="Working..."
if(fmt==="png"){
bridgeCall("dashboard.stats").then((stats)=>bridgeCall("importExport.export_stats_png",[setRenderStatsCanvas(stats)])).then((path)=>{statusEl.textContent=path?"Exported to "+path:"Cancelled."}).catch((err)=>{statusEl.textContent=err&&err.message?err.message:"Failed";statusEl.classList.add("error")})
return
}
bridgeCall("importExport.export_stats_report",[fmt]).then((path)=>{statusEl.textContent=path?"Exported to "+path:"Cancelled."}).catch((err)=>{statusEl.textContent=err&&err.message?err.message:"Failed";statusEl.classList.add("error")})
})
}
const SET_STATS_BAR_PALETTE=["#3b82f6","#8ab5ff","#8cecff","#5eead4","#a78bfa","#f472b6"]
function setFmtBytes(n){
const units=["B","KB","MB","GB"]
let v=n||0,i=0
while(v>=1024&&i<units.length-1){v/=1024;i++}
return i>0?v.toFixed(1)+" "+units[i]:Math.round(v)+" "+units[i]
}
function setRoundRect(ctx,x,y,w,h,r){
ctx.beginPath()
ctx.moveTo(x+r,y)
ctx.arcTo(x+w,y,x+w,y+h,r)
ctx.arcTo(x+w,y+h,x,y+h,r)
ctx.arcTo(x,y+h,x,y,r)
ctx.arcTo(x,y,x+w,y,r)
ctx.closePath()
}
function setTruncText(ctx,text,maxW){
if(ctx.measureText(text).width<=maxW)return text
let t=text
while(t.length>1&&ctx.measureText(t+"...").width>maxW)t=t.slice(0,-1)
return t+"..."
}
function setRenderStatsCanvas(stats){
const W=900
const groups=stats.notes_by_group||{}
const groupEntries=Object.entries(groups).sort((a,b)=>b[1]-a[1])
const backup=stats.backup_status||{}
const activity=stats.time_since_activity||{}
const engagement=stats.active_engagement||{}
const update=stats.update_status||{}
const backupVal=backup.latest_days_ago==null?"Never":(backup.latest_days_ago===0?"Today":backup.latest_days_ago+"d ago")
const cards=[
["Notes",String(stats.notes_count||0),"total notes"],
["Commands",String(stats.commands_count||0),(stats.commands_standalone||0)+" standalone / "+(stats.commands_linked||0)+" linked"],
["Targets",String(stats.targets_count||0),"saved targets"],
["Recycle Bin",String(stats.recycle_bin_count||0),"items"],
["Storage Usage",setFmtBytes(stats.storage_usage_bytes||0),"database size"],
["App Version","v"+(stats.app_version||"?"),"installed version"],
["Last Backup",backupVal,(backup.count||0)+" backups"],
["Last Activity",activity.label||"-",activity.what||""],
["Active Engagement",engagement.name||"Default",(engagement.targets_count||0)+" targets"],
["Update Status",update.label||"-",update.sub||""],
]
const cols=3,cardH=90,cardGap=14
const cardW=(W-64-cardGap*(cols-1))/cols
const cardRows=Math.ceil(cards.length/cols)
const groupRowH=26
const groupsH=groupEntries.length?(60+groupEntries.length*groupRowH+20):0
const H=110+cardRows*(cardH+cardGap)+groupsH+40
const canvas=document.createElement("canvas")
canvas.width=W;canvas.height=H
const ctx=canvas.getContext("2d")
ctx.fillStyle="#0d1117"
ctx.fillRect(0,0,W,H)
ctx.fillStyle="#ffffff"
ctx.font="700 26px \"Segoe UI\",system-ui,Cantarell,\"Noto Sans\",Arial,sans-serif"
ctx.fillText("LOYA NG - Report Statistics",32,52)
ctx.fillStyle="#9fb3c8"
ctx.font="12px \"Segoe UI\",system-ui,Cantarell,\"Noto Sans\",Arial,sans-serif"
ctx.fillText("Generated "+new Date().toISOString().slice(0,16).replace("T"," ")+" UTC",32,74)
const gridY=100
cards.forEach((c,i)=>{
const col=i%cols,row=Math.floor(i/cols)
const x=32+col*(cardW+cardGap)
const cy=gridY+row*(cardH+cardGap)
ctx.fillStyle="#141b24"
setRoundRect(ctx,x,cy,cardW,cardH,10);ctx.fill()
ctx.strokeStyle="#263446";ctx.lineWidth=1
setRoundRect(ctx,x,cy,cardW,cardH,10);ctx.stroke()
ctx.fillStyle="#ffffff"
ctx.font="700 22px \"Segoe UI\",system-ui,Cantarell,\"Noto Sans\",Arial,sans-serif"
ctx.fillText(setTruncText(ctx,c[1],cardW-32),x+16,cy+38)
ctx.fillStyle="#9fb3c8"
ctx.font="11px \"Segoe UI\",system-ui,Cantarell,\"Noto Sans\",Arial,sans-serif"
ctx.fillText(c[0],x+16,cy+58)
ctx.fillStyle="#8ab5ff"
ctx.fillText(setTruncText(ctx,c[2],cardW-32),x+16,cy+76)
})
let y=gridY+cardRows*(cardH+cardGap)+10
if(groupEntries.length){
ctx.fillStyle="#141b24"
setRoundRect(ctx,32,y,W-64,groupsH-10,10);ctx.fill()
ctx.strokeStyle="#263446";ctx.lineWidth=1
setRoundRect(ctx,32,y,W-64,groupsH-10,10);ctx.stroke()
ctx.fillStyle="#ffffff"
ctx.font="700 15px \"Segoe UI\",system-ui,Cantarell,\"Noto Sans\",Arial,sans-serif"
ctx.fillText("Notes by Group",52,y+28)
const total=groupEntries.reduce((s,g)=>s+g[1],0)||1
const barX=52+150,barMaxW=W-64-40-150-40
groupEntries.forEach((g,i)=>{
const ry=y+50+i*groupRowH
ctx.fillStyle="#9fb3c8"
ctx.font="12px \"Segoe UI\",system-ui,Cantarell,\"Noto Sans\",Arial,sans-serif"
ctx.fillText(setTruncText(ctx,g[0],140),52,ry+5)
ctx.fillStyle="#08111d"
ctx.fillRect(barX,ry-6,barMaxW,8)
const w=Math.max(2,Math.round(barMaxW*g[1]/total))
ctx.fillStyle=SET_STATS_BAR_PALETTE[i%SET_STATS_BAR_PALETTE.length]
ctx.fillRect(barX,ry-6,w,8)
ctx.fillStyle="#e8eef7"
ctx.textAlign="right"
ctx.fillText(String(g[1]),W-32,ry+5)
ctx.textAlign="left"
})
}
return canvas.toDataURL("image/png")
}
function setOpenImportModal(){
const el=document.createElement("div")
el.className="set-ie-modal glass-panel"
openModal(el)
setRenderImportPickStep(el)
}
// Import by drag-and-drop or click-to-browse: the page reads the file and stages a copy through the bridge (no real path is exposed
// to the page on either WebView2 or WebKitGTK), then the normal import dialog continues from that copy.
const SET_IE_UPLOAD_MAX=100*1024*1024
function setIeReadB64(file){return new Promise((res,rej)=>{const r=new FileReader();r.onload=()=>{const s=String(r.result||"");res(s.slice(s.indexOf(",")+1))};r.onerror=()=>rej(new Error("Could not read the file."));r.readAsDataURL(file)})}
function setIeImportFile(file){
const st=document.getElementById("setIeDropStatus")
const say=(t,err)=>{if(st){st.textContent=t;st.classList.toggle("error",!!err)}}
if(!file)return
const ext=setIeFileExt(file.name)
if(!SET_IE_EXT_FORMATS[ext]){say(`"${file.name}" is not an importable file. Use JSON, CSV, ZIP, SQLite DB or CherryTree (.ctd).`,true);return}
if(file.size>SET_IE_UPLOAD_MAX){say("That file is larger than 100 MB.",true);return}
say("Reading "+file.name+"...")
return setIeReadB64(file).then((b64)=>bridgeCall("importExport.stage_upload",[file.name,b64])).then((up)=>(ext==="zip"?bridgeCall("importExport.sniff_upload",[up.path]).catch(()=>({})):setIeSniffReport(up,file,ext)).then((sn)=>{
say("")
if(sn&&sn.report)return
const drop={path:up.path,name:file.name,guess:(sn&&sn.what)||setIeGuessEntity(file.name),format:(sn&&sn.format)||""}
const el=document.createElement("div")
el.className="set-ie-modal glass-panel"
openModal(el)
setRenderImportPickStep(el,drop)
})).catch((err)=>say(err&&err.message?err.message:"Import failed",true))
}
// A report, template or findings-library JSON belongs to the Reporting importer, which has its own confirmation step.
function setIeSniffReport(up,file,ext){
if(ext!=="json"||!window.ReportExport||typeof ReportExport.tryStaged!=="function")return Promise.resolve({})
return ReportExport.tryStaged(up.path,file.name).then((taken)=>({report:!!taken}))
}
// Reports box: the dialogs and the defaults form live in the Reporting module (UI/js/pages/reporting_export.js).
function setIeWireReports(){
const box=document.getElementById("setIeRptDefaults")
if(!box||box.dataset.wired)return
box.dataset.wired="1"
const RX=window.ReportExport||{}
const exp=(method,args)=>{
setStatus("setIeRptStatus","Working...",false)
bridgeCall("reportsIO."+method,args).then((path)=>setStatus("setIeRptStatus",path?"Exported to "+path:"Cancelled.",false)).catch((err)=>setStatus("setIeRptStatus",err&&err.message?err.message:"Failed",true))
}
document.getElementById("setIeOpenReportingBtn").addEventListener("click",()=>goToPage("reporting"))
document.getElementById("setIeRptExportAllBtn").addEventListener("click",()=>exp("export_many",[[],"json"]))
document.getElementById("setIeRptExportTplBtn").addEventListener("click",()=>exp("export_templates",[[]]))
document.getElementById("setIeRptExportLibBtn").addEventListener("click",()=>exp("export_library",[]))
document.getElementById("setIeRptImportBtn").addEventListener("click",()=>{
if(typeof RX.openImport!=="function"){setStatus("setIeRptStatus","Report import is not available in this build.",true);return}
setStatus("setIeRptStatus","",false)
RX.openImport({})
})
const mount=()=>{if(typeof RX.mountDefaults==="function")RX.mountDefaults(box)}
const tab=document.querySelector('.set-tab[data-tab="importexport"]')
if(tab)tab.addEventListener("click",mount)
mount()
}
function setIeWireDropZone(){
const zone=document.getElementById("setIeDrop"),input=document.getElementById("setIeDropInput")
if(!zone||!input||zone.dataset.wired)return
zone.dataset.wired="1"
const browse=()=>{input.value="";input.click()}
zone.addEventListener("click",(e)=>{if(e.target.closest("#setIeOpenImportBtn"))return;browse()})
zone.addEventListener("keydown",(e)=>{if(e.target!==zone)return;if(e.key==="Enter"||e.key===" "){e.preventDefault();browse()}})
input.addEventListener("change",()=>{if(input.files&&input.files[0])setIeImportFile(input.files[0])})
let depth=0
zone.addEventListener("dragenter",(e)=>{e.preventDefault();depth++;zone.classList.add("drag-over")})
zone.addEventListener("dragover",(e)=>{e.preventDefault();if(e.dataTransfer)e.dataTransfer.dropEffect="copy"})
zone.addEventListener("dragleave",()=>{depth=Math.max(0,depth-1);if(!depth)zone.classList.remove("drag-over")})
zone.addEventListener("drop",(e)=>{
e.preventDefault();depth=0;zone.classList.remove("drag-over")
const files=e.dataTransfer&&e.dataTransfer.files
if(!files||!files.length)return
setIeImportFile(files[0])
if(files.length>1)showToast("Importing the first file only - drop one file at a time.","info")
})
}
function setRenderImportPickStep(el,drop){
el.innerHTML=`<div class="set-ie-modal-title">${drop?"Import "+setEscapeHtml(drop.name):"Import Data"}</div><div class="set-ie-field"><label>What to import</label><select id="setIeImpWhat" class="set-select">${setIeEntityOptions(drop)}</select></div><div class="set-ie-field" id="setIeImpFormatWrap"><label>Format</label><select id="setIeImpFormat" class="set-select"></select></div><div class="set-status" id="setIeImpStatus"></div><div class="set-ie-modal-actions"><button type="button" id="setIeImpCancel">Cancel</button><button type="button" class="set-ie-confirm" id="setIeImpConfirm">Choose File...</button></div>`
function refreshConfirmLabel(){
const fmt=document.getElementById("setIeImpFormat").value
document.getElementById("setIeImpConfirm").textContent=drop?"Import":fmt==="markdown_folder"?"Choose Folder...":"Choose File..."
}
function refresh(){
const what=document.getElementById("setIeImpWhat").value
const cfg=SET_IE_ENTITIES[what]
document.getElementById("setIeImpFormatWrap").classList.toggle("hidden",what==="all")
if(cfg.formats)document.getElementById("setIeImpFormat").innerHTML=(drop?setIeDropFormats(what,drop):(cfg.importFormats||cfg.formats.filter((f)=>f!=="markdown"))).map((f)=>`<option value="${f}">${SET_IE_FORMAT_LABELS[f]}</option>`).join("")
refreshConfirmLabel()
}
document.getElementById("setIeImpFormat").addEventListener("change",refreshConfirmLabel)
document.getElementById("setIeImpWhat").addEventListener("change",refresh)
if(drop&&drop.guess&&[...document.getElementById("setIeImpWhat").options].some((o)=>o.value===drop.guess))document.getElementById("setIeImpWhat").value=drop.guess
refresh()
if(drop&&drop.format&&[...document.getElementById("setIeImpFormat").options].some((o)=>o.value===drop.format))document.getElementById("setIeImpFormat").value=drop.format
document.getElementById("setIeImpCancel").addEventListener("click",closeModal)
document.getElementById("setIeImpConfirm").addEventListener("click",()=>{
const what=document.getElementById("setIeImpWhat").value
const statusEl=document.getElementById("setIeImpStatus")
statusEl.classList.remove("error")
if(what==="all"){
bridgeCall("importExport.pick_import_all",drop?[drop.path]:[]).then((src)=>{
if(!src)return
return setChooseRestoreMode(src.name,src.files).then((mode)=>{
if(!mode){statusEl.textContent="Import cancelled.";return}
return setBackupPin("importExport.import_needs_pin",src.path,mode).then((p)=>{
if(!p){statusEl.textContent="Import cancelled.";return}
statusEl.textContent="Working..."
return bridgeCall("importExport.apply_import_all",[src.path,mode,p.pin,p.current_pin]).then((msg)=>{statusEl.textContent=msg})
})
})
}).catch((err)=>{statusEl.textContent=err&&err.message?err.message:"Failed";statusEl.classList.add("error")})
return
}
const fmt=SET_IE_PICK_FORMAT[document.getElementById("setIeImpFormat").value]||document.getElementById("setIeImpFormat").value
const cfg=SET_IE_ENTITIES[what]
bridgeCall(`importExport.${cfg.pickFn}`,drop?[fmt,drop.path]:[fmt]).then((res)=>{
if(!res)return
setRenderImportConfirmStep(el,cfg,fmt,res,drop)
}).catch((err)=>{statusEl.textContent=err&&err.message?err.message:"Failed";statusEl.classList.add("error")})
})
}
const SET_IE_DUP_ACTS=["Skip","Replace","Overwrite"]
const SET_IE_TABLE_LABELS={Notes:"Note",CommandsNotes:"Command"}
function setIeResultText(r){
return `Added:${r.added|0} Replaced:${r.replaced|0} Overwritten:${r.overwritten|0} Skipped:${r.skipped|0} Failed:${r.bad|0}`+(r.invalid?` | Invalid or repeated rows ignored:${r.invalid|0}`:"")
}
function setRenderImportConfirmStep(el,cfg,fmt,res,drop){
const plan=res.plan||{}
const dups=plan.dups||[]
const newCount=(plan.new||[]).length+(plan.new_commands||[]).length
const items=dups.map((d,i)=>{
const kind=SET_IE_TABLE_LABELS[d.table]||""
const detail=JSON.stringify(d.incoming||{})
return `<div class="set-dup-item" data-idx="${i}"><div class="set-dup-item-key">${kind?`<span class="set-dup-kind">${setEscapeHtml(kind)}</span> `:""}${setEscapeHtml(d.key||d.existing_key||"")}</div><div class="set-dup-item-detail">Incoming: ${setEscapeHtml(detail.length>400?detail.slice(0,400)+"...":detail)}</div><div class="set-dup-actions">${SET_IE_DUP_ACTS.map((a)=>`<button type="button" data-act="${a}"${a==="Skip"?' class="active"':""}>${a}</button>`).join("")}</div></div>`
}).join("")
const applyAll=dups.length>1?`<div class="set-ie-field set-dup-all"><label>Apply to all ${dups.length} conflicts</label><select id="setIeDupAll" class="set-select"><option value="">Choose per item</option>${SET_IE_DUP_ACTS.map((a)=>`<option value="${a}">${a} all</option>`).join("")}</select></div>`:""
const invalid=plan.invalid?`<p class="set-info">${plan.invalid|0} invalid or repeated row(s) in the file will be ignored.</p>`:""
el.innerHTML=`<button type="button" class="set-ie-back" id="setIeImpBack">&larr; Back</button><div class="set-ie-modal-title">${setEscapeHtml(cfg.label)} - ${dups.length} conflict(s), ${newCount} new</div>${invalid}<p class="set-info">Replace updates the existing item in place. Overwrite moves the existing item to the Recycle Bin and adds the incoming one as new.</p>${applyAll}<div class="set-dup-list">${items||'<p class="set-info">No conflicts - everything will be added.</p>'}</div><div class="set-status" id="setIeImpStatus"></div><div class="set-ie-modal-actions"><button type="button" id="setIeImpCancel2">Cancel</button><button type="button" class="set-ie-confirm" id="setIeImpApply">Apply</button></div>`
const decisions={}
dups.forEach((_,i)=>{decisions[i]="Skip"})
function setDecision(itemEl,act){
decisions[parseInt(itemEl.dataset.idx,10)]=act
itemEl.querySelectorAll("button[data-act]").forEach((b)=>b.classList.toggle("active",b.dataset.act===act))
}
el.querySelectorAll(".set-dup-item").forEach((itemEl)=>{
itemEl.querySelectorAll("button[data-act]").forEach((btn)=>{
btn.addEventListener("click",()=>{
setDecision(itemEl,btn.dataset.act)
const all=el.querySelector("#setIeDupAll")
if(all)all.value=""
})
})
})
const allSel=el.querySelector("#setIeDupAll")
if(allSel)allSel.addEventListener("change",()=>{if(allSel.value)el.querySelectorAll(".set-dup-item").forEach((itemEl)=>setDecision(itemEl,allSel.value))})
el.querySelector("#setIeImpBack").addEventListener("click",()=>setRenderImportPickStep(el,drop))
el.querySelector("#setIeImpCancel2").addEventListener("click",closeModal)
const applyBtn=el.querySelector("#setIeImpApply")
applyBtn.addEventListener("click",()=>{
if(applyBtn.dataset.done){closeModal();return}
const statusEl=el.querySelector("#setIeImpStatus")
statusEl.classList.remove("error")
statusEl.textContent="Applying..."
applyBtn.disabled=true
bridgeCall(`importExport.${cfg.applyFn}`,[res.path,fmt,decisions]).then((r)=>{
statusEl.textContent=setIeResultText(r||{})
statusEl.classList.toggle("error",!!(r&&r.bad))
applyBtn.textContent="Done"
applyBtn.dataset.done="1"
applyBtn.disabled=false
}).catch((err)=>{statusEl.textContent=err&&err.message?err.message:"Failed";statusEl.classList.add("error");applyBtn.disabled=false})
})
}
const SET_TPL_ENTITIES={
notes:{label:"Notes",formats:["json"]},
commands:{label:"Commands",formats:["json"]},
target_values:{label:"Target Values",formats:["json","csv"]},
targets:{label:"Targets",formats:["json","csv"]},
all:{label:"All (ZIP bundle)",formats:null},
}
const SET_TPL_FORMAT_LABELS={md:"Markdown",json:"JSON",csv:"CSV"}
function setTplEntityOptions(){
return Object.keys(SET_TPL_ENTITIES).map((k)=>`<option value="${k}">${setEscapeHtml(SET_TPL_ENTITIES[k].label)}</option>`).join("")
}
function setOpenTemplatesModal(){
const el=document.createElement("div")
el.className="set-ie-modal glass-panel"
el.innerHTML=`<div class="set-ie-modal-title">Templates</div><p class="set-info">Example files showing the exact format LOYA expects for each importable data type.</p><div class="set-ie-field"><label>Which template</label><select id="setTplWhat" class="set-select">${setTplEntityOptions()}</select></div><div class="set-ie-field" id="setTplFormatWrap"><label>Format</label><select id="setTplFormat" class="set-select"></select></div><div class="set-status" id="setTplStatus"></div><div class="set-ie-modal-actions"><button type="button" id="setTplCancel">Cancel</button><button type="button" class="set-ie-confirm" id="setTplConfirm">Export</button></div>`
openModal(el)
function refresh(){
const cfg=SET_TPL_ENTITIES[document.getElementById("setTplWhat").value]
const wrap=document.getElementById("setTplFormatWrap")
if(!cfg.formats){wrap.classList.add("hidden");return}
wrap.classList.remove("hidden")
document.getElementById("setTplFormat").innerHTML=cfg.formats.map((f)=>`<option value="${f}">${SET_TPL_FORMAT_LABELS[f]}</option>`).join("")
}
document.getElementById("setTplWhat").addEventListener("change",refresh)
refresh()
document.getElementById("setTplCancel").addEventListener("click",closeModal)
document.getElementById("setTplConfirm").addEventListener("click",()=>{
const what=document.getElementById("setTplWhat").value
const statusEl=document.getElementById("setTplStatus")
statusEl.classList.remove("error")
statusEl.textContent="Working..."
const call=what==="all"?bridgeCall("templates.export_human_bundle"):bridgeCall("templates.export_human",[what,document.getElementById("setTplFormat").value])
call.then((path)=>{statusEl.textContent=path?"Exported to "+path:"Cancelled."}).catch((err)=>{statusEl.textContent=err&&err.message?err.message:"Failed";statusEl.classList.add("error")})
})
}
function setOpenAiTemplatesModal(){
const el=document.createElement("div")
el.className="set-ie-modal glass-panel"
el.innerHTML=`<div class="set-ie-modal-title">AI Prompt Templates</div><p class="set-info">AI prompt templates explain LOYA NG's import structure for each data type. Give one to an AI along with your normal notes or data, then ask it to recreate the content in a LOYA-ready import format.</p><div class="set-ie-field"><label>Which AI template</label><select id="setAiTplWhat" class="set-select">${setTplEntityOptions()}</select></div><div class="set-status" id="setAiTplStatus"></div><div class="set-ie-modal-actions"><button type="button" id="setAiTplCancel">Cancel</button><button type="button" class="set-ie-confirm" id="setAiTplConfirm">Export</button></div>`
openModal(el)
document.getElementById("setAiTplCancel").addEventListener("click",closeModal)
document.getElementById("setAiTplConfirm").addEventListener("click",()=>{
const what=document.getElementById("setAiTplWhat").value
const statusEl=document.getElementById("setAiTplStatus")
statusEl.classList.remove("error")
statusEl.textContent="Working..."
const call=what==="all"?bridgeCall("templates.export_ai_bundle"):bridgeCall("templates.export_ai",[what])
call.then((path)=>{statusEl.textContent=path?"Exported to "+path:"Cancelled."}).catch((err)=>{statusEl.textContent=err&&err.message?err.message:"Failed";statusEl.classList.add("error")})
})
}
function setLoadUpdate(){
bridgeCall("update.status").then((st)=>{
document.getElementById("setUpCurVer").textContent=st.current_version
document.getElementById("setUpLatestVer").textContent=st.latest_version
document.getElementById("setUpLastChecked").textContent=st.last_checked
document.getElementById("setUpLastGood").textContent=st.last_good_version
document.getElementById("setUpRepo").textContent=st.source_repo
document.getElementById("setUpManifest").textContent=st.manifest_url
document.getElementById("setUpStatusText").textContent=st.status_text
document.getElementById("setUpSnapshots").textContent=`${st.snapshot_count} snapshot(s) in ${st.snapshot_dir}`
document.getElementById("setUpUpdateBtn").disabled=!st.can_update
const cfg=st.settings||{}
document.getElementById("setUpAutoToggle").checked=!!cfg.auto_enabled
document.getElementById("setUpFreq").value=String(cfg.check_interval_hours||24)
const ch=document.getElementById("setUpChannel")
if(ch){if(cfg.last_channel&&!Array.from(ch.options).some((o)=>o.value===cfg.last_channel))ch.add(new Option(cfg.last_channel,cfg.last_channel));ch.value=cfg.last_channel||"stable"}
const mode=document.getElementById("setUpOnAvailable")
if(mode)mode.value=cfg.on_available||"ask"
}).catch((err)=>console.error("update status failed",err))
}
function setSaveUpdateSettings(){
const cfg={auto_enabled:document.getElementById("setUpAutoToggle").checked,check_interval_hours:parseInt(document.getElementById("setUpFreq").value,10),last_channel:(document.getElementById("setUpChannel")||{}).value||"stable",on_available:(document.getElementById("setUpOnAvailable")||{}).value||"ask"}
bridgeCall("update.save_settings",[cfg]).then(()=>setStatus("setUpFooter","Update settings saved.",false)).catch((err)=>setStatus("setUpFooter",err&&err.message?err.message:"Failed",true))
}
function setDoUpdateCheck(){
setStatus("setUpFooter","Checking official release...",false)
bridgeCall("update.check_now").then((res)=>{
setStatus("setUpFooter",res.update_available?`New authenticated version available: ${res.status.latest_version}.`:"You are already on the latest authenticated version.",false)
setLoadUpdate()
}).catch((err)=>{
setStatus("setUpFooter",err&&err.message?err.message:"Update check failed",true)
setLoadUpdate()
})
}
function setDoUpdateNow(){
// Same flow as the launch notification: release notes, then download -> verify -> backup -> restart with progress.
if(typeof updateNoticeOpenFromSettings!=="function"){setStatus("setUpFooter","The update dialog is not available.",true);return}
updateNoticeOpenFromSettings().then((opened)=>{if(!opened)setStatus("setUpFooter","You are already on the latest authenticated version.",false)}).catch((err)=>setStatus("setUpFooter",err&&err.message?err.message:"Update start failed",true))
}
function setDoOpenLogs(){
bridgeCall("update.open_logs").then(()=>setStatus("setUpFooter","Opened update log.",false)).catch((err)=>setStatus("setUpFooter",err&&err.message?err.message:"Failed",true))
}
function setDoOpenSnapshots(){
bridgeCall("update.open_snapshots").then(()=>setStatus("setUpFooter","Opened code snapshots folder.",false)).catch((err)=>setStatus("setUpFooter",err&&err.message?err.message:"Failed",true))
}
function initSettings(){
return fetch("../pages/settings.html").then((r)=>r.text()).then((html)=>{
document.querySelector('.page[data-page="settings"]').innerHTML=html
document.querySelectorAll(".set-tab").forEach((t)=>t.addEventListener("click",()=>setSwitchTab(t.dataset.tab)))
document.querySelectorAll(".set-subtab[data-ai-tab]").forEach((b)=>b.addEventListener("click",()=>setSwitchAiTab(b.dataset.aiTab)))
document.querySelectorAll("[data-goto-ai]").forEach((b)=>b.addEventListener("click",()=>setSwitchTab("ai",b.dataset.gotoAi)))
document.getElementById("setPinBtn").addEventListener("click",setDoSetPin)
document.getElementById("setLockToggle").addEventListener("change",setDoToggleLock)
document.getElementById("setEncToggle").addEventListener("change",setDoToggleEnc)
document.getElementById("setAutoLockSelect").addEventListener("change",setDoChangeAutoLock)
document.getElementById("setAuditExpiryToggle").addEventListener("change",()=>{setSyncAuditExpiryInputs();setDoSaveAuditExpiry()})
document.getElementById("setAuditExpirySaveBtn").addEventListener("click",setDoSaveAuditExpiry)
document.getElementById("setAuditExpiryAmount").addEventListener("keydown",(e)=>{if(e.key==="Enter")setDoSaveAuditExpiry()})
document.getElementById("setAuditExpiryAmount").addEventListener("input",(e)=>{const v=e.target.value.replace(/[^0-9]/g,"").slice(0,3);if(v!==e.target.value)e.target.value=v})
document.getElementById("setBkAutoToggle").addEventListener("change",setSaveBackupSettings)
document.getElementById("setBkFreq").addEventListener("change",setSaveBackupSettings)
document.getElementById("setBkKeep").addEventListener("change",setSaveBackupSettings)
document.getElementById("setBkOffsiteBrowseBtn").addEventListener("click",setDoBrowseOffsiteDir)
document.getElementById("setBkOffsiteClearBtn").addEventListener("click",setDoClearOffsiteDir)
document.getElementById("setNotifyOsToggle").addEventListener("change",setSaveNotifySettings)
document.getElementById("setNotifyTestBtn").addEventListener("click",setDoTestNotify)
document.getElementById("setBkCreateBtn").addEventListener("click",setDoBackupNow)
document.getElementById("setBkRestoreBtn").addEventListener("click",setDoRestoreSelected)
document.getElementById("setBkDeleteBtn").addEventListener("click",setDoDeleteSelectedBackups)
document.getElementById("setTagSearch").addEventListener("input",(e)=>{setState.tagSearch=e.target.value;setRenderTags()})
document.getElementById("setTagRenameBtn").addEventListener("click",()=>setTagApply("rename"))
document.getElementById("setTagMergeBtn").addEventListener("click",()=>setTagApply("merge"))
document.getElementById("setTagDeleteBtn").addEventListener("click",()=>setTagApply("delete"))
document.getElementById("setTagRefreshBtn").addEventListener("click",()=>setRefreshTags().then(()=>setStatus("setTagStatus",setState.tags.length+" tag(s).",false)).catch((err)=>setStatus("setTagStatus",err&&err.message?err.message:"Failed",true)))
document.addEventListener("loya:page-shown",(e)=>{if(e.detail&&e.detail.page==="settings"&&!e.detail.first)setRefreshTabData(setState.tab)})
document.getElementById("setRbSearch").addEventListener("input",(e)=>{setState.rbSearch=e.target.value;setRenderRb()})
document.getElementById("setRbType").addEventListener("change",(e)=>{setState.rbType=e.target.value;setRefreshRb()})
document.getElementById("setRbRefreshBtn").addEventListener("click",setRefreshRb)
document.getElementById("setRbRetentionSaveBtn").addEventListener("click",setSaveRbRetention)
document.getElementById("setThemeModeSelect").addEventListener("change",setDoChangeThemeMode)
document.getElementById("setStyleSelect").addEventListener("change",setDoChangeStyle)
document.getElementById("setReplayTourBtn").addEventListener("click",()=>{startOnboardingTour()})
document.getElementById("setFocusModeToggle").addEventListener("change",setDoToggleFocusMode)
document.getElementById("setNoteSuggestTitle").addEventListener("change",(e)=>setDoToggleNoteSuggest("suggest_title",e.currentTarget))
document.getElementById("setNoteAutoPairs").addEventListener("change",(e)=>{const el=e.currentTarget;bridgeCall("notes.set_editor_pref",["auto_pairs_off",!el.checked]).then((p)=>{if(typeof notesApplyPrefs==="function")notesApplyPrefs(p)}).catch((err)=>{el.checked=!el.checked;showToast(err&&err.message?err.message:"Failed","error")})})
document.getElementById("setNoteSuggestTags").addEventListener("change",(e)=>setDoToggleNoteSuggest("suggest_tags",e.currentTarget))
document.getElementById("setRbRestoreBtn").addEventListener("click",setDoRestoreSelectedRb)
document.getElementById("setRbDeleteBtn").addEventListener("click",setDoDeleteSelectedRb)
document.getElementById("setRbRestoreAllBtn").addEventListener("click",setDoRestoreAllRb)
document.getElementById("setRbPurgeBtn").addEventListener("click",setDoPurgeNow)
document.getElementById("setIeOpenExportBtn").addEventListener("click",setOpenExportModal)
document.getElementById("setIeOpenImportBtn").addEventListener("click",setOpenImportModal)
setIeWireDropZone()
document.getElementById("setIeOpenReportBtn").addEventListener("click",setOpenReportModal)
document.getElementById("setIeOpenStatsBtn").addEventListener("click",setOpenStatsModal)
setIeWireReports()
document.getElementById("setIeOpenTplBtn").addEventListener("click",setOpenTemplatesModal)
document.getElementById("setIeOpenAiTplBtn").addEventListener("click",setOpenAiTemplatesModal)
document.getElementById("setUpAutoToggle").addEventListener("change",setSaveUpdateSettings)
document.getElementById("setUpFreq").addEventListener("change",setSaveUpdateSettings)
document.getElementById("setUpChannel").addEventListener("change",setSaveUpdateSettings)
document.getElementById("setUpCheckBtn").addEventListener("click",setDoUpdateCheck)
document.getElementById("setUpUpdateBtn").addEventListener("click",setDoUpdateNow)
document.getElementById("setUpOnAvailable").addEventListener("change",setSaveUpdateSettings)
document.getElementById("setUpReleaseLink").addEventListener("click",(e)=>{e.preventDefault();bridgeCall("update.open_release_page").catch((err)=>setStatus("setUpFooter",err&&err.message?err.message:"Failed",true))})
document.getElementById("setUpLogsBtn").addEventListener("click",setDoOpenLogs)
document.getElementById("setUpSnapsBtn").addEventListener("click",setDoOpenSnapshots)
document.getElementById("setUpCloseNowBtn").addEventListener("click",()=>bridgeCall("window.close"))
document.getElementById("setTermToggle").addEventListener("change",setDoToggleTerminal)
if(typeof flowSettingsMount==="function")flowSettingsMount(document.getElementById("setFlowBox"))
document.getElementById("setProfileSaveBtn").addEventListener("click",setDoSaveProfile)
document.getElementById("setProfileResetBtn").addEventListener("click",setResetProfileForm)
document.getElementById("setProfileList").addEventListener("click",(e)=>{
const row=e.target.closest(".set-profile-row")
if(!row)return
const profile=setProfileCache.find((p)=>p.id===row.dataset.id)
if(!profile)return
if(e.target.closest(".set-profile-del")){
bridgeCall("terminal.profile_delete",[profile.id]).then((profiles)=>{setProfileCache=profiles;setRenderProfiles(profiles);setStatus("setProfileStatus","Profile deleted.",false);termRefreshProfiles()}).catch(()=>{})
return
}
if(e.target.closest(".set-profile-edit")){
document.getElementById("setProfileId").value=profile.id
document.getElementById("setProfileName").value=profile.name
document.getElementById("setProfileShell").value=profile.shell_id||""
document.getElementById("setProfileCwd").value=profile.cwd||""
document.getElementById("setProfileStartup").value=profile.startup||""
document.getElementById("setProfileEnv").value=setFormatEnv(profile.env)
}
})
Object.keys(SET_RUN_BEHAVIOUR_FIELDS).forEach((id)=>document.getElementById(id).addEventListener("change",setDoSaveRunBehaviour))
document.getElementById("setTermPasteConfirm").addEventListener("change",setDoSaveRunBehaviour)
document.getElementById("setTermFullDefault").addEventListener("change",setDoSaveRunBehaviour)
document.getElementById("setTermConpty").addEventListener("change",setDoSaveRunBehaviour)
document.getElementById("setTermSuggest").addEventListener("change",(e)=>termSetSuggestEnabled(e.target.checked,false).then((s)=>setStatus("setTermShortcutStatus",s?"Saved.":"Failed",!s)))
const setShortcutWrap=document.getElementById("setTermShortcuts")
setShortcutWrap.addEventListener("keydown",setHandleShortcutKeydown)
setShortcutWrap.addEventListener("focusin",(e)=>{const input=e.target.closest(".set-shortcut-input");if(input){input.classList.add("recording");input.value="Press keys..."}})
setShortcutWrap.addEventListener("focusout",(e)=>{const input=e.target.closest(".set-shortcut-input");if(input){input.classList.remove("recording");if(input.value==="Press keys...")input.value=input.dataset.combo||"Not set"}})
setShortcutWrap.addEventListener("click",(e)=>{const btn=e.target.closest(".set-shortcut-reset");if(btn)setSaveTerminalShortcut(btn.dataset.action,null)})
document.getElementById("setAiToggle").addEventListener("change",setDoToggleAi)
document.getElementById("setAiDetectBtn").addEventListener("click",setDoDetectAiProviders)
document.querySelectorAll(".ai-provider-enable").forEach((el)=>{
el.addEventListener("change",()=>setDoToggleAiProvider(el.dataset.provider,el.checked))
})
document.querySelectorAll(".ai-field").forEach((el)=>{
const evt=el.tagName==="SELECT"?"change":"blur"
el.addEventListener(evt,()=>{
if(el.dataset.field==="api_key"&&!el.value)return
setSaveAiField(el.dataset.provider,el.dataset.field,el.value)
})
})
document.querySelectorAll(".ai-test-btn").forEach((el)=>{
el.addEventListener("click",()=>setDoTestAiProvider(el.dataset.provider))
})
document.getElementById("aiOllamaPullBtn").addEventListener("click",setDoPullOllamaModel)
setLoadOllamaSuggestions()
document.getElementById("setMcpLocalStartBtn").addEventListener("click",setDoStartMcpLocal)
document.getElementById("setMcpLocalStopBtn").addEventListener("click",setDoStopMcpLocal)
setRefreshMcpLocalStatus()
document.getElementById("setSemanticRebuildBtn").addEventListener("click",setDoRebuildSemanticIndex)
setLoadSemanticStatus()
const setApiProviderKindSelect=document.querySelector('.ai-field[data-provider="api"][data-field="provider_kind"]')
if(setApiProviderKindSelect){
setApiProviderKindSelect.addEventListener("change",()=>{
bridgeCall("ai.list_models",["api"]).then((models)=>setPopulateAiModelSelect("api",models)).catch(()=>{})
})
}
document.querySelectorAll(".ai-default-btn").forEach((el)=>{
el.addEventListener("click",()=>setDoToggleAiDefault(el.dataset.provider))
})
document.getElementById("setAiTerminalApproval").addEventListener("change",(e)=>{
bridgeCall("ai.set_terminal_approval_mode",[e.target.value]).then((mode)=>{
setApplyTerminalApproval(mode)
setStatus("setAiRolesStatus",mode==="allow"?"The AI can now run non-destructive commands without asking.":"The AI must ask before every command.",mode==="allow")
}).catch((err)=>setStatus("setAiRolesStatus",err&&err.message?err.message:"Failed",true))
})
setLoadExtensions()
setLoadAiProviders()
setLoadAiRoles()
if(typeof extAgentsMountSettings==="function")extAgentsMountSettings(document.getElementById("setExtAgentsRoot"))
if(typeof cveMountSettings==="function")cveMountSettings(document.getElementById("setCveRoot"))
if(typeof tshMountSettings==="function")tshMountSettings(document.getElementById("setTermShellsRoot"))
setLoadAppearance()
setLoadSecurity()
setLoadBackupSettings()
setLoadNotifySettings()
setLoadUpdate()
return Promise.all([setRefreshBackups(),setRefreshTags(),setRefreshRb(),setRefreshRbRetention()])
}).catch((err)=>console.error("settings init failed",err))
}
