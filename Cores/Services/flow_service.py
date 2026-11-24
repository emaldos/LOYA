"""Chain Diagrams facade: what the bridge (flows.*) and the MCP tools call. Storage lives in flow_store, the graph rules
in flow_schema/flow_rules, execution in flow_engine. A chain without a ChainGraphs row is still a linear chain: it is shown
as a derived straight-line diagram and its PlaybookSteps are never touched."""
import copy,hashlib,json,re
from datetime import datetime,timedelta
from Cores import common_db
from Cores.settings_lock import SETTINGS_LOCK as _settings_lock
from Cores.Services import flow_schema as _schema
from Cores.Services import flow_store as _store
from Cores.Services import flow_engine as _engine
from Cores.Services import flow_nodes as _nodes
from Cores.Services import playbooks_service as _chains
PREF_DEFAULTS={"snap":True,"grid":20,"minimap":True,"inspector_width":340,"hotbar":list(_nodes.HOTBAR)}
HOTBAR_MAX=12
_LOCKED_MESSAGE="LOYA NG is locked. Unlock it to continue."
def _audit(event,detail,success=True):
    try:
        from Cores.Services import security_service
        security_service.log_audit_event(event,str(detail)[:1000],success)
    except Exception:
        pass
def _terminal():
    from Cores.Services import terminal_service
    return terminal_service
def _pid(playbook_id):
    try:return int(playbook_id)
    except (TypeError,ValueError):raise ValueError("Action chain not found.")
def _book(playbook_id):
    book=_chains.get_playbook(_pid(playbook_id))
    if not book:raise ValueError("Action chain not found.")
    return book
def _linear_graph(book):
    steps=[{"command_id":s.get("command_id"),"command_src":s.get("command_src"),"label":"","command":s.get("command")} for s in book.get("steps") or [] if s.get("command")]
    return _schema.linear_to_graph(book.get("name") or "",steps)
def _load(playbook_id):
    """{"book","row","graph","derived"}: the stored diagram, or the straight line derived from a linear chain's steps."""
    book=_book(playbook_id)
    row=_store.get_graph_row(book["id"])
    if row and isinstance(row.get("graph"),dict):return {"book":book,"row":row,"graph":row["graph"],"derived":False}
    return {"book":book,"row":None,"graph":_linear_graph(book),"derived":True}
def _cycle_issues(graph,playbook_id):
    """Errors (code subchain_cycle) for sub-chain nodes of chain `playbook_id` that lead back to it: A > A, A > B > A, ..."""
    try:own=int(playbook_id)
    except (TypeError,ValueError):return []
    try:refs=_store.subchain_refs()
    except Exception:return []
    names={}
    def name_of(pid):
        if not names:
            try:names.update({int(b["id"]):b["name"] for b in _chains.list_playbooks()})
            except Exception:names[-1]=""
        return names.get(pid) or ("chain "+str(pid))
    issues=[]
    for item in graph.get("nodes") or []:
        if item.get("type")!="subchain":continue
        try:child=int((item.get("config") or {}).get("playbook_id"))
        except (TypeError,ValueError):continue
        # Depth-first through the stored diagrams, remembering the way so the message can show the loop.
        trail=None
        stack=[(child,[child])]
        seen=set()
        while stack and trail is None:
            current,way=stack.pop()
            if current==own:trail=way
            elif current not in seen:
                seen.add(current)
                for nxt in refs.get(current,()):stack.append((nxt,way+[nxt]))
        if trail is not None:
            loop=" > ".join(name_of(pid) for pid in [own]+trail)
            issues.append({"node":item.get("id"),"edge":None,"code":"subchain_cycle","message":(item.get("title") or "Sub-chain")+": this chain would run itself ("+loop+")."})
    return issues
def _checked(graph,playbook_id=None):
    """flow_schema.validate_graph plus the checks that need the other chains (sub-chain cycles)."""
    result=_schema.validate_graph(graph)
    extra=_cycle_issues(result["graph"],playbook_id) if playbook_id is not None else []
    if extra:result=dict(result,ok=False,errors=list(result["errors"])+extra)
    return result
def _usable_graph(graph,playbook_id=None):
    """Normalize a graph that is about to be stored. Raises ValueError for something that is not a diagram at all."""
    if isinstance(graph,str):
        try:graph=json.loads(graph)
        except ValueError:raise ValueError("The diagram is not valid JSON.") from None
    if not isinstance(graph,dict) or not isinstance(graph.get("nodes"),list):raise ValueError("The diagram is not valid: 'nodes' is missing.")
    result=_checked(graph,playbook_id)
    too_big=next((i for i in result["errors"] if i.get("code") in ("graph_too_large","too_many_nodes","too_many_edges")),None)
    if too_big:raise ValueError(too_big["message"])
    return result
def _issue_text(issues,limit=8):
    return "; ".join(str(i.get("message") or "") for i in issues[:limit])+(" (and %d more)"%(len(issues)-limit) if len(issues)>limit else "")
# ---- catalog / reading ---------------------------------------------------------------------------------------------
def catalog():
    from Cores.Services import flow_scripts
    try:shells=[{"id":s["id"],"label":s.get("label") or s["id"]} for s in _terminal().list_shells()]
    except Exception:shells=[]
    return {"schema":_schema.SCHEMA_VERSION,"node_types":copy.deepcopy(_schema.NODE_TYPES),"limits":dict(_schema.LIMITS),"templates":[{"id":t["id"],"name":t["name"],"description":t["description"]} for t in _schema.TEMPLATES],"script_templates":copy.deepcopy(flow_scripts.SCRIPT_TEMPLATES),"languages":flow_scripts.available_languages(),"ops":list(_schema.OPS),"sources":list(_schema.SOURCES),"parsers":list(_schema.PARSE_TOOLS),"shells":shells,"output_actions":list(_schema.OUTPUT_ACTIONS),"severities":list(_schema.SEVERITIES),
            # The node catalog (flow_nodes; the same object as the generated UI/js/components/flow-catalog.js): palette categories,
            # every type with its fields, the palette presets and the default hot bar (the user's pins are in prefs_get()["hotbar"]).
            **{key:value for key,value in _nodes.flow_catalog(_schema.SCHEMA_VERSION).items() if key!="schema"}}
def list_flows():
    """Every chain, linear or diagram."""
    index=_store.graph_index()
    out=[]
    for book in _chains.list_playbooks():
        info=index.get(int(book["id"]))
        out.append({"playbook_id":book["id"],"name":book["name"],"caller":book.get("caller") or "","step_count":book.get("step_count") or 0,"has_graph":info is not None,"node_count":info["node_count"] if info else (book.get("step_count") or 0)+1,"ai_made":bool(info and info["ai_made"]),"ai_reviewed":bool(info["ai_reviewed"]) if info else True,"updated_at":(info["updated_at"] if info else "") or book.get("updated_at") or ""})
    return out
def get(playbook_id):
    loaded=_load(playbook_id)
    book,row=loaded["book"],loaded["row"]
    check=_checked(loaded["graph"],book["id"])
    return {"playbook_id":book["id"],"name":book["name"],"caller":book.get("caller") or "","graph":check["graph"],"derived":loaded["derived"],"ai_made":bool(row and row["ai_made"]),"ai_reviewed":bool(row["ai_reviewed"]) if row else True,"ai_client":(row or {}).get("ai_client") or "","errors":check["errors"],"warnings":check["warnings"]}
def validate(graph,playbook_id=None):
    """With playbook_id the checks that need the other chains run too (a sub-chain that leads back to this chain)."""
    return _checked(graph,playbook_id)
def template(template_id):
    graph=_schema.template(str(template_id or ""))
    if graph is None:raise ValueError("Unknown template.")
    return graph
# ---- writing -------------------------------------------------------------------------------------------------------
def create(name,graph=None,caller=None,template_id=None,ai_client=None):
    """New chain with a diagram. ai_client set = made by an AI: stored as ai_made and not yet reviewed."""
    if template_id:graph=template(template_id)
    result=_usable_graph(graph if graph is not None else _schema.new_graph())
    if ai_client is not None and not result["ok"]:raise ValueError("The diagram is not valid: "+_issue_text(result["errors"]))
    playbook_id=_chains.create_playbook(name,caller)
    try:
        _store.save_graph(playbook_id,result["graph"],ai_made=ai_client is not None,ai_reviewed=ai_client is None,ai_client=ai_client or "",schema_version=_schema.SCHEMA_VERSION)
    except Exception:
        _chains.delete_playbook(playbook_id)
        raise
    _audit("chain_diagram_create",f"chain {playbook_id} '{str(name)[:120]}' nodes={len(result['graph']['nodes'])}"+(f" by AI ({ai_client})" if ai_client is not None else "")+(f" from template {template_id}" if template_id else ""))
    return {"playbook_id":playbook_id,"errors":result["errors"],"warnings":result["warnings"]}
def save(playbook_id,graph,ai_client=None):
    """Store a chain's diagram (creating the ChainGraphs row turns a linear chain into a diagram chain). Validation errors
    do not block saving a draft; they block running. An AI edit (ai_client set) must be valid and resets the review flag."""
    book=_book(playbook_id)
    result=_usable_graph(graph,book["id"])
    if ai_client is not None:
        if not result["ok"]:raise ValueError("The diagram is not valid: "+_issue_text(result["errors"]))
        _store.save_graph(book["id"],result["graph"],ai_made=True,ai_reviewed=False,ai_client=ai_client,schema_version=_schema.SCHEMA_VERSION)
    else:
        _store.save_graph(book["id"],result["graph"],schema_version=_schema.SCHEMA_VERSION)
    _audit("chain_diagram_edit",f"chain {book['id']} '{book['name'][:120]}' nodes={len(result['graph']['nodes'])} edges={len(result['graph']['edges'])}"+(f" by AI ({ai_client})" if ai_client is not None else ""))
    return {"ok":result["ok"],"errors":result["errors"],"warnings":result["warnings"]}
def revert_linear(playbook_id):
    """Drop the diagram: the chain is linear again (its steps were never touched)."""
    book=_book(playbook_id)
    removed=_store.delete_graph(book["id"])
    if removed:_audit("chain_diagram_delete",f"chain {book['id']} '{book['name'][:120]}' reverted to a linear chain")
    return removed
def chain_deleted(playbook_id):
    """Called when an Action Chain is deleted: its diagram goes with it. Never raises."""
    try:
        if _store.delete_graph(playbook_id):_audit("chain_diagram_delete",f"chain {playbook_id} deleted with its diagram")
        return True
    except Exception:
        return False
def mark_reviewed(playbook_id):
    book=_book(playbook_id)
    """The operator's explicit review: the chain becomes a normal chain (not AI-made, reviewed). A later AI edit or an
    import sets the flags again. Confirming a first run (review_ack) is weaker: it only records the review."""
    done=_store.set_reviewed(book["id"],True,clear_ai_made=True)
    if done:_audit("chain_diagram_reviewed",f"chain {book['id']} '{book['name'][:120]}' reviewed by the operator: no longer treated as AI-made")
    return done
def file_name_with_ext(path,ext):
    """The path a save dialog returned, ending in .ext exactly once: nothing is appended when it already ends in .ext
    (any case), and a doubled ending (name.json.json) is folded back to one."""
    path=str(path or "")
    ext=str(ext or "").strip().lstrip(".")
    if not path or not ext:return path
    suffix="."+ext.lower()
    while path.lower().endswith(suffix+suffix):path=path[:-len(suffix)]
    if path.lower().endswith(suffix):return path
    return path.rstrip(".")+"."+ext
def _safe_file_stem(name,fallback="chain"):
    return "".join(c if c.isalnum() or c in " -_." else "_" for c in str(name or "")).strip(" .")[:80] or fallback
def export_name(playbook_id):
    """Default file name for a chain export: <chain-name>.loya-chain.json (characters a file system dislikes replaced)."""
    return _safe_file_stem(_book(playbook_id)["name"])+".loya-chain.json"
def export_json(playbook_id):
    loaded=_load(playbook_id)
    return json.dumps(_schema.export_bundle(loaded["book"]["name"],loaded["book"].get("caller") or "",loaded["graph"]),ensure_ascii=False,indent=2)
def import_json(text,name=None):
    """Import a chain export as a NEW chain. An imported diagram came from outside, so it is flagged for review like an AI-made one."""
    bundle=_schema.import_bundle(text)
    title=str(name or "").strip() or bundle["name"] or "Imported chain"
    # A sub-chain node points at a chain id of the install that made the export; here that id is another chain (or none).
    cleared=[]
    for item in bundle["graph"].get("nodes") or []:
        if item.get("type")=="subchain" and (item.get("config") or {}).get("playbook_id") not in (None,""):
            item["config"]["playbook_id"]=None
            cleared.append({"node":item.get("id"),"edge":None,"code":"subchain_cleared","message":(item.get("title") or "Sub-chain")+": the chain it ran is not part of the file. Pick the chain again."})
    result=_schema.validate_graph(bundle["graph"])
    # The exported caller is only a wish: when it is taken (or invalid) a free one is derived from the name.
    wanted=bundle.get("caller") or None
    if wanted and not _chains.validate_caller(wanted).get("ok"):wanted=None
    playbook_id=_chains.create_playbook(title,wanted)
    try:
        _store.save_graph(playbook_id,result["graph"],ai_made=False,ai_reviewed=False,ai_client="import",schema_version=_schema.SCHEMA_VERSION)
    except Exception:
        _chains.delete_playbook(playbook_id)
        raise
    _audit("chain_diagram_create",f"chain {playbook_id} '{title[:120]}' imported, nodes={len(result['graph']['nodes'])}")
    return {"playbook_id":playbook_id,"warnings":cleared+list(result["warnings"])+list(result["errors"])}
# ---- planning and running ------------------------------------------------------------------------------------------
def _reachable(graph,start):
    """Node ids a run starting at `start` can touch."""
    following={}
    for edge in graph.get("edges") or []:following.setdefault(edge.get("from"),[]).append(edge.get("to"))
    seen=set();stack=[start]
    while stack:
        node_id=stack.pop()
        if node_id in seen:continue
        seen.add(node_id)
        stack.extend(following.get(node_id,()))
    return seen
def _needs_review(row):
    return bool(row) and not row["ai_reviewed"]
TERMINAL_DISABLED="Enable the terminal in Settings first"
def _terminal_enabled():
    try:return bool(_terminal().get_settings().get("enabled"))
    except Exception:return False
_RAW_REFUSED="This chain was made by an AI or has not been reviewed, and a command uses ${raw:...} (a value inserted without shell quoting). Replace it with ${...} first."
def _sandbox_info():
    """{"sandbox":"bwrap"|"none","network_isolation":bool} - how script nodes are contained on this computer."""
    return _engine.sandbox_info()
SCRIPT_ISOLATION_MODES=("allow","sandboxed")
SCRIPTS_BLOCKED="Script isolation is set to Sandboxed and no sandbox is available on this computer, so the script nodes of this chain cannot run."
def _global_isolation():
    from Cores.Services import ai_service
    flows_ext=ai_service._extensions(ai_service._read_settings()).get("flows")
    mode=(flows_ext if isinstance(flows_ext,dict) else {}).get("script_isolation")
    return mode if mode in SCRIPT_ISOLATION_MODES else "allow"
def policy_get():
    """{"script_isolation":"allow"|"sandboxed","sandbox":{...}}: the app-wide rule for script nodes (settings.json > extensions.flows)."""
    return {"script_isolation":_global_isolation(),"sandbox":_sandbox_info()}
def policy_set(values):
    values=values if isinstance(values,dict) else {}
    mode=values.get("script_isolation")
    if mode not in SCRIPT_ISOLATION_MODES:raise ValueError("script_isolation must be 'allow' or 'sandboxed'.")
    from Cores.Services import ai_service
    with _settings_lock:
        data=ai_service._read_settings()
        ext=ai_service._extensions(data)
        flows_ext=dict(ext.get("flows")) if isinstance(ext.get("flows"),dict) else {}
        old=flows_ext.get("script_isolation") if flows_ext.get("script_isolation") in SCRIPT_ISOLATION_MODES else "allow"
        flows_ext["script_isolation"]=mode
        ext["flows"]=flows_ext
        data["extensions"]=ext
        ai_service._write_settings(data)
    if old!=mode:_audit("chain_script_policy",f"script isolation {old} -> {mode}")
    return policy_get()
def _script_policy(row,graph,has_scripts,sandbox):
    """-> ({"mode","source","unsandboxed","blocked"}, warning issue | None) for one chain.
    The diagram's own setting can always tighten; it loosens a global "sandboxed" only for a reviewed chain no AI made."""
    mode,source,warning=_global_isolation(),"global",None
    own=((graph.get("settings") or {}).get("script_isolation")) or "inherit"
    if own=="sandboxed":mode,source="sandboxed","diagram"
    elif own=="allow" and mode=="sandboxed":
        if row and (row["ai_made"] or not row["ai_reviewed"]):
            warning={"node":None,"edge":None,"code":"script_isolation_ignored","message":"This diagram asks to allow unsandboxed scripts, but it is AI-made or not reviewed, so the app setting (Sandboxed) stays in force."}
        else:mode,source="allow","diagram"
    unsandboxed=sandbox.get("sandbox")=="none"
    return {"mode":mode,"source":source,"unsandboxed":unsandboxed,"blocked":bool(mode=="sandboxed" and unsandboxed and has_scripts)},warning
def _fingerprint(graph):
    """Identifies the exact diagram a confirmation or approval was given for."""
    return hashlib.sha256(json.dumps(graph,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode("utf-8","replace")).hexdigest()[:32]
def _subchains(graph,scope):
    """The sub-chain nodes a run can reach: [{"node","title","playbook_id","name","needs_review","error"}]."""
    out=[]
    for item in graph["nodes"]:
        if item["type"]!="subchain" or item["id"] not in scope:continue
        child_id=(item.get("config") or {}).get("playbook_id")
        row={"node":item["id"],"title":item.get("title") or "","playbook_id":child_id,"name":"","needs_review":False,"error":""}
        if child_id in (None,""):row["error"]="No chain is picked."
        else:
            try:
                child=_load(child_id)
                row["name"]=child["book"]["name"]
                row["needs_review"]=_needs_review(child["row"])
            except Exception:
                row["error"]="That chain no longer exists."
        out.append(row)
    return out
def _plan(loaded,graph=None,from_node=None):
    term=_terminal()
    check=_checked(graph if graph is not None else loaded["graph"],loaded["book"]["id"])
    normal=check["graph"]
    row=loaded["row"]
    name,values,replacer=_engine.live_target()
    start=from_node or next((n["id"] for n in normal["nodes"] if n["type"]=="start"),None)
    blocked=""
    if from_node and from_node not in {n["id"] for n in normal["nodes"]}:blocked="That node is not in the diagram."
    scope=_reachable(normal,start) if start else set()
    commands=[];missing_all=[]
    for line in _schema.graph_commands(normal):
        if line["node"] not in scope:continue
        resolved,missing,_warn=_engine.resolve_command(line["text"],replacer,keep_tokens=True)
        for m in missing:
            if m not in missing_all:missing_all.append(m)
        commands.append({"node":line["node"],"title":line["title"],"text":line["text"],"resolved":resolved,"missing":missing,"destructive":bool(term.command_is_destructive(resolved))})
    network={n["id"]:(n.get("config") or {}).get("network") is True for n in normal["nodes"] if n["type"]=="script"}
    scripts=[{"node":s["node"],"title":s["title"],"language":s["language"],"lines":len(str(s["code"]).splitlines()),"network":bool(network.get(s["node"]))} for s in _schema.graph_scripts(normal) if s["node"] in scope]
    sandbox=_sandbox_info()
    script_policy,policy_warning=_script_policy(row,normal,bool(scripts),sandbox)
    warnings=list(check["warnings"])+([policy_warning] if policy_warning else [])
    terminal_on=_terminal_enabled()
    # ${raw:...} puts a value into a command line unquoted. A chain an AI wrote (or one nobody reviewed) may not use it at all.
    raw=sorted({name for line in _schema.graph_commands(normal) for name in _engine.raw_names(line["text"])})
    raw_refused=bool(raw) and bool(row) and (row["ai_made"] or not row["ai_reviewed"])
    # An AI-made chain with script nodes and no sandbox is confirmed by the operator on every run, not only the first.
    review_each_run=bool(row and row["ai_made"] and scripts and sandbox.get("sandbox")=="none")
    approvals=sum(1 for n in normal["nodes"] if n["type"]=="approval" and n["id"] in scope)
    # Nodes that act on the world outside the run (HTTP requests, files, notes, reports, targets): shown before a run starts.
    actions=_nodes.plan_actions(normal["nodes"],scope,replacer)
    subchains=_subchains(normal,scope)
    if not blocked:
        broken=next((c for c in subchains if c["error"]),None)
        unreviewed=next((c for c in subchains if c["needs_review"]),None)
        if check["errors"]:blocked="The diagram has errors: "+_issue_text(check["errors"],3)
        elif not terminal_on:blocked=TERMINAL_DISABLED
        elif raw_refused:blocked=_RAW_REFUSED
        elif script_policy["blocked"]:blocked=SCRIPTS_BLOCKED
        elif missing_all:blocked="Fill these in on the live target first: "+", ".join("{"+m+"}" for m in missing_all)
        elif broken:blocked="Sub-chain node '"+broken["title"]+"': "+broken["error"]
        elif unreviewed:blocked="Sub-chain '"+unreviewed["name"]+"' was made by an AI or imported and has not been reviewed. Open it and review it first."
        elif not commands and not scripts and len(scope)<=1:blocked="The diagram has nothing to run yet."
    return {"target":{"name":name,"values":values},"commands":commands,"scripts":scripts,"actions":actions,"approvals":approvals,"subchains":subchains,"ai_made":bool(row and row["ai_made"]),"needs_review":_needs_review(row) or review_each_run,"review_each_run":review_each_run,"terminal_enabled":terminal_on,"sandbox":sandbox,"script_policy":script_policy,"raw":raw,"raw_refused":raw_refused,"errors":check["errors"],"warnings":warnings,"blocked":blocked,"missing":missing_all,"fingerprint":_fingerprint(normal),"graph":normal}
def plan(playbook_id,graph=None,from_node=None):
    """What a run would do, for the confirmation dialog: the target, every resolved command, scripts, approvals."""
    out=_plan(_load(playbook_id),graph,from_node)
    out.pop("graph",None)
    return out
def _subchain_loader(playbook_id):
    try:loaded=_load(playbook_id)
    except ValueError:return None
    # A chain an AI made or changed (or an import) never runs unseen, not even as a part of a reviewed chain.
    if _needs_review(loaded["row"]):raise ValueError("Sub-chain '"+loaded["book"]["name"]+"' has not been reviewed by the operator yet")
    check=_checked(loaded["graph"],loaded["book"]["id"])
    if check["errors"]:raise ValueError("Sub-chain '"+loaded["book"]["name"]+"' has errors: "+_issue_text(check["errors"],3))
    # The sub-chain's own policy travels with it: the engine lets it tighten the run, never loosen it.
    policy,_warning=_script_policy(loaded["row"],check["graph"],True,_sandbox_info())
    return {"name":loaded["book"]["name"],"graph":check["graph"],"script_mode":policy["mode"]}
def _last_status(playbook_id):
    """The most recent real run of a chain (still in memory, or from the history), for "re-run from this node"."""
    for row in _store.list_runs(playbook_id,20):
        if row.get("mode")!="run":continue
        live=_engine.get_run(row["run_id"])
        return live.status() if live is not None else _store.get_run(row["run_id"])
    for snapshot in reversed(_engine.pending_snapshots()):
        if snapshot.get("playbook_id")==playbook_id and snapshot.get("mode")=="run":return snapshot
    return None
def run(playbook_id,opts=None):
    """Start a run. opts={"mode":"run"|"dry","from_node","source":"manual"|"caller"|"live","confirmed","review_ack","graph"}.
    A real run needs confirmed=True, a valid diagram, every {Placeholder} filled and - for an AI-made or imported chain
    that nobody has reviewed - review_ack=True (which records the review). opts["fingerprint"] (from plan) is optional:
    when given, the run is refused if the diagram changed since that plan was shown."""
    if common_db.db_locked():raise ValueError(_LOCKED_MESSAGE)
    return _start(_load(playbook_id),opts)
def _start(loaded,opts):
    if common_db.db_locked():raise ValueError(_LOCKED_MESSAGE)
    opts=opts if isinstance(opts,dict) else {}
    mode="dry" if opts.get("mode")=="dry" else "run"
    source=str(opts.get("source") or "manual")
    if source not in ("manual","caller","live","ai"):source="manual"
    from_node=str(opts.get("from_node") or "") or None
    book,row=loaded["book"],loaded["row"]
    unsaved=opts.get("graph") if isinstance(opts.get("graph"),dict) else None
    if unsaved is not None and mode!="dry":raise ValueError("Save the diagram before running it. Only a dry run can use unsaved changes.")
    info=_plan(loaded,unsaved,from_node)
    graph=info["graph"]
    if info["errors"]:raise ValueError("The diagram has errors: "+_issue_text(info["errors"]))
    if from_node and from_node not in {n["id"] for n in graph["nodes"]}:raise ValueError("That node is not in the diagram.")
    if opts.get("fingerprint") and str(opts["fingerprint"])!=info["fingerprint"]:raise ValueError("The diagram changed after it was checked. Look at it again before running.")
    seed=None
    if mode=="run":
        # Commands run through the terminal job system: with the terminal extension off nothing may execute (dry runs still work).
        if not info["terminal_enabled"]:raise ValueError(TERMINAL_DISABLED)
        if not opts.get("confirmed"):raise ValueError("Confirm the run first.")
        if info["missing"]:raise ValueError("Fill these in on the live target first: "+", ".join("{"+m+"}" for m in info["missing"]))
        stuck=next((c for c in info["subchains"] if c["error"] or c["needs_review"]),None)
        if stuck:raise ValueError(info["blocked"] or "A sub-chain cannot run.")
        if info["raw_refused"]:raise ValueError(_RAW_REFUSED)
        if info["script_policy"]["blocked"]:raise ValueError(SCRIPTS_BLOCKED)
        if info["review_each_run"] and not opts.get("review_ack"):raise ValueError("This AI-made chain runs scripts and no sandbox is available on this computer. Review it and confirm before every run.")
        if _needs_review(row):
            if not opts.get("review_ack"):raise ValueError("This chain was made by an AI or imported and has not been reviewed. Review it and confirm before running.")
            _store.set_reviewed(book["id"],True)
            _audit("chain_diagram_edit",f"chain {book['id']} '{book['name'][:120]}' "+("reviewed: the operator approved its first AI run" if source=="ai" else "reviewed by the operator before its first run"))
        if any(r["playbook_id"]==book["id"] and r["mode"]=="run" for r in _engine.active_runs()):raise ValueError("This chain is already running.")
        if from_node:seed=_engine.seed_from_status(graph,_last_status(book["id"]),from_node)
    _engine.flush_pending()
    started=_engine.start_run(graph,playbook_id=book["id"],name=book["name"],mode=mode,source=source,from_node=from_node,seed=seed,loader=_subchain_loader,script_mode=info["script_policy"]["mode"])
    return {"run_id":started.run_id}
def run_status(run_id,since=0):
    live=_engine.get_run(run_id)
    if live is not None:return live.status(since)
    stored=next((s for s in _engine.pending_snapshots() if s.get("run_id")==str(run_id)),None) or _store.get_run(run_id)
    if stored is None:raise ValueError("No such run.")
    try:since=int(since or 0)
    except (TypeError,ValueError):since=0
    if since:stored=dict(stored,events=[e for e in stored.get("events") or [] if e.get("seq",0)>since],nodes=_engine.slim_nodes(stored.get("nodes"),since))
    if not isinstance(stored.get("results"),list):stored=dict(stored,results=[])   # runs stored before result nodes existed
    return stored
def active_runs():
    return _engine.active_runs()
def _live(run_id):
    live=_engine.get_run(run_id)
    if live is None:raise ValueError("No such run, or it has already finished.")
    return live
def pause(run_id):return _live(run_id).pause()
def resume(run_id):return _live(run_id).resume()
def stop(run_id):return _live(run_id).stop("stopped by the operator")
def approve(run_id,node_id,approved):
    return _live(run_id).approve(node_id,bool(approved))
def wait(run_id,timeout=30):
    """Block until a run finishes (tests, the AI dry run). -> final status, or the current one at the timeout."""
    live=_engine.get_run(run_id)
    if live is not None:live.finished.wait(timeout)
    return run_status(run_id)
def stop_all(reason="stopped"):
    return _engine.stop_all(reason)
# ---- run history ---------------------------------------------------------------------------------------------------
def runs(playbook_id=None,limit=30):
    _engine.flush_pending()
    return _store.list_runs(None if playbook_id in (None,"") else _pid(playbook_id),limit)
def run_get(run_id):
    return run_status(run_id)
def run_delete(run_id):
    live=_engine.get_run(run_id)
    if live is not None and live.active():raise ValueError("Stop the run before deleting it.")
    _engine.forget_run(run_id)
    return _store.delete_run(run_id)
def runs_clear(playbook_id=None):
    _engine.flush_pending()
    return _store.clear_runs(None if playbook_id in (None,"") else _pid(playbook_id))
def run_log(run_id,since=0,limit=2000):
    """The structured log of a run (real or dry), live from memory or from ChainRunLogs.
    -> {"run_id","entries":[entries with seq>since],"next":last seq returned (or since),"live":bool,"total":n}."""
    try:since=max(0,int(since or 0))
    except (TypeError,ValueError):since=0
    try:limit=max(1,min(int(limit or 2000),_engine.LOG_MAX))
    except (TypeError,ValueError):limit=2000
    run_id=str(run_id or "")
    live=_engine.get_run(run_id)
    if live is not None:
        entries,total,_last=live.log_entries(since,limit)
        active=live.active()
    else:
        _engine.flush_pending()
        entries,total=_store.get_run_log(run_id,since,limit)
        waiting=_engine.pending_log(run_id)
        if waiting:
            total+=len(waiting)
            entries=(entries+[e for e in waiting if e["seq"]>since])[:limit]
        active=False
        if not total and _store.get_run(run_id) is None and not any(s.get("run_id")==run_id for s in _engine.pending_snapshots()):raise ValueError("No such run.")
    return {"run_id":run_id,"entries":entries,"next":entries[-1]["seq"] if entries else since,"live":active,"total":total}
def run_log_text(run_id):
    """The whole log as plain text: a header saying which clock is used, then one entry per line (time, LEVEL, node
    title, text; the stderr tail of a failed command follows on indented lines). Times are local, like the UI shows
    them; the run_start line also carries the date. The JSON export keeps the ISO UTC timestamps."""
    entries=run_log(run_id,0,_engine.LOG_MAX)["entries"]
    if not entries:return ""
    def local(ts):
        try:return datetime.fromisoformat(str(ts)).astimezone()
        except (TypeError,ValueError):return None
    first=local(entries[0].get("ts")) or datetime.now().astimezone()
    offset=first.utcoffset() or timedelta(0)
    minutes=int(offset.total_seconds()//60)
    lines=["# times are local, UTC offset %s%02d:%02d"%("-" if minutes<0 else "+",abs(minutes)//60,abs(minutes)%60)]
    for entry in entries:
        when=local(entry.get("ts"))
        stamp=(when.strftime("%Y-%m-%d %H:%M:%S" if entry.get("kind")=="run_start" else "%H:%M:%S") if when else str(entry.get("ts") or "")[11:19])
        title=str(entry.get("title") or "")
        body=str(entry.get("text") or "").replace("\r\n","\n").split("\n")
        lines.append(stamp+" "+str(entry.get("level") or "info").upper().ljust(5)+" "+(("["+title+"] ") if title else "")+" ".join(body[0].split()))
        lines.extend("    "+line.rstrip() for line in body[1:] if line.strip())
    return "\n".join(lines)+"\n"
def run_log_file(run_id,fmt="text"):
    """(default file name, extension, content) for exporting a run log. fmt: "text" (.log) or "json"."""
    fmt="json" if str(fmt or "").lower()=="json" else "text"
    run_id=str(run_id or "")
    log=run_log(run_id,0,_engine.LOG_MAX)
    try:name=run_status(run_id).get("name") or ""
    except ValueError:name=""
    ext="json" if fmt=="json" else "log"
    content=json.dumps({"run_id":run_id,"chain":name,"entries":log["entries"]},ensure_ascii=False,indent=2)+"\n" if fmt=="json" else run_log_text(run_id)
    return _safe_file_stem(name,"chain")+"-"+_safe_file_stem(run_id,"run")+"."+ext,ext,content
# ---- editor preferences (settings.json > extensions.flow_editor) ---------------------------------------------------
def _clean_prefs(raw):
    raw=raw if isinstance(raw,dict) else {}
    out=dict(PREF_DEFAULTS)
    for key in ("snap","minimap"):
        if isinstance(raw.get(key),bool):out[key]=raw[key]
    for key,low,high in (("grid",5,100),("inspector_width",240,720)):
        value=raw.get(key)
        if isinstance(value,(int,float)) and not isinstance(value,bool):out[key]=int(max(low,min(high,value)))
    if isinstance(raw.get("hotbar"),list):
        # Hot bar pins: node type ids or palette preset ids, in order, each once, at most HOTBAR_MAX.
        known=set(_nodes.catalog_ids());pins=[]
        for item in raw["hotbar"]:
            if isinstance(item,str) and item in known and item not in pins:pins.append(item)
        out["hotbar"]=pins[:HOTBAR_MAX]
    else:out["hotbar"]=list(PREF_DEFAULTS["hotbar"])
    return out
def prefs_get():
    from Cores.Services import ai_service
    return _clean_prefs(ai_service._extensions(ai_service._read_settings()).get("flow_editor"))
def prefs_set(values):
    from Cores.Services import ai_service
    with _settings_lock:
        data=ai_service._read_settings()
        ext=ai_service._extensions(data)
        merged=_clean_prefs(dict(_clean_prefs(ext.get("flow_editor")),**(values if isinstance(values,dict) else {})))
        ext["flow_editor"]=merged
        data["extensions"]=ext
        ai_service._write_settings(data)
    return merged
# ---- AI (MCP) entry points; the permission gate itself lives in mcp_server._check -------------------------------------
_SECRET_KEY_RX=re.compile(r"pass|pwd|secret|token|hash|ntlm|cookie|cred|api[ _-]?key|private[ _-]?key|ssh[ _-]?key|session[ _-]?(id|key)|bearer",re.I)   # as mcp_app_tools
_JSON_PAIR_RX=re.compile(r'("([^"\\]{1,80})"\s*:\s*)"((?:[^"\\]|\\.){1,4000})"')
_HIDDEN="[hidden]"
def _secret_key(name):
    return bool(_SECRET_KEY_RX.search(str(name or "")))
def _redacted(text):
    """Text an AI client reads: the terminal's secret redactor, then the values of secret-looking keys in JSON text
    (a node's output is often an object as JSON, e.g. a target with its password)."""
    try:text=_terminal().redact_secrets(str(text or ""))[0]
    except Exception:text=str(text or "")
    if '"' in text and ":" in text:text=_JSON_PAIR_RX.sub(lambda m:m.group(1)+'"'+_HIDDEN+'"' if _secret_key(m.group(2)) else m.group(0),text)
    return text
def _ai_graph_schema():
    """The graph JSON Schema without the per-type config of the field-driven types (chain_node_types has those, one type
    at a time), so chain_templates stays small enough to read."""
    slim=copy.deepcopy(_schema.JSON_SCHEMA)
    node=slim["$defs"]["node"]
    node["allOf"]=[variant for variant in node["allOf"] if variant["if"]["properties"]["type"]["const"] in _nodes.LEGACY_TYPES]
    node["description"]="The config of the node types not spelled out here: chain_node_types with type=<id>."
    return slim
def ai_templates():
    return {"templates":[{"id":t["id"],"name":t["name"],"description":t["description"],"graph":copy.deepcopy(t["graph"])} for t in _schema.TEMPLATES],"node_types":{k:{"description":v["description"],"ports":v["ports"],"config":v["defaults"]} for k,v in _schema.NODE_TYPES.items()},"limits":dict(_schema.LIMITS),"graph_schema":_ai_graph_schema(),"notes":"Command lines may use {Placeholders} (filled from the live target) and ${vars} (flow values, shell-quoted). chain_node_types lists the node types by category and, for one type, every config field with its options. A chain you create or change is marked AI-made and the operator must review and approve its first run."}
def ai_create(name,graph,caller="",client=""):
    return create(name,graph,(caller or None),ai_client=str(client or "AI"))
def ai_update(playbook_id,graph,name="",client=""):
    out=save(playbook_id,graph,ai_client=str(client or "AI"))
    if str(name or "").strip():_chains.rename_playbook(_pid(playbook_id),name)
    return dict(out,playbook_id=_pid(playbook_id))
# ---- AI: the node catalog, validation without saving and small edits of a stored diagram -----------------------------------
def ai_node_types(category="",node_type="",query="",offset=0,limit=20):
    """The node catalog for an AI client, small enough to read: without `node_type` a page of {type,label,category,ports,
    description} rows (filter by category and/or words); with `node_type` (one id, or several separated by commas) the
    full parameter schema of those types: defaults, every config field with its type/options/limits, fail port, presets."""
    wanted=[name.strip() for name in str(node_type or "").split(",") if name.strip()]
    if wanted:
        unknown=[name for name in wanted if name not in _nodes.SPECS]
        if unknown:raise ValueError("Unknown node type: "+", ".join(unknown[:5])+". Call chain_node_types without a type to list them.")
        return {"schema":_schema.SCHEMA_VERSION,"types":[_nodes.param_schema(name) for name in wanted[:12]],
                "values":"Text fields take ${name} / ${last.stdout} / ${nodes.<id>.parsed} flow values; a node with a var field stores its result there (${var}, ${var.field}, ${var[0]})."}
    category=str(category or "").strip().lower()
    words=[word for word in str(query or "").lower().split() if word][:6]
    rows=[]
    for name,spec in _nodes.SPECS.items():
        if category and spec["category"]!=category:continue
        hay=" ".join([name,spec["label"],spec["description"]]+list(spec.get("keywords") or [])).lower()
        if any(word not in hay for word in words):continue
        rows.append({"type":name,"label":spec["label"],"category":spec["category"],"ports":spec["ports"] if not spec.get("dynamic") else _nodes.param_schema(name)["ports"],"description":spec["description"]})
    try:offset=max(0,int(offset or 0))
    except (TypeError,ValueError):offset=0
    try:limit=max(1,min(60,int(limit or 20)))
    except (TypeError,ValueError):limit=20
    counts={}
    for spec in _nodes.SPECS.values():counts[spec["category"]]=counts.get(spec["category"],0)+1
    return {"schema":_schema.SCHEMA_VERSION,"categories":[{"id":c["id"],"label":c["label"],"types":counts.get(c["id"],0)} for c in _nodes.CATEGORIES],
            "items":rows[offset:offset+limit],"total":len(rows),"offset":offset,"limit":limit,"more":offset+limit<len(rows),
            "next":"Call chain_node_types with type=<id> (or several, comma separated) for the config fields of a type."}
def ai_validate(graph,playbook_id=None):
    """Check a graph without storing it. -> {"ok","errors","warnings","nodes","edges"} (the normalized graph is not echoed back)."""
    if isinstance(graph,str):
        try:graph=json.loads(graph)
        except ValueError:raise ValueError("The diagram is not valid JSON.") from None
    result=_checked(graph,None if playbook_id in (None,"",0) else _pid(playbook_id))
    return {"ok":result["ok"],"errors":result["errors"],"warnings":result["warnings"],"nodes":len(result["graph"]["nodes"]),"edges":len(result["graph"]["edges"])}
def _ai_graph(playbook_id):
    return copy.deepcopy(_schema.validate_graph(_load(playbook_id)["graph"])["graph"])
def _free_id(graph,prefix):
    used={str(n.get("id")) for n in graph["nodes"]}|{str(e.get("id")) for e in graph["edges"]}
    counter=1
    while prefix+str(counter) in used:counter+=1
    return prefix+str(counter)
def _ai_node(graph,node_id):
    found=next((n for n in graph["nodes"] if n["id"]==str(node_id or "")),None)
    if found is None:raise ValueError("There is no node '%s' in this diagram."%str(node_id)[:40])
    return found
def _ai_stored(playbook_id,graph,client,**extra):
    return dict(ai_update(playbook_id,graph,"",client),**extra)
def _place(value,default):
    return default if value is None or isinstance(value,bool) or not isinstance(value,(int,float)) else value
def ai_node_add(playbook_id,node_type,config=None,title="",x=None,y=None,after="",port="",client=""):
    """Add one node to a stored diagram (and connect it behind `after`.`port` when given). node_type may be a palette
    preset id. Goes through ai_update: the result must validate, and the chain becomes AI-made and unreviewed."""
    graph=_ai_graph(playbook_id)
    preset=next((p for p in _nodes.PRESETS if p["id"]==str(node_type or "")),None)
    kind=preset["type"] if preset else str(node_type or "")
    if kind not in _schema.NODE_TYPES:raise ValueError("Unknown node type '%s'. Call chain_node_types to list them."%kind[:40])
    merged=copy.deepcopy(_schema.NODE_TYPES[kind]["defaults"])
    if preset:merged.update(copy.deepcopy(preset["config"]))
    if isinstance(config,dict):merged.update(config)
    source=_ai_node(graph,after) if str(after or "").strip() else None
    if source is not None:
        exits=_schema.node_ports(source)["out"]
        port=str(port or "").strip() or (exits[0] if exits else "")
        siblings=sum(1 for e in graph["edges"] if e["from"]==source["id"])
        default_x,default_y=source["x"]+300,source["y"]+160*siblings
    else:
        default_x=max([n["x"] for n in graph["nodes"] if n["type"]!="comment"] or [40])+300
        default_y=next((n["y"] for n in graph["nodes"] if n["type"]=="start"),160)
    node_id=_free_id(graph,"n")
    graph["nodes"].append({"id":node_id,"type":kind,"title":str(title or "").strip() or (preset["title"] if preset else _schema.NODE_TYPES[kind]["label"]),"x":_place(x,default_x),"y":_place(y,default_y),"config":merged})
    edge_id=""
    if source is not None:
        edge_id=_free_id(graph,"e")
        graph["edges"].append({"id":edge_id,"from":source["id"],"port":port,"to":node_id})
    return _ai_stored(playbook_id,graph,client,node_id=node_id,edge_id=edge_id)
def ai_node_set(playbook_id,node_id,config=None,title="",x=None,y=None,client=""):
    """Change one node: `config` is merged key by key into the node's config; title/x/y only when given."""
    graph=_ai_graph(playbook_id)
    item=_ai_node(graph,node_id)
    if isinstance(config,dict):item["config"]=dict(item.get("config") or {},**config)
    if str(title or "").strip():item["title"]=str(title).strip()
    item["x"]=_place(x,item["x"]);item["y"]=_place(y,item["y"])
    return _ai_stored(playbook_id,graph,client,node_id=item["id"])
def ai_node_delete(playbook_id,node_id,client=""):
    graph=_ai_graph(playbook_id)
    item=_ai_node(graph,node_id)
    if item["type"]=="start":raise ValueError("The Start node cannot be deleted.")
    graph["nodes"]=[n for n in graph["nodes"] if n["id"]!=item["id"]]
    before=len(graph["edges"])
    graph["edges"]=[e for e in graph["edges"] if e["from"]!=item["id"] and e["to"]!=item["id"]]
    return _ai_stored(playbook_id,graph,client,node_id=item["id"],edges_removed=before-len(graph["edges"]))
def ai_connect(playbook_id,from_node,port,to_node,remove=False,client=""):
    """Add (or with remove=True delete) the connection from_node.port -> to_node."""
    graph=_ai_graph(playbook_id)
    source=_ai_node(graph,from_node);target=_ai_node(graph,to_node)
    port=str(port or "").strip() or (_schema.node_ports(source)["out"] or [""])[0]
    existing=next((e for e in graph["edges"] if e["from"]==source["id"] and e["port"]==port and e["to"]==target["id"]),None)
    if remove:
        if existing is None:raise ValueError("There is no connection %s.%s -> %s."%(source["id"],port,target["id"]))
        graph["edges"].remove(existing)
        return _ai_stored(playbook_id,graph,client,edge_id=existing["id"],removed=True)
    if existing is not None:return {"ok":True,"errors":[],"warnings":[],"playbook_id":_pid(playbook_id),"edge_id":existing["id"],"unchanged":True}
    edge_id=_free_id(graph,"e")
    graph["edges"].append({"id":edge_id,"from":source["id"],"port":port,"to":target["id"]})
    return _ai_stored(playbook_id,graph,client,edge_id=edge_id)
def ai_run_info(playbook_id):
    """What the approval prompt needs before an AI may run a chain. Raises ValueError when the chain cannot run at all.
    force_ask: the operator must approve this run whatever the permission level or session grants say."""
    if common_db.db_locked():raise ValueError(_LOCKED_MESSAGE)
    loaded=_load(playbook_id)
    info=_plan(loaded)
    if info["errors"]:raise ValueError("The diagram has errors: "+_issue_text(info["errors"]))
    if not info["terminal_enabled"]:raise ValueError(TERMINAL_DISABLED)
    if info["raw_refused"]:raise ValueError(_RAW_REFUSED)
    if info["script_policy"]["blocked"]:raise ValueError(SCRIPTS_BLOCKED)
    if info["missing"]:raise ValueError("The live target has no value for: "+", ".join("{"+m+"}" for m in info["missing"]))
    stuck=next((c for c in info["subchains"] if c["error"] or c["needs_review"]),None)
    if stuck:raise ValueError(info["blocked"] or "A sub-chain cannot run.")
    unreviewed=_needs_review(loaded["row"])
    destructive=[c["resolved"] for c in info["commands"] if c["destructive"]]
    subchains=[c["name"] for c in info["subchains"]]
    actions=[a["summary"] or a["type"] for a in info["actions"]]
    # HTTP requests and file access reach outside the app like a script does: such a chain always goes to the operator.
    outside=[a["type"] for a in info["actions"] if a["type"] in _nodes.FORCE_ASK_TYPES]
    # A sub-chain's commands are not listed in the prompt, so a chain that runs one always goes to the operator.
    return {"playbook_id":loaded["book"]["id"],"name":loaded["book"]["name"],"derived":loaded["derived"],"unreviewed":unreviewed,"destructive":destructive,"scripts":len(info["scripts"]),"subchains":subchains,"commands":[c["resolved"] for c in info["commands"]],"actions":actions,"target":info["target"]["name"],"fingerprint":info["fingerprint"],"force_ask":bool(unreviewed or destructive or info["scripts"] or subchains or outside)}
def ai_run(playbook_id,fingerprint="",approved_first_run=False,operator_approved=False):
    """Start a real run for an AI caller AFTER mcp_server authorized it. fingerprint (from ai_run_info) pins the run to
    the diagram the operator was shown: a chain edited while the approval was pending is refused.
    approved_first_run: the operator approved an unreviewed chain, which counts as the review.
    operator_approved: this very call went through the operator's approval prompt (force_ask), which is the per-run
    confirmation an unsandboxed AI-made script chain needs."""
    loaded=_load(playbook_id)
    if _needs_review(loaded["row"]) and not approved_first_run:raise ValueError("This chain has not been reviewed by the operator yet.")
    return _start(loaded,{"mode":"run","source":"ai","confirmed":True,"review_ack":bool(approved_first_run or operator_approved),"fingerprint":str(fingerprint or "") or _fingerprint(_schema.validate_graph(loaded["graph"])["graph"])})
def ai_dry_run(playbook_id,timeout=20):
    started=run(playbook_id,{"mode":"dry","source":"ai"})
    return ai_status(started["run_id"],wait_seconds=timeout)
def ai_status(run_id,wait_seconds=0):
    """Run status for an AI client: secrets redacted, output tails shortened."""
    status=wait(run_id,wait_seconds) if wait_seconds else run_status(run_id)
    nodes={}
    for node_id,rec in (status.get("nodes") or {}).items():
        out=rec.get("output") or {}
        nodes[node_id]={"state":rec.get("state"),"branch":rec.get("branch"),"visits":rec.get("visits"),"error":_redacted(rec.get("error")),"exit_code":out.get("exit_code"),"resolved":[_redacted(c) for c in out.get("resolved") or []],"stdout":_redacted(str(out.get("stdout") or "")[-4000:]),"stderr":_redacted(str(out.get("stderr") or "")[-2000:])}
    return {"run_id":status.get("run_id"),"playbook_id":status.get("playbook_id"),"name":status.get("name"),"mode":status.get("mode"),"state":status.get("state"),"reason":status.get("reason"),"target":status.get("target"),"started_at":status.get("started_at"),"ended_at":status.get("ended_at"),"current":status.get("current"),"approval":status.get("approval"),"nodes":nodes,"results":_ai_results(status),"events":[{"node":e.get("node"),"level":e.get("level"),"text":_redacted(e.get("text"))} for e in (status.get("events") or [])[-80:]]}
def _redacted_deep(value,depth=0):
    if isinstance(value,str):return _redacted(value)
    if depth>8:return None
    # A value under a secret-looking key (a target's password, hash, token ...) is hidden whatever it looks like.
    if isinstance(value,dict):return {str(k):(_HIDDEN if _secret_key(k) and isinstance(v,(str,int,float)) and not isinstance(v,bool) and str(v).strip() else _redacted_deep(v,depth+1)) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [_redacted_deep(v,depth+1) for v in value]
    return value
def _ai_results(status):
    return [{"node":r.get("node"),"label":_redacted(r.get("label")),"value":_redacted_deep(_nodes.cap_value(r.get("value"),8000)[0])} for r in (status.get("results") or [])[-50:] if isinstance(r,dict)]
def ai_node_output(run_id,node_id="",max_chars=8000):
    """What a run produced, for an AI client (secrets redacted, sizes capped). Without node_id: the run's state, its
    `results` list (Return result nodes) and one line per node saying how much output it has. With node_id: that node's
    stdout/stderr tails, its structured `parsed` value, the variables it set and, for an HTTP node, the status line."""
    status=run_status(run_id)
    try:max_chars=max(200,min(40000,int(max_chars or 8000)))
    except (TypeError,ValueError):max_chars=8000
    head={"run_id":status.get("run_id"),"playbook_id":status.get("playbook_id"),"name":status.get("name"),"mode":status.get("mode"),"state":status.get("state"),"reason":_redacted(status.get("reason"))}
    nodes=status.get("nodes") or {}
    if not str(node_id or "").strip():
        rows=[]
        for key,rec in nodes.items():
            out=rec.get("output") or {}
            rows.append({"node":key,"state":rec.get("state"),"branch":rec.get("branch"),"visits":rec.get("visits"),"error":_redacted(rec.get("error")),"stdout_chars":len(str(out.get("stdout") or "")),"stderr_chars":len(str(out.get("stderr") or "")),"has_parsed":out.get("parsed") is not None,"vars_set":sorted((out.get("vars_set") or {}).keys())[:20]})
        return dict(head,results=_ai_results(status),nodes=rows)
    rec=nodes.get(str(node_id))
    if rec is None:raise ValueError("There is no node '%s' in this run."%str(node_id)[:40])
    out=rec.get("output") or {}
    parsed,cut=_nodes.cap_value(out.get("parsed"),max_chars)
    shown={"node":str(node_id),"state":rec.get("state"),"branch":rec.get("branch"),"visits":rec.get("visits"),"duration_ms":rec.get("duration_ms"),"error":_redacted(rec.get("error")),"exit_code":out.get("exit_code"),
           "stdout":_redacted(str(out.get("stdout") or "")[-max_chars:]),"stderr":_redacted(str(out.get("stderr") or "")[-max_chars//2:]),"parsed":_redacted_deep(parsed),"parsed_truncated":bool(cut or out.get("truncated")),
           "vars_set":_redacted_deep(_nodes.cap_value(out.get("vars_set") or {},max_chars)[0]),"resolved":[_redacted(c) for c in (out.get("resolved") or [])[:20]]}
    for key in ("http","result","file","planned","merge","match_count"):
        if key in out:shown[key]=_redacted_deep(_nodes.cap_value(out[key],2000)[0])
    return dict(head,output=shown)
def ai_stop(run_id):
    return _live(run_id).stop("stopped by the AI")
# ---- AI panel: the /newchain authoring guide and the draft it produces ---------------------------------------------------
GUIDE_FENCE="loya-chain"
_GUIDE_PORTS={"script":"each name in config.branches, plus error","decision":"each branch name, plus the config.else name","switch":"each case name, plus the config.default name"}
_GUIDE_NOTES={
    "command":'commands = [{"text":"<command line>"}], at least one. success = every command exited 0, otherwise fail. mode: sequence | parallel.',
    "script":"language: %s. network: true only when the script itself must reach the network (a sandboxed script has none otherwise). Use it only when no decision/parse node can do the job. The script gets one JSON object on stdin (and in the file $LOYA_INPUT_FILE): "
             '{"input":<previous node\'s data>,"vars":{...},"target":{...},"item":...}. The LAST line it prints must be one JSON object: '
             '{"branch":"<one of config.branches>","vars":{"name":"value"},"output":"text"}. A non-zero exit or a timeout takes the error port.'%" | ".join(_schema.SCRIPT_LANGUAGES),
    "decision":"branches are tested top to bottom; the first whose conditions hold wins (match: all | any); none -> the else port. Every branch needs at least one condition.",
    "parse":'mode: %s. mode "tool" uses a built-in parser (tool: %s) - nmap gives {"hosts","ports","open_ports"}. mode "regex" needs pattern; assign = [{"var":"ip","from":"group:1"}]. '
            "The result is stored in the variable named by var. nomatch = nothing found."%(" | ".join(_schema.PARSE_MODES)," | ".join(_schema.PARSE_TOOLS)),
    "set":'assign = [{"var":"name","value":"text with ${values}"}].',
    "foreach":"items = a ${value} or text to split (split: %s). The item port runs once per item (use ${item} there), then done."%" | ".join(_schema.SPLIT_MODES),
    "approval":"Put one before anything intrusive or destructive.",
    "output":"action: %s. severity: %s. note_append needs note_name."%(" | ".join(_schema.OUTPUT_ACTIONS)," | ".join(_schema.SEVERITIES)),
    "subchain":"playbook_id must be the id of an existing chain; do not invent one.",
    "end":"status: success | fail. Optional: a path may simply stop.",
}
_GUIDE_NOTES.update({name:note for name,note in ((name,_nodes.guide_note(name)) for name in _nodes.FIELD_TYPES) if note})   # generated from the field specs
def _guide_example():
    """The example the guide shows: ping -> alive? -> nmap | notify. Small on purpose; test_flow_ai_guide checks it validates."""
    ping=getattr(_schema,"_PING","ping -c 2 {IPv4}")
    nodes=[
        {"id":"n1","type":"start","title":"Start","x":40,"y":160,"config":{}},
        {"id":"n2","type":"command","title":"Ping the host","x":300,"y":160,"config":{"commands":[{"text":ping}],"timeout":60}},
        {"id":"n3","type":"decision","title":"Host alive?","x":560,"y":160,"config":{"branches":[{"name":"alive","match":"all","conditions":[{"source":"host_up","op":"is_true"}]}],"else":"down"}},
        {"id":"n4","type":"command","title":"Nmap scan","x":820,"y":160,"config":{"commands":[{"text":"nmap -Pn -sV --top-ports 1000 {IPv4}"}],"timeout":1800}},
        {"id":"n5","type":"output","title":"Host is down","x":820,"y":310,"config":{"action":"notify","title":"Host did not answer","content":"${last.stdout}"}},
    ]
    edges=[("n1","out","n2"),("n2","success","n3"),("n2","fail","n3"),("n3","alive","n4"),("n3","down","n5")]
    return {"name":"Ping, then scan when alive","graph":{"schema":_schema.SCHEMA_VERSION,"nodes":nodes,"edges":[{"id":"e%d"%(i+1),"from":a,"port":p,"to":b} for i,(a,p,b) in enumerate(edges)]}}
def ai_guide():
    """What a chat model needs to write a valid diagram, built from flow_schema so it cannot drift from the real rules.
    -> {"fence","guide","example"}. The AI panel sends `guide` with the user's request and looks for a ```loya-chain block in the reply."""
    compact=lambda value:json.dumps(value,ensure_ascii=False,separators=(",",":"))
    limits=_schema.LIMITS
    example=_guide_example()
    lines=[
        "You are writing a chain diagram for LOYA NG: an attack-flow automation graph (nodes joined by edges) that a penetration tester reviews and then runs against the live target.",
        "Answer with one or two sentences saying what the chain does, then exactly ONE fenced code block tagged %s that holds only JSON of the form {\"name\":\"<short chain name>\",\"graph\":{...}}. No comments and no trailing commas in the JSON. Do not use tools for this and never say the chain was run: the operator opens it in the diagram editor, reviews it and starts it."%GUIDE_FENCE,
        "",
        "GRAPH",
        '{"schema":%d,"settings":%s,"nodes":[{"id":"n1","type":"start","title":"Start","x":40,"y":160,"config":{}}],"edges":[{"id":"e1","from":"n1","port":"out","to":"n2"}]}'%(_schema.SCHEMA_VERSION,compact(_schema.DEFAULT_SETTINGS)),
        "- ids: letters, digits, _ and -, at most %d characters, unique. title: at most %d characters. Exactly one start node."%(limits["id_chars"],limits["title_chars"]),
        "- An edge leaves a named output port of \"from\" and enters the single input of \"to\". No edge may enter a start or comment node. Several edges may leave one port (they run in order). Port and branch names: letters, digits, _ and -, at most %d characters."%limits["port_chars"],
        "- Layout runs left to right: add about 300 to x per step and about 160 to y for each parallel branch.",
        "- settings.on_error: stop | continue (what happens when a node fails and its fail/error port has no edge). Config keys you leave out get their default.",
        "- Limits: %d nodes, %d edges, %d commands per command node, %d branches per decision, %d conditions per branch, regex up to %d characters."%(limits["nodes"],limits["edges"],limits["commands_per_node"],limits["branches"],limits["conditions"],limits["regex_chars"]),
        "",
        "NODE TYPES (type: what it does | output ports | config with its defaults)",
    ]
    for name,spec in _schema.NODE_TYPES.items():
        ports=_GUIDE_PORTS.get(name) or (", ".join(spec["ports"]) if spec["ports"] else "none")
        lines.append("- %s: %s | ports: %s | config: %s"%(name,spec["description"],ports,compact(spec["defaults"])))
        if name in _GUIDE_NOTES:lines.append("  "+_GUIDE_NOTES[name])
    lines+=[
        "",
        "CONDITION (inside a decision branch)",
        '{"source":S,"field":"","op":OP,"value":"","ci":true}   (ci = ignore case). It looks at the output of the node just before the decision.',
        "- S: %s."%" | ".join(_schema.SOURCES),
        "  var: field = variable name. parsed: field = path into the parsed data (ports[*].port). match_count: field = regex to count. port_open: value = port number. host_up: no value (reads ping/nmap output). port_open and host_up take op is_true or is_false.",
        "- OP: %s. eq/ne/gt/ge/lt/le compare numbers."%" ".join(_schema.OPS),
        "",
        "VALUES",
        "- {IPv4}, {Host}, {Port}, {URL}, {Domain}, {Username}: target placeholders, filled from the operator's live target. Use them in command lines for anything about the target; never hard-code an address.",
        "- ${name}, ${last.stdout}, ${last.exit_code}, ${nodes.n2.stdout}, ${item}, ${target.ipv4}: flow values (variables, the previous node's output, another node's output, the for-each item). Inside a command line they are shell-quoted for you, so do not add quotes around them. Never use ${raw:...}.",
        "- A node whose config has \"var\" stores its result in that variable: ${var}, ${var.field}, ${var[0]}; a config value that is exactly one ${...} keeps lists and objects as they are.",
        "",
        "EXAMPLE (ping the target; when it is alive run nmap, otherwise notify)",
        "```"+GUIDE_FENCE,
        compact(example),
        "```",
    ]
    return {"fence":GUIDE_FENCE,"guide":"\n".join(lines),"example":example}
def create_ai_draft(name,graph,client=""):
    """Store a diagram the AI panel's chat model wrote (a ```loya-chain reply the operator chose to open) as a NEW chain,
    AI-made and not reviewed: the run confirmation then demands the review. Like chain_create it must be valid: storing
    normalizes a diagram (a bad edge is dropped), so a broken one would be saved as something the model never wrote."""
    if isinstance(graph,dict) and "nodes" not in graph and isinstance(graph.get("graph"),dict):
        name=name or graph.get("name");graph=graph["graph"]   # an export bundle {name, graph} is accepted too
    result=_usable_graph(graph)
    if not result["ok"]:raise ValueError("The diagram is not valid: "+_issue_text(result["errors"]))
    title=str(name or "").strip()[:200] or "AI chain"
    label=("AI panel: "+str(client).strip()[:60]) if str(client or "").strip() else "AI panel"
    playbook_id=_chains.create_playbook(title,None)
    try:
        _store.save_graph(playbook_id,result["graph"],ai_made=True,ai_reviewed=False,ai_client=label,schema_version=_schema.SCHEMA_VERSION)
    except Exception:
        _chains.delete_playbook(playbook_id)
        raise
    _audit("chain_diagram_create",f"chain {playbook_id} '{title[:120]}' nodes={len(result['graph']['nodes'])} edges={len(result['graph']['edges'])} source=ai-panel ({label}), AI-made and not reviewed")
    return {"playbook_id":playbook_id,"errors":result["errors"],"warnings":result["warnings"]}
