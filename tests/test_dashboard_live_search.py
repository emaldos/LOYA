import unittest
from _isolate import ROOT
from Cores.Services import dashboard_service as d
class LiveTargetSearchFieldTests(unittest.TestCase):
    # The dashboard live-target picker shows a hint and searches values, but never values under secret-looking keys.
    def test_secrets_are_neither_shown_nor_searchable(self):
        f=d._target_search_fields({"values":{"IPv4":"10.0.0.5","Password":"Summer2026!","Domain":"acme.local","API_Key":"sk-123","NTLM_Hash":"aad3b4","Session_Cookie":"c=1","Username":"bob"}},{"ipv4":1,"domain":2})
        for secret in ("Summer2026!","sk-123","aad3b4","c=1"):
            self.assertNotIn(secret,f["hint"]);self.assertNotIn(secret,f["search"])
        self.assertEqual("10.0.0.5 · acme.local",f["hint"])
        self.assertIn("bob",f["search"])
    def test_hint_prefers_identifying_values(self):
        f=d._target_search_fields({"values":{"Wordlist":"/usr/share/wl.txt","Port":"443","URL":"https://a.example","IPv4":"10.0.0.9"}},{"wordlist":1,"port":2,"url":3,"ipv4":4})
        self.assertEqual("https://a.example · 10.0.0.9",f["hint"])
        self.assertIn("/usr/share/wl.txt",f["search"])
    def test_targets_without_values_are_fine(self):
        self.assertEqual({"hint":"","search":""},d._target_search_fields({"values":{}},{}))
        self.assertEqual({"hint":"","search":""},d._target_search_fields({},{}))
if __name__=="__main__":unittest.main()
