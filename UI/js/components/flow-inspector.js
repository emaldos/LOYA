// Chain diagrams: the node inspector side panel (one form per node type, the no-code rule builder for decision nodes and
// the script code editor). Needs flow-rules.js loaded first; flow-model.js / flow-editor.js are used when present.
// Everything rendered from graph data goes through flowEscape: names, commands and sample output are untrusted text.
// Typing never pushes one undo step per key: edits land in a local draft and are committed to the editor after a short
// pause (FI_COMMIT_MS), on change/blur, and before the inspector switches node.
// The panel has a header (icon tile, editable title, type, id, what the node does) and three tabs: Parameters, Settings and
// Output. Node types the catalog describes with fields get the generic form of flow-fields.js (load it first); the 13
// legacy types keep the hand-written forms below. Output shows status.nodes[id] of the run handed to setRun().
const FI_COMMIT_MS=450
const FI_TABS=[["params","Parameters"],["settings","Settings"],["output","Output"]]
// Catalog fields that are run settings and not parameters (a field can also say so itself: tab:"settings" or advanced:true).
const FI_SETTING_KEYS=["timeout","verify_tls","follow_redirects","max_kb"]
const FI_LIMITS={commands:20,commandChars:4096,scriptBytes:65536,title:80,branches:12,conditions:12,assign:40}
const FI_TYPE_LABELS={start:"Start",command:"Command",script:"Script",decision:"Decision",parse:"Parse output",set:"Set variables",foreach:"For each",wait:"Wait",approval:"Approval",output:"Output",subchain:"Sub-chain",end:"End",comment:"Comment"}
const FI_LANGUAGES=[["python","Python"],["bash","Bash"],["powershell","PowerShell"]]
const FI_PARSERS=["nmap","ping","lines","json","keyvalue","ips","urls"]
const FI_SEVERITIES=["info","low","medium","high","critical"]
const FI_COMMENT_COLORS=["yellow","blue","green","pink","gray"]
const FI_SCRIPT_HELP="The script receives one JSON object on stdin (also in the file named by LOYA_INPUT_FILE):\n\n"+
'{"input": {"stdout": "...", "stderr": "...", "exit_code": 0, "parsed": null, "branch": "success"},\n "vars": {"name": "value"},\n "target": {"ipv4": "10.0.0.5"},\n "item": null, "node": "n3", "run_id": "..."}\n\n'+
"input is what the previous node produced. To choose a branch and set variables, print one JSON object as the LAST line of stdout:\n\n"+
'{"branch": "alive", "vars": {"alive": true}, "output": "anything you want to pass on"}\n\n'+
"No such line: the first branch is taken. A non-zero exit code, a timeout or a crash goes to the error port.\nThe script runs in an empty temporary folder with a clean environment (no app paths, no tokens)."
// ---- pure helpers (exported for tests/js/flow_panels.js)
function fiClone(value){
return value===undefined?undefined:JSON.parse(JSON.stringify(value))
}
function fiPathParts(path){
return String(path).split(".").map((p)=>/^\d+$/.test(p)?parseInt(p,10):p)
}
function fiGet(obj,path){
let cur=obj
const parts=fiPathParts(path)
for(let i=0;i<parts.length;i++){
if(cur===null||cur===undefined)return undefined
cur=cur[parts[i]]
}
return cur
}
function fiSet(obj,path,value){
const parts=fiPathParts(path)
let cur=obj
for(let i=0;i<parts.length-1;i++){
const key=parts[i]
if(key==="__proto__"||key==="constructor"||key==="prototype")return obj
if(cur[key]===null||typeof cur[key]!=="object")cur[key]=typeof parts[i+1]==="number"?[]:{}
cur=cur[key]
}
const last=parts[parts.length-1]
if(last==="__proto__"||last==="constructor"||last==="prototype")return obj
cur[last]=value
return obj
}
function fiMove(list,index,delta){
const to=index+delta
if(!Array.isArray(list)||index<0||index>=list.length||to<0||to>=list.length)return false
const item=list.splice(index,1)[0]
list.splice(to,0,item)
return true
}
function fiClamp(value,min,max,fallback){
let n=parseInt(value,10)
if(isNaN(n))n=fallback===undefined?min:fallback
if(min!==undefined&&min!==null&&n<min)n=min
if(max!==undefined&&max!==null&&n>max)n=max
return n
}
// Output ports per the spec table; flowNodePorts (flow-model.js) wins when it is loaded.
function fiNodePorts(node,catalog){
const n=node||{}
const cfg=n.config||{}
const known=typeof FLOW_NODE_TYPES==="undefined"||!FLOW_NODE_TYPES||Object.prototype.hasOwnProperty.call(FLOW_NODE_TYPES,n.type)
if(typeof flowNodePorts==="function"&&known){
try{const p=flowNodePorts(node);if(p&&Array.isArray(p.out))return p.out.slice()}catch(_){}
}
switch(n.type){
case "start":case "set":case "wait":case "output":return ["out"]
case "command":case "subchain":return ["success","fail"]
case "script":return (Array.isArray(cfg.branches)?cfg.branches.slice():["out"]).concat(["error"])
case "decision":return (Array.isArray(cfg.branches)?cfg.branches.map((b)=>b&&b.name):[]).concat([cfg.else||"else"])
case "parse":return ["out","nomatch"]
case "foreach":return ["item","done"]
case "approval":return ["approved","rejected"]
default:{
// A catalog type: fixed ports, or one port per row followed by the port named in config[fixed_key] (switch).
const spec=typeof flowFieldSpec==="function"?flowFieldSpec(n.type,catalog):null
if(!spec)return []
const d=spec.dynamic&&typeof spec.dynamic==="object"?spec.dynamic:null
if(!d)return Array.isArray(spec.ports)?spec.ports.map(String):[]
const out=[]
const add=(p)=>{if(typeof p==="string"&&FLOW_BRANCH_RE.test(p)&&out.indexOf(p)===-1)out.push(p)}
;(Array.isArray(cfg[d.rows])?cfg[d.rows]:[]).forEach((row)=>add(row&&row[d.name]))
add(cfg[d.fixed_key]===undefined&&spec.defaults?spec.defaults[d.fixed_key]:cfg[d.fixed_key])
return out
}
}
}
function fiCommandInfo(text){
const t=String(text===undefined||text===null?"":text)
const vars=flowVarRefs(t)
return {empty:t.trim()==="",placeholders:flowPlaceholders(t),vars:vars.filter((v)=>!v.raw).map((v)=>v.name),raw:vars.filter((v)=>v.raw).map((v)=>v.name),destructive:flowCommandIsDestructive(t),long:t.length>FI_LIMITS.commandChars}
}
function fiCommandChipsHtml(text){
const info=fiCommandInfo(text)
const chips=[]
if(info.empty)chips.push('<span class="fi-chip fi-chip-warn">Empty command</span>')
if(info.destructive)chips.push('<span class="fi-chip fi-chip-danger" title="This line matches a pattern the app treats as destructive or privileged. It will be flagged again before a run.">Looks destructive</span>')
if(info.long)chips.push('<span class="fi-chip fi-chip-danger">Longer than 4 KB</span>')
info.placeholders.forEach((p)=>chips.push('<span class="fi-chip fi-chip-ph" title="Filled from the live target">{'+flowEscape(p)+"}</span>"))
info.vars.forEach((v)=>chips.push('<span class="fi-chip fi-chip-var" title="Chain value, shell-quoted when inserted">${'+flowEscape(v)+"}</span>"))
info.raw.forEach((v)=>chips.push('<span class="fi-chip fi-chip-warn" title="Inserted without quoting: only use it for values you fully control">unquoted ${raw:'+flowEscape(v)+"}</span>"))
return chips.join("")
}
function fiLineCount(text){
return String(text===undefined||text===null?"":text).split("\n").length
}
function fiLineNumbers(text){
const n=fiLineCount(text)
let out=""
for(let i=1;i<=n;i++)out+=(i>1?"\n":"")+i
return out
}
function fiByteLength(text){
const t=String(text===undefined||text===null?"":text)
let n=0
for(let i=0;i<t.length;i++){
const c=t.charCodeAt(i)
if(c<0x80)n+=1
else if(c<0x800)n+=2
else if(c>=0xd800&&c<=0xdbff){n+=4;i++}
else n+=3
}
return n
}
function fiCodeStats(text){
const bytes=fiByteLength(text)
const lines=fiLineCount(text)
return {lines:lines,bytes:bytes,over:bytes>FI_LIMITS.scriptBytes,text:lines+(lines===1?" line":" lines")+" - "+(bytes<1024?bytes+" B":(bytes/1024).toFixed(1)+" KB")+" of 64 KB"}
}
// Tab / Shift+Tab / Enter inside the code editor. -> one replacement {start,end,text,selStart,selEnd} or null.
function fiEditKey(value,selStart,selEnd,key,shift,unit){
const v=String(value===undefined||value===null?"":value)
const u=unit||"    "
const s=Math.max(0,Math.min(selStart,selEnd)),e=Math.min(v.length,Math.max(selStart,selEnd))
const lineStart=v.lastIndexOf("\n",s-1)+1
if(key==="Tab"){
const multi=v.slice(s,e).indexOf("\n")!==-1
if(!shift&&!multi)return {start:s,end:e,text:u,selStart:s+u.length,selEnd:s+u.length}
const lastChar=multi&&v[e-1]==="\n"?e-1:e
let blockEnd=v.indexOf("\n",lastChar)
if(blockEnd===-1)blockEnd=v.length
let firstDelta=0,total=0
const out=v.slice(lineStart,blockEnd).split("\n").map((line,i)=>{
if(!shift){
if(i===0)firstDelta=u.length
total+=u.length
return u+line
}
let cut=0
if(line[0]==="\t")cut=1
else while(cut<u.length&&line[cut]===" ")cut++
if(i===0)firstDelta=-cut
total-=cut
return line.slice(cut)
})
const ns=Math.max(lineStart,s+firstDelta)
return {start:lineStart,end:blockEnd,text:out.join("\n"),selStart:ns,selEnd:s===e?ns:Math.max(ns,e+total)}
}
if(key==="Enter"){
const line=v.slice(lineStart,s)
let indent=/^[ \t]*/.exec(line)[0]
if(/[:{(\[]\s*$/.test(line)||/\b(then|do|else)\s*$/.test(line))indent+=u
const text="\n"+indent
return {start:s,end:e,text:text,selStart:s+text.length,selEnd:s+text.length}
}
return null
}
function fiApplyEdit(value,edit){
return String(value).slice(0,edit.start)+edit.text+String(value).slice(edit.end)
}
function fiBranchNameError(name,others){
const n=String(name===undefined||name===null?"":name).trim()
if(!FLOW_BRANCH_RE.test(n))return "Use 1-24 letters, digits, - or _ (no spaces)"
if((others||[]).indexOf(n)!==-1)return "'"+n+"' is already used on this node"
return ""
}
function fiUniqueName(base,taken){
const used=taken||[]
if(used.indexOf(base)===-1)return base
for(let i=2;i<200;i++)if(used.indexOf(base+i)===-1)return base+i
return base+Date.now()
}
// Branch names a script mentions ("branch": "alive"), so the editor can offer to add the missing ones.
function fiBranchesFromCode(code){
const re=/["']?\bbranch["']?\s*(?:=>|[:=])\s*["']([A-Za-z0-9_-]{1,24})["']/g
const out=[]
let m
const text=String(code||"")
const add=(name)=>{if(name&&name!=="error"&&out.indexOf(name)===-1&&out.length<FI_LIMITS.branches)out.push(name)}
while((m=re.exec(text))){
add(m[1])
// "branch": "alive" if up else "down"
const rest=/^\s+if\b[^\n]*?\belse\s+["']([A-Za-z0-9_-]{1,24})["']/.exec(text.slice(re.lastIndex))
if(rest)add(rest[1])
}
// $branch = if ($alive) { 'alive' } else { 'down' }
const ps=/\bbranch\s*=\s*if\b[^\n]*?\{\s*["']([A-Za-z0-9_-]{1,24})["']\s*\}\s*else\s*\{\s*["']([A-Za-z0-9_-]{1,24})["']\s*\}/g
while((m=ps.exec(text))){add(m[1]);add(m[2])}
return out
}
function fiNormalizeCommandRow(row){
const r=row||{}
return {id:r.id===undefined?null:r.id,src:String(r.src||""),title:String(r.title||r.cmd_note_title||r.name||""),command:String(r.command||""),category:String(r.category||"")}
}
function fiFilterCommands(rows,query,limit){
const words=String(query||"").toLowerCase().split(/\s+/).filter(Boolean)
const out=[]
const list=Array.isArray(rows)?rows:[]
for(let i=0;i<list.length&&out.length<(limit||60);i++){
const r=fiNormalizeCommandRow(list[i])
if(!r.command.trim())continue
const hay=(r.title+" "+r.category+" "+r.command).toLowerCase()
if(words.every((w)=>hay.indexOf(w)!==-1))out.push(r)
}
return out
}
function fiNodeIssues(issues,nodeId){
const pick=(list)=>(Array.isArray(list)?list:[]).filter((i)=>i&&i.node===nodeId).map((i)=>flowIssueText(i))
const src=issues||{}
return {errors:pick(src.errors),warnings:pick(src.warnings)}
}
function fiIssuesHtml(issues,nodeId){
const own=fiNodeIssues(issues,nodeId)
return own.errors.map((m)=>'<div class="fi-issue fi-issue-error">'+flowEscape(m)+"</div>").join("")+own.warnings.map((m)=>'<div class="fi-issue fi-issue-warn">'+flowEscape(m)+"</div>").join("")
}
function fiTypeLabel(type,catalog){
if(typeof FLOW_NODE_TYPES!=="undefined"&&FLOW_NODE_TYPES&&FLOW_NODE_TYPES[type]&&FLOW_NODE_TYPES[type].label)return String(FLOW_NODE_TYPES[type].label)
const cat=catalog&&catalog.node_types&&catalog.node_types[type]
const spec=typeof flowFieldSpec==="function"?flowFieldSpec(type,catalog):null
return String((spec&&spec.label)||(cat&&cat.label)||FI_TYPE_LABELS[type]||type||"Node")
}
// Everything the header and the Settings tab say about a type: the catalog first, flow-model.js second.
function fiTypeInfo(type,catalog){
const spec=(typeof flowFieldSpec==="function"?flowFieldSpec(type,catalog):null)||{}
const model=typeof FLOW_NODE_TYPES!=="undefined"&&FLOW_NODE_TYPES&&Object.prototype.hasOwnProperty.call(FLOW_NODE_TYPES,type)?FLOW_NODE_TYPES[type]:{}
const pick=(k)=>spec[k]!==undefined&&spec[k]!==null&&spec[k]!==""?spec[k]:model[k]
const slug=(v,fallback)=>String(v===undefined||v===null?"":v).toLowerCase().replace(/[^a-z0-9-]/g,"").slice(0,40)||fallback
const category=slug(pick("category"),"")
return {label:fiTypeLabel(type,catalog),category:category,categoryLabel:category&&typeof flowFieldCategory==="function"?flowFieldCategory(category,catalog).label:category,color:slug(pick("color")||category,"unknown"),icon:slug(pick("icon"),"info"),description:String(pick("description")||""),tones:spec.tones&&typeof spec.tones==="object"?spec.tones:{}}
}
function fiPortTone(port,info){
const own=info&&info.tones&&Object.prototype.hasOwnProperty.call(info.tones,port)?info.tones[port]:typeof flowPortTone==="function"?flowPortTone(port):""
return ["pos","neg","alt","loop"].indexOf(own)!==-1?own:"main"
}
function fiPortChips(ports,info){
return ports.map((p)=>'<span class="fi-port-chip fi-tone-'+fiPortTone(p,info)+'">'+flowEscape(p)+"</span>").join("")
}
// The catalog entry when the type gets the generic form: it has fields and is not one of the hand-written 13.
function fiGenericSpec(type,catalog){
if(Object.prototype.hasOwnProperty.call(FI_TYPE_LABELS,type)||typeof flowFieldSpec!=="function"||typeof flowFieldsHtml!=="function")return null
const spec=flowFieldSpec(type,catalog)
return spec&&Array.isArray(spec.fields)?spec:null
}
function fiIsSettingField(field){
const f=field||{}
if(f.tab!==undefined)return f.tab==="settings"
return f.advanced===true||FI_SETTING_KEYS.indexOf(f.key)!==-1
}
function fiFieldCtx(spec,ctx,only,empty){
return {only:only,empty:empty,readOnly:!!(ctx&&ctx.readOnly),defaults:spec.defaults,portPaths:flowFieldPortPaths(spec)}
}
// ---- html builders (pure: strings in, strings out)
function fiAttr(o){
const a=o||{}
let out=""
if(a.ph)out+=' placeholder="'+flowEscape(a.ph)+'"'
if(a.max!==undefined)out+=(a.type==="number"?' max="':' maxlength="')+flowEscape(a.max)+'"'
if(a.min!==undefined)out+=' min="'+flowEscape(a.min)+'"'
if(a.fx)out+=' data-fx="'+flowEscape(a.fx)+'"'
if(a.rr)out+=' data-rr="1"'
if(a.title)out+=' title="'+flowEscape(a.title)+'"'
return out
}
function fiInput(path,value,o){
const a=o||{}
const num=a.type==="number"
return '<input class="fi-input'+(a.mono?" fi-mono":"")+(a.cls?" "+a.cls:"")+'" type="'+(num?"number":"text")+'" data-k="'+flowEscape(path)+'" data-t="'+(a.t||(num?"int":"str"))+'" value="'+flowEscape(value===undefined||value===null?"":value)+'" spellcheck="false" autocomplete="off" autocapitalize="off"'+fiAttr(a)+">"
}
function fiArea(path,value,o){
const a=o||{}
return '<textarea class="fi-input fi-area'+(a.mono?" fi-mono":"")+(a.cls?" "+a.cls:"")+'" data-k="'+flowEscape(path)+'" data-t="str" rows="'+(a.rows||3)+'" spellcheck="'+(a.spell?"true":"false")+'" autocomplete="off" autocapitalize="off"'+fiAttr(a)+">"+flowEscape(value===undefined||value===null?"":value)+"</textarea>"
}
// options: [[value,label,disabled?]]
function fiSelect(path,value,options,o){
const a=o||{}
const cur=value===undefined||value===null?"":String(value)
const known=options.some((opt)=>String(opt[0])===cur)
const all=known?options:options.concat([[cur,cur===""?"(not set)":cur+" (unknown)"]])
return '<select class="fi-select'+(a.cls?" "+a.cls:"")+'"'+(path?' data-k="'+flowEscape(path)+'"':"")+' data-t="'+(a.t||"str")+'"'+(a.chg?' data-chg="'+flowEscape(a.chg)+'"':"")+(a.data||"")+fiAttr({rr:a.rr!==false,title:a.title})+">"+all.map((opt)=>'<option value="'+flowEscape(opt[0])+'"'+(String(opt[0])===cur?" selected":"")+(opt[2]?" disabled":"")+">"+flowEscape(opt[1])+"</option>").join("")+"</select>"
}
function fiCheck(path,value,label,o){
const a=o||{}
return '<label class="fi-check"'+(a.title?' title="'+flowEscape(a.title)+'"':"")+'><input type="checkbox" data-k="'+flowEscape(path)+'" data-t="bool"'+(a.rr?' data-rr="1"':"")+(value?" checked":"")+"><span>"+flowEscape(label)+"</span></label>"
}
function fiSeg(path,value,options){
return '<span class="fi-seg" role="group">'+options.map((opt)=>'<button type="button" class="fi-seg-btn'+(String(opt[0])===String(value)?" active":"")+'" data-act="set" data-k="'+flowEscape(path)+'" data-v="'+flowEscape(opt[0])+'"'+(opt[2]?' title="'+flowEscape(opt[2])+'"':"")+">"+flowEscape(opt[1])+"</button>").join("")+"</span>"
}
function fiField(label,inner,hint){
return '<div class="fi-field"><span class="fi-label">'+flowEscape(label)+"</span>"+inner+(hint?'<span class="fi-hint">'+flowEscape(hint)+"</span>":"")+"</div>"
}
function fiIconBtn(act,icon,title,data,disabled){
return '<button type="button" class="fi-icon-btn" data-act="'+flowEscape(act)+'"'+(data||"")+' title="'+flowEscape(title)+'" aria-label="'+flowEscape(title)+'"'+(disabled?" disabled":"")+'><i class="icon icon-'+icon+'"></i></button>'
}
function fiRowBtns(prefix,data,index,count){
return '<span class="fi-row-btns">'+fiIconBtn(prefix+"-up","arrow-up","Move up",data,index===0)+fiIconBtn(prefix+"-down","arrow-down","Move down",data,index>=count-1)+fiIconBtn(prefix+"-del","trash","Remove",data,false)+"</span>"
}
function fiAddBtn(act,label,data,disabled){
return '<button type="button" class="fi-btn" data-act="'+flowEscape(act)+'"'+(data||"")+(disabled?" disabled":"")+'><i class="icon icon-add"></i><span>'+flowEscape(label)+"</span></button>"
}
// part: "params" or "settings" for one tab of the panel; left out, the whole form.
function fiCommandFormHtml(cfg,ctx,part){
const cmds=Array.isArray(cfg.commands)?cfg.commands:[]
const cat=(ctx&&ctx.catalog)||{}
const shells=(Array.isArray(cat.shells)?cat.shells:[]).filter((x)=>x&&x.id).map((x)=>[String(x.id),String(x.label||x.id)])
const rows=cmds.map((c,i)=>{
const d=' data-i="'+i+'"'
const lib=c&&c.command_id!==null&&c.command_id!==undefined&&c.command_id!==""
return '<div class="fi-cmd"'+d+'><div class="fi-cmd-top"><span class="fi-num">'+(i+1)+"</span>"+fiInput("commands."+i+".label",c&&c.label,{ph:"Label (optional)",max:80,cls:"fi-cmd-label"})+(lib?'<span class="fi-chip fi-chip-lib" title="Picked from the Commands library. The text below is what runs.">Library</span>':"")+fiRowBtns("cmd",d,i,cmds.length)+"</div>"+fiArea("commands."+i+".text",c&&c.text,{mono:true,rows:2,ph:"ping -c 2 {IPv4}",fx:"cmd",max:FI_LIMITS.commandChars,cls:"fi-cmd-text"})+'<div class="fi-chips" data-chips="'+i+'">'+fiCommandChipsHtml(c&&c.text)+"</div></div>"
}).join("")
const full=cmds.length>=FI_LIMITS.commands
const main='<div class="fi-section"><div class="fi-section-title">Commands <span class="fi-count">'+cmds.length+" of "+FI_LIMITS.commands+"</span></div>"+(rows||'<div class="fi-empty">No commands yet. Pick one from your library or type one.</div>')+'<div class="fi-actions">'+fiAddBtn("cmd-pick","Pick from Commands","",full)+fiAddBtn("cmd-type","Type a command","",full)+"</div></div>"+
fiField("Run the commands",fiSeg("mode",cfg.mode==="parallel"?"parallel":"sequence",[["sequence","One after another"],["parallel","All at once"]]),cfg.mode==="parallel"?"All lines start together; the node succeeds when every one exits 0.":"")+
(cfg.mode==="parallel"?"":fiCheck("stop_on_fail",cfg.stop_on_fail!==false,"Stop at the first command that fails"))
const extra='<div class="fi-grid2">'+fiField("Timeout per command (s)",fiInput("timeout",cfg.timeout===undefined?300:cfg.timeout,{type:"number",min:1,max:7200}))+fiField("Shell",shells.length?fiSelect("shell",cfg.shell||"",[["","Chain default"]].concat(shells),{rr:false}):fiInput("shell",cfg.shell,{ph:"Chain default",mono:true}))+"</div>"
const note='<div class="fi-note">{Element} is filled from the live target. ${name} inserts a chain value (shell-quoted); ${last.stdout} is the previous node\'s output.</div>'
return part==="settings"?extra:part==="params"?main+note:main+extra+note
}
function fiScriptFormHtml(cfg,ctx,part){
const langs=(ctx.catalog&&ctx.catalog.languages)||{}
const options=FI_LANGUAGES.map((l)=>[l[0],l[1]+(langs[l[0]]===false?" (not found on this computer)":"")])
const code=cfg.code===undefined||cfg.code===null?"":String(cfg.code)
const stats=fiCodeStats(code)
const branches=Array.isArray(cfg.branches)?cfg.branches:[]
const templates=flowScriptTemplates(ctx.catalog)
const menu=ctx.menuOpen?'<div class="fi-menu">'+templates.map((t,i)=>'<button type="button" class="fi-menu-item" data-act="tpl" data-i="'+i+'"><span class="fi-menu-name">'+flowEscape(t.name||t.id)+'</span><span class="fi-menu-desc">'+flowEscape((t.language||"")+(t.description?" - "+t.description:""))+"</span></button>").join("")+"</div>":""
const missing=fiBranchesFromCode(code).filter((b)=>branches.indexOf(b)===-1)
const rows=branches.map((b,i)=>'<div class="fi-port-row"><span class="fi-port-dot"></span><input class="fi-input fi-mono fi-port" type="text" data-rename="branches.'+i+'" value="'+flowEscape(b)+'" maxlength="24" spellcheck="false" autocomplete="off">'+fiIconBtn("sbranch-del","trash","Remove this branch",' data-i="'+i+'"',branches.length<=1)+"</div>").join("")
// Network access is a decision of its own, so it sits at the top and not among the small print.
const net='<div class="fi-switch-row'+(cfg.network===true?" is-on":"")+'"><label class="fi-switch"><input type="checkbox" data-k="network" data-t="bool" data-rr="1"'+(cfg.network===true?" checked":"")+'><span class="fi-switch-track"></span><span class="fi-switch-label">Network access</span><span class="fi-switch-state">'+(cfg.network===true?"On":"Off")+'</span></label><div class="fi-hint">A sandboxed script has no network unless this is on. Without a sandbox a script always has network access.</div></div>'
const main='<div class="fi-grid2 fi-grid-menu">'+fiField("Language",fiSelect("language",cfg.language||"python",options))+'<div class="fi-field fi-menu-host"><span class="fi-label">&nbsp;</span><button type="button" class="fi-btn" data-act="tpl-menu"><i class="icon icon-list"></i><span>Templates</span></button>'+menu+"</div></div>"+
(langs[cfg.language||"python"]===false?'<div class="fi-issue fi-issue-warn">'+flowEscape((cfg.language||"python")+" was not found on this computer. The node will fail here until it is installed.")+"</div>":"")+
'<div class="fi-section"><div class="fi-section-title">Code</div><div class="fi-code"><pre class="fi-code-gutter" aria-hidden="true">'+fiLineNumbers(code)+'</pre><textarea class="fi-code-area" data-k="code" data-t="str" data-fx="code" wrap="off" spellcheck="false" autocomplete="off" autocapitalize="off" autocorrect="off" aria-label="Script code">'+flowEscape(code)+'</textarea></div><div class="fi-code-foot"><span class="fi-code-stats'+(stats.over?" over":"")+'">'+flowEscape(stats.text)+'</span><span class="fi-hint">Tab indents. Press Esc, then Tab to leave the editor.</span></div></div>'+
'<div class="fi-section"><div class="fi-section-title">Output branches</div>'+rows+'<div class="fi-port-row fi-port-fixed"><span class="fi-port-dot fi-port-dot-err"></span><span class="fi-mono">error</span><span class="fi-hint">always there: non-zero exit, timeout or crash</span></div><div class="fi-rename-err"></div><div class="fi-actions">'+fiAddBtn("sbranch-add","Add branch","",branches.length>=FI_LIMITS.branches)+(missing.length?'<button type="button" class="fi-btn" data-act="sbranch-detect" title="The code prints these branch names">Add from code: '+flowEscape(missing.join(", "))+"</button>":"")+"</div></div>"
const timeout=fiField("Timeout (s)",fiInput("timeout",cfg.timeout===undefined?60:cfg.timeout,{type:"number",min:1,max:7200}))
const help='<details class="fi-help"><summary>How a script talks to the chain</summary><pre class="fi-help-text">'+flowEscape(FI_SCRIPT_HELP)+"</pre></details>"
return part==="settings"?net+timeout:part==="params"?main+help:net+main+timeout+help
}
function fiCondHtml(cond,bi,ci,count){
const c=flowRuleNormalize(cond)
const src=flowRuleSource(c.source)
const base="branches."+bi+".conditions."+ci
const d=' data-b="'+bi+'" data-c="'+ci+'"'
const ops=(src?src.ops:Object.keys(FLOW_RULE_OPS)).map((op)=>[op,FLOW_RULE_OPS[op].label])
const needsValue=flowRuleNeedsValue(c)
const kind=FLOW_RULE_OPS[c.op]?FLOW_RULE_OPS[c.op].kind:""
const problem=flowRuleValidate(c)
return '<div class="fi-cond"'+d+'><div class="fi-cond-row">'+fiSelect("",c.source,FLOW_RULE_SOURCES.map((s)=>[s.id,s.label]),{chg:"cond-source",data:d,cls:"fi-cond-source",rr:false,title:"What to check"})+fiRowBtns("cond",d,ci,count)+"</div>"+
(src&&src.field?'<div class="fi-cond-row">'+fiInput(base+".field",c.field,{mono:true,ph:src.fieldLabel||"",fx:"rule",max:src.field==="regex"?500:200})+"</div>":"")+
'<div class="fi-cond-row">'+fiSelect(base+".op",c.op,ops,{cls:"fi-cond-op",title:"How to compare"})+(needsValue?fiInput(base+".value",c.value,{mono:true,fx:"rule",ph:src&&src.value==="port"?"Port, e.g. 443":kind==="num"?"Number":kind==="regex"?"Regex":"Text",max:500,cls:"fi-cond-value"}):"")+"</div>"+
(flowRuleUsesCi(c)?fiCheck(base+".ci",c.ci,"Ignore upper/lower case"):"")+
'<div class="fi-cond-err" data-cond-err="'+bi+"."+ci+'">'+flowEscape(problem)+"</div></div>"
}
function fiTestHtml(config,test){
const t=test||{}
if(!String(t.stdout||"").trim()&&!String(t.stderr||"").trim()&&(t.exit===undefined||t.exit===""))return '<div class="fi-hint">Paste some output to see which branch it would take.</div>'
const exit=String(t.exit===undefined?"":t.exit).trim()
const data={stdout:String(t.stdout||""),stderr:String(t.stderr||""),exit_code:exit===""||isNaN(Number(exit))?null:Number(exit),parsed:null}
const res=flowDecisionEvaluate(config,data,{vars:{},last:data})
const branchCount=config&&Array.isArray(config.branches)?config.branches.length:0
const rows=res.trace.map((b)=>'<div class="fi-test-branch'+(b.matched?" taken":"")+'"><div class="fi-test-head"><span class="fi-mono">'+flowEscape(b.branch||"?")+'</span><span class="fi-test-flag '+(b.matched?"yes":"no")+'">'+(b.matched?"taken":"no match")+"</span></div>"+b.conditions.map((r)=>'<div class="fi-test-cond"><span class="fi-test-flag '+(r.result?"yes":"no")+'">'+(r.result?"true":"false")+'</span><span class="fi-test-text">'+flowEscape(r.text)+(r.error?' <span class="fi-test-actual">('+flowEscape(r.error)+")</span>":r.actual!==""&&r.actual.length<=60?' <span class="fi-test-actual">(got '+flowEscape(r.actual)+")</span>":"")+"</span></div>").join("")+"</div>").join("")
return '<div class="fi-test-result">This output would go to <b class="fi-mono">'+flowEscape(res.branch)+"</b>"+(res.trace.some((b)=>b.matched)?"":" (no branch matched)")+".</div>"+rows+(res.trace.length<branchCount?'<div class="fi-hint">Branches below the one taken are not checked.</div>':"")
}
function fiDecisionFormHtml(cfg,ctx){
const branches=Array.isArray(cfg.branches)?cfg.branches:[]
const test=ctx.test||{}
const cards=branches.map((b,bi)=>{
const d=' data-b="'+bi+'"'
const conds=b&&Array.isArray(b.conditions)?b.conditions:[]
return '<div class="fi-branch"'+d+'><div class="fi-branch-head"><span class="fi-branch-word">'+(bi?"Else if":"If")+"</span>"+fiSeg("branches."+bi+".match",b&&b.match==="any"?"any":"all",[["all","ALL","Every condition must be true"],["any","ANY","One true condition is enough"]])+'<span class="fi-branch-word">match</span>'+fiRowBtns("branch",d,bi,branches.length)+"</div>"+
conds.map((c,ci)=>fiCondHtml(c,bi,ci,conds.length)).join("")+
'<div class="fi-branch-foot">'+fiAddBtn("cond-add","Condition",d,conds.length>=FI_LIMITS.conditions)+'<span class="fi-branch-word">then go to</span><input class="fi-input fi-mono fi-port" type="text" data-rename="branches.'+bi+'.name" value="'+flowEscape(b&&b.name)+'" maxlength="24" spellcheck="false" autocomplete="off" title="Branch name (the port on the node)"></div></div>'
}).join("")
return '<div class="fi-section"><div class="fi-section-title">In plain words</div><pre class="fi-preview" data-preview>'+flowEscape(flowDecisionDescribe(cfg))+"</pre></div>"+
'<div class="fi-section"><div class="fi-section-title">Branches <span class="fi-count">checked top to bottom, first match wins</span></div>'+cards+'<div class="fi-actions">'+fiAddBtn("branch-add","Add branch","",branches.length>=FI_LIMITS.branches)+"</div>"+
'<div class="fi-branch fi-branch-else"><div class="fi-branch-foot"><span class="fi-branch-word">Otherwise go to</span><input class="fi-input fi-mono fi-port" type="text" data-rename="else" value="'+flowEscape(cfg.else===undefined?"else":cfg.else)+'" maxlength="24" spellcheck="false" autocomplete="off"></div></div><div class="fi-rename-err"></div></div>'+
'<details class="fi-help fi-test"'+(ctx.testOpen?" open":"")+' data-test-box><summary>Test against sample output</summary><textarea class="fi-input fi-area fi-mono" rows="4" data-test="stdout" spellcheck="false" autocomplete="off" placeholder="Paste command output here">'+flowEscape(test.stdout||"")+'</textarea><div class="fi-grid2">'+'<div class="fi-field"><span class="fi-label">Exit code</span><input class="fi-input" type="number" data-test="exit" value="'+flowEscape(test.exit===undefined?"0":test.exit)+'"></div><div class="fi-field"><span class="fi-label">Error output (optional)</span><input class="fi-input fi-mono" type="text" data-test="stderr" value="'+flowEscape(test.stderr||"")+'" spellcheck="false" autocomplete="off"></div></div><div class="fi-test-out" data-test-out>'+fiTestHtml(cfg,test)+'</div><div class="fi-hint">Runs in the editor only: nothing is executed. Variables and parsed data are empty here.</div></details>'
}
function fiAssignHtml(list,keyA,keyB,phA,phB,act){
const rows=(Array.isArray(list)?list:[]).map((a,i)=>'<div class="fi-assign-row">'+fiInput("assign."+i+"."+keyA,a&&a[keyA],{mono:true,ph:phA,max:64,cls:"fi-assign-a"})+'<span class="fi-eq">=</span>'+fiInput("assign."+i+"."+keyB,a&&a[keyB],{mono:true,ph:phB,max:2000})+fiIconBtn(act+"-del","trash","Remove",' data-i="'+i+'"',false)+"</div>").join("")
return rows+'<div class="fi-actions">'+fiAddBtn(act+"-add","Add variable","",(Array.isArray(list)?list.length:0)>=FI_LIMITS.assign)+"</div>"
}
function fiParseFormHtml(cfg,ctx){
const mode=cfg.mode||"regex"
const parsers=ctx.catalog&&Array.isArray(ctx.catalog.parsers)&&ctx.catalog.parsers.length?ctx.catalog.parsers.map((p)=>typeof p==="string"?p:String((p&&(p.id||p.name))||"")).filter(Boolean):FI_PARSERS
const problem=mode==="regex"&&cfg.pattern?flowRegexCheck(cfg.pattern,cfg.flags):""
let body=""
if(mode==="regex")body=fiField("Regex",fiInput("pattern",cfg.pattern,{mono:true,ph:"(\\d+)/tcp\\s+open",max:500,fx:"regex"}),"")+'<div class="fi-cond-err" data-regex-err>'+flowEscape(problem)+"</div>"+fiField("Flags",fiInput("flags",cfg.flags===undefined?"i":cfg.flags,{mono:true,ph:"i",max:4}),"i = ignore case, m = ^ and $ per line, s = dot matches newlines")+'<div class="fi-section"><div class="fi-section-title">Save matches into variables</div>'+fiAssignHtml(cfg.assign,"var","from","name","group:1","passign")+'<div class="fi-hint">From: group:1 (first capture group), group:0 (the whole match) or a named group.</div></div>'
else if(mode==="tool")body=fiField("Tool",fiSelect("tool",cfg.tool||"nmap",parsers.map((p)=>[p,p])),"nmap gives hosts, ports and open_ports; ping gives alive, sent, received, loss, ttl.")
else body=fiField("Path",fiInput("path",cfg.path,{mono:true,ph:"results[*].host",max:200}),"The output must be JSON. Example: items[0].name or ports[*].port")
return fiField("How to read the output",fiSelect("mode",mode,[["regex","Regex with capture groups"],["tool","Known tool output"],["jsonpath","JSON path"]]))+fiField("Read from",fiSelect("source",cfg.source||"stdout",[["stdout","Standard output"],["stderr","Error output"],["output","Both"]]))+body+fiField("Store the result as",fiInput("var",cfg.var===undefined?"parsed":cfg.var,{mono:true,ph:"parsed",max:64}),"Later nodes read it as ${"+(cfg.var||"parsed")+"} or with a 'Parsed data' condition.")+'<div class="fi-note">Goes to <b>out</b> when something was found, otherwise to <b>nomatch</b>.</div>'
}
function fiOutputFormHtml(cfg,ctx){
const action=cfg.action||"note_append"
const notes=Array.isArray(ctx.notes)?ctx.notes:[]
const reports=Array.isArray(ctx.reports)?ctx.reports:[]
let body=""
const notePick=notes.length?fiSelect("",notes.some((n)=>n===cfg.note_name)?cfg.note_name:"",[["","Pick an existing note..."]].concat(notes.map((n)=>[n,n])),{chg:"note-pick",rr:false}):""
const reportField=reports.length?fiSelect("report_id",cfg.report_id===null||cfg.report_id===undefined?"":cfg.report_id,[["","Pick a report..."]].concat(reports.map((r)=>[r.id,r.title||("Report "+r.id)])),{t:"intnull"}):fiInput("report_id",cfg.report_id,{type:"number",t:"intnull",min:1,ph:"Report id"})
if(action==="note_append")body=fiField("Note name",fiInput("note_name",cfg.note_name,{ph:"Recon notes",max:200})+notePick,"Created when it does not exist. ${vars} work here too.")
else if(action==="finding_draft")body=fiField("Report",reportField)+fiField("Finding title",fiInput("title",cfg.title,{max:200}))+fiField("Severity",fiSelect("severity",cfg.severity||"info",FI_SEVERITIES.map((s)=>[s,s.charAt(0).toUpperCase()+s.slice(1)])))
else if(action==="evidence")body=fiField("Report",reportField)+fiField("Evidence title",fiInput("title",cfg.title,{max:200}))
else body=fiField("Notification title",fiInput("title",cfg.title,{max:200}))
return fiField("What to do",fiSelect("action",action,[["note_append","Append to a note"],["finding_draft","Draft a report finding"],["evidence","Attach as report evidence"],["notify","Show a notification"]]))+body+fiField("Content",fiArea("content",cfg.content===undefined?"${last.stdout}":cfg.content,{mono:true,rows:4}),"{Placeholders} are filled from the live target and ${values} from the chain; ${last.stdout} is the previous node's output.")
}
function fiChainRow(row){
const r=row||{}
const id=r.playbook_id!==undefined?r.playbook_id:r.id
return {id:id,name:String(r.name||("Chain "+id)),caller:String(r.caller||"")}
}
// The hand-written form of a legacy type. part: "params" | "settings" | anything else for both.
function fiLegacyBodyHtml(node,ctx,part){
const c=ctx||{}
const n=node||{}
const cfg=n.config||{}
if(part==="settings")return n.type==="command"?fiCommandFormHtml(cfg,c,part):n.type==="script"?fiScriptFormHtml(cfg,c,part):""
let body=""
switch(n.type){
case "start":body=fiField("Started by",fiSelect("trigger",cfg.trigger||"manual",[["manual","Run button"],["caller","/caller in the terminal"],["live","Live target change"]],{rr:false}),"Informational: it does not change how the chain runs.");break
case "command":body=fiCommandFormHtml(cfg,c,part);break
case "script":body=fiScriptFormHtml(cfg,c,part);break
case "decision":body=fiDecisionFormHtml(cfg,c);break
case "parse":body=fiParseFormHtml(cfg,c);break
case "set":body='<div class="fi-section"><div class="fi-section-title">Variables</div>'+fiAssignHtml(cfg.assign,"var","value","name","text with ${vars}","sassign")+'</div><div class="fi-note">Read them later as ${name}. Values can use ${last.stdout}, ${item} or {Element}.</div>';break
case "foreach":body=fiField("Items",fiInput("items",cfg.items,{mono:true,ph:"${parsed.ports}",max:2000}),"A list value, or text that is split as chosen below.")+fiField("Split text by",fiSelect("split",cfg.split||"auto",[["auto","Automatic"],["lines","Lines"],["comma","Commas"],["json","JSON list"]],{rr:false}))+'<div class="fi-grid2">'+fiField("Item variable",fiInput("item_var",cfg.item_var===undefined?"item":cfg.item_var,{mono:true,max:64}))+fiField("Index variable",fiInput("index_var",cfg.index_var===undefined?"index":cfg.index_var,{mono:true,max:64}))+"</div>"+fiField("At most this many items",fiInput("max_items",cfg.max_items===undefined?50:cfg.max_items,{type:"number",min:1,max:1000}))+'<div class="fi-note">The <b>item</b> port runs once per item (use ${'+flowEscape(cfg.item_var||"item")+"}); <b>done</b> runs after the last one.</div>";break
case "wait":body=fiField("Seconds",fiInput("seconds",cfg.seconds===undefined?5:cfg.seconds,{type:"number",min:0,max:3600}),"0 to 3600.");break
case "approval":body=fiField("Question",fiArea("message",cfg.message,{rows:3,spell:true,max:500}),"The run pauses here until you approve or reject.")+fiField("Give up after (s)",fiInput("timeout",cfg.timeout===undefined?0:cfg.timeout,{type:"number",min:0,max:86400}),"0 waits forever. Timing out counts as rejected.");break
case "output":body=fiOutputFormHtml(cfg,c);break
case "subchain":{
const rows=(Array.isArray(c.chains)?c.chains:[]).map(fiChainRow).filter((r)=>r.id!==undefined&&r.id!==null&&String(r.id)!==String(c.selfId))
body=fiField("Chain to run",fiSelect("playbook_id",cfg.playbook_id===null||cfg.playbook_id===undefined?"":cfg.playbook_id,[["","Pick a chain..."]].concat(rows.map((r)=>[r.id,r.name+(r.caller?"  /"+r.caller:"")])),{t:"intnull",rr:false}),rows.length?"A chain cannot run itself; nesting stops at 3 levels.":"No other chains yet.")+fiCheck("pass_vars",cfg.pass_vars!==false,"Hand this chain's variables to it")
break}
case "end":body=fiField("Finish the run as",fiSeg("status",cfg.status==="fail"?"fail":"success",[["success","Success"],["fail","Failed"]]))+fiField("Message",fiInput("message",cfg.message,{max:300,ph:"Optional"}));break
case "comment":body=fiField("Text",fiArea("text",cfg.text,{rows:5,spell:true,max:2000}))+fiField("Colour",fiSelect("color",cfg.color||"yellow",FI_COMMENT_COLORS.map((x)=>[x,x.charAt(0).toUpperCase()+x.slice(1)]),{rr:false}))+'<div class="fi-grid2">'+fiField("Width",fiInput("w",cfg.w===undefined?220:cfg.w,{type:"number",min:120,max:800}))+fiField("Height",fiInput("h",cfg.h===undefined?120:cfg.h,{type:"number",min:60,max:800}))+"</div>";break
default:body='<div class="fi-empty">This node type has no settings here.</div>'
}
return body
}
// The Parameters tab. ctx={catalog,notes,reports,chains,selfId,test,testOpen,menuOpen,readOnly}
function fiParamsHtml(node,ctx){
const c=ctx||{}
const n=node||{}
const spec=fiGenericSpec(n.type,c.catalog)
return spec?flowFieldsHtml(spec.fields,n.config||{},fiFieldCtx(spec,c,(f)=>!fiIsSettingField(f))):fiLegacyBodyHtml(n,c,"params")
}
// The Settings tab: the run settings of the node (timeouts, shell, network, TLS...) and what the node is.
function fiSettingsHtml(node,ctx){
const c=ctx||{}
const n=node||{}
const spec=fiGenericSpec(n.type,c.catalog)
const info=fiTypeInfo(n.type,c.catalog)
const own=spec?flowFieldsHtml(spec.fields,n.config||{},fiFieldCtx(spec,c,fiIsSettingField,"")):fiLegacyBodyHtml(n,c,"settings")
const ports=fiNodePorts(n,c.catalog)
const row=(k,v)=>'<div class="fi-about-row"><span class="fi-about-k">'+k+'</span><span class="fi-about-v">'+v+"</span></div>"
return (own||'<div class="fi-hint">This node has no run settings. Its title is edited at the top of the panel.</div>')+'<div class="fi-section"><div class="fi-section-title">About this node</div><div class="fi-about">'+row("Type",flowEscape(info.label)+' <span class="fi-mono fi-about-dim">'+flowEscape(n.type)+"</span>")+row("Id",'<span class="fi-mono">'+flowEscape(n.id)+"</span>")+(info.category?row("Category",flowEscape(info.categoryLabel||info.category)):"")+row("Outputs",ports.length?fiPortChips(ports,info):"none")+"</div>"+(info.description?'<div class="fi-hint">'+flowEscape(info.description)+"</div>":"")+"</div>"
}
// Title and every control of one node in a single block (the panel itself splits it over its header and tabs).
function fiFormHtml(node,ctx){
const c=ctx||{}
const n=node||{}
const spec=fiGenericSpec(n.type,c.catalog)
return fiField("Title",fiInput("@title",n.title,{max:FI_LIMITS.title,ph:fiTypeLabel(n.type,c.catalog)}))+(spec?flowFieldsHtml(spec.fields,n.config||{},fiFieldCtx(spec,c)):fiLegacyBodyHtml(n,c,"all"))
}
// node: {id,type,title,config}. The title input commits like any other field (data-k="@title").
function fiHeadHtml(node,catalog){
if(!node)return '<span class="fi-type">Inspector</span>'
const info=fiTypeInfo(node.type,catalog)
const cfg=node.config&&typeof node.config==="object"?node.config:null
const ports=cfg?fiNodePorts(node,catalog):[]
const docs=[]
if(ports.length)docs.push('<span class="fi-docs-item">Outputs '+fiPortChips(ports,info)+"</span>")
if(cfg&&node.type!=="foreach"&&typeof cfg.var==="string"&&/^[A-Za-z_][A-Za-z0-9_]{0,39}$/.test(cfg.var))docs.push('<span class="fi-docs-item">Result in <span class="fi-mono fi-docs-var">${'+flowEscape(cfg.var)+"}</span></span>")
return '<div class="fi-head-row"><span class="fi-tile flow-cat-'+info.color+'"><i class="icon icon-'+info.icon+'"></i></span><div class="fi-head-text"><input class="fi-title" type="text" data-k="@title" data-t="str" value="'+flowEscape(node.title)+'" maxlength="'+FI_LIMITS.title+'" placeholder="'+flowEscape(info.label)+'" title="Node title" aria-label="Node title" spellcheck="false" autocomplete="off"><div class="fi-head-sub"><span class="fi-type">'+flowEscape(info.label)+'</span><span class="fi-id fi-mono" title="Node id">'+flowEscape(node.id)+"</span></div></div></div>"+(info.description?'<div class="fi-desc">'+flowEscape(info.description)+"</div>":"")+(docs.length?'<div class="fi-docs">'+docs.join("")+"</div>":"")
}
function fiTabsHtml(tab,badge){
return FI_TABS.map((t)=>'<button type="button" class="fi-tab'+(t[0]===tab?" active":"")+'" role="tab" aria-selected="'+(t[0]===tab?"true":"false")+'" data-act="tab" data-v="'+t[0]+'">'+t[1]+(t[0]==="output"&&badge?'<span class="fi-tab-dot fo-b-'+flowEscape(badge.key)+'" title="'+flowEscape(badge.label)+'"></span>':"")+"</button>").join("")
}
// ---- the panel
function flowInspectorCreate(host,editor,deps){
deps=deps||{}
const st={id:null,draft:null,type:"",sig:"",dirty:false,timer:null,committing:false,issues:{errors:[],warnings:[]},tests:{},testOpen:false,menuOpen:false,notes:null,reports:null,chains:null,loading:{},destroyed:false,picker:null,tab:"params",run:null,outFull:{},outOpen:{},outSig:"",ins:null,focusPath:""}
const root=document.createElement("div")
root.className="flow-inspector"
root.innerHTML='<div class="fi-resize" title="Drag to resize"></div><div class="fi-head"></div><div class="fi-tabs" role="tablist"></div><div class="fi-issues"></div><div class="fi-body"></div>'
host.appendChild(root)
const $=(sel)=>root.querySelector(sel)
const toast=(msg,kind)=>{if(typeof deps.toast==="function")deps.toast(msg,kind);else if(typeof showToast==="function")showToast(msg,kind)}
const bridge=(path,args)=>{
if(typeof deps.bridge==="function")return Promise.resolve().then(()=>deps.bridge(path,args||[]))
if(typeof bridgeCall==="function")return bridgeCall(path,args||[])
return Promise.reject(new Error("bridge unavailable"))
}
const selfId=()=>typeof deps.playbookId==="function"?deps.playbookId():deps.playbookId
function findNode(id){
const g=editor&&typeof editor.getGraph==="function"?editor.getGraph():null
const nodes=g&&Array.isArray(g.nodes)?g.nodes:[]
for(let i=0;i<nodes.length;i++)if(nodes[i]&&nodes[i].id===id)return nodes[i]
return null
}
const sigOf=(node)=>JSON.stringify([node.title===undefined?"":node.title,node.config||{}])
function ctx(){
return {catalog:deps.catalog||{},notes:st.notes,reports:st.reports,chains:st.chains,selfId:selfId(),test:st.tests[st.id]||{},testOpen:st.testOpen,menuOpen:st.menuOpen,readOnly:readOnly()}
}
function readOnly(){
return !!(deps.readOnly&&(typeof deps.readOnly==="function"?deps.readOnly():deps.readOnly))
}
const spec=()=>fiGenericSpec(st.type,deps.catalog)
// -- run output of the shown node (the Output tab)
function edges(){
const g=editor&&typeof editor.getGraph==="function"?editor.getGraph():null
return g&&Array.isArray(g.edges)?g.edges:[]
}
const outRec=()=>st.id&&typeof flowOutRecord==="function"?flowOutRecord(st.run,st.id):null
function outSig(){
const r=outRec()
if(!r)return st.run?"none":""
const o=r.output&&typeof r.output==="object"?r.output:{}
return [r.state,r.visits,r.branch,r.duration_ms,r.ended_at,r.seq,String(r.error||"").length,String(o.stdout||"").length,String(o.stderr||"").length,o.exit_code,o.parsed===undefined||o.parsed===null?0:1].join("|")
}
function outHtml(){
if(typeof flowOutHtml!=="function")return '<div class="fi-empty">The output preview is not available.</div>'
return flowOutHtml(outRec(),{nodeId:st.id,edges:edges(),full:st.outFull,open:st.outOpen,hasRun:!!st.run})
}
function renderTabs(){
const el=$(".fi-tabs")
if(!el)return
const rec=st.id&&st.draft?outRec():null
el.innerHTML=st.id&&st.draft?fiTabsHtml(st.tab,rec&&typeof flowOutBadge==="function"?flowOutBadge(rec,edges(),st.id):null):""
}
function renderHead(){
const head=$(".fi-head")
if(!head)return
head.innerHTML=st.id&&st.draft?fiHeadHtml({id:st.id,type:st.type,title:st.draft.title,config:st.draft.config},deps.catalog):fiHeadHtml(null)
if(st.id&&readOnly())head.querySelectorAll("input").forEach((el)=>{el.disabled=true})
}
function setTab(tab){
if(!FI_TABS.some((t)=>t[0]===tab)||tab===st.tab)return
st.tab=tab
const body=$(".fi-body")
if(body)body.scrollTop=0
renderBody(false)
}
function setRun(status){
st.run=status&&typeof status==="object"?status:null
if(st.destroyed||!st.id)return
renderTabs()
if(st.tab==="output"&&outSig()!==st.outSig)renderBody(false)
}
function copyText(text){
const t=String(text===undefined||text===null?"":text)
if(typeof deps.copy==="function"){deps.copy(t);return}
const ok=()=>toast("Copied","success")
const viaField=()=>{
const ta=document.createElement("textarea")
ta.value=t
ta.className="fi-copy-field"
root.appendChild(ta)
try{ta.select();if(document.execCommand("copy"))ok();else toast("Could not copy","error")}catch(_){toast("Could not copy","error")}
if(ta.parentNode)ta.parentNode.removeChild(ta)
}
try{if(typeof navigator!=="undefined"&&navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(t).then(ok,viaField);return}}catch(_){}
viaField()
}
// -- committing the draft
// editor.updateNode records one undo step (and merges steps on the same node made within a second), then reconciles the
// node's ports: edges of a removed port are dropped. A rename is passed explicitly so flowRenamePort moves the edges.
function commit(renames){
if(st.timer){clearTimeout(st.timer);st.timer=null}
const pairs=Array.isArray(renames)?renames:[]
if((!st.dirty&&!pairs.length)||!st.id||!st.draft)return
st.dirty=false
const d=fiClone(st.draft)
// Nothing changed since the last commit (e.g. the change event that follows a debounced commit): no extra undo step.
if(!pairs.length&&sigOf(d)===st.sig)return
st.sig=sigOf(d)
st.committing=true
const id=st.id
try{
editor.updateNode(id,(node,graph)=>{
if(!node)return
pairs.forEach((pair)=>{
let moved=false
if(graph&&typeof flowRenamePort==="function"){try{moved=flowRenamePort(graph,id,pair[0],pair[1])===true}catch(_){moved=false}}
if(!moved&&graph&&Array.isArray(graph.edges))graph.edges.forEach((e)=>{if(e&&e.from===id&&e.port===pair[0])e.port=pair[1]})
})
node.title=d.title
node.config=d.config
})
}catch(err){toast(err&&err.message?err.message:"Could not update the node","error")}
st.committing=false
}
function touch(now){
st.dirty=true
if(st.timer)clearTimeout(st.timer)
if(now){commit();return}
st.timer=setTimeout(()=>commit(),FI_COMMIT_MS)
}
// -- rendering
function renderIssues(){
const el=$(".fi-issues")
if(el)el.innerHTML=st.id?fiIssuesHtml(st.issues,st.id):""
}
function renderBody(keepFocus){
const body=$(".fi-body")
if(!body)return
closeInsert()
const top=body.scrollTop
const active=keepFocus&&document.activeElement&&root.contains(document.activeElement)?document.activeElement:null
const focusKey=active&&active.dataset?(active.dataset.k||active.dataset.rename||""):""
root.classList.toggle("has-node",!!(st.id&&st.draft))
renderHead()
renderTabs()
if(!st.id||!st.draft){
body.innerHTML='<div class="fi-empty fi-empty-big">Select a node to edit it.<br>Drag from a port to connect two nodes; double-click a node to open it here.</div>'
renderIssues()
return
}
const node={id:st.id,type:st.type,title:st.draft.title,config:st.draft.config}
body.innerHTML=st.tab==="output"?outHtml():st.tab==="settings"?fiSettingsHtml(node,ctx()):fiParamsHtml(node,ctx())
st.outSig=outSig()
root.classList.toggle("is-readonly",readOnly())
// The Output tab only has view controls (copy, show more): they stay usable on a read-only diagram.
if(readOnly()&&st.tab!=="output")body.querySelectorAll("input,textarea,select,button").forEach((el)=>{el.disabled=true})
body.scrollTop=top
const ta=body.querySelector(".fi-code-area")
if(ta)ta.addEventListener("scroll",()=>syncGutter(ta))
if(focusKey&&/^[A-Za-z0-9_.@-]+$/.test(focusKey)){
const again=root.querySelector('[data-k="'+focusKey+'"],[data-rename="'+focusKey+'"]')
if(again&&typeof again.focus==="function")again.focus()
}
renderIssues()
loadLists()
}
function syncGutter(ta){
const gutter=ta.parentNode&&ta.parentNode.querySelector(".fi-code-gutter")
if(gutter)gutter.scrollTop=ta.scrollTop
}
function loadLists(){
const once=(key,run,apply)=>{
if(st[key]!==null||st.loading[key])return
st.loading[key]=true
Promise.resolve().then(run).then((rows)=>{st[key]=apply(Array.isArray(rows)?rows:[])}).catch(()=>{st[key]=[]}).then(()=>{
st.loading[key]=false
if(st.destroyed||!st[key].length)return
if(!root.contains(document.activeElement))renderBody(false)
})
}
if(st.type==="output"){
once("notes",()=>bridge("notes.list"),(rows)=>rows.map((r)=>String((r&&r.note_name)||"")).filter(Boolean).sort((a,b)=>a.localeCompare(b)))
once("reports",()=>bridge("reports.list"),(rows)=>rows.filter((r)=>r&&r.id!==undefined).map((r)=>({id:r.id,title:String(r.title||"")})))
}
if(st.type==="subchain")once("chains",()=>typeof deps.chains==="function"?deps.chains():bridge("flows.list"),(rows)=>rows)
}
function load(id){
const node=id?findNode(id):null
st.id=node?node.id:null
st.type=node?node.type:""
st.draft=node?{title:node.title===undefined?"":node.title,config:fiClone(node.config||{})}:null
st.sig=node?sigOf(st.draft):""
st.dirty=false
st.menuOpen=false
}
function show(id){
commit()
closePicker()
closeInsert()
load(id||null)
st.testOpen=false
st.outFull={}
st.focusPath=""
renderBody(false)
}
function refresh(){
if(st.destroyed||st.committing)return
if(!st.id){renderBody(false);return}
const node=findNode(st.id)
if(!node){show(null);return}
if(st.dirty)return
if(sigOf(node)===st.sig){renderIssues();return}
load(st.id)
renderBody(true)
}
function setIssues(issues){
const src=issues||{}
st.issues={errors:Array.isArray(src.errors)?src.errors:[],warnings:Array.isArray(src.warnings)?src.warnings:[]}
renderIssues()
}
// -- draft access
function setPath(path,value){
if(path==="@title")st.draft.title=value
else fiSet(st.draft.config,path,value)
}
function readInput(el){
const t=el.dataset.t
if(t==="bool")return !!el.checked
if(t==="int"){
const min=el.min===""||el.min===undefined?undefined:Number(el.min),max=el.max===""||el.max===undefined?undefined:Number(el.max)
return fiClamp(el.value,min,max,min===undefined?0:min)
}
if(t==="intnull"){
const n=parseInt(el.value,10)
return isNaN(n)?null:n
}
if(t==="num"){
const lim=(v)=>v===""||v===undefined||v===null?undefined:Number(v)
return flowFieldNumber(el.value,{min:lim(el.min),max:lim(el.max),integer:el.dataset.int==="1"},fiGet(st.draft.config,el.dataset.k))
}
return el.value
}
// -- generic fields (flow-fields.js): the inline message under a field, and textareas that grow with their text
function fieldFeedback(el,path,value){
const sp=spec()
const hit=sp?flowFieldFind(sp.fields,path):null
if(!hit)return
const msg=flowFieldError(hit.sub||hit.field,value,{})
const box=root.querySelector('[data-ferr="'+(hit.sub?hit.field.key+"."+hit.index:hit.field.key)+'"]')
if(box)box.textContent=msg?(hit.sub?flowFieldLabel(hit.sub)+": ":"")+msg:""
if(el.classList)el.classList.toggle("invalid",!!msg)
if(el.dataset.grow){
const lim=String(el.dataset.grow).split(",")
el.rows=flowFieldGrowRows(value,parseInt(lim[0],10),parseInt(lim[1],10))
}
}
// -- the "insert a value" menu of text fields: one floating list, filled from the graph when it opens
function closeInsert(){
if(!st.ins)return
document.removeEventListener("pointerdown",st.ins.onDown,true)
if(st.ins.el.parentNode)st.ins.el.parentNode.removeChild(st.ins.el)
st.ins=null
}
function openInsert(btn){
const again=st.ins&&st.ins.btn===btn
closeInsert()
if(again||typeof flowFieldInserts!=="function")return
const rows=btn.dataset.rows||""
const path=btn.dataset.for||(rows&&st.focusPath.indexOf(rows+".")===0?st.focusPath:"")
if(!path||!/^[A-Za-z0-9_.]+$/.test(path)){toast("Click into a text cell first, then insert a value","info");return}
const field=root.querySelector('[data-k="'+path+'"]')
const menu=document.createElement("div")
menu.className="ff-menu"
menu.innerHTML=flowFieldInsertMenuHtml(flowFieldInserts(editor&&typeof editor.getGraph==="function"?editor.getGraph():null,st.id,{catalog:deps.catalog,placeholders:typeof deps.placeholders==="function"?deps.placeholders():deps.placeholders}))
const box=root.getBoundingClientRect(),at=btn.getBoundingClientRect()
// Below the button, or above it when the panel has no room left underneath.
if(at.bottom-box.top+260>box.height&&at.top-box.top>260)menu.style.bottom=Math.round(box.bottom-at.top+4)+"px"
else menu.style.top=Math.round(at.bottom-box.top+4)+"px"
root.appendChild(menu)
const ins={el:menu,btn:btn,path:path,start:field?field.selectionStart:undefined,end:field?field.selectionEnd:undefined,onDown:(e)=>{if(e.target!==btn&&!menu.contains(e.target)&&!(typeof btn.contains==="function"&&btn.contains(e.target)))closeInsert()}}
st.ins=ins
document.addEventListener("pointerdown",ins.onDown,true)
}
function pickInsert(text){
const ins=st.ins
if(!ins||!st.draft)return
const cur=fiGet(st.draft.config,ins.path)
const res=flowFieldInsertText(cur===undefined||cur===null?"":cur,ins.start,ins.end,text)
closeInsert()
setPath(ins.path,res.value)
const el=root.querySelector('[data-k="'+ins.path+'"]')
if(el){
el.value=res.value
fieldFeedback(el,ins.path,res.value)
try{el.focus();el.setSelectionRange(res.caret,res.caret)}catch(_){}
}
touch(false)
}
function updateRuleViews(){
const cfg=st.draft.config
const pre=$("[data-preview]")
if(pre)pre.textContent=flowDecisionDescribe(cfg)
;(cfg.branches||[]).forEach((b,bi)=>((b&&b.conditions)||[]).forEach((c,ci)=>{
const el=root.querySelector('[data-cond-err="'+bi+"."+ci+'"]')
if(el)el.textContent=flowRuleValidate(c)
}))
updateTest()
}
function updateTest(){
const out=$("[data-test-out]")
if(out)out.innerHTML=fiTestHtml(st.draft.config,st.tests[st.id]||{})
}
function onInput(e){
const el=e.target
if(!st.id||!st.draft||!el||!el.dataset||readOnly())return
if(el.dataset.test){
const t=st.tests[st.id]||(st.tests[st.id]={})
t[el.dataset.test]=el.value
updateTest()
return
}
if(!el.dataset.k||el.tagName==="SELECT"||el.type==="checkbox")return
// Number fields are clamped on change, not while the user is still typing digits.
if(el.dataset.t==="int"||el.dataset.t==="intnull"||el.dataset.t==="num")return
setPath(el.dataset.k,el.value)
touch(false)
if(el.dataset.ff){fieldFeedback(el,el.dataset.k,el.value);return}
const fx=el.dataset.fx
if(fx==="cmd"){
const row=el.closest(".fi-cmd")
const chips=row&&row.querySelector(".fi-chips")
if(chips)chips.innerHTML=fiCommandChipsHtml(el.value)
}else if(fx==="code"){
const gutter=el.parentNode.querySelector(".fi-code-gutter")
const numbers=fiLineNumbers(el.value)
if(gutter&&gutter.textContent!==numbers)gutter.textContent=numbers
const stats=fiCodeStats(el.value)
const label=$(".fi-code-stats")
if(label){label.textContent=stats.text;label.classList.toggle("over",stats.over)}
syncGutter(el)
}else if(fx==="rule")updateRuleViews()
else if(fx==="regex"){
const err=$("[data-regex-err]")
if(err)err.textContent=el.value?flowRegexCheck(el.value,st.draft.config.flags):""
}
}
function renameError(el,message){
const box=el.closest(".fi-section")
// A generic port field reports under itself (a row cell: under its row).
const own=el.dataset.ff?String(el.dataset.rename).split(".").slice(0,2).join("."):""
const err=(box&&box.querySelector(".fi-rename-err"))||(own&&/^[A-Za-z0-9_.]+$/.test(own)?root.querySelector('[data-ferr="'+own+'"]'):null)
if(err)err.textContent=message||""
el.classList.toggle("invalid",!!message)
}
function onRename(el){
const path=el.dataset.rename
const cfg=st.draft.config
let old=String(path==="else"?(cfg.else===undefined?"else":cfg.else):fiGet(cfg,path)||"")
const sp=el.dataset.ff?spec():null
if(!old&&sp&&sp.defaults&&typeof sp.defaults[path]==="string")old=sp.defaults[path]
const next=String(el.value||"").trim()
if(next===old){el.value=old;renameError(el,"");return}
const node={id:st.id,type:st.type,config:cfg}
const others=fiNodePorts(node,deps.catalog).filter((p)=>p!==old)
if(st.type==="script"&&others.indexOf("error")===-1)others.push("error")
const problem=fiBranchNameError(next,others)
if(problem){
renameError(el,problem)
el.value=old
return
}
renameError(el,"")
if(path==="else")cfg.else=next
else fiSet(cfg,path,next)
commit([[old,next]])
if(st.type==="decision")updateRuleViews()
// The header lists the output ports; the title field is not the one being edited here.
renderHead()
}
function onChange(e){
const el=e.target
if(!st.id||!st.draft||!el||!el.dataset||readOnly())return
if(el.dataset.test)return
if(el.dataset.rename){onRename(el);return}
if(el.dataset.chg==="cond-source"){
const bi=parseInt(el.dataset.b,10),ci=parseInt(el.dataset.c,10)
const branch=st.draft.config.branches&&st.draft.config.branches[bi]
if(!branch||!branch.conditions||!branch.conditions[ci])return
branch.conditions[ci]=flowRuleWithSource(branch.conditions[ci],el.value)
touch(true)
renderBody(false)
return
}
if(el.dataset.chg==="note-pick"){
if(!el.value)return
st.draft.config.note_name=el.value
touch(true)
renderBody(false)
return
}
if(!el.dataset.k)return
const value=readInput(el)
if((el.dataset.t==="int"||el.dataset.t==="num")&&String(value)!==el.value)el.value=String(value)
setPath(el.dataset.k,value)
touch(true)
if(el.dataset.ff)fieldFeedback(el,el.dataset.k,value)
if(el.dataset.rr)renderBody(false)
else if(st.type==="decision")updateRuleViews()
}
// -- command picker (searchable list of the Commands library)
function closePicker(){
if(!st.picker)return
document.removeEventListener("keydown",st.picker.onKey,true)
if(st.picker.el.parentNode)st.picker.el.parentNode.removeChild(st.picker.el)
st.picker=null
}
function openPicker(){
closePicker()
const overlay=document.createElement("div")
overlay.className="confirm-overlay fi-picker-overlay"
overlay.innerHTML='<div class="confirm-box confirm-box-wide glass-panel fi-picker"><div class="confirm-message">Pick from Commands</div><input type="text" class="fi-input fi-picker-search" placeholder="Search by title, category or command..." spellcheck="false" autocomplete="off"><div class="fi-picker-list"><div class="fi-empty">Loading commands...</div></div><div class="confirm-actions"><button type="button" class="confirm-cancel" data-act="picker-close">Close</button></div></div>'
document.body.appendChild(overlay)
const picker={el:overlay,rows:[],shown:[],onKey:(e)=>{if(e.key==="Escape"){e.preventDefault();e.stopPropagation();closePicker()}}}
st.picker=picker
document.addEventListener("keydown",picker.onKey,true)
const list=overlay.querySelector(".fi-picker-list")
const search=overlay.querySelector(".fi-picker-search")
const paint=()=>{
picker.shown=fiFilterCommands(picker.rows,search.value,60)
list.innerHTML=picker.shown.length?picker.shown.map((r,i)=>'<button type="button" class="fi-picker-item" data-pick="'+i+'"><span class="fi-picker-title">'+flowEscape(r.title||"(untitled)")+(r.category?'<span class="fi-picker-cat">'+flowEscape(r.category)+"</span>":"")+'</span><span class="fi-picker-cmd fi-mono">'+flowEscape(r.command.split("\n")[0].slice(0,160))+"</span></button>").join(""):'<div class="fi-empty">'+(picker.rows.length?"No commands match.":"No saved commands yet - add some on the Commands page, or type one instead.")+"</div>"
}
search.addEventListener("input",paint)
overlay.addEventListener("click",(e)=>{
if(e.target===overlay||(e.target.closest&&e.target.closest('[data-act="picker-close"]'))){closePicker();return}
const item=e.target.closest&&e.target.closest("[data-pick]")
if(!item)return
const row=picker.shown[parseInt(item.dataset.pick,10)]
if(!row||!st.draft)return
const cmds=Array.isArray(st.draft.config.commands)?st.draft.config.commands:(st.draft.config.commands=[])
if(cmds.length>=FI_LIMITS.commands){toast("A command node holds at most "+FI_LIMITS.commands+" commands","error");return}
cmds.push({text:row.command.slice(0,FI_LIMITS.commandChars),command_id:row.id,src:row.src,label:row.title.slice(0,80)})
closePicker()
touch(true)
renderBody(false)
})
Promise.resolve().then(()=>typeof deps.commands==="function"?deps.commands():bridge("commands.list")).then((rows)=>{
if(st.picker!==picker)return
picker.rows=Array.isArray(rows)?rows:[]
paint()
}).catch((err)=>{
if(st.picker!==picker)return
list.innerHTML='<div class="fi-empty">'+flowEscape(err&&err.message?err.message:"Could not load the commands")+"</div>"
})
setTimeout(()=>{if(st.picker===picker)search.focus()},0)
}
// -- buttons
function applyTemplate(tpl){
const cfg=st.draft.config
const go=()=>{
cfg.code=String(tpl.code||"")
if(tpl.language)cfg.language=tpl.language
st.menuOpen=false
touch(true)
renderBody(false)
}
if(!String(cfg.code||"").trim()||typeof appConfirm!=="function"){go();return}
appConfirm("Replace the current code with this template?",{okLabel:"Replace",danger:true}).then((ok)=>{if(ok&&st.draft&&st.draft.config===cfg)go()})
}
function onClick(e){
const btn=e.target.closest&&e.target.closest("[data-act]")
if(!btn||!root.contains(btn)||!st.id||!st.draft||btn.disabled)return
const act=btn.dataset.act
// View controls first: they work on a read-only diagram too.
if(act==="tab"){setTab(btn.dataset.v);return}
if(act==="out-more"){st.outFull[String(btn.dataset.sec)]=true;renderBody(false);return}
if(act==="out-copy"){copyText(typeof flowOutSectionText==="function"?flowOutSectionText(outRec(),btn.dataset.sec):"");return}
if(readOnly())return
if(act==="ins-open"){openInsert(btn);return}
if(act==="ins-pick"){pickInsert(btn.dataset.v);return}
const cfg=st.draft.config
const i=parseInt(btn.dataset.i,10),bi=parseInt(btn.dataset.b,10),ci=parseInt(btn.dataset.c,10)
const list=(key)=>Array.isArray(cfg[key])?cfg[key]:(cfg[key]=[])
let structural=true
switch(act){
case "set":setPath(btn.dataset.k,btn.dataset.v);break
case "cmd-pick":openPicker();return
case "cmd-type":if(list("commands").length<FI_LIMITS.commands)cfg.commands.push({text:"",command_id:null,src:"",label:""});break
case "cmd-up":fiMove(list("commands"),i,-1);break
case "cmd-down":fiMove(list("commands"),i,1);break
case "cmd-del":list("commands").splice(i,1);break
case "tpl-menu":st.menuOpen=!st.menuOpen;renderBody(false);return
case "tpl":{const tpl=flowScriptTemplates(deps.catalog)[i];if(tpl)applyTemplate(tpl);return}
case "sbranch-add":if(list("branches").length<FI_LIMITS.branches)cfg.branches.push(fiUniqueName("branch",cfg.branches.concat(["error"])));break
case "sbranch-detect":fiBranchesFromCode(cfg.code).forEach((b)=>{if(list("branches").indexOf(b)===-1&&cfg.branches.length<FI_LIMITS.branches)cfg.branches.push(b)});break
case "sbranch-del":if(list("branches").length>1)cfg.branches.splice(i,1);break
case "branch-add":if(list("branches").length<FI_LIMITS.branches)cfg.branches.push(flowBranchDefault(fiUniqueName("branch",fiNodePorts({type:"decision",config:cfg}))));break
case "branch-up":fiMove(list("branches"),bi,-1);break
case "branch-down":fiMove(list("branches"),bi,1);break
case "branch-del":list("branches").splice(bi,1);break
case "cond-add":{const b=list("branches")[bi];if(b){if(!Array.isArray(b.conditions))b.conditions=[];if(b.conditions.length<FI_LIMITS.conditions)b.conditions.push(flowRuleDefault())}break}
case "cond-up":{const b=list("branches")[bi];if(b)fiMove(b.conditions,ci,-1);break}
case "cond-down":{const b=list("branches")[bi];if(b)fiMove(b.conditions,ci,1);break}
case "cond-del":{const b=list("branches")[bi];if(b&&Array.isArray(b.conditions))b.conditions.splice(ci,1);break}
case "passign-add":list("assign").push({var:"",from:"group:1"});break
case "sassign-add":list("assign").push({var:"",value:""});break
case "passign-del":case "sassign-del":list("assign").splice(i,1);break
case "frow-add":case "frow-del":case "frow-up":case "frow-down":{
const sp=spec()
const f=sp?flowFieldList(sp.fields).filter((x)=>x.key===btn.dataset.f)[0]:null
if(!f){structural=false;break}
if(!Array.isArray(cfg[f.key]))cfg[f.key]=fiClone(flowFieldValue(f,cfg,sp.defaults))
structural=act==="frow-add"?flowFieldRowAdd(cfg,f,fiNodePorts({id:st.id,type:st.type,config:cfg},deps.catalog)):act==="frow-del"?flowFieldRowRemove(cfg,f,i):flowFieldRowMove(cfg,f,i,act==="frow-up"?-1:1)
break}
default:structural=false
}
if(!structural)return
e.preventDefault()
touch(true)
renderBody(false)
if(act.indexOf("frow-")===0)renderHead()
}
function onKeyDown(e){
const el=e.target
if(e.key==="Escape"&&st.ins){e.preventDefault();closeInsert();return}
const generic=!!(el&&el.classList&&el.classList.contains("ff-code"))
if(!el||!el.classList||!(generic||el.classList.contains("fi-code-area"))||readOnly())return
if(e.key==="Escape"){st.escaped=true;return}
if(e.ctrlKey||e.metaKey||e.altKey||e.isComposing)return
if(e.key!=="Tab"&&e.key!=="Enter")return
// Esc then Tab leaves the editor, so the keyboard is never trapped in it.
if(e.key==="Tab"&&st.escaped){st.escaped=false;return}
st.escaped=false
const unit=generic||(st.draft&&st.draft.config.language==="bash")?"  ":"    "
const edit=fiEditKey(el.value,el.selectionStart,el.selectionEnd,e.key,e.shiftKey,unit)
if(!edit)return
e.preventDefault()
if(edit.start===edit.end&&edit.text===""){return}
el.setSelectionRange(edit.start,edit.end)
let done=false
// insertText keeps the textarea's own undo history; setRangeText is the fallback.
try{done=typeof document.execCommand==="function"&&document.execCommand(edit.text===""?"delete":"insertText",false,edit.text)}catch(_){done=false}
if(!done){
el.setRangeText(edit.text,edit.start,edit.end,"end")
onInput({target:el})
}
el.setSelectionRange(edit.selStart,edit.selEnd)
}
function onFocusOut(e){
if(e.target&&e.target.classList&&(e.target.classList.contains("fi-code-area")||e.target.classList.contains("ff-code")))st.escaped=false
if(st.dirty)commit()
}
// The rows editor has one insert button per block: it writes into the cell that had the caret last.
function onFocusIn(e){
const el=e.target
if(el&&el.dataset&&el.dataset.ff&&el.dataset.k&&el.dataset.t==="str"&&el.tagName!=="SELECT")st.focusPath=el.dataset.k
}
function onToggle(e){
if(e.target&&e.target.dataset&&e.target.dataset.testBox!==undefined)st.testOpen=!!e.target.open
if(e.target&&e.target.dataset&&e.target.dataset.sec)st.outOpen[String(e.target.dataset.sec)]=!!e.target.open
}
// -- width drag (pointer capture: WebKitGTK drops moves outside the handle otherwise)
function onResizeDown(e){
const handle=e.target
if(!handle.classList||!handle.classList.contains("fi-resize")||e.button!==0)return
e.preventDefault()
const startX=e.clientX,startW=host.getBoundingClientRect().width
const dir=deps.side==="left"?1:-1
let width=startW
try{handle.setPointerCapture(e.pointerId)}catch(_){}
root.classList.add("is-resizing")
const move=(ev)=>{
width=Math.max(260,Math.min(640,Math.round(startW+(ev.clientX-startX)*dir)))
host.style.width=width+"px"
host.style.flexBasis=width+"px"
}
const up=(ev)=>{
handle.removeEventListener("pointermove",move)
handle.removeEventListener("pointerup",up)
handle.removeEventListener("pointercancel",up)
try{handle.releasePointerCapture(ev.pointerId)}catch(_){}
root.classList.remove("is-resizing")
if(width===Math.round(startW))return
if(typeof deps.onResize==="function")deps.onResize(width)
bridge("flows.prefs_set",[{inspector_width:width}]).catch(()=>{})
}
handle.addEventListener("pointermove",move)
handle.addEventListener("pointerup",up)
handle.addEventListener("pointercancel",up)
}
root.addEventListener("input",onInput)
root.addEventListener("change",onChange)
root.addEventListener("click",onClick)
root.addEventListener("keydown",onKeyDown)
root.addEventListener("focusout",onFocusOut)
root.addEventListener("focusin",onFocusIn)
root.addEventListener("toggle",onToggle,true)
root.addEventListener("pointerdown",onResizeDown)
try{if(editor&&typeof editor.getRunState==="function")st.run=editor.getRunState()||null}catch(_){st.run=null}
renderBody(false)
function destroy(){
if(st.destroyed)return
commit()
st.destroyed=true
closePicker()
closeInsert()
if(root.parentNode)root.parentNode.removeChild(root)
}
return {show:show,refresh:refresh,setIssues:setIssues,setRun:setRun,setTab:setTab,tab:()=>st.tab,flush:()=>commit(),current:()=>st.id,destroy:destroy,el:root}
}
if(typeof module!=="undefined"&&module.exports)module.exports={FI_COMMIT_MS,FI_LIMITS,fiClone,fiGet,fiSet,fiMove,fiClamp,fiNodePorts,fiCommandInfo,fiCommandChipsHtml,fiLineCount,fiLineNumbers,fiByteLength,fiCodeStats,fiEditKey,fiApplyEdit,fiBranchNameError,fiUniqueName,fiBranchesFromCode,fiNormalizeCommandRow,fiFilterCommands,fiNodeIssues,fiIssuesHtml,fiTypeLabel,fiCommandFormHtml,fiScriptFormHtml,fiCondHtml,fiTestHtml,fiDecisionFormHtml,fiParseFormHtml,fiOutputFormHtml,fiLegacyBodyHtml,fiParamsHtml,fiSettingsHtml,fiFormHtml,fiHeadHtml,fiTabsHtml,fiTypeInfo,fiPortTone,fiGenericSpec,fiIsSettingField,FI_TABS,FI_SETTING_KEYS,flowInspectorCreate}
