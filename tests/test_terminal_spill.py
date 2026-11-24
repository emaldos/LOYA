import os,unittest
from _isolate import IsolatedData
from Cores.Services import terminal_service as terminal
class OutputSpillTests(unittest.TestCase):
    def setUp(self):
        self.isolated=IsolatedData()
        self.isolated.start()
        terminal.clear_batch_output()
        self.small="line\n"*10
        self.large="x"*(terminal._SPILL_THRESHOLD+5000)
    def tearDown(self):
        terminal.clear_batch_output()
        self.isolated.stop()
    def test_small_output_stays_in_memory(self):
        terminal._batch_store_output("j1",self.small)
        self.assertEqual(self.small,terminal.batch_output("j1"))
        self.assertFalse(terminal.batch_output_info("j1")["spilled"])
    def test_large_output_is_spilled_to_disk(self):
        terminal._batch_store_output("j2",self.large)
        info=terminal.batch_output_info("j2")
        self.assertTrue(info["spilled"])
        self.assertEqual(len(self.large),info["total"])
        self.assertEqual(terminal._BATCH_MAX_OUTPUT,info["held"])
    def test_the_full_output_is_recoverable(self):
        terminal._batch_store_output("j3",self.large)
        self.assertEqual(self.large,terminal.batch_output("j3",True))
    def test_the_default_read_stays_bounded(self):
        terminal._batch_store_output("j4",self.large)
        self.assertEqual(terminal._BATCH_MAX_OUTPUT,len(terminal.batch_output("j4")))
    def test_the_bounded_read_keeps_the_tail(self):
        body="HEAD"+"x"*terminal._SPILL_THRESHOLD+"TAIL"
        terminal._batch_store_output("j5",body)
        self.assertTrue(terminal.batch_output("j5").endswith("TAIL"))
        self.assertFalse(terminal.batch_output("j5").startswith("HEAD"))
    def test_a_full_read_of_unspilled_output_is_the_whole_thing(self):
        terminal._batch_store_output("j6",self.small)
        self.assertEqual(self.small,terminal.batch_output("j6",True))
    def test_clearing_one_job_removes_its_spill_file(self):
        terminal._batch_store_output("j7",self.large)
        path=terminal._spill_path("j7")
        self.assertTrue(os.path.exists(path))
        terminal.clear_batch_output("j7")
        self.assertFalse(os.path.exists(path))
        self.assertEqual("",terminal.batch_output("j7"))
    def test_clearing_everything_removes_every_spill_file(self):
        terminal._batch_store_output("j8",self.large)
        terminal._batch_store_output("j9",self.large)
        terminal.clear_batch_output()
        self.assertEqual([],os.listdir(terminal._spill_dir()))
    def test_an_unknown_job_reads_empty(self):
        self.assertEqual("",terminal.batch_output("nope"))
        self.assertEqual("",terminal.batch_output("nope",True))
        self.assertEqual({"total":0,"held":0,"spilled":False},terminal.batch_output_info("nope"))
    def test_a_missing_spill_file_falls_back_to_the_tail(self):
        terminal._batch_store_output("j10",self.large)
        os.remove(terminal._spill_path("j10"))
        self.assertEqual(terminal._BATCH_MAX_OUTPUT,len(terminal.batch_output("j10",True)))
    def test_job_keys_cannot_escape_the_spill_directory(self):
        self.assertEqual(os.path.join(terminal._spill_dir(),"etcpasswd.txt"),terminal._spill_path("../../etc/passwd"))
        self.assertIsNone(terminal._spill_path("../.."))
        self.assertIsNone(terminal._spill_path(""))
    def test_a_hostile_job_key_still_round_trips(self):
        terminal._batch_store_output("../../evil",self.large)
        self.assertEqual(self.large,terminal.batch_output("../../evil",True))
        self.assertEqual(["evil.txt"],os.listdir(terminal._spill_dir()))
    def test_empty_output_is_stored_without_a_file(self):
        terminal._batch_store_output("j11","")
        self.assertEqual("",terminal.batch_output("j11"))
        self.assertFalse(terminal.batch_output_info("j11")["spilled"])
if __name__=="__main__":unittest.main()
