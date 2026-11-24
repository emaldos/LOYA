"""Child process that drives one Claude Agent turn through the official Claude Agent SDK (claude-agent-sdk).

Started by ext_agents_service with `python -I` and a minimal environment (the API key arrives only as an environment
variable). Protocol, one JSON object per line:
  stdin : first line = the job (options + prompt); later lines = {"t":"permission_reply","id","allow","message"}
  stdout: {"t":"init"|"delta"|"text"|"tool"|"usage"|"permission"|"result"|"commands"|"error", ...}
Nothing here decides permissions: built-in tool requests are forwarded to LOYA (can_use_tool) and LOYA's own tools are
checked by LOYA's MCP server.
"""
import sys,json,asyncio,threading,uuid
_out_lock=threading.Lock()
def emit(obj):
    line=json.dumps(obj,default=str)
    with _out_lock:
        sys.stdout.write(line+"\n")
        sys.stdout.flush()
def build_options(sdk,job,can_use_tool=None):
    kw=dict(
        tools=list(job.get("tools") or []),
        allowed_tools=list(job.get("allowed_tools") or []),
        disallowed_tools=list(job.get("disallowed_tools") or []),
        mcp_servers=job.get("mcp_config") or {},
        strict_mcp_config=True,
        permission_mode="default",
        max_turns=int(job.get("max_turns") or 8),
        max_budget_usd=float(job.get("max_budget_usd") or 1.0),
        model=job.get("model") or None,
        effort=job.get("effort") or None,
        cwd=job.get("cwd"),
        setting_sources=list(job.get("setting_sources") or []),
        system_prompt=job.get("system_prompt") or None,
        include_partial_messages=True,
        client_app=job.get("client_app") or None,
    )
    if can_use_tool is not None:kw["can_use_tool"]=can_use_tool
    if job.get("settings"):kw["settings"]=job["settings"]
    if job.get("sandbox"):kw["sandbox"]=job["sandbox"]
    if job.get("resume"):kw["resume"]=job["resume"]
    return sdk.ClaudeAgentOptions(**kw)
class Bridge:
    """Permission round-trips with the parent over stdin/stdout."""
    def __init__(self,loop):
        self.loop=loop
        self.pending={}
    def start_reader(self,stream):
        def run():
            for raw in stream:
                try:msg=json.loads(raw)
                except Exception:continue
                if isinstance(msg,dict) and msg.get("t")=="permission_reply":
                    fut=self.pending.pop(str(msg.get("id")),None)
                    if fut is not None:self.loop.call_soon_threadsafe(lambda f=fut,m=msg:f.done() or f.set_result(m))
            for fut in list(self.pending.values()):
                self.loop.call_soon_threadsafe(lambda f=fut:f.done() or f.set_result({"allow":False,"message":"LOYA closed the request."}))
        threading.Thread(target=run,daemon=True).start()
    async def ask(self,tool,tool_input):
        pid=uuid.uuid4().hex[:12]
        fut=self.loop.create_future()
        self.pending[pid]=fut
        emit({"t":"permission","id":pid,"tool":tool,"input":tool_input})
        return await fut
def make_can_use_tool(sdk,bridge):
    from claude_agent_sdk.types import PermissionResultAllow,PermissionResultDeny
    async def can_use_tool(tool_name,tool_input,context):
        reply=await bridge.ask(tool_name,tool_input if isinstance(tool_input,dict) else {})
        if reply.get("allow"):return PermissionResultAllow(updated_input=tool_input)
        return PermissionResultDeny(message=str(reply.get("message") or "Denied by LOYA."),interrupt=False)
    return can_use_tool
def handle_message(sdk,msg,seen_usage):
    """Map one SDK message to protocol events. Returns True once the turn's result has arrived."""
    if isinstance(msg,sdk.SystemMessage):
        if msg.subtype=="init":
            d=msg.data or {}
            servers=[{"name":s.get("name"),"status":s.get("status")} for s in (d.get("mcp_servers") or []) if isinstance(s,dict)]
            emit({"t":"init","session_id":d.get("session_id"),"slash_commands":d.get("slash_commands") or [],"skills":d.get("skills") or [],"tools":d.get("tools") or [],"mcp_servers":servers,"model":d.get("model")})
        return False
    if isinstance(msg,sdk.ResultMessage):
        emit({"t":"result","session_id":msg.session_id,"is_error":bool(msg.is_error),"subtype":msg.subtype,"result":msg.result,"cost_usd":msg.total_cost_usd,"num_turns":msg.num_turns,"usage":msg.usage})
        return True
    stream_cls=getattr(sdk,"StreamEvent",None)
    if stream_cls is None:
        try:from claude_agent_sdk.types import StreamEvent as stream_cls
        except Exception:stream_cls=None
    if stream_cls is not None and isinstance(msg,stream_cls):
        ev=msg.event or {}
        if msg.parent_tool_use_id is None and ev.get("type")=="content_block_delta":
            delta=ev.get("delta") or {}
            if delta.get("type")=="text_delta" and delta.get("text"):emit({"t":"delta","text":delta["text"]})
        return False
    if isinstance(msg,sdk.AssistantMessage):
        sub=msg.parent_tool_use_id is not None
        for block in msg.content or []:
            if isinstance(block,sdk.TextBlock) and not sub:emit({"t":"text","text":block.text})
            elif isinstance(block,sdk.ToolUseBlock):emit({"t":"tool","name":block.name,"id":block.id,"input":block.input,"subagent":sub})
        mid=getattr(msg,"message_id",None)
        u=getattr(msg,"usage",None)
        if isinstance(u,dict) and (mid is None or mid not in seen_usage):
            if mid is not None:seen_usage.add(mid)
            emit({"t":"usage","input_tokens":int(u.get("input_tokens") or 0)+int(u.get("cache_creation_input_tokens") or 0),"output_tokens":int(u.get("output_tokens") or 0)})
    return False
async def run_job(sdk,job,stdin=None):
    loop=asyncio.get_running_loop()
    bridge=Bridge(loop)
    if stdin is not None:bridge.start_reader(stdin)
    if job.get("mode")=="discover":
        opts=build_options(sdk,job)
        async with sdk.ClaudeSDKClient(options=opts) as client:
            info=await client.get_server_info() or {}
            cmds=[c.get("name") for c in (info.get("commands") or []) if isinstance(c,dict) and c.get("name")]
            emit({"t":"commands","slash_commands":cmds})
        return
    opts=build_options(sdk,job,make_can_use_tool(sdk,bridge))
    seen=set()
    async with sdk.ClaudeSDKClient(options=opts) as client:
        await client.query(job.get("prompt") or "")
        async for msg in client.receive_response():
            handle_message(sdk,msg,seen)
def main():
    try:sys.stdout.reconfigure(encoding="utf-8")
    except Exception:pass
    first=sys.stdin.readline()
    try:job=json.loads(first)
    except Exception:
        emit({"t":"error","message":"bad job"});return 2
    try:
        import claude_agent_sdk as sdk
    except Exception as e:
        emit({"t":"error","message":f"claude-agent-sdk is not installed: {e}"});return 3
    try:
        asyncio.run(run_job(sdk,job,sys.stdin))
    except Exception as e:
        emit({"t":"error","message":f"{type(e).__name__}: {e}"})
        return 1
    return 0
if __name__=="__main__":
    sys.exit(main())
