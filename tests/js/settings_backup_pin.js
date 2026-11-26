// Storage rebuild: restoring an encrypted .loyabak made under another PIN asks for that PIN; a plain DB export with encryption
// at rest on asks for the PIN behind an explicit "not encrypted" warning. settings.js functions are run against a fake bridge.
const fs=require("fs")
const path=require("path")
const ROOT=path.resolve(__dirname,"..","..")
const source=fs.readFileSync(path.join(ROOT,"UI","js","pages","settings.js"),"utf8")
function fn(name){
const start=source.indexOf("\nfunction "+name+"(")
if(start<0)throw new Error("missing "+name)
const end=source.indexOf("\nfunction ",start+1)
return source.slice(start,end<0?undefined:end)
}
let passed=0,failed=0
function check(name,cond,detail){if(cond){passed++;return}failed++;console.log("  FAIL  "+name+(detail?"  ->  "+detail:""))}
const tick=()=>new Promise((r)=>setTimeout(r,0))
function harness(state){
const calls=[],statuses=[],prompts=[],confirms=[]
const env={
setState:{backupSelected:new Set(["/b/x.loyabak"]),backups:[{path:"/b/x.loyabak",name:"x.loyabak"}]},
bridgeCall:(name,args)=>{calls.push([name,args]);
if(name==="backup.needs_pin"||name==="importExport.import_needs_pin")return Promise.resolve({encrypted:true,protect:"pin",needs_pin:!!state.needsPin})
if(name==="backup.restore"){if(state.restoreError)return Promise.reject(new Error(state.restoreError));return Promise.resolve("Restore done.")}
return Promise.resolve(null)},
setChooseRestoreMode:()=>Promise.resolve(state.mode||"replace"),
setPromptPin:(title,msg,_c,skip)=>{prompts.push([title,msg,skip]);const v=title==="Backup PIN"?state.pin:state.cur;return Promise.resolve(v===undefined?null:v)},
appConfirm:(msg)=>{confirms.push(msg);return Promise.resolve(!!state.confirm)},
setPromptBackupPassword:()=>Promise.resolve(null),SET_BACKUP_PLAIN_WARNING:"plain",
SET_BACKUP_PIN_WARNING:"This backup uses the PIN that was set when it was made. After restore, unlock with that PIN.",
setStatus:(id,msg,err)=>statuses.push([id,msg,!!err]),
}
const names=Object.keys(env)
const mod=new Function(...names,fn("setBackupPin")+fn("setDoRestoreSelected")+";return{setDoRestoreSelected}")(...names.map((n)=>env[n]))
return {mod,calls,statuses,prompts,confirms}
}
async function main(){
// Own backup (same data key): restore still asks for the PIN first (one prompt, no current-PIN step) and passes it through.
const a=harness({needsPin:false,pin:"own-pin-1234"})
a.mod.setDoRestoreSelected();for(let i=0;i<6;i++)await tick()
const ra=a.calls.find((c)=>c[0]==="backup.restore")
check("own backup: one PIN prompt",a.prompts.length===1&&a.prompts[0][0]==="Backup PIN",JSON.stringify(a.prompts))
check("own backup: restore gets the typed PIN",ra&&ra[1][0]==="/b/x.loyabak"&&ra[1][1]==="replace"&&ra[1][2]==="own-pin-1234"&&ra[1][3]===null,JSON.stringify(ra))
// Backup from another PIN: prompt, and the typed PIN is passed through; replace then asks for the current PIN to keep it.
const b=harness({needsPin:true,pin:"old-pin-4821",cur:"cur-pin-7310"})
b.mod.setDoRestoreSelected();for(let i=0;i<8;i++)await tick()
const rb=b.calls.find((c)=>c[0]==="backup.restore")
check("other PIN: backup PIN then current PIN",b.prompts.length===2&&/different PIN/.test(b.prompts[0][1])&&b.prompts[1][0]==="Keep your current PIN"&&b.prompts[1][2]==="Skip",JSON.stringify(b.prompts))
check("other PIN: both PINs reach backup.restore",rb&&rb[1][2]==="old-pin-4821"&&rb[1][3]==="cur-pin-7310",JSON.stringify(rb))
check("other PIN with current PIN: no warning",b.confirms.length===0)
// Skip the current PIN: the warning is shown; confirming restores with the backup's PIN, declining cancels.
const s1=harness({needsPin:true,pin:"old",cur:"",confirm:true})
s1.mod.setDoRestoreSelected();for(let i=0;i<10;i++)await tick()
const rs=s1.calls.find((c)=>c[0]==="backup.restore")
check("skip: warning shown",s1.confirms.length===1&&/unlock with that PIN/.test(s1.confirms[0]),JSON.stringify(s1.confirms))
check("skip + confirm: restore without current PIN",rs&&rs[1][2]==="old"&&rs[1][3]===null,JSON.stringify(rs))
const s2=harness({needsPin:true,pin:"old",cur:"",confirm:false})
s2.mod.setDoRestoreSelected();for(let i=0;i<10;i++)await tick()
check("skip + decline: no restore",!s2.calls.some((x)=>x[0]==="backup.restore")&&s2.statuses.some((x)=>/cancelled/i.test(x[1])))
// Merge never replaces the key file: no current-PIN prompt.
const m=harness({needsPin:true,pin:"old",mode:"merge"})
m.mod.setDoRestoreSelected();for(let i=0;i<8;i++)await tick()
const rm=m.calls.find((c)=>c[0]==="backup.restore")
check("merge: only the backup PIN",m.prompts.length===1&&rm&&rm[1][3]===null,JSON.stringify([m.prompts,rm]))
// Cancel the PIN prompt: nothing is restored.
const c=harness({needsPin:true})
c.mod.setDoRestoreSelected();for(let i=0;i<6;i++)await tick()
check("cancel: no restore call",!c.calls.some((x)=>x[0]==="backup.restore"),JSON.stringify(c.calls))
check("cancel: status says cancelled",c.statuses.some((s)=>/cancelled/i.test(s[1])),JSON.stringify(c.statuses))
// Wrong PIN: the service error is shown as an error.
const d=harness({needsPin:true,pin:"nope",cur:"cur",restoreError:"Restore failed: Wrong PIN for this backup."})
d.mod.setDoRestoreSelected();for(let i=0;i<8;i++)await tick()
check("wrong PIN: clear error shown",d.statuses.some((s)=>s[2]&&/Wrong PIN/.test(s[1])),JSON.stringify(d.statuses))
// Static checks on the other two call sites.
check("import-all goes through the work import preview, not a backup restore",/importExport\.preview_import_all/.test(source)&&/apply_import_all",\[src\.path,opts\]/.test(source))
check("plain export asks first and warns",/importExport\.export_needs_pin/.test(source)&&/setPromptPin\("Unencrypted export"/.test(source)&&/NOT encrypted/.test(source))
// PIN prompt keyboard: Enter submits through the OK handler (so the mismatch check runs), Escape cancels.
const pp=source.slice(source.indexOf("\nfunction setPromptPin("),source.indexOf("\nfunction setLoadSecurity("))
check("PIN prompt: Enter clicks OK",/e\.key==="Enter"[^}]*#setPinOk"\)\.click\(\)/.test(pp),pp.slice(0,120))
check("PIN prompt: Escape cancels",/e\.key==="Escape"[^}]*finish\(null\)/.test(pp))
console.log("")
console.log(passed+" passed, "+failed+" failed")
process.exit(failed?1:0)
}
main()
