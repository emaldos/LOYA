import os
os.environ.setdefault("LOYA_REPORT_PDF_ENGINE","fallback")  # unit tests use the fpdf2 writer; the print engine has its own tests
import os,io,re,csv,json,time,shutil,zipfile,base64,tempfile,subprocess,unittest
import xml.dom.minidom
from _isolate import ROOT,IsolatedData
import _report_fixture as fx
from Cores.Services import report_export as rx
from Cores.Services import report_export_pdf as rpdf
from Cores.Services import report_xlsx
PDFTOTEXT=shutil.which("pdftotext")
def pdf_text(path):
    return subprocess.run([PDFTOTEXT,"-layout",path,"-"],capture_output=True,timeout=60).stdout.decode("utf-8","replace")
class TempDirCase(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.mkdtemp(prefix="loya_rx_")
    def tearDown(self):shutil.rmtree(self.tmp,ignore_errors=True)
    def out(self,name):return os.path.join(self.tmp,name)
class RichParserTests(unittest.TestCase):
    def test_inline_styles_links_and_breaks(self):
        b=rx.parse_rich('<p>Hello <strong>bold <em>both</em></strong> <u>u</u> <s>s</s> <code>c()</code><br>next <a href="https://example.com/x">link</a></p>')
        self.assertEqual(1,len(b));runs=b[0]["runs"]
        self.assertEqual("Hello bold both u s c()\nnext link",rx.runs_text(runs))
        self.assertTrue(any(r.get("b") and r.get("i") and r["text"]=="both" for r in runs))
        self.assertTrue(any(r.get("code") and r["text"]=="c()" for r in runs))
        self.assertEqual("https://example.com/x",[r for r in runs if r.get("href")][0]["href"])
    def test_unsafe_links_and_script_content_are_dropped(self):
        b=rx.parse_rich('<p><a href="javascript:alert(1)">x</a><a href="data:text/html,1">y</a></p><script>alert(1)</script><style>p{}</style><iframe src=x>z</iframe><p onclick="x()">ok</p>')
        text=rx.blocks_text(b)
        self.assertNotIn("alert",text);self.assertNotIn("p{}",text);self.assertIn("ok",text)
        self.assertFalse(any(r.get("href") for blk in b for r in blk.get("runs",[])))
    def test_nested_lists_quote_pre_hr_headings(self):
        b=rx.parse_rich("<h3>T</h3><h4>S</h4><ul><li>a<ul><li>a1</li></ul></li><li>b</li></ul><ol><li>one</li></ol><blockquote><p>q</p></blockquote><pre>l1\n  l2</pre><hr>")
        self.assertEqual(["h","h","list","list","quote","pre","hr"],[x["t"] for x in b])
        self.assertEqual([3,4],[b[0]["level"],b[1]["level"]])
        self.assertEqual("a1",rx.runs_text(b[2]["items"][0]["blocks"][0]["items"][0]["runs"]))
        self.assertTrue(b[3]["ordered"]);self.assertEqual("l1\n  l2",b[5]["text"])
    def test_table_grid_marks_spanned_slots(self):
        b=rx.parse_rich('<table><thead><tr><th>A</th><th>B</th><th>C</th></tr></thead><tbody><tr><td rowspan="2">r</td><td colspan="2">wide</td></tr><tr><td>x</td><td>y</td></tr></tbody></table>')[0]
        self.assertTrue(b["header"]);rows=b["rows"]
        self.assertEqual([3,3,3],[len(r) for r in rows])
        self.assertEqual(2,rows[1][1]["colspan"]);self.assertIsNone(rows[1][2])
        self.assertIsNone(rows[2][0]);self.assertEqual("x",rows[2][1]["text"])
    def test_redaction_never_keeps_the_hidden_text(self):
        b=rx.parse_rich('<p>pw <span class="rpt-redact">hunter2</span> end</p><pre>key=<span class="rpt-redact">abc123</span></pre>')
        dump=json.dumps(b)
        self.assertNotIn("hunter2",dump);self.assertNotIn("abc123",dump)
        self.assertEqual("pw [REDACTED] end",rx.runs_text(b[0]["runs"]));self.assertEqual("key=[REDACTED]",b[1]["text"])
    def test_evidence_figure_snapshot(self):
        b=rx.parse_rich('<figure class="rpt-ev" data-evidence="E1"><figcaption>$ id \u2014 exit 0</figcaption><pre>uid=0(root)</pre></figure>')[0]
        self.assertEqual(("figure","E1","uid=0(root)"),(b["t"],b["evidence"],b["pre"]))
        self.assertIn("$ id",b["caption"])
    def test_hostile_input_never_raises(self):
        for junk in ("<div>"*5000+"deep"+"</div>"*5000,"<p><b><i>unclosed","<table><tr><td colspan='999999' rowspan='x'>a","\x00\x01<p>ctl\x07</p>","<<<>>>&&&","<img src='rptasset:nope'>",None,12345):
            blocks=rx.parse_rich(junk)
            self.assertIsInstance(blocks,list)
        self.assertNotIn("\x07",json.dumps(rx.parse_rich("<p>a\x07b</p>"),ensure_ascii=False))
class PrepareTests(unittest.TestCase):
    def setUp(self):self.doc=rx.prepare(fx.report(),{"redact":True})
    def section(self,kind,doc=None):return [s for s in (doc or self.doc)["sections"] if s["kind"]==kind][0]
    def text(self,kind,doc=None):return rx.blocks_text(self.section(kind,doc)["blocks"])
    def test_sections_ordered_numbered_and_hidden_ones_left_out(self):
        heads=[s["heading"] for s in self.doc["sections"]]
        self.assertEqual("1. Document Control",heads[0]);self.assertEqual("2. Executive Summary",heads[1])
        self.assertEqual(["Appendix A: Tools Used","Appendix B: Commands Run","Appendix C: Timeline","Appendix D: Evidence"],heads[-4:])
        self.assertFalse(any("HIDDENSECTION" in h for h in heads))
        self.assertNotIn("must never be exported",json.dumps([s["blocks"] for s in self.doc["sections"]],default=str))
    def test_unnumbered_and_without_appendices(self):
        doc=rx.prepare(fx.report(),{"number_sections":False,"include_appendices":False})
        self.assertEqual("Document Control",doc["sections"][0]["heading"])
        self.assertFalse(any(s["appendix"] for s in doc["sections"]))
    def test_placeholders_are_substituted_and_unknown_ones_stay(self):
        t=self.text("executive_summary")
        self.assertIn("RedTeam Ltd performed an external penetration test for ACME Corp between 2026-11-16 and 2026-11-20",t)
        self.assertIn("{{nope}}",t)
        self.assertEqual("Confidential \u2014 ACME Corp only",self.doc["banner"])
        self.assertIn("5 findings were identified",self.text("findings_summary"))
    def test_placeholder_values_cannot_inject_markup(self):
        r=fx.report();r["meta"]["client"]="<b>ACME</b> & <script>x</script>"
        t=rx.blocks_text(self.section("executive_summary",rx.prepare(r))["blocks"])
        self.assertIn("<b>ACME</b> & <script>x</script>",t)
    def test_finding_ids_follow_position_and_survive_a_status_filter(self):
        self.assertEqual(["F-01","F-02","F-03","F-04","F-05"],[f["number"] for f in self.doc["findings"]])
        r=fx.report();r["findings"].reverse()
        self.assertEqual("SQL Injection in product catalogue",rx.prepare(r)["findings"][0]["title"])
        doc=rx.prepare(fx.report(),{"findings_status":["retest","fixed"],"finding_id_prefix":"VULN-"})
        self.assertEqual([("VULN-02","retest"),("VULN-03","fixed")],[(f["number"],f["status"]) for f in doc["findings"]])
        self.assertEqual({"critical":0,"high":1,"medium":1,"low":0,"info":0},doc["counts"])
    def test_summary_roadmap_and_document_control_are_generated(self):
        s=self.text("findings_summary")
        for needle in ("Findings by severity","Critical | 1","Findings overview","F-01 | SQL Injection in product catalogue | Critical | 9.8 | Open"):self.assertIn(needle,s)
        self.assertTrue(any(b["t"]=="charts" and b["total"]==5 for b in self.section("findings_summary")["blocks"]))
        road=self.text("remediation_roadmap")
        self.assertLess(road.index("F-01"),road.index("F-05"));self.assertLess(road.index("F-05"),road.index("F-03"))
        self.assertIn("Use parameterised queries.",road)
        dc=self.text("document_control")
        for needle in ("Version history","1.0 issued","Assessment team","Alex Tester | Lead Consultant | alex@redteam.example","Distribution list","Jane Roe (ACME Corp)","Classification | Confidential"):self.assertIn(needle,dc)
    def test_scope_tables_come_from_meta(self):
        s=self.text("scope")
        for needle in ("In scope","10.20.0.0/24","Out of scope","mail.acme.example","No denial-of-service."):self.assertIn(needle,s)
    def test_finding_block_carries_every_field(self):
        t=self.text("findings")
        for needle in ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H","CWE-89","A03:2021 Injection","web01 (https://shop.acme.example/item), 10.20.0.15","Steps to Reproduce","Remediation","References","Retest Notes","Retested 2026-11-22","[Evidence lost capture is no longer available]"):self.assertIn(needle,t)
    def test_evidence_is_redacted_only_when_asked(self):
        self.assertNotIn(fx.SECRET,json.dumps(self.doc["sections"],default=str))
        self.assertIn("AWS_SECRET_ACCESS_KEY=[redacted]",self.text("findings"))
        plain=rx.prepare(fx.report(),{"redact":False})
        self.assertIn(fx.SECRET,self.text("findings",plain))
    def test_ansi_and_control_characters_are_stripped_from_evidence(self):
        t=self.text("appendix_evidence")
        self.assertIn("Nmap done: 1 IP address",t);self.assertNotIn("\x1b",t)
    def test_long_output_is_truncated_in_the_finding_and_kept_in_the_appendix(self):
        fig=[b for b in self.section("findings")["blocks"] if b["t"]=="figure" and b.get("evidence")=="ev-sqlmap"][0]
        self.assertGreater(fig["truncated"],100);self.assertEqual(rx.FIGURE_LINES,len(fig["pre"].split("\n")))
        app=[b for b in self.section("appendix_evidence")["blocks"] if b.get("evidence")=="ev-sqlmap"][0]
        self.assertEqual(0,app["truncated"]);self.assertIn("fetched row 199",app["pre"])
    def test_appendices_are_built_from_referenced_evidence(self):
        cmds=self.text("appendix_commands")
        for needle in ("nmap -sV -p 80,443,8443 10.20.0.15","sudo sqlmap","sudo -l","curl -sI https://shop.acme.example"):self.assertIn(needle,cmds)
        self.assertLess(cmds.index("nmap -sV"),cmds.index("sudo sqlmap"))
        tools=self.text("appendix_tools")
        for needle in ("nmap | 1","sqlmap | 1","curl | 1"):self.assertIn(needle,tools)
        self.assertNotIn("sudo |",tools)
        tl=self.text("appendix_timeline")
        self.assertIn("Screenshot | Admin console reachable without authentication",tl)
        ev=self.section("appendix_evidence")["blocks"]
        self.assertTrue(any(b["t"]=="image" and b.get("asset") for b in ev))
        self.assertTrue(any(b["t"]=="figure" and "HTTP/1.1 200 OK" in b["pre"] for b in ev))
    def test_toc_lists_sections_and_findings(self):
        toc=self.doc["toc"]
        self.assertEqual(len(self.doc["sections"])+5,len(toc))
        self.assertTrue(any(t["level"]==2 and t["text"].startswith("F-01") and t["severity"]=="critical" for t in toc))
    def test_options_resolution(self):
        o=rx.effective_options({"options":{"page_size":"Letter","include_toc":False},"branding":{"show_cover":False}},{"include_toc":True,"findings_status":["open","bogus"]})
        self.assertEqual(("Letter",True,False,["open"]),(o["page_size"],o["include_toc"],o["include_cover"],o["findings_status"]))
        self.assertIsNone(rx.effective_options({},{"findings_status":list(rx.STATUSES)})["findings_status"])
    def test_minimal_and_broken_reports_still_prepare(self):
        for r in ({"title":"x"},{"title":None,"sections":None,"findings":None,"meta":"bad","branding":7,"options":[]},{"sections":[{"kind":"findings"},"junk",{"kind":"zzz","content":5}],"findings":["junk",{"severity":"weird","cvss_score":"abc","affected":"x","references":None,"evidence":[1]}]}):
            doc=rx.prepare(r);self.assertIsInstance(rx.html_from_doc(doc),str)
        with self.assertRaises(ValueError):rx.prepare(None)
    def test_default_filename_is_a_slug_plus_date(self):
        self.assertEqual("ACME-External-Pentest-Report-2026-11-23.pdf",rx.default_filename(fx.report(),"pdf"))
        self.assertEqual("ACME-External-Pentest-Report-2026-11-23.zip",rx.default_filename(fx.report(),"markdown"))
        name=rx.default_filename({"title":"../../etc/passwd <x>","meta":{"report_date":"../x"}},"html")
        self.assertRegex(name,r"^etc-passwd-x-\d{4}-\d{2}-\d{2}\.html$")
        self.assertRegex(rx.default_filename({"title":"   "},"csv"),r"^Report-\d{4}-\d{2}-\d{2}\.csv$")
class HtmlTests(TempDirCase):
    def setUp(self):
        super().setUp();self.html=rx.build_html(fx.report(),{"redact":True})
    def test_self_contained_and_script_free(self):
        low=self.html.lower()
        self.assertNotIn("<script",low);self.assertNotIn("javascript:",low)
        self.assertIn('<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'; font-src data:">',self.html)
        self.assertEqual([],re.findall(r'(?:src|href)="(?!data:|#|https?://|mailto:)[^"]*"',self.html))
        self.assertEqual([],[s for s in re.findall(r'<img[^>]+src="([^"]{0,12})',self.html) if not s.startswith("data:image/")])
        self.assertEqual([],re.findall(r"<[^<>]*\son[a-z]+\s*=",re.sub(r'"[^"]*"','""',low)))
        self.assertNotIn("<link",low);self.assertNotIn("@import",low);self.assertEqual([],re.findall(r"url\((?!data:font/)",low))
    def test_xss_payloads_are_escaped_everywhere(self):
        self.assertIn("Stored XSS &lt;script&gt;alert(1)&lt;/script&gt;&lt;img src=x onerror=alert(2)&gt;",self.html)
        r=fx.report()
        for k in ("client","engagement","classification","version","authors","project_code"):r["meta"][k]=fx.XSS
        for k in ("company","banner","footer","cover_subtitle"):r["branding"][k]=fx.XSS
        r["title"]=fx.XSS;r["branding"]["accent"]='red;}</style><script>alert(1)</script>'
        r["meta"]["testers"]=[{"name":fx.XSS,"role":fx.XSS,"email":fx.XSS}];r["meta"]["scope_in"]=[fx.XSS];r["meta"]["distribution"]=[fx.XSS]
        r["findings"][0].update({"cwe":fx.XSS,"owasp":fx.XSS,"cvss_vector":fx.XSS,"references":[fx.XSS,"javascript:alert(1)"],"retest_notes":fx.XSS,"affected":[{"name":fx.XSS,"value":fx.XSS}],"evidence":[{"evidence_uid":"ev-nmap","caption":fx.XSS}]})
        r["_evidence"][0].update({"title":fx.XSS,"command":fx.XSS,"content":fx.XSS,"target":fx.XSS})
        r["sections"][1]["title"]=fx.XSS
        out=rx.build_html(r).lower()
        self.assertNotIn("<script",out);self.assertNotIn("<img src=x",out);self.assertEqual([],re.findall(r"<[^<>]*\son[a-z]+\s*=",re.sub(r'"[^"]*"','""',out)))
        self.assertNotIn('href="javascript:',out);self.assertIn("--accent:#1f4e79",out)
    def test_structure_cover_toc_anchors_chart(self):
        for needle in ('class="cover"',"Prepared for <b>ACME Corp</b>",'class="toc-h">Contents<','class="dash"','href="#finding-1"','id="finding-1"','id="sec-1"',"<svg","@media print","page-break-before","@page{size:A4"):self.assertIn(needle,self.html)
        self.assertNotIn("hunter2",self.html);self.assertNotIn(fx.SECRET,self.html);self.assertNotIn("HIDDENSECTION",self.html)
        self.assertIn("@page{size:letter",rx.build_html(fx.report(),{"page_size":"Letter"}))
    def test_cover_and_toc_can_be_switched_off(self):
        out=rx.build_html(fx.report(),{"include_cover":False,"include_toc":False})
        self.assertNotIn('class="cover"',out);self.assertNotIn("Table of Contents",out)
    def test_render_writes_the_same_document(self):
        p=rx.render(fx.report(),"html",self.out("r.html"),{"redact":True})
        with open(p,encoding="utf-8") as f:self.assertEqual(self.html,f.read())
class PdfTests(TempDirCase):
    def check_pdf(self,path):
        with open(path,"rb") as f:data=f.read()
        self.assertTrue(data.startswith(b"%PDF-"));self.assertIn(b"%%EOF",data[-64:]);self.assertGreater(len(data),3000)
        return data
    def test_full_report(self):
        doc=rx.prepare(fx.report(),{"redact":True})
        p=self.out("r.pdf");pages=rpdf.write_pdf(doc,p)
        data=self.check_pdf(p);self.assertGreaterEqual(pages,10)
        self.assertIn(b"/Outlines",data);self.assertIn(b"/URI",data)
        self.assertRegex(data,rb"/MediaBox \[0 0 595\.\d+ 841\.\d+\]")
        if not PDFTOTEXT:self.skipTest("pdftotext not installed: structure checked only")
        t=pdf_text(p)
        for needle in ("ACME External Pentest Report","Prepared for ACME Corp","Table of Contents","1. Document Control","F-01","SQL Injection in product catalogue","CONFIDENTIAL","Appendix D: Evidence",f"Page 3 of {pages}","FINDINGS BY SEVERITY","AWS_SECRET_ACCESS_KEY=[redacted]","RedTeam Ltd"):self.assertIn(needle,t)
        for absent in ("hunter2",fx.SECRET,"HIDDENSECTION","{nb}"):self.assertNotIn(absent,t)
    def test_letter_without_cover_or_toc(self):
        p=rx.render(fx.report(),"pdf",self.out("l.pdf"),{"page_size":"Letter","include_cover":False,"include_toc":False,"include_appendices":False})
        data=self.check_pdf(p);self.assertRegex(data,rb"/MediaBox \[0 0 612(\.0+)? 792(\.0+)?\]")
        if PDFTOTEXT:
            t=pdf_text(p);self.assertNotIn("Table of Contents",t);self.assertNotIn("Appendix",t);self.assertIn("Page 1 of",t)
    def test_empty_report(self):
        self.check_pdf(rx.render({"title":"Empty"},"pdf",self.out("e.pdf")))
        self.check_pdf(rx.render({"title":"Empty","sections":[{"kind":"findings","title":"F"},{"kind":"findings_summary","title":"S"}]},"pdf",self.out("e2.pdf"),{"include_cover":False}))
    def torture(self):
        r=fx.report();nasty="Dash \u2014 arrow \u2192 quotes \u201cx\u201d \u4e2d\u6587\u6f22\u5b57 \U0001f600\U0001f512 \u0645\u0631\u062d\u0628\u0627 \u00f1\u00e9\u00fc\u00df \u2022 \u2713 \u2588\u2591 \u200b \ufffd zero\x00ctl\x07 \ud83d tab\there"
        r["title"]=nasty;r["meta"].update({"client":nasty,"classification":nasty,"authors":nasty});r["branding"].update({"company":nasty,"banner":nasty,"footer":nasty})
        f=r["findings"][0];f["title"]=nasty;f["description"]=f"<p>{nasty}</p><pre>{nasty}\n\u250c\u2500\u2510 box</pre><table><tr><th>{nasty}</th></tr><tr><td><code>{nasty}</code></td></tr></table><ul><li>{nasty}</li></ul>"
        f["affected"]=[{"name":nasty,"value":nasty}];f["references"]=[nasty];r["_evidence"][0]["content"]=nasty*40;r["_evidence"][0]["command"]=nasty
        r["sections"][1]["title"]=nasty
        return r
    def test_unicode_torture_with_system_fonts(self):
        p=rx.render(self.torture(),"pdf",self.out("u.pdf"));self.check_pdf(p)
        if PDFTOTEXT and rpdf.find_fonts():self.assertIn("\u00f1\u00e9\u00fc\u00df",pdf_text(p))
    def test_unicode_torture_with_core_fonts_never_crashes(self):
        doc=rx.prepare(self.torture());p=self.out("c.pdf")
        rpdf.write_pdf(doc,p,fonts=None);self.check_pdf(p)
        if PDFTOTEXT:
            t=pdf_text(p);self.assertIn("Dash - arrow -> quotes",t);self.assertIn("\u00f1\u00e9\u00fc\u00df",t)
    def test_export_works_when_no_system_font_is_found(self):
        saved=dict(rpdf._font_cache);rpdf._font_cache.clear();rpdf._font_cache["fonts"]=None
        try:self.check_pdf(rx.render(self.torture(),"pdf",self.out("n.pdf")))
        finally:
            rpdf._font_cache.clear();rpdf._font_cache.update(saved)
    def test_translit_table(self):
        self.assertEqual("a - b -> c \"q\" ... e",rpdf.latin1_safe("a \u2014 b \u2192 c \u201cq\u201d \u2026 \u00e9".replace("\u00e9","e")))
        self.assertEqual("\u00e9?",rpdf.latin1_safe("\u00e9\u4e2d"))
    def test_broken_images_and_pathological_tables_do_not_stop_the_export(self):
        r=fx.report();r["_assets"]["asset-shot"]={"mime":"image/png","name":"x.png","data":b"\x89PNG\r\n\x1a\n"+b"garbage"*20}
        r["sections"][1]["content"]+="<table>"+"".join("<tr>"+"".join(f"<td>{'w'*300}</td>" for _c in range(12))+"</tr>" for _r in range(3))+"</table><p>"+"x"*5000+"</p><pre>"+"y"*5000+"</pre>"
        self.check_pdf(rx.render(r,"pdf",self.out("b.pdf")))
class DocxTests(TempDirCase):
    def test_structure_reads_back(self):
        import docx
        from docx.oxml.ns import qn
        p=rx.render(fx.report(),"docx",self.out("r.docx"),{"redact":True})
        d=docx.Document(p)
        h1=[x.text for x in d.paragraphs if x.style.name=="Heading 1"]
        self.assertEqual("1. Document Control",h1[0]);self.assertIn("6. Detailed Findings",h1);self.assertIn("Appendix D: Evidence",h1)
        h2=[x.text for x in d.paragraphs if x.style.name=="Heading 2"]
        self.assertEqual(5,len(h2));self.assertEqual("F-01  SQL Injection in product catalogue",h2[0])
        self.assertIn("Key observations",[x.text for x in d.paragraphs if x.style.name=="Heading 3"])
        self.assertGreaterEqual(len(d.tables),15)
        cells=[c.text for t in d.tables for row in t.rows for c in row.cells]
        for needle in ("ACME External Pentest Report","Critical","CWE-89","Alex Tester","shop.acme.example","Merged note across both columns"):self.assertIn(needle,cells)
        self.assertGreaterEqual(len(d.inline_shapes),5)
        images=[x for x in d.part.package.iter_parts() if str(x.partname).startswith("/word/media/")]
        self.assertGreaterEqual(len(images),4)
        sec=d.sections[0]
        self.assertTrue(sec.different_first_page_header_footer)
        self.assertIn("RedTeam Ltd\tACME External Pentest Report"," ".join(x.text for x in sec.header.paragraphs))
        self.assertIn("CONFIDENTIAL \u2014 ACME CORP ONLY"," ".join(x.text for x in sec.header.paragraphs))
        foot=sec.footer.paragraphs[0];self.assertIn("Confidential",foot.text);self.assertIn("Page ",foot.text)
        instr=[i.text for i in foot._p.iter(qn("w:instrText"))]
        self.assertEqual(["PAGE","NUMPAGES"],instr)
        body=d.element.xml
        self.assertIn('TOC \\o "1-3" \\h \\z \\u',body);self.assertIn("Update Field",body);self.assertIn('w:anchor="loya_finding_1"',body);self.assertIn('w:name="loya_finding_1"',body)
        self.assertIn("w:updateFields",d.settings.element.xml)
        self.assertEqual(("ACME External Pentest Report","Alex Tester","Confidential"),(d.core_properties.title,d.core_properties.author,d.core_properties.category))
        with zipfile.ZipFile(p) as z:
            self.assertIn("<Company>RedTeam Ltd</Company>",z.read("docProps/app.xml").decode("utf-8"))
            for name in z.namelist():
                if name.endswith((".xml",".rels")):xml.dom.minidom.parseString(z.read(name))
        text="\n".join(x.text for x in d.paragraphs)
        self.assertIn("AWS_SECRET_ACCESS_KEY=[redacted]",text);self.assertNotIn("hunter2",text+" ".join(cells));self.assertNotIn(fx.SECRET,text)
        self.assertTrue(any(x.style.name=="Code Block" for x in d.paragraphs));self.assertTrue(any(x.style.name=="List Bullet" for x in d.paragraphs))
        self.assertAlmostEqual(210,sec.page_width.mm,0);self.assertAlmostEqual(297,sec.page_height.mm,0)
    def test_property_children_are_in_schema_order(self):
        import docx
        from Cores.Services import report_export_docx as dx
        d=docx.Document(rx.render(fx.report(),"docx",self.out("o.docx")))
        for tag in ("pPr","rPr","tblPr","tcPr"):
            order=dx._ORDER[tag]
            for el in d.element.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"+tag):
                names=[dx._local(c) for c in el if dx._local(c) in order]
                self.assertEqual(sorted(names,key=order.index),names,tag)
    def test_ordered_lists_restart_and_letter_size(self):
        import docx
        d=docx.Document(rx.render(fx.report(),"docx",self.out("l.docx"),{"page_size":"Letter","include_cover":False,"include_toc":False}))
        self.assertAlmostEqual(215.9,d.sections[0].page_width.mm,0);self.assertFalse(d.sections[0].different_first_page_header_footer)
        ids=set()
        for p in d.paragraphs:
            if p.style.name=="List Number" and p._p.pPr is not None and p._p.pPr.numPr is not None:ids.add(p._p.pPr.numPr.numId.val)
        self.assertGreaterEqual(len(ids),2)
    def test_unicode_and_control_characters(self):
        import docx
        r=PdfTests.torture(self)
        d=docx.Document(rx.render(r,"docx",self.out("u.docx")))
        self.assertIn("\u4e2d\u6587\u6f22\u5b57 \U0001f600"," ".join(x.text for x in d.paragraphs))
    def test_empty_report(self):
        import docx
        docx.Document(rx.render({"title":"Empty"},"docx",self.out("e.docx")))
class MarkdownJsonTests(TempDirCase):
    def test_markdown_zip_members_and_syntax(self):
        p=rx.render(fx.report(),"markdown",self.out("r.zip"),{"redact":True})
        with zipfile.ZipFile(p) as z:
            names=z.namelist();md=z.read("report.md").decode("utf-8")
            self.assertEqual("report.md",names[0])
            for n in ("assets/asset-logo.png","assets/asset-shot.png","assets/asset-inline.png","assets/severity-chart.png"):
                self.assertIn(n,names);self.assertEqual(b"\x89PNG",z.read(n)[:4])
        for needle in ("# ACME External Pentest Report","## Table of Contents","- [1. Document Control](#sec-1)","| ID | Finding | Severity | CVSS | Status | Affected |","| --- |","```text\n$ sudo sqlmap","![Network diagram](assets/asset-inline.png)","## F-01 SQL Injection in product catalogue","**[REDACTED]**","1. First action","  - Nested point with a [link](<https://owasp.org/Top10/>)","> Overall risk: **High**."):self.assertIn(needle,md)
        self.assertNotIn("<script>alert(1)</script>",md);self.assertIn("\\<script\\>alert(1)\\</script\\>",md)
        self.assertNotIn("hunter2",md);self.assertNotIn(fx.SECRET,md)
        for line in md.split("\n"):
            if line.startswith("| F-") or line.startswith("| [F-"):self.assertEqual(7,len(re.findall(r"(?<!\\)\|",line)),line)
    def test_markdown_fences_survive_backticks(self):
        md,_files=rx.markdown_from_doc(rx.prepare({"title":"t","sections":[{"kind":"custom","title":"S","content":"<pre>a\n```\nb</pre><p><code>x`y</code></p>"}]}))
        self.assertIn("````\na\n```\nb\n````",md);self.assertIn("``x`y``",md)
    def test_json_is_full_fidelity(self):
        p=rx.render(fx.report(),"json",self.out("r.json"),{"redact":True})
        with open(p,encoding="utf-8") as f:data=json.load(f)
        self.assertEqual(("loya-report",1),(data["format"],data["version"]))
        src=fx.report()
        for k in ("title","uid","status","meta","branding","options","sections","findings","versions"):self.assertEqual(src[k],data["report"][k],k)
        self.assertNotIn("_assets",data["report"]);self.assertNotIn("_evidence",data["report"])
        self.assertEqual({"asset-logo","asset-shot","asset-inline"},set(data["assets"]))
        for a in data["assets"].values():
            self.assertEqual("image/png",a["mime"]);self.assertEqual(b"\x89PNG",base64.b64decode(a["data_b64"])[:4])
        self.assertEqual({"ev-nmap","ev-sqlmap","ev-shot","ev-rec"},{e["uid"] for e in data["evidence"]})
        self.assertTrue(all("id" not in e for e in data["evidence"]))
        self.assertEqual(6,len([e for e in data["evidence"] if e["uid"]=="ev-rec"][0]["events"]))
        self.assertIn(fx.SECRET,json.dumps(data["evidence"]))
    def test_bundle(self):
        a=fx.report();b=fx.report();b["uid"]="rep-2";b["title"]="Second"
        p=rx.render_many([a,b],"json",self.out("b.json"))
        with open(p,encoding="utf-8") as f:data=json.load(f)
        self.assertEqual("loya-report-bundle",data["format"]);self.assertEqual(["ACME External Pentest Report","Second"],[r["title"] for r in data["reports"]])
        self.assertEqual(3,len(data["assets"]));self.assertEqual(4,len(data["evidence"]))
        z=rx.render_many([a,b],"csv",self.out("b.zip"))
        with zipfile.ZipFile(z) as zf:self.assertEqual(["ACME-External-Pentest-Report-2026-11-23.csv","Second-2026-11-23.csv"],zf.namelist())
        with self.assertRaises(ValueError):rx.render_many([],"json",self.out("n.json"))
class FindingsTableTests(TempDirCase):
    def test_csv_columns_bom_and_formula_neutralisation(self):
        p=rx.render(fx.report(),"csv",self.out("r.csv"))
        with open(p,"rb") as f:raw=f.read()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        rows=list(csv.reader(io.StringIO(raw.decode("utf-8-sig"),newline="")))
        self.assertEqual(list(rx.FINDING_COLUMNS),rows[0]);self.assertEqual(6,len(rows))
        self.assertEqual(["F-01","SQL Injection in product catalogue","Critical","9.8","CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H","Open","CWE-89","A03:2021 Injection"],rows[1][:8])
        self.assertIn("web01 (https://shop.acme.example/item)\n10.20.0.15",rows[1][8])
        self.assertIn("Use parameterised queries.",rows[1][13]);self.assertIn("https://owasp.org/www-community/attacks/SQL_Injection",rows[1][14])
        self.assertEqual("'=cmd|' /C calc'!A0",rows[3][1]);self.assertEqual("'+SUM(1) formula-looking text",rows[3][10]);self.assertEqual("'-2+3 fix it",rows[3][13])
        self.assertEqual("'=HYPERLINK(\"http://evil\")",rows[2][8])
        for row in rows[1:]:
            for cell in row:self.assertNotIn(cell[:1],("=","+","-","@","\t","\r"),cell[:40])
    def test_csv_safe(self):
        for bad in ("=1+1","+1","-1","@SUM(A1)","\tx","\rx","|x"):self.assertEqual("'"+bad,rx.csv_safe(bad))
        for ok in ("plain","1.5","a=b",""):self.assertEqual(ok,rx.csv_safe(ok))
    def test_csv_respects_the_status_filter(self):
        p=rx.render(fx.report(),"csv",self.out("f.csv"),{"findings_status":["open"]})
        with open(p,encoding="utf-8-sig",newline="") as f:rows=list(csv.reader(f))
        self.assertEqual(["F-01","F-05"],[r[0] for r in rows[1:]])
    def test_xlsx_is_a_well_formed_workbook(self):
        p=rx.render(fx.report(),"xlsx",self.out("r.xlsx"))
        with zipfile.ZipFile(p) as z:
            names=set(z.namelist())
            for n in ("[Content_Types].xml","_rels/.rels","xl/workbook.xml","xl/_rels/workbook.xml.rels","xl/styles.xml","xl/worksheets/sheet1.xml","xl/worksheets/sheet2.xml","docProps/core.xml"):
                self.assertIn(n,names);xml.dom.minidom.parseString(z.read(n))
            sheet=z.read("xl/worksheets/sheet1.xml").decode("utf-8");styles=z.read("xl/styles.xml").decode("utf-8")
        self.assertNotIn("<f>",sheet);self.assertIn('t="inlineStr"',sheet);self.assertIn("=cmd|' /C calc'!A0",sheet)
        self.assertIn('<pane ySplit="1"',sheet);self.assertIn("<autoFilter",sheet);self.assertIn('customWidth="1"',sheet)
        for color in ("FF9B1C1C","FFDC2626","FFF59E0B","FF2563EB","FF6B7280","FF1F4E79"):self.assertIn(color,styles)
        try:import openpyxl
        except ImportError:return
        wb=openpyxl.load_workbook(p);ws=wb["Findings"]
        self.assertEqual(["Findings","Summary"],wb.sheetnames)
        self.assertEqual(list(rx.FINDING_COLUMNS),[c.value for c in ws[1]]);self.assertEqual(6,ws.max_row)
        self.assertTrue(ws["A1"].font.bold);self.assertEqual("FF1F4E79",ws["A1"].fill.fgColor.rgb);self.assertEqual("FF9B1C1C",ws["C2"].fill.fgColor.rgb)
        self.assertEqual(9.8,ws["D2"].value);self.assertEqual("=cmd|' /C calc'!A0",ws["B4"].value);self.assertEqual("s",ws["B4"].data_type)
        self.assertEqual("A2",ws.freeze_panes);self.assertGreater(ws.column_dimensions["B"].width,30)
        self.assertEqual("ACME Corp",wb["Summary"]["B2"].value)
    def test_xlsx_writer_edge_cases(self):
        self.assertEqual(["A","Z","AA","AZ","BA","ZZ","AAA"],[report_xlsx.col_name(i) for i in (0,25,26,51,52,701,702)])
        wb=report_xlsx.Workbook();wb.add_sheet("a/b[c]:*?\\"+"x"*40,[["h\x00\x07<&>",1,2.5,None,True],["x"*40000,"\ud800 \ufffe ok"]])
        p=self.out("e.xlsx");wb.save(p)
        with zipfile.ZipFile(p) as z:
            sheet=z.read("xl/worksheets/sheet1.xml").decode("utf-8");xml.dom.minidom.parseString(sheet)
            book=z.read("xl/workbook.xml").decode("utf-8");xml.dom.minidom.parseString(book)
        self.assertIn("<v>2.5</v>",sheet);self.assertIn("h&lt;&amp;&gt;",sheet);self.assertNotIn("x"*33000,sheet)
        self.assertLessEqual(len(re.search(r'<sheet name="([^"]*)"',book).group(1)),31)
        report_xlsx.Workbook().save(self.out("empty.xlsx"))
    def test_sarif(self):
        p=rx.render(fx.report(),"sarif",self.out("r.sarif"))
        with open(p,encoding="utf-8") as f:s=json.load(f)
        self.assertEqual("2.1.0",s["version"]);self.assertIn("sarif-2.1.0",s["$schema"]);self.assertEqual(1,len(s["runs"]))
        run=s["runs"][0];rules=run["tool"]["driver"]["rules"];res=run["results"]
        self.assertEqual("LOYA NG",run["tool"]["driver"]["name"]);self.assertEqual((5,5),(len(rules),len(res)))
        self.assertEqual(len(rules),len({r["id"] for r in rules}))
        self.assertEqual(["error","error","none","note","note"],[r["level"] for r in res])
        self.assertEqual(["error","error","warning","note","note"],[r["defaultConfiguration"]["level"] for r in rules])
        self.assertEqual("9.8",rules[0]["properties"]["security-severity"]);self.assertNotIn("security-severity",rules[4]["properties"])
        self.assertTrue(rules[0]["id"].startswith("CWE-89/"));self.assertEqual("https://owasp.org/www-community/attacks/SQL_Injection",rules[0]["helpUri"])
        for i,r in enumerate(res):
            self.assertEqual(rules[i]["id"],r["ruleId"]);self.assertEqual(i,r["ruleIndex"]);self.assertTrue(r["message"]["text"])
        self.assertEqual("https://shop.acme.example/item",res[0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"])
        self.assertEqual("10.20.0.15",res[0]["locations"][1]["logicalLocations"][0]["name"])
        self.assertEqual("pass",res[2]["kind"]);self.assertEqual("external",res[3]["suppressions"][0]["kind"])
class DispatcherTests(TempDirCase):
    def test_every_format_renders_and_unknown_ones_are_refused(self):
        for f in rx.FORMATS:
            p=rx.render(fx.report(),f["id"],self.out("all."+f["ext"]));self.assertGreater(os.path.getsize(p),200,f["id"])
        self.assertEqual(["pdf","docx","html","markdown","json","csv","xlsx","sarif"],[f["id"] for f in rx.FORMATS])
        for f in rx.FORMATS:self.assertEqual({"id","label","ext","description"},set(f))
        with self.assertRaises(ValueError):rx.render(fx.report(),"exe",self.out("x.exe"))
        with self.assertRaises(ValueError):rx.render(None,"pdf",self.out("x.pdf"))
    def test_a_failed_render_leaves_no_file_and_keeps_the_old_one(self):
        target=self.out("keep.pdf")
        with open(target,"wb") as f:f.write(b"previous export")
        def boom(path):
            with open(path,"wb") as f:f.write(b"half")
            raise RuntimeError("disk full")
        with self.assertRaises(RuntimeError):rx.atomic_write(target,boom)
        with open(target,"rb") as f:self.assertEqual(b"previous export",f.read())
        self.assertEqual(["keep.pdf"],os.listdir(self.tmp))
        with self.assertRaises(RuntimeError):rx.atomic_write(self.out("new.pdf"),boom)
        self.assertEqual(["keep.pdf"],os.listdir(self.tmp))
    def test_two_hundred_findings_render_in_reasonable_time(self):
        r=fx.big_report(200)
        for fmt,limit in (("html",20),("pdf",90),("docx",120),("xlsx",20),("markdown",20)):
            t=time.time();p=rx.render(r,fmt,self.out("big."+rx.FORMAT_BY_ID[fmt]["ext"]));took=time.time()-t
            self.assertLess(took,limit,f"{fmt} took {took:.1f}s");self.assertGreater(os.path.getsize(p),10000)
        if PDFTOTEXT:
            t=pdf_text(self.out("big.pdf"));self.assertIn("F-200",t);self.assertIn("Finding number 200",t)
    def test_tool_names(self):
        for cmd,tool in (("sudo nmap -sV x","nmap"),("/usr/bin/python3 exploit.py","python3"),("FOO=1 BAR=2 ./linpeas.sh","linpeas"),("proxychains4 -q crackmapexec smb x","crackmapexec"),("C:\\Tools\\Rubeus.exe kerberoast","rubeus"),("","")):
            self.assertEqual(tool,rx.tool_of(cmd),cmd)
class MaskingAndOrderingTests(TempDirCase):
    """Credential masking (default on), the severity-ordered overview, source labels and code-block languages."""
    def secrets_report(self):
        r=fx.report()
        r["findings"][0]["steps"]+='<pre data-lang="bash">mysql -u root --password=Tr0ub4dor&amp;3 shop\nexport API_TOKEN=tok_live_51HxSECRETVALUE</pre><p>Stored password is <span class="rpt-redact">hunter2</span>.</p>'
        return r
    NEEDLES=(fx.SECRET,"Tr0ub4dor","tok_live_51HxSECRETVALUE")
    def test_masking_is_on_by_default_in_every_rendered_format(self):
        self.assertTrue(rx.effective_options(fx.report())["redact"])
        r=self.secrets_report()
        html=rx.build_html(r)
        for n in self.NEEDLES+("hunter2",):self.assertNotIn(n,html)
        self.assertIn("[redacted]",html);self.assertIn('class="redact"',html)
        for fmt in ("markdown","csv","xlsx","sarif","docx","pdf"):
            p=rx.render(r,fmt,self.out("m."+rx.FORMAT_BY_ID[fmt]["ext"]))
            if fmt in ("markdown","xlsx","docx"):
                with zipfile.ZipFile(p) as z:blob=b"".join(z.read(n) for n in z.namelist() if n.endswith((".md",".xml")))
            elif fmt=="pdf":
                if not PDFTOTEXT:continue
                blob=pdf_text(p).encode("utf-8")
            else:
                with open(p,"rb") as f:blob=f.read()
            for n in self.NEEDLES+("hunter2",):self.assertNotIn(n.encode("utf-8"),blob,f"{n} leaked into {fmt}")
    def test_masking_off_keeps_evidence_but_never_the_redaction_marker(self):
        html=rx.build_html(self.secrets_report(),{"redact":False})
        for n in self.NEEDLES:self.assertIn(n,html)
        self.assertNotIn("hunter2",html)
        md,_files=rx.markdown_from_doc(rx.prepare(self.secrets_report(),{"redact":False}))
        self.assertIn("Tr0ub4dor",md);self.assertNotIn("hunter2",md)
    def test_json_backup_is_never_masked(self):
        p=rx.render(self.secrets_report(),"json",self.out("b.json"),{"redact":True})
        with open(p,encoding="utf-8") as f:text=f.read()
        self.assertIn(fx.SECRET,text);self.assertIn("Tr0ub4dor",text);self.assertIn("hunter2",text)
    def summary_rows(self,doc):
        sec=[s for s in doc["sections"] if s["kind"]=="findings_summary"][0]
        t=[b for b in sec["blocks"] if b["t"]=="table"][-1]
        return [[c["text"] for c in row] for row in t["rows"][1:]]
    def test_findings_overview_is_ordered_by_severity_then_cvss(self):
        r=fx.report()
        mk=lambda i,t,sev,score:fx.finding(i,t,sev,cvss_score=score)
        r["findings"]=[mk(1,"low one","low",3.1),mk(2,"high lower","high",7.1),mk(3,"info","info",None),mk(4,"crit","critical",9.1),mk(5,"high upper","high",8.8),mk(6,"medium","medium",5.0),mk(7,"crit top","critical",10.0),mk(8,"high unscored","high",None)]
        doc=rx.prepare(r)
        self.assertEqual(["crit top","crit","high upper","high lower","high unscored","medium","low one","info"],[row[1] for row in self.summary_rows(doc)])
        # the finding IDs still follow the report order, so the table points at the numbers the detailed section uses
        self.assertEqual(["F-07","F-04","F-05","F-02","F-08","F-06","F-01","F-03"],[row[0] for row in self.summary_rows(doc)])
        self.assertEqual(["low one","high lower"],[f["title"] for f in doc["findings"][:2]])
        html=rx.html_from_doc(doc);over=html[html.index("Findings overview"):html.index('id="sec-',html.index("Findings overview"))]
        self.assertLess(over.index("crit top"),over.index("high upper"));self.assertLess(over.index("high unscored"),over.index("low one"))
        md,_f=rx.markdown_from_doc(doc);part=md[md.index("**Findings overview**"):]
        self.assertLess(part.index("crit top"),part.index("| [F-04]"));self.assertLess(part.index("medium"),part.index("low one"))
        rows=rx.finding_rows(doc);self.assertEqual("F-01",rows[0][0])
    def test_command_sources_use_the_app_wording(self):
        self.assertEqual(("Action chain","Quick Run","Commands","Terminal","AI","-"),tuple(rx.source_label(x) for x in ("playbook","snippet","command","terminal","ai","")))
        r=fx.report();r["_evidence"][0]["source"]="playbook";r["_evidence"][1]["source"]="snippet"
        doc=rx.prepare(r)
        sec=[s for s in doc["sections"] if s["kind"]=="appendix_commands"][0];text=rx.blocks_text(sec["blocks"])
        self.assertIn("Action chain",text);self.assertIn("Quick Run",text)
        out=rx.html_from_doc(doc)+rx.markdown_from_doc(doc)[0]
        self.assertNotIn("Playbook",out);self.assertNotIn("playbook",out);self.assertNotIn("Snippet",out)
    def test_code_block_language(self):
        b=rx.parse_rich('<pre data-lang="Python">print(1)</pre><pre data-lang="x&quot; onload=&quot;1">a</pre><pre>plain</pre>')
        self.assertEqual(["python","",""],[x.get("lang") for x in b])
        doc=rx.prepare(dict(fx.report(),sections=[{"id":1,"kind":"custom","title":"Code","content":'<pre data-lang="python">print(1)</pre><pre>plain</pre>',"position":0,"hidden":False,"options":{}}]))
        html=rx.html_from_doc(doc)
        self.assertIn('<span class="lang">python</span><pre data-lang="python">print(1)</pre>',html);self.assertIn("<pre>plain</pre>",html)
        md,_f=rx.markdown_from_doc(doc);self.assertIn("```python\nprint(1)\n```",md);self.assertIn("```\nplain\n```",md)
        rx.render(doc and dict(fx.report(),sections=[{"id":1,"kind":"custom","title":"Code","content":'<pre data-lang="python">print(1)</pre>',"position":0,"hidden":False,"options":{}}]),"pdf",self.out("lang.pdf"))
        if PDFTOTEXT:self.assertIn("PYTHON",pdf_text(self.out("lang.pdf")))
    def test_light_brand_colour_gets_dark_text(self):
        self.assertEqual("#ffffff",rx.on_color("#1f4e79"));self.assertEqual("#111827",rx.on_color("#ffe066"))
        r=fx.report();r["branding"]["accent"]="#ffe066"
        doc=rx.prepare(r);self.assertEqual("#111827",doc["on_accent"]);self.assertNotEqual(doc["accent"],doc["ink"])
        self.assertIn("--on-accent:#111827",rx.html_from_doc(doc))
        for fmt in ("pdf","docx","xlsx"):self.assertGreater(os.path.getsize(rx.render(r,fmt,self.out("light."+fmt))),2000)
        self.assertEqual("#1f2937",rx.SEV_ON["medium"])
    def test_unicode_and_long_tokens_never_break_the_pdf(self):
        r=fx.report()
        r["title"]="Zażółć gęślą jaźń — 日本語 العربية עברית ไทย 😀 \ud83d"
        r["findings"][0]["title"]="Ünïcödé → ✓ ✗ 漢字 "+"A"*400
        r["findings"][0]["description"]="<p>"+"x"*900+" https://example.com/"+"a/"*300+"</p><table><tr><td>"+"W"*300+"</td><td>日本語</td></tr></table><pre>"+"é"*700+"\n\t\x07bell</pre>"
        r["findings"][0]["affected"]=[{"target_id":"","name":"","value":"https://h.example/"+"p"*500}]
        for fonts in ("auto",None):
            doc=rx.prepare(r)
            pages=rpdf.write_pdf(doc,self.out("u.pdf"),fonts=fonts)
            self.assertGreater(pages,5)
            with open(self.out("u.pdf"),"rb") as f:self.assertEqual(b"%PDF",f.read(4))
        for size in ("A4","Letter"):
            p=rx.render(r,"pdf",self.out(size+".pdf"),{"page_size":size})
            if PDFTOTEXT:self.assertIn("Zażółć",pdf_text(p))
    def test_small_tables_and_their_labels_are_not_split_from_each_other(self):
        if not PDFTOTEXT:self.skipTest("pdftotext not installed")
        r=fx.report()
        for s in r["sections"]:
            if s["kind"]=="findings_summary":s["content"]="".join(f"<p>Filler paragraph {i} that pushes the generated tables towards the bottom of the page.</p>" for i in range(24))
        p=rx.render(r,"pdf",self.out("keep.pdf"))
        pages=pdf_text(p).split("\f")
        page=[x for x in pages if "FINDINGS BY SEVERITY" in x][0]
        self.assertIn("Total",page);self.assertIn("Informational",page)
class FakeWindow:
    def __init__(self,path=None):self.path=path;self.calls=[]
    def create_file_dialog(self,kind,directory="",save_filename="",file_types=(),**kw):
        self.calls.append({"kind":kind,"name":save_filename,"types":file_types})
        return self.path
    def create_confirmation_dialog(self,*a,**k):return True
class BridgeExportTests(TempDirCase):
    def setUp(self):
        super().setUp()
        self.iso=IsolatedData();self.iso.start()
        from Cores.Bridge import reports_io_api
        from Cores.Services import reports_service
        self.svc=reports_service
        self.io=reports_io_api.ReportsIOAPI();self.win=FakeWindow();self.io.bind(self.win)
        src=fx.report()
        logo=self.svc.add_asset("logo.png",src["_assets"]["asset-logo"]["data"])["uid"]
        src["branding"]["logo_asset"]=logo
        self.report=self.svc.create_report({"title":src["title"],"template_id":"blank","meta":src["meta"],"branding":src["branding"],"options":src["options"],"sections":src["sections"],"findings":[{k:v for k,v in f.items() if k!="evidence"} for f in src["findings"]]})
    def tearDown(self):
        self.iso.stop();super().tearDown()
    def test_formats(self):
        self.assertEqual(["pdf","docx","html","markdown","json","csv","xlsx","sarif"],[f["id"] for f in self.io.formats()])
    def test_export_every_format_through_the_save_dialog(self):
        for f in self.io.formats():
            self.win.path=self.out("out."+f["ext"])
            p=self.io.export(self.report["id"],f["id"],{"redact":True,"findings_status":["open","retest"]})
            self.assertEqual(self.win.path,p);self.assertGreater(os.path.getsize(p),200)
            self.assertEqual("ACME-External-Pentest-Report-2026-11-23."+f["ext"],self.win.calls[-1]["name"])
            self.assertIn("*."+f["ext"],self.win.calls[-1]["types"][0])
        self.assertEqual(sorted("out."+f["ext"] for f in self.io.formats()),sorted(set(os.listdir(self.tmp))))
    def test_cancelled_dialog_returns_none_and_writes_nothing(self):
        self.win.path=None
        self.assertIsNone(self.io.export(self.report["id"],"pdf"));self.assertEqual([],os.listdir(self.tmp))
    def test_bad_arguments(self):
        with self.assertRaises(ValueError):self.io.export(self.report["id"],"exe")
        with self.assertRaises(ValueError):self.io.export(999999,"pdf")
        with self.assertRaises(ValueError):self.io.preview_html(999999)
        self.assertEqual([],self.win.calls)
    def test_preview_html_uses_the_stored_logo_and_has_no_scripts(self):
        out=self.io.preview_html(self.report["id"],{"page_size":"Letter"})
        self.assertIn("cv-logo",out);self.assertIn("data:image/png;base64,",out);self.assertNotIn("<script",out.lower());self.assertIn("@page{size:letter",out)
        self.assertIn("Content-Security-Policy",out)
    def test_export_many_templates_and_library(self):
        self.win.path=self.out("all.json")
        p=self.io.export_many([],"json")
        with open(p,encoding="utf-8") as f:self.assertEqual(1,len(json.load(f)["reports"]))
        self.assertRegex(self.win.calls[-1]["name"],r"^LOYA-Reports-\d{4}-\d{2}-\d{2}\.json$")
        self.win.path=self.out("all.zip")
        with zipfile.ZipFile(self.io.export_many([self.report["id"]],"html")) as z:self.assertEqual(["ACME-External-Pentest-Report-2026-11-23.html"],z.namelist())
        with self.assertRaises(ValueError):self.io.export_templates()
        self.svc.template_save_from_report(self.report["id"],"My template","desc")
        self.win.path=self.out("tpl.json")
        with open(self.io.export_templates(),encoding="utf-8") as f:data=json.load(f)
        self.assertEqual(("loya-report-templates",["My template"]),(data["format"],[t["name"] for t in data["templates"]]))
        self.win.path=self.out("lib.json")
        with open(self.io.export_library(),encoding="utf-8") as f:data=json.load(f)
        self.assertEqual("loya-report-library",data["format"]);self.assertGreaterEqual(len(data["entries"]),20)
    def test_export_prefs_round_trip_next_to_the_report_defaults(self):
        self.assertEqual({},self.io.export_prefs_get())
        out=self.io.export_prefs_set({"format":"docx","include_cover":False,"redact":True,"findings_status":["fixed","open","bogus"],"junk":1})
        self.assertEqual({"format":"docx","include_cover":False,"redact":True,"findings_status":["open","fixed"]},out)
        self.svc.defaults_set({"default_format":"html","classification":"Secret"})
        self.assertEqual(out,self.io.export_prefs_get())
        self.assertEqual("html",self.svc.defaults_get()["default_format"])
        self.io.export_prefs_set({"format":"exe","redact":"yes"})
        self.assertEqual(out,self.io.export_prefs_get())
    def test_preview_and_export_follow_the_remembered_masking_choice(self):
        f=self.report["findings"][0]
        self.svc.update_finding(f["id"],{"steps":"<pre>curl -H 'Authorization: Bearer abc.def.SECRETTOKEN' https://x</pre>"})
        rid=self.report["id"]
        self.assertNotIn("SECRETTOKEN",self.io.preview_html(rid));self.assertNotIn("SECRETTOKEN",self.io.preview_html(rid,{"page_size":"Letter"}))
        self.assertIn("SECRETTOKEN",self.io.preview_html(rid,{"redact":False}))
        self.io.export_prefs_set({"redact":False})
        self.assertIn("SECRETTOKEN",self.io.preview_html(rid));self.assertNotIn("SECRETTOKEN",self.io.preview_html(rid,{"redact":True}))
        self.io.export_prefs_set({"redact":True})
        self.win.path=self.out("m.html");p=self.io.export(rid,"html",{})
        with open(p,encoding="utf-8") as fh:self.assertNotIn("SECRETTOKEN",fh.read())
        self.win.path=self.out("all.zip");p=self.io.export_many([rid],"html")
        with zipfile.ZipFile(p) as z:self.assertNotIn(b"SECRETTOKEN",z.read(z.namelist()[0]))
        self.win.path=self.out("all.json");p=self.io.export_many([rid],"json")
        with open(p,encoding="utf-8") as fh:self.assertIn("SECRETTOKEN",fh.read())
    def test_locked_database_is_reported_as_locked(self):
        from Cores import common_db
        saved=common_db._LOCKED;common_db._LOCKED=True
        try:
            with self.assertRaises(common_db.DatabaseLocked):self.io.preview_html(self.report["id"])
        finally:common_db._LOCKED=saved
if __name__=="__main__":unittest.main()
