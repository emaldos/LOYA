import os,json,shutil,threading,time,uuid,contextvars,urllib.request,urllib.error
from Cores import common_db
from Cores.settings_lock import SETTINGS_LOCK as _settings_lock
def _settings_path():return os.path.join(common_db.data_dir(),"settings.json")
def _read_settings():
    try:
        with open(_settings_path(),"r",encoding="utf-8") as f:
            d=json.load(f)
        return d if isinstance(d,dict) else {}
    except Exception:
        return {}
def _write_settings(d):
    p=_settings_path()
    os.makedirs(os.path.dirname(p),exist_ok=True)
    tmp=p+".tmp"
    with open(tmp,"w",encoding="utf-8") as f:json.dump(d,f,ensure_ascii=False,indent=2)
    os.replace(tmp,p)
def _extensions(d):
    ext=d.get("extensions",{})
    return ext if isinstance(ext,dict) else {}
_PANEL_MODES=("left","right","bottom")
def _clamp_int(value,low,high,default):
    try:return max(low,min(high,int(value)))
    except Exception:return default
def get_settings():
    ext=_extensions(_read_settings())
    mode=str(ext.get("ai_panel_mode","") or "").strip().lower()
    return {"enabled":bool(ext.get("ai_enabled",True)),"panel_width":int(ext.get("ai_width",380) or 380),"panel_mode":mode if mode in _PANEL_MODES else "left","panel_height":_clamp_int(ext.get("ai_panel_height",320),160,1200,320)}
def set_enabled(enabled):
    with _settings_lock:
        d=_read_settings()
        ext=_extensions(d)
        ext["ai_enabled"]=bool(enabled)
        d["extensions"]=ext
        _write_settings(d)
    return get_settings()
def set_panel_width(width):
    try:width=max(260,min(900,int(width)))
    except Exception:width=380
    with _settings_lock:
        d=_read_settings()
        ext=_extensions(d)
        ext["ai_width"]=width
        d["extensions"]=ext
        _write_settings(d)
    return get_settings()
def set_panel_layout(values):
    """Where the AI panel docks (left/right/bottom) and its bottom-dock height; width stays in set_panel_width."""
    values=values if isinstance(values,dict) else {}
    with _settings_lock:
        d=_read_settings()
        ext=_extensions(d)
        if "mode" in values:
            mode=str(values.get("mode") or "").strip().lower()
            if mode in _PANEL_MODES:ext["ai_panel_mode"]=mode
        if "width" in values:ext["ai_width"]=_clamp_int(values.get("width"),260,900,380)
        if "height" in values:ext["ai_panel_height"]=_clamp_int(values.get("height"),160,1200,320)
        d["extensions"]=ext
        _write_settings(d)
    return get_settings()
PROVIDER_TYPES=["api","ollama","lmstudio","mcp"]
CHAT_PROVIDER_TYPES=["api","ollama","lmstudio"]
_DEFAULT_PROVIDERS={
    "api":{"enabled":False,"provider_kind":"anthropic","api_key":"","base_url":"","model":""},
    "ollama":{"enabled":False,"host":"127.0.0.1","port":11434,"model":""},
    "lmstudio":{"enabled":False,"host":"127.0.0.1","port":1234,"model":""},
    "mcp":{"enabled":False,"url":""},
}
_DEFAULT_API_BASE_URLS={"anthropic":"https://api.anthropic.com","openai":"https://api.openai.com"}
_STATIC_MODEL_FALLBACKS={
    "anthropic":["claude-opus-5","claude-sonnet-5","claude-fable-5","claude-haiku-4-5-20251001"],
    "openai":["gpt-4o","gpt-4o-mini","gpt-4.1","o3"],
}
PRICING_PER_1K_TOKENS={
    "claude-opus-5":0.020,"claude-sonnet-5":0.006,"claude-fable-5":0.003,"claude-haiku-4-5-20251001":0.002,
    "gpt-4o":0.006,"gpt-4o-mini":0.001,"gpt-4.1":0.005,"o3":0.015,
}
PROVIDER_LABELS={"api":"API","ollama":"Ollama","lmstudio":"LM Studio","mcp":"MCP Server"}
_LMSTUDIO_INSTALL_HINTS=[
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\LM Studio\LM Studio.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\LM-Studio\LM Studio.exe"),
    os.path.expanduser("~/.lmstudio"),
    os.path.expanduser("~/Applications/LM Studio.app"),
    "/Applications/LM Studio.app",
]
def _provider_store(d):
    ext=_extensions(d)
    p=ext.get("ai_providers",{})
    return p if isinstance(p,dict) else {}
def _merged_provider(kind,stored):
    base=dict(_DEFAULT_PROVIDERS[kind])
    if isinstance(stored,dict):
        for k in base:
            if k in stored:base[k]=stored[k]
    return base
def get_providers():
    stored=_provider_store(_read_settings())
    return {k:_merged_provider(k,stored.get(k)) for k in PROVIDER_TYPES}
def _mask_key(key):
    key=key or ""
    if len(key)<=8:return "*"*len(key)
    return key[:4]+"…"+key[-4:]
def get_providers_masked():
    out={}
    for kind,cfg in get_providers().items():
        c=dict(cfg)
        if "api_key" in c:
            c["api_key_set"]=bool(c["api_key"])
            c["api_key_masked"]=_mask_key(c["api_key"])
            del c["api_key"]
        out[kind]=c
    return out
def set_provider(kind,cfg):
    if kind not in PROVIDER_TYPES:raise ValueError(f"Unknown provider type: {kind}")
    if not isinstance(cfg,dict):raise ValueError("cfg must be an object")
    with _settings_lock:
        d=_read_settings()
        ext=_extensions(d)
        providers=ext.get("ai_providers",{})
        if not isinstance(providers,dict):providers={}
        current=_merged_provider(kind,providers.get(kind))
        for key in current:
            if key in cfg:current[key]=cfg[key]
        current["enabled"]=bool(current.get("enabled",False))
        providers[kind]=current
        ext["ai_providers"]=providers
        if not current["enabled"] and ext.get("ai_default_provider")==kind:ext["ai_default_provider"]=None
        d["extensions"]=ext
        _write_settings(d)
    return get_providers_masked()[kind]
def enabled_providers():
    providers=get_providers()
    return [{"kind":k,"label":PROVIDER_LABELS[k]} for k in CHAT_PROVIDER_TYPES if providers[k]["enabled"]]
def get_default_provider():
    ext=_extensions(_read_settings())
    kind=ext.get("ai_default_provider")
    return kind if kind in CHAT_PROVIDER_TYPES else None
def set_default_provider(kind):
    if kind=="mcp":raise ValueError("An MCP server only provides tools, it cannot answer chat messages. Pick API, Ollama or LM Studio as the default.")
    if kind is not None and kind not in PROVIDER_TYPES:raise ValueError(f"Unknown provider type: {kind}")
    with _settings_lock:
        d=_read_settings()
        ext=_extensions(d)
        stored=ext.get("ai_providers",{})
        if not isinstance(stored,dict):stored={}
        if kind is not None and not _merged_provider(kind,stored.get(kind))["enabled"]:raise ValueError("Provider must be enabled to be set as default.")
        ext["ai_default_provider"]=kind
        d["extensions"]=ext
        _write_settings(d)
    return get_default_provider()
def _classify_error(e):
    import socket
    if isinstance(e,urllib.error.HTTPError):
        return "auth_failed" if e.code in (401,403) else "http_error"
    if isinstance(e,urllib.error.URLError):
        reason=getattr(e,"reason",None)
        if isinstance(reason,socket.timeout):return "timeout"
        if isinstance(reason,ConnectionRefusedError) or "refused" in str(reason).lower():return "connection_refused"
        return "unreachable"
    if isinstance(e,socket.timeout):return "timeout"
    return "unknown"
def _http_get_json(url,headers=None,timeout=3):
    req=urllib.request.Request(url,headers=headers or {})
    with urllib.request.urlopen(req,timeout=timeout) as resp:
        raw=resp.read()
    try:return json.loads(raw.decode("utf-8","replace"))
    except Exception:return {}
def test_ollama(host=None,port=None):
    cfg=get_providers()["ollama"]
    host=host or cfg["host"];port=port or cfg["port"]
    try:
        data=_http_get_json(f"http://{host}:{port}/api/tags")
        models=[m.get("name","") for m in (data.get("models") or []) if isinstance(m,dict)]
        return {"status":"online","models":models}
    except Exception as e:
        return {"status":"offline","error":str(e),"reason":_classify_error(e)}
def status_ollama():
    r=test_ollama()
    if r["status"]=="online":return r
    if shutil.which("ollama"):return r
    return {"status":"not_installed"}
OLLAMA_SUGGESTED_MODELS=[
    {"name":"qwen3-coder:480b-cloud","cloud":True},
    {"name":"gpt-oss:120b-cloud","cloud":True},
    {"name":"gpt-oss:20b-cloud","cloud":True},
    {"name":"deepseek-v3.1:671b-cloud","cloud":True},
    {"name":"llama3.2","cloud":False},
    {"name":"qwen2.5:1.5b","cloud":False},
    {"name":"gemma2:9b","cloud":False},
    {"name":"mistral","cloud":False},
]
def suggested_ollama_models():
    return OLLAMA_SUGGESTED_MODELS
_pulls={}
_pulls_lock=threading.Lock()
def start_pull_ollama_model(model_name,host=None,port=None):
    cfg=get_providers()["ollama"]
    host=host or cfg["host"];port=port or cfg["port"]
    model_name=(model_name or "").strip()
    if not model_name:raise ValueError("Model name is required.")
    pull_id=uuid.uuid4().hex[:16]
    buf={"status":"starting","total":0,"completed":0,"done":False,"error":None}
    with _pulls_lock:_pulls[pull_id]=buf
    def run():
        try:
            url=f"http://{host}:{port}/api/pull"
            body=json.dumps({"model":model_name,"stream":True}).encode("utf-8")
            req=urllib.request.Request(url,data=body,headers={"Content-Type":"application/json"},method="POST")
            with urllib.request.urlopen(req,timeout=3600) as resp:
                for raw_line in resp:
                    line=raw_line.decode("utf-8","replace").strip()
                    if not line:continue
                    try:evt=json.loads(line)
                    except Exception:continue
                    if not isinstance(evt,dict):continue
                    with _pulls_lock:
                        if evt.get("error"):
                            buf["error"]=str(evt["error"])
                            buf["done"]=True
                        if evt.get("status"):buf["status"]=evt["status"]
                        if "total" in evt:buf["total"]=evt["total"]
                        if "completed" in evt:buf["completed"]=evt["completed"]
                    if buf["done"]:break
            with _pulls_lock:
                buf["done"]=True
        except urllib.error.HTTPError as e:
            with _pulls_lock:
                buf["error"]=f"HTTP {e.code}: model not found or Ollama rejected the request."
                buf["done"]=True
        except Exception as e:
            with _pulls_lock:
                buf["error"]=str(e)
                buf["done"]=True
    threading.Thread(target=run,daemon=True).start()
    return pull_id
def poll_pull_ollama_model(pull_id):
    with _pulls_lock:
        buf=_pulls.get(pull_id)
        if buf is None:return {"status":"","total":0,"completed":0,"done":True,"error":"Unknown or already-finished pull."}
        out=dict(buf)
        if buf["done"]:del _pulls[pull_id]
        return out
def test_lmstudio(host=None,port=None):
    cfg=get_providers()["lmstudio"]
    host=host or cfg["host"];port=port or cfg["port"]
    try:
        data=_http_get_json(f"http://{host}:{port}/v1/models")
        models=[m.get("id","") for m in (data.get("data") or []) if isinstance(m,dict)]
        return {"status":"online","models":models}
    except Exception as e:
        return {"status":"offline","error":str(e),"reason":_classify_error(e)}
def status_lmstudio():
    r=test_lmstudio()
    if r["status"]=="online":return r
    if any(os.path.exists(p) for p in _LMSTUDIO_INSTALL_HINTS):return r
    return {"status":"not_installed"}
def test_api(provider_kind=None,api_key=None,base_url=None):
    cfg=get_providers()["api"]
    provider_kind=provider_kind or cfg["provider_kind"]
    api_key=api_key if api_key is not None else cfg["api_key"]
    base_url=base_url or cfg["base_url"] or _DEFAULT_API_BASE_URLS.get(provider_kind,"")
    if not api_key:return {"status":"offline","error":"No API key configured.","reason":"not_configured"}
    if not base_url:return {"status":"offline","error":"No base URL configured.","reason":"not_configured"}
    headers={"x-api-key":api_key,"anthropic-version":"2023-06-01"} if provider_kind=="anthropic" else {"Authorization":f"Bearer {api_key}"}
    try:
        data=_http_get_json(base_url.rstrip("/")+"/v1/models",headers=headers)
        models=[m.get("id",m.get("name","")) for m in (data.get("data") or []) if isinstance(m,dict)]
        return {"status":"online","models":models}
    except urllib.error.HTTPError as e:
        if e.code in (401,403):return {"status":"offline","error":"Authentication failed.","reason":"auth_failed"}
        return {"status":"offline","error":f"HTTP {e.code}","reason":"http_error"}
    except Exception as e:
        return {"status":"offline","error":str(e),"reason":_classify_error(e)}
def status_api():
    cfg=get_providers()["api"]
    if not cfg["api_key"]:return {"status":"offline","error":"No API key configured."}
    return test_api()
def test_mcp(url=None):
    cfg=get_providers()["mcp"]
    url=url or cfg["url"]
    if not url:return {"status":"offline","error":"No MCP server URL configured.","reason":"not_configured"}
    try:
        with urllib.request.urlopen(urllib.request.Request(url),timeout=3) as resp:
            return {"status":"online","http_status":resp.status}
    except urllib.error.HTTPError as e:
        return {"status":"online","http_status":e.code}
    except Exception as e:
        return {"status":"offline","error":str(e),"reason":_classify_error(e)}
def status_mcp():
    cfg=get_providers()["mcp"]
    if not cfg["url"]:return {"status":"not_installed","error":"No MCP server URL configured."}
    return test_mcp()
def detect_all():
    return {"api":status_api(),"ollama":status_ollama(),"lmstudio":status_lmstudio(),"mcp":status_mcp()}
def list_models(provider_kind):
    if provider_kind not in PROVIDER_TYPES:raise ValueError(f"Unknown provider type: {provider_kind}")
    if provider_kind=="ollama":
        models=test_ollama().get("models") or []
    elif provider_kind=="lmstudio":
        models=test_lmstudio().get("models") or []
    elif provider_kind=="api":
        cfg=get_providers()["api"]
        models=test_api().get("models") or []
        if not models:models=_STATIC_MODEL_FALLBACKS.get(cfg["provider_kind"],[])
    else:
        models=[]
    return [{"id":m,"label":m} for m in models if m]
LEVELS=("allow","ask","deny")
_LEVEL_RANK={"deny":0,"ask":1,"allow":2}
ACTION_ORDER=["Read","Secrets","Add","Edit","Restore","Run","Kill","Delete"]
PERMISSION_TOOL_MAP={}
PERMISSION_LABELS={}
_DELETE_PERMISSION_KEYS=set()
_SHELL_PERMISSION_KEYS=set()
# Sensitive reads (unmasked target secrets, the audit log): Deny by default and in every preset except Full, where they Ask.
_SENSITIVE_PERMISSION_KEYS=set()
_DEFAULT_LEVELS={}
_ENTITY_ACTIONS={}
def register_permission(key,entity,action,tools,shell=False,delete=None,default=None,sensitive=False):
    """Add one AI permission. Every MCP tool must be listed under exactly one key - unlisted tools are denied."""
    PERMISSION_TOOL_MAP[key]=list(tools)
    PERMISSION_LABELS[key]=(entity,action)
    is_delete=(action=="Delete") if delete is None else bool(delete)
    if is_delete:_DELETE_PERMISSION_KEYS.add(key)
    else:_DELETE_PERMISSION_KEYS.discard(key)
    if shell:_SHELL_PERMISSION_KEYS.add(key)
    else:_SHELL_PERMISSION_KEYS.discard(key)
    if sensitive:_SENSITIVE_PERMISSION_KEYS.add(key);default="deny"
    else:_SENSITIVE_PERMISSION_KEYS.discard(key)
    _DEFAULT_LEVELS[key]=default if default in LEVELS else ("deny" if is_delete or shell else "allow")
    _ENTITY_ACTIONS.setdefault(entity,{})[action]=key
for _key,_entity,_action,_tools,_shell in (
    ("notes_read","Notes","Read",["notes_list","notes_get","notes_command_block_html"],False),
    ("notes_add","Notes","Add",["notes_create"],False),
    ("notes_edit","Notes","Edit",["notes_update","notes_append"],False),
    ("notes_delete","Notes","Delete",["notes_delete"],False),
    ("reports_read","Reports","Read",["reports_list","reports_get","findings_list","report_templates_list","findings_library_search","evidence_list","evidence_get","report_export"],False),
    ("reports_add","Reports","Add",["reports_create","report_section_add","findings_add"],False),
    ("reports_edit","Reports","Edit",["reports_update","report_section_update","findings_update"],False),
    ("reports_delete","Reports","Delete",["reports_delete","findings_delete"],False),
    ("commands_read","Commands","Read",["commands_list"],False),
    ("commands_add","Commands","Add",["commands_create"],False),
    ("commands_edit","Commands","Edit",["commands_update"],False),
    ("commands_delete","Commands","Delete",["commands_delete"],False),
    ("targets_read","Targets","Read",["targets_list"],False),
    ("targets_add","Targets","Add",["targets_add"],False),
    ("targets_edit","Targets","Edit",["targets_update"],False),
    ("targets_delete","Targets","Delete",["targets_remove"],False),
    ("parameter_read","Parameter","Read",["parameter_list","parameter_match"],False),
    ("parameter_add","Parameter","Add",["parameter_add"],False),
    ("parameter_edit","Parameter","Edit",["parameter_update"],False),
    ("parameter_delete","Parameter","Delete",["parameter_remove"],False),
    ("templates_read","Templates","Read",["ai_prompt_template"],False),
    ("quickrun_read","Quick Run","Read",["quickrun_list"],False),
    ("quickrun_run","Quick Run","Run",["quickrun_run"],True),
    ("chains_read","Action Chains","Read",["chains_list","chains_status"],False),
    ("chains_run","Action Chains","Run",["chains_run"],True),
    ("chain_diagrams_read","Chain Diagrams","Read",["chain_get","chain_dry_run","chain_run_status","chain_templates"],False),
    ("chain_diagrams_add","Chain Diagrams","Add",["chain_create"],False),
    ("chain_diagrams_edit","Chain Diagrams","Edit",["chain_update"],False),
    ("chain_diagrams_run","Chain Diagrams","Run",["chain_run","chain_run_stop"],True),
    ("tags_read","Tags","Read",["tags_list"],False),
    ("tags_edit","Tags","Edit",["tags_rename","tags_merge"],False),
    ("tags_delete","Tags","Delete",["tags_delete"],False),
    ("recycle_read","Recycle Bin","Read",["recycle_list"],False),
    ("recycle_restore","Recycle Bin","Restore",["recycle_restore"],False),
    ("recycle_delete","Recycle Bin","Delete",["recycle_purge"],False),
    ("settings_read","Settings","Read",["settings_get"],False),
    ("cve_read","CVE Intel","Read",["cve_lookup"],False),
    ("terminal_read","Terminal","Read",["terminal_list_sessions","terminal_read","terminal_run_status"],True),
    ("terminal_run","Terminal","Run",["terminal_run"],True),
    ("terminal_kill","Terminal","Kill",["terminal_kill"],True),
):register_permission(_key,_entity,_action,_tools,_shell)
TERMINAL_APPROVAL_MODES=("ask","allow")
def _coerce_level(v):
    if isinstance(v,bool):return "allow" if v else "deny"
    v=str(v or "").strip().lower()
    return v if v in LEVELS else None
def _clamp_dependencies(merged):
    for _entity,actions in _ENTITY_ACTIONS.items():
        read_key=actions.get("Read")
        if not read_key:continue
        cap=_LEVEL_RANK[merged.get(read_key,"deny")]
        for act,key in actions.items():
            if act!="Read" and _LEVEL_RANK[merged.get(key,"deny")]>cap:merged[key]=LEVELS[2-cap]
    return merged
def _default_levels():
    return dict(_DEFAULT_LEVELS)
def _merge_levels(stored):
    merged=_default_levels()
    if isinstance(stored,dict):
        for k in merged:
            lvl=_coerce_level(stored.get(k)) if k in stored else None
            if lvl:merged[k]=lvl
    return _clamp_dependencies(merged)
def get_permission_levels():
    return _merge_levels(_extensions(_read_settings()).get("ai_permissions",{}))
def _merge_permissions(stored):
    return {k:v=="allow" for k,v in _merge_levels(stored).items()}
def get_permissions():
    return {k:v=="allow" for k,v in get_permission_levels().items()}
def set_permission_levels(levels):
    if not isinstance(levels,dict):raise ValueError("levels must be an object")
    with _settings_lock:
        d=_read_settings()
        ext=_extensions(d)
        merged=_merge_levels(ext.get("ai_permissions",{}))
        for k,v in levels.items():
            if k not in merged:raise ValueError(f"Unknown permission: {k}")
            lvl=_coerce_level(v)
            if not lvl:raise ValueError(f"Level must be one of: {', '.join(LEVELS)}")
            merged[k]=lvl
        merged=_clamp_dependencies(merged)
        ext["ai_permissions"]=merged
        d["extensions"]=ext
        _write_settings(d)
        return merged
def set_permissions_bulk(keys,enabled):
    lvl=_coerce_level(enabled) or ("allow" if enabled else "deny")
    set_permission_levels({k:lvl for k in keys if k in PERMISSION_TOOL_MAP})
    return get_permissions()
def set_permission(key,enabled):
    if key not in PERMISSION_TOOL_MAP:raise ValueError(f"Unknown permission: {key}")
    return set_permissions_bulk([key],enabled)
def select_all_permissions():
    return set_permissions_bulk([k for k in PERMISSION_TOOL_MAP if k not in _DELETE_PERMISSION_KEYS and k not in _SHELL_PERMISSION_KEYS and k not in _SENSITIVE_PERMISSION_KEYS],True)
def deselect_all_permissions():
    return set_permissions_bulk([k for k in PERMISSION_TOOL_MAP if k not in _DELETE_PERMISSION_KEYS],False)
def assign_all_delete_permissions():
    return set_permissions_bulk(list(_DELETE_PERMISSION_KEYS),True)
def clear_all_delete_permissions():
    return set_permissions_bulk(list(_DELETE_PERMISSION_KEYS),False)
ROLE_PRESETS=[
    {"id":"read_only","label":"Read-only","description":"The AI can look at notes, commands, targets and the rest, but cannot change anything or touch the terminal."},
    {"id":"assistant","label":"Assistant","description":"Reads freely. Every add or edit stops for your approval. No deletes, no shell - reading terminal output asks first."},
    {"id":"full","label":"Full","description":"Reads, adds and edits without asking. Deletes and running or interrupting commands still ask every time."},
]
def preset_levels(preset_id):
    out={}
    for k,(_entity,action) in PERMISSION_LABELS.items():
        shell=k in _SHELL_PERMISSION_KEYS;delete=k in _DELETE_PERMISSION_KEYS;read=action=="Read"
        if k in _SENSITIVE_PERMISSION_KEYS and preset_id in ("read_only","assistant","full"):
            out[k]="ask" if preset_id=="full" else "deny";continue
        if preset_id=="read_only":lvl="allow" if read and not shell else "deny"
        elif preset_id=="assistant":lvl="deny" if delete or (shell and not read) else ("allow" if read and not shell else "ask")
        elif preset_id=="full":lvl="ask" if delete or (shell and not read) else "allow"
        else:raise ValueError(f"Unknown preset: {preset_id}")
        out[k]=lvl
    return _clamp_dependencies(out)
def current_preset():
    levels=get_permission_levels()
    for p in ROLE_PRESETS:
        if preset_levels(p["id"])==levels:return p["id"]
    return "custom"
def apply_preset(preset_id):
    return set_permission_levels(preset_levels(preset_id))
_session_grants=set()
_grants_lock=threading.Lock()
def grant_session(key):
    if key not in PERMISSION_TOOL_MAP:raise ValueError(f"Unknown permission: {key}")
    with _grants_lock:_session_grants.add(key)
    return session_grants()
def revoke_session_grant(key=None):
    with _grants_lock:
        if key is None:_session_grants.clear()
        else:_session_grants.discard(key)
    return session_grants()
def session_grants():
    with _grants_lock:keys=sorted(_session_grants)
    return [{"key":k,"entity":PERMISSION_LABELS[k][0],"action":PERMISSION_LABELS[k][1]} for k in keys if k in PERMISSION_LABELS]
def permission_key(tool_name):
    for key,tools in PERMISSION_TOOL_MAP.items():
        if tool_name in tools:return key
    return None
def tool_decision(tool_name):
    key=permission_key(tool_name)
    if key is None:return "deny"
    lvl=get_permission_levels().get(key,"deny")
    if lvl=="ask":
        with _grants_lock:
            if key in _session_grants:return "allow"
    return lvl
def tool_allowed(tool_name):
    return tool_decision(tool_name)=="allow"
def permission_rows():
    levels=get_permission_levels()
    with _grants_lock:grants=set(_session_grants)
    return [{"key":k,"entity":PERMISSION_LABELS[k][0],"action":PERMISSION_LABELS[k][1],"level":levels[k],"enabled":levels[k]=="allow","session_grant":k in grants and levels[k]=="ask","is_delete":k in _DELETE_PERMISSION_KEYS,"is_shell":k in _SHELL_PERMISSION_KEYS,"is_sensitive":k in _SENSITIVE_PERMISSION_KEYS,"tools":list(PERMISSION_TOOL_MAP[k])} for k in PERMISSION_TOOL_MAP]
def roles_state():
    return {"rows":permission_rows(),"preset":current_preset(),"presets":ROLE_PRESETS,"levels":list(LEVELS),"actions":[a for a in ACTION_ORDER if any(l[1]==a for l in PERMISSION_LABELS.values())],"session_grants":session_grants(),"terminal_approval":terminal_approval_mode()}
def terminal_approval_mode():
    mode=str(_extensions(_read_settings()).get("ai_terminal_approval","") or "").strip().lower()
    return mode if mode in TERMINAL_APPROVAL_MODES else "ask"
def set_terminal_approval_mode(mode):
    mode=str(mode or "").strip().lower()
    if mode not in TERMINAL_APPROVAL_MODES:mode="ask"
    with _settings_lock:
        d=_read_settings()
        ext=_extensions(d)
        ext["ai_terminal_approval"]=mode
        d["extensions"]=ext
        _write_settings(d)
    return mode
# Who is calling the tools right now. Set per MCP request from the caller's bearer token (mcp_local_service), never from a
# client-supplied header, and copied into the worker thread that runs the tool. None means LOYA's own in-app AI.
_CLIENT=contextvars.ContextVar("loya_ai_client",default=None)
_client_reason_hooks=[]
def set_client(client):
    """client: None or {"id","label","provider","session_id"}. Returns a token for reset_client."""
    return _CLIENT.set(dict(client) if isinstance(client,dict) else None)
def reset_client(token):
    try:_CLIENT.reset(token)
    except Exception:pass
def current_client():
    return _CLIENT.get()
def client_label(client=None):
    c=current_client() if client is None else client
    return str((c or {}).get("label") or "LOYA AI")
def register_reason_hook(fn):
    """fn(client) -> the agent's latest stated reason (its last words before the tool call), shown on approval prompts."""
    if fn not in _client_reason_hooks:_client_reason_hooks.append(fn)
def _client_reason(client):
    for fn in list(_client_reason_hooks):
        try:
            r=fn(client)
            if r:return " ".join(str(r).split())[:400]
        except Exception:pass
    return ""
APPROVAL_TIMEOUT=180
_APPROVAL_KEEP=50
_approvals={}
_approvals_lock=threading.Lock()
def _public_approval(rec):
    return {k:rec[k] for k in ("id","tool","key","entity","action","summary","state","created","expires","client","reason") if k in rec}
def request_approval(tool_name,summary="",timeout=None,reason=None,labels=None):
    """Block the calling tool thread until the operator answers in the app. Returns approved, approved_session, denied or expired.
    labels=(entity,action) names a request that is not an AI Roles tool (an external agent's own built-in tool); those
    have no permission key, so "Allow for this session" cannot widen anything for them."""
    key=permission_key(tool_name)
    entity,action=PERMISSION_LABELS.get(key,("",""))
    if labels and not key:entity,action=labels
    timeout=APPROVAL_TIMEOUT if timeout is None else timeout
    now=time.time()
    client=current_client()
    if reason is None:reason=_client_reason(client) if client else ""
    try:
        from Cores.Services import terminal_service as _term
        reason=_term.redact_secrets(reason)[0]
    except Exception:pass
    rec={"id":"apr"+uuid.uuid4().hex[:12],"tool":tool_name,"key":key,"entity":entity,"action":action,"summary":summary,"state":"pending","created":now,"expires":now+timeout,"client":client_label(client),"reason":reason or "","_client_id":(client or {}).get("id"),"_event":threading.Event()}
    with _approvals_lock:
        done=[k for k,v in _approvals.items() if v["state"]!="pending"]
        for k in done[:max(0,len(_approvals)-_APPROVAL_KEEP)]:_approvals.pop(k,None)
        _approvals[rec["id"]]=rec
    rec["_event"].wait(timeout)
    with _approvals_lock:
        if rec["state"]=="pending":rec["state"]="expired"
        return rec["state"]
def cancel_client_approvals(client_id):
    """Deny every pending request from one client (an external agent that was stopped or killed)."""
    if not client_id:return 0
    with _approvals_lock:
        recs=[r for r in _approvals.values() if r["state"]=="pending" and r.get("_client_id")==client_id]
        for r in recs:r["state"]="denied"
    for r in recs:r["_event"].set()
    return len(recs)
def pending_approvals():
    with _approvals_lock:
        return [_public_approval(r) for r in _approvals.values() if r["state"]=="pending"]
def resolve_approval(approval_id,decision):
    decision=str(decision or "").strip().lower()
    if decision not in ("once","session","deny"):raise ValueError("decision must be once, session or deny")
    with _approvals_lock:
        rec=_approvals.get(str(approval_id or ""))
        if rec is None or rec["state"]!="pending":return False
        rec["state"]={"once":"approved","session":"approved_session","deny":"denied"}[decision]
    if decision=="session" and rec.get("key"):grant_session(rec["key"])
    rec["_event"].set()
    return True
_SUMMARY_TYPES=(str,int,float,bool,list,dict,tuple,type(None))
_SECRET_ARG_KEY_RX=__import__("re").compile(r"pass|pwd|secret|token|hash|ntlm|cookie|cred|api[ _-]?key|private[ _-]?key|ssh[ _-]?key|session[ _-]?(id|key)|bearer",__import__("re").I)
def _mask_secret_keys(v):
    """{"Password": "x"} -> {"Password": "[redacted]"} at any depth: target values and similar maps name their secrets by key."""
    if isinstance(v,dict):return {k:("[redacted]" if _SECRET_ARG_KEY_RX.search(str(k)) and isinstance(x,(str,int,float)) and str(x).strip() else _mask_secret_keys(x)) for k,x in v.items()}
    if isinstance(v,list):return [_mask_secret_keys(x) for x in v]
    return v
def summarize_args(args):
    if not isinstance(args,dict):return ""
    parts=[]
    # Approval prompts and the audit log show resolved commands: live-target secret values are masked before anything is cut.
    try:
        from Cores.Services import mcp_local_service as _mcp_local
        secrets=_mcp_local.live_secret_values();mask=lambda t:_mcp_local.mask_live_secrets(t,secrets)
    except Exception:mask=lambda t:t
    for k,v in args.items():
        if k.startswith("_") or not isinstance(v,_SUMMARY_TYPES) or v in ("",None) or v==[] or v=={}:continue
        if isinstance(v,(dict,list)):v=_mask_secret_keys(v)
        text=v if isinstance(v,str) else json.dumps(v,ensure_ascii=False,default=str)
        text=mask(" ".join(str(text).split()))
        parts.append(f"{k}={text[:120]+('…' if len(text)>120 else '')}")
    out="; ".join(parts)[:400]
    try:
        from Cores.Services import terminal_service as _term
        out=_term.redact_secrets(out)[0]
    except Exception:pass
    return out
def log_activity(tool_name,outcome,summary="",success=True):
    client=current_client()
    who=""
    if client:who=f"[{client_label(client)}"+(f" session {client.get('session_id')}" if client.get("session_id") else "")+"] "
    try:
        from Cores.Services import security_service as _security
        return _security.log_audit_event("ai_tool",f"{who}{tool_name} - {outcome}"+(f" - {summary}" if summary else ""),success)
    except Exception:
        return None
def activity(limit=50):
    try:
        from Cores.Services import security_service as _security
        rows=_security.list_audit_events(1000)
    except Exception:
        return []
    try:limit=max(1,min(500,int(limit)))
    except Exception:limit=50
    return [r for r in rows if r.get("event")=="ai_tool"][:limit]
class AIPermissionError(PermissionError):pass
def authorize(tool_name,args=None,defer_ask=False,force_ask=False):
    """The single server-side gate every AI tool goes through. Raises AIPermissionError when the call may not run.
    Returns 'allow', or 'ask' when defer_ask is set and the caller hands the approval to its own queue (terminal_run)."""
    summary=summarize_args(args)
    lvl=tool_decision(tool_name)
    if force_ask and lvl=="allow":lvl="ask"
    if permission_key(tool_name) is None:
        log_activity(tool_name,"blocked - not covered by AI Roles",summary,False)
        raise AIPermissionError(f"'{tool_name}' is not covered by AI Roles, so it is blocked.")
    entity,action=PERMISSION_LABELS[permission_key(tool_name)]
    if lvl=="deny":
        log_activity(tool_name,"denied by AI Roles",summary,False)
        raise AIPermissionError(f"AI permission {entity} > {action} is set to Deny. The operator can change it in Settings > AI > Roles.")
    if lvl=="ask" and not defer_ask:
        outcome=request_approval(tool_name,summary)
        if outcome not in ("approved","approved_session"):
            log_activity(tool_name,"declined by the operator" if outcome=="denied" else "approval timed out",summary,False)
            raise AIPermissionError(f"The operator did not approve {entity} > {action} ('{tool_name}')." if outcome=="denied" else f"No one approved {entity} > {action} ('{tool_name}') in time.")
        log_activity(tool_name,"approved for this session" if outcome=="approved_session" else "approved once",summary,True)
        return "allow"
    log_activity(tool_name,"allowed" if lvl=="allow" else "sent to the terminal approval queue",summary,True)
    return lvl
