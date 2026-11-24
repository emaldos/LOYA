import os
import json
import time
from contextlib import contextmanager
from datetime import datetime,timezone
from Cores import db_driver
DB_SCHEMA_VERSION=18
LOCKED_MESSAGE="LOYA NG is locked. Unlock it to continue."
ENCRYPTED_MESSAGE="The database is encrypted. Unlock LOYA NG to continue."
def _abs(*p):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),*p)
def data_dir():
    d=_abs("..","Data")
    # H-02: a new Data/ is private to the user (0700; the mode is ignored on Windows, where the ACL hardening applies).
    os.makedirs(d,mode=0o700,exist_ok=True)
    return d
def db_path():
    return os.path.join(data_dir(),"Note_LOYA_V1.db")
def backups_dir():
    """Where data backups go: <app>/Backups for this installation's Data/. Overridable like data_dir (tests/_isolate.py does);
    when Data/ was moved or isolated without an override, a private Data/_backups so a scratch run never writes into the
    app's real Backups/."""
    try:
        from Cores.Update import health_check as _hc
        same=os.path.normcase(os.path.abspath(_hc.data_dir()))==os.path.normcase(os.path.abspath(data_dir()))
        d=_hc.backups_dir() if same else os.path.join(data_dir(),"_backups")
    except Exception:
        d=os.path.join(data_dir(),"_backups")
    os.makedirs(d,mode=0o700,exist_ok=True)
    return d
def key_path():
    """The envelope key file (crypto_store format): the PIN-wrapped data key. It exists whenever a PIN is set."""
    return os.path.join(data_dir(),"Note_LOYA_V1.key")
class DatabaseLocked(RuntimeError):pass
_LOCKED=False
def set_locked(v):
    global _LOCKED
    _LOCKED=bool(v)
def is_locked():return _LOCKED
# ---------------------------------------------------------------- encryption state
# The session data key (crypto_store.DataKey) while unlocked with encryption at rest on; None otherwise. Owned by security_service.
_SESSION_KEY=None
def set_session_key(dek):
    global _SESSION_KEY
    _SESSION_KEY=dek
def clear_session_key():
    global _SESSION_KEY
    k=_SESSION_KEY;_SESSION_KEY=None
    try:
        if k is not None:k.wipe()
    except Exception:pass
def session_key():return _SESSION_KEY
_SEC_CACHE={"sig":None,"sec":{}}
def _security_section():
    """security{} from settings.json, cached on the file's mtime/size (read on every connect, so it must be cheap)."""
    try:
        from Cores.Update import health_check as _hc  # the same settings.json security_service reads
        p=_hc.settings_path()
    except Exception:
        p=os.path.join(data_dir(),"settings.json")
    try:
        st=os.stat(p);sig=(p,st.st_mtime_ns,st.st_size)
    except OSError:
        return {}
    if _SEC_CACHE["sig"]==sig:return _SEC_CACHE["sec"]
    try:
        with open(p,"r",encoding="utf-8") as f:d=json.load(f)
        sec=d.get("security",{}) if isinstance(d,dict) else {}
        if not isinstance(sec,dict):sec={}
    except Exception:
        sec={}
    _SEC_CACHE["sig"]=sig;_SEC_CACHE["sec"]=sec
    return sec
def encryption_configured():
    """True when encryption at rest (v2: SQLCipher + envelope key) is the configured mode."""
    sec=_security_section()
    try:return bool(sec.get("enc_enabled")) and int(sec.get("enc_version") or 0)>=2
    except Exception:return False
def _is_main(path):
    try:return os.path.normcase(os.path.abspath(path))==os.path.normcase(os.path.abspath(db_path()))
    except Exception:return False
def at_rest_locked(path=None):
    """Opening the DB now would either fail (encrypted, no key) or start an empty plain DB in its place (the S5 guard)."""
    p=path or db_path()
    kind=db_driver.file_kind(p)
    if kind=="encrypted":return _SESSION_KEY is None
    if kind in ("missing","empty"):
        if os.path.isfile(p+".enc"):return True  # legacy (v1 Fernet) copy waiting for its one-time migration
        if _is_main(p) and _SESSION_KEY is None and encryption_configured():return True
    return False
def db_locked(path=None):return _LOCKED or at_rest_locked(path)
def connect(path=None,timeout=5,**kwargs):
    """Open the main DB (or another SQLite file) through db_driver. An encrypted file is opened with the session key; a missing
    main DB is created encrypted when encryption at rest is on. Raises DatabaseLocked instead of ever creating a plain empty
    DB where an encrypted one belongs."""
    p=path or db_path()
    kind=db_driver.file_kind(p)
    if kind=="encrypted":
        if _SESSION_KEY is None:raise DatabaseLocked(ENCRYPTED_MESSAGE)
        return db_driver.connect(p,key=_SESSION_KEY,timeout=timeout,**kwargs)
    if kind in ("missing","empty") and _is_main(p):
        if os.path.isfile(p+".enc"):raise DatabaseLocked(ENCRYPTED_MESSAGE)
        if encryption_configured():
            if _SESSION_KEY is None:raise DatabaseLocked(ENCRYPTED_MESSAGE)
            return db_driver.connect(p,key=_SESSION_KEY,timeout=timeout,**kwargs)
    return db_driver.connect(p,timeout=timeout,**kwargs)
@contextmanager
def connection(path=None,timeout=5,row_factory=None,**kwargs):
    """with common_db.connection() as con: commit on success, rollback on error, ALWAYS close (unlike `with sqlite3.connect()`)."""
    con=connect(path,timeout=timeout,**kwargs)
    if row_factory is not None:con.row_factory=row_factory
    try:
        yield con
        con.commit()
    except BaseException:
        try:con.rollback()
        except Exception:pass
        raise
    finally:
        con.close()
def wait_idle(timeout=10.0):
    """Wait until no db_driver connection is open (lock/migration need the file to themselves, Windows above all)."""
    end=time.time()+max(0.0,timeout)
    while True:
        if db_driver.open_count(collect=True)==0:return True
        if time.time()>=end:return False
        time.sleep(0.05)
def db_has_data(path):
    """True when the SQLite file at path holds at least one row in any user table. Missing, 0-byte, corrupt, locked or schema-only files are False."""
    try:
        if not path or not os.path.isfile(path) or os.path.getsize(path)==0:return False
        con=connect(path,timeout=5)
        try:
            tables=[r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name<>'SchemaMigrations'")]
            for t in tables:
                if con.execute(f'SELECT 1 FROM "{t}" LIMIT 1').fetchone():return True
            return False
        finally:con.close()
    except Exception:return False
def table_cols(cur,table):
    try:
        cur.execute(f"PRAGMA table_info({table})")
        return [r[1] for r in cur.fetchall()]
    except Exception:
        return []
def _ensure_columns(cur,table,columns):
    cols=set(table_cols(cur,table))
    for name,spec in columns:
        if name not in cols:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {name} {spec}")
def _record_migration(cur,version,applied_at):
    try:
        cur.execute(
            "INSERT OR IGNORE INTO SchemaMigrations(version,applied_at) VALUES(?,?)",
            (int(version),str(applied_at)),
        )
    except Exception:
        pass
def _dedupe_notes_for_unique_name(cur,con):
    try:
        cur.execute("SELECT note_name,MAX(id) FROM Notes GROUP BY note_name HAVING COUNT(*)>1")
        rows=cur.fetchall()
    except Exception:
        rows=[]
    for note_name,keep_id in rows:
        try:
            if note_name is None:
                cur.execute("DELETE FROM Notes WHERE note_name IS NULL AND id<>?",(keep_id,))
            else:
                cur.execute("DELETE FROM Notes WHERE note_name=? AND id<>?",(note_name,keep_id))
        except Exception:
            continue
    try:
        con.commit()
    except Exception:
        pass
_REPORTING_TABLES=(
    "CREATE TABLE IF NOT EXISTS Reports(id INTEGER PRIMARY KEY AUTOINCREMENT,uid TEXT NOT NULL UNIQUE,title TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'draft',template_id TEXT,profile_id TEXT,meta TEXT,branding TEXT,options TEXT,created_at TEXT,updated_at TEXT)",
    "CREATE TABLE IF NOT EXISTS ReportSections(id INTEGER PRIMARY KEY AUTOINCREMENT,report_id INTEGER NOT NULL,uid TEXT NOT NULL,kind TEXT NOT NULL DEFAULT 'custom',title TEXT,content TEXT,position INTEGER NOT NULL DEFAULT 0,hidden INTEGER NOT NULL DEFAULT 0,options TEXT,updated_at TEXT)",
    "CREATE INDEX IF NOT EXISTS idx_report_sections_report ON ReportSections(report_id,position)",
    "CREATE TABLE IF NOT EXISTS ReportFindings(id INTEGER PRIMARY KEY AUTOINCREMENT,report_id INTEGER NOT NULL,uid TEXT NOT NULL,position INTEGER NOT NULL DEFAULT 0,title TEXT,severity TEXT NOT NULL DEFAULT 'info',cvss_vector TEXT,cvss_score REAL,status TEXT NOT NULL DEFAULT 'open',data TEXT,created_at TEXT,updated_at TEXT)",
    "CREATE INDEX IF NOT EXISTS idx_report_findings_report ON ReportFindings(report_id,position)",
    "CREATE TABLE IF NOT EXISTS FindingLibrary(id INTEGER PRIMARY KEY AUTOINCREMENT,uid TEXT NOT NULL UNIQUE,title TEXT,category TEXT,severity TEXT NOT NULL DEFAULT 'info',cvss_vector TEXT,cvss_score REAL,data TEXT,created_at TEXT,updated_at TEXT)",
    "CREATE TABLE IF NOT EXISTS ReportTemplates(id INTEGER PRIMARY KEY AUTOINCREMENT,uid TEXT NOT NULL UNIQUE,name TEXT NOT NULL,description TEXT,data TEXT,created_at TEXT,updated_at TEXT)",
    "CREATE TABLE IF NOT EXISTS ReportVersions(id INTEGER PRIMARY KEY AUTOINCREMENT,report_id INTEGER NOT NULL,label TEXT,snapshot TEXT NOT NULL,created_at TEXT NOT NULL)",
    "CREATE INDEX IF NOT EXISTS idx_report_versions_report ON ReportVersions(report_id,created_at)",
    "CREATE TABLE IF NOT EXISTS ReportEvidence(id INTEGER PRIMARY KEY AUTOINCREMENT,uid TEXT NOT NULL UNIQUE,kind TEXT NOT NULL,title TEXT,source TEXT,session_id TEXT,profile_id TEXT,target TEXT,command TEXT,exit_code INTEGER,cwd TEXT,started_at TEXT,ended_at TEXT,content TEXT,meta TEXT,created_at TEXT NOT NULL)",
    "CREATE INDEX IF NOT EXISTS idx_report_evidence_kind ON ReportEvidence(kind,created_at)",
    "CREATE INDEX IF NOT EXISTS idx_report_evidence_session ON ReportEvidence(session_id)",
    "CREATE TABLE IF NOT EXISTS ReportEvidenceEvents(id INTEGER PRIMARY KEY AUTOINCREMENT,evidence_id INTEGER NOT NULL,seq INTEGER NOT NULL,ts TEXT NOT NULL,kind TEXT NOT NULL,data TEXT)",
    "CREATE INDEX IF NOT EXISTS idx_report_evidence_events ON ReportEvidenceEvents(evidence_id,seq)",
    "CREATE TABLE IF NOT EXISTS ReportAssets(id INTEGER PRIMARY KEY AUTOINCREMENT,uid TEXT NOT NULL UNIQUE,name TEXT,mime TEXT NOT NULL,data BLOB NOT NULL,width INTEGER,height INTEGER,sha256 TEXT,created_at TEXT NOT NULL)",
    "CREATE INDEX IF NOT EXISTS idx_report_assets_sha ON ReportAssets(sha256)",
    # v17: targets linked to a report as its scope (a snapshot of the target's non-secret values), and the findings that affect them.
    "CREATE TABLE IF NOT EXISTS ReportTargets(id INTEGER PRIMARY KEY AUTOINCREMENT,report_id INTEGER NOT NULL,uid TEXT NOT NULL,target_id TEXT,profile_id TEXT,name TEXT,snapshot TEXT,allowed_secret_keys TEXT,position INTEGER NOT NULL DEFAULT 0,linked_at TEXT,updated_at TEXT)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_report_targets_uid ON ReportTargets(report_id,uid)",
    "CREATE INDEX IF NOT EXISTS idx_report_targets_report ON ReportTargets(report_id,position)",
    "CREATE TABLE IF NOT EXISTS ReportFindingTargets(id INTEGER PRIMARY KEY AUTOINCREMENT,finding_id INTEGER NOT NULL,report_target_uid TEXT NOT NULL,keys TEXT,position INTEGER NOT NULL DEFAULT 0)",
    "CREATE INDEX IF NOT EXISTS idx_report_finding_targets ON ReportFindingTargets(finding_id,position)",
)
def _create_reporting_tables(cur):
    # Reporting (v13). Everything, screenshots included, lives inside the DB so the at-rest encryption covers it.
    for sql in _REPORTING_TABLES:
        try:cur.execute(sql)
        except Exception:pass
# CVE Intel (v15): a local cache of public vulnerability data (NVD / CISA KEV / FIRST EPSS). Kept in the main DB so lookups work offline
# and the at-rest encryption covers which CVEs the operator looked at.
_CVE_TABLES=(
    "CREATE TABLE IF NOT EXISTS CveRecords(cve_id TEXT PRIMARY KEY,data TEXT NOT NULL,published TEXT,modified TEXT,severity TEXT,score REAL,kev INTEGER DEFAULT 0,epss REAL,search TEXT,source TEXT,partial INTEGER DEFAULT 0,fetched_at TEXT NOT NULL,in_feed INTEGER DEFAULT 0,feed_kind TEXT,feed_at TEXT,is_read INTEGER DEFAULT 0,notified INTEGER DEFAULT 1,notify_kind TEXT,watch_hit TEXT)",
    "CREATE INDEX IF NOT EXISTS idx_cve_records_feed ON CveRecords(in_feed,published)",
    "CREATE INDEX IF NOT EXISTS idx_cve_records_fetched ON CveRecords(fetched_at)",
    "CREATE TABLE IF NOT EXISTS CveKev(cve_id TEXT PRIMARY KEY,data TEXT NOT NULL,date_added TEXT,seen_at TEXT)",
    "CREATE TABLE IF NOT EXISTS CveMeta(key TEXT PRIMARY KEY,value TEXT)",
)
def _create_cve_tables(cur):
    for sql in _CVE_TABLES:
        try:cur.execute(sql)
        except Exception:pass
# Chain Diagrams (v16): the node graph of an Action Chain and the history of its runs. Additive: a chain without a ChainGraphs
# row stays a plain linear chain (Playbooks/PlaybookSteps are not touched).
_CHAIN_GRAPH_TABLES=(
    "CREATE TABLE IF NOT EXISTS ChainGraphs(playbook_id INTEGER PRIMARY KEY,graph TEXT NOT NULL,schema_version INTEGER NOT NULL DEFAULT 1,ai_made INTEGER NOT NULL DEFAULT 0,ai_reviewed INTEGER NOT NULL DEFAULT 1,ai_client TEXT,created_at TEXT,updated_at TEXT)",
    "CREATE TABLE IF NOT EXISTS ChainRuns(id INTEGER PRIMARY KEY AUTOINCREMENT,run_id TEXT NOT NULL UNIQUE,playbook_id INTEGER,chain_name TEXT,mode TEXT NOT NULL,state TEXT NOT NULL,source TEXT,target TEXT,started_at TEXT NOT NULL,ended_at TEXT,data TEXT)",
    "CREATE INDEX IF NOT EXISTS idx_chain_runs_playbook ON ChainRuns(playbook_id,started_at)",
    "CREATE INDEX IF NOT EXISTS idx_chain_runs_started ON ChainRuns(started_at)",
    "CREATE TABLE IF NOT EXISTS ChainRunLogs(id INTEGER PRIMARY KEY AUTOINCREMENT,run_id TEXT NOT NULL,seq INTEGER NOT NULL,ts TEXT NOT NULL,node TEXT,level TEXT NOT NULL,kind TEXT NOT NULL,text TEXT,data TEXT)",
    "CREATE INDEX IF NOT EXISTS idx_chain_run_logs_run ON ChainRunLogs(run_id,seq)",
)
def _create_chain_graph_tables(cur):
    for sql in _CHAIN_GRAPH_TABLES:
        try:cur.execute(sql)
        except Exception:pass
def _migrate_chain_callers(cur):
    # v14: action chains get a /caller; chain jobs remember the chain name and why a step was skipped. Additive only.
    for sql in ("ALTER TABLE Playbooks ADD COLUMN caller TEXT","ALTER TABLE TerminalJobs ADD COLUMN skip_reason TEXT","ALTER TABLE TerminalJobs ADD COLUMN chain_name TEXT"):
        try:cur.execute(sql)
        except Exception:pass
    try:
        from Cores import chain_callers as _cc
        cur.execute("SELECT id,name,caller FROM Playbooks ORDER BY id ASC")
        rows=cur.fetchall()
        taken={str(r[2]).lower() for r in rows if r[2]}
        for pid,name,caller in rows:
            if caller:continue
            # Existing chains get a caller from their name so /name works straight away.
            suggestion=_cc.suggest_caller(name,taken)
            taken.add(suggestion)
            cur.execute("UPDATE Playbooks SET caller=? WHERE id=?",(suggestion,pid))
    except Exception:
        pass
    try:cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_playbooks_caller ON Playbooks(caller) WHERE caller IS NOT NULL AND caller<>''")
    except Exception:pass
# v18 (storage rebuild): the JSON stores that used to sit as plaintext files in Data/ live here while encryption at rest is on
# (Cores/doc_store.py), and API keys that are neither in the OS keyring nor session-only (Secrets).
_STORAGE_TABLES=(
    "CREATE TABLE IF NOT EXISTS AppDocs(name TEXT PRIMARY KEY,data TEXT NOT NULL,mtime REAL NOT NULL,size INTEGER NOT NULL DEFAULT 0)",
    "CREATE TABLE IF NOT EXISTS Secrets(name TEXT PRIMARY KEY,value TEXT NOT NULL,hint TEXT,updated_at TEXT)",
    "CREATE TABLE IF NOT EXISTS AuditEvents(id INTEGER PRIMARY KEY AUTOINCREMENT,ts TEXT NOT NULL,event TEXT NOT NULL,detail TEXT,success INTEGER NOT NULL DEFAULT 1)",
    "CREATE INDEX IF NOT EXISTS idx_audit_events_ts ON AuditEvents(ts)",
)
def _create_storage_tables(cur):
    for sql in _STORAGE_TABLES:
        try:cur.execute(sql)
        except Exception:pass
def apply_migrations(con):
    try:
        cur=con.cursor()
    except Exception:
        return
    try:
        cur.execute("PRAGMA user_version")
        row=cur.fetchone()
        ver=int(row[0]) if row and str(row[0]).isdigit() else 0
    except Exception:
        ver=0
    start_ver=ver
    now=datetime.now(timezone.utc).isoformat()
    try:
        cur.execute("CREATE TABLE IF NOT EXISTS SchemaMigrations(version INTEGER PRIMARY KEY,applied_at TEXT)")
    except Exception:
        pass
    if ver<1:
        _record_migration(cur,1,now)
        ver=1
    if ver<2:
        try:
            cur.execute("CREATE TABLE IF NOT EXISTS NotesHistory(id INTEGER PRIMARY KEY AUTOINCREMENT,note_id INTEGER,note_name TEXT,group_name TEXT,content TEXT,action TEXT,action_at TEXT)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_notes_hist_note_id ON NotesHistory(note_id)")
        except Exception:
            pass
        try:
            cur.execute("CREATE TABLE IF NOT EXISTS CommandsNotesHistory(id INTEGER PRIMARY KEY AUTOINCREMENT,cmd_id INTEGER,note_name TEXT,category TEXT,sub_category TEXT,command TEXT,tags TEXT,description TEXT,action TEXT,action_at TEXT)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_cmdn_hist_cmd_id ON CommandsNotesHistory(cmd_id)")
        except Exception:
            pass
        try:
            cur.execute("CREATE TABLE IF NOT EXISTS CommandsHistory(id INTEGER PRIMARY KEY AUTOINCREMENT,cmd_id INTEGER,note_id INTEGER,note_name TEXT,cmd_note_title TEXT,category TEXT,sub_category TEXT,description TEXT,tags TEXT,command TEXT,action TEXT,action_at TEXT)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_cmd_hist_cmd_id ON CommandsHistory(cmd_id)")
        except Exception:
            pass
        _record_migration(cur,2,now)
        ver=2
    if ver<3:
        try:
            _ensure_columns(cur,"Notes",(
                ("note_name","TEXT"),
                ("content","TEXT"),
                ("created_at","TEXT"),
                ("updated_at","TEXT"),
            ))
        except Exception:
            pass
        try:
            _ensure_columns(cur,"CommandsNotes",(
                ("note_name","TEXT"),
                ("category","TEXT"),
                ("sub_category","TEXT"),
                ("command","TEXT"),
                ("tags","TEXT"),
                ("description","TEXT"),
                ("created_at","TEXT"),
                ("updated_at","TEXT"),
            ))
        except Exception:
            pass
        try:
            _ensure_columns(cur,"Commands",(
                ("note_id","INTEGER"),
                ("note_name","TEXT"),
                ("cmd_note_title","TEXT"),
                ("category","TEXT"),
                ("sub_category","TEXT"),
                ("description","TEXT"),
                ("tags","TEXT"),
                ("command","TEXT"),
                ("created_at","TEXT"),
                ("updated_at","TEXT"),
            ))
        except Exception:
            pass
        _record_migration(cur,3,now)
        ver=3
    if ver<4:
        _dedupe_notes_for_unique_name(cur,con)
        try:
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_notes_name ON Notes(note_name)")
        except Exception:
            pass
        try:
            cur.execute("CREATE INDEX IF NOT EXISTS idx_notes_note_name ON Notes(note_name)")
        except Exception:
            pass
        try:
            cur.execute("CREATE INDEX IF NOT EXISTS idx_notes_updated ON Notes(updated_at)")
        except Exception:
            pass
        try:
            cur.execute("CREATE INDEX IF NOT EXISTS idx_cmdn_note_name ON CommandsNotes(note_name)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_cmdn_category ON CommandsNotes(category)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_cmdn_sub_category ON CommandsNotes(sub_category)")
        except Exception:
            pass
        try:
            cur.execute("CREATE INDEX IF NOT EXISTS idx_cmd_note_id ON Commands(note_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_cmd_note_name ON Commands(note_name)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_cmd_category ON Commands(category)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_cmd_sub_category ON Commands(sub_category)")
        except Exception:
            pass
        _record_migration(cur,4,now)
        ver=4
    if ver<5:
        try:
            _ensure_columns(cur,"Notes",(
                ("group_name","TEXT"),
            ))
        except Exception:
            pass
        try:
            _ensure_columns(cur,"NotesHistory",(
                ("group_name","TEXT"),
            ))
        except Exception:
            pass
        try:
            cur.execute("CREATE INDEX IF NOT EXISTS idx_notes_group_name ON Notes(group_name)")
        except Exception:
            pass
        _record_migration(cur,5,now)
        ver=5
    if ver<6:
        try:
            cur.execute("CREATE TABLE IF NOT EXISTS RecycleBin(id INTEGER PRIMARY KEY AUTOINCREMENT,entity_type TEXT NOT NULL,entity_key TEXT,label TEXT,payload TEXT NOT NULL,source TEXT,deleted_at TEXT NOT NULL,expires_at TEXT NOT NULL)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_recycle_type ON RecycleBin(entity_type)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_recycle_deleted_at ON RecycleBin(deleted_at)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_recycle_expires_at ON RecycleBin(expires_at)")
        except Exception:
            pass
        _record_migration(cur,6,now)
        ver=6
    if ver<7:
        try:
            _ensure_columns(cur,"Notes",(
                ("tags","TEXT"),
            ))
        except Exception:
            pass
        try:
            cur.execute("CREATE INDEX IF NOT EXISTS idx_notes_tags ON Notes(tags)")
        except Exception:
            pass
        _record_migration(cur,7,now)
        ver=7
    if ver<8:
        try:
            _ensure_columns(cur,"CommandsNotes",(
                ("command_type","TEXT DEFAULT 'other'"),
            ))
        except Exception:
            pass
        try:
            _ensure_columns(cur,"Commands",(
                ("command_type","TEXT DEFAULT 'other'"),
            ))
        except Exception:
            pass
        _record_migration(cur,8,now)
        ver=8
    if ver<9:
        try:
            _ensure_columns(cur,"CommandsNotes",(
                ("noise_level","TEXT DEFAULT 'normal'"),
            ))
        except Exception:
            pass
        try:
            _ensure_columns(cur,"Commands",(
                ("noise_level","TEXT DEFAULT 'normal'"),
            ))
        except Exception:
            pass
        try:
            cur.execute("CREATE TABLE IF NOT EXISTS CommandRuns(id INTEGER PRIMARY KEY AUTOINCREMENT,command_id INTEGER,src TEXT,text TEXT,target_snapshot TEXT,ran_at TEXT NOT NULL)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_command_runs_cmd ON CommandRuns(command_id,src)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_command_runs_ran_at ON CommandRuns(ran_at)")
        except Exception:
            pass
        _record_migration(cur,9,now)
        ver=9
    if ver<10:
        try:
            cur.execute("CREATE TABLE IF NOT EXISTS Playbooks(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,created_at TEXT,updated_at TEXT)")
            cur.execute("CREATE TABLE IF NOT EXISTS PlaybookSteps(id INTEGER PRIMARY KEY AUTOINCREMENT,playbook_id INTEGER NOT NULL,command_id INTEGER NOT NULL,command_src TEXT NOT NULL,position INTEGER NOT NULL)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_playbook_steps_playbook ON PlaybookSteps(playbook_id,position)")
        except Exception:
            pass
        _record_migration(cur,10,now)
        ver=10
    if ver<11:
        try:
            cur.execute("CREATE TABLE IF NOT EXISTS TerminalJobs(id INTEGER PRIMARY KEY AUTOINCREMENT,job_key TEXT NOT NULL UNIQUE,session_id TEXT,label TEXT,command TEXT,source TEXT,state TEXT NOT NULL,exit_code INTEGER,started_at TEXT NOT NULL,ended_at TEXT,cwd TEXT,bytes_out INTEGER DEFAULT 0)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_terminal_jobs_started ON TerminalJobs(started_at)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_terminal_jobs_state ON TerminalJobs(state)")
        except Exception:
            pass
        _record_migration(cur,11,now)
        ver=11
    if ver<12:
        try:
            cur.execute("ALTER TABLE TerminalJobs ADD COLUMN chain_id TEXT")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE TerminalJobs ADD COLUMN chain_pos INTEGER")
        except Exception:
            pass
        try:
            cur.execute("CREATE INDEX IF NOT EXISTS idx_terminal_jobs_chain ON TerminalJobs(chain_id,chain_pos)")
        except Exception:
            pass
        _record_migration(cur,12,now)
        ver=12
    if ver<13:
        _create_reporting_tables(cur)
        _record_migration(cur,13,now)
        ver=13
    if ver<14:
        _migrate_chain_callers(cur)
        _record_migration(cur,14,now)
        ver=14
    if ver<15:
        _create_cve_tables(cur)
        _record_migration(cur,15,now)
        ver=15
    if ver<16:
        _create_chain_graph_tables(cur)
        _record_migration(cur,16,now)
        ver=16
    if ver<17:
        # Report scope from Targets: two new tables in _REPORTING_TABLES. Additive only.
        _create_reporting_tables(cur)
        _record_migration(cur,17,now)
        ver=17
    if ver<18:
        _create_storage_tables(cur)
        _record_migration(cur,18,now)
        ver=18
    # Writing user_version rewrites the DB header (new mtime) even when unchanged; Mini and the targets cache poll that mtime.
    if start_ver!=DB_SCHEMA_VERSION:
        try:
            cur.execute(f"PRAGMA user_version={DB_SCHEMA_VERSION}")
        except Exception:
            pass
    try:
        con.commit()
    except Exception:
        pass
def ensure_schema(con):
    if _LOCKED:raise DatabaseLocked(LOCKED_MESSAGE)
    if at_rest_locked():raise DatabaseLocked(ENCRYPTED_MESSAGE)
    cur=con.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS Notes(id INTEGER PRIMARY KEY AUTOINCREMENT,note_name TEXT,group_name TEXT,tags TEXT,content TEXT,created_at TEXT,updated_at TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS CommandsNotes(id INTEGER PRIMARY KEY AUTOINCREMENT,note_name TEXT,category TEXT,sub_category TEXT,command TEXT,tags TEXT,description TEXT,command_type TEXT DEFAULT 'other',noise_level TEXT DEFAULT 'normal',created_at TEXT,updated_at TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS Commands(id INTEGER PRIMARY KEY AUTOINCREMENT,note_id INTEGER,note_name TEXT,cmd_note_title TEXT,category TEXT,sub_category TEXT,description TEXT,tags TEXT,command TEXT,command_type TEXT DEFAULT 'other',noise_level TEXT DEFAULT 'normal',created_at TEXT,updated_at TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS RecycleBin(id INTEGER PRIMARY KEY AUTOINCREMENT,entity_type TEXT NOT NULL,entity_key TEXT,label TEXT,payload TEXT NOT NULL,source TEXT,deleted_at TEXT NOT NULL,expires_at TEXT NOT NULL)")
    cur.execute("CREATE TABLE IF NOT EXISTS CommandRuns(id INTEGER PRIMARY KEY AUTOINCREMENT,command_id INTEGER,src TEXT,text TEXT,target_snapshot TEXT,ran_at TEXT NOT NULL)")
    cur.execute("CREATE TABLE IF NOT EXISTS Playbooks(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,created_at TEXT,updated_at TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS TerminalJobs(id INTEGER PRIMARY KEY AUTOINCREMENT,job_key TEXT NOT NULL UNIQUE,session_id TEXT,label TEXT,command TEXT,source TEXT,state TEXT NOT NULL,exit_code INTEGER,started_at TEXT NOT NULL,ended_at TEXT,cwd TEXT,bytes_out INTEGER DEFAULT 0)")
    cur.execute("CREATE TABLE IF NOT EXISTS PlaybookSteps(id INTEGER PRIMARY KEY AUTOINCREMENT,playbook_id INTEGER NOT NULL,command_id INTEGER NOT NULL,command_src TEXT NOT NULL,position INTEGER NOT NULL)")
    _create_reporting_tables(cur)
    _create_chain_graph_tables(cur)
    _create_storage_tables(cur)
    apply_migrations(con)
    try:
        con.commit()
    except Exception:
        pass
