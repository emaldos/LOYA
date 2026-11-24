"""MCP tools for the chain Run History and chain/run bundles (list, read, log, export, import, delete). Registered from
mcp_server.build_server() with register(server, check), next to the app-wide tools. Same rules as mcp_app_tools:
- every tool calls check(name, args) first (the lock, then AI Roles / ai_service.authorize) and is listed under exactly one
  permission key below, all under the "Chain History" entity: Read (Allow), Add = import (Ask), Delete (Deny);
- everything goes through Cores/Services/chain_history.py, the same code as the Chains page, so validation, the review
  flags and the audit log apply;
- text an AI reads (node output, log lines, exported bundles) passes through the terminal secret redactor;
- an import made by an AI marks the chains AI-made and unreviewed, so the operator reviews them before any run."""
from Cores.Services import ai_service as _ai
from Cores.Services import chain_history as _hist
EXPORT_MAX_CHARS=4_000_000
LOG_PAGE_MAX=2000
_PERMISSIONS=(
    ("chain_history_read","Chain History","Read",["chain_runs_list","chain_run_get","chain_run_log","chain_history_export"],{}),
    ("chain_history_add","Chain History","Add",["chain_history_import"],{"default":"ask"}),
    ("chain_history_delete","Chain History","Delete",["chain_runs_delete"],{}),
)
def register_permissions():
    for key,entity,action,tools,kw in _PERMISSIONS:
        if key not in _ai.PERMISSION_TOOL_MAP:_ai.register_permission(key,entity,action,tools,**kw)
def all_tool_names():
    return [t for _k,_e,_a,tools,_kw in _PERMISSIONS for t in tools]
register_permissions()
def _redact(value):
    from Cores.Services import flow_service as _flows
    if isinstance(value,str):return _flows._redacted(value) if value else value
    if isinstance(value,list):return [_redact(v) for v in value]
    if isinstance(value,dict):return {k:_redact(v) for k,v in value.items()}
    return value
def _ids(value):
    if value is None:return None
    if isinstance(value,(str,int)):value=[value]
    return [v for v in value if str(v).strip()] if isinstance(value,list) else None
def register(server,check):
    try:
        from Cores.Bridge import mcp_app_tools as _app_tools
        _app_tools._ENTITY_KIND.setdefault("Chain History","chains")   # a change made here refreshes the Chains page
    except Exception:
        pass
    @server.tool(description="List chain runs from the Run History, newest first: run_id, chain name and id, start time, duration (ms), status (done, failed, cancelled, timeout, running), node counts by result, trigger (manual, caller, live, ai) and target. "
                 "Filter by chain_id, state, trigger, a date range (ISO 8601, e.g. 2026-11-01T00:00:00Z) and free-text query (chain name, target, run id). Paged with offset/limit (at most 200).")
    def chain_runs_list(chain_id: int=0,state: str="",trigger: str="",date_from: str="",date_to: str="",query: str="",offset: int=0,limit: int=50) -> dict:
        check("chain_runs_list",{"chain_id":chain_id,"state":state,"trigger":trigger,"date_from":date_from,"date_to":date_to,"query":query})
        page=_hist.list_runs({"playbook_id":chain_id or None,"state":state,"source":trigger,"date_from":date_from,"date_to":date_to,"query":query,"offset":offset,"limit":limit})
        return _redact(page)
    @server.tool(description="One chain run from the Run History: overall status, reason, trigger, target, duration, node counts and the per-node timeline (state, branch taken, visits, duration, exit code, error, resolved commands and the output tail; secrets redacted).")
    def chain_run_get(run_id: str) -> dict:
        check("chain_run_get",{"run_id":run_id})
        detail=_hist.run_detail(run_id)
        for node in detail["timeline"]:
            node["stdout"]=node["stdout"][-2000:];node["stderr"]=node["stderr"][-1000:]
        return _redact(detail)
    @server.tool(description="The structured log of a chain run (secrets redacted): entries {seq, ts, node, title, level info|warn|error, kind, text}. Filter by level and words in query; page with since (the last seq you have) and limit (at most 2000).")
    def chain_run_log(run_id: str,since: int=0,limit: int=500,level: str="",query: str="") -> dict:
        check("chain_run_log",{"run_id":run_id,"since":since,"level":level,"query":query})
        from Cores.Services import flow_service as _flows
        try:limit=max(1,min(LOG_PAGE_MAX,int(limit)))
        except (TypeError,ValueError):limit=500
        log=_flows.run_log(run_id,since,limit)
        entries=log["entries"]
        lvl=str(level or "").strip().lower()
        words=[w for w in str(query or "").lower().split() if w]
        if lvl:entries=[e for e in entries if e.get("level")==lvl]
        if words:entries=[e for e in entries if all(w in (str(e.get("text") or "")+" "+str(e.get("title") or "")).lower() for w in words)]
        return _redact({"run_id":log["run_id"],"entries":[{k:e.get(k) for k in ("seq","ts","node","title","level","kind","text")} for e in entries],"next":log["next"],"live":log["live"],"total":log["total"]})
    @server.tool(description="Export chains and/or run history as a versioned LOYA chain bundle (format loya-chain-bundle, version 1) the operator can import elsewhere. "
                 "Chains: chain_ids, or all_chains. Runs: run_ids, runs_of_chain (a chain id), or all_runs; include_logs adds each run's log. Secrets in run output are redacted. Returns {bundle, chains, runs}; a bundle over 4 MB is refused (export fewer runs).")
    def chain_history_export(chain_ids: list|None=None,run_ids: list|None=None,all_chains: bool=False,all_runs: bool=False,runs_of_chain: int=0,include_logs: bool=True) -> dict:
        check("chain_history_export",{"chain_ids":chain_ids,"run_ids":run_ids,"all_chains":all_chains,"all_runs":all_runs,"runs_of_chain":runs_of_chain,"include_logs":include_logs})
        want_chains=bool(all_chains or chain_ids)
        want_runs=bool(all_runs or run_ids or runs_of_chain)
        if not want_chains and not want_runs:raise ValueError("Say what to export: chain_ids or all_chains, and/or run_ids, runs_of_chain or all_runs.")
        bundle=_hist.export_bundle(None if all_chains else _ids(chain_ids),None if (all_runs or runs_of_chain) else _ids(run_ids),include_chains=want_chains,include_runs=want_runs,runs_of_chain=runs_of_chain or None,include_logs=bool(include_logs))
        bundle=_redact(bundle)
        if len(_hist.bundle_text(bundle))>EXPORT_MAX_CHARS:raise ValueError("The bundle is larger than 4 MB. Export fewer runs or leave the logs out (include_logs=false).")
        return {"bundle":bundle,"chains":len(bundle["chains"]),"runs":len(bundle["runs"])}
    @server.tool(description="Import a LOYA chain bundle (the object chain_history_export returns, or a single-chain export) into this install. Every diagram is validated; imported chains are AI-made and unreviewed, so the operator must review them before any run, and scripts cannot loosen script isolation. "
                 "Name collisions: chains_on_conflict rename (default, adds '(imported)'), skip or replace (replaces the existing chain's diagram). run_id collisions: runs_on_conflict skip (default), replace or rename. Imported runs are history only.")
    def chain_history_import(bundle: dict|str,chains_on_conflict: str="rename",runs_on_conflict: str="skip") -> dict:
        try:preview=_hist.preview(bundle)
        except ValueError as e:
            check("chain_history_import",{"bundle":"invalid"},defer_ask=True)   # lock and Deny still apply; nothing to approve
            raise ValueError(str(e)) from None
        check("chain_history_import",{"chains":[c["name"] for c in preview["chains"]][:20],"runs":len(preview["runs"]),"scripts":preview["scripts"],"chains_on_conflict":chains_on_conflict,"runs_on_conflict":runs_on_conflict},
              force_ask=bool(preview["scripts"] or chains_on_conflict=="replace" or runs_on_conflict=="replace"))
        return _hist.import_bundle(bundle,{"chains":chains_on_conflict,"runs":runs_on_conflict},ai_client=_ai.client_label())
    @server.tool(description="Delete chain runs (with their logs) from the Run History: run_ids for one or more runs, chain_id for every run of one chain, or all_runs=true for the whole history. Runs that are still going are never deleted. Needs Chain History > Delete; deleting a whole chain's history or everything always asks the operator.")
    def chain_runs_delete(run_ids: list|None=None,chain_id: int=0,all_runs: bool=False) -> dict:
        ids=_ids(run_ids) or []
        if not ids and not chain_id and not all_runs:raise ValueError("Say what to delete: run_ids, chain_id or all_runs=true.")
        check("chain_runs_delete",{"run_ids":ids[:20],"count":len(ids),"chain_id":chain_id,"all_runs":all_runs},force_ask=bool(all_runs or chain_id or len(ids)>5))
        if all_runs:return _hist.clear_runs()
        if chain_id:return _hist.clear_runs(chain_id)
        return _hist.delete_runs(ids)
