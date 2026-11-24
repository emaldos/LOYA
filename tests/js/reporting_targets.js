// Report scope from Targets: pure helpers (UI/js/pages/reporting_targets.js), the reference chip in the sanitiser and in Markdown,
// and the wiring of the editors. Run: node tests/js/reporting_targets.js
const path=require("path")
const fs=require("fs")
const ROOT=path.resolve(__dirname,"..","..")
const RC=require(path.join(ROOT,"UI","js","pages","reporting_core.js"))
const T=require(path.join(ROOT,"UI","js","pages","reporting_targets.js"))
const read=(...p)=>fs.readFileSync(path.join(ROOT,...p),"utf8")
let passed=0,failed=0
function check(name,cond,detail){if(cond){passed++;return}failed++;console.log("  FAIL  "+name+(detail!==undefined?"  ->  "+(typeof detail==="string"?detail:JSON.stringify(detail)):""))}
const eq=(a,b)=>JSON.stringify(a)===JSON.stringify(b)
const tv=(uid,key,text)=>`<span class="rpt-tv" data-target="${uid}" data-key="${key}">${text===undefined?"stale":text}</span>`
const link=(over)=>Object.assign({uid:"u1",target_id:"t1",profile_id:"default",profile_name:"Default",name:"web01",snapshot:{values:{IPv4:"10.0.0.5",URL:"https://shop.acme.example",Port:"443"},engagement_status:"in_progress"},allowed_secret_keys:[],secret_keys:["Password"],state:"ok",changed_keys:[]},over||{})

// ---- the protected-key rule (must be the server's) ----
const py=read("Cores","Services","reports_service.py")
const pyRx=/_TARGET_SECRET_KEY_RE=re\.compile\(r"([^"]+)",re\.I\)/.exec(py)
check("the secret-key rule is the same expression as the server's",!!pyRx&&pyRx[1]===T.SECRET_KEY_RX.source&&T.SECRET_KEY_RX.flags==="i",pyRx&&pyRx[1])
check("the exporter and the findings editor use that rule too",read("Cores","Services","report_export.py").indexOf('_SECRET_KEY_RX=re.compile(r"'+T.SECRET_KEY_RX.source+'",re.I)')>=0&&read("UI","js","pages","reporting_findings.js").indexOf("const SECRET_KEY_RX=/"+T.SECRET_KEY_RX.source+"/i")>=0)
;["Password","pass","PWD","API Token","NTLM Hash","SSH Key","Credentials","Cookie","Session","Private","OTP","PIN","Username","Login","Client Secret"].forEach((k)=>check("protected: "+k,T.isSecretKey(k)))
;["IPv4","IPv6","Domain","URL","Hostname","Port","FQDN","CIDR","Wordlist","OS","Notes",""].forEach((k)=>check("not protected: "+(k||"(empty)"),!T.isSecretKey(k)))
check("publicValues drops protected and empty values",eq(T.publicValues({IPv4:"10.0.0.5",Password:"x",Username:"u",Port:" ",Domain:null}),{IPv4:"10.0.0.5"}))
check("publicValues keeps a protected key that was allowed (case-insensitive)",eq(T.publicValues({IPv4:"1",Password:"x",Hash:"h"},["password"]),{IPv4:"1",Password:"x"}))
check("secretNames lists names only, minus the allowed ones",eq(T.secretNames({IPv4:"1",Password:"x",Hash:"h",Token:""},["Hash"]),["Password"]))

// ---- link state ----
check("an unchanged target is ok",eq(T.linkState(link(),{name:"web01",engagement_status:"in_progress",values:{IPv4:"10.0.0.5",URL:"https://shop.acme.example",Port:"443",Password:"new"}}),{state:"ok",changed:[]}))
check("name, status and values are compared",eq(T.linkState(link(),{name:"web02",engagement_status:"compromised",values:{IPv4:"10.0.0.9",URL:"https://shop.acme.example",Domain:"x.example"}}),{state:"changed",changed:["@name","@status","Domain","IPv4","Port"]}))
check("a protected value only counts once it was allowed",T.linkState(link({allowed_secret_keys:["Password"],snapshot:{values:{IPv4:"10.0.0.5",URL:"https://shop.acme.example",Port:"443",Password:"old"},engagement_status:"in_progress"}}),{name:"web01",engagement_status:"in_progress",values:{IPv4:"10.0.0.5",URL:"https://shop.acme.example",Port:"443",Password:"new"}}).changed.join()==="Password")
check("a missing target is removed",eq(T.linkState(link(),null),{state:"removed",changed:[]}))
check("state labels",T.stateLabel({state:"removed"})==="target removed"&&T.stateLabel({state:"changed"})==="changed"&&T.stateLabel({state:"ok"})==="")

// ---- values ----
check("valueOf reads values, the name and the status",T.valueOf(link(),"IPv4")==="10.0.0.5"&&T.valueOf(link(),"ipv4")==="10.0.0.5"&&T.valueOf(link(),"@name")==="web01"&&T.valueOf(link(),"@status")==="In progress")
check("valueOf never returns a protected value that is not allowed, even when a snapshot holds it",T.valueOf(link({snapshot:{values:{Password:"leak"}}}),"Password")===null&&T.valueOf(link({snapshot:{values:{Password:"ok"}},allowed_secret_keys:["Password"]}),"Password")==="ok")
check("valueOf of nothing is null",T.valueOf(null,"IPv4")===null&&T.valueOf(link(),"Nope")===null)
check("status labels",T.statusLabel("compromised")==="Compromised"&&T.statusLabel("bogus")==="Not started")
check("affectedLabel prints the name and the chosen values",T.affectedLabel(link(),["URL","IPv4","Password","@name","URL"])==="web01 (https://shop.acme.example, 10.0.0.5)"&&T.affectedLabel(link(),[])==="web01"&&T.affectedLabel(null,[])==="")
check("normFindingTargets keeps known links once, with clean keys",eq(T.normFindingTargets([{uid:"u1",keys:["IPv4","IPv4","{bad}",5]},{uid:"zz"},"u1",null],[link()]),[{uid:"u1",keys:["IPv4","5"]}]))

// ---- scope table columns ----
const two=[link(),link({uid:"u2",name:"vpn",snapshot:{values:{IPv4:"203.0.113.9",Notes:"edge"},engagement_status:"compromised"}})]
check("default columns: address-like keys, then the status",eq(T.scopeColumns(two,null),["IPv4","URL","@status"]))
check("default columns never offer a protected key",eq(T.scopeColumns([link({snapshot:{values:{Password:"x",IPv4:"1"}},allowed_secret_keys:["Password"]})]),["IPv4","@status"]))
check("without address keys the first values are used",eq(T.scopeColumns([link({snapshot:{values:{OS:"Linux",Notes:"n"}}})]),["OS","Notes","@status"]))
check("a chosen list is kept in order, deduplicated, without the name",eq(T.scopeColumns(two,["Port","@name","IPv4","Port",""]),["Port","IPv4"])&&eq(T.scopeColumns(two,[]),[]))
check("allKeys is the union of what the links hold",eq(T.allKeys(two),["IPv4","URL","Port","Notes"]))

// ---- the reference chip: sanitiser ----
const san=RC.sanitizeHtml
check("a reference chip survives as it is",san("<p>a "+tv("abc123","IPv4","10.0.0.5")+" b</p>")==="<p>a "+tv("abc123","IPv4","10.0.0.5")+" b</p>")
check("keys with spaces and the @ fields are accepted",san(tv("u1","NTLM Hash","h"))===tv("u1","NTLM Hash","h")&&san(tv("u1","@name","web01"))===tv("u1","@name","web01"))
check("everything but the two attributes is dropped, and the chip holds text only",san('<span class="x rpt-tv" data-target="u1" data-key="@name" onclick="x()" style="color:red" id="q"><b>web</b><img src=x onerror=1>01<script>1</script></span>')===tv("u1","@name","web01"))
;['data-target="a b" data-key="IPv4"','data-target="u1" data-key=""','data-target="u1"','data-key="IPv4"','data-target="u1" data-key="a&quot;b"','data-target="u1" data-key="a&lt;b"','data-target="u1" data-key="{x}"','data-target="u1" data-key="a=b"','data-target="'+"u".repeat(65)+'" data-key="k"','data-target="u1" data-key="'+"k".repeat(81)+'"','data-target="u1" data-key="java\tscript"'].forEach((bad)=>{
check("a malformed reference is only its text: "+bad.slice(0,48),san('<span class="rpt-tv" '+bad+">text</span>")==="text",san('<span class="rpt-tv" '+bad+">text</span>"))
})
check("what follows a chip is sanitised as usual",san("<p>"+tv("u1","k","v")+" <strong>after</strong><script>x</script></p>")==="<p>"+tv("u1","k","v")+" <strong>after</strong></p>")
check("an unclosed chip does not swallow the next block's markup rules",san('<p><span class="rpt-tv" data-target="u1" data-key="k">v<p onclick=1>next</p>').indexOf("onclick")<0)
check("the scope widget marker is allowed and always empty",san('<div class="rpt-widget" data-widget="scope_targets">junk<b>x</b></div>')==='<div class="rpt-widget" data-widget="scope_targets"></div>'&&san('<div class="rpt-widget" data-widget="scope_nope"></div>')==="")
const pySan=/_WIDGETS=\(([^)]*)\)/.exec(py)
check("the server knows the same widget and span class",!!pySan&&pySan[1].indexOf('"scope_targets"')>=0&&/_SPAN_CLS=\([^)]*"rpt-tv"\)/.test(py))
check("chipHtml builds exactly what the sanitiser keeps",san(T.chipHtml("u1","IPv4","10.0.0.5"))===T.chipHtml("u1","IPv4","10.0.0.5")&&T.chipHtml("u1","IPv4","<b>")===tv("u1","IPv4","&lt;b&gt;")&&T.chipHtml("bad uid","IPv4","v")==="v"&&T.chipHtml("u1","{k}","<v>")==="&lt;v&gt;")

// ---- resolving references ----
const links=[link(),link({uid:"u2",name:"db<1>",snapshot:{values:{Password:"pw"},engagement_status:"reported"}})]
check("references take the snapshot's current value",T.resolveHtml("<p>"+tv("u1","IPv4")+tv("u1","@name")+tv("u2","@status")+"</p>",links)==="<p>"+tv("u1","IPv4","10.0.0.5")+tv("u1","@name","web01")+tv("u2","@status","Reported")+"</p>")
check("values are escaped",T.resolveHtml(tv("u2","@name"),links)===tv("u2","@name","db&lt;1&gt;"))
check("a reference that no longer resolves keeps its text",T.resolveHtml(tv("gone","IPv4","198.51.100.7")+tv("u1","Missing","kept"),links)===tv("gone","IPv4","198.51.100.7")+tv("u1","Missing","kept"))
check("a protected reference is withheld unless allowed",T.resolveHtml(tv("u2","Password","leak")+tv("gone","API Token","leak2"),links)===tv("u2","Password","[withheld]")+tv("gone","API Token","[withheld]")&&T.resolveHtml(tv("u2","Password","old"),[link({uid:"u2",snapshot:{values:{Password:"pw"}},allowed_secret_keys:["Password"]})])===tv("u2","Password","pw"))
check("html without references is untouched",T.resolveHtml("<p>x</p>",links)==="<p>x</p>"&&T.resolveHtml(null,links)==="")

// ---- Markdown degradation ----
const html="<p>Host "+tv("u1","IPv4","10.0.0.5")+" and "+tv("u1","NTLM Hash","h")+" named "+tv("u1","@name","web01")+".</p>"
const md=RC.htmlToMarkdown(html)
check("htmlToMarkdown writes <tv uid key=..>text</tv>",md==='Host <tv u1 key="IPv4">10.0.0.5</tv> and <tv u1 key="NTLM Hash">h</tv> named <tv u1 key="@name">web01</tv>.',md)
check("markdownToHtml brings the references back",RC.markdownToHtml(md)===html,RC.markdownToHtml(md))
check("a hand-written tag with a bad uid or key stays text",RC.markdownToHtml('<tv bad uid key="k">x</tv> <tv u1 key="{k}">y</tv>').indexOf("rpt-tv")<0)
check("the scope widget round-trips through Markdown",RC.markdownToHtml(RC.htmlToMarkdown('<p>a</p><div class="rpt-widget" data-widget="scope_targets"></div>'))==='<p>a</p><div class="rpt-widget" data-widget="scope_targets"></div>')
check("htmlToText shows the value",RC.htmlToText(html)==="Host 10.0.0.5 and h named web01.")

// ---- wiring ----
const widgets=read("UI","js","pages","reporting_widgets.js"),findings=read("UI","js","pages","reporting_findings.js"),targets=read("UI","js","pages","reporting_targets.js")
check("the editors offer Target value in the report row, the slash menu and the context menu",/\{id:"tvalue",own:true/.test(widgets)&&/\{id:"r-target",label:"Target value"/.test(widgets)&&/label:"Target Value\.\.\."/.test(widgets))
check("the widget menu offers the scope table",/\{id:"scope_targets",label:"Scope targets table/.test(widgets))
check("chips are islands in the editor and are refreshed from the links",/\.rpt-widget,\.rpt-fref,\.rpt-ph,\.rpt-tv"\)\.forEach\(\(n\)=>\{n\.contentEditable="false"\}\)/.test(widgets)&&/refreshTargetValues:refreshTargetValues/.test(widgets))
check("the plain-text choice inserts no reference",/if\(v\.plain\|\|.*\{insertNodeInline\(document\.createTextNode\(v\.value\)\);return\}/.test(widgets))
check("the old affected-assets picker filters protected keys",/Object\.keys\(t\.values\)\.filter\(\(k\)=>!SECRET_KEY_RX\.test\(k\)&&/.test(findings))
check("findings save linked targets through the normal patch (one undo step)",/patch\(id,\{targets:res\}\)/.test(findings)&&/patch\(id,\{targets:list\.filter/.test(findings))
check("a protected value is only added after the warning dialog",(targets.match(/confirmSecret\(l,k\)\.then\(\(ok\)=>\{\nif\(!ok\)return/g)||[]).length===2&&(targets.match(/"target_allow_secret"/g)||[]).length===1)
check("the module needs no storage API, and the only templated markup is the escaped button label",!/localStorage|sessionStorage/.test(targets)&&(targets.match(/innerHTML=[^"']/g)||[]).length===1&&/<span>\$\{esc\(label\)\}<\/span>/.test(targets))
check("the Node build exposes only the pure helpers",typeof T.mountScope==="undefined"&&typeof T.isSecretKey==="function")
const css=read("UI","css","pages","reporting_targets.css")
check("every user-select has its -webkit- twin",(css.match(/[^-]user-select:/g)||[]).length===(css.match(/-webkit-user-select:/g)||[]).length)
console.log("\nreporting_targets: "+passed+" passed, "+failed+" failed")
process.exit(failed?1:0)
