// Title-bar live-target badge: shown only while a target is live (green dot + name). Clicking it opens a card with
// the target's details and an Edit button that opens the same form as the Targets page.
const LIVE_BADGE_SECRET_RX=/pass|secret|token|hash|key|cred|cookie|session|private|otp|pin/i
const liveBadge={target:null,profile:"",timer:null}
function liveBadgeEsc(s){return String(s===undefined||s===null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")}
// Pure: the live target out of targets.targets(), or null.
function liveBadgePick(targets){return (targets||[]).find((t)=>String(t.status||"").toLowerCase()==="live")||null}
function liveBadgeIsSecret(key){return LIVE_BADGE_SECRET_RX.test(String(key||""))}
const LIVE_BADGE_ENGAGEMENT={not_started:"Not started",in_progress:"In progress",compromised:"Compromised",reported:"Reported"}
function liveBadgeRefresh(){
return Promise.all([bridgeCall("targets.targets"),bridgeCall("targets.list_profiles").catch(()=>[])]).then(([targets,profiles])=>{
liveBadge.target=liveBadgePick(targets)
const active=(profiles||[]).find((p)=>p.active)
liveBadge.profile=active?active.name:""
liveBadgeRender()
const card=document.getElementById("liveTargetCard")
if(card)liveBadgeFillCard(card)
}).catch(()=>{})
}
function liveBadgeRender(){
const btn=document.getElementById("titlebarLive")
if(!btn)return
const t=liveBadge.target
btn.classList.toggle("hidden",!t)
if(!t){liveBadgeClose();return}
document.getElementById("titlebarLiveName").textContent=t.name
// GTK keeps a native tooltip on screen after the click, over the open card: no title while the card is open.
btn.dataset.tip=`Live target: ${t.name}${liveBadge.profile?" ("+liveBadge.profile+")":""} - click for details`
if(btn.getAttribute("aria-expanded")!=="true")btn.title=btn.dataset.tip
}
function liveBadgeClose(){
const card=document.getElementById("liveTargetCard")
if(card)card.remove()
document.removeEventListener("mousedown",liveBadgeOutside,true)
document.removeEventListener("keydown",liveBadgeKey,true)
const btn=document.getElementById("titlebarLive")
if(btn){btn.setAttribute("aria-expanded","false");if(btn.dataset.tip)btn.title=btn.dataset.tip}
}
function liveBadgeOutside(e){
const card=document.getElementById("liveTargetCard"),btn=document.getElementById("titlebarLive")
if(card&&!card.contains(e.target)&&!(btn&&btn.contains(e.target)))liveBadgeClose()
}
function liveBadgeKey(e){if(e.key==="Escape"){e.stopPropagation();liveBadgeClose();const b=document.getElementById("titlebarLive");if(b)b.focus()}}
// Pure: [key,value] pairs that match the search. Secret values are never searched, only their key names.
function liveBadgeFilter(vals,query){
const q=String(query||"").trim().toLowerCase()
if(!q)return vals.map((pair,i)=>({pair,i}))
return vals.map((pair,i)=>({pair,i})).filter(({pair})=>String(pair[0]).toLowerCase().includes(q)||(!liveBadgeIsSecret(pair[0])&&String(pair[1]).toLowerCase().includes(q)))
}
function liveBadgeRowHtml(k,v,i){
const secret=liveBadgeIsSecret(k)
return `<li class="live-card-row"><span class="live-card-key" title="{${liveBadgeEsc(k)}}">{${liveBadgeEsc(k)}}</span><span class="live-card-val mono${secret?" masked":""}" data-i="${i}" title="${secret?"Hidden - click the eye to show":liveBadgeEsc(v)}">${secret?"&bull;&bull;&bull;&bull;&bull;&bull;&bull;&bull;":liveBadgeEsc(v)}</span>${secret?`<button type="button" class="live-card-icon" data-act="reveal" data-i="${i}" title="Show"><i class="icon icon-search"></i></button>`:""}<button type="button" class="live-card-icon" data-act="copy" data-i="${i}" title="Copy {${liveBadgeEsc(k)}}"><i class="icon icon-copy"></i></button></li>`
}
// Re-renders only the value grid, so typing in the search box keeps focus across the periodic refresh.
function liveBadgeRenderList(card){
const host=card.querySelector(".live-card-body"),count=card.querySelector(".live-card-count")
if(!host)return
const vals=card._vals||[]
const input=card.querySelector(".live-card-search input")
const hits=liveBadgeFilter(vals,input?input.value:"")
if(!vals.length)host.innerHTML=`<div class="live-card-empty">This target has no values yet. Use Edit to add {IPv4}, {Domain} and the other elements your commands use.</div>`
else if(!hits.length)host.innerHTML=`<div class="live-card-empty">No value matches your search.</div>`
else host.innerHTML=`<ul class="live-card-list">${hits.map(({pair,i})=>liveBadgeRowHtml(pair[0],pair[1],i)).join("")}</ul>`
if(count)count.textContent=input&&input.value.trim()?`${hits.length} of ${vals.length}`:""
}
function liveBadgeFillCard(card){
const t=liveBadge.target
if(!t){liveBadgeClose();return}
const vals=Object.entries(t.values||{}).filter(([,v])=>String(v||"").trim())
const eng=String(t.engagement_status||"not_started").toLowerCase()
card._vals=vals
const head=`<div class="live-card-head"><span class="live-card-dot"></span><div class="live-card-title"><div class="live-card-name">${liveBadgeEsc(t.name)}</div><div class="live-card-sub">${liveBadge.profile?liveBadgeEsc(liveBadge.profile)+" &middot; ":""}${vals.length} value${vals.length===1?"":"s"}</div></div><span class="live-card-eng eng-${liveBadgeEsc(eng)}">${liveBadgeEsc(LIVE_BADGE_ENGAGEMENT[eng]||eng)}</span></div>`
if(!card.querySelector(".live-card-body")||card._targetId!==t.id){
card._targetId=t.id
card.innerHTML=`<div class="live-card-headwrap">${head}</div>
<label class="live-card-search"><i class="icon icon-search"></i><input type="text" placeholder="Search values (e.g. IPv4, domain, user)" aria-label="Search the live target's values" spellcheck="false" autocomplete="off"><span class="live-card-count"></span></label>
<div class="live-card-body"></div>
<div class="live-card-actions"><button type="button" class="live-card-btn" data-act="targets"><i class="icon icon-target"></i><span>All targets</span></button><button type="button" class="live-card-btn primary" data-act="edit"><i class="icon icon-edit"></i><span>Edit</span></button></div>`
const input=card.querySelector(".live-card-search input")
input.addEventListener("input",()=>liveBadgeRenderList(card))
input.addEventListener("keydown",(e)=>{if(e.key==="Escape"&&input.value){e.stopPropagation();input.value="";liveBadgeRenderList(card)}})
}else{
card.querySelector(".live-card-headwrap").innerHTML=head
}
liveBadgeRenderList(card)
}
function liveBadgeOpen(){
if(document.getElementById("liveTargetCard")){liveBadgeClose();return}
const btn=document.getElementById("titlebarLive")
if(!btn||!liveBadge.target)return
const card=document.createElement("div")
card.id="liveTargetCard"
card.className="live-target-card glass-panel"
card.setAttribute("role","dialog")
card.setAttribute("aria-label","Live target details")
liveBadgeFillCard(card)
document.body.appendChild(card)
const r=btn.getBoundingClientRect()
card.style.left=Math.round(Math.max(8,Math.min(r.left,window.innerWidth-card.offsetWidth-8)))+"px"
card.style.top=Math.round(r.bottom+8)+"px"
btn.setAttribute("aria-expanded","true")
btn.removeAttribute("title")
const search=card.querySelector(".live-card-search input");if(search&&(card._vals||[]).length>6)search.focus()
card.addEventListener("click",(e)=>{
const b=e.target.closest("[data-act]")
if(!b)return
const act=b.dataset.act,i=Number(b.dataset.i),pair=(card._vals||[])[i]
if(act==="copy"&&pair){if(navigator.clipboard)navigator.clipboard.writeText(pair[1]).then(()=>showToast("Copied {"+pair[0]+"}")).catch(()=>showToast("Copy failed","error"));return}
if(act==="reveal"&&pair){const v=card.querySelector(`.live-card-val[data-i="${i}"]`);if(v){const shown=!v.classList.contains("masked");v.textContent=shown?"•".repeat(8):pair[1];v.classList.toggle("masked",shown)}return}
if(act==="edit"||act==="targets"){
const id=liveBadge.target&&liveBadge.target.id
liveBadgeClose()
Promise.resolve(goToPage("targets")).then(()=>{
if(typeof tgtSwitchTab==="function")tgtSwitchTab("targets")
if(act!=="edit")return
const run=()=>{const t=(typeof tgtState!=="undefined"&&tgtState.targets||[]).find((x)=>x.id===id);if(t&&typeof tgtOpenTargetForm==="function")tgtOpenTargetForm(t);else showToast("Open the target from the Targets list","info")}
if(typeof tgtRefreshTargets==="function")Promise.resolve(tgtRefreshTargets()).then(run,run);else setTimeout(run,300)
})
}
})
document.addEventListener("mousedown",liveBadgeOutside,true)
document.addEventListener("keydown",liveBadgeKey,true)
}
function initLiveTargetBadge(){
const btn=document.getElementById("titlebarLive")
if(!btn)return
btn.addEventListener("click",liveBadgeOpen)
// Refresh whenever the live target can have changed: picker/dashboard/targets events, page switches, window focus, and slowly while visible.
document.addEventListener("loya:live-target-changed",liveBadgeRefresh)
document.addEventListener("loya:page-shown",liveBadgeRefresh)
document.addEventListener("loya:target-keys-changed",liveBadgeRefresh)
window.addEventListener("focus",liveBadgeRefresh)
liveBadge.timer=setInterval(()=>{if(!document.hidden)liveBadgeRefresh()},15000)
liveBadgeRefresh()
}
if(typeof document!=="undefined"){if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",initLiveTargetBadge);else initLiveTargetBadge()}
if(typeof module!=="undefined"&&module.exports)module.exports={liveBadgePick,liveBadgeIsSecret,liveBadgeEsc,liveBadgeFilter,liveBadgeRender,liveBadgeClose,liveBadge}
