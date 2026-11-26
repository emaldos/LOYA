const AI_PROVIDER_STATE_GROUPS=[{state:"ready",label:"Connected"},{state:"available",label:"Available"},{state:"setup",label:"Not set up"}]
const AI_PROVIDER_CATEGORY_ORDER={cli:0,agent:1,api:2,local:3}
const AI_PROVIDER_CATEGORY_TAG={cli:"your CLI",agent:"agent",api:"",local:"local"}
function aiProviderOptionText(entry){
const tag=AI_PROVIDER_CATEGORY_TAG[entry.category]||""
const name=tag?entry.label+" ("+tag+")":entry.label
return entry.state!=="ready"&&entry.reason?name+" - "+entry.reason:name
}
function aiProviderGroups(entries){
const known=(entries||[]).filter((entry)=>entry&&entry.kind&&AI_PROVIDER_STATE_GROUPS.some((group)=>group.state===entry.state))
const seen=new Set()
const unique=known.filter((entry)=>{if(seen.has(entry.kind))return false;seen.add(entry.kind);return true})
const rank=(entry)=>Object.prototype.hasOwnProperty.call(AI_PROVIDER_CATEGORY_ORDER,entry.category)?AI_PROVIDER_CATEGORY_ORDER[entry.category]:9
return AI_PROVIDER_STATE_GROUPS.map((group)=>{
const options=unique.map((entry,index)=>({entry,index})).filter((item)=>item.entry.state===group.state).sort((a,b)=>rank(a.entry)-rank(b.entry)||a.index-b.index).map((item)=>({kind:item.entry.kind,text:aiProviderOptionText(item.entry),state:item.entry.state,category:item.entry.category}))
return {label:group.label,state:group.state,options}
}).filter((group)=>group.options.length)
}
function aiPickProvider(groups,current,preferred,pickedByUser){
const options=[].concat(...(groups||[]).map((group)=>group.options))
const find=(kind)=>options.find((option)=>option.kind===kind)
if(pickedByUser&&current&&find(current))return current
if(preferred&&find(preferred)&&find(preferred).state==="ready")return preferred
if(current&&find(current)&&find(current).state==="ready")return current
const firstReady=options.find((option)=>option.state==="ready")
if(firstReady)return firstReady.kind
if(current&&find(current))return current
return options.length?options[0].kind:""
}
const AI_PROVIDER_SETTINGS_TARGET={api:'.ai-provider-box[data-provider="api"]',ollama:'.ai-provider-box[data-provider="ollama"]',lmstudio:'.ai-provider-box[data-provider="lmstudio"]'}
function aiProviderEntries(){
return (aiState.catalog||[]).concat(typeof cliProviderEntries==="function"?cliProviderEntries():[])
}
function aiProviderEntryFor(kind){
return aiProviderEntries().find((entry)=>entry.kind===kind)||null
}
function aiSelectedUnready(){
const kind=aiState.selectedKind
if(!kind||(typeof cliIsEntryKind==="function"&&cliIsEntryKind(kind)))return null
const entry=aiProviderEntryFor(kind)
return entry&&entry.state!=="ready"?entry:null
}
function aiSetupGoToSettings(kind){
const go=typeof goToPage==="function"?goToPage("settings"):Promise.resolve()
return Promise.resolve(go).then(()=>{if(typeof setSwitchTab==="function")setSwitchTab("ai","agents")}).then(()=>{
const target=AI_PROVIDER_SETTINGS_TARGET[kind]?document.querySelector(AI_PROVIDER_SETTINGS_TARGET[kind]):document.getElementById("setExtAgentsRoot")
if(target&&target.scrollIntoView)target.scrollIntoView({block:"start"})
})
}
function aiSetupRenderIfSelected(wrap){
const entry=aiSelectedUnready()
if(!entry)return false
const panel=document.getElementById("aiPanelBody")
if(panel)panel.classList.add("ai-cli-mode")
const escape=typeof aiEscapeHtml==="function"?aiEscapeHtml:(text)=>String(text)
const stateText=entry.state==="available"?"Available":"Not set up"
const why=entry.reason?entry.reason.charAt(0).toUpperCase()+entry.reason.slice(1)+".":""
wrap.innerHTML=`<div class="ai-cli-entry" data-kind="${escape(entry.kind)}">
<div class="ai-cli-head"><i class="icon icon-brain"></i><span class="ai-cli-title">${escape(aiProviderOptionText({label:entry.label,category:entry.category,state:"ready"}))}</span><span class="ai-status-pill ${entry.state==="available"?"":"offline"}">${escape(stateText)}</span></div>
<p class="ai-cli-help">${escape(why)} Finish setting it up in Settings > AI > Agents to chat with it here, or pick a connected provider from the list.</p>
<div class="ai-cli-actions"><button type="button" class="set-btn primary ai-setup-open">Open AI settings</button></div>
</div>`
const button=wrap.querySelector(".ai-setup-open")
if(button)button.addEventListener("click",()=>aiSetupGoToSettings(entry.kind))
return true
}
function aiRefuseUnready(){
const entry=aiSelectedUnready()
if(!entry)return false
if(typeof showStatusIsland==="function")showStatusIsland(entry.label+" is not set up yet. Open Settings > AI > Agents, or pick a connected provider.","error")
return true
}
function aiRenderProviderSelect(){
const select=document.getElementById("aiProviderSelect")
if(!select)return false
const groups=aiProviderGroups(aiProviderEntries())
select.innerHTML=""
if(!groups.length){
const option=document.createElement("option")
option.value=""
option.textContent="No providers available"
select.appendChild(option)
select.disabled=true
const changed=aiState.selectedKind!==""
aiState.selectedKind=""
return changed
}
select.disabled=false
groups.forEach((group)=>{
const optgroup=document.createElement("optgroup")
optgroup.label=group.label
group.options.forEach((item)=>{const option=document.createElement("option");option.value=item.kind;option.textContent=item.text;optgroup.appendChild(option)})
select.appendChild(optgroup)
})
const pick=aiPickProvider(groups,aiState.selectedKind,aiState.defaultKind,aiState.kindPickedByUser)
const changed=pick!==aiState.selectedKind
select.value=pick
aiState.selectedKind=pick
return changed
}
function aiRefreshProviderSelect(){
if(!aiState.catalogLoaded)return
if(aiRenderProviderSelect()&&typeof aiOnProviderSelected==="function")aiOnProviderSelected()
}
