// Where the AI panel sits: docked left (the default), right or bottom of the body row, chosen by dragging the panel
// header (panel-dock.js) or from the panel-position menu. Persisted in settings.json through ai.set_panel_layout.
// The AI panel is a sibling of #workArea, so it is always the outer panel when it shares a side with the terminal.
const aiDock={mode:"left",height:320}
function aiDockApplyLayout(){
const row=document.getElementById("bodyRow")
const panel=document.getElementById("aiPanel")
if(!row||!panel)return
const vp={width:window.innerWidth,height:window.innerHeight}
aiState.width=panelDockClampSize("left",aiState.width,vp)
aiDock.height=panelDockClampSize("bottom",aiDock.height,vp)
row.classList.toggle("ai-dock-right",aiDock.mode==="right")
row.classList.toggle("ai-dock-bottom",aiDock.mode==="bottom")
panel.style.width=aiDock.mode==="bottom"?"":aiState.width+"px"
panel.style.height=aiDock.mode==="bottom"?aiDock.height+"px":""
}
function aiDockApplyMode(mode,opts){
mode=panelDockNormalizeMode(mode,aiDock.mode)
if(mode===aiDock.mode)return
aiDock.mode=mode
aiDockApplyLayout()
bridgeCall("ai.set_panel_layout",[{mode:mode}]).catch(()=>{})
if(opts&&opts.fromDrag)showStatusIsland("AI panel docked "+mode)
}
function aiDockOpenMenu(anchorEl){
const box=anchorEl.getBoundingClientRect()
const modes=[["left","Dock left","align-left"],["right","Dock right","align-right"],["bottom","Dock bottom","align-center"]]
const items=modes.map(([mode,label,icon])=>({label:aiDock.mode===mode?label+"  ✓":label,icon:icon,fn:()=>panelDockMove("ai",mode)}))
items.push({sep:true})
items.push({label:"Tip: drag the panel header to an edge",icon:"grip",disabled:true,fn:()=>{}})
openContextMenu(items,Math.max(8,box.right-210),box.bottom+4)
}
// Called from initAI with the ai.get_settings result.
function aiDockInit(s){
aiState.width=s.panel_width
aiDock.mode=panelDockNormalizeMode(s.panel_mode,"left")
aiDock.height=s.panel_height||320
aiDockApplyLayout()
}
function aiDockWire(){
const panel=document.getElementById("aiPanel")
initSidePanelResize({handle:document.getElementById("aiResizeHandle"),panel:panel,config:()=>{
const vp={width:window.innerWidth,height:window.innerHeight}
if(aiDock.mode==="bottom")return {axis:"y",anchorSide:"bottom",min:PANEL_DOCK_MIN_BOTTOM,max:panelDockClampSize("bottom",1e6,vp)}
return {axis:"x",anchorSide:aiDock.mode==="right"?"right":"left",min:PANEL_DOCK_MIN_SIDE,max:panelDockClampSize("left",1e6,vp)}
},onCommit:(size,axis)=>{
if(axis==="y"){aiDock.height=size;bridgeCall("ai.set_panel_layout",[{height:size}]).catch(()=>{});return}
aiState.width=size
bridgeCall("ai.set_panel_width",[size]).catch(()=>{})
}})
panelDockRegister("ai",{label:"AI panel",getMode:()=>aiDock.mode,applyMode:aiDockApplyMode})
panelDockAttach({name:"ai",panel:panel,header:panel.querySelector(".ai-panel-head"),grip:document.getElementById("aiDockBtn"),area:()=>document.getElementById("bodyRow"),size:(mode)=>mode==="bottom"?aiDock.height:aiState.width,onDrop:(mode)=>panelDockMove("ai",mode,{fromDrag:true}),canDrag:()=>aiState.open})
const btn=document.getElementById("aiDockBtn")
if(btn)btn.addEventListener("click",(e)=>aiDockOpenMenu(e.currentTarget))
}
