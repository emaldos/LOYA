"""AI panel > Agents > "Claude Code (your CLI)" / "Codex CLI (your CLI)": the operator's own CLI opened interactively in a
terminal (Cores/Services/ext_cli_launch.py).

No CLI is run: find_cli and the OS terminal opener are mocked. Covers the state mapping, the launch line per shell (the
Sign in button's quoting), the workspace folder, and the policy guard: the CLI is only ever started bare and interactive
(never -p / --print / exec), and the chat bridge refuses the CLI entries."""
import os,re,unittest
from unittest import mock
from _isolate import IsolatedData
from Cores.Services import ext_cli_launch as cli
from Cores.Services import ext_connections_service as conn
from Cores.Bridge import ext_agents_api
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
class StateMappingTest(unittest.TestCase):
    def test_states(self):
        self.assertEqual(cli.cli_state(None),"not_installed")
        self.assertEqual(cli.cli_state({"installed":False,"connected":True}),"not_installed")
        self.assertEqual(cli.cli_state({"installed":True,"signin":{"state":"signed_out"},"connected":True}),"not_signed_in")
        self.assertEqual(cli.cli_state({"installed":True,"signin":{"state":"signed_in"},"connected":False}),"not_connected")
        self.assertEqual(cli.cli_state({"installed":True,"signin":{"state":"signed_in"},"connected":True}),"ready")
        # A sign-in LOYA NG could not read is its own state (never "not signed in"); it still allows Open in terminal.
        self.assertEqual(cli.cli_state({"installed":True,"signin":{"state":"unknown","last":"signed_out"},"connected":True}),"signin_unknown")
        self.assertEqual(cli.cli_state({"installed":True,"connected":True}),"signin_unknown")
        self.assertEqual(cli.cli_state({"installed":True,"signin":{"state":"unknown"},"connected":False}),"not_connected")
        self.assertEqual(set(cli.STATES),{"not_installed","not_signed_in","not_connected","signin_unknown","ready"})
        self.assertEqual(set(cli.LAUNCHABLE),{"signin_unknown","ready"})
    def test_same_table_as_js(self):
        with open(os.path.join(ROOT,"UI","js","components","ext-cli-launch.js"),encoding="utf-8") as f:js=f.read()
        body=js[js.index("function cliEntryState"):js.index("const CLI_STATE_VIEW")]
        self.assertEqual(re.findall(r'return "(\w+)"',body),["not_installed","not_signed_in","not_connected","signin_unknown","ready"])
class LaunchLineTest(unittest.TestCase):
    def test_posix_shell(self):
        self.assertEqual(cli.launch_line("/home/op/.local/bin/claude","shell"),"/home/op/.local/bin/claude")
        self.assertEqual(cli.launch_line("/home/op/my tools/claude","shell"),"'/home/op/my tools/claude'")
        self.assertEqual(cli.launch_line("/opt/it's/codex",""),"'/opt/it'\"'\"'s/codex'")
    def test_windows_shells(self):
        exe="C:\\Users\\O'Neil\\.local\\bin\\claude.exe"
        self.assertEqual(cli.launch_line(exe,"pwsh"),"& 'C:\\Users\\O''Neil\\.local\\bin\\claude.exe'")
        self.assertEqual(cli.launch_line(exe,"powershell"),"& 'C:\\Users\\O''Neil\\.local\\bin\\claude.exe'")
        self.assertEqual(cli.launch_line("C:\\Users\\op\\AppData\\Roaming\\npm\\codex.cmd","cmd"),'"C:\\Users\\op\\AppData\\Roaming\\npm\\codex.cmd"')
    def test_never_wsl(self):
        self.assertEqual(cli.launch_line("C:\\x\\claude.exe","wsl:kali-linux"),"")
    def test_same_quoting_as_sign_in(self):
        for sid in ("shell","pwsh","powershell","cmd","wsl:Ubuntu"):
            with mock.patch.object(conn,"find_cli",return_value=("/x y/claude","PATH")),mock.patch.object(conn,"login_args",return_value=["auth","login"]):
                self.assertEqual(conn.sign_in_command("claude_code",sid),cli.launch_line("/x y/claude",sid,["auth","login"]))
class LaunchTest(unittest.TestCase):
    def setUp(self):
        self.iso=IsolatedData();self.dir=self.iso.start()
    def tearDown(self):
        self.iso.stop()
    def _connected(self,tool):
        with open(conn.connection_file(tool),"w") as f:f.write("{}")
    def test_workspace_is_stable_per_tool_under_data(self):
        a=cli.workspace("claude_code");b=cli.workspace("codex_cli")
        self.assertTrue(os.path.isdir(a) and os.path.isdir(b))
        self.assertNotEqual(a,b)
        self.assertEqual(a,cli.workspace("claude_code"))
        self.assertEqual(os.path.commonpath([a,self.dir]),os.path.normpath(self.dir))
        self.assertTrue(a.endswith(os.path.join("external_agents","cli_workspace","claude_code")))
    def test_launch_command(self):
        self._connected("claude_code")
        with mock.patch.object(conn,"find_cli",return_value=("/opt/c c/claude","PATH")),mock.patch.object(conn,"_run") as run:
            r=cli.launch_command("claude_code","shell")
        run.assert_not_called()  # cheap: the CLI itself is not run to build the line
        self.assertEqual(r["line"],"'/opt/c c/claude'")
        self.assertEqual(r["cwd"],cli.workspace("claude_code"))
        self.assertEqual(r["name"],"Claude Code (your CLI)")
        with mock.patch.object(conn,"find_cli",return_value=("C:\\c\\claude.exe","C:\\c")):
            self.assertEqual(cli.launch_command("claude_code","pwsh")["line"],"& 'C:\\c\\claude.exe'")
            self.assertEqual(cli.launch_command("claude_code","wsl:Ubuntu")["line"],"")
    def test_refuses_when_missing_or_not_connected(self):
        with mock.patch.object(conn,"find_cli",return_value=(None,"")):
            with self.assertRaisesRegex(cli.LaunchError,"not found"):cli.launch_command("codex_cli","shell")
        with mock.patch.object(conn,"find_cli",return_value=("/bin/codex","PATH")):
            with self.assertRaisesRegex(cli.LaunchError,"not connected"):cli.launch_command("codex_cli","shell")
            with self.assertRaisesRegex(cli.LaunchError,"not connected"):cli.launch_os_terminal("codex_cli")
        with self.assertRaises(cli.LaunchError):cli.launch_command("bogus","shell")
    def test_os_terminal_runs_in_workspace(self):
        self._connected("codex_cli")
        seen={}
        def fake_open(posix,cmd_line):
            seen["posix"]=posix;seen["cmd"]=cmd_line;return {"opened":True,"terminal":"xterm"}
        with mock.patch.object(conn,"find_cli",return_value=("/opt/codex","PATH")),mock.patch.object(conn,"_open_os_terminal",side_effect=fake_open):
            r=cli.launch_os_terminal("codex_cli")
        ws=cli.workspace("codex_cli")
        self.assertEqual(r["terminal"],"xterm");self.assertEqual(r["cwd"],ws)
        self.assertTrue(seen["posix"].startswith("cd ") and seen["posix"].endswith("&& /opt/codex"),seen["posix"])
        self.assertIn(ws,seen["posix"])
        self.assertEqual(seen["cmd"],'cd /d "'+ws+'" && "/opt/codex"')
    def test_bridge_methods(self):
        self._connected("claude_code")
        api=ext_agents_api.ExternalAgentsAPI()
        with mock.patch.object(conn,"find_cli",return_value=("/bin/claude","PATH")):
            self.assertEqual(api.cli_launch_command("claude_code","shell")["line"],"/bin/claude")
class PolicyGuardTest(unittest.TestCase):
    """Anthropic Agent SDK policy: LOYA may not offer claude.ai login or rate limits. The operator's own CLI is only ever
    started bare and interactive, in a terminal they use themselves; no chat-panel path reaches it."""
    def test_cli_started_bare(self):
        self.assertEqual(cli.LAUNCH_ARGS,{"claude_code":[],"codex_cli":[]})
        self.assertEqual(set(cli.LAUNCH_ARGS),set(conn.TOOLS))
    def test_no_non_interactive_invocation_in_source(self):
        with open(cli.__file__,encoding="utf-8") as f:src=f.read()
        code="\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
        code=re.sub(r'"""[\s\S]*?"""',"",code)
        for bad in ('"-p"',"'-p'",'"--print"','"exec"',"'exec'","subprocess.run","subprocess.Popen","_conn._run("):
            self.assertNotIn(bad,code)
    def test_chat_bridge_refuses_cli_entries(self):
        api=ext_agents_api.ExternalAgentsAPI()
        for kind in ("cli:claude_code","cli:codex_cli","claude_code","codex_cli"):
            with self.assertRaises(ValueError):api.run_start(None,kind,"hello")
            with self.assertRaises(ValueError):api.status(kind)
if __name__=="__main__":unittest.main()
