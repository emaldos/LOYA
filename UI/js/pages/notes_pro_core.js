// Pure logic for the pro note editor (no DOM, no bridge): IOC tools, title/tag heuristics, slash menu, Markdown shortcuts, table navigation, sanitiser policy, code tint, colours.
// Loaded by the app as a plain script (global NotesPro) and by tests/js/notes_pro.js through require().
const NotesPro=(function(){
const SEVERITIES=[
{id:"critical",label:"Critical",color:"#d6336c",min:9},
{id:"high",label:"High",color:"#f03e3e",min:7},
{id:"medium",label:"Medium",color:"#f59f00",min:4},
{id:"low",label:"Low",color:"#37b24d",min:0.1},
{id:"info",label:"Info",color:"#1c7ed6",min:0}
]
const CALLOUTS=[
{id:"finding",label:"Finding"},
{id:"vuln",label:"Vulnerability"},
{id:"info",label:"Info"},
{id:"warning",label:"Warning"},
{id:"credential",label:"Credential"},
{id:"evidence",label:"Evidence"}
]
// Text colours that stay readable on both the dark and the light themes, highlight colours, and shape colours.
const PALETTE_TEXT=["#f03e3e","#f76707","#f59f00","#37b24d","#0ca678","#1098ad","#1c7ed6","#4263eb","#7048e8","#ae3ec9","#d6336c","#868e96","#ff8787","#ffa94d","#ffd43b","#8ce99a","#63e6be","#66d9e8","#74c0fc","#91a7ff","#b197fc","#e599f7","#faa2c1","#ffffff","#c92a2a","#d9480f","#e67700","#2b8a3e","#087f5b","#0b7285","#1864ab","#364fc7","#5f3dc4","#862e9c","#a61e4d","#000000"]
const PALETTE_HIGHLIGHT=["#fff3bf","#ffec99","#ffd8a8","#ffc9c9","#fcc2d7","#eebefa","#d0bfff","#bac8ff","#a5d8ff","#99e9f2","#96f2d7","#b2f2bb","#d8f5a2","#e9ecef","#5c3a00","#5c1a1a","#3b1f5c","#12355c","#0e4a3a","#343a40"]
function normHex(v){
const m=/^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(String(v||"").trim())
if(!m)return ""
let h=m[1].toLowerCase()
if(h.length===3)h=h.split("").map((c)=>c+c).join("")
return "#"+h
}
function recentPush(list,color,max){
const c=normHex(color)
const out=(Array.isArray(list)?list:[]).map(normHex).filter(Boolean)
if(!c)return out.slice(0,max||12)
return [c].concat(out.filter((x)=>x!==c)).slice(0,max||12)
}
function normCvss(v){
const n=parseFloat(String(v===undefined||v===null?"":v).replace(",","."))
if(isNaN(n)||n<0||n>10)return ""
return (Math.round(n*10)/10).toFixed(1)
}
function cvssSeverity(v){
const s=normCvss(v)
if(!s)return ""
const n=parseFloat(s)
for(const sev of SEVERITIES)if(n>=sev.min)return sev.id
return "info"
}
function normSeverity(v){
const k=String(v||"").trim().toLowerCase()
return SEVERITIES.some((s)=>s.id===k)?k:""
}
function normCallout(v){
const k=String(v||"").trim().toLowerCase()
return CALLOUTS.some((s)=>s.id===k)?k:""
}
// ---- IOC tools
const TLDS=new Set("com net org edu gov mil int io co uk de fr es it nl be ch at se no dk fi pl cz ru ua cn jp kr in br mx ar au nz ca us eu info biz me tv cc xyz dev app cloud tech site online store shop blog live news pro name mobi asia tk ml ga cf top club vip work link click icu local localdomain lan internal intranet corp home htb thm lab test example invalid onion offsec vl box ad ir tr il sa ae za ng eg ke gr pt ro hu bg sk hr si lt lv ee ie lu is id my sg th vn ph hk tw pk bd".split(" "))
const RX_URL=/\b(?:https?|ftp|sftp|ldaps?|smb|rdp|ssh|wss?):\/\/[^\s<>"'`]+/gi
const RX_EMAIL=/[a-z0-9][a-z0-9._%+-]{0,63}@(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}/gi
const RX_IP=/(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?:\/(?:3[0-2]|[12]?\d)(?!\d))?/g
const RX_HASH=/\b[a-f0-9]{32}:[a-f0-9]{32}\b|\b(?:[a-f0-9]{128}|[a-f0-9]{64}|[a-f0-9]{40}|[a-f0-9]{32})\b/gi
const RX_CVE=/\bCVE-\d{4}-\d{4,7}\b/gi
const RX_DOMAIN=/\b(?:[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}\b/gi
function iocRefang(text){
return String(text||"")
.replace(/h(xx|XX)p(s?)/g,(m,x,s)=>"http"+s).replace(/H(xx|XX)P(S?)/g,(m,x,s)=>"HTTP"+s)
.replace(/\[:\/\/\]/g,"://").replace(/\[:\]/g,":")
.replace(/\s?[\[({]\s?(?:\.|dot)\s?[\])}]\s?/gi,".")
.replace(/\s?[\[({]\s?(?:@|at)\s?[\])}]\s?/gi,"@")
}
function iocDefangValue(type,value){
const v=String(value||"")
if(type==="url"){
const m=/^([a-z]+)(:\/\/)([^\/?#]*)(.*)$/i.exec(v)
if(!m)return v
return m[1].replace(/^http/i,(h)=>h==="HTTP"?"HXXP":"hxxp")+m[2]+m[3].replace(/\./g,"[.]")+m[4]
}
if(type==="email")return v.replace("@","[@]").replace(/\./g,"[.]")
if(type==="ipv4"||type==="cidr"||type==="domain")return v.replace(/\./g,"[.]")
return v
}
function trimUrl(u){
let v=u
while(/[.,;:!?'")\]}>]$/.test(v)){
const last=v[v.length-1]
if(last===")"&&(v.match(/\(/g)||[]).length>=(v.match(/\)/g)||[]).length)break
v=v.slice(0,-1)
}
return v
}
function hashType(v){
if(v.includes(":"))return "ntlm"
return {32:"md5",40:"sha1",64:"sha256",128:"sha512"}[v.length]||"hash"
}
// Returns the indicators in text (defanged forms are understood), each once, in order of first appearance: {type,value,start,end} with positions in the refanged text.
function iocExtract(text){
let work=iocRefang(text)
const found=[]
const blank=(s,e)=>{work=work.slice(0,s)+" ".repeat(e-s)+work.slice(e)}
const take=(rx,fn)=>{
rx.lastIndex=0
let m
const hits=[]
while((m=rx.exec(work))){
const r=fn(m)
if(r)hits.push(r)
if(m[0].length===0)rx.lastIndex++
}
hits.forEach((h)=>{found.push(h);blank(h.start,h.end)})
}
take(RX_URL,(m)=>{const v=trimUrl(m[0]);return v.length>8?{type:"url",value:v,start:m.index,end:m.index+v.length}:null})
take(RX_EMAIL,(m)=>({type:"email",value:m[0],start:m.index,end:m.index+m[0].length}))
take(RX_CVE,(m)=>({type:"cve",value:m[0].toUpperCase(),start:m.index,end:m.index+m[0].length}))
take(RX_IP,(m)=>{
const before=work[m.index-1]||"",after=work[m.index+m[0].length]||""
if(/[\d.]/.test(before)&&before!==".")return null
if(/\d/.test(before))return null
if(before==="."&&/\d/.test(work[m.index-2]||""))return null
if(/\d/.test(after))return null
if(after==="."&&/\d/.test(work[m.index+m[0].length+1]||""))return null
return {type:m[0].includes("/")?"cidr":"ipv4",value:m[0],start:m.index,end:m.index+m[0].length}
})
take(RX_HASH,(m)=>{
if(!/[a-f]/i.test(m[0])||!/\d/.test(m[0]))return null
return {type:hashType(m[0]),value:m[0].toLowerCase(),start:m.index,end:m.index+m[0].length}
})
take(RX_DOMAIN,(m)=>{
const v=m[0].toLowerCase()
const tld=v.slice(v.lastIndexOf(".")+1)
if(!TLDS.has(tld))return null
if(/^\d+(\.\d+)*$/.test(v))return null
return {type:"domain",value:v,start:m.index,end:m.index+m[0].length}
})
found.sort((a,b)=>a.start-b.start)
const seen=new Set(),out=[]
found.forEach((f)=>{const k=f.type+"|"+f.value.toLowerCase();if(seen.has(k))return;seen.add(k);out.push(f)})
return out
}
// Defang every network indicator in a text (URLs, IPs, CIDRs, domains, e-mail addresses); hashes and CVE ids are left alone.
function iocDefangText(text){
const src=iocRefang(text)
const all=[]
let work=src
const blank=(s,e)=>{work=work.slice(0,s)+" ".repeat(e-s)+work.slice(e)}
const scan=(rx,type,ok)=>{rx.lastIndex=0;let m;const hits=[];while((m=rx.exec(work))){let v=m[0];if(type==="url")v=trimUrl(v);const t=typeof type==="function"?type(v):type;if(!ok||ok(m,v))hits.push({type:t,value:v,start:m.index,end:m.index+v.length})}hits.forEach((h)=>{all.push(h);blank(h.start,h.end)})}
scan(RX_URL,"url")
scan(RX_EMAIL,"email")
scan(RX_IP,(v)=>v.includes("/")?"cidr":"ipv4",(m)=>!/[\d]/.test(work[m.index-1]||"")&&!/\d/.test(work[m.index+m[0].length]||""))
scan(RX_HASH,"hash")
scan(RX_DOMAIN,"domain",(m,v)=>TLDS.has(v.slice(v.lastIndexOf(".")+1).toLowerCase())&&!/^\d+(\.\d+)*$/.test(v))
all.sort((a,b)=>b.start-a.start)
let out=src
all.forEach((h)=>{out=out.slice(0,h.start)+iocDefangValue(h.type,h.value)+out.slice(h.end)})
return out
}
const PORT_SERVICES={21:"ftp",22:"ssh",23:"telnet",25:"smtp",53:"dns",69:"tftp",79:"finger",80:"http",88:"kerberos",110:"pop3",111:"rpc",119:"nntp",123:"ntp",135:"msrpc",137:"netbios",139:"smb",143:"imap",161:"snmp",389:"ldap",443:"https",445:"smb",464:"kerberos",465:"smtp",512:"rexec",513:"rlogin",514:"rsh",587:"smtp",593:"msrpc",636:"ldap",873:"rsync",993:"imap",995:"pop3",1099:"java-rmi",1433:"mssql",1521:"oracle",2049:"nfs",2375:"docker",3000:"http",3268:"ldap",3269:"ldap",3306:"mysql",3389:"rdp",4444:"shell",5000:"http",5432:"postgres",5601:"kibana",5900:"vnc",5985:"winrm",5986:"winrm",6379:"redis",8000:"http",8008:"http",8080:"http",8081:"http",8443:"https",8888:"http",9200:"elasticsearch",11211:"memcached",27017:"mongodb"}
// Open ports from nmap's normal output ("22/tcp open ssh OpenSSH 8.2") and grepable output ("Ports: 22/open/tcp//ssh//").
function nmapPorts(text){
const out=[],seen=new Set()
const add=(port,proto,service)=>{
const p=parseInt(port,10)
if(!(p>0&&p<65536))return
const k=p+"/"+proto
if(seen.has(k))return
seen.add(k)
let s=String(service||"").toLowerCase().replace(/\?$/,"")
if(!s||s==="unknown"||s==="tcpwrapped")s=PORT_SERVICES[p]||""
out.push({port:p,proto,service:s})
}
const rx=/^\s*(\d{1,5})\/(tcp|udp)\s+open(?:\|filtered)?\s+(\S+)?/gim
let m
while((m=rx.exec(text||"")))add(m[1],m[2].toLowerCase(),m[3])
const rg=/(\d{1,5})\/open\/(tcp|udp)\/\/([^\/]*)\//gi
while((m=rg.exec(text||"")))add(m[1],m[2].toLowerCase(),m[3])
return out
}
// ---- auto tags / auto title (local heuristics; nothing is applied without a click)
const TOOL_TAGS=[
[/\b(?:nmap|masscan|rustscan|naabu)\b/i,["nmap","recon"],"nmap"],
[/\b(?:gobuster|ffuf|feroxbuster|dirb|dirsearch|wfuzz|dirbuster)\b/i,["web","enum"],"web-enum"],
[/\b(?:nikto|whatweb|wappalyzer|nuclei)\b/i,["web","recon"],"web-enum"],
[/\bburp(?:suite)?\b/i,["web","burp"],"web"],
[/\bsqlmap\b|\bsql injection\b|\bsqli\b|union select/i,["sqli","web"],"sqli"],
[/\bwpscan\b|wp-content|wp-login/i,["wordpress","web"],"web-enum"],
[/\b(?:hydra|medusa|patator|ncrack)\b|password spray/i,["bruteforce"],"bruteforce"],
[/\b(?:john|hashcat)\b|rockyou/i,["cracking"],"cracking"],
[/\b(?:crackmapexec|netexec|nxc|cme|smbclient|smbmap|enum4linux(?:-ng)?|rpcclient|nbtscan)\b/i,["smb","enum"],"smb"],
[/\b(?:GetNPUsers|asreproast)\b/i,["kerberos","asrep-roast","active-directory"],"kerberos"],
[/\b(?:GetUserSPNs|kerberoast(?:ing)?)\b/i,["kerberos","kerberoast","active-directory"],"kerberos"],
[/\b(?:kerbrute|rubeus|getTGT|krbtgt)\b|\bkerberos\b/i,["kerberos","active-directory"],"kerberos"],
[/\b(?:bloodhound|sharphound|powerview|adidnsdump|ldapdomaindump|certipy|dcsync)\b|domain controller/i,["active-directory"],"ad"],
[/\b(?:secretsdump|mimikatz|lsass|pypykatz|sekurlsa|ntds\.dit)\b/i,["credentials","dumping"],"creds"],
[/\b(?:psexec|wmiexec|smbexec|atexec|dcomexec)\b|pass[- ]the[- ]hash/i,["lateral-movement"],"lateral"],
[/\bevil-winrm\b/i,["winrm","windows"],"winrm"],
[/\b(?:linpeas|linenum|pspy|linux-exploit-suggester)\b|sudo -l\b|\bSUID\b|\bgetcap\b/i,["privesc","linux"],"privesc"],
[/\b(?:winpeas|powerup|seatbelt|juicypotato|printspoofer|godpotato)\b|SeImpersonatePrivilege/i,["privesc","windows"],"privesc"],
[/\b(?:msfconsole|msfvenom|metasploit|meterpreter)\b/i,["metasploit"],"exploit"],
[/\b(?:searchsploit|exploit-db)\b/i,["exploit"],"exploit"],
[/\bresponder\b|\bllmnr\b|ntlmrelayx/i,["llmnr","relay"],"relay"],
[/\b(?:chisel|ligolo(?:-ng)?|proxychains|sshuttle|socat)\b|port forward/i,["pivoting"],"pivoting"],
[/\b(?:ldapsearch|windapsearch)\b|\bldaps?:\/\//i,["ldap"],"ldap"],
[/\b(?:snmpwalk|onesixtyone|snmp-check)\b/i,["snmp"],"snmp"],
[/\b(?:dnsrecon|dnsenum|subfinder|amass|sublist3r|assetfinder)\b|zone transfer|\bdig\s+axfr\b/i,["dns","recon"],"dns"],
[/\bshowmount\b|\bnfs\b/i,["nfs"],"nfs"],
[/\b(?:xfreerdp|rdesktop)\b/i,["rdp"],"rdp"],
[/\bssh\s+(?:-\w+\s+\S+\s+)*\S+@|\bid_rsa\b|authorized_keys/i,["ssh"],"ssh"],
[/\bftp\s+\d|anonymous ftp|\bvsftpd\b/i,["ftp"],"ftp"],
[/\b(?:mysql|mssqlclient|sqsh|psql|redis-cli|mongo(?:sh)?)\b/i,["database"],"db"],
[/reverse shell|bash -i >&|nc(?:at)? -e|\/dev\/tcp\/|rlwrap nc|pwncat/i,["revshell"],"shell"],
[/\bxss\b|cross[- ]site scripting|<script>alert/i,["xss","web"],"xss"],
[/\blfi\b|\brfi\b|local file inclusion|\.\.\/\.\.\/|path traversal/i,["lfi","web"],"lfi"],
[/\bssrf\b|server[- ]side request forgery/i,["ssrf","web"],"ssrf"],
[/\bssti\b|template injection/i,["ssti","web"],"ssti"],
[/\bxxe\b|<!ENTITY/i,["xxe","web"],"xxe"],
[/\bidor\b|insecure direct object/i,["idor","web"],"idor"],
[/\bcsrf\b/i,["csrf","web"],"csrf"],
[/command injection|\brce\b|remote code execution/i,["rce"],"rce"],
[/deseriali[sz]ation|ysoserial/i,["deserialization"],"deser"],
[/\b(?:docker|kubectl|kubernetes)\b/i,["containers"],"containers"],
[/\b(?:aws|s3:\/\/|azure|gcloud)\b/i,["cloud"],"cloud"],
[/\b(?:phishing|gophish|evilginx)\b/i,["phishing"],"phishing"],
[/\b(?:aircrack-ng|airodump-ng|wifite|hcxdumptool)\b|\bwpa2?\b/i,["wifi"],"wifi"],
[/\b(?:user|root|proof)\.txt\b/i,["flag"],"flag"]
]
const ACTIVITY_LABEL={nmap:"Nmap scan","web-enum":"Web enumeration",web:"Web testing",sqli:"SQL injection",bruteforce:"Brute force",cracking:"Hash cracking",smb:"SMB enumeration",kerberos:"Kerberos attacks",ad:"Active Directory enumeration",creds:"Credential dumping",lateral:"Lateral movement",winrm:"WinRM access",privesc:"Privilege escalation",exploit:"Exploitation",relay:"NTLM relay",pivoting:"Pivoting",ldap:"LDAP enumeration",snmp:"SNMP enumeration",dns:"DNS enumeration",nfs:"NFS enumeration",rdp:"RDP access",ssh:"SSH access",ftp:"FTP enumeration",db:"Database access",shell:"Reverse shell",xss:"XSS",lfi:"File inclusion",ssrf:"SSRF",ssti:"Template injection",xxe:"XXE",idor:"IDOR",csrf:"CSRF",rce:"Remote code execution",deser:"Deserialization",containers:"Container testing",cloud:"Cloud testing",phishing:"Phishing",wifi:"Wi-Fi testing",flag:"Flags"}
function countMatches(text,rx){
const g=new RegExp(rx.source,rx.flags.includes("g")?rx.flags:rx.flags+"g")
let n=0
while(g.exec(text)){n++;if(n>50)break}
return n
}
function escapeRx(s){return String(s).replace(/[.*+?^${}()|[\]\\]/g,"\\$&")}
function wordIn(text,word){
const w=String(word||"").trim()
if(w.length<2)return false
return new RegExp("(^|[^a-z0-9_])"+escapeRx(w.toLowerCase())+"($|[^a-z0-9_])").test(text)
}
function analyse(text,opts){
opts=opts||{}
const src=String(text||"")
const lower=src.toLowerCase()
const scores=new Map()
const activities=new Map()
const bump=(tag,n)=>{const k=String(tag).toLowerCase();scores.set(k,(scores.get(k)||0)+n)}
TOOL_TAGS.forEach(([rx,tags,act])=>{
const n=countMatches(src,rx)
if(!n)return
tags.forEach((t,i)=>bump(t,(i===0?2:1)*Math.min(n,5)))
activities.set(act,(activities.get(act)||0)+n)
})
const ports=nmapPorts(src)
ports.forEach((p)=>{if(p.service){let s=p.service.replace(/^https$/,"http").replace(/^microsoft-ds$/,"smb").replace(/^netbios-ssn$/,"smb").replace(/^ms-wbt-server$/,"rdp").replace(/^domain$/,"dns").replace(/^kerberos-sec$/,"kerberos").replace(/^ms-sql-s$/,"mssql").replace(/^postgresql$/,"postgres");if(/^[a-z0-9-]{2,20}$/.test(s))bump(s,2)}})
const iocs=iocExtract(src)
iocs.filter((i)=>i.type==="cve").forEach((i)=>bump(i.value.toLowerCase(),4))
if(/\bwindows\b|powershell|\.exe\b|C:\\/i.test(src))bump("windows",1)
if(/\blinux\b|\/etc\/passwd|\bbash\b|\/home\/|\/var\/www/i.test(src))bump("linux",1)
const existing=new Map()
;(opts.existingTags||[]).forEach((t)=>{const k=String(t||"").trim();if(k)existing.set(k.toLowerCase(),k)})
existing.forEach((orig,k)=>{if(wordIn(lower,k))bump(k,3);else if(scores.has(k))bump(k,1)})
const targets=[]
;(opts.targets||[]).forEach((t)=>{
const name=String((t&&t.name)||t||"").trim()
if(name.length<2)return
const vals=t&&t.values?Object.keys(t.values).map((k)=>String(t.values[k]||"").trim()).filter((v)=>v.length>=3):[]
const hit=wordIn(lower,name)||vals.some((v)=>lower.includes(v.toLowerCase()))
if(hit){targets.push(name);bump(name,5)}
})
return {scores,activities,ports,iocs,targets,existing}
}
function suggestTags(text,opts){
opts=opts||{}
const a=analyse(text,opts)
const have=new Set((opts.currentTags||[]).map((t)=>String(t||"").trim().toLowerCase()))
const rows=Array.from(a.scores.entries()).filter(([k])=>!have.has(k)).sort((x,y)=>y[1]-x[1]||x[0].localeCompare(y[0]))
return rows.slice(0,opts.max||8).map(([k])=>a.existing.get(k)||a.targets.find((t)=>t.toLowerCase()===k)||k)
}
function cleanLine(s){return String(s||"").replace(/\s+/g," ").trim()}
function looksLikeNoise(line){
if(line.length<3)return true
if(/^[\W_]+$/.test(line))return true
if(/^(?:\$|#|>|PS |C:\\|root@|┌──|└─)/.test(line))return true
if(/^(?:nmap|sudo|gobuster|ffuf|curl|wget|nc|ssh|python3?|bash|sh|cd|ls|cat)\s/.test(line))return true
if(/^Starting Nmap|^Nmap scan report|^PORT\s+STATE|^\d{1,5}\/(tcp|udp)\s/.test(line))return true
return false
}
function clip(s,n){
s=cleanLine(s)
if(s.length<=n)return s
const cut=s.slice(0,n)
const sp=cut.lastIndexOf(" ")
return (sp>n*0.6?cut.slice(0,sp):cut).replace(/[\s,;:.-]+$/,"")
}
// Up to three title candidates: the first heading, "<host> - <activity>", and the first meaningful line.
function suggestTitles(text,opts){
opts=opts||{}
const src=String(text||"")
const out=[]
const push=(t)=>{const v=clip(t,70);if(v&&v.length>=3&&!out.some((x)=>x.toLowerCase()===v.toLowerCase()))out.push(v)}
;(opts.headings||[]).slice(0,1).forEach(push)
const a=analyse(src,opts)
let host=a.targets[0]||""
if(!host){
const counts=new Map()
a.iocs.filter((i)=>i.type==="ipv4"||i.type==="domain").forEach((i)=>counts.set(i.value,countMatches(src,new RegExp(escapeRx(i.value),"i"))))
const best=Array.from(counts.entries()).sort((x,y)=>y[1]-x[1])[0]
if(best)host=best[0]
}
const act=Array.from(a.activities.entries()).sort((x,y)=>y[1]-x[1])[0]
const actLabel=act?ACTIVITY_LABEL[act[0]]||"":""
if(host&&actLabel)push(host+" - "+actLabel)
else if(actLabel)push(actLabel)
else if(host)push(host+" - Notes")
const cve=a.iocs.find((i)=>i.type==="cve")
if(cve)push((host?host+" - ":"")+cve.value)
const line=src.split(/\r?\n/).map(cleanLine).find((l)=>l&&!looksLikeNoise(l))
if(line)push(line)
return out.slice(0,3)
}
// ---- slash menu and Markdown shortcuts
const SLASH_ITEMS=[
{id:"h1",label:"Heading 1",hint:"Large section title",keys:"h1 heading title #"},
{id:"h2",label:"Heading 2",hint:"Section title",keys:"h2 heading subtitle ##"},
{id:"h3",label:"Heading 3",hint:"Sub-section title",keys:"h3 heading ###"},
{id:"ul",label:"Bullet list",hint:"- item",keys:"ul bullet list unordered"},
{id:"ol",label:"Numbered list",hint:"1. item",keys:"ol numbered list ordered steps"},
{id:"check",label:"Checklist",hint:"Methodology / to-do items",keys:"check checklist todo task"},
{id:"table",label:"Table",hint:"3 x 3 table",keys:"table grid"},
{id:"code",label:"Code block",hint:"Monospace, keeps whitespace",keys:"code snippet output pre exploit"},
{id:"quote",label:"Quote",hint:"Indented quote",keys:"quote blockquote"},
{id:"finding",label:"Finding template",hint:"Title, severity, hosts, steps, impact, fix",keys:"finding template vuln report"},
{id:"c-finding",label:"Callout: Finding",hint:"With severity and CVSS",keys:"callout finding severity"},
{id:"c-vuln",label:"Callout: Vulnerability",hint:"With severity and CVSS",keys:"callout vulnerability vuln cve"},
{id:"c-info",label:"Callout: Info",hint:"Neutral note",keys:"callout info note"},
{id:"c-warning",label:"Callout: Warning",hint:"Careful / out of scope",keys:"callout warning caution scope"},
{id:"c-credential",label:"Callout: Credential",hint:"Masked secret with reveal / copy",keys:"callout credential password secret creds login"},
{id:"c-evidence",label:"Callout: Evidence",hint:"Proof, output, screenshot",keys:"callout evidence proof"},
{id:"drawing",label:"Drawing",hint:"Sketch a diagram",keys:"drawing sketch draw diagram canvas"},
{id:"image",label:"Image / file",hint:"Attach a screenshot or file",keys:"image file screenshot attachment picture"},
{id:"cmd",label:"Command block",hint:"Reusable command card",keys:"command cmd block"},
{id:"divider",label:"Divider",hint:"Horizontal line",keys:"divider hr line separator"},
{id:"time",label:"Timestamp",hint:"Insert the current date and time",keys:"timestamp time date now"},
{id:"toc",label:"Outline",hint:"Show / hide the heading outline",keys:"outline toc contents"}
]
// The text of the current block up to the caret opens the menu when it is "/" plus an optional short filter.
function slashQuery(textBeforeCaret){
const m=/^\/([a-z0-9 :#-]{0,24})$/i.exec(String(textBeforeCaret||"").replace(/\u00a0/g," ").replace(/\u200b/g,""))
return m?m[1].toLowerCase():null
}
function slashFilter(query,items){
const q=String(query||"").trim().toLowerCase()
const list=items||SLASH_ITEMS
if(!q)return list.slice()
const starts=[],keys=[],has=[]
list.forEach((it)=>{
const label=it.label.toLowerCase()
if(label.startsWith(q)||it.id===q||label.split(/[\s:]+/).some((w)=>w.startsWith(q)))starts.push(it)
else if(it.keys.split(/\s+/).some((w)=>w.startsWith(q)))keys.push(it)
else if((label+" "+it.keys).includes(q))has.push(it)
})
return starts.concat(keys,has)
}
// What a typed prefix turns the block into: on Space ("#", "-", "1.", ">", "[]") or on Enter ("```", "```bash").
function mdShortcut(prefix,key){
const p=String(prefix||"").replace(/\u00a0/g," ").replace(/\u200b/g,"")
if(key==="enter"){
const m=/^```\s*([a-z0-9+#._-]{0,20})$/i.exec(p)
return m?{type:"code",lang:m[1].toLowerCase()}:null
}
if(/^#{1,3}$/.test(p))return {type:"h"+p.length}
if(p==="-"||p==="*"||p==="+")return {type:"ul"}
const ol=/^(\d{1,3})[.)]$/.exec(p)
if(ol)return {type:"ol",start:parseInt(ol[1],10)}
if(p===">")return {type:"quote"}
if(p==="[]"||p==="[ ]")return {type:"check",checked:false}
if(/^\[x\]$/i.test(p))return {type:"check",checked:true}
return null
}
// ---- tables
// Where Tab / Shift+Tab goes from cell (r,c). rowLens is the number of cells in each row.
function tableNext(rowLens,r,c,back){
const rows=rowLens.length
if(!rows)return null
if(back){
if(c>0)return {r,c:c-1,addRow:false}
if(r>0)return {r:r-1,c:Math.max(0,rowLens[r-1]-1),addRow:false}
return {r:0,c:0,addRow:false,stay:true}
}
if(c<rowLens[r]-1)return {r,c:c+1,addRow:false}
if(r<rows-1)return {r:r+1,c:0,addRow:false}
return {r:rows,c:0,addRow:true}
}
function clampColWidth(px){
const n=Math.round(Number(px)||0)
return Math.max(36,Math.min(1200,n))
}
// ---- sanitiser policy. Mode "render" is used for everything shown in the viewer or loaded into the editor; "paste" is stricter (clipboard HTML from anywhere).
const SAN_DROP=new Set(["SCRIPT","STYLE","META","LINK","IFRAME","FRAME","FRAMESET","OBJECT","EMBED","APPLET","FORM","INPUT","SELECT","OPTION","TEXTAREA","TITLE","BASE","HEAD","SVG","MATH","CANVAS","VIDEO","AUDIO","SOURCE","TRACK","NOSCRIPT","TEMPLATE","PORTAL","DIALOG","SLOT","MARQUEE","XML","PARAM","MAP","AREA","DATALIST"])
const SAN_KEEP=new Set(["A","B","I","U","S","STRIKE","EM","STRONG","SUB","SUP","CODE","PRE","KBD","SAMP","VAR","MARK","SMALL","BIG","FONT","SPAN","DIV","P","BR","HR","H1","H2","H3","H4","H5","H6","UL","OL","LI","DL","DT","DD","BLOCKQUOTE","TABLE","THEAD","TBODY","TFOOT","TR","TD","TH","CAPTION","COLGROUP","COL","IMG","FIGURE","FIGCAPTION","INS","DEL","CENTER","WBR","ABBR","CITE","Q","TIME","ADDRESS","TT","NOBR"])
const SAN_GLOBAL_ATTRS=new Set(["class","title","style","dir","lang","align","valign"])
const SAN_TAG_ATTRS={A:["href"],IMG:["src","alt","width","height"],TD:["colspan","rowspan","width","bgcolor"],TH:["colspan","rowspan","width","bgcolor","scope"],TABLE:["border","cellpadding","cellspacing","width"],COL:["span","width"],COLGROUP:["span"],FONT:["color","face","size"],OL:["start","type","reversed"],LI:["value"],BUTTON:["type"],I:[]}
// The only classes and data-* attributes pasted HTML may bring in: the note's own block markup (so copy/paste inside the editor keeps callouts, code blocks and checklists).
const SAN_PASTE_CLASSES=new Set(["note-callout","note-code","note-checklist","note-secret","note-table","note-finding","note-quote","note-ts","note-align-left","note-align-center","note-align-right","note-table-head","note-mitre","note-exit","note-cmdout","note-evidence-meta"])
const SAN_PASTE_DATA=new Set(["data-callout","data-sev","data-cvss","data-lang","data-checked","data-collapsed","data-tid","data-exit","data-vector"])
function sanTagAction(tag,mode){
const t=String(tag||"").toUpperCase()
if(SAN_DROP.has(t))return "drop"
if(t==="BUTTON")return mode==="render"?"keep":"drop"
if(SAN_KEEP.has(t))return "keep"
return "unwrap"
}
function sanStyle(value){
// Declarations are kept one by one; anything that can load a resource, run code, or lift the element out of the note is dropped.
const out=[]
String(value||"").replace(/\/\*[\s\S]*?\*\//g,"").split(";").forEach((decl)=>{
const i=decl.indexOf(":")
if(i<1)return
const prop=decl.slice(0,i).trim().toLowerCase()
const val=decl.slice(i+1).trim()
if(!/^[a-z-]{2,40}$/.test(prop)||!val)return
if(/^(?:position|z-index|behavior|content|pointer-events|-moz-binding|inset|top|left|right|bottom|transform|animation|animation-name|transition|filter|backdrop-filter|-webkit-backdrop-filter|mask|-webkit-mask|clip-path|opacity|visibility|cursor)$/.test(prop))return
if(/url\s*\(|expression\s*\(|javascript:|vbscript:|@import|image-set\s*\(|\\|<|>/i.test(val))return
if(prop==="display"&&!/^(?:block|inline|inline-block|none|table|table-row|table-cell|list-item)$/i.test(val))return
if(/^(?:margin|margin-(?:top|left|right|bottom))$/.test(prop)&&/-\s*\d/.test(val))return
if(val.length>200)return
out.push(prop+":"+val)
})
return out.join(";")
}
// file: images are only this machine's own files. Windows attachments are file:///C:/...; anything else there (file://host/share,
// file:////host, backslash or %5C forms) is a UNC path, and WebView2 would open an SMB connection to that host and hand it the
// user's NTLM hash just because a note (imported, or written by an agent) was shown. Linux attachments are file:////home/...
// (file:/// + an absolute path), which stays local.
function sanIsWindows(){
return typeof navigator!=="undefined"&&/win/i.test(String(navigator.platform||navigator.userAgent||""))
}
function sanLocalFileUrl(v,win){
const s=String(v||"")
if(/[\\]|%5c/i.test(s))return false
if(win===undefined?sanIsWindows():win)return /^file:\/\/\/[A-Za-z]:\/(?!\/)/i.test(s)
return /^file:\/\/\//i.test(s)
}
function sanUrl(value,kind){
const v=String(value||"").replace(/[\u0000-\u0020\u007f-\u009f]+/g,"").trim()
const raw=String(value||"").trim()
if(kind==="href"){
if(/^(?:https?:|mailto:|notelink:)/i.test(v))return raw
if(/^cmd[a-z]*:/i.test(v))return raw
if(v==="#")return "#"
return null
}
if(/^file:/i.test(v))return sanLocalFileUrl(v)?raw:null
if(/^(?:https?:|cmdcard:)/i.test(v))return raw
if(/^data:image\/(?:png|jpe?g|gif|webp|bmp);base64,[a-z0-9+\/=]+$/i.test(v))return v
return null
}
function sanClass(value,mode){
const tokens=String(value||"").split(/\s+/).filter((t)=>/^[a-zA-Z0-9_-]{1,60}$/.test(t))
// Rendered notes keep only the note's own classes (note-*, cmd-card*, icon*): a saved or imported note cannot borrow the app's layout classes to cover the window.
const kept=mode==="paste"?tokens.filter((t)=>SAN_PASTE_CLASSES.has(t)):tokens.filter((t)=>/^(?:note-|cmd-card|icon-|icon$)/.test(t))
return kept.join(" ")
}
// Returns the cleaned value to keep, or null to remove the attribute.
function sanAttr(tag,name,value,mode){
const t=String(tag||"").toUpperCase()
const n=String(name||"").toLowerCase()
const v=String(value===undefined||value===null?"":value)
if(/^on/.test(n))return null
if(n==="style"){const s=sanStyle(v);return s?s:null}
if(n==="class"){const c=sanClass(v,mode);return c?c:null}
if(n==="href")return t==="A"?sanUrl(v,"href"):null
if(n==="src")return t==="IMG"?sanUrl(v,"src"):null
if(n.startsWith("data-")){
if(!/^data-[a-z0-9-]{1,40}$/.test(n))return null
if(mode==="paste"&&!SAN_PASTE_DATA.has(n))return null
return v.length>400000?null:v
}
if(mode==="render"){
if(n==="contenteditable")return v==="false"?"false":null
if(n==="draggable")return v==="true"||v==="false"?v:null
}
if(n==="type"&&t==="BUTTON")return "button"
if(n==="type"&&t==="OL")return /^[1aAiI]$/.test(v)?v:null
if((SAN_TAG_ATTRS[t]||[]).includes(n)||SAN_GLOBAL_ATTRS.has(n)){
if(/javascript:|vbscript:|data:text/i.test(v.replace(/\s+/g,"")))return null
return v.length>2000?null:v
}
return null
}
// ---- code tint (ranges only; the text is never changed)
const CODE_FAMILIES={
hash:["bash","sh","zsh","shell","python","py","powershell","ps1","ruby","rb","perl","yaml","yml","conf","ini","toml","dockerfile","makefile","r"],
slash:["js","javascript","ts","typescript","c","cpp","c++","cs","csharp","java","go","rust","php","kotlin","swift","json"],
dash:["sql","lua","haskell"]
}
const CODE_KEYWORDS=new Set("if then else elif fi for while do done case esac function return in def class import from as try except finally with lambda pass raise yield async await const let var new delete typeof instanceof switch break continue default throw catch public private protected static void int char float double bool boolean string struct enum interface package func go defer select chan map range type echo export local sudo true false null none nil undefined and or not select insert update delete from where join left right inner outer on group by order limit union into values create table drop alter set begin end use exec param foreach".split(" "))
function codeFamily(lang){
const l=String(lang||"").toLowerCase()
if(!l||l==="text"||l==="output"||l==="plain"||l==="none")return ""
if(CODE_FAMILIES.hash.includes(l))return "hash"
if(CODE_FAMILIES.slash.includes(l))return "slash"
if(CODE_FAMILIES.dash.includes(l))return "dash"
return "generic"
}
function codeTokens(text,lang){
const fam=codeFamily(lang)
const out=[]
if(!fam)return out
const s=String(text||"")
const n=s.length
let i=0
const isWord=(ch)=>/[A-Za-z0-9_]/.test(ch)
while(i<n){
const ch=s[i]
const prev=i>0?s[i-1]:"\n"
if(fam==="hash"&&ch==="#"&&(/\s/.test(prev)||i===0)&&s[i+1]!=="!"||(fam==="hash"&&ch==="#"&&s[i+1]==="!"&&i===0)){
let e=s.indexOf("\n",i);if(e<0)e=n
out.push({s:i,e,t:"comment"});i=e;continue
}
if((fam==="slash"||fam==="generic")&&ch==="/"&&s[i+1]==="/"&&prev!==":"){
let e=s.indexOf("\n",i);if(e<0)e=n
out.push({s:i,e,t:"comment"});i=e;continue
}
if(fam==="slash"&&ch==="/"&&s[i+1]==="*"){
let e=s.indexOf("*/",i+2);e=e<0?n:e+2
out.push({s:i,e,t:"comment"});i=e;continue
}
if(fam==="dash"&&ch==="-"&&s[i+1]==="-"){
let e=s.indexOf("\n",i);if(e<0)e=n
out.push({s:i,e,t:"comment"});i=e;continue
}
if(ch==='"'||ch==="'"||ch==="`"){
let e=i+1
while(e<n&&s[e]!==ch&&s[e]!=="\n"){if(s[e]==="\\")e++;e++}
if(e<n&&s[e]===ch){out.push({s:i,e:e+1,t:"string"});i=e+1;continue}
i++;continue
}
if(/\d/.test(ch)&&!isWord(prev)){
let e=i+1
while(e<n&&/[0-9a-fA-FxX._]/.test(s[e]))e++
if(e>=n||!isWord(s[e])){out.push({s:i,e,t:"number"});i=e;continue}
while(e<n&&isWord(s[e]))e++
i=e;continue
}
if(/[A-Za-z_]/.test(ch)&&!isWord(prev)){
let e=i+1
while(e<n&&isWord(s[e]))e++
if(CODE_KEYWORDS.has(s.slice(i,e).toLowerCase())&&prev!=="-"&&prev!=="."&&prev!=="/"&&s[e]!=="="&&s[e]!=="/")out.push({s:i,e,t:"kw"})
i=e;continue
}
i++
}
return out
}
// ---- small text helpers
function wordCount(text){
const t=String(text||"").replace(/\u200b/g,"")
const words=(t.trim().match(/\S+/g)||[]).length
return {words,chars:t.replace(/[\r\n]/g,"").length}
}
function pad2(n){return String(n).padStart(2,"0")}
function timestamp(d){
const t=d instanceof Date?d:new Date()
return t.getFullYear()+"-"+pad2(t.getMonth()+1)+"-"+pad2(t.getDate())+" "+pad2(t.getHours())+":"+pad2(t.getMinutes())
}
function escapeHtml(s){
return String(s===undefined||s===null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")
}
// The finding template as escaped, static HTML.
function findingTemplateHtml(sev){
const s=normSeverity(sev)||"medium"
const row=(k,v)=>`<tr><th>${escapeHtml(k)}</th><td>${v}</td></tr>`
return `<div class="note-callout note-finding" data-callout="finding" data-sev="${s}"><h3>Finding title</h3><table class="note-table note-table-head"><tbody>${row("Severity",escapeHtml(SEVERITIES.find((x)=>x.id===s).label))}${row("CVSS","<br>")}${row("Affected hosts","<br>")}${row("References","<br>")}</tbody></table><h4>Description</h4><p><br></p><h4>Steps to reproduce</h4><ol><li><br></li></ol><h4>Impact</h4><p><br></p><h4>Remediation</h4><p><br></p></div>`
}
// Auto-closing pairs, VS Code style. Returns what a typed character should do:
//   {act:"wrap",open,close}  - wrap the selection; {act:"pair",open,close} - insert both, caret between;
//   {act:"skip"}              - the next char is this closer: just move past it; null - type normally.
// prev/next are the characters around the caret; lineBefore is the text from line start to the caret.
const AUTO_PAIRS={"(":")","[":"]","{":"}",'"':'"',"'":"'","`":"`"}
const AUTO_CLOSERS=new Set([")","]","}",'"',"'","`"])
function autoPairDecision(ch,prev,next,hasSelection,lineBefore){
prev=prev||"";next=next||"";lineBefore=lineBefore||""
const close=AUTO_PAIRS[ch]
if(hasSelection)return close?{act:"wrap",open:ch,close}:null
if(AUTO_CLOSERS.has(ch)&&next===ch)return {act:"skip"}
if(!close)return null
// Quotes: never after or before a letter/digit (don't, it's, 5' 10").
if((ch==="'"||ch==='"'||ch==="`")&&(/\w/.test(prev)||/\w/.test(next)))return null
// Backticks at the start of a line build a ``` fence: leave them alone so ``` + Enter still makes a code block.
if(ch==="`"&&/^\s*`*$/.test(lineBefore))return null
// Only pair when the next character is whitespace, end of line or a closer, like VS Code's autoCloseBefore.
if(next&&!/[\s)\]};,.:]/.test(next))return null
return {act:"pair",open:ch,close}
}
// Backspace between an empty pair removes both halves.
function autoPairBackspace(prev,next){return !!prev&&AUTO_PAIRS[prev]===next}
return {autoPairDecision,autoPairBackspace,SEVERITIES,CALLOUTS,PALETTE_TEXT,PALETTE_HIGHLIGHT,PORT_SERVICES,SLASH_ITEMS,normHex,recentPush,normCvss,cvssSeverity,normSeverity,normCallout,iocRefang,iocDefangValue,iocDefangText,iocExtract,nmapPorts,suggestTags,suggestTitles,slashQuery,slashFilter,mdShortcut,tableNext,clampColWidth,sanTagAction,sanStyle,sanUrl,sanLocalFileUrl,sanClass,sanAttr,codeFamily,codeTokens,wordCount,timestamp,escapeHtml,findingTemplateHtml}
})()
if(typeof module!=="undefined"&&module.exports)module.exports=NotesPro
