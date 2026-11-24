import json,os,unittest
from _isolate import IsolatedData
from Cores.Services import evidence_service as evidence
from Cores.Services import report_autogen as autogen
NMAP_FULL="""Starting Nmap 7.94SVN ( https://nmap.org ) at 2026-11-23 10:12 UTC
Nmap scan report for web01.corp.example (10.0.0.5)
Host is up (0.00042s latency).
Not shown: 990 closed tcp ports (reset)
PORT     STATE    SERVICE     VERSION
21/tcp   open     ftp         vsftpd 2.3.4
|_ftp-anon: Anonymous FTP login allowed (FTP code 230)
22/tcp   open     ssh         OpenSSH 6.6.1p1 Ubuntu 2ubuntu2.13 (Ubuntu Linux; protocol 2.0)
| ssh-hostkey:
|   1024 60:0f:cf:e1:c0:5f:6a:74:d6:90:24:fa:c4:d5:6c:cd (DSA)
|_  2048 56:56:24:0f:21:1d:de:a7:2b:ae:61:b1:24:3d:e8:f3 (RSA)
23/tcp   open     telnet      Linux telnetd
80/tcp   open     http        Apache httpd 2.2.8 ((Ubuntu) DAV/2)
|_http-server-header: Apache/2.2.8 (Ubuntu) DAV/2
| http-methods:
|_  Potentially risky methods: TRACE
139/tcp  open     netbios-ssn Samba smbd 3.X - 4.X (workgroup: WORKGROUP)
443/tcp  open     ssl/http    Apache httpd 2.4.58
| ssl-enum-ciphers:
|   TLSv1.0:
|     ciphers:
|       TLS_RSA_WITH_3DES_EDE_CBC_SHA (rsa 2048) - C
|     warnings:
|       64-bit block cipher 3DES vulnerable to SWEET32 attack
|   TLSv1.2:
|     ciphers:
|       TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384 (secp256r1) - A
|_  least strength: C
445/tcp  open     netbios-ssn Samba smbd 3.0.20-Debian (workgroup: WORKGROUP)
3306/tcp open     mysql       MySQL 5.0.51a-3ubuntu5
5432/tcp filtered postgresql
5900/tcp open     vnc         VNC (protocol 3.3)
8009/tcp open     ajp13       Apache Jserv (Protocol v1.3)
OS details: Linux 2.6.9 - 2.6.33
Service Info: Hosts:  metasploitable.localdomain; OSs: Unix, Linux; CPE: cpe:/o:linux:linux_kernel

Host script results:
| smb-security-mode:
|   account_used: guest
|   authentication_level: user
|   challenge_response: supported
|_  message_signing: disabled (dangerous, but default)
| smb-vuln-ms17-010:
|   VULNERABLE:
|   Remote Code Execution vulnerability in Microsoft SMBv1 servers (ms17-010)
|     State: VULNERABLE
|     IDs:  CVE:CVE-2017-0143
|     Risk factor: HIGH
|_      https://technet.microsoft.com/en-us/library/security/ms17-010.aspx
|_smb-vuln-ms10-054: false

Nmap scan report for 10.0.0.9
Host is up (0.00051s latency).
PORT     STATE SERVICE       VERSION
3389/tcp open  ms-wbt-server Microsoft Terminal Services
161/udp  open  snmp          SNMPv1 server (public)
OS details: Microsoft Windows Server 2008 R2 SP1

Nmap done: 2 IP addresses (2 hosts up) scanned in 31.20 seconds
"""
NMAP_CLEAN="""Nmap scan report for 10.0.0.20
Host is up.
PORT    STATE  SERVICE  VERSION
22/tcp  open   ssh      OpenSSH 9.6p1 Ubuntu 3ubuntu13.5 (Ubuntu Linux; protocol 2.0)
443/tcp open   ssl/http nginx 1.24.0
| ssl-enum-ciphers:
|   TLSv1.3:
|     ciphers:
|       TLS_AKE_WITH_AES_256_GCM_SHA384 (ecdh_x25519) - A
|_  least strength: A
23/tcp  closed telnet
| smb-vuln-ms17-010:
|   State: NOT VULNERABLE
OS details: Microsoft Windows 7|2008|8.1
"""
SS_OUTPUT="""Netid State  Recv-Q Send-Q Local Address:Port  Peer Address:Port Process
tcp   LISTEN 0      128          0.0.0.0:22         0.0.0.0:*     users:(("sshd",pid=812,fd=3))
tcp   LISTEN 0      4096       127.0.0.1:5432       0.0.0.0:*     users:(("postgres",pid=1022,fd=5))
tcp   LISTEN 0      511             [::]:80            [::]:*     users:(("nginx",pid=934,fd=7),("nginx",pid=933,fd=7))
tcp   ESTAB  0      0         10.0.0.2:22        10.0.0.1:51234
udp   UNCONN 0      0            0.0.0.0:68         0.0.0.0:*
"""
SS_NO_NETID="""State   Recv-Q  Send-Q   Local Address:Port    Peer Address:Port
LISTEN  0       128            0.0.0.0:22           0.0.0.0:*
LISTEN  0       128               [::]:22              [::]:*
"""
NETSTAT_WINDOWS="""
Active Connections

  Proto  Local Address          Foreign Address        State
  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING
  TCP    0.0.0.0:445            0.0.0.0:0              LISTENING       4
  TCP    10.0.0.7:49712         52.1.2.3:443           ESTABLISHED
  TCP    [::]:3389              [::]:0                 LISTENING
  UDP    0.0.0.0:500            *:*
"""
NETSTAT_LINUX="""Active Internet connections (only servers)
Proto Recv-Q Send-Q Local Address           Foreign Address         State       PID/Program name
tcp        0      0 0.0.0.0:22              0.0.0.0:*               LISTEN      812/sshd
tcp6       0      0 :::80                   :::*                    LISTEN      934/nginx
tcp        0      0 10.0.0.2:22             10.0.0.1:51234          ESTABLISHED 4411/sshd
udp        0      0 0.0.0.0:68              0.0.0.0:*                           700/dhclient
"""
def rec(command,output,target="",uid="ev1"):
    return {"ts":"2026-11-23T10:00:00+00:00","command":command,"output":output,"exit_code":0,"evidence_uid":uid,"session_id":"s1","target":target,"session_label":"","duration":None}
def rules(command,output,target=""):
    return sorted(set(hit["rule"] for hit in autogen.record_hits(rec(command,output,target))))
class NmapParserTests(unittest.TestCase):
    def test_hosts_names_ports_versions_and_os(self):
        hosts=autogen.parse_nmap(NMAP_FULL)
        self.assertEqual(["10.0.0.5","10.0.0.9"],[host["host"] for host in hosts])
        first=hosts[0]
        self.assertEqual(["web01.corp.example"],first["hostnames"])
        self.assertEqual("Linux 2.6.9 - 2.6.33",first["os"])
        self.assertEqual(11,len(first["ports"]))
        ssh=first["ports"][1]
        self.assertEqual((22,"tcp","open","ssh"),(ssh["port"],ssh["proto"],ssh["state"],ssh["service"]))
        self.assertTrue(ssh["version"].startswith("OpenSSH 6.6.1p1 Ubuntu"))
        self.assertEqual("filtered",[p for p in first["ports"] if p["port"]==5432][0]["state"])
        self.assertEqual("ssl/http",[p for p in first["ports"] if p["port"]==443][0]["service"])
        udp=hosts[1]["ports"][1]
        self.assertEqual((161,"udp"),(udp["port"],udp["proto"]))
        self.assertEqual("Microsoft Windows Server 2008 R2 SP1",hosts[1]["os"])
    def test_port_and_host_scripts_are_attached(self):
        first=autogen.parse_nmap(NMAP_FULL)[0]
        self.assertEqual(["ftp-anon"],[s["id"] for s in first["ports"][0]["scripts"]])
        hostkey=first["ports"][1]["scripts"][0]
        self.assertEqual("ssh-hostkey",hostkey["id"]);self.assertIn("2048 56:56",hostkey["output"])
        self.assertEqual(["smb-security-mode","smb-vuln-ms17-010","smb-vuln-ms10-054"],[s["id"] for s in first["scripts"]])
        self.assertIn("State: VULNERABLE",first["scripts"][1]["output"])
        self.assertNotIn("port",first["scripts"][0])
    def test_ports_without_a_report_line_and_empty_input(self):
        hosts=autogen.parse_nmap("PORT   STATE SERVICE\n80/tcp open  http\n")
        self.assertEqual(1,len(hosts));self.assertEqual("",hosts[0]["host"]);self.assertEqual(80,hosts[0]["ports"][0]["port"])
        self.assertEqual([],autogen.parse_nmap(""))
        self.assertEqual([],autogen.parse_nmap("total 4\ndrwxr-xr-x 2 kali kali 4096 Nov 23 10:00 loot\n"))
    def test_aggressive_guess_is_marked_as_a_guess(self):
        hosts=autogen.parse_nmap("Nmap scan report for 10.1.1.1\n80/tcp open http\nAggressive OS guesses: Linux 5.4 (96%), Linux 4.15 (93%)\n")
        self.assertEqual("Linux 5.4 (guess)",hosts[0]["os"])
class ListenerParserTests(unittest.TestCase):
    def test_ss_listeners_with_process_names(self):
        rows=autogen.parse_ss(SS_OUTPUT)
        self.assertEqual([("tcp","0.0.0.0",22,"sshd","812"),("tcp","127.0.0.1",5432,"postgres","1022"),("tcp","[::]",80,"nginx","934"),("udp","0.0.0.0",68,"","")],[(r["proto"],r["address"],r["port"],r["process"],r["pid"]) for r in rows])
    def test_ss_without_the_netid_column(self):
        self.assertEqual([("tcp","0.0.0.0",22),("tcp","[::]",22)],[(r["proto"],r["address"],r["port"]) for r in autogen.parse_ss(SS_NO_NETID)])
    def test_netstat_windows_keeps_only_listeners(self):
        rows=autogen.parse_netstat(NETSTAT_WINDOWS)
        self.assertEqual([("tcp","0.0.0.0",135,""),("tcp","0.0.0.0",445,"4"),("tcp","[::]",3389,""),("udp","0.0.0.0",500,"")],[(r["proto"],r["address"],r["port"],r["pid"]) for r in rows])
    def test_netstat_linux_keeps_only_listeners(self):
        rows=autogen.parse_netstat(NETSTAT_LINUX)
        self.assertEqual([("tcp","0.0.0.0",22,"sshd"),("tcp","::",80,"nginx"),("udp","0.0.0.0",68,"dhclient")],[(r["proto"],r["address"],r["port"],r["process"]) for r in rows])
    def test_non_listener_text_yields_nothing(self):
        self.assertEqual([],autogen.parse_listeners("uid=1000(kali) gid=1000(kali)\n"))
        self.assertEqual([],autogen.parse_listeners(NMAP_FULL))
class ToolNameTests(unittest.TestCase):
    def test_wrappers_paths_and_assignments_are_stripped(self):
        cases={"nmap -sV 10.0.0.5":"nmap","sudo nmap -sS 10.0.0.5":"nmap","sudo -u postgres psql":"psql","sudo -E /usr/bin/nmap -p- x":"nmap","HTTP_PROXY=http://x proxychains -q curl http://y":"curl","time ./linpeas.sh":"linpeas","timeout 30 nc -nv 10.0.0.5 21":"nc","C:\\Tools\\Rubeus.exe kerberoast":"rubeus","python3 sqlmap.py -u x":"python3","":"","   ":"","sudo":""}
        for command,expected in cases.items():self.assertEqual(expected,autogen.tool_name(command),command)
class CommandTargetTests(unittest.TestCase):
    def test_url_ip_hostname_and_fallback(self):
        self.assertEqual(("shop.example.com",443),autogen.command_target("sqlmap -u 'https://shop.example.com/item?id=1' --batch"))
        self.assertEqual(("10.0.0.5",8080),autogen.command_target("nikto -h http://10.0.0.5:8080/"))
        self.assertEqual(("10.0.0.5",None),autogen.command_target("hydra -L users.txt -P pass.txt ssh://10.0.0.5")[:1]+(None,))
        self.assertEqual(("10.0.0.5",21),autogen.command_target("nc 10.0.0.5:21"))
        self.assertEqual(("dc01.corp.local",None),autogen.command_target("smbclient -L dc01.corp.local -N"))
        self.assertEqual(("fallback",None),autogen.command_target("cat users.txt wordlist.lst","fallback"))
class RecogniserTests(unittest.TestCase):
    """Each recogniser against a positive and a negative sample."""
    def test_full_nmap_scan_raises_the_expected_candidates(self):
        found=rules("nmap -sV -sC 10.0.0.5 10.0.0.9",NMAP_FULL)
        for rule in ("telnet","ftp","ftp-anon","vnc","rdp","smb","snmp","database","ajp","http-plain","vsftpd-backdoor","outdated-openssh","apache-eol","samba-usermap","mysql-old","weak-tls","smb-signing","ms17-010","http-methods","os-eol"):self.assertIn(rule,found)
        self.assertNotIn("nmap-vuln",found)
    def test_hardened_host_raises_nothing(self):
        self.assertEqual([],rules("nmap -sV -sC 10.0.0.20",NMAP_CLEAN))
    def test_exposure_ignores_closed_filtered_and_tcpwrapped_ports(self):
        text="Nmap scan report for 10.0.0.1\n23/tcp closed telnet\n21/tcp filtered ftp\n3306/tcp open tcpwrapped\n"
        self.assertEqual([],rules("nmap 10.0.0.1",text))
    def test_exposure_by_port_number_alone_is_low_confidence(self):
        hits=autogen.record_hits(rec("nmap -sS 10.0.0.1","Nmap scan report for 10.0.0.1\n23/tcp open unknown\n"))
        self.assertEqual([("telnet","low")],[(hit["rule"],hit["confidence"]) for hit in hits])
        named=autogen.record_hits(rec("nmap -sS 10.0.0.1","Nmap scan report for 10.0.0.1\n23/tcp open telnet\n"))
        self.assertEqual("high",named[0]["confidence"])
    def test_http_plain_only_without_tls(self):
        self.assertEqual(["http-plain"],rules("nmap x","Nmap scan report for 10.0.0.1\n8080/tcp open http-proxy\n"))
        self.assertEqual([],rules("nmap x","Nmap scan report for 10.0.0.1\n443/tcp open ssl/http nginx 1.24.0\n8443/tcp open https-alt\n"))
    def version_rules(self,text):
        return sorted(hit["rule"] for hit in autogen.version_hits("h",1,"tcp",text))
    def test_version_strings(self):
        positive={"OpenSSH 7.2p2 Ubuntu 4ubuntu2.8":"outdated-openssh","Apache httpd 2.4.49 ((Unix))":"apache-traversal","Apache/2.4.50 (Unix)":"apache-traversal","Apache httpd 2.2.22 ((Debian))":"apache-eol","Apache httpd 2.4.29 ((Ubuntu))":"apache-old","vsftpd 2.3.4":"vsftpd-backdoor","ProFTPD 1.3.3c":"proftpd-backdoor","ProFTPD 1.3.5":"proftpd-modcopy","UnrealIRCd 3.2.8.1":"unrealircd-backdoor","Samba smbd 3.0.20-Debian":"samba-usermap","Samba 4.3.11-Ubuntu":"samba-old","Microsoft IIS httpd 6.0":"iis-eol","Microsoft-IIS/7.5":"iis-eol","nginx 1.14.0 (Ubuntu)":"nginx-old","Apache/2.4.58 (Unix) PHP/5.6.40":"php-eol","MySQL 5.5.62-0ubuntu0.14.04.1":"mysql-old","Exim smtpd 4.89":"exim-old","Apache Tomcat 7.0.88":"tomcat-eol","Apache/2.4.58 (Unix) OpenSSL/1.0.1e-fips":"openssl-heartbleed","Apache/2.4.58 OpenSSL/1.0.2k":"openssl-old"}
        for text,rule in positive.items():self.assertIn(rule,self.version_rules(text),text)
    def test_current_versions_raise_nothing(self):
        for text in ("OpenSSH 9.6p1 Ubuntu 3ubuntu13.5","OpenSSH 8.0","Apache httpd 2.4.62 ((Debian))","vsftpd 3.0.5","ProFTPD 1.3.8b","ProFTPD 1.3.5e","Samba smbd 4.19.5","Microsoft IIS httpd 10.0","nginx 1.24.0","nginx","PHP/8.3.1","MySQL 8.0.36","10.11.6-MariaDB","Exim smtpd 4.97","Apache Tomcat 10.1.19","Apache Tomcat/Coyote JSP engine 1.1","OpenSSL/3.0.13","OpenSSL/1.1.1w","Apache Jserv (Protocol v1.3)","Dropbear sshd 2022.83",""):
            self.assertEqual([],self.version_rules(text),text)
    def test_openssh_severity_depends_on_age(self):
        self.assertEqual("medium",autogen.version_hits("h",22,"tcp","OpenSSH 5.3")[0]["severity"])
        self.assertEqual("low",autogen.version_hits("h",22,"tcp","OpenSSH 7.9p1")[0]["severity"])
    def script(self,sid,output):
        return sorted(hit["rule"] for hit in autogen.script_hits("h",{"id":sid,"output":output,"port":445,"proto":"tcp"}))
    def test_nmap_scripts_positive(self):
        vuln="\n  VULNERABLE:\n  Some Service remote overflow\n    State: VULNERABLE\n    IDs:  CVE:CVE-2012-0002\n    Risk factor: MEDIUM"
        cases=[("smb-vuln-ms17-010","\n  VULNERABLE:\n  RCE (ms17-010)\n    State: VULNERABLE\n    IDs:  CVE:CVE-2017-0143","ms17-010"),("smb-vuln-ms08-067","\n  VULNERABLE:\n  x\n    State: LIKELY VULNERABLE","ms08-067"),("rdp-vuln-ms12-020",vuln,"nmap-vuln"),("http-vuln-cve2017-5638",vuln,"nmap-vuln"),("ssl-heartbleed","\n  VULNERABLE:\n  The Heartbleed Bug\n    State: VULNERABLE","openssl-heartbleed"),("ssl-enum-ciphers","\n  SSLv3: \n    ciphers: \n      TLS_RSA_WITH_RC4_128_SHA (rsa 2048) - C\n  least strength: C","weak-tls"),("ssl-enum-ciphers","\n  TLSv1.2: \n    ciphers: \n      TLS_RSA_WITH_3DES_EDE_CBC_SHA (rsa 2048) - C\n    warnings: \n      64-bit block cipher 3DES vulnerable to SWEET32 attack\n  least strength: C","weak-tls"),("ssl-cert","Subject: commonName=x\nNot valid before: 2019-01-01T00:00:00\nNot valid after:  2020-01-01T00:00:00","cert-expired"),("smb-security-mode","\n  message_signing: disabled (dangerous, but default)","smb-signing"),("smb2-security-mode","\n  3:1:1: \n    Message signing enabled but not required","smb-signing"),("smb-protocols","\n  dialects: \n    NT LM 0.12 (SMBv1) [dangerous, but default]\n    2:0:2","smbv1"),("smb-os-discovery","\n  OS: Windows 7 Professional 7601 Service Pack 1 (Windows 7 Professional 6.1)\n  Computer name: WS01","os-eol"),("ftp-anon","Anonymous FTP login allowed (FTP code 230)","ftp-anon"),("http-methods","\n  Supported Methods: GET HEAD POST PUT DELETE OPTIONS\n  Potentially risky methods: PUT DELETE","http-methods"),("http-git","\n  10.0.0.5:80/.git/\n    Git repository found!","git-exposed"),("vnc-info","\n  Protocol version: 3.8\n  Security types: \n    None (1)","vnc-noauth"),("mysql-empty-password","\n  root account has empty password","db-noauth"),("redis-info","\n  Version: 6.0.9\n  Role: master","redis-noauth"),("snmp-sysdescr","Linux fw01 5.10.0","snmp-public"),("nfs-showmount","\n  /srv/share *","nfs-export"),("http-server-header","Apache/2.2.14 (Ubuntu)","apache-eol")]
        for sid,output,rule in cases:self.assertEqual([rule],self.script(sid,output),sid)
    def test_nmap_scripts_negative(self):
        cases=[("smb-vuln-ms17-010","\n  State: NOT VULNERABLE"),("smb-vuln-ms10-054","false"),("smb-vuln-ms10-061","Could not negotiate a connection:SMB: Failed to receive bytes: ERROR"),("http-vuln-cve2017-5638","ERROR: Script execution failed (use -d to debug)"),("ssl-heartbleed","\n  State: NOT VULNERABLE"),("ssl-enum-ciphers","\n  TLSv1.2: \n    ciphers: \n      TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384 (secp256r1) - A\n  TLSv1.3: \n    ciphers: \n      TLS_AKE_WITH_AES_256_GCM_SHA384 (ecdh_x25519) - A\n  least strength: A"),("ssl-cert","Subject: commonName=x\nNot valid after:  2999-01-01T00:00:00"),("smb-security-mode","\n  message_signing: required"),("smb2-security-mode","\n  3:1:1: \n    Message signing enabled and required"),("smb-protocols","\n  dialects: \n    2:0:2\n    3:1:1"),("smb-os-discovery","\n  OS: Windows Server 2022 Standard 20348"),("ftp-anon","got code 530 \"Login incorrect.\""),("http-methods","\n  Supported Methods: GET HEAD POST OPTIONS"),("http-git","nothing here"),("vnc-info","\n  Protocol version: 3.8\n  Security types: \n    VNC Authentication (2)\n    Tight (16)"),("mysql-empty-password","Host '10.0.0.1' is not allowed to connect"),("redis-info","ERROR: NOAUTH Authentication required"),("snmp-sysdescr",""),("nfs-showmount","\n  /srv/share 10.0.0.0/24"),("http-server-header","Apache/2.4.62 (Debian)"),("http-title","Site doesn't have a title (text/html)."),("ssh-hostkey","\n  256 aa:bb (ED25519)")]
        for sid,output in cases:self.assertEqual([],self.script(sid,output),sid)
    def test_generic_vuln_script_takes_title_severity_and_cves_from_the_output(self):
        hit=autogen.script_hits("h",{"id":"rdp-vuln-ms12-020","output":"\n  VULNERABLE:\n  MS12-020 Remote Desktop Protocol Denial Of Service Vulnerability\n    State: VULNERABLE\n    IDs:  CVE:CVE-2012-0152\n    Risk factor: Medium","port":3389,"proto":"tcp"})[0]
        self.assertEqual("MS12-020 Remote Desktop Protocol Denial Of Service Vulnerability",hit["title"])
        self.assertEqual("medium",hit["severity"]);self.assertEqual(["CVE-2012-0152"],hit["refs"]);self.assertEqual("high",hit["confidence"])
    def test_os_end_of_life(self):
        self.assertEqual(1,len(autogen.os_hits("h","Microsoft Windows XP SP3","low")))
        self.assertEqual(1,len(autogen.os_hits("h","Windows Server 2003 3790 Service Pack 2","medium")))
        for text in ("Microsoft Windows 7|2008|8.1","Microsoft Windows 10 1809","Microsoft Windows Server 2019","Linux 5.4","Microsoft Windows Server 2008 R2 or Windows 8, Microsoft Windows 7",""):self.assertEqual([],autogen.os_hits("h",text,"low"),text)
    def test_hydra_medusa_and_netexec_logins(self):
        hydra="Hydra v9.5 (c) 2023 by van Hauser/THC\n[DATA] attacking ssh://10.0.0.5:22/\n[22][ssh] host: 10.0.0.5   login: admin   password: [redacted]\n1 of 1 target successfully completed, 1 valid password found\n"
        hits=autogen.record_hits(rec("hydra -l admin -P rockyou.txt ssh://10.0.0.5",hydra))
        self.assertEqual([("default-creds","10.0.0.5",22,"high")],[(h["rule"],h["host"],h["port"],h["confidence"]) for h in hits])
        self.assertEqual(["default-creds"],rules("hydra x","[21][ftp] host: 10.0.0.5   login: ftp   password: ftp\n"))
        self.assertEqual(["default-creds"],rules("hydra x","[6379][redis] host: 10.0.0.5   password: redis123\n"))
        self.assertEqual(["default-creds"],rules("medusa -h 10.0.0.5 -u root -P p.txt -M ssh","ACCOUNT FOUND: [ssh] Host: 10.0.0.5 User: root Password: toor [SUCCESS]\n"))
        self.assertEqual(["default-creds"],rules("nxc smb 10.0.0.5 -u administrator -p x","SMB         10.0.0.5        445    DC01             [+] corp.local\\administrator:Passw0rd! (Pwn3d!)\n"))
    def test_failed_password_guessing_raises_nothing(self):
        self.assertEqual([],rules("hydra -l admin -P rockyou.txt ssh://10.0.0.5","Hydra v9.5\n[DATA] attacking ssh://10.0.0.5:22/\n[STATUS] 64.00 tries/min\n1 of 1 target completed, 0 valid password found\n"))
        self.assertEqual([],rules("medusa -h 10.0.0.5 -u root -P p.txt -M ssh","ACCOUNT CHECK: [ssh] Host: 10.0.0.5 (1 of 1, 0 complete) User: root (1 of 1, 0 complete) Password: toor (1 of 3 complete)\n"))
        self.assertEqual([],rules("nxc smb 10.0.0.5 -u bob -p x","SMB         10.0.0.5        445    DC01             [+] corp.local\\bob:Passw0rd!\nSMB         10.0.0.5        445    DC01             [-] corp.local\\administrator:x STATUS_LOGON_FAILURE\n"))
    def test_sqlmap_confirmed_injection(self):
        output="[10:20:01] [INFO] GET parameter 'id' appears to be 'AND boolean-based blind - WHERE or HAVING clause' injectable\nGET parameter 'id' is vulnerable. Do you want to keep testing the others (if any)? [y/N] N\nsqlmap identified the following injection point(s) with a total of 46 HTTP(s) requests:\n---\nParameter: id (GET)\n    Type: boolean-based blind\n    Title: AND boolean-based blind - WHERE or HAVING clause\n    Payload: id=1 AND 5234=5234\n\n    Type: time-based blind\n    Title: MySQL >= 5.0.12 AND time-based blind\n    Payload: id=1 AND SLEEP(5)\n---\n[10:20:09] [INFO] the back-end DBMS is MySQL\n"
        hits=autogen.record_hits(rec("sqlmap -u 'http://shop.example.com/item.php?id=1' --batch",output))
        self.assertEqual(1,len(hits))
        self.assertEqual(("sqli","shop.example.com",80,"high"),(hits[0]["rule"],hits[0]["host"],hits[0]["port"],hits[0]["confidence"]))
        self.assertIn("id (GET)",hits[0]["reason"]);self.assertIn("boolean-based blind",hits[0]["reason"])
    def test_sqlmap_without_injection_raises_nothing(self):
        output="[10:20:01] [WARNING] GET parameter 'id' does not seem to be injectable\n[10:20:01] [CRITICAL] all tested parameters do not appear to be injectable. Try to increase values for '--level'/'--risk' options\n"
        self.assertEqual([],rules("sqlmap -u 'http://shop.example.com/item.php?id=1' --batch",output))
        self.assertEqual([],rules("sqlmap -u http://x/?id=1","[INFO] heuristic (basic) test shows that GET parameter 'id' might be injectable (possible DBMS: 'MySQL')\n"))
        self.assertEqual([],rules("cat notes.txt","the login form is vulnerable I think\n"))
    def test_nikto_findings(self):
        output="- Nikto v2.5.0\n+ Target IP:          10.0.0.5\n+ Target Hostname:    10.0.0.5\n+ Target Port:        8080\n+ Server: Apache/2.4.7 (Ubuntu)\n+ /: The anti-clickjacking X-Frame-Options header is not present. See: https://developer.mozilla.org/\n+ /: The X-Content-Type-Options header is not set.\n+ Apache/2.4.7 appears to be outdated (current is at least Apache/2.4.54).\n+ OPTIONS: Allowed HTTP Methods: GET, HEAD, POST, PUT, DELETE, OPTIONS .\n+ /icons/: Directory indexing found.\n+ /phpinfo.php: Output from the phpinfo() function was found.\n+ /.git/HEAD: Git HEAD file found. Full repo details may be present.\n+ /phpmyadmin/: phpMyAdmin directory found.\n+ 8102 requests: 0 error(s) and 9 item(s) reported on remote host\n"
        hits=autogen.record_hits(rec("nikto -h http://10.0.0.5:8080",output))
        self.assertEqual({"security-headers","nikto-outdated","http-methods","dir-listing","info-page","git-exposed","admin-exposed"},set(h["rule"] for h in hits))
        self.assertTrue(all(h["host"]=="10.0.0.5" and h["port"]==8080 for h in hits))
    def test_nikto_clean_scan_and_non_nikto_text(self):
        output="- Nikto v2.5.0\n+ Target IP:          10.0.0.5\n+ Target Port:        443\n+ Server: nginx\n+ Start Time:         2026-11-23 10:00:00 (GMT0)\n+ 8102 requests: 0 error(s) and 0 item(s) reported on remote host\n+ End Time:           2026-11-23 10:05:00 (GMT0) (300 seconds)\n"
        self.assertEqual([],rules("nikto -h https://10.0.0.5",output))
        self.assertEqual([],rules("git diff","+ /icons/: Directory indexing found.\n+ backup of the admin page\n"))
    def test_content_discovery_findings(self):
        gobuster="===============================================================\nGobuster v3.6\n===============================================================\n/.git/HEAD            (Status: 200) [Size: 23]\n/.env                 (Status: 200) [Size: 512]\n/backup.zip           (Status: 200) [Size: 104857]\n/admin                (Status: 301) [Size: 312] [--> http://10.0.0.5/admin/]\n/server-status        (Status: 200) [Size: 4096]\n/index.php            (Status: 200) [Size: 1024]\n"
        self.assertEqual(["admin-exposed","backup-exposed","env-exposed","git-exposed","info-page"],rules("gobuster dir -u http://10.0.0.5 -w common.txt",gobuster))
        ffuf=".git/config             [Status: 200, Size: 92, Words: 9, Lines: 6, Duration: 3ms]\nphpmyadmin              [Status: 401, Size: 0, Words: 1, Lines: 1, Duration: 2ms]\n"
        self.assertEqual(["admin-exposed","git-exposed"],rules("ffuf -u http://10.0.0.5/FUZZ -w common.txt",ffuf))
        self.assertEqual(["info-page"],rules("dirb http://10.0.0.5","-----------------\nDIRB v2.22\n+ http://10.0.0.5/phpinfo.php (CODE:200|SIZE:80123)\n"))
        self.assertEqual(["backup-exposed"],rules("feroxbuster -u http://10.0.0.5","200      GET       12l       34w      560c http://10.0.0.5/db.sql\n"))
    def test_content_discovery_negatives(self):
        gobuster="Gobuster v3.6\n/.git/HEAD            (Status: 403) [Size: 23]\n/.env                 (Status: 404) [Size: 0]\n/backup.zip           (Status: 403) [Size: 0]\n/server-status        (Status: 403) [Size: 277]\n/admin                (Status: 404) [Size: 0]\n/index.html           (Status: 200) [Size: 1024]\n/images               (Status: 301) [Size: 312]\n/administration-guide.pdf (Status: 200) [Size: 9]\n"
        self.assertEqual([],rules("gobuster dir -u http://10.0.0.5 -w common.txt",gobuster))
        self.assertEqual([],rules("ls -la","/admin (Status: 200)\n".replace("(Status: 200)","200")))
    def test_root_identity_from_a_target_shell(self):
        hits=autogen.record_hits(rec("id","uid=0(root) gid=0(root) groups=0(root)\n","dc01"))
        self.assertEqual([("root-shell","low","dc01")],[(h["rule"],h["confidence"],h["host"]) for h in hits])
        self.assertEqual(["root-shell"],rules("whoami","nt authority\\system\n"))
        self.assertEqual(["root-shell"],rules("python3 exploit.py 10.0.0.5; id","[*] sending payload\nuid=0(root) gid=0(root)\n"))
    def test_identity_negatives(self):
        self.assertEqual([],rules("id","uid=1000(kali) gid=1000(kali) groups=1000(kali),27(sudo)\n"))
        self.assertEqual([],rules("sudo id","uid=0(root) gid=0(root) groups=0(root)\n"))
        self.assertEqual([],rules("whoami","corp\\bob\n"))
        self.assertEqual([],rules("grep root /etc/passwd","root:x:0:0:root:/root:/bin/bash\n"))
        self.assertEqual([],rules("cat writeup.md","then run id and you get uid=0(root) gid=0(root)\n"))
    def test_sudo_nopasswd(self):
        full="Matching Defaults entries for www-data on web01:\n    env_reset, mail_badpass\n\nUser www-data may run the following commands on web01:\n    (ALL : ALL) NOPASSWD: ALL\n"
        hits=autogen.record_hits(rec("sudo -l",full,"web01"))
        self.assertEqual([("sudo-nopasswd","high","high")],[(h["rule"],h["severity"],h["confidence"]) for h in hits])
        partial="User bob may run the following commands on web01:\n    (root) NOPASSWD: /usr/bin/vim, /usr/bin/less\n"
        self.assertEqual("medium",autogen.record_hits(rec("sudo -l",partial))[0]["severity"])
    def test_sudo_negatives(self):
        self.assertEqual([],rules("sudo -l","User kali may run the following commands on kali:\n    (ALL : ALL) ALL\n"))
        self.assertEqual([],rules("sudo -l","Sorry, user www-data may not run sudo on web01.\n"))
        self.assertEqual([],rules("cat /etc/motd","Remember: never add NOPASSWD: ALL to sudoers\n"))
    def test_anonymous_ftp_from_a_client_session(self):
        session="Connected to 10.0.0.5.\n220 (vsFTPd 3.0.3)\nName (10.0.0.5:kali): anonymous\n331 Please specify the password.\nPassword:\n230 Login successful.\nRemote system type is UNIX.\n"
        hits=autogen.record_hits(rec("ftp 10.0.0.5",session))
        self.assertEqual([("ftp-anon","10.0.0.5",21)],[(h["rule"],h["host"],h["port"]) for h in hits])
        self.assertEqual([],rules("ftp 10.0.0.5","220 (vsFTPd 3.0.3)\nName (10.0.0.5:kali): anonymous\n331 Please specify the password.\n530 Login incorrect.\n"))
        self.assertEqual([],rules("ftp 10.0.0.5","220 (vsFTPd 3.0.3)\nName (10.0.0.5:kali): bob\n331 Please specify the password.\n230 Login successful.\n"))
    def test_smb_null_session(self):
        self.assertEqual(["smb-null"],rules("smbclient -L //10.0.0.5 -N","Anonymous login successful\n\n\tSharename       Type      Comment\n\tIPC$            IPC       IPC Service\n"))
        self.assertEqual(["smb-null"],rules("enum4linux -a 10.0.0.5","[+] Server 10.0.0.5 allows sessions using username '', password ''\n"))
        self.assertEqual([],rules("smbclient -L //10.0.0.5 -N","session setup failed: NT_STATUS_ACCESS_DENIED\n"))
        self.assertEqual([],rules("enum4linux -a 10.0.0.5","[E] Server doesn't allow session using username '', password ''.  Aborting remainder of tests.\n"))
    def test_nfs_exports(self):
        self.assertEqual(["nfs-export"],rules("showmount -e 10.0.0.5","Export list for 10.0.0.5:\n/srv/nfs *\n/home    10.0.0.0/24\n"))
        self.assertEqual([],rules("showmount -e 10.0.0.5","Export list for 10.0.0.5:\n/home    10.0.0.0/24\n"))
    def test_snmp_default_community(self):
        hits=autogen.record_hits(rec("onesixtyone -c communities.txt 10.0.0.9","Scanning 1 hosts, 3 communities\n10.0.0.9 [public] Linux fw01 5.10.0-21-amd64\n"))
        self.assertEqual([("snmp-public","10.0.0.9",161,"udp")],[(h["rule"],h["host"],h["port"],h["proto"]) for h in hits])
        self.assertEqual(["snmp-public"],rules("snmpwalk -v2c -c public 10.0.0.9","iso.3.6.1.2.1.1.1.0 = STRING: \"Linux fw01\"\n"))
        self.assertEqual([],rules("snmpwalk -v2c -c public 10.0.0.9","Timeout: No Response from 10.0.0.9\n"))
        self.assertEqual([],rules("snmpwalk -v3 -u admin -l authPriv 10.0.0.9","iso.3.6.1.2.1.1.1.0 = STRING: \"Linux fw01\"\n"))
        self.assertEqual([],rules("onesixtyone -c communities.txt 10.0.0.9","Scanning 1 hosts, 3 communities\n"))
    def test_tls_scanners(self):
        self.assertEqual(["weak-tls"],rules("sslscan 10.0.0.5","  SSL/TLS Protocols:\nSSLv2     disabled\nSSLv3     enabled\nTLSv1.0   enabled\nTLSv1.2   enabled\n"))
        self.assertEqual(["weak-tls"],rules("testssl.sh 10.0.0.5"," SSLv3      offered (NOT ok)\n TLS 1      offered (deprecated)\n TLS 1.2    offered (OK)\n"))
        self.assertEqual([],rules("sslscan 10.0.0.5","SSLv2     disabled\nSSLv3     disabled\nTLSv1.0   disabled\nTLSv1.1   disabled\nTLSv1.2   enabled\nTLSv1.3   enabled\n"))
        self.assertEqual([],rules("testssl.sh 10.0.0.5"," SSLv3      not offered (OK)\n TLS 1      not offered\n TLS 1.2    offered (OK)\n"))
    def test_kerberos_roasting_and_poisoning(self):
        self.assertEqual(["kerberoast"],rules("impacket-GetUserSPNs corp.local/bob -request","$krb5tgs$23$*svc_sql$CORP.LOCAL$corp.local/svc_sql*$a1b2c3$d4e5f6\n"))
        self.assertEqual(["asreproast"],rules("impacket-GetNPUsers corp.local/ -usersfile u.txt","$krb5asrep$23$alice@CORP.LOCAL:a1b2c3$d4e5\n"))
        self.assertEqual([],rules("impacket-GetUserSPNs corp.local/bob","No entries found!\n"))
        self.assertEqual(["llmnr"],rules("sudo responder -I eth0","[*] [LLMNR]  Poisoned answer sent to 10.0.0.7 for name fileserver\n[SMB] NTLMv2-SSP Client   : 10.0.0.7\n[SMB] NTLMv2-SSP Username : CORP\\alice\n[SMB] NTLMv2-SSP Hash     : alice::CORP:11223344\n"))
        self.assertEqual([],rules("sudo responder -I eth0","[+] Listening for events...\n"))
    def test_wpscan_vulnerabilities(self):
        self.assertEqual(["wordpress-vulns"],rules("wpscan --url http://blog.example.com"," | [!] 2 vulnerabilities identified:\n | [!] Title: Contact Form 7 < 5.3.2 - Unrestricted File Upload\n |     Fixed in: 5.3.2\n | [!] Title: WordPress < 5.8.3 - SQL Injection\n"))
        self.assertEqual([],rules("wpscan --url http://blog.example.com","[+] WordPress version 6.4.3 identified (Latest, released on 2024-01-30).\n[i] No plugins Found.\n"))
    def test_empty_output_raises_nothing(self):
        self.assertEqual([],autogen.record_hits(rec("nmap 10.0.0.5","")))
        self.assertEqual([],autogen.record_hits(rec("","   \n")))
class RulesTableTests(unittest.TestCase):
    def test_every_rule_is_complete_and_uses_a_valid_severity_and_vector(self):
        for name,rule in autogen.RULES.items():
            for key in ("title","description","impact","remediation"):self.assertTrue(rule[key].strip(),name+"."+key)
            self.assertIn(rule["severity"],autogen.SEVERITIES,name)
            if rule["cvss_vector"]:self.assertRegex(rule["cvss_vector"],r"^CVSS:3\.1/AV:[NALP]/AC:[LH]/PR:[NLH]/UI:[NR]/S:[UC]/C:[NLH]/I:[NLH]/A:[NLH]$",name)
class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.isolated=IsolatedData();self.data_dir=self.isolated.start()
    def tearDown(self):
        self.isolated.stop()
    def test_same_rule_on_several_hosts_is_one_candidate_with_all_affected_assets(self):
        text="Nmap scan report for 10.0.0.5\n23/tcp open telnet\nNmap scan report for 10.0.0.6\n23/tcp open telnet\n2323/tcp open telnet\n"
        cands=autogen.build_candidates([rec("nmap 10.0.0.0/24",text,uid="ev1"),rec("nmap 10.0.0.5",text,uid="ev2")],use_library=False)
        self.assertEqual(1,len(cands))
        cand=cands[0]
        self.assertEqual(["10.0.0.5:23/tcp","10.0.0.6:23/tcp","10.0.0.6:2323/tcp"],[a["value"] for a in cand["affected"]])
        self.assertEqual(["ev1","ev2"],cand["evidence_uids"])
        self.assertEqual("high",cand["confidence"]);self.assertEqual("medium",cand["severity"])
    def test_candidate_shape_and_finding_draft(self):
        cands=autogen.build_candidates([rec("hydra -l admin -P p.txt ssh://10.0.0.5","[22][ssh] host: 10.0.0.5   login: admin   password: <b>x</b>\n")],use_library=False)
        cand=cands[0]
        for key in ("key","title","severity","cvss_vector","confidence","reason","affected","evidence_uids","finding"):self.assertIn(key,cand)
        finding=cand["finding"]
        self.assertEqual({"kind":"autogen","ref":"default-creds"},finding["source"])
        self.assertEqual("high",finding["severity"]);self.assertEqual("open",finding["status"])
        self.assertEqual("CWE-1392",finding["cwe"])
        self.assertEqual([{"evidence_uid":"ev1","asset_uid":"","caption":""}],finding["evidence"])
        self.assertIn("unconfirmed",finding["tags"])
        self.assertTrue(finding["description"].startswith("<p>"));self.assertTrue(finding["remediation"].startswith("<p>"))
        self.assertIn("&lt;b&gt;x&lt;/b&gt;",finding["steps"]);self.assertNotIn("<b>x</b>",finding["steps"])
        self.assertIn("<code>hydra -l admin",finding["steps"])
    def test_keys_are_stable_and_candidates_sorted_by_severity(self):
        records=[rec("nmap -sV -sC 10.0.0.5 10.0.0.9",NMAP_FULL)]
        first=autogen.build_candidates(records,use_library=False);second=autogen.build_candidates(records,use_library=False)
        self.assertEqual([c["key"] for c in first],[c["key"] for c in second])
        self.assertEqual(len(first),len(set(c["key"] for c in first)))
        ranks=[autogen._SEV_RANK[c["severity"]] for c in first]
        self.assertEqual(sorted(ranks),ranks)
        self.assertEqual("critical",first[0]["severity"])
    def test_severity_changed_by_a_hit_drops_the_rule_vector(self):
        cands=autogen.build_candidates([rec("sudo -l","User bob may run the following commands on web01:\n    (root) NOPASSWD: /usr/bin/vim\n","web01")],use_library=False)
        self.assertEqual("medium",cands[0]["severity"]);self.assertEqual("",cands[0]["cvss_vector"])
    def test_affected_assets_link_to_profile_targets(self):
        with open(os.path.join(self.data_dir,"Targets.json"),"w",encoding="utf-8") as handle:json.dump([{"id":"t-web","name":"web01","status":"live","values":{"IP":"10.0.0.5","URL":"http://shop.example.com/"}}],handle)
        cands=autogen.build_candidates([rec("nmap 10.0.0.5","Nmap scan report for 10.0.0.5\n23/tcp open telnet\n"),rec("sqlmap -u http://shop.example.com/?id=1","sqlmap identified the following injection point(s)\nParameter: id (GET)\n    Type: error-based\n")],use_library=False)
        by_rule={c["rule"]:c for c in cands}
        self.assertEqual({"target_id":"t-web","name":"web01","value":"10.0.0.5:23/tcp"},by_rule["telnet"]["affected"][0])
        self.assertEqual("t-web",by_rule["sqli"]["affected"][0]["target_id"])
class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.isolated=IsolatedData();self.isolated.start();evidence._streams.clear()
    def tearDown(self):
        evidence._streams.clear();self.isolated.stop()
    def seed(self):
        self.scan=evidence.save_job({"session_id":"s1","job_key":"j1","command":"sudo nmap -sV -sC 10.0.0.5 10.0.0.9","output":NMAP_FULL,"exit_code":0,"started_at":"2026-11-23T10:12:00Z","session_label":"bash 1"})
        recording=evidence.recording_start({"session_id":"s2","label":"zsh 2"})
        evidence.recording_append(recording["id"],[{"ts":"2026-11-23T10:05:00Z","kind":"cmd","data":"id"},{"ts":"2026-11-23T10:05:00Z","kind":"out","data":"uid=1000(kali) gid=1000(kali)\n"},{"ts":"2026-11-23T10:05:01Z","kind":"exit","data":{"code":0,"duration":0.1}},{"ts":"2026-11-23T10:20:00Z","kind":"cmd","data":"ss -tlnp"},{"ts":"2026-11-23T10:20:00Z","kind":"out","data":SS_OUTPUT},{"ts":"2026-11-23T10:20:01Z","kind":"exit","data":{"code":0,"duration":0.2}},{"ts":"2026-11-23T10:30:00Z","kind":"cmd","data":"id"},{"ts":"2026-11-23T10:30:00Z","kind":"exit","data":{"code":127}}])
        self.recording=evidence.recording_stop(recording["id"])
        self.text=evidence.save_text({"title":"Pasted from the jump host","content":"[22][ssh] host: 10.0.0.9   login: admin   password: admin\n"})
        self.image=evidence.save_image("shot.png","iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
        return [self.scan["id"],self.recording["uid"],self.text["id"],self.image["id"],424242]
    def test_preview_shape_timeline_commands_tools_hosts(self):
        data=autogen.preview({"evidence_ids":self.seed(),"note_ids":[],"profile_id":""})
        for key in ("timeline","commands","tools","hosts","candidates","notes"):self.assertIn(key,data)
        self.assertEqual(["id","sudo nmap -sV -sC 10.0.0.5 10.0.0.9","ss -tlnp","id"],[row["command"] for row in data["timeline"]])
        first=data["timeline"][0]
        for key in ("ts","command","exit_code","evidence_uid","session_id"):self.assertIn(key,first)
        self.assertEqual((0,self.recording["uid"],"s2"),(first["exit_code"],first["evidence_uid"],first["session_id"]))
        self.assertEqual(127,data["timeline"][3]["exit_code"])
        self.assertEqual([("id",2),("sudo nmap -sV -sC 10.0.0.5 10.0.0.9",1),("ss -tlnp",1)],[(row["command"],row["count"]) for row in data["commands"]])
        self.assertEqual("2026-11-23T10:05:00+00:00",data["commands"][0]["first_ts"])
        self.assertEqual([("id",2),("nmap",1),("ss",1)],[(tool["name"],tool["count"]) for tool in data["tools"]])
        hosts={host["host"]:host for host in data["hosts"]}
        self.assertEqual(["10.0.0.5","10.0.0.9","Listening sockets (zsh 2)"],list(hosts))
        self.assertEqual(["web01.corp.example"],hosts["10.0.0.5"]["hostnames"])
        port=hosts["10.0.0.5"]["ports"][0]
        self.assertEqual({"port","proto","state","service","version"},set(port))
        listeners=hosts["Listening sockets (zsh 2)"]["ports"]
        self.assertEqual([(22,"listening","sshd"),(80,"listening","nginx"),(5432,"listening","postgres"),(68,"listening","")],[(p["port"],p["state"],p["service"]) for p in listeners])
        rules_found=set(c["rule"] for c in data["candidates"])
        self.assertIn("default-creds",rules_found);self.assertIn("ms17-010",rules_found)
        self.assertNotIn("root-shell",rules_found)
        creds=[c for c in data["candidates"] if c["rule"]=="default-creds"][0]
        self.assertEqual([self.text["uid"]],creds["evidence_uids"])
        self.assertEqual(4,len(data["evidence"]))
    def test_a_command_saved_alone_and_inside_a_recording_is_one_timeline_row(self):
        records=[rec("nmap 10.0.0.5","x",uid="job"),rec("nmap 10.0.0.5","x",uid="recording"),rec("id","y",uid="recording")]
        records[0]["ts"]="2026-11-23T10:00:01+00:00";records[0]["exit_code"]=None
        records[2]["ts"]="2026-11-23T10:00:02+00:00"
        later=rec("nmap 10.0.0.5","x",uid="recording");later["ts"]="2026-11-23T10:05:00+00:00"
        other=rec("nmap 10.0.0.5","x",uid="other");other["session_id"]="s2"
        timeline=autogen.build_timeline(records+[later,other])
        self.assertEqual([("nmap 10.0.0.5","s1"),("nmap 10.0.0.5","s2"),("id","s1"),("nmap 10.0.0.5","s1")],[(row["command"],row["session_id"]) for row in timeline])
        self.assertEqual(0,timeline[0]["exit_code"])
        self.assertEqual([("nmap 10.0.0.5",3),("id",1)],[(row["command"],row["count"]) for row in autogen.build_commands(timeline)])
    def test_preview_of_nothing_is_empty(self):
        data=autogen.preview({})
        self.assertEqual(([],[],[],[],[],[]),(data["timeline"],data["commands"],data["tools"],data["hosts"],data["candidates"],data["notes"]))
    def test_generated_html_is_escaped_and_uses_only_the_rich_subset(self):
        import re
        timeline=[{"ts":"2026-11-23T10:05:00+00:00","command":"echo '<script>alert(1)</script>' && x=\"y\"","exit_code":0,"evidence_uid":"u","session_id":"s<1>","session_label":""}]
        hosts=[{"host":"<img src=x onerror=1>","hostnames":["a&b"],"os":"<b>os</b>","ports":[{"port":80,"proto":"tcp","state":"open","service":"http","version":"<i>v</i>"}]}]
        blob=autogen.timeline_html(timeline)+autogen.commands_html(autogen.build_commands(timeline))+autogen.tools_html(autogen.build_tools(timeline))+autogen.hosts_html(hosts)
        self.assertNotIn("<script",blob);self.assertNotIn("<img",blob);self.assertNotIn("<b>",blob);self.assertNotIn("<i>",blob)
        self.assertIn("&lt;script&gt;",blob)
        self.assertEqual(set(),set(re.findall(r"</?([a-z0-9]+)",blob))-{"p","table","thead","tbody","tr","th","td","code","h4"})
        self.assertNotRegex(blob,r"<[a-z0-9]+\s")
class CreateTests(unittest.TestCase):
    def setUp(self):
        try:
            from Cores.Services import reports_service
        except ImportError:
            self.skipTest("reports_service is not available")
        for name in ("create_report","add_finding","add_section","get_report"):
            if not hasattr(reports_service,name):self.skipTest("reports_service."+name+" is not available")
        self.reports=reports_service
        self.isolated=IsolatedData();self.isolated.start();evidence._streams.clear()
    def tearDown(self):
        if hasattr(self,"isolated"):
            evidence._streams.clear();self.isolated.stop()
    def test_create_builds_a_draft_report_with_sections_and_accepted_findings(self):
        scan=evidence.save_job({"session_id":"s1","job_key":"j1","command":"nmap -sV -sC 10.0.0.5 10.0.0.9","output":NMAP_FULL,"exit_code":0,"started_at":"2026-11-23T10:12:00Z"})
        data=autogen.preview({"evidence_ids":[scan["id"]]})
        accepted=[c["key"] for c in data["candidates"] if c["rule"] in ("ms17-010","telnet")]
        telnet_key=[c["key"] for c in data["candidates"] if c["rule"]=="telnet"][0]
        result=autogen.create({"title":"ACME internal test","template_id":"internal_network","profile_id":"","evidence_ids":[scan["id"]],"note_ids":[],"accepted":accepted,"overrides":{telnet_key:{"severity":"high"}}})
        self.assertEqual(2,result["findings"])
        report=self.reports.get_report(result["report_id"])
        self.assertEqual("ACME internal test",report["title"]);self.assertEqual("draft",report["status"])
        findings={f["title"]:f for f in report["findings"]}
        self.assertEqual(2,len(findings))
        telnet=[f for f in report["findings"] if "Telnet" in f["title"]][0]
        self.assertEqual("high",telnet["severity"])
        self.assertEqual("autogen",telnet["source"]["kind"])
        self.assertEqual(scan["uid"],telnet["evidence"][0]["evidence_uid"])
        self.assertEqual("10.0.0.5:23/tcp",telnet["affected"][0]["value"])
        kinds={}
        for section in report["sections"]:kinds.setdefault(section["kind"],[]).append(section)
        for kind in ("appendix_commands","appendix_timeline","appendix_tools"):
            self.assertIn(kind,kinds)
            self.assertIn("<table>",kinds[kind][-1]["content"])
            self.assertFalse(kinds[kind][-1]["hidden"])
        self.assertIn("nmap -sV -sC 10.0.0.5 10.0.0.9",kinds["appendix_commands"][-1]["content"])
        hosts=[s for s in report["sections"] if s["title"]=="Discovered hosts and services"]
        self.assertEqual(1,len(hosts));self.assertIn("vsftpd 2.3.4",hosts[0]["content"])
    def test_create_with_nothing_accepted_adds_no_findings(self):
        scan=evidence.save_job({"session_id":"s1","job_key":"j1","command":"nmap 10.0.0.5","output":"Nmap scan report for 10.0.0.5\n23/tcp open telnet\n"})
        result=autogen.create({"title":"Empty","template_id":"blank","evidence_ids":[scan["id"]],"accepted":[]})
        self.assertEqual(0,result["findings"])
        self.assertEqual([],self.reports.get_report(result["report_id"])["findings"])
if __name__=="__main__":
    unittest.main()
