import base64,json,os,sqlite3,unittest
from _isolate import IsolatedData
from Cores import common_db,target_profiles
from Cores.Services import notes_service,reports_service as reports
from Cores.Bridge.reports_api import ReportsAPI
from test_reports_model import png
# The stated score (7.5) in GENERIC is wrong for its vector on purpose: the vector wins.
# The markup NotesPro.findingTemplateHtml() writes (UI/js/pages/notes_pro_core.js), filled in the way a tester would.
CALLOUT=('<p>Intro paragraph before the finding.</p>'
    '<div class="note-callout note-finding" data-callout="finding" data-sev="high"><h3>SQL injection in login form</h3>'
    '<table class="note-table note-table-head"><tbody><tr><th>Severity</th><td>High</td></tr><tr><th>CVSS</th><td>CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:N (9.1)</td></tr>'
    '<tr><th>Affected hosts</th><td>web01, 10.0.0.9<br>app.acme.test</td></tr><tr><th>References</th><td><a href="https://owasp.org/sqli">OWASP</a> https://cwe.mitre.org/data/definitions/89.html, CWE-89</td></tr></tbody></table>'
    '<h4>Description</h4><p>The <code>user</code> parameter is concatenated into the query.</p><p style="color:red" onclick="x()">Second paragraph.</p>'
    '<h4>Steps to reproduce</h4><ol><li>Send <code>\' OR 1=1-- -</code></li><li>Observe the login bypass<script>alert(1)</script></li></ol>'
    '<h4>Impact</h4><p>Full read access to the database. A03:2021 Injection</p><h4>Remediation</h4><p>Use prepared statements.</p></div>'
    '<div class="note-callout" data-callout="info"><p>Just a note, not a finding.</p></div>'
    '<div class="note-callout" data-callout="vuln" data-sev="medium" data-cvss="5.3"><p><strong>Directory listing enabled</strong></p><p>Listing is on for <code>/backup/</code>.</p></div>'
    '<div class="note-callout" data-callout="evidence"><pre>uid=0(root)</pre></div>')
UNTOUCHED='<div class="note-callout note-finding" data-callout="finding" data-sev="medium"><h3>Finding title</h3><table class="note-table note-table-head"><tbody><tr><th>Severity</th><td>Medium</td></tr><tr><th>CVSS</th><td><br></td></tr><tr><th>Affected hosts</th><td><br></td></tr><tr><th>References</th><td><br></td></tr></tbody></table><h4>Description</h4><p><br></p><h4>Steps to reproduce</h4><ol><li><br></li></ol><h4>Impact</h4><p><br></p><h4>Remediation</h4><p><br></p></div>'
GENERIC=('<h2>Recon</h2><p>nothing here</p>'
    '<h2>Finding: Username enumeration (Medium)</h2><p>The login form returns different messages for unknown users.</p><h3>Remediation</h3><p>Return one generic message.</p>'
    '<h2>Finding: Broken object level authorisation (High)</h2><p>Changing <code>id</code> returns other customers\' profiles. CVSS 3.1: 7.5 (AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:N/A:N). CWE-639</p>'
    '<p><strong>[CRITICAL] Default admin password</strong></p><p>admin/admin works on the router.</p><p><b>Fix:</b></p><p>Change it.</p>'
    '<h2>Loot</h2><p>not part of the finding</p>'
    '<h3>[low] Verbose banner</h3><p>Server header shows the version. CVSS 2.6</p>')
# Captured from the finished Notes editor running on WebKitGTK (typed with real key events; callouts, credential form, attachments and the drawing tool's flattened PNG
# inserted through the editor's own functions). {SHOT} / {DRAW} stand for the file:// URLs of the two attachments.
REAL=('<h2>Recon</h2><p>Scan results below.</p><pre class="note-code" data-lang="bash">nmap -sV 10.10.20.5\necho done</pre>'
    '<p><ul class="note-checklist"><li data-checked="1">Scope confirmed</li><li>Retest IDOR</li></ul><p><br></p></p>'
    '<div class="note-callout" data-callout="finding" data-sev="high" data-cvss="8.8"><p>SQL injection in login form</p><p>The user parameter is concatenated into the query. CWE-89</p>'
    '<div class="note-callout" data-callout="evidence"><p>sqlmap output</p><pre class="note-code" data-lang="output">uid=0(root) gid=0(root)</pre><p><br></p><p><br></p><p><br></p></div><p><br></p></div>'
    '<div class="note-callout" data-callout="warning"><p>Do not run sqlmap with --risk 3 on production.</p></div>'
    '<div class="note-callout" data-callout="credential"><p><b>Host: </b>10.10.20.5 - SSH</p><p><b>User: </b>svc_backup</p><p><b>Secret: </b><span class="note-secret">Summer2026!</span>&nbsp;</p><p><b>Notes: </b>Found in /opt/backup/run.sh</p></div>'
    '<h2 data-collapsed="1">Loot</h2><p>Password reuse on files01.</p>'
    '<figure class="note-embed note-embed-inline" contenteditable="false" draggable="true" data-attachment-id="96bb458d80024dce" data-attachment-url="{SHOT}" data-kind="image"><img src="{SHOT}" alt="login-bypass.png"></figure>'
    '<figure class="note-embed note-embed-inline" contenteditable="false" draggable="true" data-attachment-id="7ad26c2dd1a14262" data-attachment-url="{DRAW}" data-kind="sketch" data-shapes="eyJ2IjoxLCJ3IjoyMDAsImgiOjEyMCwiYmciOiIiLCJzaGFwZXMiOltdfQ"><img src="{DRAW}" alt="drawing-1.png"></figure><p><br></p>')
class NotesBase(unittest.TestCase):
    def setUp(self):
        self.isolated=IsolatedData()
        self.dir=self.isolated.start()
        self.api=ReportsAPI()
    def tearDown(self):
        self.isolated.stop()
    def note(self,name,content,group="",tags=""):
        con=sqlite3.connect(common_db.db_path())
        try:
            common_db.ensure_schema(con)
            cur=con.execute("INSERT INTO Notes(note_name,group_name,tags,content,created_at,updated_at) VALUES(?,?,?,?,?,?)",(name,group,tags,content,"2026-11-01T00:00:00+00:00","2026-11-0%dT00:00:00+00:00"%(1+len(name)%8)))
            con.commit()
            return int(cur.lastrowid)
        finally:con.close()
class NoteFindingsTests(NotesBase):
    def test_callouts_written_by_the_notes_editor(self):
        with open(target_profiles.profile_targets_json_path(target_profiles.active_profile_id()),"w",encoding="utf-8") as fh:
            json.dump([{"id":"tw","name":"WEB01","values":{"IP":"10.0.0.8"}},{"id":"tapp","name":"App server","values":{"HOST":"app.acme.test","IP":"10.0.0.7"}}],fh)
        nid=self.note("ACME web",CALLOUT)
        drafts=self.api.note_findings([nid])
        self.assertEqual(["SQL injection in login form","Directory listing enabled"],[d["title"] for d in drafts])
        a,b=drafts
        self.assertEqual(("high","CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:N",9.1,"open","CWE-89"),(a["severity"],a["cvss_vector"],a["cvss_score"],a["status"],a["cwe"]))
        self.assertEqual("A03:2021 Injection",a["owasp"])
        self.assertEqual([{"target_id":"tw","name":"WEB01","value":"10.0.0.8"},{"target_id":"","name":"10.0.0.9","value":""},{"target_id":"tapp","name":"App server","value":"app.acme.test"}],a["affected"])
        self.assertEqual(["https://owasp.org/sqli","https://cwe.mitre.org/data/definitions/89.html"],a["references"])
        self.assertEqual("<p>The <code>user</code> parameter is concatenated into the query.</p><p>Second paragraph.</p>",a["description"])
        self.assertEqual("<ol><li>Send <code>' OR 1=1-- -</code></li><li>Observe the login bypass</li></ol>",a["steps"])
        self.assertEqual("<p>Full read access to the database. A03:2021 Injection</p>",a["impact"]);self.assertEqual("<p>Use prepared statements.</p>",a["remediation"])
        self.assertEqual(({"kind":"note","ref":str(nid)},nid,"ACME web"),(a["source"],a["note_id"],a["note_name"]))
        self.assertEqual(("medium","",5.3),(b["severity"],b["cvss_vector"],b["cvss_score"]))
        self.assertEqual("<p>Listing is on for <code>/backup/</code>.</p>",b["description"])
        for d in drafts:
            for k in ("description","impact","steps","remediation"):self.assertEqual(d[k],reports.sanitize_html(d[k]))
        # A draft goes straight into a report.
        rep=self.api.create({"title":"R"})
        f=self.api.finding_add(rep["id"],a)
        self.assertEqual((a["title"],"high",9.1,a["affected"],a["references"],a["description"],{"kind":"note","ref":str(nid)}),(f["title"],f["severity"],f["cvss_score"],f["affected"],f["references"],f["description"],f["source"]))
        self.assertNotIn("note_id",f)
    def test_untouched_template_is_skipped_but_a_titled_one_is_kept(self):
        self.assertEqual([],self.api.note_findings([self.note("empty",UNTOUCHED)]))
        d=self.api.note_findings([self.note("titled",UNTOUCHED.replace("Finding title","Weak password policy"))])
        self.assertEqual([("Weak password policy","medium",None,"","","","")],[(x["title"],x["severity"],x["cvss_score"],x["description"],x["steps"],x["impact"],x["remediation"]) for x in d])
    def test_callout_variants_are_parsed_defensively(self):
        cases=(
            ('<div data-callout="finding" data-sev="CRITICAL" data-cvss="9,8">RCE in upload<br>Shell uploaded via avatar.</div>',("RCE in upload","critical",9.8)),
            ('<section class="note-callout" data-callout="vulnerability"><h2>[High] Open redirect</h2><p>x</p></section>',("Open redirect","high",None)),
            ('<div class="note-finding"><h4>Finding: Weak cipher (Low)</h4><p>CVSS: 3.7</p></div>',("Weak cipher","low",3.7)),
            ('<div data-callout="finding" data-sev="bogus" data-cvss="99"><h3>No severity</h3><p>text</p></div>',("No severity","info",None)),
            ('<div data-callout="finding"><h3>From vector</h3><p>AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H</p></div>',("From vector","critical",9.8)),
            ('<div data-callout="finding" data-sev="low"><h3>Unclosed<p>body <b>text',("Unclosed","low",None)),
            ('<div data-callout=finding data-sev=high><table><tr><td>Severity</td><td>Critical</td></tr><tr><td>Status</td><td>Fixed</td></tr></table><p><b>Title after table</b></p></div>',("Severity Critical","high",None)),
        )
        for markup,(title,sev,score) in cases:
            d=self.api.note_findings([self.note("n"+title,markup)])
            self.assertEqual(1,len(d),markup)
            self.assertEqual((title,sev,score),(d[0]["title"],d[0]["severity"],d[0]["cvss_score"]),markup)
        nested=self.api.note_findings([self.note("nested",'<div data-callout="finding" data-sev="high"><h3>Outer</h3><div data-callout="finding" data-sev="low"><h3>Inner</h3></div><p>o</p></div>')])
        self.assertEqual(["Outer"],[d["title"] for d in nested])
    def test_generic_headings_fallback(self):
        nid=self.note("pentest notes",GENERIC)
        drafts=self.api.note_findings([nid])
        self.assertEqual([("Username enumeration","medium",None),("Broken object level authorisation","high",6.5),("Default admin password","critical",None),("Verbose banner","low",2.6)],[(d["title"],d["severity"],d["cvss_score"]) for d in drafts])
        self.assertEqual("<p>The login form returns different messages for unknown users.</p>",drafts[0]["description"]);self.assertEqual("<p>Return one generic message.</p>",drafts[0]["remediation"])
        self.assertEqual(("CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:N/A:N","CWE-639"),(drafts[1]["cvss_vector"],drafts[1]["cwe"]))
        self.assertEqual(("<p>admin/admin works on the router.</p>","<p>Change it.</p>"),(drafts[2]["description"],drafts[2]["remediation"]))
        self.assertNotIn("not part of the finding","".join(d["description"]+d["remediation"] for d in drafts))
    def test_nothing_to_find(self):
        plain=self.note("plain","<h2>Recon</h2><p>Finding nothing: all good. [high] hopes</p><ul><li>a</li></ul>")
        self.assertEqual([],self.api.note_findings([plain]))
        self.assertEqual([],self.api.note_findings([self.note("text only","just text, no markup")]))
        self.assertEqual([],self.api.note_findings([self.note("empty note","")]))
        for bad in ([],None,[99999],["x",None,{}],"abc"):self.assertEqual([],self.api.note_findings(bad),repr(bad))
    def test_several_notes_and_sources_counts(self):
        a=self.note("with callouts",CALLOUT,"ACME","web, sqli");b=self.note("generic",GENERIC);c=self.note("plain","<p>x</p>")
        drafts=self.api.note_findings([b,a,a,c])
        self.assertEqual([b]*4+[a]*2,[d["note_id"] for d in drafts])
        self.assertEqual(2,len(self.api.note_findings(a)))
        notes={n["id"]:n for n in self.api.sources()["notes"]}
        self.assertEqual((2,4,0),(notes[a]["findings"],notes[b]["findings"],notes[c]["findings"]))
        self.assertEqual(("with callouts","ACME",["web","sqli"]),(notes[a]["name"],notes[a]["group"],notes[a]["tags"]))
    def test_command_cards_and_images_inside_a_finding(self):
        token=notes_service._encode_cmd_data({"cmd_note_title":"sqlmap","command":"sqlmap -u 'http://t/?id=1' --batch"})
        url="data:image/png;base64,"+base64.b64encode(png(6,6)).decode()
        nid=self.note("cards",f'<div data-callout="finding" data-sev="high"><h3>SQLi</h3><h4>Steps to reproduce</h4><p>Run:</p><a href="cmd:edit:{token}"><img src="cmdcard:{token}" alt="x"></a><figure class="note-embed" data-attachment-id="abc"><img src="{url}" alt="proof.png"></figure></div>')
        d=self.api.note_findings([nid])[0]
        uid=reports.add_asset("x",png(6,6))["uid"]
        self.assertEqual(f'<p>Run:</p><pre>sqlmap -u \'http://t/?id=1\' --batch</pre><p><img src="rptasset:{uid}" alt="proof.png"></p>',d["steps"])
class NoteContentTests(NotesBase):
    def test_conversion_to_the_rich_subset(self):
        token=notes_service._encode_cmd_data({"cmd_note_title":"Port scan","category":"Recon","command":"nmap -sV -p- <TARGET> && echo done"})
        legacy=notes_service._encode_cmd_data({"command":"whoami"})
        link=notes_service._encode_note_link_data({"id":1,"note_name":"Other"}) if hasattr(notes_service,"_encode_note_link_data") else "x"
        nid=self.note("Mixed",'<h1>Title</h1><h2 style="color:red">Sub</h2><div>plain line</div><div>next line</div>'
            f'<p>Before <a href="cmd:edit:{token}"><img src="cmdcard:{token}" alt="c"></a> after</p><img src="cmdcard:{legacy}">'
            f'<p>See <a href="notelink:{link}">Other note</a> and <a href="https://example.com/x">site</a><script>alert(1)</script></p>'
            '<pre class="note-code" data-lang="bash">ls -la\n  cat x</pre><span class="note-secret">hunter2</span>'
            '<img src="https://evil.example/track.png" alt="remote"><img src="file:///etc/passwd.png" alt="outside">'+CALLOUT)
        out=self.api.note_content(nid)
        self.assertEqual({"name","html"},set(out));self.assertEqual("Mixed",out["name"])
        h=out["html"]
        self.assertEqual(h,reports.sanitize_html(h))
        self.assertTrue(h.startswith("<h3>Title</h3><h3>Sub</h3>plain line<br>next line<br><p>Before </p><p><strong>Port scan</strong></p><pre>nmap -sV -p- &lt;TARGET&gt; &amp;&amp; echo done</pre> after<pre>whoami</pre>"),h[:300])
        self.assertIn('<p>See Other note and <a href="https://example.com/x">site</a></p>',h)
        self.assertIn('<pre data-lang="bash">ls -la\n  cat x</pre>',h);self.assertIn('<span class="rpt-redact">hunter2</span>',h)
        self.assertIn("[Image: remote]",h);self.assertIn("[Image: outside]",h)
        self.assertIn('<div class="note-callout note-finding" data-callout="finding" data-sev="high"><h3>SQL injection in login form</h3><table class="note-table note-table-head"><tbody><tr><th>Severity</th><td>High</td></tr>',h)
        self.assertIn('<div class="note-callout" data-callout="info"><p>Just a note, not a finding.</p></div><div class="note-callout" data-callout="vuln" data-sev="medium" data-cvss="5.3"><p><strong>Directory listing enabled</strong></p>',h)
        self.assertTrue(h.endswith('<div class="note-callout" data-callout="evidence"><pre>uid=0(root)</pre></div>'),h[-200:])
        self.assertIn("<h4>Remediation</h4><p>Use prepared statements.</p>",h)
        for bad in ("<script","alert(1)","cmdcard:","notelink:","onclick","style=","evil.example","/etc/passwd"):self.assertNotIn(bad,h)
    def test_images_become_assets_only_from_the_apps_own_folders(self):
        raw=png(9,9)
        inside=os.path.join(self.dir,"NoteImages");os.makedirs(inside)
        with open(os.path.join(inside,"shot one.png"),"wb") as fh:fh.write(raw)
        with open(os.path.join(inside,"notimage.png"),"wb") as fh:fh.write(b"<html>not an image</html>")
        outside=os.path.join(os.path.dirname(self.dir),"loya_outside_%d.png"%os.getpid())
        with open(outside,"wb") as fh:fh.write(png(8,8))
        try:
            url=lambda p:"file:///"+os.path.abspath(p).replace("\\","/").replace(" ","%20")
            data="data:image/png;base64,"+base64.b64encode(png(5,5)).decode()
            nid=self.note("Shots",f'<figure class="note-embed"><img src="{url(os.path.join(inside,"shot one.png"))}" alt="shot one.png"></figure><p><img src="{data}" alt="pasted"></p><img src="{url(os.path.join(inside,"notimage.png"))}" alt="bad"><img src="{url(outside)}" alt="outside"><img src="{url(os.path.join(inside,"..","..",os.path.basename(outside)))}" alt="traversal"><img src="{url(os.path.join(inside,"missing.png"))}">')
            h=self.api.note_content(nid)["html"]
            a=reports.add_asset("x",raw)["uid"];b=reports.add_asset("x",png(5,5))["uid"]
            self.assertEqual(f'<p><img src="rptasset:{a}" alt="shot one.png"></p><p><img src="rptasset:{b}" alt="pasted"></p>[Image: bad][Image: outside][Image: traversal][Image]',h)
            con=sqlite3.connect(common_db.db_path())
            try:self.assertEqual(2,con.execute("SELECT COUNT(*) FROM ReportAssets").fetchone()[0])
            finally:con.close()
            self.assertEqual(("shot one.png",9,9),tuple(reports.get_asset(a)[k] for k in ("name","width","height")))
        finally:
            os.remove(outside)
    def real_note(self):
        """REAL with its two attachments on disk, the way notes_service stores them (Data/Attachments/<note id>/<id>.png, file://// URL)."""
        folder=os.path.join(notes_service._attachments_root(),"77");os.makedirs(folder,exist_ok=True)
        urls=[]
        for name,raw in (("96bb458d80024dce.png",png(12,7)),("7ad26c2dd1a14262.png",png(20,12))):
            with open(os.path.join(folder,name),"wb") as fh:fh.write(raw)
            urls.append(notes_service._file_url(os.path.join(folder,name)))
        return self.note("Portal assessment",REAL.replace("{SHOT}",urls[0]).replace("{DRAW}",urls[1]))
    def test_blocks_of_the_finished_notes_editor_map_natively(self):
        nid=self.real_note()
        h=self.api.note_content(nid)["html"]
        shot=reports.add_asset("x",png(12,7))["uid"];draw=reports.add_asset("x",png(20,12))["uid"]
        self.assertEqual('<h3>Recon</h3><p>Scan results below.</p><pre data-lang="bash">nmap -sV 10.10.20.5\necho done</pre>'
            '<ul class="note-checklist"><li data-checked="1">Scope confirmed</li><li>Retest IDOR</li></ul>'
            '<div class="note-callout" data-callout="finding" data-sev="high" data-cvss="8.8"><p>SQL injection in login form</p><p>The user parameter is concatenated into the query. CWE-89</p>'
            '<div class="note-callout" data-callout="evidence"><p>sqlmap output</p><pre data-lang="output">uid=0(root) gid=0(root)</pre></div></div>'
            '<div class="note-callout" data-callout="warning"><p>Do not run sqlmap with --risk 3 on production.</p></div>'
            '<div class="note-callout" data-callout="credential"><p><b>Host: </b>10.10.20.5 - SSH</p><p><b>User: </b>svc_backup</p><p><b>Secret: </b><span class="rpt-redact">Summer2026!</span>\xa0</p><p><b>Notes: </b>Found in /opt/backup/run.sh</p></div>'
            '<h3>Loot</h3><p>Password reuse on files01.</p>'
            f'<p><img src="rptasset:{shot}" alt="login-bypass.png"></p><p><img src="rptasset:{draw}" alt="drawing-1.png"></p>',h)
        self.assertEqual(h,reports.sanitize_html(h))
        self.assertEqual((20,12),tuple(reports.get_asset(draw)[k] for k in ("width","height")))
    def test_finding_callout_of_the_finished_editor(self):
        d=self.api.note_findings([self.real_note()])
        self.assertEqual(1,len(d))
        f=d[0]
        self.assertEqual(("SQL injection in login form","high",8.8,"","CWE-89"),(f["title"],f["severity"],f["cvss_score"],f["cvss_vector"],f["cwe"]))
        # The first line is the title only; the evidence callout inside the finding is its proof.
        self.assertEqual("<p>The user parameter is concatenated into the query. CWE-89</p>",f["description"])
        self.assertEqual('<div class="note-callout" data-callout="evidence"><p>sqlmap output</p><pre data-lang="output">uid=0(root) gid=0(root)</pre></div>',f["steps"])
        self.assertEqual(1,{n["id"]:n for n in self.api.sources()["notes"]}[f["note_id"]]["findings"])
    def test_evidence_under_an_explicit_section_stays_there(self):
        nid=self.note("sections",'<div class="note-callout" data-callout="vuln" data-sev="low"><h3>Verbose errors</h3><p>Stack traces are shown.</p><h4>Impact</h4><p>Information leak.</p>'
            '<div class="note-callout" data-callout="evidence"><pre class="note-code">Traceback (most recent call last)</pre></div></div>')
        f=self.api.note_findings([nid])[0]
        self.assertEqual(("Verbose errors","low","<p>Stack traces are shown.</p>",""),(f["title"],f["severity"],f["description"],f["steps"]))
        self.assertEqual('<p>Information leak.</p><div class="note-callout" data-callout="evidence"><pre>Traceback (most recent call last)</pre></div>',f["impact"])
    def test_credential_callouts_are_masked(self):
        conv=lambda markup:self.api.note_content(self.note("cred %d"%len(markup),markup))["html"]
        # Typed by hand, nothing marked: "Password: x" style lines get their value masked.
        self.assertEqual('<div class="note-callout" data-callout="credential"><p>admin@10.0.0.5</p><p><strong>Password: </strong><span class="rpt-redact">P@ss w0rd!</span></p><p>user: bob<br><strong>NTLM hash = </strong><span class="rpt-redact">aad3b435:31d6cfe0</span></p></div>',
            conv('<div class="note-callout" data-callout="credential"><p>admin@10.0.0.5</p><p>Password: P@ss w0rd!</p><p>user: bob<br>NTLM hash = aad3b435:31d6cfe0</p></div>'))
        # Nothing recognisable: the whole content is masked rather than exported in clear.
        self.assertEqual('<div class="note-callout" data-callout="credential"><p><span class="rpt-redact">root / toor</span></p><ul><li><span class="rpt-redact">svc:<b>Winter1</b></span></li></ul></div>',
            conv('<div class="note-callout" data-callout="credential"><p>root / toor</p><p><br></p><ul><li>svc:<b>Winter1</b></li></ul></div>'))
        # A code block inside keeps being a code block; the mark survives in it.
        self.assertEqual('<div class="note-callout" data-callout="credential"><pre data-lang="text">host: dc01\ntoken: <span class="rpt-redact">eyJhbGciOi</span></pre></div>',
            conv('<div class="note-callout" data-callout="credential"><pre class="note-code" data-lang="text">host: dc01<br>token: eyJhbGciOi</pre></div>'))
        # Outside a credential callout nothing is masked on its own.
        self.assertEqual('<div class="note-callout" data-callout="info"><p>Password: policy is 8 characters</p></div>',conv('<div class="note-callout" data-callout="info"><p>Password: policy is 8 characters</p></div>'))
    def test_code_blocks_checklists_and_attachments(self):
        conv=lambda markup:self.api.note_content(self.note("blocks %d"%len(markup),markup))["html"]
        # Tint spans and <br> lines of the note editor are flattened; the language is kept only when it is a plain token.
        self.assertEqual('<pre data-lang="python">import os\nprint(1 &lt; 2)</pre><pre>x</pre><pre>plain</pre>',
            conv('<pre class="note-code" data-lang="python"><span class="note-tok-k">import</span> os<br>print(1 &lt; 2)<br></pre><pre class="note-code" data-lang="bad lang!">x</pre><pre>plain</pre>'))
        self.assertEqual('<ul class="note-checklist"><li>a<ul class="note-checklist"><li data-checked="1">nested</li></ul></li><li data-checked="1">b</li></ul><ul><li>plain</li></ul>',
            conv('<ul class="note-checklist"><li>a<ul class="note-checklist"><li data-checked="1">nested</li></ul></li><li data-checked="1">b</li></ul><ul><li>plain</li></ul>'))
        self.assertEqual("<p>[Attachment: scan.xml 1.2 KB]</p>",conv('<figure class="note-embed note-embed-inline" data-attachment-id="aa" data-kind="file"><div class="note-embed-file"><i class="icon icon-save"></i><span class="note-embed-filename">scan.xml</span> <span class="note-embed-filesize">1.2 KB</span></div></figure>'))
    def test_missing_note(self):
        for bad in (999,"x",None):
            with self.assertRaisesRegex(ValueError,"Note not found."):self.api.note_content(bad)
    def test_empty_note(self):
        self.assertEqual({"name":"Empty","html":""},self.api.note_content(self.note("Empty","")))
if __name__=="__main__":unittest.main()
