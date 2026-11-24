import os,time,unittest
from _isolate import IsolatedData
from Cores.Services import terminal_service as terminal
def wait_for_exit(proc,timeout=8):
    deadline=time.time()+timeout
    while time.time()<deadline:
        if proc.returncode is not None:return True
        time.sleep(0.05)
    return proc.returncode is not None
class SessionTeardownTests(unittest.TestCase):
    def setUp(self):
        self.isolated=IsolatedData()
        self.isolated.start()
        self.shell=terminal.list_shells()[0]["id"]
    def tearDown(self):
        terminal.close_all_sessions()
        self.isolated.stop()
    def test_closing_reaps_the_child(self):
        session_id=terminal.create_session(self.shell)
        proc=terminal._sessions[session_id].proc
        terminal.close_session(session_id)
        self.assertTrue(wait_for_exit(proc),"the child was signalled but never reaped - a zombie on posix")
        self.assertIsNotNone(proc.returncode)
    def test_closing_many_sessions_leaves_nothing_behind(self):
        procs=[]
        for _ in range(4):
            session_id=terminal.create_session(self.shell)
            procs.append(terminal._sessions[session_id].proc)
            terminal.close_session(session_id)
        for proc in procs:
            self.assertTrue(wait_for_exit(proc))
    def test_close_all_reaps_every_child(self):
        procs=[terminal._sessions[terminal.create_session(self.shell)].proc for _ in range(3)]
        terminal.close_all_sessions()
        for proc in procs:
            self.assertTrue(wait_for_exit(proc))
    def test_the_session_is_forgotten_after_close(self):
        session_id=terminal.create_session(self.shell)
        terminal.close_session(session_id)
        self.assertNotIn(session_id,terminal._sessions)
    def test_closing_twice_is_harmless(self):
        session_id=terminal.create_session(self.shell)
        terminal.close_session(session_id)
        terminal.close_session(session_id)
        self.assertNotIn(session_id,terminal._sessions)
    def test_a_closed_session_is_no_longer_addressable(self):
        session_id=terminal.create_session(self.shell)
        terminal.close_session(session_id)
        with self.assertRaises(ValueError):terminal.write_input(session_id,"echo hi\n")
    @unittest.skipIf(terminal._IS_WINDOWS,"posix only - windows has no zombies")
    def test_no_zombie_is_left_on_posix(self):
        session_id=terminal.create_session(self.shell)
        pid=terminal._sessions[session_id].proc.pid
        proc=terminal._sessions[session_id].proc
        terminal.close_session(session_id)
        wait_for_exit(proc)
        try:state=open("/proc/%d/stat"%pid).read().split(") ",1)[1].split()[0]
        except Exception:state="gone"
        self.assertNotEqual("Z",state,"the closed session left a zombie process")
    @unittest.skipIf(terminal._IS_WINDOWS,"posix only - the master fd is a pty")
    def test_the_master_fd_is_released_on_posix(self):
        session_id=terminal.create_session(self.shell)
        session=terminal._sessions[session_id]
        master_fd=session._master_fd
        self.assertIsNotNone(master_fd)
        terminal.close_session(session_id)
        wait_for_exit(session.proc)
        with self.assertRaises(OSError):os.fstat(master_fd)
if __name__=="__main__":unittest.main()
