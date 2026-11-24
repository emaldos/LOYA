// Targets page: the pure helpers behind the Add/Edit Target form and the table (secret keys, hints, warnings, filter, dirty state).
const fs=require("fs")
const path=require("path")
const src=fs.readFileSync(path.join(__dirname,"..","..","UI","js","pages","targets.js"),"utf8")
function slice(from,to){const a=src.indexOf(from),b=src.indexOf(to,a);if(a<0||b<0)throw new Error("could not slice "+from);return src.slice(a,b)}
const T=new Function(slice("// ---- Pure helpers","// ---- end pure helpers")+slice("function tgtFieldMatches","function tgtFilterFormFields")+
";return{tgtIsSecretKey,tgtKeyKind,tgtValueHint,tgtValueWarning,tgtOrderFormKeys,tgtFormFieldVisible,tgtFormIsDirty,tgtTargetHint,tgtCountLabel}")()
let passed=0,failed=0
function check(name,ok,detail){if(ok)passed++;else{failed++;console.log("FAIL: "+name+(detail?" - "+detail:""))}}
// Secret detection matches the title-bar badge.
const badge=require("../../UI/js/components/live-target-badge.js")
for(const k of ["Password","api_key","NTLM_Hash","Session_Cookie","Token","Private_Key","OTP","client_secret","creds"])check("secret: "+k,T.tgtIsSecretKey(k)&&badge.liveBadgeIsSecret(k))
for(const k of ["IPv4","Domain","URL","Port","Username","Wordlist","DC_IP"])check("not secret: "+k,!T.tgtIsSecretKey(k)&&!badge.liveBadgeIsSecret(k))
// Kinds and hints.
check("kind: IPv4/DC_IP/RHOST are ip",["IPv4","DC_IP","RHOST","ip"].every((k)=>T.tgtKeyKind(k)==="ip"))
check("kind: Port/LPORT are port",T.tgtKeyKind("Port")==="port"&&T.tgtKeyKind("LPORT")==="port")
check("kind: URL and Domain",T.tgtKeyKind("URL")==="url"&&T.tgtKeyKind("Domain")==="domain")
check("kind: IPv6 is not ipv4",T.tgtKeyKind("IPv6")==="ipv6")
check("hint: unknown key names the key",T.tgtValueHint("Foo")==="Value for {Foo}")
check("hint: ip key shows an example",/10\.10\.10\.5/.test(T.tgtValueHint("IPv4")))
// Warnings never fire on empty values and accept lists/CIDR.
check("warn: empty value is fine",T.tgtValueWarning("IPv4","")==="")
check("warn: valid ip, cidr and list",T.tgtValueWarning("IPv4","10.0.0.5")===""&&T.tgtValueWarning("IPv4","10.0.0.0/24")===""&&T.tgtValueWarning("RHOST","10.0.0.1, 10.0.0.2")==="")
check("warn: bad ip",T.tgtValueWarning("IPv4","10.0.300.1")!==""&&T.tgtValueWarning("DC_IP","10.0.0")!=="")
check("warn: ports",T.tgtValueWarning("Port","443")===""&&T.tgtValueWarning("Port","80,8000-8100")===""&&T.tgtValueWarning("Port","70000")!==""&&T.tgtValueWarning("Port","http")!=="")
check("warn: url scheme",T.tgtValueWarning("URL","https://a.b")===""&&T.tgtValueWarning("URL","a.b/x")!=="")
check("warn: other keys never warn",T.tgtValueWarning("Username","anything at all")==="")
// Filled values first, priority order kept inside each group.
check("order: filled first",T.tgtOrderFormKeys(["IPv4","Hash","URL","Port"],{URL:"x",Port:"  ",Hash:"h"}).join()==="Hash,URL,IPv4,Port")
check("order: no values keeps priority order",T.tgtOrderFormKeys(["a","b"],null).join()==="a,b")
// Field filter: key tokens plus the "only filled" toggle.
check("filter: token match",T.tgtFormFieldVisible("DC_IP","","dc",false)&&!T.tgtFormFieldVisible("URL","","dc",false))
check("filter: only filled hides empties",!T.tgtFormFieldVisible("URL"," ","",true)&&T.tgtFormFieldVisible("URL","x","",true))
check("filter: both rules apply",!T.tgtFormFieldVisible("URL","x","ip",true))
// Dirty state ignores whitespace and empty values, catches real edits.
const base={name:"web01",engagement:"in_progress",values:{IPv4:"10.0.0.5"}}
check("dirty: same data",!T.tgtFormIsDirty(base,{name:" web01 ",engagement:"in_progress",values:{IPv4:"10.0.0.5 ",URL:""}}))
check("dirty: value changed",T.tgtFormIsDirty(base,{name:"web01",engagement:"in_progress",values:{IPv4:"10.0.0.6"}}))
check("dirty: value added",T.tgtFormIsDirty(base,{name:"web01",engagement:"in_progress",values:{IPv4:"10.0.0.5",Port:"80"}}))
check("dirty: name and engagement",T.tgtFormIsDirty(base,{...base,name:"web02"})&&T.tgtFormIsDirty(base,{...base,engagement:"reported"}))
check("dirty: key order does not matter",!T.tgtFormIsDirty({name:"a",values:{x:"1",y:"2"}},{name:"a",values:{y:"2",x:"1"}}))
// Table hint: host-like value by priority, never a secret.
const hint=T.tgtTargetHint({values:{Password:"p",Domain:"corp.local",IPv4:"10.0.0.5"}},["Password","IPv4","Domain"])
check("hint: first host-like key by priority",hint.key==="IPv4"&&hint.text==="10.0.0.5"&&hint.count==="3 values")
check("hint: secrets are never shown",T.tgtTargetHint({values:{Password:"p"}},["Password"]).key===""&&T.tgtTargetHint({values:{Password:"p"}},["Password"]).text==="1 value")
check("hint: empty target",T.tgtTargetHint({values:{}},[]).text==="0 values")
check("hint: falls back to the first plain value",T.tgtTargetHint({values:{Username:"bob"}},["Username"]).key==="Username")
// Counts.
check("count: all shown",T.tgtCountLabel(4,4,"target")==="4 targets"&&T.tgtCountLabel(1,1,"element")==="1 element")
check("count: filtered",T.tgtCountLabel(1,4,"target")==="1 of 4")
check("form: the dialog itself is focusable so Ctrl+S works after clicking a label or blank area",/pop\.className="tgt-popover tgt-form glass-panel"\npop\.tabIndex=-1/.test(src)&&src.includes('pop.addEventListener("keydown",(e)=>tgtFormKeydown(pop,e))'))
check("elements: delete of a linked element counts places, not only commands (note blocks count too)",src.includes('is used in ${k.links} place${k.links===1?"":"s"} (commands and note blocks)')&&!src.includes('is used in ${k.links} command')&&src.includes('`Used in ${links} place${links===1?"":"s"}`'))
console.log(passed+" passed, "+failed+" failed")
process.exit(failed?1:0)
