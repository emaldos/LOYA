import os,json,threading,functools
# One process-wide lock for every read-modify-write of Data/settings.json. pywebview runs bridge calls on parallel threads, so two writers
# that each read the file, change their own key and write it back can drop each other's key. Re-entrant so a locked writer may call another.
SETTINGS_LOCK=threading.RLock()
def serialized(fn):
    @functools.wraps(fn)
    def run(*a,**k):
        with SETTINGS_LOCK:return fn(*a,**k)
    return run
def _docs(p):
    # Data/ JSON stores live in the encrypted DB while encryption at rest is on (Cores/doc_store.py); settings.json never does.
    try:
        from Cores import doc_store
        return doc_store if doc_store.active(p) else None
    except Exception:return None
def read_json(p,default=None):
    ds=_docs(p)
    if ds is not None:return ds.read_json(p,default)
    try:
        if not p or not os.path.isfile(p):return default
        with open(p,"r",encoding="utf-8") as f:
            v=json.load(f)
        return v if v is not None else default
    except Exception:return default
def write_json(p,obj):
    ds=_docs(p)
    if ds is not None:return ds.write_json(p,obj)
    t=f"{p}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        os.makedirs(os.path.dirname(p),exist_ok=True)
        with open(t,"w",encoding="utf-8") as f:json.dump(obj,f,ensure_ascii=False,indent=2)
        os.replace(t,p);return True
    except Exception:
        try:
            if os.path.isfile(t):os.remove(t)
        except Exception:pass
        return False
def update_json(p,mutate):
    """Read the dict at p, let mutate(d) change it in place, write it back - all under SETTINGS_LOCK. Returns the write result."""
    with SETTINGS_LOCK:
        d=read_json(p,{})
        if not isinstance(d,dict):d={}
        mutate(d)
        return write_json(p,d)
