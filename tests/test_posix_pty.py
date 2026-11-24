import os,shutil,sys,time,unittest
from _isolate import IsolatedData
from Cores.Services import terminal_service as terminal
def drain(session_id,needle,timeout=8,times=1):
    deadline=time.time()+timeout
    text=""
    while time.time()<deadline:
        text+=terminal.read_output(session_id) or ""
        if text.count(needle)>=times:return text
        time.sleep(0.05)
    return text
def wait_until_shell_settles(session_id,timeout=10,quiet=0.35):
    deadline=time.time()+timeout
    text=""
    stable_since=None
    while time.time()<deadline:
        chunk=terminal.read_output(session_id) or ""
        if chunk:
            text+=chunk
            stable_since=None
        elif text:
            if stable_since is None:stable_since=time.time()
            elif time.time()-stable_since>=quiet:return text
        time.sleep(0.05)
    return text
def _controlling_tty_number(pid):
    with open(f"/proc/{pid}/stat",encoding="utf-8") as f:data=f.read()
    return int(data[data.rindex(")")+2:].split()[4])
@unittest.skipIf(terminal._IS_WINDOWS,"posix only - run under WSL or a real Linux desktop")
class PosixPtyTests(unittest.TestCase):
    def setUp(self):
        self.isolated=IsolatedData()
        self.isolated.start()
        self.shell=terminal.list_shells()[0]["id"]
        self.session_id=terminal.create_session(self.shell)
        self.session=terminal._sessions[self.session_id]
        wait_until_shell_settles(self.session_id)
    def tearDown(self):
        terminal.close_all_sessions()
        self.isolated.stop()
    def test_a_session_gets_a_real_pty(self):
        self.assertIsNotNone(self.session._master_fd)
        self.assertEqual("pipe",self.session.backend)
    def test_the_child_runs_in_its_own_process_group(self):
        self.assertNotEqual(os.getpgid(os.getpid()),os.getpgid(self.session.proc.pid))
    def test_the_pty_round_trips_a_command(self):
        terminal.write_input(self.session_id,"echo PTY_ROUNDTRIP_OK\n")
        self.assertIn("PTY_ROUNDTRIP_OK",drain(self.session_id,"PTY_ROUNDTRIP_OK"))
    def test_the_pty_echoes_input_so_it_is_a_tty_not_a_pipe(self):
        terminal.write_input(self.session_id,"echo PTY_ECHO_OK\n")
        text=drain(self.session_id,"PTY_ECHO_OK",times=2)
        self.assertGreaterEqual(text.count("PTY_ECHO_OK"),2,"a pipe would show the output once, a tty echoes the command too")
    def test_resize_reaches_the_child(self):
        self.assertTrue(terminal.resize_session(self.session_id,132,50))
        terminal.write_input(self.session_id,"stty size\n")
        self.assertIn("50 132",drain(self.session_id,"50 132"))
    def test_a_session_starts_at_the_size_it_was_created_with(self):
        sid=terminal.create_session(self.shell,None,132,50)
        try:
            wait_until_shell_settles(sid)
            terminal.write_input(sid,"stty size\n")
            self.assertIn("50 132",drain(sid,"50 132"),"the pty must start at the panel's size or the shell redraws its prompt on the first resize")
        finally:
            terminal.close_session(sid)
    def test_a_session_created_without_a_size_still_works(self):
        sid=terminal.create_session(self.shell)
        try:
            self.assertIsNone(terminal._sessions[sid]._initial_size)
            self.assertTrue(terminal.session_alive(sid))
        finally:
            terminal.close_session(sid)
    def test_resize_survives_repeated_sizes(self):
        for cols,rows in ((100,40),(132,50),(80,24)):
            self.assertTrue(terminal.resize_session(self.session_id,cols,rows))
    def test_interrupt_writes_the_raw_etx_byte(self):
        terminal.write_input(self.session_id,"sleep 30\n")
        time.sleep(0.4)
        self.assertTrue(terminal.interrupt_session(self.session_id))
    def test_one_shot_commands_use_a_login_shell(self):
        self.assertEqual("-lc",terminal._one_shot_command("shell","echo x")[1])
    def test_elevation_reports_a_posix_method(self):
        self.assertEqual("linux",terminal.elevation_available().get("platform"))
    def test_the_session_owns_a_controlling_terminal(self):
        self.assertNotEqual(0,_controlling_tty_number(self.session.proc.pid),"os.setsid alone leaves no controlling terminal, so sudo and ssh cannot open /dev/tty")
    def test_the_controlling_terminal_is_the_sessions_own_pty(self):
        slave=os.ptsname(self.session._master_fd)
        self.assertEqual(os.stat(slave).st_rdev,_controlling_tty_number(self.session.proc.pid))
    def test_tty_names_a_real_pts_device(self):
        terminal.write_input(self.session_id,"tty\n")
        self.assertRegex(drain(self.session_id,"/dev/pts/"),r"/dev/pts/\d+")
    def test_elevation_prefers_the_in_terminal_sudo_flow(self):
        if not shutil.which("sudo"):self.skipTest("sudo not installed")
        self.assertEqual("sudo",terminal.elevation_available().get("method"))
    def test_the_sudo_command_wraps_the_selected_shell(self):
        command=terminal._sudo_command(self.shell)
        self.assertEqual("sudo",command[0])
        self.assertIn("-p",command)
        self.assertEqual(terminal._shell_command(self.shell),command[-len(terminal._shell_command(self.shell)):])
    def test_conpty_is_never_offered_off_windows(self):
        self.assertFalse(terminal.conpty_supported())
        self.assertFalse(terminal.get_settings()["conpty_supported"])
@unittest.skipIf(terminal._IS_WINDOWS,"posix only - reads /proc")
class PosixProcessInfoTests(unittest.TestCase):
    def test_proc_lookup_resolves_this_process(self):
        sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from RunNote import _unix_process_info
        alive,ident=_unix_process_info(os.getpid())
        self.assertTrue(alive)
        self.assertIn("python",ident.lower())
    def test_proc_lookup_of_a_dead_pid_reports_not_alive(self):
        from RunNote import _unix_process_info
        self.assertEqual((False,""),_unix_process_info(4194303))
if __name__=="__main__":unittest.main()
