import os,logging,hashlib,re,json,base64,html,csv,zipfile,shutil,uuid,difflib,io
from logging.handlers import RotatingFileHandler
from datetime import datetime,timezone
from Cores import common_db as _common_db
from Cores import db_driver as _db_driver
from Cores import note_refs as _note_refs
from Cores import recycle_bin as _recycle_bin
from Cores import settings_lock as _settings_lock
from Cores.Theme import palettes as _palettes
from Cores.Theme import tokens as _tokens
from Cores import doc_store as _doc_store
def _pal():
    try:return _palettes.PALETTES.get(_tokens.current_theme()) or _palettes.PALETTES[_palettes.DEFAULT_THEME]
    except Exception:return {}
def _abs(*p):return os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","..",*p)
def _log_setup():
    d=_abs("Logs");os.makedirs(d,exist_ok=True)
    lg=logging.getLogger("Note");lg.setLevel(logging.INFO)
    fp=os.path.abspath(os.path.join(d,"Note_log.log"))
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
_NOTE_REF_COLOR_DEFAULT="#b197fc"
_NOTE_LINK_COLOR_DEFAULT="#4dabf7"
_NOTE_REF_RX=re.compile(r"-Notename-([^\r\n-]+)-",re.I)
_NOTE_LINK_ANCHOR="notelink:"
def _db_path():
    return _common_db.db_path()
DB_SCHEMA_VERSION=_common_db.DB_SCHEMA_VERSION
def _ensure_schema(con):
    _common_db.ensure_schema(con)
def _ensure_cmd_schema(con):
    _common_db.ensure_schema(con)
def _table_cols(cur,t):
    return _common_db.table_cols(cur,t)
def _norm(s):return " ".join((s or "").strip().split())
def _kci(s):return _norm(s).lower()
def _group_label(s):return _norm(s) or "Ungrouped"
def _group_sort_key(s):
    g=_norm(s)
    return (1 if not g else 0,_group_label(g).lower())
def _parse_cmd_blocks(text):
    t=text or ""
    out=[]
    for m in re.finditer(r"<C\s*\[(.*?)\]\s*>\s*(.*?)\s*</C>",t,re.S|re.I):
        meta=(m.group(1) or "").strip()
        body=(m.group(2) or "").rstrip()
        d={"cmd_note_title":"","category":"","sub_category":"","description":"","tags":"","command":body}
        for p in [x.strip() for x in meta.split(",") if x.strip()]:
            if ":" not in p:continue
            k,v=p.split(":",1)
            k=(k or "").strip().lower()
            v=(v or "").strip()
            if "command note tittle" in k or "note title" in k:d["cmd_note_title"]=v
            elif k=="category":d["category"]=v
            elif "sub category" in k or "subcategory" in k:d["sub_category"]=v
            elif k=="description":d["description"]=v
            elif k=="tags":d["tags"]=v
        if _norm(d["command"]):out.append(d)
    return out
def _sync_commands(con,note_id,note_name,note_text,now):
    _ensure_cmd_schema(con)
    cmds=note_text if isinstance(note_text,list) else _parse_cmd_blocks(note_text)
    cur=con.cursor()
    nn=(note_name or "").strip()
    # Rows are updated in place (unchanged commands first, then edited ones by position) so a command keeps its id across note saves:
    # Snippets favourites, playbook steps and run history point at that id, and noise_level only lives on the row.
    cur.execute("SELECT id,note_id,note_name,cmd_note_title,category,sub_category,description,tags,command,command_type FROM Commands WHERE note_id=? ORDER BY id",(int(note_id),))
    old=cur.fetchall()
    def key(t,cat,sub,desc,tg,cmd):return (_norm(t),_norm(cat),_norm(sub),_norm(desc),_norm(tg),_norm(cmd))
    new=[(key(c.get("cmd_note_title",""),c.get("category",""),c.get("sub_category",""),c.get("description",""),c.get("tags",""),c.get("command","")),c) for c in cmds]
    pair=[None]*len(new);used=set()
    for i,(k,_c) in enumerate(new):
        for r in old:
            if r[0] not in used and key(*r[3:9])==k:pair[i]=r;used.add(r[0]);break
    rest=[r for r in old if r[0] not in used]
    for i in range(len(new)):
        if pair[i] is None and rest:pair[i]=rest.pop(0)
    for r in rest:
        _insert_cmd_history(cur,r[0],r[1],r[2],r[3],r[4],r[5],r[6],r[7],r[8],"delete",now)
        cur.execute("DELETE FROM Commands WHERE id=?",(r[0],))
    for (k,c),r in zip(new,pair):
        vals=(nn,_norm(c.get("cmd_note_title","")),_norm(c.get("category","")),_norm(c.get("sub_category","")),_norm(c.get("description","")),_norm(c.get("tags","")),(c.get("command","") or "").rstrip(),_norm(c.get("command_type","")) or "other")
        if r is not None:
            if (r[2] or "")==vals[0] and tuple(r[3:8])==vals[1:6] and (r[8] or "")==vals[6] and (r[9] or "other")==vals[7]:continue
            cur.execute("UPDATE Commands SET note_name=?,cmd_note_title=?,category=?,sub_category=?,description=?,tags=?,command=?,command_type=?,updated_at=? WHERE id=?",vals+(now,r[0]))
            _insert_cmd_history(cur,r[0],int(note_id),*vals[:7],"update",now)
            continue
        cur.execute("INSERT INTO Commands(note_id,note_name,cmd_note_title,category,sub_category,description,tags,command,command_type,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(int(note_id),)+vals+(now,now))
        try:cid=int(cur.lastrowid)
        except Exception:cid=None
        _insert_cmd_history(cur,cid,int(note_id),*vals[:7],"insert",now)
    con.commit()
    return len(cmds)
def _strip_html(s):
    if not s:return ""
    t=str(s)
    t=re.sub(r"(?i)<br\s*/?>","\n",t)
    t=re.sub(r"(?i)</p>","\n",t)
    t=re.sub(r"(?i)</pre>","\n",t)
    t=re.sub(r"(?i)<pre[^>]*>","",t)
    t=re.sub(r"(?i)<span[^>]*>","",t)
    t=re.sub(r"(?i)</span>","",t)
    t=re.sub(r"<[^>]+>","",t)
    t=html.unescape(t)
    t=t.replace("\r\n","\n").replace("\r","\n")
    lines=[ln.rstrip() for ln in t.split("\n")]
    while lines and not lines[0].strip():lines.pop(0)
    while lines and not lines[-1].strip():lines.pop()
    return "\n".join(lines)
def _notes_meta_path():
    d=_abs("Data");os.makedirs(d,exist_ok=True)
    return os.path.join(d,"notes_meta.json")
def _read_json(p):
    if _doc_store.active(p):return _doc_store.read_json(p,None)
    try:
        with open(p,"r",encoding="utf-8") as f:return json.load(f)
    except Exception:
        return None
def _write_json(p,data):
    if _doc_store.active(p):return _doc_store.write_json(p,data)
    t=p+".tmp"
    try:
        os.makedirs(os.path.dirname(p),exist_ok=True)
        with open(t,"w",encoding="utf-8") as f:json.dump(data,f,ensure_ascii=True,indent=2)
        os.replace(t,p)
        return True
    except Exception as e:
        _log("[!]",f"JSON write failed: {p} ({e})")
        try:
            if os.path.isfile(t):os.remove(t)
        except Exception:pass
        return False
def _dedupe_ci(items):
    out=[];seen=set()
    for x in items or []:
        t=_norm(x)
        if not t:continue
        k=t.lower()
        if k in seen:continue
        seen.add(k);out.append(t)
    return out
def _load_notes_meta():
    p=_notes_meta_path()
    d=_read_json(p)
    if not isinstance(d,dict):d={}
    pinned=_note_refs.dedupe_note_refs(d.get("pinned",[]))
    recent=_note_refs.dedupe_note_refs(d.get("recent",[]))
    groups=_dedupe_ci(d.get("groups",[]))
    nav_collapsed_groups=_dedupe_ci(d.get("nav_collapsed_groups",[]))
    return {"pinned":pinned,"recent":recent,"groups":groups,"nav_collapsed_groups":nav_collapsed_groups}
def _save_notes_meta(pinned,recent,groups=None,nav_collapsed_groups=None):
    if groups is None:
        cur=_read_json(_notes_meta_path())
        if not isinstance(cur,dict):cur={}
        groups=_dedupe_ci(cur.get("groups",[]))
    if nav_collapsed_groups is None:
        cur=_read_json(_notes_meta_path())
        if not isinstance(cur,dict):cur={}
        nav_collapsed_groups=_dedupe_ci(cur.get("nav_collapsed_groups",[]))
    data={"pinned":_note_refs.dedupe_note_refs(pinned),"recent":_note_refs.dedupe_note_refs(recent),"groups":_dedupe_ci(groups),"nav_collapsed_groups":_dedupe_ci(nav_collapsed_groups)}
    return _write_json(_notes_meta_path(),data)
def pinned_refs():
    return _load_notes_meta().get("pinned",[])
def pinned_note_ids():
    ids=set()
    for r in pinned_refs():
        nid=_note_refs.note_ref_id(r)
        if nid is not None:ids.add(int(nid))
    return ids
def set_pinned(note_id,note_name,pinned):
    meta=_load_notes_meta()
    key=_note_refs.note_ref_key(note_id=note_id,note_name=note_name)
    current=meta.get("pinned",[])
    filtered=[r for r in current if _note_refs.note_ref_key(r)!=key]
    if pinned and key:
        filtered.append(_note_refs.serialize_note_ref(note_id=note_id,note_name=note_name))
    _save_notes_meta(filtered,meta.get("recent",[]),meta.get("groups",[]),meta.get("nav_collapsed_groups",[]))
    return bool(pinned)
def _templates_path():
    d=_abs("Data");os.makedirs(d,exist_ok=True)
    return os.path.join(d,"notes_templates.json")
def list_templates():
    items=_read_json(_templates_path())
    items=items if isinstance(items,list) else []
    out=[]
    for t in items:
        if not isinstance(t,dict):continue
        tid=_norm(t.get("id",""));name=_norm(t.get("name",""))
        if not tid or not name:continue
        out.append({"id":tid,"name":name,"content_html":t.get("content_html","") or ""})
    out.sort(key=lambda x:x["name"].lower())
    return out
def get_template(template_id):
    tid=_norm(template_id)
    for t in list_templates():
        if t["id"]==tid:return t
    return None
def save_template(name,content_html):
    name=_norm(name)
    if not name:raise ValueError("Template name is required.")
    items=_read_json(_templates_path())
    items=items if isinstance(items,list) else []
    key=name.lower()
    existing=next((t for t in items if isinstance(t,dict) and _norm(t.get("name","")).lower()==key),None)
    if existing:
        existing["content_html"]=content_html or ""
        tid=_norm(existing.get("id",""))
    else:
        tid=hashlib.sha1(f"{name}|{datetime.now(timezone.utc).isoformat()}".encode("utf-8")).hexdigest()[:12]
        items.append({"id":tid,"name":name,"content_html":content_html or ""})
    _write_json(_templates_path(),items)
    return tid
def delete_template(template_id):
    tid=_norm(template_id)
    items=_read_json(_templates_path())
    items=items if isinstance(items,list) else []
    filtered=[t for t in items if not(isinstance(t,dict) and _norm(t.get("id",""))==tid)]
    if len(filtered)==len(items):return False
    _write_json(_templates_path(),filtered)
    return True
_ATTACHMENT_IMAGE_EXTS={"png","jpg","jpeg","gif","webp","bmp","svg"}
_ATTACHMENT_ID_RX=re.compile(r'data-attachment-id="([^"]+)"')
def _attachments_root():
    d=_abs("Data","Attachments");os.makedirs(d,exist_ok=True)
    return d
def _attachments_pending_dir():
    d=os.path.join(_attachments_root(),"_pending");os.makedirs(d,exist_ok=True)
    return d
def _attachments_note_dir(note_id):
    d=os.path.join(_attachments_root(),str(int(note_id)));os.makedirs(d,exist_ok=True)
    return d
def _attachment_kind(ext):
    return "image" if (ext or "").lower().lstrip(".") in _ATTACHMENT_IMAGE_EXTS else "file"
def _file_url(path):
    return "file:///"+os.path.abspath(path).replace("\\","/")
def save_pending_attachment(filename,data_b64):
    raw=data_b64 or ""
    if raw.strip().lower().startswith("data:") and "," in raw:
        raw=raw.split(",",1)[1]
    try:
        blob=base64.b64decode(raw)
    except Exception:
        raise ValueError("Invalid attachment data.")
    safe_name=re.sub(r'[\\/:*?"<>|]',"_",_norm(filename) or "file")
    ext=os.path.splitext(safe_name)[1].lstrip(".").lower()
    aid=uuid.uuid4().hex[:16]
    out_name=f"{aid}.{ext}" if ext else aid
    path=os.path.join(_attachments_pending_dir(),out_name)
    _write_attachment(path,blob)
    kind=_attachment_kind(ext)
    return {"id":aid,"filename":safe_name,"kind":kind,"size":len(blob),"url":_file_url(path)}
def finalize_attachments(content_html,note_id):
    t=content_html or ""
    ids=set(_ATTACHMENT_ID_RX.findall(t))
    if not ids:return t
    pending=_attachments_pending_dir()
    dest_dir=_attachments_note_dir(note_id)
    for aid in ids:
        try:matches=[f for f in os.listdir(pending) if f.startswith(aid+".") or f==aid]
        except Exception:matches=[]
        for fname in matches:
            src=os.path.join(pending,fname)
            dest=os.path.join(dest_dir,fname)
            try:shutil.move(src,dest)
            except Exception:continue
            t=t.replace(_file_url(src),_file_url(dest))
    return t
def discard_pending_attachments(ids):
    pending=_attachments_pending_dir()
    for aid in ids or []:
        aid=_norm(aid)
        if not aid:continue
        try:matches=[f for f in os.listdir(pending) if f.startswith(aid+".") or f==aid]
        except Exception:matches=[]
        for fname in matches:
            try:os.remove(os.path.join(pending,fname))
            except Exception:pass
def purge_note_attachments(note_id):
    d=os.path.join(_attachments_root(),str(int(note_id)))
    try:
        if os.path.isdir(d):shutil.rmtree(d)
    except Exception:pass
_ATTACHMENT_DIR_REF_RX=re.compile(r"Attachments[\\/]+(\d+)[\\/]")
def purge_orphan_attachments(dbp=None):
    # A soft-deleted note keeps its files (the Recycle Bin can restore it, under a new id, with the old paths); a folder is only removed once no note and no Recycle Bin entry mentions it.
    dbp=dbp or _db_path()
    root=_attachments_root()
    try:dirs=[d for d in os.listdir(root) if d.isdigit() and os.path.isdir(os.path.join(root,d))]
    except Exception:return 0
    if not dirs:return 0
    used=set()
    try:
        with _common_db.connection(dbp,timeout=5) as con:
            _ensure_schema(con)
            cur=con.cursor()
            for sql in ("SELECT content FROM Notes","SELECT payload FROM RecycleBin"):
                try:
                    cur.execute(sql)
                    for (t,) in cur.fetchall():used.update(_ATTACHMENT_DIR_REF_RX.findall(t or ""))
                except Exception:pass
    except Exception:return 0
    n=0
    for d in dirs:
        if d in used:continue
        try:shutil.rmtree(os.path.join(root,d));n+=1
        except Exception:pass
    return n
_ATTACHMENT_ID_SAFE_RX=re.compile(r"^[0-9a-f]{8,32}$")
_ATTACHMENT_DATA_MIME={"png":"image/png","jpg":"image/jpeg","jpeg":"image/jpeg","gif":"image/gif","webp":"image/webp","bmp":"image/bmp"}
_ATTACHMENT_DATA_MAX=48*1024*1024
def _attachment_key():
    """The session data key when attachments are stored encrypted (encryption at rest on), else None."""
    if not _common_db.encryption_configured():return None
    k=_common_db.session_key()
    if k is None:raise _common_db.DatabaseLocked(_common_db.ENCRYPTED_MESSAGE)
    return k
def _write_attachment(path,blob):
    """Encryption at rest on: the file is a crypto_store AES-256-GCM stream (same name, so note HTML and purge logic are
    unchanged; the notes view shows it through attachment_view). Off: the plain bytes, as before."""
    from Cores import crypto_store as _cs
    key=_attachment_key()
    data=_cs.encrypt_bytes(blob,key) if key is not None else blob
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|getattr(os,"O_BINARY",0),0o600)
    with os.fdopen(fd,"wb") as f:f.write(data)
def attachment_bytes(raw):
    """Plain bytes of an attachment file's content (decrypted when it is a crypto_store stream)."""
    from Cores import crypto_store as _cs
    if raw[:8]==_cs.MAGIC:
        k=_common_db.session_key()
        if k is None:raise _common_db.DatabaseLocked(_common_db.ENCRYPTED_MESSAGE)
        return _cs.decrypt_bytes(raw,k)
    return raw
def _find_attachment(aid):
    root=_attachments_root()
    dirs=[_attachments_pending_dir()]
    try:dirs+=[os.path.join(root,d) for d in sorted(os.listdir(root),key=lambda x:(len(x),x),reverse=True) if d.isdigit() and os.path.isdir(os.path.join(root,d))]
    except Exception:pass
    for d in dirs:
        try:names=[f for f in os.listdir(d) if f.startswith(aid+".")]
        except Exception:continue
        for fname in names:return os.path.join(d,fname)
    return None
def attachment_view(attachment_id):
    """An image attachment as a data: URL for the notes view, when its file is encrypted at rest (an <img> cannot read the
    ciphertext from its file:// URL). Only ids, never paths."""
    aid=_norm(attachment_id).lower()
    if not _ATTACHMENT_ID_SAFE_RX.match(aid):raise ValueError("Invalid attachment id.")
    path=_find_attachment(aid)
    if not path:raise ValueError("Attachment not found.")
    ext=os.path.splitext(path)[1].lstrip(".").lower()
    mime={"png":"image/png","jpg":"image/jpeg","jpeg":"image/jpeg","gif":"image/gif","webp":"image/webp","bmp":"image/bmp","svg":"image/svg+xml"}.get(ext)
    if not mime:raise ValueError("Not an image attachment.")
    if os.path.getsize(path)>_ATTACHMENT_DATA_MAX:raise ValueError("This image is too large to show.")
    with open(path,"rb") as f:blob=attachment_bytes(f.read())
    return {"id":aid,"mime":mime,"size":len(blob),"data_url":f"data:{mime};base64,"+base64.b64encode(blob).decode("ascii")}
def attachment_data_url(attachment_id):
    """A raster image attachment as a data: URL, for the drawing tool (a canvas that drew a file:// image cannot be exported). Only ids, never paths."""
    aid=_norm(attachment_id).lower()
    if not _ATTACHMENT_ID_SAFE_RX.match(aid):raise ValueError("Invalid attachment id.")
    root=_attachments_root()
    dirs=[_attachments_pending_dir()]
    try:dirs+=[os.path.join(root,d) for d in sorted(os.listdir(root),key=lambda x:(len(x),x),reverse=True) if d.isdigit() and os.path.isdir(os.path.join(root,d))]
    except Exception:pass
    for d in dirs:
        try:names=[f for f in os.listdir(d) if f.startswith(aid+".")]
        except Exception:continue
        for fname in names:
            ext=os.path.splitext(fname)[1].lstrip(".").lower()
            mime=_ATTACHMENT_DATA_MIME.get(ext)
            if not mime:raise ValueError("This image type cannot be annotated.")
            path=os.path.join(d,fname)
            if os.path.getsize(path)>_ATTACHMENT_DATA_MAX:raise ValueError("This image is too large to annotate.")
            with open(path,"rb") as f:blob=attachment_bytes(f.read())
            return {"id":aid,"mime":mime,"size":len(blob),"data_url":f"data:{mime};base64,"+base64.b64encode(blob).decode("ascii")}
    raise ValueError("Attachment not found.")
# ---- Open / Save as for file attachments. The UI only ever sends an attachment id (and a display name for the copy); the file is
# looked up here and must be a regular file inside Data/Attachments (no traversal, no symlink out of the folder). With encryption at
# rest on, Open decrypts into a private temp folder (0700 dir, 0600 file) that is removed on lock, on exit and at the next start;
# Save as decrypts straight into the chosen file (written atomically, so a tampered stream leaves nothing behind).
# Types the desktop would run rather than show (xdg-open launches .desktop files, os.startfile runs .exe/.bat...): Save as only.
_ATTACHMENT_OPEN_BLOCKED={"exe","com","bat","cmd","scr","pif","msi","msp","cpl","hta","jar","lnk","reg","ps1","psm1","vbs","vbe","js","jse","wsf","wsh","desktop","appimage","run","sh","bash","zsh","py","pyw","pl","rb","bin","elf","deb","rpm","url","scf","inf"}
_ATTACHMENT_OPEN_PREFIX="loya_att_"
_ATTACHMENT_OPEN_STATE={"dir":None,"swept":False}
def _attachment_audit(event,detail,success=True):
    try:
        from Cores.Services import security_service as _sec
        _sec.log_audit_event(event,detail,success)
    except Exception:pass
def _attachment_require_unlocked():
    try:
        from Cores.Services import security_service as _sec
        locked=_sec.is_locked()
    except Exception:locked=_common_db.is_locked()
    if locked or _common_db.is_locked():raise _common_db.DatabaseLocked("LOYA NG is locked. Unlock it to open or save attachments.")
def resolve_attachment_file(attachment_id):
    """The real path of an attachment, by id only; it must be a regular file directly inside an Attachments/<note id> or _pending folder."""
    aid=_norm(attachment_id).lower()
    if not _ATTACHMENT_ID_SAFE_RX.match(aid):raise ValueError("Invalid attachment id.")
    path=_find_attachment(aid)
    if not path:raise ValueError("Attachment not found.")
    root=os.path.realpath(_attachments_root())
    real=os.path.realpath(path)
    parent=os.path.dirname(real)
    ok=os.path.islink(path) is False and os.path.dirname(parent)==root and os.path.isfile(real)
    ok=ok and (os.path.basename(parent).isdigit() or os.path.basename(parent)=="_pending") and not os.path.islink(os.path.dirname(path))
    if not ok:raise ValueError("Attachment not found.")
    return real
def _attachment_copy_name(display_name,real_path):
    ext=os.path.splitext(real_path)[1].lstrip(".").lower()
    base=os.path.basename(str(display_name or "").replace("\\","/"))
    base=re.sub(r'[\x00-\x1f<>:"/\\|?*]',"_",base).strip(" .")
    stem=os.path.splitext(base)[0].strip(" .")[:120] if base else ""
    stem=stem or os.path.splitext(os.path.basename(real_path))[0]
    return (stem+"."+ext) if ext else stem,ext
def _pid_alive(pid):
    if pid==os.getpid():return True
    if os.name=="nt":return False  # an open file there cannot be removed anyway; the rmtree below just skips it
    try:os.kill(pid,0)
    except ProcessLookupError:return False
    except Exception:return True
    return True
def sweep_stale_attachment_copies(tmp_root=None):
    """Removes decrypted copies left by an earlier run that did not exit cleanly (folders named for a process that is gone)."""
    import tempfile
    tmp_root=tmp_root or tempfile.gettempdir()
    n=0
    try:names=os.listdir(tmp_root)
    except Exception:return 0
    for name in names:
        m=re.match(r"^"+_ATTACHMENT_OPEN_PREFIX+r"(\d+)_",name)
        if not m or _pid_alive(int(m.group(1))):continue
        p=os.path.join(tmp_root,name)
        try:
            if os.path.islink(p) or not os.path.isdir(p):continue
            if os.name!="nt" and os.stat(p).st_uid!=os.getuid():continue
            shutil.rmtree(p,ignore_errors=True);n+=1
        except Exception:pass
    return n
def _attachment_open_dir():
    import tempfile,atexit
    st=_ATTACHMENT_OPEN_STATE
    if not st["swept"]:
        st["swept"]=True
        sweep_stale_attachment_copies()
    d=st["dir"]
    if not d or not os.path.isdir(d):
        d=tempfile.mkdtemp(prefix=f"{_ATTACHMENT_OPEN_PREFIX}{os.getpid()}_")  # 0700 on POSIX
        st["dir"]=d
        atexit.register(purge_open_attachment_copies)
    return d
def purge_open_attachment_copies():
    """Drops every decrypted copy this process made for Open (called on lock and at exit)."""
    d=_ATTACHMENT_OPEN_STATE.get("dir")
    _ATTACHMENT_OPEN_STATE["dir"]=None
    if d and os.path.isdir(d):shutil.rmtree(d,ignore_errors=True)
def _copy_attachment_plain(real,dst):
    """Writes the plain bytes of the attachment file `real` to the open binary file dst (decrypting a crypto_store stream)."""
    from Cores import crypto_store as _cs
    with open(real,"rb") as src:
        head=src.read(8)
        src.seek(0)
        if head==_cs.MAGIC:
            k=_common_db.session_key()
            if k is None:raise _common_db.DatabaseLocked(_common_db.ENCRYPTED_MESSAGE)
            for chunk in _cs.decrypt_stream(src,k):dst.write(chunk)
        else:shutil.copyfileobj(src,dst,1024*1024)
def attachment_open_copy(attachment_id,display_name=""):
    """A private plaintext copy of the attachment for the system viewer: (path, name). 0600 file in a 0700 folder."""
    _attachment_require_unlocked()
    real=resolve_attachment_file(attachment_id)
    name,ext=_attachment_copy_name(display_name,real)
    if ext in _ATTACHMENT_OPEN_BLOCKED:raise ValueError(f"\"{name}\" could run as a program, so it is not opened from here. Use Save as\u2026 and check it first.")
    import tempfile
    sub=tempfile.mkdtemp(dir=_attachment_open_dir())
    out=os.path.join(sub,name)
    fd=os.open(out,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_BINARY",0),0o600)
    try:
        with os.fdopen(fd,"wb") as f:_copy_attachment_plain(real,f)
    except BaseException:
        try:os.remove(out)
        except OSError:pass
        raise
    return out,name
def _open_with_system(path):
    if os.name=="nt":
        os.startfile(path)  # noqa - Windows only
        return
    from Cores.Update import recovery as _recovery
    ok,msg=_recovery.open_with_desktop(path)
    if not ok:raise ValueError(msg or "No application is set up to open this file.")
def open_attachment(attachment_id,display_name="",opener=None):
    """Open a file attachment with the system default application (xdg-open / os.startfile) via a private plaintext copy."""
    aid=_norm(attachment_id).lower()
    try:
        path,name=attachment_open_copy(aid,display_name)
        (opener or _open_with_system)(path)
    except Exception as e:
        _attachment_audit("attachment_open",f"{aid[:32]} refused: {e}",False)
        raise
    _attachment_audit("attachment_open",f"{aid} {name}",True)
    return {"id":aid,"name":name}
def save_attachment_copy(attachment_id,out_path,display_name=""):
    """Save as: the plain bytes of the attachment into out_path (a path from the native save dialog), written atomically."""
    from Cores import crypto_store as _cs
    aid=_norm(attachment_id).lower()
    try:
        _attachment_require_unlocked()
        real=resolve_attachment_file(aid)
        out=os.path.abspath(str(out_path or ""))
        if not out_path or os.path.isdir(out):raise ValueError("Choose a file name to save to.")
        if os.path.realpath(out)==real:raise ValueError("Choose another place to save the copy.")
        with _cs.atomic_write(out) as dst:_copy_attachment_plain(real,dst)
    except Exception as e:
        _attachment_audit("attachment_save",f"{aid[:32]} refused: {e}",False)
        raise
    _attachment_audit("attachment_save",f"{aid} {_attachment_copy_name(display_name,real)[0]} -> {os.path.basename(out)}",True)
    return out
def attachment_save_default(attachment_id,display_name=""):
    """(suggested file name, extension) for the Save as dialog."""
    real=resolve_attachment_file(attachment_id)
    return _attachment_copy_name(display_name,real)
_SAN_BLOCK_RX=re.compile(r"<\s*(script|style|iframe|object|embed|applet|frameset|noscript|template|svg|math|form|textarea|select|title)\b[^>]*>.*?<\s*/\s*\1\s*>",re.I|re.S)
_SAN_TAG_RX=re.compile(r"<\s*/?\s*(?:script|style|iframe|frame|frameset|object|embed|applet|meta|link|base|form|input|textarea|select|option|svg|math|noscript|template|portal)\b[^>]*>",re.I)
# A start tag runs to the first > outside a quoted value. A stray quote (src=x') or a < inside an unquoted value (title=<) does not
# end it for the browser, so it must not stop this match either - otherwise the on* handler behind it would be left in place.
_SAN_ANY_TAG_RX=re.compile(r"""<[a-zA-Z](?:[^>"']|"[^"]*"|'[^']*'|["'])*>""")
_SAN_ON_ATTR_RX=re.compile(r"""(?<![\w-])on[a-zA-Z]+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)""",re.I)
_SAN_URL_ATTR_RX=re.compile(r"""((?:href|src|action|formaction|xlink:href|background|poster)\s*=\s*)(?:"\s*(?:javascript|vbscript|data\s*:\s*text)[^"]*"|'\s*(?:javascript|vbscript|data\s*:\s*text)[^']*'|(?:javascript|vbscript):[^\s>]*)""",re.I)
_SAN_SRCDOC_RX=re.compile(r"""(?<![\w-])(?:srcdoc|formaction)\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)""",re.I)
def sanitize_note_html(content):
    """Defence in depth for stored note HTML: script-capable elements, on* handlers and javascript: URLs are removed. The UI sanitises again, with a DOM allow-list, before showing a note."""
    t=content or ""
    if "<" not in t:return t
    t=_SAN_BLOCK_RX.sub("",t)
    t=_SAN_TAG_RX.sub("",t)
    def tag(m):
        g=m.group(0)
        low=g.lower()
        if "on" not in low and "script" not in low and "srcdoc" not in low and "formaction" not in low and "data" not in low:return g
        g=_SAN_ON_ATTR_RX.sub("",g)
        g=_SAN_SRCDOC_RX.sub("",g)
        return _SAN_URL_ATTR_RX.sub(lambda u:u.group(1)+'"#"',g)
    return _SAN_ANY_TAG_RX.sub(tag,t)
def _unpin_note(note_id):
    meta=_load_notes_meta()
    key=_note_refs.note_ref_key(note_id=note_id)
    current=meta.get("pinned",[])
    filtered=[r for r in current if _note_refs.note_ref_key(r)!=key]
    if len(filtered)!=len(current):
        _save_notes_meta(filtered,meta.get("recent",[]),meta.get("groups",[]),meta.get("nav_collapsed_groups",[]))
def _settings_path():
    d=_abs("Data");os.makedirs(d,exist_ok=True)
    return os.path.join(d,"settings.json")
_SETTINGS_CACHE=None
_SETTINGS_MTIME=None
def _read_settings():
    global _SETTINGS_CACHE,_SETTINGS_MTIME
    p=_settings_path()
    try:m=os.path.getmtime(p)
    except Exception:m=None
    if _SETTINGS_CACHE is not None and m==_SETTINGS_MTIME:return _SETTINGS_CACHE
    try:
        if not p or not os.path.isfile(p):
            _SETTINGS_CACHE={}
            _SETTINGS_MTIME=m
            return _SETTINGS_CACHE
        with open(p,"r",encoding="utf-8") as f:
            d=json.load(f)
            if not isinstance(d,dict):d={}
            _SETTINGS_CACHE=d
            _SETTINGS_MTIME=m
            return d
    except Exception:
        _SETTINGS_CACHE={}
        _SETTINGS_MTIME=m
        return _SETTINGS_CACHE
def _write_settings(data):
    global _SETTINGS_CACHE,_SETTINGS_MTIME
    p=_settings_path()
    t=p+".tmp"
    try:
        os.makedirs(os.path.dirname(p),exist_ok=True)
        with open(t,"w",encoding="utf-8") as f:json.dump(data if isinstance(data,dict) else {},f,ensure_ascii=False,indent=2)
        os.replace(t,p)
        try:_SETTINGS_CACHE=data if isinstance(data,dict) else {}
        except Exception:pass
        try:_SETTINGS_MTIME=os.path.getmtime(p)
        except Exception:_SETTINGS_MTIME=None
        return True
    except Exception as e:
        _log("[!]",f"Settings write failed: {p} ({e})")
        try:
            if os.path.isfile(t):os.remove(t)
        except Exception:pass
        return False
def _norm_hex_color(v):
    s=_norm(v)
    if not s:return ""
    if re.fullmatch(r"#?[0-9a-fA-F]{6}",s):
        return s if s.startswith("#") else "#"+s
    return ""
def _auto_fg_for_bg(hexv):
    color=_norm_hex_color(hexv) or _NOTE_LINK_COLOR_DEFAULT
    h=color.lstrip("#")
    if len(h)!=6:
        return "#000000"
    try:
        r=int(h[0:2],16);g=int(h[2:4],16);b=int(h[4:6],16)
    except Exception:
        return "#000000"
    lum=(0.299*r+0.587*g+0.114*b)/255.0
    return "#000000" if lum>0.6 else "#ffffff"
def _note_ref_color():
    s=_read_settings()
    c=_norm_hex_color(s.get("note_ref_color","") if isinstance(s,dict) else "")
    return c or _pal().get("note-ref-default",_NOTE_REF_COLOR_DEFAULT)
@_settings_lock.serialized
def _set_note_ref_color_setting(hexv):
    s=_read_settings()
    if not isinstance(s,dict):s={}
    if hexv:s["note_ref_color"]=hexv
    else:s.pop("note_ref_color",None)
    _write_settings(s)
def _note_text_color():
    s=_read_settings()
    c=_norm_hex_color(s.get("note_text_color","") if isinstance(s,dict) else "")
    return c or _pal().get("note-text-default","#ffffff")
@_settings_lock.serialized
def _set_note_text_color_setting(hexv):
    s=_read_settings()
    if not isinstance(s,dict):s={}
    c=_norm_hex_color(hexv) or _pal().get("note-text-default","#ffffff")
    s["note_text_color"]=c
    _write_settings(s)
def _note_highlight_color():
    s=_read_settings()
    c=_norm_hex_color(s.get("note_highlight_color","") if isinstance(s,dict) else "")
    return c or _pal().get("note-highlight-default","#fff3bf")
@_settings_lock.serialized
def _set_note_highlight_color_setting(hexv):
    s=_read_settings()
    if not isinstance(s,dict):s={}
    c=_norm_hex_color(hexv) or _pal().get("note-highlight-default","#fff3bf")
    s["note_highlight_color"]=c
    _write_settings(s)
def _draft_recovery_path():
    d=_abs("Data");os.makedirs(d,exist_ok=True)
    return os.path.join(d,"note_draft_recovery.json")
def _iter_note_refs(text):
    t=text or ""
    for m in _NOTE_REF_RX.finditer(t):
        raw=m.group(1) or ""
        if not raw:continue
        name=raw.strip()
        if not name:continue
        start=m.start(1)
        ltrim=len(raw)-len(raw.lstrip())
        rtrim=len(raw.rstrip())
        if rtrim<=ltrim:continue
        yield name,start+ltrim,start+rtrim
def _cmd_id(data):
    parts=[
        _norm(data.get("cmd_note_title","")),
        _norm(data.get("category","")),
        _norm(data.get("sub_category","")),
        _norm(data.get("description","")),
        _norm(data.get("tags","")),
        _norm(data.get("command","")),
    ]
    raw="|".join(parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12] if raw else ""
def _encode_cmd_data(data):
    if not isinstance(data,dict):return ""
    d=dict(data)
    if not _norm(d.get("cid","")):d["cid"]=_cmd_id(d)
    raw=json.dumps(d,ensure_ascii=False)
    b=base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")
    return b.rstrip("=")
def _decode_cmd_data(token):
    t=_norm(token)
    if not t:return {}
    pad="="*((4-len(t)%4)%4)
    try:
        raw=base64.urlsafe_b64decode(t+pad).decode("utf-8")
        d=json.loads(raw)
        return d if isinstance(d,dict) else {}
    except Exception:
        return {}
def _encode_note_link_data(note,color=None):
    ref=_note_refs.normalize_note_ref(note)
    d={
        "note_id":ref.get("note_id"),
        "note_name":ref.get("note_name",""),
        "note":ref.get("note_name",""),
    }
    raw=json.dumps(d,ensure_ascii=False)
    b=base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")
    return b.rstrip("=")
def _decode_note_link_data(token):
    t=_norm(token)
    if not t:return {}
    pad="="*((4-len(t)%4)%4)
    try:
        raw=base64.urlsafe_b64decode(t+pad).decode("utf-8")
        d=json.loads(raw)
        if not isinstance(d,dict):
            return {}
        ref=_note_refs.normalize_note_ref(d)
        return {"note_id":ref.get("note_id"),"note_name":ref.get("note_name",""),"note":ref.get("note_name",""),"color":_norm_hex_color(d.get("color",""))}
    except Exception:
        return {}
def _parse_cmd_meta(meta):
    d={"cmd_note_title":"","category":"","sub_category":"","description":"","tags":""}
    for p in [x.strip() for x in (meta or "").split(",") if x.strip()]:
        if ":" not in p:continue
        k,v=p.split(":",1)
        k=(k or "").strip().lower()
        v=(v or "").strip()
        if "command note tittle" in k or "note title" in k:d["cmd_note_title"]=v
        elif k=="category":d["category"]=v
        elif "sub category" in k or "subcategory" in k:d["sub_category"]=v
        elif k=="description":d["description"]=v
        elif k=="tags":d["tags"]=v
    return d
def _cmd_meta(dbp):
    cats=set();subm={}
    try:
        with _common_db.connection(dbp,timeout=5) as con:
            cur=con.cursor()
            for t in ("CommandsNotes","Commands"):
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",(t,))
                if not cur.fetchone():continue
                cols=[c.lower() for c in _table_cols(cur,t)]
                if "category" not in cols:continue
                subcol="sub_category" if "sub_category" in cols else ("subcategory" if "subcategory" in cols else "")
                if not subcol:continue
                cur.execute(f"SELECT DISTINCT category,{subcol} FROM {t} WHERE category IS NOT NULL AND TRIM(category)!=''")
                for c,sc in cur.fetchall():
                    c=_norm(c);sc=_norm(sc)
                    if not c:continue
                    cats.add(c);subm.setdefault(c,set())
                    if sc:subm[c].add(sc)
    except Exception:pass
    cats=sorted(list(cats),key=lambda x:x.lower())
    return cats,{c:sorted(list(subm.get(c,set())),key=lambda x:x.lower()) for c in cats}
def _sig(name,htmls,group_name=""):
    s=(name or "").strip()+"\n"+_norm(group_name)+"\n"+(htmls or "")
    return hashlib.sha256(s.encode("utf-8","ignore")).hexdigest()
def _fmt_note_time(t):
    raw=_norm(t)
    if not raw:return ""
    dt=None
    try:
        dt=datetime.fromisoformat(raw.replace("Z","+00:00"))
    except Exception:
        for fmt in ("%Y-%m-%d %H:%M:%S","%Y-%m-%dT%H:%M:%S"):
            try:
                dt=datetime.strptime(raw[:19],fmt)
                break
            except Exception:
                dt=None
    if not dt:return raw.replace("T"," ")[:19]
    try:dt=dt.astimezone()
    except Exception:pass
    return dt.strftime("%H:%M %d/%m/%Y")
def _insert_note_history(cur,note_id,note_name,group_name,content,action,action_at):
    try:
        cur.execute("INSERT INTO NotesHistory(note_id,note_name,group_name,content,action,action_at) VALUES(?,?,?,?,?,?)",(note_id,note_name,group_name,content,action,action_at))
    except Exception:pass
def _insert_cmd_history(cur,cmd_id,note_id,note_name,cmd_note_title,category,sub_category,description,tags,command,action,action_at):
    try:
        cur.execute("INSERT INTO CommandsHistory(cmd_id,note_id,note_name,cmd_note_title,category,sub_category,description,tags,command,action,action_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(cmd_id,note_id,note_name,cmd_note_title,category,sub_category,description,tags,command,action,action_at))
    except Exception:pass
def _load_notes(dbp):
    try:
        with _common_db.connection(dbp,timeout=5) as con:
            _ensure_schema(con)
            cur=con.cursor()
            cols=set(_table_cols(cur,"Notes"))
            sel=["id","note_name"]
            if "group_name" in cols:sel.append("group_name")
            if "tags" in cols:sel.append("tags")
            sel+=["content","created_at","updated_at"]
            cur.execute("SELECT "+",".join(sel)+" FROM Notes ORDER BY updated_at DESC")
            rows=cur.fetchall()
        out=[]
        for r in rows:
            i=0
            rid=r[i];i+=1
            note_name=r[i];i+=1
            group_name=(r[i] if "group_name" in sel else "");i+=1 if "group_name" in sel else 0
            tags=(r[i] if "tags" in sel else "");i+=1 if "tags" in sel else 0
            content=r[i] if i<len(r) else "";i+=1
            created_at=r[i] if i<len(r) else "";i+=1
            updated_at=r[i] if i<len(r) else ""
            out.append({"id":rid,"note_name":(note_name or "").strip(),"group_name":_norm(group_name),"tags":_norm(tags),"content":content or "","created_at":created_at or "","updated_at":updated_at or ""})
        return out
    except Exception as e:
        _log("[!]",f"Load notes failed ({e})")
        return []
def _load_note_commands(dbp,note_id=None,note_name=""):
    try:
        with _common_db.connection(dbp,timeout=5) as con:
            _ensure_schema(con);_ensure_cmd_schema(con)
            cur=con.cursor()
            rows=[]
            if note_id is not None:
                try:
                    cur.execute("SELECT cmd_note_title,category,sub_category,description,tags,command,command_type FROM Commands WHERE note_id=? ORDER BY id",(int(note_id),))
                    rows=cur.fetchall()
                except Exception:rows=[]
            if not rows and _norm(note_name):
                cur.execute("SELECT cmd_note_title,category,sub_category,description,tags,command,command_type FROM Commands WHERE note_name=? ORDER BY id",(_norm(note_name),))
                rows=cur.fetchall()
        out=[]
        for r in rows:
            d={"cmd_note_title":_norm(r[0] if len(r)>0 else ""),"category":_norm(r[1] if len(r)>1 else ""),"sub_category":_norm(r[2] if len(r)>2 else ""),"description":_norm(r[3] if len(r)>3 else ""),"tags":_norm(r[4] if len(r)>4 else ""),"command":(r[5] if len(r)>5 else "") or "","command_type":_norm(r[6] if len(r)>6 else "") or "other"}
            if _norm(d.get("command","")):d["cid"]=_cmd_id(d);out.append(d)
        return out
    except Exception as e:
        _log("[!]",f"Load note commands failed ({e})")
        return []
def _delete_note(dbp,name):
    try:
        with _common_db.connection(dbp,timeout=5) as con:
            _ensure_schema(con);_ensure_cmd_schema(con)
            cur=con.cursor()
            cols=set(_table_cols(cur,"Notes"))
            sel="id,note_name"+(",group_name" if "group_name" in cols else "")+",content,created_at,updated_at"
            cur.execute(f"SELECT {sel} FROM Notes WHERE note_name=?",(name,))
            r=cur.fetchone()
            if not r:return False
            nid=int(r[0]);now=datetime.now(timezone.utc).isoformat()
            group_name=(r[2] if "group_name" in cols else "")
            content=(r[3] if "group_name" in cols else r[2])
            created_at=(r[4] if "group_name" in cols else r[3])
            updated_at=(r[5] if "group_name" in cols else r[4])
            note_tags=""
            if "tags" in cols:
                cur.execute("SELECT tags FROM Notes WHERE id=?",(nid,));tr=cur.fetchone();note_tags=(tr[0] if tr else "") or ""
            _insert_note_history(cur,nid,r[1] or "",group_name or "",content or "","delete",now)
            recycle_cmds=[]
            try:
                cur.execute("SELECT id,note_id,note_name,cmd_note_title,category,sub_category,description,tags,command,created_at,updated_at,command_type,noise_level FROM Commands WHERE note_id=?",(nid,))
                for row in cur.fetchall():
                    _insert_cmd_history(cur,row[0],row[1],row[2],row[3],row[4],row[5],row[6],row[7],row[8],"delete",now)
                    recycle_cmds.append({"id":row[0],"note_id":row[1],"note_name":row[2],"cmd_note_title":row[3],"category":row[4],"sub_category":row[5],"description":row[6],"tags":row[7],"command":row[8],"created_at":row[9] or "","updated_at":row[10] or "","command_type":row[11] or "other","noise_level":row[12] or "normal"})
            except Exception:pass
            _recycle_bin.put_entry_cur(cur,_recycle_bin.TYPE_NOTE,r[1] or "",{"note":{"id":nid,"note_name":r[1] or "","group_name":group_name or "","tags":note_tags,"content":content or "","created_at":created_at or "","updated_at":updated_at or ""},"commands":recycle_cmds},source="Notes",entity_key=str(nid),deleted_at=now,expires_at=_recycle_bin.expires_text())
            con.execute("DELETE FROM Commands WHERE note_id=?",(nid,))
            cur.execute("DELETE FROM Notes WHERE id=?",(nid,))
            con.commit()
            _unpin_note(nid)
            return bool(cur.rowcount)
    except Exception as e:
        _log("[!]",f"Delete note failed ({e})")
        return False
def linked_from_notes(dbp,target,notes=None):
    if not isinstance(target,dict):return []
    if notes is None:notes=_load_notes(dbp)
    tid=target.get("id",None);tn=_norm(target.get("note_name",""))
    out=[];seen=set()
    for n in notes:
        try:
            if tid is not None and int(n.get("id"))==int(tid):continue
        except Exception:
            pass
        if tn and _kci(n.get("note_name",""))==_kci(tn):continue
        content=n.get("content","") or ""
        matched=False
        for m in re.finditer(re.escape(_NOTE_LINK_ANCHOR)+r"([A-Za-z0-9_-]+)",content):
            data=_decode_note_link_data(m.group(1))
            did=_note_refs.note_ref_id(data);dn=_note_refs.note_ref_name(data)
            try:
                if tid is not None and did is not None and int(did)==int(tid):matched=True
            except Exception:
                pass
            if not matched and tn and dn and _kci(dn)==_kci(tn):matched=True
            if matched:break
        if matched:
            ref=_note_refs.serialize_note_ref(note_id=n.get("id"),note_name=n.get("note_name",""))
            key=_note_refs.note_ref_key(ref)
            if key and key not in seen:seen.add(key);out.append(n)
    return out
def note_link_graph():
    dbp=_db_path()
    notes=_load_notes(dbp)
    ids={n["id"] for n in notes}
    nodes=[{"id":n["id"],"note_name":n["note_name"],"group_name":n["group_name"]} for n in notes]
    edges=[];seen=set()
    for n in notes:
        content=n.get("content","") or ""
        for m in re.finditer(re.escape(_NOTE_LINK_ANCHOR)+r"([A-Za-z0-9_-]+)",content):
            data=_decode_note_link_data(m.group(1))
            did=_note_refs.note_ref_id(data)
            if did is None or did not in ids or did==n["id"]:continue
            key=(n["id"],did)
            if key in seen:continue
            seen.add(key);edges.append({"source":n["id"],"target":did})
    return {"nodes":nodes,"edges":edges}
def group_summary_text(notes):
    names=[_norm(n.get("note_name","")) for n in (notes or []) if _norm(n.get("note_name",""))]
    if not names:return "No notes"
    head=", ".join(names[:3])
    if len(names)>3:head+=f", +{len(names)-3} more"
    return head
def group_full_text(notes):
    names=[_norm(n.get("note_name","")) for n in (notes or []) if _norm(n.get("note_name",""))]
    return ", ".join(names)
def apply_group_update(dbp,notes,target_group,action):
    rows=[]
    for n in notes or []:
        try:nid=int(n.get("id"))
        except Exception:continue
        rows.append({"id":nid,"note_name":_norm(n.get("note_name","")),"content":n.get("content","") or ""})
    if not rows:return 0,[]
    target=_norm(target_group)
    now=datetime.now(timezone.utc).isoformat()
    with _common_db.connection(dbp,timeout=5) as con:
        _ensure_schema(con)
        cur=con.cursor()
        for row in rows:
            cur.execute("UPDATE Notes SET group_name=?,updated_at=? WHERE id=?",(target,now,int(row["id"])))
            _insert_note_history(cur,row["id"],row["note_name"],target,row["content"],action,now)
    return len(rows),[r["id"] for r in rows]
_NAV_UNGROUPED_KEY="__ungrouped__"
def _nav_group_key(g):
    g=_norm(g)
    return _NAV_UNGROUPED_KEY if not g or _kci(g)==_NAV_UNGROUPED_KEY else _kci(g)
def _store_meta(meta,groups=None,collapsed=None):
    return _save_notes_meta(meta.get("pinned",[]),meta.get("recent",[]),meta.get("groups",[]) if groups is None else groups,meta.get("nav_collapsed_groups",[]) if collapsed is None else collapsed)
def ensure_group_meta(name):
    grp=_norm(name)
    if not grp:return ""
    meta=_load_notes_meta()
    known=meta["groups"]+[n["group_name"] for n in _load_notes(_db_path()) if n["group_name"]]
    hit=next((g for g in known if _kci(g)==_kci(grp)),None)
    if hit and any(_kci(g)==_kci(grp) for g in meta["groups"]):return hit
    _store_meta(meta,groups=meta["groups"]+[hit or grp])
    return hit or grp
def rename_group(dbp,old_group,new_group):
    old=_norm(old_group);new=_norm(new_group)
    if not old:raise ValueError("Ungrouped notes cannot be renamed. Move a note into a named group instead.")
    if not new:raise ValueError("Group name is required.")
    if _kci(old)==_kci(new):return 0
    notes=[n for n in _load_notes(dbp) if _kci(n["group_name"])==_kci(old)]
    changed=apply_group_update(dbp,notes,new,"group_rename")[0] if notes else 0
    meta=_load_notes_meta()
    groups=[g for g in meta["groups"] if _kci(g)!=_kci(old)]
    if not any(_kci(g)==_kci(new) for g in groups):groups.append(new)
    collapsed=[(new if _nav_group_key(c)==_kci(old) else c) for c in meta["nav_collapsed_groups"]]
    _store_meta(meta,groups=groups,collapsed=collapsed)
    return changed
def move_note_to_group(dbp,note_id,target_group):
    note=next((n for n in _load_notes(dbp) if int(n["id"])==int(note_id)),None)
    if not note:raise ValueError("Note not found.")
    target=_norm(target_group)
    if target:target=ensure_group_meta(target) or target
    if _kci(target)==_kci(note["group_name"]) and target==note["group_name"]:return 0
    return apply_group_update(dbp,[note],target,"group_move" if target else "ungroup")[0]
def delete_empty_group(dbp,group_name):
    grp=_norm(group_name)
    if not grp:return False
    if any(_kci(n["group_name"])==_kci(grp) for n in _load_notes(dbp)):raise ValueError("Move or ungroup all notes before deleting this group.")
    meta=_load_notes_meta()
    _store_meta(meta,groups=[g for g in meta["groups"] if _kci(g)!=_kci(grp)],collapsed=[c for c in meta["nav_collapsed_groups"] if _nav_group_key(c)!=_kci(grp)])
    return True
def collapsed_group_keys():
    return [_nav_group_key(c) for c in _load_notes_meta().get("nav_collapsed_groups",[])]
def set_group_collapsed(group_name,collapsed):
    grp=_norm(group_name);key=_nav_group_key(grp)
    meta=_load_notes_meta()
    rows=[c for c in meta["nav_collapsed_groups"] if _nav_group_key(c)!=key]
    if collapsed:rows.append(grp or _NAV_UNGROUPED_KEY)
    _store_meta(meta,collapsed=rows)
    return bool(collapsed)
_CMD_BOX_CMD_MIN_H=72
_CMD_BOX_CMD_DEFAULT_H=86
_CMD_BOX_CMD_MAX_H=180
def _cmd_box_height_clamp(v):
    try:n=int(v)
    except Exception:n=_CMD_BOX_CMD_DEFAULT_H
    return max(_CMD_BOX_CMD_MIN_H,min(_CMD_BOX_CMD_MAX_H,n))
def _cmd_box_command_height():
    s=_read_settings()
    n=s.get("note",{}) if isinstance(s,dict) and isinstance(s.get("note",{}),dict) else {}
    return _cmd_box_height_clamp(n.get("cmd_box_command_height",_CMD_BOX_CMD_DEFAULT_H))
_NOTE_BOOL_PREFS=("editor_maximized","editor_outline","suggest_title","suggest_tags","auto_pairs_off","editor_bubble_off")
_TOOLBAR_ID_RX=re.compile(r"^[a-z][a-zA-Z0-9.]{0,39}$")
def _toolbar_main(v):
    """The pinned main-bar tools of the note editor: a list of command ids, or None for the default bar. The UI drops ids it does not know."""
    if not isinstance(v,(list,tuple)):return None
    out=[]
    for x in v:
        if isinstance(x,str) and _TOOLBAR_ID_RX.match(x) and x not in out:out.append(x)
    return out[:40]
_NOTE_RECENT_COLORS_MAX=12
def _note_prefs_dict():
    s=_read_settings()
    n=s.get("note",{}) if isinstance(s,dict) else {}
    return n if isinstance(n,dict) else {}
def _recent_colors(v):
    out=[]
    for c in (v if isinstance(v,(list,tuple)) else []):
        h=(_norm_hex_color(c) or "").lower()
        if h and h not in out:out.append(h)
    return out[:_NOTE_RECENT_COLORS_MAX]
def _draw_width(v):
    try:n=int(v)
    except Exception:n=2
    return n if n in (1,2,3,4) else 2
def editor_prefs():
    s=_read_settings()
    s=s if isinstance(s,dict) else {}
    n=_note_prefs_dict()
    out={"note_ref_color":_note_ref_color(),"note_text_color":_norm_hex_color(s.get("note_text_color","")),"note_highlight_color":_norm_hex_color(s.get("note_highlight_color","")),"cmd_box_command_height":_cmd_box_command_height(),"cmd_box_min":_CMD_BOX_CMD_MIN_H,"cmd_box_max":_CMD_BOX_CMD_MAX_H}
    # Pro editor preferences (all under settings.json "note"). The suggestion toggles are opt-in: off unless the user turned them on.
    for k in _NOTE_BOOL_PREFS:out[k]=n.get(k) is True
    # Privacy default: remote (http/https) images in notes are not fetched until clicked, unless the user turns this off.
    out["block_remote_images"]=n.get("block_remote_images") is not False
    out["recent_colors"]=_recent_colors(n.get("recent_colors"))
    out["draw_color"]=(_norm_hex_color(n.get("draw_color","")) or "#f03e3e").lower()
    out["draw_width"]=_draw_width(n.get("draw_width",2))
    out["toolbar_main"]=_toolbar_main(n.get("toolbar_main"))
    return out
def set_editor_pref(key,value):
    global _SETTINGS_CACHE
    k=_norm(key)
    def note_set(d,name,v):
        n=dict(d.get("note",{})) if isinstance(d.get("note",{}),dict) else {}
        n[name]=v;d["note"]=n
    def mut(d):
        if k=="note_text_color":d[k]=_norm_hex_color(value) or _pal().get("note-text-default","#ffffff")
        elif k=="note_highlight_color":d[k]=_norm_hex_color(value) or _pal().get("note-highlight-default","#fff3bf")
        elif k=="note_ref_color":
            if _norm_hex_color(value):d[k]=_norm_hex_color(value)
            else:d.pop(k,None)
        elif k in _NOTE_BOOL_PREFS:note_set(d,k,value is True)
        elif k=="block_remote_images":note_set(d,k,value is not False)
        elif k=="recent_colors":note_set(d,k,_recent_colors(value))
        elif k=="draw_color":note_set(d,k,(_norm_hex_color(value) or "#f03e3e").lower())
        elif k=="draw_width":note_set(d,k,_draw_width(value))
        elif k=="toolbar_main":
            t=_toolbar_main(value)
            if t is None:
                n=dict(d.get("note",{})) if isinstance(d.get("note",{}),dict) else {}
                n.pop(k,None);d["note"]=n
            else:note_set(d,k,t)
        else:note_set(d,"cmd_box_command_height",_cmd_box_height_clamp(value))
    if k not in ("note_text_color","note_highlight_color","note_ref_color","cmd_box_command_height","recent_colors","draw_color","draw_width","toolbar_main","block_remote_images")+_NOTE_BOOL_PREFS:raise ValueError(f"Unknown editor preference: {k}")
    _settings_lock.update_json(_settings_path(),mut)
    _SETTINGS_CACHE=None
    return editor_prefs()
# ---- Notes sidebar: one payload for the whole left bar (a single DB read), its UI preferences (settings.json "note"."sidebar"),
# per-group colour/icon, pinned order, recently opened notes and the content search. Per-note facts are cached on (id, updated_at, size).
_SB_VIEWS=("groups","tags","recent","targets")
_SB_SORTS=("name","edited","created")
_SB_DIRS=("asc","desc")
_SB_DENSITIES=("comfortable","compact")
_SB_FILTERS=("pinned","findings","commands","untagged")
_SB_SCOPES=("name","tags","content")
_SB_ICONS=("folder","target","command-line","report","star","file","link","brain","search","list","home","info")
_SB_BOOL_PREFS={"nested":True,"show_recent":True}
_SB_W_MIN=220
_SB_W_MAX=560
_SB_W_DEFAULT=280
_SB_RECENT_MAX=12
_SB_SEVERITIES=("critical","high","medium","low","info")
_SB_SEV_RX=re.compile(r'data-sev="(critical|high|medium|low|info)"',re.I)
_SB_CALLOUT_RX=re.compile(r'data-callout="([a-z]+)"',re.I)
_SB_CMD_TOKEN_RX=re.compile(r'src="cmdcard:([^"]+)"',re.I)
_SB_META_CACHE={}
_SB_TEXT_CACHE={}
def _sb_pick(v,allowed,default):
    s=_kci(v) if isinstance(v,str) else ""
    return s if s in allowed else default
def _sb_list(v,allowed):
    return [x for x in allowed if x in {_kci(i) for i in (v if isinstance(v,(list,tuple)) else []) if isinstance(i,str)}]
def _sb_width(v):
    try:n=int(v)
    except Exception:n=_SB_W_DEFAULT
    return max(_SB_W_MIN,min(_SB_W_MAX,n))
def _sb_group_styles(v):
    out={}
    for k,st in (v.items() if isinstance(v,dict) else []):
        key=_kci(k)
        if not key or not isinstance(st,dict):continue
        color=(_norm_hex_color(st.get("color","")) or "").lower();icon=_sb_pick(st.get("icon",""),_SB_ICONS,"")
        if color or icon:out[key]={"color":color,"icon":icon}
    return out
def _sb_dict():
    s=_note_prefs_dict().get("sidebar")
    return s if isinstance(s,dict) else {}
def sidebar_prefs():
    s=_sb_dict()
    scopes=_sb_list(s.get("scopes"),_SB_SCOPES) if "scopes" in s else ["name","tags"]
    out={"view":_sb_pick(s.get("view"),_SB_VIEWS,"groups"),"sort":_sb_pick(s.get("sort"),_SB_SORTS,"name"),"dir":_sb_pick(s.get("dir"),_SB_DIRS,"asc"),"density":_sb_pick(s.get("density"),_SB_DENSITIES,"comfortable"),"width":_sb_width(s.get("width",_SB_W_DEFAULT)),"filters":_sb_list(s.get("filters"),_SB_FILTERS),"scopes":scopes or ["name"],"group_styles":_sb_group_styles(s.get("group_styles")),"width_min":_SB_W_MIN,"width_max":_SB_W_MAX}
    for k,d in _SB_BOOL_PREFS.items():out[k]=s.get(k) if isinstance(s.get(k),bool) else d
    return out
def _sb_update(mutate):
    global _SETTINGS_CACHE
    def mut(d):
        n=dict(d.get("note",{})) if isinstance(d.get("note",{}),dict) else {}
        sb=dict(n.get("sidebar",{})) if isinstance(n.get("sidebar",{}),dict) else {}
        mutate(sb);n["sidebar"]=sb;d["note"]=n
    _settings_lock.update_json(_settings_path(),mut)
    _SETTINGS_CACHE=None
    return sidebar_prefs()
def set_sidebar_pref(key,value):
    k=_kci(key) if isinstance(key,str) else ""
    if k=="view":v=_sb_pick(value,_SB_VIEWS,"groups")
    elif k=="sort":v=_sb_pick(value,_SB_SORTS,"name")
    elif k=="dir":v=_sb_pick(value,_SB_DIRS,"asc")
    elif k=="density":v=_sb_pick(value,_SB_DENSITIES,"comfortable")
    elif k=="width":v=_sb_width(value)
    elif k=="filters":v=_sb_list(value,_SB_FILTERS)
    elif k=="scopes":v=_sb_list(value,_SB_SCOPES) or ["name"]
    elif k in _SB_BOOL_PREFS:v=value is True
    else:raise ValueError(f"Unknown sidebar preference: {k}")
    return _sb_update(lambda sb:sb.__setitem__(k,v))
def set_group_style(group_name,color="",icon=""):
    key=_nav_group_key(group_name if isinstance(group_name,str) else "")
    c=(_norm_hex_color(color) or "").lower();i=_sb_pick(icon,_SB_ICONS,"")
    def mut(sb):
        st=_sb_group_styles(sb.get("group_styles"))
        if c or i:st[key]={"color":c,"icon":i}
        else:st.pop(key,None)
        sb["group_styles"]=st
    return _sb_update(mut)["group_styles"]
def move_group_style(old_group,new_group=""):
    """Carry a group's colour/icon to its new name (rename), or drop it (delete: new_group empty)."""
    old=_kci(old_group);new=_kci(new_group)
    if not old or old not in _sb_group_styles(_sb_dict().get("group_styles")):return False
    def mut(sb):
        st=_sb_group_styles(sb.get("group_styles"))
        cur=st.pop(old,None)
        if cur and new and new not in st:st[new]=cur
        sb["group_styles"]=st
    _sb_update(mut)
    return True
def note_epoch_ms(t):
    raw=_norm(t)
    if not raw:return 0
    dt=None
    try:dt=datetime.fromisoformat(raw.replace("Z","+00:00"))
    except Exception:
        try:dt=datetime.strptime(raw[:19].replace("T"," "),"%Y-%m-%d %H:%M:%S")
        except Exception:return 0
    try:return int(dt.timestamp()*1000)
    except Exception:return 0
def note_sidebar_meta(content):
    """Cheap facts for a note row: command cards, callouts, and the highest severity among its finding/vulnerability callouts."""
    t=content or ""
    kinds=[k.lower() for k in _SB_CALLOUT_RX.findall(t)]
    sevs={s.lower() for s in _SB_SEV_RX.findall(t)}
    findings=sum(1 for k in kinds if k in ("finding","vuln"))
    return {"cmds":len(_SB_CMD_TOKEN_RX.findall(t)),"callouts":len(kinds),"findings":findings,"sev":next((s for s in _SB_SEVERITIES if s in sevs),"")}
def _sb_cached(cache,note,build):
    key=(note.get("updated_at",""),len(note.get("content","")),note.get("note_name",""))
    hit=cache.get(note["id"])
    if hit and hit[0]==key:return hit[1]
    v=build(note);cache[note["id"]]=(key,v)
    return v
def _sb_prune(cache,notes):
    live={n["id"] for n in notes}
    for k in [k for k in cache if k not in live]:cache.pop(k,None)
def note_search_text(content):
    """Plain text of a note for searching: the visible text plus the title and command of every command card (they live in base64 tokens)."""
    t=content or ""
    parts=[_strip_html(re.sub(r"(?i)</(?:h[1-6]|div|li|tr|td|th|blockquote|summary)>"," \n",t))]
    for tok in dict.fromkeys(_SB_CMD_TOKEN_RX.findall(t)):
        d=_decode_cmd_data(tok)
        if isinstance(d,dict):parts+=[_norm(d.get("cmd_note_title","")),_norm(d.get("command",""))]
    return "\n".join(p for p in parts if p)
def _sb_text(note):
    return _sb_cached(_SB_TEXT_CACHE,note,lambda n:note_search_text(n.get("content","")))
def target_terms(targets):
    """[{name, terms}] for the Targets view: the target name plus its distinctive values (hosts, addresses, URLs) - not ports, paths or short words."""
    out=[]
    for t in targets if isinstance(targets,(list,tuple)) else []:
        if not isinstance(t,dict):continue
        name=_norm(t.get("name",""))
        if not name:continue
        terms=[name.lower()]
        vals=t.get("values",{})
        for v in (vals.values() if isinstance(vals,dict) else []):
            s=_norm(v).lower()
            if len(s)<4 or len(s)>120 or s.startswith(("/","~","\\")) or re.fullmatch(r"[\d\s,;-]{1,6}",s) or re.fullmatch(r"[a-z]:\\.*",s):continue
            if s not in terms:terms.append(s)
        out.append({"name":name,"terms":terms})
    return out
def note_targets(note,terms):
    hay="\n".join([note.get("note_name",""),note.get("group_name",""),note.get("tags",""),_sb_text(note)]).lower()
    return [t["name"] for t in terms if any(x in hay for x in t["terms"])]
def recent_note_ids(live=None):
    out=[]
    for r in _load_notes_meta().get("recent",[]):
        nid=_note_refs.note_ref_id(r)
        if nid is None:continue
        nid=int(nid)
        if nid not in out and (live is None or nid in live):out.append(nid)
    return out[:_SB_RECENT_MAX]
def touch_recent(note_id,note_name=""):
    nid=int(note_id)
    meta=_load_notes_meta()
    rest=[r for r in meta.get("recent",[]) if _note_refs.note_ref_id(r) is not None and int(_note_refs.note_ref_id(r))!=nid]
    recent=[_note_refs.serialize_note_ref(note_id=nid,note_name=_norm(note_name))]+rest
    _save_notes_meta(meta.get("pinned",[]),recent[:_SB_RECENT_MAX],meta.get("groups",[]),meta.get("nav_collapsed_groups",[]))
    return recent_note_ids()
def pinned_order_ids():
    out=[]
    for r in pinned_refs():
        nid=_note_refs.note_ref_id(r)
        if nid is not None and int(nid) not in out:out.append(int(nid))
    return out
def reorder_pinned(note_ids):
    """Rewrite the pinned list in the given order. Ids that are not pinned are ignored; pinned notes left out keep their place at the end."""
    meta=_load_notes_meta()
    cur=meta.get("pinned",[])
    by_id={}
    for r in cur:
        nid=_note_refs.note_ref_id(r)
        if nid is not None:by_id.setdefault(int(nid),r)
    order=[]
    for i in note_ids if isinstance(note_ids,(list,tuple)) else []:
        try:n=int(i)
        except Exception:continue
        if n in by_id and n not in order:order.append(n)
    head=[by_id[n] for n in order]
    tail=[r for r in cur if _note_refs.note_ref_id(r) is None or int(_note_refs.note_ref_id(r)) not in order]
    _save_notes_meta(head+tail,meta.get("recent",[]),meta.get("groups",[]),meta.get("nav_collapsed_groups",[]))
    return pinned_order_ids()
def set_groups_collapsed(group_names,collapsed):
    """Collapse or expand many groups in one write (Expand all / Collapse all)."""
    group_names=[g for g in (group_names if isinstance(group_names,(list,tuple)) else []) if isinstance(g,str)]
    keys={_nav_group_key(g) for g in group_names}
    meta=_load_notes_meta()
    rows=[c for c in meta["nav_collapsed_groups"] if _nav_group_key(c) not in keys]
    if collapsed:rows+=[_norm(g) or _NAV_UNGROUPED_KEY for g in group_names if _nav_group_key(g) in keys]
    _store_meta(meta,collapsed=rows)
    return collapsed_group_keys()
def sidebar_data(dbp,targets=None):
    notes=_load_notes(dbp)
    meta=_load_notes_meta()
    live={int(n["id"]) for n in notes}
    pinned=[i for i in pinned_order_ids() if i in live]
    pset=set(pinned)
    terms=target_terms(targets)
    sig=json.dumps(terms,sort_keys=True)
    rows=[]
    for n in notes:
        m=_sb_cached(_SB_META_CACHE,n,lambda x:note_sidebar_meta(x.get("content","")))
        row={"id":n["id"],"note_name":n["note_name"],"group_name":n["group_name"],"tags":n.get("tags",""),"updated_at":n["updated_at"],"updated_label":_fmt_note_time(n["updated_at"]),"updated_ts":note_epoch_ms(n["updated_at"]),"created_ts":note_epoch_ms(n["created_at"]),"pinned":int(n["id"]) in pset}
        row.update(m)
        if terms:row["targets"]=_sb_cached(_SB_TEXT_CACHE,{"id":("t",n["id"]),"updated_at":n["updated_at"],"content":n["content"],"note_name":n["note_name"]+"\0"+n["group_name"]+"\0"+n.get("tags","")+"\0"+sig},lambda x:note_targets(n,terms))
        rows.append(row)
    _sb_prune(_SB_META_CACHE,notes)
    live_text=live|{("t",i) for i in live}
    for k in [k for k in _SB_TEXT_CACHE if k not in live_text]:_SB_TEXT_CACHE.pop(k,None)
    return {"notes":rows,"groups":_dedupe_ci(meta["groups"]),"collapsed":[_nav_group_key(c) for c in meta["nav_collapsed_groups"]],"pinned":pinned,"recent":recent_note_ids(live),"targets":[t["name"] for t in terms],"prefs":sidebar_prefs(),"now":int(datetime.now(timezone.utc).timestamp()*1000)}
def _sb_snippet(text,pos,size,before=14,after=90):
    a=max(0,pos-before);b=min(len(text),pos+size+after)
    s=" ".join(text[a:b].split())
    return ("..." if a>0 else "")+s+("..." if b<len(text) else "")
def search_content(dbp,query,limit=300):
    """Notes whose text contains every word of the query (case-insensitive). Returns [{id, snippet}] with the snippet around the first word found."""
    words=[w for w in _norm(query).lower().split() if w][:8]
    if not words or max(len(w) for w in words)<2:return []
    try:cap=max(1,min(1000,int(limit)))
    except Exception:cap=300
    out=[]
    for n in _load_notes(dbp):
        text=_sb_text(n);low=text.lower()
        if not all(w in low for w in words):continue
        pos=min(low.find(w) for w in words)
        out.append({"id":n["id"],"snippet":_sb_snippet(text,pos,len(words[0]))})
        if len(out)>=cap:break
    return out
def group_rows_data(notes,group_meta,group_filter="*"):
    by_group={}
    for n in notes or []:
        grp=_norm(n.get("group_name",""))
        by_group.setdefault(grp,[]).append(n)
    for grp in list(by_group.keys()):
        by_group[grp]=sorted(by_group[grp],key=lambda n:_kci(n.get("note_name","")))
    rows=[]
    if by_group.get("") or group_filter=="":
        rows.append({"group_name":"","label":"Ungrouped","notes":by_group.get("",[]),"count":len(by_group.get("",[]))})
    groups=sorted(set(_dedupe_ci(group_meta))|{g for g in by_group if g},key=lambda s:s.lower())
    for grp in groups:
        rows.append({"group_name":grp,"label":grp,"notes":by_group.get(grp,[]),"count":len(by_group.get(grp,[]))})
    if group_filter not in ("*",None):
        rows=[r for r in rows if _kci(r.get("group_name",""))==_kci(group_filter)]
    return rows
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
# cmd:edit: is NG's anchor; the original app wrote cmdedit: (and Qt may wrap the image in a span).
_CMD_CARD_A_RX=re.compile(r'<a[^>]*href="cmd[a-z]*:[^"]*"[^>]*>\s*(?:<span[^>]*>\s*)?<img[^>]*src="cmdcard:([^"]+)"[^>]*/?>\s*(?:</span>\s*)?</a>',re.I)
_CMD_CARD_IMG_RX=re.compile(r'<img[^>]*src="cmdcard:([^"]+)"[^>]*/?>',re.I)
_NOTE_LINK_A_RX=re.compile(r'<a[^>]*href="notelink:([^"]+)"[^>]*>(.*?)</a>',re.I|re.S)
_NOTE_LINK_TOKEN_RX=re.compile(r'notelink:([A-Za-z0-9_-]+)')
_LEGACY_CMD_TABLE_RX=re.compile(r'<table\b[^>]*>(?:(?!</?table\b).)*?(?:cmdedit:|cmdcopy:|cmddelete:)([A-Za-z0-9_-]+)(?:(?!</?table\b).)*?</table>',re.I|re.S)
_LEGACY_C_BLOCK_RX=re.compile(r'(?:<|&lt;)C\s*\[(.*?)\]\s*(?:>|&gt;)(.*?)(?:<|&lt;)/C\s*(?:>|&gt;)',re.I|re.S)
_NOTE_IMAGES_SRC_RX=re.compile(r'(<img\b[^>]*?\bsrc=")([^"]*?[\\/]NoteImages[\\/]([^"\\/]+))(")',re.I)
_NOTE_REF_HTML_RX=re.compile(r"-Notename-([^\r\n<>-]+)-",re.I)
def _cmd_card_token_html(d):
    token=_encode_cmd_data(d)
    return f'<a href="cmd:edit:{token}"><img src="cmdcard:{token}" width="320" height="90" /></a>'
def _legacy_table_repl(m):
    block=m.group(0)
    if "cmdcard:" in block.lower():return block
    d=_decode_cmd_data(m.group(1))
    return _cmd_card_token_html(d) if _norm(d.get("command","")) else block
def upgrade_legacy_content(content,note_name=""):
    """Turn the original app's command formats into NG cards: <C [meta]>..</C> text blocks, the old command tables (cmdedit:/cmdcopy: anchors) and cmdedit: image anchors."""
    t=content or ""
    low=t.lower()
    if "<head" in low or "<!doctype" in low:
        # Qt's toHtml() wraps the note in a full document whose <style> would leak into the whole page once inserted.
        m=re.search(r"<body\b[^>]*>(.*)</body>",t,re.I|re.S)
        if m:t=m.group(1).strip("\r\n");low=t.lower()
    if "cmd" in low:t=_LEGACY_CMD_TABLE_RX.sub(_legacy_table_repl,t)
    if "c [" in low or "c[" in low:
        def crepl(m):
            body=_strip_html(re.sub(r"</(?:div|li|h[1-6])\s*>","\n",m.group(2) or "",flags=re.I)).rstrip()
            if not _norm(body):return m.group(0)
            d=_parse_cmd_meta(html.unescape(re.sub(r"<[^>]+>","",m.group(1) or "")))
            if not _norm(d.get("cmd_note_title","")):d["cmd_note_title"]=_norm(note_name)
            d["command"]=body
            return _cmd_card_token_html(d)
        t=_LEGACY_C_BLOCK_RX.sub(crepl,t)
    if "cmdedit:" in t or "cmdcopy:" in t:
        def arepl(m):
            d=_decode_cmd_data(m.group(1))
            return _cmd_card_token_html(d) if _norm(d.get("command","")) else m.group(0)
        t=_CMD_CARD_A_RX.sub(arepl,t)
    return t
def ensure_db_cards(content,db_cmds):
    """A note whose commands live only in the Commands table (no card in the content) gets them appended as cards, as the original did on load."""
    t=content or ""
    if "cmdcard:" in t or not db_cmds:return t
    return t+"".join(f"<p>{_cmd_card_token_html(c)}</p>" for c in db_cmds if isinstance(c,dict) and _norm(c.get("command","")))
def _note_images_dir():
    return _abs("Data","NoteImages")
def rewrite_legacy_image_paths(content):
    """Images pasted in the original app were saved as absolute paths under its Data/NoteImages; point them at this install's copy (or keep the old file if it still exists)."""
    t=content or ""
    if "noteimages" not in t.lower():return t
    def repl(m):
        fname=html.unescape(m.group(3))
        local=os.path.join(_note_images_dir(),fname)
        if os.path.isfile(local):return m.group(1)+html.escape(_file_url(local),quote=True)+m.group(4)
        src=html.unescape(m.group(2))
        p=re.sub(r"^file:/*","",src,flags=re.I) if src.lower().startswith("file:") else src
        if os.name!="nt" and src.lower().startswith("file:"):p="/"+p
        if os.path.isfile(p):return m.group(1)+html.escape(_file_url(p),quote=True)+m.group(4)
        return m.group(0)
    return _NOTE_IMAGES_SRC_RX.sub(repl,t)
def _note_lookup(notes):
    by_id={};by_name={}
    for n in notes or []:
        try:by_id[int(n.get("id"))]=n
        except Exception:continue
        k=_kci(n.get("note_name",""))
        if k and k not in by_name:by_name[k]=n
    return by_id,by_name
def _resolve_link(data,lookup):
    # Same order as note_refs.resolve_note_ref: the id if it still exists, otherwise the name.
    by_id,by_name=lookup
    nid=_note_refs.note_ref_id(data)
    if nid is not None and nid in by_id:return by_id[nid]
    nm=_kci(_note_refs.note_ref_name(data))
    return by_name.get(nm) if nm else None
def normalize_note_links(content,notes):
    t=content or ""
    if "notelink:" not in t:return t
    lookup=_note_lookup(notes)
    def repl(m):
        n=_resolve_link(_decode_note_link_data(m.group(1)),lookup)
        if not n:return m.group(0)
        return _NOTE_LINK_ANCHOR+_encode_note_link_data({"note_id":n["id"],"note_name":n.get("note_name","")})
    return _NOTE_LINK_TOKEN_RX.sub(repl,t)
def _cmd_card_align_class(d):
    align=_norm(d.get("align",""))
    return f" cmd-card-align-{align}" if align in ("left","center","right") else ""
def _cmd_type_slug(t):
    return re.sub(r"[^a-z0-9]+","-",(t or "").lower()).strip("-") or "other"
def _cmd_type_badge_html(d):
    t=_norm(d.get("command_type","")) or "other"
    return f'<span class="cmd-card-type cmd-card-type-{_cmd_type_slug(t)}">{html.escape(t)}</span>'
def _cmd_card_html(token):
    d=_decode_cmd_data(token)
    title=_norm(d.get("cmd_note_title","")) or "Command"
    meta=" / ".join([x for x in (_norm(d.get("category","")),_norm(d.get("sub_category",""))) if x])
    desc=_norm(d.get("description",""))
    cmd=(d.get("command","") or "").rstrip()
    tags=_split_tags(d.get("tags",""))
    meta_html=f'<span class="cmd-card-meta">{html.escape(meta)}</span>' if meta else ""
    desc_html=f'<div class="cmd-card-desc">{html.escape(desc)}</div>' if desc else ""
    tags_html="".join(f'<span class="cmd-card-tag">{html.escape(t)}</span>' for t in tags)
    tags_wrap=f'<div class="cmd-card-tags">{tags_html}</div>' if tags_html else ""
    align_class=_cmd_card_align_class(d)
    return f'<div class="cmd-card{align_class}"><div class="cmd-card-head"><span class="cmd-card-title">{html.escape(title)}</span>{_cmd_type_badge_html(d)}{meta_html}<span class="cmd-card-actions"><button type="button" class="cmd-card-copy" title="Copy command">Copy</button></span></div>{desc_html}<pre class="cmd-card-code">{html.escape(cmd)}</pre>{tags_wrap}</div>'
def _note_link_repl(m,lookup=None):
    data=_decode_note_link_data(m.group(1))
    if lookup is not None:
        n=_resolve_link(data,lookup)
        if not n:return f'<span class="note-link note-link-missing" title="Note not found: {html.escape(_note_refs.note_ref_name(data))}">{m.group(2)}</span>'
        nid=int(n["id"]);nm=html.escape(_norm(n.get("note_name","")))
    else:
        nid=data.get("note_id")
        if nid is None:return m.group(2)
        nm=html.escape(_norm(data.get("note_name","")))
    return f'<a href="#" class="note-link" data-note-id="{nid}" title="Open note: {nm}">{m.group(2)}</a>'
def _note_ref_text_repl(m,lookup):
    name=_norm(m.group(1))
    n=lookup[1].get(_kci(name)) if name else None
    if not n:return f'<span class="note-ref note-ref-missing" title="Note not found: {html.escape(name)}">{m.group(0)}</span>'
    return f'<a href="#" class="note-link note-ref" data-note-id="{int(n["id"])}" title="Open note: {html.escape(n.get("note_name",""))}">{m.group(0)}</a>'
def render_note_content(content,notes=None,note_name="",db_cmds=None):
    t=upgrade_legacy_content(content,note_name)
    if db_cmds:t=ensure_db_cards(t,db_cmds)
    t=rewrite_legacy_image_paths(t)
    t=_CMD_CARD_A_RX.sub(lambda m:_cmd_card_html(m.group(1)),t)
    t=_CMD_CARD_IMG_RX.sub(lambda m:_cmd_card_html(m.group(1)),t)
    lookup=_note_lookup(notes) if notes is not None else None
    t=_NOTE_LINK_A_RX.sub(lambda m:_note_link_repl(m,lookup),t)
    if lookup is not None and "-notename-" in t.lower():t=_NOTE_REF_HTML_RX.sub(lambda m:_note_ref_text_repl(m,lookup),t)
    return t
_CMD_CARD_MARKER_RX=re.compile(r'<span[^>]*class="cmd-card-marker"[^>]*data-cid="([^"]+)"[^>]*>\s*</span>',re.I)
def _cmd_card_embed_html(d):
    cid=_norm(d.get("cid","")) or _cmd_id(d)
    title=_norm(d.get("cmd_note_title","")) or "Command"
    meta=" / ".join([x for x in (_norm(d.get("category","")),_norm(d.get("sub_category",""))) if x])
    desc=_norm(d.get("description",""))
    cmd=(d.get("command","") or "").rstrip()
    tags=_split_tags(d.get("tags",""))
    meta_html=f'<span class="cmd-card-meta">{html.escape(meta)}</span>' if meta else ""
    desc_html=f'<div class="cmd-card-desc">{html.escape(desc)}</div>' if desc else ""
    tags_html="".join(f'<span class="cmd-card-tag">{html.escape(t)}</span>' for t in tags)
    tags_wrap=f'<div class="cmd-card-tags">{tags_html}</div>' if tags_html else ""
    align=_norm(d.get("align",""))
    align_class=_cmd_card_align_class(d)
    align_btns="".join(f'<button type="button" class="cmd-card-align-btn{" active" if align==a else ""}" data-align="{a}" title="Align {a}"><i class="icon icon-align-{a}"></i></button>' for a in ("left","center","right"))
    return f'<div class="cmd-card cmd-card-embed{align_class}" contenteditable="false" draggable="true" data-cid="{html.escape(cid)}"><div class="cmd-card-head"><span class="cmd-card-grip" title="Drag to move"><i class="icon icon-grip"></i></span><span class="cmd-card-title">{html.escape(title)}</span>{_cmd_type_badge_html(d)}{meta_html}<span class="cmd-card-actions">{align_btns}<button type="button" class="cmd-card-copy" title="Copy command">Copy</button><button type="button" class="cmd-card-menu" title="More options"><i class="icon icon-dots-vertical"></i></button></span></div>{desc_html}<pre class="cmd-card-code">{html.escape(cmd)}</pre>{tags_wrap}</div>'
def render_editor_content(content,note_name=""):
    t=rewrite_legacy_image_paths(upgrade_legacy_content(content,note_name))
    t=_CMD_CARD_A_RX.sub(lambda m:_cmd_card_embed_html(_decode_cmd_data(m.group(1))),t)
    t=_CMD_CARD_IMG_RX.sub(lambda m:_cmd_card_embed_html(_decode_cmd_data(m.group(1))),t)
    return t
def extract_editor_cmd_cards(content,note_name=""):
    t=upgrade_legacy_content(content,note_name)
    out=[]
    seen=set()
    for m in _CMD_CARD_IMG_RX.finditer(t):
        d=_decode_cmd_data(m.group(1))
        if not isinstance(d,dict):continue
        cid=_norm(d.get("cid","")) or _cmd_id(d)
        if not cid or cid in seen or not _norm(d.get("command","")):continue
        seen.add(cid)
        d["cid"]=cid
        out.append(d)
    return out
def finalize_editor_content(content_html,cmds):
    by_cid={}
    for c in cmds or []:
        if not isinstance(c,dict):continue
        cid=_norm(c.get("cid",""))or _cmd_id(c)
        by_cid[cid]=c
    def repl(m):
        d=by_cid.get(m.group(1))
        if not d:return ""
        return _cmd_card_token_html(d)
    return _CMD_CARD_MARKER_RX.sub(repl,content_html or "")
def note_html_is_empty(content):
    t=content or ""
    if "cmdcard:" in t or re.search(r"<(?:img|hr|figure|table)\b",t,re.I) or "data-attachment-id" in t:return False
    return not _norm(_strip_html(t))
def prepare_note_html(content,note_name="",dbp=None):
    """What a save stores: legacy commands upgraded and note links resolved to current ids."""
    t=upgrade_legacy_content(content,note_name)
    if "notelink:" in t:t=normalize_note_links(t,_load_notes(dbp or _db_path()))
    return t
def replace_saved_content(dbp,note_id,content):
    # Used after a new note's attachments are moved under its id: rewrite the row and its first history entry instead of saving twice.
    with _common_db.connection(dbp,timeout=5) as con:
        _ensure_schema(con)
        cur=con.cursor()
        cur.execute("UPDATE Notes SET content=? WHERE id=?",(content,int(note_id)))
        cur.execute("UPDATE NotesHistory SET content=? WHERE id=(SELECT MAX(id) FROM NotesHistory WHERE note_id=?)",(content,int(note_id)))
        con.commit()
def load_draft():
    d=_read_json(_draft_recovery_path())
    return d if isinstance(d,dict) and (_norm(d.get("name",""))or _norm(d.get("html",""))or d.get("cmd_cards")) else None
def save_draft(payload):
    if not isinstance(payload,dict):return False
    payload=dict(payload)
    payload["saved_at"]=datetime.now(timezone.utc).isoformat()
    return _write_json(_draft_recovery_path(),payload)
def clear_draft():
    try:
        p=_draft_recovery_path()
        if _doc_store.active(p):return _doc_store.remove(p)
        if os.path.isfile(p):os.remove(p)
        return True
    except Exception:
        return False
def _cmd_rows_key(rows):
    return [tuple(_norm(x) for x in r[:5])+((r[5] or "").rstrip(),) for r in rows]
def save_note(dbp,note_id,name,group_name,htmls,cmds=None,tags=""):
    """cmds=None (what every caller should pass) rebuilds the note's Commands rows from the cards in htmls, as the original did on every save."""
    now=datetime.now(timezone.utc).isoformat()
    tags=_norm(tags)
    if cmds is None:cmds=extract_editor_cmd_cards(htmls,name)
    with _common_db.connection(dbp,timeout=5) as con:
        _ensure_schema(con);_ensure_cmd_schema(con)
        cur=con.cursor()
        if note_id:
            cur.execute("SELECT id FROM Notes WHERE note_name=? AND id<>?",(name,int(note_id)))
            if cur.fetchone():raise ValueError(f'A note named "{name}" already exists.')
            cur.execute("SELECT note_name,group_name,tags,content FROM Notes WHERE id=?",(int(note_id),))
            old=cur.fetchone()
            # The note was deleted while it was open (another page, Mini, AI): save it as a new note instead of updating nothing and reporting success.
            if not old:note_id=None
        if note_id:
            if old and (old[0] or "")==name and _norm(old[1])==_norm(group_name) and _norm(old[2])==tags and (old[3] or "")==(htmls or ""):
                cur.execute("SELECT cmd_note_title,category,sub_category,description,tags,command FROM Commands WHERE note_id=? ORDER BY id",(int(note_id),))
                have=_cmd_rows_key(cur.fetchall())
                want=_cmd_rows_key([(c.get("cmd_note_title",""),c.get("category",""),c.get("sub_category",""),c.get("description",""),c.get("tags",""),c.get("command","")) for c in cmds])
                if have==want:return int(note_id),len(have),"unchanged"
                return int(note_id),_sync_commands(con,int(note_id),name,cmds,now),"update"
            cur.execute("UPDATE Notes SET note_name=?,group_name=?,tags=?,content=?,updated_at=? WHERE id=?",(name,group_name,tags,htmls,now,int(note_id)))
            nid=int(note_id)
            action="update"
        else:
            # A new note never replaces an existing one with the same name. A repeat of the identical save (double-clicked Save) returns that note unchanged.
            def same_name_note():
                cur.execute("SELECT id,group_name,tags,content FROM Notes WHERE note_name=?",(name,));ex=cur.fetchone()
                if not ex:return None
                if _norm(ex[1])==_norm(group_name) and _norm(ex[2])==tags and (ex[3] or "")==(htmls or ""):
                    cur.execute("SELECT COUNT(*) FROM Commands WHERE note_id=?",(int(ex[0]),));return int(ex[0]),int(cur.fetchone()[0]),"unchanged"
                raise ValueError(f'A note named "{name}" already exists.')
            dup=same_name_note()
            if dup:return dup
            try:cur.execute("INSERT INTO Notes(note_name,group_name,tags,content,created_at,updated_at) VALUES(?,?,?,?,?,?)",(name,group_name,tags,htmls,now,now))
            except _db_driver.IntegrityError:
                dup=same_name_note()
                if dup:return dup
                raise
            nid=int(cur.lastrowid)
            action="insert"
        _insert_note_history(cur,nid,name,group_name,htmls,action,now)
        if nid:_prune_note_history(cur,nid)
        ncmd=_sync_commands(con,nid,name,cmds,now) if nid else 0
    return nid,ncmd,action
_NOTE_HISTORY_KEEP=20
def _prune_note_history(cur,note_id,keep=_NOTE_HISTORY_KEEP):
    try:
        cur.execute("SELECT id FROM NotesHistory WHERE note_id=? AND action IN ('insert','update') ORDER BY action_at DESC,id DESC",(int(note_id),))
        rows=[r[0] for r in cur.fetchall()]
        if len(rows)>keep:
            cur.executemany("DELETE FROM NotesHistory WHERE id=?",[(i,) for i in rows[keep:]])
    except Exception:pass
def list_versions(note_id):
    dbp=_db_path()
    out=[]
    try:
        with _common_db.connection(dbp,timeout=5) as con:
            _ensure_schema(con)
            cur=con.cursor()
            cur.execute("SELECT id,content,action,action_at FROM NotesHistory WHERE note_id=? AND action IN ('insert','update') ORDER BY action_at DESC,id DESC",(int(note_id),))
            rows=cur.fetchall()
        for r in rows:
            out.append({"id":r[0],"action":r[2],"action_at":r[3] or "","action_label":_fmt_note_time(r[3] or ""),"preview":_strip_html(r[1] or "")[:160]})
    except Exception as e:
        _log("[!]",f"List versions failed ({e})")
    return out
def _history_row(note_id,version_id):
    dbp=_db_path()
    with _common_db.connection(dbp,timeout=5) as con:
        _ensure_schema(con)
        cur=con.cursor()
        cur.execute("SELECT content,action_at FROM NotesHistory WHERE id=? AND note_id=?",(int(version_id),int(note_id)))
        return cur.fetchone()
def diff_versions(note_id,version_id):
    row=_history_row(note_id,version_id)
    if not row:raise ValueError("Version not found.")
    dbp=_db_path()
    notes=_load_notes(dbp)
    note=next((n for n in notes if int(n["id"])==int(note_id)),None)
    if not note:raise ValueError("Note not found.")
    old_words=_strip_html(row[0] or "").split()
    new_words=_strip_html(note.get("content","") or "").split()
    sm=difflib.SequenceMatcher(None,old_words,new_words)
    segs=[]
    for op,i1,i2,j1,j2 in sm.get_opcodes():
        if op=="equal":segs.append({"type":"equal","text":" ".join(new_words[j1:j2])})
        elif op=="delete":segs.append({"type":"delete","text":" ".join(old_words[i1:i2])})
        elif op=="insert":segs.append({"type":"insert","text":" ".join(new_words[j1:j2])})
        elif op=="replace":
            segs.append({"type":"delete","text":" ".join(old_words[i1:i2])})
            segs.append({"type":"insert","text":" ".join(new_words[j1:j2])})
    return segs
def restore_version(note_id,version_id):
    row=_history_row(note_id,version_id)
    if not row:raise ValueError("Version not found.")
    content=row[0] or ""
    dbp=_db_path()
    notes=_load_notes(dbp)
    note=next((n for n in notes if int(n["id"])==int(note_id)),None)
    if not note:raise ValueError("Note not found.")
    content=prepare_note_html(content,note["note_name"],dbp)
    nid,ncmd,action=save_note(dbp,note_id,note["note_name"],note["group_name"],content,None,note.get("tags",""))
    return {"id":nid,"action":action}
def all_tags():
    dbp=_db_path()
    notes=_load_notes(dbp)
    counts={}
    for n in notes:
        for t in _split_tags(n.get("tags","")):
            k=t.lower()
            if k not in counts:counts[k]={"tag":t,"count":0}
            counts[k]["count"]+=1
    out=list(counts.values())
    out.sort(key=lambda x:x["tag"].lower())
    return out
_NOTE_EXPORT_FIELDS=["note_name","group_name","tags","content"]
_MD_FRONTMATTER_RX=re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?",re.S)
_MD_FENCE_RX=re.compile(r"```[a-zA-Z0-9_+-]*\r?\n(.*?)```",re.S)
def _parse_md_frontmatter(raw):
    m=_MD_FRONTMATTER_RX.match(raw or "")
    if not m:return {},raw or ""
    meta={};title="";tags=[]
    lines=m.group(1).split("\n")
    i=0
    while i<len(lines):
        ln=lines[i]
        mm=re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$",ln)
        if mm:
            key=mm.group(1).strip().lower();val=mm.group(2).strip()
            if key=="title" and val:title=val.strip("\"'")
            elif key=="tags":
                if val.startswith("["):
                    tags=[t.strip().strip("\"'") for t in val.strip("[]").split(",") if t.strip()]
                elif val:
                    tags=[t.strip().strip("\"'") for t in val.split(",") if t.strip()]
                else:
                    j=i+1
                    while j<len(lines) and re.match(r"^\s*-\s+",lines[j]):
                        tags.append(re.sub(r"^\s*-\s+","",lines[j]).strip().strip("\"'"))
                        j+=1
                    i=j-1
        i+=1
    meta["title"]=title;meta["tags"]=[t for t in tags if t]
    return meta,(raw or "")[m.end():]
def _markdown_to_html(text):
    text=(text or "").replace("\r\n","\n")
    fences=[]
    def stash_fence(m):
        fences.append(m.group(1))
        return f"\x00FENCE{len(fences)-1}\x00"
    text=_MD_FENCE_RX.sub(stash_fence,text)
    lines=text.split("\n")
    out=[];para=[];list_buf=[];list_tag=None
    def flush_para():
        if para:
            out.append("<p>"+_md_inline("\n".join(para))+"</p>")
            para.clear()
    def flush_list():
        nonlocal list_tag
        if list_buf:
            out.append(f"<{list_tag}>"+"".join(f"<li>{_md_inline(x)}</li>" for x in list_buf)+f"</{list_tag}>")
            list_buf.clear();list_tag=None
    for ln in lines:
        if not ln.strip():
            flush_para();flush_list();continue
        hm=re.match(r"^(#{1,6})\s+(.*)$",ln)
        if hm:
            flush_para();flush_list()
            lvl=len(hm.group(1))
            out.append(f"<h{lvl}>{_md_inline(hm.group(2))}</h{lvl}>")
            continue
        qm=re.match(r"^>\s?(.*)$",ln)
        if qm:
            flush_para();flush_list()
            out.append(f"<blockquote>{_md_inline(qm.group(1))}</blockquote>")
            continue
        um=re.match(r"^\s*[-*]\s+(.*)$",ln)
        om=re.match(r"^\s*\d+\.\s+(.*)$",ln)
        if um or om:
            flush_para()
            tag="ol" if om else "ul"
            if list_tag and list_tag!=tag:flush_list()
            list_tag=tag
            list_buf.append((um or om).group(1))
            continue
        flush_list()
        para.append(ln)
    flush_para();flush_list()
    html_out="\n".join(out)
    for i,fence in enumerate(fences):
        html_out=html_out.replace(f"\x00FENCE{i}\x00",f"<pre>{html.escape(fence)}</pre>")
    return html_out
def _md_inline(s):
    s=html.escape(s or "")
    s=re.sub(r"`([^`]+)`",r"<code>\1</code>",s)
    s=re.sub(r"\*\*([^*]+)\*\*|__([^_]+)__",lambda m:f"<b>{m.group(1) or m.group(2)}</b>",s)
    s=re.sub(r"\*([^*]+)\*|(?<![A-Za-z0-9_])_([^_]+)_(?![A-Za-z0-9_])",lambda m:f"<i>{m.group(1) or m.group(2)}</i>",s)
    s=re.sub(r"\[([^\]]+)\]\(([^)]+)\)",r'<a href="\2">\1</a>',s)
    return s
def legacy_cblocks_to_cards(content,note_name=""):
    # One converter for import and for the editor/viewer: upgrade_legacy_content (also handles the old command tables and cmdedit: anchors).
    return upgrade_legacy_content(content,note_name)
_NOTE_BUNDLE_TABLES=("Notes","CommandsNotes","Commands")
def _read_bundle_tables(dbp):
    out={t:[] for t in _NOTE_BUNDLE_TABLES}
    con=_common_db.connect(dbp,timeout=5)
    try:
        con.row_factory=_db_driver.Row;cur=con.cursor()
        for t in _NOTE_BUNDLE_TABLES:
            try:cur.execute(f"SELECT * FROM {t} ORDER BY id");out[t]=[dict(r) for r in cur.fetchall()]
            except Exception:out[t]=[]
    finally:con.close()
    return out
class NotesExport:
    def __init__(self):self.invalid=0;self.commands=[]
    def load(self):
        dbp=_db_path()
        notes=_load_notes(dbp)
        return [{"id":n["id"],"note_name":n["note_name"],"group_name":n["group_name"],"tags":n.get("tags",""),"content":n["content"]} for n in notes]
    def export_json(self,out_path,rows):
        data=[{k:r.get(k,"") for k in _NOTE_EXPORT_FIELDS} for r in (rows or [])]
        with open(out_path,"w",encoding="utf-8") as f:json.dump(data,f,ensure_ascii=False,indent=2)
    def export_csv(self,out_path,rows):
        with open(out_path,"w",encoding="utf-8",newline="") as f:
            w=csv.DictWriter(f,fieldnames=_NOTE_EXPORT_FIELDS);w.writeheader()
            for r in (rows or []):w.writerow({k:r.get(k,"") for k in _NOTE_EXPORT_FIELDS})
    def export_markdown_zip(self,out_path,rows):
        with zipfile.ZipFile(out_path,"w",zipfile.ZIP_DEFLATED) as zf:
            used=set()
            for r in (rows or []):
                name=_norm(r.get("note_name","")) or "untitled"
                safe=re.sub(r'[\\/:*?"<>|]',"_",name)[:80] or "untitled"
                fname=safe;n=1
                while fname in used:
                    n+=1;fname=f"{safe}_{n}"
                used.add(fname)
                group=_norm(r.get("group_name",""))
                header=f"# {name}\n\n"+(f"_Group: {group}_\n\n" if group else "")
                zf.writestr(f"{fname}.md",header+_strip_html(r.get("content","") or ""))
    def parse_markdown_folder(self,folder):
        out=[]
        if not folder or not os.path.isdir(folder):return out
        for root,_dirs,files in os.walk(folder):
            rel=os.path.relpath(root,folder)
            group="" if rel in (".","") else rel.replace(os.sep,"/")
            for fname in sorted(files):
                if not fname.lower().endswith((".md",".markdown")):continue
                fpath=os.path.join(root,fname)
                try:
                    with open(fpath,"r",encoding="utf-8") as f:raw=f.read()
                except Exception:continue
                meta,body=_parse_md_frontmatter(raw)
                title=_norm(meta.get("title","")) or os.path.splitext(fname)[0]
                tags=",".join(meta.get("tags") or [])
                content=_markdown_to_html(body)
                out.append({"note_name":title,"group_name":group,"tags":tags,"content":content})
        return out
    def parse_cherrytree(self,path):
        import xml.etree.ElementTree as ET
        out=[]
        try:
            tree=ET.parse(path)
        except Exception as e:
            raise ValueError(f"Not a valid CherryTree (.ctd) file: {e}")
        root=tree.getroot()
        def walk(node,group):
            name=_norm(node.get("name","")) or "Untitled"
            parts=[rt.text for rt in node.findall("rich_text") if rt.text]
            body="\n\n".join(parts).strip()
            content="".join(f"<p>{html.escape(p)}</p>" for p in body.split("\n\n") if p.strip())
            out.append({"note_name":name,"group_name":group,"tags":"","content":content})
            for child in node.findall("node"):
                walk(child,name)
        for top in root.findall("node"):
            walk(top,"")
        return out
    def note_row(self,r):
        if not isinstance(r,dict):return None
        g=lambda k,alt="":_norm("" if r.get(k,r.get(alt)) is None else str(r.get(k,r.get(alt))))
        name=g("note_name","title")
        if not name:return None
        return {"note_name":name,"group_name":g("group_name","group"),"tags":g("tags"),"content":legacy_cblocks_to_cards(str(r.get("content","") or ""))}
    def note_rows(self,items):
        out=[]
        for r in (items or []):
            x=self.note_row(r)
            if x is None:self.invalid+=1
            else:out.append(x)
        return out
    def from_tables(self,tables):
        from Cores.Services import commands_service as _cmd_svc
        lk={_norm(k).lower():v for k,v in (tables or {}).items() if isinstance(v,list)}
        if "notes" not in lk and "commandsnotes" not in lk:raise ValueError("No Notes or CommandsNotes table found.")
        out=self.note_rows(lk.get("notes") or [])
        ce=_cmd_svc.CommandsExport();self.commands=ce.rows(lk.get("commandsnotes") or []);self.invalid+=ce.invalid
        return out
    def from_data(self,d):
        if isinstance(d,dict):return self.from_tables(d)
        if not isinstance(d,list):raise ValueError("Unsupported JSON: expected a list of notes or an object of tables (Notes, CommandsNotes).")
        notes=[r for r in d if not (isinstance(r,dict) and "command" in r and "content" not in r)]
        cmds=[r for r in d if isinstance(r,dict) and "command" in r and "content" not in r]
        return self.from_tables({"Notes":notes,"CommandsNotes":cmds})
    def parse_json(self,path):
        with open(path,"r",encoding="utf-8-sig") as f:d=json.load(f)
        return self.from_data(d)
    def parse_csv(self,path):
        with open(path,"r",encoding="utf-8-sig",newline="") as f:return self.note_rows(list(csv.DictReader(f)))
    def parse_db(self,path):
        try:
            with open(path,"rb") as f:head=f.read(16)
        except Exception as e:raise ValueError(f"Cannot read file: {e}")
        if head!=b"SQLite format 3\x00":raise ValueError("Not a SQLite database file.")
        return self.from_tables(_read_bundle_tables(path))
    def parse_csv_zip(self,path):
        tables={}
        try:
            with zipfile.ZipFile(path,"r") as z:
                for n in z.namelist():
                    if not n.lower().endswith(".csv"):continue
                    txt=z.read(n).decode("utf-8-sig","ignore")
                    tables[os.path.splitext(os.path.basename(n))[0]]=list(csv.DictReader(io.StringIO(txt,newline="")))
        except zipfile.BadZipFile:raise ValueError("Not a valid ZIP file.")
        return self.from_tables(tables)
    def export_json_all(self,out_path):
        with open(out_path,"w",encoding="utf-8") as f:json.dump(_read_bundle_tables(_db_path()),f,ensure_ascii=False,indent=2)
    def export_csv_zip(self,out_path):
        tables=_read_bundle_tables(_db_path())
        with zipfile.ZipFile(out_path,"w",zipfile.ZIP_DEFLATED) as zf:
            for t,rows in tables.items():
                cols=[];[cols.append(k) for r in rows for k in r.keys() if k not in cols]
                buf=io.StringIO();w=csv.DictWriter(buf,fieldnames=cols or ["id"]);w.writeheader()
                for r in rows:w.writerow({k:("" if r.get(k) is None else r.get(k)) for k in cols})
                zf.writestr(f"{t}.csv",buf.getvalue())
    def export_db(self,out_path,pin=None):
        # A plain SQLite copy of every note and command: with encryption at rest on it needs the PIN typed now (and is audited).
        from Cores.Services import security_service as _sec
        ok,msg=_sec.plain_export_allowed(pin,"notes export (SQLite DB)")
        if not ok:raise ValueError(msg)
        if os.path.exists(out_path):os.remove(out_path)
        tables=_read_bundle_tables(_db_path())
        con=_common_db.connect(out_path)
        try:
            _ensure_schema(con);_ensure_cmd_schema(con)
            cur=con.cursor()
            for t,rows in tables.items():
                cols=set(_table_cols(cur,t))
                for r in rows:
                    ks=[k for k in r.keys() if k in cols]
                    if ks:cur.execute(f"INSERT INTO {t}({','.join(ks)}) VALUES({','.join('?'*len(ks))})",[r[k] for k in ks])
            con.commit()
        finally:con.close()
    def build_plan(self,incoming,base,cmd_base=None):
        base_by_key={}
        for r in (base or []):base_by_key.setdefault(_norm(r.get("note_name","")).lower(),r)
        new=[];dups=[];seen=set()
        for r in (incoming or []):
            k=_norm(r.get("note_name","")).lower()
            if not k or k in seen:self.invalid+=1;continue
            seen.add(k)
            if k in base_by_key:dups.append({"table":"Notes","key":r.get("note_name",""),"incoming":r,"existing":base_by_key[k]})
            else:new.append(r)
        plan={"new":new,"dups":dups,"new_commands":[],"invalid":self.invalid}
        if self.commands:
            from Cores.Services import commands_service as _cmd_svc
            ce=_cmd_svc.CommandsExport();cp=ce.build_plan(self.commands,ce.load() if cmd_base is None else cmd_base)
            plan["new_commands"]=cp["new"];plan["dups"]+=cp["dups"];plan["invalid"]+=cp["invalid"]
        return plan
    def apply_plan(self,plan,decisions):
        dbp=_db_path();decisions=decisions or {}
        res={"added":0,"replaced":0,"overwritten":0,"skipped":0,"bad":0,"invalid":int((plan or {}).get("invalid",0) or 0)}
        def do_save(note_id,r):
            content=r.get("content","") or ""
            save_note(dbp,note_id,r["note_name"],r.get("group_name",""),content,extract_editor_cmd_cards(content),r.get("tags",""))
        for r in ((plan or {}).get("new") or []):
            try:do_save(None,r);res["added"]+=1
            except Exception as e:res["bad"]+=1;_log("[!]",f"Notes import row failed ({e})")
        cmd_dups=[];cmd_dec={}
        for idx,d in enumerate((plan or {}).get("dups") or []):
            act=decisions.get(idx,"Skip")
            if d.get("table")=="CommandsNotes":cmd_dec[len(cmd_dups)]=act;cmd_dups.append(d);continue
            if act not in ("Replace","Overwrite"):res["skipped"]+=1;continue
            incoming=d.get("incoming") or {};existing=d.get("existing") or {}
            try:
                if act=="Replace":do_save(existing.get("id"),dict(incoming,note_name=existing.get("note_name") or incoming["note_name"]));res["replaced"]+=1
                else:
                    if not _delete_note(dbp,existing.get("note_name","")):raise ValueError("Could not remove the existing note.")
                    do_save(None,incoming);res["overwritten"]+=1
            except Exception as e:res["bad"]+=1;_log("[!]",f"Notes import row failed ({e})")
        if (plan or {}).get("new_commands") or cmd_dups:
            from Cores.Services import commands_service as _cmd_svc
            r2=_cmd_svc.CommandsExport().apply_plan({"new":plan.get("new_commands") or [],"dups":cmd_dups,"invalid":0},cmd_dec)
            for k in ("added","replaced","overwritten","skipped","bad"):res[k]+=r2.get(k,0)
        return res
