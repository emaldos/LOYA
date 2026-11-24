"""Settings > AI > Agents > Connections: the operator's own Claude Code / Codex CLI connected to LOYA's MCP server.

No real CLI is run and no real config is touched: HOME, CLAUDE_CONFIG_DIR and CODEX_HOME point into a temp folder and
`claude` / `codex` are fake scripts on PATH that log their argv and answer like the real commands. The MCP traffic is real:
the stdio bridge is run as a child process against the in-app HTTP server on a free port."""
import json,os,signal,socket,stat,subprocess,sys,tempfile,textwrap,time,unittest
from unittest import mock
from _isolate import IsolatedData
from Cores import common_db
from Cores.Services import ai_service as ai
from Cores.Services import mcp_local_service as mcp
from Cores.Services import security_service as security
from Cores.Services import ext_agents_service as ext
from Cores.Services import ext_connections_service as conn
FAKE=r'''
import json,os,sys,time
name=sys.argv[1];args=sys.argv[2:]
home=os.environ["HOME"]
with open(os.path.join(home,"cli_calls.log"),"a") as f:f.write(json.dumps([name]+args)+"\n")
hang_p=os.path.join(home,name+"_hang.json")  # test hook: hang on these leading args, pid in <name>_hang.pid
if os.path.exists(hang_p):
    h=json.load(open(hang_p))
    if args[:len(h["args"])]==h["args"]:
        pid_p=os.path.join(home,name+"_hang.pid")
        with open(pid_p+".tmp","w") as f:f.write(str(os.getpid()))
        os.replace(pid_p+".tmp",pid_p)
        time.sleep(h.get("secs",30))
state_p=os.path.join(home,name+"_state.json")
state=json.load(open(state_p)) if os.path.exists(state_p) else {}
def save():json.dump(state,open(state_p,"w"))
old=os.path.exists(os.path.join(home,name+"_old"))
if args==["--version"]:print("2.1.400 (Claude Code)" if name=="claude" else "codex-cli 0.120.0");sys.exit(0)
if name=="claude":
    if args==["auth","--help"]:
        print("Usage: claude auth [options] [command]\n\nCommands:\n"+("" if old else "  login [options]   Sign in\n  logout   Log out\n  status [options]  Show authentication status\n"));sys.exit(0)
    if args==["auth","status"]:
        if state.get("signed"):print(json.dumps({"loggedIn":True,"authMethod":"claude.ai","email":"op@example.test","configDirectory":home}));sys.exit(0)
        print(json.dumps({"loggedIn":False,"authMethod":"none"}));sys.exit(1)
    if args[:2]==["mcp","add"]:
        i=args.index("--");state.setdefault("mcp",{})[args[i-1]]={"opts":args[2:i-1],"cmd":args[i+1:]};save();print("Added stdio MCP server");sys.exit(0)
    if args[:2]==["mcp","remove"]:
        if args[-1] in state.get("mcp",{}):state["mcp"].pop(args[-1]);save();sys.exit(0)
        print('No MCP server found with name: "%s"'%args[-1],file=sys.stderr);sys.exit(1)
    if args[:2]==["mcp","get"]:
        sys.exit(0 if args[2] in state.get("mcp",{}) else 1)
else:
    if args==["login","--help"]:
        print("Manage login\n\nUsage: codex login [OPTIONS] [COMMAND]\n\nCommands:\n"+("" if old else "  status  Show login status\n")+"  help    Print this message");sys.exit(0)
    if args==["login","status"]:
        if state.get("signed"):print("Logged in using ChatGPT");sys.exit(0)
        print("Not logged in");sys.exit(1)
    if args[:2]==["mcp","add"]:
        i=args.index("--");state.setdefault("mcp",{})[args[2]]={"cmd":args[i+1:]};save();sys.exit(0)
    if args[:2]==["mcp","remove"]:
        state.get("mcp",{}).pop(args[2],None);save();sys.exit(0)
    if args[:2]==["mcp","get"]:
        sys.exit(0 if args[2] in state.get("mcp",{}) else 1)
print("error: unexpected argument "+" ".join(args),file=sys.stderr);sys.exit(2)
'''
INIT={"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}
def free_port():
    s=socket.socket();s.bind(("127.0.0.1",0));p=s.getsockname()[1];s.close();return p
class Env:
    """Temp HOME / CLAUDE_CONFIG_DIR / CODEX_HOME and fake CLIs first on PATH."""
    KEYS=("HOME","USERPROFILE","CLAUDE_CONFIG_DIR","CODEX_HOME","PATH")
    def start(self):
        self.tmp=tempfile.mkdtemp(prefix="loya_conn_")
        self.home=os.path.join(self.tmp,"home");self.bin=os.path.join(self.tmp,"bin")
        os.makedirs(self.home);os.makedirs(self.bin)
        self.saved={k:os.environ.get(k) for k in self.KEYS}
        with open(os.path.join(self.bin,"fake_cli.py"),"w") as f:f.write(FAKE)
        for name in ("claude","codex"):
            p=os.path.join(self.bin,name)
            with open(p,"w") as f:f.write(f"#!/bin/sh\nexec '{sys.executable}' '{os.path.join(self.bin,'fake_cli.py')}' {name} \"$@\"\n")
            os.chmod(p,0o755)
        os.environ.update({"HOME":self.home,"USERPROFILE":self.home,"CLAUDE_CONFIG_DIR":os.path.join(self.home,"claude-config"),"CODEX_HOME":os.path.join(self.home,"codex-home"),"PATH":self.bin+os.pathsep+"/usr/bin"+os.pathsep+"/bin"})
        conn._help_cache.clear()
        return self
    def stop(self):
        for k,v in self.saved.items():
            if v is None:os.environ.pop(k,None)
            else:os.environ[k]=v
        conn._help_cache.clear()
        import shutil;shutil.rmtree(self.tmp,ignore_errors=True)
    def calls(self):
        p=os.path.join(self.home,"cli_calls.log")
        return [json.loads(l) for l in open(p)] if os.path.exists(p) else []
    def state(self,name):
        p=os.path.join(self.home,name+"_state.json")
        return json.load(open(p)) if os.path.exists(p) else {}
    def set_state(self,name,**kw):
        d=self.state(name);d.update(kw)
        json.dump(d,open(os.path.join(self.home,name+"_state.json"),"w"))
    def hang(self,name,args,secs=30):
        """The fake `name` sleeps `secs` when called with these leading args (and writes its pid first)."""
        json.dump({"args":args,"secs":secs},open(os.path.join(self.home,name+"_hang.json"),"w"))
        return os.path.join(self.home,name+"_hang.pid")
def wait_for(cond,timeout):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        if cond():return True
        time.sleep(0.05)
    return bool(cond())
def pid_gone(pid):
    """True when the process no longer exists (a zombie waiting for its parent counts as gone)."""
    if os.path.isdir("/proc"):
        try:
            with open(f"/proc/{pid}/stat") as f:return f.read().rsplit(")",1)[1].split()[0] in ("Z","X")
        except (FileNotFoundError,ProcessLookupError):return True
    try:os.kill(pid,0)
    except ProcessLookupError:return True
    except PermissionError:return False
    return False
def read_pid(path,timeout=10):
    if not wait_for(lambda:os.path.exists(path) and open(path).read().strip(),timeout):raise AssertionError("no pid file "+path)
    return int(open(path).read().strip())
@unittest.skipIf(os.name=="nt","fake CLIs are POSIX shell scripts")
class ConnectionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.iso=IsolatedData();cls.iso.start()
        cls.port=free_port()
        mcp.start_server(cls.port,register_provider=False)
    @classmethod
    def tearDownClass(cls):
        mcp.stop_server()
        common_db.set_locked(False)
        cls.iso.stop()
    def setUp(self):
        self.env=Env().start()
        self.real_home=self.env.saved["HOME"]
    def tearDown(self):
        for t in conn.TOOLS:conn._delete_conn(t)
        common_db.set_locked(False)
        ai.revoke_session_grant()
        self.env.stop()
    # ---- detection and sign-in status
    def test_detects_cli_path_and_version(self):
        st=conn.status("claude_code")
        self.assertTrue(st["installed"]);self.assertEqual(os.path.join(self.env.bin,"claude"),st["path"]);self.assertEqual("PATH",st["found_in"])
        self.assertEqual("2.1.400 (Claude Code)",st["version"])
        self.assertEqual("codex-cli 0.120.0",conn.status("codex_cli")["version"])
        self.assertEqual("claude auth login",st["login_command"])
    def test_not_installed_shows_install_instructions(self):
        os.environ["PATH"]="/nonexistent"
        st=conn.status("codex_cli")
        self.assertFalse(st["installed"]);self.assertTrue(st["docs"].startswith("https://"))
        self.assertEqual(["native","npm"],[m["id"] for m in st["install_methods"]])
        self.assertIn("@openai/codex",st["install_methods"][1]["commands"]["posix"])
    def test_found_in_install_folder_when_not_on_path(self):
        os.environ["PATH"]="/nonexistent"
        d=os.path.join(self.env.home,".local","bin");os.makedirs(d)
        os.symlink(os.path.join(self.env.bin,"claude"),os.path.join(d,"claude"))
        path,how=conn.find_cli("claude_code")
        self.assertEqual(os.path.join(d,"claude"),path);self.assertEqual(d,how)
    def test_signin_status_comes_from_the_cli(self):
        self.assertEqual("signed_out",conn.signin_status("claude_code")["state"])
        self.env.set_state("claude",signed=True)
        s=conn.signin_status("claude_code")
        self.assertEqual("signed_in",s["state"]);self.assertIn("Claude account",s["detail"])
        self.assertEqual("signed_out",conn.signin_status("codex_cli")["state"])
        self.env.set_state("codex",signed=True)
        self.assertEqual({"state":"signed_in","detail":"Logged in using ChatGPT"},conn.signin_status("codex_cli"))
        self.assertIn(["claude","auth","status"],self.env.calls());self.assertIn(["codex","login","status"],self.env.calls())
    def test_old_cli_is_never_given_an_unknown_subcommand(self):
        open(os.path.join(self.env.home,"claude_old"),"w").close()
        self.assertEqual("unknown",conn.signin_status("claude_code")["state"])
        self.assertNotIn(["claude","auth","status"],self.env.calls())
        self.assertEqual([],conn.login_args("claude_code",conn.find_cli("claude_code")[0]))  # start `claude`, then /login
    def test_never_reads_cli_credentials(self):
        cred=os.path.join(os.environ["CLAUDE_CONFIG_DIR"],".credentials.json");os.makedirs(os.path.dirname(cred))
        with open(cred,"w") as f:f.write('{"secret":"TEST-should-not-be-read"}')
        os.chmod(cred,0)  # any attempt to read it would fail loudly
        try:
            conn.status("claude_code");conn.connect("claude_code");conn.disconnect("claude_code")
        finally:os.chmod(cred,0o600)
        for t in conn.TOOLS:self.assertNotIn("TEST-should-not-be-read",json.dumps(conn.status(t)))
    # ---- connect / disconnect
    def test_connect_registers_with_the_clis_own_command_and_installs_skills(self):
        r=conn.connect("claude_code")
        self.assertTrue(r["connected"])
        add=[c for c in self.env.calls() if c[:3]==["claude","mcp","add"]][-1]
        i=add.index("--")
        self.assertEqual(["claude","mcp","add","--scope","user","--transport","stdio","loya-note"],add[:i])
        self.assertEqual([conn.bridge_python(),"-I",conn.bridge_script(),"--client","claude_code","--token-file",conn.connection_file("claude_code")],add[i+1:])
        f=conn.connection_file("claude_code")
        self.assertEqual(0o600,stat.S_IMODE(os.stat(f).st_mode))
        self.assertTrue(f.startswith(self.iso.dir))
        tok=json.load(open(f))["token"]
        self.assertNotIn(tok,json.dumps(self.env.state("claude")))  # the token is never in the CLI's config
        sk=os.path.join(os.environ["CLAUDE_CONFIG_DIR"],"skills","loya-basics","SKILL.md")
        self.assertTrue(os.path.isfile(sk))
        self.assertIn("loya-basics",r["skills"])
        self.assertFalse(os.path.exists(os.path.join(self.real_home or "/nonexistent-home","claude-config")))
        c=conn.connect("codex_cli")
        self.assertTrue(c["connected"])
        add=[c for c in self.env.calls() if c[:3]==["codex","mcp","add"]][-1]
        self.assertEqual(["codex","mcp","add","loya-note","--"],add[:5])
        self.assertTrue(os.path.isfile(os.path.join(self.env.home,".agents","skills","loya-basics","SKILL.md")))
        self.assertTrue(any(e["event"]=="ext_connection" and "Claude Code connected" in e["detail"] for e in security.list_audit_events(50)))
    def test_reconnect_rotates_the_token(self):
        conn.connect("claude_code");t1=json.load(open(conn.connection_file("claude_code")))["token"]
        conn.connect("claude_code");t2=json.load(open(conn.connection_file("claude_code")))["token"]
        self.assertNotEqual(t1,t2);self.assertIsNone(mcp.resolve_token(t1));self.assertIsNotNone(mcp.resolve_token(t2))
        removes=[c for c in self.env.calls() if c[:3]==["claude","mcp","remove"]]
        self.assertTrue(all(c==["claude","mcp","remove","--scope","user","loya-note"] for c in removes))
    def test_disconnect_revokes_and_removes_only_untouched_skills(self):
        conn.connect("claude_code")
        tok=json.load(open(conn.connection_file("claude_code")))["token"]
        self.assertEqual("Claude Code (your CLI)",mcp.resolve_token(tok)["label"])
        edited=os.path.join(os.environ["CLAUDE_CONFIG_DIR"],"skills","loya-notes","SKILL.md")
        with open(edited,"a") as f:f.write("\nmy own note\n")
        r=conn.disconnect("claude_code")
        self.assertFalse(r["connected"]);self.assertIsNone(mcp.resolve_token(tok))
        self.assertNotIn("loya-note",self.env.state("claude").get("mcp",{}))
        self.assertFalse(os.path.exists(os.path.join(os.environ["CLAUDE_CONFIG_DIR"],"skills","loya-basics")))
        self.assertTrue(os.path.isfile(edited))
    def test_failed_registration_leaves_nothing_behind(self):
        with open(os.path.join(self.env.bin,"codex"),"w") as f:f.write("#!/bin/sh\necho 'error: boom' >&2\nexit 3\n")
        with self.assertRaises(conn.ConnectionError_) as cx:conn.connect("codex_cli")
        self.assertIn("boom",str(cx.exception))
        self.assertFalse(os.path.exists(conn.connection_file("codex_cli")))
    # ---- the CLI's MCP traffic goes through AI Roles
    def bridge(self,tool,msgs):
        p=subprocess.run([sys.executable,"-I",conn.bridge_script(),"--client",tool,"--token-file",conn.connection_file(tool)],input="".join(json.dumps(m)+"\n" for m in msgs),capture_output=True,text=True,timeout=60)
        return [json.loads(l) for l in p.stdout.splitlines() if l.strip()]
    def call(self,tool,name,args):
        out=self.bridge(tool,[INIT,{"jsonrpc":"2.0","method":"notifications/initialized"},{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":name,"arguments":args}}])
        return {m.get("id"):m for m in out}
    def test_cli_calls_are_gated_by_ai_roles(self):
        conn.connect("claude_code")
        out=self.call("claude_code","notes_list",{})
        self.assertTrue(out[1]["result"]["serverInfo"]["name"].startswith("LOYA"))
        self.assertFalse(out[2]["result"].get("isError"),out[2])
        out=self.call("claude_code","notes_delete",{"note_id":1})
        self.assertTrue(out[2]["result"].get("isError"))
        self.assertIn("Deny",json.dumps(out[2]))
        rows=[e["detail"] for e in security.list_audit_events(80) if e["event"]=="ai_tool"]
        self.assertTrue(any(d.startswith("[Claude Code (your CLI)] notes_list - allowed") for d in rows),rows[:5])
        self.assertTrue(any(d.startswith("[Claude Code (your CLI)] notes_delete - denied by AI Roles") for d in rows),rows[:5])
    def test_every_registered_tool_authorizes_for_cli_sessions(self):
        """Deny everything, then call every tool the server offers through the CLI bridge: each must be refused by AI Roles."""
        conn.connect("codex_cli")
        out=self.bridge("codex_cli",[INIT,{"jsonrpc":"2.0","method":"notifications/initialized"},{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}])
        listed={m.get("id"):m for m in out}[2]["result"]["tools"]
        tools=[t["name"] for t in listed]
        def sample(schema):
            t=schema.get("type") or next((x.get("type") for x in schema.get("anyOf",[]) if x.get("type")!="null"),"string")
            return {"integer":1,"number":1,"boolean":False,"array":[1],"object":{}}.get(t,"x")
        # Every argument filled in, so a tool that checks its input before AI Roles still reaches AI Roles.
        call_args={t["name"]:{k:sample(v) for k,v in (t.get("inputSchema") or {}).get("properties",{}).items()} for t in listed}
        self.assertGreater(len(tools),50)
        before=ai.get_permission_levels()
        ai.set_permission_levels({k:"deny" for k in before})
        try:
            msgs=[INIT,{"jsonrpc":"2.0","method":"notifications/initialized"}]+[{"jsonrpc":"2.0","id":100+i,"method":"tools/call","params":{"name":n,"arguments":call_args[n]}} for i,n in enumerate(tools)]
            got={m.get("id"):m for m in self.bridge("codex_cli",msgs)}
        finally:
            ai.set_permission_levels(before)
        rows=[e["detail"] for e in security.list_audit_events(2000) if e["event"]=="ai_tool"]
        for i,n in enumerate(tools):
            m=got.get(100+i)
            self.assertIsNotNone(m,n)
            self.assertTrue((m.get("result") or {}).get("isError") or m.get("error"),n)
        denied={d.split("] ",1)[1].split(" - ")[0] for d in rows if d.startswith("[Codex CLI (your CLI)]") and ("denied by AI Roles" in d or "not covered" in d)}
        self.assertEqual(set(tools)-denied,set(),"tools that did not go through AI Roles for a CLI session")
    def test_locked_app_and_stopped_server_are_reported(self):
        conn.connect("claude_code")
        common_db.set_locked(True)
        out={m.get("id"):m for m in self.bridge("claude_code",[INIT])}
        self.assertIn("locked",out[1]["error"]["message"])
        common_db.set_locked(False)
        f=conn.connection_file("claude_code");d=json.load(open(f));d["port"]=free_port();json.dump(d,open(f,"w"))
        out={m.get("id"):m for m in self.bridge("claude_code",[INIT])}
        self.assertIn("not running",out[1]["error"]["message"])
    def test_unknown_token_is_refused(self):
        conn.connect("claude_code")
        self.assertIsNone(mcp.resolve_token("probe"))  # LOYA now holds the issued token
        f=conn.connection_file("claude_code");d=json.load(open(f));d["token"]="x"*43;json.dump(d,open(f,"w"))
        out={m.get("id"):m for m in self.bridge("claude_code",[INIT])}
        self.assertIn("refused",out[1]["error"]["message"])
    def test_test_connection_runs_the_real_path(self):
        self.assertFalse(conn.test_connection("claude_code")["ok"])
        conn.connect("claude_code")
        r=conn.test_connection("claude_code")
        self.assertTrue(r["ok"],r)
        self.assertIn("tools offered",[s for s in r["steps"] if s["name"]=="Bridge to LOYA NG"][0]["detail"])
        self.assertIn(["claude","mcp","get","loya-note"],self.env.calls())
    def test_port_follows_the_running_server(self):
        conn.connect("codex_cli")
        f=conn.connection_file("codex_cli");d=json.load(open(f));d["port"]=1;json.dump(d,open(f,"w"))
        conn._refresh_cache()
        conn.status("codex_cli")
        self.assertEqual(self.port,json.load(open(f))["port"])
    # ---- sign in
    def test_sign_in_command_per_shell(self):
        cli=os.path.join(self.env.bin,"claude")
        self.assertEqual(f"'{cli}' auth login" if " " in cli else f"{cli} auth login",conn.sign_in_command("claude_code","shell"))
        self.assertEqual(f"& '{cli}' auth login",conn.sign_in_command("claude_code","pwsh"))
        self.assertEqual(f'"{cli}" auth login',conn.sign_in_command("claude_code","cmd"))
        self.assertEqual("",conn.sign_in_command("claude_code","wsl:kali-linux"))
        self.assertTrue(conn.sign_in_command("codex_cli","shell").endswith("codex login"))
    def test_autostart_only_when_connected(self):
        self.assertFalse(conn.autostart())
        conn.connect("codex_cli")
        self.assertTrue(conn.autostart())
    # ---- a CLI that hangs, or leaves a helper running, never holds a call (the setup dialog hung on this)
    def script(self,name,body):
        p=os.path.join(self.env.bin,name)
        with open(p,"w") as f:f.write("#!/bin/sh\n"+body+"\n")
        os.chmod(p,0o755)
        return p
    def kill_later(self,pid):
        def k():
            try:os.kill(pid,signal.SIGKILL)
            except OSError:pass
        self.addCleanup(k)
    def test_run_returns_when_cli_leaves_a_helper_holding_stdout(self):
        pidf=os.path.join(self.env.tmp,"helper.pid")
        p=self.script("leaves_helper",f"sleep 60 &\necho $! > '{pidf}.tmp'; mv '{pidf}.tmp' '{pidf}'\necho hello\necho oops >&2\nexit 0")
        t=time.monotonic()
        rc,out,err=conn._run([p],timeout=5)
        took=time.monotonic()-t
        self.kill_later(read_pid(pidf))
        self.assertLess(took,2.5)
        self.assertEqual((0,"hello\n","oops\n"),(rc,out,err))
    def test_run_timeout_kills_the_whole_process_group(self):
        pidf=os.path.join(self.env.tmp,"child.pid")
        p=self.script("hangs",f"echo started\nsleep 60 &\necho $! > '{pidf}.tmp'; mv '{pidf}.tmp' '{pidf}'\nwait")
        t=time.monotonic()
        rc,out,err=conn._run([p],timeout=1)
        took=time.monotonic()-t
        child=read_pid(pidf,1);self.kill_later(child)
        self.assertLess(took,3)
        self.assertEqual(124,rc);self.assertTrue(err.endswith("timed out"),err);self.assertEqual("started\n",out)
        self.assertTrue(wait_for(lambda:pid_gone(child),2),"the CLI's child survived the timeout")
    def test_run_gives_the_cli_no_stdin(self):
        p=self.script("reads_stdin",'read line\necho "got:[$line]"')
        t=time.monotonic()
        rc,out,_err=conn._run([p],timeout=10)
        self.assertLess(time.monotonic()-t,2)
        self.assertNotEqual(124,rc);self.assertIn("got:[]",out)
    def test_run_missing_program(self):
        rc,_o,err=conn._run([os.path.join(self.env.bin,"nope")],timeout=5)
        self.assertEqual(127,rc);self.assertTrue(err)
    # ---- background jobs
    def poll_until_done(self,jid,timeout=30):
        r={}
        def done():
            r.update(conn.job_poll(jid));return r["done"]
        self.assertTrue(wait_for(done,timeout),r)
        return r
    def test_job_returns_at_once_and_cancel_stops_the_cli(self):
        pidf=self.env.hang("claude",["--version"],30)
        t=time.monotonic()
        jid=conn.job_start("status","claude_code")["job"]
        self.assertLess(time.monotonic()-t,0.5)
        pid=read_pid(pidf);self.kill_later(pid)
        r=conn.job_poll(jid)
        self.assertFalse(r["done"]);self.assertIn("elapsed",r)
        self.assertEqual({"cancelled":True},conn.job_cancel(jid))
        r=self.poll_until_done(jid,2)
        self.assertTrue(r.get("cancelled"),r)
        self.assertTrue(wait_for(lambda:conn._jobs[jid].done,2),"the job thread did not stop")
        self.assertTrue(wait_for(lambda:pid_gone(pid),2),"the hung CLI is still running")
        self.assertTrue(conn.job_poll(jid)["cancelled"])
    def test_job_result_and_error(self):
        r=self.poll_until_done(conn.job_start("status","codex_cli")["job"])
        self.assertTrue(r["ok"],r);self.assertEqual("codex-cli 0.120.0",r["result"]["version"])
        r=self.poll_until_done(conn.job_start("overview")["job"])
        self.assertTrue(r["ok"],r);self.assertEqual(set(conn.TOOLS),set(r["result"]["tools"]))
        os.environ["PATH"]="/nonexistent"
        r=self.poll_until_done(conn.job_start("connect","codex_cli")["job"])
        self.assertFalse(r["ok"]);self.assertIn("not found",r["error"])
    def test_cancel_after_done_changes_nothing(self):
        jid=conn.job_start("preview","claude_code")["job"]
        r=self.poll_until_done(jid)
        self.assertTrue(r["ok"],r)
        self.assertEqual({"cancelled":False,"done":True},conn.job_cancel(jid))
        self.assertTrue(conn.job_poll(jid)["ok"])
    def test_connect_job_completes(self):
        r=self.poll_until_done(conn.job_start("connect","claude_code")["job"])
        self.assertTrue(r["ok"],r);self.assertTrue(r["result"]["connected"])
        self.assertIsNotNone(conn._read_conn("claude_code"))
        r=self.poll_until_done(conn.job_start("disconnect","claude_code")["job"])
        self.assertTrue(r["ok"],r);self.assertFalse(r["result"]["connected"])
    def test_cancelled_connect_leaves_no_connection(self):
        pidf=self.env.hang("claude",["mcp","add"],30)
        jid=conn.job_start("connect","claude_code")["job"]
        pid=read_pid(pidf);self.kill_later(pid)
        self.assertIsNotNone(conn._read_conn("claude_code"))  # written before the CLI registers it
        conn.job_cancel(jid)
        self.assertTrue(self.poll_until_done(jid,2).get("cancelled"))
        self.assertTrue(wait_for(lambda:conn._jobs[jid].done,2))
        self.assertIsNone(conn._read_conn("claude_code"))
        self.assertTrue(wait_for(lambda:pid_gone(pid),2))
    def test_cancelled_reconnect_restores_the_previous_connection(self):
        conn.connect("claude_code");before=conn._read_conn("claude_code")
        pidf=self.env.hang("claude",["mcp","add"],30)
        jid=conn.job_start("connect","claude_code")["job"]
        self.kill_later(read_pid(pidf))
        conn.job_cancel(jid)
        self.assertTrue(wait_for(lambda:conn._jobs[jid].done,2))
        self.assertEqual(before["token"],conn._read_conn("claude_code")["token"])
    def test_status_right_after_a_cancelled_connect_sees_the_restored_state(self):
        # The UI refreshes the card as soon as Cancel is pressed: that status must not read the half-done connection file.
        pidf=self.env.hang("claude",["mcp","add"],30)
        jid=conn.job_start("connect","claude_code")["job"]
        self.kill_later(read_pid(pidf))
        conn.job_cancel(jid)
        sid=conn.job_start("status","claude_code")["job"]
        r=self.poll_until_done(sid,10)
        self.assertTrue(r["ok"],r)
        self.assertFalse(r["result"]["connected"])
    def test_unknown_job_and_kind_are_refused(self):
        for bad in ("nope",None,""):
            with self.assertRaises(conn.ConnectionError_):conn.job_poll(bad)
            with self.assertRaises(conn.ConnectionError_):conn.job_cancel(bad)
        with self.assertRaises(conn.ConnectionError_):conn.job_start("rm -rf","claude_code")
        with self.assertRaises(conn.ConnectionError_):conn.job_start("status","bogus")
@unittest.skipIf(os.name=="nt","SO_REUSEADDR rules differ on Windows")
class ServerPortTest(unittest.TestCase):
    """A busy port never ends the app: an explicit port is refused, an automatic one moves on to a free port."""
    @classmethod
    def setUpClass(cls):
        cls.iso=IsolatedData();cls.iso.start()
    @classmethod
    def tearDownClass(cls):
        mcp.stop_server()
        cls.iso.stop()
    def setUp(self):
        mcp.stop_server()
        self.busy=socket.socket();self.busy.bind(("127.0.0.1",0));self.busy.listen(1)
        self.port=self.busy.getsockname()[1]
    def tearDown(self):
        mcp.stop_server()
        self.busy.close()
    def test_explicit_busy_port_raises_runtime_error(self):
        with self.assertRaises(RuntimeError) as cx:mcp.start_server(self.port,register_provider=False)
        self.assertIn(str(self.port),str(cx.exception))
        self.assertFalse(mcp.is_running())
    def test_automatic_port_skips_a_busy_default(self):
        with mock.patch.object(mcp,"DEFAULT_PORT",self.port):
            st=mcp.start_server(None,register_provider=False)
        self.assertTrue(st["running"]);self.assertNotEqual(self.port,st["port"])
        self.assertTrue(mcp.status()["running"])
        self.assertEqual(st["port"],mcp.start_server(None,register_provider=False)["port"])  # already running: same server
    def test_uvicorn_bind_failure_does_not_end_the_process(self):
        with mock.patch.object(mcp,"_port_free",lambda p:True):
            try:
                with self.assertRaises(RuntimeError):mcp.start_server(self.port,register_provider=False)
            except SystemExit:self.fail("SystemExit escaped start_server")
        self.assertFalse(mcp.is_running())
        self.assertTrue(mcp.start_server(None,register_provider=False)["running"])  # a later start still works
TOOL_SH="#!/bin/sh\necho \"$(basename $0) $*\" >> '{log}'\n{body}\n"
@unittest.skipIf(os.name=="nt","fake tools are POSIX shell scripts")
class InstallTest(unittest.TestCase):
    """"Install for me": per-OS official commands, prerequisites, and nothing runs without the operator's confirm."""
    @classmethod
    def setUpClass(cls):
        cls.iso=IsolatedData();cls.iso.start()
    @classmethod
    def tearDownClass(cls):
        cls.iso.stop()
    def setUp(self):
        self.env=Env().start()
        self.tools=os.path.join(self.env.tmp,"tools");os.makedirs(self.tools)
        self.log=os.path.join(self.env.tmp,"tools.log")
        for n in ("claude","codex"):os.remove(os.path.join(self.env.bin,n))  # not installed
        os.environ["PATH"]=self.tools
        self.opened=[]
        self._open=conn._open_os_terminal
        conn._open_os_terminal=lambda posix,cmd:(self.opened.append((posix,cmd)),{"opened":True,"terminal":"fake-term"})[1]
        self.was_windows=conn._IS_WINDOWS
    def tearDown(self):
        conn._open_os_terminal=self._open
        conn._IS_WINDOWS=self.was_windows
        conn._confirm.clear()
        self.env.stop()
    def tool(self,name,body="exit 0"):
        p=os.path.join(self.tools,name)
        with open(p,"w") as f:f.write(TOOL_SH.format(log=self.log,body=body))
        os.chmod(p,0o755)
    def ran(self):
        return open(self.log).read().splitlines() if os.path.exists(self.log) else []
    def test_linux_commands_are_the_official_user_level_ones(self):
        conn._IS_WINDOWS=False
        c={m["id"]:m["commands"] for m in conn.install_methods("claude_code")}
        self.assertEqual({"posix":"curl -fsSL https://claude.ai/install.sh | bash"},c["native"])
        self.assertEqual({"posix":"npm install -g @anthropic-ai/claude-code@latest"},c["npm"])
        x={m["id"]:m["commands"] for m in conn.install_methods("codex_cli")}
        self.assertEqual({"posix":"curl -fsSL https://chatgpt.com/codex/install.sh | sh"},x["native"])
        self.assertEqual({"posix":"npm install -g @openai/codex"},x["npm"])
    def test_windows_commands_are_the_official_ones(self):
        conn._IS_WINDOWS=True
        c={m["id"]:m for m in conn.install_methods("claude_code")}
        self.assertEqual(["native","winget","npm"],list(c))
        self.assertEqual("irm https://claude.ai/install.ps1 | iex",c["native"]["commands"]["ps"])
        self.assertEqual("curl -fsSL https://claude.ai/install.cmd -o install.cmd && install.cmd && del install.cmd",c["native"]["commands"]["cmd"])
        self.assertEqual("winget install Anthropic.ClaudeCode",c["winget"]["commands"]["ps"])
        self.assertFalse(c["winget"]["auto"])  # shown for manual use only
        x={m["id"]:m for m in conn.install_methods("codex_cli")}
        self.assertEqual('powershell -ExecutionPolicy ByPass -c "irm https://chatgpt.com/codex/install.ps1 | iex"',x["native"]["commands"]["cmd"])
        self.assertEqual("npm install -g @openai/codex",x["npm"]["commands"]["ps"])
    def test_no_elevation_anywhere(self):
        for tool in conn.INSTALL_METHODS.values():
            for plat in tool.values():
                for m in plat:
                    for line in m["lines"].values():
                        self.assertNotRegex(line.lower(),r"\bsudo\b|runas|-verb|pkexec|\bsu\b|doas")
                    self.assertTrue(m["source"].startswith("https://"))
    def test_missing_prerequisites_are_reported_with_links(self):
        conn._IS_WINDOWS=False
        m={x["id"]:x for x in conn.install_methods("claude_code")}
        self.assertFalse(m["native"]["auto"]);self.assertIn("curl",m["native"]["missing"][0]["name"])
        self.assertFalse(m["npm"]["auto"]);self.assertEqual("https://nodejs.org/en/download",m["npm"]["missing"][0]["url"])
        self.tool("npm");self.tool("node",'echo v18.19.0')
        m={x["id"]:x for x in conn.install_methods("claude_code")}
        self.assertIn("22 or later",m["npm"]["problem"]);self.assertFalse(m["npm"]["auto"])
    def test_npm_route_needs_a_user_writable_prefix(self):
        conn._IS_WINDOWS=False
        root=os.path.join(self.env.tmp,"rootprefix");os.makedirs(root);os.chmod(root,0o555)
        self.tool("node","echo v22.3.0");self.tool("npm",f"echo '{root}'")
        try:
            m={x["id"]:x for x in conn.install_methods("codex_cli")}
            self.assertFalse(m["npm"]["auto"]);self.assertIn("sudo",m["npm"]["problem"])
            mine=os.path.join(self.env.tmp,"userprefix");os.makedirs(mine)
            self.tool("npm",f"echo '{mine}'")
            self.assertTrue({x["id"]:x for x in conn.install_methods("codex_cli")}["npm"]["auto"])
        finally:os.chmod(root,0o755)
    def test_plan_shows_the_command_and_runs_nothing(self):
        conn._IS_WINDOWS=False
        self.tool("curl");self.tool("bash");self.tool("sh")
        p=conn.install_plan("claude_code","native","shell")
        self.assertEqual("curl -fsSL https://claude.ai/install.sh | bash",p["command"])
        self.assertEqual("https://claude.ai/install.sh",p["source"]);self.assertIn("your user's permissions",p["warning"])
        self.assertTrue(p["token"])
        self.assertEqual([],self.ran());self.assertEqual([],self.opened)
    def test_no_install_without_the_confirm_token(self):
        conn._IS_WINDOWS=False
        self.tool("curl");self.tool("bash");self.tool("sh")
        for bad in (None,"","forged"):
            with self.assertRaises(conn.ConnectionError_):conn.install_command("claude_code","native","shell",bad)
            with self.assertRaises(conn.ConnectionError_):conn.install_os_terminal("claude_code","native",bad)
        self.assertEqual([],self.opened)
        p=conn.install_plan("codex_cli","native")
        with self.assertRaises(conn.ConnectionError_):conn.install_os_terminal("claude_code","native",p["token"])  # token is per tool+method
        p=conn.install_plan("codex_cli","native")
        r=conn.install_os_terminal("codex_cli","native",p["token"])
        self.assertEqual("fake-term",r["terminal"])
        self.assertEqual([("curl -fsSL https://chatgpt.com/codex/install.sh | sh",None)],self.opened)
        with self.assertRaises(conn.ConnectionError_):conn.install_os_terminal("codex_cli","native",p["token"])  # single use
        p=conn.install_plan("claude_code","native","shell")
        self.assertEqual("curl -fsSL https://claude.ai/install.sh | bash",conn.install_command("claude_code","native","shell",p["token"]))
        self.assertEqual([],self.ran())  # the installer itself never ran in tests
    def test_windows_shell_lines(self):
        conn._IS_WINDOWS=True
        orig=conn._which
        conn._which=lambda n:"/fake/"+n
        try:
            p=conn.install_plan("claude_code","native","pwsh")
            self.assertEqual("irm https://claude.ai/install.ps1 | iex",conn.install_command("claude_code","native","pwsh",p["token"]))
            p=conn.install_plan("claude_code","native","cmd")
            self.assertEqual("curl -fsSL https://claude.ai/install.cmd -o install.cmd && install.cmd && del install.cmd",conn.install_command("claude_code","native","cmd",p["token"]))
            p=conn.install_plan("codex_cli","native")
            conn.install_os_terminal("codex_cli","native",p["token"])
            self.assertEqual((None,'powershell -ExecutionPolicy ByPass -c "irm https://chatgpt.com/codex/install.ps1 | iex"'),self.opened[-1])
            with self.assertRaises(conn.ConnectionError_):conn.install_plan("claude_code","winget","pwsh")  # manual only
        finally:
            conn._which=orig
    def test_plan_refused_when_already_installed(self):
        conn._IS_WINDOWS=False
        self.tool("curl");self.tool("bash");self.tool("claude","echo 2.1.400")
        with self.assertRaises(conn.ConnectionError_):conn.install_plan("claude_code","native","shell")
        self.assertTrue(conn.detect("claude_code")["installed"])
class HelpersTest(unittest.TestCase):
    def test_ps_quote(self):
        self.assertEqual("'C:\\a b\\it''s.exe'",conn._ps_quote("C:\\a b\\it's.exe"))
    def test_windows_candidates_include_npm_and_native_installer(self):
        old=conn._IS_WINDOWS
        conn._IS_WINDOWS=True
        try:
            env={"APPDATA":"/A/Roaming","LOCALAPPDATA":"/A/Local"}
            saved={k:os.environ.get(k) for k in env};os.environ.update(env)
            try:dirs=conn._candidate_dirs("claude")
            finally:
                for k,v in saved.items():
                    if v is None:os.environ.pop(k,None)
                    else:os.environ[k]=v
        finally:conn._IS_WINDOWS=old
        self.assertIn(os.path.join("/A/Roaming","npm"),dirs)
        self.assertIn(os.path.join(os.path.expanduser("~"),".local","bin"),dirs)
        self.assertIn(os.path.join("/A/Local","Microsoft","WinGet","Links"),dirs)
    def test_bridge_is_stdlib_only(self):
        src=open(conn.bridge_script(),encoding="utf-8").read()
        self.assertNotIn("from Cores",src);self.assertNotIn("import mcp",src)
if __name__=="__main__":
    unittest.main()
