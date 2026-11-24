// Settings > AI (Roles / Agents) layout and the Connections card's pure helpers (UI/js/components/ext-connections.js).
const fs=require("fs")
const path=require("path")
const ROOT=path.resolve(__dirname,"..","..")
const source=fs.readFileSync(path.join(ROOT,"UI","js","components","ext-connections.js"),"utf8")
const start=source.indexOf("// ---- conn pure start")
const end=source.indexOf("// ---- conn pure end")
if(start<0||end<start)throw new Error("could not find the pure helpers in ext-connections.js")
const api=new Function(source.slice(start,end)+"\nreturn {CONN_TOOLS,CONN_STEPS,connSigninPill,connSigninState,connNextText,connLinkPill,connPickShell,connStepsText,connCommandFor,connPickMethod,connStepDone,connResumeIndex,connResumeStart,connRunWizard,connJobRun,connCancelToken,connIsCancel,CONN_CANCELLED,connWatchHtml,connVerifyReady,connVerifyInfo}")()
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
eq("unknown",api.connSigninPill({installed:true,signin:{state:"unknown"}}).text,"Could not check sign-in")
// "could not check" is its own state, never shown as "not signed in"
check("unknown pill differs from signed out",api.connSigninPill({installed:true,signin:{state:"unknown"}}).cls!=="offline")
eq("unknown pill explains why",api.connSigninPill({installed:true,signin:{state:"unknown",detail:"Could not check the sign-in: timed out"}}).title,"Could not check the sign-in: timed out")
eq("state words",["signed_in","signed_out","unknown",undefined,"weird"].map((x)=>api.connSigninState({signin:x===undefined?undefined:{state:x}})),["signed_in","signed_out","unknown","unknown","unknown"])
// what the card / Refresh says next comes from the reported state (Refresh used to ask to sign in even when signed in)
eq("next: signed in + connected",api.connNextText({installed:true,connected:true,signin:{state:"signed_in"}}),"Signed in and connected to LOYA NG.")
eq("next: signed in, not connected",api.connNextText({installed:true,signin:{state:"signed_in"}}),"Signed in. Next: Connect to LOYA NG.")
eq("next: signed out",api.connNextText({installed:true,signin:{state:"signed_out"}}),"Next: Sign in, then Connect to LOYA NG.")
for(const st of [{installed:true,signin:{state:"unknown"}},{installed:true,connected:true,signin:{state:"unknown",last:"signed_in"}},{installed:true,signin:{state:"signed_in"}},{installed:true,connected:true,signin:{state:"signed_in"}}]){
check("never asks to sign in unless signed out: "+JSON.stringify(st),!/Sign in/.test(api.connNextText(st)),api.connNextText(st))
}
check("unknown says it could not check",/could not be checked/.test(api.connNextText({installed:true,signin:{state:"unknown"}})))
check("unknown mentions the last good state",/signed in before/.test(api.connNextText({installed:true,connected:true,signin:{state:"unknown",last:"signed_in"}})))
check("no em/en dashes, ellipsis or middle dots in next texts",![{installed:true,signin:{state:"unknown"}},{installed:true,connected:true,signin:{state:"signed_out"}}].some((st)=>/[\u2013\u2014\u2026\u00b7]/.test(api.connNextText(st))))
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
const agents=panel.slice(panel.indexOf('data-ai-panel="agents"'),panel.indexOf('data-ai-panel="roles"'))
const roles=panel.slice(panel.indexOf('data-ai-panel="roles"'))
check("Agents is the first and default sub-tab",panel.indexOf('data-ai-tab="agents"')<panel.indexOf('data-ai-tab="roles"')&&/set-subtab active[^>]*data-ai-tab="agents"/.test(panel)&&/set-subpanel active" data-ai-panel="agents"/.test(panel)&&panel.indexOf('data-ai-panel="agents"')<panel.indexOf('data-ai-panel="roles"'))
check("Connections first, then External Agents, then AI Assistant",agents.indexOf('id="setExtConnectionsRoot"')>0&&agents.indexOf('id="setExtConnectionsRoot"')<agents.indexOf('id="setExtAgentsRoot"')&&agents.indexOf('id="setExtAgentsRoot"')<agents.indexOf('id="setAiToggle"'))
check("AI sub-tab defaults to Agents in code",/sub=sub==="roles"\?"roles":"agents"/.test(settingsJs)&&/if\(tab==="ai"\)setSwitchAiTab\(sub\|\|setState\.aiTab\|\|"agents"\)/.test(settingsJs))
check("AI Roles content under Roles",roles.includes('id="setAiRolesRoot"')&&roles.includes('id="setAiTerminalApproval"'))
check("agents and connections under Agents",agents.includes('id="setExtAgentsRoot"')&&agents.includes('id="setExtConnectionsRoot"'))
const extensions=html.slice(html.indexOf('data-tab-panel="extensions"'),html.indexOf('data-tab-panel="ai"'))
check("Extensions only links to AI > Agents",!extensions.includes("setExtAgentsRoot")&&!extensions.includes('id="setAiToggle"')&&/data-goto-ai="agents"/.test(extensions))
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
check("Esc handled as cancel",/confirmTrapKey\(e,box,cancel\)/.test(source)&&/const cancel=\(\)=>\{if\(answer\)\{answer\("cancel"\);return\}if\(running\)running\.cancel\(\)\}/.test(source))
// ---- regression (frozen dialog): Cancel is never disabled, every CLI step is a polled job, every step shows a running state
check("Cancel is never disabled while a step runs",!/cancelBtn\.disabled=true/.test(source)&&/cancelBtn\.addEventListener\("click",cancel\)/.test(source))
check("no step waits on a direct CLI bridge call",!/bridgeCall\("extAgents\.connection_(connect|test|detect|status|disconnect)"/.test(source)&&!/bridgeCall\("extAgents\.connections"\)/.test(source))
check("verify, connect and test run as jobs with a running state",/verify:\(\)=>job\("detect"/.test(source)&&/connect:\(\)=>job\("connect"/.test(source)&&/test:\(\)=>job\("test"/.test(source)&&/const status=\(\)=>job\("status"/.test(source))
check("running state has a spinner and elapsed time",/conn-wiz-spin/.test(source)&&/conn-wiz-elapsed/.test(source))
check("no ellipsis or long dashes in UI text",!/\.\.\.|…|–|—|·/.test(source))
// connJobRun against a fake bridge: start returns at once, polls until done.
function fakeBridge(script){
const calls=[]
let polls=0
const call=(path,args)=>{calls.push(path.split(".").pop()+(args&&args[0]!==undefined?":"+args[0]:""))
if(path.endsWith("job_start"))return Promise.resolve(script.start===undefined?{job:"j1"}:script.start)
if(path.endsWith("job_poll")){polls++;return Promise.resolve(script.poll(polls))}
if(path.endsWith("job_cancel"))return Promise.resolve({cancelled:true})
return Promise.reject(new Error("unexpected "+path))}
return {call,calls}
}
const fast={sleep:()=>Promise.resolve(),every:1}
tests.push((async()=>{
const b=fakeBridge({poll:(n)=>n<4?{done:false,elapsed:n}:{done:true,ok:true,result:{connected:true,message:"ok"}}})
const ticks=[]
const r=await api.connJobRun(b.call,"connect","claude_code",Object.assign({onTick:(p)=>ticks.push(p.done)},fast))
eq("job: result after polling",r,{connected:true,message:"ok"})
eq("job: started once, polled until done",b.calls,["connection_job_start:connect","connection_job_poll:j1","connection_job_poll:j1","connection_job_poll:j1","connection_job_poll:j1"])
eq("job: every poll reported",ticks,[false,false,false,true])
})())
tests.push((async()=>{
const b=fakeBridge({poll:()=>({done:true,ok:false,error:"Claude Code could not add LOYA NG's MCP server: boom"})})
let err=null
try{await api.connJobRun(b.call,"connect","claude_code",fast)}catch(e){err=e}
eq("job: backend error is raised with its text",err&&err.message,"Claude Code could not add LOYA NG's MCP server: boom")
})())
// A hung CLI: polls never finish. Cancel stops waiting at once and asks the backend to stop the job.
tests.push((async()=>{
const b=fakeBridge({poll:()=>({done:false})})
const tok=api.connCancelToken()
let n=0
const p=api.connJobRun(b.call,"test","claude_code",{token:tok,every:1,sleep:()=>{n++;if(n===5)tok.cancel();return new Promise((r)=>setTimeout(r,1))}})
let err=null
try{await p}catch(e){err=e}
eq("hung step: Cancel ends the wait",api.connIsCancel(err),true)
await new Promise((r)=>setTimeout(r,5))
check("hung step: backend told to cancel the job",b.calls.includes("connection_job_cancel:j1"),JSON.stringify(b.calls))
})())
// A bridge call that never answers at all: Cancel still works (the wait is raced against the cancel token).
tests.push((async()=>{
const tok=api.connCancelToken()
const call=(path)=>path.endsWith("job_start")?Promise.resolve({job:"j9"}):path.endsWith("job_cancel")?Promise.resolve({}):new Promise(()=>{})
const p=api.connJobRun(call,"status","claude_code",{token:tok,every:1})
setTimeout(()=>tok.cancel(),10)
let err=null
try{await p}catch(e){err=e}
eq("never-answering poll: Cancel still ends the wait",api.connIsCancel(err),true)
})())
// The flow: a step cancelled while running ends as cancelled+running; nothing after it runs.
tests.push((async()=>{
const ran=[]
const o={start:4,status:()=>Promise.resolve(INST),ask:()=>Promise.resolve("approve"),act:{connect:()=>{ran.push("connect");return Promise.reject(api.CONN_CANCELLED)},test:()=>{ran.push("test");return {ok:true}}}}
const r=await api.connRunWizard(o)
eq("cancel mid-step: cancelled while running at connect",[r.cancelled,r.running,r.index],[true,true,4])
eq("cancel mid-step: test never ran",ran,["connect"])
})())
// Connect advances to the test, with the connect result shown on the next step.
tests.push((async()=>{
const asked=[]
let connected=false
const o={start:4,status:()=>Promise.resolve(connected?CONN:SIGNED),ask:(v)=>{asked.push([v.step.id,v.info||""]);return Promise.resolve(asked.length<2?"approve":"cancel")},
act:{connect:()=>{connected=true;return {info:"Claude Code is connected."}}}}
const r=await api.connRunWizard(o)
eq("connect advances to test with its result",asked,[["connect",""],["test","Claude Code is connected."]])
eq("then cancel at test",r.index,5)
})())
// A failing step is shown on the same step (not swallowed); Approve tries again.
tests.push((async()=>{
const asked=[]
let tries=0
const o={start:4,status:()=>Promise.resolve(tries>1?CONN:SIGNED),ask:(v)=>{asked.push([v.step.id,v.note||""]);return Promise.resolve(asked.length<3?"approve":"cancel")},
act:{connect:()=>{tries++;if(tries===1)return Promise.reject(new Error("LOYA NG's MCP server did not start"));return null}}}
await api.connRunWizard(o)
eq("error shown on the step, then retried",asked,[["connect",""],["connect","LOYA NG's MCP server did not start"],["test",""]])
})())
// A status check that fails is shown too, and cancelling a running status check ends the flow.
tests.push((async()=>{
const asked=[]
let n=0
const o={start:3,status:()=>{n++;return n===1?Promise.reject(new Error("timed out")):Promise.reject(api.CONN_CANCELLED)},ask:(v)=>{asked.push([v.step.id,!!v.statusFailed,v.note]);return Promise.resolve("approve")},act:{}}
const r=await api.connRunWizard(o)
eq("failed status shown",asked,[["signin",true,"timed out"]])
eq("cancelled status check ends as running cancel",[r.cancelled,r.running],[true,true])
})())
// Step 3: the installer's questions (backend watch of the LOYA terminal tab)
const KNOWN_MSG='The installer asked "Start Codex now? [y/N]". LOYA NG answered No; you can start it from the AI panel later.'
const knownWv={watch:"w1",session:"s1",session_alive:true,answered:[{rule:"codex_start_now",question:"Start Codex now? [y/N]",answer:"No",ok:true,message:KNOWN_MSG}],prompt:null,installed:true,path:"/home/op/.local/bin/codex",version:"codex-cli 0.172.0"}
const kh=api.connWatchHtml(knownWv)
check("known auto-answer: the line is shown",kh.includes(KNOWN_MSG.replace(/"/g,"&quot;")),kh)
check("known auto-answer: no question buttons",!/conn-watch-choice|conn-watch-dismiss/.test(kh))
check("known auto-answer: found line with version and path",/Found codex-cli 0\.172\.0 at <code>\/home\/op\/\.local\/bin\/codex<\/code>/.test(kh),kh)
check("verify goes on once found with a version and no question",api.connVerifyReady(knownWv))
eq("verify result line names the answer, then the path",api.connVerifyInfo("Codex CLI",{path:"/home/op/.local/bin/codex"},knownWv),KNOWN_MSG+" Found Codex CLI codex-cli 0.172.0 at /home/op/.local/bin/codex.")
const askWv={watch:"w1",session:"s1",session_alive:true,answered:[],prompt:{id:"p9",kind:"ask",question:"Keep the old settings? [Y/n]",choices:[{id:"yes",label:"Yes",send:"y"},{id:"no",label:"No",send:"n"},{id:"enter",label:"Enter",send:""}]},installed:true,path:"/x/codex",version:"codex-cli 0.172.0"}
const ah=api.connWatchHtml(askWv)
check("unknown question is shown",ah.includes("Keep the old settings? [Y/n]")&&/role="alert"/.test(ah))
eq("unknown question: one button per choice",(ah.match(/class="set-btn conn-watch-choice" data-prompt="p9" data-choice="(yes|no|enter)">(Yes|No|Enter)</g)||[]).length,3)
check("unknown question: Cancel types nothing",/conn-watch-dismiss" data-prompt="p9">Cancel</.test(ah))
check("unknown question: says LOYA NG does not answer it by itself",/does not answer this one by itself/.test(ah))
check("verify waits while a question is open, even when found",!api.connVerifyReady(askWv)&&/Answer the installer's question first/.test(ah))
check("no version yet: verify waits",!api.connVerifyReady({installed:true,path:"/x",version:""}))
check("Press Enter question: only Enter",(api.connWatchHtml({session:"s",session_alive:true,answered:[],prompt:{id:"p1",question:"Press Enter to continue",choices:[{id:"enter",label:"Enter"}]}}).match(/conn-watch-choice/g)||[]).length===1)
check("question text is escaped",!api.connWatchHtml({answered:[],prompt:{id:"p",question:"<img src=x onerror=1>?",choices:[]}}).includes("<img"))
check("failed write is shown as an error",/set-status error/.test(api.connWatchHtml({answered:[{ok:false,message:"LOYA NG could not type the answer"}]})))
check("closed tab is reported",/terminal tab has closed/.test(api.connWatchHtml({session:"s",session_alive:false,answered:[],installed:false})))
check("no em/en dashes, ellipsis or middle dots in the watch texts",![kh,ah].some((t)=>/[\u2013\u2014\u2026\u00b7]/.test(t)))
check("install passes the new tab's session to the watch",/termNewTab\(shell,\{name:label\+" install",startup:line\}\)\)\.then\(\(sid\)=>watch\(sid\)\)/.test(source)&&/connection_install_watch_start",\[tool,sid\|\|""\]/.test(source))
check("choices go to the backend only on click",/conn-watch-choice"\)\.forEach\(\(b\)=>b\.addEventListener\("click"/.test(source)&&(source.match(/connection_install_watch_answer/g)||[]).length===1)
check("step 3 polls the watch and stops when the step ends",/if\(v\.step\.id==="verify"\)startLive\(v\)/.test(source)&&/answer=\(a\)=>\{answer=null;stopLive\(\)/.test(source)&&/const close=\(\)=>\{stopLive\(\)/.test(source))
check("step 3 goes on by itself only when ready",/if\(!v\.done&&connVerifyReady\(wv\)&&answer\)\{answer\("approve"\)/.test(source))
check("focus goes to the primary button",/\(okBtn\.disabled\?cancelBtn:okBtn\)\.focus\(\)/.test(source))
check("new UI text says LOYA NG",!/LOYA Note NG/.test(source))
Promise.all(tests).then(()=>{
console.log(`ext_connections: ${passed} passed, ${failed} failed`)
process.exit(failed?1:0)
})
