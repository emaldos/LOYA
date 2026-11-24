import os,json,uuid,threading
from datetime import datetime,timezone
from Cores import doc_store as _doc_store
_settings_lock=threading.Lock()
def _abs(*p):return os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","..",*p)
def _sessions_dir():
    d=_abs("Data","ai_sessions");os.makedirs(d,exist_ok=True)
    return d
def _index_path():return os.path.join(_sessions_dir(),"index.json")
def _session_path(sid):return os.path.join(_sessions_dir(),f"{sid}.json")
def _now():return datetime.now(timezone.utc).isoformat()
def _read_json(p,default):
    if _doc_store.active(p):return _doc_store.read_json(p,default)
    try:
        if not os.path.isfile(p):return default
        with open(p,"r",encoding="utf-8") as f:
            v=json.load(f)
            return v if v is not None else default
    except Exception:
        return default
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
def _read_index():
    d=_read_json(_index_path(),[])
    return d if isinstance(d,list) else []
def _write_index(items):
    return _write_json(_index_path(),items)
def _title_from_text(text):
    t=(text or "").strip().replace("\n"," ")
    if not t:return "New Session"
    return t[:40]+("..." if len(t)>40 else "")
def list_sessions():
    return sorted(_read_index(),key=lambda s:s.get("updated_at",s.get("created_at","")),reverse=True)
def create_session(provider_kind=""):
    with _settings_lock:
        sid=uuid.uuid4().hex[:16]
        now=_now()
        entry={"id":sid,"title":"New Session","provider_kind":provider_kind or "","created_at":now,"updated_at":now}
        idx=_read_index()
        idx.append(entry)
        _write_index(idx)
        _write_json(_session_path(sid),{"id":sid,"title":"New Session","provider_kind":provider_kind or "","created_at":now,"updated_at":now,"messages":[]})
        return entry
def load_session(sid):
    if not sid:return None
    data=_read_json(_session_path(sid),None)
    if not isinstance(data,dict):return None
    return data
def save_session_messages(session_id,messages,provider_kind=None):
    with _settings_lock:
        data=_read_json(_session_path(session_id),None)
        if not isinstance(data,dict):return None
        data["messages"]=list(messages or [])
        if provider_kind:data["provider_kind"]=provider_kind
        title=data.get("title") or "New Session"
        if title=="New Session":
            first_user=next((m for m in data["messages"] if m.get("role")=="user"),None)
            if first_user:
                title=_title_from_text(first_user.get("display") or first_user.get("content",""))
                data["title"]=title
        now=_now()
        data["updated_at"]=now
        idx=_read_index()
        for e in idx:
            if e.get("id")==session_id:
                e["title"]=title
                e["updated_at"]=now
                if provider_kind:e["provider_kind"]=provider_kind
                break
        _write_index(idx)
        _write_json(_session_path(session_id),data)
        return data
def clear_session(session_id):
    with _settings_lock:
        data=_read_json(_session_path(session_id),None)
        if not isinstance(data,dict):return False
        data["messages"]=[]
        data["updated_at"]=_now()
        _write_json(_session_path(session_id),data)
        return True
def delete_session(session_id):
    with _settings_lock:
        idx=_read_index()
        new_idx=[e for e in idx if e.get("id")!=session_id]
        if len(new_idx)==len(idx):return False
        _write_index(new_idx)
        try:
            _doc_store.remove(_session_path(session_id))
        except Exception:pass
        return True
def rename_session(session_id,title):
    title=(title or "").strip() or "New Session"
    with _settings_lock:
        idx=_read_index()
        found=False
        for e in idx:
            if e.get("id")==session_id:
                e["title"]=title
                found=True
                break
        if not found:return False
        _write_index(idx)
        data=_read_json(_session_path(session_id),None)
        if isinstance(data,dict):
            data["title"]=title
            _write_json(_session_path(session_id),data)
        return True
