// Full terminal mode (UI/js/components/terminal-emu.js): the mode switch, key routing (app shortcuts stay out while the
// emulator has focus), the raw write / resize bridge calls, the "all new sessions" setting and the terminal.js hooks.
const fs=require("fs")
const path=require("path")
const ROOT=path.resolve(__dirname,"..","..")
const read=(...p)=>fs.readFileSync(path.join(ROOT,...p),"utf8")
const SOURCE=read("UI","js","components","terminal-emu.js")
const TERMINAL=read("UI","js","components","terminal.js")
const MENU=read("UI","js","components","terminal-menu.js")
const CLI=read("UI","js","components","ext-cli-launch.js")
const HTML=read("UI","windows","main.html")
const SETTINGS_HTML=read("UI","pages","settings.html")
const SETTINGS_JS=read("UI","js","pages","settings.js")
const CSS=read("UI","css","terminal.css")
const PALETTE=read("UI","js","components","palette.js")
const SHORTCUTS=read("UI","js","components","shortcuts.js")
let passed=0,failed=0
function check(name,condition,detail){
if(condition){passed++;return}
failed++
console.log("  FAIL  "+name+(detail?"  ->  "+detail:""))
}
// ---- pure helpers
const pure=SOURCE.slice(SOURCE.indexOf("// ---- emu pure start"),SOURCE.indexOf("// ---- emu pure end"))
const P=new Function(pure+";return{termEmuWants,termEmuIsLocked,termEmuKeyAction,termEmuTheme,termEmuSeedText,termEmuStripMarkers,termEmuSearchOptions,TERM_EMU_SCROLLBACK}")()
check("scrollback is 10000 lines",P.TERM_EMU_SCROLLBACK===10000)
check("CLI tabs always want full terminal mode",P.termEmuWants({rawInput:true,emulator:false},false)===true)
check("an explicit per-tab choice wins over the setting",P.termEmuWants({emulator:false},true)===false&&P.termEmuWants({emulator:true},false)===true)
check("the setting decides for a new tab (default off)",P.termEmuWants({},false)===false&&P.termEmuWants({},true)===true)
check("no tab: no emulator",P.termEmuWants(null,true)===false)
check("only CLI tabs are locked",P.termEmuIsLocked({rawInput:true})&&!P.termEmuIsLocked({emulator:true}))
const key=(k,mods)=>Object.assign({type:"keydown",key:k,code:"Key"+k.toUpperCase(),ctrlKey:false,shiftKey:false,altKey:false,metaKey:false},mods||{})
check("Ctrl+Shift+C copies",P.termEmuKeyAction(key("C",{ctrlKey:true,shiftKey:true}))==="copy")
check("Ctrl+Shift+V pastes",P.termEmuKeyAction(key("V",{ctrlKey:true,shiftKey:true}))==="paste")
check("Ctrl+Shift+F finds",P.termEmuKeyAction(key("F",{ctrlKey:true,shiftKey:true}))==="find")
;["c","k","f","l","v","d","z","r"].forEach((k)=>check("Ctrl+"+k.toUpperCase()+" goes to the program",P.termEmuKeyAction(key(k,{ctrlKey:true}))==="pass"))
check("Esc / Tab / arrows go to the program",["Escape","Tab","ArrowUp"].every((k)=>P.termEmuKeyAction({type:"keydown",key:k,code:k})==="pass"))
check("Shift+Tab goes to the program",P.termEmuKeyAction({type:"keydown",key:"Tab",code:"Tab",shiftKey:true})==="pass")
check("keyup is never an app action",P.termEmuKeyAction(key("C",{type:"keyup",ctrlKey:true,shiftKey:true}))==="pass")
check("Ctrl+Alt+Shift+C passes",P.termEmuKeyAction(key("C",{ctrlKey:true,shiftKey:true,altKey:true}))==="pass")
const vars={"--text":"#111111","--bg":"#fafafa","--ansi-red":"#dc2626","--ansi-brred":"#ef4444"}
const theme=P.termEmuTheme((n)=>vars[n]||"")
check("theme: foreground from --text",theme.foreground==="#111111"&&theme.cursor==="#111111")
check("theme: transparent background (the glass shows)",theme.background==="rgba(0,0,0,0)")
check("theme: ANSI colours from the tokens",theme.red==="#dc2626"&&theme.brightRed==="#ef4444")
check("theme: every ANSI key is set",["black","red","green","yellow","blue","magenta","cyan","white"].every((c)=>theme[c]&&theme["bright"+c[0].toUpperCase()+c.slice(1)]))
check("seed text uses CR LF",P.termEmuSeedText("a\nb\r\nc")==="a\r\nb\r\nc")
check("job markers are stripped",P.termEmuStripMarkers("x__LOYA_JOB__j1ab|0|/tmp__END__\ny")==="xy")
check("plain output is untouched",P.termEmuStripMarkers("\x1b[2J\x1b[Hhello")==="\x1b[2J\x1b[Hhello")
const so=P.termEmuSearchOptions(true,true)
check("search options: regex, incremental, decorations with #RRGGBB",so.regex&&so.incremental&&Object.values(so.decorations).every((c)=>/^#[0-9a-f]{6}$/i.test(c))&&so.decorations.matchOverviewRuler&&so.decorations.activeMatchColorOverviewRuler)
// ---- DOM side with a fake xterm
function makeEnv(platform){
const calls=[]
const listeners=[]
const terms=[]
function el(){
return {classList:{s:new Set(),add(c){this.s.add(c)},remove(c){this.s.delete(c)},contains(c){return this.s.has(c)},toggle(c,on){on?this.s.add(c):this.s.delete(c)}},dataset:{},children:[],isConnected:true,clientWidth:800,clientHeight:400,
addEventListener(type,fn){listeners.push({el:this,type,fn})},remove(){this.removed=true},querySelectorAll(){return []},appendChild(c){this.children.push(c);c.parentNode=this}}
}
class FakeTerminal{
constructor(opts){this.opts=opts;this.options=Object.assign({},opts);this.cols=opts.cols;this.rows=opts.rows;this.written=[];this.sel="";terms.push(this);this.addons=[];this.unicode={activeVersion:"6"};this.buffer={active:{length:2,getLine:(i)=>({isWrapped:false,translateToString:()=>["$ ls","a b"][i]})}}}
loadAddon(a){this.addons.push(a);if(a.activate)a.activate(this)}
onData(fn){this.dataFn=fn}
onBinary(fn){this.binFn=fn}
attachCustomKeyEventHandler(fn){this.keyFn=fn}
open(host){this.openedIn=host}
write(t){this.written.push(t)}
focus(){this.focused=true}
hasSelection(){return !!this.sel}
getSelection(){return this.sel}
selectAll(){this.all=true}
clear(){this.cleared=true}
paste(t){this.pasted=t}
clearSelection(){}
dispose(){this.disposed=true}
resize(c,r){this.cols=c;this.rows=r}
}
class Fit{activate(t){this.t=t}proposeDimensions(){return {cols:120,rows:33}}fit(){this.t.resize(120,33)}}
class Search{constructor(){this.found=[]}findNext(q,o){this.found.push(["next",q,o]);return true}findPrevious(q,o){this.found.push(["prev",q,o]);return true}clearDecorations(){this.cleared=true}onDidChangeResults(fn){this.cb=fn}}
const panel=el()
const doc={documentElement:el(),createElement:()=>el(),querySelector:()=>null,getElementById:(id)=>id==="terminalPanel"?panel:null}
const tabs=[]
const termState={platform,fontSize:14,tabs,activeId:"s1",searchQuery:"",searchRegex:false}
const env={Terminal:FakeTerminal,FitAddon:{FitAddon:Fit},SearchAddon:{SearchAddon:Search},Unicode11Addon:{Unicode11Addon:class{}},WebLinksAddon:{WebLinksAddon:class{constructor(h){this.h=h}}},document:doc,getComputedStyle:()=>({getPropertyValue:()=>"",fontFamily:"JetBrains Mono"}),MutationObserver:class{observe(){}},
bridgeCall:(m,a)=>{calls.push([m,a]);return Promise.resolve(m==="terminal.set_raw"?{raw:a[1],backend:platform==="windows"?"conpty":"pty"}:true)},
termState,termWakePolling:()=>{},termFindTab:(id)=>tabs.find((t)=>t.sessionId===id),showToast:(m,k)=>calls.push(["toast",m,k]),
termCtxCopyText:(t)=>calls.push(["copy",t]),termCtxPaste:(one,tab)=>calls.push(["paste",one,tab&&tab.sessionId]),termOpenSearch:()=>calls.push(["search"])}
const names=Object.keys(env)
const api=new Function(...names,SOURCE+";return{termEmuEnsure,termEmuMount,termEmuOn,termEmuFit,termEmuWrite,termEmuSetMode,termEmuSelection,termEmuPaste,termEmuClear,termEmuSelectAll,termEmuFind,termEmuText,termEmuLocked,termEmuApplyFont,termEmuSyncChrome,termEmuDispose}")(...names.map((n)=>env[n]))
return {api,calls,listeners,terms,tabs,termState,panel,el}
}
;(async()=>{
const E=makeEnv("linux")
const tab={sessionId:"s1",shellId:"zsh",cols:100,rows:30,emulator:true,buffer:""}
E.tabs.push(tab)
const emu=E.api.termEmuEnsure(tab)
const t=E.terms[0]
check("xterm options: scrollback, proposed API (unicode11 + search decorations), font size from the setting",t.opts.scrollback===10000&&t.opts.allowProposedApi===true&&t.opts.fontSize===14)
check("xterm starts at the tab's grid",t.opts.cols===100&&t.opts.rows===30)
check("no windowsPty option on Linux",!t.opts.windowsPty)
check("unicode 11 widths are active",t.unicode.activeVersion==="11")
check("fit, search, unicode11 and web links addons load",t.addons.length===4)
// raw input
t.dataFn("\x1b[A")
t.dataFn("\x03")
check("keys go raw to terminal.write",E.calls.filter((c)=>c[0]==="terminal.write").map((c)=>c[1][1]).join("|")==="\x1b[A|\x03"&&E.calls.every((c)=>c[0]!=="terminal.write"||c[1][0]==="s1"))
// key routing
const stops=E.listeners.filter((l)=>l.el===emu.host)
check("the host stops keydown, keypress and keyup from bubbling to app shortcuts",["keydown","keypress","keyup"].every((type)=>stops.some((l)=>l.type===type)))
let stopped=0
stops.forEach((l)=>l.fn({stopPropagation(){stopped++}}))
check("each key listener calls stopPropagation",stopped===3)
const ev=(k,mods)=>Object.assign({type:"keydown",key:k,code:"Key"+k.toUpperCase(),ctrlKey:true,shiftKey:false,altKey:false,metaKey:false,preventDefault(){this.prevented=true}},mods||{})
check("Ctrl+K is handled by xterm (sent to the program)",t.keyFn(ev("k"))===true)
check("Ctrl+F is handled by xterm",t.keyFn(ev("f"))===true)
check("Ctrl+C is handled by xterm even with a selection",(t.sel="abc",t.keyFn(ev("c"))===true))
const cc=ev("c",{shiftKey:true})
check("Ctrl+Shift+C is taken by LOYA and copies the selection",t.keyFn(cc)===false&&cc.prevented&&E.calls.some((c)=>c[0]==="copy"&&c[1]==="abc"))
check("Ctrl+Shift+V pastes into this tab",t.keyFn(ev("v",{shiftKey:true}))===false&&E.calls.some((c)=>c[0]==="paste"&&c[1]===false&&c[2]==="s1"))
check("Ctrl+Shift+F opens the search bar",t.keyFn(ev("f",{shiftKey:true}))===false&&E.calls.some((c)=>c[0]==="search"))
// mount + fit -> resize
const pane={out:E.el()}
E.api.termEmuMount(pane,tab)
check("mount opens xterm in the host inside the pane output",t.openedIn===emu.host&&pane.out.children.indexOf(emu.host)>=0&&pane.out.classList.contains("term-emu"))
const resizes=()=>E.calls.filter((c)=>c[0]==="terminal.resize")
check("fit sizes the PTY to xterm's cols x rows",resizes().length===1&&resizes()[0][1].join(",")==="s1,120,33"&&tab.cols===120&&tab.rows===33)
E.api.termEmuFit(tab)
check("an unchanged size is not sent again",resizes().length===1)
// output, selection, clear, paste, text
E.api.termEmuWrite(tab,"\x1b[2J__LOYA_JOB__jx|0|/__END__hi")
check("output goes raw to xterm, minus job markers",t.written[t.written.length-1]==="\x1b[2Jhi")
E.api.termEmuPaste(tab,"a\nb")
check("paste goes through xterm (bracketed paste)",t.pasted==="a\nb")
E.api.termEmuClear(tab)
check("clear uses xterm.clear",t.cleared===true)
check("plain text of the buffer",E.api.termEmuText(tab)==="$ ls\na b")
E.termState.searchQuery="ls"
E.api.termEmuFind(tab,"ls",{prev:true})
check("find uses the search addon",emu.search.found.length===1&&emu.search.found[0][0]==="prev")
// mode switch
const plain={sessionId:"s2",shellId:"bash",cols:80,rows:24,buffer:"$ id\nuid=0(root)\n"}
E.tabs.push(plain)
const on=await E.api.termEmuSetMode(plain,true)
check("switching on asks the backend for raw mode",on===true&&E.calls.some((c)=>c[0]==="terminal.set_raw"&&c[1][0]==="s2"&&c[1][1]===true))
check("switching on seeds xterm with the line view output",E.terms[1]&&E.terms[1].written[0]==="$ id\r\nuid=0(root)\r\n")
const off=await E.api.termEmuSetMode(plain,false)
check("switching off restores the line view with the screen text",off===false&&!E.api.termEmuOn(plain)&&plain.buffer==="$ ls\na b\n"&&E.terms[1].disposed)
check("switching off tells the backend",E.calls.some((c)=>c[0]==="terminal.set_raw"&&c[1][0]==="s2"&&c[1][1]===false))
const cli={sessionId:"s3",rawInput:true,emulator:true,buffer:""}
E.tabs.push(cli)
E.api.termEmuEnsure(cli)
const stay=await E.api.termEmuSetMode(cli,false)
check("a CLI tab cannot leave full terminal mode",stay===true&&E.api.termEmuOn(cli)&&E.api.termEmuLocked(cli))
E.api.termEmuSyncChrome()
check("chrome: the panel hides the input box while the focused tab is an emulator",E.panel.classList.contains("term-emu-active"))
E.termState.activeId="s2"
E.api.termEmuSyncChrome()
check("chrome: the input box comes back for a line view tab",!E.panel.classList.contains("term-emu-active"))
// Windows: same calls, plus the ConPTY hint
const W=makeEnv("windows")
const wt={sessionId:"w1",cols:90,rows:25,emulator:true}
W.tabs.push(wt)
W.api.termEmuEnsure(wt)
check("Windows: xterm is told it runs on ConPTY",W.terms[0].opts.windowsPty&&W.terms[0].opts.windowsPty.backend==="conpty")
W.terms[0].dataFn("\r")
W.api.termEmuMount({out:W.el()},wt)
check("Windows: the same write and resize bridge calls",W.calls.some((c)=>c[0]==="terminal.write"&&c[1][1]==="\r")&&W.calls.some((c)=>c[0]==="terminal.resize"&&c[1].join(",")==="w1,120,33"))
// ---- source hooks
check("main.html loads the vendored xterm locally, before terminal-emu.js",/vendor\/xterm\/xterm\.js/.test(HTML)&&HTML.indexOf("vendor/xterm/xterm.js")<HTML.indexOf("terminal-emu.js")&&/\.\.\/vendor\/xterm\/xterm\.css/.test(SOURCE)&&!/https?:\/\/[^"]*xterm/.test(HTML))
check("main.html does not load the WebGL addon",!/addon-webgl/.test(HTML))
check("terminal.create gets the emulator flag",/bridgeCall\("terminal\.create",\[[^\]]*opts\.name\|\|"",emulator\]/.test(TERMINAL))
check("new tabs follow the setting (termState.emuDefault)",/termEmuWants\(\{rawInput:opts\.rawInput,emulator:opts\.emulator\},termState\.emuDefault\)/.test(TERMINAL))
check("the setting is read from terminal settings",/termState\.emuDefault=!!s\.full_terminal_default/.test(TERMINAL))
check("output of an emulator tab goes to xterm",/if\(tab\.emulator&&typeof termEmuWrite==="function"&&termEmuWrite\(tab,text\)\)/.test(TERMINAL))
check("size sync fits emulator tabs instead of measuring cells",/if\(tab\.emulator\)\{if\(termIsEmu\(tab\)\)termEmuFit\(tab\)/.test(TERMINAL))
check("runs into an emulator tab are typed raw (no job markers)",/if\(runTab&&runTab\.emulator\)return bridgeCall\("terminal\.write",\[id,text\+"\\r"\]\)/.test(TERMINAL))
check("focus goes to the emulator when the tab has one",/function termFocusInput\(\)\{[\s\S]*?termEmuFocus\(tab\)/.test(TERMINAL)&&TERMINAL.split('getElementById("terminalInput").focus()').length-1===TERMINAL.split('if(typeof termFocusInput==="function")termFocusInput();else document.getElementById("terminalInput").focus()').length-1)
check("the tab menu has the Full terminal mode toggle",/label:"Full terminal mode"/.test(TERMINAL))
check("the right-click Session submenu has the toggle",/id:"full_terminal",label:"Full terminal mode"/.test(MENU))
check("search bar routes to the search addon",/if\(termIsEmu\(tab\)\)\{termEmuFind\(tab,termState\.searchQuery,\{incremental:true\}\)/.test(TERMINAL))
check("CLI tabs are created in full terminal mode",/termNewTab\(plan\.shell,\{[^}]*rawInput:true\}\)/.test(CLI))
check("settings page has the checkbox, default off in the backend",/id="setTermFullDefault"/.test(SETTINGS_HTML)&&/Use full terminal mode for all new sessions/.test(SETTINGS_HTML)&&/full_terminal_default:!!\(document\.getElementById\("setTermFullDefault"\)/.test(SETTINGS_JS))
check("CSS hides the input row in full terminal mode",/\.terminal-panel\.term-emu-active \.terminal-input-row/.test(CSS))
// The app-level shortcut handlers that react to Ctrl+K / Ctrl+/ listen in the bubble phase, so the host's stopPropagation keeps them out.
check("palette Ctrl+K listens in the bubble phase",/document\.addEventListener\("keydown",\(e\)=>\{\s*const mod=e\.ctrlKey\|\|e\.metaKey/.test(PALETTE))
check("shortcuts sheet listens in the bubble phase",/document\.addEventListener\("keydown",\(e\)=>\{\s*const active=/.test(SHORTCUTS))
console.log(`${passed} passed, ${failed} failed`)
process.exit(failed?1:0)
})().catch((err)=>{console.log("  FAIL  threw "+(err&&err.stack||err));console.log(`${passed} passed, ${failed+1} failed`);process.exit(1)})
