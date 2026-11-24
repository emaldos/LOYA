// CVE Intel in Notes: CVE-id detection, the viewer's link segments, the vulnerability callout (escaping, https-only links, vendor vs generic guidance) and the editor command.
const path=require("path")
const fs=require("fs")
const ROOT=path.resolve(__dirname,"..","..")
const C=require(path.join(ROOT,"UI","js","pages","cve_notes.js"))
const E=require(path.join(ROOT,"UI","js","pages","notes_editor_core.js"))
const P=require(path.join(ROOT,"UI","js","pages","notes_pro_core.js"))
let passed=0,failed=0
function check(name,ok,detail){if(ok)passed++;else{failed++;console.log("FAIL: "+name+(detail?" - "+detail:""))}}
function eq(name,a,b){check(name,JSON.stringify(a)===JSON.stringify(b),JSON.stringify(a)+" != "+JSON.stringify(b))}
// ---- ids
eq("ids: found, uppercased, unique, in order",C.cveNotesIds("see cve-2021-44228 and CVE-2026-129448, again CVE-2021-44228."),["CVE-2021-44228","CVE-2026-129448"])
eq("ids: short or malformed ones are not ids",C.cveNotesIds("CVE-2021-123 CVE-21-44228 CVE 2021 44228 CVE-2021-12345678"),[])
eq("ids: junk input",[C.cveNotesIds(null),C.cveNotesIds(undefined),C.cveNotesIds(42)],[[],[],[]])
// ---- segments
eq("segments: text and ids alternate",C.cveNotesSegments("a CVE-2021-44228, b"),[{t:"a "},{cve:"CVE-2021-44228",raw:"CVE-2021-44228"},{t:", b"}])
eq("segments: the typed case is kept for display",C.cveNotesSegments("cve-2021-44228")[0],{cve:"CVE-2021-44228",raw:"cve-2021-44228"})
eq("segments: an id glued to a word is left alone",C.cveNotesSegments("xCVE-2021-44228 CVE-2021-44228_poc"),[{t:"xCVE-2021-44228 CVE-2021-44228_poc"}])
eq("segments: no id",C.cveNotesSegments("nothing here"),[{t:"nothing here"}])
check("segments: the text is preserved exactly",C.cveNotesSegments("x CVE-2021-1234 y cve-2022-99999z CVE-2023-0001.").map((s)=>s.t||s.raw).join("")==="x CVE-2021-1234 y cve-2022-99999z CVE-2023-0001.")
// ---- links
check("https: only https urls pass",C.cveNotesHttps("https://example.com/a?b=1")==="https://example.com/a?b=1"&&["http://example.com","javascript:alert(1)","data:text/html,x","//example.com","https://a b","https://a\"onx=1",""].every((u)=>C.cveNotesHttps(u)===""))
// ---- callout
const rec={id:"CVE-2021-44228",title:"Apache Log4j2 JNDI",description:"Remote code execution.",published:"2021-12-10T10:15:09.143",modified:"2026-08-11T19:33:44.513",severity:"critical",score:10,
cvss:{v31:{version:"3.1",vector:"CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H",score:10,severity:"critical"},v40:null,v2:{version:"2.0",vector:"AV:N/AC:M/Au:N/C:C/I:C/A:C",score:9.3,severity:"high"}},
cwes:[{id:"CWE-502",name:"Deserialization of Untrusted Data"}],affected:[{vendor:"Apache",product:"Log4j2",versions:"2.0-beta9 to 2.15.0"}],affected_total:40,
references:[{url:"https://logging.apache.org/log4j/2.x/security.html",plain:"",tags:["Vendor Advisory"],kind:"vendor"},{url:"",plain:"http://packetstormsecurity.com/files/165225/x.html",tags:["Exploit"],kind:"exploit"}],
kev:{in_kev:true,date_added:"2021-12-10",due_date:"2021-12-24",required_action:"Apply updates.",ransomware:"Known"},epss:{score:0.99999,percentile:1,date:"2026-11-23"},
links:{cve_org:"https://www.cve.org/CVERecord?id=CVE-2021-44228",nvd:"https://nvd.nist.gov/vuln/detail/CVE-2021-44228",kev:"https://www.cisa.gov/known-exploited-vulnerabilities-catalog"},
protect:{kev_action:{text:"Apply updates.",due_date:"2021-12-24",date_added:"2021-12-10"},vendor:[{url:"https://logging.apache.org/log4j/2.x/security.html",tags:["Vendor Advisory"],kind:"vendor"}],generic:[{cwe:"CWE-502",name:"Deserialization of Untrusted Data",mitigations:["Do not deserialize untrusted data."],detection:["Alert on gadget-chain class names."]}]},
sources:["NVD","CISA KEV","FIRST EPSS"],origin:"live",fetched_at:"2026-11-23T18:48:13+00:00"}
const html=C.cveNotesCalloutHtml(rec)
check("callout: a vulnerability callout with severity and score",html.startsWith('<div class="note-callout note-finding" data-callout="vuln" data-sev="critical" data-cvss="10.0">')&&html.endsWith("</div>"))
check("callout: the severity is one the note editor knows",P.normSeverity("critical")==="critical"&&["critical","high","medium","low","info"].every((s)=>P.normSeverity(s)===s))
check("callout: title, vector, CWE, EPSS and KEV are there",html.includes("<h3>CVE-2021-44228: Apache Log4j2 JNDI</h3>")&&html.includes("<code>CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H</code>")&&html.includes("CWE-502 - Deserialization of Untrusted Data")&&html.includes("chance of exploitation")&&html.includes("<strong>Known exploited</strong> - added 2021-12-10, due 2021-12-24, ransomware use: Known"))
check("callout: affected products are capped with a count",html.includes("Apache Log4j2 2.0-beta9 to 2.15.0<br>and 39 more"))
check("callout: how to protect yourself has the KEV action",html.includes("<h4>How to protect yourself</h4>")&&html.includes("<strong>CISA KEV required action</strong> (due 2021-12-24): Apply updates."))
const iVendor=html.indexOf("<strong>Vendor guidance</strong>"),iGeneric=html.indexOf("<strong>Generic guidance (CWE-502 - Deserialization of Untrusted Data, not specific to this product)</strong>")
check("callout: vendor guidance and generic guidance are separate, labelled parts",iVendor>0&&iGeneric>iVendor)
check("callout: generic guidance lists mitigation and detection",html.includes("<p>Mitigation:</p><ul><li>Do not deserialize untrusted data.</li></ul>")&&html.includes("<p>Detection:</p><ul><li>Alert on gadget-chain class names.</li></ul>"))
check("callout: online pages come first in the references",html.includes('<h4>References</h4><ul><li><a href="https://www.cve.org/CVERecord?id=CVE-2021-44228">CVE.org record</a></li><li><a href="https://nvd.nist.gov/vuln/detail/CVE-2021-44228">NVD detail page</a></li><li><a href="https://www.cisa.gov/known-exploited-vulnerabilities-catalog">CISA Known Exploited Vulnerabilities catalog</a></li>'))
check("callout: a non-https reference is plain text, never a link",html.includes("http://packetstormsecurity.com/files/165225/x.html <em>(not https, not linked)</em>")&&!/href="http:/.test(html))
check("callout: the source line says where and when",html.includes("Source: NVD / CISA KEV / FIRST EPSS - fetched 2026-11-23."))
const hrefs=(h)=>Array.from(h.matchAll(/href="([^"]*)"/g)).map((m)=>m[1])
check("callout: every link is https",hrefs(html).length>=4&&hrefs(html).every((u)=>/^https:\/\//.test(u)))
// hostile record: nothing a remote source sends may become markup, an attribute or a non-https link
const X='<img src=x onerror="alert(1)">'
const evil={id:"CVE-2024-0001",title:X+'" onmouseover="x',description:"<script>alert(1)</script>"+X,severity:'critical" onclick="x',score:'9.8"><script>',published:X,modified:X,
cvss:{v31:{vector:X,score:"<b>",severity:X}},cwes:[{id:X,name:X},X],affected:[{vendor:X,product:X,versions:X},X],affected_total:"<i>",
references:[{url:"javascript:alert(1)",tags:[X]},{url:"http://plain.example/x",tags:[]},{url:"data:text/html,<script>alert(1)</script>",tags:[]},{url:'https://ok.example/"><img src=x onerror=alert(1)>',tags:[]},{url:"https://ok.example/path?a=1&b=2",tags:[X]},{url:"",plain:X}],
kev:{in_kev:true,date_added:X,due_date:X,ransomware:X},epss:{score:"x",percentile:X,date:X},
links:{cve_org:"javascript:alert(1)",nvd:"http://nvd.example",kev:X},
protect:{kev_action:{text:X,due_date:X},vendor:[{url:"javascript:alert(2)",tags:[X]},{url:"https://vendor.example/a",tags:[X]}],generic:[{cwe:X,name:X,mitigations:[X],detection:[X]}]},sources:[X],fetched_at:X}
const bad=C.cveNotesCalloutHtml(evil)
const tags=Array.from(bad.matchAll(/<\/?([a-zA-Z0-9]+)/g)).map((m)=>m[1].toLowerCase())
const allowed=new Set(["div","h3","h4","table","tbody","tr","th","td","p","br","strong","em","code","ul","li","a","small"])
eq("hostile: only the callout's own tags are produced",Array.from(new Set(tags.filter((t)=>!allowed.has(t)))),[])
check("hostile: no script, image or event handler survives as markup",!/<script|<img|<b>|<i>/i.test(bad)&&!/<[^>]*\son[a-z]+\s*=/i.test(bad))
eq("hostile: only clean https urls become links",hrefs(bad),["https://vendor.example/a","https://ok.example/path?a=1&amp;b=2"])
check("hostile: unknown severity falls back to info, the score is written as a plain number",bad.startsWith('<div class="note-callout note-finding" data-callout="vuln" data-sev="info" data-cvss="9.8"><h3>'))
check("hostile: the escaped text is still shown",bad.includes("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;")&&bad.includes("&lt;script&gt;alert(1)&lt;/script&gt;"))
check("hostile: the labels stay",bad.includes("<strong>Vendor guidance</strong>")&&bad.includes("<strong>Generic guidance ("))
// tags, classes and data attributes are ones the note sanitiser keeps
check("sanitiser: every tag is kept",Array.from(new Set(tags)).every((t)=>P.sanTagAction(t,"render")==="keep"&&P.sanTagAction(t,"paste")==="keep"))
const empty=C.cveNotesCalloutHtml(null)
check("empty: junk input still gives a well-formed callout",empty.startsWith('<div class="note-callout note-finding" data-callout="vuln" data-sev="info">')&&empty.includes("no vendor patch or advisory link is listed")&&C.cveNotesCalloutHtml({id:"CVE-2020-1234"}).includes("<h3>CVE-2020-1234</h3>"))
const many=C.cveNotesCalloutHtml({id:"CVE-2020-1234",references:Array.from({length:40},(_,i)=>({url:"https://r.example/"+i,tags:[]}))})
check("references: capped, with the rest pointed at NVD",hrefs(many).length===15&&many.includes("<li>25 more on NVD</li>"))
check("kev: a full record that is not in KEV says so, a partial one stays silent",C.cveNotesCalloutHtml({id:"CVE-2020-1234",kev:null}).includes("Not in the CISA KEV catalog")&&!C.cveNotesCalloutHtml({id:"CVE-2020-1234",kev:null,partial:true}).includes("Not in the CISA KEV catalog"))
// ---- editor command
const cmd=E.get("pt.cve")
check("command: registered for the More panel",!!cmd&&cmd.group==="pentest"&&cmd.tier==="advanced"&&cmd.icon==="shield"&&E.pinnable("pt.cve"))
check("command: in the More panel when not pinned",E.moreSections(E.defaultMain(),[],false).some((s)=>s.label==="Pentest"&&s.items.includes("pt.cve")))
check("command: in the right-click menu",E.menuIds(E.menuModel({})).includes("pt.cve"))
check("command: in the slash menu",E.slashItems().some((s)=>s.id==="pt.cve"&&s.label==="CVE"&&/cve/.test(s.keys)))
const dom=fs.readFileSync(path.join(ROOT,"UI","js","pages","notes_editor.js"),"utf8")
check("command: has a handler",/^"pt\.cve":\(ctx\)=>/m.test(dom))
const notes=fs.readFileSync(path.join(ROOT,"UI","js","pages","notes.js"),"utf8")
const viewer=notes.slice(notes.indexOf("function notesRenderViewer(note){"),notes.indexOf("function notesDecodeCmdToken"))
check("viewer: CVE ids are linked after the note is sanitised and decorated",viewer.indexOf("cveLinkify(body)")>viewer.indexOf("notesProDecorate(body)")&&viewer.indexOf("notesProDecorate(body)")>viewer.indexOf("notesProSetHtml(body,note.content_html)"))
check("viewer: the editor is never linkified",notes.split("cveLinkify(").length===2)
console.log(passed+" passed, "+failed+" failed")
process.exit(failed?1:0)
