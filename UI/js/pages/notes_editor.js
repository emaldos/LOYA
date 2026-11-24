// Note editor options (DOM side): the main toolbar, the More panel with pin / unpin, the selection bubble, the right-click menu with submenus and the pentest tool panels.
// Every surface is drawn from the one registry in notes_editor_core.js (NotesEd.COMMANDS); what a command does lives in NOTES_ED_RUN below, keyed by the same id, so the surfaces cannot drift apart.
// Nothing here is saved with a note: the bubble, the menus and the panels live outside the contenteditable body.
let notesEdState={bars:[],customise:false,mouseDown:false,bubbleTimer:null,refreshRaf:0,anchor:null,menu:null,docWired:false,moreBar:null,pinsKey:""}
// ---------------------------------------------------------------- mounting
// The editor works on the active host (notes.js: notesHost / notesEditorBody()). A host gets the whole set by 1) having its body wired - notesProWireBody() does that for every host - and
// 2) optionally mounting a registry toolbar into any element with notesEdMountToolbar(el,{host}). Bubble, right-click menu and shortcuts need no toolbar at all.
// A host can switch commands off with features: {"pt.terminal":false} for one command, {"group:pentest":false} for a group, {noteLinks:false} for links to notes.
function notesEdMountToolbar(el,opts){
if(!el||notesEdState.bars.some((b)=>b.el===el))return
const bar={el,host:(opts&&opts.host)||null,width:0,overflow:[]}
notesEdState.bars.push(bar)
el.classList.add("notes-ed-toolbar")
el.setAttribute("role","toolbar")
el.setAttribute("aria-label","Editor tools")
el.addEventListener("mousedown",notesEdKeepSelection)
el.addEventListener("click",(e)=>notesEdToolClick(e,"bar"))
el.addEventListener("change",notesEdSizeChange)
el.addEventListener("keydown",(e)=>notesEdRovingKeys(e,el))
if(typeof ResizeObserver!=="undefined"){
bar.observer=new ResizeObserver(()=>{const w=el.clientWidth;if(w&&w!==bar.width)notesEdFit(bar)})
bar.observer.observe(el)
}
notesEdRenderBar(bar)
}
function notesEdUnmountToolbar(el){
const i=notesEdState.bars.findIndex((b)=>b.el===el)
if(i<0)return
const bar=notesEdState.bars[i]
if(bar.observer)bar.observer.disconnect()
notesEdState.bars.splice(i,1)
}
function notesEdWireBody(body){
if(!body||body.dataset.edWired)return
body.dataset.edWired="1"
body.addEventListener("keydown",notesEdBodyKeydown)
body.addEventListener("mousedown",()=>{notesEdState.mouseDown=true;notesEdBubbleHide()})
body.addEventListener("mouseup",()=>{notesEdState.mouseDown=false;notesEdBubbleSoon(20)})
body.addEventListener("input",notesEdBubbleHide)
body.addEventListener("scroll",()=>{notesEdBubbleHide();notesEdMenuClose()},{passive:true})
body.addEventListener("blur",()=>setTimeout(()=>{const a=document.activeElement;if(a!==body&&!(a&&a.closest&&a.closest("#notesEdBubble")))notesEdBubbleHide()},120))
}
function notesEdWireDoc(){
if(notesEdState.docWired)return
notesEdState.docWired=true
document.addEventListener("mouseup",()=>{notesEdState.mouseDown=false})
document.addEventListener("selectionchange",()=>{notesEdRefreshSoon();if(!notesEdState.mouseDown)notesEdBubbleSoon(90)})
document.addEventListener("keydown",notesEdDocKeydown,true)
window.addEventListener("resize",()=>{notesEdBubbleHide();notesEdMenuClose();notesEdMoreClose()})
}
function notesEdBody(){return notesEditorBody()}
function notesEdHost(){return typeof notesHost!=="undefined"?notesHost:null}
// The toolbar that belongs to the active host (the notes editor's own bar when the host has none).
function notesEdBar(){
const h=notesEdHost()
const live=notesEdState.bars.filter((b)=>b.el.isConnected)
return live.find((b)=>b.host&&b.host===h)||live.find((b)=>!b.host&&(!h||h.native||!h.root||h.root.contains(b.el)))||null
}
function notesEdAllowed(id){
const h=notesEdHost()
const f=h&&h.features
if(!f)return true
const c=NotesEd.get(id)
return !(f[id]===false||(c&&f["group:"+c.group]===false))
}
function notesEdPrefs(){return (typeof notesState!=="undefined"&&notesState.prefs)||{}}
function notesEdPins(){return NotesEd.normPins(notesEdPrefs().toolbar_main)}
function notesEdSetPref(key,value){
if(!notesState.prefs)notesState.prefs={}
notesState.prefs[key]=value
return bridgeCall("notes.set_editor_pref",[key,value]).then((p)=>{notesState.prefs=p;notesEdOnPrefs();return p}).catch(()=>{})
}
// ---------------------------------------------------------------- selection context
function notesEdRangeText(range){
if(!range)return ""
let out=""
const block=/^(P|DIV|LI|H[1-6]|TR|PRE|BLOCKQUOTE|TABLE|UL|OL|FIGURE)$/
const walk=(node)=>{
node.childNodes.forEach((n)=>{
if(n.nodeType===3){out+=n.nodeValue.replace(/​/g,"");return}
if(n.nodeType!==1)return
if(n.tagName==="BR"){out+="\n";return}
const isBlock=block.test(n.tagName)
if(isBlock&&out&&!out.endsWith("\n"))out+="\n"
walk(n)
if((n.tagName==="TD"||n.tagName==="TH")&&n.nextElementSibling)out+="\t"
if(isBlock&&!out.endsWith("\n"))out+="\n"
})
}
walk(range.cloneContents())
return out.replace(/\n+$/,"")
}
// A triple click selects up to the start of the next block. That empty tail is cut off, so "insert after the selection" and "replace the selection" stay in the block that was selected.
function notesEdTrimRange(range,body){
if(range.endOffset!==0||range.endContainer===range.startContainer)return range
const w=document.createTreeWalker(body,NodeFilter.SHOW_TEXT,null)
let n,last=null
while((n=w.nextNode())){
if(n===range.endContainer||(range.endContainer.nodeType===1&&range.endContainer.contains(n)&&range.comparePoint(n,0)>=0))break
if(range.comparePoint(n,n.nodeValue.length)>0)break
if(range.intersectsNode(n))last=n
}
if(!last)return range
const r=range.cloneRange()
r.setEnd(last,last.nodeValue.length)
return r.collapsed?range:r
}
// Everything a command needs to know about where the caret (or the right-clicked element) is.
function notesEdContext(target){
const body=notesEdBody()
const sel=window.getSelection()
let range=sel&&sel.rangeCount?sel.getRangeAt(0):null
if(!range||!body.contains(range.startContainer)){const s=notesState.savedRange;range=s&&body.contains(s.startContainer)?s:null}
let el=target&&target.nodeType?(target.nodeType===1?target:target.parentElement):null
if(el&&!body.contains(el))el=null
if(!el&&range)el=range.startContainer.nodeType===1?range.startContainer:range.startContainer.parentElement
const at=(s)=>{const hit=el&&el.closest?el.closest(s):null;return hit&&hit!==body&&body.contains(hit)?hit:null}
if(range&&!range.collapsed)range=notesEdTrimRange(range,body)
const hasSel=!!range&&!range.collapsed
const card=at(".cmd-card-embed"),fig=at("figure.note-embed"),pre=at("pre.note-code"),cell=at("td,th"),callout=at(".note-callout")
let secret=at(".note-secret")
if(!secret&&hasSel)secret=Array.from(body.querySelectorAll(".note-secret")).find((s)=>range.intersectsNode(s))||null
let block=el
while(block&&block!==body&&block.parentNode!==body)block=block.parentNode
if(!block||block===body||block.nodeType!==1)block=null
const finding=callout&&/^(finding|vuln)$/.test(callout.dataset.callout||"")?callout:null
return {range,hasSel,text:hasSel?notesEdRangeText(range):"",el,card,fig,pre,code:pre,cell,table:cell,link:at("a"),secret,callout,finding,block,fmt:!card&&!fig&&!pre}
}
function notesEdEnabled(cmd,ctx){return NotesEd.enabledFor(cmd,ctx)}
function notesEdWhyDisabled(cmd,ctx){
const n=(cmd.needs||[]).find((k)=>k==="sel"?!ctx.hasSel:!ctx[k])
return {sel:"Select some text first",fmt:"Not available inside a code block or a command card",block:"Click inside a block first",table:"Click inside a table first",finding:"Click inside a finding or vulnerability callout first",secret:"Click a masked secret first"}[n]||"Not available here"
}
function notesEdFocus(){
const body=notesEdBody()
if(document.activeElement!==body){body.focus();notesRestoreRange()}
else{const sel=window.getSelection();if(!sel.rangeCount||!body.contains(sel.getRangeAt(0).startContainer))notesRestoreRange()}
}
function notesEdSelect(range){
const sel=window.getSelection()
sel.removeAllRanges()
sel.addRange(range)
notesState.savedRange=range.cloneRange()
}
// A fixed rectangle to hang a popover on: the element that was clicked may be gone (menu, bubble) by the time the popover opens.
function notesEdRectAnchor(el){
if(!el||!el.getBoundingClientRect)return null
const r=el.getBoundingClientRect()
const rect={left:r.left,top:r.top,right:r.right,bottom:r.bottom,width:r.width,height:r.height}
return {getBoundingClientRect:()=>rect}
}
function notesEdPointAnchor(x,y){
const rect={left:x,top:y,right:x,bottom:y,width:0,height:0}
return {getBoundingClientRect:()=>rect}
}
// Where a command's popover opens: next to what started it, else its toolbar button, else the More button.
function notesEdAnchor(id){
if(notesEdState.anchor)return notesEdState.anchor
const bar=notesEdBar()
if(!bar){
// A host with its own toolbar names its buttons through el(), as it does for notes.js.
const legacy={"ins.cmd":"notesInsertCmd","callout.credential":"notesInsertCallout","pt.ioc":"notesIocTools","ins.link":"notesInsertLink"}[id]
return (legacy&&notesHostEl(legacy))||notesHostWrap()
}
const btn=id?bar.el.querySelector('[data-ed="'+id+'"]:not(.notes-ed-overflowed)'):null
return btn||bar.el.querySelector(".notes-ed-more-btn")||bar.el
}
function notesEdRun(id,opts){
const o=opts||{}
const fn=NOTES_ED_RUN[id]
if(!fn)return false
notesEdMenuClose()
notesEdBubbleHide()
notesEdFocus()
const ctx=o.ctx||notesEdContext()
const cmd=NotesEd.get(id)
if(!notesEdAllowed(id))return false
if(cmd&&!notesEdEnabled(cmd,ctx)){showToast(notesEdWhyDisabled(cmd,ctx),"error");return false}
notesEdState.anchor=o.anchor||null
try{fn(ctx,o)}finally{notesEdState.anchor=null}
notesEdRefreshSoon()
return true
}
// ---------------------------------------------------------------- what each command does
function notesEdStyle(tag,ctx){
const cur=notesEdStyleOf(ctx)
if(cur.tag===tag)return
if(ctx.pre&&tag!=="pre"){notesEdConvertBlock(ctx.pre,tag);return}
notesProFormatBlock(tag)
}
// A host label overrides a command's label (a report field calls its two heading levels "Heading" and "Sub-heading").
function notesEdHostLabel(id){const h=notesEdHost();return (h&&h.labels&&h.labels[id])||""}
// Names the block under the caret by its Notes style. A host that maps tags (report fields store h1 as h3 and h3 as h4)
// is read back through that map, so the dropdown and menus show the host's names, not the stored tag.
function notesEdStyleOf(ctx){
const el=ctx&&ctx.el
if(ctx&&ctx.pre)return {tag:"pre",label:"Code block"}
const host=notesEdHost(),map=(host&&host.tags)||{}
const real={h1:map.h1||"h1",h2:map.h2||"h2",h3:map.h3||"h3"}
const sel=[...new Set([real.h1,real.h2,real.h3,"blockquote"])].join(",")
const h=el&&el.closest?el.closest(sel):null
if(h&&notesEdBody().contains(h)){
const t=h.tagName.toLowerCase()
if(t==="blockquote")return {tag:"blockquote",label:notesEdHostLabel("style.quote")||"Quote"}
const k=["h1","h2","h3"].find((x)=>real[x]===t)
if(k)return {tag:k,label:notesEdHostLabel("style."+k)||{h1:"Heading 1",h2:"Heading 2",h3:"Heading 3"}[k]}
}
return {tag:"p",label:notesEdHostLabel("style.p")||"Normal"}
}
// Turns a plain block into another kind of block, keeping its text.
function notesEdConvertBlock(block,kind){
if(!block||!block.parentNode)return
const text=(block.tagName==="PRE"?notesProCodeText(block):(block.innerText||block.textContent||"")).replace(/​/g,"")
let el
if(kind==="pre"){
el=document.createElement("pre");el.className="note-code"
if(text)el.textContent=text;else el.appendChild(document.createElement("br"))
}else if(kind.startsWith("callout:")){
el=notesProBuildCallout(kind.slice(8))
if(block.matches("p,div,h1,h2,h3,h4,blockquote,ul,ol,pre,table")&&!block.matches(".note-callout")){block.replaceWith(el);el.appendChild(block);notesProCaretInto(block,true);notesMarkDirty();notesProAfterStructureChange();return}
const p=document.createElement("p");p.textContent=text;el.appendChild(p)
}else{
el=document.createElement(kind)
const lines=text.split("\n")
lines.forEach((l,i)=>{if(i)el.appendChild(document.createElement("br"));el.appendChild(document.createTextNode(l))})
if(!text)el.appendChild(document.createElement("br"))
}
block.replaceWith(el)
notesProCaretInto(el.matches(".note-callout")?el.lastElementChild:el,true)
notesMarkDirty()
notesProAfterStructureChange()
}
function notesEdInlineCode(ctx){
const inside=ctx.el&&ctx.el.closest?ctx.el.closest("code"):null
if(inside&&notesEdBody().contains(inside)&&!inside.closest("pre")){
const t=document.createTextNode(inside.textContent)
inside.replaceWith(t)
notesProSetCaret(t,t.length)
notesMarkDirty()
return
}
if(!ctx.hasSel){showToast("Select the text to mark as code first","error");return}
const code=document.createElement("code")
code.textContent=ctx.range.toString()
ctx.range.deleteContents()
ctx.range.insertNode(code)
const r=document.createRange()
r.selectNodeContents(code)
notesEdSelect(r)
notesMarkDirty()
}
function notesEdClearFormat(ctx){
notesExec("removeFormat")
if(!ctx.hasSel)return
const range=notesProSel()
if(!range)return
Array.from(notesEdBody().querySelectorAll("code,mark,span[style]")).filter((n)=>range.intersectsNode(n)&&!n.closest("pre,.cmd-card")).forEach((n)=>{
if(n.tagName==="SPAN"){n.removeAttribute("style");if(n.attributes.length)return}
const p=n.parentNode
while(n.firstChild)p.insertBefore(n.firstChild,n)
n.remove()
})
notesMarkDirty()
}
function notesEdAlign(dir,ctx){
const b=ctx.card||ctx.fig||(ctx.el&&ctx.el.closest&&!ctx.cell?ctx.el.closest("table"):null)
if(b&&notesEdBody().contains(b)){
if(b.matches(".cmd-card-embed"))notesSetCmdCardAlign(b,dir)
else notesProSetLayout(b,dir)
return
}
notesExec({left:"justifyLeft",center:"justifyCenter",right:"justifyRight"}[dir])
}
function notesEdColor(kind,o){
const text=kind==="text"
const apply=text?notesApplyTextColor:notesApplyHighlightColor
const cur=text?notesColorTextCurrent:notesColorHighlightCurrent
if(o.color){apply(o.color);return}
if(!o.pick){apply(cur);return}
const live=notesEdSelColors(notesEdContext())
notesOpenColorPopover(notesEdAnchor(text?"fmt.color":"fmt.highlight"),text?NOTES_TEXT_COLORS:NOTES_HIGHLIGHT_COLORS,apply,(text?live.text:live.highlight)||cur,!text)
}
function notesEdCssHex(v){
const m=/rgba?\(\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)(?:[\s,\/]+([\d.]+))?/.exec(v||"")
if(!m||(m[4]!==undefined&&parseFloat(m[4])===0))return ""
return notesRgbToHex(+m[1],+m[2],+m[3])
}
// The colours of the text at the caret, when it has its own (so the swatches and the palette show what is selected).
function notesEdSelColors(ctx){
const body=notesEdBody()
const out={text:"",highlight:""}
if(!ctx||!ctx.el||!ctx.range||ctx.el===body)return out
const own=notesEdCssHex(getComputedStyle(ctx.el).color),base=notesEdCssHex(getComputedStyle(body).color)
if(own&&own!==base&&!ctx.el.closest("a,code,pre,.cmd-card,.note-ts,.note-mitre,h1,h2,h3,h4"))out.text=own
let n=ctx.el
while(n&&n!==body){
if(n.style&&n.style.backgroundColor&&n.matches("span,font,mark")){out.highlight=notesEdCssHex(getComputedStyle(n).backgroundColor);break}
n=n.parentElement
}
return out
}
function notesEdSyncColors(){
const live=notesEdBody()&&notesHostOpen()?notesEdSelColors(notesEdContext()):{text:"",highlight:""}
document.querySelectorAll(".notes-ed-swatch-text").forEach((s)=>{s.style.background=live.text||notesColorTextCurrent})
document.querySelectorAll(".notes-ed-swatch-highlight").forEach((s)=>{s.style.background=live.highlight||notesColorHighlightCurrent})
}
function notesEdCollapseAfter(range){
const r=range?range.cloneRange():null
if(r){r.collapse(false);notesState.savedRange=r}
}
function notesEdReplaceRange(range,text){
const body=notesEdBody()
body.focus()
notesEdSelect(range)
document.execCommand("insertText",false,text)
notesMarkDirty()
}
function notesEdInsertCodeBelow(range,text,lang){
notesEdBody().focus()
notesEdCollapseAfter(range)
notesProInsertCode(lang||"",text)
}
// Moving a node drops the selection that was inside it; it is put back so the shortcut can be pressed again and again.
function notesEdMoveBlock(ctx,dir){
const r=ctx.range
const keep=r&&ctx.block.contains(r.startContainer)&&ctx.block.contains(r.endContainer)?{sc:r.startContainer,so:r.startOffset,ec:r.endContainer,eo:r.endOffset}:null
notesProMoveBlock(ctx.block,dir)
if(!keep)return
try{const n=document.createRange();n.setStart(keep.sc,keep.so);n.setEnd(keep.ec,keep.eo);notesEdSelect(n)}catch(e){}
}
function notesEdDuplicateBlock(block){
const clone=block.cloneNode(true)
clone.querySelectorAll("[id]").forEach((n)=>n.removeAttribute("id"))
clone.classList.remove("note-block-hover","note-block-dragging")
const cards=clone.matches(".cmd-card-embed")?[clone]:Array.from(clone.querySelectorAll(".cmd-card-embed"))
let out=clone
cards.forEach((c)=>{
const data=notesState.cmdCards[c.dataset.cid]
if(!data){if(c===clone)out=null;else c.remove();return}
const cid=notesGenCid()
notesState.cmdCards[cid]=Object.assign({},data)
const fresh=notesRenderCmdCardEmbed(cid,notesState.cmdCards[cid])
if(c===clone)out=fresh;else c.replaceWith(fresh)
})
if(!out)return
block.after(out)
notesMarkDirty()
notesProAfterStructureChange()
out.scrollIntoView({block:"nearest"})
}
function notesEdCopy(text,msg){notesProCopy(text,msg)}
function notesEdPaste(plain){
if(!navigator.clipboard||!navigator.clipboard.readText){showToast("Use Ctrl+V to paste here","error");return}
navigator.clipboard.readText().then((t)=>{
if(!t)return
notesEdFocus()
const range=notesProSel()
if(range&&notesProInside(range,"pre.note-code")){notesProInsertPlain(t.replace(/\r\n?/g,"\n"));notesProScheduleTint();return}
if(!plain&&LoyaMarkdown.looksLikeMarkdown(t)&&notesProPasteMarkdown(t))return
notesExec("insertText",t)
}).catch(()=>showToast("Use Ctrl+V to paste here","error"))
}
function notesEdToTerminal(ctx){
const text=ctx.text.trim()
if(!text)return
if(typeof termState==="undefined"||!termState.enabled||typeof termInsertAtCursor!=="function"){showToast("Enable the Terminal extension in Settings first","error");return}
if(!termState.open)termOpenPanel()
const go=()=>{try{termInsertAtCursor(text);showToast("On the terminal input line - press Enter there to run it")}catch(e){showToast("The terminal is not ready yet","error")}}
setTimeout(go,termState.tabs&&termState.tabs.length?0:350)
}
function notesEdSaveCommand(ctx){
const text=ctx.text.trim()
notesOpenCmdPopover(notesEdAnchor("ins.cmd"))
const ta=document.getElementById("notesCmdCommand")
if(ta){ta.value=text;ta.dispatchEvent(new Event("input",{bubbles:true}))}
const pop=document.getElementById("notesPopover")
if(pop){const hint=document.createElement("p");hint.className="notes-pro-hint";hint.textContent="Insert replaces the selection with a command card. The command is added to Commands when the note is saved.";pop.insertBefore(hint,pop.querySelector(".notes-popover-actions"))}
}
function notesEdToggleSecret(ctx){
if(ctx.secret&&!ctx.hasSel){ctx.secret.classList.toggle("revealed");return}
notesProMaskSelection()
}
const NOTES_ED_RUN={
"style":(ctx,o)=>notesEdOpenStyleMenu(notesEdAnchor("style"),ctx,o),
"style.p":(ctx)=>notesEdStyle("p",ctx),
"style.h1":(ctx)=>notesEdStyle("h1",ctx),
"style.h2":(ctx)=>notesEdStyle("h2",ctx),
"style.h3":(ctx)=>notesEdStyle("h3",ctx),
"style.quote":(ctx)=>notesEdStyle("blockquote",ctx),
"fmt.bold":()=>notesExec("bold"),
"fmt.italic":()=>notesExec("italic"),
"fmt.underline":()=>notesExec("underline"),
"fmt.strike":()=>notesExec("strikeThrough"),
"fmt.color":(ctx,o)=>notesEdColor("text",o),
"fmt.highlight":(ctx,o)=>notesEdColor("highlight",o),
"fmt.sizeDown":()=>notesApplyFontSize(notesCurrentFontSize()-1),
"fmt.sizeUp":()=>notesApplyFontSize(notesCurrentFontSize()+1),
"fmt.size":(ctx,o)=>{if(o.size)notesApplyFontSize(o.size)},
"fmt.code":(ctx)=>notesEdInlineCode(ctx),
"fmt.clear":(ctx)=>notesEdClearFormat(ctx),
"list.bullet":()=>notesExec("insertUnorderedList"),
"list.number":()=>notesExec("insertOrderedList"),
"list.check":()=>notesProInsertChecklist(false),
"align.left":(ctx)=>notesEdAlign("left",ctx),
"align.center":(ctx)=>notesEdAlign("center",ctx),
"align.right":(ctx)=>notesEdAlign("right",ctx),
"ins.link":(ctx)=>notesEdOpenLink(ctx),
"ins.image":()=>notesHostEl("notesAttachmentFileInput").click(),
"ins.cmd":()=>notesOpenCmdPopover(notesEdAnchor("ins.cmd")),
"ins.finding":()=>notesProInsertFinding(),
"ins.table":()=>notesInsertTable(3,3),
"ins.pickcmd":()=>notesOpenPickCommand(),
"ins.code":(ctx,o)=>{if(o.convert&&!ctx.hasSel&&ctx.block&&ctx.block.matches("p,div,h1,h2,h3,h4,blockquote"))notesEdConvertBlock(ctx.block,"pre");else if(ctx.hasSel){notesEdSelect(ctx.range);notesProInsertCode("",ctx.text)}else notesProInsertCode("")},
"ins.divider":()=>notesExec("insertHorizontalRule"),
"ins.time":()=>notesProInsertTimestamp(),
"ins.drawing":()=>notesProInsertSketch(),
"callout.finding":(ctx,o)=>notesEdCallout("finding",ctx,o),
"callout.vuln":(ctx,o)=>notesEdCallout("vuln",ctx,o),
"callout.info":(ctx,o)=>notesEdCallout("info",ctx,o),
"callout.warning":(ctx,o)=>notesEdCallout("warning",ctx,o),
"callout.credential":(ctx)=>notesProOpenCredentialForm(ctx.hasSel?NotesEd.parseCredential(ctx.text):null,notesEdAnchor("callout.credential")),
"callout.evidence":(ctx,o)=>notesEdCallout("evidence",ctx,o),
"pt.output":(ctx)=>notesEdOpenOutput(ctx),
"pt.nmap":(ctx)=>notesEdOpenNmap(ctx),
"pt.mitre":(ctx)=>notesEdOpenMitre(ctx),
"pt.cvss":(ctx)=>notesEdOpenCvss(ctx),
"pt.cve":(ctx)=>{if(typeof cveNotesOpenInsert==="function")cveNotesOpenInsert(ctx)},
"pt.ioc":()=>notesProOpenIoc(notesEdAnchor("pt.ioc")),
"pt.encode":(ctx,o)=>notesEdOpenEncode(ctx,o.op),
"pt.hash":(ctx)=>notesEdOpenHash(ctx),
"pt.defang":(ctx)=>{const n=notesProReplaceInRange(ctx.range,NotesPro.iocDefangText);showToast(n?"Selection defanged":"Nothing to defang in the selection")},
"pt.refang":(ctx)=>{const n=notesProReplaceInRange(ctx.range,NotesPro.iocRefang);showToast(n?"Selection refanged":"Nothing to refang in the selection")},
"pt.terminal":(ctx)=>notesEdToTerminal(ctx),
"pt.savecmd":(ctx)=>notesEdSaveCommand(ctx),
"pt.wrapcode":(ctx)=>{notesEdSelect(ctx.range);notesProInsertCode("",ctx.text)},
"pt.evidence":(ctx)=>notesEdOpenEvidence(ctx),
"pt.secret":()=>notesProMaskSelection(),
"pt.copysecret":(ctx)=>notesEdCopy(ctx.secret.textContent||"","Secret copied"),
"pt.copymd":(ctx)=>notesEdCopy(notesEdMarkdown(ctx),ctx.hasSel?"Selection copied as Markdown":"Note copied as Markdown"),
"pt.copytext":(ctx)=>{const body=notesEdBody();notesEdCopy(ctx.hasSel?ctx.text:(body.innerText||body.textContent||"").replace(/​/g,""),ctx.hasSel?"Selection copied as plain text":"Note copied as plain text")},
"block.up":(ctx)=>notesEdMoveBlock(ctx,-1),
"block.down":(ctx)=>notesEdMoveBlock(ctx,1),
"block.dup":(ctx)=>notesEdDuplicateBlock(ctx.block),
"block.del":(ctx)=>notesProDeleteBlock(ctx.block),
"tbl.rowAbove":(ctx)=>notesTableOp(ctx.cell,"rowAbove"),
"tbl.rowBelow":(ctx)=>notesTableOp(ctx.cell,"rowBelow"),
"tbl.colLeft":(ctx)=>notesTableOp(ctx.cell,"colLeft"),
"tbl.colRight":(ctx)=>notesTableOp(ctx.cell,"colRight"),
"tbl.header":(ctx)=>notesProToggleHeaderRow(ctx.cell.closest("table")),
"tbl.delRow":(ctx)=>notesTableOp(ctx.cell,"delRow"),
"tbl.delCol":(ctx)=>notesTableOp(ctx.cell,"delCol"),
"tbl.delTable":(ctx)=>notesTableOp(ctx.cell,"delTable"),
"view.undo":()=>notesUndoUndo(),
"view.redo":()=>notesUndoRedo(),
"view.find":()=>notesFindOpen(),
"view.outline":()=>notesProToggleOutline(),
"view.pairs":()=>{const off=!(notesEdPrefs().auto_pairs_off===true);notesEdSetPref("auto_pairs_off",off);showToast(off?"Auto-close brackets is off":"Auto-close brackets is on")},
"view.bubble":()=>{const off=!(notesEdPrefs().editor_bubble_off===true);notesEdSetPref("editor_bubble_off",off);showToast(off?"Selection toolbar is off":"Selection toolbar is on")},
"view.remoteImages":()=>{const on=!(notesEdPrefs().block_remote_images!==false);notesEdSetPref("block_remote_images",on);showToast(on?"Remote images are blocked until clicked":"Remote images load automatically")},
"clip.cut":()=>{document.execCommand("cut");notesMarkDirty()},
"clip.copy":()=>document.execCommand("copy"),
"clip.paste":()=>notesEdPaste(false),
"clip.pastePlain":()=>notesEdPaste(true),
"card.edit":(ctx)=>notesOpenCmdPopover(notesEdAnchor("ins.cmd"),ctx.card.dataset.cid),
"card.copy":(ctx)=>{const d=notesState.cmdCards[ctx.card.dataset.cid];if(d)notesEdCopy(d.command||"","Command copied")},
"card.delete":(ctx)=>notesDeleteCmdCard(ctx.card),
"link.open":(ctx)=>notesHandleLinkClick(ctx.link,{preventDefault(){}},true),
"link.remove":(ctx)=>{const a=ctx.link,p=a.parentNode;while(a.firstChild)p.insertBefore(a.firstChild,a);a.remove();notesMarkDirty()},
"secret.toggle":(ctx)=>notesEdToggleSecret(ctx),
"callout.settings":(ctx)=>notesProOpenCalloutSettings(ctx.callout,notesEdAnchor()),
"code.lang":(ctx)=>notesProOpenLangPopover(ctx.pre,notesEdAnchor()),
"code.copy":(ctx)=>notesEdCopy(notesProCodeText(ctx.pre),"Code copied")
}
// Which commands show as "on" for the current caret.
const NOTES_ED_ACTIVE={
"fmt.bold":()=>document.queryCommandState("bold"),
"fmt.italic":()=>document.queryCommandState("italic"),
"fmt.underline":()=>document.queryCommandState("underline"),
"fmt.strike":()=>document.queryCommandState("strikeThrough"),
"fmt.code":(ctx)=>{const c=ctx.el&&ctx.el.closest?ctx.el.closest("code"):null;return !!c&&!c.closest("pre")},
"list.bullet":(ctx)=>{const l=ctx.el&&ctx.el.closest?ctx.el.closest("ul,ol"):null;return !!l&&l.tagName==="UL"&&!l.classList.contains("note-checklist")},
"list.number":(ctx)=>{const l=ctx.el&&ctx.el.closest?ctx.el.closest("ul,ol"):null;return !!l&&l.tagName==="OL"},
"list.check":(ctx)=>{const l=ctx.el&&ctx.el.closest?ctx.el.closest("ul,ol"):null;return !!l&&l.classList.contains("note-checklist")},
"align.center":()=>document.queryCommandState("justifyCenter"),
"align.right":()=>document.queryCommandState("justifyRight"),
"style.p":(ctx)=>notesEdStyleOf(ctx).tag==="p",
"style.h1":(ctx)=>notesEdStyleOf(ctx).tag==="h1",
"style.h2":(ctx)=>notesEdStyleOf(ctx).tag==="h2",
"style.h3":(ctx)=>notesEdStyleOf(ctx).tag==="h3",
"style.quote":(ctx)=>notesEdStyleOf(ctx).tag==="blockquote",
"pt.secret":(ctx)=>!!ctx.secret&&!ctx.hasSel,
"view.outline":()=>notesProOutlineOpen(),
"view.pairs":()=>!(notesEdPrefs().auto_pairs_off===true),
"view.bubble":()=>!(notesEdPrefs().editor_bubble_off===true),
"view.remoteImages":()=>notesEdPrefs().block_remote_images!==false
}
function notesEdIsActive(id,ctx){
const fn=NOTES_ED_ACTIVE[id]
if(!fn||!ctx)return false
if(!ctx.range&&!id.startsWith("view."))return false
try{return !!fn(ctx)}catch(e){return false}
}
function notesEdCallout(kind,ctx,o){
if(o&&o.convert&&!ctx.hasSel&&ctx.block&&!ctx.block.matches(".note-callout,.cmd-card-embed,figure")){notesEdConvertBlock(ctx.block,"callout:"+kind);return}
if(ctx.hasSel)notesEdSelect(ctx.range)
notesProInsertCallout(kind)
}
// ---------------------------------------------------------------- tool elements (toolbar, More panel, bubble)
function notesEdIconHtml(c){
if(c.icon)return `<i class="icon icon-${c.icon}"></i>`
return `<span class="notes-ed-glyph">${notesEscapeHtml(c.glyph||c.label.slice(0,1))}</span>`
}
function notesEdToolHtml(id,where){
const c=NotesEd.get(id)
if(!c)return ""
const t=notesEscapeHtml(NotesEd.title(c))
const tile=where==="more"
const label=tile?`<span class="notes-ed-tile-label">${notesEscapeHtml(c.label)}</span>${c.shortcut?`<span class="notes-ed-kbd">${notesEscapeHtml(c.shortcut)}</span>`:""}`:""
if(c.kind==="style"&&!tile)return `<button type="button" class="notes-ed-style" data-ed="style" title="${t}" aria-haspopup="menu"><span class="notes-ed-style-label">Normal</span><i class="icon icon-caret-down"></i></button>`
if(c.kind==="style")return `<button type="button" class="notes-ed-tile" data-ed="style" title="${t}"><i class="icon icon-pilcrow"></i>${label}</button>`
if(c.kind==="size"){
const ctl=`<button type="button" class="notes-tb-btn" data-act="minus" title="Smaller text (Ctrl+Shift+,)" aria-label="Smaller text"><i class="icon icon-font-smaller"></i></button><input type="text" class="notes-font-size-input notes-ed-size-input" list="notesFontSizePresets" title="Font size of the selected text" aria-label="Font size" inputmode="numeric" autocomplete="off"><button type="button" class="notes-tb-btn" data-act="plus" title="Larger text (Ctrl+Shift+.)" aria-label="Larger text"><i class="icon icon-font-bigger"></i></button>`
return tile?`<div class="notes-ed-tile notes-ed-tile-size" data-ed="fmt.size" title="${t}"><span class="notes-ed-size">${ctl}</span>${label}</div>`:`<span class="notes-ed-size" data-ed="fmt.size">${ctl}</span>`
}
if(c.kind==="color"){
const sw=`<span class="notes-tb-color-swatch ${id==="fmt.color"?"text notes-ed-swatch-text":"highlight notes-ed-swatch-highlight"}"></span>`
if(where==="bar")return `<span class="notes-ed-split" data-ed="${id}"><button type="button" class="notes-tb-color" data-act="main" title="${notesEscapeHtml(c.label+(c.shortcut?" ("+c.shortcut+")":"")+" - apply the current colour")}" aria-label="${notesEscapeHtml(c.label)}"><i class="icon icon-${c.icon}"></i>${sw}</button><button type="button" class="notes-ed-split-arrow" data-act="arrow" title="${notesEscapeHtml(c.label)} palette" aria-label="${notesEscapeHtml(c.label)} palette" aria-haspopup="true"><i class="icon icon-caret-down"></i></button></span>`
if(tile)return `<button type="button" class="notes-ed-tile" data-ed="${id}" title="${t}"><span class="notes-tb-color"><i class="icon icon-${c.icon}"></i>${sw}</span>${label}</button>`
return `<button type="button" class="notes-tb-color" data-ed="${id}" title="${t}" aria-label="${notesEscapeHtml(c.label)}"><i class="icon icon-${c.icon}"></i>${sw}</button>`
}
if(tile)return `<button type="button" class="notes-ed-tile${c.danger?" danger":""}" data-ed="${id}" title="${t}">${notesEdIconHtml(c)}${label}</button>`
return `<button type="button" class="notes-tb-btn${c.icon?"":" notes-tb-text"}" data-ed="${id}" title="${t}" aria-label="${notesEscapeHtml(c.label)}">${notesEdIconHtml(c)}</button>`
}
function notesEdKeepSelection(e){
if(e.target.closest("input,textarea,select"))return
e.preventDefault()
}
function notesEdToolClick(e,where){
const el=e.target.closest("[data-ed]")
if(!el||el.disabled||e.target.closest("input"))return
const id=el.dataset.ed
const actEl=e.target.closest("[data-act]")
const act=actEl&&el.contains(actEl)?actEl.dataset.act:""
if(where==="more"&&notesEdState.customise){notesEdTogglePin(id);return}
if(el.matches("div")&&!act)return
if(act&&actEl.disabled)return
let anchor=notesEdRectAnchor(el)
if(where==="more"){anchor=null;notesEdMoreClose()}
if(id==="fmt.size"){if(act==="minus")notesEdRun("fmt.sizeDown",{source:where});else if(act==="plus")notesEdRun("fmt.sizeUp",{source:where});return}
notesEdRun(id,{anchor,source:where,pick:where!=="bar"||act==="arrow"})
}
function notesEdSizeChange(e){
const input=e.target.closest(".notes-ed-size-input")
if(!input)return
const v=parseInt(input.value,10)
if(!isNaN(v))notesApplyFontSize(v)
else notesUpdateFontSizeDisplay()
}
// Left / Right move between the tools of a bar once the keyboard is in it; Escape goes back to the text with the selection intact.
function notesEdRovingKeys(e,root){
if(e.target.closest("input")&&e.key!=="Escape"){if(e.key==="Enter"){e.preventDefault();e.target.blur();notesEdFocus()}return}
const keys=["ArrowLeft","ArrowRight","Home","End","Escape"]
if(!keys.includes(e.key))return
e.preventDefault();e.stopPropagation()
if(e.key==="Escape"){notesEdBody().focus();notesRestoreRange();return}
const items=Array.from(root.querySelectorAll("button:not(:disabled),input")).filter((b)=>b.offsetParent!==null)
if(!items.length)return
const i=items.indexOf(document.activeElement)
const next=e.key==="Home"?0:e.key==="End"?items.length-1:(i+(e.key==="ArrowRight"?1:-1)+items.length)%items.length
items[next].focus()
}
// ---------------------------------------------------------------- main toolbar
function notesEdRenderBar(bar){
const tb=bar.el
const parts=NotesEd.barItems(notesEdPins().filter(notesEdAllowedFor(bar))).map((it)=>it.sep?'<span class="notes-toolbar-sep"></span>':notesEdToolHtml(it.id,"bar"))
parts.push('<button type="button" class="notes-tb-btn notes-ed-more-btn" title="More tools, and customise the toolbar" aria-label="More tools" aria-haspopup="true" aria-expanded="false"><i class="icon icon-dots"></i><span>More</span></button>')
tb.innerHTML=parts.join("")
tb.querySelector(".notes-ed-more-btn").addEventListener("click",(e)=>{e.stopPropagation();notesEdMoreToggle(bar)})
notesEdFit(bar)
}
function notesEdAllowedFor(bar){
const f=bar.host&&bar.host.features
return (id)=>{const c=NotesEd.get(id);return !f||!(f[id]===false||(c&&f["group:"+c.group]===false))}
}
function notesEdRenderToolbar(){
notesEdState.bars.forEach(notesEdRenderBar)
notesEdRefresh()
}
// Tools that do not fit the editor's width are hidden here and listed first in the More panel.
function notesEdFit(bar){
const tb=bar.el
const more=tb.querySelector(".notes-ed-more-btn")
if(!more)return
const kids=Array.from(tb.children).filter((k)=>k!==more)
kids.forEach((k)=>k.classList.remove("notes-ed-overflowed"))
const cs=getComputedStyle(tb)
const gap=parseFloat(cs.columnGap)||0
const avail=tb.clientWidth-(parseFloat(cs.paddingLeft)||0)-(parseFloat(cs.paddingRight)||0)
bar.width=tb.clientWidth
bar.overflow=[]
if(avail<=0)return
const widths=kids.map((k)=>k.offsetWidth+(parseFloat(getComputedStyle(k).marginLeft)||0)+(parseFloat(getComputedStyle(k).marginRight)||0))
let n=NotesEd.fitCount(widths,avail,gap,more.offsetWidth)
while(n>0&&kids[n-1].classList.contains("notes-toolbar-sep"))n--
kids.slice(n).forEach((k)=>{k.classList.add("notes-ed-overflowed");if(k.dataset.ed)bar.overflow.push(k.dataset.ed)})
more.classList.toggle("has-overflow",bar.overflow.length>0)
}
function notesEdRefreshSoon(){
if(notesEdState.refreshRaf)return
notesEdState.refreshRaf=requestAnimationFrame(()=>{notesEdState.refreshRaf=0;notesEdRefresh()})
}
// Enabled / active state of every visible tool, the style label, the font size and the colour swatches.
function notesEdRefresh(){
const body=notesEdBody()
if(!body||!notesHostOpen())return
const sel=window.getSelection()
const live=sel&&sel.rangeCount&&body.contains(sel.getRangeAt(0).startContainer)
if(!live&&document.activeElement&&document.activeElement.closest&&document.activeElement.closest("#notesPopover"))return
const ctx=notesEdContext()
const bar=notesEdBar()
const roots=[bar&&bar.el,document.getElementById("notesEdMore"),document.getElementById("notesEdBubble")].filter(Boolean)
roots.forEach((root)=>{
root.querySelectorAll("[data-ed]").forEach((el)=>{
const c=NotesEd.get(el.dataset.ed)
if(!c)return
const on=notesEdState.customise&&root.id==="notesEdMore"?true:notesEdEnabled(c,ctx)
if(root.id==="notesEdBubble")el.classList.toggle("hidden",!notesEdAllowed(c.id))
if(el.tagName==="BUTTON")el.disabled=!on
else el.querySelectorAll("button,input").forEach((b)=>{b.disabled=!on})
el.classList.toggle("is-disabled",!on)
const active=notesEdIsActive(c.id,ctx)
const target=el.matches(".notes-ed-split")?el.querySelector(".notes-tb-color"):el
target.classList.toggle("active",active)
if(el.tagName==="BUTTON"&&NOTES_ED_ACTIVE[c.id])el.setAttribute("aria-pressed",active?"true":"false")
})
})
const st=notesEdStyleOf(ctx)
if(bar)bar.el.querySelectorAll(".notes-ed-style-label").forEach((l)=>{l.textContent=st.label})
notesUpdateFontSizeDisplay()
notesEdSyncColors()
}
function notesEdOpenStyleMenu(anchor,ctx){
const r=anchor.getBoundingClientRect()
const cur=notesEdStyleOf(ctx).tag
const row=(id,tag,cls)=>({cmd:id,cls,active:cur===tag})
notesEdMenuOpen([row("style.p","p","notes-ed-st-p"),row("style.h1","h1","notes-ed-st-h1"),row("style.h2","h2","notes-ed-st-h2"),row("style.h3","h3","notes-ed-st-h3"),row("style.quote","blockquote","notes-ed-st-quote"),{cmd:"ins.code",label:"Code block",cls:"notes-ed-st-code",active:cur==="pre",opts:{convert:true}}],r.left,r.bottom+4,{ctx})
}
// ---------------------------------------------------------------- More panel and customise
function notesEdMoreClose(){
const p=document.getElementById("notesEdMore")
if(p)p.remove()
document.removeEventListener("mousedown",notesEdMoreOutside,true)
document.querySelectorAll(".notes-ed-more-btn").forEach((btn)=>{btn.classList.remove("active");btn.setAttribute("aria-expanded","false")})
notesEdState.customise=false
notesEdState.moreBar=null
}
function notesEdMoreOutside(e){
const p=document.getElementById("notesEdMore")
if(p&&!p.contains(e.target)&&!e.target.closest(".notes-ed-more-btn"))notesEdMoreClose()
}
function notesEdMoreToggle(bar){
if(document.getElementById("notesEdMore")){notesEdMoreClose();return}
notesEdMenuClose();notesEdBubbleHide();notesClosePopover()
notesEdState.moreBar=bar||notesEdBar()
if(!notesEdState.moreBar)return
const p=document.createElement("div")
p.id="notesEdMore"
p.className="notes-ed-more"
p.setAttribute("role","dialog")
p.setAttribute("aria-label","More editor tools")
p.addEventListener("mousedown",notesEdKeepSelection)
p.addEventListener("click",(e)=>{
if(e.target.closest("#notesEdCustomise")){notesEdState.customise=!notesEdState.customise;notesEdMoreRender();return}
if(e.target.closest("#notesEdResetBar")){notesEdSavePins(NotesEd.defaultMain());return}
notesEdToolClick(e,"more")
})
p.addEventListener("change",notesEdSizeChange)
p.addEventListener("keydown",(e)=>{if(e.key==="Escape"){e.preventDefault();e.stopPropagation();notesEdMoreClose();notesEdFocus()}})
document.body.appendChild(p)
const btn=notesEdState.moreBar.el.querySelector(".notes-ed-more-btn")
btn.classList.add("active");btn.setAttribute("aria-expanded","true")
notesEdMoreRender()
setTimeout(()=>document.addEventListener("mousedown",notesEdMoreOutside,true),0)
}
function notesEdMoreRender(){
const p=document.getElementById("notesEdMore")
const bar=notesEdState.moreBar
if(!p||!bar)return
const allowed=notesEdAllowedFor(bar)
const custom=notesEdState.customise
const pins=notesEdPins()
const scroll=p.querySelector(".notes-ed-more-body")
const keep=scroll?scroll.scrollTop:0
let h=`<div class="notes-ed-more-head"><span class="notes-ed-more-title">${custom?"Customise the toolbar":"More tools"}</span>${custom?'<button type="button" class="notes-ed-more-act" id="notesEdResetBar">Reset to default</button>':""}<button type="button" class="notes-ed-more-act${custom?" active":""}" id="notesEdCustomise" aria-pressed="${custom?"true":"false"}"><i class="icon icon-${custom?"check":"sliders"}"></i><span>${custom?"Done":"Customise"}</span></button></div>`
if(custom)h+='<p class="notes-ed-more-hint">Click a tool to pin it to the toolbar or take it off. Pinned tools are marked. When the editor is narrow, the last tools move in here on their own.</p>'
h+='<div class="notes-ed-more-body">'
NotesEd.moreSections(pins,bar.overflow,custom).forEach((s)=>{
s.items=s.items.filter(allowed)
if(!s.items.length)return
h+=`<div class="notes-ed-more-sec" data-sec="${s.id}"><div class="notes-ed-more-label">${notesEscapeHtml(s.label)}</div><div class="notes-ed-more-grid">`
s.items.forEach((id)=>{
if(custom){
const c=NotesEd.get(id)
const on=pins.includes(id)
h+=`<button type="button" class="notes-ed-tile notes-ed-tile-pin${on?" pinned":""}" data-ed="${id}" aria-pressed="${on?"true":"false"}" title="${on?"On the toolbar - click to take it off":"Click to pin it to the toolbar"}">${c.kind==="style"?'<i class="icon icon-pilcrow"></i>':c.kind==="size"?'<i class="icon icon-font-bigger"></i>':notesEdIconHtml(c)}<span class="notes-ed-tile-label">${notesEscapeHtml(c.label)}</span><i class="icon icon-pin notes-ed-pin-mark"></i></button>`
}else h+=notesEdToolHtml(id,"more")
})
h+="</div></div>"
})
h+="</div>"
p.innerHTML=h
const btn=bar.el.querySelector(".notes-ed-more-btn").getBoundingClientRect()
const w=p.offsetWidth
p.style.left=Math.round(Math.max(8,Math.min(btn.right-w,window.innerWidth-w-8)))+"px"
p.style.top=Math.round(btn.bottom+8)+"px"
p.style.maxHeight=Math.max(180,window.innerHeight-btn.bottom-20)+"px"
const body=p.querySelector(".notes-ed-more-body")
if(body)body.scrollTop=keep
notesEdRefresh()
}
function notesEdSavePins(pins){
const next=NotesEd.normPins(pins)
notesEdSetPref("toolbar_main",next)
notesEdRenderToolbar()
notesEdMoreRender()
}
function notesEdTogglePin(id){notesEdSavePins(NotesEd.togglePin(notesEdPins(),id))}
// ---------------------------------------------------------------- selection bubble
function notesEdBubbleEl(){
let b=document.getElementById("notesEdBubble")
if(b)return b
b=document.createElement("div")
b.id="notesEdBubble"
b.className="notes-ed-bubble hidden"
b.setAttribute("role","toolbar")
b.setAttribute("aria-label","Selection tools")
b.innerHTML=NotesEd.bubbleItems().map((id)=>id==="-"?'<span class="notes-toolbar-sep"></span>':notesEdToolHtml(id,"bubble")).join("")+'<span class="notes-toolbar-sep"></span><button type="button" class="notes-tb-btn notes-ed-bubble-more" id="notesEdBubbleMore" title="Pentest and selection tools: encode, hash, defang, send to terminal, evidence..." aria-label="Selection tools" aria-haspopup="menu"><i class="icon icon-shield"></i><i class="icon icon-caret-down"></i></button>'
b.addEventListener("mousedown",notesEdKeepSelection)
b.addEventListener("click",(e)=>{
const more=e.target.closest("#notesEdBubbleMore")
if(more){
const r=more.getBoundingClientRect()
const ctx=notesEdContext()
notesEdMenuOpen(notesEdBubbleMenuModel(),r.left,r.bottom+6,{ctx,keepBubble:true,anchor:notesEdRectAnchor(b)})
return
}
notesEdToolClick(e,"bubble")
})
b.addEventListener("keydown",(e)=>notesEdRovingKeys(e,b))
document.body.appendChild(b)
return b
}
function notesEdBubbleMenuModel(){
return NotesEd.bubbleMenuItems().filter((id)=>id==="-"||notesEdAllowed(id)).map((id)=>id==="pt.encode"?{label:"Encode / decode",icon:"shuffle",items:NotesEd.TRANSFORMS.map((t)=>({op:t.id,label:t.label}))}:id)
}
function notesEdBubbleHide(){
if(notesEdState.bubbleTimer){clearTimeout(notesEdState.bubbleTimer);notesEdState.bubbleTimer=null}
const b=document.getElementById("notesEdBubble")
if(b)b.classList.add("hidden")
}
function notesEdBubbleSoon(ms){
if(notesEdState.bubbleTimer)clearTimeout(notesEdState.bubbleTimer)
notesEdState.bubbleTimer=setTimeout(()=>{notesEdState.bubbleTimer=null;notesEdBubbleUpdate()},ms||0)
}
function notesEdBubbleVisible(){
const b=document.getElementById("notesEdBubble")
return !!b&&!b.classList.contains("hidden")
}
function notesEdBubbleUpdate(){
const body=notesEdBody()
if(!body)return
const sel=window.getSelection()
const ok=notesHostOpen()&&notesEdPrefs().editor_bubble_off!==true&&!notesEdState.mouseDown&&sel&&sel.rangeCount&&!sel.isCollapsed&&body.contains(sel.getRangeAt(0).commonAncestorContainer)&&document.activeElement===body&&!notesEdState.menu&&!document.getElementById("notesPopover")&&!document.getElementById("notesEdMore")&&!document.getElementById("notesSlashMenu")&&!(typeof notesDrawIsOpen==="function"&&notesDrawIsOpen())
if(!ok||!sel.toString().trim()){if(!(document.activeElement&&document.activeElement.closest&&document.activeElement.closest("#notesEdBubble")))notesEdBubbleHide();return}
const range=sel.getRangeAt(0)
const rects=Array.from(range.getClientRects()).filter((r)=>r.width>0&&r.height>0)
const box=range.getBoundingClientRect()
if(!rects.length&&!box.height){notesEdBubbleHide();return}
const first=rects[0]||box
const wrap=(notesHostWrap()||body).getBoundingClientRect()
const b=notesEdBubbleEl()
b.classList.remove("hidden")
notesEdRefresh()
const w=b.offsetWidth,h=b.offsetHeight
// Above the first selected line when there is room inside the editor, otherwise under the last one; always inside the editor and the window.
let top=first.top-h-8
if(top<wrap.top+2)top=Math.min(box.bottom+8,wrap.bottom-h-2)
if(box.bottom<wrap.top||first.top>wrap.bottom){notesEdBubbleHide();return}
const mid=rects.length>1?first.left+first.width/2:box.left+box.width/2
const minL=Math.max(8,wrap.left+2),maxL=Math.min(window.innerWidth-w-8,wrap.right-w-2)
b.style.left=Math.round(Math.max(minL,Math.min(mid-w/2,Math.max(minL,maxL))))+"px"
b.style.top=Math.round(Math.max(8,Math.min(top,window.innerHeight-h-8)))+"px"
}
// ---------------------------------------------------------------- menus with submenus (right-click, style dropdown, bubble tools)
// model items: "cmd.id" | "-" | {cmd,label,cls,active,opts} | {label,icon,items} | {strip:[ids]} | {palette:"text"|"highlight"} | {sizes:[..]} | {op,label}
function notesEdMenuClose(){
const m=notesEdState.menu
if(!m)return
m.panels.forEach((p)=>p.el.remove())
if(m.timer)clearTimeout(m.timer)
document.removeEventListener("mousedown",notesEdMenuOutside,true)
notesEdState.menu=null
}
function notesEdMenuOutside(e){
const m=notesEdState.menu
if(m&&!m.panels.some((p)=>p.el.contains(e.target)))notesEdMenuClose()
}
function notesEdMenuOpen(model,x,y,opts){
notesEdMenuClose()
closeContextMenu()
const o=opts||{}
if(!o.keepBubble)notesEdBubbleHide()
notesEdState.menu={panels:[],ctx:o.ctx||notesEdContext(),anchor:o.anchor||notesEdPointAnchor(x,y),timer:null}
notesEdMenuPanel(model,{x,y},null)
setTimeout(()=>document.addEventListener("mousedown",notesEdMenuOutside,true),0)
}
function notesEdMenuRun(id,opts){
const m=notesEdState.menu
if(!m)return
const ctx=m.ctx,anchor=m.anchor
notesEdMenuClose()
notesEdRun(id,Object.assign({ctx,anchor,source:"menu",pick:true},opts||{}))
}
function notesEdMenuPanel(items,pos,parentRow){
const m=notesEdState.menu
const depth=parentRow?m.panels.findIndex((p)=>p.el.contains(parentRow))+1:0
while(m.panels.length>depth)m.panels.pop().el.remove()
const el=document.createElement("div")
el.className="notes-ed-menu app-context-menu glass-panel"
el.setAttribute("role","menu")
const panel={el,rows:[],index:-1,parentRow}
const ctx=m.ctx
const addRow=(html,cls,run,sub,disabled,active)=>{
const b=document.createElement("button")
b.type="button"
b.className="app-context-menu-item notes-ed-menu-item"+(cls?" "+cls:"")+(active?" checked":"")
b.setAttribute("role",active!==undefined?"menuitemcheckbox":"menuitem")
if(active!==undefined)b.setAttribute("aria-checked",active?"true":"false")
b.disabled=!!disabled
b.innerHTML=html
const row={el:b,run,sub}
panel.rows.push(row)
b.addEventListener("mouseenter",()=>{if(b.disabled)return;notesEdMenuSetIndex(panel,panel.rows.indexOf(row));notesEdMenuHover(panel,row)})
b.addEventListener("click",()=>{if(b.disabled)return;if(sub)notesEdMenuOpenSub(panel,row);else run()})
el.appendChild(b)
return b
}
const rowHtml=(icon,glyph,label,shortcut,sub)=>`${icon?`<i class="icon icon-${icon}"></i>`:glyph?`<span class="notes-ed-glyph">${notesEscapeHtml(glyph)}</span>`:'<span class="notes-ed-menu-noicon"></span>'}<span class="notes-ed-menu-label">${notesEscapeHtml(label)}</span>${shortcut?`<span class="notes-ed-kbd">${notesEscapeHtml(shortcut)}</span>`:""}${sub?'<i class="icon icon-caret-right notes-ed-menu-caret"></i>':""}`
let lastSep=true
items.forEach((it)=>{
if(it==="-"){if(!lastSep){const s=document.createElement("div");s.className="app-context-menu-sep";el.appendChild(s);lastSep=true}return}
lastSep=false
if(typeof it==="string"||it.cmd){
const id=typeof it==="string"?it:it.cmd
const c=NotesEd.get(id)||NotesEd.MENU_LOCAL.find((x)=>x.id===id)
if(!c||!NOTES_ED_RUN[id]||!notesEdAllowed(id)){lastSep=el.lastChild?el.lastChild.classList.contains("app-context-menu-sep"):true;return}
const reg=NotesEd.get(id)
const active=it.active!==undefined?it.active:(NOTES_ED_ACTIVE[id]?notesEdIsActive(id,ctx):undefined)
let label=it.label||notesEdHostLabel(id)||c.menuLabel||c.label
if(id==="pt.secret"&&ctx.secret&&!ctx.hasSel)label="Unmask secret"
if(id==="link.open"&&ctx.link&&/^notelink:/i.test(ctx.link.getAttribute("href")||""))label="Open linked note"
const b=addRow(rowHtml(c.icon,c.glyph,label,c.shortcut,false),(c.danger?"danger ":"")+(it.cls||""),()=>notesEdMenuRun(id,it.opts),null,reg?!notesEdEnabled(reg,ctx):false,active)
if(reg&&reg.hint)b.title=reg.hint
return
}
if(it.custom){const cu=it.custom;addRow(rowHtml(cu.icon,"",String(cu.label||""),"",false),cu.danger?"danger":"",()=>{notesEdMenuClose();if(cu.fn)cu.fn()},null,!!cu.disabled);return}
if(it.op){addRow(rowHtml("","",it.label,"",false),"",()=>notesEdMenuRun("pt.encode",{op:it.op}),null,false);return}
if(it.items){
const live=NotesEd.menuIds(it.items).some((id)=>notesEdAllowed(id)&&NOTES_ED_RUN[id])||it.items.some((x)=>x&&(x.op||x.palette||x.sizes))
if(!live){lastSep=el.lastChild?el.lastChild.classList.contains("app-context-menu-sep"):true;return}
addRow(rowHtml(it.icon,"",it.label,"",true),"notes-ed-menu-parent",null,it.items,false)
return
}
if(it.strip){
const row=document.createElement("div")
row.className="notes-ed-menu-strip"
row.innerHTML=it.strip.filter(notesEdAllowed).map((id)=>notesEdToolHtml(id,"bubble")).join("")
row.querySelectorAll("[data-ed]").forEach((b)=>{
const c=NotesEd.get(b.dataset.ed)
b.disabled=!notesEdEnabled(c,ctx)
b.classList.toggle("active",notesEdIsActive(c.id,ctx))
b.addEventListener("click",()=>notesEdMenuRun(c.id))
panel.rows.push({el:b,run:()=>notesEdMenuRun(c.id),strip:true})
})
el.appendChild(row)
return
}
if(it.palette){
const text=it.palette==="text"
const grid=document.createElement("div")
grid.className="notes-ed-menu-palette"
const cur=NotesPro.normHex((text?notesEdSelColors(ctx).text:notesEdSelColors(ctx).highlight)||"")
const colors=(text?NotesPro.SEVERITIES.map((s)=>s.color):[]).concat(text?NOTES_TEXT_COLORS:NOTES_HIGHLIGHT_COLORS).filter((c,i,a)=>a.indexOf(c)===i).slice(0,text?24:18)
colors.forEach((c)=>{
const b=document.createElement("button")
b.type="button"
b.className="notes-color-cell"+(cur===NotesPro.normHex(c)?" current":"")
b.style.background=c
b.title=c
const run=()=>{notesRememberColor(c);notesEdMenuRun(text?"fmt.color":"fmt.highlight",{color:c})}
b.addEventListener("click",run)
panel.rows.push({el:b,run,strip:true,cols:6})
grid.appendChild(b)
})
el.appendChild(grid)
if(!text)addRow(rowHtml("close","","No highlight","",false),"",()=>notesEdMenuRun("fmt.highlight",{color:"transparent"}),null,false)
addRow(rowHtml("color","","More colours...","",false),"",()=>notesEdMenuRun(text?"fmt.color":"fmt.highlight",{pick:true}),null,false)
return
}
if(it.sizes){
const row=document.createElement("div")
row.className="notes-ed-menu-sizes"
const cur=notesCurrentFontSize()
it.sizes.forEach((s)=>{
const b=document.createElement("button")
b.type="button"
b.className="notes-pro-pill"+(s===cur?" active":"")
b.textContent=String(s)
b.disabled=!ctx.hasSel
const run=()=>notesEdMenuRun("fmt.size",{size:s})
b.addEventListener("click",run)
panel.rows.push({el:b,run,strip:true})
row.appendChild(b)
})
el.appendChild(row)
}
})
while(el.lastChild&&el.lastChild.classList&&el.lastChild.classList.contains("app-context-menu-sep"))el.lastChild.remove()
el.addEventListener("mousedown",(e)=>e.preventDefault())
el.addEventListener("contextmenu",(e)=>e.preventDefault())
document.body.appendChild(el)
m.panels.push(panel)
// Placed after it is measured, so the menu and every submenu stay inside the window.
const w=el.offsetWidth,vh=window.innerHeight,vw=window.innerWidth
el.style.maxHeight=(vh-16)+"px"
const h=Math.min(el.offsetHeight,vh-16)
let left,top
if(parentRow){
const pr=parentRow.getBoundingClientRect()
left=pr.right+2
if(left+w>vw-8)left=Math.max(8,pr.left-w-2)
top=pr.top-6
}else{left=pos.x;top=pos.y;if(left+w>vw-8)left=Math.max(8,vw-w-8);if(top+h>vh-8&&pos.y-h>8)top=pos.y-h}
el.style.left=Math.round(Math.max(8,left))+"px"
el.style.top=Math.round(Math.max(8,Math.min(top,vh-h-8)))+"px"
return panel
}
function notesEdMenuSetIndex(panel,i){
panel.index=i
panel.rows.forEach((r,k)=>r.el.classList.toggle("kb-active",k===i))
if(i>=0&&panel.rows[i])panel.rows[i].el.scrollIntoView({block:"nearest"})
}
function notesEdMenuCloseAfter(panel){
const m=notesEdState.menu
const d=m.panels.indexOf(panel)
while(m.panels.length>d+1)m.panels.pop().el.remove()
panel.rows.forEach((r)=>r.el.classList.remove("open"))
}
function notesEdMenuOpenSub(panel,row,focusFirst){
const m=notesEdState.menu
if(!m||!row.sub)return
const d=m.panels.indexOf(panel)
if(m.panels[d+1]&&m.panels[d+1].parentRow===row.el){if(focusFirst)notesEdMenuSetIndex(m.panels[d+1],notesEdMenuNext(m.panels[d+1],-1,1));return}
notesEdMenuCloseAfter(panel)
row.el.classList.add("open")
const sub=notesEdMenuPanel(row.sub,null,row.el)
if(focusFirst)notesEdMenuSetIndex(sub,notesEdMenuNext(sub,-1,1))
}
function notesEdMenuHover(panel,row){
const m=notesEdState.menu
if(!m)return
if(m.timer)clearTimeout(m.timer)
m.timer=setTimeout(()=>{
m.timer=null
if(!notesEdState.menu||!document.body.contains(panel.el))return
if(row.sub)notesEdMenuOpenSub(panel,row)
else notesEdMenuCloseAfter(panel)
},row.sub?140:260)
}
function notesEdMenuNext(panel,from,dir){
const n=panel.rows.length
for(let k=1;k<=n;k++){const i=((from+dir*k)%n+n)%n;if(!panel.rows[i].el.disabled)return i}
return -1
}
function notesEdMenuKey(e){
const m=notesEdState.menu
const panel=m.panels[m.panels.length-1]
const key=e.key
if(!["ArrowDown","ArrowUp","ArrowLeft","ArrowRight","Enter"," ","Escape","Home","End","Tab"].includes(key)){if(key.length===1&&!e.ctrlKey&&!e.metaKey&&!e.altKey){
// Typing a letter jumps to the next entry that starts with it.
const k=key.toLowerCase()
const n=panel.rows.length
for(let s=1;s<=n;s++){const i=(Math.max(panel.index,-1)+s)%n;const r=panel.rows[i];if(!r.el.disabled&&!r.strip&&(r.el.textContent||"").trim().toLowerCase().startsWith(k)){notesEdMenuSetIndex(panel,i);break}}
e.preventDefault();e.stopPropagation()
}return}
e.preventDefault();e.stopPropagation()
const row=panel.rows[panel.index]
if(key==="Escape"||key==="Tab"){if(m.panels.length>1&&key==="Escape"){m.panels.pop().el.remove();const p=m.panels[m.panels.length-1];p.rows.forEach((r)=>r.el.classList.remove("open"))}else{notesEdMenuClose();notesEdFocus()}return}
if(key==="ArrowDown"||key==="ArrowUp"){
// Inside an icon strip or a colour grid, Up / Down leave it instead of stepping through every cell.
const dir=key==="ArrowDown"?1:-1
let i=panel.index
if(row&&row.strip){
const group=row.el.parentElement
const jump=row.cols?panel.rows[i+dir*row.cols]:null
if(jump&&jump.el.parentElement===group){notesEdMenuSetIndex(panel,i+dir*row.cols);return}
let k=i;while(panel.rows[k+dir]&&panel.rows[k+dir].el.parentElement===group)k+=dir;i=k
}
notesEdMenuSetIndex(panel,notesEdMenuNext(panel,i,dir))
return
}
if(key==="Home"){notesEdMenuSetIndex(panel,notesEdMenuNext(panel,-1,1));return}
if(key==="End"){notesEdMenuSetIndex(panel,notesEdMenuNext(panel,0,-1));return}
if(key==="ArrowRight"){
if(row&&row.strip){const nx=panel.rows[panel.index+1];if(nx&&nx.strip&&nx.el.parentElement===row.el.parentElement)notesEdMenuSetIndex(panel,notesEdMenuNext(panel,panel.index,1));return}
if(row&&row.sub)notesEdMenuOpenSub(panel,row,true)
return
}
if(key==="ArrowLeft"){
if(row&&row.strip){const pv=panel.rows[panel.index-1];if(pv&&pv.strip&&pv.el.parentElement===row.el.parentElement){notesEdMenuSetIndex(panel,notesEdMenuNext(panel,panel.index,-1));return}}
if(m.panels.length>1){m.panels.pop().el.remove();const p=m.panels[m.panels.length-1];p.rows.forEach((r)=>r.el.classList.remove("open"))}
return
}
if(!row||row.el.disabled)return
if(row.sub)notesEdMenuOpenSub(panel,row,true)
else row.run()
}
function notesEdOpenContextMenu(e,fromKeyboard){
const body=notesEdBody()
let x=e.clientX,y=e.clientY,target=e.target
if(fromKeyboard){
const sel=window.getSelection()
const r=sel.rangeCount?sel.getRangeAt(0):null
let rect=r?r.getBoundingClientRect():null
if(!rect||(!rect.width&&!rect.height&&!rect.top)){const el=r?(r.startContainer.nodeType===1?r.startContainer:r.startContainer.parentElement):body;rect=el.getBoundingClientRect()}
x=rect.left+Math.min(rect.width,24);y=rect.bottom+4;target=null
}
notesClosePopover()
notesEdMoreClose()
const ctx=notesEdContext(target)
const extra=[]
const h=notesEdHost()
if(h&&h.menu){
// A host adds its own entries the way it does for the app's context menu: {label,icon,fn,danger,disabled} or {sep:true}. They are shown first.
try{h.menu(extra,e)}catch(err){console.error("host menu failed",err)}
}
const lead=extra.map((it)=>it.sep?"-":{custom:it})
if(lead.length&&lead[lead.length-1]!=="-")lead.push("-")
notesEdMenuOpen(lead.concat(NotesEd.menuModel({hasSel:ctx.hasSel,card:!!ctx.card,link:!!ctx.link,secret:!!ctx.secret,callout:!!ctx.callout,finding:!!ctx.finding,code:!!ctx.pre,block:!!ctx.block,table:!!ctx.cell})),x,y,{ctx})
if(fromKeyboard){const p=notesEdState.menu.panels[0];notesEdMenuSetIndex(p,notesEdMenuNext(p,-1,1))}
}
// ---------------------------------------------------------------- keyboard
// Shortcuts that other handlers already own (the app, the terminal, the browser's own clipboard keys).
const NOTES_ED_KEY_SKIP=["ins.cmd","ins.time","view.find","view.undo","view.redo","clip.cut","clip.copy","clip.paste","clip.pastePlain"]
function notesEdBodyKeydown(e){
if(e.defaultPrevented||e.isComposing)return
if((e.key==="ContextMenu"||(e.key==="F10"&&e.shiftKey))&&!e.ctrlKey&&!e.altKey){e.preventDefault();notesEdOpenContextMenu(e,true);return}
if(e.key==="F10"&&e.altKey){
e.preventDefault()
const bar=notesEdBar()
const root=notesEdBubbleVisible()?document.getElementById("notesEdBubble"):bar&&bar.el
if(!root)return
const first=Array.from(root.querySelectorAll("button:not(:disabled)")).find((b)=>b.offsetParent!==null)
if(first)first.focus()
return
}
if(!(e.ctrlKey||e.metaKey||e.altKey))return
const id=NotesEd.shortcutMatch(e,NOTES_ED_KEY_SKIP)
if(!id||!NOTES_ED_RUN[id])return
e.preventDefault()
e.stopPropagation()
notesEdRun(id,{source:"key",pick:true})
}
// Escape closes the innermost of our own surfaces first, and the arrow keys drive an open menu without taking the focus (and the selection) out of the text.
function notesEdDocKeydown(e){
if(notesEdState.menu){notesEdMenuKey(e);return}
if(e.key!=="Escape")return
if(document.getElementById("notesEdMore")){e.preventDefault();e.stopPropagation();notesEdMoreClose();notesEdFocus();return}
if(notesEdBubbleVisible()&&!document.getElementById("notesPopover")){e.preventDefault();e.stopPropagation();notesEdBubbleHide();if(document.activeElement&&document.activeElement.closest("#notesEdBubble")){notesEdBody().focus();notesRestoreRange()}}
}
// ---------------------------------------------------------------- pentest panels
function notesEdPop(id,width,title){
const pop=notesOpenPopover(notesEdAnchor(id),width)
pop.classList.add("notes-ed-pop")
pop.style.width=width+"px"
const t=document.createElement("div")
t.className="notes-popover-title"
t.textContent=title
pop.appendChild(t)
return pop
}
function notesEdEl(tag,cls,text){
const el=document.createElement(tag)
if(cls)el.className=cls
if(text!==undefined)el.textContent=text
return el
}
function notesEdActions(pop,list){
const row=notesEdEl("div","notes-popover-actions notes-ed-pop-actions")
const out={}
list.forEach((a)=>{
const b=notesEdEl("button",a.primary?"notes-popover-confirm":"",a.label)
b.type="button"
b.addEventListener("click",a.fn)
row.appendChild(b)
out[a.key||a.label]=b
})
pop.appendChild(row)
return out
}
function notesEdField(pop,label,el){
const f=notesEdEl("div","notes-popover-field")
if(label)f.appendChild(notesEdEl("label","",label))
f.appendChild(el)
pop.appendChild(f)
return el
}
function notesEdInput(placeholder,value){
const i=document.createElement("input")
i.type="text";i.autocomplete="off";i.spellcheck=false
if(placeholder)i.placeholder=placeholder
if(value)i.value=value
return i
}
function notesEdTextarea(rows,value,readonly){
const t=document.createElement("textarea")
t.rows=rows;t.spellcheck=false;t.autocomplete="off"
t.className="notes-ed-ta"
if(value)t.value=value
if(readonly)t.readOnly=true
return t
}
function notesEdOpenEncode(ctx,op){
const range=ctx.hasSel?ctx.range.cloneRange():null
const pop=notesEdPop("pt.encode",420,"Encode / decode")
const input=notesEdField(pop,range?"Input (the selection)":"Input",notesEdTextarea(3,ctx.text))
const pills=notesEdEl("div","notes-pro-pills")
let cur=op||NotesEd.transformGuess(ctx.text)
NotesEd.TRANSFORMS.forEach((t)=>{const b=notesEdEl("button","notes-pro-pill",t.label.replace(" (view)",""));b.type="button";b.dataset.op=t.id;b.addEventListener("click",()=>{cur=t.id;run()});pills.appendChild(b)})
pop.appendChild(pills)
const output=notesEdField(pop,"Result",notesEdTextarea(7,"",true))
const note=notesEdEl("p","notes-pro-hint")
pop.appendChild(note)
let res={ok:false}
const btn=notesEdActions(pop,[
{key:"copy",label:"Copy",fn:()=>{if(res.ok)notesEdCopy(res.text,"Result copied")}},
{key:"code",label:"Insert as code",fn:()=>{if(!res.ok)return;notesClosePopover();notesEdInsertCodeBelow(range||notesState.savedRange,res.text,cur==="jwt"?"json":"")}},
{key:"replace",label:"Replace selection",primary:true,fn:()=>{if(!res.ok||!range)return;notesClosePopover();notesEdReplaceRange(range,res.text)}}
])
function run(){
res=NotesEd.transform(cur,input.value)
pills.querySelectorAll("[data-op]").forEach((b)=>b.classList.toggle("active",b.dataset.op===cur))
output.value=res.ok?res.text:""
note.textContent=res.ok?(res.note||""):(input.value?res.error:"Type or paste the text to convert.")
note.classList.toggle("notes-ed-error",!res.ok&&!!input.value)
btn.copy.disabled=!res.ok;btn.code.disabled=!res.ok
btn.replace.disabled=!res.ok||!range||cur==="jwt"||input.value!==ctx.text
btn.replace.title=range?(input.value!==ctx.text?"The input was edited, so it no longer matches the selection":""):"Nothing was selected in the note"
}
input.addEventListener("input",run)
run()
if(!ctx.text)notesProFocusSoon(input)
}
function notesEdOpenHash(ctx){
const range=ctx.range.cloneRange()
const text=ctx.text
const pop=notesEdPop("pt.hash",440,"Hash of the selection")
const list=NotesEd.hashes(text)
const info=notesEdEl("p","notes-pro-hint",`${NotesEd.utf8Bytes(text).length} bytes, hashed exactly as selected (UTF-8; NTLM uses UTF-16LE).`+(/^\s|\s$/.test(text)?" The selection starts or ends with white space.":""))
pop.appendChild(info)
const box=notesEdEl("div","notes-ed-hash-list")
list.forEach((h)=>{
const row=notesEdEl("div","notes-ed-hash-row")
row.appendChild(notesEdEl("span","notes-ed-hash-name",h.label))
const v=notesEdEl("code","notes-ed-hash-value",h.value);v.title=h.value
row.appendChild(v)
const b=notesEdEl("button","notes-ioc-btn","Copy");b.type="button"
b.addEventListener("click",()=>notesEdCopy(h.value,h.label+" copied"))
row.appendChild(b)
box.appendChild(row)
})
pop.appendChild(box)
notesEdActions(pop,[
{label:"Copy all",fn:()=>notesEdCopy(list.map((h)=>h.label+": "+h.value).join("\n"),"Hashes copied")},
{label:"Insert below",primary:true,fn:()=>{notesClosePopover();notesEdInsertCodeBelow(range,list.map((h)=>(h.label+":").padEnd(9)+h.value).join("\n"),"text")}}
])
}
function notesEdMitreTag(t){
const info=NotesEd.mitreLookup(t.id)
const span=notesEdEl("span","note-mitre",t.id+" "+t.name)
span.dataset.tid=t.id
span.title="MITRE ATT&CK - "+info.tactic+" - "+info.full
return span
}
function notesEdOpenMitre(ctx){
const range=ctx.range?ctx.range.cloneRange():null
const pop=notesEdPop("pt.mitre",380,"MITRE ATT&CK technique")
const search=notesEdInput("Search: kerberoast, T1059, lateral, mimikatz...")
search.className="notes-popover-search"
pop.appendChild(search)
const list=notesEdEl("div","notes-popover-list notes-ed-mitre-list")
pop.appendChild(list)
pop.appendChild(notesEdEl("p","notes-pro-hint","Enter inserts the highlighted technique as a tag at the caret. The list is built in (offline): the common Enterprise techniques, not the whole matrix."))
const hints=NotesEd.mitreSuggest(ctx.hasSel?ctx.text:"",5)
let rows=[],index=0
const insert=(t)=>{
notesClosePopover()
notesEdBody().focus()
if(range){notesEdCollapseAfter(range);notesRestoreRange()}
notesProLeaveIsland()
// The caret at the end of a line that ends with a tag sits inside the tag: put the new tag after it, not nested in it.
const sel=window.getSelection(),an=sel.rangeCount?sel.anchorNode:null,pill=an?(an.nodeType===1?an:an.parentElement).closest(".note-mitre,.note-ts"):null
if(pill&&notesEdBody().contains(pill)){const r=document.createRange();r.setStartAfter(pill);r.collapse(true);sel.removeAllRanges();sel.addRange(r);notesState.savedRange=r.cloneRange()}
const tag=notesEdMitreTag(t)
notesInsertNodeAtCursor(tag)
// A no-break space: a plain trailing space collapses, WebKit then puts the caret back inside the tag and the next line (Enter) inherits it.
const sp=document.createTextNode("\u00a0")
tag.after(sp)
notesProSetCaret(sp,1)
notesMarkDirty()
}
const render=()=>{
const q=search.value.trim()
list.innerHTML=""
rows=[]
const add=(t,suggested)=>{
const b=notesEdEl("button","notes-ed-mitre-row")
b.type="button"
b.appendChild(notesEdEl("span","note-mitre",t.id))
const info=NotesEd.mitreLookup(t.id)
b.appendChild(notesEdEl("span","notes-ed-mitre-name",info.full))
b.appendChild(notesEdEl("span","notes-ed-mitre-tactic",suggested?"suggested":t.tactic))
b.addEventListener("click",()=>insert(t))
list.appendChild(b)
rows.push({t,el:b})
}
if(!q&&hints.length){list.appendChild(notesEdEl("div","notes-ed-more-label","Suggested from the selection"));hints.forEach((t)=>add(t,true));list.appendChild(notesEdEl("div","notes-ed-more-label","All techniques"))}
NotesEd.mitreSearch(q,q?40:200).forEach((t)=>add(t,false))
if(!rows.length)list.appendChild(notesEdEl("div","notes-empty-msg","No technique matches. Try a tool name, a tactic or a T-number."))
index=0
mark()
}
const mark=()=>rows.forEach((r,i)=>{r.el.classList.toggle("active",i===index);if(i===index)r.el.scrollIntoView({block:"nearest"})})
search.addEventListener("input",render)
search.addEventListener("keydown",(e)=>{
if(e.key==="ArrowDown"||e.key==="ArrowUp"){e.preventDefault();if(rows.length){index=(index+(e.key==="ArrowDown"?1:-1)+rows.length)%rows.length;mark()}}
else if(e.key==="Enter"){e.preventDefault();if(rows[index])insert(rows[index].t)}
})
render()
notesProFocusSoon(search)
}
function notesEdOpenCvss(ctx){
const callout=ctx.finding
const pop=notesEdPop("pt.cvss",400,"CVSS 3.1 base score")
const metrics=NotesEd.cvssParse(callout.dataset.vector||"")
const head=notesEdEl("div","notes-ed-cvss-head")
const score=notesEdEl("span","notes-ed-cvss-score","-")
const vec=notesEdEl("code","notes-ed-cvss-vector","")
head.appendChild(score);head.appendChild(vec)
pop.appendChild(head)
NotesEd.CVSS_METRICS.forEach((m)=>{
const row=notesEdEl("div","notes-ed-cvss-row")
row.appendChild(notesEdEl("span","notes-ed-cvss-name",m.label))
const pills=notesEdEl("div","notes-pro-pills")
m.values.forEach((v)=>{
const b=notesEdEl("button","notes-pro-pill",v[1])
b.type="button";b.dataset.m=m.id;b.dataset.v=v[0]
b.addEventListener("click",()=>{metrics[m.id]=v[0];sync()})
pills.appendChild(b)
})
row.appendChild(pills)
pop.appendChild(row)
})
const btn=notesEdActions(pop,[
{key:"copy",label:"Copy vector",fn:()=>notesEdCopy(NotesEd.cvssVector(metrics),"Vector copied")},
{key:"apply",label:"Apply to finding",primary:true,fn:()=>{
const s=NotesEd.cvssScore(metrics),v=NotesEd.cvssVector(metrics)
if(!s)return
callout.dataset.cvss=s
callout.dataset.vector=v
const sev=NotesPro.cvssSeverity(s)
if(sev)callout.dataset.sev=sev
// The finding template's own Severity and CVSS rows are filled in too, so the table, the badge and the report agree.
callout.querySelectorAll(":scope > table tr").forEach((tr)=>{
const th=tr.cells[0],td=tr.cells[1]
if(!th||!td)return
const k=th.textContent.trim().toLowerCase()
if(k==="cvss")td.textContent=s+" ("+v+")"
else if(k==="severity"&&sev)td.textContent=NotesPro.SEVERITIES.find((x)=>x.id===sev).label
})
notesMarkDirty()
notesClosePopover()
showToast("CVSS "+s+" applied to the finding")
}}
])
function sync(){
pop.querySelectorAll("[data-m]").forEach((b)=>b.classList.toggle("active",metrics[b.dataset.m]===b.dataset.v))
const s=NotesEd.cvssScore(metrics)
const sev=s?NotesPro.SEVERITIES.find((x)=>x.id===NotesPro.cvssSeverity(s)):null
score.textContent=s?s+" "+(sev?sev.label:""):"Pick every metric"
score.style.setProperty("--sev",sev?sev.color:"transparent")
score.classList.toggle("has-score",!!s)
vec.textContent=NotesEd.cvssVector(metrics)
btn.copy.disabled=!s;btn.apply.disabled=!s
}
sync()
}
function notesEdBuildTable(head,rows){
const t=document.createElement("table")
t.className="note-table note-table-head"
const hr=t.insertRow()
head.forEach((h)=>{const th=document.createElement("th");th.textContent=h;hr.appendChild(th)})
rows.forEach((r)=>{const tr=t.insertRow();r.forEach((c)=>{const td=tr.insertCell();if(c)td.textContent=String(c);else td.appendChild(document.createElement("br"))})})
return t
}
function notesEdOpenNmap(ctx){
const range=ctx.range?ctx.range.cloneRange():null
const fromSel=ctx.hasSel&&NotesEd.nmapHosts(ctx.text).length>0
const pop=notesEdPop("pt.nmap",460,"Nmap output to table")
const ta=notesEdField(pop,fromSel?"Nmap output (the selection)":"Paste nmap output (normal -oN or grepable -oG)",notesEdTextarea(8,fromSel?ctx.text:""))
ta.placeholder="Nmap scan report for 10.10.10.5\nPORT   STATE SERVICE VERSION\n22/tcp open  ssh     OpenSSH 8.2p1"
const info=notesEdEl("p","notes-pro-hint")
pop.appendChild(info)
let hosts=[]
const btn=notesEdActions(pop,[
{key:"cancel",label:"Cancel",fn:notesClosePopover},
{key:"replace",label:"Replace selection",fn:()=>go(true)},
{key:"insert",label:"Insert table",primary:true,fn:()=>go(false)}
])
function go(replace){
if(!hosts.length)return
const tbl=NotesEd.nmapTable(hosts)
notesClosePopover()
notesEdBody().focus()
if(range){if(replace&&fromSel)notesState.savedRange=range.cloneRange();else notesEdCollapseAfter(range)}
notesProInsertBlock(notesEdBuildTable(tbl.head,tbl.rows),null)
showToast(`Table inserted: ${tbl.rows.length} open port${tbl.rows.length===1?"":"s"}`)
}
function sync(){
hosts=NotesEd.nmapHosts(ta.value)
const ports=hosts.reduce((a,h)=>a+h.ports.length,0)
info.textContent=hosts.length?`${hosts.length} host${hosts.length===1?"":"s"}, ${ports} open port${ports===1?"":"s"}. Closed and filtered ports are left out.`:(ta.value.trim()?"No open ports found in this text.":"")
btn.insert.disabled=!hosts.length
btn.replace.disabled=!hosts.length||!fromSel||ta.value!==ctx.text
btn.replace.classList.toggle("hidden",!fromSel)
}
ta.addEventListener("input",sync)
sync()
if(!fromSel)notesProFocusSoon(ta)
}
function notesEdEvidenceBlock(source,text,lang){
const div=notesProBuildCallout("evidence")
const meta=notesEdEl("p","note-evidence-meta")
if(source){meta.appendChild(notesEdEl("b","","Source: "));meta.appendChild(document.createTextNode(source+" "))}
meta.appendChild(notesEdEl("span","note-ts","["+NotesPro.timestamp(new Date())+"]"))
div.appendChild(meta)
const pre=notesEdEl("pre","note-code")
if(lang)pre.dataset.lang=lang
pre.textContent=text
div.appendChild(pre)
return div
}
function notesEdOpenEvidence(ctx){
const range=ctx.range.cloneRange()
const text=ctx.text
const pop=notesEdPop("pt.evidence",340,"Wrap as evidence")
const iocs=NotesPro.iocExtract(text).filter((i)=>["ipv4","domain","url"].includes(i.type))
const src=notesEdField(pop,"Source (host, tool, URL or file)",notesEdInput("10.10.10.5 - nmap",iocs.length?iocs[0].value:""))
pop.appendChild(notesEdEl("p","notes-pro-hint","The selection becomes an Evidence block with this source and the current time."))
const go=()=>{
notesClosePopover()
notesEdBody().focus()
notesState.savedRange=range
const div=notesEdEvidenceBlock(src.value.trim().slice(0,200),text,"output")
notesProInsertBlock(div,null)
}
notesEdActions(pop,[{label:"Cancel",fn:notesClosePopover},{label:"Wrap",primary:true,fn:go}])
src.addEventListener("keydown",(e)=>{if(e.key==="Enter"){e.preventDefault();go()}})
notesProFocusSoon(src)
}
function notesEdOpenOutput(ctx){
const range=ctx.range?ctx.range.cloneRange():null
const pop=notesEdPop("pt.output",440,"Command output")
const first=ctx.hasSel?ctx.text.split("\n")[0]:""
const looksCmd=/^\s*(?:[$#>]|PS [A-Z]:\\[^>]*>)\s*\S/.test(first)
const cmd=notesEdField(pop,"Command",notesEdInput("nmap -sV -p- 10.10.10.5",looksCmd?first.replace(/^\s*(?:[$#>]|PS [A-Z]:\\[^>]*>)\s*/,""):""))
const exit=notesEdField(pop,"Exit code (optional)",notesEdInput("0",""))
exit.inputMode="numeric"
exit.classList.add("notes-ed-exit-input")
const out=notesEdField(pop,ctx.hasSel?"Output (the selection)":"Output",notesEdTextarea(7,ctx.hasSel?(looksCmd?ctx.text.split("\n").slice(1).join("\n"):ctx.text):""))
const err=notesEdEl("p","notes-pro-hint notes-ed-error","")
pop.appendChild(err)
const go=()=>{
const c=cmd.value.trim(),o=out.value.replace(/\r\n?/g,"\n").replace(/\n+$/,"")
if(!c&&!o){err.textContent="Type the command or paste its output.";return}
if(exit.value.trim()&&NotesEd.normExit(exit.value)===""){err.textContent="The exit code must be a number.";return}
const code=NotesEd.normExit(exit.value)
const div=notesProBuildCallout("evidence")
div.classList.add("note-cmdout")
const head=notesEdEl("p","note-evidence-meta")
if(c){head.appendChild(notesEdEl("code","","$ "+c));head.appendChild(document.createTextNode(" "))}
if(code!==""){const x=notesEdEl("span","note-exit","exit "+code);x.dataset.exit=code;head.appendChild(x);head.appendChild(document.createTextNode(" "))}
head.appendChild(notesEdEl("span","note-ts","["+NotesPro.timestamp(new Date())+"]"))
div.appendChild(head)
if(o){const pre=notesEdEl("pre","note-code");pre.dataset.lang="output";pre.textContent=o;div.appendChild(pre)}
notesClosePopover()
notesEdBody().focus()
if(range)notesState.savedRange=range
notesProInsertBlock(div,null)
}
notesEdActions(pop,[{label:"Cancel",fn:notesClosePopover},{label:ctx.hasSel?"Replace selection":"Insert",primary:true,fn:go}])
;[cmd,exit].forEach((i)=>i.addEventListener("keydown",(e)=>{if(e.key==="Enter"){e.preventDefault();go()}}))
notesProFocusSoon(cmd)
}
function notesEdOpenLink(ctx){
const range=ctx.range?ctx.range.cloneRange():null
const existing=ctx.link&&!/^notelink:/i.test(ctx.link.getAttribute("href")||"")?ctx.link:null
const pop=notesEdPop("ins.link",340,"Link")
const selUrl=ctx.hasSel&&/^(https?:\/\/|mailto:)\S+$/i.test(ctx.text.trim())?ctx.text.trim():""
const url=notesEdField(pop,"Web address",notesEdInput("https://example.com",existing?existing.getAttribute("href"):selUrl))
const err=notesEdEl("p","notes-pro-hint notes-ed-error","")
pop.appendChild(err)
const apply=()=>{
let v=url.value.trim()
if(v&&!/^[a-z][a-z0-9+.-]*:/i.test(v))v="https://"+v
const clean=NotesPro.sanUrl(v,"href")
if(!v||!clean||!/^(https?:|mailto:)/i.test(v)){err.textContent="Type an http, https or mailto address.";return}
notesClosePopover()
notesEdBody().focus()
if(existing){existing.setAttribute("href",clean);notesMarkDirty();return}
if(range&&!range.collapsed){notesEdSelect(range);document.execCommand("createLink",false,clean);notesMarkDirty();return}
if(range)notesState.savedRange=range
const a=document.createElement("a")
a.setAttribute("href",clean)
a.textContent=clean
notesInsertNodeAtCursor(a)
}
const acts=!notesHostHas("noteLinks")?[]:[{label:"Link to a note...",fn:()=>{const anchor=notesEdRectAnchor(pop);notesClosePopover();if(range)notesState.savedRange=range;notesOpenLinkPopover(anchor||notesEdAnchor("ins.link"))}}]
if(ctx.link)acts.push({label:"Remove link",fn:()=>{notesClosePopover();NOTES_ED_RUN["link.remove"](ctx)}})
acts.push({label:existing?"Update":"Apply",primary:true,fn:apply})
notesEdActions(pop,acts)
url.addEventListener("keydown",(e)=>{if(e.key==="Enter"){e.preventDefault();apply()}})
notesProFocusSoon(url)
}
// ---------------------------------------------------------------- copy as Markdown
function notesEdMarkdown(ctx){
const custom=(node)=>{
if(node.nodeType!==1)return null
if(node.matches(".cmd-card-embed")){
const d=notesState.cmdCards[node.dataset.cid]
if(!d)return ""
return (d.cmd_note_title?"**"+d.cmd_note_title+"**\n\n":"")+"```bash\n"+(d.command||"")+"\n```"
}
if(node.matches("figure.note-embed")){
const img=node.querySelector("img")
const cap=node.querySelector("figcaption")
const name=(img&&img.getAttribute("alt"))||(cap&&cap.textContent)||node.dataset.kind||"attachment"
return img?"![" + name + "]":"[" + name + "]"
}
return null
}
const root=ctx.hasSel?ctx.range.cloneContents():notesProCleanClone(notesEdBody().cloneNode(true))
return LoyaMarkdown.fromDom(root,{custom})
}
// ---------------------------------------------------------------- lifecycle
function notesEdOnPrefs(){
const want=JSON.stringify(notesEdPins())
if(notesEdState.pinsKey!==want){notesEdState.pinsKey=want;notesEdRenderToolbar()}
else notesEdRefresh()
if(notesEdPrefs().editor_bubble_off===true)notesEdBubbleHide()
}
function notesEdOnEditorShown(){
notesEdState.bars.forEach((b)=>{if(b.el.isConnected)notesEdFit(b)})
notesEdRefresh()
}
function notesEdOnEditorClosed(){
notesEdBubbleHide()
notesEdMenuClose()
notesEdMoreClose()
}
function notesEdOverlayOpen(){return !!(notesEdState.menu||document.getElementById("notesEdMore"))}
function notesEdInit(){
notesEdWireDoc()
notesEdState.pinsKey=JSON.stringify(notesEdPins())
const toolbar=document.getElementById("notesToolbar")
if(toolbar)notesEdMountToolbar(toolbar)
notesEdWireBody(document.getElementById("notesEditorBody"))
}
