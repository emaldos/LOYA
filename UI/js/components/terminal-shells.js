// Settings > Extensions: "Terminal Shells" (default shell, PowerShell on Linux) and, on Windows, "Kali Linux on WSL".
// The backend (terminal.* / wsl.*) validates, backs up, audit-logs and refuses while locked; this file only shows state, asks first and
// shows exactly what will run (wsl.describe) before anything runs. Nothing here starts on its own.
// Loaded by the app as a plain script and by tests/js/terminal_shells.js through require() (pure helpers and the timer / popover).
const TSH_NOTES_MS=100000
const TSH_MODES=["nat","mirrored","bridged","custom"]
const TSH_STEPS=[["prereq","Check WSL"],["install","Install Kali"],["user","Create your user"],["network","Choose the network"],["verify","Check it works"]]
const TSH_NOTES_LABEL="WSL network notes"
let tshState={root:null,token:0,status:null,shells:[],settings:null,extras:null,notesTimer:null,notesShown:false,popover:null,job:null,jobLog:[],busy:false,form:{}}
function tshEsc(s){
return String(s===undefined||s===null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")
}
// ---- pure helpers
function tshDefaultShellOptions(shells,choice,platform){
const auto=platform==="windows"?"Automatic (PowerShell 7 if installed, otherwise Windows PowerShell)":"Automatic (your login shell)"
const opts=[{value:"auto",label:auto}].concat((shells||[]).map((s)=>({value:s.id,label:s.label})))
const has=opts.some((o)=>o.value===choice)
if(choice&&!has)opts.push({value:choice,label:choice+" (not installed now)",missing:true})
return opts.map((o)=>({value:o.value,label:o.label,selected:o.value===(choice||"auto"),missing:!!o.missing}))
}
function tshModeOptions(availability,selected,labels){
availability=availability||{}
return TSH_MODES.map((m)=>{
const a=availability[m]||{available:m==="nat",reason:""}
return {value:m,label:(labels&&labels[m])||m,available:!!a.available,reason:a.reason||"",warning:a.warning||"",selected:m===selected}
})
}
function tshUnavailableReasons(availability,labels){
return tshModeOptions(availability,"",labels).filter((o)=>!o.available&&o.reason).map((o)=>({mode:o.value,label:o.label,reason:o.reason}))
}
// Which fields a mode needs.
function tshModeFields(mode){
if(mode==="custom")return ["switch","mac","ip","prefix","gateway","dns"]
if(mode==="bridged")return ["switch","mac"]
return []
}
function tshCollectNetwork(mode,values){
const out={mode:TSH_MODES.indexOf(mode)>=0?mode:"nat"}
tshModeFields(out.mode).forEach((f)=>{out[f]=String((values&&values[f])===undefined||(values&&values[f])===null?"":values[f]).trim()})
return out
}
function tshStepIndex(step){
if(step==="reboot")return 0
const i=TSH_STEPS.findIndex((s)=>s[0]===step)
return step==="done"?TSH_STEPS.length:i
}
function tshStepsHtml(step){
const at=tshStepIndex(step)
return '<ol class="tsh-steps">'+TSH_STEPS.map((s,i)=>'<li class="tsh-step'+(i<at?" done":i===at?" current":"")+'"'+(i===at?' aria-current="step"':"")+'><span class="tsh-step-n">'+(i+1)+'</span><span>'+tshEsc(s[1])+"</span></li>").join("")+"</ol>"
}
function tshNotesListHtml(notes){
return '<ul class="tsh-notes-list">'+(notes||[]).map((n)=>"<li>"+tshEsc(n)+"</li>").join("")+"</ul>"
}
function tshNotesButtonHtml(){
return '<button type="button" class="tsh-notes-btn" id="tshNotesBtn" aria-label="'+TSH_NOTES_LABEL+'" title="'+TSH_NOTES_LABEL+'" aria-haspopup="dialog" aria-expanded="false" aria-controls="tshNotesPopover">!</button>'
}
function tshInlineNotesHtml(notes,remainingMs,totalMs){
const pct=Math.max(0,Math.min(100,totalMs?remainingMs/totalMs*100:0))
return '<div class="tsh-notes-inline" id="tshNotesInline" role="note"><div class="tsh-notes-inline-head"><span class="tsh-notes-inline-title">'+TSH_NOTES_LABEL+'</span><span class="tsh-notes-count" id="tshNotesCount">Hides in '+Math.ceil(remainingMs/1000)+' s</span><button type="button" class="tsh-notes-x" id="tshNotesClose" aria-label="Close the WSL network notes">×</button></div>'+tshNotesListHtml(notes)+'<div class="tsh-notes-bar"><span id="tshNotesBar" style="width:'+pct.toFixed(1)+'%"></span></div></div>'
}
// A countdown that the tests drive with a fake clock. onTick(remainingMs), onDone(reason) with reason "timeout" or "closed".
function tshCreateNotesTimer(totalMs,hooks){
hooks=hooks||{}
const now=hooks.now||(()=>Date.now())
const setI=hooks.setInterval||((fn,ms)=>setInterval(fn,ms))
const clearI=hooks.clearInterval||((id)=>clearInterval(id))
let started=0,handle=null,finished=false
const timer={
start(){started=now();finished=false;if(hooks.onTick)hooks.onTick(totalMs);handle=setI(()=>timer.tick(),1000);return timer},
remaining(){return finished?0:Math.max(0,totalMs-(now()-started))},
tick(){if(finished)return;const left=timer.remaining();if(hooks.onTick)hooks.onTick(left);if(left<=0)timer.finish("timeout")},
finish(reason){if(finished)return;finished=true;if(handle!==null)clearI(handle);handle=null;if(hooks.onDone)hooks.onDone(reason||"closed")},
stop(){timer.finish("closed")},
get done(){return finished}
}
return timer
}
function tshVerifyHtml(v){
if(!v)return ""
if(!v.started)return '<div class="set-status error">Kali did not start.</div>'
const ips=(v.addresses||[]).map((a)=>a.ip+"/"+a.prefix+" ("+a.interface+")").join(", ")||"no IPv4 address yet"
const row=(label,ok,text)=>'<div class="tsh-check '+(ok?"ok":"bad")+'"><span class="tsh-check-dot"></span><span>'+tshEsc(label)+'</span><span class="tsh-dim">'+tshEsc(text)+"</span></div>"
return '<div class="tsh-verify">'+row("Kali IP",(v.addresses||[]).length>0,ips)+row("Gateway ping",v.gateway_ok,v.gateway?v.gateway+(v.gateway_ok?" answers":" does not answer"):"no default gateway")+row("DNS lookup",v.dns_ok,v.dns_ok?v.dns_answer:"kali.org did not resolve")+"</div>"
}
function tshStatusRowsHtml(st){
const win=st.windows||{},wsl=st.wsl||{},labels=st.mode_labels||{}
const mode=st.network_mode||"nat"
const rows=[["Windows",(win.name||"Windows")+(win.build?" (build "+win.build+(win.ubr?"."+win.ubr:"")+")":"")],["WSL",wsl.ok?"Ready"+(wsl.version?" · version "+wsl.version:""):(wsl.present?"Not set up yet":"Not installed")],["Kali Linux",st.kali_installed?"Installed (kali-linux)":"Not installed"],["Network mode",(labels[mode]||mode)+(st.wslconfig&&st.wslconfig.exists?"":" (no .wslconfig yet)")],["Kali IP",(st.addresses||[]).length?(st.addresses||[]).map((a)=>a.ip+"/"+a.prefix).join(", "):"—"]]
return '<div class="tsh-status">'+rows.map((r)=>'<div class="tsh-status-row"><span class="tsh-dim">'+tshEsc(r[0])+"</span><span>"+tshEsc(r[1])+"</span></div>").join("")+"</div>"
}
function tshNetworkFormHtml(st,mode,values){
values=values||{}
const opts=tshModeOptions(st.availability,mode,st.mode_labels)
const sel='<select id="tshMode" class="set-select" aria-label="Network mode">'+opts.map((o)=>'<option value="'+o.value+'"'+(o.selected?" selected":"")+(o.available?"":" disabled")+">"+tshEsc(o.label)+(o.available?"":" (won't work here)")+"</option>").join("")+"</select>"
const fields=tshModeFields(mode)
const switches=(st.hyperv&&st.hyperv.switches)||[]
const input=(id,label,ph,val)=>'<label class="tsh-field"><span>'+label+'</span><input type="text" class="set-input" id="tshNet_'+id+'" data-field="'+id+'" placeholder="'+tshEsc(ph)+'" value="'+tshEsc(val||"")+'" autocomplete="off" spellcheck="false"></label>'
let html=""
if(fields.indexOf("switch")>=0)html+='<label class="tsh-field"><span>External virtual switch</span><select class="set-select" id="tshNet_switch" data-field="switch">'+switches.map((n)=>'<option value="'+tshEsc(n)+'"'+(values.switch===n?" selected":"")+">"+tshEsc(n)+"</option>").join("")+"</select></label>"
if(fields.indexOf("ip")>=0)html+=input("ip","IP address","192.168.1.50",values.ip)+input("prefix","Subnet mask or prefix","255.255.255.0 or 24",values.prefix)+input("gateway","Gateway","192.168.1.1",values.gateway)+input("dns","DNS servers","1.1.1.1, 9.9.9.9",values.dns)
if(fields.indexOf("mac")>=0)html+=input("mac","MAC address (optional)","00:15:5d:12:34:56",values.mac)
const current=opts.find((o)=>o.value===mode)
const reasons=tshUnavailableReasons(st.availability,st.mode_labels)
return '<div class="set-row tsh-mode-row"><span>Network mode</span>'+sel+'<button type="button" class="set-btn primary" id="tshApply">'+(st.state&&st.state.configured?"Update":"Apply")+"</button>"+tshNotesButtonHtml()+"</div>"+
(current&&current.warning?'<p class="set-info tsh-warn">'+tshEsc(current.warning)+"</p>":"")+
(html?'<div class="tsh-fields">'+html+"</div>":"")+
(reasons.length?'<div class="tsh-reasons"><div class="tsh-dim">Options that won\'t work on this computer</div>'+reasons.map((r)=>'<p class="tsh-reason"><b>'+tshEsc(r.label)+":</b> "+tshEsc(r.reason)+"</p>").join("")+(opts.some((o)=>(st.availability[o.value]||{}).needs_lookup)?'<button type="button" class="set-btn" id="tshLookup">Look up switches (administrator, read-only)</button>':"")+"</div>":"")
}
function tshWizardHtml(st){
const step=st.step
let body=""
if(step==="prereq"){
const ok=st.wsl&&st.wsl.ok
body='<p class="set-info">'+(ok?"WSL is ready.":"WSL is not set up on this computer yet. LOYA can run <code>wsl.exe --install --no-distribution</code> as administrator (one UAC prompt). Windows may need a restart afterwards; this setup continues after the restart.")+'</p><div class="set-row">'+(ok?"":'<button type="button" class="set-btn primary" id="tshFeature">Install WSL (administrator)</button>')+'<button type="button" class="set-btn" id="tshRefresh">Check again</button></div>'
}else if(step==="reboot"){
body='<p class="set-info">Restart Windows to finish installing WSL. When you open LOYA again this setup continues from here.</p><div class="set-row"><button type="button" class="set-btn" id="tshRefresh">Check again</button></div>'
}else if(step==="install"){
body='<p class="set-info">Installs the kali-linux distro in a LOYA terminal session. When Kali starts for the first time it asks you for a new username and password there.</p><div class="set-row"><label class="set-check"><input type="checkbox" id="tshWebDownload"'+(tshState.form.web_download?" checked":"")+'><span>Download directly instead of through the Microsoft Store (--web-download)</span></label></div><div class="set-row"><button type="button" class="set-btn primary" id="tshInstall">Install Kali Linux</button><button type="button" class="set-btn" id="tshRefresh">Check again</button></div>'
}else if(step==="user"){
body='<p class="set-info">Kali needs your own user (it is still logging in as root). Start Kali in a terminal session and answer its first-run questions, or create the user here.</p><div class="set-row"><button type="button" class="set-btn primary" id="tshFirstRun">Open Kali first run</button><button type="button" class="set-btn" id="tshRefresh">Check again</button></div><div class="set-row"><input type="text" class="set-input" id="tshUser" placeholder="new username, e.g. kali" maxlength="32" autocomplete="off" spellcheck="false" value="'+tshEsc(tshState.form.username||"")+'"><button type="button" class="set-btn" id="tshAddUser">Create user</button><button type="button" class="set-btn" id="tshDefaultUser">Make it the default user</button></div>'
}else if(step==="network"){
body='<p class="set-info">How Kali shows up on your network. You can change this later with the Update button.</p>'+tshNetworkFormHtml(st,tshState.form.mode||"nat",tshState.form)
}else if(step==="verify"){
body='<p class="set-info">Kali started with the new network settings. Check the result, then finish.</p>'+tshVerifyHtml(st.state&&st.state.last_verify)+'<div class="set-row"><button type="button" class="set-btn" id="tshVerify">Check network</button><button type="button" class="set-btn primary" id="tshFinish">Finish setup</button></div>'
}
return tshStepsHtml(step)+'<div class="tsh-step-body">'+body+'</div><div class="set-row"><button type="button" class="set-btn" id="tshCancelWizard">Cancel setup</button></div>'
}
function tshKaliHtml(st){
const state=st.state||{}
let html='<div class="set-box glass-panel tsh-box" id="tshKaliBox"><div class="set-box-title">Kali Linux on WSL</div><p class="set-info">Run Kali Linux inside Windows (WSL) and open it as a terminal session. Setup is step by step and only runs when you start it. LOYA changes WSL settings only; it never changes this computer\'s network adapters or creates virtual switches.</p>'
html+='<div class="set-row"><label class="set-check"><input type="checkbox" id="tshKaliEnable"'+(state.enabled?" checked":"")+'><span>Use Kali Linux on WSL</span></label></div>'
if(state.enabled){
html+=tshStatusRowsHtml(st)
if(state.configured){
html+=tshNetworkFormHtml(st,tshState.form.mode||(state.network&&state.network.mode)||"nat",tshState.form)
html+='<div class="tsh-notes-slot" id="tshNotesSlot"></div>'
html+='<div class="set-row tsh-actions"><button type="button" class="set-btn" id="tshOpenKali">Open Kali session</button><button type="button" class="set-btn" id="tshVerify">Check network</button><button type="button" class="set-btn" id="tshRestart">Restart WSL</button><button type="button" class="set-btn" id="tshRollback"'+(state.wslconfig_backup?"":" disabled")+'>Restore previous .wslconfig</button><button type="button" class="set-btn" id="tshRefresh">Refresh</button><button type="button" class="set-btn danger" id="tshRemove">Remove Kali setup</button></div>'
html+=tshVerifyHtml(state.last_verify)
}else if(st.step==="idle"){
html+='<div class="set-row"><button type="button" class="set-btn primary" id="tshStart">Set up Kali Linux on WSL</button>'+tshNotesButtonHtml()+'<button type="button" class="set-btn" id="tshRefresh">Refresh</button></div><div class="tsh-notes-slot" id="tshNotesSlot"></div>'
}else{
html+='<div class="tsh-notes-slot" id="tshNotesSlot"></div>'+tshWizardHtml(st)
}
html+='<pre class="term-run-preview tsh-log'+(tshState.jobLog.length?"":" hidden")+'" id="tshLog">'+tshEsc(tshState.jobLog.join("\n"))+"</pre>"
}
html+='<div class="set-status" id="tshKaliStatus"></div></div>'
return html
}
function tshShellsHtml(shells,settings,extras){
const opts=tshDefaultShellOptions(shells,settings.default_shell_choice,settings.platform)
let html='<div class="set-box glass-panel tsh-box" id="tshShellsBox"><div class="set-box-title">Terminal Shells</div><p class="set-info">The shell a new terminal session starts with. Right-click the + button in the terminal to pick another one for a single session.</p>'
html+='<div class="set-row"><label class="set-label" for="tshDefaultShell">Default shell for new sessions</label><select id="tshDefaultShell" class="set-select">'+opts.map((o)=>'<option value="'+tshEsc(o.value)+'"'+(o.selected?" selected":"")+">"+tshEsc(o.label)+"</option>").join("")+"</select></div>"
const pwsh=extras&&extras.pwsh
if(settings.platform==="linux"&&pwsh){
html+='<div class="set-row"><span>PowerShell (pwsh)</span>'+(pwsh.installed?'<span class="tsh-pill ok">Installed · '+tshEsc(pwsh.path)+"</span>":(pwsh.installable?'<button type="button" class="set-btn" id="tshPwshInstall">Install PowerShell…</button>':'<span class="tsh-pill">'+tshEsc(pwsh.reason||"Not installed")+"</span>"))+"</div>"
}
html+='<div class="set-status" id="tshShellStatus"></div></div>'
return html
}
function tshDescribeHtml(plan){
return '<pre class="term-run-preview">'+tshEsc((plan.commands||[]).join("\n"))+"</pre>"+(plan.elevated?'<p class="tsh-confirm-note"><b>Needs administrator approval (UAC).</b></p>':"")+((plan.notes||[]).length?tshNotesListHtml(plan.notes):"")
}
// ---- DOM: notes popover and inline countdown
function tshCloseNotesPopover(focusButton){
const pop=tshState.popover
if(!pop)return
pop.remove()
tshState.popover=null
document.removeEventListener("keydown",tshPopoverKey,true)
document.removeEventListener("mousedown",tshPopoverOutside,true)
const btn=document.getElementById("tshNotesBtn")
if(btn){btn.setAttribute("aria-expanded","false");if(focusButton)btn.focus()}
}
function tshPopoverKey(e){if(e.key==="Escape"){e.preventDefault();e.stopPropagation();tshCloseNotesPopover(true)}}
function tshPopoverOutside(e){const pop=tshState.popover;if(pop&&!pop.contains(e.target)&&!(e.target.closest&&e.target.closest("#tshNotesBtn")))tshCloseNotesPopover(false)}
function tshOpenNotesPopover(btn,notes){
if(tshState.popover){tshCloseNotesPopover(true);return}
const pop=document.createElement("div")
pop.className="tsh-notes-popover"
pop.id="tshNotesPopover"
pop.setAttribute("role","dialog")
pop.setAttribute("aria-label",TSH_NOTES_LABEL)
pop.tabIndex=-1
pop.innerHTML='<div class="tsh-notes-inline-head"><span class="tsh-notes-inline-title">'+TSH_NOTES_LABEL+'</span><button type="button" class="tsh-notes-x" aria-label="Close the WSL network notes">×</button></div>'+tshNotesListHtml(notes)
document.body.appendChild(pop)
const r=btn.getBoundingClientRect()
const w=Math.min(340,window.innerWidth-16)
pop.style.width=w+"px"
pop.style.left=Math.round(Math.max(8,Math.min(r.left,window.innerWidth-w-8)))+"px"
const h=pop.offsetHeight||140
pop.style.top=Math.round(r.bottom+8+h>window.innerHeight?Math.max(8,r.top-h-8):r.bottom+8)+"px"
pop.querySelector(".tsh-notes-x").addEventListener("click",()=>tshCloseNotesPopover(true))
tshState.popover=pop
btn.setAttribute("aria-expanded","true")
document.addEventListener("keydown",tshPopoverKey,true)
document.addEventListener("mousedown",tshPopoverOutside,true)
pop.focus()
}
function tshNotes(){return (tshState.status&&tshState.status.notes)||[]}
// leftMs: what is left of the 100 seconds (a re-render of the card keeps the countdown where it was).
function tshShowInlineNotes(leftMs){
const slot=document.getElementById("tshNotesSlot")
if(!slot)return
if(tshState.notesTimer)tshState.notesTimer.finish("closed")
const total=typeof leftMs==="number"&&leftMs>0?Math.min(leftMs,TSH_NOTES_MS):TSH_NOTES_MS
slot.innerHTML=tshInlineNotesHtml(tshNotes(),total,TSH_NOTES_MS)
const close=()=>{slot.innerHTML=""}
tshState.notesTimer=tshCreateNotesTimer(total,{
onTick:(left)=>{const c=document.getElementById("tshNotesCount");const b=document.getElementById("tshNotesBar");if(c)c.textContent="Hides in "+Math.ceil(left/1000)+" s";if(b)b.style.width=(left/TSH_NOTES_MS*100).toFixed(1)+"%"},
onDone:()=>{close();tshState.notesTimer=null}
}).start()
slot.querySelector("#tshNotesClose").addEventListener("click",()=>{if(tshState.notesTimer)tshState.notesTimer.stop();else close();const b=document.getElementById("tshNotesBtn");if(b)b.focus()})
}
// ---- DOM: actions
function tshSetStatus(id,msg,isError){const el=document.getElementById(id);if(!el)return;el.textContent=msg||"";el.classList.toggle("error",!!isError)}
function tshError(err){tshSetStatus("tshKaliStatus",err&&err.message?err.message:String(err||"Failed"),true)}
function tshReadForm(){
const modeEl=document.getElementById("tshMode")
if(modeEl)tshState.form.mode=modeEl.value
document.querySelectorAll("#tshKaliBox [data-field]").forEach((el)=>{tshState.form[el.dataset.field]=el.value})
const wd=document.getElementById("tshWebDownload");if(wd)tshState.form.web_download=wd.checked
const user=document.getElementById("tshUser");if(user)tshState.form.username=user.value.trim()
return tshState.form
}
function tshConfirmPlan(action,params,okLabel,danger){
return bridgeCall("wsl.describe",[action,params||{}]).then((plan)=>appConfirm(plan.title,{wide:true,okLabel:okLabel||"Run",danger:!!danger,bodyHtml:'<p class="tsh-confirm-note">This is exactly what will run:</p>'+tshDescribeHtml(plan)}))
}
function tshPollJob(jobId){
return new Promise((resolve,reject)=>{
const tick=()=>bridgeCall("wsl.job_status",[jobId]).then((job)=>{
tshState.jobLog=job.log||[]
const log=document.getElementById("tshLog");if(log){log.textContent=tshState.jobLog.join("\n");log.classList.toggle("hidden",!tshState.jobLog.length)}
if(job.state==="running"){setTimeout(tick,1000);return}
if(job.state==="done")resolve(job.result);else reject(new Error(job.error||"Failed"))
}).catch(reject)
tick()
})
}
function tshAfterShellsChange(){if(typeof termReloadShells==="function")termReloadShells().catch(()=>{})}
function tshRun(promise,okMsg){
tshState.busy=true
tshSetStatus("tshKaliStatus","Working…")
return Promise.resolve(promise).then((res)=>{tshState.busy=false;return tshLoad(false).then(()=>{if(okMsg)tshSetStatus("tshKaliStatus",typeof okMsg==="function"?okMsg(res):okMsg);return res})}).catch((err)=>{tshState.busy=false;return tshLoad(false).then(()=>tshError(err))})
}
function tshClosedMsg(res){const n=res&&res.closed?res.closed.length:0;return n?" "+n+" WSL terminal session"+(n===1?" was":"s were")+" closed; reopen them from the + menu.":""}
function tshTask(task,params,label){
if(typeof termOpenTaskSession!=="function")return Promise.reject(new Error("The terminal is not available."))
return termOpenTaskSession(task,params,()=>{tshAfterShellsChange();if(typeof bridgeCall==="function")bridgeCall("wsl.refresh_shells").catch(()=>{}).then(()=>tshLoad(false))}).then(()=>tshSetStatus("tshKaliStatus",label+" is running in the terminal panel. Press Check again when it has finished."))
}
function tshWire(root){
const on=(id,fn)=>{const el=root.querySelector("#"+id);if(el)el.addEventListener("click",fn)}
const def=root.querySelector("#tshDefaultShell")
if(def)def.addEventListener("change",()=>bridgeCall("terminal.set_default_shell",[def.value]).then((s)=>{tshState.settings=s;tshAfterShellsChange();tshSetStatus("tshShellStatus","New sessions now start with "+def.options[def.selectedIndex].text+".")}).catch((err)=>tshSetStatus("tshShellStatus",err&&err.message?err.message:"Failed",true)))
on("tshPwshInstall",()=>{if(typeof termInstallPowershell==="function")termInstallPowershell().then(()=>tshLoad(false))})
const enable=root.querySelector("#tshKaliEnable")
if(enable)enable.addEventListener("change",()=>{
if(!enable.checked){bridgeCall("wsl.set_enabled",[false,false]).then(()=>{tshAfterShellsChange();return tshLoad(false)}).catch(tshError);return}
appConfirm("Before you turn on Kali Linux on WSL",{wide:true,okLabel:"I understand, turn it on",bodyHtml:tshNotesListHtml(tshNotes())}).then((ok)=>{
if(!ok){enable.checked=false;return}
return bridgeCall("wsl.set_enabled",[true,true]).then(()=>{tshState.notesShown=true;return tshLoad(false)})
}).catch(tshError)
})
const notesBtn=root.querySelector("#tshNotesBtn")
if(notesBtn)notesBtn.addEventListener("click",()=>tshOpenNotesPopover(notesBtn,tshNotes()))
const mode=root.querySelector("#tshMode")
if(mode)mode.addEventListener("change",()=>{tshReadForm();tshRender()})
on("tshRefresh",()=>tshRun(bridgeCall("wsl.refresh_shells").then(tshAfterShellsChange)))
on("tshStart",()=>tshRun(bridgeCall("wsl.wizard_start")))
on("tshCancelWizard",()=>appConfirm("Cancel the Kali setup? Nothing already installed is removed.",{okLabel:"Cancel setup",cancelLabel:"Keep going"}).then((ok)=>ok&&tshRun(bridgeCall("wsl.wizard_cancel"))))
on("tshFeature",()=>tshConfirmPlan("feature",{},"Install WSL").then((ok)=>ok&&tshRun(bridgeCall("wsl.enable_feature").then((r)=>tshPollJob(r.job_id)),(res)=>res&&res.reboot_required?"Restart Windows to finish. LOYA continues this setup after the restart.":"WSL is ready.")))
on("tshInstall",()=>{tshReadForm();const p={web_download:!!tshState.form.web_download};tshConfirmPlan("install",p,"Install").then((ok)=>ok&&tshTask("wsl_install_kali",p,"The Kali install")).catch(tshError)})
on("tshFirstRun",()=>tshConfirmPlan("first_run",{},"Open").then((ok)=>ok&&tshTask("wsl_kali_first_run",{},"Kali's first run")).catch(tshError))
on("tshAddUser",()=>{tshReadForm();const p={username:tshState.form.username};tshConfirmPlan("adduser",p,"Create user").then((ok)=>ok&&tshTask("wsl_kali_adduser",p,"Creating the user")).catch(tshError)})
on("tshDefaultUser",()=>{tshReadForm();const p={username:tshState.form.username};tshConfirmPlan("default_user",p,"Make default").then((ok)=>ok&&tshRun(bridgeCall("wsl.set_default_user",[p.username]),(r)=>"Default user set."+tshClosedMsg(r))).catch(tshError)})
on("tshApply",()=>{
const values=tshCollectNetwork(tshReadForm().mode,tshState.form)
bridgeCall("wsl.validate_network",[values]).then(()=>tshConfirmPlan("network",values,"Apply and restart WSL",true)).then((ok)=>{
if(!ok)return
return tshRun(bridgeCall("wsl.apply_network",[values,true]).then((r)=>tshPollJob(r.job_id)).then((res)=>{tshAfterShellsChange();return res}),(res)=>"Applied. "+((res&&res.verify&&res.verify.addresses||[]).map((a)=>a.ip).join(", ")||"No IPv4 address yet.")+tshClosedMsg(res))
}).catch(tshError)
})
on("tshLookup",()=>tshRun(bridgeCall("wsl.lookup_switches"),(names)=>names&&names.length?"Found: "+names.join(", "):"No external virtual switch exists."))
on("tshVerify",()=>tshRun(bridgeCall("wsl.verify"),(v)=>v&&v.started?"Checked.":"Kali did not start."))
on("tshFinish",()=>tshRun(bridgeCall("wsl.wizard_finish").then(tshAfterShellsChange),"Kali Linux on WSL is set up. It is in the terminal's + menu as Kali Linux (WSL)."))
on("tshOpenKali",()=>{if(typeof termOpenShellSession!=="function")return;(typeof termReloadShells==="function"?termReloadShells():Promise.resolve()).then(()=>termOpenShellSession("wsl:kali-linux")).catch(tshError)})
on("tshRestart",()=>tshConfirmPlan("restart",{},"Restart WSL",true).then((ok)=>ok&&tshRun(bridgeCall("wsl.restart"),(r)=>"WSL restarted."+tshClosedMsg(r))).catch(tshError))
on("tshRollback",()=>appConfirm("Put the previous .wslconfig back and restart WSL?",{danger:true,okLabel:"Restore and restart",bodyHtml:tshNotesListHtml([tshNotes()[1]||""])}).then((ok)=>ok&&tshRun(bridgeCall("wsl.rollback"),(r)=>"Restored."+tshClosedMsg(r))))
on("tshRemove",()=>tshConfirmRemove())
}
function tshConfirmRemove(){
let unregister=false,typed=""
const opened=bridgeCall("wsl.describe",["remove",{unregister:false}]).then((plan)=>{
const p=appConfirm("Remove the Kali setup?",{wide:true,danger:true,okLabel:"Remove",bodyHtml:'<p class="tsh-confirm-note">LOYA puts back the WSL networking lines it changed and forgets the setup. The Kali distro and your files in it stay unless you tick the box.</p>'+tshDescribeHtml(plan)+'<label class="set-check tsh-unreg"><input type="checkbox" id="tshUnreg"><span>Also delete the kali-linux distro and all its files (wsl --unregister)</span></label><input type="text" class="set-input hidden" id="tshUnregName" placeholder="Type kali-linux to confirm" autocomplete="off" spellcheck="false">'})
const box=document.getElementById("tshUnreg"),name=document.getElementById("tshUnregName")
if(box)box.addEventListener("change",()=>{unregister=box.checked;if(name)name.classList.toggle("hidden",!box.checked)})
if(name)name.addEventListener("input",()=>{typed=name.value.trim()})
return p
})
return opened.then((ok)=>{
if(!ok)return
if(unregister&&typed!=="kali-linux"){tshError(new Error("Type kali-linux to delete the distro. Nothing was removed."));return}
return tshRun(bridgeCall("wsl.remove_setup",[unregister,typed,true]).then((r)=>{tshAfterShellsChange();return r}),(r)=>((r&&r.log)||[]).join(" ")||"Removed.")
}).catch(tshError)
}
function tshRender(){
const root=tshState.root
if(!root)return
tshCloseNotesPopover(false)
const st=tshState.status
let html=tshShellsHtml(tshState.shells,tshState.settings||{},tshState.extras)
if(st&&st.supported)html+=tshKaliHtml(st)
const left=tshState.notesTimer&&!tshState.notesTimer.done?tshState.notesTimer.remaining():0
if(tshState.notesTimer){tshState.notesTimer.finish("closed");tshState.notesTimer=null}
root.innerHTML=html
tshWire(root)
if(left>0)tshShowInlineNotes(left)
}
function tshLoad(first){
const root=tshState.root
if(!root)return Promise.resolve()
const token=++tshState.token
const safe=(p,args,fallback)=>bridgeCall(p,args).catch(()=>fallback)
return Promise.all([bridgeCall("terminal.shells"),bridgeCall("terminal.get_settings"),safe("terminal.shell_extras",[],null)]).then(([shells,settings,extras])=>{
const win=settings&&settings.platform==="windows"
return (win?safe("wsl.status",[true],null):Promise.resolve(null)).then((status)=>{
if(token!==tshState.token)return
tshState.shells=shells||[];tshState.settings=settings||{};tshState.extras=extras;tshState.status=status
if(status&&status.state&&!tshState.form.mode)tshState.form.mode=status.state.network&&status.state.network.mode||"nat"
tshRender()
// The option is already on when the card loads: show the notes for 100 seconds (once per visit).
if(first&&status&&status.supported&&status.state&&status.state.enabled&&!tshState.notesShown){tshState.notesShown=true;tshShowInlineNotes()}
})
}).catch((err)=>{
if(token!==tshState.token)return
root.innerHTML='<div class="set-box glass-panel"><div class="set-box-title">Terminal Shells</div><div class="set-status error">'+tshEsc(err&&err.message?err.message:"Could not load the shell settings.")+"</div></div>"
})
}
function tshMountSettings(root){
if(!root)return
const first=tshState.root!==root
tshState.root=root
if(first){tshState.notesShown=false;tshState.form={}}
return tshLoad(true)
}
if(typeof module!=="undefined"&&module.exports)module.exports={tshEsc,tshDefaultShellOptions,tshModeOptions,tshUnavailableReasons,tshModeFields,tshCollectNetwork,tshStepIndex,tshStepsHtml,tshNotesListHtml,tshNotesButtonHtml,tshInlineNotesHtml,tshCreateNotesTimer,tshVerifyHtml,tshStatusRowsHtml,tshNetworkFormHtml,tshWizardHtml,tshKaliHtml,tshShellsHtml,tshDescribeHtml,tshOpenNotesPopover,tshCloseNotesPopover,tshShowInlineNotes,tshState,TSH_NOTES_MS,TSH_NOTES_LABEL}
