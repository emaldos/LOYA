// Drag-to-dock for the side panels (Terminal and AI) plus the small pure helpers behind it: drop-zone geometry and
// hit-testing, panel size clamping, the "bottom is exclusive" rule between the two panels, and the toolbar overflow
// partition used by narrow panel headers. The pure helpers are exported for the Node tests (tests/js/panel_dock.js).
//
// Docking rules for Terminal + AI together (one place, used by drag-and-drop and by the panel-position menus):
//  - Left / right: both panels may share a side. They sit side by side: the AI panel is the outer one (window edge),
//    the terminal is the inner one (next to the page), because the terminal lives inside the work area.
//  - Bottom is exclusive: when one panel is docked to the bottom while the other one is already there, the other one
//    swaps to the moving panel's previous side, so two short panels never stack and squeeze the page away.
const PANEL_DOCK_MODES=["left","right","bottom"]
const PANEL_DOCK_MIN_SIDE=320
const PANEL_DOCK_MIN_BOTTOM=180
const PANEL_DOCK_MAX_SIDE=900
const PANEL_DOCK_DEFAULT_SIDE=380
const PANEL_DOCK_DEFAULT_BOTTOM=320
const PANEL_DOCK_DRAG_THRESHOLD=6
function panelDockNormalizeMode(mode,fallback){
return PANEL_DOCK_MODES.indexOf(mode)>=0?mode:(fallback||"right")
}
// Width (left/right) or height (bottom) a docked panel may have in a viewport of the given size. A saved size below
// the minimum (older builds allowed 260 x 160) is lifted to the minimum; garbage falls back to the default.
function panelDockClampSize(mode,size,viewport){
const vw=viewport&&viewport.width>0?viewport.width:1920
const vh=viewport&&viewport.height>0?viewport.height:1080
let n=Number(size)
if(mode==="bottom"){
if(!isFinite(n)||n<=0)n=PANEL_DOCK_DEFAULT_BOTTOM
const max=Math.max(PANEL_DOCK_MIN_BOTTOM,Math.round(vh*0.85))
return Math.round(Math.max(PANEL_DOCK_MIN_BOTTOM,Math.min(max,n)))
}
if(!isFinite(n)||n<=0)n=PANEL_DOCK_DEFAULT_SIDE
const max=Math.max(PANEL_DOCK_MIN_SIDE,Math.min(PANEL_DOCK_MAX_SIDE,Math.round(vw*0.75)))
return Math.round(Math.max(PANEL_DOCK_MIN_SIDE,Math.min(max,n)))
}
// Drop zones over an area rect {left,top,width,height}: full-height bands at the left and right edges and a band along
// the bottom edge between them, so the zones never overlap and a point is in at most one.
function panelDockZones(area){
const bandX=Math.round(Math.max(64,Math.min(area.width*0.2,180)))
const bandY=Math.round(Math.max(56,Math.min(area.height*0.24,160)))
return {
left:{left:area.left,top:area.top,width:bandX,height:area.height},
right:{left:area.left+area.width-bandX,top:area.top,width:bandX,height:area.height},
bottom:{left:area.left+bandX,top:area.top+area.height-bandY,width:Math.max(0,area.width-2*bandX),height:bandY}
}
}
function panelDockRectContains(r,x,y){
return !!r&&x>=r.left&&x<r.left+r.width&&y>=r.top&&y<r.top+r.height
}
function panelDockHitTest(zones,x,y){
for(const mode of PANEL_DOCK_MODES)if(panelDockRectContains(zones[mode],x,y))return mode
return null
}
// Where the panel would land: the docked size against the matching edge of the area.
function panelDockPreviewRect(area,mode,size){
if(mode==="bottom"){
const h=Math.min(size,area.height)
return {left:area.left,top:area.top+area.height-h,width:area.width,height:h}
}
const w=Math.min(size,area.width)
return {left:mode==="left"?area.left:area.left+area.width-w,top:area.top,width:w,height:area.height}
}
// panels: {name:{mode}}. Returns the new mode for every panel that has to change (always including the moving one).
function panelDockResolve(moving,target,panels){
const plan={}
plan[moving]=target
if(target!=="bottom")return plan
const prev=panels[moving]&&panels[moving].mode
Object.keys(panels).forEach((name)=>{
if(name===moving||panels[name].mode!=="bottom")return
plan[name]=prev&&prev!=="bottom"?prev:(name==="ai"?"left":"right")
})
return plan
}
// Toolbar overflow. items are in DOM order: {id,width,priority,pinned}; a higher priority number leaves first.
// Pinned items never move. Returns the ids that stay and the ids that go into the "More" menu (both in DOM order).
function panelDockOverflow(items,available,opts){
opts=opts||{}
const gap=opts.gap||0
const live=items.filter((it)=>it.width>0)
const total=(list)=>list.reduce((s,it)=>s+it.width,0)+Math.max(0,list.length-1)*gap
if(total(live)<=available)return {visible:live.map((it)=>it.id),overflow:[]}
const budget=available-(opts.moreWidth||0)-gap
const keep=live.slice()
const leaving=live.filter((it)=>!it.pinned).map((it,i)=>({it,i})).sort((a,b)=>(b.it.priority-a.it.priority)||(b.i-a.i)).map((x)=>x.it)
const gone=new Set()
for(const it of leaving){
if(total(keep)<=budget)break
keep.splice(keep.indexOf(it),1)
gone.add(it.id)
}
return {visible:keep.map((it)=>it.id),overflow:live.filter((it)=>gone.has(it.id)).map((it)=>it.id)}
}

// ---- DOM side ---------------------------------------------------------------------------------------------------
const panelDockPanels={}
// api: {label, getMode():mode, applyMode(mode,opts)} - applyMode sets, lays out and persists without asking back here.
function panelDockRegister(name,api){panelDockPanels[name]=api}
function panelDockMove(name,mode,opts){
const me=panelDockPanels[name]
if(!me)return
const state={}
Object.keys(panelDockPanels).forEach((k)=>{state[k]={mode:panelDockPanels[k].getMode()}})
const plan=panelDockResolve(name,mode,state)
me.applyMode(mode,opts||{})
// The displaced panel's notice comes last so it is the one left on screen.
Object.keys(plan).forEach((k)=>{
if(k===name)return
if(plan[k]===state[k].mode)return
panelDockPanels[k].applyMode(plan[k],{displaced:true})
if(typeof showStatusIsland==="function")showStatusIsland(panelDockPanels[k].label+" moved to the "+plan[k]+" - only one panel docks at the bottom")
})
}
const PANEL_DOCK_NO_DRAG="button,input,select,textarea,a,label,[contenteditable],[draggable=true],.terminal-tabs,.ui-select-trigger,.ai-provider-select-wrap,[data-no-dock-drag]"
function panelDockCanStartFrom(target,header,grip){
if(!target||!header.contains(target))return false
if(grip&&grip.contains(target))return true
const blocked=target.closest&&target.closest(PANEL_DOCK_NO_DRAG)
return !(blocked&&header.contains(blocked))
}
function panelDockPlace(el,r){
el.style.left=Math.round(r.left)+"px"
el.style.top=Math.round(r.top)+"px"
el.style.width=Math.round(r.width)+"px"
el.style.height=Math.round(r.height)+"px"
}
const PANEL_DOCK_LABELS={left:["Dock left","align-left"],right:["Dock right","align-right"],bottom:["Dock bottom","align-center"]}
function panelDockBuildOverlay(area,current,label){
const overlay=document.createElement("div")
overlay.className="panel-dock-overlay"
overlay.setAttribute("aria-hidden","true")
const zones=panelDockZones(area)
const preview=document.createElement("div")
preview.className="panel-dock-preview hidden"
overlay.appendChild(preview)
const zoneEls={}
PANEL_DOCK_MODES.forEach((mode)=>{
const z=document.createElement("div")
z.className="panel-dock-zone panel-dock-zone-"+mode+(mode===current?" current":"")
z.innerHTML='<span class="panel-dock-zone-label"><i class="icon icon-'+PANEL_DOCK_LABELS[mode][1]+'"></i><span>'+PANEL_DOCK_LABELS[mode][0]+"</span></span>"
panelDockPlace(z,zones[mode])
overlay.appendChild(z)
zoneEls[mode]=z
})
const chip=document.createElement("div")
chip.className="panel-dock-chip"
chip.textContent=label
overlay.appendChild(chip)
document.body.appendChild(overlay)
return {overlay,zones,zoneEls,preview,chip}
}
// opts: {name, panel, header, grip?, area():Element, size(mode):px, onDrop(mode), canDrag()?}
function panelDockAttach(opts){
const header=opts.header
let pending=null
let drag=null
let suppressClickUntil=0
function cleanup(){
window.removeEventListener("pointermove",onMove,true)
window.removeEventListener("pointerup",onUp,true)
window.removeEventListener("pointercancel",onCancel,true)
window.removeEventListener("keydown",onKey,true)
if(drag){
try{if(header.hasPointerCapture&&header.hasPointerCapture(drag.pointerId))header.releasePointerCapture(drag.pointerId)}catch(err){}
header.removeEventListener("lostpointercapture",onCancel)
if(drag.ui)drag.ui.overlay.remove()
opts.panel.classList.remove("panel-dock-source")
document.documentElement.classList.remove("panel-dock-dragging")
}
pending=null
drag=null
}
function begin(e){
const areaEl=opts.area()
if(!areaEl)return cleanup()
const r=areaEl.getBoundingClientRect()
const area={left:r.left,top:r.top,width:r.width,height:r.height}
drag={pointerId:pending.pointerId,area,current:null,ui:panelDockBuildOverlay(area,panelDockPanels[opts.name]?panelDockPanels[opts.name].getMode():"",(panelDockPanels[opts.name]&&panelDockPanels[opts.name].label)||"Panel")}
try{header.setPointerCapture(drag.pointerId)}catch(err){}
header.addEventListener("lostpointercapture",onCancel)
opts.panel.classList.add("panel-dock-source")
document.documentElement.classList.add("panel-dock-dragging")
if(typeof closeContextMenu==="function")closeContextMenu()
track(e)
}
function track(e){
const ui=drag.ui
ui.chip.style.left=Math.round(e.clientX+14)+"px"
ui.chip.style.top=Math.round(e.clientY+14)+"px"
const mode=panelDockHitTest(ui.zones,e.clientX,e.clientY)
if(mode===drag.current)return
drag.current=mode
PANEL_DOCK_MODES.forEach((m)=>ui.zoneEls[m].classList.toggle("active",m===mode))
ui.preview.classList.toggle("hidden",!mode)
if(mode)panelDockPlace(ui.preview,panelDockPreviewRect(drag.area,mode,panelDockClampSize(mode,opts.size(mode),{width:window.innerWidth,height:window.innerHeight})))
const label=(panelDockPanels[opts.name]&&panelDockPanels[opts.name].label)||"Panel"
ui.chip.textContent=mode?label+" → "+PANEL_DOCK_LABELS[mode][0].toLowerCase():label+" - release over an edge to dock, Esc cancels"
}
function onMove(e){
if(!pending||e.pointerId!==pending.pointerId)return
if(!drag){
if(Math.hypot(e.clientX-pending.x,e.clientY-pending.y)<PANEL_DOCK_DRAG_THRESHOLD)return
begin(e)
if(!drag)return
}
e.preventDefault()
track(e)
}
function onUp(e){
if(!pending||e.pointerId!==pending.pointerId)return
if(!drag){cleanup();return}
const mode=drag.current
suppressClickUntil=Date.now()+400
e.preventDefault()
cleanup()
if(mode)opts.onDrop(mode)
}
function onCancel(){
if(drag)suppressClickUntil=Date.now()+400
cleanup()
}
function onKey(e){
if(e.key!=="Escape")return
if(!drag){cleanup();return}
e.preventDefault()
e.stopPropagation()
onCancel()
}
header.addEventListener("pointerdown",(e)=>{
if(e.button!==0||pending)return
if(opts.canDrag&&!opts.canDrag())return
if(!panelDockCanStartFrom(e.target,header,opts.grip))return
pending={pointerId:e.pointerId,x:e.clientX,y:e.clientY}
window.addEventListener("pointermove",onMove,true)
window.addEventListener("pointerup",onUp,true)
window.addEventListener("pointercancel",onCancel,true)
window.addEventListener("keydown",onKey,true)
})
// A drag that started on the grip button must not also "click" it (which would open the position menu).
header.addEventListener("click",(e)=>{if(Date.now()<suppressClickUntil){e.preventDefault();e.stopPropagation();suppressClickUntil=0}},true)
return {cancel:onCancel,isDragging:()=>!!drag}
}
if(typeof module!=="undefined"&&module.exports)module.exports={PANEL_DOCK_MODES,PANEL_DOCK_MIN_SIDE,PANEL_DOCK_MIN_BOTTOM,PANEL_DOCK_MAX_SIDE,PANEL_DOCK_DRAG_THRESHOLD,panelDockNormalizeMode,panelDockClampSize,panelDockZones,panelDockHitTest,panelDockPreviewRect,panelDockResolve,panelDockOverflow,panelDockCanStartFrom}
