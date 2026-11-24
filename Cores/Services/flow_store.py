"""Chain Diagrams storage: one ChainGraphs row per Action Chain that has a diagram, and the ChainRuns history.
Every function opens its own short-lived connection through _con() (the single place to switch to db_driver later)."""
import json
from datetime import datetime,timezone
from Cores import common_db
RUN_DATA_MAX=768*1024
RUNS_KEEP=300
_RUN_COLUMNS="run_id,playbook_id,chain_name,mode,state,source,target,started_at,ended_at"
def _now():return datetime.now(timezone.utc).isoformat()
def _con():
    con=common_db.connect(common_db.db_path(),timeout=5)
    try:
        common_db.ensure_schema(con)
    except Exception:
        con.close()
        raise
    return con
def _pid(playbook_id):
    try:return int(playbook_id)
    except (TypeError,ValueError):raise ValueError("Invalid action chain id.")
def _graph_row(row):
    if not row:return None
    try:graph=json.loads(row[1])
    except Exception:graph=None
    return {"playbook_id":row[0],"graph":graph if isinstance(graph,dict) else None,"schema_version":row[2],"ai_made":bool(row[3]),"ai_reviewed":bool(row[4]),"ai_client":row[5] or "","created_at":row[6] or "","updated_at":row[7] or ""}
def get_graph_row(playbook_id):
    """The stored diagram of a chain, or None when the chain is still linear."""
    con=_con()
    try:
        row=con.execute("SELECT playbook_id,graph,schema_version,ai_made,ai_reviewed,ai_client,created_at,updated_at FROM ChainGraphs WHERE playbook_id=?",(_pid(playbook_id),)).fetchone()
    finally:
        con.close()
    return _graph_row(row)
def has_graph(playbook_id):
    con=_con()
    try:
        return con.execute("SELECT 1 FROM ChainGraphs WHERE playbook_id=?",(_pid(playbook_id),)).fetchone() is not None
    finally:
        con.close()
def graph_index():
    """{playbook_id:{"node_count","ai_made","ai_reviewed","ai_client","updated_at"}} for every chain that has a diagram."""
    con=_con()
    try:
        rows=con.execute("SELECT playbook_id,graph,ai_made,ai_reviewed,updated_at,ai_client FROM ChainGraphs").fetchall()
    finally:
        con.close()
    out={}
    for pid,text,ai_made,ai_reviewed,updated,client in rows:
        try:count=len((json.loads(text) or {}).get("nodes") or [])
        except Exception:count=0
        out[int(pid)]={"node_count":count,"ai_made":bool(ai_made),"ai_reviewed":bool(ai_reviewed),"ai_client":client or "","updated_at":updated or ""}
    return out
def subchain_refs():
    """{playbook_id:[playbook ids its sub-chain nodes run]} for every stored diagram (cycle detection)."""
    con=_con()
    try:
        rows=con.execute("SELECT playbook_id,graph FROM ChainGraphs").fetchall()
    finally:
        con.close()
    out={}
    for pid,text in rows:
        try:nodes=(json.loads(text) or {}).get("nodes") or []
        except Exception:nodes=[]
        children=[]
        for node in nodes:
            if not isinstance(node,dict) or node.get("type")!="subchain":continue
            try:children.append(int((node.get("config") or {}).get("playbook_id")))
            except (TypeError,ValueError):continue
        out[int(pid)]=children
    return out
def save_graph(playbook_id,graph,ai_made=None,ai_reviewed=None,ai_client=None,schema_version=1):
    """Insert or replace a chain's diagram. The AI flags are kept as they are when left at None."""
    if not isinstance(graph,dict):raise ValueError("The diagram must be an object.")
    pid=_pid(playbook_id)
    text=json.dumps(graph,ensure_ascii=False,separators=(",",":"))
    now=_now()
    con=_con()
    try:
        cur=con.cursor()
        if cur.execute("SELECT 1 FROM Playbooks WHERE id=?",(pid,)).fetchone() is None:raise ValueError("Action chain not found.")
        old=cur.execute("SELECT ai_made,ai_reviewed,ai_client,created_at FROM ChainGraphs WHERE playbook_id=?",(pid,)).fetchone()
        made=int(bool(ai_made)) if ai_made is not None else (old[0] if old else 0)
        reviewed=int(bool(ai_reviewed)) if ai_reviewed is not None else (old[1] if old else 1)
        client=(str(ai_client)[:120] or None) if ai_client is not None else (old[2] if old else None)
        cur.execute("INSERT OR REPLACE INTO ChainGraphs(playbook_id,graph,schema_version,ai_made,ai_reviewed,ai_client,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",(pid,text,int(schema_version or 1),made,reviewed,client,(old[3] if old else None) or now,now))
        cur.execute("UPDATE Playbooks SET updated_at=? WHERE id=?",(now,pid))
        con.commit()
    finally:
        con.close()
    return {"playbook_id":pid,"created":old is None,"ai_made":bool(made),"ai_reviewed":bool(reviewed)}
def set_reviewed(playbook_id,reviewed=True,clear_ai_made=False):
    """clear_ai_made: an explicit operator review also drops the AI-made flag (the chain becomes a normal chain)."""
    con=_con()
    try:
        if clear_ai_made and reviewed:changed=con.execute("UPDATE ChainGraphs SET ai_reviewed=1,ai_made=0 WHERE playbook_id=?",(_pid(playbook_id),)).rowcount
        else:changed=con.execute("UPDATE ChainGraphs SET ai_reviewed=? WHERE playbook_id=?",(1 if reviewed else 0,_pid(playbook_id))).rowcount
        con.commit()
    finally:
        con.close()
    return changed>0
def delete_graph(playbook_id):
    """Back to a linear chain (or the chain itself was deleted). PlaybookSteps are never touched."""
    con=_con()
    try:
        changed=con.execute("DELETE FROM ChainGraphs WHERE playbook_id=?",(_pid(playbook_id),)).rowcount
        con.commit()
    finally:
        con.close()
    return changed>0
def _tail(text,limit):
    text=str(text or "")
    return text if len(text)<=limit else text[-limit:]
def _capped_run_json(status):
    """The run status as JSON, shrunk in steps (node output, then old events) until it fits RUN_DATA_MAX."""
    text=json.dumps(status,ensure_ascii=False,separators=(",",":"),default=str)
    if len(text)<=RUN_DATA_MAX:return text
    slim=json.loads(text)
    for limit in (8192,1024,0):
        for node in (slim.get("nodes") or {}).values():
            out=node.get("output") if isinstance(node,dict) else None
            if not isinstance(out,dict):continue
            for key in ("stdout","stderr"):out[key]=_tail(out.get(key),limit)
            if limit<=1024:out["parsed"]=None
            if limit==0:out["trace"]=[];out["resolved"]=[str(c)[:200] for c in (out.get("resolved") or [])[:20]]
        if limit<=1024:slim["events"]=(slim.get("events") or [])[-200:]
        if limit==0:slim["vars"]={}
        slim["truncated"]=True
        text=json.dumps(slim,ensure_ascii=False,separators=(",",":"),default=str)
        if len(text)<=RUN_DATA_MAX:return text
    return json.dumps({k:slim.get(k) for k in ("run_id","playbook_id","name","mode","state","reason","source","target","started_at","ended_at")}|{"nodes":{},"events":[],"edges_taken":[],"truncated":True},default=str)
def save_run(status):
    """Insert or replace one run's snapshot. Raises (DatabaseLocked included) when the DB cannot be written; the engine retries."""
    if not isinstance(status,dict) or not status.get("run_id"):raise ValueError("A run status with a run_id is required.")
    data=_capped_run_json(status)
    pid=status.get("playbook_id")
    con=_con()
    try:
        con.execute("INSERT INTO ChainRuns(run_id,playbook_id,chain_name,mode,state,source,target,started_at,ended_at,data) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET state=excluded.state,ended_at=excluded.ended_at,data=excluded.data",(str(status["run_id"]),int(pid) if pid is not None else None,str(status.get("name") or "")[:200],str(status.get("mode") or "run"),str(status.get("state") or ""),str(status.get("source") or ""),str(status.get("target") or "")[:200],str(status.get("started_at") or _now()),status.get("ended_at") or None,data))
        # History is bounded: the oldest runs beyond RUNS_KEEP go, with their logs.
        old=[r[0] for r in con.execute("SELECT run_id FROM ChainRuns WHERE id NOT IN (SELECT id FROM ChainRuns ORDER BY id DESC LIMIT ?)",(RUNS_KEEP,)).fetchall()]
        if old:
            con.executemany("DELETE FROM ChainRunLogs WHERE run_id=?",[(r,) for r in old])
            con.executemany("DELETE FROM ChainRuns WHERE run_id=?",[(r,) for r in old])
        con.commit()
    finally:
        con.close()
    return True
def list_runs(playbook_id=None,limit=30):
    try:limit=max(1,min(int(limit or 30),200))
    except (TypeError,ValueError):limit=30
    query="SELECT "+_RUN_COLUMNS+" FROM ChainRuns"
    params=[]
    if playbook_id is not None:
        query+=" WHERE playbook_id=?"
        params.append(_pid(playbook_id))
    query+=" ORDER BY id DESC LIMIT ?"
    params.append(limit)
    con=_con()
    try:
        rows=con.execute(query,params).fetchall()
    finally:
        con.close()
    keys=_RUN_COLUMNS.split(",")
    return [dict(zip(keys,(v if v is not None else ("" if k!="playbook_id" else None) for k,v in zip(keys,row)))) for row in rows]
def get_run(run_id):
    """The stored final status of a run, or None."""
    con=_con()
    try:
        row=con.execute("SELECT data FROM ChainRuns WHERE run_id=?",(str(run_id or ""),)).fetchone()
    finally:
        con.close()
    if not row:return None
    try:
        data=json.loads(row[0] or "")
        return data if isinstance(data,dict) else None
    except Exception:
        return None
def delete_run(run_id):
    con=_con()
    try:
        changed=con.execute("DELETE FROM ChainRuns WHERE run_id=?",(str(run_id or ""),)).rowcount
        logs=con.execute("DELETE FROM ChainRunLogs WHERE run_id=?",(str(run_id or ""),)).rowcount
        con.commit()
    finally:
        con.close()
    return changed>0 or logs>0
def clear_runs(playbook_id=None):
    """Delete finished runs (all, or one chain's) with their logs. Logs of runs that are still going are left alone."""
    con=_con()
    try:
        if playbook_id is None:rows=con.execute("SELECT run_id FROM ChainRuns").fetchall()
        else:rows=con.execute("SELECT run_id FROM ChainRuns WHERE playbook_id=?",(_pid(playbook_id),)).fetchall()
        ids=[(r[0],) for r in rows]
        con.executemany("DELETE FROM ChainRunLogs WHERE run_id=?",ids)
        con.executemany("DELETE FROM ChainRuns WHERE run_id=?",ids)
        con.commit()
    finally:
        con.close()
    return len(ids)
# ---- structured run logs (ChainRunLogs) ----------------------------------------------------------------------------
def append_run_log(run_id,entries):
    """Write a batch of log entries ({"seq","ts","node","title","level","kind","text","data"}). Raises when the DB cannot be written."""
    rows=[]
    for entry in entries or []:
        data=dict(entry.get("data") or {})
        if entry.get("title"):data["_title"]=entry["title"]
        rows.append((str(run_id),int(entry.get("seq") or 0),str(entry.get("ts") or _now()),entry.get("node"),str(entry.get("level") or "info"),str(entry.get("kind") or "info"),str(entry.get("text") or ""),json.dumps(data,ensure_ascii=False,separators=(",",":"),default=str) if data else None))
    if not rows:return 0
    con=_con()
    try:
        con.executemany("INSERT INTO ChainRunLogs(run_id,seq,ts,node,level,kind,text,data) VALUES(?,?,?,?,?,?,?,?)",rows)
        con.commit()
    finally:
        con.close()
    return len(rows)
def _log_entry(row):
    try:data=json.loads(row[6]) if row[6] else {}
    except Exception:data={}
    if not isinstance(data,dict):data={}
    title=str(data.pop("_title","") or "")
    return {"seq":row[0],"ts":row[1],"node":row[2],"title":title,"level":row[3],"kind":row[4],"text":row[5] or "","data":data}
def get_run_log(run_id,since=0,limit=2000):
    """-> (entries with seq>since in order, total number of entries of that run)."""
    try:since=int(since or 0)
    except (TypeError,ValueError):since=0
    try:limit=max(1,min(int(limit or 2000),20000))
    except (TypeError,ValueError):limit=2000
    con=_con()
    try:
        rows=con.execute("SELECT seq,ts,node,level,kind,text,data FROM ChainRunLogs WHERE run_id=? AND seq>? ORDER BY seq ASC,id ASC LIMIT ?",(str(run_id or ""),since,limit)).fetchall()
        total=con.execute("SELECT COUNT(*) FROM ChainRunLogs WHERE run_id=?",(str(run_id or ""),)).fetchone()[0]
    finally:
        con.close()
    return [_log_entry(r) for r in rows],int(total)
def run_log_seq(run_id):
    """Highest stored seq of a run's log (0 when it has none)."""
    con=_con()
    try:
        row=con.execute("SELECT MAX(seq) FROM ChainRunLogs WHERE run_id=?",(str(run_id or ""),)).fetchone()
    finally:
        con.close()
    return int(row[0] or 0)
