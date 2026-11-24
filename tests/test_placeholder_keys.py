import unittest
from _isolate import ROOT
from Cores.Services import targets_service as ts
class PlaceholderKeyTests(unittest.TestCase):
    # Seeding demo data turned jq's '{id,email}' into a Target key. Keys must look like names, not code.
    def test_real_keys_are_accepted(self):
        for k in ("IPv4","Domain","DC_IP","Target Name","Wordlist","host.ip"):
            self.assertTrue(ts._is_valid_key(k),k)
    def test_code_braces_are_not_keys(self):
        for k in ("id,email","a,b","2,3","1..10","0","42",'"a":1',"print $1","x|y","a=b","(x)","a;b","a*b","C:\\x","<b>",""," "):
            self.assertFalse(ts._is_valid_key(k),repr(k))
    def test_extraction_skips_code_and_shell_braces(self):
        text="jq -c '{id,email}' {URL}/users/{id}; echo {1..5} ${HOME}; grep -E 'a{2,3}' {Domain}; awk '{print $1}'"
        self.assertEqual(["URL","id","Domain"],ts._extract_keys_from_text(text))
if __name__=="__main__":unittest.main()
