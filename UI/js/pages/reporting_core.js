// Reporting: pure logic shared by the page, the widgets and the Node tests (no DOM here; also loaded with require()).
var ReportCore=(function(){
const SEVERITIES=[
{id:"critical",label:"Critical",color:"#9b1c1c"},
{id:"high",label:"High",color:"#dc2626"},
{id:"medium",label:"Medium",color:"#f59e0b"},
{id:"low",label:"Low",color:"#2563eb"},
{id:"info",label:"Informational",color:"#6b7280"}
]
const STATUSES=[
{id:"open",label:"Open"},
{id:"retest",label:"Retest"},
{id:"fixed",label:"Fixed"},
{id:"accepted",label:"Risk accepted"}
]
const LIKELIHOODS=[{id:"",label:"Not set"},{id:"low",label:"Low"},{id:"medium",label:"Medium"},{id:"high",label:"High"}]
const OWASP_TOP10=[
"A01:2021 Broken Access Control","A02:2021 Cryptographic Failures","A03:2021 Injection","A04:2021 Insecure Design",
"A05:2021 Security Misconfiguration","A06:2021 Vulnerable and Outdated Components","A07:2021 Identification and Authentication Failures",
"A08:2021 Software and Data Integrity Failures","A09:2021 Security Logging and Monitoring Failures","A10:2021 Server-Side Request Forgery (SSRF)"
]
const COMMON_CWES=[
["CWE-20","Improper Input Validation"],["CWE-22","Path Traversal"],["CWE-77","Command Injection"],["CWE-78","OS Command Injection"],
["CWE-79","Cross-site Scripting"],["CWE-89","SQL Injection"],["CWE-94","Code Injection"],["CWE-119","Memory Buffer Bounds"],
["CWE-125","Out-of-bounds Read"],["CWE-190","Integer Overflow"],["CWE-200","Exposure of Sensitive Information"],["CWE-209","Error Message Information Leak"],
["CWE-250","Execution with Unnecessary Privileges"],["CWE-269","Improper Privilege Management"],["CWE-284","Improper Access Control"],
["CWE-285","Improper Authorization"],["CWE-287","Improper Authentication"],["CWE-295","Improper Certificate Validation"],
["CWE-306","Missing Authentication for Critical Function"],["CWE-307","Improper Restriction of Authentication Attempts"],
["CWE-311","Missing Encryption of Sensitive Data"],["CWE-312","Cleartext Storage of Sensitive Information"],
["CWE-319","Cleartext Transmission of Sensitive Information"],["CWE-326","Inadequate Encryption Strength"],
["CWE-327","Broken or Risky Cryptographic Algorithm"],["CWE-330","Insufficiently Random Values"],["CWE-345","Insufficient Verification of Data Authenticity"],
["CWE-352","Cross-Site Request Forgery"],["CWE-384","Session Fixation"],["CWE-400","Uncontrolled Resource Consumption"],
["CWE-416","Use After Free"],["CWE-434","Unrestricted File Upload"],["CWE-502","Deserialization of Untrusted Data"],
["CWE-521","Weak Password Requirements"],["CWE-522","Insufficiently Protected Credentials"],["CWE-532","Sensitive Information in Log File"],
["CWE-548","Directory Listing"],["CWE-601","Open Redirect"],["CWE-611","XML External Entity Reference"],["CWE-613","Insufficient Session Expiration"],
["CWE-614","Sensitive Cookie Without Secure Attribute"],["CWE-639","Insecure Direct Object Reference"],["CWE-693","Protection Mechanism Failure"],
["CWE-732","Incorrect Permission Assignment"],["CWE-787","Out-of-bounds Write"],["CWE-798","Hard-coded Credentials"],
["CWE-862","Missing Authorization"],["CWE-863","Incorrect Authorization"],["CWE-918","Server-Side Request Forgery"],
["CWE-942","Permissive Cross-domain Policy"],["CWE-1004","Sensitive Cookie Without HttpOnly"],["CWE-1021","Clickjacking"],
["CWE-1104","Use of Unmaintained Third Party Components"],["CWE-1392","Use of Default Credentials"]
]

function sevLabel(id){
const s=SEVERITIES.find((x)=>x.id===id)
return s?s.label:"Informational"
}
function sevRank(id){
const i=SEVERITIES.findIndex((x)=>x.id===id)
return i<0?SEVERITIES.length-1:i
}
function statusLabel(id){
const s=STATUSES.find((x)=>x.id===id)
return s?s.label:"Open"
}
function sevFromScore(score){
const n=Number(score)
if(score===null||score===undefined||score===""||!isFinite(n)||n<=0)return "info"
if(n<4)return "low"
if(n<7)return "medium"
if(n<9)return "high"
return "critical"
}
function escapeHtml(s){
return String(s===undefined||s===null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")
}

// ---- CVSS v3.1 base score (FIRST specification, section 7 and appendix A) ----
const CVSS_ORDER=["AV","AC","PR","UI","S","C","I","A"]
const CVSS_METRICS=[
{key:"AV",name:"Attack Vector",help:"How remote the attacker can be.",values:[
{v:"N",label:"Network",help:"Exploitable remotely over the network, across routers."},
{v:"A",label:"Adjacent",help:"Needs the same physical or logical network (LAN, Bluetooth, VPN)."},
{v:"L",label:"Local",help:"Needs local access, or the user opening something."},
{v:"P",label:"Physical",help:"Needs to physically touch the device."}]},
{key:"AC",name:"Attack Complexity",help:"Conditions beyond the attacker's control.",values:[
{v:"L",label:"Low",help:"No special conditions; works reliably."},
{v:"H",label:"High",help:"Depends on conditions the attacker must prepare for (race, MITM position, secrets)."}]},
{key:"PR",name:"Privileges Required",help:"Privileges needed before the attack.",values:[
{v:"N",label:"None",help:"Unauthenticated."},
{v:"L",label:"Low",help:"A basic user account."},
{v:"H",label:"High",help:"Administrative privileges."}]},
{key:"UI",name:"User Interaction",help:"Whether another person must take part.",values:[
{v:"N",label:"None",help:"No victim action needed."},
{v:"R",label:"Required",help:"A user must do something (click a link, open a file)."}]},
{key:"S",name:"Scope",help:"Whether the impact crosses a security boundary.",values:[
{v:"U",label:"Unchanged",help:"Impact stays within the vulnerable component's authority."},
{v:"C",label:"Changed",help:"Impact reaches components under another authority (sandbox escape, XSS to browser)."}]},
{key:"C",name:"Confidentiality",help:"Impact on information disclosure.",values:[
{v:"H",label:"High",help:"All data, or critical data, disclosed."},
{v:"L",label:"Low",help:"Some data disclosed without control over what."},
{v:"N",label:"None",help:"No loss of confidentiality."}]},
{key:"I",name:"Integrity",help:"Impact on trustworthiness of data.",values:[
{v:"H",label:"High",help:"Attacker can modify any data, or critical data."},
{v:"L",label:"Low",help:"Limited modification without serious consequence."},
{v:"N",label:"None",help:"No loss of integrity."}]},
{key:"A",name:"Availability",help:"Impact on availability of the component.",values:[
{v:"H",label:"High",help:"Full denial of service, sustained or persistent."},
{v:"L",label:"Low",help:"Reduced performance or intermittent interruptions."},
{v:"N",label:"None",help:"No impact on availability."}]}
]
const CVSS_W={
AV:{N:0.85,A:0.62,L:0.55,P:0.2},
AC:{L:0.77,H:0.44},
PR:{N:0.85,L:0.62,H:0.27},
UI:{N:0.85,R:0.62},
S:{U:1,C:1},
C:{H:0.56,L:0.22,N:0},
I:{H:0.56,L:0.22,N:0},
A:{H:0.56,L:0.22,N:0}
}
// Temporal and environmental metrics are accepted in a pasted vector and ignored: only the base score is used.
const CVSS_EXTRA={E:"XUPFH",RL:"XOTWU",RC:"XURC",CR:"XLMH",IR:"XLMH",AR:"XLMH",MAV:"XNALP",MAC:"XLH",MPR:"XNLH",MUI:"XNR",MS:"XUC",MC:"XNLH",MI:"XNLH",MA:"XNLH"}
function cvssParse(vector){
const out={valid:false,metrics:{},error:"",version:"3.1"}
let s=String(vector===undefined||vector===null?"":vector).trim().toUpperCase()
if(!s){out.error="Empty vector.";return out}
const m=/^CVSS:(\d\.\d)\//.exec(s)
if(m){
if(m[1]!=="3.1"&&m[1]!=="3.0"){out.error="Only CVSS 3.x vectors are supported.";return out}
out.version=m[1]
s=s.slice(m[0].length)
}
s=s.replace(/^\/+|\/+$/g,"")
const parts=s.split("/")
for(let i=0;i<parts.length;i++){
const kv=parts[i].split(":")
if(kv.length!==2||!kv[0]||!kv[1]){out.error="Malformed metric \""+parts[i]+"\".";out.metrics={};return out}
const k=kv[0],v=kv[1]
if(Object.prototype.hasOwnProperty.call(CVSS_W,k)){
if(Object.prototype.hasOwnProperty.call(out.metrics,k)){out.error="Metric "+k+" is repeated.";out.metrics={};return out}
if(!Object.prototype.hasOwnProperty.call(CVSS_W[k],v)){out.error="Invalid value \""+v+"\" for "+k+".";out.metrics={};return out}
out.metrics[k]=v
}else if(Object.prototype.hasOwnProperty.call(CVSS_EXTRA,k)){
if(v.length!==1||CVSS_EXTRA[k].indexOf(v)<0){out.error="Invalid value \""+v+"\" for "+k+".";out.metrics={};return out}
}else{out.error="Unknown metric \""+k+"\".";out.metrics={};return out}
}
const missing=CVSS_ORDER.filter((k)=>!Object.prototype.hasOwnProperty.call(out.metrics,k))
if(missing.length){out.error="Missing metric"+(missing.length>1?"s":"")+": "+missing.join(", ")+".";return out}
out.valid=true
return out
}
function cvssRoundup(x){
const i=Math.round(x*100000)
if(i%10000===0)return i/100000
return (Math.floor(i/10000)+1)/10
}
function cvssScoreMetrics(mt){
const changed=mt.S==="C"
const iss=1-(1-CVSS_W.C[mt.C])*(1-CVSS_W.I[mt.I])*(1-CVSS_W.A[mt.A])
const impact=changed?7.52*(iss-0.029)-3.25*Math.pow(iss-0.02,15):6.42*iss
let pr=CVSS_W.PR[mt.PR]
if(changed&&mt.PR==="L")pr=0.68
if(changed&&mt.PR==="H")pr=0.5
const expl=8.22*CVSS_W.AV[mt.AV]*CVSS_W.AC[mt.AC]*pr*CVSS_W.UI[mt.UI]
if(impact<=0)return 0
return changed?cvssRoundup(Math.min(1.08*(impact+expl),10)):cvssRoundup(Math.min(impact+expl,10))
}
function cvssScore(vector){
const p=cvssParse(vector)
return p.valid?cvssScoreMetrics(p.metrics):null
}
function cvssBuild(metrics){
metrics=metrics||{}
return "CVSS:3.1/"+CVSS_ORDER.map((k)=>k+":"+String(metrics[k]||"").toUpperCase()).join("/")
}

// ---- Rich HTML subset sanitiser (hand-written tokenizer; the Python one is authoritative on save, this one guards the UI) ----
// Subset v2 adds the Notes editor's structures (callouts, checklists, embeds, command figures, masked secrets, colour spans, widget markers): still no style / id / on* attribute, only whitelisted class tokens and pattern-checked data-* values.
const SAN_ALLOWED={p:1,br:1,h3:1,h4:1,strong:1,b:1,em:1,i:1,u:1,s:1,code:1,pre:1,blockquote:1,ul:1,ol:1,li:1,a:1,table:1,thead:1,tbody:1,tr:1,th:1,td:1,hr:1,img:1,figure:1,figcaption:1,span:1,div:1}
const SAN_VOID={br:1,hr:1,img:1}
// Dropped together with everything inside them.
const SAN_DROP={script:1,style:1,iframe:1,object:1,svg:1,form:1,embed:1,applet:1,math:1,noscript:1,template:1,head:1,title:1,textarea:1,select:1,option:1,button:1,xmp:1,noembed:1,noframes:1,frameset:1,frame:1,audio:1,video:1,canvas:1,map:1,datalist:1,link:1,meta:1,base:1,plaintext:1,listing:1}
// The HTML parser reads these as raw text up to their own end tag, so nothing inside may be tokenised as markup.
const SAN_RAW={script:1,style:1,textarea:1,title:1,xmp:1,iframe:1,noembed:1,noframes:1,noscript:1,plaintext:1,listing:1}
const SAN_DROP_VOID={embed:1,link:1,meta:1,base:1,frame:1}
const SAN_ENT={amp:"&",lt:"<",gt:">",quot:"\"",apos:"'",nbsp:"\u00a0",colon:":",tab:"\t",newline:"\n",sol:"/",lpar:"(",rpar:")",num:"#",period:".",semi:";",quest:"?",equals:"="}
const SAN_UID=/^[A-Za-z0-9][A-Za-z0-9_.\-]{0,79}$/
const SAN_MAX_DEPTH=64
const SAN_LANG=/^[A-Za-z0-9_+#.\-]{1,32}$/
const SAN_ID=/^[A-Za-z0-9_\-]{1,64}$/
const SAN_ASSET=/^[A-Za-z0-9_\-]{6,64}$/
const SAN_SHAPES=/^[A-Za-z0-9_\-]{1,400000}$/
const SAN_LABEL=/^[A-Za-z0-9 ._+#\/()\-]{1,80}$/
const SAN_TAGS=/^[A-Za-z0-9 ._+#\/(),\-]{1,200}$/
const SAN_HEX=/^#[0-9a-fA-F]{6}$/
const SAN_ALIGN={center:1,right:1,justify:1}
const SAN_ALIGN_TAGS={p:1,h3:1,h4:1,li:1,blockquote:1,td:1,th:1}
const SAN_CALLOUTS={finding:1,vuln:1,info:1,warning:1,credential:1,evidence:1}
const SAN_SEVS={critical:1,high:1,medium:1,low:1,info:1}
const SAN_WIDGETS={risk_matrix:1,severity_summary:1,findings_table:1,commands_run:1,scope_targets:1}
const SAN_TABLE_CLS=["note-table","note-table-head","note-align-center","note-align-right"]
const SAN_EMBED_CLS=["note-embed-inline","note-embed-float-left","note-embed-float-right","note-align-center","note-align-right","note-sketch"]
const SAN_SPAN_CLS=["rpt-redact","note-secret","note-ts","rpt-fref","rpt-ph","rpt-tv"]
// A target value key as the Targets page allows it; "@name" / "@status" are the target's own fields (same rule as reports_service._TV_KEY_RX).
const SAN_TV_KEY=/^@?[^\u0000-\u001f\u007f"'<>&{}\\`$,;=|()*]{1,80}$/
function sanDecode(s){
return s.replace(/&(#[xX][0-9a-fA-F]{1,6}|#[0-9]{1,7}|[A-Za-z][A-Za-z0-9]{1,31});?/g,(all,body)=>{
if(body.charAt(0)==="#"){
const hex=body.charAt(1)==="x"||body.charAt(1)==="X"
const code=parseInt(body.slice(hex?2:1),hex?16:10)
if(!isFinite(code)||code<=0||code>0x10ffff||(code>=0xd800&&code<=0xdfff))return ""
return String.fromCodePoint(code)
}
const k=body.toLowerCase()
return Object.prototype.hasOwnProperty.call(SAN_ENT,k)?SAN_ENT[k]:all
})
}
// Text between tags: keep well-formed character references as they are, escape everything else that could open markup.
function sanText(s){
return s.replace(/&(?!(?:#[0-9]{1,7}|#[xX][0-9a-fA-F]{1,6}|[A-Za-z][A-Za-z0-9]{1,31});)/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")
}
function sanUrl(raw){
// Browsers drop tab/CR/LF inside a URL and trim C0 controls and spaces around it before reading the scheme.
const v=sanDecode(String(raw)).replace(/[\t\n\r]/g,"").replace(/^[\u0000- \u007f-\u009f\u00a0\u200b-\u200f\u2028\u2029\ufeff]+|[\u0000- \u007f-\u009f]+$/g,"")
if(/^https?:\/\/[^\s]/i.test(v)||/^mailto:[^\s]/i.test(v)){
if(/[\u0000-\u001f\u007f]/.test(v))return ""
return v
}
return ""
}
function sanSpan(v){
const n=parseInt(sanDecode(String(v)).trim(),10)
return n>=1&&n<=1000?String(n):""
}
// Reads the tag starting at html[i]==="<". Returns null when it is not a tag (the "<" is then literal text).
function sanReadTag(html,i){
const n=html.length
let j=i+1,close=false
if(html.charAt(j)==="/"){close=true;j++}
const c=html.charCodeAt(j)
if(!((c>=65&&c<=90)||(c>=97&&c<=122)))return null
let k=j
while(k<n&&!/[\s\/>]/.test(html.charAt(k)))k++
const name=html.slice(j,k).toLowerCase()
const attrs=[]
let selfClose=false
while(k<n){
const ch=html.charAt(k)
if(ch===">")return {name:name,close:close,attrs:attrs,selfClose:selfClose,end:k+1}
if(/\s/.test(ch)||ch==="/"){selfClose=ch==="/"?true:selfClose;k++;continue}
selfClose=false
let a=k
// A leading "=" is part of the attribute name (HTML tokenizer rule), so `<a =href=x>` cannot smuggle a value.
k++
while(k<n&&!/[\s\/>=]/.test(html.charAt(k)))k++
const an=html.slice(a,k).toLowerCase()
let m=k
while(m<n&&/\s/.test(html.charAt(m)))m++
let val=""
if(html.charAt(m)==="="){
m++
while(m<n&&/\s/.test(html.charAt(m)))m++
const q=html.charAt(m)
if(q==="\""||q==="'"){
const e=html.indexOf(q,m+1)
if(e<0)return {name:name,close:close,attrs:attrs,selfClose:false,end:n,broken:true}
val=html.slice(m+1,e)
k=e+1
}else{
let e=m
while(e<n&&!/[\s>]/.test(html.charAt(e)))e++
val=html.slice(m,e)
k=e
}
}else k=m>k?m:k
if(!attrs.some((x)=>x[0]===an))attrs.push([an,val])
}
return {name:name,close:close,attrs:attrs,selfClose:false,end:n,broken:true}
}
function sanAttr(tag,name){
for(let i=0;i<tag.attrs.length;i++)if(tag.attrs[i][0]===name)return tag.attrs[i][1]
return null
}
// Decoded, trimmed attribute value ("" when absent).
function sanVal(tag,name){
const v=sanAttr(tag,name)
return v===null?"":sanDecode(v).trim()
}
function sanClasses(tag){return sanVal(tag,"class").split(/\s+/)}
function sanInt(v,min,max){
if(!/^\d{1,6}$/.test(v))return ""
const n=parseInt(v,10)
return n>=min&&n<=max?String(n):""
}
function sanCvss(v){
if(!/^\d{1,2}(?:\.\d)?$/.test(v))return ""
const n=parseFloat(v)
return n>=0&&n<=10?n.toFixed(1):""
}
function sanAlign(tag){
const v=sanVal(tag,"data-align").toLowerCase()
return Object.prototype.hasOwnProperty.call(SAN_ALIGN,v)?" data-align=\""+v+"\"":""
}
// opts.imgSrc(src) lets the rich editor map a pasted data: image to a temporary asset id; nothing else relaxes the rules.
function sanitizeHtml(html,opts){
opts=opts||{}
html=String(html===undefined||html===null?"":html).replace(/\u0000/g,"")
const n=html.length
const out=[]
const stack=[]
let i=0
// Stack entries: {n:tag name,e:emitted}. A tag of the subset that is not emitted (a span without an allowed class, a plain div) still owns its end tag, so it cannot close an enclosing element early.
function closeTo(idx){
while(stack.length>idx){const t=stack.pop();if(t.e)out.push("</"+t.n+">")}
if(tvAt>=idx)tvAt=-1
}
// Index of the open target-value reference (it holds text only), else -1.
let tvAt=-1
function lastOpen(name){
for(let k=stack.length-1;k>=0;k--)if(stack[k].n===name)return k
return -1
}
// >0 while inside a widget marker: its content is dropped (the exporter generates it).
let skip=0
while(i<n){
const lt=html.indexOf("<",i)
if(lt<0){if(!skip)out.push(sanText(html.slice(i)));break}
if(lt>i&&!skip)out.push(sanText(html.slice(i,lt)))
i=lt
if(html.startsWith("<!--",i)){
// "<!-->" and "<!--->" are complete (empty) comments for the HTML parser.
if(html.startsWith("<!-->",i)){i+=5;continue}
if(html.startsWith("<!--->",i)){i+=6;continue}
const e=html.indexOf("-->",i+4)
const e2=html.indexOf("--!>",i+4)
if(e<0&&e2<0)break
i=e>=0&&(e2<0||e<e2)?e+3:e2+4
continue
}
const nx=html.charAt(i+1)
if(nx==="!"||nx==="?"){
const e=html.indexOf(">",i+1)
if(e<0)break
i=e+1
continue
}
const tag=sanReadTag(html,i)
if(!tag){if(!skip)out.push("&lt;");i++;continue}
if(tag.broken)break
i=tag.end
const name=tag.name
if(Object.prototype.hasOwnProperty.call(SAN_DROP,name)){
if(tag.close||Object.prototype.hasOwnProperty.call(SAN_DROP_VOID,name))continue
if(Object.prototype.hasOwnProperty.call(SAN_RAW,name)){
const re=new RegExp("</"+name+"(?=[\\s/>]|$)","i")
const rest=html.slice(i)
const m=re.exec(rest)
if(!m){i=n;break}
const t=sanReadTag(html,i+m.index)
i=t?t.end:n
continue
}
// Foreign/nested containers (svg, math, object, form...): skip to the balancing end tag. Where the skip ends is not security-relevant: whatever follows still goes through the whitelist.
let depth=1
while(i<n&&depth>0){
const l2=html.indexOf("<",i)
if(l2<0){i=n;break}
i=l2
if(html.startsWith("<!--",i)){
const e=html.indexOf("-->",i+4)
if(e<0){i=n;break}
i=e+3
continue
}
const t=sanReadTag(html,i)
if(!t){i++;continue}
if(t.broken){i=n;break}
i=t.end
if(t.name===name){
if(t.close)depth--
else if(!t.selfClose)depth++
}
}
continue
}
if(skip){
if(name==="div"){
if(tag.close)skip--
else if(!tag.selfClose)skip++
}
continue
}
if(!Object.prototype.hasOwnProperty.call(SAN_ALLOWED,name))continue
if(tag.close){
if(Object.prototype.hasOwnProperty.call(SAN_VOID,name))continue
const idx=lastOpen(name)
if(idx>=0)closeTo(idx)
continue
}
if(tvAt>=0){
if(!Object.prototype.hasOwnProperty.call(SAN_VOID,name)&&stack.length<SAN_MAX_DEPTH)stack.push({n:name,e:false})
continue
}
let attrs="",emit=true,isTv=false
if(name==="a"){
const href=sanAttr(tag,"href")
const url=href===null?"":sanUrl(href)
if(url)attrs=" href=\""+escapeHtml(url)+"\""
else emit=false
}else if(name==="td"||name==="th"){
const cs=sanAttr(tag,"colspan"),rs=sanAttr(tag,"rowspan")
const c=cs===null?"":sanSpan(cs),r=rs===null?"":sanSpan(rs)
if(c&&c!=="1")attrs+=" colspan=\""+c+"\""
if(r&&r!=="1")attrs+=" rowspan=\""+r+"\""
const w=sanInt(sanVal(tag,"data-width"),20,2000)
if(w)attrs+=" data-width=\""+w+"\""
attrs+=sanAlign(tag)
}else if(name==="img"){
let src=sanAttr(tag,"src")
src=src===null?"":sanDecode(src).trim()
if(typeof opts.imgSrc==="function"&&!/^rptasset:/.test(src)){
const mapped=opts.imgSrc(src)
src=typeof mapped==="string"?mapped:""
}
const m=/^rptasset:(.+)$/.exec(src)
if(!m||!SAN_UID.test(m[1]))continue
attrs=" src=\"rptasset:"+m[1]+"\""
const alt=sanAttr(tag,"alt")
if(alt!==null)attrs+=" alt=\""+escapeHtml(sanDecode(alt).replace(/[\u0000-\u001f]/g," ").slice(0,300))+"\""
const dw=sanVal(tag,"data-width")
if(/^\d{1,4}(?:%|px)?$/.test(dw))attrs+=" data-width=\""+dw+"\""
}else if(name==="figure"){
const cls=sanClasses(tag)
if(cls.indexOf("note-embed")>=0){
attrs=" class=\"note-embed"+SAN_EMBED_CLS.filter((c)=>cls.indexOf(c)>=0).map((c)=>" "+c).join("")+"\""
const kind=sanVal(tag,"data-kind")
if(kind==="image"||kind==="sketch")attrs+=" data-kind=\""+kind+"\""
const asset=sanVal(tag,"data-asset")
if(SAN_ASSET.test(asset))attrs+=" data-asset=\""+asset+"\""
const shapes=sanVal(tag,"data-shapes")
if(SAN_SHAPES.test(shapes))attrs+=" data-shapes=\""+shapes+"\""
}else if(cls.indexOf("rpt-cmd")>=0){
attrs=" class=\"rpt-cmd\""
;[["data-type",SAN_LABEL,40],["data-cat",SAN_LABEL,80],["data-sub",SAN_LABEL,80],["data-tags",SAN_TAGS,200]].forEach((d)=>{
const v=sanVal(tag,d[0])
if(v.length<=d[2]&&d[1].test(v))attrs+=" "+d[0]+"=\""+v+"\""
})
}else{
attrs=" class=\"rpt-ev\""
const uid=sanVal(tag,"data-evidence")
if(uid&&SAN_UID.test(uid))attrs+=" data-evidence=\""+uid+"\""
}
}else if(name==="pre"){
const dl=sanAttr(tag,"data-lang")
const lang=dl===null?"":sanDecode(dl).trim()
if(SAN_LANG.test(lang))attrs=" data-lang=\""+lang+"\""
}else if(name==="span"){
const cls=sanClasses(tag)
const kind=SAN_SPAN_CLS.find((c)=>cls.indexOf(c)>=0)
if(kind){
attrs=" class=\""+kind+"\""
if(kind==="rpt-fref"){const f=sanVal(tag,"data-finding");if(SAN_ID.test(f))attrs+=" data-finding=\""+f+"\""}
else if(kind==="rpt-ph"){const tk=sanVal(tag,"data-token");if(/^[a-z_]{1,40}$/.test(tk))attrs+=" data-token=\""+tk+"\""}
else if(kind==="rpt-tv"){
// A live reference to a linked target's value; without both attributes it is just its text.
const tu=sanVal(tag,"data-target"),tk=sanVal(tag,"data-key")
if(SAN_ID.test(tu)&&SAN_TV_KEY.test(tk)){attrs+=" data-target=\""+tu+"\" data-key=\""+escapeHtml(tk)+"\"";isTv=true}
else emit=false
}
}else{
const col=sanVal(tag,"data-color"),bg=sanVal(tag,"data-bg"),size=sanInt(sanVal(tag,"data-size"),8,72)
if(SAN_HEX.test(col))attrs+=" data-color=\""+col.toLowerCase()+"\""
if(SAN_HEX.test(bg))attrs+=" data-bg=\""+bg.toLowerCase()+"\""
if(size)attrs+=" data-size=\""+size+"\""
if(!attrs)emit=false
}
}else if(name==="div"){
const cls=sanClasses(tag)
if(cls.indexOf("rpt-widget")>=0){
const w=sanVal(tag,"data-widget")
if(Object.prototype.hasOwnProperty.call(SAN_WIDGETS,w))out.push("<div class=\"rpt-widget\" data-widget=\""+w+"\"></div>")
if(!tag.selfClose)skip=1
continue
}
if(cls.indexOf("note-callout")>=0){
let kind=sanVal(tag,"data-callout").toLowerCase()
if(kind==="vulnerability")kind="vuln"
if(!Object.prototype.hasOwnProperty.call(SAN_CALLOUTS,kind))kind="info"
attrs=" class=\"note-callout"+(cls.indexOf("note-finding")>=0?" note-finding":"")+"\" data-callout=\""+kind+"\""
if(kind==="finding"||kind==="vuln"){
const sev=sanVal(tag,"data-sev").toLowerCase(),cv=sanCvss(sanVal(tag,"data-cvss"))
if(Object.prototype.hasOwnProperty.call(SAN_SEVS,sev))attrs+=" data-sev=\""+sev+"\""
if(cv)attrs+=" data-cvss=\""+cv+"\""
}
}else emit=false
}else if(name==="ul"){
if(sanClasses(tag).indexOf("note-checklist")>=0)attrs=" class=\"note-checklist\""
}else if(name==="ol"){
const st=sanInt(sanVal(tag,"start"),1,9999)
if(st&&st!=="1")attrs=" start=\""+st+"\""
}else if(name==="table"){
const cls=sanClasses(tag)
const keep=SAN_TABLE_CLS.filter((c)=>cls.indexOf(c)>=0)
if(keep.length)attrs=" class=\""+keep.join(" ")+"\""
}else if(Object.prototype.hasOwnProperty.call(SAN_ALIGN_TAGS,name)){
if(name==="li"&&/^(?:1|true|checked|yes)$/i.test(sanVal(tag,"data-checked")))attrs+=" data-checked=\"1\""
if((name==="h3"||name==="h4")&&sanVal(tag,"data-collapsed")==="1")attrs+=" data-collapsed=\"1\""
attrs+=sanAlign(tag)
}
if(Object.prototype.hasOwnProperty.call(SAN_VOID,name)){out.push("<"+name+attrs+">");continue}
if(stack.length>=SAN_MAX_DEPTH)continue
// A new paragraph or list item ends the one that is still open, as the HTML parser would.
if(name==="p"||(name==="div"&&emit)){
const idx=lastOpen("p")
if(idx>=0&&stack.slice(idx+1).every((t)=>!/^(td|th|li|blockquote|figure|figcaption|div)$/.test(t.n)))closeTo(idx)
}else if(name==="li"){
const idx=lastOpen("li")
if(idx>=0&&stack.slice(idx+1).every((t)=>t.n!=="ul"&&t.n!=="ol"))closeTo(idx)
}
if(emit)out.push("<"+name+attrs+">")
stack.push({n:name,e:emit})
if(isTv)tvAt=stack.length-1
}
closeTo(0)
return out.join("")
}

// ---- Markdown <-> rich subset. Markdown is parsed by LoyaMarkdown (UI/js/components/markdown.js); this part only adds what the report subset needs on top:
// backslash escapes, report images ![alt](rptasset:UID "width=50%"), <u>..</u>, <redact>..</redact>, evidence figures (```evidence UID) and raw subset blocks (```rpt-html).
function mdLib(lib){
if(lib)return lib
if(typeof LoyaMarkdown!=="undefined")return LoyaMarkdown
if(typeof require==="function"){try{return require("../components/markdown.js")}catch(e){}}
return null
}
// What a typed block prefix turns into: on Space ("#", "-", "1.", ">", "[ ]", "```") or on Enter ("```bash", "---").
function mdShortcut(prefix,key){
const p=String(prefix===undefined||prefix===null?"":prefix).replace(/\u00a0/g," ").replace(/\u200b/g,"")
if(key==="enter"){
const m=/^(?:```|~~~)\s*([A-Za-z0-9_+#.\-]{0,32})$/.exec(p)
if(m)return {type:"code",lang:m[1].toLowerCase()}
if(/^(?:-{3,}|\*{3,}|_{3,})$/.test(p.trim()))return {type:"hr"}
return null
}
if(p==="```"||p==="~~~")return {type:"code",lang:""}
const h=/^#{1,6}$/.exec(p)
if(h)return {type:p.length<=2?"h3":"h4"}
if(p==="-"||p==="*"||p==="+")return {type:"ul"}
if(/^\d{1,3}[.)]$/.test(p))return {type:"ol"}
if(p===">")return {type:"quote"}
if(p==="[]"||p==="[ ]")return {type:"check",checked:false}
if(/^\[x\]$/i.test(p))return {type:"check",checked:true}
return null
}
const MD_TOK_A="\ue080",MD_TOK_B="\ue081"
const MD_QUOTE_RX=/^(?:\s{0,3}>\s?)*/
const MD_IMG_RX=/!\[([^\]\n]*)\]\(\s*rptasset:([A-Za-z0-9][A-Za-z0-9_.\-]{0,79})(?:\s+"(?:width=)?(\d{1,4}%?)")?\s*\)/g
function mdUnesc(s){return s.replace(/[\ue021-\ue07e]/g,(c)=>String.fromCharCode(c.charCodeAt(0)-0xe000))}
function mdImgHtml(alt,uid,width){
return "<img src=\"rptasset:"+uid+"\" alt=\""+escapeHtml(mdUnesc(alt))+"\""+(width?" data-width=\""+width+"\"":"")+">"
}
function mdPrepare(md){
const tokens=[]
const tok=(html)=>{tokens.push(html);return MD_TOK_A+(tokens.length-1)+MD_TOK_B}
const span=(text)=>text
.replace(MD_IMG_RX,(m,alt,uid,w)=>tok(mdImgHtml(alt,uid,w)))
.replace(/<(\/?)(u|redact|secret)>/gi,(m,close,name)=>tok(name.toLowerCase()==="u"?"<"+close+"u>":(close?"</span>":"<span class=\""+(name.toLowerCase()==="secret"?"note-secret":"rpt-redact")+"\">")))
.replace(/<fref ([A-Za-z0-9_\-]{1,64})>/g,(m,uid)=>tok("<span class=\"rpt-fref\" data-finding=\""+uid+"\">"))
.replace(/<span((?: data-(?:color|bg|size)="[#0-9a-fA-F]{1,7}"){1,3})>/g,(m,attrs)=>tok("<span"+attrs+">"))
.replace(/<tv ([A-Za-z0-9_\-]{1,64}) key="(@?[^\u0000-\u001f\u007f"'<>&{}\\`$,;=|()*]{1,80})">/g,(m,uid,key)=>tok("<span class=\"rpt-tv\" data-target=\""+uid+"\" data-key=\""+key+"\">"))
.replace(/<\/(?:fref|span|tv)>/g,()=>tok("</span>"))
.replace(/\{\{([a-z_]{1,40})\}\}/g,(m,t)=>tok("<span class=\"rpt-ph\" data-token=\""+t+"\">{{"+t+"}}</span>"))
const lines=String(md===undefined||md===null?"":md).replace(/\r\n?/g,"\n").replace(/[\u0000\ue000-\ue0ff]/g,"").split("\n")
const out=[]
let i=0
while(i<lines.length){
const line=lines[i]
const f=/^((?:\s{0,3}>\s?)*)\s{0,3}(`{3,}|~{3,})\s*([^`]*)$/.exec(line)
if(!f){
// Code spans stay literal (set aside while the escapes and report extras are read); an escaped backtick does not open one.
const codes=[]
const held=line.replace(/\\[!-\/:-@\[-`{-~]|(`+)([^`\n]|[^`\n][^\n]*?[^`\n])\1(?!`)/g,(m,t)=>{
if(!t)return String.fromCharCode(0xe000+m.charCodeAt(1))
codes.push(m)
return "\ue082"+(codes.length-1)+"\ue083"
})
out.push(span(held).replace(/\ue082(\d+)\ue083/g,(m,k)=>codes[parseInt(k,10)]))
i++
continue
}
const close=new RegExp("^(?:\\s{0,3}>\\s?)*\\s{0,3}"+f[2].charAt(0)+"{"+f[2].length+",}\\s*$")
let j=i+1
while(j<lines.length&&!close.test(lines[j]))j++
const special=/^(evidence|rpt-html)(?:\s+(\S+))?$/i.exec(f[3].trim())
if(!special){
for(let k=i;k<=j&&k<lines.length;k++)out.push(lines[k])
i=j+1
continue
}
const body=lines.slice(i+1,j).map((l)=>f[1]?l.replace(MD_QUOTE_RX,""):l)
let html
if(special[1].toLowerCase()==="rpt-html")html=sanitizeHtml(body.join("\n"))
else{
const uid=special[2]&&SAN_UID.test(special[2])?special[2]:""
const caption=body.length?body[0]:""
let img=""
const rest=[]
body.slice(1).forEach((l)=>{
MD_IMG_RX.lastIndex=0
const im=MD_IMG_RX.exec(l.trim())
if(im&&!img&&im[0]===l.trim())img=mdImgHtml(im[1],im[2],im[3])
else rest.push(l)
})
const text=rest.join("\n")
html="<figure class=\"rpt-ev\""+(uid?" data-evidence=\""+uid+"\"":"")+"><figcaption>"+escapeHtml(caption)+"</figcaption>"+img+(text.trim()||!img?"<pre>"+escapeHtml(text)+"</pre>":"")+"</figure>"
}
const pre=f[1].replace(/\s+$/,"")
out.push(pre)
out.push(f[1]+tok(html))
out.push(pre)
i=j+1
}
return {text:out.join("\n"),tokens:tokens}
}
const MD_ALERTS={finding:"finding",vuln:"vuln",vulnerability:"vuln",info:"info",note:"info",tip:"info",warning:"warning",important:"warning",caution:"warning",credential:"credential",evidence:"evidence"}
// Heading levels of the subset, and "> [!KIND] severity=high cvss=8.1" quotes (GitHub alert syntax) as callouts.
function mdLevels(blocks,tokens){
const out=[]
blocks.forEach((b)=>{
if(b.type==="heading")b.level=b.level<=2?3:4
else if(b.type==="quote"){
const first=b.blocks[0]
const m=first&&first.type==="paragraph"?/^\[!([A-Za-z]{3,13})\]([^\n]*)(?:\n([\s\S]*))?$/.exec(first.text):null
const kind=m?MD_ALERTS[m[1].toLowerCase()]:""
if(kind&&tokens){
let attrs=" class=\"note-callout\" data-callout=\""+kind+"\""
const sev=/\bseverity=([a-z]+)/i.exec(m[2]),cv=/\bcvss=(\d{1,2}(?:\.\d)?)/i.exec(m[2])
if(sev)attrs+=" data-sev=\""+sev[1].toLowerCase()+"\""
if(cv)attrs+=" data-cvss=\""+cv[1]+"\""
const inner=b.blocks.slice(1)
if(m[3]&&m[3].trim())inner.unshift({type:"paragraph",text:m[3]})
tokens.push("<div"+attrs+">")
out.push({type:"paragraph",text:MD_TOK_A+(tokens.length-1)+MD_TOK_B})
mdLevels(inner,tokens).forEach((x)=>out.push(x))
tokens.push("</div>")
out.push({type:"paragraph",text:MD_TOK_A+(tokens.length-1)+MD_TOK_B})
return
}
b.blocks=mdLevels(b.blocks,tokens)
}
out.push(b)
})
return out
}
// Markdown -> sanitised rich subset. "#"/"##" become h3, deeper headings h4; task items become a checklist, "> [!WARNING]" quotes callouts.
function markdownToHtml(md,lib){
const L=mdLib(lib)
const src=String(md===undefined||md===null?"":md)
if(!L)return sanitizeHtml(src.split(/\n{2,}/).map((p)=>"<p>"+escapeHtml(p).replace(/\n/g,"<br>")+"</p>").join(""))
const prep=mdPrepare(src)
let html=L.blocksToHtml(mdLevels(L.toBlocks(prep.text),prep.tokens),{noteClasses:true})
html=html.replace(/<p>\ue080(\d+)\ue081<\/p>/g,(m,i)=>{const t=prep.tokens[parseInt(i,10)]||"";return /^<\/?(?:figure|table|pre|ul|ol|blockquote|h3|h4|hr|p|div)[\s>]/.test(t)?t:m})
html=html.replace(/\ue080(\d+)\ue081/g,(m,i)=>prep.tokens[parseInt(i,10)]||"")
html=html.replace(/[\ue021-\ue07e]/g,(c)=>escapeHtml(String.fromCharCode(c.charCodeAt(0)-0xe000)))
// Quotes in text are written the way the rich view serialises them, so both views give the same HTML.
html=html.replace(/(^|>)([^<]+)/g,(m,a,t)=>a+t.replace(/&quot;/g,"\"").replace(/&#39;/g,"'"))
return sanitizeHtml(html.replace(/[\ue000-\ue0ff]/g,""))
}
// Sanitised subset -> small tree ({tag,attrs,kids}; strings are decoded text).
function mdTree(html){
const root={tag:"",attrs:{},kids:[]}
const stack=[root]
const rx=/<(\/?)([a-z0-9]+)((?:\s+[a-z\-]+="[^"]*")*)>|([^<]+)/g
let m
while((m=rx.exec(html))){
const top=stack[stack.length-1]
if(m[4]!==undefined){top.kids.push(sanDecode(m[4]));continue}
if(m[1]){
const idx=stack.map((n)=>n.tag).lastIndexOf(m[2])
if(idx>0)stack.length=idx
continue
}
const n={tag:m[2],attrs:{},kids:[]}
m[3].replace(/([a-z\-]+)="([^"]*)"/g,(all,k,v)=>{n.attrs[k]=sanDecode(v);return ""})
top.kids.push(n)
if(!Object.prototype.hasOwnProperty.call(SAN_VOID,m[2]))stack.push(n)
}
return root
}
function mdNodeHtml(n){
if(typeof n==="string")return sanText(n)
let a=""
Object.keys(n.attrs).forEach((k)=>{a+=" "+k+"=\""+escapeHtml(n.attrs[k])+"\""})
if(Object.prototype.hasOwnProperty.call(SAN_VOID,n.tag))return "<"+n.tag+a+">"
return "<"+n.tag+a+">"+n.kids.map(mdNodeHtml).join("")+"</"+n.tag+">"
}
function mdRawText(n){
if(typeof n==="string")return n
if(n.tag==="br")return "\n"
return n.kids.map(mdRawText).join("")
}
function mdHas(n,test){
if(typeof n==="string")return false
return n.kids.some((k)=>typeof k!=="string"&&(test(k)||mdHas(k,test)))
}
function mdEscText(t){
return t.replace(/\\/g,"\\\\").replace(/[`*\[\]]/g,"\\$&").replace(/~~/g,"\\~\\~")
.replace(/_/g,(m,off,s)=>/[A-Za-z0-9]/.test(s.charAt(off-1))&&/[A-Za-z0-9]/.test(s.charAt(off+1))?"_":"\\_")
.replace(/<(?=\/?(?:u|redact|secret|fref|span)[\s>]|https?:|mailto:)/gi,"\\<")
}
function mdWrap(inner,mark){
return inner.split("\n").map((line)=>{
const m=/^(\s*)([\s\S]*?)(\s*)$/.exec(line)
return m[2]?m[1]+mark+m[2]+mark+m[3]:line
}).join("\n")
}
function mdCodeSpan(text){
let t=text.replace(/\s*\n\s*/g," ")
if(!t)return ""
let run=0
;(t.match(/`+/g)||[]).forEach((r)=>{run=Math.max(run,r.length)})
const mark="`".repeat(run+1)
if(t.charAt(0)==="`")t=" "+t
if(t.charAt(t.length-1)==="`")t+=" "
return mark+t+mark
}
const MD_BLOCK_TAGS={p:1,h3:1,h4:1,pre:1,blockquote:1,ul:1,ol:1,li:1,table:1,thead:1,tbody:1,tr:1,td:1,th:1,hr:1,figure:1,figcaption:1,div:1}
function mdCls(n,c){return String(n.attrs["class"]||"").split(" ").indexOf(c)>=0}
function mdSpan(k,inner){
if(mdCls(k,"note-secret"))return "<secret>"+inner+"</secret>"
if(mdCls(k,"rpt-redact"))return "<redact>"+inner+"</redact>"
if(mdCls(k,"rpt-fref"))return k.attrs["data-finding"]?"<fref "+k.attrs["data-finding"]+">"+inner+"</fref>":inner
if(mdCls(k,"rpt-ph")&&k.attrs["data-token"])return "{{"+k.attrs["data-token"]+"}}"
if(mdCls(k,"rpt-tv"))return k.attrs["data-target"]&&k.attrs["data-key"]?"<tv "+k.attrs["data-target"]+" key=\""+k.attrs["data-key"]+"\">"+inner+"</tv>":inner
let a=""
;["data-color","data-bg","data-size"].forEach((n)=>{if(k.attrs[n])a+=" "+n+"=\""+k.attrs[n]+"\""})
return a?"<span"+a+">"+inner+"</span>":inner
}
function mdInline(kids,ctx){
let out=""
kids.forEach((k)=>{
if(typeof k==="string"){out+=mdEscText(k.replace(/[ \t\r\n\u00a0]+/g," "));return}
const t=k.tag
if(t==="br")out+="\n"
else if(t==="strong"||t==="b")out+=mdWrap(mdInline(k.kids,{bold:true,italic:ctx.italic,link:ctx.link}),"**")
else if(t==="em"||t==="i"){
const nested=ctx.bold||mdHas(k,(x)=>x.tag==="strong"||x.tag==="b")
out+=mdWrap(mdInline(k.kids,{bold:ctx.bold,italic:true,link:ctx.link}),nested?"_":"*")
}else if(t==="s")out+=mdWrap(mdInline(k.kids,ctx),"~~")
else if(t==="u")out+="<u>"+mdInline(k.kids,ctx)+"</u>"
else if(t==="span")out+=mdSpan(k,mdInline(k.kids,ctx))
else if(t==="code"){
// LoyaMarkdown cannot nest a code span in a link label, and a redaction cannot live inside a code span.
const span=ctx.link?mdEscText(mdRawText(k).replace(/\s+/g," ")):mdCodeSpan(mdRawText(k))
out+=mdHas(k,(x)=>x.tag==="span"&&mdCls(x,"note-secret"))?"<secret>"+span+"</secret>":mdHas(k,(x)=>x.tag==="span"&&mdCls(x,"rpt-redact"))?"<redact>"+span+"</redact>":span
}else if(t==="a"){
const label=mdInline(k.kids,{bold:ctx.bold,italic:ctx.italic,link:true}).replace(/\n/g," ").trim()
const url=String(k.attrs.href||"").replace(/[\s()<>\\]/g,(c)=>encodeURIComponent(c).replace(/\(/g,"%28").replace(/\)/g,"%29"))
out+="["+(label||mdEscText(url))+"]("+url+")"
}else if(t==="img"){
const uid=String(k.attrs.src||"").replace(/^rptasset:/,"")
if(SAN_UID.test(uid))out+="!["+mdEscText(String(k.attrs.alt||"").replace(/\s+/g," "))+"](rptasset:"+uid+(k.attrs["data-width"]?" \"width="+k.attrs["data-width"]+"\"":"")+")"
}else if(t==="hr")out+="\n"
else{
const inner=mdInline(k.kids,ctx)
out+=Object.prototype.hasOwnProperty.call(MD_BLOCK_TAGS,t)?"\n"+inner+"\n":inner
}
})
return out
}
// A text line that would start a block (heading, list, quote, rule, table) gets a backslash so it stays text.
function mdGuardLine(line){
let l=line
if(/^[\s|:\-]+$/.test(l)&&l.indexOf("-")>=0&&l.indexOf("|")>=0)l=l.replace(/\|/g,"\\|")
if(/^(?:#{1,6}\s|>|[-+]\s|[-+]$|(?:-\s*){3,}$|~~~)/.test(l))return "\\"+l
const m=/^(\d{1,9})([.)])(\s|$)/.exec(l)
if(m)return m[1]+"\\"+l.slice(m[1].length)
return l
}
function mdLines(text){
return text.split("\n").map((l)=>l.replace(/^\s+|\s+$/g,"")).filter((l)=>l!=="").map(mdGuardLine)
}
function mdFence(text,info){
let mark="```"
while(text.indexOf(mark)>=0)mark+="`"
return mark+(info||"")+"\n"+text+"\n"+mark
}
function mdList(node,ctx){
const ordered=node.tag==="ol"
const check=!ordered&&mdCls(node,"note-checklist")
const out=[]
let index=ordered&&/^\d{1,4}$/.test(node.attrs.start||"")?parseInt(node.attrs.start,10)-1:0
node.kids.forEach((li)=>{
if(typeof li==="string"){if(!li.trim())return;li={tag:"li",attrs:{},kids:[li]}}
if(li.tag==="ul"||li.tag==="ol"){mdList(li,ctx).forEach((l)=>out.push("  "+l));return}
index++
const mark=ordered?index+". ":"- "
const pad=" ".repeat(mark.length)
const own=li.tag==="li"?li.kids.filter((k)=>typeof k==="string"||(k.tag!=="ul"&&k.tag!=="ol")):[li]
const subs=li.tag==="li"?li.kids.filter((k)=>typeof k!=="string"&&(k.tag==="ul"||k.tag==="ol")):[]
const lines=mdLines(mdInline(own,ctx))
let first=lines.length?lines[0]:""
if(check&&li.tag==="li")first=(li.attrs["data-checked"]==="1"?"[x] ":"[ ] ")+first
else if(!ordered){
if(/^\\?☐(\s|$)/.test(first))first="[ ] "+first.replace(/^\\?☐\s*/,"")
else if(/^\\?☑(\s|$)/.test(first))first="[x] "+first.replace(/^\\?☑\s*/,"")
}
out.push(mark+first)
lines.slice(1).forEach((l)=>out.push(pad+l))
subs.forEach((s)=>mdList(s,ctx).forEach((l)=>out.push(pad+l)))
})
return out
}
function mdTable(node){
const rows=[]
const walk=(n)=>n.kids.forEach((k)=>{
if(typeof k==="string")return
if(k.tag==="tr")rows.push(k.kids.filter((c)=>typeof c!=="string"&&(c.tag==="td"||c.tag==="th")))
else if(k.tag==="thead"||k.tag==="tbody")walk(k)
})
walk(node)
const body=rows.filter((r)=>r.length)
if(!body.length)return ""
const cols=Math.max.apply(null,body.map((r)=>r.length))
const line=(r)=>{
const cells=r.map((c)=>mdLines(mdInline(c.kids,{})).join(" ").replace(/\|/g,"\\|"))
while(cells.length<cols)cells.push("")
return "| "+cells.map((c)=>c||" ").join(" | ")+" |"
}
const out=[line(body[0]),"|"+new Array(cols+1).join(" --- |")]
body.slice(1).forEach((r)=>out.push(line(r)))
return out.join("\n")
}
function mdFigure(node){
let caption="",img="",text=""
const walk=(n)=>n.kids.forEach((k)=>{
if(typeof k==="string")return
if(k.tag==="figcaption")caption=mdRawText(k).replace(/\s+/g," ").trim()
else if(k.tag==="pre")text+=(text?"\n":"")+mdRawText(k).replace(/\n$/,"")
else if(k.tag==="img"){
const uid=String(k.attrs.src||"").replace(/^rptasset:/,"")
if(SAN_UID.test(uid))img="!["+String(k.attrs.alt||"").replace(/[\[\]\\\n]/g," ")+"](rptasset:"+uid+(k.attrs["data-width"]?" \"width="+k.attrs["data-width"]+"\"":"")+")"
}else walk(k)
})
walk(node)
const uid=node.attrs["data-evidence"]||""
const body=[caption]
if(img)body.push(img)
if(text||!img)body.push(text)
return mdFence(body.join("\n"),"evidence"+(uid?" "+uid:""))
}
function mdBlocks(kids){
const out=[]
let run=[]
const flush=()=>{
if(!run.length)return
const lines=mdLines(mdInline(run,{}))
run=[]
if(lines.length)out.push(lines.join("\n"))
}
kids.forEach((k)=>{
if(typeof k==="string"||!Object.prototype.hasOwnProperty.call(MD_BLOCK_TAGS,k.tag)){run.push(k);return}
flush()
const t=k.tag
if(t==="p"||t==="li"||t==="figcaption"||t==="td"||t==="th"){
const lines=mdLines(mdInline(k.kids,{}))
if(lines.length)out.push(lines.join("\n"))
}else if(t==="h3"||t==="h4"){
const text=mdLines(mdInline(k.kids,{})).join(" ")
if(text)out.push((t==="h3"?"## ":"### ")+text.replace(/^\\(?=#)/,""))
}else if(t==="pre"){
if(mdHas(k,(x)=>x.tag!=="br"))out.push(mdFence(mdNodeHtml(k),"rpt-html"))
else out.push(mdFence(mdRawText(k).replace(/\n$/,""),k.attrs["data-lang"]||""))
}else if(t==="blockquote"){
const inner=mdBlocks(k.kids)
if(inner)out.push(inner.split("\n").map((l)=>l?"> "+l:">").join("\n"))
}else if(t==="ul"||t==="ol"){
const lines=mdList(k,{})
if(lines.length)out.push(lines.join("\n"))
}else if(t==="table"){
if(mdCls(k,"note-table-head")||mdHas(k,(x)=>(x.tag==="td"||x.tag==="th")&&(x.attrs.colspan||x.attrs.rowspan||x.attrs["data-width"])))out.push(mdFence(mdNodeHtml(k),"rpt-html"))
else{const tb=mdTable(k);if(tb)out.push(tb)}
}else if(t==="hr")out.push("---")
else if(t==="figure")out.push(mdCls(k,"note-embed")||mdCls(k,"rpt-cmd")?mdFence(mdNodeHtml(k),"rpt-html"):mdFigure(k))
else if(t==="div"&&mdCls(k,"rpt-widget"))out.push(mdFence(mdNodeHtml(k),"rpt-html"))
else if(t==="div"&&mdCls(k,"note-callout")){
// A callout is a quote that starts with the GitHub alert marker; severity and CVSS ride on the marker line.
const kind=k.attrs["data-callout"]||"info"
const head="[!"+kind.toUpperCase()+"]"+(k.attrs["data-sev"]?" severity="+k.attrs["data-sev"]:"")+(k.attrs["data-cvss"]?" cvss="+k.attrs["data-cvss"]:"")
const inner=mdBlocks(k.kids)
out.push((head+(inner?"\n\n"+inner:"")).split("\n").map((l)=>l?"> "+l:">").join("\n"))
}else{const inner=mdBlocks(k.kids);if(inner)out.push(inner)}
})
flush()
return out.join("\n\n")
}
// Rich subset -> Markdown that markdownToHtml() reads back: h3 "##", h4 "###", task items "- [ ]", fenced code with its language.
function htmlToMarkdown(html){
return mdBlocks(mdTree(sanitizeHtml(html)).kids)
}
function riskSummary(findings){
const counts={critical:0,high:0,medium:0,low:0,info:0}
const byStatus={open:0,retest:0,fixed:0,accepted:0}
let max=""
;(findings||[]).forEach((f)=>{
if(!f)return
const sev=Object.prototype.hasOwnProperty.call(counts,f.severity)?f.severity:"info"
counts[sev]++
const st=Object.prototype.hasOwnProperty.call(byStatus,f.status)?f.status:"open"
byStatus[st]++
if(!max||sevRank(sev)<sevRank(max))max=sev
})
const total=counts.critical+counts.high+counts.medium+counts.low+counts.info
return {counts:counts,total:total,open:byStatus.open,by_status:byStatus,max:max}
}
function pad2(n){return (n<10?"0":"")+n}
function fmtUtc(iso){
const d=new Date(iso)
if(!iso||isNaN(d.getTime()))return ""
return d.getUTCFullYear()+"-"+pad2(d.getUTCMonth()+1)+"-"+pad2(d.getUTCDate())+" "+pad2(d.getUTCHours())+":"+pad2(d.getUTCMinutes())+" UTC"
}
// Local time, sortable; a plain YYYY-MM-DD is returned unchanged (no time-zone shift for report dates).
function fmtDate(iso){
if(iso===undefined||iso===null||iso==="")return ""
const s=String(iso)
if(/^\d{4}-\d{2}-\d{2}$/.test(s))return s
const d=new Date(/[zZ]|[+\-]\d{2}:?\d{2}$/.test(s)||!/T|\s/.test(s)?s:s.replace(" ","T")+"Z")
if(isNaN(d.getTime()))return s
return d.getFullYear()+"-"+pad2(d.getMonth()+1)+"-"+pad2(d.getDate())+" "+pad2(d.getHours())+":"+pad2(d.getMinutes())
}
// index is the 0-based position in the report: findingNumber("F-",0) -> "F-01".
function findingNumber(prefix,index){
const n=Math.max(0,parseInt(index,10)||0)+1
return String(prefix===undefined||prefix===null?"":prefix)+(n<10?"0":"")+n
}
const EV_MAX=60000
function stripAnsi(s){
return String(s).replace(/\u001b\[[0-?]*[ -\/]*[@-~]/g,"").replace(/\u001b\][^\u0007\u001b]*(?:\u0007|\u001b\\)/g,"").replace(/\u001b[@-Z\\-_]/g,"").replace(/\r\n?/g,"\n").replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g,"")
}
function evidenceCaption(ev){
ev=ev||{}
const parts=[]
const cmd=String(ev.command||"").trim()
if(cmd)parts.push("$ "+cmd.replace(/\s*\n\s*/g," "))
else if(ev.title)parts.push(String(ev.title))
else parts.push(ev.kind==="image"?"Screenshot":ev.kind==="recording"?"Terminal recording":"Evidence")
if(cmd&&ev.exit_code!==null&&ev.exit_code!==undefined&&ev.exit_code!=="")parts.push("exit "+ev.exit_code)
const when=fmtUtc(ev.started_at||ev.created_at||ev.ended_at)
if(when)parts.push(when)
return parts.join(" \u2014 ")
}
function evidenceFigureHtml(ev){
ev=ev||{}
const uid=SAN_UID.test(String(ev.uid||""))?String(ev.uid):""
const meta=ev.meta||{}
let body
if(ev.kind==="image"&&meta.asset_uid&&SAN_UID.test(String(meta.asset_uid))){
body="<img src=\"rptasset:"+meta.asset_uid+"\" alt=\""+escapeHtml(ev.title||"Screenshot")+"\">"
}else{
let text=stripAnsi(ev.content===undefined||ev.content===null?"":ev.content).replace(/\s+$/,"")
if(text.length>EV_MAX)text=text.slice(0,EV_MAX)+"\n[... output truncated ...]"
body="<pre>"+escapeHtml(text)+"</pre>"
}
return sanitizeHtml("<figure class=\"rpt-ev\""+(uid?" data-evidence=\""+uid+"\"":"")+"><figcaption>"+escapeHtml(evidenceCaption(ev))+"</figcaption>"+body+"</figure>")
}
function htmlToText(html){
return sanDecode(sanitizeHtml(html).replace(/<(?:br|hr)>|<\/(?:p|h3|h4|li|tr|pre|blockquote|figcaption)>/g,"\n").replace(/<[^>]*>/g,"")).replace(/\n{3,}/g,"\n\n").trim()
}
return {
SEVERITIES:SEVERITIES,STATUSES:STATUSES,LIKELIHOODS:LIKELIHOODS,OWASP_TOP10:OWASP_TOP10,COMMON_CWES:COMMON_CWES,CVSS_METRICS:CVSS_METRICS,CVSS_ORDER:CVSS_ORDER,
sevLabel:sevLabel,sevRank:sevRank,statusLabel:statusLabel,sevFromScore:sevFromScore,
cvssParse:cvssParse,cvssScore:cvssScore,cvssBuild:cvssBuild,
sanitizeHtml:sanitizeHtml,escapeHtml:escapeHtml,htmlToText:htmlToText,
mdShortcut:mdShortcut,markdownToHtml:markdownToHtml,htmlToMarkdown:htmlToMarkdown,
riskSummary:riskSummary,evidenceFigureHtml:evidenceFigureHtml,evidenceCaption:evidenceCaption,findingNumber:findingNumber,fmtDate:fmtDate,fmtUtc:fmtUtc
}
})()
if(typeof module!=="undefined"&&module.exports)module.exports=ReportCore
if(typeof window!=="undefined")window.ReportCore=ReportCore
