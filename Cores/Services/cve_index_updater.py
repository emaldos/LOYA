"""In-app updates of the offline CVE index.

Deltas come from the CVE Program's own GitHub releases (CVEProject/cvelistV5): one small zip per finished day
("..._at_end_of_day") plus the newest hourly zip for today. When the installed index is too old for deltas (or there
is none), the whole index is downloaded once from the app's latest GitHub release (cve-index-YYYYMMDD.sqlite.xz) and
the deltas since then are applied on top.

Rules:
- every request goes through cve_service._request, so the opt-in, "Offline only" and the app lock all apply, the hosts
  are fixed and HTTPS-only, and nothing but the file name (a date) is sent
- every file is checked against the SHA-256 and size GitHub records for the release asset before it is used
- a delta is applied in one database transaction; a full index is unpacked next to the old one, checked, and only
  then swapped in - the old index stays usable until that moment
- zip and xz content is bounded (cve_index limits), records are cleaned like every other remote text
- the result is written to the security audit log
"""
import os,re,json,time,hashlib,threading
from datetime import datetime,timezone,timedelta
from Cores.Services import cve_index as _index
from Cores.Services import cve_service as _cve
UPSTREAM="CVEProject/cvelistV5"
MAX_DELTA_DAYS=45                 # GitHub allows 60 unauthenticated API requests an hour; one is needed per day
MAX_DELTA_ZIP_BYTES=96*1024*1024
MAX_INDEX_XZ_BYTES=120*1024*1024
_ASSET_RX=re.compile(r"^cve-index-(\d{8})\.sqlite\.xz$")
_state={"running":False,"progress":{"phase":"","done":0,"total":0,"message":""},"error":"","result":"","thread":None}
_cancel=threading.Event()
_lock=threading.Lock()
def _now():return datetime.now(timezone.utc)
def _app_repo():
    try:
        from Cores.Update import update_helpers as _h
        return f"{_h.OFFICIAL_SOURCE_OWNER}/{_h.OFFICIAL_SOURCE_NAME}"
    except Exception:return "emaldos/LOYA"
def _progress(phase,done=0,total=0,message=""):
    _state["progress"]={"phase":phase,"done":int(done),"total":int(total),"message":message}
def _check_cancel():
    if _cancel.is_set():raise _cve.CveError("The index update was cancelled.","cancelled")
def _gh_json(path):
    status,body,_h=_cve._request("github",_cve.ENDPOINTS["gh_api"]+path,{"Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28"},max_bytes=4*1024*1024)
    if status==404:return None
    return _cve._json(body,"github")
def _asset(release,match):
    for a in release.get("assets") if isinstance(release.get("assets"),list) else []:
        if isinstance(a,dict) and match(str(a.get("name") or "")):return a
    return None
def _download_asset(repo,asset,max_bytes):
    """Download one release asset and check it against the size and SHA-256 GitHub recorded for it. Returns the bytes."""
    name=str(asset.get("name") or "");url=str(asset.get("browser_download_url") or "")
    size=asset.get("size") if isinstance(asset.get("size"),int) else -1
    digest=str(asset.get("digest") or "").lower()
    if not url.startswith(_cve.ENDPOINTS["gh_dl"]+f"/{repo}/releases/download/"):raise _cve.CveError("The release points at an unexpected download address, so it was not used.","blocked")
    if not re.match(r"^sha256:[0-9a-f]{64}$",digest):raise _cve.CveError(f"GitHub has no SHA-256 for {name}, so it was not used.","integrity")
    if size<=0 or size>max_bytes:raise _cve.CveError(f"{name} has an unexpected size, so it was not downloaded.","integrity")
    status,body,_h=_cve._request("github",url,{"Accept":"application/octet-stream"},max_bytes=max_bytes)
    if status!=200:raise _cve.CveError(f"GitHub answered with an error for {name} (HTTP {status}).","http")
    if len(body)!=size or hashlib.sha256(body).hexdigest()!=digest[7:]:raise _cve.CveError(f"{name} does not match the size and SHA-256 GitHub lists for it, so it was not used.","integrity")
    return body
def _full_download():
    """Fetch the whole index from the app's latest release and swap it in. Returns its meta."""
    repo=_app_repo()
    _progress("full",0,0,"Looking for the published CVE index…")
    rel=_gh_json(f"/repos/{repo}/releases/latest")
    asset=_asset(rel or {},lambda n:bool(_ASSET_RX.match(n)))
    if not asset:raise _cve.CveError("No published CVE index was found in the app's latest release. Update the app, or try again after the next release.","no_index")
    _check_cancel()
    _progress("full",0,int(asset.get("size") or 0),"Downloading the full CVE index…")
    body=_download_asset(repo,asset,MAX_INDEX_XZ_BYTES)
    _check_cancel()
    _progress("full",len(body),len(body),"Checking and installing the index…")
    part=os.path.join(_index.index_dir(),"download.part")
    try:
        with open(part,"wb") as f:f.write(body)
        return _index.install_xz(part,_index.index_path(),cancel=_cancel)
    finally:
        try:os.remove(part)
        except OSError:pass
def _parse_wm(wm):
    try:return datetime.strptime(wm,"%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except Exception:return None
def plan(watermark,now):
    """Which upstream deltas bring an index at `watermark` up to `now`: [(tag, asset name, new watermark)] for finished days; today's hourly one is found by probing."""
    wm=_parse_wm(watermark)
    if wm is None:return None
    steps=[]
    day=wm.date()
    while day<now.date():
        if wm<datetime(day.year,day.month,day.day,23,59,59,tzinfo=timezone.utc):
            d=day.isoformat()
            steps.append((f"cve_{d}_at_end_of_day",f"{d}_delta_CVEs_at_end_of_day.zip",f"{d}T23:59:59Z"))
        day+=timedelta(days=1)
    return steps
def _kev_ids():
    """KEV ids from the app's own KEV table (refreshed first when that source is on). None = leave the flags alone."""
    try:
        s=_cve.get_settings()
        with _cve._db() as con:
            cur=con.cursor()
            if s["sources"]["kev"]:
                try:_cve._sync_kev(cur,False,s["feed"]["days_back"]);con.commit()
                except _cve.CveError:pass
            ids=[r[0] for r in cur.execute("SELECT cve_id FROM CveKev").fetchall()]
        return ids or None
    except Exception:return None
def _run():
    _cve._require_network()
    now=_now()
    info=_index.ensure_installed()
    before=dict(info)
    wm=_parse_wm(info["watermark"]) if info["installed"] else None
    full=False
    if wm is None or (now-wm).days>MAX_DELTA_DAYS:
        _full_download();full=True
        info=_index.info();wm=_parse_wm(info["watermark"])
        if wm is None:raise _cve.CveError("The downloaded CVE index has no date stamp, so it cannot be updated further.","integrity")
    steps=plan(info["watermark"],now)
    added=changed=0
    total=len(steps)+1
    for n,(tag,name,new_wm) in enumerate(steps):
        _check_cancel()
        _progress("delta",n,total,f"Updating: {name[:10]} ({n+1} of {total})")
        rel=_gh_json(f"/repos/{UPSTREAM}/releases/tags/{tag}")
        asset=_asset(rel or {},lambda x:x==name)
        if not asset:raise _cve.CveError(f"The CVE Program has not published the update for {name[:10]} (yet). Try again later.","missing_delta")
        rows=_index.read_delta_zip(_download_asset(UPSTREAM,asset,MAX_DELTA_ZIP_BYTES),_cancel)
        a,c=_index.apply_delta(rows,new_wm)
        added+=a;changed+=c
    # today: the newest hourly delta that exists (each one covers everything since midnight)
    _check_cancel()
    _progress("delta",len(steps),total,"Updating: today")
    today=now.date().isoformat()
    cur_wm=_parse_wm(_index.info()["watermark"])
    for back in range(0,4):
        hour=now.hour-back
        if hour<0:break
        new_wm=f"{today}T{hour:02d}:00:00Z"
        if cur_wm and cur_wm>=_parse_wm(new_wm):break
        name=f"{today}_delta_CVEs_at_{hour:02d}00Z.zip"
        rel=_gh_json(f"/repos/{UPSTREAM}/releases/tags/cve_{today}_{hour:02d}00Z")
        asset=_asset(rel or {},lambda x:x==name)
        if not asset:continue
        rows=_index.read_delta_zip(_download_asset(UPSTREAM,asset,MAX_DELTA_ZIP_BYTES),_cancel)
        a,c=_index.apply_delta(rows,new_wm)
        added+=a;changed+=c
        break
    _progress("kev",total,total,"Marking known exploited CVEs…")
    ids=_kev_ids()
    if ids is not None:_index.apply_delta([],None,ids)
    after=_index.info()
    msg=("Full index installed, then " if full else "")+(f"{added:,} new and {changed:,} changed CVEs" if (added or changed) else "the index was already up to date")+f". Now {after['count']:,} CVEs, data up to {after['watermark']}."
    _cve._audit("cve_index",f"CVE index updated: {before.get('watermark') or 'none'} -> {after['watermark']} ({'full download + ' if full else ''}{added} new, {changed} changed, {after['count']} CVEs)",True)
    return msg[0].upper()+msg[1:]
def _worker():
    try:
        _state["error"]="";_state["result"]=""
        _state["result"]=_run()
    except _cve.CveError as e:
        _state["error"]=str(e)
        if e.code!="cancelled":_cve._audit("cve_index","CVE index update failed: "+str(e),False)
    except _index.IndexError_ as e:
        if _cancel.is_set():_state["error"]="The index update was cancelled."
        else:
            _state["error"]=str(e);_cve._audit("cve_index","CVE index update failed: "+str(e),False)
    except Exception as e:
        _state["error"]="The index update failed ("+type(e).__name__+").";_cve._audit("cve_index","CVE index update failed: "+type(e).__name__,False)
    finally:
        _progress("",0,0,"")
        try:
            with _cve._db() as con:
                _cve._meta_set(con.cursor(),"index_last_attempt",_cve._now_iso())
                if not _state["error"]:_cve._meta_set(con.cursor(),"index_last_update",_cve._now_iso())
                con.commit()
        except Exception:pass
        with _lock:_state["running"]=False
def start(wait=False):
    """Start an index update in the background (wait=True runs it inline, for tests)."""
    _cve._require_network()
    with _lock:
        if _state["running"]:return {"started":False,"updating":True,"message":"An index update is already running."}
        _state["running"]=True
        _cancel.clear()
    _progress("start",0,0,"Starting…")
    if wait:
        _worker()
        return {"started":True,"updating":False,"message":_state["error"] or _state["result"]}
    t=threading.Thread(target=_worker,name="cve-index-update",daemon=True)
    _state["thread"]=t;t.start()
    return {"started":True,"updating":True,"message":"Updating the CVE index…"}
def cancel():
    with _lock:running=_state["running"]
    if running:_cancel.set()
    return {"cancelled":bool(running)}
def status():
    _cve._require_unlocked()
    s=_cve.get_settings()
    info=_index.ensure_installed()
    last=""
    try:
        with _cve._db() as con:last=_cve._meta_get(con.cursor(),"index_last_update")
    except Exception:pass
    return {"installed":info["installed"],"count":info["count"],"built_at":info["built_at"],"watermark":info["watermark"],"version":info["version"],"size_bytes":info["size_bytes"],"seed_available":info["seed_available"],
        "published":info["published"],"scored":info["scored"],"updating":bool(_state["running"]),"progress":dict(_state["progress"]),"error":_state["error"],"last_update":last,"last_result":_state["result"],
        "auto":s["index_auto"],"can_update":_cve.can_fetch(s)}
def auto_tick(s=None):
    """Called from cve_service.tick(): start an update when auto-update is on and one is due. Never raises."""
    s=s or _cve.get_settings()
    if s["index_auto"]=="off" or not _cve.can_fetch(s) or _state["running"]:return False
    every=86400 if s["index_auto"]=="daily" else 7*86400
    try:
        with _cve._db() as con:last=_cve._meta_get(con.cursor(),"index_last_attempt")
        if last and (_now()-datetime.fromisoformat(last)).total_seconds()<every:return False
    except Exception:return False
    try:return bool(start()["started"])
    except _cve.CveError:return False
