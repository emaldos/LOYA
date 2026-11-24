// Chain diagrams: the generic typed-field form and the output preview (UI/js/components/flow-fields.js): rendering of every
// FIELD type, show_if, validation, the row helpers, variable discovery from a graph, the insert menu, output formatting,
// truncation, and that no config or run text reaches the page unescaped. The panel wiring is in tests/js/flow_panels.js.
const fs=require("fs")
const path=require("path")
const ROOT=path.resolve(__dirname,"..","..")
const SRC=fs.readFileSync(path.join(ROOT,"UI","js","components","flow-fields.js"),"utf8")
const CSS=fs.readFileSync(path.join(ROOT,"UI","css","chains-fields.css"),"utf8")
const F=require(path.join(ROOT,"UI","js","components","flow-fields.js"))
let passed=0,failed=0
function check(name,cond,detail){if(cond){passed++;return}failed++;console.log("  FAIL  "+name+(detail?"  ->  "+detail:""))}
function eq(name,a,b){check(name,JSON.stringify(a)===JSON.stringify(b),JSON.stringify(a)+" != "+JSON.stringify(b))}
const XSS="\"><img src=x onerror=alert(1)>'<script>x</script>"
const safe=(html)=>typeof html==="string"&&html.indexOf("<img")===-1&&html.indexOf("<script")===-1&&html.indexOf("onerror=alert(1)>")===-1&&html.indexOf("x</script>")===-1
const count=(html,re)=>(html.match(re)||[]).length
// A hand-written sample in the shape of the generated FLOW_CATALOG (the contract's FIELD schema), used only here.
const HTTP_FIELDS=[
{key:"method",label:"Method",type:"select",options:[{value:"GET",label:"GET"},{value:"POST",label:"POST"}]},
{key:"url",label:"URL",type:"text",help:"Where to send the request.",placeholder:"https://{Domain}/",required:true,max_chars:20},
{key:"headers",label:"Headers",type:"rows",row_label:"header",max_rows:3,rows:[{key:"name",label:"Name",type:"text",required:true},{key:"value",label:"Value",type:"text"}]},
{key:"body",label:"Body",type:"textarea",show_if:{method:["POST","PUT"]}},
{key:"timeout",label:"Timeout (s)",type:"number",min:1,max:300,integer:true},
{key:"verify_tls",label:"Verify TLS",type:"bool"},
{key:"var",label:"Store as",type:"var"}]
const CATALOG={schema:2,categories:[{id:"action",label:"Actions",hint:"Do something"},{id:"logic",label:"Logic"}],types:{
http:{label:"HTTP request",category:"action",icon:"flow-globe",color:"action",input:true,ports:["success","fail"],tones:{success:"pos",fail:"neg"},defaults:{method:"GET",url:"",headers:[],body:"",timeout:30,verify_tls:true,var:"response"},description:"Call a URL.",fields:HTTP_FIELDS},
switch:{label:"Switch",category:"logic",icon:"flow-switch",color:"logic",input:true,ports:[],dynamic:{rows:"cases",name:"name",fixed_key:"default"},defaults:{value:"${last.stdout}",cases:[{name:"case1",op:"equals",value:""}],default:"default",ci:true},
fields:[{key:"value",label:"Value",type:"text"},{key:"cases",label:"Cases",type:"rows",row_label:"case",rows:[{key:"name",label:"Port",type:"port"},{key:"op",label:"When",type:"select",options:[{value:"equals",label:"equals"},{value:"contains",label:"contains"}]},{key:"value",label:"Value",type:"text"},{key:"save",label:"Save as",type:"var"}]},{key:"default",label:"Otherwise",type:"port"},{key:"ci",label:"Ignore case",type:"bool"}]},
math:{label:"Math",category:"math",icon:"flow-math",color:"math",input:true,ports:["out","error"],defaults:{expr:"",var:"result",decimals:-1},fields:[{key:"expr",label:"Expression",type:"code",required:true},{key:"var",label:"Store as",type:"var"},{key:"decimals",label:"Decimals",type:"number",min:-1,max:10,integer:true}]},
start:{label:"Start",category:"input",icon:"play",color:"input",input:false,ports:["out"],defaults:{trigger:"manual"}}}}
const CFG={method:"GET",url:"http://h/${path}",headers:[{name:"Accept",value:"*/*"}],body:"x",timeout:30,verify_tls:true,var:"response"}
// ---- source hygiene
check("source: LF only, no localStorage, no eval",SRC.indexOf("\r")===-1&&!/localStorage|sessionStorage/.test(SRC)&&!/\beval\(|new Function\(/.test(SRC))
check("source: exports for node at the end",/if\(typeof module!=="undefined"&&module\.exports\)module\.exports=\{[^}]+\}\s*$/.test(SRC))
check("source: every exported global is flowField*/flowOut*/FLOW_FIELD_*/FLOW_OUT_*",Object.keys(F).length>50&&Object.keys(F).every((k)=>/^(flowFields?[A-Z]\w*|flowOut[A-Z]\w*|FLOW_FIELD_\w+|FLOW_OUT_\w+)$/.test(k)&&new RegExp("^(?:const|function) "+k+"\\b","m").test(SRC)),Object.keys(F).filter((k)=>!/^(flowFields?[A-Z]\w*|flowOut[A-Z]\w*|FLOW_FIELD_\w+|FLOW_OUT_\w+)$/.test(k)).join(","))
check("source: the catalog global is read at call time only",/typeof FLOW_CATALOG!=="undefined"\?FLOW_CATALOG:null/.test(SRC)&&!/^const FLOW_CATALOG/m.test(SRC))
check("source: nothing touches the DOM outside flowFieldsBind",SRC.slice(0,SRC.indexOf("function flowFieldsBind")).indexOf("document")===-1&&SRC.slice(0,SRC.indexOf("function flowFieldsBind")).indexOf("innerHTML")===-1)
eq("escape",F.flowFieldEsc("<a href=\"x\">'&"),"&lt;a href=&quot;x&quot;&gt;&#39;&amp;")
// ---- catalog lookup
eq("spec: FLOW_CATALOG shape (types) and bridge shape (node_types) both work",[F.flowFieldSpec("http",CATALOG).label,F.flowFieldSpec("http",{node_types:CATALOG.types}).label,F.flowFieldSpec("nope",CATALOG),F.flowFieldSpec("http",null),F.flowFieldSpec("constructor",CATALOG),F.flowFieldSpec("__proto__",CATALOG)],["HTTP request","HTTP request",null,null,null,null])
eq("category: label from the catalog, the id when unknown",[F.flowFieldCategory("action",CATALOG),F.flowFieldCategory("zzz",CATALOG).label],[{id:"action",label:"Actions",hint:"Do something"},"zzz"])
eq("port paths: the fields that name output ports",[F.flowFieldPortPaths(CATALOG.types.switch),F.flowFieldPortPaths(CATALOG.types.http),F.flowFieldPortPaths({dynamic:{rows:"__proto__",name:"x",fixed_key:"a b"}})],[{default:true,"cases.name":true},{},{}])
// ---- defaults, values, visibility
eq("defaults per type",["text","textarea","code","number","bool","select","var","port","rows","weird"].map((t)=>F.flowFieldDefault({key:"k",type:t,min:t==="number"?3:undefined,options:[{value:"a"},{value:"b"}]})),["","","",3,false,"a","","",[],""])
eq("value: config first, then the type defaults, then the field default",[F.flowFieldValue(HTTP_FIELDS[4],{timeout:9},{timeout:30}),F.flowFieldValue(HTTP_FIELDS[4],{},{timeout:30}),F.flowFieldValue(HTTP_FIELDS[4],{timeout:null}),F.flowFieldValue(HTTP_FIELDS[2],{},{headers:[{name:"a"}]})],[9,30,1,[{name:"a"}]])
eq("show_if: listed values, scalars, booleans, several keys",[F.flowFieldVisible(HTTP_FIELDS[3],{method:"GET"}),F.flowFieldVisible(HTTP_FIELDS[3],{method:"POST"}),F.flowFieldVisible({show_if:{on:true}},{on:true}),F.flowFieldVisible({show_if:{on:true}},{on:false}),F.flowFieldVisible({show_if:{a:"x",b:[1,2]}},{a:"x",b:2}),F.flowFieldVisible({show_if:{a:"x",b:[1,2]}},{a:"x",b:3}),F.flowFieldVisible({},null),F.flowFieldVisible({show_if:{a:[""]}},{})],[false,true,true,false,true,false,true,true])
eq("controllers: the keys a show_if depends on",F.flowFieldControllers(HTTP_FIELDS),{method:true})
eq("field list: junk and unsafe keys are dropped, unknown types fall back to text",[F.flowFieldList([null,"x",{key:"__proto__",type:"text"},{key:"a b",type:"text"},{key:"ok",type:"wat"}]).map((f)=>f.key),F.flowFieldType({type:"wat"}),F.flowFieldSubs({rows:[{key:"a",type:"textarea"},{key:"b",type:"port"}]}).map((s)=>s.type)],[["ok"],"text",["text","port"]])
// ---- numbers
eq("number: integer, float, clamp, fallback",[F.flowFieldNumber("12.7",{integer:true}),F.flowFieldNumber("12.7",{}),F.flowFieldNumber("999",{min:1,max:300,integer:true}),F.flowFieldNumber("-5",{min:-1,max:10,integer:true}),F.flowFieldNumber("abc",{min:1,max:300},30),F.flowFieldNumber("",{min:2}),F.flowFieldNumber("",{}),F.flowFieldNumber(2.6,{integer:true})],[12,12.7,300,-1,30,2,0,3])
// ---- validation
eq("error: required, numbers, var, port, select, max_chars",[F.flowFieldError(HTTP_FIELDS[1],""),F.flowFieldError(HTTP_FIELDS[1],"",{required:false}),F.flowFieldError(HTTP_FIELDS[1],"http://ok"),F.flowFieldError(HTTP_FIELDS[1],"x".repeat(21)),F.flowFieldError(HTTP_FIELDS[4],"0"),F.flowFieldError(HTTP_FIELDS[4],"301"),F.flowFieldError(HTTP_FIELDS[4],"1.5"),F.flowFieldError(HTTP_FIELDS[4],"abc"),F.flowFieldError(HTTP_FIELDS[4],"30"),F.flowFieldError(HTTP_FIELDS[4],""),F.flowFieldError(HTTP_FIELDS[0],"PATCH"),F.flowFieldError(HTTP_FIELDS[0],"POST"),F.flowFieldError(HTTP_FIELDS[5],"whatever")],["Required","","","Longer than 20 characters","At least 1","At most 300","Whole numbers only","Enter a number","","","Pick one of the listed options","",""])
eq("error: variable names follow VAR_RE",["tgt","_a1","a".repeat(40),"1a","a-b","a b","a".repeat(41),""].map((v)=>F.flowFieldError({key:"var",type:"var"},v)===""),[true,true,true,false,false,false,false,true])
eq("error: port names follow PORT_RE and must be free",["out","a-b_1","a".repeat(24),"a b","a".repeat(25),"é"].map((v)=>F.flowFieldError({key:"p",type:"port"},v)==="").concat([F.flowFieldError({key:"p",type:"port"},"web",{taken:["web"]})]),[true,true,true,false,false,false,"'web' is already used on this node"])
eq("error: rows count",[F.flowFieldError(HTTP_FIELDS[2],[{},{},{},{}]),F.flowFieldError(HTTP_FIELDS[2],[{}]),F.flowFieldError({key:"r",type:"rows",required:true,row_label:"case"},[])],["At most 3 rows","","Add at least one case"])
eq("validate: hidden fields are skipped, row cells are checked, duplicate ports are caught",[F.flowFieldsValidate(HTTP_FIELDS,{method:"GET",url:"",headers:[{name:"",value:"x"}],body:"",timeout:999,var:"9x"}).map((e)=>e.path),F.flowFieldsValidate(HTTP_FIELDS,CFG),F.flowFieldsValidate(CATALOG.types.switch.fields,{value:"",cases:[{name:"a",op:"equals",value:""},{name:"a",op:"equals",value:""},{name:"b c",op:"x"}],default:"default"}).map((e)=>e.path)],[["url","headers.0.name","timeout","var"],[],["cases.0.name","cases.1.name","cases.2.name","cases.2.op"]])
eq("find: a field, a row cell, nothing else",[F.flowFieldFind(HTTP_FIELDS,"url").field.key,F.flowFieldFind(HTTP_FIELDS,"headers.2.value").sub.key,F.flowFieldFind(HTTP_FIELDS,"headers.2.value").index,F.flowFieldFind(HTTP_FIELDS,"headers.x.value"),F.flowFieldFind(HTTP_FIELDS,"headers.0.nope"),F.flowFieldFind(HTTP_FIELDS,"url.0.x"),F.flowFieldFind(HTTP_FIELDS,"@title"),F.flowFieldFind(HTTP_FIELDS,"__proto__")],["url","value",2,null,null,null,null,null])
// ---- rows
const SW=CATALOG.types.switch.fields[1]
eq("row new: sub-field defaults and a free port name",[F.flowFieldRowNew(SW,[{name:"case1"}]),F.flowFieldRowNew(SW,[{name:"case1"}],["case2"]).name,F.flowFieldRowNew(HTTP_FIELDS[2],[]),F.flowFieldRowNew({key:"r",type:"rows",row_label:"my <case>",rows:[{key:"p",type:"port"}]},[]).p],[{name:"case2",op:"equals",value:"",save:""},"case3",{name:"",value:""},"mycase1"])
const rc={headers:[{name:"a"},{name:"b"}]}
eq("row add: appends until max_rows, creates the list when missing",[F.flowFieldRowAdd(rc,HTTP_FIELDS[2]),F.flowFieldRowAdd(rc,HTTP_FIELDS[2]),rc.headers.length,(()=>{const c={};F.flowFieldRowAdd(c,HTTP_FIELDS[2]);return c.headers})(),F.flowFieldRowAdd(null,HTTP_FIELDS[2]),F.flowFieldRowAdd({},{key:"__proto__",type:"rows"})],[true,false,3,[{name:"",value:""}],false,false])
eq("row move / remove: inside bounds only",(()=>{const c={headers:[{name:"a"},{name:"b"},{name:"c"}]};const r=[F.flowFieldRowMove(c,HTTP_FIELDS[2],0,1),F.flowFieldRowMove(c,HTTP_FIELDS[2],2,1),F.flowFieldRowMove(c,HTTP_FIELDS[2],0,-1),F.flowFieldRowMove(c,HTTP_FIELDS[2],NaN,1),F.flowFieldRowRemove(c,HTTP_FIELDS[2],1),F.flowFieldRowRemove(c,HTTP_FIELDS[2],9),F.flowFieldRowRemove(c,HTTP_FIELDS[2],NaN)];return [r,c.headers.map((h)=>h.name)]})(),[[true,false,false,false,true,false,false],["b","c"]])
eq("max rows: the field's own, or the shared cap",[F.flowFieldMaxRows({max_rows:5}),F.flowFieldMaxRows({}),F.flowFieldMaxRows({max_rows:-1})],[5,F.FLOW_FIELD_LIMITS.rows,F.FLOW_FIELD_LIMITS.rows])
// ---- text helpers
eq("grow rows: between the limits",[F.flowFieldGrowRows("",2,14),F.flowFieldGrowRows("a\nb\nc\nd",2,14),F.flowFieldGrowRows("x\n".repeat(40),2,14),F.flowFieldGrowRows(null,4,22)],[2,4,14,4])
eq("insert text: at the caret, over a selection, at the end when unknown, clamped",[F.flowFieldInsertText("ping host",5,9,"{IPv4}"),F.flowFieldInsertText("ab",1,1,"X"),F.flowFieldInsertText("ab",undefined,undefined,"X"),F.flowFieldInsertText("ab",99,-4,"X"),F.flowFieldInsertText(null,0,0,"X")],[{value:"ping {IPv4}",caret:11},{value:"aXb",caret:2},{value:"abX",caret:3},{value:"abX",caret:3},{value:"X",caret:1}])
eq("tab edit: two spaces at the caret",(()=>{const e=F.flowFieldTabEdit("ab",1,1);return [e.value,e.selStart,e.text]})(),["a  b",3,"  "])
// ---- variable discovery
const GRAPH={nodes:[
{id:"n1",type:"start",title:"Start",config:{trigger:"manual"}},
{id:"n2",type:"http",title:"Fetch",config:{method:"GET",url:"http://{Domain}/x?u={User Name}&v=${keep}",var:"response"}},
{id:"n3",type:"parse",title:"Ports",config:{mode:"regex",var:"parsed",assign:[{var:"port",from:"group:1"},{var:"9bad",from:"group:2"},null]}},
{id:"n4",type:"set",title:"Vars",config:{assign:[{var:"proto",value:"tcp"},{var:"port",value:"1"}]}},
{id:"n5",type:"foreach",title:"Loop",config:{items:"${parsed}",item_var:"host"}},
{id:"n6",type:"switch",title:"Route",config:{value:"",cases:[{name:"a",save:"picked"},{name:"b",save:XSS}],default:"default"}},
{id:"n7",type:"math",title:XSS,config:{expr:"1+1",var:"total"}},
{id:"n8",type:"comment",title:"Note",config:{text:"{NotAPlaceholder is fine}",var:"ignored not a name"}},
null,{id:"bad id",type:"command",config:{commands:[{text:"nmap {IPv4} ${raw:x}"}]}}]}
eq("graph vars: catalog var fields, row var cells and the legacy keys, once each, valid names only",F.flowFieldGraphVars(GRAPH,CATALOG).map((v)=>v.name+"@"+v.node),["response@n2","parsed@n3","port@n3","proto@n4","host@n5","index@n5","picked@n6","total@n7"])
eq("graph vars: without a catalog the well-known keys still work",F.flowFieldGraphVars(GRAPH,null).map((v)=>v.name),["response","parsed","port","proto","host","index","total"])
eq("graph vars: junk graphs",[F.flowFieldGraphVars(null),F.flowFieldGraphVars({nodes:"x"}),F.flowFieldGraphVars({nodes:[{id:"a",config:"x"}]})],[[],[],[]])
eq("graph placeholders: {Element} names used anywhere, never ${var}",F.flowFieldGraphPlaceholders(GRAPH),["Domain","User Name","NotAPlaceholder is fine","IPv4"])
const INS=F.flowFieldInserts(GRAPH,"n2",{catalog:CATALOG})
const insValues=INS.map((i)=>i.value)
check("inserts: previous output, loop values, placeholders, other nodes' variables",["${last.stdout}","${last.parsed}","${item}","${index}","{IPv4}","{Domain}","${parsed}","${port}","${host}","${total}","${nodes.n3.stdout}"].every((v)=>insValues.indexOf(v)!==-1),insValues.join(" "))
check("inserts: not the node's own variable, its own output, comments or odd ids",insValues.indexOf("${response}")===-1&&insValues.indexOf("${nodes.n2.stdout}")===-1&&insValues.indexOf("${nodes.n8.stdout}")===-1&&!insValues.some((v)=>/bad id/.test(v)))
eq("inserts: grouped in a fixed order",INS.map((i)=>i.group).filter((g,i,a)=>a.indexOf(g)===i),["Previous node","Loop","Live target","Variables","Output of a node"])
eq("inserts: placeholders handed in replace the defaults",F.flowFieldInserts(null,"",{placeholders:["LHOST","bad{name"]}).filter((i)=>i.group==="Live target").map((i)=>i.value),["{LHOST}"])
const MENU=F.flowFieldInsertMenuHtml(INS)
check("insert menu: one button per value, group titles, escaped",count(MENU,/data-act="ins-pick"/g)===INS.length&&count(MENU,/class="ff-menu-group"/g)===5&&/data-v="\$\{last\.stdout\}"/.test(MENU)&&safe(MENU))
check("insert menu: hostile titles and values stay text",safe(F.flowFieldInsertMenuHtml([{group:XSS,value:XSS,label:XSS,hint:XSS}]))&&/Nothing to insert/.test(F.flowFieldInsertMenuHtml([])))
// ---- rendering
const FORM=F.flowFieldsHtml(HTTP_FIELDS,CFG,{defaults:CATALOG.types.http.defaults})
check("form: one wrapper per visible field, hidden ones left out",count(FORM,/class="ff-field /g)===6&&!/data-field="body"/.test(FORM)&&/^<div class="ff-form">/.test(FORM))
check("form: show_if shows the field once its controller matches",/data-field="body"/.test(F.flowFieldsHtml(HTTP_FIELDS,Object.assign({},CFG,{method:"POST"}))))
check("text: input with value, placeholder, maxlength, data-k, monospace when it holds an expression",/<input class="fi-input ff-text ff-expr" type="text" value="http:\/\/h\/\$\{path\}" data-ff="1" data-t="str" aria-label="URL" data-k="url" placeholder="https:\/\/\{Domain\}\/" maxlength="20"/.test(FORM),FORM.slice(FORM.indexOf('data-field="url"'),FORM.indexOf('data-field="url"')+700))
check("text: required marker, help text and the insert button",/<span class="ff-label">URL<span class="ff-req" title="Required">\*<\/span><\/span><button type="button" class="ff-ins" data-act="ins-open" data-for="url"/.test(FORM)&&/<div class="ff-help">Where to send the request\.<\/div>/.test(FORM))
check("select: app select styling, the current option selected, re-render flag on a controller",/<select class="fi-select ff-select" data-ff="1" data-t="str" aria-label="Method" data-k="method" data-rr="1"><option value="GET" selected>GET<\/option><option value="POST">POST<\/option><\/select>/.test(FORM))
check("select: an unknown stored value is kept and labelled",/<option value="PATCH" selected>PATCH \(unknown\)<\/option>/.test(F.flowFieldHtml(HTTP_FIELDS[0],{method:"PATCH"})))
check("select: plain string options work",/<option value="a" selected>a<\/option><option value="b">b<\/option>/.test(F.flowFieldHtml({key:"s",type:"select",options:["a","b"]},{s:"a"})))
check("number: min, max, step and the integer flag",/<input class="fi-input ff-num" type="number" value="30" min="1" max="300" step="1" data-int="1" data-ff="1" data-t="num" aria-label="Timeout \(s\)" data-k="timeout"/.test(FORM)&&/ff-t-number ff-half/.test(FORM))
check("number: floats use step any and carry no integer flag",/step="any" data-ff/.test(F.flowFieldHtml({key:"n",type:"number"},{n:1.5})))
check("bool: the themed switch, checked from the config, no separate label row",/<label class="fi-switch ff-switch"><input type="checkbox" data-ff="1" data-t="bool" aria-label="Verify TLS" data-k="verify_tls" checked><span class="fi-switch-track"><\/span><span class="fi-switch-label">Verify TLS<\/span><\/label>/.test(FORM)&&!/checked/.test(F.flowFieldHtml(HTTP_FIELDS[5],{verify_tls:false}))&&!/ff-head/.test(F.flowFieldHtml(HTTP_FIELDS[5],{})))
check("var: monospace input between ${ and }, 40 characters at most",/<span class="ff-affix"><span class="ff-affix-pre" aria-hidden="true">\$\{<\/span><input class="fi-input fi-mono ff-var" type="text" value="response" maxlength="40"[^>]*data-k="var"/.test(FORM))
check("var: an invalid stored name is flagged in the markup",/class="ff-affix invalid"/.test(F.flowFieldHtml(HTTP_FIELDS[6],{var:"9x"}))&&/data-ferr="var">Start with a letter/.test(F.flowFieldHtml(HTTP_FIELDS[6],{var:"9x"})))
check("textarea: grows with its lines, within limits",/<textarea class="fi-input fi-area ff-area" rows="3" data-grow="2,14"[^>]*data-k="body"[^>]*>a\nb\nc<\/textarea>/.test(F.flowFieldHtml(HTTP_FIELDS[3],{method:"POST",body:"a\nb\nc"})))
const CODE=F.flowFieldHtml(CATALOG.types.math.fields[0],{expr:"1 < 2 && \"x\""})
check("code: monospace, unwrapped, escaped, with the insert button",/<textarea class="fi-input fi-area fi-mono ff-code" wrap="off" rows="4" data-grow="4,22"/.test(CODE)&&/>1 &lt; 2 &amp;&amp; &quot;x&quot;<\/textarea>/.test(CODE)&&/data-act="ins-open" data-for="expr"/.test(CODE))
check("required: an empty required field is not shouted at until asked",!/>Required</.test(F.flowFieldHtml(HTTP_FIELDS[1],{url:""}))&&/data-ferr="url">Required</.test(F.flowFieldHtml(HTTP_FIELDS[1],{url:""},{showRequired:true})))
check("placeholder and help are escaped",safe(F.flowFieldHtml({key:"k",label:XSS,type:"text",help:XSS,placeholder:XSS},{k:XSS})))
// rows
const ROWS=F.flowFieldRowsHtml(HTTP_FIELDS[2],{headers:[{name:"Accept",value:"*/*"},{name:"",value:"${tok}"}]},{})
check("rows: a compact grid, one line per row, cells addressed by path",count(ROWS,/<div class="ff-row ff-cols-2" data-i="/g)===2&&/data-k="headers\.0\.name"/.test(ROWS)&&/data-k="headers\.1\.value"/.test(ROWS)&&/class="ff-row ff-row-head ff-cols-2"/.test(ROWS)&&/<span class="ff-col-label">Name<span class="ff-req">\*<\/span><\/span>/.test(ROWS))
check("rows: move and remove per row, first cannot go up, last cannot go down",count(ROWS,/data-act="frow-up"/g)===2&&/data-act="frow-up" data-f="headers" data-i="0" title="Move up" aria-label="Move up" disabled/.test(ROWS)&&/data-act="frow-down" data-f="headers" data-i="1" title="Move down" aria-label="Move down" disabled/.test(ROWS)&&!/data-act="frow-del"[^>]*disabled/.test(ROWS))
check("rows: add button, the count, and one insert button for the block",/data-act="frow-add" data-f="headers"><i class="icon icon-add"><\/i><span>Add header<\/span>/.test(ROWS)&&/<span class="ff-count">2 of 3<\/span>/.test(ROWS)&&/data-act="ins-open" data-rows="headers"/.test(ROWS))
check("rows: add is disabled at max_rows",/data-act="frow-add" data-f="headers" disabled/.test(F.flowFieldRowsHtml(HTTP_FIELDS[2],{headers:[{},{},{}]},{})))
check("rows: empty state",/<div class="ff-rows-empty">No header yet\.<\/div>/.test(F.flowFieldRowsHtml(HTTP_FIELDS[2],{headers:[]},{}))&&!/ff-row-head/.test(F.flowFieldRowsHtml(HTTP_FIELDS[2],{},{})))
const SWROWS=F.flowFieldsHtml(CATALOG.types.switch.fields,{value:"x",cases:[{name:"web",op:"equals",value:"80"},{name:"web",op:"contains",value:""}],default:"other",ci:true},{portPaths:F.flowFieldPortPaths(CATALOG.types.switch)})
check("rows: port cells that name real ports rename (data-rename), others edit (data-k)",/data-rename="cases\.0\.name"/.test(SWROWS)&&/data-rename="default"/.test(SWROWS)&&!/data-k="cases\.0\.name"/.test(SWROWS)&&/data-k="cases\.0\.op"/.test(SWROWS)&&/data-k="default"/.test(F.flowFieldsHtml(CATALOG.types.switch.fields,{default:"other"})))
check("rows: a duplicate port is reported under its row, up to four columns",/data-ferr="cases\.1">Port: &#39;web&#39; is already used on this node</.test(SWROWS)&&/ff-cols-4/.test(SWROWS)&&/ff-cell-bool|ff-cell-select/.test(SWROWS))
check("rows: hostile cell values and row labels are escaped",safe(F.flowFieldRowsHtml({key:"r",type:"rows",row_label:XSS,rows:[{key:"a",label:XSS,type:"text"},{key:"b",label:XSS,type:"select",options:[{value:XSS,label:XSS}]},{key:"c",label:XSS,type:"bool"}]},{r:[{a:XSS,b:XSS,c:true},XSS,null]},{})))
// read-only, filters, empty
const RO=F.flowFieldsHtml(HTTP_FIELDS,CFG,{readOnly:true})
check("read-only: every control and button is disabled",count(RO,/<(input|select|textarea)[^>]*>/g)===count(RO,/<(input|select|textarea)[^>]* disabled[^>]*>/g)&&count(RO,/<button[^>]*>/g)===count(RO,/<button[^>]* disabled[^>]*>/g))
check("only: a filter picks the fields of one tab",count(F.flowFieldsHtml(HTTP_FIELDS,CFG,{only:(f)=>f.key==="timeout"}),/class="ff-field /g)===1)
eq("empty: a message, a custom one, or nothing",[/This node has no parameters\./.test(F.flowFieldsHtml([],{})),/ff-empty">Nope</.test(F.flowFieldsHtml(null,null,{empty:"Nope"})),F.flowFieldsHtml([],{},{empty:""})],[true,true,""])
check("form: junk in, safe markup out",safe(F.flowFieldsHtml([{key:"a",label:XSS,type:"select",options:[XSS,{value:XSS}]},{key:"b",type:"rows",rows:XSS},{key:"c",type:"number",min:XSS,max:XSS},{key:"d",type:"code"}],{a:XSS,b:XSS,c:XSS,d:{x:XSS}})))
// every type of a real catalog, when the generated file is there
const CATALOG_FILE=path.join(ROOT,"UI","js","components","flow-catalog.js")
if(fs.existsSync(CATALOG_FILE)){
const REAL=require(CATALOG_FILE).FLOW_CATALOG
const typed=Object.keys(REAL.types||{}).filter((t)=>Array.isArray(REAL.types[t].fields))
const poison=(v)=>typeof v==="string"?XSS:Array.isArray(v)?v.map(poison):v&&typeof v==="object"?Object.keys(v).reduce((o,k)=>{o[k]=poison(v[k]);return o},{}):v
check("generated catalog: every typed node renders its defaults",typed.length>0&&typed.every((t)=>/class="ff-form"|class="ff-empty"/.test(F.flowFieldsHtml(REAL.types[t].fields,REAL.types[t].defaults,{defaults:REAL.types[t].defaults}))),typed.filter((t)=>!/ff-form|ff-empty/.test(F.flowFieldsHtml(REAL.types[t].fields,REAL.types[t].defaults))).join(","))
check("generated catalog: hostile config never reaches the markup",typed.every((t)=>safe(F.flowFieldsHtml(REAL.types[t].fields,poison(REAL.types[t].defaults),{}))))
check("generated catalog: every field type is one the renderer knows, and the defaults validate",typed.every((t)=>REAL.types[t].fields.every((f)=>F.FLOW_FIELD_TYPES.indexOf(f.type)!==-1&&(f.type!=="rows"||(f.rows||[]).every((s)=>F.FLOW_FIELD_ROW_TYPES.indexOf(s.type)!==-1)))&&F.flowFieldsValidate(REAL.types[t].fields,REAL.types[t].defaults,{required:false}).length===0),typed.map((t)=>t+":"+F.flowFieldsValidate(REAL.types[t].fields,REAL.types[t].defaults,{required:false}).map((e)=>e.path+" "+e.message).join("/")).filter((x)=>!/:$/.test(x)).join("; "))
}
// ---- output preview
eq("record: only an own entry of status.nodes",[F.flowOutRecord({nodes:{n2:{state:"success"}}},"n2"),F.flowOutRecord({nodes:{n2:{state:"success"}}},"n9"),F.flowOutRecord(null,"n2"),F.flowOutRecord({nodes:{}},"constructor"),F.flowOutRecord({nodes:{n2:"x"}},"n2")],[{state:"success"},null,null,null,null])
const EDGES=[{id:"e1",from:"n2",port:"fail",to:"n3"},{id:"e2",from:"n4",port:"success",to:"n3"}]
eq("badge: run states mapped to the panel's badges",["pending","running","success","fail","skipped","waiting","planned","weird",undefined].map((s)=>F.flowOutBadge({state:s},[],"n2").key),["queued","running","ok","fail","skipped","waiting","planned","queued","queued"])
eq("badge: a failure whose branch is wired is a handled failure",[F.flowOutBadge({state:"fail",branch:"fail"},EDGES,"n2"),F.flowOutBadge({state:"fail",branch:"fail"},EDGES,"n4").key,F.flowOutBadge({state:"fail",branch:""},EDGES,"n2").key,F.flowOutBadge({state:"fail",branch:"fail"},null,"n2").key,F.flowOutBadge({state:"success",branch:"fail"},EDGES,"n2").key],[{key:"warn",label:"Failed, handled"},"fail","fail","fail","ok"])
eq("duration",[F.flowOutDuration(0),F.flowOutDuration(42.4),F.flowOutDuration(1234),F.flowOutDuration(15300),F.flowOutDuration(75000),F.flowOutDuration(3723000),F.flowOutDuration(null),F.flowOutDuration(-1),F.flowOutDuration("x")],["0 ms","42 ms","1.2 s","15 s","1m 15s","1h 02m","","",""])
eq("text: strings stay, values are pretty-printed, nothing throws",[F.flowOutText("a"),F.flowOutText(null),F.flowOutText({a:[1]}),F.flowOutText(7),(()=>{const o={};o.self=o;return typeof F.flowOutText(o)})()],["a","","{\n  \"a\": [\n    1\n  ]\n}","7","string"])
eq("truncate: by characters, by lines, never inside a surrogate pair",[F.flowOutTruncate("abcdef",4,0),F.flowOutTruncate("a\nb\nc\nd",100,2),F.flowOutTruncate("abc",10,5),F.flowOutTruncate("ab😀cd",3,0).text,F.flowOutTruncate(null,5,0),F.flowOutTruncate("x".repeat(5000)).text.length],[{text:"abcd",more:true,total:6,hidden:2},{text:"a\nb",more:true,total:7,hidden:4},{text:"abc",more:false,total:3,hidden:0},"ab",{text:"",more:false,total:0,hidden:0},F.FLOW_FIELD_LIMITS.preview])
eq("count: lines of a text",[F.flowOutCount("a\nb\n"),F.flowOutCount("a"),F.flowOutCount("")],["2 lines","1 line",""])
const REC={state:"success",visits:3,branch:"success",duration_ms:1234,error:"",seq:9,output:{stdout:"line1\nline2 "+XSS,stderr:"warn "+XSS,exit_code:0,parsed:{hosts:[{ip:"10.0.0.5",open:[22,80],up:true,note:null,name:XSS}],[XSS]:1},vars_set:{scan:{a:1},[XSS]:XSS},resolved:["nmap 10.0.0.5 "+XSS],http:{status:200,url:"http://h/"+XSS,elapsed_ms:87,headers:{"content-type":XSS}},trace:[{branch:XSS,matched:true,conditions:[{result:true,text:XSS,error:XSS}]}]}}
eq("sections: what the record has, in display order",F.flowOutSections(REC).map((s)=>s.id+":"+s.kind),["http:http","stdout:text","stderr:text","parsed:json","vars:kv","resolved:list","trace:trace"])
eq("sections: empty values are left out",[F.flowOutSections({output:{stdout:"",stderr:null,parsed:null,vars_set:{},resolved:[],http:{}}}),F.flowOutSections(null),F.flowOutSections({output:{parsed:0,stdout:"0"}}).map((s)=>s.id),F.flowOutSections({output:{parsed:"text",stdout:"x"}}).map((s)=>s.kind)],[[],[],["stdout","parsed"],["text","text"]])
const OUT=F.flowOutHtml(REC,{nodeId:"n2",edges:EDGES})
check("output: everything from the run is escaped",safe(OUT))
check("output: status badge, duration, visits, branch and exit code",/<span class="fo-badge fo-b-ok">OK<\/span>/.test(OUT)&&/title="Duration">1\.2 s</.test(OUT)&&/>3 visits</.test(OUT)&&/took <b class="fo-branch">success<\/b>/.test(OUT)&&/>exit 0</.test(OUT))
check("output: one collapsible section each, with counts and copy buttons",count(OUT,/<details class="fo-sec" data-sec="/g)===7&&/data-sec="stdout" open><summary><span class="fo-sec-title">Output<\/span><span class="fo-sec-count">2 lines<\/span>/.test(OUT)&&count(OUT,/data-act="out-copy"/g)===6&&/data-sec="vars"><summary>/.test(OUT))
check("output: parsed data as a tree",/<div class="fo-tree"><details class="fo-node" open><summary><span class="fo-k fo-k-root">object<\/span><span class="fo-n">\{2\}<\/span>/.test(OUT)&&/<span class="fo-k">ip<\/span><span class="fo-v fo-v-str">"10\.0\.0\.5"<\/span>/.test(OUT)&&/<span class="fo-k">up<\/span><span class="fo-v fo-v-bool">true<\/span>/.test(OUT)&&/<span class="fo-v fo-v-null">null<\/span>/.test(OUT)&&/<span class="fo-k">open<\/span><span class="fo-n">\[2\]<\/span>/.test(OUT))
check("output: HTTP status, variables and resolved commands",/<span class="fo-badge fo-b-ok">200<\/span><span class="fo-meta">87 ms<\/span>/.test(OUT)&&/<span class="fo-k">scan<\/span><span class="fo-v fo-v-str">"\{&quot;a&quot;:1\}"<\/span>/.test(OUT)&&/<pre class="fo-pre fo-cmd">nmap 10\.0\.0\.5 /.test(OUT))
check("output: HTTP error statuses are painted as failures",/fo-b-fail">503</.test(F.flowOutHtml({state:"fail",output:{http:{status:503}}},{}))&&/fo-b-queued">no status</.test(F.flowOutHtml({state:"fail",output:{http:{url:"x"}}},{})))
eq("copy text: the whole section, never the preview",[F.flowOutSectionText(REC,"stdout"),F.flowOutSectionText(REC,"resolved"),JSON.parse(F.flowOutSectionText(REC,"parsed")).hosts[0].ip,F.flowOutSectionText(REC,"nope"),F.flowOutSectionText({output:{stdout:"x".repeat(9000)}},"stdout").length],["line1\nline2 "+XSS,"nmap 10.0.0.5 "+XSS,"10.0.0.5","",9000])
const BIG={state:"success",output:{stdout:"Q".repeat(9000)+XSS}}
const bigHtml=F.flowOutHtml(BIG,{})
check("output: long text is cut, with a show-more control",count(bigHtml,/Q/g)===F.FLOW_FIELD_LIMITS.preview&&/data-act="out-more" data-sec="stdout">Show more \(50\d\d more characters\)</.test(bigHtml)&&safe(bigHtml))
const fullHtml=F.flowOutHtml(BIG,{full:{stdout:true}})
check("output: show more reveals the rest, still escaped",count(fullHtml,/Q/g)===9000&&!/data-act="out-more"/.test(fullHtml)&&safe(fullHtml))
check("output: many lines are cut by line count",(F.flowOutHtml({state:"success",output:{stdout:"l\n".repeat(500)}},{}).match(/<pre class="fo-pre">([^<]*)<\/pre>/)||["",""])[1].split("\n").length===F.FLOW_FIELD_LIMITS.previewLines)
check("output: even 'show more' has a hard cap",count(F.flowOutHtml({state:"success",output:{stdout:"z".repeat(F.FLOW_FIELD_LIMITS.full+500)}},{full:{stdout:true}}),/z/g)===F.FLOW_FIELD_LIMITS.full)
check("output: the open state of a section follows the caller",/data-sec="stdout"><summary>/.test(F.flowOutHtml(REC,{open:{stdout:false}}))&&/data-sec="vars" open>/.test(F.flowOutHtml(REC,{open:{vars:true}})))
check("output: a failed node opens its error output and shows the error text",/data-sec="stderr" open>/.test(F.flowOutHtml({state:"fail",error:"boom "+XSS,output:{stdout:"a",stderr:"b"}},{}))&&/<div class="fo-error">boom /.test(F.flowOutHtml({state:"fail",error:"boom "+XSS,output:{}},{}))&&safe(F.flowOutHtml({state:"fail",error:XSS,branch:XSS,output:{exit_code:XSS}},{})))
eq("output: empty states",[/Run or dry-run the chain to see this node&#39;s output/.test(F.flowOutHtml(null,{})),/not part of the last run/.test(F.flowOutHtml(null,{hasRun:true})),/not part of the last run/.test(F.flowOutHtml(null,{})),/This node has not run yet\./.test(F.flowOutHtml({state:"pending"},{})),/output appears here/.test(F.flowOutHtml({state:"running",output:{}},{})),/did not go through this node/.test(F.flowOutHtml({state:"skipped"},{})),/fo-b-planned">Would run</.test(F.flowOutHtml({state:"planned",output:{resolved:["id"]}},{}))],[true,true,false,true,true,true,true])
const wide={};for(let i=0;i<2000;i++)wide["k"+i]={v:i}
const TREE=F.flowOutTreeHtml(wide)
check("tree: a huge value stops at the node budget and says so",count(TREE,/class="fo-(leaf|node)"/g)<=F.FLOW_FIELD_LIMITS.treeNodes&&/more not shown - Copy has everything/.test(TREE))
let deep={v:XSS};for(let i=0;i<40;i++)deep={d:deep}
check("tree: deep values stop at the depth limit, strings are cut, keys escaped",/deeper levels not shown/.test(F.flowOutTreeHtml(deep))&&safe(F.flowOutTreeHtml({[XSS]:[XSS,{[XSS]:XSS}]}))&&/\.\.\."<\/span>/.test(F.flowOutTreeHtml({s:"q".repeat(1000)}))&&count(F.flowOutTreeHtml({s:"q".repeat(1000)}),/q/g)===F.FLOW_FIELD_LIMITS.value)
eq("tree: primitives and empty containers are leaves",[F.flowOutTreeHtml(5),F.flowOutTreeHtml([],null,0,"list"),/fo-node/.test(F.flowOutTreeHtml({a:{}}))&&/<span class="fo-k">a<\/span><span class="fo-n">\{0\}<\/span>/.test(F.flowOutTreeHtml({a:{}}))],['<div class="fo-leaf"><span class="fo-v fo-v-num">5</span></div>','<div class="fo-leaf"><span class="fo-k">list</span><span class="fo-n">[0]</span></div>',true])
// ---- stylesheet
check("css: LF only, no hard-coded colours",CSS.indexOf("\r")===-1&&!/#[0-9a-fA-F]{3,8}\b/.test(CSS)&&!/\brgba?\(|\bhsla?\(/.test(CSS))
check("css: every user-select has its -webkit- twin",(CSS.match(/[^{}]+\{[^{}]*\}/g)||[]).every((r)=>(r.match(/(?:^|[;{])user-select:/g)||[]).length===(r.match(/-webkit-user-select:/g)||[]).length))
check("css: colours and fonts come from the theme tokens",["--text","--text-dim","--glass-border","--glass-bg","--accent-a","--accent-a-soft","--danger","--pal-success","--pal-warn-text","--font-mono"].every((t)=>CSS.indexOf("var("+t+")")!==-1))
check("css: buttons and the title input inherit the app font",[".fi-title",".fi-tab",".ff-menu-item",".fo-copy,.fo-more"].every((sel)=>new RegExp(sel.replace(/[.,]/g,"\\$&")+"\\{[^}]*font-family:inherit").test(CSS))&&/\.ff-ins\{[^}]*font-family:var\(--font-mono\)/.test(CSS))
check("css: no :has() and no HTML5 drag styles",!/:has\(/.test(CSS)&&!/-webkit-user-drag/.test(CSS))
check("css: glass variants keyed off data-style, in this file",(CSS.match(/^html:where\(\[data-style="glass"\]\) /gm)||[]).length>=3)
const emitted=new Set();(SRC.match(/\b(?:ff|fo)-[a-z0-9-]+/g)||[]).forEach((c)=>{if(!/-$/.test(c))emitted.add(c)})
const dynamicCls=/^(ff-t-|ff-cell-|ff-cols-|fo-b-|fo-v-)/
const hooks=["ff-text","ff-select","ff-check","ff-add","ff-required","ff-row-head","ff-form","fo-kv-row","fo-node","fo-sec-title","fo-leaf"]
const unstyled=[...emitted].filter((c)=>CSS.indexOf("."+c)===-1&&!dynamicCls.test(c)&&hooks.indexOf(c)===-1)
check("css: every class the renderer emits is styled",unstyled.length===0,unstyled.join(","))
check("css: every badge and every row width has a rule",Object.keys(F.FLOW_OUT_BADGES).every((k)=>CSS.indexOf(".fo-b-"+k)!==-1)&&[1,2,3,4].every((n)=>CSS.indexOf(".ff-cols-"+n+"{")!==-1)&&F.FLOW_FIELD_LIMITS.cols===4)
console.log("\nflow_fields: "+passed+" passed, "+failed+" failed")
process.exit(failed?1:0)
