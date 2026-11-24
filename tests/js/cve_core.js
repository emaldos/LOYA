// CVE Intel page helpers: id detection, escaping, https-only links, Markdown export, and a source check that cve.js escapes remote text.
const fs=require("fs")
const path=require("path")
const C=require("../../UI/js/pages/cve_core.js")
const ROOT=path.resolve(__dirname,"..","..")
const PAGE=fs.readFileSync(path.join(ROOT,"UI","js","pages","cve.js"),"utf8")
const HTML=fs.readFileSync(path.join(ROOT,"UI","pages","cve.html"),"utf8")
const CSS=fs.readFileSync(path.join(ROOT,"UI","css","pages","cve.css"),"utf8")
const MAIN=fs.readFileSync(path.join(ROOT,"UI","windows","main.html"),"utf8")
let passed=0,failed=0
function check(name,ok,detail){if(ok)passed++;else{failed++;console.log("FAIL: "+name+(detail?" - "+detail:""))}}
function eq(name,a,b){check(name,JSON.stringify(a)===JSON.stringify(b),JSON.stringify(a)+" != "+JSON.stringify(b))}
// ---- ids
eq("ids: mixed case, duplicates, order kept",C.extractIds("see cve-2021-44228, CVE-2021-44228 and Cve-2023-4863."),["CVE-2021-44228","CVE-2023-4863"])
eq("ids: six and seven digit sequence numbers",C.extractIds("CVE-2026-129448 CVE-2026-1234567"),["CVE-2026-129448","CVE-2026-1234567"])
eq("ids: too short or malformed ones are ignored",C.extractIds("CVE-99-1 CVE-2021-123 CVE_2021_44228 CVE-20211-44228"),[])
eq("ids: an id glued to a longer word or number is ignored",C.extractIds("XCVE-2021-44228 CVE-2021-12345678"),[])
eq("ids: found inside pasted text and URLs",C.extractIds("nmap: |  CVE-2017-0144  9.3 https://nvd.nist.gov/vuln/detail/CVE-2019-0708\n(cve-2020-0796)"),["CVE-2017-0144","CVE-2019-0708","CVE-2020-0796"])
eq("ids: nothing in empty input",[C.extractIds(""),C.extractIds(null),C.extractIds(undefined)],[[],[],[]])
check("ids: repeated calls give the same answer",C.extractIds("CVE-2021-44228").length===1&&C.extractIds("CVE-2021-44228").length===1)
eq("normId",[C.normId(" cve-2021-44228 "),C.normId("CVE-2021-44228; rm"),C.normId("")],["CVE-2021-44228","",""])
// ---- escaping
eq("esc: attribute-breaking payload",C.esc('" onmouseover="alert(1)'),"&quot; onmouseover=&quot;alert(1)")
eq("esc: tags and single quotes",C.esc("<img src=x onerror='a()'>&"),"&lt;img src=x onerror=&#39;a()&#39;&gt;&amp;")
eq("esc: null and numbers",[C.esc(null),C.esc(undefined),C.esc(7)],["","","7"])
check("esc: never returns a raw quote or angle bracket",!/[<>"']/.test(C.esc('</script><svg onload="x" a=\'y\'>')))
// ---- links
eq("safeUrl: https is kept",C.safeUrl(" https://nvd.nist.gov/vuln/detail/CVE-2021-44228 "),"https://nvd.nist.gov/vuln/detail/CVE-2021-44228")
for(const bad of ["http://example.com/a","javascript:alert(1)","JaVaScRiPt:alert(1)","data:text/html,<script>1</script>","//evil.example/x","/relative","file:///etc/passwd","https://","https:// evil.example","https://user:pw@evil.example/","https://a.example/\"onclick=\"x","https://a.example/<b>","https://a.example/\nx","vbscript:x","",null,undefined,{}])check("safeUrl rejects "+JSON.stringify(bad),C.safeUrl(bad)==="")
// ---- formatting
eq("severity: normalised",[C.normSeverity("CRITICAL"),C.normSeverity("none"),C.normSeverity("Informational"),C.normSeverity("x<y")],["critical","info","info",""])
eq("severity: class is always a fixed token",[C.sevClass("HIGH"),C.sevClass('"><b>')],["cve-sev-high","cve-sev-unknown"])
eq("severity: label",[C.sevLabel("medium"),C.sevLabel("")],["Medium","Unknown"])
eq("score",[C.fmtScore(10),C.fmtScore("7.55"),C.fmtScore(null),C.fmtScore("x"),C.fmtScore(11)],["10.0","7.6","-","-","-"])
eq("epss",[C.fmtEpss({score:0.97224,percentile:0.9999}),C.fmtEpss(0.00042),C.fmtEpss(null),C.fmtEpss({score:"abc"})],["97.2% (100.0th percentile)","0.04%","-","-"])
eq("dates",[C.fmtDate("2021-12-10T10:15:09.143"),C.fmtDate("2021-12-24"),C.fmtDate(""),C.fmtDate("<b>")],["2021-12-10","2021-12-24","",""])
const NOW=Date.parse("2026-11-23T12:00:00Z")
eq("relTime",[C.relTime("2026-11-23T11:59:30Z",NOW),C.relTime("2026-11-23T11:30:00.000",NOW),C.relTime("2026-11-23T09:00:00+00:00",NOW),C.relTime("2026-11-20T12:00:00Z",NOW),C.relTime("",NOW)],["just now","30m ago","3h ago","3d ago",""])
eq("ref kinds fall back to other",[C.refKind("Patch"),C.refKind("weird"),C.refKindLabel("vendor"),C.refIcon("exploit"),C.refIcon('"><i>')],["patch","other","Vendor advisory","bug","link"])
const ICONS=fs.readdirSync(path.join(ROOT,"Assets","icons")).map((f)=>f.replace(/\.svg$/,""))
check("ref icons exist in Assets/icons",Object.values(C.REF_KINDS).every((k)=>ICONS.includes(k.icon)))
eq("summaryLine",C.summaryLine({id:"CVE-2021-44228",severity:"critical",score:10,kev:true,epss:0.9999}),"CVE-2021-44228 · Critical 10.0 · KEV · EPSS 100.0%")
// ---- feed filters
eq("filters: defaults",C.feedFilterNormalize(null),{limit:100})
eq("filters: cleaned and clamped",C.feedFilterNormalize({severity:"HIGH",kev_only:1,epss_min:50,q:"  apache   tomcat ",from:"2026-11-20",to:"2026-11-01",unread_only:true,watch_only:0,limit:9999,offset:"20",evil:"x"}),{severity:"high",kev_only:true,epss_min:0.5,q:"apache tomcat",from:"2026-11-01",to:"2026-11-20",unread_only:true,limit:500,offset:20})
eq("filters: bad values dropped",C.feedFilterNormalize({severity:"'; drop",epss_min:"x",from:"yesterday",to:"2026-13-99x",limit:0}),{limit:1})
eq("watchlist: trimmed, de-duplicated, capped at 80 chars",C.watchNormalize(["Apache Tomcat"," apache  tomcat ","",null],"x".repeat(90)),["Apache Tomcat","x".repeat(80)])
check("watchlist: at most 100 terms",C.watchNormalize(Array.from({length:150},(_,i)=>"t"+i)).length===100)
// ---- Markdown export
const REC={id:"CVE-2021-44228",title:"Log4Shell <img src=x onerror=alert(1)>",description:"JNDI [click](javascript:alert(1)) `code`\n# heading",severity:"critical",score:10,published:"2021-12-10T10:15:09.143",modified:"2026-08-11T19:33:44.513",
cvss:{v31:{vector:"CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H",score:10,severity:"critical"},v40:null,v2:null},
cwes:[{id:"CWE-502",name:"Deserialization of Untrusted Data"}],affected:[{vendor:"Apache",product:"Log4j2",versions:"2.0-beta9 to 2.15.0"}],affected_total:1,
references:[{url:"https://logging.apache.org/log4j/2.x/security.html",plain:"",tags:["Vendor Advisory"],kind:"vendor"},{url:"",plain:"http://packetstormsecurity.com/files/165225/x.html",tags:["Exploit"],kind:"exploit"},{url:"javascript:alert(1)",plain:"",tags:[],kind:"other"}],
kev:{in_kev:true,date_added:"2021-12-10",due_date:"2021-12-24",required_action:"Apply updates.",ransomware:"Known",name:"Log4j2 RCE",notes:""},epss:{score:0.99999,percentile:1,date:"2026-11-23"},
links:{cve_org:"https://www.cve.org/CVERecord?id=CVE-2021-44228",nvd:"https://nvd.nist.gov/vuln/detail/CVE-2021-44228",kev:"https://www.cisa.gov/known-exploited-vulnerabilities-catalog"},
protect:{kev_action:{text:"Apply updates.",due_date:"2021-12-24",date_added:"2021-12-10"},vendor:[{url:"https://logging.apache.org/log4j/2.x/security.html",tags:["Vendor Advisory"],kind:"vendor"},{url:"http://insecure.example/patch",tags:["Patch"],kind:"patch"}],generic:[{cwe:"CWE-502",name:"Deserialization of Untrusted Data",mitigations:["Do not deserialize untrusted data."],detection:["Alert on JNDI lookups in logs."]}],vendor_note:"",generic_note:""},
sources:["nvd"],origin:"cache",fetched_at:"2026-11-23T18:48:13+00:00",stale:false,warning:""}
const md=C.toMarkdown(REC)
check("markdown: heading with the id",md.startsWith("## CVE-2021-44228 - Log4Shell"))
check("markdown: html in remote text is neutralised",!/(^|[^\\])<img/.test(md)&&md.includes("\\<img"))
check("markdown: a markdown link in remote text cannot become a link",!/\]\(javascript:/.test(md)&&md.includes("\\[click\\]\\(javascript:alert\\(1\\)\\)"))
check("markdown: remote newlines cannot start a heading",!/\n# heading/.test(md))
check("markdown: https references are linked",md.includes("](<https://logging.apache.org/log4j/2.x/security.html>)"))
check("markdown: only https links are emitted",(md.match(/\]\(<([^>]*)>\)/g)||[]).length>=4&&(md.match(/\]\(<([^>]*)>\)/g)||[]).every((l)=>l.startsWith("](<https://"))&&!md.includes("http://"))
check("markdown: the protect block labels vendor and generic guidance",md.includes("**CISA KEV required action:** Apply updates.")&&md.includes("**Vendor guidance:**")&&md.includes("**Generic guidance (CWE-502 Deserialization of Untrusted Data) - not specific to this product:**"))
check("markdown: KEV, EPSS and CVSS facts",md.includes("**CISA KEV:** yes, added 2021-12-10, due 2021-12-24, known ransomware use")&&md.includes("**EPSS:** 100.0%")&&md.includes("`CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H`"))
check("markdown: online pages listed",md.includes("[cve.org](<https://www.cve.org/CVERecord?id=CVE-2021-44228>)")&&md.includes("[NVD](<https://nvd.nist.gov/vuln/detail/CVE-2021-44228>)"))
eq("markdown: empty record",[C.toMarkdown(null),C.toMarkdown({})],["",""])
check("markdown: a backtick in a vector cannot close the code span",!C.toMarkdown({id:"CVE-2024-0001",cvss:{v31:{vector:"CVSS:3.1/`x`",score:5}}}).includes("`x`"))
// ---- notifications
eq("notify text",[C.notifyText({id:"CVE-2026-129448",kind:"kev",title:"Apache Roller",message:"Apache Roller deserialization"}),C.notifyText({id:"cve-2024-3094",kind:"watch",message:"matches xz"}),C.notifyText(null)],["New CISA KEV entry: CVE-2026-129448 - Apache Roller deserialization","Watchlist match: CVE-2024-3094 - matches xz",""])
check("notify text is clipped",C.notifyText({id:"CVE-2024-0001",kind:"watch",message:"x".repeat(900)}).length<230)
// ---- the page source: remote fields only reach HTML through cveE()/CveCore.esc
const REMOTE="description|title|required_action|name|vendor|product|versions|plain|message|text|notes|status|warning|error|cwe|id|url|vendors|ransomware|source"
const raw=PAGE.match(new RegExp("\\$\\{[^{}]*\\.("+REMOTE+")\\}","g"))||[]
eq("page: no remote field is interpolated without escaping",raw,[])
const tpl=PAGE.match(/\$\{[^{}]*\}/g)||[]
const SAFE=/cveE\(|CveCore\.(sevClass|refIcon)\(|cveSevBadge\(|cveKevBadge\(|cveLinkBtn\(|cveCvssRow\(|cveCweChip|cveRefHtml|cveProtectHtml\(|cveRowHtml\(|\.length|affTotal|^\$\{(insert|origin|errs|epss|watch|kind|read|label|body|tags|kind|chipState|chipIndex|stateChip|summaryNote|protect|idx\?' data-cve-index="1"':""|summary\?"[A-Za-z ]*":"[A-Za-z ]*"|num\[1\]|canFetch\?[^}]*|active\?[^}]*|cls\?[^}]*|cveState\.(affAll|refsAll)\?[^}]*|i|r\.origin==="live"\?"live":"cache"|s\.is_read\?[^}]*|o\.feed[^}]*|ransom\?[^}]*|r\.partial\?[^}]*|!cv\.[^}]*|cv[^}]*|kev\?[^}]*|refs[^}]*|aff[^}]*|vendor[^}]*|generic[^}]*|p\.[^}]*|\(g\.[^}]*|\(Array[^}]*|Array[^}]*|m\.source\?[^}]*|r\.[a-z_]+(&&[^}]*)?\?[^}]*|errorId\?[^}]*)\}$/
check("page: the template check sees the templates",tpl.length>60,String(tpl.length))
eq("page: every template expression is a known safe shape",tpl.filter((t)=>!SAFE.test(t)),[])
check("page: innerHTML is never fed a bridge error or record directly",!/innerHTML\s*=\s*(err|rec|res|r|s)\b/.test(PAGE))
check("page: links open through notes.open_url after a second https check",/function cveOpenUrl\(url\)\{\nconst u=CveCore\.safeUrl\(url\)/.test(PAGE)&&PAGE.includes('bridgeCall("notes.open_url",[u])'))
check("page: no anchors, window.open or location changes",!/<a\s|window\.open|location\.(href|assign|replace)/.test(PAGE)&&!/<a\s/.test(HTML))
check("page: no localStorage or sessionStorage",!/localStorage|sessionStorage/.test(PAGE+C.toString()))
check("page: search uses the local cache call",PAGE.includes('cveCall("search",[q,30])'))
// ---- the bundled offline index
eq("search filters: empty means the plain call",[C.searchFilters({}),C.searchFilters(null),C.searchFilters({severity:"",kev_only:false}),C.searchFilters({severity:"bogus"}),C.searchFilters({severity:"info"})],[null,null,null,null,null])
eq("search filters: normalised",[C.searchFilters({severity:"HIGH",kev_only:true,evil:"x"}),C.searchFilters({kev_only:true}),C.searchFilters({kev_only:"yes"})],[{severity:"high",kev_only:true},{kev_only:true},null])
eq("count formatting",[C.fmtCount(312404),C.fmtCount("1000"),C.fmtCount(-4),C.fmtCount("x"),C.fmtCount(null)],["312,404","1,000","0","0","0"])
check("index-only detection",C.isIndexOnly({index_only:true})&&C.isIndexOnly({origin:"index"})&&!C.isIndexOnly({origin:"cache",index_only:false})&&!C.isIndexOnly(null))
eq("state labels",[C.stateLabel("rejected"),C.stateLabel("REJECTED"),C.stateLabel("reserved"),C.stateLabel("published"),C.stateLabel("<b>"),C.stateLabel(null)],["Rejected","Rejected","Reserved","","",""])
eq("index count: search answer first, then status",[C.indexCount({used:true,count:300000},{installed:true,count:5}),C.indexCount(null,{installed:true,count:5}),C.indexCount({count:0},{installed:false,count:9}),C.indexCount(null,null),C.indexCount({count:"x"},{count:"7"})],[300000,5,0,0,7])
eq("results title",[C.resultsTitle("",{index:{used:false}},false),C.resultsTitle("",{index:{used:true}},false),C.resultsTitle("log4j",{index:{used:true}},false),C.resultsTitle("log4j",{},false),C.resultsTitle("",{index:{used:true}},true)],["Saved CVEs","Saved CVEs and the offline index","Matches - saved CVEs first, then the offline index","Saved CVEs matching your text","Matches - saved CVEs first, then the offline index"])
check("empty state: index installed",C.emptyResultsText("",312404,false,false)==="Search 312,404 CVEs offline by ID, product or keyword.")
check("empty state: nothing at all",/Nothing saved yet/.test(C.emptyResultsText("",0,false,false)))
check("empty state: no match with and without the index",/offline index of 5 CVEs/.test(C.emptyResultsText("zzz",5,true,false))&&/once online lookups are on/.test(C.emptyResultsText("zzz",0,false,false))&&/offline index/.test(C.emptyResultsText("",5,true,true)))
check("page: filters go as the third search argument only when set",PAGE.includes('(f?cveCall("search",[q,30,f]):cveCall("search",[q,30]))')&&PAGE.includes("const f=CveCore.searchFilters(cveState.searchFilters)"))
check("page: index-only rows open the summary without fetching",/if\(row\.dataset\.cveIndex==="1"\)cveShowIndex\(row\.dataset\.cveId\)/.test(PAGE)&&PAGE.includes('cveCall("index_get",[cid])')&&!/function cveShowIndex[\s\S]{0,500}cveCall\("lookup"/.test(PAGE))
check("page: a missing index bridge falls back to the normal lookup",/cveCall\("index_get",\[cid\]\)[\s\S]{0,260}\.catch\(\(\)=>\{[\s\S]{0,260}return cveShowRecord\(cid,false\)/.test(PAGE))
check("page: Fetch full details only when online lookups are allowed",/!summary\?"":canFetch\?'<div class="cve-summary-note">[^']*data-cve-act="fetch">Fetch full details<\/button><\/div>':'<div class="cve-summary-note">[^']*Online lookups are off - this is the summary from the bundled index\.[^']*data-cve-act="settings">Open Settings<\/button><\/div>'/.test(PAGE))
check("page: fetch asks for the live record",PAGE.includes('if(a==="fetch"){cveShowRecord(r.id,true);return}')&&PAGE.includes('if(a==="settings"){cveGoSettings();return}'))
check("page: index chip explains itself",PAGE.includes('title="From the bundled CVE index - summary only">index</span>'))
check("page: summary mode drops empty sections",PAGE.includes('${summary&&!aff.length?"":`<div class="cve-section"><div class="cve-section-title">Affected products')&&PAGE.includes("if(vendor.length||!summary)out.push(")&&PAGE.includes('${protect?`<div class="cve-section cve-protect">'))
check("html: lookup filters exist",/id="cveSSeverity"/.test(HTML)&&/id="cveSKev"/.test(HTML))
check("page: notifications go to the bell history",PAGE.includes('toastAddHistory(CveCore.notifyText(n),"info",()=>cveOpenDetail(id))'))
check("page: the poller starts at script load and skips while locked",/document\.addEventListener\("DOMContentLoaded",cveStartPoller\)/.test(PAGE)&&PAGE.includes("cveLocked()"))
check("html: static page has no inline handlers or scripts",!/\son[a-z]+\s*=|<script/i.test(HTML))
// ---- css rules from the Linux audit
const decls=CSS.replace(/\/\*[\s\S]*?\*\//g,"")
const rules=decls.match(/[^{}]+\{[^{}]*\}/g)||[]
check("css: every user-select has its -webkit- twin",rules.filter((r)=>/[;{]user-select:/.test(r)).every((r)=>/-webkit-user-select:/.test(r)))
check("css: no standard scrollbar properties (WebKitGTK)",!/scrollbar-(width|color)/.test(decls))
check("css: every class is prefixed cve-",(decls.match(/\.[a-zA-Z][\w-]*/g)||[]).every((c)=>/^\.(cve-|hidden$|icon$|set-btn$|set-input$|nav-btn$|primary$|busy$|active$|unread$)/.test(c)),(decls.match(/\.[a-zA-Z][\w-]*/g)||[]).filter((c)=>!/^\.(cve-|hidden$|icon$|set-btn$|set-input$|nav-btn$|primary$|busy$|active$|unread$)/.test(c)).join(" "))
check("css: tables use separate borders",/\.cve-table\{[^}]*border-collapse:separate;border-spacing:0/.test(decls))
// ---- registration
const links=MAIN.match(/<link rel="stylesheet"[^>]*>/g)||[]
check("main: cve.css is linked before glass.css, which stays last",links[links.length-1].includes("glass.css")&&links.some((l)=>l.includes("pages/cve.css")))
check("markdown: generic guidance without a CWE id has no stray space",C.toMarkdown({id:"CVE-2026-0001",protect:{generic:[{cwe:"",name:"General vulnerability guidance",mitigations:["Patch."],detection:[]}]}}).includes("**Generic guidance (General vulnerability guidance) - not specific"))
check("page: generic title joins the CWE id and name only when both exist",PAGE.includes('${g.name?(g.cwe?" · ":"")+cveE(g.name):""}'))
check("page: a KEV entry without a date or ransomware field shows no placeholder",PAGE.includes('${kev.date_added?"added "+cveE(CveCore.fmtDate(kev.date_added)):"in the catalog"}')&&!PAGE.includes('fmtDate(kev.date_added)||"-"')&&PAGE.includes('${kev.ransomware?" · ransomware use: "+cveE(kev.ransomware):""}'))
check("main: page section and dock button",MAIN.includes('<section class="page" data-page="cve"></section>')&&/<button class="nav-btn" data-page="cve"[^>]*><i class="icon icon-shield"><\/i><span>CVE Intel<\/span><\/button>/.test(MAIN))
check("main: cve_core.js loads before cve.js, both before app.js",MAIN.indexOf("pages/cve_core.js")>0&&MAIN.indexOf("pages/cve_core.js")<MAIN.indexOf("pages/cve.js")&&MAIN.indexOf("pages/cve.js")<MAIN.indexOf("js/app.js"))
check("app: page loader registered",fs.readFileSync(path.join(ROOT,"UI","js","app.js"),"utf8").includes("cve:initCve"))
console.log(passed+" passed, "+failed+" failed")
process.exit(failed?1:0)
