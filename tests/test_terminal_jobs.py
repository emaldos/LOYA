import unittest
from _isolate import IsolatedData
from Cores.Services import terminal_service as terminal
class JobRegistryTests(unittest.TestCase):
    def setUp(self):
        self.isolated=IsolatedData()
        self.isolated.start()
    def tearDown(self):
        self.isolated.stop()
    def test_start_then_finish_zero_is_done(self):
        terminal.start_job("j1","s1","nmap -sV 10.0.0.1","snippet")
        running=terminal.get_job("j1")
        self.assertEqual("running",running["state"])
        self.assertEqual("nmap",running["label"])
        self.assertEqual("snippet",running["source"])
        self.assertIsNone(running["exit_code"])
        done=terminal.finish_job("j1",0,"/home/me",2048)
        self.assertEqual("done",done["state"])
        self.assertEqual(0,done["exit_code"])
        self.assertEqual("/home/me",done["cwd"])
        self.assertEqual(2048,done["bytes_out"])
        self.assertTrue(done["ended_at"])
    def test_non_zero_exit_is_failed(self):
        terminal.start_job("j2","s1","bad-command")
        self.assertEqual("failed",terminal.finish_job("j2",127)["state"])
    def test_missing_exit_code_is_orphaned(self):
        terminal.start_job("j3","s1","hangs forever")
        self.assertEqual("orphaned",terminal.finish_job("j3",None)["state"])
    def test_mark_killed_sets_end_time(self):
        terminal.start_job("j4","s1","sleep 100")
        killed=terminal.mark_job("j4","killed")
        self.assertEqual("killed",killed["state"])
        self.assertTrue(killed["ended_at"])
    def test_unknown_state_is_rejected(self):
        terminal.start_job("j5","s1","x")
        with self.assertRaises(ValueError):terminal.mark_job("j5","not-a-state")
    def test_empty_job_key_is_rejected(self):
        with self.assertRaises(ValueError):terminal.start_job("","s1","x")
    def test_listing_is_newest_first_and_filterable(self):
        terminal.start_job("a1","alpha","one")
        terminal.start_job("b1","beta","two")
        terminal.start_job("a2","alpha","three")
        self.assertEqual(["a2","b1","a1"],[job["job_key"] for job in terminal.list_jobs()])
        self.assertEqual(["a2","a1"],[job["job_key"] for job in terminal.list_jobs("alpha")])
    def test_list_limit_is_clamped(self):
        terminal.start_job("only","s1","x")
        self.assertLessEqual(len(terminal.list_jobs(limit=10**6)),terminal._JOB_LIST_LIMIT)
        self.assertGreaterEqual(len(terminal.list_jobs(limit=0)),1)
    def test_delete_and_clear_finished(self):
        terminal.start_job("d1","s1","one");terminal.finish_job("d1",0)
        terminal.start_job("d2","s1","two")
        self.assertTrue(terminal.delete_job("d1"))
        self.assertIsNone(terminal.get_job("d1"))
        terminal.start_job("d3","s1","three");terminal.finish_job("d3",1)
        self.assertEqual(1,terminal.clear_finished_jobs("s1"))
        self.assertEqual(["d2"],[job["job_key"] for job in terminal.list_jobs()])
    def test_reap_marks_stale_running_jobs(self):
        terminal.start_job("r1","s1","left running")
        self.assertEqual(1,terminal.reap_running_jobs())
        self.assertEqual("orphaned",terminal.get_job("r1")["state"])
    def test_interrupt_unknown_session_is_false(self):
        self.assertFalse(terminal.interrupt_session("no-such-session"))
    def test_unknown_job_lookup_returns_none(self):
        self.assertIsNone(terminal.get_job("missing"))
if __name__=="__main__":
    unittest.main()
