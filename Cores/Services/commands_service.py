import os,logging,re,html,hashlib,json,base64,csv
from datetime import datetime,timezone
from logging.handlers import RotatingFileHandler
from Cores import common_db as _common_db
from Cores import recycle_bin as _recycle_bin
def _abs(*p):return os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","..",*p)
def _log_setup():
    d=_abs("Logs");os.makedirs(d,exist_ok=True)
    lg=logging.getLogger("CommandsNotes");lg.setLevel(logging.INFO)
    fp=os.path.abspath(os.path.join(d,"CommandsNotes_log.log"))
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
DB_SCHEMA_VERSION=_common_db.DB_SCHEMA_VERSION
def _table_cols(cur,t):
    return _common_db.table_cols(cur,t)
def _ensure_schema(con):
    _common_db.ensure_schema(con)
def _apply_migrations(con):
    _common_db.apply_migrations(con)
def _norm(s):return (str(s) if s is not None else "").strip()
def _ell(s,n):
    s=_norm(s)
    if not s:return ""
    return (s[:max(0,n-3)]+"...") if len(s)>n else s
def _clean_cmd(s):
    raw=html.unescape(str(s or ""))
    low=raw.lower()
    if not ("<span" in low or "<pre" in low or "<p" in low or "<div" in low or "<br" in low or "style=" in low or "-qt-" in low):
        # Plain commands keep their indentation and tabs (heredocs, scripts); only legacy rich-text HTML is flattened below.
        return raw.replace("\r\n","\n").replace("\r","\n").replace("\xa0"," ").strip()
    raw=re.sub(r"<[^>]+>"," ",raw)
    raw=raw.replace("\xa0"," ")
    raw=re.sub(r"[ \t\r\f\v]+"," ",raw)
    raw=re.sub(r"\n\s+","\n",raw)
    raw=re.sub(r"\s+\n","\n",raw)
    return raw.strip()
def _cmd_norm_data(d):
    d=d or {}
    title=d.get("cmd_note_title","") if "cmd_note_title" in d else (d.get("title","") or d.get("note_name",""))
    return {"cmd_note_title":_norm(title),"category":_norm(d.get("category","")),"sub_category":_norm(d.get("sub_category","") or d.get("sub","")),"description":_norm(d.get("description","")),"tags":_norm(d.get("tags","")),"command":(d.get("command","") or "").rstrip()}
def _cmd_id(d):
    x=_cmd_norm_data(d);raw="|".join([x.get("cmd_note_title",""),x.get("category",""),x.get("sub_category",""),x.get("description",""),x.get("tags",""),_norm(x.get("command",""))])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12] if raw else ""
def _encode_cmd_data(d):
    x=_cmd_norm_data(d);x["cid"]=_cmd_id(x)
    raw=json.dumps(x,ensure_ascii=False)
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")
def _insert_cmdn_history(cur,cmd_id,note_name,category,subcat,cmd,tags,desc,action,action_at):
    try:
        cur.execute("INSERT INTO CommandsNotesHistory(cmd_id,note_name,category,sub_category,command,tags,description,action,action_at) VALUES(?,?,?,?,?,?,?,?,?)",(cmd_id,note_name,category,subcat,cmd,tags,desc,action,action_at))
    except Exception:pass
def _insert_cmd_history(cur,cmd_id,note_id,note_name,cmd_note_title,category,subcat,desc,tags,cmd,action,action_at):
    try:
        cur.execute("INSERT INTO CommandsHistory(cmd_id,note_id,note_name,cmd_note_title,category,sub_category,description,tags,command,action,action_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(cmd_id,note_id,note_name,cmd_note_title,category,subcat,desc,tags,cmd,action,action_at))
    except Exception:pass
def _parse_cmd_meta(meta):
    d={"cmd_note_title":"","category":"","sub_category":"","description":"","tags":""}
    for p in [x.strip() for x in (meta or "").split(",") if x.strip()]:
        if ":" not in p:continue
        k,v=p.split(":",1)
        k=(k or "").strip().lower();v=(v or "").strip()
        if "command note tittle" in k or "note title" in k:d["cmd_note_title"]=v
        elif k=="category":d["category"]=v
        elif "sub category" in k or "subcategory" in k:d["sub_category"]=v
        elif k=="description":d["description"]=v
        elif k=="tags":d["tags"]=v
    return d
def _parse_cmd_blocks(text):
    t=text or ""
    out=[]
    for m in re.finditer(r"<C\s*\[(.*?)\]\s*>\s*(.*?)\s*</C>",t,re.S|re.I):
        meta=(m.group(1) or "").strip()
        body=_clean_cmd(m.group(2) or "")
        d={"cmd_note_title":"","category":"","sub_category":"","description":"","tags":"","command":body}
        d.update(_parse_cmd_meta(meta))
        if _norm(d.get("command")):out.append(d)
    return out
def _sync_missing_note_cmds(dbp):
    if not dbp or not os.path.isfile(dbp):return 0
    try:
        con=_common_db.connect(dbp,timeout=5);_ensure_schema(con)
        cur=con.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Notes'")
        if not cur.fetchone():
            con.close();return 0
        cur.execute("SELECT id,note_name,content FROM Notes WHERE (content LIKE '%<C %' OR content LIKE '%&lt;C %') AND NOT EXISTS (SELECT 1 FROM Commands WHERE Commands.note_id=Notes.id)")
        rows=cur.fetchall()
        if not rows:
            con.close();return 0
        now=datetime.now(timezone.utc).isoformat()
        total=0
        for nid,name,content in rows:
            raw=html.unescape(content or "")
            cmds=_parse_cmd_blocks(raw)
            if not cmds:continue
            try:cur.execute("DELETE FROM Commands WHERE note_id=?",(int(nid),))
            except Exception:continue
            for c in cmds:
                try:
                    cur.execute("INSERT INTO Commands(note_id,note_name,cmd_note_title,category,sub_category,description,tags,command,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(int(nid),_norm(name),_norm(c.get("cmd_note_title","")),_norm(c.get("category","")),_norm(c.get("sub_category","")),_norm(c.get("description","")),_norm(c.get("tags","")),(c.get("command","") or "").rstrip(),now,now))
                    total+=1
                except Exception:
                    pass
        con.commit();con.close()
        _log("[+]",f"Synced commands from notes: {total}")
        return total
    except Exception as e:
        _log("[!]",f"Sync commands failed ({e})")
        try:con.close()
        except Exception:pass
        return 0
def _load_cmds():
    p=_db_path()
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
                grp=_norm(r[2]) if "group_name" in notes_cols and len(r)>2 else ""
                try:note_groups_by_id[int(r[0])]=grp
                except Exception:pass
                nn=_norm(r[1])
                if nn:note_groups_by_name[nn.lower()]=grp
        cn=set(_table_cols(cur,"CommandsNotes"))
        if {"note_name","category","sub_category","command","tags"}.issubset(cn):
            has_desc="description" in cn
            has_type="command_type" in cn
            has_noise="noise_level" in cn
            sel="id,note_name,category,sub_category,command,tags"+(",description" if has_desc else "")+(",command_type" if has_type else "")+(",noise_level" if has_noise else "")
            cur.execute(f"SELECT {sel} FROM CommandsNotes ORDER BY id DESC")
            for r in cur.fetchall():
                i=6
                rid=r[0];nn=r[1];c=r[2];sc=r[3];cmd=r[4];tags=r[5]
                desc=(r[i] if has_desc else "");i+=1 if has_desc else 0
                ctype=(r[i] if has_type else "");i+=1 if has_type else 0
                noise=(r[i] if has_noise else "")
                out.append({"id":int(rid),"src":"CommandsNotes","locked":False,"note_id":None,"note_name":_norm(nn) or "Unlinked","cmd_note_title":_norm(nn) or "Unlinked","group_name":"","title":_norm(nn) or "Unlinked","category":_norm(c) or "Uncategorized","sub":_norm(sc) or "General","command":_clean_cmd(cmd),"tags":_norm(tags),"description":_norm(desc),"command_type":_norm(ctype) or "other","noise_level":_norm(noise) or "normal","db":p})
        cc=set(_table_cols(cur,"Commands"))
        if {"note_name","category","sub_category","command","tags"}.issubset(cc):
            has_desc="description" in cc
            has_title="cmd_note_title" in cc
            has_note_id="note_id" in cc
            has_type="command_type" in cc
            has_noise="noise_level" in cc
            sel="id"+(",note_id" if has_note_id else "")+",note_name,category,sub_category,command,tags"+(",description" if has_desc else "")+(",cmd_note_title" if has_title else "")+(",command_type" if has_type else "")+(",noise_level" if has_noise else "")
            cur.execute(f"SELECT {sel} FROM Commands ORDER BY id DESC")
            for r in cur.fetchall():
                i=0
                rid=r[i];i+=1
                note_id=(r[i] if has_note_id else None);i+=1 if has_note_id else 0
                nn=r[i];i+=1
                c=r[i];i+=1
                sc=r[i];i+=1
                cmd=r[i];i+=1
                tags=r[i];i+=1
                desc=(r[i] if has_desc else "");i+=1 if has_desc else 0
                ttl=(r[i] if has_title else "");i+=1 if has_title else 0
                ctype=(r[i] if has_type else "");i+=1 if has_type else 0
                noise=(r[i] if has_noise else "")
                nn=_norm(nn) or "Unlinked"
                raw_ttl=_norm(ttl);ttl=raw_ttl or nn
                nid=(int(note_id) if str(note_id).isdigit() else None)
                grp=note_groups_by_id.get(nid,"") if nid is not None else note_groups_by_name.get(nn.lower(),"")
                out.append({"id":int(rid),"src":"Commands","locked":False,"note_id":nid,"note_name":nn,"cmd_note_title":raw_ttl,"group_name":grp,"title":ttl,"category":_norm(c) or "Uncategorized","sub":_norm(sc) or "General","command":_clean_cmd(cmd),"tags":_norm(tags),"description":_norm(desc),"command_type":_norm(ctype) or "other","noise_level":_norm(noise) or "normal","db":p})
        con.close()
        _log("[+]",f"Loaded commands: {len(out)} from {os.path.basename(p)}")
        return p,out
    except Exception as e:
        _log("[!]",f"DB load error ({e})")
        try:con.close()
        except Exception:pass
        return p,[]
def _delete_cmd(item):
    if not isinstance(item,dict):return False
    dbp=item.get("db");nid=item.get("id");src=item.get("src")
    if not dbp or nid is None:return False
    if src!="CommandsNotes":return False
    try:
        with _common_db.connection(dbp,timeout=5) as con:
            _ensure_schema(con)
            cur=con.cursor()
            cols=set(_table_cols(cur,"CommandsNotes"))
            key_col="id" if "id" in cols else "rowid"
            now=datetime.now(timezone.utc).isoformat()
            try:
                cur.execute(f"SELECT {key_col},note_name,category,sub_category,command,tags,description,created_at,updated_at,command_type,noise_level FROM CommandsNotes WHERE {key_col}=?",(int(nid),))
                r=cur.fetchone()
                if r:
                    _insert_cmdn_history(cur,r[0],r[1],r[2],r[3],r[4],r[5],r[6],"delete",now)
                    _recycle_bin.put_entry_cur(cur,_recycle_bin.TYPE_COMMAND,_norm(r[1]) or "Unlinked",{"command":{"id":r[0],"note_name":r[1],"category":r[2],"sub_category":r[3],"command":r[4],"tags":r[5],"description":r[6],"created_at":r[7] or "","updated_at":r[8] or "","command_type":r[9] or "other","noise_level":r[10] or "normal"}},source="CommandsNotes",entity_key=str(r[0]),deleted_at=now,expires_at=_recycle_bin.expires_text())
            except Exception:pass
            cur.execute(f"DELETE FROM CommandsNotes WHERE {key_col}=?",(int(nid),))
            con.commit()
            return bool(cur.rowcount)
    except Exception as e:
        _log("[!]",f"Delete error ({e})")
        return False
def _linked_command_rows(dbp,item):
    if not isinstance(item,dict):return []
    target=_cmd_id(item);out=[]
    try:
        with _common_db.connection(dbp,timeout=5) as con:
            _ensure_schema(con);cur=con.cursor();cols=set(_table_cols(cur,"Commands"))
            if not {"id","note_name","category","sub_category","command","tags"}.issubset(cols):return []
            has_desc="description" in cols;has_title="cmd_note_title" in cols;has_note_id="note_id" in cols
            sel="id"+(",note_id" if has_note_id else "")+",note_name,category,sub_category,command,tags"+(",description" if has_desc else "")+(",cmd_note_title" if has_title else "")
            cur.execute(f"SELECT {sel} FROM Commands")
            for r in cur.fetchall():
                i=0;rid=r[i];i+=1;nid=(r[i] if has_note_id else None);i+=1 if has_note_id else 0;nn=r[i];i+=1;cat=r[i];i+=1;sub=r[i];i+=1;cmd=r[i];i+=1;tags=r[i];i+=1;desc=(r[i] if has_desc else "");i+=1 if has_desc else 0;ttl=(r[i] if has_title else "")
                raw_ttl=_norm(ttl)
                row={"id":int(rid),"note_id":int(nid) if str(nid).isdigit() else None,"note_name":_norm(nn),"cmd_note_title":raw_ttl,"title":raw_ttl or _norm(nn),"category":_norm(cat),"sub":_norm(sub),"sub_category":_norm(sub),"description":_norm(desc),"tags":_norm(tags),"command":_clean_cmd(cmd)}
                if _cmd_id(row)==target:out.append(row)
    except Exception as e:_log("[!]",f"Linked command lookup failed ({e})")
    if not out and item.get("id") is not None:out=[item]
    return out
def _linked_note_count(dbp,item):
    rows=_linked_command_rows(dbp,item);seen=set()
    for r in rows:
        key=r.get("note_id") if r.get("note_id") is not None else _norm(r.get("note_name","")).lower()
        if key not in ("",None):seen.add(key)
    return len(seen) or (1 if item.get("src")=="Commands" else 0)
def related_notes(dbp,item):
    if not isinstance(item,dict) or item.get("src")!="Commands":return []
    rows=_linked_command_rows(dbp,item)
    ids=[];names=[]
    for r in rows:
        if r.get("note_id") is not None:ids.append(int(r.get("note_id")))
        elif _norm(r.get("note_name","")):names.append(_norm(r.get("note_name","")))
    notes=[]
    try:
        with _common_db.connection(dbp,timeout=5) as con:
            _ensure_schema(con);cur=con.cursor();cols=set(_table_cols(cur,"Notes"))
            if {"id","note_name"}.issubset(cols):
                sel="id,note_name"+(",group_name" if "group_name" in cols else "")
                if ids:
                    q=",".join("?" for _ in sorted(set(ids)));cur.execute(f"SELECT {sel} FROM Notes WHERE id IN ({q})",sorted(set(ids)))
                    for r in cur.fetchall():
                        grp=_norm(r[2]) if "group_name" in cols and len(r)>2 else "";notes.append({"note_id":int(r[0]),"note_name":_norm(r[1]),"group_name":grp})
                if names:
                    q=",".join("?" for _ in sorted(set(names)));cur.execute(f"SELECT {sel} FROM Notes WHERE note_name IN ({q})",sorted(set(names)))
                    for r in cur.fetchall():
                        grp=_norm(r[2]) if "group_name" in cols and len(r)>2 else "";notes.append({"note_id":int(r[0]),"note_name":_norm(r[1]),"group_name":grp})
    except Exception:pass
    for r in rows:
        if any((n.get("note_id") is not None and n.get("note_id")==r.get("note_id")) or (_norm(n.get("note_name","")).lower()==_norm(r.get("note_name","")).lower()) for n in notes):continue
        if r.get("note_id") is not None or _norm(r.get("note_name","")):notes.append({"note_id":r.get("note_id"),"note_name":_norm(r.get("note_name","")),"group_name":""})
    uniq=[];seen=set()
    for n in notes:
        key=n.get("note_id") if n.get("note_id") is not None else _norm(n.get("note_name","")).lower()
        if key in ("",None) or key in seen:continue
        seen.add(key);uniq.append(n)
    return uniq
_CARD_TOKEN_RX=re.compile(r"((?:cmdcard|cmd:edit|cmdedit|cmddelete|cmdcopy):)([A-Za-z0-9_-]+)",re.I)
def _decode_card_token(tok):
    try:
        d=json.loads(base64.urlsafe_b64decode(tok+"="*((4-len(tok)%4)%4)).decode("utf-8"))
        return d if isinstance(d,dict) else None
    except Exception:return None
def _rewrite_card_tokens(htmls,old_item,new_item):
    """Re-encode every command card in a note that holds old_item. Cards written by the note editor carry cid/align/command_type and a
    different key order, so they never match an exact token string; match on the command's identity instead and keep cid/align."""
    target=_cmd_id(old_item);new_data=_cmd_norm_data(new_item);cache={}
    if not target:return htmls
    def repl(m):
        tok=m.group(2)
        if tok not in cache:
            cache[tok]=tok;d=_decode_card_token(tok)
            if d is not None and _cmd_id(d)==target:
                nd=dict(d);nd.update(new_data)
                if _norm(new_item.get("command_type","")):nd["command_type"]=_norm(new_item.get("command_type",""))
                if not _norm(nd.get("cid","")):nd["cid"]=_cmd_id(nd)
                cache[tok]=base64.urlsafe_b64encode(json.dumps(nd,ensure_ascii=False).encode("utf-8")).decode("ascii").rstrip("=")
        return m.group(1)+cache[tok]
    return _CARD_TOKEN_RX.sub(repl,htmls or "")
def _update_linked_command(dbp,old_item,new_item):
    if not dbp or not isinstance(old_item,dict) or not isinstance(new_item,dict):return False
    rows=_linked_command_rows(dbp,old_item);old_token=_encode_cmd_data(old_item);new_data=_cmd_norm_data(new_item);new_token=_encode_cmd_data(new_data);now=datetime.now(timezone.utc).isoformat()
    try:
        with _common_db.connection(dbp,timeout=5) as con:
            _ensure_schema(con);cur=con.cursor();cmd_cols=set(_table_cols(cur,"Commands"));note_cols=set(_table_cols(cur,"Notes"))
            ids=[int(r.get("id")) for r in rows if str(r.get("id")).isdigit()]
            if ids:
                q=",".join("?" for _ in ids)
                cur.execute(f"SELECT id,note_id,note_name,cmd_note_title,category,sub_category,description,tags,command FROM Commands WHERE id IN ({q})",ids)
                for r in cur.fetchall():_insert_cmd_history(cur,r[0],r[1],r[2],r[3],r[4],r[5],r[6],r[7],r[8],"update",now)
                new_type=_norm_command_type(new_item.get("command_type",""))
                new_noise=_norm_noise_level(new_item.get("noise_level",""))
                cur.execute(f"UPDATE Commands SET cmd_note_title=?,category=?,sub_category=?,description=?,tags=?,command=?,command_type=?,noise_level=?,updated_at=? WHERE id IN ({q})",(new_data["cmd_note_title"],new_data["category"],new_data["sub_category"],new_data["description"],new_data["tags"],new_data["command"],new_type,new_noise,now,*ids))
            note_ids=[];note_names=[]
            for r in rows:
                if r.get("note_id") is not None:note_ids.append(int(r.get("note_id")))
                elif _norm(r.get("note_name","")):note_names.append(_norm(r.get("note_name","")))
            notes=[]
            if "content" in note_cols:
                if note_ids:
                    q=",".join("?" for _ in sorted(set(note_ids)));cur.execute(f"SELECT id,note_name,content FROM Notes WHERE id IN ({q})",sorted(set(note_ids)));notes+=cur.fetchall()
                if note_names:
                    q=",".join("?" for _ in sorted(set(note_names)));cur.execute(f"SELECT id,note_name,content FROM Notes WHERE note_name IN ({q})",sorted(set(note_names)));notes+=cur.fetchall()
            seen=set()
            for nid,nn,content in notes:
                if nid in seen:continue
                seen.add(nid);htmls=content or "";new_html=_rewrite_card_tokens(htmls.replace(old_token,new_token),old_item,new_item)
                if new_html!=htmls:cur.execute("UPDATE Notes SET content=?,updated_at=? WHERE id=?",(new_html,now,int(nid)))
            con.commit()
            return True
    except Exception as e:
        _log("[!]",f"Linked command update failed ({e})")
        return False
def _norm_tag(t):return " ".join((t or "").strip().split())
def _split_tags(s):
    if not s:return []
    raw=str(s).replace(";",",").split(",")
    out=[];seen=set()
    for p in raw:
        t=_norm_tag(p)
        if not t:continue
        k=t.lower()
        if k in seen:continue
        seen.add(k);out.append(t)
    return out
def _norm_command_type(t):
    return _norm(t) or "other"
_NOISE_LEVELS={"stealthy","normal","noisy","destructive"}
def _norm_noise_level(t):
    v=_norm(t).lower()
    return v if v in _NOISE_LEVELS else "normal"
def _insert_cmd(dbp,note_name,category,subcat,cmd,tags,desc,command_type="other",noise_level="normal"):
    with _common_db.connection(dbp,timeout=5) as con:
        _ensure_schema(con)
        now=datetime.now(timezone.utc).isoformat()
        cur=con.cursor()
        cur.execute("INSERT INTO CommandsNotes(note_name,category,sub_category,command,tags,description,command_type,noise_level,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(note_name,category,subcat,cmd,tags,desc,_norm_command_type(command_type),_norm_noise_level(noise_level),now,now))
        try:cid=int(cur.lastrowid)
        except Exception:cid=None
        _insert_cmdn_history(cur,cid,note_name,category,subcat,cmd,tags,desc,"insert",now)
        con.commit()
        try:return int(cur.lastrowid)
        except Exception:return None
def _update_cmd(dbp,nid,note_name,category,subcat,cmd,tags,desc,command_type="other",noise_level="normal"):
    if nid is None:return False
    with _common_db.connection(dbp,timeout=5) as con:
        _ensure_schema(con)
        now=datetime.now(timezone.utc).isoformat()
        cur=con.cursor()
        cols=_table_cols(cur,"CommandsNotes")
        key_col="id" if "id" in cols else "rowid"
        cur.execute(f"UPDATE CommandsNotes SET note_name=?,category=?,sub_category=?,command=?,tags=?,description=?,command_type=?,noise_level=?,updated_at=? WHERE {key_col}=?",(note_name,category,subcat,cmd,tags,desc,_norm_command_type(command_type),_norm_noise_level(noise_level),now,int(nid)))
        if cur.rowcount:
            try:
                cur.execute(f"SELECT note_name,category,sub_category,command,tags,description FROM CommandsNotes WHERE {key_col}=?",(int(nid),))
                r=cur.fetchone()
                if r:_insert_cmdn_history(cur,int(nid),r[0],r[1],r[2],r[3],r[4],r[5],"update",now)
            except Exception:pass
        con.commit()
        return bool(cur.rowcount)
def _history_from_db(dbp):
    out={"notes":[],"categories":[],"subcategories":[],"tags":[],"suggest_tags":[],"last_note":"","last_category":"","last_subcategory":""}
    if not dbp or not os.path.isfile(dbp):return out
    try:
        with _common_db.connection(dbp,timeout=5) as con:
            _ensure_schema(con)
            cur=con.cursor()
            cur.execute("SELECT note_name,category,sub_category FROM CommandsNotes ORDER BY id DESC LIMIT 1")
            r=cur.fetchone()
            if r:
                out["last_note"]=_norm_tag(r[0])
                out["last_category"]=_norm_tag(r[1])
                out["last_subcategory"]=_norm_tag(r[2])
            cur.execute("SELECT DISTINCT note_name FROM CommandsNotes WHERE note_name IS NOT NULL AND TRIM(note_name)<>''")
            seen=set();notes=[]
            for (n,) in cur.fetchall():
                t=_norm_tag(n)
                if not t:continue
                k=t.lower()
                if k in seen:continue
                seen.add(k);notes.append(t)
            out["notes"]=notes
            cur.execute("SELECT DISTINCT category FROM CommandsNotes WHERE category IS NOT NULL AND TRIM(category)<>''")
            seen=set();cats=[]
            for (c,) in cur.fetchall():
                t=_norm_tag(c)
                if not t:continue
                k=t.lower()
                if k in seen:continue
                seen.add(k);cats.append(t)
            out["categories"]=cats
            cur.execute("SELECT DISTINCT sub_category FROM CommandsNotes WHERE sub_category IS NOT NULL AND TRIM(sub_category)<>''")
            seen=set();subs=[]
            for (s,) in cur.fetchall():
                t=_norm_tag(s)
                if not t:continue
                k=t.lower()
                if k in seen:continue
                seen.add(k);subs.append(t)
            out["subcategories"]=subs
            cur.execute("SELECT tags FROM CommandsNotes WHERE tags IS NOT NULL AND TRIM(tags)<>'' ORDER BY id ASC")
            all_tags=[];seen=set()
            for (t,) in cur.fetchall():
                for x in _split_tags(t):
                    k=x.lower()
                    if k in seen:continue
                    seen.add(k);all_tags.append(x)
            out["tags"]=all_tags
            cur.execute("SELECT tags FROM CommandsNotes WHERE tags IS NOT NULL AND TRIM(tags)<>'' ORDER BY id DESC LIMIT 200")
            sug=[];seen=set()
            for (t,) in cur.fetchall():
                for x in _split_tags(t):
                    k=x.lower()
                    if k in seen:continue
                    seen.add(k);sug.append(x)
                    if len(sug)>=5:break
                if len(sug)>=5:break
            out["suggest_tags"]=sug
    except Exception:pass
    return out
def log_command_run(command_id,src,text,target_snapshot):
    dbp=_db_path()
    now=datetime.now(timezone.utc).isoformat()
    snap_json=json.dumps(target_snapshot,ensure_ascii=False) if target_snapshot else ""
    try:
        with _common_db.connection(dbp,timeout=5) as con:
            _ensure_schema(con)
            cur=con.cursor()
            cid=int(command_id) if command_id is not None and str(command_id).lstrip("-").isdigit() else None
            cur.execute("INSERT INTO CommandRuns(command_id,src,text,target_snapshot,ran_at) VALUES(?,?,?,?,?)",(cid,_norm(src),text or "",snap_json,now))
            con.commit()
        return True
    except Exception as e:
        _log("[!]",f"Log command run failed ({e})")
        return False
def list_command_runs(command_id,src,limit=20):
    dbp=_db_path()
    out=[]
    if command_id is None:return out
    try:
        with _common_db.connection(dbp,timeout=5) as con:
            _ensure_schema(con)
            cur=con.cursor()
            cur.execute("SELECT text,target_snapshot,ran_at FROM CommandRuns WHERE command_id=? AND src=? ORDER BY ran_at DESC LIMIT ?",(int(command_id),_norm(src),int(limit)))
            rows=cur.fetchall()
        for r in rows:
            try:snap=json.loads(r[1]) if r[1] else {}
            except Exception:snap={}
            out.append({"text":r[0] or "","target_snapshot":snap,"ran_at":r[2] or ""})
    except Exception as e:
        _log("[!]",f"List command runs failed ({e})")
    return out
def validate_command_fields(note_name,category,sub_category,command):
    if not _norm_tag(note_name):return False,"Command Note Title is required."
    if not _norm_tag(category):return False,"Category is required."
    if not _norm_tag(sub_category):return False,"Sub Category is required."
    if not _norm_tag(command):return False,"Command is required."
    return True,""
def normalize_command_fields(title,category,sub_category,tags):
    return _norm_tag(title),_norm_tag(category),_norm_tag(sub_category),",".join(_split_tags(tags))
def commands_stamp(dbp=None):
    dbp=dbp or _db_path()
    if not dbp or not os.path.isfile(dbp):return ""
    parts=[]
    try:
        con=_common_db.connect(dbp,timeout=5)
        try:
            cur=con.cursor()
            for t in ("CommandsNotes","Commands"):
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",(t,))
                if not cur.fetchone():parts.append("-");continue
                cols=set(_table_cols(cur,t))
                upd="MAX(updated_at)" if "updated_at" in cols else "''"
                cur.execute(f"SELECT COUNT(*),MAX(id),{upd} FROM {t}")
                r=cur.fetchone() or (0,0,"")
                parts.append(f"{r[0]}:{r[1] or 0}:{r[2] or ''}")
        finally:con.close()
    except Exception as e:
        _log("[!]",f"Commands stamp failed ({e})")
        return ""
    return "|".join(parts)
def target_element_rows(dbp=None,prefix="",limit=0):
    from Cores.Services import targets_service as _tsvc
    dbp=dbp or _db_path()
    try:usage=_tsvc._all_placeholder_usage(dbp) or {}
    except Exception:usage={}
    try:values_path,targets_path=_tsvc._paths()
    except Exception:values_path,targets_path="",""
    rows={}
    def add(k,priority=0,manual=False,source="target_values"):
        nk=_norm_tag(k)
        if not nk or "{" in nk or "}" in nk:return
        try:
            if not _tsvc._is_valid_key(nk):return
        except Exception:pass
        lk=nk.lower();cur=rows.get(lk,{})
        try:pr=_tsvc._clamp_u16(priority)
        except Exception:pr=0
        key=cur.get("key",nk)
        rows[lk]={"key":key,"token":"{"+key+"}","priority":max(pr,int(cur.get("priority",0) or 0)),"manual":bool(cur.get("manual",False) or manual),"usage":int((usage.get(lk) or {}).get("count",0) or 0),"source":cur.get("source",source)}
    vals=_tsvc._read_json(values_path,{}) if values_path else {}
    if isinstance(vals,dict):
        for k,v in vals.items():add(k,_tsvc._priority_from(v),_tsvc._manual_from(v),"target_values")
    elif isinstance(vals,list):
        for it in vals:
            if isinstance(it,str):add(it)
            elif isinstance(it,dict):add(it.get("key") or it.get("name"),it.get("priority",it.get("value",0)),it.get("manual",False))
    tg=_tsvc._read_json(targets_path,[]) if targets_path else []
    for t in (tg if isinstance(tg,list) else []):
        if isinstance(t,dict) and isinstance(t.get("values"),dict):
            for k in t["values"].keys():add(k,0,False,"targets")
    for v in usage.values():add((v or {}).get("key",""),0,False,"commands")
    base=sorted(rows.values(),key=lambda r:(-int(r.get("usage",0) or 0),r.get("key","").lower()))
    pre=_norm_tag(prefix).strip("{}").lower()
    if pre:base=[r for r in base if r.get("key","").lower().startswith(pre)]
    try:lim=int(limit)
    except Exception:lim=0
    return base[:lim] if lim>0 else base
_CMD_EXPORT_FIELDS=["note_name","category","sub_category","command","tags","description","command_type","noise_level"]
def _import_cmd_key(cmd):return re.sub(r"\s+"," ",_norm(cmd)).lower()
def _tables_lower(d):return {_norm(k).lower():v for k,v in (d or {}).items() if isinstance(v,list)}
class CommandsExport:
    def __init__(self):self.invalid=0
    def load(self):
        dbp=_db_path()
        rows=[]
        try:
            con=_common_db.connect(dbp);_ensure_schema(con)
            cur=con.cursor()
            cur.execute("SELECT id,note_name,category,sub_category,command,tags,description,command_type,noise_level FROM CommandsNotes ORDER BY id")
            for r in cur.fetchall():
                rows.append({"id":int(r[0]),"note_name":_norm(r[1]),"category":_norm(r[2]),"sub_category":_norm(r[3]),"command":(r[4] or "").rstrip(),"tags":_norm(r[5]),"description":_norm(r[6]),"command_type":_norm(r[7]) or "other","noise_level":_norm(r[8]) or "normal"})
            con.close()
        except Exception as e:
            _log("[!]",f"CommandsExport.load failed ({e})")
        return rows
    def export_json(self,out_path,rows):
        data=[{k:r.get(k,"") for k in _CMD_EXPORT_FIELDS} for r in (rows or [])]
        with open(out_path,"w",encoding="utf-8") as f:json.dump(data,f,ensure_ascii=False,indent=2)
    def export_csv(self,out_path,rows):
        with open(out_path,"w",encoding="utf-8",newline="") as f:
            w=csv.DictWriter(f,fieldnames=_CMD_EXPORT_FIELDS);w.writeheader()
            for r in (rows or []):w.writerow({k:r.get(k,"") for k in _CMD_EXPORT_FIELDS})
    def row(self,r):
        if not isinstance(r,dict):return None
        command=str(r.get("command","") or "").rstrip()
        if not _norm(command):return None
        return {"note_name":_norm(r.get("note_name",r.get("title",""))) or "Unlinked","category":_norm(r.get("category","")),"sub_category":_norm(r.get("sub_category",r.get("sub",""))),"command":command,"tags":_norm(r.get("tags","")),"description":_norm(r.get("description","")),"command_type":_norm(r.get("command_type","")),"noise_level":_norm(r.get("noise_level",""))}
    def rows(self,items):
        out=[]
        for r in (items or []):
            x=self.row(r)
            if x is None:self.invalid+=1
            else:out.append(x)
        return out
    def from_data(self,d):
        if isinstance(d,list):return self.rows(d)
        if isinstance(d,dict):return self.rows(_tables_lower(d).get("commandsnotes") or [])
        raise ValueError("Unsupported JSON: expected a list of commands or an object with a CommandsNotes list.")
    def parse_json(self,path):
        with open(path,"r",encoding="utf-8-sig") as f:d=json.load(f)
        return self.from_data(d)
    def parse_csv(self,path):
        with open(path,"r",encoding="utf-8-sig",newline="") as f:return self.rows(list(csv.DictReader(f)))
    def build_plan(self,incoming,base):
        base_by_key={}
        for r in (base or []):base_by_key.setdefault(_import_cmd_key(r.get("command","")),r)
        new=[];dups=[];seen=set()
        for r in (incoming or []):
            k=_import_cmd_key(r.get("command",""))
            if not k or k in seen:self.invalid+=1;continue
            seen.add(k)
            if k in base_by_key:dups.append({"table":"CommandsNotes","key":f"{r.get('note_name','')} - {_norm(r.get('command',''))[:60]}","incoming":r,"existing":base_by_key[k]})
            else:new.append(r)
        return {"new":new,"dups":dups,"invalid":self.invalid}
    def apply_plan(self,plan,decisions):
        dbp=_db_path()
        res={"added":0,"replaced":0,"overwritten":0,"skipped":0,"bad":0,"invalid":int((plan or {}).get("invalid",0) or 0)}
        def ins(r,ex=None):
            ex=ex or {}
            cid=_insert_cmd(dbp,r["note_name"],r.get("category",""),r.get("sub_category",""),r["command"],r.get("tags",""),r.get("description",""),r.get("command_type") or ex.get("command_type") or "other",r.get("noise_level") or ex.get("noise_level") or "normal")
            if cid is None:raise ValueError("Insert failed.")
        for r in ((plan or {}).get("new") or []):
            try:ins(r);res["added"]+=1
            except Exception as e:res["bad"]+=1;_log("[!]",f"Commands import row failed ({e})")
        for idx,d in enumerate((plan or {}).get("dups") or []):
            act=(decisions or {}).get(idx,"Skip")
            if act not in ("Replace","Overwrite"):res["skipped"]+=1;continue
            r=d.get("incoming") or {};ex=d.get("existing") or {}
            try:
                if act=="Replace":
                    if not _update_cmd(dbp,ex.get("id"),r["note_name"],r.get("category",""),r.get("sub_category",""),r["command"],r.get("tags",""),r.get("description",""),r.get("command_type") or ex.get("command_type") or "other",r.get("noise_level") or ex.get("noise_level") or "normal"):raise ValueError("Existing command not found.")
                    res["replaced"]+=1
                else:
                    if not _delete_cmd({"db":dbp,"id":ex.get("id"),"src":"CommandsNotes"}):raise ValueError("Could not remove the existing command.")
                    ins(r,ex);res["overwritten"]+=1
            except Exception as e:res["bad"]+=1;_log("[!]",f"Commands import row failed ({e})")
        return res
