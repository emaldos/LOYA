// Regression tests for SECURITY-AUDIT.md (phase 1), JS side. Run: node tests/js/security_audit.js
const fs=require("fs")
const path=require("path")
const ROOT=path.resolve(__dirname,"..","..")
const notesSrc=fs.readFileSync(path.join(ROOT,"UI","js","pages","notes.js"),"utf8")
const NotesPro=require(path.join(ROOT,"UI","js","pages","notes_pro_core.js"))
const LoyaMarkdown=require(path.join(ROOT,"UI","js","components","markdown.js"))
let passed=0,failed=0
function check(name,cond,detail){if(cond){passed++;return}failed++;console.log("  FAIL  "+name+(detail?"  ->  "+detail:""))}
function grab(src,name){
const start=src.indexOf("function "+name+"(")
if(start<0)throw new Error("missing "+name)
const next=src.indexOf("\nfunction ",start+1)
return src.slice(start,next<0?undefined:next)
}
// SA-01: note text extraction must parse in an inert document, never in a live-page element (img onerror would run there).
const liveDoc={createElement(){throw new Error("live-document element used for untrusted HTML")}}
let parsed=null
class FakeDOMParser{parseFromString(html,type){parsed={html,type};return {body:{textContent:html.replace(/<[^>]*>/g,"")}}}}
const fns=new Function("document","DOMParser",["notesInertText","notesPlainTextFromHtml","notesStripHtmlPreview"].map((n)=>grab(notesSrc,n)).join("\n")+"\nreturn {notesPlainTextFromHtml,notesStripHtmlPreview}")(liveDoc,FakeDOMParser)
const xss='<img src=x onerror="alert(1)"><p>Hello   world</p>'
let threw=null
try{check("SA-01 plain text from note HTML",fns.notesPlainTextFromHtml(xss)==="Hello world")}catch(e){threw=e}
check("SA-01 notesPlainTextFromHtml never builds live elements",!threw,threw&&threw.message)
check("SA-01 parsed as text/html in DOMParser",parsed&&parsed.type==="text/html")
threw=null
try{check("SA-01 draft preview text",fns.notesStripHtmlPreview(xss)==="Hello   world")}catch(e){threw=e}
check("SA-01 notesStripHtmlPreview never builds live elements",!threw,threw&&threw.message)
check("SA-01 no detached-div innerHTML left in notes.js",!/createElement\("div"\)\s*\n\s*\w+\.innerHTML=html/.test(notesSrc))
// SA-03: rendered/pasted note images may only load this machine's files; UNC forms would leak the NTLM hash on Windows.
const L=NotesPro.sanLocalFileUrl
check("SA-03 windows attachment allowed",L("file:///C:/Users/u/LOYA/Data/Attachments/1/a.png",true))
check("SA-03 linux attachment allowed",L("file:////home/u/LOYA/Data/Attachments/1/a.png",false))
;["file://10.0.0.5/s/a.png","file:////10.0.0.5/s/a.png","file:///\\\\10.0.0.5\\s\\a.png","file:///%5C%5C10.0.0.5/s/a.png","file:///C://host/x","FILE://host/x"].forEach((u)=>check("SA-03 windows refuses "+u,!L(u,true)))
;["file://10.0.0.5/s/a.png","file:///%5chost/x","file:///\\\\h\\s"].forEach((u)=>check("SA-03 linux refuses "+u,!L(u,false)))
check("SA-03 sanAttr drops a UNC img src",NotesPro.sanAttr("IMG","src","file://attacker/share/x.png","render")===null)
check("SA-03 sanAttr keeps an https img src",NotesPro.sanAttr("IMG","src","https://example.com/a.png","render")==="https://example.com/a.png")
// Sanitiser and Markdown policies the audit verified (kept as regression guards).
check("policy: on* attributes dropped",NotesPro.sanAttr("IMG","onerror","alert(1)","render")===null)
check("policy: javascript: href dropped",NotesPro.sanAttr("A","href","java\tscript:alert(1)","render")===null)
check("policy: data:text/html href dropped",NotesPro.sanAttr("A","href","data:text/html,<script>","render")===null)
check("policy: srcdoc dropped",NotesPro.sanAttr("DIV","srcdoc","<script>","render")===null)
check("policy: css url() dropped",NotesPro.sanStyle("background:url(https://x/y)")==="")
check("policy: css escapes dropped",NotesPro.sanStyle("background:\\75rl(x)")==="")
check("policy: position:fixed dropped",NotesPro.sanStyle("position:fixed;color:red")==="color:red")
;["SVG","MATH","STYLE","SCRIPT","IFRAME","TEMPLATE","NOSCRIPT","OBJECT","EMBED","BASE","FORM"].forEach((t)=>check("policy: "+t+" dropped",NotesPro.sanTagAction(t,"render")==="drop"))
check("policy: paste drops app classes",NotesPro.sanClass("note-callout app-modal-card","paste")==="note-callout")
check("policy: paste drops unknown data-*",NotesPro.sanAttr("DIV","data-foo","x","paste")===null)
const md=LoyaMarkdown.toHtml("[x](javascript:alert(1)) ![i](data:text/html,x) <img src=x onerror=alert(1)> [ok](https://a.b/c)")
check("markdown: no javascript/data link",!/href="(?:javascript|data):/i.test(md),md)
check("markdown: raw HTML escaped",!/<img/i.test(md)&&/&lt;img/.test(md),md)
check("markdown: https link kept",/href="https:\/\/a\.b\/c"/.test(md),md)

// SA-15: a cmd: link copies only what it shows.
const cmdFns=new Function("atob","TextDecoder",["notesDecodeCmdToken","notesCmdLinkCopyText"].map((n)=>grab(notesSrc,n)).join("\n")+"\nreturn {notesCmdLinkCopyText}")((x)=>Buffer.from(x,"base64").toString("latin1"),TextDecoder)
const tokOf=(cmd)=>Buffer.from(JSON.stringify({command:cmd}),"utf8").toString("base64").replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/,"")
const evilTok=tokOf("rm -rf ~")
check("SA-15 link text matches -> copied",cmdFns.notesCmdLinkCopyText("cmd:copy:"+tokOf("nmap -sV 10.0.0.1"),"  nmap  -sV 10.0.0.1 ","")==="nmap -sV 10.0.0.1")
check("SA-15 link text differs -> refused",cmdFns.notesCmdLinkCopyText("cmd:copy:"+evilTok,"ls","")===null)
check("SA-15 card image from the same token -> copied",cmdFns.notesCmdLinkCopyText("cmd:edit:"+evilTok,"","cmdcard:"+evilTok)==="rm -rf ~")
check("SA-15 card image from another token -> refused",cmdFns.notesCmdLinkCopyText("cmd:edit:"+evilTok,"","cmdcard:"+tokOf("ls"))===null)
check("SA-15 no command -> nothing",cmdFns.notesCmdLinkCopyText("cmd:copy:!!!","x","")==="")
// H-05: navigation guard.
const NG=require(path.join(ROOT,"UI","js","components","nav-guard.js"))
function ev(target,extra){const e=Object.assign({target,defaultPrevented:false,preventDefault(){this.defaultPrevented=true}},extra||{});return e}
const linkEl={closest:(sel)=>/a\[href\]/.test(sel)?{href:"https://evil.example"}:null}
const plainEl={closest:()=>null}
let e1=ev(linkEl);NG.onClick(e1);check("H-05 link click never navigates",e1.defaultPrevented)
let e2=ev(plainEl);NG.onClick(e2);check("H-05 non-link click untouched",!e2.defaultPrevented)
let e3=ev(plainEl);NG.onSubmit(e3);check("H-05 form submit blocked",e3.defaultPrevented)
let e4=ev(plainEl,{dataTransfer:{types:["text/uri-list"],dropEffect:"copy"}});NG.onDragOver(e4);check("H-05 URL drag gets dropEffect none",e4.defaultPrevented&&e4.dataTransfer.dropEffect==="none")
let e5=ev(plainEl,{dataTransfer:{types:["text/uri-list"]}});NG.onDrop(e5);check("H-05 unhandled URL drop blocked",e5.defaultPrevented)
const editEl={closest:(sel)=>/contenteditable/.test(sel)?{}:null}
let e6=ev(editEl,{dataTransfer:{types:["text/plain","text/uri-list"]}});NG.onDrop(e6);check("H-05 text drop into an editor keeps working",!e6.defaultPrevented)
let e7=ev(editEl,{dataTransfer:{types:["Files"]}});NG.onDrop(e7);check("H-05 unhandled file drop into an editor blocked",e7.defaultPrevented)
const listeners={};const fakeWin={document:{addEventListener:(t,f,c)=>{listeners["d:"+t]=c}},addEventListener:(t)=>{listeners["w:"+t]=1}}
check("H-05 install once",NG.install(fakeWin)===true&&NG.install(fakeWin)===false)
check("H-05 click/auxclick/submit are capture listeners",listeners["d:click"]===true&&listeners["d:auxclick"]===true&&listeners["d:submit"]===true)
check("H-05 window.open disabled",fakeWin.open()===null)
const mainHtml=fs.readFileSync(path.join(ROOT,"UI","windows","main.html"),"utf8"),miniHtml=fs.readFileSync(path.join(ROOT,"UI","windows","mini.html"),"utf8")
;[["main",mainHtml],["mini",miniHtml]].forEach(([n,h])=>{const b=h.indexOf("js/bridge.js"),g=h.indexOf("components/nav-guard.js");check("H-05 "+n+".html loads nav-guard right after bridge.js",b>0&&g>b&&!/<script[^>]*src="[^"]*(pages|windows)\//.test(h.slice(b,g)))})
// H-04: Quick Space HTML is sanitised before it reaches the mini window.
const miniSrc=fs.readFileSync(path.join(ROOT,"UI","js","windows","mini.js"),"utf8")
check("H-04 no raw innerHTML for Quick Space",!/miniQuickBody\(\)\.innerHTML=/.test(miniSrc))
check("H-04 Quick Space goes through the notes allow-list",/function miniSanitizeNode[\s\S]*NotesPro\.sanTagAction[\s\S]*NotesPro\.sanAttr/.test(miniSrc)&&/notes_pro_core\.js/.test(miniHtml))
// Remote images: blocked behind a click-to-load placeholder, restored on save.
const proSrc=fs.readFileSync(path.join(ROOT,"UI","js","pages","notes_pro.js"),"utf8")
function fakeImg(attrs){const a=Object.assign({},attrs);const cls=new Set();return {attrs:a,cls,getAttribute:(k)=>k in a?a[k]:null,setAttribute:(k,v)=>{a[k]=String(v)},removeAttribute:(k)=>{delete a[k]},classList:{add:(c)=>cls.add(c),remove:(c)=>cls.delete(c)},remove(){this.removed=true}}}
const rim=new Function("notesState",["notesProRemoteImagesBlocked","notesProBlockRemoteImg","notesProLoadRemoteImg","notesProUnblockForSave"].map((n)=>grab(proSrc,n)).join("\n")+"\nreturn {notesProRemoteImagesBlocked,notesProBlockRemoteImg,notesProLoadRemoteImg,notesProUnblockForSave}")
const on=rim({prefs:{}}),off=rim({prefs:{block_remote_images:false}})
check("remote images: blocked by default",on.notesProRemoteImagesBlocked()&&!off.notesProRemoteImagesBlocked())
const img=fakeImg({src:"https://tracker.example/p.gif"});on.notesProBlockRemoteImg(img,img.attrs.src)
check("remote images: no src while blocked",!("src" in img.attrs)&&img.attrs["data-loya-remote-src"]==="https://tracker.example/p.gif"&&img.cls.has("note-remote-blocked"))
const img2=fakeImg({src:"https://tracker.example/p.gif"});on.notesProBlockRemoteImg(img2,img2.attrs.src);on.notesProUnblockForSave({querySelectorAll:()=>[img2]})
check("remote images: saving restores the original src",img2.attrs.src==="https://tracker.example/p.gif"&&!("data-loya-remote-src" in img2.attrs)&&!("title" in img2.attrs))
check("remote images: click loads it",on.notesProLoadRemoteImg(img)&&img.attrs.src==="https://tracker.example/p.gif")
const bad=fakeImg({"data-loya-remote-src":"javascript:alert(1)"})
check("remote images: a non-http placeholder never becomes a src",!on.notesProLoadRemoteImg(bad)&&!("src" in bad.attrs))
check("remote images: render mode blocks http(s) img",/mode==="render"&&\/\^https\?:\/i\.test\(src\)&&notesProRemoteImagesBlocked\(\)\)notesProBlockRemoteImg/.test(proSrc))
check("remote images: CleanClone unblocks before saving",/function notesProCleanClone\(clone\)\{\nnotesProUnblockForSave\(clone\)/.test(proSrc))

// SA-34: confirm dialog traps focus, Esc cancels, labels are text.
const CD=require(path.join(ROOT,"UI","js","components","confirm-dialog.js"))
function fakeBtn(name){return {name,focus(){doc.activeElement=this},closest:()=>null}}
const doc={activeElement:null}
const b1=fakeBtn("cancel"),b2=fakeBtn("ok")
const box={ownerDocument:doc,querySelectorAll:()=>[b1,b2],contains:(el)=>el===b1||el===b2}
function key(k,shift){return {key:k,shiftKey:!!shift,defaultPrevented:false,stopped:false,preventDefault(){this.defaultPrevented=true},stopPropagation(){this.stopped=true}}}
let closed=null;const close=(v)=>{closed=v}
doc.activeElement=b2;let k1=key("Tab");CD.confirmTrapKey(k1,box,close);check("SA-34 Tab from the last button wraps to the first",k1.defaultPrevented&&doc.activeElement===b1)
doc.activeElement=b1;let k2=key("Tab",true);CD.confirmTrapKey(k2,box,close);check("SA-34 Shift+Tab from the first wraps to the last",k2.defaultPrevented&&doc.activeElement===b2)
doc.activeElement={};let k3=key("Tab");CD.confirmTrapKey(k3,box,close);check("SA-34 focus outside is pulled back in",k3.defaultPrevented&&doc.activeElement===b1)
let k4=key("Escape");CD.confirmTrapKey(k4,box,close);check("SA-34 Esc cancels",closed===false&&k4.defaultPrevented)
const cdSrc=fs.readFileSync(path.join(ROOT,"UI","js","components","confirm-dialog.js"),"utf8")
check("SA-34 button labels are set as text, never HTML",!/\$\{opts\.(okLabel|cancelLabel)|\$\{opts\.extraLabel\}/.test(cdSrc)&&/\.textContent=opts\.okLabel/.test(cdSrc))
check("SA-34 long names wrap",/\.confirm-message\{[^}]*overflow-wrap:anywhere/.test(fs.readFileSync(path.join(ROOT,"UI","css","components.css"),"utf8")))
// SA-35: a fast click on a window edge must not leave resize mode on.
const RS=fs.readFileSync(path.join(ROOT,"UI","js","components","resize.js"),"utf8")
const winL={},elL={};let calls=[];let resolveBounds=null
const fakeWindow={addEventListener:(t,f)=>{winL[t]=f}}
const fakeEl={addEventListener:(t,f)=>{elL[t]=f}}
const bridge=(m,a)=>{if(m==="window.bounds")return new Promise((r)=>{resolveBounds=r});calls.push(a);return Promise.resolve()}
const mod=new Function("window","bridgeCall","module",RS+"\nreturn {initResizeHandle}")(fakeWindow,bridge,{exports:{}})
mod.initResizeHandle(fakeEl,{e:true})
const ev0={screenX:100,screenY:100,preventDefault(){},stopPropagation(){}}
elL.mousedown(ev0);winL.mouseup({})
resolveBounds({x:0,y:0,w:800,h:600})
setTimeout(()=>{
winL.mousemove({screenX:300,screenY:100,buttons:0})
check("SA-35 late bounds after mouseup do not start resizing",calls.length===0)
elL.mousedown(ev0);resolveBounds({x:0,y:0,w:800,h:600})
setTimeout(()=>{
winL.mousemove({screenX:300,screenY:100,buttons:1})
check("SA-35 a real drag still resizes",calls.length===1&&calls[0][2]===1000)
winL.mousemove({screenX:320,screenY:100,buttons:0})
check("SA-35 a move with no button held stops resizing",calls.length===1)
console.log("")
console.log(passed+" passed, "+failed+" failed")
process.exit(failed?1:0)
},0)
},0)
