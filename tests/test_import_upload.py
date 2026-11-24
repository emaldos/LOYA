import os,base64,tempfile,shutil,unittest
from _isolate import ROOT,IsolatedData
from Cores.Bridge import api
def b64(data):return base64.b64encode(data).decode("ascii")
class StagedUploadTests(unittest.TestCase):
    # Drag-and-drop imports stage the dropped bytes in a private temp folder; the importer may only read files from there.
    def setUp(self):
        self.iso=IsolatedData();self.iso.start()
        self.saved=api._upload_state["dir"]
        api._upload_state["dir"]=None
    def tearDown(self):
        d=api._upload_state["dir"]
        if d:shutil.rmtree(d,ignore_errors=True)
        api._upload_state["dir"]=self.saved
        self.iso.stop()
    def test_round_trip_keeps_bytes_and_name(self):
        p=api._stage_upload("notes.json",b64(b'[{"name":"a"}]'))
        self.assertEqual("notes.json",os.path.basename(p))
        with open(p,"rb") as f:self.assertEqual(b'[{"name":"a"}]',f.read())
        self.assertEqual(os.path.realpath(p),api._staged_path(p))
    def test_path_parts_in_the_name_are_dropped(self):
        for name in ("../../etc/passwd","..\\..\\win.ini","/abs/x.csv"):
            p=api._stage_upload(name,b64(b"x"))
            self.assertTrue(os.path.realpath(p).startswith(os.path.realpath(api._upload_state["dir"])),name)
    def test_paths_outside_the_staging_folder_are_refused(self):
        api._stage_upload("a.json",b64(b"[]"))
        outside=tempfile.NamedTemporaryFile(delete=False,suffix=".json");outside.close()
        try:
            for bad in (outside.name,api._upload_state["dir"],os.path.join(api._upload_state["dir"],"..","x.json"),"",None):
                with self.assertRaises(ValueError):api._staged_path(bad)
        finally:os.remove(outside.name)
    def test_nothing_staged_means_nothing_allowed(self):
        with self.assertRaises(ValueError):api._staged_path("/tmp/anything.json")
    def test_empty_invalid_and_oversized_uploads_are_refused(self):
        with self.assertRaises(ValueError):api._stage_upload("a.json","")
        with self.assertRaises(ValueError):api._stage_upload("a.json","%%%not-base64%%%")
        old=api.UPLOAD_MAX_BYTES;api.UPLOAD_MAX_BYTES=4
        try:
            with self.assertRaises(ValueError):api._stage_upload("a.json",b64(b"12345"))
        finally:api.UPLOAD_MAX_BYTES=old
    def test_pick_uses_the_staged_file_without_a_dialog(self):
        class NoDialog:
            def create_file_dialog(self,*a,**k):raise AssertionError("dialog must not open for a staged file")
        ie=api.ImportExportAPI();ie._window=NoDialog()
        p=api._stage_upload("cmds.json",b64(b'[{"command":"nmap -sV {IPv4}","title":"scan"}]'))
        res=ie.pick_commands_import("json",p)
        self.assertEqual(os.path.realpath(p),res["path"])
        with self.assertRaises(ValueError):ie.pick_notes_import("markdown_folder",p)
if __name__=="__main__":unittest.main()
