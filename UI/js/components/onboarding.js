const ONBOARDING_STEPS=[
{page:"dashboard",selector:"#dashGrid",title:"Welcome to your Dashboard",body:"Customizable widgets show your notes, commands, targets, and recent activity at a glance. Click \"Edit Layout\" to rearrange or add more, or \"Layouts\" to save different setups."},
{page:"notes",selector:"#notesNewBtn",title:"Notes",body:"Add New Note to start writing. Notes support rich text, embedded command blocks, tags, attachments, and links between notes."},
{page:"reporting",selector:"#bottomNav [data-page=reporting]",title:"Reporting",body:"Write penetration-test reports from templates: findings with CVSS and CVEs, evidence saved from terminal sessions, a timeline with deadline reminders, and export to PDF, Word, HTML and more."},
{page:null,selector:"#dockTerminalBtn",title:"Terminal",body:"Enable the Terminal extension in Settings → Extensions for a built-in terminal panel with saved profiles and command history, right inside the app."},
{page:null,selector:"#aiToggleBtn",title:"AI Assistant",body:"Enable an AI provider in Settings → Extensions to get an assistant with direct access to your notes, commands, and targets."}
]
let onboardingIndex=0
function onboardingElVisible(el){
return !!el&&!!(el.offsetWidth||el.offsetHeight||el.getClientRects().length)
}
function onboardingCloseOverlay(){
const el=document.getElementById("onboardingOverlay")
if(el)el.remove()
document.removeEventListener("keydown",_onboardingKeydown,true)
const nav=document.getElementById("bottomNav")
if(nav&&nav.dataset.onboardingForced){
nav.classList.remove("expanded")
delete nav.dataset.onboardingForced
}
}
function _onboardingKeydown(e){
if(e.key==="Escape")onboardingFinish()
}
function onboardingFinish(){
onboardingCloseOverlay()
bridgeCall("onboarding.complete").catch(()=>{})
}
function onboardingRenderStep(){
onboardingCloseOverlay()
const step=ONBOARDING_STEPS[onboardingIndex]
if(!step){onboardingFinish();return}
const proceed=()=>{
const target=step.selector?document.querySelector(step.selector):null
const nav=document.getElementById("bottomNav")
if(nav&&target&&nav.contains(target)&&!nav.classList.contains("expanded")){
nav.classList.add("expanded")
nav.dataset.onboardingForced="1"
setTimeout(renderNow,340)
return
}
renderNow()
}
function renderNow(){
const target=step.selector?document.querySelector(step.selector):null
const visible=onboardingElVisible(target)
const overlay=document.createElement("div")
overlay.id="onboardingOverlay"
overlay.className="onboarding-overlay"
const tooltip=document.createElement("div")
tooltip.className="onboarding-tooltip glass-panel"+(visible?"":" onboarding-tooltip-centered")
const isLast=onboardingIndex===ONBOARDING_STEPS.length-1
tooltip.innerHTML=`<div class="onboarding-step-count">Step ${onboardingIndex+1} of ${ONBOARDING_STEPS.length}</div><div class="onboarding-title">${step.title}</div><div class="onboarding-body">${step.body}</div><div class="onboarding-actions"><button type="button" id="onboardingSkip">Skip Tour</button><button type="button" class="onboarding-next" id="onboardingNext">${isLast?"Finish":"Next"}</button></div>`
overlay.appendChild(tooltip)
if(visible){
const rect=target.getBoundingClientRect()
const ring=document.createElement("div")
ring.className="onboarding-ring"
ring.style.left=Math.round(rect.left-6)+"px"
ring.style.top=Math.round(rect.top-6)+"px"
ring.style.width=Math.round(rect.width+12)+"px"
ring.style.height=Math.round(rect.height+12)+"px"
overlay.appendChild(ring)
document.body.appendChild(overlay)
const tipH=tooltip.offsetHeight
const spaceBelow=window.innerHeight-rect.bottom
const top=spaceBelow>=tipH+14?rect.bottom+14:Math.max(14,Math.min(rect.top-tipH-14,window.innerHeight-tipH-14))
const left=Math.max(14,Math.min(rect.left,window.innerWidth-296))
tooltip.style.left=Math.round(left)+"px"
tooltip.style.top=Math.round(top)+"px"
}else{
document.body.appendChild(overlay)
}
document.getElementById("onboardingSkip").addEventListener("click",onboardingFinish)
document.getElementById("onboardingNext").addEventListener("click",()=>{
onboardingIndex++
onboardingRenderStep()
})
document.addEventListener("keydown",_onboardingKeydown,true)
}
if(step.page)goToPage(step.page).then(()=>setTimeout(proceed,150))
else proceed()
}
function startOnboardingTour(){
onboardingIndex=0
onboardingRenderStep()
}
function initOnboarding(){
bridgeCall("onboarding.status").then((st)=>{
if(!st.first_run_complete)setTimeout(startOnboardingTour,700)
}).catch(()=>{})
}
