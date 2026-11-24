// The Chains page "Run History" sub-tab (UI/js/pages/chains_history.js, UI/css/chains-history.css) and its wiring in
// chains.html / chains.js / main.html: pure helpers, escaping, the list and run view in a small fake DOM, and the dialogs.
const fs=require("fs")
const path=require("path")
const vm=require("vm")
const ROOT=path.resolve(__dirname,"..","..")
const read=(...p)=>fs.readFileSync(path.join(ROOT,...p),"utf8")
const SRC=read("UI","js","pages","chains_history.js")
const PAGE=read("UI","js","pages","chains.js")
const HTML=read("UI","pages","chains.html")
const MAIN=read("UI","windows","main.html")
const CSS=read("UI","css","chains-history.css")
let passed=0,failed=0
function check(name,cond,detail){if(cond){passed++;return}failed++;console.log("  FAIL  "+name+(detail?"  ->  "+detail:""))}
function eq(name,a,b){check(name,JSON.stringify(a)===JSON.stringify(b),JSON.stringify(a)+" != "+JSON.stringify(b))}
const sandbox={module:{exports:{}},console,Date,setTimeout,clearTimeout}
vm.createContext(sandbox)
vm.runInContext(SRC,sandbox)
const H=sandbox.module.exports
// ---- pure helpers
eq("escape",H.chhEscape('<img src=x onerror="a">&\''),"&lt;img src=x onerror=&quot;a&quot;&gt;&amp;&#39;")
eq("duration",[H.chhDuration(850),H.chhDuration(12345),H.chhDuration(65000),H.chhDuration(3723000),H.chhDuration(null),H.chhDuration("x")],["850 ms","12 s","1 min 05 s","1 h 02 min","",""])
eq("duration: under 10 s keeps a decimal",H.chhDuration(4300),"4.3 s")
eq("state labels and kinds",[H.chhStateLabel("cancelled"),H.chhStateKind("done"),H.chhStateKind("failed"),H.chhStateKind("timeout"),H.chhStateKind("cancelled"),H.chhStateKind("running")],["Stopped","ok","bad","bad","muted","live"])
eq("node state kinds",["success","fail","skipped","running","pending"].map(H.chhNodeStateKind),["ok","bad","muted","live","idle"])
eq("trigger labels",[H.chhTriggerLabel("caller"),H.chhTriggerLabel("ai",true),H.chhTriggerLabel("")],["/caller","AI (imported)","-"])
eq("node counts text",[H.chhNodesText({total:6,success:4,fail:1,skipped:1}),H.chhNodesText({total:0}),H.chhNodesText(null)],["4/6 ok, 1 failed, 1 skipped","-","-"])
check("time: local wall clock",/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(H.chhTime("2026-11-24T10:00:00+00:00"))&&H.chhTime("junk")==="")
const now=new Date(2026,10,24,15,30,0)
const today=H.chhRangeBounds("today","","",now)
eq("range: today starts at local midnight",new Date(today.date_from).getHours()+":"+new Date(today.date_from).getMinutes(),"0:0")
eq("range: 7 days",Date.parse(H.chhRangeBounds("7d","","",now).date_from),now.getTime()-7*86400000)
const custom=H.chhRangeBounds("custom","2026-11-01","2026-11-03",now)
eq("range: custom is whole local days",[new Date(custom.date_from).getDate(),new Date(custom.date_to).getDate(),new Date(custom.date_to).getHours()],[1,3,23])
eq("range: custom with a bad day stays open",H.chhRangeBounds("custom","nope","",now),{date_from:"",date_to:""})
eq("range: any time",H.chhRangeBounds("","","",now),{date_from:"",date_to:""})
const q=H.chhQuery({query:" nmap ",chain:"id:7",state:"failed",trigger:"ai",range:""},50,now)
eq("query: chain id, state, trigger, paging",[q.query,q.playbook_id,q.state,q.source,q.offset,q.limit],["nmap",7,"failed","ai",50,H.CHH_PAGE])
eq("query: an orphaned chain filters by name, imported by mode",[H.chhQuery({chain:"name:Old one",trigger:"import"},0,now).chain,H.chhQuery({trigger:"import"},0,now).mode,H.chhQuery({trigger:"import"},0,now).source],["Old one","import",undefined])
eq("filtered?",[H.chhFiltered({}),H.chhFiltered({query:"  "}),H.chhFiltered({state:"done"})],[false,false,true])
const bars=H.chhTimelineBars([{node:"a",title:"A",state:"success",started_at:"2026-01-01T00:00:00Z",ended_at:"2026-01-01T00:00:05Z"},{node:"b",title:"B",state:"fail",started_at:"2026-01-01T00:00:05Z",ended_at:"2026-01-01T00:00:10Z"},{node:"c",state:"pending"}],"2026-01-01T00:00:00Z","2026-01-01T00:00:10Z")
eq("timeline bars: only nodes that ran, in percent",bars.map((b)=>[b.node,b.left,b.width,b.kind]),[["a",0,50,"ok"],["b",50,50,"bad"]])
eq("timeline bars: a zero-length node still shows",H.chhTimelineBars([{node:"a",state:"success",started_at:"2026-01-01T00:00:00Z",ended_at:"2026-01-01T00:00:00Z"}],"2026-01-01T00:00:00Z","2026-01-01T00:01:00Z")[0].width,0.6)
// ---- preview / result text
const prev=H.chhPreviewHtml({chains:[{name:"<b>evil</b>",nodes:3,scripts:1,conflict:{playbook_id:1}}],runs:[{run_id:"r1"}],chain_conflicts:1,run_conflicts:1,scripts:1,history_overflow:2,problems:["bad <x>"]},"file<1>.json")
check("preview: everything from the file is escaped",!/<b>evil|<x>|file<1>/.test(prev)&&prev.includes("&lt;b&gt;evil")&&prev.includes("file&lt;1&gt;.json"))
check("preview: collision choices for chains and runs",/name="chhChainMode" value="rename" checked/.test(prev)&&/value="skip"/.test(prev)&&/value="replace"/.test(prev)&&/name="chhRunMode" value="skip" checked/.test(prev)&&/name="chhRunMode" value="rename"/.test(prev))
check("preview: imported chains need a review, scripts called out, history overflow and problems shown",/Imported - review/.test(prev)&&/1 script/.test(prev)&&/2 older runs will be removed/.test(prev)&&/Left out/.test(prev))
check("preview: both sections can be switched off",/chh-imp-chains/.test(prev)&&/chh-imp-runs/.test(prev))
check("preview: no collision block without collisions",!/chhChainMode/.test(H.chhPreviewHtml({chains:[{name:"x",nodes:1}],runs:[]})))
eq("result text",H.chhResultText({chains:{created:[1,2],replaced:[3],skipped:[]},runs:{imported:1,skipped:2},problems:["x"]}),"2 chains imported, 1 replaced, 1 run imported, 2 runs skipped, 1 left out")
eq("result text: nothing",H.chhResultText({}),"Nothing was imported")
// ---- wiring
const at=(s)=>MAIN.indexOf(s)
check("main: chains_history.js loads after chains_flow.js and flow-log.js, before app.js",at("pages/chains_history.js")>at("pages/chains_flow.js")&&at("pages/chains_history.js")>at("components/flow-log.js")&&at("pages/chains_history.js")<at("js/app.js"))
const links=(MAIN.match(/<link rel="stylesheet"[^>]*>/g)||[]).map((l)=>/css\/([^"]+)"/.exec(l)[1])
check("main: chains-history.css is linked once, before glass.css, and glass.css stays last",links.filter((l)=>l==="chains-history.css").length===1&&links.indexOf("chains-history.css")<links.indexOf("glass.css")&&links[links.length-1]==="glass.css")
check("html: the sub-tab switch is a tablist with both tabs",/class="chh-switch" role="tablist"/.test(HTML)&&/data-chains-tab="chains" aria-selected="true"/.test(HTML)&&/data-chains-tab="history" aria-selected="false"/.test(HTML))
check("html: the history panel sits after the diagram host",HTML.indexOf('id="chainsHistoryHost"')>HTML.indexOf('id="chainsFlowHost"'))
check("html: history toolbar items and chains bundle buttons",["chhSearchInput","chhRefreshBtn","chhImportBtn","chhExportBtn","chhDeleteBtn","chhClearBtn","chainsExportBtn","chainsImportBundleBtn","chainsDetailHistoryBtn"].every((id)=>HTML.includes('id="'+id+'"')))
check("html: still no inline handlers or scripts",!/\son[a-z]+\s*=|<script/i.test(HTML))
check("chains.js: switch, entry point, the diagram editor forces the Chains tab",/function chainsSetTab\(tab,opts\)/.test(PAGE)&&/function loyaOpenChainHistory\(playbookId\)/.test(PAGE)&&/new MutationObserver\(\(\)=>\{if\(!flowHost\.classList\.contains\("hidden"\)&&chainsState\.tab!=="chains"\)chainsSetTab\("chains"\)\}\)/.test(PAGE))
const pageSandbox={module:{exports:{}},document:{addEventListener(){}},console}
vm.createContext(pageSandbox);vm.runInContext(PAGE,pageSandbox)
eq("chains.js: tab names",["history","chains","x",undefined].map(pageSandbox.module.exports.chainsTabName),["history","chains","chains","chains"])
check("css: tokens only (no hard-coded colours)",!/#[0-9a-fA-F]{3,8}\b|rgba?\(/.test(CSS))
check("css: the history toolbar items hide on the Chains tab and the other way round",CSS.includes('.page[data-page="chains"]:not(.chh-history-on) .chh-history-only{display:none}')&&CSS.includes('.page[data-page="chains"].chh-history-on .chains-toolbar>:not(.chh-switch):not(.chh-history-only){display:none}'))
check("css: light theme has its own warn colour",/\[data-theme="light"\]\{--chh-warn:/.test(CSS))
check("js: every bridge call is a chainHistory method or the log viewer",(SRC.match(/chhBridge\("([^"]+)"/g)||[]).every((m)=>/chhBridge\("chainHistory\./.test(m)))
check("js: deletes and clears always confirm first",/function chhDeleteSelected\(\)\{\nconst ids=[^\n]*\nif\(!ids\.length\)return\nappConfirm\(/.test(SRC)&&/function chhClearPrompt\(\)\{[\s\S]*?appConfirm\([\s\S]*?danger:true/.test(SRC)&&/if\(what==="delete"\)\{\nappConfirm\(/.test(SRC))
check("js: the run log opens in flow-log.js (colours and search)",SRC.includes("flowLogOpen({runId:d.run_id"))
// ---- the list and run view in a tiny fake DOM
function fakeDom(){
const nodes={}
function el(tag){
const e={tagName:tag,children:[],dataset:{},style:{},attrs:{},listeners:{},_html:"",textContent:"",value:"",checked:false,disabled:false,
classList:{set:new Set(),add(c){this.set.add(c)},remove(c){this.set.delete(c)},contains(c){return this.set.has(c)},toggle(c,on){if(on===undefined?!this.set.has(c):on)this.set.add(c);else this.set.delete(c)}},
addEventListener(t,f){(this.listeners[t]=this.listeners[t]||[]).push(f)},setAttribute(k,v){this.attrs[k]=v},
querySelector(){return el("span")},querySelectorAll(){return []}}
Object.defineProperty(e,"innerHTML",{get(){return e._html},set(v){e._html=String(v)}})
return e
}
return {el,nodes}
}
const dom=fakeDom()
const host=dom.el("div")
const parts={}
host.querySelector=(sel)=>{parts[sel]=parts[sel]||dom.el("x");return parts[sel]}
host.querySelectorAll=()=>[]
const calls=[]
const responses={"chainHistory.facets":{chains:[{playbook_id:1,name:"Recon <x>",count:2,exists:true}],all_chains:[{playbook_id:1,name:"Recon <x>"}],states:{},total:2},
"chainHistory.list":{items:[{run_id:"r1",playbook_id:1,chain_name:"Recon <x>",chain_exists:true,state:"failed",reason:"node <b> failed",source:"ai",target:"<t>",started_at:"2026-11-24T10:00:00Z",ended_at:"2026-11-24T10:00:05Z",duration_ms:5000,nodes:{total:3,success:1,fail:1,skipped:1},live:false,imported:false,mode:"run"}],total:1},
"chainHistory.detail":{run_id:"r1",playbook_id:1,chain_name:"Recon <x>",chain_exists:true,state:"failed",source:"ai",target:"<t>",started_at:"2026-11-24T10:00:00Z",ended_at:"2026-11-24T10:00:05Z",duration_ms:5000,nodes:{total:2,success:1,fail:1},live:false,mode:"run",
timeline:[{node:"n1",title:"Ping <i>",type:"command",state:"success",started_at:"2026-11-24T10:00:00Z",ended_at:"2026-11-24T10:00:02Z",duration_ms:2000,exit_code:0,stdout:"<script>alert(1)</script>",stderr:"",resolved:["ping 1.2.3.4"],error:""},{node:"n2",title:"Scan",type:"command",state:"fail",started_at:"2026-11-24T10:00:02Z",ended_at:"2026-11-24T10:00:05Z",duration_ms:3000,exit_code:1,stdout:"",stderr:"boom",resolved:[],error:"Exit code 1"}]}}
const ui=Object.assign({},sandbox,{module:{exports:{}},document:{getElementById:(id)=>id==="chainsHistoryHost"?host:(dom.nodes[id]=dom.nodes[id]||dom.el(id)),addEventListener(){},querySelector:()=>null,querySelectorAll:()=>[]},
bridgeCall:(p,a)=>{calls.push([p,a]);return Promise.resolve(JSON.parse(JSON.stringify(responses[p]||{})))},showToast(){},appConfirm:()=>Promise.resolve(false)})
vm.createContext(ui)
vm.runInContext(SRC,ui)
const flush=()=>new Promise((r)=>setTimeout(r,0))
;(async()=>{
vm.runInContext("chhShow({playbookId:1})",ui)
await flush();await flush()
const listCall=calls.find((c)=>c[0]==="chainHistory.list")
eq("ui: opening for one chain filters by its id",listCall&&listCall[1][0].playbook_id,1)
const rows=parts[".chh-body"].innerHTML
check("ui: the row shows status, duration, counts, trigger and target",/chh-pill chh-bad"[^>]*>Failed/.test(rows)&&rows.includes("5.0 s")&&rows.includes("1/3 ok, 1 failed, 1 skipped")&&rows.includes(">AI<"),rows.slice(0,400))
check("ui: row text is escaped",!/<x>|<t>|node <b>/.test(rows)&&rows.includes("Recon &lt;x&gt;"))
vm.runInContext('chhOpenRun("r1")',ui)
await flush();await flush()
const view=parts[".chh-detail-view"].innerHTML
check("ui: run view has facts, timeline and per-node results",/chh-facts/.test(view)&&/chh-gantt-bar chh-ok/.test(view)&&/chh-gantt-bar chh-bad/.test(view)&&/chh-node chh-node-bad/.test(view)&&view.includes("exit 1"))
check("ui: node output is escaped",!/<script>|<i>/.test(view)&&view.includes("&lt;script&gt;alert(1)&lt;/script&gt;"))
check("ui: run view actions",["d-log","d-chain","d-export","d-delete","d-back"].every((a)=>view.includes('data-chh="'+a+'"')))
console.log("chains_history: "+passed+" passed, "+failed+" failed")
process.exit(failed?1:0)
})().catch((e)=>{console.log("  FAIL  ui crashed: "+(e&&e.stack||e));console.log("chains_history: "+passed+" passed, "+(failed+1)+" failed");process.exit(1)})
