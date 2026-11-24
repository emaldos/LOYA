import unittest
from _isolate import ROOT
from Cores.Services import cve_guidance as g
REQUIRED=(79,89,22,78,77,94,787,416,20,287,306,862,863,434,502,611,918,352,400,798,119,125,190,269,732,
          200,284,285,476,601,917,1321,295,327,522,532,639,770,276,362,59,74,120,121,122,426,427,613,384,1188)
class CveGuidanceTests(unittest.TestCase):
    """The offline CWE guidance shipped with CVE Intel: complete, well-formed, plain text."""
    def _check_entry(self,label,e):
        self.assertIsInstance(e["name"],str,label)
        self.assertTrue(e["name"].strip(),label)
        self.assertTrue(3<=len(e["mitigations"])<=5,f"{label}: {len(e['mitigations'])} mitigations")
        self.assertTrue(2<=len(e["detection"])<=4,f"{label}: {len(e['detection'])} detection ideas")
        for line in list(e["mitigations"])+list(e["detection"])+[e["name"]]:
            self.assertIsInstance(line,str,label)
            self.assertEqual(line,line.strip(),label)
            self.assertTrue(line.isascii(),f"{label}: non-ASCII in {line!r}")
            self.assertNotIn("\n",line,label)
            self.assertNotRegex(line,r"</?[a-zA-Z][^>]*>|\*\*|\]\(",f"{label}: markup in {line!r}")
        for line in list(e["mitigations"])+list(e["detection"]):
            self.assertTrue(line.endswith("."),f"{label}: {line!r}")
            self.assertTrue(20<=len(line)<=260,f"{label}: length of {line!r}")
    def test_every_required_cwe_is_covered(self):
        missing=[n for n in REQUIRED if str(n) not in g.CWE]
        self.assertEqual([],missing)
    def test_entries_are_well_formed(self):
        for k,e in g.CWE.items():
            self.assertRegex(k,r"^[1-9]\d*$")
            self.assertEqual({"name","mitigations","detection"},set(e))
            self._check_entry("CWE-"+k,e)
    def test_fallback_is_well_formed(self):
        self.assertEqual({"name","mitigations","detection"},set(g.FALLBACK))
        self._check_entry("FALLBACK",g.FALLBACK)
    def test_guidance_accepts_every_id_form(self):
        a=g.guidance("CWE-79")
        self.assertEqual("CWE-79",a["cwe"])
        self.assertEqual({"cwe","name","mitigations","detection"},set(a))
        for form in (79,"79"," cwe-79 ","CWE-079"):
            self.assertEqual(a,g.guidance(form),form)
        self.assertIn("Cross-site Scripting",a["name"])
    def test_unknown_ids_return_none_and_an_empty_name(self):
        for bad in ("CWE-999999","NVD-CWE-noinfo","NVD-CWE-Other","",None,0,-5,True,"79; DROP","CWE-",[79]):
            self.assertIsNone(g.guidance(bad),bad)
            self.assertEqual("",g.name(bad),bad)
    def test_name_matches_the_entry(self):
        self.assertEqual(g.CWE["89"]["name"],g.name("CWE-89"))
        self.assertEqual(g.CWE["502"]["name"],g.name(502))
    def test_guidance_returns_copies(self):
        a=g.guidance(79)
        a["mitigations"].append("x")
        self.assertNotIn("x",g.guidance(79)["mitigations"])
        self.assertNotIn("x",g.CWE["79"]["mitigations"])
if __name__=="__main__":unittest.main()
