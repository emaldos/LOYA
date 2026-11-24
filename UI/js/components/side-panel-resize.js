function initSidePanelResize(opts){
const handle=opts.handle
const panel=opts.panel
const onCommit=opts.onCommit||function(){}
const config=opts.config||function(){return opts}
let resizing=false
let anchor=0
let base=0
let axis="x"
let sign=-1
let min=260
let max=900
handle.addEventListener("mousedown",(e)=>{
const c=config()||{}
axis=c.axis==="y"?"y":"x"
sign=(c.anchorSide==="left"||c.anchorSide==="top")?1:-1
min=c.min||260
max=c.max||900
anchor=axis==="y"?e.screenY:e.screenX
const box=panel.getBoundingClientRect()
base=axis==="y"?box.height:box.width
resizing=true
e.preventDefault()
})
window.addEventListener("mousemove",(e)=>{
if(!resizing)return
const delta=((axis==="y"?e.screenY:e.screenX)-anchor)*sign
const size=Math.max(min,Math.min(max,base+delta))
panel.style[axis==="y"?"height":"width"]=size+"px"
})
window.addEventListener("mouseup",()=>{
if(!resizing)return
resizing=false
const box=panel.getBoundingClientRect()
onCommit(Math.round(axis==="y"?box.height:box.width),axis)
})
}
