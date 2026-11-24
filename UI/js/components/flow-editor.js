// Chain diagram studio canvas on top of flow-model.js: HTML node cards in a transformed world, SVG bezier wires coloured by
// port type, a hot bar, a searchable node picker, sticky notes, a minimap and floating tool bars.
// flowEditorCreate(host,opts) -> editor. All drags use Pointer Events with pointer capture (HTML5 drag-and-drop is unreliable in
// WebKitGTK). The view transform is our own maths ({x,y,zoom} + getBoundingClientRect), never the SVG screen matrix.
// Nothing at the top level of this file touches the DOM, so the pure helpers below are testable in node.
const FLOW_NS="http://www.w3.org/2000/svg"
const FLOW_ZOOM_MIN=0.25,FLOW_ZOOM_MAX=2
const FLOW_RUN_STATES=["pending","running","success","fail","skipped","waiting","planned"]
// What the status pill on a node card says. "warn" = the node failed and the diagram handles it (its fail port is wired).
const FLOW_RUN_BADGES={pending:{label:"Queued",icon:"clock"},running:{label:"Running",icon:"refresh"},success:{label:"OK",icon:"check"},warn:{label:"Handled",icon:"warning"},fail:{label:"Failed",icon:"close"},skipped:{label:"Skipped",icon:"arrow-right"},waiting:{label:"Waiting",icon:"clipboard-check"},planned:{label:"Planned",icon:"eye-off"}}
// The state shown for a node record of a run status: a failure whose branch is wired counts as handled.
function flowRunBadgeState(rec,edges,id){
const rs=rec?String(rec.state||""):""
if(rs==="fail"&&rec.branch&&(edges||[]).some((e)=>e.from===id&&e.port===rec.branch))return "warn"
return FLOW_RUN_BADGES[rs]?rs:""
}
function flowPillDuration(ms){ms=Number(ms);if(!Number.isFinite(ms)||ms<1)return "";if(ms<1000)return Math.round(ms)+" ms";if(ms<59950)return (Math.round(ms/100)/10)+" s";const sec=Math.round(ms/1000);return Math.floor(sec/60)+"m "+(sec%60)+"s"}
// For the app's Ctrl+/ sheet.
const FLOW_EDITOR_SHORTCUTS=[
{keys:"Tab or /",label:"Search every node type and add one"},
{keys:"Double-click the canvas",label:"Open the node search at that spot"},
{keys:"Drag from a port",label:"Connect two nodes; drop on empty canvas to pick a new node that is wired in"},
{keys:"Delete / Backspace",label:"Delete the selected nodes and connections"},
{keys:"Ctrl+Z",label:"Undo"},
{keys:"Ctrl+Y / Ctrl+Shift+Z",label:"Redo"},
{keys:"Ctrl+C / Ctrl+X / Ctrl+V",label:"Copy, cut, paste nodes"},
{keys:"Ctrl+D",label:"Duplicate the selection"},
{keys:"Ctrl+A",label:"Select every node"},
{keys:"Arrow keys",label:"Nudge the selection (Shift = 5 steps); pan when nothing is selected"},
{keys:"Enter",label:"Open the selected node"},
{keys:"Ctrl+Shift+L",label:"Auto-layout, left to right"},
{keys:"F",label:"Fit the diagram to the screen"},
{keys:"+ / -",label:"Zoom in / out"},
{keys:"0",label:"Zoom to 100%"},
{keys:"Space + drag / middle button",label:"Pan the canvas"},
{keys:"Wheel / two-finger scroll",label:"Pan the canvas (Shift+wheel pans sideways)"},
{keys:"Ctrl+wheel / pinch",label:"Zoom at the cursor"},
{keys:"Shift+click / Ctrl+click",label:"Add to or remove from the selection"},
{keys:"Escape",label:"Cancel a drag, or clear the selection"}
]
// Node icons: the shapes of Assets/icons/<name>.svg (24x24, stroked), drawn inline so they take the node's colour inside the SVG.
const FLOW_ICON_SHAPES={
"play":[["path",{d:"M8 5.5v13a1 1 0 0 0 1.5.87l11-6.5a1 1 0 0 0 0-1.74l-11-6.5A1 1 0 0 0 8 5.5z",fill:"currentColor"}]],
"command-line":[["rect",{x:3,y:4,width:18,height:16,rx:2}],["path",{d:"m7 9 3 3-3 3"}],["path",{d:"M12.5 15H17"}]],
"code-block":[["rect",{x:3,y:4,width:18,height:16,rx:2}],["path",{d:"M10 9l-3 3 3 3"}],["path",{d:"M14 9l3 3-3 3"}]],
"chain":[["rect",{x:3,y:3,width:8,height:8,rx:2}],["rect",{x:13,y:13,width:8,height:8,rx:2}],["path",{d:"M7 11v3a3 3 0 0 0 3 3h3"}]],
"shuffle":[["path",{d:"M3 7h4l10 10h4"}],["path",{d:"M3 17h4l3-3"}],["path",{d:"M14 10l3-3h4"}],["path",{d:"M18 4l3 3-3 3"}],["path",{d:"M18 14l3 3-3 3"}]],
"clipboard-check":[["rect",{x:5,y:5,width:14,height:16,rx:2}],["path",{d:"M9 5V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v1"}],["path",{d:"M9 13l2 2 4-4"}]],
"search":[["circle",{cx:11,cy:11,r:7}],["path",{d:"m16.5 16.5 4.5 4.5"}]],
"pairs":[["path",{d:"M8 4c-2 0-3 1-3 3v2c0 1.5-.8 3-2 3 1.2 0 2 1.5 2 3v2c0 2 1 3 3 3"}],["path",{d:"M16 4c2 0 3 1 3 3v2c0 1.5.8 3 2 3-1.2 0-2 1.5-2 3v2c0 2-1 3-3 3"}]],
"refresh":[["path",{d:"M20 11a8 8 0 1 0-2.3 5.7"}],["path",{d:"M20 5v6h-6"}]],
"clock":[["circle",{cx:12,cy:12,r:9}],["path",{d:"M12 7v5l3.5 2"}]],
"stop":[["rect",{x:6,y:6,width:12,height:12,rx:2,fill:"currentColor"}]],
"report":[["path",{d:"M9 4H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-2"}],["rect",{x:9,y:2,width:6,height:4,rx:1}],["path",{d:"M9 17v-2"}],["path",{d:"M12 17v-5"}],["path",{d:"M15 17v-3"}]],
"text":[["path",{d:"M5 6V4h14v2"}],["path",{d:"M12 4v16"}],["path",{d:"M9 20h6"}]],
"_":[["circle",{cx:12,cy:12,r:8}]]
}
// ---- pure helpers (no DOM)
function flowClampZoom(z){z=Number(z);if(!Number.isFinite(z)||z<=0)return 1;return Math.min(FLOW_ZOOM_MAX,Math.max(FLOW_ZOOM_MIN,z))}
// view={x,y,zoom}: (x,y) is the canvas point at the top-left corner. Screen coordinates are px from that corner.
function flowViewToScreen(view,wx,wy){return {x:(wx-view.x)*view.zoom,y:(wy-view.y)*view.zoom}}
function flowViewToWorld(view,sx,sy){return {x:sx/view.zoom+view.x,y:sy/view.zoom+view.y}}
function flowViewZoomAt(view,sx,sy,zoom){const z=flowClampZoom(zoom),w=flowViewToWorld(view,sx,sy);return {x:w.x-sx/z,y:w.y-sy/z,zoom:z}}
function flowViewPan(view,dx,dy){return {x:view.x-dx/view.zoom,y:view.y-dy/view.zoom,zoom:view.zoom}}
// What a wheel event does (deltas in px): a plain wheel or two-finger scroll pans on both axes, Shift+wheel pans sideways,
// Ctrl+wheel zooms at the cursor. Pinch gestures arrive as Ctrl+wheel with small deltas in WebKit and Chromium.
function flowWheelAction(dx,dy,ctrl,shift){
dx=Number(dx)||0;dy=Number(dy)||0
if(ctrl){
if(!dy)return {type:"none"}
const k=Math.abs(dy)<40?0.012:0.0016
return {type:"zoom",factor:Math.exp(-Math.max(-300,Math.min(300,dy))*k)}
}
if(shift&&!dx)return dy?{type:"pan",dx:dy,dy:0}:{type:"none"}
if(!dx&&!dy)return {type:"none"}
return {type:"pan",dx:dx,dy:dy}
}
// The view that shows `bounds` centred in a w x h canvas with `pad` px around it (never zooms in past 100%).
function flowViewFit(bounds,w,h,pad){
if(!bounds||!(w>0)||!(h>0))return {x:0,y:0,zoom:1}
pad=Math.max(0,Math.min(pad||0,w/3,h/3))
const z=flowClampZoom(Math.min((w-2*pad)/Math.max(bounds.w,1),(h-2*pad)/Math.max(bounds.h,1),1))
return {x:bounds.x+bounds.w/2-w/(2*z),y:bounds.y+bounds.h/2-h/(2*z),zoom:z}
}
function flowViewSees(view,w,h,rect){
if(!rect)return false
const x1=view.x+w/view.zoom,y1=view.y+h/view.zoom
return rect.x<x1&&rect.x+rect.w>view.x&&rect.y<y1&&rect.y+rect.h>view.y
}
function flowBoxRect(x1,y1,x2,y2){return {x:Math.min(x1,x2),y:Math.min(y1,y2),w:Math.abs(x2-x1),h:Math.abs(y2-y1)}}
function flowBoxHits(graph,rect){
return ((graph&&graph.nodes)||[]).filter((n)=>{const s=flowNodeSize(n);return n.x<rect.x+rect.w&&n.x+s.w>rect.x&&n.y<rect.y+rect.h&&n.y+s.h>rect.y}).map((n)=>n.id)
}
// Minimap mapping: canvas bounds scaled into a w x h box. mini = world*s + (ox,oy).
function flowMiniMap(bounds,w,h,pad){
const b=bounds||{x:0,y:0,w:1,h:1}
const s=Math.min((w-2*pad)/Math.max(b.w,1),(h-2*pad)/Math.max(b.h,1))
return {s,ox:(w-b.w*s)/2-b.x*s,oy:(h-b.h*s)/2-b.y*s}
}
function flowMiniToMini(mm,wx,wy){return {x:wx*mm.s+mm.ox,y:wy*mm.s+mm.oy}}
function flowMiniToWorld(mm,mx,my){return {x:(mx-mm.ox)/mm.s,y:(my-mm.oy)/mm.s}}
// Word-wrap for sticky notes drawn as SVG text (cols characters per line, at most maxLines lines).
function flowWrapText(text,cols,maxLines){
cols=Math.max(1,Math.floor(cols)||1);maxLines=Math.max(1,Math.floor(maxLines)||1)
const lines=[]
String(text==null?"":text).split("\n").forEach((para)=>{
let cur=""
para.split(/\s+/).filter(Boolean).forEach((word)=>{
while(word.length>cols){if(cur){lines.push(cur);cur=""}lines.push(word.slice(0,cols));word=word.slice(cols)}
if(!word)return
if(!cur)cur=word
else if(cur.length+1+word.length<=cols)cur+=" "+word
else{lines.push(cur);cur=word}
})
lines.push(cur)
})
if(lines.length<=maxLines)return lines
const out=lines.slice(0,maxLines);out[maxLines-1]=out[maxLines-1].slice(0,Math.max(0,cols-1))+"\u2026"
return out
}
// {errors,warnings} -> {nodes:{id:{level,text}},edges:{id:{level,text}}} (errors listed first).
function flowIssueMap(issues){
const map={nodes:{},edges:{}}
const add=(list,level)=>(Array.isArray(list)?list:[]).forEach((i)=>{
if(!i||typeof i!=="object")return
const put=(bag,id)=>{if(id==null||id==="")return;const cur=bag[id]||(bag[id]={level,text:""});if(level==="error")cur.level="error";cur.text+=(cur.text?"\n":"")+(typeof flowIssueText==="function"?flowIssueText(i):String(i.message||i.code||""))||level}
put(map.nodes,i.node);put(map.edges,i.edge)
})
add(issues&&issues.errors,"error");add(issues&&issues.warnings,"warning")
return map
}
// One clipboard for every editor instance, so nodes can be copied from one chain into another.
let flowEditorClip=null
// ---- the editor
function flowEditorCreate(host,opts){
opts=opts||{}
const doc=host.ownerDocument||document,win=doc.defaultView||window
const raf=win.requestAnimationFrame?win.requestAnimationFrame.bind(win):(fn)=>win.setTimeout(fn,16)
const caf=win.cancelAnimationFrame?win.cancelAnimationFrame.bind(win):(id)=>win.clearTimeout(id)
const st={graph:null,view:{x:0,y:0,zoom:1},sel:new Set(),selEdges:new Set(),readOnly:!!opts.readOnly,
prefs:{snap:!opts.prefs||opts.prefs.snap!==false,grid:(opts.prefs&&Number(opts.prefs.grid)>0)?Number(opts.prefs.grid):20,minimap:!opts.prefs||opts.prefs.minimap!==false,hotbar:flowHotbarClean(opts.prefs&&opts.prefs.hotbar)},pick:null,lastEmpty:0,
drag:null,box:null,space:false,issues:{nodes:{},edges:{}},run:null,nodeEls:new Map(),edgeEls:new Map(),history:flowHistoryCreate(100),
lastKey:null,lastT:0,pasteN:0,editing:null,lastClick:null,dragRaf:0,miniRaf:0,mm:null,miniRects:[],destroyed:false,pendingFit:false,palClickAt:0}
const cleanup=[]
const on=(el,type,fn,o)=>{el.addEventListener(type,fn,o);cleanup.push(()=>el.removeEventListener(type,fn,o))}
const call=(name,...args)=>{const fn=opts[name];if(typeof fn!=="function")return;try{fn(...args)}catch(err){if(win.console)win.console.error("flow editor "+name+" callback failed",err)}}
const H=(tag,cls,text)=>{const el=doc.createElement(tag);if(cls)el.className=cls;if(text!=null)el.textContent=text;return el}
const S=(tag,attrs,cls)=>{const el=doc.createElementNS(FLOW_NS,tag);if(cls)el.setAttribute("class",cls);if(attrs)for(const k in attrs)el.setAttribute(k,attrs[k]);return el}
const css=(s)=>String(s==null?"":s).replace(/[^A-Za-z0-9_-]/g,"")
// ---- DOM skeleton
const root=H("div","flow-editor");root.tabIndex=0;root.setAttribute("role","application");root.setAttribute("aria-label","Chain diagram editor")
const stage=H("div","flow-stage")
// surface: what the pointer works on (the dotted grid is its background); world: everything that pans and zooms.
const surface=H("div","flow-surface")
const world=H("div","flow-world")
const svg=S("svg",{"aria-hidden":"true",focusable:"false",width:1,height:1},"flow-wires")
const edgesLayer=S("g",null,"flow-edges")
const rubber=S("path",{d:""},"flow-rubber")
svg.appendChild(edgesLayer);svg.appendChild(rubber)
const notesLayer=H("div","flow-layer flow-notes"),nodesLayer=H("div","flow-layer flow-nodes")
world.appendChild(notesLayer);world.appendChild(svg);world.appendChild(nodesLayer)
const selBox=H("div","flow-selbox")
surface.appendChild(world);surface.appendChild(selBox)
const noteInput=H("textarea","flow-comment-input");noteInput.hidden=true;noteInput.setAttribute("aria-label","Note text");noteInput.spellcheck=false
const toolbar=H("div","flow-toolbar");toolbar.setAttribute("role","toolbar");toolbar.setAttribute("aria-label","Diagram tools")
const zoombar=H("div","flow-toolbar flow-zoombar");zoombar.setAttribute("role","toolbar");zoombar.setAttribute("aria-label","Zoom")
const hotbar=H("div","flow-hotbar");hotbar.setAttribute("role","toolbar");hotbar.setAttribute("aria-label","Most used nodes")
const MINI_W=180,MINI_H=120
const minimap=H("div","flow-minimap");minimap.setAttribute("aria-hidden","true")
const miniSvg=S("svg",{viewBox:"0 0 "+MINI_W+" "+MINI_H,width:MINI_W,height:MINI_H},"flow-minimap-svg")
const miniNodes=S("g"),miniView=S("rect",{x:0,y:0,width:0,height:0},"flow-minimap-view")
miniSvg.appendChild(miniNodes);miniSvg.appendChild(miniView);minimap.appendChild(miniSvg)
const tip=H("div","flow-tooltip");tip.hidden=true
const emptyHint=H("div","flow-empty-hint");emptyHint.hidden=true
emptyHint.appendChild(H("div","flow-empty-title","Build your workflow"))
emptyHint.appendChild(H("div","flow-empty-text","Press Tab or / to search every node, pick one from the hot bar below, or drag from the Start port and drop on the canvas."))
const edgeTools=H("div","flow-edge-tools");edgeTools.hidden=true
const picker=H("div","flow-picker");picker.hidden=true;picker.setAttribute("role","dialog");picker.setAttribute("aria-label","Add a node")
const pickHead=H("div","flow-picker-head")
const pickInput=H("input","flow-picker-input");pickInput.type="text";pickInput.placeholder="Search nodes: name, category or keyword";pickInput.spellcheck=false;pickInput.setAttribute("autocomplete","off");pickInput.setAttribute("aria-label","Search nodes")
pickHead.appendChild(H("i","icon icon-search"));pickHead.appendChild(pickInput)
const pickHint=H("div","flow-picker-hint")
const pickList=H("div","flow-picker-list")
const pickFoot=H("div","flow-picker-foot","Enter adds | Up and Down move | Esc closes | the pin puts a node on the hot bar")
picker.appendChild(pickHead);picker.appendChild(pickHint);picker.appendChild(pickList);picker.appendChild(pickFoot)
stage.appendChild(surface);stage.appendChild(noteInput);stage.appendChild(emptyHint);stage.appendChild(edgeTools);stage.appendChild(toolbar);stage.appendChild(zoombar);stage.appendChild(hotbar);stage.appendChild(minimap);stage.appendChild(picker);stage.appendChild(tip)
root.appendChild(stage)
// ---- tool bars
const tb={}
function toolButton(parent,key,icon,label,fn,extra,text){
const b=H("button","flow-tool"+(extra?" "+extra:""));b.type="button";b.title=label;b.setAttribute("aria-label",label)
if(icon)b.appendChild(H("i","icon icon-"+icon))
if(text)b.appendChild(H("span","flow-tool-text",text))
on(b,"click",(e)=>{fn(e);if(e.detail!==0&&!(st.pick&&st.pick.open))focus()})
on(b,"pointerdown",(e)=>e.stopPropagation())
parent.appendChild(b);tb[key]=b;return b
}
toolButton(toolbar,"add","add","Add a node: search every node type (Tab or /)",()=>{if(st.pick&&st.pick.open)closePicker();else openPicker({})},"flow-tool-add","Add node")
toolbar.appendChild(H("span","flow-tool-sep"))
toolButton(toolbar,"undo","undo","Undo (Ctrl+Z)",()=>undo())
toolButton(toolbar,"redo","redo","Redo (Ctrl+Y)",()=>redo())
toolbar.appendChild(H("span","flow-tool-sep"))
toolButton(toolbar,"layout","network","Auto-layout, left to right (Ctrl+Shift+L)",()=>autoLayout())
toolButton(toolbar,"snap","hash","Snap to grid",()=>setPref("snap",!st.prefs.snap))
toolButton(toolbar,"minimap","image","Minimap",()=>setPref("minimap",!st.prefs.minimap))
toolButton(toolbar,"note","flow-note","Add a sticky note",()=>addNodeAt("comment"))
toolButton(zoombar,"zoomOut","minimize","Zoom out (-)",()=>zoomBy(1/1.2),"flow-tool-zoomout")
toolButton(zoombar,"zoom",null,"Zoom to 100% (0)",()=>zoomTo(1),"flow-zoom-label")
toolButton(zoombar,"zoomIn","add","Zoom in (+)",()=>zoomBy(1.2))
toolButton(zoombar,"fit","fullscreen","Fit to screen (F)",()=>fit(0))
// wire tools: shown on the middle of the one selected connection
const etAdd=H("button","flow-edge-tool");etAdd.type="button";etAdd.title="Insert a node on this connection";etAdd.setAttribute("aria-label",etAdd.title);etAdd.appendChild(H("i","icon icon-add"))
const etDel=H("button","flow-edge-tool is-danger");etDel.type="button";etDel.title="Delete this connection (Delete)";etDel.setAttribute("aria-label",etDel.title);etDel.appendChild(H("i","icon icon-trash"))
edgeTools.appendChild(etAdd);edgeTools.appendChild(etDel)
on(edgeTools,"pointerdown",(e)=>e.stopPropagation())
on(etAdd,"click",()=>{const id=Array.from(st.selEdges)[0],e=id&&flowFindEdge(st.graph,id);if(!e||st.readOnly)return;const m=edgeMid(e);openPicker({world:m,pending:{edge:id}})})
on(etDel,"click",()=>{deleteSelection();focus()})
// ---- hot bar: the most used node types, one click (or a drag onto the canvas) away. The pins live in the editor prefs.
const palItems=new Map()
function nodeTile(item,cls){const t=H("span",(cls||"flow-tile")+" flow-cat-"+css(item.color||item.category));t.appendChild(H("i","icon icon-"+css(item.icon||"_")));return t}
function renderHotbar(){
clearLayer(hotbar);palItems.clear()
st.prefs.hotbar.forEach((id)=>{
const item=flowCatalogItem(id);if(!item)return
const b=H("button","flow-hot flow-cat-"+css(item.color||item.category));b.type="button";b.dataset.item=id;b.dataset.type=item.type
b.title=item.label+" - "+item.description+" Click to add, or drag onto the canvas.";b.setAttribute("aria-label","Add "+item.label+" node")
b.appendChild(nodeTile(item));b.appendChild(H("span","flow-hot-label",item.label))
hotbar.appendChild(b);palItems.set(id,b);bindAdder(b,item)
})
const more=H("button","flow-hot flow-hot-more");more.type="button";more.title="All nodes (Tab or /)";more.setAttribute("aria-label","All nodes")
more.appendChild(nodeTile({color:"unknown",icon:"search"}));more.appendChild(H("span","flow-hot-label","All nodes"))
on(more,"pointerdown",(e)=>e.stopPropagation())
on(more,"click",()=>openPicker({}))
hotbar.appendChild(more)
}
function togglePin(id){
const list=st.prefs.hotbar.slice(),i=list.indexOf(id)
if(i>=0)list.splice(i,1);else{if(list.length>=FLOW_HOTBAR_MAX)list.shift();list.push(id)}
st.prefs.hotbar=flowHotbarClean(list)
renderHotbar();refreshChrome()
call("onPrefs",getPrefs())
}
// ---- node picker: every node type and preset, searched by name, category and keywords, grouped by category
function closePicker(){
if(!st.pick)return
st.pick=null;picker.hidden=true;root.classList.remove("is-picking")
rubber.setAttribute("d","")
}
function openPicker(o){
if(st.readOnly||st.destroyed)return false
o=o||{}
if(st.drag)endDrag(null,true)
const box=stageBox()
let at=o.world||null
if(!at&&typeof o.clientX==="number")at=worldPoint(o.clientX,o.clientY,box)
st.pick={open:true,at,pending:o.pending||null,idx:0,items:[]}
picker.hidden=false;root.classList.add("is-picking")
pickInput.value=""
const from=o.pending&&o.pending.from?flowFindNode(st.graph,o.pending.from):null
pickHint.textContent=from?"The new node is wired to \""+(from.title||from.id)+"\" ("+o.pending.port+")":o.pending&&o.pending.edge?"The new node is inserted on the selected connection":""
pickHint.hidden=!pickHint.textContent
// near the spot it is for, else under the tool bar
const pw=340,ph=Math.min(460,Math.max(220,box.h-24))
let x=14,y=58
if(at){const p=flowViewToScreen(st.view,at.x,at.y);x=p.x+12;y=p.y-40}
picker.style.left=Math.round(Math.max(8,Math.min(x,box.w-pw-8)))+"px"
picker.style.top=Math.round(Math.max(8,Math.min(y,box.h-ph-8)))+"px"
picker.style.maxHeight=ph+"px"
renderPicker()
try{pickInput.focus({preventScroll:true})}catch(err){pickInput.focus()}
return true
}
function pickerAllowed(item){
if(item.type==="start"&&flowHasStart(st.graph))return false
const p=st.pick&&st.pick.pending
if(p&&(p.from||p.edge)&&!FLOW_NODE_TYPES[item.type].input)return false
return true
}
function renderPicker(){
if(!st.pick)return
const groups=flowCatalogSearch(pickInput.value,flowCatalogItems().filter(pickerAllowed))
clearLayer(pickList)
const flat=[]
groups.forEach((g)=>{
pickList.appendChild(H("div","flow-picker-group",g.category.label))
g.items.forEach((item)=>{
const row=H("div","flow-picker-item");row.dataset.idx=String(flat.length);row.setAttribute("role","button")
row.appendChild(nodeTile(item))
const txt=H("span","flow-picker-text");txt.appendChild(H("span","flow-picker-name",item.label));txt.appendChild(H("span","flow-picker-desc",item.description))
row.appendChild(txt)
const pinned=st.prefs.hotbar.indexOf(item.id)>=0
const pin=H("button","flow-picker-pin"+(pinned?" is-on":""));pin.type="button";pin.title=pinned?"Remove from the hot bar":"Pin to the hot bar";pin.setAttribute("aria-label",pin.title);pin.dataset.pin=item.id
pin.appendChild(H("i","icon icon-"+(pinned?"star-filled":"star")))
if(item.type!=="start")row.appendChild(pin)
pickList.appendChild(row);flat.push({item,row})
})
})
if(!flat.length)pickList.appendChild(H("div","flow-picker-empty","No node matches. Try a category such as \"logic\" or a keyword such as \"nmap\"."))
st.pick.items=flat;st.pick.idx=Math.min(st.pick.idx,Math.max(0,flat.length-1))
paintPickerIdx(false)
}
function paintPickerIdx(scroll){
if(!st.pick)return
st.pick.items.forEach((x,i)=>x.row.classList.toggle("is-active",i===st.pick.idx))
const cur=st.pick.items[st.pick.idx]
if(scroll&&cur&&cur.row.scrollIntoView)try{cur.row.scrollIntoView({block:"nearest"})}catch(err){}
}
function pickerChoose(item){
const pk=st.pick;if(!pk||!item)return
closePicker()
placeNew(item,pk.at,pk.pending)
focus()
}
on(pickInput,"input",()=>{if(st.pick){st.pick.idx=0;renderPicker()}})
on(pickInput,"keydown",(e)=>{
if(!st.pick)return
const n=st.pick.items.length
if(e.key==="ArrowDown"||e.key==="ArrowUp"){e.preventDefault();if(n){st.pick.idx=(st.pick.idx+(e.key==="ArrowDown"?1:n-1))%n;paintPickerIdx(true)}}
else if(e.key==="Enter"){e.preventDefault();const cur=st.pick.items[st.pick.idx];if(cur)pickerChoose(cur.item)}
else if(e.key==="Escape"||e.key==="Tab"){e.preventDefault();closePicker();focus()}
e.stopPropagation()
})
on(picker,"pointerdown",(e)=>e.stopPropagation())
on(picker,"wheel",(e)=>e.stopPropagation())
on(pickList,"click",(e)=>{
if(!st.pick)return
const pin=closest(e.target,"[data-pin]")
if(pin){const keep=pickInput.value,idx=st.pick.idx;togglePin(pin.dataset.pin);pickInput.value=keep;st.pick.idx=idx;renderPicker();return}
const row=closest(e.target,".flow-picker-item")
if(row){const cur=st.pick.items[Number(row.dataset.idx)];if(cur)pickerChoose(cur.item)}
})
host.appendChild(root)
// ---- geometry helpers
// The measured box is kept while a drag runs (st.box), so a drag frame never forces a layout.
function stageBox(){
if(st.box)return st.box
const r=stage.getBoundingClientRect()
// k: guards against an ancestor CSS transform scale (rect px vs layout px)
let k=stage.clientWidth>0&&r.width>0?r.width/stage.clientWidth:1
if(Math.abs(k-1)<0.02)k=1
return {left:r.left,top:r.top,w:stage.clientWidth||r.width,h:stage.clientHeight||r.height,k:k||1}
}
function localPoint(clientX,clientY,box){box=box||stageBox();return {x:(clientX-box.left)/box.k,y:(clientY-box.top)/box.k}}
function worldPoint(clientX,clientY,box){const p=localPoint(clientX,clientY,box);return flowViewToWorld(st.view,p.x,p.y)}
const r1=(v)=>Math.round(v*100)/100
const setA=(el,name,value)=>{value=String(value);const c=el.__fa||(el.__fa={});if(c[name]!==value){c[name]=value;el.setAttribute(name,value)}}
// ---- rendering
function applyView(){
const v=st.view,g=st.prefs.grid*v.zoom
world.style.transform="translate("+r1(-v.x*v.zoom)+"px,"+r1(-v.y*v.zoom)+"px) scale("+v.zoom+")"
surface.style.backgroundSize=r1(g)+"px "+r1(g)+"px"
surface.style.backgroundPosition=r1(-v.x*v.zoom)+"px "+r1(-v.y*v.zoom)+"px"
root.classList.toggle("is-nogrid",g<9)
root.classList.toggle("is-far",v.zoom<0.45)
const zl=Math.round(v.zoom*100)+"%";if(tb.zoom.textContent!==zl)tb.zoom.textContent=zl
tb.zoomOut.disabled=v.zoom<=FLOW_ZOOM_MIN+1e-6;tb.zoomIn.disabled=v.zoom>=FLOW_ZOOM_MAX-1e-6
if(st.editing)placeNoteInput()
if(!tip.hidden)tip.hidden=true
placeEdgeTools()
scheduleMini()
}
function place(el,n){el.style.left=r1(n.x)+"px";el.style.top=r1(n.y)+"px"}
function buildNode(n){
const t=FLOW_NODE_TYPES[n.type],size=flowNodeSize(n),G=FLOW_GEOM
const g=H("div","flow-node flow-type-"+css(n.type)+" flow-cat-"+css(t?t.color:"unknown"));g.setAttribute("data-id",n.id)
place(g,n);g.style.width=size.w+"px";g.style.height=size.h+"px"
if(n.type==="comment"){
const c=n.config||{},text=String(c.text||"")
g.className+=" flow-comment flow-comment-"+css(FLOW_COMMENT_COLORS.indexOf(c.color)>=0?c.color:"yellow")
g.appendChild(H("div","flow-comment-text"+(text.trim()?"":" is-placeholder"),text.trim()?text:"Double-click to write a note"))
g.appendChild(H("span","flow-comment-resize"))
return g
}
const ports=flowNodePorts(n),rowY=G.head+G.sum+G.row/2
g.title=(n.title||(t?t.label:n.type))+(t?" ("+t.label+")":"")+"\n"+flowNodeSummary(n)
const head=H("div","flow-node-head");head.style.height=G.head+"px"
const tile=H("span","flow-node-tile");tile.appendChild(H("i","icon icon-"+css(t?t.icon:"_")));head.appendChild(tile)
const titles=H("span","flow-node-titles")
titles.appendChild(H("span","flow-node-title",n.title||(t?t.label:n.type)))
titles.appendChild(H("span","flow-node-kind",t?t.label:n.type))
head.appendChild(titles);g.appendChild(head)
const sm=H("div","flow-node-summary"+(n.type==="command"||n.type==="http"||n.type==="math"||n.type==="regex"?" is-mono":""),flowNodeSummary(n));sm.style.height=G.sum+"px";g.appendChild(sm)
if(ports.in){const p=H("span","flow-port flow-port-in");p.style.top=rowY+"px";p.appendChild(H("span","flow-port-dot"));g.appendChild(p)}
ports.out.forEach((name,i)=>{
const y=rowY+i*G.row,tone=flowPortTone(name,n)
const lab=H("span","flow-port-label"+(tone?" flow-tone-"+tone:""),name);lab.style.top=(y-G.row/2)+"px";lab.style.height=G.row+"px";g.appendChild(lab)
const p=H("span","flow-port flow-port-out"+(tone?" flow-tone-"+tone:""));p.setAttribute("data-port",name);p.style.top=y+"px";p.title="Drag to connect, or click to add the next node"
p.appendChild(H("span","flow-port-dot"));p.appendChild(H("span","flow-port-plus"))
g.appendChild(p)
})
const status=H("span","flow-node-status");status.hidden=true;status.appendChild(H("i","icon"));status.appendChild(H("span","flow-node-status-text"));g.appendChild(status)
g.appendChild(H("span","flow-node-badge","!"))
return g
}
function decorateNode(id){
const el=st.nodeEls.get(id);if(!el)return
el.classList.toggle("is-selected",st.sel.has(id))
const issue=st.issues.nodes[id]
el.classList.toggle("has-error",!!issue&&issue.level==="error");el.classList.toggle("has-warning",!!issue&&issue.level==="warning")
const rec=st.run&&st.run.nodes?st.run.nodes[id]:null
const rs=rec?String(rec.state||""):"",shown=flowRunBadgeState(rec,st.graph.edges,id)
FLOW_RUN_STATES.forEach((s)=>el.classList.toggle("is-"+s,rs===s))
el.classList.toggle("is-warn",shown==="warn")
el.classList.toggle("is-current",!!st.run&&st.run.current===id)
el.classList.toggle("is-editing",st.editing===id)
const status=el.querySelector?el.querySelector(".flow-node-status"):null
if(status){
const b=FLOW_RUN_BADGES[shown]
status.hidden=!b
if(b){
const sig=shown+"|"+(rec.duration_ms||0)+"|"+(rec.visits||0)
if(status.__sig!==sig){
status.__sig=sig
status.className="flow-node-status is-"+shown
status.firstChild.className="icon icon-"+b.icon
const time=shown==="running"||shown==="pending"||shown==="planned"||shown==="skipped"?"":flowPillDuration(rec.duration_ms)
status.lastChild.textContent=(time||b.label)+(Number(rec.visits)>1?" x"+rec.visits:"")
status.title=b.label+(time?" in "+time:"")+(rec.error?": "+rec.error:"")+" - click to see this node's output"
}
}
if(el.querySelectorAll)el.querySelectorAll(".flow-port-out").forEach((p)=>p.classList.toggle("is-taken",!!rec&&!!rec.branch&&p.getAttribute("data-port")===rec.branch))
}
}
function mountNode(n,replace){
const el=buildNode(n),old=st.nodeEls.get(n.id)
if(old&&old.parentNode&&replace)old.parentNode.replaceChild(el,old)
else{if(old&&old.parentNode)old.parentNode.removeChild(old);(n.type==="comment"?notesLayer:nodesLayer).appendChild(el)}
st.nodeEls.set(n.id,el);decorateNode(n.id)
}
function edgeEnds(e){
const a=flowFindNode(st.graph,e.from),b=flowFindNode(st.graph,e.to)
if(!a||!b)return null
return {a,b,p:flowPortPos(a,"out",e.port),q:flowPortPos(b,"in")}
}
function edgeMid(e){const k=edgeEnds(e);return k?{x:(k.p.x+k.q.x)/2,y:(k.p.y+k.q.y)/2}:{x:0,y:0}}
function placeEdgeTools(){
const id=st.selEdges.size===1&&!st.sel.size&&!st.readOnly&&!st.drag?Array.from(st.selEdges)[0]:null,e=id?flowFindEdge(st.graph,id):null
if(!e){if(!edgeTools.hidden)edgeTools.hidden=true;return}
const m=edgeMid(e),p=flowViewToScreen(st.view,m.x,m.y)
edgeTools.style.left=r1(p.x)+"px";edgeTools.style.top=r1(p.y)+"px";edgeTools.hidden=false
}
function edgeGeom(e,rec){
const k=edgeEnds(e)
if(!k){rec.g.style.display="none";return}
rec.g.style.display=""
const d=flowEdgePath(k.p.x+6,k.p.y,k.q.x-8,k.q.y)
rec.line.setAttribute("d",d);rec.hit.setAttribute("d",d);rec.flow.setAttribute("d",d)
rec.arrow.setAttribute("d","M"+r1(k.q.x-5)+","+r1(k.q.y)+" l-7,-4.5 v9 z")
}
function decorateEdge(id){
const rec=st.edgeEls.get(id);if(!rec)return
const e=rec.edge,tone=flowPortTone(e.port,flowFindNode(st.graph,e.from)),issue=st.issues.edges[id]
const taken=!!(st.run&&Array.isArray(st.run.edges_taken)&&st.run.edges_taken.indexOf(id)>=0)
// the wire that feeds the node running right now carries the moving dashes
const live=taken&&!!st.run&&st.run.current===e.to
rec.g.setAttribute("class","flow-edge"+(tone?" flow-edge-"+tone:"")+(st.selEdges.has(id)?" is-selected":"")+(taken?" is-taken":"")+(live?" is-live":"")+(issue?" has-error":""))
}
// Brings the edge elements in line with graph.edges; geometry is refreshed for edges touching `ids` (all when ids is null).
function syncEdges(ids){
const want=ids?new Set(ids):null,alive=new Set()
st.graph.edges.forEach((e)=>{
alive.add(e.id)
let rec=st.edgeEls.get(e.id),fresh=false
if(!rec){
const g=S("g",{"data-id":e.id},"flow-edge")
const t=S("title");g.appendChild(t)
rec={g,title:t,hit:S("path",{d:""},"flow-edge-hit"),line:S("path",{d:""},"flow-edge-line"),flow:S("path",{d:""},"flow-edge-flow"),arrow:S("path",{d:""},"flow-edge-arrow"),edge:e}
g.appendChild(rec.hit);g.appendChild(rec.line);g.appendChild(rec.flow);g.appendChild(rec.arrow)
edgesLayer.appendChild(g);st.edgeEls.set(e.id,rec);fresh=true
}
rec.edge=e
if(fresh||!want||want.has(e.from)||want.has(e.to)){rec.title.textContent=e.port;edgeGeom(e,rec);decorateEdge(e.id)}
})
st.edgeEls.forEach((rec,id)=>{if(!alive.has(id)){if(rec.g.parentNode)rec.g.parentNode.removeChild(rec.g);st.edgeEls.delete(id);st.selEdges.delete(id)}})
markFreePorts();placeEdgeTools()
}
// An output port with nothing connected offers a "+" (click it to add the next node).
function markFreePorts(){
const used=new Set();st.graph.edges.forEach((e)=>used.add(e.from+"\u0000"+e.port))
st.nodeEls.forEach((el,id)=>{if(el.querySelectorAll)el.querySelectorAll(".flow-port-out").forEach((p)=>p.classList.toggle("is-free",!used.has(id+"\u0000"+p.getAttribute("data-port"))))})
}
function clearLayer(el){while(el.firstChild)el.removeChild(el.firstChild)}
function renderAll(){
clearLayer(notesLayer);clearLayer(edgesLayer);clearLayer(nodesLayer)
st.nodeEls.clear();st.edgeEls.clear()
const ids=new Set(st.graph.nodes.map((n)=>n.id)),edgeIds=new Set(st.graph.edges.map((e)=>e.id))
let selChanged=false
Array.from(st.sel).forEach((id)=>{if(!ids.has(id)){st.sel.delete(id);selChanged=true}})
Array.from(st.selEdges).forEach((id)=>{if(!edgeIds.has(id))st.selEdges.delete(id)})
st.graph.nodes.forEach((n)=>mountNode(n,false))
syncEdges(null)
refreshChrome();scheduleMini()
return selChanged
}
function refreshChrome(){
tb.undo.disabled=st.readOnly||!st.history.canUndo();tb.redo.disabled=st.readOnly||!st.history.canRedo()
tb.layout.disabled=st.readOnly;tb.add.disabled=st.readOnly;tb.note.disabled=st.readOnly||st.graph.nodes.length>=FLOW_LIMITS.nodes
tb.snap.classList.toggle("is-on",st.prefs.snap);tb.snap.setAttribute("aria-pressed",st.prefs.snap?"true":"false")
tb.minimap.classList.toggle("is-on",st.prefs.minimap);tb.minimap.setAttribute("aria-pressed",st.prefs.minimap?"true":"false")
minimap.hidden=!st.prefs.minimap
root.classList.toggle("is-readonly",st.readOnly)
const full=st.graph.nodes.length>=FLOW_LIMITS.nodes,hasStart=flowHasStart(st.graph)
palItems.forEach((b)=>{b.disabled=st.readOnly||full||(b.dataset.type==="start"&&hasStart)})
hotbar.hidden=st.readOnly
emptyHint.hidden=st.readOnly||st.graph.nodes.filter((n)=>n.type!=="start").length>0
}
// ---- minimap
function scheduleMini(){if(st.miniRaf||st.destroyed||!st.prefs.minimap)return;st.miniRaf=raf(drawMini)}
function viewRect(box){box=box||stageBox();return {x:st.view.x,y:st.view.y,w:box.w/st.view.zoom,h:box.h/st.view.zoom}}
function drawMini(){
st.miniRaf=0
if(st.destroyed||!st.prefs.minimap)return
const box=stageBox();if(!(box.w>0)||!(box.h>0))return
const vr=viewRect(box)
let mm=st.drag&&st.drag.type==="mini"?st.drag.mm:null
if(!mm){
const b=flowGraphBounds(st.graph)||vr
const x0=Math.min(b.x,vr.x),y0=Math.min(b.y,vr.y),x1=Math.max(b.x+b.w,vr.x+vr.w),y1=Math.max(b.y+b.h,vr.y+vr.h)
mm=flowMiniMap({x:x0,y:y0,w:x1-x0,h:y1-y0},MINI_W,MINI_H,6)
}
st.mm=mm
const nodes=st.graph.nodes
for(let i=0;i<nodes.length;i++){
const n=nodes[i],s=flowNodeSize(n),p=flowMiniToMini(mm,n.x,n.y),t=FLOW_NODE_TYPES[n.type]
let el=st.miniRects[i];if(!el){el=S("rect",{rx:1});miniNodes.appendChild(el);st.miniRects[i]=el}
setA(el,"class","flow-minimap-node flow-cat-"+css(t?t.color:"unknown")+(st.sel.has(n.id)?" is-selected":""))
setA(el,"x",r1(p.x));setA(el,"y",r1(p.y));setA(el,"width",r1(Math.max(2,s.w*mm.s)));setA(el,"height",r1(Math.max(2,s.h*mm.s)))
}
while(st.miniRects.length>nodes.length){const el=st.miniRects.pop();if(el.parentNode)el.parentNode.removeChild(el)}
const p=flowMiniToMini(mm,vr.x,vr.y)
setA(miniView,"x",r1(p.x));setA(miniView,"y",r1(p.y));setA(miniView,"width",r1(Math.max(4,vr.w*mm.s)));setA(miniView,"height",r1(Math.max(4,vr.h*mm.s)))
}
function miniPoint(e){const r=st.drag&&st.drag.type==="mini"&&st.drag.rect?st.drag.rect:miniSvg.getBoundingClientRect();return {x:(e.clientX-r.left)*(r.width>0?MINI_W/r.width:1),y:(e.clientY-r.top)*(r.height>0?MINI_H/r.height:1)}}
on(minimap,"pointerdown",(e)=>{
if(e.button!==0||st.drag||!st.mm)return
e.preventDefault();e.stopPropagation()
const mm=st.mm,p=miniPoint(e),w=flowMiniToWorld(mm,p.x,p.y),box=stageBox(),vr=viewRect(box)
const inside=w.x>=vr.x&&w.x<=vr.x+vr.w&&w.y>=vr.y&&w.y<=vr.y+vr.h
// grabbing the rectangle keeps the grab point; clicking elsewhere centres the view there
const mr=miniSvg.getBoundingClientRect()
st.drag={type:"mini",pid:e.pointerId,mm,off:inside?{x:w.x-(vr.x+vr.w/2),y:w.y-(vr.y+vr.h/2)}:{x:0,y:0},rect:{left:mr.left,top:mr.top,width:mr.width,height:mr.height}}
st.box=box
try{minimap.setPointerCapture(e.pointerId)}catch(err){}
minimap.classList.add("is-dragging")
miniMove(e)
})
function miniMove(e){
const d=st.drag;if(!d||d.type!=="mini"||e.pointerId!==d.pid)return
const p=miniPoint(e),w=flowMiniToWorld(d.mm,p.x,p.y),vr=viewRect()
st.view={x:w.x-d.off.x-vr.w/2,y:w.y-d.off.y-vr.h/2,zoom:st.view.zoom}
applyView()
}
function miniEnd(e){
const d=st.drag;if(!d||d.type!=="mini"||(e&&e.pointerId!==d.pid))return
try{minimap.releasePointerCapture(d.pid)}catch(err){}
minimap.classList.remove("is-dragging");st.drag=null;st.box=null;scheduleMini()
}
on(minimap,"pointermove",miniMove);on(minimap,"pointerup",miniEnd);on(minimap,"pointercancel",miniEnd);on(minimap,"lostpointercapture",miniEnd)
// ---- selection
function setSelection(nodeIds,edgeIds,silent){
const next=new Set((nodeIds||[]).filter((id)=>st.nodeEls.has(id))),nextE=new Set((edgeIds||[]).filter((id)=>st.edgeEls.has(id)))
let changed=next.size!==st.sel.size;if(!changed)next.forEach((id)=>{if(!st.sel.has(id))changed=true})
const touched=new Set([...st.sel,...next]),touchedE=new Set([...st.selEdges,...nextE])
st.sel=next;st.selEdges=nextE
touched.forEach(decorateNode);touchedE.forEach(decorateEdge)
placeEdgeTools();scheduleMini()
if(changed&&!silent)call("onSelect",Array.from(st.sel))
return changed
}
function getSelection(){return Array.from(st.sel)}
// ---- history / change notification
function exportGraph(){const g=flowClone(st.graph);g.viewport={x:r1(st.view.x),y:r1(st.view.y),zoom:Math.round(st.view.zoom*1000)/1000};return g}
// Records the current graph as an undo step. Calls with the same key within a second replace the previous step (typing, nudging).
function commit(key){
const now=Date.now()
let changed
if(key&&st.lastKey===key&&now-st.lastT<1000&&st.history.canUndo()&&!st.history.canRedo())changed=st.history.replace(st.graph)
else changed=st.history.push(st.graph)
st.lastKey=key||null;st.lastT=now
refreshChrome();scheduleMini()
if(changed===false)return false
if(opts.autoValidate)setIssues(flowValidate(st.graph))
call("onChange",exportGraph())
return true
}
function restore(g){
if(!g)return false
stopNoteEdit(false)
g.viewport=flowClone(st.view);st.graph=g;st.lastKey=null
const selChanged=renderAll()
if(opts.autoValidate)setIssues(flowValidate(st.graph))
call("onChange",exportGraph())
if(selChanged)call("onSelect",Array.from(st.sel))
return true
}
function undo(){if(st.readOnly||st.drag)return false;return restore(st.history.undo())}
function redo(){if(st.readOnly||st.drag)return false;return restore(st.history.redo())}
// ---- view commands
function zoomAtLocal(px,py,zoom){st.view=flowViewZoomAt(st.view,px,py,zoom);applyView()}
function zoomTo(z){const b=stageBox();zoomAtLocal(b.w/2,b.h/2,z)}
function zoomBy(f){zoomTo(st.view.zoom*f)}
// minZoom: a diagram too wide to read when shown whole opens at that zoom on its first nodes instead (opening a chain).
function fit(minZoom){
const b=stageBox()
if(!(b.w>10)||!(b.h>10)){st.pendingFit=true;return}
st.pendingFit=false
const gb=flowGraphBounds(st.graph)
let v=flowViewFit(gb,b.w,b.h,64)
if(gb&&Number(minZoom)>0&&v.zoom<minZoom){const z=flowClampZoom(minZoom),start=st.graph.nodes.find((n)=>n.type==="start")||st.graph.nodes[0];v={x:Math.min(start.x,gb.x+gb.w-b.w/z)-64/z,y:(gb.h*z<=b.h-150?gb.y+gb.h/2:start.y+flowNodeSize(start).h/2)-b.h/(2*z),zoom:z}}
st.view=v;applyView()
}
// Opening a diagram: keep its saved viewport when that shows part of the diagram, otherwise fit. The untouched default
// viewport ({0,0,1}) counts as "never placed". While the editor has no size yet (hidden tab) the choice waits for the first resize.
function autoView(vp){
st.view={x:Number(vp&&vp.x)||0,y:Number(vp&&vp.y)||0,zoom:flowClampZoom(vp&&vp.zoom)}
const b=stageBox()
if(!(b.w>10)||!(b.h>10)){st.pendingFit=true;applyView();return}
st.pendingFit=false
const fresh=st.view.x===0&&st.view.y===0&&st.view.zoom===1
if(!fresh&&flowViewSees(st.view,b.w,b.h,flowGraphBounds(st.graph)))applyView()
else fit(0.6)
}
function getPrefs(){return {snap:st.prefs.snap,grid:st.prefs.grid,minimap:st.prefs.minimap,hotbar:st.prefs.hotbar.slice()}}
function setPref(name,value){
st.prefs[name]=value
refreshChrome();applyView();scheduleMini()
call("onPrefs",getPrefs())
}
// ---- editing commands
function snapGrid(){return st.prefs.snap?st.prefs.grid:0}
function addNodeAt(type,clientX,clientY,item){
if(st.readOnly||!FLOW_NODE_TYPES[type])return null
const probe={type,config:Object.assign(flowDefaultConfig(type),(item&&item.config)||{})},size=flowNodeSize(probe),box=stageBox(),g=snapGrid()
let x,y
if(typeof clientX==="number"&&typeof clientY==="number"){const w=worldPoint(clientX,clientY,box);x=w.x-size.w/2;y=w.y-Math.min(size.h/2,30)}
else{
const c=flowViewToWorld(st.view,box.w/2,box.h/2);x=c.x-size.w/2;y=c.y-size.h/2
// cascade so repeated clicks do not stack nodes exactly on top of each other
for(let i=0;i<40&&st.graph.nodes.some((n)=>Math.abs(n.x-flowSnap(x,g))<10&&Math.abs(n.y-flowSnap(y,g))<10);i++){x+=20;y+=20}
}
const node=flowAddNode(st.graph,type,flowSnap(x,g),flowSnap(y,g),item&&item.config)
if(!node)return null
if(item&&item.title)node.title=String(item.title).slice(0,FLOW_LIMITS.title_chars)
mountNode(node,false)
setSelection([node.id],[])
syncEdges([]);commit()
return flowClone(node)
}
// Adds a catalog item (a type or a preset). pending.from/port: wired to that output; pending.edge: inserted on that connection.
// With nothing pending and exactly one node selected, the new node continues from its first free output.
function placeNew(item,at,pending){
if(st.readOnly||!item||!FLOW_NODE_TYPES[item.type])return null
const g=snapGrid(),G=FLOW_GEOM,spec=FLOW_NODE_TYPES[item.type]
const probe={type:item.type,config:Object.assign(flowDefaultConfig(item.type),item.config||{})},size=flowNodeSize(probe),inY=G.head+G.sum+G.row/2
pending=pending||null
let edge=pending&&pending.edge?flowFindEdge(st.graph,pending.edge):null
if(!pending&&!at&&st.sel.size===1&&spec.input){
const sel=flowFindNode(st.graph,Array.from(st.sel)[0])
if(sel&&sel.type!=="comment"){const free=flowNodePorts(sel).out.find((p)=>!st.graph.edges.some((e)=>e.from===sel.id&&e.port===p));if(free)pending={from:sel.id,port:free}}
}
const src=pending&&pending.from?flowFindNode(st.graph,pending.from):null
let x,y
if(at){x=at.x-(src||edge?0:size.w/2);y=at.y-(src||edge?inY:Math.min(size.h/2,30));if(edge)x=at.x-size.w/2}
else if(src){const p=flowPortPos(src,"out",pending.port);x=src.x+flowNodeSize(src).w+80;y=p.y-inY}
else{const box=stageBox(),c=flowViewToWorld(st.view,box.w/2,box.h/2);x=c.x-size.w/2;y=c.y-size.h/2}
x=flowSnap(x,g);y=flowSnap(y,g)
// never exactly on top of another node
for(let i=0;i<40&&st.graph.nodes.some((n)=>n.type!=="comment"&&Math.abs(n.x-x)<size.w*0.6&&Math.abs(n.y-y)<size.h*0.8);i++)y=flowSnap(y+size.h+30,g)
const node=flowAddNode(st.graph,item.type,x,y,item.config)
if(!node)return null
if(item.title)node.title=String(item.title).slice(0,FLOW_LIMITS.title_chars)
let made=null,twin=null
if(src&&spec.input){made=flowConnect(st.graph,src.id,pending.port,node.id);if(made)twin=flowAutoWireTwin(st.graph,made)}
else if(edge&&spec.input){
const outs=flowNodePorts(node).out
flowRemoveEdges(st.graph,[edge.id])
flowConnect(st.graph,edge.from,edge.port,node.id)
if(outs.length)flowConnect(st.graph,node.id,outs[0],edge.to)
}
mountNode(node,false);syncEdges([node.id])
setSelection([node.id],[])
commit()
if(twin){const to=flowFindNode(st.graph,twin.to),from=flowFindNode(st.graph,twin.from);call("onAutoWire",{edge:flowClone(made),twin:flowClone(twin),from:from?from.title||from.id:twin.from,to:to?to.title||to.id:twin.to})}
return flowClone(node)
}
function deleteSelection(){
if(st.readOnly)return false
// the Start node stays: a diagram always has exactly one
const ids=Array.from(st.sel).filter((id)=>{const n=flowFindNode(st.graph,id);return n&&n.type!=="start"}),edgeIds=Array.from(st.selEdges)
if(!ids.length&&!edgeIds.length)return false
if(st.editing&&ids.indexOf(st.editing)>=0)stopNoteEdit(false)
flowRemoveNodes(st.graph,ids);flowRemoveEdges(st.graph,edgeIds)
const keep=Array.from(st.sel).filter((id)=>ids.indexOf(id)<0)
st.sel=new Set(keep);st.selEdges=new Set()
renderAll();commit()
call("onSelect",Array.from(st.sel))
return true
}
function copy(){
if(!st.sel.size)return false
flowEditorClip=flowCopy(st.graph,Array.from(st.sel));st.pasteN=0
return true
}
function cut(){if(st.readOnly||!copy())return false;return deleteSelection()}
function pasteClip(clip,offset){
if(st.readOnly||!clip||!clip.nodes||!clip.nodes.length)return false
const made=flowPaste(st.graph,clip,offset,offset)
if(!made.length)return false
renderAll();setSelection(made,[]);commit()
return true
}
function paste(){
if(!flowEditorClip)return false
st.pasteN++
return pasteClip(flowEditorClip,st.pasteN*Math.max(20,st.prefs.grid))
}
function duplicate(){if(!st.sel.size)return false;return pasteClip(flowCopy(st.graph,Array.from(st.sel)),Math.max(20,st.prefs.grid)*2)}
function selectAll(){setSelection(st.graph.nodes.map((n)=>n.id),[])}
function autoLayout(){
if(st.readOnly)return false
flowAutoLayout(st.graph,{grid:st.prefs.grid})
renderAll();commit();fit()
return true
}
function moveEls(ids){
ids.forEach((id)=>{const n=flowFindNode(st.graph,id),el=st.nodeEls.get(id);if(n&&el)place(el,n)})
}
function edgesOf(ids){const set=new Set(ids);return st.graph.edges.filter((e)=>set.has(e.from)||set.has(e.to))}
function refreshEdges(edges){edges.forEach((e)=>{const rec=st.edgeEls.get(e.id);if(rec)edgeGeom(e,rec)});placeEdgeTools()}
function nudge(dx,dy){
if(st.readOnly||!st.sel.size)return false
const ids=Array.from(st.sel)
flowMoveNodes(st.graph,ids,dx,dy,0)
moveEls(ids);refreshEdges(edgesOf(ids));if(st.editing)placeNoteInput()
commit("nudge")
return true
}
// Inspector edits: patch is a function (node,graph) that mutates the node (or returns fields to merge), or an object to merge.
function updateNode(id,patch){
const n=flowFindNode(st.graph,id);if(!n)return false
const before=flowNodePorts(n).out,type=n.type
let out=patch
if(typeof patch==="function")out=patch(n,st.graph)
if(out&&typeof out==="object"&&out!==n){
Object.keys(out).forEach((k)=>{if(k==="config"&&out.config&&typeof out.config==="object"&&!Array.isArray(out.config))n.config=Object.assign(n.config||{},out.config);else if(k!=="id"&&k!=="type")n[k]=out[k]})
}
n.id=id;n.type=type
if(typeof n.title!=="string")n.title=String(n.title==null?"":n.title)
if(n.title.length>FLOW_LIMITS.title_chars)n.title=n.title.slice(0,FLOW_LIMITS.title_chars)
n.x=Number.isFinite(Number(n.x))?Number(n.x):0;n.y=Number.isFinite(Number(n.y))?Number(n.y):0
if(!n.config||typeof n.config!=="object")n.config={}
flowReconcilePorts(st.graph,id,before)
mountNode(n,true);syncEdges([id])
if(st.editing===id)placeNoteInput()
return commit("node:"+id)
}
// ---- sticky note text: an HTML textarea laid over the note
function placeNoteInput(){
const n=flowFindNode(st.graph,st.editing);if(!n)return
const s=flowNodeSize(n),p=flowViewToScreen(st.view,n.x,n.y),z=st.view.zoom
noteInput.style.left=r1(p.x)+"px";noteInput.style.top=r1(p.y)+"px"
noteInput.style.width=r1(s.w*z)+"px";noteInput.style.height=r1(s.h*z)+"px"
noteInput.style.fontSize=r1(12*z)+"px";noteInput.style.padding=r1(8*z)+"px "+r1(10*z)+"px"
}
function startNoteEdit(id){
const n=flowFindNode(st.graph,id)
if(st.readOnly||!n||n.type!=="comment")return false
if(st.editing)stopNoteEdit(true)
st.editing=id
noteInput.value=String((n.config&&n.config.text)||"")
noteInput.className="flow-comment-input flow-comment-"+css(FLOW_COMMENT_COLORS.indexOf(n.config&&n.config.color)>=0?n.config.color:"yellow")
noteInput.hidden=false;placeNoteInput();decorateNode(id)
try{noteInput.focus({preventScroll:true})}catch(err){noteInput.focus()}
return true
}
function stopNoteEdit(save){
const id=st.editing;if(!id)return
st.editing=null;noteInput.hidden=true
const n=flowFindNode(st.graph,id),text=noteInput.value.slice(0,4000)
if(save&&n&&String((n.config&&n.config.text)||"")!==text)updateNode(id,(node)=>{node.config.text=text})
else decorateNode(id)
}
on(noteInput,"blur",()=>stopNoteEdit(true))
on(noteInput,"keydown",(e)=>{
if(e.key==="Escape"){e.preventDefault();e.stopPropagation();stopNoteEdit(false);focus()}
else if(e.key==="Enter"&&(e.ctrlKey||e.metaKey)){e.preventDefault();e.stopPropagation();stopNoteEdit(true);focus()}
})
on(noteInput,"pointerdown",(e)=>e.stopPropagation())
on(noteInput,"wheel",(e)=>e.stopPropagation())
function openNode(id){
const n=flowFindNode(st.graph,id);if(!n)return
if(n.type==="comment"&&!st.readOnly){startNoteEdit(id);return}
call("onOpenNode",id)
}
// ---- canvas pointer handling
function capture(el,pid){try{el.setPointerCapture(pid)}catch(err){}}
function release(el,pid){try{el.releasePointerCapture(pid)}catch(err){}}
function closest(target,sel){return target&&target.closest?target.closest(sel):null}
function startPan(e,box){
st.drag={type:"pan",pid:e.pointerId,sx:e.clientX,sy:e.clientY,view:flowClone(st.view),k:box.k}
root.classList.add("is-panning")
}
function onCanvasDown(e){
if(st.drag||st.destroyed)return
if(e.button!==0&&e.button!==1)return
if(st.editing)stopNoteEdit(true)
if(st.pick)closePicker()
focus()
const box=stageBox(),w=worldPoint(e.clientX,e.clientY,box)
const nodeEl=closest(e.target,".flow-node"),id=nodeEl?nodeEl.getAttribute("data-id"):null
const multi=e.shiftKey||e.ctrlKey||e.metaKey
if(e.button===1||st.space){e.preventDefault();startPan(e,box)}
else if(id&&!st.readOnly&&closest(e.target,".flow-port-out")){
const port=closest(e.target,".flow-port-out").getAttribute("data-port"),valid=new Set()
st.graph.nodes.forEach((n)=>{if(!flowConnectRefusal(st.graph,id,port,n.id))valid.add(n.id)})
valid.forEach((v)=>{const el=st.nodeEls.get(v);if(el)el.classList.add("is-valid-target")})
st.drag={type:"connect",pid:e.pointerId,from:id,port,valid,over:null,sx:e.clientX,sy:e.clientY,moved:false,last:w}
root.classList.add("is-connecting");nodeEl.classList.add("is-connect-source")
dragConnect(w)
}
else if(id&&!st.readOnly&&closest(e.target,".flow-comment-resize")){
const n=flowFindNode(st.graph,id),s=flowNodeSize(n)
if(!st.sel.has(id)||st.sel.size>1)setSelection([id],[])
st.drag={type:"resize",pid:e.pointerId,id,start:w,w0:s.w,h0:s.h,moved:false}
}
else if(id){
if(multi){const next=new Set(st.sel);if(next.has(id))next.delete(id);else next.add(id);setSelection(Array.from(next),Array.from(st.selEdges));st.drag={type:"press",pid:e.pointerId,id:null}}
else{
const wasOnly=st.sel.has(id)&&st.sel.size===1&&!st.selEdges.size
if(!st.sel.has(id))setSelection([id],[])
const ids=Array.from(st.sel)
st.drag={type:st.readOnly?"press":"move",pid:e.pointerId,id,wasOnly,ids,start:w,sx:e.clientX,sy:e.clientY,moved:false,onStatus:!!closest(e.target,".flow-node-status"),
orig:ids.map((nid)=>{const n=flowFindNode(st.graph,nid);return {id:nid,x:n.x,y:n.y}}),edges:edgesOf(ids)}
}
}
else if(closest(e.target,".flow-edge")){
const eid=closest(e.target,".flow-edge").getAttribute("data-id")
if(multi){const next=new Set(st.selEdges);if(next.has(eid))next.delete(eid);else next.add(eid);setSelection(Array.from(st.sel),Array.from(next))}
else setSelection([],[eid])
st.drag={type:"press",pid:e.pointerId,id:null}
}
else if(st.readOnly)startPan(e,box)
else{
const p=localPoint(e.clientX,e.clientY,box)
st.drag={type:"box",pid:e.pointerId,p0:p,w0:w,add:multi,base:Array.from(st.sel),baseE:Array.from(st.selEdges),moved:false}
}
if(st.drag){st.drag.ev={x:e.clientX,y:e.clientY};st.box=box;capture(surface,e.pointerId);placeEdgeTools()}
}
function dragConnect(w){
const d=st.drag,a=flowFindNode(st.graph,d.from);if(!a)return
const p=flowPortPos(a,"out",d.port)
const hit=flowHitNode(st.graph,w.x,w.y,6),over=hit&&d.valid.has(hit.id)?hit.id:null
if(over!==d.over){
if(d.over&&st.nodeEls.get(d.over))st.nodeEls.get(d.over).classList.remove("is-drop-target")
if(over&&st.nodeEls.get(over))st.nodeEls.get(over).classList.add("is-drop-target")
d.over=over
}
// over a valid node the rubber band snaps to its input port
const q=over?flowPortPos(flowFindNode(st.graph,over),"in"):w
d.last=w
rubber.setAttribute("d",flowEdgePath(p.x+6,p.y,q.x-(over?8:0),q.y))
}
function applyDrag(){
st.dragRaf=0
const d=st.drag;if(!d||!d.ev||st.destroyed)return
const box=stageBox(),w=worldPoint(d.ev.x,d.ev.y,box)
if(d.type==="pan"){st.view=flowViewPan(d.view,(d.ev.x-d.sx)/box.k,(d.ev.y-d.sy)/box.k);applyView()}
else if(d.type==="move"){
if(!d.moved&&Math.abs(d.ev.x-d.sx)<4&&Math.abs(d.ev.y-d.sy)<4)return
d.moved=true
let dx=w.x-d.start.x,dy=w.y-d.start.y
const g=snapGrid(),lead=d.orig.find((o)=>o.id===d.id)||d.orig[0]
if(g>0){dx=flowSnap(lead.x+dx,g)-lead.x;dy=flowSnap(lead.y+dy,g)-lead.y}
d.orig.forEach((o)=>{const n=flowFindNode(st.graph,o.id);if(n){n.x=o.x+dx;n.y=o.y+dy}})
moveEls(d.ids);refreshEdges(d.edges);scheduleMini()
}
else if(d.type==="connect"){if(!d.moved&&(Math.abs(d.ev.x-d.sx)>=5||Math.abs(d.ev.y-d.sy)>=5))d.moved=true;dragConnect(w)}
else if(d.type==="resize"){
const n=flowFindNode(st.graph,d.id);if(!n)return
const g=snapGrid(),G=FLOW_GEOM
const nw=Math.min(G.commentMaxW,Math.max(G.commentMinW,flowSnap(d.w0+w.x-d.start.x,g))),nh=Math.min(G.commentMaxH,Math.max(G.commentMinH,flowSnap(d.h0+w.y-d.start.y,g)))
if(nw===n.config.w&&nh===n.config.h)return
d.moved=true;n.config.w=nw;n.config.h=nh
mountNode(n,true);scheduleMini()
}
else if(d.type==="box"){
const p=localPoint(d.ev.x,d.ev.y,box),r=flowBoxRect(d.p0.x,d.p0.y,p.x,p.y)
if(!d.moved&&r.w<4&&r.h<4)return
d.moved=true
selBox.style.left=r1(r.x)+"px";selBox.style.top=r1(r.y)+"px";selBox.style.width=r1(r.w)+"px";selBox.style.height=r1(r.h)+"px"
selBox.classList.add("is-active")
const hits=flowBoxHits(st.graph,flowBoxRect(d.w0.x,d.w0.y,w.x,w.y))
setSelection(d.add?Array.from(new Set(d.base.concat(hits))):hits,d.add?d.baseE:[],true)
}
}
function onCanvasMove(e){
const d=st.drag
if(!d||d.type==="mini"){hoverTip(e);return}
if(e.pointerId!==d.pid)return
d.ev={x:e.clientX,y:e.clientY}
if(!st.dragRaf)st.dragRaf=raf(applyDrag)
}
function clearDragChrome(){
root.classList.remove("is-panning","is-connecting")
selBox.classList.remove("is-active");selBox.style.width="0px";selBox.style.height="0px"
rubber.setAttribute("d","")
st.nodeEls.forEach((el)=>el.classList.remove("is-valid-target","is-drop-target","is-connect-source"))
}
function endDrag(e,cancelled){
const d=st.drag
if(!d||d.type==="mini")return
if(e&&e.pointerId!==d.pid)return
if(e&&!cancelled){d.ev={x:e.clientX,y:e.clientY}}
if(st.dragRaf){caf(st.dragRaf);st.dragRaf=0}
if(!cancelled)applyDrag()
const dropBox=d.type==="connect"&&!cancelled?stageBox():null
st.drag=null;st.box=null
release(surface,d.pid)
const selBefore=d.type==="box"?JSON.stringify(d.base.slice().sort()):null
if(cancelled){
if(d.type==="move"&&d.moved){d.orig.forEach((o)=>{const n=flowFindNode(st.graph,o.id);if(n){n.x=o.x;n.y=o.y}});moveEls(d.ids);refreshEdges(d.edges)}
else if(d.type==="resize"&&d.moved){const n=flowFindNode(st.graph,d.id);if(n){n.config.w=d.w0;n.config.h=d.h0;mountNode(n,true)}}
else if(d.type==="box")setSelection(d.base,d.baseE,true)
else if(d.type==="pan"){st.view=d.view;applyView()}
}
else if(d.type==="move"){
if(d.moved)commit()
else{
// a plain click on one node of a multi-selection narrows the selection to it; a second quick click opens it
if(st.sel.size>1||st.selEdges.size)setSelection([d.id],[])
const now=Date.now()
if(d.onStatus){st.lastClick=null;call("onOpenNode",d.id,"output")}
else if(st.lastClick&&st.lastClick.id===d.id&&now-st.lastClick.t<400){st.lastClick=null;openNode(d.id)}
else st.lastClick={id:d.id,t:now}
}
}
else if(d.type==="press"&&d.id){
const now=Date.now()
if(st.lastClick&&st.lastClick.id===d.id&&now-st.lastClick.t<400){st.lastClick=null;openNode(d.id)}
else st.lastClick={id:d.id,t:now}
}
else if(d.type==="connect"){
if(d.over){
const edge=flowConnect(st.graph,d.from,d.port,d.over)
if(edge){
// a command wired to a decision: its other result port follows, in the same undo step
const twin=flowAutoWireTwin(st.graph,edge)
syncEdges([]);setSelection([],[edge.id]);commit()
if(twin){const to=flowFindNode(st.graph,twin.to),from=flowFindNode(st.graph,twin.from);call("onAutoWire",{edge:flowClone(edge),twin:flowClone(twin),from:from?from.title||from.id:twin.from,to:to?to.title||to.id:twin.to})}
}
}
// dropped on empty canvas (or the port was just clicked): pick the next node, it comes wired in
else if(!d.moved||!flowHitNode(st.graph,d.last.x,d.last.y,6)){
clearDragChrome()
const keep=d.moved?rubber.getAttribute("d"):""
openPicker({world:d.moved?d.last:null,pending:{from:d.from,port:d.port}})
if(keep&&st.pick)rubber.setAttribute("d",keep)
scheduleMini();return
}
}
else if(d.type==="resize"){if(d.moved)commit()}
else if(d.type==="box"){
if(!d.moved&&!d.add)setSelection([],[],true)
if(!d.moved&&!st.readOnly&&e){const now=Date.now();if(now-st.lastEmpty<400){st.lastEmpty=0;clearDragChrome();openPicker({clientX:e.clientX,clientY:e.clientY});return}st.lastEmpty=now}
if(JSON.stringify(Array.from(st.sel).sort())!==selBefore)call("onSelect",Array.from(st.sel))
}
clearDragChrome();placeEdgeTools();scheduleMini()
}
function hoverTip(e){
const badge=closest(e.target,".flow-node-badge"),nodeEl=badge?closest(badge,".flow-node"):null
const issue=nodeEl?st.issues.nodes[nodeEl.getAttribute("data-id")]:null
if(!issue){if(!tip.hidden)tip.hidden=true;return}
const box=stageBox(),p=localPoint(e.clientX,e.clientY,box)
tip.textContent=issue.text;tip.className="flow-tooltip is-"+issue.level;tip.hidden=false
tip.style.left=Math.max(4,Math.min(p.x+14,box.w-270))+"px";tip.style.top=Math.max(4,p.y+16)+"px"
}
on(surface,"pointerdown",onCanvasDown)
on(surface,"pointermove",onCanvasMove)
on(surface,"pointerup",(e)=>endDrag(e,false))
on(surface,"pointercancel",(e)=>endDrag(e,true))
on(surface,"lostpointercapture",(e)=>{if(st.drag&&st.drag.type!=="mini"&&st.drag.pid===e.pointerId)endDrag(e,true)})
on(surface,"pointerleave",()=>{if(!tip.hidden)tip.hidden=true})
// middle button: stop autoscroll (WebView2) and primary-selection paste (Linux)
on(stage,"mousedown",(e)=>{if(e.button===1)e.preventDefault()})
on(stage,"auxclick",(e)=>{if(e.button===1)e.preventDefault()})
on(surface,"dblclick",(e)=>e.preventDefault())
on(stage,"wheel",(e)=>{
if(closest(e.target,".flow-comment-input")||closest(e.target,".flow-picker"))return
e.preventDefault()
const unit=e.deltaMode===1?16:e.deltaMode===2?400:1,dx=e.deltaX*unit,dy=e.deltaY*unit
const act=flowWheelAction(dx,dy,e.ctrlKey||e.metaKey,e.shiftKey)
if(act.type==="pan"){st.view=flowViewPan(st.view,-act.dx,-act.dy);applyView();return}
if(act.type!=="zoom")return
const p=localPoint(e.clientX,e.clientY)
zoomAtLocal(p.x,p.y,st.view.zoom*act.factor)
},{passive:false})
// ---- hot bar buttons: drag an item onto the canvas (pointer capture + a ghost), or click to add it
function bindAdder(b,item){
let d=null
const ghostAt=(e)=>{const r=root.getBoundingClientRect();d.ghost.style.left=(e.clientX-r.left+8)+"px";d.ghost.style.top=(e.clientY-r.top+8)+"px"}
const overStage=(e)=>{const r=surface.getBoundingClientRect(),h=hotbar.getBoundingClientRect();return e.clientX>=r.left&&e.clientX<=r.right&&e.clientY>=r.top&&e.clientY<=r.bottom&&!(e.clientX>=h.left&&e.clientX<=h.right&&e.clientY>=h.top&&e.clientY<=h.bottom)}
const finish=(e,cancelled)=>{
if(!d||(e&&e.pointerId!==d.pid))return
const cur=d;d=null
release(b,cur.pid)
if(cur.ghost&&cur.ghost.parentNode)cur.ghost.parentNode.removeChild(cur.ghost)
root.classList.remove("is-palette-drag")
st.palClickAt=Date.now()
if(cancelled||b.disabled)return
if(cur.moved){if(overStage(e))addNodeAt(item.type,e.clientX,e.clientY,item)}
else placeNew(item,null,null)
focus()
}
on(b,"pointerdown",(e)=>{
e.stopPropagation()
if(e.button!==0||b.disabled||d)return
if(st.pick)closePicker()
d={pid:e.pointerId,sx:e.clientX,sy:e.clientY,moved:false,ghost:null}
capture(b,e.pointerId)
})
on(b,"pointermove",(e)=>{
if(!d||e.pointerId!==d.pid)return
if(!d.moved){
if(Math.abs(e.clientX-d.sx)<5&&Math.abs(e.clientY-d.sy)<5)return
d.moved=true
d.ghost=H("div","flow-palette-ghost flow-cat-"+css(item.color||item.category));d.ghost.appendChild(H("i","icon icon-"+css(item.icon)));d.ghost.appendChild(H("span",null,item.label))
root.appendChild(d.ghost);root.classList.add("is-palette-drag")
}
ghostAt(e);d.ghost.classList.toggle("is-over",overStage(e))
})
on(b,"pointerup",(e)=>finish(e,false))
on(b,"pointercancel",(e)=>finish(e,true))
on(b,"lostpointercapture",(e)=>finish(e,true))
// keyboard activation (Enter/Space on the focused button): no pointer sequence came just before it
on(b,"click",()=>{if(Date.now()-st.palClickAt<600||d)return;placeNew(item,null,null)})
}
renderHotbar()
// ---- keyboard (only while focus is inside the editor, never while typing in a field)
function isTyping(t){return !!t&&(!!closest(t,"input,textarea,select")||t.isContentEditable===true)}
function onKeyDown(e){
if(st.destroyed||isTyping(e.target)||e.altKey)return
const mod=e.ctrlKey||e.metaKey,k=e.key,lk=k&&k.length===1?k.toLowerCase():k
const onButton=!!closest(e.target,"button")
let done=false
if(mod){
if(lk==="z")done=e.shiftKey?redo():undo(),done=true
else if(lk==="y"){redo();done=true}
else if(lk==="c"&&!e.shiftKey)done=copy()
else if(lk==="x"&&!e.shiftKey)done=cut()
else if(lk==="v"&&!e.shiftKey)done=!st.readOnly&&paste()
else if(lk==="a"&&!e.shiftKey){selectAll();done=true}
else if(lk==="d"&&!e.shiftKey){done=!st.readOnly&&!!st.sel.size;if(done)duplicate()}
else if(lk==="l"&&e.shiftKey){done=!st.readOnly;if(done)autoLayout()}
}
else if((k==="Tab"&&!e.shiftKey&&!onButton)||k==="/"){done=openPicker({})}
else if(k==="Delete"||k==="Backspace")done=deleteSelection()
else if(k==="ArrowLeft"||k==="ArrowRight"||k==="ArrowUp"||k==="ArrowDown"){
const sx=k==="ArrowLeft"?-1:k==="ArrowRight"?1:0,sy=k==="ArrowUp"?-1:k==="ArrowDown"?1:0
if(st.sel.size&&!st.readOnly){const step=(st.prefs.snap?st.prefs.grid:1)*(e.shiftKey?5:1);done=nudge(sx*step,sy*step)}
else{st.view=flowViewPan(st.view,-sx*60,-sy*60);applyView();done=true}
}
else if(k==="Escape"){
if(st.pick){closePicker();done=true}
else if(st.drag&&st.drag.type!=="mini"){endDrag(null,true);done=true}
else if(st.sel.size||st.selEdges.size){setSelection([],[]);done=true}
}
else if(k==="Enter"&&!onButton){if(st.sel.size===1){openNode(Array.from(st.sel)[0]);done=true}}
else if(k===" "&&!onButton){if(!st.space){st.space=true;root.classList.add("is-pan-ready")}done=true}
else if(lk==="f"){fit(0);done=true}
else if(k==="+"||k==="="){zoomBy(1.2);done=true}
else if(k==="-"||k==="_"){zoomBy(1/1.2);done=true}
else if(k==="0"){zoomTo(1);done=true}
if(done){e.preventDefault();e.stopPropagation()}
}
function spaceOff(){if(st.space){st.space=false;root.classList.remove("is-pan-ready")}}
on(root,"keydown",onKeyDown)
on(root,"keyup",(e)=>{if(e.key===" ")spaceOff()})
on(root,"focusout",(e)=>{if(!e.relatedTarget||!root.contains(e.relatedTarget))spaceOff()})
on(win,"blur",spaceOff)
if(typeof win.ResizeObserver==="function"){
const ro=new win.ResizeObserver(()=>{if(st.destroyed)return;if(st.pendingFit)autoView(st.view);else{if(st.editing)placeNoteInput();scheduleMini()}})
ro.observe(stage);cleanup.push(()=>ro.disconnect())
}
// ---- public API
function focus(){try{root.focus({preventScroll:true})}catch(err){root.focus()}}
function getGraph(){return exportGraph()}
function setGraph(g,o){
o=o||{}
if(st.drag)endDrag(null,true)
if(st.pick)closePicker()
stopNoteEdit(false)
let next
try{next=flowNormalize(flowClone(g||flowNewGraph()))}catch(err){next=flowNewGraph();if(win.console)win.console.error("flow editor: bad graph, showing an empty one",err)}
const hadSel=st.sel.size>0
st.graph=next;st.sel=new Set();st.selEdges=new Set();st.lastKey=null;st.lastClick=null
st.history.reset(st.graph)
renderAll()
if(o.keepView)applyView()
else autoView(next.viewport)
if(opts.autoValidate)setIssues(flowValidate(st.graph))
if(hadSel)call("onSelect",[])
}
function select(ids){setSelection(Array.isArray(ids)?ids:(ids==null?[]:[ids]),[],true)}
function setReadOnly(b){
b=!!b;if(b===st.readOnly)return
if(st.drag)endDrag(null,true)
if(st.pick)closePicker()
stopNoteEdit(true)
st.readOnly=b;refreshChrome();placeEdgeTools()
}
// Paints node states and taken edges from a run status JSON ({state,current,nodes:{id:{state}},edges_taken:[ids]}); null clears.
function setRunState(status){
st.run=status&&typeof status==="object"?status:null
root.classList.toggle("has-run",!!st.run)
root.classList.toggle("is-run-live",!!st.run&&["running","paused","waiting_approval"].indexOf(st.run.state)>=0)
st.nodeEls.forEach((el,id)=>decorateNode(id));st.edgeEls.forEach((rec,id)=>decorateEdge(id))
call("onRunState",st.run)
}
function setIssues(issues){
st.issues=flowIssueMap(issues)
st.nodeEls.forEach((el,id)=>decorateNode(id));st.edgeEls.forEach((rec,id)=>decorateEdge(id))
if(!tip.hidden)tip.hidden=true
}
function destroy(){
if(st.destroyed)return
st.destroyed=true
if(st.dragRaf)caf(st.dragRaf);if(st.miniRaf)caf(st.miniRaf)
cleanup.forEach((fn)=>{try{fn()}catch(err){}})
if(root.parentNode)root.parentNode.removeChild(root)
}
setGraph(opts.graph||flowNewGraph())
return {el:root,getGraph,setGraph,getSelection,select,updateNode,addNodeAt,deleteSelection,copy,cut,paste,duplicate,selectAll,undo,redo,canUndo:()=>st.history.canUndo(),canRedo:()=>st.history.canRedo(),autoLayout,fit,zoomTo,getView:()=>flowClone(st.view),getPrefs,setPrefs:(p)=>{if(!p)return;if(p.snap!=null)st.prefs.snap=!!p.snap;if(Number(p.grid)>0)st.prefs.grid=Number(p.grid);if(p.minimap!=null)st.prefs.minimap=!!p.minimap;if(Array.isArray(p.hotbar)){st.prefs.hotbar=flowHotbarClean(p.hotbar);renderHotbar()}refreshChrome();applyView()},getRunState:()=>st.run,openPicker,closePicker,placeNew,togglePin,setReadOnly,isReadOnly:()=>st.readOnly,setRunState,setIssues,getSelectedEdges:()=>Array.from(st.selEdges),editNote:startNoteEdit,focus,destroy}
}
if(typeof module!=="undefined"&&module.exports)module.exports={FLOW_RUN_BADGES,flowRunBadgeState,flowPillDuration,FLOW_EDITOR_SHORTCUTS,FLOW_ICON_SHAPES,flowClampZoom,flowViewToScreen,flowViewToWorld,flowViewZoomAt,flowViewPan,flowWheelAction,flowViewFit,flowViewSees,flowBoxRect,flowBoxHits,flowMiniMap,flowMiniToMini,flowMiniToWorld,flowWrapText,flowIssueMap,flowEditorCreate}
