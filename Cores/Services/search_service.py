import os,json,re,html,logging
from Cores import settings_lock as _settings_lock
from logging.handlers import RotatingFileHandler
from datetime import datetime,timezone
from Cores import common_db as _common_db
from Cores import note_refs as _note_refs
from Cores import target_profiles as _target_profiles
from Cores import doc_store as _doc_store
def _abs(*p):return os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","..",*p)
def _log_setup():
    d=_abs("Logs");os.makedirs(d,exist_ok=True)
    lg=logging.getLogger("SearchCore");lg.setLevel(logging.INFO)
    fp=os.path.abspath(os.path.join(d,"SearchCore_log.log"))
    for h in list(lg.handlers):
        try:
            if getattr(h,"baseFilename","") and os.path.abspath(h.baseFilename)==fp:return lg
        except Exception:pass
    h=RotatingFileHandler(fp,maxBytes=1024*1024,backupCount=5,encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(message)s","%Y-%m-%d %H:%M:%S"))
    lg.addHandler(h);return lg
_LOG=None
def _log(tag,msg):
    global _LOG
    if _LOG is None:_LOG=_log_setup()
    try:_LOG.info(f"{tag} {msg}")
    except Exception:pass
def _db_path():
    return _common_db.db_path()
def _table_cols(cur,t):
    return _common_db.table_cols(cur,t)
def _ensure_schema(con):
    _common_db.ensure_schema(con)
def _norm(s):return (str(s) if s is not None else "").strip()
def _l(s):return _norm(s).lower()
def _ell(s,n):
    s=_norm(s)
    if not s:return ""
    return (s[:max(0,n-3)]+"...") if len(s)>n else s
def _clean_cmd(s):
    raw=html.unescape(str(s or ""))
    low=raw.lower()
    if not ("<span" in low or "<pre" in low or "<p" in low or "<div" in low or "<br" in low or "style=" in low or "-qt-" in low):
        # Plain commands keep their indentation and tabs; only legacy rich-text HTML is flattened (same rule as commands_service).
        return raw.replace("\r\n","\n").replace("\r","\n").replace("\xa0"," ").strip()
    raw=re.sub(r"<[^>]+>"," ",raw)
    raw=raw.replace("\xa0"," ")
    raw=re.sub(r"[ \t\r\f\v]+"," ",raw)
    raw=re.sub(r"\n\s+","\n",raw)
    raw=re.sub(r"\s+\n","\n",raw)
    return raw.strip()
_PH_KEY_RE=re.compile(r'^[A-Za-z_][A-Za-z0-9_ ]*$')
def _iter_placeholders(text):
    t=str(text or "")
    i=0;n=len(t)
    while i<n:
        if t[i]!="{":
            i+=1;continue
        start=i;j=i+1;bad=False
        while j<n and t[j]!="}":
            if t[j] in "{\r\n":bad=True
            j+=1
        if j>=n:break
        if not bad and not (start>0 and t[start-1]=="$"):
            raw=t[start+1:j].strip()
            if raw and _PH_KEY_RE.match(raw):yield start,j+1,raw
        i=j+1
def _safe_mtime(p):
    try:
        if p and _doc_store.is_doc_path(p):return _doc_store.mtime(p)
        return os.path.getmtime(p) if p and os.path.isfile(p) else None
    except Exception:return None
def _load_cmds(dbp=None):
    p=dbp or _db_path()
    if not p or not os.path.isfile(p):
        _log("[-]",f"DB not found: {p}")
        return p,[]
    try:
        con=_common_db.connect(p);_ensure_schema(con)
        cur=con.cursor()
        out=[]
        note_groups_by_id={};note_groups_by_name={}
        notes_cols=set(_table_cols(cur,"Notes"))
        if {"id","note_name"}.issubset(notes_cols):
            sel="id,note_name"+(",group_name" if "group_name" in notes_cols else "")
            cur.execute(f"SELECT {sel} FROM Notes")
            for r in cur.fetchall():
                gid=_norm(r[2]) if "group_name" in notes_cols and len(r)>2 else ""
                try:note_groups_by_id[int(r[0])]=gid
                except Exception:pass
                nn=_norm(r[1])
                if nn:note_groups_by_name[nn.lower()]=gid
        cn=set(_table_cols(cur,"CommandsNotes"))
        if {"note_name","category","sub_category","command","tags"}.issubset(cn):
            has_desc="description" in cn
            has_type="command_type" in cn
            sel="id,note_name,category,sub_category,command,tags"+(",description" if has_desc else "")+(",command_type" if has_type else "")
            cur.execute(f"SELECT {sel} FROM CommandsNotes ORDER BY id DESC")
            for r in cur.fetchall():
                off=6
                rid=r[0];nn=r[1];c=r[2];sc=r[3];cmd=r[4];tags=r[5]
                desc=(r[off] if has_desc else "");off+=1 if has_desc else 0
                ctype=(r[off] if has_type else "")
                title=_norm(nn) or "Untitled"
                out.append({"id":int(rid),"src":"CommandsNotes","group_name":"","title":title,"cmd_note_title":title,"category":_norm(c) or "Uncategorized","sub":_norm(sc) or "General","command":_clean_cmd(cmd),"tags":_norm(tags),"description":_norm(desc),"command_type":_norm(ctype) or "other"})
        cc=set(_table_cols(cur,"Commands"))
        if {"note_name","category","sub_category","command","tags"}.issubset(cc):
            has_desc="description" in cc
            has_title="cmd_note_title" in cc
            has_note_id="note_id" in cc
            has_type="command_type" in cc
            sel="id"+(",note_id" if has_note_id else "")+",note_name,category,sub_category,command,tags"+(",description" if has_desc else "")+(",cmd_note_title" if has_title else "")+(",command_type" if has_type else "")
            cur.execute(f"SELECT {sel} FROM Commands ORDER BY id DESC")
            for r in cur.fetchall():
                off=0
                rid=r[off];off+=1
                note_id=(r[off] if has_note_id else None);off+=1 if has_note_id else 0
                nn=r[off];off+=1
                c=r[off];off+=1
                sc=r[off];off+=1
                cmd=r[off];off+=1
                tags=r[off];off+=1
                desc=(r[off] if has_desc else "");off+=1 if has_desc else 0
                ttl=(r[off] if has_title else "");off+=1 if has_title else 0
                ctype=(r[off] if has_type else "")
                base=_norm(nn) or "Untitled"
                title=_norm(ttl) or base
                nid=_note_refs.note_ref_id(note_id=note_id)
                grp=note_groups_by_id.get(nid,"") if nid is not None else note_groups_by_name.get(_norm(nn).lower(),"")
                out.append({"id":int(rid),"src":"Commands","note_id":nid,"note_name":_norm(nn),"group_name":grp,"title":title,"cmd_note_title":_norm(ttl),"category":_norm(c) or "Uncategorized","sub":_norm(sc) or "General","command":_clean_cmd(cmd),"tags":_norm(tags),"description":_norm(desc),"command_type":_norm(ctype) or "other"})
        con.close()
        _log("[+]",f"Loaded search cmds: {len(out)} from {os.path.basename(p)}")
        return p,out
    except Exception as e:
        _log("[!]",f"DB load error ({e})")
        try:con.close()
        except Exception:pass
        return p,[]
def _targets_path():
    return _target_profiles.profile_targets_json_path()
def _read_json(p,default):
    if _doc_store.active(p):return _doc_store.read_json(p,default)
    try:
        if not p or not os.path.isfile(p):return default
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
        os.replace(t,p);return True
    except Exception:
        try:
            if os.path.isfile(t):os.remove(t)
        except Exception:pass
        return False
def _searches_path():
    d=_abs("Data");os.makedirs(d,exist_ok=True)
    return os.path.join(d,"saved_searches.json")
def _recent_searches_path():
    d=_abs("Data");os.makedirs(d,exist_ok=True)
    return os.path.join(d,"recent_searches.json")
def _settings_path():
    d=_abs("Data");os.makedirs(d,exist_ok=True)
    return os.path.join(d,"settings.json")
def load_favorites():
    d=_read_json(_settings_path(),{})
    m=d.get("mini_window",{}) if isinstance(d,dict) else {}
    favs=m.get("favorites",[]) if isinstance(m,dict) else []
    if not isinstance(favs,list):favs=[]
    return [str(x) for x in favs if str(x).strip()],bool(m.get("favorites_only",False)) if isinstance(m,dict) else False
@_settings_lock.serialized
def save_favorites(favorites,favorites_only):
    d=_read_json(_settings_path(),{})
    if not isinstance(d,dict):d={}
    m=d.get("mini_window",{}) if isinstance(d.get("mini_window",{}),dict) else {}
    m["favorites"]=sorted(set(str(x) for x in (favorites or []) if str(x).strip()))
    m["favorites_only"]=bool(favorites_only)
    d["mini_window"]=m
    return _write_json(_settings_path(),d)
def fav_key(n):
    if not isinstance(n,dict):return ""
    src=n.get("src") or ""
    cid=n.get("id")
    if cid is not None:return f"{src}:{cid}"
    cmd=n.get("command") or ""
    if cmd:return cmd.strip().lower()
    title=n.get("title") or ""
    return title.strip().lower()
def _norm_filters(filters):
    data=filters if isinstance(filters,dict) else {}
    return {"src":_norm(data.get("src","All")) or "All","group":_norm(data.get("group","All")) or "All","category":_norm(data.get("category","All")) or "All","sub":_norm(data.get("sub","All")) or "All","tag":_norm(data.get("tag","All")) or "All"}
def _normalize_search_entry(item,name=""):
    data=item if isinstance(item,dict) else {}
    out={"name":_norm(data.get("name",name)),"query":_norm(data.get("query","")),"mode":_norm(data.get("mode","Keyword")) or "Keyword","filters":_norm_filters(data.get("filters",{})),"captured_at":_norm(data.get("captured_at",""))}
    return out
def _entry_signature(item):
    entry=_normalize_search_entry(item)
    return json.dumps({"query":entry.get("query",""),"mode":entry.get("mode","Keyword"),"filters":entry.get("filters",{})},sort_keys=True,ensure_ascii=False)
def _fmt_when(text):
    s=_norm(text)
    if not s:return "-"
    try:return datetime.fromisoformat(s.replace("Z","+00:00")).strftime("%Y-%m-%d %H:%M")
    except Exception:return s[:16].replace("T"," ")
def _entry_summary(item):
    entry=_normalize_search_entry(item)
    parts=[]
    q=_norm(entry.get("query",""))
    if q:parts.append(q)
    filters=entry.get("filters",{}) if isinstance(entry.get("filters",{}),dict) else {}
    for key,label in (("src","src"),("group","group"),("category","cat"),("sub","sub"),("tag","tag")):
        val=_norm(filters.get(key,"All"))
        if val and val!="All":parts.append(f"{label}={val}")
    if entry.get("mode","Keyword")!="Keyword":parts.append("mode="+_norm(entry.get("mode","Keyword")))
    return " | ".join(parts) if parts else "Current filters"
def _recent_entry_label(item):
    entry=_normalize_search_entry(item)
    return f"{_fmt_when(entry.get('captured_at',''))} | {_entry_summary(entry)}"
def _load_searches():
    d=_read_json(_searches_path(),[])
    if not isinstance(d,list):return []
    out=[]
    for it in d:
        entry=_normalize_search_entry(it)
        if _norm(entry.get("name","")):out.append(entry)
    return out
def _save_searches(items):
    out=[]
    for it in (items or []):
        entry=_normalize_search_entry(it)
        if _norm(entry.get("name","")):out.append(entry)
    return _write_json(_searches_path(),out)
def _load_recent_searches():
    d=_read_json(_recent_searches_path(),[])
    if not isinstance(d,list):return []
    out=[];seen=set()
    for it in d:
        entry=_normalize_search_entry(it)
        sig=_entry_signature(entry)
        if sig in seen:continue
        seen.add(sig)
        if _entry_summary(entry)!="Current filters":out.append(entry)
    return out[:20]
def _save_recent_searches(items):
    out=[];seen=set()
    for it in (items or []):
        entry=_normalize_search_entry(it)
        sig=_entry_signature(entry)
        if sig in seen:continue
        seen.add(sig)
        if _entry_summary(entry)!="Current filters":out.append(entry)
    return _write_json(_recent_searches_path(),out[:20])
def _split_tags(s):
    if not s:return []
    raw=str(s).replace(";",",").split(",")
    out=[];seen=set()
    for p in raw:
        t=_norm(p)
        if not t:continue
        k=t.lower()
        if k in seen:continue
        seen.add(k);out.append(t)
    return out
def _title_text(n):
    title=_norm(n.get("title","")) or "Untitled"
    grp=_norm(n.get("group_name",""))
    return f"[{grp}] {title}" if grp else title
def _row_preview(n,cmd_disp):
    title=_title_text(n)
    meta=[]
    src=_norm(n.get("src",""))
    if src=="Commands":meta.append("Linked")
    elif src=="CommandsNotes":meta.append("Standalone")
    note_name=_norm(n.get("note_name",""))
    if note_name and note_name!=_norm(n.get("title","")):meta.append("Note: "+note_name)
    cat=_norm(n.get("category",""));sub=_norm(n.get("sub",""))
    if cat or sub:meta.append((cat+" / "+sub).strip(" /"))
    tags=_norm(n.get("tags",""))
    if tags:meta.append("Tags: "+tags)
    desc=_clean_cmd(n.get("description",""))
    cmd=_clean_cmd(cmd_disp or n.get("command",""))
    lines=[title]
    if meta:lines.append(" | ".join(meta))
    if desc:lines.append("Desc: "+_ell(desc,220))
    if cmd:lines.append("Cmd: "+_ell(cmd,260))
    return "\n".join([x for x in lines if _norm(x)])
def _subsequence_score(q,t):
    ti=0
    for ch in q:
        idx=t.find(ch,ti)
        if idx==-1:return 0
        ti=idx+1
    density=len(q)/max(1,ti)
    return int(25*density)
def _fuzzy_score(query,text):
    q=_l(query)
    t=_l(text)
    if not q or not t:return 0
    if t.startswith(q):return 100
    idx=t.find(q)
    if idx>=0:return max(50,90-idx)
    for tok in t.split():
        if tok.startswith(q):return 60
    return _subsequence_score(q,t)
def global_search(query,limit=30,hide_secret_values=False):
    """hide_secret_values (AI callers): secret-named target values are neither matched nor shown, so a search is not an oracle for them."""
    from Cores.Services import notes_service as _notes_svc
    from Cores.Services import targets_service as _targets_svc
    q=_norm(query)
    if not q:return []
    results=[]
    try:
        dbp=_notes_svc._db_path()
        for n in _notes_svc._load_notes(dbp):
            title=_norm(n.get("note_name",""))
            preview=_ell(_notes_svc._strip_html(n.get("content","")),160)
            text=" ".join([title,preview,_norm(n.get("tags","")),_norm(n.get("group_name",""))])
            score=_fuzzy_score(q,text)
            if score>0:results.append({"kind":"note","id":n.get("id"),"title":title or "Untitled","preview":preview,"score":score})
    except Exception as e:
        _log("[!]",f"global_search notes failed ({e})")
    try:
        _dbp2,cmds=_load_cmds()
        for c in cmds:
            title=_title_text(c)
            cmd=_clean_cmd(c.get("command",""))
            text=" ".join([title,cmd,_norm(c.get("tags","")),_norm(c.get("description",""))])
            score=_fuzzy_score(q,text)
            if score>0:results.append({"kind":"command","id":c.get("id"),"src":c.get("src"),"title":title,"preview":_ell(cmd,160),"score":score})
    except Exception as e:
        _log("[!]",f"global_search commands failed ({e})")
    try:
        store=_targets_svc.Store()
        for t in store.targets:
            name=_norm(t.get("name",""))
            values=t.get("values",{}) if isinstance(t.get("values",{}),dict) else {}
            if hide_secret_values:
                from Cores.Bridge import mcp_app_tools as _app_tools
                values={k:v for k,v in values.items() if not _app_tools.is_secret_key(k)}
            text=" ".join([name]+[f"{k} {v}" for k,v in values.items()])
            score=_fuzzy_score(q,text)
            if score>0:results.append({"kind":"target","id":t.get("id"),"title":name or "Untitled","preview":", ".join(f"{k}: {v}" for k,v in values.items()),"score":score})
    except Exception as e:
        _log("[!]",f"global_search targets failed ({e})")
    results.sort(key=lambda r:r["score"],reverse=True)
    return results[:limit]
def _palette_recent_path():
    d=_abs("Data");os.makedirs(d,exist_ok=True)
    return os.path.join(d,"palette_recent.json")
def list_recent_queries():
    d=_read_json(_palette_recent_path(),[])
    if not isinstance(d,list):return []
    return [str(x) for x in d if str(x).strip()][:10]
def record_recent_query(query):
    q=_norm(query)
    if not q:return list_recent_queries()
    items=[x for x in list_recent_queries() if x.lower()!=q.lower()]
    items.insert(0,q)
    items=items[:10]
    _write_json(_palette_recent_path(),items)
    return items
class LiveTargetContext:
    def __init__(self):
        self.path=_targets_path()
        self.mtime=_safe_mtime(self.path)
        self.name=""
        self.map={}
        self.reload()
    def reload(self):
        self.path=_targets_path()
        self.mtime=_safe_mtime(self.path)
        data=_read_json(self.path,[])
        live=None
        if isinstance(data,list):
            for t in data:
                if not isinstance(t,dict):continue
                if _l(t.get("status",""))=="live":
                    live=t;break
        self.name=_norm(live.get("name","")) if live else ""
        vals=live.get("values",{}) if live else {}
        m={}
        if isinstance(vals,dict):
            for k,v in vals.items():
                kk=_l(k);vv=_norm(v)
                if kk and vv:m[kk]=vv
        self.map=m
    def changed(self):
        p=_targets_path()
        mt=_safe_mtime(p)
        return p!=self.path or mt!=self.mtime
class CommandReplacer:
    def __init__(self,ctx):
        self.ctx=ctx
    def apply(self,cmd):
        s=_norm(cmd)
        if not s:return ""
        mp=getattr(self.ctx,"map",{}) or {}
        if not mp:return s
        out=[];last=0
        try:
            for start,end,key in _iter_placeholders(s):
                out.append(s[last:start]);out.append(mp.get(_l(key),"{"+key+"}"));last=end
            out.append(s[last:])
            return "".join(out)
        except Exception:return s
