import asyncio,json,threading,uuid,urllib.request,urllib.error
from mcp.server.mcpserver.exceptions import ToolError
from Cores.Services import ai_service as _ai_svc
from Cores.Services import semantic_search_service as _semantic_svc
from Cores.Bridge import mcp_server as _mcp_server
MAX_TOOL_ITERS=5
ANTHROPIC_MAX_TOKENS=16000
BASE_SYSTEM_PROMPT="""You are the AI assistant embedded in LOYA NG, a penetration-testing notes and command manager. You act through the provided tools - use them rather than only describing what you would do.

Rules for editing notes:
- notes_create/notes_update REPLACE the note's entire content. If the user asks you to ADD or APPEND something to a note that already exists, use notes_append instead - never call notes_update with content you don't already have, since it would erase everything else in the note.
- To include a runnable command block inside note content, first call notes_command_block_html with the command's details, then paste its returned HTML snippet directly into the content you send to notes_create/notes_update/notes_append. Never hand-write command block markup yourself - it uses an internal encoded format and will not work otherwise.
- tags fields are always a comma-separated string, e.g. "recon, web".

Rules for target placeholders:
- Commands use {PlaceholderName} tokens (e.g. {IPv4}, {Host}, {Port}, {URL}, {Username}, {Domain}) that get substituted with the active target's values.
- Before introducing a new placeholder name, call parameter_list to see what's already registered and reuse an existing name (matched case-insensitively) instead of creating a near-duplicate like {ip}/{IP}/{ipv4} for the same concept. Prefer the standard names above when none of the existing ones fit.

If you are unsure of the exact expected format for notes, commands, or targets data, call ai_prompt_template with the relevant kind before writing.
"""
_server=None
def _get_server():
    global _server
    if _server is None:_server=_mcp_server.build_server()
    return _server
def _list_tools():
    return asyncio.run(_get_server().list_tools())
def _returns_list(name):
    try:
        import typing
        tool=_get_server()._tool_manager.get_tool(name)
        ann=typing.get_type_hints(tool.fn).get("return") if tool is not None else None
        return ann is list or typing.get_origin(ann) is list
    except Exception:
        return False
def _call_tool(name,args):
    try:
        result=asyncio.run(_get_server().call_tool(name,args))
    except ToolError as e:
        return False,str(e)
    except Exception as e:
        return False,str(e)
    texts=[c.text for c in result.content if hasattr(c,"text")]
    if getattr(result,"is_error",False):return False,"\n".join(texts) or f"{name} failed."
    sc=result.structured_content
    if isinstance(sc,dict) and set(sc.keys())=={"result"}:return True,sc["result"]
    if sc is not None:return True,sc
    # Without an output schema the SDK sends a list as one text block per item, so a one-item list looked like a single object
    # (and an empty list like nothing). The tool's declared return type says which it was.
    if _returns_list(name):
        out=[]
        for t in texts:
            try:out.append(json.loads(t))
            except Exception:out.append(t)
        return True,out
    if len(texts)==1:
        try:return True,json.loads(texts[0])
        except Exception:return True,texts[0]
    out=[]
    for t in texts:
        try:out.append(json.loads(t))
        except Exception:out.append(t)
    return True,out
def _tools_openai_format():
    return [{"type":"function","function":{"name":t.name,"description":t.description or "","parameters":t.input_schema}} for t in _list_tools()]
def _tools_anthropic_format():
    return [{"name":t.name,"description":t.description or "","input_schema":t.input_schema} for t in _list_tools()]
def _http_error_text(e):
    try:raw=e.read().decode("utf-8","replace")
    except Exception:raw=""
    msg=""
    try:
        d=json.loads(raw)
        err=d.get("error") if isinstance(d,dict) else None
        if isinstance(err,dict):msg=str(err.get("message") or err.get("type") or "")
        elif err:msg=str(err)
        elif isinstance(d,dict):msg=str(d.get("message") or "")
    except Exception:msg=raw.strip()[:300]
    hint={401:" Check the API key.",403:" Check the API key and its permissions.",404:" Check the base URL and the model name.",429:" Rate limited - wait and retry."}.get(e.code,"")
    return f"HTTP {e.code} from the provider"+(f": {msg}" if msg else ".")+hint
def _open(req,timeout):
    try:return urllib.request.urlopen(req,timeout=timeout)
    except urllib.error.HTTPError as e:raise RuntimeError(_http_error_text(e)) from None
    except urllib.error.URLError as e:raise RuntimeError(f"Could not reach {req.full_url}: {e.reason}") from None
def _http_post_json(url,body,headers=None,timeout=120):
    data=json.dumps(body).encode("utf-8")
    hdrs={"Content-Type":"application/json"}
    hdrs.update(headers or {})
    req=urllib.request.Request(url,data=data,headers=hdrs,method="POST")
    with _open(req,timeout) as resp:
        return json.loads(resp.read().decode("utf-8","replace"))
def _http_post_sse_lines(url,body,headers=None,timeout=120):
    data=json.dumps(body).encode("utf-8")
    hdrs={"Content-Type":"application/json","Accept":"text/event-stream"}
    hdrs.update(headers or {})
    req=urllib.request.Request(url,data=data,headers=hdrs,method="POST")
    with _open(req,timeout) as resp:
        for raw_line in resp:
            yield raw_line.decode("utf-8","replace").rstrip("\r\n")
def _to_openai_messages(history):
    out=[]
    for turn in history:
        role=turn["role"]
        if role=="tool":
            out.append({"role":"tool","tool_call_id":turn.get("tool_call_id",""),"content":turn.get("content","")})
        elif role=="assistant" and turn.get("tool_calls"):
            out.append({"role":"assistant","content":turn.get("content") or None,"tool_calls":turn["tool_calls"]})
        else:
            out.append({"role":role,"content":turn.get("content","")})
    return out
def _chat_openai_compatible_turn(url,body,headers,on_delta):
    content_acc=""
    tool_calls_acc={}
    for line in _http_post_sse_lines(url,body,headers=headers):
        if not line.startswith("data:"):continue
        payload=line[5:].strip()
        if payload=="[DONE]" or not payload:continue
        try:chunk=json.loads(payload)
        except Exception:continue
        choice=(chunk.get("choices") or [{}])[0]
        delta=choice.get("delta") or {}
        if delta.get("content"):
            content_acc+=delta["content"]
            if on_delta:on_delta(delta["content"])
        for tc in delta.get("tool_calls") or []:
            idx=tc.get("index",0)
            slot=tool_calls_acc.setdefault(idx,{"id":"","type":"function","function":{"name":"","arguments":""}})
            if tc.get("id"):slot["id"]=tc["id"]
            fn=tc.get("function") or {}
            if fn.get("name"):slot["function"]["name"]+=fn["name"]
            if fn.get("arguments"):slot["function"]["arguments"]+=fn["arguments"]
    tool_calls=[tool_calls_acc[i] for i in sorted(tool_calls_acc)]
    return content_acc,tool_calls
def chat_openai_compatible(base_url,model,history,headers=None,on_delta=None,on_status=None,system_context=None):
    tools=_tools_openai_format()
    url=base_url.rstrip("/")+"/v1/chat/completions"
    for _ in range(MAX_TOOL_ITERS):
        streaming=on_delta is not None
        messages=_to_openai_messages(history)
        if system_context:messages=[{"role":"system","content":system_context}]+messages
        body={"model":model,"messages":messages,"stream":streaming}
        if tools:body["tools"]=tools
        try:
            if streaming:
                msg_content,tool_calls=_chat_openai_compatible_turn(url,body,headers,on_delta)
            else:
                data=_http_post_json(url,body,headers=headers)
                msg=(data.get("choices") or [{}])[0].get("message",{})
                tool_calls=msg.get("tool_calls") or []
                msg_content=msg.get("content") or ""
        except RuntimeError as e:
            if not tools or "support tools" not in str(e).lower():raise
            tools=None
            if on_status:on_status(f"{model} has no tool support - answering without app tools…")
            continue
        if not tool_calls:
            history.append({"role":"assistant","content":msg_content if msg_content.strip() else "(The model returned an empty reply.)"})
            return history
        history.append({"role":"assistant","content":msg_content or None,"tool_calls":tool_calls})
        for tc in tool_calls:
            fn=tc.get("function",{})
            name=fn.get("name","")
            if on_status:on_status(f"Using tool: {name}…")
            try:args=json.loads(fn.get("arguments") or "{}")
            except Exception:args={}
            ok,result=_call_tool(name,args)
            history.append({"role":"tool","tool_call_id":tc.get("id",""),"tool_name":name,"content":json.dumps(result) if ok else f"Error: {result}"})
    history.append({"role":"assistant","content":"(stopped after too many tool calls)"})
    return history
def _to_anthropic_messages(history):
    out=[]
    for turn in history:
        role=turn["role"]
        if role=="tool":
            out.append({"role":"user","content":[{"type":"tool_result","tool_use_id":turn.get("tool_call_id",""),"content":turn.get("content","")}]})
        elif role=="assistant" and turn.get("tool_calls"):
            blocks=[dict(b) for b in (turn.get("thinking") or []) if isinstance(b,dict)]
            if turn.get("content"):blocks.append({"type":"text","text":turn["content"]})
            for tc in turn["tool_calls"]:
                blocks.append({"type":"tool_use","id":tc["id"],"name":tc["name"],"input":tc.get("input",{})})
            out.append({"role":"assistant","content":blocks})
        elif role=="assistant" and not (turn.get("content") or "").strip():
            continue
        else:
            out.append({"role":role,"content":turn.get("content","")})
    return out
def _chat_anthropic_turn(url,body,headers,on_delta):
    blocks={}
    meta={"stop_reason":None}
    for line in _http_post_sse_lines(url,body,headers=headers):
        if not line.startswith("data:"):continue
        payload=line[5:].strip()
        if not payload:continue
        try:evt=json.loads(payload)
        except Exception:continue
        etype=evt.get("type")
        if etype=="content_block_start":
            idx=evt.get("index",0)
            cb=evt.get("content_block") or {}
            blocks[idx]={"type":cb.get("type"),"text":cb.get("text",""),"partial_json":"","id":cb.get("id"),"name":cb.get("name"),"thinking":cb.get("thinking",""),"signature":cb.get("signature",""),"data":cb.get("data")}
        elif etype=="content_block_delta":
            idx=evt.get("index",0)
            slot=blocks.setdefault(idx,{"type":"text","text":"","partial_json":"","id":None,"name":None,"thinking":"","signature":"","data":None})
            d=evt.get("delta") or {}
            if d.get("type")=="text_delta":
                chunk=d.get("text","")
                slot["text"]+=chunk
                if on_delta and chunk:on_delta(chunk)
            elif d.get("type")=="input_json_delta":
                slot["partial_json"]+=d.get("partial_json","")
            elif d.get("type")=="thinking_delta":
                slot["thinking"]+=d.get("thinking","")
            elif d.get("type")=="signature_delta":
                slot["signature"]+=d.get("signature","")
        elif etype=="message_delta":
            meta["stop_reason"]=(evt.get("delta") or {}).get("stop_reason") or meta["stop_reason"]
        elif etype=="error":
            err=evt.get("error") or {}
            raise RuntimeError("Provider error: "+str(err.get("message") or err.get("type") or "unknown"))
        elif etype=="message_stop":
            break
    blocks_sorted=[blocks[i] for i in sorted(blocks)]
    text="".join(b["text"] for b in blocks_sorted if b["type"]=="text")
    tool_uses=[]
    for b in blocks_sorted:
        if b["type"]=="tool_use":
            try:inp=json.loads(b["partial_json"] or "{}")
            except Exception:inp={}
            tool_uses.append({"id":b["id"],"name":b["name"],"input":inp})
    return text,tool_uses,_thinking_blocks(blocks_sorted),meta["stop_reason"]
def _thinking_blocks(blocks):
    out=[]
    for b in blocks:
        if b.get("type")=="thinking":out.append({"type":"thinking","thinking":b.get("thinking",""),"signature":b.get("signature","")})
        elif b.get("type")=="redacted_thinking":out.append({"type":"redacted_thinking","data":b.get("data")})
    return out
def _stop_note(stop_reason):
    if stop_reason=="refusal":return "(The model declined this request.)"
    if stop_reason=="max_tokens":return "(The reply hit the token limit before it finished.)"
    return "(The model returned an empty reply.)"
def chat_anthropic(base_url,model,history,api_key,on_delta=None,on_status=None,system_context=None):
    tools=_tools_anthropic_format()
    headers={"x-api-key":api_key,"anthropic-version":"2023-06-01"}
    url=base_url.rstrip("/")+"/v1/messages"
    for _ in range(MAX_TOOL_ITERS):
        streaming=on_delta is not None
        body={"model":model,"max_tokens":ANTHROPIC_MAX_TOKENS,"messages":_to_anthropic_messages(history),"tools":tools,"stream":streaming}
        if system_context:body["system"]=system_context
        if streaming:
            text,tool_uses,thinking,stop_reason=_chat_anthropic_turn(url,body,headers,on_delta)
        else:
            data=_http_post_json(url,body,headers=headers)
            blocks_data=data.get("content") or []
            tool_uses=[{"id":b["id"],"name":b["name"],"input":b.get("input",{})} for b in blocks_data if b.get("type")=="tool_use"]
            text="".join(b.get("text","") for b in blocks_data if b.get("type")=="text")
            thinking=_thinking_blocks(blocks_data)
            stop_reason=data.get("stop_reason")
        if not tool_uses:
            history.append({"role":"assistant","content":text if text.strip() else _stop_note(stop_reason)})
            return history
        turn={"role":"assistant","content":text,"tool_calls":tool_uses}
        if thinking:turn["thinking"]=thinking
        history.append(turn)
        for b in tool_uses:
            if on_status:on_status(f"Using tool: {b['name']}…")
            ok,result=_call_tool(b["name"],b.get("input",{}))
            history.append({"role":"tool","tool_call_id":b["id"],"tool_name":b["name"],"content":json.dumps(result) if ok else f"Error: {result}"})
    history.append({"role":"assistant","content":"(stopped after too many tool calls)"})
    return history
def _first_ollama_model():
    r=_ai_svc.test_ollama()
    models=r.get("models") or []
    if not models:raise ValueError("No Ollama models available. Pull a model first.")
    return models[0]
def _first_lmstudio_model():
    r=_ai_svc.test_lmstudio()
    models=r.get("models") or []
    if not models:raise ValueError("No LM Studio models available.")
    return models[0]
def send_message(provider_kind,history,text,on_delta=None,on_status=None,user_meta=None):
    history=[dict(t) for t in (history or [])]
    text=(text or "").strip()
    if not text:raise ValueError("Message is required.")
    turn={"role":"user","content":text}
    if isinstance(user_meta,dict):turn.update({k:v for k,v in user_meta.items() if k in ("display","attachments")})
    history.append(turn)
    providers=_ai_svc.get_providers()
    cfg=providers.get(provider_kind)
    if provider_kind=="mcp":raise ValueError("An MCP server only provides tools, it cannot answer chat messages. Enable API, Ollama or LM Studio in Settings and pick it in the AI panel.")
    if not cfg or not cfg["enabled"]:raise ValueError("That AI provider is not enabled. Turn it on in Settings > Extensions > AI.")
    try:
        rag_context=_semantic_svc.build_context_for_query(text)
    except Exception:
        rag_context=None
    system_context=BASE_SYSTEM_PROMPT+("\n\n"+rag_context if rag_context else "")
    if provider_kind=="ollama":
        base_url=f"http://{cfg['host']}:{cfg['port']}"
        model=cfg.get("model") or _first_ollama_model()
        return chat_openai_compatible(base_url,model,history,on_delta=on_delta,on_status=on_status,system_context=system_context)
    if provider_kind=="lmstudio":
        base_url=f"http://{cfg['host']}:{cfg['port']}"
        model=cfg.get("model") or _first_lmstudio_model()
        return chat_openai_compatible(base_url,model,history,on_delta=on_delta,on_status=on_status,system_context=system_context)
    if provider_kind=="api":
        if not cfg["api_key"]:raise ValueError("No API key configured. Add one in Settings > Extensions > AI > API.")
        kind=cfg["provider_kind"]
        base_url=cfg["base_url"] or _ai_svc._DEFAULT_API_BASE_URLS.get(kind,"")
        if not base_url:raise ValueError("No base URL configured.")
        model=cfg["model"] or ("claude-sonnet-5" if kind=="anthropic" else "gpt-4o")
        if kind=="anthropic":return chat_anthropic(base_url,model,history,cfg["api_key"],on_delta=on_delta,on_status=on_status,system_context=system_context)
        return chat_openai_compatible(base_url,model,history,headers={"Authorization":f"Bearer {cfg['api_key']}"},on_delta=on_delta,on_status=on_status,system_context=system_context)
    raise ValueError("Chat is not supported for this provider type yet.")
_streams={}
_streams_lock=threading.Lock()
def start_stream(provider_kind,history,text,user_meta=None):
    stream_id=uuid.uuid4().hex[:16]
    buf={"text":"","status":"","done":False,"error":None,"history":None}
    with _streams_lock:_streams[stream_id]=buf
    def on_delta(chunk):
        with _streams_lock:buf["text"]+=chunk
    def on_status(msg):
        with _streams_lock:buf["status"]=msg
    def run():
        try:
            result_history=send_message(provider_kind,list(history),text,on_delta=on_delta,on_status=on_status,user_meta=user_meta)
            with _streams_lock:
                buf["history"]=result_history
                buf["done"]=True
        except Exception as e:
            with _streams_lock:
                buf["error"]=str(e)
                buf["done"]=True
    threading.Thread(target=run,daemon=True).start()
    return stream_id
def poll_stream(stream_id):
    with _streams_lock:
        buf=_streams.get(stream_id)
        if buf is None:return {"text":"","status":"","done":True,"error":"Unknown or already-consumed stream."}
        out={"text":buf["text"],"status":buf["status"],"done":buf["done"],"error":buf["error"]}
        if buf["done"]:
            out["history"]=buf["history"]
            del _streams[stream_id]
        return out
def abort_stream(stream_id):
    with _streams_lock:
        _streams.pop(stream_id,None)
    return True
