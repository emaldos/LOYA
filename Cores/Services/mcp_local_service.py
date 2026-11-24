import asyncio,hmac,json,os,secrets,socket,threading,time,urllib.request,urllib.error
from urllib.parse import urlsplit
from Cores.Services import ai_service as _ai_svc
DEFAULT_PORT=8765
_lock=threading.Lock()
_server=None
_thread=None
_port=None
# Access control (S30): the server binds 127.0.0.1 only, and every HTTP request must also carry
#   Authorization: Bearer <token>   - a random token made each time the server starts, compared in constant time
#   Host: 127.0.0.1|localhost|[::1] - anything else is refused (DNS rebinding: a web page that resolves its own name to 127.0.0.1)
#   Origin (when a browser sends one) on localhost too
# and nothing is served while the app is locked. The main token is for an MCP client the operator connects on purpose
# (shown masked in Settings). LOYA's own agent processes get their own per-run tokens via issue_client_token(), so the
# audit log and the approval prompts can say which agent made each call.
_tokens_lock=threading.Lock()
_main_token=None
_client_tokens={}
_LOCAL_HOSTS=("127.0.0.1","localhost","::1")
EXTERNAL_CLIENT={"id":"external","label":"External MCP client","provider":"external","session_id":""}
def _new_token():return secrets.token_urlsafe(32)
def _local_url(port):
    return f"http://127.0.0.1:{port}/mcp"
def _http_reachable(port):
    try:
        urllib.request.urlopen(_local_url(port),timeout=1)
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False
def is_running():
    return _server is not None and _thread is not None and _thread.is_alive() and bool(getattr(_server,"started",False))
def status():
    running=is_running()
    return {"running":running,"port":_port if running else None,"url":_local_url(_port) if running else None,"auth":"bearer","token_set":bool(_main_token) and running}
def _mask(tok):
    tok=tok or ""
    return (tok[:4]+"…"+tok[-4:]) if len(tok)>12 else ("*"*len(tok))
def token_info(reveal=False):
    """Masked by default. reveal=True is for the Settings "Copy" button only and is written to the audit log."""
    with _tokens_lock:tok=_main_token if is_running() else None
    if not tok:return {"running":False,"token":"","masked":""}
    out={"running":True,"masked":_mask(tok),"token":""}
    if reveal:
        out["token"]=tok
        try:
            from Cores.Services import security_service as _security
            _security.log_audit_event("mcp_token_copied","the MCP access token was copied from Settings",True)
        except Exception:pass
    return out
def issue_client_token(client):
    """A token for one agent run. client: {"id","label","provider","session_id"}. Revoke it when the run ends."""
    tok=_new_token()
    with _tokens_lock:_client_tokens[tok]=dict(client or {})
    return tok
def revoke_client_token(tok):
    with _tokens_lock:_client_tokens.pop(tok,None)
def revoke_all_client_tokens():
    with _tokens_lock:_client_tokens.clear()
def resolve_token(presented):
    """The client identity for a presented bearer token, or None. Compares against every live token in constant time."""
    if not presented or not isinstance(presented,str):return None
    p=presented.encode("utf-8","replace")
    hit=None
    with _tokens_lock:
        cands=[(_main_token,EXTERNAL_CLIENT)]+list(_client_tokens.items())
    for tok,client in cands:
        if tok and hmac.compare_digest(p,tok.encode("utf-8")) and hit is None:hit=client
    if hit is None:
        for fn in list(_token_resolvers):
            try:c=fn(presented)
            except Exception:c=None
            if c and hit is None:hit=c
    return dict(hit) if hit else None
_token_resolvers=[]
def add_token_resolver(fn):
    """fn(presented) -> client dict or None, for tokens that outlive one server start: the operator's own CLI connected
    under Settings > AI > Agents > Connections (ext_connections_service). Same guard and AI Roles checks as every token."""
    if fn not in _token_resolvers:_token_resolvers.append(fn)
def _host_ok(value):
    if not value:return False
    v=value.strip().lower()
    if v.startswith("["):
        host=v[1:v.find("]")] if "]" in v else v
    else:
        host=v.rsplit(":",1)[0] if v.count(":")==1 else v
    return host in _LOCAL_HOSTS
def _origin_ok(value):
    if value is None:return True
    try:u=urlsplit(value.strip())
    except Exception:return False
    return u.scheme in ("http","https") and (u.hostname or "") in _LOCAL_HOSTS
def check_request(headers,locked=False):
    """headers: dict of lower-case names. Returns (status, message, client). status 200 means let it through."""
    if not _host_ok(headers.get("host","")):return 403,"Host not allowed - the LOYA MCP server only answers on localhost.",None
    if not _origin_ok(headers.get("origin")):return 403,"Origin not allowed.",None
    auth=headers.get("authorization","")
    scheme,_,tok=auth.partition(" ")
    client=resolve_token(tok.strip()) if scheme.lower()=="bearer" else None
    if client is None:return 401,"Missing or wrong bearer token.",None
    if locked:return 423,"LOYA NG is locked. Unlock the app before using its tools.",None
    return 200,"",client
_CLIENT_HEADER=b"x-loya-client"
class AuthGuard:
    """ASGI middleware in front of the MCP app. Strips any client-sent x-loya-client header and sets it from the token."""
    def __init__(self,app,locked=None):
        self.app=app
        self._locked=locked or _db_locked
    async def __call__(self,scope,receive,send):
        if scope.get("type")!="http":
            return await self.app(scope,receive,send)
        raw=[(k,v) for k,v in scope.get("headers") or [] if k.lower()!=_CLIENT_HEADER]
        headers={}
        for k,v in raw:headers.setdefault(k.decode("latin-1").lower(),v.decode("latin-1"))
        code,msg,client=check_request(headers,self._locked())
        if code!=200:
            body=json.dumps({"error":msg}).encode("utf-8")
            hdrs=[(b"content-type",b"application/json"),(b"content-length",str(len(body)).encode())]
            if code==401:hdrs.append((b"www-authenticate",b'Bearer realm="loya-mcp"'))
            await send({"type":"http.response.start","status":code,"headers":hdrs})
            await send({"type":"http.response.body","body":body})
            return
        raw.append((_CLIENT_HEADER,json.dumps(client).encode("utf-8")))
        scope=dict(scope,headers=raw)
        return await self.app(scope,receive,send)
def _db_locked():
    try:
        from Cores import common_db as _common_db
        return _common_db.db_locked()
    except Exception:
        return False
_redact_hook=None
def set_redact_hook(fn):
    """fn(client) -> True when tool results for that client must pass through the secret redactor (External Agents setting)."""
    global _redact_hook
    _redact_hook=fn
def _wants_redaction(client):
    if not client:return False
    try:return bool(_redact_hook(client)) if _redact_hook else True
    except Exception:return True
def install_client_context(server):
    """Wrap server.call_tool so the tool (and the worker thread it runs on) knows which client called it, and so results
    sent to external agents pass through the secret redactor."""
    orig=server.call_tool
    async def call_tool(name,arguments,context=None,*a,**k):
        client=None
        try:
            hdrs=context.headers if context is not None else None
            raw=hdrs.get("x-loya-client") if hdrs else None
            client=json.loads(raw) if raw else None
        except Exception:
            client=None
        tok=_ai_svc.set_client(client)
        try:
            result=await orig(name,arguments,context,*a,**k)
        finally:
            _ai_svc.reset_client(tok)
        if client and _wants_redaction(client):
            try:
                from Cores.Services import ext_agents_service as _ext
                result=_ext.redact_tool_result(result)
            except Exception:pass
        return result
    server.call_tool=call_tool
    return server
def _expected_errors():
    from Cores import common_db as _common_db
    # KeyError/IndexError are left masked: their text is usually an internal detail, not a message meant for the agent.
    return (ValueError,PermissionError,TimeoutError,_common_db.DatabaseLocked)
# Live-target secret values ({Password}, {NTLM Hash}...) must not reach an AI through any tool result: a command resolved with the
# live target, a queued request's status, a chain's step list or its output tail would otherwise carry them in clear. Only
# targets_secret_values (its own AI Roles key, Deny by default) returns them on purpose.
_SECRET_TOOLS=frozenset(("targets_secret_values",))
_SECRET_MIN_LEN=4
def live_secret_values():
    try:
        from Cores.Services import search_service as _search_svc
        from Cores.Bridge import mcp_app_tools as _app_tools
        mp=getattr(_search_svc.LiveTargetContext(),"map",{}) or {}
        vals={str(v).strip() for k,v in mp.items() if _app_tools.is_secret_key(k) and len(str(v or "").strip())>=_SECRET_MIN_LEN}
        return sorted(vals,key=len,reverse=True)
    except Exception:
        return []
def _secret_mask():
    try:
        from Cores.Bridge import mcp_app_tools as _app_tools
        return _app_tools.MASK
    except Exception:return "[hidden]"
def mask_live_secrets(obj,values=None):
    values=live_secret_values() if values is None else values
    if not values:return obj
    mask=_secret_mask()
    def walk(v):
        if isinstance(v,str):
            for s in values:
                if s in v:v=v.replace(s,mask)
            return v
        if isinstance(v,list):return [walk(x) for x in v]
        if isinstance(v,tuple):return tuple(walk(x) for x in v)
        if isinstance(v,dict):return {k:walk(x) for k,x in v.items()}
        return v
    return walk(obj)
def _mask_result(result,values):
    try:
        content=[]
        for c in getattr(result,"content",None) or []:
            if getattr(c,"type","")=="text" and isinstance(getattr(c,"text",None),str):content.append(c.model_copy(update={"text":mask_live_secrets(c.text,values)}))
            else:content.append(c)
        upd={"content":content}
        sc=getattr(result,"structured_content",None)
        if sc is not None:upd["structured_content"]=mask_live_secrets(sc,values)
        return result.model_copy(update=upd)
    except Exception:
        return result
def passthrough_expected_errors(server):
    """mcp >= 2.2 shows the model only "Error executing tool <name>" for anything that is not a ToolError. LOYA's tools report
    expected refusals (AI Roles denials, the lock, "No such note") as ValueError/PermissionError, and the agent needs that text,
    so those are re-raised as ToolError (through the secret redactor). Real crashes stay masked. A no-op on mcp 2.0."""
    from mcp.server.mcpserver import exceptions as _exc
    unexpected=getattr(_exc,"UnexpectedToolError",None) or type("_NeverRaised",(Exception,),{})
    if getattr(server,"_loya_errors_passthrough",False):return server
    orig=server.call_tool
    expected=_expected_errors()
    async def call_tool(name,arguments,context=None,*a,**k):
        try:
            result=await orig(name,arguments,context,*a,**k)
            if name in _SECRET_TOOLS:return result
            values=live_secret_values()
            return _mask_result(result,values) if values else result
        except unexpected as e:
            cause=e.__cause__
            if not isinstance(cause,expected):raise
            msg=mask_live_secrets(str(cause))
            try:
                from Cores.Services import ext_agents_service as _ext
                msg=_ext.redact_text(msg)
            except Exception:pass
            raise _exc.ToolError(msg) from cause
    server.call_tool=call_tool
    server._loya_errors_passthrough=True
    return server
def build_app(port=None):
    from Cores.Bridge import mcp_server as _mcp_server
    server=install_client_context(passthrough_expected_errors(_mcp_server.build_server()))
    return AuthGuard(server.streamable_http_app(host="127.0.0.1"))
def _build_uvicorn(port):
    import uvicorn
    return uvicorn.Server(uvicorn.Config(build_app(port),host="127.0.0.1",port=port,log_level="warning",lifespan="on"))
_last_error={"text":""}
def _serve(server):
    # uvicorn reports a failed bind with sys.exit(1): caught here, so it ends this thread only, never the app.
    try:asyncio.run(server.serve())
    except BaseException as e:
        _last_error["text"]=f"{type(e).__name__}: {e}" if not isinstance(e,SystemExit) else "the server could not bind its port"
def _port_free(port):
    """True when 127.0.0.1:<port> can be bound now (same SO_REUSEADDR rule uvicorn uses on POSIX)."""
    s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    try:
        if os.name!="nt":s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        s.bind(("127.0.0.1",int(port)))
        return True
    except OSError:
        return False
    finally:
        s.close()
AUTO_PORT_TRIES=20
def _auto_port(skip=()):
    """The default port when it is free, else the next free one, else one the OS picks. Another LOYA NG instance (or any
    other program) on 8765 must not stop this one: connected CLIs read the port from their connection file."""
    for p in range(DEFAULT_PORT,DEFAULT_PORT+AUTO_PORT_TRIES):
        if p not in skip and _port_free(p) and not _http_reachable(p):return p  # Windows lets a 127.0.0.1 bind shadow a 0.0.0.0 listener
    s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1",0))
        return s.getsockname()[1]
    finally:
        s.close()
# Starting is serialized: two callers at once (the CLI autostart thread and a Connect) must share one server, not race
# to start a second one on the same port.
_start_lock=threading.RLock()
def start_server(port=None,register_provider=True):
    """port=None picks a free port (8765 first). An explicit port must be free, or this raises RuntimeError.
    Never raises anything else and never ends the process; a failed start leaves no server behind."""
    with _start_lock:
        if is_running():
            return status()
        explicit=port is not None
        tried=[]
        for attempt in range(1 if explicit else 3):
            p=int(port) if explicit else _auto_port(tried)
            tried.append(p)
            if explicit and (_http_reachable(p) or not _port_free(p)):
                raise RuntimeError(f"Port {p} is already in use - another MCP server (or another app) is listening there.")
            if _try_start(p):
                if register_provider:_ai_svc.set_provider("mcp",{"url":_local_url(p),"enabled":True})
                return status()
        why=_last_error["text"]
        raise RuntimeError(f"Local MCP server did not start on port {tried[-1]}"+(f" ({why})." if why else "."))
def _try_start(port):
    global _server,_thread,_port,_main_token
    _last_error["text"]=""
    try:server=_build_uvicorn(port)
    except Exception as e:
        _last_error["text"]=f"{type(e).__name__}: {e}"
        return False
    with _lock:
        with _tokens_lock:_main_token=_new_token()
        thread=threading.Thread(target=_serve,args=(server,),name="loya-mcp-http",daemon=True)
        thread.start()
        _server,_thread,_port=server,thread,port
    for _ in range(40):
        if server.started:return True
        if not thread.is_alive():break
        time.sleep(0.25)
    stop_server()
    return False
def stop_server():
    global _server,_thread,_port,_main_token
    with _lock:
        server,thread,port=_server,_thread,_port
        _server=None;_thread=None;_port=None
    with _tokens_lock:
        _main_token=None
        _client_tokens.clear()
    if server is not None:
        server.should_exit=True
        if thread is not None:thread.join(timeout=5)
    if port is not None:
        cfg=_ai_svc.get_providers()["mcp"]
        if cfg.get("url")==_local_url(port):
            _ai_svc.set_provider("mcp",{"enabled":False})
    return status()
def serve_forever(port=None):
    """Standalone `python -m Cores.Bridge.mcp_server --http`: same guard, token printed once to stderr."""
    global _main_token
    import sys,uvicorn
    port=int(port or DEFAULT_PORT)
    with _tokens_lock:_main_token=_new_token()
    sys.stderr.write(f"LOYA MCP server on {_local_url(port)} - send 'Authorization: Bearer {_main_token}'\n");sys.stderr.flush()
    uvicorn.Server(uvicorn.Config(build_app(port),host="127.0.0.1",port=port,log_level="warning",lifespan="on")).run()
