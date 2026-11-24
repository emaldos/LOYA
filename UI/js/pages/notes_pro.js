// Pro note editor features (DOM side). Pure logic lives in notes_pro_core.js (NotesPro) and notes_draw.js (NotesDraw); notes.js calls notesProInit() once the editor markup exists.
// Everything transient (hover bars, table handles, resize grips, menus) lives outside the contenteditable body, so nothing here ends up in a saved note.
// figure.rpt-ev and .rpt-widget only exist in report fields (evidence snapshots, generated-block markers): they get the plain move / delete bar.
const NOTES_PRO_BLOCK_SEL="figure.note-embed,.cmd-card-embed,table,.note-callout,pre.note-code,figure.rpt-ev,.rpt-widget"
const NOTES_PRO_LANGS=["bash","powershell","cmd","python","sql","http","json","xml","javascript","php","c","go","output","text"]
let notesProState={hover:null,cell:null,hideTimer:null,drag:null,colCand:null,colDrag:null,imgDrag:null,slash:null,suggestTimer:null,suggestHidden:false,suggestCache:null,aiSuggest:null,countTimer:null,outlineTimer:null,tintTimer:null,chipTimer:null,chipFor:null}
// ---------------------------------------------------------------- sanitising
function notesProSanitizeNode(root,mode,images){
const walk=(node)=>{
Array.from(node.childNodes).forEach((c)=>{
if(c.nodeType===3)return
if(c.nodeType!==1){c.remove();return}
const tag=String(c.tagName||"").toUpperCase()
const act=NotesPro.sanTagAction(tag,mode)
if(act==="drop"){c.remove();return}
if(act==="unwrap"){walk(c);while(c.firstChild)node.insertBefore(c.firstChild,c);c.remove();return}
Array.from(c.attributes).forEach((a)=>{
const v=NotesPro.sanAttr(tag,a.name,a.value,mode)
if(v===null)c.removeAttribute(a.name)
else if(v!==a.value)c.setAttribute(a.name,v)
})
if(tag==="IMG"){
const src=(c.getAttribute("src")||"").trim()
if(!src){c.remove();return}
if(mode==="paste"&&images&&/^data:image\//i.test(src)){const ph=document.createElement("span");ph.dataset.pasteImg=String(images.length);images.push(src);c.replaceWith(ph);return}
if(mode==="paste"&&!/^(https?:|file:)/i.test(src)){c.remove();return}
if(mode==="render"&&/^https?:/i.test(src)&&notesProRemoteImagesBlocked())notesProBlockRemoteImg(c,src)
if(c.hasAttribute("data-loya-file-src")){const fs=c.getAttribute("data-loya-file-src");c.removeAttribute("data-loya-file-src");if(/^file:/i.test(fs))c.setAttribute("src",fs)}
}
walk(c)
})
}
walk(root)
return root
}
// ---------------------------------------------------------------- encrypted attachments
// With encryption at rest on, attachment files are AES-GCM streams: an <img> pointing at the file:// URL fails to decode. The failed
// load is caught (capture phase: error events do not bubble), the picture is fetched through the bridge as a data: URL, and the
// original file:// URL rides along in data-loya-file-src - saving (notesProCleanClone) and re-rendering always put it back, so a
// note never stores the decrypted picture. With encryption off the file loads normally and none of this runs.
const NOTES_PRO_ATT_RX=/[\/]Attachments[\/](?:_pending|\d+)[\/]([0-9a-f]{8,32})\.[a-z0-9]{1,8}$/i
function notesProAttachmentId(src){
try{return (NOTES_PRO_ATT_RX.exec(decodeURIComponent(String(src||"")))||[])[1]||""}catch(e){return ""}
}
function notesProAttachmentsForSave(root){
root.querySelectorAll("img[data-loya-file-src]").forEach((img)=>{img.setAttribute("src",img.getAttribute("data-loya-file-src"));img.removeAttribute("data-loya-file-src")})
}
document.addEventListener("error",(e)=>{
const img=e.target
if(!img||img.tagName!=="IMG"||img.hasAttribute("data-loya-file-src")||img.dataset.loyaAttTried)return
const src=img.getAttribute("src")||""
if(!/^file:/i.test(src))return
const id=notesProAttachmentId(src)
if(!id||typeof bridgeCall!=="function")return
img.dataset.loyaAttTried="1"
bridgeCall("notes.attachment_view",[id]).then((d)=>{
if(!d||!d.data_url||img.getAttribute("src")!==src)return
img.setAttribute("data-loya-file-src",src)
img.src=d.data_url
}).catch(()=>{}).finally(()=>{delete img.dataset.loyaAttTried})
},true)
// Parsed in an inert <template>, cleaned there, and the cleaned nodes are moved over: the markup is never re-parsed after cleaning.
function notesProFragment(html,mode,images){
const tpl=document.createElement("template")
tpl.innerHTML=html||""
notesProSanitizeNode(tpl.content,mode||"render",images)
return tpl.content
}
function notesProSetHtml(el,html){
const frag=notesProFragment(html,"render")
while(el.firstChild)el.removeChild(el.firstChild)
el.appendChild(frag)
}
function notesProSanitizedHtml(html,mode,images){
const d=document.createElement("div")
d.appendChild(notesProFragment(html,mode,images))
return d.innerHTML
}
// Remote images (privacy, default on): the <img> keeps its place but its URL moves to data-loya-remote-src, so nothing is fetched
// until the user clicks the placeholder. Saving puts the URL back (notesProCleanClone), so the note itself never changes.
function notesProRemoteImagesBlocked(){
const p=(typeof notesState!=="undefined"&&notesState.prefs)||{}
return p.block_remote_images!==false
}
function notesProBlockRemoteImg(img,src){
img.setAttribute("data-loya-remote-src",src)
img.removeAttribute("src")
img.classList.add("note-remote-blocked")
if(!img.getAttribute("title"))img.setAttribute("title","Remote image blocked - click to load "+src.slice(0,120))
}
function notesProLoadRemoteImg(img){
const src=img.getAttribute("data-loya-remote-src")||""
if(!/^https?:/i.test(src))return false
img.removeAttribute("data-loya-remote-src")
img.classList.remove("note-remote-blocked")
if(/^Remote image blocked/.test(img.getAttribute("title")||""))img.removeAttribute("title")
img.setAttribute("src",src)
return true
}
function notesProUnblockForSave(root){
root.querySelectorAll("img[data-loya-remote-src]").forEach((img)=>{
const src=img.getAttribute("data-loya-remote-src")||""
img.removeAttribute("data-loya-remote-src")
img.classList.remove("note-remote-blocked")
if(/^Remote image blocked/.test(img.getAttribute("title")||""))img.removeAttribute("title")
if(/^https?:/i.test(src))img.setAttribute("src",src);else img.remove()
})
}
// What the editor must not save: hover/collapse state and the old in-figure toolbars.
function notesProCleanClone(clone){
notesProUnblockForSave(clone)
notesProAttachmentsForSave(clone)
clone.querySelectorAll(".note-embed-toolbar,.note-embed-resize").forEach((el)=>el.remove())
clone.querySelectorAll(".note-sec-hidden").forEach((el)=>el.classList.remove("note-sec-hidden"))
clone.querySelectorAll(".note-secret.revealed").forEach((el)=>el.classList.remove("revealed"))
clone.querySelectorAll(".note-block-hover,.note-block-dragging").forEach((el)=>el.classList.remove("note-block-hover","note-block-dragging"))
clone.querySelectorAll("[class='']").forEach((el)=>el.removeAttribute("class"))
clone.querySelectorAll("[id]").forEach((el)=>el.removeAttribute("id"))
const w=document.createTreeWalker(clone,NodeFilter.SHOW_TEXT,null)
let n
while((n=w.nextNode()))if(n.textContent.indexOf("\u200b")>=0)n.textContent=n.textContent.replace(/\u200b/g,"")
return clone
}
// ---------------------------------------------------------------- caret helpers
function notesProSel(){
const sel=window.getSelection()
if(!sel||!sel.rangeCount)return null
const r=sel.getRangeAt(0)
return notesEditorBody().contains(r.startContainer)?r:null
}
function notesProEl(node){return node?(node.nodeType===1?node:node.parentElement):null}
function notesProSetCaret(node,offset){
const r=document.createRange()
r.setStart(node,offset||0)
r.collapse(true)
const sel=window.getSelection()
sel.removeAllRanges()
sel.addRange(r)
notesState.savedRange=r.cloneRange()
}
function notesProCaretInto(el,atEnd){
const r=document.createRange()
r.selectNodeContents(el)
r.collapse(!atEnd)
const sel=window.getSelection()
sel.removeAllRanges()
sel.addRange(r)
notesState.savedRange=r.cloneRange()
}
const NOTES_PRO_LINE_BLOCKS="P,DIV,LI,H1,H2,H3,H4,H5,H6,BLOCKQUOTE,TD,TH,PRE"
// The innermost block that holds the caret (null when the caret sits in bare text directly inside the editor).
function notesProCaretBlock(range){
const body=notesEditorBody()
let el=notesProEl(range.startContainer)
while(el&&el!==body){
if(el.matches(NOTES_PRO_LINE_BLOCKS))return el
el=el.parentElement
}
return null
}
// Range from the start of the caret's line to the caret.
function notesProLineRange(range){
const body=notesEditorBody()
const block=notesProCaretBlock(range)
const r=document.createRange()
if(block){r.selectNodeContents(block);r.setEnd(range.startContainer,range.startOffset);return {range:r,block}}
let n=range.startContainer
if(n===body){
let i=range.startOffset
while(i>0){const p=body.childNodes[i-1];if(p.nodeType===1&&(p.tagName==="BR"||getComputedStyle(p).display!=="inline"))break;i--}
r.setStart(body,i);r.setEnd(body,range.startOffset)
return {range:r,block:null}
}
while(n.parentNode&&n.parentNode!==body)n=n.parentNode
let first=n
while(first.previousSibling){const p=first.previousSibling;if(p.nodeType===1&&(p.tagName==="BR"||getComputedStyle(p).display!=="inline"))break;first=p}
r.setStartBefore(first);r.setEnd(range.startContainer,range.startOffset)
return {range:r,block:null}
}
function notesProInside(range,sel){
const el=notesProEl(range.startContainer)
return el?el.closest(sel):null
}
function notesProEmptyPara(){const p=document.createElement("p");p.appendChild(document.createElement("br"));return p}
function notesProInsertPlain(text){
const range=notesProSel()
if(!range)return
range.deleteContents()
const node=document.createTextNode(text)
range.insertNode(node)
notesProSetCaret(node,node.length)
node.parentNode.normalize()
notesMarkDirty()
}
// Insert a block element at the caret without nesting it inside a paragraph or heading; the caret ends up inside it (or after it when it is not editable).
function notesProInsertBlock(node,caretTarget){
const body=notesEditorBody()
body.focus()
notesRestoreRange()
const sel=window.getSelection()
let range=sel.rangeCount?sel.getRangeAt(0):null
if(!range||!body.contains(range.startContainer)){range=document.createRange();range.selectNodeContents(body);range.collapse(false)}
range.deleteContents()
let host=notesProEl(range.startContainer)
const container=host?host.closest(".note-callout,td,th,li")||body:body
const safeContainer=body.contains(container)?container:body
let child=range.startContainer
if(child===safeContainer){
const ref=safeContainer.childNodes[range.startOffset]||null
safeContainer.insertBefore(node,ref)
}else{
while(child.parentNode&&child.parentNode!==safeContainer)child=child.parentNode
if(child.parentNode!==safeContainer)safeContainer.appendChild(node)
else if(child.nodeType===1&&child.matches("p,div,h1,h2,h3,h4,h5,h6")&&!child.textContent.trim()&&!child.querySelector("img,figure,table,hr,.cmd-card-embed")&&!child.classList.contains("note-callout"))child.replaceWith(node)
else if(child.nodeType===1&&child.matches("p,div,h1,h2,h3,h4,h5,h6,ul,ol,table,pre,figure,blockquote"))child.after(node)
else{range.insertNode(node)}
}
if(!node.nextSibling||(node.nextSibling.nodeType===3&&!node.nextSibling.textContent.trim()&&!node.nextSibling.nextSibling))node.after(notesProEmptyPara())
const target=caretTarget||null
if(target&&node.contains(target))notesProCaretInto(target,true)
else if(node.nextSibling)notesProCaretInto(node.nextSibling.nodeType===1?node.nextSibling:node.parentNode,false)
notesMarkDirty()
notesProAfterStructureChange()
// Setting the caret from script does not scroll (and body.focus() can jump to the top): bring the new block into view.
if(body.contains(node))node.scrollIntoView({block:"nearest"})
return node
}
// There is always a line to click into after the last block.
function notesProEnsureTail(){
const body=notesEditorBody()
const last=body.lastElementChild
if(!last)return
if(last.matches("table,pre,figure,.note-callout,.cmd-card-embed,hr,blockquote,ul,ol")){let n=body.lastChild;while(n&&n!==last&&n.nodeType===3&&!n.textContent.trim())n=n.previousSibling;if(n===last)body.appendChild(notesProEmptyPara())}
else if(last.matches("div,p")&&!last.firstChild)last.appendChild(document.createElement("br"))
}
function notesProAfterStructureChange(){
if(notesHost&&notesHost.structure)notesHost.structure(notesEditorBody())
notesProEnsureTail()
notesProScheduleOutline()
notesProScheduleTint()
notesProScheduleCount()
notesProLayoutHover()
}
// ---------------------------------------------------------------- block styles, checklists, code, callouts
function notesProFormatBlock(tag){
tag=notesHostTag(tag)
const body=notesEditorBody()
body.focus()
notesRestoreRange()
const range=notesProSel()
const block=range?notesProCaretBlock(range):null
// A plain line is swapped for the new element by hand: execCommand("formatBlock") merges neighbouring lines in WebKit.
if(block&&block.matches("p,div,h1,h2,h3,h4,h5,h6,blockquote")&&!block.matches(".note-callout,.cmd-card,.cmd-card *")&&!block.querySelector("p,div,table,figure,pre,ul,ol,.cmd-card-embed")){
const keep={sc:range.startContainer,so:range.startOffset,ec:range.endContainer,eo:range.endOffset}
const el=document.createElement(block.tagName.toLowerCase()===tag?"p":tag)
while(block.firstChild)el.appendChild(block.firstChild)
if(!el.firstChild)el.appendChild(document.createElement("br"))
block.replaceWith(el)
const sel=window.getSelection()
const r=document.createRange()
try{
if(keep.sc===block)r.setStart(el,Math.min(keep.so,el.childNodes.length));else r.setStart(keep.sc,keep.so)
if(keep.ec===block)r.setEnd(el,Math.min(keep.eo,el.childNodes.length));else r.setEnd(keep.ec,keep.eo)
}catch(e){r.selectNodeContents(el);r.collapse(true)}
sel.removeAllRanges();sel.addRange(r)
notesState.savedRange=r.cloneRange()
}else document.execCommand("formatBlock",false,"<"+tag+">")
notesMarkDirty()
notesProAfterStructureChange()
}
function notesProOpenStyleMenu(anchor){
const r=anchor.getBoundingClientRect()
openContextMenu([
{label:"Paragraph",fn:()=>notesProFormatBlock("p")},
{label:"Heading 1",fn:()=>notesProFormatBlock("h1")},
{label:"Heading 2",fn:()=>notesProFormatBlock("h2")},
{label:"Heading 3",fn:()=>notesProFormatBlock("h3")},
{label:"Quote",fn:()=>notesProFormatBlock("blockquote")},
{sep:true},
{label:"Code block",fn:()=>notesProInsertCode("")},
{label:"Checklist",fn:()=>notesProInsertChecklist(false)},
{sep:true},
{label:"Show / hide outline",icon:"list",fn:()=>notesProToggleOutline()}
],r.left,r.bottom+4)
}
function notesProInsertChecklist(checked){
const body=notesEditorBody()
body.focus()
notesRestoreRange()
const before=notesProSel()
const inList=before?notesProInside(before,"ul,ol"):null
if(!inList||inList.tagName!=="UL"){document.execCommand("insertUnorderedList",false,null);notesFixListInP()}
const range=notesProSel()
const ul=range?notesProInside(range,"ul"):null
if(ul&&body.contains(ul)){
if(inList&&inList===ul&&ul.classList.contains("note-checklist")){ul.classList.remove("note-checklist");ul.querySelectorAll(":scope > li").forEach((li)=>li.removeAttribute("data-checked"))}
else{
ul.classList.add("note-checklist")
if(checked){const li=notesProInside(range,"li");if(li)li.dataset.checked="1"}
}
}
notesMarkDirty()
}
function notesProInsertCode(lang,text){
const range=notesProSel()
const selected=text!==undefined?text:(range&&!range.collapsed?range.toString():"")
const pre=document.createElement("pre")
pre.className="note-code"
const l=String(lang||"").toLowerCase().replace(/[^a-z0-9+#._-]/g,"").slice(0,20)
if(l)pre.dataset.lang=l
if(selected)pre.textContent=selected
else pre.appendChild(document.createElement("br"))
notesProInsertBlock(pre,pre)
return pre
}
function notesProBuildCallout(kind,sev,cvss){
const k=NotesPro.normCallout(kind)||"info"
const div=document.createElement("div")
div.className="note-callout"
div.dataset.callout=k
if(k==="finding"||k==="vuln"){
div.dataset.sev=NotesPro.normSeverity(sev)||"medium"
const c=NotesPro.normCvss(cvss)
if(c)div.dataset.cvss=c
}
return div
}
function notesProInsertCallout(kind){
if(kind==="credential"){notesProOpenCredentialForm(null,null);return}
const range=notesProSel()
const selected=range&&!range.collapsed?range.toString():""
const div=notesProBuildCallout(kind)
const p=document.createElement("p")
if(selected)p.textContent=selected
else p.appendChild(document.createElement("br"))
div.appendChild(p)
notesProInsertBlock(div,p)
}
function notesProInsertFinding(){
const frag=notesProFragment(NotesPro.findingTemplateHtml("medium"),"render")
const div=frag.firstElementChild
notesProInsertBlock(div,div.querySelector("h3"))
const h=div.querySelector("h3")
if(h){const r=document.createRange();r.selectNodeContents(h);const s=window.getSelection();s.removeAllRanges();s.addRange(r);notesState.savedRange=r.cloneRange()}
}
function notesProOpenCalloutMenu(anchor){
const r=anchor.getBoundingClientRect()
const items=NotesPro.CALLOUTS.map((c)=>({label:c.label,fn:()=>notesProInsertCallout(c.id)}))
items.push({sep:true})
items.push({label:"Finding template",icon:"file",fn:notesProInsertFinding})
openContextMenu(items,r.left,r.bottom+4)
}
// A popover is invisible until it has been placed; focus only works once it is shown.
function notesProFocusSoon(el){setTimeout(()=>{if(document.body.contains(el)){el.focus();if(el.select)el.select()}},60)}
// prefill: {host,user,secret} taken from a selected "user:password" (NotesEd.parseCredential); the selection is then replaced by the credential block.
function notesProOpenCredentialForm(prefill,anchorEl){
const anchor=anchorEl||notesHostEl("notesInsertCallout")||notesEdAnchor("callout.credential")
const pop=notesOpenPopover(anchor,300)
pop.innerHTML=`<div class="notes-popover-title">Credential</div>
<div class="notes-popover-field"><label>Host / service</label><input type="text" id="notesCredHost" autocomplete="off" placeholder="10.10.10.5 - SMB"></div>
<div class="notes-popover-field"><label>Username</label><input type="text" id="notesCredUser" autocomplete="off"></div>
<div class="notes-popover-field"><label>Password / hash / key</label><input type="text" id="notesCredSecret" autocomplete="off"></div>
<div class="notes-popover-field"><label>Notes</label><input type="text" id="notesCredNote" autocomplete="off" placeholder="Where it was found, what it opens"></div>
<div class="notes-popover-actions"><button type="button" id="notesCredCancel">Cancel</button><button type="button" class="notes-popover-confirm" id="notesCredOk">Insert</button></div>`
const val=(id)=>pop.querySelector(id).value.trim()
const insert=()=>{
const div=notesProBuildCallout("credential")
const row=(label,text,secret)=>{
if(!text)return
const p=document.createElement("p")
const b=document.createElement("b")
b.textContent=label+": "
p.appendChild(b)
if(secret){const s=document.createElement("span");s.className="note-secret";s.textContent=text;p.appendChild(s);p.appendChild(document.createTextNode(" "))}
else p.appendChild(document.createTextNode(text))
div.appendChild(p)
}
row("Host",val("#notesCredHost"))
row("User",val("#notesCredUser"))
row("Secret",val("#notesCredSecret"),true)
row("Notes",val("#notesCredNote"))
if(!div.firstChild)div.appendChild(notesProEmptyPara())
notesClosePopover()
notesProInsertBlock(div,div.lastElementChild)
}
pop.querySelector("#notesCredCancel").addEventListener("click",notesClosePopover)
pop.querySelector("#notesCredOk").addEventListener("click",insert)
pop.querySelectorAll("input").forEach((i)=>i.addEventListener("keydown",(e)=>{if(e.key==="Enter"){e.preventDefault();insert()}}))
if(prefill){pop.querySelector("#notesCredHost").value=prefill.host||"";pop.querySelector("#notesCredUser").value=prefill.user||"";pop.querySelector("#notesCredSecret").value=prefill.secret||""}
notesProFocusSoon(pop.querySelector("#notesCredHost"))
}
function notesProOpenCalloutSettings(callout,anchor){
const pop=notesOpenPopover(anchor||callout,280)
const kinds=NotesPro.CALLOUTS.map((c)=>`<button type="button" class="notes-pro-pill" data-kind="${c.id}">${c.label}</button>`).join("")
const sevs=NotesPro.SEVERITIES.map((s)=>`<button type="button" class="notes-pro-pill note-sev-pill" data-sev="${s.id}" style="--sev:${s.color}">${s.label}</button>`).join("")
pop.innerHTML=`<div class="notes-popover-title">Callout</div><div class="notes-pro-pills" id="notesCoKinds">${kinds}</div><div id="notesCoSevWrap"><div class="notes-popover-field"><label>Severity</label></div><div class="notes-pro-pills" id="notesCoSevs">${sevs}</div><div class="notes-popover-field"><label>CVSS score (0.0 - 10.0, optional)</label><input type="text" id="notesCoCvss" inputmode="decimal" autocomplete="off" placeholder="e.g. 7.5"></div></div><div class="notes-popover-actions"><button type="button" class="notes-popover-confirm" id="notesCoDone">Done</button></div>`
const cvss=pop.querySelector("#notesCoCvss")
const sync=()=>{
const k=callout.dataset.callout||"info"
pop.querySelectorAll("[data-kind]").forEach((b)=>b.classList.toggle("active",b.dataset.kind===k))
pop.querySelectorAll("[data-sev]").forEach((b)=>b.classList.toggle("active",b.dataset.sev===(callout.dataset.sev||"")))
pop.querySelector("#notesCoSevWrap").classList.toggle("hidden",!(k==="finding"||k==="vuln"))
}
cvss.value=callout.dataset.cvss||""
pop.querySelectorAll("[data-kind]").forEach((b)=>b.addEventListener("click",()=>{
callout.dataset.callout=b.dataset.kind
if(b.dataset.kind==="finding"||b.dataset.kind==="vuln"){if(!callout.dataset.sev)callout.dataset.sev="medium"}
else{delete callout.dataset.sev;delete callout.dataset.cvss}
notesMarkDirty();sync()
}))
pop.querySelectorAll("[data-sev]").forEach((b)=>b.addEventListener("click",()=>{callout.dataset.sev=b.dataset.sev;notesMarkDirty();sync()}))
cvss.addEventListener("input",()=>{
const c=NotesPro.normCvss(cvss.value)
if(c){callout.dataset.cvss=c;const s=NotesPro.cvssSeverity(c);if(s)callout.dataset.sev=s}
else delete callout.dataset.cvss
notesMarkDirty();sync()
})
cvss.addEventListener("keydown",(e)=>{if(e.key==="Enter"){e.preventDefault();notesClosePopover()}})
pop.querySelector("#notesCoDone").addEventListener("click",notesClosePopover)
sync()
}
function notesProOpenLangPopover(pre,anchor){
const pop=notesOpenPopover(anchor||pre,240)
pop.innerHTML=`<div class="notes-popover-title">Code language</div><div class="notes-popover-field"><input type="text" id="notesLangInput" autocomplete="off" placeholder="bash, python, output..."></div><div class="notes-pro-pills">${NOTES_PRO_LANGS.map((l)=>`<button type="button" class="notes-pro-pill" data-lang="${l}">${l}</button>`).join("")}</div><p class="notes-pro-hint">A language adds a light syntax tint. "output" and "text" stay plain.</p>`
const input=pop.querySelector("#notesLangInput")
input.value=pre.dataset.lang||""
const apply=(v)=>{
const l=String(v||"").toLowerCase().replace(/[^a-z0-9+#._-]/g,"").slice(0,20)
if(l)pre.dataset.lang=l;else delete pre.dataset.lang
notesMarkDirty();notesProScheduleTint();notesClosePopover()
}
pop.querySelectorAll("[data-lang]").forEach((b)=>b.addEventListener("click",()=>apply(b.dataset.lang)))
input.addEventListener("keydown",(e)=>{if(e.key==="Enter"){e.preventDefault();apply(input.value)}})
notesProFocusSoon(input)
}
function notesProCodeText(pre){
const clone=pre.cloneNode(true)
clone.querySelectorAll("br").forEach((br)=>br.replaceWith(document.createTextNode("\n")))
return (clone.textContent||"").replace(/\n$/,"")
}
function notesProCopy(text,msg){
if(!navigator.clipboard){showToast("Clipboard is not available","error");return}
navigator.clipboard.writeText(text||"").then(()=>showToast(msg||"Copied")).catch(()=>showToast("Copy failed","error"))
}
function notesProMaskSelection(){
notesEditorBody().focus()
notesRestoreRange()
const range=notesProSel()
if(!range)return
const inside=notesProInside(range,".note-secret")
if(inside){
const p=inside.parentNode
while(inside.firstChild)p.insertBefore(inside.firstChild,inside)
inside.remove();notesMarkDirty();return
}
if(range.collapsed){showToast("Select the secret text first","error");return}
const span=document.createElement("span")
span.className="note-secret"
span.textContent=range.toString()
range.deleteContents()
range.insertNode(span)
const after=document.createTextNode(" ")
span.after(after)
notesProSetCaret(after,1)
notesMarkDirty()
}
// Inline inserts must not land inside a command card or a figure: those are replaced as a whole on save.
function notesProLeaveIsland(){
const r=notesState.savedRange
const el=r?notesProEl(r.startContainer):null
const island=el?el.closest(".cmd-card-embed,figure.note-embed"):null
if(!island||!notesEditorBody().contains(island))return
let next=island.nextSibling
if(!next||next.nodeType!==1||!next.matches("p,div")){next=notesProEmptyPara();island.after(next)}
notesProCaretInto(next,false)
}
function notesProInsertTimestamp(){
notesProLeaveIsland()
const span=document.createElement("span")
span.className="note-ts"
span.textContent="["+NotesPro.timestamp(new Date())+"]"
notesInsertNodeAtCursor(span)
const sp=document.createTextNode(" ")
span.after(sp)
notesProSetCaret(sp,1)
}
// ---------------------------------------------------------------- collapsible sections, outline, counters, code tint
function notesProHeadingLevel(el){const m=/^H([1-6])$/.exec(el.tagName||"");return m?parseInt(m[1],10):0}
function notesProApplyCollapse(root){
if(!root)return
root.querySelectorAll(".note-sec-hidden").forEach((el)=>el.classList.remove("note-sec-hidden"))
root.querySelectorAll("h1[data-collapsed],h2[data-collapsed],h3[data-collapsed],h4[data-collapsed]").forEach((h)=>{
if(h.classList.contains("note-sec-hidden"))return
const lvl=notesProHeadingLevel(h)
let n=h.nextElementSibling
while(n){
const l=notesProHeadingLevel(n)
if(l&&l<=lvl)break
n.classList.add("note-sec-hidden")
n=n.nextElementSibling
}
})
}
function notesProToggleCollapse(h){
if(h.dataset.collapsed)delete h.dataset.collapsed
else h.dataset.collapsed="1"
const root=h.closest(".notes-editor-body,#notesViewerBody")
notesProApplyCollapse(root)
if(root&&root.classList.contains("notes-editor-body")){notesMarkDirty();notesProLayoutHover()}
}
// A click on the fold marker in front of a heading (drawn by CSS, so it is not part of the text).
function notesProHeadingFoldClick(e){
const t=notesProEl(e.target)
const h=t?t.closest("h1,h2,h3,h4"):null
if(!h||h.closest(".note-callout,.cmd-card,table"))return false
const rect=h.getBoundingClientRect()
if(e.clientX>rect.left+16||e.clientX<rect.left-4)return false
e.preventDefault()
notesProToggleCollapse(h)
return true
}
function notesProOutlineOpen(){
if(notesHost&&notesHost.prefGet){const v=notesHost.prefGet("editor_outline");if(v!==undefined)return !!v}
return !!(notesState.prefs&&notesState.prefs.editor_outline)
}
function notesProSetPref(key,value){
if(notesHost&&notesHost.prefSet&&notesHost.prefSet(key,value))return Promise.resolve()
if(!notesState.prefs)notesState.prefs={}
notesState.prefs[key]=value
return bridgeCall("notes.set_editor_pref",[key,value]).then((p)=>{notesState.prefs=p;return p}).catch(()=>{})
}
function notesProToggleOutline(){
notesProSetPref("editor_outline",!notesProOutlineOpen())
notesProRenderOutline()
}
function notesProRenderOutline(){
const panel=notesHostEl("notesOutline")
const btn=notesHostEl("notesOutlineBtn")
if(!panel)return
const open=notesProOutlineOpen()
panel.classList.toggle("hidden",!open)
if(btn)btn.classList.toggle("active",open)
if(!open)return
const heads=Array.from(notesEditorBody().querySelectorAll("h1,h2,h3,h4")).filter((h)=>!h.closest(".cmd-card,table")&&h.textContent.trim())
panel.innerHTML='<div class="notes-outline-title">Outline</div>'
if(!heads.length){const e=document.createElement("div");e.className="notes-outline-empty";e.textContent="Headings appear here. Type # and a space, or use the H button.";panel.appendChild(e);return}
heads.forEach((h)=>{
const b=document.createElement("button")
b.type="button"
const inFinding=h.closest(".note-callout")
b.className="notes-outline-item notes-outline-l"+notesProHeadingLevel(h)+(inFinding?" notes-outline-finding":"")
b.textContent=h.textContent.trim()
b.title=h.textContent.trim()
if(inFinding&&inFinding.dataset.sev&&notesProHeadingLevel(h)===3){const dot=document.createElement("span");dot.className="note-sev-dot note-sev-"+inFinding.dataset.sev;b.prepend(dot)}
b.addEventListener("click",()=>{
if(h.classList.contains("note-sec-hidden")){notesEditorBody().querySelectorAll("[data-collapsed]").forEach((x)=>delete x.dataset.collapsed);notesProApplyCollapse(notesEditorBody())}
h.scrollIntoView({block:"start",behavior:"smooth"})
})
panel.appendChild(b)
})
}
function notesProScheduleOutline(){
if(notesProState.outlineTimer)clearTimeout(notesProState.outlineTimer)
notesProState.outlineTimer=setTimeout(()=>{notesProState.outlineTimer=null;if(notesHostOpen())notesProRenderOutline()},350)
}
function notesProScheduleCount(){
if(notesProState.countTimer)clearTimeout(notesProState.countTimer)
notesProState.countTimer=setTimeout(()=>{
notesProState.countTimer=null
const el=notesHostEl("notesEditorCount")
if(!el||!notesHostOpen())return
const body=notesEditorBody()
const c=NotesPro.wordCount(body.innerText||body.textContent||"")
const findings=body.querySelectorAll('.note-callout[data-callout="finding"],.note-callout[data-callout="vuln"]').length
const todo=body.querySelectorAll("ul.note-checklist > li").length
const done=body.querySelectorAll('ul.note-checklist > li[data-checked="1"]').length
el.textContent=`${c.words} words · ${c.chars} chars`+(findings?` · ${findings} finding${findings===1?"":"s"}`:"")+(todo?` · ${done}/${todo} done`:"")
},300)
}
function notesProTintRoot(root,out){
if(!root)return
root.querySelectorAll("pre.note-code[data-lang]").forEach((pre)=>{
const nodes=[]
const w=document.createTreeWalker(pre,NodeFilter.SHOW_TEXT,null)
let n,text=""
while((n=w.nextNode())){nodes.push({n,start:text.length});text+=n.textContent}
if(!text||text.length>60000)return
const locate=(pos)=>{
for(let i=nodes.length-1;i>=0;i--)if(pos>=nodes[i].start)return {node:nodes[i].n,off:Math.min(pos-nodes[i].start,nodes[i].n.textContent.length)}
return null
}
NotesPro.codeTokens(text,pre.dataset.lang).forEach((tok)=>{
const a=locate(tok.s),b=locate(tok.e)
if(!a||!b)return
try{const r=document.createRange();r.setStart(a.node,a.off);r.setEnd(b.node,b.off);out[tok.t].push(r)}catch(e){}
})
})
}
function notesProTint(){
if(!notesHasHighlights())return
const out={comment:[],string:[],number:[],kw:[]}
notesProTintRoot(document.getElementById("notesViewerBody"),out)
notesHostBodies().forEach((b)=>notesProTintRoot(b,out))
Object.keys(out).forEach((k)=>{if(out[k].length)CSS.highlights.set("notes-code-"+k,new Highlight(...out[k]));else CSS.highlights.delete("notes-code-"+k)})
}
function notesProScheduleTint(){
if(notesProState.tintTimer)clearTimeout(notesProState.tintTimer)
notesProState.tintTimer=setTimeout(()=>{notesProState.tintTimer=null;notesProTint()},300)
}
// ---------------------------------------------------------------- viewer / shared decoration
function notesProDecorate(root){
notesProApplyCollapse(root)
notesProScheduleTint()
}
// One small floating chip, reused for a masked secret (Show / Copy) and for a code block (Copy).
function notesProChip(){
let chip=document.getElementById("notesProChip")
if(chip)return chip
chip=document.createElement("div")
chip.id="notesProChip"
chip.className="notes-pro-chip glass-panel hidden"
chip.addEventListener("mouseenter",()=>{if(notesProState.chipTimer){clearTimeout(notesProState.chipTimer);notesProState.chipTimer=null}})
chip.addEventListener("mouseleave",notesProChipHideSoon)
chip.addEventListener("mousedown",(e)=>e.preventDefault())
document.body.appendChild(chip)
return chip
}
function notesProChipHide(){
const chip=document.getElementById("notesProChip")
if(chip)chip.classList.add("hidden")
notesProState.chipFor=null
}
function notesProChipHideSoon(){
if(notesProState.chipTimer)clearTimeout(notesProState.chipTimer)
notesProState.chipTimer=setTimeout(()=>{notesProState.chipTimer=null;notesProChipHide()},350)
}
function notesProChipShow(target){
if(notesProState.chipTimer){clearTimeout(notesProState.chipTimer);notesProState.chipTimer=null}
if(notesProState.chipFor===target)return
notesProState.chipFor=target
const chip=notesProChip()
chip.innerHTML=""
const add=(label,fn)=>{const b=document.createElement("button");b.type="button";b.textContent=label;b.addEventListener("click",fn);chip.appendChild(b);return b}
const rect=target.getBoundingClientRect()
if(target.classList.contains("note-secret")){
const show=add(target.classList.contains("revealed")?"Hide":"Show",()=>{target.classList.toggle("revealed");show.textContent=target.classList.contains("revealed")?"Hide":"Show"})
add("Copy",()=>notesProCopy(target.textContent||"","Secret copied"))
chip.classList.remove("hidden")
chip.style.left=Math.round(Math.max(8,Math.min(rect.left,window.innerWidth-chip.offsetWidth-8)))+"px"
chip.style.top=Math.round(rect.top-chip.offsetHeight-4<8?rect.bottom+4:rect.top-chip.offsetHeight-4)+"px"
}else{
add("Copy",()=>notesProCopy(notesProCodeText(target),"Code copied"))
chip.classList.remove("hidden")
const host=target.closest(".notes-editor-body,#notesViewerBody")
const hr=host?host.getBoundingClientRect():rect
chip.style.left=Math.round(Math.min(rect.right,hr.right)-chip.offsetWidth-8)+"px"
chip.style.top=Math.round(Math.max(rect.top,hr.top)+6)+"px"
}
}
function notesProWireChips(root,codeToo){
root.addEventListener("mouseover",(e)=>{
const t=notesProEl(e.target)
if(!t)return
const secret=t.closest(".note-secret")
if(secret){notesProChipShow(secret);return}
if(codeToo){const pre=t.closest("pre.note-code");if(pre){notesProChipShow(pre);return}}
if(notesProState.chipFor)notesProChipHideSoon()
})
root.addEventListener("mouseleave",notesProChipHideSoon)
root.addEventListener("scroll",notesProChipHide,{passive:true})
}
// ---------------------------------------------------------------- positioning: alignment, wrap, move, drag, resize
const NOTES_PRO_LAYOUT_CLASSES=["note-embed-inline","note-embed-float-left","note-embed-float-right","note-align-left","note-align-center","note-align-right"]
function notesProBlockKind(el){
if(!el)return ""
if(el.matches("figure.note-embed"))return el.dataset.kind==="sketch"?"sketch":(el.dataset.kind==="image"?"image":"file")
if(el.matches(".cmd-card-embed"))return "cmd"
if(el.tagName==="TABLE")return "table"
if(el.matches(".note-callout"))return "callout"
if(el.matches("pre.note-code"))return "code"
return ""
}
function notesProLayoutOf(el){
if(el.classList.contains("note-embed-float-left"))return "float-left"
if(el.classList.contains("note-embed-float-right"))return "float-right"
if(el.classList.contains("note-align-center"))return "center"
if(el.classList.contains("note-align-right"))return "right"
return "left"
}
function notesProSetLayout(el,layout){
NOTES_PRO_LAYOUT_CLASSES.forEach((c)=>el.classList.remove(c))
const fig=el.matches("figure.note-embed")
if(layout==="float-left"&&fig)el.classList.add("note-embed-float-left")
else if(layout==="float-right"&&fig)el.classList.add("note-embed-float-right")
else if(layout==="center")el.classList.add("note-align-center")
else if(layout==="right")el.classList.add("note-align-right")
else if(fig)el.classList.add("note-embed-inline")
notesMarkDirty()
notesProRenderBar()
notesProLayoutHover()
}
function notesProMoveBlock(el,dir){
const body=notesEditorBody()
if(dir<0){
let prev=el.previousSibling
while(prev&&prev.nodeType===3&&!prev.textContent.trim())prev=prev.previousSibling
if(prev)el.parentNode.insertBefore(el,prev)
else if(el.parentNode!==body&&!el.parentNode.matches("td,th,li"))el.parentNode.before(el)
else return
}else{
let next=el.nextSibling
while(next&&next.nodeType===3&&!next.textContent.trim())next=next.nextSibling
if(next)next.after(el)
else if(el.parentNode!==body&&!el.parentNode.matches("td,th,li"))el.parentNode.after(el)
else return
}
notesMarkDirty()
el.scrollIntoView({block:"nearest"})
notesProAfterStructureChange()
}
function notesProDeleteBlock(el){
const kind=notesProBlockKind(el)
if(kind==="cmd"){notesDeleteCmdCard(el);return}
const label={image:"this image",sketch:"this drawing",file:"this attachment",table:"this table",callout:"this callout",code:"this code block"}[kind]||"this block"
const has=kind===""||kind==="image"||kind==="sketch"||kind==="file"||(el.textContent||"").trim().length>0
const go=()=>{el.remove();notesProSetHover(null,null);notesMarkDirty();notesProAfterStructureChange()}
if(!has){go();return}
appConfirm(`Delete ${label}?`,{okLabel:"Delete",danger:true}).then((yes)=>{if(yes)go()})
}
function notesProOverlay(){return notesProOverlayEl||document.getElementById("notesEdOverlay")}
function notesProRel(rect){
const w=notesHostWrap().getBoundingClientRect()
return {left:rect.left-w.left,top:rect.top-w.top,right:rect.right-w.left,bottom:rect.bottom-w.top,width:rect.width,height:rect.height,ww:w.width,wh:w.height}
}
function notesProBarButton(act,title,inner,active){return `<button type="button" class="notes-bar-btn${active?" active":""}" data-act="${act}" title="${title}">${inner}</button>`}
function notesProRenderBar(){
const bar=document.getElementById("notesBlockBar")
const el=notesProState.hover
if(!bar)return
if(!el||!notesEditorBody().contains(el)){bar.classList.add("hidden");return}
const kind=notesProBlockKind(el)
const lay=notesProLayoutOf(el)
const ico=(n)=>`<i class="icon icon-${n}"></i>`
let h=`<span class="notes-bar-grip" data-act="grip" title="Drag to move">${ico("grip")}</span>`+notesProBarButton("up","Move up",ico("arrow-up"))+notesProBarButton("down","Move down",ico("arrow-down"))
if(kind==="image"||kind==="sketch"||kind==="file"||kind==="table"){
h+='<span class="notes-bar-sep"></span>'+notesProBarButton("lay-left","Align left",ico("align-left"),lay==="left")+notesProBarButton("lay-center","Align centre",ico("align-center"),lay==="center")+notesProBarButton("lay-right","Align right",ico("align-right"),lay==="right")
}
if(kind==="image"||kind==="sketch"||kind==="file"){
h+=notesProBarButton("lay-float-left","Wrap text: picture on the left","<b>◧</b>",lay==="float-left")+notesProBarButton("lay-float-right","Wrap text: picture on the right","<b>◨</b>",lay==="float-right")
}
if(kind==="image"||kind==="sketch")h+='<span class="notes-bar-sep"></span>'+notesProBarButton("draw",kind==="sketch"?"Edit drawing":"Draw on / annotate (arrows, boxes, redact)","<b>✎</b> "+(kind==="sketch"?"Edit":"Annotate"))+notesProBarButton("size","Reset size","1:1")
if(kind==="table")h+='<span class="notes-bar-sep"></span>'+notesProBarButton("head","Header row on / off","<b>H</b>",!!el.querySelector("tr:first-child > th"))
if(kind==="callout")h+='<span class="notes-bar-sep"></span>'+notesProBarButton("callout","Type, severity, CVSS",ico("settings"))
if(kind==="code")h+='<span class="notes-bar-sep"></span>'+notesProBarButton("lang","Language",el.dataset.lang?NotesPro.escapeHtml(el.dataset.lang):"lang")+notesProBarButton("copy","Copy code",ico("copy"))
h+='<span class="notes-bar-sep"></span>'+notesProBarButton("del","Delete",ico("trash"))
bar.innerHTML=h
bar.classList.remove("hidden")
}
function notesProBarAction(e){
const btn=e.target.closest("[data-act]")
const el=notesProState.hover
if(!btn||!el)return
const act=btn.dataset.act
if(act==="grip")return
e.preventDefault()
if(act==="up")notesProMoveBlock(el,-1)
else if(act==="down")notesProMoveBlock(el,1)
else if(act.startsWith("lay-"))notesProSetLayout(el,notesProLayoutOf(el)===act.slice(4)?"left":act.slice(4))
else if(act==="draw")notesProAnnotate(el)
else if(act==="size"){const img=el.querySelector("img");if(img){img.style.width="";img.style.height="";notesMarkDirty();notesProLayoutHover()}}
else if(act==="head"){notesProToggleHeaderRow(el);notesProRenderBar()}
else if(act==="callout")notesProOpenCalloutSettings(el,btn)
else if(act==="lang")notesProOpenLangPopover(el,btn)
else if(act==="copy")notesProCopy(notesProCodeText(el),"Code copied")
else if(act==="del")notesProDeleteBlock(el)
}
function notesProSetHover(block,cell){
const st=notesProState
if(st.hideTimer){clearTimeout(st.hideTimer);st.hideTimer=null}
if(st.hover!==block){
if(st.hover)st.hover.classList.remove("note-block-hover")
st.hover=block
if(block)block.classList.add("note-block-hover")
notesProRenderBar()
}
st.cell=cell&&block&&block.tagName==="TABLE"?cell:null
notesProLayoutHover()
}
function notesProHideSoon(){
const st=notesProState
if(st.hideTimer)clearTimeout(st.hideTimer)
st.hideTimer=setTimeout(()=>{st.hideTimer=null;if(!st.drag&&!st.imgDrag&&!st.colDrag)notesProSetHover(null,null)},420)
}
function notesProPlace(el,left,top,w,h){
el.style.left=Math.round(left)+"px"
el.style.top=Math.round(top)+"px"
if(w!==undefined)el.style.width=Math.round(w)+"px"
if(h!==undefined)el.style.height=Math.round(h)+"px"
el.classList.remove("hidden")
}
function notesProLayoutHover(){
const st=notesProState
const bar=document.getElementById("notesBlockBar")
if(!bar)return
const ids=["notesTblAddRow","notesTblAddCol","notesTblRowHandle","notesTblColHandle","notesImgResize"]
const els=ids.map((id)=>document.getElementById(id))
const el=st.hover
if(!el||!notesEditorBody().contains(el)||!notesHostOpen()){bar.classList.add("hidden");els.forEach((x)=>x.classList.add("hidden"));return}
const r=notesProRel(el.getBoundingClientRect())
if(r.bottom<0||r.top>r.wh){bar.classList.add("hidden");els.forEach((x)=>x.classList.add("hidden"));return}
bar.classList.remove("hidden")
const bw=bar.offsetWidth,bh=bar.offsetHeight
const kind=notesProBlockKind(el)
// Above the block (and above a table's column handle); it sticks to the top edge while a tall block is scrolled.
const top=Math.max(2,Math.min(r.top-bh-(kind==="table"?19:3),r.bottom-bh-2))
notesProPlace(bar,Math.max(2,Math.min(Math.max(r.left,r.right-bw),r.ww-bw-14)),top)
els.forEach((x)=>x.classList.add("hidden"))
if(kind==="table"){
notesProPlace(els[0],r.left,r.bottom+2,r.width,14)
notesProPlace(els[1],r.right+2,r.top,14,r.height)
if(st.cell&&el.contains(st.cell)){
const row=st.cell.parentElement
const rr=notesProRel(row.getBoundingClientRect())
const cr=notesProRel(st.cell.getBoundingClientRect())
notesProPlace(els[2],Math.max(0,r.left-15),rr.top,13,rr.height)
notesProPlace(els[3],cr.left,Math.max(0,r.top-15),cr.width,13)
}
}else if(kind==="image"||kind==="sketch"){
const img=el.querySelector("img")
if(img){const ir=notesProRel(img.getBoundingClientRect());notesProPlace(els[4],Math.min(ir.right,ir.ww-12)-16,Math.max(ir.top,Math.min(ir.bottom,ir.wh))-16)}
}
}
function notesProNear(el,e,pad){
const r=el.getBoundingClientRect()
return e.clientX>=r.left-pad&&e.clientX<=r.right+pad&&e.clientY>=r.top-pad&&e.clientY<=r.bottom+pad
}
function notesProBodyMouseMove(e){
const st=notesProState
if(st.drag||st.imgDrag||st.colDrag)return
const body=notesEditorBody()
const t=notesProEl(e.target)
let block=t?t.closest(NOTES_PRO_BLOCK_SEL):null
if(block&&(!body.contains(block)||block===body))block=null
let cell=t?t.closest("td,th"):null
if(!block&&st.hover&&body.contains(st.hover)&&notesProNear(st.hover,e,st.hover.tagName==="TABLE"?22:10)){block=st.hover;cell=st.cell}
if(block&&block.tagName==="TABLE"&&cell&&cell.closest("table")!==block)cell=st.cell
if(block)notesProSetHover(block,cell)
else if(st.hover)notesProHideSoon()
// column resize: the pointer is on the border between two cells
let cand=null
const c=t?t.closest("td,th"):null
if(c&&body.contains(c)&&!c.closest(".cmd-card")){
const cr=c.getBoundingClientRect()
if(Math.abs(e.clientX-cr.right)<=4)cand=c
else if(e.clientX-cr.left<=3&&c.previousElementSibling)cand=c.previousElementSibling
}
if(cand!==st.colCand){st.colCand=cand;body.classList.toggle("note-col-resize",!!cand)}
}
function notesProColMouseDown(e){
const st=notesProState
if(!st.colCand||e.button!==0)return
e.preventDefault()
e.stopPropagation()
const cell=st.colCand
st.colDrag={table:cell.closest("table"),index:cell.cellIndex,startX:e.clientX,startW:cell.getBoundingClientRect().width,moved:false}
}
function notesProDocMouseMove(e){
const st=notesProState
if(st.colDrag){
const d=st.colDrag
const w=NotesPro.clampColWidth(d.startW+(e.clientX-d.startX))
d.moved=true
Array.from(d.table.rows).forEach((row)=>{const c=row.cells[d.index];if(c){c.style.width=w+"px";c.style.minWidth=w+"px"}})
notesProLayoutHover()
return
}
if(st.imgDrag){
const d=st.imgDrag
const max=Math.max(80,notesEditorBody().clientWidth-34)
const w=Math.max(40,Math.min(max,Math.round(d.startW+(e.clientX-d.startX))))
d.img.style.width=w+"px"
d.img.style.height="auto"
d.moved=true
notesProLayoutHover()
return
}
if(st.drag)notesProDragMove(e)
}
function notesProDocMouseUp(e){
const st=notesProState
if(st.colDrag){const moved=st.colDrag.moved;st.colDrag=null;if(moved)notesMarkDirty();return}
if(st.imgDrag){const moved=st.imgDrag.moved;st.imgDrag=null;if(moved)notesMarkDirty();notesProLayoutHover();return}
if(st.drag)notesProDragEnd(e)
}
// Drag a block by its grip: a line shows where it will land among its siblings.
function notesProDragStart(e){
const st=notesProState
const el=st.hover
if(!el||e.button!==0)return
e.preventDefault()
st.drag={el,parent:el.parentNode,ref:undefined}
el.classList.add("note-block-dragging")
document.body.classList.add("notes-dragging-block")
}
function notesProDragMove(e){
const st=notesProState
const d=st.drag
const body=notesEditorBody()
const br=body.getBoundingClientRect()
if(e.clientY<br.top+30)body.scrollTop-=14
else if(e.clientY>br.bottom-30)body.scrollTop+=14
const sibs=Array.from(d.parent.children).filter((c)=>c!==d.el&&!c.classList.contains("note-sec-hidden"))
let ref=null,lineY=null,rect=null
for(const s of sibs){
const r=s.getBoundingClientRect()
if(e.clientY<r.top+r.height/2){ref=s;lineY=r.top-2;rect=r;break}
lineY=r.bottom+2;rect=r
}
d.ref=ref
const line=document.getElementById("notesDropLine")
if(lineY===null){line.classList.add("hidden");return}
const pr=notesProRel({left:rect.left,top:lineY,right:rect.right,bottom:lineY,width:rect.width,height:0})
const parentRect=notesProRel((d.parent===body?body:d.parent).getBoundingClientRect())
notesProPlace(line,parentRect.left+8,pr.top,Math.max(40,parentRect.width-16),3)
}
function notesProDragEnd(){
const st=notesProState
const d=st.drag
st.drag=null
d.el.classList.remove("note-block-dragging")
document.body.classList.remove("notes-dragging-block")
document.getElementById("notesDropLine").classList.add("hidden")
if(d.ref===undefined)return
if(d.ref!==d.el.nextElementSibling||d.ref===null&&d.el!==d.parent.lastElementChild){
d.parent.insertBefore(d.el,d.ref)
notesMarkDirty()
notesProAfterStructureChange()
}
}
// ---------------------------------------------------------------- tables
function notesProNewCell(tag,like){
const c=document.createElement(tag==="TH"?"th":"td")
c.appendChild(document.createElement("br"))
if(like&&like.style.width){c.style.width=like.style.width;c.style.minWidth=like.style.minWidth}
return c
}
function notesProTableAddRow(table,beforeRow,afterRow){
const rows=Array.from(table.rows)
const model=afterRow||beforeRow||rows[rows.length-1]
if(!model)return null
const tr=document.createElement("tr")
Array.from(model.cells).forEach((c)=>tr.appendChild(notesProNewCell("TD",c)))
if(beforeRow){
// A row above the header row stays a header row; the old one keeps its cells.
if(beforeRow.cells[0]&&beforeRow.cells[0].tagName==="TH"&&beforeRow===rows[0]){tr.innerHTML="";Array.from(model.cells).forEach((c)=>tr.appendChild(notesProNewCell("TD",c)))}
beforeRow.parentNode.insertBefore(tr,beforeRow)
}else{
const ref=afterRow||rows[rows.length-1]
let host=ref.parentNode
if(host.tagName==="THEAD"){host=table.tBodies[0]||table.appendChild(document.createElement("tbody"));host.insertBefore(tr,host.firstChild)}
else host.insertBefore(tr,ref.nextSibling)
}
notesMarkDirty();notesProLayoutHover()
return tr
}
function notesProTableAddCol(table,index,after){
Array.from(table.rows).forEach((row)=>{
const ref=row.cells[Math.min(index,row.cells.length-1)]||null
const c=notesProNewCell(ref?ref.tagName:"TD",null)
if(!ref)row.appendChild(c)
else if(after)ref.after(c)
else ref.before(c)
})
notesMarkDirty();notesProLayoutHover()
}
function notesProTableDelRow(table,row){
if(table.rows.length<=1){table.remove();notesProSetHover(null,null)}
else row.remove()
notesMarkDirty();notesProLayoutHover()
}
function notesProTableDelCol(table,index){
const max=Math.max(...Array.from(table.rows).map((r)=>r.cells.length))
if(max<=1){table.remove();notesProSetHover(null,null)}
else Array.from(table.rows).forEach((r)=>{if(r.cells[index])r.cells[index].remove()})
notesMarkDirty();notesProLayoutHover()
}
function notesProToggleHeaderRow(table){
const row=table.rows[0]
if(!row)return
const toHead=row.cells[0]&&row.cells[0].tagName!=="TH"
Array.from(row.cells).forEach((c)=>{
const n=document.createElement(toHead?"th":"td")
Array.from(c.attributes).forEach((a)=>n.setAttribute(a.name,a.value))
while(c.firstChild)n.appendChild(c.firstChild)
c.replaceWith(n)
})
notesMarkDirty()
}
function notesProTableMoveRow(row,dir){
const sib=dir<0?row.previousElementSibling:row.nextElementSibling
if(!sib)return
if(dir<0)sib.before(row);else sib.after(row)
notesMarkDirty();notesProLayoutHover()
}
function notesProTableMoveCol(table,index,dir){
Array.from(table.rows).forEach((r)=>{
const c=r.cells[index],o=r.cells[index+dir]
if(!c||!o)return
if(dir<0)o.before(c);else o.after(c)
})
notesMarkDirty();notesProLayoutHover()
}
function notesProRowMenu(e){
const st=notesProState
const cell=st.cell,table=st.hover
if(!cell||!table)return
const row=cell.parentElement
const isFirst=row===table.rows[0]
const r=e.currentTarget.getBoundingClientRect()
openContextMenu([
{label:"Insert row above",icon:"arrow-up",fn:()=>notesProTableAddRow(table,row,null)},
{label:"Insert row below",icon:"arrow-down",fn:()=>notesProTableAddRow(table,null,row)},
{label:"Move row up",icon:"arrow-up",disabled:!row.previousElementSibling,fn:()=>notesProTableMoveRow(row,-1)},
{label:"Move row down",icon:"arrow-down",disabled:!row.nextElementSibling,fn:()=>notesProTableMoveRow(row,1)},
{label:isFirst&&cell.tagName==="TH"?"Header row off":"Header row on",icon:"table",disabled:!isFirst,fn:()=>notesProToggleHeaderRow(table)},
{sep:true},
{label:"Delete row",icon:"trash",danger:true,fn:()=>notesProTableDelRow(table,row)}
],r.right+4,r.top)
}
function notesProColMenu(e){
const st=notesProState
const cell=st.cell,table=st.hover
if(!cell||!table)return
const i=cell.cellIndex
const r=e.currentTarget.getBoundingClientRect()
openContextMenu([
{label:"Insert column left",icon:"arrow-left",fn:()=>notesProTableAddCol(table,i,false)},
{label:"Insert column right",icon:"arrow-right",fn:()=>notesProTableAddCol(table,i,true)},
{label:"Move column left",icon:"arrow-left",disabled:i===0,fn:()=>notesProTableMoveCol(table,i,-1)},
{label:"Move column right",icon:"arrow-right",disabled:i>=cell.parentElement.cells.length-1,fn:()=>notesProTableMoveCol(table,i,1)},
{label:"Fit column to content",icon:"shrink",fn:()=>{Array.from(table.rows).forEach((row)=>{const c=row.cells[i];if(c){c.style.width="";c.style.minWidth=""}});notesMarkDirty();notesProLayoutHover()}},
{sep:true},
{label:"Delete column",icon:"trash",danger:true,fn:()=>notesProTableDelCol(table,i)}
],r.left,r.bottom+4)
}
function notesProTableTab(e,cell){
const table=cell.closest("table")
const rows=Array.from(table.rows)
const r=rows.indexOf(cell.parentElement),c=cell.cellIndex
const next=NotesPro.tableNext(rows.map((x)=>x.cells.length),r,c,e.shiftKey)
if(!next)return
e.preventDefault()
let target
if(next.addRow){const tr=notesProTableAddRow(table,null,null);target=tr?tr.cells[0]:null}
else target=rows[next.r].cells[next.c]
if(target){notesProCaretInto(target,true);target.scrollIntoView({block:"nearest"})}
}
// ---------------------------------------------------------------- drawing / annotation glue
function notesProLoadImage(src){
return new Promise((resolve,reject)=>{
const img=new Image()
img.onload=()=>resolve(img)
img.onerror=()=>reject(new Error("The image could not be loaded."))
img.src=src
})
}
function notesProStoreFlat(fig,model,png,isSketch){
const img=fig.querySelector("img")
if(!img)return Promise.reject(new Error("The image is missing."))
if(!isSketch&&!model.shapes.length){
// No shapes left: the picture goes back to the untouched original.
if(fig.dataset.attachmentUrl)img.src=fig.dataset.attachmentUrl
img.removeAttribute("data-attachment-id")
fig.removeAttribute("data-shapes")
notesMarkDirty()
return Promise.resolve()
}
return notesHostStore((isSketch?"drawing-":"annotated-")+Date.now()+".png",png).then((att)=>{
img.src=att.url
if(isSketch){fig.dataset.attachmentId=att.id;fig.dataset.attachmentUrl=att.url}
else img.dataset.attachmentId=att.id
fig.dataset.shapes=NotesDraw.encode(model)
notesMarkDirty()
notesProLayoutHover()
})
}
function notesProAnnotate(fig){
const model=NotesDraw.decode(fig.dataset.shapes||"")
if(fig.dataset.kind==="sketch"){
notesDrawOpen({title:"Edit drawing",image:null,model:model||{w:900,h:500,bg:"#ffffff",shapes:[]},onSave:(m,png)=>notesProStoreFlat(fig,m,png,true)})
return
}
const id=fig.dataset.attachmentId||""
if(!id){showToast("Only pictures attached to this note can be annotated","error");return}
notesHostData(id).then((url)=>notesProLoadImage(url)).then((img)=>{
notesDrawOpen({title:"Annotate image",image:img,model:model||{shapes:[]},onSave:(m,png)=>notesProStoreFlat(fig,m,png,false)})
}).catch((err)=>showToast(err&&err.message?err.message:"Could not open the image","error"))
}
function notesProInsertSketch(){
notesEditorBody().focus()
notesRestoreRange()
const saved=notesState.savedRange?notesState.savedRange.cloneRange():null
notesDrawOpen({title:"New drawing",image:null,model:{w:900,h:500,bg:"#ffffff",shapes:[]},onSave:(m,png)=>{
if(!m.shapes.length)return Promise.resolve()
return notesHostStore("drawing-"+Date.now()+".png",png).then((att)=>{
const fig=notesBuildEmbedEl(att)
fig.classList.add("note-sketch")
fig.dataset.kind="sketch"
fig.dataset.shapes=NotesDraw.encode(m)
const img=fig.querySelector("img")
if(img)img.alt="Drawing"
if(saved)notesState.savedRange=saved
notesProInsertBlock(fig,null)
})
}})
}
// ---------------------------------------------------------------- slash menu and Markdown shortcuts
function notesProSlashClose(){
const el=document.getElementById("notesSlashMenu")
if(el)el.remove()
notesProState.slash=null
}
function notesProSlashAllowed(range){
return !notesProInside(range,"pre,td,th,.cmd-card,figure,a")
}
function notesProSlashCheck(){
const range=notesProSel()
if(!range||!range.collapsed||!notesProSlashAllowed(range)){notesProSlashClose();return}
const line=notesProLineRange(range)
const q=NotesPro.slashQuery(line.range.toString())
if(q===null){notesProSlashClose();return}
// The slash menu lists the registry's commands (notes_editor_core.js), so it offers what the toolbar and the right-click menu offer; a host may supply its own list.
const items=NotesPro.slashFilter(q,notesHost&&notesHost.slash?notesHost.slash():NotesEd.slashItems().filter((it)=>notesEdAllowed(it.id)))
if(!items.length){notesProSlashClose();return}
const prev=notesProState.slash
notesProState.slash={items,index:prev&&prev.query===q?Math.min(prev.index,items.length-1):0,query:q}
notesProSlashRender(range)
}
function notesProSlashRender(range){
const st=notesProState.slash
if(!st)return
let el=document.getElementById("notesSlashMenu")
if(!el){
el=document.createElement("div")
el.id="notesSlashMenu"
el.className="notes-slash-menu glass-panel"
el.addEventListener("mousedown",(e)=>e.preventDefault())
document.body.appendChild(el)
}
el.innerHTML=""
st.items.forEach((it,i)=>{
const b=document.createElement("button")
b.type="button"
b.className="notes-slash-item"+(i===st.index?" active":"")
const l=document.createElement("span");l.className="notes-slash-label";l.textContent=it.label
const h=document.createElement("span");h.className="notes-slash-hint";h.textContent=it.hint
b.appendChild(l);b.appendChild(h)
b.addEventListener("click",()=>notesProSlashApply(i))
el.appendChild(b)
})
const active=el.querySelector(".active")
if(active)active.scrollIntoView({block:"nearest"})
if(range){
let rect=range.getBoundingClientRect()
if(!rect||(!rect.width&&!rect.height&&!rect.top)){const host=notesProEl(range.startContainer);rect=host?host.getBoundingClientRect():notesEditorBody().getBoundingClientRect()}
const h=el.offsetHeight,w=el.offsetWidth
let top=rect.bottom+6
if(top+h>window.innerHeight-8)top=Math.max(8,rect.top-h-6)
el.style.top=Math.round(top)+"px"
el.style.left=Math.round(Math.max(8,Math.min(rect.left,window.innerWidth-w-8)))+"px"
}
}
function notesProDeleteLinePrefix(){
const range=notesProSel()
if(!range)return null
const line=notesProLineRange(range)
line.range.deleteContents()
const sel=window.getSelection()
const r=document.createRange()
r.setStart(line.range.startContainer,line.range.startOffset)
r.collapse(true)
sel.removeAllRanges();sel.addRange(r)
notesState.savedRange=r.cloneRange()
if(line.block&&!line.block.textContent&&!line.block.querySelector("br,img,figure,table")){
while(line.block.firstChild)line.block.removeChild(line.block.firstChild)
line.block.appendChild(document.createElement("br"))
notesProCaretInto(line.block,false)
}
return line
}
function notesProRunAction(id){
if(notesHost&&notesHost.runAction&&notesHost.runAction(id)){notesProAfterStructureChange();return}
if(NotesEd.get(id)){
const r=notesProSel()
const rect=r?r.getBoundingClientRect():null
notesEdRun(id,{source:"slash",pick:true,anchor:rect&&(rect.top||rect.height)?notesEdPointAnchor(rect.left,rect.bottom):null})
notesProAfterStructureChange()
return
}
if(id==="h1"||id==="h2"||id==="h3")notesProFormatBlock(id)
else if(id==="ul")notesExec("insertUnorderedList")
else if(id==="ol")notesExec("insertOrderedList")
else if(id==="check")notesProInsertChecklist(false)
else if(id==="table")notesInsertTable(3,3)
else if(id==="code")notesProInsertCode("")
else if(id==="quote")notesProFormatBlock("blockquote")
else if(id==="finding")notesProInsertFinding()
else if(id.startsWith("c-"))notesProInsertCallout(id.slice(2))
else if(id==="drawing")notesProInsertSketch()
else if(id==="image")notesHostEl("notesAttachmentFileInput").click()
else if(id==="cmd")notesOpenCmdPopover(notesHostEl("notesInsertCmd"))
else if(id==="divider")notesExec("insertHorizontalRule")
else if(id==="time")notesProInsertTimestamp()
else if(id==="toc")notesProToggleOutline()
notesProAfterStructureChange()
}
function notesProSlashApply(index){
const st=notesProState.slash
if(!st)return
const item=st.items[index]
notesProSlashClose()
if(!item)return
notesEditorBody().focus()
notesProDeleteLinePrefix()
notesProRunAction(item.id)
}
function notesProApplyShortcut(sc){
notesProDeleteLinePrefix()
if(sc.type==="h1"||sc.type==="h2"||sc.type==="h3")notesProFormatBlock(sc.type)
else if(sc.type==="ul")notesExec("insertUnorderedList")
else if(sc.type==="ol"){
notesExec("insertOrderedList")
const r=notesProSel();const ol=r?notesProInside(r,"ol"):null
if(ol&&sc.start>1)ol.setAttribute("start",String(sc.start))
}
else if(sc.type==="quote")notesProFormatBlock("blockquote")
else if(sc.type==="check")notesProInsertChecklist(sc.checked)
else if(sc.type==="code")notesProInsertCode(sc.lang)
notesProAfterStructureChange()
}
// An automatic conversion is its own undo step: the literal text (with the key that triggered it) is recorded first, so one Ctrl+Z brings it back.
function notesProLiteralStep(ch){
if(ch){
const range=notesProSel()
if(range){range.deleteContents();const n=document.createTextNode(ch);range.insertNode(n);notesProSetCaret(n,n.length)}
}
if(notesUndoState.debounceTimer){clearTimeout(notesUndoState.debounceTimer);notesUndoState.debounceTimer=null}
notesUndoPushSnapshot()
}
function notesProCommitStep(){
if(notesUndoState.debounceTimer){clearTimeout(notesUndoState.debounceTimer);notesUndoState.debounceTimer=null}
notesUndoPushSnapshot()
}
// `code`, **bold**, *italic*, ~~strike~~ and [text](url) turn into real formatting when the closing marker is typed.
function notesProInlineConvert(){
const range=notesProSel()
if(!range||!range.collapsed)return false
const node=range.startContainer
if(node.nodeType!==3||notesProInside(range,"pre,code,a,.cmd-card,.note-secret"))return false
const before=node.textContent.slice(0,range.startOffset)
const hit=LoyaMarkdown.inlineTrigger(before)
if(!hit)return false
notesProCommitStep()
// A line that is only ```code``` becomes a real code block (same as typing ``` + Enter).
if(hit.type==="code"&&hit.block){
const span=document.createRange()
span.setStart(node,hit.start)
span.setEnd(node,hit.start+hit.raw.length)
span.deleteContents()
const caret=document.createRange();caret.setStart(node,hit.start);caret.collapse(true)
const sel=window.getSelection();sel.removeAllRanges();sel.addRange(caret)
notesProInsertCode("",hit.text)
notesHostTouch()
notesProCommitStep()
return true
}
const tag={code:"code",bold:"b",italic:"i",strike:"s",link:"a"}[hit.type]
const el=document.createElement(tag)
el.textContent=hit.text
if(hit.type==="link")el.setAttribute("href",hit.url)
const r=document.createRange()
r.setStart(node,hit.start)
r.setEnd(node,hit.start+hit.raw.length)
r.deleteContents()
r.insertNode(el)
// The caret continues in plain text after the formatted span.
let after=el.nextSibling
if(!after||after.nodeType!==3){after=document.createTextNode("");el.after(after)}
if(!after.textContent.length)after.textContent="\u200b"
notesProSetCaret(after,after.textContent.startsWith("\u200b")?1:0)
notesHostTouch()
notesProCommitStep()
return true
}
function notesProLineText(node){return node?(node.textContent||"").replace(/\u200b/g,"").trim():""}
// "| a | b |" followed by "|---|---|" and Enter becomes a table.
function notesProTableFromLines(range){
const block=notesProCaretBlock(range)
if(!block||block.matches("td,th,li,pre"))return false
const align=LoyaMarkdown.tableSeparator(notesProLineText(block))
if(!align)return false
let prev=block.previousSibling
while(prev&&prev.nodeType===3&&!prev.textContent.trim())prev=prev.previousSibling
if(!prev||(prev.nodeType===1&&!prev.matches("p,div")))return false
const head=LoyaMarkdown.tableRow(notesProLineText(prev))
if(!head||head.length!==align.length)return false
notesProLiteralStep("")
const frag=notesProFragment(LoyaMarkdown.toHtml("| "+head.join(" | ")+" |\n|"+align.map(()=>"---").join("|")+"|\n|"+head.map(()=>" ").join("|")+"|"),"render")
const table=frag.querySelector("table")
if(!table)return false
table.querySelectorAll("td").forEach((td)=>{td.innerHTML="<br>"})
prev.remove()
block.replaceWith(table)
const nx=table.nextSibling
if(!nx)table.after(notesProEmptyPara())
else if(nx.nodeType===1&&nx.matches("div,p")&&!nx.firstChild)nx.appendChild(document.createElement("br"))
const first=table.rows[1]?table.rows[1].cells[0]:table.rows[0].cells[0]
notesProCaretInto(first,false)
notesHostTouch()
notesProCommitStep()
notesProAfterStructureChange()
return true
}
function notesProLeaveBlock(block){
// Put the caret in a fresh paragraph right after a callout, quote or code block.
const p=notesProEmptyPara()
block.after(p)
notesProCaretInto(p,false)
notesMarkDirty()
notesProAfterStructureChange()
}
// ---------------------------------------------------------------- auto-closing pairs ( [ { " ' ` (Settings: on by default)
function notesProAutoPairOn(){return !((notesState.prefs||{}).auto_pairs_off===true)}
function notesProAutoPair(e,range){
if(!notesProAutoPairOn()||e.ctrlKey||e.metaKey||e.altKey||e.isComposing)return false
if(notesProInside(range,".cmd-card,.note-secret,a"))return false
const node=range.startContainer
const isText=node.nodeType===3
const text=isText?node.textContent:""
const off=isText?range.startOffset:0
const prev=text.slice(off-1,off),next=range.collapsed?text.slice(off,off+1):""
if(e.key==="Backspace"&&range.collapsed&&isText&&NotesPro.autoPairBackspace(prev,next)){
e.preventDefault()
node.deleteData(off-1,2)
notesProSetCaret(node,off-1)
notesHostTouch()
return true
}
if(e.key.length!==1)return false
const lineBefore=isText?text.slice(0,off).split("\n").pop():""
const d=NotesPro.autoPairDecision(e.key,prev,next,!range.collapsed,lineBefore)
if(!d)return false
e.preventDefault()
notesProCommitStep()
if(d.act==="skip"){notesProSetCaret(node,off+1);if(e.key==="`")notesProInlineConvert()}
else if(d.act==="wrap"){
const inner=range.toString()
range.deleteContents()
const tn=document.createTextNode(d.open+inner+d.close)
range.insertNode(tn)
const r=document.createRange();r.setStart(tn,1);r.setEnd(tn,1+inner.length)
const sel=window.getSelection();sel.removeAllRanges();sel.addRange(r)
}
else if(isText){node.insertData(off,d.open+d.close);notesProSetCaret(node,off+1)}
else{const tn=document.createTextNode(d.open+d.close);range.insertNode(tn);notesProSetCaret(tn,1)}
notesHostTouch()
return true
}
function notesProKeydown(e){
if(e.isComposing)return
const st=notesProState
const mod=e.ctrlKey||e.metaKey
if(st.slash){
if(e.key==="ArrowDown"||e.key==="ArrowUp"){e.preventDefault();const n=st.slash.items.length;st.slash.index=(st.slash.index+(e.key==="ArrowDown"?1:-1)+n)%n;notesProSlashRender(null);return}
if(e.key==="Enter"||e.key==="Tab"){e.preventDefault();notesProSlashApply(st.slash.index);return}
if(e.key==="Escape"){e.preventDefault();e.stopPropagation();notesProSlashClose();return}
}
if(mod&&e.shiftKey&&!e.altKey&&(e.code==="Semicolon"||e.key===";"||e.key===":")){e.preventDefault();notesProInsertTimestamp();return}
const range=notesProSel()
if(!range)return
if(notesProAutoPair(e,range))return
const pre=notesProInside(range,"pre.note-code")
if(pre){
if(e.key==="Enter"&&(mod||e.shiftKey)){e.preventDefault();notesProLeaveBlock(pre);return}
if(e.key==="Escape"){e.preventDefault();e.stopPropagation();notesProLeaveBlock(pre);return}
if(e.key==="Enter"&&!e.altKey&&range.collapsed){
// A closing ``` on its own last line ends the block.
const code=notesProCodeText(pre)
const tail=document.createRange();tail.selectNodeContents(pre);tail.setStart(range.endContainer,range.endOffset)
if(/(^|\n)```$/.test(code)&&!tail.toString().trim()){
e.preventDefault()
notesProLiteralStep("")
const kept=code.replace(/\n?```$/,"")
pre.textContent=kept
if(!kept)pre.appendChild(document.createElement("br"))
notesProLeaveBlock(pre)
notesProCommitStep()
return
}
}
if(e.key==="Enter"&&!e.altKey){
e.preventDefault()
range.deleteContents()
const atEnd=(()=>{const r=document.createRange();r.selectNodeContents(pre);r.setStart(range.endContainer,range.endOffset);return r.toString().replace(/\n$/,"")===""&&!r.cloneContents().querySelector("br")})()
const node=document.createTextNode(atEnd&&!/\n$/.test(pre.textContent)?"\n\n":"\n")
range.insertNode(node)
notesProSetCaret(node,1)
pre.querySelectorAll("br").forEach((br)=>{if(br===pre.lastChild&&pre.textContent.length)br.remove()})
notesMarkDirty();notesProScheduleTint()
return
}
if(e.key==="Tab"&&!mod&&!e.altKey){e.preventDefault();if(!e.shiftKey)notesProInsertPlain("    ");notesProScheduleTint();return}
if(e.key==="ArrowDown"&&!pre.nextSibling){const r=document.createRange();r.selectNodeContents(pre);r.setStart(range.endContainer,range.endOffset);if(!r.toString().includes("\n")){pre.after(notesProEmptyPara())}}
return
}
if(e.key==="Tab"&&!mod&&!e.altKey){
const cell=notesProInside(range,"td,th")
if(cell&&!cell.closest(".cmd-card")){notesProTableTab(e,cell);return}
const li=notesProInside(range,"li")
if(li){e.preventDefault();document.execCommand(e.shiftKey?"outdent":"indent",false,null);notesMarkDirty();return}
return
}
if(e.key===" "&&!mod&&!e.altKey&&range.collapsed&&notesProSlashAllowed(range)&&!notesProInside(range,"li,h1,h2,h3,h4,blockquote")){
const line=notesProLineRange(range)
const sc=NotesPro.mdShortcut(line.range.toString(),"space")
if(sc){e.preventDefault();notesProLiteralStep(" ");notesProApplyShortcut(sc);notesProCommitStep();return}
}
if(e.key==="Enter"&&!e.shiftKey&&!mod&&!e.altKey&&range.collapsed){
if(notesProSlashAllowed(range)&&!notesProInside(range,"li")){
const line=notesProLineRange(range)
const text=line.range.toString()
const sc=NotesPro.mdShortcut(text,"enter")
if(sc){e.preventDefault();notesProLiteralStep("");notesProApplyShortcut(sc);notesProCommitStep();return}
if(/^(?:\*{3,}|_{3,})$/.test(text.trim())){e.preventDefault();notesProLiteralStep("");notesProDeleteLinePrefix();notesExec("insertHorizontalRule");notesProCommitStep();return}
if(notesProTableFromLines(range)){e.preventDefault();return}
}
const lineBlock=notesProCaretBlock(range)
if(lineBlock&&lineBlock.tagName==="BLOCKQUOTE"&&!lineBlock.textContent.trim()&&!lineBlock.querySelector("img,figure,table,hr")){
// An empty quote line ends the quote.
e.preventDefault()
const d=document.createElement("div")
d.appendChild(document.createElement("br"))
lineBlock.replaceWith(d)
notesProCaretInto(d,false)
notesMarkDirty()
return
}
// Enter on an empty last line leaves a callout or a quote.
const box=notesProInside(range,".note-callout,blockquote")
if(box&&notesEditorBody().contains(box)){
const block=notesProCaretBlock(range)
if(block&&block!==box&&block.parentNode===box&&block===box.lastElementChild&&!block.textContent.trim()&&!block.querySelector("img,figure,table")&&box.children.length>1&&block.tagName!=="LI"){
e.preventDefault()
block.remove()
notesProLeaveBlock(box)
return
}
}
}
if(e.key==="Backspace"&&range.collapsed&&!mod){
const box=notesProInside(range,".note-callout")
if(box&&!box.textContent.trim()&&!box.querySelector("img,figure,table,hr")){
e.preventDefault()
const p=notesProEmptyPara()
box.replaceWith(p)
notesProCaretInto(p,false)
notesMarkDirty();notesProAfterStructureChange()
return
}
const li=notesProInside(range,"ul.note-checklist > li")
if(li&&li.dataset.checked&&!li.textContent.trim())li.removeAttribute("data-checked")
}
}
function notesProInput(e){
const range=notesProSel()
if(e&&e.inputType==="insertParagraph"&&range){
// A new checklist line starts unchecked, and a new line after a heading is not "collapsed".
const li=notesProInside(range,"ul.note-checklist > li")
if(li&&li.dataset.checked&&!li.textContent.trim())li.removeAttribute("data-checked")
const block=notesProCaretBlock(range)
if(block&&block.dataset&&block.dataset.collapsed&&!block.textContent.trim())block.removeAttribute("data-collapsed")
}
if(e&&e.inputType==="insertText"&&e.data&&"`*_~)".includes(e.data))notesProInlineConvert()
notesProSlashCheck()
notesProScheduleOutline()
notesProScheduleTint()
notesProScheduleCount()
notesProScheduleSuggest()
notesProLayoutHover()
}
function notesProBodyClick(e){
const t=notesProEl(e.target)
if(!t)return
const li=t.closest("ul.note-checklist > li")
if(li&&t===li){
const r=li.getBoundingClientRect()
if(e.clientX<r.left+2){
e.preventDefault()
if(li.dataset.checked)li.removeAttribute("data-checked");else li.dataset.checked="1"
notesMarkDirty();notesProScheduleCount()
return
}
}
if(notesProHeadingFoldClick(e))return
const callout=t.closest(".note-callout")
if(callout&&t===callout){
// The badge strip at the top of a callout is drawn by CSS; a click on it opens the callout's settings.
const r=callout.getBoundingClientRect()
if(e.clientY<r.top+26)notesProOpenCalloutSettings(callout,callout)
}
}
// ---------------------------------------------------------------- IOC tools
function notesProIocSource(){
const range=notesState.savedRange
const body=notesEditorBody()
if(range&&!range.collapsed&&body.contains(range.commonAncestorContainer))return {text:range.toString(),range,scope:"selection"}
return {text:body.innerText||body.textContent||"",range:null,scope:"note"}
}
function notesProAddTarget(ioc,btn){
btn.disabled=true
bridgeCall("targets.keys").then((keys)=>{
const names=(keys||[]).map((k)=>k.key)
const want=ioc.type==="url"?[/^url/i,/url/i]:ioc.type==="domain"?[/^(domain|host|hostname|fqdn)$/i,/domain|host/i]:[/^(ip|rhost|rhosts|target|host)$/i,/ip|host|target/i]
let key=null
for(const rx of want){key=names.find((n)=>rx.test(n));if(key)break}
const values={}
if(key)values[key]=ioc.value
return bridgeCall("targets.upsert_target",[null,ioc.value,"not_used",values,null])
}).then(()=>{btn.textContent="Added";showToast("Added to Targets: "+ioc.value);document.dispatchEvent(new CustomEvent("loya:target-keys-changed",{detail:{kind:"add"}}))}).catch((err)=>{btn.disabled=false;showToast(err&&err.message?err.message:"Could not add the target","error")})
}
function notesProReplaceInRange(range,fn){
const body=notesEditorBody()
const nodes=[]
const w=document.createTreeWalker(body,NodeFilter.SHOW_TEXT,null)
let n
while((n=w.nextNode())){if(range.intersectsNode(n)&&!n.parentElement.closest(".cmd-card,.note-secret"))nodes.push(n)}
let changed=0
nodes.forEach((node)=>{
let s=0,e=node.textContent.length
if(node===range.startContainer)s=range.startOffset
if(node===range.endContainer)e=range.endOffset
const part=node.textContent.slice(s,e)
const next=fn(part)
if(next!==part){node.textContent=node.textContent.slice(0,s)+next+node.textContent.slice(e);changed++}
})
if(changed){notesState.savedRange=null;notesMarkDirty()}
return changed
}
function notesProOpenIoc(anchor){
const src=notesProIocSource()
const iocs=NotesPro.iocExtract(src.text)
const pop=notesOpenPopover(anchor,360)
pop.classList.add("notes-ioc-popover")
const title=document.createElement("div")
title.className="notes-popover-title"
title.textContent=`Indicators in the ${src.scope} (${iocs.length})`
pop.appendChild(title)
const list=document.createElement("div")
list.className="notes-popover-list notes-ioc-list"
if(!iocs.length){const e=document.createElement("div");e.className="notes-empty-msg";e.textContent="No IPs, domains, URLs, hashes, e-mail addresses or CVE ids found. Select some text first to limit the search.";list.appendChild(e)}
iocs.forEach((ioc)=>{
const row=document.createElement("div")
row.className="notes-ioc-row"
const type=document.createElement("span");type.className="notes-ioc-type notes-ioc-"+ioc.type;type.textContent=ioc.type
const val=document.createElement("span");val.className="notes-ioc-value";val.textContent=ioc.value;val.title=ioc.value
row.appendChild(type);row.appendChild(val)
const copy=document.createElement("button");copy.type="button";copy.className="notes-ioc-btn";copy.textContent="Copy"
copy.addEventListener("click",()=>notesProCopy(ioc.value,"Copied"))
row.appendChild(copy)
if(["ipv4","cidr","domain","url"].includes(ioc.type)){
const add=document.createElement("button");add.type="button";add.className="notes-ioc-btn";add.textContent="+ Target";add.title="Add to Targets"
add.addEventListener("click",()=>notesProAddTarget(ioc,add))
row.appendChild(add)
}
list.appendChild(row)
})
pop.appendChild(list)
const actions=document.createElement("div")
actions.className="notes-popover-actions notes-ioc-actions"
const btn=(label,fn,disabled)=>{const b=document.createElement("button");b.type="button";b.textContent=label;b.disabled=!!disabled;b.addEventListener("click",fn);actions.appendChild(b);return b}
btn("Copy all",()=>notesProCopy(iocs.map((i)=>i.value).join("\n"),"Indicators copied"),!iocs.length)
btn("Copy defanged",()=>notesProCopy(iocs.map((i)=>NotesPro.iocDefangValue(i.type,i.value)).join("\n"),"Defanged indicators copied"),!iocs.length)
btn("Defang selection",()=>{const n=notesProReplaceInRange(src.range,NotesPro.iocDefangText);notesClosePopover();showToast(n?"Selection defanged":"Nothing to defang")},!src.range)
btn("Refang selection",()=>{const n=notesProReplaceInRange(src.range,NotesPro.iocRefang);notesClosePopover();showToast(n?"Selection refanged":"Nothing to refang")},!src.range)
pop.appendChild(actions)
}
// ---------------------------------------------------------------- title / tag suggestions (opt-in, never applied without a click)
function notesProSuggestEnabled(){
const p=notesState.prefs||{}
return {title:p.suggest_title===true,tags:p.suggest_tags===true}
}
function notesProSuggestData(){
if(notesProState.suggestCache)return Promise.resolve(notesProState.suggestCache)
return Promise.all([bridgeCall("notes.tags").catch(()=>[]),bridgeCall("targets.targets").catch(()=>[]),bridgeCall("ai.enabled_providers").catch(()=>[])]).then(([tags,targets,providers])=>{
notesProState.suggestCache={tags:(tags||[]).map((t)=>t.tag).filter(Boolean),targets:(targets||[]).map((t)=>({name:t.name,values:t.values||{}})),ai:Array.isArray(providers)&&providers.length>0}
return notesProState.suggestCache
})
}
function notesProScheduleSuggest(){
if(!notesHostHas("suggest"))return
const on=notesProSuggestEnabled()
if(!on.title&&!on.tags){notesProRenderSuggest(null);return}
if(notesProState.suggestTimer)clearTimeout(notesProState.suggestTimer)
notesProState.suggestTimer=setTimeout(()=>{notesProState.suggestTimer=null;notesProComputeSuggest()},700)
}
function notesProComputeSuggest(){
const on=notesProSuggestEnabled()
if(!notesEditorOpen()||(!on.title&&!on.tags)){notesProRenderSuggest(null);return}
const body=notesEditorBody()
const text=(body.innerText||body.textContent||"").slice(0,20000)
notesProSuggestData().then((data)=>{
if(!notesEditorOpen())return
const current=notesEditorTagsArray()
const headings=Array.from(body.querySelectorAll("h1,h2,h3")).map((h)=>h.textContent.trim()).filter(Boolean)
const out={titles:[],tags:[],ai:data.ai}
if(text.trim()){
if(on.title)out.titles=NotesPro.suggestTitles(text,{headings,targets:data.targets,existingTags:data.tags})
if(on.tags)out.tags=NotesPro.suggestTags(text,{existingTags:data.tags,targets:data.targets,currentTags:current,max:8})
}
notesProRenderSuggest(out)
})
}
function notesProRenderSuggest(data){
const row=document.getElementById("notesSuggestRow")
if(!row)return
const on=notesProSuggestEnabled()
if(!data||notesProState.suggestHidden||(!on.title&&!on.tags)){row.classList.add("hidden");row.innerHTML="";return}
const name=document.getElementById("notesEditorName").value.trim().toLowerCase()
const ai=notesProState.aiSuggest||{titles:[],tags:[]}
const have=new Set(notesEditorTagsArray().map((t)=>t.toLowerCase()))
const titles=[...(on.title?ai.titles:[]).map((t)=>({t,ai:true})),...data.titles.map((t)=>({t,ai:false}))].filter((x,i,a)=>x.t.toLowerCase()!==name&&a.findIndex((y)=>y.t.toLowerCase()===x.t.toLowerCase())===i).slice(0,3)
const tags=[...(on.tags?ai.tags:[]).map((t)=>({t,ai:true})),...data.tags.map((t)=>({t,ai:false}))].filter((x,i,a)=>!have.has(x.t.toLowerCase())&&a.findIndex((y)=>y.t.toLowerCase()===x.t.toLowerCase())===i).slice(0,10)
row.innerHTML=""
const label=(text)=>{const s=document.createElement("span");s.className="notes-suggest-label";s.textContent=text;row.appendChild(s)}
if(titles.length){
label("Title")
titles.forEach((x)=>{
const b=document.createElement("button");b.type="button";b.className="notes-suggest-chip notes-suggest-title"+(x.ai?" notes-suggest-ai":"");b.textContent=x.t;b.title="Use this title"
b.addEventListener("click",()=>{document.getElementById("notesEditorName").value=x.t;notesState.nameTouched=true;notesMarkDirty();notesProRenderSuggest(data)})
row.appendChild(b)
})
}
if(tags.length){
label("Tags")
tags.forEach((x)=>{
const b=document.createElement("button");b.type="button";b.className="notes-suggest-chip"+(x.ai?" notes-suggest-ai":"");b.textContent="+ "+x.t;b.title="Add this tag"
b.addEventListener("click",()=>{const cur=notesEditorTagsArray();cur.push(x.t);notesSetEditorTags(cur);notesMarkDirty();notesProRenderSuggest(data)})
row.appendChild(b)
})
}
if(!titles.length&&!tags.length){row.classList.add("hidden");return}
if(data.ai){
const b=document.createElement("button");b.type="button";b.className="notes-suggest-chip notes-suggest-ask";b.textContent="Ask AI";b.title="Ask the configured AI provider for a title and tags (sends the note text to it)"
b.addEventListener("click",()=>notesProAskAi(b,data))
row.appendChild(b)
}
const x=document.createElement("button");x.type="button";x.className="notes-suggest-close";x.title="Hide suggestions for this note";x.textContent="×"
x.addEventListener("click",()=>{notesProState.suggestHidden=true;notesProRenderSuggest(null)})
row.appendChild(x)
row.classList.remove("hidden")
}
function notesProParseAiSuggest(reply){
const out={titles:[],tags:[]}
String(reply||"").split(/\r?\n/).forEach((line)=>{
const t=/^\s*\**\s*title\s*\**\s*[:\-]\s*(.+)$/i.exec(line)
if(t){const v=t[1].replace(/^["'*\s]+|["'*\s]+$/g,"").slice(0,80);if(v)out.titles.push(v)}
const g=/^\s*\**\s*tags\s*\**\s*[:\-]\s*(.+)$/i.exec(line)
if(g)g[1].split(/[,;]/).map((x)=>x.trim().toLowerCase().replace(/^[#"'*\s]+|["'*\s.]+$/g,"")).filter((x)=>x&&x.length<=30&&/^[a-z0-9][a-z0-9 ._-]*$/.test(x)).slice(0,8).forEach((x)=>out.tags.push(x))
})
return out
}
function notesProAskAi(btn,data){
const body=notesEditorBody()
const plain=(body.innerText||body.textContent||"").replace(/\s+\n/g,"\n").trim().slice(0,4000)
if(!plain){showToast("Write some note content first","error");return}
btn.disabled=true
btn.textContent="Asking..."
const prompt=`Suggest a short title (max 8 words) and 2-5 short lowercase tags for this penetration testing note. Reply with exactly two lines and nothing else:\nTITLE: <title>\nTAGS: <tag>, <tag>, <tag>\n\n---\n${plain}\n---`
aiOpenPanel().then(()=>aiSendExternalPrompt(prompt)).then((reply)=>{
notesProState.aiSuggest=notesProParseAiSuggest(reply)
if(!notesProState.aiSuggest.titles.length&&!notesProState.aiSuggest.tags.length)showToast("The AI reply had no usable title or tags","error")
notesProRenderSuggest(data)
}).catch((err)=>{btn.disabled=false;btn.textContent="Ask AI";showToast(err&&err.message?err.message:"AI suggestion failed","error")})
}
// ---------------------------------------------------------------- editor size
function notesProApplyMax(){
const max=!!(notesState.prefs&&notesState.prefs.editor_maximized)
const ed=document.getElementById("notesEditor")
const btn=document.getElementById("notesMaxBtn")
if(ed)ed.classList.toggle("notes-editor-max",max)
if(btn){btn.classList.toggle("active",max);btn.title=max?"Restore editor size":"Maximize editor";const i=btn.querySelector(".icon");if(i)i.className="icon icon-"+(max?"restore":"maximize")}
notesProLayoutHover()
}
function notesProToggleMax(){
const next=!(notesState.prefs&&notesState.prefs.editor_maximized)
notesProSetPref("editor_maximized",next)
notesProApplyMax()
}
// ---------------------------------------------------------------- lifecycle hooks called from notes.js
function notesProOnPrefs(){
notesProApplyMax()
notesEdOnPrefs()
if(notesEditorOpen()){notesProRenderOutline();notesProScheduleSuggest()}
}
function notesProOnEditorReset(){
const body=notesEditorBody()
body.querySelectorAll(".note-embed-toolbar,.note-embed-resize").forEach((el)=>el.remove())
notesProState.suggestHidden=false
notesProState.suggestCache=null
notesProState.aiSuggest=null
notesProSlashClose()
notesProSetHover(null,null)
notesProApplyCollapse(body)
notesProEnsureTail()
notesProApplyMax()
notesProRenderOutline()
notesProScheduleTint()
notesProScheduleCount()
notesProRenderSuggest(null)
notesProScheduleSuggest()
requestAnimationFrame(notesEdOnEditorShown)
}
function notesProOnEditorClosed(){
notesEdOnEditorClosed()
notesProSlashClose()
notesProChipHide()
notesProSetHover(null,null)
if(typeof notesDrawIsOpen==="function"&&notesDrawIsOpen())notesDrawClose(true)
notesProScheduleTint()
}
function notesProOverlayOpen(){
return !!(notesProState.slash||(typeof notesDrawIsOpen==="function"&&notesDrawIsOpen())||notesEdOverlayOpen())
}
// The floating layer (block bar, table handles, resize grip, drop line) exists once; notesHostActivate moves it into the active host's wrap.
let notesProOverlayEl=null
function notesProInitOverlay(){
if(notesProOverlayEl&&notesProOverlayEl.firstChild){document.querySelectorAll("#notesEdOverlay").forEach((o)=>{if(o!==notesProOverlayEl)o.remove()});return}
let overlay=document.getElementById("notesEdOverlay")
if(!overlay){
overlay=document.createElement("div")
overlay.id="notesEdOverlay"
overlay.className="notes-ed-overlay"
const wrap=notesHostWrap()||(notesHosts[0]&&notesHosts[0].wrap)
if(wrap)wrap.appendChild(overlay)
}
notesProOverlayEl=overlay
const byId=(id)=>overlay.querySelector("#"+id)
overlay.innerHTML='<div id="notesBlockBar" class="notes-block-bar hidden"></div><button type="button" id="notesTblAddRow" class="notes-tbl-add hidden" title="Add a row">+</button><button type="button" id="notesTblAddCol" class="notes-tbl-add notes-tbl-add-col hidden" title="Add a column">+</button><button type="button" id="notesTblRowHandle" class="notes-tbl-handle hidden" title="Row options"></button><button type="button" id="notesTblColHandle" class="notes-tbl-handle notes-tbl-handle-col hidden" title="Column options"></button><span id="notesImgResize" class="notes-img-resize hidden" title="Drag to resize"></span><div id="notesDropLine" class="notes-drop-line hidden"></div>'
const bar=byId("notesBlockBar")
overlay.querySelectorAll("#notesBlockBar,.notes-tbl-add,.notes-tbl-handle,.notes-img-resize").forEach((el)=>{
el.addEventListener("mouseenter",()=>{if(notesProState.hideTimer){clearTimeout(notesProState.hideTimer);notesProState.hideTimer=null}})
el.addEventListener("mouseleave",notesProHideSoon)
el.addEventListener("mousedown",(e)=>{if(!e.target.closest(".notes-bar-grip,.notes-img-resize"))e.preventDefault()})
})
bar.addEventListener("click",notesProBarAction)
bar.addEventListener("mousedown",(e)=>{if(e.target.closest(".notes-bar-grip"))notesProDragStart(e)})
byId("notesTblAddRow").addEventListener("click",()=>{const t=notesProState.hover;if(t&&t.tagName==="TABLE")notesProTableAddRow(t,null,null)})
byId("notesTblAddCol").addEventListener("click",()=>{const t=notesProState.hover;if(t&&t.tagName==="TABLE"){const n=Math.max(...Array.from(t.rows).map((r)=>r.cells.length));notesProTableAddCol(t,n-1,true)}})
byId("notesTblRowHandle").addEventListener("click",notesProRowMenu)
byId("notesTblColHandle").addEventListener("click",notesProColMenu)
byId("notesImgResize").addEventListener("mousedown",(e)=>{
const fig=notesProState.hover
const img=fig?fig.querySelector("img"):null
if(!img||e.button!==0)return
e.preventDefault()
notesProState.imgDrag={img,startX:e.clientX,startW:img.getBoundingClientRect().width,moved:false}
})
document.addEventListener("mousemove",notesProDocMouseMove)
document.addEventListener("mouseup",notesProDocMouseUp)
window.addEventListener("resize",notesProLayoutHover)
}
// The listeners every host body needs.
function notesProWireBody(body){
body.addEventListener("mousemove",notesProBodyMouseMove)
body.addEventListener("mouseleave",()=>{if(notesProState.colCand&&!notesProState.colDrag){notesProState.colCand=null;body.classList.remove("note-col-resize")}notesProHideSoon()})
body.addEventListener("mousedown",notesProColMouseDown,true)
body.addEventListener("scroll",()=>{notesProLayoutHover();notesProSlashClose()},{passive:true})
body.addEventListener("keydown",notesProKeydown)
body.addEventListener("input",notesProInput)
body.addEventListener("click",notesProBodyClick)
body.addEventListener("blur",()=>setTimeout(()=>{if(document.activeElement!==body)notesProSlashClose()},150))
notesProWireChips(body,true)
notesEdWireBody(body)
}
function notesProInit(){
const body=notesEditorBody()
notesProInitOverlay()
if(!body||!notesProOverlay())return
notesProWireBody(body)
const viewer=document.getElementById("notesViewerBody")
notesProWireChips(viewer,true)
viewer.addEventListener("click",(e)=>{notesProHeadingFoldClick(e)})
const on=(id,fn)=>{const el=document.getElementById(id);if(el)el.addEventListener("click",fn)}
// The toolbar itself is drawn and wired by notes_editor.js from the command registry.
on("notesOutlineBtn",notesProToggleOutline)
on("notesMaxBtn",notesProToggleMax)
document.getElementById("notesEditorName").addEventListener("input",()=>{if(notesProState.suggestTimer===null)notesProScheduleSuggest()})
notesProApplyMax()
}
// ---------------------------------------------------------------- Markdown paste
// Plain text that is clearly Markdown is pasted as formatted blocks. The plain-text version is recorded as the previous undo step, so one Ctrl+Z keeps it as text.
function notesProPasteMarkdown(text){
const body=notesEditorBody()
const sel=window.getSelection()
if(sel.rangeCount&&!sel.isCollapsed)document.execCommand("delete",false,null)
notesProCommitStep()
const before={html:body.innerHTML,offset:notesUndoCaretOffset()}
// A text offset cannot address an empty line (the caret would come back at the end of the block before it, e.g. inside a code block or a command card): an empty line is remembered by its element path.
const at=notesProSel()
const line=at?notesProCaretBlock(at):null
let linePath=null
if(line&&!line.textContent.replace(/\u200b/g,"")){linePath=[];for(let n=line;n&&n!==body;n=n.parentNode)linePath.unshift(Array.prototype.indexOf.call(n.parentNode.children,n))}
document.execCommand("insertText",false,text)
notesProCommitStep()
notesUndoState.applying=true
body.innerHTML=before.html
body.focus()
notesUndoRestoreCaret(before.offset)
if(linePath){let n=body;linePath.forEach((i)=>{n=n?n.children[i]:null});if(n&&n!==body)notesProCaretInto(n,false)}
notesUndoState.applying=false
const range=notesProSel()
const frag=notesProFragment(LoyaMarkdown.toHtml(text),"render")
const blocks=Array.from(frag.childNodes)
if(!range||!blocks.length)return false
let anchor=notesProCaretBlock(range)
if(anchor&&anchor.matches("td,th,li"))anchor=null
const empty=anchor&&anchor.matches("p,div")&&!anchor.textContent.trim()&&!anchor.querySelector("img,figure,table,hr,.cmd-card-embed")
if(anchor&&anchor.parentNode&&anchor.matches("p,div,h1,h2,h3,h4,h5,h6,blockquote")){
let ref=anchor
blocks.forEach((b)=>{ref.after(b);ref=b})
if(empty)anchor.remove()
}else{
range.deleteContents()
const holder=document.createDocumentFragment()
blocks.forEach((b)=>holder.appendChild(b))
range.insertNode(holder)
}
const last=blocks[blocks.length-1]
if(!last.nextSibling)last.after(notesProEmptyPara())
if(last.matches&&last.matches("p,h1,h2,h3,h4,h5,h6,blockquote,li"))notesProCaretInto(last,true)
else notesProCaretInto(last.nextSibling&&last.nextSibling.nodeType===1?last.nextSibling:last.parentNode,false)
notesHostTouch()
notesProCommitStep()
notesProAfterStructureChange()
showToast("Pasted as Markdown - Ctrl+Z to keep plain text")
return true
}
