"""External Agents (Claude Agent / OpenAI Codex): consent, key storage, redaction, child processes, permission routing,
limits and audit. No real provider is contacted - the agent processes are stub scripts that speak the same protocol."""
import asyncio,json,os,stat,sys,tempfile,textwrap,threading,time,types,unittest
from _isolate import IsolatedData
from Cores import common_db
from Cores.Services import ai_service as ai
from Cores.Services import ext_agents_service as ext
from Cores.Services import mcp_local_service as mcp
from Cores.Services import security_service as security
from Cores.Services import ext_agent_claude_runner as runner
# The MCP tool modules register their AI Roles permissions on import. In the app they are imported at startup, before any
# consent; import them here too, so a run does not register new permissions after consent and look like a widening.
from Cores.Bridge import mcp_app_tools,mcp_chain_history_tools,mcp_flow_tools  # noqa: F401
CLAUDE_KEY="sk-ant-api03-TESTKEY-0123456789abcdefWXYZ"
CODEX_KEY="sk-proj-TESTKEY-0123456789abcdefQRST"
STUB_CLAUDE=r'''
import sys,json,os,subprocess,time
job=json.loads(sys.stdin.readline())
cwd=job["cwd"]
with open(os.path.join(cwd,"job.json"),"w") as f:json.dump({"job":job,"argv":sys.argv,"env":dict(os.environ)},f)
def emit(o):sys.stdout.write(json.dumps(o)+"\n");sys.stdout.flush()
emit({"t":"init","session_id":"sdk-1","slash_commands":["compact","security-check","config","model"],"skills":["security-check"],"tools":[],"mcp_servers":[{"name":"loya","status":"connected"}]})
if job["prompt"].startswith("SLEEP"):
    child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(120)"])
    with open(os.path.join(cwd,"child.pid"),"w") as f:f.write(str(child.pid))
    time.sleep(120)
emit({"t":"text","text":"Checking the notes first."})
emit({"t":"tool","name":"mcp__loya__notes_list","input":{}})
emit({"t":"permission","id":"p1","tool":"Bash","input":{"command":"ls -la"}})
reply=json.loads(sys.stdin.readline())
emit({"t":"usage","input_tokens":100,"output_tokens":20})
emit({"t":"text","text":"reply:%s\n```bash\nnmap -sV 10.0.0.1\n```" % reply["allow"]})
emit({"t":"result","session_id":"sdk-1","is_error":False,"subtype":"success","result":"done","cost_usd":0.0123})
'''
STUB_CODEX=r'''
import sys,json,os
data=sys.stdin.read()
with open(os.path.join(os.getcwd(),"codex.json"),"w") as f:json.dump({"argv":sys.argv,"env":dict(os.environ),"stdin":data},f)
def emit(o):sys.stdout.write(json.dumps(o)+"\n");sys.stdout.flush()
emit({"type":"thread.started","thread_id":"th-9"})
emit({"type":"turn.started"})
emit({"type":"item.started","item":{"id":"i1","type":"command_execution","command":"ls","status":"in_progress"}})
emit({"type":"item.started","item":{"id":"i2","type":"mcp_tool_call","server":"loya","tool":"notes_list","status":"in_progress"}})
emit({"type":"item.completed","item":{"id":"i3","type":"agent_message","text":"codex saw: "+data[:40]}})
emit({"type":"turn.completed","usage":{"input_tokens":50,"cached_input_tokens":0,"output_tokens":5}})
'''
def pid_alive(pid):
    try:os.kill(pid,0)
    except OSError:return False
    try:
        with open(f"/proc/{pid}/stat") as f:return f.read().split()[2]!="Z"
    except Exception:return True
class Base(unittest.TestCase):
    def setUp(self):
        self.iso=IsolatedData();self.dir=self.iso.start()
        self.tmp=tempfile.mkdtemp(prefix="loya_ext_stub_")
        self._saved={n:getattr(ext,n) for n in ("claude_runner_argv","_ensure_mcp","sdk_version","_keyring","_secrets","codex_path","codex_version")}
        claude_stub=os.path.join(self.tmp,"claude_stub.py")
        with open(claude_stub,"w") as f:f.write(STUB_CLAUDE)
        codex_stub=os.path.join(self.tmp,"codex")
        with open(codex_stub,"w") as f:f.write("#!/usr/bin/env python3\n"+STUB_CODEX)
        os.chmod(codex_stub,os.stat(codex_stub).st_mode|stat.S_IEXEC)
        ext.claude_runner_argv=lambda:[sys.executable,claude_stub]
        ext._ensure_mcp=lambda:"http://127.0.0.1:9/mcp"
        ext.sdk_version=lambda:ext.CLAUDE_SDK_VERSION
        ext._keyring=lambda:None
        ext._secrets=lambda:None
        ext.codex_path=lambda:codex_stub
        ext.codex_version=lambda:"codex-cli 0.0-test"
        ext._session_keys.clear()
        ai.revoke_session_grant()
        os.environ["LOYA_TEST_LEAK_SECRET"]="should-not-reach-agents"
    def tearDown(self):
        ext.suspend_all("test teardown")
        for n,v in self._saved.items():setattr(ext,n,v)
        ext._session_keys.clear()
        ext._discovered.clear()
        os.environ.pop("LOYA_TEST_LEAK_SECRET",None)
        common_db.set_locked(False)
        ai.revoke_session_grant()
        self.iso.stop()
    def enable(self,provider,key):
        ext.grant_consent(provider,True)
        ext.set_enabled(provider,True)
        ext.set_api_key(provider,key)
    def wait(self,run_id,timeout=20):
        end=time.time()+timeout
        while time.time()<end:
            r=ext.poll_run(run_id)
            if r["done"]:return r
            time.sleep(0.05)
        self.fail("run did not finish")
    def audit(self,event=None):
        return [e for e in security.list_audit_events(500) if event is None or e["event"]==event]
    def settings_text(self):
        with open(os.path.join(self.dir,"settings.json"),encoding="utf-8") as f:return f.read()
    def audit_text(self):
        p=os.path.join(self.dir,"security_audit.jsonl")
        with open(p,encoding="utf-8") as f:return f.read()
class ConsentTest(Base):
    def test_off_by_default_and_enable_needs_consent(self):
        self.assertFalse(ext.public_config("claude")["enabled"])
        self.assertEqual([],ext.enabled_agents())
        with self.assertRaises(ext.ExtAgentError) as cm:ext.set_enabled("claude",True)
        self.assertEqual("consent_required",cm.exception.code)
        with self.assertRaises(ext.ExtAgentError):ext.grant_consent("claude",False)
    def test_consent_recorded_with_timestamp_in_settings_and_audit(self):
        st=ext.grant_consent("codex",True)
        self.assertTrue(st["granted"]);self.assertTrue(st["ts"])
        d=json.loads(self.settings_text())
        rec=d["extensions"]["external_agents"]["providers"]["codex"]["consent"]
        self.assertIn("ts",rec);self.assertIn("snapshot",rec)
        self.assertTrue(any("OpenAI Codex: consent given" in e["detail"] for e in self.audit("ext_agent_consent")))
        ext.set_enabled("codex",True)
        self.assertEqual(["ext:codex"],[a["kind"] for a in ext.enabled_agents()])
    def test_consent_text_covers_the_required_points(self):
        info=ext.consent_info("claude")
        text=" ".join(info["points"]).lower()
        for word in ("sent to anthropic","billed","api key","ai roles","prompt injection","disclaimer","claude-agent-sdk"):self.assertIn(word,text)
        self.assertIn("Disclaimer",info["disclaimer"])
        self.assertNotIn("claude code",text)
    def test_widening_permissions_needs_reconsent(self):
        self.enable("claude",CLAUDE_KEY)
        self.assertFalse(ext.consent_state("claude")["needs_reconsent"])
        ai.set_permission_levels({"terminal_read":"ask"})
        st=ext.consent_state("claude")
        self.assertTrue(st["needs_reconsent"]);self.assertIn("Terminal > Read",st["widened"][0])
        with self.assertRaises(ext.ExtAgentError) as cm:ext.start_run("claude","s1","hi")
        self.assertEqual("reconsent_required",cm.exception.code)
        ai.set_permission_levels({"terminal_read":"deny"})
        self.assertFalse(ext.consent_state("claude")["needs_reconsent"])
        ext.set_config("claude",{"builtin_tools":["Bash","Nope"]})
        self.assertEqual(["Bash"],ext.public_config("claude")["builtin_tools"])
        self.assertTrue(ext.consent_state("claude")["needs_reconsent"])
        ext.grant_consent("claude",True)
        self.assertFalse(ext.consent_state("claude")["needs_reconsent"])
        ext.set_config("codex",{"sandbox":"workspace-write"})
        self.assertFalse(ext.consent_state("codex")["granted"])
    def test_narrowing_does_not_need_reconsent_and_disable_clears(self):
        self.enable("codex",CODEX_KEY)
        ai.set_permission_levels({"notes_add":"deny"})
        self.assertFalse(ext.consent_state("codex")["needs_reconsent"])
        ext.set_enabled("codex",False)
        self.assertFalse(ext.consent_state("codex")["granted"])
        self.assertTrue(self.audit("ext_agent_disabled"))
    def test_model_name_validated(self):
        with self.assertRaises(ext.ExtAgentError):ext.set_config("claude",{"model":"x; rm -rf /"})
        self.assertEqual("claude-opus-5-5",ext.public_config("claude")["model"])
        ext.set_config("claude",{"max_turns":999,"max_budget_usd":-4})
        c=ext.public_config("claude")
        self.assertEqual(50,c["max_turns"]);self.assertEqual(0.05,c["max_budget_usd"])
class KeysTest(Base):
    def test_session_only_when_no_keyring_and_no_encryption(self):
        st=ext.set_api_key("claude",CLAUDE_KEY)
        self.assertEqual("session",st["store"]);self.assertTrue(st["set"])
        self.assertEqual("…WXYZ",st["masked"])
        self.assertNotIn(CLAUDE_KEY,self.settings_text())
        self.assertNotIn("key_enc",json.dumps(ext.public_config("claude")))
        self.assertNotIn(CLAUDE_KEY,json.dumps(ext.public_config("claude")))
        self.assertEqual(CLAUDE_KEY,ext.get_api_key("claude"))
        ext._session_keys.clear()
        self.assertIsNone(ext.get_api_key("claude"))
        self.assertNotIn(CLAUDE_KEY,self.audit_text())
    def test_keyring_used_when_available(self):
        store={}
        kr=types.SimpleNamespace(set_password=lambda s,u,p:store.__setitem__((s,u),p),get_password=lambda s,u:store.get((s,u)),delete_password=lambda s,u:store.pop((s,u),None))
        ext._keyring=lambda:kr
        st=ext.set_api_key("codex",CODEX_KEY)
        self.assertEqual("keyring",st["store"])
        self.assertNotIn(CODEX_KEY,self.settings_text())
        ext._session_keys.clear()
        self.assertEqual(CODEX_KEY,ext.get_api_key("codex"))
        ext.clear_api_key("codex")
        self.assertEqual({},store)
        self.assertFalse(ext.key_state("codex")["set"])
    def test_encrypted_store_fallback(self):
        """No keyring: the key goes to the encrypted database's Secrets table (Cores.secret_store), never settings.json."""
        store={}
        st=types.SimpleNamespace(put=lambda n,v,h=None:store.__setitem__(n,v) or True,get=lambda n:store.get(n),delete=lambda n:store.pop(n,None))
        ext._secrets=lambda:st
        res=ext.set_api_key("claude",CLAUDE_KEY)
        self.assertEqual("encrypted",res["store"])
        self.assertNotIn(CLAUDE_KEY,self.settings_text())
        ext._session_keys.clear()
        self.assertEqual(CLAUDE_KEY,ext.get_api_key("claude"))
        ext._session_keys.clear();ext._secrets=lambda:None
        self.assertIsNone(ext.get_api_key("claude"))
        self.assertTrue(ext.key_state("claude")["stored_but_locked"])
    def test_rejects_garbage(self):
        with self.assertRaises(ext.ExtAgentError):ext.set_api_key("claude","has space")
class RedactionTest(Base):
    def test_note_secrets_and_patterns(self):
        html='<p>Creds: <span class="note-secret">Winter2024!</span></p><div data-callout="credential">password: hunter2</div><pre>mysql -u root --password s3cr3t</pre><p>api_key=AKIAABCDEFGHIJKLMNOP</p>'
        out=ext.redact_text(html)
        for s in ("Winter2024!","hunter2","s3cr3t","AKIAABCDEFGHIJKLMNOP"):self.assertNotIn(s,out)
        self.assertIn("note-secret",out)
    def test_tool_result(self):
        from mcp.types import CallToolResult,TextContent
        r=CallToolResult(content=[TextContent(type="text",text='{"content":"token: abcdef123456"}')],structured_content={"result":{"content":"password=hunter2","n":3}})
        out=ext.redact_tool_result(r)
        self.assertNotIn("abcdef123456",out.content[0].text)
        self.assertNotIn("hunter2",json.dumps(out.structured_content))
        self.assertEqual(3,out.structured_content["result"]["n"])
    def test_redaction_toggle_is_audited(self):
        self.assertTrue(ext.redaction_enabled())
        ext.set_redaction(False);self.assertFalse(ext.redaction_enabled())
        self.assertTrue(any("OFF" in e["detail"] for e in self.audit("ext_agent_settings")))
class ProcessTest(Base):
    def test_child_env_is_minimal(self):
        env=ext.child_env({"X":"1"})
        self.assertNotIn("LOYA_TEST_LEAK_SECRET",env)
        self.assertEqual("1",env["X"])
        self.assertIn("PATH",env)
    @unittest.skipIf(os.name=="nt","POSIX process checks and a shebang stub; Windows uses taskkill /T - see the Windows checklist")
    def test_kill_tree_kills_grandchildren(self):
        import subprocess
        pidfile=os.path.join(self.tmp,"gc.pid")
        code=f"import subprocess,sys,time;p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);open({pidfile!r},'w').write(str(p.pid));time.sleep(60)"
        proc=subprocess.Popen([sys.executable,"-c",code],**ext._popen_flags(True))
        end=time.time()+10
        while not os.path.exists(pidfile) and time.time()<end:time.sleep(0.05)
        time.sleep(0.1)
        gc=int(open(pidfile).read())
        self.assertTrue(pid_alive(gc))
        ext.kill_tree(proc)
        self.assertIsNotNone(proc.poll())
        end=time.time()+5
        while pid_alive(gc) and time.time()<end:time.sleep(0.05)
        self.assertFalse(pid_alive(gc))
class ClaudeRunTest(Base):
    def test_full_turn_routes_permissions_and_audits(self):
        self.enable("claude",CLAUDE_KEY)
        rid=ext.start_run("claude","sessA","summarise my notes, password=hunter2",[{"role":"user","content":"earlier"}],{"display":"summarise"})
        r=self.wait(rid)
        hist=r["history"]
        self.assertEqual(["user","user","assistant"],[t["role"] for t in hist])
        self.assertEqual("summarise",hist[1]["display"])
        reply=hist[-1]["content"]
        self.assertIn("Checking the notes first.",reply)
        self.assertIn("reply:False",reply)
        self.assertIn("notes_list",hist[-1]["agent_tools"])
        ws=ext.workspace("claude","sessA")
        rec=json.load(open(os.path.join(ws,"job.json")))
        job,env,argv=rec["job"],rec["env"],rec["argv"]
        self.assertNotIn("hunter2",job["prompt"])
        self.assertEqual(CLAUDE_KEY,env["ANTHROPIC_API_KEY"])
        self.assertNotIn("LOYA_TEST_LEAK_SECRET",env)
        self.assertNotIn(CLAUDE_KEY," ".join(argv))
        self.assertNotIn(CLAUDE_KEY,json.dumps(job))
        self.assertEqual(ext.claude_config_dir(),env["CLAUDE_CONFIG_DIR"])
        self.assertEqual(["Skill"],job["tools"])
        for t in ext.CLAUDE_OPTIONAL_TOOLS:self.assertIn(t,job["disallowed_tools"])
        self.assertEqual(["mcp__loya"],job["allowed_tools"])
        self.assertEqual(8,job["max_turns"]);self.assertEqual(1.0,job["max_budget_usd"])
        self.assertTrue(job["cwd"].startswith(os.path.join(self.dir,"external_agents")))
        self.assertFalse(os.path.exists(job["mcp_config"]),"per-run MCP config with the token is deleted afterwards")
        self.assertEqual({},mcp._client_tokens)
        self.assertTrue(any(e["event"]=="ext_agent_tool" and "built-in Bash deny" in e["detail"] for e in self.audit()))
        starts=[e["detail"] for e in self.audit("ext_agent_session")]
        self.assertTrue(any("sessA" in d and "started" in d for d in starts))
        self.assertTrue(any("sessA" in d and "ended" in d for d in starts))
        self.assertTrue(any("nmap -sV 10.0.0.1" in e["detail"] for e in self.audit("ext_agent_command_proposal")))
        self.assertNotIn(CLAUDE_KEY,self.audit_text())
        self.assertNotIn("hunter2",self.audit_text())
        self.assertEqual(1,ext.usage_today("claude")["requests"]);self.assertEqual(120,ext.usage_today("claude")["tokens"])
        self.assertEqual(["security-check","compact"],ext._discovered["claude"],"skills plus safe built-ins only - no /config or /model")
        rid=ext.start_run("claude","sessA","again",[])
        self.wait(rid)
        self.assertEqual("sdk-1",json.load(open(os.path.join(ws,"job.json")))["job"]["resume"])
    def test_opted_in_builtin_tool_asks_the_operator(self):
        self.enable("claude",CLAUDE_KEY)
        ext.set_config("claude",{"builtin_tools":["Bash"]})
        ext.grant_consent("claude",True)
        seen={}
        def approve():
            end=time.time()+15
            while time.time()<end:
                rows=ai.pending_approvals()
                if rows:
                    seen.update(rows[0]);ai.resolve_approval(rows[0]["id"],"once");return
                time.sleep(0.02)
        t=threading.Thread(target=approve,daemon=True);t.start()
        r=self.wait(ext.start_run("claude","sessB","list files",[]))
        t.join()
        self.assertIn("reply:True",r["history"][-1]["content"])
        self.assertEqual("Claude Agent",seen["client"])
        self.assertEqual(("Claude Agent","Bash"),(seen["entity"],seen["action"]))
        self.assertIn("Checking the notes first.",seen["reason"])
    def test_builtin_tool_decisions(self):
        ws=ext.workspace("claude","s9")
        cfg={"builtin_tools":["Read","Write"]}
        self.assertEqual("allow",ext.builtin_tool_decision(cfg,ws,"Read",{"file_path":os.path.join(ws,"a.txt")})[0])
        self.assertEqual("deny",ext.builtin_tool_decision(cfg,ws,"Read",{"file_path":"/etc/passwd"})[0])
        self.assertEqual("deny",ext.builtin_tool_decision(cfg,ws,"Read",{"file_path":os.path.join(ws,"..","..","x")})[0])
        self.assertEqual("ask",ext.builtin_tool_decision(cfg,ws,"Write",{"file_path":"b.txt"})[0])
        self.assertEqual("deny",ext.builtin_tool_decision(cfg,ws,"Bash",{"command":"id"})[0])
    @unittest.skipIf(os.name=="nt","POSIX process checks and a shebang stub; Windows uses taskkill /T - see the Windows checklist")
    def test_stop_kills_the_process_tree(self):
        self.enable("claude",CLAUDE_KEY)
        rid=ext.start_run("claude","sessC","SLEEP please",[])
        ws=ext.workspace("claude","sessC")
        end=time.time()+10
        while not os.path.exists(os.path.join(ws,"child.pid")) and time.time()<end:time.sleep(0.05)
        time.sleep(0.1)
        gc=int(open(os.path.join(ws,"child.pid")).read())
        with ext._runs_lock:proc=ext._runs[rid].proc
        self.assertTrue(ext.stop_run(rid))
        r=self.wait(rid)
        self.assertIn("Stopped: stopped by the operator",r["history"][-1]["content"])
        self.assertIsNotNone(proc.poll())
        end=time.time()+5
        while pid_alive(gc) and time.time()<end:time.sleep(0.05)
        self.assertFalse(pid_alive(gc))
        self.assertTrue(self.audit("ext_agent_stopped"))
    def test_lock_suspends_agents_and_blocks_new_runs(self):
        self.enable("claude",CLAUDE_KEY)
        rid=ext.start_run("claude","sessD","SLEEP",[])
        time.sleep(0.5)
        security._suspend_agents()
        r=self.wait(rid)
        self.assertIn("app locked",r["history"][-1]["content"])
        common_db.set_locked(True)
        with self.assertRaises(ext.ExtAgentError) as cm:ext.start_run("claude","sessE","hi")
        self.assertEqual("locked",cm.exception.code)
    def test_daily_budget(self):
        self.enable("claude",CLAUDE_KEY)
        ext.set_config("claude",{"daily_requests":1})
        self.wait(ext.start_run("claude","sessF","one",[]))
        with self.assertRaises(ext.ExtAgentError) as cm:ext.start_run("claude","sessF","two",[])
        self.assertEqual("budget",cm.exception.code)
    def test_preflight_errors(self):
        with self.assertRaises(ext.ExtAgentError) as cm:ext.start_run("claude","s","hi")
        self.assertEqual("disabled",cm.exception.code)
        ext.grant_consent("claude",True);ext.set_enabled("claude",True)
        with self.assertRaises(ext.ExtAgentError) as cm:ext.start_run("claude","s","hi")
        self.assertEqual("no_key",cm.exception.code)
        ext.sdk_version=lambda:None
        with self.assertRaises(ext.ExtAgentError) as cm:ext.start_run("claude","s","hi")
        self.assertEqual("not_installed",cm.exception.code)
        self.assertEqual("not_installed",ext.provider_status("claude")["reason"])
class CodexRunTest(Base):
    @unittest.skipIf(os.name=="nt","POSIX process checks and a shebang stub; Windows uses taskkill /T - see the Windows checklist")
    def test_codex_runs_read_only_with_key_in_env_only(self):
        self.enable("codex",CODEX_KEY)
        r=self.wait(ext.start_run("codex","sessX","what is in my notes? token=abcdef0123456",[]))
        self.assertIn("codex saw:",r["history"][-1]["content"])
        rec=json.load(open(os.path.join(ext.workspace("codex","sessX"),"codex.json")))
        argv,env=rec["argv"],rec["env"]
        self.assertIn("--ignore-user-config",argv);self.assertIn("--json",argv)
        self.assertEqual("read-only",argv[argv.index("-s")+1])
        self.assertIn('approval_policy="never"',argv)
        self.assertIn('mcp_servers.loya.bearer_token_env_var="LOYA_MCP_TOKEN"',argv)
        self.assertEqual("-",argv[-1])
        self.assertNotIn(CODEX_KEY," ".join(argv))
        self.assertNotIn(env["LOYA_MCP_TOKEN"]," ".join(argv))
        self.assertEqual(CODEX_KEY,env["CODEX_API_KEY"])
        self.assertEqual(ext.codex_home(),env["CODEX_HOME"])
        self.assertNotIn("LOYA_TEST_LEAK_SECRET",env)
        self.assertNotIn("abcdef0123456",rec["stdin"])
        self.assertTrue(any("shell (Codex sandbox)" in e["detail"] for e in self.audit("ext_agent_tool")))
        self.wait(ext.start_run("codex","sessX","more",[]))
        argv=json.load(open(os.path.join(ext.workspace("codex","sessX"),"codex.json")))["argv"]
        self.assertEqual(["resume","th-9","-"],argv[-3:])
    def test_not_installed_state(self):
        ext.codex_path=lambda:None
        st=ext.provider_status("codex")
        self.assertFalse(st["installed"]);self.assertEqual("not_installed",st["reason"])
class SkillsTest(Base):
    def test_skills_listed_with_source_and_dispatch(self):
        home=os.path.join(self.tmp,"home")
        os.makedirs(os.path.join(home,".claude","skills","recon-sum"))
        with open(os.path.join(home,".claude","skills","recon-sum","SKILL.md"),"w") as f:f.write("---\nname: recon-sum\ndescription: Summarise recon\n---\nbody")
        os.makedirs(os.path.join(home,".claude","skills","hidden"))
        with open(os.path.join(home,".claude","skills","hidden","SKILL.md"),"w") as f:f.write("---\nname: hidden\nuser-invocable: false\n---\n")
        os.makedirs(os.path.join(home,".codex","prompts"))
        with open(os.path.join(home,".codex","prompts","triage.md"),"w") as f:f.write("---\ndescription: Triage\n---\nTriage this: $ARGUMENTS")
        old=os.environ.get("HOME");os.environ["HOME"]=home
        try:
            rows=ext.list_skills("claude")
            names={r["name"]:r for r in rows}
            self.assertIn("recon-sum",names);self.assertNotIn("hidden",names)
            self.assertIn("personal",names["recon-sum"]["source"])
            ext._discovered["claude"]=["compact","recon-sum"]
            names={r["name"]:r for r in ext.list_skills("claude")}
            self.assertIn("reported by Claude Agent",names["compact"]["source"])
            self.assertEqual("/recon-sum 10.0.0.0/24",ext.skill_prompt("claude","recon-sum","10.0.0.0/24"))
            self.assertEqual("Triage this: web01",ext.skill_prompt("codex","triage","web01"))
            ext.set_config("claude",{"personal_skills":False})
            ext._discovered.clear()
            self.assertNotIn("recon-sum",{r["name"] for r in ext.list_skills("claude")})
        finally:
            if old is None:os.environ.pop("HOME",None)
            else:os.environ["HOME"]=old
class PermissionSummaryTest(Base):
    def test_summary(self):
        s=ext.permission_summary("claude")
        self.assertIn("delete: off",s);self.assertIn("terminal: off",s);self.assertIn("built-in tools: none",s)
        self.assertIn("sandbox: read-only",ext.permission_summary("codex"))
# ---------------------------------------------------------------- the real runner module, against a fake SDK
class FakeSDK:
    def __init__(self):
        class _O:
            def __init__(s,**kw):s.__dict__.update(kw)
        self.ClaudeAgentOptions=_O
        class SystemMessage:
            def __init__(s,subtype,data):s.subtype=subtype;s.data=data
        class ResultMessage:
            def __init__(s,**kw):s.__dict__.update(dict(subtype="success",is_error=False,result="ok",total_cost_usd=0.01,num_turns=1,usage={},session_id="S"),**kw)
        class AssistantMessage:
            def __init__(s,content,parent_tool_use_id=None,usage=None,message_id=None):s.content=content;s.parent_tool_use_id=parent_tool_use_id;s.usage=usage;s.message_id=message_id
        class TextBlock:
            def __init__(s,text):s.text=text
        class ToolUseBlock:
            def __init__(s,id,name,input):s.id=id;s.name=name;s.input=input
        class StreamEvent:
            def __init__(s,event,parent_tool_use_id=None):s.event=event;s.parent_tool_use_id=parent_tool_use_id
        self.SystemMessage=SystemMessage;self.ResultMessage=ResultMessage;self.AssistantMessage=AssistantMessage
        self.TextBlock=TextBlock;self.ToolUseBlock=ToolUseBlock;self.StreamEvent=StreamEvent
class RunnerTest(unittest.TestCase):
    def setUp(self):
        self.out=[]
        self._emit=runner.emit
        runner.emit=lambda o:self.out.append(o)
    def tearDown(self):runner.emit=self._emit
    def test_build_options_locks_down_tools(self):
        sdk=FakeSDK()
        job=ext._claude_job(dict(ext._DEFAULTS["claude"]),None,"hi","/ws","/run/x.mcp.json",None)
        o=build=runner.build_options(sdk,job,can_use_tool="CB")
        self.assertEqual(["Skill"],o.tools)
        self.assertEqual("/run/x.mcp.json",o.mcp_servers)
        self.assertTrue(o.strict_mcp_config)
        self.assertEqual("default",o.permission_mode)
        self.assertEqual("CB",o.can_use_tool)
        self.assertEqual("claude-opus-5-5",o.model);self.assertEqual("high",o.effort)
        self.assertEqual(["user","project"],o.setting_sources)
        self.assertEqual("LOYA-NG/1.0.1",o.client_app)
        self.assertFalse(hasattr(o,"sandbox"))
        self.assertEqual({"disableAllHooks":True},json.loads(o.settings))
        self.assertNotIn("Claude Code",job["system_prompt"])
        job=ext._claude_job(dict(ext._DEFAULTS["claude"],builtin_tools=["Bash"]),None,"hi","/ws","/m",None)
        o=runner.build_options(sdk,job)
        self.assertEqual(["Bash","Skill"],o.tools)
        self.assertEqual({"enabled":True,"autoAllowBashIfSandboxed":False,"allowUnsandboxedCommands":False,"failIfUnavailable":True},o.sandbox)
    def test_message_mapping(self):
        sdk=FakeSDK();seen=set()
        runner.handle_message(sdk,sdk.SystemMessage("init",{"session_id":"S","slash_commands":["compact"],"mcp_servers":[{"name":"loya","status":"connected"}]}),seen)
        runner.handle_message(sdk,sdk.StreamEvent({"type":"content_block_delta","delta":{"type":"text_delta","text":"Hel"}}),seen)
        runner.handle_message(sdk,sdk.StreamEvent({"type":"content_block_delta","delta":{"type":"text_delta","text":"sub"}},parent_tool_use_id="t"),seen)
        runner.handle_message(sdk,sdk.AssistantMessage([sdk.TextBlock("Hello"),sdk.ToolUseBlock("t1","mcp__loya__notes_list",{})],usage={"input_tokens":5,"output_tokens":2},message_id="m1"),seen)
        runner.handle_message(sdk,sdk.AssistantMessage([sdk.TextBlock("again")],usage={"input_tokens":5,"output_tokens":2},message_id="m1"),seen)
        done=runner.handle_message(sdk,sdk.ResultMessage(),seen)
        self.assertTrue(done)
        kinds=[o["t"] for o in self.out]
        self.assertEqual(["init","delta","text","tool","usage","text","result"],kinds)
        self.assertEqual(["compact"],self.out[0]["slash_commands"])
        self.assertEqual(0.01,self.out[-1]["cost_usd"])
    def test_permission_round_trip(self):
        async def go():
            loop=asyncio.get_running_loop()
            b=runner.Bridge(loop)
            r,w=os.pipe()
            rf=os.fdopen(r,"r");wf=os.fdopen(w,"w")
            b.start_reader(rf)
            task=asyncio.ensure_future(b.ask("Bash",{"command":"id"}))
            for _ in range(100):
                if self.out:break
                await asyncio.sleep(0.01)
            pid=self.out[0]["id"]
            wf.write(json.dumps({"t":"permission_reply","id":pid,"allow":False,"message":"no"})+"\n");wf.flush()
            res=await asyncio.wait_for(task,5)
            wf.close()
            return res
        res=asyncio.run(go())
        self.assertEqual({"t":"permission_reply","id":self.out[0]["id"],"allow":False,"message":"no"},res)
        self.assertEqual("permission",self.out[0]["t"])
if __name__=="__main__":
    unittest.main()
class BundledSkillsTest(Base):
    def test_installed_for_both_agents_on_run(self):
        self.enable("claude",CLAUDE_KEY);self.enable("codex",CODEX_KEY)
        self.wait(ext.start_run("claude","sk1","hi",[]))
        self.wait(ext.start_run("codex","sk2","hi",[]))
        srcs=ext.bundled_skill_sources()
        self.assertGreaterEqual(len(srcs),5)
        for dest in (os.path.join(ext.claude_project_dir(),".claude","skills"),os.path.join(ext.workspace("codex","sk2"),".agents","skills")):
            for s in srcs:
                p=os.path.join(dest,s["dir"],"SKILL.md")
                self.assertEqual(s["data"],open(p,"rb").read(),p)
                man=json.load(open(os.path.join(dest,s["dir"],ext.SKILL_MANIFEST)))
                self.assertEqual(s["version"],man["version"])
    def test_user_edits_are_never_overwritten_and_old_versions_update(self):
        dest=os.path.join(self.tmp,"skills")
        self.assertTrue(all(v=="installed" for v in ext.install_bundled_skills(dest).values()))
        self.assertTrue(all(v=="current" for v in ext.install_bundled_skills(dest).values()))
        p=os.path.join(dest,"loya-notes","SKILL.md")
        with open(p,"a") as f:f.write("\nMy own house rules.\n")
        self.assertEqual("kept_user_copy",ext.install_bundled_skills(dest)["loya-notes"])
        self.assertIn("My own house rules.",open(p).read())
        old=b"---\nname: loya-recon\ndescription: old\n---\n<!-- loya-skill-version: 0 -->\nold\n"
        q=os.path.join(dest,"loya-recon","SKILL.md")
        open(q,"wb").write(old)
        json.dump({"version":0,"sha256":ext._sha(old)},open(os.path.join(dest,"loya-recon",ext.SKILL_MANIFEST),"w"))
        self.assertEqual("updated",ext.install_bundled_skills(dest)["loya-recon"])
        self.assertNotEqual(old,open(q,"rb").read())
    def test_skill_format_is_neutral_and_names_real_tools(self):
        """The same SKILL.md must load in Codex (.agents/skills: name + description frontmatter) and in Claude."""
        import re
        from Cores.Services import ai_chat_service as chat
        tools={t.name for t in chat._list_tools()}
        future={"chain_get","chain_templates","chain_create","chain_update","chain_dry_run","chain_run","chain_run_status","chain_run_stop"}
        for s in ext.bundled_skill_sources():
            text=s["data"].decode("utf-8")
            self.assertTrue(text.startswith("---\n"),s["name"])
            fm=ext._frontmatter(os.path.join(ext.bundled_skills_dir(),s["dir"],"SKILL.md"))
            self.assertEqual(s["dir"],fm.get("name"));self.assertTrue(fm.get("description"))
            self.assertLess(len(fm["description"]),1024)
            self.assertTrue(re.match(r"^[a-z0-9-]{1,64}$",fm["name"]))
            self.assertGreaterEqual(s["version"],1)
            for bad in ("$ARGUMENTS","allowed-tools","${CLAUDE_","Claude Code","!`"):self.assertNotIn(bad,text,f"{s['name']}: {bad}")
            for tok in set(re.findall(r"`([a-z]+_[a-z_]+)",text)):
                if tok.startswith(("notes_","commands_","targets_","target_","reports_","report_","findings_","cve_","quickrun_","chains_","chain_","terminal_","app_","dashboard_","parameter_","evidence_","audit_")):
                    self.assertTrue(tok in tools or tok in future,f"{s['name']} names unknown tool {tok}")
    def test_listed_and_dispatched_for_both(self):
        for p in ("claude","codex"):
            rows=[r for r in ext.list_skills(p) if r["source"]=="LOYA skill"]
            self.assertEqual({"loya-basics","loya-notes","loya-reporting","loya-recon","loya-chains"},{r["name"] for r in rows}-set())
        self.assertEqual("/loya-recon 10.0.0.5",ext.skill_prompt("claude","loya-recon","10.0.0.5"))
        self.assertEqual("$loya-recon 10.0.0.5",ext.skill_prompt("codex","loya-recon","10.0.0.5"))
