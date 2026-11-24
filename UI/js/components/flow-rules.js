// Chain diagrams: the no-code rule model behind decision nodes (describe / validate / evaluate) plus the small pure text
// helpers shared by flow-inspector.js and flow-run.js. No DOM in this file; tests/js/flow_rules.js loads it in plain node.
// The Python side (Cores/Services/flow_rules.py) is the one that decides at run time. This file mirrors its sentences
// and its evaluation rules so the builder's live preview and the "Test against sample output" box say the same thing.
const FLOW_BRANCH_RE=/^[A-Za-z0-9_-]{1,24}$/
const FLOW_RULE_LIMITS={branches:12,conditions:12,regex:500,text:262144,matches:100000,groups:40}
const FLOW_RULE_TEXT_OPS=["contains","not_contains","equals","not_equals","starts_with","ends_with","regex","not_regex","is_empty","not_empty"]
const FLOW_RULE_NUM_OPS=["eq","ne","gt","ge","lt","le"]
const FLOW_RULE_BOOL_OPS=["is_true","is_false"]
// label: the builder's operator select. phrase: the sentence (same words as flow_rules._OP_LABELS).
// kind: text (string compare), regex, num (numeric compare), empty, bool. value: the op reads cond.value.
const FLOW_RULE_OPS={
contains:{label:"contains",phrase:"contains",kind:"text",value:true},
not_contains:{label:"does not contain",phrase:"does not contain",kind:"text",value:true},
equals:{label:"is exactly",phrase:"is",kind:"text",value:true},
not_equals:{label:"is not",phrase:"is not",kind:"text",value:true},
starts_with:{label:"starts with",phrase:"starts with",kind:"text",value:true},
ends_with:{label:"ends with",phrase:"ends with",kind:"text",value:true},
regex:{label:"matches regex",phrase:"matches",kind:"regex",value:true},
not_regex:{label:"does not match regex",phrase:"does not match",kind:"regex",value:true},
eq:{label:"=",phrase:"=",kind:"num",value:true},
ne:{label:"!=",phrase:"!=",kind:"num",value:true},
gt:{label:">",phrase:">",kind:"num",value:true},
ge:{label:">=",phrase:">=",kind:"num",value:true},
lt:{label:"<",phrase:"<",kind:"num",value:true},
le:{label:"<=",phrase:"<=",kind:"num",value:true},
is_empty:{label:"is empty",phrase:"is empty",kind:"empty",value:false},
not_empty:{label:"is not empty",phrase:"is not empty",kind:"empty",value:false},
is_true:{label:"is true",phrase:"is true",kind:"bool",value:false},
is_false:{label:"is false",phrase:"is false",kind:"bool",value:false}
}
// ops: what the builder offers for the source. field: "" (none) | "name" | "path" | "regex".
// value: false = the source never reads cond.value; "port" = a port number.
const FLOW_RULE_SOURCES=[
{id:"output",label:"Output (stdout + stderr)",subject:"output",field:"",ops:FLOW_RULE_TEXT_OPS,op:"contains",value:true},
{id:"stdout",label:"Standard output",subject:"stdout",field:"",ops:FLOW_RULE_TEXT_OPS,op:"contains",value:true},
{id:"stderr",label:"Error output (stderr)",subject:"stderr",field:"",ops:FLOW_RULE_TEXT_OPS,op:"contains",value:true},
{id:"exit_code",label:"Exit code",subject:"exit code",field:"",ops:FLOW_RULE_NUM_OPS,op:"eq",value:true,defValue:"0"},
{id:"host_up",label:"Host is up (ping / nmap)",subject:"host",field:"",ops:FLOW_RULE_BOOL_OPS,op:"is_true",value:false},
{id:"port_open",label:"Port is open",subject:"port",field:"",ops:FLOW_RULE_BOOL_OPS,op:"is_true",value:"port",valueLabel:"Port",defValue:"80"},
{id:"line_count",label:"Number of output lines",subject:"number of output lines",field:"",ops:FLOW_RULE_NUM_OPS,op:"gt",value:true,defValue:"0"},
{id:"match_count",label:"Number of regex matches",subject:"matches",field:"regex",fieldLabel:"Regex",ops:FLOW_RULE_NUM_OPS,op:"ge",value:true,defValue:"1"},
{id:"var",label:"Variable",subject:"variable",field:"name",fieldLabel:"Variable name",ops:FLOW_RULE_TEXT_OPS.concat(FLOW_RULE_NUM_OPS,FLOW_RULE_BOOL_OPS),op:"equals",value:true},
{id:"parsed",label:"Parsed data",subject:"parsed",field:"path",fieldLabel:"Path, e.g. ports[*].port",ops:FLOW_RULE_TEXT_OPS.concat(FLOW_RULE_NUM_OPS,FLOW_RULE_BOOL_OPS),op:"not_empty",value:true}
]
function flowRuleSource(id){
for(let i=0;i<FLOW_RULE_SOURCES.length;i++)if(FLOW_RULE_SOURCES[i].id===id)return FLOW_RULE_SOURCES[i]
return null
}
function flowRuleNeedsValue(cond){
const src=flowRuleSource(cond&&cond.source)
if(!src||src.value===false)return false
if(src.value==="port")return true
const op=FLOW_RULE_OPS[cond.op]
return !!(op&&op.value)
}
// The case-insensitive switch only means something for string compares and for counting regex matches.
function flowRuleUsesCi(cond){
const src=flowRuleSource(cond&&cond.source)
const op=FLOW_RULE_OPS[cond&&cond.op]
if(!src||!op)return false
if(src.id==="match_count")return true
return src.value===true&&(op.kind==="text"||op.kind==="regex")
}
function flowRuleDefault(source){
const src=flowRuleSource(source)||FLOW_RULE_SOURCES[0]
return {source:src.id,field:"",op:src.op,value:src.defValue||"",ci:true}
}
function flowBranchDefault(name){
return {name:String(name||"match"),match:"all",conditions:[flowRuleDefault()]}
}
function flowRuleNormalize(cond){
const c=cond&&typeof cond==="object"?cond:{}
const text=(v)=>v===undefined||v===null?"":String(v)
return {source:text(c.source),field:text(c.field),op:text(c.op),value:text(c.value),ci:c.ci!==false}
}
function flowIsNumeric(value){
if(typeof value==="number")return isFinite(value)
if(typeof value!=="string")return false
const t=value.trim()
return t!==""&&isFinite(Number(t))&&!/^0[xob]/i.test(t.replace(/^[+-]/,""))
}
// Switching the source keeps what still makes sense and resets the rest (used by the builder's source select).
function flowRuleWithSource(cond,source){
const c=flowRuleNormalize(cond)
const src=flowRuleSource(source)
if(!src)return c
const fresh=flowRuleDefault(source)
const prev=flowRuleSource(c.source)
c.source=src.id
if(src.ops.indexOf(c.op)===-1)c.op=fresh.op
if(!src.field||!prev||prev.field!==src.field)c.field=""
if(src.value===false)c.value=""
else if(!prev||prev.value!==src.value||(FLOW_RULE_OPS[c.op].kind==="num"&&!flowIsNumeric(c.value)))c.value=fresh.value
return c
}
// ---- shared text helpers
// Validation issue -> the text shown to the user. An open "fail" port gets the consequence spelled out.
const FLOW_FAIL_PORT_HINT="A failed command stops the run unless its fail port is connected or the diagram's On error setting is Continue."
function flowIssueText(issue){
const i=issue&&typeof issue==="object"?issue:{}
const text=String(i.message||i.code||"")
if(i.code==="port_unconnected"&&/['"]fail['"]/.test(text)&&text.indexOf(FLOW_FAIL_PORT_HINT)<0)return text+" "+FLOW_FAIL_PORT_HINT
return text
}
function flowEscape(value){
return String(value===undefined||value===null?"":value).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")
}
// {IPv4} style target placeholders, same reading as snipIterPlaceholders: one line, a plain key, and never ${VAR}.
function flowPlaceholders(text){
const t=String(text===undefined||text===null?"":text)
const keyRe=/^[A-Za-z_][A-Za-z0-9_ ]*$/
const out=[],seen={}
let i=0
while(i<t.length){
if(t[i]!=="{"){i++;continue}
const start=i
let j=i+1,bad=false
while(j<t.length&&t[j]!=="}"){
if(t[j]==="{"||t[j]==="\r"||t[j]==="\n")bad=true
j++
}
if(j>=t.length)break
if(!bad&&!(start>0&&t[start-1]==="$")){
const raw=t.slice(start+1,j).trim()
const lower=raw.toLowerCase()
if(raw&&keyRe.test(raw)&&!seen[lower]){seen[lower]=true;out.push(raw)}
}
i=j+1
}
return out
}
// ${name}, ${last.stdout}, ${raw:name} flow values (flow_rules._TEMPLATE_RE; $${name} is an escape). -> [{name,raw}], no duplicates.
function flowVarRefs(text){
const t=String(text===undefined||text===null?"":text)
const re=/\$(\$)?\{(raw:)?\s*([^{}\s][^{}]*?)\s*\}/g
const out=[],seen={}
let m
while((m=re.exec(t))){
if(m[1])continue
const key=(m[2]?"raw:":"")+m[3]
if(seen[key])continue
seen[key]=true
out.push({name:m[3],raw:!!m[2]})
}
return out
}
// Mirror of terminal_service._AI_DESTRUCTIVE_PATTERNS. Advisory only: the bridge's plan() answer is what a run trusts.
const FLOW_DESTRUCTIVE_PATTERNS=[
/\brm\s+(-[a-z]*\s+)*-[a-z]*[rf]/i,
/\bdd\s+.*\bof=\/dev\//i,
/\bmkfs(\.[a-z0-9]+)?\b/i,
/\b(shutdown|reboot|halt|poweroff)\b/i,
/\bformat\s+[a-z]:/i,
/\b(del|erase)\s+\/[sq]/i,
/\bRemove-Item\b.*-Recurse/i,
/\b(curl|wget|iwr|Invoke-WebRequest)\b[^|]*\|\s*(sudo\s+)?(ba)?sh\b/i,
/\|\s*iex\b/i,
/\bchmod\s+(-R\s+)?777\b/i,
/\b(sudo|doas|runas|pkexec)\b/i,
/:\(\)\s*\{[\s\S]*\};\s*:/
]
function flowCommandIsDestructive(text){
const t=String(text===undefined||text===null?"":text)
return FLOW_DESTRUCTIVE_PATTERNS.some((re)=>re.test(t))
}
// ---- regex guard. JS cannot time a regex out, so the "Test" box refuses the shapes that blow up instead.
// Python spellings are accepted: (?P<name>..), (?P=name) and a leading (?ims) flag group.
function flowRegexTranslate(pattern,flags){
let p=String(pattern===undefined||pattern===null?"":pattern)
let f=String(flags||"").toLowerCase().replace(/[^ims]/g,"")
const lead=/^\(\?([imsx]+)\)/.exec(p)
if(lead){p=p.slice(lead[0].length);f+=lead[1].replace(/x/g,"")}
p=p.replace(/\(\?P<([A-Za-z_][A-Za-z0-9_]*)>/g,"(?<$1>").replace(/\(\?P=([A-Za-z_][A-Za-z0-9_]*)\)/g,"\\k<$1>")
let out=""
for(let i=0;i<f.length;i++)if(out.indexOf(f[i])===-1)out+=f[i]
return {pattern:p,flags:out}
}
function flowRegexCheck(pattern,flags){
const raw=String(pattern===undefined||pattern===null?"":pattern)
if(!raw)return "The regex is empty"
if(raw.length>FLOW_RULE_LIMITS.regex)return "The regex is longer than "+FLOW_RULE_LIMITS.regex+" characters"
const tr=flowRegexTranslate(raw,flags)
try{new RegExp(tr.pattern,tr.flags)}catch(err){return "Invalid regex: "+String(err&&err.message?err.message:err).replace(/^Invalid regular expression:\s*/,"")}
// Static screen: blank out escapes and character classes, then fold groups from the inside out.
let s=tr.pattern.replace(/\\./g,"\u0001").replace(/\[(?:[^\]])*\]/g,"\u0002")
if((s.match(/\(/g)||[]).length>FLOW_RULE_LIMITS.groups||(s.match(/\|/g)||[]).length>FLOW_RULE_LIMITS.groups*2)return "The regex has too many groups or alternatives"
const unbounded=/^(?:[+*]|\{\d+,\})/
const inner=/\(([^()]*)\)/
for(let guard=0;guard<=FLOW_RULE_LIMITS.groups+1;guard++){
const m=inner.exec(s)
if(!m)break
const body=m[1].replace(/^\?(?:[:=!]|<[=!]|<[A-Za-z_][A-Za-z0-9_]*>)/,"")
const after=s.slice(m.index+m[0].length)
const repeated=unbounded.test(after)
const loops=/[+*]|\{\d+,\}|\u0004/.test(body)
if(repeated&&loops)return "The regex nests one repeat inside another (like (a+)+), which can hang on some input"
if(repeated&&body.indexOf("|")!==-1){
const firsts={}
const alts=body.split("|")
for(let i=0;i<alts.length;i++){
const first=alts[i].charAt(0)
if(first>="\u0001"&&first<="\u0004")continue
if(first===""||first==="."||firsts[first])return "The regex repeats overlapping alternatives (like (a|aa)*), which can hang on some input"
firsts[first]=true
}
}
s=s.slice(0,m.index)+(repeated||loops?"\u0004":"\u0003")+after
}
return ""
}
function flowRegexCompile(pattern,flags,extra){
const problem=flowRegexCheck(pattern,flags)
if(problem)throw new Error(problem)
const tr=flowRegexTranslate(pattern,flags)
let f=tr.flags
String(extra||"").split("").forEach((ch)=>{if(f.indexOf(ch)===-1)f+=ch})
return new RegExp(tr.pattern,f)
}
// ---- values, as flow_rules.to_text / lookup / resolve
function flowIsDict(value){
return !!value&&typeof value==="object"&&!Array.isArray(value)
}
// Lists of plain values become a,b,c; other structures become JSON.
function flowValueText(value){
if(value===undefined||value===null)return ""
if(typeof value==="string")return value.replace(/\u0000/g,"")
if(typeof value==="boolean")return value?"true":"false"
if(typeof value==="number")return String(value)
if(Array.isArray(value)&&value.every((v)=>v===null||typeof v!=="object"))return value.map(flowValueText).join(",")
try{return JSON.stringify(value)}catch(_){return String(value)}
}
function flowValueEmpty(value){
if(value===undefined||value===null)return true
if(typeof value==="string")return value.trim()===""
if(Array.isArray(value))return value.length===0
if(typeof value==="object")return Object.keys(value).length===0
return false
}
function flowValueTruthy(value){
if(typeof value==="string")return ["true","yes","y","1","on","up","open","ok","success","alive"].indexOf(value.trim().toLowerCase())!==-1
if(value===undefined||value===null)return false
if(Array.isArray(value))return value.length>0
if(typeof value==="object")return Object.keys(value).length>0
if(typeof value==="number")return value!==0&&!isNaN(value)
return !!value
}
function flowCapText(text){
const t=String(text===undefined||text===null?"":text)
return t.length>FLOW_RULE_LIMITS.text?t.slice(0,FLOW_RULE_LIMITS.text):t
}
function flowActualLabel(value){
const text=flowValueText(value)
return text.length>200?text.slice(0,200)+"...":text
}
// "a.b[0].c", "ports[*].port", ["a key"], optional leading "$." -> tokens, or null when the path is malformed.
function flowPathTokens(path){
if(typeof path!=="string")return null
let p=path.trim()
if(p.indexOf("$.")===0)p=p.slice(2)
else if(p==="$")p=""
if(p.length>400)return null
const re=/\.?([^.\[\]]+)|\[(\*|-?\d+)\]|\["([^"\]]*)"\]|\['([^'\]]*)'\]/y
const tokens=[]
let pos=0
while(pos<p.length){
re.lastIndex=pos
const m=re.exec(p)
if(!m||re.lastIndex===pos)return null
if(m[1]!==undefined)tokens.push({kind:"key",arg:m[1].trim()})
else if(m[2]!==undefined)tokens.push(m[2]==="*"?{kind:"all"}:{kind:"index",arg:parseInt(m[2],10)})
else tokens.push({kind:"key",arg:m[3]!==undefined?m[3]:m[4]})
pos=re.lastIndex
}
return tokens.length<=24?tokens:null
}
// Own keys of plain objects (exact, then case-insensitive) and list indexes only: nothing is evaluated.
function flowWalk(value,tokens,from){
for(let i=from||0;i<tokens.length;i++){
const tok=tokens[i]
if(tok.kind==="all"){
if(flowIsDict(value))value=Object.keys(value).map((k)=>value[k])
if(!Array.isArray(value))return null
const found=[]
for(let j=0;j<value.length;j++){
const item=i+1<tokens.length?flowWalk(value[j],tokens,i+1):value[j]
if(item!==null&&item!==undefined)found.push(item)
}
return found
}
if(tok.kind==="index"){
if(!Array.isArray(value)||tok.arg<-value.length||tok.arg>=value.length)return null
value=value[tok.arg<0?value.length+tok.arg:tok.arg]
}else if(flowIsDict(value)){
if(Object.prototype.hasOwnProperty.call(value,tok.arg))value=value[tok.arg]
else{
const lowered=tok.arg.toLowerCase()
const key=Object.keys(value).filter((k)=>k.toLowerCase()===lowered)[0]
if(key===undefined)return null
value=value[key]
}
}else if(Array.isArray(value)&&/^-?\d{1,9}$/.test(tok.arg)){
const n=parseInt(tok.arg,10)
if(n<-value.length||n>=value.length)return null
value=value[n<0?value.length+n:n]
}else return null
}
return value===undefined?null:value
}
function flowLookup(scope,path){
const tokens=flowPathTokens(path===undefined||path===null?"":String(path))
if(tokens===null)return null
if(!tokens.length)return scope===undefined?null:scope
return flowWalk(scope,tokens,0)
}
// A template / condition name: the run-scope roots (vars, last, nodes, target, item, index) first, then a flow variable.
function flowResolve(scope,path){
const tokens=flowPathTokens(path===undefined||path===null?"":String(path))
if(!tokens||!tokens.length||!flowIsDict(scope))return null
const head=tokens[0]
if(head.kind==="key"&&["vars","last","nodes","target","item","index"].indexOf(head.arg)!==-1&&Object.prototype.hasOwnProperty.call(scope,head.arg)){
const value=flowWalk(scope,tokens,0)
if(value!==null)return value
}
if(flowIsDict(scope.vars)){
const value=flowWalk(scope.vars,tokens,0)
if(value!==null)return value
}
return null
}
// ${name} -> the flow value as text ($${name} stays a literal ${name}); unknown names become "".
function flowExpandTemplate(text,scope){
return String(text===undefined||text===null?"":text).replace(/\$(\$)?\{(raw:)?\s*([^{}\s][^{}]*?)\s*\}/g,(all,esc,raw,name)=>esc?all.slice(1):flowValueText(flowResolve(scope,name)))
}
// ---- envelope readers, as flow_rules._output_of / open_ports / host_is_up
function flowDataOutput(data){
const d=data&&typeof data==="object"?data:{}
const out=flowValueText(d.stdout),err=flowValueText(d.stderr)
return out+(err?"\n"+err:"")
}
function flowLineCount(text){
return String(text||"").split(/\r\n|\r|\n/).filter((line)=>line.trim()!=="").length
}
// Open port numbers known from an envelope: its parsed nmap data and nmap-style lines in its output.
function flowOpenPorts(data){
const d=data&&typeof data==="object"?data:{}
const ports={}
const add=(value)=>{
const t=String(value===undefined||value===null?"":value).trim()
if(!/^[+-]?\d+$/.test(t))return
const n=parseInt(t,10)
if(n>0&&n<65536)ports[n]=true
}
const rows=(items)=>{
if(!Array.isArray(items))return
items.forEach((row)=>{
if(flowIsDict(row)){if(String(row.state===undefined?"open":row.state).toLowerCase().split("|")[0]==="open")add(row.port)}
else add(row)
})
}
const parsed=d.parsed
if(flowIsDict(parsed)){
rows(parsed.open_ports)
rows(parsed.ports)
if(Array.isArray(parsed.hosts))parsed.hosts.forEach((h)=>{if(flowIsDict(h))rows(h.ports)})
}else if(Array.isArray(parsed))rows(parsed)
flowDataOutput(d).slice(0,FLOW_RULE_LIMITS.text*4).split(/\r\n|\r|\n/).forEach((raw)=>{
const line=raw.trim()
let m=/^(\d{1,5})\/(?:tcp|udp|sctp)[ \t]+open(?:[ \t]|$)/i.exec(line)
if(m){add(m[1]);return}
if(line.length>=400)return
m=/Discovered open port (\d{1,5})\//i.exec(line)
if(m)add(m[1])
m=/^Open [0-9a-fA-F:.\[\]]{2,60}:(\d{1,5})[ \t]*$/.exec(line)
if(m)add(m[1])
})
return Object.keys(ports).map(Number).sort((a,b)=>a-b)
}
function flowPortOpen(port,data){
const t=String(port===undefined||port===null?"":port).trim()
if(!flowIsNumeric(t))return false
const n=Number(t)
return n>0&&n<65536&&flowOpenPorts(data).indexOf(Math.trunc(n))!==-1
}
// ping / nmap heuristics over an envelope.
function flowHostUp(data){
const d=data&&typeof data==="object"?data:{}
const parsed=d.parsed
if(flowIsDict(parsed)&&typeof parsed.alive==="boolean")return parsed.alive
const text=flowDataOutput(d).slice(0,FLOW_RULE_LIMITS.text*4).toLowerCase()
let received=null
text.split(/\r\n|\r|\n/).forEach((line)=>{
if(line.length>=400)return
const m=/(\d{1,6})[ \t]+(?:packets[ \t]+)?received|received[ \t]*=[ \t]*(\d{1,6})/.exec(line)
if(m)received=parseInt(m[1]!==undefined?m[1]:m[2],10)
})
if(text.indexOf("100% packet loss")!==-1||text.indexOf("100% loss")!==-1||text.indexOf("host seems down")!==-1||text.indexOf("0 hosts up")!==-1||received===0)return false
if(text.indexOf("ttl=")!==-1||text.indexOf("bytes from")!==-1||text.indexOf("host is up")!==-1)return true
if(text.indexOf("unreachable")!==-1)return false
if(received)return true
if(flowIsDict(parsed)&&((Array.isArray(parsed.open_ports)&&parsed.open_ports.length)||(Array.isArray(parsed.hosts)&&parsed.hosts.length)))return true
return false
}
// ---- describe (same sentences as flow_rules.describe_condition)
function flowQuote(value){
const t=String(value===undefined||value===null?"":value)
return "'"+(t.length<=60?t:t.slice(0,60)+"...")+"'"
}
function flowRuleSubject(cond){
const c=flowRuleNormalize(cond)
const src=flowRuleSource(c.source)
if(c.source==="var")return "variable "+(c.field||"?")
if(c.source==="parsed")return c.field?"parsed "+c.field:"parsed data"
if(c.source==="match_count")return "matches of /"+(c.field.length<=60?c.field:c.field.slice(0,60)+"...")+"/"
return src?src.subject:(c.source||"?")
}
function flowRuleDescribe(cond){
if(!cond||typeof cond!=="object")return "invalid condition"
const c=flowRuleNormalize(cond)
if(!c.source)c.source="output"
if(!c.op)c.op="contains"
if(c.source==="port_open")return "port "+(c.value.trim()||"?")+" is "+(c.op==="is_false"?"not open":"open")
if(c.source==="host_up")return "host is "+(c.op==="is_false"?"down":"up")
const subject=flowRuleSubject(c)
const op=FLOW_RULE_OPS[c.op]
const label=op?op.phrase:c.op
if(op&&!op.value)return subject+" "+label
if(op&&op.kind==="regex")return subject+" "+label+" /"+(c.value.length<=60?c.value:c.value.slice(0,60)+"...")+"/"
if(op&&op.kind==="num")return subject+" "+label+" "+(c.value.trim()||"?")
return subject+" "+label+" "+flowQuote(c.value)
}
function flowBranchDescribe(branch){
const b=branch||{}
const conds=Array.isArray(b.conditions)?b.conditions:[]
if(!conds.length)return "(no conditions)"
return conds.map(flowRuleDescribe).join(b.match==="any"?" or ":" and ")
}
// "If output contains 'ttl=' -> alive" / "Otherwise if ... -> x" / "Otherwise -> down", one line per branch.
function flowDecisionDescribe(config){
const cfg=config||{}
const branches=Array.isArray(cfg.branches)?cfg.branches:[]
const lines=branches.map((b,i)=>(i?"Otherwise if ":"If ")+flowBranchDescribe(b)+" -> "+((b&&b.name)||"?"))
lines.push((branches.length?"Otherwise":"Always")+" -> "+(cfg.else||"else"))
return lines.join("\n")
}
// ---- validate (what the builder shows under a row; flows.validate on the Python side is the authority)
function flowRuleValidate(cond){
const c=flowRuleNormalize(cond)
const src=flowRuleSource(c.source)
if(!src)return "Pick what to check"
const op=FLOW_RULE_OPS[c.op]
if(!op)return "Pick how to compare"
if((c.source==="var"||c.source==="match_count")&&!c.field.trim())return (src.fieldLabel||"Field")+" is required"
if(src.field==="regex"){
const problem=flowRegexCheck(c.field,"")
if(problem)return problem
}
const templated=/\$\{[^}]+\}/.test(c.value)
if(src.value==="port"){
const text=c.value.trim()
if(templated)return ""
if(!/^\d+$/.test(text)||Number(text)<1||Number(text)>65535)return "Port must be a number from 1 to 65535"
return ""
}
if(!flowRuleNeedsValue(c))return ""
if(op.kind==="num")return flowIsNumeric(c.value)||templated?"":"Enter a number to compare with"
if(op.kind==="regex")return templated?"":flowRegexCheck(c.value,"")
if(c.value===""&&(c.op==="contains"||c.op==="not_contains"||c.op==="starts_with"||c.op==="ends_with"))return "Enter the text to look for"
return ""
}
function flowDecisionValidate(config){
const cfg=config||{}
const out=[]
const branches=Array.isArray(cfg.branches)?cfg.branches:[]
const seen={}
if(branches.length>FLOW_RULE_LIMITS.branches)out.push("A decision can have at most "+FLOW_RULE_LIMITS.branches+" branches")
branches.forEach((b,i)=>{
const name=String((b&&b.name)||"")
const label="Branch "+(i+1)+(name?" ("+name+")":"")
if(!FLOW_BRANCH_RE.test(name))out.push(label+": the name must be 1-24 letters, digits, - or _")
else if(seen[name])out.push(label+": the name is used twice")
seen[name]=true
if(b&&b.match!=="all"&&b.match!=="any")out.push(label+": choose ALL or ANY")
const conds=b&&Array.isArray(b.conditions)?b.conditions:[]
if(!conds.length)out.push(label+": add at least one condition, or it can never be taken")
if(conds.length>FLOW_RULE_LIMITS.conditions)out.push(label+": at most "+FLOW_RULE_LIMITS.conditions+" conditions")
conds.forEach((cond,j)=>{
const problem=flowRuleValidate(cond)
if(problem)out.push(label+", condition "+(j+1)+": "+problem)
})
})
const other=String(cfg.else===undefined||cfg.else===null?"":cfg.else)
if(!FLOW_BRANCH_RE.test(other))out.push("The 'otherwise' branch needs a name of 1-24 letters, digits, - or _")
else if(seen[other])out.push("The 'otherwise' branch name is already used by a branch")
return out
}
// ---- evaluate. Result shapes and rules follow flow_rules.evaluate_condition / evaluate_decision.
// One operator on one actual value: lists test "any element", the not_ ops are plain negations.
function flowRuleCompare(opName,actual,expected,ci){
if(opName==="is_empty")return flowValueEmpty(actual)
if(opName==="not_empty")return !flowValueEmpty(actual)
if(opName==="is_true")return flowValueTruthy(actual)
if(opName==="is_false")return !flowValueTruthy(actual)
if(opName==="not_contains")return !flowRuleCompare("contains",actual,expected,ci)
if(opName==="not_equals")return !flowRuleCompare("equals",actual,expected,ci)
if(opName==="not_regex")return !flowRuleCompare("regex",actual,expected,ci)
const items=Array.isArray(actual)?actual:[actual]
const op=FLOW_RULE_OPS[opName]
if(!op)throw new Error("Unknown operator '"+opName+"'.")
if(op.kind==="num"){
if(!flowIsNumeric(expected))throw new Error("'"+String(expected).slice(0,40)+"' is not a number.")
const w=Number(expected)
return items.some((v)=>{
const t=typeof v==="boolean"?(v?1:0):v
if(!flowIsNumeric(t))return false
const a=Number(t)
return opName==="eq"?a===w:opName==="ne"?a!==w:opName==="gt"?a>w:opName==="ge"?a>=w:opName==="lt"?a<w:a<=w
})
}
if(opName==="regex"){
if(!expected)throw new Error("The regex is empty.")
const re=flowRegexCompile(expected,ci?"i":"")
return items.some((v)=>re.test(flowCapText(flowValueText(v))))
}
let wanted=opName==="equals"?expected.trim():expected
if(ci)wanted=wanted.toLowerCase()
return items.some((v)=>{
let text=flowValueText(v)
if(opName==="equals")text=text.trim()
if(ci)text=text.toLowerCase()
if(opName==="contains")return text.indexOf(wanted)!==-1
if(opName==="equals")return text===wanted
if(opName==="starts_with")return text.indexOf(wanted)===0
return wanted.length<=text.length&&text.lastIndexOf(wanted)===text.length-wanted.length
})
}
function flowRuleActual(c,data,scope){
const d=data&&typeof data==="object"?data:{}
if(c.source==="exit_code")return d.exit_code===undefined?null:d.exit_code
if(c.source==="stdout")return flowValueText(d.stdout)
if(c.source==="stderr")return flowValueText(d.stderr)
if(c.source==="output")return flowDataOutput(d)
if(c.source==="line_count")return flowLineCount(flowDataOutput(d))
if(c.source==="match_count"){
if(!c.field)throw new Error("The regex is empty.")
const re=flowRegexCompile(c.field,c.ci?"i":"","g")
const text=flowCapText(flowDataOutput(d))
let n=0,m
while((m=re.exec(text))&&n<FLOW_RULE_LIMITS.matches){
n++
if(m[0]==="")re.lastIndex++
}
return n
}
if(c.source==="var")return flowResolve(scope,c.field.trim())
if(c.source==="parsed"){
const parsed=d.parsed===undefined?null:d.parsed
return c.field.trim()?flowLookup(parsed,c.field.trim()):parsed
}
throw new Error("Unknown condition source '"+c.source+"'.")
}
// -> {result,actual,text,error}. Never throws: a broken condition is simply false.
function flowRuleEvaluate(cond,data,scope){
const text=flowRuleDescribe(cond)
try{
if(!cond||typeof cond!=="object")throw new Error("The condition is not an object.")
const c=flowRuleNormalize(cond)
if(!c.source)c.source="output"
if(!c.op)c.op="contains"
const expected=flowExpandTemplate(c.value,scope)
if(c.source==="port_open"){
const n=flowIsNumeric(expected)?Number(expected):null
if(n===null||!(n>0&&n<65536))throw new Error("'"+expected.slice(0,40)+"' is not a port number.")
const ports=flowOpenPorts(data)
const open=ports.indexOf(Math.trunc(n))!==-1
return {result:open!==(c.op==="is_false"),actual:"open ports: "+(flowActualLabel(ports)||"none"),text:text,error:""}
}
if(c.source==="host_up"){
const up=flowHostUp(data)
return {result:up!==(c.op==="is_false"),actual:up?"up":"down",text:text,error:""}
}
if(!FLOW_RULE_OPS[c.op])throw new Error("Unknown operator '"+c.op+"'.")
const actual=flowRuleActual(c,data,scope)
return {result:!!flowRuleCompare(c.op,actual,expected,c.ci),actual:flowActualLabel(actual),text:text,error:""}
}catch(err){
return {result:false,actual:"",text:text,error:String(err&&err.message?err.message:err)}
}
}
// Branches are tested top to bottom; the first whose conditions hold wins (the trace stops there); none -> the else port.
function flowDecisionEvaluate(config,data,scope){
const cfg=config&&typeof config==="object"?config:{}
const other=typeof cfg.else==="string"&&cfg.else?cfg.else:"else"
const trace=[]
const branches=Array.isArray(cfg.branches)?cfg.branches:[]
for(let i=0;i<branches.length;i++){
const b=branches[i]
if(!flowIsDict(b))continue
const name=flowValueText(b.name)
const results=(Array.isArray(b.conditions)?b.conditions:[]).map((cond)=>flowRuleEvaluate(cond,data,scope))
// A branch without rules is never taken (the else port is the catch-all).
const matched=!results.length?false:b.match==="any"?results.some((r)=>r.result):results.every((r)=>r.result)
trace.push({branch:name,matched:matched,conditions:results})
if(matched)return {branch:name,trace:trace}
}
return {branch:other,trace:trace}
}
// ---- script templates used when the catalog has none (the "is the host alive?" example in all three languages)
const FLOW_SCRIPT_TEMPLATES=[
{id:"host-alive-python",language:"python",name:"Is the host alive? (Python)",description:"Reads the previous node's output and picks the alive or down branch.",
code:"import json, sys\n\n# The payload arrives as JSON on stdin: input (previous node), vars, target, item.\ndata = json.load(sys.stdin)\nout = ((data.get(\"input\") or {}).get(\"stdout\") or \"\").lower()\n\nalive = \"ttl=\" in out or \"bytes from\" in out\n\n# The last JSON line printed decides the branch and can set variables.\nprint(json.dumps({\"branch\": \"alive\" if alive else \"down\", \"vars\": {\"alive\": alive}}))\n"},
{id:"host-alive-bash",language:"bash",name:"Is the host alive? (Bash)",description:"Greps the payload for ping replies and picks the alive or down branch.",
code:"#!/usr/bin/env bash\n# The JSON payload is on stdin and in the file named by $LOYA_INPUT_FILE.\npayload=\"$(cat)\"\n\nif printf '%s' \"$payload\" | grep -qiE 'ttl=|bytes from'; then\n  echo '{\"branch\":\"alive\",\"vars\":{\"alive\":true}}'\nelse\n  echo '{\"branch\":\"down\",\"vars\":{\"alive\":false}}'\nfi\n"},
{id:"host-alive-powershell",language:"powershell",name:"Is the host alive? (PowerShell)",description:"Reads the payload file and picks the alive or down branch.",
code:"# The JSON payload is on stdin and in the file named by $env:LOYA_INPUT_FILE.\n$payload = Get-Content -Raw -LiteralPath $env:LOYA_INPUT_FILE | ConvertFrom-Json\n$out = [string]$payload.input.stdout\n\n$alive = $out -match 'ttl=|bytes from'\n$branch = if ($alive) { 'alive' } else { 'down' }\n\n# The last JSON line printed decides the branch and can set variables.\n@{ branch = $branch; vars = @{ alive = [bool]$alive } } | ConvertTo-Json -Compress\n"}
]
function flowScriptTemplates(catalog){
const list=catalog&&Array.isArray(catalog.script_templates)?catalog.script_templates.filter((t)=>t&&typeof t.code==="string"&&t.language):[]
return list.length?list:FLOW_SCRIPT_TEMPLATES
}
if(typeof module!=="undefined"&&module.exports)module.exports={FLOW_FAIL_PORT_HINT,flowIssueText,FLOW_BRANCH_RE,FLOW_RULE_LIMITS,FLOW_RULE_SOURCES,FLOW_RULE_OPS,FLOW_RULE_TEXT_OPS,FLOW_RULE_NUM_OPS,FLOW_RULE_BOOL_OPS,FLOW_DESTRUCTIVE_PATTERNS,FLOW_SCRIPT_TEMPLATES,flowRuleSource,flowRuleNeedsValue,flowRuleUsesCi,flowRuleDefault,flowBranchDefault,flowRuleNormalize,flowRuleWithSource,flowEscape,flowPlaceholders,flowVarRefs,flowCommandIsDestructive,flowIsNumeric,flowRegexTranslate,flowRegexCheck,flowRegexCompile,flowIsDict,flowPathTokens,flowLookup,flowResolve,flowExpandTemplate,flowValueText,flowValueEmpty,flowValueTruthy,flowDataOutput,flowLineCount,flowOpenPorts,flowPortOpen,flowHostUp,flowRuleSubject,flowRuleDescribe,flowBranchDescribe,flowDecisionDescribe,flowRuleValidate,flowDecisionValidate,flowRuleCompare,flowRuleEvaluate,flowDecisionEvaluate,flowScriptTemplates}
