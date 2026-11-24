const fs=require("fs")
const path=require("path")
const ROOT=path.resolve(__dirname,"..","..")
const source=fs.readFileSync(path.join(ROOT,"UI","js","pages","notes.js"),"utf8")
function grab(name){
const start=source.indexOf("function "+name+"(")
if(start<0)throw new Error("missing "+name)
const next=source.indexOf("\nfunction ",start+1)
return source.slice(start,next<0?undefined:next)
}
const api=new Function("atob","TextDecoder",["notesDecodeCmdToken","notesPhClassify"].map(grab).join("\n")+"\nreturn {notesDecodeCmdToken,notesPhClassify}")((s)=>Buffer.from(s,"base64").toString("latin1"),TextDecoder)
// The sidebar search moved to notes_sidebar_core.js (NotesSidebar.matchNote); the full suite is tests/js/notes_sidebar.js.
const SB=require(path.join(ROOT,"UI","js","pages","notes_sidebar_core.js"))
api.notesNoteMatches=(n,q)=>SB.matchNote(n,SB.searchWords(q),["name","tags"],null)
let passed=0,failed=0
function check(name,cond,detail){if(cond){passed++;return}failed++;console.log("  FAIL  "+name+(detail?"  ->  "+detail:""))}
function eq(name,a,b){check(name,JSON.stringify(a)===JSON.stringify(b),JSON.stringify(a)+" != "+JSON.stringify(b))}
const n={note_name:"Recon Box",group_name:"HTB",tags:"web, linux",preview:"secret body text"}
check("search matches name",api.notesNoteMatches(n,"recon"))
check("search matches group",api.notesNoteMatches(n,"htb"))
check("search matches tags",api.notesNoteMatches(n,"linux"))
check("search ignores body preview",!api.notesNoteMatches(n,"secret"))
check("empty search matches all",api.notesNoteMatches(n,""))
const tok=Buffer.from(JSON.stringify({command:"nmap -sV {IP} é",note_id:3,note_name:"Box"}),"utf8").toString("base64").replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/,"")
eq("decode urlsafe token (unpadded, utf-8)",api.notesDecodeCmdToken(tok).command,"nmap -sV {IP} é")
eq("decode note link token",api.notesDecodeCmdToken(tok).note_id,3)
eq("decode garbage is empty",api.notesDecodeCmdToken("!!!"),{})
const keys=new Set(["ip","url path"])
eq("known key (case-insensitive)",api.notesPhClassify("IP",keys),"known")
eq("known key with space",api.notesPhClassify("URL Path",keys),"known")
eq("unknown key",api.notesPhClassify("PORT",keys),"unknown")
eq("empty braces invalid",api.notesPhClassify("",keys),"invalid")
eq("padded key invalid",api.notesPhClassify(" IP",keys),"invalid")
// ---- WebKitGTK list-in-<p> repair and font-size span reuse (tiny fake DOM: just what the two functions touch)
function el(tag,kids,style){const e={nodeType:1,tagName:tag,childNodes:[],parentNode:null,_style:style||"",getAttribute:(k)=>k==="style"?e._style:null,
get firstChild(){return e.childNodes[0]||null},get textContent(){return e.childNodes.map((c)=>c.textContent).join("")},
insertBefore(c,ref){if(c.parentNode)c.parentNode.removeChild(c);e.childNodes.splice(e.childNodes.indexOf(ref),0,c);c.parentNode=e;return c},
removeChild(c){e.childNodes.splice(e.childNodes.indexOf(c),1);c.parentNode=null;return c}};(kids||[]).forEach((k)=>{k.parentNode=e;e.childNodes.push(k)});return e}
function txt(s){return {nodeType:3,textContent:s,parentNode:null}}
const dom=new Function(["notesLiftListFromP","notesFontSpanFor"].map(grab).join("\n")+"\nreturn {notesLiftListFromP,notesFontSpanFor}")()
const t1=txt("one"),li=el("LI",[t1]),ul=el("UL",[li]),after=el("DIV",[txt("next")]),para=el("P",[ul,after]),body=el("DIV",[el("PRE",[txt("code")]),para])
check("list in <p>: lifted out",dom.notesLiftListFromP(body,t1)&&body.childNodes.map((c)=>c.tagName).join()==="PRE,UL,DIV"&&ul.parentNode===body&&para.parentNode===null)
check("list in <p>: list already at the top level is left alone",!dom.notesLiftListFromP(body,t1))
const t2=txt("x"),ol=el("OL",[el("LI",[t2])]),body2=el("DIV",[ol])
check("list in <p>: no paragraph, no change",!dom.notesLiftListFromP(body2,t2)&&ol.parentNode===body2)
const t3=txt("big"),fsp=el("SPAN",[t3],"font-size: 15px;"),body3=el("DIV",[el("DIV",[txt("a "),fsp])])
check("font size: the span the selection already fills is reused",dom.notesFontSpanFor({commonAncestorContainer:t3,toString:()=>"big"},body3)===fsp)
check("font size: a partial selection gets a new span",dom.notesFontSpanFor({commonAncestorContainer:t3,toString:()=>"bi"},body3)===null)
const t4=txt("red"),colored=el("SPAN",[t4],"color: red; font-size: 15px;"),body4=el("DIV",[colored])
check("font size: a span with other styles is not reused",dom.notesFontSpanFor({commonAncestorContainer:t4,toString:()=>"red"},body4)===null)
const src2=source
check("font size: notesExec repairs list-in-<p> after list commands",/function notesExec\([^)]*\)\{[^\n]*notesFixListInP\(\)/.test(src2))
check("execCommand never gets a null value (WebKit writes <hr id=\"null\">)",!/execCommand\([^)]*,null\)/.test(src2)&&!/arg\|\|null/.test(src2))
check("note link popover: search is focused and Enter picks the first match",/notesOpenLinkPopover[\s\S]*?search\.focus\(\)\n\}/.test(src2))
console.log("")
console.log(passed+" passed, "+failed+" failed")
process.exit(failed?1:0)
