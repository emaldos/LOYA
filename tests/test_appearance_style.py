import json,os,shutil,tempfile,unittest
from _isolate import ROOT
from Cores.Theme import tokens
try:
    from Cores.Bridge import api
except Exception:
    api=None
class AppearanceStyleTests(unittest.TestCase):
    """The Glass/Classic appearance style: glass by default, persisted in settings.json next to the colour theme."""
    def setUp(self):
        self.dir=tempfile.mkdtemp(prefix="loya_style_")
        self._paths=(tokens.SETTINGS_PATH,tokens.BOOT_JS_PATH)
        tokens.SETTINGS_PATH=os.path.join(self.dir,"settings.json")
        tokens.BOOT_JS_PATH=os.path.join(self.dir,"appearance-boot.js")
    def tearDown(self):
        tokens.SETTINGS_PATH,tokens.BOOT_JS_PATH=self._paths
        shutil.rmtree(self.dir,ignore_errors=True)
    def _write(self,d):
        with open(tokens.SETTINGS_PATH,"w",encoding="utf-8") as f:json.dump(d,f)
    def _read(self):
        with open(tokens.SETTINGS_PATH,encoding="utf-8") as f:return json.load(f)
    def test_glass_is_the_default_for_users_who_never_chose(self):
        self.assertEqual("glass",tokens.DEFAULT_STYLE)
        self.assertEqual("glass",tokens.current_style())
        self._write({"appearance":{"mode":"light","theme":"light"}})
        self.assertEqual("glass",tokens.current_style())
    def test_classic_persists_and_keeps_the_other_appearance_keys(self):
        self._write({"appearance":{"mode":"royal","theme":"royal","accent_a":"#14b8a6","accent_b":"#06b6d4"},"window":{"w":900}})
        self.assertTrue(tokens.set_style("classic"))
        self.assertEqual("classic",tokens.current_style())
        d=self._read()
        self.assertEqual("classic",d["appearance"]["style"])
        self.assertEqual("royal",d["appearance"]["mode"])
        self.assertEqual("#14b8a6",d["appearance"]["accent_a"])
        self.assertEqual({"w":900},d["window"])
        self.assertEqual("royal",tokens.current_mode())
        self.assertTrue(tokens.set_style("glass"))
        self.assertEqual("glass",tokens.current_style())
    def test_values_are_normalised(self):
        self.assertTrue(tokens.set_style("  Classic "))
        self.assertEqual("classic",self._read()["appearance"]["style"])
    def test_invalid_values_are_rejected_and_change_nothing(self):
        tokens.set_style("classic")
        for bad in ("","neon","dark",None,"glass;x",42):
            self.assertFalse(tokens.set_style(bad),bad)
        self.assertEqual("classic",tokens.current_style())
    def test_a_corrupt_stored_value_falls_back_to_glass(self):
        for stored in ("neon",None,7,["classic"]):
            self._write({"appearance":{"style":stored}})
            self.assertEqual("glass",tokens.current_style(),stored)
        self._write({"appearance":"classic"})
        self.assertEqual("glass",tokens.current_style())
        with open(tokens.SETTINGS_PATH,"w",encoding="utf-8") as f:f.write("{not json")
        self.assertEqual("glass",tokens.current_style())
    def test_boot_script_carries_the_saved_style_before_first_paint(self):
        self.assertTrue(tokens.set_style("classic"))
        with open(tokens.BOOT_JS_PATH,encoding="utf-8") as f:src=f.read()
        self.assertEqual('document.documentElement.setAttribute("data-style","classic");\n',src)
        tokens.set_style("glass")
        with open(tokens.BOOT_JS_PATH,encoding="utf-8") as f:self.assertIn('"glass"',f.read())
    def test_html_defaults_to_glass_and_loads_the_glass_sheet_last(self):
        for page in ("main.html","mini.html"):
            with open(os.path.join(ROOT,"UI","windows",page),encoding="utf-8") as f:html=f.read()
            self.assertIn('data-style="glass"',html.split("<head>")[0],page)
            head=html.split("</head>")[0]
            links=[l for l in head.splitlines() if l.startswith("<link rel=\"stylesheet\"")]
            self.assertTrue(links[-1].endswith('href="../css/glass.css">'),page)
            self.assertIn('<script src="../js/appearance-boot.js"></script>',head,page)
    def test_every_glass_rule_is_scoped_to_the_glass_style(self):
        import re
        with open(os.path.join(ROOT,"UI","css","glass.css"),encoding="utf-8") as f:css=re.sub(r"/\*.*?\*/","",f.read(),flags=re.S)
        selectors=[s.strip() for s in re.findall(r"([^{}]+)\{",css)]
        self.assertTrue(selectors)
        def top_level(group):
            out,depth,cur=[],0,""
            for ch in group:
                if ch=="(":depth+=1
                elif ch==")":depth-=1
                if ch=="," and depth==0:out.append(cur);cur=""
                else:cur+=ch
            return out+[cur]
        for group in selectors:
            for sel in top_level(group):
                self.assertIn('[data-style="glass"',sel,sel)
    @unittest.skipIf(api is None,"bridge not importable here")
    def test_bridge_get_and_set(self):
        theme=api.ThemeAPI()
        self.assertEqual({"style":"glass","styles":["glass","classic"]},theme.style())
        self.assertEqual("classic",theme.set_style("classic")["style"])
        with self.assertRaises(ValueError):theme.set_style("chrome")
        self.assertEqual("classic",theme.style()["style"])
if __name__=="__main__":
    unittest.main()
