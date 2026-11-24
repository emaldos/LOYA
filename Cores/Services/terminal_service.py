import os,json,base64,platform,subprocess,threading,uuid,shutil,sys,socket,tempfile,secrets,hmac,time,codecs,re,unicodedata
from datetime import datetime,timezone
from Cores import common_db
_IS_WINDOWS=platform.system()=="Windows"
if not _IS_WINDOWS:
    import pty,fcntl,termios,struct,signal
def _pty_child_setup():
    os.setsid()
    try:fcntl.ioctl(0,termios.TIOCSCTTY,0)
    except OSError:pass
_READ_CHUNK=65536
_DSR_QUERY=b"\x1b[6n"
_CUP_RE=re.compile(rb"\x1b\[(\d+);(\d+)H")
_ANSI_ANY_RE=re.compile(rb"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-9;?]*[A-Za-z]|\x1b[=>]")
_EDIT_BUF_MAX=65536
_MAX_SESSION_BUFFER=4*1024*1024
_SESSION_TAIL_BYTES=64*1024
_sessions={}
_lock=threading.Lock()
from Cores.settings_lock import SETTINGS_LOCK as _settings_lock
_WSL_PREFIX="wsl:"
_wsl_cache=None
def list_wsl_distros():
    global _wsl_cache
    if _wsl_cache is not None:return _wsl_cache
    _wsl_cache=[]
    if not _IS_WINDOWS or not shutil.which("wsl.exe"):return _wsl_cache
    try:
        res=subprocess.run(["wsl.exe","-l","-q"],capture_output=True,timeout=6,creationflags=subprocess.CREATE_NO_WINDOW)
        text=res.stdout.decode("utf-16-le",errors="ignore") if res.stdout[:2]==b"\xff\xfe" or b"\x00" in res.stdout[:8] else res.stdout.decode("utf-8",errors="ignore")
        _wsl_cache=[line.strip() for line in text.replace("\x00","").splitlines() if line.strip()]
    except Exception:
        _wsl_cache=[]
    return _wsl_cache
def refresh_wsl_distros():
    global _wsl_cache
    _wsl_cache=None
    return list_wsl_distros()
# Linux shells besides the login shell: offered only when they are on PATH and are not already the login shell.
_POSIX_EXTRA_SHELLS=("bash","zsh")
def _kali_wsl_ready():
    try:
        from Cores.Services import wsl_kali_service
        return wsl_kali_service.is_ready_for_sessions()
    except Exception:
        return False
def _available_shells():
    if _IS_WINDOWS:
        shells=[{"id":"cmd","label":"Command Prompt"}]
        if shutil.which("powershell.exe"):shells.append({"id":"powershell","label":"Windows PowerShell"})
        if shutil.which("pwsh.exe"):shells.append({"id":"pwsh","label":"PowerShell 7"})
        distros=list_wsl_distros()
        kali_ready="kali-linux" in distros and _kali_wsl_ready()
        for distro in distros:shells.append({"id":_WSL_PREFIX+distro,"label":"Kali Linux (WSL)" if distro=="kali-linux" and kali_ready else "WSL: "+distro})
        return shells
    sh=os.environ.get("SHELL","/bin/bash")
    login=os.path.basename(sh) or "shell"
    shells=[{"id":"shell","label":login}]
    for name in _POSIX_EXTRA_SHELLS:
        if name!=login and shutil.which(name):shells.append({"id":name,"label":name})
    if shutil.which("pwsh"):shells.append({"id":"pwsh","label":"PowerShell"})
    return shells
# The default for new sessions. "auto" (or nothing stored) = PowerShell 7, else Windows PowerShell, else cmd on Windows; the login shell on Linux.
# An explicit choice is kept as stored even while that shell is missing (e.g. pwsh uninstalled) - it is used again once the shell is back.
DEFAULT_SHELL_AUTO="auto"
def _auto_default_shell(ids):
    order=("pwsh","powershell","cmd") if _IS_WINDOWS else ("shell",)
    for candidate in order:
        if candidate in ids:return candidate
    return ids[0] if ids else ""
def _stored_default_shell():
    value=str(_extensions(_read_settings()).get("terminal_default_shell","") or "").strip()
    return value[:80] or DEFAULT_SHELL_AUTO
def default_shell(shells=None):
    ids=[s["id"] for s in (shells if shells is not None else _available_shells())]
    stored=_stored_default_shell()
    if stored!=DEFAULT_SHELL_AUTO and stored in ids:return stored
    return _auto_default_shell(ids)
def list_shells():
    """Shells for new sessions, the default first (the UI and create_session fall back to the first entry)."""
    shells=_available_shells()
    chosen=default_shell(shells)
    shells.sort(key=lambda s:0 if s["id"]==chosen else 1)
    for s in shells:s["default"]=s["id"]==chosen
    return shells
def set_default_shell(value):
    value=str(value or "").strip()
    if value!=DEFAULT_SHELL_AUTO and value not in {s["id"] for s in _available_shells()}:raise ValueError("That shell is not available on this computer.")
    with _settings_lock:
        d=_read_settings()
        ext=_extensions(d)
        ext["terminal_default_shell"]=value
        d["extensions"]=ext
        _write_settings(d)
    return get_settings()
_PWSH_APT_SCRIPT="apt-get update && apt-get install -y powershell"
def _pwsh_install_command():
    return ["sudo","-p","[sudo] password for %p: ","sh","-c",_PWSH_APT_SCRIPT]
def shell_extras():
    """What the new-session menu offers besides the shells: PowerShell install on Linux, Kali-on-WSL readiness on Windows."""
    if _IS_WINDOWS:
        return {"platform":"windows","kali_ready":any(s["id"]==_WSL_PREFIX+"kali-linux" and s["label"]=="Kali Linux (WSL)" for s in _available_shells())}
    installed=shutil.which("pwsh")
    installable=bool(shutil.which("apt-get") and shutil.which("sudo"))
    return {"platform":"linux","pwsh":{"installed":bool(installed),"path":installed or "","installable":installable and not installed,"command":"sudo sh -c '"+_PWSH_APT_SCRIPT+"'","reason":"" if installable or installed else "Install PowerShell with your distribution's package manager (apt-get and sudo were not found)."}}
# Task sessions run one fixed, known command in a LOYA terminal (installers and first-run steps that need the user to type).
# The argv comes from this table or from wsl_kali_service.task_command - never from text sent by the UI.
def _task_command(task,params):
    task=str(task or "")
    if task=="pwsh_install":
        if _IS_WINDOWS:raise ValueError("PowerShell is already part of Windows.")
        extras=shell_extras()["pwsh"]
        if extras["installed"]:raise ValueError("PowerShell is already installed.")
        if not extras["installable"]:raise ValueError(extras["reason"])
        return {"shell_id":"shell","argv":_pwsh_install_command(),"label":"Install PowerShell","conpty":False,"env":None,"audit":"terminal_pwsh_install"}
    from Cores.Services import wsl_kali_service
    return wsl_kali_service.task_command(task,params)
def create_task_session(task,params=None,cols=0,rows=0):
    spec=_task_command(task,params if isinstance(params,dict) else {})
    sess=TerminalSession(spec["shell_id"],spec["argv"],"",spec.get("env"),(cols,rows),prefer_conpty=bool(spec.get("conpty")))
    sess.label=spec["label"][:60]
    sess.task=str(task)
    with _lock:_sessions[sess.id]=sess
    if spec.get("audit"):
        try:
            from Cores.Services import security_service
            security_service.log_audit_event(spec["audit"],subprocess.list2cmdline(spec["argv"]) if _IS_WINDOWS else " ".join(spec["argv"]))
        except Exception:pass
    return {"session_id":sess.id,"shell_id":spec["shell_id"],"label":sess.label}
def close_wsl_sessions(distro=None):
    """Closes LOYA's WSL sessions (all of them, or one distro's) before WSL is stopped. Returns what was closed so the UI can offer to reopen it."""
    closed=[]
    with _lock:items=list(_sessions.items())
    for sid,sess in items:
        shell=str(getattr(sess,"shell_id","") or "")
        if not shell.startswith(_WSL_PREFIX):continue
        if distro and shell!=_WSL_PREFIX+distro:continue
        closed.append({"session_id":sid,"shell_id":shell,"label":getattr(sess,"label","") or ""})
        close_session(sid)
    return closed
def _posix_shell_path(shell_id):
    if shell_id in _POSIX_EXTRA_SHELLS or shell_id=="pwsh":
        found=shutil.which(shell_id)
        if found:return found
    return os.environ.get("SHELL","/bin/bash")
def _shell_command(shell_id):
    shell_id=str(shell_id or "")
    if shell_id.startswith(_WSL_PREFIX):return ["wsl.exe","-d",shell_id[len(_WSL_PREFIX):]]
    if _IS_WINDOWS:
        if shell_id=="powershell":return ["powershell.exe","-NoLogo"]
        if shell_id=="pwsh":return ["pwsh.exe","-NoLogo"]
        return ["cmd.exe"]
    # LOYA sends whole lines, so PSReadLine (which repaints the line with absolute cursor moves the panel cannot replay) is unloaded;
    # PowerShell then reads lines like it does on Windows pipes. The user's profile and prompt still load.
    if shell_id=="pwsh" and shutil.which("pwsh"):return [shutil.which("pwsh"),"-NoLogo","-NoExit","-Command","Remove-Module PSReadLine -ErrorAction SilentlyContinue"]
    return [_posix_shell_path(shell_id),"-i"]
def elevation_available():
    if _IS_WINDOWS:return {"platform":"windows","method":"uac"}
    if shutil.which("sudo"):return {"platform":"linux","method":"sudo"}
    if shutil.which("pkexec"):return {"platform":"linux","method":"pkexec"}
    return {"platform":"linux","method":None}
def _sudo_command(shell_id):
    return ["sudo","-p","[sudo] password for %p: "]+_shell_command(shell_id)
_CLOSE_GRACE_SECONDS=3
_CONPTY_PROBE_SECONDS=0.35
_conpty_module=None
def _conpty():
    global _conpty_module
    if _conpty_module is None:
        try:
            from Cores.Services import conpty as module
            _conpty_module=module if module.available() else False
        except Exception:
            _conpty_module=False
    return _conpty_module or None
def conpty_supported():
    return bool(_conpty())
def _clean_size(cols,rows):
    try:
        cols=int(cols or 0);rows=int(rows or 0)
    except Exception:
        return None
    if cols<20 or rows<5 or cols>1000 or rows>500:return None
    return (cols,rows)
class TerminalSession:
    def __init__(self,shell_id,command=None,cwd="",env=None,size=None,prefer_conpty=False):
        self.id=uuid.uuid4().hex[:12]
        self._prefer_conpty=bool(prefer_conpty)
        # PowerShell on Linux repaints the input line with "cursor to row N, column 1" on every key; the panel is line based,
        # so that becomes a carriage return (overwrite the current line), which it already renders.
        self._line_redraw_to_cr=not _IS_WINDOWS and shell_id=="pwsh" and command is None
        self._last_line=b""
        self._edit_buf=None
        self.shell_id=shell_id
        self._buf=bytearray()
        self._buf_lock=threading.Lock()
        self._decoder=codecs.getincrementaldecoder("utf-8")("replace")
        self._closed=False
        self._master_fd=None
        self._tail=bytearray()
        self._pty=None
        self.backend="pipe"
        self.elevated=False
        self.label=""
        self._initial_size=_clean_size(*size) if size else None
        self.cols=self._initial_size[0] if self._initial_size else 0
        self._start(command or _shell_command(shell_id),cwd,env)
    def _try_conpty(self,cmd,workdir,environment):
        module=_conpty()
        if module is None:return False
        try:
            session=module.ConptySession(cmd,120,30,workdir,environment)
        except Exception:
            return False
        time.sleep(_CONPTY_PROBE_SECONDS)
        if not session.alive():
            try:session.close()
            except Exception:pass
            return False
        self._pty=session
        self.backend="conpty"
        return True
    def _start(self,cmd,cwd="",env=None):
        workdir=cwd if cwd and os.path.isdir(cwd) else None
        environment=None
        if env:
            environment=dict(os.environ)
            environment.update({str(k):str(v) for k,v in env.items()})
        if _IS_WINDOWS:
            # Interactive installers (WSL first-run user creation) need a real console, so task sessions ask for ConPTY even when the setting is off.
            if (self._prefer_conpty or get_settings().get("use_conpty")) and self._try_conpty(cmd,workdir,environment):
                threading.Thread(target=self._read_loop,daemon=True).start()
                return
            self.proc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW,bufsize=0,cwd=workdir,env=environment)
        else:
            master,slave=pty.openpty()
            if self._initial_size:
                cols,rows=self._initial_size
                try:fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack("HHHH",int(rows),int(cols),0,0))
                except OSError:pass
            self.proc=subprocess.Popen(cmd,stdin=slave,stdout=slave,stderr=slave,preexec_fn=_pty_child_setup,close_fds=True,cwd=workdir,env=environment)
            os.close(slave)
            self._master_fd=master
        threading.Thread(target=self._read_loop,daemon=True).start()
    def _track_line(self,chunk):
        # The raw bytes of the line the cursor is on (the prompt, before input), capped.
        cut=chunk.rfind(b"\n")
        self._last_line=(chunk[cut+1:] if cut>=0 else self._last_line+chunk)[-4096:]
    def _answer_cursor_query(self,chunk):
        # PowerShell (and some TUIs) ask "where is the cursor?" (ESC[6n) and block until a terminal answers. LOYA's panel is not a
        # full VT, so answer for it: the last row, and the column right after the text already on the current line (the prompt).
        rows=(self._initial_size or (0,24))[1] or 24
        head=chunk[:chunk.find(_DSR_QUERY)]
        cut=head.rfind(b"\n")
        line=head[cut+1:] if cut>=0 else self._last_line+head
        prompt=_ANSI_ANY_RE.sub(b"",line).replace(b"\r",b"")
        col=len(prompt.decode("utf-8","replace"))+1
        for _ in range(chunk.count(_DSR_QUERY)):
            try:os.write(self._master_fd,b"\x1b[%d;%dR"%(rows,col))
            except OSError:break
    def _collapse_line_edit(self,chunk):
        # PowerShell on Linux echoes the input line by repainting it after every character ("cursor to the input start" + the
        # whole line). The panel is line based and LOYA sends whole lines, so the repaints are held back while the line is
        # edited and only the final text is passed on when the line ends (CR LF).
        if self._edit_buf is None:
            at=chunk.find(_DSR_QUERY)
            if at<0:return chunk
            self._edit_buf=b""
            head,chunk=chunk[:at+len(_DSR_QUERY)],chunk[at+len(_DSR_QUERY):]
            return head+self._collapse_line_edit(chunk)
        buf=self._edit_buf+chunk
        end=buf.find(b"\r\n")
        if end<0 and len(buf)>=_EDIT_BUF_MAX:end=len(buf)
        line,rest=(buf,b"") if end<0 else (buf[:end],buf[end:])
        # Asked again mid-line (the input wrapped): answer, but keep holding the line. A query after the line end belongs to the
        # next prompt and is handled when that rest is passed on.
        asked=line.count(_DSR_QUERY)
        if asked:
            line=line.replace(_DSR_QUERY,b"")
            rows=(self._initial_size or (0,24))[1] or 24
            for _ in range(asked):
                try:os.write(self._master_fd,b"\x1b[%d;1R"%rows)
                except OSError:break
        if end<0:
            self._edit_buf=line
            return b""
        self._edit_buf=None
        # The last repaint is the last stretch after a cursor move that has visible text (later moves only park the cursor).
        parts=[p for p in _CUP_RE.split(line)[::3] if _ANSI_ANY_RE.sub(b"",p).strip()]
        typed=parts[-1] if parts else b""
        return typed+self._collapse_line_edit(rest) if rest else typed
    def _append(self,chunk):
        with self._buf_lock:
            self._buf.extend(chunk)
            if len(self._buf)>_MAX_SESSION_BUFFER:del self._buf[:len(self._buf)-_MAX_SESSION_BUFFER]
            self._tail.extend(chunk)
            if len(self._tail)>_SESSION_TAIL_BYTES:del self._tail[:len(self._tail)-_SESSION_TAIL_BYTES]
    def peek(self):
        with self._buf_lock:
            return bytes(self._tail).decode("utf-8",errors="replace")
    def _read_loop(self):
        try:
            if self._pty is not None:
                while True:
                    chunk=self._pty.read(_READ_CHUNK)
                    if not chunk:break
                    self._append(chunk)
            elif _IS_WINDOWS:
                stream=self.proc.stdout
                while True:
                    chunk=stream.read(_READ_CHUNK)
                    if not chunk:break
                    self._append(chunk)
            else:
                while True:
                    try:chunk=os.read(self._master_fd,_READ_CHUNK)
                    except OSError:break
                    if not chunk:break
                    if self._line_redraw_to_cr:chunk=self._collapse_line_edit(chunk)
                    if _DSR_QUERY in chunk:self._answer_cursor_query(chunk)
                    if not chunk:continue
                    self._track_line(chunk)
                    self._append(chunk)
        except Exception:pass
        finally:self._closed=True
    def write(self,data):
        if self._closed:return False
        b=data.encode("utf-8",errors="ignore") if isinstance(data,str) else data
        try:
            if self._pty is not None:return self._pty.write(b)
            if _IS_WINDOWS:self.proc.stdin.write(b);self.proc.stdin.flush()
            else:os.write(self._master_fd,b)
            return True
        except Exception:return False
    def read(self):
        with self._buf_lock:
            data=bytes(self._buf)
            self._buf.clear()
        return self._decoder.decode(data)
    def resize(self,cols,rows):
        try:self.cols=int(cols)
        except (TypeError,ValueError):pass
        if self._pty is not None:return self._pty.resize(cols,rows)
        if _IS_WINDOWS or self._master_fd is None:return False
        try:
            fcntl.ioctl(self._master_fd,termios.TIOCSWINSZ,struct.pack("HHHH",int(rows),int(cols),0,0))
            return True
        except Exception:return False
    def alive(self):
        if self._pty is not None:return self._pty.alive()
        return self.proc.poll() is None
    def close(self):
        self._closed=True
        if self._pty is not None:
            try:self._pty.close()
            except Exception:pass
            return
        try:
            if _IS_WINDOWS:self.proc.terminate()
            else:os.killpg(os.getpgid(self.proc.pid),signal.SIGTERM)
        except Exception:pass
        try:
            if not _IS_WINDOWS and self._master_fd is not None:os.close(self._master_fd)
        except Exception:pass
        threading.Thread(target=self._reap,daemon=True).start()
    def _reap(self):
        try:
            self.proc.wait(timeout=_CLOSE_GRACE_SECONDS)
            return
        except Exception:pass
        try:
            if _IS_WINDOWS:self.proc.kill()
            else:os.killpg(os.getpgid(self.proc.pid),signal.SIGKILL)
        except Exception:pass
        try:self.proc.wait(timeout=_CLOSE_GRACE_SECONDS)
        except Exception:pass
_ELEVATED_HELPER_SRC=r'''
import socket,subprocess,sys,threading
HANDSHAKE_TOKEN="__LOYA_ELEVATED_TOKEN__"
def main():
    port=int(sys.argv[1])
    cmd=sys.argv[2:]
    s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    s.connect(("127.0.0.1",port))
    s.sendall((HANDSHAKE_TOKEN+"\n").encode("ascii"))
    proc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW,bufsize=0)
    def pump_out():
        try:
            while True:
                chunk=proc.stdout.read(65536)
                if not chunk:break
                s.sendall(chunk)
        except Exception:
            pass
        finally:
            try:s.shutdown(socket.SHUT_WR)
            except Exception:pass
    threading.Thread(target=pump_out,daemon=True).start()
    try:
        while True:
            chunk=s.recv(4096)
            if not chunk:break
            try:
                proc.stdin.write(chunk)
                proc.stdin.flush()
            except Exception:
                break
    except Exception:
        pass
    finally:
        try:proc.terminate()
        except Exception:pass
        try:s.close()
        except Exception:pass
if __name__=="__main__":
    main()
'''
_ELEVATED_TOKEN_BYTES=32
_ELEVATED_CONNECT_TIMEOUT=60
_ELEVATED_HANDSHAKE_TIMEOUT=10
_WINDOWS_ADMINISTRATORS_SID="*S-1-5-32-544"
# SA-39: the administrator helper never exists as a file. A script written to a temp folder before the UAC prompt could be swapped
# by any process running as the user in that window (it would then run elevated); instead the source travels base64-encoded
# inside the -c argument of the elevated interpreter, i.e. in the command line ShellExecute hands to the elevated process.
def elevated_helper_source(token):
    if not re.fullmatch(r"[0-9a-f]{16,128}",str(token or "")):raise ValueError("Invalid elevation token.")
    return _ELEVATED_HELPER_SRC.replace("__LOYA_ELEVATED_TOKEN__",token)
def elevated_helper_parameters(token,port,shell_cmd):
    """The lpParameters string for ShellExecuteW(runas, python): -I -S (standard library only), the helper as -c code (base64,
    so no quote or newline needs escaping), then the port and the shell command line. Inside the helper sys.argv[1] is the port."""
    code=base64.b64encode(elevated_helper_source(token).encode("utf-8")).decode("ascii")
    loader=f"import base64;exec(compile(base64.b64decode('{code}'),'loya_elevated_helper','exec'))"
    port=int(port)
    if not 0<port<65536:raise ValueError("Invalid port.")
    args=[]
    for c in shell_cmd:
        c=str(c)
        if '"' in c or "\n" in c or "\r" in c:raise ValueError("The shell command cannot be passed to the elevated helper.")
        args.append(f'"{c}"')
    return f'-I -S -c "{loader}" {port} '+" ".join(args)
def _recv_exact(conn,size,timeout):
    conn.settimeout(timeout)
    buf=b""
    while len(buf)<size:
        chunk=conn.recv(size-len(buf))
        if not chunk:break
        buf+=chunk
    return buf
def _accept_verified_connection(server,token,deadline):
    expected=(token+"\n").encode("ascii")
    while True:
        remaining=deadline-time.monotonic()
        if remaining<=0:break
        server.settimeout(remaining)
        try:conn,_=server.accept()
        except socket.timeout:break
        try:
            received=_recv_exact(conn,len(expected),min(_ELEVATED_HANDSHAKE_TIMEOUT,max(1.0,remaining)))
            if hmac.compare_digest(received,expected):
                conn.settimeout(None)
                return conn
        except OSError:pass
        try:conn.close()
        except OSError:pass
    raise RuntimeError("Elevated session did not authenticate in time.")
class ElevatedSession:
    def __init__(self,shell_id):
        self.id=uuid.uuid4().hex[:12]
        self.shell_id=shell_id
        self.label=""
        self._buf=bytearray()
        self._buf_lock=threading.Lock()
        self._decoder=codecs.getincrementaldecoder("utf-8")("replace")
        self._closed=False
        self._conn=None
        self._start(shell_id)
    def _start(self,shell_id):
        import ctypes
        token=secrets.token_hex(_ELEVATED_TOKEN_BYTES)
        server=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        try:
            server.bind(("127.0.0.1",0))
            server.listen(8)
            port=server.getsockname()[1]
            # -I -S: the elevated interpreter loads only the standard library - no PYTHON* variables, no user site-packages and no
            # .pth files from the (user-writable) venv, which would otherwise run with administrator rights. The helper is -c code.
            args=elevated_helper_parameters(token,port,_shell_command(shell_id))
            if int(ctypes.windll.shell32.ShellExecuteW(None,"runas",sys.executable,args,None,0))<=32:
                raise RuntimeError("Elevation was cancelled or failed.")
            self._conn=_accept_verified_connection(server,token,time.monotonic()+_ELEVATED_CONNECT_TIMEOUT)
        finally:
            try:server.close()
            except OSError:pass
        threading.Thread(target=self._read_loop,daemon=True).start()
    def _read_loop(self):
        try:
            while True:
                chunk=self._conn.recv(_READ_CHUNK)
                if not chunk:break
                with self._buf_lock:
                    self._buf.extend(chunk)
                    if len(self._buf)>_MAX_SESSION_BUFFER:del self._buf[:len(self._buf)-_MAX_SESSION_BUFFER]
        except Exception:pass
        finally:self._closed=True
    def write(self,data):
        if self._closed or not self._conn:return False
        b=data.encode("utf-8",errors="ignore") if isinstance(data,str) else data
        try:
            self._conn.sendall(b)
            return True
        except Exception:return False
    def read(self):
        with self._buf_lock:
            data=bytes(self._buf)
            self._buf.clear()
        return self._decoder.decode(data)
    def resize(self,cols,rows):
        return False
    def alive(self):
        return not self._closed
    def close(self):
        self._closed=True
        try:
            if self._conn:self._conn.close()
        except Exception:pass
def _expand_cwd(cwd):
    text=str(cwd or "").strip()
    if not text:return ""
    path=os.path.expandvars(os.path.expanduser(text))
    return path if os.path.isdir(path) else ""
def _startup_payload(shell_id,text):
    lines=[line.rstrip() for line in str(text or "").replace("\r\n","\n").replace("\r","\n").split("\n")]
    lines=[line for line in lines if line.strip()]
    if not lines:return ""
    newline="\r\n" if _IS_WINDOWS and not str(shell_id or "").startswith(_WSL_PREFIX) else "\n"
    return newline.join(lines)+newline
def create_session(shell_id=None,profile_id=None,cols=0,rows=0,cwd="",startup="",label=""):
    # cwd and startup come from saved or reopened sessions and override / extend the profile's own.
    profile=get_profile(profile_id) if profile_id else None
    if profile and profile.get("shell_id"):shell_id=profile["shell_id"]
    shells=list_shells()
    ids={s["id"] for s in shells}
    if shell_id not in ids:shell_id=shells[0]["id"]
    workdir=_expand_cwd(cwd) or _expand_cwd((profile or {}).get("cwd",""))
    sess=TerminalSession(shell_id,None,workdir,(profile or {}).get("env"),(cols,rows))
    sess.label=str(label or "")[:60]
    with _lock:_sessions[sess.id]=sess
    payload=_startup_payload(shell_id,"\n".join(x for x in ((profile or {}).get("startup",""),str(startup or "")[:SAVED_STARTUP_MAX]) if x))
    if payload:
        threading.Timer(0.4,lambda:sess.write(payload)).start()
    return sess.id
def session_cwd(session_id):
    """The shell's live working directory where the OS exposes it (Linux /proc); "" otherwise, so the UI falls back to the cwd its shell integration reported."""
    sess=_sessions.get(session_id)
    if sess is None or getattr(sess,"elevated",False) or _IS_WINDOWS:return ""
    proc=getattr(sess,"proc",None)
    if proc is None:return ""
    try:return os.readlink(f"/proc/{proc.pid}/cwd")
    except OSError:return ""
def set_session_label(session_id,label):
    sess=_sessions.get(session_id)
    if sess is None:return False
    sess.label=str(label or "").strip()[:60]
    return True
def poll_sessions(session_ids,alive_ids=None):
    """One bridge round trip for every visible pane instead of one read plus one alive call per session."""
    out={};alive={}
    for sid in list(session_ids or [])[:64]:
        sess=_sessions.get(sid)
        if sess is None:continue
        try:chunk=sess.read()
        except Exception:chunk=""
        if chunk:out[sid]=chunk
    for sid in list(alive_ids or [])[:64]:
        sess=_sessions.get(sid)
        try:alive[sid]=bool(sess) and sess.alive()
        except Exception:alive[sid]=False
    return {"out":out,"alive":alive}
PROFILE_COLORS=["accent","blue","green","amber","rose","violet"]
def _profile_store(d):
    ext=_extensions(d)
    items=ext.get("terminal_profiles",[])
    return items if isinstance(items,list) else []
def _clean_profile(raw):
    if not isinstance(raw,dict):return None
    name=str(raw.get("name","") or "").strip()
    if not name:return None
    env=raw.get("env",{})
    if not isinstance(env,dict):env={}
    color=str(raw.get("color","") or "").strip().lower()
    return {"id":str(raw.get("id") or uuid.uuid4().hex[:10]),"name":name[:60],"shell_id":str(raw.get("shell_id","") or ""),"cwd":str(raw.get("cwd","") or ""),"startup":str(raw.get("startup","") or "")[:500],"env":{str(k)[:64]:str(v)[:512] for k,v in list(env.items())[:32]},"color":color if color in PROFILE_COLORS else "accent"}
def list_profiles():
    return [p for p in (_clean_profile(x) for x in _profile_store(_read_settings())) if p]
def get_profile(profile_id):
    key=str(profile_id or "")
    for profile in list_profiles():
        if profile["id"]==key:return profile
    return None
def save_profile(raw):
    profile=_clean_profile(raw)
    if not profile:raise ValueError("A profile name is required.")
    with _settings_lock:
        d=_read_settings()
        ext=_extensions(d)
        items=[p for p in (_clean_profile(x) for x in _profile_store(d)) if p]
        replaced=False
        for index,existing in enumerate(items):
            if existing["id"]==profile["id"]:
                items[index]=profile
                replaced=True
                break
        if not replaced:items.append(profile)
        ext["terminal_profiles"]=items[:40]
        d["extensions"]=ext
        _write_settings(d)
    return list_profiles()
def delete_profile(profile_id):
    key=str(profile_id or "")
    with _settings_lock:
        d=_read_settings()
        ext=_extensions(d)
        items=[p for p in (_clean_profile(x) for x in _profile_store(d)) if p and p["id"]!=key]
        ext["terminal_profiles"]=items
        d["extensions"]=ext
        _write_settings(d)
    return list_profiles()
def _get(session_id):
    sess=_sessions.get(session_id)
    if not sess:raise ValueError("Unknown terminal session.")
    return sess
def write_input(session_id,data):
    return _get(session_id).write(data)
def peek_output(session_id):
    session=_sessions.get(session_id)
    if session is None:return None
    return session.peek()
# Plain text of raw terminal output, for readers that are not the panel (the AI's terminal_read). Line editors (zsh ZLE with
# syntax highlighting, bash readline) repaint the typed line with backspaces and cursor moves and wrap it with " \r"; each line
# is replayed on a `cols`-wide row so the result is what a terminal shows. LOYA's hidden job markers and their echo are removed.
_PLAIN_SEQ_RE=re.compile(r"\x1b(?:\[([0-9;?:>=!]*)[ -/]*([@-~])|\][^\x07\x1b]*(?:\x07|\x1b\\)?|[PX^_].*?(?:\x1b\\|$)|[()*+#%].?|.?)",re.S)
_JOB_RESULT_RE=re.compile(r"__LOYA_JOB__[0-9a-z]+\|-?\d+\|[^|\r\n]*__END__")
_JOB_ECHO_RE=re.compile(r"\s*(?:;?printf '|&call echo |;\$LoyaOk=\$\?;Write-Output \")__LOYA_JOB__.*$")
def _plain_line(line,cols):
    width=cols if cols and cols>=20 else 80
    rows=[[]];row=col=0;wrap=False;i=0
    while i<len(line):
        ch=line[i]
        if ch=="\x1b":
            m=_PLAIN_SEQ_RE.match(line,i)
            i=m.end() if m and m.end()>i else i+1
            if m and m.group(2) and not (m.group(1) or "").startswith(("?",">")):
                final=m.group(2);params=m.group(1) or "";n=max(1,int(params) if params.isdigit() else 1);mode=int(params) if params.isdigit() else 0
                if final=="D":col=max(0,col-n);wrap=False
                elif final=="C":col=min(width-1,col+n);wrap=False
                elif final=="G":col=min(width-1,n-1);wrap=False
                elif final=="A":row=max(0,row-n);wrap=False
                elif final=="B":
                    row+=n;wrap=False
                    while len(rows)<=row:rows.append([])
                elif final=="K" and mode==0:del rows[row][col:]
                elif final=="K" and mode==2:rows[row].clear()
                elif final=="J" and mode==0:del rows[row][col:];del rows[row+1:]
            continue
        i+=1
        if ch=="\r":col=0;wrap=False;continue
        if ch=="\b":col=max(0,col-1);wrap=False;continue
        if ch=="\t":col=min(width-1,(col//8+1)*8);continue
        if ord(ch)<32 or ch=="\x7f":continue
        wide=2 if unicodedata.east_asian_width(ch) in "WF" else 1
        if wrap or (wide==2 and col==width-1):
            row+=1;col=0;wrap=False
            if len(rows)<=row:rows.append([])
        cells=rows[row]
        while len(cells)<col+wide:cells.append(" ")
        cells[col]=ch
        if wide==2:cells[col+1]=""
        col+=wide
        if col>=width:col=width-1;wrap=True
    return "".join("".join(r) for r in rows)
def peek_plain(session_id):
    session=_sessions.get(session_id)
    if session is None:return None
    return plain_terminal_text(session.peek(),getattr(session,"cols",0))
def plain_terminal_text(text,cols=0):
    out=[]
    for line in str(text or "").split("\n"):
        plain=_JOB_ECHO_RE.sub("",_JOB_RESULT_RE.sub("",_plain_line(line,cols))).rstrip()
        if plain or not _JOB_RESULT_RE.search(line):out.append(plain)
    return "\n".join(out)
def read_output(session_id):
    return _get(session_id).read()
def resize_session(session_id,cols,rows):
    return _get(session_id).resize(cols,rows)
def session_alive(session_id):
    sess=_sessions.get(session_id)
    return bool(sess) and sess.alive()
def session_exit_code(session_id):
    sess=_sessions.get(session_id)
    if not sess or sess.alive():return None
    proc=getattr(sess,"proc",None)
    return None if proc is None else proc.returncode
def close_session(session_id):
    sess=_sessions.pop(session_id,None)
    if not sess:return False
    sess.close()
    return True
def close_all_sessions():
    with _lock:
        ids=list(_sessions.keys())
    for sid in ids:close_session(sid)
def launch_elevated(shell_id=None):
    shells=list_shells()
    ids={s["id"] for s in shells}
    if shell_id not in ids:shell_id=shells[0]["id"]
    if _IS_WINDOWS:
        try:
            sess=ElevatedSession(shell_id)
            with _lock:_sessions[sess.id]=sess
            return True,{"kind":"session","session_id":sess.id}
        except Exception as e:
            return False,f"Elevation failed: {e}"
    info=elevation_available()
    method=info["method"]
    if method in ("sudo","pkexec"):
        command=_sudo_command(shell_id) if method=="sudo" else ["pkexec"]+_shell_command(shell_id)
        try:
            sess=TerminalSession(shell_id,command=command)
            sess.elevated=True
            with _lock:_sessions[sess.id]=sess
            return True,{"kind":"session","session_id":sess.id,"method":method}
        except Exception as e:
            return False,f"{method} launch failed: {e}"
    return False,"No elevation mechanism available on this system."
JOB_STATES=("pending","running","done","failed","killed","orphaned","skipped")
_JOB_LIST_LIMIT=500
# skip_reason and chain_name (v14) are additive: older readers that pick columns by name keep working.
_JOB_COLUMNS="id,job_key,session_id,label,command,source,state,exit_code,started_at,ended_at,cwd,bytes_out,chain_id,chain_pos,skip_reason,chain_name"
def _job_now():
    return datetime.now(timezone.utc).isoformat()
_job_columns_ok=set()
def _job_con():
    con=common_db.connect(common_db.db_path(),timeout=5)
    common_db.ensure_schema(con)
    path=common_db.db_path()
    if path not in _job_columns_ok:
        # Self-heal the v14 columns once per DB file, in case its user_version was written by a build without that migration.
        try:
            have={r[1] for r in con.execute("PRAGMA table_info(TerminalJobs)").fetchall()}
            for col in ("skip_reason","chain_name"):
                if col not in have:con.execute("ALTER TABLE TerminalJobs ADD COLUMN "+col+" TEXT")
            con.commit()
            _job_columns_ok.add(path)
        except Exception:
            pass
    return con
def _job_row(row):
    return dict(zip(_JOB_COLUMNS.split(","),row)) if row else None
def _job_label(command):
    text=str(command or "").strip()
    if not text:return "command"
    return text.split()[0][:40]
def start_job(job_key,session_id,command,source="terminal"):
    key=str(job_key or "").strip()
    if not key:raise ValueError("A job key is required.")
    audit_command(command,source,session_id)
    con=_job_con()
    try:
        con.execute("INSERT OR REPLACE INTO TerminalJobs(job_key,session_id,label,command,source,state,exit_code,started_at,ended_at,cwd,bytes_out,chain_id,chain_pos) VALUES(?,?,?,?,?,'running',NULL,?,NULL,NULL,0,NULL,NULL)",(key,str(session_id or ""),_job_label(command),str(command or ""),str(source or "terminal"),_job_now()))
        con.commit()
    finally:
        con.close()
    return get_job(key)
def finish_job(job_key,exit_code=None,cwd="",bytes_out=0,state=""):
    key=str(job_key or "").strip()
    if not key:return None
    code=None if exit_code is None else int(exit_code)
    resolved=state if state in JOB_STATES else ("done" if code==0 else "failed" if code is not None else "orphaned")
    con=_job_con()
    try:
        con.execute("UPDATE TerminalJobs SET state=?,exit_code=?,ended_at=?,cwd=?,bytes_out=? WHERE job_key=?",(resolved,code,_job_now(),str(cwd or ""),int(bytes_out or 0),key))
        con.commit()
    finally:
        con.close()
    return get_job(key)
def mark_job(job_key,state):
    if state not in JOB_STATES:raise ValueError("Unknown job state.")
    key=str(job_key or "").strip()
    ended=None if state=="running" else _job_now()
    con=_job_con()
    try:
        con.execute("UPDATE TerminalJobs SET state=?,ended_at=? WHERE job_key=?",(state,ended,key))
        con.commit()
    finally:
        con.close()
    return get_job(key)
def get_job(job_key):
    con=_job_con()
    try:
        row=con.execute("SELECT "+_JOB_COLUMNS+" FROM TerminalJobs WHERE job_key=?",(str(job_key or ""),)).fetchone()
    finally:
        con.close()
    return _job_row(row)
def list_jobs(session_id=None,limit=200):
    try:limit=max(1,min(int(limit or 200),_JOB_LIST_LIMIT))
    except (TypeError,ValueError):limit=200
    query="SELECT "+_JOB_COLUMNS+" FROM TerminalJobs"
    params=[]
    if session_id:
        query+=" WHERE session_id=?"
        params.append(str(session_id))
    query+=" ORDER BY id DESC LIMIT ?"
    params.append(limit)
    con=_job_con()
    try:
        rows=con.execute(query,params).fetchall()
    finally:
        con.close()
    return [_job_row(r) for r in rows]
def delete_job(job_key):
    con=_job_con()
    try:
        changed=con.execute("DELETE FROM TerminalJobs WHERE job_key=?",(str(job_key or ""),)).rowcount
        con.commit()
    finally:
        con.close()
    return changed>0
def clear_finished_jobs(session_id=None):
    query="DELETE FROM TerminalJobs WHERE state NOT IN ('running','pending')"
    params=[]
    if session_id:
        query+=" AND session_id=?"
        params.append(str(session_id))
    con=_job_con()
    try:
        changed=con.execute(query,params).rowcount
        con.commit()
    finally:
        con.close()
    return changed
def reap_running_jobs():
    con=_job_con()
    try:
        changed=con.execute("UPDATE TerminalJobs SET state='orphaned',ended_at=? WHERE state IN ('running','pending')",(_job_now(),)).rowcount
        con.commit()
    finally:
        con.close()
    return changed
def interrupt_session(session_id):
    sess=_sessions.get(session_id)
    if not sess:return False
    return bool(sess.write("\x03"))
_BATCH_MAX_OUTPUT=512*1024
_BATCH_DEFAULT_CONCURRENCY=4
_BATCH_MAX_CONCURRENCY=16
_batch_outputs={}
_batch_procs={}
_batch_lock=threading.Lock()
def _one_shot_command(shell_id,text):
    if _IS_WINDOWS:
        if shell_id=="pwsh":return ["pwsh.exe","-NoLogo","-NoProfile","-Command",text]
        if shell_id=="powershell":return ["powershell.exe","-NoLogo","-NoProfile","-Command",text]
        return ["cmd.exe","/c",text]
    if shell_id=="pwsh" and shutil.which("pwsh"):return [shutil.which("pwsh"),"-NoLogo","-NoProfile","-Command",text]
    return [_posix_shell_path(shell_id),"-lc",text]
_SPILL_DIR_NAME="job_output"
_SPILL_THRESHOLD=_BATCH_MAX_OUTPUT
def _spill_dir():
    path=os.path.join(common_db.data_dir(),_SPILL_DIR_NAME)
    os.makedirs(path,exist_ok=True)
    return path
def _spill_path(job_key):
    safe=re.sub(r"[^A-Za-z0-9_-]","",str(job_key or ""))[:64]
    if not safe:return None
    return os.path.join(_spill_dir(),safe+".txt")
def _batch_store_output(job_key,text):
    body=str(text or "")
    path=None
    if len(body)>_SPILL_THRESHOLD:
        try:
            path=_spill_path(job_key)
            if path:
                data=body.encode("utf-8",errors="replace")
                if common_db.encryption_configured():
                    # Encryption at rest on: the spilled output (it can hold credentials) is an AES-GCM stream, never plaintext.
                    from Cores import crypto_store as _cs
                    key=common_db.session_key()
                    if key is None:raise common_db.DatabaseLocked(common_db.ENCRYPTED_MESSAGE)
                    data=_cs.encrypt_bytes(data,key)
                fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|getattr(os,"O_BINARY",0),0o600)
                with os.fdopen(fd,"wb") as handle:handle.write(data)
        except Exception:
            path=None
    with _batch_lock:
        _batch_outputs[job_key]={"tail":body[-_BATCH_MAX_OUTPUT:],"total":len(body),"path":path}
def _run_batch_item(shell_id,item,semaphore):
    job_key=item["job_key"]
    command=item["command"]
    with semaphore:
        if get_job(job_key) is None:return
        current=get_job(job_key)
        if current and current.get("state")=="killed":return
        try:
            proc=subprocess.Popen(_one_shot_command(shell_id,command),stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0,start_new_session=not _IS_WINDOWS)
        except Exception as exc:
            _batch_store_output(job_key,str(exc))
            finish_job(job_key,None,"",0,"failed")
            return
        with _batch_lock:_batch_procs[job_key]=proc
        try:
            raw=proc.communicate()[0] or b""
        except Exception:
            raw=b""
        finally:
            with _batch_lock:_batch_procs.pop(job_key,None)
        text=raw.decode("utf-8",errors="replace")
        _batch_store_output(job_key,text)
        state="killed" if (get_job(job_key) or {}).get("state")=="killed" else ""
        finish_job(job_key,proc.returncode,"",len(text),state)
def start_batch(shell_id,items,max_concurrent=None,source="batch"):
    shells={s["id"] for s in list_shells()}
    if shell_id not in shells:shell_id=list_shells()[0]["id"]
    prepared=[]
    for item in items or []:
        if not isinstance(item,dict):continue
        command=str(item.get("command","") or "").strip()
        if not command:continue
        job_key=str(item.get("job_key") or "").strip() or ("b"+uuid.uuid4().hex[:11])
        prepared.append({"job_key":job_key,"command":command,"label":str(item.get("label","") or "")})
    if not prepared:raise ValueError("No commands to run.")
    try:limit=_BATCH_DEFAULT_CONCURRENCY if max_concurrent is None or max_concurrent=="" else int(max_concurrent)
    except (TypeError,ValueError):limit=_BATCH_DEFAULT_CONCURRENCY
    limit=max(1,min(limit,_BATCH_MAX_CONCURRENCY))
    for item in prepared:
        start_job(item["job_key"],"batch:"+shell_id,item["command"],source)
        if item["label"]:_set_job_label(item["job_key"],item["label"])
    semaphore=threading.Semaphore(limit)
    for item in prepared:
        threading.Thread(target=_run_batch_item,args=(shell_id,item,semaphore),daemon=True).start()
    return {"job_keys":[i["job_key"] for i in prepared],"concurrency":limit}
def _set_job_label(job_key,label):
    con=_job_con()
    try:
        con.execute("UPDATE TerminalJobs SET label=? WHERE job_key=?",(str(label)[:80],str(job_key)))
        con.commit()
    finally:
        con.close()
def batch_output(job_key,full=False):
    with _batch_lock:
        record=_batch_outputs.get(str(job_key or ""))
    if not record:return ""
    if not full or not record.get("path"):return record["tail"]
    try:
        with open(record["path"],"rb") as handle:raw=handle.read()
        from Cores import crypto_store as _cs
        if raw[:8]==_cs.MAGIC:raw=_cs.decrypt_bytes(raw,common_db.session_key())
        return raw.decode("utf-8",errors="replace").replace("\r\n","\n").replace("\r","\n")  # same as text-mode reading
    except Exception:
        return record["tail"]
def batch_output_info(job_key):
    with _batch_lock:
        record=_batch_outputs.get(str(job_key or ""))
    if not record:return {"total":0,"held":0,"spilled":False}
    return {"total":record["total"],"held":len(record["tail"]),"spilled":bool(record.get("path"))}
def cancel_batch_job(job_key):
    key=str(job_key or "")
    with _batch_lock:
        proc=_batch_procs.get(key)
    mark_job(key,"killed")
    if proc is None:return False
    try:
        if _IS_WINDOWS:proc.terminate()
        else:os.killpg(os.getpgid(proc.pid),signal.SIGTERM)
        return True
    except Exception:
        return False
_CHAIN_POLICIES=("stop","continue")
_cancelled_chains=set()
def _chain_insert(chain_id,position,item,shell_id,source,chain_name=""):
    # A step that arrives with a skip_reason (the run was told to stop before it) is stored as skipped straight away.
    reason=item.get("skip_reason") or None
    state="skipped" if reason else "pending"
    now=_job_now()
    con=_job_con()
    try:
        con.execute("INSERT OR REPLACE INTO TerminalJobs(job_key,session_id,label,command,source,state,exit_code,started_at,ended_at,cwd,bytes_out,chain_id,chain_pos,skip_reason,chain_name) VALUES(?,?,?,?,?,?,NULL,?,?,NULL,0,?,?,?,?)",(item["job_key"],"chain:"+shell_id,item["label"] or _job_label(item["command"]),item["command"],source,state,now,now if reason else None,chain_id,position,reason,str(chain_name or "")[:120] or None))
        con.commit()
    finally:
        con.close()
def _chain_begin_step(job_key):
    con=_job_con()
    try:
        con.execute("UPDATE TerminalJobs SET state='running',started_at=? WHERE job_key=? AND state='pending'",(_job_now(),job_key))
        con.commit()
    finally:
        con.close()
def _chain_skip(job_keys,reason=""):
    if not job_keys:return
    con=_job_con()
    try:
        con.executemany("UPDATE TerminalJobs SET state='skipped',ended_at=?,skip_reason=COALESCE(skip_reason,?) WHERE job_key=? AND state='pending'",[(_job_now(),reason or None,key) for key in job_keys])
        con.commit()
    finally:
        con.close()
def _run_chain_step(shell_id,item):
    job_key=item["job_key"]
    current=get_job(job_key)
    if current is None:return "skipped"
    if current.get("state")in("killed","skipped"):return current["state"]
    _chain_begin_step(job_key)
    try:
        proc=subprocess.Popen(_one_shot_command(shell_id,item["command"]),stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0,start_new_session=not _IS_WINDOWS)
    except Exception as exc:
        _batch_store_output(job_key,str(exc))
        finish_job(job_key,None,"",0,"failed")
        return "failed"
    with _batch_lock:_batch_procs[job_key]=proc
    try:
        raw=proc.communicate()[0] or b""
    except Exception:
        raw=b""
    finally:
        with _batch_lock:_batch_procs.pop(job_key,None)
    text=raw.decode("utf-8",errors="replace")
    _batch_store_output(job_key,text)
    killed=(get_job(job_key) or {}).get("state")=="killed"
    finish_job(job_key,proc.returncode,"",len(text),"killed" if killed else "")
    if killed:return "killed"
    return "done" if proc.returncode==0 else "failed"
def _run_chain(chain_id,shell_id,items,policy):
    try:
        for index,item in enumerate(items):
            with _batch_lock:cancelled=chain_id in _cancelled_chains
            if cancelled:
                _chain_skip([i["job_key"] for i in items[index:]],"Cancelled")
                return
            outcome=_run_chain_step(shell_id,item)
            if outcome=="done":continue
            if outcome=="killed" or policy=="stop":
                _chain_skip([i["job_key"] for i in items[index+1:]],("Step "+str(index+1)+" was stopped") if outcome=="killed" else ("Step "+str(index+1)+" failed"))
                return
    finally:
        with _batch_lock:_cancelled_chains.discard(chain_id)
def start_chain(shell_id,items,policy="stop",source="playbook",chain_name=""):
    shells={s["id"] for s in list_shells()}
    if shell_id not in shells:shell_id=list_shells()[0]["id"]
    prepared=[]
    for item in items or []:
        if not isinstance(item,dict):continue
        command=str(item.get("command","") or "").strip()
        if not command:continue
        prepared.append({"job_key":str(item.get("job_key") or "").strip() or ("c"+uuid.uuid4().hex[:11]),"command":command,"label":str(item.get("label","") or ""),"skip_reason":str(item.get("skip_reason","") or "").strip()[:200]})
    if not prepared:raise ValueError("No commands to run.")
    if policy not in _CHAIN_POLICIES:policy="stop"
    # The chain stops before the first step that carries a skip_reason; every later step is skipped too.
    stop_at=next((i for i,item in enumerate(prepared) if item["skip_reason"]),None)
    if stop_at is not None:
        for item in prepared[stop_at+1:]:
            if not item["skip_reason"]:item["skip_reason"]="Chain stopped before step "+str(stop_at+1)
    runnable=prepared if stop_at is None else prepared[:stop_at]
    chain_id="chain"+uuid.uuid4().hex[:10]
    for position,item in enumerate(prepared):
        _chain_insert(chain_id,position,item,shell_id,source,chain_name)
        if not item["skip_reason"]:audit_command(item["command"],source,"chain:"+shell_id)
    threading.Thread(target=_run_chain,args=(chain_id,shell_id,runnable,policy),daemon=True).start()
    return {"chain_id":chain_id,"policy":policy,"job_keys":[i["job_key"] for i in prepared],"stop_at":stop_at}
def chain_status(chain_id):
    key=str(chain_id or "")
    if not key:return None
    con=_job_con()
    try:
        rows=con.execute("SELECT "+_JOB_COLUMNS+" FROM TerminalJobs WHERE chain_id=? ORDER BY chain_pos ASC",(key,)).fetchall()
    finally:
        con.close()
    steps=[_job_row(r) for r in rows]
    if not steps:return None
    states=[s["state"] for s in steps]
    finished=[s for s in states if s not in("pending","running")]
    return {"chain_id":key,"chain_name":steps[0].get("chain_name") or "","steps":steps,"total":len(steps),"finished":len(finished),"failed":states.count("failed"),"skipped":states.count("skipped"),"active":"running"in states or "pending"in states}
def cancel_chain(chain_id):
    status=chain_status(chain_id)
    if status is None:return False
    with _batch_lock:_cancelled_chains.add(str(chain_id))
    _chain_skip([s["job_key"] for s in status["steps"] if s["state"]=="pending"],"Cancelled")
    for step in status["steps"]:
        if step["state"]=="running":cancel_batch_job(step["job_key"])
    return True
def _drop_spill(record):
    path=record.get("path") if isinstance(record,dict) else None
    if not path:return
    try:os.remove(path)
    except Exception:pass
def clear_batch_output(job_key=None):
    with _batch_lock:
        if job_key:
            _drop_spill(_batch_outputs.pop(str(job_key),None) or {})
        else:
            for record in _batch_outputs.values():_drop_spill(record)
            _batch_outputs.clear()
    return True
_AI_REQUEST_LIMIT=50
_AI_DESTRUCTIVE_PATTERNS=[
    re.compile(r"\brm\s+(-[a-z]*\s+)*-[a-z]*[rf]",re.I),
    re.compile(r"\bdd\s+.*\bof=/dev/",re.I),
    re.compile(r"\bmkfs(\.[a-z0-9]+)?\b",re.I),
    re.compile(r"\b(shutdown|reboot|halt|poweroff)\b",re.I),
    re.compile(r"\bformat\s+[a-z]:",re.I),
    re.compile(r"\b(del|erase)\s+/[sq]",re.I),
    re.compile(r"\bRemove-Item\b.*-Recurse",re.I),
    re.compile(r"\b(curl|wget|iwr|Invoke-WebRequest)\b[^|]*\|\s*(sudo\s+)?(ba)?sh\b",re.I),
    re.compile(r"\|\s*iex\b",re.I),
    re.compile(r"\bchmod\s+(-R\s+)?777\b",re.I),
    re.compile(r"\b(sudo|doas|runas|pkexec)\b",re.I),
    re.compile(r":\(\)\s*\{.*\};\s*:",re.S),
]
def command_is_destructive(command):
    text=str(command or "")
    return any(pattern.search(text) for pattern in _AI_DESTRUCTIVE_PATTERNS)
_ai_requests={}
_ai_lock=threading.Lock()
def _ai_request_row(record):
    return {k:v for k,v in record.items() if k!="job_key"} if record else None
def request_ai_command(command,shell_id="",reason="",mode="ask"):
    text=str(command or "").strip()
    if not text:raise ValueError("No command was supplied.")
    destructive=command_is_destructive(text)
    auto=mode=="allow" and not destructive
    request_id="air"+uuid.uuid4().hex[:11]
    record={"request_id":request_id,"command":text,"shell_id":str(shell_id or ""),"reason":str(reason or "")[:400],"destructive":destructive,"state":"approved" if auto else "pending","requested_at":_job_now(),"job_key":None,"auto":auto}
    with _ai_lock:
        if len(_ai_requests)>=_AI_REQUEST_LIMIT:
            stale=[k for k,v in _ai_requests.items() if v["state"] not in("pending","running")]
            for key in stale[:max(1,len(stale)//2)]:_ai_requests.pop(key,None)
        _ai_requests[request_id]=record
    if auto:_launch_ai_request(request_id)
    return _ai_request_row(dict(record))
def _launch_ai_request(request_id):
    with _ai_lock:
        record=_ai_requests.get(request_id)
        if not record or record["state"] not in("approved",):return None
        command=record["command"]
        shell_id=record["shell_id"]
    started=start_batch(shell_id,[{"command":command,"label":"AI"}],1,"ai")
    job_key=started["job_keys"][0]
    with _ai_lock:
        record=_ai_requests.get(request_id)
        if record:
            record["job_key"]=job_key
            record["state"]="running"
    return job_key
def list_ai_requests(pending_only=False):
    with _ai_lock:
        rows=[dict(record) for record in _ai_requests.values()]
    rows.sort(key=lambda r:r["requested_at"])
    if pending_only:rows=[r for r in rows if r["state"]=="pending"]
    return [_ai_request_row(r) for r in rows]
def resolve_ai_request(request_id,approved):
    with _ai_lock:
        record=_ai_requests.get(str(request_id or ""))
        if not record or record["state"]!="pending":return None
        record["state"]="approved" if approved else "denied"
        record["resolved_at"]=_job_now()
    if approved:_launch_ai_request(request_id)
    with _ai_lock:
        record=_ai_requests.get(str(request_id or ""))
        return _ai_request_row(dict(record)) if record else None
def ai_request_status(request_id):
    with _ai_lock:
        record=_ai_requests.get(str(request_id or ""))
        if not record:return None
        row=_ai_request_row(dict(record))
        job_key=record["job_key"]
    if not job_key:return row
    job=get_job(job_key)
    if job:
        row["job_state"]=job["state"]
        row["exit_code"]=job["exit_code"]
        if job["state"] not in("running","pending"):
            row["state"]="finished"
            row["output"]=batch_output(job_key)
            with _ai_lock:
                if request_id in _ai_requests:_ai_requests[request_id]["state"]="finished"
    return row
def clear_ai_requests():
    with _ai_lock:_ai_requests.clear()
    return True
_SECRET_PATTERNS=[
    (re.compile(r"(-{1,2}(?:pass|password|passwd|pwd)[ =]+)(\S+)",re.I),"password"),
    # (?<![\w-]): only a real -p option, never the "-p" inside --protocols / --port-range / ssh-pass.
    (re.compile(r"((?<![\w-])-p[ =]?)(?!(?:-|\d{1,5}(?:[-,:.]\d{1,5})*-?)(?:\s|$))(\S+)"),"password flag"),
    # curl -u user:pass / --user user:pass, smbclient -U user%pass, impacket -hashes LM:NT.
    (re.compile(r"((?<![\w-])(?:-u|--user|--proxy-user)[ =]+['\"]?[^:\s'\"]+:)([^\s'\"]+)"),"user:password"),
    (re.compile(r"((?<![\w-])-U[ =]+['\"]?[^%\s'\"]+%)([^\s'\"]+)"),"user%password"),
    (re.compile(r"((?<![\w-])-{1,2}hashes[ =]+)(\S+)",re.I),"ntlm hashes"),
    (re.compile(r"((?:api[_-]?key|apikey|token|secret|access[_-]?key|client[_-]?secret|password|passwd|passphrase)\s*[:=]\s*)(\S+)",re.I),"credential"),
    (re.compile(r"(Authorization:\s*(?:Bearer|Basic)\s+)(\S+)",re.I),"authorization header"),
    (re.compile(r"(-----BEGIN [A-Z ]*PRIVATE KEY-----)[\s\S]*?(-----END [A-Z ]*PRIVATE KEY-----)"),"private key"),
    # Any scheme with user:password@ (https://u:p@host, ftp://, smb://, mysql://...), and impacket's domain/user:password@host.
    (re.compile(r"(\b[a-z][a-z0-9+.-]{1,20}://[^:@/\s]+:)([^@\s]+)(@)",re.I),"connection string"),
    (re.compile(r"((?<![\w/:.-])[\w.-]{1,64}/[\w.$-]{1,64}:)([^@\s]+)(@[\w.-])"),"connection string"),
    (re.compile(r"(\bAWS_SECRET_ACCESS_KEY\s*=\s*)(\S+)",re.I),"aws secret"),
    (re.compile(r"(:\s*)(\$[0-9a-z]\$[^\s:]{10,})",re.I),"password hash"),
]
_REDACTION="[redacted]"
def redact_secrets(text):
    if not text:return "",[]
    out=str(text)
    found=[]
    for pattern,label in _SECRET_PATTERNS:
        if label=="private key":
            out,count=pattern.subn(lambda m:m.group(1)+_REDACTION+m.group(2),out)
        elif label=="connection string":
            out,count=pattern.subn(lambda m:m.group(1)+_REDACTION+m.group(3),out)
        else:
            out,count=pattern.subn(lambda m:m.group(1)+_REDACTION,out)
        if count:found.append({"kind":label,"count":count})
    return out,found
def audit_command(command,source="terminal",session_id="",exit_code=None):
    try:
        from Cores.Services import security_service as _security
    except Exception:
        return False
    safe,found=redact_secrets(command)
    detail=safe if not found else safe+"  [redacted: "+", ".join(f["kind"] for f in found)+"]"
    try:
        _security.log_audit_event("terminal_command",f"{source}:{session_id or '-'} {detail}"[:1000],exit_code in (None,0))
        return True
    except Exception:
        return False
_EXPORT_ANSI_COLORS={"black":"#6b7280","red":"#f87171","green":"#4ade80","yellow":"#facc15","blue":"#60a5fa","magenta":"#e879f9","cyan":"#22d3ee","white":"#e5e7eb","brblack":"#9ca3af","brred":"#fca5a5","brgreen":"#86efac","bryellow":"#fde047","brblue":"#93c5fd","brmagenta":"#f0abfc","brcyan":"#67e8f9","brwhite":"#f9fafb"}
def _export_styles():
    rules=["body{margin:0;padding:24px;background:#05060a;color:#eaf6ff;font-family:Consolas,'Courier New',monospace;font-size:13px;line-height:1.5}","h1{font-size:15px;font-weight:700;margin:0 0 14px;color:#9fb3c8}","pre{margin:0;white-space:pre-wrap;word-break:break-word}",".ansi-bold{font-weight:700}",".ansi-dim{opacity:0.65}",".ansi-italic{font-style:italic}",".ansi-underline{text-decoration:underline}",".term-ioc{text-decoration:underline dotted}"]
    for name,color in _EXPORT_ANSI_COLORS.items():
        rules.append(".ansi-fg-%s{color:%s}"%(name,color))
        rules.append(".ansi-bg-%s{background:%s3d}"%(name,color))
    return "".join(rules)
def render_export_html(title,body_html):
    safe_title=str(title or "Terminal session").replace("<","&lt;").replace(">","&gt;")
    return "<!DOCTYPE html><html><head><meta charset=\"utf-8\"><title>"+safe_title+"</title><style>"+_export_styles()+"</style></head><body><h1>"+safe_title+"</h1><pre>"+(body_html or "")+"</pre></body></html>"
def _settings_path():return os.path.join(common_db.data_dir(),"settings.json")
def _read_settings():
    try:
        with open(_settings_path(),"r",encoding="utf-8") as f:
            d=json.load(f)
        return d if isinstance(d,dict) else {}
    except Exception:
        return {}
def _write_settings(d):
    p=_settings_path()
    os.makedirs(os.path.dirname(p),exist_ok=True)
    tmp=p+".tmp"
    with open(tmp,"w",encoding="utf-8") as f:json.dump(d,f,ensure_ascii=False,indent=2)
    os.replace(tmp,p)
def _extensions(d):
    ext=d.get("extensions",{})
    return ext if isinstance(ext,dict) else {}
CLICK_ACTIONS=("copy","run","insert","ask")
CONFIRM_MODES=("always","risky","never")
RUN_DESTINATIONS=("active","new","pick")
_RUN_DEFAULTS={"snippet_click_action":"copy","snippet_run_confirm":"risky","command_click_action":"copy","command_run_confirm":"risky","run_destination":"active"}
_RUN_CHOICES={"snippet_click_action":CLICK_ACTIONS,"snippet_run_confirm":CONFIRM_MODES,"command_click_action":CLICK_ACTIONS,"command_run_confirm":CONFIRM_MODES,"run_destination":RUN_DESTINATIONS}
def _run_behaviour(ext):
    out={}
    for key,default in _RUN_DEFAULTS.items():
        value=str(ext.get("terminal_"+key,"") or "").strip().lower()
        out[key]=value if value in _RUN_CHOICES[key] else default
    return out
_PANEL_MODES=("right","left","bottom")
def _clamp_int(value,low,high,default):
    try:return max(low,min(high,int(value)))
    except Exception:return default
def _panel_mode(ext):
    mode=str(ext.get("terminal_panel_mode","") or "").strip().lower()
    return mode if mode in _PANEL_MODES else "right"
def get_settings():
    ext=_extensions(_read_settings())
    settings={"enabled":bool(ext.get("terminal_enabled",False)),"panel_width":_clamp_int(ext.get("terminal_width",380),260,900,380),"panel_height":_clamp_int(ext.get("terminal_panel_height",320),160,1200,320),"panel_mode":_panel_mode(ext),"panel_maximized":bool(ext.get("terminal_panel_maximized",False)),"confirm_multiline_paste":bool(ext.get("terminal_confirm_multiline_paste",True)),"use_conpty":bool(ext.get("terminal_use_conpty",False)),"conpty_supported":conpty_supported()}
    settings.update(_run_behaviour(ext))
    settings["suggest_enabled"]=bool(ext.get("terminal_suggest_enabled",True))
    settings["font_size"]=_clamp_int(ext.get("terminal_font_size",12),9,22,12)
    settings["shortcuts"]=_shortcuts(ext)
    settings["platform"]="windows" if _IS_WINDOWS else "linux"
    settings["default_shell_choice"]=str(ext.get("terminal_default_shell","") or "").strip()[:80] or DEFAULT_SHELL_AUTO
    return settings
def set_run_behaviour(values):
    values=values if isinstance(values,dict) else {}
    with _settings_lock:
        d=_read_settings()
        ext=_extensions(d)
        for key,choices in _RUN_CHOICES.items():
            if key not in values:continue
            value=str(values.get(key) or "").strip().lower()
            if value in choices:ext["terminal_"+key]=value
        if "confirm_multiline_paste" in values:ext["terminal_confirm_multiline_paste"]=bool(values.get("confirm_multiline_paste"))
        if "use_conpty" in values:ext["terminal_use_conpty"]=bool(values.get("use_conpty"))
        if "suggest_enabled" in values:ext["terminal_suggest_enabled"]=bool(values.get("suggest_enabled"))
        d["extensions"]=ext
        _write_settings(d)
    return get_settings()
def set_enabled(enabled):
    with _settings_lock:
        d=_read_settings()
        ext=_extensions(d)
        ext["terminal_enabled"]=bool(enabled)
        d["extensions"]=ext
        _write_settings(d)
    return get_settings()
def set_panel_width(width):
    return set_panel_layout({"width":width})
def set_panel_layout(values):
    values=values if isinstance(values,dict) else {}
    with _settings_lock:
        d=_read_settings()
        ext=_extensions(d)
        if "mode" in values:
            mode=str(values.get("mode") or "").strip().lower()
            if mode in _PANEL_MODES:ext["terminal_panel_mode"]=mode
        if "width" in values:ext["terminal_width"]=_clamp_int(values.get("width"),260,900,380)
        if "height" in values:ext["terminal_panel_height"]=_clamp_int(values.get("height"),160,1200,320)
        if "maximized" in values:ext["terminal_panel_maximized"]=bool(values.get("maximized"))
        if "font_size" in values:ext["terminal_font_size"]=_clamp_int(values.get("font_size"),9,22,12)
        d["extensions"]=ext
        _write_settings(d)
    return get_settings()
SHORTCUT_DEFAULTS={"suggest":"Ctrl+Space","toggle_suggest":"Ctrl+Shift+Space","command_search":"Ctrl+Shift+P","reopen_closed":"Ctrl+Shift+T","pane_left":"Alt+ArrowLeft","pane_right":"Alt+ArrowRight","pane_up":"Alt+ArrowUp","pane_down":"Alt+ArrowDown"}
_SHORTCUT_MODS=("Ctrl","Alt","Shift")
_SHORTCUT_NAMED={"space":"Space","enter":"Enter","tab":"Tab","escape":"Escape","esc":"Escape","backspace":"Backspace","delete":"Delete","insert":"Insert","home":"Home","end":"End","pageup":"PageUp","pagedown":"PageDown","arrowup":"ArrowUp","arrowdown":"ArrowDown","arrowleft":"ArrowLeft","arrowright":"ArrowRight","up":"ArrowUp","down":"ArrowDown","left":"ArrowLeft","right":"ArrowRight"}
_SHORTCUT_RESERVED={m+k for m in ("Ctrl+","Ctrl+Shift+") for k in "CDZLRUWAEFKVXY/"}|{"Ctrl+"+k for k in "123456789"}|{"Ctrl+Tab","Ctrl+Shift+Tab","Ctrl+Shift+Enter","Ctrl+ArrowUp","Ctrl+ArrowDown","Ctrl+Alt+T","Ctrl+Alt+Delete","Ctrl+Alt+L","Alt+Tab","Alt+F4","F11"}|{"Ctrl+Alt+"+k for k in ("ArrowLeft","ArrowRight","ArrowUp","ArrowDown")}
def normalize_shortcut(value):
    parts=[p.strip() for p in str(value or "").replace(" ","").split("+")]
    if len(parts)>1 and parts[-1]=="" and parts[-2]=="":parts=parts[:-2]+["+"]
    parts=[p for p in parts if p]
    if not parts:return ""
    mods=set();key=None
    for part in parts:
        low=part.lower()
        if low in ("ctrl","control"):mods.add("Ctrl")
        elif low=="alt":mods.add("Alt")
        elif low=="shift":mods.add("Shift")
        elif low in ("meta","super","win","cmd","os"):return None
        elif key is not None:return None
        elif low in _SHORTCUT_NAMED:key=_SHORTCUT_NAMED[low]
        elif re.fullmatch(r"f([1-9]|1[0-2])",low):key=low.upper()
        elif len(part)==1 and part.isprintable():key=part.upper()
        else:return None
    if key is None:return None
    if not mods.intersection({"Ctrl","Alt"}) and not re.fullmatch(r"F\d+",key):return None
    return "+".join([m for m in _SHORTCUT_MODS if m in mods]+[key])
def shortcut_conflict(combo):
    if combo in _SHORTCUT_RESERVED:return combo+" is already used by the terminal, the app or the desktop."
    return ""
def _shortcuts(ext):
    saved=ext.get("terminal_shortcuts")
    saved=saved if isinstance(saved,dict) else {}
    out={}
    for action,default in SHORTCUT_DEFAULTS.items():
        if action not in saved:out[action]=default;continue
        combo=normalize_shortcut(saved.get(action))
        out[action]=combo if combo is not None and not (combo and shortcut_conflict(combo)) else default
    return out
def set_shortcuts(values):
    values=values if isinstance(values,dict) else {}
    with _settings_lock:
        d=_read_settings()
        ext=_extensions(d)
        merged=_shortcuts(ext)
        for action in SHORTCUT_DEFAULTS:
            if action not in values:continue
            raw=values.get(action)
            combo=SHORTCUT_DEFAULTS[action] if raw is None else normalize_shortcut(raw)
            if combo is None:raise ValueError(f"'{raw}' is not a usable shortcut. Use Ctrl or Alt with a key, or F1-F12.")
            reason=shortcut_conflict(combo) if combo else ""
            if reason:raise ValueError(reason)
            merged[action]=combo
        used={}
        for action,combo in merged.items():
            if not combo:continue
            if combo in used:raise ValueError(f"{combo} is assigned twice.")
            used[combo]=action
        ext["terminal_shortcuts"]=merged
        d["extensions"]=ext
        _write_settings(d)
    return get_settings()
_SHELL_FAMILIES={"linux shell":"posix","linux":"posix","bash":"posix","sh":"posix","zsh":"posix","shell":"posix","posix":"posix","powershell":"powershell","pwsh":"powershell","cmd":"cmd","batch":"cmd"}
def command_family(command_type):
    return _SHELL_FAMILIES.get(str(command_type or "").strip().lower(),"any")
def build_command_index(rows):
    out=[];seen=set()
    for row in rows or []:
        if not isinstance(row,dict):continue
        cmd=str(row.get("command") or "").strip()
        if not cmd or cmd.lower() in seen:continue
        seen.add(cmd.lower())
        ctype=str(row.get("command_type") or "").strip() or "other"
        out.append({"command":cmd,"title":str(row.get("title") or "").strip(),"category":str(row.get("category") or "").strip(),"sub":str(row.get("sub") or "").strip(),"tags":str(row.get("tags") or "").strip(),"type":ctype,"family":command_family(ctype),"noise_level":str(row.get("noise_level") or "normal").strip().lower(),"src":row.get("src") or "","id":row.get("id")})
    return out
def _index_signature(dbp):
    parts=[]
    for path in (dbp,dbp+"-wal"):
        try:
            st=os.stat(path)
            parts.append(f"{st.st_mtime_ns}:{st.st_size}")
        except OSError:parts.append("-")
    return "|".join(parts)
def command_index(known_sig=None):
    from Cores.Services import commands_service as _cmds
    dbp=_cmds._db_path()
    sig=_index_signature(dbp)
    if known_sig and known_sig==sig:return {"sig":sig,"unchanged":True}
    _path,rows=_cmds._load_cmds()
    return {"sig":_index_signature(dbp),"entries":build_command_index(rows)}
# Saved sessions, recently closed sessions and the split-pane workspace live in Data/terminal_sessions.json rather than
# settings.json: they carry scrollback text, and settings.json is re-read by every settings writer in the app.
# A dead process cannot be resurrected, so everything here describes how to start a FRESH shell (name, shell, cwd,
# startup commands) plus, optionally, old output to show above it as greyed history.
SAVED_SESSIONS_MAX=50
SAVED_STARTUP_MAX=2000
SAVED_SCROLLBACK_MAX=64*1024
CLOSED_SESSIONS_MAX=10
CLOSED_SCROLLBACK_MAX=32*1024
WORKSPACE_LAYOUTS={"single":1,"cols2":2,"rows2":2,"top1bottom2":3,"left2right1":3,"grid4":4}
_ANSI_STRIP_RE=re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[PX^_][\s\S]*?\x1b\\|\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[()*+][0-9A-Za-z]|\x1b[=>NOM78c]|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
def _sessions_path():return os.path.join(common_db.data_dir(),"terminal_sessions.json")
def _now_iso():return datetime.now(timezone.utc).isoformat(timespec="seconds")
def _short(value,limit):return str(value if value is not None else "").strip()[:limit]
def _clean_id(value):
    text=re.sub(r"[^0-9a-zA-Z_-]","",str(value or ""))[:32]
    return text or uuid.uuid4().hex[:12]
def clean_scrollback(text,limit):
    """Plain text only (escape sequences and control bytes stripped), secrets redacted, and only the newest `limit` characters."""
    if not text:return ""
    plain=_ANSI_STRIP_RE.sub("",str(text).replace("\r\n","\n"))
    plain="\n".join(line[line.rfind("\r")+1:] if "\r" in line else line for line in plain.split("\n"))
    if len(plain)>limit:
        plain=plain[-limit:]
        cut=plain.find("\n")
        if 0<=cut<200:plain=plain[cut+1:]
    plain,_found=redact_secrets(plain)
    return plain
def _clean_saved_session(raw):
    if not isinstance(raw,dict):return None
    name=_short(raw.get("name"),60)
    if not name:return None
    created=_short(raw.get("created"),40) or _now_iso()
    return {"id":_clean_id(raw.get("id")),"name":name,"shell_id":_short(raw.get("shell_id"),64),"profile_id":_short(raw.get("profile_id"),32),"cwd":_short(raw.get("cwd"),1024),"startup":str(raw.get("startup") or "").replace("\r\n","\n")[:SAVED_STARTUP_MAX],"scrollback":clean_scrollback(raw.get("scrollback"),SAVED_SCROLLBACK_MAX),"created":created,"updated":_short(raw.get("updated"),40) or created}
def _clean_closed_session(raw,keep_output=True):
    if not isinstance(raw,dict):return None
    return {"id":_clean_id(raw.get("id")),"name":_short(raw.get("name"),60) or "Terminal","shell_id":_short(raw.get("shell_id"),64),"profile_id":_short(raw.get("profile_id"),32),"cwd":_short(raw.get("cwd"),1024),"scrollback":clean_scrollback(raw.get("scrollback"),CLOSED_SCROLLBACK_MAX) if keep_output else "","closed_at":_short(raw.get("closed_at"),40) or _now_iso()}
def _clamp_ratio(value):
    try:value=float(value)
    except Exception:return 0.5
    if value!=value:return 0.5
    return round(max(0.1,min(0.9,value)),4)
def clean_workspace(raw):
    raw=raw if isinstance(raw,dict) else {}
    layout=str(raw.get("layout") or "single")
    if layout not in WORKSPACE_LAYOUTS:layout="single"
    ratios=raw.get("ratios") if isinstance(raw.get("ratios"),dict) else {}
    panes=[]
    for pane in (raw.get("panes") if isinstance(raw.get("panes"),list) else [])[:WORKSPACE_LAYOUTS[layout]]:
        if not isinstance(pane,dict):panes.append(None);continue
        panes.append({"name":_short(pane.get("name"),60),"shell_id":_short(pane.get("shell_id"),64),"profile_id":_short(pane.get("profile_id"),32),"cwd":_short(pane.get("cwd"),1024)})
    try:focus=int(raw.get("focus") or 0)
    except Exception:focus=0
    return {"layout":layout,"ratios":{"v":_clamp_ratio(ratios.get("v",0.5)),"h":_clamp_ratio(ratios.get("h",0.5))},"focus":max(0,min(WORKSPACE_LAYOUTS[layout]-1,focus)),"panes":panes}
def _read_sessions_store():
    from Cores.settings_lock import read_json
    d=read_json(_sessions_path(),{})
    return d if isinstance(d,dict) else {}
def _store_list(d,key,cleaner):
    items=d.get(key)
    return [x for x in (cleaner(item) for item in (items if isinstance(items,list) else [])) if x]
def _update_sessions_store(mutate):
    from Cores.settings_lock import update_json
    if not update_json(_sessions_path(),mutate):raise OSError("Could not write terminal_sessions.json.")
def sessions_state():
    d=_read_sessions_store()
    keep=d.get("remember_output") is not False
    return {"saved":_store_list(d,"saved",_clean_saved_session),"closed":_store_list(d,"closed",lambda x:_clean_closed_session(x,keep)),"workspace":clean_workspace(d.get("workspace")),"remember_output":keep}
def save_saved_session(raw):
    entry=_clean_saved_session(raw)
    if not entry:raise ValueError("A session name is required.")
    def mutate(d):
        items=_store_list(d,"saved",_clean_saved_session)
        for index,existing in enumerate(items):
            if existing["id"]==entry["id"]:
                # Editing without sending scrollback keeps the output that was saved with it, unless the caller clears it explicitly.
                if "scrollback" not in raw:entry["scrollback"]=existing.get("scrollback","")
                entry["created"]=existing.get("created") or entry["created"]
                entry["updated"]=_now_iso()
                items[index]=entry
                break
        else:
            if len(items)>=SAVED_SESSIONS_MAX:raise ValueError(f"You can keep up to {SAVED_SESSIONS_MAX} saved sessions. Delete one first.")
            items.append(entry)
        d["saved"]=items
    _update_sessions_store(mutate)
    return sessions_state()
def delete_saved_session(entry_id):
    key=str(entry_id or "")
    _update_sessions_store(lambda d:d.__setitem__("saved",[x for x in _store_list(d,"saved",_clean_saved_session) if x["id"]!=key]))
    return sessions_state()
def remember_closed_session(session_id,raw):
    raw=dict(raw) if isinstance(raw,dict) else {}
    live=session_cwd(session_id) if session_id else ""
    if live:raw["cwd"]=live
    raw["closed_at"]=_now_iso()
    raw["id"]=uuid.uuid4().hex[:12]
    def mutate(d):
        keep=d.get("remember_output") is not False
        entry=_clean_closed_session(raw,keep)
        d["closed"]=([entry]+_store_list(d,"closed",lambda x:_clean_closed_session(x,keep)))[:CLOSED_SESSIONS_MAX]
    _update_sessions_store(mutate)
    return sessions_state()
def pop_closed_session(entry_id=None):
    """Take one entry (the newest when entry_id is empty) off the recently closed list and return it, so reopening it twice opens two shells only on purpose."""
    key=str(entry_id or "")
    found={}
    def mutate(d):
        keep=d.get("remember_output") is not False
        items=_store_list(d,"closed",lambda x:_clean_closed_session(x,keep))
        for index,item in enumerate(items):
            if not key or item["id"]==key:
                found["entry"]=items.pop(index)
                break
        d["closed"]=items
    _update_sessions_store(mutate)
    state=sessions_state()
    state["entry"]=found.get("entry")
    return state
def forget_closed_session(entry_id=None):
    key=str(entry_id or "")
    _update_sessions_store(lambda d:d.__setitem__("closed",[] if not key else [x for x in _store_list(d,"closed",_clean_closed_session) if x["id"]!=key]))
    return sessions_state()
def set_remember_output(enabled):
    def mutate(d):
        d["remember_output"]=bool(enabled)
        if not enabled:d["closed"]=_store_list(d,"closed",lambda x:_clean_closed_session(x,False))
    _update_sessions_store(mutate)
    return sessions_state()
def set_workspace(raw):
    ws=clean_workspace(raw)
    _update_sessions_store(lambda d:d.__setitem__("workspace",ws))
    return ws
