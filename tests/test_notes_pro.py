import os,sys,unittest,base64
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from _isolate import IsolatedData
from Cores.Services import notes_service as ns
from Cores.Services import report_service as rs
from Cores.Bridge import api
PNG=base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
PRO_NOTE=('<h2 data-collapsed="1">Recon</h2><div class="note-callout" data-callout="vuln" data-sev="critical" data-cvss="9.8"><p>Samba RCE</p></div>'
'<pre class="note-code" data-lang="bash">nmap -sV 10.10.10.3\necho "a &lt; b"</pre><ul class="note-checklist"><li data-checked="1">scan</li><li>report</li></ul>'
'<p>Secret: <span class="note-secret">Winter2024!</span> <span class="note-ts">[2026-11-23 21:00]</span></p>'
'<table class="note-table"><tbody><tr><th style="width: 132px;">Port</th><th>Service</th></tr><tr><td>22</td><td>ssh</td></tr></tbody></table>')
class NotesProTest(unittest.TestCase):
    def setUp(self):
        self.iso=IsolatedData();self.dir=self.iso.start()
        self._abs=ns._abs
        ns._abs=lambda *p:os.path.join(self.dir,*(p[1:] if p and p[0]=="Data" else p))
        ns._SETTINGS_CACHE=None;ns._SETTINGS_MTIME=None
        self._stubs=[(api._semantic_svc,"index_note",api._semantic_svc.index_note),(api._semantic_svc,"remove_note",api._semantic_svc.remove_note),(api._targets_svc,"auto_add_target_values",api._targets_svc.auto_add_target_values)]
        for mod,name,_ in self._stubs:setattr(mod,name,lambda *a,**k:0)
        self.api=api.NotesAPI()
    def tearDown(self):
        for mod,name,fn in self._stubs:setattr(mod,name,fn)
        ns._abs=self._abs
        ns._SETTINGS_CACHE=None;ns._SETTINGS_MTIME=None
        self.iso.stop()
    # ---- sanitiser
    def test_sanitize_removes_script_capable_markup(self):
        s=ns.sanitize_note_html
        self.assertEqual(s('<p onclick="x()">a</p>'),'<p >a</p>')
        self.assertEqual(s('<img src=x onerror=alert(1)>'),'<img src=x >')
        self.assertEqual(s('<IMG SRC="a" OnError="x">'),'<IMG SRC="a" >')
        self.assertEqual(s('<script>alert(1)</script><b>ok</b>'),'<b>ok</b>')
        self.assertEqual(s('a<iframe src="x"></iframe>z'),'az')
        self.assertEqual(s('<svg onload=a><circle/></svg>k'),'k')
        self.assertEqual(s('<style>*{display:none}</style>t'),'t')
        self.assertNotIn("javascript",s('<a href="javascript:alert(1)">x</a>'))
        self.assertNotIn("javascript",s("<a href=' JavaScript:alert(1)'>x</a>"))
        self.assertNotIn("onmouseover",s('<p title="a>b" onmouseover=\'x\'>t</p>').lower())
        self.assertNotIn("<meta",s('<meta http-equiv="refresh" content="0;url=http://x">t'))
        self.assertNotIn("srcdoc",s('<div srcdoc="<script>1</script>">t</div>'))
    def test_sanitize_keeps_note_markup_untouched(self):
        s=ns.sanitize_note_html
        tok=ns._encode_cmd_data({"command":"nmap -sV {IP}","cmd_note_title":"scan"})
        card=f'<a href="cmd:edit:{tok}"><img src="cmdcard:{tok}" width="320" height="90" /></a>'
        fig='<figure class="note-embed note-sketch" contenteditable="false" data-attachment-id="abc123abc123abcd" data-kind="sketch" data-shapes="eyJ2IjoxfQ"><img src="file:///d/abc.png" alt="Drawing"></figure>'
        for good in (PRO_NOTE,card,fig,"plain onclick=1 text","<p>1 &lt; 2 and on=x</p>",'<span data-ontology="1" contenteditable="false">x</span>',""):
            self.assertEqual(s(good),good)
        self.assertEqual(s(None),"")
    def test_save_strips_handlers_and_keeps_pro_blocks(self):
        r=self.api.save(None,"Pro",'',PRO_NOTE+'<p onclick="evil()">x</p><script>evil()</script>',[],"")
        got=self.api.get(r["id"])["content_html"]
        self.assertNotIn("onclick",got);self.assertNotIn("<script",got)
        for part in ('data-callout="vuln"','data-sev="critical"','data-cvss="9.8"','class="note-code" data-lang="bash"','data-checked="1"','class="note-secret"','data-collapsed="1"','width: 132px'):
            self.assertIn(part,got)
        self.assertIn('echo "a &lt; b"',got)
        ed=self.api.edit_content(r["id"])["content_html"]
        self.assertIn('class="note-callout"',ed)
        # an unchanged re-save of the same content is still "unchanged"
        self.assertEqual(self.api.save(r["id"],"Pro","",ed,[],"")["action"],"unchanged")
    def test_history_and_restore_keep_pro_blocks(self):
        r=self.api.save(None,"Hist","",PRO_NOTE,[],"")
        self.api.save(r["id"],"Hist","","<p>second</p>",[],"")
        versions=self.api.versions(r["id"])
        self.assertEqual(len(versions),2)
        self.api.restore_version(r["id"],versions[-1]["id"])
        self.assertIn('data-callout="vuln"',self.api.get(r["id"])["content_html"])
    def test_stored_hostile_content_is_cleaned_on_read(self):
        nid,_,_=ns.save_note(ns._db_path(),None,"Old","",'<p>hi</p><img src=x onerror="steal()"><script>steal()</script>',None,"")
        for html in (self.api.get(nid)["content_html"],self.api.edit_content(nid)["content_html"]):
            self.assertNotIn("onerror",html);self.assertNotIn("<script",html);self.assertIn("<p>hi</p>",html)
    # ---- report / export still read the new blocks
    def test_report_builder_reads_pro_blocks(self):
        r=self.api.save(None,"Rep","",PRO_NOTE,[],"web")
        notes=rs.load_notes_for_report([r["id"]])
        text="\n".join(b.get("text","") for b in rs.build_note_blocks(notes[0]))
        for part in ("Recon","Samba RCE","nmap -sV 10.10.10.3",'echo "a < b"',"scan","Winter2024!","Port","ssh"):
            self.assertIn(part,text)
        md=rs.render_markdown(notes,"T");html=rs.render_html(notes,"T")
        self.assertIn("Samba RCE",md);self.assertIn("Samba RCE",html)
        self.assertNotIn("data-shapes",md)
    def test_strip_html_search_text(self):
        t=ns._strip_html(PRO_NOTE)
        self.assertIn("nmap -sV 10.10.10.3",t);self.assertIn("Samba RCE",t);self.assertNotIn("<",t.replace("a < b",""))
    # ---- attachments for the drawing tool
    def test_attachment_data_url_pending_and_saved(self):
        att=self.api.insert_attachment("shot.png","data:image/png;base64,"+base64.b64encode(PNG).decode())
        d=self.api.attachment_data(att["id"])
        self.assertEqual(d["mime"],"image/png");self.assertEqual(d["size"],len(PNG))
        self.assertEqual(base64.b64decode(d["data_url"].split(",",1)[1]),PNG)
        flat=self.api.insert_attachment("annotated.png","data:image/png;base64,"+base64.b64encode(PNG).decode())
        fig=f'<figure class="note-embed note-embed-inline" contenteditable="false" data-attachment-id="{att["id"]}" data-attachment-url="{att["url"]}" data-kind="image" data-shapes="eyJ2IjoxfQ"><img src="{flat["url"]}" alt="shot.png" data-attachment-id="{flat["id"]}"></figure>'
        r=self.api.save(None,"Img","",fig,[],"")
        got=self.api.get(r["id"])["content_html"]
        self.assertNotIn("_pending",got)
        # both the original and the flattened picture moved under the note and are still readable by id
        note_dir=os.path.join(self.dir,"Attachments",str(r["id"]))
        self.assertEqual(sorted(os.listdir(note_dir)),sorted([att["id"]+".png",flat["id"]+".png"]))
        self.assertEqual(self.api.attachment_data(att["id"])["size"],len(PNG))
        self.assertEqual(self.api.attachment_data(flat["id"])["size"],len(PNG))
    def test_attachment_data_url_rejects_paths_and_other_types(self):
        for bad in ("../../etc/passwd","..","","abc","ZZZZZZZZZZZZZZZZ","abc123abc123abcd/../x","0"*64):
            with self.assertRaises(ValueError):ns.attachment_data_url(bad)
        with self.assertRaises(ValueError):ns.attachment_data_url("abcdefabcdefabcd")
        svg=self.api.insert_attachment("x.svg","data:image/svg+xml;base64,"+base64.b64encode(b"<svg/>").decode())
        with self.assertRaises(ValueError):self.api.attachment_data(svg["id"])
        txt=self.api.insert_attachment("x.txt","data:text/plain;base64,"+base64.b64encode(b"hi").decode())
        with self.assertRaises(ValueError):self.api.attachment_data(txt["id"])
    # ---- editor preferences
    def test_pro_prefs_default_off_and_persist(self):
        p=ns.editor_prefs()
        for k in ("suggest_title","suggest_tags","editor_maximized","editor_outline"):self.assertIs(p[k],False)
        self.assertEqual(p["recent_colors"],[]);self.assertEqual(p["draw_width"],2);self.assertEqual(p["draw_color"],"#f03e3e")
        self.assertIs(ns.set_editor_pref("suggest_title",True)["suggest_title"],True)
        self.assertIs(ns.set_editor_pref("editor_maximized",True)["editor_maximized"],True)
        ns._SETTINGS_CACHE=None
        p=ns.editor_prefs()
        self.assertIs(p["suggest_title"],True);self.assertIs(p["suggest_tags"],False);self.assertIs(p["editor_maximized"],True)
        self.assertIs(ns.set_editor_pref("suggest_title",False)["suggest_title"],False)
    def test_pro_prefs_only_true_turns_a_toggle_on(self):
        for v in ("true",1,"yes",[1],{"a":1}):self.assertIs(ns.set_editor_pref("suggest_tags",v)["suggest_tags"],False)
    def test_recent_colors_validated_and_capped(self):
        p=ns.set_editor_pref("recent_colors",["#FF0000","red","#ff0000","javascript:x","#00ff00"]+["#%06x"%i for i in range(1,30)])
        self.assertEqual(p["recent_colors"][:2],["#ff0000","#00ff00"]);self.assertEqual(len(p["recent_colors"]),12)
        self.assertEqual(ns.set_editor_pref("recent_colors","nope")["recent_colors"],[])
    def test_draw_prefs_validated(self):
        self.assertEqual(ns.set_editor_pref("draw_color","#1C7ED6")["draw_color"],"#1c7ed6")
        self.assertEqual(ns.set_editor_pref("draw_color","url(x)")["draw_color"],"#f03e3e")
        self.assertEqual(ns.set_editor_pref("draw_width",4)["draw_width"],4)
        self.assertEqual(ns.set_editor_pref("draw_width",99)["draw_width"],2)
    def test_pro_prefs_keep_other_settings(self):
        ns.set_editor_pref("cmd_box_command_height",120)
        ns.set_editor_pref("note_text_color","#112233")
        ns.set_editor_pref("suggest_tags",True)
        p=ns.editor_prefs()
        self.assertEqual(p["cmd_box_command_height"],120);self.assertEqual(p["note_text_color"],"#112233");self.assertIs(p["suggest_tags"],True)
        with self.assertRaises(ValueError):ns.set_editor_pref("nope",1)
if __name__=="__main__":unittest.main()
