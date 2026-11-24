import unittest
from _isolate import IsolatedData
from Cores.Services import terminal_service as terminal
class ConptyBackendTests(unittest.TestCase):
    def setUp(self):
        self.isolated=IsolatedData()
        self.isolated.start()
    def tearDown(self):
        self.isolated.stop()
    def test_conpty_is_off_by_default(self):
        self.assertFalse(terminal.get_settings()["use_conpty"])
    def test_support_flag_is_reported(self):
        self.assertIn("conpty_supported",terminal.get_settings())
    def test_flag_round_trips(self):
        terminal.set_run_behaviour({"use_conpty":True})
        self.assertTrue(terminal.get_settings()["use_conpty"])
        terminal.set_run_behaviour({"use_conpty":False})
        self.assertFalse(terminal.get_settings()["use_conpty"])
    def test_session_works_with_flag_off(self):
        session_id=terminal.create_session(terminal.list_shells()[0]["id"])
        session=terminal._sessions[session_id]
        self.assertEqual("pipe",session.backend)
        self.assertTrue(session.alive())
        terminal.close_session(session_id)
    def test_session_still_works_with_flag_on(self):
        terminal.set_run_behaviour({"use_conpty":True})
        session_id=terminal.create_session(terminal.list_shells()[0]["id"])
        session=terminal._sessions[session_id]
        self.assertIn(session.backend,("pipe","conpty"))
        self.assertTrue(session.alive(),"a failed pseudoconsole must fall back to a working pipe session")
        self.assertTrue(session.write("echo probe\r\n"))
        terminal.close_session(session_id)
if __name__=="__main__":
    unittest.main()
