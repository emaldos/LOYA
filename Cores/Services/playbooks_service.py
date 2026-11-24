from datetime import datetime,timezone
from Cores import common_db as _common_db
from Cores import chain_callers as _callers
from Cores.Services import commands_service as _commands_svc
def _db_path():
    return _common_db.db_path()
def _ensure_schema(con):
    _common_db.ensure_schema(con)
    _ensure_caller_column(con)
_caller_column_ok=False
def _ensure_caller_column(con):
    # Self-heal: the v14 migration adds the column, but never trust a user_version another build may have written.
    global _caller_column_ok
    if _caller_column_ok:return
    try:
        cols={r[1] for r in con.execute("PRAGMA table_info(Playbooks)").fetchall()}
        if "caller" not in cols:
            con.execute("ALTER TABLE Playbooks ADD COLUMN caller TEXT")
            con.commit()
        _caller_column_ok=True
    except Exception:
        pass
def _norm(s):return (str(s) if s is not None else "").strip()
def _taken_callers(cur,exclude_id=None):
    cur.execute("SELECT id,caller FROM Playbooks WHERE caller IS NOT NULL AND caller<>''")
    return {str(c).lower() for pid,c in cur.fetchall() if exclude_id is None or int(pid)!=int(exclude_id)}
def _checked_caller(cur,caller,exclude_id=None):
    """Normalized caller, or raises ValueError. An empty caller is allowed and means "no caller"."""
    value=_callers.normalize_caller(caller)
    if not value:return ""
    err=_callers.caller_error(value)
    if err:raise ValueError(err)
    if value in _taken_callers(cur,exclude_id):raise ValueError(f"/{value} is already used by another action chain.")
    return value
def validate_caller(caller,playbook_id=None):
    """{"ok","caller","error"} for the chain form: lets the page check a caller as it is typed."""
    try:
        with _common_db.connection(_db_path(),timeout=5) as con:
            _ensure_schema(con)
            value=_checked_caller(con.cursor(),caller,playbook_id)
        return {"ok":True,"caller":value,"error":""}
    except ValueError as exc:
        return {"ok":False,"caller":_callers.normalize_caller(caller),"error":str(exc)}
def suggest_caller(name,playbook_id=None):
    with _common_db.connection(_db_path(),timeout=5) as con:
        _ensure_schema(con)
        return _callers.suggest_caller(name,_taken_callers(con.cursor(),playbook_id))
def list_playbooks():
    dbp=_db_path()
    out=[]
    try:
        with _common_db.connection(dbp,timeout=5) as con:
            _ensure_schema(con)
            cur=con.cursor()
            cur.execute("SELECT id,name,created_at,updated_at,caller FROM Playbooks ORDER BY name COLLATE NOCASE")
            rows=cur.fetchall()
            for r in rows:
                cur.execute("SELECT COUNT(*) FROM PlaybookSteps WHERE playbook_id=?",(r[0],))
                count=cur.fetchone()[0]
                out.append({"id":r[0],"name":r[1] or "","created_at":r[2] or "","updated_at":r[3] or "","step_count":count,"caller":r[4] or ""})
    except Exception:
        pass
    return out
def create_playbook(name,caller=None):
    """caller=None picks a free caller from the name; "" creates the chain without one."""
    name=_norm(name)
    if not name:raise ValueError("Action chain name is required.")
    dbp=_db_path()
    now=datetime.now(timezone.utc).isoformat()
    with _common_db.connection(dbp,timeout=5) as con:
        _ensure_schema(con)
        cur=con.cursor()
        value=_callers.suggest_caller(name,_taken_callers(cur)) if caller is None else _checked_caller(cur,caller)
        cur.execute("INSERT INTO Playbooks(name,created_at,updated_at,caller) VALUES(?,?,?,?)",(name,now,now,value or None))
        con.commit()
        return int(cur.lastrowid)
def rename_playbook(playbook_id,name):
    name=_norm(name)
    if not name:raise ValueError("Action chain name is required.")
    dbp=_db_path()
    now=datetime.now(timezone.utc).isoformat()
    with _common_db.connection(dbp,timeout=5) as con:
        _ensure_schema(con)
        cur=con.cursor()
        cur.execute("UPDATE Playbooks SET name=?,updated_at=? WHERE id=?",(name,now,int(playbook_id)))
        con.commit()
        return bool(cur.rowcount)
def set_caller(playbook_id,caller):
    """Set or clear ("") a chain's caller. Returns the stored caller."""
    dbp=_db_path()
    now=datetime.now(timezone.utc).isoformat()
    with _common_db.connection(dbp,timeout=5) as con:
        _ensure_schema(con)
        cur=con.cursor()
        cur.execute("SELECT id FROM Playbooks WHERE id=?",(int(playbook_id),))
        if not cur.fetchone():raise ValueError("Action chain not found.")
        value=_checked_caller(cur,caller,playbook_id)
        cur.execute("UPDATE Playbooks SET caller=?,updated_at=? WHERE id=?",(value or None,now,int(playbook_id)))
        con.commit()
        return value
def list_callers():
    """Chains that have a caller, for the terminal and AI "/" suggestions: [{id,caller,name,steps,description}]."""
    out=[]
    for pb in list_playbooks():
        if not pb.get("caller"):continue
        out.append({"id":pb["id"],"caller":pb["caller"],"name":pb["name"],"steps":pb["step_count"],"description":""})
    if not out:return out
    # The description lists the step titles, so a suggestion says what the chain does.
    try:
        _dbp2,cmds=_commands_svc._load_cmds()
        by_key={(c["id"],c["src"]):c for c in cmds}
        with _common_db.connection(_db_path(),timeout=5) as con:
            _ensure_schema(con)
            rows=con.execute("SELECT playbook_id,command_id,command_src FROM PlaybookSteps ORDER BY playbook_id,position ASC").fetchall()
        titles={}
        for pid,cid,csrc in rows:
            cmd=by_key.get((cid,csrc))
            if cmd:titles.setdefault(pid,[]).append(_norm(cmd.get("title")) or _norm(cmd.get("category")) or "step")
        for item in out:
            item["description"]=" > ".join(titles.get(item["id"],[]))[:200]
    except Exception:
        pass
    return out
def find_by_caller(caller):
    value=_callers.normalize_caller(caller)
    if not value:return None
    for pb in list_playbooks():
        if pb.get("caller")==value:return pb
    return None
def delete_playbook(playbook_id):
    dbp=_db_path()
    with _common_db.connection(dbp,timeout=5) as con:
        _ensure_schema(con)
        cur=con.cursor()
        cur.execute("DELETE FROM PlaybookSteps WHERE playbook_id=?",(int(playbook_id),))
        cur.execute("DELETE FROM Playbooks WHERE id=?",(int(playbook_id),))
        con.commit()
        return bool(cur.rowcount)
def get_playbook(playbook_id):
    dbp=_db_path()
    with _common_db.connection(dbp,timeout=5) as con:
        _ensure_schema(con)
        cur=con.cursor()
        cur.execute("SELECT id,name,created_at,updated_at,caller FROM Playbooks WHERE id=?",(int(playbook_id),))
        row=cur.fetchone()
        if not row:return None
        cur.execute("SELECT id,command_id,command_src,position FROM PlaybookSteps WHERE playbook_id=? ORDER BY position ASC",(int(playbook_id),))
        step_rows=cur.fetchall()
    _dbp2,cmds=_commands_svc._load_cmds()
    by_key={(c["id"],c["src"]):c for c in cmds}
    steps=[]
    for sid,cid,csrc,pos in step_rows:
        cmd=by_key.get((cid,csrc))
        steps.append({"step_id":sid,"command_id":cid,"command_src":csrc,"position":pos,"command":({k:v for k,v in cmd.items() if k!="db"} if cmd else None)})
    return {"id":row[0],"name":row[1] or "","created_at":row[2] or "","updated_at":row[3] or "","caller":row[4] or "","steps":steps}
def playbook_commands(playbook_id):
    book=get_playbook(playbook_id)
    if not book:return []
    out=[]
    for step in book["steps"]:
        cmd=step.get("command")
        if not cmd:continue
        text=_norm(cmd.get("command"))
        if not text:continue
        out.append({"label":_norm(cmd.get("title")) or _norm(cmd.get("category")) or "step","command":text,"noise_level":cmd.get("noise_level") or "normal"})
    return out
def add_step(playbook_id,command_id,command_src):
    dbp=_db_path()
    now=datetime.now(timezone.utc).isoformat()
    with _common_db.connection(dbp,timeout=5) as con:
        _ensure_schema(con)
        cur=con.cursor()
        cur.execute("SELECT COALESCE(MAX(position),-1) FROM PlaybookSteps WHERE playbook_id=?",(int(playbook_id),))
        nextpos=int(cur.fetchone()[0])+1
        cur.execute("INSERT INTO PlaybookSteps(playbook_id,command_id,command_src,position) VALUES(?,?,?,?)",(int(playbook_id),int(command_id),_norm(command_src),nextpos))
        cur.execute("UPDATE Playbooks SET updated_at=? WHERE id=?",(now,int(playbook_id)))
        con.commit()
        return int(cur.lastrowid)
def remove_step(step_id):
    dbp=_db_path()
    with _common_db.connection(dbp,timeout=5) as con:
        _ensure_schema(con)
        cur=con.cursor()
        cur.execute("SELECT playbook_id FROM PlaybookSteps WHERE id=?",(int(step_id),))
        row=cur.fetchone()
        if not row:return False
        pid=row[0]
        cur.execute("DELETE FROM PlaybookSteps WHERE id=?",(int(step_id),))
        cur.execute("SELECT id FROM PlaybookSteps WHERE playbook_id=? ORDER BY position ASC",(pid,))
        for i,(sid,) in enumerate(cur.fetchall()):
            cur.execute("UPDATE PlaybookSteps SET position=? WHERE id=?",(i,sid))
        con.commit()
        return True
def move_step(step_id,direction):
    dbp=_db_path()
    with _common_db.connection(dbp,timeout=5) as con:
        _ensure_schema(con)
        cur=con.cursor()
        cur.execute("SELECT playbook_id,position FROM PlaybookSteps WHERE id=?",(int(step_id),))
        row=cur.fetchone()
        if not row:return False
        pid,pos=row
        newpos=pos+(1 if direction>0 else -1)
        cur.execute("SELECT id FROM PlaybookSteps WHERE playbook_id=? AND position=?",(pid,newpos))
        other=cur.fetchone()
        if not other:return False
        other_id=other[0]
        cur.execute("UPDATE PlaybookSteps SET position=? WHERE id=?",(newpos,int(step_id)))
        cur.execute("UPDATE PlaybookSteps SET position=? WHERE id=?",(pos,other_id))
        con.commit()
        return True
