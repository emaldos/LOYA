let tgtState={tab:"targets",targets:[],keys:[],targetSearch:"",keySearch:"",manualOnly:false,unusedOnly:false,keyPattern:false}
// Escapes quotes too: the result is also placed inside HTML attributes (title, data-*, value). The old textContent/innerHTML
// trick left " unescaped, so a saved name like  " onmouseover="...  injected a handler with full bridge access.
function tgtEscapeHtml(s){
return String(s===undefined||s===null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")
}
function tgtSwitchTab(tab){
tgtState.tab=tab
document.querySelectorAll(".tgt-tab").forEach((t)=>{const on=t.dataset.tab===tab;t.classList.toggle("active",on);t.setAttribute("aria-selected",on?"true":"false")})
document.querySelectorAll(".tgt-panel").forEach((p)=>p.classList.toggle("active",p.dataset.tabPanel===tab))
tgtCloseToolsMenu()
}
// T11/T12 (ORIG Target.py _render_targets): search the name and the values, list sorted by name.
function tgtFilterTargets(){
const q=tgtState.targetSearch.trim().toLowerCase()
const list=q?tgtState.targets.filter((t)=>((t.name||"")+" "+Object.values(t.values||{}).join(" ")).toLowerCase().includes(q)):tgtState.targets.slice()
return list.sort((a,b)=>(a.name||"").toLowerCase().localeCompare((b.name||"").toLowerCase()))
}
function tgtStripBraces(k){
k=(k||"").trim()
if(k.length>=2&&k.startsWith("{")&&k.endsWith("}"))k=k.slice(1,-1).trim()
return k
}
function tgtErr(err,fallback){return err&&err.message?err.message:fallback}
// T2/T14: keys and target values move together, and other pages must drop their cached keys.
function tgtRefreshAll(){
return Promise.all([tgtRefreshTargets(),tgtRefreshKeys()])
}
function tgtKeysChanged(kind){
document.dispatchEvent(new CustomEvent("loya:target-keys-changed",{detail:{kind}}))
return tgtRefreshAll()
}
const TGT_ENGAGEMENT_STATUSES=[{value:"not_started",label:"Not Started"},{value:"in_progress",label:"In Progress"},{value:"compromised",label:"Compromised"},{value:"reported",label:"Reported"}]
function tgtEngagementOptionsHtml(current){
return TGT_ENGAGEMENT_STATUSES.map((s)=>`<option value="${s.value}"${s.value===current?" selected":""}>${s.label}</option>`).join("")
}
// ---- Pure helpers (tests/js/targets_page.js loads this block on its own) ----
// Same rule as the title-bar badge (live-target-badge.js): these keys hold secrets, so the form masks them.
const TGT_SECRET_RX=/pass|secret|token|hash|key|cred|cookie|session|private|otp|pin/i
function tgtIsSecretKey(key){return TGT_SECRET_RX.test(String(key||""))}
const TGT_IPV4_RX=/^(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}(\/([12]?\d|3[0-2]))?$/
function tgtKeyKind(key){
const k=String(key||"").toLowerCase().replace(/[\s-]+/g,"_")
if(/(^|_)ipv6$/.test(k))return "ipv6"
if(/^(ip|ipv4|rhost|lhost|rhosts|target_?ip|host_?ip)$/.test(k)||/(^|_)ip(v4)?$/.test(k))return "ip"
if(/^(r|l)?ports?$/.test(k)||/(^|_)ports?$/.test(k))return "port"
if(/url|uri|endpoint/.test(k))return "url"
if(/domain|fqdn|dns/.test(k))return "domain"
if(/user/.test(k))return "user"
if(/wordlist|list_?file/.test(k))return "path"
if(/hash/.test(k))return "hash"
if(tgtIsSecretKey(k))return "secret"
return ""
}
function tgtValueHint(key){
const hints={ipv6:"e.g. fe80::1",ip:"e.g. 10.10.10.5 or 10.10.10.0/24",port:"e.g. 443 or 80,8080",url:"e.g. https://host.example/",domain:"e.g. corp.local",user:"e.g. administrator",path:"e.g. /usr/share/wordlists/rockyou.txt",hash:"NTLM or other hash",secret:"Hidden value"}
return hints[tgtKeyKind(key)]||"Value for {"+String(key||"")+"}"
}
// Inline validation only warns (pentest values are often unusual); it never blocks the save.
function tgtValueWarning(key,value){
const v=String(value||"").trim()
if(!v)return ""
const kind=tgtKeyKind(key)
const parts=v.split(/[\s,]+/).filter(Boolean)
if(kind==="ip"&&!parts.every((p)=>TGT_IPV4_RX.test(p)))return "Does not look like an IPv4 address or CIDR range"
if(kind==="port"&&!parts.every((p)=>/^\d{1,5}(-\d{1,5})?$/.test(p)&&p.split("-").every((n)=>+n>=1&&+n<=65535)))return "Ports are numbers from 1 to 65535 (lists and ranges allowed)"
if(kind==="url"&&!/^[a-z][a-z0-9+.-]*:\/\//i.test(v))return "URLs usually start with http:// or https://"
return ""
}
// Filled values first (in priority order), then the empty ones (in priority order).
function tgtOrderFormKeys(keys,values){
values=values||{}
const has=(k)=>String(values[k]===undefined||values[k]===null?"":values[k]).trim()!==""
return keys.filter(has).concat(keys.filter((k)=>!has(k)))
}
function tgtFormFieldVisible(key,value,query,onlyFilled){
if(onlyFilled&&!String(value||"").trim())return false
return tgtFieldMatches(key,query)
}
function tgtFormNormalize(data){
data=data||{}
const vals={}
Object.keys(data.values||{}).sort().forEach((k)=>{const v=String(data.values[k]===undefined||data.values[k]===null?"":data.values[k]).trim();if(v)vals[k]=v})
return JSON.stringify([String(data.name||"").trim(),data.engagement||"not_started",vals])
}
function tgtFormIsDirty(initial,current){return tgtFormNormalize(initial)!==tgtFormNormalize(current)}
// A short second line under the name: the first host-like value (IP, domain, URL...) by element priority, never a secret.
function tgtTargetHint(t,keyOrder){
const values=(t&&t.values)||{}
const filled=Object.keys(values).filter((k)=>String(values[k]||"").trim())
const order=(keyOrder||[]).filter((k)=>filled.includes(k)).concat(filled.filter((k)=>!(keyOrder||[]).includes(k)))
const shown=order.filter((k)=>!tgtIsSecretKey(k))
const host=shown.find((k)=>["ip","domain","url","ipv6"].includes(tgtKeyKind(k)))||shown[0]
const count=filled.length+" value"+(filled.length===1?"":"s")
if(!host)return {text:count,key:""}
return {text:String(values[host]).trim(),key:host,count}
}
function tgtCountLabel(shown,total,noun){
if(shown===total)return total+" "+noun+(total===1?"":"s")
return shown+" of "+total
}
// ---- end pure helpers ----
const TGT_EYE_SVG='<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>'
const TGT_EYE_OFF_SVG='<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 3l18 18"/><path d="M10.6 5.1A10.8 10.8 0 0 1 12 5c6.4 0 10 7 10 7a17.6 17.6 0 0 1-3.2 4.1M6.6 6.6C3.9 8.4 2 12 2 12s3.6 7 10 7a9.7 9.7 0 0 0 5.4-1.6"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/></svg>'
function tgtRenderTargetRow(t,keyOrder){
const tr=document.createElement("tr")
const live=t.status==="live"
tr.className="tgt-row"+(live?" tgt-row-live":"")
const est=t.engagement_status||"not_started"
const hint=tgtTargetHint(t,keyOrder)
const hintHtml=hint.key?`<span class="tgt-hint-key">{${tgtEscapeHtml(hint.key)}}</span><span class="tgt-hint-val">${tgtEscapeHtml(hint.text)}</span>${hint.count?`<span class="tgt-hint-count">${tgtEscapeHtml(hint.count)}</span>`:""}`:`<span class="tgt-hint-count">${tgtEscapeHtml(hint.text)}</span>`
const status=live?`<button type="button" class="tgt-status-badge tgt-status-live" title="Live target - click to stop using it"><span class="tgt-live-dot"></span><span>Live</span></button>`:`<button type="button" class="tgt-status-badge tgt-status-not-used" title="Make this the live target"><span class="tgt-idle-dot"></span><span>Set live</span></button>`
tr.innerHTML=`<td class="tgt-cell-target"><div class="tgt-target"><span class="tgt-dot${live?" live":""}" aria-hidden="true"></span><div class="tgt-target-text"><button type="button" class="tgt-cell-name" title="${live?"Click to stop using this target":"Click to use this target"}">${tgtEscapeHtml(t.name)}</button><div class="tgt-target-hint">${hintHtml}</div></div></div></td><td class="tgt-col-status">${status}</td><td class="tgt-col-engagement"><select class="tgt-engagement-select tgt-engagement-${est}" aria-label="Engagement status">${tgtEngagementOptionsHtml(est)}</select></td><td class="tgt-col-actions"><div class="tgt-row-actions"><button type="button" class="tgt-icon-btn" data-action="edit" title="Edit target"><i class="icon icon-edit"></i></button><button type="button" class="tgt-icon-btn danger" data-action="delete" title="Delete (Shift+click skips the confirm)"><i class="icon icon-trash"></i></button></div></td>`
tr.querySelector(".tgt-status-badge").addEventListener("click",()=>tgtToggleLive(t))
tr.querySelector(".tgt-cell-name").addEventListener("click",()=>tgtToggleLive(t))
tr.querySelector(".tgt-engagement-select").addEventListener("change",(e)=>{
const val=e.target.value
bridgeCall("targets.set_engagement_status",[t.id,val]).then((targets)=>{
tgtState.targets=targets
tgtRenderTargets()
}).catch((err)=>showToast(err&&err.message?err.message:"Update failed","error"))
})
tr.querySelector('[data-action="edit"]').addEventListener("click",()=>tgtOpenTargetForm(t))
tr.querySelector('[data-action="delete"]').addEventListener("click",(e)=>tgtDeleteTarget(t,e.shiftKey))
tr.addEventListener("dblclick",(e)=>{if(!e.target.closest("button,select,.ui-select-trigger"))tgtOpenTargetForm(t)})
return tr
}
function tgtEmptyHtml(icon,title,sub,btnLabel,act){
return `<i class="icon ${icon} tgt-empty-icon"></i><div class="tgt-empty-title">${title}</div><div class="tgt-empty-sub">${sub}</div>${btnLabel?`<button type="button" class="tgt-new-btn" data-empty-act="${act}">${act==="clear"?"":'<i class="icon icon-add"></i>'}<span>${btnLabel}</span></button>`:""}`
}
function tgtSyncSearchClear(id){
const input=document.getElementById(id)
const btn=document.querySelector(`.tgt-search-clear[data-clear="${id}"]`)
if(input&&btn)btn.classList.toggle("hidden",!input.value)
}
function tgtRenderTargets(){
const tbody=document.getElementById("tgtTableBody")
if(!tbody)return
tbody.innerHTML=""
const list=tgtFilterTargets()
const total=tgtState.targets.length
const empty=document.getElementById("tgtEmptyMsg")
empty.classList.toggle("hidden",list.length>0)
tbody.closest("table").classList.toggle("hidden",list.length===0)
if(!list.length){
empty.innerHTML=total?tgtEmptyHtml("icon-search","No targets match “"+tgtEscapeHtml(tgtState.targetSearch.trim())+"”","The search looks at target names and every value.","Clear search","clear"):tgtEmptyHtml("icon-target","No targets in this profile yet","A target holds the values ({IPv4}, {URL}, {Username}...) that your commands fill in.","Add Target","add")
}
const count=document.getElementById("tgtCount")
if(count)count.textContent=total?tgtCountLabel(list.length,total,"target"):""
const keyOrder=tgtState.keys.map((k)=>k.key)
list.forEach((t)=>tbody.appendChild(tgtRenderTargetRow(t,keyOrder)))
}
function tgtToggleLive(t){
const wasLive=t.status==="live"
bridgeCall("targets.set_live_target",[t.id]).then((targets)=>{
tgtState.targets=targets
tgtRenderTargets()
showToast(wasLive?"No target in use now":`Using target: ${t.name}`)
}).catch((err)=>showToast(tgtErr(err,"Could not change the live target"),"error"))
}
function tgtDeleteTarget(t,skipConfirm){
const ask=skipConfirm?Promise.resolve(true):appConfirm(`Delete target "${t.name}"? This moves it to the Recycle Bin.`,{okLabel:"Delete",danger:true})
ask.then((yes)=>{
if(!yes)return
bridgeCall("targets.delete_target",[t.id]).then(()=>tgtRefreshTargets()).catch((err)=>showToast(err&&err.message?err.message:"Delete failed","error"))
})
}
function tgtClosePopover(){
closeModal()
}
const TGT_CIDR_RX=/^\d{1,3}(\.\d{1,3}){3}\/\d{1,2}$/
function tgtCloseCidrPopover(){
const el=document.getElementById("tgtCidrPopover")
if(el)el.remove()
}
function tgtOpenCidrPopover(anchorEl,value){
tgtCloseCidrPopover()
const box=document.createElement("div")
box.id="tgtCidrPopover"
box.className="notes-ph-suggest glass-panel tgt-cidr-popover"
box.textContent="Expanding..."
document.body.appendChild(box)
const rect=anchorEl.getBoundingClientRect()
box.style.left=Math.round(Math.min(rect.left,window.innerWidth-260))+"px"
box.style.top=Math.round(rect.bottom+6)+"px"
bridgeCall("targets.expand_cidr",[value]).then((res)=>{
const extra=res.truncated?`<div class="tgt-cidr-more">+${res.total-res.hosts.length} more (showing first ${res.hosts.length})</div>`:""
box.innerHTML=`<div class="tgt-cidr-title">${tgtEscapeHtml(res.network)} - ${res.total} host${res.total===1?"":"s"}</div><div class="tgt-cidr-list">${res.hosts.map((h)=>tgtEscapeHtml(h)).join("<br>")}</div>${extra}`
}).catch((err)=>{box.textContent=err&&err.message?err.message:"Failed to expand"})
setTimeout(()=>document.addEventListener("mousedown",tgtCidrOutsideClick,true),0)
}
function tgtCidrOutsideClick(e){
const box=document.getElementById("tgtCidrPopover")
if(box&&!box.contains(e.target)){box.remove();document.removeEventListener("mousedown",tgtCidrOutsideClick,true)}
}
function tgtSyncProfileBtnLabel(){
bridgeCall("targets.list_profiles").then((profiles)=>{
const active=profiles.find((p)=>p.active)
const name=active?active.name:"Default"
tgtState.profileName=name
const label=document.getElementById("tgtProfileBtnLabel")
if(label){label.textContent=name;label.title=name}
}).catch(()=>{})
}
function tgtOpenProfilesMenu(){
bridgeCall("targets.list_profiles").then((profiles)=>{
const pop=document.createElement("div")
pop.className="tgt-popover glass-panel"
let html='<div class="tgt-popover-title">Target Profiles</div><div class="tgt-popover-values">'
profiles.forEach((p)=>{
html+=`<div class="tgt-profile-row"><button type="button" class="tgt-profile-apply${p.active?" active":""}" data-id="${tgtEscapeHtml(p.id)}"><i class="icon icon-folder"></i><span>${tgtEscapeHtml(p.name)}</span>${p.active?'<span class="tgt-profile-active-tag">Active</span>':""}</button>${p.id!=="default"?`<button type="button" class="tgt-profile-delete" data-id="${tgtEscapeHtml(p.id)}" title="Delete profile"><i class="icon icon-close"></i></button>`:""}</div>`
})
html+='</div><div class="tgt-popover-field"><label for="tgtNewProfileInput">New profile name</label><input type="text" id="tgtNewProfileInput" autocomplete="off" spellcheck="false"></div><div class="tgt-popover-error hidden" id="tgtProfileErr"></div><div class="tgt-popover-actions"><button type="button" id="tgtProfileCloseBtn">Close</button><button type="button" class="tgt-popover-confirm" id="tgtProfileCreateBtn">Create Profile</button></div>'
pop.innerHTML=html
openModal(pop)
pop.querySelectorAll(".tgt-profile-apply").forEach((btn)=>{
btn.addEventListener("click",()=>{
if(btn.classList.contains("active")){closeModal();return}
bridgeCall("targets.switch_profile",[btn.dataset.id]).then(()=>{
closeModal()
tgtSyncProfileBtnLabel()
return tgtKeysChanged("profile")
}).catch((err)=>showToast(err&&err.message?err.message:"Switch failed","error"))
})
})
pop.querySelectorAll(".tgt-profile-delete").forEach((btn)=>{
btn.addEventListener("click",(e)=>{
e.stopPropagation()
appConfirm("Delete this profile? Its targets and values cannot be recovered.",{okLabel:"Delete",danger:true}).then((yes)=>{
if(!yes)return
bridgeCall("targets.delete_profile",[btn.dataset.id]).then(()=>{
tgtSyncProfileBtnLabel()
Promise.all([tgtRefreshTargets(),tgtRefreshKeys()])
tgtOpenProfilesMenu()
}).catch((err)=>showToast(err&&err.message?err.message:"Delete failed","error"))
})
})
})
const createProfile=()=>{
const input=pop.querySelector("#tgtNewProfileInput")
const name=input.value.trim()
const errEl=pop.querySelector("#tgtProfileErr")
errEl.classList.add("hidden")
if(!name){errEl.textContent="Profile name is required.";errEl.classList.remove("hidden");input.focus();return}
bridgeCall("targets.create_profile",[name]).then(()=>{
closeModal()
tgtOpenProfilesMenu()
}).catch((err)=>{errEl.textContent=err&&err.message?err.message:"Create failed";errEl.classList.remove("hidden")})
}
pop.querySelector("#tgtProfileCloseBtn").addEventListener("click",closeModal)
pop.querySelector("#tgtProfileCreateBtn").addEventListener("click",createProfile)
pop.querySelector("#tgtNewProfileInput").addEventListener("keydown",(e)=>{if(e.key==="Enter"){e.preventDefault();createProfile()}})
}).catch((err)=>console.error("list profiles failed",err))
}
// ---- Add/Edit Target form ----
function tgtFormRead(pop){
const values={}
pop.querySelectorAll(".tgt-value-input").forEach((input)=>{
const v=input.value.trim()
if(v)values[input.dataset.key]=v
})
const name=pop.querySelector("#tgtFieldName")
const eng=pop.querySelector("#tgtFieldEngagement")
return {name:name?name.value.trim():"",engagement:eng?eng.value:"not_started",values}
}
function tgtFormConfirmDiscard(pop){
if(!pop._tgtInitial||!tgtFormIsDirty(pop._tgtInitial,tgtFormRead(pop)))return true
return appConfirm("Discard your unsaved changes to this target?",{okLabel:"Discard",cancelLabel:"Keep editing",danger:true}).then((yes)=>!!yes)
}
function tgtFormSyncState(pop){
const data=tgtFormRead(pop)
const total=pop.querySelectorAll(".tgt-value-input").length
const filled=Object.keys(data.values).length
const counter=pop.querySelector("#tgtFormFilled")
if(counter)counter.textContent=total?`${filled} of ${total} filled`:""
const dirty=!!pop._tgtInitial&&tgtFormIsDirty(pop._tgtInitial,data)
pop.classList.toggle("is-dirty",dirty)
const mark=pop.querySelector(".tgt-form-dirty")
if(mark)mark.classList.toggle("hidden",!dirty)
}
function tgtFormFieldHtml(key,i){
const secret=tgtIsSecretKey(key)
const id="tgtV"+i
const k=tgtEscapeHtml(key)
const tools=secret?`<button type="button" class="tgt-vbtn" data-act="reveal" tabindex="-1" title="Show value" aria-label="Show value of {${k}}">${TGT_EYE_SVG}</button><button type="button" class="tgt-vbtn" data-act="copy" tabindex="-1" title="Copy value" aria-label="Copy value of {${k}}"><i class="icon icon-copy"></i></button>`:""
return `<div class="tgt-popover-field tgt-vfield${secret?" is-secret":""}" data-key="${k}"><label class="tgt-vlabel" for="${id}"><span class="tgt-vkey">{${k}}</span>${secret?'<span class="tgt-vtag">secret</span>':""}</label><div class="tgt-value-row"><div class="tgt-vinput"><input id="${id}" type="${secret?"password":"text"}" class="tgt-value-input" data-key="${k}" placeholder="${tgtEscapeHtml(tgtValueHint(key))}" autocomplete="${secret?"new-password":"off"}" spellcheck="false">${tools}</div><button type="button" class="tgt-cidr-expand hidden" data-key="${k}" title="Expand CIDR range"><i class="icon icon-expand"></i></button></div><div class="tgt-vwarn hidden" aria-live="polite"></div></div>`
}
function tgtOpenTargetForm(target){
const isEdit=!!target
const pop=document.createElement("div")
pop.id="tgtPopover"
pop.className="tgt-popover tgt-form glass-panel"
pop.tabIndex=-1 // a click on a label or blank part of the form focuses the form, so Ctrl+S still reaches its keydown handler
pop.setAttribute("role","dialog")
pop.setAttribute("aria-modal","true")
pop.setAttribute("aria-labelledby","tgtFormTitle")
const values=isEdit?(target.values||{}):{}
const keys=tgtOrderFormKeys(tgtState.keys.map((k)=>k.key),values)
const live=isEdit&&target.status==="live"
const engagementOptions=tgtEngagementOptionsHtml(isEdit?target.engagement_status||"not_started":"not_started")
const sub=isEdit?(live?'<span class="tgt-form-live"><span class="tgt-live-dot"></span>Live target</span>':"Not in use")+` <span class="tgt-form-sep">&middot;</span> ${tgtEscapeHtml(tgtState.profileName||"Default")}`:`New target in ${tgtEscapeHtml(tgtState.profileName||"Default")}`
const fields=keys.map((k,i)=>tgtFormFieldHtml(k,i)).join("")
const valuesBody=keys.length?`<div class="tgt-form-sec-head"><div class="tgt-form-sec-title tgt-popover-values-title">Values <span class="tgt-form-filled" id="tgtFormFilled"></span></div><div class="tgt-field-finder"><i class="icon icon-search"></i><input type="text" id="tgtFieldFind" placeholder="Find element..." autocomplete="off" spellcheck="false" aria-label="Find element"></div><button type="button" class="tgt-chip" id="tgtOnlyFilled" aria-pressed="false" title="Show only the elements that have a value">Only filled</button></div><div class="tgt-form-grid">${fields}</div><div class="tgt-form-nomatch hidden">No element matches. <button type="button" class="tgt-link" data-act="clear-find">Show all</button></div>`:`<div class="tgt-form-sec-head"><div class="tgt-form-sec-title tgt-popover-values-title">Values</div></div><div class="tgt-form-novalues">No elements yet. Elements are the {placeholders} your commands use, such as {IPv4} or {URL}.</div>`
pop.innerHTML=`<header class="tgt-form-head"><div class="tgt-form-head-icon"><i class="icon icon-target"></i></div><div class="tgt-form-head-text"><div class="tgt-popover-title" id="tgtFormTitle">${isEdit?"Edit Target":"Add Target"}<span class="tgt-form-dirty hidden" title="Unsaved changes">&bull;</span></div><div class="tgt-form-sub">${sub}</div></div><button type="button" class="tgt-form-close" id="tgtFormClose" title="Close (Esc)" aria-label="Close"><i class="icon icon-close"></i></button></header>
<div class="tgt-form-body">
<section class="tgt-form-sec tgt-form-basics"><div class="tgt-form-sec-title">Basics</div><div class="tgt-form-basics-grid"><div class="tgt-popover-field tgt-field-name"><label for="tgtFieldName">Name <span class="tgt-req" aria-hidden="true">*</span></label><input type="text" id="tgtFieldName" placeholder="e.g. web01.corp.local" autocomplete="off" spellcheck="false" aria-required="true"><div class="tgt-field-err hidden" id="tgtFieldNameErr"></div></div><div class="tgt-popover-field"><label for="tgtFieldEngagement">Engagement status</label><select id="tgtFieldEngagement">${engagementOptions}</select></div></div></section>
<div class="tgt-popover-error hidden" id="tgtFormError" role="alert"></div>
<section class="tgt-form-sec tgt-popover-values">${valuesBody}<div class="tgt-form-addel"><button type="button" class="tgt-link" id="tgtFormAddElement"><i class="icon icon-add"></i><span>Add element</span></button><span>New elements show up here for every target.</span></div></section>
</div>
<footer class="tgt-form-foot"><span class="tgt-form-keys"><kbd>Ctrl</kbd>+<kbd>S</kbd> save<span class="tgt-form-sep">&middot;</span><kbd>Esc</kbd> close</span><div class="tgt-popover-actions"><button type="button" id="tgtFormCancel">Cancel</button><button type="button" class="tgt-popover-confirm" id="tgtFormSave">${isEdit?"Save Changes":"Create Target"}</button></div></footer>`
openModal(pop,{onBeforeClose:()=>tgtFormConfirmDiscard(pop),onEscape:()=>tgtFormOnEscape(pop)})
const nameInput=pop.querySelector("#tgtFieldName")
if(isEdit){
nameInput.value=target.name
keys.forEach((k)=>{
const input=pop.querySelector(`.tgt-value-input[data-key="${CSS.escape(k)}"]`)
if(input)input.value=values[k]||""
})
}
pop._tgtInitial=tgtFormRead(pop)
pop._tgtOnlyFilled=false
pop._tgtTargetId=isEdit?target.id:null
pop.querySelectorAll(".tgt-vfield").forEach((field)=>{
const input=field.querySelector(".tgt-value-input")
const expandBtn=field.querySelector(".tgt-cidr-expand")
const warn=field.querySelector(".tgt-vwarn")
const sync=()=>{
const v=input.value.trim()
expandBtn.classList.toggle("hidden",!TGT_CIDR_RX.test(v))
field.classList.toggle("is-filled",!!v)
const msg=tgtValueWarning(input.dataset.key,v)
warn.textContent=msg
warn.classList.toggle("hidden",!msg)
field.classList.toggle("has-warning",!!msg)
}
input.addEventListener("input",()=>{sync();tgtFormSyncState(pop)})
sync()
expandBtn.addEventListener("click",()=>tgtOpenCidrPopover(expandBtn,input.value.trim()))
const reveal=field.querySelector('[data-act="reveal"]')
if(reveal)reveal.addEventListener("click",()=>{
const show=input.type==="password"
input.type=show?"text":"password"
reveal.innerHTML=show?TGT_EYE_OFF_SVG:TGT_EYE_SVG
reveal.title=show?"Hide value":"Show value"
field.classList.toggle("is-revealed",show)
})
const copy=field.querySelector('[data-act="copy"]')
if(copy)copy.addEventListener("click",()=>{
const v=input.value
if(!v){showToast("Nothing to copy","error");return}
if(navigator.clipboard)navigator.clipboard.writeText(v).then(()=>showToast(`Copied {${input.dataset.key}}`)).catch(()=>showToast("Copy failed","error"))
})
})
nameInput.addEventListener("input",()=>{tgtFormValidateName(pop,false);tgtFormSyncState(pop)})
pop.querySelector("#tgtFieldEngagement").addEventListener("change",()=>tgtFormSyncState(pop))
const findInput=pop.querySelector("#tgtFieldFind")
if(findInput){
findInput.addEventListener("input",()=>tgtFilterFormFields(pop,findInput.value))
findInput.addEventListener("keydown",(e)=>{
if(e.key!=="Enter"||e.ctrlKey||e.metaKey)return
e.preventDefault()
e.stopPropagation()
const first=tgtFilterFormFields(pop,findInput.value)
if(first){first.focus();first.select()}
})
}
const onlyFilled=pop.querySelector("#tgtOnlyFilled")
if(onlyFilled)onlyFilled.addEventListener("click",()=>{
pop._tgtOnlyFilled=!pop._tgtOnlyFilled
onlyFilled.classList.toggle("active",pop._tgtOnlyFilled)
onlyFilled.setAttribute("aria-pressed",pop._tgtOnlyFilled?"true":"false")
tgtFilterFormFields(pop,findInput?findInput.value:"")
})
const clearFind=pop.querySelector('[data-act="clear-find"]')
if(clearFind)clearFind.addEventListener("click",()=>{
if(findInput)findInput.value=""
if(pop._tgtOnlyFilled&&onlyFilled)onlyFilled.click()
else tgtFilterFormFields(pop,"")
})
pop.querySelector("#tgtFormAddElement").addEventListener("click",()=>{
Promise.resolve(tgtFormConfirmDiscard(pop)).then((ok)=>{
if(ok===false)return
closeModal(true)
tgtSwitchTab("elements")
tgtOpenAddKeyModal()
})
})
pop.querySelector("#tgtFormClose").addEventListener("click",()=>closeModal())
pop.querySelector("#tgtFormCancel").addEventListener("click",()=>closeModal())
const saveBtn=pop.querySelector("#tgtFormSave")
saveBtn.addEventListener("click",()=>tgtFormSave(pop,target))
pop.addEventListener("keydown",(e)=>tgtFormKeydown(pop,e))
tgtFormSyncState(pop)
// Focus now (not in a timeout): callers such as the dashboard focus a value field right after this returns.
nameInput.focus()
}
function tgtFormValidateName(pop,showEmpty){
const input=pop.querySelector("#tgtFieldName")
const err=pop.querySelector("#tgtFieldNameErr")
const name=input.value.trim()
let msg=""
if(!name&&showEmpty)msg="Name is required."
else if(name){
const self=pop._tgtTargetId
const dup=tgtState.targets.find((t)=>t.id!==self&&(t.name||"").trim().toLowerCase()===name.toLowerCase())
if(dup)msg="Another target already uses this name."
}
err.textContent=msg
err.classList.toggle("hidden",!msg)
input.classList.toggle("invalid",!!msg&&!name)
return !!name
}
function tgtFormSave(pop,target){
if(pop._tgtSaving)return
const isEdit=!!target
if(!tgtFormValidateName(pop,true)){pop.querySelector("#tgtFieldName").focus();return}
const data=tgtFormRead(pop)
const errEl=pop.querySelector("#tgtFormError")
const saveBtn=pop.querySelector("#tgtFormSave")
errEl.classList.add("hidden")
pop._tgtSaving=true
saveBtn.disabled=true
bridgeCall("targets.upsert_target",[isEdit?target.id:null,data.name,isEdit?target.status:"not_used",data.values,data.engagement]).then(()=>{
closeModal(true)
showToast(isEdit?`Saved ${data.name}`:`Added target ${data.name}`)
return tgtRefreshTargets()
}).catch((err)=>{
errEl.textContent=err&&err.message?err.message:"Save failed"
errEl.classList.remove("hidden")
}).then(()=>{pop._tgtSaving=false;saveBtn.disabled=false})
}
function tgtFormOnEscape(pop){
if(document.getElementById("uiSelectPopover")){if(typeof uiSelectClose==="function")uiSelectClose();return false}
if(document.getElementById("tgtCidrPopover")){tgtCloseCidrPopover();return false}
const find=pop.querySelector("#tgtFieldFind")
if(find&&document.activeElement===find&&find.value){find.value="";tgtFilterFormFields(pop,"");return false}
return true
}
function tgtFormKeydown(pop,e){
if(document.querySelector(".confirm-overlay"))return
const mod=e.ctrlKey||e.metaKey
if(mod&&(e.key==="Enter"||e.key.toLowerCase()==="s")){
e.preventDefault()
e.stopPropagation()
pop.querySelector("#tgtFormSave").click()
return
}
if(e.key!=="Enter"||e.target.tagName!=="INPUT")return
// Enter never submits: it moves to the next visible field instead.
e.preventDefault()
const inputs=Array.from(pop.querySelectorAll("#tgtFieldName,.tgt-value-input")).filter((el)=>!el.closest(".hidden"))
const i=inputs.indexOf(e.target)
if(i>=0&&i<inputs.length-1){inputs[i+1].focus();inputs[i+1].select()}
}
// T15 (ORIG TargetEditorDialog._on_find_preview): any token contained in the key name keeps the field visible.
function tgtFieldMatches(key,query){
const toks=(query||"").toLowerCase().split(/[,\s]+/).filter(Boolean)
if(!toks.length)return true
const k=(key||"").toLowerCase()
return toks.some((t)=>k.includes(t))
}
function tgtFilterFormFields(pop,query){
let first=null
let shown=0
pop.querySelectorAll(".tgt-value-input").forEach((input)=>{
const ok=tgtFormFieldVisible(input.dataset.key,input.value,query,!!pop._tgtOnlyFilled)
const field=input.closest(".tgt-popover-field")
if(field)field.classList.toggle("hidden",!ok)
if(ok){shown++;if(!first)first=input}
})
const none=pop.querySelector(".tgt-form-nomatch")
if(none)none.classList.toggle("hidden",shown>0)
if(first&&(query||"").trim())first.scrollIntoView({block:"nearest"})
return first
}
function tgtRefreshTargets(){
return bridgeCall("targets.targets").then((targets)=>{
tgtState.targets=targets
tgtRenderTargets()
})
}
// ---- Set Elements ----
function tgtFilterKeys(){
let list=tgtState.keys
const q=tgtState.keySearch.trim().toLowerCase()
if(q)list=list.filter((k)=>k.key.toLowerCase().includes(q))
if(tgtState.manualOnly)list=list.filter((k)=>k.manual)
else if(tgtState.unusedOnly)list=list.filter((k)=>k.links===0&&!k.manual)
return list
}
function tgtRenderKeyRow(k){
const tr=document.createElement("tr")
tr.className="tgt-row"
const key=tgtEscapeHtml(k.key)
const links=k.links||0
tr.innerHTML=`<td><div class="tgt-key-cell"><span class="tgt-brace">{</span><input type="text" class="tgt-key-name-input" value="${key}" title="Click to rename" aria-label="Rename element {${key}}" spellcheck="false" autocomplete="off"><span class="tgt-brace">}</span><span class="tgt-key-edit-hint">Enter to save &middot; Esc to cancel</span></div></td><td class="tgt-col-priority"><div class="tgt-stepper" title="Lower numbers are listed first"><button type="button" class="tgt-step" data-step="-1" aria-label="Lower priority number" tabindex="-1">&minus;</button><input type="text" inputmode="numeric" class="tgt-priority-input" value="${k.priority}" aria-label="Priority of {${key}}"><button type="button" class="tgt-step" data-step="1" aria-label="Higher priority number" tabindex="-1">+</button></div></td><td class="tgt-col-links"><button type="button" class="tgt-links-btn${links?"":" zero"}" title="Show the commands that use {${key}}">${links} ${links===1?"use":"uses"}</button></td><td class="tgt-col-manual">${k.manual?'<span class="tgt-manual-badge" title="Added by hand">Manual</span>':'<span class="tgt-auto-badge" title="Found in your commands">Auto</span>'}</td><td class="tgt-col-actions"><div class="tgt-row-actions"><button type="button" class="tgt-icon-btn" data-action="rename" title="Rename"><i class="icon icon-edit"></i></button><button type="button" class="tgt-icon-btn danger" data-action="delete" title="${links?`Used in ${links} place${links===1?"":"s"}`:"Remove (Shift+click skips the confirm)"}"><i class="icon icon-trash"></i></button></div></td>`
const nameInput=tr.querySelector(".tgt-key-name-input")
const fit=()=>{nameInput.style.width=`calc(${Math.max(3,Math.min(48,nameInput.value.length+1))}ch + 14px)`}
fit()
nameInput.addEventListener("input",fit)
nameInput.addEventListener("focus",()=>tr.classList.add("is-editing"))
nameInput.addEventListener("blur",()=>tr.classList.remove("is-editing"))
nameInput.addEventListener("keydown",(e)=>{
if(e.key==="Enter"){e.preventDefault();nameInput.blur()}
else if(e.key==="Escape"){e.preventDefault();e.stopPropagation();nameInput.value=k.key;fit();nameInput.blur()}
})
nameInput.addEventListener("change",()=>tgtRenameKey(k.key,nameInput.value,nameInput))
tr.querySelector('[data-action="rename"]').addEventListener("click",()=>{nameInput.focus();nameInput.select()})
const priorityInput=tr.querySelector(".tgt-priority-input")
let stepTimer=null
const commitSoon=()=>{
clearTimeout(stepTimer)
stepTimer=setTimeout(()=>{if(String(priorityInput.value)!==String(k.priority))tgtSetPriority(k.key,priorityInput.value,priorityInput,k.priority)},450)
}
const step=(d)=>{
const cur=parseInt(priorityInput.value,10)
priorityInput.value=String(Math.max(0,Math.min(65535,(isNaN(cur)?k.priority:cur)+d)))
commitSoon()
}
tr.querySelectorAll(".tgt-step").forEach((b)=>b.addEventListener("click",()=>step(parseInt(b.dataset.step,10))))
priorityInput.addEventListener("keydown",(e)=>{
if(e.key==="ArrowUp"){e.preventDefault();step(1)}
else if(e.key==="ArrowDown"){e.preventDefault();step(-1)}
else if(e.key==="Enter"){e.preventDefault();priorityInput.blur()}
})
priorityInput.addEventListener("change",()=>{clearTimeout(stepTimer);tgtSetPriority(k.key,priorityInput.value,priorityInput,k.priority)})
tr.querySelector(".tgt-links-btn").addEventListener("click",()=>tgtOpenUsagePopover(k.key))
tr.querySelector('[data-action="delete"]').addEventListener("click",(e)=>tgtRemoveKey(k,e.shiftKey))
return tr
}
function tgtRenderKeys(){
const tbody=document.getElementById("keysTableBody")
if(!tbody)return
tbody.innerHTML=""
const list=tgtFilterKeys()
const total=tgtState.keys.length
const empty=document.getElementById("keysEmptyMsg")
empty.classList.toggle("hidden",list.length>0)
tbody.closest("table").classList.toggle("hidden",list.length===0)
if(!list.length){
const filtered=total&&(tgtState.keySearch.trim()||tgtState.manualOnly||tgtState.unusedOnly)
empty.innerHTML=filtered?tgtEmptyHtml("icon-search","No elements match these filters","Clear the search or turn off Manual only / Unused.","Clear filters","clear"):tgtEmptyHtml("icon-list","No elements yet","Elements are the {placeholders} commands use, such as {IPv4} or {URL}. They are also found automatically in your commands.","Add Element","add")
}
const count=document.getElementById("keysCount")
if(count)count.textContent=total?tgtCountLabel(list.length,total,"element"):""
list.forEach((k)=>tbody.appendChild(tgtRenderKeyRow(k)))
}
function tgtRefreshKeys(){
return bridgeCall("targets.keys").then((keys)=>{
tgtState.keys=keys
tgtRenderKeys()
})
}
// T13/T19 (ORIG _on_key_cell_changed): strip {}, confirm (mentioning a merge), toast the update counts.
function tgtRenameKey(oldKey,rawKey,inputEl){
const newKey=tgtStripBraces(rawKey)
if(!newKey||newKey===oldKey){inputEl.value=oldKey;return}
const merge=tgtState.keys.some((k)=>k.key.toLowerCase()===newKey.toLowerCase()&&k.key.toLowerCase()!==oldKey.toLowerCase())
appConfirm(`Update ${oldKey} to ${newKey}?${merge?" This will merge keys.":""}`,{okLabel:merge?"Merge":"Rename"}).then((yes)=>{
if(!yes){inputEl.value=oldKey;return}
bridgeCall("targets.rename_key",[oldKey,newKey]).then((msg)=>{
showToast(`Renamed: ${msg||newKey}`)
return tgtKeysChanged("rename")
}).catch((err)=>{
showToast(tgtErr(err,"Rename failed"),"error")
inputEl.value=oldKey
})
})
}
// T18 (ORIG): a non-numeric priority reverts to the stored value instead of showing 0.
function tgtSetPriority(key,value,inputEl,previous){
const raw=String(value||"").trim()
if(!/^\d+$/.test(raw)){inputEl.value=String(previous||0);return}
const n=Math.min(65535,parseInt(raw,10))
bridgeCall("targets.set_priority",[key,n]).then(()=>tgtRefreshKeys()).catch((err)=>{
inputEl.value=String(previous||0)
showToast(tgtErr(err,"Priority update failed"),"error")
})
}
// T17 (ORIG): a linked key cannot be removed (the backend refuses); say so up front and offer the usage list.
function tgtRemoveKey(k,skipConfirm){
if(k.links>0){
appConfirm(`{${k.key}} is used in ${k.links} place${k.links===1?"":"s"} (commands and note blocks). Remove it from ${k.links===1?"there":"those places"} first, then delete the element.`,{okLabel:"Show usage",cancelLabel:"Close"}).then((yes)=>{if(yes)tgtOpenUsagePopover(k.key)})
return
}
const ask=skipConfirm?Promise.resolve(true):appConfirm(`Remove element {${k.key}}? Its value is cleared from every target in this profile.`,{okLabel:"Remove",danger:true})
ask.then((yes)=>{
if(!yes)return
bridgeCall("targets.remove_key",[k.key]).then(()=>tgtKeysChanged("remove")).catch((err)=>showToast(tgtErr(err,"Remove failed"),"error"))
})
}
function tgtAddKey(){
const keyInput=document.getElementById("keyNewInput")
const priorityInput=document.getElementById("keyNewPriority")
const errEl=document.getElementById("keyAddError")
if(!keyInput)return
const key=tgtStripBraces(keyInput.value)
const showErr=(msg)=>{if(errEl){errEl.textContent=msg;errEl.classList.toggle("hidden",!msg)}else if(msg)showToast(msg,"error")}
if(!key){showErr("Enter an element name, for example IPv4.");keyInput.focus();return}
if(tgtState.keys.some((k)=>k.key.toLowerCase()===key.toLowerCase())){showErr(`{${key}} already exists.`);keyInput.focus();return}
showErr("")
const priority=Math.max(0,Math.min(65535,parseInt(priorityInput&&priorityInput.value,10)||0))
bridgeCall("targets.add_key",[key,priority]).then(()=>{
closeModal(true)
showToast(`Added element {${key}}`)
return tgtKeysChanged("add")
}).catch((err)=>showErr(tgtErr(err,"Add failed")))
}
function tgtPatternToggleHtml(id){
return `<label class="tgt-check tgt-setting"><input type="checkbox" id="${id}"${tgtState.keyPattern?" checked":""}><span><b>Accept spaces and symbols in keys</b><small>Off: letters, digits and _ only (recommended for commands).</small></span></label>`
}
function tgtBindPatternToggle(el){
if(!el)return
el.addEventListener("change",()=>{
const val=el.checked
bridgeCall("targets.set_key_pattern",[val]).then(()=>{tgtState.keyPattern=val}).catch((err)=>{el.checked=!val;showToast(tgtErr(err,"Could not change the key setting"),"error")})
})
}
function tgtOpenAddKeyModal(){
tgtCloseToolsMenu()
const pop=document.createElement("div")
pop.id="tgtPopover"
pop.className="tgt-popover tgt-add-key glass-panel"
pop.setAttribute("role","dialog")
const maxPriority=tgtState.keys.reduce((m,k)=>Math.max(m,k.priority||0),-1)
pop.innerHTML=`<div class="tgt-popover-title">Add Element</div><div class="tgt-popover-field"><label for="keyNewInput">Element name</label><div class="tgt-key-field"><span class="tgt-brace">{</span><input type="text" id="keyNewInput" placeholder="IPv4, URL, DC_IP..." autocomplete="off" spellcheck="false"><span class="tgt-brace">}</span></div><div class="tgt-hint">Commands use it as <code id="keyNewPreview">{Key}</code>. Braces are optional.</div></div><div class="tgt-popover-field"><label for="keyNewPriority">Priority</label><div class="tgt-stepper tgt-stepper-lg"><button type="button" class="tgt-step" data-step="-1" aria-label="Lower">&minus;</button><input type="text" inputmode="numeric" id="keyNewPriority" class="tgt-priority-input" value="${maxPriority+1}"><button type="button" class="tgt-step" data-step="1" aria-label="Higher">+</button></div><div class="tgt-hint">Lower numbers are listed first in the target form.</div></div>${tgtPatternToggleHtml("keyPatternToggle")}<div class="tgt-popover-error hidden" id="keyAddError" role="alert"></div><div class="tgt-popover-actions"><button type="button" id="keyAddCancel">Cancel</button><button type="button" class="tgt-popover-confirm" id="keyAddConfirm">Add Element</button></div>`
openModal(pop)
const keyInput=pop.querySelector("#keyNewInput")
const prInput=pop.querySelector("#keyNewPriority")
keyInput.addEventListener("input",()=>{if(/^\{[^{}]*\}$/.test(keyInput.value.trim()))keyInput.value=tgtStripBraces(keyInput.value);pop.querySelector("#keyNewPreview").textContent="{"+(tgtStripBraces(keyInput.value)||"Key")+"}"})
pop.querySelectorAll(".tgt-step").forEach((b)=>b.addEventListener("click",()=>{const n=parseInt(prInput.value,10)||0;prInput.value=String(Math.max(0,Math.min(65535,n+parseInt(b.dataset.step,10))))}))
;[keyInput,prInput].forEach((el)=>el.addEventListener("keydown",(e)=>{if(e.key==="Enter"){e.preventDefault();tgtAddKey()}}))
tgtBindPatternToggle(pop.querySelector("#keyPatternToggle"))
pop.querySelector("#keyAddCancel").addEventListener("click",()=>closeModal())
pop.querySelector("#keyAddConfirm").addEventListener("click",tgtAddKey)
keyInput.focus()
}
function tgtCloseToolsMenu(){
const m=document.getElementById("tgtToolsMenu")
if(m)m.remove()
document.removeEventListener("mousedown",tgtToolsOutside,true)
document.removeEventListener("keydown",tgtToolsKeydown,true)
const btn=document.getElementById("keyToolsBtn")
if(btn){btn.classList.remove("open");btn.setAttribute("aria-expanded","false")}
}
function tgtToolsOutside(e){
const m=document.getElementById("tgtToolsMenu")
if(m&&!m.contains(e.target)&&!e.target.closest("#keyToolsBtn"))tgtCloseToolsMenu()
}
function tgtToolsKeydown(e){if(e.key==="Escape"){e.stopPropagation();tgtCloseToolsMenu()}}
function tgtToggleToolsMenu(){
if(document.getElementById("tgtToolsMenu")){tgtCloseToolsMenu();return}
const btn=document.getElementById("keyToolsBtn")
const menu=document.createElement("div")
menu.id="tgtToolsMenu"
menu.className="tgt-menu glass-panel"
menu.setAttribute("role","menu")
menu.innerHTML=`<button type="button" class="tgt-menu-item" role="menuitem" id="keyAuditBtn"><i class="icon icon-search"></i><span><b>Target Audit...</b><small>Unused elements and undefined placeholders</small></span></button><button type="button" class="tgt-menu-item" role="menuitem" id="keyMergeBtn"><i class="icon icon-link"></i><span><b>Merge Keys...</b><small>Fold several elements into one</small></span></button><div class="tgt-menu-sep"></div>${tgtPatternToggleHtml("keyPatternToggleMenu")}`
document.body.appendChild(menu)
const r=btn.getBoundingClientRect()
const w=menu.offsetWidth
menu.style.left=Math.round(Math.max(8,Math.min(r.right-w,window.innerWidth-w-8)))+"px"
menu.style.top=Math.round(r.bottom+6)+"px"
btn.classList.add("open")
btn.setAttribute("aria-expanded","true")
menu.querySelector("#keyAuditBtn").addEventListener("click",()=>{tgtCloseToolsMenu();tgtOpenAuditModal()})
menu.querySelector("#keyMergeBtn").addEventListener("click",()=>{tgtCloseToolsMenu();tgtOpenMergePopover()})
tgtBindPatternToggle(menu.querySelector("#keyPatternToggleMenu"))
setTimeout(()=>{document.addEventListener("mousedown",tgtToolsOutside,true);document.addEventListener("keydown",tgtToolsKeydown,true)},0)
}
function tgtOpenUsagePopover(key){
const pop=document.createElement("div")
pop.id="tgtPopover"
pop.className="tgt-popover glass-panel"
pop.innerHTML=`<div class="tgt-popover-title">Usage of {${tgtEscapeHtml(key)}}</div><div class="tgt-usage-list" id="tgtUsageList"><div class="tgt-empty-msg">Loading...</div></div><div class="tgt-popover-actions"><button type="button" id="tgtUsageClose">Close</button></div>`
openModal(pop)
pop.querySelector("#tgtUsageClose").addEventListener("click",tgtClosePopover)
bridgeCall("targets.key_usage",[key]).then((rows)=>{
const wrap=document.getElementById("tgtUsageList")
if(!wrap)return
if(!rows.length){wrap.innerHTML='<div class="tgt-empty-msg">Not used anywhere</div>';return}
wrap.innerHTML=rows.map((r)=>`<div class="tgt-usage-item"><div class="tgt-usage-item-note">${tgtEscapeHtml(r.note)} - ${tgtEscapeHtml(r.src)}</div><div class="tgt-usage-item-cmd">${tgtEscapeHtml(r.command)}</div></div>`).join("")
}).catch((err)=>console.error("key_usage failed",err))
}
function tgtOpenMergePopover(){
const pop=document.createElement("div")
pop.id="tgtPopover"
pop.className="tgt-popover glass-panel"
const items=tgtState.keys.map((k)=>`<label class="tgt-merge-item"><input type="checkbox" value="${tgtEscapeHtml(k.key)}"><span>${tgtEscapeHtml(k.key)}</span></label>`).join("")
pop.innerHTML=`<div class="tgt-popover-title">Merge Keys</div><div class="tgt-merge-list">${items}</div><div class="tgt-popover-field"><label>Merge into (new or existing key)</label><input type="text" id="tgtMergeTarget"></div><div class="tgt-popover-error hidden" id="tgtMergeError"></div><div class="tgt-popover-actions"><button type="button" id="tgtMergeCancel">Cancel</button><button type="button" class="tgt-popover-confirm" id="tgtMergeConfirm">Merge</button></div>`
openModal(pop)
pop.querySelector("#tgtMergeCancel").addEventListener("click",tgtClosePopover)
pop.querySelector("#tgtMergeConfirm").addEventListener("click",()=>{
const selected=Array.from(pop.querySelectorAll(".tgt-merge-item input:checked")).map((el)=>el.value)
const target=tgtStripBraces(pop.querySelector("#tgtMergeTarget").value)
const errEl=pop.querySelector("#tgtMergeError")
errEl.classList.add("hidden")
const sources=selected.filter((k)=>k.toLowerCase()!==target.toLowerCase())
if(sources.length<1||!target){errEl.textContent="Select at least one key and a target key name.";errEl.classList.remove("hidden");return}
appConfirm(`Merge ${sources.length} key(s) into ${target}? This updates commands and notes.`,{okLabel:"Merge"}).then((yes)=>{
if(!yes)return
bridgeCall("targets.bulk_rename",[sources,target]).then((msg)=>{
tgtClosePopover()
showToast(`Renamed: ${msg||target}`)
return tgtKeysChanged("merge")
}).catch((err)=>{
errEl.textContent=err&&err.message?err.message:"Merge failed"
errEl.classList.remove("hidden")
})
})
})
}
function tgtRenderAuditList(items,type){
if(!items.length)return `<div class="tgt-audit-empty">Nothing to show.</div>`
return items.map((it)=>{
const extra=type==="undefined"?` <span class="tgt-audit-count">(${it.count} use${it.count===1?"":"s"})</span>`:""
return `<label class="tgt-merge-item"><input type="checkbox" value="${tgtEscapeHtml(it.key)}"><span>${tgtEscapeHtml(it.key)}${extra}</span></label>`
}).join("")
}
function tgtRefreshAuditModal(pop){
return bridgeCall("targets.audit").then((res)=>{
pop.querySelector("#tgtAuditUnusedTitle").textContent=`Unused Keys (${res.unused.length}) - registered but never referenced`
pop.querySelector("#tgtAuditUnusedList").innerHTML=tgtRenderAuditList(res.unused,"unused")
pop.querySelector("#tgtAuditUndefinedTitle").textContent=`Undefined Placeholders (${res.undefined.length}) - used but not registered`
pop.querySelector("#tgtAuditUndefinedList").innerHTML=tgtRenderAuditList(res.undefined,"undefined")
pop.querySelector("#tgtAuditUnusedAll").checked=false
pop.querySelector("#tgtAuditUndefinedAll").checked=false
}).catch((err)=>{
const statusEl=pop.querySelector("#tgtAuditStatus")
statusEl.textContent=err&&err.message?err.message:"Failed to load audit"
statusEl.classList.add("error")
})
}
function tgtOpenAuditModal(){
const pop=document.createElement("div")
pop.id="tgtPopover"
pop.className="tgt-popover tgt-popover-wide glass-panel"
pop.innerHTML=`<div class="tgt-popover-title">Target Audit</div>
<div class="tgt-audit-section">
<div class="tgt-audit-row"><span class="tgt-audit-section-title" id="tgtAuditUnusedTitle">Unused Keys</span><label class="tgt-check"><input type="checkbox" id="tgtAuditUnusedAll"><span>Select all</span></label></div>
<div class="tgt-merge-list" id="tgtAuditUnusedList"><div class="tgt-audit-empty">Loading...</div></div>
<div class="tgt-popover-actions"><button type="button" class="tgt-popover-confirm danger" id="tgtAuditRemoveBtn">Remove Selected</button></div>
</div>
<div class="tgt-audit-section">
<div class="tgt-audit-row"><span class="tgt-audit-section-title" id="tgtAuditUndefinedTitle">Undefined Placeholders</span><label class="tgt-check"><input type="checkbox" id="tgtAuditUndefinedAll"><span>Select all</span></label></div>
<div class="tgt-merge-list" id="tgtAuditUndefinedList"><div class="tgt-audit-empty">Loading...</div></div>
<div class="tgt-popover-actions"><button type="button" class="tgt-popover-confirm" id="tgtAuditRegisterBtn">Register Selected</button></div>
</div>
<div class="tgt-audit-status" id="tgtAuditStatus"></div>
<div class="tgt-popover-actions"><button type="button" id="tgtAuditClose">Close</button></div>`
openModal(pop)
pop.querySelector("#tgtAuditClose").addEventListener("click",tgtClosePopover)
pop.querySelector("#tgtAuditUnusedAll").addEventListener("change",(e)=>{
pop.querySelectorAll("#tgtAuditUnusedList input[type=checkbox]").forEach((cb)=>{cb.checked=e.target.checked})
})
pop.querySelector("#tgtAuditUndefinedAll").addEventListener("change",(e)=>{
pop.querySelectorAll("#tgtAuditUndefinedList input[type=checkbox]").forEach((cb)=>{cb.checked=e.target.checked})
})
pop.querySelector("#tgtAuditRemoveBtn").addEventListener("click",()=>{
const selected=Array.from(pop.querySelectorAll("#tgtAuditUnusedList input:checked")).map((el)=>el.value)
if(!selected.length)return
const statusEl=pop.querySelector("#tgtAuditStatus")
statusEl.classList.remove("error")
statusEl.textContent="Removing..."
Promise.all(selected.map((key)=>bridgeCall("targets.remove_key",[key]).catch((err)=>({__error:err})))).then((results)=>{
const failed=results.filter((r)=>r&&r.__error).length
statusEl.textContent=failed?`Removed ${selected.length-failed}, ${failed} failed.`:`Removed ${selected.length} key(s).`
return Promise.all([tgtKeysChanged("remove"),tgtRefreshAuditModal(pop)])
})
})
pop.querySelector("#tgtAuditRegisterBtn").addEventListener("click",()=>{
const selected=Array.from(pop.querySelectorAll("#tgtAuditUndefinedList input:checked")).map((el)=>el.value)
if(!selected.length)return
const statusEl=pop.querySelector("#tgtAuditStatus")
statusEl.classList.remove("error")
statusEl.textContent="Registering..."
Promise.all(selected.map((key)=>bridgeCall("targets.add_key",[key,0]).catch((err)=>({__error:err})))).then((results)=>{
const failed=results.filter((r)=>r&&r.__error).length
statusEl.textContent=failed?`Registered ${selected.length-failed}, ${failed} failed.`:`Registered ${selected.length} key(s).`
return Promise.all([tgtKeysChanged("add"),tgtRefreshAuditModal(pop)])
})
})
tgtRefreshAuditModal(pop)
}
function tgtInitKeyPattern(){
bridgeCall("targets.key_pattern").then((val)=>{tgtState.keyPattern=!!val}).catch(()=>{})
}
function tgtSetChip(id,on){
const el=document.getElementById(id)
if(!el)return
el.classList.toggle("active",on)
el.setAttribute("aria-pressed",on?"true":"false")
}
function tgtSetManualOnly(val){
tgtState.manualOnly=val
if(val)tgtState.unusedOnly=false
tgtSetChip("keyManualFilter",tgtState.manualOnly)
tgtSetChip("keyUnusedFilter",tgtState.unusedOnly)
tgtRenderKeys()
}
function tgtSetUnusedOnly(val){
tgtState.unusedOnly=val
if(val)tgtState.manualOnly=false
tgtSetChip("keyManualFilter",tgtState.manualOnly)
tgtSetChip("keyUnusedFilter",tgtState.unusedOnly)
tgtRenderKeys()
}
function tgtBindSearch(id,stateKey,render){
const input=document.getElementById(id)
input.addEventListener("input",()=>{tgtState[stateKey]=input.value;tgtSyncSearchClear(id);render()})
input.addEventListener("keydown",(e)=>{if(e.key==="Escape"&&input.value){e.stopPropagation();input.value="";tgtState[stateKey]="";tgtSyncSearchClear(id);render()}})
document.querySelector(`.tgt-search-clear[data-clear="${id}"]`).addEventListener("click",()=>{input.value="";tgtState[stateKey]="";tgtSyncSearchClear(id);render();input.focus()})
}
function initTargets(){
return fetch("../pages/targets.html").then((r)=>r.text()).then((html)=>{
document.querySelector('.page[data-page="targets"]').innerHTML=html
document.querySelectorAll(".tgt-tab").forEach((t)=>t.addEventListener("click",()=>tgtSwitchTab(t.dataset.tab)))
document.getElementById("tgtNewBtn").addEventListener("click",()=>tgtOpenTargetForm(null))
document.getElementById("tgtProfileBtn").addEventListener("click",tgtOpenProfilesMenu)
tgtSyncProfileBtnLabel()
tgtBindSearch("tgtSearchInput","targetSearch",tgtRenderTargets)
tgtBindSearch("keyFilterInput","keySearch",tgtRenderKeys)
document.getElementById("keyAddBtn").addEventListener("click",tgtOpenAddKeyModal)
document.getElementById("keyToolsBtn").addEventListener("click",tgtToggleToolsMenu)
document.getElementById("keyManualFilter").addEventListener("click",()=>tgtSetManualOnly(!tgtState.manualOnly))
document.getElementById("keyUnusedFilter").addEventListener("click",()=>tgtSetUnusedOnly(!tgtState.unusedOnly))
document.getElementById("tgtEmptyMsg").addEventListener("click",(e)=>{
const b=e.target.closest("[data-empty-act]")
if(!b)return
if(b.dataset.emptyAct==="add")tgtOpenTargetForm(null)
else{const i=document.getElementById("tgtSearchInput");i.value="";tgtState.targetSearch="";tgtSyncSearchClear("tgtSearchInput");tgtRenderTargets()}
})
document.getElementById("keysEmptyMsg").addEventListener("click",(e)=>{
const b=e.target.closest("[data-empty-act]")
if(!b)return
if(b.dataset.emptyAct==="add")tgtOpenAddKeyModal()
else{const i=document.getElementById("keyFilterInput");i.value="";tgtState.keySearch="";tgtSyncSearchClear("keyFilterInput");tgtSetManualOnly(false);tgtSetUnusedOnly(false)}
})
tgtInitKeyPattern()
return tgtRefreshAll()
}).catch((err)=>console.error("targets init failed",err))
}
// T1: Mini, Recycle Bin restores, imports and command saves change targets/keys while this page is hidden.
document.addEventListener("loya:page-shown",(e)=>{
const d=e.detail||{}
if(d.page!=="targets"){tgtCloseToolsMenu();return}
if(d.first)return
tgtSyncProfileBtnLabel()
tgtRefreshAll().catch((err)=>console.error("targets refresh failed",err))
})
