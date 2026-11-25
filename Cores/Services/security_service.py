import os,json,base64,hashlib,hmac,re,math,time,calendar,threading
from datetime import datetime,timezone,timedelta
from Cores import common_db as _common_db
from Cores import settings_lock as _settings_lock
from Cores.Update import health_check as _health_check
try:
    from Cores import crypto_store as _cs
    _HAS_CRYPTO=True
except Exception:
    _cs=None
    _HAS_CRYPTO=False
# Storage rebuild (phase 2). A PIN is a crypto_store key file (Data/Note_LOYA_V1.key): a random data key (DEK) wrapped with a key
# derived from the PIN by Argon2id (m=64 MiB, t=3, p=4). Verifying the PIN = unwrapping that file (AES-GCM tag, constant time);
# no PIN hash is kept in settings.json any more (SA-12). With encryption at rest on, the DEK (in memory only while unlocked)
# keys the SQLCipher database. The v1 scheme (PBKDF2-200k pin_hash in settings.json, Fernet .db.enc) is read only to migrate.
_PIN_ITERS=200000  # v1 PBKDF2 iterations, for verifying a legacy pin_hash once
_KDF=None  # crypto_store KDF parameters for new key files (None = crypto_store.default_kdf()); tests lower it
MIN_PIN=4
ENC_MIN_PIN=6  # encryption at rest makes the PIN the only thing between a copied Data/ folder and the notes
_SESSION_OK=False  # the PIN was entered this session (app lock); the DEK itself lives in common_db.session_key()
_MCP_RESUME_PORT=None
_UNLOCK_LOCK=threading.Lock()
_AUDIT_LOCK=threading.RLock()
# Wrong-PIN policy (ORIG exits after 3): the first 3 misses are free, then each miss waits 30 s, doubling up to 1 h. Persisted in settings.json, so a restart does not reset it.
LOCKOUT_FREE_ATTEMPTS=3
LOCKOUT_BASE_SECONDS=30
LOCKOUT_MAX_SECONDS=3600
AUDIT_EXPIRY_UNITS=("days","months","years")
AUDIT_EXPIRY_MAX=999
AUDIT_EXPIRY_DEFAULT={"enabled":False,"amount":90,"unit":"days"}
def _settings_path():return _health_check.settings_path()
def _db_path():return _common_db.db_path()
def _read_json(p,default):return _settings_lock.read_json(p,default)
def _write_json(p,obj):return _settings_lock.write_json(p,obj)
def _read_settings():return _read_json(_settings_path(),{})
def _write_settings(d):return _write_json(_settings_path(),d or {})
def _clean_pin(pin):return ("" if pin is None else str(pin)).strip()
def _int(v,default=0):
    try:return int(v or 0)
    except Exception:return default
def _float(v,default=0.0):
    try:return float(v or 0)
    except Exception:return default
def get_security_settings():
    d=_read_settings()
    s=d.get("security",{}) if isinstance(d,dict) else {}
    if not isinstance(s,dict):s={}
    return {"app_lock_enabled":bool(s.get("app_lock_enabled",False)),"pin_salt":s.get("pin_salt",""),"pin_hash":s.get("pin_hash",""),"enc_enabled":bool(s.get("enc_enabled",False)),"enc_salt":s.get("enc_salt",""),"enc_version":_int(s.get("enc_version",0)),"auto_lock_minutes":_int(s.get("auto_lock_minutes",0)),"failed_attempts":max(0,_int(s.get("failed_attempts",0))),"lockout_until":_float(s.get("lockout_until",0)),"audit_expiry":_clean_audit_expiry(s.get("audit_expiry"))}
def _audit_path():
    return os.path.join(_common_db.data_dir(),"security_audit.jsonl")
def _redact_detail(detail):
    # Every entry is redacted on the way in (commands, agent summaries, tool arguments): security_audit.jsonl is never a store of
    # passwords, tokens or hashes, whichever caller wrote it.
    text=str(detail or "")
    if not text:return ""
    try:
        from Cores.Services import terminal_service as _term
        text=_term.redact_secrets(text)[0]
    except Exception:pass
    return text
# Security lifecycle events always go to the plaintext security_audit.jsonl: several happen before any key exists (wrong PIN,
# lockout) and the log must stay readable while locked. Every other event (terminal commands, AI/agent tool calls, chain runs...)
# names targets and commands, so with encryption at rest on it is written to the AuditEvents table of the encrypted DB instead.
AUDIT_PLAINTEXT_EVENTS=frozenset(("unlock","lock","pin_change","pin_reset","pin_kdf_upgraded","encryption_toggle","app_lock_toggle","keyfile_invalid",
    "storage_migrated","storage_migration_failed","storage_migration_rolled_back","storage_migration_finished","storage_migration_recover",
    "audit_log_pruned","audit_expiry","mcp_paused","ext_agents_suspended","api_key_migrate","mcp_token_copied","ext_agent_key","cve_key","plain_export","backup_restored"))
def _audit_to_db(entry):
    """True when the entry was stored in the encrypted DB (encryption at rest on and unlocked)."""
    if entry["event"] in AUDIT_PLAINTEXT_EVENTS or not _common_db.encryption_configured():return False
    if _common_db.session_key() is None or _common_db.is_locked():
        entry["detail"]="(detail withheld: encryption at rest is on and the app was locked)"
        return False
    try:
        with _common_db.connection(timeout=5) as con:
            _common_db._create_storage_tables(con.cursor())
            con.execute("INSERT INTO AuditEvents(ts,event,detail,success) VALUES(?,?,?,?)",(entry["ts"],entry["event"],entry["detail"],1 if entry["success"] else 0))
        return True
    except Exception:
        entry["detail"]="(detail withheld: the encrypted audit table could not be written)"
        return False
def _db_audit_events(limit):
    if not _common_db.encryption_configured() or _common_db.session_key() is None or _common_db.is_locked():return []
    try:
        with _common_db.connection(timeout=5) as con:
            _common_db._create_storage_tables(con.cursor())
            rows=con.execute("SELECT ts,event,detail,success FROM AuditEvents ORDER BY ts DESC,id DESC LIMIT ?",(int(limit),)).fetchall()
        return [{"ts":r[0],"event":r[1],"detail":r[2] or "","success":bool(r[3])} for r in rows]
    except Exception:return []
def split_audit_lines(lines):
    """(plaintext_lines, entries_for_the_db) - used when encryption at rest is turned on."""
    keep=[];move=[]
    for line in lines:
        if not line.strip():continue
        try:e=json.loads(line)
        except Exception:keep.append(line if line.endswith("\n") else line+"\n");continue
        if isinstance(e,dict) and e.get("event") not in AUDIT_PLAINTEXT_EVENTS:move.append(e)
        else:keep.append(line if line.endswith("\n") else line+"\n")
    return keep,move
def log_audit_event(event,detail="",success=True):
    entry={"ts":datetime.now(timezone.utc).isoformat(),"event":event,"detail":_redact_detail(detail),"success":bool(success)}
    if _audit_to_db(entry):return entry  # when it returns False for a content event, entry carries a withheld detail instead
    try:
        p=_audit_path()
        os.makedirs(os.path.dirname(p),exist_ok=True)
        with _AUDIT_LOCK,open(p,"a",encoding="utf-8") as f:
            f.write(json.dumps(entry,ensure_ascii=False)+"\n")
    except Exception:pass
    return entry
def list_audit_events(limit=200):
    p=_audit_path()
    if not os.path.isfile(p):return []
    out=[]
    try:
        with _AUDIT_LOCK,open(p,"r",encoding="utf-8") as f:
            for line in f:
                line=line.strip()
                if not line:continue
                try:out.append(json.loads(line))
                except Exception:continue
    except Exception:pass
    try:limit=max(1,min(1000,int(limit)))
    except Exception:limit=200
    db=_db_audit_events(limit)
    if db:
        out=sorted(out+db,key=lambda e:str(e.get("ts","")))
    return list(reversed(out[-limit:]))
# A data restore never rolls the audit log back: the live log is kept and the backup's copy only adds the entries the live one lacks
# (same ts/event/detail/success = the same entry). Used by backup_restore for security_audit.jsonl and the AuditEvents table.
def _audit_key(e):
    return (str(e.get("ts","")),str(e.get("event","")),str(e.get("detail","") or ""),bool(e.get("success",True)))
def merge_audit_file(live_path,backup_path):
    """Merge the backup's security_audit.jsonl into the live one (atomic write); the live entries are never dropped."""
    def _lines(p):
        try:
            with open(p,"r",encoding="utf-8") as f:return [x for x in f.read().splitlines() if x.strip()]
        except (OSError,UnicodeDecodeError):return []
    with _AUDIT_LOCK:
        live=_lines(live_path);seen=set();rows=[]
        for i,line in enumerate(live+_lines(backup_path)):
            try:e=json.loads(line)
            except Exception:e=None
            k=_audit_key(e) if isinstance(e,dict) else ("raw",line.strip())
            if k in seen:continue
            seen.add(k);rows.append((str(e.get("ts","")) if isinstance(e,dict) else "",i,line.rstrip("\r\n")))
        rows.sort(key=lambda r:(r[0],r[1]))
        data=("".join(r[2]+"\n" for r in rows)).encode("utf-8")
        tmp=live_path+".merge.tmp"
        with open(tmp,"wb") as f:f.write(data)
        if os.name!="nt":
            try:os.chmod(tmp,0o600)
            except OSError:pass
        os.replace(tmp,live_path)
def read_audit_rows(con):
    """All AuditEvents rows of an open DB connection ([] when the table does not exist)."""
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='AuditEvents'").fetchone():return []
    return [{"ts":r[0],"event":r[1],"detail":r[2] or "","success":bool(r[3])} for r in con.execute("SELECT ts,event,detail,success FROM AuditEvents ORDER BY ts,id").fetchall()]
def merge_audit_rows(con,rows):
    """Insert the given AuditEvents rows the DB does not hold yet. Returns how many were added."""
    if not rows:return 0
    _common_db._create_storage_tables(con.cursor())
    have={_audit_key(e) for e in read_audit_rows(con)};n=0
    for e in rows:
        k=_audit_key(e)
        if k in have:continue
        have.add(k);n+=1
        con.execute("INSERT INTO AuditEvents(ts,event,detail,success) VALUES(?,?,?,?)",(k[0],k[1],k[2],1 if k[3] else 0))
    return n
def parse_audit_expiry_amount(v):
    """A whole number 1-999. Rejects bools, fractions and anything that is not plain digits."""
    msg=f"Enter a whole number from 1 to {AUDIT_EXPIRY_MAX}."
    if isinstance(v,bool):raise ValueError(msg)
    if isinstance(v,int):n=v
    elif isinstance(v,float):
        if not v.is_integer():raise ValueError(msg)
        n=int(v)
    elif isinstance(v,str) and re.fullmatch(r"[0-9]{1,4}",v.strip()):n=int(v.strip())
    else:raise ValueError(msg)
    if n<1 or n>AUDIT_EXPIRY_MAX:raise ValueError(msg)
    return n
def parse_audit_expiry_unit(v):
    u=str(v or "").strip().lower()
    if u not in AUDIT_EXPIRY_UNITS:raise ValueError("Unit must be days, months or years.")
    return u
def _clean_audit_expiry(raw):
    out=dict(AUDIT_EXPIRY_DEFAULT)
    if not isinstance(raw,dict):return out
    out["enabled"]=bool(raw.get("enabled",False))
    try:out["amount"]=parse_audit_expiry_amount(raw.get("amount"))
    except ValueError:pass
    try:out["unit"]=parse_audit_expiry_unit(raw.get("unit"))
    except ValueError:pass
    return out
def _sub_months(dt,months):
    y,m=divmod(dt.month-1-months,12)
    y+=dt.year;m+=1
    return dt.replace(year=y,month=m,day=min(dt.day,calendar.monthrange(y,m)[1]))
def audit_cutoff(amount,unit,now=None):
    """The oldest timestamp kept. Months and years step back on the calendar, clamping the day (Mar 31 - 1 month = Feb 28/29)."""
    amount=parse_audit_expiry_amount(amount);unit=parse_audit_expiry_unit(unit)
    now=now or datetime.now(timezone.utc)
    if unit=="days":return now-timedelta(days=amount)
    return _sub_months(now,amount if unit=="months" else amount*12)
def _parse_ts(ts):
    try:
        dt=datetime.fromisoformat(str(ts).replace("Z","+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:return None
def get_audit_expiry():return get_security_settings()["audit_expiry"]
def _expiry_text(amount,unit):return f"{amount} {unit[:-1] if amount==1 else unit}"
def prune_audit_log(now=None):
    """Drop audit entries older than the configured expiry. Disabled = never prune. Records the prune itself as 'audit_log_pruned'. Returns the count removed."""
    cfg=get_audit_expiry()
    if not cfg.get("enabled"):return 0
    cutoff=audit_cutoff(cfg["amount"],cfg["unit"],now)
    p=_audit_path()
    with _AUDIT_LOCK:
        if not os.path.isfile(p):return 0
        keep=[];removed=0
        try:
            with open(p,"r",encoding="utf-8") as f:lines=f.readlines()
        except Exception:return 0
        for line in lines:
            if not line.strip():continue
            try:ts=_parse_ts(json.loads(line).get("ts"))
            except Exception:ts=None
            if ts is not None and ts<cutoff:removed+=1
            else:keep.append(line if line.endswith("\n") else line+"\n")
        try:
            if _common_db.encryption_configured() and _common_db.session_key() is not None:
                with _common_db.connection(timeout=5) as con:
                    _common_db._create_storage_tables(con.cursor())
                    removed+=con.execute("DELETE FROM AuditEvents WHERE ts<?",(cutoff.isoformat(),)).rowcount or 0
        except Exception:pass
        if not removed:return 0
        t=p+".tmp"
        try:
            with open(t,"w",encoding="utf-8") as f:f.writelines(keep)
            os.replace(t,p)
        except Exception:
            try:
                if os.path.isfile(t):os.remove(t)
            except Exception:pass
            return 0
        log_audit_event("audit_log_pruned",f"{removed} entr{'y' if removed==1 else 'ies'} older than {_expiry_text(cfg['amount'],cfg['unit'])}",True)
    return removed
def set_audit_expiry(enabled,amount=None,unit=None):
    cur=get_audit_expiry();enabled=bool(enabled)
    if enabled:amount=parse_audit_expiry_amount(amount);unit=parse_audit_expiry_unit(unit)
    else:
        try:amount=parse_audit_expiry_amount(amount)
        except ValueError:amount=cur["amount"]
        try:unit=parse_audit_expiry_unit(unit)
        except ValueError:unit=cur["unit"]
    cfg={"enabled":enabled,"amount":amount,"unit":unit}
    if not save_security_settings({"audit_expiry":cfg}):raise ValueError("Could not save the audit log expiry.")
    if cfg!=cur:log_audit_event("audit_expiry",f"enabled: {_expiry_text(amount,unit)}" if enabled else "disabled",True)
    return dict(cfg,pruned=prune_audit_log())
def set_auto_lock_minutes(minutes):
    try:minutes=max(0,min(240,int(minutes)))
    except Exception:minutes=0
    save_security_settings({"auto_lock_minutes":minutes})
    return minutes
def _pause_mcp():
    global _MCP_RESUME_PORT
    try:
        from Cores.Services import mcp_local_service as _mcp
        if _mcp.is_running():
            _MCP_RESUME_PORT=_mcp.status().get("port")
            _mcp.stop_server()
            log_audit_event("mcp_paused","app locked",True)
    except Exception:pass
def _resume_mcp():
    global _MCP_RESUME_PORT
    port=_MCP_RESUME_PORT;_MCP_RESUME_PORT=None
    if not port:return
    def run():
        try:
            from Cores.Services import mcp_local_service as _mcp
            _mcp.start_server(port)
        except Exception:pass
    threading.Thread(target=run,name="loya-mcp-resume",daemon=True).start()
def _suspend_agents():
    """External agents (Claude Agent / OpenAI Codex) never keep running behind the lock screen: kill their process trees."""
    try:
        from Cores.Services import ext_agents_service as _ext
        n=_ext.suspend_all("app locked")
        if n:log_audit_event("ext_agents_suspended",f"{n} external agent run(s) stopped: app locked",True)
    except Exception:pass
    try:__import__("Cores.Services.flow_service",fromlist=["stop_all"]).stop_all("locked")  # chain diagram runs stop now, not at the engine's next lock check
    except Exception:pass
def lock_now(reason="manual"):
    cfg=get_security_settings()
    if not pin_is_set(cfg):
        log_audit_event("lock",f"{reason} (no PIN set)",False)
        return False
    # Block DB access and the bridge first; then drop the key. The DB file is always encrypted on disk, so there is nothing to
    # re-encrypt and no plaintext copy to remove.
    _common_db.set_locked(True)
    _pause_mcp()
    _suspend_agents()
    _forget_session()
    try:
        from Cores.Services import notes_service as _notes_svc
        _notes_svc.purge_open_attachment_copies()  # decrypted copies made for "Open attachment"
    except Exception:pass
    log_audit_event("lock",reason,True)
    return True
def _forget_session():
    global _SESSION_OK
    _SESSION_OK=False
    if _common_db.session_key() is not None:
        _checkpoint()
        _common_db.wait_idle(2.0)
    _common_db.clear_session_key()
def _checkpoint():
    """Fold the (encrypted) WAL into the main file so a closed DB is one self-contained file."""
    try:
        con=_common_db.connect(timeout=5)
        try:con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
        finally:con.close()
    except Exception:pass
# Linux/macOS: Data/ (notes DB, settings with the PIN hash, API-key ciphertext, audit log), Backups/ and Logs/ are private to the
# user. They are created with the process umask (often 0o002/0o022, i.e. readable - or with a copied 0o766 DB, writable - by other
# local users). Windows: the folders inherit the ACL of wherever the app was copied (under C:\ that includes Users /
# Authenticated Users); _harden_windows_acls() replaces that with an explicit ACL for the current user, SYSTEM and Administrators.
def _private_dirs(root=None):
    if root:return [os.path.join(root,n) for n in ("Data","Backups","Logs")]
    app=os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),"..",".."))
    return [_common_db.data_dir(),os.path.join(app,"Backups"),os.path.join(app,"Logs")]
_WIN_KEEP_SIDS=("*S-1-5-18","*S-1-5-32-544")  # SYSTEM, Administrators: kept so backup/AV tools and an admin can still reach the data
_WIN_NO_WINDOW=0x08000000
def _win_user_sid(run):
    r=run(["whoami","/user","/fo","csv","/nh"],capture_output=True,text=True,timeout=10,creationflags=_WIN_NO_WINDOW)
    if r.returncode!=0:return ""
    for line in (r.stdout or "").splitlines():
        cells=[c.strip().strip('"') for c in line.split('","')]
        sid=cells[-1].strip('"') if cells else ""
        if re.fullmatch(r"S-1-5-21(?:-\d+){4}|S-1-12-1(?:-\d+){4}|S-1-5-\d+(?:-\d+)*",sid):return sid
    return ""
def _win_unreadable_paths(top):
    unreadable=[]
    def note_error(error):
        if isinstance(error,PermissionError):unreadable.append(error.filename)
    for folder,dirs,files in os.walk(top,onerror=note_error):
        for name in files:
            path=os.path.join(folder,name)
            try:open(path,"rb").close()
            except PermissionError:unreadable.append(path)
            except OSError:pass
    return unreadable
def _win_repair_unreadable(top,run,log):
    unreadable=_win_unreadable_paths(top)
    if not unreadable:return 0
    result=run(["icacls",os.path.join(top,"*"),"/reset","/T","/C","/Q"],capture_output=True,text=True,timeout=300,creationflags=_WIN_NO_WINDOW)
    if result.returncode==0:
        log(f"[sec] {top}: reset the ACL of {len(unreadable)} unreadable path(s) to inherit from the folder")
        return 1
    log(f"[sec] icacls could not reset {top} (exit {result.returncode}): {(result.stderr or result.stdout or '').strip()[:200]}")
    return 0
def _harden_windows_acls(dirs,run=None,log=None):
    """Windows counterpart of the chmod above. Only a folder that still inherits its ACL (an "(I)" entry in icacls output) is
    changed: inheritance is removed and full control is granted to the current user (by SID), SYSTEM and Administrators, in one
    icacls call (argv list, no shell). The grant happens in the same call as the removal, the user's SID must be known first, and
    any failure only writes a log line - so the user can never be locked out. Already-hardened folders are left alone."""
    import subprocess
    run=run or subprocess.run
    log=log or (lambda m:None)
    changed=0
    try:sid=_win_user_sid(run)
    except Exception as e:
        log(f"[sec] Windows ACL hardening skipped: could not read the user SID ({e})");return 0
    if not sid:
        log("[sec] Windows ACL hardening skipped: could not read the user SID");return 0
    for top in dirs:
        if not os.path.isdir(top):continue
        try:
            cur=run(["icacls",top],capture_output=True,text=True,timeout=20,creationflags=_WIN_NO_WINDOW)
            if cur.returncode!=0:log(f"[sec] icacls could not read {top}: {(cur.stderr or cur.stdout or '').strip()[:200]}");continue
            if "(I)" not in (cur.stdout or ""):
                changed+=_win_repair_unreadable(top,run,log)
                continue
            argv=["icacls",top,"/inheritance:r","/grant:r",f"*{sid}:(OI)(CI)F"]+[a for k in _WIN_KEEP_SIDS for a in ("/grant:r",f"{k}:(OI)(CI)F")]+["/C","/Q"]
            r=run(argv,capture_output=True,text=True,timeout=300,creationflags=_WIN_NO_WINDOW)
            if r.returncode==0:changed+=1;log(f"[sec] {top}: owner-only ACL applied")
            else:log(f"[sec] icacls could not restrict {top} (exit {r.returncode}): {(r.stderr or r.stdout or '').strip()[:200]}")
        except Exception as e:
            log(f"[sec] Windows ACL hardening of {top} failed: {e}")
    return changed
def harden_data_permissions(root=None):
    """chmod the private folders to 0700 and every file in them to 0600 (executable bits are never needed there); on Windows,
    an owner-only ACL instead. Returns the number of paths changed."""
    if os.name=="nt":
        import logging
        return _harden_windows_acls(_private_dirs(root),log=logging.getLogger("Note").info)
    changed=0
    def fix(path,mode):
        nonlocal changed
        try:
            st=os.lstat(path)
            if os.path.islink(path) or st.st_uid!=os.getuid():return
            if (st.st_mode&0o777)!=mode:os.chmod(path,mode);changed+=1
        except OSError:pass
    for top in _private_dirs(root):
        if not os.path.isdir(top) or os.path.islink(top):continue
        fix(top,0o700)
        for d,dirs,files in os.walk(top):
            for n in dirs:fix(os.path.join(d,n),0o700)
            for n in files:fix(os.path.join(d,n),0o600)
    return changed
def sync_lock_state():
    """Call once at startup: finish or roll back an interrupted storage migration, then lock DB access until the PIN is entered
    when app lock or encryption is on."""
    try:harden_data_permissions()
    except Exception:pass
    try:
        from Cores import storage_migration as _mig
        _mig.recover()
    except Exception as e:
        log_audit_event("storage_migration_recover",f"{type(e).__name__}: {e}",False)
    _common_db.set_locked(needs_unlock() and not _SESSION_OK)
    return _common_db.is_locked()
def save_security_settings(cfg):
    def mutate(d):
        cur=d.get("security",{}) if isinstance(d.get("security",{}),dict) else {}
        cur.update(cfg or {})
        d["security"]=cur
    return _settings_lock.update_json(_settings_path(),mutate)
# ---------------------------------------------------------------- PIN: key file (v2) or legacy v1 hash
def _key_path():return _common_db.key_path()
def _has_keyfile():return os.path.isfile(_key_path())
def _legacy_pin_set(cfg):return bool(cfg.get("pin_salt")) and bool(cfg.get("pin_hash"))
def pin_is_set(cfg=None):
    c=cfg or get_security_settings()
    return _has_keyfile() or _legacy_pin_set(c)
def _legacy_verify(pin,cfg):
    try:
        salt=base64.b64decode(cfg.get("pin_salt","") or "")
        expect=base64.b64decode(cfg.get("pin_hash","") or "")
        if not salt or not expect:return False
        dk=hashlib.pbkdf2_hmac("sha256",pin.encode("utf-8"),salt,_PIN_ITERS)
        return hmac.compare_digest(dk,expect)
    except Exception:return False
def _check_pin(pin,cfg):
    """("v2", DataKey) | ("legacy", None) | (None, None). The caller owns (and must wipe) the DataKey."""
    pin=_clean_pin(pin)
    if not pin:return None,None
    if _has_keyfile():
        if not _HAS_CRYPTO:return None,None
        try:return "v2",_cs.unwrap(pin,_key_path())
        except _cs.WrongPin:return None,None
        except _cs.KeyFileError as e:
            log_audit_event("keyfile_invalid",str(e),False)
            return None,None
    if _legacy_pin_set(cfg) and _legacy_verify(pin,cfg):return "legacy",None
    return None,None
def verify_pin(pin,cfg=None):
    kind,dek=_check_pin(pin,cfg or get_security_settings())
    if dek is not None:dek.wipe()
    return kind is not None
def _new_keyfile(pin):
    """A fresh DEK wrapped by this PIN, written atomically; the v1 hash is removed from settings.json."""
    dek,_kf=_cs.create_keyfile(pin,_key_path(),kdf=_KDF)
    try:
        if os.name!="nt":os.chmod(_key_path(),0o600)
    except OSError:pass
    save_security_settings({"pin_salt":"","pin_hash":""})
    return dek
def _upgrade_kdf(pin):
    """Raise the key file's KDF cost (or leave the scrypt fallback) once Argon2id with the current defaults is available."""
    try:
        if _KDF is None and _cs.needs_upgrade(_key_path()):
            _cs.rewrap(pin,None,_key_path())
            log_audit_event("pin_kdf_upgraded",json.dumps({k:v for k,v in _cs.load_keyfile(_key_path())["kdf"].items() if k!="salt"}),True)
    except Exception as e:
        log_audit_event("pin_kdf_upgraded",f"{type(e).__name__}: {e}",False)
def hash_pin(pin):
    """v1 helper kept for tools/tests that build legacy settings; new PINs never use it."""
    salt=os.urandom(16)
    dk=hashlib.pbkdf2_hmac("sha256",pin.encode("utf-8"),salt,_PIN_ITERS)
    return base64.b64encode(salt).decode("ascii"),base64.b64encode(dk).decode("ascii")
def clear_session_pin():
    """Forget this session's unlock (kept name; there is no PIN in memory any more)."""
    _forget_session()
def _enc_path():return _db_path()+".enc"
def encrypted_file_exists():
    try:
        from Cores import db_driver as _drv
        return _drv.file_kind(_db_path())=="encrypted"
    except Exception:return False
def _enc_v2(cfg):
    try:return bool(cfg.get("enc_enabled")) and int(cfg.get("enc_version") or 0)>=2
    except Exception:return False
def encrypt_on_exit():
    """At exit: fold the WAL into the encrypted file and drop the key. Nothing is ever decrypted to disk, so a crash or a kill
    at any moment leaves only ciphertext (the Reporting-QA finding of a plaintext DB beside the .enc cannot happen)."""
    cfg=get_security_settings()
    if not cfg.get("enc_enabled"):return True,"Encryption not enabled."
    had=_common_db.session_key() is not None
    _forget_session()
    return True,("Closed." if had else "Locked.")
def _lock_requested(cfg):
    return pin_is_set(cfg) and (bool(cfg.get("app_lock_enabled")) or bool(cfg.get("enc_enabled")))
def needs_unlock():
    cfg=get_security_settings()
    locked=bool(cfg.get("app_lock_enabled")) and pin_is_set(cfg)
    encrypted=bool(cfg.get("enc_enabled")) and pin_is_set(cfg)
    return locked or encrypted
def is_locked():
    return _common_db.is_locked() or (needs_unlock() and not _SESSION_OK)
def lockout_delay(failed):
    if failed<LOCKOUT_FREE_ATTEMPTS:return 0
    return min(LOCKOUT_MAX_SECONDS,LOCKOUT_BASE_SECONDS*(2**min(failed-LOCKOUT_FREE_ATTEMPTS,20)))
def lockout_remaining(now=None,cfg=None):
    cfg=cfg or get_security_settings()
    now=time.time() if now is None else now
    rem=cfg.get("lockout_until",0)-now
    if rem>LOCKOUT_MAX_SECONDS:
        # The clock went backwards: cap the wait instead of locking out for the size of the jump.
        save_security_settings({"lockout_until":now+LOCKOUT_MAX_SECONDS});rem=LOCKOUT_MAX_SECONDS
    return max(0,int(math.ceil(rem)))
def _fmt_wait(sec):
    sec=int(sec)
    if sec<60:return f"{sec} second{'s' if sec!=1 else ''}"
    m=int(math.ceil(sec/60))
    return f"{m} minute{'s' if m!=1 else ''}"
def _mark_unlocked():
    _common_db.set_locked(False)
    _resume_mcp()
def _exclusive(fn):
    """Run fn with the DB to itself: lock new access, wait for open connections, then restore the previous lock state."""
    prev=_common_db.is_locked()
    _common_db.set_locked(True)
    try:
        _common_db.wait_idle(10.0)
        return fn()
    finally:
        _common_db.set_locked(prev)
def _adopt_legacy_keys(fernet):
    """v1 API keys (Fernet ciphertext in settings.json) move into the Secrets table of the now-encrypted DB."""
    def dec(tok):return fernet.decrypt(str(tok).encode("ascii")).decode("utf-8")
    for mod,fn in (("ext_agents_service","adopt_legacy_keys"),("cve_service","adopt_legacy_key")):
        try:getattr(__import__(f"Cores.Services.{mod}",fromlist=[fn]),fn)(dec)
        except Exception as e:log_audit_event("api_key_migrate",f"{mod}: {type(e).__name__}",False)
def _open_encrypted(dek):
    """Make dek the session key after checking it really opens the DB (a wrong key must never reach the services)."""
    from Cores import db_driver as _drv
    dbp=_db_path()
    if _drv.file_kind(dbp)=="encrypted":
        con=_drv.connect(dbp,key=dek,timeout=10)
        con.close()
    _common_db.set_session_key(dek)
def unlock(pin,now=None):
    global _SESSION_OK
    with _UNLOCK_LOCK:
        cfg=get_security_settings()
        if not _lock_requested(cfg) and not (_common_db.is_locked() and pin_is_set(cfg)):
            _mark_unlocked()
            return True,"Not required."
        if not pin_is_set(cfg):return False,"PIN is not set."
        if not _HAS_CRYPTO:return False,"cryptography is not installed."
        now=time.time() if now is None else now
        wait=lockout_remaining(now,cfg)
        if wait:
            log_audit_event("unlock","refused: wrong-PIN delay active",False)
            return False,f"Too many wrong PINs. Try again in {_fmt_wait(wait)}."
        pin=_clean_pin(pin)
        kind,dek=_check_pin(pin,cfg)
        if kind is None:
            failed=cfg.get("failed_attempts",0)+1;delay=lockout_delay(failed)
            save_security_settings({"failed_attempts":failed,"lockout_until":now+delay if delay else 0})
            log_audit_event("unlock",f"pin (wrong attempt {failed})",False)
            if delay:return False,f"Wrong PIN. Too many wrong PINs. Try again in {_fmt_wait(delay)}."
            left=LOCKOUT_FREE_ATTEMPTS-failed
            return False,f"Wrong PIN. {left} more attempt{'s' if left!=1 else ''} before a delay." if left>0 else "Wrong PIN."
        if cfg.get("failed_attempts") or cfg.get("lockout_until"):save_security_settings({"failed_attempts":0,"lockout_until":0})
        try:
            if kind=="legacy":
                dek=_new_keyfile(pin)
                log_audit_event("pin_kdf_upgraded","v1 PBKDF2 hash replaced by an Argon2id key file",True)
            else:
                _upgrade_kdf(pin)
            from Cores import storage_migration as _mig
            _mig.recover()
            if cfg.get("enc_enabled"):
                if not _enc_v2(cfg):
                    # v1 Fernet copy: one-time migration to SQLCipher (backup first, journalled, rolled back on failure).
                    legacy={"pin":pin,"enc_salt":cfg.get("enc_salt","")}
                    try:
                        _exclusive(lambda:_mig.enable(dek,_cs.load_keyfile(_key_path()),legacy=legacy))
                    except Exception as e:
                        log_audit_event("unlock",f"storage migration failed: {e}",False)
                        dek.wipe()
                        return False,f"Could not upgrade the encrypted database: {e}"
                    _open_encrypted(dek)
                    try:
                        if cfg.get("enc_salt"):_adopt_legacy_keys(_mig.legacy_fernet(pin,cfg.get("enc_salt")))
                    finally:
                        save_security_settings({"enc_salt":""})
                else:
                    try:_open_encrypted(dek)
                    except Exception as e:
                        dek.wipe()
                        log_audit_event("unlock",f"database key check failed: {type(e).__name__}",False)
                        return False,"The PIN is right, but the database does not open with its key. Restore a backup."
            else:
                dek.wipe()
        except Exception:
            if dek is not None and _common_db.session_key() is not dek:dek.wipe()
            raise
        _SESSION_OK=True
        _mark_unlocked()
        log_audit_event("unlock","pin",True)
        return True,"Unlocked."
def _pin_rule(pin,cfg):
    if not pin:return "PIN is required."
    if len(pin)<MIN_PIN:return f"PIN should be at least {MIN_PIN} characters."
    if cfg.get("enc_enabled") and len(pin)<ENC_MIN_PIN:return f"With encryption at rest on, the PIN should be at least {ENC_MIN_PIN} characters."
    return ""
def set_pin(new_pin,current_pin=None):
    global _SESSION_OK
    new_pin=_clean_pin(new_pin)
    cfg=get_security_settings()
    bad=_pin_rule(new_pin,cfg)
    if bad:return False,bad
    if not _HAS_CRYPTO:return False,"cryptography is not installed."
    if pin_is_set(cfg):
        cur=_clean_pin(current_pin)
        kind,dek=_check_pin(cur,cfg)
        if kind is None:
            log_audit_event("pin_change","",False)
            return False,"Wrong current PIN."
        if kind=="v2":
            dek.wipe()
            # Only the 48-byte wrap changes; the data key and every encrypted byte stay as they are.
            _cs.rewrap(cur,new_pin,_key_path(),kdf=_KDF)
        else:
            if cfg.get("enc_enabled") and not _enc_v2(cfg):return False,"Unlock once with the current PIN to upgrade the encrypted database first."
            _new_keyfile(new_pin).wipe()
    else:
        _new_keyfile(new_pin).wipe()
    _SESSION_OK=True
    log_audit_event("pin_change","",True)
    return True,"PIN updated."
def set_app_lock(enabled,new_pin=None):
    global _SESSION_OK
    cfg=get_security_settings()
    if enabled:
        if not pin_is_set(cfg):
            np=_clean_pin(new_pin)
            if not np:return False,"PIN is required to enable app lock."
            bad=_pin_rule(np,cfg)
            if bad:return False,bad
            if not _HAS_CRYPTO:return False,"cryptography is not installed."
            _new_keyfile(np).wipe()
            _SESSION_OK=True
        save_security_settings({"app_lock_enabled":True})
        log_audit_event("app_lock_toggle","enabled",True)
        return True,"App lock enabled."
    # Turning the lock off is persistent, so it needs the current PIN typed now, as turning encryption off does (S20).
    # new_pin carries that PIN here; the session's unlock is never accepted instead.
    if pin_is_set(cfg) and cfg.get("app_lock_enabled") and not _verify_typed_pin(new_pin,cfg,"app_lock_toggle"):
        return False,"Wrong PIN."
    save_security_settings({"app_lock_enabled":False})
    log_audit_event("app_lock_toggle","disabled",True)
    return True,"App lock disabled."
def _verify_typed_pin(pin,cfg,event):
    # S20: the dialog asks for the PIN, so check what was typed - never fall back to this session's unlock.
    typed=_clean_pin(pin)
    if not typed or not verify_pin(typed,cfg):
        log_audit_event(event,"wrong PIN",False)
        return None
    return typed
PLAIN_EXPORT_WARNING="This export is NOT encrypted: anyone who gets the file can read everything in it."
def plain_export_allowed(pin,what,log_success=True):
    """Encryption at rest on: writing a plaintext copy of the data needs the PIN typed now (S20 - never this session's unlock),
    checked against the key file, and is audited. Off: nothing to check. Returns (ok, message)."""
    if not _common_db.encryption_configured():return True,""
    typed=_clean_pin(pin)
    if not typed:return False,PLAIN_EXPORT_WARNING+" Enter your PIN to confirm."
    if not verify_pin(typed):
        log_audit_event("plain_export",f"{what}: refused (wrong PIN)",False)
        return False,"Wrong PIN. The unencrypted export was not written."
    if log_success:log_audit_event("plain_export",f"{what}: unencrypted export confirmed with the PIN",True)
    return True,""
def set_encryption(enabled,pin=None,new_pin=None):
    global _SESSION_OK
    cfg=get_security_settings()
    from Cores import storage_migration as _mig
    from Cores import db_driver as _drv
    if enabled:
        if not _HAS_CRYPTO:return False,"cryptography is not installed."
        if not _drv.has_sqlcipher():return False,"sqlcipher3 is not installed, so the database cannot be encrypted."
        if _enc_v2(cfg) and _drv.file_kind(_db_path())!="plain":return True,"Encryption is already on."
        if not pin_is_set(cfg):
            np=_clean_pin(new_pin)
            if not np:return False,"PIN is required for encryption."
            bad=_pin_rule(np,dict(cfg,enc_enabled=True))
            if bad:return False,bad
            dek=_new_keyfile(np)
        else:
            typed=_clean_pin(pin)
            kind,dek=_check_pin(typed,cfg)
            if kind is None:
                log_audit_event("encryption_toggle","wrong PIN",False)
                return False,"Wrong PIN."
            if len(typed)<ENC_MIN_PIN:
                if dek is not None:dek.wipe()
                return False,f"Choose a PIN of at least {ENC_MIN_PIN} characters (Change PIN) before turning encryption on."
            if kind=="legacy":dek=_new_keyfile(typed)
        try:
            _mig.recover()
            report=_exclusive(lambda:_mig.enable(dek,_cs.load_keyfile(_key_path())))
        except Exception as e:
            dek.wipe()
            log_audit_event("encryption_toggle",f"enable failed: {e}",False)
            return False,f"Encryption could not be turned on: {e}"
        _open_encrypted(dek)
        _SESSION_OK=True
        log_audit_event("encryption_toggle","enabled",True)
        return True,"Encryption enabled. A backup of the previous data is in Backups/ ("+os.path.basename(report.get("backup",""))+")."
    if not cfg.get("enc_enabled"):return True,"Encryption is already off."
    typed=_clean_pin(pin)
    kind,dek=_check_pin(typed,cfg)
    if kind is None:
        log_audit_event("encryption_toggle","wrong PIN",False)
        return False,"Wrong PIN."
    if kind!="v2":
        return False,"Unlock once with the current PIN to upgrade the encrypted database first."
    try:
        _mig.recover()
        _exclusive(lambda:_mig.disable(dek))
    except Exception as e:
        dek.wipe()
        log_audit_event("encryption_toggle",f"disable failed: {e}",False)
        return False,f"Encryption could not be turned off: {e}"
    dek.wipe()
    _common_db.clear_session_key()
    _drop_encrypted_key_refs()
    _SESSION_OK=True
    log_audit_event("encryption_toggle","disabled",True)
    return True,"Encryption disabled."
def _drop_encrypted_key_refs():
    """API keys that lived in the Secrets table are gone with encryption off: the operator enters them again."""
    try:
        from Cores.Services import ext_agents_service as _ext
        for p in _ext.PROVIDERS:
            if _ext._cfg(p).get("key_store")=="encrypted":
                _ext._save_cfg(p,lambda cur:cur.update(key_store="",key_hint="",key_enc=""))
                _ext._session_keys.pop(p,None) if hasattr(_ext,"_session_keys") else None
    except Exception:pass
    try:
        from Cores.Services import cve_service as _cve
        if _cve._stored().get("key_store")=="encrypted":_cve._save_private(key_store="",key_hint="",key_enc="")
    except Exception:pass
def reset_pin():
    """resetPIN.py: forget the PIN. Refused while encryption at rest is on: without the PIN the data key cannot be recovered,
    so a reset would only make the encrypted data unreadable."""
    cfg=get_security_settings()
    dbp=_db_path()
    try:
        from Cores import db_driver as _drv
        encrypted=_drv.file_kind(dbp)=="encrypted"
    except Exception:encrypted=False
    if cfg.get("enc_enabled") or encrypted or os.path.isfile(_enc_path()):
        return False,"PIN reset refused: the database is encrypted with this PIN. Without the PIN it cannot be decrypted; restore a backup taken with a PIN you know, or turn encryption off first (it needs the PIN)."
    updates={"app_lock_enabled":False,"pin_salt":"","pin_hash":"","failed_attempts":0,"lockout_until":0,"enc_salt":""}
    _forget_session()
    try:
        if _has_keyfile():os.remove(_key_path())
    except Exception as e:
        return False,f"PIN reset failed while removing the key file: {e}"
    if not save_security_settings(updates):return False,"PIN reset failed while writing settings."
    log_audit_event("pin_reset","",True)
    return True,"PIN reset complete."
