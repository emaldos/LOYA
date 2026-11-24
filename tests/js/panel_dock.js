// Drag-to-dock helpers (UI/js/components/panel-dock.js) and the terminal header overflow plan (terminal.js).
const fs=require("fs")
const path=require("path")
const D=require("../../UI/js/components/panel-dock.js")
let passed=0,failed=0
function check(name,ok,detail){if(ok)passed++;else{failed++;console.log("FAIL: "+name+(detail?" - "+detail:""))}}
// ---- drop-zone hit-testing
const area={left:100,top:50,width:1200,height:800}
const z=D.panelDockZones(area)
check("left band hugs the left edge",z.left.left===100&&z.left.width>=64&&z.left.width<=180&&z.left.height===800)
check("right band hugs the right edge",z.right.left+z.right.width===1300)
check("bottom band sits between the side bands",z.bottom.left===z.left.left+z.left.width&&z.bottom.left+z.bottom.width===z.right.left&&z.bottom.top+z.bottom.height===850)
check("point near the left edge docks left",D.panelDockHitTest(z,110,400)==="left")
check("point near the right edge docks right",D.panelDockHitTest(z,1290,400)==="right")
check("point near the bottom edge docks bottom",D.panelDockHitTest(z,700,840)==="bottom")
check("bottom-left corner belongs to the left band only",D.panelDockHitTest(z,105,845)==="left")
check("centre of the area cancels",D.panelDockHitTest(z,700,400)===null)
check("outside the area cancels",D.panelDockHitTest(z,50,400)===null&&D.panelDockHitTest(z,700,900)===null&&D.panelDockHitTest(z,1300,400)===null)
const tiny=D.panelDockZones({left:0,top:0,width:300,height:200})
check("small areas still get usable bands",tiny.left.width===64&&tiny.bottom.height===56&&tiny.bottom.width===172)
// every point is in at most one zone
let overlaps=0
for(let x=100;x<1300;x+=7)for(let y=50;y<850;y+=7){const hits=["left","right","bottom"].filter((m)=>D.panelDockHitTest({[m]:z[m]},x,y));if(hits.length>1)overlaps++}
check("zones never overlap",overlaps===0)
const pl=D.panelDockPreviewRect(area,"left",380),pr=D.panelDockPreviewRect(area,"right",380),pb=D.panelDockPreviewRect(area,"bottom",320)
check("left preview",pl.left===100&&pl.width===380&&pl.height===800)
check("right preview",pr.left===920&&pr.width===380)
check("bottom preview",pb.top===530&&pb.height===320&&pb.width===1200)
check("preview never exceeds the area",D.panelDockPreviewRect({left:0,top:0,width:300,height:200},"left",900).width===300)
// ---- size clamping
const vp={width:1536,height:864}
check("side min is 320",D.PANEL_DOCK_MIN_SIDE===320&&D.panelDockClampSize("left",260,vp)===320&&D.panelDockClampSize("right",10,vp)===320)
check("bottom min is 180",D.PANEL_DOCK_MIN_BOTTOM===180&&D.panelDockClampSize("bottom",160,vp)===180)
check("side max is 900 on a wide screen",D.panelDockClampSize("right",5000,{width:2560,height:1440})===900)
check("side max follows a narrow window",D.panelDockClampSize("right",5000,{width:800,height:600})===600)
check("side max never drops below the min",D.panelDockClampSize("right",5000,{width:300,height:300})===320)
check("bottom max is 85% of the height",D.panelDockClampSize("bottom",5000,vp)===734)
check("garbage falls back to defaults",D.panelDockClampSize("left","wide",vp)===380&&D.panelDockClampSize("bottom",null,vp)===320)
check("in-range sizes are kept",D.panelDockClampSize("left",512.4,vp)===512&&D.panelDockClampSize("bottom",400,vp)===400)
// ---- terminal + AI rules
check("sides can be shared",JSON.stringify(D.panelDockResolve("terminal","left",{terminal:{mode:"right"},ai:{mode:"left"}}))==='{"terminal":"left"}')
check("bottom is exclusive: the other panel takes the mover's old side",JSON.stringify(D.panelDockResolve("terminal","bottom",{terminal:{mode:"right"},ai:{mode:"bottom"}}))==='{"terminal":"bottom","ai":"right"}')
check("AI to bottom pushes the terminal to the AI's old side",D.panelDockResolve("ai","bottom",{terminal:{mode:"bottom"},ai:{mode:"left"}}).terminal==="left")
check("a mover already at the bottom falls back to the default side",D.panelDockResolve("ai","bottom",{terminal:{mode:"bottom"},ai:{mode:"bottom"}}).terminal==="right")
// ---- drag start guard
function el(tag,cls,parent){const e={tagName:tag,cls:cls||"",parent:parent||null,contains(o){for(let n=o;n;n=n.parent)if(n===this)return true;return false},closest(sel){for(let n=this;n;n=n.parent){if(sel.split(",").some((s)=>s===n.tagName.toLowerCase()||(s[0]==="."&&n.cls.split(" ").includes(s.slice(1)))))return n}return null}};return e}
const head=el("DIV","terminal-panel-head"),row=el("DIV","terminal-panel-actions",head),btn=el("BUTTON","terminal-head-btn",row),icon=el("I","icon",btn),grip=el("BUTTON","terminal-head-btn",row),tabs=el("DIV","terminal-tabs",head),tab=el("SPAN","terminal-tab-label",tabs)
check("empty header space starts a drag",D.panelDockCanStartFrom(row,head,grip))
check("buttons (and their icons) never start a drag",!D.panelDockCanStartFrom(btn,head,grip)&&!D.panelDockCanStartFrom(icon,head,grip))
check("the tabs strip never starts a drag",!D.panelDockCanStartFrom(tab,head,grip))
check("the grip button does start a drag",D.panelDockCanStartFrom(grip,head,grip))
check("outside the header never starts a drag",!D.panelDockCanStartFrom(el("DIV","x"),head,grip))
check("threshold is 6px",D.PANEL_DOCK_DRAG_THRESHOLD===6)
// ---- generic overflow partition
const items=[{id:"a",width:26,priority:3},{id:"b",width:26,priority:1},{id:"c",width:26,priority:2},{id:"x",width:26,pinned:true}]
check("everything fits -> no overflow",D.panelDockOverflow(items,200,{gap:4,moreWidth:26}).overflow.length===0)
const o=D.panelDockOverflow(items,100,{gap:4,moreWidth:26})
check("highest priority number leaves first, pinned stays",JSON.stringify(o)==='{"visible":["b","x"],"overflow":["a","c"]}',JSON.stringify(o))
check("zero-width (hidden) items are ignored",D.panelDockOverflow([{id:"h",width:0,priority:1},{id:"v",width:26,priority:1}],30,{}).visible.join()==="v")
// ---- terminal header plan at real widths (26px buttons, 46px Clear; row = panel width - 22 for border+padding)
const src=fs.readFileSync(path.join(__dirname,"..","..","UI","js","components","terminal.js"),"utf8")
const a=src.indexOf("const TERM_HEAD_ITEMS"),b=src.indexOf("let termHeadFrame")
const T=new Function("panelDockOverflow",src.slice(a,b)+";return{TERM_HEAD_ITEMS,termHeadOverflowPlan}")(D.panelDockOverflow)
const widths={};T.TERM_HEAD_ITEMS.forEach((it)=>{widths[it.id]=it.id==="terminalClearBtn"?46:26})
const plan=(w)=>T.termHeadOverflowPlan(w-22,widths)
const p900=plan(900),p600=plan(600),p400=plan(400),p320=plan(320)
check("900 px: nothing overflows",p900.overflow.length===0)
check("600 px: nothing overflows",p600.overflow.length===0)
check("400 px: job blocks and record go to More",p400.overflow.join()==="terminalBlocksBtn,terminalRecordBtn",p400.overflow.join())
check("320 px: elevate, clear, blocks, record go to More",p320.overflow.join()==="terminalElevateBtn,terminalClearBtn,terminalBlocksBtn,terminalRecordBtn",p320.overflow.join())
for(const w of [320,400,600,900]){
const p=plan(w)
check(w+" px: layout, maximize and close always visible",["terminalLayoutBtn","terminalMaximizeBtn","terminalCloseBtn"].every((id)=>p.visible.includes(id)))
check(w+" px: search and jobs stay visible",p.visible.includes("terminalSearchBtn")&&p.visible.includes("terminalJobsBtn"))
const used=p.visible.reduce((s,id)=>s+widths[id],0)+(p.visible.length-1)*4+(p.overflow.length?30:0)+8
check(w+" px: visible buttons fit on one row",used<=w-22,used+" > "+(w-22))
}
let prev=-1,mono=true
for(let w=900;w>=320;w-=10){const n=plan(w).overflow.length;if(n<prev)mono=false;prev=n}
check("narrowing never brings buttons back",mono)
console.log(passed+" passed, "+failed+" failed")
process.exit(failed?1:0)
