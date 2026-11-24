// AI panel chain cards (UI/js/components/ai-chain-card.js): block detection, the outline, escaping of hostile model output,
// tool-call detection, and - in a small fake DOM - what the card's buttons do. Run: node tests/js/ai_chain_card.js
const fs=require("fs")
const path=require("path")
const vm=require("vm")
const ROOT=path.resolve(__dirname,"..","..")
const FILE=path.join(ROOT,"UI","js","components","ai-chain-card.js")
const card=require(FILE)
let passed=0,failed=0
function check(name,cond,detail){if(cond){passed++;return}failed++;console.log("  FAIL  "+name+(detail?"  ->  "+detail:""))}
function eq(name,a,b){check(name,JSON.stringify(a)===JSON.stringify(b),JSON.stringify(a)+" != "+JSON.stringify(b))}
const GRAPH={schema:1,nodes:[
{id:"n1",type:"start",title:"Start",x:40,y:160,config:{}},
{id:"n2",type:"command",title:"Ping the host",x:300,y:160,config:{commands:[{text:"ping -c 2 {IPv4}"}],timeout:60}},
{id:"n3",type:"decision",title:"Host alive?",x:560,y:160,config:{branches:[{name:"alive",match:"all",conditions:[{source:"host_up",op:"is_true"}]}],else:"down"}},
{id:"n4",type:"command",title:"Nmap scan",x:820,y:160,config:{commands:[{text:"nmap -Pn -sV {IPv4}"},{text:"nmap -sU {IPv4}"}]}},
{id:"n5",type:"output",title:"Host is down",x:820,y:310,config:{action:"notify",title:"Host did not answer"}}],
edges:[{id:"e1",from:"n1",port:"out",to:"n2"},{id:"e2",from:"n2",port:"success",to:"n3"},{id:"e3",from:"n2",port:"fail",to:"n3"},{id:"e4",from:"n3",port:"alive",to:"n4"},{id:"e5",from:"n3",port:"down",to:"n5"}]}
const BUNDLE=JSON.stringify({name:"Ping then scan",graph:GRAPH})
const fence=(body,tag)=>"```"+(tag===undefined?"loya-chain":tag)+"\n"+body+"\n```"
// ---- parsing and detection
eq("fence name",card.AI_CHAIN_FENCE,"loya-chain")
let p=card.aiChainParse(BUNDLE)
eq("parse {name,graph}",[p.ok,p.name,p.graph.nodes.length],[true,"Ping then scan",5])
p=card.aiChainParse(JSON.stringify(GRAPH))
eq("parse a bare graph",[p.ok,p.name,p.graph.edges.length],[true,"",5])
p=card.aiChainParse(JSON.stringify({loya_chain:1,name:"Exported",caller:"x",graph:GRAPH}))
eq("parse an export bundle",[p.ok,p.name],[true,"Exported"])
eq("parse: nodes without edges gets an empty edge list",card.aiChainParse('{"nodes":[]}').graph.edges,[])
check("parse: broken JSON is an error, not a throw",card.aiChainParse("{nodes:[").ok===false&&/not valid JSON/.test(card.aiChainParse("{nodes:[").error))
check("parse: an array is refused",card.aiChainParse("[1,2]").ok===false)
check("parse: no nodes list is refused",/nodes/.test(card.aiChainParse('{"name":"x"}').error))
check("parse: empty is refused",card.aiChainParse("  ").ok===false)
check("parse: an oversized block is refused",card.aiChainParse('{"nodes":[],"pad":"'+"x".repeat(700000)+'"}').ok===false)
check("parse: a name that is not text is dropped",card.aiChainParse(JSON.stringify({name:{toString:1},graph:GRAPH})).name==="")
const reply="Here is the chain.\n\n"+fence(BUNDLE)+"\n\nReview it before running."
let blocks=card.aiChainBlocks(reply)
eq("one block found",[blocks.length,blocks[0].ok,blocks[0].name],[1,true,"Ping then scan"])
eq("the reply text loses the block","Here is the chain.\n\nReview it before running.",card.aiChainStripBlocks(reply))
eq("a reply with no block is untouched","Use `nmap`:\n```\nnmap -sV x\n```",card.aiChainStripBlocks("Use `nmap`:\n```\nnmap -sV x\n```"))
eq("an ordinary code block is not a chain",card.aiChainBlocks("```bash\nnmap -sV {IPv4}\n```").length,0)
eq("a json block that is not a graph is not a chain",card.aiChainBlocks(fence('{"nodes":"no","edges":1,"type":2}',"json")).length,0)
eq("a json block holding a graph counts",card.aiChainBlocks(fence(BUNDLE,"json")).length,1)
eq("an untagged block holding a graph counts",card.aiChainBlocks(fence(BUNDLE,"")).length,1)
eq("the tag is case-insensitive and may carry spaces",card.aiChainBlocks("``` LOYA-Chain \n"+BUNDLE+"\n```").length,1)
eq("CRLF replies work",card.aiChainBlocks("text\r\n```loya-chain\r\n"+BUNDLE+"\r\n```\r\n").map((b)=>b.ok),[true])
blocks=card.aiChainBlocks(fence("{broken"))
eq("a tagged block with broken JSON still gives a (broken) card",[blocks.length,blocks[0].ok],[1,false])
blocks=card.aiChainBlocks("Sure:\n```loya-chain\n"+BUNDLE.slice(0,200))
eq("a reply cut off inside the block is reported as cut off",[blocks.length,blocks[0].ok,/cut off/.test(blocks[0].error)],[1,false,true])
eq("the cut-off block is hidden from the text",card.aiChainStripBlocks("Sure:\n```loya-chain\n"+BUNDLE.slice(0,200)),"Sure:")
eq("two blocks, both found",card.aiChainBlocks(fence(BUNDLE)+"\nor\n"+fence(JSON.stringify(GRAPH))).length,2)
eq("null and undefined are fine",[card.aiChainBlocks(null).length,card.aiChainStripBlocks(undefined)],[0,""])
// ---- counts and outline
eq("counts",card.aiChainCounts(GRAPH),{nodes:5,edges:5,commands:3,scripts:0,approvals:0})
eq("counts of rubbish",card.aiChainCounts({nodes:"x",edges:null}),{nodes:0,edges:0,commands:0,scripts:0,approvals:0})
const rows=card.aiChainOutline(GRAPH)
eq("outline: one row per node, in run order",rows.map((r)=>r.id),["n1","n2","n3","n4","n5"])
eq("outline: command row",[rows[1].type,rows[1].title,rows[1].detail],["command","Ping the host","ping -c 2 {IPv4}"])
eq("outline: where each port leads",rows[2].next,[{port:"alive",to:"Nmap scan"},{port:"down",to:"Host is down"}])
check("outline: decision lists its branches",rows[2].detail==="branches: alive / down",rows[2].detail)
check("outline: several commands are counted",/\(\+1 more\)/.test(rows[3].detail),rows[3].detail)
check("outline: output row",rows[4].detail==="notify: Host did not answer",rows[4].detail)
const shuffled={nodes:[GRAPH.nodes[4],GRAPH.nodes[2],GRAPH.nodes[0],GRAPH.nodes[3],GRAPH.nodes[1]],edges:GRAPH.edges}
eq("outline: order follows the edges, not the file",card.aiChainOutline(shuffled).map((r)=>r.id),["n1","n2","n3","n4","n5"])
const loop={nodes:[{id:"a",type:"start"},{id:"b",type:"wait",config:{seconds:3}},{id:"c",type:"comment",config:{text:"note"}}],edges:[{from:"a",port:"out",to:"b"},{from:"b",port:"out",to:"a"},{from:"b",port:"out",to:"ghost"}]}
const loopRows=card.aiChainOutline(loop)
eq("outline: cycles end, unreachable nodes are still listed",loopRows.map((r)=>r.id),["a","b","c"])
check("outline: an edge to a missing node says so",loopRows[1].next.some((o)=>/missing node ghost/.test(o.to)))
const many={nodes:Array.from({length:60},(_,i)=>({id:"n"+i,type:i?"wait":"start"})),edges:[]}
eq("outline: long diagrams are cut with a count",[card.aiChainOutline(many).length,card.aiChainOutline(many)[40].more],[41,20])
const details=(type,config)=>card.aiChainNodeDetail({type:type,config:config})
check("detail: script",details("script",{language:"bash",code:"a\n\nb\n",network:true})==="bash script, 2 lines, network on",details("script",{language:"bash",code:"a\n\nb\n",network:true}))
eq("detail: parse / set / foreach / wait / approval / subchain / end",[details("parse",{mode:"tool",tool:"nmap"}),details("set",{assign:[{var:"a"},{var:"b"}]}),details("foreach",{items:"${scan.open_ports}"}),details("wait",{seconds:5}),details("approval",{message:"Go?"}),details("subchain",{playbook_id:7}),details("end",{status:"fail"})],["read nmap output","set a, b","for each of ${scan.open_ports}","wait 5 s","asks: Go?","runs chain #7","ends the run (fail)"])
eq("detail: a node with no config does not throw",[details("command"),details("decision",null),details("nope",{})],["(no command)","branches: else",""])
// ---- escaping: everything in the graph came from a model
const EVIL='<img src=x onerror="alert(1)">'
const QUOTE='" onmouseover="alert(2)" x=\''
const hostile={nodes:[
{id:"n1",type:"start",title:EVIL,config:{}},
{id:'n2"><script>alert(3)</script>',type:"command",title:QUOTE,config:{commands:[{text:"echo </li><script>alert(4)</script>"}]}},
{id:"n3",type:'<b onclick="x()">',title:{toString:()=>"<svg onload=alert(5)>"},config:{branches:[{name:"<i>"}],else:"<u>"}},
{id:"n4",type:"output",title:"ok",config:{action:"<script>",title:"</span><iframe src=javascript:alert(6)>"}}],
edges:[{from:"n1",port:'<img src=x onerror=alert(7)>',to:'n2"><script>alert(3)</script>'},{from:"n1",port:"out",to:"<h1>"}]}
const hostileHtml=card.aiChainCardHtml({name:EVIL+QUOTE,graph:hostile,state:"checked",errors:[{message:EVIL},{message:"</ul><script>alert(8)</script>"}],warnings:[QUOTE,{message:{evil:1}}],tool:"chain_create"})
check("card: no tag from model text survives",!/<(img|script|svg|iframe|b |i>|u>|h1)/i.test(hostileHtml),hostileHtml.match(/<(img|script|svg|iframe|b |i>|u>|h1)[^>]*>/i)+"")
check("card: only the tags the card itself writes",(hostileHtml.match(/<\/?([a-z0-9]+)/gi)||[]).every((t)=>/^<\/?(div|span|i|ol|ul|li|b|button)$/i.test(t)),[...new Set(hostileHtml.match(/<\/?([a-z0-9]+)/gi))].join(" "))
check("card: quotes cannot open an attribute",!/"\s+on[a-z]+=/i.test(hostileHtml)&&!/onmouseover="/.test(hostileHtml))
check("card: the hostile text is shown as text",hostileHtml.includes("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;"))
check("card: every attribute is one of the card's own",(hostileHtml.match(/\s([a-z-]+)="/g)||[]).every((a)=>/^\s(class|type|data-act)="$/.test(a)),[...new Set(hostileHtml.match(/\s([a-z-]+)="/g))].join(" "))
check("card: class names take letters only",(hostileHtml.match(/class="([^"]*)"/g)||[]).every((c)=>/^class="[a-z0-9 -]*"$/.test(c)))
check("card: no tag carries a url, style or handler attribute",!/<[^>]*\s(href|src|style|on[a-z]+)=/i.test(hostileHtml))
const brokenHtml=card.aiChainCardHtml({state:"broken",raw:EVIL,error:"Unexpected token "+EVIL,name:EVIL})
check("broken card: escaped, offers the fix and copy buttons, no open button",!/<img/.test(brokenHtml)&&/data-act="fix"/.test(brokenHtml)&&/data-act="copy"/.test(brokenHtml)&&!/data-act="open"/.test(brokenHtml))
eq("text: control and bidi characters are flattened","a b c",card.aiChainText("a\u0000\n\tb\u202e\u2066 c"))
eq("text: objects never print",[card.aiChainText({a:1}),card.aiChainText(["x"]),card.aiChainText(null),card.aiChainText(12)],["","","","12"])
check("text: long values are cut",card.aiChainText("x".repeat(500),50).length===50)
eq("esc",card.aiChainEsc(`<a href="x" onclick='y'>&</a>`),"&lt;a href=&quot;x&quot; onclick=&#39;y&#39;&gt;&amp;&lt;/a&gt;")
// ---- the card itself
const okHtml=card.aiChainCardHtml({name:"Ping then scan",graph:GRAPH,state:"checked",errors:[],warnings:[{message:"Nmap scan: nothing is connected to 'fail'."}]})
check("card: name and the AI-made flag",okHtml.includes("Ping then scan")&&okHtml.includes("AI-made - review before running"))
check("card: counts",okHtml.includes("5 nodes \u00b7 5 connections \u00b7 3 commands"),okHtml.slice(0,400))
eq("card: one outline row per node",(okHtml.match(/<li><span class="ai-chain-type/g)||[]).length,5)
check("card: warnings listed",/1 warning/.test(okHtml)&&okHtml.includes("nothing is connected to &#39;fail&#39;"))
check("card: open + copy, no fix button when valid",/data-act="open"/.test(okHtml)&&/data-act="copy"/.test(okHtml)&&!/data-act="fix"/.test(okHtml))
check("card: says it will not run by itself",/runs only after you confirm/.test(okHtml))
const badHtml=card.aiChainCardHtml({name:"x",graph:GRAPH,state:"checked",errors:[{message:"Ping: unknown port 'ok'."}],warnings:[]})
check("card: errors listed with the fix button, and no open button",/1 error/.test(badHtml)&&badHtml.includes("unknown port &#39;ok&#39;")&&/data-act="fix"/.test(badHtml)&&!/data-act="open"/.test(badHtml)&&/data-act="copy"/.test(badHtml))
check("card: checking state",/Checking the diagram/.test(card.aiChainCardHtml({name:"x",graph:GRAPH,state:"checking"})))
const storedHtml=card.aiChainCardHtml({name:"Made by a tool",graph:GRAPH,state:"stored",stored:true,playbookId:7,tool:"chain_update",errors:[{message:"e"}]})
check("stored card: says the AI changed it; no fix button (the chain is already saved)",/changed by the AI/.test(storedHtml)&&!/data-act="fix"/.test(storedHtml)&&/data-act="open"/.test(storedHtml))
check("stored card: a reviewed chain loses the flag",!card.aiChainCardHtml({name:"x",graph:GRAPH,state:"stored",stored:true,reviewed:true}).includes("AI-made"))
check("unknown card: points at the Chains page",/data-act="chains"/.test(card.aiChainCardHtml({state:"unknown"})))
eq("issue texts are capped",card.aiChainIssueTexts(Array.from({length:12},(_,i)=>({message:"m"+i})),3),["m0","m1","m2","and 9 more"])
eq("copy JSON is the bundle",JSON.parse(card.aiChainJson({name:"N",graph:GRAPH})).name,"N")
eq("copy JSON of a broken block is its raw text",card.aiChainJson({raw:"{oops"}),"{oops")
// ---- prompts
const fix=card.aiChainFixPrompt({errors:[{message:"No start node."},{message:"Ping: unknown port."}]},"")
check("fix prompt lists the errors and asks for the whole diagram again",fix.includes("- No start node.")&&fix.includes("- Ping: unknown port.")&&fix.includes("loya-chain")&&/COMPLETE/.test(fix))
check("fix prompt carries the guide when asked",card.aiChainFixPrompt({error:"bad json"},"GUIDE TEXT").startsWith("GUIDE TEXT\n\n")&&card.aiChainFixPrompt({error:"bad json"},"").includes("- bad json"))
eq("chat prompt = guide + request",card.aiChainChatPrompt("GUIDE","  ping it  "),"GUIDE\n\nWHAT THE CHAIN SHOULD DO\nping it")
;["create a chain that pings the target, and if it is alive runs an nmap scan, otherwise notifies me","Make me an attack flow for SMB","please build a new chain diagram: ping then scan","Could you draw a workflow that enumerates web ports","generate an action chain for AD recon"].forEach((t)=>check("intent: "+t.slice(0,40),card.aiChainIntent(t)))
;["how do chains work?","explain what a chain diagram is","/newchain ping it","create a note about chains","run the recon chain","what does this command do: make chain","delete the chain called x",""].forEach((t)=>check("not an intent: "+(t||"(empty)").slice(0,40),!card.aiChainIntent(t)))
// ---- tool calls
eq("tool result: chain_create",card.aiChainToolResult({role:"tool",tool_name:"chain_create",content:'{"playbook_id": 12, "errors": [], "warnings": []}'}),{tool:"chain_create",playbookId:12})
eq("tool result: chain_update",card.aiChainToolResult({role:"tool",tool_name:"chain_update",content:'{"ok":true,"playbook_id":3}'}),{tool:"chain_update",playbookId:3})
eq("tool result: a refused call gives no card",card.aiChainToolResult({role:"tool",tool_name:"chain_create",content:"Error: AI Roles denies Chain Diagrams > Add."}),null)
eq("tool result: other tools are ignored",card.aiChainToolResult({role:"tool",tool_name:"chain_run",content:'{"playbook_id":1}'}),null)
eq("tool result: a hostile id is ignored",[card.aiChainToolResult({role:"tool",tool_name:"chain_create",content:'{"playbook_id":"1; DROP"}'}),card.aiChainToolResult({role:"tool",tool_name:"chain_create",content:'{"playbook_id":-4}'}),card.aiChainToolResult({role:"tool",tool_name:"chain_create",content:"not json"})],[null,null,null])
check("agent turn that used chain_create is noticed",card.aiChainAgentTouched({role:"assistant",content:"done",agent_tools:["notes_list","chain_create"]})&&!card.aiChainAgentTouched({role:"assistant",agent_tools:["chain_get","chains_list"]})&&!card.aiChainAgentTouched({role:"user"}))
const before=[{playbook_id:1,ai_made:false,updated_at:"a"},{playbook_id:2,ai_made:true,updated_at:"b"},{playbook_id:3,ai_made:true,updated_at:"c"}]
const after=[{playbook_id:1,ai_made:false,updated_at:"a2"},{playbook_id:2,ai_made:true,updated_at:"b"},{playbook_id:3,ai_made:true,updated_at:"c2"},{playbook_id:4,ai_made:true,updated_at:"d"},{playbook_id:5,ai_made:false,updated_at:"e"}]
eq("list diff: new and changed AI-made chains only",card.aiChainListDiff(before,after),[3,4])
eq("list diff: rubbish in, nothing out",card.aiChainListDiff(null,"x"),[])
// ---- the DOM side, in a small fake document: validation, the buttons, storing the draft
function fakeElement(){
const el={className:"",children:[],_html:"",buttons:[],disabled:false,
appendChild(c){this.children.push(c);return c},
querySelectorAll(sel){return sel==="[data-act]"?this.buttons:[]}}
Object.defineProperty(el,"innerHTML",{get(){return this._html},set(v){
this._html=String(v);this.children=[]
this.buttons=[...this._html.matchAll(/<button[^>]*data-act="([a-z]+)"/g)].map((m)=>({dataset:{act:m[1]},disabled:false,handlers:[],addEventListener(_t,fn){this.handlers.push(fn)},click(){this.handlers.forEach((fn)=>fn())}}))
}})
return el
}
function sandbox(extra){
const calls=[],toasts=[],events=[],sent=[],copied=[]
const ctx=Object.assign({console:console,Promise:Promise,JSON:JSON,Map:Map,Set:Set,
document:{createElement:fakeElement,dispatchEvent:(e)=>{events.push(e);return true}},
CustomEvent:function(type,init){this.type=type;this.detail=init&&init.detail},
navigator:{clipboard:{writeText:(t)=>{copied.push(t);return Promise.resolve()}}},
showToast:(m,t)=>toasts.push([m,t||""]),showStatusIsland:(m,t)=>toasts.push([m,t||""]),
aiState:{sessionId:"s1",selectedKind:"ollama",currentModel:"llama3",chatHistory:[],sending:false,chainCache:{at:1,list:[]}},
aiSendPrompt:(prompt,shown,att)=>{sent.push({prompt:prompt,shown:shown,att:att});return Promise.resolve("")},
bridgeCall:(p,a)=>{calls.push([p,a]);const fn=(extra&&extra.bridge&&extra.bridge[p]);return fn?Promise.resolve().then(()=>fn.apply(null,a||[])):Promise.reject(new Error("no "+p))}
},(extra&&extra.globals)||{})
vm.createContext(ctx)
vm.runInContext(fs.readFileSync(FILE,"utf8")+"\n;globalThis.__api={aiChainTurnCards,aiChainRequest,aiChainWatchStart,aiChainCache}",ctx)
return {ctx:ctx,api:ctx.__api,calls:calls,toasts:toasts,events:events,sent:sent,copied:copied}
}
const tick=()=>new Promise((r)=>setTimeout(r,5))
const button=(el,act)=>el.buttons.find((b)=>b.dataset.act===act)
async function domTests(){
// A valid block: validated once, opened through the bridge as an AI-made draft, stored once.
let opened=[]
let box=sandbox({bridge:{"flows.validate":(g)=>({ok:true,errors:[],warnings:[],graph:g}),"flows.create_ai_draft":(name)=>({playbook_id:41,errors:[],warnings:[],name:name})},globals:{loyaOpenChainDiagram:(id)=>{opened.push(id)}}})
const turn={role:"assistant",content:"Here:\n"+fence(BUNDLE)}
let cards=box.api.aiChainTurnCards(turn,1)
eq("dom: one card for the reply",cards.length,1)
check("dom: it starts as checking",/Checking the diagram/.test(cards[0].innerHTML))
await tick()
check("dom: after flows.validate it is a valid card",/The diagram is valid/.test(cards[0].innerHTML)&&cards[0].className==="ai-chain-card",cards[0].className)
eq("dom: validate was asked once",box.calls.filter((c)=>c[0]==="flows.validate").length,1)
const again=box.api.aiChainTurnCards(turn,1)
check("dom: a re-render uses the cached check",/The diagram is valid/.test(again[0].innerHTML)&&box.calls.filter((c)=>c[0]==="flows.validate").length===1)
button(again[0],"open").click()
await tick()
const draft=box.calls.find((c)=>c[0]==="flows.create_ai_draft")
check("dom: open stores the draft through flows.create_ai_draft",!!draft&&draft[1][0]==="Ping then scan"&&draft[1][1].nodes.length===5&&draft[1][2]==="llama3",JSON.stringify(draft&&[draft[1][0],draft[1][2]]))
eq("dom: then opens it in the diagram editor",opened,[41])
check("dom: the Chains list is told",box.events.some((e)=>e.type==="loya:chains-changed"&&e.detail.ids[0]===41)&&box.ctx.aiState.chainCache===null)
button(again[0],"open").click()
await tick()
eq("dom: a second click does not store it twice",[box.calls.filter((c)=>c[0]==="flows.create_ai_draft").length,opened],[1,[41,41]])
check("dom: nothing ever asks to run",!box.calls.some((c)=>/run|plan|approve/.test(c[0])),box.calls.map((c)=>c[0]).join(","))
button(again[0],"copy").click()
await tick()
eq("dom: copy JSON",JSON.parse(box.copied[0]).name,"Ping then scan")
// Storing wins even when the diagram page offers its unsaved-draft entry point: only a stored draft carries the AI-made mark.
let drafts=[]
opened=[]
box=sandbox({bridge:{"flows.validate":(g)=>({ok:true,errors:[],warnings:[],graph:g}),"flows.create_ai_draft":()=>({playbook_id:8})},globals:{loyaOpenChainDraft:(d)=>{drafts.push(d);return true},loyaOpenChainDiagram:(id)=>{opened.push(id)}}})
cards=box.api.aiChainTurnCards(turn,1)
await tick()
button(cards[0],"open").click()
await tick()
eq("dom: with both available the draft is stored as AI-made and opened by id",[opened,drafts.length],[[8],0])
// Storing is not possible (an older backend): the diagram page takes it as an unsaved draft, flagged AI-made.
box=sandbox({bridge:{"flows.validate":(g)=>({ok:true,errors:[],warnings:[],graph:g})},globals:{loyaOpenChainDraft:(d)=>{drafts.push(d);return true}}})
cards=box.api.aiChainTurnCards(turn,1)
await tick()
button(cards[0],"open").click()
await tick()
check("dom: loyaOpenChainDraft gets {name,graph,ai_made:true}",drafts.length===1&&drafts[0].name==="Ping then scan"&&drafts[0].ai_made===true&&drafts[0].graph.nodes.length===5&&drafts[0].source==="ai-panel")
check("dom: no toast about a failure",!box.toasts.some((t)=>t[1]==="error"),JSON.stringify(box.toasts))
box=sandbox({bridge:{"flows.validate":(g)=>({ok:true,errors:[],warnings:[],graph:g})}})
cards=box.api.aiChainTurnCards(turn,1)
await tick()
button(cards[0],"open").click()
await tick()
check("dom: neither way available -> an error toast, nothing opened",box.toasts.some((t)=>t[1]==="error"))
// An invalid diagram: errors shown, "Ask the AI to fix it" re-sends them (with the guide when the chat has none).
box=sandbox({bridge:{"flows.validate":(g)=>({ok:false,errors:[{code:"unknown_port",message:"Ping the host: there is no port 'ok'."}],warnings:[],graph:g}),"flows.ai_guide":()=>({fence:"loya-chain",guide:"THE GUIDE"})}})
cards=box.api.aiChainTurnCards(turn,1)
await tick()
check("dom: invalid card, not openable",cards[0].className.includes("ai-chain-card-invalid")&&/there is no port/.test(cards[0].innerHTML)&&!button(cards[0],"open"))
button(cards[0],"fix").click()
await tick()
check("dom: fix sends the errors and the guide",box.sent.length===1&&box.sent[0].prompt.startsWith("THE GUIDE")&&box.sent[0].prompt.includes("there is no port 'ok'")&&/1 error/.test(box.sent[0].shown),JSON.stringify(box.sent[0]&&box.sent[0].shown))
box.ctx.aiState.chatHistory=[{role:"user",content:"guide ```loya-chain {..} ```",display:"/newchain x"}]
button(cards[0],"fix").click()
await tick()
check("dom: the guide is not repeated when the chat already has it",box.sent.length===2&&!box.sent[1].prompt.includes("THE GUIDE"))
box.ctx.aiState.sending=true
button(cards[0],"fix").click()
await tick()
eq("dom: no fix while a reply is in progress",box.sent.length,2)
// The check itself failing (bridge error) still leaves a usable card and is retried on the next render.
box=sandbox({bridge:{"flows.validate":()=>{throw new Error("locked")}}})
cards=box.api.aiChainTurnCards(turn,1)
await tick()
check("dom: a failed check is reported on the card",/could not be checked: locked/.test(cards[0].innerHTML)&&!!button(cards[0],"open"))
box.api.aiChainTurnCards(turn,1)
await tick()
eq("dom: and retried on the next render",box.calls.filter((c)=>c[0]==="flows.validate").length,2)
// Broken JSON: no validation call, fix button only.
box=sandbox({bridge:{"flows.ai_guide":()=>({guide:"G"})}})
cards=box.api.aiChainTurnCards({role:"assistant",content:fence("{not json")},0)
await tick()
check("dom: broken JSON gives a broken card without asking the backend",cards.length===1&&!!button(cards[0],"fix")&&!button(cards[0],"open")&&!box.calls.length)
// Path B, in-app chat: a successful chain_create tool turn becomes a stored-chain card.
opened=[]
box=sandbox({bridge:{"flows.get":(id)=>({playbook_id:id,name:"Made <b>by</b> tool",graph:GRAPH,ai_made:true,ai_reviewed:false,errors:[],warnings:[]})},globals:{loyaOpenChainDiagram:(id)=>{opened.push(id)}}})
cards=box.api.aiChainTurnCards({role:"tool",tool_name:"chain_create",tool_call_id:"c1",content:'{"playbook_id":12,"errors":[],"warnings":[]}'},3)
await tick()
check("dom: tool card shows the stored chain, escaped, with the flag",cards.length===1&&cards[0].innerHTML.includes("Made &lt;b&gt;by&lt;/b&gt; tool")&&cards[0].innerHTML.includes("AI-made - review before running")&&/created by the AI/.test(cards[0].innerHTML))
button(cards[0],"open").click()
await tick()
eq("dom: its open button opens that chain; nothing new is stored",[opened,box.calls.some((c)=>c[0]==="flows.create_ai_draft")],[[12],false])
eq("dom: an error tool turn gives no card",box.api.aiChainTurnCards({role:"tool",tool_name:"chain_create",content:"Error: denied"},4).length,0)
eq("dom: user turns give no card",box.api.aiChainTurnCards({role:"user",content:fence(BUNDLE)},0).length,0)
// A chain the tool result names but that is gone.
box=sandbox({bridge:{"flows.get":()=>{throw new Error("Action chain not found.")}}})
cards=box.api.aiChainTurnCards({role:"tool",tool_name:"chain_update",content:'{"playbook_id":5}'},1)
await tick()
check("dom: a deleted chain says so and has no open button",/Action chain not found/.test(cards[0].innerHTML)&&!button(cards[0],"open"))
// Path B, external agent: only tool names reach the panel, so the chains are compared before/after the turn.
let listing=before
box=sandbox({bridge:{"flows.list":()=>listing,"flows.get":(id)=>({playbook_id:id,name:"Agent chain "+id,graph:GRAPH,ai_made:true,ai_reviewed:false,errors:[],warnings:[]})},globals:{extIsAgentKind:(k)=>String(k).startsWith("ext:")}})
box.ctx.aiState.selectedKind="ext:claude"
box.api.aiChainWatchStart()
await tick()
listing=after
const agentTurn={role:"assistant",content:"I made the chain.",agent_tools:["chain_create"]}
box.ctx.aiState.chatHistory=[{role:"user",content:"make it"},agentTurn]
cards=box.api.aiChainTurnCards(agentTurn,1)
await tick();await tick()
const holder=cards[0]
check("dom: agent turn -> a card per chain it made or changed",cards.length===1&&holder.children.length===2&&holder.children[0].innerHTML.includes("Agent chain 3")&&holder.children[1].innerHTML.includes("Agent chain 4"),holder.children.map((c)=>c.innerHTML.slice(0,90)).join(" | "))
check("dom: and a toast",box.toasts.some((t)=>/review them before running/.test(t[0])))
const lists=box.calls.filter((c)=>c[0]==="flows.list").length
box.api.aiChainTurnCards(agentTurn,1)
await tick()
eq("dom: re-rendering does not list again",box.calls.filter((c)=>c[0]==="flows.list").length,lists)
box=sandbox({bridge:{},globals:{extIsAgentKind:()=>true,loyaOpenChain:()=>{}}})
box.ctx.aiState.chatHistory=[agentTurn]
cards=box.api.aiChainTurnCards(agentTurn,0)
check("dom: an old agent turn (no snapshot) points at the Chains page",/data-act="chains"/.test(cards[0].children[0].innerHTML)&&!box.calls.length)
box=sandbox({bridge:{"flows.list":()=>[]}})
box.api.aiChainWatchStart()
eq("dom: no snapshot for an ordinary chat provider",box.calls.length,0)
// /newchain: the request goes out with the guide; the user sees only what they typed.
box=sandbox({bridge:{"flows.ai_guide":()=>({fence:"loya-chain",guide:"GUIDE TEXT"})}})
await box.api.aiChainRequest("ping the target, then nmap","/newchain ping the target, then nmap",[])
eq("dom: /newchain sends guide + request, shows the command",[box.sent[0].prompt,box.sent[0].shown],["GUIDE TEXT\n\nWHAT THE CHAIN SHOULD DO\nping the target, then nmap","/newchain ping the target, then nmap"])
await box.api.aiChainRequest("again","/newchain again",[])
eq("dom: the guide is fetched once",box.calls.filter((c)=>c[0]==="flows.ai_guide").length,1)
box=sandbox({bridge:{}})
await box.api.aiChainRequest("x","/newchain x",[])
check("dom: no guide -> an error, nothing sent",box.sent.length===0&&box.toasts.length===1)
// A diagram whose nodes all sit on one spot is laid out before it is opened (when the editor's model is loaded).
let laid=0
box=sandbox({bridge:{"flows.validate":(g)=>({ok:true,errors:[],warnings:[],graph:g}),"flows.create_ai_draft":()=>({playbook_id:2})},globals:{loyaOpenChain:()=>{},flowAutoLayout:(g)=>{laid++;g.nodes.forEach((n,i)=>{n.x=i*260});return g}}})
const flat=JSON.parse(JSON.stringify(GRAPH));flat.nodes.forEach((n)=>{delete n.x;delete n.y})
cards=box.api.aiChainTurnCards({role:"assistant",content:fence(JSON.stringify({name:"Flat",graph:flat}))},0)
await tick()
button(cards[0],"open").click()
await tick()
const sentGraph=box.calls.find((c)=>c[0]==="flows.create_ai_draft")[1][1]
check("dom: stacked nodes are auto-laid-out once",laid===1&&sentGraph.nodes[4].x===1040)
}
// ---- wiring in the real files
const aiSource=fs.readFileSync(path.join(ROOT,"UI","js","components","ai.js"),"utf8")
const mainHtml=fs.readFileSync(path.join(ROOT,"UI","windows","main.html"),"utf8")
check("wiring: /newchain is a built-in slash command that needs an argument",/\{name:"newchain",args:"<what it should do>",desc:"[^"]+",needsArg:true\}/.test(aiSource))
check("wiring: /newchain goes through aiChainRequest",/if\(name==="newchain"\)\{[\s\S]{0,200}aiChainRequest\(arg,"\/newchain "\+arg,aiTakeAttachments\(\)\)/.test(aiSource))
check("wiring: a plain request is recognised for chat providers only",/aiChainIntent\(text\)&&!\(typeof extIsAgentKind==="function"&&extIsAgentKind\(aiState\.selectedKind\)\)/.test(aiSource))
check("wiring: replies are shown without the raw block",/turn\.role==="assistant"&&typeof aiChainStripBlocks==="function"\?aiChainStripBlocks\(turn\.content\):turn\.content/.test(aiSource))
eq("wiring: cards are appended for tool turns, block-only replies and normal replies",(aiSource.match(/aiChainAppendCards\(wrap,turn,i\)/g)||[]).length-(aiSource.match(/function aiChainAppendCards\(wrap,turn,i\)/g)||[]).length,3)
check("wiring: the agent snapshot starts with the turn",/function aiRunChatTurn\([^)]*\)\{\nif\(typeof aiChainWatchStart==="function"\)aiChainWatchStart\(\)/.test(aiSource))
check("wiring: 'To terminal' never stages chain JSON",/aiExtractCommand\(typeof aiChainStripBlocks==="function"\?aiChainStripBlocks\(text\):text\)/.test(aiSource))
check("wiring: ai-chain-card.js loads right after ai.js",/<script src="\.\.\/js\/components\/ai\.js"><\/script>\r?\n<script src="\.\.\/js\/components\/ai-chain-card\.js"><\/script>/.test(mainHtml))
const cardSource=fs.readFileSync(FILE,"utf8")
check("source: no eval, no Function, no inline handlers, ASCII only",!/\beval\(|new Function|\son[a-z]+=/.test(cardSource)&&!/[^\x00-\x7f]/.test(cardSource))
check("source: LF line endings",!cardSource.includes("\r"))
check("source: the only innerHTML writes are the card renderer's",(cardSource.match(/\.innerHTML=/g)||[]).every(()=>true)&&(cardSource.match(/\.innerHTML=(?!aiChainCardHtml\(model\)|"")/g)||[]).length===0,(cardSource.match(/\.innerHTML=.{0,30}/g)||[]).join(" | "))
check("css: the card is styled in ai.css with theme variables only",(()=>{const css=fs.readFileSync(path.join(ROOT,"UI","css","ai.css"),"utf8");const part=css.slice(css.indexOf(".ai-chain-cards{"));return part.length>200&&!/#[0-9a-f]{3,8}\b|rgba?\(/i.test(part)})())
domTests().then(()=>{
console.log("ai_chain_card: "+passed+" passed, "+failed+" failed")
process.exit(failed?1:0)
}).catch((err)=>{console.error(err);process.exit(1)})
