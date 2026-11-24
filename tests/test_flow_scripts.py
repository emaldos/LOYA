import json,os,shutil,sys,tempfile,threading,time,unittest
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from _isolate import IsolatedData
from Cores.Services import flow_scripts as scripts
PAYLOAD={"input":{"node":"n2","type":"command","ok":True,"exit_code":0,"stdout":"64 bytes from 10.0.0.5: icmp_seq=1 ttl=63\n\u00e9\u4e2d \"quoted\" 'single' $HOME `x`","stderr":"","branch":"success","parsed":None},
         "vars":{"ip":"10.0.0.5","n":3},"target":{"ipv4":"10.0.0.5"},"item":{"port":443},"node":"n3","run_id":"run-1"}
PY_ECHO='''import json, os, sys
stdin = json.loads(sys.stdin.read())
with open(os.environ["LOYA_INPUT_FILE"], encoding="utf-8") as handle:
    from_file = json.load(handle)
from_env = json.loads(os.environ["LOYA_INPUT"])
print("some log line")
print(json.dumps({"branch": "alive" if "ttl=" in stdin["input"]["stdout"] else "down",
                  "vars": {"same": stdin == from_file == from_env, "ip": stdin["vars"]["ip"], "port": stdin["item"]["port"], "text": stdin["input"]["stdout"]},
                  "output": {"node": stdin["node"], "run": stdin["run_id"]}}))
'''
PY_ENV='''import json, os
print(json.dumps({"branch": "out", "vars": {"env": dict(os.environ), "cwd": os.getcwd(), "files": sorted(os.listdir("."))}}))
'''
def pid_alive(pid):
    try:os.kill(pid,0)
    except OSError:return False
    try:
        with open("/proc/%d/stat"%pid) as handle:return handle.read().rsplit(")",1)[1].split()[0]!="Z"
    except OSError:return True
SLOW=120   # upper bound for "this must not hang" checks: several test suites run on this machine at the same time
class ScriptsBase(unittest.TestCase):
    """Every test gets its own temp root for script work directories, so nothing here looks at the shared /tmp."""
    def setUp(self):
        self.isolated=IsolatedData();self.isolated.start()
        self.root=os.path.realpath(tempfile.mkdtemp(prefix="loya-scripts-test-"))
        self._watching=threading.Event()
        previous=scripts.TMP_ROOT
        scripts.TMP_ROOT=self.root
        def restore():
            self._watching.set()
            scripts.TMP_ROOT=previous
            shutil.rmtree(self.root,ignore_errors=True)
        self.addCleanup(restore)
    def tearDown(self):
        try:self.assertEqual([],os.listdir(self.root),"a script work directory was left behind")
        finally:self.isolated.stop()
    def when_file(self,name,action):
        """Call action(text) once the running script has written `name` (ending with a newline) into its work directory."""
        def watch():
            while not self._watching.is_set():
                try:folders=os.listdir(self.root)
                except OSError:return
                for folder in folders:
                    try:
                        with open(os.path.join(self.root,folder,name)) as handle:text=handle.read()
                    except OSError:continue
                    if text.endswith("\n"):
                        action(text.strip());return
                time.sleep(0.02)
        threading.Thread(target=watch,daemon=True).start()
    def wait_dead(self,pid,timeout=30):
        deadline=time.monotonic()+timeout
        while pid_alive(pid) and time.monotonic()<deadline:time.sleep(0.05)
        return not pid_alive(pid)
    def run_ok(self,language,code,payload=None,**options):
        done=scripts.run_script(language,code,PAYLOAD if payload is None else payload,**options)
        self.assertTrue(done["ok"],done)
        return done
class RoundTripTests(ScriptsBase):
    def test_result_shape(self):
        done=self.run_ok("python","print('hi')")
        self.assertEqual({"ok","exit_code","stdout","stderr","timed_out","cancelled","truncated","result","error","duration_ms","sandbox","network"},set(done))
        self.assertIsInstance(done["network"],bool)
        if done["sandbox"]=="none":self.assertTrue(done["network"])
        self.assertTrue(scripts.run_script("ruby","x",PAYLOAD)["network"])
        self.assertEqual((0,"hi\n","",False,False,False,None,""),(done["exit_code"],done["stdout"],done["stderr"],done["timed_out"],done["cancelled"],done["truncated"],done["result"],done["error"]))
        self.assertIn(done["sandbox"],("bwrap","none"));self.assertIsInstance(done["duration_ms"],int)
    def test_python_round_trips_the_payload(self):
        for sandbox in(True,False):
            done=self.run_ok("python",PY_ECHO,sandbox=sandbox)
            result=done["result"]
            self.assertEqual("alive",result["branch"])
            self.assertEqual({"same":True,"ip":"10.0.0.5","port":443,"text":PAYLOAD["input"]["stdout"]},result["vars"])
            self.assertEqual({"node":"n3","run":"run-1"},result["output"])
            self.assertIn("some log line",done["stdout"])
            if not sandbox:self.assertEqual("none",done["sandbox"])
    @unittest.skipUnless(scripts.available_languages()["bash"],"needs bash")
    def test_bash_round_trips_the_payload(self):
        code='''input=$(cat)
file=$(cat "$LOYA_INPUT_FILE")
same=false
if [ "$input" = "$file" ] && [ "$input" = "$LOYA_INPUT" ]; then same=true; fi
if printf '%s' "$input" | grep -q 'ttl='; then branch=alive; else branch=down; fi
echo "working in $PWD"
printf '{"branch":"%s","vars":{"same":%s,"flow":"%s"},"output":"done"}\\n' "$branch" "$same" "$LOYA_FLOW"
'''
        done=self.run_ok("bash",code.replace("\n","\r\n"))
        self.assertEqual({"branch":"alive","vars":{"same":True,"flow":"1"},"output":"done"},done["result"])
    @unittest.skipUnless(scripts.available_languages()["powershell"],"needs pwsh / powershell")
    def test_powershell_round_trips_the_payload(self):
        code='''$fromStdin = [Console]::In.ReadToEnd() | ConvertFrom-Json
$data = Get-Content -Raw -LiteralPath $env:LOYA_INPUT_FILE | ConvertFrom-Json
$branch = if ($data.input.stdout -match 'ttl=') { 'alive' } else { 'down' }
Write-Output "log line"
@{ branch = $branch; vars = @{ ip = $data.vars.ip; same = ($fromStdin.run_id -eq $data.run_id); port = $data.item.port } } | ConvertTo-Json -Compress
'''
        done=self.run_ok("powershell",code,timeout=120)
        self.assertEqual("alive",done["result"]["branch"])
        self.assertEqual({"ip":"10.0.0.5","same":True,"port":443},done["result"]["vars"])
    def test_script_templates_run(self):
        ids=[t["id"] for t in scripts.SCRIPT_TEMPLATES]
        self.assertEqual(len(ids),len(set(ids)))
        available=scripts.available_languages()
        for language in scripts.LANGUAGES:self.assertIn("alive-"+language,ids)
        down=dict(PAYLOAD,input=dict(PAYLOAD["input"],stdout="2 packets transmitted, 0 received, 100% packet loss"))
        for entry in scripts.SCRIPT_TEMPLATES:
            self.assertEqual({"id","language","name","description","code","branches"},set(entry))
            self.assertIn(entry["language"],scripts.LANGUAGES)
            if not available[entry["language"]]:continue
            done=self.run_ok(entry["language"],entry["code"],timeout=120,branches=entry["branches"])
            self.assertIn(done["result"]["branch"],entry["branches"],entry["id"])
            if entry["id"].startswith("alive-"):
                self.assertEqual(("alive",{"alive":True}),(done["result"]["branch"],done["result"]["vars"]),entry["id"])
                self.assertEqual(("down",{"alive":False}),tuple(self.run_ok(entry["language"],entry["code"],payload=down,timeout=120)["result"][k] for k in("branch","vars")),entry["id"])
    def test_schema_template_script_runs(self):
        from Cores.Services import flow_schema
        row=flow_schema.graph_scripts(flow_schema.template("script-demo"))[0]
        self.assertEqual("alive",self.run_ok(row["language"],row["code"])["result"]["branch"])
    def test_large_payload_goes_through_stdin_and_file_but_not_the_environment(self):
        big=dict(PAYLOAD,input=dict(PAYLOAD["input"],stdout="x"*300000))
        code='''import json, os, sys
data = json.loads(sys.stdin.read())
with open(os.environ["LOYA_INPUT_FILE"]) as handle: other = json.load(handle)
print(json.dumps({"branch": "out", "vars": {"n": len(data["input"]["stdout"]), "same": data == other, "env": "LOYA_INPUT" in os.environ}}))
'''
        self.assertEqual({"n":300000,"same":True,"env":False},self.run_ok("python",code,payload=big)["result"]["vars"])
    def test_script_that_ignores_stdin_still_finishes(self):
        big=dict(PAYLOAD,input=dict(PAYLOAD["input"],stdout="x"*2000000))
        self.assertEqual("ok\n",self.run_ok("python","print('ok')",payload=big)["stdout"])
class EnvironmentTests(ScriptsBase):
    def test_environment_is_built_from_scratch(self):
        os.environ["LOYA_TEST_SENTINEL_TOKEN"]="super-secret-value"
        os.environ["PYTHONSTARTUP"]="/nonexistent/startup.py"
        try:done=self.run_ok("python",PY_ENV)
        finally:
            del os.environ["LOYA_TEST_SENTINEL_TOKEN"];del os.environ["PYTHONSTARTUP"]
        seen=done["result"]["vars"]["env"]
        self.assertNotIn("LOYA_TEST_SENTINEL_TOKEN",seen)
        self.assertNotIn("super-secret-value",json.dumps(seen))
        allowed={"PATH","HOME","TMP","TEMP","TMPDIR","LANG","LC_ALL","LOYA_FLOW","LOYA_INPUT_FILE","LOYA_INPUT","LC_CTYPE","PWD"}
        if os.name=="nt":allowed|={"SYSTEMROOT","COMSPEC","PATHEXT","WINDIR","SYSTEMDRIVE","PROGRAMFILES","PROGRAMFILES(X86)","PROGRAMDATA","NUMBER_OF_PROCESSORS","PROCESSOR_ARCHITECTURE","OS","USERPROFILE","APPDATA","LOCALAPPDATA"}
        self.assertEqual(set(),{key.upper() for key in seen}-allowed)
        self.assertEqual("1",seen["LOYA_FLOW"]);self.assertEqual(PAYLOAD,json.loads(seen["LOYA_INPUT"]))
        for key in("HOME","TMP","TEMP"):self.assertEqual(os.path.dirname(seen["LOYA_INPUT_FILE"]),seen[key])
    @unittest.skipUnless(scripts.available_languages()["bash"],"needs bash")
    def test_bash_does_not_see_the_sentinel_either(self):
        os.environ["LOYA_TEST_SENTINEL_TOKEN"]="super-secret-value"
        try:done=self.run_ok("bash","env")
        finally:del os.environ["LOYA_TEST_SENTINEL_TOKEN"]
        self.assertNotIn("SENTINEL",done["stdout"]);self.assertNotIn("super-secret-value",done["stdout"])
        self.assertIn("LOYA_FLOW=1",done["stdout"])
    def test_cwd_is_the_temp_workdir_and_it_is_removed(self):
        for sandbox in(True,False):
            done=self.run_ok("python",PY_ENV,sandbox=sandbox)
            seen=done["result"]["vars"]
            cwd=seen["cwd"]
            self.assertTrue(os.path.basename(cwd).startswith("loya-flow-"),cwd)
            self.assertEqual(self.root,os.path.dirname(cwd))
            self.assertEqual(["input.json","script.py"],seen["files"])
            self.assertEqual(os.path.join(cwd,"input.json"),seen["env"]["LOYA_INPUT_FILE"])
            self.assertFalse(os.path.exists(cwd),"the work directory must be removed")
    def test_workdir_is_removed_after_failures_too(self):
        litter="import os\nos.makedirs('deep/er')\nopen('deep/er/file','w').close()\nos.chmod('deep/er/file',0)\nos.chmod('deep/er',0o500)\nos.chmod('deep',0o500)\n"
        for code,options in(("import sys; sys.exit(3)",{}),("import time; time.sleep(600)",{"timeout":1}),("print('x'*5000000)",{"max_output":2048}),("def broken(:",{})):
            for sandbox in(True,False):
                done=scripts.run_script("python",(litter if "broken" not in code else "")+code,PAYLOAD,sandbox=sandbox,**options)
                self.assertFalse(done["ok"])
                self.assertEqual([],os.listdir(self.root),(code,sandbox))
        already=threading.Event();already.set()
        scripts.run_script("python","print(1)",PAYLOAD,cancel_event=already)
        self.assertEqual([],os.listdir(self.root))
    def test_tmp_root_argument_and_fallback(self):
        other=os.path.realpath(tempfile.mkdtemp(prefix="loya-scripts-other-"))
        try:
            cwd=self.run_ok("python",PY_ENV,tmp_root=other)["result"]["vars"]["cwd"]
            self.assertEqual(other,os.path.dirname(cwd));self.assertEqual([],os.listdir(other))
            self.assertEqual(self.root,os.path.dirname(self.run_ok("python",PY_ENV,tmp_root=os.path.join(other,"missing"))["result"]["vars"]["cwd"]))
        finally:shutil.rmtree(other,ignore_errors=True)
        self.assertEqual(self.root,scripts._tmp_root(os.path.join(self.root,"nope")));self.assertEqual(self.root,scripts._tmp_root())
    def test_remove_tree_handles_read_only_entries_and_links(self):
        victim=os.path.join(self.root,"victim");os.makedirs(victim)
        keep=os.path.join(victim,"keep.txt")
        with open(keep,"w") as handle:handle.write("keep")
        os.chmod(keep,0o400)
        work=os.path.join(self.root,"loya-flow-manual");os.makedirs(os.path.join(work,"a","b"))
        with open(os.path.join(work,"a","b","f"),"w") as handle:handle.write("x")
        if os.name=="posix":
            os.symlink(keep,os.path.join(work,"a","link-file"));os.symlink(victim,os.path.join(work,"a","link-dir"))
        os.chmod(os.path.join(work,"a","b","f"),0);os.chmod(os.path.join(work,"a","b"),0o500);os.chmod(os.path.join(work,"a"),0o500)
        self.assertTrue(scripts._remove_tree(work))
        self.assertFalse(os.path.lexists(work))
        with open(keep) as handle:self.assertEqual("keep",handle.read())                 # link targets are left alone
        self.assertEqual(0o400,os.stat(keep).st_mode&0o777)
        self.assertTrue(scripts._remove_tree(os.path.join(self.root,"never-existed")))
        os.chmod(keep,0o600);shutil.rmtree(victim)
    def test_python_runs_isolated(self):
        code="import sys, json; print(json.dumps({'branch':'out','vars':{'isolated':bool(sys.flags.isolated),'bytecode':bool(sys.flags.dont_write_bytecode),'cwd_in_path':'' in sys.path}}))"
        self.assertEqual({"isolated":True,"bytecode":True,"cwd_in_path":False},self.run_ok("python",code)["result"]["vars"])
    def test_build_env_posix(self):
        environ={"PATH":"/usr/bin:/bin","LANG":"en_US.UTF-8","SECRET":"x","AWS_SECRET_ACCESS_KEY":"y","HOME":"/home/user","SSH_AUTH_SOCK":"/s","DISPLAY":":0"}
        built=scripts.build_env("/tmp/w","{}",windows=False,environ=environ)
        self.assertEqual({"PATH":"/usr/bin:/bin","HOME":"/tmp/w","TMP":"/tmp/w","TEMP":"/tmp/w","TMPDIR":"/tmp/w","LANG":"en_US.UTF-8","LC_ALL":"en_US.UTF-8",
                          "LOYA_FLOW":"1","LOYA_INPUT_FILE":"/tmp/w/input.json","LOYA_INPUT":"{}"},built)
        bare=scripts.build_env("/tmp/w","{}",windows=False,environ={})
        self.assertEqual((os.defpath,"C.UTF-8","C.UTF-8"),(bare["PATH"],bare["LANG"],bare["LC_ALL"]))
        self.assertNotIn("LOYA_INPUT",scripts.build_env("/tmp/w","x"*32769,windows=False,environ={}))
        self.assertIn("LOYA_INPUT",scripts.build_env("/tmp/w","x"*32768,windows=False,environ={}))
    SECRETS={"LOYA_MCP_TOKEN":"tok-1","ANTHROPIC_API_KEY":"sk-ant-2","CODEX_API_KEY":"cx-3","OPENAI_API_KEY":"sk-4","AWS_ACCESS_KEY_ID":"AKIA5","AWS_SECRET_ACCESS_KEY":"aws-6",
             "AWS_SESSION_TOKEN":"aws-7","AWS_PROFILE":"prod-8","HTTP_PROXY":"http://u:p9@proxy","HTTPS_PROXY":"http://u:p10@proxy","ALL_PROXY":"socks://p11","NO_PROXY":"internal-12",
             "http_proxy":"http://lower-13","https_proxy":"http://lower-14","GITHUB_TOKEN":"ghp-15","SSH_AUTH_SOCK":"/run/agent-16","CLAUDE_CODE_OAUTH_TOKEN":"oauth-17","LOYA_DB_KEY":"key-18"}
    def test_build_env_never_passes_tokens_or_proxies(self):
        for windows in(False,True):
            environ=dict(self.SECRETS,PATH="/usr/bin",LANG="C.UTF-8",SYSTEMROOT="C:\\Windows")
            built=scripts.build_env("/tmp/w","{}",windows=windows,environ=environ)
            for name,value in self.SECRETS.items():
                self.assertNotIn(name,built);self.assertNotIn(name.upper(),{key.upper() for key in built})
                self.assertNotIn(value,json.dumps(built))
            self.assertFalse([key for key in built if key.upper().startswith("AWS_") or key.upper().endswith("_PROXY") or "TOKEN" in key.upper() or "API_KEY" in key.upper()])
    def test_running_script_sees_no_tokens_or_proxies(self):
        saved={name:os.environ.get(name) for name in self.SECRETS}
        os.environ.update(self.SECRETS)
        try:
            seen=[self.run_ok("python",PY_ENV,sandbox=sandbox)["result"]["vars"]["env"] for sandbox in(True,False)]
            if scripts.available_languages()["bash"]:seen.append({"raw":self.run_ok("bash","env; set")["stdout"]})
        finally:
            for name,value in saved.items():
                if value is None:os.environ.pop(name,None)
                else:os.environ[name]=value
        for env in seen:
            text=json.dumps(env)
            for name,value in self.SECRETS.items():
                self.assertNotIn(value,text,name);self.assertNotIn(name+"=",text);self.assertNotIn('"%s"'%name,text)
    def test_build_env_windows(self):
        environ={"Path":"C:\\Windows\\system32","SystemRoot":"C:\\Windows","ComSpec":"C:\\Windows\\system32\\cmd.exe","PATHEXT":".COM;.EXE","windir":"C:\\Windows",
                 "USERPROFILE":"C:\\Users\\me","APPDATA":"C:\\Users\\me\\AppData\\Roaming","GITHUB_TOKEN":"ghp_x","USERNAME":"me","LOYA_NOTE_HOME":"C:\\app"}
        built=scripts.build_env("C:\\T\\w","{}",windows=True,environ=environ)
        self.assertEqual({"SYSTEMROOT":"C:\\Windows","COMSPEC":"C:\\Windows\\system32\\cmd.exe","PATHEXT":".COM;.EXE","WINDIR":"C:\\Windows"},{k:built[k] for k in("SYSTEMROOT","COMSPEC","PATHEXT","WINDIR")})
        for key in("HOME","TMP","TEMP","USERPROFILE","APPDATA","LOCALAPPDATA"):self.assertEqual("C:\\T\\w",built[key])
        for key in("GITHUB_TOKEN","USERNAME","LOYA_NOTE_HOME","TMPDIR","LC_ALL"):self.assertNotIn(key,built)
        self.assertNotIn("ghp_x",json.dumps(built));self.assertNotIn("Users\\\\me",json.dumps(built))
        self.assertEqual(("1","{}"),(built["LOYA_FLOW"],built["LOYA_INPUT"]))
        self.assertNotIn("LOYA_INPUT",scripts.build_env("C:\\T\\w","x"*24001,windows=True,environ=environ))
class ArgvTests(unittest.TestCase):
    def which(self,table):
        return lambda name:table.get(name)
    def test_python(self):
        self.assertEqual([sys.executable,"-I","-X","utf8","-B","/w/script.py"],scripts.script_argv("python","/w/script.py"))
    def test_bash(self):
        self.assertEqual(["/usr/bin/bash","--noprofile","--norc","/w/s.sh"],scripts.script_argv("bash","/w/s.sh",windows=False,which=self.which({"bash":"/usr/bin/bash","sh":"/bin/sh"})))
        self.assertEqual(["/bin/sh","/w/s.sh"],scripts.script_argv("bash","/w/s.sh",windows=False,which=self.which({"sh":"/bin/sh"})))
        self.assertIsNone(scripts.script_argv("bash","/w/s.sh",windows=False,which=self.which({})))
        git="C:\\Program Files\\Git\\bin\\bash.EXE"
        self.assertEqual([git,"--noprofile","--norc","C:\\w\\s.sh"],scripts.script_argv("bash","C:\\w\\s.sh",windows=True,which=self.which({"bash":git})))
        self.assertIsNone(scripts.script_argv("bash","C:\\w\\s.sh",windows=True,which=self.which({"bash":"C:\\Windows\\System32\\bash.exe","sh":"C:\\x\\sh.exe"})))
    def test_powershell(self):
        tail=["-NoLogo","-NoProfile","-NonInteractive","-ExecutionPolicy","Bypass","-File","C:\\w\\s.ps1"]
        self.assertEqual(["C:\\p\\pwsh.exe"]+tail,scripts.script_argv("powershell","C:\\w\\s.ps1",windows=True,which=self.which({"pwsh":"C:\\p\\pwsh.exe","powershell":"C:\\p\\powershell.exe"})))
        self.assertEqual(["C:\\p\\powershell.exe"]+tail,scripts.script_argv("powershell","C:\\w\\s.ps1",windows=True,which=self.which({"powershell":"C:\\p\\powershell.exe"})))
        self.assertIsNone(scripts.script_argv("powershell","/w/s.ps1",windows=False,which=self.which({"powershell":"/x/powershell"})))
        self.assertEqual("/usr/bin/pwsh",scripts.script_argv("powershell","/w/s.ps1",windows=False,which=self.which({"pwsh":"/usr/bin/pwsh"}))[0])
    def test_unknown_language_and_available(self):
        self.assertIsNone(scripts.script_argv("ruby","/w/x.rb"))
        available=scripts.available_languages()
        self.assertEqual(set(scripts.LANGUAGES),set(available));self.assertTrue(available["python"])
        self.assertEqual(("python","bash","powershell"),scripts.LANGUAGES)
    def test_taskkill_and_bwrap_argv(self):
        self.assertEqual(["taskkill","/T","/F","/PID","4321"],scripts.taskkill_argv(4321))
        wrapped=scripts.bwrap_argv("/usr/bin/bwrap","/tmp/loya-flow-x",["/app/Data","/app/Logs"],["/usr/bin/python3","-I","/tmp/loya-flow-x/script.py"])
        self.assertEqual(["/usr/bin/bwrap","--ro-bind","/","/"],wrapped[:4])
        self.assertEqual(["--","/usr/bin/python3","-I","/tmp/loya-flow-x/script.py"],wrapped[-4:])
        joined=" ".join(wrapped)
        for fragment in("--tmpfs /app/Data","--tmpfs /app/Logs","--bind /tmp/loya-flow-x /tmp/loya-flow-x","--chdir /tmp/loya-flow-x","--die-with-parent","--new-session","--unshare-pid"):self.assertIn(fragment,joined)
        self.assertIn("--unshare-net",wrapped)   # no network unless asked for
        self.assertLess(wrapped.index("--ro-bind"),wrapped.index("--tmpfs"));self.assertLess(wrapped.index("--tmpfs"),wrapped.index("--bind"))
        online=scripts.bwrap_argv("/usr/bin/bwrap","/tmp/w",["/app/Data"],["/bin/true"],network=True,hidden_files=["/home/u/.netrc","/home/u/.git-credentials"])
        self.assertNotIn("--unshare-net",online);self.assertIn("--unshare-pid",online)
        self.assertIn("--ro-bind /dev/null /home/u/.netrc --ro-bind /dev/null /home/u/.git-credentials --bind /tmp/w /tmp/w"," ".join(online))
        self.assertEqual([w for w in wrapped if w!="--unshare-net"][:-3],scripts.bwrap_argv("/usr/bin/bwrap","/tmp/loya-flow-x",["/app/Data","/app/Logs"],["x"],network=True)[:-1])
class LimitTests(ScriptsBase):
    def test_non_zero_exit_is_not_ok(self):
        done=scripts.run_script("python","import sys\nprint('{\"branch\":\"alive\"}')\nsys.stderr.write('boom\\n')\nsys.exit(4)",PAYLOAD,branches=["alive","down"])
        self.assertEqual((False,4,None,"boom\n"),(done["ok"],done["exit_code"],done["result"],done["stderr"]))
        self.assertIn("exit code 4",done["error"])
        broken=scripts.run_script("python","def broken(:\n",PAYLOAD)
        self.assertFalse(broken["ok"]);self.assertIn("SyntaxError",broken["stderr"])
    def test_timeout_kills(self):
        started=time.monotonic()
        done=scripts.run_script("python","import time\nprint('started', flush=True)\ntime.sleep(600)\nprint('never')",PAYLOAD,timeout=1)
        elapsed=time.monotonic()-started
        self.assertEqual((False,True,False,None),(done["ok"],done["timed_out"],done["cancelled"],done["result"]))
        self.assertIn(done["stdout"],("started\n",""))    # on a loaded machine the interpreter may not even have started yet
        self.assertIn("stopped after 1 seconds",done["error"])
        self.assertLess(elapsed,SLOW);self.assertGreaterEqual(done["duration_ms"],900)
    @unittest.skipUnless(os.name=="posix","process groups")
    def _tree_marker(self):return "child.pid"
    TREE_CODE='''import subprocess, sys, time
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
with open("child.pid", "w") as handle: handle.write("%d\\n" % child.pid)
time.sleep(600)
'''
    @unittest.skipUnless(os.name=="posix","process groups")
    def test_cancel_kills_the_whole_tree(self):
        cancel=threading.Event();seen=[]
        def ready(text):
            seen.append(int(text));cancel.set()      # event-based: stop only once the grandchild really exists
        self.when_file("child.pid",ready)
        done=scripts.run_script("python",self.TREE_CODE,PAYLOAD,timeout=SLOW,cancel_event=cancel,sandbox=False)
        self.assertTrue(done["cancelled"],done)
        self.assertEqual(1,len(seen))
        self.assertTrue(self.wait_dead(seen[0]),"the grandchild survived the cancel")
    @unittest.skipUnless(os.name=="posix","process groups")
    def test_timeout_kills_the_whole_tree(self):
        seen=[]
        self.when_file("child.pid",lambda text:seen.append(int(text)))
        done=scripts.run_script("python",self.TREE_CODE,PAYLOAD,timeout=4,sandbox=False)
        self.assertTrue(done["timed_out"])
        if not seen:self.skipTest("the machine was too busy to start the grandchild within the timeout")
        self.assertTrue(self.wait_dead(seen[0]),"the grandchild survived the timeout")
    @unittest.skipUnless(os.name=="posix" and scripts.available_languages()["bash"],"process groups")
    def test_background_children_do_not_outlive_the_script(self):
        code='''import subprocess, sys
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print(child.pid)
'''
        done=self.run_ok("python",code,sandbox=False)
        self.assertTrue(self.wait_dead(int(done["stdout"].split()[0])),"a background child survived the script")
    def test_output_cap_truncates(self):
        code="import sys\nwhile True:\n    sys.stdout.write('x'*65536)\n"
        started=time.monotonic()
        done=scripts.run_script("python",code,PAYLOAD,timeout=30,max_output=100000)
        self.assertEqual((False,True,False,None),(done["ok"],done["truncated"],done["timed_out"],done["result"]))
        self.assertEqual(100000,len(done["stdout"]));self.assertLess(time.monotonic()-started,SLOW)
        self.assertIn("KB",done["error"])
        err=scripts.run_script("python","import sys\nwhile True:\n    sys.stderr.write('e'*65536)\n",PAYLOAD,timeout=30,max_output=4096)
        self.assertTrue(err["truncated"]);self.assertEqual(4096,len(err["stderr"]))
        fits=self.run_ok("python","print('y'*5000)",max_output=8192)
        self.assertFalse(fits["truncated"]);self.assertEqual(5001,len(fits["stdout"]))
    def test_cancel_event_stops(self):
        cancel=threading.Event();seen=[]
        self.when_file("started",lambda text:cancel.set())     # event-based: cancel once the script says it is running
        started=time.monotonic()
        code="import time\nprint('started', flush=True)\nopen('started','w').write('yes\\n')\ntime.sleep(600)"
        done=scripts.run_script("python",code,PAYLOAD,timeout=SLOW*2,cancel_event=cancel,on_start=seen.append)
        self.assertEqual((False,True,False),(done["ok"],done["cancelled"],done["timed_out"]))
        self.assertEqual("started\n",done["stdout"]);self.assertLess(time.monotonic()-started,SLOW*2)
        self.assertEqual(1,len(seen));self.assertIsNotNone(seen[0].poll())
        already=threading.Event();already.set()
        skipped=scripts.run_script("python","print('never')",PAYLOAD,cancel_event=already)
        self.assertEqual((False,True,""),(skipped["ok"],skipped["cancelled"],skipped["stdout"]))
    def test_on_start_can_kill_the_tree(self):
        def killer(proc):threading.Timer(0.5,scripts.kill_tree,args=(proc,)).start()
        started=time.monotonic()
        done=scripts.run_script("python","import time\ntime.sleep(600)",PAYLOAD,timeout=SLOW*2,on_start=killer)
        self.assertFalse(done["ok"]);self.assertLess(time.monotonic()-started,SLOW);self.assertNotEqual(0,done["exit_code"])
        self.assertFalse(done["timed_out"])
    def test_kill_tree_tolerates_anything(self):
        scripts.kill_tree(None)
        import subprocess
        proc=subprocess.Popen([sys.executable,"-c","pass"])
        proc.wait()
        scripts.kill_tree(proc);scripts.kill_tree(proc)
        same_group=subprocess.Popen([sys.executable,"-c","import time; time.sleep(600)"])   # shares OUR process group: must not signal the group
        scripts.kill_tree(same_group,grace=0.2)
        self.assertIsNotNone(same_group.wait(timeout=SLOW))
    def test_bad_arguments(self):
        self.assertIn("Unknown script language",scripts.run_script("ruby","puts 1",PAYLOAD)["error"])
        self.assertTrue(self.run_ok("python","print(1)",timeout="soon",max_output="lots")["ok"])
        self.assertTrue(self.run_ok("python","print(1)",payload=None)["ok"])
        circular=[];circular.append(circular)
        self.assertIn("JSON",scripts.run_script("python","print(1)",{"x":circular})["error"])
    def test_missing_interpreter(self):
        real=scripts.script_argv
        scripts.script_argv=lambda *a,**k:None
        try:done=scripts.run_script("powershell","1",PAYLOAD)
        finally:scripts.script_argv=real
        self.assertFalse(done["ok"]);self.assertIn("PowerShell is not installed",done["error"])
        scripts.script_argv=lambda language,path,**k:["/nonexistent/loya-interpreter",path]
        try:done=scripts.run_script("python","1",PAYLOAD,sandbox=False)
        finally:scripts.script_argv=real
        self.assertFalse(done["ok"]);self.assertIn("could not be started",done["error"])
class ResultProtocolTests(ScriptsBase):
    def test_last_json_object_line_wins(self):
        out='{"branch":"first"}\nlog\n{"branch":"second","vars":{"a":1,"bad name":2,"_ok":[1]},"output":[1,2]}\n\n   \n'
        self.assertEqual({"branch":"second","vars":{"a":1,"_ok":[1]},"output":[1,2]},scripts.parse_result(out))
        self.assertEqual("first",scripts.parse_result('{"branch":"first"}\ntrailing log line\n')["branch"])
    def test_lines_that_are_not_results_are_ignored(self):
        for out in("","just text\n","[1,2]\n",'"text"\n','{"unrelated":1}\n',"{broken json}\n","5\n"):
            self.assertIsNone(scripts.parse_result(out),out)
            self.assertEqual({"branch":"alive","vars":{},"output":None},scripts.parse_result(out,["alive","down"]),out)
    def test_branch_names_are_validated(self):
        self.assertEqual("",scripts.parse_result('{"branch":"bad name!"}')["branch"])
        self.assertEqual("a",scripts.parse_result('{"branch":"bad name!"}',["a","b"])["branch"])
        self.assertEqual("a",scripts.parse_result('{"vars":{"x":1}}',["a","b"])["branch"])
        self.assertEqual("7",scripts.parse_result('{"branch":7}')["branch"]);self.assertEqual("true",scripts.parse_result('{"branch":true}')["branch"])
        self.assertEqual({},scripts.parse_result('{"branch":"a","vars":[1]}')["vars"])
        self.assertEqual("b",scripts.parse_result('  {"branch":"b"}  \r\n',["a","b"])["branch"])
    def test_run_script_fills_the_default_branch(self):
        self.assertEqual({"branch":"first","vars":{},"output":None},scripts.run_script("python","print('no result line')",PAYLOAD,branches=["first","second"])["result"])
        self.assertIsNone(scripts.run_script("python","print('no result line')",PAYLOAD)["result"])
@unittest.skipUnless(sys.platform.startswith("linux"),"bubblewrap is Linux only")
class SandboxTests(ScriptsBase):
    def setUp(self):
        super().setUp()
        scripts.reset_sandbox_probe()
    def tearDown(self):
        scripts.reset_sandbox_probe()
        super().tearDown()
    def test_probe_is_cached(self):
        calls=[]
        real=scripts.subprocess.run
        def spy(argv,**options):
            calls.append(argv);return real(argv,**options)
        scripts.subprocess.run=spy
        try:
            first=scripts._bwrap_path();second=scripts._bwrap_path();third=scripts._bwrap_path()
        finally:scripts.subprocess.run=real
        self.assertEqual(first,second);self.assertEqual(first,third)
        self.assertLessEqual(len(calls),1)
        if shutil.which("bwrap"):
            self.assertEqual(1,len(calls));self.assertEqual("--",calls[0][-2]);self.assertTrue(calls[0][-1].endswith("true"))
    def test_sandbox_hides_the_data_directory_and_makes_the_system_read_only(self):
        secret=os.path.join(self.isolated.dir,"secret.txt")
        with open(secret,"w") as handle:handle.write("db-key")
        outside=tempfile.mkdtemp(prefix="loya-outside-")
        try:
            code='''import json, os
def can_write(path):
    try:
        with open(path, "w") as handle: handle.write("x")
        return True
    except OSError: return False
print(json.dumps({"branch": "out", "vars": {"secret": os.path.exists(%r), "data": sorted(os.listdir(%r)), "outside": can_write(%r), "own": can_write("note.txt"), "pid": os.getpid()}}))
'''%(secret,self.isolated.dir,os.path.join(outside,"written.txt"))
            done=self.run_ok("python",code)
            seen=done["result"]["vars"]
            self.assertTrue(seen["own"])
            if done["sandbox"]!="bwrap":self.skipTest("bubblewrap does not work on this machine")
            self.assertEqual((False,[],False),(seen["secret"],seen["data"],seen["outside"]))
            self.assertEqual([],os.listdir(outside));self.assertLess(seen["pid"],50)
            self.assertTrue(os.path.exists(secret))
            plain=self.run_ok("python",code,sandbox=False)
            self.assertEqual(("none",True),(plain["sandbox"],plain["result"]["vars"]["secret"]))
        finally:shutil.rmtree(outside,ignore_errors=True)
    def test_falls_back_cleanly_when_bwrap_is_missing_or_broken(self):
        real=scripts.shutil.which
        scripts.shutil.which=lambda name,*a,**k:None if name=="bwrap" else real(name,*a,**k)
        try:
            self.assertIsNone(scripts._bwrap_path())
            done=self.run_ok("python",PY_ECHO)
        finally:scripts.shutil.which=real
        self.assertEqual(("none","alive"),(done["sandbox"],done["result"]["branch"]))
        scripts.reset_sandbox_probe()
        scripts.shutil.which=lambda name,*a,**k:"/bin/false" if name=="bwrap" else real(name,*a,**k)   # installed but not permitted
        try:
            self.assertIsNone(scripts._bwrap_path())
            self.assertEqual("none",self.run_ok("python",PY_ECHO)["sandbox"])
        finally:scripts.shutil.which=real
        scripts._bwrap_state.update(checked=True,path="/nonexistent/bwrap")   # vanished after the probe
        done=self.run_ok("python",PY_ECHO)
        self.assertEqual(("none","alive"),(done["sandbox"],done["result"]["branch"]))
    NET_CODE='''import json, socket, sys
port = int(sys.argv[1]) if len(sys.argv) > 1 else %d
try:
    socket.create_connection(("127.0.0.1", port), timeout=3).close(); reached = True
except OSError: reached = False
print(json.dumps({"branch": "out", "vars": {"reached": reached, "interfaces": sorted(name for _, name in socket.if_nameindex())}}))
'''
    def test_network_is_cut_unless_asked_for(self):
        import socket
        server=socket.socket();server.bind(("127.0.0.1",0));server.listen(5)
        try:
            code=self.NET_CODE%server.getsockname()[1]
            info=scripts.sandbox_info()
            self.assertEqual({"sandbox","network_isolation"},set(info))
            offline=self.run_ok("python",code)
            online=self.run_ok("python",code,network=True)
            plain=self.run_ok("python",code,sandbox=False)
            self.assertEqual(("none",True,True),(plain["sandbox"],plain["network"],plain["result"]["vars"]["reached"]))
            self.assertEqual((True,True),(online["network"],online["result"]["vars"]["reached"]))
            self.assertEqual(info["sandbox"],offline["sandbox"])
            if not info["network_isolation"]:
                self.assertTrue(offline["network"]);self.skipTest("bubblewrap cannot isolate the network on this machine")
            self.assertEqual(("bwrap",False,False,["lo"]),(offline["sandbox"],offline["network"],offline["result"]["vars"]["reached"],offline["result"]["vars"]["interfaces"]))
            self.assertEqual("bwrap",online["sandbox"])
        finally:server.close()
    def test_sandbox_info_reports_no_isolation(self):
        real=scripts.shutil.which
        scripts.shutil.which=lambda name,*a,**k:None if name=="bwrap" else real(name,*a,**k)
        try:
            self.assertEqual({"sandbox":"none","network_isolation":False},scripts.sandbox_info())
            done=self.run_ok("python","print(1)",network=False)
            self.assertEqual(("none",True),(done["sandbox"],done["network"]))
        finally:scripts.shutil.which=real
        scripts.reset_sandbox_probe()
        os.environ["LOYA_FLOW_NO_SANDBOX"]="1"
        try:self.assertEqual({"sandbox":"none","network_isolation":False},scripts.sandbox_info())
        finally:del os.environ["LOYA_FLOW_NO_SANDBOX"]
    def test_sandbox_without_network_namespaces_still_sandboxes(self):
        real=scripts.subprocess.run
        class Refused:returncode=1
        def fake(argv,**options):
            return Refused() if "--unshare-net" in argv else real(argv,**options)
        scripts.subprocess.run=fake
        try:info=scripts.sandbox_info()
        finally:scripts.subprocess.run=real
        if info["sandbox"]!="bwrap":self.skipTest("bubblewrap does not work on this machine")
        self.assertEqual({"sandbox":"bwrap","network_isolation":False},info)
        done=self.run_ok("python","print(1)",network=False)
        self.assertEqual(("bwrap",True),(done["sandbox"],done["network"]))    # sandboxed, and honest about the network
    def test_home_secrets_are_hidden(self):
        home=tempfile.mkdtemp(prefix="loya-home-")
        saved=os.environ.get("HOME")
        try:
            for folder in(".ssh",".aws",".gnupg",".config/gh",".claude",".codex",".kube",".docker","Documents"):
                os.makedirs(os.path.join(home,folder))
                with open(os.path.join(home,folder,"secret"),"w") as handle:handle.write("TOPSECRET")
            for name in(".netrc",".git-credentials",".claude.json","notes.txt"):
                with open(os.path.join(home,name),"w") as handle:handle.write("TOPSECRET")
            os.environ["HOME"]=home
            dirs,files=scripts._hidden_paths("/tmp/loya-flow-zz",["/usr/bin/python3"])
            real_home=os.path.realpath(home)
            for folder in(".ssh",".aws",".gnupg",".config",".claude",".codex",".kube",".docker"):self.assertIn(os.path.join(real_home,folder),dirs)
            self.assertEqual({os.path.join(real_home,name) for name in(".netrc",".git-credentials",".claude.json")},set(files))
            self.assertNotIn(os.path.join(real_home,"Documents"),dirs);self.assertNotIn(os.path.join(real_home,".azure"),dirs)
            code='''import json, os
home = %r
found = {}
for root, _, names in os.walk(home):
    for name in names:
        path = os.path.join(root, name)
        try:
            with open(path) as handle: found[os.path.relpath(path, home)] = handle.read()
        except OSError as exc: found[os.path.relpath(path, home)] = "ERR"
print(json.dumps({"branch": "out", "vars": {"found": found, "home_env": os.environ["HOME"]}}))
'''%real_home
            done=self.run_ok("python",code)
            self.assertNotEqual(real_home,done["result"]["vars"]["home_env"])
            if done["sandbox"]!="bwrap":self.skipTest("bubblewrap does not work on this machine")
            found=done["result"]["vars"]["found"]
            self.assertEqual({"Documents/secret","notes.txt",".netrc",".git-credentials",".claude.json"},set(found))   # the secret folders are empty
            self.assertEqual(("TOPSECRET","TOPSECRET"),(found["Documents/secret"],found["notes.txt"]))
            for name in(".netrc",".git-credentials",".claude.json"):self.assertIn(found[name],("","ERR"),name)       # empty or unreadable, never the content
            self.assertNotIn("TOPSECRET",json.dumps({k:v for k,v in found.items() if k.startswith(".")}))
            with open(os.path.join(home,".ssh","secret")) as handle:self.assertEqual("TOPSECRET",handle.read())   # only hidden, never touched
        finally:
            if saved is None:os.environ.pop("HOME",None)
            else:os.environ["HOME"]=saved
            shutil.rmtree(home,ignore_errors=True)
    def test_the_run_itself_is_never_hidden(self):
        home=tempfile.mkdtemp(prefix="loya-home-")
        saved=os.environ.get("HOME")
        try:
            os.makedirs(os.path.join(home,".config","work"))
            os.environ["HOME"]=home
            inside=os.path.join(os.path.realpath(home),".config","work")
            dirs,_=scripts._hidden_paths(inside,["/usr/bin/python3"])
            self.assertNotIn(os.path.join(os.path.realpath(home),".config"),dirs)
            dirs,_=scripts._hidden_paths("/tmp/loya-flow-zz",[os.path.join(inside,"python3")])
            self.assertNotIn(os.path.join(os.path.realpath(home),".config"),dirs)
        finally:
            if saved is None:os.environ.pop("HOME",None)
            else:os.environ["HOME"]=saved
            shutil.rmtree(home,ignore_errors=True)
    def test_environment_switch_disables_the_sandbox(self):
        os.environ["LOYA_FLOW_NO_SANDBOX"]="1"
        try:self.assertEqual("none",self.run_ok("python","print(1)")["sandbox"])
        finally:del os.environ["LOYA_FLOW_NO_SANDBOX"]
    def test_timeout_inside_the_sandbox(self):
        started=time.monotonic()
        done=scripts.run_script("bash" if scripts.available_languages()["bash"] else "python","sleep 60 &\nsleep 60\n" if scripts.available_languages()["bash"] else "import time; time.sleep(60)",PAYLOAD,timeout=1)
        self.assertTrue(done["timed_out"]);self.assertLess(time.monotonic()-started,SLOW)
if __name__=="__main__":unittest.main()
