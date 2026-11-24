"""Connections (Settings > AI > Agents): hook the operator's OWN official Claude Code / Codex CLI up to LOYA.

This is the same model the VS Code extensions use: the operator installs the official CLI and signs in to it themselves
(their own subscription or key, the vendor's own browser flow). LOYA only
- detects the CLI (path and version) and asks the CLI for its sign-in state with the CLI's own command,
- opens a terminal running the CLI's own sign-in command, so the operator finishes the official flow themselves,
- registers LOYA's MCP server in the CLI's user config with the CLI's own `mcp add` command, and installs the bundled
  LOYA skills where that CLI looks for personal skills.

LOYA never reads, copies or stores the CLI's credentials (~/.claude, ~/.codex, auth.json, keychains). LOYA's in-app
Claude Agent stays on API key / Bedrock / Vertex auth and never offers claude.ai login (Anthropic's Agent SDK policy).

How the CLI reaches LOYA: the registered server is a stdio command, `<LOYA python> -I Cores/Bridge/mcp_cli_bridge.py
--client <tool> --token-file <file>`. The bridge forwards to the in-app HTTP MCP server with a per-connection bearer token
kept in that file (Data/external_agents/connections/<tool>.json, owner-only). The server maps the token to the client
"Claude Code (your CLI)" / "Codex CLI (your CLI)", so every call goes through ai_service.authorize (AI Roles), Ask prompts
name the CLI, and the audit log records it. Disconnect removes the registration and deletes the file (instant revoke).

CLI commands used (from the vendors' CLI references, read 2026-11-24; the CLIs were not installed on the dev machine):
  claude --version | claude auth status (JSON; exit 0 signed in, 1 not) | claude auth login
  claude mcp add --scope user --transport stdio <name> -- <cmd> [args] | claude mcp remove --scope user <name> | claude mcp get <name>
  codex --version | codex login status (exit 0 when signed in) | codex login
  codex mcp add <name> -- <cmd> [args] | codex mcp remove <name> | codex mcp get <name> --json
Older CLIs without one of these answer with an error; that is reported as "unknown", never guessed.
"""
import os,sys,re,json,glob,shlex,shutil,secrets,hmac,hashlib,signal,tempfile,threading,time,subprocess,uuid
from datetime import datetime,timezone
TOOLS=("claude_code","codex_cli")
SERVER_NAME="loya-note"
TOOL_INFO={
    "claude_code":{"label":"Claude Code","vendor":"Anthropic","exe":"claude","client_label":"Claude Code (your CLI)",
                   "docs":"https://code.claude.com/docs/en/setup",
                   "login":["auth","login"],"status":["auth","status"]},
    "codex_cli":{"label":"Codex CLI","vendor":"OpenAI","exe":"codex","client_label":"Codex CLI (your CLI)",
                 "docs":"https://developers.openai.com/codex/cli",
                 "login":["login"],"status":["login","status"]},
}
CLI_TIMEOUT=20
_IS_WINDOWS=os.name=="nt"
_lock=threading.Lock()
class ConnectionError_(Exception):pass
def _ext():
    from Cores.Services import ext_agents_service as m
    return m
def _tool(tool):
    tool=str(tool or "")
    if tool not in TOOLS:raise ConnectionError_(f"Unknown CLI: {tool}")
    return tool
def _now_iso():return datetime.now(timezone.utc).isoformat()
def _audit(event,detail,success=True):
    try:_ext()._audit(event,detail,success)
    except Exception:pass
# ---------------------------------------------------------------- connection files
def connections_dir():
    d=os.path.normpath(os.path.join(_ext().base_dir(),"connections"))
    os.makedirs(d,exist_ok=True)
    if not _IS_WINDOWS:
        try:os.chmod(d,0o700)
        except OSError:pass
    return d
def connection_file(tool):return os.path.join(connections_dir(),_tool(tool)+".json")
def _read_conn(tool):
    try:
        with open(connection_file(tool),"r",encoding="utf-8") as f:d=json.load(f)
        return d if isinstance(d,dict) and d.get("token") else None
    except Exception:return None
def _write_conn(tool,data):
    p=connection_file(tool)
    tmp=p+".tmp"
    fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,"w",encoding="utf-8") as f:json.dump(data,f,indent=1)
    os.replace(tmp,p)
    if not _IS_WINDOWS:
        try:os.chmod(p,0o600)
        except OSError:pass
    _refresh_cache()
def _delete_conn(tool):
    try:os.remove(connection_file(tool))
    except FileNotFoundError:pass
    _refresh_cache()
# ---------------------------------------------------------------- token check (called by the MCP server for every request)
_cache={"tokens":None}
def _refresh_cache():
    with _lock:_cache["tokens"]=None
def _tokens():
    with _lock:
        if _cache["tokens"] is None:
            toks=[]
            for t in TOOLS:
                c=_read_conn(t)
                if c:toks.append((str(c["token"]),t))
            _cache["tokens"]=toks
        return list(_cache["tokens"])
def client_for(tool):
    info=TOOL_INFO[tool]
    return {"id":"cli:"+tool,"label":info["client_label"],"provider":tool,"session_id":""}
def resolve_token(presented):
    """mcp_local_service token resolver: the CLI connection a bearer token belongs to, or None (constant-time compare)."""
    if not presented or not isinstance(presented,str):return None
    p=presented.encode("utf-8","replace")
    hit=None
    for tok,tool in _tokens():
        if hmac.compare_digest(p,tok.encode("utf-8")) and hit is None:hit=tool
    return client_for(hit) if hit else None
def _register_resolver():
    try:
        from Cores.Services import mcp_local_service as _mcp
        _mcp.add_token_resolver(resolve_token)
    except Exception:pass
_register_resolver()
# ---------------------------------------------------------------- detection
def _home():return os.path.expanduser("~")
def _candidate_dirs(exe):
    home=_home()
    if _IS_WINDOWS:
        appdata=os.environ.get("APPDATA") or os.path.join(home,"AppData","Roaming")
        local=os.environ.get("LOCALAPPDATA") or os.path.join(home,"AppData","Local")
        dirs=[os.path.join(appdata,"npm"),                                   # npm install -g
              os.path.join(home,".local","bin"),                             # Claude Code native installer (install.ps1)
              os.path.join(local,"Microsoft","WinGet","Links"),              # winget
              os.path.join(local,"Programs",exe),os.path.join(local,"Programs",exe,"bin"),
              os.path.join(home,"scoop","shims"),os.path.join(home,".bun","bin"),os.path.join(home,".volta","bin")]
        if exe=="claude":dirs.append(os.path.join(home,".claude","local"))
        return dirs
    dirs=[os.path.join(home,".local","bin"),os.path.join(home,".npm-global","bin"),os.path.join(home,".bun","bin"),os.path.join(home,".volta","bin"),
          "/usr/local/bin","/usr/bin","/opt/homebrew/bin","/snap/bin"]
    if exe=="claude":dirs.append(os.path.join(home,".claude","local"))
    dirs+=sorted(glob.glob(os.path.join(home,".nvm","versions","node","*","bin")),reverse=True)
    return dirs
def _names(exe):return [exe+".exe",exe+".cmd",exe+".bat",exe] if _IS_WINDOWS else [exe]
def find_cli(tool):
    """(path, how) for the official CLI: PATH first, then the usual install folders; (None, "") when not found."""
    exe=TOOL_INFO[_tool(tool)]["exe"]
    p=shutil.which(exe)
    if p:return os.path.abspath(p),"PATH"
    for d in _candidate_dirs(exe):
        for n in _names(exe):
            c=os.path.join(d,n)
            if os.path.isfile(c) and (_IS_WINDOWS or os.access(c,os.X_OK)):return c,d
    return None,""
def _flags():
    return {"creationflags":0x08000000} if _IS_WINDOWS else {}  # CREATE_NO_WINDOW: no console flashes on Windows
def _cli_env():
    """The operator's own environment (HOME, CLAUDE_CONFIG_DIR, CODEX_HOME, PATH...): the CLI must see its own config.
    LOYA's own MCP/agent variables are left out."""
    env=dict(os.environ)
    for k in list(env):
        if k.startswith("LOYA_"):env.pop(k,None)
    return env
class Cancelled(Exception):
    """The operator pressed Cancel while this step was running."""
_job_local=threading.local()
def _current_job():return getattr(_job_local,"job",None)
def _popen_kw():
    """The CLI runs in its own process group / session, so a timeout or Cancel can stop it together with anything it
    started, and nothing it does to its own group can reach LOYA NG."""
    if _IS_WINDOWS:return {"creationflags":0x08000000|0x00000200}  # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    return {"start_new_session":True}
def _kill_tree(proc):
    if _IS_WINDOWS:
        try:subprocess.run(["taskkill","/T","/F","/PID",str(proc.pid)],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10,creationflags=0x08000000)
        except Exception:pass
    else:
        try:os.killpg(proc.pid,signal.SIGKILL)
        except Exception:pass
    try:proc.kill()
    except Exception:pass
    try:proc.wait(timeout=5)
    except Exception:pass
def _decode(b):return (b or b"").decode("utf-8","replace").replace("\r\n","\n")
def _run(argv,timeout=CLI_TIMEOUT,env=None):
    """(rc, stdout, stderr). Never waits longer than `timeout` (rc 124) and never blocks on stdin (DEVNULL): the output goes
    to temp files, not pipes, so a helper the CLI leaves running cannot keep this call waiting for the pipe to close.
    In a connection job, Cancel stops the CLI at once (raises Cancelled)."""
    job=_current_job()
    if job is not None and job.cancelled:raise Cancelled()
    with tempfile.TemporaryFile() as out,tempfile.TemporaryFile() as err:
        try:
            proc=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=out,stderr=err,env=_cli_env() if env is None else env,**_popen_kw())
        except OSError as e:
            return 127,"",str(e)
        if job is not None:job.procs.add(proc)
        deadline=time.monotonic()+max(0.1,float(timeout))
        rc=None
        try:
            while rc is None:
                try:rc=proc.wait(timeout=0.1)
                except subprocess.TimeoutExpired:pass
                if rc is not None:break
                if job is not None and job.cancelled:
                    _kill_tree(proc)
                    raise Cancelled()
                if time.monotonic()>=deadline:
                    _kill_tree(proc)
                    rc=124
        finally:
            if job is not None:job.procs.discard(proc)
        out.seek(0);err.seek(0)
        o,e=_decode(out.read()),_decode(err.read())
    if rc==124:return 124,o,(e+"\n" if e else "")+"timed out"
    return rc,o,e
def _clean(text,limit=200):
    t=" ".join(str(text or "").split())
    try:t=_ext().redact_text(t)
    except Exception:pass
    return t[:limit]
def cli_version(path):
    rc,out,err=_run([path,"--version"],timeout=15)
    if rc!=0:return ""
    line=(out or err).strip().splitlines()
    return _clean(line[0],80) if line else ""
_help_cache={}
def _group_has(tool,path,word):
    """True when `<cli> <group> --help` lists that subcommand (group: `auth` for claude, `login` for codex). Checked first
    because an old CLI that does not know the subcommand could read "auth status" as a prompt and start a session;
    --help never does."""
    group=TOOL_INFO[tool]["status"][:-1]
    try:key=(path,os.path.getmtime(path))
    except OSError:key=(path,0)
    if key not in _help_cache:
        rc,out,err=_run([path]+group+["--help"],timeout=15)
        _help_cache[key]=(out+"\n"+err) if rc==0 else ""
    return bool(re.search(r"^\s*"+re.escape(word)+r"\b",_help_cache[key],re.M))
def supports_status(tool,path):return _group_has(tool,path,"status")
def login_args(tool,path):
    """The CLI's own sign-in command. Claude Code before `claude auth login` existed: start `claude` and type /login."""
    if tool=="claude_code" and not _group_has(tool,path,"login"):return []
    return list(TOOL_INFO[tool]["login"])
_UNKNOWN_RX=re.compile(r"unknown (command|subcommand|option)|unrecognized|unexpected argument|invalid choice|no such command|not a valid",re.I)
def signin_status(tool,path=None):
    """{"state": signed_in|signed_out|unknown, "detail": short text}. Asks the CLI itself; never reads its credential files."""
    tool=_tool(tool)
    path=path or find_cli(tool)[0]
    if not path:return {"state":"unknown","detail":"Not installed."}
    if not supports_status(tool,path):
        return {"state":"unknown","detail":"This version of the CLI has no '"+" ".join(TOOL_INFO[tool]["status"])+"' command. Update it, or sign in and use it."}
    rc,out,err=_run([path]+TOOL_INFO[tool]["status"])
    text=(out.strip() or err.strip())
    if tool=="claude_code":
        try:d=json.loads(out)
        except Exception:d=None
        if isinstance(d,dict):
            signed=bool(d.get("loggedIn",rc==0)) and str(d.get("authMethod") or "")!="none"
            method={"claude.ai":"Claude account (subscription)","oauth_token":"OAuth token","api_key":"API key","api_key_helper":"API key helper","third_party":"Bedrock / Vertex / Foundry"}.get(str(d.get("authMethod") or ""),str(d.get("authMethod") or ""))
            who=d.get("email") or d.get("account") or ""
            bits=[x for x in (method,who if isinstance(who,str) else "",d.get("orgName") if isinstance(d.get("orgName"),str) else "") if x]
            return {"state":"signed_in" if signed else "signed_out","detail":_clean(" | ".join(bits) if signed else "Not signed in.")}
    if _UNKNOWN_RX.search(text) or rc in (124,127):
        return {"state":"unknown","detail":"This version of the CLI cannot report its sign-in state"+(" (timed out)" if rc==124 else "")+". Update it, or sign in and use it."}
    if rc==0:return {"state":"signed_in","detail":_clean(text.splitlines()[0] if text else "Signed in.")}
    return {"state":"signed_out","detail":_clean(text.splitlines()[0] if text else "Not signed in.")}
# ---------------------------------------------------------------- skills
def skills_dir(tool):
    """Where the CLI reads the operator's personal skills."""
    if _tool(tool)=="claude_code":
        base=os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(_home(),".claude")
        return os.path.join(base,"skills")
    return os.path.join(_home(),".agents","skills")  # Codex: user skills in $HOME/.agents/skills (OpenAI Codex "Build skills")
def _remove_installed_skills(dest_root,names):
    """Remove the LOYA skills this connection installed - only copies still exactly as LOYA wrote them."""
    ext=_ext();removed=[]
    for s in ext.bundled_skill_sources():
        if s["name"] not in names and s["dir"] not in names:continue
        d=os.path.join(dest_root,s["dir"]);p=os.path.join(d,"SKILL.md");mp=os.path.join(d,ext.SKILL_MANIFEST)
        try:
            with open(mp,"r",encoding="utf-8") as f:man=json.load(f)
            with open(p,"rb") as f:cur=ext._sha(f.read())
        except Exception:continue
        if man.get("sha256")!=cur or not str(man.get("source") or "").startswith("LOYA"):continue
        try:
            os.remove(p);os.remove(mp)
            if not os.listdir(d):os.rmdir(d)
            removed.append(s["name"])
        except OSError:pass
    return removed
# ---------------------------------------------------------------- the bridge command
def _app_root():return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),"..",".."))
def bridge_script():return os.path.join(_app_root(),"Cores","Bridge","mcp_cli_bridge.py")
def bridge_python():
    if getattr(sys,"frozen",False):raise ConnectionError_("A packaged build has no Python interpreter for the bridge. Run LOYA NG from source to connect a CLI.")
    exe=sys.executable or ""
    if _IS_WINDOWS and os.path.basename(exe).lower()=="pythonw.exe":
        cand=os.path.join(os.path.dirname(exe),"python.exe")  # stdio needs a console interpreter
        if os.path.isfile(cand):exe=cand
    if not exe or not os.path.isfile(exe):raise ConnectionError_("Could not find LOYA NG's Python interpreter.")
    return exe
def bridge_argv(tool):
    return [bridge_python(),"-I",bridge_script(),"--client",tool,"--token-file",connection_file(tool)]
def add_argv(tool,cli):
    cmd=bridge_argv(tool)
    if tool=="claude_code":return [cli,"mcp","add","--scope","user","--transport","stdio",SERVER_NAME,"--"]+cmd
    return [cli,"mcp","add",SERVER_NAME,"--"]+cmd
def remove_argv(tool,cli):
    if tool=="claude_code":return [cli,"mcp","remove","--scope","user",SERVER_NAME]
    return [cli,"mcp","remove",SERVER_NAME]
def get_argv(tool,cli):
    if tool=="claude_code":return [cli,"mcp","get",SERVER_NAME]
    return [cli,"mcp","get",SERVER_NAME,"--json"]
# ---------------------------------------------------------------- MCP server
def _mcp():
    from Cores.Services import mcp_local_service as m
    return m
def ensure_server():
    """Start LOYA's MCP server (without making it the chat provider) when it is not running. Returns its port."""
    m=_mcp()
    if not m.is_running():m.start_server(None,register_provider=False)
    return m.status()["port"]
def autostart():
    """At app start: a connected CLI needs the server, so start it in the background (it refuses every call while locked)."""
    if not any(_read_conn(t) for t in TOOLS):return False
    def run():
        try:
            ensure_server()
            for t in TOOLS:  # the server may be on another port than last time (8765 busy): point the bridges at it
                c=_read_conn(t)
                if c:_sync_port(t,c)
        except Exception as e:_audit("ext_connection",f"MCP server autostart failed: {e}",False)
    threading.Thread(target=run,name="loya-cli-mcp-autostart",daemon=True).start()
    return True
def _sync_port(tool,conn):
    """The server may have been started on another port since: keep the bridge's file pointing at it (same token)."""
    try:
        st=_mcp().status()
        if st.get("running") and st.get("port") and st["port"]!=conn.get("port"):
            conn["port"]=st["port"];_write_conn(tool,conn)
    except Exception:pass
# ---------------------------------------------------------------- public API
def status(tool):
    tool=_tool(tool)
    info=TOOL_INFO[tool]
    path,how=find_cli(tool)
    conn=_read_conn(tool)
    if conn:_sync_port(tool,conn)
    out={"tool":tool,"label":info["label"],"vendor":info["vendor"],"installed":bool(path),"path":path or "","found_in":how,
         "version":cli_version(path) if path else "","docs":info["docs"],"install_methods":[] if path else install_methods(tool),
         "connected":bool(conn),"connected_at":(conn or {}).get("connected_at",""),"skills_dir":skills_dir(tool),
         "skills":(conn or {}).get("skills",[]),"server_name":SERVER_NAME}
    out["signin"]=signin_status(tool,path) if path else {"state":"unknown","detail":"Not installed."}
    if path:
        largs=login_args(tool,path)
        out["login_command"]=" ".join([info["exe"]]+largs)+("" if largs else "   (then type /login)")
    try:out["server"]=_mcp().status()
    except Exception:out["server"]={"running":False}
    return out
def overview():
    return {"tools":{t:status(t) for t in TOOLS},"platform":"windows" if _IS_WINDOWS else "linux"}
def connect(tool):
    tool=_tool(tool)
    label=TOOL_INFO[tool]["label"]
    cli,_how=find_cli(tool)
    if not cli:raise ConnectionError_(f"{label} was not found. Install it first, then try again.")
    bridge_python()
    try:port=ensure_server()
    except Exception as e:
        _audit("ext_connection",f"{label}: LOYA NG's MCP server did not start: {e}",False)
        raise ConnectionError_(f"LOYA NG's MCP server did not start, so {label} was not connected: {e}")
    job=_current_job()
    if job is not None and job.cancelled:raise Cancelled()
    prev=_read_conn(tool)
    _write_conn(tool,{"tool":tool,"token":secrets.token_urlsafe(32),"port":port,"connected_at":_now_iso(),"cli_path":cli,"skills":(prev or {}).get("skills",[])})
    try:
        _run(remove_argv(tool,cli))  # an older registration (e.g. another LOYA folder) is replaced
        rc,out,err=_run(add_argv(tool,cli))
    except Cancelled:
        # Stopped half way: put the connection file back the way it was (the CLI may or may not have the new entry;
        # its bridge then reads the old token, or none, so nothing new is reachable).
        if prev:_write_conn(tool,prev)
        else:_delete_conn(tool)
        _audit("ext_connection",f"{label}: Connect cancelled by the operator",False)
        raise
    if rc!=0:
        if prev:_write_conn(tool,prev)
        else:_delete_conn(tool)
        msg=_clean(err or out,300) or f"exit code {rc}"
        _audit("ext_connection",f"{label}: registering LOYA NG's MCP server failed: {msg}",False)
        raise ConnectionError_(f"{label} could not add LOYA NG's MCP server: {msg}")
    dest=skills_dir(tool)
    try:res=_ext().install_bundled_skills(dest)
    except Exception as e:res={};_audit("ext_connection",f"{label}: installing LOYA skills failed: {e}",False)
    conn=_read_conn(tool) or {}
    conn["skills"]=sorted(k for k,v in res.items() if v in ("installed","updated","current"))
    _write_conn(tool,conn)
    kept=[k for k,v in res.items() if v=="kept_user_copy"]
    _audit("ext_connection",f"{label} connected to LOYA NG's MCP server as '{SERVER_NAME}' (user scope); skills in {dest}: "+", ".join(f"{k} {v}" for k,v in sorted(res.items())),True)
    out=status(tool)
    out["message"]=f"{label} is connected. Start it (or run /mcp in it) to pick up LOYA NG's tools."+(f" Kept your edited copy of: {', '.join(kept)}." if kept else "")
    return out
def disconnect(tool):
    tool=_tool(tool)
    label=TOOL_INFO[tool]["label"]
    conn=_read_conn(tool) or {}
    cli,_how=find_cli(tool)
    note=""
    if cli:
        rc,out,err=_run(remove_argv(tool,cli))
        if rc!=0 and not re.search(r"not found|no .*server|does not exist|no mcp server",(out+err),re.I):note=" The CLI did not confirm the removal: "+_clean(err or out,200)
    else:note=f" {label} was not found, so remove '{SERVER_NAME}' from its MCP servers yourself if it is still listed."
    _delete_conn(tool)  # revokes the token at once, whatever the CLI did
    removed=_remove_installed_skills(skills_dir(tool),conn.get("skills") or [])
    _audit("ext_connection",f"{label} disconnected; removed skills: {', '.join(removed) or 'none'}",True)
    out=status(tool)
    out["message"]=f"{label} is disconnected."+note
    return out
def test_connection(tool):
    """Checks the whole path the CLI uses: registration in the CLI, the server, and a real initialize + tools/list
    through the bridge with the connection's token."""
    tool=_tool(tool)
    label=TOOL_INFO[tool]["label"]
    steps=[]
    cli,_how=find_cli(tool)
    steps.append({"name":"CLI found","ok":bool(cli),"detail":cli or "not found"})
    conn=_read_conn(tool)
    steps.append({"name":"Connected in LOYA NG","ok":bool(conn),"detail":"connection token present" if conn else "not connected"})
    if cli:
        rc,out,err=_run(get_argv(tool,cli))
        steps.append({"name":f"Registered in {label}","ok":rc==0,"detail":f"'{SERVER_NAME}' found" if rc==0 else _clean(err or out,160) or f"exit code {rc}"})
    running=False
    try:running=_mcp().is_running()
    except Exception:pass
    steps.append({"name":"LOYA NG MCP server","ok":running,"detail":"running" if running else "not running"})
    if conn and running:
        _sync_port(tool,conn)
        rc,sout,serr=_run(bridge_argv(tool)+["--selftest"],timeout=60)
        try:res=json.loads((sout or "{}").strip().splitlines()[-1])
        except Exception:res={"ok":False,"error":"timed out" if rc==124 else (_clean(serr,200) or f"exit code {rc}")}
        steps.append({"name":"Bridge to LOYA NG","ok":bool(res.get("ok")),"detail":f"{res.get('tools')} tools offered" if res.get("ok") else _clean(res.get("error"),200)})
    ok=all(s["ok"] for s in steps)
    _audit("ext_connection",f"{label} connection test: "+("passed" if ok else "failed - "+"; ".join(s["name"] for s in steps if not s["ok"])),ok)
    return {"ok":ok,"steps":steps,"message":(f"{label} can reach LOYA NG. Its calls go through AI Roles." if ok else "Not working yet: "+"; ".join(f"{s['name']} ({s['detail']})" for s in steps if not s["ok"]))}
# ---------------------------------------------------------------- sign in (the CLI's own flow, in a terminal)
def _ps_quote(s):return "'"+str(s).replace("'","''")+"'"
def sign_in_command(tool,shell_id="shell"):
    """The line to type in a LOYA terminal of that shell, or "" when that shell cannot run the CLI (a WSL shell on Windows)."""
    tool=_tool(tool)
    cli,_how=find_cli(tool)
    if not cli:raise ConnectionError_(f"{TOOL_INFO[tool]['label']} was not found. Install it first.")
    args=login_args(tool,cli)
    sid=str(shell_id or "")
    if sid.startswith("wsl:"):return ""
    if sid in ("pwsh","powershell"):return " ".join(["&",_ps_quote(cli)]+args)
    if sid=="cmd":return " ".join(['"'+cli+'"']+args)
    return " ".join(shlex.quote(x) for x in [cli]+args)
_LINUX_TERMINALS=(("x-terminal-emulator",["-e"]),("qterminal",["-e"]),("gnome-terminal",["--"]),("konsole",["-e"]),("xfce4-terminal",["-x"]),
                  ("mate-terminal",["-x"]),("tilix",["-e"]),("alacritty",["-e"]),("kitty",[]),("xterm",["-e"]))
def sign_in_os_terminal(tool):
    """Open the OS terminal running the CLI's own sign-in command. The operator completes the vendor's flow there."""
    tool=_tool(tool)
    info=TOOL_INFO[tool]
    cli,_how=find_cli(tool)
    if not cli:raise ConnectionError_(f"{info['label']} was not found. Install it first.")
    largs=login_args(tool,cli)
    r=_open_os_terminal(" ".join(shlex.quote(x) for x in [cli]+largs)," ".join(['"'+cli+'"']+largs))
    _audit("ext_connection",f"{info['label']}: opened {r['terminal']} for its own sign-in",True)
    return r
# ---------------------------------------------------------------- install (the vendor's own installer, only after a confirm)
# Every command below is a constant copied from the vendor's install docs (read 2026-11-24). Nothing is built from user
# input, nothing uses sudo or asks for elevation: all of them install for the current user only.
#   Claude Code: https://code.claude.com/docs/en/setup ("Native Install (Recommended)", WinGet, "Install with npm": Node.js 22+,
#                "Do NOT use sudo npm install -g")
#   Codex CLI:   https://github.com/openai/codex (README "Installing and running Codex CLI") and
#                https://developers.openai.com/codex/cli (Quickstart "Install Codex")
# "lines" gives the line to type per shell family: posix (bash/zsh/sh/fish on Linux), ps (PowerShell 5/7), cmd (Windows cmd).
NODE_URL="https://nodejs.org/en/download"
INSTALL_METHODS={
    "claude_code":{
        "linux":[
            {"id":"native","label":"Native installer (recommended)","source":"https://claude.ai/install.sh","docs":"https://code.claude.com/docs/en/setup",
             "lines":{"posix":"curl -fsSL https://claude.ai/install.sh | bash"},"requires":["curl","bash"],"auto":True,
             "note":"Installs to ~/.local/bin/claude for your user and keeps itself updated. No sudo."},
            {"id":"npm","label":"npm (Node.js 22 or later)","source":"https://www.npmjs.com/package/@anthropic-ai/claude-code","docs":"https://code.claude.com/docs/en/setup#install-with-npm",
             "lines":{"posix":"npm install -g @anthropic-ai/claude-code@latest"},"requires":["npm"],"node_min":22,"auto":True,"npm_global":True,
             "note":"Never with sudo: if npm's global folder is not yours, use the native installer."},
        ],
        "windows":[
            {"id":"native","label":"Native installer, PowerShell (recommended)","source":"https://claude.ai/install.ps1","docs":"https://code.claude.com/docs/en/setup",
             "lines":{"ps":"irm https://claude.ai/install.ps1 | iex","cmd":"curl -fsSL https://claude.ai/install.cmd -o install.cmd && install.cmd && del install.cmd"},
             "requires":["powershell"],"auto":True,
             "note":"Installs to %USERPROFILE%\\.local\\bin\\claude.exe for your user. No Administrator needed."},
            {"id":"winget","label":"WinGet","source":"https://winget.run/pkg/Anthropic/ClaudeCode","docs":"https://code.claude.com/docs/en/setup",
             "lines":{"ps":"winget install Anthropic.ClaudeCode","cmd":"winget install Anthropic.ClaudeCode"},"requires":["winget"],"auto":False,
             "note":"Does not update itself: run winget upgrade Anthropic.ClaudeCode now and then."},
            {"id":"npm","label":"npm (Node.js 22 or later)","source":"https://www.npmjs.com/package/@anthropic-ai/claude-code","docs":"https://code.claude.com/docs/en/setup#install-with-npm",
             "lines":{"ps":"npm install -g @anthropic-ai/claude-code@latest","cmd":"npm install -g @anthropic-ai/claude-code@latest"},"requires":["npm"],"node_min":22,"auto":True,
             "note":"Installs into %APPDATA%\\npm for your user."},
        ],
    },
    "codex_cli":{
        "linux":[
            {"id":"native","label":"Install script (recommended)","source":"https://chatgpt.com/codex/install.sh","docs":"https://developers.openai.com/codex/cli",
             "lines":{"posix":"curl -fsSL https://chatgpt.com/codex/install.sh | sh"},"requires":["curl","sh"],"auto":True,
             "note":"OpenAI's standalone installer, for your user. No sudo."},
            {"id":"npm","label":"npm","source":"https://www.npmjs.com/package/@openai/codex","docs":"https://github.com/openai/codex",
             "lines":{"posix":"npm install -g @openai/codex"},"requires":["npm"],"auto":True,"npm_global":True,
             "note":"Never with sudo: if npm's global folder is not yours, use the install script."},
        ],
        "windows":[
            {"id":"native","label":"Install script, PowerShell (recommended)","source":"https://chatgpt.com/codex/install.ps1","docs":"https://github.com/openai/codex",
             "lines":{"ps":'powershell -ExecutionPolicy ByPass -c "irm https://chatgpt.com/codex/install.ps1 | iex"',"cmd":'powershell -ExecutionPolicy ByPass -c "irm https://chatgpt.com/codex/install.ps1 | iex"'},
             "requires":["powershell"],"auto":True,
             "note":"OpenAI's standalone installer, for your user. The ExecutionPolicy bypass applies to this one command only."},
            {"id":"npm","label":"npm","source":"https://www.npmjs.com/package/@openai/codex","docs":"https://github.com/openai/codex",
             "lines":{"ps":"npm install -g @openai/codex","cmd":"npm install -g @openai/codex"},"requires":["npm"],"auto":True,
             "note":"Installs into %APPDATA%\\npm for your user."},
        ],
    },
}
_PREREQ_HELP={"npm":("Node.js and npm",NODE_URL),"node":("Node.js",NODE_URL),"curl":("curl (install it with your distribution's package manager)","https://curl.se/download.html"),
              "bash":("bash","https://www.gnu.org/software/bash/"),"sh":("a POSIX sh","https://pubs.opengroup.org/onlinepubs/9699919799/utilities/sh.html"),
              "powershell":("Windows PowerShell","https://learn.microsoft.com/powershell/scripting/install/installing-powershell-on-windows"),
              "winget":("WinGet (App Installer)","https://learn.microsoft.com/windows/package-manager/winget/")}
def _platform():return "windows" if _IS_WINDOWS else "linux"
def _which(name):
    if name=="powershell" and _IS_WINDOWS:return shutil.which("powershell.exe") or shutil.which("pwsh.exe")
    return shutil.which(name)
def _node_major():
    node=shutil.which("node")
    if not node:return None
    rc,out,err=_run([node,"--version"],timeout=10)
    m=re.match(r"v?(\d+)",(out or err).strip())
    return int(m.group(1)) if rc==0 and m else None
def _npm_global_writable():
    """True when `npm install -g` would not need root (prefix folder owned by / writable for this user)."""
    if _IS_WINDOWS:return True
    npm=shutil.which("npm")
    if not npm:return False
    rc,out,_err=_run([npm,"config","get","prefix"],timeout=15)
    prefix=(out or "").strip().splitlines()[0] if rc==0 and out.strip() else ""
    if not prefix:return False
    target=os.path.join(prefix,"lib","node_modules")
    probe=target if os.path.isdir(target) else prefix
    return os.access(probe,os.W_OK)
def install_methods(tool):
    """The vendor's install routes for this OS, with what is missing to use each one."""
    tool=_tool(tool)
    out=[]
    for m in INSTALL_METHODS[tool][_platform()]:
        missing=[]
        for req in m["requires"]:
            if not _which(req):missing.append(req)
        node_note=""
        if "npm" in m["requires"] and "npm" not in missing:
            major=_node_major()
            if major is None:missing.append("node")
            elif m.get("node_min") and major<m["node_min"]:node_note=f"Node.js {major} found; {m['node_min']} or later is required."
        if m.get("npm_global") and not missing and not _npm_global_writable():
            node_note=(node_note+" " if node_note else "")+"npm's global folder needs root here, and LOYA NG never uses sudo: use the recommended installer, or set a user npm prefix."
        help_=[{"name":_PREREQ_HELP.get(x,(x,""))[0],"url":_PREREQ_HELP.get(x,("",""))[1]} for x in missing]
        ready=not missing and not node_note
        out.append({"id":m["id"],"label":m["label"],"source":m["source"],"docs":m["docs"],"note":m["note"],
                    "commands":dict(m["lines"]),"missing":help_,"problem":node_note,"available":ready,"auto":bool(m["auto"]) and ready})
    return out
def _method(tool,method_id):
    for m in INSTALL_METHODS[_tool(tool)][_platform()]:
        if m["id"]==method_id:return m
    raise ConnectionError_("Unknown install method.")
def _shell_family(shell_id):
    sid=str(shell_id or "")
    if sid in ("pwsh","powershell"):return "ps"
    if sid=="cmd":return "cmd"
    if sid.startswith("wsl:"):return ""
    return "cmd" if _IS_WINDOWS else "posix"
def _line_for(m,family):
    lines=m["lines"]
    if family in lines:return lines[family]
    return ""
# One-time confirm tokens: plan() hands one out with the exact command; a run needs it (the UI asks the operator first).
_confirm={}
_confirm_lock=threading.Lock()
CONFIRM_TTL=300
def install_plan(tool,method_id,shell_id=""):
    """What "Install for me" would run, for the confirm dialog: the exact command, its official source and a token that
    the run must present. Nothing is run here."""
    tool=_tool(tool)
    m=_method(tool,method_id)
    if find_cli(tool)[0]:raise ConnectionError_(f"{TOOL_INFO[tool]['label']} is already installed.")
    st=[x for x in install_methods(tool) if x["id"]==method_id][0]
    if not st["auto"]:
        why=st["problem"] or ("Missing: "+", ".join(x["name"] for x in st["missing"]) if st["missing"] else "Run this one yourself.")
        raise ConnectionError_(why)
    family=_shell_family(shell_id) if shell_id else ("cmd" if _IS_WINDOWS else "posix")
    line=_line_for(m,family)
    os_line=_line_for(m,"cmd" if _IS_WINDOWS else "posix")
    token=secrets.token_urlsafe(18)
    import time as _t
    with _confirm_lock:
        for k in [k for k,v in _confirm.items() if v["exp"]<_t.time()]:_confirm.pop(k,None)
        _confirm[token]={"tool":tool,"method":method_id,"exp":_t.time()+CONFIRM_TTL}
    return {"tool":tool,"method":method_id,"label":m["label"],"command":line,"os_command":os_line,"use_loya_terminal":bool(line),
            "source":m["source"],"docs":m["docs"],"note":m["note"],"token":token,
            "warning":f"This downloads and runs {TOOL_INFO[tool]['vendor']}'s official installer with your user's permissions. LOYA NG does not use sudo or Administrator rights."}
def _take_confirm(tool,method_id,token):
    import time as _t
    with _confirm_lock:
        rec=_confirm.pop(str(token or ""),None)
    if not rec or rec["tool"]!=tool or rec["method"]!=method_id or rec["exp"]<_t.time():
        raise ConnectionError_("Confirm the install first (the command is shown before anything runs).")
def install_command(tool,method_id,shell_id,token):
    """The line for a LOYA terminal tab, after the operator confirmed it (single-use token)."""
    tool=_tool(tool)
    m=_method(tool,method_id)
    family=_shell_family(shell_id)
    line=_line_for(m,family)
    if not line:raise ConnectionError_("That terminal cannot run this installer.")
    _take_confirm(tool,method_id,token)
    _audit("ext_connection",f"{TOOL_INFO[tool]['label']}: install confirmed by the operator, running in a LOYA NG terminal: {line}",True)
    return line
def install_os_terminal(tool,method_id,token):
    """Run the confirmed install command in the OS terminal (when LOYA's Terminal extension is off)."""
    tool=_tool(tool)
    m=_method(tool,method_id)
    _take_confirm(tool,method_id,token)
    if _IS_WINDOWS:
        line=_line_for(m,"cmd")
        r=_open_os_terminal(None,line)
    else:
        line=_line_for(m,"posix")
        r=_open_os_terminal(line,None)
    _audit("ext_connection",f"{TOOL_INFO[tool]['label']}: install confirmed by the operator, running in {r['terminal']}: {line}",True)
    return r
def detect(tool):
    """Cheap re-check for the card after an install (no sign-in or version calls)."""
    path,how=find_cli(_tool(tool))
    return {"tool":tool,"installed":bool(path),"path":path or "","found_in":how}
def _open_os_terminal(posix_script,cmd_line):
    """Open the OS terminal running one command; the window stays open until Enter. Returns {"opened","terminal"}."""
    if _IS_WINDOWS:
        subprocess.Popen('cmd.exe /k "'+cmd_line+'"',env=_cli_env(),creationflags=0x00000010)  # CREATE_NEW_CONSOLE
        return {"opened":True,"terminal":"cmd.exe"}
    script=posix_script+"; printf '\\nPress Enter to close. '; read _"
    for name,flag in _LINUX_TERMINALS:
        term=shutil.which(name)
        if not term:continue
        try:
            subprocess.Popen([term]+flag+["sh","-c",script],env=_cli_env(),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
            return {"opened":True,"terminal":name}
        except OSError:continue
    raise ConnectionError_("No terminal program was found. Run this yourself in a terminal: "+posix_script)
def connect_preview(tool):
    """The exact `mcp add` command Connect runs, for the setup assistant's approval step."""
    tool=_tool(tool)
    cli,_how=find_cli(tool)
    if not cli:raise ConnectionError_(f"{TOOL_INFO[tool]['label']} was not found. Install it first.")
    argv=add_argv(tool,cli)
    shown=[TOOL_INFO[tool]["exe"]]+argv[1:]
    text=subprocess.list2cmdline(shown) if _IS_WINDOWS else " ".join(shlex.quote(x) for x in shown)
    return {"command":text,"skills_dir":skills_dir(tool),"skills":[s["name"] for s in _ext().bundled_skill_sources()],"server_name":SERVER_NAME}
# ---------------------------------------------------------------- background jobs (the UI never waits on a CLI in a bridge call)
# Every step of the Connections card and the setup assistant that runs the CLI or starts the MCP server is a job: the
# bridge call that starts it returns at once, the UI polls it (short calls) and shows it running, and Cancel stops it.
JOB_KINDS={"overview":None,"status":status,"detect":detect,"connect":connect,"disconnect":disconnect,"test":test_connection,"preview":connect_preview}
JOB_KEEP=600
_jobs={}
_jobs_lock=threading.Lock()
class _Job:
    def __init__(self,kind,tool):
        self.id=uuid.uuid4().hex[:16];self.kind=kind;self.tool=tool;self.started=time.monotonic();self.ended=None
        self.done=False;self.cancelled=False;self.result=None;self.error="";self.procs=set()
_WRITES=("connect","disconnect")
def _job_body(job,before=()):
    for b in before:
        deadline=time.monotonic()+10
        while not b.done and time.monotonic()<deadline:time.sleep(0.05)
    _job_local.job=job
    try:
        out=overview() if job.kind=="overview" else JOB_KINDS[job.kind](job.tool)
        if not job.cancelled:job.result=out
    except Cancelled:
        job.cancelled=True
    except ConnectionError_ as e:
        job.error=str(e)
    except Exception as e:
        job.error=f"{type(e).__name__}: {e}"
        _audit("ext_connection",f"{job.kind} failed: {job.error}",False)
    finally:
        _job_local.job=None
        job.ended=time.monotonic();job.done=True
def job_start(kind,tool=None):
    """Start a connection step in the background. Returns {"job": id} at once."""
    kind=str(kind or "")
    if kind not in JOB_KINDS:raise ConnectionError_(f"Unknown step: {kind}")
    tool=None if kind=="overview" else _tool(tool)
    job=_Job(kind,tool)
    now=time.monotonic()
    with _jobs_lock:
        for k in [k for k,j in _jobs.items() if j.done and now-(j.ended or now)>JOB_KEEP]:_jobs.pop(k,None)
        # A step started right after a cancelled Connect / Disconnect waits until that one has put the connection file back,
        # so it never reads (or overwrites) a half-done state. Two writes on one tool never overlap.
        before=[j for j in _jobs.values() if j.kind in _WRITES and not j.done and (tool is None or j.tool==tool) and (j.cancelled or kind in _WRITES)]
        _jobs[job.id]=job
    threading.Thread(target=_job_body,args=(job,before),name=f"loya-conn-{kind}",daemon=True).start()
    return {"job":job.id}
def _get_job(job_id):
    with _jobs_lock:j=_jobs.get(str(job_id or ""))
    if j is None:raise ConnectionError_("That step is no longer running. Open the assistant again.")
    return j
def job_poll(job_id):
    """{"done": False, "elapsed"} while it runs; then {"done": True} with "result", "error" or "cancelled"."""
    j=_get_job(job_id)
    el=round((j.ended or time.monotonic())-j.started,1)
    if j.cancelled:return {"done":True,"cancelled":True,"elapsed":el}
    if not j.done:return {"done":False,"elapsed":el}
    if j.error:return {"done":True,"ok":False,"error":j.error,"elapsed":el}
    return {"done":True,"ok":True,"result":j.result,"elapsed":el}
def job_cancel(job_id):
    """Stop waiting for a step: its CLI (and anything that CLI started) is stopped at once."""
    j=_get_job(job_id)
    if j.done and not j.cancelled:return {"cancelled":False,"done":True}
    j.cancelled=True  # the job's _run() sees this within 0.1 s and stops its CLI; this call itself never waits
    return {"cancelled":True}
