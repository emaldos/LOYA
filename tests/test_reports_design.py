"""Report design: themes and tokens, the subset-v2 rich blocks, the HTML design in its print variants, the small PDF tools
(markers, merge, overlay, links, bookmarks) and the engine selection with its fallback."""
import os
os.environ.setdefault("LOYA_REPORT_PDF_ENGINE","fallback")  # unit tests never start a web engine
import re,io,json,shutil,tempfile,unittest,zipfile
from _isolate import ROOT,IsolatedData
import _report_fixture as fx
from Cores.Services import report_design as rd
from Cores.Services import report_export as rx
from Cores.Services import report_export_html as rh
from Cores.Services import report_pdf_tools as pt
from Cores.Services import report_pdf_native as native
def kinds(blocks):return [b["t"] for b in blocks]
def sec(i,kind,title,content=""):return {"id":i,"uid":f"sx{i}","kind":kind,"title":title,"content":content,"position":i,"hidden":False,"options":{}}
class TempDirCase(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.mkdtemp(prefix="loya_rd_")
    def tearDown(self):shutil.rmtree(self.tmp,ignore_errors=True)
    def out(self,name):return os.path.join(self.tmp,name)
class DesignTokenTests(unittest.TestCase):
    def test_three_themes_with_fonts_cover_styles_and_preview_colours(self):
        th=rd.themes()
        self.assertEqual(["corporate","modern","minimal"],[t["id"] for t in th])
        for t in th:
            self.assertTrue(t["name"] and t["description"])
            self.assertIn("theme",[f["id"] for f in t["fonts"]]);self.assertGreaterEqual(len(t["fonts"]),5)
            self.assertEqual(["band","full","simple"],[c["id"] for c in t["cover_styles"]])
            self.assertIn(t["default_cover_style"],("band","full","simple"))
            for k in ("accent","secondary","text","rule"):self.assertRegex(t["preview"][k],r"^#[0-9a-f]{6}$")
        json.dumps(th)
    def test_resolve_theme_font_cover_and_colour_rules(self):
        d=rd.resolve({})
        self.assertEqual(("corporate","band","#1f4e79"),(d["theme"],d["cover_style"],d["accent"]))
        m=rd.resolve({"theme":"modern","accent":"#1f4e79","secondary":"#5b6770"})
        self.assertEqual(("modern","full","#3b3fd8"),(m["theme"],m["cover_style"],m["accent"]))
        # a colour the author chose always wins; a built-in theme's own colour follows the theme
        self.assertEqual("#aa3300",rd.resolve({"theme":"modern","accent":"#AA3300"})["accent"])
        self.assertEqual("#1f4e79",rd.resolve({"theme":"corporate","accent":"#3b3fd8"})["accent"])
        # per-export overrides beat the stored branding; junk falls back
        o=rd.resolve({"theme":"modern","font":"serif","cover_style":"simple"},{"theme":"minimal","cover_style":"band"})
        self.assertEqual(("minimal","band","serif"),(o["theme"],o["cover_style"],o["font"]))
        j=rd.resolve({"theme":"<x>","font":"../../etc","cover_style":"7","accent":"red;}"})
        self.assertEqual(("corporate","theme","band","#1f4e79"),(j["theme"],j["font"],j["cover_style"],j["accent"]))
    def test_text_colours_meet_contrast(self):
        for t in rd.THEME_IDS:
            d=rd.resolve({"theme":t})
            self.assertGreaterEqual(rd.contrast(d["text"],"#ffffff"),7.0)
            self.assertGreaterEqual(rd.contrast(d["ink"],"#ffffff"),4.5)
            self.assertGreaterEqual(rd.contrast(d["on_accent"],d["accent"]),4.5)
            self.assertGreaterEqual(rd.contrast(d["muted"],"#ffffff"),4.5)
        for s in rd.SEVERITIES:
            self.assertGreaterEqual(rd.contrast(rd.SEV_ON[s],rd.SEV_COLORS[s]),4.5,s)
            self.assertGreaterEqual(rd.contrast(rd.SEV_INK[s],rd.SEV_TINTS[s]),4.5,s)
        light=rd.resolve({"accent":"#ffe066"})
        self.assertEqual("#111827",light["on_accent"]);self.assertGreaterEqual(rd.contrast(light["ink"],"#ffffff"),4.5)
    def test_bundled_fonts_exist_are_renamed_and_licensed(self):
        from fontTools.ttLib import TTFont
        self.assertTrue(os.path.isfile(os.path.join(rd.FONT_DIR,"LICENSE.txt")))
        for fam in ("sans","text","serif","mono"):
            for st,name in rd.FAMILIES[fam]["files"].items():
                p=os.path.join(rd.FONT_DIR,name);self.assertTrue(os.path.isfile(p),p)
                self.assertLess(os.path.getsize(p),160*1024,name)
                f=TTFont(p);family=f["name"].getDebugName(1)
                # subsets are modified versions: the OFL's reserved names (Lato, Liberation) must not be used
                self.assertTrue(family.startswith("LOYA Report"),family)
                cmap=f.getBestCmap()
                for ch in "Aa0\u00e9\u0105\u0416\u03a9\u2014":self.assertIn(ord(ch),cmap,(name,ch))
        mono=TTFont(rd.font_path("mono","")).getBestCmap()
        for ch in "\u2500\u2502\u2514\u2588":self.assertIn(ord(ch),mono)
        files=rd.font_files(rd.resolve({"theme":"modern"}))
        self.assertTrue(files["body"][""].endswith("LoyaSans-Regular.ttf") and files["mono"]["B"].endswith("LoyaMono-Bold.ttf"))
        self.assertEqual({},rd.font_files(rd.resolve({"font":"system"}))["body"])
    def test_font_face_css_embeds_only_what_the_document_uses(self):
        css=rd.font_face_css(rd.resolve({"theme":"corporate"}))
        self.assertEqual(3+3+2,css.count("@font-face"));self.assertNotIn("http",css);self.assertEqual(css.count("@font-face"),css.count("url(data:font/"))
        self.assertEqual("",rd.font_face_css(rd.resolve({}),embed=False))
        self.assertEqual(2,rd.font_face_css(rd.resolve({"font":"system"})).count("@font-face"))
        self.assertEqual(4+2,rd.font_face_css(rd.resolve({"theme":"modern"}),black=True).count("@font-face"))
class BrandingServiceTests(unittest.TestCase):
    def test_branding_keeps_only_known_design_ids(self):
        from Cores.Services import reports_service as svc
        b=svc._norm_branding({"theme":"modern","font":"serif-head","cover_style":"simple"})
        self.assertEqual(("modern","serif-head","simple"),(b["theme"],b["font"],b["cover_style"]))
        b=svc._norm_branding({"theme":"<script>","font":"x","cover_style":"y"})
        self.assertEqual(("corporate","theme",""),(b["theme"],b["font"],b["cover_style"]))
        self.assertEqual("corporate",svc._norm_branding({})["theme"])
class SubsetV2Tests(unittest.TestCase):
    def test_callouts_with_severity_cvss_and_title(self):
        b=rx.parse_rich('<div class="note-callout note-finding" data-callout="finding" data-sev="high" data-cvss="8.1"><h3>Weak ACL</h3><p>text</p></div><div class="note-callout" data-callout="warning"><p>Out of scope</p></div><div class="note-callout" data-callout="bogus" data-sev="high"><p>x</p></div>')
        self.assertEqual(["callout","callout","callout"],kinds(b))
        self.assertEqual(("finding","high","8.1","Weak ACL"),(b[0]["kind"],b[0]["sev"],b[0]["cvss"],b[0]["title"]))
        self.assertEqual("Finding · High · CVSS 8.1: Weak ACL",rx.callout_head(b[0]))
        self.assertEqual(("warning","","Warning"),(b[1]["kind"],b[1]["sev"],b[1]["label"]))
        self.assertEqual(("info",""),(b[2]["kind"],b[2]["sev"]))
        self.assertEqual("",rx.parse_rich('<div class="note-callout" data-callout="vuln" data-cvss="99"><p>x</p></div>')[0]["cvss"])
    def test_credential_callouts_are_masked_by_default(self):
        src='<div class="note-callout" data-callout="credential"><p><b>Host: </b>10.10.10.5 - SMB</p><p><b>Secret: </b><span class="note-secret">P@ssw0rd!</span></p></div>'
        on=rx.prepare(dict(fx.report(),sections=[sec(1,"custom","C",src)]),{"redact":True})
        html=rx.html_from_doc(on)
        self.assertNotIn("P@ssw0rd!",html);self.assertNotIn("10.10.10.5",html);self.assertIn("Host:",html);self.assertIn('class="redact"',html)
        off=rx.html_from_doc(rx.prepare(dict(fx.report(),sections=[sec(1,"custom","C",src)]),{"redact":False}))
        self.assertIn("10.10.10.5 - SMB",off)
        # a masked secret never prints, whatever the option says
        self.assertNotIn("P@ssw0rd!",off);self.assertNotIn("P@ssw0rd!",rx.blocks_text(rx.parse_rich(src)))
    def test_checklists_code_language_and_ordered_start(self):
        b=rx.parse_rich('<ul class="note-checklist"><li data-checked="1">done</li><li>open</li></ul><ul><li>\u2611 a</li><li>\u2610 b</li><li>[x] c</li></ul><ul><li>plain</li><li>\u2610 not all</li></ul><ol start="4"><li>four</li></ol><pre data-lang="bash">ls -la</pre><pre data-lang="<x>">x</pre>')
        self.assertEqual([True,False],[it["checked"] for it in b[0]["items"]]);self.assertTrue(b[0]["check"])
        self.assertEqual([(True,"a"),(False,"b"),(True,"c")],[(it["checked"],rx.runs_text(it["runs"])) for it in b[1]["items"]])
        self.assertFalse(b[2].get("check"));self.assertEqual(4,b[3]["start"])
        self.assertEqual(("bash",""),(b[4]["lang"],b[5]["lang"]))
        html=rh._R(rx.prepare(fx.report()),None).blocks(b)
        self.assertEqual(2+3,html.count('class="bx'));self.assertEqual(1+2,html.count('class="bx on"'));self.assertIn('<ol start="4">',html);self.assertIn('<span class="lang">bash</span>',html)
        # the basic writers get the box as text
        self.assertEqual("\u2611 done",rx.runs_text(rx.legacy_blocks(b)[0]["items"][0]["runs"]))
    def test_figures_command_cards_embeds_and_widths(self):
        r=fx.report()
        src='<figure class="rpt-cmd" data-type="Linux Shell" data-cat="Recon" data-sub="Ports"><figcaption>Full TCP scan</figcaption><p>Scan all ports.</p><pre>nmap -p- 10.0.0.5</pre></figure>'\
            '<figure class="note-embed note-align-center" data-kind="image" data-asset="asset-shot" data-shapes="eyJ2IjoxfQ"><img src="rptasset:asset-shot" alt="Login page" data-width="420px"></figure>'\
            '<figure class="rpt-cmd" data-type="<img>"><pre>id</pre></figure><p><img src="rptasset:asset-shot" alt="shot.png" data-width="50"></p>'
        doc=rx.prepare(dict(r,sections=[sec(1,"custom","C",src)]))
        b=doc["sections"][0]["blocks"]
        self.assertEqual(["cmd","image","cmd","image"],kinds(b))
        self.assertEqual(("Full TCP scan","Linux Shell","Recon / Ports","nmap -p- 10.0.0.5"),(b[0]["title"],b[0]["kind"],b[0]["category"],b[0]["text"]))
        self.assertEqual("",b[2]["kind"])
        self.assertEqual((420,0,"C",1,"Login page"),(b[1]["px"],b[1]["width"],b[1]["align"],b[1]["fig"],b[1]["caption"]))
        self.assertEqual((0,50,2,""),(b[3]["px"],b[3]["width"],b[3]["fig"],b[3]["caption"]))
        html=rx.html_from_doc(doc)
        self.assertIn("<b>Figure 1</b> \u2014 Login page",html);self.assertIn('class="cmdc"',html);self.assertIn(">Linux Shell</span>",html);self.assertNotIn("data-shapes",html);self.assertNotIn("eyJ2IjoxfQ",html)
        md=rx.markdown_from_doc(doc)[0];self.assertIn("nmap -p- 10.0.0.5",md);self.assertIn("Figure 1 - Login page",md)
    def test_spans_alignment_tables_and_finding_references(self):
        r=fx.report();uid=r["findings"][1]["uid"]
        src=f'<p data-align="center">c <span data-color="#ff0000" data-bg="#00ff00" data-size="20">col</span> <span data-color="red">no</span> <span class="note-ts">[2026-11-23 10:12]</span> see <span class="rpt-fref" data-finding="{uid}">F-99 old title</span> and <span class="rpt-fref" data-finding="gone">F-07 kept text</span> <span class="rpt-ph" data-token="client">{{{{client}}}}</span></p>'\
            '<table class="note-table note-table-head"><tbody><tr><th>Severity</th><td data-align="right">High</td></tr><tr><th>CVSS</th><td>8.1</td></tr></tbody></table>'\
            '<table><tr><td data-width="100">a</td><td data-width="300">b</td></tr></table>'
        doc=rx.prepare(dict(r,sections=[sec(1,"custom","C",src)]+[s for s in r["sections"] if s["kind"]=="findings"]))
        b=doc["sections"][0]["blocks"]
        self.assertEqual("C",b[0]["align"])
        runs=b[0]["runs"];col=[x for x in runs if x.get("color")][0]
        self.assertEqual(("#ff0000","#00ff00",20,"col"),(col["color"],col["bg"],col["size"],col["text"]))
        self.assertFalse(any(x.get("color")=="red" for x in runs));self.assertTrue(any(x.get("muted") for x in runs))
        f=doc["findings"][1];ref=[x for x in runs if x.get("fref")==uid][0]
        self.assertEqual((f"{f['number']} {f['title']}","#"+f["anchor"]),(ref["text"],ref["link"]))
        self.assertEqual("F-07 kept text",[x for x in runs if x.get("fref")=="gone"][0]["text"])
        self.assertIn("ACME Corp",rx.runs_text(runs));self.assertNotIn("{{",rx.runs_text(runs))
        self.assertTrue(b[1]["kv"]);self.assertEqual("R",b[1]["rows"][0][1]["align"])
        self.assertEqual([0.25,0.75],b[2]["widths"])
        html=rx.html_from_doc(doc)
        self.assertIn('style="color:#ff0000;background:#00ff00;font-size:15.0pt"',html);self.assertIn(f'<a href="#{f["anchor"]}"><strong>',html);self.assertIn('<p class="ac">',html)
    def test_widgets_become_generated_blocks_and_unknown_markup_never_passes_through(self):
        r=fx.report()
        src='<div class="rpt-widget" data-widget="risk_matrix"></div><div class="rpt-widget" data-widget="severity_summary">junk</div><div class="rpt-widget" data-widget="findings_table"></div><div class="rpt-widget" data-widget="commands_run"></div><div class="rpt-widget" data-widget="evil"></div>'\
            '<div class="whatever" style="position:fixed" onclick="x()"><custom-tag>kept text</custom-tag><iframe src="https://x">gone</iframe><svg><script>alert(31337)</script></svg></div>'
        doc=rx.prepare(dict(r,sections=[sec(1,"custom","C",src)]))
        b=doc["sections"][0]["blocks"]
        self.assertEqual(["matrix","table","table"],kinds(b)[:3]);self.assertNotIn("widget",kinds(b))
        self.assertEqual("kept text",rx.blocks_text(b[-1:]))
        html=rx.html_from_doc(doc).lower()
        for bad in ("rpt-widget","junk","<custom-tag","position:fixed","onclick","<iframe","alert(31337)","gone"):self.assertNotIn(bad,html)
        self.assertIn("risk matrix: likelihood by impact",html)
class ModelTests(unittest.TestCase):
    def test_dashboard_overall_risk_and_matrix(self):
        doc=rx.prepare(fx.report())
        ex=[s for s in doc["sections"] if s["kind"]=="executive_summary"][0]["blocks"]
        self.assertEqual("dashboard",ex[0]["t"])
        self.assertEqual(("critical","Critical",5),(ex[0]["overall"],ex[0]["overall_label"],ex[0]["total"]))
        self.assertEqual(sum(ex[0]["by_status"].values()),ex[0]["total"])
        r=fx.report()
        for f in r["findings"]:f["status"]="fixed"
        closed=rx.prepare(r)
        self.assertEqual(("","No open risk"),(closed["overall"],[s for s in closed["sections"] if s["kind"]=="executive_summary"][0]["blocks"][0]["overall_label"]))
        r=fx.report();r["sections"][1]["options"]={"dashboard":False}
        self.assertNotIn("dashboard",kinds([s for s in rx.prepare(r)["sections"] if s["kind"]=="executive_summary"][0]["blocks"]))
        summary=[s for s in doc["sections"] if s["kind"]=="findings_summary"][0]["blocks"]
        mx=[b for b in summary if b["t"]=="matrix"][0]
        self.assertEqual(mx["count"],sum(len(mx["cells"][l][i]) for l in ("low","medium","high") for i in ("low","medium","high")))
        self.assertEqual(len([f for f in doc["findings"] if f["status"]!="fixed"]),mx["count"])
        self.assertEqual("critical",rx.cell_risk("high","high"));self.assertEqual("low",rx.cell_risk("low","low"));self.assertEqual("medium",rx.cell_risk("low","high"))
    def test_likelihood_from_the_author_then_cvss(self):
        f={"likelihood":"low","cvss_vector":"CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H","severity":"critical","raw":{}}
        self.assertEqual(("low","high",False),rx.risk_levels(f))
        f["likelihood"]="";self.assertEqual(("high","high",True),rx.risk_levels(f))
        f["cvss_vector"]="CVSS:3.1/AV:L/AC:H/PR:H/UI:R/S:U/C:L/I:N/A:N";f["severity"]="low";self.assertEqual(("low","low",True),rx.risk_levels(f))
        f["raw"]={"impact_level":"HIGH"};self.assertEqual("high",rx.risk_levels(f)[1])
    def test_new_section_kinds(self):
        r=fx.report()
        r["meta"]["schedule"]={"milestones":[{"id":"b","key":"handover","label":"Hand-over","date":"2026-12-01","done":False,"notes":"<b>n</b>"},{"id":"a","key":"kickoff","label":"Kick-off","date":"2026-11-02","done":True},{"id":"c","key":"custom","label":"","date":"junk"}]}
        r["sections"]=[sec(1,"risk_matrix","Risk Matrix","<p>intro</p>"),sec(2,"attack_narrative","Attack Narrative","<h4>1. Initial access</h4><p>story</p>"),sec(3,"project_timeline","Project Timeline",""),sec(4,"brand_new_kind","Future","<p>plain</p>"),sec(5,"findings_summary","Summary","")]
        doc=rx.prepare(r);s=doc["sections"]
        self.assertEqual(["p","matrix"],kinds(s[0]["blocks"]));self.assertEqual(["h","p"],kinds(s[1]["blocks"]));self.assertEqual(["p"],kinds(s[3]["blocks"]))
        tl=s[2]["blocks"][0]
        self.assertEqual(["Kick-off","Hand-over","Milestone"],[m["label"] for m in tl["items"]])
        self.assertEqual(["2 November 2026","1 December 2026","To be agreed"],[m["date"] for m in tl["items"]])
        # the dedicated section owns the matrix: the summary does not repeat it
        self.assertNotIn("matrix",kinds(s[4]["blocks"]))
        html=rx.html_from_doc(doc)
        self.assertIn('class="tl"',html);self.assertIn("&lt;b&gt;n&lt;/b&gt;",html);self.assertIn("Kick-off",html)
        r["meta"]["schedule"]={"milestones":[]}
        self.assertIn("No milestones have been scheduled",rx.blocks_text(rx.prepare(r)["sections"][2]["blocks"]))
        text=rx.blocks_text(rx.legacy_blocks(s[0]["blocks"]+s[2]["blocks"]))
        self.assertIn("High likelihood",text);self.assertIn("Kick-off | 2 November 2026 | Completed",text)
    def test_roadmap_priorities_and_commands_grouped_by_source(self):
        doc=rx.prepare(fx.report())
        road=[s for s in doc["sections"] if s["kind"]=="remediation_roadmap"][0]["blocks"][-1]
        self.assertEqual(["Priority","ID","Finding","Severity","Recommended action","Target","Status"],[c["text"] for c in road["rows"][0]])
        self.assertEqual(("P1","Immediate"),(road["rows"][1][0]["text"],road["rows"][1][5]["text"]))
        closed=[row for row in road["rows"][1:] if row[5]["text"]=="Closed"]
        self.assertTrue(closed and all(row[0]["text"]=="-" for row in closed));self.assertEqual(closed,road["rows"][-len(closed):])
        r=fx.report()
        r["_evidence"]=[{"uid":"e1","kind":"command","command":"nmap -sV h","source":"terminal","started_at":"2026-11-10T09:00:00Z","content":"x","meta":{}},
            {"uid":"e2","kind":"command","command":"whoami","source":"playbook","started_at":"2026-11-10T10:00:00Z","content":"x","meta":{}},
            {"uid":"e3","kind":"command","command":"id","source":"snippet","started_at":"2026-11-10T11:00:00Z","content":"x","meta":{}}]
        r["findings"][0]["evidence"]=[{"evidence_uid":u,"asset_uid":"","caption":""} for u in ("e1","e2","e3")]
        r["sections"]=[s for s in r["sections"] if s["kind"]=="findings"]+[sec(90,"appendix_commands","Commands Run",""),sec(91,"appendix_evidence","Evidence","")]
        doc=rx.prepare(r)
        cmds=[s for s in doc["sections"] if s["kind"]=="appendix_commands"][0]["blocks"]
        self.assertEqual(["Terminal (1)","Action chain (1)","Quick Run (1)"],[b["text"] for b in cmds if b["t"]=="label" and not b["text"].startswith("Other")])
        ev=[s for s in doc["sections"] if s["kind"]=="appendix_evidence"][0]["blocks"]
        self.assertEqual("Evidence index",ev[0]["text"]);self.assertEqual(["E-01","E-02","E-03"],[row[0]["text"] for row in ev[1]["rows"][1:4]])
        # appendix dumps keep their E-numbers; figures are numbered in the body only
        self.assertFalse(any(b.get("fig") for b in ev));self.assertGreaterEqual(doc["figures"],3)
class HtmlDesignTests(unittest.TestCase):
    def setUp(self):self.report=fx.report()
    def html(self,options=None,mode=None):return rh.render(rx.prepare(self.report,options),mode)
    def test_every_theme_and_cover_style_renders_script_free(self):
        for theme in rd.THEME_IDS:
            for cover in rd.COVER_IDS:
                html,marks=self.html({"theme":theme,"cover_style":cover,"embed_fonts":True})
                self.assertIn(f'class="t-{theme} cs-{cover}"',html);self.assertEqual([],marks)
                low=html.lower()
                self.assertNotIn("<script",low);self.assertNotIn("javascript:",low);self.assertNotIn("<link",low);self.assertNotIn("@import",low)
                self.assertEqual([],re.findall(r"url\((?!data:font/)",low));self.assertEqual([],re.findall(r"<[^<>]*\son[a-z]+\s*=",re.sub(r'"[^"]*"','""',low)))
                self.assertIn(rx.CSP,html)
                for needle in ('class="cover"','class="toc"','class="dash"','class="fd-top"','class="sv"',"<svg","@page{size:A4","counter(page)"):self.assertIn(needle,html,(theme,cover,needle))
    def test_fonts_are_embedded_on_request_only(self):
        self.assertNotIn("@font-face",self.html()[0])
        self.assertIn("@font-face",self.html({"embed_fonts":True})[0])
        self.assertIn('"LOYA Report Serif",Georgia',self.html()[0])
        sysfont=self.html({"font":"system"})[0]
        self.assertNotIn("LOYA Report Text",sysfont);self.assertNotIn("LOYA Report Serif",sysfont);self.assertIn('--fb:"Segoe UI"',sysfont)
        self.assertIn("@font-face",self.html(None,{"engine":"webkit","part":"body"})[0])
    def test_print_variants_split_cover_and_body_and_carry_markers(self):
        doc=rx.prepare(self.report)
        cover,cm=rh.render(doc,{"engine":"webkit","part":"cover"})
        body,bm=rh.render(doc,{"engine":"webkit","part":"body"})
        self.assertIn('class="cover"',cover);self.assertNotIn('class="toc"',cover);self.assertEqual([],cm);self.assertIn("margin:0}",cover)
        self.assertNotIn('class="cover"',body);self.assertIn('class="toc"',body);self.assertIn("zoom:0.9375",body)
        self.assertNotIn("counter(page)",body);self.assertNotIn("classbar",body.split("</style>")[1])
        n=len(doc["toc"])
        self.assertEqual(["toc"]*n+["target"]*n,[m["kind"] for m in bm])
        self.assertEqual([t["anchor"] for t in doc["toc"]]*2,[m["anchor"] for m in bm])
        self.assertEqual(2*n,body.count('<i class="mk"'))
        # every marker colour decodes back to its code
        for m,(g,b) in zip(bm,re.findall(r'class="mk" style="background:#ff([0-9a-f]{2})([0-9a-f]{2})"',body)):
            self.assertEqual(m["code"],pt.marker_code(1.0,int(g,16)/255.0,int(b,16)/255.0))
        chrom,_m=rh.render(doc,{"engine":"chromium","part":"body"})
        self.assertNotIn("zoom:",chrom);self.assertIn("@page{size:210mm 297mm;margin:24mm 18mm 21mm 18mm}",chrom)
        self.assertIn("<thead>",chrom);self.assertIn('class="tw"',body)
        letter,_m=rh.render(rx.prepare(self.report,{"page_size":"Letter"}),{"engine":"chromium","part":"cover"})
        self.assertIn("@page{size:215.9mm 279.4mm;margin:0}",letter)
    def test_user_text_cannot_break_out_of_the_page_rule(self):
        self.report["branding"]["company"]='Evil"} body{display:none} @page{x:"';self.report["title"]="T</style><script>alert(1)</script>"
        html=self.html()[0]
        self.assertNotIn("<script",html.lower());self.assertNotIn('"} body{display:none}',html)
        self.assertIn(r'content:"Evil\22 } body{display:none} @page{x:\22 "',html)
class PdfToolTests(TempDirCase):
    def make(self,name,pages,marker_page=None,y=40):
        from fpdf import FPDF
        pdf=FPDF(unit="pt",format=(300,400));pdf.set_auto_page_break(False)
        for i in range(pages):
            pdf.add_page();pdf.set_font("helvetica","",12);pdf.text(20,y,f"{name} page {i+1}")
            if marker_page==i:
                for k,(x,y) in enumerate(((30,100),(30,250))):
                    pdf.set_fill_color(255,254-(k//12),253-(k%12));pdf.rect(x,y,1.5,1.5,style="F")
        p=self.out(name+".pdf");pdf.output(p)
        return p
    def read(self,p):
        with open(p,"rb") as f:return pt.Reader(f.read())
    def test_object_parser_and_writer_round_trip(self):
        v,i=pt.parse(b"<< /Type /Page /Kids [1 0 R 12 0 R] /N 3 /F -1.50 /S (a\\)b) /H <00FF> /B true /Z null /D << /X 7 >> >> tail")
        self.assertEqual(("Page",[pt.Ref(1),pt.Ref(12)],3,-1.5,True,None,7),(v["Type"],v["Kids"],v["N"],v["F"],v["B"],v["Z"],v["D"]["X"]))
        self.assertEqual((b"(a\\)b)",b"<00FF>"),(bytes(v["S"]),bytes(v["H"])))
        again,_j=pt.parse(pt.dump(v));self.assertEqual(v,again)
        self.assertEqual(b"<FEFF00C4>",pt.text_string("\u00c4"))
        with self.assertRaises(pt.PdfError):pt.Reader(b"not a pdf")
    def test_markers_are_found_with_their_position(self):
        rd_=self.read(self.make("m",2,marker_page=1));pages=rd_.pages()
        self.assertEqual([],pt.find_markers(rd_.page_content(pages[0][1])))
        found=pt.find_markers(rd_.page_content(pages[1][1]))
        self.assertEqual([0,1],[f[0] for f in found])
        self.assertAlmostEqual(30,found[0][1],delta=0.5);self.assertAlmostEqual(400-100-1.5,found[0][2],delta=0.6);self.assertAlmostEqual(400-250-1.5,found[1][2],delta=0.6)
        # colours outside the marker palette, big rectangles and text that looks like operators are ignored
        self.assertEqual([],pt.find_markers(b"q 1 1 1 rg 10 10 1 1 re f Q q 1 .9961 .9922 rg 0 0 200 200 re f Q (1 .9961 .9922 rg 5 5 1 1 re) Tj"))
        self.assertEqual([(0,15.0,25.0)],[(c,round(x,3),round(y,3)) for c,x,y in pt.find_markers(b"q 2 0 0 2 5 5 cm 1 .9961 .9922 RG 1 .9961 .9922 rg /G3 gs EMC /P <</MCID 3 >>BDC 5 10 1 1 re f Q")])
    def test_assemble_merges_stamps_links_and_bookmarks(self):
        a=self.read(self.make("cover",2));b=self.read(self.make("body",3));ov=self.read(self.make("stamp",4,y=300))
        out=self.out("final.pdf")
        n=pt.assemble(out,[(a,[0]),(b,[0,1,2])],ov,[{"page":1,"rect":[10,10,200,30],"to":3,"top":380}],
            [{"title":"1. Intro \u00e4","page":1,"top":390,"level":1},{"title":"F-01  Child","page":2,"top":300,"level":2},{"title":"2. Next","page":3,"top":390,"level":1}],{"Title":"Report \u00fc","Author":"me"})
        self.assertEqual(4,n)
        r=self.read(out);pages=r.pages();self.assertEqual(4,len(pages))
        texts=[r.page_content(p) for _n,p in pages]
        self.assertIn(b"cover page 1",texts[0]);self.assertIn(b"body page 3",texts[3]);self.assertNotIn(b"cover page 2",b"".join(texts))
        for i,(_n,p) in enumerate(pages):
            xo=r.res(r.res(p["Resources"])["XObject"]);self.assertIn("LoyaOv",xo)
            form=r.res(xo["LoyaOv"]);self.assertIn(f"stamp page {i+1}".encode(),r.decode(form))
            self.assertTrue(texts[i].startswith(b"q\n"));self.assertIn(b"/LoyaOv Do",texts[i])
        ann=r.res(r.res(pages[1][1]["Annots"])[0])
        self.assertEqual(("Link",pt.Ref(pages[3][0])),(ann["Subtype"],ann["Dest"][0]))
        cat=r.res(r.trailer["Root"]);ol=r.res(cat["Outlines"]);first=r.res(ol["First"])
        self.assertEqual(2,ol["Count"]);self.assertEqual(pt.text_string("1. Intro \u00e4"),bytes(pt.dump(first["Title"])))
        self.assertEqual(pt.Ref(pages[2][0]),r.res(first["First"])["Dest"][0]);self.assertNotIn("Prev",first);self.assertIn("Next",first)
        self.assertEqual(pt.text_string("Report \u00fc"),bytes(pt.dump(r.res(r.trailer["Info"])["Title"])))
        pdftotext=shutil.which("pdftotext")
        if pdftotext:
            import subprocess
            text=subprocess.run([pdftotext,out,"-"],capture_output=True,timeout=60).stdout.decode("utf-8","replace")
            for needle in ("cover page 1","body page 1","body page 3","stamp page 4"):self.assertIn(needle,text)
    def test_stamp_overlay_draws_furniture_and_contents_numbers(self):
        doc=rx.prepare(fx.report(),{"theme":"modern"})
        st=native._Stamp(doc,[(595.0,842.0)]*3)
        st.page(0,3,"",[],False);st.page(1,3,"Contents",[(200.0,"7",True),(220.0,"12",False)]);st.page(2,3,"Executive Summary",[])
        p=self.out("stamp.pdf")
        with open(p,"wb") as f:f.write(st.output())
        r=self.read(p);pages=r.pages();self.assertEqual(3,len(pages))
        self.assertTrue(pt._BLANK_RX.fullmatch(r.page_content(pages[0][1])))
        self.assertFalse(pt._BLANK_RX.fullmatch(r.page_content(pages[1][1])))
        pdftotext=shutil.which("pdftotext")
        if pdftotext:
            import subprocess
            text=subprocess.run([pdftotext,"-layout",p,"-"],capture_output=True,timeout=60).stdout.decode("utf-8","replace")
            for needle in ("REDTEAM LTD","CONTENTS","EXECUTIVE SUMMARY","CONFIDENTIAL","02","/ 03","12"):self.assertIn(needle,text)
class EngineSelectionTests(TempDirCase):
    def test_service_default_is_the_basic_writer_and_auto_falls_back(self):
        res={};p=rx.render(fx.report(),"pdf",self.out("a.pdf"),{"_result":res})
        self.assertEqual("fallback",res["engine"]);self.assertGreater(os.path.getsize(p),2000)
        old=os.environ.get("LOYA_REPORT_PDF_ENGINE");os.environ["LOYA_REPORT_PDF_ENGINE"]="fallback"
        try:
            self.assertEqual("",native.engine())
            res={};p=rx.render(fx.report(),"pdf",self.out("b.pdf"),{"pdf_engine":"auto","_result":res,"theme":"minimal"})
            self.assertEqual("fallback",res["engine"]);self.assertTrue(res["reason"]);self.assertGreater(os.path.getsize(p),2000)
            with self.assertRaises(ValueError):rx.render(fx.report(),"pdf",self.out("c.pdf"),{"pdf_engine":"native"})
            self.assertFalse(os.path.exists(self.out("c.pdf")));self.assertEqual(["a.pdf","b.pdf"],sorted(os.listdir(self.tmp)))
        finally:
            if old is None:os.environ.pop("LOYA_REPORT_PDF_ENGINE",None)
            else:os.environ["LOYA_REPORT_PDF_ENGINE"]=old
    def test_basic_writers_take_every_theme_and_the_new_blocks(self):
        r=fx.report()
        r["sections"].insert(1,sec(50,"risk_matrix","Risk Matrix",'<div class="note-callout" data-callout="warning"><p>Careful</p></div><ul class="note-checklist"><li data-checked="1">done</li></ul><figure class="rpt-cmd"><figcaption>Scan</figcaption><pre>nmap h</pre></figure>'))
        for theme in rd.THEME_IDS:
            for fmt in ("pdf","docx"):
                p=rx.render(r,fmt,self.out(f"{theme}.{fmt}"),{"theme":theme,"cover_style":"simple" if theme=="minimal" else "full"})
                self.assertGreater(os.path.getsize(p),4000,(theme,fmt))
        with zipfile.ZipFile(self.out("minimal.docx")) as z:
            styles=z.read("word/styles.xml").decode("utf-8");body=z.read("word/document.xml").decode("utf-8")
        self.assertIn('w:ascii="Segoe UI"',styles);self.assertIn("WARNING",body);self.assertIn("nmap h",body);self.assertIn("\u2611",body);self.assertIn(">done<",body)
        with zipfile.ZipFile(self.out("corporate.docx")) as z:styles=z.read("word/styles.xml").decode("utf-8")
        self.assertIn('w:ascii="Cambria"',styles)
class BridgeDesignTests(unittest.TestCase):
    def setUp(self):
        self.iso=IsolatedData();self.iso.start()
        from Cores.Bridge.reports_io_api import ReportsIOAPI
        self.io=ReportsIOAPI()
    def tearDown(self):self.iso.stop()
    def test_themes_engine_and_preview_overrides(self):
        from Cores.Services import reports_service as svc
        self.assertEqual(["corporate","modern","minimal"],[t["id"] for t in self.io.themes()])
        self.assertIn(self.io.pdf_engine()["engine"],("webkit","chromium","fallback"))
        r=svc.create_report({"title":"Design test","branding":{"theme":"modern","cover_style":"simple"}})
        self.assertEqual(("modern","simple","theme"),(r["branding"]["theme"],r["branding"]["cover_style"],r["branding"]["font"]))
        html=self.io.preview_html(r["id"])
        self.assertIn('class="t-modern cs-simple"',html);self.assertIn("@font-face",html)
        self.assertIn('class="t-minimal cs-band"',self.io.preview_html(r["id"],{"theme":"minimal","cover_style":"band","font":"serif"}))
        self.assertNotIn("@font-face",self.io.preview_html(r["id"],{"embed_fonts":False}))
        self.assertEqual({"embed_fonts":False},self.io.export_prefs_set({"embed_fonts":False,"theme":"x"}))
        self.assertNotIn("@font-face",self.io.preview_html(r["id"]))
if __name__=="__main__":unittest.main()
