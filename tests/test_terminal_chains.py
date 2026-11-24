import time,unittest
from _isolate import IsolatedData
from Cores.Services import terminal_service as terminal
SLOW_COMMAND="ping -n 6 127.0.0.1 >nul" if terminal._IS_WINDOWS else "sleep 5"
def wait_for_chain(chain_id,timeout=40):
    deadline=time.time()+timeout
    while time.time()<deadline:
        status=terminal.chain_status(chain_id)
        if status and not status["active"]:return status
        time.sleep(0.05)
    return terminal.chain_status(chain_id)
class ChainRunnerTests(unittest.TestCase):
    def setUp(self):
        self.isolated=IsolatedData()
        self.isolated.start()
        self.shell=terminal.list_shells()[0]["id"]
    def tearDown(self):
        terminal.clear_batch_output()
        self.isolated.stop()
    def start(self,commands,policy="stop"):
        return terminal.start_chain(self.shell,[{"command":c} for c in commands],policy)
    def test_every_step_finishes_in_order(self):
        started=self.start(["echo one","echo two","echo three"])
        status=wait_for_chain(started["chain_id"])
        self.assertEqual(["done","done","done"],[s["state"] for s in status["steps"]])
        self.assertEqual([0,1,2],[s["chain_pos"] for s in status["steps"]])
    def test_steps_do_not_overlap(self):
        started=self.start(["echo one","echo two","echo three"])
        status=wait_for_chain(started["chain_id"])
        for earlier,later in zip(status["steps"],status["steps"][1:]):
            self.assertLessEqual(earlier["ended_at"],later["started_at"])
    def test_stop_policy_skips_the_rest(self):
        started=self.start(["echo one","exit 1","echo three","echo four"])
        status=wait_for_chain(started["chain_id"])
        self.assertEqual(["done","failed","skipped","skipped"],[s["state"] for s in status["steps"]])
        self.assertEqual(1,status["failed"])
        self.assertEqual(2,status["skipped"])
    def test_continue_policy_runs_everything(self):
        started=self.start(["echo one","exit 1","echo three"],"continue")
        status=wait_for_chain(started["chain_id"])
        self.assertEqual(["done","failed","done"],[s["state"] for s in status["steps"]])
        self.assertEqual(0,status["skipped"])
    def test_skipped_steps_never_ran(self):
        started=self.start(["exit 1","echo never"])
        wait_for_chain(started["chain_id"])
        self.assertEqual("",terminal.batch_output(started["job_keys"][1]))
    def test_output_is_captured_per_step(self):
        started=self.start(["echo alpha","echo beta"])
        wait_for_chain(started["chain_id"])
        self.assertIn("alpha",terminal.batch_output(started["job_keys"][0]))
        self.assertIn("beta",terminal.batch_output(started["job_keys"][1]))
    def test_steps_start_pending_and_carry_the_chain_id(self):
        started=self.start(["echo one","echo two"])
        chain_id=started["chain_id"]
        status=terminal.chain_status(chain_id)
        self.assertTrue(status["active"])
        self.assertTrue(all(s["chain_id"]==chain_id for s in status["steps"]))
        wait_for_chain(chain_id)
    def test_unknown_policy_falls_back_to_stop(self):
        started=terminal.start_chain(self.shell,[{"command":"exit 1"},{"command":"echo two"}],"whatever")
        self.assertEqual("stop",started["policy"])
        status=wait_for_chain(started["chain_id"])
        self.assertEqual("skipped",status["steps"][1]["state"])
    def test_labels_fall_back_to_the_command(self):
        started=terminal.start_chain(self.shell,[{"command":"echo one","label":"First step"},{"command":"echo two"}])
        status=wait_for_chain(started["chain_id"])
        self.assertEqual("First step",status["steps"][0]["label"])
        self.assertEqual("echo",status["steps"][1]["label"])
    def test_blank_commands_are_dropped(self):
        started=terminal.start_chain(self.shell,[{"command":"  "},{"command":"echo one"},"not a dict",None])
        status=wait_for_chain(started["chain_id"])
        self.assertEqual(1,status["total"])
    def test_an_empty_chain_is_refused(self):
        with self.assertRaises(ValueError):terminal.start_chain(self.shell,[])
        with self.assertRaises(ValueError):terminal.start_chain(self.shell,[{"command":""}])
    def test_cancel_skips_the_pending_steps(self):
        started=terminal.start_chain(self.shell,[{"command":SLOW_COMMAND},{"command":"echo two"},{"command":"echo three"}])
        self.assertTrue(terminal.cancel_chain(started["chain_id"]))
        status=wait_for_chain(started["chain_id"])
        self.assertEqual(["skipped","skipped"],[s["state"] for s in status["steps"][1:]])
        self.assertFalse(status["active"])
        self.assertEqual("",terminal.batch_output(started["job_keys"][1]))
    def test_cancel_of_an_unknown_chain_is_false(self):
        self.assertFalse(terminal.cancel_chain("chain-does-not-exist"))
        self.assertFalse(terminal.cancel_chain(""))
    def test_status_of_an_unknown_chain_is_none(self):
        self.assertIsNone(terminal.chain_status("chain-does-not-exist"))
        self.assertIsNone(terminal.chain_status(""))
    def test_chain_steps_appear_in_the_job_list(self):
        started=self.start(["echo one","echo two"])
        wait_for_chain(started["chain_id"])
        keys={j["job_key"] for j in terminal.list_jobs()}
        self.assertTrue(set(started["job_keys"]).issubset(keys))
    def test_plain_jobs_carry_no_chain(self):
        terminal.start_job("solo","s1","echo one")
        job=terminal.get_job("solo")
        self.assertIsNone(job["chain_id"])
        self.assertIsNone(job["chain_pos"])
    def test_pending_steps_survive_a_clear(self):
        started=terminal.start_chain(self.shell,[{"command":SLOW_COMMAND},{"command":"echo two"}])
        terminal.clear_finished_jobs()
        self.assertEqual(2,terminal.chain_status(started["chain_id"])["total"])
        terminal.cancel_chain(started["chain_id"])
        wait_for_chain(started["chain_id"])
    def test_reap_orphans_pending_steps(self):
        started=terminal.start_chain(self.shell,[{"command":"echo one"},{"command":"echo two"}])
        wait_for_chain(started["chain_id"])
        terminal.start_job("stray","s1","echo one")
        self.assertGreaterEqual(terminal.reap_running_jobs(),1)
        self.assertEqual("orphaned",terminal.get_job("stray")["state"])
if __name__=="__main__":unittest.main()
