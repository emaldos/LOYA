// Terminal right-click menu in full terminal mode (xterm): the Full terminal mode row, key hints, and how
// termCtxRun routes copy / paste / find / clear / select all / mode switch to the terminal-emu.js hooks.
const fs=require("fs")
const path=require("path")
const ROOT=path.resolve(__dirname,"..","..")
const SOURCE=fs.readFileSync(path.join(ROOT,"UI","js","components","terminal-menu.js"),"utf8")
let passed=0,failed=0
function check(name,condition,detail){
if(condition){passed++;return}
failed++
console.log("  FAIL  "+name+(detail?"  ->  "+detail:""))
}
const pure=SOURCE.slice(0,SOURCE.indexOf("// ---- DOM"))
const M=new Function(pure+";return{termCtxBuildItems}")()
const base={hasSession:true,dead:false,jobRunning:false,hasOutput:true,layout:"single",mode:"right",maximized:false,fontSize:12,closedCount:0,canNote:true,canCve:true,canSearch:true,canOpenUrl:true,canSplit:true}
function build(extra){return M.termCtxBuildItems(Object.assign({},base,extra||{}))}
function row(items,id){
for(const it of items){if(it.id===id)return it;if(it.submenu){const hit=row(it.submenu,id);if(hit)return hit}}
return null
}
// ---- Full terminal mode row
const line=build({})
const session=row(line,"session").submenu
check("Full terminal mode sits in the Session submenu",session.some((it)=>it.id==="full_terminal")&&!line.some((it)=>it.id==="full_terminal"))
check("Full terminal mode is a checkbox row",row(line,"full_terminal").checkbox===true&&row(line,"full_terminal").label==="Full terminal mode")
check("line view: unchecked and enabled",row(line,"full_terminal").checked===false&&!row(line,"full_terminal").disabled)
const emu=build({emulator:true})
check("emulator: checked and enabled",row(emu,"full_terminal").checked===true&&!row(emu,"full_terminal").disabled)
const locked=build({emulator:true,emuLocked:true})
check("locked tab: checked and disabled",row(locked,"full_terminal").checked===true&&row(locked,"full_terminal").disabled===true)
check("no session: disabled",row(build({hasSession:false,hasOutput:false}),"full_terminal").disabled===true)
check("no emulator support: disabled",row(build({canEmulate:false}),"full_terminal").disabled===true)
// ---- key hints and rows
check("emulator: Copy and Paste keep Ctrl+Shift+C / Ctrl+Shift+V",row(emu,"copy").key==="Ctrl+Shift+C"&&row(emu,"paste").key==="Ctrl+Shift+V")
check("emulator: Clear and Find drop the Ctrl+L / Ctrl+F hints",!row(emu,"clear").key&&!row(emu,"find").key&&!!row(emu,"find"))
check("line view: Clear and Find keep their hints",row(line,"clear").key==="Ctrl+L"&&row(line,"find").key==="Ctrl+F")
check("emulator: paste rows stay",!!row(emu,"paste_line")&&!row(emu,"paste").disabled)
check("emulator: Interrupt enabled without job tracking",row(emu,"interrupt").disabled===false&&row(line,"interrupt").disabled===true)
check("emulator dead session: Interrupt and paste disabled",row(build({emulator:true,dead:true}),"interrupt").disabled&&row(build({emulator:true,dead:true}),"paste").disabled)
check("emulator: Select all needs only a session",!row(build({emulator:true,hasOutput:false}),"select_all").disabled&&row(build({hasOutput:false}),"select_all").disabled)
check("emulator: selection enables Copy",row(build({emulator:true,selection:"root"}),"copy").disabled===false)
// ---- termCtxRun routing (DOM-free, stubbed globals)
function harness(opts){
const o=opts||{}
const log=[]
const input={value:"",focus(){log.push("input.focus")},select(){}}
const searchInput={value:"",focus(){},select(){}}
const document={
getElementById:(id)=>id==="terminalInput"?(o.noInput?null:input):id==="terminalSearchInput"?searchInput:id==="terminalSearchBar"?{classList:{remove(){}}}:null,
documentElement:{classList:{contains:()=>false}},
addEventListener(){},removeEventListener(){}
}
const navigator={clipboard:{writeText:(t)=>{log.push("clip.write:"+t);return Promise.resolve()},readText:()=>Promise.resolve(o.clip===undefined?"ls":o.clip)}}
const termState={open:true,activeId:"s1",confirmMultilinePaste:true,panes:[],searchQuery:"",searchIndex:0}
const tab={sessionId:"s1",buffer:"out",emu:!!o.emu}
const g={
document,navigator,termState,window:{addEventListener(){},removeEventListener(){}},
showToast:(m)=>log.push("toast:"+m),
appConfirm:(msg)=>{log.push("confirm:"+msg);return Promise.resolve(o.confirm!==false)},
termPastePreviewHtml:()=>"",
termFindTab:()=>tab,
termInsertAtCursor:(t)=>log.push("insert:"+t),
termConfirmMultilinePaste:(t)=>log.push("lineconfirm:"+t),
termOpenSearch:()=>log.push("openSearch"),
termRunSearch:()=>log.push("runSearch"),
termClearOutput:()=>log.push("clearOutput"),
termSendControl:(k)=>log.push("ctl:"+JSON.stringify(k)),
termClearStagedInput:()=>log.push("clearStaged"),
TERM_SHELL_CONTROL_KEYS:{c:"\x03"},
termEmuOn:(t)=>!!t.emu,
termEmuLocked:()=>false,
termEmuSelection:()=>o.emuSel||"",
termEmuPaste:(t,text)=>log.push("emuPaste:"+text),
termEmuSelectAll:()=>log.push("emuSelectAll"),
termEmuClear:()=>log.push("emuClear"),
termEmuFocus:()=>log.push("emuFocus"),
termEmuFind:(t,q)=>{log.push("emuFind:"+q);return true},
termEmuSetMode:(t,on)=>{log.push("setMode:"+on);t.emu=on;return Promise.resolve()}
}
const names=Object.keys(g)
const api=new Function(...names,SOURCE+";return{termCtxRun,termCtxContext,termCtxClose,termCtx}")(...names.map((n)=>g[n]))
const run=(id,extra)=>api.termCtxRun(id,{},Object.assign({tab,pane:null,selection:o.sel||"",x:0,y:0},extra||{}))
return {log,tab,termState,searchInput,api,run}
}
const tick=()=>new Promise((r)=>setTimeout(r,0))
;(async()=>{
let h=harness({emu:true,emuSel:"uid=0(root)"})
h.run("copy")
await tick()
check("emulator Copy copies the xterm selection",h.log.includes("clip.write:uid=0(root)"),h.log.join("|"))
check("emulator Copy refocuses the xterm, not the input",h.log.includes("emuFocus")&&!h.log.includes("input.focus"),h.log.join("|"))
h=harness({emu:true,clip:"whoami"})
h.run("paste")
await tick();await tick()
check("emulator Paste writes through termEmuPaste",h.log.includes("emuPaste:whoami")&&!h.log.some((l)=>/^insert:/.test(l)),h.log.join("|"))
check("emulator Paste refocuses the xterm",h.log.includes("emuFocus")&&!h.log.includes("input.focus"),h.log.join("|"))
h=harness({emu:true,clip:"id\nls\n"})
h.run("paste")
await tick();await tick();await tick()
check("emulator multi-line Paste asks first",h.log.some((l)=>/^confirm:Paste 3 lines/.test(l))&&h.log.includes("emuPaste:id\nls\n"),h.log.join("|"))
h=harness({emu:true,clip:"id\nls\n",confirm:false})
h.run("paste")
await tick();await tick();await tick()
check("emulator multi-line Paste cancelled sends nothing",!h.log.some((l)=>/^emuPaste:/.test(l))&&h.log.includes("emuFocus"),h.log.join("|"))
h=harness({emu:true,clip:"id\n ls \n"})
h.run("paste_line")
await tick();await tick()
check("emulator Paste as one line joins lines without asking",h.log.includes("emuPaste:id ls")&&!h.log.some((l)=>/^confirm:/.test(l)),h.log.join("|"))
h=harness({emu:true})
h.run("select_all")
check("emulator Select all uses termEmuSelectAll and keeps the xterm focused",h.log[0]==="emuSelectAll"&&h.log.includes("emuFocus"),h.log.join("|"))
h=harness({emu:true})
h.run("clear")
check("emulator Clear uses termEmuClear",h.log.includes("emuClear")&&!h.log.includes("clearOutput")&&h.log.includes("emuFocus"),h.log.join("|"))
h=harness({emu:true})
h.run("find",{selection:"password"})
check("emulator Find opens the bar and searches with termEmuFind",h.log.includes("openSearch")&&h.log.includes("emuFind:password")&&!h.log.includes("runSearch")&&h.termState.searchQuery==="password",h.log.join("|"))
h=harness({emu:true})
h.run("interrupt")
check("emulator Interrupt sends Ctrl+C without touching the input line",h.log.includes('ctl:"\\u0003"')&&!h.log.includes("clearStaged"),h.log.join("|"))
h=harness({emu:true})
h.run("full_terminal")
await tick();await tick()
check("Full terminal mode off: termEmuSetMode(tab,false), then focus the input",h.log.includes("setMode:false")&&h.log.indexOf("input.focus")>h.log.indexOf("setMode:false"),h.log.join("|"))
h=harness({emu:false})
h.run("full_terminal")
check("Full terminal mode does not refocus before the switch settles",h.log.join("|")==="setMode:true",h.log.join("|"))
await tick();await tick()
check("Full terminal mode on: termEmuSetMode(tab,true), then focus the xterm",h.log.includes("setMode:true")&&h.log.includes("emuFocus")&&!h.log.includes("input.focus"),h.log.join("|"))
// line view is unchanged
h=harness({emu:false,clip:"whoami"})
h.run("paste")
await tick();await tick()
check("line view Paste still inserts into the input",h.log.includes("insert:whoami")&&!h.log.some((l)=>/^emuPaste:/.test(l)),h.log.join("|"))
h=harness({emu:false})
h.run("clear")
check("line view Clear still clears the output and focuses the input",h.log.includes("clearOutput")&&h.log.includes("input.focus")&&!h.log.includes("emuClear"),h.log.join("|"))
h=harness({emu:false})
h.run("find",{selection:"x"})
check("line view Find still runs the line search",h.log.includes("runSearch")&&!h.log.some((l)=>/^emuFind/.test(l)),h.log.join("|"))
// context and close
h=harness({emu:true,emuSel:"abc"})
const ctx=h.api.termCtxContext({tab:h.tab,selection:"",target:""})
check("context: emulator fields and xterm selection",ctx.emulator===true&&ctx.emuLocked===false&&ctx.selection==="abc"&&ctx.canEmulate===true)
check("context: line view reports emulator false",harness({emu:false}).api.termCtxContext({tab:{sessionId:"s1"},selection:"q",target:""}).emulator===false)
h=harness({emu:true})
h.api.termCtx.menus=[{el:{remove(){}},info:{tab:h.tab}}]
h.api.termCtxClose(true)
check("Escape close refocuses the xterm in emulator mode",h.log.includes("emuFocus")&&!h.log.includes("input.focus"),h.log.join("|"))
// wiring
check("capture-phase contextmenu listener for the xterm",/panes\.addEventListener\("contextmenu",termCtxOnEmuContextMenu,true\)/.test(SOURCE))
check("bubble pass skips xterm targets, input box path untouched",/if\(inEmu&&e\.eventPhase!==Event\.CAPTURING_PHASE\)return/.test(SOURCE)&&/input\.addEventListener\("contextmenu",termCtxOnInputContextMenu\)/.test(SOURCE))
console.log("")
console.log(passed+" passed, "+failed+" failed")
process.exit(failed?1:0)
})().catch((err)=>{console.log("  FAIL  harness crashed  ->  "+(err&&err.stack||err));console.log("");console.log(passed+" passed, "+(failed+1)+" failed");process.exit(1)})
