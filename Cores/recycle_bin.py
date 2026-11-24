import hashlib,json,os,threading
from datetime import datetime,timedelta,timezone
from Cores import common_db
from Cores import target_profiles as _target_profiles
RETENTION_DAYS=30
from Cores.settings_lock import SETTINGS_LOCK as _settings_lock
from Cores import doc_store as _doc_store
TYPE_NOTE="note"
TYPE_COMMAND="command"
TYPE_TARGET="target"
TYPE_REPORT="report"
TYPE_REPORT_FINDING="report_finding"
TYPE_REPORT_EVIDENCE="report_evidence"
TYPE_LABELS={TYPE_NOTE:"Note",TYPE_COMMAND:"Command",TYPE_TARGET:"Target",TYPE_REPORT:"Report",TYPE_REPORT_FINDING:"Report finding",TYPE_REPORT_EVIDENCE:"Report evidence"}
def _norm(v):return str(v or "").strip()
def _utc_now():return datetime.now(timezone.utc)
def _iso(dt):return dt.astimezone(timezone.utc).isoformat()
def now_text():return _iso(_utc_now())
def _settings_path():return os.path.join(common_db.data_dir(),"settings.json")
def get_retention_days():
    d=_read_json(_settings_path(),{})
    rb=d.get("recycle_bin",{}) if isinstance(d,dict) else {}
    try:days=int(rb.get("retention_days",RETENTION_DAYS))
    except Exception:days=RETENTION_DAYS
    return max(1,min(365,days))
def set_retention_days(days):
    try:days=max(1,min(365,int(days)))
    except Exception:raise ValueError("Retention days must be a whole number.")
    with _settings_lock:
        d=_read_json(_settings_path(),{})
        if not isinstance(d,dict):d={}
        d["recycle_bin"]={"retention_days":days}
        _write_json(_settings_path(),d)
    return days
def expires_text(days=None):
    d=days if days is not None else get_retention_days()
    return _iso(_utc_now()+timedelta(days=max(1,int(d or RETENTION_DAYS))))
def _read_json(path,default):
    if _doc_store.active(path):return _doc_store.read_json(path,default)
    try:
        if not path or not os.path.isfile(path):return default
        with open(path,"r",encoding="utf-8") as fh:
            data=json.load(fh)
            return data if data is not None else default
    except Exception:
        return default
def _write_json(path,obj):
    if _doc_store.active(path):return _doc_store.write_json(path,obj)
    tmp=path+".tmp"
    os.makedirs(os.path.dirname(path),exist_ok=True)
    with open(tmp,"w",encoding="utf-8") as fh:json.dump(obj,fh,ensure_ascii=False,indent=2)
    os.replace(tmp,path)
def _targets_path():return _target_profiles.profile_targets_json_path()
def _target_id_seed(name):return hashlib.sha256(_norm(name).lower().encode("utf-8")).hexdigest()[:16]
def _payload_text(payload):return json.dumps(payload or {},ensure_ascii=False)
def _payload_obj(text):
    try:
        data=json.loads(text or "{}")
        return data if isinstance(data,dict) else {}
    except Exception:
        return {}
def put_entry_cur(cur,entity_type,label,payload,source="",entity_key="",deleted_at="",expires_at=""):
    deleted=_norm(deleted_at) or now_text()
    expires=_norm(expires_at) or expires_text()
    cur.execute("INSERT INTO RecycleBin(entity_type,entity_key,label,payload,source,deleted_at,expires_at) VALUES(?,?,?,?,?,?,?)",(_norm(entity_type),_norm(entity_key),_norm(label),_payload_text(payload),_norm(source),deleted,expires))
    try:return int(cur.lastrowid or 0)
    except Exception:return 0
def put_entry(entity_type,label,payload,source="",entity_key="",dbp=None,deleted_at="",expires_at=""):
    try:
        with common_db.connection(dbp or common_db.db_path(),timeout=5) as con:
            common_db.ensure_schema(con)
            rid=put_entry_cur(con.cursor(),entity_type,label,payload,source=source,entity_key=entity_key,deleted_at=deleted_at,expires_at=expires_at)
            con.commit()
            return True,rid
    except Exception as e:
        return False,str(e)
def _purge_orphan_files(dbp=None):
    # Soft-deleted notes keep their attachment folders so a restore can show them; once an entry is gone for good, drop folders nothing refers to.
    try:
        from Cores.Services import notes_service as _notes_svc
        _notes_svc.purge_orphan_attachments(dbp)
    except Exception:pass
    try:
        from Cores.Services import reports_service as _reports_svc
        _reports_svc.purge_orphan_assets(dbp)
    except Exception:pass
def purge_expired(dbp=None,now_value=""):
    try:
        with common_db.connection(dbp or common_db.db_path(),timeout=5) as con:
            common_db.ensure_schema(con)
            cur=con.cursor()
            cur.execute("DELETE FROM RecycleBin WHERE expires_at<>'' AND expires_at<=?",(_norm(now_value) or now_text(),))
            con.commit()
            n=int(cur.rowcount or 0)
    except Exception:
        return 0
    if n:_purge_orphan_files(dbp)
    return n
def purge_all(dbp=None):
    with common_db.connection(dbp or common_db.db_path(),timeout=5) as con:
        common_db.ensure_schema(con)
        cur=con.cursor();cur.execute("DELETE FROM RecycleBin");con.commit()
        n=int(cur.rowcount or 0)
    if n:_purge_orphan_files(dbp)
    return n
def list_entries(dbp=None,entity_type=""):
    purge_expired(dbp)
    rows=[]
    try:
        with common_db.connection(dbp or common_db.db_path(),timeout=5) as con:
            common_db.ensure_schema(con)
            cur=con.cursor()
            et=_norm(entity_type)
            if et:cur.execute("SELECT id,entity_type,entity_key,label,source,payload,deleted_at,expires_at FROM RecycleBin WHERE entity_type=? ORDER BY deleted_at DESC,id DESC",(et,))
            else:cur.execute("SELECT id,entity_type,entity_key,label,source,payload,deleted_at,expires_at FROM RecycleBin ORDER BY deleted_at DESC,id DESC")
            for r in cur.fetchall():
                rows.append({"id":int(r[0]),"entity_type":_norm(r[1]),"entity_key":_norm(r[2]),"label":_norm(r[3]),"source":_norm(r[4]),"payload":_payload_obj(r[5]),"deleted_at":_norm(r[6]),"expires_at":_norm(r[7])})
    except Exception:
        return []
    return rows
def delete_entry(entry_id,dbp=None):
    try:
        with common_db.connection(dbp or common_db.db_path(),timeout=5) as con:
            common_db.ensure_schema(con)
            cur=con.cursor()
            cur.execute("DELETE FROM RecycleBin WHERE id=?",(int(entry_id),))
            con.commit()
            if not cur.rowcount:return False,"Not found"
    except Exception as e:
        return False,str(e)
    _purge_orphan_files(dbp)
    return True,"Deleted permanently"
def _restore_note(cur,payload):
    note=payload.get("note",{}) if isinstance(payload,dict) else {}
    commands=payload.get("commands",[]) if isinstance(payload.get("commands",[]),list) else []
    note_name=_norm(note.get("note_name",""))
    if not note_name:raise ValueError("Recycle Bin note payload is invalid.")
    cur.execute("SELECT 1 FROM Notes WHERE note_name=?",(note_name,))
    if cur.fetchone():raise ValueError("A note with the same name already exists.")
    group_name=_norm(note.get("group_name",""))
    content=note.get("content","") or ""
    created_at=_norm(note.get("created_at","")) or now_text()
    updated_at=_norm(note.get("updated_at","")) or created_at
    note_tags=_norm(note.get("tags",""))
    cur.execute("INSERT INTO Notes(note_name,group_name,tags,content,created_at,updated_at) VALUES(?,?,?,?,?,?)",(note_name,group_name,note_tags,content,created_at,updated_at))
    note_id=int(cur.lastrowid or 0)
    stamp=now_text()
    try:cur.execute("INSERT INTO NotesHistory(note_id,note_name,group_name,content,action,action_at) VALUES(?,?,?,?,?,?)",(note_id,note_name,group_name,content,"restore",stamp))
    except Exception:pass
    for row in commands:
        if not isinstance(row,dict):continue
        ttl=_norm(row.get("cmd_note_title","")) or note_name
        cat=_norm(row.get("category",""))
        sub=_norm(row.get("sub_category",""))
        desc=_norm(row.get("description",""))
        tags=_norm(row.get("tags",""))
        command=row.get("command","") or ""
        c_created=_norm(row.get("created_at","")) or stamp
        c_updated=_norm(row.get("updated_at","")) or c_created
        cur.execute("INSERT INTO Commands(note_id,note_name,cmd_note_title,category,sub_category,description,tags,command,command_type,noise_level,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(note_id,note_name,ttl,cat,sub,desc,tags,command,_norm(row.get("command_type","")) or "other",_norm(row.get("noise_level","")) or "normal",c_created,c_updated))
        cmd_id=int(cur.lastrowid or 0)
        try:cur.execute("INSERT INTO CommandsHistory(cmd_id,note_id,note_name,cmd_note_title,category,sub_category,description,tags,command,action,action_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(cmd_id,note_id,note_name,ttl,cat,sub,desc,tags,command,"restore",stamp))
        except Exception:pass
def _restore_command(cur,payload):
    row=payload.get("command",{}) if isinstance(payload,dict) else {}
    note_name=_norm(row.get("note_name",""))
    category=_norm(row.get("category",""))
    sub=_norm(row.get("sub_category",""))
    command=row.get("command","") or ""
    tags=_norm(row.get("tags",""))
    desc=_norm(row.get("description",""))
    created_at=_norm(row.get("created_at","")) or now_text()
    updated_at=_norm(row.get("updated_at","")) or created_at
    cur.execute("INSERT INTO CommandsNotes(note_name,category,sub_category,command,tags,description,command_type,noise_level,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(note_name,category,sub,command,tags,desc,_norm(row.get("command_type","")) or "other",_norm(row.get("noise_level","")) or "normal",created_at,updated_at))
    cmd_id=int(cur.lastrowid or 0)
    stamp=now_text()
    try:cur.execute("INSERT INTO CommandsNotesHistory(cmd_id,note_name,category,sub_category,command,tags,description,action,action_at) VALUES(?,?,?,?,?,?,?,?,?)",(cmd_id,note_name,category,sub,command,tags,desc,"restore",stamp))
    except Exception:pass
def _restore_target(payload):
    row=payload.get("target",{}) if isinstance(payload,dict) else {}
    name=_norm(row.get("name",""))
    if not name:raise ValueError("Recycle Bin target payload is invalid.")
    pid=_norm(payload.get("profile_id",""))
    if pid and not any(_norm(p.get("id",""))==pid for p in _target_profiles.list_profiles()):pid=""
    path=_target_profiles.profile_targets_json_path(pid or None)
    targets=_read_json(path,[])
    if not isinstance(targets,list):targets=[]
    if any(_norm(t.get("name","")).lower()==name.lower() for t in targets if isinstance(t,dict)):raise ValueError("A target with the same name already exists.")
    tid=_norm(row.get("id","")) or _target_id_seed(name+now_text())
    if any(_norm(t.get("id",""))==tid for t in targets if isinstance(t,dict)):tid=_target_id_seed(name+now_text())
    status=_norm(row.get("status","not_used")).lower()
    if status=="live" and any(_norm(t.get("status","not_used")).lower()=="live" for t in targets if isinstance(t,dict)):status="not_used"
    if status!="live":status="not_used"
    vals=row.get("values",{})
    values={_norm(k):_norm(v) for k,v in (vals.items() if isinstance(vals,dict) else []) if _norm(k) and _norm(v)}
    created_at=_norm(row.get("created","")) or now_text()
    updated_at=_norm(row.get("updated","")) or created_at
    engagement=_norm(row.get("engagement_status","")).lower()
    if engagement not in ("not_started","in_progress","compromised","reported"):engagement="not_started"
    targets.append({"id":tid,"name":name,"status":status,"engagement_status":engagement,"values":values,"created":created_at,"updated":updated_at})
    _write_json(path,targets)
def restore_entry(entry_id,dbp=None):
    purge_expired(dbp)
    db_path=dbp or common_db.db_path()
    with common_db.connection(db_path,timeout=5) as con:
        common_db.ensure_schema(con)
        cur=con.cursor()
        cur.execute("SELECT id,entity_type,payload FROM RecycleBin WHERE id=?",(int(entry_id),))
        row=cur.fetchone()
        if not row:return False,"Not found"
        entity_type=_norm(row[1]);payload=_payload_obj(row[2])
        try:
            if entity_type==TYPE_NOTE:_restore_note(cur,payload)
            elif entity_type==TYPE_COMMAND:_restore_command(cur,payload)
            elif entity_type==TYPE_TARGET:_restore_target(payload)
            elif entity_type in (TYPE_REPORT,TYPE_REPORT_FINDING):
                from Cores.Services import reports_service as _reports_svc
                _reports_svc.restore_from_bin(cur,entity_type,payload)
            elif entity_type==TYPE_REPORT_EVIDENCE:
                from Cores.Services import evidence_service as _evidence_svc
                _evidence_svc.restore_entry(payload,cur)
            else:return False,"Unsupported Recycle Bin item."
            cur.execute("DELETE FROM RecycleBin WHERE id=?",(int(entry_id),))
            con.commit()
            return True,"Restored"
        except Exception as e:
            con.rollback()
            return False,str(e)
