import os,sys,time,threading,unittest
from unittest import mock
from _isolate import IsolatedData
from Cores.Services import terminal_service as terminal
def drain(session_id,needle,timeout=8):
    deadline=time.time()+timeout
    text=""
    while time.time()<deadline:
        text+=terminal.read_output(session_id) or ""
        if needle in text:return text
        time.sleep(0.02)
    return text
def spawn(code,size=(80,24),raw=False):
    sess=terminal.TerminalSession("shell",[sys.executable,"-I","-c",code],"",None,size,raw=raw)
    with terminal._lock:terminal._sessions[sess.id]=sess
    return sess.id
_SIZE_CHILD=r'''
import os,signal,sys,time
hit=[]
signal.signal(signal.SIGWINCH,lambda *a:hit.append(1))
c,r=os.get_terminal_size(0)
print("START %d %d"%(c,r),flush=True)
deadline=time.time()+10
while not hit and time.time()<deadline:time.sleep(0.02)
c,r=os.get_terminal_size(0)
print("SIZE %d %d"%(c,r),flush=True)
'''
_ECHO_CHILD=r'''
import os,tty
tty.setraw(0)
os.write(1,b"READY\r\n")
want=%d
data=b""
while len(data)<want:data+=os.read(0,want-len(data))
os.write(1,b"HEX "+data.hex().encode()+b" END\r\n")
'''
_DSR_CHILD=r'''
import os,select,tty
tty.setraw(0)
os.write(1,b"Q\x1b[6n")
r,_,_=select.select([0],[],[],%s)
ans=os.read(0,64) if r else b""
os.write(1,b"\r\nANS "+(ans.hex().encode() or b"none")+b" END\r\n")
'''
@unittest.skipIf(terminal._IS_WINDOWS,"posix only - run under WSL or a real Linux desktop")
class PosixEmulatorTests(unittest.TestCase):
    def setUp(self):
        self.isolated=IsolatedData()
        self.isolated.start()
    def tearDown(self):
        terminal.close_all_sessions()
        self.isolated.stop()
    def test_resize_reaches_the_child_and_is_remembered(self):
        sid=spawn(_SIZE_CHILD)
        self.assertIn("START 80 24",drain(sid,"START"))
        self.assertTrue(terminal.resize_session(sid,100,40))
        self.assertIn("SIZE 100 40",drain(sid,"SIZE"))
        sess=terminal._sessions[sid]
        self.assertEqual((100,40),(sess.cols,sess.rows))
        self.assertEqual(40,sess._dsr_rows(),"the DSR answer follows the current grid, not the start size")
    def test_out_of_range_resize_is_ignored(self):
        sid=spawn(_SIZE_CHILD)
        drain(sid,"START")
        for cols,rows in ((0,0),(5,40),(100,2),(5000,40),(100,900),("x",40),(None,None)):
            self.assertFalse(terminal.resize_session(sid,cols,rows),(cols,rows))
        sess=terminal._sessions[sid]
        self.assertEqual((80,24),(sess.cols,sess.rows))
    def test_control_bytes_reach_the_child_unchanged(self):
        payload="\x03\x1b[A\x1b[200~hi\x1b[201~\x7f\t\x1b"
        sid=spawn(_ECHO_CHILD%len(payload.encode()),raw=True)
        self.assertIn("READY",drain(sid,"READY"))
        self.assertTrue(terminal.write_input(sid,payload))
        out=drain(sid,"END")
        self.assertIn("HEX "+payload.encode().hex()+" END",out)
    def test_dsr_is_answered_when_raw_is_off(self):
        sid=spawn(_DSR_CHILD%"5")
        out=drain(sid,"END")
        self.assertIn("ANS "+b"\x1b[24;2R".hex()+" END",out)
    def test_dsr_is_left_to_the_emulator_when_raw_is_on(self):
        sid=spawn(_DSR_CHILD%"0.6",raw=True)
        out=drain(sid,"END")
        self.assertIn("ANS none END",out)
        self.assertIn("\x1b[6n",out,"the query reaches xterm.js, which answers it itself")
    def test_emulator_session_is_raw_and_reports_pty(self):
        sid=terminal.create_session(terminal.list_shells()[0]["id"],cols=90,rows=30,emulator=True)
        sess=terminal._sessions[sid]
        self.assertTrue(sess.raw)
        self.assertEqual("pipe",sess.backend,"the session attribute keeps its old value for existing readers")
        self.assertEqual({"raw":True,"backend":"pty"},terminal.set_session_raw(sid,True))
        self.assertEqual({"raw":False,"backend":"pty"},terminal.set_session_raw(sid,False))
        self.assertFalse(sess.raw)
    def test_plain_session_is_not_raw(self):
        sid=terminal.create_session(terminal.list_shells()[0]["id"])
        self.assertFalse(terminal._sessions[sid].raw)
class RawFilterTests(unittest.TestCase):
    def make(self):
        with mock.patch.object(terminal,"_IS_WINDOWS",False),mock.patch.object(terminal.TerminalSession,"_start"):
            sess=terminal.TerminalSession("pwsh",size=(100,30))
        sess._master_fd=99
        self.assertTrue(sess._line_redraw_to_cr)
        return sess
    def test_toggling_raw_on_flushes_the_held_edit_line(self):
        sess=self.make();written=[]
        with mock.patch.object(terminal.os,"write",side_effect=lambda fd,data:written.append(data)):
            sess._filter_and_append(b"PS> \x1b[6n")
            sess._filter_and_append(b"W\x1b[30;5HWr")
        self.assertEqual("PS> \x1b[6n",sess.read())
        self.assertEqual(b"W\x1b[30;5HWr",sess._edit_buf)
        self.assertTrue(sess.set_raw(True))
        self.assertIsNone(sess._edit_buf)
        self.assertEqual("W\x1b[30;5HWr",sess.read(),"the held bytes are not lost")
        with mock.patch.object(terminal.os,"write",side_effect=lambda fd,data:written.append(data)):
            sess._filter_and_append(b"i\x1b[6n")
        self.assertEqual("i\x1b[6n",sess.read())
        self.assertEqual([b"\x1b[30;5R"],written,"only the query from before the switch was answered")
    def test_raw_set_directly_still_releases_the_held_line(self):
        sess=self.make();sess._edit_buf=b"held";sess.raw=True
        sess._filter_and_append(b"+next")
        self.assertEqual("held+next",sess.read())
        self.assertIsNone(sess._edit_buf)
    def test_raw_off_again_restores_the_filters(self):
        sess=self.make();written=[]
        sess.set_raw(True);sess.set_raw(False)
        with mock.patch.object(terminal.os,"write",side_effect=lambda fd,data:written.append(data)):
            sess._filter_and_append(b"PS> \x1b[6n")
        self.assertEqual([b"\x1b[30;5R"],written)
        self.assertEqual(b"",sess._edit_buf)
class FakeConpty:
    def __init__(self):
        self.created=[]
        module=self
        class ConptySession:
            def __init__(self,cmd,cols=120,rows=30,cwd=None,env=None):
                self.cmd=cmd;self.cols=cols;self.rows=rows;self.resizes=[];self.writes=[];self._done=threading.Event()
                module.created.append(self)
            def read(self,size):
                self._done.wait(10)
                return b""
            def write(self,data):
                self.writes.append(data)
                return True
            def resize(self,cols,rows):
                self.resizes.append((cols,rows))
                return True
            def alive(self):return not self._done.is_set()
            def close(self):self._done.set()
        self.ConptySession=ConptySession
    def available(self):return True
class WindowsConptySymmetryTests(unittest.TestCase):
    def setUp(self):
        self.isolated=IsolatedData()
        self.isolated.start()
        self.fake=FakeConpty()
        shells=[{"id":"cmd","label":"Command Prompt"}]
        self.patches=[mock.patch.object(terminal,"_IS_WINDOWS",True),mock.patch.object(terminal,"_conpty",lambda:self.fake),mock.patch.object(terminal,"_CONPTY_PROBE_SECONDS",0),mock.patch.object(terminal,"list_shells",lambda:shells)]
        for p in self.patches:p.start()
        self.assertFalse(terminal.get_settings()["use_conpty"])
    def tearDown(self):
        terminal.close_all_sessions()
        for p in reversed(self.patches):p.stop()
        self.isolated.stop()
    def test_emulator_session_uses_conpty_at_the_initial_size(self):
        sid=terminal.create_session("cmd",cols=110,rows=35,emulator=True)
        sess=terminal._sessions[sid]
        self.assertEqual(1,len(self.fake.created),"emulator sessions ask for ConPTY even with use_conpty off")
        con=self.fake.created[0]
        self.assertEqual((110,35),(con.cols,con.rows))
        self.assertEqual("conpty",sess.backend)
        self.assertTrue(sess.raw)
        self.assertEqual({"raw":True,"backend":"conpty"},terminal.set_session_raw(sid,True))
        self.assertEqual({"raw":False,"backend":"conpty"},terminal.set_session_raw(sid,False))
    def test_conpty_falls_back_to_120x30_without_a_size(self):
        terminal.create_session("cmd",emulator=True)
        self.assertEqual((120,30),(self.fake.created[0].cols,self.fake.created[0].rows))
    def test_resize_delegates_validated_values(self):
        sid=terminal.create_session("cmd",cols=110,rows=35,emulator=True)
        con=self.fake.created[0]
        self.assertTrue(terminal.resize_session(sid,"132","50"))
        self.assertFalse(terminal.resize_session(sid,3,50))
        self.assertFalse(terminal.resize_session(sid,132,9999))
        self.assertEqual([(132,50)],con.resizes)
        sess=terminal._sessions[sid]
        self.assertEqual((132,50),(sess.cols,sess.rows))
    def test_write_passes_raw_bytes(self):
        sid=terminal.create_session("cmd",cols=110,rows=35,emulator=True)
        payload="\x03\x1b[A\x1b[200~hi\x1b[201~\x7f\t\x1b"
        self.assertTrue(terminal.write_input(sid,payload))
        self.assertEqual([payload.encode()],self.fake.created[0].writes)
    def test_plain_session_keeps_the_pipe_with_the_setting_off(self):
        proc=mock.MagicMock()
        proc.stdout.read.return_value=b""
        with mock.patch.object(terminal.subprocess,"Popen",return_value=proc),mock.patch.object(terminal.subprocess,"CREATE_NO_WINDOW",0,create=True):
            sid=terminal.create_session("cmd",cols=110,rows=35)
        self.assertEqual([],self.fake.created)
        self.assertEqual({"raw":True,"backend":"pipe"},terminal.set_session_raw(sid,True),"the UI warns: a pipe session cannot host a TUI")
class ElevatedRawTests(unittest.TestCase):
    def test_elevated_session_stores_the_flag(self):
        with mock.patch.object(terminal.ElevatedSession,"_start"):sess=terminal.ElevatedSession("cmd")
        with mock.patch.dict(terminal._sessions,{sess.id:sess},clear=True):
            self.assertEqual({"raw":True,"backend":"elevated"},terminal.set_session_raw(sess.id,True))
            self.assertTrue(sess.raw)
    def test_session_without_a_setter_gets_the_attribute(self):
        class Bare:pass
        bare=Bare()
        with mock.patch.dict(terminal._sessions,{"b":bare},clear=True):
            self.assertEqual({"raw":True,"backend":"pipe"},terminal.set_session_raw("b",1))
    def test_unknown_session_raises(self):
        with self.assertRaises(ValueError):terminal.set_session_raw("nope",True)
class BridgeTests(unittest.TestCase):
    def test_terminal_api_exposes_set_raw_and_emulator(self):
        import inspect
        from Cores.Bridge import api
        self.assertIn("emulator",inspect.signature(api.TerminalAPI.create).parameters)
        self.assertEqual(False,inspect.signature(api.TerminalAPI.create).parameters["emulator"].default)
        t=api.TerminalAPI()
        with mock.patch.object(api._terminal_svc,"create_session",return_value="sid") as create:
            self.assertEqual("sid",t.create("shell",None,90,30,"","","",True))
        self.assertEqual(True,create.call_args[0][7])
        with mock.patch.object(api._terminal_svc,"set_session_raw",return_value={"raw":True,"backend":"pty"}) as setter:
            self.assertEqual({"raw":True,"backend":"pty"},t.set_raw("sid",True))
        setter.assert_called_once_with("sid",True)
class FullTerminalSettingTests(unittest.TestCase):
    def setUp(self):
        self.isolated=IsolatedData()
        self.isolated.start()
    def tearDown(self):
        self.isolated.stop()
    def test_default_is_off(self):
        self.assertIs(False,terminal.get_settings()["full_terminal_default"])
    def test_saved_and_read_back(self):
        self.assertIs(True,terminal.set_run_behaviour({"full_terminal_default":True})["full_terminal_default"])
        self.assertIs(True,terminal.get_settings()["full_terminal_default"])
        self.assertIs(False,terminal.set_run_behaviour({"full_terminal_default":False})["full_terminal_default"])
    def test_other_saves_keep_it(self):
        terminal.set_run_behaviour({"full_terminal_default":True})
        terminal.set_run_behaviour({"confirm_multiline_paste":False})
        self.assertIs(True,terminal.get_settings()["full_terminal_default"])
class BackendOfTests(unittest.TestCase):
    def test_unknown_id_is_none(self):
        self.assertIsNone(terminal.session_backend_of("no-such-session"))
    def test_matches_session_backend(self):
        sess=terminal.ElevatedSession.__new__(terminal.ElevatedSession)
        sess.backend="elevated"
        with terminal._lock:terminal._sessions["bk1"]=sess
        try:self.assertEqual(terminal.session_backend(sess),terminal.session_backend_of("bk1"))
        finally:terminal._sessions.pop("bk1",None)
if __name__=="__main__":unittest.main()
