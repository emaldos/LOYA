// Settings > Terminal Shells / Kali Linux on WSL card logic, the 100 s notes timer, the "!" popover, and the terminal's new-session menu.
const fs=require("fs")
const path=require("path")
const ROOT=path.join(__dirname,"..","..")
const S=require("../../UI/js/components/terminal-shells.js")
const SRC=fs.readFileSync(path.join(ROOT,"UI","js","components","terminal-shells.js"),"utf8")
const CSS=fs.readFileSync(path.join(ROOT,"UI","css","terminal-shells.css"),"utf8")
const TERM=fs.readFileSync(path.join(ROOT,"UI","js","components","terminal.js"),"utf8")
let passed=0,failed=0
function check(name,ok,detail){if(ok)passed++;else{failed++;console.log("FAIL: "+name+(detail?" - "+detail:""))}}
function eq(name,a,b){check(name,JSON.stringify(a)===JSON.stringify(b),JSON.stringify(a)+" != "+JSON.stringify(b))}
function slice(source,from,to){const a=source.indexOf(from),b=source.indexOf(to,a);if(a<0||b<0)throw new Error("slice "+from);return source.slice(a,b)}
// ---- new-session menu (terminal.js)
const menu=new Function(slice(TERM,"const TERM_INSTALL_PWSH","function termRenderShellSelect")+";return{termShellMenuOptions,TERM_INSTALL_PWSH}")()
const linuxShells=[{id:"shell",label:"zsh",default:true},{id:"bash",label:"bash"}]
let opts=menu.termShellMenuOptions(linuxShells,{platform:"linux",pwsh:{installed:false,installable:true,command:"sudo sh -c 'apt-get update && apt-get install -y powershell'"}})
eq("linux menu: shells then the install offer",opts.map((o)=>o.value),["shell","bash","__install:pwsh"])
check("default shell is marked",opts[0].label==="zsh (default)")
check("install label",opts[2].label==="PowerShell (not installed) – Install…"&&opts[2].kind==="install"&&!opts[2].disabled)
check("install shows the command as a tooltip",opts[2].title.indexOf("apt-get install -y powershell")>=0)
opts=menu.termShellMenuOptions(linuxShells.concat([{id:"pwsh",label:"PowerShell"}]),{platform:"linux",pwsh:{installed:true,installable:false}})
eq("linux with pwsh: a real PowerShell session, no install offer",opts.map((o)=>o.value),["shell","bash","pwsh"])
opts=menu.termShellMenuOptions(linuxShells,{platform:"linux",pwsh:{installed:false,installable:false,reason:"no apt"}})
check("no apt: shown but disabled with the reason",opts[2].disabled===true&&opts[2].title==="no apt"&&opts[2].label==="PowerShell (not installed)")
opts=menu.termShellMenuOptions([{id:"pwsh",label:"PowerShell 7",default:true},{id:"powershell",label:"Windows PowerShell"},{id:"cmd",label:"Command Prompt"},{id:"wsl:kali-linux",label:"Kali Linux (WSL)"}],{platform:"windows",kali_ready:true})
eq("windows: no install entry, Kali as the backend names it",opts.map((o)=>o.label),["PowerShell 7 (default)","Windows PowerShell","Command Prompt","Kali Linux (WSL)"])
eq("no extras yet",menu.termShellMenuOptions(linuxShells,null).length,2)
check("an action value is never used as a shell id",TERM.indexOf('sel.value.indexOf("__")!==0?sel.value:""')>=0)
const nl=new Function("termState",slice(TERM,"function termShellFamily","function termNewJobId")+";return termSubmitNewline")
check("pwsh on Linux submits with CR",nl({platform:"linux"})("pwsh")==="\r")
check("pwsh on Windows keeps CRLF",nl({platform:"windows"})("pwsh")==="\r\n")
check("posix stays LF",nl({platform:"linux"})("bash")==="\n")
// ---- default shell select
let d=S.tshDefaultShellOptions([{id:"pwsh",label:"PowerShell 7"},{id:"cmd",label:"Command Prompt"}],"auto","windows")
eq("auto first and selected",d.map((o)=>[o.value,o.selected]),[["auto",true],["pwsh",false],["cmd",false]])
check("windows auto text names PowerShell",d[0].label.indexOf("PowerShell 7 if installed")>=0)
d=S.tshDefaultShellOptions([{id:"cmd",label:"Command Prompt"}],"pwsh","windows")
check("a stored choice that is missing now stays selected and is marked",d[2].value==="pwsh"&&d[2].selected&&d[2].missing)
// ---- network modes
const LABELS={nat:"Default (NAT)",mirrored:"Same IP as this computer",bridged:"Separate device on the network",custom:"Custom IP"}
const HOME_REASON="Separate device on the network won't work on Windows 11 Home because it needs Hyper-V, which Home doesn't include."
const avail={nat:{available:true},mirrored:{available:true},bridged:{available:false,reason:HOME_REASON},custom:{available:false,reason:"Custom IP won't work on Windows 11 Home because it needs Hyper-V, which Home doesn't include."}}
let m=S.tshModeOptions(avail,"mirrored",LABELS)
eq("modes in order",m.map((o)=>o.value),["nat","mirrored","bridged","custom"])
eq("availability",m.map((o)=>o.available),[true,true,false,false])
check("selected",m[1].selected)
eq("reasons for the unavailable ones",S.tshUnavailableReasons(avail,LABELS).map((r)=>r.mode),["bridged","custom"])
eq("fields per mode",[S.tshModeFields("nat"),S.tshModeFields("mirrored"),S.tshModeFields("bridged"),S.tshModeFields("custom")],[[],[],["switch","mac"],["switch","mac","ip","prefix","gateway","dns"]])
eq("collect drops fields a mode does not use",S.tshCollectNetwork("nat",{ip:"1.2.3.4"}),{mode:"nat"})
eq("collect trims",S.tshCollectNetwork("custom",{switch:"LAN",ip:" 192.168.1.5 ",prefix:"24",gateway:"192.168.1.1",dns:"1.1.1.1",mac:""}),{mode:"custom",switch:"LAN",mac:"",ip:"192.168.1.5",prefix:"24",gateway:"192.168.1.1",dns:"1.1.1.1"})
eq("unknown mode falls back to nat",S.tshCollectNetwork("evil",{}).mode,"nat")
const st={supported:true,mode_labels:LABELS,availability:avail,hyperv:{switches:["LAN <b>"]},state:{enabled:true,configured:true,network:{mode:"nat"},wslconfig_backup:"x"},windows:{name:"Windows 11 Home",build:22631,ubr:4317},wsl:{ok:true,present:true,version:"2.6.1.0"},kali_installed:true,network_mode:"nat",addresses:[{ip:"172.20.1.2",prefix:20,interface:"eth0"}],wslconfig:{exists:true},notes:["A","B"],step:"done"}
let html=S.tshNetworkFormHtml(st,"nat",{})
check("unavailable options are disabled and say so",/<option value="bridged" disabled>Separate device on the network \(won't work here\)<\/option>/.test(html))
check("the plain reason is shown",html.indexOf("Windows 11 Home because it needs Hyper-V, which Home doesn&#39;t include.")>=0)
check("configured: Update button, with the ! next to it",/id="tshApply">Update<\/button><button type="button" class="tsh-notes-btn"/.test(html))
check("wizard: Apply",S.tshNetworkFormHtml(Object.assign({},st,{state:{configured:false}}),"nat",{}).indexOf(">Apply</button>")>=0)
html=S.tshNetworkFormHtml(st,"custom",{ip:'"><img src=x onerror=1>'})
check("switch names and values are escaped",html.indexOf("LAN &lt;b&gt;")>=0&&html.indexOf("<img")<0)
check("custom shows all the network fields",["tshNet_ip","tshNet_prefix","tshNet_gateway","tshNet_dns","tshNet_mac","tshNet_switch"].every((id)=>html.indexOf(id)>=0))
check("no switch-creation flow anywhere",!/New-VMSwitch|create (a|the) switch/i.test(SRC))
const lookup=S.tshNetworkFormHtml(Object.assign({},st,{availability:Object.assign({},avail,{bridged:{available:false,needs_lookup:true,reason:"r"}})}),"nat",{})
check("needs admin to list switches: read-only lookup button",lookup.indexOf('id="tshLookup"')>=0)
// ---- card states
html=S.tshKaliHtml(Object.assign({},st,{state:{enabled:false}}))
check("off: only the toggle",html.indexOf('id="tshKaliEnable"')>=0&&html.indexOf("tshStart")<0&&html.indexOf("tsh-status")<0)
html=S.tshKaliHtml(Object.assign({},st,{state:{enabled:true,configured:false},step:"idle"}))
check("on, not set up: Set up button with the ! next to it",/id="tshStart">Set up Kali Linux on WSL<\/button><button type="button" class="tsh-notes-btn"/.test(html)&&html.indexOf('id="tshNotesSlot"')>=0)
html=S.tshKaliHtml(st)
check("configured: open, restart, remove",["tshOpenKali","tshRestart","tshRemove","tshMode","tshNotesSlot"].every((id)=>html.indexOf('id="'+id+'"')>=0))
check("status shows the IP and the build",html.indexOf("172.20.1.2/20")>=0&&html.indexOf("build 22631.4317")>=0)
html=S.tshKaliHtml(Object.assign({},st,{state:{enabled:true,configured:false},step:"user"}))
check("wizard user step",html.indexOf("tshFirstRun")>=0&&html.indexOf("tshAddUser")>=0&&html.indexOf('aria-current="step"')>=0)
eq("step index",[S.tshStepIndex("prereq"),S.tshStepIndex("reboot"),S.tshStepIndex("install"),S.tshStepIndex("verify"),S.tshStepIndex("done")],[0,0,1,4,5])
check("verify html",S.tshVerifyHtml({started:true,addresses:[{ip:"1.2.3.4",prefix:24,interface:"eth0"}],gateway:"1.2.3.1",gateway_ok:true,dns_ok:false}).indexOf("kali.org did not resolve")>=0)
check("describe html escapes",S.tshDescribeHtml({commands:["<x>"],elevated:true,notes:[]}).indexOf("&lt;x&gt;")>=0)
// ---- "!" button
const btnHtml=S.tshNotesButtonHtml()
check("! is a real button with a name, tooltip and dialog semantics",btnHtml.indexOf('type="button"')>=0&&btnHtml.indexOf('aria-label="WSL network notes"')>=0&&btnHtml.indexOf('title="WSL network notes"')>=0&&btnHtml.indexOf('aria-haspopup="dialog"')>=0&&btnHtml.indexOf('aria-expanded="false"')>=0)
check("hover never opens the notes",!/tshNotesBtn[^\n]*(mouseenter|mouseover|pointerenter)/.test(SRC))
check("bump animation respects reduced motion",/@media \(prefers-reduced-motion:reduce\)\{\.tsh-notes-btn\{animation:none\}\}/.test(CSS)&&CSS.indexOf("@keyframes tsh-bump")>=0)
check("css uses tokens only (no hard-coded theme colours except white text)",!/#[0-9a-f]{3,8}\b/i.test(CSS.replace(/#fff\b/g,"")))
// ---- timer
function fakeClock(){let t=0,fn=null,cleared=0;return{now:()=>t,setInterval:(f)=>{fn=f;return 7},clearInterval:(id)=>{if(id===7)cleared++},advance(ms){t+=ms;if(fn)fn()},get cleared(){return cleared}}}
let clock=fakeClock(),ticks=[],done=[]
let timer=S.tshCreateNotesTimer(100000,{now:clock.now,setInterval:clock.setInterval,clearInterval:clock.clearInterval,onTick:(l)=>ticks.push(l),onDone:(r)=>done.push(r)}).start()
eq("first tick is the full time",ticks[0],100000)
clock.advance(40000)
eq("counts down",timer.remaining(),60000)
clock.advance(59000)
check("still showing at 99 s",done.length===0)
clock.advance(1000)
eq("hides at 100 s",done,["timeout"])
check("interval cleared",clock.cleared===1)
clock.advance(1000)
eq("no second done",done.length,1)
clock=fakeClock();done=[]
timer=S.tshCreateNotesTimer(100000,{now:clock.now,setInterval:clock.setInterval,clearInterval:clock.clearInterval,onDone:(r)=>done.push(r)}).start()
clock.advance(5000);timer.stop();timer.stop()
eq("x closes once",done,["closed"])
check("closed timer reports done and 0 left",timer.done&&timer.remaining()===0)
html=S.tshInlineNotesHtml(["Note A","Note B"],100000,100000)
check("inline notes: close button, countdown, bar",html.indexOf('id="tshNotesClose" aria-label="Close the WSL network notes"')>=0&&html.indexOf("Hides in 100 s")>=0&&html.indexOf('width:100.0%')>=0)
check("inline notes: both notes",html.indexOf("Note A")>=0&&html.indexOf("Note B")>=0)
check("inline notes resume part-way",S.tshInlineNotesHtml([],50000,100000).indexOf("width:50.0%")>=0)
check("re-render keeps the remaining time",SRC.indexOf("tshShowInlineNotes(left)")>=0)
// ---- popover with a tiny DOM
function el(tag){
const e={tagName:tag,attrs:{},listeners:{},children:[],style:{},className:"",id:"",innerHTML:"",tabIndex:0,focused:false,removed:false,
setAttribute(k,v){this.attrs[k]=String(v)},getAttribute(k){return this.attrs[k]},addEventListener(t,f){(this.listeners[t]=this.listeners[t]||[]).push(f)},
focus(){focusLog.push(this)},remove(){this.removed=true;body.children=body.children.filter((c)=>c!==this)},contains(x){return x===this||x===this._x},
getBoundingClientRect(){return {left:100,top:100,bottom:126,right:126}},get offsetHeight(){return 120},
querySelector(sel){if(sel===".tsh-notes-x"){this._x=this._x||el("button");return this._x}return null},closest(){return null}}
return e
}
const focusLog=[]
const body=el("body");body.appendChild=(c)=>body.children.push(c)
const docListeners={}
global.window={innerWidth:1200,innerHeight:800}
const btn=el("button");btn.id="tshNotesBtn";btn.closest=(s)=>s==="#tshNotesBtn"?btn:null
global.document={body,createElement:el,getElementById:(id)=>id==="tshNotesBtn"?btn:null,addEventListener:(t,f)=>{(docListeners[t]=docListeners[t]||[]).push(f)},removeEventListener:(t,f)=>{docListeners[t]=(docListeners[t]||[]).filter((x)=>x!==f)}}
S.tshOpenNotesPopover(btn,["Note A","Note B"])
const pop=body.children[0]
check("popover opens on click",!!pop&&S.tshState.popover===pop&&pop.attrs.role==="dialog"&&pop.attrs["aria-label"]==="WSL network notes")
check("popover shows both notes",pop.innerHTML.indexOf("Note A")>=0&&pop.innerHTML.indexOf("Note B")>=0)
check("aria-expanded true while open",btn.attrs["aria-expanded"]==="true")
check("focus moves into the popover",focusLog[focusLog.length-1]===pop)
const key=(k)=>{let prevented=false;(docListeners.keydown||[]).slice().forEach((f)=>f({key:k,preventDefault(){prevented=true},stopPropagation(){}}));return prevented}
key("a")
check("other keys do not close it",S.tshState.popover===pop)
check("Escape is handled",key("Escape"))
check("Escape closes it",S.tshState.popover===null&&pop.removed&&btn.attrs["aria-expanded"]==="false")
check("focus returns to the ! button",focusLog[focusLog.length-1]===btn)
check("listeners are removed",(docListeners.keydown||[]).length===0&&(docListeners.mousedown||[]).length===0)
S.tshOpenNotesPopover(btn,["x"]);S.tshOpenNotesPopover(btn,["x"])
check("clicking ! again toggles it shut",S.tshState.popover===null)
S.tshOpenNotesPopover(btn,["x"])
const p2=S.tshState.popover
p2._x.listeners.click[0]()
check("the x closes it",S.tshState.popover===null&&p2.removed)
S.tshOpenNotesPopover(btn,["x"])
const p3=S.tshState.popover;(docListeners.mousedown||[]).slice().forEach((f)=>f({target:{closest:()=>null}}))
check("a click outside closes it",S.tshState.popover===null&&p3.removed)
// ---- H-03 / SA-13: no terminal polling while the app is locked, and it resumes after unlock
{
const ts={tabs:[{sessionId:"a"}],polling:false,pollTimer:null,pollDelay:0,lastAliveCheck:0}
let ticks=0
const lockMod=new Function("termState","termPollTick","TERM_POLL_MIN_MS","clearTimeout",slice(TERM,"function termStartPolling","// \"zsh 3\" style default names")+";return{termStartPolling,termStopPolling,termSetLockPaused}")(ts,()=>{ticks++},60,()=>{})
lockMod.termStartPolling()
check("polls when unlocked",ts.polling&&ticks===1)
lockMod.termSetLockPaused(true)
check("lock stops polling",!ts.polling&&ts.locked===true)
lockMod.termStartPolling()
check("nothing can start polling while locked",!ts.polling&&ticks===1)
lockMod.termSetLockPaused(true)
lockMod.termSetLockPaused(false)
check("unlock resumes polling that was running",ts.polling&&ticks===2&&!ts.locked)
lockMod.termStopPolling();lockMod.termSetLockPaused(true);lockMod.termSetLockPaused(false)
check("unlock does not start polling that was not running",!ts.polling&&ticks===2)
const LOCK=fs.readFileSync(path.join(ROOT,"UI","js","components","lock-screen.js"),"utf8")
check("the lock screen pauses and resumes the terminal",/function setLockedChromeState\(locked\)\{[\s\S]*termSetLockPaused\(locked\)[\s\S]*?\n\}/.test(LOCK))
}
// ---- popovers stay inside the window even when they render wider than asked (split picker: 320px vs 276)
{
const fn=new Function("document","window","requestAnimationFrame","termClosePopover","termPopoverOutsideClick","setTimeout",slice(TERM,"function termOpenPopover","function termShowHistoryWidget")+";return termOpenPopover")
const pop={style:{},offsetWidth:320,offsetHeight:240}
const open=fn({createElement:()=>pop,body:{appendChild(){}},addEventListener(){}},{innerWidth:1280,innerHeight:800},(cb)=>cb(),()=>{},null,()=>{})
open({getBoundingClientRect:()=>({left:988,top:106,bottom:132})},276)
check("popover re-clamped to its real width",parseInt(pop.style.left)+320<=1280-16,pop.style.left)
}
// ---- running into an existing session while the panel is closed opens the panel (Quick Run "Sent to Terminal" was invisible)
{
const fn=new Function("termState","termOpenPanel",slice(TERM,"function termEnsureActiveSession","function termOpenForRun")+";return termEnsureActiveSession")
let opened=0
const st={activeId:"abc",open:false,enabled:true}
fn(st,()=>{opened++;st.open=true})().then((id)=>check("ensure-active returns the live session",id==="abc"))
check("closed panel is opened for a run into the active session",opened===1)
fn(st,()=>{opened++})()
check("an open panel is not reopened",opened===1)
}
console.log("terminal_shells: "+passed+" passed, "+failed+" failed")
if(failed)process.exit(1)
