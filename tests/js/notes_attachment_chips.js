// Notes file attachment chips: click (viewer) / double-click (editor) opens, right-click shows Open / Save as..., and only the
// attachment id and shown name go to the bridge.
const fs=require("fs")
const path=require("path")
const ROOT=path.resolve(__dirname,"..","..")
const source=fs.readFileSync(path.join(ROOT,"UI","js","pages","notes.js"),"utf8")
function grab(name){
const start=source.indexOf("function "+name+"(")
if(start<0)throw new Error("missing "+name)
const next=source.indexOf("\nfunction ",start+1)
return source.slice(start,next<0?undefined:next).split("\nlet ")[0]
}
let passed=0,failed=0
function check(name,cond,detail){if(cond){passed++;return}failed++;console.log("  FAIL  "+name+(detail?"  ->  "+detail:""))}
const calls=[],menus=[],toasts=[]
const bridgeCall=(m,a)=>{calls.push([m,a]);return Promise.resolve(m==="notes.attachment_open"?{name:a[1]}:"/home/u/out.pdf")}
const openContextMenu=(items,x,y)=>menus.push({items,x,y})
const showToast=(m,k)=>toasts.push([m,k||""])
const names=["notesAttachmentChipInfo","notesAttachmentError","notesAttachmentOpen","notesAttachmentSaveAs","notesAttachmentMenu","notesWireAttachmentChips"]
const api=new Function("bridgeCall","openContextMenu","showToast",names.map(grab).join("\n")+"\nreturn {"+names.join(",")+"}")(bridgeCall,openContextMenu,showToast)
// Tiny fake DOM: closest() over a parent chain, querySelector for the file name.
function node(cls,parent,extra){const n=Object.assign({cls,parent,dataset:{},closest(sel){let c=this;while(c){if(sel.split(",").some((s)=>c.cls.split(" ").some((k)=>s.includes("."+k))&&(!s.includes("[data-attachment-id]")||c.dataset.attachmentId)))return c;c=c.parent}return null},querySelector(sel){return sel===".note-embed-filename"?this._name:null}},extra||{});return n}
function root(){const h={};return {dataset:{},h,addEventListener(t,f,cap){(h[t]=h[t]||[]).push({f,cap:!!cap})}}}
const fig=node("note-embed note-embed-inline",null);fig.dataset.attachmentId="0123456789abcdef"
const chip=node("note-embed-file",fig);chip._name={textContent:" report.pdf "}
const fname=node("note-embed-filename",chip)
const plain=node("other",null)
const info=api.notesAttachmentChipInfo(fname)
check("chip info from a click on the file name",info&&info.id==="0123456789abcdef"&&info.name==="report.pdf"&&info.chip===chip)
check("no chip, no info",api.notesAttachmentChipInfo(plain)===null)
function ev(target,extra){return Object.assign({target,button:0,clientX:10,clientY:20,prevented:false,stopped:false,preventDefault(){this.prevented=true},stopPropagation(){this.stopped=true}},extra||{})}
const tick=()=>new Promise((r)=>setTimeout(r,0))
;(async()=>{
const ed=root();api.notesWireAttachmentChips(ed,"edit");api.notesWireAttachmentChips(ed,"edit")
check("editor: wired once",(ed.h.dblclick||[]).length===1&&!ed.h.click)
check("editor: context menu listener is capture phase (runs before the editor menu)",ed.h.contextmenu&&ed.h.contextmenu[0].cap)
ed.h.dblclick[0].f(ev(fname))
await tick()
check("editor: double-click opens by id + name",JSON.stringify(calls[0])===JSON.stringify(["notes.attachment_open",["0123456789abcdef","report.pdf"]]),JSON.stringify(calls))
check("open: success toast",toasts.some((t)=>t[0]==="Opened report.pdf"))
const e2=ev(fname);ed.h.contextmenu[0].f(e2)
check("right-click: own menu, editor menu stopped",e2.prevented&&e2.stopped&&menus.length===1)
const labels=menus[0].items.map((i)=>i.label)
check("menu: Open and Save as...",labels.join("|")==="Open|Save as…",labels.join("|"))
menus[0].items[1].fn()
await tick()
check("Save as goes to the bridge with id + name only",JSON.stringify(calls[1])===JSON.stringify(["notes.attachment_save_as",["0123456789abcdef","report.pdf"]]))
check("save: toast with the path",toasts.some((t)=>t[0]==="Saved /home/u/out.pdf"))
const e3=ev(plain);ed.h.contextmenu[0].f(e3)
check("right-click elsewhere: editor menu untouched",!e3.prevented&&!e3.stopped&&menus.length===1)
const vw=root();api.notesWireAttachmentChips(vw,"view")
check("viewer: single click opens",(vw.h.click||[]).length===1&&!vw.h.dblclick)
vw.h.click[0].f(ev(fname))
await tick()
check("viewer: click calls open",calls.length===3&&calls[2][0]==="notes.attachment_open")
check("viewer and editor are wired",/notesWireAttachmentChips\(body,"view"\)/.test(source)&&/function notesWireAttachmentEmbeds\(body\)\{\nnotesWireAttachmentChips\(body,"edit"\)/.test(source))
console.log("")
console.log(passed+" passed, "+failed+" failed")
process.exit(failed?1:0)
})()
