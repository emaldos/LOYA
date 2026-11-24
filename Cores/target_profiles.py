import os,json,hashlib,shutil
from datetime import datetime,timezone
from Cores import common_db as _common_db
from Cores import doc_store as _doc_store
def _now():return datetime.now(timezone.utc).isoformat()
def _norm(s):return (str(s) if s is not None else "").strip()
def _kci(s):return _norm(s).lower()
def _sid(s):return hashlib.sha256(_norm(s).lower().encode("utf-8")).hexdigest()[:16]
def _data_dir():return _common_db.data_dir()
DEFAULT_PROFILE_ID="default"
def _profiles_index_path():
    return os.path.join(_data_dir(),"profiles.json")
def _read_json(p,default):
    if _doc_store.active(p):return _doc_store.read_json(p,default)
    try:
        if not os.path.isfile(p):return default
        with open(p,"r",encoding="utf-8") as f:
            v=json.load(f)
            return v if v is not None else default
    except Exception:return default
def _write_json(p,obj):
    if _doc_store.active(p):return _doc_store.write_json(p,obj)
    t=p+".tmp"
    try:
        os.makedirs(os.path.dirname(p),exist_ok=True)
        with open(t,"w",encoding="utf-8") as f:json.dump(obj,f,ensure_ascii=False,indent=2)
        os.replace(t,p)
        return True
    except Exception:
        try:
            if os.path.isfile(t):os.remove(t)
        except Exception:pass
        return False
def list_profiles():
    d=_read_json(_profiles_index_path(),None)
    if isinstance(d,list):d=[p for p in d if isinstance(p,dict) and _norm(p.get("id",""))]
    else:d=None
    if not d:
        d=[{"id":DEFAULT_PROFILE_ID,"name":"Default","created_at":_now(),"active":True}]
        _write_json(_profiles_index_path(),d)
        return d
    if not any(p.get("active") for p in d):
        d[0]["active"]=True
        _write_json(_profiles_index_path(),d)
    return d
def active_profile_id():
    for p in list_profiles():
        if p.get("active"):return p.get("id") or DEFAULT_PROFILE_ID
    return DEFAULT_PROFILE_ID
def create_profile(name):
    name=_norm(name)
    if not name:return False,"Profile name is required",None
    idx=list_profiles()
    if any(_kci(p.get("name",""))==_kci(name) for p in idx):return False,"Profile name already exists",None
    pid=_sid(name+_now())
    idx.append({"id":pid,"name":name,"created_at":_now(),"active":False})
    if not _write_json(_profiles_index_path(),idx):return False,"Save failed",None
    return True,"Created",pid
def rename_profile(pid,name):
    name=_norm(name)
    if not name:return False,"Profile name is required"
    idx=list_profiles()
    found=None
    for p in idx:
        if p.get("id")==pid:found=p;break
    if not found:return False,"Profile not found"
    if any(_kci(p.get("name",""))==_kci(name) and p.get("id")!=pid for p in idx):return False,"Profile name already exists"
    found["name"]=name
    if not _write_json(_profiles_index_path(),idx):return False,"Save failed"
    return True,"Renamed"
def switch_profile(pid):
    idx=list_profiles()
    if not any(p.get("id")==pid for p in idx):return False,"Profile not found"
    for p in idx:p["active"]=(p.get("id")==pid)
    if not _write_json(_profiles_index_path(),idx):return False,"Save failed"
    return True,"Switched"
def delete_profile(pid):
    if pid==DEFAULT_PROFILE_ID:return False,"The Default profile cannot be deleted"
    idx=list_profiles()
    found=None
    for p in idx:
        if p.get("id")==pid:found=p;break
    if not found:return False,"Profile not found"
    was_active=bool(found.get("active"))
    idx=[p for p in idx if p.get("id")!=pid]
    if was_active and idx:
        for p in idx:p["active"]=(p.get("id")==DEFAULT_PROFILE_ID)
        if not any(p.get("active") for p in idx):idx[0]["active"]=True
    if not _write_json(_profiles_index_path(),idx):return False,"Save failed"
    d=os.path.join(_data_dir(),"Profiles",pid)
    _doc_store.remove_dir(d)
    try:
        if os.path.isdir(d):shutil.rmtree(d)
    except Exception:pass
    return True,"Deleted"
def _default_targets_json_path():
    p_new=os.path.join(_data_dir(),"Targets.json")
    p_old=os.path.join(_data_dir(),"Targes.json")
    return p_new if _doc_store.exists(p_new) or not _doc_store.exists(p_old) else p_old
def _default_target_values_path():
    return os.path.join(_data_dir(),"target_values.json")
def profile_targets_json_path(pid=None):
    pid=pid or active_profile_id()
    if pid==DEFAULT_PROFILE_ID:return _default_targets_json_path()
    d=os.path.join(_data_dir(),"Profiles",pid)
    os.makedirs(d,exist_ok=True)
    return os.path.join(d,"Targets.json")
def profile_target_values_path(pid=None):
    pid=pid or active_profile_id()
    if pid==DEFAULT_PROFILE_ID:return _default_target_values_path()
    d=os.path.join(_data_dir(),"Profiles",pid)
    os.makedirs(d,exist_ok=True)
    return os.path.join(d,"target_values.json")
