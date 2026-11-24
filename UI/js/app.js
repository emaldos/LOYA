const PAGE_LOADERS={dashboard:initDashboard,notes:initNotes,reporting:initReporting,commands:initCommands,chains:initChains,cve:initCve,targets:initTargets,snippets:initSnippets,settings:initSettings}
const pagesLoaded={}
const pageReady={}
let idleState={lastActivity:Date.now(),autoLockMinutes:0,locked:false}
function idleResetActivity(){
if(!idleState.locked)idleState.lastActivity=Date.now()
}
function idleRefreshSetting(){
return bridgeCall("security.status").then((st)=>{idleState.autoLockMinutes=st.auto_lock_minutes||0}).catch(()=>{})
}
function idleCheckTick(){
if(!idleState.autoLockMinutes||idleState.locked)return
const elapsedMin=(Date.now()-idleState.lastActivity)/60000
if(elapsedMin>=idleState.autoLockMinutes){
idleState.locked=true
// lock returns false when no PIN is set (nothing to lock with); if the call itself fails, lock the UI anyway.
bridgeCall("security.lock",["idle"]).then((locked)=>{
if(locked===false){idleState.locked=false;idleResetActivity();return}
showLockScreen(idleOnUnlocked)
}).catch(()=>showLockScreen(idleOnUnlocked))
}
}
function idleOnUnlocked(){
idleState.locked=false
idleResetActivity()
// Calls made while locked were refused, so let the visible page reload its data.
const active=document.querySelector(".page.active")
if(active&&active.dataset.page)document.dispatchEvent(new CustomEvent("loya:page-shown",{detail:{page:active.dataset.page,first:false}}))
}
function initAutoLock(){
idleRefreshSetting()
document.addEventListener("mousemove",idleResetActivity,{passive:true})
document.addEventListener("keydown",idleResetActivity,{passive:true})
document.addEventListener("mousedown",idleResetActivity,{passive:true})
setInterval(idleCheckTick,15000)
}
function ensurePageLoaded(key){
if(pagesLoaded[key])return pageReady[key]||Promise.resolve()
if(!PAGE_LOADERS[key])return Promise.resolve()
pagesLoaded[key]=true
pageReady[key]=Promise.resolve(PAGE_LOADERS[key]())
return pageReady[key]
}
function goToPage(key){
document.querySelectorAll(".nav-btn[data-page]").forEach((btn)=>btn.classList.toggle("active",btn.dataset.page===key))
document.querySelectorAll(".page").forEach((page)=>page.classList.toggle("active",page.dataset.page===key))
// Pages init once; they subscribe to "loya:page-shown" (detail.page, detail.first) to reload data that changed while they were hidden.
const first=!pagesLoaded[key]
return Promise.resolve(ensurePageLoaded(key)).then((r)=>{document.dispatchEvent(new CustomEvent("loya:page-shown",{detail:{page:key,first}}));return r})
}
function initTitlebarVersion(){
bridgeCall("update.status").then((st)=>{
const el=document.getElementById("titlebarVersion")
if(el&&st&&st.current_version)el.textContent="v"+st.current_version
}).catch(()=>{})
}
function initTitlebarSearch(){
const btn=document.getElementById("titlebarSearchBtn")
const label=document.getElementById("titlebarSearchLabel")
bridgeCall("search.recent_queries").then((rows)=>{
if(rows&&rows.length)label.textContent=rows[0]
}).catch(()=>{})
btn.addEventListener("click",()=>{
paletteToggle()
const q=label.textContent
if(q&&q!=="Search..."){
const input=document.getElementById("paletteInput")
if(input){input.value=q;input.dispatchEvent(new Event("input"))}
}
})
}
function forceFirstFullRepaint(){
const root=document.documentElement
const nudge=()=>{
root.style.opacity="0.999"
requestAnimationFrame(()=>{root.style.opacity=""})
}
[120,600,1400].forEach((delay)=>setTimeout(nudge,delay))
}
function boot(){
forceFirstFullRepaint()
initTitleBar()
initTitlebarVersion()
initTitlebarSearch()
initNav()
initResize()
initTheme()
initTerminal()
initAI()
initPalette()
initUiSelects()
initAutoLock()
initShortcuts()
initToastHistory()
initFocusMode()
bridgeCall("security.needs_unlock").then((needed)=>{
if(needed)showLockScreen(()=>{goToPage("dashboard");initOnboarding()})
else{goToPage("dashboard");initOnboarding()}
}).catch(()=>showLockScreen(()=>{goToPage("dashboard");initOnboarding()}))
bridgeCall("ping").then((res)=>console.log("bridge ready",res)).catch((err)=>console.error("bridge ping failed",err))
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",boot)
else boot()
