import time,unittest
from _isolate import IsolatedData
from Cores.Services import terminal_service as terminal
class ShellMappingTests(unittest.TestCase):
    def test_wsl_ids_map_to_a_distro_launch(self):
        self.assertEqual(["wsl.exe","-d","Ubuntu"],terminal._shell_command("wsl:Ubuntu"))
    def test_unknown_shell_falls_back(self):
        self.assertTrue(terminal._shell_command("nonsense"))
    def test_every_listed_shell_maps_to_a_command(self):
        for shell in terminal.list_shells():
            self.assertTrue(terminal._shell_command(shell["id"]),shell["id"])
class InitialSizeTests(unittest.TestCase):
    def test_a_usable_grid_is_accepted(self):
        self.assertEqual((132,50),terminal._clean_size(132,50))
    def test_strings_from_the_bridge_are_accepted(self):
        self.assertEqual((80,24),terminal._clean_size("80","24"))
    def test_an_unmeasured_panel_is_rejected(self):
        self.assertIsNone(terminal._clean_size(0,0))
    def test_absurd_grids_are_rejected(self):
        self.assertIsNone(terminal._clean_size(99999,10))
        self.assertIsNone(terminal._clean_size(80,9999))
        self.assertIsNone(terminal._clean_size(-5,-5))
    def test_junk_is_rejected_rather_than_raising(self):
        self.assertIsNone(terminal._clean_size("wide","tall"))
        self.assertIsNone(terminal._clean_size(None,None))
class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.isolated=IsolatedData()
        self.isolated.start()
    def tearDown(self):
        self.isolated.stop()
    def test_save_get_and_delete(self):
        saved=terminal.save_profile({"name":"Engagement","shell_id":"cmd","startup":"echo hi","env":{"TARGET":"10.0.0.1"}})
        self.assertEqual(1,len(saved))
        profile_id=saved[0]["id"]
        self.assertEqual("Engagement",terminal.get_profile(profile_id)["name"])
        terminal.delete_profile(profile_id)
        self.assertEqual([],terminal.list_profiles())
    def test_saving_same_id_updates_in_place(self):
        first=terminal.save_profile({"name":"One"})[0]
        again=terminal.save_profile({"id":first["id"],"name":"Renamed"})
        self.assertEqual(1,len(again))
        self.assertEqual("Renamed",again[0]["name"])
    def test_blank_name_is_rejected(self):
        with self.assertRaises(ValueError):terminal.save_profile({"name":"   "})
        with self.assertRaises(ValueError):terminal.save_profile("not a dict")
    def test_limits_are_enforced(self):
        oversized={"name":"Big","startup":"x"*900,"env":{"K%d"%index:"v"*900 for index in range(60)}}
        stored=[item for item in terminal.save_profile(oversized) if item["name"]=="Big"][0]
        self.assertEqual(500,len(stored["startup"]))
        self.assertEqual(32,len(stored["env"]))
        self.assertTrue(all(len(value)<=512 for value in stored["env"].values()))
    def test_unknown_colour_falls_back(self):
        stored=terminal.save_profile({"name":"Colour","color":"chartreuse"})[0]
        self.assertIn(stored["color"],terminal.PROFILE_COLORS)
    def test_unknown_profile_is_none(self):
        self.assertIsNone(terminal.get_profile("missing"))
class BatchTests(unittest.TestCase):
    def setUp(self):
        self.isolated=IsolatedData()
        self.isolated.start()
        self.shell=terminal.list_shells()[0]["id"]
    def tearDown(self):
        terminal.clear_batch_output()
        self.isolated.stop()
    def _wait(self,keys,timeout=25):
        deadline=time.time()+timeout
        while time.time()<deadline:
            jobs={job["job_key"]:job for job in terminal.list_jobs(limit=100)}
            if all(jobs.get(key,{}).get("state") not in (None,"running") for key in keys):return jobs
            time.sleep(0.2)
        return {job["job_key"]:job for job in terminal.list_jobs(limit=100)}
    def test_exit_codes_come_from_the_process(self):
        terminal.start_batch(self.shell,[{"job_key":"ok","command":"echo alpha"},{"job_key":"bad","command":"exit 3"}],2)
        jobs=self._wait(["ok","bad"])
        self.assertEqual("done",jobs["ok"]["state"])
        self.assertEqual(0,jobs["ok"]["exit_code"])
        self.assertEqual("failed",jobs["bad"]["state"])
        self.assertEqual(3,jobs["bad"]["exit_code"])
        self.assertIn("alpha",terminal.batch_output("ok"))
    def test_labels_are_stored(self):
        terminal.start_batch(self.shell,[{"job_key":"lbl","label":"host-a","command":"echo x"}],1)
        self._wait(["lbl"])
        self.assertEqual("host-a",terminal.get_job("lbl")["label"])
    def test_concurrency_is_clamped(self):
        self.assertEqual(1,terminal.start_batch(self.shell,[{"command":"echo x"}],0)["concurrency"])
        self.assertEqual(terminal._BATCH_MAX_CONCURRENCY,terminal.start_batch(self.shell,[{"command":"echo x"}],10**6)["concurrency"])
        self.assertEqual(terminal._BATCH_DEFAULT_CONCURRENCY,terminal.start_batch(self.shell,[{"command":"echo x"}],None)["concurrency"])
        self.assertEqual(terminal._BATCH_DEFAULT_CONCURRENCY,terminal.start_batch(self.shell,[{"command":"echo x"}],"nonsense")["concurrency"])
    def test_empty_batch_is_rejected(self):
        with self.assertRaises(ValueError):terminal.start_batch(self.shell,[])
        with self.assertRaises(ValueError):terminal.start_batch(self.shell,[{"command":"   "}])
    def test_job_keys_are_generated_when_absent(self):
        result=terminal.start_batch(self.shell,[{"command":"echo auto"}],1)
        self.assertTrue(result["job_keys"][0])
        self._wait(result["job_keys"])
class BufferTests(unittest.TestCase):
    def _holder(self):
        import threading
        return type("Holder",(),{"_buf":bytearray(),"_tail":bytearray(),"_buf_lock":threading.Lock(),"_append":terminal.TerminalSession._append,"peek":terminal.TerminalSession.peek})()
    def test_session_buffer_is_capped(self):
        holder=self._holder()
        holder._append(b"x"*(terminal._MAX_SESSION_BUFFER+4096))
        self.assertEqual(terminal._MAX_SESSION_BUFFER,len(holder._buf))
    def test_the_peek_tail_is_capped_independently(self):
        holder=self._holder()
        holder._append(b"x"*(terminal._SESSION_TAIL_BYTES+4096))
        self.assertEqual(terminal._SESSION_TAIL_BYTES,len(holder._tail))
        self.assertEqual(terminal._SESSION_TAIL_BYTES,len(holder.peek()))
    def test_the_tail_keeps_the_newest_bytes(self):
        holder=self._holder()
        holder._append(b"H"*terminal._SESSION_TAIL_BYTES)
        holder._append(b"TAIL")
        self.assertTrue(holder.peek().endswith("TAIL"))
if __name__=="__main__":
    unittest.main()
