// Pure helpers of the report export/import dialogs (UI/js/pages/reporting_export.js). Run: node tests/js/reporting_export.js
const path=require("path")
const fs=require("fs")
const ROOT=path.resolve(__dirname,"..","..")
const file=path.join(ROOT,"UI","js","pages","reporting_export.js")
const RX=require(file)
const P=RX._pure
let passed=0,failed=0
function check(name,cond,detail){if(cond){passed++;return}failed++;console.log("  FAIL  "+name+(detail?"  ->  "+detail:""))}
const eq=(a,b)=>JSON.stringify(a)===JSON.stringify(b)
// public surface from the contract
check("exports open/openImport",typeof RX.open==="function"&&typeof RX.openImport==="function")
check("exports helpers used by other pages",["exportAll","exportTemplates","exportLibrary","tryStaged","mountDefaults"].every((k)=>typeof RX[k]==="function"))
// formats mirror the bridge
check("eight formats in contract order",eq(P.FORMATS.map((f)=>f.id),["pdf","docx","html","markdown","json","csv","xlsx","sarif"]))
check("every format has label/ext/description",P.FORMATS.every((f)=>f.label&&f.ext&&f.description&&f.description.length<110))
const py=fs.readFileSync(path.join(ROOT,"Cores","Services","report_export.py"),"utf8")
check("descriptions match the Python formats table",P.FORMATS.every((f)=>py.includes('"id":"'+f.id+'","label":"'+f.label+'","ext":"'+f.ext+'","description":"'+f.description+'"')))
// which options apply to which format
check("pdf takes every option but font embedding",eq(P.applicable("pdf"),{page_size:true,theme:true,embed_fonts:false,include_cover:true,include_toc:true,include_appendices:true,redact:true,findings_status:true}))
check("fonts are embedded on request in html only",P.applicable("html").embed_fonts===true&&P.applicable("docx").embed_fonts===false&&P.applicable("docx").theme===true&&P.applicable("markdown").theme===false)
check("a theme override crosses the bridge only when chosen",P.exportOptions(Object.assign(P.initialState({},{},{format:"pdf"}),{theme:"modern"})).theme==="modern"&&!("theme" in P.exportOptions(P.initialState({},{},{format:"pdf"})))&&!("theme" in P.exportOptions(Object.assign(P.initialState({},{},{format:"csv"}),{theme:"modern"}))))
check("pdf result names the engine",/built-in print engine/.test(P.exportMessage({path:"/x/r.pdf",format:"pdf",native:true,message:"PDF created with the built-in print engine."}))&&P.exportMessage({path:"/x/r.csv",format:"csv",message:""})==="Report exported to /x/r.csv"&&P.exportMessage(null)==="")
check("markdown has no page size",P.applicable("markdown").page_size===false&&P.applicable("markdown").include_toc===true)
check("csv/xlsx/sarif are findings only, still masked",["csv","xlsx","sarif"].every((f)=>{const a=P.applicable(f);return !a.page_size&&!a.include_cover&&a.redact&&a.findings_status}))
check("json is never masked (backup format)",P.applicable("json").redact===false)
check("json takes no options",Object.values(P.applicable("json")).every((v)=>v===false))
// initial state precedence
const rep={options:{page_size:"Letter",include_toc:false,include_appendices:true},branding:{show_cover:false}}
let s=P.initialState(rep,{default_format:"docx",page_size:"A4",include_toc:true,redact_evidence:false},{})
check("report options win for layout",s.page_size==="Letter"&&s.include_toc===false&&s.include_appendices===true)
check("format from defaults",s.format==="docx")
check("cover from report branding, masking on by default whatever the capture setting",s.include_cover===false&&s.redact===true)
check("masking stays off only when the user turned it off",P.initialState(rep,{},{redact:false}).redact===false)
check("all statuses by default",eq(s.findings_status,["open","retest","fixed","accepted"]))
s=P.initialState(rep,{default_format:"docx"},{format:"html",include_cover:true,redact:true,findings_status:["fixed","bogus","fixed"]})
check("last choices win for format/cover/redact/statuses",s.format==="html"&&s.include_cover===true&&s.redact===true&&eq(s.findings_status,["fixed"]))
s=P.initialState(null,null,{format:"exe",findings_status:"x"})
check("junk falls back to safe defaults",s.format==="pdf"&&s.page_size==="A4"&&s.include_toc===true&&s.include_cover===true&&s.redact===true&&s.findings_status.length===4)
s=P.initialState({options:{page_size:"B5"}},{page_size:"Letter"},{})
check("invalid page size falls through",s.page_size==="Letter")
// options sent over the bridge
const st={format:"pdf",page_size:"A4",include_cover:true,include_toc:false,include_appendices:true,redact:true,findings_status:["open","retest","fixed","accepted"]}
check("pdf options, no status filter when all are selected",eq(P.exportOptions(st),{page_size:"A4",include_cover:true,include_toc:false,include_appendices:true,redact:true}))
check("status filter is sent when narrowed",eq(P.exportOptions(Object.assign({},st,{findings_status:["open"]})).findings_status,["open"]))
check("csv sends masking and the status filter",eq(P.exportOptions(Object.assign({},st,{format:"csv",findings_status:["open","fixed"]})),{redact:true,findings_status:["open","fixed"]}))
check("json sends nothing",eq(P.exportOptions(Object.assign({},st,{format:"json",findings_status:["open"]})),{}))
check("markdown omits page size",!("page_size" in P.exportOptions(Object.assign({},st,{format:"markdown"}))))
// summaries
check("summary chips pluralise",eq(P.summaryChips({reports:1,findings:2,sections:0,assets:1,evidence:3,library:1,templates:2}),["1 report","2 templates","1 library entry","2 findings","1 image","3 evidence items"]))
check("summary chips tolerate nothing",eq(P.summaryChips(null),[]))
// testers text <-> list
const list=P.parseTesters("Alex Tester, Lead, alex@x.example\n\n  Sam Pwn ,Consultant\nSolo\n , , \nA, B, c@d, extra")
check("testers parse",eq(list,[{name:"Alex Tester",role:"Lead",email:"alex@x.example"},{name:"Sam Pwn",role:"Consultant",email:""},{name:"Solo",role:"",email:""},{name:"A",role:"B",email:"c@d, extra"}]))
check("testers format round trip",eq(P.parseTesters(P.formatTesters(list)),list))
check("testers format trims empty tails",P.formatTesters([{name:"Solo"}])==="Solo"&&P.formatTesters(null)==="")
// small guards
check("hex colours",P.validHex("#1f4e79")&&P.validHex(" #ABCDEF ")&&!P.validHex("#12345")&&!P.validHex("red")&&!P.validHex("#1f4e79;}"))
check("importable files",P.importable("a.JSON")&&P.importable("scan.csv")&&P.importable("x.tsv")&&!P.importable("a.zip")&&!P.importable("noext"))
check("escape",P.esc('<img src=x onerror="a">&\'')==="&lt;img src=x onerror=&quot;a&quot;&gt;&amp;&#39;")
// source hygiene: Linux/WebKitGTK pitfalls and the injection rules from the contract
const src=fs.readFileSync(file,"utf8")
check("no localStorage/sessionStorage",!/localStorage|sessionStorage/.test(src))
check("no native dialog element or alert/confirm/prompt",!/<dialog|\balert\(|\bprompt\(|window\.confirm\(/.test(src))
const inner=src.split("\n").filter((l)=>/\.innerHTML\s*=/.test(l))
check("innerHTML only ever receives static markup",inner.every((l)=>/innerHTML=""|innerHTML='<i class="icon icon-add rpt-x-drop-icon">/.test(l)&&!/\$\{|\+/.test(l.split("innerHTML=")[1]||"")),inner.join(" | "))
check("classes are prefixed rpt-x- (or shared rpt- widgets)",(src.match(/el\("[a-z]+","([^"]+)"/g)||[]).every((m)=>m.split('"')[3].split(" ").every((c)=>/^(rpt-|glass-panel$|hidden$)/.test(c))))
const css=fs.readFileSync(path.join(ROOT,"UI","css","pages","reporting_export.css"),"utf8")
check("user-select has its -webkit- twin",(css.match(/[^-]user-select:/g)||[]).length===(css.match(/-webkit-user-select:/g)||[]).length)
check("css selectors are prefixed",css.split("\n").filter((l)=>/^\./.test(l)).every((l)=>l.startsWith(".rpt-x")))
check("css has no backdrop-filter without prefix",!/[^-]backdrop-filter/.test(css)||/-webkit-backdrop-filter/.test(css))
// Settings drop zone: a dropped report/template/library JSON is handed to the Reporting importer, everything else is not
const settingsSrc=fs.readFileSync(path.join(ROOT,"UI","js","pages","settings.js"),"utf8")
function settingsFn(name){
const start=settingsSrc.indexOf("\nfunction "+name+"(")
if(start<0)throw new Error("missing "+name)
const end=settingsSrc.indexOf("\nfunction ",start+1)
return settingsSrc.slice(start,end<0?undefined:end)
}
function dropHarness(kind){
const calls=[],opened=[],generic=[]
const status={textContent:"",classList:{toggle(){}}}
const env={
SET_IE_EXT_FORMATS:{json:["json","json_all"],csv:["csv"],zip:["csv_zip"],db:["db"],sqlite:["db"],ctd:["cherrytree"]},SET_IE_UPLOAD_MAX:100*1024*1024,
setIeFileExt:(name)=>{const m=/\.([a-z0-9]+)$/i.exec(String(name||""));return m?m[1].toLowerCase():""},
setIeGuessEntity:()=>"notes",
setIeReadB64:()=>Promise.resolve("e30="),
bridgeCall:(name,args)=>{calls.push([name,args]);if(name==="importExport.stage_upload")return Promise.resolve({path:"/staged/"+args[0]});return Promise.resolve({})},
window:{ReportExport:{tryStaged:(p,n)=>{calls.push(["tryStaged",[p,n]]);if(kind)opened.push(p);return Promise.resolve(!!kind)}}},
document:{getElementById:(id)=>id==="setIeDropStatus"?status:null,createElement:()=>({className:""})},
openModal:()=>{},
setRenderImportPickStep:(el,drop)=>generic.push(drop),
}
env.ReportExport=env.window.ReportExport
const names=Object.keys(env)
const mod=new Function(...names,settingsFn("setIeImportFile")+settingsFn("setIeSniffReport")+"\n;return{setIeImportFile,setIeSniffReport}")(...names.map((n)=>env[n]))
return {mod,calls,opened,generic,status}
}
async function dropTests(){
let h=dropHarness("report_json")
await h.mod.setIeImportFile({name:"Acme-Report.json",size:10})
check("drop zone: a report JSON goes to the Reporting importer",eq(h.opened,["/staged/Acme-Report.json"])&&h.generic.length===0)
h=dropHarness("")
await h.mod.setIeImportFile({name:"notes.json",size:10})
check("drop zone: any other JSON continues to the normal import dialog",h.opened.length===0&&h.generic.length===1&&h.generic[0].path==="/staged/notes.json")
h=dropHarness("report_json")
await h.mod.setIeImportFile({name:"commands.csv",size:10})
check("drop zone: CSV files are never sniffed as reports",!h.calls.some((c)=>c[0]==="tryStaged")&&h.generic.length===1)
h=dropHarness("report_json")
await h.mod.setIeImportFile({name:"bundle.zip",size:10})
check("drop zone: ZIP keeps its own sniffing",h.calls.some((c)=>c[0]==="importExport.sniff_upload")&&!h.calls.some((c)=>c[0]==="tryStaged"))
// visible wording
const js=fs.readFileSync(file,"utf8")
check("masking option is labelled as agreed",js.includes('"Mask credentials and secrets"'))
check("json warns about unmasked evidence",js.includes("contains unmasked evidence"))
check("no Playbook/Snippets wording",!/Playbook|Snippet/.test(js))
check("no localStorage/sessionStorage",!/localStorage|sessionStorage/.test(js))
}
dropTests().then(()=>{
console.log(`\nreporting_export: ${passed} passed, ${failed} failed`)
process.exit(failed?1:0)
}).catch((e)=>{console.log(e);process.exit(1)})
