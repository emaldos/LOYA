// Full terminal mode: a tab rendered by xterm.js (UI/vendor/xterm, loaded locally) instead of the line view, so full-screen
// programs (the operator's own Claude Code / Codex CLI, vim, htop, less, ssh, msfconsole) draw and take keys as in a real
// terminal. Every keystroke goes raw to the PTY (terminal.write), every output chunk goes raw to xterm, and xterm's cols x rows
// size the PTY (terminal.resize: TIOCSWINSZ on Linux, ResizePseudoConsole on Windows). The session is switched to raw on the
// backend (terminal.set_raw), so it stops answering cursor queries for the line view: xterm answers them itself.
// CLI tabs (tab.rawInput, ext-cli-launch.js) always use it. Other tabs use it when toggled in the tab menu or the right-click
// Session submenu, or for every new session when Settings > Terminal "Use full terminal mode for all new sessions" is on.
// The DOM renderer is used (the WebGL addon is not vendored: GPU issues on WebKitGTK). The pure helpers between the markers are
// loaded by tests/js/terminal_emu.js.
// ---- emu pure start
const TERM_EMU_SCROLLBACK=10000
const TERM_EMU_ANSI=["black","red","green","yellow","blue","magenta","cyan","white"]
// The mode a tab should be in: CLI tabs always; an explicit per-tab choice next; else the "all new sessions" setting.
function termEmuWants(tab,defaultOn){
if(!tab)return false
if(tab.rawInput)return true
if(tab.emulator===true||tab.emulator===false)return tab.emulator
return !!defaultOn
}
function termEmuIsLocked(tab){return !!(tab&&tab.rawInput)}
// The few keys LOYA keeps while the emulator has focus (like VS Code's terminal): Ctrl+Shift+C copies the selection,
// Ctrl+Shift+V pastes, Ctrl+Shift+F opens the search bar. Everything else, Ctrl+C / Ctrl+K / Ctrl+F / Esc / Tab included,
// goes to the program.
function termEmuKeyAction(e){
if(!e||e.type!=="keydown"||!e.ctrlKey||!e.shiftKey||e.altKey||e.metaKey)return "pass"
const k=String(e.key||"").toLowerCase()
if(k==="c"||e.code==="KeyC")return "copy"
if(k==="v"||e.code==="KeyV")return "paste"
if(k==="f"||e.code==="KeyF")return "find"
return "pass"
}
// The xterm theme from the app's theme tokens. read(name) returns a CSS custom property value ("" when unset).
// The background stays transparent so the panel's glass shows through, as in the line view.
function termEmuTheme(read){
const v=(name,fallback)=>{const x=String(read(name)||"").trim();return x||fallback}
const fg=v("--text","#eaf6ff")
const t={foreground:fg,background:"rgba(0,0,0,0)",cursor:fg,cursorAccent:v("--bg","#05060a"),selectionBackground:v("--accent-a-soft","rgba(59,130,246,0.35)"),selectionInactiveBackground:v("--accent-b-soft","rgba(168,85,247,0.2)")}
const defaults={black:"#6b7280",red:"#f87171",green:"#4ade80",yellow:"#facc15",blue:"#60a5fa",magenta:"#e879f9",cyan:"#22d3ee",white:"#e5e7eb"}
TERM_EMU_ANSI.forEach((name)=>{
const cap=name.charAt(0).toUpperCase()+name.slice(1)
t[name]=v("--ansi-"+name,defaults[name])
t["bright"+cap]=v("--ansi-br"+name,t[name])
})
return t
}
// Line view text to seed a tab switched into full terminal mode: xterm needs CR LF to start each line at column 0.
function termEmuSeedText(text){
return String(text||"").replace(/\r?\n/g,"\r\n")
}
// LOYA's job result markers can still arrive for a command started in the line view before the switch.
const TERM_EMU_JOB_RE=/__LOYA_JOB__[0-9a-z]+\|-?\d+\|[^|\r\n]*__END__\r?\n?/g
function termEmuStripMarkers(text){
const s=String(text||"")
return s.indexOf("__LOYA_JOB__")<0?s:s.replace(TERM_EMU_JOB_RE,"")
}
// Search decorations must be #RRGGBB.
const TERM_EMU_SEARCH_DECOR={matchBackground:"#6b5a12",matchBorder:"#a08a2a",matchOverviewRuler:"#d4b106",activeMatchBackground:"#b8860b",activeMatchBorder:"#ffd54a",activeMatchColorOverviewRuler:"#ffd54a"}
function termEmuSearchOptions(regex,incremental){
return {regex:!!regex,caseSensitive:false,wholeWord:false,incremental:!!incremental,decorations:TERM_EMU_SEARCH_DECOR}
}
// ---- emu pure end
const termEmu={observer:null,themeTimer:null}
// xterm.css (vendored, local) is linked from here, before terminal.css rules that refine it, so main.html keeps only css/ links.
;(function termEmuLinkCss(){
if(typeof document==="undefined"||!document.head||document.getElementById("xtermVendorCss"))return
const link=document.createElement("link")
link.id="xtermVendorCss";link.rel="stylesheet";link.href="../vendor/xterm/xterm.css"
const ours=document.querySelector('link[href$="css/terminal.css"]')
if(ours)document.head.insertBefore(link,ours);else document.head.appendChild(link)
})()
function termEmuAvailable(){return typeof Terminal==="function"&&typeof FitAddon!=="undefined"}
function termEmuOn(tab){return !!(tab&&tab.emu&&tab.emu.term)}
function termEmuLocked(tab){return termEmuIsLocked(tab)}
function termEmuReadVar(name){
try{return getComputedStyle(document.documentElement).getPropertyValue(name)}catch(e){return ""}
}
function termEmuFont(){
const probe=document.querySelector(".terminal-output")||document.documentElement
let family=""
try{family=getComputedStyle(probe).fontFamily}catch(e){}
const size=(typeof termState!=="undefined"&&termState.fontSize)||12
return {family:family||"monospace",size}
}
function termEmuSend(tab,data){
if(!tab||tab.dead||!data)return
bridgeCall("terminal.write",[tab.sessionId,data]).then(()=>{if(typeof termWakePolling==="function")termWakePolling()}).catch((err)=>console.error("terminal write failed",err))
}
// Creates the xterm for a tab (not yet opened into the DOM: writes before open are kept and drawn on open).
function termEmuEnsure(tab){
if(termEmuOn(tab))return tab.emu
if(!termEmuAvailable())return null
const font=termEmuFont()
const cols=tab.cols>=20?tab.cols:80,rows=tab.rows>=5?tab.rows:24
const platform=typeof termState!=="undefined"?termState.platform:""
const opts={allowProposedApi:true,scrollback:TERM_EMU_SCROLLBACK,cols,rows,fontFamily:font.family,fontSize:font.size,lineHeight:1.1,cursorBlink:true,theme:termEmuTheme(termEmuReadVar),drawBoldTextInBrightColors:true,minimumContrastRatio:4.5,rightClickSelectsWord:false,altClickMovesCursor:true}
if(platform==="windows")opts.windowsPty={backend:"conpty"}
const term=new Terminal(opts)
const fit=new FitAddon.FitAddon()
term.loadAddon(fit)
let search=null
if(typeof SearchAddon!=="undefined"){search=new SearchAddon.SearchAddon();term.loadAddon(search)}
if(typeof Unicode11Addon!=="undefined"){try{term.loadAddon(new Unicode11Addon.Unicode11Addon());term.unicode.activeVersion="11"}catch(e){}}
// Ctrl+click opens a link in the browser (a plain click stays a click for the program).
if(typeof WebLinksAddon!=="undefined")term.loadAddon(new WebLinksAddon.WebLinksAddon((ev,uri)=>{if(ev&&(ev.ctrlKey||ev.metaKey))bridgeCall("notes.open_url",[uri]).catch(()=>{})}))
const host=document.createElement("div")
host.className="terminal-emu-host"
host.dataset.session=tab.sessionId
// Typing in the emulator never reaches the app's own shortcuts (Ctrl+K palette, Ctrl+F, page keys, the panel's keys):
// xterm handles the key on its textarea first, then the event stops here instead of bubbling to the panel and document.
;["keydown","keypress","keyup"].forEach((type)=>host.addEventListener(type,(e)=>e.stopPropagation()))
tab.emu={term,fit,search,host,opened:false,sent:"",searchResults:null}
term.onData((d)=>termEmuSend(tab,d))
term.onBinary((d)=>termEmuSend(tab,d))
term.attachCustomKeyEventHandler((e)=>termEmuKey(tab,e))
if(search&&search.onDidChangeResults)search.onDidChangeResults((r)=>{tab.emu.searchResults=r;termEmuSearchStatus(tab)})
termEmuWatchTheme()
return tab.emu
}
function termEmuKey(tab,e){
const action=termEmuKeyAction(e)
if(action==="pass")return true
e.preventDefault()
if(action==="copy"){
const text=termEmuSelection(tab)
if(text&&typeof termCtxCopyText==="function")termCtxCopyText(text)
}else if(action==="paste"){
if(typeof termCtxPaste==="function")termCtxPaste(false,tab)
}else if(action==="find"){
if(typeof termOpenSearch==="function")termOpenSearch()
}
return false
}
// Shows the tab's xterm in a pane (the line view's stream nodes are hidden by CSS while .term-emu is set).
function termEmuMount(pane,tab){
const emu=termEmuEnsure(tab)
if(!emu||!pane||!pane.out)return false
pane.out.classList.add("term-emu")
Array.from(pane.out.querySelectorAll(":scope > .terminal-emu-host")).forEach((h)=>{if(h!==emu.host)h.remove()})
if(emu.host.parentNode!==pane.out)pane.out.appendChild(emu.host)
if(!emu.opened){emu.term.open(emu.host);emu.opened=true}
termEmuFit(tab)
return true
}
function termEmuUnmount(pane){
if(!pane||!pane.out)return
pane.out.classList.remove("term-emu")
Array.from(pane.out.querySelectorAll(":scope > .terminal-emu-host")).forEach((h)=>h.remove())
}
// Fits xterm to its pane and sizes the PTY to match (the same terminal.resize path the line view uses).
function termEmuFit(tab){
const emu=tab&&tab.emu
if(!emu||!emu.opened||!emu.host.isConnected||!emu.host.clientWidth||!emu.host.clientHeight)return
const dims=emu.fit.proposeDimensions()
if(dims&&isFinite(dims.cols)&&isFinite(dims.rows)&&dims.cols>0&&dims.rows>0&&(dims.cols!==emu.term.cols||dims.rows!==emu.term.rows)){
try{emu.fit.fit()}catch(e){}
}
const cols=emu.term.cols,rows=emu.term.rows
tab.cols=cols;tab.rows=rows
const key=cols+"x"+rows
if(emu.sent===key||tab.dead)return
emu.sent=key
bridgeCall("terminal.resize",[tab.sessionId,cols,rows]).catch(()=>{})
}
function termEmuWrite(tab,text){
const emu=termEmuEnsure(tab)
if(!emu)return false
const clean=termEmuStripMarkers(text)
if(clean)emu.term.write(clean)
return true
}
function termEmuDispose(tab){
const emu=tab&&tab.emu
if(!emu)return
tab.emu=null
try{emu.host.remove()}catch(e){}
try{emu.term.dispose()}catch(e){}
}
function termEmuFocus(tab){if(termEmuOn(tab))tab.emu.term.focus()}
function termEmuSelection(tab){return termEmuOn(tab)&&tab.emu.term.hasSelection()?tab.emu.term.getSelection():""}
function termEmuSelectAll(tab){if(termEmuOn(tab))tab.emu.term.selectAll()}
function termEmuClear(tab){if(termEmuOn(tab)){tab.emu.term.clear();termEmuFocus(tab)}}
function termEmuPaste(tab,text){if(termEmuOn(tab)&&text)tab.emu.term.paste(String(text))}
// Plain text of the scrollback and screen, for Copy all output and Send session to a note.
function termEmuText(tab){
if(!termEmuOn(tab))return ""
const buf=tab.emu.term.buffer.active
const lines=[]
for(let i=0;i<buf.length;i++){const line=buf.getLine(i);if(!line)continue;if(line.isWrapped&&lines.length)lines[lines.length-1]+=line.translateToString(true);else lines.push(line.translateToString(true))}
return lines.join("\n").replace(/\s+$/,"")
}
function termEmuSearchStatus(tab){
const status=document.getElementById("terminalSearchStatus")
if(!status||!tab||!tab.emu)return
const r=tab.emu.searchResults
if(!termState.searchQuery){status.textContent="";return}
if(!r||!r.resultCount){status.textContent="no matches";return}
status.textContent=(r.resultIndex>=0?r.resultIndex+1:"?")+" / "+r.resultCount
}
// opts: {prev, incremental}. Uses the search bar's query and regex toggle.
function termEmuFind(tab,query,opts){
if(!termEmuOn(tab)||!tab.emu.search)return false
const search=tab.emu.search
const q=String(query===undefined?termState.searchQuery:query||"")
if(!q){search.clearDecorations();tab.emu.searchResults=null;termEmuSearchStatus(tab);return false}
const o=termEmuSearchOptions(termState.searchRegex,opts&&opts.incremental)
let hit=false
try{hit=opts&&opts.prev?search.findPrevious(q,o):search.findNext(q,o)}catch(e){hit=false}
termEmuSearchStatus(tab)
return hit
}
function termEmuFindPrev(tab,query){return termEmuFind(tab,query,{prev:true})}
function termEmuClearSearch(tab){
if(!termEmuOn(tab)||!tab.emu.search)return
tab.emu.search.clearDecorations()
tab.emu.term.clearSelection()
tab.emu.searchResults=null
}
// Switches a tab between the line view and full terminal mode. CLI tabs cannot leave it.
function termEmuSetMode(tab,on){
on=!!on
if(!tab)return Promise.resolve(false)
if(!on&&termEmuIsLocked(tab))return Promise.resolve(true)
if(on===termEmuOn(tab)&&on===!!tab.emulator)return Promise.resolve(on)
if(on&&!termEmuAvailable()){showToast("Full terminal mode is not available in this build","error");return Promise.resolve(false)}
tab.emulator=on
return bridgeCall("terminal.set_raw",[tab.sessionId,on]).catch(()=>null).then((res)=>{
if(on){
const seed=typeof termStripJobMarkers==="function"?termStripJobMarkers(tab.buffer||"",tab.shellId):(tab.buffer||"")
termEmuEnsure(tab)
if(seed)tab.emu.term.write(termEmuSeedText(seed))
tab.pendingCapture=null
if(res&&res.backend==="pipe")showToast("This session has no pseudoconsole, so full-screen programs may not draw correctly. Open a new session to use full terminal mode.","error")
}else{
const text=termEmuText(tab)
termEmuDispose(tab)
tab.buffer=text?text+"\n":""
tab.visible=tab.buffer
tab.pendingRaw=""
tab.listings=[]
tab.renderedLen=0
tab.ansiClasses=[]
const pane=typeof termPaneForSession==="function"?termPaneForSession(tab.sessionId):null
if(pane){termEmuUnmount(pane);pane.renderedTabId=null}
if(typeof termInvalidateRender==="function")termInvalidateRender(tab)
}
if(typeof termRenderSession==="function")termRenderSession(tab.sessionId)
termEmuSyncChrome()
if(typeof termScheduleSizeSync==="function")termScheduleSizeSync()
return on
})
}
// The panel hides the line input box and the job blocks button while the focused tab is in full terminal mode.
function termEmuSyncChrome(){
const panel=document.getElementById("terminalPanel")
if(!panel||typeof termFindTab!=="function")return
const tab=termFindTab(termState.activeId)
panel.classList.toggle("term-emu-active",!!(tab&&tab.emulator&&termEmuOn(tab)))
}
function termEmuApplyFont(){
if(typeof termState==="undefined")return
const font=termEmuFont()
termState.tabs.forEach((tab)=>{
if(!termEmuOn(tab))return
tab.emu.term.options.fontFamily=font.family
tab.emu.term.options.fontSize=font.size
termEmuFit(tab)
})
}
function termEmuApplyTheme(){
if(typeof termState==="undefined")return
const theme=termEmuTheme(termEmuReadVar)
termState.tabs.forEach((tab)=>{if(termEmuOn(tab))tab.emu.term.options.theme=theme})
}
// A theme switch (dark / light / custom tokens) recolours every open emulator.
function termEmuWatchTheme(){
if(termEmu.observer||typeof MutationObserver!=="function")return
termEmu.observer=new MutationObserver(()=>{
if(termEmu.themeTimer)clearTimeout(termEmu.themeTimer)
termEmu.themeTimer=setTimeout(()=>{termEmu.themeTimer=null;termEmuApplyTheme()},60)
})
termEmu.observer.observe(document.documentElement,{attributes:true,attributeFilter:["data-theme","style","class"]})
}
