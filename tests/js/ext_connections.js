// Settings > AI (Roles / Agents) layout and the Connections card's pure helpers (UI/js/components/ext-connections.js).
const fs=require("fs")
const path=require("path")
const ROOT=path.resolve(__dirname,"..","..")
const source=fs.readFileSync(path.join(ROOT,"UI","js","components","ext-connections.js"),"utf8")
const start=source.indexOf("// ---- conn pure start")
const end=source.indexOf("// ---- conn pure end")
if(start<0||end<start)throw new Error("could not find the pure helpers in ext-connections.js")
const api=new Function(source.slice(start,end)+"\nreturn {CONN_TOOLS,CONN_STEPS,connSigninPill,connLinkPill,connPickShell,connStepsText,connCommandFor,connPickMethod,connStepDone,connResumeIndex,connResumeStart,connRunWizard}")()
const html=fs.readFileSync(path.join(ROOT,"UI","pages","settings.html"),"utf8")
const settingsJs=fs.readFileSync(path.join(ROOT,"UI","js","pages","settings.js"),"utf8")
const mainHtml=fs.readFileSync(path.join(ROOT,"UI","windows","main.html"),"utf8")
let passed=0,failed=0
function check(name,cond,detail){if(cond){passed++;return}failed++;console.log("  FAIL  "+name+(detail?"  ->  "+detail:""))}
function eq(name,a,b){check(name,JSON.stringify(a)===JSON.stringify(b),JSON.stringify(a)+" != "+JSON.stringify(b))}
// pills
eq("not installed",api.connSigninPill({installed:false}),{text:"Not installed",cls:"not_installed"})
eq("signed in",api.connSigninPill({installed:true,signin:{state:"signed_in"}}).text,"Signed in")
eq("signed out",api.connSigninPill({installed:true,signin:{state:"signed_out"}}).cls,"offline")
eq("unknown",api.connSigninPill({installed:true,signin:{state:"unknown"}}).text,"Sign-in unknown")
eq("link pill",[api.connLinkPill({connected:false}).text,api.connLinkPill({connected:true}).cls],["Not connected","online"])
// shell for the sign-in tab: native shells only, never WSL
eq("linux login shell",api.connPickShell([{id:"zsh"},{id:"shell"}],"linux"),"shell")
eq("windows prefers pwsh",api.connPickShell([{id:"cmd"},{id:"powershell"},{id:"pwsh"},{id:"wsl:kali-linux"}],"windows"),"pwsh")
eq("windows falls back to cmd",api.connPickShell([{id:"wsl:kali-linux"},{id:"cmd"}],"windows"),"cmd")
eq("only WSL: none (OS terminal is used)",api.connPickShell([{id:"wsl:kali-linux"}],"windows"),"")
eq("nothing",api.connPickShell([],"linux"),"")
eq("steps text",api.connStepsText([{name:"CLI found",ok:true,detail:"/x"},{name:"Bridge",ok:false}]),"OK  CLI found - /x\nNO  Bridge")
eq("tools",api.CONN_TOOLS,["claude_code","codex_cli"])
// Settings layout: "AI" tab with Roles / Agents; agents config moved out of Extensions
check("tab renamed to AI",/data-tab="ai">AI<\/button>/.test(html)&&!/data-tab="airoles"/.test(html))
const panel=html.slice(html.indexOf('data-tab-panel="ai"'),html.indexOf('data-tab-panel="cve"'))
check("Roles and Agents sub-tabs",/data-ai-tab="roles">Roles</.test(panel)&&/data-ai-tab="agents">Agents</.test(panel))
const roles=panel.slice(panel.indexOf('data-ai-panel="roles"'),panel.indexOf('data-ai-panel="agents"'))
const agents=panel.slice(panel.indexOf('data-ai-panel="agents"'))
check("AI Roles content under Roles",roles.includes('id="setAiRolesRoot"')&&roles.includes('id="setAiTerminalApproval"'))
check("agents and connections under Agents",agents.includes('id="setExtAgentsRoot"')&&agents.includes('id="setExtConnectionsRoot"'))
const extensions=html.slice(html.indexOf('data-tab-panel="extensions"'),html.indexOf('data-tab-panel="ai"'))
check("Extensions only links to AI > Agents",!extensions.includes("setExtAgentsRoot")&&/data-goto-ai="agents"/.test(extensions))
check("old tab id still opens the AI tab",/if\(tab==="airoles"\)tab="ai"/.test(settingsJs))
check("connections script loaded after ext-agents",mainHtml.indexOf("ext-connections.js")>mainHtml.indexOf("ext-agents.js"))
// Policy: the Connections card never offers a claude.ai login inside LOYA; it runs the CLI's own sign-in.
check("no in-app claude.ai login",!/claude\.ai\/login|oauth\/authorize/i.test(source))
check("says AI Roles still gate",/AI Roles still decide every tool call/.test(source))
// ---- setup assistant: per-OS command shown, method choice
eq("posix command",api.connCommandFor({commands:{posix:"curl -fsSL https://claude.ai/install.sh | bash"}},"posix"),"curl -fsSL https://claude.ai/install.sh | bash")
eq("windows prefers PowerShell",api.connCommandFor({commands:{ps:"irm https://claude.ai/install.ps1 | iex",cmd:"curl x"}},"ps"),"irm https://claude.ai/install.ps1 | iex")
eq("cmd line when asked",api.connCommandFor({commands:{ps:"a",cmd:"b"}},"cmd"),"b")
eq("first ready method",api.connPickMethod([{id:"native",auto:false},{id:"npm",auto:true}]),"npm")
eq("no ready method",api.connPickMethod([{id:"native",auto:false}]),"")
eq("step ids",api.CONN_STEPS.map((s)=>s.id),["prereq","install","verify","signin","connect","test"])
// ---- resume from the state the CLI is in
const NOT={installed:false},INST={installed:true,signin:{state:"signed_out"}},SIGNED={installed:true,signin:{state:"signed_in"}},CONN={installed:true,signin:{state:"signed_in"},connected:true}
eq("resume: not installed -> prerequisites",api.connResumeIndex(NOT),0)
eq("resume: installed -> sign in",api.connResumeIndex(INST),3)
eq("resume: signed in -> connect",api.connResumeIndex(SIGNED),4)
eq("resume: connected -> test",api.connResumeIndex(CONN),5)
eq("installed but signed out: connect not done",api.connStepDone("connect",INST),false)
eq("reopen at the step reached",api.connResumeStart(NOT,1),1)
eq("reopen at verify while the installer runs",api.connResumeStart(NOT,2),2)
eq("never past verify without the CLI",api.connResumeStart(NOT,4),2)
eq("state ahead of the last step wins",api.connResumeStart(SIGNED,1),4)
eq("installed: reopen at connect",api.connResumeStart(INST,4),4)
eq("first open",api.connResumeStart(INST,undefined),3)
// ---- the flow: a scripted ask() and recording actions
function harness(states,answers){
const log={asked:[],ran:[]}
let si=0
const o={start:0,status:()=>Promise.resolve(states[Math.min(si,states.length-1)]),
ask:(v)=>{log.asked.push(v.step.id+(v.done?":done":""));return Promise.resolve(answers.length?answers.shift():"cancel")},
act:{}}
for(const s of api.CONN_STEPS)o.act[s.id]=(st)=>{log.ran.push(s.id);si++;return s.id==="test"?{ok:true}:null}
return {o,log}
}
const run=(h)=>api.connRunWizard(h.o)
const tests=[]
// Cancel at each step: nothing at or after that step runs.
for(let k=0;k<6;k++){
tests.push((async()=>{
const h=harness([NOT,NOT,NOT,INST,SIGNED,CONN],Array(k).fill("approve").concat(["cancel"]))
const r=await run(h)
eq("cancel at step "+(k+1)+" stops there",[r.cancelled,r.index],[true,k])
eq("cancel at step "+(k+1)+": only approved steps ran",h.log.ran,api.CONN_STEPS.slice(0,k).map((s)=>s.id))
})())
}
// Approve everything: each step asked once, in order, each run after its own approval.
tests.push((async()=>{
const h=harness([NOT,NOT,NOT,INST,SIGNED,CONN],Array(6).fill("approve"))
const r=await run(h)
eq("all approved: done",r.done,true)
eq("all approved: asked in order",h.log.asked,["prereq","install","verify","signin","connect","test"])
eq("all approved: ran in order",h.log.ran,["prereq","install","verify","signin","connect","test"])
})())
// Anything other than "approve" (Esc, closing) counts as Cancel.
tests.push((async()=>{
const h=harness([NOT],[undefined])
const r=await run(h)
eq("Esc/close is a cancel",[r.cancelled,h.log.ran.length],[true,0])
})())
// Already-done steps are shown as done and run nothing on Continue.
tests.push((async()=>{
const h=harness([SIGNED],["approve","approve","approve","approve","cancel"])
h.o.start=0
const r=await run(h)
eq("done steps say so",h.log.asked.slice(0,4),["prereq:done","install:done","verify:done","signin:done"])
eq("done steps run nothing",h.log.ran,[])
eq("stops at connect",r.index,4)
})())
// Resume: a later run starts where the state says, and earlier steps are not asked again.
tests.push((async()=>{
const h=harness([INST,SIGNED,CONN],["approve","approve","approve"])
h.o.start=api.connResumeIndex(INST)
const r=await run(h)
eq("resume asks from sign-in",h.log.asked,["signin","connect","test"])
eq("resume finishes",r.done,true)
})())
// Verify retries (install still running) and never moves on without the CLI.
tests.push((async()=>{
const asked=[],ran=[]
let found=false
const o={start:2,status:()=>Promise.resolve(found?INST:NOT),ask:(v)=>{asked.push(v.step.id+(v.note?"!":""));return Promise.resolve(asked.length<3?"approve":"cancel")},
act:{verify:()=>{ran.push("verify");if(ran.length===2)found=true;return found?null:{retry:true,message:"not yet"}}}}
const r=await api.connRunWizard(o)
eq("verify asked again with a note",asked,["verify","verify!","signin"])
eq("verify ran twice",ran,["verify","verify"])
eq("then cancel at sign-in",r.index,3)
})())
// Install never runs from the card without the assistant; the confirm is per step.
check("install runs only from the assistant's install action",(source.match(/connection_install_command|connection_install_os/g)||[]).length===2&&/install:\(\)=>\{/.test(source))
check("Esc handled as cancel",/confirmTrapKey\(e,box,\(\)=>answer&&answer\("cancel"\)\)/.test(source))
check("focus goes to the primary button",/\(okBtn\.disabled\?cancelBtn:okBtn\)\.focus\(\)/.test(source))
check("new UI text says LOYA NG",!/LOYA Note NG/.test(source))
Promise.all(tests).then(()=>{
console.log(`ext_connections: ${passed} passed, ${failed} failed`)
process.exit(failed?1:0)
})
