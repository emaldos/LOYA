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
function harness(state){
const calls=[],statuses=[],confirms=[]
const els={setTagNew:{value:state.newTag||""},setTagLinked:{checked:!!state.linked}}
const env={
setState:{tagSelected:new Set(state.tags||[]),rb:state.rb||[],rbSearch:"",rbSelected:new Set(),tags:[]},
document:{getElementById:(id)=>els[id]||{value:"",checked:false}},
bridgeCall:(name,args)=>{calls.push([name,args]);return Promise.resolve(state.reply?state.reply(name,args):{commands_notes:0,linked:0,notes:0,note_tags:0})},
appConfirm:(msg)=>{confirms.push(msg);return Promise.resolve(state.confirm)},
setStatus:(id,msg,err)=>statuses.push([id,msg,!!err]),
setRefreshTags:()=>Promise.resolve(),
setRefreshRb:()=>Promise.resolve(),
RB_TYPE_LABELS:{},
}
const names=Object.keys(env)
const mod=new Function(...names,fn("setTagCheck")+fn("setTagApply")+fn("setIeResultText")+fn("setFilteredRb")+fn("setRbReport")+fn("setDoPurgeNow")+";return{setTagCheck,setTagApply,setIeResultText,setDoPurgeNow}")(...names.map((n)=>env[n]))
return {mod,calls,statuses,confirms,env}
}
const tick=()=>new Promise((r)=>setTimeout(r,0))
async function main(){
const h0=harness({})
check("tag check: none selected",h0.mod.setTagCheck("delete",[],"")!=="")
check("tag check: rename needs exactly one",h0.mod.setTagCheck("rename",["a","b"],"c").includes("exactly one"))
check("tag check: merge needs two",h0.mod.setTagCheck("merge",["a"],"c").includes("two or more"))
check("tag check: rename needs a name",h0.mod.setTagCheck("rename",["a"],"").includes("new tag"))
check("tag check: same name",h0.mod.setTagCheck("rename",["Web"],"web")!=="")
check("tag check: ok",h0.mod.setTagCheck("merge",["a","b"],"c")===""&&h0.mod.setTagCheck("delete",["a"],"")==="")
// S1: cancel must not call the bridge
const h1=harness({tags:["web"],newTag:"http",confirm:false})
h1.mod.setTagApply("rename");await tick();await tick()
check("tag apply: cancel makes no bridge call",h1.calls.length===0,JSON.stringify(h1.calls))
check("tag apply: confirm shown",h1.confirms.length===1)
const h2=harness({tags:["web"],newTag:"http",confirm:true,linked:true})
h2.mod.setTagApply("rename");await tick();await tick()
check("tag apply: confirm calls rename once",h2.calls.length===1&&h2.calls[0][0]==="tags.rename"&&JSON.stringify(h2.calls[0][1])==='[["web"],"http",true]',JSON.stringify(h2.calls))
const h3=harness({tags:["a"],newTag:"b",confirm:true})
h3.mod.setTagApply("merge");await tick()
check("tag apply: invalid merge stops before confirm",h3.confirms.length===0&&h3.calls.length===0&&h3.statuses[0][2])
// S10/S4 result text
const txt=h0.mod.setIeResultText({added:2,replaced:1,overwritten:0,skipped:3,bad:1,invalid:4})
check("ie result shows failed and invalid",txt.includes("Failed:1")&&txt.includes("ignored:4"),txt)
check("ie result hides invalid when zero",!h0.mod.setIeResultText({added:1}).includes("ignored"))
// Purge All uses the unfiltered list and purge_all
const h4=harness({confirm:true,rb:[{id:1,label:"x"}],reply:(n)=>n==="recycleBin.list"?[{id:1},{id:2},{id:3}]:3})
h4.mod.setDoPurgeNow();await tick();await tick();await tick()
check("purge: lists unfiltered",h4.calls[0][0]==="recycleBin.list"&&JSON.stringify(h4.calls[0][1])==='[""]')
check("purge: prompt counts all and hidden",h4.confirms[0]&&h4.confirms[0].includes("ALL 3")&&h4.confirms[0].includes("2 not shown"),h4.confirms[0])
check("purge: calls purge_all",h4.calls.some((c)=>c[0]==="recycleBin.purge_all"))
check("settings.js: no parallel restore",!/Promise\.all\(ids\.map\(\(id\)=>bridgeCall\("recycleBin\.restore"/.test(source))
check("settings.js: channel select is read",source.includes('getElementById("setUpChannel")'))
console.log("")
console.log(passed+" passed, "+failed+" failed")
process.exit(failed?1:0)
}
main()
