"""Chain Run History and chain/run bundles: what the Run History sub-tab of the Chains page (bridge chainHistory.*) and the
chain-history MCP tools call. Reads and writes ChainRuns / ChainRunLogs / ChainGraphs through flow_store's connection helper;
runs that are still going live in flow_engine and are never deleted from here.

Bundle format (export and import), a JSON object:
    {"format":"loya-chain-bundle","version":1,"app":"LOYA NG","app_version":"1.0.0","exported_at":"...Z",
     "contents":["chains","runs"],
     "chains":[{"ref":"c12","source_id":12,"name","caller","derived":bool,"origin":{"ai_made":bool,"ai_client":str},"graph":{...}}],
     "runs":[{"run_id","chain_ref":"c12"|None,"source_playbook_id":12|None,"chain_name","mode","state","source","target",
              "started_at","ended_at","node_titles":{node_id:title},"status":{...},"log":[{seq,ts,node,title,level,kind,text,data}]}]}
A single-chain export of flows.export_json ({"loya_chain":1,...}) and a bare graph are accepted on import too.

Import never trusts the file: every diagram goes through flow_schema validation, an imported chain is stored unreviewed (the run
confirmation then demands the review, exactly like an AI-made chain; an origin marked AI-made stays AI-made), a diagram can
never loosen script isolation (settings.script_isolation "allow" becomes "inherit"), sub-chain links are re-pointed only to
chains of the same bundle, and imported runs are stored with mode "import" so they are history only (never the seed of a
"re-run from this node")."""
import json,re
from datetime import datetime,timezone
from Cores import common_db
from Cores.Services import flow_schema as _schema
from Cores.Services import flow_store as _store
from Cores.Services import flow_engine as _engine
from Cores.Services import playbooks_service as _chains
BUNDLE_FORMAT="loya-chain-bundle"
BUNDLE_VERSION=1
IMPORT_MAX_BYTES=64*1024*1024
MAX_CHAINS=500
MAX_RUNS=_store.RUNS_KEEP
PAGE_MAX=200
STATES=("done","failed","cancelled","timeout","running","paused","waiting_approval")
FINAL_STATES=("done","failed","cancelled","timeout")
CHAIN_CONFLICT_MODES=("rename","skip","replace")
RUN_CONFLICT_MODES=("skip","replace","rename")
IMPORTED_MODE="import"
_RUN_ID_RX=re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
_LOG_LEVELS=("info","warn","error")
_LOCKED_MESSAGE=common_db.LOCKED_MESSAGE
def _now():return datetime.now(timezone.utc).isoformat()
def _stamp():return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
def _audit(event,detail,success=True):
    try:
        from Cores.Services import security_service
        security_service.log_audit_event(event,str(detail)[:1000],success)
    except Exception:
        pass
def _guard():
    if common_db.db_locked():raise ValueError(_LOCKED_MESSAGE)
def _text(value,limit):
    return ("" if value is None else str(value))[:limit]
def _int(value,default=None):
    if isinstance(value,bool):return default
    try:return int(value)
    except (TypeError,ValueError):return default
def _parse_ts(value):
    try:
        ts=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    except (TypeError,ValueError):return None
def duration_ms(started,ended):
    a,b=_parse_ts(started),_parse_ts(ended)
    if a is None or b is None:return None
    return max(0,int((b-a).total_seconds()*1000))
def node_counts(status):
    """{"total","success","fail","skipped","pending","running","other"} from a run status' nodes."""
    out={"total":0,"success":0,"fail":0,"skipped":0,"pending":0,"running":0,"other":0}
    nodes=(status or {}).get("nodes") if isinstance(status,dict) else None
    for rec in (nodes.values() if isinstance(nodes,dict) else []):
        state=str((rec or {}).get("state") or "pending") if isinstance(rec,dict) else "pending"
        out["total"]+=1
        key={"success":"success","fail":"fail","failed":"fail","skipped":"skipped","pending":"pending","planned":"pending","running":"running","waiting":"running"}.get(state,"other")
        out[key]+=1
    return out
# ---------------------------------------------------------------- listing
def _filters(raw):
    f=raw if isinstance(raw,dict) else {}
    out={"playbook_id":_int(f.get("playbook_id")),"chain":_text(f.get("chain"),200).strip(),"state":_text(f.get("state"),40).strip().lower(),
         "source":_text(f.get("source"),40).strip().lower(),"mode":_text(f.get("mode"),20).strip().lower(),"query":_text(f.get("query"),200).strip(),
         "date_from":_text(f.get("date_from"),40).strip(),"date_to":_text(f.get("date_to"),40).strip()}
    out["offset"]=max(0,_int(f.get("offset"),0) or 0)
    out["limit"]=max(1,min(PAGE_MAX,_int(f.get("limit"),50) or 50))
    return out
def _where(f):
    """SQL WHERE clause and parameters for the stored runs."""
    clauses,params=[],[]
    if f["playbook_id"] is not None:clauses.append("playbook_id=?");params.append(f["playbook_id"])
    if f["chain"]:clauses.append("LOWER(chain_name)=LOWER(?)");params.append(f["chain"])
    if f["state"]:clauses.append("state=?");params.append(f["state"])
    if f["source"]:clauses.append("LOWER(source)=?");params.append(f["source"])
    if f["mode"]:clauses.append("mode=?");params.append(f["mode"])
    if f["date_from"]:clauses.append("started_at>=?");params.append(f["date_from"])
    if f["date_to"]:clauses.append("started_at<=?");params.append(f["date_to"])
    for word in f["query"].lower().split()[:8]:
        like="%"+word.replace("\\","\\\\").replace("%","\\%").replace("_","\\_")+"%"
        clauses.append("(LOWER(chain_name) LIKE ? ESCAPE '\\' OR LOWER(target) LIKE ? ESCAPE '\\' OR LOWER(run_id) LIKE ? ESCAPE '\\' OR LOWER(source) LIKE ? ESCAPE '\\' OR LOWER(state) LIKE ? ESCAPE '\\')")
        params.extend([like]*5)
    return (" WHERE "+" AND ".join(clauses)) if clauses else "",params
def _live_matches(row,f):
    if f["playbook_id"] is not None and _int(row.get("playbook_id"))!=f["playbook_id"]:return False
    if f["chain"] and str(row.get("name") or "").lower()!=f["chain"].lower():return False
    if f["state"] and str(row.get("state") or "")!=f["state"]:return False
    if f["source"] and str(row.get("source") or "").lower()!=f["source"]:return False
    if f["mode"] and str(row.get("mode") or "")!=f["mode"]:return False
    started=str(row.get("started_at") or "")
    if f["date_from"] and started<f["date_from"]:return False
    if f["date_to"] and started>f["date_to"]:return False
    hay=" ".join(str(row.get(k) or "") for k in ("name","target","run_id","source","state")).lower()
    return all(w in hay for w in f["query"].lower().split()[:8])
def _chain_names():
    try:return {int(b["id"]):b["name"] for b in _chains.list_playbooks()}
    except Exception:return {}
def _row(run_id,playbook_id,chain_name,mode,state,source,target,started,ended,data,names,live=False):
    try:status=json.loads(data) if isinstance(data,str) and data else (data if isinstance(data,dict) else {})
    except ValueError:status={}
    if not isinstance(status,dict):status={}
    imported=mode==IMPORTED_MODE
    pid=_int(playbook_id)
    return {"run_id":run_id,"playbook_id":pid,"chain_name":chain_name or status.get("name") or "","chain_exists":pid in names,
            "current_name":names.get(pid,""),"mode":(str(status.get("mode") or "run") if imported else (mode or "run")),"imported":imported,
            "state":state or "","reason":_text(status.get("reason"),300),"source":source or "","target":target or "","started_at":started or "",
            "ended_at":ended or "","duration_ms":duration_ms(started,ended) if ended else None,"nodes":node_counts(status),"live":live,
            "truncated":bool(status.get("truncated"))}
def list_runs(filters=None):
    """One page of the run history, newest first. -> {"items","total","offset","limit","live"}. Runs still going (in memory)
    come first on the first page when they match the filters."""
    _guard()
    f=_filters(filters)
    _engine.flush_pending()
    where,params=_where(f)
    names=_chain_names()
    con=_store._con()
    try:
        total=con.execute("SELECT COUNT(*) FROM ChainRuns"+where,params).fetchone()[0]
        rows=con.execute("SELECT run_id,playbook_id,chain_name,mode,state,source,target,started_at,ended_at,data FROM ChainRuns"+where+" ORDER BY started_at DESC,id DESC LIMIT ? OFFSET ?",params+[f["limit"],f["offset"]]).fetchall()
    finally:
        con.close()
    items=[_row(*r,names) for r in rows]
    stored={i["run_id"] for i in items}
    active=_engine.active_runs()
    going={r.get("run_id") for r in active}
    for item in items:item["live"]=item["run_id"] in going   # a re-run from a node updates a stored row while it goes
    live=[]
    for summary in active:
        if summary.get("run_id") in stored or not _live_matches(summary,f):continue
        run=_engine.get_run(summary["run_id"])
        status=run.status() if run is not None else summary
        live.append(_row(summary["run_id"],summary.get("playbook_id"),summary.get("name"),summary.get("mode"),summary.get("state"),summary.get("source"),summary.get("target"),summary.get("started_at"),summary.get("ended_at"),status,names,live=True))
    if f["offset"]==0:items=live+items
    return {"items":items,"total":int(total)+len(live),"offset":f["offset"],"limit":f["limit"],"live":len(live)}
def facets():
    """What the filters can offer: every chain that has runs (with its count) and the states and triggers in use."""
    _guard()
    _engine.flush_pending()
    names=_chain_names()
    con=_store._con()
    try:
        chains=con.execute("SELECT playbook_id,chain_name,COUNT(*),MAX(started_at) FROM ChainRuns GROUP BY playbook_id,chain_name ORDER BY MAX(started_at) DESC").fetchall()
        states=con.execute("SELECT state,COUNT(*) FROM ChainRuns GROUP BY state").fetchall()
        sources=con.execute("SELECT source,COUNT(*) FROM ChainRuns GROUP BY source").fetchall()
        total=con.execute("SELECT COUNT(*) FROM ChainRuns").fetchone()[0]
    finally:
        con.close()
    merged={}
    for pid,name,count,last in chains:
        key=("id",int(pid)) if pid is not None else ("name",str(name or ""))
        entry=merged.setdefault(key,{"playbook_id":_int(pid),"name":names.get(_int(pid)) or name or "","count":0,"last":last or "","exists":_int(pid) in names})
        entry["count"]+=count
        if (last or "")>entry["last"]:entry["last"]=last or ""
    return {"chains":list(merged.values()),"states":{s or "":c for s,c in states},"sources":{s or "":c for s,c in sources},"total":int(total),
            "all_chains":[{"playbook_id":pid,"name":name} for pid,name in sorted(names.items(),key=lambda kv:kv[1].lower())]}
# ---------------------------------------------------------------- one run
def _graph_info(playbook_id):
    """({node_id:title},{node_id:type}) of a chain's current diagram (or derived straight line), empty when it is gone."""
    if playbook_id is None:return {},{}
    try:
        from Cores.Services import flow_service as _flows
        graph=_flows.get(playbook_id).get("graph") or {}
    except Exception:
        return {},{}
    titles,types={},{}
    for node in graph.get("nodes") or []:
        if isinstance(node,dict) and node.get("id"):
            titles[str(node["id"])]=str(node.get("title") or node.get("type") or node["id"])
            types[str(node["id"])]=str(node.get("type") or "")
    return titles,types
def _timeline(status,titles,types,tail=4000):
    out=[]
    for node_id,rec in ((status or {}).get("nodes") or {}).items():
        if not isinstance(rec,dict):continue
        output=rec.get("output") if isinstance(rec.get("output"),dict) else {}
        out.append({"node":str(node_id),"title":titles.get(str(node_id)) or str(node_id),"type":types.get(str(node_id),""),"state":str(rec.get("state") or "pending"),
                    "visits":_int(rec.get("visits"),0) or 0,"branch":_text(rec.get("branch"),80),"started_at":_text(rec.get("started_at"),40),"ended_at":_text(rec.get("ended_at"),40),
                    "duration_ms":_int(rec.get("duration_ms"),0) or 0,"error":_text(rec.get("error"),2000),"exit_code":output.get("exit_code") if isinstance(output.get("exit_code"),int) else None,
                    "resolved":[_text(c,2000) for c in (output.get("resolved") or [])[:20]] if isinstance(output.get("resolved"),list) else [],
                    "stdout":str(output.get("stdout") or "")[-tail:],"stderr":str(output.get("stderr") or "")[-tail:]})
    # Nodes that ran, in the order they started; nodes that never ran after them (in diagram order).
    ran=sorted([n for n in out if n["started_at"]],key=lambda n:n["started_at"])
    return ran+[n for n in out if not n["started_at"]]
def run_detail(run_id):
    """Everything the history's run view shows: the stored (or live) status summary, per-node results in run order and the
    node titles (from the export for an imported run, else the chain's current diagram, else the log)."""
    _guard()
    from Cores.Services import flow_service as _flows
    status=_flows.run_status(run_id)
    names=_chain_names()
    pid=_int(status.get("playbook_id"))
    imported=status.get("imported") if isinstance(status.get("imported"),dict) else None
    titles,types=_graph_info(pid) if pid in names and not imported else ({},{})
    if isinstance(status.get("node_titles"),dict):
        for k,v in status["node_titles"].items():titles.setdefault(str(k),_text(v,120))
    if isinstance(status.get("node_types"),dict):
        for k,v in status["node_types"].items():types.setdefault(str(k),_text(v,40))
    if not titles:
        try:
            for entry in _flows.run_log(run_id,0,2000)["entries"]:
                if entry.get("node") and entry.get("title"):titles.setdefault(str(entry["node"]),str(entry["title"]))
        except ValueError:
            pass
    live=_engine.get_run(run_id)
    return {"run_id":str(status.get("run_id") or run_id),"playbook_id":pid,"chain_name":status.get("name") or "","chain_exists":pid in names,"current_name":names.get(pid,""),
            "mode":str(status.get("mode") or "run"),"imported":imported,"state":str(status.get("state") or ""),"reason":_text(status.get("reason"),1000),
            "source":str(status.get("source") or ""),"target":str(status.get("target") or ""),"started_at":str(status.get("started_at") or ""),"ended_at":str(status.get("ended_at") or ""),
            "duration_ms":duration_ms(status.get("started_at"),status.get("ended_at")) if status.get("ended_at") else None,"live":bool(live is not None and live.active()),
            "nodes":node_counts(status),"timeline":_timeline(status,titles,types),"titles":titles,"edges_taken":list(status.get("edges_taken") or [])[:2000],
            "truncated":bool(status.get("truncated")),"notices":[n for n in (status.get("notices") or []) if isinstance(n,dict)][:50]}
# ---------------------------------------------------------------- deleting
def _active_ids():
    return {r.get("run_id") for r in _engine.active_runs()}
def delete_runs(run_ids):
    """Delete finished runs with their logs. Runs that are still going are skipped. -> {"deleted","skipped","missing"}."""
    _guard()
    ids=[str(r) for r in (run_ids if isinstance(run_ids,(list,tuple)) else [run_ids]) if str(r or "").strip()][:5000]
    active=_active_ids()
    _engine.flush_pending()
    deleted,skipped,missing=0,[],0
    for run_id in ids:
        if run_id in active:skipped.append(run_id);continue
        _engine.forget_run(run_id)
        if _store.delete_run(run_id):deleted+=1
        else:missing+=1
    if deleted:_audit("chain_runs_delete",f"{deleted} chain run(s) deleted from the history"+(f", {len(skipped)} still running were kept" if skipped else ""))
    return {"deleted":deleted,"skipped":skipped,"missing":missing}
def clear_runs(playbook_id=None,chain_name=None):
    """Delete every finished run (all, one chain's by id, or an orphaned chain's by name). Runs that are going are kept."""
    _guard()
    _engine.flush_pending()
    active=_active_ids()
    pid=_int(playbook_id)
    con=_store._con()
    try:
        if pid is not None:rows=con.execute("SELECT run_id FROM ChainRuns WHERE playbook_id=?",(pid,)).fetchall()
        elif chain_name:rows=con.execute("SELECT run_id FROM ChainRuns WHERE playbook_id IS NULL AND LOWER(chain_name)=LOWER(?)",(str(chain_name),)).fetchall()
        else:rows=con.execute("SELECT run_id FROM ChainRuns").fetchall()
        ids=[(r[0],) for r in rows if r[0] not in active]
        con.executemany("DELETE FROM ChainRunLogs WHERE run_id=?",ids)
        con.executemany("DELETE FROM ChainRuns WHERE run_id=?",ids)
        con.commit()
    finally:
        con.close()
    for (run_id,) in ids:_engine.forget_run(run_id)
    scope=f"chain {pid}" if pid is not None else (f"chain '{str(chain_name)[:120]}'" if chain_name else "all chains")
    if ids:_audit("chain_runs_delete",f"run history cleared for {scope}: {len(ids)} run(s)")
    return {"deleted":len(ids),"skipped":sorted(r for r in active if r)}
# ---------------------------------------------------------------- export
def _app_version():
    try:
        from Cores.Update import update_service as _up
        return str(_up.get_app_version() or "")
    except Exception:
        return ""
def _ids(value):
    if value in (None,"","all"):return None
    out=[]
    for v in (value if isinstance(value,(list,tuple)) else [value]):
        n=_int(v)
        if n is not None and n not in out:out.append(n)
    return out
def _export_chain(playbook_id):
    from Cores.Services import flow_service as _flows
    loaded=_flows._load(playbook_id)
    book,row=loaded["book"],loaded["row"]
    bundle=_schema.export_bundle(book["name"],book.get("caller") or "",loaded["graph"])
    return {"ref":"c%d"%int(book["id"]),"source_id":int(book["id"]),"name":bundle["name"],"caller":bundle["caller"],"derived":bool(loaded["derived"]),
            "origin":{"ai_made":bool(row and row["ai_made"]),"reviewed":bool(row["ai_reviewed"]) if row else True,"ai_client":(row or {}).get("ai_client") or ""},"graph":bundle["graph"]}
def _stored_run_ids(run_ids=None,playbook_id=None):
    con=_store._con()
    try:
        if run_ids is not None:
            return [r for r in run_ids if con.execute("SELECT 1 FROM ChainRuns WHERE run_id=?",(r,)).fetchone()]
        if playbook_id is not None:
            ids=playbook_id if isinstance(playbook_id,list) else [playbook_id]
            rows=con.execute("SELECT run_id FROM ChainRuns WHERE playbook_id IN (%s) ORDER BY started_at,id"%",".join("?"*len(ids)),ids).fetchall() if ids else []
        else:rows=con.execute("SELECT run_id FROM ChainRuns ORDER BY started_at,id").fetchall()
    finally:
        con.close()
    return [r[0] for r in rows]
def _export_run(run_id,include_logs=True,titles_cache=None):
    con=_store._con()
    try:
        row=con.execute("SELECT run_id,playbook_id,chain_name,mode,state,source,target,started_at,ended_at,data FROM ChainRuns WHERE run_id=?",(run_id,)).fetchone()
    finally:
        con.close()
    if not row:return None
    try:status=json.loads(row[9] or "{}")
    except ValueError:status={}
    if not isinstance(status,dict):status={}
    pid=_int(row[1])
    cache=titles_cache if isinstance(titles_cache,dict) else {}
    if pid not in cache:cache[pid]=_graph_info(pid)
    titles,types=dict(status.get("node_titles") or {}) if isinstance(status.get("node_titles"),dict) else {},{}
    for k,v in cache[pid][0].items():titles.setdefault(k,v)
    types.update(cache[pid][1])
    log=_store.get_run_log(run_id,0,_engine.LOG_MAX)[0] if include_logs else []
    imported=row[3]==IMPORTED_MODE
    return {"run_id":row[0],"chain_ref":("c%d"%pid) if pid is not None else None,"source_playbook_id":pid,"chain_name":row[2] or "",
            "mode":str(status.get("mode") or "run") if imported else row[3],"state":row[4],"source":row[5] or "","target":row[6] or "",
            "started_at":row[7] or "","ended_at":row[8] or "","node_titles":titles,"node_types":types,"status":status,"log":log}
def export_bundle(chain_ids=None,run_ids=None,include_chains=True,include_runs=False,runs_of_chain=None,include_logs=True):
    """Build a bundle. chain_ids: list of chain ids, or None/"all" for every chain. run_ids: list, or None/"all" for every run
    (or, with runs_of_chain - one chain id or a list - those chains' runs). include_chains/include_runs choose the sections."""
    _guard()
    _engine.flush_pending()
    chains,runs=[],[]
    if include_chains:
        wanted=_ids(chain_ids)
        ids=wanted if wanted is not None else [int(b["id"]) for b in _chains.list_playbooks()]
        for pid in ids[:MAX_CHAINS]:
            try:chains.append(_export_chain(pid))
            except ValueError:continue
    if include_runs:
        chains_of=_ids(runs_of_chain) if isinstance(runs_of_chain,(list,tuple)) else _int(runs_of_chain)
        ids=_stored_run_ids(None if run_ids in (None,"","all") else [str(r) for r in (run_ids if isinstance(run_ids,(list,tuple)) else [run_ids])],chains_of)
        cache={}
        for run_id in ids[-MAX_RUNS:]:
            item=_export_run(run_id,include_logs,cache)
            if item is not None:runs.append(item)
    contents=(["chains"] if include_chains else [])+(["runs"] if include_runs else [])
    return {"format":BUNDLE_FORMAT,"version":BUNDLE_VERSION,"app":"LOYA NG","app_version":_app_version(),"exported_at":_stamp(),"contents":contents,"chains":chains,"runs":runs}
def bundle_text(bundle):
    return json.dumps(bundle,ensure_ascii=False,indent=1,default=str)+"\n"
def export_file_name(bundle):
    chains,runs=bundle.get("chains") or [],bundle.get("runs") or []
    day=datetime.now().strftime("%Y-%m-%d")
    if len(chains)==1 and not runs:stem=chains[0]["name"]
    elif runs and not chains:stem="chain-runs-"+day
    else:stem="chains-"+day
    stem="".join(c if c.isalnum() or c in " -_." else "_" for c in str(stem)).strip(" .")[:80] or "chains"
    return stem+".loya-chains.json"
# ---------------------------------------------------------------- import: parse and validate
class BundleError(ValueError):pass
def parse_bundle(raw):
    """Bytes/str/dict -> a normalized bundle {"chains":[...],"runs":[...],"version","legacy"}. Raises BundleError."""
    data=raw
    if isinstance(data,(bytes,bytearray)):
        if len(data)>IMPORT_MAX_BYTES:raise BundleError("This file is too large to import (the limit is 64 MB).")
        try:data=bytes(data).decode("utf-8-sig")
        except UnicodeDecodeError:raise BundleError("This file is not a chain bundle (it is not UTF-8 text).") from None
    if isinstance(data,str):
        if len(data)>IMPORT_MAX_BYTES:raise BundleError("This file is too large to import (the limit is 64 MB).")
        try:data=json.loads(data.lstrip("﻿"))
        except ValueError:raise BundleError("This file is not a chain bundle (it is not valid JSON).") from None
    if not isinstance(data,dict):raise BundleError("This file is not a chain bundle.")
    if data.get("format")!=BUNDLE_FORMAT:
        if "loya_chain" in data or ("nodes" in data and "edges" in data):
            try:single=_schema.import_bundle(data)
            except ValueError as e:raise BundleError(str(e)) from None
            return {"version":1,"legacy":True,"chains":[{"ref":"c0","source_id":None,"name":single["name"],"caller":single["caller"],"origin":{},"graph":single["graph"]}],"runs":[]}
        raise BundleError("This file is not a LOYA chain bundle (the 'format' field is missing).")
    version=data.get("version")
    if isinstance(version,bool) or not isinstance(version,int) or version<1:raise BundleError("This chain bundle has no valid version.")
    if version>BUNDLE_VERSION:raise BundleError("This chain bundle was made by a newer version of LOYA NG (bundle version %d)."%version)
    chains=data.get("chains") if data.get("chains") is not None else []
    runs=data.get("runs") if data.get("runs") is not None else []
    if not isinstance(chains,list) or not isinstance(runs,list):raise BundleError("This chain bundle is damaged ('chains' and 'runs' must be lists).")
    if len(chains)>MAX_CHAINS:raise BundleError("This bundle holds %d chains; at most %d can be imported at once."%(len(chains),MAX_CHAINS))
    if len(runs)>MAX_RUNS:raise BundleError("This bundle holds %d runs; the history keeps at most %d."%(len(runs),MAX_RUNS))
    return {"version":version,"legacy":False,"chains":chains,"runs":runs}
def _clean_chain(item,index):
    """-> (chain dict, None) or (None, problem text). The diagram is validated like any other import."""
    if not isinstance(item,dict):return None,"Chain %d is not an object."%(index+1)
    name=_text(item.get("name"),200).strip() or "Imported chain"
    try:checked=_schema.import_bundle({"loya_chain":1,"name":name,"caller":_text(item.get("caller"),80),"graph":item.get("graph")})
    except ValueError as e:return None,"Chain '%s': %s"%(name[:80],e)
    origin=item.get("origin") if isinstance(item.get("origin"),dict) else {}
    ref=_text(item.get("ref"),40) or ("c%d"%index)
    return {"ref":ref,"source_id":_int(item.get("source_id")),"name":checked["name"] or name,"caller":checked["caller"],"graph":checked["graph"],
            "ai_made":origin.get("ai_made") is True},None
def _clean_log(entries):
    out=[]
    if not isinstance(entries,list):return out
    for i,entry in enumerate(entries[:_engine.LOG_MAX]):
        if not isinstance(entry,dict):continue
        level=str(entry.get("level") or "info").lower()
        level="warn" if level=="warning" else level
        data=entry.get("data") if isinstance(entry.get("data"),dict) else {}
        try:
            if len(json.dumps(data,default=str))>16384:data={"truncated":True}
        except (TypeError,ValueError):data={}
        out.append({"seq":_int(entry.get("seq"),i+1) or (i+1),"ts":_text(entry.get("ts"),40) or _now(),"node":_text(entry.get("node"),80) or None,"title":_text(entry.get("title"),200),
                    "level":level if level in _LOG_LEVELS else "info","kind":_text(entry.get("kind"),40) or "info","text":_text(entry.get("text"),20000),"data":data})
    return out
def _clean_run(item,index):
    if not isinstance(item,dict):return None,"Run %d is not an object."%(index+1)
    run_id=_text(item.get("run_id"),80).strip()
    if not _RUN_ID_RX.match(run_id):return None,"Run %d has no valid run_id."%(index+1)
    started=_parse_ts(item.get("started_at"))
    if started is None:return None,"Run %s has no valid start time."%run_id
    ended=_parse_ts(item.get("ended_at"))
    state=_text(item.get("state"),40).strip().lower()
    if state not in FINAL_STATES:state="cancelled"   # a run that was going when it was exported never finishes here
    mode="dry" if str(item.get("mode") or "")=="dry" else "run"
    status=item.get("status") if isinstance(item.get("status"),dict) else {}
    titles={str(k)[:80]:_text(v,120) for k,v in list((item.get("node_titles") or {}).items())[:_schema.LIMITS["nodes"]*2]} if isinstance(item.get("node_titles"),dict) else {}
    types={str(k)[:80]:_text(v,40) for k,v in list((item.get("node_types") or {}).items())[:_schema.LIMITS["nodes"]*2]} if isinstance(item.get("node_types"),dict) else {}
    nodes=status.get("nodes") if isinstance(status.get("nodes"),dict) else {}
    clean_nodes={}
    for node_id,rec in list(nodes.items())[:_schema.LIMITS["nodes"]*2]:
        if not isinstance(rec,dict):continue
        out=rec.get("output") if isinstance(rec.get("output"),dict) else {}
        clean_nodes[str(node_id)[:80]]={"state":_text(rec.get("state"),20) or "pending","visits":_int(rec.get("visits"),0) or 0,"branch":_text(rec.get("branch"),80),
            "started_at":_text(rec.get("started_at"),40),"ended_at":_text(rec.get("ended_at"),40),"duration_ms":_int(rec.get("duration_ms"),0) or 0,"error":_text(rec.get("error"),4000),"job_keys":[],
            "output":{"exit_code":out.get("exit_code") if isinstance(out.get("exit_code"),int) and not isinstance(out.get("exit_code"),bool) else None,
                      "stdout":_text(out.get("stdout"),65536),"stderr":_text(out.get("stderr"),65536),"resolved":[_text(c,4096) for c in (out.get("resolved") or [])[:20]] if isinstance(out.get("resolved"),list) else []},"seq":0}
    events=[{"seq":_int(e.get("seq"),0) or 0,"ts":_text(e.get("ts"),40),"node":_text(e.get("node"),80) or None,"level":_text(e.get("level"),10) or "info","text":_text(e.get("text"),2000)}
            for e in (status.get("events") or [])[-500:] if isinstance(e,dict)] if isinstance(status.get("events"),list) else []
    # vars and anything else a real run could be seeded from are left behind: an imported run is history only.
    clean={"run_id":run_id,"playbook_id":None,"name":_text(item.get("chain_name") or status.get("name"),200),"mode":mode,"state":state,"reason":_text(status.get("reason"),1000),
           "source":_text(item.get("source") or status.get("source"),40),"target":_text(item.get("target") or status.get("target"),200),"started_at":started.isoformat(),
           "ended_at":ended.isoformat() if ended else "","current":None,"nodes":clean_nodes,"edges_taken":[_text(e,80) for e in (status.get("edges_taken") or [])[:2000]] if isinstance(status.get("edges_taken"),list) else [],
           "events":events,"approval":None,"vars":{},"notices":[],"node_titles":titles,"node_types":types,"truncated":bool(status.get("truncated"))}
    return {"run":clean,"chain_ref":_text(item.get("chain_ref"),40) or None,"source_playbook_id":_int(item.get("source_playbook_id")),"log":_clean_log(item.get("log"))},None
# ---------------------------------------------------------------- import: preview and apply
def _existing_chains():
    return {int(b["id"]):b for b in _chains.list_playbooks()}
def _norm_name(name):return " ".join(str(name or "").lower().split())
def _run_exists(con,run_id):
    return con.execute("SELECT 1 FROM ChainRuns WHERE run_id=?",(run_id,)).fetchone() is not None
def _script_notes(graph):
    scripts=_schema.graph_scripts(graph)
    raw=sorted({n for line in _schema.graph_commands(graph) for n in _engine.raw_names(line["text"])}) if hasattr(_engine,"raw_names") else []
    return len(scripts),raw
def preview(raw):
    """What an import would do, before anything is written: counts, name/run_id conflicts, problems and script warnings."""
    _guard()
    bundle=parse_bundle(raw)
    existing={_norm_name(b["name"]):b for b in _existing_chains().values()}
    chains,problems=[],[]
    for i,item in enumerate(bundle["chains"]):
        clean,problem=_clean_chain(item,i)
        if problem:problems.append(problem);continue
        scripts,raw_vars=_script_notes(clean["graph"])
        hit=existing.get(_norm_name(clean["name"]))
        chains.append({"name":clean["name"],"nodes":len(clean["graph"].get("nodes") or []),"scripts":scripts,"raw":raw_vars,"ai_made":clean["ai_made"],
                       "conflict":({"playbook_id":int(hit["id"]),"name":hit["name"]} if hit else None)})
    runs=[]
    con=_store._con()
    try:
        for i,item in enumerate(bundle["runs"]):
            clean,problem=_clean_run(item,i)
            if problem:problems.append(problem);continue
            runs.append({"run_id":clean["run"]["run_id"],"chain_name":clean["run"]["name"],"state":clean["run"]["state"],"started_at":clean["run"]["started_at"],"log_lines":len(clean["log"]),"conflict":_run_exists(con,clean["run"]["run_id"])})
        stored=con.execute("SELECT COUNT(*) FROM ChainRuns").fetchone()[0]
    finally:
        con.close()
    fresh=sum(1 for r in runs if not r["conflict"])
    return {"legacy":bundle["legacy"],"version":bundle["version"],"chains":chains,"runs":runs,"problems":problems[:50],
            "chain_conflicts":sum(1 for c in chains if c["conflict"]),"run_conflicts":sum(1 for r in runs if r["conflict"]),
            "scripts":sum(c["scripts"] for c in chains),"history_overflow":max(0,int(stored)+fresh-MAX_RUNS)}
def _free_name(name,taken):
    base=str(name or "Imported chain").strip()[:180] or "Imported chain"
    candidate=base+" (imported)"
    n=2
    while _norm_name(candidate) in taken:
        candidate="%s (imported %d)"%(base,n)
        n+=1
    return candidate
def _free_run_id(con,run_id,taken):
    n=1
    while True:
        candidate=("%s-imp%d"%(run_id[:70],n))
        if candidate not in taken and not _run_exists(con,candidate):return candidate
        n+=1
def _harden_graph(graph,warnings,name):
    settings=graph.get("settings") if isinstance(graph.get("settings"),dict) else None
    if settings and settings.get("script_isolation")=="allow":
        settings["script_isolation"]="inherit"
        warnings.append({"chain":name,"code":"script_isolation_reset","message":name+": the file asked to allow unsandboxed scripts; the app setting applies until you change it after review."})
def import_bundle(raw,options=None,ai_client=None,origin="import"):
    """Import chains and/or runs. options={"chains":"rename"|"skip"|"replace","runs":"skip"|"replace"|"rename",
    "import_chains":bool,"import_runs":bool}. ai_client set: the import came through an AI tool (chains become AI-made).
    -> {"chains":{"created","replaced","skipped"},"runs":{"imported","replaced","skipped","renamed"},"warnings","problems"}"""
    _guard()
    opts=options if isinstance(options,dict) else {}
    chain_mode=opts.get("chains") if opts.get("chains") in CHAIN_CONFLICT_MODES else "rename"
    run_mode=opts.get("runs") if opts.get("runs") in RUN_CONFLICT_MODES else "skip"
    bundle=parse_bundle(raw)
    from Cores.Services import flow_service as _flows
    problems,warnings=[],[]
    result={"chains":{"created":[],"replaced":[],"skipped":[]},"runs":{"imported":0,"replaced":0,"skipped":0,"renamed":0,"evicted":0},"warnings":warnings,"problems":problems}
    ref_map={}      # bundle ref / source id -> playbook id here, for run ownership (a skipped chain maps to the one kept)
    sub_map={}      # source id -> playbook id of a chain this import wrote: the only targets a sub-chain link may keep
    created=[]      # (playbook_id, clean, replaced?)
    if opts.get("import_chains",True) is not False:
        existing=_existing_chains()
        taken={_norm_name(b["name"]):int(pid) for pid,b in existing.items()}
        for i,item in enumerate(bundle["chains"]):
            clean,problem=_clean_chain(item,i)
            if problem:problems.append(problem);continue
            name=clean["name"]
            hit=taken.get(_norm_name(name))
            if hit is not None and chain_mode=="skip":
                ref_map[clean["ref"]]=hit
                if clean["source_id"] is not None:ref_map[("id",clean["source_id"])]=hit
                result["chains"]["skipped"].append({"name":name,"playbook_id":hit})
                continue
            graph=clean["graph"]
            _harden_graph(graph,warnings,name)
            made=bool(clean["ai_made"] or ai_client is not None)
            label=("AI import: "+str(ai_client)[:60]) if ai_client is not None else str(origin or "import")[:60]
            if hit is not None and chain_mode=="replace":
                _store.save_graph(hit,graph,ai_made=made,ai_reviewed=False,ai_client=label,schema_version=_schema.SCHEMA_VERSION)
                pid,replaced=hit,True
            else:
                title=_free_name(name,taken) if hit is not None else name
                wanted=clean["caller"] or None
                if wanted and not _chains.validate_caller(wanted).get("ok"):wanted=None
                pid=_chains.create_playbook(title,wanted)
                try:_store.save_graph(pid,graph,ai_made=made,ai_reviewed=False,ai_client=label,schema_version=_schema.SCHEMA_VERSION)
                except Exception:
                    _chains.delete_playbook(pid)
                    raise
                taken[_norm_name(title)]=pid
                name,replaced=title,False
            ref_map[clean["ref"]]=pid
            if clean["source_id"] is not None:ref_map[("id",clean["source_id"])]=pid;sub_map[clean["source_id"]]=pid
            created.append((pid,clean,replaced,name))
            scripts,raw_vars=_script_notes(graph)
            if scripts:warnings.append({"chain":name,"code":"imported_scripts","message":"%s: %d script node%s came from the file. Read every script before the first run."%(name,scripts,"" if scripts==1 else "s")})
            if raw_vars:warnings.append({"chain":name,"code":"imported_raw","message":name+": uses ${raw:...}, which an unreviewed chain may not run."})
        # Second pass: sub-chain nodes keep their link only when the chain they ran came in the same bundle.
        for pid,clean,replaced,name in created:
            graph=clean["graph"]
            changed=False
            for node in graph.get("nodes") or []:
                if node.get("type")!="subchain":continue
                cfg=node.setdefault("config",{})
                old=_int(cfg.get("playbook_id"))
                if old is None and cfg.get("playbook_id") in (None,""):continue
                new=sub_map.get(old) if old is not None else None
                if new is not None and new!=pid:cfg["playbook_id"]=new
                else:
                    cfg["playbook_id"]=None
                    warnings.append({"chain":name,"code":"subchain_cleared","message":"%s: sub-chain node '%s' ran a chain that is not in the file. Pick the chain again."%(name,node.get("title") or node.get("id"))})
                changed=True
            if changed:_store.save_graph(pid,graph,schema_version=_schema.SCHEMA_VERSION)
            (result["chains"]["replaced"] if replaced else result["chains"]["created"]).append({"name":name,"playbook_id":pid})
            _audit("chain_diagram_create",f"chain {pid} '{name[:120]}' {'replaced' if replaced else 'created'} by a bundle import"+(f" through an AI ({ai_client})" if ai_client is not None else "")+", not reviewed")
    if opts.get("import_runs",True) is not False and bundle["runs"]:
        names={_norm_name(b["name"]):int(pid) for pid,b in _existing_chains().items()}
        con=_store._con()
        try:
            taken=set()
            for i,item in enumerate(bundle["runs"]):
                clean,problem=_clean_run(item,i)
                if problem:problems.append(problem);continue
                run=clean["run"]
                if _run_exists(con,run["run_id"]) or run["run_id"] in taken:
                    if run_mode=="skip":result["runs"]["skipped"]+=1;continue
                    if run_mode=="replace":
                        if run["run_id"] in _active_ids():result["runs"]["skipped"]+=1;continue
                        con.execute("DELETE FROM ChainRunLogs WHERE run_id=?",(run["run_id"],))
                        con.execute("DELETE FROM ChainRuns WHERE run_id=?",(run["run_id"],))
                        result["runs"]["replaced"]+=1
                    else:
                        run["run_id"]=_free_run_id(con,run["run_id"],taken)
                        result["runs"]["renamed"]+=1
                pid=ref_map.get(clean["chain_ref"]) if clean["chain_ref"] else None
                if pid is None and clean["source_playbook_id"] is not None:pid=ref_map.get(("id",clean["source_playbook_id"]))
                if pid is None:pid=names.get(_norm_name(run["name"]))
                run["playbook_id"]=pid
                run["imported"]={"at":_now(),"mode":run["mode"],"by":("AI: "+str(ai_client)[:60]) if ai_client is not None else ("operator" if origin=="import" else str(origin)[:60])}
                data=_store._capped_run_json(run)
                con.execute("INSERT INTO ChainRuns(run_id,playbook_id,chain_name,mode,state,source,target,started_at,ended_at,data) VALUES(?,?,?,?,?,?,?,?,?,?)",
                            (run["run_id"],pid,run["name"],IMPORTED_MODE,run["state"],run["source"],run["target"],run["started_at"],run["ended_at"] or None,data))
                rows=[]
                for entry in clean["log"]:
                    extra=dict(entry["data"])
                    if entry["title"]:extra["_title"]=entry["title"]
                    rows.append((run["run_id"],entry["seq"],entry["ts"],entry["node"],entry["level"],entry["kind"],entry["text"],json.dumps(extra,ensure_ascii=False,separators=(",",":"),default=str) if extra else None))
                con.executemany("INSERT INTO ChainRunLogs(run_id,seq,ts,node,level,kind,text,data) VALUES(?,?,?,?,?,?,?,?)",rows)
                taken.add(run["run_id"])
                result["runs"]["imported"]+=1
            # The history stays bounded: beyond RUNS_KEEP the runs that started first go (whether imported or not).
            active=_active_ids()
            old=[r[0] for r in con.execute("SELECT run_id FROM ChainRuns ORDER BY started_at DESC,id DESC LIMIT -1 OFFSET ?",(_store.RUNS_KEEP,)).fetchall() if r[0] not in active]
            if old:
                con.executemany("DELETE FROM ChainRunLogs WHERE run_id=?",[(r,) for r in old])
                con.executemany("DELETE FROM ChainRuns WHERE run_id=?",[(r,) for r in old])
                result["runs"]["evicted"]=len(old)
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()
        if result["runs"]["imported"]:_audit("chain_runs_import",f"{result['runs']['imported']} chain run(s) imported into the history"+(f" through an AI ({ai_client})" if ai_client is not None else ""))
    return result
# ---------------------------------------------------------------- another database (a backup's, for a merge restore)
def bundle_from_db(path,key=None):
    """The diagram chains and the run history (with logs) stored in another LOYA database file, as a bundle. key: the
    SQLCipher data key of an encrypted file. A table the file does not have (an older backup) is simply empty."""
    from Cores import db_driver as _drv
    con=_drv.connect(path,key=key,timeout=10)
    chains,runs=[],[]
    try:
        tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if {"ChainGraphs","Playbooks"}<=tables:
            has_caller="caller" in {r[1] for r in con.execute("PRAGMA table_info(Playbooks)").fetchall()}
            rows=con.execute("SELECT p.id,p.name,"+("p.caller" if has_caller else "''")+",g.graph,g.ai_made FROM ChainGraphs g JOIN Playbooks p ON p.id=g.playbook_id ORDER BY p.id").fetchall()
            for pid,name,caller,graph,ai_made in rows[:MAX_CHAINS]:
                try:graph=json.loads(graph or "")
                except ValueError:continue
                chains.append({"ref":"c%d"%int(pid),"source_id":int(pid),"name":name or "","caller":caller or "","origin":{"ai_made":bool(ai_made)},"graph":graph})
        if "ChainRuns" in tables:
            rows=con.execute("SELECT run_id,playbook_id,chain_name,mode,state,source,target,started_at,ended_at,data FROM ChainRuns ORDER BY started_at DESC,id DESC LIMIT ?",(MAX_RUNS,)).fetchall()
            has_logs="ChainRunLogs" in tables
            for run_id,pid,name,mode,state,source,target,started,ended,data in reversed(rows):
                try:status=json.loads(data or "{}")
                except ValueError:status={}
                if not isinstance(status,dict):status={}
                log=[]
                if has_logs:
                    for seq,ts,node,level,kind,text,extra in con.execute("SELECT seq,ts,node,level,kind,text,data FROM ChainRunLogs WHERE run_id=? ORDER BY seq,id LIMIT ?",(run_id,_engine.LOG_MAX)).fetchall():
                        try:extra=json.loads(extra) if extra else {}
                        except ValueError:extra={}
                        extra=extra if isinstance(extra,dict) else {}
                        log.append({"seq":seq,"ts":ts,"node":node,"title":str(extra.pop("_title","") or ""),"level":level,"kind":kind,"text":text or "","data":extra})
                runs.append({"run_id":run_id,"chain_ref":("c%d"%int(pid)) if pid is not None else None,"source_playbook_id":pid,"chain_name":name or "",
                             "mode":str(status.get("mode") or "run") if mode==IMPORTED_MODE else mode,"state":state,"source":source or "","target":target or "",
                             "started_at":started,"ended_at":ended or "","node_titles":status.get("node_titles") or {},"node_types":status.get("node_types") or {},"status":status,"log":log})
    finally:
        con.close()
    return {"format":BUNDLE_FORMAT,"version":BUNDLE_VERSION,"contents":["chains","runs"],"chains":chains,"runs":runs}
def merge_from_db(path,key=None):
    """A merge restore: the chains (by name) and runs (by run_id) of a backup's database that this install does not have
    yet are added; nothing here is replaced. -> import_bundle's result, or None when the file holds neither."""
    bundle=bundle_from_db(path,key)
    if not bundle["chains"] and not bundle["runs"]:return None
    return import_bundle(bundle,{"chains":"skip","runs":"skip"},origin="backup restore")
