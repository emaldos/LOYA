import os,subprocess,sys,tempfile,unittest
from _isolate import IsolatedData
from Cores.Services import terminal_service as terminal
_REDIRECTED_PARENT_SCRIPT="""
import sys,time,threading
sys.path.insert(0,sys.argv[1])
from Cores.Services import conpty
session=conpty.ConptySession("cmd.exe /c echo LOYA_CONPTY_MARKER",80,25)
chunks=[]
def read_output():
    try:
        while True:
            data=session._reader.read(4096)
            if not data:break
            chunks.append(data)
    except OSError:pass
threading.Thread(target=read_output,daemon=True).start()
deadline=time.time()+10
while time.time()<deadline and b"LOYA_CONPTY_MARKER" not in b"".join(chunks):time.sleep(0.1)
with open(sys.argv[2],"w") as result:result.write("in_pty" if b"LOYA_CONPTY_MARKER" in b"".join(chunks) else "missing")
"""
@unittest.skipUnless(sys.platform.startswith("win"),"ConPTY is Windows only")
class ConptyRedirectedParentTests(unittest.TestCase):
    def test_child_output_reaches_the_pseudoconsole_when_the_app_stdio_is_redirected(self):
        from Cores.Services import conpty
        if not conpty.available():self.skipTest("no ConPTY on this Windows build")
        root=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with tempfile.TemporaryDirectory() as work:
            script=os.path.join(work,"child.py")
            result_path=os.path.join(work,"result.txt")
            stdout_path=os.path.join(work,"app_output.log")
            with open(script,"w") as handle:handle.write(_REDIRECTED_PARENT_SCRIPT)
            with open(stdout_path,"wb") as stdout_file:
                subprocess.run([sys.executable,script,root,result_path],stdin=subprocess.DEVNULL,stdout=stdout_file,stderr=subprocess.STDOUT,timeout=60)
            with open(result_path) as handle:outcome=handle.read()
            with open(stdout_path,"rb") as handle:leaked=handle.read()
        self.assertEqual("in_pty",outcome)
        self.assertNotIn(b"LOYA_CONPTY_MARKER",leaked)
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
