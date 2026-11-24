// Editor hosts (notes.js notesHost*): the note editor and the report fields share one editor implementation, with exactly one active host. Run: node tests/js/notes_hosts.js
const fs=require("fs")
const path=require("path")
const ROOT=path.resolve(__dirname,"..","..")
const read=(f)=>fs.readFileSync(path.join(ROOT,"UI","js","pages",f),"utf8")
const source=read("notes.js"),pro=read("notes_pro.js"),widgets=read("reporting_widgets.js")
function grab(name){
const start=source.indexOf("function "+name+"(")
if(start<0)throw new Error("missing "+name)
const next=source.indexOf("\nfunction ",start+1)
return source.slice(start,next<0?undefined:next)
}
let passed=0,failed=0
function check(name,cond,detail){if(cond){passed++;return}failed++;console.log("  FAIL  "+name+(detail?"  ->  "+detail:""))}
function eq(name,a,b){check(name,JSON.stringify(a)===JSON.stringify(b),JSON.stringify(a)+" != "+JSON.stringify(b))}
const names=["notesHostHas","notesHostEl","notesHostWrap","notesHostOpen","notesHostTag","notesHostBodies","notesHostFor","notesHostTouch","notesHostStore","notesHostData","notesHostActivate","notesHostUnmount","notesEditorBody"]
const log=[]
function body(id){return {id:id,innerHTML:"<p>"+id+"</p>",isConnected:true,contains:(n)=>n===id}}
const wrapOf=(id)=>({id:"wrap-"+id,kids:[],appendChild(o){if(o.parentNode)o.parentNode.kids=[];o.parentNode=this;this.kids=[o]}})
const env=new Function("log","document","bridgeCall",`
let notesHost=null,notesHostNotes=null
const notesHosts=[]
let notesState={savedRange:null,cmdCards:{},dirty:false,pendingAttachments:[]}
let notesUndoState={stack:[{html:"",offset:0}],pointer:0,debounceTimer:null,applying:false}
const overlay={parentNode:null}
function notesProSlashClose(){log.push("slash")}
function notesProChipHide(){log.push("chip")}
function notesProSetHover(){log.push("hover")}
function notesProOverlay(){return overlay}
function notesUndoPushSnapshot(){log.push("snapshot:"+notesHost.id)}
function notesScheduleDraftSave(){log.push("draft")}
function notesEditorOpen(){return true}
${names.map(grab).join("\n")}
return {
mount:(h)=>{notesHosts.push(h);if(!notesHost)notesHostActivate(h);return h},
setNotes:(h)=>{notesHostNotes=h},
get host(){return notesHost},get state(){return notesState},get undo(){return notesUndoState},set undo(v){notesUndoState=v},overlay,hosts:notesHosts,
notesHostHas,notesHostEl,notesHostWrap,notesHostOpen,notesHostTag,notesHostBodies,notesHostFor,notesHostTouch,notesHostStore,notesHostData,notesHostActivate,notesHostUnmount,notesEditorBody}
`)(log,{getElementById:(id)=>({fallback:id})},(m,a)=>{log.push("bridge:"+m);return Promise.resolve(m==="notes.insert_attachment"?{id:"att1",url:"file:///x"}:{data_url:"data:x"})})
const notes=env.mount({id:"notes",native:true,body:body("nb"),wrap:wrapOf("n")})
env.setNotes(notes)
eq("the first mounted host is active",env.host.id,"notes")
eq("active body",env.notesEditorBody().id,"nb")
eq("the overlay sits in the active host's wrap",env.overlay.parentNode.id,"wrap-n")
check("the note editor has every feature",env.notesHostHas("noteLinks")&&env.notesHostHas("suggest"))
eq("the note editor resolves controls by id",env.notesHostEl("notesInsertCmd"),{fallback:"notesInsertCmd"})
eq("tags are not mapped in notes",env.notesHostTag("h1"),"h1")
env.notesHostTouch()
check("notes: an edit marks the note dirty and schedules the draft",env.state.dirty===true&&log.indexOf("draft")>=0)
let dirtyCalls=0
const stored=[]
const rep=env.mount({id:"report-1",body:body("rb"),wrap:wrapOf("r"),isOpen:()=>true,el:(id)=>id==="notesInsertCmd"?"btn":null,features:{noteLinks:false,suggest:false},tags:{h1:"h3",h2:"h3",h3:"h4"},onDirty:()=>{dirtyCalls++},store:(n,d)=>{stored.push(n);return Promise.resolve({id:"uid1",url:"blob:x"})},data:(id)=>Promise.resolve("data:"+id)})
eq("mounting a second host does not steal the editor",env.host.id,"notes")
env.state.savedRange="RANGE-N";env.state.cmdCards.c1={command:"id"};env.undo.debounceTimer=setTimeout(()=>{},10000)
log.length=0
env.notesHostActivate(rep)
eq("switching activates the other host",env.host.id,"report-1")
check("switching flushes the pending undo snapshot of the old host and closes its floating UI",log.indexOf("snapshot:notes")>=0&&log.indexOf("slash")>=0&&log.indexOf("chip")>=0&&log.indexOf("hover")>=0,log.join(","))
eq("the old host keeps its selection and cards",[notes.savedRange,Object.keys(notes.cmdCards)],["RANGE-N",["c1"]])
eq("the new host starts with its own state",[env.state.savedRange,Object.keys(env.state.cmdCards),env.undo.stack[0].html],[null,[],"<p>rb</p>"])
eq("the overlay moved",env.overlay.parentNode.id,"wrap-r")
eq("report host: features, controls, tags",[env.notesHostHas("noteLinks"),env.notesHostHas("drawing"),env.notesHostEl("notesInsertCmd"),env.notesHostEl("notesEditorCount"),env.notesHostTag("h1"),env.notesHostTag("h3"),env.notesHostTag("p")],[false,true,"btn",null,"h3","h4","p"])
env.state.dirty=false;log.length=0
env.notesHostTouch()
check("report host: an edit goes to its own hook, never to the note draft",dirtyCalls===1&&env.state.dirty===false&&log.indexOf("draft")<0)
eq("host lookup by node",[env.notesHostFor("rb").id,env.notesHostFor("nb").id,env.notesHostFor("zz")],["report-1","notes",null])
eq("open bodies",env.notesHostBodies().map((b)=>b.id),["nb","rb"])
Promise.all([env.notesHostStore("a.png","data:image/png;base64,AA"),env.notesHostData("uid9")]).then((r)=>{
eq("report host: images go to its store, not to notes attachments",[r[0].id,r[1],stored,log.filter((l)=>/^bridge:/.test(l)),env.state.pendingAttachments],["uid1","data:uid9",["a.png"],[],[]])
env.state.savedRange="RANGE-R"
env.notesHostActivate(notes)
eq("switching back restores the note editor's state",[env.host.id,env.state.savedRange,Object.keys(env.state.cmdCards),rep.savedRange],["notes","RANGE-N",["c1"],"RANGE-R"])
return Promise.all([env.notesHostStore("b.png","data:x"),env.notesHostData("att1")])
}).then((r)=>{
eq("notes host: attachments go through the notes bridge and are tracked as pending",[r[0].id,r[1],env.state.pendingAttachments],["att1","data:x",["att1"]])
env.notesHostActivate(rep)
env.notesHostUnmount(rep)
eq("unmounting the active host hands the editor back to notes",[env.host.id,env.hosts.length,env.overlay.parentNode.id],["notes",1,"wrap-n"])
env.notesHostActivate(rep)
eq("an unmounted host cannot be activated",env.host.id,"notes")
// ---- wiring the rest of the editor relies on
check("notes.js: every body listener is attached through notesHostWireBody",/function notesHostWireBody\(body\)\{/.test(source)&&/notesHostWireBody\(h\.body\)/.test(source))
check("notes.js: the note editor is a host too",/notesHostNotes=notesHostMount\(\{id:"notes",native:true/.test(source))
check("notes.js: opening or serialising a note always works on the note editor's host",/function notesResetEditor\([^)]*\)\{\nnotesHostActivate\(notesHostNotes\)/.test(source)&&/function notesSerializeContent\(\)\{\nnotesHostActivate\(notesHostNotes\)/.test(source)&&/function notesCollectCmds\(\)\{\nnotesHostActivate\(notesHostNotes\)/.test(source))
check("notes_pro.js: attachments and drawings are stored through the host",!/bridgeCall\("notes\.insert_attachment"/.test(pro)&&!/bridgeCall\("notes\.attachment_data"/.test(pro)&&/notesHostStore\(/.test(pro)&&/notesHostData\(/.test(pro))
check("notes.js: the only direct attachment call is the host fallback",(source.match(/bridgeCall\("notes\.insert_attachment"/g)||[]).length===1)
check("notes_pro.js: no direct dirty flag writes (hosts decide)",!/notesState\.dirty=true/.test(pro))
check("notes_pro.js: overlay and per-body wiring are separate",/function notesProInitOverlay\(\)\{/.test(pro)&&/function notesProWireBody\(body\)\{/.test(pro))
check("report fields mount the shared editor and never call the notes attachment bridge",/notesHostMount\(\{/.test(widgets)&&!/notes\.insert_attachment|notes\.attachment_data/.test(widgets)&&/store:storeAsset/.test(widgets))
check("report fields never use localStorage",!/localStorage|sessionStorage/.test(widgets))
console.log("")
console.log(passed+" passed, "+failed+" failed")
process.exit(failed?1:0)
}).catch((e)=>{console.error(e);process.exit(1)})
