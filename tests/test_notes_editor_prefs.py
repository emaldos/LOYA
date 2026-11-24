import os,sys,json,unittest
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from _isolate import IsolatedData
from Cores.Services import notes_service as ns
# The note editor's toolbar pins and selection-bubble switch live in settings.json (never localStorage: WebKitGTK has none), and the markup the new tools write must survive the stored-note sanitiser.
TOOLS_NOTE=('<p>Kerberoast <span class="note-mitre" data-tid="T1558.003" title="MITRE ATT&amp;CK - Credential Access">T1558.003 Kerberoasting</span></p>'
'<div class="note-callout note-cmdout" data-callout="evidence"><p class="note-evidence-meta"><code>$ id</code> <span class="note-exit" data-exit="0">exit 0</span> <span class="note-ts">[2026-11-23 22:26]</span></p><pre class="note-code" data-lang="output">uid=0(root)</pre></div>'
'<div class="note-callout note-finding" data-callout="finding" data-sev="medium" data-cvss="6.1" data-vector="CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:C/C:L/I:L/A:N"><h3>XSS</h3></div>'
'<table class="note-table note-table-head"><tbody><tr><th>Host</th><th>Port</th></tr><tr><td>10.10.10.5</td><td>445/tcp</td></tr></tbody></table>')
class NotesEditorPrefsTest(unittest.TestCase):
    def setUp(self):
        self.iso=IsolatedData();self.dir=self.iso.start()
        self._abs=ns._abs
        ns._abs=lambda *p:os.path.join(self.dir,*(p[1:] if p and p[0]=="Data" else p))
        ns._SETTINGS_CACHE=None;ns._SETTINGS_MTIME=None
    def tearDown(self):
        ns._abs=self._abs
        ns._SETTINGS_CACHE=None;ns._SETTINGS_MTIME=None
        self.iso.stop()
    def _stored(self):
        with open(ns._settings_path(),encoding="utf-8") as f:return json.load(f)
    def test_toolbar_default_is_none_until_customised(self):
        self.assertIsNone(ns.editor_prefs()["toolbar_main"])
        self.assertIs(ns.editor_prefs()["editor_bubble_off"],False)
    def test_toolbar_pins_persist_in_settings_json(self):
        p=ns.set_editor_pref("toolbar_main",["style","fmt.bold","ins.time","pt.ioc"])
        self.assertEqual(p["toolbar_main"],["style","fmt.bold","ins.time","pt.ioc"])
        self.assertEqual(self._stored()["note"]["toolbar_main"],["style","fmt.bold","ins.time","pt.ioc"])
        ns._SETTINGS_CACHE=None
        self.assertEqual(ns.editor_prefs()["toolbar_main"],["style","fmt.bold","ins.time","pt.ioc"])
    def test_toolbar_pins_are_validated(self):
        p=ns.set_editor_pref("toolbar_main",["fmt.bold","fmt.bold","<script>","a b",7,None,"x"*60,"../etc","ins.table"])
        self.assertEqual(p["toolbar_main"],["fmt.bold","ins.table"])
        self.assertEqual(len(ns.set_editor_pref("toolbar_main",["t%d"%i for i in range(90)])["toolbar_main"]),40)
    def test_empty_bar_is_kept_and_none_resets(self):
        self.assertEqual(ns.set_editor_pref("toolbar_main",[])["toolbar_main"],[])
        self.assertIsNone(ns.set_editor_pref("toolbar_main",None)["toolbar_main"])
        self.assertNotIn("toolbar_main",self._stored().get("note",{}))
        self.assertIsNone(ns.set_editor_pref("toolbar_main","fmt.bold")["toolbar_main"])
    def test_pins_do_not_disturb_other_note_prefs(self):
        ns.set_editor_pref("editor_outline",True);ns.set_editor_pref("auto_pairs_off",True)
        ns.set_editor_pref("toolbar_main",["fmt.bold"])
        p=ns.editor_prefs()
        self.assertIs(p["editor_outline"],True);self.assertIs(p["auto_pairs_off"],True);self.assertEqual(p["toolbar_main"],["fmt.bold"])
    def test_bubble_switch_only_true_turns_it_off(self):
        self.assertIs(ns.set_editor_pref("editor_bubble_off",True)["editor_bubble_off"],True)
        for v in ("true",1,"yes",[1]):self.assertIs(ns.set_editor_pref("editor_bubble_off",v)["editor_bubble_off"],False)
    def test_unknown_pref_is_refused(self):
        with self.assertRaises(ValueError):ns.set_editor_pref("toolbar_extra",["x"])
    def test_new_tool_markup_survives_the_note_sanitiser(self):
        self.assertEqual(ns.sanitize_note_html(TOOLS_NOTE),TOOLS_NOTE)
    def test_sanitiser_still_strips_scripts_from_the_new_markup(self):
        dirty='<span class="note-mitre" data-tid="T1059" onclick="alert(1)">T1059</span><script>alert(2)</script><a href="javascript:alert(3)" class="note-mitre">x</a>'
        out=ns.sanitize_note_html(dirty)
        self.assertNotIn("onclick",out);self.assertNotIn("<script",out);self.assertNotIn("javascript:",out)
        self.assertIn('class="note-mitre"',out);self.assertIn('data-tid="T1059"',out)
if __name__=="__main__":unittest.main()
