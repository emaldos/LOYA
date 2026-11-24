"""Kali Linux on WSL (Windows only): status, the setup wizard and the WSL network mode.

Scope, by design:
- It changes WSL settings only: the networking lines of %UserProfile%\\.wslconfig (merged, never overwritten, backed up first) and, for a
  custom IP, a few files inside the kali-linux distro (backed up inside the distro first). It never creates Hyper-V switches and never
  touches the host's network adapters. Bridged / custom IP can only use an external switch the user already made.
- Nothing runs on its own. Every step is started from Settings by the user, after the UI has shown what will run (describe_*).
- Commands are argv lists. PowerShell gets -EncodedCommand built from constant text plus values that passed validation and are quoted
  as PowerShell literals. Files inside the distro go through `wsl -d kali-linux -u root -- sh -c '<constant>' sh <constant path>` with the
  content on stdin, never on the command line.
- Mutating calls refuse while the app is locked (the bridge refuses too) and are written to the audit log.
"""
import os,re,json,time,base64,ipaddress,platform,subprocess,shutil,threading,uuid
from datetime import datetime,timezone
from Cores import common_db
from Cores.settings_lock import update_json,read_json
_IS_WINDOWS=platform.system()=="Windows"
_NO_WINDOW=getattr(subprocess,"CREATE_NO_WINDOW",0)
DISTRO="kali-linux"
SHELL_ID="wsl:"+DISTRO
# networkingMode (and so mirrored and bridged) is documented for Windows 11 22H2+; mirrored arrived in 22621.2359 (wsl-config, 2026-10-16).
WIN11_BUILD=22000
NETWORKING_MIN_BUILD=22621
MIRRORED_MIN_UBR=2359
MODES=("nat","mirrored","bridged","custom")
MODE_LABELS={"nat":"Default (NAT)","mirrored":"Same IP as this computer","bridged":"Separate device on the network","custom":"Custom IP"}
MANAGED_KEYS=("networkingMode","vmSwitch","dhcp","macAddress")
STATIC_SCRIPT="/usr/local/sbin/loya-wsl-static-ip"
WSL_CONF="/etc/wsl.conf"
RESOLV_CONF="/etc/resolv.conf"
WIZARD_STEPS=("prereq","reboot","install","user","network","verify","done")
NOTE_A="WSL network settings apply to every WSL distro, not just Kali. LOYA backs up your current .wslconfig and only changes the networking lines."
NOTE_B="Applying a change restarts WSL. That stops all running WSL distros and LOYA's WSL sessions."
_SHUTDOWN_SETTLE_SECONDS=8
_state_lock=threading.RLock()
_jobs={}
_jobs_lock=threading.Lock()
_switch_cache={"names":None,"at":0.0,"needs_admin":False,"error":""}

# ---------------------------------------------------------------- persistence
def _settings_path():return os.path.join(common_db.data_dir(),"settings.json")
def _default_state():
    return {"enabled":False,"notes_ack":False,"configured":False,"wizard":{"active":False,"reboot_pending":False,"boot_id":0,"verified":False},"network":{"mode":"nat"},"wslconfig_prior":None,"wslconfig_backup":"","distro_prior":None,"last_verify":None,"updated_at":""}
def get_state():
    d=read_json(_settings_path(),{})
    ext=d.get("extensions") if isinstance(d,dict) else None
    raw=ext.get("wsl_kali") if isinstance(ext,dict) else None
    state=_default_state()
    if isinstance(raw,dict):
        for key in state:
            if key in raw and (isinstance(raw[key],type(state[key])) or state[key] is None or key in ("wslconfig_prior","distro_prior","last_verify")):state[key]=raw[key]
        if not isinstance(state["wizard"],dict):state["wizard"]=_default_state()["wizard"]
        if not isinstance(state["network"],dict):state["network"]={"mode":"nat"}
    return state
def _save_state(mutate):
    def apply(d):
        ext=d.get("extensions")
        if not isinstance(ext,dict):ext={};d["extensions"]=ext
        cur=ext.get("wsl_kali")
        state=_default_state()
        if isinstance(cur,dict):state.update(cur)
        mutate(state)
        state["updated_at"]=datetime.now(timezone.utc).isoformat(timespec="seconds")
        ext["wsl_kali"]=state
    with _state_lock:
        if not update_json(_settings_path(),apply):raise ValueError("Could not save the Kali WSL settings.")
    return get_state()
def is_ready_for_sessions():
    """True when the setup has completed; the terminal menu then names kali-linux "Kali Linux (WSL)" (it also checks the distro exists)."""
    state=get_state()
    return bool(_IS_WINDOWS and state["enabled"] and state["configured"])

# ---------------------------------------------------------------- guards and audit
def _require_windows():
    if not _IS_WINDOWS:raise ValueError("Kali Linux on WSL is only available on Windows.")
def _require_unlocked():
    if common_db.is_locked():raise ValueError("LOYA NG is locked. Unlock it to continue.")
def _audit(event,detail="",success=True):
    try:
        from Cores.Services import security_service
        security_service.log_audit_event(event,str(detail)[:600],success)
    except Exception:pass

# ---------------------------------------------------------------- running things
def _decode(raw):
    if not raw:return ""
    if raw[:2]==b"\xff\xfe" or (len(raw)>3 and raw[1:2]==b"\x00" and raw[3:4]==b"\x00"):
        text=raw.decode("utf-16-le",errors="ignore")
    else:
        text=raw.decode("utf-8",errors="ignore")
    return text.replace("\x00","").lstrip("﻿")
def _run(argv,timeout=30,input_text=None):
    """Runs one argv (never a shell string). Returns (returncode, combined text). WSL_UTF8=1 makes wsl.exe print UTF-8."""
    env=dict(os.environ);env["WSL_UTF8"]="1"
    try:
        res=subprocess.run(list(argv),input=input_text.encode("utf-8") if input_text is not None else None,capture_output=True,timeout=timeout,creationflags=_NO_WINDOW,env=env)
    except FileNotFoundError:
        return 127,"not found"
    except subprocess.TimeoutExpired:
        return 124,"timed out"
    except Exception as e:
        return 1,str(e)
    return res.returncode,(_decode(res.stdout)+("\n"+_decode(res.stderr) if res.stderr else "")).strip()
def show_command(argv):
    """How an argv reads in a Windows console - for the "this is what will run" confirmations."""
    return subprocess.list2cmdline([str(a) for a in argv])
_PS_QUOTES=("'","‘","’","‚","‛")
def ps_literal(value):
    """A PowerShell single-quoted literal. PowerShell treats the typographic single quotes as quotes too, so every one is doubled."""
    text=str(value)
    if any(ch in text for ch in ("\x00","\r","\n")):raise ValueError("Control characters are not allowed here.")
    for q in _PS_QUOTES:text=text.replace(q,q+q)
    return "'"+text+"'"
def encode_ps(script):
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")
def ps_argv(script):
    return ["powershell.exe","-NoLogo","-NoProfile","-NonInteractive","-ExecutionPolicy","Bypass","-EncodedCommand",encode_ps(script)]
def elevated_argv(file_path,args,window="Normal"):
    """Starts file_path elevated (one UAC prompt), waits for it and passes its exit code back. 1223 = the user said no to UAC."""
    arg_list=",".join(ps_literal(a) for a in args)
    script="try{$p=Start-Process -FilePath %s -Verb RunAs -Wait -PassThru -WindowStyle %s -ArgumentList @(%s);exit $p.ExitCode}catch{exit 1223}"%(ps_literal(file_path),window,arg_list)
    return ps_argv(script)

# ---------------------------------------------------------------- facts about this machine
_HOME_PREFIX="core"
def _edition_label(edition_id):
    e=str(edition_id or "").lower()
    if e.startswith(_HOME_PREFIX):return "Home"
    if e.startswith("professional"):return "Pro"
    if e.startswith("enterprise"):return "Enterprise"
    if e.startswith("education"):return "Education"
    if e.startswith("server"):return "Server"
    return str(edition_id or "Unknown")
def windows_info():
    """Edition and build from the registry. ProductName still says "Windows 10" on Windows 11, so the name comes from the build."""
    info={"edition_id":"","edition":"Unknown","build":0,"ubr":0,"display_version":""}
    if not _IS_WINDOWS:return dict(info,name="")
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r"SOFTWARE\Microsoft\Windows NT\CurrentVersion") as key:
            def value(name,default):
                try:return winreg.QueryValueEx(key,name)[0]
                except OSError:return default
            info["edition_id"]=str(value("EditionID",""))
            info["build"]=int(str(value("CurrentBuild",value("CurrentBuildNumber","0"))) or 0)
            info["ubr"]=int(value("UBR",0) or 0)
            info["display_version"]=str(value("DisplayVersion",""))
    except Exception:
        try:info["build"]=int(platform.version().split(".")[-1])
        except Exception:pass
    return describe_windows(info)
def describe_windows(info):
    info=dict(info)
    info["edition"]=_edition_label(info.get("edition_id"))
    info["is_home"]=info["edition"]=="Home"
    info["name"]=("Windows 11" if int(info.get("build") or 0)>=WIN11_BUILD else "Windows 10")+(" "+info["edition"] if info["edition"]!="Unknown" else "")
    return info
_VERSION_RE=re.compile(r"(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?")
def parse_wsl_version(text):
    m=_VERSION_RE.search(str(text or ""))
    return ".".join(g for g in m.groups() if g is not None) if m else ""
def _version_tuple(text):
    m=_VERSION_RE.search(str(text or ""))
    return tuple(int(g or 0) for g in m.groups()) if m else ()
def list_distros():
    rc,text=_run(["wsl.exe","--list","--quiet"],12)
    if rc!=0:return []
    return [line.strip() for line in text.splitlines() if line.strip()]
def wsl_info():
    if not _IS_WINDOWS:return {"present":False,"ok":False,"version":"","status":"","distros":[]}
    present=bool(shutil.which("wsl.exe"))
    if not present:return {"present":False,"ok":False,"version":"","status":"WSL is not installed.","distros":[]}
    rc,status=_run(["wsl.exe","--status"],15)
    vrc,vtext=_run(["wsl.exe","--version"],15)
    distros=list_distros() if rc==0 else []
    return {"present":True,"ok":rc==0,"version":parse_wsl_version(vtext) if vrc==0 else "","status":status[:800],"distros":distros}
def hyperv_info():
    """Whether the Hyper-V PowerShell module is there, and the external switches (read-only; Get-VMSwitch may need admin rights)."""
    if not _IS_WINDOWS:return {"module":False,"switches":[],"needs_admin":False,"error":""}
    rc,text=_run(ps_argv("if(Get-Command Get-VMSwitch -ErrorAction SilentlyContinue){'LOYA_YES'}else{'LOYA_NO'}"),20)
    if "LOYA_YES" not in text:
        return {"module":False,"switches":[],"needs_admin":False,"error":""}
    rc,text=_run(ps_argv("try{ConvertTo-Json -Compress -InputObject @(Get-VMSwitch -SwitchType External -ErrorAction Stop | ForEach-Object {$_.Name})}catch{'LOYA_ERR:'+$_.Exception.Message}"),30)
    names,needs_admin,error=parse_switch_output(text)
    if names is not None:_cache_switches(names)
    elif _switch_cache["names"] is not None:names=_switch_cache["names"]
    return {"module":True,"switches":names or [],"needs_admin":needs_admin and names is None,"error":error}
def parse_switch_output(text):
    """-> (names or None, needs_admin, error)."""
    text=str(text or "").strip()
    if text.startswith("LOYA_ERR:") or "LOYA_ERR:" in text:
        msg=text.split("LOYA_ERR:",1)[1].strip()
        low=msg.lower()
        return None,("permission" in low or "access" in low or "administrator" in low or "authorization" in low),msg[:300]
    if not text:return [],False,""
    try:data=json.loads(text)
    except Exception:return None,False,"Could not read the switch list."
    if isinstance(data,str):data=[data]
    if not isinstance(data,list):return None,False,"Could not read the switch list."
    return [str(n) for n in data if isinstance(n,str) and SWITCH_RE.match(n)],False,""
def _cache_switches(names):
    _switch_cache.update({"names":list(names),"at":time.time(),"needs_admin":False,"error":""})
def lookup_switches_elevated():
    """Read-only switch listing with one UAC prompt, for accounts that cannot query Hyper-V. Writes JSON to a private temp file."""
    _require_windows();_require_unlocked()
    import tempfile
    folder=tempfile.mkdtemp(prefix="loya_vmswitch_")
    out=os.path.join(folder,"switches.json")
    inner="try{ConvertTo-Json -Compress -InputObject @(Get-VMSwitch -SwitchType External -ErrorAction Stop | ForEach-Object {$_.Name}) | Set-Content -LiteralPath %s -Encoding UTF8}catch{('LOYA_ERR:'+$_.Exception.Message) | Set-Content -LiteralPath %s -Encoding UTF8}"%(ps_literal(out),ps_literal(out))
    try:
        rc,_=_run(elevated_argv("powershell.exe",["-NoLogo","-NoProfile","-NonInteractive","-ExecutionPolicy","Bypass","-EncodedCommand",encode_ps(inner)],"Hidden"),120)
        if rc==1223:raise ValueError("The administrator prompt was cancelled.")
        try:
            with open(out,"r",encoding="utf-8-sig") as f:text=f.read()
        except OSError:
            raise ValueError("Hyper-V did not return a switch list.")
        names,_,error=parse_switch_output(text)
        if names is None:raise ValueError(error or "Hyper-V did not return a switch list.")
        _cache_switches(names)
        return names
    finally:
        shutil.rmtree(folder,ignore_errors=True)

# ---------------------------------------------------------------- which network options can work here
def _unavailable(label,why):
    return {"available":False,"reason":"%s won't work on this computer because %s"%(label,why)}
def mode_availability(win,wsl,hyperv):
    """Pure: which network options can work, and in plain words why the others cannot. Nothing here changes the machine."""
    build=int(win.get("build") or 0);ubr=int(win.get("ubr") or 0)
    name=win.get("name") or "this version of Windows"
    out={"nat":{"available":True,"reason":""}}
    old=build<NETWORKING_MIN_BUILD
    if old:
        out["mirrored"]=_unavailable(MODE_LABELS["mirrored"],"it needs Windows 11 version 22H2 (build 22621) or newer, and this is %s build %d."%(name,build))
    elif build==NETWORKING_MIN_BUILD and ubr and ubr<MIRRORED_MIN_UBR:
        out["mirrored"]=_unavailable(MODE_LABELS["mirrored"],"it needs Windows update 22621.%d or newer, and this is 22621.%d. Run Windows Update, then refresh."%(MIRRORED_MIN_UBR,ubr))
    else:
        out["mirrored"]={"available":True,"reason":""}
    for mode in ("bridged","custom"):
        label=MODE_LABELS[mode]
        if old:
            out[mode]=_unavailable(label,"WSL network modes need Windows 11 version 22H2 (build 22621) or newer, and this is %s build %d."%(name,build))
        elif win.get("is_home"):
            out[mode]={"available":False,"reason":"%s won't work on %s because it needs Hyper-V, which Home doesn't include."%(label,name)}
        elif not hyperv.get("module"):
            out[mode]=_unavailable(label,"it needs Hyper-V, which is turned off. To use it you would turn on Hyper-V yourself (Windows Features > Hyper-V), restart, and create an external virtual switch in Hyper-V Manager. LOYA does not change the host's network.")
        elif hyperv.get("needs_admin") and not hyperv.get("switches"):
            out[mode]={"available":False,"needs_lookup":True,"reason":"LOYA could not list Hyper-V switches without administrator rights. Use \"Look up switches\" (one read-only administrator prompt) and refresh."}
        elif not hyperv.get("switches"):
            out[mode]=_unavailable(label,"it needs an external Hyper-V virtual switch and this computer has none. You can create one yourself in Hyper-V Manager > Virtual Switch Manager > External network (this briefly interrupts the computer's connection), then refresh. LOYA does not create switches or change the host's network.")
        else:
            out[mode]={"available":True,"reason":""}
    if not wsl.get("ok"):
        for mode in ("mirrored","bridged","custom"):
            if out[mode]["available"]:out[mode]={"available":False,"reason":"Set up WSL first."}
    ver=_version_tuple(wsl.get("version"))
    if ver and (2,4,5)<=ver[:3]<(2,5,6):
        for mode in ("bridged","custom"):
            if out[mode]["available"]:out[mode]["warning"]="This WSL version (%s) marks bridged networking as deprecated. Microsoft brought it back in WSL 2.5.6; updating WSL (wsl --update) is recommended."%wsl.get("version")
    return out

# ---------------------------------------------------------------- validation
SWITCH_RE=re.compile(r"^[A-Za-z0-9 _.\-()]{1,100}$")
USER_RE=re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
MAC_RE=re.compile(r"^[0-9a-fA-F]{2}([:-])(?:[0-9a-fA-F]{2}\1){4}[0-9a-fA-F]{2}$")
_RESERVED_USERS={"root","daemon","bin","sys","sync","games","man","lp","mail","news","uucp","proxy","www-data","backup","list","irc","nobody","systemd-network","systemd-resolve","messagebus","sshd","postgres","mysql"}
def _text(raw,name,limit=64):
    if raw is None:return ""
    if not isinstance(raw,(str,int)) or isinstance(raw,bool):raise ValueError("%s is not valid."%name)
    text=str(raw)
    # Control characters (a newline would start a new line in a config file) are refused before trimming, not trimmed away.
    if any(ord(c)<32 or ord(c)==127 for c in text):raise ValueError("%s is not valid."%name)
    text=text.strip()
    if len(text)>limit:raise ValueError("%s is not valid."%name)
    return text
def _ipv4(raw,name):
    text=_text(raw,name)
    if not text:raise ValueError("%s is required."%name)
    try:addr=ipaddress.IPv4Address(text)
    except ValueError:raise ValueError("%s must be an IPv4 address like 192.168.1.50."%name)
    if addr.is_loopback or addr.is_multicast or addr.is_unspecified or addr.is_reserved or addr.is_link_local or str(addr)=="255.255.255.255":
        raise ValueError("%s cannot be %s."%(name,addr))
    return addr
def parse_prefix(raw):
    """Accepts 24, /24 or 255.255.255.0. Returns the prefix length (8..30)."""
    text=_text(raw,"Subnet").lstrip("/")
    if not text:raise ValueError("Subnet mask or prefix is required.")
    if text.isdigit():prefix=int(text)
    else:
        try:prefix=ipaddress.IPv4Network("0.0.0.0/"+text).prefixlen
        except ValueError:raise ValueError("Subnet must be a prefix like 24 or a mask like 255.255.255.0.")
    if prefix<8 or prefix>30:raise ValueError("Subnet prefix must be between 8 and 30.")
    return prefix
def parse_dns(raw):
    items=raw if isinstance(raw,list) else re.split(r"[\s,;]+",_text(raw,"DNS servers",200))
    out=[]
    for item in items:
        text=_text(item,"DNS server")
        if not text:continue
        try:addr=ipaddress.ip_address(text)
        except ValueError:raise ValueError("DNS server %s is not an IP address."%text[:40])
        if addr.is_multicast or addr.is_unspecified:raise ValueError("DNS server %s is not usable."%addr)
        if str(addr) not in out:out.append(str(addr))
    if not out:raise ValueError("Add at least one DNS server.")
    if len(out)>3:raise ValueError("Use at most 3 DNS servers (Linux reads only the first 3).")
    return out
def parse_mac(raw):
    text=_text(raw,"MAC address")
    if not text:return ""
    if not MAC_RE.match(text):raise ValueError("MAC address must look like 00:15:5d:12:34:56.")
    mac=text.replace("-",":").lower()
    first=int(mac[:2],16)
    if first&1:raise ValueError("MAC address must be a unicast address (the first byte must be even).")
    if mac=="00:00:00:00:00:00":raise ValueError("MAC address cannot be all zeros.")
    return mac
def parse_switch(raw,known=None):
    name=_text(raw,"Virtual switch",100)
    if not name or not SWITCH_RE.match(name):raise ValueError("Pick an external virtual switch from the list.")
    if known is not None and name not in known:raise ValueError("Pick an external virtual switch from the list (LOYA only uses switches that already exist).")
    return name
def parse_username(raw):
    name=_text(raw,"Username",32)
    if not USER_RE.match(name):raise ValueError("Username must start with a lowercase letter or _ and use only a-z, 0-9, _ and - (32 characters at most).")
    if name in _RESERVED_USERS:raise ValueError("Pick a different username; %s is a system account."%name)
    return name
def validate_network(raw,known_switches=None):
    """Returns a clean network dict or raises ValueError. Every value that later reaches a file or a command comes out of here."""
    if not isinstance(raw,dict):raise ValueError("Network settings are missing.")
    mode=_text(raw.get("mode"),"Network mode").lower()
    if mode not in MODES:raise ValueError("Pick a network mode.")
    out={"mode":mode}
    if mode in ("bridged","custom"):
        out["switch"]=parse_switch(raw.get("switch"),known_switches)
        out["mac"]=parse_mac(raw.get("mac"))
    if mode=="custom":
        ip=_ipv4(raw.get("ip"),"IP address")
        prefix=parse_prefix(raw.get("prefix") if raw.get("prefix") not in (None,"") else raw.get("mask"))
        iface=ipaddress.IPv4Interface("%s/%d"%(ip,prefix))
        net=iface.network
        if ip in (net.network_address,net.broadcast_address):raise ValueError("%s is the network or broadcast address of %s; pick a host address."%(ip,net))
        gw=_ipv4(raw.get("gateway"),"Gateway")
        if gw not in net:raise ValueError("Gateway %s is not in the same subnet as %s (%s)."%(gw,ip,net))
        if gw==ip:raise ValueError("Gateway cannot be the same as the IP address.")
        if gw in (net.network_address,net.broadcast_address):raise ValueError("Gateway %s is the network or broadcast address."%gw)
        out.update({"ip":str(ip),"prefix":prefix,"mask":str(net.netmask),"gateway":str(gw),"dns":parse_dns(raw.get("dns"))})
    return out

# ---------------------------------------------------------------- .wslconfig / wsl.conf (INI) merge
_SECTION_RE=re.compile(r"^\s*\[([^\]]+)\]\s*(?:[#;].*)?$")
def _key_of(line):
    s=line.strip()
    if not s or s[0] in "#;[" or "=" not in s:return None
    return s.split("=",1)[0].strip().lower()
def ini_get(text,section,key):
    current=None;value=None
    for line in str(text or "").splitlines():
        m=_SECTION_RE.match(line)
        if m:current=m.group(1).strip().lower();continue
        if current==section.lower() and _key_of(line)==key.lower():value=line.split("=",1)[1].strip()
    return value
def ini_merge(text,section,updates):
    """Sets (str) or removes (None) keys in one section. Comments, blank lines, unknown keys and other sections are kept as they are,
    in place. Key and section names match case-insensitively; a key repeated in the section keeps only its first, updated, line."""
    text=str(text or "")
    nl="\r\n" if "\r\n" in text else "\n"
    lines=text.splitlines()
    sec=section.lower()
    pending={k:v for k,v in updates.items()}
    seen=set();out=[];current=None;last_in_section=-1
    for line in lines:
        m=_SECTION_RE.match(line)
        if m:
            current=m.group(1).strip().lower()
            out.append(line)
            if current==sec:last_in_section=len(out)-1
            continue
        if current==sec:
            key=_key_of(line)
            match=next((k for k in updates if k.lower()==key),None) if key else None
            if match is not None:
                if match in seen or updates[match] is None:
                    seen.add(match);pending.pop(match,None)
                    continue
                indent=line[:len(line)-len(line.lstrip())]
                out.append("%s%s=%s"%(indent,line.strip().split("=",1)[0].strip(),updates[match]))
                seen.add(match);pending.pop(match,None)
                last_in_section=len(out)-1
                continue
            if line.strip():last_in_section=len(out)
            out.append(line)
            continue
        out.append(line)
    additions=["%s=%s"%(k,v) for k,v in pending.items() if v is not None]
    if additions:
        if last_in_section>=0:
            out[last_in_section+1:last_in_section+1]=additions
        else:
            while out and not out[-1].strip():out.pop()
            if out:out.append("")
            out.append("["+section+"]")
            out.extend(additions)
    result=nl.join(out)
    return result+nl if result else ""
def wslconfig_updates(net):
    mode=net["mode"]
    if mode in ("nat","mirrored"):return {"networkingMode":mode,"vmSwitch":None,"dhcp":None,"macAddress":None}
    return {"networkingMode":"bridged","vmSwitch":net["switch"],"dhcp":"false" if mode=="custom" else None,"macAddress":net.get("mac") or None}

# ---------------------------------------------------------------- %UserProfile%\.wslconfig on disk
def wslconfig_path():
    return os.path.join(os.environ.get("USERPROFILE") or os.path.expanduser("~"),".wslconfig")
def read_wslconfig(path=None):
    """-> (text, encoding, exists). Keeps a UTF-16 file UTF-16 when it is written back."""
    path=path or wslconfig_path()
    if not os.path.isfile(path):return "","utf-8",False
    with open(path,"rb") as f:raw=f.read()
    if raw[:2] in (b"\xff\xfe",b"\xfe\xff"):return raw.decode("utf-16"),"utf-16",True
    if raw[:3]==b"\xef\xbb\xbf":return raw[3:].decode("utf-8",errors="replace"),"utf-8-sig",True
    return raw.decode("utf-8",errors="replace"),"utf-8",True
def _stamp():return datetime.now().strftime("%Y%m%d-%H%M%S")
def backup_wslconfig(path=None):
    """Copies .wslconfig next to itself. Returns the backup path, or "absent" when there was no file (a rollback then deletes it)."""
    path=path or wslconfig_path()
    if not os.path.isfile(path):return "absent"
    dest="%s.loya-backup-%s"%(path,_stamp())
    n=1
    while os.path.exists(dest):dest="%s.loya-backup-%s-%d"%(path,_stamp(),n);n+=1
    shutil.copy2(path,dest)
    return dest
def restore_wslconfig(backup,path=None):
    path=path or wslconfig_path()
    if backup=="absent":
        if os.path.isfile(path):os.remove(path)
        return True
    if backup and os.path.isfile(backup):
        shutil.copy2(backup,path)
        return True
    return False
def write_wslconfig(updates,path=None):
    """Merges updates into [wsl2] and writes atomically. Returns (backup, prior values of the touched keys)."""
    path=path or wslconfig_path()
    text,enc,_=read_wslconfig(path)
    prior={k:ini_get(text,"wsl2",k) for k in updates}
    backup=backup_wslconfig(path)
    merged=ini_merge(text,"wsl2",updates)
    tmp=path+".loya-tmp"
    try:
        with open(tmp,"w",encoding=enc,newline="") as f:f.write(merged)
        os.replace(tmp,path)
    except Exception:
        try:os.remove(tmp)
        except OSError:pass
        restore_wslconfig(backup,path)
        raise
    return backup,prior

# ---------------------------------------------------------------- inside the distro (root, content on stdin)
def _wsl_root(args,input_text=None,timeout=60):
    return _run(["wsl.exe","-d",DISTRO,"-u","root","--"]+list(args),timeout,input_text)
def distro_read(path):
    rc,text=_wsl_root(["sh","-c",'[ -e "$1" ] && cat -- "$1" || true',"sh",path])
    if rc!=0:raise ValueError("Could not read %s inside %s."%(path,DISTRO))
    return text
def distro_write_argv(path,mode="0644"):
    return ["wsl.exe","-d",DISTRO,"-u","root","--","sh","-c",'rm -f -- "$1" && cat > "$1" && chmod "$2" "$1"',"sh",path,mode]
def distro_write(path,content,mode="0644"):
    rc,text=_run(distro_write_argv(path,mode),60,content)
    if rc!=0:raise ValueError("Could not write %s inside %s: %s"%(path,DISTRO,text[:200]))
def distro_backup(path,stamp):
    rc,_=_wsl_root(["sh","-c",'[ ! -e "$1" ] || cp -a -- "$1" "$1.loya-bak-$2"',"sh",path,stamp])
    return rc==0
def distro_restore(path,stamp):
    _wsl_root(["sh","-c",'if [ -e "$1.loya-bak-$2" ]; then rm -f -- "$1" && cp -a -- "$1.loya-bak-$2" "$1"; fi',"sh",path,stamp])
def distro_remove(path):
    _wsl_root(["rm","-f","--",path])
def static_ip_script(net):
    """Built only from values validate_network produced (canonical ipaddress strings), never from raw input."""
    ip=ipaddress.IPv4Address(net["ip"]);gw=ipaddress.IPv4Address(net["gateway"]);prefix=int(net["prefix"])
    return ("#!/bin/sh\n"
            "# Written by LOYA NG: Kali Linux on WSL, Custom IP. Remove it in Settings > Extensions > Kali Linux on WSL.\n"
            "for i in 1 2 3 4 5 6 7 8 9 10; do [ -e /sys/class/net/eth0 ] && break; sleep 1; done\n"
            "ip link set dev eth0 up\n"
            "ip -4 addr flush dev eth0 scope global\n"
            "ip -4 addr add %s/%d dev eth0\n"
            "ip -4 route replace default via %s dev eth0\n")%(ip,prefix,gw)
def resolv_conf(net):
    return "# Written by LOYA NG (Kali Linux on WSL, Custom IP)\n"+"".join("nameserver %s\n"%ipaddress.ip_address(d) for d in net["dns"])
def wsl_conf_static_updates():
    return {"boot":{"command":STATIC_SCRIPT},"network":{"generateResolvConf":"false"}}
def plan_distro_static(current_wsl_conf):
    """Pure. Refuses to replace a [boot] command the user set (LOYA would break their boot). Returns (new wsl.conf, prior values)."""
    existing=ini_get(current_wsl_conf,"boot","command")
    if existing and existing.strip()!=STATIC_SCRIPT:
        raise ValueError("Kali's /etc/wsl.conf already has a [boot] command (%s). LOYA won't replace it; remove it yourself or use a mode without a custom IP."%existing[:80])
    prior={"boot_command":existing,"generateResolvConf":ini_get(current_wsl_conf,"network","generateResolvConf")}
    text=ini_merge(current_wsl_conf,"boot",{"command":STATIC_SCRIPT})
    text=ini_merge(text,"network",{"generateResolvConf":"false"})
    return text,prior
def plan_distro_revert(current_wsl_conf,prior):
    prior=prior if isinstance(prior,dict) else {}
    text=current_wsl_conf
    if (ini_get(text,"boot","command") or "").strip()==STATIC_SCRIPT:
        text=ini_merge(text,"boot",{"command":prior.get("boot_command") if prior.get("boot_command") and prior.get("boot_command")!=STATIC_SCRIPT else None})
    text=ini_merge(text,"network",{"generateResolvConf":prior.get("generateResolvConf")})
    return text
def apply_distro_static(net):
    stamp=_stamp()
    current=distro_read(WSL_CONF)
    new_conf,prior=plan_distro_static(current)
    for path in (WSL_CONF,RESOLV_CONF):distro_backup(path,stamp)
    try:
        distro_write(STATIC_SCRIPT,static_ip_script(net),"0755")
        distro_write(RESOLV_CONF,resolv_conf(net),"0644")
        distro_write(WSL_CONF,new_conf,"0644")
    except Exception:
        distro_restore(WSL_CONF,stamp);distro_restore(RESOLV_CONF,stamp);distro_remove(STATIC_SCRIPT)
        raise
    return {"stamp":stamp,"prior":prior}
def revert_distro_static(distro_prior):
    info=distro_prior if isinstance(distro_prior,dict) else {}
    current=distro_read(WSL_CONF)
    stamp=_stamp()
    distro_backup(WSL_CONF,stamp)
    distro_write(WSL_CONF,plan_distro_revert(current,info.get("prior")),"0644")
    distro_remove(STATIC_SCRIPT)
    # WSL writes a fresh resolv.conf on the next start when generateResolvConf is back on.
    if (info.get("prior") or {}).get("generateResolvConf") in (None,"true","True"):distro_remove(RESOLV_CONF)

# ---------------------------------------------------------------- WSL restart and checks
def restart_argv():return ["wsl.exe","--shutdown"]
def _wait_stopped(timeout=20):
    end=time.time()+timeout
    while time.time()<end:
        rc,text=_run(["wsl.exe","--list","--running","--quiet"],10)
        if rc!=0 or not text.strip():return True
        time.sleep(1)
    return False
def restart_wsl(close_sessions=True):
    """wsl --shutdown stops every distro. LOYA's WSL sessions are closed first so none is left writing to a dead pipe."""
    closed=[]
    if close_sessions:
        from Cores.Services import terminal_service
        closed=terminal_service.close_wsl_sessions()
    rc,text=_run(restart_argv(),60)
    if rc!=0:raise ValueError("wsl --shutdown failed: %s"%text[:200])
    _wait_stopped()
    time.sleep(_SHUTDOWN_SETTLE_SECONDS)
    return closed
def parse_addresses(text):
    out=[]
    for line in str(text or "").splitlines():
        m=re.search(r"^\d+:\s+(\S+)\s+inet\s+(\d+\.\d+\.\d+\.\d+)/(\d+)",line.strip())
        if m:out.append({"interface":m.group(1),"ip":m.group(2),"prefix":int(m.group(3))})
    return out
def parse_default_gateway(text):
    m=re.search(r"default\s+via\s+(\d+\.\d+\.\d+\.\d+)",str(text or ""))
    if not m:return ""
    try:return str(ipaddress.IPv4Address(m.group(1)))
    except ValueError:return ""
def kali_addresses():
    rc,text=_run(["wsl.exe","-d",DISTRO,"--","ip","-4","-o","addr","show","scope","global"],40)
    return parse_addresses(text) if rc==0 else []
def verify_network():
    """Shows the IP and checks connectivity from inside Kali: ping the default gateway, then a DNS lookup."""
    result={"started":False,"addresses":[],"gateway":"","gateway_ok":False,"dns_ok":False,"dns_answer":"","checked_at":datetime.now(timezone.utc).isoformat(timespec="seconds")}
    rc,_=_run(["wsl.exe","-d",DISTRO,"--","true"],90)
    result["started"]=rc==0
    if rc!=0:return result
    result["addresses"]=kali_addresses()
    rc,text=_wsl_root(["ip","-4","route","show","default"],30)
    gw=parse_default_gateway(text)
    result["gateway"]=gw
    if gw:
        rc,_=_wsl_root(["ping","-c","2","-W","2",gw],30)
        result["gateway_ok"]=rc==0
    rc,text=_wsl_root(["getent","hosts","kali.org"],30)
    result["dns_ok"]=rc==0 and bool(text.strip())
    result["dns_answer"]=text.strip().splitlines()[0][:120] if result["dns_ok"] else ""
    return result

# ---------------------------------------------------------------- wizard
def boot_id():
    """Rounded boot time; a different value means Windows restarted since the WSL feature was installed."""
    if not _IS_WINDOWS:return 0
    try:
        import ctypes
        ticks=ctypes.windll.kernel32.GetTickCount64
        ticks.restype=ctypes.c_ulonglong
        return int((time.time()-ticks()/1000.0)//60)
    except Exception:
        return 0
def compute_step(state,facts):
    """Pure state machine. facts: wsl_ok, kali_installed, user_ready, boot_id. The persisted state only remembers what the
    machine cannot tell us (a reboot is pending, the network was applied, the check passed), so the wizard resumes after a restart."""
    wiz=state.get("wizard") or {}
    if state.get("configured"):return "done"
    if not wiz.get("active"):return "idle"
    if not facts.get("wsl_ok"):
        # Same boot (the id is minutes since the epoch, so allow one minute of rounding) = Windows has not restarted yet.
        if wiz.get("reboot_pending") and abs(int(wiz.get("boot_id") or 0)-int(facts.get("boot_id") or 0))<=1:return "reboot"
        return "prereq"
    if not facts.get("kali_installed"):return "install"
    if not facts.get("user_ready"):return "user"
    if not wiz.get("network_applied"):return "network"
    if not wiz.get("verified"):return "verify"
    return "done"
def _kali_default_uid():
    rc,text=_run(["wsl.exe","-d",DISTRO,"--","id","-u"],60)
    text=text.strip().splitlines()[-1].strip() if rc==0 and text.strip() else ""
    return int(text) if text.isdigit() else None
def gather_facts(include_user=True):
    wsl=wsl_info()
    kali=DISTRO in wsl["distros"]
    uid=_kali_default_uid() if (kali and include_user) else None
    return {"wsl":wsl,"wsl_ok":wsl["ok"],"kali_installed":kali,"default_uid":uid,"user_ready":uid not in (None,0),"boot_id":boot_id()}
def status(include_ip=False):
    """Everything the settings card shows. Read-only (the user check starts the distro once it is installed)."""
    state=get_state()
    if not _IS_WINDOWS:
        return {"supported":False,"platform":"linux","state":state,"notes":[NOTE_A,NOTE_B],"mode_labels":MODE_LABELS}
    win=windows_info()
    wiz_active=bool(state["wizard"].get("active")) or state["configured"]
    facts=gather_facts(include_user=wiz_active)
    if state["wizard"].get("reboot_pending") and facts["wsl_ok"]:
        state=_save_state(lambda s:s["wizard"].update({"reboot_pending":False}))
    hv=hyperv_info()
    path=wslconfig_path()
    text,_,exists=read_wslconfig(path)
    current_mode=(ini_get(text,"wsl2","networkingMode") or "nat").lower()
    out={"supported":True,"platform":"windows","windows":win,"wsl":facts["wsl"],"kali_installed":facts["kali_installed"],"default_uid":facts["default_uid"],
         "hyperv":hv,"availability":mode_availability(win,facts["wsl"],hv),"state":state,"step":compute_step(state,facts),
         "wslconfig":{"path":path,"exists":exists,"networking_mode":current_mode,"vm_switch":ini_get(text,"wsl2","vmSwitch") or "","experimental_mode":ini_get(text,"experimental","networkingMode") or ""},
         "network_mode":state["network"].get("mode") if state["configured"] else current_mode,"addresses":[],"notes":[NOTE_A,NOTE_B],"mode_labels":MODE_LABELS,"distro":DISTRO}
    if include_ip and facts["kali_installed"] and (state["configured"] or wiz_active):out["addresses"]=kali_addresses()
    return out
def set_enabled(enabled,acknowledged=False):
    """Turning the option on needs both notes acknowledged. Turning it off only hides it; nothing on the machine changes."""
    _require_windows();_require_unlocked()
    enabled=enabled is True
    if enabled and acknowledged is not True:raise ValueError("Read and acknowledge the WSL notes first.")
    state=_save_state(lambda s:s.update({"enabled":enabled,"notes_ack":True} if enabled else {"enabled":False}))
    _audit("wsl_kali_enabled" if enabled else "wsl_kali_disabled","notes acknowledged" if enabled else "")
    return state
def _require_enabled():
    state=get_state()
    if not state["enabled"] or not state["notes_ack"]:raise ValueError("Turn on Kali Linux on WSL in Settings first.")
    return state
def wizard_start():
    _require_windows();_require_unlocked();_require_enabled()
    _audit("wsl_kali_wizard_start")
    return _save_state(lambda s:s["wizard"].update({"active":True}))
def wizard_cancel():
    _require_windows();_require_unlocked()
    return _save_state(lambda s:s.update({"wizard":_default_state()["wizard"]}))

# ---------------------------------------------------------------- the commands each step runs
def feature_install_argv():return elevated_argv("wsl.exe",["--install","--no-distribution"],"Normal")
def distro_install_argv(web_download=False):return ["wsl.exe","--install","-d",DISTRO]+(["--web-download"] if web_download else [])
def first_run_argv():return ["wsl.exe","-d",DISTRO]
def adduser_argv(username):
    name=parse_username(username)
    return ["wsl.exe","-d",DISTRO,"-u","root","--","sh","-c",'adduser -- "$1" && usermod -aG sudo -- "$1"',"sh",name]
def describe(action,params=None):
    """What will run, shown to the user before they confirm. The same builders produce the argv that runs."""
    _require_windows()
    params=params if isinstance(params,dict) else {}
    if action=="feature":
        return {"title":"Install WSL","elevated":True,"commands":["wsl.exe --install --no-distribution"],"notes":["Windows asks for administrator approval (UAC).","Windows may need a restart afterwards. LOYA continues this setup after the restart."]}
    if action=="install":
        return {"title":"Install Kali Linux","elevated":False,"commands":[show_command(distro_install_argv(params.get("web_download") is True))],"notes":["Runs in a LOYA terminal session. When Kali starts for the first time it asks you to create a username and password there."]}
    if action=="first_run":
        return {"title":"Start Kali for the first time","elevated":False,"commands":[show_command(first_run_argv())],"notes":["Type the new username and password in the terminal session."]}
    if action=="adduser":
        name=parse_username(params.get("username"))
        return {"title":"Create a Kali user","elevated":False,"commands":["wsl.exe -d kali-linux -u root -- adduser %s"%name,"wsl.exe -d kali-linux -u root -- usermod -aG sudo %s"%name],"notes":["adduser asks for the new password in the terminal session."]}
    if action=="default_user":
        name=parse_username(params.get("username"))
        return {"title":"Make %s the default user"%name,"elevated":False,"commands":["Set [user] default=%s in kali-linux:/etc/wsl.conf (backed up first)"%name,"wsl.exe --terminate kali-linux"],"notes":["LOYA's Kali sessions are closed first."]}
    if action=="network":
        net=validate_network(params,_known_switches())
        updates=wslconfig_updates(net)
        lines=["Set in %s [wsl2] (backed up first; other lines kept):"%wslconfig_path()]+["  %s=%s"%(k,v) if v is not None else "  remove %s"%k for k,v in updates.items()]
        if net["mode"]=="custom":
            lines+=["Write kali-linux:%s (sets %s/%d, gateway %s)"%(STATIC_SCRIPT,net["ip"],net["prefix"],net["gateway"]),"Write kali-linux:%s (nameserver %s)"%(RESOLV_CONF,", ".join(net["dns"])),"Set in kali-linux:%s  [boot] command=%s  [network] generateResolvConf=false"%(WSL_CONF,STATIC_SCRIPT)]
        elif get_state()["network"].get("mode")=="custom":
            lines.append("Undo the custom IP inside kali-linux (restore %s, remove %s)"%(WSL_CONF,STATIC_SCRIPT))
        lines+=["wsl.exe --shutdown","wsl.exe -d kali-linux -- true   (start Kali and check the IP, gateway ping and DNS)"]
        return {"title":"Apply network mode: %s"%MODE_LABELS[net["mode"]],"elevated":False,"commands":lines,"notes":[NOTE_A,NOTE_B]}
    if action=="restart":
        return {"title":"Restart WSL","elevated":False,"commands":["wsl.exe --shutdown"],"notes":[NOTE_B]}
    if action=="remove":
        cmds=["Restore the networking lines LOYA changed in %s (backed up first)"%wslconfig_path()]
        if get_state()["network"].get("mode")=="custom":cmds.append("Undo the custom IP inside kali-linux")
        if params.get("unregister") is True:cmds.append("wsl.exe --unregister kali-linux   (DELETES the distro and all its files)")
        cmds.append("wsl.exe --shutdown")
        return {"title":"Remove Kali setup","elevated":False,"commands":cmds,"notes":[NOTE_B]}
    raise ValueError("Unknown action.")
def task_command(task,params):
    """Terminal task sessions for the steps the user has to type into. Called by terminal_service.create_task_session."""
    _require_windows();_require_unlocked();_require_enabled()
    params=params if isinstance(params,dict) else {}
    env={"WSL_UTF8":"1"}
    if task=="wsl_install_kali":
        return {"shell_id":SHELL_ID,"argv":distro_install_argv(params.get("web_download") is True),"label":"Install Kali Linux","conpty":True,"env":env,"audit":"wsl_kali_install"}
    if task=="wsl_kali_first_run":
        return {"shell_id":SHELL_ID,"argv":first_run_argv(),"label":"Kali first run","conpty":True,"env":env,"audit":"wsl_kali_first_run"}
    if task=="wsl_kali_adduser":
        return {"shell_id":SHELL_ID,"argv":adduser_argv(params.get("username")),"label":"Create Kali user","conpty":True,"env":env,"audit":"wsl_kali_adduser"}
    if task=="wsl_kali_session":
        if not is_ready_for_sessions():raise ValueError("Finish the Kali Linux on WSL setup first.")
        return {"shell_id":SHELL_ID,"argv":first_run_argv(),"label":"Kali Linux (WSL)","conpty":False,"env":None,"audit":""}
    raise ValueError("Unknown terminal task.")

# ---------------------------------------------------------------- background jobs (UAC waits, WSL restarts)
def _new_job(kind):
    job={"id":uuid.uuid4().hex[:12],"kind":kind,"state":"running","log":[],"result":None,"error":"","started":time.time()}
    with _jobs_lock:
        for old in [k for k,v in _jobs.items() if v["state"]!="running" and time.time()-v["started"]>3600]:_jobs.pop(old,None)
        _jobs[job["id"]]=job
    return job
def _log(job,text):job["log"].append(str(text)[:400])
def _run_job(job,fn):
    def target():
        try:
            job["result"]=fn(job)
            job["state"]="done"
        except Exception as e:
            job["error"]=str(e)[:500] or e.__class__.__name__
            job["state"]="failed"
            _log(job,"Failed: "+job["error"])
    threading.Thread(target=target,daemon=True).start()
    return {"job_id":job["id"]}
def job_status(job_id):
    job=_jobs.get(str(job_id or ""))
    if not job:raise ValueError("That task is no longer running.")
    return {k:job[k] for k in ("id","kind","state","log","result","error")}
def _job_running(kind=None):
    return any(j["state"]=="running" and (kind is None or j["kind"]==kind) for j in _jobs.values())
def enable_feature():
    """Step 1 when WSL is missing: elevated `wsl --install --no-distribution`, then remember that a restart may be pending."""
    _require_windows();_require_unlocked();_require_enabled()
    if _job_running():raise ValueError("Another WSL task is still running.")
    job=_new_job("feature")
    def work(job):
        argv=feature_install_argv()
        _log(job,"Running as administrator: wsl.exe --install --no-distribution")
        rc,text=_run(argv,3600)
        if rc==1223:
            _audit("wsl_feature_install","cancelled at the UAC prompt",False)
            raise ValueError("The administrator prompt was cancelled.")
        if rc not in (0,3010):
            _audit("wsl_feature_install","exit %s"%rc,False)
            raise ValueError("wsl --install --no-distribution exited with code %s. %s"%(rc,text[:200]))
        now_ok=wsl_info()["ok"]
        _save_state(lambda s:s["wizard"].update({"reboot_pending":not now_ok,"boot_id":boot_id()}))
        _audit("wsl_feature_install","exit %s, restart %s"%(rc,"not needed" if now_ok else "pending"))
        _log(job,"WSL is ready." if now_ok else "Restart Windows to finish installing WSL. LOYA continues this setup after the restart.")
        return {"reboot_required":not now_ok}
    return _run_job(job,work)
def _known_switches():
    return _switch_cache["names"] if _switch_cache["names"] is not None else hyperv_info()["switches"]
def set_default_user(username):
    """Writes [user] default=<name> into the distro's /etc/wsl.conf (merged, backed up) after checking the user exists."""
    _require_windows();_require_unlocked();_require_enabled()
    name=parse_username(username)
    rc,_=_run(["wsl.exe","-d",DISTRO,"-u","root","--","id","-u","--",name],60)
    if rc!=0:raise ValueError("User %s does not exist in %s yet. Create it first."%(name,DISTRO))
    stamp=_stamp()
    current=distro_read(WSL_CONF)
    distro_backup(WSL_CONF,stamp)
    distro_write(WSL_CONF,ini_merge(current,"user",{"default":name}),"0644")
    from Cores.Services import terminal_service
    closed=terminal_service.close_wsl_sessions(DISTRO)
    _run(["wsl.exe","--terminate",DISTRO],60)
    _audit("wsl_kali_default_user",name)
    return {"closed":closed,"default_uid":_kali_default_uid()}
def apply_network(raw,confirm_restart=False,from_wizard=False):
    """Validates, backs up, writes .wslconfig (and Kali's files for a custom IP), restarts WSL, starts Kali and checks it.
    If Kali cannot start afterwards everything is rolled back. Runs as a background job; poll job_status."""
    _require_windows();_require_unlocked();_require_enabled()
    if confirm_restart is not True:raise ValueError("Confirm that WSL may restart first.")
    if _job_running():raise ValueError("Another WSL task is still running.")
    avail=mode_availability(windows_info(),wsl_info(),hyperv_info())
    net=validate_network(raw,_known_switches())
    if not avail[net["mode"]]["available"]:raise ValueError(avail[net["mode"]]["reason"])
    previous=get_state()
    job=_new_job("network")
    def work(job):
        prev_mode=previous["network"].get("mode") if previous["configured"] or previous["wizard"].get("network_applied") else None
        distro_info=previous.get("distro_prior")
        kali=DISTRO in list_distros()
        if net["mode"]=="custom":
            if not kali:raise ValueError("Install Kali Linux first.")
            _log(job,"Writing the custom IP setup inside Kali (backed up first).")
            info=apply_distro_static(net)
            if prev_mode=="custom" and isinstance(distro_info,dict) and distro_info.get("prior"):info["prior"]=distro_info["prior"]
            distro_info=info
        elif prev_mode=="custom" and kali:
            _log(job,"Undoing the custom IP inside Kali.")
            revert_distro_static(distro_info)
            distro_info=None
        _log(job,"Backing up and updating %s."%wslconfig_path())
        updates=wslconfig_updates(net)
        backup,prior=write_wslconfig(updates)
        _log(job,"Backup: %s"%backup)
        _log(job,"Restarting WSL (wsl --shutdown).")
        closed=restart_wsl()
        _log(job,"Starting Kali and checking the network.")
        result=verify_network()
        if not result["started"]:
            _log(job,"Kali did not start with the new settings. Rolling back.")
            restore_wslconfig(backup)
            if net["mode"]=="custom":
                try:revert_distro_static(distro_info)
                except Exception:pass
            try:restart_wsl(close_sessions=False)
            except Exception:pass
            _audit("wsl_network_mode","%s failed to start; rolled back"%net["mode"],False)
            raise ValueError("Kali did not start with %s. LOYA restored the previous settings."%MODE_LABELS[net["mode"]])
        def save(s):
            if s.get("wslconfig_prior") is None:s["wslconfig_prior"]=prior
            s["wslconfig_backup"]=backup
            s["network"]=net
            s["distro_prior"]=distro_info
            s["last_verify"]=result
            if from_wizard or s["wizard"].get("active"):
                s["wizard"]["network_applied"]=True
            if s["configured"] or s["wizard"].get("active"):
                s["configured"]=True
                s["wizard"]["verified"]=bool(result["addresses"])
        _save_state(save)
        _audit("wsl_network_mode","%s -> %s (switch %s)"%(prev_mode or "unset",net["mode"],net.get("switch","-")))
        return {"verify":result,"closed":closed,"backup":backup,"mode":net["mode"]}
    return _run_job(job,work)
def rollback_network():
    """Puts the last .wslconfig backup back (and undoes a custom IP), then restarts WSL."""
    _require_windows();_require_unlocked();_require_enabled()
    state=get_state()
    backup=state.get("wslconfig_backup")
    if not backup:raise ValueError("There is no backup to restore.")
    if state["network"].get("mode")=="custom" and DISTRO in list_distros():revert_distro_static(state.get("distro_prior"))
    if not restore_wslconfig(backup):raise ValueError("The backup file is missing: %s"%backup)
    closed=restart_wsl()
    text,_,_=read_wslconfig()
    mode=(ini_get(text,"wsl2","networkingMode") or "nat").lower()
    _save_state(lambda s:s.update({"network":{"mode":mode if mode in MODES else "nat"},"distro_prior":None}))
    _audit("wsl_network_rollback",backup)
    return {"closed":closed,"mode":mode}
def restart():
    _require_windows();_require_unlocked()
    closed=restart_wsl()
    _audit("wsl_restart","wsl --shutdown")
    return {"closed":closed}
def verify():
    _require_windows();_require_unlocked();_require_enabled()
    result=verify_network()
    def save(s):
        s["last_verify"]=result
        if s["wizard"].get("active") and s["wizard"].get("network_applied") and result["addresses"]:
            s["wizard"]["verified"]=True;s["configured"]=True
    _save_state(save)
    return result
def finish_wizard():
    _require_windows();_require_unlocked();_require_enabled()
    state=get_state()
    if not state["wizard"].get("network_applied"):raise ValueError("Apply a network mode first.")
    _audit("wsl_kali_setup_complete",state["network"].get("mode",""))
    return _save_state(lambda s:s.update({"configured":True,"wizard":dict(s["wizard"],verified=True)}))
def remove_setup(unregister=False,confirm_name="",confirm_restart=False):
    """Undoes LOYA's changes: the .wslconfig lines go back to what they were before LOYA, a custom IP is removed from Kali.
    The distro itself is only deleted when unregister is ticked AND its name is typed."""
    _require_windows();_require_unlocked()
    if confirm_restart is not True:raise ValueError("Confirm that WSL may restart first.")
    if unregister is True and confirm_name!=DISTRO:raise ValueError("Type %s to confirm deleting the distro."%DISTRO)
    state=get_state()
    log=[]
    prior=state.get("wslconfig_prior")
    if isinstance(prior,dict) and prior:
        backup,_=write_wslconfig({k:prior.get(k) for k in MANAGED_KEYS})
        log.append("Restored the networking lines in .wslconfig (backup %s)."%backup)
    kali=DISTRO in list_distros()
    if state["network"].get("mode")=="custom" and kali and unregister is not True:
        try:revert_distro_static(state.get("distro_prior"));log.append("Removed the custom IP from Kali.")
        except Exception as e:log.append("Could not undo the custom IP inside Kali: %s"%e)
    from Cores.Services import terminal_service
    closed=terminal_service.close_wsl_sessions()
    if unregister is True and kali:
        rc,text=_run(["wsl.exe","--unregister",DISTRO],300)
        log.append("Deleted the kali-linux distro." if rc==0 else "wsl --unregister failed: %s"%text[:200])
        _audit("wsl_kali_unregister","exit %s"%rc,rc==0)
        terminal_service.refresh_wsl_distros()
    try:restart_wsl(close_sessions=False)
    except Exception as e:log.append(str(e))
    _save_state(lambda s:s.update({"configured":False,"wizard":_default_state()["wizard"],"network":{"mode":"nat"},"wslconfig_prior":None,"distro_prior":None,"last_verify":None}))
    _audit("wsl_kali_remove_setup","unregister=%s"%(unregister is True))
    return {"log":log,"closed":closed}
def refresh_shells():
    from Cores.Services import terminal_service
    terminal_service.refresh_wsl_distros()
    return terminal_service.list_shells()
