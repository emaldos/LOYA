import os,re,json,math,threading,urllib.request,urllib.error
from Cores import common_db as _common_db
from Cores.Services import ai_service as _ai_svc
from Cores import doc_store as _doc_store
_lock=threading.Lock()
TOP_K=4
_KNOWN_EMBED_MODELS=["nomic-embed-text","mxbai-embed-large","all-minilm","bge-m3","snowflake-arctic-embed"]
_STOPWORDS={"the","a","an","and","or","but","of","to","in","on","for","with","is","are","was","were","be","this",
"that","it","as","at","by","from","then","than","so","not","no","have","has","had","will","would","can","could",
"should","into","via","using","use","used"}
_TOKEN_RE=re.compile(r"[a-z0-9]+")
def _index_dir():
    d=os.path.join(_common_db.data_dir(),"search_index")
    os.makedirs(d,exist_ok=True)
    return d
def _index_path():
    return os.path.join(_index_dir(),"index.json")
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
        with open(t,"w",encoding="utf-8") as f:json.dump(obj,f,ensure_ascii=False)
        os.replace(t,p)
        return True
    except Exception:
        try:
            if os.path.isfile(t):os.remove(t)
        except Exception:pass
        return False
def _tokenize(text):
    words=[w for w in _TOKEN_RE.findall((text or "").lower()) if len(w)>=2 and w not in _STOPWORDS]
    counts={}
    for w in words:counts[w]=counts.get(w,0)+1
    return counts
def _pick_ollama_embed_model():
    cfg=_ai_svc.get_providers()["ollama"]
    if not cfg["enabled"]:return None
    r=_ai_svc.test_ollama(cfg["host"],cfg["port"])
    if r.get("status")!="online":return None
    installed=r.get("models") or []
    for known in _KNOWN_EMBED_MODELS:
        for m in installed:
            if m==known or m.startswith(known+":"):return m,cfg["host"],cfg["port"]
    return None
def _ollama_embed(text,model,host,port):
    url=f"http://{host}:{port}/api/embeddings"
    body=json.dumps({"model":model,"prompt":text}).encode("utf-8")
    req=urllib.request.Request(url,data=body,headers={"Content-Type":"application/json"},method="POST")
    with urllib.request.urlopen(req,timeout=15) as resp:
        data=json.loads(resp.read().decode("utf-8","replace"))
    vec=data.get("embedding")
    return vec if isinstance(vec,list) and vec else None
def _cosine(a,b):
    if not a or not b or len(a)!=len(b):return 0.0
    dot=sum(x*y for x,y in zip(a,b))
    na=math.sqrt(sum(x*x for x in a))
    nb=math.sqrt(sum(y*y for y in b))
    if na==0 or nb==0:return 0.0
    return dot/(na*nb)
def _keyword_score(query_counts,doc_tokens,doc_length):
    if not doc_tokens or not doc_length:return 0.0
    score=0.0
    for w,qc in query_counts.items():
        if w in doc_tokens:score+=doc_tokens[w]/doc_length
    return score
def _load_index():
    idx=_read_json(_index_path(),None)
    if not isinstance(idx,dict) or "docs" not in idx:
        embed=_pick_ollama_embed_model()
        idx={"mode":"embedding" if embed else "keyword","embed_model":embed[0] if embed else None,"docs":{}}
    return idx
def _save_index(idx):
    with _lock:_write_json(_index_path(),idx)
def _embed_or_tokenize(idx,text):
    if idx["mode"]=="embedding":
        embed=_pick_ollama_embed_model()
        if not embed:return None,None
        model,host,port=embed
        try:
            vec=_ollama_embed(text,model,host,port)
        except Exception:
            vec=None
        return vec,None
    return None,_tokenize(text)
def _index_doc(kind,doc_id,title,text):
    text=(text or "").strip()
    key=f"{kind}:{doc_id}"
    with _lock:
        idx=_load_index()
        if not text:
            idx["docs"].pop(key,None)
            _write_json(_index_path(),idx)
            return
        vec,tokens=_embed_or_tokenize(idx,text[:4000])
        if idx["mode"]=="embedding" and vec is None:
            idx["docs"].pop(key,None)
            _write_json(_index_path(),idx)
            return
        entry={"kind":kind,"id":doc_id,"title":(title or "")[:120],"snippet":text[:400]}
        if idx["mode"]=="embedding":entry["vector"]=vec
        else:
            entry["tokens"]=tokens
            entry["length"]=sum(tokens.values()) or 1
        idx["docs"][key]=entry
        _write_json(_index_path(),idx)
def index_note(note_id,title,text):
    try:_index_doc("note",note_id,title,text)
    except Exception:pass
def remove_note(note_id):
    try:_index_doc("note",note_id,"","")
    except Exception:pass
def index_command(cmd_id,title,text):
    try:_index_doc("command",cmd_id,title,text)
    except Exception:pass
def remove_command(cmd_id):
    try:_index_doc("command",cmd_id,"","")
    except Exception:pass
def rebuild_index():
    from Cores.Services import notes_service as _notes_svc
    from Cores.Services import commands_service as _commands_svc
    with _lock:
        embed=_pick_ollama_embed_model()
        idx={"mode":"embedding" if embed else "keyword","embed_model":embed[0] if embed else None,"docs":{}}
        _write_json(_index_path(),idx)
    dbp=_notes_svc._db_path()
    notes=_notes_svc._load_notes(dbp)
    for n in notes:
        plain=_notes_svc._strip_html(n["content"])
        index_note(n["id"],n["note_name"],plain)
    _dbp2,cmds=_commands_svc._load_cmds()
    for c in cmds:
        if c.get("src")!="CommandsNotes":continue
        text=f"{c.get('category','')} / {c.get('sub','')}: {c.get('command','')}\n{c.get('description','')}\ntags: {c.get('tags','')}"
        index_command(c["id"],c.get("note_name",""),text)
    return {"mode":idx["mode"],"embed_model":idx["embed_model"],"count":len(notes)+len([c for c in cmds if c.get("src")=="CommandsNotes"])}
def status():
    idx=_load_index()
    return {"mode":idx["mode"],"embed_model":idx.get("embed_model"),"doc_count":len(idx.get("docs") or {})}
def build_context_for_query(query_text):
    allow_notes=_ai_svc.tool_allowed("notes_list")
    allow_commands=_ai_svc.tool_allowed("commands_list")
    if not allow_notes and not allow_commands:return None
    idx=_load_index()
    docs=idx.get("docs") or {}
    if not docs:return None
    query_text=(query_text or "").strip()
    if not query_text:return None
    scored=[]
    if idx["mode"]=="embedding":
        embed=_pick_ollama_embed_model()
        if not embed:return None
        model,host,port=embed
        try:
            qvec=_ollama_embed(query_text,model,host,port)
        except Exception:
            qvec=None
        if not qvec:return None
        for key,d in docs.items():
            if d["kind"]=="note" and not allow_notes:continue
            if d["kind"]=="command" and not allow_commands:continue
            score=_cosine(qvec,d.get("vector"))
            if score>0:scored.append((score,d))
    else:
        qcounts=_tokenize(query_text)
        if not qcounts:return None
        for key,d in docs.items():
            if d["kind"]=="note" and not allow_notes:continue
            if d["kind"]=="command" and not allow_commands:continue
            score=_keyword_score(qcounts,d.get("tokens") or {},d.get("length") or 0)
            if score>0:scored.append((score,d))
    if not scored:return None
    scored.sort(key=lambda t:t[0],reverse=True)
    top=scored[:TOP_K]
    lines=["Relevant items from this workspace's notes/commands (context only - may not be directly relevant, verify before relying on it):"]
    for score,d in top:
        label="Note" if d["kind"]=="note" else "Command"
        lines.append(f"---\n[{label}] {d['title']}\n{d['snippet']}")
    lines.append("---")
    return "\n".join(lines)
