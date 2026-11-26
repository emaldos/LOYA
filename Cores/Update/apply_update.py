import hashlib,json,os,re,shutil,signal,stat,subprocess,sys,tempfile,time,zipfile
# Standalone on purpose: this file is copied to a temp folder and run by the interpreter alone while Cores/ is being replaced,
# so it must not import anything from the app.
_SKIP_TOP_LEVEL={"Data","Logs","Backups","Update",".venv_windows",".venv_linux","__pycache__",".git",".pytest_cache",".mypy_cache",".ruff_cache",".idea",".vs",".vscode"}
_KEEP_ON_ROLLBACK=("Cores/Update/state.json","Cores/Update/OldVersions")
_OFFICIAL_REPO="https://github.com/emaldos/LOYA"  # must match update_helpers.OFFICIAL_SOURCE_REPO
_SEMVER_RX=re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_MAX_ENTRIES=20000
_MAX_FILE=100*1024*1024
_MAX_TOTAL=600*1024*1024
def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())
def _norm(v):
    return str(v or "").strip()
def _is_semver(text):
    return bool(_SEMVER_RX.fullmatch(_norm(text)))
def _is_official_repo(url):
    return _norm(url).rstrip("/").lower()==_OFFICIAL_REPO.lower()
def _is_official_package_url(url):
    low=_norm(url).lower()
    return low.startswith("https://github.com/emaldos/loya/releases/download/") or bool(re.fullmatch(r"https://api\.github\.com/repos/emaldos/loya/releases/assets/\d+",low))
def _read_json(path,default=None):
    try:
        with open(path,"r",encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default
def _write_json(path,obj):
    tmp=path+".tmp"
    os.makedirs(os.path.dirname(path),exist_ok=True)
    with open(tmp,"w",encoding="utf-8") as fh:
        json.dump(obj,fh,ensure_ascii=False,indent=2)
    os.replace(tmp,path)
def _write_text(path,text):
    os.makedirs(os.path.dirname(path),exist_ok=True)
    with open(path,"w",encoding="utf-8",newline="\n") as fh:
        fh.write(str(text))
def _within_root(path,root):
    try:
        return os.path.commonpath([os.path.abspath(path),os.path.abspath(root)])==os.path.abspath(root)
    except Exception:
        return False
def _state_path(root):
    return os.path.join(root,"Cores","Update","state.json")
def _update_log_path(root):
    return os.path.join(root,"Logs","Update_log.log")
def _append_log(root,tag,msg):
    try:
        path=_update_log_path(root)
        os.makedirs(os.path.dirname(path),exist_ok=True)
        with open(path,"a",encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {tag} {msg}\n")
    except Exception:
        pass
def _set_state(root,mutator):
    path=_state_path(root)
    state=_read_json(path,{})
    if not isinstance(state,dict):
        state={}
    mutator(state)
    _write_json(path,state)
    return state
def _mark_waiting_launch(root,error=""):
    err=_norm(error)
    def _mut(state):
        state["last_error"]=err
        state["recovery_required"]=True
        state["recovery_reason"]=err
        state["last_checked"]=_now()
        state["update_in_progress"]=True
    return _set_state(root,_mut)
def _write_version_files(root,version):
    ver=_norm(version)
    if not ver:
        return
    path=os.path.join(root,"Cores","Update","CurrentVersion.info")
    _write_text(path,ver+"\n")
def _sha256_file(path):
    h=hashlib.sha256()
    with open(path,"rb") as fh:
        while True:
            chunk=fh.read(1024*1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()
def _copy_hashed(src,dst):
    h=hashlib.sha256()
    with open(src,"rb") as fi,open(dst,"wb") as fo:
        for chunk in iter(lambda:fi.read(1024*1024),b""):
            h.update(chunk);fo.write(chunk)
    return h.hexdigest()
def _pid_running(pid):
    try:
        pid=int(pid or 0)
    except Exception:
        pid=0
    if pid<=0:
        return False
    try:
        if os.name=="nt":
            p=subprocess.run(["tasklist","/FI",f"PID eq {pid}","/NH"],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,creationflags=0x08000000)
            txt=(p.stdout or "").strip().lower()
            return bool(txt and "no tasks are running" not in txt and str(pid) in txt)
        os.kill(pid,0)
        return True
    except Exception:
        return False
def _wait_for_exit(pid,timeout=180):
    end=time.time()+max(1,int(timeout or 180))
    while time.time()<end:
        if not _pid_running(pid):
            return True
        time.sleep(1)
    return not _pid_running(pid)
def _member_parts(name):
    if not name or "\x00" in name or "\\" in name or name.startswith("/") or re.match(r"^[A-Za-z]:",name):
        raise RuntimeError(f"Package contains an unsafe path: {name[:120]}")
    parts=[p for p in name.split("/") if p and p!="."]
    if any(p==".." or ":" in p for p in parts):
        raise RuntimeError(f"Package contains an unsafe path: {name[:120]}")
    return parts
def _apply_mode(target,info):
    # Keep the executable bit (scripts) on Linux; never setuid/setgid/sticky or world-writable bits from an archive.
    if os.name=="nt":
        return
    mode=(info.external_attr>>16)&0o777
    if mode:
        try:os.chmod(target,(mode&0o755)|0o600)
        except OSError:pass
def _safe_extract(zip_path,dst_dir):
    out=os.path.abspath(dst_dir)
    os.makedirs(out,exist_ok=True)
    total=0
    with zipfile.ZipFile(zip_path,"r") as zf:
        infos=zf.infolist()
        if len(infos)>_MAX_ENTRIES:
            raise RuntimeError("Package has too many entries.")
        for info in infos:
            parts=_member_parts(str(getattr(info,"filename","") or ""))
            if not parts:
                continue
            ftype=stat.S_IFMT((info.external_attr>>16)&0xFFFF)
            if ftype and ftype not in (stat.S_IFREG,stat.S_IFDIR):
                raise RuntimeError(f"Package contains a link or special file: {info.filename[:120]}")
            if info.flag_bits&0x1:
                raise RuntimeError("Package contains encrypted entries.")
            target=os.path.abspath(os.path.join(out,*parts))
            if not _within_root(target,out):
                raise RuntimeError("Package extraction escaped the staging directory.")
            if info.is_dir():
                os.makedirs(target,exist_ok=True)
                continue
            if info.file_size>_MAX_FILE:
                raise RuntimeError(f"Package entry is too large: {info.filename[:120]}")
            total+=info.file_size
            if total>_MAX_TOTAL:
                raise RuntimeError("Package expands beyond the size limit.")
            os.makedirs(os.path.dirname(target),exist_ok=True)
            written=0
            with zf.open(info,"r") as src,open(target,"wb") as dst:
                for chunk in iter(lambda:src.read(1024*1024),b""):
                    written+=len(chunk)
                    if written>info.file_size or written>_MAX_FILE:
                        raise RuntimeError(f"Package entry is larger than declared: {info.filename[:120]}")
                    dst.write(chunk)
            _apply_mode(target,info)
def _looks_like_source_root(path,required_dirs,required_files):
    return all(os.path.isdir(os.path.join(path,item)) for item in required_dirs) and all(os.path.isfile(os.path.join(path,item)) for item in required_files)
def _locate_source_root(base_dir,required_dirs,required_files):
    base=os.path.abspath(base_dir)
    if _looks_like_source_root(base,required_dirs,required_files):
        return base
    for root,dirs,_ in os.walk(base):
        rel=os.path.relpath(root,base)
        if rel!="." and rel.count(os.sep)>3:
            dirs[:]=[]
            continue
        if _looks_like_source_root(root,required_dirs,required_files):
            return os.path.abspath(root)
    raise RuntimeError("Downloaded package is missing the required application files.")
def _norm_rel(rel):
    return "/".join([p for p in str(rel or "").replace("\\","/").split("/") if p and p!="."]).strip("/")
def _is_preserved(rel,preserve_paths):
    rel=_norm_rel(rel)
    return any(rel==keep or rel.startswith(keep+"/") for keep in preserve_paths)
def _has_preserved_child(rel,preserve_paths):
    rel=_norm_rel(rel)
    return any(keep.startswith(rel+"/") for keep in preserve_paths)
def _clear_tree(dst_root,preserve_paths=()):
    if not os.path.isdir(dst_root):
        return
    base_root=os.path.abspath(dst_root)
    for base,dirs,files in os.walk(base_root,topdown=False):
        rel_dir=os.path.relpath(base,base_root)
        rel_dir="" if rel_dir=="." else _norm_rel(rel_dir)
        for fn in files:
            rel=_norm_rel(os.path.join(rel_dir,fn) if rel_dir else fn)
            path=os.path.join(base,fn)
            if _is_preserved(rel,preserve_paths):
                continue
            if _within_root(path,base_root):
                try:os.remove(path)
                except Exception:pass
        for dn in dirs:
            rel=_norm_rel(os.path.join(rel_dir,dn) if rel_dir else dn)
            path=os.path.join(base,dn)
            if _is_preserved(rel,preserve_paths) or _has_preserved_child(rel,preserve_paths):
                continue
            if _within_root(path,base_root):
                shutil.rmtree(path,ignore_errors=True)
def _copy_tree(src_root,dst_root,preserve_paths=()):
    os.makedirs(dst_root,exist_ok=True)
    for base,dirs,files in os.walk(src_root):
        rel_dir=os.path.relpath(base,src_root)
        rel_dir="" if rel_dir=="." else _norm_rel(rel_dir)
        dirs[:]=[d for d in dirs if not _is_preserved(os.path.join(rel_dir,d) if rel_dir else d,preserve_paths)]
        target_dir=os.path.join(dst_root,rel_dir) if rel_dir else dst_root
        os.makedirs(target_dir,exist_ok=True)
        for fn in files:
            rel=_norm_rel(os.path.join(rel_dir,fn) if rel_dir else fn)
            if _is_preserved(rel,preserve_paths):
                continue
            src=os.path.join(base,fn)
            dst=os.path.join(target_dir,fn)
            shutil.copy2(src,dst)
def _replace_dir(root,source_root,top_name,preserve_paths=()):
    src=os.path.join(source_root,top_name)
    dst=os.path.join(root,top_name)
    if not os.path.isdir(src):
        raise RuntimeError(f"Missing update folder: {top_name}")
    if not _within_root(dst,root):
        raise RuntimeError(f"Unsafe target folder: {top_name}")
    _clear_tree(dst,preserve_paths)
    _copy_tree(src,dst,preserve_paths)
def _replace_file(root,source_root,name):
    src=os.path.join(source_root,name)
    dst=os.path.join(root,name)
    if not os.path.isfile(src):
        return
    if not _within_root(dst,root):
        raise RuntimeError(f"Unsafe target file: {name}")
    os.makedirs(os.path.dirname(dst),exist_ok=True)
    shutil.copy2(src,dst)
def _should_skip_restore(rel):
    rel=_norm_rel(rel)
    if not rel:
        return False
    top=rel.split("/",1)[0]
    if top in _SKIP_TOP_LEVEL:
        return True
    return any(rel==keep or rel.startswith(keep+"/") for keep in _KEEP_ON_ROLLBACK)
def _remove_current_code(root):
    base_root=os.path.abspath(root)
    for base,dirs,files in os.walk(base_root,topdown=True):
        rel_dir=os.path.relpath(base,base_root)
        rel_dir="" if rel_dir=="." else _norm_rel(rel_dir)
        dirs[:]=[d for d in dirs if not _should_skip_restore(os.path.join(rel_dir,d) if rel_dir else d)]
        for fn in files:
            rel=_norm_rel(os.path.join(rel_dir,fn) if rel_dir else fn)
            path=os.path.join(base,fn)
            if _should_skip_restore(rel) or not _within_root(path,base_root):
                continue
            try:os.remove(path)
            except Exception:pass
    for base,dirs,_ in os.walk(base_root,topdown=False):
        rel_dir=os.path.relpath(base,base_root)
        rel_dir="" if rel_dir=="." else _norm_rel(rel_dir)
        if not rel_dir or _should_skip_restore(rel_dir) or any(k.startswith(rel_dir+"/") for k in _SKIP_TOP_LEVEL):
            continue
        if not _within_root(base,base_root):
            continue
        for dn in dirs:
            _=dn
        try:
            if not os.listdir(base):
                os.rmdir(base)
        except Exception:
            pass
def _restore_snapshot(root,snapshot_zip):
    if not snapshot_zip or not os.path.isfile(snapshot_zip):
        raise RuntimeError("Rollback snapshot was not found.")
    tmp=tempfile.mkdtemp(prefix="loya_update_rollback_")
    try:
        _safe_extract(snapshot_zip,tmp)
        app_root=os.path.join(tmp,"app")
        if not os.path.isdir(app_root):
            raise RuntimeError("Rollback snapshot format is invalid.")
        _remove_current_code(root)
        for base,dirs,files in os.walk(app_root):
            rel_dir=os.path.relpath(base,app_root)
            rel_dir="" if rel_dir=="." else _norm_rel(rel_dir)
            dirs[:]=[d for d in dirs if not _should_skip_restore(os.path.join(rel_dir,d) if rel_dir else d)]
            target_dir=os.path.join(root,rel_dir) if rel_dir else root
            os.makedirs(target_dir,exist_ok=True)
            for fn in files:
                rel=_norm_rel(os.path.join(rel_dir,fn) if rel_dir else fn)
                if _should_skip_restore(rel):
                    continue
                src=os.path.join(base,fn)
                dst=os.path.join(target_dir,fn)
                if _within_root(dst,root):
                    shutil.copy2(src,dst)
    finally:
        shutil.rmtree(tmp,ignore_errors=True)
def _launch_runnote(python_exe,launcher_script,root):
    if not os.path.isfile(launcher_script):
        raise RuntimeError("RunNote.py was not found after the update.")
    args=[python_exe or sys.executable,launcher_script]
    stdin=subprocess.DEVNULL
    stdout=subprocess.DEVNULL
    stderr=subprocess.DEVNULL
    if os.name=="nt":
        flags=0x00000200|0x08000000
        return subprocess.Popen(args,stdin=stdin,stdout=stdout,stderr=stderr,cwd=root,creationflags=flags)
    return subprocess.Popen(args,stdin=stdin,stdout=stdout,stderr=stderr,cwd=root,start_new_session=True)
def _kill_pid(pid):
    try:
        pid=int(pid or 0)
    except Exception:
        return
    if pid<=0:
        return
    try:
        if os.name=="nt":
            subprocess.run(["taskkill","/PID",str(pid),"/T","/F"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=0x08000000)
            return
        os.kill(pid,signal.SIGTERM)
        for _ in range(50):
            if not _pid_running(pid):
                return
            time.sleep(0.1)
        os.kill(pid,signal.SIGKILL)
    except Exception:
        pass
def _read_app_pid(root):
    try:
        with open(os.path.join(root,"Data","loya.pid"),"r",encoding="utf-8") as fh:
            return int(fh.read().strip())
    except Exception:
        return 0
def _launch_confirmed(root,target_version):
    state=_read_json(_state_path(root),{})
    if not isinstance(state,dict):
        return False
    return not state.get("update_in_progress") and _norm(state.get("current_version",""))==target_version and _norm(state.get("last_good_version",""))==target_version
def _await_launch_confirmation(root,proc,target_version,timeout):
    """Health gate: the new version must reach update.launch_ready (UI loaded + health check) in time, or it is rolled back.
    Returns "" on success or the failure reason."""
    end=time.time()+20*60
    while time.time()<end:
        if _launch_confirmed(root,target_version):
            return ""
        rc=proc.poll()
        if rc is not None:
            break
        time.sleep(1)
    rc=proc.poll()
    if rc is None:
        _kill_pid(proc.pid)
        return "the launcher did not finish starting the new version"
    if rc!=0 and not _launch_confirmed(root,target_version):
        return f"the launcher stopped with exit code {rc}"
    app_pid=_read_app_pid(root)
    end=time.time()+max(30,int(timeout or 180))
    dead_since=0.0
    while time.time()<end:
        if _launch_confirmed(root,target_version):
            return ""
        if app_pid and not _pid_running(app_pid):
            dead_since=dead_since or time.time()
            if time.time()-dead_since>3:
                return "the new version closed before it finished starting"
        time.sleep(1)
    if _launch_confirmed(root,target_version):
        return ""
    _kill_pid(app_pid)
    return f"the new version did not confirm a healthy start within {int(timeout or 180)} seconds"
def _record_result(root,ok,target_version,previous_version,message,keep_pending=False):
    def _mut(state):
        state["update_in_progress"]=bool(keep_pending)
        if not keep_pending:
            state["pending_version"]=""
        state["rollback_snapshot"]=""
        for key in ("staged_version","staged_package","staged_sha256","staged_at"):
            state[key]=""
        if not ok:
            state["current_version"]=previous_version or state.get("current_version","")
            state["last_error"]=message
            state["last_error_kind"]="update_failed"
            state["recovery_required"]=False
            state["recovery_reason"]=""
            state["last_launch_ok"]=True
            state["last_launch_error"]=""
        state["last_checked"]=_now()
        state["last_update_result"]={"ok":bool(ok),"version":target_version,"previous_version":previous_version,"message":message,"at":_now(),"acknowledged":False}
    return _set_state(root,_mut)
def _relaunch_quietly(root,launcher_python,launcher_script):
    try:
        _launch_runnote(launcher_python,launcher_script,root)
    except Exception as e:
        _append_log(root,"[!]",f"Relaunch failed: {e}")
def _validate_plan(plan):
    if not isinstance(plan,dict):
        raise RuntimeError("Invalid update plan.")
    root=os.path.abspath(_norm(plan.get("root_dir","")))
    package_path=os.path.abspath(_norm(plan.get("package_path","")))
    manifest=plan.get("manifest",{}) if isinstance(plan.get("manifest",{}),dict) else {}
    version=_norm(plan.get("target_version","") or manifest.get("version",""))
    if not _is_semver(version):
        raise RuntimeError("Update plan target_version must use X.X.X format.")
    tag=_norm(manifest.get("source_tag",""))
    if tag and tag.lower()!=f"v{version}".lower():
        raise RuntimeError("Update plan source_tag does not match target_version.")
    repo=_norm(manifest.get("source_repo",""))
    if repo and not _is_official_repo(repo):
        raise RuntimeError("Update plan source_repo is not the official LOYA repository.")
    requested_url=_norm(plan.get("requested_url",""))
    if requested_url and not _is_official_package_url(requested_url):
        raise RuntimeError("Update plan package URL is not from the official repository.")
    if not root or not os.path.isdir(root):
        raise RuntimeError("Update plan root_dir is invalid.")
    if not package_path or not os.path.isfile(package_path):
        raise RuntimeError("Update package file is missing.")
    expected_sha=_norm(plan.get("expected_sha256","")).lower()
    if not re.fullmatch(r"[a-f0-9]{64}",expected_sha):
        raise RuntimeError("Update plan is missing package_sha256.")
    if not _norm(plan.get("code_snapshot","")) or not os.path.isfile(_norm(plan.get("code_snapshot",""))):
        raise RuntimeError("Update plan has no code snapshot to roll back to.")
    return root,package_path
def _cleanup_stage(root,stage_dir):
    stage=os.path.abspath(_norm(stage_dir))
    if stage and _within_root(stage,os.path.join(root,"Backups","PendingUpdate")) and stage!=os.path.abspath(os.path.join(root,"Backups","PendingUpdate")):
        shutil.rmtree(stage,ignore_errors=True)
def main():
    if len(sys.argv)<2:
        return 2
    plan_path=os.path.abspath(sys.argv[1])
    plan=_read_json(plan_path,{})
    try:
        root,package_path=_validate_plan(plan)
    except Exception as e:
        root=os.path.abspath(_norm((plan or {}).get("root_dir",""))) if isinstance(plan,dict) else ""
        if root and os.path.isdir(root):
            _append_log(root,"[!]",f"Update plan refused: {e}")
        return 2
    current_version=_norm(plan.get("current_version",""))
    target_version=_norm(plan.get("target_version",""))
    parent_pid=int(plan.get("parent_pid",0) or 0)
    expected_sha=_norm(plan.get("expected_sha256","")).lower()
    preserve_paths=[_norm_rel(p) for p in plan.get("preserve_paths",[]) if _norm_rel(p)]
    allowed_dirs=[_norm(p) for p in plan.get("allowed_dirs",[]) if _norm(p)]
    allowed_files=[_norm(p) for p in plan.get("allowed_files",[]) if _norm(p)]
    required_dirs=[_norm(p) for p in plan.get("required_dirs",[]) if _norm(p)]
    required_files=[_norm(p) for p in plan.get("required_files",[]) if _norm(p)]
    launcher_python=_norm(plan.get("launcher_python","")) or sys.executable
    launcher_script=os.path.abspath(_norm(plan.get("launcher_script","")) or os.path.join(root,"RunNote.py"))
    code_snapshot=os.path.abspath(_norm(plan.get("code_snapshot","")))
    relaunch=bool(plan.get("relaunch",True))
    confirm_timeout=int(plan.get("confirm_timeout",180) or 180)
    for name in allowed_dirs+allowed_files:
        if "/" in name or "\\" in name or name in ("..",".") or name.split("/")[0] in _SKIP_TOP_LEVEL:
            _append_log(root,"[!]",f"Update plan lists a forbidden target: {name}")
            return 2
    _append_log(root,"[*]",f"Apply helper started for {target_version} (from {current_version}) plan={plan_path}")
    if not _wait_for_exit(parent_pid,180):
        msg=f"Update to {target_version} was not applied: LOYA NG (PID {parent_pid}) did not close within 3 minutes."
        _append_log(root,"[!]",msg)
        _record_result(root,False,target_version,current_version,msg)
        return 3
    # Hash a private copy and extract that same copy, so the zip cannot be swapped between the check and the extraction.
    verified_dir=tempfile.mkdtemp(prefix="loya_update_pkg_")
    verified_pkg=os.path.join(verified_dir,"package.zip")
    try:copied_sha=_copy_hashed(package_path,verified_pkg)
    except OSError:copied_sha=""
    if copied_sha.lower()!=expected_sha:
        shutil.rmtree(verified_dir,ignore_errors=True)
        msg=f"Update to {target_version} was refused: the package no longer matches its verified SHA-256. Nothing was changed."
        _append_log(root,"[!]",msg)
        _record_result(root,False,target_version,current_version,msg)
        _cleanup_stage(root,plan.get("stage_dir",""))
        if relaunch:_relaunch_quietly(root,launcher_python,launcher_script)
        return 4
    tmp=tempfile.mkdtemp(prefix="loya_update_apply_")
    apply_started=False
    failure=""
    try:
        _safe_extract(verified_pkg,tmp)
        source_root=_locate_source_root(tmp,required_dirs,required_files)
        # From the first replaced folder on, any error means a rollback.
        apply_started=True
        for top in allowed_dirs:
            if not os.path.isdir(os.path.join(source_root,top)) and top not in required_dirs:
                continue
            preserve=tuple(_norm_rel(p.split("/",1)[1]) for p in preserve_paths if p.startswith(top+"/"))
            _replace_dir(root,source_root,top,preserve_paths=preserve)
        for name in allowed_files:
            _replace_file(root,source_root,name)
        _write_version_files(root,target_version)
        _set_state(root,lambda state:(state.__setitem__("last_error",""),state.__setitem__("last_checked",_now()),state.__setitem__("current_version",target_version)))
        _append_log(root,"[+]",f"Update files applied for {target_version}")
    except Exception as e:
        failure=f"applying the files failed ({_norm(e)})"
    finally:
        shutil.rmtree(tmp,ignore_errors=True)
        shutil.rmtree(verified_dir,ignore_errors=True)
    if not failure and not relaunch:
        return 0
    if not failure:
        try:
            proc=_launch_runnote(launcher_python,launcher_script,root)
            _append_log(root,"[*]",f"Relaunched RunNote (PID {proc.pid}); waiting for the new version to confirm a healthy start")
            reason=_await_launch_confirmation(root,proc,target_version,confirm_timeout)
            if not reason:
                _append_log(root,"[+]",f"Update to {target_version} confirmed healthy")
                _cleanup_stage(root,plan.get("stage_dir",""))
                return 0
            failure=reason
        except Exception as e:
            failure=f"the new version could not be started ({_norm(e)})"
    if not apply_started:
        msg=f"Update to {target_version} was not applied: {failure}. Nothing was changed."
        _append_log(root,"[!]",msg)
        _record_result(root,False,target_version,current_version,msg)
        if relaunch:_relaunch_quietly(root,launcher_python,launcher_script)
        return 5
    _append_log(root,"[!]",f"Update to {target_version} failed: {failure}. Rolling back to {current_version}.")
    try:
        _restore_snapshot(root,code_snapshot)
        _write_version_files(root,current_version)
        msg=f"Update to {target_version} failed ({failure}) and was rolled back to {current_version}. Your data was not changed."
        _append_log(root,"[*]",f"Rollback restored from {code_snapshot}")
        _record_result(root,False,target_version,current_version,msg)
        if relaunch:_relaunch_quietly(root,launcher_python,launcher_script)
        return 5
    except Exception as rollback_err:
        rerr=_norm(rollback_err)
        _append_log(root,"[!]",f"Rollback failed: {rerr}")
        _mark_waiting_launch(root,f"Update to {target_version} failed ({failure}) and the automatic rollback failed ({rerr}). Run RunNote.py --recovery and choose Downgrade Last Version.")
        return 6
if __name__=="__main__":
    raise SystemExit(main())
