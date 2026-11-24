"""Chain Diagrams executor. One FlowRun walks one graph on its own daemon thread: deterministic depth-first, bounded by
visit caps and timeouts, stoppable at any moment (the running process tree is killed), and stopped when the app locks.
Every command line goes through the terminal job system (TerminalJobs row + audit entry + captured output); scripts go
through flow_scripts.run_script. Nothing here evaluates user text as Python."""
import atexit,copy,html,os,re,signal,subprocess,threading,time,uuid
from datetime import datetime,timezone
from Cores import common_db
MAX_NODE_VISITS=50
MAX_DEPTH=3
OUTPUT_CAP=64*1024
CAPTURE_MAX=4*1024*1024
EVENTS_MAX=2000
LOG_MAX=20000          # structured log entries kept per run; one "log truncated" entry marks the cut
LOG_BATCH=100          # entries written to ChainRunLogs per batch while a run is going
KEEP_FINISHED=40
MAX_ACTIVE_RUNS=8
FINAL_STATES=("done","failed","cancelled","timeout")
JOB_SOURCES={"manual":"flow","live":"flow","caller":"flow-caller","ai":"flow-ai"}
_IS_WINDOWS=os.name=="nt"
_TOKEN_RE=re.compile(r"\$\{[^{}\r\n]*\}")
_MISSING_RE=re.compile(r"(?<!\$)\{([A-Za-z_][A-Za-z0-9_ ]*)\}")
_FAIL_PORTS={"command":"fail","script":"error","subchain":"fail"}
_BARE_NAME=re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,39}$")
_SCOPE_ROOTS=("vars","last","nodes","target","item","index")
def _now():return datetime.now(timezone.utc).isoformat()
def _terminal():
    from Cores.Services import terminal_service
    return terminal_service
def _rules():
    from Cores.Services import flow_rules
    return flow_rules
def _schema():
    from Cores.Services import flow_schema
    return flow_schema
def _scripts():
    from Cores.Services import flow_scripts
    return flow_scripts
def _nodes():
    from Cores.Services import flow_nodes
    return flow_nodes
def _audit(event,detail,success=True):
    try:
        from Cores.Services import security_service
        security_service.log_audit_event(event,str(detail)[:1000],success)
    except Exception:
        pass
def _redact(value,depth=0):
    """Secrets out of anything that goes into the stored run log (strings anywhere inside lists/dicts)."""
    if isinstance(value,str):
        try:return _terminal().redact_secrets(value)[0]
        except Exception:return value
    if depth>6:return None
    if isinstance(value,dict):return {str(k):_redact(v,depth+1) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [_redact(v,depth+1) for v in value]
    return value
def _last_lines(text,lines=20,chars=2000):
    """The end of an output stream for the log: at most `lines` lines and `chars` characters."""
    kept=str(text or "").replace("\r\n","\n").rstrip().split("\n")[-lines:]
    return "\n".join(kept)[-chars:].strip("\n")
def sandbox_info():
    """{"sandbox":"bwrap"|"none","network_isolation":bool}: how script nodes are contained on this computer."""
    try:
        info=_scripts().sandbox_info()
        return {"sandbox":str(info.get("sandbox") or "none"),"network_isolation":bool(info.get("network_isolation"))}
    except Exception:
        return {"sandbox":"none","network_isolation":False}
SCRIPTS_NEED_SANDBOX="Script nodes may only run inside the sandbox (script isolation is set to Sandboxed) and no sandbox is available on this computer."
def _tail(text,limit=OUTPUT_CAP):
    text=str(text or "")
    return text if len(text)<=limit else text[-limit:]
def _num(value,default,low,high):
    try:value=float(value)
    except (TypeError,ValueError):value=default
    return max(low,min(high,value))
# ---- live target and command-line resolution -------------------------------------------------------------------------
def live_target():
    """(name, {lower-cased key: value}, CommandReplacer) of the live target, read once per run."""
    from Cores.Services import search_service
    ctx=search_service.LiveTargetContext()
    return ctx.name or "",dict(ctx.map or {}),search_service.CommandReplacer(ctx)
def raw_names(text):
    """Names used as ${raw:name} (inserted unquoted) in a text."""
    template_re=getattr(_rules(),"_TEMPLATE_RE",None)
    if template_re is None:return sorted(set(m.group(1).strip() for m in re.finditer(r"(?<!\$)\$\{raw:\s*([^{}]*?)\s*\}",str(text or ""))))
    return sorted(set(m.group(3).strip() for m in template_re.finditer(str(text or "")) if m.group(2) and not m.group(1)))
def resolve_command(text,replacer,scope=None,quoter=None,keep_tokens=False,raw_ok=None):
    """One command line -> (resolved, missing placeholders, warnings).
    {Placeholders} are filled exactly like the linear chains (CommandReplacer). The ${...} flow tokens are masked while
    that happens, so a flow value is never read as a {Placeholder}; any ${...} that arrives inside a target value is
    escaped, so it stays literal text. Then the whole line goes through flow_rules.expand_template ONCE with the shell
    quoter (which looks at the text before each value, e.g. the user's own quotes). keep_tokens leaves ${...} as written
    (plans and dry runs, where the values do not exist yet). Raises flow_rules.RuleError for a value the target shell
    cannot take safely."""
    rules=_rules()
    template_re=getattr(rules,"_TEMPLATE_RE",_TOKEN_RE)
    tokens=[]
    mark="\x00"+uuid.uuid4().hex[:8]
    def stash(match):
        tokens.append(match.group(0))
        return mark+str(len(tokens)-1)+"\x00"
    masked=template_re.sub(stash,str(text or "").replace("\x00",""))
    resolved=replacer.apply(masked) if replacer is not None else masked.strip()
    missing=sorted(set(_MISSING_RE.findall(resolved)))
    if not keep_tokens:resolved=template_re.sub(lambda match:"$"+match.group(0),resolved)
    resolved=re.sub(re.escape(mark)+r"(\d+)\x00",lambda match:tokens[int(match.group(1))],resolved)
    if keep_tokens:return resolved,missing,[]
    # ${raw:name} skips the quoter, so it is only allowed for names raw_ok approves (a run: literal `set` variables).
    refused=[name for name in raw_names(resolved) if raw_ok is None or not raw_ok(name)]
    if refused:raise rules.RuleError("${raw:"+refused[0]+"} is not allowed here: an unquoted value must come from a Set variable node with plain text (no ${...}). Use ${"+refused[0]+"} instead.")
    resolved,warnings=rules.expand_template(resolved,scope or {},quoter,raw_ok=raw_ok)
    return resolved,missing,[str(w) for w in (warnings or [])]
def pick_shell(wanted=""):
    """A shell id the terminal knows: the wanted one when it exists here, else the default shell."""
    shells=[s["id"] for s in _terminal().list_shells()]
    wanted=str(wanted or "").strip()
    if wanted and wanted in shells:return wanted
    return shells[0] if shells else ""
def kill_tree(proc,grace=1.5):
    """Stop a process and everything it started. POSIX: SIGTERM to the process group, then SIGKILL; Windows: taskkill /T /F."""
    if proc is None:return
    if _IS_WINDOWS:
        if proc.poll() is not None:return
        try:
            subprocess.run(["taskkill","/T","/F","/PID",str(proc.pid)],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        except Exception:
            pass
        try:
            if proc.poll() is None:proc.kill()
        except Exception:
            pass
        return
    # The command was started with start_new_session=True, so its pid is the id of a process group of its own.
    pgid=proc.pid
    if proc.poll() is None:
        try:os.killpg(pgid,signal.SIGTERM)
        except Exception:
            try:proc.terminate()
            except Exception:pass
        try:proc.wait(timeout=grace)
        except Exception:pass
    # Children that ignored SIGTERM (or outlived the shell) still hold the group id.
    try:os.killpg(pgid,signal.SIGKILL)
    except Exception:pass
    try:
        if proc.poll() is None:proc.kill()
    except Exception:
        pass
def _drain(stream,sink):
    # Keeps reading to EOF so the child never blocks on a full pipe, but stores at most CAPTURE_MAX bytes.
    held=0
    try:
        while True:
            chunk=stream.read(65536)
            if not chunk:break
            if held<CAPTURE_MAX:
                sink.append(chunk[:CAPTURE_MAX-held])
                held+=len(chunk)
    except Exception:
        pass
    finally:
        try:stream.close()
        except Exception:pass
def slim_nodes(nodes,since=0):
    """Node records for a status poll. since==0: everything. Otherwise a node's `output` is only sent when the node changed
    after `since` (node["seq"]>since); the state fields are always there, so the page merges by node id."""
    out={}
    for node_id,rec in (nodes or {}).items():
        if not isinstance(rec,dict):continue
        if since and int(rec.get("seq") or 0)<=since:out[node_id]={k:(list(v) if isinstance(v,list) else v) for k,v in rec.items() if k!="output"}
        else:out[node_id]=copy.deepcopy(rec)
    return out
def seed_from_status(graph,status,from_node):
    """What a re-run from `from_node` starts with, rebuilt from an earlier run's status: its variables, every node's
    last envelope, and as `last` the envelope of the node that fed `from_node`."""
    status=status if isinstance(status,dict) else {}
    types={n.get("id"):n.get("type") for n in (graph.get("nodes") or [])}
    envs={}
    ended={}
    for node_id,rec in (status.get("nodes") or {}).items():
        if not isinstance(rec,dict) or rec.get("state") not in ("success","fail") or node_id not in types:continue
        out=rec.get("output") if isinstance(rec.get("output"),dict) else {}
        envs[node_id]={"node":node_id,"type":types[node_id],"ok":rec.get("state")=="success","exit_code":out.get("exit_code"),"stdout":out.get("stdout") or "","stderr":out.get("stderr") or "","branch":rec.get("branch") or "","parsed":out.get("parsed"),"duration_ms":rec.get("duration_ms") or 0,"commands":[]}
        ended[node_id]=str(rec.get("ended_at") or "")
    feeders=[e.get("from") for e in (graph.get("edges") or []) if e.get("to")==from_node and e.get("from") in envs]
    feeders.sort(key=lambda node_id:ended.get(node_id,""))
    last=envs[feeders[-1]] if feeders else None
    saved=status.get("vars")
    return {"vars":copy.deepcopy(saved) if isinstance(saved,dict) else {},"envs":envs,"last":last}
# ---- the run -------------------------------------------------------------------------------------------------------
class FlowRun:
    def __init__(self,graph,playbook_id=None,name="",mode="run",source="manual",from_node=None,seed=None,loader=None,parent=None,variables=None,on_finish=None,script_mode="allow"):
        self.graph=graph if isinstance(graph,dict) else {}
        self.playbook_id=playbook_id
        self.name=str(name or "")
        self.mode="dry" if mode=="dry" else "run"
        self.source=str(source or "manual")
        self.from_node=from_node or None
        self.loader=loader
        self.parent=parent
        self.root=parent.root if parent is not None else self
        self.depth=parent.depth+1 if parent is not None else 0
        self.on_finish=on_finish
        self.run_id="run"+uuid.uuid4().hex[:12]
        self.job_source=JOB_SOURCES.get(self.source,"flow")
        settings=self.graph.get("settings") if isinstance(self.graph.get("settings"),dict) else {}
        self.shell_setting=str(settings.get("shell") or "")
        self.run_timeout=_num(settings.get("run_timeout"),1800,1,86400)
        self.max_visits=int(_num(settings.get("max_visits"),200,1,2000))
        self.on_error="continue" if settings.get("on_error")=="continue" else "stop"
        self.nodes={}
        for node in self.graph.get("nodes") or []:
            if isinstance(node,dict) and node.get("id"):self.nodes[str(node["id"])]=node
        self.edges_out={}
        for edge in self.graph.get("edges") or []:
            if isinstance(edge,dict):self.edges_out.setdefault((str(edge.get("from")),str(edge.get("port"))),[]).append(edge)
        # Incoming connections per node (a merge node in "all" mode waits for that many arrivals) and what merges have collected.
        self.edges_in={}
        for edge in self.graph.get("edges") or []:
            if isinstance(edge,dict):self.edges_in[str(edge.get("to"))]=self.edges_in.get(str(edge.get("to")),0)+1
        self._merge={}
        seed=seed if isinstance(seed,dict) else {}
        self.vars=copy.deepcopy(variables) if isinstance(variables,dict) else copy.deepcopy(seed.get("vars") or {})
        self.envs=dict(seed.get("envs") or {})
        self.seed_last=seed.get("last")
        self.item=None
        self.index=None
        # Names of variables a `set` node filled from pure literal text. Only these may be used as ${raw:name} in a command.
        self.trusted=set()
        # Script isolation: once a run (or the chain that started this sub-chain) demands the sandbox, nothing below loosens it.
        self.script_sandboxed=bool(parent is not None and parent.script_sandboxed) or script_mode=="sandboxed" or settings.get("script_isolation")=="sandboxed"
        self.log=[]
        self._exit_noted=set()
        self._log_seq=0
        self._log_saved=0
        self._log_full=False
        self._log_flushed=time.monotonic()
        self._started_mono=time.monotonic()
        self._counts={"nodes":0,"commands":0,"scripts":0,"warnings":0,"errors":0}
        if parent is not None:
            self.target_name,self.target_values,self.replacer=parent.target_name,parent.target_values,parent.replacer
        else:
            self.target_name,self.target_values,self.replacer=live_target()
        self._lock=threading.RLock()
        self._halt_evt=threading.Event()
        self._resume_evt=threading.Event()
        self._resume_evt.set()
        self._final=None
        self._approval=None
        self._child=None
        self._parent_node=None
        self._thread=None
        self._total_visits=0
        self._job_pos=0
        self._seq=0
        self._deadline=None
        self._failed_nodes=0
        self.finished=threading.Event()
        self.data={"run_id":self.run_id,"playbook_id":playbook_id,"name":self.name,"mode":self.mode,"state":"running","reason":"","source":self.source,"target":self.target_name,"started_at":_now(),"ended_at":"","current":None,"nodes":{node_id:self._blank_node() for node_id,node in self.nodes.items() if node.get("type")!="comment"},"edges_taken":[],"events":[],"approval":None,"vars":{},"notices":[],"results":[],"pausing":False,"seq":0}
    @staticmethod
    def _blank_node():
        return {"state":"pending","visits":0,"branch":"","started_at":"","ended_at":"","duration_ms":0,"error":"","job_keys":[],"output":{},"seq":0}
    # -- public control ------------------------------------------------------------------------------------------
    def start(self):
        self._thread=threading.Thread(target=self.execute,name="flow-"+self.run_id,daemon=True)
        self._thread.start()
        return self
    def active(self):
        return not self.finished.is_set()
    def status(self,since=0):
        try:since=int(since or 0)
        except (TypeError,ValueError):since=0
        with self._lock:
            out=dict(self.data)
            out["nodes"]=slim_nodes(self.data["nodes"],since)
            out["edges_taken"]=list(self.data["edges_taken"])
            out["events"]=[dict(e) for e in self.data["events"] if e["seq"]>since]
            out["approval"]=dict(self.data["approval"]) if self.data["approval"] else None
            out["notices"]=[dict(n) for n in self.data["notices"]]
            out["results"]=copy.deepcopy(self.data.get("results") or [])
            out["vars"]=copy.deepcopy(self.vars)
            out["seq"]=self._seq
        return out
    def summary(self):
        with self._lock:
            return {k:self.data[k] for k in ("run_id","playbook_id","name","mode","state","reason","source","target","started_at","ended_at","current")}
    def pause(self):
        with self._lock:
            if not self.active() or self.data["state"]!="running" or self.data["pausing"]:return False
            self._resume_evt.clear()
            # The node that is running finishes first: until then the run is still "running", with pausing=True.
            self.data["pausing"]=True
        self._event(None,"info","Pause requested (takes effect after the current node)")
        return True
    def resume(self):
        with self._lock:
            if not self.active() or self._resume_evt.is_set():return False
            self._resume_evt.set()
            self.data["pausing"]=False
            if self.data["state"]=="paused":self.data["state"]="running"
        self._event(None,"info","Resumed")
        return True
    def stop(self,reason="stopped",state="cancelled"):
        """Ask the run to end now. The thread that is waiting on a process kills its whole tree and winds down."""
        if not self.active():return False
        self._request_halt(state,reason)
        return True
    def approve(self,node_id,approved):
        """Answer the approval node that is waiting (in this run or in a sub-chain it is running)."""
        with self._lock:
            pending=self.data["approval"]
            if not pending or str(pending.get("node"))!=str(node_id or ""):return False
        run=self
        while run is not None:
            with run._lock:
                wait=run._approval
                child=run._child
            if wait is not None and wait["answer"] is None:
                wait["answer"]="approved" if approved else "rejected"
                wait["event"].set()
                return True
            run=child
        return False
    # -- internals ----------------------------------------------------------------------------------------------
    def _title(self,node_id):
        node=self.nodes.get(node_id) if node_id else None
        return str((node or {}).get("title") or "") if node else ""
    def _event(self,node_id,level,text,kind=None,data=None,quiet=False):
        """One line for the live status (unless quiet) and, when it has a kind, one entry in the structured run log.
        Warnings and errors always get a log entry."""
        root=self.root
        if self is not root:
            # A sub-chain reports into its parent's log, under the parent's sub-chain node.
            inner=self._title(node_id)
            return self.parent._event(self._parent_node,level,"["+self.name+"] "+((inner+": ") if inner and quiet else "")+str(text),kind,data,quiet)
        kind=None if kind is False else (kind or {"warn":"warning","error":"error"}.get(level))  # kind=False: status line only, no log entry
        with self._lock:
            if not quiet:
                self._seq+=1
                self.data["events"].append({"seq":self._seq,"ts":_now(),"node":node_id,"level":level,"text":str(text)[:2000]})
                if len(self.data["events"])>EVENTS_MAX:del self.data["events"][:len(self.data["events"])-EVENTS_MAX]
                self.data["seq"]=self._seq
            if not kind or self._log_full:return
            if level=="warn":self._counts["warnings"]+=1
            elif level=="error":self._counts["errors"]+=1
            self._log_seq+=1
            if len(self.log)>=LOG_MAX-1:
                self._log_full=True
                self.log.append({"seq":self._log_seq,"ts":_now(),"node":None,"title":"","level":"warn","kind":"warning","text":"Log truncated: this run wrote more than "+str(LOG_MAX)+" entries.","data":{}})
                return
            # Never an unredacted command line, value or message: the log is kept in the database.
            self.log.append({"seq":self._log_seq,"ts":_now(),"node":node_id,"title":self._title(node_id),"level":level if level in ("info","warn","error") else "info","kind":kind,"text":_redact(str(text))[:4000],"data":_redact(data) if isinstance(data,dict) else {}})
    def _note(self,kind,node_id,text,data=None,level="info"):
        """A log-only entry (nothing added to the live status events)."""
        self._event(node_id,level,text,kind,data,quiet=True)
    def _note_exit(self,node_id,fail_port,headline,succeeded,data,stderr="",stdout=""):
        """The one log entry for a finished command or script. A non-zero exit carries the tail of stderr (stdout when
        stderr is empty); it is a warning when the node's fail/error port is connected, an error otherwise."""
        self._exit_noted.add(node_id)
        if succeeded:return self._note("exit",node_id,headline,data)
        tail=_last_lines(stderr) or _last_lines(stdout)
        data=dict(data,stderr_tail=tail)
        handled=bool(self.edges_out.get((node_id,fail_port)))
        self._note("exit",node_id,headline+(("\n"+tail) if tail else ""),data,"warn" if handled else "error")
    def log_entries(self,since=0,limit=2000):
        """-> (entries with seq>since, total, last seq) of the root run's structured log."""
        with self._lock:
            entries=[dict(e,data=dict(e["data"])) for e in self.log if e["seq"]>since][:max(1,int(limit))]
            return entries,len(self.log),self._log_seq
    def _flush_log(self,final=False):
        """Write the entries not stored yet as one batch. Behind the lock (or when the DB is busy) they stay in memory."""
        if self is not self.root:return
        with self._lock:
            batch=self.log[self._log_saved:]
            count=len(batch)
        if not count:return
        if not final and count<LOG_BATCH and time.monotonic()-self._log_flushed<2.0:return
        self._log_flushed=time.monotonic()
        stored=False
        if not common_db.db_locked():
            try:
                from Cores.Services import flow_store
                flow_store.append_run_log(self.run_id,batch)
                stored=True
            except Exception:
                stored=False
        if not stored and final:
            with _runs_lock:_unsaved_logs.append((self.run_id,batch))
            stored=True
        if stored:
            with self._lock:self._log_saved+=count
    def _request_halt(self,state,reason):
        with self._lock:
            if self._final is None:self._final=(state,str(reason or ""))
            wait=self._approval
            child=self._child
        self._halt_evt.set()
        self._resume_evt.set()
        if wait is not None:wait["event"].set()
        if child is not None:child._request_halt(state,reason)
    def _halted(self):
        return self._halt_evt.is_set()
    def _check_limits(self):
        """Node boundary / wait-loop check: a locked app or an expired run timeout ends the run. True when halted."""
        if self._halted():return True
        root=self.root
        if common_db.is_locked():
            root._request_halt("cancelled","locked")
            return True
        with root._lock:waiting=root.data["state"] in ("paused","waiting_approval")
        if root._deadline is not None and not waiting and time.monotonic()>root._deadline:
            root._request_halt("timeout","The run took longer than "+str(int(root.run_timeout))+" s")
            return True
        return self._halted()
    def _watchdog(self):
        while not self.finished.wait(0.2):
            self._check_limits()
    def _remaining(self):
        root=self.root
        if root._deadline is None:return 86400.0
        return max(0.0,root._deadline-time.monotonic())
    def _set_state(self,state):
        root=self.root
        with root._lock:
            if root.data["state"] not in FINAL_STATES:root.data["state"]=state
    def _node_rec(self,node_id):
        return self.data["nodes"].setdefault(node_id,self._blank_node())
    def _touch(self,rec):
        # Called with self._lock held after a node record changed: a poller that passes since=<seq> gets this node's output again.
        self._seq+=1
        rec["seq"]=self._seq
        self.data["seq"]=self._seq
    def _scope(self,last):
        return {"vars":self.vars,"last":last or {},"nodes":self.envs,"target":self.target_values,"item":self.item,"index":self.index}
    def _raw_ok(self,name):
        """May ${raw:name} be inserted unquoted? Only a plain variable that a set node filled with literal text."""
        name=str(name or "").strip()
        return bool(_BARE_NAME.match(name)) and name in self.trusted and name not in _SCOPE_ROOTS
    def _shell(self,node_shell=""):
        return pick_shell(node_shell or self.shell_setting)
    def _next_pos(self):
        root=self.root
        with root._lock:
            pos=root._job_pos
            root._job_pos+=1
        return pos
    def execute(self):
        """Run to the end on the calling thread (start() calls this on a new thread; a sub-chain calls it inline)."""
        is_root=self is self.root
        if is_root:
            self._deadline=time.monotonic()+self.run_timeout
            _audit("chain_run_start",f"{self.job_source} {'dry run' if self.mode=='dry' else 'run'} {self.run_id} chain {self.playbook_id} '{self.name}' target '{self.target_name}'"+(f" from node {self.from_node}" if self.from_node else ""))
            threading.Thread(target=self._watchdog,name="flow-watch-"+self.run_id,daemon=True).start()
        self._event(None,"info",("Dry run" if self.mode=="dry" else "Run")+" started"+(f" from node {self.from_node}" if self.from_node else ""),"run_start",{"run_id":self.run_id,"chain":self.name,"playbook_id":self.playbook_id,"mode":self.mode,"source":self.source,"target":self.target_name,"from_node":self.from_node,"scripts_sandboxed":self.script_sandboxed,"nodes":len(self.data["nodes"])})
        try:
            start=self.from_node or next((node_id for node_id,node in self.nodes.items() if node.get("type")=="start"),None)
            if start is None or start not in self.nodes:
                self._request_halt("failed","The diagram has no start node" if not self.from_node else "Node "+str(self.from_node)+" does not exist")
            elif self.mode=="dry":
                self._walk_dry(start)
            else:
                self._walk(start,self.seed_last if self.from_node else None)
        except Exception as exc:
            self._request_halt("failed","Internal error: "+str(exc)[:300])
        self._finish()
        return self.data["state"]
    def _finish(self):
        with self._lock:
            state,reason=self._final or ("done","")
            if state=="done" and self._failed_nodes and self.mode=="run":reason=str(self._failed_nodes)+" node(s) failed; the run continued (on_error=continue)"
            for rec in self.data["nodes"].values():
                # Whatever never ran (branches not taken, or everything after a stop) is shown as skipped.
                before=rec["state"]
                if rec["state"] in ("running","waiting"):rec["state"]="skipped" if state!="done" else rec["state"]
                if rec["state"]=="pending" and self.mode=="run":rec["state"]="skipped"
                if rec["state"]!=before:self._touch(rec)
            self.data["state"]=state
            self.data["reason"]=reason
            self.data["ended_at"]=_now()
            self.data["current"]=None
            self.data["approval"]=None
            self.data["pausing"]=False
            self.data["vars"]=copy.deepcopy(self.vars)
        self._event(None,"info" if state=="done" else "error",{"done":"Finished","failed":"Failed","cancelled":"Stopped","timeout":"Timed out"}[state]+(": "+reason if reason else ""),"run_end",dict(self._counts,state=state,reason=reason,duration_ms=int((time.monotonic()-self._started_mono)*1000),failed_nodes=self._failed_nodes,node_visits=self._total_visits))
        if self is self.root:
            self._flush_log(final=True)
            _audit("chain_run_end",f"{self.job_source} {'dry run' if self.mode=='dry' else 'run'} {self.run_id} chain {self.playbook_id} '{self.name}' {state}"+(f" ({reason})" if reason else ""),state=="done")
            if self.on_finish is not None:
                # The history row is written before the run counts as finished, so "finished" always means "in the history".
                try:self.on_finish(self)
                except Exception:pass
        self.finished.set()
    # -- walking --------------------------------------------------------------------------------------------------
    def _gate(self):
        """Pause point between nodes. Returns False when the run must stop."""
        root=self.root
        root._flush_log()
        if not root._resume_evt.is_set():
            held=time.monotonic()
            with root._lock:
                if root.data["pausing"] and root.data["state"]=="running":root.data["state"]="paused"
                root.data["pausing"]=False
            while not root._resume_evt.wait(0.2):
                if self._check_limits():return False
            root._extend_deadline(time.monotonic()-held)
        return not self._check_limits()
    def _extend_deadline(self,seconds):
        # Time spent paused or waiting for an approval does not count against the run timeout.
        with self._lock:
            if self._deadline is not None:self._deadline+=max(0.0,seconds)
    def _push_port(self,stack,node_id,port,env):
        for edge in reversed(self.edges_out.get((node_id,port),[])):
            stack.append(("node",str(edge.get("to")),env,edge.get("id")))
    def _walk(self,start,last):
        # Explicit stack (no recursion): a cycle can legally revisit nodes up to max_visits times.
        stack=[("node",start,last,None)]
        while stack:
            task=stack.pop()
            if task[0]=="iter":
                _kind,node_id,index,item,env=task
                self.item,self.index=item,index
                self._name_loop_vars(node_id)
                self._push_port(stack,node_id,"item",env)
                continue
            if task[0]=="endloop":
                _kind,node_id,previous,env=task
                self.item,self.index=previous
                self._push_port(stack,node_id,"done",env)
                continue
            _kind,node_id,last,edge_id=task
            if not self._gate():return
            node=self.nodes.get(node_id)
            if node is None or node.get("type")=="comment":continue
            if edge_id:
                with self._lock:
                    if edge_id not in self.data["edges_taken"]:self.data["edges_taken"].append(edge_id)
            env,branch,items=self._run_node(node,last)
            if env is None or self._halted():return
            if items is not None:
                stack.append(("endloop",node_id,(self.item,self.index),env))
                for index in range(len(items)-1,-1,-1):stack.append(("iter",node_id,index,items[index],env))
                continue
            if branch:self._push_port(stack,node_id,branch,env)
    def _name_loop_vars(self,node_id):
        cfg=self.nodes[node_id].get("config") or {}
        item_var=str(cfg.get("item_var") or "item")
        index_var=str(cfg.get("index_var") or "index")
        self.vars[item_var]=self.item
        self.vars[index_var]=self.index
        self.trusted.difference_update((item_var,index_var))
    def _walk_dry(self,start):
        ports=_schema().node_ports
        seen=set()
        stack=[(start,None)]
        while stack:
            node_id,edge_id=stack.pop()
            if self._check_limits():return
            node=self.nodes.get(node_id)
            if node is None or node.get("type")=="comment":continue
            if edge_id:
                with self._lock:
                    if edge_id not in self.data["edges_taken"]:self.data["edges_taken"].append(edge_id)
            if node_id in seen:continue
            seen.add(node_id)
            self._plan_node(node)
            pending=[]
            for port in ports(node).get("out") or []:
                pending.extend(self.edges_out.get((node_id,port),[]))
            for edge in reversed(pending):stack.append((str(edge.get("to")),edge.get("id")))
    def _plan_node(self,node):
        node_id=node["id"]
        cfg=node.get("config") or {}
        output={}
        self._note("node_start",node_id,"Planned (dry run: nothing is executed)",{"type":node.get("type"),"dry":True})
        if node.get("type")=="command":
            resolved=[]
            for line in cfg.get("commands") or []:
                text=str((line or {}).get("text") or "").strip()
                if not text:continue
                command,missing,_warn=resolve_command(text,self.replacer,keep_tokens=True)
                resolved.append(command)
                self._event(node_id,"warn" if missing else "info","Would run: "+command+((" (unfilled: "+", ".join("{"+m+"}" for m in missing)+")") if missing else ""),"command",{"dry":True,"command":command,"missing":missing})
            output["resolved"]=resolved
        elif node.get("type")=="script":
            self._event(node_id,"info","Would run a "+str(cfg.get("language") or "python")+" script ("+str(len(str(cfg.get("code") or "").splitlines()))+" lines)","script",{"dry":True,"language":str(cfg.get("language") or "python"),"network":cfg.get("network") is True})
        elif node.get("type")=="approval":
            self._event(node_id,"info","Would wait for approval: "+str(cfg.get("message") or ""),"approval",{"dry":True})
        elif node.get("type")=="subchain":
            self._event(node_id,"info","Would run sub-chain "+str(cfg.get("playbook_id")))
        elif node.get("type")=="output":
            self._event(node_id,"info","Would write output ("+str(cfg.get("action") or "")+")")
        elif node.get("type") in _nodes().HANDLERS:
            line=_nodes().plan_line(node,self.replacer)
            if line:
                self._event(node_id,"info",line,"action",{"dry":True,"type":node.get("type")})
                output["planned"]=line
        with self._lock:
            rec=self._node_rec(node_id)
            rec.update({"state":"planned","visits":1,"output":output})
            self._touch(rec)
    # -- one node -----------------------------------------------------------------------------------------------
    def _run_node(self,node,last):
        """-> (envelope, branch, loop_items). envelope None = the run was halted."""
        node_id=node["id"]
        node_type=str(node.get("type") or "")
        title=str(node.get("title") or node_type)
        self._total_visits+=1
        with self._lock:
            rec=self._node_rec(node_id)
            visits=rec["visits"]+1
        if self._total_visits>self.max_visits:
            self._request_halt("failed","Visit limit reached ("+str(self.max_visits)+" node visits). A loop in the diagram probably never ends.")
            return None,None,None
        if visits>MAX_NODE_VISITS:
            self._request_halt("failed","Node '"+title+"' ran "+str(MAX_NODE_VISITS)+" times, which is the limit for one node.")
            return None,None,None
        started=time.monotonic()
        self.root._counts["nodes"]+=1
        self._note("node_start",node_id,"Started"+(" (visit "+str(visits)+")" if visits>1 else ""),{"type":node_type,"visit":visits})
        with self._lock:
            rec.update({"state":"running","visits":visits,"branch":"","started_at":_now(),"ended_at":"","duration_ms":0,"error":"","job_keys":[],"output":{}})
            self._touch(rec)
            self.data["current"]=node_id
        base={"node":node_id,"type":node_type,"ok":True,"exit_code":(last or {}).get("exit_code"),"stdout":(last or {}).get("stdout") or "","stderr":(last or {}).get("stderr") or "","branch":"","parsed":(last or {}).get("parsed"),"duration_ms":0,"commands":[]}
        output={}
        error=""
        branch=""
        items=None
        ok=True
        self._exit_noted.discard(node_id)
        try:
            handler=getattr(self,"_node_"+node_type,None)
            if handler is not None:result=handler(node,last,base,output) or {}
            elif node_type in _nodes().HANDLERS:result=_nodes().run_node(self,node,last,base,output) or {}   # the field-driven types
            else:raise ValueError("Unknown node type '"+node_type+"'")
            branch=result.get("branch") or ""
            ok=result.get("ok",True)
            error=result.get("error") or ""
            items=result.get("items")
        except Exception as exc:
            # A node that blows up fails like a failed command would: through its fail/error port when it has one.
            ok=False
            error=str(exc)[:500] or exc.__class__.__name__
            branch=_FAIL_PORTS.get(node_type) or _nodes().fail_port(node_type)
        if self._halted() and node_type!="end":
            with self._lock:
                rec.update({"state":"skipped" if not rec["job_keys"] else "fail","ended_at":_now(),"duration_ms":int((time.monotonic()-started)*1000),"error":error or "stopped","output":output})
                self._touch(rec)
            self._note("node_end",node_id,"Stopped before it finished",{"state":"stopped","duration_ms":int((time.monotonic()-started)*1000),"error":error or "stopped"},"warn")
            return None,None,None
        base["ok"]=bool(ok)
        base["branch"]=branch
        base["duration_ms"]=int((time.monotonic()-started)*1000)
        self.envs[node_id]=base
        output.setdefault("stdout",_tail(base["stdout"]))
        output.setdefault("stderr",_tail(base["stderr"]))
        output.setdefault("exit_code",base["exit_code"])
        output.setdefault("parsed",base["parsed"])
        with self._lock:
            rec.update({"state":"success" if ok else "fail","branch":branch,"ended_at":_now(),"duration_ms":base["duration_ms"],"error":error,"output":output})
            self._touch(rec)
            self.data["vars"]=copy.deepcopy(self.vars)
        # A failure the diagram deals with (its fail/error port is connected) is a warning, not an error. And when the
        # command or script already wrote its exit entry, the same message is not logged a second time.
        handled_failure=(not ok) and bool(branch) and bool(self.edges_out.get((node_id,branch)))
        if error:self._event(node_id,"warn" if ok or handled_failure else "error",title+": "+error,False if node_id in self._exit_noted else None)
        if branch:
            detail={"branch":branch}
            if node_type=="decision":detail["rules"]=[{"branch":t.get("branch"),"matched":bool(t.get("matched")),"conditions":[{"text":str(c.get("text") or "")[:200],"result":bool(c.get("result")),"actual":str(c.get("actual") or "")[:200]} for c in (t.get("conditions") or [])[:12]]} for t in (output.get("trace") or [])[:12]]
            if items is not None:detail["items"]=len(items)
            self._note("branch",node_id,"Took '"+branch+"'"+(" for "+str(len(items))+" item(s)" if items is not None else ""),detail)
        self._note("node_end",node_id,("Finished" if ok else "Failed")+" in "+str(base["duration_ms"])+" ms",{"state":"success" if ok else "fail","branch":branch,"duration_ms":base["duration_ms"],"exit_code":base["exit_code"] if node_type in ("command","script","subchain") else None,"error":error,"handled":handled_failure},"info" if ok else "warn" if handled_failure else "error")
        if node_type=="end":
            self._request_halt("done" if ok else "failed",str((node.get("config") or {}).get("message") or ""))
            return None,None,None
        if not ok:
            handled=bool(branch) and bool(self.edges_out.get((node_id,branch)))
            if not handled:
                self._failed_nodes+=1
                if self.on_error=="stop":
                    self._request_halt("failed","'"+title+"' failed"+(": "+error if error else ""))
                    return None,None,None
                self._event(node_id,"warn",title+" failed; continuing (on_error=continue)")
                # Nodes with a single way out (decision else, output, parse...) carry on through it.
                branch=result_port_for_continue(node,branch)
        return base,branch,items
    # -- node types ---------------------------------------------------------------------------------------------
    def _node_start(self,node,last,env,output):
        return {"branch":"out"}
    def _node_comment(self,node,last,env,output):
        return {"branch":""}
    def _node_end(self,node,last,env,output):
        cfg=node.get("config") or {}
        return {"ok":cfg.get("status")!="fail","branch":""}
    def _node_wait(self,node,last,env,output):
        seconds=_num((node.get("config") or {}).get("seconds"),0,0,3600)
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            if self._halt_evt.wait(min(0.2,max(0.0,deadline-time.monotonic()))):break
        return {"branch":"out"}
    def _node_set(self,node,last,env,output):
        rules=_rules()
        scope=self._scope(last)
        changed={}
        for row in (node.get("config") or {}).get("assign") or []:
            name=str((row or {}).get("var") or "").strip()
            if not name:continue
            value,warns=rules.expand_template(str(row.get("value") if row.get("value") is not None else ""),scope)
            for warn in warns or []:self._event(node["id"],"warn",str(warn))
            self.vars[name]=value
            changed[name]=value
            # Literal text typed by whoever drew the chain is trusted for ${raw:...}; anything built from other values is not.
            if "${" in str(row.get("value") if row.get("value") is not None else ""):self.trusted.discard(name)
            else:self.trusted.add(name)
        output["vars_set"]=changed
        return {"branch":"out"}
    def _node_decision(self,node,last,env,output):
        cfg=node.get("config") or {}
        result=_rules().evaluate_decision(cfg,last or {},self._scope(last))
        output["trace"]=result.get("trace") or []
        branch=str(result.get("branch") or cfg.get("else") or "else")
        self._event(node["id"],"info","Decision: "+branch)
        return {"branch":branch}
    def _node_parse(self,node,last,env,output):
        cfg=node.get("config") or {}
        result=_rules().run_parse(cfg,last or {},self._scope(last))
        found=result.get("vars") if isinstance(result.get("vars"),dict) else {}
        self.vars.update(found)
        self.trusted.difference_update(found)
        output["vars_set"]=found
        matched=bool(result.get("matched"))
        if matched:env["parsed"]=result.get("parsed")
        output["parsed"]=result.get("parsed")
        if result.get("error"):return {"branch":"nomatch","error":str(result["error"])}
        return {"branch":"out" if matched else "nomatch"}
    def _node_foreach(self,node,last,env,output):
        rules=_rules()
        cfg=node.get("config") or {}
        scope=self._scope(last)
        # "${parsed.ports}" alone hands over the real list; anything else is expanded as text and split.
        value,warns=rules.resolve_value(cfg.get("items"),scope)
        for warn in warns or []:self._event(node["id"],"warn",str(warn))
        limit=int(_num(cfg.get("max_items"),50,1,_limit("foreach_items_max",1000)))
        everything=rules.split_items(value,str(cfg.get("split") or "auto"),limit+1)
        items=list(everything)[:limit]
        if len(everything)>limit:self._event(node["id"],"warn","More than "+str(limit)+" items: only the first "+str(limit)+" are processed")
        output["vars_set"]={"count":len(items)}
        self._event(node["id"],"info","For each: "+str(len(items))+" item(s)")
        return {"branch":"item","items":items}
    def _node_approval(self,node,last,env,output):
        cfg=node.get("config") or {}
        message,_warn=_rules().expand_template(str(cfg.get("message") or "Continue?"),self._scope(last))
        timeout=_num(cfg.get("timeout"),0,0,86400)
        wait={"node":node["id"],"answer":None,"event":threading.Event()}
        root=self.root
        shown=node["id"] if self is root else self._root_node()
        with self._lock:
            self._approval=wait
            self._node_rec(node["id"])["state"]="waiting"
            self._touch(self._node_rec(node["id"]))
        with root._lock:
            root.data["approval"]={"node":shown,"message":str(message)[:1000]}
            if root.data["state"]=="running":root.data["state"]="waiting_approval"
        self._event(node["id"],"info","Waiting for approval: "+str(message)[:300],"approval",{"waiting":True,"timeout":timeout})
        deadline=time.monotonic()+timeout if timeout>0 else None
        asked=time.monotonic()
        while wait["answer"] is None:
            wait["event"].wait(0.2)
            if self._check_limits():break
            if deadline is not None and time.monotonic()>deadline:
                wait["answer"]="rejected"
                self._event(node["id"],"warn","No answer in "+str(int(timeout))+" s: treated as rejected")
        with self._lock:self._approval=None
        root._extend_deadline(time.monotonic()-asked)
        with root._lock:
            root.data["approval"]=None
            if root.data["state"]=="waiting_approval":root.data["state"]="running"
        answer=wait["answer"] or "rejected"
        if not self._halted():
            _audit("chain_run_approval",f"run {root.run_id} chain {root.playbook_id} node {node['id']} {answer}: {str(message)[:200]}",answer=="approved")
            self._event(node["id"],"info","Approval: "+answer,"approval",{"answer":answer,"waited_ms":int((time.monotonic()-asked)*1000)})
        return {"branch":answer}
    def _root_node(self):
        run=self
        while run.parent is not None and run.parent is not run.root:run=run.parent
        return run._parent_node
    def _node_command(self,node,last,env,output):
        cfg=node.get("config") or {}
        node_id=node["id"]
        shell=self._shell(cfg.get("shell"))
        quoter=_rules().shell_quoter(shell)
        scope=self._scope(last)
        lines=[]
        for position,line in enumerate(cfg.get("commands") or []):
            text=str((line or {}).get("text") or "").strip()
            if not text:continue
            command,missing,warns=resolve_command(text,self.replacer,scope,quoter,raw_ok=self._raw_ok)
            for warn in warns:self._event(node_id,"warn",warn)
            if missing:raise ValueError("The live target has no value for "+", ".join("{"+m+"}" for m in missing))
            if not command.strip():continue
            lines.append({"text":command,"label":str(line.get("label") or "")[:80] or (str(node.get("title") or "")[:60]+(" #"+str(position+1) if len(cfg.get("commands") or [])>1 else ""))})
        if not lines:raise ValueError("This command node has no command to run")
        output["resolved"]=[l["text"] for l in lines]
        deadline=time.monotonic()+_num(cfg.get("timeout"),300,1,7200)
        results=[None]*len(lines)
        if cfg.get("mode")=="parallel" and len(lines)>1:
            def work(slot):
                results[slot]=self._run_command(node_id,lines[slot],shell,deadline)
            threads=[threading.Thread(target=work,args=(slot,),daemon=True) for slot in range(len(lines))]
            for thread in threads:thread.start()
            for thread in threads:thread.join()
        else:
            for slot,line in enumerate(lines):
                if self._halted():break
                results[slot]=self._run_command(node_id,line,shell,deadline)
                if results[slot]["exit_code"]!=0 and cfg.get("stop_on_fail",True):break
        ran=[r for r in results if r is not None]
        env["commands"]=[{"text":r["text"],"exit_code":r["exit_code"],"stdout":_tail(r["stdout"]),"stderr":_tail(r["stderr"]),"job_key":r["job_key"]} for r in ran]
        env["stdout"]="\n".join(r["stdout"].rstrip("\n") for r in ran if r["stdout"])
        env["stderr"]="\n".join(r["stderr"].rstrip("\n") for r in ran if r["stderr"])
        failed=[r for r in ran if r["exit_code"]!=0]
        env["exit_code"]=(failed[0]["exit_code"] if failed[0]["exit_code"] is not None else -1) if failed else 0
        env["parsed"]=None
        output.update({"stdout":_tail(env["stdout"]),"stderr":_tail(env["stderr"]),"exit_code":env["exit_code"],"parsed":None,"commands":[{k:(c[k] if k not in("stdout","stderr") else _tail(c[k],4096)) for k in c} for c in env["commands"]]})
        ok=not failed and len(ran)==len(lines)
        error=""
        if any(r.get("timed_out") for r in ran):error="Timed out after "+str(int(_num(cfg.get("timeout"),300,1,7200)))+" s"
        elif failed:error=(failed[0].get("error") or ("exit code "+str(failed[0]["exit_code"])))
        return {"ok":ok,"branch":"success" if ok else "fail","error":error}
    def _run_command(self,node_id,line,shell,deadline):
        """One command line through the terminal job system: job row, audit entry, process (tree-killable), captured output."""
        term=_terminal()
        root=self.root
        command=line["text"]
        job_key="f"+uuid.uuid4().hex[:11]
        result={"text":command,"exit_code":None,"stdout":"","stderr":"","job_key":job_key,"timed_out":False,"error":""}
        try:
            term._chain_insert(root.run_id,self._next_pos(),{"job_key":job_key,"label":line.get("label") or "","command":command},shell,self.job_source,root.name)
            term.audit_command(command,self.job_source,"chain:"+shell)
            term._chain_begin_step(job_key)
        except Exception as exc:
            # No job row, no run: an unrecorded command is never executed (this is what a lock in mid-run looks like).
            result["error"]="Could not record the command: "+str(exc)[:200]
            return result
        with self._lock:
            self._node_rec(node_id)["job_keys"].append(job_key)
            self._touch(self._node_rec(node_id))
        self._event(node_id,"info","$ "+command[:500])
        self.root._counts["commands"]+=1
        began=time.monotonic()
        self._note("command",node_id,command,{"job_key":job_key,"shell":shell,"label":line.get("label") or ""})
        try:
            proc=subprocess.Popen(term._one_shot_command(shell,command),stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0) if _IS_WINDOWS else 0,start_new_session=not _IS_WINDOWS)
        except Exception as exc:
            result["error"]=str(exc)[:300]
            result["stderr"]=str(exc)
            self._note_exit(node_id,"fail","Could not start: "+str(exc)[:300],False,{"job_key":job_key,"exit_code":None})
            self._job_done(term,job_key,str(exc),None,"failed")
            return result
        with term._batch_lock:term._batch_procs[job_key]=proc
        out_chunks=[];err_chunks=[]
        readers=[threading.Thread(target=_drain,args=(proc.stdout,out_chunks),daemon=True),threading.Thread(target=_drain,args=(proc.stderr,err_chunks),daemon=True)]
        for reader in readers:reader.start()
        killed=False
        try:
            while proc.poll() is None:
                if self._halt_evt.wait(0.05) or self._check_limits():
                    killed=True
                elif time.monotonic()>deadline:
                    killed=True
                    result["timed_out"]=True
                if killed:
                    try:
                        if not common_db.is_locked():term.cancel_batch_job(job_key)  # marks the job row killed; skipped behind the lock (no DB access)
                    except Exception:pass
                    kill_tree(proc)
                    break
            try:proc.wait(timeout=5)
            except Exception:pass
            for reader in readers:reader.join(timeout=3)
        finally:
            with term._batch_lock:term._batch_procs.pop(job_key,None)
        result["stdout"]=b"".join(out_chunks).decode("utf-8",errors="replace")
        result["stderr"]=b"".join(err_chunks).decode("utf-8",errors="replace")
        result["exit_code"]=None if killed else proc.returncode
        if result["timed_out"]:result["error"]="timed out"
        elif killed:result["error"]="stopped"
        text=result["stdout"]+(("\n[stderr]\n"+result["stderr"]) if result["stderr"] else "")
        self._job_done(term,job_key,text,proc.returncode,"killed" if killed else "")
        self._note_exit(node_id,"fail",("Timed out" if result["timed_out"] else "Stopped" if killed else "Exit code "+str(proc.returncode)),result["exit_code"]==0,{"job_key":job_key,"exit_code":result["exit_code"],"timed_out":result["timed_out"],"killed":killed,"duration_ms":int((time.monotonic()-began)*1000),"stdout_bytes":len(result["stdout"]),"stderr_bytes":len(result["stderr"])},result["stderr"],result["stdout"])
        return result
    @staticmethod
    def _job_done(term,job_key,text,exit_code,state):
        # Behind the lock nothing is written: no output spill file, no job row (it is reaped as orphaned on the next start).
        if common_db.is_locked():return
        try:
            term._batch_store_output(job_key,text)
            term.finish_job(job_key,exit_code,"",len(text),state)
        except Exception:
            pass
    def _node_script(self,node,last,env,output):
        cfg=node.get("config") or {}
        node_id=node["id"]
        language=str(cfg.get("language") or "python")
        code=str(cfg.get("code") or "")
        branches=[str(b) for b in (cfg.get("branches") or []) if str(b)] or ["out"]
        timeout=min(_num(cfg.get("timeout"),60,1,7200),max(1.0,self._remaining()))
        payload={"input":last or {},"vars":self.vars,"target":self.target_values,"item":self.item,"index":self.index,"node":node_id,"run_id":self.root.run_id}
        # Defence in depth: flow_service already refuses such a run; a sub-chain or a changed policy is caught here.
        if self.script_sandboxed and sandbox_info().get("sandbox")=="none":raise ValueError(SCRIPTS_NEED_SANDBOX)
        try:_terminal().audit_command("[script:"+language+"] "+str(node.get("title") or node_id)+" ("+str(len(code.splitlines()))+" lines)",self.job_source,"flow:"+self.root.run_id)
        except Exception:pass
        self.root._counts["scripts"]+=1
        self._event(node_id,"info","Running "+language+" script","script",{"language":language,"lines":len(code.splitlines()),"network_requested":cfg.get("network") is True,"sandbox_required":self.script_sandboxed,"timeout":timeout})
        result=_scripts().run_script(language,code,payload,timeout=timeout,cancel_event=self._halt_evt,branches=branches,network=cfg.get("network") is True)
        headline="Timed out" if result.get("timed_out") else "Stopped" if result.get("cancelled") else ("Exit code "+str(result.get("exit_code"))) if result.get("exit_code") is not None else (str(result.get("error") or "The script could not be started")[:300])
        self._note_exit(node_id,"error",headline,bool(result.get("ok")),{"exit_code":result.get("exit_code"),"timed_out":bool(result.get("timed_out")),"killed":bool(result.get("cancelled")),"duration_ms":result.get("duration_ms"),"sandbox":result.get("sandbox") or "none","network":result.get("network"),"truncated":bool(result.get("truncated")),"error":str(result.get("error") or "")[:300]},str(result.get("stderr") or ""),str(result.get("stdout") or ""))
        env["stdout"]=str(result.get("stdout") or "")
        env["stderr"]=str(result.get("stderr") or "")
        env["exit_code"]=result.get("exit_code")
        answer=result.get("result") if isinstance(result.get("result"),dict) else {}
        env["parsed"]=answer.get("output")
        output.update({"stdout":_tail(env["stdout"]),"stderr":_tail(env["stderr"]),"exit_code":env["exit_code"],"parsed":env["parsed"],"sandbox":result.get("sandbox") or "none","network":result.get("network")})
        if not result.get("ok"):
            reason="timed out" if result.get("timed_out") else "stopped" if result.get("cancelled") else (result.get("error") or ("exit code "+str(result.get("exit_code"))))
            return {"ok":False,"branch":"error","error":str(reason)[:300]}
        found=answer.get("vars") if isinstance(answer.get("vars"),dict) else {}
        self.vars.update(found)
        self.trusted.difference_update(found)
        output["vars_set"]=found
        branch=str(answer.get("branch") or "")
        if branch not in branches:
            if branch:self._event(node_id,"warn","The script chose branch '"+branch+"', which this node does not have; using '"+branches[0]+"'")
            branch=branches[0]
        return {"branch":branch}
    def _node_subchain(self,node,last,env,output):
        cfg=node.get("config") or {}
        try:child_id=int(cfg.get("playbook_id"))
        except (TypeError,ValueError):raise ValueError("Pick the chain this node should run")
        if self.depth+1>MAX_DEPTH:raise ValueError("Sub-chains are nested too deep (limit "+str(MAX_DEPTH)+")")
        run=self
        while run is not None:
            if run.playbook_id is not None and int(run.playbook_id)==child_id:raise ValueError("A chain cannot run itself as a sub-chain")
            run=run.parent
        if self.loader is None:raise ValueError("Sub-chains are not available here")
        loaded=self.loader(child_id)
        if not loaded:raise ValueError("Sub-chain "+str(child_id)+" does not exist")
        child=FlowRun(loaded["graph"],child_id,loaded.get("name") or "",self.mode,self.source,loader=self.loader,parent=self,variables=self.vars if cfg.get("pass_vars",True) else {},script_mode=str(loaded.get("script_mode") or "allow"))
        child._parent_node=node["id"]
        if cfg.get("pass_vars",True):child.trusted=set(self.trusted)
        with self._lock:self._child=child
        if self._halted():child._request_halt(*(self._final or ("cancelled","stopped")))
        try:
            state=child.execute()
        finally:
            with self._lock:self._child=None
        child_status=child.status()
        final=child.envs.get(next(reversed(child.envs),None)) if child.envs else None
        if final:
            env["stdout"],env["stderr"],env["exit_code"]=final.get("stdout") or "",final.get("stderr") or "",final.get("exit_code")
        env["parsed"]={"state":state,"vars":copy.deepcopy(child.vars)}
        output.update({"stdout":_tail(env["stdout"]),"stderr":_tail(env["stderr"]),"exit_code":env["exit_code"],"parsed":{"state":state},"sub_run":{"run_id":child.run_id,"playbook_id":child_id,"name":child.name,"state":state,"reason":child_status.get("reason") or "","nodes":{k:{"state":v["state"],"branch":v["branch"],"error":v["error"]} for k,v in child_status["nodes"].items()}}})
        with self._lock:
            rec=self._node_rec(node["id"])
            for child_rec in child_status["nodes"].values():rec["job_keys"].extend(child_rec.get("job_keys") or [])
        ok=state=="done"
        return {"ok":ok,"branch":"success" if ok else "fail","error":"" if ok else ("Sub-chain "+state+((": "+child_status.get("reason")) if child_status.get("reason") else ""))}
    def _node_output(self,node,last,env,output):
        rules=_rules()
        cfg=node.get("config") or {}
        scope=self._scope(last)
        def text_of(key,default=""):
            # {Placeholders} from the live target first, then ${...} flow values - the same order as a command line, but
            # as plain text (no shell quoting). A placeholder without a value stays as written.
            value,_missing,_warn=resolve_command(str(cfg.get(key) if cfg.get(key) is not None else default),self.replacer,scope,None,raw_ok=lambda name:True)
            return str(value)
        action=str(cfg.get("action") or "notify")
        content=text_of("content")
        title=text_of("title").strip() or str(node.get("title") or self.root.name or "Chain output")
        cfg=dict(cfg,note_name=text_of("note_name").strip())
        done=write_output(action,title,content,cfg,{"chain":self.root.name,"run_id":self.root.run_id,"target":self.target_name,"last":last or {}})
        output["result"]=done
        if action=="notify":
            root=self.root
            with root._lock:
                root.data["notices"].append({"ts":_now(),"node":node["id"],"title":title[:200],"text":content[:1000]})
                del root.data["notices"][:-50]
        self._event(node["id"],"info","Output: "+str(done.get("text") or action))
        return {"branch":"out"}
def result_port_for_continue(node,branch):
    """Where a failed node with no fail edge goes on when on_error is "continue": through its plain way out, if it has one."""
    node_type=node.get("type")
    if node_type in ("output","set","wait","start"):return "out"
    if node_type=="decision":return str((node.get("config") or {}).get("else") or "else")
    if node_type=="parse":return "nomatch"
    return _nodes().continue_port(node) or ""
def _limit(name,default):
    try:return int(_schema().LIMITS.get(name,default))
    except Exception:return default
# ---- output node actions -------------------------------------------------------------------------------------------
def _as_html(title,content):
    return "<p><strong>"+html.escape(title)+"</strong></p><pre>"+html.escape(content)+"</pre>"
def write_output(action,title,content,cfg,context):
    """Deliver an output node's text through the existing services. -> {"action","text",...ids}. Raises ValueError."""
    if action=="note_append":
        from Cores.Bridge import api as _api
        from Cores.Services import notes_service
        name=str(cfg.get("note_name") or "").strip() or ("Chain output - "+str(context.get("chain") or "chain"))
        if not content.strip():raise ValueError("Nothing to write to the note")
        notes=notes_service._load_notes(notes_service._db_path())
        found=next((n for n in notes if str(n.get("note_name") or "").strip().lower()==name.lower()),None)
        body=_as_html(title,content)
        notes_api=_api.NotesAPI()
        if found:saved=notes_api.append(found["id"],body)
        else:saved=notes_api.save(None,name,"",body,[],"")
        return {"action":action,"note_id":saved.get("id"),"text":("Appended to" if found else "Created")+" note '"+name+"'"}
    if action=="finding_draft":
        from Cores.Services import reports_service
        report_id=cfg.get("report_id")
        if report_id in (None,""):
            reports=reports_service.list_reports()
            if not reports:raise ValueError("There is no report to add the finding to. Create a report or pick one in the node.")
            report_id=reports[0]["id"]
        severity=str(cfg.get("severity") or "info").lower()
        if severity not in reports_service.SEVERITIES:severity="info"
        finding=reports_service.add_finding(report_id,{"title":title[:200],"severity":severity,"description":"<pre>"+html.escape(content)+"</pre>","tags":["chain-draft"]})
        return {"action":action,"finding_id":finding.get("id"),"report_id":report_id,"text":"Finding draft '"+title[:80]+"' added to report "+str(report_id)}
    if action=="evidence":
        from Cores.Services import evidence_service
        last=context.get("last") or {}
        commands=last.get("commands") or []
        saved=evidence_service.save_text({"title":title[:200],"content":content,"command":str(commands[-1].get("text") or "") if commands else "","exit_code":last.get("exit_code"),"source":"chain","tags":["chain"],"notes":"Chain '"+str(context.get("chain") or "")+"', run "+str(context.get("run_id") or "")})
        return {"action":action,"evidence_id":(saved or {}).get("id"),"text":"Evidence '"+title[:80]+"' saved"}
    if action=="notify":
        sent=False
        try:
            from Cores.Services import settings_service
            from Cores import os_toast
            if settings_service.get_notification_settings().get("os_enabled"):sent=bool(os_toast.send(title[:120],content[:300]))
        except Exception:
            sent=False
        return {"action":action,"os_toast":sent,"text":"Notification: "+title[:80]+((" - "+content[:200]) if content else "")}
    raise ValueError("Unknown output action '"+action+"'")
# ---- registry ------------------------------------------------------------------------------------------------------
_runs={}
_runs_lock=threading.Lock()
_unsaved=[]
_unsaved_logs=[]   # [(run_id,[entries])] batches that could not be written (app locked / DB busy)
def _persist(run):
    """Final snapshot -> ChainRuns. A locked or busy DB keeps it in memory; flush_pending() retries later."""
    snapshot=run.status()
    with _runs_lock:_unsaved.append(snapshot)
    flush_pending()
def flush_pending():
    """Write the run snapshots that could not be stored yet. Returns how many are still waiting."""
    from Cores.Services import flow_store
    with _runs_lock:waiting=list(_unsaved)
    if common_db.db_locked():return len(waiting)  # behind the lock the snapshots stay in memory; no DB file is touched
    for snapshot in waiting:
        try:
            flow_store.save_run(snapshot)
        except Exception:
            break
        with _runs_lock:
            if snapshot in _unsaved:_unsaved.remove(snapshot)
    with _runs_lock:batches=list(_unsaved_logs)
    for batch in batches:
        try:
            flow_store.append_run_log(batch[0],batch[1])
        except Exception:
            break
        with _runs_lock:
            if batch in _unsaved_logs:_unsaved_logs.remove(batch)
    with _runs_lock:return len(_unsaved)
def pending_log(run_id):
    """Log entries of a finished run that are still waiting to be written."""
    with _runs_lock:return [entry for key,entries in _unsaved_logs if key==str(run_id) for entry in entries]
def pending_snapshots():
    with _runs_lock:return list(_unsaved)
def start_run(graph,**kw):
    """Create, register and start a run. kw: playbook_id, name, mode, source, from_node, seed, loader."""
    with _runs_lock:
        if sum(1 for r in _runs.values() if r.active())>=MAX_ACTIVE_RUNS:raise ValueError("Too many chains are running. Stop one first.")
    run=FlowRun(graph,on_finish=_persist,**kw)
    with _runs_lock:
        _runs[run.run_id]=run
        finished=[key for key,r in _runs.items() if not r.active()]
        for key in finished[:max(0,len(finished)-KEEP_FINISHED)]:_runs.pop(key,None)
    return run.start()
def get_run(run_id):
    with _runs_lock:return _runs.get(str(run_id or ""))
def active_runs():
    with _runs_lock:runs=[r for r in _runs.values() if r.active()]
    return [r.summary() for r in runs]
def forget_run(run_id):
    with _runs_lock:
        run=_runs.get(str(run_id or ""))
        if run is not None and not run.active():_runs.pop(str(run_id),None)
        _unsaved[:]=[s for s in _unsaved if s.get("run_id")!=str(run_id)]
        _unsaved_logs[:]=[b for b in _unsaved_logs if b[0]!=str(run_id)]
def _stop_at_exit():
    # Commands run in their own session, so they would outlive the app: stop every run when the interpreter exits.
    try:
        with _runs_lock:runs=[r for r in _runs.values() if r.active()]
        for run in runs:run.stop("the app closed")
        for run in runs:run.finished.wait(4)
    except Exception:
        pass
atexit.register(_stop_at_exit)
def stop_all(reason="stopped"):
    """Stop every active run (app exit, lock). Returns how many were told to stop."""
    with _runs_lock:runs=[r for r in _runs.values() if r.active()]
    for run in runs:run.stop(reason)
    return len(runs)
