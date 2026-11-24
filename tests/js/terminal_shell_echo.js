// Terminal job markers under real shells: replays raw PTY bytes recorded from zsh (Kali's default /etc/skel/.zshrc with
// zsh-syntax-highlighting + autosuggestions, also at a narrow 40-column width) and bash through the real terminal.js
// (termSubmitCommand / termAppend / termSendControl) and checks what the panel keeps.
// Re-record:  node tests/js/terminal_shell_echo.js --emit <scenario> > steps.json
//             python3 tests/fixtures/terminal/record_shell_fixture.py steps.json tests/fixtures/terminal/<scenario>.json
const fs=require("fs")
const path=require("path")
const vm=require("vm")
const ROOT=path.resolve(__dirname,"..","..")
const SOURCE=fs.readFileSync(path.join(ROOT,"UI","js","components","terminal.js"),"utf8")
const FIXTURES=process.env.LOYA_SHELL_FIXTURES||path.join(ROOT,"tests","fixtures","terminal")
const ESC="\x1b"
// Each scenario: shell + rc file to record with, width, and the steps. expect: the job's exit code once the run is over.
const SCENARIOS={
zsh_skel:{shell:"zsh",rc:"/etc/skel/.zshrc",cols:120,files:["alpha.txt","beta.log","notes"],steps:[
{submit:"ls",jobId:"jls01",expect:0,listing:["alpha.txt","beta.log","notes"]},
{submit:"echo hello world",jobId:"jecho2",expect:0,output:"hello world"},
{submit:"echo \"unterminated",jobId:"jopen3",wait:0.8},{control:"\x03",closes:"jopen3",expect:130},
{submit:"ls )",jobId:"jsyn04",expect:1,output:"parse error"},
{submit:"sleep 5",jobId:"jint05",wait:0.7},{control:"\x03",closes:"jint05",expect:130},
{submit:"for i in 1 2\ndo echo $i\ndone",jobId:"jfor06",expect:0,output:"1\n2"},
{submit:"echo hi # it's a comment",jobId:"jcom07",expect:0,output:"hi"},
{submit:"false",jobId:"jfal08",expect:1},
{submit:"echo \"a",jobId:"jcont9",wait:0.8},{submit:"b\"",continues:"jcont9",expect:0,output:"a\nb"},
{submit:"sleep 0.1 &",jobId:"jbg010",expect:0},
{submit:"echo $((1+))",jobId:"jmath11",expect:1,output:"bad math"},
{submit:"clear",jobId:"jclr12",expect:0}]},
zsh_skel_narrow:{shell:"zsh",rc:"/etc/skel/.zshrc",cols:40,files:["alpha.txt"],steps:[
{submit:"echo hello world from a narrow pane",jobId:"jnar01",expect:0,output:"hello world from a narrow pane"},
{submit:"ls )",jobId:"jnar02",expect:1,output:"parse error"},
{submit:"ls",jobId:"jnar03",expect:0,listing:["alpha.txt"]}]},
bash_skel:{shell:"bash",rc:"/etc/skel/.bashrc",cols:120,files:["alpha.txt"],steps:[
{submit:"ls",jobId:"jbls01",expect:0,listing:["alpha.txt"]},
{submit:"ls )",jobId:"jbsy02",expect:2,output:"syntax error"},
{submit:"echo \"unterminated",jobId:"jbop03",wait:0.8},{control:"\x03",closes:"jbop03",expect:130},
{submit:"sleep 5",jobId:"jbin04",wait:0.7},{control:"\x03",closes:"jbin04",expect:130},
{submit:"echo hi # it's a comment",jobId:"jbco05",expect:0,output:"hi"}]}
}
function loadTerminal(){
const writes=[]
const nullEl=null
const ctx={console,setTimeout,clearTimeout,setInterval,clearInterval,Promise,
document:{getElementById:()=>nullEl,querySelector:()=>nullEl,querySelectorAll:()=>[],addEventListener(){},body:{appendChild(){}}},
window:{},navigator:{},requestAnimationFrame:()=>0,
bridgeCall:(name,args)=>{if(name==="terminal.write")writes.push(args[1]);return Promise.resolve(null)},
showToast(){},showStatusIsland(){},appConfirm:()=>Promise.resolve(false)}
vm.createContext(ctx)
vm.runInContext(SOURCE+"\n;this.__termState=termState",ctx,{filename:"terminal.js"})
for(const name of ["termRenderTabs","termRenderSession","termRenderPane","termRenderActiveOutput","termSaveWorkspaceSoon","termWakePolling","termRefreshJobs","termUpdateStatusBar","termSuggestHide"])ctx[name]=()=>{}
const state=ctx.__termState
state.platform="linux"
state.jobBlocks=true
return {ctx,state,writes}
}
function newSession(t,shellId,cols){
const tab={sessionId:"s1",shellId,label:"t",buffer:"",dead:false,history:[],historyIdx:null,listings:[],pendingCapture:null,elevated:false,visible:"",pendingRaw:"",activeJob:null,jobHistory:[],lastExitCode:null,cwd:"",renderVersion:0,renderedVersion:-1,renderedLen:0,ansiClasses:[],profileId:"",prior:null,staged:"",cols,rows:30}
t.state.tabs.push(tab)
t.state.activeId="s1"
return tab
}
function submit(t,step){
if(step.jobId)t.ctx.termNewJobId=()=>step.jobId
const before=t.writes.length
t.ctx.termSubmitCommand(step.submit)
return t.writes.slice(before).join("")
}
// --emit: the exact bytes the app sends for each step, for the recorder.
if(process.argv[2]==="--emit"){
const sc=SCENARIOS[process.argv[3]]
if(!sc){console.error("unknown scenario");process.exit(2)}
const t=loadTerminal()
newSession(t,sc.shell,sc.cols)
const tab=t.state.tabs[0]
// No shell answers here: a Ctrl+C step stands for the prompt coming back, which ends the job and any open continuation.
const out=sc.steps.map((step)=>{if(step.control){tab.continuation=null;tab.activeJob=null;return {control:step.control,wait:step.wait||1.2}}return {submit:step.submit,jobId:step.jobId||"",sent:submit(t,step),wait:step.wait||1.2}})
process.stdout.write(JSON.stringify({shell:sc.shell,rc:sc.rc,cols:sc.cols,files:sc.files,steps:out},null,1))
process.exit(0)
}
let passed=0,failed=0
function check(name,ok,detail){if(ok){passed++;return}failed++;console.log("  FAIL  "+name+(detail?"  ->  "+detail:""))}
function plain(text){return String(text).replace(/\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-9;?]*[A-Za-z]|\x1b[=>]/g,"").replace(/\r/g,"")}
for(const name of Object.keys(SCENARIOS)){
const sc=SCENARIOS[name]
const file=path.join(FIXTURES,name+".json")
if(!fs.existsSync(file)){check(name+": fixture exists",false,file);continue}
const fx=JSON.parse(fs.readFileSync(file,"utf8"))
const t=loadTerminal()
const tab=newSession(t,fx.shell,fx.cols)
let stepAt=0
const seen={}
fx.events.forEach((ev)=>{
if(ev.out!==undefined){t.ctx.termAppend("s1",ev.out);return}
const step=sc.steps[stepAt++]
if(ev.control!==undefined){t.ctx.termSendControl(ev.control);return}
const sent=submit(t,step)
check(name+": "+JSON.stringify(step.submit)+" sends the recorded bytes",sent===ev.sent,JSON.stringify(sent)+" vs "+JSON.stringify(ev.sent))
})
const shown=plain(tab.buffer)
check(name+": no marker text is ever shown",!/__LOYA_JOB__|__END__|printf '/.test(shown),JSON.stringify(shown.slice(shown.search(/__LOYA|printf '/)-80,shown.search(/__LOYA|printf '/)+80)))
check(name+": no raw line-editing controls are left",!/[\x08]/.test(tab.buffer)&&!/\x1b\[\d*[CDG]/.test(tab.buffer))
check(name+": no job is left running",tab.activeJob===null,tab.activeJob&&JSON.stringify(tab.activeJob.command))
sc.steps.forEach((step)=>{
const jobId=step.closes||step.continues||step.jobId
if(!jobId||step.expect===undefined)return
const record=tab.jobHistory.find((j)=>j.jobId===jobId)
check(name+": job "+jobId+" finished with exit "+step.expect,record&&record.exitCode===step.expect,record?String(record.exitCode):"no record")
if(!record)return
if(step.submit&&!step.continues){
const head=plain(tab.buffer.slice(record.startIdx)).split("\n")[0]
check(name+": job "+jobId+" block starts at the typed command",head===step.submit.split("\n")[0].replace(/\s*#.*$/,""),JSON.stringify(head))
}
if(step.output){
const body=plain(tab.buffer.slice(record.startIdx,record.endIdx))
check(name+": job "+jobId+" output kept",body.indexOf(step.output)>=0,JSON.stringify(body.slice(0,300)))
}
if(step.listing){
const listing=(tab.listings||[]).find((l)=>l.startIdx===record.startIdx)
check(name+": job "+jobId+" listing widget has exactly the files",listing&&JSON.stringify(listing.rows.map((r)=>r.name))===JSON.stringify(step.listing),listing?JSON.stringify(listing.rows.map((r)=>r.name)):"no listing")
check(name+": job "+jobId+" listing widget does not swallow the next prompt",listing&&!/┌──|└─\$/.test(plain(tab.buffer.slice(listing.startIdx,listing.endIdx))),listing&&JSON.stringify(plain(tab.buffer.slice(listing.startIdx,listing.endIdx))))
}
})
check(name+": only real listings become widgets (a rejected 'ls )' does not)",(tab.listings||[]).length===sc.steps.filter((s)=>s.listing).length,JSON.stringify((tab.listings||[]).map((l)=>l.rows.map((r)=>r.name))))
const promptLines=shown.split("\n").filter((l)=>/^└─[$#] \S/.test(l))
const typed=sc.steps.filter((s)=>s.submit&&!s.continues).map((s)=>s.submit.split("\n")[0].replace(/\s*#.*$/,""))
check(name+": every command shows once on its prompt line, clean",typed.every((cmd)=>promptLines.filter((l)=>l==="└─$ "+cmd).length===1),JSON.stringify(promptLines))
}
// "Clear output" right before a command wipes the prompt line from the panel: the rejected line still closes the job.
if(fs.existsSync(path.join(FIXTURES,"zsh_skel.json"))){
const fx=JSON.parse(fs.readFileSync(path.join(FIXTURES,"zsh_skel.json"),"utf8"))
const t=loadTerminal()
const tab=newSession(t,fx.shell,fx.cols)
fx.events.forEach((ev)=>{
if(ev.out!==undefined)t.ctx.termAppend("s1",ev.out)
else if(ev.control!==undefined)t.ctx.termSendControl(ev.control)
else{if(ev.jobId==="jsyn04")t.ctx.termClearOutput();t.ctx.termNewJobId=()=>ev.jobId;t.ctx.termSubmitCommand(ev.submit)}
})
const record=tab.jobHistory.find((j)=>j.jobId==="jsyn04")
check("after Clear output a syntax error still closes its job",record&&record.exitCode===1,record?String(record.exitCode):"no record")
}
// ---- unit checks on the POSIX helpers
const t=loadTerminal()
const em=t.ctx.termEmulateLine("ab\x08\x08XY"+ESC+"[1D"+ESC+"[31mZ"+ESC+"[0m",80)
check("emulator: backspace and cursor-left overwrite in place",em.plain==="XZ",JSON.stringify(em.plain))
check("emulator: colour of the overwritten cell is kept",em.cells[1].sgr===ESC+"[31m"&&em.sgr==="")
const wrap=t.ctx.termEmulateLine("$ "+"x".repeat(38)+" \r"+ESC+"[K"+"y\ry",40)
check("emulator: zsh's margin wrap (' \\r ESC[K') continues on the next row",wrap.plain==="$ "+"x".repeat(38)+"y",JSON.stringify(wrap.plain))
check("emulator: wide characters take two cells",t.ctx.termEmulateLine("㉿"+"a".repeat(38)+"b",40).plain==="㉿"+"a".repeat(38)+"b")
const ls=t.ctx.termPosixLineState
check("line state: an open double quote",ls("echo \"x").open)
check("line state: quotes inside single quotes are literal",!ls("echo 'a\"b'").open)
check("line state: an escaped quote does not open",!ls("echo \\\"").open)
check("line state: an open $(",ls("echo $(ls").open)
check("line state: a trailing backslash continues",ls("echo a \\").open)
check("line state: a comment with an apostrophe is a comment",!ls("echo hi # it's").open&&ls("echo hi # it's").commentAt===8)
check("line state: # inside a word is not a comment",ls("echo a#b").commentAt===-1&&ls("echo $#").commentAt===-1)
const ep=t.ctx.termJobEpilogue("shell","jx")
const jl=t.ctx.termPosixJobLine
check("job line: plain command gets the marker",jl("ls",ep).line==="ls"+ep)
check("job line: trailing comment is dropped so the marker runs",jl("ls # note",ep).line==="ls"+ep)
check("job line: trailing & keeps the job in the background without ';&'",jl("sleep 1 &",ep).line==="sleep 1 &"+ep.replace(/^ ;/," "))
check("job line: trailing ; is not doubled",jl("ls;",ep).line==="ls"+ep)
check("job line: && stays a list",jl("a && b",ep).line==="a && b"+ep)
check("job line: an open quote goes without the marker",jl("echo \"x",ep).open&&jl("echo \"x",ep).line==="echo \"x")
for(const shell of ["cmd","powershell","pwsh"]){
const tab={shellId:shell}
check(shell+": payload is the command plus its marker, unchanged",t.ctx.termJobPayload(tab,"dir # x","jq")==="dir # x"+t.ctx.termJobEpilogue(shell,"jq"))
}
console.log("")
console.log(passed+" passed, "+failed+" failed")
process.exit(failed?1:0)
