import json,logging,os,shutil,tempfile,time,zipfile
from logging.handlers import RotatingFileHandler
from pathlib import Path
from . import update_helpers as _helpers
from . import update_service as _service
_DATA_LOGGER=None
_DOWNGRADE_LOGGER=None
_SKIP_DIR_NAMES={"Data","Logs","Backups",".venv_windows",".venv_linux","__pycache__",".git",".pytest_cache",".mypy_cache",".ruff_cache",".idea",".vs",".vscode"}
_SKIP_FILE_NAMES={"Thumbs.db",".DS_Store"}
_SKIP_FILE_SUFFIXES={".pyc",".pyo",".tmp",".temp",".log",".bak",".old",".swp",".swo"}
def _utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())
def _stamp():
    return time.strftime("%Y-%m-%d_%H-%M-%S",time.gmtime())
def _root_dir(root_dir=None):
    p=Path(root_dir) if root_dir else _helpers.root_dir()
    return p.resolve()
def _data_dir(root_dir=None):
    if not root_dir:
        # This installation: the Data/ the app actually uses (common_db), so a moved/isolated Data/ is the one backed up.
        try:
            from Cores import common_db as _cdb
            return Path(_cdb.data_dir()).resolve()
        except Exception:pass
    return _root_dir(root_dir).joinpath("Data")
def _backups_dir(root_dir=None,out_dir=None):
    if not out_dir and not root_dir:
        # This installation: common_db.backups_dir() (overridable, and never the app's Backups/ for a moved/isolated Data/).
        try:
            from Cores import common_db as _cdb
            out_dir=_cdb.backups_dir()
        except Exception:pass
    p=Path(out_dir) if out_dir else _root_dir(root_dir).joinpath("Backups")
    p.mkdir(parents=True,exist_ok=True)
    return p.resolve()
def old_versions_dir(root_dir=None,out_dir=None):
    p=Path(out_dir) if out_dir else _root_dir(root_dir).joinpath("Cores","Update","OldVersions")
    p.mkdir(parents=True,exist_ok=True)
    return p.resolve()
def _logs_dir(root_dir=None):
    p=_root_dir(root_dir).joinpath("Logs")
    p.mkdir(parents=True,exist_ok=True)
    return p.resolve()
def _safe_name(text,fallback):
    raw="".join(ch if ch.isalnum() or ch in ("-","_",".") else "_" for ch in str(text or "").strip())
    raw=raw.strip("._")
    return raw or fallback
def _within_root(path,root):
    try:return os.path.commonpath([str(Path(path).resolve()),str(Path(root).resolve())])==str(Path(root).resolve())
    except Exception:return False
def _skip_dir(name):
    return str(name or "").strip() in _SKIP_DIR_NAMES
def _skip_file(name):
    base=str(name or "").strip()
    if not base:return True
    if base in _SKIP_FILE_NAMES:return True
    if base.endswith("~"):return True
    low=base.lower()
    return any(low.endswith(sfx) for sfx in _SKIP_FILE_SUFFIXES)
def _should_skip_rel(rel_path):
    rel=str(rel_path or "").replace("\\","/").strip("/")
    if not rel:return False
    parts=[p for p in rel.split("/") if p]
    if any(_skip_dir(p) for p in parts):return True
    if parts[:3]==["Cores","Update","OldVersions"]:return True
    return _skip_file(parts[-1])
def _iter_project_files(root_dir=None):
    root=_root_dir(root_dir)
    for base,dirs,files in os.walk(root):
        rel_dir=os.path.relpath(base,root)
        if rel_dir==".":
            rel_dir=""
        dirs[:]=[d for d in dirs if not _should_skip_rel(os.path.join(rel_dir,d))]
        for fn in files:
            rel=os.path.join(rel_dir,fn) if rel_dir else fn
            if _should_skip_rel(rel):continue
            src=root.joinpath(rel)
            if src.is_file():yield src,rel.replace("\\","/")
def _logger(name,path):
    lg=logging.getLogger(name);lg.setLevel(logging.INFO)
    fp=os.path.abspath(str(path))
    for h in list(lg.handlers):
        try:
            if getattr(h,"baseFilename","") and os.path.abspath(h.baseFilename)==fp:return lg
        except Exception:
            pass
    h=RotatingFileHandler(fp,maxBytes=1024*1024,backupCount=5,encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(message)s","%Y-%m-%d %H:%M:%S"))
    lg.addHandler(h);return lg
def _update_log(root_dir=None):
    global _DATA_LOGGER
    if _DATA_LOGGER is None:_DATA_LOGGER=_logger("UpdateService",_logs_dir(root_dir).joinpath("Update_log.log"))
    return _DATA_LOGGER
def _downgrade_log(root_dir=None):
    global _DOWNGRADE_LOGGER
    if _DOWNGRADE_LOGGER is None:_DOWNGRADE_LOGGER=_logger("DowngradeService",_logs_dir(root_dir).joinpath("Downgrade_log.log"))
    return _DOWNGRADE_LOGGER
def _log_update(tag,msg,root_dir=None):
    try:_update_log(root_dir).info(f"{tag} {msg}")
    except Exception:pass
def _log_downgrade(tag,msg,root_dir=None):
    try:_downgrade_log(root_dir).info(f"{tag} {msg}")
    except Exception:pass
_SKIP_BACKUP_DATA_DIR="cve_index"
_SKIP_BACKUP_TOP={"cve_index",".migrate","_backups"}  # public CVE index; migration work folder; isolated-backup folder
def _is_live(root_dir):
    """True when root_dir is this installation (its Data/ is the one common_db uses)."""
    try:
        from Cores import common_db as _cdb
        return os.path.normcase(os.path.abspath(str(_data_dir(root_dir))))==os.path.normcase(os.path.abspath(_cdb.data_dir()))
    except Exception:return False
def _encrypted_mode(root_dir):
    try:
        from Cores import common_db as _cdb
        return _is_live(root_dir) and _cdb.encryption_configured()
    except Exception:return False
def _create_encrypted_backup(prefix,bdir,data_dir,root_dir):
    """Encryption at rest on: a .loyabak (Cores/loyabak.py). The zip inside holds a consistent copy of the (still encrypted) DB,
    the encrypted attachments and the key file, and is itself AES-256-GCM under the data key. Needs the app unlocked."""
    from Cores import common_db as _cdb,db_driver as _drv,loyabak as _lb,crypto_store as _cs
    key=_cdb.session_key()
    if key is None:raise _cdb.DatabaseLocked("Unlock LOYA NG to make an encrypted backup.")
    keyfile=_cs.load_keyfile(_cdb.key_path())
    out=bdir.joinpath(f"{_safe_name(prefix,'Backup')}_{_stamp()}{_lb.EXT}")
    work=tempfile.mkdtemp(prefix=".loya_backup_",dir=str(data_dir))
    try:
        dbp=_cdb.db_path();snap=os.path.join(work,"db.snap")
        if _drv.file_kind(dbp)=="encrypted":_drv.backup_encrypted(dbp,snap,key)
        zp=os.path.join(work,"backup.zip")
        main=os.path.normcase(os.path.abspath(dbp))
        with zipfile.ZipFile(zp,"w",compression=zipfile.ZIP_DEFLATED) as z:
            for base,dirs,files in os.walk(data_dir):
                dirs[:]=[d for d in dirs if not _skip_backup_dir(base,d,data_dir,bdir)]
                for fn in files:
                    p=os.path.join(base,fn)
                    if os.path.normcase(os.path.abspath(p)).startswith(main) or fn.endswith(".tmp"):continue
                    z.write(p,arcname="Data/"+os.path.relpath(p,data_dir).replace("\\","/"))
            if os.path.isfile(snap):z.write(snap,arcname="Data/Note_LOYA_V1.db")
        _lb.write(zp,str(out),key,keyfile,{"kind":"data","label":prefix,"created_at":_utc_now()})
        _lb.verify(str(out),key)
    finally:
        shutil.rmtree(work,ignore_errors=True)
    return out
_DB_NAME="Note_LOYA_V1.db"
_DB_SIDECARS=("-wal","-shm","-journal")
def plain_db_snapshot(dbp,work):
    """A consistent copy of a plain (unencrypted) SQLite DB made with the SQLite backup API, so a backup never catches the
    file halfway through a write (a chain run writes its history and log while it runs). None when it cannot be made
    (an encrypted or missing DB, or the DB is busy past the timeout): the caller then copies the file as before."""
    from Cores import db_driver as _drv
    if _drv.file_kind(str(dbp))!="plain":return None
    snap=os.path.join(str(work),"db.snap")
    try:
        src=_drv.connect(str(dbp),timeout=10)
        try:
            dst=_drv.connect(snap)
            try:src.backup(dst)
            finally:dst.close()
        finally:src.close()
        return snap
    except Exception:
        try:os.remove(snap)
        except OSError:pass
        return None
def _skip_backup_dir(base,name,data_dir,bdir):
    """Top-level Data/ folders a data backup leaves out (public CVE index, migration work, backups kept inside Data/, the
    temporary snapshot folder), plus the backups folder itself wherever it sits under Data/ (no backup inside a backup)."""
    full=os.path.normcase(os.path.abspath(os.path.join(base,name)))
    if bdir is not None and full==os.path.normcase(os.path.abspath(str(bdir))):return True
    if os.path.abspath(base)!=os.path.abspath(str(data_dir)):return False
    return name in _SKIP_BACKUP_TOP or name.startswith(".loya_backup_")
def create_data_backup(progress=None,prefix="Backup",root_dir=None,out_dir=None):
    bdir=_backups_dir(root_dir,out_dir)
    data_dir=_data_dir(root_dir)
    from Cores import common_db as _cdb
    if _encrypted_mode(root_dir) and _cdb.session_key() is not None:
        out=_create_encrypted_backup(prefix,bdir,data_dir,root_dir)
        _log_update("[+]",f"Encrypted data backup created: {out}",root_dir)
        return str(out)
    # Encrypted mode while locked (e.g. the updater): a plain zip of files that are themselves ciphertext (SQLCipher DB, encrypted
    # attachments, PIN-wrapped key file) - the WAL was folded in at lock, and nothing readable is added.
    name=f"{_safe_name(prefix,'Backup')}_{_stamp()}.zip"
    out=bdir.joinpath(name)
    if progress:
        try:progress.setValue(10);progress._label.setText("Collecting Data/ ...")
        except Exception:pass
    work=tempfile.mkdtemp(prefix=".loya_backup_",dir=str(data_dir)) if data_dir.is_dir() else None
    try:
        # A plain DB goes in as a consistent snapshot (chain graphs, run history and run logs included), never half-written.
        snap=plain_db_snapshot(data_dir.joinpath(_DB_NAME),work) if work else None
        main=os.path.normcase(os.path.abspath(str(data_dir.joinpath(_DB_NAME))))
        with zipfile.ZipFile(out,"w",compression=zipfile.ZIP_DEFLATED) as z:
            if data_dir.is_dir():
                for base,dirs,files in os.walk(data_dir):
                    # Data/cve_index is public, regenerable CVE data (tens of MB): the app reinstalls it when missing, so backups skip it.
                    dirs[:]=[d for d in dirs if not _skip_backup_dir(base,d,data_dir,bdir)]
                    for fn in files:
                        p=Path(base).joinpath(fn)
                        np=os.path.normcase(os.path.abspath(str(p)))
                        if snap and (np==main or any(np==main+sfx for sfx in _DB_SIDECARS)):continue
                        rel=os.path.relpath(p,data_dir).replace("\\","/")
                        z.write(str(p),arcname=f"Data/{rel}")
            if snap:z.write(snap,arcname=f"Data/{_DB_NAME}")
    finally:
        if work:shutil.rmtree(work,ignore_errors=True)
    if progress:
        try:progress.setValue(100);progress._label.setText("Done.")
        except Exception:pass
    _log_update("[+]",f"Data backup created: {out}",root_dir)
    return str(out)
# Backup zips come from the user's own Backups/ folder but also from an off-site folder or a file picked for restore, so they are
# checked before anything is written: safe names (no .., absolute, drive, ADS or reserved names), no links or special files, no
# encrypted entries, and entry-count / per-file / total / compression-ratio / free-space limits against zip bombs. Extraction
# then stops at the declared size of each entry.
BACKUP_MAX_ENTRIES=200000
BACKUP_MAX_FILE_BYTES=4*1024**3
BACKUP_MAX_TOTAL_BYTES=16*1024**3
BACKUP_MAX_RATIO=200
def _safe_extract_backup(zip_path,dst):
    import stat as _stat
    out=os.path.abspath(dst)
    with zipfile.ZipFile(zip_path,"r") as zf:
        infos=zf.infolist()
        if len(infos)>BACKUP_MAX_ENTRIES:raise ValueError("The backup has too many entries.")
        plan=[];total=0;seen=set()
        for info in infos:
            parts=_helpers.safe_zip_member_parts(info.filename)
            if not parts:continue
            ftype=_stat.S_IFMT((info.external_attr>>16)&0xFFFF)
            if ftype and ftype not in (_stat.S_IFREG,_stat.S_IFDIR):raise ValueError(f"The backup contains a link or special file: {info.filename[:120]}")
            if info.flag_bits&0x1:raise ValueError("The backup contains encrypted entries.")
            target=os.path.abspath(os.path.join(out,*parts))
            if os.path.commonpath([target,out])!=out:raise ValueError("A backup entry escapes the restore folder.")
            key="/".join(parts).lower()
            if key in seen:raise ValueError(f"The backup lists the same path twice: {info.filename[:120]}")
            seen.add(key)
            if not info.is_dir():
                if info.file_size>BACKUP_MAX_FILE_BYTES:raise ValueError(f"A backup entry is too large: {info.filename[:120]}")
                if info.file_size>1024*1024 and info.compress_size>0 and info.file_size/info.compress_size>BACKUP_MAX_RATIO:raise ValueError(f"A backup entry has a suspicious compression ratio: {info.filename[:120]}")
                total+=info.file_size
                if total>BACKUP_MAX_TOTAL_BYTES:raise ValueError("The backup expands beyond the size limit.")
            plan.append((info,target))
        try:free=shutil.disk_usage(out).free
        except OSError:free=None
        if free is not None and total>free:raise ValueError("Not enough free disk space to restore this backup.")
        for info,target in plan:
            if info.is_dir():os.makedirs(target,exist_ok=True);continue
            os.makedirs(os.path.dirname(target),exist_ok=True)
            written=0
            with zf.open(info,"r") as src,open(target,"wb") as fh:
                for chunk in iter(lambda:src.read(1024*1024),b""):
                    written+=len(chunk)
                    if written>info.file_size:raise ValueError(f"A backup entry is larger than declared: {info.filename[:120]}")
                    fh.write(chunk)
def _open_loyabak(path,tmp,pin=None):
    """Decrypt a .loyabak into tmp/backup.zip. The session key opens backups of this installation; another PIN-era backup
    needs the PIN that was current when it was made. Returns (zip_path, data_key)."""
    from Cores import common_db as _cdb,loyabak as _lb,crypto_store as _cs
    header=_lb.read_header(path)
    key=_cdb.session_key()
    dek=None
    if key is not None and _cs.verify_dek(key,header["keyfile"]):dek=key.copy()
    elif pin:
        try:dek=_cs.unwrap(str(pin),header["keyfile"])
        except _cs.WrongPin:raise ValueError("Wrong PIN for this backup.")
    if dek is None:raise ValueError("This encrypted backup was made with another PIN: enter the PIN that was set when it was made.")
    zp=os.path.join(tmp,"backup.zip")
    _lb.decrypt_to(path,zp,dek)
    return zp,dek
def backup_needs_pin(path):
    """{"encrypted", "needs_pin", "created_at"} for a backup file. needs_pin: an encrypted .loyabak whose key file does not wrap
    this session's data key (made under another PIN / installation), so the restore must ask for that backup's PIN."""
    from Cores import common_db as _cdb,loyabak as _lb,crypto_store as _cs
    if not path or not _lb.is_loyabak(path):
        out={"encrypted":False,"needs_pin":False,"created_at":""}
        kf=_zip_keyfile(path) if path else None
        if kf is not None:
            # A zip made while locked in encrypted mode carries the SQLCipher DB and its key file: a foreign key needs its PIN too.
            key=_cdb.session_key()
            out["needs_pin"]=not (key is not None and _cs.verify_dek(key,kf))
        return out
    try:header=_lb.read_header(path)
    except _lb.BackupError as e:raise ValueError(str(e))
    key=_cdb.session_key()
    same=key is not None and _cs.verify_dek(key,header["keyfile"])
    # Same data key: the restore keeps this installation's key file (and PIN). Another key: the restore can re-wrap the backup's
    # key under the current PIN (restore(current_pin=...)), or else the backup's PIN comes back with it.
    return {"encrypted":True,"needs_pin":not same,"created_at":str(header.get("created_at",""))}
def _zip_keyfile(path):
    """The validated key file inside a plain backup zip (Data/Note_LOYA_V1.key), or None."""
    from Cores import crypto_store as _cs
    try:
        with zipfile.ZipFile(path,"r") as z:
            info=next((i for i in z.infolist() if i.filename.replace("\\","/").lstrip("/") in ("Data/Note_LOYA_V1.key","Note_LOYA_V1.key")),None)
            if info is None or info.file_size>64*1024:return None
            return _cs.validate_keyfile(json.loads(z.read(info).decode("utf-8")))
    except Exception:return None
def _audit_restore(name,mode,ok,note=""):
    try:
        from Cores.Services import security_service as _sec
        _sec.log_audit_event("backup_restored",f"restored backup {name} ({mode})"+(f": {note}" if note else ""),ok)
    except Exception:pass
def _mark_chains_unreviewed():
    """A restored backup does not vouch for its own scripts: every chain diagram must be reviewed again (as import does)."""
    try:
        from Cores import common_db as _cdb
        with _cdb.connection(timeout=10) as con:
            if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ChainGraphs'").fetchone():
                con.execute("UPDATE ChainGraphs SET ai_reviewed=0")
    except Exception:pass
def _merge_chain_history(bdb,bkind,dek,prev_lock,root_dir=None):
    """Merge mode keeps the live database file, so the backup's chain diagrams (missing ones, matched by name) and run history
    (missing runs, matched by run_id, with their logs) are added row by row through the chain bundle import, which validates
    every diagram and leaves the chains unreviewed. Never raises: a backup it cannot read is logged and left alone."""
    from Cores import common_db as _cdb
    try:
        key=(dek if dek is not None else _cdb.session_key()) if bkind=="encrypted" else None
        if bkind=="encrypted" and key is None:return None
        _cdb.set_locked(bool(prev_lock))   # the import goes through the normal (lock-checked) storage path
        from Cores.Services import chain_history as _hist
        return _hist.merge_from_db(bdb,key)
    except Exception as e:
        _log_downgrade("[!]",f"Chain history from the backup could not be merged: {e}",root_dir)
        return None
def _read_live_audit_rows(dbp):
    """The live DB's AuditEvents rows (kept across a replace restore), [] when there are none or the DB cannot be opened."""
    from Cores import common_db as _cdb,db_driver as _drv
    from Cores.Services import security_service as _sec
    kind=_drv.file_kind(dbp)
    if kind not in ("plain","encrypted"):return []
    key=_cdb.session_key() if kind=="encrypted" else None
    if kind=="encrypted" and key is None:return []
    try:
        con=_drv.connect(dbp,key=key)
        try:return _sec.read_audit_rows(con)
        finally:con.close()
    except Exception:return []
def restore_data_backup(zip_path,mode="merge",progress=None,root_dir=None,pin=None,current_pin=None):
    """Restore Data/ from a backup. Never rolls back the security audit log (security_audit.jsonl and the AuditEvents table keep
    every live entry; the backup's copy only adds what is missing) and never silently brings back an old PIN: when the backup's
    data key is this session's, the live key file is kept; when it is another key, current_pin (verified first) re-wraps it so the
    current PIN keeps working; without current_pin the backup's key file - and so its PIN - comes back (the UI warns)."""
    if not zip_path or not os.path.isfile(zip_path):return False,"Backup not found"
    if mode not in ("merge","replace"):return False,"Invalid mode"
    tmp=tempfile.mkdtemp(prefix="loya_restore_")
    try:os.chmod(tmp,0o700)
    except Exception:pass
    live=_is_live(root_dir)
    prev_lock=None
    dek=None
    src_name=os.path.basename(str(zip_path))
    try:
        if progress:
            try:progress.setValue(10);progress._label.setText("Extracting ...")
            except Exception:pass
        from Cores import loyabak as _lb
        if _lb.is_loyabak(zip_path):
            zip_path,dek=_open_loyabak(zip_path,tmp,pin)
        ex=os.path.join(tmp,"x");os.makedirs(ex,exist_ok=True)  # own folder: tmp also holds the decrypted backup.zip, which must never reach Data/
        _safe_extract_backup(zip_path,ex)
        src=os.path.join(ex,"Data")
        # Storage-migration backups (pre-encryption-*.loyabak) hold Data/'s contents at the archive root, marked by loyabak-manifest.json.
        if not os.path.isdir(src) and os.path.isfile(os.path.join(ex,"loyabak-manifest.json")):src=ex
        dst=str(_data_dir(root_dir))
        if not os.path.isdir(src):return False,"Missing Data/ in backup"
        from Cores import db_driver as _drv,common_db as _cdb
        bdb=os.path.join(src,"Note_LOYA_V1.db")
        bkind=_drv.file_kind(bdb)
        from Cores import crypto_store as _cs
        src_key=os.path.join(src,"Note_LOYA_V1.key");dst_key=os.path.join(dst,"Note_LOYA_V1.key")
        keep_key=False;new_kf=None;audit_rows=[]
        if live:
            enc_now=_cdb.encryption_configured()
            if enc_now and bkind=="plain":
                return False,"This backup is not encrypted. Turn encryption at rest off, restore it, then turn encryption on again."
            if not enc_now and bkind=="encrypted":
                return False,"This backup is encrypted. Turn encryption at rest on first (with the backup's PIN), then restore it."
            bkf=None
            if bkind=="encrypted" and os.path.isfile(src_key):
                try:bkf=_cs.load_keyfile(src_key)
                except _cs.KeyFileError:bkf=None
            sess=_cdb.session_key()
            if bkf is not None and dek is None and sess is not None and not _cs.verify_dek(sess,bkf):
                # A plain zip made while locked, under another data key: its PIN opens it (as a .loyabak's would).
                if not pin:return False,"This encrypted backup was made with another PIN: enter the PIN that was set when it was made."
                try:dek=_cs.unwrap(str(pin),bkf)
                except _cs.WrongPin:
                    _audit_restore(src_name,mode,False,"wrong PIN for this backup")
                    return False,"Wrong PIN for this backup."
            if bkf is not None and mode=="replace" and os.path.isfile(dst_key):
                if sess is not None and _cs.verify_dek(sess,bkf):
                    keep_key=True  # same data key (e.g. the PIN changed since the backup): the current key file, and PIN, stay
                elif dek is not None and current_pin:
                    # Another data key: verify the current PIN BEFORE anything is written, then wrap the backup's key under it.
                    try:live_kf=_cs.load_keyfile(dst_key)
                    except _cs.KeyFileError:return False,"The current key file cannot be read."
                    if not _cs.verify_pin(str(current_pin),live_kf):
                        _audit_restore(src_name,mode,False,"wrong current PIN")
                        return False,"Wrong current PIN."
                    new_kf=_cs.wrap_dek(dek,str(current_pin),{k:v for k,v in live_kf["kdf"].items() if k!="salt"})
                    new_kf["created_at"]=live_kf.get("created_at",new_kf["created_at"])
            if mode=="replace" and os.path.isfile(bdb):audit_rows=_read_live_audit_rows(os.path.join(dst,"Note_LOYA_V1.db"))
            if bkind=="encrypted" and dek is not None and mode=="replace":
                # The DB and its key file come back together; the session continues with the backup's data key.
                try:_drv.connect(bdb,key=dek).close()
                except Exception:return False,"The database in this backup does not open with its key."
            prev_lock=_cdb.is_locked()
            _cdb.set_locked(True)
            _cdb.wait_idle(10.0)
        if progress:
            try:progress.setValue(40);progress._label.setText("Restoring Data/ ...")
            except Exception:pass
        db_main=os.path.normcase(os.path.abspath(os.path.join(dst,"Note_LOYA_V1.db")))
        key_main=os.path.normcase(os.path.abspath(dst_key))
        audit_main=os.path.normcase(os.path.abspath(os.path.join(dst,"security_audit.jsonl")))
        db_kept=False
        for base,_,files in os.walk(src):
            rel=os.path.relpath(base,src)
            td=os.path.join(dst,rel) if rel!="." else dst
            os.makedirs(td,exist_ok=True)
            # The main DB first: copying it removes the live DB's sidecars, which must not take the backup's own with them.
            for fn in (sorted(files,key=lambda n:(n!=_DB_NAME,n)) if rel=="." else files):
                if rel=="." and fn=="loyabak-manifest.json":continue
                dp=os.path.join(td,fn)
                if mode=="merge" and os.path.exists(dp):
                    if rel=="." and fn==_DB_NAME:db_kept=True
                    continue
                ndp=os.path.normcase(os.path.abspath(dp))
                if ndp==key_main and (keep_key or new_kf is not None):continue
                if ndp==audit_main and os.path.isfile(dp):
                    # The audit log is append-only across restores: keep the live log, add only what the backup has and it lacks.
                    from Cores.Services import security_service as _sec
                    _sec.merge_audit_file(dp,os.path.join(base,fn))
                    continue
                if os.path.normcase(os.path.abspath(dp))==db_main:
                    for sfx in ("-wal","-shm","-journal"):
                        try:os.remove(dp+sfx)  # the live DB's sidecars must never be replayed onto the restored file
                        except OSError:pass
                shutil.copy2(os.path.join(base,fn),dp)
                # copy2 carries the temp extract's umask mode (0664 on Linux): keep restored Data/ files owner-only, like the originals.
                if os.name!="nt":
                    try:os.chmod(dp,0o600)
                    except OSError:pass
        if new_kf is not None:_cs.save_keyfile(dst_key,new_kf)
        if live:
            if audit_rows:
                # Events written to the encrypted AuditEvents table since the backup survive the restored DB.
                from Cores.Services import security_service as _sec
                rkey=(dek if dek is not None else _cdb.session_key()) if bkind=="encrypted" else None
                try:
                    con=_drv.connect(os.path.join(dst,"Note_LOYA_V1.db"),key=rkey)
                    try:_sec.merge_audit_rows(con,audit_rows);con.commit()
                    finally:con.close()
                except Exception as e:_log_downgrade("[!]",f"Audit events could not be merged into the restored DB: {e}",root_dir)
            if dek is not None and bkind=="encrypted" and mode=="replace":
                from Cores import common_db as _cdb2
                _cdb2.set_session_key(dek);dek=None
            merged=_merge_chain_history(bdb,bkind,dek,prev_lock,root_dir) if db_kept and os.path.isfile(bdb) else None
            _mark_chains_unreviewed()
            _audit_restore(src_name,mode,True,"current PIN kept" if (keep_key or new_kf is not None) else ("backup's PIN restored" if bkind=="encrypted" and mode=="replace" else ""))
        if progress:
            try:progress.setValue(100);progress._label.setText("Done.")
            except Exception:pass
        _log_downgrade("[+]",f"Data restore ok: {src_name} mode={mode}",root_dir)
        if live and merged:
            got=len(merged["chains"]["created"]),merged["runs"]["imported"]
            if got[0] or got[1]:return True,f"Restore done ({got[0]} chain(s) and {got[1]} chain run(s) added from the backup). Restart app if needed."
        return True,"Restore done. Restart app if needed."
    except Exception as e:
        _log_downgrade("[!]",f"Data restore failed: {src_name} ({e})",root_dir)
        if live:_audit_restore(src_name,mode,False,str(e))
        return False,f"Restore failed: {e}"
    finally:
        if prev_lock is not None:
            from Cores import common_db as _cdb3
            _cdb3.set_locked(prev_lock)
        if dek is not None:
            try:dek.wipe()
            except Exception:pass
        try:shutil.rmtree(tmp,ignore_errors=True)
        except Exception:pass
def list_code_snapshots(root_dir=None,out_dir=None):
    rows=[]
    sdir=old_versions_dir(root_dir,out_dir)
    try:
        for n in os.listdir(sdir):
            if not n.lower().endswith(".zip"):continue
            p=sdir.joinpath(n)
            try:
                st=p.stat()
                rows.append((str(p),st.st_mtime,st.st_size))
            except Exception:
                pass
    except Exception:
        pass
    rows.sort(key=lambda x:x[1],reverse=True)
    return rows
def trim_code_snapshots(keep=2,root_dir=None,out_dir=None):
    try:keep=max(0,int(keep))
    except Exception:keep=2
    rows=list_code_snapshots(root_dir,out_dir)
    ok=0;bad=0
    allowed=str(old_versions_dir(root_dir,out_dir))
    for p,_,_ in rows[keep:]:
        try:
            if p and os.path.isfile(p) and os.path.dirname(os.path.abspath(p))==os.path.abspath(allowed):
                os.remove(p);ok+=1;_log_update("[*]",f"Old snapshot removed: {p}",root_dir)
            else:bad+=1
        except Exception:bad+=1
    return ok,bad
def create_code_snapshot(version="",reason="update",keep=2,progress=None,root_dir=None,out_dir=None):
    root=_root_dir(root_dir)
    sdir=old_versions_dir(root_dir,out_dir)
    ver=_helpers.coerce_local_version(version,_service.get_app_version())
    tag=_safe_name(reason,"update")
    name=f"CodeSnapshot_{_safe_name(ver,'0.0.0')}_{tag}_{_stamp()}.zip"
    out=sdir.joinpath(name)
    meta={"version":ver,"reason":tag,"created_at":_utc_now(),"source_repo":_helpers.OFFICIAL_SOURCE_REPO}
    if progress:
        try:progress.setValue(5);progress._label.setText("Collecting code files ...")
        except Exception:pass
    with zipfile.ZipFile(out,"w",compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("__snapshot__/metadata.json",json.dumps(meta,ensure_ascii=False,indent=2))
        total=0
        for src,rel in _iter_project_files(root):
            z.write(str(src),arcname=f"app/{rel}")
            total+=1
    trim_code_snapshots(keep=keep,root_dir=root,out_dir=sdir)
    if progress:
        try:progress.setValue(100);progress._label.setText("Done.")
        except Exception:pass
    _log_update("[+]",f"Code snapshot created: {out} version={ver} reason={tag}",root)
    return {"path":str(out),"version":ver,"reason":tag}
def _remove_current_code(root):
    root=str(_root_dir(root))
    for base,dirs,files in os.walk(root,topdown=True):
        rel_dir=os.path.relpath(base,root)
        if rel_dir==".":
            rel_dir=""
        dirs[:]=[d for d in dirs if not _should_skip_rel(os.path.join(rel_dir,d))]
        for fn in files:
            rel=os.path.join(rel_dir,fn) if rel_dir else fn
            if _should_skip_rel(rel):continue
            p=os.path.join(base,fn)
            if _within_root(p,root):
                try:os.remove(p)
                except Exception:pass
    for base,dirs,_ in os.walk(root,topdown=False):
        rel_dir=os.path.relpath(base,root)
        if rel_dir in (".",""):continue
        if _should_skip_rel(rel_dir):continue
        if not _within_root(base,root):continue
        try:
            if not os.listdir(base):os.rmdir(base)
        except Exception:
            pass
def restore_code_snapshot(zip_path,root_dir=None,progress=None,replace=True):
    if not zip_path or not os.path.isfile(zip_path):return False,"Snapshot not found"
    root=_root_dir(root_dir)
    tmp=tempfile.mkdtemp(prefix="loya_code_restore_")
    try:
        if progress:
            try:progress.setValue(10);progress._label.setText("Extracting code snapshot ...")
            except Exception:pass
        _safe_extract_backup(zip_path,tmp)
        with zipfile.ZipFile(zip_path,"r") as z:
            if os.name!="nt":
                for info in z.infolist():
                    mode=(info.external_attr>>16)&0o777
                    p=os.path.join(tmp,*[x for x in info.filename.split("/") if x])
                    if mode and not info.is_dir() and _within_root(p,tmp) and os.path.isfile(p):
                        try:os.chmod(p,(mode&0o755)|0o600)
                        except OSError:pass
        app_src=os.path.join(tmp,"app")
        if not os.path.isdir(app_src):return False,"Invalid snapshot format"
        if replace:_remove_current_code(root)
        if progress:
            try:progress.setValue(55);progress._label.setText("Restoring code files ...")
            except Exception:pass
        for base,dirs,files in os.walk(app_src):
            rel_dir=os.path.relpath(base,app_src)
            rel_dir="" if rel_dir=="." else rel_dir
            dirs[:]=[d for d in dirs if not _should_skip_rel(os.path.join(rel_dir,d))]
            td=os.path.join(str(root),rel_dir) if rel_dir else str(root)
            os.makedirs(td,exist_ok=True)
            for fn in files:
                rel=os.path.join(rel_dir,fn) if rel_dir else fn
                if _should_skip_rel(rel):continue
                src=os.path.join(base,fn);dst=os.path.join(td,fn)
                if _within_root(dst,root):shutil.copy2(src,dst)
        if progress:
            try:progress.setValue(100);progress._label.setText("Done.")
            except Exception:pass
        _log_downgrade("[+]",f"Code snapshot restored: {zip_path}",root)
        return True,"Code snapshot restored."
    except Exception as e:
        _log_downgrade("[!]",f"Code snapshot restore failed: {zip_path} ({e})",root)
        return False,f"Restore failed: {e}"
    finally:
        try:shutil.rmtree(tmp,ignore_errors=True)
        except Exception:pass
def prepare_update_backups(current_version="",reason="update",keep_code_versions=2,progress=None,root_dir=None,data_backup_dir=None,code_backup_dir=None):
    ver=_helpers.coerce_local_version(current_version,_service.get_app_version())
    data_backup=create_data_backup(progress=progress,prefix="UpdateBackup",root_dir=root_dir,out_dir=data_backup_dir)
    code_snapshot=create_code_snapshot(version=ver,reason=reason,keep=keep_code_versions,progress=progress,root_dir=root_dir,out_dir=code_backup_dir)
    out={"version":ver,"data_backup":data_backup,"code_snapshot":code_snapshot.get("path",""),"old_versions_dir":str(old_versions_dir(root_dir,code_backup_dir))}
    _log_update("[+]",f"Update safety backups ready: data={data_backup} code={out['code_snapshot']}",root_dir)
    return out
