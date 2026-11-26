import os,json,csv,re,time,logging,shutil,base64,zipfile,tempfile
from logging.handlers import RotatingFileHandler
from Cores import common_db as _common_db
from Cores import settings_lock as _settings_lock
from Cores.Update import health_check as _health_check
from Cores.Update import backup_restore as _update_backup
from Cores import target_profiles as _target_profiles
from Cores import doc_store as _doc_store
def _abs(*p):return os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","..",*p)
def _log_setup():
    d=_health_check.logs_dir();os.makedirs(d,exist_ok=True)
    lg=logging.getLogger("Settings");lg.setLevel(logging.INFO)
    fp=os.path.abspath(os.path.join(d,"Settings_log.log"))
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
def _norm(s):return (str(s) if s is not None else "").replace("\x00","").strip()
def _l(s):return _norm(s).lower()
def _db_path():return _common_db.db_path()
def _backups_dir():return _common_db.backups_dir()
def _targets_values_path():return _target_profiles.profile_target_values_path()
def _targets_path():return _target_profiles.profile_targets_json_path()
def _settings_path():return _health_check.settings_path()
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
    except Exception as e:
        _log("[!]",f"Write JSON failed: {p} ({e})")
        try:
            if os.path.isfile(t):os.remove(t)
        except Exception:pass
        return False
def _read_settings():return _read_json(_settings_path(),{})
def _write_settings(data):return _write_json(_settings_path(),data or {})
def _get_backup_settings():
    d=_read_settings()
    b=d.get("backup",{}) if isinstance(d,dict) else {}
    try:interval=int(b.get("interval_hours",24))
    except Exception:interval=24
    try:keep=int(b.get("keep",20))
    except Exception:keep=20
    return {"auto_enabled":bool(b.get("auto_enabled",False)),"interval_hours":max(1,interval),"keep":max(1,keep),"offsite_dir":_norm(b.get("offsite_dir",""))}
@_settings_lock.serialized
def _save_backup_settings(cfg):
    d=_read_settings()
    if not isinstance(d,dict):d={}
    cur=d.get("backup",{}) if isinstance(d.get("backup",{}),dict) else {}
    cur.update({"auto_enabled":bool(cfg.get("auto_enabled",False)),"interval_hours":int(cfg.get("interval_hours",24)),"keep":int(cfg.get("keep",20)),"offsite_dir":_norm(cfg.get("offsite_dir",""))})
    d["backup"]=cur
    return _write_settings(d)
def get_notification_settings():
    d=_read_settings()
    n=d.get("notifications",{}) if isinstance(d,dict) else {}
    return {"os_enabled":bool(n.get("os_enabled",False))}
@_settings_lock.serialized
def set_notification_settings(enabled):
    d=_read_settings()
    if not isinstance(d,dict):d={}
    d["notifications"]={"os_enabled":bool(enabled)}
    _write_settings(d)
    return get_notification_settings()
def get_onboarding_state():
    d=_read_settings()
    o=d.get("onboarding",{}) if isinstance(d,dict) else {}
    return {"first_run_complete":bool(o.get("first_run_complete",False))}
@_settings_lock.serialized
def set_onboarding_complete(complete=True):
    d=_read_settings()
    if not isinstance(d,dict):d={}
    d["onboarding"]={"first_run_complete":bool(complete)}
    _write_settings(d)
    return get_onboarding_state()
def get_focus_mode_enabled():
    d=_read_settings()
    fm=d.get("focus_mode",{}) if isinstance(d,dict) else {}
    return bool(fm.get("enabled",False))
@_settings_lock.serialized
def set_focus_mode_enabled(enabled):
    d=_read_settings()
    if not isinstance(d,dict):d={}
    d["focus_mode"]={"enabled":bool(enabled)}
    _write_settings(d)
    return get_focus_mode_enabled()
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
def _dedupe_tags(tags):
    out=[];seen=set()
    for t in tags or []:
        tt=_norm(t)
        if not tt:continue
        k=tt.lower()
        if k in seen:continue
        seen.add(k);out.append(tt)
    return out
def _join_tags(tags):return ",".join(_dedupe_tags(tags))
def _decode_card_token(token):
    t=_norm(token)
    try:
        d=json.loads(base64.urlsafe_b64decode(t+"="*((4-len(t)%4)%4)).decode("utf-8"))
        return d if isinstance(d,dict) else {}
    except Exception:return {}
def _encode_card_token(d):return base64.urlsafe_b64encode(json.dumps(d,ensure_ascii=False).encode("utf-8")).decode("ascii").rstrip("=")
_TAG_COLOR_RE=re.compile(r"^#[0-9a-fA-F]{6}$")
def _tag_colors_path():return os.path.join(_health_check.data_dir(),"tag_colors.json")
def _read_tag_colors():
    d=_read_json(_tag_colors_path(),{})
    return d if isinstance(d,dict) else {}
def _write_tag_colors(d):return _write_json(_tag_colors_path(),d or {})
def get_tag_colors():
    d=_read_tag_colors()
    out={}
    for k,v in d.items():
        if isinstance(v,dict) and v.get("color"):
            out[_l(k)]=_norm(v.get("color"))
    return out
def set_tag_color(tag,color):
    tag=_norm(tag)
    if not tag:raise ValueError("Tag is required.")
    color=_norm(color)
    if color and not _TAG_COLOR_RE.match(color):raise ValueError("Color must be a hex value like #3b82f6.")
    d=_read_tag_colors()
    k=_l(tag)
    if color:
        d[k]={"tag":tag,"color":color}
    else:
        d.pop(k,None)
    if not _write_tag_colors(d):raise ValueError("Failed to save tag color.")
    return {"tag":tag,"color":color}
def rename_tag_color(old_tag,new_tag):
    d=_read_tag_colors()
    ok=_l(old_tag);nk=_l(new_tag)
    if not ok or not nk or ok==nk or ok not in d:return
    entry=d.pop(ok)
    if nk not in d and isinstance(entry,dict):
        entry["tag"]=_norm(new_tag)
        d[nk]=entry
    _write_tag_colors(d)
class TargetValues:
    def __init__(self,path=None):self.path=path or _targets_values_path()
    def load(self):
        d=_read_json(self.path,{})
        out={}
        if isinstance(d,dict):
            for k,v in d.items():
                kk=_norm(k)
                if not kk:continue
                vv=v.get("priority",v.get("value",0)) if isinstance(v,dict) else v
                try:vv=int(vv)
                except Exception:vv=0
                entry={"priority":max(0,min(65535,vv))}
                if isinstance(v,dict) and v.get("manual"):entry["manual"]=True
                out[kk]=entry
        return out
    def save(self,data):
        out={}
        for k,v in (data or {}).items():
            kk=_norm(k)
            if not kk:continue
            try:vv=int((v or {}).get("priority",(v or {}).get("value",0)))
            except Exception:vv=0
            entry={"priority":max(0,min(65535,vv))}
            if isinstance(v,dict) and v.get("manual"):entry["manual"]=True
            out[kk]=entry
        return _write_json(self.path,out)
    def export_json(self,out_path,data):
        out={}
        for k,v in (data or {}).items():
            entry={"priority":int((v or {}).get("priority",(v or {}).get("value",0)) or 0)}
            if isinstance(v,dict) and v.get("manual"):entry["manual"]=True
            out[k]=entry
        _write_json(out_path,out)
    def export_csv(self,out_path,data):
        with open(out_path,"w",encoding="utf-8",newline="") as f:
            w=csv.DictWriter(f,fieldnames=["key","priority"]);w.writeheader()
            for k,v in sorted((data or {}).items(),key=lambda x:x[0].lower()):
                w.writerow({"key":_norm(k),"priority":int((v or {}).get("priority",(v or {}).get("value",0)) or 0)})
    def parse_json(self,path):
        d=_read_json(path,{})
        if not isinstance(d,dict):return {}
        out={}
        for k,v in d.items():
            kk=_norm(k)
            if not kk:continue
            vv=v.get("priority",v.get("value",0)) if isinstance(v,dict) else v
            try:vv=int(vv)
            except Exception:vv=0
            entry={"priority":max(0,min(65535,vv))}
            if isinstance(v,dict) and v.get("manual"):entry["manual"]=True
            out[kk]=entry
        return out
    def parse_csv(self,path):
        out={}
        with open(path,"r",encoding="utf-8",newline="") as f:
            rd=csv.DictReader(f)
            for r in rd:
                kk=_norm(r.get("key",r.get("name","")))
                if not kk:continue
                try:vv=int(_norm(r.get("priority",r.get("value","0"))) or "0")
                except Exception:vv=0
                out[kk]={"priority":max(0,min(65535,vv))}
        return out
    def build_plan(self,incoming,base):
        dups=[];new={}
        base_ci={_l(k):k for k in (base or {}).keys()}
        for k,v in (incoming or {}).items():
            lk=_l(k)
            if lk in base_ci:
                exk=base_ci[lk]
                dups.append({"key":k,"existing_key":exk,"existing":base.get(exk,{}),"incoming":v})
            else:
                new[k]=v
        return {"new":new,"dups":dups}
    def apply_plan(self,base,plan,decisions):
        added=0;replaced=0;overwritten=0;skipped=0
        for k,v in (plan.get("new") or {}).items():
            entry={"priority":int((v or {}).get("priority",(v or {}).get("value",0)) or 0)}
            if isinstance(v,dict) and v.get("manual"):entry["manual"]=True
            base[_norm(k)]=entry;added+=1
        for idx,d in enumerate(plan.get("dups") or []):
            act=decisions.get(idx,"Skip")
            if act=="Skip":skipped+=1;continue
            exk=d.get("existing_key","")
            if act=="Replace":
                incoming=d.get("incoming") or {}
                existing=base.get(exk,{})
                entry={"priority":int((incoming.get("priority",incoming.get("value",0)) or 0))}
                if isinstance(incoming,dict) and "manual" in incoming:
                    if incoming.get("manual"):entry["manual"]=True
                elif isinstance(existing,dict) and existing.get("manual"):
                    entry["manual"]=True
                base[exk]=entry;replaced+=1
            else:
                del base[exk]
                incoming=d.get("incoming") or {}
                entry={"priority":int((incoming.get("priority",incoming.get("value",0)) or 0))}
                if isinstance(incoming,dict) and incoming.get("manual"):entry["manual"]=True
                base[_norm(d.get("key",""))]=entry;overwritten+=1
        return {"added":added,"replaced":replaced,"overwritten":overwritten,"skipped":skipped,"dups":len(plan.get("dups") or [])}
class Targets:
    def __init__(self,path=None):self.path=path or _targets_path()
    def load(self):
        d=_read_json(self.path,[])
        if isinstance(d,list):return d
        if isinstance(d,dict):return [d]
        return []
    def save(self,data):
        arr=[x for x in (data or []) if isinstance(x,(dict,list,str,int,float,bool)) or x is None]
        return _write_json(self.path,arr)
    def export_json(self,out_path,data):_write_json(out_path,data if isinstance(data,list) else [data] if isinstance(data,dict) else [])
    def export_csv(self,out_path,data):
        arr=data if isinstance(data,list) else [data] if isinstance(data,dict) else []
        keys=[]
        for it in arr:
            vals=it.get("values",{}) if isinstance(it,dict) and isinstance(it.get("values",{}),dict) else {}
            for k in vals.keys():
                kk=_norm(k)
                if kk and kk not in keys:keys.append(kk)
        fields=["id","name","status","created","updated"]+keys
        with open(out_path,"w",encoding="utf-8",newline="") as f:
            w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
            for it in arr:
                if not isinstance(it,dict):continue
                vals=it.get("values",{}) if isinstance(it.get("values",{}),dict) else {}
                row={k:_norm(it.get(k,"")) for k in ["id","name","status","created","updated"]}
                for k in keys:row[k]=_norm(vals.get(k,""))
                w.writerow(row)
    def parse_json(self,path):
        d=_read_json(path,[])
        if isinstance(d,list):return d
        if isinstance(d,dict):return [d]
        return []
    def parse_csv(self,path):
        out=[];base={"id","name","target","target_name","status","created","updated","values","values_json"}
        with open(path,"r",encoding="utf-8",newline="") as f:
            rd=csv.DictReader(f)
            for r in rd:
                if not isinstance(r,dict):continue
                vals={}
                raw=_norm(r.get("values_json",r.get("values","")))
                if raw:
                    try:
                        parsed=json.loads(raw)
                        if isinstance(parsed,dict):vals.update({str(k):"" if v is None else str(v) for k,v in parsed.items()})
                    except Exception:pass
                for k,v in r.items():
                    kk=_norm(k)
                    if not kk or _l(kk) in base:continue
                    vv=_norm(v)
                    if vv:vals[kk]=vv
                name=_norm(r.get("name",r.get("target_name",r.get("target",""))))
                if not name and not vals:continue
                st=_l(r.get("status","not_used")).replace(" ","_").replace("-","_")
                item={"id":_norm(r.get("id","")),"name":name,"status":"live" if st in ("live","used") else "not_used","values":vals,"created":_norm(r.get("created","")),"updated":_norm(r.get("updated",""))}
                out.append(item)
        return out
    def _key(self,item):
        if isinstance(item,dict):
            if _norm(item.get("id","")):return "id:"+_l(item.get("id",""))
            if _norm(item.get("name","")):return "name:"+_l(item.get("name",""))
        return "raw:"+_l(json.dumps(item,ensure_ascii=False,sort_keys=True))
    def _summ(self,item):
        if isinstance(item,dict):
            a=_norm(item.get("id",""));b=_norm(item.get("name",""));c=_norm(item.get("status",""))
            if a or b:return f"{a} {b} {c}".strip()
        return _norm(json.dumps(item,ensure_ascii=False))[:120]
    def build_plan(self,incoming,base):
        base_map={}
        for it in (base or []):
            k=self._key(it)
            if k and k not in base_map:base_map[k]=it
        dups=[];new=[]
        for it in (incoming or []):
            k=self._key(it)
            if k in base_map:dups.append({"key":k,"existing":base_map[k],"incoming":it})
            else:new.append(it)
        return {"new":new,"dups":dups}
    def apply_plan(self,base,plan,decisions):
        added=0;replaced=0;overwritten=0;skipped=0
        for it in (plan.get("new") or []):
            base.append(it);added+=1
        for idx,d in enumerate(plan.get("dups") or []):
            act=decisions.get(idx,"Skip")
            if act=="Skip":skipped+=1;continue
            ek=d.get("key","")
            if act=="Replace":
                for i,cur in enumerate(list(base)):
                    if self._key(cur)==ek:
                        base[i]=d.get("incoming");replaced+=1;break
            else:
                base=[x for x in base if self._key(x)!=ek]
                base.append(d.get("incoming"));overwritten+=1
        return base,{"added":added,"replaced":replaced,"overwritten":overwritten,"skipped":skipped,"dups":len(plan.get("dups") or [])}
class Backup:
    def __init__(self,dir_path=None):self.dir=dir_path or _backups_dir()
    def list(self):
        rows=[]
        try:
            for n in os.listdir(self.dir):
                if not n.lower().endswith((".zip",".loyabak")):continue
                p=os.path.join(self.dir,n)
                try:
                    st=os.stat(p)
                    rows.append((p,st.st_mtime,st.st_size))
                except Exception:pass
        except Exception:pass
        rows.sort(key=lambda x:x[1],reverse=True)
        return rows
    def latest(self):
        rows=self.list()
        return rows[0] if rows else (None,None,None)
    def trim(self,keep):
        try:keep=max(1,int(keep))
        except Exception:keep=20
        rows=self.list()
        ok=0;bad=0
        for p,_,_ in rows[keep:]:
            try:
                if p and os.path.isfile(p) and os.path.dirname(os.path.abspath(p))==os.path.abspath(self.dir):
                    os.remove(p);ok+=1
                else:bad+=1
            except Exception:bad+=1
        return ok,bad
    def create(self,progress=None,password=None,remember=False):
        """An encrypted .loyabak (see backup_restore.create_data_backup). password: a new or one-off backup password (checked);
        remember: keep it in the OS keyring for automatic and update backups (never in Data/ or settings.json)."""
        from Cores import backup_password as _bp
        if password:
            err=_bp.check(password)
            if err:raise ValueError(err)
        out=_update_backup.create_data_backup(progress=progress,prefix="Backup",out_dir=self.dir,password=password or None)
        if password and remember and not _bp.remember(password):_log("[!]","Backup password not remembered: no OS keyring available.")
        clear_backup_notice()
        return out
    def restore(self,zip_path,mode,progress=None,pin=None,current_pin=None,password=None):
        return _update_backup.restore_data_backup(zip_path,mode=mode,progress=progress,pin=pin,current_pin=current_pin,password=password)
    def delete(self,paths):
        ok=0;bad=0
        for p in (paths or []):
            try:
                if p and os.path.isfile(p) and os.path.dirname(os.path.abspath(p))==os.path.abspath(self.dir):
                    os.remove(p);ok+=1
                else:bad+=1
            except Exception:bad+=1
        return ok,bad
def export_all_zip(out_path,**opts):
    """Export my work: the allowlisted content only (Cores/Services/work_export.py). Returns the number of zip entries."""
    from Cores.Services import work_export as _we
    return _we.export_work_zip(out_path,**opts)["files"]
def import_all_info(path):
    """The number of content items a work export (or an old full-Data zip) would bring, 0 when it is not one."""
    from Cores.Services import work_import as _wi
    kind=_wi.detect(path)
    if kind=="work_protected":return 1
    if kind not in ("work","legacy"):return 0
    try:return sum(int(v or 0) for v in (_wi.preview(path).get("counts") or {}).values())
    except Exception:return 0
AUTO_BACKUP_SKIPPED="Automatic backup skipped: set a backup password first."
def backup_password_status():
    """What the Backup card shows: is a password remembered (OS keyring), is a keyring there at all, the minimum length, and
    whether encryption at rest protects backups with the PIN instead."""
    from Cores import backup_password as _bp
    return {"remembered":_bp.has(),"keyring":_bp.available(),"min_len":_bp.MIN_LEN,"at_rest":bool(_common_db.encryption_configured())}
def get_backup_notice():
    d=_read_settings();b=d.get("backup",{}) if isinstance(d,dict) else {}
    n=b.get("notice") if isinstance(b,dict) else None
    return n if isinstance(n,dict) and n.get("text") else None
@_settings_lock.serialized
def _set_backup_notice(text):
    d=_read_settings()
    if not isinstance(d,dict):d={}
    cur=d.get("backup",{}) if isinstance(d.get("backup",{}),dict) else {}
    if text:cur["notice"]={"text":str(text),"at":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())}
    elif "notice" in cur:cur.pop("notice",None)
    else:return True
    d["backup"]=cur
    return _write_settings(d)
def clear_backup_notice():
    try:return _set_backup_notice("")
    except Exception:return False
def auto_backup_if_needed():
    cfg=_get_backup_settings()
    if not cfg.get("auto_enabled"):return False,"Auto backup disabled."
    try:
        back=Backup()
        _,mt,_=back.latest()
        interval=int(cfg.get("interval_hours",24))*3600
        if mt and (time.time()-float(mt))<interval:return False,"Recent backup exists."
        # Never an unencrypted backup: without encryption at rest (unlocked) or a remembered backup password, skip with a notice.
        from Cores import backup_password as _bp
        if not (_common_db.encryption_configured() and _common_db.session_key() is not None) and not _bp.has():
            _set_backup_notice(AUTO_BACKUP_SKIPPED)
            _log("[!]",AUTO_BACKUP_SKIPPED)
            return False,AUTO_BACKUP_SKIPPED
        out=back.create()
        try:back.trim(cfg.get("keep",20))
        except Exception:pass
        _log("[+]",f"Auto backup created: {out}")
        offsite_dir=_norm(cfg.get("offsite_dir",""))
        if offsite_dir:
            try:
                os.makedirs(offsite_dir,exist_ok=True)
                shutil.copy2(out,os.path.join(offsite_dir,os.path.basename(out)))
                _log("[+]",f"Off-machine backup copy saved to {offsite_dir}")
            except Exception as e:
                _log("[!]",f"Off-machine backup copy failed ({e})")
        return True,os.path.basename(out)
    except Exception as e:
        _log("[!]",f"Auto backup failed ({e})")
        return False,f"Auto backup failed: {e}"
class TagManager:
    def __init__(self,db_path=None):self.db_path=db_path or _db_path()
    def _collect(self,cur,table):
        tags={}
        try:
            cur.execute(f"SELECT tags FROM {table} WHERE tags IS NOT NULL AND TRIM(tags)<>''")
        except Exception:return tags
        for (t,) in cur.fetchall():
            for tag in _split_tags(t):
                k=tag.lower()
                if k not in tags:tags[k]={"tag":tag,"count":0}
                tags[k]["count"]+=1
        return tags
    def load_summary(self):
        if not os.path.isfile(self.db_path):return []
        with _common_db.connection(self.db_path,timeout=5) as con:
            cur=con.cursor()
            a=self._collect(cur,"CommandsNotes")
            b=self._collect(cur,"Commands")
            n=self._collect(cur,"Notes")
        rows=[]
        for k in set(a.keys())|set(b.keys())|set(n.keys()):
            tag=(a.get(k) or b.get(k) or n.get(k) or {}).get("tag",k)
            cn=(a.get(k) or {}).get("count",0);cl=(b.get(k) or {}).get("count",0);nt=(n.get(k) or {}).get("count",0)
            rows.append({"tag":tag,"commands_notes":cn,"linked":cl,"notes_tagged":nt,"total":cn+cl+nt})
        rows.sort(key=lambda x:(-x.get("total",0),x.get("tag","").lower()))
        return rows
    def _apply_change(self,tags,mode,old_set,new_tag):
        out=[]
        newt=_norm(new_tag)
        for t in tags or []:
            tl=_norm(t).lower()
            if tl in old_set:
                if mode in ("rename","merge") and newt:out.append(newt)
            else:
                out.append(t)
        return _dedupe_tags(out)
    def _update_table(self,cur,table,mode,old_set,new_tag):
        try:cur.execute(f"SELECT id,tags FROM {table}")
        except Exception:return 0
        changed=0
        for rid,tags in cur.fetchall():
            ntags=self._apply_change(_split_tags(tags),mode,old_set,new_tag)
            new_val=_join_tags(ntags)
            if _norm(tags)!=new_val:
                cur.execute(f"UPDATE {table} SET tags=? WHERE id=?",(new_val,rid))
                changed+=1
        return changed
    _LEGACY_RX=re.compile(r"((?:&lt;|<)C\s*\[)(.*?)(\]\s*(?:&gt;|>))",re.S|re.I)
    _TOKEN_RX=re.compile(r"((?:cmdcard|cmd:edit|cmdedit|cmddelete|cmdcopy):)([A-Za-z0-9_-]+)",re.I)
    def _update_note_html(self,html_text,mode,old_set,new_tag):
        changed=[False]
        def repl(m):
            meta=m.group(2)
            m2=re.search(r"Tags:([^,\]]*)",meta,re.I)
            if not m2:return m.group(0)
            tags=_split_tags(m2.group(1))
            ntags=self._apply_change(tags,mode,old_set,new_tag)
            if ntags==tags:return m.group(0)
            changed[0]=True
            return m.group(1)+meta[:m2.start()]+"Tags: "+";".join(ntags)+meta[m2.end():]+m.group(3)
        cache={}
        def trepl(m):
            tok=m.group(2)
            if tok not in cache:
                cache[tok]=tok
                d=_decode_card_token(tok)
                if d:
                    tags=_split_tags(d.get("tags",""))
                    ntags=self._apply_change(tags,mode,old_set,new_tag)
                    if ntags!=tags:
                        d["tags"]=_join_tags(ntags);cache[tok]=_encode_card_token(d);changed[0]=True
            return m.group(1)+cache[tok]
        new_html=self._LEGACY_RX.sub(repl,html_text or "")
        new_html=self._TOKEN_RX.sub(trepl,new_html)
        return new_html,changed[0]
    def update_tags(self,mode,old_tags,new_tag,include_linked=False):
        old_set=set([_norm(t).lower() for t in (old_tags or []) if _norm(t)])
        res={"commands_notes":0,"linked":0,"notes":0,"note_tags":0}
        if not old_set or not os.path.isfile(self.db_path):return res
        with _common_db.connection(self.db_path,timeout=5) as con:
            cur=con.cursor()
            res["commands_notes"]=self._update_table(cur,"CommandsNotes",mode,old_set,new_tag)
            res["note_tags"]=self._update_table(cur,"Notes",mode,old_set,new_tag)
            if include_linked:
                res["linked"]=self._update_table(cur,"Commands",mode,old_set,new_tag)
                try:
                    cur.execute("SELECT id,content FROM Notes")
                    for nid,content in cur.fetchall():
                        new_html,chg=self._update_note_html(content,mode,old_set,new_tag)
                        if chg:
                            cur.execute("UPDATE Notes SET content=? WHERE id=?",(new_html,nid))
                            res["notes"]+=1
                except Exception:pass
            con.commit()
        return res
