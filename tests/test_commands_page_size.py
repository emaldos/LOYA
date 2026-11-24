import os,json,tempfile,shutil,unittest
from _isolate import ROOT
from Cores.Bridge import api
class CommandsPageSizeTests(unittest.TestCase):
    # The page size used to live in localStorage, which does not exist under WebKitGTK's private mode, so it reset on every Linux launch.
    def setUp(self):
        self.dir=tempfile.mkdtemp(prefix="loya_test_")
        self.path=os.path.join(self.dir,"settings.json")
        with open(self.path,"w",encoding="utf-8") as f:json.dump({"theme":"dark"},f)
        self._orig=api._settings_path
        api._settings_path=lambda:self.path
        self.cmds=api.CommandsAPI()
    def tearDown(self):
        api._settings_path=self._orig
        shutil.rmtree(self.dir,ignore_errors=True)
    def test_default_is_twenty(self):
        self.assertEqual(20,self.cmds.get_page_size())
    def test_round_trip_keeps_other_settings(self):
        self.assertEqual(50,self.cmds.set_page_size("50"))
        self.assertEqual(50,self.cmds.get_page_size())
        with open(self.path,encoding="utf-8") as f:self.assertEqual("dark",json.load(f)["theme"])
    def test_invalid_sizes_are_refused(self):
        for bad in (7,0,-10,"abc",None,1000):
            with self.assertRaises(ValueError):self.cmds.set_page_size(bad)
        self.assertEqual(20,self.cmds.get_page_size())
    def test_a_hand_edited_bad_value_falls_back(self):
        with open(self.path,"w",encoding="utf-8") as f:json.dump({"commands_page_size":33},f)
        self.assertEqual(20,self.cmds.get_page_size())
if __name__=="__main__":unittest.main()
