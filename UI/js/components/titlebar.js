function initTitleBar(){
const bar=document.getElementById("titlebar")
const btnShrink=document.getElementById("btnShrink")
const btnMin=document.getElementById("btnMin")
const btnMax=document.getElementById("btnMax")
const btnMaxIcon=document.getElementById("btnMaxIcon")
const btnClose=document.getElementById("btnClose")
const DRAG_THRESHOLD=4
let dragging=false
let pendingDrag=false
let maximized=false
let dragAnchorX=0
let dragAnchorY=0
function setMaximizedIcon(isMax){
document.documentElement.classList.toggle("window-maximized",!!isMax)
btnMaxIcon.classList.toggle("icon-maximize",!isMax)
btnMaxIcon.classList.toggle("icon-restore",isMax)
btnMax.title=isMax?"Restore":"Maximize"
}
function toggleMaximize(){
bridgeCall("window.toggle_maximize").then((isMax)=>{
maximized=isMax
setMaximizedIcon(isMax)
})
}
bar.addEventListener("mousedown",(e)=>{
if(e.target.closest("button"))return
dragAnchorX=e.clientX
dragAnchorY=e.clientY
pendingDrag=true
dragging=!maximized
e.preventDefault()
})
window.addEventListener("mousemove",(e)=>{
if(!pendingDrag)return
if(maximized){
if(Math.abs(e.clientX-dragAnchorX)<DRAG_THRESHOLD&&Math.abs(e.clientY-dragAnchorY)<DRAG_THRESHOLD)return
pendingDrag=false
const ratio=Math.min(Math.max(e.clientX/window.innerWidth,0),1)
bridgeCall("window.restore_for_drag",[e.screenX,e.screenY,ratio]).then((res)=>{
if(!res)return
maximized=false
setMaximizedIcon(false)
dragAnchorX=e.clientX
dragAnchorY=e.clientY
dragging=true
})
return
}
if(!dragging)return
bridgeCall("window.drag_to",[e.screenX-dragAnchorX,e.screenY-dragAnchorY])
})
window.addEventListener("mouseup",()=>{dragging=false;pendingDrag=false})
bar.addEventListener("dblclick",(e)=>{
if(e.target.closest("button"))return
toggleMaximize()
})
btnShrink.addEventListener("click",()=>bridgeCall("window.shrink"))
btnMin.addEventListener("click",()=>bridgeCall("window.minimize"))
btnMax.addEventListener("click",toggleMaximize)
btnClose.addEventListener("click",()=>bridgeCall("window.close"))
bridgeCall("window.is_maximized").then((isMax)=>{
maximized=!!isMax
setMaximizedIcon(maximized)
}).catch(()=>{})
// Rounded corners (Linux with a compositor): the page clips itself to a rounded rect unless maximized (base.css html.window-rounded).
bridgeCall("window.chrome").then((c)=>{document.documentElement.classList.toggle("window-rounded",!!(c&&c.rounded))}).catch(()=>{})
// A maximize the app did not start (WM shortcut, double-click on a tiling edge) arrives as a resize: re-read the state then.
let maxCheckTimer=null
window.addEventListener("resize",()=>{
clearTimeout(maxCheckTimer)
maxCheckTimer=setTimeout(()=>{
bridgeCall("window.is_maximized").then((isMax)=>{
if(!!isMax===maximized)return
maximized=!!isMax
setMaximizedIcon(maximized)
}).catch(()=>{})
},150)
})
}
