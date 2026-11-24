import os,json,logging,hashlib,re,html,base64,ipaddress
from Cores import common_db as _common_db
from Cores import settings_lock as _settings_lock
from logging.handlers import RotatingFileHandler
from datetime import datetime,timezone
from Cores.Update import health_check as _health_check
from Cores import recycle_bin as _recycle_bin
from Cores import target_profiles as _profiles
from Cores import doc_store as _doc_store
def _abs(*p):return os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","..",*p)
def _log_setup():
    d=_health_check.logs_dir();os.makedirs(d,exist_ok=True)
    lg=logging.getLogger("Target");lg.setLevel(logging.INFO)
    fp=os.path.abspath(os.path.join(d,"Target_log.log"))
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
def _data_dir():
    d=_health_check.data_dir();os.makedirs(d,exist_ok=True);return d
def _db_path():
    return _health_check.db_path()
def _paths(profile_id=None):
    return _profiles.profile_target_values_path(profile_id),_profiles.profile_targets_json_path(profile_id)
def list_profiles():return _profiles.list_profiles()
def active_profile_id():return _profiles.active_profile_id()
def create_profile(name):return _profiles.create_profile(name)
def rename_profile(pid,name):return _profiles.rename_profile(pid,name)
def switch_profile(pid):return _profiles.switch_profile(pid)
def delete_profile(pid):return _profiles.delete_profile(pid)
def _now():return datetime.now(timezone.utc).isoformat()
def _norm(s):return (str(s) if s is not None else "").strip()
def _kci(s):return _norm(s).lower()
def _sid(s):return hashlib.sha256(_norm(s).lower().encode("utf-8")).hexdigest()[:16]
def _clamp_u16(n):
    try:n=int(n)
    except Exception:return 0
    if n<0:n=0
    if n>65535:n=65535
    return n
_SETTINGS_CACHE=None
_SETTINGS_MTIME=None
_KEY_RE_STRICT=re.compile(r"^[^{}\r\n]+$")
_KEY_RE_EXT=re.compile(r"^[^{}\r\n]+$")
def _settings_path():
    return _health_check.settings_path()
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
        with open(t,"w",encoding="utf-8") as f:json.dump(data,f,ensure_ascii=False,indent=2)
        os.replace(t,p)
        _SETTINGS_CACHE=data if isinstance(data,dict) else {}
        try:_SETTINGS_MTIME=os.path.getmtime(p)
        except Exception:_SETTINGS_MTIME=None
        return True
    except Exception as e:
        _log("[!]",f"Write settings failed: {p} ({e})")
        try:
            if os.path.isfile(t):os.remove(t)
        except Exception:pass
        return False
def _allow_dots_colons():
    s=_read_settings()
    t=s.get("targets",{}) if isinstance(s,dict) else {}
    return bool(t.get("allow_dots_colons",False))
@_settings_lock.serialized
def _set_allow_dots_colons(val):
    s=_read_settings()
    if not isinstance(s,dict):s={}
    t=s.get("targets",{}) if isinstance(s.get("targets",{}),dict) else {}
    t["allow_dots_colons"]=bool(val)
    s["targets"]=t
    return _write_settings(s)
# Quotes, $ and backticks never appear in a target key: they mark shell/JSON braces such as ${HOME}, {"a":1}, awk '{print $1}' or { $_.Name }.
# Commas, pipes, =, <, >, parentheses, *, ; and backslashes mark jq objects {id,email}, bash brace expansion {a,b}, regex counts {2,3},
# format strings and code blocks - none is a placeholder (the page-side detector in snippets.js only accepts identifier-like keys).
_KEY_BAD_CHARS=frozenset('"\'$`,;=|<>()*\\')
_KEY_NUMERIC_RE=re.compile(r"[\d\s.]+")
def _is_valid_key(k):
    k=_norm(k)
    if not k or any(c in _KEY_BAD_CHARS for c in k):return False
    if _KEY_NUMERIC_RE.fullmatch(k):return False
    return bool(_KEY_RE_EXT.fullmatch(k))
def _strip_braces(k):
    k=_norm(k)
    if len(k)>=2 and k.startswith("{") and k.endswith("}"):k=_norm(k[1:-1])
    return k
def _iter_brace_keys(text):
    t=html.unescape(str(text or ""))
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
            raw=_norm(t[start+1:j])
            if raw:yield raw
        i=j+1
_TOKEN_RE=re.compile(r"(cmdedit:|cmddelete:|cmdcard:)([A-Za-z0-9_-]+)")
def _table_cols(cur,t):
    try:cur.execute(f"PRAGMA table_info({t})");return [r[1] for r in cur.fetchall()]
    except Exception:return []
def _extract_keys_from_text(text):
    out=[]
    if not text:return out
    for k in _iter_brace_keys(text):
        if k and _is_valid_key(k):out.append(k)
    return out
def _extract_keys_from_db(dbp,tables=("Commands","CommandsNotes")):
    keys=[]
    seen=set()
    if not dbp or not os.path.isfile(dbp):return keys
    con=None
    try:
        con=_common_db.connect(dbp,timeout=5)
        cur=con.cursor()
        for table in tables:
            col="command"
            try:
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",(table,))
                if not cur.fetchone():continue
                cols=set(_table_cols(cur,table))
                if col not in cols:continue
                q="SELECT {col} FROM {table} WHERE {col} LIKE '%{{%' AND {col} LIKE '%}}%'".format(col=col,table=table)
                cur.execute(q)
                for (text,) in cur.fetchall():
                    for k in _extract_keys_from_text(text):
                        lk=_kci(k)
                        if lk in seen:continue
                        seen.add(lk)
                        keys.append(k)
            except Exception:
                continue
        return keys
    except Exception as e:
        _log("[!]",f"Read keys from DB failed ({e})")
        return keys
    finally:
        try:
            if con:con.close()
        except Exception:pass
def _command_links_map(dbp,include_unlinked=False):
    links={}
    if not dbp or not os.path.isfile(dbp):return links
    con=None
    try:
        con=_common_db.connect(dbp,timeout=5)
        cur=con.cursor()
        tables=("CommandsNotes","Commands") if include_unlinked else ("Commands",)
        for table in tables:
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",(table,))
            if not cur.fetchone():continue
            cols=set(_table_cols(cur,table))
            if "command" not in cols:continue
            q=f"SELECT command FROM {table} WHERE command LIKE '%{{%' AND command LIKE '%}}%'"
            cur.execute(q)
            for (text,) in cur.fetchall():
                if not text:continue
                keys=set(_extract_keys_from_text(text))
                for k in keys:
                    lk=_kci(k)
                    links[lk]=links.get(lk,0)+1
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Notes'")
        if cur.fetchone():
            cols=set(_table_cols(cur,"Notes"))
            if "content" in cols:
                cur.execute("SELECT content FROM Notes WHERE content LIKE '%cmdedit:%' OR content LIKE '%cmdcard:%' OR content LIKE '%cmddelete:%'")
                for (content,) in cur.fetchall():
                    keys=set()
                    for cmd in _note_token_commands(content):keys.update(_extract_keys_from_text(cmd))
                    for k in keys:
                        lk=_kci(k)
                        links[lk]=links.get(lk,0)+1
        return links
    except Exception as e:
        _log("[!]",f"Read links from DB failed ({e})")
        return links
    finally:
        try:
            if con:con.close()
        except Exception:pass
def _all_placeholder_usage(dbp):
    used={}
    def record(k):
        lk=_kci(k)
        if not lk:return
        if lk not in used:used[lk]={"key":k,"count":0}
        used[lk]["count"]+=1
    if not dbp or not os.path.isfile(dbp):return used
    con=None
    try:
        con=_common_db.connect(dbp,timeout=5)
        cur=con.cursor()
        for table in ("CommandsNotes","Commands"):
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",(table,))
            if not cur.fetchone():continue
            cols=set(_table_cols(cur,table))
            if "command" not in cols:continue
            cur.execute(f"SELECT command FROM {table}")
            for (text,) in cur.fetchall():
                for k in _extract_keys_from_text(text):record(k)
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Notes'")
        if cur.fetchone():
            cols=set(_table_cols(cur,"Notes"))
            if "content" in cols:
                cur.execute("SELECT content FROM Notes")
                for (content,) in cur.fetchall():
                    if not content:continue
                    for cmd in _note_token_commands(content):
                        for k in _extract_keys_from_text(cmd):record(k)
                    for k in _extract_keys_from_text(content):record(k)
        return used
    except Exception as e:
        _log("[!]",f"Audit placeholder scan failed ({e})")
        return used
    finally:
        try:
            if con:con.close()
        except Exception:pass
def audit_keys():
    dbp=_db_path()
    store=Store()
    used=_all_placeholder_usage(dbp)
    unused=[]
    for k,v in store.values.items():
        if _kci(k) not in used:
            unused.append({"key":k,"priority":_clamp_u16(_priority_from(v)),"manual":_manual_from(v)})
    registered={_kci(k) for k in store.values.keys()}
    undefined=[{"key":u["key"],"count":u["count"]} for lk,u in used.items() if lk not in registered]
    unused.sort(key=lambda x:x["key"].lower())
    undefined.sort(key=lambda x:x["key"].lower())
    return {"unused":unused,"undefined":undefined}
def _parse_dt(s):
    try:
        if not s:return None
        v=str(s).replace("Z","+00:00")
        return datetime.fromisoformat(v)
    except Exception:
        return None
def _command_last_seen_map(dbp,include_unlinked=False):
    out={}
    if not dbp or not os.path.isfile(dbp):return out
    con=None
    try:
        con=_common_db.connect(dbp,timeout=5)
        cur=con.cursor()
        tables=("CommandsNotes","Commands") if include_unlinked else ("Commands",)
        for table in tables:
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",(table,))
            if not cur.fetchone():continue
            cols=set(_table_cols(cur,table))
            if "command" not in cols:continue
            time_col="updated_at" if "updated_at" in cols else ("created_at" if "created_at" in cols else "")
            if not time_col:continue
            q=f"SELECT command,{time_col} FROM {table} WHERE command LIKE '%{{%' AND command LIKE '%}}%'"
            cur.execute(q)
            for cmd,ts in cur.fetchall():
                if not cmd:continue
                dt=_parse_dt(ts)
                if not dt:continue
                keys=set(_extract_keys_from_text(cmd))
                for k in keys:
                    lk=_kci(k)
                    cur_dt=out.get(lk)
                    if cur_dt is None or dt>cur_dt:
                        out[lk]=dt
        return out
    except Exception as e:
        _log("[!]",f"Read last seen from DB failed ({e})")
        return out
    finally:
        try:
            if con:con.close()
        except Exception:pass
def _save_last_seen_map(dbp,last_seen_map):
    if not dbp or not os.path.isfile(dbp):return False
    if not isinstance(last_seen_map,dict):return False
    con=None
    try:
        con=_common_db.connect(dbp,timeout=5)
        cur=con.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS TargetKeyStats(key TEXT PRIMARY KEY,last_seen TEXT)")
        for k,dt in last_seen_map.items():
            if not k or not dt:continue
            cur.execute("INSERT INTO TargetKeyStats(key,last_seen) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET last_seen=excluded.last_seen",(str(k),dt.isoformat()))
        con.commit()
        return True
    except Exception as e:
        _log("[!]",f"Save last seen failed ({e})")
        try:
            if con:con.rollback()
        except Exception:pass
        return False
    finally:
        try:
            if con:con.close()
        except Exception:pass
def _delete_key_stats(dbp,key):
    if not dbp or not os.path.isfile(dbp):return False
    k=_norm(key)
    if not k:return False
    con=None
    try:
        con=_common_db.connect(dbp,timeout=5)
        cur=con.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS TargetKeyStats(key TEXT PRIMARY KEY,last_seen TEXT)")
        cur.execute("DELETE FROM TargetKeyStats WHERE lower(key)=?",(k.lower(),))
        con.commit()
        return bool(cur.rowcount)
    except Exception as e:
        _log("[!]",f"Delete key stats failed ({e})")
        try:
            if con:con.rollback()
        except Exception:pass
        return False
    finally:
        try:
            if con:con.close()
        except Exception:pass
def _rename_key_stats(dbp,old_key,new_key):
    if not dbp or not os.path.isfile(dbp):return False
    ok=_norm(old_key);nk=_norm(new_key)
    if not ok or not nk:return False
    con=None
    try:
        con=_common_db.connect(dbp,timeout=5)
        cur=con.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS TargetKeyStats(key TEXT PRIMARY KEY,last_seen TEXT)")
        cur.execute("SELECT last_seen FROM TargetKeyStats WHERE lower(key)=?",(ok.lower(),))
        r=cur.fetchone()
        if not r:return False
        last_seen=r[0]
        cur.execute("DELETE FROM TargetKeyStats WHERE lower(key)=?",(ok.lower(),))
        cur.execute("INSERT INTO TargetKeyStats(key,last_seen) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET last_seen=excluded.last_seen",(nk,last_seen))
        con.commit()
        return True
    except Exception as e:
        _log("[!]",f"Rename key stats failed ({e})")
        try:
            if con:con.rollback()
        except Exception:pass
        return False
    finally:
        try:
            if con:con.close()
        except Exception:pass
def _commands_for_key(dbp,key,include_unlinked=False):
    out=[]
    if not dbp or not os.path.isfile(dbp):return out
    lk=_kci(key)
    if not lk:return out
    con=None
    try:
        con=_common_db.connect(dbp,timeout=5)
        cur=con.cursor()
        tables=[("Commands","Linked")]
        if include_unlinked:tables.append(("CommandsNotes","Unlinked"))
        for table,label in tables:
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",(table,))
            if not cur.fetchone():continue
            cols=set(_table_cols(cur,table))
            if "command" not in cols:continue
            field="note_name" if "note_name" in cols else "''"
            q=f"SELECT {field},command FROM {table} WHERE lower(command) LIKE ?"
            cur.execute(q,(f"%{{{lk}}}%",))
            for note,cmd in cur.fetchall():
                if not cmd:continue
                out.append({"note":_norm(note) or "Unlinked","command":_clean_cmd_text(cmd),"src":label})
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Notes'")
        if cur.fetchone():
            cols=set(_table_cols(cur,"Notes"))
            if "content" in cols:
                field="note_name" if "note_name" in cols else "''"
                cur.execute(f"SELECT {field},content FROM Notes WHERE content LIKE '%cmdedit:%' OR content LIKE '%cmdcard:%' OR content LIKE '%cmddelete:%'")
                for note,content in cur.fetchall():
                    for cmd in _note_token_commands(content):
                        if lk in {_kci(x) for x in _extract_keys_from_text(cmd)}:
                            out.append({"note":_norm(note) or "Note","command":cmd,"src":"Note block"})
        return out
    except Exception:
        return out
    finally:
        try:
            if con:con.close()
        except Exception:pass
def _replace_placeholders(text,old_keys,new_key):
    if not text:return text
    out=str(text)
    for old in old_keys:
        if not old:continue
        pat=re.compile(r"(?<!\$)\{"+re.escape(old)+r"\}",re.I)
        out=pat.sub("{%s}"%new_key,out)
    return out
def _clean_cmd_text(text):
    if text is None:return ""
    raw=html.unescape(str(text))
    low=raw.lower()
    if "<span" in low or "<pre" in low or "<p" in low or "<div" in low or "<br" in low or "style=" in low or "-qt-" in low:
        raw=re.sub(r"<[^>]+>"," ",raw)
    raw=raw.replace("\xa0"," ")
    raw=re.sub(r"[ \t\r\f\v]+"," ",raw)
    raw=re.sub(r"\n\s+","\n",raw)
    raw=re.sub(r"\s+\n","\n",raw)
    return raw.strip()
def _decode_cmd_token(token):
    t=_norm(token)
    if not t:return {}
    pad="="*((4-len(t)%4)%4)
    try:
        raw=base64.urlsafe_b64decode(t+pad).decode("utf-8")
        d=json.loads(raw)
        return d if isinstance(d,dict) else {}
    except Exception:
        return {}
def _encode_cmd_token(data):
    if not isinstance(data,dict):return ""
    raw=json.dumps(data,ensure_ascii=False)
    b=base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")
    return b.rstrip("=")
def _note_token_commands(text):
    out=[];seen=set()
    for _,token in _TOKEN_RE.findall(str(text or "")):
        if token in seen:continue
        seen.add(token)
        d=_decode_cmd_token(token)
        cmd=_clean_cmd_text(d.get("command","") if isinstance(d,dict) else "")
        if cmd:out.append(cmd)
    return out
def _update_note_tokens(html_text,old_keys,new_key):
    if not html_text:return html_text
    def repl(m):
        prefix=m.group(1);token=m.group(2)
        d=_decode_cmd_token(token)
        if not d:return m.group(0)
        cmd=d.get("command","")
        new_cmd=_replace_placeholders(cmd,old_keys,new_key)
        if new_cmd==cmd:return m.group(0)
        d["command"]=new_cmd
        nt=_encode_cmd_token(d)
        if not nt:return m.group(0)
        return prefix+nt
    return _TOKEN_RE.sub(repl,html_text)
def _rename_placeholders_db(dbp,old_keys,new_key):
    res={"commands":0,"commands_notes":0,"notes":0}
    if not dbp or not os.path.isfile(dbp):return res
    if not isinstance(old_keys,(list,tuple,set)):old_keys=[old_keys]
    old_keys=[_norm(k) for k in old_keys if _norm(k)]
    if not old_keys:return res
    con=None
    try:
        con=_common_db.connect(dbp,timeout=5)
        cur=con.cursor()
        for table,label in (("Commands","commands"),("CommandsNotes","commands_notes")):
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",(table,))
            if not cur.fetchone():continue
            cols=set(_table_cols(cur,table))
            if "command" not in cols:continue
            q=f"SELECT id,command FROM {table} WHERE command LIKE '%{{%' AND command LIKE '%}}%'"
            cur.execute(q)
            for rid,cmd in cur.fetchall():
                new_cmd=_replace_placeholders(cmd,old_keys,new_key)
                if new_cmd!=cmd:
                    cur.execute(f"UPDATE {table} SET command=? WHERE id=?",(new_cmd,int(rid)))
                    res[label]+=1
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Notes'")
        if cur.fetchone():
            cols=set(_table_cols(cur,"Notes"))
            if "content" in cols:
                q="SELECT id,content FROM Notes WHERE (content LIKE '%{{%' AND content LIKE '%}}%') OR content LIKE '%cmdedit:%' OR content LIKE '%cmdcard:%' OR content LIKE '%cmddelete:%'"
                cur.execute(q)
                for rid,htmls in cur.fetchall():
                    new_html=_replace_placeholders(htmls,old_keys,new_key)
                    new_html=_update_note_tokens(new_html,old_keys,new_key)
                    if new_html!=htmls:
                        cur.execute("UPDATE Notes SET content=? WHERE id=?",(new_html,int(rid)))
                        res["notes"]+=1
        con.commit()
        return res
    except Exception as e:
        _log("[!]",f"Rename placeholders failed ({e})")
        try:
            if con:con.rollback()
        except Exception:pass
        return res
    finally:
        try:
            if con:con.close()
        except Exception:pass
def _priority_from(v):
    if isinstance(v,dict):
        return v.get("priority",v.get("value",0))
    return v
def _manual_from(v):
    if isinstance(v,dict):
        return bool(v.get("manual",False))
    return False
def _serialize_values(values):
    out={}
    if not isinstance(values,dict):return out
    for k,v in values.items():
        nk=_norm(k)
        if not nk:continue
        entry={"priority":_clamp_u16(_priority_from(v))}
        if _manual_from(v):entry["manual"]=True
        out[nk]=entry
    return out
def _read_json(p,default):
    if _doc_store.active(p):return _doc_store.read_json(p,default)
    try:
        if not os.path.isfile(p):return default
        with open(p,"r",encoding="utf-8") as f:
            v=json.load(f)
            return v if v is not None else default
    except Exception as e:
        _log("[!]",f"Read JSON failed: {p} ({e})")
        return default
def _write_json(p,obj):
    if _doc_store.active(p):return _doc_store.write_json(p,obj)
    try:
        os.makedirs(os.path.dirname(p),exist_ok=True)
        t=p+".tmp"
        with open(t,"w",encoding="utf-8") as f:json.dump(obj,f,ensure_ascii=False,indent=2)
        os.replace(t,p)
        return True
    except Exception as e:
        _log("[!]",f"Write JSON failed: {p} ({e})")
        try:
            if os.path.isfile(t):os.remove(t)
        except Exception:pass
        return False
def _pretty(obj):return json.dumps(obj,ensure_ascii=False,indent=2)
_ENGAGEMENT_STATUSES={"not_started","in_progress","compromised","reported"}
def _norm_engagement_status(s):
    v=_kci(s)
    return v if v in _ENGAGEMENT_STATUSES else "not_started"
_CIDR_RE=re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}/\d{1,2}$")
def is_cidr(value):
    return bool(_CIDR_RE.match(_norm(value)))
def expand_cidr(value,limit=1024):
    v=_norm(value)
    try:
        net=ipaddress.ip_network(v,strict=False)
    except Exception as e:
        raise ValueError(f"Invalid CIDR: {e}")
    hosts=list(net.hosts()) if net.num_addresses>2 else list(net)
    total=len(hosts)
    return {"network":str(net),"total":total,"hosts":[str(h) for h in hosts[:limit]],"truncated":total>limit}
# Called after a note/command save (ORIG _auto_add_target_values): registers new {KEY}s in the active profile. Never raises.
def auto_add_target_values(profile_id=None):
    try:return Store(profile_id).auto_added
    except Exception as e:
        _log("[!]",f"Auto-add target values failed ({e})")
        return 0
# Fingerprint of everything a Store is read from; when it changes a cached Store is stale.
def store_signature(profile_id=None):
    pid=profile_id or _profiles.active_profile_id()
    vp,tp=_paths(pid)
    dbp=_db_path() or ""
    out=[pid]
    for p in (vp,tp):out.append(_doc_store.signature(p))
    for p in (dbp,dbp+"-wal"):
        try:
            st=os.stat(p);out.append((st.st_mtime_ns,st.st_size))
        except OSError:out.append(None)
    return tuple(out)
class Store:
    def __init__(self,profile_id=None):
        self.profile_id=profile_id or _profiles.active_profile_id()
        self.values_path,self.targets_path=_paths(self.profile_id)
        self.values=self._load_values()
        self.targets=self._load_targets()
        self._auto_add_values_from_db()
        self._prune_targets_to_current_keys(save=True)
    def ordered_keys(self):
        items=[(k,_clamp_u16(_priority_from(v))) for k,v in self.values.items()]
        items.sort(key=lambda x:(x[1],x[0].lower()))
        return [k for k,_ in items]
    def _load_values(self):
        exists=_doc_store.exists(self.values_path)
        d=_read_json(self.values_path,{})
        out={}
        seen=set()
        dupe=False
        invalid=False
        def addk(k,val,manual=False):
            nonlocal dupe
            nonlocal invalid
            nk=_norm(k)
            if not nk:return
            if not _is_valid_key(nk):
                invalid=True
                return
            lk=_kci(nk)
            if lk in seen:
                dupe=True
                return
            seen.add(lk)
            out[nk]={"priority":_clamp_u16(val),"manual":bool(manual)}
        if isinstance(d,list):
            for it in d:
                if isinstance(it,str):addk(it,0)
                elif isinstance(it,dict):
                    k=it.get("key") if "key" in it else it.get("name")
                    addk(k,it.get("priority",it.get("value",0)),it.get("manual",False))
        elif isinstance(d,dict):
            for k,v in d.items():
                if isinstance(v,dict):addk(k,v.get("priority",v.get("value",0)),v.get("manual",False))
                elif isinstance(v,int):addk(k,v,False)
                else:addk(k,0,False)
        if not out:out={}
        changed=dupe or invalid or (not exists)
        for k,v in out.items():
            if not isinstance(v,dict) or "priority" not in v:
                out[k]={"priority":_clamp_u16(_priority_from(v)),"manual":False};changed=True
            else:
                vv=_clamp_u16(v.get("priority",0))
                if vv!=v.get("priority"):out[k]["priority"]=vv;changed=True
                mm=bool(v.get("manual",False))
                if v.get("manual",False)!=mm:out[k]["manual"]=mm;changed=True
        if changed or not (isinstance(d,dict) and all(isinstance(v,dict) and "priority" in v for v in d.values())):_write_json(self.values_path,_serialize_values(out))
        _log("[+]",f"Values loaded: {len(out)}")
        return out
    def _load_targets(self):
        d=_read_json(self.targets_path,[])
        if not isinstance(d,list):d=[]
        out=[]
        for t in d:
            if not isinstance(t,dict):continue
            name=_norm(t.get("name",""))
            if not name:continue
            st=_kci(t.get("status","not_used"))
            st="live" if st=="live" else "not_used"
            vals=t.get("values",{})
            if not isinstance(vals,dict):vals={}
            out.append({"id":t.get("id") or _sid(name),"name":name,"status":st,"engagement_status":_norm_engagement_status(t.get("engagement_status","not_started")),"values":{str(k):("" if v is None else str(v)) for k,v in vals.items()},"created":t.get("created") or _now(),"updated":t.get("updated") or _now()})
        _log("[+]",f"Targets loaded: {len(out)}")
        return out
    def _auto_add_values_from_db(self):
        self.auto_added=0
        keys=_extract_keys_from_db(_db_path())
        if not keys:return 0
        existing={_kci(k) for k in self.values.keys()}
        added=0
        for k in keys:
            lk=_kci(k)
            if lk in existing:continue
            self.values[k]={"priority":0,"manual":False}
            existing.add(lk)
            added+=1
        if added:
            if self.save_values():_log("[+]",f"Auto-added target values: {added}")
        self.auto_added=added
        return added
    def save_values(self):return _write_json(self.values_path,_serialize_values(self.values))
    def save_targets(self):
        for t in self.targets:
            v=t.get("values",{})
            if not isinstance(v,dict):v={}
            t["values"]={k:_norm(vv) for k,vv in v.items() if _norm(k) and _norm(vv)}
        return _write_json(self.targets_path,self.targets)
    def _sync_targets_keys(self,save=False):
        keys=self.ordered_keys()
        kset_ci={_kci(k) for k in keys}
        changed=False
        for t in self.targets:
            v=t.get("values",{})
            if not isinstance(v,dict):v={}
            nv={}
            for k in keys:nv[k]="" if v.get(k) is None else str(v.get(k,""))
            for k0,val0 in v.items():
                if _kci(k0) in kset_ci and k0 not in nv:
                    for kk in keys:
                        if _kci(kk)==_kci(k0):nv[kk]="" if val0 is None else str(val0);break
            if nv!=v:
                t["values"]=nv
                t["updated"]=_now()
                changed=True
        if save and changed:self.save_targets()
    def _rename_target_value_keys(self,old_keys,new_key):
        if not isinstance(old_keys,(list,tuple,set)):old_keys=[old_keys]
        old_ci={_kci(k) for k in old_keys if _norm(k)}
        nk=_norm(new_key)
        if not old_ci or not nk:return False
        changed=False
        for t in self.targets:
            vals=t.get("values",{})
            if not isinstance(vals,dict):vals={}
            nv={};moved=""
            for k,v in vals.items():
                if _kci(k) in old_ci:
                    vv=_norm(v)
                    if vv and not moved:moved=vv
                else:nv[k]=v
            target_key=None
            for k in nv.keys():
                if _kci(k)==_kci(nk):
                    target_key=k
                    break
            if moved:
                if target_key:
                    if not _norm(nv.get(target_key,"")):nv[target_key]=moved
                else:nv[nk]=moved
            if nv!=vals:
                t["values"]=nv
                t["updated"]=_now()
                changed=True
        return changed
    def add_key(self,k,val,manual=True):
        nk=_strip_braces(k)
        if not nk:return False,"Key is empty"
        if not _is_valid_key(nk):return False,"Invalid key"
        lk=_kci(nk)
        existing=next((x for x in self.values.keys() if _kci(x)==lk),None)
        if existing:return False,f"Key already exists as '{existing}' (case-insensitive) - reuse that name instead of creating a new one."
        self.values[nk]={"priority":_clamp_u16(val),"manual":bool(manual)}
        if not self.save_values():return False,"Save failed"
        return True,"Added"
    def sync_manual_flags(self,links_map=None,save=True):
        links=links_map if isinstance(links_map,dict) else _command_links_map(_db_path(),include_unlinked=True)
        changed=False
        for k,v in self.values.items():
            if isinstance(v,dict) and v.get("manual") and links.get(_kci(k),0)>0:
                v["manual"]=False
                changed=True
        if changed and save:self.save_values()
        return changed
    def bulk_rename(self,old_keys,new_key):
        nk=_strip_braces(new_key)
        if not nk:return False,"New key is empty"
        if not _is_valid_key(nk):return False,"Invalid key"
        if not isinstance(old_keys,(list,tuple,set)):return False,"No keys to merge"
        cleaned=[]
        seen=set()
        for k in old_keys:
            kk=_norm(k)
            if kk.startswith("{"):kk=kk[1:]
            if kk.endswith("}"):kk=kk[:-1]
            kk=_norm(kk)
            if not kk:continue
            lk=_kci(kk)
            if lk==_kci(nk):continue
            if lk in seen:continue
            seen.add(lk);cleaned.append(kk)
        if not cleaned:return False,"No keys to merge"
        res=_rename_placeholders_db(_db_path(),cleaned,nk)
        old_set={_kci(k) for k in cleaned}
        old_actuals=[k for k in list(self.values.keys()) if _kci(k) in old_set]
        new_actual=None
        for k in self.values.keys():
            if _kci(k)==_kci(nk):new_actual=k;break
        if new_actual:
            new_pr=_clamp_u16(_priority_from(self.values.get(new_actual)))
        elif old_actuals:
            new_pr=min(_clamp_u16(_priority_from(self.values.get(k))) for k in old_actuals)
        else:
            new_pr=0
        for k in old_actuals:self.values.pop(k,None)
        if new_actual and new_actual!=nk:self.values.pop(new_actual,None)
        self.values[nk]={"priority":new_pr,"manual":False}
        if self._rename_target_value_keys(cleaned,nk) and not self.save_targets():return False,"Save failed"
        for k in cleaned:_delete_key_stats(_db_path(),k)
        if new_actual and new_actual!=nk:_rename_key_stats(_db_path(),new_actual,nk)
        if not self.save_values():return False,"Save failed"
        self._prune_targets_to_current_keys(save=True)
        msg=f"Updated commands:{res.get('commands',0)} notes:{res.get('notes',0)}"
        if res.get("commands_notes",0):msg+=f" unlinked:{res.get('commands_notes',0)}"
        return True,msg
    def rename_key(self,old_key,new_key):
        ok_key=_strip_braces(old_key)
        nk=_strip_braces(new_key)
        if not ok_key:return False,"Key is empty"
        if not nk:return False,"New key is empty"
        if not _is_valid_key(nk):return False,"Invalid key"
        old_actual=None
        for k in self.values.keys():
            if _kci(k)==_kci(ok_key):old_actual=k;break
        if not old_actual:return False,"Key not found"
        new_actual=None
        for k in self.values.keys():
            if _kci(k)==_kci(nk):new_actual=k;break
        res=_rename_placeholders_db(_db_path(),old_actual,nk)
        _rename_key_stats(_db_path(),old_actual,nk)
        if new_actual and _kci(new_actual)==_kci(old_actual):
            if old_actual!=nk:
                val=self.values.pop(old_actual)
                self.values[nk]=val
        elif new_actual:
            self.values.pop(old_actual,None)
        else:
            val=self.values.pop(old_actual)
            self.values[nk]=val
        # Saved here: the next Store rebuild would otherwise prune the old key from Targets.json and drop every target's value for it.
        if self._rename_target_value_keys([old_actual],nk) and not self.save_targets():return False,"Save failed"
        if not self.save_values():return False,"Save failed"
        self._prune_targets_to_current_keys(save=True)
        msg=f"Updated commands:{res.get('commands',0)} notes:{res.get('notes',0)}"
        if res.get("commands_notes",0):
            msg+=f" unlinked:{res.get('commands_notes',0)}"
        return True,msg
    def remove_key(self,k):
        lk=_kci(k)
        found=None
        for kk in list(self.values.keys()):
            if _kci(kk)==lk:found=kk;break
        if not found:return False,"Key not found"
        links=_command_links_map(_db_path(),include_unlinked=True).get(lk,0)
        if links>0:return False,f"Key is used in {links} command(s). Remove it from commands first."
        self.values.pop(found,None)
        _delete_key_stats(_db_path(),found)
        if not self.save_values():return False,"Save failed"
        self._prune_targets_to_current_keys(save=True)
        return True,"Removed"
    def apply_values_json(self,raw):
        out={}
        def addk(k,val,manual=False):
            nk=_norm(k)
            if not nk:return
            lk=_kci(nk)
            for ex in list(out.keys()):
                if _kci(ex)==lk:return
            out[nk]={"priority":_clamp_u16(val),"manual":bool(manual)}
        if isinstance(raw,dict):
            for k,v in raw.items():
                if isinstance(v,dict):addk(k,v.get("priority",v.get("value",0)),v.get("manual",False))
                elif isinstance(v,int):addk(k,v,False)
                else:addk(k,0,False)
        elif isinstance(raw,list):
            for it in raw:
                if isinstance(it,dict):addk(it.get("key") if "key" in it else it.get("name"),it.get("priority",it.get("value",0)),it.get("manual",False))
                elif isinstance(it,str):addk(it,0,False)
        else:return False,"JSON must be an object or a list"
        if not out:return False,"At least one key is required"
        self.values=out
        if not self.save_values():return False,"Save failed"
        self._prune_targets_to_current_keys(save=True)
        return True,"Applied"
    def upsert_target(self,tid,name,status,vals,engagement_status=None):
        name=_norm(name)
        if not name:return False,"Target name is required"
        keys=self.ordered_keys()
        nv={}
        if isinstance(vals,dict):
            for k in keys:
                vv=_norm(vals.get(k,""))
                if vv:nv[k]=vv
            for k0,val0 in vals.items():
                for kk in keys:
                    if _kci(kk)==_kci(k0) and kk not in nv:
                        vv=_norm(val0)
                        if vv:nv[kk]=vv
                        break
        now=_now()
        if tid:
            for t in self.targets:
                if t["id"]==tid:
                    t["name"]=name
                    t["values"]=nv
                    if engagement_status is not None:t["engagement_status"]=_norm_engagement_status(engagement_status)
                    t["updated"]=now
                    return (True,"Updated") if self.save_targets() else (False,"Save failed")
        if _kci(name) in {_kci(t["name"]) for t in self.targets}:return False,"Target name already exists (case-insensitive)"
        self.targets.append({"id":_sid(name+now),"name":name,"status":"not_used","engagement_status":_norm_engagement_status(engagement_status),"values":nv,"created":now,"updated":now})
        return (True,"Created") if self.save_targets() else (False,"Save failed")
    def set_target_engagement_status(self,tid,status):
        now=_now()
        for t in self.targets:
            if t.get("id")==tid:
                t["engagement_status"]=_norm_engagement_status(status)
                t["updated"]=now
                return (True,"Updated") if self.save_targets() else (False,"Save failed")
        return False,"Not found"
    def delete_target(self,tid):
        found=None
        for t in self.targets:
            if t.get("id")==tid:found=dict(t);break
        if not found:return False,"Not found"
        ok,recycle_id=_recycle_bin.put_entry(_recycle_bin.TYPE_TARGET,_norm(found.get("name","")),{"target":found,"profile_id":self.profile_id},source="Targets",entity_key=_norm(found.get("id","")))
        if not ok:return False,f"Recycle Bin failed: {recycle_id}"
        before=len(self.targets)
        self.targets=[t for t in self.targets if t["id"]!=tid]
        if len(self.targets)==before:
            _recycle_bin.delete_entry(recycle_id)
            return False,"Not found"
        if self.save_targets():return True,"Moved to Recycle Bin"
        _recycle_bin.delete_entry(recycle_id)
        self.targets.append(found)
        return False,"Save failed"
    def set_live_target(self,tid):
        tid=_norm(tid)
        if not tid:return False,"Missing id"
        found=None
        for t in self.targets:
            if t.get("id")==tid:found=t;break
        if not found:return False,"Not found"
        was_live=_kci(found.get("status","not_used"))=="live"
        changed=False
        now=_now()
        if was_live:
            for t in self.targets:
                cur=_kci(t.get("status","not_used"))
                if cur!="not_used":
                    t["status"]="not_used"
                    t["updated"]=now
                    changed=True
            if not changed:return True,"No change"
            return (True,"Cleared") if self.save_targets() else (False,"Save failed")
        for t in self.targets:
            cur=_kci(t.get("status","not_used"))
            want="live" if t.get("id")==tid else "not_used"
            if cur!=want:
                t["status"]=want
                t["updated"]=now
                changed=True
        if not changed:return True,"No change"
        return (True,"Using") if self.save_targets() else (False,"Save failed")
    def _prune_targets_to_current_keys(self,save=False):
        keys_ci={_kci(k) for k in self.ordered_keys()}
        changed=False
        for t in self.targets:
            v=t.get("values",{})
            if not isinstance(v,dict):v={}
            nv={}
            for k,val in v.items():
                kk=_norm(k)
                vv=_norm(val)
                if not kk or not vv:continue
                if _kci(kk) in keys_ci:nv[kk]=vv
            if nv!=v:
                t["values"]=nv
                t["updated"]=_now()
                changed=True
        if save and changed:self.save_targets()
    def set_target_status(self,tid,status):
        st="live" if _kci(status)=="live" else "not_used"
        now=_now()
        for t in self.targets:
            if t.get("id")==tid:
                t["status"]=st
                t["updated"]=now
                return (True,"Updated") if self.save_targets() else (False,"Save failed")
        return False,"Not found"
