"""Chain diagrams ("flows"): run a user script node (Python, Bash or PowerShell) as a separate process.
The script is written to a throw-away work directory and started with an argv list (never through a shell), an environment
built from scratch (nothing secret is inherited), the node input as JSON on stdin and in a file, a timeout, an output cap
and a kill of the whole process tree on timeout / cancel. On Linux the process is additionally wrapped in bubblewrap when
that works on this machine (best effort: the app's data directories are hidden, the rest of the system is read-only)."""
import json,os,re,shutil,signal,subprocess,sys,tempfile,threading,time
LANGUAGES=("python","bash","powershell")
_IS_WINDOWS=os.name=="nt"
_FILE_NAMES={"python":"script.py","bash":"script.sh","powershell":"script.ps1"}
_INPUT_ENV_LIMIT=32768
_INPUT_ENV_LIMIT_WINDOWS=24000    # one Windows environment variable holds at most 32767 characters
_BRANCH_RE=re.compile(r"^[A-Za-z0-9_-]{1,24}$")
_VAR_RE=re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,39}$")
_WINDOWS_ENV_KEEP=("SYSTEMROOT","COMSPEC","PATHEXT","WINDIR","SYSTEMDRIVE","PROGRAMFILES","PROGRAMFILES(X86)","PROGRAMDATA",
                   "NUMBER_OF_PROCESSORS","PROCESSOR_ARCHITECTURE","OS")
TMP_ROOT=None    # where work directories are made; None = the system temp directory (tests point this at their own folder)
def _tmp_root(tmp_root=None):
    for root in(tmp_root,TMP_ROOT):
        if root and os.path.isdir(root):return root
    return None
def _remove_tree(path,wait=3.0):
    """Delete a work directory for good: read-only entries are made writable and retried, and because a process that was
    just killed can still be writing for a moment, the removal is repeated until the directory is gone. -> bool."""
    def retry(function,target,_error):
        try:
            for item in(os.path.dirname(target),target):
                if not os.path.islink(item):os.chmod(item,0o700)   # never through a link the script may have planted
            function(target)
        except OSError:pass
    handler={"onexc":retry} if sys.version_info>=(3,12) else {"onerror":retry}
    deadline=time.monotonic()+max(0.0,wait)
    while True:
        try:shutil.rmtree(path,**handler)
        except OSError:pass
        if not os.path.lexists(path):return True
        if time.monotonic()>=deadline:return False
        time.sleep(0.05)
# ---------------------------------------------------------------- interpreters
def _find_bash(windows,which):
    if windows:
        found=which("bash")
        # System32\bash.exe is the WSL launcher: it cannot run a script given as a Windows path.
        if found and "system32" not in found.lower().replace("/","\\").split("\\"):return found
        return None
    return which("bash") or which("sh")
def _find_powershell(windows,which):
    if windows:return which("pwsh") or which("powershell")
    return which("pwsh")
def script_argv(language,path,windows=None,which=None):
    """The argv list that runs a script file, or None when the interpreter is missing."""
    windows=_IS_WINDOWS if windows is None else bool(windows)
    which=which or shutil.which
    if language=="python":
        if not sys.executable or getattr(sys,"frozen",False):return None
        return [sys.executable,"-I","-X","utf8","-B",path]
    if language=="bash":
        shell=_find_bash(windows,which)
        if not shell:return None
        return [shell,"--noprofile","--norc",path] if re.split(r"[\\/]",shell)[-1].lower().split(".")[0]=="bash" else [shell,path]
    if language=="powershell":
        shell=_find_powershell(windows,which)
        return [shell,"-NoLogo","-NoProfile","-NonInteractive","-ExecutionPolicy","Bypass","-File",path] if shell else None
    return None
def available_languages():
    return {language:script_argv(language,"x") is not None for language in LANGUAGES}
def build_env(workdir,payload_json,windows=None,environ=None):
    """The complete environment of a script: a few machine facts plus the LOYA_* inputs. Nothing else is inherited."""
    windows=_IS_WINDOWS if windows is None else bool(windows)
    environ=os.environ if environ is None else environ
    env={"PATH":environ.get("PATH") or os.defpath,"HOME":workdir,"TMP":workdir,"TEMP":workdir,
         "LOYA_FLOW":"1","LOYA_INPUT_FILE":os.path.join(workdir,"input.json")}
    if windows:
        upper={str(key).upper():value for key,value in environ.items()}
        for name in _WINDOWS_ENV_KEEP:
            if upper.get(name):env[name]=upper[name]
        env.update({"USERPROFILE":workdir,"APPDATA":workdir,"LOCALAPPDATA":workdir})
    else:
        env["TMPDIR"]=workdir
        locale=environ.get("LC_ALL") or environ.get("LANG") or "C.UTF-8"
        env["LANG"]=environ.get("LANG") or locale
        env["LC_ALL"]=locale
    if len(payload_json)<=(_INPUT_ENV_LIMIT_WINDOWS if windows else _INPUT_ENV_LIMIT):env["LOYA_INPUT"]=payload_json
    return env
# ---------------------------------------------------------------- process tree
def taskkill_argv(pid):
    return ["taskkill","/T","/F","/PID",str(int(pid))]
def kill_tree(proc,grace=0.5):
    """Stop a process and everything it started. POSIX: SIGTERM then SIGKILL to its process group (when it leads one of its
    own); Windows: taskkill /T /F."""
    if proc is None:return
    try:
        if proc.poll() is not None and _IS_WINDOWS:return
    except Exception:return
    if _IS_WINDOWS:
        try:subprocess.run(taskkill_argv(proc.pid),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                           timeout=10,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        except Exception:pass
        try:
            if proc.poll() is None:proc.kill()
        except Exception:pass
        return
    group=None
    try:
        group=os.getpgid(proc.pid)
        if group!=proc.pid or group==os.getpgrp():group=None   # never signal our own group
    except (OSError,AttributeError):
        group=proc.pid if proc.poll() is not None and getattr(proc,"_loya_own_group",False) else None
    def send(sig):
        try:
            if group is not None:os.killpg(group,sig)
            elif proc.poll() is None:proc.send_signal(sig)
        except (OSError,ValueError):pass
    send(signal.SIGTERM)
    deadline=time.monotonic()+max(0.0,grace)
    while time.monotonic()<deadline:
        if proc.poll() is not None:break
        time.sleep(0.02)
    send(signal.SIGKILL)
# ---------------------------------------------------------------- bubblewrap (Linux, best effort)
_bwrap_lock=threading.Lock()
_bwrap_state={"checked":False,"path":None,"net":False}
_HOME_SECRET_DIRS=(".ssh",".aws",".gnupg",".config",".claude",".codex",".kube",".docker",".azure",".gcloud",".password-store",".mozilla",".local/share/keyrings")
_HOME_SECRET_FILES=(".netrc",".git-credentials",".pgpass",".my.cnf",".npmrc",".pypirc",".claude.json",".boto",".s3cfg",".vault-token",
                    ".bash_history",".zsh_history",".python_history",".psql_history",".mysql_history",".lesshst",".Xauthority")
def _hidden_dirs():
    """Directories a script must not see: the app's data, logs and backups."""
    found=[]
    try:
        from Cores import common_db
        data=os.path.realpath(common_db.data_dir())
        roots={os.path.dirname(data),os.path.dirname(os.path.dirname(os.path.realpath(common_db.__file__)))}
        candidates=[data]+[os.path.join(root,name) for root in sorted(roots) for name in("Data","Logs","Backups")]
    except Exception:candidates=[]
    for path in candidates:
        if path not in found and os.path.isdir(path) and path not in("/",os.path.realpath(tempfile.gettempdir())):found.append(path)
    return found
def _home_secrets():
    """(directories, files) in the user's home that hold credentials and exist on this machine."""
    try:home=os.path.realpath(os.path.expanduser("~"))
    except Exception:return [],[]
    if not home or home in("/","~") or not os.path.isdir(home):return [],[]
    dirs=[];files=[]
    for name in _HOME_SECRET_DIRS:
        path=os.path.realpath(os.path.join(home,name))
        if os.path.isdir(path) and path not in dirs and path not in("/",home):dirs.append(path)
    for name in _HOME_SECRET_FILES:
        path=os.path.realpath(os.path.join(home,name))
        if os.path.isfile(path) and path not in files:files.append(path)
    return dirs,files
def _hidden_paths(workdir,argv):
    """(directories to cover with an empty tmpfs, files to replace with /dev/null) for one sandboxed run. Anything the run
    itself lives in (the work directory, the interpreter) is never covered."""
    home_dirs,home_files=_home_secrets()
    keep=[os.path.realpath(p) for p in [workdir,sys.executable,sys.prefix,getattr(sys,"base_prefix",sys.prefix)]+[a for a in list(argv)[:1] if os.path.isabs(str(a))] if p]
    def clear(path):
        return not any(k==path or k.startswith(path.rstrip(os.sep)+os.sep) for k in keep)
    dirs=[]
    for path in _hidden_dirs()+home_dirs:
        if path not in dirs and clear(path):dirs.append(path)
    return dirs,[path for path in home_files if clear(path) and not any(path.startswith(d+os.sep) for d in dirs)]
def bwrap_argv(bwrap,workdir,hidden,argv,network=False,hidden_files=()):
    """bubblewrap command line: read-only system, empty tmpfs over `hidden` directories, /dev/null over `hidden_files`,
    writable work directory, own PID namespace, and no network unless network=True."""
    wrapped=[bwrap,"--ro-bind","/","/","--dev","/dev","--proc","/proc"]
    for path in hidden:wrapped+=["--tmpfs",path]
    for path in hidden_files:wrapped+=["--ro-bind","/dev/null",path]
    wrapped+=["--bind",workdir,workdir,"--chdir",workdir,"--unshare-pid"]
    if not network:wrapped.append("--unshare-net")
    return wrapped+["--die-with-parent","--new-session","--"]+list(argv)
def _bwrap_probe():
    """(path of a bubblewrap that works here or None, can it also cut the network). Probed once per process."""
    if not sys.platform.startswith("linux") or os.environ.get("LOYA_FLOW_NO_SANDBOX")=="1":return None,False
    with _bwrap_lock:
        if _bwrap_state["checked"]:return _bwrap_state["path"],_bwrap_state["net"]
        path=shutil.which("bwrap");works=False;net=False
        probe=shutil.which("true") or "/bin/true"
        if path:
            scratch=None
            try:
                scratch=tempfile.mkdtemp(prefix="loya-flow-probe-",dir=_tmp_root())
                dirs,files=_hidden_paths(scratch,[probe])
                for network in(False,True):   # first with the network cut; some kernels allow the sandbox but not that
                    try:
                        done=subprocess.run(bwrap_argv(path,scratch,dirs,[probe],network=network,hidden_files=files),stdin=subprocess.DEVNULL,
                                            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=8,env={"PATH":os.environ.get("PATH") or os.defpath})
                    except Exception:continue
                    if done.returncode==0:
                        works=True;net=not network;break
            except Exception:works=False
            finally:
                if scratch:_remove_tree(scratch)
        _bwrap_state.update(checked=True,path=path if works else None,net=bool(works and net))
        return _bwrap_state["path"],_bwrap_state["net"]
def _bwrap_path():
    return _bwrap_probe()[0]
def sandbox_info():
    """What script isolation this machine gives: {"sandbox":"bwrap"|"none","network_isolation":bool}."""
    path,net=_bwrap_probe()
    return {"sandbox":"bwrap" if path else "none","network_isolation":bool(path and net)}
def reset_sandbox_probe():
    with _bwrap_lock:_bwrap_state.update(checked=False,path=None,net=False)
# ---------------------------------------------------------------- result protocol
def parse_result(stdout,branches=None):
    """The script's answer: the last non-empty stdout line that is a JSON object carrying branch / vars / output.
    -> {"branch","vars","output"} or None. With `branches`, a missing answer or branch falls back to the first one."""
    default=branches[0] if isinstance(branches,(list,tuple)) and branches else ""
    found=None
    lines=[line.strip() for line in str(stdout or "").splitlines()[-400:]]
    for line in reversed([line for line in lines if line][-60:]):
        if not(line.startswith("{") and line.endswith("}")):continue
        try:value=json.loads(line)
        except ValueError:continue
        if isinstance(value,dict) and any(key in value for key in("branch","vars","output")):
            found=value;break
    if found is None:return {"branch":default,"vars":{},"output":None} if default else None
    branch=found.get("branch")
    if isinstance(branch,bool):branch="true" if branch else "false"
    branch=str(branch).strip() if isinstance(branch,(str,int)) else ""
    if not _BRANCH_RE.match(branch):branch=default
    variables=found.get("vars") if isinstance(found.get("vars"),dict) else {}
    return {"branch":branch,"vars":{str(k):v for k,v in variables.items() if _VAR_RE.match(str(k))},"output":found.get("output")}
# ---------------------------------------------------------------- runner
class _Reader(threading.Thread):
    """Drains one pipe into memory up to a hard cap; sets `overflow` and stops keeping data beyond it."""
    def __init__(self,stream,cap,overflow):
        super().__init__(daemon=True)
        self.stream=stream;self.cap=cap;self.overflow=overflow;self.chunks=[];self.size=0
    def run(self):
        try:
            while True:
                chunk=self.stream.read1(65536) if hasattr(self.stream,"read1") else self.stream.read(65536)
                if not chunk:break
                room=self.cap-self.size
                if room>0:
                    self.chunks.append(chunk[:room]);self.size+=min(len(chunk),room)
                if len(chunk)>room:self.overflow.set()
        except (OSError,ValueError):pass
    def text(self):
        return b"".join(self.chunks).decode("utf-8","replace")
def _feed(stream,data):
    try:
        stream.write(data);stream.flush()
    except (OSError,ValueError):pass
    finally:
        try:stream.close()
        except (OSError,ValueError):pass
def _result(**values):
    base={"ok":False,"exit_code":None,"stdout":"","stderr":"","timed_out":False,"cancelled":False,"truncated":False,
          "result":None,"error":"","duration_ms":0,"sandbox":"none","network":True}
    base.update(values)
    return base
def _spawn(argv,workdir,env):
    options={"stdin":subprocess.PIPE,"stdout":subprocess.PIPE,"stderr":subprocess.PIPE,"cwd":workdir,"env":env,"shell":False,"close_fds":True}
    if _IS_WINDOWS:options["creationflags"]=getattr(subprocess,"CREATE_NEW_PROCESS_GROUP",0)|getattr(subprocess,"CREATE_NO_WINDOW",0)
    else:options["start_new_session"]=True
    proc=subprocess.Popen(argv,**options)
    proc._loya_own_group=not _IS_WINDOWS
    return proc
def run_script(language,code,payload,timeout=60,max_output=1048576,cancel_event=None,on_start=None,branches=None,sandbox=True,network=False,tmp_root=None):
    """Run a script node. See the module docstring for the model.
    -> {"ok","exit_code","stdout","stderr","timed_out","cancelled","truncated","result":{"branch","vars","output"}|None,
        "error","duration_ms","sandbox":"bwrap"|"none","network":bool}. Never raises.
    network=False cuts the script off from the network when it runs under bubblewrap; the returned "network" says whether the
    script could in fact reach the network (always True when sandbox is "none").
    tmp_root: the folder the work directory is created in (default: TMP_ROOT, else the system temp directory).
    on_start(proc) is called with the Popen right after it starts (so the caller can kill_tree() it).
    branches (optional): the node's configured branches; then `result` is always filled, defaulting to the first branch."""
    started=time.monotonic()
    def finish(**values):
        values["duration_ms"]=int((time.monotonic()-started)*1000)
        return _result(**values)
    if language not in LANGUAGES:return finish(error="Unknown script language %r."%(language,))
    if cancel_event is not None and cancel_event.is_set():return finish(cancelled=True,error="Cancelled.")
    try:timeout=max(1.0,min(float(timeout),7200.0))
    except (TypeError,ValueError):timeout=60.0
    try:max_output=max(1024,min(int(max_output),64*1048576))
    except (TypeError,ValueError):max_output=1048576
    code=str(code or "").replace("\r\n","\n").replace("\r","\n")
    try:payload_json=json.dumps(payload if payload is not None else {},ensure_ascii=True,default=str)
    except (TypeError,ValueError) as exc:return finish(error="The script input could not be written as JSON: %s"%exc)
    workdir=None;proc=None
    try:
        workdir=tempfile.mkdtemp(prefix="loya-flow-",dir=_tmp_root(tmp_root))
        try:os.chmod(workdir,0o700)
        except OSError:pass
        workdir=os.path.realpath(workdir)
        path=os.path.join(workdir,_FILE_NAMES[language])
        # Windows PowerShell 5 reads a script without a BOM in the ANSI code page.
        with open(path,"w",encoding="utf-8-sig" if language=="powershell" else "utf-8",newline="\n") as handle:handle.write(code if code.endswith("\n") else code+"\n")
        with open(os.path.join(workdir,"input.json"),"w",encoding="utf-8",newline="\n") as handle:handle.write(payload_json)
        for name in(path,os.path.join(workdir,"input.json")):
            try:os.chmod(name,0o600)
            except OSError:pass
        argv=script_argv(language,path)
        if argv is None:return finish(error="%s is not installed on this computer."%{"python":"Python","bash":"Bash","powershell":"PowerShell"}[language])
        env=build_env(workdir,payload_json)
        mode="none";online=True
        bwrap,can_isolate=_bwrap_probe() if sandbox else (None,False)
        if bwrap:
            try:
                hidden,hidden_files=_hidden_paths(workdir,argv)
                allow=bool(network) or not can_isolate
                proc=_spawn(bwrap_argv(bwrap,workdir,hidden,argv,network=allow,hidden_files=hidden_files),workdir,env);mode="bwrap";online=allow
            except OSError:proc=None
        if proc is None:
            try:proc=_spawn(argv,workdir,env)
            except OSError as exc:return finish(error="The script could not be started: %s"%exc)
        if on_start is not None:
            try:on_start(proc)
            except Exception:pass
        overflow=threading.Event()
        readers=[_Reader(proc.stdout,max_output,overflow),_Reader(proc.stderr,max_output,overflow)]
        for reader in readers:reader.start()
        threading.Thread(target=_feed,args=(proc.stdin,payload_json.encode("ascii")),daemon=True).start()
        deadline=started+timeout
        timed_out=cancelled=truncated=False
        while proc.poll() is None:
            if overflow.is_set():truncated=True
            elif cancel_event is not None and cancel_event.is_set():cancelled=True
            elif time.monotonic()>=deadline:timed_out=True
            if truncated or cancelled or timed_out:
                kill_tree(proc);break
            time.sleep(0.02)
        try:proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            kill_tree(proc,grace=0)
            try:proc.wait(timeout=5)
            except subprocess.TimeoutExpired:pass
        if not(timed_out or cancelled or truncated):kill_tree(proc,grace=0)   # background children the script left behind
        for reader in readers:reader.join(timeout=3)
        for stream in(proc.stdout,proc.stderr):
            try:stream.close()
            except (OSError,ValueError):pass
        truncated=truncated or overflow.is_set()
        exit_code=proc.returncode
        stdout=readers[0].text();stderr=readers[1].text()
        ok=exit_code==0 and not(timed_out or cancelled or truncated)
        error=""
        if timed_out:error="The script was stopped after %d seconds."%int(timeout)
        elif cancelled:error="Cancelled."
        elif truncated:error="The script printed more than %d KB and was stopped."%(max_output//1024)
        elif exit_code!=0:error="The script ended with exit code %s."%exit_code
        return finish(ok=ok,exit_code=exit_code,stdout=stdout,stderr=stderr,timed_out=timed_out,cancelled=cancelled,truncated=truncated,
                      result=parse_result(stdout,branches) if ok else None,error=error,sandbox=mode,network=online)
    except Exception as exc:
        if proc is not None:kill_tree(proc,grace=0)
        return finish(error="The script could not be run: %s"%exc)
    finally:
        if workdir:_remove_tree(workdir)
# ---------------------------------------------------------------- templates for the editor
_PY_HEADER='''import json, os

# The previous node's result is in the file $LOYA_INPUT_FILE (also sent on stdin):
#   data["input"]  -> {"stdout", "stderr", "exit_code", "parsed", ...}
#   data["vars"]   -> flow variables      data["target"] -> the live target      data["item"] -> for-each item
with open(os.environ["LOYA_INPUT_FILE"], encoding="utf-8") as handle:
    data = json.load(handle)
'''
_PY_ALIVE=_PY_HEADER+'''text = ((data.get("input") or {}).get("stdout") or "").lower()
alive = ("ttl=" in text or "bytes from" in text) and "100% packet loss" not in text

# The LAST line printed must be one JSON object: the branch to follow and variables to set.
print(json.dumps({"branch": "alive" if alive else "down", "vars": {"alive": alive}}))
'''
_PY_BLANK=_PY_HEADER+'''output = (data.get("input") or {}).get("stdout") or ""

# Decide here, then print one JSON object as the last line.
print(json.dumps({"branch": "out", "vars": {"lines": len(output.splitlines())}}))
'''
_PY_PORTS=_PY_HEADER+'''import re

# Collect the open TCP ports from nmap output and hand them on as a variable.
output = (data.get("input") or {}).get("stdout") or ""
ports = sorted({int(m.group(1)) for m in re.finditer(r"^(\\d+)/tcp\\s+open", output, re.M)})
print(json.dumps({"branch": "found" if ports else "none", "vars": {"ports": ports}}))
'''
_SH_ALIVE='''# The previous node's result is the JSON file "$LOYA_INPUT_FILE" (also sent on stdin).
# The LAST line printed must be one JSON object: the branch to follow and variables to set.
if grep -qiE 'ttl=|bytes from' "$LOYA_INPUT_FILE" && ! grep -qi '100% packet loss' "$LOYA_INPUT_FILE"; then
  echo '{"branch":"alive","vars":{"alive":true}}'
else
  echo '{"branch":"down","vars":{"alive":false}}'
fi
'''
_SH_BLANK='''# The previous node's result is the JSON file "$LOYA_INPUT_FILE" (also sent on stdin).
# With jq installed:  stdout=$(jq -r '.input.stdout' "$LOYA_INPUT_FILE")
# The LAST line printed must be one JSON object: the branch to follow and variables to set.
echo '{"branch":"out","vars":{}}'
'''
_PS_ALIVE='''# The previous node's result is the JSON file $env:LOYA_INPUT_FILE (also sent on stdin).
$data = Get-Content -Raw -LiteralPath $env:LOYA_INPUT_FILE | ConvertFrom-Json
$text = [string]$data.input.stdout
$alive = ($text -match 'ttl=|bytes from') -and ($text -notmatch '100% (packet )?loss')

# The LAST line printed must be one JSON object: the branch to follow and variables to set.
$branch = if ($alive) { 'alive' } else { 'down' }
@{ branch = $branch; vars = @{ alive = $alive } } | ConvertTo-Json -Compress
'''
_PS_BLANK='''# The previous node's result is the JSON file $env:LOYA_INPUT_FILE (also sent on stdin).
$data = Get-Content -Raw -LiteralPath $env:LOYA_INPUT_FILE | ConvertFrom-Json
$output = [string]$data.input.stdout

# Decide here, then print one JSON object as the last line.
@{ branch = 'out'; vars = @{ length = $output.Length } } | ConvertTo-Json -Compress
'''
SCRIPT_TEMPLATES=[
    {"id":"alive-python","language":"python","name":"Is the host alive?","description":"Reads the ping output and takes the 'alive' or 'down' branch.","code":_PY_ALIVE,"branches":["alive","down"]},
    {"id":"alive-bash","language":"bash","name":"Is the host alive?","description":"Reads the ping output and takes the 'alive' or 'down' branch.","code":_SH_ALIVE,"branches":["alive","down"]},
    {"id":"alive-powershell","language":"powershell","name":"Is the host alive?","description":"Reads the ping output and takes the 'alive' or 'down' branch.","code":_PS_ALIVE,"branches":["alive","down"]},
    {"id":"blank-python","language":"python","name":"Blank Python script","description":"Reads the input and prints a result line.","code":_PY_BLANK,"branches":["out"]},
    {"id":"blank-bash","language":"bash","name":"Blank Bash script","description":"Prints a result line.","code":_SH_BLANK,"branches":["out"]},
    {"id":"blank-powershell","language":"powershell","name":"Blank PowerShell script","description":"Reads the input and prints a result line.","code":_PS_BLANK,"branches":["out"]},
    {"id":"nmap-ports-python","language":"python","name":"Open ports from nmap","description":"Collects the open TCP ports into the variable 'ports'; branches 'found' / 'none'.","code":_PY_PORTS,"branches":["found","none"]},
]
