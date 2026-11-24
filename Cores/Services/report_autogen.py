"""Auto-generate a draft report from captured evidence: timeline, commands, tools, discovered hosts/services and CANDIDATE findings.
The recognisers are deliberately conservative pattern matches over tool output; every candidate carries a confidence and the reason it
was raised, and is meant to be confirmed by the tester before it is reported."""
import hashlib,html,json,re
from datetime import datetime,timezone
from Cores import target_profiles as _target_profiles
from Cores.Services import evidence_service as _evidence
from Cores import doc_store as _doc_store
SEVERITIES=("critical","high","medium","low","info")
_SEV_RANK={name:index for index,name in enumerate(SEVERITIES)}
_CONF_RANK={"high":0,"medium":1,"low":2}
def _esc(value):return html.escape(str(value if value is not None else ""),quote=True)
def _norm(value):return str(value if value is not None else "").strip()
# ---------------------------------------------------------------- parsers
_NMAP_HOST_RE=re.compile(r"^Nmap scan report for (?:(\S+) \(([^)\s]+)\)|(\S+))\s*$")
# Same shape as terminal.js TERM_NMAP_PORT_RE, so the table matches what the terminal's nmap widget shows.
_NMAP_PORT_RE=re.compile(r"^(\d{1,5})/(tcp|udp|sctp)\s+(open\|filtered|closed\|filtered|open|closed|filtered|unfiltered)\s*(\S*)\s*(.*)$",re.I)
_NMAP_SCRIPT_RE=re.compile(r"^\|[_ ]([A-Za-z0-9][\w.-]*):\s?(.*)$")
def _new_host(name="",ip=""):
    return {"host":ip or name,"hostnames":[name] if name and ip and name!=ip else [],"ports":[],"os":"","scripts":[],"source":"nmap"}
def parse_nmap(text):
    """Hosts from nmap normal output: [{host,hostnames,ports:[{port,proto,state,service,version,scripts}],os,scripts}]."""
    hosts=[];host=None;port=None;script=None;in_host_scripts=False
    def ensure():
        nonlocal host
        if host is None:
            host=_new_host();hosts.append(host)
        return host
    for raw in str(text or "").replace("\r\n","\n").split("\n"):
        line=raw.rstrip()
        match=_NMAP_HOST_RE.match(line.strip())
        if match:
            host=_new_host(match.group(1) or "",match.group(2) or match.group(3) or "")
            hosts.append(host);port=None;script=None;in_host_scripts=False
            continue
        if line.startswith("|"):
            match=_NMAP_SCRIPT_RE.match(line)
            if match:
                script={"id":match.group(1),"output":match.group(2).strip()}
                if port is not None and not in_host_scripts:
                    script["port"]=port["port"];script["proto"]=port["proto"]
                    port["scripts"].append(script)
                else:ensure()["scripts"].append(script)
            elif script is not None:
                script["output"]=(script["output"]+"\n"+line[1:].lstrip("_").rstrip()).strip("\n")
            continue
        script=None
        stripped=line.strip()
        match=_NMAP_PORT_RE.match(stripped)
        if match:
            service=match.group(4) or ""
            port={"port":int(match.group(1)),"proto":match.group(2).lower(),"state":match.group(3).lower(),"service":service,"version":(match.group(5) or "").strip(),"scripts":[]}
            ensure()["ports"].append(port);in_host_scripts=False
            continue
        if stripped.startswith("Host script results:"):
            in_host_scripts=True;ensure()
            continue
        if host is None:continue
        low=stripped.lower()
        if low.startswith("os details:"):host["os"]=stripped.split(":",1)[1].strip()
        elif low.startswith("aggressive os guesses:") and not host["os"]:host["os"]=re.sub(r"\s*\(\d+%\)$","",stripped.split(":",1)[1].split(",")[0].strip())+" (guess)"
        elif low.startswith("running:") and not host["os"]:host["os"]=stripped.split(":",1)[1].strip()
        elif low.startswith("service info:"):
            found=re.search(r"OSs?:\s*([^;]+)",stripped)
            if found:
                host["service_os"]=found.group(1).strip()
                if not host["os"]:host["os"]=host["service_os"]
        elif low.startswith("rdns record for"):
            name=stripped.split(":",1)[1].strip() if ":" in stripped else ""
            if name and name not in host["hostnames"]:host["hostnames"].append(name)
    return [h for h in hosts if h["ports"] or h["scripts"] or h["host"]]
_SS_RE=re.compile(r"^(?:(tcp|udp|tcp6|udp6|mptcp)\s+)?(LISTEN|UNCONN)\s+\d+\s+\d+\s+(\S+):(\d+)\s+\S+(?:\s+(.*))?$",re.I)
_SS_PROC_RE=re.compile(r'users:\(\("([^"]+)",pid=(\d+)')
def parse_ss(text):
    """Listening sockets from `ss -tlnp` style output: [{proto,address,port,process,pid}]."""
    rows=[]
    for raw in str(text or "").split("\n"):
        match=_SS_RE.match(raw.strip())
        if not match:continue
        state=match.group(2).upper()
        proto=(match.group(1) or ("udp" if state=="UNCONN" else "tcp")).lower().replace("6","")
        proc=_SS_PROC_RE.search(match.group(5) or "")
        rows.append({"proto":proto,"address":match.group(3),"port":int(match.group(4)),"process":proc.group(1) if proc else "","pid":proc.group(2) if proc else ""})
    return rows
_NETSTAT_WIN_RE=re.compile(r"^(TCP|UDP)\s+(\S+):(\d+)\s+(\S+)\s*(LISTENING)?\s*(\d+)?$",re.I)
_NETSTAT_NIX_RE=re.compile(r"^(tcp|udp|tcp4|udp4|tcp6|udp6|tcp46|udp46)\s+\d+\s+\d+\s+(\S+)[:.](\d+)\s+(\S+)\s*(LISTEN)?\s*(?:(\d+)/(\S+)|-)?\s*$",re.I)
def parse_netstat(text):
    """Listening sockets from `netstat -an` (Windows) or `netstat -tlnp` / `netstat -an` (Linux, macOS)."""
    rows=[]
    for raw in str(text or "").split("\n"):
        line=raw.strip()
        match=_NETSTAT_WIN_RE.match(line)
        if match:
            proto=match.group(1).lower()
            if proto=="tcp" and not match.group(5):continue
            if proto=="udp" and match.group(4)!="*:*":continue
            rows.append({"proto":proto,"address":match.group(2),"port":int(match.group(3)),"process":"","pid":match.group(6) or ""})
            continue
        match=_NETSTAT_NIX_RE.match(line)
        if match:
            proto=re.sub(r"\d+$","",match.group(1).lower())
            if proto=="tcp" and not match.group(5):continue
            if proto=="udp" and match.group(4) not in ("0.0.0.0:*",":::*","*.*","*:*"):continue
            rows.append({"proto":proto,"address":match.group(2),"port":int(match.group(3)),"process":match.group(7) or "","pid":match.group(6) or ""})
    return rows
def parse_listeners(text):
    return parse_ss(text) or parse_netstat(text)
# ---------------------------------------------------------------- command records
def _ts_key(ts):return ts or "9999"
def records_from_evidence(item):
    """Flatten one evidence item into command records {ts,command,output,exit_code,evidence_uid,session_id,target,duration}."""
    base={"evidence_uid":item.get("uid",""),"session_id":item.get("session_id",""),"target":item.get("target",""),"session_label":(item.get("meta") or {}).get("session_label","")}
    kind=item.get("kind")
    if kind=="recording":
        out=[];current=None
        def start(ts,command):
            nonlocal current
            current=dict(base,ts=ts,command=command,output="",exit_code=None,duration=None)
            out.append(current)
        for event in item.get("events") or []:
            ekind=event.get("kind");data=event.get("data") or ""
            if ekind=="cmd":start(event.get("ts",""),data)
            elif ekind=="out":
                if current is None:start(event.get("ts","") or item.get("started_at",""),"")
                current["output"]+=data
            elif ekind=="exit" and current is not None:
                try:value=json.loads(data)
                except Exception:value={}
                if isinstance(value,dict):
                    current["exit_code"]=value.get("code");current["duration"]=value.get("duration")
        if not out and item.get("content"):out.append(dict(base,ts=item.get("started_at",""),command="",output=item.get("content",""),exit_code=None,duration=None))
        return out
    if kind in ("command","text"):
        return [dict(base,ts=item.get("started_at") or item.get("created_at",""),command=item.get("command",""),output=item.get("content",""),exit_code=item.get("exit_code"),duration=None)]
    return []
_WRAPPERS=("sudo","doas","time","nohup","proxychains","proxychains4","torsocks","stdbuf","env","nice","ionice","timeout","watch","rlwrap","unbuffer")
def tool_name(command):
    """The tool a command line runs: first token with sudo-style wrappers, their flags and VAR=value prefixes stripped; path and .exe removed."""
    tokens=_norm(command).split()
    index=0
    while index<len(tokens):
        token=tokens[index]
        low=token.lower()
        if low in _WRAPPERS:
            index+=1
            while index<len(tokens) and (tokens[index].startswith("-") or (low=="timeout" and re.fullmatch(r"\d+[smhd]?",tokens[index])) or (low in ("sudo","doas") and index>0 and tokens[index-1] in ("-u","-g","-h","-p","-C"))):index+=1
            continue
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*",token):
            index+=1
            continue
        break
    if index>=len(tokens):return ""
    name=tokens[index].strip("\"'()").replace("\\","/").rsplit("/",1)[-1]
    name=re.sub(r"\.(exe|py|sh|pl|rb|ps1|bat|cmd)$","",name,flags=re.I)
    return name.lower()[:40] if re.search(r"[A-Za-z0-9]",name) else ""
TOOL_PURPOSE={"nmap":"Network and service discovery","masscan":"Port scanning","rustscan":"Port scanning","nikto":"Web server scanning","gobuster":"Content and directory discovery","ffuf":"Content and parameter fuzzing","feroxbuster":"Content discovery","dirb":"Content discovery","dirsearch":"Content discovery","wfuzz":"Web fuzzing","sqlmap":"SQL injection testing","hydra":"Online password guessing","medusa":"Online password guessing","crackmapexec":"Windows/Active Directory assessment","nxc":"Windows/Active Directory assessment","netexec":"Windows/Active Directory assessment","smbclient":"SMB share access","smbmap":"SMB share enumeration","enum4linux":"SMB/NetBIOS enumeration","enum4linux-ng":"SMB/NetBIOS enumeration","rpcclient":"MS-RPC enumeration","snmpwalk":"SNMP enumeration","onesixtyone":"SNMP community guessing","curl":"HTTP requests","wget":"HTTP downloads","whatweb":"Web technology fingerprinting","wpscan":"WordPress scanning","sslscan":"TLS configuration testing","testssl":"TLS configuration testing","sslyze":"TLS configuration testing","msfconsole":"Exploitation framework","searchsploit":"Exploit lookup","john":"Offline password cracking","hashcat":"Offline password cracking","responder":"LLMNR/NBT-NS/mDNS poisoning","impacket-getuserspns":"Kerberoasting","getuserspns":"Kerberoasting","impacket-getnpusers":"AS-REP roasting","getnpusers":"AS-REP roasting","impacket-secretsdump":"Credential extraction","secretsdump":"Credential extraction","evil-winrm":"Remote shell over WinRM","ssh":"Remote shell","ftp":"FTP client","nc":"Raw TCP/UDP connections","ncat":"Raw TCP/UDP connections","netcat":"Raw TCP/UDP connections","dig":"DNS queries","nslookup":"DNS queries","host":"DNS queries","whois":"Registration lookups","ping":"Reachability checks","traceroute":"Route discovery","ss":"Local socket listing","netstat":"Local socket listing","id":"Identity check","whoami":"Identity check","showmount":"NFS export listing","ldapsearch":"LDAP enumeration","bloodhound-python":"Active Directory collection","tcpdump":"Packet capture","openssl":"TLS/crypto checks","burpsuite":"Web proxy and scanner","amass":"Attack surface mapping","subfinder":"Subdomain discovery","nuclei":"Template-based vulnerability scanning","linpeas":"Local privilege escalation checks","winpeas":"Local privilege escalation checks"}
def build_timeline(records):
    rows=[{"ts":r["ts"],"command":r["command"],"exit_code":r["exit_code"],"evidence_uid":r["evidence_uid"],"session_id":r["session_id"],"session_label":r.get("session_label",""),"duration":r.get("duration")} for r in records if _norm(r["command"])]
    rows.sort(key=lambda row:_ts_key(row["ts"]))
    # A command saved on its own and also caught by a recording of the same session is one run, not two.
    out=[]
    for row in rows:
        twin=next((prev for prev in reversed(out[-8:]) if prev["command"]==row["command"] and prev["session_id"]==row["session_id"] and prev["evidence_uid"]!=row["evidence_uid"] and _seconds_apart(prev["ts"],row["ts"])<=3),None)
        if twin is None:out.append(row)
        elif twin["exit_code"] is None:twin["exit_code"]=row["exit_code"]
    return out
def _seconds_apart(first,second):
    try:return abs((datetime.fromisoformat(first)-datetime.fromisoformat(second)).total_seconds())
    except Exception:return 10**9
def build_commands(timeline):
    seen={}
    for row in timeline:
        key=_norm(row["command"])
        if key not in seen:seen[key]={"command":key,"count":0,"first_ts":row["ts"]}
        seen[key]["count"]+=1
    return list(seen.values())
def build_tools(timeline):
    seen={}
    for row in timeline:
        name=tool_name(row["command"])
        if not name:continue
        if name not in seen:seen[name]={"name":name,"count":0,"purpose":TOOL_PURPOSE.get(name,"")}
        seen[name]["count"]+=1
    return sorted(seen.values(),key=lambda tool:(-tool["count"],tool["name"]))
_PORT_NAMES={21:"ftp",22:"ssh",23:"telnet",25:"smtp",53:"domain",80:"http",88:"kerberos",110:"pop3",111:"rpcbind",135:"msrpc",139:"netbios-ssn",143:"imap",161:"snmp",389:"ldap",443:"https",445:"microsoft-ds",465:"smtps",587:"submission",631:"ipp",636:"ldaps",993:"imaps",995:"pop3s",1433:"ms-sql-s",1521:"oracle-tns",2049:"nfs",3306:"mysql",3389:"ms-wbt-server",5432:"postgresql",5900:"vnc",5985:"winrm",6379:"redis",8080:"http-proxy",8443:"https-alt",27017:"mongodb"}
def build_hosts(records):
    """Merge nmap results per host. Listener tables (ss/netstat) describe whichever machine the shell was on, which the output
    does not say, so they become one entry per terminal session rather than being pinned on a target."""
    hosts={};order=[]
    def entry(key,source):
        if key not in hosts:
            hosts[key]={"host":key,"hostnames":[],"ports":[],"os":"","source":source,"evidence_uids":[]}
            order.append(key)
        return hosts[key]
    def add_port(host,port):
        for existing in host["ports"]:
            if existing["port"]==port["port"] and existing["proto"]==port["proto"] and existing.get("address","")==port.get("address",""):
                for key in ("service","version"):
                    if len(port.get(key,""))>len(existing.get(key,"")):existing[key]=port[key]
                if port.get("state")=="open":existing["state"]="open"
                return
        host["ports"].append(port)
    for record in records:
        output=record["output"]
        if not output:continue
        if "Nmap scan report for" in output or re.search(r"^\d{1,5}/(?:tcp|udp)\s+open",output,re.M):
            for parsed in parse_nmap(output):
                if not parsed["ports"] and not parsed["scripts"]:continue
                host=entry(parsed["host"] or "unknown host","nmap")
                for name in parsed["hostnames"]:
                    if name not in host["hostnames"]:host["hostnames"].append(name)
                if parsed["os"] and (not host["os"] or host["os"].endswith("(guess)")):host["os"]=parsed["os"]
                for port in parsed["ports"]:add_port(host,{"port":port["port"],"proto":port["proto"],"state":port["state"],"service":port["service"],"version":port["version"]})
                if record["evidence_uid"] not in host["evidence_uids"]:host["evidence_uids"].append(record["evidence_uid"])
        tool=tool_name(record["command"])
        if tool in ("ss","netstat") or (not record["command"] and re.search(r"^(?:Netid\s+State|Proto\s+Recv-Q|\s*Proto\s+Local Address)",output,re.M)):
            listeners=parse_listeners(output)
            if listeners:
                host=entry("Listening sockets ("+(record.get("session_label") or "captured shell")+")","listeners")
                for row in listeners:add_port(host,{"port":row["port"],"proto":row["proto"],"state":"listening","service":row["process"] or _PORT_NAMES.get(row["port"],""),"version":"","address":row["address"]})
                if record["evidence_uid"] not in host["evidence_uids"]:host["evidence_uids"].append(record["evidence_uid"])
    out=[]
    for key in order:
        host=hosts[key]
        host["ports"].sort(key=lambda port:(port["proto"],port["port"],port.get("address","")))
        out.append(host)
    return out
# ---------------------------------------------------------------- candidate rule texts
_V_NET_FULL="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"
def _rule(title,severity,description,impact,remediation,cvss="",cwe="",owasp="",refs=(),lib=()):
    return {"title":title,"severity":severity,"cvss_vector":cvss,"description":description,"impact":impact,"remediation":remediation,"cwe":cwe,"owasp":owasp,"references":list(refs),"lib":list(lib)}
RULES={
"telnet":_rule("Telnet service exposed (cleartext administration)","medium","A Telnet service is reachable. Telnet transmits credentials and session data without encryption.","An attacker positioned on the network path can capture credentials and commands, or hijack an administrative session.","Disable Telnet and use SSH. Where Telnet cannot be removed, restrict it to a management network.",cvss="CVSS:3.1/AV:A/AC:H/PR:N/UI:N/S:U/C:H/I:H/A:N",cwe="CWE-319",lib=("telnet","cleartext")),
"ftp":_rule("FTP service exposed (cleartext file transfer)","low","An FTP service is reachable. FTP transmits credentials and file contents without encryption.","Credentials and transferred files can be captured by an attacker positioned on the network path.","Replace FTP with SFTP or FTPS, or restrict access to trusted networks.",cwe="CWE-319",lib=("ftp","cleartext")),
"ftp-anon":_rule("Anonymous FTP access permitted","medium","The FTP service accepts anonymous logins.","Anyone who can reach the service can list and download the files it exposes; if the area is writable it can also be used to stage malicious content.","Disable anonymous access unless there is a documented business need, and make sure no sensitive or writable directories are reachable anonymously.",cvss="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:L/I:N/A:N",cwe="CWE-284",lib=("anonymous ftp",)),
"rservices":_rule("Berkeley r-services exposed (rsh/rlogin/rexec)","medium","Legacy r-services are reachable. They rely on host-based trust and send data in cleartext.","Trust relationships can be abused or spoofed to obtain a shell without a password, and traffic can be captured.","Disable rsh, rlogin and rexec and use SSH.",cwe="CWE-319",lib=("r-services","rsh")),
"vnc":_rule("VNC remote desktop service exposed","medium","A VNC service is reachable. VNC authentication is weak (8-character passwords, no lockout) and many deployments are unencrypted.","Password guessing or traffic capture can give an attacker interactive desktop access to the host.","Restrict VNC to a management network or tunnel it over SSH/VPN, and require strong authentication.",cwe="CWE-284",lib=("vnc",)),
"vnc-noauth":_rule("VNC service does not require authentication","high","The VNC service offers the security type None, so a desktop session can be opened without a password.","Anyone who can reach the service gets interactive access to the host with the privileges of the logged-in user.","Require authentication on the VNC server and restrict network access to it.",cvss=_V_NET_FULL,cwe="CWE-306",lib=("vnc",)),
"rdp":_rule("Remote Desktop (RDP) service exposed","low","A Remote Desktop service is reachable from the tested network position.","RDP is a frequent target for password guessing and for pre-authentication vulnerabilities on unpatched hosts.","Restrict RDP to a management network or VPN, enforce Network Level Authentication and multi-factor authentication.",cwe="CWE-284",lib=("rdp","remote desktop")),
"smb":_rule("SMB file sharing service exposed","low","SMB/NetBIOS services are reachable from the tested network position.","SMB exposes a large attack surface (share enumeration, relay, legacy protocol flaws) and should not be reachable from untrusted networks.","Block SMB (TCP 139/445) at network boundaries and restrict it to hosts that need it.",cwe="CWE-284",lib=("smb exposed",)),
"smb-signing":_rule("SMB signing not required","medium","The SMB server does not require message signing.","An attacker who can intercept or coerce authentication can relay it to this host (NTLM relay) and act as the victim account.","Require SMB signing on all servers and clients through Group Policy (Microsoft network server/client: Digitally sign communications (always)).",cvss="CVSS:3.1/AV:A/AC:H/PR:N/UI:N/S:U/C:H/I:H/A:N",cwe="CWE-347",lib=("smb signing",)),
"smbv1":_rule("SMBv1 protocol enabled","medium","The server still accepts the obsolete SMBv1 dialect.","SMBv1 lacks modern protections and is the vector for several wormable vulnerabilities (for example MS17-010).","Disable SMBv1 on servers and clients.",cwe="CWE-327",refs=("https://learn.microsoft.com/windows-server/storage/file-server/troubleshoot/detect-enable-and-disable-smbv1-v2-v3",),lib=("smbv1",)),
"smb-null":_rule("SMB null session permitted","medium","The SMB service accepts a session without credentials.","Unauthenticated users can enumerate shares, users, groups and password policy, which supports password guessing and further attacks.","Disable anonymous/null sessions (RestrictAnonymous, RestrictNullSessAccess) and remove anonymous share access.",cvss="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:L/I:N/A:N",cwe="CWE-284",lib=("null session",)),
"snmp":_rule("SNMP service exposed","low","An SNMP agent is reachable. SNMP v1/v2c send community strings in cleartext.","With a known or guessed community string an attacker can read detailed device information and, with write access, change configuration.","Restrict SNMP to management hosts and use SNMPv3 with authentication and privacy.",cwe="CWE-319",lib=("snmp",)),
"snmp-public":_rule("SNMP agent answers to a default community string","medium","The SNMP agent returned data for a default community string (such as public).","Device details, interfaces, routing, running software and sometimes credentials can be read without authentication.","Change default community strings, restrict SNMP to management hosts and migrate to SNMPv3.",cvss="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:L/I:N/A:N",cwe="CWE-1392",lib=("snmp","default community")),
"database":_rule("Database service exposed to the network","medium","A database listener is reachable from the tested network position.","Direct database access enables password guessing and exploitation of database flaws, and bypasses application-level controls.","Bind the database to localhost or an internal interface and restrict access with firewall rules to the application servers that need it.",cwe="CWE-284",lib=("database exposed","exposed database")),
"db-noauth":_rule("Database service accessible without authentication","critical","The database service accepted access without valid credentials.","Unauthenticated users can read or modify the data it stores and may be able to execute code on the host.","Require authentication, remove empty or default passwords and restrict network access to the service.",cvss=_V_NET_FULL,cwe="CWE-306",lib=("default cred","unauthenticated")),
"http-plain":_rule("Web service without transport encryption","low","A web service is offered over unencrypted HTTP.","Session tokens, credentials and content can be read or modified in transit if the service handles anything sensitive.","Serve the application over HTTPS only, redirect HTTP to HTTPS and enable HSTS.",cwe="CWE-319",owasp="A02:2021 Cryptographic Failures",lib=("unencrypted http","cleartext http","missing https")),
"ajp":_rule("Apache JServ Protocol (AJP) connector exposed","low","An AJP connector is reachable. AJP is intended for trusted reverse proxies only.","On Tomcat versions before 9.0.31/8.5.51/7.0.100 an exposed connector allows file read and inclusion (Ghostcat).","Disable the AJP connector if unused, or bind it to localhost and require a secret.",cwe="CWE-284",refs=("CVE-2020-1938",),lib=("ajp","ghostcat")),
"nfs-export":_rule("NFS export accessible to any host","medium","An NFS export is offered to all hosts.","Anyone on the network can mount the export and read (or, if writable, change) its files; weak squash settings may allow privilege escalation.","Restrict exports to specific hosts, use root_squash and remove exports that are not needed.",cwe="CWE-284",lib=("nfs",)),
"outdated-openssh":_rule("Outdated OpenSSH version","low","The SSH banner reports an OpenSSH release that no longer receives upstream security fixes.","Older releases are affected by publicly known issues such as user enumeration (CVE-2018-15473, before 7.7).","Upgrade OpenSSH to a supported release, or confirm that the distribution package carries the relevant backported fixes.",cwe="CWE-1104",owasp="A06:2021 Vulnerable and Outdated Components",refs=("CVE-2018-15473",),lib=("outdated software","outdated")),
"apache-traversal":_rule("Apache HTTP Server path traversal and remote code execution","critical","The banner reports Apache HTTP Server 2.4.49/2.4.50, which are affected by a path traversal flaw that leads to file disclosure and, with mod_cgi enabled, remote code execution.","An unauthenticated attacker can read files outside the document root and may execute commands on the server.","Upgrade Apache HTTP Server to 2.4.51 or later.",cvss=_V_NET_FULL,cwe="CWE-22",owasp="A06:2021 Vulnerable and Outdated Components",refs=("CVE-2021-41773","CVE-2021-42013"),lib=("path traversal","outdated software")),
"apache-eol":_rule("Unsupported Apache HTTP Server version","high","The banner reports an Apache HTTP Server branch that is end-of-life and no longer receives security fixes.","Publicly known vulnerabilities in the unsupported branch remain unpatched.","Upgrade to a supported Apache HTTP Server 2.4 release.",cwe="CWE-1104",owasp="A06:2021 Vulnerable and Outdated Components",lib=("outdated software","unsupported")),
"apache-old":_rule("Outdated Apache HTTP Server version","low","The banner reports an Apache HTTP Server 2.4 release that is several versions behind the current one.","Releases in between fixed security issues (request smuggling, mod_proxy SSRF and others) that may apply depending on the modules in use.","Upgrade to the current Apache HTTP Server 2.4 release, or confirm that the distribution package carries the backported fixes.",cwe="CWE-1104",owasp="A06:2021 Vulnerable and Outdated Components",lib=("outdated software","outdated")),
"vsftpd-backdoor":_rule("vsftpd 2.3.4 backdoored release","critical","The banner reports vsftpd 2.3.4. A compromised source archive of this release contains a backdoor that opens a root shell on TCP 6200.","If the backdoored build is installed, an unauthenticated attacker obtains a root shell.","Replace vsftpd with a current release from a trusted source and review the host for compromise.",cvss=_V_NET_FULL,cwe="CWE-506",refs=("CVE-2011-2523",),lib=("backdoor","outdated software")),
"proftpd-backdoor":_rule("ProFTPD 1.3.3c backdoored release","critical","The banner reports ProFTPD 1.3.3c. The source archive distributed for this release in late 2010 contained a backdoor giving unauthenticated root access.","If the backdoored build is installed, an unauthenticated attacker obtains a root shell.","Replace ProFTPD with a current release from a trusted source and review the host for compromise.",cvss=_V_NET_FULL,cwe="CWE-506",lib=("backdoor","outdated software")),
"proftpd-modcopy":_rule("ProFTPD 1.3.5 mod_copy unauthenticated file copy","high","The banner reports ProFTPD 1.3.5, whose mod_copy module lets unauthenticated clients copy files on the server (SITE CPFR/CPTO).","Arbitrary files can be read or written, typically leading to remote code execution through a web root.","Upgrade ProFTPD or disable mod_copy.",cwe="CWE-284",refs=("CVE-2015-3306",),lib=("outdated software",)),
"unrealircd-backdoor":_rule("UnrealIRCd 3.2.8.1 backdoored release","critical","The banner reports UnrealIRCd 3.2.8.1, a release whose download was replaced with a backdoored archive.","If the backdoored build is installed, an unauthenticated attacker can execute commands on the host.","Replace UnrealIRCd with a verified current release and review the host for compromise.",cvss=_V_NET_FULL,cwe="CWE-506",refs=("CVE-2010-2075",),lib=("backdoor","outdated software")),
"samba-usermap":_rule("Samba username map script command execution","critical","The banner reports a Samba 3.0.20 - 3.0.25rc3 release, affected by command injection through the username map script option.","An unauthenticated attacker can execute commands as root when the option is enabled.","Upgrade Samba to a supported release.",cvss=_V_NET_FULL,cwe="CWE-78",refs=("CVE-2007-2447",),lib=("outdated software",)),
"samba-old":_rule("Outdated Samba version","medium","The reported Samba release is in a range affected by a remote code execution flaw when a writable share is available (CVE-2017-7494).","An attacker with write access to a share can load a library and execute code as root.","Upgrade Samba to a supported release, or confirm that the distribution package carries the backported fix.",cwe="CWE-1104",refs=("CVE-2017-7494",),lib=("outdated software","outdated")),
"iis-eol":_rule("Unsupported Microsoft IIS version","high","The banner reports a Microsoft IIS version that ships with an end-of-life Windows release.","Publicly known vulnerabilities remain unpatched (IIS 6.0, for example, is affected by the WebDAV overflow CVE-2017-7269).","Migrate the site to a supported Windows Server and IIS release.",cwe="CWE-1104",owasp="A06:2021 Vulnerable and Outdated Components",lib=("outdated software","unsupported")),
"nginx-old":_rule("Outdated nginx version","low","The banner reports an nginx release from a branch that is no longer maintained.","Security fixes released since then are missing unless they were backported by the distribution.","Upgrade nginx to the current stable release, or confirm the backported fixes.",cwe="CWE-1104",owasp="A06:2021 Vulnerable and Outdated Components",lib=("outdated software","outdated")),
"php-eol":_rule("Unsupported PHP version","medium","The server reports a PHP branch that is end-of-life and no longer receives security fixes.","Publicly known vulnerabilities in the interpreter remain unpatched and may be reachable through the application.","Upgrade to a supported PHP release and stop disclosing the version (expose_php = Off).",cwe="CWE-1104",owasp="A06:2021 Vulnerable and Outdated Components",lib=("outdated software","unsupported")),
"mysql-old":_rule("Unsupported MySQL version","low","The banner reports a MySQL branch that is end-of-life.","Publicly known vulnerabilities remain unpatched.","Upgrade to a supported MySQL or MariaDB release.",cwe="CWE-1104",lib=("outdated software","unsupported")),
"exim-old":_rule("Outdated Exim mail server","high","The banner reports an Exim release older than 4.92, the range affected by the remote command execution flaw known as The Return of the WIZard.","A remote attacker may be able to execute commands as root.","Upgrade Exim to a supported release, or confirm the backported fix.",cwe="CWE-1104",refs=("CVE-2019-10149",),lib=("outdated software",)),
"distcc":_rule("distccd remote command execution","high","A distcc daemon is reachable. When it is not restricted to trusted clients it runs arbitrary commands submitted as compilation jobs.","An unauthenticated attacker can execute commands on the host with the privileges of the daemon.","Restrict distccd to trusted hosts (--allow) or disable it.",cwe="CWE-284",refs=("CVE-2004-2687",),lib=("distcc",)),
"tomcat-eol":_rule("Unsupported Apache Tomcat version","medium","The banner reports an Apache Tomcat branch that is end-of-life.","Publicly known vulnerabilities remain unpatched.","Upgrade to a supported Apache Tomcat release.",cwe="CWE-1104",owasp="A06:2021 Vulnerable and Outdated Components",lib=("outdated software","unsupported")),
"openssl-heartbleed":_rule("OpenSSL version in the Heartbleed range","high","The server reports OpenSSL 1.0.1 - 1.0.1f, the range affected by the Heartbleed memory disclosure.","Process memory, including private keys and session data, may be readable by unauthenticated clients.","Upgrade OpenSSL, then reissue certificates and rotate secrets that may have been exposed.",cvss="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N",cwe="CWE-125",refs=("CVE-2014-0160",),lib=("heartbleed","outdated software")),
"openssl-old":_rule("Unsupported OpenSSL version","low","The server reports an OpenSSL branch that is end-of-life.","Publicly known vulnerabilities in the library remain unpatched.","Upgrade to a supported OpenSSL release.",cwe="CWE-1104",lib=("outdated software","unsupported")),
"os-eol":_rule("Unsupported operating system","high","The host identifies itself as an operating system release that no longer receives security updates.","Every vulnerability disclosed since the end of support remains unpatched, which makes the host an easy entry and pivot point.","Upgrade or replace the host. Until then, isolate it and limit the services it exposes.",cwe="CWE-1104",owasp="A06:2021 Vulnerable and Outdated Components",lib=("unsupported operating system","outdated software","unsupported")),
"nmap-vuln":_rule("Vulnerability reported by an Nmap script","high","An Nmap NSE vulnerability check reported the service as vulnerable.","See the referenced advisory for the impact of the vulnerability.","Apply the vendor patch or mitigation for the referenced vulnerability.",lib=()),
"ms17-010":_rule("MS17-010 (EternalBlue) SMBv1 remote code execution","critical","The SMB server is missing the MS17-010 security update. The SMBv1 implementation mishandles crafted packets, allowing remote code execution.","An unauthenticated attacker on the network can execute code with SYSTEM privileges; the flaw is wormable.","Install the MS17-010 security update and disable SMBv1.",cwe="CWE-119",refs=("CVE-2017-0143","CVE-2017-0144","https://learn.microsoft.com/security-updates/securitybulletins/2017/ms17-010"),lib=("ms17-010","eternalblue")),
"ms08-067":_rule("MS08-067 Server service remote code execution","critical","The host is missing the MS08-067 security update. The Server service mishandles crafted RPC requests.","An unauthenticated attacker on the network can execute code with SYSTEM privileges.","Install the MS08-067 security update; the affected Windows versions are end-of-life and should be replaced.",cwe="CWE-119",refs=("CVE-2008-4250",),lib=("ms08-067",)),
"weak-tls":_rule("Weak TLS configuration","medium","The service accepts deprecated protocol versions or weak cipher suites.","An attacker able to intercept traffic may downgrade or decrypt connections (for example POODLE, SWEET32, RC4 biases).","Disable SSLv2, SSLv3, TLS 1.0 and TLS 1.1, and allow only strong AEAD cipher suites with forward secrecy.",cvss="CVSS:3.1/AV:N/AC:H/PR:N/UI:N/S:U/C:H/I:N/A:N",cwe="CWE-326",owasp="A02:2021 Cryptographic Failures",lib=("weak tls","tls","ssl")),
"cert-expired":_rule("Expired TLS certificate","low","The TLS certificate presented by the service has expired.","Clients show warnings or refuse to connect, and users trained to click through warnings are easier to intercept.","Renew the certificate and monitor expiry dates.",cwe="CWE-298",lib=("certificate",)),
"http-methods":_rule("Risky HTTP methods enabled","low","The web server advertises HTTP methods that are rarely needed (such as PUT, DELETE or TRACE).","Depending on configuration these methods may allow content to be modified or reflected (cross-site tracing).","Disable HTTP methods that the application does not need.",cwe="CWE-650",owasp="A05:2021 Security Misconfiguration",lib=("http methods",)),
"git-exposed":_rule("Version control metadata exposed on the web server","high","A .git directory is reachable through the web server.","The repository can be downloaded and reconstructed, disclosing source code, history and often credentials.","Remove version control directories from the web root or block access to them, and rotate any secrets in the repository.",cvss="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N",cwe="CWE-527",owasp="A05:2021 Security Misconfiguration",lib=("git","source code disclosure")),
"env-exposed":_rule("Environment/configuration file exposed on the web server","high","A configuration file (such as .env) is served by the web server.","Such files commonly hold database passwords, API keys and application secrets.","Remove the file from the web root or block access to it, and rotate every secret it contains.",cvss="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N",cwe="CWE-538",owasp="A05:2021 Security Misconfiguration",lib=("sensitive file","information disclosure")),
"backup-exposed":_rule("Backup or archive files exposed on the web server","medium","Backup, archive or database dump files are served by the web server.","These files can disclose source code, configuration and data.","Remove backup files from the web root and block the extensions at the web server.",cwe="CWE-530",owasp="A05:2021 Security Misconfiguration",lib=("backup file","information disclosure")),
"admin-exposed":_rule("Administrative interface exposed","low","An administrative or management interface was found on the web server.","Exposed administration panels are targets for password guessing and for vulnerabilities in the management software.","Restrict administrative interfaces to trusted networks and require strong, multi-factor authentication.",cwe="CWE-284",owasp="A05:2021 Security Misconfiguration",lib=("admin interface","administrative interface")),
"info-page":_rule("Diagnostic page discloses server information","low","A diagnostic page (such as phpinfo or server-status) is publicly reachable.","It discloses versions, paths, modules, environment variables and sometimes requests of other users, which helps to plan further attacks.","Remove diagnostic pages or restrict them to administrators.",cwe="CWE-200",owasp="A05:2021 Security Misconfiguration",lib=("information disclosure",)),
"dir-listing":_rule("Directory listing enabled","low","The web server returns directory listings.","Files that are not linked from the application can be discovered and downloaded.","Disable directory indexing (Options -Indexes / autoindex off).",cwe="CWE-548",owasp="A05:2021 Security Misconfiguration",lib=("directory listing",)),
"security-headers":_rule("Missing HTTP security headers","low","The web server does not send recommended security response headers.","Browsers lack instructions that mitigate clickjacking, MIME sniffing and content injection.","Send X-Frame-Options or a frame-ancestors policy, X-Content-Type-Options, a Content-Security-Policy and Strict-Transport-Security.",cwe="CWE-693",owasp="A05:2021 Security Misconfiguration",lib=("security headers",)),
"nikto-outdated":_rule("Outdated web server software","low","The scanner reports that the web server software is outdated.","Security fixes released since then are missing.","Upgrade the web server software to a supported release.",cwe="CWE-1104",owasp="A06:2021 Vulnerable and Outdated Components",lib=("outdated software","outdated")),
"default-creds":_rule("Weak or default credentials accepted","high","A password guessing run reported a successful login.","The account can be used by anyone who guesses or knows the password, giving access with that account's privileges.","Change the password to a strong unique value, remove default accounts, and enforce lockout and multi-factor authentication.",cvss=_V_NET_FULL,cwe="CWE-1392",owasp="A07:2021 Identification and Authentication Failures",lib=("default cred","weak cred","weak password")),
"sqli":_rule("SQL injection","critical","A request parameter is used in a database query without proper parameterisation; sqlmap confirmed an injection point.","An attacker can read or modify database contents and, depending on the database and privileges, execute commands on the server.","Use parameterised queries or prepared statements for all database access, validate input and run the application with a least-privilege database account.",cvss=_V_NET_FULL,cwe="CWE-89",owasp="A03:2021 Injection",lib=("sql injection","sqli")),
"root-shell":_rule("Privileged access obtained on a host","critical","Command output shows an identity with full administrative privileges (uid 0 / SYSTEM).","Full control over the host: all data can be read or changed, and the host can be used to attack others.","Fix the vulnerability or misconfiguration that gave this access (see the related findings) and review the host for persistence.",cwe="CWE-269",lib=("privilege escalation",)),
"sudo-nopasswd":_rule("Sudo configuration allows privilege escalation","high","The account may run commands through sudo without a password (NOPASSWD).","A compromise of this account leads directly to root, either through unrestricted sudo or through programs that can spawn a shell.","Remove NOPASSWD entries, limit sudo rules to the specific commands required and avoid programs with shell escapes.",cvss="CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H",cwe="CWE-269",lib=("sudo","privilege escalation")),
"kerberoast":_rule("Kerberoastable service accounts","medium","Service tickets could be requested for accounts with a service principal name; the ticket can be cracked offline.","Weak service account passwords are recovered offline, often yielding privileged domain access.","Use group managed service accounts or long random passwords for service accounts and prefer AES-only encryption types.",cwe="CWE-521",lib=("kerberoast",)),
"asreproast":_rule("Accounts without Kerberos pre-authentication (AS-REP roasting)","medium","An AS-REP could be requested for accounts that do not require Kerberos pre-authentication; it can be cracked offline.","Weak passwords of those accounts are recovered offline.","Enable Kerberos pre-authentication for all accounts and enforce strong passwords.",cwe="CWE-521",lib=("as-rep","asrep")),
"llmnr":_rule("LLMNR/NBT-NS poisoning possible","medium","Name resolution poisoning captured authentication from hosts on the network.","Captured NetNTLM hashes can be cracked offline or relayed to other hosts.","Disable LLMNR and NBT-NS through Group Policy and require SMB signing.",cwe="CWE-290",lib=("llmnr","nbt-ns")),
"wordpress-vulns":_rule("Vulnerable WordPress components","medium","WPScan reported known vulnerabilities in the WordPress core, plugins or themes in use.","Depending on the component, impact ranges from information disclosure to remote code execution.","Update WordPress core, plugins and themes, and remove components that are not used.",cwe="CWE-1104",owasp="A06:2021 Vulnerable and Outdated Components",lib=("outdated software","wordpress")),
"redis-noauth":_rule("Redis accessible without authentication","high","The Redis service returned server information without authentication.","Unauthenticated users can read and modify cached data and can often obtain code execution on the host.","Require authentication (requirepass/ACLs), bind Redis to localhost or an internal interface and enable protected mode.",cvss=_V_NET_FULL,cwe="CWE-306",lib=("redis","unauthenticated")),
}
# ---------------------------------------------------------------- recognisers
def _version(text):
    return tuple(int(part) for part in re.findall(r"\d+",str(text))[:4])
def _hit(rule,reason,confidence="medium",host="",port=None,proto="tcp",lines=(),**extra):
    return dict(rule=rule,reason=reason,confidence=confidence,host=host,port=port,proto=proto,lines=[line for line in lines if line][:12],**extra)
_DB_SERVICES={"mysql":"MySQL","postgresql":"PostgreSQL","ms-sql-s":"Microsoft SQL Server","oracle-tns":"Oracle","oracle":"Oracle","mongodb":"MongoDB","mongod":"MongoDB","redis":"Redis","couchdb":"CouchDB","memcached":"Memcached","cassandra":"Cassandra","elasticsearch":"Elasticsearch"}
_DB_PORTS={3306:"MySQL",5432:"PostgreSQL",1433:"Microsoft SQL Server",1521:"Oracle",27017:"MongoDB",6379:"Redis",5984:"CouchDB",11211:"Memcached",9200:"Elasticsearch"}
def exposure_hits(host,port):
    """Service exposure candidates for one open nmap port."""
    if port["state"]!="open":return []
    number=port["port"];proto=port["proto"]
    service=port["service"].lower().rstrip("?")
    tls=service.startswith("ssl/") or service.startswith("https") or "ssl" in service.split("/")
    name=service.split("/")[-1]
    unknown=name in ("","unknown")
    line=str(number)+"/"+proto+" open "+port["service"]+(" "+port["version"] if port["version"] else "")
    base=dict(host=host,port=number,proto=proto,lines=[line])
    def hit(rule,reason,confidence="medium",**extra):return [_hit(rule,reason,confidence,**dict(base,**extra))]
    if name=="tcpwrapped":return []
    if name=="telnet" or (unknown and number==23 and proto=="tcp"):return hit("telnet","Port "+str(number)+"/"+proto+" is open and identified as Telnet.","high" if name=="telnet" else "low")
    if name in ("ftp","ftps") or (unknown and number==21 and proto=="tcp"):return hit("ftp","Port "+str(number)+"/"+proto+" is open and identified as FTP.","medium" if name=="ftp" else "low") if not tls and name!="ftps" else []
    if (name in ("exec","login","shell","rsh","rlogin","rexec") and number in (512,513,514)) or (unknown and number in (512,513,514) and proto=="tcp"):return hit("rservices","Port "+str(number)+"/tcp is open ("+(name or "r-service port")+").","medium" if not unknown else "low")
    if name.startswith("vnc") or (unknown and 5900<=number<=5903):return hit("vnc","Port "+str(number)+"/"+proto+" is open and identified as VNC.","medium" if name.startswith("vnc") else "low")
    if name in ("ms-wbt-server","rdp") or (unknown and number==3389):return hit("rdp","Port "+str(number)+"/"+proto+" is open (Remote Desktop).","medium" if not unknown else "low")
    if name in ("microsoft-ds","netbios-ssn","smb") or (unknown and number in (139,445) and proto=="tcp"):return hit("smb","Port "+str(number)+"/tcp is open (SMB/NetBIOS).","medium" if not unknown else "low")
    if name=="snmp" or (unknown and number==161 and proto=="udp"):return hit("snmp","Port "+str(number)+"/"+proto+" is open (SNMP).","medium" if name=="snmp" else "low")
    if name in _DB_SERVICES or (unknown and number in _DB_PORTS):
        product=_DB_SERVICES.get(name) or _DB_PORTS.get(number)
        return hit("database","Port "+str(number)+"/"+proto+" is open and identified as "+product+".","medium" if name in _DB_SERVICES else "low",variant=product)
    if name=="ajp13":return hit("ajp","Port "+str(number)+"/tcp is open and identified as AJP.","low")
    if name=="distccd":return hit("distcc","Port "+str(number)+"/tcp is open and identified as distccd.","medium")
    if name in ("http","http-proxy","http-alt") and not tls and number not in (443,8443):return hit("http-plain","Port "+str(number)+"/"+proto+" serves HTTP without TLS. Confirm that it carries more than a redirect to HTTPS.","low")
    return []
_EOL_WINDOWS_RE=re.compile(r"Windows(?: Server)? (XP|2000|2003|Vista|7|2008(?: R2)?|Server 2003|Server 2008(?: R2)?)\b",re.I)
def version_hits(host,port_number,proto,text,line=""):
    """Outdated/backdoored software candidates from one banner or version string."""
    text=str(text or "")
    if not text:return []
    out=[]
    base=dict(host=host,port=port_number,proto=proto,lines=[line or text])
    def hit(rule,reason,confidence="low",**extra):out.append(_hit(rule,reason,confidence,**dict(base,**extra)))
    found=re.search(r"OpenSSH[ _]([\d.]+)",text)
    if found and _version(found.group(1))<(8,0):
        version=_version(found.group(1))
        hit("outdated-openssh","Banner reports OpenSSH "+found.group(1)+" (older than 8.0). Distribution packages may carry backported fixes.","low",severity="medium" if version<(7,0) else "low",variant=found.group(1))
    found=re.search(r"Apache httpd ([\d.]+)|Apache/([\d.]+)",text)
    if found:
        raw=found.group(1) or found.group(2);version=_version(raw)
        if version in ((2,4,49),(2,4,50)):hit("apache-traversal","Banner reports Apache HTTP Server "+raw+" (CVE-2021-41773 / CVE-2021-42013).","medium")
        elif len(version)>=2 and version<(2,4):hit("apache-eol","Banner reports Apache HTTP Server "+raw+" (end-of-life branch).","medium",variant=raw)
        elif len(version)>=3 and version<(2,4,56):hit("apache-old","Banner reports Apache HTTP Server "+raw+". Distribution packages may carry backported fixes.","low",variant=raw)
    if re.search(r"vsftpd 2\.3\.4\b",text):hit("vsftpd-backdoor","Banner reports vsftpd 2.3.4 (CVE-2011-2523). Only the tampered archive is backdoored - confirm.","medium")
    if re.search(r"ProFTPD 1\.3\.3c\b",text):hit("proftpd-backdoor","Banner reports ProFTPD 1.3.3c. Only the tampered archive is backdoored - confirm.","medium")
    elif re.search(r"ProFTPD 1\.3\.5(?![\d.a-z])",text):hit("proftpd-modcopy","Banner reports ProFTPD 1.3.5 (CVE-2015-3306 when mod_copy is loaded).","low")
    if re.search(r"UnrealIRCd[ /]?3\.2\.8\.1\b",text,re.I):hit("unrealircd-backdoor","Banner reports UnrealIRCd 3.2.8.1 (CVE-2010-2075).","medium")
    found=re.search(r"Samba (?:smbd )?(\d+\.\d+\.\d+)",text)
    if found:
        version=_version(found.group(1))
        if (3,0,20)<=version<=(3,0,25):hit("samba-usermap","Banner reports Samba "+found.group(1)+" (CVE-2007-2447).","medium")
        elif (3,5,0)<=version<(4,6,4):hit("samba-old","Banner reports Samba "+found.group(1)+" (CVE-2017-7494 range). Distribution packages may carry the backported fix.","low",variant=found.group(1))
    found=re.search(r"Microsoft IIS httpd ([\d.]+)|Microsoft-IIS/([\d.]+)",text)
    if found:
        raw=found.group(1) or found.group(2);version=_version(raw)
        if version and version<(10,):hit("iis-eol","Banner reports Microsoft IIS "+raw+", shipped with an end-of-life Windows Server release.","medium",severity="high" if version<(8,) else "medium",variant=raw)
    found=re.search(r"nginx[ /]([\d.]+)",text)
    if found and len(_version(found.group(1)))>=2 and _version(found.group(1))<(1,20):hit("nginx-old","Banner reports nginx "+found.group(1)+". Distribution packages may carry backported fixes.","low",variant=found.group(1))
    found=re.search(r"PHP/([\d.]+)",text)
    if found and len(_version(found.group(1)))>=2 and _version(found.group(1))<(8,1):
        hit("php-eol","Server reports PHP "+found.group(1)+" (end-of-life branch).","medium",severity="medium" if _version(found.group(1))<(7,4) else "low",variant=found.group(1))
    found=re.search(r"MySQL ([\d.]+)",text)
    if found and len(_version(found.group(1)))>=2 and _version(found.group(1))<(5,7) and "MariaDB" not in text:hit("mysql-old","Banner reports MySQL "+found.group(1)+" (end-of-life branch).","low",variant=found.group(1))
    found=re.search(r"Exim smtpd ([\d.]+)",text)
    if found and len(_version(found.group(1)))>=2 and _version(found.group(1))<(4,92):hit("exim-old","Banner reports Exim "+found.group(1)+" (older than 4.92, CVE-2019-10149 range).","low",variant=found.group(1))
    found=re.search(r"Apache Tomcat[ /]([\d.]+)",text)
    if found and len(_version(found.group(1)))>=2 and _version(found.group(1))<(9,0):hit("tomcat-eol","Banner reports Apache Tomcat "+found.group(1)+" (end-of-life branch).","medium",variant=found.group(1))
    found=re.search(r"OpenSSL/(\d+\.\d+\.\d+)([a-z]?)",text)
    if found:
        version=_version(found.group(1))
        if version==(1,0,1) and found.group(2) in ("","a","b","c","d","e","f"):hit("openssl-heartbleed","Server reports OpenSSL "+found.group(1)+found.group(2)+" (CVE-2014-0160 range).","low")
        elif version<(1,1,1):hit("openssl-old","Server reports OpenSSL "+found.group(1)+found.group(2)+" (end-of-life branch).","low",variant=found.group(1))
    return out
def os_hits(host,text,confidence,line=""):
    text=str(text or "")
    if "|" in text or "," in text.split("(")[0]:return []
    found=_EOL_WINDOWS_RE.search(text)
    if not found:return []
    return [_hit("os-eol","Host identifies as "+found.group(0)+", which is past its end of support.",confidence,host=host,port=None,lines=[line or text],variant=found.group(0))]
_VULN_SCRIPT_RE=re.compile(r"(?:^|-)vuln|^ssl-(?:heartbleed|poodle|ccs-injection|dh-params)$|^sslv2-drown$|backdoor|^http-shellshock$|^realvnc-auth-bypass$|^distcc-cve2004-2687$|^rmi-vuln-classloader$|cve-?\d{4}",re.I)
_RISK_SEVERITY={"critical":"critical","high":"high","medium":"medium","low":"low"}
def script_hits(host,script):
    """Candidates from one nmap NSE script block {id,output,port?,proto?}."""
    sid=script.get("id","");output=script.get("output","")
    low=output.lower()
    port=script.get("port");proto=script.get("proto","tcp")
    lines=["| "+sid+":"]+[("|   "+line.strip()) for line in output.split("\n")[:10] if line.strip()]
    base=dict(host=host,port=port,proto=proto,lines=lines)
    def hit(rule,reason,confidence="medium",**extra):return [_hit(rule,reason,confidence,**dict(base,**extra))]
    if _VULN_SCRIPT_RE.search(sid):
        state=re.search(r"State:\s*((?:LIKELY )?VULNERABLE|NOT VULNERABLE)",output)
        vulnerable=bool(state and state.group(1)!="NOT VULNERABLE") or (not state and re.search(r"^\s*VULNERABLE:?\s*$",output,re.M) is not None)
        if not vulnerable:return []
        confidence="medium" if state and state.group(1).startswith("LIKELY") else "high"
        cves=sorted(set(re.findall(r"CVE-\d{4}-\d{4,7}",output)))
        if "ms17-010" in sid.lower() or "CVE-2017-0143" in cves or "CVE-2017-0144" in cves:return hit("ms17-010","Nmap script "+sid+" reports State: VULNERABLE.",confidence)
        if "ms08-067" in sid.lower():return hit("ms08-067","Nmap script "+sid+" reports State: VULNERABLE.",confidence)
        if sid=="ssl-heartbleed":return hit("openssl-heartbleed","Nmap script ssl-heartbleed reports State: VULNERABLE.",confidence,title="Heartbleed OpenSSL memory disclosure")
        title=""
        rows=[row.strip() for row in output.split("\n")]
        for index,row in enumerate(rows):
            if row.rstrip(":")=="VULNERABLE" and index+1<len(rows):title=rows[index+1];break
        risk=re.search(r"Risk factor:\s*(\w+)",output)
        severity=_RISK_SEVERITY.get(risk.group(1).lower(),"high") if risk else "high"
        return hit("nmap-vuln","Nmap script "+sid+" reports State: "+(state.group(1) if state else "VULNERABLE")+".",confidence,variant=sid,title=(title[:150] or "Vulnerability reported by Nmap script "+sid),severity=severity,refs=cves)
    if sid=="ssl-enum-ciphers":
        problems=[]
        for proto_name in ("SSLv2","SSLv3","TLSv1.0","TLSv1.1"):
            if re.search(r"^\s*"+re.escape(proto_name)+r":",output,re.M):problems.append(proto_name+" offered")
        grade=re.search(r"least strength:\s*([A-F])",output)
        if grade and grade.group(1) in "CDEF":problems.append("least cipher strength "+grade.group(1))
        if re.search(r"RC4|3DES|SWEET32|NULL|EXPORT|anon",output) and re.search(r"warnings:|\b[CDEF]\s*$",output,re.M):
            if "weak ciphers flagged" not in problems:problems.append("weak ciphers flagged")
        return hit("weak-tls","Nmap ssl-enum-ciphers: "+", ".join(problems)+".","high") if problems else []
    if sid=="ssl-cert":
        expiry=re.search(r"Not valid after:\s*(\d{4}-\d{2}-\d{2})",output)
        if expiry and expiry.group(1)<datetime.now(timezone.utc).strftime("%Y-%m-%d"):return hit("cert-expired","Certificate was valid until "+expiry.group(1)+".","high")
        return []
    if sid=="smb-security-mode":
        return hit("smb-signing","Nmap smb-security-mode reports message_signing: disabled.","high") if re.search(r"message_signing:\s*disabled",low) else []
    if sid=="smb2-security-mode":
        return hit("smb-signing","Nmap smb2-security-mode reports that signing is enabled but not required.","high") if "not required" in low else []
    if sid=="smb-protocols":
        return hit("smbv1","Nmap smb-protocols lists the SMBv1 dialect (NT LM 0.12).","high") if "smbv1" in low or "nt lm 0.12" in low else []
    if sid=="smb-os-discovery":
        found=re.search(r"OS:\s*(.+)",output)
        return os_hits(host,found.group(1),"medium","| smb-os-discovery: OS: "+found.group(1).strip()) if found else []
    if sid=="ftp-anon":
        return hit("ftp-anon","Nmap ftp-anon reports that anonymous FTP login is allowed.","high") if "anonymous ftp login allowed" in low else []
    if sid=="http-methods":
        risky=re.search(r"Potentially risky methods:\s*(.+)",output)
        return hit("http-methods","Nmap http-methods lists potentially risky methods: "+risky.group(1).strip()+".","medium") if risky else []
    if sid=="http-git":
        return hit("git-exposed","Nmap http-git found a Git repository in the web root.","high") if "git repository found" in low else []
    if sid=="vnc-info":
        return hit("vnc-noauth","Nmap vnc-info lists the security type None (no authentication).","high") if re.search(r"\bnone\b|no authentication",low) else []
    if sid=="mysql-empty-password":
        return hit("db-noauth","Nmap mysql-empty-password reports an account with an empty password.","high",variant="MySQL") if "empty password" in low else []
    if sid=="redis-info":
        return hit("redis-noauth","Nmap redis-info returned server information without authentication.","high") if re.search(r"version|role|used memory",low) else []
    if sid in ("snmp-info","snmp-sysdescr","snmp-interfaces","snmp-processes","snmp-netstat","snmp-win32-users") and output.strip():
        return hit("snmp-public","Nmap script "+sid+" returned data using a default community string.","medium")
    if sid=="nfs-showmount":
        return hit("nfs-export","Nmap nfs-showmount lists exports open to any host.","medium") if re.search(r"\s\*\s*$|\(everyone\)",output,re.M) else []
    if sid=="http-server-header":
        return version_hits(host,port,proto,output,"|_http-server-header: "+output.split("\n")[0])
    return []
def nmap_hits(parsed_hosts):
    out=[]
    for host in parsed_hosts:
        name=host["host"] or "unknown host"
        for port in host["ports"]:
            out+=exposure_hits(name,port)
            if port["state"]=="open":
                out+=version_hits(name,port["port"],port["proto"],port["version"],str(port["port"])+"/"+port["proto"]+" open "+port["service"]+" "+port["version"])
            for script in port["scripts"]:out+=script_hits(name,script)
        for script in host["scripts"]:
            hits=script_hits(name,script)
            for hit in hits:
                if hit.get("port") is None and hit["rule"] in ("ms17-010","ms08-067","smb-signing","smbv1","nmap-vuln"):hit["port"]=445
            out+=hits
        if host.get("os") and not host["os"].endswith("(guess)") and host.get("os")!=host.get("service_os"):out+=os_hits(name,host["os"],"low","OS details: "+host["os"])
    return out
_URL_RE=re.compile(r"\b(https?)://(\[[0-9a-fA-F:]+\]|[A-Za-z0-9.-]+)(?::(\d{1,5}))?")
_IP_RE=re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
_HOSTNAME_RE=re.compile(r"(?<![\w.@/-])(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+(?:[A-Za-z]{2,24})(?![\w-])")
_FILE_EXT_RE=re.compile(r"\.(txt|lst|log|xml|json|py|sh|pl|rb|php|html?|conf|cfg|ini|csv|out|nmap|gnmap|zip|gz|tar|exe|dll|ps1|bat|pcap|key|pem|crt|db|sql|md|yaml|yml)$",re.I)
def command_target(command,fallback=""):
    """(host,port) a command is aimed at: the first URL, IPv4 address or host name on its command line."""
    text=_norm(command)
    found=_URL_RE.search(text)
    if found:return found.group(2).strip("[]"),int(found.group(3)) if found.group(3) else (443 if found.group(1).lower()=="https" else 80)
    found=_IP_RE.search(text)
    if found:
        port=re.match(r":(\d{1,5})\b",text[found.end():])
        return found.group(0),int(port.group(1)) if port else None
    for found in _HOSTNAME_RE.finditer(text):
        if not _FILE_EXT_RE.search(found.group(0)):return found.group(0),None
    return fallback,None
def _lines(text):return str(text or "").replace("\r\n","\n").split("\n")
_HYDRA_RE=re.compile(r"^\[(\d{1,5})\]\[([\w-]+)\]\s+host:\s*(\S+)\s+(?:login:\s*(\S*)\s+)?password:\s*(.*)$")
_MEDUSA_RE=re.compile(r"ACCOUNT FOUND:\s*\[([\w-]+)\]\s*Host:\s*(\S+)\s+User:\s*(\S+)\s+Password:\s*(\S*).*\[SUCCESS",re.I)
_CME_RE=re.compile(r"^(SMB|WINRM|SSH|MSSQL|RDP|LDAP|FTP|WMI)\s+(\S+)\s+(\d{1,5})\s+\S+\s+\[\+\]\s+(\S+?):(\S*)\s.*\(Pwn3d!\)",re.I)
def credential_hits(record):
    out=[]
    for line in _lines(record["output"]):
        text=line.strip()
        found=_HYDRA_RE.match(text)
        if found:
            out.append(_hit("default-creds","Hydra reports a valid login for "+(found.group(4) or "(no user)")+" on "+found.group(2)+".","high",host=found.group(3),port=int(found.group(1)),lines=[text],variant=found.group(2)))
            continue
        found=_MEDUSA_RE.search(text)
        if found:
            out.append(_hit("default-creds","Medusa reports a valid login for "+found.group(3)+" on "+found.group(1)+".","high",host=found.group(2),port=None,lines=[text],variant=found.group(1).lower()))
            continue
        found=_CME_RE.match(text)
        if found:out.append(_hit("default-creds","The account "+found.group(4)+" authenticated with administrative rights (Pwn3d!) over "+found.group(1).upper()+".","high",host=found.group(2),port=int(found.group(3)),lines=[text],variant=found.group(1).lower()))
    return out
def sqlmap_hits(record):
    output=record["output"]
    if "sqlmap" not in record["command"].lower() and "sqlmap" not in output.lower()[:4000] and "sqlmap identified" not in output:return []
    points=re.findall(r"^Parameter:\s*(.+?)\s*$",output,re.M)
    confirmed="sqlmap identified the following injection point" in output or bool(re.search(r"parameter '[^']+' is vulnerable",output,re.I))
    if not confirmed or (not points and not re.search(r"is vulnerable",output,re.I)):return []
    host,port=command_target(record["command"],record["target"])
    kept=[line.strip() for line in _lines(output) if re.match(r"\s*(Parameter:|Type:|Title:|Payload:)",line) or "is vulnerable" in line]
    types=sorted(set(re.findall(r"^\s*Type:\s*(.+?)\s*$",output,re.M)))
    reason="sqlmap identified an injection point"+(" in "+", ".join(sorted(set(points))[:4]) if points else "")+(" ("+", ".join(types[:4])+")" if types else "")+"."
    return [_hit("sqli",reason,"high",host=host,port=port,lines=kept,variant=host)]
_NIKTO_RULES=(
(re.compile(r"X-Frame-Options header is not present|X-Content-Type-Options header is not set|Strict-Transport-Security HTTP header is not defined|Content-Security-Policy.*not (?:present|set)",re.I),"security-headers","low"),
(re.compile(r"Directory indexing found|directory listing",re.I),"dir-listing","medium"),
(re.compile(r"HTTP TRACE method is active|Allowed HTTP Methods:.*\b(?:PUT|DELETE|TRACE)\b|HTTP method .*(?:PUT|DELETE).*allow",re.I),"http-methods","medium"),
(re.compile(r"phpinfo\(\)|/server-status|/server-info|\bphpinfo\.php",re.I),"info-page","medium"),
(re.compile(r"default (?:account|password|credentials?) (?:found|was found)|Default account found",re.I),"default-creds","medium"),
(re.compile(r"appears to be outdated",re.I),"nikto-outdated","low"),
(re.compile(r"/\.git/|\.git/(?:HEAD|config|index)",re.I),"git-exposed","medium"),
(re.compile(r"\.env\b.*(?:found|file)|/\.env:",re.I),"env-exposed","medium"),
(re.compile(r"backup|\.bak\b|\.old\b|\.tar\b|\.sql\b|database dump",re.I),"backup-exposed","low"),
(re.compile(r"admin(?:istration)? (?:login|page|interface|console)|/phpmyadmin|/manager/html",re.I),"admin-exposed","low"),
)
def nikto_hits(record):
    output=record["output"]
    if "nikto" not in record["command"].lower() and not re.search(r"^- Nikto v|^\+ Target (?:IP|Hostname):",output,re.M):return []
    host,port=command_target(record["command"],record["target"])
    found=re.search(r"^\+ Target (?:Hostname|IP):\s*(\S+)",output,re.M)
    if found and not host:host=found.group(1)
    found=re.search(r"^\+ Target Port:\s*(\d+)",output,re.M)
    if found:port=int(found.group(1))
    out=[]
    for line in _lines(output):
        text=line.strip()
        if not text.startswith("+ ") or re.match(r"\+ (Target|Start Time|End Time|Server:|\d+ (?:requests|host))",text):continue
        for pattern,rule,confidence in _NIKTO_RULES:
            if pattern.search(text):
                out.append(_hit(rule,"Nikto: "+text[2:220],confidence,host=host,port=port,lines=[text]))
                break
    return out
_DIR_LINE_RES=(
re.compile(r"^(/\S*)\s+\(Status:\s*(\d{3})\)"),
re.compile(r"^(\S+)\s+\[Status:\s*(\d{3}),"),
re.compile(r"^\+ (https?://\S+)\s+\(CODE:(\d{3})"),
re.compile(r"^(\d{3})\s+\S+\s+\S+l\s+\S+w\s+\S+c\s+(https?://\S+)"),
re.compile(r"^\[[\d:]+\]\s+(\d{3})\s+-\s+\S+\s+-\s+(/\S*)"),
)
_DIR_RULES=(
(re.compile(r"(?:^|/)\.git(?:/|$)",re.I),"git-exposed","medium"),
(re.compile(r"(?:^|/)\.env(?:\.[\w-]+)?$|(?:^|/)(?:wp-config\.php\.\w+|config\.php\.\w+|web\.config\.\w+|\.htpasswd|id_rsa)$",re.I),"env-exposed","medium"),
(re.compile(r"\.(?:bak|old|orig|save|swp|sql|sql\.gz|tar|tar\.gz|tgz|zip|7z|rar|dump)$|(?:^|/)(?:backup|backups|dump)s?/?$",re.I),"backup-exposed","low"),
(re.compile(r"(?:^|/)(?:phpinfo(?:\.php)?|info\.php|server-status|server-info)$",re.I),"info-page","medium"),
(re.compile(r"(?:^|/)(?:admin|administrator|phpmyadmin|pma|wp-admin|manager/html|adminer(?:\.php)?|cpanel|webmin)/?$",re.I),"admin-exposed","low"),
)
def dirscan_hits(record):
    tool=tool_name(record["command"])
    output=record["output"]
    if tool not in ("gobuster","ffuf","dirb","feroxbuster","dirsearch","wfuzz") and not re.search(r"Gobuster v|\(Status:\s*\d{3}\)|DIRB v|:: Method\s+:|feroxbuster",output):return []
    host,port=command_target(record["command"],record["target"])
    out=[]
    for line in _lines(output):
        text=re.sub(r"^\s+","",line.rstrip())
        path=status=None
        for index,pattern in enumerate(_DIR_LINE_RES):
            found=pattern.match(text)
            if not found:continue
            path,status=(found.group(2),found.group(1)) if index in (3,4) else (found.group(1),found.group(2))
            break
        if not path:continue
        status=int(status)
        clean=re.sub(r"^https?://[^/]+","",path).split("?")[0]
        if not clean.startswith("/"):clean="/"+clean
        for pattern,rule,confidence in _DIR_RULES:
            if not pattern.search(clean):continue
            # A sensitive file is only a finding when the server actually serves it; panels and redirects to them count as present.
            ok=status==200 if rule in ("git-exposed","env-exposed","backup-exposed","info-page") else status in (200,301,302,401)
            if rule=="git-exposed" and status in (301,302) and clean.rstrip("/").endswith(".git"):ok=True
            if ok:out.append(_hit(rule,"Content discovery found "+clean+" (HTTP "+str(status)+").",confidence,host=host,port=port,lines=[text[:200]]))
            break
    return out
def shell_hits(record):
    """Privilege evidence from an interactive shell: root/SYSTEM identity, sudo NOPASSWD rules."""
    out=[]
    command=_norm(record["command"]);output=record["output"]
    low=command.lower()
    host=record["target"]
    elevated_by_user=bool(re.match(r"(sudo|doas|su|pkexec|runas)\b",low))
    if not elevated_by_user:
        found=re.search(r"^uid=0\(root\)\s+gid=\d+\([^)]*\).*$",output,re.M)
        if found and (not command or re.search(r"\bid\b",low)):out.append(_hit("root-shell","Output of id shows uid=0(root). Confirm that the command ran on the target and not on the testing machine.","low",host=host,lines=[found.group(0).strip()[:200]],variant=host))
        found=re.search(r"^nt authority\\system\s*$",output,re.M|re.I)
        if found and (not command or "whoami" in low):out.append(_hit("root-shell","Output of whoami shows NT AUTHORITY\\SYSTEM. Confirm that the command ran on the target.","low",host=host,lines=[found.group(0).strip()],variant=host))
    if re.search(r"\bsudo\s+(?:-\S+\s+)*-l\b|\bsudo\s+-\S*l",low) or "may run the following commands" in output:
        rules=[line.strip() for line in _lines(output) if re.search(r"\(\s*[\w,:\s!%-]+\)\s*(?:\w+:\s*)*NOPASSWD:",line)]
        if rules:
            full=any(re.search(r"NOPASSWD:\s*ALL\s*$",rule) for rule in rules)
            out.append(_hit("sudo-nopasswd","sudo -l lists "+("NOPASSWD: ALL" if full else "commands that run as another user without a password")+".","high" if full else "medium",host=host,lines=rules,severity="high" if full else "medium",variant=host))
    return out
def misc_hits(record):
    out=[]
    command=_norm(record["command"]);output=record["output"]
    low=command.lower();tool=tool_name(command)
    host,port=command_target(command,record["target"])
    if tool in ("ftp","lftp","ncftp","curl","wget","nc","ncat","telnet") or not command:
        if re.search(r"^230[ -].*",output,re.M) and (re.search(r"Name \([^)]*\):\s*anonymous|USER anonymous|331 .*anonymous|anonymous",output,re.I) or "anonymous" in low):
            found=re.search(r"^230[ -].*$",output,re.M)
            out.append(_hit("ftp-anon","The FTP server answered 230 (login successful) to an anonymous login.","high",host=host,port=port or 21,lines=[found.group(0).strip()[:200]]))
    if re.search(r"Anonymous login successful",output) or re.search(r"allows sessions using username '', password ''",output):
        found=re.search(r"^.*(?:Anonymous login successful|allows sessions using username '', password '').*$",output,re.M)
        out.append(_hit("smb-null","The SMB server accepted a session without credentials.","medium",host=host,port=445,lines=[found.group(0).strip()[:200]]))
    if tool=="showmount" or re.search(r"^Export list for \S+:",output,re.M):
        exports=[line.strip() for line in _lines(output) if re.match(r"^/\S*\s+(?:\*|\(everyone\)|0\.0\.0\.0/0)",line.strip())]
        if exports:
            found=re.search(r"^Export list for (\S+?):",output,re.M)
            out.append(_hit("nfs-export","showmount lists exports open to any host.","high",host=host or (found.group(1) if found else ""),port=2049,lines=exports))
    if tool=="onesixtyone" or re.search(r"^\S+ \[(?:public|private)\] ",output,re.M):
        for found in re.finditer(r"^(\S+) \[(public|private|community|manager)\] (.*)$",output,re.M):
            out.append(_hit("snmp-public","onesixtyone: the agent answered to the community string \""+found.group(2)+"\".","high",host=found.group(1),port=161,proto="udp",lines=[found.group(0).strip()[:200]]))
    elif tool in ("snmpwalk","snmpget","snmpbulkwalk","snmp-check") and re.search(r"-c\s*['\"]?(public|private)\b",command) and re.search(r"^(?:iso\.|SNMPv2-MIB::|\.1\.3\.6\.)\S+ = ",output,re.M):
        found=re.search(r"^(?:iso\.|SNMPv2-MIB::|\.1\.3\.6\.)\S+ = .*$",output,re.M)
        out.append(_hit("snmp-public","The agent returned data for a default community string.","high",host=host,port=161,proto="udp",lines=[found.group(0).strip()[:200]]))
    weak=[line.strip() for line in _lines(output) if re.match(r"^\s*(?:SSLv2|SSLv3|TLSv1\.0|TLSv1\.1)\s+enabled\s*$",line) or re.match(r"^\s*(?:SSLv2|SSLv3|TLS 1|TLS 1\.1)\s+offered \((?:NOT ok|deprecated)\)",line)]
    if weak:out.append(_hit("weak-tls","The TLS scan reports deprecated protocol versions: "+", ".join(re.split(r"\s{2,}|\s+(?=enabled|offered)",item)[0] for item in weak[:4])+".","high",host=host,port=port or 443,lines=weak))
    if "$krb5tgs$" in output:
        users=sorted(set(re.findall(r"\$krb5tgs\$\d+\$\*?([^$*]+)\$",output)))
        out.append(_hit("kerberoast","Service tickets were obtained"+(" for "+", ".join(users[:5]) if users else "")+".","high",host=host,port=88,lines=[line.strip()[:120]+"..." for line in _lines(output) if "$krb5tgs$" in line][:5]))
    if "$krb5asrep$" in output:
        users=sorted(set(re.findall(r"\$krb5asrep\$\d+\$([^:@$]+)",output)))
        out.append(_hit("asreproast","AS-REP responses were obtained"+(" for "+", ".join(users[:5]) if users else "")+".","high",host=host,port=88,lines=[line.strip()[:120]+"..." for line in _lines(output) if "$krb5asrep$" in line][:5]))
    if re.search(r"\[(?:SMB|HTTP|MSSQL|LDAP|FTP)\] NTLMv[12](?:-SSP)? (?:Hash|Client|Username)",output):
        kept=[line.strip()[:160] for line in _lines(output) if re.search(r"Poisoned answer sent to|NTLMv[12](?:-SSP)? (?:Client|Username)",line)]
        out.append(_hit("llmnr","Responder captured NetNTLM authentication after poisoning name resolution.","high",host="",port=None,lines=kept[:8]))
    if tool=="wpscan" or "WordPress Security Scanner" in output:
        titles=[line.split("Title:",1)[1].strip() for line in _lines(output) if re.match(r"^\s*(?:\|\s*)?\[!\] Title:",line)]
        if titles:out.append(_hit("wordpress-vulns","WPScan lists "+str(len(titles))+" known vulnerabilit"+("y" if len(titles)==1 else "ies")+": "+"; ".join(titles[:3])+("..." if len(titles)>3 else ""),"medium",host=host,port=port,lines=["[!] Title: "+title for title in titles[:10]],variant=host))
    return out
def record_hits(record):
    """Every candidate hit one command record yields."""
    output=record.get("output") or ""
    if not output.strip():return []
    hits=[]
    if "Nmap scan report for" in output or re.search(r"^\d{1,5}/(?:tcp|udp)\s+(?:open|closed|filtered)",output,re.M):
        parsed=parse_nmap(output)
        fallback=command_target(record["command"],record["target"])[0]
        for host in parsed:
            if not host["host"]:host["host"]=fallback
        hits+=nmap_hits(parsed)
    for finder in (credential_hits,sqlmap_hits,nikto_hits,dirscan_hits,shell_hits,misc_hits):
        hits+=finder(record)
    for hit in hits:
        hit["evidence_uid"]=record.get("evidence_uid","")
        hit["command"]=record.get("command","")
    return hits
# ---------------------------------------------------------------- candidates
def _affected_value(hit):
    host=hit.get("host") or ""
    if hit.get("port") is None:return host
    return (host+":" if host else "port ")+str(hit["port"])+"/"+hit.get("proto","tcp")
def _profile_targets(profile_id):
    try:
        path=_target_profiles.profile_targets_json_path(profile_id or None)
        data=_doc_store.read_json(path,None)
        return [t for t in data if isinstance(t,dict)] if isinstance(data,list) else []
    except Exception:
        return []
def _match_target(targets,host):
    host=_norm(host).lower()
    if not host:return None
    for target in targets:
        if _norm(target.get("name")).lower()==host:return target
        values=target.get("values") if isinstance(target.get("values"),dict) else {}
        for value in values.values():
            text=_norm(value).lower()
            if text==host or re.sub(r"^https?://","",text).split("/")[0].split(":")[0]==host:return target
    return None
def _library_index():
    """[(title_lower,id)] of member A's finding library, or [] when the reports service is not available."""
    try:
        from Cores.Services import reports_service as _reports
        return _reports,[(_norm(entry.get("title")).lower(),entry.get("id")) for entry in _reports.library_list() if isinstance(entry,dict)]
    except Exception:
        return None,[]
def _library_match(reports,index,rule):
    for keyword in rule.get("lib",()):
        for title,entry_id in index:
            if keyword in title:
                try:
                    entry=reports.library_get(entry_id)
                    if isinstance(entry,dict):return entry
                except Exception:pass
    return None
def _para(text):return "<p>"+_esc(text)+"</p>" if text else ""
def build_candidates(records,profile_id=None,use_library=True):
    grouped={};order=[]
    for record in records:
        for hit in record_hits(record):
            rule_id=hit["rule"]
            key_text=rule_id+"|"+_norm(hit.get("variant") if rule_id in ("nmap-vuln","database","root-shell","sudo-nopasswd","sqli","wordpress-vulns") else "")
            key=rule_id+"-"+hashlib.sha1(key_text.encode("utf-8")).hexdigest()[:8]
            if key not in grouped:
                grouped[key]={"key":key,"rule":rule_id,"hits":[]}
                order.append(key)
            grouped[key]["hits"].append(hit)
    targets=_profile_targets(profile_id)
    reports,index=_library_index() if use_library else (None,[])
    out=[]
    for key in order:
        group=grouped[key];rule=RULES[group["rule"]];hits=group["hits"]
        severity=min((hit.get("severity") or rule["severity"] for hit in hits),key=lambda name:_SEV_RANK.get(name,9))
        confidence=min((hit["confidence"] for hit in hits),key=lambda name:_CONF_RANK.get(name,9))
        title=next((hit["title"] for hit in hits if hit.get("title")),rule["title"])
        if group["rule"]=="database" and hits[0].get("variant"):title=hits[0]["variant"]+" database service exposed to the network"
        affected=[];seen=set()
        for hit in hits:
            value=_affected_value(hit)
            if not value or value in seen:continue
            seen.add(value)
            target=_match_target(targets,hit.get("host"))
            affected.append({"target_id":_norm(target.get("id")) if target else "","name":_norm(target.get("name")) if target else (hit.get("host") or ""),"value":value})
        evidence_uids=[]
        for hit in hits:
            if hit.get("evidence_uid") and hit["evidence_uid"] not in evidence_uids:evidence_uids.append(hit["evidence_uid"])
        reasons=[]
        for hit in hits:
            text=(_affected_value(hit)+": " if len(affected)>1 and _affected_value(hit) else "")+hit["reason"]
            if text not in reasons:reasons.append(text)
        reason=" ".join(reasons[:4])+(" (+"+str(len(reasons)-4)+" more)" if len(reasons)>4 else "")
        refs=list(rule["references"])
        for hit in hits:
            for ref in hit.get("refs") or []:
                if ref not in refs:refs.append(ref)
        excerpt=[]
        for hit in hits:
            for line in hit.get("lines") or []:
                if line not in excerpt:excerpt.append(line)
        commands=[]
        for hit in hits:
            if hit.get("command") and hit["command"] not in commands:commands.append(hit["command"])
        steps="".join("<p>Command: <code>"+_esc(command[:300])+"</code></p>" for command in commands[:3])+("<p>Relevant output:</p><pre>"+_esc("\n".join(excerpt[:20]))+"</pre>" if excerpt else "")
        description=_para(rule["description"]);impact=_para(rule["impact"]);remediation=_para(rule["remediation"])
        cvss=rule["cvss_vector"];cwe=rule["cwe"];owasp=rule["owasp"]
        library_uid=""
        entry=_library_match(reports,index,rule) if reports else None
        if entry:
            library_uid=_norm(entry.get("uid"))
            description=(entry.get("description") or description)
            impact=entry.get("impact") or impact
            remediation=entry.get("remediation") or remediation
            cvss=cvss or _norm(entry.get("cvss_vector"));cwe=cwe or _norm(entry.get("cwe"));owasp=owasp or _norm(entry.get("owasp"))
            for ref in entry.get("references") or []:
                if ref not in refs:refs.append(ref)
        finding={"title":title,"severity":severity,"cvss_vector":cvss if severity==rule["severity"] else "","status":"open","cwe":cwe,"owasp":owasp,"references":refs,"affected":affected,"description":description,"impact":impact,"likelihood":"","steps":steps,"remediation":remediation,"evidence":[{"evidence_uid":uid,"asset_uid":"","caption":""} for uid in evidence_uids],"tags":["autogen","unconfirmed"],"retest_notes":"","source":{"kind":"autogen","ref":group["rule"]}}
        out.append({"key":key,"rule":group["rule"],"title":title,"severity":severity,"cvss_vector":finding["cvss_vector"],"confidence":confidence,"reason":reason,"affected":affected,"evidence_uids":evidence_uids,"library_uid":library_uid,"finding":finding})
    out.sort(key=lambda cand:(_SEV_RANK.get(cand["severity"],9),_CONF_RANK.get(cand["confidence"],9),cand["title"]))
    return out
# ---------------------------------------------------------------- preview / create
def _load_evidence(evidence_ids):
    items=[]
    for ident in evidence_ids if isinstance(evidence_ids,(list,tuple)) else []:
        try:items.append(_evidence.get(ident))
        except ValueError:continue
    return items
def _note_names(note_ids):
    out=[]
    ids=[]
    for note_id in note_ids if isinstance(note_ids,(list,tuple)) else []:
        try:ids.append(int(note_id))
        except Exception:continue
    if not ids:return out
    try:
        from Cores import common_db
        con=common_db.connect(timeout=5)
        try:
            common_db.ensure_schema(con)
            for note_id in ids:
                row=con.execute("SELECT id,note_name FROM Notes WHERE id=?",(note_id,)).fetchone()
                if row:out.append({"id":int(row[0]),"name":row[1] or ""})
        finally:
            con.close()
    except Exception as error:
        if error.__class__.__name__=="DatabaseLocked":raise
    return out
def preview(params):
    params=params if isinstance(params,dict) else {}
    items=_load_evidence(params.get("evidence_ids"))
    records=[]
    for item in items:records+=records_from_evidence(item)
    records.sort(key=lambda record:_ts_key(record["ts"]))
    timeline=build_timeline(records)
    return {"timeline":timeline,"commands":build_commands(timeline),"tools":build_tools(timeline),"hosts":build_hosts(records),"candidates":build_candidates(records,_norm(params.get("profile_id")) or None),"notes":_note_names(params.get("note_ids")),"evidence":[{"id":item["id"],"uid":item["uid"],"kind":item["kind"],"title":item["title"]} for item in items]}
def _table(headers,rows):
    head="".join("<th>"+_esc(text)+"</th>" for text in headers)
    body="".join("<tr>"+"".join("<td>"+cell+"</td>" for cell in row)+"</tr>" for row in rows)
    return "<table><thead><tr>"+head+"</tr></thead><tbody>"+body+"</tbody></table>"
def _when(ts):return _esc(ts[:19].replace("T"," ")) if ts else ""
def timeline_html(timeline):
    if not timeline:return "<p>No commands were captured.</p>"
    rows=[[_when(row["ts"]),_esc(row.get("session_label") or row.get("session_id") or ""),"<code>"+_esc(row["command"][:500])+"</code>",_esc("" if row["exit_code"] is None else row["exit_code"])] for row in timeline]
    return "<p>Commands in the order they were run. Times are UTC.</p>"+_table(("Time (UTC)","Session","Command","Exit code"),rows)
def commands_html(commands):
    if not commands:return "<p>No commands were captured.</p>"
    rows=[["<code>"+_esc(row["command"][:500])+"</code>",_esc(row["count"]),_when(row["first_ts"])] for row in commands]
    return "<p>Distinct commands run during the engagement, with the number of times each was run.</p>"+_table(("Command","Runs","First run (UTC)"),rows)
def tools_html(tools):
    if not tools:return "<p>No tools were captured.</p>"
    rows=[["<code>"+_esc(row["name"])+"</code>",_esc(row.get("purpose") or ""),_esc(row["count"])] for row in tools]
    return _table(("Tool","Purpose","Runs"),rows)
def hosts_html(hosts):
    if not hosts:return "<p>No hosts or services were identified in the captured output.</p>"
    parts=["<p>Hosts and services identified in the captured tool output.</p>"]
    for host in hosts:
        label=host["host"]+(" ("+", ".join(host["hostnames"])+")" if host.get("hostnames") else "")
        parts.append("<h4>"+_esc(label)+"</h4>")
        if host.get("os"):parts.append("<p>Operating system: "+_esc(host["os"])+"</p>")
        rows=[[_esc(str(port["port"])+"/"+port["proto"]+((" on "+port["address"]) if port.get("address") else "")),_esc(port["state"]),_esc(port["service"]),_esc(port["version"])] for port in host["ports"]]
        parts.append(_table(("Port","State","Service","Version"),rows) if rows else "<p>No ports recorded.</p>")
    return "".join(parts)
def _service_call(module,names,*args):
    for name in names:
        fn=getattr(module,name,None)
        if callable(fn):return fn(*args)
    raise AttributeError(names[0])
def _set_section(reports,report,kind,title,content,after_kind=None):
    """Fill the template's section of this kind, or add one when the template has none. Returns the section dict/id."""
    for section in report.get("sections") or []:
        if section.get("kind")==kind and kind!="custom":
            intro=section.get("content") or ""
            _service_call(reports,("section_update","update_section"),section["id"],{"content":intro+content,"hidden":False})
            return section
    payload={"kind":kind,"title":title,"content":content}
    if after_kind:
        anchor=next((section for section in report.get("sections") or [] if section.get("kind")==after_kind),None)
        if anchor:payload["after_id"]=anchor["id"]
    return _service_call(reports,("add_section","section_add"),report["id"],payload)
def create(params):
    params=params if isinstance(params,dict) else {}
    try:
        from Cores.Services import reports_service as reports
    except ImportError:
        raise ValueError("The report model is not available, so a report cannot be created.")
    data=preview(params)
    accepted=params.get("accepted")
    accepted=set(str(key) for key in accepted) if isinstance(accepted,(list,tuple)) else None
    overrides=params.get("overrides") if isinstance(params.get("overrides"),dict) else {}
    title=_norm(params.get("title")) or "Penetration test report (draft)"
    payload={"title":title}
    if _norm(params.get("template_id")):payload["template_id"]=_norm(params.get("template_id"))
    if _norm(params.get("profile_id")):payload["profile_id"]=_norm(params.get("profile_id"))
    report=_service_call(reports,("create_report","create"),payload)
    report_id=report["id"]
    sections=0
    if data["hosts"]:
        _set_section(reports,report,"custom","Discovered hosts and services",hosts_html(data["hosts"]),"scope");sections+=1
    for note in data["notes"]:
        try:
            content=reports.note_content(note["id"])
            body=content.get("html","") if isinstance(content,dict) else ""
            if body.strip():
                _service_call(reports,("add_section","section_add"),report_id,{"kind":"custom","title":"Notes: "+(content.get("name") or note["name"]),"content":body});sections+=1
        except Exception:
            continue
    if data["timeline"]:
        report=_service_call(reports,("get_report","get"),report_id)
        _set_section(reports,report,"appendix_tools","Appendix: Tools used",tools_html(data["tools"]))
        _set_section(reports,report,"appendix_commands","Appendix: Commands run",commands_html(data["commands"]))
        _set_section(reports,report,"appendix_timeline","Appendix: Activity timeline",timeline_html(data["timeline"]))
        sections+=3
    findings=0
    for candidate in data["candidates"]:
        if accepted is not None and candidate["key"] not in accepted:continue
        finding=dict(candidate["finding"])
        patch=overrides.get(candidate["key"]) if isinstance(overrides.get(candidate["key"]),dict) else {}
        if patch.get("severity") in SEVERITIES and patch["severity"]!=finding["severity"]:
            finding["severity"]=patch["severity"];finding["cvss_vector"]=""
        if _norm(patch.get("title")):finding["title"]=_norm(patch.get("title"))[:300]
        _service_call(reports,("add_finding","finding_add"),report_id,finding)
        findings+=1
    return {"report_id":report_id,"findings":findings,"sections":sections}
