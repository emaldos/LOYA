// The Chains page (UI/pages/chains.html, UI/js/pages/chains.js): Action Chains moved out of Commands into their own dock tab.
const fs=require("fs")
const path=require("path")
const vm=require("vm")
const ROOT=path.resolve(__dirname,"..","..")
const read=(...p)=>fs.readFileSync(path.join(ROOT,...p),"utf8")
const MAIN=read("UI","windows","main.html")
const APP=read("UI","js","app.js")
const PAGE=read("UI","js","pages","chains.js")
const HTML=read("UI","pages","chains.html")
const CMDS_HTML=read("UI","pages","commands.html")
const CMDS=read("UI","js","pages","commands.js")
const AC=read("UI","js","components","action-chains.js")
const PALETTE=read("UI","js","components","palette.js")
const DASH=read("UI","js","pages","dashboard.js")
const CARD=read("UI","js","components","card.js")
const LAYOUT=read("UI","css","layout.css")
const COMPONENTS=read("UI","css","components.css")
let passed=0,failed=0
function check(name,cond,detail){if(cond){passed++;return}failed++;console.log("  FAIL  "+name+(detail?"  ->  "+detail:""))}
function eq(name,a,b){check(name,JSON.stringify(a)===JSON.stringify(b),JSON.stringify(a)+" != "+JSON.stringify(b))}
// ---- pure helpers
const sandbox={module:{exports:{}},document:{addEventListener(){}},console}
vm.createContext(sandbox)
vm.runInContext(PAGE,sandbox)
const C=sandbox.module.exports
const items=[{id:1,name:"Recon basics",caller:"recon",step_count:3},{id:2,name:"DEMO External web quick wins",caller:"web-quick",step_count:3},{id:3,name:"Full sweep",caller:"",step_count:0}]
eq("filter: blank keeps all, in order",C.chainsFilterItems(items,"  ").map((p)=>p.id),[1,2,3])
eq("filter: by name, case-insensitive",C.chainsFilterItems(items,"WEB").map((p)=>p.id),[2])
eq("filter: by caller with or without the slash",[C.chainsFilterItems(items,"/recon").map((p)=>p.id),C.chainsFilterItems(items,"quick").map((p)=>p.id)],[[1],[2]])
eq("filter: every word must match",C.chainsFilterItems(items,"demo wins").map((p)=>p.id),[2])
eq("filter: no match",C.chainsFilterItems(items,"zzz"),[])
check("filter: does not reorder or mutate the input",C.chainsFilterItems(items,"")!==items&&items[0].id===1)
eq("filter: null-safe",[C.chainsFilterItems(null,"x"),C.chainsFilterItems([{id:9}],"")].map((r)=>r.length),[0,1])
// ---- dock order: Commands then Chains on the left; Terminal then CVE Intel on the right
const group=(id)=>{const m=new RegExp('<div class="bottom-nav-group" id="'+id+'">([\\s\\S]*?)</div>').exec(MAIN);return m?m[1]:""}
const slots=(html)=>(html.match(/<button[^>]*>/g)||[]).map((b)=>{const p=/data-page="([^"]+)"/.exec(b);return p?p[1]:(/id="dockTerminalBtn"/.test(b)?"terminal":"?")})
eq("dock: left group order",slots(group("bottomNavLeft")),["dashboard","notes","reporting","commands","chains"])
eq("dock: right group order",slots(group("bottomNavRight")),["terminal","cve","targets","snippets","settings"])
check("dock: AI button sits between the groups",MAIN.indexOf('id="bottomNavLeft"')<MAIN.indexOf('id="aiToggleBtn"')&&MAIN.indexOf('id="aiToggleBtn"')<MAIN.indexOf('id="bottomNavRight"'))
check("dock: Chains button has its icon, label and a tooltip",/<button class="nav-btn" data-page="chains" title="[^"]+"><i class="icon icon-chain"><\/i><span>Chains<\/span><\/button>/.test(MAIN))
check("icon: chain.svg exists, 24x24 stroke-2 round caps",(()=>{const s=read("Assets","icons","chain.svg");return /viewBox="0 0 24 24"/.test(s)&&/stroke-width="2"/.test(s)&&/stroke-linecap="round"/.test(s)})())
check("icon: .icon-chain rule with the -webkit- mask twin",/\.icon-chain\{-webkit-mask-image:url\(\.\.\/\.\.\/Assets\/icons\/chain\.svg\);mask-image:url\(\.\.\/\.\.\/Assets\/icons\/chain\.svg\)\}/.test(COMPONENTS))
// ---- dock fits: ten 78px slots + gaps + the AI button (42px + 14px margins when open) + 6px padding + 1px border
const fit=10*78+2*4*4+2*4+42+28+12+2
const maxW=/\.bottom-nav\.expanded\{[^}]*max-width:min\((\d+)px/.exec(LAYOUT)
check("dock: expanded max-width holds every slot",maxW&&Number(maxW[1])>=fit,(maxW&&maxW[1])+" < "+fit)
check("dock: narrow windows shrink the slots instead of clipping",/@media \(max-width:960px\)/.test(LAYOUT)&&/@media \(max-width:800px\)/.test(LAYOUT)&&/@media \(max-width:620px\)/.test(LAYOUT))
const narrow=10*36+2*4*2+2*2+36+8+12+2
check("dock: the narrowest layout fits the 460px minimum window",narrow<=460,String(narrow))
// ---- page registration
check("main: page section after Commands",MAIN.indexOf('<section class="page" data-page="commands"></section>\n<section class="page" data-page="chains"></section>')>0)
check("main: chains.js loads after commands.js and before app.js",MAIN.indexOf("pages/commands.js")>0&&MAIN.indexOf("pages/commands.js")<MAIN.indexOf("pages/chains.js")&&MAIN.indexOf("pages/chains.js")<MAIN.indexOf("js/app.js"))
const links=MAIN.match(/<link rel="stylesheet"[^>]*>/g)||[]
check("main: chains.css linked, glass.css stays last",links.some((l)=>l.includes("pages/chains.css"))&&links[links.length-1].includes("glass.css"))
check("app: page loader registered",APP.includes("chains:initChains"))
check("page: loads its own html",PAGE.includes('fetch("../pages/chains.html")')&&PAGE.includes('.page[data-page="chains"]'))
check("page: refreshes on loya:page-shown",/addEventListener\("loya:page-shown",[\s\S]{0,120}e\.detail\.page!=="chains"\|\|e\.detail\.first/.test(PAGE))
check("page: Add Step loads commands itself",/function chainsOpenAddStepPopover[\s\S]*bridgeCall\("commands\.list"\)/.test(PAGE)&&!/cmdsState\.rows/.test(PAGE))
check("page: a stale chain load never overwrites a newer one",(PAGE.match(/if\(String\(chainsState\.currentId\)!==String\(id\)\)return/g)||[]).length===2)
check("page: runs are tagged as from the Chains page",PAGE.includes('source:"chains"'))
check("html: toolbar with search and New chain",/id="chainsSearchInput"/.test(HTML)&&/<button[^>]*id="chainsNewBtn"[^>]*aria-haspopup="dialog"[^>]*>.*?<span>New chain<\/span><\/button>/.test(HTML))
check("html: the old New Diagram button is gone",!HTML.includes("chainsNewDiagramBtn")&&!HTML.includes("New Diagram")&&!HTML.includes("New Action Chain"))
{const tb=(/<div class="cmds-toolbar chains-toolbar">([\s\S]*?)\n<div class="cmds-search chh-history-only"/.exec(HTML)||[])[1]||""
eq("html: exactly one New button in the toolbar",(tb.match(/<button[^>]*>(?:(?!<\/button>)[\s\S])*?<span>New[^<]*<\/span><\/button>/g)||[]).length,1)}
check("page: #chainsNewBtn opens the chooser",PAGE.includes('document.getElementById("chainsNewBtn").addEventListener("click",chainsNewChooser)')&&!PAGE.includes('addEventListener("click",chainsCreatePrompt)'))
check("page: empty list button is New chain and opens the chooser",/<span>New chain<\/span><\/button>'\nempty\.querySelector\("button"\)\.addEventListener\("click",chainsNewChooser\)/.test(PAGE))
check("page: the list is decorated after both render paths",(PAGE.match(/^chainsDecorateList\(wrap\)$/gm)||[]).length===2&&PAGE.includes("chainsFlowDecorateList(wrap,chainsState.search)"))
const ids=["cmdsPlaybooksWrap","cmdsPlaybooksList","cmdsPlaybookDetail","cmdsPlaybookBackBtn","cmdsPlaybookTitle","cmdsPlaybookRunAllBtn","cmdsPlaybookStepThroughBtn","cmdsPlaybookAddStepBtn","cmdsPlaybookDeleteBtn","cmdsChainCallerWrap","cmdsChainCallerInput","cmdsChainCallerErr","cmdsChainRunHost","cmdsPlaybookSteps"]
eq("html: every chain element moved to the Chains page",ids.filter((id)=>!HTML.includes('id="'+id+'"')),[])
eq("html: and none left on Commands",ids.filter((id)=>CMDS_HTML.includes('id="'+id+'"')),[])
eq("html: mount points for other chain views",["chainsToolbarSlot","chainsViewSwitchSlot","chainsEditorArea","chainsDiagramHost","chainsFlowHost","chainsOpenDiagramBtn"].filter((id)=>!HTML.includes('id="'+id+'"')),[])
check("html: the step list and the diagram host share the editor area",/id="chainsEditorArea">\n<div class="cmds-playbook-steps" id="cmdsPlaybookSteps"><\/div>\n<div class="chains-diagram-host hidden" id="chainsDiagramHost"><\/div>/.test(HTML))
check("page: announces each render for other views",PAGE.includes('new CustomEvent("loya:chain-rendered",{detail:{id:pb.id,playbook:pb}})')&&(PAGE.match(/chainsNotifyRendered\(\)/g)||[]).length===3)
check("page: diagram editor hooks",PAGE.includes('if(typeof chainsFlowDecorateCard==="function")chainsFlowDecorateCard(card,pb)')&&/function chainsOpenChain\(id\)\{\n\/\/[^\n]*\nif\(typeof chainsFlowOpenChain==="function"&&chainsFlowOpenChain\(id\)\)return Promise\.resolve\(\)/.test(PAGE))
check("html: static page has no inline handlers or scripts",!/\son[a-z]+\s*=|<script/i.test(HTML))
// ---- Commands only shows commands
check("commands: no mode toggle left",!/cmdsMode|cmds-mode/.test(CMDS_HTML+CMDS)&&!/cmds-mode/.test(read("UI","css","pages","commands.css")))
check("commands: no chain code left",!/playbook/i.test(CMDS))
// ---- every way in now lands on Chains
check("action-chains: follows the Chains page state",AC.includes('typeof chainsState!=="undefined"&&String(chainsState.currentId)===String(ctx.id)')&&!AC.includes("cmdsPlaybookState"))
check("action-chains: Chains runs mount on the page host",/if\(source==="chains"\|\|source==="commands"\)\{\nconst host=document\.getElementById\("cmdsChainRunHost"\)/.test(AC))
check("action-chains: run card links back to the chain",AC.includes('data-ac="open"')&&AC.includes('what==="open"&&typeof loyaOpenChain==="function")loyaOpenChain(run.playbookId)'))
check("palette: Go to Chains and New chain",PALETTE.includes('run:()=>goToPage("chains")}')&&PALETTE.includes('label:"New chain"')&&PALETTE.includes('goToPage("chains").then(()=>chainsNewChooser())')&&!PALETTE.includes("New Action Chain"))
check("dashboard: Chains quick action opens Chains",DASH.includes('if(q==="playbooks")return dashQuickGoto("chains")')&&!DASH.includes("cmdsModePlaybooksBtn")&&CARD.includes('{q:"playbooks",label:"Chains",icon:"chain"'))
check("public: loyaOpenChain opens the page then the chain",/function loyaOpenChain\(id\)\{\nreturn Promise\.resolve\(goToPage\("chains"\)\)/.test(PAGE))
// ---- nothing anywhere still points at the old mode
const grepRoots=[["UI","js"],["UI","pages"],["UI","windows"]]
const stale=[]
for(const r of grepRoots){
const dir=path.join(ROOT,...r)
const walk=(d)=>fs.readdirSync(d,{withFileTypes:true}).forEach((e)=>{const p=path.join(d,e.name);if(e.isDirectory())walk(p);else if(/\.(js|html)$/.test(e.name)&&/cmdsModePlaybooksBtn|cmdsSwitchMode|cmdsPlaybookState|Commands\s*(->|→)\s*Action Chains/.test(fs.readFileSync(p,"utf8")))stale.push(path.relative(ROOT,p))})
walk(dir)
}
eq("no stale references to Commands -> Action Chains",stale,[])
check("readme: describes the Chains tab",/^### Chains\b/m.test(read("README.md"))&&!/Commands → Action Chains/.test(read("README.md")))
check("confirm dialogs: plain body text is sized like the message, not the 16px page default",/\.confirm-body\{[^}]*font-size:12\.5px/.test(COMPONENTS))
check("chains toolbar wraps on narrow content instead of overflowing",/\.chains-toolbar\{flex-wrap:wrap/.test(read("UI","css","pages","chains.css")))
// ---- New chain chooser: pure helpers
{
const withD=C.chainsNewOptions(true),noD=C.chainsNewOptions(false)
eq("new: with diagrams the order is blank, demo, template, steps",withD.map((o)=>o.id),["blank","demo","template","steps"])
eq("new: without diagrams only the step list",noD.map((o)=>o.id),["steps"])
check("new: every option has a label, desc and icon",withD.every((o)=>o.label&&o.desc&&o.icon))
check("new: Blank diagram is first and named",withD[0].label==="Blank diagram")
const h=C.chainsNewChooserHtml(withD)
eq("new html: one button per option, data-new ids in order",(h.match(/data-new="([^"]+)"/g)||[]).map((x)=>x.slice(10,-1)),["blank","demo","template","steps"])
eq("new html: only the first is the default and selected",[(h.match(/is-default/g)||[]).length,(h.match(/aria-selected="true"/g)||[]).length,(h.match(/aria-selected="false"/g)||[]).length],[1,1,3])
check("new html: the default is the blank option",/class="chains-new-opt is-default" role="option" aria-selected="true" data-new="blank"/.test(h))
check("new html: options are type=button inside a labelled listbox",(h.match(/<button type="button" class="chains-new-opt/g)||[]).length===4&&/role="listbox" aria-labelledby="chainsNewChooserTitle"/.test(h)&&h.includes('id="chainsNewChooserTitle">New chain<'))
check("new html: has a Cancel button",h.includes('<button type="button" data-new-x="cancel">Cancel</button>'))
const evil=C.chainsNewChooserHtml([{id:'x"><b>',label:"<img src=x onerror=1>",desc:"a&b",icon:'i"x'}])
check("new html: label, desc, id and icon are escaped",!evil.includes("<img")&&!evil.includes("<b>")&&evil.includes("&lt;img")&&evil.includes("a&amp;b")&&evil.includes('data-new="x&quot;&gt;&lt;b&gt;"')&&evil.includes("icon-i&quot;x"))
eq("new html: null-safe",(C.chainsNewChooserHtml(null).match(/data-new=/g)||[]).length,0)
}
// ---- New chain chooser: behaviour in a sandbox
function chooserBox(diagrams){
const calls=[],modal={open:[],closed:[]},timers=[]
const mkEl=()=>{const el={attrs:{},listeners:{},className:"",innerHTML:"",setAttribute(k,v){this.attrs[k]=String(v)},addEventListener(t,f){(this.listeners[t]=this.listeners[t]||[]).push(f)},
opts:null,
querySelectorAll(sel){return sel===".chains-new-opt"?this.optEls():[]},
querySelector(sel){return sel===".chains-new-opt"?this.optEls()[0]||null:null},
optEls(){if(!this.opts)this.opts=(this.innerHTML.match(/data-new="[^"]+"/g)||[]).map((m)=>{const o={id:m.slice(10,-1),focus(){box.doc.activeElement=o}};return o});return this.opts},
fire(t,e){(this.listeners[t]||[]).forEach((f)=>f(e))}};return el}
const doc={addEventListener(){},activeElement:null,createElement:()=>mkEl()}
const sb={module:{exports:{}},document:doc,console,setTimeout:(f)=>{timers.push(f);return timers.length},
openModal:(el)=>modal.open.push(el),closeModal:(x)=>modal.closed.push(x===undefined?null:x)}
if(diagrams){
sb.chainsFlowNewPrompt=(...a)=>calls.push(["blank",...a])
sb.chainsFlowDemosPrompt=(...a)=>calls.push(["demo",...a])
sb.chainsFlowTemplatesPrompt=(...a)=>calls.push(["template",...a])
}
vm.createContext(sb)
vm.runInContext(PAGE,sb)
vm.runInContext("chainsCreatePrompt=(...a)=>__calls.push(['steps',...a])",Object.assign(sb,{__calls:calls}))
const box={sb,calls,modal,timers,doc}
return box
}
const target=(attr,val)=>({closest(sel){if(attr==="cancel")return sel==='[data-new-x="cancel"]'?this:null;if(attr==="opt"&&sel==="[data-new]")return this;return null},dataset:{new:val}})
{
const b=chooserBox(true)
const pop=vm.runInContext("chainsNewChooser()",b.sb)
check("chooser: opens one modal popover with the dialog role",b.modal.open.length===1&&b.modal.open[0]===pop&&pop.attrs.role==="dialog"&&pop.attrs["aria-label"]==="New chain"&&/chains-new-chooser/.test(pop.className))
eq("chooser: shows the four options",pop.optEls().map((o)=>o.id),["blank","demo","template","steps"])
eq("chooser: nothing chosen yet",b.calls,[])
b.timers.forEach((f)=>f())
check("chooser: the first option gets focus",b.doc.activeElement&&b.doc.activeElement.id==="blank")
const key=(k)=>{let prevented=false;pop.fire("keydown",{key:k,preventDefault(){prevented=true}});return prevented}
check("chooser: ArrowDown moves focus and is consumed",key("ArrowDown")&&b.doc.activeElement.id==="demo")
key("ArrowDown");key("ArrowDown")
eq("chooser: ArrowDown reaches the last option",b.doc.activeElement.id,"steps")
key("ArrowDown")
eq("chooser: ArrowDown wraps to the first",b.doc.activeElement.id,"blank")
key("ArrowUp")
eq("chooser: ArrowUp wraps to the last",b.doc.activeElement.id,"steps")
check("chooser: other keys are left alone",!key("Enter")&&b.doc.activeElement.id==="steps")
pop.fire("click",{target:{}})
pop.fire("click",{target:null})
check("chooser: a click outside any option does nothing",b.calls.length===0&&b.modal.closed.length===0)
pop.fire("click",{target:target("cancel")})
check("chooser: Cancel closes without choosing",b.modal.closed.length===1&&b.modal.closed[0]===null&&b.calls.length===0)
}
for(const [kind,want] of [["blank",["blank",null,{blank:true}]],["demo",["demo"]],["template",["template"]],["steps",["steps"]]]){
const b=chooserBox(true)
const pop=vm.runInContext("chainsNewChooser()",b.sb)
pop.fire("click",{target:target("opt",kind)})
eq("chooser: clicking "+kind+" closes the chooser and opens the right dialog",[b.modal.closed,JSON.parse(JSON.stringify(b.calls))],[[true],[want]])
}
{
const b=chooserBox(true)
vm.runInContext('chainsNewChoose("bogus")',b.sb)
eq("choose: an unknown kind falls back to a blank diagram",JSON.parse(JSON.stringify(b.calls)),[["blank",null,{blank:true}]])
}
{
const b=chooserBox(false)
const r=vm.runInContext("chainsNewChooser()",b.sb)
check("chooser: without the diagram editor the step list prompt opens directly",b.modal.open.length===0&&b.calls.length===1&&b.calls[0][0]==="steps"&&typeof r==="number")
b.calls.length=0
;["blank","demo","template"].forEach((k)=>vm.runInContext("chainsNewChoose("+JSON.stringify(k)+")",b.sb))
eq("choose: without the diagram editor every kind is the step list",b.calls.map((c)=>c[0]),["steps","steps","steps"])
}
console.log("chains_page: "+passed+" passed, "+failed+" failed")
process.exit(failed?1:0)
