"""Shell lists per OS, PowerShell detection and install on Linux, the default shell setting and its migration."""
import os,json,unittest
from unittest import mock
from _isolate import IsolatedData
from Cores import common_db
from Cores.Services import terminal_service as terminal
def which_from(present):
    return lambda name:("/usr/bin/"+name if not name.endswith(".exe") else "C:\\Windows\\"+name) if name in present else None
class ShellCase(unittest.TestCase):
    def setUp(self):
        self.iso=IsolatedData();self.dir=self.iso.start()
        common_db.set_locked(False)
    def tearDown(self):
        self.iso.stop()
    def store(self,ext):
        with open(os.path.join(self.dir,"settings.json"),"w",encoding="utf-8") as f:json.dump({"extensions":ext},f)
    def linux(self,present,shell="/bin/zsh"):
        return [mock.patch.object(terminal,"_IS_WINDOWS",False),mock.patch.object(terminal.shutil,"which",side_effect=which_from(present)),mock.patch.dict(os.environ,{"SHELL":shell})]
    def windows(self,present,distros=(),kali_ready=False):
        return [mock.patch.object(terminal,"_IS_WINDOWS",True),mock.patch.object(terminal.shutil,"which",side_effect=which_from(present)),mock.patch.object(terminal,"list_wsl_distros",return_value=list(distros)),mock.patch.object(terminal,"_kali_wsl_ready",return_value=kali_ready)]
    def run_with(self,patches,fn):
        for p in patches:p.start()
        try:return fn()
        finally:
            for p in reversed(patches):p.stop()
class LinuxShellTests(ShellCase):
    def test_login_shell_first_then_other_shells_and_pwsh(self):
        shells=self.run_with(self.linux({"bash","zsh","pwsh"}),terminal.list_shells)
        self.assertEqual(["shell","bash","pwsh"],[s["id"] for s in shells])
        self.assertEqual("zsh",shells[0]["label"])
        self.assertEqual("PowerShell",shells[2]["label"])
        self.assertTrue(shells[0]["default"])
    def test_no_pwsh_means_no_pwsh_session_but_an_install_offer(self):
        shells=self.run_with(self.linux({"bash","apt-get","sudo"},"/bin/bash"),terminal.list_shells)
        self.assertEqual(["shell"],[s["id"] for s in shells])
        extras=self.run_with(self.linux({"bash","apt-get","sudo"},"/bin/bash"),terminal.shell_extras)
        self.assertFalse(extras["pwsh"]["installed"])
        self.assertTrue(extras["pwsh"]["installable"])
        self.assertIn("apt-get install -y powershell",extras["pwsh"]["command"])
    def test_without_apt_the_install_is_explained_not_offered(self):
        extras=self.run_with(self.linux({"bash"},"/bin/bash"),terminal.shell_extras)
        self.assertFalse(extras["pwsh"]["installable"])
        self.assertTrue(extras["pwsh"]["reason"])
        with self.assertRaises(ValueError):self.run_with(self.linux({"bash"},"/bin/bash"),lambda:terminal._task_command("pwsh_install",{}))
    def test_installed_pwsh_is_reported_and_install_refused(self):
        extras=self.run_with(self.linux({"pwsh","apt-get","sudo"}),terminal.shell_extras)
        self.assertTrue(extras["pwsh"]["installed"]);self.assertFalse(extras["pwsh"]["installable"])
        with self.assertRaises(ValueError):self.run_with(self.linux({"pwsh","apt-get","sudo"}),lambda:terminal._task_command("pwsh_install",{}))
    def test_pwsh_install_task_is_in_terminal_sudo_with_a_fixed_argv(self):
        spec=self.run_with(self.linux({"apt-get","sudo"}),lambda:terminal._task_command("pwsh_install",{"evil":"; rm -rf /"}))
        self.assertEqual(["sudo","-p","[sudo] password for %p: ","sh","-c","apt-get update && apt-get install -y powershell"],spec["argv"])
        self.assertNotIn("pkexec",spec["argv"])
        self.assertEqual("shell",spec["shell_id"])
    def test_unknown_task_is_refused(self):
        with self.assertRaises(ValueError):self.run_with(self.linux({"bash"}),lambda:terminal._task_command("rm -rf /",{}))
    def test_shell_commands_use_the_found_binaries(self):
        def check():
            self.assertEqual(["/usr/bin/pwsh","-NoLogo","-NoExit","-Command","Remove-Module PSReadLine -ErrorAction SilentlyContinue"],terminal._shell_command("pwsh"))
            self.assertEqual(["/usr/bin/bash","-i"],terminal._shell_command("bash"))
            self.assertEqual(["/bin/zsh","-i"],terminal._shell_command("shell"))
            self.assertEqual(["/usr/bin/pwsh","-NoLogo","-NoProfile","-Command","ls"],terminal._one_shot_command("pwsh","ls"))
            self.assertEqual(["/usr/bin/bash","-lc","ls"],terminal._one_shot_command("bash","ls"))
        self.run_with(self.linux({"bash","pwsh"}),check)
    def test_linux_default_can_be_changed_to_pwsh(self):
        def go():
            terminal.set_default_shell("pwsh")
            return terminal.list_shells()
        shells=self.run_with(self.linux({"pwsh"}),go)
        self.assertEqual("pwsh",shells[0]["id"])
class WindowsShellTests(ShellCase):
    def test_default_is_pwsh_when_installed(self):
        shells=self.run_with(self.windows({"powershell.exe","pwsh.exe"}),terminal.list_shells)
        self.assertEqual("pwsh",shells[0]["id"]);self.assertTrue(shells[0]["default"])
        self.assertEqual({"cmd","powershell","pwsh"},{s["id"] for s in shells})
    def test_default_is_windows_powershell_without_pwsh(self):
        shells=self.run_with(self.windows({"powershell.exe"}),terminal.list_shells)
        self.assertEqual("powershell",shells[0]["id"])
    def test_explicit_choice_is_kept(self):
        self.store({"terminal_default_shell":"cmd"})
        shells=self.run_with(self.windows({"powershell.exe","pwsh.exe"}),terminal.list_shells)
        self.assertEqual("cmd",shells[0]["id"])
    def test_missing_explicit_choice_falls_back_without_overwriting_it(self):
        self.store({"terminal_default_shell":"pwsh","other":"kept"})
        shells=self.run_with(self.windows({"powershell.exe"}),terminal.list_shells)
        self.assertEqual("powershell",shells[0]["id"])
        with open(os.path.join(self.dir,"settings.json"),encoding="utf-8") as f:ext=json.load(f)["extensions"]
        self.assertEqual("pwsh",ext["terminal_default_shell"]);self.assertEqual("kept",ext["other"])
    def test_no_stored_value_migrates_to_auto(self):
        self.store({"terminal_enabled":True})
        settings=self.run_with(self.windows({"powershell.exe"}),terminal.get_settings)
        self.assertEqual("auto",settings["default_shell_choice"])
        self.assertEqual("windows",settings["platform"])
    def test_set_default_rejects_unknown_shells(self):
        with self.assertRaises(ValueError):self.run_with(self.windows({"powershell.exe"}),lambda:terminal.set_default_shell("calc.exe"))
        settings=self.run_with(self.windows({"powershell.exe"}),lambda:terminal.set_default_shell("auto"))
        self.assertEqual("auto",settings["default_shell_choice"])
    def test_kali_entry_only_after_setup(self):
        shells=self.run_with(self.windows({"powershell.exe"},["Ubuntu","kali-linux"],kali_ready=False),terminal.list_shells)
        labels={s["id"]:s["label"] for s in shells}
        self.assertEqual("WSL: kali-linux",labels["wsl:kali-linux"])
        self.assertEqual("WSL: Ubuntu",labels["wsl:Ubuntu"])
        shells=self.run_with(self.windows({"powershell.exe"},["Ubuntu","kali-linux"],kali_ready=True),terminal.list_shells)
        labels={s["id"]:s["label"] for s in shells}
        self.assertEqual("Kali Linux (WSL)",labels["wsl:kali-linux"])
        self.assertEqual("WSL: Ubuntu",labels["wsl:Ubuntu"])
        extras=self.run_with(self.windows({"powershell.exe"},["kali-linux"],kali_ready=True),terminal.shell_extras)
        self.assertTrue(extras["kali_ready"])
    def test_kali_ready_needs_the_distro(self):
        extras=self.run_with(self.windows({"powershell.exe"},["Ubuntu"],kali_ready=True),terminal.shell_extras)
        self.assertFalse(extras["kali_ready"])
class FakeSession:
    def __init__(self,shell_id):self.shell_id=shell_id;self.label="x";self.closed=False
    def close(self):self.closed=True
class WslSessionCloseTests(unittest.TestCase):
    def test_only_wsl_sessions_are_closed(self):
        sessions={"a":FakeSession("wsl:kali-linux"),"b":FakeSession("powershell"),"c":FakeSession("wsl:Ubuntu")}
        with mock.patch.dict(terminal._sessions,sessions,clear=True):
            closed=terminal.close_wsl_sessions("kali-linux")
            self.assertEqual(["a"],[c["session_id"] for c in closed])
            self.assertTrue(sessions["a"].closed);self.assertFalse(sessions["b"].closed);self.assertFalse(sessions["c"].closed)
            closed=terminal.close_wsl_sessions()
            self.assertEqual(["c"],[c["session_id"] for c in closed])
            self.assertFalse(sessions["b"].closed)
class PwshLinuxEchoTests(unittest.TestCase):
    """PowerShell on Linux asks for the cursor (ESC[6n) and repaints the input after every key; LOYA answers and keeps the final line."""
    def make(self):
        sess=object.__new__(terminal.TerminalSession)
        sess._initial_size=(100,30);sess._master_fd=99;sess._edit_buf=None;sess._last_line=b""
        return sess
    def test_cursor_query_is_answered_after_the_prompt(self):
        sess=self.make();written=[]
        with mock.patch.object(terminal.os,"write",side_effect=lambda fd,data:written.append((fd,data))):
            sess._answer_cursor_query(b"\x1b[94mPS>\x1b[0m \x1b[6n")
        self.assertEqual([(99,b"\x1b[30;5R")],written)
    def test_repaints_collapse_to_the_final_line(self):
        sess=self.make();written=[]
        with mock.patch.object(terminal.os,"write",side_effect=lambda fd,data:written.append(data)):
            out=sess._collapse_line_edit(b"PS> \x1b[6n")
            self.assertEqual(b"PS> \x1b[6n",out)
            self.assertEqual(b"",sess._collapse_line_edit(b"W\x1b[30;5HWr\x1b[30;5HWri"))
            self.assertEqual(b"",sess._collapse_line_edit(b"\x1b[6n\x1b[30;5HWrite-Output 1\x1b[31;3H"))
            out=sess._collapse_line_edit(b"\r\n1\r\nPS> \x1b[6n")
        self.assertEqual(b"Write-Output 1\r\n1\r\nPS> \x1b[6n",out)
        self.assertEqual([b"\x1b[30;1R"],written,"the mid-line query is answered")
        self.assertEqual(b"",sess._edit_buf,"the next prompt starts a new edit")
    def test_only_linux_pwsh_sessions_collapse(self):
        with mock.patch.object(terminal,"_IS_WINDOWS",False),mock.patch.object(terminal.TerminalSession,"_start"):
            self.assertTrue(terminal.TerminalSession("pwsh")._line_redraw_to_cr)
            self.assertFalse(terminal.TerminalSession("bash")._line_redraw_to_cr)
            self.assertFalse(terminal.TerminalSession("pwsh",command=["x"])._line_redraw_to_cr)
        with mock.patch.object(terminal,"_IS_WINDOWS",True),mock.patch.object(terminal.TerminalSession,"_start"):
            self.assertFalse(terminal.TerminalSession("pwsh")._line_redraw_to_cr)
class TerminalBlurbTests(unittest.TestCase):
    def test_extension_blurb_is_not_windows_only(self):
        here=os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here,"..","UI","pages","settings.html"),encoding="utf-8") as f:html=f.read()
        self.assertNotIn("offering CMD/PowerShell sessions",html)
        self.assertIn("your login shell",html)
        # The AI chat is wired (ai.complete, sessions): the AI Assistant card must not say it is unavailable.
        self.assertNotIn("Chat wiring is not yet available",html)
if __name__=="__main__":unittest.main()
