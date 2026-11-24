"""plain_terminal_text: what the AI's terminal_read sees, checked against raw PTY bytes recorded from zsh (Kali's default
/etc/skel/.zshrc: syntax highlighting, autosuggestions, two-line prompt) and bash. See tests/js/terminal_shell_echo.js."""
import json,os,unittest
from Cores.Services import terminal_service as ts
FIXTURES=os.path.join(os.path.dirname(__file__),"fixtures","terminal")
def _raw(name):
    with open(os.path.join(FIXTURES,name+".json"),encoding="utf-8") as f:fx=json.load(f)
    return fx,"".join(ev["out"] for ev in fx["events"] if "out" in ev)
class PlainTerminalTextTests(unittest.TestCase):
    def _lines(self,name):
        fx,raw=_raw(name)
        text=ts.plain_terminal_text(raw,fx["cols"])
        self.assertNotIn("__LOYA_JOB__",text)
        self.assertNotIn("printf '",text)
        self.assertFalse(any(c in text for c in "\x1b\x08\r"),repr(text[:200]))
        return text.split("\n")
    def test_zsh_skel_lines_read_like_the_screen(self):
        lines=self._lines("zsh_skel")
        for cmd in ("ls","echo hello world",'echo "unterminated',"ls )","sleep 5","for i in 1 2","echo hi","false",'echo "a',"sleep 0.1 &","echo $((1+))","clear"):
            self.assertIn(("\u2514\u2500$ "+cmd).rstrip(),lines,cmd)
        self.assertIn("for> do echo $i",lines)
        self.assertIn("dquote> b\"",lines)
        self.assertIn("hello world",lines)
        self.assertIn("zsh: parse error near `)'",lines)
        self.assertIn("alpha.txt  beta.log  notes",lines)
    def test_zsh_wrapped_line_in_a_narrow_pane(self):
        lines=self._lines("zsh_skel_narrow")
        self.assertIn("\u2514\u2500$ echo hello world from a narrow pane",lines)
        self.assertIn("hello world from a narrow pane",lines)
    def test_bash(self):
        lines=self._lines("bash_skel")
        self.assertIn("\u2514\u2500$ ls )",lines)
        self.assertIn("bash: syntax error near unexpected token `)'",lines)
    def test_line_editing(self):
        self.assertEqual(ts.plain_terminal_text("ab\b\bXY\x1b[1DZ"),"XZ")
        self.assertEqual(ts.plain_terminal_text("$ "+"x"*38+" \r\x1b[Ky",40),"$ "+"x"*38+"y")
        self.assertEqual(ts.plain_terminal_text("\u327f"+"a"*38+"b",40),"\u327f"+"a"*38+"b")
        self.assertEqual(ts.plain_terminal_text("out\n__LOYA_JOB__j1|0|/x__END__\nnext"),"out\nnext")
        # Windows shells' echoed markers go too.
        self.assertEqual(ts.plain_terminal_text('C:\\>dir &call echo __LOYA_JOB__j1^|%^ERRORLEVEL%^|%^CD%__END__'),"C:\\>dir")
        self.assertEqual(ts.plain_terminal_text('PS C:\\> ls ;$LoyaOk=$?;Write-Output "__LOYA_JOB__j1|$(1)|x__END__"'),"PS C:\\> ls")
    def test_peek_plain_uses_the_session_width(self):
        class Fake:
            cols=40
            def peek(self):return "$ "+"x"*38+" \r\x1b[Ky"
        ts._sessions["fakeplain"]=Fake()
        try:self.assertEqual(ts.peek_plain("fakeplain"),"$ "+"x"*38+"y")
        finally:ts._sessions.pop("fakeplain",None)
        self.assertIsNone(ts.peek_plain("missing"))
if __name__=="__main__":
    unittest.main()
