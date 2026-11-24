// Chain diagrams: the generic typed-field form (one renderer for every node type the catalog describes with FIELDs) and the
// per-node output preview of the inspector's Output tab. Everything above flowFieldsBind is pure: strings and plain objects
// in, strings out, so tests/js/flow_fields.js covers it in node. Node config, run output and variable names are untrusted
// text: every value goes through flowFieldEsc before it reaches markup. Loads before flow-inspector.js; needs nothing.
const FLOW_FIELD_VAR_RE=/^[A-Za-z_][A-Za-z0-9_]{0,39}$/
const FLOW_FIELD_PORT_RE=/^[A-Za-z0-9_-]{1,24}$/
const FLOW_FIELD_TYPES=["text","textarea","code","number","bool","select","var","port","rows"]
const FLOW_FIELD_ROW_TYPES=["text","select","number","bool","var","port"]
const FLOW_FIELD_LIMITS={rows:40,chars:8192,areaMin:2,areaMax:14,codeMin:4,codeMax:22,cols:4,preview:4000,previewLines:60,full:200000,value:240,treeNodes:400,treeDepth:8,treeOpen:2,menuVars:60,menuNodes:30}
const FLOW_FIELD_PLACEHOLDERS=["IPv4","Domain","URL","Port","Username"]
const FLOW_OUT_BADGES={queued:"Queued",running:"Running",ok:"OK",warn:"Failed, handled",fail:"Failed",skipped:"Skipped",waiting:"Waiting",planned:"Would run"}
const FLOW_OUT_EMPTY="Run or dry-run the chain to see this node's output"
// ---- small helpers
function flowFieldEsc(value){
return String(value===undefined||value===null?"":value).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")
}
function flowFieldSafeKey(key){
const k=String(key===undefined||key===null?"":key)
return /^[A-Za-z0-9_]{1,64}$/.test(k)&&k!=="__proto__"&&k!=="constructor"&&k!=="prototype"
}
function flowFieldType(field){
const t=field&&field.type
return FLOW_FIELD_TYPES.indexOf(t)===-1?"text":t
}
function flowFieldList(fields){
return (Array.isArray(fields)?fields:[]).filter((f)=>f&&typeof f==="object"&&flowFieldSafeKey(f.key))
}
function flowFieldSubs(field){
return flowFieldList(field&&field.rows).map((s)=>FLOW_FIELD_ROW_TYPES.indexOf(s.type)===-1?Object.assign({},s,{type:"text"}):s)
}
function flowFieldLabel(field){
const f=field||{}
return String(f.label||f.key||"")
}
// The catalog entry of a node type. Accepts flows.catalog() (node_types), the generated FLOW_CATALOG (types) or both.
function flowFieldSpec(type,catalog){
const pick=(src)=>{
const map=src&&typeof src==="object"?(src.types&&typeof src.types==="object"?src.types:src.node_types):null
const spec=map&&typeof map==="object"&&Object.prototype.hasOwnProperty.call(map,type)?map[type]:null
return spec&&typeof spec==="object"?spec:null
}
const own=pick(catalog)
if(own&&Array.isArray(own.fields))return own
const shared=pick(typeof FLOW_CATALOG!=="undefined"?FLOW_CATALOG:null)
if(shared&&Array.isArray(shared.fields))return shared
return own||shared
}
function flowFieldCategory(id,catalog){
const find=(src)=>(src&&Array.isArray(src.categories)?src.categories:[]).filter((c)=>c&&c.id===id)[0]
const cat=find(catalog)||find(typeof FLOW_CATALOG!=="undefined"?FLOW_CATALOG:null)
return {id:String(id||""),label:String((cat&&cat.label)||id||""),hint:String((cat&&cat.hint)||"")}
}
function flowFieldDefault(field){
const f=field||{}
switch(flowFieldType(f)){
case "bool":return false
case "number":return typeof f.min==="number"&&f.min>0?f.min:0
case "select":{const o=flowFieldOptions(f)[0];return o?o.value:""}
case "rows":return []
default:return ""
}
}
function flowFieldValue(field,config,defaults){
const key=field&&field.key
const own=config&&typeof config==="object"?config[key]:undefined
if(own!==undefined&&own!==null)return own
const d=defaults&&typeof defaults==="object"?defaults[key]:undefined
return d!==undefined&&d!==null?JSON.parse(JSON.stringify(d)):flowFieldDefault(field)
}
function flowFieldOptions(field){
return (field&&Array.isArray(field.options)?field.options:[]).map((o)=>o&&typeof o==="object"?{value:o.value,label:String(o.label===undefined||o.label===null?o.value:o.label)}:{value:o,label:String(o)}).filter((o)=>o.value!==undefined&&o.value!==null)
}
// show_if: {key:[allowed values]} (or one value); every key must match. Hidden fields are neither shown nor validated.
function flowFieldVisible(field,config){
const cond=field&&field.show_if
if(!cond||typeof cond!=="object")return true
const cfg=config&&typeof config==="object"?config:{}
return Object.keys(cond).every((k)=>{
const want=Array.isArray(cond[k])?cond[k]:[cond[k]]
const have=cfg[k]
return want.some((w)=>w===have||String(w)===String(have===undefined||have===null?"":have))
})
}
// Keys other fields' show_if depends on: changing one of them re-renders the form.
function flowFieldControllers(fields){
const out={}
flowFieldList(fields).forEach((f)=>{if(f.show_if&&typeof f.show_if==="object")Object.keys(f.show_if).forEach((k)=>{out[k]=true})})
return out
}
function flowFieldNumber(raw,field,fallback){
const f=field||{}
let n=typeof raw==="number"?raw:f.integer?parseInt(raw,10):parseFloat(raw)
if(!isFinite(n)){
const fb=Number(fallback)
n=fallback!==undefined&&fallback!==null&&fallback!==""&&isFinite(fb)?fb:typeof f.min==="number"?f.min:0
}
if(f.integer)n=Math.round(n)
if(typeof f.min==="number"&&n<f.min)n=f.min
if(typeof f.max==="number"&&n>f.max)n=f.max
return n
}
function flowFieldMaxRows(field){
const n=Number(field&&field.max_rows)
return isFinite(n)&&n>0?Math.floor(n):FLOW_FIELD_LIMITS.rows
}
// One field's problem as a sentence, "" when fine. opts: {required:false} mutes the empty check, {taken:[names]} for ports.
function flowFieldError(field,value,opts){
const f=field||{},o=opts||{},t=flowFieldType(f)
const needs=!!f.required&&o.required!==false
if(t==="bool")return ""
if(t==="rows"){
const n=Array.isArray(value)?value.length:0,max=flowFieldMaxRows(f)
if(n>max)return "At most "+max+" rows"
return needs&&!n?"Add at least one "+String(f.row_label||"row"):""
}
const text=value===undefined||value===null?"":String(value)
const empty=text.trim()===""
if(t==="number"){
if(empty)return needs?"Required":""
const n=Number(text)
if(!isFinite(n))return "Enter a number"
if(f.integer&&Math.floor(n)!==n)return "Whole numbers only"
if(typeof f.min==="number"&&n<f.min)return "At least "+f.min
if(typeof f.max==="number"&&n>f.max)return "At most "+f.max
return ""
}
if(empty)return needs?"Required":""
if(t==="var")return FLOW_FIELD_VAR_RE.test(text)?"":"Start with a letter or _, then letters, digits or _ (40 at most)"
if(t==="port"){
if(!FLOW_FIELD_PORT_RE.test(text))return "Use 1-24 letters, digits, - or _ (no spaces)"
return (Array.isArray(o.taken)?o.taken:[]).indexOf(text)!==-1?"'"+text+"' is already used on this node":""
}
if(t==="select"){
const options=flowFieldOptions(f)
return options.length&&!options.some((x)=>String(x.value)===text)?"Pick one of the listed options":""
}
const max=Number(f.max_chars)
if(isFinite(max)&&max>0&&text.length>max)return "Longer than "+max+" characters"
return ""
}
// Every problem of a config: [{key,path,message}]. Row cells are checked too; port cells must be unique inside their rows.
function flowFieldsValidate(fields,config,opts){
const cfg=config&&typeof config==="object"?config:{}
const out=[]
flowFieldList(fields).forEach((f)=>{
if(!flowFieldVisible(f,cfg))return
const value=cfg[f.key]
const msg=flowFieldError(f,value,opts)
if(msg)out.push({key:f.key,path:f.key,message:msg})
if(flowFieldType(f)!=="rows"||!Array.isArray(value))return
const subs=flowFieldSubs(f)
value.forEach((row,i)=>subs.forEach((s)=>{
const cell=row&&typeof row==="object"?row[s.key]:undefined
const taken=s.type==="port"?value.filter((r,j)=>j!==i&&r&&typeof r==="object").map((r)=>String(r[s.key])):[]
const problem=flowFieldError(s,cell,Object.assign({},opts||{},{taken:taken}))
if(problem)out.push({key:f.key,path:f.key+"."+i+"."+s.key,message:problem})
}))
})
return out
}
// "url" -> {field}; "headers.2.value" -> {field,index,sub}; anything else -> null.
function flowFieldFind(fields,path){
const parts=String(path===undefined||path===null?"":path).split(".")
const field=flowFieldList(fields).filter((f)=>f.key===parts[0])[0]
if(!field)return null
if(parts.length===1)return {field:field,index:-1,sub:null}
if(parts.length!==3||!/^\d+$/.test(parts[1])||flowFieldType(field)!=="rows")return null
const sub=flowFieldSubs(field).filter((s)=>s.key===parts[2])[0]
return sub?{field:field,index:parseInt(parts[1],10),sub:sub}:null
}
// Field paths that name an output port of the node (their rename must move the edges): {"default":true,"cases.name":true}.
function flowFieldPortPaths(spec){
const d=spec&&spec.dynamic&&typeof spec.dynamic==="object"?spec.dynamic:null
const out={}
if(!d)return out
if(flowFieldSafeKey(d.fixed_key))out[d.fixed_key]=true
if(flowFieldSafeKey(d.rows)&&flowFieldSafeKey(d.name))out[d.rows+"."+d.name]=true
return out
}
// ---- rows
function flowFieldRowNew(field,rows,taken){
const row={}
const list=Array.isArray(rows)?rows:[]
flowFieldSubs(field).forEach((s)=>{
if(s.type!=="port"){row[s.key]=flowFieldDefault(s);return}
const used=list.map((r)=>String(r&&typeof r==="object"?r[s.key]:"")).concat(Array.isArray(taken)?taken.map(String):[])
const base=String((field&&field.row_label)||"row").replace(/[^A-Za-z0-9_-]/g,"").slice(0,20)||"row"
let name=""
for(let i=list.length+1;i<list.length+500&&!name;i++)if(used.indexOf(base+i)===-1)name=base+i
row[s.key]=name||base
})
return row
}
function flowFieldRowAdd(config,field,taken){
if(!config||typeof config!=="object"||!field||!flowFieldSafeKey(field.key))return false
if(!Array.isArray(config[field.key]))config[field.key]=[]
if(config[field.key].length>=flowFieldMaxRows(field))return false
config[field.key].push(flowFieldRowNew(field,config[field.key],taken))
return true
}
function flowFieldRowRemove(config,field,index){
const list=config&&field&&flowFieldSafeKey(field.key)?config[field.key]:null
if(!Array.isArray(list)||!(index>=0)||index>=list.length)return false
list.splice(index,1)
return true
}
function flowFieldRowMove(config,field,index,delta){
const list=config&&field&&flowFieldSafeKey(field.key)?config[field.key]:null
const to=index+delta
if(!Array.isArray(list)||!(index>=0)||index>=list.length||!(to>=0)||to>=list.length)return false
list.splice(to,0,list.splice(index,1)[0])
return true
}
// ---- text helpers
function flowFieldGrowRows(text,min,max){
const lines=String(text===undefined||text===null?"":text).split("\n").length
return Math.max(min||1,Math.min(max||lines,lines))
}
function flowFieldInsertText(value,start,end,text){
const v=String(value===undefined||value===null?"":value),t=String(text===undefined||text===null?"":text)
let s=typeof start==="number"&&isFinite(start)?start:v.length,e=typeof end==="number"&&isFinite(end)?end:s
s=Math.max(0,Math.min(v.length,s));e=Math.max(s,Math.min(v.length,e))
return {value:v.slice(0,s)+t+v.slice(e),caret:s+t.length}
}
// Tab in a code field: two spaces at the caret (the inspector passes its richer fiEditKey when it is loaded).
function flowFieldTabEdit(value,start,end){
const r=flowFieldInsertText(value,start,end,"  ")
return {start:Math.min(start,end),end:Math.max(start,end),text:"  ",selStart:r.caret,selEnd:r.caret,value:r.value}
}
// ---- what a text field can insert: values of the run scope, target placeholders and the variables the graph defines
function flowFieldGraphVars(graph,catalog){
const out=[],seen={}
const add=(name,node)=>{
const n=typeof name==="string"?name.trim():""
if(!FLOW_FIELD_VAR_RE.test(n)||seen["$"+n])return
seen["$"+n]=true
out.push({name:n,node:String(node.id===undefined?"":node.id),title:String(node.title||node.type||node.id||"")})
}
;(graph&&Array.isArray(graph.nodes)?graph.nodes:[]).forEach((node)=>{
if(!node||typeof node!=="object")return
const cfg=node.config&&typeof node.config==="object"?node.config:{}
const spec=flowFieldSpec(node.type,catalog)
flowFieldList(spec&&spec.fields).forEach((f)=>{
if(!flowFieldVisible(f,cfg))return
if(f.type==="var")add(cfg[f.key],node)
else if(f.type==="rows"&&Array.isArray(cfg[f.key]))flowFieldSubs(f).filter((s)=>s.type==="var").forEach((s)=>cfg[f.key].forEach((row)=>add(row&&row[s.key],node)))
})
// Legacy node types have no fields in the catalog: read the keys they are known to store names in.
if(node.type!=="foreach")add(cfg.var,node)
if(Array.isArray(cfg.assign))cfg.assign.forEach((a)=>add(a&&a.var,node))
if(node.type==="foreach"){add(cfg.item_var===undefined?"item":cfg.item_var,node);add(cfg.index_var===undefined?"index":cfg.index_var,node)}
})
return out
}
function flowFieldGraphPlaceholders(graph){
const out=[],seen={}
const re=/(^|[^$\\])\{([A-Za-z_][A-Za-z0-9_ ]{0,39})\}/g
const walk=(v,depth)=>{
if(typeof v==="string"){let m;re.lastIndex=0;while((m=re.exec(v))){if(!seen["$"+m[2]]){seen["$"+m[2]]=true;out.push(m[2])}re.lastIndex=m.index+m[0].length-1}}
else if(v&&typeof v==="object"&&depth<6)(Array.isArray(v)?v:Object.keys(v).map((k)=>v[k])).forEach((x)=>walk(x,depth+1))
}
;(graph&&Array.isArray(graph.nodes)?graph.nodes:[]).forEach((n)=>walk(n&&n.config,0))
return out
}
// -> [{group,value,label,hint}]. opts: {catalog,placeholders:[names]}
function flowFieldInserts(graph,nodeId,opts){
const o=opts||{}
const items=[
{group:"Previous node",value:"${last.stdout}",hint:"Its output text"},
{group:"Previous node",value:"${last.parsed}",hint:"Its structured value"},
{group:"Previous node",value:"${last.stderr}",hint:"Its error output"},
{group:"Previous node",value:"${last.exit_code}",hint:"Its exit code"},
{group:"Loop",value:"${item}",hint:"Current item of a For each"},
{group:"Loop",value:"${index}",hint:"Position of that item, from 0"}]
const ph=[]
;(Array.isArray(o.placeholders)&&o.placeholders.length?o.placeholders:FLOW_FIELD_PLACEHOLDERS).concat(flowFieldGraphPlaceholders(graph)).forEach((p)=>{const name=String(p);if(/^[A-Za-z_][A-Za-z0-9_ ]{0,39}$/.test(name)&&ph.indexOf(name)===-1)ph.push(name)})
ph.slice(0,FLOW_FIELD_LIMITS.menuVars).forEach((p)=>items.push({group:"Live target",value:"{"+p+"}",hint:"Filled from the live target"}))
const nodes=graph&&Array.isArray(graph.nodes)?graph.nodes:[]
// A node's own variable is not set yet while it runs, so only the other nodes' names are offered.
flowFieldGraphVars({nodes:nodes.filter((n)=>n&&n.id!==nodeId)},o.catalog).slice(0,FLOW_FIELD_LIMITS.menuVars).forEach((v)=>{items.push({group:"Variables",value:"${"+v.name+"}",hint:"Set by "+v.title})})
nodes.filter((n)=>n&&n.id!==nodeId&&n.type!=="comment"&&n.type!=="start"&&/^[A-Za-z0-9_-]{1,40}$/.test(String(n.id))).slice(0,FLOW_FIELD_LIMITS.menuNodes).forEach((n)=>items.push({group:"Output of a node",value:"${nodes."+n.id+".stdout}",hint:String(n.title||n.type||n.id)}))
return items.map((i)=>({group:i.group,value:i.value,label:i.value,hint:i.hint}))
}
function flowFieldInsertMenuHtml(items){
const list=Array.isArray(items)?items:[]
if(!list.length)return '<div class="ff-menu-empty">Nothing to insert yet.</div>'
let html="",group=null
list.forEach((it)=>{
if(!it)return
if(it.group!==group){group=it.group;html+='<div class="ff-menu-group">'+flowFieldEsc(group)+"</div>"}
html+='<button type="button" class="ff-menu-item" data-act="ins-pick" data-v="'+flowFieldEsc(it.value)+'"><span class="ff-menu-val">'+flowFieldEsc(it.label===undefined?it.value:it.label)+'</span><span class="ff-menu-hint">'+flowFieldEsc(it.hint)+"</span></button>"
})
return html
}
// ---- form markup. ctx: {readOnly,defaults,portPaths,only:(field)=>bool,showRequired,insert:false,empty:"text"}
function flowFieldAttrs(field,path,ctx,type){
const f=field||{},c=ctx||{}
let out=' data-ff="1" data-t="'+type+'" aria-label="'+flowFieldEsc(flowFieldLabel(f))+'"'
out+=c.portKey?' data-rename="'+flowFieldEsc(path)+'"':' data-k="'+flowFieldEsc(path)+'"'
if(f.placeholder!==undefined&&f.placeholder!==null&&type!=="bool"&&flowFieldType(f)!=="select")out+=' placeholder="'+flowFieldEsc(f.placeholder)+'"'
if(c.controllers&&c.controllers[f.key]&&path===f.key)out+=' data-rr="1"'
if(c.readOnly)out+=" disabled"
return out
}
function flowFieldControlHtml(field,path,value,ctx,compact){
const f=field||{},c=ctx||{},t=flowFieldType(f),E=flowFieldEsc
const text=value===undefined||value===null?"":typeof value==="object"?JSON.stringify(value):String(value)
const plain=' spellcheck="false" autocomplete="off" autocapitalize="off"'
const invalid=c.invalid?" invalid":""
const expr=text.indexOf("${")!==-1||/\{[A-Za-z_][A-Za-z0-9_ ]*\}/.test(text)?" ff-expr":""
const max=Number(f.max_chars)
const cap=' maxlength="'+(isFinite(max)&&max>0?Math.floor(max):FLOW_FIELD_LIMITS.chars)+'"'
switch(t){
case "textarea":return '<textarea class="fi-input fi-area ff-area'+expr+invalid+'" rows="'+flowFieldGrowRows(text,FLOW_FIELD_LIMITS.areaMin,FLOW_FIELD_LIMITS.areaMax)+'" data-grow="'+FLOW_FIELD_LIMITS.areaMin+","+FLOW_FIELD_LIMITS.areaMax+'"'+flowFieldAttrs(f,path,c,"str")+cap+plain+">"+E(text)+"</textarea>"
case "code":return '<textarea class="fi-input fi-area fi-mono ff-code'+invalid+'" wrap="off" rows="'+flowFieldGrowRows(text,FLOW_FIELD_LIMITS.codeMin,FLOW_FIELD_LIMITS.codeMax)+'" data-grow="'+FLOW_FIELD_LIMITS.codeMin+","+FLOW_FIELD_LIMITS.codeMax+'"'+flowFieldAttrs(f,path,c,"str")+cap+plain+' autocorrect="off">'+E(text)+"</textarea>"
case "number":return '<input class="fi-input ff-num'+invalid+'" type="number" value="'+E(text)+'"'+(typeof f.min==="number"?' min="'+f.min+'"':"")+(typeof f.max==="number"?' max="'+f.max+'"':"")+' step="'+(f.integer?"1":"any")+'"'+(f.integer?' data-int="1"':"")+flowFieldAttrs(f,path,c,"num")+' autocomplete="off">'
case "bool":return compact?'<label class="fi-check ff-check"><input type="checkbox"'+flowFieldAttrs(f,path,c,"bool")+(value===true?" checked":"")+"><span>"+E(flowFieldLabel(f))+"</span></label>":'<label class="fi-switch ff-switch"><input type="checkbox"'+flowFieldAttrs(f,path,c,"bool")+(value===true?" checked":"")+'><span class="fi-switch-track"></span><span class="fi-switch-label">'+E(flowFieldLabel(f))+(f.required?'<span class="ff-req" title="Required">*</span>':"")+"</span></label>"
case "select":{
const options=flowFieldOptions(f)
const all=options.some((o)=>String(o.value)===text)?options:options.concat([{value:text,label:text===""?"(not set)":text+" (unknown)"}])
return '<select class="fi-select ff-select'+invalid+'"'+flowFieldAttrs(f,path,c,"str")+">"+all.map((o)=>'<option value="'+E(o.value)+'"'+(String(o.value)===text?" selected":"")+">"+E(o.label)+"</option>").join("")+"</select>"
}
case "var":return '<span class="ff-affix'+invalid+'"><span class="ff-affix-pre" aria-hidden="true">${</span><input class="fi-input fi-mono ff-var" type="text" value="'+E(text)+'" maxlength="40"'+flowFieldAttrs(f,path,c,"str")+plain+'><span class="ff-affix-post" aria-hidden="true">}</span></span>'
case "port":return '<input class="fi-input fi-mono ff-port'+invalid+'" type="text" value="'+E(text)+'" maxlength="24"'+flowFieldAttrs(f,path,c,"str")+plain+">"
default:return '<input class="fi-input ff-text'+expr+invalid+'" type="text" value="'+E(text)+'"'+flowFieldAttrs(f,path,c,"str")+cap+plain+">"
}
}
function flowFieldRowsHtml(field,config,ctx){
const f=field||{},c=ctx||{},E=flowFieldEsc
const rows=Array.isArray(config&&config[f.key])?config[f.key]:[]
const subs=flowFieldSubs(f)
const max=flowFieldMaxRows(f)
const what=String(f.row_label||"row")
const d=' data-f="'+E(f.key)+'"'
const off=c.readOnly?" disabled":""
const btn=(act,icon,title,i,disabled)=>'<button type="button" class="fi-icon-btn" data-act="'+act+'"'+d+' data-i="'+i+'" title="'+title+'" aria-label="'+title+'"'+(disabled||c.readOnly?" disabled":"")+'><i class="icon icon-'+icon+'"></i></button>'
const cols="ff-cols-"+Math.max(1,Math.min(FLOW_FIELD_LIMITS.cols,subs.length))
const head=rows.length&&subs.length>1?'<div class="ff-row ff-row-head '+cols+'">'+subs.map((s)=>'<span class="ff-col-label">'+(s.type==="bool"?"":E(flowFieldLabel(s))+(s.required?'<span class="ff-req">*</span>':""))+"</span>").join("")+'<span class="ff-row-btns"></span></div>':""
const body=rows.map((row,i)=>{
const r=row&&typeof row==="object"?row:{}
let problem=""
const cells=subs.map((s)=>{
const taken=s.type==="port"?rows.filter((x,j)=>j!==i&&x&&typeof x==="object").map((x)=>String(x[s.key])):[]
const msg=flowFieldVisible(s,r)?flowFieldError(s,r[s.key],{required:!!c.showRequired,taken:taken}):""
if(msg&&!problem)problem=flowFieldLabel(s)+": "+msg
const portKey=!!(c.portPaths&&c.portPaths[f.key+"."+s.key])
return '<span class="ff-cell ff-cell-'+flowFieldType(s)+'">'+(flowFieldVisible(s,r)?flowFieldControlHtml(s,f.key+"."+i+"."+s.key,r[s.key]===undefined||r[s.key]===null?flowFieldDefault(s):r[s.key],Object.assign({},c,{portKey:portKey,invalid:!!msg,controllers:null}),true):"")+"</span>"
}).join("")
return '<div class="ff-row '+cols+'" data-i="'+i+'">'+cells+'<span class="ff-row-btns">'+btn("frow-up","arrow-up","Move up",i,i===0)+btn("frow-down","arrow-down","Move down",i,i>=rows.length-1)+btn("frow-del","trash","Remove",i,false)+'</span></div><div class="ff-err ff-row-err" data-ferr="'+E(f.key+"."+i)+'">'+E(problem)+"</div>"
}).join("")
const textCells=subs.some((s)=>s.type==="text")
return '<div class="ff-rows" data-rows="'+E(f.key)+'">'+head+(body||'<div class="ff-rows-empty">No '+E(what)+" yet.</div>")+'<div class="ff-rows-foot"><button type="button" class="fi-btn ff-add" data-act="frow-add"'+d+(rows.length>=max?" disabled":off)+'><i class="icon icon-add"></i><span>Add '+E(what)+'</span></button><span class="ff-count">'+rows.length+" of "+max+"</span>"+(textCells&&c.insert!==false&&rows.length?'<button type="button" class="ff-ins" data-act="ins-open" data-rows="'+E(f.key)+'" title="Insert a value into the cell you last clicked"'+off+">{ }</button>":"")+"</div></div>"
}
function flowFieldHtml(field,config,ctx){
const f=field||{},c=Object.assign({},ctx||{}),t=flowFieldType(f),E=flowFieldEsc
const cfg=config&&typeof config==="object"?config:{}
const value=flowFieldValue(f,cfg,c.defaults)
c.portKey=!!(c.portPaths&&c.portPaths[f.key])
const msg=flowFieldError(f,value,{required:!!c.showRequired})
c.invalid=!!msg&&t!=="rows"
const label=E(flowFieldLabel(f))+(f.required?'<span class="ff-req" title="Required">*</span>':"")
const textLike=t==="text"||t==="textarea"||t==="code"
const ins=textLike&&c.insert!==false?'<button type="button" class="ff-ins" data-act="ins-open" data-for="'+E(f.key)+'" title="Insert a value: previous output, a variable or a target placeholder" aria-label="Insert a value"'+(c.readOnly?" disabled":"")+">{ }</button>":""
const head=t==="bool"?"":'<div class="ff-head"><span class="ff-label">'+label+"</span>"+(t==="rows"?"":ins)+"</div>"
const control=t==="rows"?flowFieldRowsHtml(f,Object.assign({},cfg,{[f.key]:value}),c):flowFieldControlHtml(f,f.key,value,c,false)
const half=t==="number"||t==="var"||t==="port"
return '<div class="ff-field ff-t-'+t+(half?" ff-half":"")+(f.required?" ff-required":"")+'" data-field="'+E(f.key)+'">'+head+control+(f.help?'<div class="ff-help">'+E(f.help)+"</div>":"")+'<div class="ff-err" data-ferr="'+E(f.key)+'">'+E(msg)+"</div></div>"
}
function flowFieldsHtml(fields,config,ctx){
const c=Object.assign({},ctx||{})
const cfg=config&&typeof config==="object"?config:{}
c.controllers=flowFieldControllers(fields)
const list=flowFieldList(fields).filter((f)=>flowFieldVisible(f,cfg)&&(typeof c.only!=="function"||c.only(f)))
if(!list.length)return c.empty===""?"":'<div class="ff-empty">'+flowFieldEsc(c.empty||"This node has no parameters.")+"</div>"
return '<div class="ff-form">'+list.map((f)=>flowFieldHtml(f,cfg,c)).join("")+"</div>"
}
// ---- output preview (the inspector's Output tab). rec = status.nodes[id]
function flowOutRecord(status,nodeId){
const nodes=status&&typeof status==="object"&&status.nodes&&typeof status.nodes==="object"?status.nodes:null
const rec=nodes&&Object.prototype.hasOwnProperty.call(nodes,nodeId)?nodes[nodeId]:null
return rec&&typeof rec==="object"?rec:null
}
// pending->queued, success->ok, fail->fail, or warn when the failure was routed: the branch it took has an edge.
function flowOutBadge(rec,edges,nodeId){
const r=rec||{}
const state=String(r.state||"")
let key=state==="pending"?"queued":state==="success"?"ok":Object.prototype.hasOwnProperty.call(FLOW_OUT_BADGES,state)?state:"queued"
if(state==="fail"){
const branch=typeof r.branch==="string"?r.branch:""
key=branch&&(Array.isArray(edges)?edges:[]).some((e)=>e&&e.from===nodeId&&e.port===branch)?"warn":"fail"
}
return {key:key,label:FLOW_OUT_BADGES[key]}
}
function flowOutDuration(ms){
const n=Number(ms)
if(ms===null||ms===undefined||ms===""||!isFinite(n)||n<0)return ""
if(n<1000)return Math.round(n)+" ms"
if(n<60000)return (n/1000).toFixed(n<10000?1:0)+" s"
const s=Math.floor(n/1000),m=Math.floor(s/60)
return m<60?m+"m "+("0"+(s%60)).slice(-2)+"s":Math.floor(m/60)+"h "+("0"+(m%60)).slice(-2)+"m"
}
function flowOutText(value){
if(value===undefined||value===null)return ""
if(typeof value==="string")return value
try{const t=JSON.stringify(value,null,2);return t===undefined?String(value):t}catch(_){return String(value)}
}
function flowOutTruncate(text,limit,lines){
const t=flowOutText(text)
const max=limit>0?limit:FLOW_FIELD_LIMITS.preview
let cut=t.length>max?max:t.length
if(lines>0){
let at=-1
for(let i=0;i<lines;i++){at=t.indexOf("\n",at+1);if(at===-1)break}
if(at!==-1&&at<cut)cut=at
}
// Never split a surrogate pair.
if(cut<t.length&&cut>0){const code=t.charCodeAt(cut-1);if(code>=0xd800&&code<=0xdbff)cut--}
return {text:t.slice(0,cut),more:cut<t.length,total:t.length,hidden:t.length-cut}
}
function flowOutCount(text){
const t=flowOutText(text)
if(!t)return ""
const lines=t.replace(/\n$/,"").split("\n").length
return lines+(lines===1?" line":" lines")
}
function flowOutLeaf(value){
const E=flowFieldEsc
if(value===null||value===undefined)return '<span class="fo-v fo-v-null">null</span>'
if(typeof value==="string"){
const cut=flowOutTruncate(value,FLOW_FIELD_LIMITS.value,0)
return '<span class="fo-v fo-v-str">"'+E(cut.text)+(cut.more?"...":"")+'"</span>'
}
return '<span class="fo-v fo-v-'+(typeof value==="number"?"num":typeof value==="boolean"?"bool":"str")+'">'+E(String(value))+"</span>"
}
// A collapsible tree of a JSON value. budget={n:remaining nodes}: a huge value stops growing instead of freezing the panel.
function flowOutTreeHtml(value,budget,depth,key){
const b=budget||{n:FLOW_FIELD_LIMITS.treeNodes},dep=depth||0,E=flowFieldEsc
const name=key===undefined?"":'<span class="fo-k">'+E(key)+"</span>"
if(b.n<=0)return ""
b.n--
if(value===null||typeof value!=="object")return '<div class="fo-leaf">'+name+flowOutLeaf(value)+"</div>"
const isList=Array.isArray(value)
const keys=isList?value.map((_,i)=>i):Object.keys(value)
const size='<span class="fo-n">'+(isList?"["+keys.length+"]":"{"+keys.length+"}")+"</span>"
if(!keys.length)return '<div class="fo-leaf">'+name+size+"</div>"
if(dep>=FLOW_FIELD_LIMITS.treeDepth)return '<div class="fo-leaf">'+name+size+'<span class="fo-cut">deeper levels not shown</span></div>'
let kids=""
let shown=0
for(let i=0;i<keys.length&&b.n>0;i++){kids+=flowOutTreeHtml(value[keys[i]],b,dep+1,isList?String(keys[i]):keys[i]);shown++}
if(shown<keys.length)kids+='<div class="fo-leaf fo-cut">'+(keys.length-shown)+" more not shown - Copy has everything</div>"
return '<details class="fo-node"'+(dep<FLOW_FIELD_LIMITS.treeOpen?" open":"")+"><summary>"+(name||'<span class="fo-k fo-k-root">'+(isList?"list":"object")+"</span>")+size+'</summary><div class="fo-kids">'+kids+"</div></details>"
}
// The sections a record has something for, in display order: [{id,label,kind,value,count}]
function flowOutSections(rec){
const out=rec&&rec.output&&typeof rec.output==="object"?rec.output:{}
const list=[]
const has=(v)=>v!==undefined&&v!==null&&v!==""&&!(Array.isArray(v)&&!v.length)&&!(typeof v==="object"&&!Array.isArray(v)&&!Object.keys(v).length)
if(out.http&&typeof out.http==="object"&&has(out.http))list.push({id:"http",label:"HTTP response",kind:"http",value:out.http,count:has(out.http.status)?String(out.http.status):""})
if(has(out.stdout))list.push({id:"stdout",label:"Output",kind:"text",value:flowOutText(out.stdout),count:flowOutCount(out.stdout)})
if(has(out.stderr))list.push({id:"stderr",label:"Errors",kind:"text",value:flowOutText(out.stderr),count:flowOutCount(out.stderr)})
if(out.parsed!==undefined&&out.parsed!==null&&has(out.parsed))list.push({id:"parsed",label:"Parsed data",kind:typeof out.parsed==="object"?"json":"text",value:out.parsed,count:Array.isArray(out.parsed)?out.parsed.length+(out.parsed.length===1?" item":" items"):typeof out.parsed==="object"?Object.keys(out.parsed).length+" keys":""})
if(out.vars_set&&typeof out.vars_set==="object"&&has(out.vars_set))list.push({id:"vars",label:"Variables set",kind:"kv",value:out.vars_set,count:String(Object.keys(out.vars_set).length)})
if(Array.isArray(out.resolved)&&out.resolved.length)list.push({id:"resolved",label:"Resolved commands",kind:"list",value:out.resolved.map(flowOutText),count:String(out.resolved.length)})
if(Array.isArray(out.trace)&&out.trace.length)list.push({id:"trace",label:"Decision trace",kind:"trace",value:out.trace,count:""})
return list
}
// What Copy puts on the clipboard for one section: always the whole value, never the truncated preview.
function flowOutSectionText(rec,id){
const sec=flowOutSections(rec).filter((s)=>s.id===id)[0]
if(!sec)return ""
if(sec.kind==="list")return sec.value.join("\n")
return flowOutText(sec.value)
}
function flowOutPreHtml(text,id,full,cls){
const E=flowFieldEsc
const cut=full?flowOutTruncate(text,FLOW_FIELD_LIMITS.full,0):flowOutTruncate(text,FLOW_FIELD_LIMITS.preview,FLOW_FIELD_LIMITS.previewLines)
return '<pre class="fo-pre'+(cls?" "+cls:"")+'">'+E(cut.text)+"</pre>"+(cut.more?(full?'<div class="fo-cut">'+cut.hidden+" more characters not shown here - Copy has everything.</div>":'<button type="button" class="fo-more" data-act="out-more" data-sec="'+E(id)+'">Show more ('+cut.hidden+" more characters)</button>"):"")
}
function flowOutSectionBody(sec,full){
const E=flowFieldEsc
if(sec.kind==="json")return '<div class="fo-tree">'+flowOutTreeHtml(sec.value,{n:full?FLOW_FIELD_LIMITS.treeNodes*5:FLOW_FIELD_LIMITS.treeNodes},0)+"</div>"
if(sec.kind==="kv")return '<div class="fo-kv">'+Object.keys(sec.value).slice(0,200).map((k)=>'<div class="fo-kv-row"><span class="fo-k">'+E(k)+"</span>"+flowOutLeaf(typeof sec.value[k]==="object"&&sec.value[k]!==null?JSON.stringify(sec.value[k]):sec.value[k])+"</div>").join("")+"</div>"
if(sec.kind==="list")return sec.value.slice(0,full?500:20).map((line)=>'<pre class="fo-pre fo-cmd">'+E(flowOutTruncate(line,FLOW_FIELD_LIMITS.preview,0).text)+"</pre>").join("")+(!full&&sec.value.length>20?'<button type="button" class="fo-more" data-act="out-more" data-sec="'+E(sec.id)+'">Show all '+sec.value.length+"</button>":"")
if(sec.kind==="http"){
const h=sec.value,code=Number(h.status)
const headers=h.headers&&typeof h.headers==="object"?h.headers:{}
const names=Object.keys(headers).slice(0,80)
return '<div class="fo-http"><span class="fo-badge fo-b-'+(code>=200&&code<400?"ok":code>=400?"fail":"queued")+'">'+E(h.status===undefined||h.status===null?"no status":h.status)+"</span>"+(h.elapsed_ms!==undefined&&flowOutDuration(h.elapsed_ms)?'<span class="fo-meta">'+E(flowOutDuration(h.elapsed_ms))+"</span>":"")+'</div><div class="fo-url">'+E(flowOutTruncate(h.url,FLOW_FIELD_LIMITS.value*2,0).text)+"</div>"+(names.length?'<div class="fo-kv">'+names.map((k)=>'<div class="fo-kv-row"><span class="fo-k">'+E(k)+'</span><span class="fo-v">'+E(flowOutTruncate(headers[k],FLOW_FIELD_LIMITS.value,0).text)+"</span></div>").join("")+"</div>":"")
}
if(sec.kind==="trace")return sec.value.slice(0,24).map((b)=>'<div class="fo-trace'+(b&&b.matched?" matched":"")+'"><div class="fo-trace-head"><span class="fo-k">'+E(b&&b.branch)+'</span><span class="fo-flag '+(b&&b.matched?"yes":"no")+'">'+(b&&b.matched?"taken":"no match")+"</span></div>"+(b&&Array.isArray(b.conditions)?b.conditions:[]).slice(0,24).map((c)=>'<div class="fo-trace-cond"><span class="fo-flag '+(c&&c.result?"yes":"no")+'">'+(c&&c.result?"true":"false")+'</span><span class="fo-trace-text">'+E(c&&c.text)+(c&&c.error?" ("+E(c.error)+")":"")+"</span></div>").join("")+"</div>").join("")
return flowOutPreHtml(sec.value,sec.id,full,sec.id==="stderr"?"fo-pre-err":"")
}
// ctx: {nodeId,edges,full:{section:true},open:{section:bool},hasRun:bool}
function flowOutHtml(rec,ctx){
const c=ctx||{},E=flowFieldEsc
if(!rec||typeof rec!=="object")return '<div class="fo"><div class="fo-empty">'+(c.hasRun?"This node was not part of the last run.<br>":"")+E(FLOW_OUT_EMPTY)+"</div></div>"
const badge=flowOutBadge(rec,c.edges,c.nodeId)
const out=rec.output&&typeof rec.output==="object"?rec.output:{}
const meta=[]
const dur=flowOutDuration(rec.duration_ms)
if(dur)meta.push('<span class="fo-meta" title="Duration">'+E(dur)+"</span>")
const visits=Number(rec.visits)
if(isFinite(visits)&&visits>1)meta.push('<span class="fo-meta">'+Math.floor(visits)+" visits</span>")
if(typeof rec.branch==="string"&&rec.branch)meta.push('<span class="fo-meta">took <b class="fo-branch">'+E(rec.branch)+"</b></span>")
if(out.exit_code!==undefined&&out.exit_code!==null&&out.exit_code!=="")meta.push('<span class="fo-meta">exit '+E(out.exit_code)+"</span>")
const sections=flowOutSections(rec)
const full=c.full||{},open=c.open||{}
const first=sections.filter((s)=>s.kind!=="http")[0]
const failed=rec.state==="fail"
const body=sections.map((s)=>{
const isOpen=open[s.id]===undefined?(s.id==="http"||s===first||(failed&&s.id==="stderr")||(s.id==="parsed"&&first&&first.id==="stdout"&&sections.length<=3)):!!open[s.id]
const copy=s.kind==="trace"?"":'<button type="button" class="fo-copy" data-act="out-copy" data-sec="'+E(s.id)+'" title="Copy all of it"><i class="icon icon-copy"></i><span>Copy</span></button>'
return '<details class="fo-sec" data-sec="'+E(s.id)+'"'+(isOpen?" open":"")+'><summary><span class="fo-sec-title">'+E(s.label)+"</span>"+(s.count?'<span class="fo-sec-count">'+E(s.count)+"</span>":"")+'</summary><div class="fo-sec-body">'+(copy?'<div class="fo-tools">'+copy+"</div>":"")+flowOutSectionBody(s,!!full[s.id])+"</div></details>"
}).join("")
const idle=badge.key==="queued"?"This node has not run yet.":badge.key==="running"?"Running - output appears here as it arrives.":badge.key==="skipped"?"The run did not go through this node.":badge.key==="waiting"?"Waiting for you to approve or reject.":"This node produced no output."
return '<div class="fo"><div class="fo-top"><span class="fo-badge fo-b-'+badge.key+'">'+E(badge.label)+"</span>"+meta.join("")+"</div>"+(rec.error?'<div class="fo-error">'+E(flowOutTruncate(rec.error,FLOW_FIELD_LIMITS.preview,0).text)+"</div>":"")+(body||'<div class="fo-empty">'+E(idle)+"</div>")+"</div>"
}
// ---- a small standalone binder for hosts other than the inspector (which wires the same helpers into its own draft).
// commit(now) is called after every edit: now=false while typing (debounce it), true for discrete changes.
function flowFieldsBind(root,fields,getConfig,commit,ctx){
const opts=ctx||{}
let focusPath=""
const config=()=>{const c=typeof getConfig==="function"?getConfig():getConfig;return c&&typeof c==="object"?c:{}}
const done=(now)=>{if(typeof commit==="function")commit(!!now)}
const render=()=>{root.innerHTML=flowFieldsHtml(fields,config(),opts)}
const setPath=(path,value)=>{
const hit=flowFieldFind(fields,path)
if(!hit)return null
const cfg=config()
if(!hit.sub)cfg[hit.field.key]=value
else{
if(!Array.isArray(cfg[hit.field.key]))cfg[hit.field.key]=[]
const rows=cfg[hit.field.key]
if(!rows[hit.index]||typeof rows[hit.index]!=="object")rows[hit.index]={}
rows[hit.index][hit.sub.key]=value
}
return hit
}
const feedback=(el,path,value)=>{
const hit=flowFieldFind(fields,path)
if(!hit)return
const msg=flowFieldError(hit.sub||hit.field,value,{})
const box=root.querySelector('[data-ferr="'+(hit.sub?hit.field.key+"."+hit.index:path)+'"]')
if(box)box.textContent=msg?(hit.sub?flowFieldLabel(hit.sub)+": ":"")+msg:""
if(el.classList)el.classList.toggle("invalid",!!msg)
if(el.dataset.grow){const lim=el.dataset.grow.split(",");el.rows=flowFieldGrowRows(el.value,parseInt(lim[0],10),parseInt(lim[1],10))}
}
const pathOf=(el)=>el&&el.dataset?(el.dataset.k||el.dataset.rename||""):""
const onInput=(e)=>{
const el=e.target,path=pathOf(el)
if(!path||opts.readOnly||el.tagName==="SELECT"||el.type==="checkbox"||el.dataset.t==="num")return
if(setPath(path,el.value)){feedback(el,path,el.value);done(false)}
}
const onChange=(e)=>{
const el=e.target,path=pathOf(el)
if(!path||opts.readOnly)return
const hit=flowFieldFind(fields,path)
if(!hit)return
const f=hit.sub||hit.field
let value=el.value
if(el.dataset.t==="bool")value=!!el.checked
else if(el.dataset.t==="num"){value=flowFieldNumber(el.value,f,flowFieldDefault(f));if(String(value)!==el.value)el.value=String(value)}
setPath(path,value)
feedback(el,path,value)
done(true)
if(el.dataset.rr)render()
}
const onClick=(e)=>{
const btn=e.target&&e.target.closest?e.target.closest("[data-act]"):null
if(!btn||btn.disabled||opts.readOnly)return
const act=btn.dataset.act
if(act==="ins-open"){
if(typeof opts.onInsert==="function")opts.onInsert(btn.dataset.for||focusPath,btn)
return
}
const field=flowFieldList(fields).filter((f)=>f.key===btn.dataset.f)[0]
if(!field)return
const i=parseInt(btn.dataset.i,10)
const ok=act==="frow-add"?flowFieldRowAdd(config(),field,opts.taken):act==="frow-del"?flowFieldRowRemove(config(),field,i):act==="frow-up"?flowFieldRowMove(config(),field,i,-1):act==="frow-down"?flowFieldRowMove(config(),field,i,1):false
if(!ok)return
e.preventDefault()
done(true)
render()
}
const onKey=(e)=>{
const el=e.target
if(!el||!el.classList||!el.classList.contains("ff-code")||e.key!=="Tab"||e.shiftKey||e.ctrlKey||e.metaKey||e.altKey||opts.readOnly)return
e.preventDefault()
const edit=flowFieldTabEdit(el.value,el.selectionStart,el.selectionEnd)
el.value=edit.value
el.setSelectionRange(edit.selStart,edit.selEnd)
onInput({target:el})
}
const onFocus=(e)=>{const p=pathOf(e.target);if(p)focusPath=p}
root.addEventListener("input",onInput)
root.addEventListener("change",onChange)
root.addEventListener("click",onClick)
root.addEventListener("keydown",onKey)
root.addEventListener("focusin",onFocus)
render()
return {render:render,validate:()=>flowFieldsValidate(fields,config(),opts),destroy:()=>{
root.removeEventListener("input",onInput)
root.removeEventListener("change",onChange)
root.removeEventListener("click",onClick)
root.removeEventListener("keydown",onKey)
root.removeEventListener("focusin",onFocus)
}}
}
if(typeof module!=="undefined"&&module.exports)module.exports={FLOW_FIELD_VAR_RE,FLOW_FIELD_PORT_RE,FLOW_FIELD_TYPES,FLOW_FIELD_ROW_TYPES,FLOW_FIELD_LIMITS,FLOW_FIELD_PLACEHOLDERS,FLOW_OUT_BADGES,FLOW_OUT_EMPTY,flowFieldEsc,flowFieldSafeKey,flowFieldType,flowFieldList,flowFieldSubs,flowFieldLabel,flowFieldSpec,flowFieldCategory,flowFieldDefault,flowFieldValue,flowFieldOptions,flowFieldVisible,flowFieldControllers,flowFieldNumber,flowFieldMaxRows,flowFieldError,flowFieldsValidate,flowFieldFind,flowFieldPortPaths,flowFieldRowNew,flowFieldRowAdd,flowFieldRowRemove,flowFieldRowMove,flowFieldGrowRows,flowFieldInsertText,flowFieldTabEdit,flowFieldGraphVars,flowFieldGraphPlaceholders,flowFieldInserts,flowFieldInsertMenuHtml,flowFieldAttrs,flowFieldControlHtml,flowFieldRowsHtml,flowFieldHtml,flowFieldsHtml,flowOutRecord,flowOutBadge,flowOutDuration,flowOutText,flowOutTruncate,flowOutCount,flowOutLeaf,flowOutTreeHtml,flowOutSections,flowOutSectionText,flowOutPreHtml,flowOutSectionBody,flowOutHtml,flowFieldsBind}
