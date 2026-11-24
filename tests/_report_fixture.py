"""Rich Report fixture in the reporting contract's exact shape, shared by the export and import tests."""
import io,copy
def png(width=320,height=120,color=(31,78,121)):
    from PIL import Image,ImageDraw
    im=Image.new("RGB",(width,height),color);d=ImageDraw.Draw(im)
    d.rectangle([8,8,width-8,height-8],outline=(255,255,255),width=3)
    d.line([8,8,width-8,height-8],fill=(245,158,11),width=4)
    buf=io.BytesIO();im.save(buf,"PNG")
    return buf.getvalue()
XSS='<script>alert(1)</script><img src=x onerror=alert(2)>"\'&'
SECRET="wJalrXUtnFEMIK7MDENGbPxRfiCYEXAMPLEKEY"
def evidence():
    return [
        {"id":1,"uid":"ev-nmap","kind":"command","title":"Service scan of the web tier","source":"terminal","session_id":"s1","profile_id":"p1","target":"web01","command":"nmap -sV -p 80,443,8443 10.20.0.15","exit_code":0,"cwd":"/home/tester",
         "started_at":"2026-11-16T09:12:04+00:00","ended_at":"2026-11-16T09:12:31+00:00","content":"Starting Nmap 7.95 ( https://nmap.org )\nPORT     STATE SERVICE  VERSION\n80/tcp   open  http     nginx 1.18.0\n443/tcp  open  ssl/http nginx 1.18.0\n8443/tcp open  ssl/http Apache Tomcat 9.0.31\n\x1b[32mNmap done\x1b[0m: 1 IP address (1 host up) scanned in 26.41 seconds",
         "meta":{"redacted":0,"shell":"zsh","tags":["recon"]},"created_at":"2026-11-16T09:12:31+00:00"},
        {"id":2,"uid":"ev-sqlmap","kind":"command","title":"","source":"terminal","session_id":"s1","profile_id":"p1","target":"web01","command":"sudo sqlmap -u 'https://shop.acme.example/item?id=7' --batch --dbs","exit_code":0,"cwd":"/home/tester",
         "started_at":"2026-11-17T13:40:00+00:00","ended_at":"2026-11-17T13:44:10+00:00","content":"[13:41:02] [INFO] GET parameter 'id' is vulnerable\navailable databases [3]:\n[*] information_schema\n[*] shop\n[*] users\nAWS_SECRET_ACCESS_KEY="+SECRET+"\n"+"\n".join(f"[13:42:{i%60:02d}] [INFO] fetched row {i}" for i in range(200)),
         "meta":{"redacted":0},"created_at":"2026-11-17T13:44:10+00:00"},
        {"id":3,"uid":"ev-shot","kind":"image","title":"Admin console reachable without authentication","source":"manual","session_id":"","profile_id":"p1","target":"web01","command":"","exit_code":None,"cwd":"","started_at":"2026-11-18T10:00:00+00:00","ended_at":"",
         "content":"","meta":{"asset_uid":"asset-shot"},"created_at":"2026-11-18T10:00:00+00:00"},
        {"id":4,"uid":"ev-rec","kind":"recording","title":"Privilege escalation session","source":"terminal","session_id":"s2","profile_id":"p1","target":"db01","command":"","exit_code":None,"cwd":"","started_at":"2026-11-19T15:00:00+00:00","ended_at":"2026-11-19T15:05:00+00:00",
         "content":"$ id\nuid=33(www-data)\n$ sudo -l\n(ALL) NOPASSWD: /usr/bin/vim\n","meta":{"state":"stopped"},"created_at":"2026-11-19T15:00:00+00:00",
         "events":[{"seq":1,"ts":"2026-11-19T15:00:05+00:00","kind":"cmd","data":"id"},{"seq":2,"ts":"2026-11-19T15:00:05+00:00","kind":"out","data":"uid=33(www-data)\n"},{"seq":3,"ts":"2026-11-19T15:00:06+00:00","kind":"exit","data":"0"},
                   {"seq":4,"ts":"2026-11-19T15:01:00+00:00","kind":"cmd","data":"sudo -l"},{"seq":5,"ts":"2026-11-19T15:01:01+00:00","kind":"out","data":"(ALL) NOPASSWD: /usr/bin/vim\n"},{"seq":6,"ts":"2026-11-19T15:01:01+00:00","kind":"exit","data":"0"}]},
    ]
def assets():
    return {"asset-logo":{"mime":"image/png","name":"logo.png","data":png(240,80,(255,255,255))},"asset-shot":{"mime":"image/png","name":"admin.png","data":png(900,520,(15,23,42))},"asset-inline":{"mime":"image/png","name":"inline.png","data":png(400,200,(100,116,139))}}
def finding(i,title,severity,**kw):
    f={"id":100+i,"uid":f"f-{i}","report_id":1,"position":i,"title":title,"severity":severity,"cvss_vector":"","cvss_score":None,"status":"open","cwe":"","owasp":"","references":[],"affected":[],
       "description":"","impact":"","likelihood":"","steps":"","remediation":"","evidence":[],"tags":[],"retest_notes":"","source":{"kind":"","ref":""},"created_at":"2026-11-20T10:00:00+00:00","updated_at":"2026-11-20T10:00:00+00:00"}
    f.update(kw)
    return f
def report():
    sections=[
        {"id":1,"uid":"s-dc","kind":"document_control","title":"Document Control","content":"<p>This document is the property of {{client}} and {{company}}.</p>","position":0,"hidden":False,"options":{}},
        {"id":2,"uid":"s-ex","kind":"executive_summary","title":"Executive Summary","content":"<p>{{company}} performed an external penetration test for <strong>{{client}}</strong> between {{start_date}} and {{end_date}} — engagement <em>{{engagement}}</em>. Unknown token {{nope}} stays.</p><h3>Key observations</h3><ul><li>Two <u>critical</u> issues allow <code>remote code execution</code>.<ul><li>Nested point with a <a href=\"https://owasp.org/Top10/\">link</a></li></ul></li><li>Patch management is <s>adequate</s> weak.</li></ul><blockquote><p>Overall risk: <strong>High</strong>.</p></blockquote><ol><li>First action</li><li>Second action</li></ol><hr><p>Password was <span class=\"rpt-redact\">hunter2-very-secret</span> at the time.</p><p><img src=\"rptasset:asset-inline\" alt=\"Network diagram\" data-width=\"60\"></p><table><thead><tr><th>Area</th><th>Rating</th></tr></thead><tbody><tr><td>Perimeter</td><td>Poor</td></tr><tr><td colspan=\"2\">Merged note across both columns</td></tr></tbody></table>","position":1,"hidden":False,"options":{}},
        {"id":3,"uid":"s-sc","kind":"scope","title":"Scope & Rules of Engagement","content":"<p>The following assets were tested.</p>","position":2,"hidden":False,"options":{}},
        {"id":4,"uid":"s-me","kind":"methodology","title":"Methodology","content":"<p>Testing followed {{methodology}}.</p><pre>recon -> scanning -> exploitation -> reporting</pre>","position":3,"hidden":False,"options":{}},
        {"id":5,"uid":"s-fs","kind":"findings_summary","title":"Findings Summary","content":"<p>{{total_findings}} findings were identified.</p>","position":4,"hidden":False,"options":{}},
        {"id":6,"uid":"s-fi","kind":"findings","title":"Detailed Findings","content":"","position":5,"hidden":False,"options":{}},
        {"id":7,"uid":"s-rr","kind":"remediation_roadmap","title":"Remediation Roadmap","content":"<p>Address the items below in order.</p>","position":6,"hidden":False,"options":{}},
        {"id":8,"uid":"s-hid","kind":"custom","title":"Internal Notes HIDDENSECTION","content":"<p>must never be exported</p>","position":7,"hidden":True,"options":{}},
        {"id":9,"uid":"s-co","kind":"conclusion","title":"Conclusion","content":"<p>Retest is recommended after remediation.</p><figure class=\"rpt-ev\" data-evidence=\"ev-gone\"><figcaption>$ curl -sI https://shop.acme.example — exit 0 — 2026-11-18 11:02 UTC</figcaption><pre>HTTP/1.1 200 OK\nServer: nginx/1.18.0</pre></figure>","position":8,"hidden":False,"options":{}},
        {"id":10,"uid":"s-at","kind":"appendix_tools","title":"Tools Used","content":"","position":9,"hidden":False,"options":{}},
        {"id":11,"uid":"s-ac","kind":"appendix_commands","title":"Commands Run","content":"","position":10,"hidden":False,"options":{}},
        {"id":12,"uid":"s-tl","kind":"appendix_timeline","title":"Timeline","content":"","position":11,"hidden":False,"options":{}},
        {"id":13,"uid":"s-ae","kind":"appendix_evidence","title":"Evidence","content":"<p>All evidence referenced in this report.</p>","position":12,"hidden":False,"options":{}},
    ]
    findings=[
        finding(1,"SQL Injection in product catalogue","critical",cvss_vector="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",cvss_score=9.8,cwe="CWE-89",owasp="A03:2021 Injection",likelihood="high",
            references=["https://owasp.org/www-community/attacks/SQL_Injection","CWE-89 reference card"],affected=[{"target_id":"t1","name":"web01","value":"https://shop.acme.example/item"},{"target_id":"","name":"","value":"10.20.0.15"}],
            description="<p>The <code>id</code> parameter is concatenated into a SQL statement → full database read.</p>",impact="<p>An unauthenticated attacker can read <strong>all</strong> customer records.</p>",
            steps="<ol><li>Browse to the item page.</li><li>Append <code>' OR 1=1-- -</code>.</li></ol><figure class=\"rpt-ev\" data-evidence=\"ev-nmap\"><figcaption>$ nmap -sV -p 80,443,8443 10.20.0.15 — exit 0 — 2026-11-16 09:12 UTC</figcaption><pre>80/tcp open http nginx 1.18.0</pre></figure>",
            remediation="<p>Use parameterised queries. Validate input server-side. Apply least privilege to the database account.</p>",evidence=[{"evidence_uid":"ev-sqlmap","asset_uid":"","caption":"sqlmap confirms the injection"},{"evidence_uid":"","asset_uid":"asset-shot","caption":"Dumped table in the browser"}],tags=["web","injection"]),
        finding(2,"Stored XSS "+XSS,"high",cvss_vector="CVSS:3.1/AV:N/AC:L/PR:L/UI:R/S:C/C:L/I:L/A:N",cvss_score=5.4,cwe="CWE-79",owasp="A03:2021 Injection",status="retest",affected=[{"target_id":"","name":"=HYPERLINK(\"http://evil\")","value":"=HYPERLINK(\"http://evil\")"}],
            description="<p>Comment field renders markup: "+"&lt;script&gt;alert(1)&lt;/script&gt;"+"</p>",impact="<p>Session theft.</p>",remediation="<p>Encode output.</p>",retest_notes="Retested 2026-11-22: still reproducible.",evidence=[{"evidence_uid":"ev-shot","asset_uid":"","caption":""}]),
        finding(3,"=cmd|' /C calc'!A0","medium",cvss_score=5.3,cvss_vector="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:L/I:N/A:N",status="fixed",description="<p>+SUM(1) formula-looking text</p>",remediation="<p>-2+3 fix it</p>",affected=[{"target_id":"t2","name":"db01","value":"10.20.0.22"}],evidence=[{"evidence_uid":"ev-rec","asset_uid":"","caption":"Recorded session"}]),
        finding(4,"Missing security headers","low",cvss_score=3.1,status="accepted",description="<p>HSTS and CSP are absent.</p>",remediation="<ul><li>Add <code>Strict-Transport-Security</code></li><li>Add a CSP</li></ul>"),
        finding(5,"Server banner discloses version","info",description="<p>nginx/1.18.0 is disclosed.</p>",evidence=[{"evidence_uid":"ev-missing","asset_uid":"","caption":"lost capture"}]),
    ]
    return {"id":1,"uid":"rep-acme","title":"ACME External Pentest Report","status":"review","template_id":"external_network","profile_id":"p1","created_at":"2026-11-15T08:00:00+00:00","updated_at":"2026-11-23T08:00:00+00:00",
        "meta":{"client":"ACME Corp","client_contact":"Jane Roe <jane@acme.example>","engagement":"External Network Penetration Test","project_code":"ACME-2026-11","report_type":"Penetration Test Report","start_date":"2026-11-16","end_date":"2026-11-20","report_date":"2026-11-23",
            "testers":[{"name":"Alex Tester","role":"Lead Consultant","email":"alex@redteam.example"},{"name":"Sam Pwn","role":"Consultant","email":"sam@redteam.example"}],"scope_in":["shop.acme.example","10.20.0.0/24"],"scope_out":["mail.acme.example"],
            "rules_of_engagement":"Testing between 08:00 and 18:00 UTC.\nNo denial-of-service.","methodology":"OWASP WSTG, PTES","classification":"Confidential","version":"1.2","authors":"Alex Tester","reviewers":"Riley Review","distribution":["Jane Roe (ACME Corp)","Alex Tester (RedTeam Ltd)"]},
        "branding":{"company":"RedTeam Ltd","logo_asset":"asset-logo","accent":"#1f4e79","secondary":"#64748b","banner":"Confidential — {{client}} only","footer":"RedTeam Ltd · redteam.example","cover_subtitle":"External Penetration Test","show_cover":True},
        "options":{"page_size":"A4","include_toc":True,"include_appendices":True,"number_sections":True,"finding_id_prefix":"F-"},
        "sections":sections,"findings":findings,"versions":[{"id":1,"label":"0.9 draft for review","created_at":"2026-11-21T16:00:00+00:00"},{"id":2,"label":"1.0 issued","created_at":"2026-11-22T12:00:00+00:00"}],
        "stats":{"counts":{"critical":1,"high":1,"medium":1,"low":1,"info":1},"total":5,"open":2,"by_status":{"open":2,"retest":1,"fixed":1,"accepted":1}},
        "_assets":assets(),"_evidence":evidence()}
def big_report(n=200):
    r=report();base=copy.deepcopy(r["findings"][0]);out=[]
    sevs=["critical","high","medium","low","info"]
    for i in range(n):
        f=copy.deepcopy(base);f.update({"id":1000+i,"uid":f"bf-{i}","position":i,"title":f"Finding number {i+1} with a reasonably long descriptive title","severity":sevs[i%5],"status":["open","retest","fixed","accepted"][i%4]})
        f["evidence"]=[] if i%10 else f["evidence"]
        out.append(f)
    r["findings"]=out
    return r
