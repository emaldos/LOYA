import os,sys,json,subprocess,threading,time,re,datetime,shutil
from pathlib import Path
try:
    from Cores.Update import APP_NAME as _UPDATE_APP_NAME
    from Cores.Update import DEFAULT_APP_VERSION as _DEFAULT_APP_VERSION
    from Cores.Update import ensure_runtime_files as _ensure_update_runtime
    from Cores.Update import get_app_version as _get_app_version
    from Cores.Update import recovery as _recovery
    from Cores.Update import sync_installed_version as _sync_installed_version
except Exception:
    _UPDATE_APP_NAME="LOYA NG"
    _DEFAULT_APP_VERSION="1.0.1"
    _recovery=None
    def _get_app_version():
        return _DEFAULT_APP_VERSION
    def _ensure_update_runtime(current_version=""):
        return {"version":_DEFAULT_APP_VERSION,"state":{}}
    def _sync_installed_version(version=""):
        return {}
def _abs(*p):
    return str(Path(__file__).resolve().parent.joinpath(*p))
DEFAULT_LOG_RETENTION_DAYS=30
def _read_settings_json():
    try:
        with open(_abs("Data","settings.json"),"r",encoding="utf-8") as f:
            d=json.load(f)
        return d if isinstance(d,dict) else {}
    except Exception:
        return {}
def _log_retention_days():
    try:
        v=int(_read_settings_json().get("log_retention_days",DEFAULT_LOG_RETENTION_DAYS))
        return v if v>0 else DEFAULT_LOG_RETENTION_DAYS
    except Exception:
        return DEFAULT_LOG_RETENTION_DAYS
_LOG_FILE=None
_VERBOSE=False
def _init_log(keep_days=None):
    global _LOG_FILE
    if keep_days is None:keep_days=_log_retention_days()
    try:
        log_dir=_abs("Logs")
        os.makedirs(log_dir,exist_ok=True)
        date=datetime.datetime.now().strftime("%Y-%m-%d")
        _LOG_FILE=os.path.join(log_dir,f"RunNote_{date}.log")
        cutoff=datetime.datetime.now()-datetime.timedelta(days=keep_days)
        for name in os.listdir(log_dir):
            if not (name.startswith("RunNote_") and name.endswith(".log")):
                continue
            try:
                fd=datetime.datetime.strptime(name[8:-4],"%Y-%m-%d")
                if fd<cutoff:
                    os.remove(os.path.join(log_dir,name))
            except Exception:
                pass
    except Exception:
        _LOG_FILE=None
def _log(msg,level="INFO"):
    if _VERBOSE:
        print(f"[{level}] {msg}")
    if not _LOG_FILE:
        return
    try:
        ts=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(_LOG_FILE,"a",encoding="utf-8") as f:
            f.write(f"[{ts}] [{level}] {msg}\n")
    except Exception:
        pass
def _is_win():
    return os.name=="nt"
def _console_python():
    py=os.path.abspath(sys.executable)
    if _is_win() and py.lower().endswith("pythonw.exe"):
        alt=py[:-5]+".exe"
        if os.path.isfile(alt):return alt
    return py
def _restart_self():
    script=_abs("RunNote.py")
    py=_console_python()
    try:
        if _is_win():
            subprocess.Popen([py,script],cwd=_abs(),stdin=subprocess.DEVNULL,creationflags=0x00000010)
        else:
            subprocess.Popen([py,script],cwd=_abs(),stdin=subprocess.DEVNULL,start_new_session=True)
        return True,"Launcher restarted."
    except Exception as e:
        return False,str(e)
_USAGE="""Usage: RunNote.py [options]
  --skip-update      skip the pip/dependency steps and start straight away
  --verbose          print launcher log lines to the console
  --recovery         open the recovery console instead of the app
  --reason TEXT      reason shown in the recovery console (with --recovery)
  --version          print the app version and exit
  -h, --help         show this help and exit"""
def _parse_args(argv):
    out={"force_recovery":False,"recovery_reason":"","skip_update":False,"verbose":False,"version":False,"help":False,"unknown":[]}
    i=0
    while i<len(argv):
        arg=str(argv[i] or "").strip()
        if arg=="--recovery":
            out["force_recovery"]=True
        elif arg=="--skip-update":
            out["skip_update"]=True
        elif arg=="--verbose":
            out["verbose"]=True
        elif arg=="--reason" and i+1<len(argv):
            i+=1;out["recovery_reason"]=str(argv[i] or "").strip()
        elif arg in ("--version","-V"):
            out["version"]=True
        elif arg in ("-h","--help"):
            out["help"]=True
        elif arg:
            out["unknown"].append(arg)
        i+=1
    return out
def _bootstrap_startup_state():
    try:
        from Cores.Update import health_check as _health_check
    except Exception as exc:
        return False,f"Failed to load startup health check ({exc})","",None
    try:
        report=_health_check.run_health_check(after_security=False)
    except Exception as exc:
        return False,f"Startup health check crashed ({exc})","",None
    if report.fatal:
        return False,report.fatal_text(),"",report
    notice=report.notice_text() if report.has_notice() else ""
    return True,"",notice,report
def _interactive():
    try:return bool(sys.stdin) and sys.stdin.isatty()
    except Exception:return False
def _run_recovery(force=False,reason="",report=None):
    if _recovery is None:
        return {"action":"continue","shown":False}
    try:
        ctx=_recovery.build_recovery_context(report=report,extra_reason=reason,root_dir=_abs())
        if not _recovery.needs_recovery(ctx,force):return {"action":"continue","shown":False,"context":ctx}
        # Started without a console (e.g. relaunched by the updater): the menu would read EOF and exit, so keep going and let
        # the startup check below decide; a fatal problem still stops the launch and is logged.
        if not force and not _interactive():
            _log("Recovery recommended but no console is attached; continuing ("+"; ".join(ctx.get("reasons") or [])+")","WARN")
            return {"action":"continue","shown":False,"context":ctx}
        out=_recovery.run_recovery_console(context=ctx,launcher_python=_console_python(),launcher_script=_abs("RunNote.py"),forced=force,extra_reason=reason)
        if not isinstance(out,dict):out={"action":"continue"}
        out["shown"]=True
        return out
    except Exception as exc:
        return {"action":"continue","shown":False,"error":f"Recovery mode failed to start ({exc})."}
def _launch_staged_update():
    # "Download in the background and install on next restart": the package was downloaded and verified while the app ran;
    # hand it to the apply helper now, before the app starts, so no file is in use (Windows) while it is replaced.
    try:
        from Cores.Update import update_service as _svc
    except Exception as exc:
        return {"started":False,"error":f"updater unavailable ({exc})"}
    try:
        if not _svc.staged_update_info():return {"started":False,"error":""}
        return _svc.launch_staged_update(parent_pid=os.getpid(),launcher_python=_console_python(),launcher_script=_abs("RunNote.py"))
    except Exception as exc:
        return {"started":False,"error":str(exc)}
def _py_ok(req):
    if not req:
        return True
    m=re.match(r"^\s*>=\s*(\d+)\.(\d+)",str(req))
    if not m:
        return True
    maj,mi=int(m.group(1)),int(m.group(2))
    return (sys.version_info.major,sys.version_info.minor)>=(maj,mi)
def _read_requirements(p):
    d=None
    try:
        if os.path.isfile(p):
            with open(p,"r",encoding="utf-8") as f:
                d=json.load(f)
    except Exception:
        d=None
    if not isinstance(d,dict):
        d={
            "python":{"requires":">=3.10"},
            "pip":{"packages":[
                {"name":"cryptography","version":"==48.0.1"},
                {"name":"pywebview","version":"==6.2.1","linux_extra":"gtk"}
            ]}
        }
    py_req=((d.get("python") or {}).get("requires") if isinstance(d.get("python"),dict) else "")
    pkgs=((d.get("pip") or {}).get("packages") if isinstance(d.get("pip"),dict) else [])
    out=[]
    if isinstance(pkgs,list):
        for it in pkgs:
            if not isinstance(it,dict):
                continue
            n=str(it.get("name","") or "").strip()
            v=str(it.get("version","") or "").strip()
            extra=str(it.get("linux_extra","") or "").strip()
            if not n:
                continue
            if extra and not _is_win():
                n=f"{n}[{extra}]"
            out.append(n+v)
    return py_req,out
# ---------------------------------------------------------------- console look (banner, colours, status lines)
# Colours only on a real terminal; NO_COLOR turns them off, FORCE_COLOR forces them on. Windows 10+ consoles get ANSI
# processing switched on first. Box/block glyphs are used only when the console encoding can print them.
_UI={"color":None,"truecolor":False,"unicode":None}
def _ui_enable_windows_vt():
    try:
        import ctypes
        k=ctypes.windll.kernel32
        h=k.GetStdHandle(-11)
        mode=ctypes.c_ulong()
        if not k.GetConsoleMode(h,ctypes.byref(mode)):return False
        return bool(k.SetConsoleMode(h,mode.value|0x0004))
    except Exception:
        return False
def _ui_color():
    if _UI["color"] is None:
        env=os.environ
        if env.get("NO_COLOR"):on=False
        elif env.get("FORCE_COLOR"):on=True
        else:
            try:on=sys.stdout.isatty() and env.get("TERM","")!="dumb"
            except Exception:on=False
        if on and _is_win():on=_ui_enable_windows_vt() or bool(env.get("WT_SESSION") or env.get("FORCE_COLOR"))
        _UI["color"]=on
        _UI["truecolor"]=on and (env.get("COLORTERM","").lower() in ("truecolor","24bit") or bool(env.get("WT_SESSION")))
    return _UI["color"]
def _ui_unicode():
    if _UI["unicode"] is None:
        try:
            "█╔═⠋".encode(sys.stdout.encoding or "ascii")
            _UI["unicode"]=True
        except Exception:
            _UI["unicode"]=False
    return _UI["unicode"]
_SGR={"reset":"0","bold":"1","dim":"2","italic":"3","red":"31","green":"32","yellow":"33","blue":"34","magenta":"35","cyan":"36","white":"97","grey":"90"}
def _c(text,*styles):
    if not _ui_color() or not styles:return str(text)
    return "\x1b["+";".join(_SGR.get(x,x) for x in styles)+"m"+str(text)+"\x1b[0m"
def _ui_rgb(r,g,b):
    if _UI["truecolor"]:return f"38;2;{r};{g};{b}"
    return "38;5;"+str(16+36*round(r/255*5)+6*round(g/255*5)+round(b/255*5))
_LOGO_LETTERS={
"L":["██╗     ","██║     ","██║     ","██║     ","███████╗","╚══════╝"],
"O":[" ██████╗ ","██╔═══██╗","██║   ██║","██║   ██║","╚██████╔╝"," ╚═════╝ "],
"Y":["██╗   ██╗","╚██╗ ██╔╝"," ╚████╔╝ ","  ╚██╔╝  ","   ██║   ","   ╚═╝   "],
"A":[" █████╗ ","██╔══██╗","███████║","██╔══██║","██║  ██║","╚═╝  ╚═╝"],
"N":["███╗   ██╗","████╗  ██║","██╔██╗ ██║","██║╚██╗██║","██║ ╚████║","╚═╝  ╚═══╝"],
"G":[" ██████╗ ","██╔════╝ ","██║  ███╗","██║   ██║","╚██████╔╝"," ╚═════╝ "],
" ":["   "]*6}
def _ui_logo_rows():
    return ["".join(_LOGO_LETTERS[ch][i] for ch in "LOYA NG") for i in range(6)]
def _ui_gradient(row,width):
    # App accent blue (#3b82f6) to violet (#a855f7) across the logo.
    a,b=(59,130,246),(168,85,247)
    out=[]
    for i,ch in enumerate(row):
        if ch==" ":out.append(ch);continue
        t=i/max(1,width-1)
        out.append("\x1b["+_ui_rgb(*(round(a[k]+(b[k]-a[k])*t) for k in range(3)))+";1m"+ch)
    return "".join(out)+"\x1b[0m"
def _ui_banner(version):
    print()
    if _ui_unicode():
        rows=_ui_logo_rows();w=max(len(r) for r in rows)
        for r in rows:print("  "+(_ui_gradient(r,w) if _ui_color() else r))
    else:
        print("  "+_c("L O Y A   N G","bold","blue"))
    print("  "+_c("Language Of Your Attack","italic","grey"))
    import platform
    info=f"v{version}  |  Python {sys.version.split()[0]}  |  {platform.system()} {platform.machine()}  |  {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"
    print("  "+_c(info,"dim"))
    print("  "+_c("-"*len(info),"grey"))
_STATUS={"ok":("  OK  ","green"),"warn":(" WARN ","yellow"),"fail":("FAILED","red"),"info":(" INFO ","cyan"),"skip":(" SKIP ","grey"),"wait":(" .... ","cyan")}
def _status_tag(kind):
    word,col=_STATUS.get(kind,_STATUS["info"])
    return _c("[","bold")+_c(word,"bold",col)+_c("]","bold")
def _step(kind,msg,tail=""):
    line=f"{_status_tag(kind)} {msg}"
    if tail:line+=" "+_c(tail,"dim")
    sys.stdout.write(line+"\n");sys.stdout.flush()
def _ui_error(msg):
    sys.stdout.write(f"{_status_tag('fail')} {_c('ERROR:','bold','red')} {msg}\n");sys.stdout.flush()
def _ui_warning(msg):
    sys.stdout.write(f"{_status_tag('warn')} {_c('WARNING:','bold','yellow')} {msg}\n");sys.stdout.flush()
class _Spinner:
    def __init__(self):
        self._stop=threading.Event()
        self._t=None
        self._msg=""
        self._ok=None
    def start(self,msg):
        self._msg=msg
        self._ok=None
        self._stop.clear()
        self._t=threading.Thread(target=self._run,daemon=True)
        self._t.start()
    def _run(self):
        try:live=sys.stdout.isatty()
        except Exception:live=False
        if not live:return   # no animation in pipes/logs; stop() prints the final line
        frames=list("\u280b\u2819\u2839\u2838\u283c\u2834\u2826\u2827\u2807\u280f") if _ui_unicode() else ["|","/","-","\\"]
        i=0;t0=time.time()
        while not self._stop.is_set():
            f=frames[i%len(frames)]
            i+=1
            sys.stdout.write("\r"+_c("[","bold")+_c(f" {f}{f}{f}{f} ","bold","cyan")+_c("]","bold")+f" {self._msg} "+_c(f"{time.time()-t0:.1f}s","dim")+"   ")
            sys.stdout.flush()
            time.sleep(0.08)
    def stop(self,ok=True,tail=""):
        self._ok=ok
        self._stop.set()
        if self._t:
            self._t.join(timeout=0.5)
        try:live=sys.stdout.isatty()
        except Exception:live=False
        line=f"{_status_tag('ok' if ok else 'fail')} {self._msg}"
        if tail:line+=" "+_c(tail,"dim")
        sys.stdout.write(("\r\x1b[2K" if live and _ui_color() else ("\r" if live else ""))+line+(" "*8 if live and not _ui_color() else "")+"\n")
        sys.stdout.flush()
def _run(cmd,spinner_msg=None,env=None,cwd=None):
    sp=_Spinner()
    t0=time.time()
    if spinner_msg:
        sp.start(spinner_msg)
    p=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,env=env,cwd=cwd)
    out=[]
    try:
        for line in p.stdout:
            if line:
                out.append(line.rstrip("\n"))
    except Exception:
        pass
    rc=p.wait()
    if spinner_msg:
        sp.stop(rc==0,tail=f"({time.time()-t0:.1f}s)")
    return rc,"\n".join(out[-30:])
def _venv_paths(venv_dir):
    if _is_win():
        py=os.path.join(venv_dir,"Scripts","python.exe")
        pyw=os.path.join(venv_dir,"Scripts","pythonw.exe")
        pip=os.path.join(venv_dir,"Scripts","pip.exe")
    else:
        py=os.path.join(venv_dir,"bin","python3")
        pyw=""
        pip=os.path.join(venv_dir,"bin","pip3")
    return py,pyw,pip
def _make_hidden_windows(p):
    if not _is_win():
        return
    try:
        subprocess.run(["attrib","+h",p],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    except Exception:
        pass
def _venv_sees_system_site(venv_dir):
    cfg=os.path.join(venv_dir,"pyvenv.cfg")
    try:
        with open(cfg,"r",encoding="utf-8") as f:
            for line in f:
                k,_,v=line.partition("=")
                if k.strip().lower()=="include-system-site-packages":
                    return v.strip().lower()=="true"
    except Exception:
        pass
    return False
def _ensure_venv(venv_dir):
    if os.path.isdir(venv_dir):
        return True,""
    cmd=[sys.executable,"-m","venv"]
    if not _is_win():
        cmd.append("--system-site-packages")
    cmd.append(venv_dir)
    rc,tail=_run(cmd,f"Creating venv ({os.path.basename(venv_dir)})")
    if rc!=0:
        shutil.rmtree(venv_dir,ignore_errors=True)
        return False,tail
    _make_hidden_windows(venv_dir)
    return True,""
def _pip_trusted_host_args():
    return ["--trusted-host","pypi.org","--trusted-host","files.pythonhosted.org","--trusted-host","pypi.python.org"]
def _pip_is_functional(py):
    rc,_=_run([py,"-m","pip","--version"],None)
    return rc==0
def _is_ssl_error(text):
    return any(k in text for k in ("SSLError","CERTIFICATE_VERIFY_FAILED","ssl.SSLError"))
def _ensure_pip(py):
    rc,tail=_run([py,"-m","pip","install","-U","pip"],"Updating pip")
    if rc==0:
        return True,tail
    if _is_ssl_error(tail):
        rc2,tail2=_run([py,"-m","pip","install","-U","pip"]+_pip_trusted_host_args(),"Updating pip (trusted hosts)")
        if rc2==0:
            return True,tail2
        if _pip_is_functional(py):
            _log("pip upgrade failed due to SSL/certificate issue in certificate chain; existing pip will be used\n"+tail2,"WARN")
            _ui_warning("pip upgrade skipped (SSL certificate issue); existing pip will be used")
            return True,""
        _log("pip upgrade failed (SSL); pip also not functional\n"+tail2,"ERROR")
        return False,tail2
    _log("pip upgrade failed\n"+tail,"ERROR")
    return False,tail
def _ensure_deps(py,reqs):
    if not reqs:
        return True,""
    cmd=[py,"-m","pip","install","--upgrade","--upgrade-strategy","only-if-needed"]+reqs
    rc,tail=_run(cmd,"Installing/Updating requirements")
    if rc==0:
        return True,tail
    if _is_ssl_error(tail):
        rc2,tail2=_run(cmd+_pip_trusted_host_args(),"Installing/Updating requirements (trusted hosts)")
        if rc2==0:
            return True,tail2
        _log("deps install failed (SSL trusted-host fallback)\n"+tail2,"ERROR")
        return False,tail2
    _log("deps install failed\n"+tail,"ERROR")
    return False,tail
def _deps_fingerprint(reqs):
    import hashlib
    return hashlib.sha256("|".join(sorted(reqs)).encode()).hexdigest()[:16]
def _load_deps_state():
    path=_abs("Data","deps_state.json")
    try:
        with open(path,"r",encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}
def _save_deps_state(reqs):
    path=_abs("Data","deps_state.json")
    try:
        os.makedirs(os.path.dirname(path),exist_ok=True)
        with open(path,"w",encoding="utf-8") as f:
            json.dump({"fingerprint":_deps_fingerprint(reqs),"ts":datetime.datetime.now().isoformat()},f)
    except Exception:
        pass
def _deps_up_to_date(reqs):
    if not reqs:
        return True
    return _load_deps_state().get("fingerprint")==_deps_fingerprint(reqs)
_WEBVIEW2_CLIENT_GUID="{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
def _webview2_info():
    info={"ok":False,"version":""}
    try:
        import winreg
    except Exception:
        return info
    key_paths=(
        (winreg.HKEY_LOCAL_MACHINE,r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\%s"%_WEBVIEW2_CLIENT_GUID),
        (winreg.HKEY_LOCAL_MACHINE,r"SOFTWARE\Microsoft\EdgeUpdate\Clients\%s"%_WEBVIEW2_CLIENT_GUID),
        (winreg.HKEY_CURRENT_USER,r"SOFTWARE\Microsoft\EdgeUpdate\Clients\%s"%_WEBVIEW2_CLIENT_GUID),
    )
    for hive,key_path in key_paths:
        try:
            with winreg.OpenKey(hive,key_path) as key:
                try:
                    info["version"]=str(winreg.QueryValueEx(key,"pv")[0] or "").strip()
                except OSError:
                    info["version"]=""
                if info["version"]:
                    info["ok"]=True
                    return info
        except OSError:
            continue
    return info
def _check_linux_webview_runtime(py):
    code=(
        "import sys,traceback\n"
        "try:\n"
        "    import gi\n"
        "    try:\n"
        "        gi.require_version('WebKit2','4.1')\n"
        "    except ValueError:\n"
        "        gi.require_version('WebKit2','4.0')\n"
        "    from gi.repository import WebKit2\n"
        "except Exception:\n"
        "    traceback.print_exc()\n"
        "    sys.exit(1)\n"
        "print('WEBVIEW_IMPORT_OK')\n"
    )
    rc,tail=_run([py,"-c",code],"Verifying WebKitGTK runtime")
    return rc==0,tail
def _check_webview_runtime(py):
    if _is_win():
        info=_webview2_info()
        return bool(info.get("ok")),""
    return _check_linux_webview_runtime(py)
def _webview_runtime_help(tail=""):
    lines=[]
    if _is_win():
        lines.append("Microsoft Edge WebView2 Runtime was not detected.")
        lines.append("LOYA NG needs the WebView2 Runtime to display its interface.")
        lines.append("Most Windows 10/11 machines already have it via Microsoft Edge; install or repair the WebView2 Runtime, then run LOYA NG again.")
    else:
        lines.append("WebKitGTK bindings were not found for this Python environment.")
        lines.append("LOYA NG needs GTK's WebKit2 bindings to display its interface.")
        lines.append("Install them, e.g. on Debian/Ubuntu:")
        lines.append("  sudo apt install python3-gi gir1.2-webkit2-4.1 gobject-introspection")
        lines.append("(use gir1.2-webkit2-4.0 instead of 4.1 on older distros)")
    if tail:
        lines.append("")
        lines.append("Import traceback:")
        lines.append(tail)
    return "\n".join(lines).strip()
def _linux_app_env():
    # The DMA-BUF renderer paints a blank white window on virtualised GL (vmwgfx). Disabling it outright
    # also drops WebKit to the non-composited path, where backdrop-filter is ignored and every glass
    # surface turns see-through. Shared-memory frames avoid the blank window and keep compositing on.
    # With shared-memory frames, Skia's GPU painter intermittently leaves stale tiles behind composited
    # backdrop-filter layers (old card edges stay on screen after a resize or page switch); its CPU painter
    # does not, and costs no more here since every frame is copied to shared memory anyway.
    env=dict(os.environ)
    if "WEBKIT_DISABLE_DMABUF_RENDERER" not in env:env.setdefault("WEBKIT_DMABUF_RENDERER_FORCE_SHM","1")
    if env.get("WEBKIT_DMABUF_RENDERER_FORCE_SHM")=="1":env.setdefault("WEBKIT_SKIA_ENABLE_CPU_RENDERING","1")
    return env
APP_OUTPUT_LOG_MAX=2*1024*1024
def _app_output_log():
    """The app's stdout/stderr go to Logs/app_output.log (started fresh once it passes 2 MB), so an error printed before
    logging is set up, or by WebKit/GTK/WebView2 itself, is not lost. Falls back to discarding them."""
    try:
        d=_abs("Logs");os.makedirs(d,exist_ok=True)
        path=os.path.join(d,"app_output.log")
        mode="wb" if os.path.isfile(path) and os.path.getsize(path)>APP_OUTPUT_LOG_MAX else "ab"
        fh=open(path,mode)
        fh.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} launch ===\n".encode("utf-8"));fh.flush()
        return fh
    except Exception:
        return None
def _launch_app(py,pyw,app_path):
    if not os.path.isfile(app_path):
        return False,f"Missing file: {os.path.basename(app_path)}",0
    stdin=subprocess.DEVNULL
    out=_app_output_log()
    stdout=out if out is not None else subprocess.DEVNULL
    stderr=subprocess.STDOUT if out is not None else subprocess.DEVNULL
    try:
        return _spawn_app(py,pyw,app_path,stdin,stdout,stderr)
    finally:
        if out is not None:
            try:out.close()
            except Exception:pass
def _spawn_app(py,pyw,app_path,stdin,stdout,stderr):
    if _is_win():
        DETACHED_PROCESS=0x00000008
        CREATE_NEW_PROCESS_GROUP=0x00000200
        CREATE_NO_WINDOW=0x08000000
        flags=DETACHED_PROCESS|CREATE_NEW_PROCESS_GROUP|CREATE_NO_WINDOW
        exe=pyw if pyw and os.path.isfile(pyw) else py
        p=subprocess.Popen([exe,app_path],stdin=stdin,stdout=stdout,stderr=stderr,creationflags=flags,cwd=os.path.dirname(app_path))
    else:
        p=subprocess.Popen([py,app_path],stdin=stdin,stdout=stdout,stderr=stderr,start_new_session=True,cwd=os.path.dirname(app_path),env=_linux_app_env())
    return True,"",int(getattr(p,"pid",0) or 0)
_WIN_PROCESS_QUERY_LIMITED_INFORMATION=0x1000
_WIN_STILL_ACTIVE=259
def _win_process_info(pid):
    import ctypes
    kernel32=ctypes.windll.kernel32
    handle=kernel32.OpenProcess(_WIN_PROCESS_QUERY_LIMITED_INFORMATION,False,int(pid))
    if not handle:
        return False,""
    try:
        exit_code=ctypes.c_ulong(0)
        if not kernel32.GetExitCodeProcess(handle,ctypes.byref(exit_code)) or exit_code.value!=_WIN_STILL_ACTIVE:
            return False,""
        buf=ctypes.create_unicode_buffer(1024)
        size=ctypes.c_ulong(1024)
        exe=buf.value if kernel32.QueryFullProcessImageNameW(handle,0,buf,ctypes.byref(size)) else ""
        return True,exe
    finally:
        kernel32.CloseHandle(handle)
def _unix_process_info(pid):
    try:
        os.kill(int(pid),0)
    except OSError:
        return False,""
    ident=""
    try:
        ident=os.readlink(f"/proc/{int(pid)}/exe")
    except OSError:
        pass
    try:
        with open(f"/proc/{int(pid)}/cmdline","rb") as f:
            ident+=" "+f.read().decode("utf-8","ignore").replace("\x00"," ")
    except OSError:
        pass
    return True,ident
def _pid_is_loya(pid):
    try:
        pid=int(pid)
    except (TypeError,ValueError):
        return False
    if pid<=0:
        return False
    try:
        alive,ident=_win_process_info(pid) if _is_win() else _unix_process_info(pid)
    except Exception:
        return False
    if not alive:
        return False
    ident_norm=ident.lower().replace("\\","/")
    venv_norm=_abs(".venv_windows" if _is_win() else ".venv_linux").lower().replace("\\","/")
    return ident_norm.startswith(venv_norm) or "loya_note.py" in ident_norm
def _read_pid_file():
    try:
        with open(_abs("Data","loya.pid"),"r",encoding="utf-8") as f:
            return int(f.read().strip())
    except (OSError,ValueError):
        return None
def _write_pid_file(pid):
    path=_abs("Data","loya.pid")
    try:
        os.makedirs(os.path.dirname(path),exist_ok=True)
        with open(path,"w",encoding="utf-8") as f:
            f.write(str(pid))
    except OSError:
        pass
def _remove_pid_file():
    try:
        os.remove(_abs("Data","loya.pid"))
    except OSError:
        pass
def _check_already_running():
    pid=_read_pid_file()
    if pid is None:
        return False,0
    if _pid_is_loya(pid):
        return True,pid
    _log(f"Stale pid file ignored (PID: {pid})","WARN")
    _remove_pid_file()
    return False,0
def main():
    global _VERBOSE
    args=_parse_args(sys.argv[1:])
    # Informational flags must not start the app.
    if args.get("help"):
        print(_USAGE);return 0
    if args.get("version"):
        print(f"{_UPDATE_APP_NAME} v{_get_app_version()}");return 0
    for arg in args.get("unknown") or []:
        _ui_warning(f"unknown option {arg!r} ignored (see --help)")
    skip_update=bool(args.get("skip_update"))
    _VERBOSE=bool(args.get("verbose"))
    app_version=_get_app_version()
    try:
        _ensure_update_runtime(app_version)
        _sync_installed_version(app_version)
    except Exception as exc:
        _ui_warning(f"updater runtime init failed ({exc})")
    _init_log()
    _log(f"{_UPDATE_APP_NAME} v{app_version} starting (Python {sys.version.split()[0]})")
    if _VERBOSE:
        _log(f"Verbose mode active; log retention={_log_retention_days()}d")
    if skip_update:
        _log("--skip-update flag active; pip/deps steps will be skipped")
    _t_start=time.time()
    _ui_banner(app_version)
    req_path=_abs("Requirements.json")
    py_req,reqs=_read_requirements(req_path)
    if not _py_ok(py_req):
        msg=f"Python version not supported. Required: {py_req} | Current: {sys.version.split()[0]}"
        _log(msg,"ERROR")
        _ui_error(msg)
        return 2
    _step("ok",f"Python {sys.version.split()[0]} supported")
    force_recovery=bool(args.get("force_recovery"))
    recovery_reason=str(args.get("recovery_reason","") or "")
    while True:
        ok,msg,notice,report=_bootstrap_startup_state()
        rec=_run_recovery(force=force_recovery,reason=(recovery_reason or msg),report=report)
        if rec.get("error"):
            _log(str(rec.get("error")),"WARN")
            _ui_warning(str(rec.get("error")))
        act=str(rec.get("action","continue") or "continue").strip().lower()
        if act=="restart":
            rok,rmsg=_restart_self()
            _log(f"Restart: {rmsg}","INFO" if rok else "ERROR")
            _step("info",rmsg) if rok else _ui_error(rmsg)
            return 0 if rok else 10
        if act=="exit":
            _log("Exit requested by recovery","INFO")
            return 10
        if rec.get("shown"):
            force_recovery=False;recovery_reason=""
            continue
        force_recovery=False;recovery_reason=""
        if ok:
            if notice:_step("info",notice)
            break
        _log(f"Startup state validation failed: {msg}","ERROR")
        _ui_error("Startup state validation failed")
        print(msg)
        return 2
    running,old_pid=_check_already_running()
    if running:
        _log(f"Already running (PID: {old_pid})","WARN")
        _ui_warning(f"LOYA NG is already running (PID: {old_pid})")
        return 0
    staged=_launch_staged_update()
    if staged.get("started"):
        msg=f"Installing the downloaded update {staged.get('version','')} - LOYA NG starts again by itself when it is done."
        _log(msg)
        _step("info",msg)
        return 0
    if staged.get("error"):
        _log(f"Downloaded update not installed: {staged.get('error')}","WARN")
        _ui_warning("downloaded update not installed: "+str(staged.get("error")))
    venv_dir=_abs(".venv_windows" if _is_win() else ".venv_linux")
    _py_check=os.path.join(venv_dir,"Scripts","python.exe") if _is_win() else os.path.join(venv_dir,"bin","python3")
    stale_site=os.path.isdir(venv_dir) and not _is_win() and not _venv_sees_system_site(venv_dir)
    if os.path.isdir(venv_dir) and os.path.isfile(_py_check) and not stale_site:
        _step("ok","Virtual environment ready","(cached)")
        _log("Venv already exists")
    else:
        if os.path.isdir(venv_dir):
            reason="Venv without system site-packages" if stale_site else "Incomplete venv"
            _step("warn",f"{reason} detected, removing and recreating")
            _log(f"{reason} detected; removing before recreate")
            shutil.rmtree(venv_dir,ignore_errors=True)
        ok,tail=_ensure_venv(venv_dir)
        if not ok:
            _log(f"Failed to create venv: {tail}","ERROR")
            _ui_error("Failed to create venv")
            print(tail)
            if not _is_win():
                pkg="python3-venv"
                m=re.search(r"apt install (\S+)",tail or "")
                if m:pkg=m.group(1)
                print("\n"+_c("Hint:","bold","cyan")+f" Run:  sudo apt install {pkg} python3-pip")
            return 3
    py,pyw,pip=_venv_paths(venv_dir)
    if not os.path.isfile(py):
        _log("venv python not found after creation","ERROR")
        _ui_error("venv python not found - the venv may be corrupted, delete it and re-run")
        return 4
    if skip_update:
        _step("skip","pip and dependency update","(--skip-update)")
        _log("pip/deps update skipped via --skip-update")
    else:
        t0=time.time()
        ok,tail=_ensure_pip(py)
        if not ok:
            _log(f"Failed to update pip ({time.time()-t0:.1f}s): {tail}","ERROR")
            _ui_error("Failed to update pip")
            print(tail)
            return 5
        _log(f"pip ready ({time.time()-t0:.1f}s)")
        _step("ok","pip ready",f"({time.time()-t0:.1f}s)")
        if _deps_up_to_date(reqs):
            _step("ok","Requirements up to date","(cached)")
            _log("Deps fingerprint matches; skipping pip install")
        else:
            t0=time.time()
            ok,tail=_ensure_deps(py,reqs)
            if not ok:
                _log(f"Failed to install requirements ({time.time()-t0:.1f}s): {tail}","ERROR")
                _ui_error("Failed to install requirements")
                print(tail)
                return 6
            _save_deps_state(reqs)
            _log(f"Deps installed ({time.time()-t0:.1f}s)")
    t0=time.time()
    ok,tail=_check_webview_runtime(py)
    if not ok:
        _log(f"Webview runtime check failed ({time.time()-t0:.1f}s): {tail}","ERROR")
        _ui_error("Webview runtime check failed")
        msg=_webview_runtime_help(tail)
        if msg:
            print(msg)
        return 7
    _log(f"Webview runtime verified ({time.time()-t0:.1f}s)")
    app=_abs("LOYA_Note.py")
    sp=_Spinner()
    sp.start("Launching LOYA NG")
    ok,msg,pid=_launch_app(py,pyw,app)
    sp.stop(ok)
    if not ok:
        _log(f"Launch failed: {msg}","ERROR")
        _ui_error(msg)
        return 7
    _write_pid_file(pid)
    _log(f"Launched successfully (PID: {pid})","INFO")
    print()
    print("  "+_c(">>","bold","magenta")+" "+_c("LOYA NG is running","bold","green")+_c(f"  |  PID {pid}  |  ready in {time.time()-_t_start:.1f}s","dim"))
    print("  "+_c("Logs: Logs/  |  crash details: Logs/crash.log  |  RunNote.py --help for options","grey"))
    print()
    return 0
if __name__=="__main__":
    raise SystemExit(main())
