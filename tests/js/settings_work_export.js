// Export my work / import it, and always-encrypted full backups: the dialog options and the password prompts. settings.js
// functions are run against a fake bridge (the same pattern as settings_backup_pin.js).
const fs=require("fs")
const path=require("path")
const ROOT=path.resolve(__dirname,"..","..")
const source=fs.readFileSync(path.join(ROOT,"UI","js","pages","settings.js"),"utf8")
const html=fs.readFileSync(path.join(ROOT,"UI","pages","settings.html"),"utf8")
function fn(name){
let start=source.indexOf("\nfunction "+name+"(")
if(start<0)throw new Error("missing "+name)
const end=source.indexOf("\nfunction ",start+1)
return source.slice(start,end<0?undefined:end)
}
function constant(name){
const start=source.indexOf("\nconst "+name+"=")
if(start<0)throw new Error("missing const "+name)
return source.slice(start,source.indexOf("\n",start+1))
}
let passed=0,failed=0
function check(name,cond,detail){if(cond){passed++;return}failed++;console.log("  FAIL  "+name+(detail?"  ->  "+detail:""))}
const tick=()=>new Promise((r)=>setTimeout(r,0))
async function settle(n){for(let i=0;i<(n||12);i++)await tick()}
function fakeRoot(vals){
return {querySelector:(sel)=>{const id=sel.replace(/^#/,"");const v=vals[id];return typeof v==="boolean"?{checked:v}:{value:v===undefined?"":v,checked:false}}}
}
function harness(state,fnNames){
const calls=[],statuses=[],prompts=[],pwPrompts=[],confirms=[]
const status={textContent:"",classList:{add:()=>{status.error=true},remove:()=>{}}}
const env={
setState:{backupSelected:new Set(["/b/x.loyabak"]),backups:[{path:"/b/x.loyabak",name:"x.loyabak"}]},
bridgeCall:(name,args)=>{calls.push([name,args])
if(name==="importExport.export_all_info")return Promise.resolve({at_rest:!!state.atRest,min_len:8,warning:"Not encrypted."})
if(name==="importExport.export_all")return Promise.resolve({name:"w.zip",counts:{notes:2,targets:1},protected:!!(args[0]&&args[0].password)})
if(name==="importExport.pick_import_all")return Promise.resolve({path:"/x/w.loyawork",name:"w.loyawork",protected:!!state.protected})
if(name==="importExport.preview_import_all"){if(state.previewError)return Promise.reject(new Error(state.previewError));return Promise.resolve(state.preview||{format:"work",counts:{notes:1}})}
if(name==="importExport.apply_import_all")return Promise.resolve({message:"Import done: 1 note added."})
if(name==="backup.password_status")return Promise.resolve(state.pwStatus||{})
if(name==="backup.needs_pin")return Promise.resolve(state.inspect||{})
if(name==="backup.create")return Promise.resolve({name:"Backup_1.loyabak"})
if(name==="backup.restore")return Promise.resolve("Restore done.")
return Promise.resolve(null)},
setPromptPin:(title,msg)=>{prompts.push([title,msg]);return Promise.resolve(state.pin===undefined?null:state.pin)},
setPromptBackupPassword:(title,msg,opts)=>{pwPrompts.push([title,msg,opts||{}]);return Promise.resolve(state.pw===undefined?null:{password:state.pw,remember:!!state.remember})},
setIeChooseImportAll:(pv)=>{env._pv=pv;return Promise.resolve(state.choice===undefined?{mode:"merge",clash:"rename",apply_settings:false}:state.choice)},
setChooseRestoreMode:()=>Promise.resolve(state.mode||"merge"),
appConfirm:(msg)=>{confirms.push(msg);return Promise.resolve(state.confirm!==false)},
setStatus:(id,msg,err)=>statuses.push([id,msg,!!err]),
showStatusIsland:()=>{},setRefreshBackups:()=>Promise.resolve(),setRefreshBackupPassword:()=>Promise.resolve(),
setEscapeHtml:(s)=>String(s==null?"":s).replace(/[&<>"]/g,(c)=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])),
}
const names=Object.keys(env)
const body=fnNames.map((n)=>n.startsWith("const ")?constant(n.slice(6)):fn(n)).join("\n")
const mod=new Function(...names,body+"\n;return{"+fnNames.filter((n)=>!n.startsWith("const ")).join(",")+"}")(...names.map((n)=>env[n]))
return {mod,calls,statuses,prompts,pwPrompts,confirms,status,env}
}
async function main(){
// ---- export options
const h=harness({},["setIeExportAllOpts","setPwStrength"])
const def=h.mod.setIeExportAllOpts(fakeRoot({setIeExpRunHistory:true,setIeExpSettings:false,setIeExpAiChats:false,setIeExpProtect:false}),8)
check("export defaults: run history on, settings and AI chats off, no password",def.include_run_history===true&&def.include_settings===false&&def.include_ai_chats===false&&def.password===null,JSON.stringify(def))
const short=h.mod.setIeExportAllOpts(fakeRoot({setIeExpRunHistory:true,setIeExpSettings:false,setIeExpAiChats:false,setIeExpProtect:true,setIeExpPw1:"abc",setIeExpPw2:"abc"}),8)
check("protected export: short password refused",/at least 8/.test(short.error||""),JSON.stringify(short))
const mism=h.mod.setIeExportAllOpts(fakeRoot({setIeExpRunHistory:true,setIeExpSettings:false,setIeExpAiChats:false,setIeExpProtect:true,setIeExpPw1:"correct horse 1",setIeExpPw2:"correct horse 2"}),8)
check("protected export: mismatch refused",/do not match/.test(mism.error||""),JSON.stringify(mism))
const good=h.mod.setIeExportAllOpts(fakeRoot({setIeExpRunHistory:false,setIeExpSettings:true,setIeExpAiChats:true,setIeExpProtect:true,setIeExpPw1:"correct horse 1",setIeExpPw2:"correct horse 1"}),8)
check("protected export: options and password passed",!good.error&&good.password==="correct horse 1"&&good.include_run_history===false&&good.include_settings===true&&good.include_ai_chats===true,JSON.stringify(good))
check("strength: weak vs strong",h.mod.setPwStrength("abc").score<h.mod.setPwStrength("Tr0ub4dor&3-horse").score&&h.mod.setPwStrength("Tr0ub4dor&3-horse").label==="Strong")
// ---- export: encryption at rest on and no password asks for the PIN; with a password it does not
const ROOT_PLAIN=fakeRoot({setIeExpRunHistory:true,setIeExpSettings:false,setIeExpAiChats:false,setIeExpProtect:false})
const e1=harness({atRest:true,pin:"1234"},["setIeExportAllOpts","setIeDoExportAll"])
e1.mod.setIeDoExportAll(ROOT_PLAIN,e1.status);await settle()
const x1=e1.calls.find((c)=>c[0]==="importExport.export_all")
check("at rest, unprotected: PIN prompt first",e1.prompts.length===1&&e1.prompts[0][0]==="Unprotected export",JSON.stringify(e1.prompts))
check("at rest, unprotected: PIN reaches export_all",x1&&x1[1][0].pin==="1234"&&x1[1][0].password===null,JSON.stringify(x1))
check("unprotected result says NOT encrypted",/NOT encrypted/.test(e1.status.textContent),e1.status.textContent)
const e2=harness({atRest:true,pin:null},["setIeExportAllOpts","setIeDoExportAll"])
e2.mod.setIeDoExportAll(ROOT_PLAIN,e2.status);await settle()
check("at rest, PIN cancelled: no export",!e2.calls.some((c)=>c[0]==="importExport.export_all")&&/Cancelled/.test(e2.status.textContent))
const e3=harness({atRest:true},["setIeExportAllOpts","setIeDoExportAll"])
e3.mod.setIeDoExportAll(fakeRoot({setIeExpRunHistory:true,setIeExpSettings:false,setIeExpAiChats:false,setIeExpProtect:true,setIeExpPw1:"correct horse 1",setIeExpPw2:"correct horse 1"}),e3.status);await settle()
const x3=e3.calls.find((c)=>c[0]==="importExport.export_all")
check("protected: no PIN prompt, password sent",e3.prompts.length===0&&x3&&x3[1][0].password==="correct horse 1",JSON.stringify([e3.prompts,x3]))
check("protected result says password protected",/password protected/.test(e3.status.textContent),e3.status.textContent)
// ---- import: protected file asks the password, preview, then apply with the chosen options
const i1=harness({protected:true,pw:"correct horse 1",choice:{mode:"merge",clash:"skip",apply_settings:true}},["setIeDoImportAll"])
i1.mod.setIeDoImportAll(null,i1.status);await settle(16)
const pv=i1.calls.find((c)=>c[0]==="importExport.preview_import_all"),ap=i1.calls.find((c)=>c[0]==="importExport.apply_import_all")
check("import protected: password prompt",i1.pwPrompts.length===1&&/protected with a password/.test(i1.pwPrompts[0][1]),JSON.stringify(i1.pwPrompts))
check("import: preview gets the password",pv&&pv[1][1]==="correct horse 1",JSON.stringify(pv))
check("import: apply gets mode, clash, apply_settings and password",ap&&ap[1][1].mode==="merge"&&ap[1][1].clash==="skip"&&ap[1][1].apply_settings===true&&ap[1][1].password==="correct horse 1",JSON.stringify(ap))
check("import: result message shown",/Import done/.test(i1.status.textContent))
const i2=harness({protected:false},["setIeDoImportAll"])
i2.mod.setIeDoImportAll(null,i2.status);await settle(16)
check("import plain: no password prompt",i2.pwPrompts.length===0&&i2.calls.some((c)=>c[0]==="importExport.apply_import_all"))
const i3=harness({protected:false,choice:{mode:"replace",clash:"rename",apply_settings:false},confirm:false},["setIeDoImportAll"])
i3.mod.setIeDoImportAll(null,i3.status);await settle(16)
check("import replace: confirm first, decline cancels",i3.confirms.length===1&&!i3.calls.some((c)=>c[0]==="importExport.apply_import_all"),JSON.stringify(i3.confirms))
const i4=harness({protected:true,pw:"bad pass word",previewError:"Wrong password."},["setIeDoImportAll"])
i4.mod.setIeDoImportAll(null,i4.status);await settle(16)
check("import wrong password: error shown, nothing applied",i4.status.error&&/Wrong password/.test(i4.status.textContent)&&!i4.calls.some((c)=>c[0]==="importExport.apply_import_all"))
// ---- preview: clash choice only when there are clashes; Apply settings only when settings are in the file
const p=harness({},["const SET_IE_KIND_LABELS","setIeImportPreviewHtml"])
const plain=p.mod.setIeImportPreviewHtml({format:"work",counts:{notes:3},clashes:{}})
check("preview: counts row",/Notes<\/td><td>3/.test(plain))
check("preview: no clash choice and no apply settings without them",!/setIeImpClash/.test(plain)&&!/setIeImpApplySettings/.test(plain))
const rich=p.mod.setIeImportPreviewHtml({format:"legacy",counts:{notes:3,chains:1},clashes:{notes:["A"]},has_settings:true,ignored:["Data/settings.json"]})
check("preview: clash rename/skip choice",/name="setIeImpClash" value="rename" checked/.test(rich)&&/value="skip"/.test(rich))
check("preview: apply settings checkbox, off by default",/id="setIeImpApplySettings">/.test(rich)&&!/setIeImpApplySettings" checked/.test(rich))
check("preview: legacy note and ignored files",/Old full-data export/.test(rich)&&/Ignored 1/.test(rich))
check("preview: merge and replace modes",/value="merge" checked/.test(rich)&&/value="replace"/.test(rich))
// ---- backup now: always encrypted
const b1=harness({pwStatus:{at_rest:false,remembered:false,keyring:true,min_len:10},pw:"long backup pass",remember:true},["setDoBackupNow"])
b1.mod.setDoBackupNow();await settle()
const c1=b1.calls.find((c)=>c[0]==="backup.create")
check("backup: asks a password with confirm, min length and remember",b1.pwPrompts.length===1&&b1.pwPrompts[0][2].needConfirm===true&&b1.pwPrompts[0][2].minLen===10&&b1.pwPrompts[0][2].remember===true,JSON.stringify(b1.pwPrompts))
check("backup: password and remember reach backup.create",c1&&c1[1][0]==="long backup pass"&&c1[1][1]===true,JSON.stringify(c1))
const b2=harness({pwStatus:{at_rest:true}},["setDoBackupNow"])
b2.mod.setDoBackupNow();await settle()
check("backup with encryption at rest: no password prompt",b2.pwPrompts.length===0&&b2.calls.some((c)=>c[0]==="backup.create"))
const b3=harness({pwStatus:{remembered:true}},["setDoBackupNow"])
b3.mod.setDoBackupNow();await settle()
check("backup with a remembered password: no prompt",b3.pwPrompts.length===0&&b3.calls.some((c)=>c[0]==="backup.create"))
const b4=harness({pwStatus:{}},["setDoBackupNow"])
b4.mod.setDoBackupNow();await settle()
check("backup: cancelled password, no backup",!b4.calls.some((c)=>c[0]==="backup.create")&&b4.statuses.some((s)=>/cancelled/i.test(s[1])))
// ---- restore: password backups ask the password; old plain zips warn
const r1=harness({inspect:{encrypted:true,protect:"password",needs_password:true},pw:"long backup pass"},["const SET_BACKUP_PIN_WARNING","const SET_BACKUP_PLAIN_WARNING","setBackupPin","setDoRestoreSelected"])
r1.mod.setDoRestoreSelected();await settle()
const rr1=r1.calls.find((c)=>c[0]==="backup.restore")
check("restore password backup: password prompt, no PIN prompt",r1.pwPrompts.length===1&&r1.prompts.length===0,JSON.stringify([r1.pwPrompts,r1.prompts]))
check("restore password backup: password reaches backup.restore",rr1&&rr1[1][4]==="long backup pass",JSON.stringify(rr1))
const r2=harness({inspect:{encrypted:true,protect:"password",needs_password:true}},["const SET_BACKUP_PIN_WARNING","const SET_BACKUP_PLAIN_WARNING","setBackupPin","setDoRestoreSelected"])
r2.mod.setDoRestoreSelected();await settle()
check("restore: cancelled password, nothing restored",!r2.calls.some((c)=>c[0]==="backup.restore"))
const r3=harness({inspect:{encrypted:false,protect:"none",legacy_plain:true}},["const SET_BACKUP_PIN_WARNING","const SET_BACKUP_PLAIN_WARNING","setBackupPin","setDoRestoreSelected"])
r3.mod.setDoRestoreSelected();await settle()
check("restore old plain zip: not-encrypted warning",r3.confirms.length===1&&/not encrypted/.test(r3.confirms[0])&&r3.calls.some((c)=>c[0]==="backup.restore"),JSON.stringify(r3.confirms))
const r4=harness({inspect:{encrypted:false,protect:"none",legacy_plain:true},confirm:false},["const SET_BACKUP_PIN_WARNING","const SET_BACKUP_PLAIN_WARNING","setBackupPin","setDoRestoreSelected"])
r4.mod.setDoRestoreSelected();await settle()
check("restore old plain zip: declined, nothing restored",!r4.calls.some((c)=>c[0]==="backup.restore"))
check("restore with nothing selected picks from the Backup card's own picker",/bridgeCall\("backup\.pick_restore"\)/.test(fn("setDoRestoreSelected")))
// ---- password prompt and wording
const pp=source.slice(source.indexOf("\nfunction setPromptBackupPassword("),source.indexOf("\nfunction setDoBackupNow("))
check("password prompt: Enter clicks OK, Escape cancels",/e\.key==="Enter"[^}]*#setBkPwOk"\)\.click\(\)/.test(pp)&&/e\.key==="Escape"[^}]*finish\(null\)/.test(pp))
check("password prompt: confirm, min length, strength hint, remember",/setBkPwInput2/.test(pp)&&/minLen/.test(pp)&&/Strength: /.test(pp)&&/Remember for automatic backups/.test(pp))
check("wording: Export my work in the data type list",/Export my work \(notes, targets, reports, diagrams\.\.\.\)/.test(source))
check("wording: Full backup of this install",/Full backup of this install/.test(html))
check("export dialog checkboxes",["setIeExpRunHistory\" checked","setIeExpSettings\">","setIeExpAiChats\">","Protect the export with a password"].every((s)=>source.includes(s)))
check("no ellipsis, em or en dash characters in settings UI",!/[…—–·]/.test(source)&&!/[…—–·]/.test(html))
check("auto backup notice element",/id="setBkAutoNotice"/.test(html)&&/Automatic backups are skipped until a backup password is set/.test(source))
console.log("")
console.log(passed+" passed, "+failed+" failed")
process.exit(failed?1:0)
}
main()
