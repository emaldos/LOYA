import os,json
from Cores import settings_lock as _settings_lock
from Cores import doc_store as _doc_store
def _abs(*p):return os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","..",*p)
def _data_dir():
    d=_abs("Data");os.makedirs(d,exist_ok=True);return d
def _settings_path():
    return os.path.join(_data_dir(),"settings.json")
def _quick_space_path():
    return os.path.join(_data_dir(),"QuicSpace.json")
def _read_json(p,default):
    if _doc_store.active(p):return _doc_store.read_json(p,default)
    try:
        if not p or not os.path.isfile(p):return default
        with open(p,"r",encoding="utf-8") as f:
            v=json.load(f)
            return v if v is not None else default
    except Exception:
        return default
def _write_json(p,obj):
    if _doc_store.active(p):return _doc_store.write_json(p,obj)
    # Unique temp name: two bridge threads (autosave + Ctrl+S) may write the same file at once.
    return _settings_lock.write_json(p,obj)
def _read_settings():
    return _read_json(_settings_path(),{})
def _write_settings(data):
    return _write_json(_settings_path(),data or {})
def _get_mini_settings():
    d=_read_settings()
    m=d.get("mini_window",{}) if isinstance(d,dict) else {}
    favs=m.get("favorites",[])
    if not isinstance(favs,list):favs=[]
    try:w=int(m.get("w",520))
    except Exception:w=520
    try:h=int(m.get("h",420))
    except Exception:h=420
    return {"x":m.get("x"),"y":m.get("y"),"w":max(320,w),"h":max(240,h),"always_on_top":bool(m.get("always_on_top",False)),"favorites":[str(x) for x in favs if str(x).strip()],"favorites_only":bool(m.get("favorites_only",False)),"collapsed":bool(m.get("collapsed",False))}
def _save_mini_settings(cfg):
    # Under the process-wide settings lock: the main window writes other keys of settings.json at the same time.
    def mutate(d):
        cur=d.get("mini_window") if isinstance(d.get("mini_window"),dict) else {}
        cur.update(cfg or {})
        d["mini_window"]=cur
    return _settings_lock.update_json(_settings_path(),mutate)
