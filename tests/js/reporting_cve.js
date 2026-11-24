// Pure helpers of the CVEs of a report finding (UI/js/pages/reporting_cve_core.js). Run: node tests/js/reporting_cve.js
const path=require("path")
const fs=require("fs")
const ROOT=path.resolve(__dirname,"..","..")
const RC=require(path.join(ROOT,"UI","js","pages","reporting_core.js"))
const CV=require(path.join(ROOT,"UI","js","pages","reporting_cve_core.js"))
let passed=0,failed=0
function check(name,cond,detail){if(cond){passed++;return}failed++;console.log("  FAIL  "+name+(detail!==undefined?"  ->  "+(typeof detail==="string"?detail:JSON.stringify(detail)):""))}
const eq=(a,b)=>JSON.stringify(a)===JSON.stringify(b)
const VEC="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H"
const V4="CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N"
const XSS='<img src=x onerror=alert(1)><script>alert(2)</script>"\'&'
const NVD="https://nvd.nist.gov/vuln/detail/CVE-2021-44228"
const ORG="https://www.cve.org/CVERecord?id=CVE-2021-44228"
const KEV="https://www.cisa.gov/known-exploited-vulnerabilities-catalog?search_api_fulltext=CVE-2021-44228"
function payload(over){
return Object.assign({cve_id:"CVE-2021-44228",title:"Apache Log4j2 JNDI remote code execution",severity:"critical",cvss:{version:"3.1",vector:VEC,score:10},cvss_all:{v31:{vector:VEC,score:10,severity:"critical"},v40:null},cvss_vector:VEC,cvss_score:10,
cwe:"CWE-502",cwes:["CWE-502","CWE-20"],description:"Log4j2 JNDI features do not protect against attacker controlled LDAP endpoints.",impact:"Remote code execution as the service account.",
remediation:"Fix:\nUpgrade to 2.17.1 or later.\n\nWorkaround:\nRemove the JndiLookup class.",references:[{url:"https://logging.apache.org/log4j/2.x/security.html",tags:["Vendor Advisory"]}],reference_urls:["https://logging.apache.org/log4j/2.x/security.html",NVD],
affected:["apache log4j 2.0 - 2.14.1"],kev:{in_kev:true,date_added:"2021-12-10",due_date:"2021-12-24",required_action:"Apply updates",ransomware:"Known"},epss:{score:0.97,percentile:0.99,date:"2026-11-20"},tags:["cve","kev"],source:"cve:CVE-2021-44228",origin:"cache",fetched_at:"2026-11-20T10:00:00Z",stale:false},over||{})
}
const blank={title:"New finding",severity:"medium",cvss_vector:"",cvss_score:null,cwe:"",description:"",impact:"",remediation:"",references:[],cves:[]}
const written={title:"Outdated Log4j on app01",severity:"high",cvss_vector:"CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",cvss_score:9.8,cwe:"CWE-1104",description:"<p>My own words.</p>",impact:"",remediation:"<p>Patch it.</p>",references:["Internal ticket SEC-42","https://example.com/mine"],cves:[]}

// ---- ids ----
check("normId accepts the usual spellings",CV.normId("cve-2021-44228")==="CVE-2021-44228"&&CV.normId(" CVE 2021 44228 ")==="CVE-2021-44228"&&CV.normId("2021-44228")==="CVE-2021-44228"&&CV.normId("CVE_2021_44228")==="CVE-2021-44228")
check("normId refuses anything else",["","CVE-21-1","CVE-2021-123","CVE-2021-44228x","<script>","CVE-2021-44228 OR 1=1","CVE-2021-","20211-4422",null,undefined,{}].every((v)=>CV.normId(v)===""))
check("isId is strict",CV.isId("CVE-2021-44228")&&CV.isId("CVE-2024-1234567")&&!CV.isId("cve-2021-44228")&&!CV.isId("CVE-2021-442")&&!CV.isId(5))
check("extractIds finds every id once, in order, uppercased",eq(CV.extractIds("see cve-2021-44228, CVE-2021-45046 and CVE-2021-44228 again; CVE 2017 0144; not CVE-1-2 or XCVE-2020-0001"),["CVE-2021-44228","CVE-2021-45046","CVE-2017-0144"]),CV.extractIds("see cve-2021-44228, CVE-2021-45046 and CVE-2021-44228 again; CVE 2017 0144; not CVE-1-2 or XCVE-2020-0001"))
check("extractIds on nothing",eq(CV.extractIds(""),[])&&eq(CV.extractIds(null),[])&&eq(CV.extractIds("log4j"),[]))

// ---- urls and references ----
check("safeUrl keeps http(s) only",CV.safeUrl("https://a.example/x?y=1")==="https://a.example/x?y=1"&&CV.safeUrl("HTTP://a.example")==="HTTP://a.example")
check("safeUrl refuses scripts, other schemes and markup",["javascript:alert(1)","data:text/html,x","file:///etc/passwd","ftp://a.example","//a.example","https://a.example/\"onmouseover=x","https://a.example/<b>","https://a b.example","https://a.example/`x`","",null,"https://"+"a".repeat(1200)].every((u)=>CV.safeUrl(u)===""))
check("dedupeRefs drops bad urls and repeats (scheme, case, trailing slash)",eq(CV.dedupeRefs(["https://a.example/x","HTTPS://A.example/x/","http://a.example/x","javascript:alert(1)",{url:"https://b.example"},null,"https://c.example"]),["https://a.example/x","https://b.example","https://c.example"]),CV.dedupeRefs(["https://a.example/x","HTTPS://A.example/x/","http://a.example/x","javascript:alert(1)",{url:"https://b.example"},null,"https://c.example"]))
check("dedupeRefs caps",CV.dedupeRefs(Array.from({length:40},(_x,i)=>"https://a.example/"+i),5).length===5)
check("links: NVD, cve.org and KEV only when exploited",eq(CV.links("cve-2021-44228",false),[NVD,ORG])&&eq(CV.links("CVE-2021-44228",true),[NVD,ORG,KEV])&&eq(CV.links("nope",true),[]))

// ---- plain text -> rich subset ----
check("plainToHtml escapes remote text",CV.plainToHtml(XSS)==="<p>&lt;img src=x onerror=alert(1)&gt;&lt;script&gt;alert(2)&lt;/script&gt;&quot;&#39;&amp;</p>",CV.plainToHtml(XSS))
check("plainToHtml output survives the sanitiser unchanged and holds no tag from the text",(()=>{const h=CV.plainToHtml("a "+XSS+"\n\nb <a href=\"javascript:alert(1)\">x</a>\n<iframe src=x>");return RC.sanitizeHtml(h)===h&&!/<(img|script|a|iframe)\b/i.test(h)})())
check("plainToHtml paragraphs, line breaks and bold section labels",CV.plainToHtml("Fix:\r\nUpgrade to 2.17.1.\n\n\nWorkaround:\nRemove the class.\nRestart.")==="<p><strong>Fix:</strong><br>Upgrade to 2.17.1.</p><p><strong>Workaround:</strong><br>Remove the class.<br>Restart.</p>",CV.plainToHtml("Fix:\r\nUpgrade to 2.17.1.\n\n\nWorkaround:\nRemove the class.\nRestart."))
check("plainToHtml turns dash lines into a list and keeps the text around it",CV.plainToHtml("Vendor guidance:\n- https://a.example/x (Patch)\n- <b>y</b>\nDetection:\n* watch logs\n\nEnd - not a list")==="<p><strong>Vendor guidance:</strong></p><ul><li>https://a.example/x (Patch)</li><li>&lt;b&gt;y&lt;/b&gt;</li></ul><p><strong>Detection:</strong></p><ul><li>watch logs</li></ul><p>End - not a list</p>",CV.plainToHtml("Vendor guidance:\n- https://a.example/x (Patch)\n- <b>y</b>\nDetection:\n* watch logs\n\nEnd - not a list"))
check("the list form also survives the sanitiser unchanged",(()=>{const h=CV.plainToHtml("A:\n- one "+XSS+"\n- two");return RC.sanitizeHtml(h)===h})())
check("plainToHtml of nothing is empty",CV.plainToHtml("")===""&&CV.plainToHtml(null)===""&&CV.plainToHtml(" \n \n ")==="")
check("a hostile label line is still escaped",CV.plainToHtml("<b>x</b>:")==="<p><strong>&lt;b&gt;x&lt;/b&gt;:</strong></p>")
check("richEmpty",CV.richEmpty("")&&CV.richEmpty("<p><br></p>")&&CV.richEmpty("<p> </p>")&&!CV.richEmpty("<p>x</p>")&&!CV.richEmpty('<p><img src="rptasset:abcdef12"></p>'))

// ---- entries ----
const entry=CV.entryFromPayload(payload())
check("entryFromPayload",eq(entry,{id:"CVE-2021-44228",title:"Apache Log4j2 JNDI remote code execution",cvss_version:"3.1",cvss_vector:VEC,cvss_score:10,severity:"critical",cwe:"CWE-502",description:"Log4j2 JNDI features do not protect against attacker controlled LDAP endpoints.",
remediation:"Fix:\nUpgrade to 2.17.1 or later.\n\nWorkaround:\nRemove the JndiLookup class.",references:["https://logging.apache.org/log4j/2.x/security.html",NVD],kev:true,kev_due:"2021-12-24",epss:0.97,source:"cache",fetched_at:"2026-11-20T10:00:00Z"}),entry)
check("a live record is marked live",CV.entryFromPayload(payload({origin:"live"})).source==="live")
check("entry text stays plain (escaped only where shown)",CV.entryFromPayload(payload({title:XSS,description:XSS})).title===XSS.trim())
check("a payload without a valid id gives no entry",CV.entryFromPayload(payload({cve_id:"<script>"}))===null&&CV.entryFromPayload(null)===null&&CV.entryFromPayload({})===null)
check("normEntry caps and validates",(()=>{const e=CV.normEntry({id:"cve-2024-3094",title:"t".repeat(900),cvss_version:"9",cvss_score:"11",severity:"bogus",description:"d".repeat(30000),references:["javascript:alert(1)"].concat(Array.from({length:60},(_x,i)=>"https://a.example/"+i)),kev:"yes",epss:7,source:"evil"});return e.id==="CVE-2024-3094"&&e.title.length===300&&e.cvss_version===""&&e.cvss_score===null&&e.severity===""&&e.description.length===20000&&e.references.length===30&&e.kev===false&&e.epss===null&&e.source==="manual"})())
check("normEntry: severity falls back to the score",CV.normEntry({id:"CVE-2024-3094",cvss_score:9.3}).severity==="critical"&&CV.normEntry({id:"CVE-2024-3094",cvss_score:"5,5"}).cvss_score===5.5)
check("normList drops bad ids, repeats and caps at 50",(()=>{const l=CV.normList([{id:"CVE-2021-44228"},{id:"cve-2021-44228"},{id:"x"},null,"CVE-2020-0601"].concat(Array.from({length:80},(_x,i)=>({id:"CVE-2024-"+(10000+i)}))));return l.length===50&&l[0].id==="CVE-2021-44228"&&l[1].id==="CVE-2024-10000"})())
check("addCve appends, replaces the same id and respects the cap",(()=>{const a=CV.addCve([],entry);const b=CV.addCve(a,Object.assign({},entry,{title:"new"}));const c=CV.addCve(b,{id:"CVE-2020-0601"});const full=CV.normList(Array.from({length:50},(_x,i)=>({id:"CVE-2024-"+(10000+i)})));return a.length===1&&b.length===1&&b[0].title==="new"&&eq(c.map((x)=>x.id),["CVE-2021-44228","CVE-2020-0601"])&&CV.addCve(full,entry).length===50&&CV.addCve(a,{id:"bad"}).length===1})())
check("removeCve",eq(CV.removeCve([entry,{id:"CVE-2020-0601"}],"cve-2021-44228").map((x)=>x.id),["CVE-2020-0601"])&&CV.removeCve([entry],"CVE-0000-0000").length===1)
check("chipLabel and idsText",CV.chipLabel(entry)==="CVE-2021-44228 · 10.0"&&CV.chipLabel({id:"CVE-2020-0601",cvss_score:null})==="CVE-2020-0601"&&CV.idsText([entry,{id:"CVE-2020-0601"}])==="CVE-2021-44228, CVE-2020-0601")
check("chipTitle names the rating, KEV and where it came from",/Critical 10\.0 \(CVSS 3\.1\)/.test(CV.chipTitle(entry))&&/Known exploited/.test(CV.chipTitle(entry))&&/From CVE Intel/.test(CV.chipTitle(entry))&&/Entered by hand/.test(CV.chipTitle({id:"CVE-2020-0601",source:"manual"})))

// ---- CVSS: 3.1 for the finding, 4.0 stays on the entry ----
const both=payload({cvss:{version:"4.0",vector:V4,score:9.3},cvss_all:{v31:{vector:VEC,score:10,severity:"critical"},v40:{vector:V4,score:9.3,severity:"critical"}},cvss_vector:V4,cvss_score:9.3})
check("CVE Intel rates in 4.0 and a 3.1 exists: the finding takes 3.1, the CVE keeps its 4.0 vector",eq(CV.pickCvss(both).finding,{vector:VEC,score:10,version:"3.1"})&&(()=>{const e=CV.entryFromPayload(both);return e.cvss_version==="4.0"&&e.cvss_vector===V4&&e.cvss_score===9.3})())
check("that fallback is said in so many words",CV.pickCvss(both).note==="v31_fallback"&&CV.incomingFrom(both).cvss_note==="Using the CVSS 3.1 vector; the 4.0 vector is kept on the CVE.")
check("a 3.1 default rating keeps 3.1 on both sides, without a note",(()=>{const p=payload({cvss_all:{v31:{vector:VEC,score:10,severity:"critical"},v40:{vector:V4,score:9.3,severity:"critical"}}});return CV.entryFromPayload(p).cvss_version==="3.1"&&CV.pickCvss(p).note===""&&CV.incomingFrom(p).cvss_note===""})())
const only4=payload({cvss:{version:"4.0",vector:V4,score:9.3},cvss_all:{v31:null,v40:{vector:V4,score:9.3,severity:"critical"}},cvss_vector:V4,cvss_score:9.3})
check("v4.0 only: the finding takes the score without a vector",eq(CV.pickCvss(only4).finding,{vector:"",score:9.3,version:"4.0"})&&CV.incomingFrom(only4).cvss.vector==="")
check("v4.0 only: the note says the score is 4.0 and read-only",CV.pickCvss(only4).note==="v40_only"&&/CVSS 4\.0 only/.test(CV.incomingFrom(only4).cvss_note))
check("v4.0 only: the finding's score is labelled CVSS 4.0, never 3.1",(()=>{const f=CV.findingFrom(only4);return f.cvss_vector===""&&f.cvss_score===9.3&&CV.findingCvssVersion(f)==="4.0"&&CV.findingCvssLabel(f)==="CVSS 4.0"})())
check("score labels: own vector is 3.1, a bare score without a matching CVE has no version",CV.findingCvssLabel({cvss_vector:VEC,cvss_score:10})==="CVSS 3.1"&&CV.findingCvssLabel({cvss_vector:"",cvss_score:5,cves:[{id:"CVE-2024-1234",cvss_version:"4.0",cvss_score:9.3}]})==="CVSS"&&CV.findingCvssVersion({})==="")
check("an offline-index payload gives a summary entry with source index",(()=>{const p=payload({origin:"index",stale:true,description:"",cvss:{version:"4.0",vector:V4,score:9.3},cvss_all:{v31:null,v40:{vector:V4,score:9.3,severity:"critical"}}});const e=CV.entryFromPayload(p);return e.source==="index"&&e.cvss_version==="4.0"&&CV.normEntry({id:"CVE-2024-1234",source:"index"}).source==="index"&&CV.normEntry({id:"CVE-2024-1234",source:"bogus"}).source==="manual"&&/offline index/.test(CV.sourceText(e))&&!!CV.findingFrom(p)})())
check("v4.0 only: the entry keeps the 4.0 vector and score",(()=>{const e=CV.entryFromPayload(only4);return e.cvss_version==="4.0"&&e.cvss_vector===V4&&e.cvss_score===9.3})())
check("a 3.0 vector is taken as 3.1",CV.pickCvss(payload({cvss:{version:"3.0",vector:"CVSS:3.0/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",score:9.8},cvss_all:{}})).finding.vector==="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H")
check("an unrated CVE offers no CVSS",CV.pickCvss(payload({cvss:{version:"",vector:"",score:null},cvss_all:{},cvss_vector:"",cvss_score:null})).finding===null&&CV.incomingFrom(payload({cvss:null,cvss_all:null,cvss_vector:"",cvss_score:null})).cvss===null)
check("a broken vector is not passed to the finding",CV.pickCvss(payload({cvss:{version:"3.1",vector:"CVSS:3.1/AV:X",score:7},cvss_all:{}})).finding.vector==="")

// ---- incoming ----
const inc=CV.incomingFrom(payload())
check("incoming fields are in the finding's formats",inc.id==="CVE-2021-44228"&&inc.title==="Apache Log4j2 JNDI remote code execution"&&inc.severity==="critical"&&inc.cwe==="CWE-502"&&inc.description==="<p>Log4j2 JNDI features do not protect against attacker controlled LDAP endpoints.</p>"&&inc.impact==="<p>Remote code execution as the service account.</p>"&&/^<p><strong>Fix:<\/strong><br>Upgrade/.test(inc.remediation))
check("incoming references: NVD, cve.org, KEV, then the record's links, no repeats",eq(inc.references,[NVD,ORG,KEV,"https://logging.apache.org/log4j/2.x/security.html"]),inc.references)
check("no KEV link when the CVE is not in KEV",CV.incomingFrom(payload({kev:null})).references.indexOf(KEV)<0&&CV.incomingFrom(payload({kev:{in_kev:false}})).references.indexOf(KEV)<0)
check("hostile remote text is escaped in every rich field",(()=>{const h=CV.incomingFrom(payload({description:XSS,impact:XSS,remediation:XSS}));return [h.description,h.impact,h.remediation].every((x)=>!/<(img|script)/i.test(x)&&x.indexOf("&lt;script&gt;")>0&&RC.sanitizeHtml(x)===x)})())
check("hostile reference urls never reach the finding",CV.incomingFrom(payload({reference_urls:["javascript:alert(1)","https://ok.example/","data:x"],references:[]})).references.every((u)=>/^https:\/\//.test(u)))
check("reference objects are used when no url list is given",CV.incomingFrom(payload({reference_urls:null})).references.indexOf("https://logging.apache.org/log4j/2.x/security.html")>=0)
check("incomingFromEntry offers what was typed by hand",(()=>{const i=CV.incomingFromEntry({id:"CVE-2024-3094",title:"xz backdoor",cvss_version:"4.0",cvss_vector:V4,cvss_score:9.3,description:"<b>bad</b>",remediation:"Downgrade.",references:["https://x.example/a"],kev:false});return i.title==="xz backdoor"&&i.cvss.vector===""&&i.cvss.score===9.3&&i.severity==="critical"&&i.description==="<p>&lt;b&gt;bad&lt;/b&gt;</p>"&&i.remediation==="<p>Downgrade.</p>"&&i.impact===""&&eq(i.references,["https://nvd.nist.gov/vuln/detail/CVE-2024-3094","https://www.cve.org/CVERecord?id=CVE-2024-3094","https://x.example/a"])})())

// ---- merge plan: defaults ----
const byKey=(rows)=>{const o={};rows.forEach((r)=>{o[r.key]=r});return o}
let plan=byKey(CV.mergePlan(blank,inc))
check("empty finding: every field is offered and defaults to Fill",eq(Object.keys(plan),["title","severity","cvss","cwe","description","impact","remediation","references"])&&Object.keys(plan).every((k)=>plan[k].choice==="fill"&&plan[k].empty),CV.planChoices(CV.mergePlan(blank,inc)))
check("empty fields offer Fill and Keep only",Object.keys(plan).every((k)=>eq(plan[k].options,["fill","keep"])))
plan=byKey(CV.mergePlan(written,inc))
check("written fields default to Keep, empty ones to Fill, references to Append",eq(CV.planChoices(CV.mergePlan(written,inc)),{title:"keep",severity:"keep",cvss:"keep",cwe:"keep",description:"keep",impact:"fill",remediation:"keep",references:"append"}),CV.planChoices(CV.mergePlan(written,inc)))
check("Fill is only offered for an empty field",Object.keys(plan).every((k)=>(plan[k].options.indexOf("fill")>=0)===plan[k].empty))
check("Append is offered for text and list fields only",eq(plan.description.options,["keep","append","replace"])&&eq(plan.references.options,["keep","append","replace"])&&eq(plan.title.options,["keep","replace"])&&eq(plan.cvss.options,["keep","replace"])&&eq(plan.severity.options,["keep","replace"])&&eq(plan.cwe.options,["keep","replace"]))
check("the rows show current and incoming previews as plain text",plan.description.current==="My own words."&&/^Log4j2 JNDI/.test(plan.description.incoming)&&plan.cvss.current==="9.8  CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"&&plan.cvss.incoming==="10.0  "+VEC&&plan.severity.current==="High"&&plan.severity.incoming==="Critical"&&plan.references.incoming==="4 links (4 new)"&&plan.references.current==="2 references")
check("fields the CVE has nothing for are not offered",eq(CV.mergePlan(blank,CV.incomingFrom(payload({impact:"",cwe:"",remediation:" "}))).map((r)=>r.key),["title","severity","cvss","description","references"]))
check("a second CVE keeps everything and only appends references",(()=>{const f=Object.assign({},blank,{title:"x",cves:[{id:"CVE-2020-0601"}]});return eq(CV.planChoices(CV.mergePlan(f,inc)),{title:"keep",severity:"keep",cvss:"keep",cwe:"keep",description:"keep",impact:"keep",remediation:"keep",references:"fill"})&&eq(CV.planChoices(CV.mergePlan(Object.assign({},written,{cves:[{id:"CVE-2020-0601"}]}),inc)).references,"append")})())
check("refreshing the CVE that is already on the finding is not a second CVE",CV.planChoices(CV.mergePlan(Object.assign({},blank,{cves:[{id:"CVE-2021-44228"}]}),inc)).title==="fill")
check("identical values are marked the same and kept",(()=>{const f=Object.assign({},blank,{title:inc.title,cwe:"CWE-502",cvss_vector:VEC,cvss_score:10,severity:"critical",description:inc.description,references:inc.references.slice()});const p=byKey(CV.mergePlan(f,inc));return ["title","cwe","cvss","severity","description","references"].every((k)=>p[k].same&&p[k].choice==="keep")&&!p.impact.same})())
check("the default severity of a new finding counts as empty, a chosen one does not",byKey(CV.mergePlan(blank,inc)).severity.empty&&!byKey(CV.mergePlan(Object.assign({},blank,{title:"Mine"}),inc)).severity.empty&&byKey(CV.mergePlan(Object.assign({},blank,{title:"Mine",severity:"info"}),inc)).severity.empty)
check("a default title counts as empty",byKey(CV.mergePlan(Object.assign({},blank,{title:"Untitled finding"}),inc)).title.empty&&byKey(CV.mergePlan(Object.assign({},blank,{title:""}),inc)).title.empty&&!byKey(CV.mergePlan(written,inc)).title.empty)
check("the plan never throws on junk",(()=>{try{return CV.mergePlan(null,null).length===0&&CV.mergePlan({},{}).length===0&&eq(CV.applyMerge(null,null,null),{})}catch(e){return false}})())

// ---- applying a merge ----
let patch=CV.applyMerge(blank,inc,CV.planChoices(CV.mergePlan(blank,inc)))
check("defaults on an empty finding fill everything",eq(patch,{title:inc.title,severity:"critical",cvss_vector:VEC,cvss_score:10,cwe:"CWE-502",description:inc.description,impact:inc.impact,remediation:inc.remediation,references:inc.references}),patch)
patch=CV.applyMerge(written,inc,CV.planChoices(CV.mergePlan(written,inc)))
check("defaults on a written finding never overwrite",eq(patch,{impact:inc.impact,references:["Internal ticket SEC-42","https://example.com/mine",NVD,ORG,KEV,"https://logging.apache.org/log4j/2.x/security.html"]}),patch)
check("all Keep changes nothing",eq(CV.applyMerge(written,inc,{title:"keep",severity:"keep",cvss:"keep",cwe:"keep",description:"keep",impact:"keep",remediation:"keep",references:"keep"}),{}))
patch=CV.applyMerge(written,inc,{title:"replace",severity:"replace",cvss:"replace",cwe:"replace",description:"replace",impact:"fill",remediation:"replace",references:"replace"})
check("Replace takes the CVE's value",eq(patch,{title:inc.title,severity:"critical",cvss_vector:VEC,cvss_score:10,cwe:"CWE-502",description:inc.description,impact:inc.impact,remediation:inc.remediation,references:inc.references}),patch)
patch=CV.applyMerge(written,inc,{description:"append",remediation:"append",references:"append"})
check("Append keeps the user's text first and marks the CVE's part",patch.description==="<p>My own words.</p><p><strong>CVE-2021-44228</strong></p>"+inc.description&&patch.remediation.indexOf("<p>Patch it.</p><p><strong>CVE-2021-44228</strong></p>")===0&&Object.keys(patch).length===3,patch)
check("appended rich text is still inside the stored subset",RC.sanitizeHtml(patch.description)===patch.description)
check("Append on references de-dupes against what is listed and keeps non-links",eq(CV.applyMerge(Object.assign({},written,{references:["Internal ticket SEC-42",NVD+"/","HTTP://www.cve.org/CVERecord?id=CVE-2021-44228"]}),inc,{references:"append"}),{references:["Internal ticket SEC-42",NVD+"/","HTTP://www.cve.org/CVERecord?id=CVE-2021-44228",KEV,"https://logging.apache.org/log4j/2.x/security.html"]}))
check("Fill on a field that is not empty is refused",eq(CV.applyMerge(written,inc,{title:"fill",description:"fill",cvss:"fill",references:"fill"}),{}))
check("an unknown mode or a mode the row does not offer is ignored",eq(CV.applyMerge(written,inc,{title:"append",cwe:"append",severity:"drop",description:"<script>"}),{}))
check("a v4.0-only CVE fills the score and clears no vector text",eq(CV.applyMerge(blank,CV.incomingFrom(only4),{cvss:"fill"}),{cvss_vector:"",cvss_score:9.3}))
check("applyMerge does not touch its inputs",(()=>{const f=JSON.parse(JSON.stringify(written)),i=JSON.parse(JSON.stringify(inc));CV.applyMerge(f,i,{description:"append",references:"append",title:"replace"});return eq(f,written)&&eq(i,inc)})())

// ---- new finding / references ----
const nf=CV.findingFrom(payload())
check("findingFrom writes a whole finding",nf.title===inc.title&&nf.severity==="critical"&&nf.status==="open"&&nf.cvss_vector===VEC&&nf.cvss_score===10&&nf.cwe==="CWE-502"&&nf.description===inc.description&&nf.impact===inc.impact&&nf.remediation===inc.remediation&&eq(nf.references,inc.references)&&eq(nf.tags,["cve","kev"])&&eq(nf.source,{kind:"cve",ref:"CVE-2021-44228"})&&eq(nf.cves,[entry]),nf)
check("findingFrom falls back to the id as the title and info as the severity",(()=>{const f=CV.findingFrom(payload({title:"",severity:"",cvss:null,cvss_all:null,cvss_vector:"",cvss_score:null}));return f.title==="CVE-2021-44228"&&f.severity==="info"&&f.cvss_score===null&&f.cvss_vector===""})())
check("findingFrom of a bad payload is null",CV.findingFrom({cve_id:"x"})===null&&CV.findingFrom(null)===null)
check("findingFromEntry (manual entry) carries the entry and tags",(()=>{const f=CV.findingFromEntry({id:"cve-2024-3094",title:"xz backdoor",cvss_version:"4.0",cvss_vector:V4,cvss_score:9.3,kev:true});return f.title==="xz backdoor"&&f.cvss_vector===""&&f.cvss_score===9.3&&f.severity==="critical"&&f.cves[0].cvss_vector===V4&&f.cves[0].source==="manual"&&eq(f.tags,["cve","kev"])&&f.source.ref==="CVE-2024-3094"&&CV.findingFromEntry({id:"x"})===null})())
check("withLinks adds only the missing links and keeps the rest",eq(CV.withLinks(["note",NVD],{id:"CVE-2021-44228",kev:true}),["note",NVD,ORG,KEV])&&CV.withLinks([NVD,ORG],{id:"CVE-2021-44228",kev:false})===null&&eq(CV.withLinks(null,{id:"CVE-2021-44228"}),[NVD,ORG]))

// ---- the page code: wiring that cannot run without a DOM ----
const js=fs.readFileSync(path.join(ROOT,"UI","js","pages","reporting_findings.js"),"utf8")
const css=fs.readFileSync(path.join(ROOT,"UI","css","pages","reporting_findings.css"),"utf8")
const cveUi=js.slice(js.indexOf("// ---- CVEs: picker"),js.indexOf("// ---- the workspace ----"))
check("the CVE dialogs were found",cveUi.length>3000)
check("search results reach the page as text or through esc()/numbers only",!/innerHTML\s*=\s*[^\n]*\b(r|row|payload|entry|e|c)\.(title|description|remediation|id|cwe)\b(?![^\n]*esc\()/.test(cveUi.replace(/cveBadges\([^\n]*?\)\)?/g,"")))
check("badges escape what they print",/function cveBadges[\s\S]{0,400}RW\.severityBadge\(sv\)/.test(cveUi)&&/esc\(c\.cvss_version\)/.test(cveUi))
check("links open through the bridge after the https check",/function openUrl\(url\)\{\nconst u=CV\.safeUrl\(url\)\nif\(u\)bridgeCall\("notes\.open_url",\[u\]\)/.test(cveUi)&&!/window\.open|location\.href/.test(cveUi))
check("a missing cve bridge leaves manual entry",/status===null\)\{manual\(/.test(cveUi)&&/bridge method missing/.test(cveUi))
check("the picker searches the cache per keystroke (debounced) and only fetches on a choice",/setTimeout\(run,180\)/.test(cveUi)&&/cveCall\("search",kevOnly\.checked\?\[q,20,\{kev_only:true\}\]:\[q,20\]\)/.test(cveUi)&&(cveUi.match(/cveCall\("to_finding"/g)||[]).length===1)
check("keyboard: arrows move, Enter chooses",/e\.key==="ArrowDown"\|\|e\.key==="ArrowUp"/.test(cveUi)&&/e\.key==="Enter"/.test(cveUi))
check("a merge is one patch (one undo step)",/function writeCves\(id,cves,fields\)\{[\s\S]{0,200}const p=Object\.assign\(\{\},fields\|\|\{\},\{cves:cves\}\)\npatch\(id,p\)/.test(js))
check("the list tooltip and the editor name the score's real CVSS version",!/title="CVSS 3\.1 base score"/.test(js)&&/CV\.findingCvssLabel\(f\)/.test(js)&&/CV\.findingCvssVersion\(f\)/.test(js)&&/rpt-cvss-v4-note/.test(js))
check("offline-index rows are labelled and stay pickable",/r\.origin==="index"\|\|r\.index_only===true/.test(js)&&/"offline index"/.test(js))
check("a new finding from a CVE goes through addFinding (the normal add op)",/onPick:\(payload\)=>\{\nconst fields=CV\.findingFrom\(payload\)\ncreate\(/.test(js)&&/addFinding\(fields,false\)/.test(js))
check("the workspace still works when the helper script is not loaded",/const CV=typeof ReportCve!=="undefined"\?ReportCve:null/.test(js)&&(js.match(/\nif\(CV\)\{/g)||[]).length===2)
check("no web storage",!/localStorage|sessionStorage/.test(js)&&!/localStorage|sessionStorage/.test(fs.readFileSync(path.join(ROOT,"UI","js","pages","reporting_cve_core.js"),"utf8")))
check("user-select is prefixed too",(css.match(/[^-]user-select:/g)||[]).length===(css.match(/-webkit-user-select:/g)||[]).length)
check("CVE buttons inherit the app font",/\.rpt-cve-row\{[^}]*font-family:inherit/.test(css)&&/\.rpt-cve-opt\{[^}]*font-family:inherit/.test(css)&&/\.rpt-cve-chip-main\{[^}]*font-family:inherit/.test(css))
console.log(`\nreporting_cve: ${passed} passed, ${failed} failed`)
process.exit(failed?1:0)
