const APP_SHORTCUTS=[
{scope:"Global",items:[
{keys:"Ctrl+K",desc:"Open command palette"},
{keys:"Ctrl+/  or  ?",desc:"Show this shortcuts list"},
{keys:"Escape",desc:"Close the open popover, modal, or palette"}
]},
{scope:"Dashboard",items:[
{keys:"Alt+N",desc:"Add Note"},
{keys:"Alt+C",desc:"Add Command"},
{keys:"Alt+T",desc:"Add Target"}
]},
{scope:"Note Editor",items:[
{keys:"Ctrl+S",desc:"Save note"},
{keys:"Ctrl+Z",desc:"Undo"},
{keys:"Ctrl+Shift+Z  or  Ctrl+Y",desc:"Redo"},
{keys:"Ctrl+F",desc:"Find in note"},
{keys:"Ctrl+B / Ctrl+I / Ctrl+U",desc:"Bold, italic, underline"},
{keys:"Ctrl+Shift+X",desc:"Strikethrough"},
{keys:"Ctrl+E",desc:"Inline code"},
{keys:"Ctrl+Shift+H",desc:"Highlight"},
{keys:"Ctrl+Shift+,  /  Ctrl+Shift+.",desc:"Smaller / larger text"},
{keys:"Ctrl+\\",desc:"Clear formatting"},
{keys:"Ctrl+Alt+0 - Ctrl+Alt+3",desc:"Normal text, Heading 1-3"},
{keys:"Ctrl+Shift+7 / 8 / 9",desc:"Numbered list, bullet list, checklist"},
{keys:"Ctrl+L",desc:"Insert link"},
{keys:"Ctrl+Shift+C",desc:"Insert command block"},
{keys:"Ctrl+Alt+C",desc:"Code block (wraps the selection)"},
{keys:"Ctrl+Shift+;",desc:"Insert timestamp"},
{keys:"Ctrl+Shift+M",desc:"Mask selection as secret"},
{keys:"Alt+Shift+Up / Down",desc:"Move block up or down"},
{keys:"Ctrl+Shift+D",desc:"Duplicate block"},
{keys:"Ctrl+Shift+V",desc:"Paste as plain text"},
{keys:"Alt+F10",desc:"Move into the toolbar or selection bubble"},
{keys:"Shift+F10  or  Menu",desc:"Open the editor menu at the caret"}
]},
{scope:"Reporting",items:[
{keys:"Ctrl+S",desc:"Save the report now"},
{keys:"Ctrl+Shift+P",desc:"Preview the report"},
{keys:"Ctrl+Z",desc:"Undo the last change to the report; inside a text field, undo the typing first"},
{keys:"Ctrl+Shift+Z  or  Ctrl+Y",desc:"Redo"},
{keys:"Alt+A",desc:"Add a section: choose from the section types"},
{keys:"Alt+1 - Alt+6",desc:"Quick-add executive summary, scope, methodology, detailed findings, attack narrative, conclusion"},
{keys:"F2",desc:"Rename the selected section"},
{keys:"Alt+Up / Alt+Down",desc:"Move the selected section or finding"},
{keys:"Double-click a section",desc:"Rename it"}
]},
{scope:"Chains",items:[
{keys:"/caller  then Enter",desc:"Run that action chain from the terminal or the AI input"},
{keys:"Enter  (caller box)",desc:"Save the chain's caller"},
{keys:"Escape  (caller box)",desc:"Put the caller back as it was"},
{keys:"Escape  (search box)",desc:"Clear the chain search"}
]},
{scope:"Terminal",items:[
{keys:"Enter",desc:"Run command"},
{keys:"Shift+Enter",desc:"New line without running"},
{keys:"Tab",desc:"Send tab to the shell for completion"},
{keys:"Ctrl+C",desc:"Copy the selection, or interrupt when nothing is selected"},
{keys:"Ctrl+D",desc:"Send end of file"},
{keys:"Ctrl+Z",desc:"Suspend the foreground process"},
{keys:"Ctrl+L",desc:"Clear the output view"},
{keys:"Ctrl+U",desc:"Clear the typed line"},
{keys:"Ctrl+F",desc:"Search the output, Enter for next, Shift+Enter for previous"},
{keys:"Ctrl+Tab",desc:"Cycle sessions, add Shift to go back"},
{keys:"Ctrl+1 - Ctrl+9",desc:"Jump straight to a session"},
{keys:"Double-click a tab",desc:"Rename the session"},
{keys:"Ctrl+Shift+Enter",desc:"Maximize or restore the terminal panel"},
{keys:"Ctrl+Up / Ctrl+Down",desc:"Jump to the previous or next job block"},
{keys:"Up / Down",desc:"Recall command history, or move through suggestions while they are open"},
{keys:"Tab  or  Right",desc:"Accept the highlighted command suggestion"},
{keys:"Escape",desc:"Dismiss command suggestions"},
{keys:"Tab  (line has a {PLACEHOLDER})",desc:"Select the next placeholder to fill in"},
{keys:"Click a job header",desc:"Fold or unfold that command's output"}
]}
]
const SHORTCUT_MODIFIER_KEYS=["Control","Shift","Alt","Meta","OS","AltGraph","CapsLock","Hyper","Super"]
const SHORTCUT_KEY_NAMES={" ":"Space",Spacebar:"Space",Esc:"Escape",Up:"ArrowUp",Down:"ArrowDown",Left:"ArrowLeft",Right:"ArrowRight",Del:"Delete"}
const SHORTCUT_NAMED_LOWER={space:"Space",enter:"Enter",tab:"Tab",escape:"Escape",esc:"Escape",backspace:"Backspace",delete:"Delete",insert:"Insert",home:"Home",end:"End",pageup:"PageUp",pagedown:"PageDown",arrowup:"ArrowUp",arrowdown:"ArrowDown",arrowleft:"ArrowLeft",arrowright:"ArrowRight",up:"ArrowUp",down:"ArrowDown",left:"ArrowLeft",right:"ArrowRight"}
const SHORTCUT_RESERVED=(()=>{
const out=["Ctrl+Tab","Ctrl+Shift+Tab","Ctrl+Shift+Enter","Ctrl+ArrowUp","Ctrl+ArrowDown","Ctrl+Alt+T","Ctrl+Alt+Delete","Ctrl+Alt+L","Alt+Tab","Alt+F4","F11"]
"CDZLRUWAEFKVXY/".split("").forEach((k)=>{out.push("Ctrl+"+k);out.push("Ctrl+Shift+"+k)})
"123456789".split("").forEach((k)=>out.push("Ctrl+"+k))
// Ctrl+Alt+Arrow switches workspaces on XFCE and GNOME, so the desktop eats it before the app sees it.
;["ArrowLeft","ArrowRight","ArrowUp","ArrowDown"].forEach((k)=>out.push("Ctrl+Alt+"+k))
return out
})()
function shortcutNormalize(value){
let parts=String(value||"").replace(/\s+/g,"").split("+")
if(parts.length>1&&parts[parts.length-1]===""&&parts[parts.length-2]==="")parts=parts.slice(0,-2).concat(["+"])
parts=parts.filter(Boolean)
if(!parts.length)return ""
const mods={}
let key=null
for(const part of parts){
const low=part.toLowerCase()
if(low==="ctrl"||low==="control")mods.Ctrl=true
else if(low==="alt")mods.Alt=true
else if(low==="shift")mods.Shift=true
else if(["meta","super","win","cmd","os"].indexOf(low)!==-1)return null
else if(key!==null)return null
else if(SHORTCUT_NAMED_LOWER[low])key=SHORTCUT_NAMED_LOWER[low]
else if(/^f([1-9]|1[0-2])$/.test(low))key=low.toUpperCase()
else if(part.length===1)key=part.toUpperCase()
else return null
}
if(key===null)return null
if(!mods.Ctrl&&!mods.Alt&&!/^F\d+$/.test(key))return null
return ["Ctrl","Alt","Shift"].filter((m)=>mods[m]).concat([key]).join("+")
}
function shortcutFromEvent(e){
if(!e||!e.key||e.metaKey||SHORTCUT_MODIFIER_KEYS.indexOf(e.key)!==-1)return ""
let key=SHORTCUT_KEY_NAMES[e.key]||e.key
if(e.code&&/^Key[A-Z]$/.test(e.code))key=e.code.slice(3)
else if(e.code&&/^Digit[0-9]$/.test(e.code))key=e.code.slice(5)
else if(e.code==="Space")key="Space"
else if(key.length===1)key=key.toUpperCase()
return [e.ctrlKey?"Ctrl":"",e.altKey?"Alt":"",e.shiftKey?"Shift":"",key].filter(Boolean).join("+")
}
function shortcutMatches(e,combo){
return !!combo&&shortcutFromEvent(e)===combo
}
function shortcutConflict(combo){
return combo&&SHORTCUT_RESERVED.indexOf(combo)!==-1?combo+" is already used by the terminal, the app or the desktop.":""
}
function shortcutSheetSections(){
const out=APP_SHORTCUTS.map((s)=>s.scope==="Terminal"&&typeof termShortcutSheetItems==="function"?{scope:s.scope,items:s.items.concat(termShortcutSheetItems())}:s)
// The chain diagram editor keeps its own list (FLOW_EDITOR_SHORTCUTS in flow-editor.js, loaded later); it goes right after Chains.
if(typeof FLOW_EDITOR_SHORTCUTS!=="undefined"&&Array.isArray(FLOW_EDITOR_SHORTCUTS)){
const at=out.findIndex((s)=>s.scope==="Chains")
out.splice(at<0?out.length:at+1,0,{scope:"Chain diagram editor",items:[{keys:"Ctrl+S",desc:"Save the diagram"}].concat(FLOW_EDITOR_SHORTCUTS.map((k)=>({keys:k.keys,desc:k.label})))})
}
return out
}
// Split the sheet into two balanced columns at row boundaries. A section that has to continue in the next column repeats its
// title as "(continued)", and a split never leaves fewer than two rows on either side.
// rowHeight/headerHeight: measured pixel heights when available (the sheet measures them at the real column width);
// otherwise a row is 1 unit (1.8 if its text is long enough to wrap) and a section title 1.5.
function shortcutSheetColumns(sections,count=2,rowHeight=null,headerHeight=null){
const HEADER=headerHeight||1.5
const lines=(rows)=>rows.reduce((n,it)=>n+(rowHeight?rowHeight(it):(String(it.desc||"").length+String(it.keys||"").length*1.1>62?1.8:1)),0)
const total=sections.reduce((n,s)=>n+HEADER+lines(s.items),0)
const target=total/count
const cols=[[]];let used=0
for(const s of sections){
let rows=s.items.slice(),cont=false
while(rows.length){
const col=cols[cols.length-1]
const put=(n)=>{col.push({scope:s.scope,cont,items:rows.slice(0,n)});used+=HEADER+lines(rows.slice(0,n));rows=rows.slice(n)}
if(cols.length===count){put(rows.length);break}
let room=0,h=0
while(room<rows.length&&used+HEADER+h+lines([rows[room]])<=target){h+=lines([rows[room]]);room++}
if(room===rows.length){put(rows.length);break}
if(room<2||rows.length-room<2){
if(used===0){put(rows.length);break}
cols.push([]);used=0;continue
}
put(room);cols.push([]);used=0;cont=true
}
}
return cols.filter((c)=>c.length)
}
// Rows whose description or keys contain every typed word (case-insensitive); sections with no match are dropped.
function shortcutSheetFilter(sections,query){
const words=String(query||"").toLowerCase().split(/\s+/).filter(Boolean)
if(!words.length)return sections
return sections.map((s)=>({scope:s.scope,items:s.items.filter((it)=>{const hay=(s.scope+" "+it.desc+" "+it.keys).toLowerCase();return words.every((w)=>hay.includes(w))})})).filter((s)=>s.items.length)
}
// Height of a section's title plus spacing: the section's height minus its rows.
function sec0RowsHeight(sectionEl){return [...sectionEl.querySelectorAll(".shortcuts-row")].reduce((n,r)=>n+r.getBoundingClientRect().height,0)}
function openShortcutsSheet(){
const el=document.createElement("div")
el.className="shortcuts-modal glass-panel"
const all=shortcutSheetSections()
const renderSection=(s)=>`<div class="shortcuts-section"><div class="shortcuts-section-title">${s.scope}${s.cont?" (continued)":""}</div>${s.items.map((it)=>`<div class="shortcuts-row"><span class="shortcuts-keys">${it.keys}</span><span class="shortcuts-desc">${it.desc}</span></div>`).join("")}</div>`
el.innerHTML=`<div class="shortcuts-head"><div class="shortcuts-title">Keyboard Shortcuts</div><label class="shortcuts-search"><i class="icon icon-search"></i><input type="search" id="shortcutsSearch" placeholder="Search shortcuts..." autocomplete="off" spellcheck="false" aria-label="Search shortcuts"></label></div><div class="shortcuts-list" id="shortcutsList"></div><div class="shortcuts-actions"><button type="button" id="shortcutsCloseBtn">Close</button></div>`
const list=el.querySelector("#shortcutsList")
const render=(q)=>{
const found=shortcutSheetFilter(all,q)
let rowH=null,headH=null
const twoCols=getComputedStyle(list).gridTemplateColumns.split(" ").length>1
if(found.length&&twoCols){
// Measure every row at the real column width, so wrapped rows count as the height they really take.
const width=(list.clientWidth-33)/2
list.innerHTML=`<div class="shortcuts-col" style="width:${width}px;padding:0">${found.map(renderSection).join("")}</div>`
const heights=new Map(),rowEls=list.querySelectorAll(".shortcuts-row")
let i=0
found.forEach((sec)=>sec.items.forEach((it)=>{const r=rowEls[i++];if(r)heights.set(it,r.getBoundingClientRect().height)}))
const title=list.querySelector(".shortcuts-section")
headH=title?title.getBoundingClientRect().height-sec0RowsHeight(title):null
rowH=(it)=>heights.get(it)||30
}
list.innerHTML=found.length?shortcutSheetColumns(found,twoCols?2:1,rowH,headH).map((col)=>`<div class="shortcuts-col">${col.map(renderSection).join("")}</div>`).join(""):`<div class="shortcuts-empty">No shortcut matches "${String(q).replace(/[&<>"']/g,(c)=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]))}".</div>`
}
openModal(el)
render("")
const search=el.querySelector("#shortcutsSearch")
search.addEventListener("input",()=>render(search.value))
search.addEventListener("keydown",(e)=>{if(e.key==="Escape"&&search.value){e.preventDefault();e.stopPropagation();search.value="";render("")}})
setTimeout(()=>search.focus(),0)
el.querySelector("#shortcutsCloseBtn").addEventListener("click",closeModal)
}
function initShortcuts(){
document.getElementById("btnShortcuts").addEventListener("click",openShortcutsSheet)
document.addEventListener("keydown",(e)=>{
const active=document.activeElement
const tag=active?active.tagName:""
const editable=!!(active&&(tag==="INPUT"||tag==="TEXTAREA"||active.isContentEditable))
if((e.ctrlKey||e.metaKey)&&e.key==="/"){e.preventDefault();openShortcutsSheet();return}
if(e.key==="?"&&!editable){e.preventDefault();openShortcutsSheet()}
})
}
