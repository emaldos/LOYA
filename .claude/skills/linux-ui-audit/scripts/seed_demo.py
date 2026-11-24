"""Seed obviously fake pentest demo data into a LOYA NG Data/ folder through the app's own API classes.

Usage (stop the app first):
  .venv_linux/bin/python3 .claude/skills/linux-ui-audit/scripts/seed_demo.py            # back up Data/, then seed
  .venv_linux/bin/python3 .claude/skills/linux-ui-audit/scripts/seed_demo.py --no-backup

Everything goes through Cores.Bridge.api (save/sync/auto-key logic runs for real). Demo items are tagged "demo"
and live in the "DEMO ..." target profiles, so they are easy to spot. All data is obviously fake: client "ACME Demo Corp",
hosts under demo.example.com, IPs only from the documentation ranges 203.0.113.0/24 and 198.51.100.0/24 (RFC 5737),
users such as jane.doe. Safe for README screenshots. The backup lands in Backups/pre-demo-<time>/.
"""
import os, sys, shutil, time, sqlite3, random, datetime
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
sys.path.insert(0, ROOT); os.chdir(ROOT)
from Cores.Bridge import api as A
from Cores.Services import terminal_service as TS
from Cores import common_db

def backup():
    src = os.path.join(ROOT, "Data")
    if not os.path.isdir(src): return None
    dst = os.path.join(ROOT, "Backups", "pre-demo-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    shutil.copytree(src, dst)
    return dst

def card(N, title, cat, sub, cmd, tags="demo", desc=""):
    return N.command_block_html(title, cat, sub, cmd, tags, desc)

def main():
    if "--no-backup" not in sys.argv:
        print("backup:", backup())
    N, C, T, P, S = A.NotesAPI(), A.CommandsAPI(), A.TargetsAPI(), A.PlaybooksAPI(), A.SearchAPI()
    rnd = random.Random(7)

    # --- Target profiles, keys, targets ------------------------------------------------------------
    def profile(name):
        for p in T.list_profiles() or []:
            if p.get("name") == name: return p.get("id")
        T.create_profile(name)
        for p in T.list_profiles() or []:
            if p.get("name") == name: return p.get("id")
        raise RuntimeError("profile not created: " + name)
    keys = [("IPv4", 10), ("Domain", 9), ("URL", 8), ("Port", 7), ("Username", 6), ("Password", 5), ("DC_IP", 4), ("Wordlist", 3), ("Hash", 2)]
    def ensure_keys():
        have = {str(k.get("key") if isinstance(k, dict) else k).lower() for k in (T.keys() or [])}
        for k, pr in keys:
            if k.lower() not in have:
                try: T.add_key(k, pr)
                except Exception as e: print("key", k, e)
    acme = profile("DEMO ACME Demo Corp - External")
    T.switch_profile(acme); ensure_keys()
    ext = [("web01.demo.example.com", "in_progress", {"IPv4": "203.0.113.15", "Domain": "demo.example.com", "URL": "https://portal.demo.example.com", "Port": "443", "Wordlist": "/usr/share/seclists/Discovery/Web-Content/raft-medium-words.txt"}),
           ("mail01.demo.example.com", "not_started", {"IPv4": "203.0.113.25", "Domain": "demo.example.com", "Port": "25"}),
           ("vpn-gw.demo.example.com", "compromised", {"IPv4": "203.0.113.1", "Domain": "vpn.demo.example.com", "Port": "443", "Username": "jane.doe"}),
           ("api.demo.example.com", "reported", {"IPv4": "203.0.113.40", "URL": "https://api.demo.example.com/v2", "Port": "8443"})]
    live = None
    for name, eng, vals in ext:
        tg = T.upsert_target(None, name, "Not Used", vals, eng)
        tid = next((t.get("id") for t in tg if t.get("name") == name), None)
        if name.startswith("web01"): live = tid
    internal = profile("DEMO ACME Demo Corp - Internal AD")
    T.switch_profile(internal); ensure_keys()
    for name, eng, vals in [("dc01.ad.demo.example.com", "compromised", {"IPv4": "198.51.100.10", "DC_IP": "198.51.100.10", "Domain": "ad.demo.example.com", "Username": "svc_demo", "Password": "DEMO-Passw0rd!"}),
                            ("files01.ad.demo.example.com", "in_progress", {"IPv4": "198.51.100.21", "Domain": "ad.demo.example.com", "Username": "svc_demo"}),
                            ("sql01.ad.demo.example.com", "not_started", {"IPv4": "198.51.100.30", "Port": "1433", "Domain": "ad.demo.example.com"})]:
        T.upsert_target(None, name, "Not Used", vals, eng)
    T.switch_profile(acme)
    if live: T.set_live_target(live)

    # --- Notes with command blocks -------------------------------------------------------------------
    for g in ("Recon", "Web Application", "Active Directory", "Post-Exploitation", "Reporting"):
        try: N.create_group(g)
        except Exception: pass
    notes = [
        ("External Recon - ACME Demo Corp", "Recon", "demo,recon,external",
         "<h2>Scope</h2><p>External perimeter for <b>demo.example.com</b> (203.0.113.0/24). Rules of engagement signed 2026-11-18; testing window 09:00-18:00 UTC.</p>"
         + card(N, "Full TCP scan", "Recon", "Port Scan", "nmap -sV -sC -p- -T4 {IPv4} -oA scans/{IPv4}", "demo,nmap")
         + card(N, "Subdomain enumeration", "Recon", "DNS", "subfinder -d {Domain} -silent | httpx -title -tech-detect", "demo,dns")
         + "<ul><li>443/tcp nginx 1.24 - customer portal</li><li>8443/tcp API gateway</li><li>25/tcp Postfix (mail01)</li></ul>"),
        ("SMB & Service Enumeration", "Recon", "demo,smb",
         "<p>Null sessions allowed on files01 - see shares below.</p>"
         + card(N, "SMB shares (null)", "Recon", "SMB", "nxc smb {IPv4} -u '' -p '' --shares", "demo,smb")
         + card(N, "enum4linux-ng", "Recon", "SMB", "enum4linux-ng -A {IPv4} -oJ loot/enum4linux_{IPv4}", "demo,smb")),
        ("Login Portal Testing", "Web Application", "demo,web,auth",
         "<h2>Finding: Username enumeration (Medium)</h2><p>The login form returns different messages for unknown users vs wrong passwords.</p>"
         + card(N, "Content discovery", "Web", "Fuzzing", "ffuf -u {URL}/FUZZ -w {Wordlist} -mc 200,204,301,302,403 -o ffuf_portal.json", "demo,web")
         + card(N, "SQLi check on login", "Web", "Injection", "sqlmap -u \"{URL}/login\" --data \"user=a&pass=b\" --batch --level 3", "demo,web,sqli")
         + "<table><tr><th>Endpoint</th><th>Status</th><th>Note</th></tr><tr><td>/admin</td><td>403</td><td>IP restricted</td></tr><tr><td>/api/v1/users</td><td>200</td><td>IDOR candidate</td></tr></table>"),
        ("API IDOR - /api/v1/users", "Web Application", "demo,web,idor",
         "<h2>Finding: Broken object level authorisation (High)</h2><p>Changing <code>id</code> returns other customers' profiles. CVSS 3.1: 7.5 (AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:N/A:N).</p>"
         + card(N, "Enumerate user ids", "Web", "API", "for i in $(seq 1000 1050); do curl -sk -H \"Authorization: Bearer $TOKEN\" {URL}/users/$i | jq -c '{id,email}'; done", "demo,api")),
        ("Kerberoasting", "Active Directory", "demo,ad,kerberos",
         "<p>Service accounts with SPNs found; svc_demo cracked in 4 minutes with rockyou.</p>"
         + card(N, "Request TGS hashes", "AD", "Kerberos", "GetUserSPNs.py {Domain}/{Username}:'{Password}' -dc-ip {DC_IP} -request -outputfile kerberoast.hashes", "demo,ad")
         + card(N, "Crack TGS", "AD", "Cracking", "hashcat -m 13100 kerberoast.hashes /usr/share/wordlists/rockyou.txt -r rules/best64.rule", "demo,cracking")),
        ("BloodHound Collection", "Active Directory", "demo,ad,bloodhound",
         "<p>Path: svc_demo -> Backup Operators -> DC01 (SeBackupPrivilege).</p>"
         + card(N, "Collect", "AD", "Enumeration", "bloodhound-python -u {Username} -p '{Password}' -d {Domain} -ns {DC_IP} -c All --zip", "demo,ad")),
        ("Privilege Escalation - files01", "Post-Exploitation", "demo,privesc,linux",
         "<p>Writable cron script in /opt/backup/run.sh executed as root every 5 minutes.</p>"
         + card(N, "Linpeas", "PrivEsc", "Linux", "curl -s http://{IPv4}:8000/linpeas.sh | sh | tee linpeas_files01.txt", "demo,privesc")),
        ("Executive Summary Draft", "Reporting", "demo,report",
         "<h2>Executive summary</h2><p>During the assessment window the team obtained domain administrator privileges in the ACME Demo Corp internal network and accessed customer data through an authorisation flaw in the ACME customer API. Two findings are rated High, three Medium.</p><ul><li>Prioritise the API authorisation fix.</li><li>Rotate service account credentials and enforce AES-only Kerberos.</li></ul>"),
        ("Engagement Checklist", "Reporting", "demo,methodology",
         "<ul><li>[x] Scope confirmed</li><li>[x] External recon</li><li>[ ] Retest IDOR fix</li><li>[ ] Final report QA</li></ul>"),
        ("Scratch - old notes", "Recon", "demo", "<p>Temporary notes, will be deleted (Recycle Bin demo).</p>"),
    ]
    ids = {}
    for name, group, tags, html in notes:
        try:
            r = N.save(None, name, group, html, None, tags)
        except TypeError:
            r = N.save(None, name, group, html, [], tags)
        ids[name] = (r or {}).get("id")
    for nm in ("External Recon - ACME Demo Corp", "API IDOR - /api/v1/users"):
        if ids.get(nm):
            try: N.set_pinned(ids[nm], nm, True)
            except Exception as e: print("pin", e)
    if ids.get("Scratch - old notes"): N.delete(ids["Scratch - old notes"])

    # --- Standalone commands (several shells, noise levels) ------------------------------------------
    standalone = [
        ("SPN service accounts", "AD", "Users", "Get-ADUser -Filter * -Properties ServicePrincipalName | Where-Object {$_.ServicePrincipalName} | Select SamAccountName", "demo,powershell,ad", "SPN users", "PowerShell", "stealthy"),
        ("Domain Admins members", "AD", "Groups", "net group \"Domain Admins\" /domain", "demo,cmd,ad", "", "CMD", "normal"),
        ("Ping sweep /24", "Recon", "Ping sweep", "nmap -sn {IPv4}/24 -oG - | awk '/Up/{print $2}'", "demo,nmap", "Live hosts", "Linux Shell", "normal"),
        ("TLS configuration scan", "Web", "TLS", "testssl.sh --fast {URL}", "demo,tls", "", "Linux Shell", "noisy"),
        ("SSH password spray", "Brute force", "SSH", "hydra -l {Username} -P {Wordlist} ssh://{IPv4} -t 4", "demo,bruteforce", "Lockout risk", "Linux Shell", "destructive"),
        ("MSSQL version & databases", "MSSQL", "Version", "SELECT @@version; SELECT name FROM sys.databases;", "demo,sql", "", "SQL", "stealthy"),
    ]
    for t in standalone:
        try: C.create(*t)
        except Exception as e: print("cmd", t[3][:30], e)

    # --- Quick Run favourites, runs, playbook ---------------------------------------------------------
    cmds = C.list()
    favs = [f"{c['src']}:{c['id']}" for c in cmds if any(w in c.get("command", "") for w in ("nmap -sV", "ffuf", "GetUserSPNs"))]
    try: S.set_favorites(favs, False)
    except Exception as e: print("fav", e)
    for c in cmds[:8]:
        for _ in range(rnd.randint(1, 4)):
            try: C.record_run(c["id"], c["src"], c.get("command", ""), {"target": "web01.demo.example.com"})
            except Exception: break
    try:
        pb = P.create("DEMO External web quick wins")
        pid = pb.get("id") if isinstance(pb, dict) else pb
        for c in cmds:
            if any(w in c.get("command", "") for w in ("nmap -sV", "subfinder", "ffuf")):
                P.add_step(pid, c["id"], c["src"])
    except Exception as e: print("playbook", e)

    # --- Terminal job history spread over the last 3 weeks --------------------------------------------
    jobs = [("nmap -sV -sC -p- -T4 203.0.113.15 -oA scans/203.0.113.15", 0), ("subfinder -d demo.example.com -silent", 0),
            ("ffuf -u https://portal.demo.example.com/FUZZ -w raft-medium-words.txt", 0), ("sqlmap -u https://portal.demo.example.com/login --batch", 1),
            ("GetUserSPNs.py ad.demo.example.com/svc_demo -dc-ip 198.51.100.10 -request", 0), ("hashcat -m 13100 kerberoast.hashes rockyou.txt", 0),
            ("nxc smb 198.51.100.21 -u '' -p '' --shares", 0), ("hydra -l jane.doe -P top100.txt ssh://203.0.113.1", 255), ("id; whoami /all", 0)]
    keys_made = []
    for i, (cmd, code) in enumerate(jobs * 2):
        k = f"demo-{int(time.time()*1000)}-{i}"
        TS.start_job(k, "demo-session", cmd, "terminal")
        TS.finish_job(k, code, "/opt/demo/acme-demo-corp", rnd.randint(200, 90000))
        keys_made.append(k)
    con = sqlite3.connect(common_db.db_path())
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
        for i, k in enumerate(keys_made):
            st = now - datetime.timedelta(days=rnd.randint(0, 20), hours=rnd.randint(0, 9), minutes=rnd.randint(0, 59))
            en = st + datetime.timedelta(seconds=rnd.randint(3, 1800))
            con.execute("UPDATE TerminalJobs SET started_at=?,ended_at=? WHERE job_key=?", (st.isoformat(), en.isoformat(), k))
        con.commit()
    finally: con.close()
    print("seeded: notes", len(notes), "standalone", len(standalone), "jobs", len(keys_made), "favourites", len(favs))

# --- Demo reports (Reporting tab) -------------------------------------------------------------------------
REPORTS = [
    {"title": "DEMO ACME Demo Corp - External Penetration Test", "template_id": "external_network", "profile": "DEMO ACME Demo Corp - External", "status": "review",
     "client": "ACME Demo Corp", "summary": "<p>Between 18 and 22 November 2026 the team assessed ACME Demo Corp's internet-facing perimeter. An authorisation flaw in the customer API exposed other customers' profile data; the login portal leaks which usernames exist. No remote code execution was achieved.</p><ul><li>Fix the API object-level authorisation first.</li><li>Unify login error messages and add rate limiting.</li><li>Harden TLS on the customer portal.</li></ul>",
     "findings": [
        {"title": "Broken object level authorisation in /api/v1/users", "severity": "high", "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:N/A:N", "affected": ["api.demo.example.com (203.0.113.40)"],
         "description": "Changing the numeric id in GET /api/v1/users/{id} returns other customers' profiles. The API checks that the caller is authenticated but not that the record belongs to them.",
         "impact": "Any customer can read every other customer's name, e-mail, address and order history (about 48,000 records).",
         "steps": "1. Log in as a normal customer and capture the bearer token.\n2. Request /api/v1/users/1001 to /api/v1/users/1050 with that token.\n3. Every request returns 200 with another customer's data.",
         "remediation": "Enforce ownership checks on every object lookup server-side (user id from the session, not the URL). Add automated authorisation tests.", "references": ["https://owasp.org/API-Security/editions/2023/en/0xa1-broken-object-level-authorization/"], "cwe": "CWE-639", "owasp": "API1:2023"},
        {"title": "Username enumeration on the customer login", "severity": "medium", "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:L/I:N/A:N", "affected": ["web01.demo.example.com (203.0.113.15)"],
         "description": "The login form answers 'Unknown user' for non-existent accounts and 'Wrong password' for existing ones.", "impact": "Attackers can build a list of valid accounts for password spraying.",
         "steps": "Submit the login form with a random username, then with a known one, and compare the messages.", "remediation": "Return one generic message and add per-account and per-IP rate limiting.", "cwe": "CWE-204"},
        {"title": "Weak TLS configuration on the customer portal", "severity": "low", "cvss_vector": "CVSS:3.1/AV:N/AC:H/PR:N/UI:N/S:U/C:L/I:N/A:N", "affected": ["web01.demo.example.com:443"],
         "description": "TLS 1.0/1.1 and CBC cipher suites are still accepted.", "impact": "Older protocol versions have known weaknesses that make interception easier for a well-placed attacker.",
         "remediation": "Allow only TLS 1.2+ with AEAD cipher suites; enable HSTS.", "cwe": "CWE-326"},
        {"title": "Missing HTTP security headers", "severity": "info", "affected": ["portal.demo.example.com"],
         "description": "Content-Security-Policy, X-Frame-Options and Referrer-Policy are not set.", "remediation": "Add the headers at the reverse proxy."}]},
    {"title": "DEMO ACME Demo Corp - Internal Network & Active Directory", "template_id": "internal_network", "profile": "DEMO ACME Demo Corp - Internal AD", "status": "draft",
     "client": "ACME Demo Corp", "summary": "<p>From a standard user foothold the team reached Domain Admin in under four hours by Kerberoasting a service account with a weak password and abusing its Backup Operators membership.</p>",
     "findings": [
        {"title": "Domain compromise via Backup Operators membership", "severity": "critical", "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:C/C:H/I:H/A:H", "affected": ["dc01.ad.demo.example.com (198.51.100.10)"],
         "description": "svc_demo is a member of Backup Operators, which grants SeBackupPrivilege on the domain controller; the NTDS.dit database could be copied.",
         "impact": "Full domain compromise: every account's password hash was recovered.", "steps": "1. Kerberoast svc_demo.\n2. Crack the TGS (4 minutes, rockyou + best64).\n3. Use SeBackupPrivilege to copy NTDS.dit and the SYSTEM hive.\n4. Extract hashes offline.",
         "remediation": "Remove service accounts from Backup Operators; use gMSAs; monitor for shadow-copy creation on DCs.", "cwe": "CWE-269"},
        {"title": "Kerberoastable service account with a weak password", "severity": "high", "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H", "affected": ["ad.demo.example.com\\svc_demo"],
         "description": "svc_demo has an SPN and uses RC4 with an 11-character dictionary password.", "impact": "Any domain user can request its ticket and crack the password offline.",
         "remediation": "Use 25+ character random passwords or gMSAs for service accounts and enforce AES-only Kerberos.", "references": ["https://attack.mitre.org/techniques/T1558/003/"], "cwe": "CWE-521"},
        {"title": "Local privilege escalation through a writable root cron script", "severity": "high", "cvss_vector": "CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H", "affected": ["files01.ad.demo.example.com (198.51.100.21)"],
         "description": "/opt/backup/run.sh is world-writable and runs as root every 5 minutes.", "impact": "Any local user becomes root.", "remediation": "Make the script root-owned and 0755; review other cron jobs.", "cwe": "CWE-732"},
        {"title": "SMB null sessions allowed", "severity": "medium", "cvss_vector": "CVSS:3.1/AV:A/AC:L/PR:N/UI:N/S:U/C:L/I:N/A:N", "affected": ["files01.ad.demo.example.com (198.51.100.21)"],
         "description": "Anonymous SMB sessions can list shares and users.", "remediation": "Set RestrictAnonymous=2 and disable SMBv1."}]},
    {"title": "DEMO ACME API - Retest", "template_id": "retest_short", "profile": "DEMO ACME Demo Corp - External", "status": "final", "client": "ACME Demo Corp",
     "summary": "<p>Retest of the findings reported on 22 November 2026. The authorisation flaw is fixed; username enumeration remains.</p>",
     "findings": [
        {"title": "Broken object level authorisation in /api/v1/users", "severity": "high", "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:N/A:N", "status": "fixed", "affected": ["api.demo.example.com (203.0.113.40)"],
         "description": "Retested on 2 December 2026: requests for other users' ids now return 403.", "remediation": "Fixed - no further action."},
        {"title": "Username enumeration on the customer login", "severity": "medium", "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:L/I:N/A:N", "status": "retest", "affected": ["web01.demo.example.com (203.0.113.15)"],
         "description": "The messages are now identical, but response times still differ by ~180 ms for valid users.", "remediation": "Make the password check constant-time for unknown users."}]},
]

def seed_reports():
    from Cores.Bridge import reports_api as R
    from Cores import target_profiles as TP
    rep = R.ReportsAPI()
    have = {r.get("title") for r in (rep.list() or [])}
    profiles = {p["name"]: p["id"] for p in TP.list_profiles()}
    made = 0
    for spec in REPORTS:
        if spec["title"] in have: continue
        r = rep.create({"title": spec["title"], "template_id": spec["template_id"], "profile_id": profiles.get(spec["profile"], ""), "status": spec["status"],
                        "meta": {"client": spec["client"], "testers": ["Jane Doe (DEMO)"]}})
        rid = r["id"]
        for sec in r.get("sections", []):
            if sec.get("kind") in ("executive_summary", "summary") or "summary" in sec.get("title", "").lower():
                rep.section_update(sec["id"], {"content": spec["summary"]}); break
        for f in spec["findings"]:
            rep.finding_add(rid, f)
        try: rep.findings_sort(rid, "severity")
        except Exception: pass
        made += 1
    print("reports seeded:", made)

if __name__ == "__main__":
    if "--reports-only" in sys.argv:
        seed_reports()
    else:
        main()
        seed_reports()
