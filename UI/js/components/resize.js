function initResizeHandle(el,dirs){
if(!el)return
let resizing=false
// pressed: the button is still down. A fast click releases it before window.bounds answers; without this the late answer turned
// resizing on with no button held and every later mouse move resized the window.
let pressed=false
let anchorX=0
let anchorY=0
let baseX=0
let baseY=0
let baseW=0
let baseH=0
const MIN_W=460
const MIN_H=380
el.addEventListener("mousedown",(e)=>{
resizing=false
pressed=true
anchorX=e.screenX
anchorY=e.screenY
bridgeCall("window.bounds").then((b)=>{
baseX=b.x
baseY=b.y
baseW=b.w
baseH=b.h
resizing=pressed
}).catch(()=>{resizing=false})
e.preventDefault()
e.stopPropagation()
})
window.addEventListener("mousemove",(e)=>{
if(!resizing)return
if(e.buttons===0){resizing=false;pressed=false;return}
const dx=e.screenX-anchorX
const dy=e.screenY-anchorY
let x=baseX,y=baseY,w=baseW,h=baseH
if(dirs.e)w=Math.max(MIN_W,baseW+dx)
if(dirs.w){w=Math.max(MIN_W,baseW-dx);x=baseX+(baseW-w)}
if(dirs.s)h=Math.max(MIN_H,baseH+dy)
if(dirs.n){h=Math.max(MIN_H,baseH-dy);y=baseY+(baseH-h)}
bridgeCall("window.set_bounds",[x,y,w,h])
})
const stop=()=>{resizing=false;pressed=false}
window.addEventListener("mouseup",stop)
window.addEventListener("blur",stop)
}
function initResize(){
initResizeHandle(document.getElementById("resizeN"),{n:true})
initResizeHandle(document.getElementById("resizeS"),{s:true})
initResizeHandle(document.getElementById("resizeW"),{w:true})
initResizeHandle(document.getElementById("resizeE"),{e:true})
initResizeHandle(document.getElementById("resizeNW"),{n:true,w:true})
initResizeHandle(document.getElementById("resizeNE"),{n:true,e:true})
initResizeHandle(document.getElementById("resizeSW"),{s:true,w:true})
initResizeHandle(document.getElementById("resizeSE"),{s:true,e:true})
}

if(typeof module!=="undefined"&&module.exports)module.exports={initResizeHandle}
