// Right-click menu for the terminal output (docked right, left or bottom; single or split panes).
// Shift+right-click keeps the engine's own menu. The menu only reuses what the terminal already does (terminal.js):
// it adds no backend calls of its own except the saved text size, which rides on terminal.set_panel_layout.
// Everything above "---- DOM" is pure and covered by tests/js/terminal_context_menu.js.
const TERM_CTX_FONT_DEFAULT=12
const TERM_CTX_FONT_MIN=9
const TERM_CTX_FONT_MAX=22
const TERM_CTX_CVE_RE=/\bCVE-(\d{4})-(\d{4,7})\b/i
const TERM_CTX_URL_RE=/^https?:\/\/[^\s<>"'`]+$/i
const TERM_CTX_ANSI_RE=/\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[PX^_][\s\S]*?\x1b\\|\x1b\[[0-9;?]*[ -\/]*[@-~]|\x1b[()*+][0-9A-Za-z]|\x1b[=>NOM78]/g
// What a piece of selected text can be used for. A CVE id counts when the selection is short and holds one;
// a URL only when the whole selection is one http(s) link (the app only opens web links in the browser).
function termCtxDetect(text){
const value=String(text||"").trim()
const out={text:value,cve:"",url:""}
if(!value)return out
if(value.length<=200){
const m=TERM_CTX_CVE_RE.exec(value)
if(m)out.cve="CVE-"+m[1]+"-"+m[2]
}
const bare=value.replace(/[),.;:!?\]]+$/,"")
if(bare.length<=2048&&TERM_CTX_URL_RE.test(bare))out.url=bare
return out
}
function termCtxStripAnsi(text){
return String(text||"").replace(TERM_CTX_ANSI_RE,"").replace(/\x1b/g,"").replace(/\r+\n/g,"\n").replace(/[^\n]*\r(?!\n)/g,"")
}
// "Paste as one line": every line break becomes a single space, so a multi-line clipboard can never run line by line.
function termCtxOneLine(text){
return String(text||"").split(/\r?\n|\r/).map((line)=>line.trim()).filter(Boolean).join(" ")
}
function termCtxFontStep(current,step){
const now=Math.round(Number(current))||TERM_CTX_FONT_DEFAULT
if(!step)return TERM_CTX_FONT_DEFAULT
return Math.max(TERM_CTX_FONT_MIN,Math.min(TERM_CTX_FONT_MAX,now+step))
}
// Keeps a menu of size w x h inside the viewport with a margin. Opens at (x,y); flips left/up when it would spill.
function termCtxClamp(x,y,w,h,vw,vh,margin){
const m=margin===undefined?8:margin
let left=x,top=y
if(left+w>vw-m)left=Math.max(m,x-w)
if(left+w>vw-m)left=vw-m-w
if(top+h>vh-m)top=Math.max(m,vh-m-h)
return {left:Math.round(Math.max(m,left)),top:Math.round(Math.max(m,top))}
}
// A submenu opens to the right of its row, or to the left of the parent menu when there is no room.
function termCtxSubmenuPos(row,parent,w,h,vw,vh,margin){
const m=margin===undefined?8:margin
let left=parent.right-2
if(left+w>vw-m)left=parent.left-w+2
return termCtxClamp(left,row.top-6,w,h,vw,vh,m)
}
// ctx: {selection, target, hasSession, dead, jobRunning, layout, mode, maximized, fontSize, closedCount, canNote, canCve, canSearch, canOpenUrl, canSplit, canRecord, emulator, emuLocked}
// emulator: the tab runs in full terminal mode (xterm). Ctrl+F and Ctrl+L go to the program there, so those rows drop
// their key hints; there are no job blocks, so Interrupt is offered whenever the session is live.
function termCtxBuildItems(ctx){
const c=ctx||{}
const emu=!!c.emulator
const sel=String(c.selection||"")
const has=!!sel.trim()
const live=!!c.hasSession&&!c.dead
const use=termCtxDetect(has?sel:(c.target||""))
const items=[
{id:"copy",label:"Copy",icon:"copy",key:"Ctrl+Shift+C",disabled:!has},
{id:"copy_all",label:"Copy all output",icon:"copy",disabled:!c.hasOutput},
{id:"paste",label:"Paste",icon:"paste",key:"Ctrl+Shift+V",disabled:!live},
{id:"paste_line",label:"Paste as one line",icon:"paste",disabled:!live},
{id:"select_all",label:"Select all",icon:"text",disabled:emu?!c.hasSession:!c.hasOutput},
{sep:true},
{id:"find",label:has&&sel.length<=200&&!/[\r\n]/.test(sel.trim())?"Find selection":"Find",icon:"search",key:emu?"":"Ctrl+F"},
{id:"clear",label:"Clear",icon:"eraser",key:emu?"":"Ctrl+L",disabled:!c.hasSession},
{id:"interrupt",label:"Interrupt",icon:"stop",key:"Ctrl+C",disabled:!live||(!emu&&!c.jobRunning)}
]
const useItems=[]
if(use.url&&c.canOpenUrl)useItems.push({id:"open_url",label:"Open link",icon:"link",value:use.url})
if(use.cve&&c.canCve)useItems.push({id:"cve",label:"Look up "+use.cve,icon:"bug",value:use.cve})
if(has&&c.canSearch)useItems.push({id:"search_loya",label:"Search in LOYA",icon:"search",value:sel.trim().slice(0,200)})
if(has&&c.canNote)useItems.push({id:"note",label:"Send selection to a note...",icon:"edit",value:sel})
if(useItems.length){items.push({sep:true});items.push(...useItems)}
const single=(c.layout||"single")==="single"
const session=[
{id:"new",label:"New session",icon:"add"},
{id:"new_pick",label:"New session with...",icon:"command-line"},
{id:"duplicate",label:"Duplicate session",icon:"copy",disabled:!c.hasSession},
{id:"rename",label:"Rename session",icon:"edit",disabled:!c.hasSession},
{id:"full_terminal",label:"Full terminal mode",icon:"command-line",checkbox:true,checked:emu,disabled:!c.hasSession||!!c.emuLocked||c.canEmulate===false},
{sep:true},
single?{id:"split",label:"Split side by side",icon:"flow-split",disabled:!c.canSplit}:{id:"unsplit",label:"Single pane",icon:"flow-split"},
{id:"split_pick",label:"Split layout...",icon:"table",disabled:!c.canSplit},
{sep:true},
{id:"send_session",label:"Send session to a note...",icon:"save",disabled:!c.hasOutput},
{id:"reopen",label:"Reopen closed session",icon:"refresh",key:"Ctrl+Shift+T",disabled:!c.closedCount},
{id:"close",label:"Close session",icon:"close",danger:true,disabled:!c.hasSession}
]
const size=Math.round(Number(c.fontSize))||TERM_CTX_FONT_DEFAULT
const font=[
{id:"font_up",label:"Larger",icon:"font-bigger",disabled:size>=TERM_CTX_FONT_MAX},
{id:"font_down",label:"Smaller",icon:"font-smaller",disabled:size<=TERM_CTX_FONT_MIN},
{id:"font_reset",label:"Reset ("+TERM_CTX_FONT_DEFAULT+" px)",icon:"text",disabled:size===TERM_CTX_FONT_DEFAULT}
]
const modes=[["right","Dock right","align-right"],["left","Dock left","align-left"],["bottom","Dock bottom","align-center"]]
const dock=modes.map(([mode,label,icon])=>({id:"dock_"+mode,label,icon,checked:c.mode===mode}))
dock.push({sep:true})
dock.push({id:"maximize",label:c.maximized?"Restore panel":"Maximize panel",icon:c.maximized?"restore":"maximize",key:"Ctrl+Shift+Enter"})
items.push({sep:true})
items.push({id:"session",label:"Session",icon:"command-line",submenu:session})
items.push({id:"font",label:"Text size ("+size+" px)",icon:"text",submenu:font})
items.push({id:"dock",label:"Panel position",icon:"grip",submenu:dock})
return items
}
// Next enabled row index from `from` in direction `dir` (wraps). -1 when nothing is enabled.
function termCtxNextIndex(items,from,dir){
const n=items.length
if(!n)return -1
if(from<0||from>=n)from=dir>0?-1:n
for(let k=1;k<=n;k++){
const i=((from+dir*k)%n+n)%n
const it=items[i]
if(it&&!it.sep&&!it.disabled)return i
}
return -1
}
// ---- DOM
let termCtx={menus:[],opened:null,hoverTimer:null}
function termCtxEsc(s){
return String(s===undefined||s===null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;")
}
// Full terminal mode (terminal-emu.js). Every hook is optional: without it the tab is in the line view.
function termCtxEmu(tab){
return !!tab&&typeof termEmuOn==="function"&&!!termEmuOn(tab)
}
// Puts the caret back where the user types: the xterm in full terminal mode, otherwise the input line.
function termCtxRefocus(tab){
if(termCtxEmu(tab)&&typeof termEmuFocus==="function"){termEmuFocus(tab);return}
const input=document.getElementById("terminalInput")
if(input&&termState.open)input.focus()
}
function termCtxFontSize(){
return termState.fontSize||TERM_CTX_FONT_DEFAULT
}
function termCtxApplyFont(size,save){
termState.fontSize=Math.max(TERM_CTX_FONT_MIN,Math.min(TERM_CTX_FONT_MAX,Math.round(Number(size))||TERM_CTX_FONT_DEFAULT))
const panel=document.getElementById("terminalPanel")
if(panel)panel.style.setProperty("--term-font-size",termState.fontSize+"px")
if(typeof termScheduleSizeSync==="function")termScheduleSizeSync()
if(save)bridgeCall("terminal.set_panel_layout",[{font_size:termState.fontSize}]).catch(()=>{})
if(typeof termEmuApplyFont==="function")termEmuApplyFont()
}
// Copy: the async clipboard first (works in WebView2 and WebKitGTK on 127.0.0.1); if it is refused, a hidden
// textarea + execCommand("copy"), which pywebview allows on GTK (javascript_can_access_clipboard).
function termCtxCopyText(text,message){
const value=String(text||"")
if(!value)return Promise.resolve(false)
const done=()=>{if(typeof showToast==="function")showToast(message||"Copied");return true}
const viaField=()=>{
const ta=document.createElement("textarea")
ta.value=value
ta.setAttribute("readonly","")
ta.style.cssText="position:fixed;left:-9999px;top:0;opacity:0"
document.body.appendChild(ta)
ta.select()
let ok=false
try{ok=document.execCommand("copy")}catch(e){ok=false}
ta.remove()
if(ok)return done()
if(typeof showToast==="function")showToast("Could not copy","error")
return false
}
if(navigator.clipboard&&navigator.clipboard.writeText)return navigator.clipboard.writeText(value).then(done).catch(viaField)
return Promise.resolve(viaField())
}
// Paste: WebKitGTK's async readText pops its own "Paste" confirmation, so there a hidden textarea + execCommand("paste")
// goes first; WebView2 reads through navigator.clipboard. Each falls back to the other. Resolves "" when both fail.
function termCtxReadClipboard(){
const viaField=()=>{
const ta=document.createElement("textarea")
ta.style.cssText="position:fixed;left:-9999px;top:0;opacity:0"
document.body.appendChild(ta)
ta.focus()
let ok=false
try{ok=document.execCommand("paste")}catch(e){ok=false}
const value=ta.value
ta.remove()
return ok?value:null
}
const viaAsync=()=>navigator.clipboard&&navigator.clipboard.readText?navigator.clipboard.readText():Promise.reject(new Error("no clipboard"))
const webkit=document.documentElement.classList.contains("engine-webkit")
if(webkit){
const got=viaField()
if(got)return Promise.resolve(got)
return viaAsync().catch(()=>got===null?Promise.reject(new Error("no clipboard")):"")
}
return viaAsync().catch(()=>{const got=viaField();return got===null?Promise.reject(new Error("no clipboard")):got})
}
function termCtxPaste(oneLine,tab){
if(tab===undefined&&typeof termFindTab==="function")tab=termFindTab(termState.activeId)
if(termCtxEmu(tab)){termCtxEmuPaste(oneLine,tab);return}
const input=document.getElementById("terminalInput")
termCtxReadClipboard().then((text)=>{
if(input)input.focus()
if(!text)return
if(oneLine){termInsertAtCursor(termCtxOneLine(text));return}
if(!termState.confirmMultilinePaste||!/[\r\n]/.test(text.trim())){termInsertAtCursor(text);return}
termConfirmMultilinePaste(text)
}).catch(()=>{if(input)input.focus();showToast("Could not read the clipboard - use Ctrl+V","error")})
}
// Full terminal mode: the text goes to the program through xterm's paste (bracketed paste when the program asked for it).
// A multi-line paste asks first, the same as in the line view, since a plain shell still runs each line.
function termCtxEmuPaste(oneLine,tab){
const back=()=>termCtxRefocus(tab)
const send=(text)=>{if(typeof termEmuPaste==="function")termEmuPaste(tab,text);back()}
termCtxReadClipboard().then((text)=>{
if(!text){back();return}
if(oneLine){send(termCtxOneLine(text));return}
if(!termState.confirmMultilinePaste||!/[\r\n]/.test(text.trim())||typeof appConfirm!=="function"){send(text);return}
const count=text.split(/\r?\n/).length
const body=typeof termPastePreviewHtml==="function"?termPastePreviewHtml(text):""
appConfirm("Paste "+count+" lines into the terminal?",{okLabel:"Paste",cancelLabel:"Cancel",wide:true,danger:true,bodyHtml:body}).then((ok)=>{if(ok)send(text);else back()})
}).catch(()=>{back();showToast("Could not read the clipboard - use Ctrl+V","error")})
}
function termCtxPaneAt(target){
const el=target&&target.closest?target.closest(".terminal-pane"):null
return termState.panes.find((p)=>p.el===el)||termFocusedPane()
}
function termCtxSelectAll(pane,tab){
if(termCtxEmu(tab)){if(typeof termEmuSelectAll==="function")termEmuSelectAll(tab);return}
pane=pane||termFocusedPane()
if(!pane||!pane.out)return
const range=document.createRange()
range.selectNodeContents(pane.out)
const sel=window.getSelection()
sel.removeAllRanges()
sel.addRange(range)
}
function termCtxPlainBuffer(tab){
if(termCtxEmu(tab)&&typeof termEmuText==="function")return termEmuText(tab)
if(!tab||!tab.buffer)return ""
const text=typeof termStripJobMarkers==="function"?termStripJobMarkers(tab.buffer,tab.shellId):tab.buffer
return termCtxStripAnsi(text).replace(/\s+$/,"")
}
// Full terminal mode shares the search bar; the query runs through xterm's search addon instead of the line view's matcher.
function termCtxFind(selection,tab){
const one=String(selection||"").trim()
termOpenSearch()
if(one&&one.length<=200&&!/[\r\n]/.test(one)){
const input=document.getElementById("terminalSearchInput")
input.value=one
termState.searchQuery=one
termState.searchIndex=0
if(termCtxEmu(tab)){if(typeof termEmuFind==="function")termEmuFind(tab,one)}
else termRunSearch()
input.select()
}
}
function termCtxRename(tab,pane){
if(!tab)return
if(termState.layout!=="single"&&pane&&pane.sessionId===tab.sessionId){termStartPaneRename(pane);return}
const el=document.querySelector('.terminal-tab[data-id="'+tab.sessionId+'"]')
if(el){el.scrollIntoView({block:"nearest",inline:"nearest"});termStartTabRename(el,tab)}
}
function termCtxSearchLoya(text){
if(typeof paletteOpen!=="function")return
paletteOpen()
setTimeout(()=>{
const input=document.getElementById("paletteInput")
if(!input)return
input.value=text
input.dispatchEvent(new Event("input",{bubbles:true}))
input.focus()
},0)
}
function termCtxRun(id,item,info){
const tab=info.tab
const emu=termCtxEmu(tab)
const fail=(err)=>showToast(err&&err.message?err.message:"Something went wrong","error")
const actions={
copy:()=>termCtxCopyText(emu&&typeof termEmuSelection==="function"?termEmuSelection(tab):info.selection),
copy_all:()=>termCtxCopyText(termCtxPlainBuffer(tab),"Copied all output"),
paste:()=>termCtxPaste(false,tab),
paste_line:()=>termCtxPaste(true,tab),
select_all:()=>termCtxSelectAll(info.pane,tab),
find:()=>termCtxFind(info.selection,tab),
clear:()=>{if(emu){if(typeof termEmuClear==="function")termEmuClear(tab)}else termClearOutput()},
interrupt:()=>{termSendControl(TERM_SHELL_CONTROL_KEYS.c);if(!emu)termClearStagedInput()},
full_terminal:()=>{
if(!tab||typeof termEmuSetMode!=="function")return
Promise.resolve(termEmuSetMode(tab,!emu)).then(()=>termCtxRefocus(tab)).catch((err)=>{fail(err);termCtxRefocus(tab)})
},
open_url:()=>bridgeCall("notes.open_url",[item.value]).catch((err)=>showToast(err&&err.message?err.message:"Could not open the link","error")),
cve:()=>Promise.resolve(cveOpenDetail(item.value)).catch(fail),
search_loya:()=>termCtxSearchLoya(item.value),
note:()=>termOpenNotePicker("Terminal selection - "+(tab&&tab.label?tab.label:"session")+" - "+new Date().toLocaleString(),item.value),
new:()=>termNewTab().catch(fail),
new_pick:()=>termOpenNewSessionMenu(info.x,info.y),
duplicate:()=>tab&&termNewTab(tab.profileId?"profile:"+tab.profileId:tab.shellId,{cwd:tab.cwd}).catch(fail),
rename:()=>termCtxRename(tab,info.pane),
split:()=>termSetLayout("cols2"),
unsplit:()=>termSetLayout("single"),
split_pick:()=>{const btn=document.getElementById("terminalSplitBtn");if(btn)termOpenSplitPicker(btn)},
send_session:()=>termSendSessionToNote(),
reopen:()=>termReopenClosed(),
close:()=>tab&&termCloseTab(tab.sessionId),
font_up:()=>termCtxApplyFont(termCtxFontStep(termCtxFontSize(),1),true),
font_down:()=>termCtxApplyFont(termCtxFontStep(termCtxFontSize(),-1),true),
font_reset:()=>termCtxApplyFont(TERM_CTX_FONT_DEFAULT,true),
dock_right:()=>termSetDockMode("right"),
dock_left:()=>termSetDockMode("left"),
dock_bottom:()=>termSetDockMode("bottom"),
maximize:()=>termToggleMaximize()
}
const fn=actions[id]
if(!fn)return
// Actions that put the caret back in the terminal: everything except those that open their own UI.
// full_terminal refocuses itself once the mode switch settles. In full terminal mode Select all keeps the xterm focused.
const keepsFocus=/^(find|note|search_loya|cve|open_url|rename|new_pick|split_pick|send_session|close|paste|paste_line|select_all|full_terminal)$/.test(id)
try{fn()}catch(err){console.error("terminal menu action failed",id,err)}
if(!keepsFocus||(emu&&id==="select_all"))termCtxRefocus(tab)
}
function termCtxContext(info){
const tab=info.tab
const emu=termCtxEmu(tab)
return {
selection:emu&&typeof termEmuSelection==="function"?String(termEmuSelection(tab)||""):info.selection,target:info.target,
emulator:emu,emuLocked:emu&&typeof termEmuLocked==="function"&&!!termEmuLocked(tab),
hasSession:!!tab,dead:!!(tab&&tab.dead),jobRunning:!!(tab&&tab.activeJob),hasOutput:emu?true:!!(tab&&tab.buffer&&tab.buffer.trim()),
layout:termState.layout,mode:termState.mode,maximized:!!termState.maximized,fontSize:termCtxFontSize(),
closedCount:(termState.closed||[]).length,
canNote:typeof termOpenNotePicker==="function",canCve:typeof cveOpenDetail==="function",canSearch:typeof paletteOpen==="function",
canOpenUrl:typeof bridgeCall==="function",canSplit:!!tab&&typeof termSetLayout==="function",
canEmulate:typeof termEmuSetMode==="function"
}
}
function termCtxClose(refocus){
const tab=termCtx.menus[0]&&termCtx.menus[0].info?termCtx.menus[0].info.tab:null
if(termCtx.hoverTimer){clearTimeout(termCtx.hoverTimer);termCtx.hoverTimer=null}
termCtx.menus.forEach((m)=>m.el.remove())
termCtx.menus=[]
document.removeEventListener("mousedown",termCtxOutside,true)
document.removeEventListener("keydown",termCtxKeydown,true)
window.removeEventListener("blur",termCtxOnBlur)
window.removeEventListener("resize",termCtxOnBlur)
if(refocus)termCtxRefocus(tab)
}
function termCtxOutside(e){
if(termCtx.menus.some((m)=>m.el.contains(e.target)))return
termCtxClose(false)
}
function termCtxOnBlur(){termCtxClose(false)}
function termCtxRows(menu){
return Array.prototype.slice.call(menu.el.querySelectorAll(":scope > .app-context-menu-item"))
}
function termCtxFocusRow(menu,index){
const rows=termCtxRows(menu)
if(index<0||!rows[index])return
menu.index=index
rows.forEach((r,i)=>{r.classList.toggle("term-ctx-active",i===index);r.setAttribute("aria-selected",i===index?"true":"false")})
menu.el.setAttribute("aria-activedescendant",rows[index].id)
}
// Rows are highlighted, never focused: focusing anything would collapse the terminal selection the menu acts on.
// Keys are read by a capture listener on the document while the menu is open; the deepest menu with a highlight is active.
function termCtxActiveMenu(){
for(let i=termCtx.menus.length-1;i>=0;i--)if(termCtx.menus[i].index>=0)return termCtx.menus[i]
return termCtx.menus[0]||null
}
function termCtxRenderMenu(items,level){
const el=document.createElement("div")
el.className="app-context-menu glass-panel term-ctx-menu"
el.setAttribute("role","menu")
el.setAttribute("aria-label",level?"Terminal submenu":"Terminal")
if(!level)el.id="terminalContextMenu"
const menu={el,rowItems:[],index:-1,level}
items.forEach((it)=>{
if(it.sep){const s=document.createElement("div");s.className="app-context-menu-sep";s.setAttribute("role","separator");el.appendChild(s);return}
const b=document.createElement("button")
b.type="button"
b.tabIndex=-1
b.id="termCtxRow"+(level||0)+"_"+menu.rowItems.length
b.className="app-context-menu-item"+(it.danger?" danger":"")+(it.submenu?" term-ctx-has-sub":"")
b.setAttribute("role",it.checkbox?"menuitemcheckbox":it.checked!==undefined?"menuitemradio":"menuitem")
if(it.checked!==undefined)b.setAttribute("aria-checked",it.checked?"true":"false")
if(it.submenu)b.setAttribute("aria-haspopup","menu")
b.disabled=!!it.disabled
if(it.disabled)b.setAttribute("aria-disabled","true")
b.dataset.id=it.id
const tail=it.submenu?'<i class="icon icon-caret-right term-ctx-caret"></i>':it.checked?'<i class="icon icon-check term-ctx-check"></i>':it.key?'<kbd class="term-ctx-key">'+termCtxEsc(it.key)+"</kbd>":""
b.innerHTML=(it.icon?'<i class="icon icon-'+termCtxEsc(it.icon)+'"></i>':"")+'<span class="term-ctx-label">'+termCtxEsc(it.label)+"</span>"+tail
el.appendChild(b)
menu.rowItems.push(it)
})
// Keep the terminal selection: a mousedown on a menu row must not move focus or collapse the selection.
el.addEventListener("mousedown",(e)=>e.preventDefault())
el.addEventListener("contextmenu",(e)=>e.preventDefault())
el.addEventListener("click",(e)=>{
const row=e.target.closest(".app-context-menu-item")
if(!row||row.disabled)return
const i=termCtxRows(menu).indexOf(row)
termCtxActivate(menu,i)
})
el.addEventListener("mousemove",(e)=>{
const row=e.target.closest(".app-context-menu-item")
if(!row)return
const i=termCtxRows(menu).indexOf(row)
if(i===menu.index)return
if(row.disabled)return
termCtxTrim(menu.level)
termCtxFocusRow(menu,i)
const it=menu.rowItems[i]
if(it&&it.submenu){
if(termCtx.hoverTimer)clearTimeout(termCtx.hoverTimer)
termCtx.hoverTimer=setTimeout(()=>{termCtx.hoverTimer=null;if(menu.index===i&&termCtx.menus[menu.level]===menu)termCtxOpenSub(menu,i,false)},160)
}
})
return menu
}
function termCtxPlace(menu,x,y,anchor){
const el=menu.el
el.style.visibility="hidden"
el.style.left="0px"
el.style.top="0px"
document.body.appendChild(el)
el.style.maxHeight=(window.innerHeight-16)+"px"
const w=el.offsetWidth,h=el.offsetHeight
const pos=anchor?termCtxSubmenuPos(anchor.row,anchor.parent,w,h,window.innerWidth,window.innerHeight,8):termCtxClamp(x,y,w,h,window.innerWidth,window.innerHeight,8)
el.style.left=pos.left+"px"
el.style.top=pos.top+"px"
el.style.visibility=""
}
// Closes every submenu deeper than `level`.
function termCtxTrim(level){
while(termCtx.menus.length>level+1){const m=termCtx.menus.pop();m.el.remove()}
termCtxRows(termCtx.menus[level]||{el:document.createElement("div")}).forEach((r)=>r.classList.remove("term-ctx-open"))
}
function termCtxOpenSub(menu,index,focusFirst){
const it=menu.rowItems[index]
if(!it||!it.submenu||it.disabled)return
termCtxTrim(menu.level)
const row=termCtxRows(menu)[index]
row.classList.add("term-ctx-open")
row.setAttribute("aria-expanded","true")
const sub=termCtxRenderMenu(it.submenu,menu.level+1)
sub.info=menu.info
termCtx.menus.push(sub)
termCtxPlace(sub,0,0,{row:row.getBoundingClientRect(),parent:menu.el.getBoundingClientRect()})
if(focusFirst)termCtxFocusRow(sub,termCtxNextIndex(sub.rowItems,-1,1))
}
function termCtxActivate(menu,index){
const it=menu.rowItems[index]
if(!it||it.disabled)return
if(it.submenu){termCtxOpenSub(menu,index,true);return}
const info=termCtx.menus[0].info
termCtxClose(false)
termCtxRun(it.id,it,info)
}
function termCtxKeydown(e){
const menu=termCtxActiveMenu()
if(!menu)return
const k=e.key
e.stopPropagation()
if(/^(Shift|Control|Alt|Meta|AltGraph|CapsLock)$/.test(k))return
if(k==="Escape"){e.preventDefault();if(menu.level>0){const parent=termCtx.menus[menu.level-1];termCtxTrim(parent.level);termCtxFocusRow(parent,parent.index)}else termCtxClose(true);return}
if(k==="Tab"){e.preventDefault();termCtxClose(true);return}
if(k==="ArrowDown"||k==="ArrowUp"){e.preventDefault();termCtxTrim(menu.level);termCtxFocusRow(menu,termCtxNextIndex(menu.rowItems,menu.index,k==="ArrowDown"?1:-1));return}
if(k==="Home"){e.preventDefault();termCtxFocusRow(menu,termCtxNextIndex(menu.rowItems,-1,1));return}
if(k==="End"){e.preventDefault();termCtxFocusRow(menu,termCtxNextIndex(menu.rowItems,-1,-1));return}
if(k==="ArrowRight"){e.preventDefault();const it=menu.rowItems[menu.index];if(it&&it.submenu)termCtxOpenSub(menu,menu.index,true);return}
if(k==="ArrowLeft"){e.preventDefault();if(menu.level>0){const parent=termCtx.menus[menu.level-1];termCtxTrim(parent.level);termCtxFocusRow(parent,parent.index)}return}
if(k==="Enter"||k===" "){e.preventDefault();termCtxActivate(menu,menu.index);return}
// Every other key stays with the menu (never reaches the shell) while it is open.
e.preventDefault()
// First letter jumps to the next row starting with it.
if(k.length===1&&!e.ctrlKey&&!e.altKey&&!e.metaKey){
const ch=k.toLowerCase(),n=menu.rowItems.length
for(let s=1;s<=n;s++){const i=(menu.index+s)%n;const it=menu.rowItems[i];if(!it.disabled&&String(it.label).toLowerCase().startsWith(ch)){termCtxTrim(menu.level);termCtxFocusRow(menu,i);return}}
}
}
function termCtxOpen(x,y,info,fromKeyboard){
termCtxClose(false)
if(typeof closeContextMenu==="function")closeContextMenu()
if(typeof termClosePopover==="function")termClosePopover()
if(typeof termSuggestHide==="function")termSuggestHide()
const items=termCtxBuildItems(termCtxContext(info))
const menu=termCtxRenderMenu(items,0)
menu.info=Object.assign({},info,{x,y})
termCtx.menus=[menu]
termCtxPlace(menu,x,y,null)
const first=termCtxNextIndex(menu.rowItems,-1,1)
if(fromKeyboard)termCtxFocusRow(menu,first)
document.addEventListener("keydown",termCtxKeydown,true)
setTimeout(()=>{document.addEventListener("mousedown",termCtxOutside,true);window.addEventListener("blur",termCtxOnBlur);window.addEventListener("resize",termCtxOnBlur)},0)
}
// Full terminal mode: xterm's DOM (its hidden helper textarea included) sits inside the pane output. termCtxWire also
// listens in the capture phase so the menu opens before xterm's own contextmenu handling, and the bubble pass skips it.
function termCtxInEmu(target){
return !!(target&&target.closest&&target.closest(".terminal-pane .xterm"))
}
function termCtxOnEmuContextMenu(e){
if(!termCtxInEmu(e.target))return
termCtxOnContextMenu(e)
}
function termCtxOnContextMenu(e){
if(e.shiftKey)return
const panes=document.getElementById("terminalPanes")
if(!panes||!panes.contains(e.target))return
const inEmu=termCtxInEmu(e.target)
if(inEmu&&e.eventPhase!==Event.CAPTURING_PHASE)return
if(!inEmu&&e.target.closest(".terminal-pane-head,.terminal-pane-empty,input,textarea,select"))return
e.preventDefault()
e.stopPropagation()
const pane=termCtxPaneAt(e.target)
const idx=termState.panes.indexOf(pane)
if(idx>=0&&idx!==termState.focusPane)termFocusPane(idx,{noInput:true})
const tab=termFindTab(pane&&pane.sessionId?pane.sessionId:termState.activeId)
const ioc=inEmu?null:e.target.closest(".term-ioc")
const info={pane,tab,selection:termCtxEmu(tab)&&typeof termEmuSelection==="function"?String(termEmuSelection(tab)||""):termOutputSelectionText(),target:ioc?ioc.dataset.value||ioc.textContent:""}
const fromKeyboard=e.button!==2&&e.clientX===0&&e.clientY===0
let x=e.clientX,y=e.clientY
if(fromKeyboard&&pane&&pane.out){const r=pane.out.getBoundingClientRect();x=r.left+24;y=r.top+24}
termCtxOpen(x,y,info,fromKeyboard)
}
// The Menu key / Shift+F10 while typing in the terminal: WebKit and Chromium send contextmenu to the hidden input.
function termCtxOnInputContextMenu(e){
e.preventDefault()
const pane=termFocusedPane()
const tab=termFindTab(termState.activeId)
const r=pane&&pane.out?pane.out.getBoundingClientRect():{left:40,top:40}
termCtxOpen(r.left+24,r.top+24,{pane,tab,selection:termOutputSelectionText(),target:""},true)
}
function termCtxWire(){
const panes=document.getElementById("terminalPanes")
if(!panes||panes.dataset.ctxWired)return
panes.dataset.ctxWired="1"
panes.addEventListener("contextmenu",termCtxOnContextMenu)
panes.addEventListener("contextmenu",termCtxOnEmuContextMenu,true)
const input=document.getElementById("terminalInput")
if(input)input.addEventListener("contextmenu",termCtxOnInputContextMenu)
bridgeCall("terminal.get_settings").then((s)=>{if(s&&s.font_size)termCtxApplyFont(s.font_size,false)}).catch(()=>{})
}
