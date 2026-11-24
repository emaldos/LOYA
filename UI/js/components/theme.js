let themeState={mode:"dark",theme:"dark"}
function themeResolveSystem(){
return window.matchMedia&&window.matchMedia("(prefers-color-scheme: light)").matches?"light":"dark"
}
function applyThemeState(state){
themeState=state
const resolved=state.mode==="system"?themeResolveSystem():state.theme
document.documentElement.dataset.theme=resolved
return state
}
function themeHexToRgb(hex){
const m=/^#?([0-9a-f]{6})$/i.exec((hex||"").trim())
if(!m)return {r:59,g:130,b:246}
const n=parseInt(m[1],16)
return {r:(n>>16)&255,g:(n>>8)&255,b:n&255}
}
function applyAccentState(accent){
const root=document.documentElement
root.style.setProperty("--accent-a",accent.a)
root.style.setProperty("--accent-b",accent.b)
const rgbA=themeHexToRgb(accent.a)
const rgbB=themeHexToRgb(accent.b)
const alpha=document.documentElement.dataset.theme==="light"?"0.15":"0.20"
root.style.setProperty("--accent-a-soft",`rgba(${rgbA.r},${rgbA.g},${rgbA.b},${alpha})`)
root.style.setProperty("--accent-b-soft",`rgba(${rgbB.r},${rgbB.g},${rgbB.b},${alpha})`)
return accent
}
// Appearance style ("glass" default, "classic") is independent of the colour theme; glass.css keys every rule off html[data-style="glass"].
function applyStyleState(state){
const style=state&&(state.style==="classic"||state.style==="glass")?state.style:"glass"
document.documentElement.dataset.style=style
return state
}
function themeApplyAll(){
return bridgeCall("theme.get").then(applyThemeState).then(()=>bridgeCall("theme.accent")).then(applyAccentState).then(()=>bridgeCall("theme.style")).then(applyStyleState)
}
function initTheme(){
themeApplyAll().catch((err)=>console.error("theme.get failed",err))
window.__toggleTheme=function(){return bridgeCall("theme.toggle").then(themeApplyAll)}
if(window.matchMedia){
window.matchMedia("(prefers-color-scheme: light)").addEventListener("change",()=>{
if(themeState.mode==="system"){
document.documentElement.dataset.theme=themeResolveSystem()
bridgeCall("theme.accent").then(applyAccentState).catch(()=>{})
}
})
}
}
