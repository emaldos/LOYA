// The redesigned Chains diagram studio: the canvas (UI/js/components/flow-editor.js) as HTML node cards in a transformed world with
// SVG wires, its hot bar and node picker, the run status pills, the stylesheets (flow-editor.css, chains-studio.css, chains-icons.css)
// and how the files are wired into main.html. The model side (catalog, search, ports, validation) is in tests/js/flow_model.js.
const fs=require("fs")
const path=require("path")
const vm=require("vm")
const ROOT=path.resolve(__dirname,"..","..")
const read=(...p)=>fs.readFileSync(path.join(ROOT,...p),"utf8")
const CATALOG=read("UI","js","components","flow-catalog.js")
const MODEL=read("UI","js","components","flow-model.js")
const EDITOR=read("UI","js","components","flow-editor.js")
const FLOWPAGE=read("UI","js","pages","chains_flow.js")
const MAIN=read("UI","windows","main.html")
const CSS=read("UI","css","flow-editor.css")
const STUDIO=read("UI","css","chains-studio.css")
const ICONS=read("UI","css","chains-icons.css")
const FIELDS=read("UI","css","chains-fields.css")
let passed=0,failed=0
function check(name,cond,detail){if(cond){passed++;return}failed++;console.log("  FAIL  "+name+(detail?"  ->  "+detail:""))}
function eq(name,a,b){check(name,JSON.stringify(a)===JSON.stringify(b),JSON.stringify(a)+" != "+JSON.stringify(b))}
const noComments=(t)=>t.replace(/\/\*[\s\S]*?\*\//g,"")
// ---- a small generic fake DOM: just enough for flowEditorCreate to build its cards, bars and picker (no layout, no events of its own)
class El{
constructor(tag){
this.tagName=String(tag).toUpperCase();this.children=[];this.parentNode=null;this.dataset={};this.attrs={};this.listeners={};this.textContent="";this.value="";this.hidden=false;this.disabled=false;this.clientWidth=1000;this.clientHeight=600
this.style={setProperty(k,v){this[k]=String(v)},removeProperty(k){delete this[k]}}
const set=this._set=new Set()
this.classList={add:(...c)=>c.forEach((x)=>set.add(x)),remove:(...c)=>c.forEach((x)=>set.delete(x)),contains:(c)=>set.has(c),toggle:(c,on)=>{const want=on===undefined?!set.has(c):!!on;if(want)set.add(c);else set.delete(c);return want}}
}
get className(){return Array.from(this._set).join(" ")}
set className(v){this._set.clear();String(v||"").split(/\s+/).filter(Boolean).forEach((c)=>this._set.add(c))}
setAttribute(k,v){this.attrs[k]=String(v);if(k==="class")this.className=v}
getAttribute(k){return k in this.attrs?this.attrs[k]:null}
removeAttribute(k){delete this.attrs[k]}
appendChild(c){if(c.parentNode)c.parentNode.removeChild(c);c.parentNode=this;this.children.push(c);return c}
insertBefore(c,ref){if(c.parentNode)c.parentNode.removeChild(c);c.parentNode=this;const i=this.children.indexOf(ref);this.children.splice(i<0?this.children.length:i,0,c);return c}
removeChild(c){this.children=this.children.filter((x)=>x!==c);c.parentNode=null;return c}
replaceChild(c,old){const i=this.children.indexOf(old);if(i>=0){this.children[i]=c;c.parentNode=this;old.parentNode=null}return old}
get firstChild(){return this.children[0]||null}
get lastChild(){return this.children[this.children.length-1]||null}
addEventListener(t,fn){(this.listeners[t]=this.listeners[t]||[]).push(fn)}
removeEventListener(){}
all(){return this.children.reduce((a,c)=>a.concat([c],c.all()),[])}
// class selectors only (".a" or ".a,.b"), which is all the editor and these checks ask for
querySelectorAll(sel){const cls=sel.split(",").map((s)=>s.trim().replace(/^\./,""));return this.all().filter((e)=>cls.some((c)=>e._set.has(c)))}
querySelector(sel){return this.querySelectorAll(sel)[0]||null}
contains(o){for(let n=o;n;n=n.parentNode)if(n===this)return true;return false}
closest(){return null}
getBoundingClientRect(){return {left:0,top:0,right:1000,bottom:600,width:1000,height:600}}
focus(){}
blur(){}
setPointerCapture(){}
releasePointerCapture(){}
scrollIntoView(){}
}
function makeEditor(opts){
const win={q:[],console:{log(){},warn(){},error(){}},requestAnimationFrame:(fn)=>{win.q.push(fn);return win.q.length},cancelAnimationFrame(){},setTimeout:(fn)=>{win.q.push(fn);return win.q.length},clearTimeout(){},addEventListener(){},removeEventListener(){}}
const doc={createElement:(t)=>new El(t),createElementNS:(ns,t)=>Object.assign(new El(t),{ns:ns}),addEventListener(){},removeEventListener(){},activeElement:null,defaultView:win,body:new El("body")}
const box={module:{exports:{}},console:win.console,document:doc,window:win,setTimeout:win.setTimeout,clearTimeout(){}}
vm.createContext(box)
vm.runInContext(CATALOG+"\n"+MODEL+"\n"+EDITOR,box)
const get=(expr)=>vm.runInContext(expr,box)
const host=new El("div");host.ownerDocument=doc
const log={prefs:[],changes:0,selects:[],wires:[],runs:[],opens:[]}
const ed=get("flowEditorCreate")(host,Object.assign({onPrefs:(p)=>log.prefs.push(p),onChange:()=>{log.changes++},onSelect:(ids)=>log.selects.push(ids),onAutoWire:(i)=>log.wires.push(i),onRunState:(s)=>log.runs.push(s),onOpenNode:(id,tab)=>log.opens.push([id,tab])},opts||{}))
const tick=()=>{for(let i=0;i<5;i++){const q=win.q.splice(0);q.forEach((fn)=>{try{fn()}catch(_){}})}}
return {ed,host,log,get,tick,item:get("flowCatalogItem"),M:box.module.exports}
}
const M=require(path.join(ROOT,"UI","js","components","flow-model.js"))
const E=require(path.join(ROOT,"UI","js","components","flow-editor.js"))
const CAT=M.FLOW_CAT
// ---- run status pills (pure)
eq("badges: one pill per run state, plus 'warn' for a handled failure",[Object.keys(E.FLOW_RUN_BADGES).sort(),Object.keys(E.FLOW_RUN_BADGES).filter((k)=>!E.FLOW_RUN_BADGES[k].label||!E.FLOW_RUN_BADGES[k].icon)],[["fail","pending","planned","running","skipped","success","waiting","warn"],[]])
eq("badges: labels",Object.keys(E.FLOW_RUN_BADGES).map((k)=>k+"="+E.FLOW_RUN_BADGES[k].label).sort(),["fail=Failed","pending=Queued","planned=Planned","running=Running","skipped=Skipped","success=OK","waiting=Waiting","warn=Handled"])
const COMPONENTS=read("UI","css","components.css")
const hasIcon=(i)=>fs.existsSync(path.join(ROOT,"Assets","icons",i+".svg"))&&(COMPONENTS+ICONS+read("UI","css","pages","notes_editor.css")).indexOf(".icon-"+i+"{")>=0
eq("badges: every pill icon exists (svg file and .icon-<name> rule)",Object.keys(E.FLOW_RUN_BADGES).map((k)=>E.FLOW_RUN_BADGES[k].icon).filter((i)=>!hasIcon(i)),[])
{const edges=[{id:"e1",from:"a",port:"fail",to:"b"},{id:"e2",from:"a",port:"success",to:"c"},{id:"e3",from:"z",port:"error",to:"b"}]
eq("badge state: a failure whose taken branch is wired is handled -> warn",E.flowRunBadgeState({state:"fail",branch:"fail"},edges,"a"),"warn")
eq("badge state: a failure with no wire on that branch, no branch at all, or another node's wire stays a failure",[E.flowRunBadgeState({state:"fail",branch:"error"},edges,"a"),E.flowRunBadgeState({state:"fail"},edges,"a"),E.flowRunBadgeState({state:"fail",branch:""},edges,"a"),E.flowRunBadgeState({state:"fail",branch:"fail"},edges,"b"),E.flowRunBadgeState({state:"fail",branch:"fail"},null,"a"),E.flowRunBadgeState({state:"fail",branch:"fail"},[],"a")],["fail","fail","fail","fail","fail","fail"])
eq("badge state: only a failure can be 'handled'",[E.flowRunBadgeState({state:"success",branch:"fail"},edges,"a"),E.flowRunBadgeState({state:"running",branch:"fail"},edges,"a")],["success","running"])
eq("badge state: the other states pass through",["pending","running","success","skipped","waiting","planned"].map((s)=>E.flowRunBadgeState({state:s},edges,"a")),["pending","running","success","skipped","waiting","planned"])
eq("badge state: no record, an unknown state, a state named like an Object member -> no pill",[E.flowRunBadgeState(null,edges,"a"),E.flowRunBadgeState(undefined,edges,"a"),E.flowRunBadgeState({},edges,"a"),E.flowRunBadgeState({state:"exploded"},edges,"a"),E.flowRunBadgeState({state:"warn"},edges,"a")==="warn"],["","","","",true])}
eq("duration: nothing for zero / junk, ms under a second, one decimal of seconds under a minute",[E.flowPillDuration(0),E.flowPillDuration(null),E.flowPillDuration(undefined),E.flowPillDuration("x"),E.flowPillDuration(-5),E.flowPillDuration(1),E.flowPillDuration(450),E.flowPillDuration(999),E.flowPillDuration(1500),E.flowPillDuration("2500"),E.flowPillDuration(42300)],["","","","","","1 ms","450 ms","999 ms","1.5 s","2.5 s","42.3 s"])
check("duration: minutes and seconds from one minute on",/^1m 0?5s$/.test(E.flowPillDuration(65000))&&/^12m 0?3s$/.test(E.flowPillDuration(723000)),E.flowPillDuration(65000)+" / "+E.flowPillDuration(723000))
check("duration: always a short plain string",[0,1,999,1000,59999,60000,3599000,86400000,NaN,-1].every((ms)=>{const s=E.flowPillDuration(ms);return typeof s==="string"&&s.length<=12&&!/NaN|undefined|Infinity/.test(s)}))
// ---- pure view helpers that the redesign kept
eq("wheel: a plain wheel pans on both axes, Shift pans sideways, nothing for no movement",[E.flowWheelAction(0,120,false,false),E.flowWheelAction(30,-40,false,false),E.flowWheelAction(0,120,false,true),E.flowWheelAction(50,7,false,true),E.flowWheelAction(0,0,false,false),E.flowWheelAction(0,0,false,true)],[{type:"pan",dx:0,dy:120},{type:"pan",dx:30,dy:-40},{type:"pan",dx:120,dy:0},{type:"pan",dx:50,dy:7},{type:"none"},{type:"none"}])
{const out=E.flowWheelAction(0,120,true,false),inn=E.flowWheelAction(0,-120,true,false)
eq("wheel: Ctrl+wheel zooms (down = out, up = in), never pans; Ctrl with no vertical movement does nothing",[out.type,out.factor<1,inn.type,inn.factor>1,Math.abs(out.factor*inn.factor-1)<1e-9,"dx" in out,E.flowWheelAction(40,0,true,false),E.flowWheelAction(0,120,true,true).type],["zoom",true,"zoom",true,true,false,{type:"none"},"zoom"])
check("wheel: a plain wheel never zooms",[[0,120],[0,-120],[5,5],[0,3]].every((d)=>E.flowWheelAction(d[0],d[1],false,false).type==="pan"))}
check("wheel: the stage handler goes through flowWheelAction (Ctrl or Meta = zoom at the cursor, else pan)",/on\(stage,"wheel",\(e\)=>\{[\s\S]{0,400}flowWheelAction\(dx,dy,e\.ctrlKey\|\|e\.metaKey,e\.shiftKey\)/.test(EDITOR)&&/on\(stage,"wheel",\(e\)=>\{\n[^\n]*\ne\.preventDefault\(\)\n/.test(EDITOR)&&/zoomAtLocal\(p\.x,p\.y,st\.view\.zoom\*act\.factor\)\n\},\{passive:false\}\)/.test(EDITOR)&&/if\(act\.type==="pan"\)\{st\.view=flowViewPan\(st\.view,-act\.dx,-act\.dy\);applyView\(\);return\}/.test(EDITOR))
eq("view: zoom limits and the conversions",[E.flowClampZoom(0.01),E.flowClampZoom(9),E.flowClampZoom(NaN),E.flowViewToScreen({x:100,y:50,zoom:2},110,60),E.flowViewToWorld({x:100,y:50,zoom:2},20,20),E.flowViewPan({x:100,y:50,zoom:2},40,-20)],[0.25,2,1,{x:20,y:20},{x:110,y:60},{x:80,y:60,zoom:2}])
eq("view: every pure helper is still exported",["flowClampZoom","flowViewToScreen","flowViewToWorld","flowViewZoomAt","flowViewPan","flowWheelAction","flowViewFit","flowViewSees","flowBoxRect","flowBoxHits","flowMiniMap","flowMiniToMini","flowMiniToWorld","flowWrapText","flowIssueMap","flowRunBadgeState","flowPillDuration","flowEditorCreate"].filter((f)=>typeof E[f]!=="function"),[])
// ---- the keyboard sheet names the new ways to add a node
{const keys=E.FLOW_EDITOR_SHORTCUTS.map((s)=>s.keys)
eq("keys: the picker, the canvas double-click and the wire drop are on the sheet",["Tab or /","Double-click the canvas","Drag from a port"].filter((k)=>keys.indexOf(k)<0),[])
check("keys: wheel pans, Ctrl+wheel zooms",E.FLOW_EDITOR_SHORTCUTS.some((s)=>s.keys==="Wheel / two-finger scroll"&&/^Pan the canvas/.test(s.label))&&E.FLOW_EDITOR_SHORTCUTS.some((s)=>s.keys==="Ctrl+wheel / pinch"&&s.label==="Zoom at the cursor"))
check("keys: no row mentions the old palette",!E.FLOW_EDITOR_SHORTCUTS.some((s)=>/palette/i.test(s.keys+s.label)))}
// ---- source: the canvas is HTML cards in a CSS-transformed world, wires are SVG, the palette is gone
check("source: the world is moved with a CSS transform",/world\.style\.transform="translate\("\+r1\(-v\.x\*v\.zoom\)\+"px,"\+r1\(-v\.y\*v\.zoom\)\+"px\) scale\("\+v\.zoom\+"\)"/.test(EDITOR))
check("source: node cards are HTML elements, only wires and the minimap are SVG",/const g=H\("div","flow-node flow-type-"/.test(EDITOR)&&/const svg=S\("svg",\{[^}]*\},"flow-wires"\)/.test(EDITOR)&&!/S\("(foreignObject|text|tspan)"/.test(EDITOR))
// (.flow-palette-ghost is the label that follows the pointer while a hot bar button is dragged onto the canvas)
check("source: no palette is built any more",!/flow-palette(?!-ghost)/.test(EDITOR)&&!/flow-palette(?!-ghost)/.test(noComments(CSS))&&!/flow-palette/.test(FLOWPAGE)&&!/"flow-palette"/.test(EDITOR))
check("source: Tab or / opens the picker (not from a focused button, not while typing)",/else if\(\(k==="Tab"&&!e\.shiftKey&&!onButton\)\|\|k==="\/"\)\{done=openPicker\(\{\}\)\}/.test(EDITOR)&&/if\(st\.destroyed\|\|isTyping\(e\.target\)\|\|e\.altKey\)return/.test(EDITOR))
check("source: a wire dropped on empty canvas, or a clicked output port, opens the picker with the new node wired in",/else if\(!d\.moved\|\|!flowHitNode\(st\.graph,d\.last\.x,d\.last\.y,6\)\)\{[\s\S]{0,200}openPicker\(\{world:d\.moved\?d\.last:null,pending:\{from:d\.from,port:d\.port\}\}\)/.test(EDITOR))
check("source: a double-click on empty canvas opens the picker at that spot",/if\(now-st\.lastEmpty<400\)\{st\.lastEmpty=0;clearDragChrome\(\);openPicker\(\{clientX:e\.clientX,clientY:e\.clientY\}\);return\}/.test(EDITOR))
check("source: the wire tool inserts a node on the selected connection",/openPicker\(\{world:m,pending:\{edge:id\}\}\)/.test(EDITOR)&&/on\(etDel,"click",\(\)=>\{deleteSelection\(\);focus\(\)\}\)/.test(EDITOR))
check("source: picker and hot bar text is set with textContent, never innerHTML",!/innerHTML/.test(EDITOR))
check("source: class names built from data go through the css() filter",/const css=\(s\)=>String\(s==null\?"":s\)\.replace\(\/\[\^A-Za-z0-9_-\]\/g,""\)/.test(EDITOR)&&(EDITOR.match(/(flow-cat-|flow-type-|flow-comment-)"\+/g)||[]).length>=5&&!/(flow-cat-|flow-type-|flow-comment-)"\+(?!css\()/.test(EDITOR)&&!/"icon icon-"\+(?!css\(|icon\)|b\.icon\n|\(pinned\?"star-filled":"star"\))/.test(EDITOR))
check("source: no web storage, pointer capture for drags, no HTML5 drag and drop",!/localStorage|sessionStorage/.test(EDITOR)&&/setPointerCapture/.test(EDITOR)&&!/addEventListener\("(dragstart|drop|dragover)"/.test(EDITOR)&&!/on\([a-zA-Z]+,"(dragstart|drop|dragover)"/.test(EDITOR))
// ---- the page: History button, prefs, panel wiring
check("page: History opens the Run History tab when the Chains page has one, else the run panel's list",/if\(typeof loyaOpenChainHistory==="function"\)\{const id=open\.playbookId;chainsFlowLeave\(\)\.then\(\(ok\)=>\{if\(ok\)loyaOpenChainHistory\(id\)\}\)\}\nelse st\.view\.run\.showHistory\(open\.playbookId\)/.test(FLOWPAGE))
check("page: the hot bar pins are a pref (null = the catalog default) handed to the editor",/const CHAINS_FLOW_PREFS=\{snap:true,grid:20,minimap:true,inspector_width:340,hotbar:null\}/.test(FLOWPAGE)&&/prefs:\{snap:prefs\.snap,grid:prefs\.grid,minimap:prefs\.minimap,hotbar:prefs\.hotbar\}/.test(FLOWPAGE))
check("page: onOpenNode(id,tab) and onRunState reach the inspector when it has setTab / setRun",/onOpenNode:\(id,tab\)=>\{/.test(FLOWPAGE)&&/if\(typeof inspector\.setTab==="function"\)inspector\.setTab\(tab==="output"\?"output":"params"\)/.test(FLOWPAGE)&&/onRunState:\(status\)=>\{if\(inspector&&typeof inspector\.setRun==="function"\)inspector\.setRun\(status\)\}/.test(FLOWPAGE))
check("page: the inspector really has setTab and setRun",/\bsetTab\b/.test(read("UI","js","components","flow-inspector.js"))&&/\bsetRun\b/.test(read("UI","js","components","flow-inspector.js")))
// ---- main.html: tag order
{const links=(MAIN.match(/<link rel="stylesheet"[^>]*>/g)||[]).map((l)=>/css\/([^"]+)"/.exec(l)[1])
const scripts=(MAIN.match(/<script src="\.\.\/js\/[^"]+"><\/script>/g)||[]).map((s)=>/js\/([^"]+)"/.exec(s)[1])
const L=(n)=>links.indexOf(n),S=(n)=>scripts.indexOf(n)
eq("main: glass.css is the last stylesheet (and linked once)",[links[links.length-1],links.filter((l)=>l==="glass.css").length],["glass.css",1])
eq("main: the studio sheets are linked once each, in order, right before glass.css",links.slice(-6),["flow-editor.css","flow-panels.css","chains-fields.css","chains-icons.css","chains-studio.css","glass.css"])
check("main: chains-studio.css comes after the sheets it overrides",L("chains-studio.css")>L("flow-panels.css")&&L("chains-studio.css")>L("flow-editor.css")&&L("chains-studio.css")>L("pages/chains.css")&&L("pages/chains.css")>=0)
check("main: the icon sheet comes after components.css (same .icon base rule)",L("components.css")>=0&&L("chains-icons.css")>L("components.css"))
eq("main: every script of the studio is loaded exactly once",["components/flow-catalog.js","components/flow-model.js","components/flow-rules.js","components/flow-editor.js","components/flow-fields.js","components/flow-inspector.js","components/flow-run.js","components/flow-log.js","pages/chains_flow.js"].filter((n)=>scripts.filter((x)=>x===n).length!==1),[])
check("main: flow-catalog.js right before flow-model.js",S("components/flow-catalog.js")>=0&&S("components/flow-model.js")===S("components/flow-catalog.js")+1)
check("main: flow-model.js before the editor, flow-fields.js right before flow-inspector.js",S("components/flow-model.js")<S("components/flow-editor.js")&&S("components/flow-fields.js")>S("components/flow-editor.js")&&S("components/flow-inspector.js")===S("components/flow-fields.js")+1)
check("main: the panels load before the page script, the page script before app.js",S("components/flow-inspector.js")<S("pages/chains_flow.js")&&S("components/flow-run.js")<S("pages/chains_flow.js")&&S("pages/chains.js")<S("pages/chains_flow.js")&&S("pages/chains_flow.js")<S("app.js"))
check("main: every linked studio file exists",["flow-editor.css","flow-panels.css","chains-fields.css","chains-icons.css","chains-studio.css"].every((f)=>fs.existsSync(path.join(ROOT,"UI","css",f)))&&["flow-catalog.js","flow-fields.js"].every((f)=>fs.existsSync(path.join(ROOT,"UI","js","components",f))))}
// ---- the catalog file
check("catalog: a generated file that defines the global and exports it for node",/^\/\/ GENERATED by tools\/gen_flow_catalog\.py from Cores\/Services\/flow_nodes\.py/.test(CATALOG)&&/^const FLOW_CATALOG=\{/m.test(CATALOG)&&CATALOG.split("\n").length===4&&CATALOG.split("\n")[2]==='if(typeof module!=="undefined"&&module.exports)module.exports={FLOW_CATALOG}'&&CATALOG.split("\n")[3]===""&&(()=>{try{JSON.parse(CATALOG.split("\n")[1].replace(/^const FLOW_CATALOG=/,""));return true}catch(e){return false}})())
check("catalog: no markup in any label, description, help text or placeholder (they are shown as text, and must stay harmless)",!/<\/?[a-z][^>]*>/i.test(JSON.stringify(CAT).replace(/\$\{nodes\.<id>[^"]*/g,"")),(JSON.stringify(CAT).replace(/\$\{nodes\.<id>[^"]*/g,"").match(/.{0,30}<\/?[a-z][^>]*>.{0,10}/i)||[""])[0])
// ---- CSS hygiene
const SHEETS={"flow-editor.css":CSS,"chains-studio.css":STUDIO,"chains-icons.css":ICONS,"chains-fields.css":FIELDS}
const rules=(t)=>noComments(t).match(/[^{}]+\{[^{}]*\}/g)||[]
Object.keys(SHEETS).forEach((name)=>{
const t=SHEETS[name]
eq("css "+name+": every user-select has its -webkit-user-select twin in the same rule, with the same value",rules(t).filter((r)=>{const plain=(r.match(/(?<![\w-])user-select:[^;}]+/g)||[]).map((x)=>x.replace("user-select:","")),wk=(r.match(/-webkit-user-select:[^;}]+/g)||[]).map((x)=>x.replace("-webkit-user-select:",""));return JSON.stringify(plain)!==JSON.stringify(wk)}).map((r)=>r.slice(0,60)),[])
check("css "+name+": LF line endings, no tab characters, ends with a newline",t.indexOf("\r")<0&&t.indexOf("\t")<0&&/\n$/.test(t))
check("css "+name+": braces balance",(noComments(t).match(/\{/g)||[]).length===(noComments(t).match(/\}/g)||[]).length)
check("css "+name+": no CSS zoom, no backdrop-filter",!/[;{\s]zoom:/.test(noComments(t))&&!/backdrop-filter\s*:/.test(noComments(t)))
check("css "+name+": no em dash, en dash, ellipsis or middle dot",!/[—–…·]/.test(t))
})
check("css: flow-editor.css has user-select rules to check (the canvas is not selectable, inputs are)",(CSS.match(/-webkit-user-select:none/g)||[]).length>=1&&(CSS.match(/-webkit-user-select:text/g)||[]).length>=1)
eq("css: every mask-image in chains-icons.css has its -webkit- twin and points at an existing svg",rules(ICONS).filter((r)=>{const m=/^\s*\.icon-([a-z0-9-]+)\{-webkit-mask-image:url\(\.\.\/\.\.\/Assets\/icons\/([a-z0-9-]+)\.svg\);mask-image:url\(\.\.\/\.\.\/Assets\/icons\/([a-z0-9-]+)\.svg\)\}$/.exec(r);return !m||m[1]!==m[2]||m[2]!==m[3]||!fs.existsSync(path.join(ROOT,"Assets","icons",m[1]+".svg"))}).map((r)=>r.trim().slice(0,40)),[])
check("css: chains-icons.css defines no icon components.css already has",(ICONS.match(/\.icon-[a-z0-9-]+\{/g)||[]).every((r)=>COMPONENTS.indexOf(r)<0))
eq("css: the classes the editor builds are styled",["flow-editor","flow-stage","flow-surface","flow-world","flow-wires","flow-layer","flow-node","flow-node-head","flow-node-tile","flow-node-title","flow-node-kind","flow-node-summary","flow-port","flow-port-in","flow-port-out","flow-port-dot","flow-port-plus","flow-port-label","flow-node-status","flow-node-badge","flow-comment","flow-comment-text","flow-comment-resize","flow-comment-input","flow-edge","flow-edge-tools","flow-edge-tool","flow-toolbar","flow-zoombar","flow-tool","flow-tool-add","flow-tool-sep","flow-hotbar","flow-hot","flow-hot-label","flow-hot-more","flow-tile","flow-picker","flow-picker-head","flow-picker-input","flow-picker-hint","flow-picker-list","flow-picker-group","flow-picker-item","flow-picker-text","flow-picker-name","flow-picker-desc","flow-picker-pin","flow-picker-empty","flow-picker-foot","flow-minimap","flow-empty-hint","flow-selbox","flow-rubber","flow-tooltip"].filter((c)=>!new RegExp("\\."+c+"(?![A-Za-z0-9_-])").test(noComments(CSS))),[])
eq("css: every state class the editor toggles is styled",["is-selected","has-error","has-warning","is-pending","is-running","is-success","is-fail","is-warn","is-skipped","is-waiting","is-planned","is-current","is-taken","is-free","is-active","is-on","is-nogrid","is-far","is-panning","is-readonly"].filter((c)=>!new RegExp("\\."+c+"(?![A-Za-z0-9_-])").test(noComments(CSS))),[])
eq("css: each status pill state has a rule on .flow-node-status",Object.keys(E.FLOW_RUN_BADGES).filter((s)=>!new RegExp("\\.flow-node-status\\.is-"+s+"(?![a-z-])").test(CSS)),[])
check("css: reduced motion is respected",/@media \(prefers-reduced-motion:\s*reduce\)/.test(CSS))
check("css: the properties panel overlays the canvas and only shows with one node selected",/\.cf-main\{position:relative\}/.test(STUDIO)&&/\.cf-side\{position:absolute;top:0;right:0;bottom:0;/.test(STUDIO)&&/\.cf-view:not\(\.cf-has-sel\) \.cf-side\{display:none\}/.test(STUDIO))
check("css: the hot bar makes room for the open panel and hides during a run",/\.cf-has-sel \.flow-hotbar\{left:calc\(\(100% - var\(--cf-side-w,340px\)\)\/2\)/.test(STUDIO)&&/\.cf-has-run \.flow-hotbar\{display:none\}/.test(STUDIO))
// ---- forbidden typography in UI strings (plain ASCII punctuation only)
{const SRC={"UI/js/components/flow-editor.js":EDITOR,"UI/js/pages/chains_flow.js":FLOWPAGE,"UI/js/components/flow-model.js":MODEL}
const names={"—":"em dash","–":"en dash","…":"ellipsis","·":"middle dot"}
const hits=[]
Object.keys(SRC).forEach((f)=>SRC[f].split("\n").forEach((line,i)=>{for(const ch of line)if(names[ch])hits.push(f+":"+(i+1)+" "+names[ch])}))
eq("text: no em dash, en dash, ellipsis character or middle dot in the editor, the page or the model",hits,[])
// written as escapes they would still reach the screen: the only ones are the two text-cutting helpers (flowTruncate, flowWrapText)
const esc=[]
Object.keys(SRC).forEach((f)=>SRC[f].split("\n").forEach((line,i)=>{(line.match(/\\u(2014|2013|2026|00[bB]7)/g)||[]).forEach((m)=>esc.push(f.replace(/^.*\//,"")+" "+m+" "+(/^function (\w+)/.exec(line)||/(\w+)\[maxLines-1\]/.exec(line)||["","?"])[1]))}))
eq("text: the same characters as \\u escapes appear only where text is cut short",esc,["flow-editor.js \\u2026 out","flow-model.js \\u2026 flowTruncate"])
check("text: sources are LF only",Object.keys(SRC).every((f)=>SRC[f].indexOf("\r")<0)&&CATALOG.indexOf("\r")<0&&MAIN.indexOf("\r")<0&&fs.readFileSync(__filename,"utf8").indexOf("\r")<0)}
// ---- behaviour: the real editor on the fake DOM
{const T=makeEditor({prefs:{hotbar:["command","nope","http","command","start"]}}),ed=T.ed,root=ed.el
check("editor: mounts into its host",T.host.children.length===1&&T.host.children[0]===root&&root.classList.contains("flow-editor"))
eq("editor: the picker API is on the editor object",["openPicker","closePicker","placeNew","togglePin","getRunState","setRunState","fit","getPrefs","setPrefs","getGraph","setGraph","select"].filter((f)=>typeof ed[f]!=="function"),[])
// skeleton
const surface=root.querySelector(".flow-surface"),world=root.querySelector(".flow-world"),wires=root.querySelector(".flow-wires")
check("dom: .flow-world sits inside .flow-surface and holds the notes layer, the SVG wires and the node layer",!!surface&&world.parentNode===surface&&wires.parentNode===world&&wires.tagName==="SVG"&&wires.ns==="http://www.w3.org/2000/svg"&&world.querySelectorAll(".flow-layer").length===2&&world.querySelector(".flow-nodes").parentNode===world)
check("dom: no palette",root.querySelectorAll(".flow-palette").length===0&&root.all().every((e)=>!/palette/.test(e.className)))
{const cards=root.querySelectorAll(".flow-node");eq("dom: a node is an HTML card placed with left/top and sized from the model",[cards.length,cards[0].tagName,cards[0].ns===undefined,cards[0].parentNode===world.querySelector(".flow-nodes"),cards[0].getAttribute("data-id"),cards[0].classList.contains("flow-type-start"),cards[0].classList.contains("flow-cat-input"),cards[0].style.left,cards[0].style.top,cards[0].style.width,cards[0].style.height],[1,"DIV",true,true,"n1",true,true,"40px","160px",M.FLOW_GEOM.w+"px",M.flowNodeSize({type:"start",config:{}}).h+"px"])
eq("dom: the card shows title, kind, summary and one output port per model port",[cards[0].querySelector(".flow-node-title").textContent,cards[0].querySelector(".flow-node-kind").textContent,cards[0].querySelector(".flow-node-summary").textContent,cards[0].querySelectorAll(".flow-port-out").map((p)=>p.getAttribute("data-port")),cards[0].querySelectorAll(".flow-port-in").length,cards[0].querySelector(".flow-node-status").hidden],["Start","Start","Manual run",["out"],0,true])}
check("dom: the world carries the view as a CSS transform",/^translate\(-?[\d.]+px,-?[\d.]+px\) scale\([\d.]+\)$/.test(world.style.transform),world.style.transform)
// hot bar
const hot=()=>root.querySelectorAll(".flow-hot").map((b)=>b.dataset.item||"(all)")
eq("hot bar: the pins of prefs.hotbar, cleaned, then the All nodes button",[hot(),ed.getPrefs().hotbar,root.querySelector(".flow-hotbar").children.length],[["command","http","(all)"],["command","http"],3])
eq("hot bar: with no pins in the prefs it shows the catalog default",(()=>{const D=makeEditor({});return D.ed.getPrefs().hotbar})(),CAT.hotbar)
eq("hot bar: a button carries its category colour, icon, label and an accessible name",(()=>{const b=root.querySelectorAll(".flow-hot")[1];return [b.classList.contains("flow-cat-action"),b.querySelector(".flow-tile").children[0].className,b.querySelector(".flow-hot-label").textContent,b.getAttribute("aria-label"),b.dataset.type]})(),[true,"icon icon-flow-globe","HTTP request","Add HTTP request node","http"])
// picker
const pickerEl=root.querySelector(".flow-picker"),rows=()=>root.querySelectorAll(".flow-picker-item"),names=()=>rows().map((r)=>r.querySelector(".flow-picker-name").textContent)
check("picker: hidden until asked for",pickerEl.hidden===true&&rows().length===0)
eq("picker: openPicker lists every item except Start (the graph has one), grouped by category",[ed.openPicker({}),pickerEl.hidden,root.classList.contains("is-picking"),rows().length,root.querySelectorAll(".flow-picker-group").map((g)=>g.textContent)],[true,false,true,M.flowCatalogItems().length-1,M.FLOW_CATEGORIES.map((c)=>c.label)])
check("picker: Start is not offered twice, presets are offered",names().indexOf("Start")<0&&names().indexOf("If")>=0&&names().indexOf("Stop and fail")>=0&&names().indexOf("Switch")>=0)
check("picker: every row has a description, a tile and a pin button; pinned items show the filled star",rows().every((r)=>r.querySelector(".flow-picker-desc").textContent.length>0&&!!r.querySelector(".flow-tile")&&r.querySelectorAll(".flow-picker-pin").length===1)&&rows().filter((r)=>r.querySelector(".flow-picker-pin").classList.contains("is-on")).map((r)=>r.querySelector(".flow-picker-pin").dataset.pin).join()==="command,http"&&rows().find((r)=>r.querySelector(".flow-picker-pin").dataset.pin==="http").querySelector(".flow-picker-pin").children[0].className==="icon icon-star-filled")
const input=root.querySelector(".flow-picker-input"),type=(q)=>{input.value=q;input.listeners.input.forEach((fn)=>fn({}))}
const want=(q)=>M.flowCatalogSearch(q,M.flowCatalogItems().filter((i)=>i.type!=="start")).reduce((a,g)=>a.concat(g.items.map((i)=>i.label)),[])
type("nmap");eq("picker: typing filters by keyword, best group first (the order of flowCatalogSearch)",[names(),names().length,names().indexOf("Command")>=0,names().indexOf("Wait")],[want("nmap"),5,true,-1])
type("logic");check("picker: ... by category",rows().length===11&&root.querySelectorAll(".flow-picker-group").map((g)=>g.textContent).join()==="Logic")
type("zzzz");eq("picker: no match shows the hint, no rows",[rows().length,root.querySelectorAll(".flow-picker-empty").length,/No node matches/.test(root.querySelector(".flow-picker-empty").textContent)],[0,1,true])
type("<img src=x onerror=1>");check("picker: a query is only ever compared, never rendered",rows().length===0&&root.all().every((e)=>e.tagName!=="IMG"))
ed.closePicker();eq("picker: closePicker hides it",[pickerEl.hidden,root.classList.contains("is-picking")],[true,false])
{const key=(k,extra)=>{const e=Object.assign({key:k,target:root,prevented:false,preventDefault(){e.prevented=true},stopPropagation(){}},extra||{});root.listeners.keydown.forEach((fn)=>fn(e));return e}
key("/");const a=!pickerEl.hidden;ed.closePicker();key("Tab");const b=!pickerEl.hidden;ed.closePicker();key("Tab",{shiftKey:true});const c=!pickerEl.hidden;key("/",{altKey:true});const d=!pickerEl.hidden
eq("picker: / and Tab open it; Shift+Tab and Alt+/ do not",[a,b,c,d],[true,true,false,false])
key("/");key("Escape");check("picker: Escape closes it",pickerEl.hidden===true)}
// placeNew: wired after a source port
const before=T.log.changes
const cmd=ed.placeNew(T.item("command"),null,{from:"n1",port:"out"})
eq("place: a node placed with pending.from is wired to that port, to the right of its source, and selected",[cmd.type,ed.getGraph().edges.map((e)=>[e.from,e.port,e.to]),cmd.x>=40+M.FLOW_GEOM.w+80,ed.getSelection?JSON.stringify(ed.getSelection()).indexOf(cmd.id)>=0:true,T.log.changes>before],["command",[["n1","out",cmd.id]],true,true,true])
eq("place: its input lines up with the source port (a straight wire)",M.flowPortPos(cmd,"in").y,M.flowPortPos(ed.getGraph().nodes[0],"out","out").y)
check("place: the card is on the canvas and a wire is drawn",root.querySelectorAll(".flow-node").length===2&&root.querySelector(".flow-edges").children.length===1)
// auto-wire: command -> decision takes the other result port along
ed.select([cmd.id])
const dec=ed.placeNew(T.item("decision"),null,{from:cmd.id,port:"success"})
eq("place: command -> decision also wires the other result port, and says so once",[ed.getGraph().edges.filter((e)=>e.from===cmd.id).map((e)=>[e.port,e.to]),T.log.wires.length,T.log.wires[0]&&T.log.wires[0].to,T.log.wires[0]&&T.log.wires[0].twin.port,T.log.wires[0]&&T.log.wires[0].edge.port],[[["success",dec.id],["fail",dec.id]],1,"Decision","fail","success"])
check("place: both edges came in one undo step",(()=>{ed.undo();const g=ed.getGraph();const ok=g.nodes.length===2&&g.edges.length===1;ed.redo();return ok&&ed.getGraph().edges.length===3})())
// with nothing pending and one node selected the new node continues from its first free output
ed.select([dec.id])
const nxt=ed.placeNew(T.item("log"),null,null)
eq("place: with one node selected the new node continues from its first free output",ed.getGraph().edges.filter((e)=>e.to===nxt.id).map((e)=>[e.from,e.port]),[[dec.id,"yes"]])
ed.select([]);const lone=ed.placeNew(T.item("wait"),{x:900,y:900},null)
eq("place: with nothing selected and a spot given it lands there, unwired",[ed.getGraph().edges.filter((e)=>e.to===lone.id||e.from===lone.id).length,Math.abs(lone.x+M.FLOW_GEOM.w/2-900)<=20,T.log.wires.length],[0,true,1])
// a preset: type + config overlay + title
const pre=ed.placeNew(T.item("stop_fail"),{x:1400,y:900},null)
eq("place: a preset is its type with the config overlay and its own title",[pre.type,pre.title,pre.config.status,pre.config.message],["end","Stop and fail","fail",""])
// pending.edge: the new node splits that connection
{const g0=ed.getGraph(),e1=g0.edges.find((e)=>e.from==="n1"),n0=g0.edges.length
const mid=ed.placeNew(T.item("delay"),{x:300,y:200},{edge:e1.id}),g1=ed.getGraph()
eq("place: with pending.edge the node is inserted on that connection (old edge gone, in and out rewired)",[mid.type,mid.config.seconds,g1.edges.some((e)=>e.id===e1.id&&e.from==="n1"&&e.to===cmd.id),g1.edges.filter((e)=>e.to===mid.id).map((e)=>[e.from,e.port]),g1.edges.filter((e)=>e.from===mid.id).map((e)=>[e.port,e.to]),g1.edges.length-n0],["wait",10,false,[["n1","out"]],[["out",cmd.id]],1])
check("place: the split graph still validates (no dangling edge, no unknown port)",M.flowValidate(g1).errors.filter((i)=>["dangling_edge","unknown_port","bad_edge_target","self_loop"].indexOf(i.code)>=0).length===0)
const e2=g1.edges.find((e)=>e.from===mid.id),sw=ed.placeNew(T.item("switch"),{x:500,y:200},{edge:e2.id}),g2=ed.getGraph()
eq("place: a node with several outputs continues the split on its first one",[g2.edges.filter((e)=>e.to===sw.id).map((e)=>[e.from,e.port]),g2.edges.filter((e)=>e.from===sw.id).map((e)=>[e.port,e.to])],[[[mid.id,"out"]],[["case1",cmd.id]]])
ed.undo();eq("place: one undo takes the inserted node out and puts the connection back",[ed.getGraph().nodes.some((n)=>n.id===sw.id),ed.getGraph().edges.filter((e)=>e.from===mid.id).map((e)=>[e.port,e.to])],[false,[["out",cmd.id]]])}
eq("place: junk is refused (no item, unknown type, a second Start, a sticky note into a wire stays unwired)",(()=>{const n=ed.getGraph().nodes.length,e=ed.getGraph().edges.length;const r=[ed.placeNew(null,null,null),ed.placeNew({type:"nope"},null,null),ed.placeNew(T.item("start"),null,null)];const c=ed.placeNew(T.item("comment"),{x:0,y:-500},{from:"n1",port:"out"});return [r,c.type,ed.getGraph().nodes.length-n,ed.getGraph().edges.length-e]})(),[[null,null,null],"comment",1,0])
// the picker hides what cannot be wired in, and choosing a row places it
{const e1=ed.getGraph().edges.find((e)=>e.from==="n1")
ed.openPicker({world:{x:300,y:200},pending:{edge:e1.id}})
check("picker: for a wire it offers only nodes with an input, and says what will happen",names().indexOf("Comment")<0&&names().indexOf("Command")>=0&&/inserted on the selected connection/.test(root.querySelector(".flow-picker-hint").textContent))
ed.closePicker();ed.openPicker({pending:{from:cmd.id,port:"fail"}})
check("picker: for a port the hint names the source node and the port",/wired to "Command" \(fail\)/.test(root.querySelector(".flow-picker-hint").textContent)&&root.querySelector(".flow-picker-hint").hidden===false)
type("result");const n=ed.getGraph().nodes.length
input.listeners.keydown.forEach((fn)=>fn({key:"Enter",preventDefault(){},stopPropagation(){}}))
const g=ed.getGraph(),made=g.nodes[g.nodes.length-1]
eq("picker: Enter adds the highlighted item, wired to the pending port, and closes",[g.nodes.length-n,made.type,g.edges.filter((e)=>e.to===made.id).map((e)=>[e.from,e.port]),pickerEl.hidden],[1,"result",[[cmd.id,"fail"]],true])}
// togglePin
{const n=T.log.prefs.length
ed.togglePin("math")
eq("pin: togglePin adds to the hot bar and reports the prefs through onPrefs",[T.log.prefs.length-n,T.log.prefs[T.log.prefs.length-1],hot()],[1,{snap:true,grid:20,minimap:true,hotbar:["command","http","math"]},["command","http","math","(all)"]])
ed.togglePin("command")
eq("pin: toggling a pinned item removes it",[T.log.prefs[T.log.prefs.length-1].hotbar,hot()],[["http","math"],["http","math","(all)"]])
ed.togglePin("nope");ed.togglePin("start")
eq("pin: unknown ids and Start are never pinned",[ed.getPrefs().hotbar,hot()],[["http","math"],["http","math","(all)"]])
ed.togglePin("if");check("pin: a preset can be pinned",ed.getPrefs().hotbar.join()==="http,math,if"&&root.querySelectorAll(".flow-hot")[2].dataset.type==="decision")
M.flowCatalogItems().filter((i)=>i.type!=="start").slice(0,20).forEach((i)=>{if(ed.getPrefs().hotbar.indexOf(i.id)<0)ed.togglePin(i.id)})
eq("pin: the hot bar never grows past FLOW_HOTBAR_MAX (the oldest pin makes room)",[ed.getPrefs().hotbar.length,hot().length,new Set(ed.getPrefs().hotbar).size],[M.FLOW_HOTBAR_MAX,M.FLOW_HOTBAR_MAX+1,M.FLOW_HOTBAR_MAX])
const got=ed.getPrefs();got.hotbar.push("x");check("pin: getPrefs hands out a copy",ed.getPrefs().hotbar.length===M.FLOW_HOTBAR_MAX)
ed.setPrefs({hotbar:["wait","nope","wait"]});eq("pin: setPrefs replaces the pins (cleaned) and redraws",[ed.getPrefs().hotbar,hot()],[["wait"],["wait","(all)"]])
ed.setPrefs({hotbar:[]});eq("pin: an empty hot bar keeps the All nodes button",hot(),["(all)"])}
// run state
{const g=ed.getGraph(),card=(id)=>root.querySelectorAll(".flow-node").find((c)=>c.getAttribute("data-id")===id),pill=(id)=>card(id).querySelector(".flow-node-status")
eq("run: no state before a run",[ed.getRunState(),pill(cmd.id).hidden],[null,true])
const status={state:"running",current:dec.id,nodes:{n1:{state:"success",duration_ms:3},[cmd.id]:{state:"fail",branch:"fail",duration_ms:1500,error:"exit 1"},[dec.id]:{state:"running"},[lone.id]:{state:"fail",branch:"out",duration_ms:20}},edges_taken:[]}
const r0=T.log.runs.length;ed.setRunState(status)
eq("run: setRunState is readable back and reported through onRunState",[ed.getRunState()===status,T.log.runs.length-r0,T.log.runs[T.log.runs.length-1]===status,root.classList.contains("has-run"),root.classList.contains("is-run-live")],[true,1,true,true,true])
eq("run: a failure whose fail port is wired shows as Handled, with its duration",[pill(cmd.id).hidden,pill(cmd.id).className,card(cmd.id).classList.contains("is-warn"),card(cmd.id).classList.contains("is-fail"),pill(cmd.id).children[0].className,pill(cmd.id).children[1].textContent,/^Handled in /.test(pill(cmd.id).title)&&/exit 1/.test(pill(cmd.id).title)],[false,"flow-node-status is-warn",true,true,"icon icon-warning",E.flowPillDuration(1500),true])
eq("run: a failure with nothing wired on that port stays Failed; running shows no time; untouched nodes show no pill",[pill(lone.id).className,card(lone.id).classList.contains("is-warn"),pill(dec.id).children[1].textContent,card(dec.id).classList.contains("is-current"),pill(nxt.id).hidden,pill("n1").className],["flow-node-status is-fail",false,"Running",true,true,"flow-node-status is-success"])
check("run: the taken output port is marked",card(cmd.id).querySelectorAll(".flow-port-out").filter((p)=>p.classList.contains("is-taken")).map((p)=>p.getAttribute("data-port")).join()==="fail")
ed.setRunState(null)
eq("run: null clears everything",[ed.getRunState(),T.log.runs[T.log.runs.length-1],pill(cmd.id).hidden,card(cmd.id).classList.contains("is-warn"),card(cmd.id).classList.contains("is-fail"),root.classList.contains("has-run")],[null,null,true,false,false,false])
eq("run: junk is treated as no run",(()=>{ed.setRunState("running");const a=ed.getRunState();ed.setRunState(7);return [a,ed.getRunState()]})(),[null,null])}
// fit(minZoom)
{const W=makeEditor({}),wide=M.flowNewGraph();let prev="n1",port="out"
for(let i=0;i<30;i++){const n=M.flowAddNode(wide,"command",40+(i+1)*300,160,{commands:[{text:"id"}]});M.flowConnect(wide,prev,port,n.id);prev=n.id;port="success"}
W.ed.setGraph(wide);W.ed.fit(0)
const whole=W.ed.getView()
check("fit: fit(0) shows the whole diagram, however small it gets (down to the zoom limit)",whole.zoom<0.6&&whole.zoom>=0.25,JSON.stringify(whole))
W.ed.fit(0.6);const readable=W.ed.getView()
eq("fit: fit(minZoom) opens a diagram that would be too small at that zoom, on its first nodes",[readable.zoom,readable.x<40&&readable.x>40-1000/0.6,E.flowViewSees(readable,1000,600,{x:40,y:160,w:M.FLOW_GEOM.w,h:100})],[0.6,true,true])
const small=makeEditor({});small.ed.fit(0.6)
check("fit: a small diagram is simply fitted (never zoomed in past 100%)",small.ed.getView().zoom===1)}
// read-only
{const R=makeEditor({readOnly:true}),n=R.ed.getGraph().nodes.length
eq("read-only: no picker, no placing; pins are a view preference and still work",[R.ed.openPicker({}),R.ed.el.querySelector(".flow-picker").hidden,R.ed.placeNew(R.item("command"),null,null),R.ed.getGraph().nodes.length-n],[false,true,null,0])}
// escaping: titles and config text reach the card as text
{const X=makeEditor({}),g=M.flowNewGraph();const n=M.flowAddNode(g,"command",300,160,{commands:[{text:"echo '<img src=x onerror=1>'"}]});n.title="<b onclick=1>x</b>";M.flowAddNode(g,"comment",0,400,{text:"<script>1</script>",color:"red\" onload=\"x"})
X.ed.setGraph(g)
const cards=X.ed.el.querySelectorAll(".flow-node"),c=cards.find((x)=>x.getAttribute("data-id")===n.id),note=cards.find((x)=>x.classList.contains("flow-comment"))
eq("escaping: a node title, a command and a note text are set as text, never parsed",[c.querySelector(".flow-node-title").textContent,c.querySelector(".flow-node-summary").textContent,note.querySelector(".flow-comment-text").textContent,X.ed.el.all().filter((e)=>["B","IMG","SCRIPT"].indexOf(e.tagName)>=0).length],["<b onclick=1>x</b>","echo '<img src=x onerror=1>'","<script>1</script>",0])
check("escaping: an unknown note colour falls back to yellow, class names stay clean",note.classList.contains("flow-comment-yellow")&&X.ed.el.all().every((e)=>/^[A-Za-z0-9_ -]*$/.test(e.className)))
const bad=M.flowNewGraph();bad.nodes.push({id:"q",type:"teleport\" x=\"",title:"T",x:0,y:0,config:{}});X.ed.setGraph(bad)
check("escaping: an unknown node type still draws, as an 'unknown' card with a clean class",(()=>{const u=X.ed.el.querySelectorAll(".flow-node").find((x)=>x.getAttribute("data-id")==="q");return !!u&&u.classList.contains("flow-cat-unknown")&&/^[A-Za-z0-9_ -]*$/.test(u.className)})())}
}
console.log("chains_studio: "+passed+" passed, "+failed+" failed")
if(failed)process.exit(1)
