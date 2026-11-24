// Action chain callers and pre-run checks (UI/js/components/action-chains.js) - pure helpers only.
const fs=require("fs")
const path=require("path")
const vm=require("vm")
const ROOT=path.resolve(__dirname,"..","..")
const snippets=fs.readFileSync(path.join(ROOT,"UI","js","pages","snippets.js"),"utf8")
const chains=fs.readFileSync(path.join(ROOT,"UI","js","components","action-chains.js"),"utf8")
const terminal=fs.readFileSync(path.join(ROOT,"UI","js","components","terminal.js"),"utf8")
const sandbox={module:{exports:{}},document:{addEventListener(){}},setTimeout(){},console}
vm.createContext(sandbox)
vm.runInContext(snippets.slice(snippets.indexOf("function snipIterPlaceholders"),snippets.indexOf("function snipResolveCommand")),sandbox)
vm.runInContext(chains,sandbox)
const ac=sandbox.module.exports
let passed=0,failed=0
function check(name,cond,detail){if(cond){passed++;return}failed++;console.log("  FAIL  "+name+(detail?"  ->  "+detail:""))}
function eq(name,a,b){check(name,JSON.stringify(a)===JSON.stringify(b),JSON.stringify(a)+" != "+JSON.stringify(b))}
const callers=[{id:1,caller:"recon",name:"Recon basics",steps:3},{id:2,caller:"web-quick",name:"DEMO External web quick wins",steps:3},{id:3,caller:"recon-full",name:"Full recon",steps:7}]
// "/" trigger rules
check("trigger: / at position 0",ac.acIsSlashTrigger("/")&&ac.acIsSlashTrigger("/rec"))
check("trigger: not with a leading space",!ac.acIsSlashTrigger(" /rec"))
check("trigger: not once the line has a space",!ac.acIsSlashTrigger("/recon now")&&!ac.acIsSlashTrigger("ls /usr"))
check("trigger: not mid-line",!ac.acIsSlashTrigger("cat /etc/passwd"))
// suggestions
eq("match: bare / lists all, shortest prefix first",ac.acMatchCallers(callers,"/").map((c)=>c.caller),["recon","web-quick","recon-full"])
eq("match: prefix",ac.acMatchCallers(callers,"/rec").map((c)=>c.caller),["recon","recon-full"])
eq("match: by name after prefix hits",ac.acMatchCallers(callers,"/demo").map((c)=>c.caller),["web-quick"])
eq("match: paths never match",ac.acMatchCallers(callers,"/usr/bin/id"),[])
eq("match: case-insensitive query",ac.acMatchCallers(callers,"/REC").map((c)=>c.caller),["recon","recon-full"])
// Enter: only an exact caller is intercepted
eq("exact: /recon",ac.acExactCaller(callers,"/recon").id,1)
eq("exact: trailing blanks ok",ac.acExactCaller(callers,"/recon  ").id,1)
eq("exact: prefix is not enough",ac.acExactCaller(callers,"/reco"),null)
eq("exact: absolute command goes to the shell",ac.acExactCaller(callers,"/usr/bin/id"),null)
eq("exact: arguments go to the shell",ac.acExactCaller(callers,"/recon -v"),null)
eq("exact: leading space goes to the shell",ac.acExactCaller(callers," /recon"),null)
eq("exact: case must match",ac.acExactCaller(callers,"/Recon"),null)
// caller validation
eq("validate: ok",ac.acCallerError("new-one",callers,null),"")
check("validate: reserved",/built-in/.test(ac.acCallerError("help",callers,null))&&/built-in/.test(ac.acCallerError("/summarize-note",callers,null)))
check("validate: duplicate",/already used/.test(ac.acCallerError("recon",callers,null)))
eq("validate: own caller is not a clash",ac.acCallerError("recon",callers,1),"")
check("validate: bad chars and length",/only use/.test(ac.acCallerError("a b",[],null))&&/at most/.test(ac.acCallerError("x".repeat(33),[],null))&&/required/.test(ac.acCallerError("",[],null)))
eq("validate: uppercase is normalized",ac.acCallerError("WebScan",[],null),"")
eq("slugify",ac.acSlugifyCaller("DEMO External web quick wins!"),"demo-external-web-quick-wins")
eq("slugify: accents and trim",ac.acSlugifyCaller("  Énum  SMB / LDAP "),"enum-smb-ldap")
check("slugify: max 32",ac.acSlugifyCaller("a".repeat(50)).length===32)
const aiSource=fs.readFileSync(path.join(ROOT,"UI","js","components","ai.js"),"utf8")
const aiList=aiSource.slice(aiSource.indexOf("const AI_SLASH_COMMANDS"),aiSource.indexOf("\n]",aiSource.indexOf("const AI_SLASH_COMMANDS")))
const aiNames=[...aiList.matchAll(/name:"([^"]+)"/g)].map((m)=>m[1])
eq("reserved list matches the AI panel's built-in commands",ac.AC_RESERVED_CALLERS.slice().sort(),aiNames.slice().sort())
// missing elements per step and the stop step
const steps=[{label:"id",command:"id"},{label:"wait",command:"sleep 3; echo ok"},{label:"web",command:"curl http://{IPv4}:{Port}/ ${HOME}"},{label:"user",command:"echo {Username} {ipv4}"}]
const values={IPv4:"10.0.0.5",Port:"",Domain:"corp.local"}
eq("missing: grouped per step, empty value counts as missing, ${VAR} ignored",ac.acMissingByStep(steps,values).map((r)=>[r.index,r.missing]),[[2,["Port"]],[3,["Username"]]])
eq("missing: first blocked step",ac.acFirstBlockedStep(steps,values),2)
eq("missing: none when all filled",ac.acFirstBlockedStep(steps,{IPv4:"1",Port:"80",Username:"bob"}),-1)
eq("missing: keys are case-insensitive",ac.acMissingByStep([{command:"x {USERNAME}"}],{username:"a"}),[])
eq("missing: duplicate keys reported once",ac.acMissingByStep([{command:"{A} {a} {A}"}],{})[0].missing,["A"])
eq("resolve: fills known keys, keeps unknown and ${VAR}",ac.acResolveCommand("curl {IPv4}:{Port} ${IPv4}",values),"curl 10.0.0.5:{Port} ${IPv4}")
const items=ac.acBuildChainItems(steps,values,2)
eq("items: steps before the stop run",items.slice(0,2).map((i)=>i.skip_reason||""),["",""])
eq("items: the stop step says what is missing",items[2].skip_reason,"Missing {Port}")
check("items: later steps say where it stopped and their own gaps",/^Stopped before step 3/.test(items[3].skip_reason)&&/\{Username\}/.test(items[3].skip_reason))
eq("items: no stop means no skip reasons",ac.acBuildChainItems(steps,values,-1).filter((i)=>i.skip_reason).length,0)
eq("items: commands are resolved",items[3].command,"echo {Username} 10.0.0.5")
// progress model
const sum=ac.acRunSummary({steps:[{state:"done"},{state:"running"},{state:"pending"},{state:"skipped"}]})
eq("summary: running",[sum.total,sum.settled,sum.running,sum.active,sum.percent,sum.state],[4,2,1,true,50,"running"])
eq("summary: stopped",ac.acRunSummary({steps:[{state:"done"},{state:"skipped"}]}).state,"stopped")
eq("summary: failed",ac.acRunSummary({steps:[{state:"done"},{state:"failed"},{state:"skipped"}]}).state,"failed")
check("time: microsecond ISO parses",!isNaN(ac.acParseTime("2026-11-23T10:00:00.123456+00:00")))
eq("duration format",[ac.acFormatDuration(4200),ac.acFormatDuration(65000),ac.acFormatDuration(3725000)],["4s","1m 05s","1h 02m"])
// terminal wiring
check("terminal: Enter checks for an exact caller before sending",/acTerminalExactCaller\(input\.value\)[\s\S]{0,200}loyaRunChainByCaller[\s\S]{0,90}termSendLine\(\)/.test(terminal))
check("terminal: chain suggestions only when / starts the line",/acTerminalSlashActive\(input\.value,input\.selectionEnd\)/.test(terminal))
check("terminal: accepting a chain suggestion runs it",/entry\.chainCaller&&typeof loyaRunChainByCaller==="function"/.test(terminal))
const html=fs.readFileSync(path.join(ROOT,"UI","windows","main.html"),"utf8")
check("main.html loads action-chains.js after terminal.js and before ai.js",html.indexOf("components/terminal.js")<html.indexOf("components/action-chains.js")&&html.indexOf("components/action-chains.js")<html.indexOf("components/ai.js"))
check("public API exists",/function loyaChainCallers\(\)/.test(chains)&&/function loyaRunChainByCaller\(caller,opts\)/.test(chains))
console.log("")
console.log(passed+" passed, "+failed+" failed")
process.exit(failed?1:0)
