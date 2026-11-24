import io,os,sys,unittest
from unittest import mock
from _isolate import ROOT
import RunNote
class _Out(io.StringIO):
    def __init__(self,tty=False,encoding="utf-8"):
        super().__init__();self._tty=tty;self._enc=encoding
    def isatty(self):return self._tty
    @property
    def encoding(self):return self._enc
class LauncherConsoleTests(unittest.TestCase):
    def setUp(self):
        self.saved=dict(RunNote._UI)
        RunNote._UI.update(color=None,truecolor=False,unicode=None)
    def tearDown(self):
        RunNote._UI.clear();RunNote._UI.update(self.saved)
    def _render(self,env,tty=True,encoding="utf-8"):
        out=_Out(tty,encoding)
        with mock.patch.dict(os.environ,env,clear=False),mock.patch.object(sys,"stdout",out),mock.patch.object(RunNote,"_is_win",lambda:False):
            for k in ("NO_COLOR","FORCE_COLOR"):
                if k not in env:os.environ.pop(k,None)
            RunNote._ui_banner("1.0.0")
            RunNote._step("ok","Virtual environment ready","(cached)")
            RunNote._ui_error("boom")
        return out.getvalue()
    def test_no_color_means_no_escape_codes(self):
        text=self._render({"NO_COLOR":"1","TERM":"xterm-256color"})
        self.assertNotIn("\x1b[",text)
        self.assertIn("[  OK  ] Virtual environment ready (cached)",text)
        self.assertIn("[FAILED] ERROR: boom",text)
    def test_a_pipe_gets_no_colours(self):
        self.assertNotIn("\x1b[",self._render({"TERM":"xterm-256color"},tty=False))
    def test_a_terminal_gets_colours_and_the_block_logo(self):
        text=self._render({"TERM":"xterm-256color"})
        self.assertIn("\x1b[",text);self.assertIn("█",text)
        self.assertIn("Language Of Your Attack",text);self.assertIn("v1.0.0",text)
    def test_an_ascii_console_gets_a_plain_logo(self):
        text=self._render({"NO_COLOR":"1"},encoding="ascii")
        text.encode("ascii")
        self.assertIn("L O Y A   N G",text)
    def test_logo_rows_line_up(self):
        rows=RunNote._ui_logo_rows()
        self.assertEqual(6,len(rows));self.assertEqual(1,len({len(r) for r in rows}))
    def test_no_ai_style_punctuation_in_console_text(self):
        with open(os.path.join(ROOT,"RunNote.py"),encoding="utf-8") as f:src=f.read()
        for ch in ("—","–","…","·"):self.assertNotIn(ch,src)
    def test_version_flag_stays_plain(self):
        out=_Out(tty=True)
        with mock.patch.object(sys,"stdout",out),mock.patch.object(sys,"argv",["RunNote.py","--version"]):
            self.assertEqual(0,RunNote.main())
        self.assertEqual(f"{RunNote._UPDATE_APP_NAME} v{RunNote._get_app_version()}\n",out.getvalue())
if __name__=="__main__":unittest.main()
