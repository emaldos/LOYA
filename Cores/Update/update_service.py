import hashlib,json,os,shutil,socket,ssl,subprocess,sys,tempfile,threading,time,urllib.error,urllib.request,zipfile
from datetime import datetime,timedelta,timezone
from pathlib import Path
from . import update_helpers as _helpers
from Cores import settings_lock as _settings_lock
_STATE_VERSION_FIELDS=("current_version","last_available_version","pending_version","last_good_version")
_STATE_TEXT_FIELDS=("last_checked","last_error","last_error_kind","source_repo","source_owner","source_name","source_tag","last_available_tag","package_sha256","release_id","commit_sha","remote_manifest_url","last_launch_started_at","last_launch_completed_at","last_launch_error","recovery_reason","release_name","release_published_at","release_html_url","asset_name","staged_version","staged_package","staged_sha256","staged_at","rollback_snapshot")
_STATE_BOOL_FIELDS=("update_in_progress","last_launch_ok","recovery_required")
# What an update may replace. Data/, Logs/, Backups/, the venvs and .git are never listed, so they are never touched.
_ALLOWED_UPDATE_DIRS=("Assets","Cores","UI","AI Template")
_ALLOWED_UPDATE_FILES=("LOYA_Note.py","RunNote.py","Requirements.json","README.md","LICENSE","DISCLAIMER.md","resetPIN.py")
_REQUIRED_UPDATE_DIRS=("Assets","Cores","UI")
_REQUIRED_UPDATE_FILES=("LOYA_Note.py","RunNote.py","Requirements.json","Cores/Update/CurrentVersion.info","Cores/Update/apply_update.py","UI/windows/main.html")
# Runtime files that live inside replaced folders and must survive an update.
_PRESERVE_UPDATE_PATHS=("Cores/Update/CurrentVersion.info","Cores/Update/state.json","Cores/Update/OldVersions","UI/js/appearance-boot.js")
ON_AVAILABLE_MODES=("ask","background","notify")
REMIND_LATER_HOURS=8
LAUNCH_CONFIRM_TIMEOUT=180
_HTTP_HEADERS={"User-Agent":"LOYA-NG-Updater","X-GitHub-Api-Version":"2022-11-28"}
class UpdateError(Exception):
    # kind: offline | rate_limited | no_release | tls | http | integrity | package | cancelled | error
    def __init__(self,message,kind="error"):
        super().__init__(message)
        self.kind=kind
class UpdateCancelled(UpdateError):
    def __init__(self):
        super().__init__("Update download was cancelled.","cancelled")
def _utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())
def _safe_name(text,fallback):
    raw="".join(ch if ch.isalnum() or ch in ("-","_",".") else "_" for ch in str(text or "").strip())
    raw=raw.strip("._")
    return raw or fallback
def _log_update(tag,msg):
    try:
        path=_helpers.update_log_path()
        os.makedirs(os.path.dirname(path),exist_ok=True)
        with open(path,"a",encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {tag} {msg}\n")
    except Exception:
        pass
def _progress(progress,val,msg):
    if not progress:
        return
    if callable(progress):
        try:progress(int(val),str(msg))
        except Exception:pass
        return
    try:
        progress.setValue(int(val))
    except Exception:
        pass
    try:
        progress._label.setText(str(msg))
    except Exception:
        pass
def default_update_state(current_version=""):
    version=_helpers.coerce_local_version(current_version,_helpers.DEFAULT_APP_VERSION)
    return {"current_version":version,"last_checked":"","last_available_version":"","pending_version":"","last_good_version":version,"update_in_progress":False,"last_error":"","source_repo":_helpers.OFFICIAL_SOURCE_REPO,"source_owner":_helpers.OFFICIAL_SOURCE_OWNER,"source_name":_helpers.OFFICIAL_SOURCE_NAME,"source_tag":_helpers.version_to_tag(version),"last_available_tag":"","package_sha256":"","release_id":"","commit_sha":"","remote_manifest_url":_helpers.GITHUB_RELEASES_API_URL,"last_launch_started_at":"","last_launch_completed_at":"","last_launch_ok":True,"last_launch_error":"","recovery_required":False,"recovery_reason":"","last_error_kind":"","release_name":"","release_notes":"","release_published_at":"","release_html_url":"","asset_name":"","asset_size":0,"staged_version":"","staged_package":"","staged_sha256":"","staged_at":"","rollback_snapshot":"","last_update_result":{}}
def normalize_update_state(data,current_version=""):
    version=_helpers.coerce_local_version(current_version,_helpers.DEFAULT_APP_VERSION)
    out=default_update_state(version)
    changed=not isinstance(data,dict)
    if isinstance(data,dict):
        out.update(data)
    for key in _STATE_TEXT_FIELDS:
        val=out.get(key,"")
        norm=_helpers.normalize_text(val)
        if norm!=val:
            out[key]=norm
            changed=True
    for key in _STATE_VERSION_FIELDS:
        val=out.get(key,"")
        norm=_helpers.coerce_local_version(val,"")
        if key=="current_version" and not norm:
            norm=version
        if key=="last_good_version" and not norm:
            norm=out.get("current_version") or version
        if norm!=val:
            out[key]=norm
            changed=True
    for key in _STATE_BOOL_FIELDS:
        val=out.get(key)
        norm=bool(val)
        if norm is not val:
            out[key]=norm
            changed=True
    try:size=max(0,int(out.get("asset_size") or 0))
    except Exception:size=0
    if size!=out.get("asset_size"):
        out["asset_size"]=size
        changed=True
    if not isinstance(out.get("release_notes"),str):
        out["release_notes"]=str(out.get("release_notes") or "")
        changed=True
    if not isinstance(out.get("last_update_result"),dict):
        out["last_update_result"]={}
        changed=True
    if out["source_repo"]!=_helpers.OFFICIAL_SOURCE_REPO:
        out["source_repo"]=_helpers.OFFICIAL_SOURCE_REPO
        changed=True
    if out["source_owner"]!=_helpers.OFFICIAL_SOURCE_OWNER:
        out["source_owner"]=_helpers.OFFICIAL_SOURCE_OWNER
        changed=True
    if out["source_name"]!=_helpers.OFFICIAL_SOURCE_NAME:
        out["source_name"]=_helpers.OFFICIAL_SOURCE_NAME
        changed=True
    if out["remote_manifest_url"]!=_helpers.GITHUB_RELEASES_API_URL:
        out["remote_manifest_url"]=_helpers.GITHUB_RELEASES_API_URL
        changed=True
    sha=_helpers.normalize_sha256(out.get("package_sha256",""))
    if sha!=out.get("package_sha256",""):
        out["package_sha256"]=sha
        changed=True
    commit=_helpers.normalize_commit_sha(out.get("commit_sha",""))
    if commit!=out.get("commit_sha",""):
        out["commit_sha"]=commit
        changed=True
    expected_tag=_helpers.version_to_tag(out.get("current_version") or version)
    tag=_helpers.normalize_text(out.get("source_tag",""))
    if tag and tag!=expected_tag:
        tag=expected_tag
        changed=True
    if not tag:
        tag=expected_tag
        changed=True
    out["source_tag"]=tag
    expected_latest_tag=_helpers.version_to_tag(out.get("last_available_version") or "")
    latest_tag=_helpers.normalize_text(out.get("last_available_tag",""))
    if expected_latest_tag:
        if latest_tag!=expected_latest_tag:
            latest_tag=expected_latest_tag
            changed=True
    elif latest_tag:
        latest_tag=""
        changed=True
    out["last_available_tag"]=latest_tag
    return out,changed
def write_current_version(version):
    ver=_helpers.coerce_local_version(version,_helpers.DEFAULT_APP_VERSION)
    _helpers.write_text(_helpers.version_info_path(),ver+"\n")
    return ver
def get_app_version():
    cur=_helpers.read_text(_helpers.version_info_path(),"")
    ver=_helpers.coerce_local_version(cur,"")
    if not ver:
        legacy=_helpers.read_text(_helpers.legacy_version_info_path(),"")
        ver=_helpers.coerce_local_version(legacy,_helpers.DEFAULT_APP_VERSION)
    return write_current_version(ver or _helpers.DEFAULT_APP_VERSION)
def get_update_state(current_version=""):
    version=_helpers.coerce_local_version(current_version,get_app_version())
    data=_helpers.read_json(_helpers.update_state_path(),None)
    state,changed=normalize_update_state(data,version)
    if changed or not _helpers.update_state_path().is_file():
        _helpers.write_json(_helpers.update_state_path(),state)
    return state
def write_update_state(state,current_version=""):
    version=_helpers.coerce_local_version(current_version,get_app_version())
    out,_=normalize_update_state(state,version)
    _helpers.write_json(_helpers.update_state_path(),out)
    return out
def ensure_runtime_files(current_version=""):
    version=write_current_version(_helpers.coerce_local_version(current_version,get_app_version()))
    state=get_update_state(version)
    if state.get("current_version")!=version:
        state["current_version"]=version
        if not state.get("last_good_version"):
            state["last_good_version"]=version
        state=write_update_state(state,version)
    return {"version":version,"state":state}
def sync_installed_version(version=""):
    info=ensure_runtime_files(version)
    state=dict(info["state"])
    ver=info["version"]
    changed=False
    if state.get("current_version")!=ver:
        state["current_version"]=ver
        changed=True
    if not state.get("last_good_version"):
        state["last_good_version"]=ver
        changed=True
    expected_tag=_helpers.version_to_tag(ver)
    if state.get("source_tag")!=expected_tag:
        state["source_tag"]=expected_tag
        changed=True
    if changed:
        state=write_update_state(state,ver)
    return state
def get_windows_app_id(version=""):
    return _helpers.build_windows_app_id(version or get_app_version())
def get_app_identity():
    version=get_app_version()
    state=get_update_state(version)
    return {"app_name":_helpers.APP_NAME,"version":version,"display_version":version,"window_title":f"{_helpers.APP_NAME} v{version}","windows_app_id":get_windows_app_id(version),"source_repo":state.get("source_repo",_helpers.OFFICIAL_SOURCE_REPO),"source_owner":state.get("source_owner",_helpers.OFFICIAL_SOURCE_OWNER),"source_name":state.get("source_name",_helpers.OFFICIAL_SOURCE_NAME),"source_tag":state.get("source_tag",_helpers.version_to_tag(version))}
def validate_remote_manifest(data):
    return _helpers.validate_remote_manifest(data)
# ---------- GitHub access ----------
class _GitHubOnlyRedirects(urllib.request.HTTPRedirectHandler):
    # urllib would follow a redirect to any host; refuse every hop that leaves HTTPS GitHub before a byte is read from it.
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        if not _helpers.is_allowed_download_redirect_url(newurl):
            raise UpdateError("The package download was redirected away from GitHub. The download was stopped.","integrity")
        return super().redirect_request(req,fp,code,msg,headers,newurl)
def _opener():
    # Proxies come from the environment / Windows Internet settings (urllib's default ProxyHandler).
    return urllib.request.build_opener(_GitHubOnlyRedirects)
def _rate_limit_text(headers):
    try:
        reset=int((headers or {}).get("X-RateLimit-Reset") or 0)
    except Exception:
        reset=0
    if reset>0:
        return time.strftime("%H:%M",time.localtime(reset))
    return ""
def _describe_error(exc,what):
    if isinstance(exc,UpdateError):
        return exc
    if isinstance(exc,urllib.error.HTTPError):
        code=int(getattr(exc,"code",0) or 0)
        headers=getattr(exc,"headers",None)
        if code==404:
            return UpdateError(f"No published release was found in {_helpers.OFFICIAL_SOURCE_OWNER}/{_helpers.OFFICIAL_SOURCE_NAME} yet.","no_release")
        remaining=str((headers or {}).get("X-RateLimit-Remaining","") if headers is not None else "")
        if code==429 or (code==403 and remaining=="0"):
            at=_rate_limit_text(headers)
            return UpdateError("GitHub API rate limit reached"+(f"; checks work again after {at}." if at else "; try again later."),"rate_limited")
        return UpdateError(f"GitHub answered HTTP {code} while {what}.","http")
    reason=getattr(exc,"reason",exc) if isinstance(exc,urllib.error.URLError) else exc
    if isinstance(reason,ssl.SSLError):
        return UpdateError(f"Secure connection to GitHub failed ({reason}). A proxy or security product may be intercepting HTTPS.","tls")
    if isinstance(reason,(socket.timeout,TimeoutError)):
        return UpdateError(f"GitHub did not answer in time while {what}.","offline")
    if isinstance(exc,(urllib.error.URLError,ConnectionError,OSError)):
        return UpdateError(f"Could not reach GitHub while {what} (offline, DNS, firewall or proxy): {reason}","offline")
    return UpdateError(f"{what[:1].upper()+what[1:]} failed: {exc}","error")
def _read_capped(resp,limit):
    data=resp.read(limit+1)
    if len(data)>limit:
        raise UpdateError("GitHub returned an unexpectedly large response.","http")
    return data
def _get_json(url,timeout,what):
    req=urllib.request.Request(url,headers=dict(_HTTP_HEADERS,Accept="application/vnd.github+json"))
    try:
        with _opener().open(req,timeout=float(timeout)) as resp:
            raw=_read_capped(resp,4*1024*1024)
    except Exception as e:
        raise _describe_error(e,what)
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        raise UpdateError("GitHub returned a response that is not valid JSON.","http")
def _pick_assets(assets,version):
    want=_helpers.expected_package_asset_name(version).lower()
    pkg=None;sums=None
    rows=[a for a in (assets if isinstance(assets,list) else []) if isinstance(a,dict) and _helpers.normalize_text(a.get("name",""))]
    for a in rows:
        if _helpers.normalize_text(a.get("name","")).lower()==want:
            pkg=a
    if pkg is None:
        zips=[a for a in rows if _helpers.normalize_text(a.get("name","")).lower().endswith(".zip")]
        named=[a for a in zips if _helpers.normalize_text(a.get("name","")).lower().startswith(_helpers.PACKAGE_ASSET_PREFIX.lower())]
        if len(named)==1:pkg=named[0]
        elif not named and len(zips)==1:pkg=zips[0]
    if pkg is not None:
        pkg_name=_helpers.normalize_text(pkg.get("name","")).lower()
        for a in rows:
            n=_helpers.normalize_text(a.get("name","")).lower()
            if n in {x.lower() for x in _helpers.CHECKSUM_ASSET_NAMES} or n==pkg_name+".sha256":
                sums=a
                if n==pkg_name+".sha256":break
    return pkg,sums
def _manifest_from_github_release(payload):
    if not isinstance(payload,dict):
        raise ValueError("GitHub release payload must be an object.")
    if payload.get("draft") or payload.get("prerelease"):
        raise ValueError("The latest GitHub release is a draft or pre-release; only stable releases are installed.")
    html_url=_helpers.normalize_text(payload.get("html_url",""))
    owner,name,repo_url=_helpers.canonical_repo_parts(html_url.rsplit("/releases/",1)[0] if "/releases/" in html_url else html_url)
    repo_url=repo_url or _helpers.OFFICIAL_SOURCE_REPO
    tag=_helpers.normalize_text(payload.get("tag_name",""))
    version=_helpers.tag_to_version(tag)
    pkg,sums=_pick_assets(payload.get("assets",[]),version)
    asset_name=_helpers.normalize_text((pkg or {}).get("name",""))
    body=str(payload.get("body") or "")
    manifest={"manifest_version":_helpers.REMOTE_MANIFEST_VERSION,"source_repo":repo_url,"source_owner":owner or _helpers.OFFICIAL_SOURCE_OWNER,"source_name":name or _helpers.OFFICIAL_SOURCE_NAME,"version":version,"source_tag":tag,"package_sha256":"","release_id":_helpers.normalize_text(payload.get("id","")),"commit_sha":_helpers.normalize_commit_sha(payload.get("target_commitish","")),"html_url":html_url,"asset_url":_helpers.normalize_text((pkg or {}).get("browser_download_url","")),"asset_name":asset_name,"asset_size":(pkg or {}).get("size",0),"checksum_url":_helpers.normalize_text((sums or {}).get("browser_download_url","")),"digest_sha256":_helpers.sha256_from_asset_digest((pkg or {}).get("digest","")),"body_sha256":_helpers.sha256_from_release_body(body,asset_name) if asset_name else "","release_name":_helpers.normalize_text(payload.get("name","")),"release_notes":body,"published_at":_helpers.normalize_text(payload.get("published_at",""))}
    out=validate_remote_manifest(manifest)
    if out["asset_url"] and not _helpers.is_official_package_url(out["asset_url"],tag=out["source_tag"]):
        raise ValueError("The release package is not attached to the release it was announced in.")
    return out
def fetch_latest_release_manifest(timeout=10):
    payload=_get_json(_helpers.GITHUB_RELEASES_API_URL,timeout,"checking the latest release")
    return _manifest_from_github_release(payload)
def check_for_updates(timeout=10):
    state=get_update_state()
    try:
        manifest=fetch_latest_release_manifest(timeout=timeout)
        state=record_remote_manifest(manifest)
        state["last_error"]=""
        state["last_error_kind"]=""
        state=write_update_state(state,state.get("current_version",""))
        cur=state.get("current_version","")
        latest=state.get("last_available_version","")
        newer=bool(cur and latest and _helpers.compare_semver(latest,cur)>0)
        _log_update("[*]",f"Update check: current={cur} latest={latest} newer={newer}")
        return {"ok":True,"state":state,"manifest":manifest,"update_available":newer,"error":"","error_kind":""}
    except Exception as e:
        err=_describe_error(e,"checking the latest release") if not isinstance(e,ValueError) else UpdateError(str(e),"invalid_release")
        state=get_update_state()
        state["last_checked"]=_utc_now()
        state["last_error"]=_helpers.normalize_text(err)
        state["last_error_kind"]=err.kind
        state=write_update_state(state,state.get("current_version",""))
        _log_update("[-]",f"Update check failed ({err.kind}): {err}")
        return {"ok":False,"state":state,"manifest":None,"update_available":False,"error":str(err),"error_kind":err.kind}
def _apply_manifest_to_state(state,manifest):
    state=dict(state or {})
    norm=validate_remote_manifest(manifest)
    state["last_checked"]=_utc_now()
    state["last_available_version"]=norm["version"]
    state["source_repo"]=norm["source_repo"]
    state["source_owner"]=norm["source_owner"]
    state["source_name"]=norm["source_name"]
    state["last_available_tag"]=norm["source_tag"]
    state["package_sha256"]=norm["package_sha256"] or norm["digest_sha256"] or norm["body_sha256"]
    state["release_id"]=norm["release_id"]
    state["commit_sha"]=norm["commit_sha"]
    state["release_name"]=norm["release_name"]
    state["release_notes"]=norm["release_notes"]
    state["release_published_at"]=norm["published_at"]
    state["release_html_url"]=norm["html_url"]
    state["asset_name"]=norm["asset_name"]
    state["asset_size"]=norm["asset_size"]
    return state
def record_remote_manifest(manifest):
    state=get_update_state()
    state=_apply_manifest_to_state(state,manifest)
    return write_update_state(state,state.get("current_version",""))
def mark_update_pending(manifest,rollback_snapshot=""):
    state=get_update_state()
    state=_apply_manifest_to_state(state,manifest)
    state["pending_version"]=state.get("last_available_version","")
    state["update_in_progress"]=bool(state.get("pending_version"))
    state["last_error"]=""
    state["last_error_kind"]=""
    state["recovery_required"]=False
    state["recovery_reason"]=""
    state["rollback_snapshot"]=_helpers.normalize_text(rollback_snapshot)
    return write_update_state(state,state.get("current_version",""))
def _clear_staged(state):
    for key in ("staged_version","staged_package","staged_sha256","staged_at"):
        state[key]=""
    return state
def mark_update_completed(version="",release_id="",commit_sha="",package_sha256="",previous_version=""):
    ver=write_current_version(version or get_app_version())
    state=get_update_state(ver)
    state["current_version"]=ver
    state["last_good_version"]=ver
    state["pending_version"]=""
    state["last_available_version"]=ver
    state["update_in_progress"]=False
    state["last_error"]=""
    state["last_error_kind"]=""
    state["source_tag"]=_helpers.version_to_tag(ver)
    state["last_available_tag"]=_helpers.version_to_tag(ver)
    state["release_id"]=_helpers.normalize_text(release_id or state.get("release_id",""))
    state["commit_sha"]=_helpers.normalize_commit_sha(commit_sha or state.get("commit_sha",""))
    state["package_sha256"]=_helpers.normalize_sha256(package_sha256 or state.get("package_sha256",""))
    state["last_checked"]=_utc_now()
    state["recovery_required"]=False
    state["recovery_reason"]=""
    state["rollback_snapshot"]=""
    _clear_staged(state)
    state["last_update_result"]={"ok":True,"version":ver,"previous_version":_helpers.normalize_text(previous_version),"message":f"{_helpers.APP_NAME} was updated to {ver}.","at":_utc_now(),"acknowledged":False}
    return write_update_state(state,ver)
def mark_update_failed(error):
    state=get_update_state()
    state["update_in_progress"]=False
    state["pending_version"]=""
    state["last_error"]=_helpers.normalize_text(error)
    state["recovery_required"]=True
    state["recovery_reason"]=_helpers.normalize_text(error)
    return write_update_state(state,state.get("current_version",""))
def pending_update_matches_current_install(state=None,version=""):
    st=state if isinstance(state,dict) else get_update_state(version)
    ver=_helpers.coerce_local_version(version or st.get("current_version","") or get_app_version(),"")
    pending=_helpers.coerce_local_version(st.get("pending_version",""),"")
    return bool(st.get("update_in_progress") and ver and pending and pending==ver)
def finalize_pending_update_on_launch(version=""):
    ver=_helpers.coerce_local_version(version,get_app_version())
    state=get_update_state(ver)
    if not pending_update_matches_current_install(state,ver):
        return {"completed":False,"version":ver,"state":state}
    prev=_helpers.normalize_text(state.get("last_good_version",""))
    state=mark_update_completed(ver,release_id=state.get("release_id",""),commit_sha=state.get("commit_sha",""),package_sha256=state.get("package_sha256",""),previous_version=prev)
    _log_update("[+]",f"Update launch confirmed: {ver}")
    return {"completed":True,"version":ver,"state":state}
def confirm_launch_health():
    # Called once the new UI has loaded (update.launch_ready). The apply helper waits for this; without it the update is rolled back.
    from . import health_check as _health_check
    ver=get_app_version()
    state=get_update_state(ver)
    if not pending_update_matches_current_install(state,ver):
        return {"completed":False,"version":ver,"pending":False}
    report=_health_check.run_health_check(after_security=False)
    if report.fatal:
        _log_update("[!]",f"Post-update health check failed: {report.fatal_text()}")
        return {"completed":False,"version":ver,"pending":True,"error":report.fatal_text()}
    out=finalize_pending_update_on_launch(ver)
    return {"completed":bool(out.get("completed")),"version":ver,"pending":False}
# ---------- package checks ----------
def _relative_package_members(zip_path):
    _prefix,rows=_helpers.strip_package_prefix(_helpers.inspect_package_zip(zip_path))
    return rows
def _validate_package_archive(zip_path,version=""):
    try:
        rows=_helpers.inspect_package_zip(zip_path)
    except zipfile.BadZipFile:
        raise UpdateError("The downloaded package is not a valid zip file.","package")
    except ValueError as e:
        raise UpdateError(f"The downloaded package was refused: {e}","package")
    prefix,members=_helpers.strip_package_prefix(rows)
    files=set(members)
    for folder in _REQUIRED_UPDATE_DIRS:
        if not any(item.startswith(folder+"/") for item in files):
            raise UpdateError(f"Downloaded package is missing required folder: {folder}","package")
    for path in _REQUIRED_UPDATE_FILES:
        if path not in files:
            raise UpdateError(f"Downloaded package is missing required file: {path}","package")
    if version:
        inner=(prefix+"/" if prefix else "")+"Cores/Update/CurrentVersion.info"
        with zipfile.ZipFile(zip_path,"r") as zf:
            packaged=_helpers.coerce_local_version(zf.read(inner)[:64].decode("utf-8","ignore"),"")
        if packaged!=_helpers.normalize_semver(version,""):
            raise UpdateError(f"The package says it is version {packaged or '?'} but the release is {version}.","package")
    return {"entries":len(files),"files":sorted(files),"prefix":prefix}
def _sha256_file(path):
    h=hashlib.sha256()
    with open(path,"rb") as fh:
        for chunk in iter(lambda:fh.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()
def _download_small(url,timeout,limit):
    req=urllib.request.Request(url,headers=dict(_HTTP_HEADERS,Accept="application/octet-stream"))
    try:
        with _opener().open(req,timeout=float(timeout)) as resp:
            if not _helpers.is_allowed_download_redirect_url(resp.geturl() or url):
                raise UpdateError("The checksum download left GitHub.","integrity")
            return _read_capped(resp,limit).decode("utf-8","replace")
    except Exception as e:
        raise _describe_error(e,"downloading the release checksums")
def resolve_expected_sha256(manifest,timeout=20):
    # The expected hash comes from the official release itself: GitHub's own asset digest, a SHA256SUMS asset, and/or a SHA256 line in
    # the release notes. Every source present must agree; with none, the package is refused.
    found={}
    if manifest.get("digest_sha256"):found["GitHub asset digest"]=manifest["digest_sha256"]
    if manifest.get("body_sha256"):found["release notes"]=manifest["body_sha256"]
    if manifest.get("checksum_url"):
        text=_download_small(manifest["checksum_url"],timeout,_helpers.MAX_CHECKSUM_BYTES)
        sha=_helpers.parse_sha256_listing(text,manifest.get("asset_name",""))
        if not sha:
            lines=[ln for ln in text.splitlines() if ln.strip()]
            if len(lines)==1 and _helpers.normalize_sha256(lines[0].split()[0] if lines[0].split() else ""):
                sha=_helpers.normalize_sha256(lines[0].split()[0])
        if sha:found["checksum file"]=sha
    if not found:
        raise UpdateError("The release does not publish a SHA-256 for its package, so it cannot be verified. Install it manually from GitHub.","integrity")
    if len(set(found.values()))>1:
        detail=", ".join(f"{k}={v[:12]}..." for k,v in found.items())
        raise UpdateError(f"The release publishes conflicting SHA-256 values ({detail}). The update was refused.","integrity")
    return next(iter(found.values()))
def staging_root():
    return _helpers.root_dir().joinpath("Backups","PendingUpdate")
def _download_package(manifest,timeout=60,stage_dir=None,expected_sha256="",on_bytes=None,cancel=None):
    url=_helpers.normalize_text(manifest.get("asset_url",""))
    if not url:
        raise UpdateError(f"This release has no installable {_helpers.PACKAGE_ASSET_PREFIX}vX.Y.Z.zip package. Download it manually from the release page.","package")
    if not _helpers.is_official_package_url(url,manifest.get("source_owner",""),manifest.get("source_name",""),manifest.get("source_tag","")):
        raise UpdateError("Authenticated release package URL does not belong to the official repository.","integrity")
    expected=_helpers.normalize_sha256(expected_sha256)
    if not expected:
        raise UpdateError("No verified SHA-256 is known for this package.","integrity")
    stage=Path(stage_dir or tempfile.mkdtemp(prefix="loya_update_")).resolve()
    stage.mkdir(parents=True,exist_ok=True)
    name=_safe_name(manifest.get("asset_name") or "release_package.zip","release_package.zip")
    pkg_path=stage.joinpath(name)
    part=stage.joinpath(name+".part")
    declared=int(manifest.get("asset_size") or 0)
    limit=min(declared,_helpers.MAX_PACKAGE_BYTES) if declared else _helpers.MAX_PACKAGE_BYTES
    if pkg_path.is_file() and _sha256_file(pkg_path)==expected:
        return {"path":str(pkg_path),"sha256":expected,"requested_url":url,"final_url":url,"stage_dir":str(stage),"reused":True}
    sha=hashlib.sha256()
    have=0
    if part.is_file():
        have=part.stat().st_size
        if have>=limit:
            part.unlink();have=0
        else:
            with open(part,"rb") as fh:
                for chunk in iter(lambda:fh.read(1024*1024),b""):sha.update(chunk)
    headers=dict(_HTTP_HEADERS,Accept="application/octet-stream")
    if have:headers["Range"]=f"bytes={have}-"
    req=urllib.request.Request(url,headers=headers)
    try:
        with _opener().open(req,timeout=float(timeout)) as resp:
            final_url=_helpers.normalize_text(resp.geturl() or url)
            if not _helpers.is_allowed_download_redirect_url(final_url):
                raise UpdateError("Downloaded package redirected to a non-GitHub host.","integrity")
            status=int(getattr(resp,"status",200) or 200)
            if have and status!=206:
                sha=hashlib.sha256();have=0
            mode="ab" if have else "wb"
            try:
                length=int(resp.headers.get("Content-Length") or 0)
            except Exception:
                length=0
            if length and have+length>limit:
                raise UpdateError("The package is larger than the size published in the release.","integrity")
            total=declared or (have+length)
            got=have
            with open(part,mode) as fh:
                while True:
                    if cancel is not None and cancel.is_set():
                        raise UpdateCancelled()
                    chunk=resp.read(256*1024)
                    if not chunk:break
                    got+=len(chunk)
                    if got>limit:
                        raise UpdateError("The package is larger than the size published in the release.","integrity")
                    fh.write(chunk)
                    sha.update(chunk)
                    if on_bytes:
                        try:on_bytes(got,total)
                        except Exception:pass
    except UpdateCancelled:
        raise
    except Exception as e:
        raise _describe_error(e,"downloading the update package")
    if declared and got!=declared:
        raise UpdateError(f"The download stopped early ({got} of {declared} bytes). Try again to resume.","offline")
    digest=sha.hexdigest()
    if digest!=expected:
        try:part.unlink()
        except OSError:pass
        raise UpdateError(f"Integrity check failed: the downloaded package's SHA-256 ({digest[:16]}...) does not match the SHA-256 published in the official release ({expected[:16]}...). The package was deleted and nothing was changed.","integrity")
    os.replace(part,pkg_path)
    return {"path":str(pkg_path),"sha256":digest,"requested_url":url,"final_url":final_url,"stage_dir":str(stage),"reused":False}
def stage_update(timeout=60,progress=None,cancel=None,manifest=None):
    """Download + verify + validate the latest release into Backups/PendingUpdate/<tag>/ without touching the install."""
    current_version=get_app_version()
    _progress(progress,3,"Checking the official release ...")
    manifest=manifest or fetch_latest_release_manifest(timeout=min(20,timeout))
    if _helpers.compare_semver(manifest["version"],current_version)<=0:
        raise UpdateError("You are already on the latest authenticated version.","up_to_date")
    _progress(progress,6,"Reading the published SHA-256 ...")
    expected=resolve_expected_sha256(manifest,timeout=min(20,timeout))
    stage=staging_root().joinpath(_helpers.version_to_tag(manifest["version"]))
    def on_bytes(got,total):
        pct=6+int(54*got/total) if total else 30
        _progress(progress,min(60,pct),f"Downloading {got//1024:,} KB"+(f" of {total//1024:,} KB" if total else "")+" ...")
    _progress(progress,8,"Downloading the package ...")
    package_info=_download_package(manifest,timeout=timeout,stage_dir=str(stage),expected_sha256=expected,on_bytes=on_bytes,cancel=cancel)
    _progress(progress,62,"Verifying the package contents ...")
    try:
        package_meta=_validate_package_archive(package_info["path"],manifest["version"])
    except UpdateError:
        try:os.remove(package_info["path"])
        except OSError:pass
        raise
    manifest=dict(manifest);manifest["package_sha256"]=package_info["sha256"]
    manifest=validate_remote_manifest(manifest)
    _helpers.write_json(stage.joinpath("manifest.json"),manifest)
    state=record_remote_manifest(manifest)
    state["staged_version"]=manifest["version"]
    state["staged_package"]=package_info["path"]
    state["staged_sha256"]=package_info["sha256"]
    state["staged_at"]=_utc_now()
    state=write_update_state(state,state.get("current_version",""))
    _log_update("[+]",f"Update {manifest['version']} downloaded and verified (sha256={package_info['sha256']}) -> {package_info['path']}")
    return {"manifest":manifest,"package":package_info,"package_meta":package_meta,"stage_dir":str(stage),"state":state}
def _write_update_plan(stage_dir,manifest,package_info,backups,parent_pid=0,launcher_python="",launcher_script="",relaunch=True):
    stage=Path(stage_dir).resolve()
    plan={"plan_version":2,"created_at":_utc_now(),"root_dir":str(_helpers.root_dir().resolve()),"parent_pid":int(parent_pid or 0),"launcher_python":launcher_python or _console_python(),"launcher_script":launcher_script or str(_helpers.root_dir().joinpath("RunNote.py")),"package_path":package_info.get("path",""),"expected_sha256":package_info.get("sha256",""),"requested_url":package_info.get("requested_url",""),"final_url":package_info.get("final_url",""),"stage_dir":str(stage),"current_version":get_app_version(),"target_version":manifest.get("version",""),"manifest":{k:v for k,v in manifest.items() if k!="release_notes"},"data_backup":backups.get("data_backup",""),"code_snapshot":backups.get("code_snapshot",""),"allowed_dirs":list(_ALLOWED_UPDATE_DIRS),"allowed_files":list(_ALLOWED_UPDATE_FILES),"required_dirs":list(_REQUIRED_UPDATE_DIRS),"required_files":list(_REQUIRED_UPDATE_FILES),"preserve_paths":list(_PRESERVE_UPDATE_PATHS),"relaunch":bool(relaunch),"confirm_timeout":LAUNCH_CONFIRM_TIMEOUT}
    path=stage.joinpath("update_plan.json")
    _helpers.write_json(path,plan)
    return str(path)
def _console_python(python_exe=""):
    py=os.path.abspath(python_exe or sys.executable)
    if os.name=="nt" and py.lower().endswith("pythonw.exe"):
        alt=py[:-5]+".exe"
        if os.path.isfile(alt):return alt
    return py
def default_launcher():
    """(python, RunNote.py) used to relaunch the app after an update."""
    return _console_python(),str(_helpers.root_dir().joinpath("RunNote.py"))
def _spawn_apply_helper(helper_path,plan_path):
    # -I: the helper runs from a temp folder; isolated mode keeps that folder (and PYTHON* variables, user site-packages) off sys.path.
    args=[_console_python(),"-I",helper_path,plan_path]
    stdin=subprocess.DEVNULL
    stdout=subprocess.DEVNULL
    stderr=subprocess.DEVNULL
    if os.name=="nt":
        flags=0x00000008|0x00000200|0x08000000
        proc=subprocess.Popen(args,stdin=stdin,stdout=stdout,stderr=stderr,cwd=os.path.dirname(helper_path),creationflags=flags)
    else:
        proc=subprocess.Popen(args,stdin=stdin,stdout=stdout,stderr=stderr,cwd=os.path.dirname(helper_path),start_new_session=True)
    return int(getattr(proc,"pid",0) or 0)
def _prepare_and_spawn(manifest,package_info,stage_dir,parent_pid=0,launcher_python="",launcher_script="",progress=None):
    current_version=get_app_version()
    _progress(progress,66,"Backing up Data/ and the current code ...")
    from . import backup_restore as _backup_restore
    backups=_backup_restore.prepare_update_backups(current_version=current_version,reason=f"update_{manifest['version']}",progress=None,root_dir=_helpers.root_dir())
    _progress(progress,88,"Writing the update plan ...")
    helper_src=_helpers.update_dir().joinpath("apply_update.py")
    if not helper_src.is_file():
        raise FileNotFoundError("Missing updater apply helper: Cores/Update/apply_update.py")
    # The helper runs from a temp copy, so replacing Cores/Update/ never touches the running helper file.
    helper_dir=tempfile.mkdtemp(prefix="loya_update_helper_")
    helper_dst=Path(helper_dir).joinpath("apply_update.py")
    shutil.copy2(helper_src,helper_dst)
    plan_path=_write_update_plan(stage_dir,manifest,package_info,backups,parent_pid=parent_pid,launcher_python=launcher_python,launcher_script=launcher_script)
    state=mark_update_pending(manifest,rollback_snapshot=backups.get("code_snapshot",""))
    _progress(progress,94,"Starting the updater ...")
    helper_pid=_spawn_apply_helper(str(helper_dst),plan_path)
    _log_update("[+]",f"Update staged: current={current_version} target={manifest['version']} helper_pid={helper_pid} package={package_info['path']}")
    return {"state":state,"backups":backups,"plan_path":plan_path,"helper_pid":helper_pid}
def start_update_install(timeout=60,parent_pid=0,launcher_python="",launcher_script="",progress=None,cancel=None):
    stage_dir=""
    pending_marked=False
    try:
        staged=stage_update(timeout=timeout,progress=progress,cancel=cancel)
        manifest=staged["manifest"];package_info=staged["package"];stage_dir=staged["stage_dir"]
        if cancel is not None and cancel.is_set():
            raise UpdateCancelled()
        out=_prepare_and_spawn(manifest,package_info,stage_dir,parent_pid=parent_pid,launcher_python=launcher_python,launcher_script=launcher_script,progress=progress)
        pending_marked=True
        _progress(progress,100,f"Ready. {_helpers.APP_NAME} will restart to finish the update.")
        return {"ok":True,"state":out["state"],"manifest":manifest,"package":package_info,"package_meta":staged["package_meta"],"backups":out["backups"],"plan_path":out["plan_path"],"helper_pid":out["helper_pid"],"stage_dir":stage_dir,"error":"","error_kind":""}
    except Exception as e:
        err=e if isinstance(e,UpdateError) else UpdateError(str(e),"error")
        if pending_marked:
            try:mark_update_failed(str(err))
            except Exception:pass
        _log_update("[!]",f"Update start failed ({err.kind}): {err}")
        return {"ok":False,"state":get_update_state(),"manifest":None,"package":None,"package_meta":None,"backups":None,"plan_path":"","helper_pid":0,"stage_dir":stage_dir,"error":str(err),"error_kind":err.kind}
def staged_update_info(state=None):
    st=state if isinstance(state,dict) else get_update_state()
    ver=_helpers.normalize_semver(st.get("staged_version",""),"")
    pkg=_helpers.normalize_text(st.get("staged_package",""))
    if not ver or not pkg or not os.path.isfile(pkg):
        return None
    try:
        if _helpers.compare_semver(ver,st.get("current_version") or get_app_version())<=0:
            return None
    except Exception:
        return None
    return {"version":ver,"package":pkg,"sha256":_helpers.normalize_sha256(st.get("staged_sha256","")),"stage_dir":os.path.dirname(pkg)}
def launch_staged_update(parent_pid=0,launcher_python="",launcher_script=""):
    """Used by RunNote.py at startup ("install on next restart"): re-verify the staged package, back up, and hand off to the helper."""
    info=staged_update_info()
    if not info:
        return {"ok":False,"started":False,"error":""}
    try:
        state=get_update_state()
        if state.get("update_in_progress"):
            return {"ok":False,"started":False,"error":"An update is already in progress."}
        if not info["sha256"] or _sha256_file(info["package"])!=info["sha256"]:
            raise UpdateError("The downloaded update no longer matches its verified SHA-256 and was discarded.","integrity")
        manifest=validate_remote_manifest(_helpers.read_json(os.path.join(info["stage_dir"],"manifest.json"),{}) or {})
        if manifest.get("version")!=info["version"] or _helpers.normalize_sha256(manifest.get("package_sha256",""))!=info["sha256"]:
            raise UpdateError("The staged update's manifest does not match the verified package.","integrity")
        _validate_package_archive(info["package"],info["version"])
        package_info={"path":info["package"],"sha256":info["sha256"],"requested_url":manifest.get("asset_url",""),"final_url":""}
        out=_prepare_and_spawn(manifest,package_info,info["stage_dir"],parent_pid=parent_pid,launcher_python=launcher_python,launcher_script=launcher_script)
        return {"ok":True,"started":True,"version":info["version"],"helper_pid":out["helper_pid"],"error":""}
    except Exception as e:
        err=str(e)
        _log_update("[!]",f"Staged update not applied: {err}")
        st=_clear_staged(get_update_state())
        st["last_error"]=err
        write_update_state(st,st.get("current_version",""))
        shutil.rmtree(info["stage_dir"],ignore_errors=True)
        return {"ok":False,"started":False,"error":err}
def discard_staged_update():
    st=get_update_state()
    info=staged_update_info(st)
    if info:shutil.rmtree(info["stage_dir"],ignore_errors=True)
    write_update_state(_clear_staged(st),st.get("current_version",""))
    return True
# ---------- settings (Data/settings.json "update") ----------
def _settings_path():
    return os.path.join(str(_helpers.root_dir()),"Data","settings.json")
def _read_settings():
    d=_settings_lock.read_json(_settings_path(),{})
    return d if isinstance(d,dict) else {}
def _norm(s):return (str(s) if s is not None else "").strip()
def _to_int(v,default):
    try:return int(str(v).strip())
    except Exception:return default
def get_update_settings():
    d=_read_settings()
    u=d.get("update",{}) if isinstance(d.get("update",{}),dict) else {}
    hrs=max(1,_to_int(u.get("check_interval_hours",24),24))
    channel=_norm(u.get("last_channel","stable")) or "stable"
    mode=_norm(u.get("on_available","ask")).lower()
    if mode not in ON_AVAILABLE_MODES:mode="ask"
    return {"auto_enabled":bool(u.get("auto_enabled",False)),"check_interval_hours":hrs,"repo_url":_helpers.OFFICIAL_SOURCE_REPO,"manifest_url":_helpers.GITHUB_RELEASES_API_URL,"last_checked":_norm(u.get("last_checked","")),"last_channel":channel,"on_available":mode,"skipped_version":_helpers.normalize_semver(u.get("skipped_version",""),""),"remind_version":_helpers.normalize_semver(u.get("remind_version",""),""),"remind_until":_norm(u.get("remind_until","")),"remind_session":_norm(u.get("remind_session","")),"notified_version":_helpers.normalize_semver(u.get("notified_version",""),"")}
def save_update_settings(cfg):
    """Merge the given keys into settings.json "update" under the settings lock; unknown or invalid values are ignored."""
    cfg=cfg if isinstance(cfg,dict) else {}
    def mutate(d):
        cur=d.get("update",{}) if isinstance(d.get("update",{}),dict) else {}
        if "auto_enabled" in cfg:cur["auto_enabled"]=bool(cfg.get("auto_enabled"))
        if "check_interval_hours" in cfg:cur["check_interval_hours"]=max(1,_to_int(cfg.get("check_interval_hours"),24))
        if "last_checked" in cfg:cur["last_checked"]=_norm(cfg.get("last_checked"))
        if "last_channel" in cfg:cur["last_channel"]=_norm(cfg.get("last_channel")) or "stable"
        if "on_available" in cfg:
            mode=_norm(cfg.get("on_available")).lower()
            if mode in ON_AVAILABLE_MODES:cur["on_available"]=mode
        for key in ("skipped_version","remind_version","notified_version"):
            if key in cfg:cur[key]=_helpers.normalize_semver(cfg.get(key),"")
        for key in ("remind_until","remind_session"):
            if key in cfg:cur[key]=_norm(cfg.get(key))[:64]
        # The source is fixed in code; these keys are written only so older builds reading this file see the official values.
        cur["repo_url"]=_helpers.OFFICIAL_SOURCE_REPO
        cur["manifest_url"]=_helpers.GITHUB_RELEASES_API_URL
        cur.setdefault("on_available","ask")
        d["update"]=cur
    return _settings_lock.update_json(_settings_path(),mutate)
def sync_update_settings_from_state(state=None):
    st=state if isinstance(state,dict) else {}
    if st.get("last_checked"):
        save_update_settings({"last_checked":_norm(st.get("last_checked",""))})
    return get_update_settings()
# ---------- launch notification ----------
def _parse_ts(ts):
    try:
        dt=datetime.fromisoformat(str(ts).strip().replace("Z","+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None
def update_notice(session_id="",now=None,state=None,cfg=None):
    """What the UI should show about an available update. Pure decision over state + settings (tests drive it directly).
    show   - an update is available and the user has not skipped/postponed it
    popup  - open the modal by itself (mode "ask", or "background" once the package is downloaded)"""
    now=now or datetime.now(timezone.utc)
    st=state if isinstance(state,dict) else get_update_state()
    cfg=cfg if isinstance(cfg,dict) else get_update_settings()
    cur=_helpers.normalize_semver(st.get("current_version",""),"")
    latest=_helpers.normalize_semver(st.get("last_available_version",""),"")
    staged=bool(latest and _helpers.normalize_semver(st.get("staged_version",""),"")==latest and os.path.isfile(_norm(st.get("staged_package",""))))
    out={"show":False,"popup":False,"reason":"","version":latest,"current_version":cur,"mode":cfg.get("on_available","ask"),"title":f"{_helpers.APP_NAME} {latest} is available" if latest else "","release_name":_norm(st.get("release_name","")),"notes":str(st.get("release_notes") or ""),"published_at":_norm(st.get("release_published_at","")),"size":int(st.get("asset_size") or 0),"html_url":_norm(st.get("release_html_url","")) or f"{_helpers.OFFICIAL_SOURCE_REPO}/releases","installable":bool(_norm(st.get("asset_name",""))),"staged":staged,"result":None}
    res=st.get("last_update_result")
    if isinstance(res,dict) and res.get("message") and not res.get("acknowledged"):
        out["result"]={k:res.get(k) for k in ("ok","version","previous_version","message","at")}
    if not cfg.get("auto_enabled"):
        out["reason"]="checks_disabled";return out
    if not latest or not cur:
        out["reason"]="up_to_date";return out
    try:
        newer=_helpers.compare_semver(latest,cur)>0
    except Exception:
        newer=False
    if not newer:
        out["reason"]="up_to_date";return out
    if st.get("update_in_progress"):
        out["reason"]="in_progress";return out
    if cfg.get("skipped_version")==latest:
        out["reason"]="skipped";return out
    until=_parse_ts(cfg.get("remind_until",""))
    if cfg.get("remind_version")==latest and until and now<until and (not session_id or cfg.get("remind_session")==session_id):
        out["reason"]="remind_later";return out
    out["show"]=True;out["reason"]="available"
    mode=out["mode"]
    out["popup"]=mode=="ask" or (mode=="background" and staged)
    # A release that was just rolled back is not pushed again; it stays in the bell until a newer one is published.
    if isinstance(res,dict) and res.get("ok") is False and _helpers.normalize_semver(res.get("version",""),"")==latest:
        out["popup"]=False;out["failed_before"]=True
    return out
def remind_later(version,session_id="",hours=REMIND_LATER_HOURS,now=None):
    now=now or datetime.now(timezone.utc)
    until=(now+timedelta(hours=max(1,int(hours or REMIND_LATER_HOURS)))).strftime("%Y-%m-%dT%H:%M:%SZ")
    save_update_settings({"remind_version":version,"remind_until":until,"remind_session":session_id})
    return until
def skip_version(version):
    ver=_helpers.normalize_semver(version,"")
    if not ver:raise ValueError("Invalid version.")
    save_update_settings({"skipped_version":ver})
    st=get_update_state()
    if _helpers.normalize_semver(st.get("staged_version",""),"")==ver:
        discard_staged_update()
    return ver
def acknowledge_update_result():
    st=get_update_state()
    res=st.get("last_update_result")
    if isinstance(res,dict) and res:
        res=dict(res);res["acknowledged"]=True
        st["last_update_result"]=res
        write_update_state(st,st.get("current_version",""))
    return True
