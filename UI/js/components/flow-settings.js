// Settings > Extensions > "Chain diagrams": how the scripts of a chain diagram may run on this computer.
// flowSettingsMount(host) renders the block into the container that pages/settings.js hands over. The policy lives in
// the bridge (flows.policy_get / flows.policy_set); nothing is kept in the page. The pure parts are exported for tests.
const FLOW_ISOLATION_CHOICES=[
{id:"sandboxed",label:"Sandboxed only",text:"Scripts run only inside a sandbox. On a system without one, a diagram that has scripts does not run."},
{id:"allow",label:"Allow unsandboxed scripts",text:"Where there is no sandbox, scripts run with no isolation, as your user. Never applies to AI-made or unreviewed diagrams."}
]
function flowSettingsEscape(value){
return String(value===undefined||value===null?"":value).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")
}
// What flows.policy_get returned -> what the block shows.
function flowSettingsModel(policy){
const p=policy&&typeof policy==="object"?policy:{}
const box=p.sandbox&&typeof p.sandbox==="object"?p.sandbox:{}
const kind=String(box.sandbox||"none")
const has=kind!=="none"&&kind!==""
return {mode:p.script_isolation==="allow"?"allow":"sandboxed",hasSandbox:has,sandbox:has?kind:"none",
detected:has?(kind==="bwrap"?"bubblewrap":kind)+" is available on this system: scripts run inside it"+(box.network_isolation?", without network access unless a script node turns it on.":"."):"No sandbox on this system: scripts can only run unsandboxed, with network access."}
}
function flowSettingsHtml(model){
const m=model||flowSettingsModel(null)
return '<div class="set-box-title">Chain diagrams</div><p class="set-info">A chain diagram can contain Script nodes (Python, Bash, PowerShell). This decides whether they may run when this computer cannot isolate them. A single diagram can override it in its own Settings.</p>'+
'<div class="flow-set-choices" role="radiogroup" aria-label="Script isolation">'+FLOW_ISOLATION_CHOICES.map((c)=>'<label class="flow-set-choice'+(m.mode===c.id?" active":"")+'"><input type="radio" name="flowSetIsolation" value="'+c.id+'"'+(m.mode===c.id?" checked":"")+'><span class="flow-set-choice-main"><span class="flow-set-choice-label">'+flowSettingsEscape(c.label)+'</span><span class="flow-set-choice-text">'+flowSettingsEscape(c.text)+"</span></span></label>").join("")+"</div>"+
'<p class="set-info flow-set-detected '+(m.hasSandbox?"is-ok":"is-none")+'">'+flowSettingsEscape(m.detected)+'</p><div class="set-status" id="flowSetStatus"></div>'
}
function flowSettingsMount(host){
if(!host)return Promise.resolve(false)
const show=(policy)=>{
host.innerHTML=flowSettingsHtml(flowSettingsModel(policy))
host.classList.remove("hidden")
host.querySelectorAll('input[name="flowSetIsolation"]').forEach((input)=>input.addEventListener("change",()=>{
if(!input.checked)return
const status=host.querySelector("#flowSetStatus")
bridgeCall("flows.policy_set",[{script_isolation:input.value}]).then((res)=>{
show(res&&typeof res==="object"&&res.script_isolation?res:Object.assign({},policy,{script_isolation:input.value}))
const again=host.querySelector("#flowSetStatus")
if(again)again.textContent=input.value==="allow"?"Saved. Unsandboxed scripts are allowed where there is no sandbox.":"Saved. Scripts need a sandbox."
}).catch((err)=>{show(policy);const again=host.querySelector("#flowSetStatus")||status;if(again)again.textContent=err&&err.message?err.message:"Could not save the setting"})
}))
return true
}
// An older bridge without the policy: the block stays hidden instead of showing a setting that does nothing.
return bridgeCall("flows.policy_get").then(show).catch(()=>{host.classList.add("hidden");return false})
}
if(typeof module!=="undefined"&&module.exports)module.exports={FLOW_ISOLATION_CHOICES,flowSettingsModel,flowSettingsHtml,flowSettingsMount}
