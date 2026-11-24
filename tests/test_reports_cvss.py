import unittest
from _isolate import IsolatedData
from Cores.Services import cvss
KNOWN=(
    ("AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",9.8,"critical"),
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H",10.0,"critical"),
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:C/C:L/I:L/A:N",6.1,"medium"),
    ("CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:C/C:L/I:L/A:N",6.4,"medium"),
    ("CVSS:3.1/AV:N/AC:L/PR:H/UI:N/S:C/C:H/I:H/A:H",9.1,"critical"),
    ("CVSS:3.1/AV:L/AC:L/PR:H/UI:N/S:U/C:L/I:L/A:L",4.2,"medium"),
    ("CVSS:3.1/AV:N/AC:H/PR:N/UI:R/S:U/C:H/I:H/A:H",7.5,"high"),
    ("CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H",7.8,"high"),
    ("CVSS:3.1/AV:A/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N",6.5,"medium"),
    ("CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:N/A:N",6.5,"medium"),
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:L/I:N/A:N",5.3,"medium"),
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N",7.5,"high"),
    ("CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H",8.8,"high"),
    ("CVSS:3.1/AV:N/AC:L/PR:L/UI:R/S:C/C:L/I:L/A:N",5.4,"medium"),
    ("CVSS:3.1/AV:N/AC:H/PR:N/UI:N/S:C/C:H/I:H/A:H",9.0,"critical"),
    ("CVSS:3.0/AV:P/AC:H/PR:H/UI:R/S:U/C:L/I:N/A:N",1.6,"low"),
    ("CVSS:3.1/AV:P/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",6.8,"medium"),
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:N",0.0,"info"),
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:N/I:N/A:N",0.0,"info"),
)
class CvssTests(unittest.TestCase):
    def test_known_vectors(self):
        for vector,score,sev in KNOWN:
            r=cvss.calc(vector)
            self.assertTrue(r["valid"],vector)
            self.assertEqual(score,r["score"],vector)
            self.assertEqual(sev,r["severity"],vector)
            self.assertEqual("",r["error"])
    def test_vector_is_normalised(self):
        r=cvss.calc("  a:h/i:h/c:h/s:u/ui:n/pr:n/ac:l/av:n ")
        self.assertEqual("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",r["vector"])
        self.assertEqual(9.8,r["score"])
        self.assertEqual("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",cvss.calc("CVSS:3.0/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H")["vector"])
    def test_temporal_metrics_are_accepted_and_dropped(self):
        r=cvss.calc("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H/E:P/RL:O/RC:C")
        self.assertTrue(r["valid"])
        self.assertEqual(9.8,r["score"])
        self.assertNotIn("E:P",r["vector"])
    def test_invalid_vectors(self):
        for bad in ("",None,"nonsense","AV:N/AC:L","CVSS:2.0/AV:N/AC:L/Au:N/C:P/I:P/A:P","AV:X/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H","AV:N/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H","AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H/ZZ:1","CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N",12,["x"]):
            r=cvss.calc(bad)
            self.assertFalse(r["valid"],repr(bad))
            self.assertIsNone(r["score"])
            self.assertEqual("",r["severity"])
            self.assertTrue(r["error"])
    def test_roundup_matches_the_specification(self):
        self.assertEqual(4.0,cvss.roundup(4.0))
        self.assertEqual(4.1,cvss.roundup(4.02))
        self.assertEqual(4.0,cvss.roundup(4.000001))
        self.assertEqual(0.1,cvss.roundup(0.00002))
        # 8.6 is the textbook float case: 6.0*... sums that land on x.x0000000001 must not round up a step.
        self.assertEqual(8.6,cvss.calc("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:N/A:N")["score"])
    def test_severity_bands(self):
        for score,sev in ((0,"info"),(0.1,"low"),(3.9,"low"),(4.0,"medium"),(6.9,"medium"),(7.0,"high"),(8.9,"high"),(9.0,"critical"),(10,"critical"),(None,"info"),("x","info")):
            self.assertEqual(sev,cvss.severity(score),score)
    def test_service_wrapper(self):
        iso=IsolatedData();iso.start()
        try:
            from Cores.Bridge.reports_api import ReportsAPI
            self.assertEqual(9.8,ReportsAPI().cvss_calc("AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H")["score"])
        finally:iso.stop()
if __name__=="__main__":unittest.main()
