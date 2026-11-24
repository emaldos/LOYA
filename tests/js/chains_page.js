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
check("html: toolbar with search and New Action Chain",/id="chainsSearchInput"/.test(HTML)&&/id="chainsNewBtn"[^>]*>[\s\S]*New Action Chain/.test(HTML))
const ids=["cmdsPlaybooksWrap","cmdsPlaybooksList","cmdsPlaybookDetail","cmdsPlaybookBackBtn","cmdsPlaybookTitle","cmdsPlaybookRunAllBtn","cmdsPlaybookStepThroughBtn","cmdsPlaybookAddStepBtn","cmdsPlaybookDeleteBtn","cmdsChainCallerWrap","cmdsChainCallerInput","cmdsChainCallerErr","cmdsChainRunHost","cmdsPlaybookSteps"]
eq("html: every chain element moved to the Chains page",ids.filter((id)=>!HTML.includes('id="'+id+'"')),[])
eq("html: and none left on Commands",ids.filter((id)=>CMDS_HTML.includes('id="'+id+'"')),[])
eq("html: mount points for other chain views",["chainsToolbarSlot","chainsViewSwitchSlot","chainsEditorArea","chainsDiagramHost","chainsFlowHost","chainsNewDiagramBtn","chainsOpenDiagramBtn"].filter((id)=>!HTML.includes('id="'+id+'"')),[])
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
check("palette: Go to Chains and New Action Chain",PALETTE.includes('run:()=>goToPage("chains")}')&&PALETTE.includes('goToPage("chains").then(()=>chainsCreatePrompt())'))
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
console.log("chains_page: "+passed+" passed, "+failed+" failed")
process.exit(failed?1:0)
